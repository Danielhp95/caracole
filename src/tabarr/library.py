"""The library folder: one directory per song, with the files tabarr keeps (plan §5).

    Library/
      Soda Stereo/
        De Música Ligera/
          sheet.txt  sheet.json  sheet.cho  sheet.pdf
          lyrics.txt lyrics.lrc  guitar-1.gp5  tab.txt  info.json

Names keep their accents and scripts ("宋冬野/斑马，斑马/") but never contain a
path separator or a reserved character, so a song can't escape the library.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from tabarr.db import kv_get_json
from tabarr.normalize import clean_title
from tabarr.songs import Song
from tabarr.versions import get_version, song_versions

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
    """Write through a temporary file and rename; return the SHA-256 of the data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return hashlib.sha256(data).hexdigest()


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
    """Write info.json: the song, where it came from, and what was kept or picked."""
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
        "key": song.key,
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
    write_atomic(path, (json.dumps(info, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return path
