"""Read access to the local UG index and learned artist pages, shared by matching and fetching."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from caracole.db import kv_delete, kv_get, kv_set
from caracole.normalize import split_variant
from caracole.ug.page import page_url


@dataclass(frozen=True)
class IndexTab:
    tab_id: int
    type: str
    song_key: str
    label: str | None
    path: str = ""

    @property
    def url(self) -> str:
        """The tab page URL; slugged tabs are only served at their slugged path."""
        return page_url(self.tab_id, self.path or None)


def song_tabs(conn: sqlite3.Connection, artist_key: str, song_key: str) -> list[IndexTab]:
    """Every indexed tab of a song, including variant slugs such as ``song-key-acoustic``."""
    rows = conn.execute(
        "SELECT tab_id, type, song_key, path FROM ug_index WHERE artist_key = ? AND (song_key = ? OR song_key LIKE ?) "
        "ORDER BY tab_id",
        (artist_key, song_key, song_key + "-%"),
    )
    out: list[IndexTab] = []
    for r in rows:
        if r["song_key"] == song_key:
            out.append(IndexTab(r["tab_id"], r["type"], r["song_key"], None, r["path"]))
            continue
        base, label = split_variant(r["song_key"])
        if base == song_key:
            out.append(IndexTab(r["tab_id"], r["type"], r["song_key"], label, r["path"]))
    return out


def artist_known(conn: sqlite3.Connection, artist_key: str) -> bool:
    return conn.execute("SELECT 1 FROM ug_index WHERE artist_key = ? LIMIT 1", (artist_key,)).fetchone() is not None


def _artist_url_key(artist_key: str) -> str:
    return f"ug:artist_url:{artist_key}"


def learned_artist_url(conn: sqlite3.Connection, artist_key: str) -> str | None:
    return kv_get(conn, _artist_url_key(artist_key))


def remember_artist_url(conn: sqlite3.Connection, artist_key: str, url: str) -> None:
    kv_set(conn, _artist_url_key(artist_key), url)


def _index_tab(row: sqlite3.Row) -> IndexTab:
    return IndexTab(row["tab_id"], row["type"], row["song_key"], split_variant(row["song_key"])[1], row["path"])


def index_tab(conn: sqlite3.Connection, tab_id: int) -> IndexTab | None:
    """One tab of the index by id, or None when the sitemaps list it bare (or not at all)."""
    row = conn.execute("SELECT tab_id, type, song_key, path FROM ug_index WHERE tab_id = ?", (tab_id,)).fetchone()
    return _index_tab(row) if row else None


def tab_url_for(conn: sqlite3.Connection, tab_id: int) -> str:
    """A tab's page URL: its slugged path when the index has it, else the bare ``/tab/{id}``."""
    tab = index_tab(conn, tab_id)
    return tab.url if tab is not None else page_url(tab_id)


def artist_tabs(conn: sqlite3.Connection, artist_key: str, limit: int = 5) -> list[IndexTab]:
    """A few slugged tabs of an artist, oldest first, with the paths their pages live at."""
    rows = conn.execute(
        "SELECT tab_id, type, song_key, path FROM ug_index WHERE artist_key = ? ORDER BY tab_id LIMIT ?",
        (artist_key, limit),
    )
    return [_index_tab(r) for r in rows]


def forget_artist_url(conn: sqlite3.Connection, artist_key: str) -> None:
    """Drop a learned artist page (UG no longer serves it), so it is learned again."""
    kv_delete(conn, _artist_url_key(artist_key))
