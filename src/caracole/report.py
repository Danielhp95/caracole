"""The run summary: what ``caracole run`` prints on stdout, and sends to ntfy, in words.

Each step of the run (pipeline.py) hands back a ``StepResult``: what it did,
counted; the songs a provider's error left for the next run; what only you can
do; what else went wrong. ``summary`` turns a run's results into a short report:

- the most pressing thing only you can do comes first ("First, build the index
  once: …"), said once however many steps wait for it;
- then one line per step that did something; a step with nothing to do is left
  out;
- then what needs you, the problems (one line per provider and cause, with the
  count of the songs it left for the next run), the requests against each
  budget, and how long the run took.

Every line has a level, logging's: ``quiet`` keeps the lines that need you or
say what went wrong. The words are the same wherever they go (``render``):
plain for ntfy, a pipe or a file; coloured on a terminal; prefixed with their
syslog priority for the journal.

The words are people's: providers by their own names (``provider_name``, from
logs.py, which the log shares), songs as "Artist – Title", and ``why``, a
provider's error as a clause without its URL ("didn't answer (HTTP 503)").
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from caracole.logs import PROVIDER_NAMES as PROVIDER_NAMES  # the log's names, which the report shares
from caracole.logs import priority, provider_name
from caracole.normalize import clean_title

INFO, WARNING, ERROR = logging.INFO, logging.WARNING, logging.ERROR


class _Song(Protocol):
    artist: str
    title: str


def song_name(song: _Song) -> str:
    """A song as the summary and the log show it: "Artist – Title", the title without its version suffix."""
    return f"{song.artist.strip()} – {clean_title(song.title)}"


def plural(n: int, noun: str, many: str | None = None) -> str:
    return f"{n} {noun if n == 1 else (many or noun + 's')}"


def when(dt: datetime | None) -> str:
    """A time as the to-do page shows it, in UTC; a naive time is UTC already."""
    if dt is None:
        return "?"
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def duration(seconds: float) -> str:
    if seconds < 1:
        return "less than a second"
    total = round(seconds)
    if total < 60:
        return f"{total} s"
    if total < 3600:
        minutes, rest = divmod(total, 60)
        return f"{minutes} min" + (f" {rest} s" if rest else "")
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    return f"{hours} h" + (f" {minutes} min" if minutes else "")


def _network_error(error: BaseException) -> BaseException | None:
    """The httpx error a ProviderError was raised for, if any: PoliteClient raises one while handling it."""
    import httpx

    seen: set[int] = set()
    e: BaseException | None = error
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, httpx.TransportError):
            return e
        e = e.__cause__ or e.__context__
    return None


STOPPED = "kept failing and caracole stopped asking it"  # why, once the client gave up on a provider


def why(error: BaseException) -> str:
    """What a provider did, as the clause after its name: "didn't answer (HTTP 503)".

    Never its URL or the raw status line: those are in the log at -v.
    """
    import httpx

    from caracole.http import ProviderBlocked, ProviderUnavailable, RobotsClosed

    if isinstance(error, ProviderBlocked):
        return f"blocked caracole ({error.message})" if error.message else "blocked caracole"
    if isinstance(error, ProviderUnavailable):
        return STOPPED
    if isinstance(error, RobotsClosed):
        return "closes that page to bots (robots.txt)"
    network = _network_error(error)
    if network is not None:
        return "didn't answer in time" if isinstance(network, httpx.TimeoutException) else "couldn't be reached"
    if isinstance(error.__cause__, TimeoutError):  # a program stopped after its timeout (yt-dlp, youtube.py)
        return "didn't answer in time"
    status = getattr(error, "status", None)
    if isinstance(status, int):
        if status in (502, 503, 504):
            return f"didn't answer (HTTP {status})"
        if status >= 500:
            return f"had an error (HTTP {status})"
        if status >= 400:
            return f"refused the request (HTTP {status})"
        if status >= 300:
            return "redirected caracole somewhere it doesn't follow"
    return "sent an answer caracole couldn't read"


# --- what a step hands back ------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    """Something only you can do. ``text`` follows "First, " when it leads; the lowest ``rank`` leads."""

    text: str
    detail: str = ""
    rank: int = 50


def sentence(action: Action) -> str:
    """An action as a sentence of its own, the way the summary ends with it and an alert says it."""
    return f"{action.text[:1].upper()}{action.text[1:]}." + (f" {action.detail}" if action.detail else "")


@dataclass(frozen=True)
class Problem:
    """Something that went wrong, as a sentence of its own."""

    text: str
    level: int = WARNING


@dataclass(frozen=True)
class Failure:
    """A song a provider's error left for the next run."""

    provider: str
    song: str
    cause: str

    @classmethod
    def of(cls, song: _Song, error: BaseException) -> Failure:
        return cls(str(getattr(error, "provider", "?")), song_name(song), why(error))


@dataclass(frozen=True)
class NeedsYou:
    """How many things the to-do page lists for you, and where it is."""

    count: int
    page: Path


@dataclass
class StepResult:
    """What one step of ``caracole run`` did, for the summary. A step returns one.

    ``title`` names the step's line, which says what it ``done``, counted ("3
    found"); a step that did nothing has no line. ``failures`` are the songs a
    provider's error left for the next run, and ``retry`` says what happens to
    them, with ``{songs}`` for "1 song" (or a song's name, in the log): the
    summary gives the songs of one provider and one cause one line. ``actions``
    are what only you can do; ``problems`` what else went wrong; ``spent`` the
    providers whose budget ran out; ``todo`` what the to-do page lists for you.
    ``status`` is the step's line for the log at -v and for kv ``run:last``.
    """

    title: str = ""
    done: list[str] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    retry: str = "{songs} will be tried again on the next run"
    actions: list[Action] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    spent: list[str] = field(default_factory=list)
    todo: NeedsYou | None = None
    status: str = "ok"


def failure_line(failure: Failure, retry: str, songs: str) -> str:
    """The line for the songs one cause left: "LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song
    will be tried again on the next run."."""
    return f"{provider_name(failure.provider)} {failure.cause}, so {retry.format(songs=songs)}."


# --- the words for what the run itself sees --------------------------------------------------

BUILD_INDEX = Action(
    "build the index once: caracole index build (about 10 minutes)",
    "Until then, no song is matched or looked for on Ultimate Guitar.",
    rank=10,
)
FINISH_INDEX = Action(
    "finish the index: caracole index build, or let the nightly refresh read the rest",
    "Until then, no song is matched, so nothing Ultimate Guitar has is taken for missing.",
    rank=25,
)


def fix_overrides(error: object) -> Action:
    return Action(f"fix overrides.toml: {error}",
                  "Nothing else ran, as every step reads it; the to-do page leads with the error.", rank=0)


def unreadable_wanted(errors: Iterable[str]) -> Action:
    return Action(f"fix wanted.txt, which caracole can't read: {'; '.join(errors)}",
                  "The songs it read before are still looked for.", rank=20)


def spotify_auth(message: str | None) -> Action:
    why_ = f"{message.strip()} " if message and message.strip() else ""
    return Action("authorize Spotify again: caracole auth spotify",
                  f"{why_}wanted.txt keeps working meanwhile.", rank=30)


def spotify_setup(message: str | None) -> Action:
    return Action(f"finish setting up Spotify: {(message or 'it is set up only in part').rstrip('.')}", rank=30)


def cooling(provider: str, until: datetime | None) -> Problem:
    return Problem(f"{provider_name(provider)} is cooling down after a block until {when(until)}, "
                   "so caracole leaves it alone this run.")


def blocked(error: Any, step: str, until: datetime | None, *, strikes: int) -> Problem:
    """A block: until when caracole leaves the provider alone. The ntfy alert says it in these words."""
    reason = error.message or (f"HTTP {error.status}" if error.status else "")
    reason = f" ({reason})" if reason else ""
    streak = f" ({strikes} blocks in a row)" if strikes > 1 else ""
    return Problem(f"{provider_name(error.provider)} blocked caracole{reason} during the {step} step, so caracole "
                   f"leaves it alone until {when(until)}{streak}. Nothing was marked not found.")


def step_error(error: Any, step: str) -> Problem:
    return Problem(f"{provider_name(error.provider)} {why(error)} during the {step} step, so the step will be "
                   "tried again on the next run.")


def bug(error: BaseException, step: str) -> Problem:
    return Problem(f"The {step} step failed: {type(error).__name__}: {error}. That's a bug in caracole: its "
                   "traceback is in the log, and the run exits 1.", ERROR)


# --- the summary ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    text: str
    level: int = INFO
    lead: bool = False


class _Report(Protocol):
    steps: Mapping[str, str]
    results: Mapping[str, StepResult]
    requests: Mapping[str, int]
    budgets: Mapping[str, int]
    seconds: float | None


def _results(report: _Report) -> list[StepResult]:
    """The steps' results in run order; a step that returned only a line of text shows it."""
    out = []
    for name in dict.fromkeys([*report.steps, *report.results]):
        result = report.results.get(name)
        if result is None:
            status = report.steps[name]
            result = StepResult(title=name, done=[] if status == "ok" else [status], status=status)
        out.append(result)
    return out


def _needs_you(todo: NeedsYou) -> str:
    if todo.count == 0:
        return "Nothing on your to-do page needs you."
    verb = "needs" if todo.count == 1 else "need"
    return f"{plural(todo.count, 'thing')} on your to-do page {verb} you: {todo.page}"


def _requests(report: _Report, spent: set[str]) -> str | None:
    if not report.requests:
        return None
    parts = []
    for provider, n in report.requests.items():
        budget = report.budgets.get(provider)
        part = f"{provider_name(provider)} {n}" + (f" of {budget}" if budget is not None else "")
        if provider in spent:
            part += " (used up: the rest waits for the next run)"
        parts.append(part)
    return f"Requests: {', '.join(parts)}."


def _groups(failures: list[Failure]) -> list[tuple[Failure, int]]:
    """The failures by provider and cause, in the order they came, each with its count of songs.

    The songs a client never asked about once it gave up on a provider (``STOPPED``) join
    the cause that made it give up, the provider's last one before: one cause, one line.
    """
    groups: dict[tuple[str, str], list[Failure]] = {}
    stopped: dict[str, tuple[str, str]] = {}  # provider -> the group its songs left unasked join
    for f in failures:
        key = (f.provider, f.cause)
        if f.cause == STOPPED:
            if f.provider not in stopped:
                earlier = [k for k in groups if k[0] == f.provider]
                stopped[f.provider] = key
                if earlier:
                    stopped[f.provider] = (f.provider, f"{earlier[-1][1]} and caracole stopped asking it")
                    groups[stopped[f.provider]] = groups.pop(earlier[-1])
            key = stopped[f.provider]
        groups.setdefault(key, []).append(f)
    return [(Failure(provider, group[0].song, cause), len(group)) for (provider, cause), group in groups.items()]


def _problems(results: list[StepResult]) -> list[Line]:
    """Each step's problems, then its failures, one line per provider and cause; errors first."""
    found: dict[str, Line] = {}
    for r in results:
        for p in r.problems:
            found.setdefault(p.text, Line(p.text, p.level))
        for failure, n in _groups(r.failures):
            text = failure_line(failure, r.retry, plural(n, "song"))
            found.setdefault(text, Line(text, WARNING))
    return sorted(found.values(), key=lambda line: -line.level)


def summary(report: _Report, *, quiet: bool = False) -> list[list[Line]]:
    """The run's summary, in blocks of lines; ``quiet`` keeps only what needs you or went wrong."""
    results = _results(report)
    actions = sorted(dict.fromkeys(a for r in results for a in r.actions), key=lambda a: a.rank)
    blocks: list[list[Line]] = []
    if actions:
        lead = actions[0]
        blocks.append([Line(f"First, {lead.text}.", WARNING, lead=True),
                       *([Line(lead.detail, WARNING)] if lead.detail else [])])
    blocks.append([Line(f"{r.title}: {', '.join(r.done)}.") for r in results if r.done])
    closing = [Line(sentence(a), WARNING) for a in actions[1:]]
    todo = next((r.todo for r in results if r.todo is not None), None)
    if todo is not None:
        closing.append(Line(_needs_you(todo)))
    closing += _problems(results)
    requests = _requests(report, {p for r in results for p in r.spent})
    if requests:
        closing.append(Line(requests))
    if report.seconds is not None:
        closing.append(Line(f"Took {duration(report.seconds)}."))
    blocks.append(closing)
    if quiet:
        blocks = [[line for line in block if line.level >= WARNING] for block in blocks]
    return [block for block in blocks if block]


# --- writing it out ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Style:
    """How the summary is written: plain, with colour (a terminal), or for the journal."""

    colour: bool = False
    journal: bool = False


PLAIN = Style()
JOURNAL = Style(journal=True)
_COLOURS = {ERROR: "\x1b[1;31m", WARNING: "\x1b[33m"}
_LEAD = "\x1b[1;33m"
_RESET = "\x1b[0m"


def render(blocks: list[list[Line]], style: Style) -> str:
    """The blocks as text, a blank line between them. For the journal, each line starts with its
    syslog priority and blank lines go: journald stores each line as an entry."""
    out: list[str] = []
    for i, block in enumerate(blocks):
        if i and not style.journal:
            out.append("")
        for line in block:
            if style.journal:
                out.append(f"<{priority(line.level)}>{line.text}")
            elif style.colour and (line.lead or line.level in _COLOURS):
                out.append(f"{_LEAD if line.lead else _COLOURS[line.level]}{line.text}{_RESET}")
            else:
                out.append(line.text)
    return "\n".join(out) + "\n" if out else ""


def summary_text(report: _Report, *, quiet: bool = False, style: Style = PLAIN) -> str:
    return render(summary(report, quiet=quiet), style)


def style_for(stream: Any, env: Mapping[str, str] | None = None) -> Style:
    """How to write the summary to ``stream``: for the journal under systemd, coloured on a terminal
    (unless ``$NO_COLOR``), else plain, as the log decides for stderr (logs.py)."""
    from caracole.logs import is_journal, wants_colour

    if is_journal(stream, env):
        return JOURNAL
    return Style(colour=True) if wants_colour(stream, env) else PLAIN


_COUNTED = re.compile(r"^## (.+) \((\d+)\)$", re.MULTILINE)
# Sections of the to-do page that only tell you something: caracole keeps at them by itself.
FOR_YOUR_INFORMATION = frozenset({"Partial sheets", "Missing lyrics", "Suggestions from your Spotify top tracks",
                                  "No human sheet found yet"})  # the last: what caracole takes from YouTube


def todo_count(page: str) -> int:
    """How many things a to-do page lists for you: the sum of its counted sections ("## Review (3)"),
    but for those that only tell you something (``FOR_YOUR_INFORMATION``)."""
    return sum(int(n) for title, n in _COUNTED.findall(page) if title not in FOR_YOUR_INFORMATION)
