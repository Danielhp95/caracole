"""The log: diagnostics on stderr, through Python's logging, set up once for every command.

stdout carries a command's report (``caracole run``'s summary: report.py); stderr
carries the log, levelled, and nothing else. ``setup`` is called by the CLI's
root callback, so every command shares it, and undone when the command ends:

- **Verbosity.** By default, and with ``-q``, the log shows problems only
  (warnings and errors); ``-q`` also cuts the report down to its problems.
  ``-v`` adds caracole's information, such as a line for each request; ``-vv``
  adds debug lines, the logger names, and the other libraries' logs. Below
  ``-vv``, those libraries (httpx, httpcore, numba, torch, …)
  show their warnings and errors only, whatever level they set themselves.
- **Under systemd** (``$JOURNAL_STREAM`` names stderr), every line starts with
  its sd-daemon priority (``<3>`` an error, ``<4>`` a warning, ``<6>``
  information, ``<7>`` debug), a traceback's lines included, so
  ``journalctl -p warning`` finds them; there are no timestamps, as journald
  keeps its own. There, by default, the information of ``JOURNAL_INFO``'s
  loggers shows too: the library page's line a build (page_log.py), so the
  journal says what each page showed (``-q`` still keeps to the problems).
- **On a terminal**, the level is coloured, unless ``$NO_COLOR`` is set. Never
  anywhere else.

stdlib only: the CLI imports this module on every start.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from typing import IO, Any

QUIET, NORMAL, VERBOSE, DEBUG = -1, 0, 1, 2

# Libraries whose logs stay at warnings below -vv; any other non-caracole logger does too.
THIRD_PARTY = ("httpx", "httpcore", "urllib3", "requests", "numba", "torch", "torchaudio",
               "librosa", "audioread", "matplotlib", "PIL", "fsspec", "filelock")

_LEVELS = {QUIET: logging.WARNING, NORMAL: logging.WARNING, VERBOSE: logging.INFO, DEBUG: logging.DEBUG}

# caracole's loggers whose information the journal keeps at the default verbosity, as -v would show it: the library
# page's line a build (page_log.py), the evidence asked for of what each page showed.
JOURNAL_INFO = ("caracole.page_log",)


PROVIDER_NAMES: Mapping[str, str] = {
    "ug": "Ultimate Guitar",
    "lrclib": "LRCLIB",
    "megalobiz": "Megalobiz",
    "lacuerda": "LaCuerda",
    "gtptabs": "gtptabs.com",
    "musescore": "MuseScore",
    "harptabs": "harptabs.com",
    "gametabs": "gametabs.net",
    "youtube": "YouTube",
    "ytimg": "YouTube's images",
}


def provider_name(provider: str) -> str:
    """A provider as people call it: "Ultimate Guitar", not "ug"."""
    return PROVIDER_NAMES.get(provider, provider)


def plural(n: int, noun: str, many: str | None = None) -> str:
    """A count and its noun, as every message says one: "1 song", "2 songs" (``many``, when not noun + "s")."""
    return f"{n} {noun if n == 1 else (many or noun + 's')}"


def request_line(provider: str, method: str, url: str, answer: str, *, cached: bool = False,
                 seconds: float | None = None, used: int, budget: int) -> str:
    """One request, as the log shows it at -v: who was asked what, what came back, how fast, and
    how much of the run's budget is used. ``answer`` is a status ("503 Service Unavailable"), or
    the error a request ended on ("ReadTimeout")."""
    if cached:
        how = " from the cache"
    elif seconds is None:
        how = ""
    else:
        how = f" {'in' if answer[:1].isdigit() else 'after'} {seconds:.2f} s"
    return f"{provider_name(provider)} {method} {url} → {answer}{how} ({used} of {budget} requests)"


def verbosity(verbose: int, quiet: bool) -> int:
    """The verbosity the root options ask for: ``-q``, nothing, ``-v`` or ``-vv`` (more counts as ``-vv``)."""
    return QUIET if quiet else min(max(verbose, 0), DEBUG)


def priority(level: int) -> int:
    """The sd-daemon (syslog) priority of a logging level."""
    if level >= logging.CRITICAL:
        return 2
    if level >= logging.ERROR:
        return 3
    if level >= logging.WARNING:
        return 4
    if level >= logging.INFO:
        return 6
    return 7


def is_journal(stream: Any, env: Mapping[str, str] | None = None) -> bool:
    """Whether ``stream`` is the journal: systemd names the stream it connected in ``$JOURNAL_STREAM``."""
    value = (os.environ if env is None else env).get("JOURNAL_STREAM", "")
    try:
        device, inode = (int(part) for part in value.split(":"))
        st = os.fstat(stream.fileno())
    except (ValueError, OSError, AttributeError):  # unset or malformed, or a stream with no file
        return False
    return (st.st_dev, st.st_ino) == (device, inode)


def wants_colour(stream: Any, env: Mapping[str, str] | None = None) -> bool:
    """Colour for a terminal, unless ``$NO_COLOR`` is set (to anything but "") or ``$TERM`` is "dumb"."""
    env = os.environ if env is None else env
    if env.get("NO_COLOR") or env.get("TERM") == "dumb":
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):  # no isatty, or closed
        return False


# --- formatting ---------------------------------------------------------------------------------

_LABELS = ((logging.ERROR, "error", "\x1b[1;31m"), (logging.WARNING, "warning", "\x1b[1;33m"),
           (logging.INFO, "", ""), (logging.NOTSET, "debug", "\x1b[2m"))
_RESET = "\x1b[0m"


class Formatter(logging.Formatter):
    """One record as the log shows it; see the module docstring."""

    def __init__(self, *, journal: bool = False, colour: bool = False, names: bool = False):
        super().__init__()
        self.journal, self.colour, self.names = journal, colour, names

    def format(self, record: logging.LogRecord) -> str:
        text = record.getMessage()
        if record.exc_info:
            text = f"{text}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            text = f"{text}\n{self.formatStack(record.stack_info)}"
        name = f"{record.name}: " if self.names else ""
        if self.journal:
            p = f"<{priority(record.levelno)}>"
            first, *rest = text.split("\n")
            return "\n".join([f"{p}{name}{first}", *(f"{p}{line}" for line in rest)])
        label, colour = next((label, colour) for level, label, colour in _LABELS if record.levelno >= level)
        if label and self.colour:
            label = f"{colour}{label}:{_RESET} "
        elif label:
            label = f"{label}: "
        return f"{label}{name}{text}"


def _ours(name: str) -> bool:
    return name == "caracole" or name.startswith("caracole.")


class _OthersQuiet(logging.Filter):
    """Below -vv, another library's record shows only when it is a warning or worse."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or _ours(record.name)


class _Stderr(logging.StreamHandler):
    """Writes to whatever ``sys.stderr`` is when a record comes, as ``logging.lastResort`` does."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> IO[str]:  # type: ignore[override]
        return sys.stderr


_handler: logging.Handler | None = None
_saved: dict[str, int] = {}  # logger name ("" for the root) -> its level before setup


def _style(stream: Any, env: Mapping[str, str] | None, level: int) -> Formatter:
    return Formatter(journal=is_journal(stream, env), colour=wants_colour(stream, env), names=level >= DEBUG)


def setup(level: int, *, stream: IO[str] | None = None, env: Mapping[str, str] | None = None) -> None:
    """Send the log to stderr (or ``stream``) at a verbosity: ``QUIET``, ``NORMAL``, ``VERBOSE`` or ``DEBUG``.

    Calling it again replaces the setup; ``teardown`` restores the logging it found.
    Other handlers, such as pytest's, are left alone.
    """
    global _handler
    teardown()
    handler: logging.Handler = _Stderr() if stream is None else logging.StreamHandler(stream)
    style = _style(sys.stderr if stream is None else stream, env, level)
    handler.setFormatter(style)
    if level < DEBUG:
        handler.addFilter(_OthersQuiet())
    root = logging.getLogger()
    for name in ("", "caracole", *THIRD_PARTY, *JOURNAL_INFO):
        _saved[name] = logging.getLogger(name).level
    root.setLevel(logging.DEBUG if level >= DEBUG else logging.WARNING)
    logging.getLogger("caracole").setLevel(_LEVELS[level])
    for name in THIRD_PARTY:
        logging.getLogger(name).setLevel(logging.NOTSET if level >= DEBUG else logging.WARNING)
    if style.journal and level == NORMAL:
        for name in JOURNAL_INFO:
            logging.getLogger(name).setLevel(logging.INFO)
    root.addHandler(handler)
    _handler = handler
    _current[:] = [(level, stream, env)]


def at_least(level: int) -> None:
    """Raise the verbosity to ``level``, unless ``-q`` asked for problems only, for a command whose
    progress is its report (``caracole autochords``: a line per song, minutes apart). Never lowers it."""
    if not _current:
        return
    current, stream, env = _current[0]
    if current != QUIET and current < level:
        setup(level, stream=stream, env=env)


_current: list[tuple[int, IO[str] | None, Mapping[str, str] | None]] = []  # what setup was last asked for


def teardown() -> None:
    """Undo ``setup``: its handler goes, and the levels it set are as they were."""
    global _handler
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler.close()
        _handler = None
    for name, level in _saved.items():
        logging.getLogger(name).setLevel(level)
    _saved.clear()
    _current.clear()


def say(level: int, message: str, *, env: Mapping[str, str] | None = None,
        exc_info: BaseException | None = None) -> None:
    """Write one line on stderr as the log would, outside the logging machinery: a command's last
    word as it exits (``commands._common.fail``), which must show however logging is set up, or a
    bug's, with its traceback (``exc_info``) after it (``cli.main``)."""
    exc = (type(exc_info), exc_info, exc_info.__traceback__) if exc_info is not None else None
    record = logging.LogRecord("caracole", level, __file__, 0, message, None, exc)
    formatter = _handler.formatter if _handler is not None and env is None else None
    formatter = formatter or _style(sys.stderr, env, NORMAL)
    sys.stderr.write(formatter.format(record) + "\n")
    sys.stderr.flush()
