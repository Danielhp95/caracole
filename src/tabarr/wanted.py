r"""wanted.txt: the songs you want to learn, as a plain text file you edit.

This is tabarr's always-available source; Spotify is optional. The file lives in
the library folder, so Syncthing carries it to your phone. One song per line:

    Artist - Title
    Artist - Title | Album
    Artist - Title | m:ss
    Artist - Title | Album | m:ss

- The album and the duration are optional; either makes the lyrics lookup more
  exact. A duration is ``m:ss``, ``h:mm:ss`` or whole seconds. A field that
  looks like a duration is the duration and the other one is the album, so an
  album named like a number (Adele's "21") needs a field after it:
  ``Adele - Someone Like You | 21 |``.
- The artist ends at the first " - " (an en or em dash also works) with text on
  both sides. A title may therefore contain " - ", but an artist can't:
  "Sergio Mendes - Brasil '66" can't be written in this file.
- ``#`` starts a comment, at the start of a line or after a space, and blank
  lines are ignored. Write ``\#`` for a ``#`` that belongs to a name
  ("John Lennon - \#9 Dream") and ``\|`` for a ``|``.
- Deleting a line doesn't delete the song from tabarr, just as unliking a track
  on Spotify doesn't.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from tabarr.normalize import identity_key
from tabarr.sources import (
    KvGet,
    KvSet,
    SyncStats,
    Upsert,
    default_kv_get,
    default_kv_set,
    default_upsert,
    utc_stamp,
)

SOURCE = "wanted"
FORMAT = "expected 'Artist - Title', optionally followed by ' | Album' and/or ' | m:ss'"

# Where sync_wanted remembers when it first saw each song (see sync_wanted).
FIRST_SEEN_KEY = "wanted:first_seen:"

HEADER = r"""# tabarr: the songs you want to learn, one per line.
#
#   Artist - Title
#   Artist - Title | Album | m:ss
#
# The album and the duration (m:ss, or whole seconds) are optional; either one
# makes the lyrics lookup more exact. For example:
#
#   宋冬野 - 斑马斑马 | 安和桥北 | 4:13
#   Soda Stereo - De Música Ligera
#
# A # starts a comment, at the start of a line or after a space. Write \# for a
# # that is part of a name (John Lennon - \#9 Dream), and \| for a |.
# Deleting a line doesn't delete the song from tabarr.

"""

_SEPARATOR = re.compile(r"\s+[-–—]\s+")
_FIELD = re.compile(r"(?<!\\)\|")
_COMMENT = re.compile(r"(?:^|(?<=\s))#")
_DURATION_SHAPE = re.compile(r"\d+(?::\d+){0,2}")
_NEEDS_ESCAPE = re.compile(r"(?:^|(?<=\s))#|\|")
_INVISIBLE = "\u200b\u200e\u200f\ufeff"
_COMMENT_HINT = " (# starts a comment: write \\# for a # that is part of a name)"


@dataclass(frozen=True)
class WantedLine:
    """One song from wanted.txt; ``line_no`` counts from 1."""

    artist: str
    title: str
    album: str | None
    duration_ms: int | None
    line_no: int

    @property
    def identity(self) -> str:
        """The song's identity key, which is also its source id."""
        return identity_key(self.artist, self.title)


class _LineError(ValueError):
    pass


def parse_duration(text: str) -> int | None:
    """Milliseconds for ``m:ss``, ``h:mm:ss`` or whole seconds; None if ``text`` isn't one.

    Raises ValueError for something shaped like a duration that isn't a valid
    one, such as "4:75" or "0:00".
    """
    s = unicodedata.normalize("NFKC", text).strip()
    if not _DURATION_SHAPE.fullmatch(s):
        return None
    *head, last = s.split(":")
    bad = f"bad duration {text.strip()!r}: write m:ss, h:mm:ss or whole seconds"
    if not head:
        seconds = int(last)
    else:
        if len(last) != 2 or int(last) >= 60:
            raise ValueError(bad)
        if len(head) == 2:
            hours, minutes = head
            if len(minutes) != 2 or int(minutes) >= 60:
                raise ValueError(bad)
            seconds = int(hours) * 3600 + int(minutes) * 60 + int(last)
        else:
            seconds = int(head[0]) * 60 + int(last)
    if seconds <= 0:
        raise ValueError(f"bad duration {text.strip()!r}: it must be longer than zero")
    return seconds * 1000


def format_duration(duration_ms: int) -> str:
    """``m:ss``, or ``h:mm:ss`` from an hour up, rounded to the nearest second."""
    seconds = (duration_ms + 500) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_line(
    artist: str, title: str, album: str | None = None, duration_ms: int | None = None
) -> str:
    """The wanted.txt line for a song, escaped so that it parses back to the same song."""
    artist, title = _clean(artist), _clean(title)
    if not artist or not title:
        raise ValueError("a song needs an artist and a title")
    album = _clean(album) if album else ""
    parts = [f"{_escape(artist)} - {_escape(title)}"]
    if album:
        parts.append(_escape(album))
    if duration_ms is not None:
        if (duration_ms + 500) // 1000 <= 0:
            raise ValueError("a duration must be at least one second")
        parts.append(format_duration(duration_ms))
    elif album and _DURATION_SHAPE.fullmatch(unicodedata.normalize("NFKC", album)):
        parts.append("")  # "| 21 |": an empty last field keeps "21" an album
    return " | ".join(parts).rstrip()


def parse_wanted(text: str) -> tuple[list[WantedLine], list[tuple[int, str]]]:
    """The songs in wanted.txt, and ``(line_no, message)`` for each line that isn't one."""
    text = text.removeprefix("\ufeff")
    lines: list[WantedLine] = []
    errors: list[tuple[int, str]] = []
    # Split on "\n" only, so line numbers match what an editor shows.
    for line_no, raw in enumerate(text.split("\n"), start=1):
        raw = raw.rstrip("\r")
        try:
            line = _parse_line(raw, line_no)
        except _LineError as e:
            errors.append((line_no, f'{e}: "{_snippet(raw)}"'))
            continue
        if line is not None:
            lines.append(line)
    return lines, errors


def find_wanted(path: Path, artist: str, title: str) -> WantedLine | None:
    """The line of wanted.txt that holds this song (by identity key), if any."""
    text = _read_text(Path(path))
    if text is None:
        return None
    key = identity_key(artist, title)
    return next((line for line in parse_wanted(text)[0] if line.identity == key), None)


def append_wanted(
    path: Path,
    artist: str,
    title: str,
    album: str | None = None,
    duration_ms: int | None = None,
) -> WantedLine:
    """Add a song to the end of wanted.txt and return its line as the file now holds it.

    A missing file is created with a header that explains the format. A song
    already listed (same identity key) is not added twice; its existing line is
    returned. The file's newline style is kept. Raises ValueError for a song the
    format can't hold, such as an artist whose name contains " - ".
    """
    path = Path(path)
    text, wanted = _checked_line(artist, title, album, duration_ms)
    existing = _read_text(path)
    if existing is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = HEADER + text + "\n"
        try:
            with path.open("x", encoding="utf-8", newline="") as f:
                f.write(content)
        except FileExistsError:  # created meanwhile, e.g. by Syncthing: append to it instead
            return append_wanted(path, artist, title, album, duration_ms)
        return replace(wanted, line_no=content.count("\n"))
    for line in parse_wanted(existing)[0]:
        if line.identity == wanted.identity:
            return line
    newline = "\r\n" if "\r\n" in existing else "\n"
    lead = newline if existing and not existing.endswith("\n") else ""
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(lead + text + newline)
    return replace(wanted, line_no=(existing + lead).count("\n") + 1)


def sync_wanted(
    conn: sqlite3.Connection,
    path: Path,
    now: datetime,
    *,
    upsert: Upsert | None = None,
    kv_get: KvGet | None = None,
    kv_set: KvSet | None = None,
) -> SyncStats:
    """Hand every song in wanted.txt to the song repository, as source "wanted".

    The source id is the song's identity key. A missing file is an empty source,
    not an error, and bad lines go to ``stats.errors`` and ``stats.line_errors``:
    this never raises for anything in the file.

    ``added_at`` is the time a song was first seen in the file (``now`` for a
    new line), remembered in the kv table. Passing ``now`` every night would let
    the repository's "keep the newest added_at" rule push every listed song to
    the front of the queue, so a song you just added would no longer go first.
    """
    path = Path(path)
    stats = SyncStats()
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return stats
    except OSError as e:
        stats.errors.append(f"{path.name}: can't read {path}: {e.strerror or e}")
        return stats
    text, undecodable = _decode(data)
    lines, bad = parse_wanted(text)
    for line_no, message in sorted(undecodable + bad):
        stats.line_errors.append((line_no, message))
        stats.errors.append(f"{path.name} line {line_no}: {message}")
    if not lines:
        return stats

    upsert = upsert or default_upsert()
    kv_get = kv_get or default_kv_get()
    kv_set = kv_set or default_kv_set()
    stamp = utc_stamp(now)
    songs: set[str] = set()
    for line in lines:
        key = line.identity
        first_seen = kv_get(conn, FIRST_SEEN_KEY + key)
        _, created = upsert(
            conn,
            artists=[line.artist],
            title=line.title,
            album=line.album,
            duration_ms=line.duration_ms,
            isrc=None,
            source=SOURCE,
            source_id=key,
            added_at=first_seen or stamp,
        )
        if first_seen is None:
            kv_set(conn, FIRST_SEEN_KEY + key, stamp)
        songs.add(key)
        stats.new += int(created)
    stats.seen = len(songs)
    return stats


def _checked_line(
    artist: str, title: str, album: str | None, duration_ms: int | None
) -> tuple[str, WantedLine]:
    """The text of a song's line and what it parses back to; ValueError if that's another song."""
    if _SEPARATOR.search(_clean(artist)):
        raise ValueError(f"wanted.txt can't hold an artist name with ' - ' in it: {artist!r}")
    text = format_line(artist, title, album, duration_ms)
    lines, errors = parse_wanted(text)
    seconds = None if duration_ms is None else (duration_ms + 500) // 1000 * 1000
    expected = (_clean(artist), _clean(title), _clean(album or "") or None, seconds)
    if errors or len(lines) != 1 or (
        (lines[0].artist, lines[0].title, lines[0].album, lines[0].duration_ms) != expected
    ):
        raise ValueError(f"wanted.txt can't hold {artist!r} - {title!r} as written")
    return text, lines[0]


def _read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    return _decode(data)[0]


def _decode(data: bytes) -> tuple[str, list[tuple[int, str]]]:
    """UTF-8 text, with each line that isn't UTF-8 blanked and reported."""
    try:
        return data.decode("utf-8"), []
    except UnicodeDecodeError:
        pass
    lines: list[str] = []
    errors: list[tuple[int, str]] = []
    for line_no, raw in enumerate(data.split(b"\n"), start=1):
        try:
            lines.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            lines.append("")
            snippet = _snippet(raw.decode("utf-8", errors="replace"))
            errors.append((line_no, f'not valid UTF-8 (save the file as UTF-8): "{snippet}"'))
    return "\n".join(lines), errors


def _parse_line(raw: str, line_no: int) -> WantedLine | None:
    text = unicodedata.normalize("NFC", raw)
    hint = ""
    comment = _COMMENT.search(text)
    if comment:
        if text[: comment.start()].strip():
            hint = _COMMENT_HINT
        text = text[: comment.start()]
    if not _clean(text):
        return None
    fields = _FIELD.split(text)
    if len(fields) > 3:
        raise _LineError(f"too many ' | ' fields; {FORMAT}{hint}")
    names = _split_names(fields[0])
    if names is None:
        raise _LineError(FORMAT + hint)
    try:
        album, duration_ms = _extras([_clean(_unescape(f)) for f in fields[1:]])
    except ValueError as e:
        raise _LineError(f"{e}{hint}") from None
    return WantedLine(names[0], names[1], album, duration_ms, line_no)


def _split_names(main: str) -> tuple[str, str] | None:
    for sep in _SEPARATOR.finditer(main):
        artist = _clean(_unescape(main[: sep.start()]))
        title = _clean(_unescape(main[sep.end() :]))
        if artist and title:
            return artist, title
    return None


def _extras(fields: list[str]) -> tuple[str | None, int | None]:
    """(album, duration_ms) from the fields after the title."""
    if not fields:
        return None, None
    if len(fields) == 1:
        (only,) = fields
        if not only:
            return None, None
        ms = parse_duration(only)
        return (None, ms) if ms is not None else (only, None)
    first, last = fields
    ms = parse_duration(last) if last else None
    if ms is not None or not last:
        return first or None, ms
    ms = parse_duration(first) if first else None
    if ms is not None:
        return last, ms
    raise ValueError(f"{last!r} is not a duration: write m:ss, h:mm:ss or whole seconds")


def _clean(s: str) -> str:
    """NFC, single spaces, no stray zero-width characters at the ends."""
    return " ".join(unicodedata.normalize("NFC", s).split()).strip(_INVISIBLE).strip()


def _escape(s: str) -> str:
    return _NEEDS_ESCAPE.sub(lambda m: "\\" + m.group(0), s)


def _unescape(s: str) -> str:
    return s.replace("\\#", "#").replace("\\|", "|")


def _snippet(raw: str, width: int = 60) -> str:
    s = _clean(raw)
    return s if len(s) <= width else s[: width - 1] + "…"
