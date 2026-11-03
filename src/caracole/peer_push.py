"""A push: the units another caracole (the phone's) gives this one, staged by ``caracole serve`` and then taken by
``caracole peer take`` (web/peer_routes.py; the plan: docs/superpowers/plans/2026-11-03-android-port-m1-m3.md §5.3).

The phone starts every sync and serves nothing to the network, so it can't be asked to pull: it takes what it takes
from this side (peer_sync.py's reads), then pushes what this side takes, in three requests, each with the form token
in its header (web/app.py's ``json`` and ``bytes`` routes):

1. ``POST /peer/push/new`` names the files its units keep, by their SHA-256 (``new_push``). This side opens a folder
   for the push, ``state_dir/peer/push-<id>/`` (0700), and answers its id and the files it has no readable copy of,
   ``need`` (``kept_copy``: a kept file here whose bytes have that SHA-256).
2. ``POST /peer/push/file?push=&sha256=``, once a file needed: its bytes, checked by their SHA-256 and kept as
   ``files/<sha256>`` (``stage_file``).
3. ``POST /peer/push?push=``: the push document (``read_push_document``), kept as ``push.json``; then ``caracole peer
   take DIR`` is queued, which takes its units from a ``StagedSource``, as a pull takes a peer's, and deletes the
   folder once it is over.

Nothing of it goes into the library, and caracole serve writes nothing else for a push (AGENTS.md). A push's id is
16 hex and a file's SHA-256 64 hex, both checked before any path is built of them (``_folder`` builds the one path
an id names). At most ``OPEN`` (2) pushes are open, not sent yet, at once; a file is at most ``FILE_MAX`` (64 MiB)
and a push's files ``PUSH_MAX`` (2 GiB). A push untouched for ``EXPIRES`` (an hour) is deleted the next time a push
is opened (``sweep``), unless a take holds it (``held``).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caracole import peer_sync as sync

ID = re.compile(r"[0-9a-f]{16}")  # a push's id, and a caracole's (kv sync:id: db.py's schema 15, peer_sync.new_id)
SHA256 = re.compile(r"[0-9a-f]{64}")
OPEN = 2  # pushes open at once, at most
FILE_MAX = 64 * 1024 * 1024  # a file's bytes, at most (POST /peer/push/file's limit)
PUSH_MAX = 2 * 1024 ** 3  # a push's files' bytes, at most
NEW_MAX = 1024 * 1024  # POST /peer/push/new's document, at most
DOCUMENT_MAX = 16 * 1024 * 1024  # POST /peer/push's, at most
EXPIRES = 3600.0  # seconds a push is left untouched before it is deleted
FOLDER = "peer"  # under state_dir
PREFIX = "push-"
NEW = "new.json"  # who opened the push, the files it named and those this side needed
DOCUMENT = "push.json"  # the push document, once sent
FILES = "files"  # the files sent, each named by its SHA-256

_lock = threading.Lock()  # one change at a time to the pushes, of caracole serve's threads


class PushError(ValueError):
    """A push, or a part of one, refused: why, in a sentence, and the status caracole serve answers it with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check_id(push_id: str) -> str:
    if not isinstance(push_id, str) or not ID.fullmatch(push_id):
        raise PushError("Which push? Its id is 16 hex.")
    return push_id


def check_sha256(digest: str) -> str:
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise PushError("Which file? Its SHA-256 is 64 hex.")
    return digest


def _folder(state_dir: Path, push_id: str) -> Path:
    """The folder of the push ``push_id`` names: the one path built of an id, once it is checked."""
    return state_dir / FOLDER / (PREFIX + check_id(push_id))


def _private_dir(path: Path) -> None:
    """``path`` made a folder only its owner reads, whatever the umask."""
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _write_private(path: Path, data: bytes) -> None:
    """``data`` written to ``path`` through a temporary name of its own, created exclusively, 0600, then renamed."""
    part = path.with_name(f".{path.name}.{secrets.token_hex(6)}.part")
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with open(fd, "wb") as f:
            f.write(data)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def _read_json(path: Path) -> Any:
    """What a file of a push's folder holds, as JSON; None when it is gone or can't be read."""
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError, RecursionError):
        return None


# --- a push opened, and its files -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Opened:
    """A push just opened: its id, and the files this side needs sent (``POST /peer/push/new``'s answer)."""

    push: str
    need: list[str]


def read_new(data: Any) -> tuple[str, list[str]]:
    """``POST /peer/push/new``'s document, ``{"format", "from", "files"}``, read: who pushes (its caracole's id) and
    the files its units keep (each SHA-256 once, in order). PushError for anything else."""
    if not isinstance(data, Mapping) or data.get("format") != sync.FORMAT:
        raise PushError(f"That isn't a push of format {sync.FORMAT} (the other caracole may be of another version).")
    sender, files = data.get("from"), data.get("files")
    if not isinstance(sender, str) or not ID.fullmatch(sender):
        raise PushError("Who pushes? Its caracole's id is 16 hex.")
    if not isinstance(files, list):
        raise PushError("Which files? A push lists them, by their SHA-256.")
    return sender, list(dict.fromkeys(check_sha256(f) for f in files))


def kept_copy(conn: sqlite3.Connection | None, library_dir: Path, digest: str) -> bytes | None:
    """The bytes of a file kept here (``files``) whose SHA-256 is ``digest``, read from the library as it is now (no
    link followed), or None: a push needs no file this side can read already."""
    from caracole.library import read_regular

    if conn is None:
        return None
    for (path,) in conn.execute("SELECT path FROM files WHERE sha256 = ? ORDER BY id", (digest,)):
        try:
            data = read_regular(library_dir / path)
        except (OSError, ValueError):
            continue
        if hashlib.sha256(data).hexdigest() == digest:
            return data
    return None


def new_push(state_dir: Path, conn: sqlite3.Connection | None, library_dir: Path, *, sender: str,
             files: Sequence[str], own: str | None, now: float | None = None) -> Opened:
    """A push opened for ``sender`` (``read_new``'s), which names ``files``: its folder made, with what it needs;
    PushError when ``sender`` is this caracole (``own``, its id), or with ``OPEN`` pushes open already (409). Pushes
    left untouched for an hour go first (``sweep``)."""
    if own is not None and sender == own:
        raise PushError("That push comes from this caracole itself (the same id): its database is a copy of this "
                        "one's. Give one of them another: caracole peer new-id.")
    need = [f for f in files if kept_copy(conn, library_dir, f) is None]
    sweep(state_dir, now)
    with _lock:
        root = state_dir / FOLDER
        if sum(1 for p in _pushes(root) if not (p / DOCUMENT).exists()) >= OPEN:
            raise PushError("Two pushes are open already: try again once one is sent, or in an hour.", 409)
        state_dir.mkdir(parents=True, exist_ok=True)
        _private_dir(root)
        while True:
            push_id = secrets.token_hex(8)
            folder = _folder(state_dir, push_id)
            try:
                folder.mkdir(mode=0o700)
                break
            except FileExistsError:
                continue
        os.chmod(folder, 0o700)
        _private_dir(folder / FILES)
        _write_private(folder / NEW, json.dumps({"from": sender, "files": list(files), "need": need}).encode())
    return Opened(push_id, need)


def stage_file(state_dir: Path, push_id: str, digest: str, data: bytes) -> None:
    """A file the push ``push_id`` needs, kept as ``files/<digest>`` once its bytes have that SHA-256; PushError when
    the push isn't open, or doesn't need it, or its files would pass ``PUSH_MAX``. A file staged already is as it
    was."""
    check_id(push_id)
    check_sha256(digest)
    if hashlib.sha256(data).hexdigest() != digest:
        raise PushError("Those bytes aren't the file of that SHA-256.")
    with _lock:
        folder = _folder(state_dir, push_id)
        opened = _read_json(folder / NEW)
        if not isinstance(opened, Mapping):
            raise PushError("No such push is open here: open another (POST /peer/push/new).")
        if (folder / DOCUMENT).exists():
            raise PushError("That push is sent already: it takes no more files.")
        if digest not in opened.get("need", ()):
            raise PushError("That push doesn't need that file: this side has it, or the push never named it.")
        target = folder / FILES / digest
        if target.exists():
            return
        if _staged_bytes(folder) + len(data) > PUSH_MAX:
            raise PushError("That push's files would pass 2 GiB: push fewer changes at a time.")
        _write_private(target, data)


def _staged_bytes(folder: Path) -> int:
    try:
        return sum(entry.stat(follow_symlinks=False).st_size for entry in os.scandir(folder / FILES))
    except FileNotFoundError:
        return 0


# --- pushes left, and a take's hold on one -----------------------------------------------------------------------


def _pushes(root: Path) -> list[Path]:
    """The pushes' folders under ``root`` (state_dir/peer), by their names alone: nothing else there is one."""
    try:
        entries = list(os.scandir(root))
    except FileNotFoundError:
        return []
    return [Path(e.path) for e in entries if e.name.startswith(PREFIX) and ID.fullmatch(e.name[len(PREFIX):])
            and e.is_dir(follow_symlinks=False)]


def _touched(folder: Path) -> float:
    """When the push in ``folder`` last changed: opened, a file staged, or sent."""
    times = []
    for path in (folder, folder / FILES, folder / NEW, folder / DOCUMENT):
        try:
            times.append(os.lstat(path).st_mtime)
        except FileNotFoundError:
            pass
    return max(times, default=0.0)


def sweep(state_dir: Path, now: float | None = None) -> list[str]:
    """Delete each push untouched for ``EXPIRES``, sent or not, unless a take holds it (``held``); the ids deleted."""
    now = time.time() if now is None else now
    gone = []
    with _lock:
        for folder in _pushes(state_dir / FOLDER):
            if now - _touched(folder) <= EXPIRES:
                continue
            with _unless_held(folder) as free:
                if free:
                    shutil.rmtree(folder, ignore_errors=True)
                    gone.append(folder.name[len(PREFIX):])
    return gone


@contextmanager
def _unless_held(folder: Path) -> Iterator[bool]:
    """Whether no take holds the push in ``folder`` (``held``), kept so for the block."""
    try:
        fd = os.open(folder / DOCUMENT, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        yield True  # not sent: no take holds it
        return
    except OSError:
        yield False
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


@contextmanager
def held(folder: Path) -> Iterator[None]:
    """The push sent in ``folder`` held for a take, so that no ``sweep`` deletes it meanwhile; PushError when it is
    gone (deleted, left over an hour) or was never sent."""
    try:
        fd = os.open(folder / DOCUMENT, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise PushError("That push is gone: it was never sent, or was left over an hour. Sync again.") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if not (folder / DOCUMENT).exists():  # a sweep deleted it as the take came
            raise PushError("That push is gone: it was left over an hour. Sync again.")
        yield
    finally:
        os.close(fd)


# --- the push document ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Taken:
    """A unit the push gives: its id, this side's digest of it as the pusher compared it (``expected``), the pusher's
    digest of it now and its document (``/api/peer/unit``'s ``unit``), each None for a unit it hasn't got."""

    id: str
    expected: str | None
    digest: str | None
    unit: Mapping[str, Any] | None


@dataclass(frozen=True)
class Push:
    """A push document read back (``read_push_document``): who pushes (its id, its library's name, its caracole's
    version), this side's time in the state it compared (``at``), its whole state after its own take (``units``), and
    the units this side takes (``take``)."""

    sender: str
    name: str
    version: str
    at: str
    units: dict[str, sync.Unit]
    take: tuple[Taken, ...]

    def files(self) -> set[str]:
        """The SHA-256 of every file a song document of ``take`` keeps; PushError for a song document that names
        them otherwise."""
        found: set[str] = set()
        for taken in self.take:
            if taken.unit is None or taken.id.partition("/")[0] != "song":
                continue
            versions = taken.unit.get("versions")
            if not isinstance(versions, list):
                raise PushError(f"{taken.id[:200]}: a song with no versions to read.")
            for version in versions:
                files = version.get("files") if isinstance(version, Mapping) else None
                if not isinstance(files, list) or not all(isinstance(f, Mapping) for f in files):
                    raise PushError(f"{taken.id[:200]}: a version whose files can't be read.")
                found.update(check_sha256(f.get("sha256")) for f in files)
        return found


def read_push_document(data: Any) -> Push:
    """``POST /peer/push``'s document read: ``{"format", "from", "name", "caracole", "at", "units": {id: {label,
    digest}}, "take": [{id, expected, digest, unit}]}``, each unit given once, a document with each digest and none
    without, and each digest the one its state gives it. PushError for anything else."""
    if not isinstance(data, Mapping) or data.get("format") != sync.FORMAT:
        raise PushError(f"That isn't a push of format {sync.FORMAT} (the other caracole may be of another version).")
    sender, name, version, at = data.get("from"), data.get("name"), data.get("caracole"), data.get("at")
    if not isinstance(sender, str) or not ID.fullmatch(sender):
        raise PushError("Who pushes? Its caracole's id is 16 hex.")
    if not (isinstance(name, str) and isinstance(version, str) and isinstance(at, str) and at):
        raise PushError("A push says its library's name, its caracole's version and when it compared.")
    try:
        state = sync.read_state_document({"format": sync.FORMAT, "server": sender, "caracole": version, "name": name,
                                          "units": data.get("units")})
    except sync.StateError as e:
        raise PushError(f"Its state can't be read: {e}.") from None
    entries = data.get("take")
    if not isinstance(entries, list):
        raise PushError("What does it give? A push lists its units to take.")
    take: list[Taken] = []
    for entry in entries:
        take.append(_taken(entry, state.units))
    ids = [t.id for t in take]
    if len(set(ids)) != len(ids):
        raise PushError("A push gives each unit once.")
    return Push(sender, name, version, at, state.units, tuple(take))


def _taken(entry: Any, units: Mapping[str, sync.Unit]) -> Taken:
    if not isinstance(entry, Mapping):
        raise PushError("A unit to take that can't be read.")
    unit_id, expected, digest, unit = entry.get("id"), entry.get("expected"), entry.get("digest"), entry.get("unit")
    if not isinstance(unit_id, str) or "/" not in unit_id or len(unit_id) > 1000:
        raise PushError("A unit to take with no id to read.")
    for value in (expected, digest):
        if value is not None and not (isinstance(value, str) and SHA256.fullmatch(value)):
            raise PushError(f"{unit_id[:200]}: a digest that can't be read.")
    if (digest is None) != (unit is None) or not (unit is None or isinstance(unit, Mapping)):
        raise PushError(f"{unit_id[:200]}: a document goes with a digest, and none with none.")
    if digest != (units[unit_id].digest if unit_id in units else None):
        raise PushError(f"{unit_id[:200]}: given other than its state says.")
    return Taken(unit_id, expected, digest, unit)


# --- a push taken -------------------------------------------------------------------------------------------------


class StagedSource:
    """A push's units as ``peer_sync.apply_units`` takes them, as it takes a peer's (its ``UnitSource``, as
    ``peer_sync.Peer`` is one): each unit's document from the push (``push``, its folder's ``push.json`` read), each
    file as staged in ``folder``, else a copy kept here (``kept_copy``), checked by its SHA-256."""

    def __init__(self, folder: Path, push: Push, conn: sqlite3.Connection | None, library_dir: Path):
        self.folder = folder
        self.push = push
        self._conn = conn
        self._library_dir = library_dir
        self._take = {t.id: t for t in push.take}

    def unit(self, unit_id: str) -> dict[str, Any] | None:
        """The unit's document as the push gives it (``GET /api/peer/unit``'s ``"unit"``), or None for a unit it
        hasn't got."""
        taken = self._take.get(unit_id)
        return None if taken is None or taken.unit is None else dict(taken.unit)

    def file(self, key: str, name: str, sha256: str) -> bytes:
        """A kept file of the song of ``key``, by its SHA-256: sent with the push, or kept here; PeerError else."""
        from caracole.library import read_regular

        check_sha256(sha256)
        try:
            data = read_regular(self.folder / FILES / sha256)
        except FileNotFoundError:
            data = kept_copy(self._conn, self._library_dir, sha256)
        except (OSError, ValueError):
            data = None
        if data is None or hashlib.sha256(data).hexdigest() != sha256:
            raise sync.PeerError(f"{name} wasn't sent with the push, nor is it kept here as it was: the song is "
                                 "left as it was here.")
        return data
