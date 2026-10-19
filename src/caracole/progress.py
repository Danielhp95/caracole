"""Progress for long commands: one live line on a terminal, plain lines anywhere else.

A ``Console`` writes four kinds of output. ``say`` is a result, always printed.
``note`` says what is about to happen, and ``step`` that one step is done;
``status`` says what is under way. On a terminal (``isatty``, and ``TERM``
isn't ``dumb``), ``step`` and ``status`` share one live line, rewritten in
place after a carriage return and kept within the terminal's width; ``say``
and ``note`` clear it first. Anywhere else, such as systemd's journal or a
pipe, a step is one plain line and ``status`` prints nothing: no carriage
return and no color. Color only ever goes to a terminal, and never when
``NO_COLOR`` is set (https://no-color.org). ``quiet`` keeps only ``say``.

``Pace`` estimates the time a run of paced steps has left, and ``about`` and
``duration`` put times into words.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any, TextIO

import click


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
        self._width = width or (lambda: shutil.get_terminal_size().columns)
        self._shown = 0  # characters of the live line on screen

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
        click.echo("\r" + line + " " * max(0, self._shown - len(line)), file=self.stream, nl=False, color=False)
        self._shown = len(line)

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


def _join(text: str, tail: str) -> str:
    return "  ".join(part for part in (text, tail) if part)


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 3)] + "..."


def _fit(text: str, tail: str, width: int) -> str:
    room = width - len(tail) - 2
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
