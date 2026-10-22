"""What the requests page says of a request: the running one's steps, and how a finished one ended.

The library page's song lines keep status.py's ``Line``; the requests page (pages.py) reads that same
line and says it its own way, never from anything else than the job and what the library knows of its
song:

- **Steps** (``steps``), for the request that runs: a lookup's stages (get.py's ``STAGES``) as a few
  steps in plain words, Song, Match, Sheet, PDF, Lyrics, Guitar Pro (Ultimate Guitar's second pass,
  LaCuerda's and gtptabs.com's, from the first to the last) and Songbooks; a request of other commands,
  its commands, each by what it does ("Sheet" for ``caracole fetch``), else by its step's label. A step
  is running while one of its stages runs, or once some ran and others wait; done once all are over,
  failed when one failed. A step the request doesn't use is not drawn: the songbooks of a lookup that
  leaves them to a later job (``--no-songbooks``), and a step whose every stage ended skipped, with
  nothing to do for the song.
- **Outcome** (``outcome``), for one that is over: a word and its tone (Ready, Needs review, Not found,
  Not fetched yet, Failed, Removed, a songbook's Made, Deleted…: the line's), a reason in one sentence
  when there is one, from the job's stages and the song's state (``SongFacts``), and the next step
  (``Action``): a link, or a form posted with the form token. Ready opens its sheet; Needs review picks
  the match (its picker's page), or, with no candidates, opens the song on the library page; Not found,
  with a sheet or a Guitar Pro file the local indexes have elsewhere (``elsewhere``: LaCuerda's index,
  gtptabs.com's), gets it from there with the lookup the search's Get it runs; else, for a song the
  offline index didn't match, shows what ``caracole search`` finds for it (the picker's page,
  ``/review?song=ID``), also offered beside Get it from there (``Outcome.also``), and for any other,
  requests it by name (the library page's request form, filled in: ``/#q=Artist - Title``); Failed and
  Not fetched yet try again (``POST /jobs/again``: the same steps, queued again), a failed removal by
  asking what goes again (``POST /remove``, its question, as of now); a songbook made opens it. A
  request cancelled before it ran says so, Cancelled, with no next step: you took it out of the queue.

A reason is a site's own answer, worded for a person: a lookup's stage that ended in a wait or an error
says which site, what it answered and what waits ("LRCLIB answered 503: the lyrics wait for tonight's
run."); a Not found says Ultimate Guitar has no chords for it only when the fetch asked it
(``SongFacts.asked_ug``), and else, for a song the offline index didn't match, that the index doesn't
have it under this name; then what the indexes have elsewhere. A reason that can't be told from the job
is left out, never made up.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from caracole.get import GTPTABS_KEPT
from caracole.web.jobs import LACUERDA_READS, LOOKUP, REMOVING, Job, Stage
from caracole.web.status import Line, SongFacts

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.songs import Song

# A lookup's steps: a name in plain words, and the stages (get.STAGES) it stands for. "pages" (index.html
# written again) is no step of its own: the line above the steps says it while it runs.
LOOKUP_STEPS = (
    ("Song", ("song",)),
    ("Match", ("match",)),
    ("Sheet", ("sheet",)),
    ("PDF", ("pdf",)),
    ("Lyrics", ("lyrics",)),
    ("Guitar Pro", ("ug", "lacuerda", "gtptabs")),
    ("Songbooks", ("songbooks",)),
)
# A request of other commands: each command's step, by what it does; any other by its step's label.
COMMAND_STEPS = {"add": "Add", "match": "Match", "fetch": "Sheet", "render": "PDF", "review": "Your pick",
                 "remove": "Remove", "lacuerda": "LaCuerda", "songbook": "Songbook", LOOKUP: "Look it up"}
_OVER = ("done", "skipped", "failed")

# What a stage leaves for tonight's run, when it ends in a wait or an error: its name, and its verb.
_WHAT = {"sheet": ("the sheet", "waits"), "lyrics": ("the lyrics", "wait"),
         "ug": ("its other versions and guitar parts", "wait"), "lacuerda": ("LaCuerda's sheet", "waits"),
         "gtptabs": ("the Guitar Pro file", "waits")}
# How get.py words them (``_Lookup.asking``, ``_usable``).
_FAILED = re.compile(r"^(?P<site>.+?) failed \((?P<why>.*)\); the nightly run tries again$")
_STATUS = re.compile(r"^[\w.-]+: (\d{3})(?::|$)")  # http.ProviderError: "provider: status: url: message"
_BLOCKED = re.compile(r"^(?P<site>.+?) blocked caracole\b(?:.*?no more requests to it until (?P<until>.+?)\.(?:\s|$))?")
_COOLING = re.compile(r"^(?P<site>.+?) is cooling down after a block, until (?P<until>.+)$")
_SPENT = re.compile(r"^(?P<spent>.+); the nightly run does the rest$")

NO_CHORDS = "Ultimate Guitar has no chords for it"
NOT_INDEXED = "Not in the offline Ultimate Guitar index under this name"
NOT_ASKED = ("caracole didn't ask Ultimate Guitar this time (a cooldown, a block, a spent budget or an error: "
             "the output says which).")
IN_REVIEW = "caracole isn't sure which Ultimate Guitar song it is."
CANCELLED = "Taken out of the queue before it ran."
_ELSEWHERE = {"lacuerda": "LaCuerda has a sheet", "gtptabs": "gtptabs.com's index lists a page for it"}


@dataclass(frozen=True)
class Chip:
    """A step of the running request: its name, and waiting, running, done or failed."""

    name: str
    state: str


@dataclass(frozen=True)
class Action:
    """The next step: a link (``href``), or a form posted to ``post`` with ``fields`` and the form token."""

    label: str
    href: str | None = None
    post: str | None = None
    fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Outcome:
    """How a finished request ended: ``tone`` (status.py's), ``word``, ``reason`` ("" for none), ``action``,
    and ``also``, a second way on beside it."""

    tone: str
    word: str
    reason: str = ""
    action: Action | None = None
    also: Action | None = None


# --- the running request's steps ------------------------------------------------------------------------


def steps(job: Job) -> list[Chip]:
    """The request's steps, as the requests page draws the one that runs."""
    if job.stages:
        return _lookup_steps(job)
    chips = []
    for step in job.steps:
        if step.state == "skipped":
            continue
        name = COMMAND_STEPS.get(step.args[0] if step.args else "", step.label)
        chips.append(Chip(name, step.state if step.state in ("waiting", "running", "done", "failed") else "done"))
    return chips


def _lookup_steps(job: Job) -> list[Chip]:
    leaves_songbooks = any(step.args[:1] == (LOOKUP,) and "--no-songbooks" in step.args for step in job.steps)
    by_name = {stage.name: stage for stage in job.stages}
    chips = []
    for name, names in LOOKUP_STEPS:
        if name == "Songbooks" and leaves_songbooks:
            continue
        states = [by_name[n].state for n in names if n in by_name]
        state = _state(states)
        if state is not None:
            chips.append(Chip(name, state))
    return chips


def _state(states: list[str]) -> str | None:
    """A step's state from its stages'; None for a step not drawn (no stage, or every one skipped)."""
    if not states or all(s == "skipped" for s in states):
        return None
    if "running" in states:
        return "running"
    if all(s in _OVER for s in states):
        return "failed" if "failed" in states else "done"
    if any(s in _OVER for s in states):
        return "running"  # between two of its stages
    return "waiting"


# --- how a finished request ended ---------------------------------------------------------------------------


def outcome(job: Job, line: Line, facts: SongFacts | None = None, *, song_id: int | None = None) -> Outcome:
    """The request's outcome, read from its ``line`` (status.py's ``job_line``), its stages and ``facts``;
    ``song_id``: its song's, for the actions that name it."""
    again = Action("Try again", post="/jobs/again", fields=(("job", str(job.id)),))
    tone, text = line.tone, line.text
    if tone == "failed":
        if job.song_key.startswith(REMOVING):  # what goes is asked again, as of now: never removed unasked
            again = (Action("Try again", post="/remove", fields=(("song", str(job.song_id)),))
                     if job.song_id is not None else None)
        return Outcome("failed", "Failed", _sentence(text), again)
    if tone == "removed":
        return Outcome("removed", text)
    if tone == "cancelled":  # you took it out of the queue: asked for again from the library, never from here
        return Outcome("cancelled", text, CANCELLED)
    if tone == "ready":
        href = _href(line.link[1]) if line.link else None
        if text == "Ready":
            return Outcome("ready", "Ready", _waits(job.stages, after_sheet=True), Action("Open", href=href)
                           if href else None)
        return Outcome("ready", text, "", Action(line.link[0], href=href) if line.link and href else None)
    if tone == "review":
        picker = facts.picker if facts is not None else None
        action = Action("Pick the match", href=_href(picker)) if picker else _in_library(song_id)
        return Outcome("review", "Needs review", IN_REVIEW, action)
    word, _, rest = text.partition(": ")  # "Read: …", "Not read: …", "Added: the nightly run looks for it"
    if job.song_key.startswith(LACUERDA_READS):
        return Outcome(tone, word, _sentence(rest) if rest else "", again if tone == "waiting" else None)
    if tone == "missing":
        return _not_found(job, facts, song_id)
    if tone == "waiting":
        return Outcome("waiting", text, _waits(job.stages) or ("" if job.stages else NOT_ASKED), again)
    return Outcome(tone, word, _sentence(rest[:1].upper() + rest[1:]) if rest else "")


def _not_found(job: Job, facts: SongFacts | None, song_id: int | None) -> Outcome:
    """Not found: Ultimate Guitar has no chords for it once the fetch asked it, else, for a song the offline
    index didn't match, the index lacks it under this name; then what the lookup got elsewhere, or what the
    local indexes have elsewhere. A song the index didn't match goes on to what caracole search finds for
    it; any other, with nothing elsewhere, is requested by name."""
    unmatched = facts is not None and facts.not_found
    head = NO_CHORDS if facts is not None and facts.asked_ug else NOT_INDEXED if unmatched else ""
    search = (Action("See what caracole search finds", href=f"/review?song={song_id}")
              if unmatched and song_id is not None else None)
    if any(s.name == "gtptabs" and s.state == "done" and s.detail == GTPTABS_KEPT for s in job.stages):
        return Outcome("missing", "Not found", _joined(head, "caracole got a Guitar Pro file from gtptabs.com"),
                       _in_library(song_id), search)
    where = facts.elsewhere if facts is not None else None
    if where is not None and song_id is not None and where[0] in _ELSEWHERE:
        source, url = where
        fields = (("song", str(song_id)), *((("lacuerda", url),) if source == "lacuerda" else ()), ("then", "jobs"))
        return Outcome("missing", "Not found", _joined(head, _ELSEWHERE[source]),
                       Action("Get it from there", post="/lookup", fields=fields), search)
    return Outcome("missing", "Not found", _sentence(head),
                   search or Action("Request by name", href="/#" + urlencode({"q": job.display or job.title})))


def _joined(head: str, rest: str) -> str:
    return _sentence(f"{head}; {rest}" if head else rest)


def _in_library(song_id: int | None) -> Action | None:
    return Action("Open in the library", href=f"/#song={song_id}") if song_id is not None else None


def _waits(stages: list[Stage], *, after_sheet: bool = False) -> str:
    """The first stage's wait or error, in one sentence ("LRCLIB answered 503: the lyrics wait for tonight's
    run."); "" for none. ``after_sheet``: the stages after the sheet only, for a song whose sheet is there."""
    names = [name for _, group in LOOKUP_STEPS[3 if after_sheet else 2:] for name in group]
    by_name = {stage.name: stage for stage in stages}
    return next((said for name in names if name in by_name and (said := _stage_reason(by_name[name]))), "")


def _stage_reason(stage: Stage) -> str:
    detail = stage.detail.strip()
    if stage.name in ("pdf", "songbooks"):  # a refusal of caracole's own, in its own words
        return _sentence(detail) if stage.state == "failed" and detail else ""
    if stage.name not in _WHAT:
        return ""
    what, verb = _WHAT[stage.name]
    if stage.state == "failed" and (m := _FAILED.match(detail)):
        status = _STATUS.match(m["why"])
        answered = f"answered {status[1]}" if status else "failed"
        return f"{m['site']} {answered}: {what} {verb} for tonight's run."
    if stage.state != "skipped":
        return ""
    if m := _BLOCKED.match(detail):
        return f"{m['site']} blocked caracole: {what} {verb} until {m['until'] or 'it cools down'}."
    if m := _COOLING.match(detail):
        return f"{m['site']} is cooling down after a block: {what} {verb} until {m['until']}."
    if m := _SPENT.match(detail):
        spent = m["spent"]
        return f"{spent[:1].upper()}{spent[1:]}: {what} {verb} for tonight's run."
    return ""


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text.endswith((".", "!", "?", "…")) else text + "."


def _href(href: str) -> str:
    """A link of status.py's, relative to the library page at /, as an address from any page."""
    return href if href.startswith(("/", "https://", "http://")) else "/" + href


# --- what the local indexes have elsewhere -----------------------------------------------------------------


def elsewhere(conn: sqlite3.Connection, cfg: Config, song: Song, job: Job, now: datetime) -> tuple[str, str] | None:
    """For a song a fetch left without a sheet: a sheet LaCuerda's index holds of it (``("lacuerda", its
    page)``), else a gtptabs.com page whose title its index lists for a song with no Guitar Pro file
    (``("gtptabs", the page)``); None for neither. A site a new lookup would skip again is none: one the
    job's lookup asked already, one that cools down after a block now, one its stage skipped for a block,
    a cooldown or a spent budget, and LaCuerda once asked about the song this month (``asked_lately``),
    as gtptabs.com (``title_page``). It reads the local tables alone, and sends nothing."""
    from caracole.gtptabs_fetch import title_page
    from caracole.health import is_cooling
    from caracole.lacuerda_fetch import asked_lately
    from caracole.lacuerda_index import sheet_page

    if song.status == "ignored":
        return None
    by_name = {stage.name: stage for stage in job.stages}

    def may_ask(provider: str) -> bool:
        stage = by_name.get(provider)
        if stage is not None and (stage.state == "done" or stage.detail.startswith("asked already")
                                  or stage.state == "skipped" and _waited(stage.detail)):
            return False
        return not is_cooling(conn, provider, now)

    if may_ask("lacuerda") and not asked_lately(song, now):
        page = sheet_page(conn, song.artists or [song.artist], song.title)
        if page is not None:
            return "lacuerda", page
    if cfg.provider("gtptabs").enabled and may_ask("gtptabs"):
        page = title_page(conn, song, now)
        if page is not None:
            return "gtptabs", page
    return None


def _waited(detail: str) -> bool:
    """Whether a stage was skipped for a block, a cooldown or a spent budget, in get.py's words."""
    detail = detail.strip()
    return bool(_BLOCKED.match(detail) or _COOLING.match(detail) or _SPENT.match(detail))
