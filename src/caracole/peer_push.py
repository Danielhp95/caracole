"""A push: the units another caracole (the phone's) gives this one, staged by ``caracole serve`` and then taken by
``caracole peer take`` (web/peer_routes.py; the plan: docs/superpowers/plans/2026-11-03-android-port-m1-m3.md §5.3).

The phone starts every sync and serves nothing to the network, so it can't be asked to pull: it takes what it takes
from this side (peer_sync.py's reads), then pushes what this side takes, in three requests, each with the form token
in its header (web/app.py's ``json`` and ``bytes`` routes):

1. ``POST /peer/push/new`` names the files its units keep, by their SHA-256 (``read_new``, ``needed``,
   ``new_push``). This side opens a folder for the push, ``state_dir/peer/push-<id>/`` (0700), and answers its id
   and the files it has no readable copy of, ``need`` (``kept_copy``: a kept file here whose bytes have that
   SHA-256).
2. ``POST /peer/push/file?push=&sha256=``, once a file needed: its bytes, checked by their SHA-256 and kept as
   ``files/<sha256>`` (``stage_file``).
3. ``POST /peer/push?push=``: the push document (``read_push_document``: refused, 409, from a caracole whose songs
   are keyed by other rules, its ``key_version``), each unit's document checked against its digest
   (``check_digests``) and each file its songs keep staged or kept here, then kept as ``push.json``
   (``send``); ``caracole peer take DIR`` is queued, which takes its units from a ``StagedSource``, as a pull takes
   a peer's, and deletes the folder once it is over.

A push that fails after it is opened (a file or its document refused, a network that drops) is let go of at once:
``POST /peer/push/drop`` (``drop``) deletes a push never sent, asked by whoever opened it, as a send is (its id, and
the caracole that opened it), never one whose document was taken (409: its take waits or runs). The pusher asks it on
any failure after ``push/new``, and a sender's next ``push/new`` lets go of its earlier push never sent too: a sender
holds one open push at a time, so that a push that stops never holds a slot here for the hour.

Nothing of it goes into the library, and caracole serve writes nothing else for a push (AGENTS.md). A push's id is
16 hex and a file's SHA-256 64 hex, both checked before any path is built of them (``_folder`` builds the one path
an id names, and ``sent_folder`` checks the one a take is given). At most ``OPEN`` (2) pushes are here at once, open
or sent and not taken yet, one never sent of each sender at most; a file is at most ``FILE_MAX`` (64 MiB) and a
push's files ``PUSH_MAX`` (2 GiB). A push untouched for ``EXPIRES`` (an hour), sent or not, is deleted (``sweep``:
when caracole serve starts, at each of the three requests, and as a take ends), unless a take holds it (``held``).

A caracole pushes to another as the phone does (``Pusher``, ``push_units``), so ``caracole peer sync --push`` gives
the other side its units with no need for it to reach this one: in as many pushes as the other side's limits ask
(``_cut``), each taken there before the next is opened, a song with a kept file past ``FILE_MAX`` left out.

**The phone's index pages** (``POST /peer/index``): an index export of the pages its lookups read
(``index_transfer.export(pages=)``), at most ``INDEX_MAX`` (64 MiB), whose bytes must open as a SQLite file's, kept
as ``state_dir/peer/index-<16 hex>.sqlite`` (0600, ``stage_index``) for ``caracole index merge --delete --progress``,
which deletes it once it is merged or refused. At most ``INDEX_OPEN`` (2) wait at once (409 for another); one an
hour old that no queued or running request names is deleted as the next comes (``sweep_indexes``).
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
import stat
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caracole import normalize, stamps
from caracole import peer_sync as sync

ID = re.compile(r"[0-9a-f]{16}")  # a push's id, and a caracole's (kv sync:id: db.py's schema 15, peer_sync.new_id)
SHA256 = re.compile(r"[0-9a-f]{64}")
OPEN = 2  # pushes open at once, at most
FILE_MAX = 64 * 1024 * 1024  # a file's bytes, at most (POST /peer/push/file's limit)
PUSH_MAX = 2 * 1024 ** 3  # a push's files' bytes, at most
NEW_MAX = 1024 * 1024  # POST /peer/push/new's document, at most
DOCUMENT_MAX = 16 * 1024 * 1024  # POST /peer/push's, at most
DROP_MAX = 16 * 1024  # POST /peer/push/drop's, at most
EXPIRES = 3600.0  # seconds a push is left untouched before it is deleted
FOLDER = "peer"  # under state_dir
PREFIX = "push-"
NEW = "new.json"  # who opened the push, the files it named and those this side needed
DOCUMENT = "push.json"  # the push document, once sent
FILES = "files"  # the files sent, each named by its SHA-256

INDEX_PREFIX = "index-"  # a phone's index pages staged (POST /peer/index): index-<16 hex>.sqlite
INDEX_SUFFIX = ".sqlite"
INDEX_MAX = 64 * 1024 * 1024  # POST /peer/index's export, at most
INDEX_OPEN = 2  # index exports waiting to be merged, at most
SQLITE_HEADER = b"SQLite format 3\x00"  # the first 16 bytes of every SQLite database file

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


def needed(conn: sqlite3.Connection | None, library_dir: Path, files: Sequence[str]) -> list[str]:
    """Those of ``files`` (each a SHA-256) this side has no readable copy of (``kept_copy``), in order."""
    return [f for f in files if kept_copy(conn, library_dir, f) is None]


def _not_from_here(sender: str, own: str | None) -> None:
    if own is not None and sender == own:
        raise PushError("That push comes from this same scribe (same id): its database is a copy of ours. "
                        "Give one a new id: caracole peer new-id.")


def new_push(state_dir: Path, *, sender: str, files: Sequence[str], need: Sequence[str], own: str | None,
             now: float | None = None) -> Opened:
    """A push opened for ``sender`` (``read_new``'s), which names ``files``, of which this side needs ``need``
    (``needed``): its folder made; PushError when ``sender`` is this caracole (``own``, its id), or with ``OPEN``
    pushes here already, open or sent and not taken yet (409); OSError when its folder can't be made. Pushes left
    untouched for an hour go first (``sweep``), and so does the push ``sender`` opened before and never sent: one
    sender holds one open push at a time."""
    _not_from_here(sender, own)
    need = list(need)
    sweep(state_dir, now)
    with _lock:
        root = state_dir / FOLDER
        for folder in _pushes(root):
            if _never_sent_by(folder, sender):
                shutil.rmtree(folder, ignore_errors=True)
        if len(_pushes(root)) >= OPEN:
            raise PushError("Two pushes wait here already. Try again once one is taken, or in an "
                            "hour.", 409)
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


def _never_sent_by(folder: Path, sender: str) -> bool:
    """Whether the push in ``folder`` was opened by ``sender`` and its document never taken (no take queued)."""
    opened = _read_json(folder / NEW)
    return isinstance(opened, Mapping) and opened.get("from") == sender and not os.path.lexists(folder / DOCUMENT)


def drop(state_dir: Path, push_id: str, sender: str) -> None:
    """The push ``push_id`` deleted now, never sent (``POST /peer/push/drop``: its pusher failed after it opened it),
    asked by ``sender``, the caracole that opened it, as a send is; PushError for a bad id or sender (400), no such
    push here (404), one another caracole opened (400), or one whose document was taken, its take queued or running
    (409)."""
    check_id(push_id)
    if not isinstance(sender, str) or not ID.fullmatch(sender):
        raise PushError("Who pushes? Its caracole's id is 16 hex.")
    with _lock:
        folder = _folder(state_dir, push_id)
        try:
            entry = os.lstat(folder)
        except FileNotFoundError:
            entry = None
        if entry is None or not stat.S_ISDIR(entry.st_mode):
            raise PushError("No such push is open here.", 404)
        opened = _read_json(folder / NEW)
        if not isinstance(opened, Mapping) or opened.get("from") != sender:
            raise PushError("That push was opened by another caracole.")
        if os.path.lexists(folder / DOCUMENT):
            raise PushError("That push is sent: its take waits or runs here.", 409)
        shutil.rmtree(folder, ignore_errors=True)


def stage_file(state_dir: Path, push_id: str, digest: str, data: bytes) -> None:
    """A file the push ``push_id`` needs, kept as ``files/<digest>`` once its bytes have that SHA-256; PushError when
    the push isn't open, or doesn't need it, or its files would pass ``PUSH_MAX``. A file staged already is as it
    was."""
    check_id(push_id)
    check_sha256(digest)
    if hashlib.sha256(data).hexdigest() != digest:
        raise PushError("Those bytes aren't the file of that SHA-256.")
    sweep(state_dir)
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
            raise PushError("That push's files pass 2 GiB. Push fewer changes at a time.")
        _write_private(target, data)


def _staged_bytes(folder: Path) -> int:
    try:
        return sum(entry.stat(follow_symlinks=False).st_size for entry in os.scandir(folder / FILES))
    except FileNotFoundError:
        return 0


def _staged(folder: Path) -> set[str]:
    """The files staged in a push's folder, by their SHA-256 (their names)."""
    try:
        return {e.name for e in os.scandir(folder / FILES) if SHA256.fullmatch(e.name)
                and e.is_file(follow_symlinks=False)}
    except FileNotFoundError:
        return set()


def unstaged(state_dir: Path, push_id: str, files: set[str]) -> set[str]:
    """Those of ``files`` the push ``push_id`` hasn't had sent: what a send must find kept here instead."""
    return files - _staged(_folder(state_dir, push_id))


# --- the phone's index pages -------------------------------------------------------------------------------------


def staged_indexes(state_dir: Path) -> list[Path]:
    """The index exports staged in ``state_dir/peer``, by their names alone (``index-<16 hex>.sqlite``, a file)."""
    try:
        entries = list(os.scandir(state_dir / FOLDER))
    except OSError:  # none yet, or no folder to read
        return []
    return sorted(Path(e.path) for e in entries
                  if e.name.startswith(INDEX_PREFIX) and e.name.endswith(INDEX_SUFFIX)
                  and ID.fullmatch(e.name[len(INDEX_PREFIX):-len(INDEX_SUFFIX)]) and e.is_file(follow_symlinks=False))


def sweep_indexes(state_dir: Path, named: set[str], now: float | None = None) -> list[str]:
    """Delete each staged index export untouched for ``EXPIRES`` that ``named`` (the paths of the queued and
    running requests' commands) doesn't name: its merge is over, or will never come. The names deleted."""
    now = time.time() if now is None else now
    gone = []
    with _lock:
        for path in staged_indexes(state_dir):
            try:
                old = now - os.lstat(path).st_mtime > EXPIRES
            except FileNotFoundError:
                continue
            if old and str(path) not in named:
                path.unlink(missing_ok=True)
                gone.append(path.name)
    return gone


def stage_index(state_dir: Path, data: bytes) -> Path:
    """The index export a phone posted, kept as ``state_dir/peer/index-<16 hex>.sqlite`` (0600) for its merge:
    its path. PushError for bytes that are no SQLite file (400), or with ``INDEX_OPEN`` waiting already (409);
    OSError when it can't be written."""
    if not data.startswith(SQLITE_HEADER):
        raise PushError("That isn't an index export: caracole's are SQLite files (index_transfer.export).")
    if len(data) > INDEX_MAX:
        raise PushError("That index export passes 64 MiB.", 413)
    with _lock:
        root = state_dir / FOLDER
        if len(staged_indexes(state_dir)) >= INDEX_OPEN:
            raise PushError("Two index exports wait to be merged here already: send it again once they are.", 409)
        state_dir.mkdir(parents=True, exist_ok=True)
        _private_dir(root)
        while True:
            path = root / f"{INDEX_PREFIX}{secrets.token_hex(8)}{INDEX_SUFFIX}"
            if not os.path.lexists(path):
                break
        _write_private(path, data)
    return path


# --- pushes left, and a take's hold on one -----------------------------------------------------------------------


def _pushes(root: Path) -> list[Path]:
    """The pushes' folders under ``root`` (state_dir/peer), by their names alone: nothing else there is one."""
    try:
        entries = list(os.scandir(root))
    except OSError:  # none yet, or no folder to read
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
        raise PushError("That push is gone: never sent, or left over an hour. Share again.") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if not (folder / DOCUMENT).exists():  # a sweep deleted it as the take came
            raise PushError("That push is gone: left over an hour. Share again.")
        yield
    finally:
        os.close(fd)


def sent_folder(state_dir: Path, given: str | os.PathLike[str]) -> Path:
    """The folder of a push here that ``given`` names (``caracole peer take DIR``): ``state_dir/peer/push-<id>``
    itself, a folder and no link, reached through no link but those of ``state_dir``'s own path; PushError for any
    other, so that a take, which deletes its folder once it is over, deletes no other."""
    path = Path(given)
    name = path.name
    if not name.startswith(PREFIX) or not ID.fullmatch(name[len(PREFIX):]):
        raise PushError(f"{str(given)[:200]!r} isn't a push's folder: push-<16 hex>.")
    folder = _folder(state_dir, name[len(PREFIX):])
    try:
        same = os.path.realpath(path.parent) == os.path.realpath(folder.parent)
        entry = os.lstat(folder)
    except OSError:
        same, entry = False, None
    if not same or entry is None or not stat.S_ISDIR(entry.st_mode):
        raise PushError(f"{str(given)[:200]!r} isn't a push here: a take is given its folder in "
                        f"{state_dir / FOLDER}.")
    return folder


def remove(folder: Path) -> None:
    """A push's folder deleted, all of it (once its take is over)."""
    shutil.rmtree(folder, ignore_errors=True)


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
    """``POST /peer/push``'s document read: ``{"format", "from", "name", "caracole", "key_version", "at", "units": {id:
    {label, digest}}, "take": [{id, expected, digest, unit}]}``, each unit given once, a document with each digest and
    none without, and each digest the one its state gives it. PushError for anything else; 409 (``OTHER_KEYS``) for a
    push of a caracole whose songs are keyed by other rules (``peer_sync.other_keys``: one that says none is an older
    caracole's, read as before)."""
    if not isinstance(data, Mapping) or data.get("format") != sync.FORMAT:
        raise PushError(f"That isn't a push of format {sync.FORMAT} (the other caracole may be of another version).")
    if sync.other_keys(data.get("key_version")):
        raise PushError(sync.OTHER_KEYS, 409)
    sender, name, version, at = data.get("from"), data.get("name"), data.get("caracole"), data.get("at")
    if not isinstance(sender, str) or not ID.fullmatch(sender):
        raise PushError("Who pushes? Its caracole's id is 16 hex.")
    if not (isinstance(name, str) and isinstance(version, str) and isinstance(at, str) and at):
        raise PushError("A push says its library's name, its caracole's version and when it compared.")
    if stamps.parse(at) is None:
        raise PushError(f"{at[:80]!r} isn't a time: a push says when it compared as this side's state said it.")
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


def check_digests(push: Push) -> None:
    """Each document the push gives is what its digest says: the digest of its value read from it alone
    (``peer_sync.value_of_document``), as a take reads it; PushError for the first that isn't."""
    for taken in push.take:
        if taken.unit is None:
            continue
        try:
            found = sync.digest_of(sync.value_of_document(taken.id, taken.unit))
        except (sync.UnitError, TypeError, ValueError) as e:
            raise PushError(f"{taken.id[:200]}: {e}.") from None
        if found != taken.digest:
            raise PushError(f"{taken.id[:200]}: its document isn't what its digest says.")


def send(state_dir: Path, push_id: str, push: Push, document: Mapping[str, Any], *, own: str | None,
         kept: set[str]) -> Path:
    """The push ``push_id`` sent: ``push`` (``document`` read, ``read_push_document``) kept as its ``push.json``
    once it is open, from whoever opened it and not from this caracole (``own``), each of its documents what its
    digest says (``check_digests``) and each file its songs keep staged, else kept here (``kept``: those of
    ``unstaged`` this side has a readable copy of); its folder, for the take. PushError else; OSError when it can't
    be written."""
    check_id(push_id)
    _not_from_here(push.sender, own)
    check_digests(push)
    files = push.files()
    with _lock:
        folder = _folder(state_dir, push_id)
        opened = _read_json(folder / NEW)
        if not isinstance(opened, Mapping):
            raise PushError("No such push is open here: open another (POST /peer/push/new).")
        if (folder / DOCUMENT).exists():
            raise PushError("That push is sent already.")
        if opened.get("from") != push.sender:
            raise PushError("That push was opened by another caracole.")
        missing = sorted(files - _staged(folder) - kept)
        if missing:
            raise PushError(f"{len(missing)} {'file' if len(missing) == 1 else 'files'} of the push never came, "
                            f"nor {'is' if len(missing) == 1 else 'are'} kept here: "
                            + ", ".join(missing[:3]) + ("…" if len(missing) > 3 else "") + ".")
        _write_private(folder / DOCUMENT, json.dumps(document, ensure_ascii=False).encode("utf-8"))
    return folder


def unsend(state_dir: Path, push_id: str) -> None:
    """The push ``push_id`` open again, its ``push.json`` gone: no take was queued for it."""
    with _lock:
        folder = _folder(state_dir, push_id)
        with _unless_held(folder) as free:
            if free:
                (folder / DOCUMENT).unlink(missing_ok=True)


def read_sent(folder: Path) -> Push:
    """The push sent in ``folder`` (``sent_folder``), as ``send`` kept it; PushError when it can't be read."""
    data = _read_json(folder / DOCUMENT)
    if data is None:
        raise PushError("That push can't be read. Share again.")
    push = read_push_document(data)
    check_digests(push)
    return push


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
        gives as one it hasn't got (a song removed there); PeerError for a unit it doesn't give at all, which a
        take must leave as it is, never take as gone."""
        taken = self._take.get(unit_id)
        if taken is None:
            raise sync.PeerError("the push doesn't give it")
        return None if taken.unit is None else dict(taken.unit)

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
            raise sync.PeerError(f"{name} wasn't sent with the push, nor kept here as it was: the song stays as it "
                                 "was here.")
        return data


# --- a push to another caracole -----------------------------------------------------------------------------------

NEW_PATH = "/peer/push/new"
FILE_PATH = "/peer/push/file"
PUSH_PATH = "/peer/push"
DROP_PATH = "/peer/push/drop"
JOBS_PATH = "/api/jobs/"
WAIT = 600.0  # seconds a push's take is waited for, at most
POLL = 1.0  # seconds between two asks of how it goes


class Pusher(sync.Peer):
    """Another ``caracole serve`` asked to take a push, as the phone asks it: its state (and with it its form token,
    which each request of a push carries in its header), the three requests of a push, and how its take goes
    (``GET /api/jobs/<id>``). A request refused for a token older than the server (403, ``reload``) is sent once
    more, with the token its state gives now."""

    def __init__(self, address: str, *, transport=None):
        super().__init__(address, transport=transport)
        self.token: str | None = None
        self._asking: str | None = None

    def state(self, asking: str | None = None) -> sync.PeerState:
        state = super().state(asking)
        self.token, self._asking = state.token, asking
        return state

    def _post(self, path: str, content: bytes, kind: str, params: Mapping[str, str] | None = None) -> Any:
        import httpx

        for again in (False, True):
            if self.token is None:
                self.state(self._asking)
            try:
                response = self._client.post(self.address + path, params=params, content=content, headers={
                    "Content-Type": kind, "Accept": "application/json", "X-Caracole-Form-Token": self.token or ""})
            except httpx.HTTPError as e:
                raise sync.PeerError(f"{self.address} stopped answering: {e}") from None
            if response.status_code == 403 and not again and _says_reload(response):
                self.token = None  # older than the server: its state gives the token again
                continue
            if response.status_code != 200:
                raise self._refused(response)
            try:
                return response.json()
            except ValueError:
                raise sync.PeerError(f"{self.address} answered {path} in a form we can't read.") from None
        raise AssertionError("unreachable")

    def push_new(self, sender: str, files: Sequence[str]) -> tuple[str, list[str]]:
        """``POST /peer/push/new``: the push's id and the files the other side needs sent."""
        answer = self._post(NEW_PATH, _json({"format": sync.FORMAT, "from": sender, "files": list(files)}),
                            "application/json")
        answer = answer if isinstance(answer, dict) else {}
        push, need = answer.get("push"), answer.get("need")
        if not (isinstance(push, str) and ID.fullmatch(push) and isinstance(need, list)
                and all(isinstance(f, str) and SHA256.fullmatch(f) for f in need)):
            raise sync.PeerError(f"{self.address} opened a push it can't name.")
        return push, list(need)

    def push_file(self, push: str, sha256: str, data: bytes) -> None:
        """``POST /peer/push/file``: a file the push needs, its bytes."""
        self._post(FILE_PATH, data, "application/octet-stream", {"push": push, "sha256": sha256})

    def push(self, push: str, document: Mapping[str, Any]) -> int:
        """``POST /peer/push``: the push document; the number of the job that takes it there."""
        answer = self._post(PUSH_PATH, _json(document), "application/json", {"push": push})
        job = answer.get("job") if isinstance(answer, dict) else None
        if not (isinstance(job, dict) and type(job.get("id")) is int):
            raise sync.PeerError(f"{self.address} took the push but named no Journal entry for it.")
        return job["id"]

    def push_drop(self, push: str, sender: str) -> bool:
        """``POST /peer/push/drop``: the push ``push`` there, never sent, let go of; whether it was (an error, or its
        refusal, is no more than that: the sender's next push lets go of it, or it is swept within the hour)."""
        try:
            self._post(DROP_PATH, _json({"push": push, "from": sender}), "application/json")
        except Exception:  # whatever went wrong, the push's own failure is the one said
            return False
        return True

    def job(self, job_id: int) -> dict[str, Any]:
        """``GET /api/jobs/<id>``: how a job there goes."""
        response = self._get(f"{JOBS_PATH}{job_id}")
        if response.status_code != 200:
            raise self._refused(response)
        try:
            data = response.json()
        except ValueError:
            data = None
        if not (isinstance(data, dict) and isinstance(data.get("state"), str)):
            raise sync.PeerError(f"{self.address} answered about entry {job_id} in a form we can't read.")
        return data


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _says_reload(response) -> bool:
    try:
        data = response.json()
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("reload") is True


@dataclass(frozen=True)
class Pushed:
    """A push sent (each of ``push_units``'): the job that takes it there (0: nothing was sent), the units it gives,
    and those left out here, each with why (the first push's hold those the give left before any was sent)."""

    job: int
    given: tuple[str, ...]
    left: tuple[tuple[str, str], ...]


class PushStopped(sync.PeerError):
    """A give stopped at one of its pushes (``push_units``): why, and how far it got: ``sent`` of its ``pushes``
    pushes taken there before it (each handed to ``between``), and, when none was, the units it had left out by then,
    each with why (``left``)."""

    def __init__(self, message: str, *, sent: int, pushes: int, left: Sequence[tuple[str, str]] = ()):
        super().__init__(message)
        self.sent, self.pushes, self.left = sent, pushes, tuple(left)


TOO_LONG = "its document is longer than a push carries (16 MiB)"  # one unit's, alone past DOCUMENT_MAX
TOO_HEAVY = "its files are more than a push carries (2 GiB)"  # one song's, alone past PUSH_MAX (or NEW_MAX's names)
_NAMED = 67  # a SHA-256 in push/new's "files", as _json writes it: 64 hex, its quotes and a comma


def push_units(pusher: Pusher, conn: sqlite3.Connection, cfg, overrides, books, give: Mapping[str, str | None],
               *, own: str, at: str, name: str, version: str,
               compared_here: Mapping[str, str | None] | None = None,
               between: Callable[[Pushed], Any] | None = None) -> Pushed:
    """Give the other side the units of ``give`` (each unit's id, and the other side's digest of it as compared,
    None for one it hadn't), as the phone gives them: their files, then the push document, this side's whole state
    with it, ``at`` the other side's time in the state compared. A unit whose digest here differs from
    ``compared_here``'s is left out (``CHANGED_HERE``), and so is a song with a kept file this side can no longer
    read as kept, one with a kept file past ``FILE_MAX`` (peer_file's ``TOO_BIG``, the export's words for it), and a
    unit that alone passes what a push carries (``TOO_LONG``, ``TOO_HEAVY``).

    The units go in as many pushes as the other side's limits ask (``_pushes``: each document within
    ``DOCUMENT_MAX``, each ``push/new`` within ``NEW_MAX``, each push's files within ``PUSH_MAX``, a song and its
    tombstone in one), one at a time: each but the last is handed to ``between`` once sent, which returns once its
    take is over there (``wait_for``, its default), the take agreeing on what it took as it ends and its push's slot
    let go of, and only then is the next opened. The last is returned, for the caller to wait for. A push that fails
    is let go of there (``Pusher.push_drop``) and the give stops there, ``PushStopped`` saying how far it got; an
    interrupt (Ctrl-C) lets go of it too, then goes on. The caller holds caracole's lock."""
    from caracole.peer_file import TOO_BIG

    units = sync.library_state(conn, overrides, books)
    take: list[dict[str, Any]] = []
    left: list[tuple[str, str]] = []
    files_of: dict[str, set[str]] = {}
    sizes: dict[str, int] = {}
    for unit_id, expected in give.items():
        mine = units.get(unit_id)
        digest = mine.digest if mine is not None else None
        if compared_here is not None and unit_id in compared_here and compared_here[unit_id] != digest:
            left.append((unit_id, sync.CHANGED_HERE))
            continue
        doc = sync.unit_document(conn, cfg, overrides, books, unit_id) if mine is not None else None
        unit = doc["unit"] if doc is not None else None
        if unit is not None and unit_id.partition("/")[0] == "song":
            kept = _kept_sizes(conn, cfg.library_dir, unit_id.partition("/")[2], unit)
            if any(size > FILE_MAX for size in kept.values()):
                left.append((unit_id, TOO_BIG))
                continue
            files_of[unit_id] = set(kept)
            sizes.update(kept)
        take.append({"id": unit_id, "expected": expected, "digest": digest, "unit": unit})
    header = {"format": sync.FORMAT, "from": own, "name": name, "caracole": version,
              "key_version": normalize.KEY_VERSION, "at": at,
              "units": {u.id: {"label": u.label, "digest": u.digest} for u in units.values()}, "take": []}
    pushes, too_much = _cut(header, take, files_of, sizes, own)
    left += too_much
    if not pushes:
        return Pushed(0, (), tuple(left))
    wait = between if between is not None else (lambda sent: wait_for(pusher, sent.job))
    for n, batch in enumerate(pushes):
        which = "" if len(pushes) == 1 else f"push {n + 1} of {len(pushes)}: "
        try:
            pushed = _push_one(pusher, conn, cfg, own, header, batch, files_of)
        except sync.PeerError as e:
            raise PushStopped(which + str(e), sent=n, pushes=len(pushes), left=left) from None
        pushed = Pushed(pushed.job, pushed.given, tuple(left) + pushed.left)
        left = []
        if n == len(pushes) - 1:
            return pushed
        try:
            wait(pushed)
        except sync.PeerError as e:
            raise PushStopped(which + str(e), sent=n, pushes=len(pushes)) from None
    raise AssertionError("unreachable")


def _kept_sizes(conn: sqlite3.Connection, library_dir: Path, key: str, unit: Mapping[str, Any]) -> dict[str, int]:
    """Each file a song's document keeps, by its SHA-256, and its size in the song's folder now (no link followed;
    0 for one that can't be read there, which its push then finds changed)."""
    found: dict[str, int] = {}
    for version in unit["versions"]:
        for f in version["files"]:
            row = conn.execute("SELECT files.path FROM files JOIN songs ON songs.id = files.song_id "
                               "WHERE songs.key = ? AND files.name = ?", (key, f["name"])).fetchone()
            try:
                entry = os.lstat(library_dir / row[0]) if row is not None else None
            except OSError:
                entry = None
            size = entry.st_size if entry is not None and stat.S_ISREG(entry.st_mode) else 0
            found[f["sha256"]] = max(found.get(f["sha256"], 0), size)
    return found


def _cut(header: Mapping[str, Any], take: Sequence[dict[str, Any]], files_of: Mapping[str, set[str]],
            sizes: Mapping[str, int], own: str) -> tuple[list[list[dict[str, Any]]], list[tuple[str, str]]]:
    """``take`` cut into pushes within the other side's limits, in order: each push's document (``header`` with its
    entries as ``take``) within ``DOCUMENT_MAX``, its ``push/new`` within ``NEW_MAX`` and its files' bytes within
    ``PUSH_MAX``, a song and its tombstone (``song/K``, ``removed/K``) in the same push, where the first of the two
    came; and the units that alone
    pass one of them, each with why (``TOO_LONG``, ``TOO_HEAVY``). Lengths are those of the bytes ``_json`` sends."""
    base = len(_json(header))  # its "take": [] counted
    new_base = len(_json({"format": sync.FORMAT, "from": own, "files": []}))
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in take:
        kind, _, key = entry["id"].partition("/")
        groups.setdefault(f"song/{key}" if kind in ("song", "removed") else entry["id"], []).append(entry)
    pushes: list[list[dict[str, Any]]] = []
    too_much: list[tuple[str, str]] = []
    batch: list[dict[str, Any]] = []
    length, named, weight = 0, set(), 0
    for group in groups.values():
        more = sum(len(_json(e)) + 1 for e in group)  # each entry and its comma
        files = set().union(*(files_of.get(e["id"], set()) for e in group))
        if base + more - 1 > DOCUMENT_MAX:
            too_much += [(e["id"], TOO_LONG) for e in group]
            continue
        if new_base + _NAMED * len(files) - 1 > NEW_MAX or sum(sizes.get(f, 0) for f in files) > PUSH_MAX:
            too_much += [(e["id"], TOO_HEAVY) for e in group]
            continue
        new = files - named
        if batch and (base + length + more - 1 > DOCUMENT_MAX
                      or new_base + _NAMED * (len(named) + len(new)) - 1 > NEW_MAX
                      or weight + sum(sizes.get(f, 0) for f in new) > PUSH_MAX):
            pushes.append(batch)
            batch, length, named, weight = [], 0, set(), 0
            new = files
        batch += group
        length += more
        named |= new
        weight += sum(sizes.get(f, 0) for f in new)
    if batch:
        pushes.append(batch)
    return pushes, too_much


def _push_one(pusher: Pusher, conn: sqlite3.Connection, cfg, own: str, header: Mapping[str, Any],
              batch: list[dict[str, Any]], files_of: Mapping[str, set[str]]) -> Pushed:
    """One push of ``push_units``': opened, the files the other side needs sent, then its document (``header``
    with ``batch`` as its ``take``); any failure before its document is taken, an interrupt's too, lets go of it
    there (``Pusher.push_drop``: refused, 409, once its document was taken: its take goes on there) before it is
    raised as it was."""
    take = list(batch)
    files = sorted(set().union(*(files_of.get(e["id"], set()) for e in take)))
    push_id, need = pusher.push_new(own, files)
    left: list[tuple[str, str]] = []
    try:
        unreadable = set()
        for sha256 in need:
            data = kept_copy(conn, cfg.library_dir, sha256)
            if data is None:
                unreadable.add(sha256)
                continue
            pusher.push_file(push_id, sha256, data)
        if unreadable:
            for entry in [e for e in take if files_of.get(e["id"], set()) & unreadable]:
                take.remove(entry)
                left.append((entry["id"], "a file it keeps changed here since we kept it"))
        job = pusher.push(push_id, {**header, "take": take})
    except BaseException:
        pusher.push_drop(push_id, own)
        raise
    return Pushed(job, tuple(e["id"] for e in take), tuple(left))


def wait_for(pusher: Pusher, job_id: int, *, timeout: float = WAIT, every: float = POLL,
             sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic
             ) -> dict[str, Any]:
    """The job ``job_id`` there, as ``GET /api/jobs/<id>`` gives it once it is over; PeerError when it isn't
    within ``timeout`` seconds (it goes on there all the same)."""
    end = clock() + timeout
    while True:
        job = pusher.job(job_id)
        if job["state"] not in ("queued", "running"):
            return job
        if clock() >= end:
            raise sync.PeerError(f"{pusher.address} hasn't taken the push yet: its Journal entry {job_id} goes on.")
        sleep(every)


# kv, then a peer's id: {"address", "name", "synced_at"} of the last ``caracole peer sync`` with it, which caracole
# serve's Sync tab lists (GET /api/sync); written by that command alone, never by caracole serve
PEER_KEY = "sync:peer:"
