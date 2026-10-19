"""Read access to the local UG index and learned artist pages, shared by matching and fetching."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from tabarr.db import kv_get, kv_set
from tabarr.normalize import split_variant


@dataclass(frozen=True)
class IndexTab:
    tab_id: int
    type: str
    song_key: str
    label: str | None


def song_tabs(conn: sqlite3.Connection, artist_key: str, song_key: str) -> list[IndexTab]:
    """Every indexed tab of a song, including variant slugs such as ``song-key-acoustic``."""
    rows = conn.execute(
        "SELECT tab_id, type, song_key FROM ug_index WHERE artist_key = ? AND (song_key = ? OR song_key LIKE ?) "
        "ORDER BY tab_id",
        (artist_key, song_key, song_key + "-%"),
    )
    out: list[IndexTab] = []
    for r in rows:
        if r["song_key"] == song_key:
            out.append(IndexTab(r["tab_id"], r["type"], r["song_key"], None))
            continue
        base, label = split_variant(r["song_key"])
        if base == song_key:
            out.append(IndexTab(r["tab_id"], r["type"], r["song_key"], label))
    return out


def artist_tab_ids(conn: sqlite3.Connection, artist_key: str, limit: int = 5) -> list[int]:
    """A few slugged tab ids of an artist, oldest first (to learn the artist's page URL)."""
    rows = conn.execute(
        "SELECT tab_id FROM ug_index WHERE artist_key = ? ORDER BY tab_id LIMIT ?", (artist_key, limit)
    )
    return [r[0] for r in rows]


def artist_known(conn: sqlite3.Connection, artist_key: str) -> bool:
    return conn.execute("SELECT 1 FROM ug_index WHERE artist_key = ? LIMIT 1", (artist_key,)).fetchone() is not None


def _artist_url_key(artist_key: str) -> str:
    return f"ug:artist_url:{artist_key}"


def learned_artist_url(conn: sqlite3.Connection, artist_key: str) -> str | None:
    return kv_get(conn, _artist_url_key(artist_key))


def remember_artist_url(conn: sqlite3.Connection, artist_key: str, url: str) -> None:
    kv_set(conn, _artist_url_key(artist_key), url)
