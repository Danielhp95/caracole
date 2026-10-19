"""The library's files over HTTP: what index.html links to, and nothing else.

The library is synced, so anyone with a synced device can put a symbolic link
there, pointing at caracole's database, the Spotify token or the credentials.
Each folder on the way is opened relative to the last without following a
link (``O_NOFOLLOW``), and the file too, without waiting on a FIFO, then checked
on the open descriptor to be a regular file (as ``library.open_regular`` does
for the last part alone).

Only the kinds of file caracole keeps there are served: PDFs, text (sheets,
ChordPro, lyrics, the to-do page), info.json, and Guitar Pro and Power Tab
files, as downloads. Never HTML, SVG or anything a browser would run as the
server's own page, never a hidden name (Syncthing's folders, caracole's
temporary files), and never what is under ``hidden``: caracole's state and
cache, should they be inside the library.

A page caracole wrote into the library (a sheet viewer) is the one exception,
through ``read_written_page``, and only while it is still the bytes caracole
recorded writing there: anyone with a synced device can put a page there, or
edit one, whose script would run as the server's.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

from caracole.inbox import GP_EXTENSIONS

MAX_BYTES = 64 * 1024 * 1024
_TEXT = "text/plain; charset=utf-8"
TYPES = {
    ".pdf": "application/pdf",
    ".txt": _TEXT,
    ".cho": _TEXT,
    ".lrc": _TEXT,
    ".md": _TEXT,
    ".json": "application/json; charset=utf-8",
    **{ext: "application/octet-stream" for ext in GP_EXTENSIONS},
}
DOWNLOADS = frozenset(GP_EXTENSIONS)


# The lookup of a kind of page caracole writes: given a path's parts, the SHA-256 and the length of
# each page caracole recorded writing there, none when it wrote none (read_written_page).
Written = Callable[[tuple[str, ...]], Iterable[tuple[str, int]]]


class NotServed(Exception):
    """A path the server answers 404 for."""


def read_library_file(library_dir: Path, path: str, *, hidden: Iterable[Path] = ()) -> tuple[bytes, str, bool]:
    """The bytes of the library file at ``path`` (``/``-separated, decoded), its type, and whether
    it is a download; NotServed for anything else."""
    parts = _parts(library_dir, path, hidden)
    suffix = PurePosixPath(parts[-1]).suffix.lower()
    if suffix not in TYPES:
        raise NotServed(path)
    fd = _open(library_dir, parts)
    with open(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise NotServed(path)
        return f.read(), TYPES[suffix], suffix in DOWNLOADS


def read_written_page(library_dir: Path, path: str, written: Written, *, hidden: Iterable[Path] = ()) -> bytes:
    """The bytes of the page at ``path`` while it is a page caracole wrote there, as it wrote it;
    NotServed for anything else.

    ``written`` is the record of the page's kind: given the path's parts
    (``("Soda Stereo", "De Música Ligera", "sheet.html")``), the SHA-256 and the
    length of each page caracole recorded writing there (``render.written_file`` for
    a viewer), none when it wrote none. A path is checked as ``read_library_file``
    checks one, and nothing is opened for a path with no record. The file is then
    opened as any file is (no link followed, at any step), and must be a regular
    file of a recorded length, whose bytes, read once, have its SHA-256: the test
    ``library.holds`` makes, on the very bytes served.
    """
    parts = _parts(library_dir, path, hidden)
    records = set(written(tuple(parts)))
    if not records:
        raise NotServed(path)
    with open(_open(library_dir, parts), "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise NotServed(path)
        if not any(size == info.st_size for _, size in records):
            raise NotServed(path)
        data = f.read(MAX_BYTES + 1)
    if (hashlib.sha256(data).hexdigest(), len(data)) not in records:
        raise NotServed(path)
    return data


def _parts(library_dir: Path, path: str, hidden: Iterable[Path]) -> list[str]:
    """The parts of a ``/``-separated path to a file in the library; NotServed for an empty part,
    ``.``, ``..``, a hidden name, a NUL, or a path in one of the ``hidden`` folders."""
    parts = path.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") or "\x00" in p for p in parts):
        raise NotServed(path)
    if _is_hidden(library_dir, parts, hidden):
        raise NotServed(path)
    return parts


def _open(library_dir: Path, parts: list[str]) -> int:
    """A descriptor for the file, every part opened without following a link."""
    try:
        folder = os.open(library_dir, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as e:
        raise NotServed(str(library_dir)) from e
    try:
        for part in parts[:-1]:
            inner = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = inner
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    except OSError as e:  # missing, a link (ELOOP), not a folder
        raise NotServed("/".join(parts)) from e
    finally:
        os.close(folder)


def _is_hidden(library_dir: Path, parts: list[str], hidden: Iterable[Path]) -> bool:
    """Whether the path is in one of the ``hidden`` folders, when that folder is inside the library."""
    root = Path(os.path.realpath(library_dir))
    for folder in hidden:
        try:
            inside = Path(os.path.realpath(folder)).relative_to(root).parts
        except ValueError:
            continue
        if tuple(parts[: len(inside)]) == inside:
            return True
    return False
