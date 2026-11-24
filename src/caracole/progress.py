"""Progress for long commands: one live line on a terminal, plain lines anywhere else.

A ``Console`` writes four kinds of output. ``say`` is a result, always printed.
``note`` says what is about to happen, and ``step`` that one step is done;
``status`` says what is under way. On a terminal (``isatty``, and ``TERM``
isn't ``dumb``), ``step`` and ``status`` share one live line, rewritten in
place after a carriage return and kept within the terminal's width (its
stream's own, in display columns: a Chinese character takes two); ``say``
and ``note`` clear it first. Anywhere else, such as systemd's journal or a
pipe, a step is one plain line and ``status`` prints nothing: no carriage
return and no color. Color only ever goes to a terminal, and never when
``NO_COLOR`` is set (https://no-color.org). ``quiet`` keeps only ``say``.

``Pace`` estimates the time a run of paced steps has left, and ``about`` and
``duration`` put times into words.

A ``Ticker`` says what long work is doing while it goes, for whoever watches
(``caracole run``, ``ug --directory``, the ``--index`` passes, ``render``,
``fetch``): on a terminal at the default verbosity, the live line of a
``Console`` on stderr, so stdout stays the command's report; and, at most a
line a minute, the ``caracole.progress`` log, which the journal keeps at the
default verbosity (logs.py's ``JOURNAL_INFO``), and -v anywhere; and, in a unit
that lets it (``$NOTIFY_SOCKET``: nix/module.nix's ``NotifyAccess``), the unit's
status line, which ``systemctl status`` shows (``systemd_status``, sd_notify's
``STATUS=``). ``Requests`` counts what a client sends onto one, and ``Counted``
work of a known size. They only count and say: nothing here paces, delays or
holds a request.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import time
import unicodedata
from collections.abc import Callable, Mapping
from typing import Any, TextIO

import click

from caracole import logs


class Console:
    """Where a command's report goes; see the module docstring.

    ``live`` and ``color`` default to what the stream and ``environ`` (the
    environment) say: a caller that knows better, such as a journal or a
    verbose log interleaved with this output, passes ``live=False``.
    """

    def __init__(self, stream: TextIO | None = None, *, live: bool | None = None, color: bool | None = None,
                 quiet: bool = False, environ: Mapping[str, str] | None = None,
                 width: Callable[[], int] | None = None):
        self.stream = stream if stream is not None else sys.stdout
        env = os.environ if environ is None else environ
        terminal = _isatty(self.stream) and env.get("TERM", "") != "dumb"
        self.live = terminal if live is None else live
        self.color = (terminal and not env.get("NO_COLOR")) if color is None else color
        self.quiet = quiet
        self._width = width or (lambda: _columns_of(self.stream))
        self._shown = 0  # display columns of the live line on screen

    def say(self, text: str = "", **style: Any) -> None:
        """A result: a line of its own, always (``style`` as ``click.style`` takes it, on a terminal)."""
        self._clear()
        self._echo(self.style(text, **style) if style else text)

    def note(self, text: str) -> None:
        """What is about to happen: a line of its own, unless quiet."""
        if not self.quiet:
            self.say(text)

    def step(self, text: str, tail: str = "") -> None:
        """One step done: the live line on a terminal, else a plain line; ``tail`` (the time left) is
        what stays when the live line has to be cut short."""
        if self.quiet:
            return
        if self.live:
            self.status(text, tail)
        else:
            self._echo(_join(text, tail))

    def status(self, text: str, tail: str = "") -> None:
        """What is under way: the live line on a terminal, nothing anywhere else."""
        if self.quiet or not self.live:
            return
        line = _fit(text, tail, max(1, self._width() - 1))  # one column short, so the cursor never wraps
        click.echo("\r" + line + " " * max(0, self._shown - _columns(line)), file=self.stream, nl=False, color=False)
        self._shown = _columns(line)

    def style(self, text: str, **style: Any) -> str:
        return click.style(text, **style) if self.color else text

    def close(self) -> None:
        """Clear a live line left on screen, so what is printed next starts on a clean line."""
        self._clear()

    def _clear(self) -> None:
        if self._shown:
            click.echo("\r" + " " * self._shown + "\r", file=self.stream, nl=False, color=False)
            self._shown = 0

    def _echo(self, text: str) -> None:
        click.echo(text, file=self.stream, color=self.color)


def _isatty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):  # no isatty, or a closed stream
        return False


def _columns_of(stream: TextIO) -> int:
    """The width of the terminal ``stream`` is, from its own descriptor (stderr's for a ticker, whatever stdout is);
    80 for one that says none."""
    try:
        return os.get_terminal_size(stream.fileno()).columns or 80
    except (AttributeError, ValueError, OSError):  # no descriptor, a closed one, or no terminal there
        return 80


def _char_columns(ch: str) -> int:
    """The display columns a character takes, as chordpro.py's ``display_columns`` counts them (not imported: this
    module loads on every start): a wide East Asian one two, a combining mark none."""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _columns(text: str) -> int:
    return sum(_char_columns(ch) for ch in text)


def _join(text: str, tail: str) -> str:
    return "  ".join(part for part in (text, tail) if part)


def _cut(text: str, width: int) -> str:
    """``text`` within ``width`` display columns, its end "..." where it is cut."""
    if _columns(text) <= width:
        return text
    kept, used = [], 0
    for ch in text:
        used += _char_columns(ch)
        if used > max(0, width - 3):
            break
        kept.append(ch)
    return "".join(kept) + "..."


def _fit(text: str, tail: str, width: int) -> str:
    room = width - _columns(tail) - 2
    if not tail:
        return _cut(text, width)
    if room < 4:
        return _cut(tail, width)
    return _join(_cut(text, room), tail)


class Pace:
    """The time a run of paced steps has left.

    It starts from ``per_step``, the pacing's mean, and moves to the pace
    measured as steps are done: the pacing counts as ``weight`` steps already
    taken at its own pace, so a slow or quick first step doesn't swing it.
    """

    def __init__(self, per_step: float, *, clock: Callable[[], float] = time.monotonic, weight: float = 2.0):
        self.prior = per_step
        self.weight = weight
        self._clock = clock
        self._started = clock()
        self.steps = 0

    def step(self) -> None:
        self.steps += 1

    def per_step(self) -> float:
        return (self.prior * self.weight + self._clock() - self._started) / (self.weight + self.steps)

    def left(self, steps: int) -> float:
        return steps * self.per_step()


def about(seconds: float) -> str:
    """A time to come, as precise as an estimate can be: "about 15 s", "about 8 min"."""
    if seconds < 1:
        return "under a second"
    if seconds < 10:
        return f"about {round(seconds)} s"
    rounded = 5 * round(seconds / 5)
    if rounded < 60:
        return f"about {rounded} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"about {minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"about {hours} h" + (f" {minutes} min" if minutes else "")


def duration(seconds: float) -> str:
    """How long something took: "4.2 s", "42 s", "10 min 32 s", "1 h 2 min"."""
    if seconds < 9.95:
        return f"{seconds:.1f} s"
    total = round(seconds)
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {secs} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


EVERY = 60.0  # seconds: a ticker's line in the log at most this often
_screen_gone = False  # a live line failed to be written: none more in this process (``ticker``)
STATUS_EVERY = 2.0  # seconds: the unit's status line told at most this often, but as a part begins
ANSWER = 0.5  # seconds a site takes to answer, about, beside the pause before each request
# A request's events, sent: a redirect too, followed or not, which reached the site as any other request did. The one
# list, which commands/_common.py counts the hour's, the day's and the last request by too.
SENT = ("ok", "not_modified", "redirect", "blocked", "error")


class Ticker:
    """What long work is doing, as it goes; see the module docstring.

    ``show`` says where the work is (its text, and ``tail``, the time left, which stays when the live line is cut
    short): the console's live line at once, and a line of the log once ``every`` seconds have passed since the last.
    ``prefix``, what the work is part of (the run's step, "[6/20] lyrics"), goes before each text; ``begin`` starts
    such a part, its line live at once and the log's next a whole ``every`` later, its own start line just logged by
    its caller. A record the log writes takes the live line off the screen first (``logs.clears_first``), and so does
    ``clear``, before the command prints on stdout; ``close`` does both for good. ``status``, where given, is told
    the line too (the unit's status line, ``systemd_status``): as a part begins, and at most every ``STATUS_EVERY``
    seconds after; ``finish`` tells it the work's last word. A terminal that can't be written (gone, closed) never
    stops the work: the live line goes off, for the rest of the process.
    """

    def __init__(self, console: Console | None = None, *, clock: Callable[[], float] = time.monotonic,
                 every: float = EVERY, logger: logging.Logger | None = None,
                 status: Callable[[str], object] | None = None):
        self.console = console
        self.prefix = ""
        self._clock = clock
        self._every = every
        self._log = logger or logging.getLogger("caracole.progress")
        self._said = self._told = clock()
        self._status = status
        self._undo = logs.clears_first(self.clear) if console is not None and console.live else None

    def begin(self, prefix: str) -> None:
        self.prefix = prefix
        self._said = self._told = self._clock()
        self._on_screen(lambda console: console.status(prefix + "…"))
        if self._status is not None:
            self._status(prefix + "…")

    def show(self, text: str = "", tail: str = "") -> None:
        line = " · ".join(part for part in (self.prefix, text) if part)
        self._on_screen(lambda console: console.status(line, tail))
        now = self._clock()
        if now - self._said >= self._every:
            self._said = now
            self._log.info("%s", _join(line, tail))
        if self._status is not None and now - self._told >= STATUS_EVERY:
            self._told = now
            self._status(_join(line, tail))

    def finish(self, text: str) -> None:
        """The work's last word, for the unit's status line alone (``systemctl status`` after the run)."""
        if self._status is not None:
            self._status(text)

    def clear(self) -> None:
        self._on_screen(lambda console: console.close())

    def close(self) -> None:
        self.clear()
        self._unhook()

    def _on_screen(self, write: Callable[[Console], object]) -> None:
        if self.console is None:
            return
        try:
            write(self.console)
        except (OSError, ValueError):  # the terminal went (EIO, a closed stream): the work goes on, unseen
            global _screen_gone
            _screen_gone = True
            self.console = None
            self._unhook()

    def _unhook(self) -> None:
        if self._undo is not None:
            self._undo()
            self._undo = None

    def __enter__(self) -> Ticker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def ticker() -> Ticker:
    """A command's ``Ticker``: its live line on stderr on a terminal at the default verbosity alone (at -v the log's
    own lines say more, -q keeps quiet, and a caller that set up no log, a test's, gets none); its log lines whatever
    the log shows; and the unit's status line where the unit lets it be told (``$NOTIFY_SOCKET``)."""
    live = None if logs.level() == logs.NORMAL and not _screen_gone else False
    status = systemd_status if os.environ.get("NOTIFY_SOCKET") else None
    return Ticker(Console(sys.stderr, live=live), status=status)


def systemd_status(text: str, *, environ: Mapping[str, str] | None = None) -> bool:
    """``text`` as the unit's status line (sd_notify's ``STATUS=``, which ``systemctl status`` shows), on one line,
    sent to the socket systemd names in ``$NOTIFY_SOCKET`` (a path, or an abstract address after "@"); True once
    sent. Nothing without one, or to one of another kind, and a socket that won't take it is no error: the line is a
    courtesy."""
    address = (os.environ if environ is None else environ).get("NOTIFY_SOCKET", "")
    if address.startswith("@"):
        address = "\0" + address[1:]
    elif not address.startswith("/"):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as s:
            s.connect(address)
            s.sendall(("STATUS=" + " ".join(text.splitlines())).encode("utf-8", "replace"))
    except OSError:
        return False
    return True


class Requests:
    """An ``on_event`` (http.py's events, youtube.py's) that counts the requests a client sends on a ``Ticker``:
    "LRCLIB · 37 of up to 200 requests", "up to about 2 min left", or "AZLyrics · 12 requests" with no budget.

    The budget is what the work may spend, not what it will, hence "up to": the time is what the rest of it would
    take at the pace measured since the step's first request (``Pace``, from ``delay``'s mean and ``ANSWER`` before
    any), measured again from the ticker's next ``prefix`` (the run's next step: a client serves several).
    """

    def __init__(self, ticker: Ticker, provider: str, *, budget: int | None, delay: tuple[float, float],
                 noun: str = "request", estimate: bool = True, clock: Callable[[], float] = time.monotonic):
        self.ticker = ticker
        self.name = logs.provider_name(provider)
        self.budget = budget
        self.per_request = sum(delay) / 2 + ANSWER
        self.noun = noun
        self.estimate = estimate  # False for a yt-dlp run, a download of minutes no pacing foretells
        self.sent = 0
        self._clock = clock
        self._pace: Pace | None = None
        self._prefix = ""

    def __call__(self, event: Any) -> None:
        if getattr(event, "decision", None) not in SENT:
            return
        self.sent += 1
        if self._pace is None or self.ticker.prefix != self._prefix:
            self._pace, self._prefix = Pace(self.per_request, clock=self._clock), self.ticker.prefix
        else:
            self._pace.step()
        if self.budget is None:
            self.ticker.show(f"{self.name} · {logs.plural(self.sent, self.noun)}")
            return
        left = self._pace.left(max(self.budget - self.sent, 0))
        tail = f"up to {about(left)} left" if self.estimate and left >= 1 else ""
        self.ticker.show(f"{self.name} · {self.sent:,} of up to {self.budget:,} {self.noun}s", tail)


class Counted:
    """Work of a known size on a ``Ticker``: called with its text, the steps done and those in all, it adds the time
    the rest should take ("about 2 min left") once one step is measured (``Pace``, from ``per_step`` before), measured
    again for another ``kind`` of step (a pass's next phase)."""

    def __init__(self, ticker: Ticker, *, per_step: float, clock: Callable[[], float] = time.monotonic):
        self.ticker = ticker
        self.per_step = per_step
        self._clock = clock
        self._pace: Pace | None = None
        self._kind = ""
        self._base = 0

    def __call__(self, text: str, done: int, total: int, kind: str = "") -> None:
        if self._pace is None or kind != self._kind or done < self._base:
            self._pace, self._kind, self._base = Pace(self.per_step, clock=self._clock), kind, done
        self._pace.steps = done - self._base
        left = max(total - done, 0)
        tail = f"{about(self._pace.left(left))} left" if left and self._pace.steps else ""
        self.ticker.show(text, tail)
