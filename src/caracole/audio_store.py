"""The audio files you give caracole for a song's auto sheet, kept in caracole's own folder, ``state_dir/audio/``.

Not Music/, which is yours and read-only to the services, nor the library, which is synced, nor the cache, whose
promise is that losing it costs only requests: a file you gave can't be fetched again. The folder is caracole's alone
(0700, each file 0600), never synced, and backed up with the state.

- **A kept file** is ``<song id>-<first 16 hex of its SHA-256><ext>`` (``keep``), and the song's ``audio_path`` names
  it, as it names a purchase. A song's audio is an upload when that path is a regular file of this folder by such a
  name (``uploaded``): no kv record, nothing the phone or a sync sees.
- **An upload always wins**, the owner's decision of 2026-11-25: a file you give a song is its audio whatever it had
  (a purchase linked from Music/, whose file stays where it is; YouTube's audio, which youtube_fetch.py's ``tidy``
  then lets go of; an earlier upload, deleted), and nothing takes its place later: ``music.scan_music`` leaves such a
  song as it is. ``tidy``, in the nightly scan step, deletes the kept files no song's ``audio_path`` names (an older
  upload a newer one replaced, a song merged into another, one a removal couldn't delete).
- **A staged upload** is ``.upload-<16 hex><ext>`` beside ``.upload-<id>.json`` (the name it was sent under, its size,
  SHA-256, format, length, tags and when): caracole serve's, from a page's upload (``stage``) until a job keeps it as a
  song's audio (``keep(move=True)``). At most one no job names waits: a new one lets go of the others no waiting or
  running job names (``named``); and one left an hour that no job names is swept (``sweep``), or dropped at once
  (``drop``: the page's Cancel).
- **What a file is** is read from its bytes alone (``sniff``: MP3, M4A, FLAC, WAV, Ogg or AIFF, ``FORMATS``), never
  its name or the Content-Type, then mutagen must read it as that format, with a length over 0 and at most
  ``MAX_SECONDS``. The extension is caracole's, from the format. An upload is ``AUDIO_MAX`` at most (a file of your own,
  ``keep(move=False)``, any size, read first as ``examine`` reads it); either is refused when the disk would keep less
  than ``ROOM`` beside twice it.
- **The client never chooses a path**: the name an upload is sent under is a name to show (its last part, control
  characters out, 255 characters at most); a staged upload is named by its 16-hex id, checked whole, and resolved to
  exactly one regular file of the folder, never through a symbolic link; every file is made with ``O_CREAT | O_EXCL |
  O_NOFOLLOW``; nothing is served back from the folder.

mutagen is imported only to read a file: the pages and the server import this module.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
import unicodedata
from collections.abc import Callable, Collection
from dataclasses import asdict, dataclass
from pathlib import Path
from shutil import disk_usage
from typing import IO, Any

from caracole.config import Config
from caracole.songs import Song, get_song, update_song

log = logging.getLogger(__name__)

FOLDER = "audio"  # in the state directory
AUDIO_MAX = 128 * 1024 * 1024  # an upload's bytes, at most; a file of your own is any size
MAX_SECONDS = 30 * 60  # an audio file's length, at most
ROOM = 1024 ** 3  # bytes the disk keeps free beside twice the file, at least
EXPIRES = 3600.0  # seconds a staged upload no job names is left before it is swept
HEAD = 64  # the bytes ``sniff`` reads
FORMATS = {"MP3": ".mp3", "M4A": ".m4a", "FLAC": ".flac", "WAV": ".wav", "Ogg": ".ogg", "AIFF": ".aiff"}
# The mutagen classes that read each format, tried in order.
_READERS = {
    "MP3": (("mutagen.mp3", "EasyMP3"),),
    "M4A": (("mutagen.easymp4", "EasyMP4"),),
    "FLAC": (("mutagen.flac", "FLAC"),),
    "WAV": (("mutagen.wave", "WAVE"),),
    "Ogg": (("mutagen.oggvorbis", "OggVorbis"), ("mutagen.oggopus", "OggOpus"), ("mutagen.oggflac", "OggFLAC"),
            ("mutagen.oggspeex", "OggSpeex")),
    "AIFF": (("mutagen.aiff", "AIFF"),),
}
# The MP4 brands of audio files: iTunes' (M4A, M4B, mp42), FFmpeg's (isom, iso2, mp41; iso5 and iso6 for DASH),
# Android's recorders' (mp42, isom), and YouTube's audio as yt-dlp takes it before FFmpeg's fix-up (dash, iso6, mp41).
# A picture's or a video's alone (heic, avif, qt, M4V, 3gp) is none.
_MP4_BRANDS = {b"M4A ", b"M4B ", b"mp42", b"isom", b"dash", b"iso2", b"iso5", b"iso6", b"mp41"}
_EXT = "|".join(re.escape(ext) for ext in FORMATS.values())
ID = re.compile(r"[0-9a-f]{16}")  # a staged upload's id
_STAGED = ".upload-"
_PIECE = re.compile(rf"\.upload-(?P<id>[0-9a-f]{{16}})(?P<ext>{_EXT}|\.json)")  # a staged upload's audio or record
_STAGED_AUDIO = re.compile(rf"\.upload-(?P<id>[0-9a-f]{{16}})(?:{_EXT})")
_MARKER = re.compile(r"\.upload-(?P<id>[0-9a-f]{16})\.kept")  # a moved upload's marker: the kept file it became
# How long a moved upload's marker is kept: the Journal's history (web/history.py DAYS), as Try again of its job can't
# come later than that. A few dozen bytes each.
MARKED = 30 * 86400
KEPT = re.compile(rf"[0-9]+-[0-9a-f]{{16}}(?:{_EXT})")  # a kept file: <song id>-<sha256 16 hex><ext>
_PART = re.compile(r"\.keep-[0-9a-f]{16}\.part")  # a copy into the folder, until it is whole
_RECORD_MAX = 64 * 1024  # a staged upload's record's bytes, at most

NOT_AUDIO = "Not an audio file caracole reads (MP3, M4A, FLAC, WAV, Ogg or AIFF)."
TOO_BIG = "That file is too big: an audio file is 128 MiB at most; `caracole audio FILE` takes any."
TOO_LONG = "That file is longer than 30 minutes."
NO_ROOM = "No room to keep it here."
EMPTY = "That file is empty."
NO_NAME = "What is the file called? Its name is text."
WHICH = "Which upload? Its id is 16 hex."
GONE = "That upload is gone: it was left over an hour, or another file was chosen since. Choose it again."

# One change at a time to the staged uploads, of caracole serve's threads; re-entrant, so that a route may hold it
# (``held``) across what it reads of the queue and what it changes here.
_lock = threading.RLock()


def held() -> threading.RLock:
    """The staged uploads' lock, for a route to hold across a check and what it does after it: Make sheet's ``staged``
    and its job queued, a drop's check and its ``drop``; an upload passes ``stage`` and ``sweep`` a function of the
    jobs' uploads, which they call under it. So no upload lets go of a file a job is being queued for, and none
    holds the store while it reads a file."""
    return _lock


class AudioError(ValueError):
    """A file refused, or an upload that isn't there: why, in a sentence, and the status caracole serve answers it
    with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Audio:
    """What an audio file is: its format (a key of ``FORMATS``), its length in seconds, and its artist, title and
    album tags (None for a tag it hasn't)."""

    format: str
    duration: float
    tags: dict[str, str | None]


@dataclass(frozen=True)
class Staged:
    """An upload staged in the folder: its id, its file, the name it was sent under (a name to show), its size,
    SHA-256, format, length and tags, and when it came."""

    id: str
    path: Path
    name: str
    size: int
    sha256: str
    format: str
    duration: float
    tags: dict[str, str | None]
    at: float

    def record(self) -> dict[str, Any]:
        """What ``.upload-<id>.json`` holds of it."""
        kept = asdict(self)
        del kept["id"], kept["path"]
        return kept


def folder(cfg: Config) -> Path:
    """The folder of the audio files you give caracole, there or not."""
    return cfg.state_dir / FOLDER


# --- what a file is -----------------------------------------------------------------------------------------------


def sniff(head: bytes) -> str | None:
    """The format the first bytes of a file say it is (a key of ``FORMATS``), or None: an ID3 tag or an MPEG audio
    frame's header, MP3; ``ftyp`` with an MP4 audio brand (``_MP4_BRANDS``) as its major or a compatible one, M4A;
    ``fLaC``, FLAC; ``RIFF…WAVE``, WAV; ``OggS``, Ogg; ``FORM…AIFF`` or ``AIFC``, AIFF. A first gate alone: mutagen's
    read of the file decides (``_examine``)."""
    if head[:3] == b"ID3" or _mpeg_frame(head):
        return "MP3"
    if head[4:8] == b"ftyp" and _mp4_audio(head):
        return "M4A"
    if head[:4] == b"fLaC":
        return "FLAC"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "WAV"
    if head[:4] == b"OggS":
        return "Ogg"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "AIFF"
    return None


def _mpeg_frame(head: bytes) -> bool:
    """Whether ``head`` begins with an MPEG audio frame's header: its sync, and a version, layer, bitrate and sample
    rate that exist (ADTS's AAC, layer 0, is none)."""
    if len(head) < 3 or head[0] != 0xFF or head[1] & 0xE0 != 0xE0:
        return False
    version, layer = (head[1] >> 3) & 3, (head[1] >> 1) & 3
    return version != 1 and layer != 0 and head[2] >> 4 != 15 and (head[2] >> 2) & 3 != 3


def _mp4_audio(head: bytes) -> bool:
    """Whether an MP4 file's ``ftyp`` names an audio brand, as its major brand or a compatible one."""
    size = int.from_bytes(head[:4], "big")
    brands = [head[8:12]] + [head[at:at + 4] for at in range(16, min(size, len(head)) - 3, 4)]
    return any(brand in _MP4_BRANDS for brand in brands)


def _examine(f: IO[bytes]) -> Audio:
    """What the file open as ``f`` is: AudioError when its bytes are no format caracole reads, when mutagen can't
    read it as the one they say, or reads no length, or an MP4 with no audio track (415), and when it is longer than
    ``MAX_SECONDS`` (422).

    The bytes are anyone's, made to crash a reader as well as not: whatever mutagen raises on them is a refusal
    (mutagen 1.48's OggSpeex divides by its header's rate, unguarded), but an OSError reading a file of the disk,
    which is the disk's."""
    f.seek(0)
    fmt = sniff(f.read(HEAD))
    if fmt is None:
        raise AudioError(NOT_AUDIO, 415)
    for module, name in _READERS[fmt]:
        reader = getattr(importlib.import_module(module), name)  # here, not on import: the pages import this module
        f.seek(0)
        try:
            return _read(reader, f, fmt)
        except AudioError:
            raise
        except OSError:
            if not isinstance(f, io.BytesIO):
                raise
        except Exception:  # noqa: BLE001 (a file anyone may send: whatever it makes the reader raise)
            pass
    raise AudioError(NOT_AUDIO, 415)


def _read(reader: Any, f: IO[bytes], fmt: str) -> Audio:
    """The file ``f`` read by the mutagen class ``reader`` of the format ``fmt``: AudioError as ``_examine`` says;
    whatever else the reader raises, ``_examine``'s to judge."""
    from caracole.music import _ALBUM_KEYS, _ARTIST_KEYS, _TITLE_KEYS, _first

    read = reader(f)
    length = getattr(read.info, "length", None)
    if not isinstance(length, (int, float)) or not math.isfinite(length) or length <= 0:
        raise AudioError(NOT_AUDIO, 415)
    if fmt == "M4A" and not (read.info.channels > 0 and read.info.sample_rate > 0):
        # mutagen reads an MP4 with no sound track ('soun') as long as its movie: a video alone. A sound track's
        # sample entry gives its channels and rate, whatever its codec.
        raise AudioError(NOT_AUDIO, 415)
    if length > MAX_SECONDS:
        raise AudioError(TOO_LONG, 422)
    tags = read.tags
    named = {key: _first(tags, keys) if tags is not None else None
             for key, keys in (("artist", _ARTIST_KEYS), ("title", _TITLE_KEYS), ("album", _ALBUM_KEYS))}
    return Audio(fmt, float(length), named)


def examine(path: Path) -> Audio:
    """What the audio file at ``path`` (a file of your own) is, read as an upload's bytes are (``_examine``):
    AudioError for one caracole doesn't read, a folder or a device among them (415), or one longer than
    ``MAX_SECONDS`` (422); an OSError opening or reading it is the disk's."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise AudioError(NOT_AUDIO, 415)
    with open(fd, "rb") as f:
        return _examine(f)


def _display_name(name: object) -> str:
    """The name an upload was sent under, as a name to show: its last part, control characters out, 255 characters
    at most; never a path."""
    if not isinstance(name, str):
        return ""
    last = re.split(r"[/\\]", name)[-1]
    return "".join(c for c in last if unicodedata.category(c) != "Cc").strip()[:255]


# --- the folder -----------------------------------------------------------------------------------------------------


def _store(cfg: Config) -> Path:
    """The folder, made if it isn't there, 0700; AudioError (500) when its place holds a link or anything else."""
    path = folder(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        raise AudioError(f"{path} isn't a folder of caracole's own (a symbolic link, say): no audio file is kept "
                         "there.", 500) from e
    try:
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    return path


def _is_store(path: Path) -> bool:
    """Whether the folder is there, a folder and no link."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _room(root: Path, size: int) -> None:
    if disk_usage(root).free < 2 * size + ROOM:
        raise AudioError(NO_ROOM, 507)


def _create(path: Path) -> int:
    """A new file at ``path``, 0600, never through a link nor over anything there."""
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)


def _sync(root: Path) -> None:
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink(path: Path) -> bool:
    """``path`` deleted (a link itself, never what it points at); whether it was there."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    except IsADirectoryError:
        return False
    return True


# --- a staged upload ----------------------------------------------------------------------------------------------


def _check_id(upload_id: object) -> str:
    if not isinstance(upload_id, str) or not ID.fullmatch(upload_id):
        raise AudioError(WHICH)
    return upload_id


def _staged_ids(root: Path) -> set[str]:
    """The ids of the staged uploads in the folder, by their files' names alone: never one a keep began moving (its
    marker there), which is no staged upload to let go of but the marker's to finish (``keep``, ``sweep``)."""
    try:
        names = os.listdir(root)
    except OSError:
        return set()
    marked = {m.group("id") for m in map(_MARKER.fullmatch, names) if m is not None}
    return {m.group("id") for m in map(_PIECE.fullmatch, names) if m is not None} - marked


def _drop_pieces(root: Path, upload_id: str) -> bool:
    """A staged upload's files deleted, whatever they are; whether any was there."""
    gone = [_unlink(root / f"{_STAGED}{upload_id}{ext}") for ext in (*FORMATS.values(), ".json")]
    return any(gone)


def _touched(root: Path, upload_id: str) -> float:
    times = []
    for ext in (*FORMATS.values(), ".json"):
        try:
            times.append(os.lstat(root / f"{_STAGED}{upload_id}{ext}").st_mtime)
        except OSError:
            pass
    return max(times, default=0.0)


def _ids(named: Collection[str] | Callable[[], Collection[str]]) -> set[str]:
    return set(named() if callable(named) else named)


def stage(cfg: Config, data: bytes, name: str, *,
          named: Collection[str] | Callable[[], Collection[str]]) -> Staged:
    """An upload's bytes, sent under ``name``, staged in the folder until a job keeps them as a song's audio
    (``keep(move=True)``). The bytes are read (their format, length and digest) before the store's lock is taken;
    under it, first every other staged upload goes that ``named`` (the ids the waiting and running jobs name, or a
    function giving them, called under the lock: as they are then) doesn't hold, so that at most one no job names waits. AudioError, nothing written: no name or no bytes
    (400), past ``AUDIO_MAX`` (413), not an audio file caracole reads (415), longer than ``MAX_SECONDS`` (422), no
    room (507)."""
    shown = _display_name(name)
    if not shown:
        raise AudioError(NO_NAME)
    if not data:
        raise AudioError(EMPTY)
    if len(data) > AUDIO_MAX:
        raise AudioError(TOO_BIG, 413)
    found = _examine(io.BytesIO(data))
    digest = hashlib.sha256(data).hexdigest()
    with _lock:
        root = _store(cfg)
        for upload_id in _staged_ids(root) - _ids(named):
            _drop_pieces(root, upload_id)
        _room(root, len(data))
        while True:
            upload_id = secrets.token_hex(8)
            path = root / f"{_STAGED}{upload_id}{FORMATS[found.format]}"
            try:
                fd = _create(path)
                break
            except FileExistsError:
                continue
        up = Staged(upload_id, path, shown, len(data), digest, found.format, found.duration, found.tags, time.time())
        try:
            with open(fd, "wb") as f:
                f.write(data)
            with open(_create(root / f"{_STAGED}{upload_id}.json"), "wb") as f:
                f.write(json.dumps(up.record()).encode())
        except BaseException:
            _drop_pieces(root, upload_id)
            raise
    return up


def _read_json(path: Path) -> Any:
    """A small JSON file of the folder, read never through a link; None when it is gone or isn't JSON."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    with open(fd, "rb") as f:
        data = f.read(_RECORD_MAX + 1)
    try:
        return json.loads(data) if len(data) <= _RECORD_MAX else None
    except (ValueError, RecursionError):
        return None


def _read_record(path: Path) -> dict[str, Any] | None:
    """A staged upload's record, read never through a link; None when it is gone or isn't one."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    with open(fd, "rb") as f:
        data = f.read(_RECORD_MAX + 1)
    try:
        record = json.loads(data) if len(data) <= _RECORD_MAX else None
    except (ValueError, RecursionError):
        return None
    if not isinstance(record, dict):
        return None
    tags = record.get("tags")
    ok = (isinstance(record.get("name"), str) and type(record.get("size")) is int
          and isinstance(record.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
          and record.get("format") in FORMATS and type(record.get("duration")) in (int, float)
          and type(record.get("at")) in (int, float) and isinstance(tags, dict)
          and set(tags) == {"artist", "title", "album"} and all(v is None or isinstance(v, str) for v in tags.values()))
    return record if ok else None


def staged(cfg: Config, upload_id: str) -> Staged:
    """The staged upload ``upload_id`` names: AudioError for an id that isn't 16 hex (400), and for none here (404):
    no record of it, no audio file or more than one under its id, or one that isn't a regular file (a link planted
    in its place), or that isn't what its record says."""
    _check_id(upload_id)
    root = folder(cfg)
    if not _is_store(root):
        raise AudioError(GONE, 404)
    there = [ext for ext in FORMATS.values() if os.path.lexists(root / f"{_STAGED}{upload_id}{ext}")]
    record = _read_record(root / f"{_STAGED}{upload_id}.json")
    if len(there) != 1 or record is None or FORMATS[record["format"]] != there[0]:
        raise AudioError(GONE, 404)
    path = root / f"{_STAGED}{upload_id}{there[0]}"
    try:
        entry = os.lstat(path)
    except OSError:
        raise AudioError(GONE, 404) from None
    if not stat.S_ISREG(entry.st_mode) or entry.st_size != record["size"]:
        raise AudioError(GONE, 404)
    return Staged(upload_id, path, record["name"], record["size"], record["sha256"], record["format"],
                  float(record["duration"]), record["tags"], float(record["at"]))


def gone(cfg: Config, upload_id: str | None) -> bool:
    """Whether ``upload_id`` is a well-formed id that names no staged upload (``staged``'s 404), never one that isn't
    an id (400)."""
    if upload_id is None or not ID.fullmatch(upload_id):
        return False
    try:
        staged(cfg, upload_id)
    except AudioError as e:
        return e.status == 404
    return False


@dataclass(frozen=True)
class Marked:
    """A moved upload's marker (``.upload-<id>.kept``): the kept file it became (``path``, in the folder), the song it
    was kept for (``song``), when (``at``), and whether its keep is over (``done``: the song's row named the file and
    the staged record went)."""

    upload: str
    path: Path
    song: int
    at: float
    done: bool


def _marker(root: Path, upload_id: str) -> Path:
    return root / f"{_STAGED}{upload_id}.kept"


def _write_marker(root: Path, upload_id: str, kept: Path, song_id: int) -> None:
    """The marker written whole (a temporary name, then a rename over any before it), before the data's move."""
    part = root / f".keep-{secrets.token_hex(8)}.part"
    try:
        with open(_create(part), "wb") as f:
            f.write(json.dumps({"kept": kept.name, "song": song_id, "at": time.time()}).encode())
            f.flush()
            os.fsync(f.fileno())
        os.rename(part, _marker(root, upload_id))
    except BaseException:
        _unlink(part)
        raise


def _read_marker(root: Path, upload_id: str) -> Marked | None:
    record = _read_json(_marker(root, upload_id))
    if (not isinstance(record, dict) or not isinstance(record.get("kept"), str) or not KEPT.fullmatch(record["kept"])
            or type(record.get("song")) is not int or type(record.get("at")) not in (int, float)):
        return None
    done = not os.path.lexists(root / f"{_STAGED}{upload_id}.json")
    return Marked(upload_id, root / record["kept"], record["song"], float(record["at"]), done)


def marked(cfg: Config, upload_id: str | None) -> Marked | None:
    """The marker of an upload a keep moved (or began moving) into place, while the kept file it names is a regular
    file of the folder; None for none: an id never kept, a marker let go, or its file gone. ``keep`` writes it before
    the move, so that a job cut off at any point, asked again, finishes or knows its upload is the song's audio; it is
    kept ``MARKED`` (the Journal's 30 days, as long as Try again can come), then ``sweep`` lets it go."""
    if upload_id is None or not ID.fullmatch(upload_id):
        return None
    root = folder(cfg)
    if not _is_store(root):
        return None
    found = _read_marker(root, upload_id)
    return found if found is not None and _regular(found.path) else None


def _markers(root: Path) -> list[str]:
    try:
        return sorted(m.group("id") for m in map(_MARKER.fullmatch, os.listdir(root)) if m is not None)
    except OSError:
        return []


def _live_kept(root: Path) -> set[str]:
    """The kept files' names the markers of keeps not over name: ``tidy`` spares them for that keep's retry."""
    return {found.path.name for upload_id in _markers(root)
            if (found := _read_marker(root, upload_id)) is not None and not found.done}


def drop(cfg: Config, upload_id: str) -> None:
    """The staged upload ``upload_id`` deleted now, whatever is left of it (the page's Cancel); AudioError for an id
    that isn't 16 hex (400), or for none here (404)."""
    _check_id(upload_id)
    with _lock:
        root = folder(cfg)
        if not _is_store(root) or not _drop_pieces(root, upload_id):
            raise AudioError(GONE, 404)


def sweep(cfg: Config, named: Collection[str] | Callable[[], Collection[str]], *,
          now: float | None = None) -> list[str]:
    """Delete each staged upload left ``EXPIRES`` (an hour) that ``named`` (the ids the waiting and running jobs name,
    or a function giving them, called under the lock) doesn't hold, whatever is left of it; the ids deleted. A moved
    upload's marker (``marked``) is no staged upload: it goes, with what is left of its upload, ``MARKED`` (30 days)
    after its keep, and before that only once the kept file it names and its staged data are both gone and no job
    names its id. A marker is written before the data's move, so one whose kept file isn't there yet, with the data
    still staged, is a keep under way or cut off: left whole for it, or for its job asked again."""
    now = time.time() if now is None else now
    with _lock:
        root = folder(cfg)
        if not _is_store(root):
            return []
        held = _ids(named)
        gone = sorted(upload_id for upload_id in _staged_ids(root) - held
                      if now - _touched(root, upload_id) > EXPIRES)
        for upload_id in gone:
            _drop_pieces(root, upload_id)
        for upload_id in _markers(root):
            found = _read_marker(root, upload_id)
            marker = _marker(root, upload_id)
            try:
                at = found.at if found is not None else os.lstat(marker).st_mtime
            except OSError:
                continue
            data = any(os.path.lexists(root / f"{_STAGED}{upload_id}{ext}") for ext in FORMATS.values())
            if now - at > MARKED:
                pass  # past the Journal's history: its job can't be asked again
            elif data or upload_id in held or (found is not None and _regular(found.path)):
                continue  # a keep's to finish (written before the move, or a job on it), or Try again's to come
            _drop_pieces(root, upload_id)
            _unlink(marker)
    return gone


# --- a song's own audio ---------------------------------------------------------------------------------------------


def kept_in(store: Path, audio_path: str | None) -> Path | None:
    """The kept file ``audio_path`` names in the folder ``store``, as ``store`` spells it: a regular file of that
    folder (no link) by a kept file's name, however the path spells the folder (a link to the state directory, a
    "..": another process's config may); None for any other path, or none."""
    if not audio_path:
        return None
    path = Path(audio_path)
    if not KEPT.fullmatch(path.name) or not _is_store(store) or not _regular(path):
        return None
    try:
        same = os.path.samefile(path.parent, store)
    except OSError:
        return None
    return store / path.name if same else None


def given_file(audio_path: str | None) -> bool:
    """Whether ``audio_path`` names a file you gave a song, with no config at hand (songs.py's ``_merge``, under a
    re-keying any command may run): a regular file by a kept file's name in a folder named as the store is. A
    purchase in Music/ is never named so; a false one (a file named so in a folder named so elsewhere) could only be
    taken as a merged song's audio: nothing outside the store is ever deleted or moved (``kept_in`` and ``tidy`` touch
    the store's files alone)."""
    if not audio_path:
        return False
    path = Path(audio_path)
    return bool(KEPT.fullmatch(path.name)) and path.parent.name == FOLDER and _regular(path)


def uploaded(cfg: Config, song: Song) -> Path | None:
    """The file you gave the song, when its audio is one (a kept file of the folder), else None: a purchase,
    YouTube's audio, or none."""
    return kept_in(folder(cfg), song.audio_path)


def _hash(f: IO[bytes], into: IO[bytes] | None = None) -> str:
    f.seek(0)
    digest = hashlib.sha256()
    while chunk := f.read(1 << 20):
        digest.update(chunk)
        if into is not None:
            into.write(chunk)
    return digest.hexdigest()


def keep(cfg: Config, conn: sqlite3.Connection, song: Song, source: Path, *, move: bool) -> Path:
    """The file at ``source`` kept as the song's audio, whatever it had (an upload always wins), and its path in the
    folder, ``<song id>-<sha256 16 hex><ext>``: a staged upload moved there (``move``: its record goes too), or a file
    of your own copied there, read as an upload is read. The song's ``audio_path`` and ``audio_mtime`` name it, and
    the file it had there before goes (a purchase's in Music/ never: only an upload). The same file again is the
    song's audio already: the path it has, nothing changed.

    Moved, the upload's marker (``.upload-<id>.kept``, naming the kept file and the song) is written before the data's
    move, and the staged record goes only once the song's row names the kept file, so that at every point of a kill
    the same job again finishes: the staged data still there, ``staged`` answers it and the move is done; moved and the
    row not written, ``adopt``; all of it done, the marker says the upload is the song's audio (``marked``). A kept
    file another song's row names too is never deleted (``_named_by_another``).

    AudioError: a song no longer in the book (404), nothing read or moved; with ``move``, a ``source`` that isn't a
    staged upload's regular file (404); a file caracole doesn't read (415), longer than ``MAX_SECONDS`` (422), or,
    copied, for which the disk has no room (507). Run under caracole's lock, as ``tidy`` is."""
    try:
        current = get_song(conn, song.id)
    except KeyError:
        raise AudioError(f"{song.display} isn't in the book any more.", 404) from None
    source = Path(source)
    root = folder(cfg)
    staged_audio = _STAGED_AUDIO.fullmatch(source.name)
    if move and (source.parent != root or staged_audio is None or not _is_store(root)):
        raise AudioError(GONE, 404)
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK | (os.O_NOFOLLOW if move else 0))
    except OSError:
        if move:
            raise AudioError(GONE, 404) from None
        raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):  # a folder, a device
        os.close(fd)
        raise AudioError(GONE, 404) if move else AudioError(NOT_AUDIO, 415)
    with open(fd, "rb") as f:
        found = _examine(f)
        ext = FORMATS[found.format]
        if move:
            kept = root / f"{current.id}-{_hash(f)[:16]}{ext}"
            _write_marker(root, staged_audio.group("id"), kept, current.id)
            if _regular(kept):
                _unlink(source)  # the song's audio already
            else:
                os.rename(source, kept)
        else:
            root = _store(cfg)
            _room(root, os.fstat(f.fileno()).st_size)
            part = root / f".keep-{secrets.token_hex(8)}.part"
            try:
                with open(_create(part), "wb") as out:
                    digest = _hash(f, out)
                    out.flush()
                    os.fsync(out.fileno())
                kept = root / f"{current.id}-{digest[:16]}{ext}"
                if _regular(kept):
                    _unlink(part)  # the song's audio already
                else:
                    os.rename(part, kept)
            except BaseException:
                _unlink(part)
                raise
    _sync(root)
    return _named(conn, root, current, kept, staged_audio.group("id") if move else None)


def _named(conn: sqlite3.Connection, root: Path, current: Song, kept: Path, upload_id: str | None) -> Path:
    """The song's row naming the kept file, then the staged record let go (a moved upload's keep over), then the file
    the song had there before, unless another song's row names it."""
    mtime = os.lstat(kept).st_mtime
    if (current.audio_path, current.audio_mtime) != (str(kept), mtime):
        update_song(conn, current.id, audio_path=str(kept), audio_mtime=mtime)
    if upload_id is not None:
        _unlink(root / f"{_STAGED}{upload_id}.json")  # the row names the kept file now
    earlier = kept_in(root, current.audio_path)
    if earlier is not None and earlier != kept and not _named_by_another(conn, earlier, current.id):
        _unlink(earlier)
    return kept


def adopt(cfg: Config, conn: sqlite3.Connection, song: Song, upload_id: str) -> Path:
    """The kept file an upload's marker names, made the song's audio: for a keep cut off after the move and before the
    song's row named it (its staged record still there). That exact name alone, kept for this song; AudioError (404,
    "gone") for anything else: no marker, another song's, the file not a regular one, a keep already over."""
    root = folder(cfg)
    found = _read_marker(root, upload_id) if ID.fullmatch(upload_id or "") and _is_store(root) else None
    if found is None or found.done or found.song != song.id or not _regular(found.path):
        raise AudioError(GONE, 404)
    try:
        current = get_song(conn, song.id)
    except KeyError:
        raise AudioError(f"{song.display} isn't in the book any more.", 404) from None
    examine(found.path)  # still audio caracole reads
    return _named(conn, root, current, found.path, upload_id)


def _named_by_another(conn: sqlite3.Connection, path: Path, song_id: int) -> bool:
    """Whether a song other than ``song_id``'s row names the kept file ``path`` (by its name: a kept file's name is
    unique in the folder, however a row spells the folder)."""
    tail = "/" + path.name
    return conn.execute("SELECT 1 FROM songs WHERE id != ? AND (audio_path = ? OR substr(audio_path, -?) = ?) LIMIT 1",
                        (song_id, str(path), len(tail), tail)).fetchone() is not None


def named_by_another(conn: sqlite3.Connection, path: Path, song_id: int) -> bool:
    """``_named_by_another``, for removal.py: a song's given file another song's row names too stays."""
    return _named_by_another(conn, path, song_id)


def tidy(conn: sqlite3.Connection, cfg: Config) -> int:
    """Delete the kept files no song's ``audio_path`` names (an upload a newer one replaced, a song removed, the older
    of two uploads a merge met: songs.py ``_merge`` gives the merged song the one given last), and the copies a
    stopped ``keep`` left; how many files went. A kept file the marker of a keep not over names (cut off between its
    move and the song's row) stays for that keep's retry. A kept file's name holds the id of the song it was kept for, which a
    merge leaves as it is: every reader goes by a song's ``audio_path``, never by that id. The staged uploads are caracole
    serve's (``sweep``), and any other file stays. Run under caracole's lock, as ``keep`` is."""
    root = folder(cfg)
    if not _is_store(root):
        return 0
    # By the files' names alone, however a path spells the folder (a kept file's name is unique in it): a name a song
    # names elsewhere keeps a file, never deletes one.
    named = {Path(path).name for (path,) in conn.execute("SELECT audio_path FROM songs WHERE audio_path IS NOT NULL")}
    pending = _live_kept(root)  # moved by a keep cut off before the song's row named it: that keep's to finish
    deleted = 0
    with os.scandir(root) as entries:
        for entry in list(entries):
            mine = (KEPT.fullmatch(entry.name) and entry.name not in named and entry.name not in pending
                    ) or _PART.fullmatch(entry.name)
            if not mine or entry.is_dir(follow_symlinks=False):
                continue
            try:
                if _unlink(Path(entry.path)):
                    deleted += 1
                    log.info("Let go of %s: no song's audio is that file now.", entry.path)
            except OSError as e:
                log.warning("Couldn't delete %s: %s", entry.path, e)
    return deleted
