"""Song records: one row per song you want to learn, whatever source it came from.

A song's identity is ``normalize.identity_key(primary artist, title)``, so the
same song liked on Spotify and listed in ``wanted.txt`` (or a remaster next to
the original) becomes one record that remembers every source id.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence

from tabarr.normalize import display_key, identity_key, title_variant

_JSON_COLUMNS = {"artists", "source_ids", "match_candidates", "lyrics_json"}
_BOOL_COLUMNS = {"review", "ug_dirty"}
SHEET_FILE_NAMES = ("sheet.txt", "sheet (auto).txt")


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Song:
    id: int
    key: str
    artist: str
    title: str
    artists: list[str]
    album: str | None
    duration_ms: int | None
    isrc: str | None
    source_ids: dict[str, list[str]]
    added_at: str
    variant: str | None
    status: str
    review: bool
    match_decision: str | None
    match_step: str | None
    match_score: float | None
    match_artist_key: str | None
    match_song_key: str | None
    match_candidates: list[Any] = field(default_factory=list)
    matched_at: str | None = None
    ug_dirty: bool = True
    ug_checked_at: str | None = None
    lyrics_status: str = "pending"
    lyrics_json: Any = None
    lyrics_at: str | None = None
    lacuerda_checked_at: str | None = None
    audio_path: str | None = None
    audio_mtime: float | None = None
    autochords_mtime: float | None = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def display(self) -> str:
        """"Artist - Clean Title", as written in overrides.toml and on the to-do page."""
        return display_key(self.artist, self.title)

    @property
    def duration_s(self) -> float | None:
        return self.duration_ms / 1000 if self.duration_ms else None


_COLUMNS = tuple(Song.__dataclass_fields__)


def _from_row(row: sqlite3.Row) -> Song:
    values: dict[str, Any] = {}
    for name in _COLUMNS:
        value = row[name]
        if name == "lyrics_json":
            values[name] = value  # kept as the raw JSON text; lyrics.lyrics_from_json decodes it
        elif name in _JSON_COLUMNS and value is not None:
            values[name] = json.loads(value)
        elif name in _BOOL_COLUMNS:
            values[name] = bool(value)
        else:
            values[name] = value
    return Song(**values)


def get_song(conn: sqlite3.Connection, song_id: int) -> Song:
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if row is None:
        raise KeyError(f"no song with id {song_id}")
    return _from_row(row)


def find_song(conn: sqlite3.Connection, key: str) -> Song | None:
    row = conn.execute("SELECT * FROM songs WHERE key = ?", (key,)).fetchone()
    return _from_row(row) if row else None


def list_songs(conn: sqlite3.Connection, *, statuses: Iterable[str] | None = None) -> list[Song]:
    """Songs, newest ``added_at`` first (so a song you just added is handled first)."""
    if statuses is None:
        rows = conn.execute("SELECT * FROM songs ORDER BY added_at DESC, id DESC").fetchall()
    else:
        wanted = list(statuses)
        marks = ",".join("?" for _ in wanted)
        rows = conn.execute(
            f"SELECT * FROM songs WHERE status IN ({marks}) ORDER BY added_at DESC, id DESC", wanted
        ).fetchall()
    return [_from_row(r) for r in rows]


def upsert_song(
    conn: sqlite3.Connection,
    *,
    artists: Sequence[str],
    title: str,
    album: str | None,
    duration_ms: int | None,
    isrc: str | None,
    source: str,
    source_id: str,
    added_at: str,
) -> tuple[int, bool]:
    """Insert a song or merge it into the existing record; return ``(song_id, created)``.

    Merging keeps the newest ``added_at``, fills fields that were empty, and adds
    the source id. The display artist and title of the first source are kept.
    """
    names = [a.strip() for a in artists if a and a.strip()]
    if not names:
        raise ValueError("a song needs at least one artist")
    title = title.strip()
    key = identity_key(names[0], title)
    now = utc_now_iso()
    row = conn.execute("SELECT * FROM songs WHERE key = ?", (key,)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO songs (key, artist, title, artists, album, duration_ms, isrc, source_ids, "
            "added_at, variant, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key, names[0], title, json.dumps(names, ensure_ascii=False), album, duration_ms, isrc,
                json.dumps({source: [source_id]}, ensure_ascii=False), added_at,
                title_variant(title), now, now,
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid, True

    existing = _from_row(row)
    ids = {k: list(v) for k, v in existing.source_ids.items()}
    bucket = ids.setdefault(source, [])
    if source_id not in bucket:
        bucket.append(source_id)
    conn.execute(
        "UPDATE songs SET source_ids = ?, added_at = ?, album = COALESCE(album, ?), "
        "duration_ms = COALESCE(duration_ms, ?), isrc = COALESCE(isrc, ?), "
        "variant = COALESCE(variant, ?), updated_at = ? WHERE id = ?",
        (
            json.dumps(ids, ensure_ascii=False), max(existing.added_at, added_at), album, duration_ms,
            isrc, title_variant(title), now, existing.id,
        ),
    )
    return existing.id, False


def update_song(conn: sqlite3.Connection, song_id: int, **fields: Any) -> None:
    """Set columns on a song; lists and dicts are stored as JSON, booleans as 0/1."""
    unknown = sorted(set(fields) - set(_COLUMNS) - {"id"})
    if unknown or "id" in fields:
        raise ValueError(f"unknown or read-only song field(s): {', '.join(unknown or ['id'])}")
    if not fields:
        return
    values: list[Any] = []
    for name, value in fields.items():
        if name in _JSON_COLUMNS and name != "lyrics_json" and value is not None:
            value = json.dumps(value, ensure_ascii=False)
        elif name in _BOOL_COLUMNS:
            value = int(bool(value))
        values.append(value)
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(
        f"UPDATE songs SET {assignments}, updated_at = ? WHERE id = ?",
        (*values, utc_now_iso(), song_id),
    )


def refresh_status(conn: sqlite3.Connection, song_id: int, *, ignored: bool) -> str:
    """Recompute and store a song's status: ignored, found (has a sheet) or wanted.

    A song is "found" only once it has a human or auto-generated sheet; a guitar
    part alone never makes it found.
    """
    if ignored:
        status = "ignored"
    else:
        marks = ",".join("?" for _ in SHEET_FILE_NAMES)
        has_sheet = conn.execute(
            f"SELECT 1 FROM files WHERE song_id = ? AND name IN ({marks}) LIMIT 1",
            (song_id, *SHEET_FILE_NAMES),
        ).fetchone()
        status = "found" if has_sheet else "wanted"
    update_song(conn, song_id, status=status)
    return status
