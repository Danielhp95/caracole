"""A file to import, staged here part by part: what caracole serve's import routes keep of a ``.caracole`` file
(or an index export) a page sends it, until ``caracole peer import`` takes it (peer_file.py; the plan:
docs/superpowers/plans/2026-11-03-sync-redesign.md §3.4.2).

A page sends a file in parts, since a file holds a library's kept files and pages, and maybe its site indexes
(hundreds of MB): ``open_import`` makes its folder, ``state_dir/peer/import-<id>/`` (0700, beside a push's,
peer_push.py), with ``open.json`` (the size the page said, its name, when it was opened) and ``file.caracole``, the
file as it comes (0600); ``add_part`` writes each part where the last one ended, at most ``PART_MAX`` (8 MiB) a part,
refusing a part that isn't the next one or would pass the size; ``whole`` is the file once every part has come. Then
``caracole peer import <folder>`` holds it (``held``), takes it as it takes any file, and deletes it (``remove``).

Nothing of it goes into the library. An import's id is 16 hex, checked before any path is built of it, and
``staged_folder`` checks the one an import is given, so that a take, which deletes its folder, deletes no other. At
most ``OPEN`` (1) import is here at once, sent or being sent, and a file is at most ``peer_file.IMPORT_MAX``
(8 GiB). One untouched for ``EXPIRES`` (an hour) is deleted (``sweep``: as one is opened, as an import ends), unless
an import holds it.
"""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import shutil
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from caracole.peer_file import IMPORT_MAX
from caracole.peer_push import FOLDER, ID, _private_dir, _read_json, _write_private

OPEN = 1  # imports here at once, at most
PART_MAX = 8 * 1024 * 1024  # a part's bytes, at most (POST /sync/import/part's limit)
EXPIRES = 3600.0  # seconds an import is left untouched before it is deleted
PREFIX = "import-"
FILE = "file.caracole"  # the file, as it comes
OPENED = "open.json"  # its size, its name and when it was opened

TOO_BIG = "That file is too big: a file to import is at most 8 GiB."
BUSY = "A file is being sent here already: try again once it is taken, or in an hour."
NOT_NEXT = "That part isn't the next one: choose the file again."
NO_SUCH = "No such import is open here: choose the file again."
NOT_WHOLE = "That file isn't whole yet: send the rest of it."

_lock = threading.Lock()  # one change at a time to the imports, of caracole serve's threads


class StagingError(ValueError):
    """An import, or a part of one, refused: why, in a sentence, and the status caracole serve answers it with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check_id(import_id: str) -> str:
    if not isinstance(import_id, str) or not ID.fullmatch(import_id):
        raise StagingError("Which import? Its id is 16 hex.")
    return import_id


def _folder(state_dir: Path, import_id: str) -> Path:
    """The folder of the import ``import_id`` names: the one path built of an id, once it is checked."""
    return Path(state_dir) / FOLDER / (PREFIX + check_id(import_id))


def _opened(folder: Path) -> dict | None:
    found = _read_json(folder / OPENED)
    return found if isinstance(found, dict) and type(found.get("size")) is int else None


def open_import(state_dir: Path, *, size: int, name: str, now: float | None = None) -> str:
    """An import opened for a file of ``size`` bytes named ``name``: its folder made, its id; StagingError for a
    size that isn't one (400) or is past ``IMPORT_MAX`` (413), before anything is made, and with ``OPEN`` imports
    here already (409). Imports untouched for an hour go first (``sweep``)."""
    if type(size) is not int or size <= 0:
        raise StagingError("How big is the file? Its size is a number of bytes.")
    if size > IMPORT_MAX:
        raise StagingError(TOO_BIG, 413)
    if not isinstance(name, str):
        raise StagingError("What is the file called? Its name is text.")
    sweep(state_dir, now)
    with _lock:
        root = Path(state_dir) / FOLDER
        if len(_imports(root)) >= OPEN:
            raise StagingError(BUSY, 409)
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        _private_dir(root)
        while True:
            import_id = secrets.token_hex(8)
            folder = _folder(state_dir, import_id)
            try:
                folder.mkdir(mode=0o700)
                break
            except FileExistsError:
                continue
        os.chmod(folder, 0o700)
        os.close(os.open(folder / FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
        _write_private(folder / OPENED, json.dumps({"size": size, "name": name[:255],
                                                    "opened": time.time() if now is None else now}).encode())
    return import_id


def _size_of(folder: Path) -> int:
    entry = os.lstat(folder / FILE)
    if not stat.S_ISREG(entry.st_mode):
        raise StagingError(NO_SUCH, 404)
    return entry.st_size


def add_part(state_dir: Path, import_id: str, at: int, data: bytes) -> int:
    """A part of the import ``import_id``'s file, written at ``at``, where what it has ends: how much it has then;
    StagingError for no such import (404), a part not at the end of what it has or that would pass its size, or
    one past ``PART_MAX`` (400). What it had stays as it was."""
    check_id(import_id)
    if len(data) > PART_MAX:
        raise StagingError("A part is 8 MiB at most: send it in smaller parts.")
    with _lock:
        folder = _folder(state_dir, import_id)
        opened = _opened(folder)
        if opened is None:
            raise StagingError(NO_SUCH, 404)
        try:
            have = _size_of(folder)
        except FileNotFoundError:
            raise StagingError(NO_SUCH, 404) from None
        if type(at) is not int or at != have or have + len(data) > opened["size"]:
            raise StagingError(NOT_NEXT)
        fd = os.open(folder / FILE, os.O_WRONLY | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise StagingError(NO_SUCH, 404)
            written = 0
            while written < len(data):
                written += os.pwrite(fd, memoryview(data)[written:], at + written)
        finally:
            os.close(fd)
        os.utime(folder)
        return have + len(data)


def whole(state_dir: Path, import_id: str) -> Path:
    """The import ``import_id``'s file, once every part has come; StagingError else."""
    with _lock:
        folder = _folder(state_dir, import_id)
        opened = _opened(folder)
        if opened is None:
            raise StagingError(NO_SUCH, 404)
        try:
            have = _size_of(folder)
        except FileNotFoundError:
            raise StagingError(NO_SUCH, 404) from None
        if have != opened["size"]:
            raise StagingError(NOT_WHOLE)
        return folder / FILE


def opened_name(folder: Path) -> str:
    """The name the file staged in ``folder`` was sent under (an index export's name is its own)."""
    opened = _opened(folder)
    name = opened.get("name") if opened is not None else None
    return name if isinstance(name, str) and name else FILE


# --- imports left, and an import's hold on one ----------------------------------------------------------------------


def _imports(root: Path) -> list[Path]:
    """The imports' folders under ``root`` (state_dir/peer), by their names alone."""
    try:
        entries = list(os.scandir(root))
    except OSError:
        return []
    return [Path(e.path) for e in entries if e.name.startswith(PREFIX) and ID.fullmatch(e.name[len(PREFIX):])
            and e.is_dir(follow_symlinks=False)]


def _touched(folder: Path) -> float:
    """When the import in ``folder`` last changed: opened, or a part written."""
    times = []
    for path in (folder, folder / FILE, folder / OPENED):
        try:
            times.append(os.lstat(path).st_mtime)
        except FileNotFoundError:
            pass
    return max(times, default=0.0)


def sweep(state_dir: Path, now: float | None = None) -> list[str]:
    """Delete each import untouched for ``EXPIRES``, unless an import holds it (``held``); the ids deleted."""
    now = time.time() if now is None else now
    gone = []
    with _lock:
        for folder in _imports(Path(state_dir) / FOLDER):
            if now - _touched(folder) <= EXPIRES:
                continue
            with _unless_held(folder) as free:
                if free:
                    shutil.rmtree(folder, ignore_errors=True)
                    gone.append(folder.name[len(PREFIX):])
    return gone


@contextmanager
def _unless_held(folder: Path) -> Iterator[bool]:
    try:
        fd = os.open(folder / OPENED, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        yield True  # a folder half made: no import holds it
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
    """The import in ``folder`` held for ``caracole peer import``, so that no ``sweep`` deletes it meanwhile;
    StagingError when it is gone (left over an hour)."""
    try:
        fd = os.open(folder / OPENED, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise StagingError("That file is gone: it was left over an hour. Choose it again.", 404) from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if not (folder / OPENED).exists():  # a sweep deleted it as the import came
            raise StagingError("That file is gone: it was left over an hour. Choose it again.", 404)
        yield
    finally:
        os.close(fd)


def staged_folder(state_dir: Path, given: str | os.PathLike[str]) -> Path:
    """The folder of an import here that ``given`` names (``caracole peer import DIR``): ``state_dir/peer/import-<id>``
    itself, a folder and no link, reached through no link but those of ``state_dir``'s own path; StagingError for any
    other, so that an import, which deletes its folder once it is over, deletes no other."""
    path = Path(given)
    name = path.name
    if not name.startswith(PREFIX) or not ID.fullmatch(name[len(PREFIX):]):
        raise StagingError(f"{str(given)[:200]!r} isn't an import's folder: import-<16 hex>.")
    folder = _folder(state_dir, name[len(PREFIX):])
    try:
        same = os.path.realpath(path.parent) == os.path.realpath(folder.parent)
        entry = os.lstat(folder)
    except OSError:
        same, entry = False, None
    if not same or entry is None or not stat.S_ISDIR(entry.st_mode):
        raise StagingError(f"{str(given)[:200]!r} isn't an import here: an import is given its folder in "
                           f"{Path(state_dir) / FOLDER}.")
    return folder


def remove(folder: Path) -> None:
    """An import's folder deleted, all of it (once it is taken)."""
    shutil.rmtree(folder, ignore_errors=True)
