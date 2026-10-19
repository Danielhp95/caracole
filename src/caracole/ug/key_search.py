"""Substring search over the local UG index's keys: search.py's prefilter, read from an index.

``ug_index`` holds about 1.6 million rows. A ``LIKE '%creep%'`` on its artist
and song keys reads every row twice, about 0.4 s a pattern: too slow to search
as you type. ``ug_keys`` holds each distinct key once (about 870,000, artist and
song keys alike) and ``ug_keys_fts`` indexes their trigrams (db.py, schema 4),
so a pattern with a run of three letters or more reads the trigram index; a
shorter one (``%u2%``) reads the keys, not the rows. The keys found then reach
the rows through ``ug_index``'s own indexes, by artist and by song.

``rows_like`` answers exactly what the scan would: what the patterns find is
the same, only how fast.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

_KEYS = "temp._ug_like"
_CREATE = "CREATE TEMP TABLE IF NOT EXISTS _ug_like (key TEXT PRIMARY KEY) WITHOUT ROWID"
_BY_TRIGRAMS = f"INSERT OR IGNORE INTO {_KEYS} SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?)"
_BY_SCAN = f"INSERT OR IGNORE INTO {_KEYS} SELECT key FROM ug_keys WHERE key LIKE ?"
_ROWS = (
    f"SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE artist_key IN (SELECT key FROM {_KEYS}) "
    "GROUP BY artist_key, song_key "
    "UNION ALL "
    f"SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE song_key IN (SELECT key FROM {_KEYS}) "
    f"AND artist_key NOT IN (SELECT key FROM {_KEYS}) GROUP BY artist_key, song_key"
)


def indexed(pattern: str) -> bool:
    """Whether the trigram index can answer a ``LIKE`` pattern: one run of three characters or more."""
    return any(len(run) >= 3 for run in pattern.split("%"))


def rows_like(conn: sqlite3.Connection, patterns: Sequence[str]) -> list[tuple[str, str, int]]:
    """(artist key, song key, rows) for each song key of an artist whose artist key or song key matches
    any of ``patterns`` (``LIKE``, without ``_`` or an escape): what ``SELECT artist_key, song_key,
    COUNT(*) FROM ug_index WHERE artist_key LIKE ? OR song_key LIKE ? … GROUP BY artist_key, song_key``
    gives."""
    if not patterns:
        return []
    conn.execute(_CREATE)
    conn.execute(f"DELETE FROM {_KEYS}")
    try:
        for pattern in patterns:
            conn.execute(_BY_TRIGRAMS if indexed(pattern) else _BY_SCAN, (pattern,))
        return [(r[0], r[1], r[2]) for r in conn.execute(_ROWS)]
    finally:
        conn.execute(f"DELETE FROM {_KEYS}")
