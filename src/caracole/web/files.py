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
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable
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


class NotServed(Exception):
    """A path the server answers 404 for."""


def read_library_file(library_dir: Path, path: str, *, hidden: Iterable[Path] = ()) -> tuple[bytes, str, bool]:
    """The bytes of the library file at ``path`` (``/``-separated, decoded), its type, and whether
    it is a download; NotServed for anything else."""
    parts = path.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") or "\x00" in p for p in parts):
        raise NotServed(path)
    suffix = PurePosixPath(parts[-1]).suffix.lower()
    if suffix not in TYPES:
        raise NotServed(path)
    if _is_hidden(library_dir, parts, hidden):
        raise NotServed(path)
    fd = _open(library_dir, parts)
    with open(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise NotServed(path)
        return f.read(), TYPES[suffix], suffix in DOWNLOADS


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
