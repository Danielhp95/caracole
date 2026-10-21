"""The library folder: one directory per song, with the files caracole keeps (plan §5).

    Library/
      Soda Stereo/
        De Música Ligera/
          sheet.txt  sheet.json  sheet.cho  sheet.pdf
          lyrics.txt lyrics.lrc  guitar-1.gp5  tab.txt  info.json

Names keep their accents and scripts ("宋冬野/斑马，斑马/") but never contain a
path separator or a reserved character, so a song can't escape the library.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caracole.db import kv_get_json
from caracole.normalize import clean_title
from caracole.songs import Song
from caracole.versions import get_version, song_versions

MAX_NAME_BYTES = 120
_RESERVED = re.compile(r'[*?"<>|\x00-\x1f\x7f]')


def safe_name(s: str) -> str:
    """A single path component made from a name: no separators, no reserved characters."""
    s = unicodedata.normalize("NFC", s)
    s = s.replace("/", "-").replace("\\", "-")
    s = re.sub(r"\s*:\s*", " - ", s)
    s = re.sub(r"[\t\r\n\v\f]+", " ", s)
    s = _RESERVED.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    data = s.encode("utf-8")
    if len(data) > MAX_NAME_BYTES:
        s = data[:MAX_NAME_BYTES].decode("utf-8", errors="ignore").rstrip(" .")
    return s or "_"


def song_dir(library_dir: Path, song: Song) -> Path:
    return library_dir / safe_name(song.artist) / safe_name(clean_title(song.title))


def write_atomic(path: Path, data: bytes) -> str:
    """Write through a temporary file and rename; return the SHA-256 of the data.

    Anyone who can write to the library can plant a symbolic link there, so the
    temporary file gets a random name and is created exclusively (O_EXCL): a
    link waiting at a predictable name is never written through. The rename
    replaces a link at ``path`` itself rather than its target. open(..., "x")
    rather than mkstemp: mkstemp makes 0600 files, which would hide the library
    from Syncthing reading it through the group.

    The data reaches the disk before the rename, and the rename before this
    returns (the folder is synced too): a power cut during the nightly run then
    leaves the old file or the new one, never an empty file that the database,
    committed after, says is kept.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)
    return hashlib.sha256(data).hexdigest()


class NotRegularFile(OSError):
    """A path caracole won't open: a symbolic link, a directory, a FIFO or a device."""


def open_regular(path: Path, flags: int = os.O_RDONLY, *, dir_fd: int | None = None) -> int:
    """A descriptor for the regular file at ``path``, never opened through a symbolic link.

    The library is writable by the Syncthing group and every synced device, so a
    link planted there could point at caracole's private files (the database, the
    Spotify token, the credentials): read, they would be copied into the
    library; written, they would be destroyed. The file is opened without
    following a link and without waiting on a FIFO, then checked on the open
    descriptor, so it can't be swapped in between. With ``dir_fd``, a folder's
    descriptor, ``path`` is a name in that folder (the inbox's, opened without
    following a link). Raises NotRegularFile, FileNotFoundError when nothing is
    there, or another OSError.
    """
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError as e:
        if e.errno == errno.ELOOP:  # O_NOFOLLOW's answer for a link
            link = "a symbolic link, which caracole doesn't follow"
            raise NotRegularFile(e.errno, link, str(path)) from None
        raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise NotRegularFile(errno.EINVAL, "not a regular file", str(path))
    return fd


def read_regular(path: Path, *, dir_fd: int | None = None) -> bytes:
    """The bytes of the regular file at ``path`` (in the folder open at ``dir_fd``, when given),
    never read through a link (``open_regular``)."""
    with open(open_regular(path, dir_fd=dir_fd), "rb") as f:
        return f.read()


def read_text(path: Path, error: Callable[[str], Exception]) -> str | None:
    """The text of the regular file at ``path``, None when there is none (``read_regular``).

    Anything else is ``error`` with a message that names the file, for every caller to report:
    a link or no regular file (refused unread), a file it can't read, or one that isn't UTF-8.
    overrides.toml and songbooks.toml are read this way.
    """
    try:
        data = read_regular(path)
    except FileNotFoundError:
        return None
    except NotRegularFile as e:
        raise error(f"{path}: {e.strerror}; put the file itself there") from e
    except OSError as e:  # no permission to read it, say
        raise error(f"{path}: can't read it: {e.strerror or e}") from e
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        line = data[: e.start].count(b"\n") + 1
        raise error(f"{path}: line {line} is not valid UTF-8 (save the file as UTF-8)") from e


def read_json(path: Path) -> Any:
    """The JSON in the regular file at ``path``, never read through a link (``read_regular``).

    Any synced device can write the file, so whatever it holds raises ValueError at worst: not
    UTF-8, not JSON, or nested too deep for the decoder (which raises RecursionError, and that
    would stop a pass over every song). Nothing there, a link or no regular file raises
    OSError (FileNotFoundError, NotRegularFile).
    """
    text = read_regular(path).decode("utf-8")
    try:
        return json.loads(text)
    except RecursionError:
        raise ValueError("nested too deep for the JSON decoder") from None


def holds(path: Path, sha256: str, size: int | None = None) -> bool:
    """Whether the regular file at ``path`` holds the bytes whose SHA-256 is ``sha256``.

    How caracole tells that a file it wrote is still in the library as written: not
    deleted (on a synced device, say), not cut short (by a power cut), not
    replaced by a link or anything else (``open_regular``). The test is cheap:
    with ``size``, the length of those bytes, a file of another length fails
    unread, and only one of that length is hashed.
    """
    try:
        fd = open_regular(path)
    except OSError:
        return False
    with open(fd, "rb") as f:
        if size is not None and os.fstat(f.fileno()).st_size != size:
            return False
        return hashlib.file_digest(f, "sha256").hexdigest() == sha256


@dataclass
class KeptFile:
    id: int
    version_id: int
    song_id: int
    name: str
    path: str
    sha256: str
    kept_rank: int


def kept_files(conn: sqlite3.Connection, song_id: int) -> list[KeptFile]:
    rows = conn.execute(
        "SELECT id, version_id, song_id, name, path, sha256, kept_rank FROM files WHERE song_id = ? ORDER BY name",
        (song_id,),
    )
    return [KeptFile(**dict(r)) for r in rows]


def kept_already(
    conn: sqlite3.Connection, library_dir: Path, *, song: Song, version_id: int, name: str, data: bytes
) -> bool:
    """Whether this version's ``data`` is the song's kept ``name`` already: so the files table says,
    and so the file in the library still is (``holds``). Then it needn't be written again, and
    isn't, for each rewrite is one more sync on every device."""
    sha = hashlib.sha256(data).hexdigest()
    return any(
        f.name == name and f.version_id == version_id and f.sha256 == sha
        and holds(library_dir / f.path, sha, len(data))
        for f in kept_files(conn, song.id)
    )


def keep_file(
    conn: sqlite3.Connection,
    library_dir: Path,
    *,
    song: Song,
    version_id: int,
    name: str,
    data: bytes,
    rank: int,
) -> bool:
    """Write a file into the song's folder and record it; False if identical bytes are kept already.

    A file with the same name is replaced. The same content under another name
    in the same song is a duplicate and isn't written again.
    """
    sha = hashlib.sha256(data).hexdigest()
    dup = conn.execute(
        "SELECT 1 FROM files WHERE song_id = ? AND sha256 = ? AND name != ?", (song.id, sha, name)
    ).fetchone()
    if dup:
        return False
    path = song_dir(library_dir, song) / safe_name(name)
    write_atomic(path, data)
    rel = path.relative_to(library_dir).as_posix()
    conn.execute(
        "INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) "
        "ON CONFLICT(song_id, name) DO UPDATE SET version_id = excluded.version_id, path = excluded.path, "
        "sha256 = excluded.sha256, kept_rank = excluded.kept_rank, created_at = excluded.created_at",
        (version_id, song.id, name, rel, sha, rank),
    )
    return True


def drop_file(conn: sqlite3.Connection, library_dir: Path, *, song: Song, name: str) -> None:
    """Forget a kept file and delete it from the library."""
    row = conn.execute("SELECT path FROM files WHERE song_id = ? AND name = ?", (song.id, name)).fetchone()
    if row is None:
        return
    (library_dir / row[0]).unlink(missing_ok=True)
    conn.execute("DELETE FROM files WHERE song_id = ? AND name = ?", (song.id, name))


def write_info(conn: sqlite3.Connection, library_dir: Path, song: Song) -> Path:
    """Write info.json: the song, where it came from, and what was kept or picked.

    ``key`` is the song's musical key ("A minor", "C") and ``key_source`` where it
    came from ("tab", "chords" or "audio"), both null when unknown (``keys.song_key``);
    ``identity_key`` is caracole's key for the song itself.

    An info.json that holds these bytes already is left alone: each rewrite is one more sync on
    every device.
    """
    from caracole.keys import song_key  # it reads the library through this module

    musical = song_key(conn, library_dir, song)
    files = []
    for f in kept_files(conn, song.id):
        v = get_version(conn, f.version_id)
        files.append({
            "name": f.name, "rank": f.kept_rank, "sha256": f.sha256, "provider": v.provider,
            "tab_id": v.tab_id, "kind": v.kind, "url": v.url, "rating": v.rating, "votes": v.votes,
            "version": v.version, "label": v.label, "coverage": v.coverage,
        })
    picked = [
        {"kind": v.kind, "rank": v.pick_rank, "url": v.url, "rating": v.rating, "votes": v.votes,
         "version": v.version, "label": v.label}
        for v in song_versions(conn, song.id)
        if v.pick_rank is not None
    ]
    rendered = kv_get_json(conn, f"render:{song.id}")  # recorded by render.render_all
    render = {"transpose": rendered["transpose"], "pdf": rendered["pdf"]} if rendered else None
    info = {
        "artist": song.artist,
        "title": song.title,
        "artists": song.artists,
        "album": song.album,
        "duration_ms": song.duration_ms,
        "isrc": song.isrc,
        "identity_key": song.key,
        "key": musical.key if musical else None,
        "key_source": musical.source if musical else None,
        "status": song.status,
        "sources": song.source_ids,
        "lyrics": song.lyrics_status,
        "match": {
            "decision": song.match_decision, "step": song.match_step, "score": song.match_score,
            "artist_key": song.match_artist_key, "song_key": song.match_song_key,
        },
        "files": files,
        "picks": sorted(picked, key=lambda p: (p["kind"], p["rank"])),
        "render": render,
    }
    path = song_dir(library_dir, song) / "info.json"
    data = (json.dumps(info, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if not holds(path, hashlib.sha256(data).hexdigest(), len(data)):
        write_atomic(path, data)
    return path
