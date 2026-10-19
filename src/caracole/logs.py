"""The log: diagnostics on stderr, through Python's logging, set up once for every command.

stdout carries a command's report (``caracole run``'s summary: report.py); stderr
carries the log, levelled, and nothing else. ``setup`` is called by the CLI's
root callback, so every command shares it, and undone when the command ends:

- **Verbosity.** By default, and with ``-q``, the log shows problems only
  (warnings and errors); ``-q`` also cuts the report down to its problems.
  ``-v`` adds caracole's information, such as a line for each request; ``-vv``
  adds debug lines, the logger names, and the other libraries' logs. Below
  ``-vv``, those libraries (httpx, httpcore, urllib3, spotipy, numba, torch, …)
  show their warnings and errors only, whatever level they set themselves.
- **Under systemd** (``$JOURNAL_STREAM`` names stderr), every line starts with
  its sd-daemon priority (``<3>`` an error, ``<4>`` a warning, ``<6>``
  information, ``<7>`` debug), a traceback's lines included, so
  ``journalctl -p warning`` finds them; there are no timestamps, as journald
  keeps its own.
- **On a terminal**, the level is coloured, unless ``$NO_COLOR`` is set. Never
  anywhere else.
- **Secrets never reach it**, at any level: the values ``add_secrets`` names
  (the Spotify client secret, the ntfy token), Authorization headers, bearer
  and basic credentials, and OAuth tokens and codes are replaced by
  ``[redacted]`` in every line, tracebacks included.

stdlib only: the CLI imports this module on every start.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Mapping
from typing import IO, Any

QUIET, NORMAL, VERBOSE, DEBUG = -1, 0, 1, 2

# Libraries whose logs stay at warnings below -vv; any other non-caracole logger does too.
THIRD_PARTY = ("httpx", "httpcore", "urllib3", "requests", "spotipy", "numba", "torch", "torchaudio",
               "librosa", "audioread", "matplotlib", "PIL", "fsspec", "filelock")

_LEVELS = {QUIET: logging.WARNING, NORMAL: logging.WARNING, VERBOSE: logging.INFO, DEBUG: logging.DEBUG}


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


# --- secrets ------------------------------------------------------------------------------------

REDACTED = "[redacted]"
_secrets: set[str] = set()
# A credential after its scheme: six or more token characters with a digit or a symbol among them,
# or twenty letters, so "token expired" and "basic chords" stay as they are.
_SCHEMES = re.compile(
    r"(?i)\b(bearer|basic|token)(\s+)"
    r"(?=[A-Za-z0-9._~+/=-]{6})(?:[A-Za-z.]*[0-9_~+/=-][A-Za-z0-9._~+/=-]*|[A-Za-z]{20,})"
)
_HEADER = re.compile(r"""(?i)(\b(?:proxy-)?authorization["']?\s*[:=]\s*["']?)(?!(?:bearer|basic|token)\s)[^"'\s,}]+""")
_KEYS = re.compile(
    r"""(?i)(["']?\b(?:access_token|refresh_token|id_token|client_secret|code_verifier|password|secret|token)"""
    r"""["']?\s*[:=]\s*["']?)[^"'\s,&}]+"""
)
_CODE = re.compile(r"(?i)([?&](?:code|access_token|refresh_token|client_secret)=)[^&\s#\"']+")


def add_secrets(*values: str | None) -> None:
    """Values the log must never show, such as the secrets the config read. They stay known
    for the life of the process: a crash reported after a command ends is scrubbed too."""
    _secrets.update(v for v in values if v and len(v) >= 4)


def redact(text: str) -> str:
    """``text`` without the known secrets, credentials in headers, or OAuth tokens and codes."""
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = _SCHEMES.sub(rf"\1\2{REDACTED}", text)
    text = _HEADER.sub(rf"\1{REDACTED}", text)
    text = _KEYS.sub(rf"\1{REDACTED}", text)
    return _CODE.sub(rf"\1{REDACTED}", text)


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
        text = redact(text)
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
    handler.setFormatter(_style(sys.stderr if stream is None else stream, env, level))
    if level < DEBUG:
        handler.addFilter(_OthersQuiet())
    root = logging.getLogger()
    for name in ("", "caracole", *THIRD_PARTY):
        _saved[name] = logging.getLogger(name).level
    root.setLevel(logging.DEBUG if level >= DEBUG else logging.WARNING)
    logging.getLogger("caracole").setLevel(_LEVELS[level])
    for name in THIRD_PARTY:
        logging.getLogger(name).setLevel(logging.NOTSET if level >= DEBUG else logging.WARNING)
    root.addHandler(handler)
    _handler = handler


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


def say(level: int, message: str, *, env: Mapping[str, str] | None = None) -> None:
    """Write one line on stderr as the log would, outside the logging machinery: a command's last
    word as it exits (``commands._common.fail``), which must show however logging is set up."""
    record = logging.LogRecord("caracole", level, __file__, 0, message, None, None)
    formatter = _handler.formatter if _handler is not None and env is None else None
    formatter = formatter or _style(sys.stderr, env, NORMAL)
    sys.stderr.write(formatter.format(record) + "\n")
    sys.stderr.flush()
