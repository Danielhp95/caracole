"""Substring search over the local UG index's keys: search.py's prefilter, read from an index.

``ug_index`` holds about 1.6 million rows. A ``LIKE '%creep%'`` on its artist
and song keys reads every row twice, about 0.4 s a pattern: too slow to search
as you type. ``ug_keys`` holds each distinct key once (about 870,000, artist and
song keys alike) and ``ug_keys_fts`` indexes their trigrams (db.py, schema 4),
so a pattern with a run of three letters or more reads the trigram index; a
shorter one (``%u2%``) reads the keys, not the rows. The keys found then reach
the rows through ``ug_index``'s own indexes, by artist and by song.

``rows_like`` answers what the scan would: what the patterns find is the same,
only how fast, except for a pattern of a word in tens of thousands of keys
("the", "love", "you"). Every song of those keys would be ranked, about a
second a keystroke; such a pattern brings in its ``KEYS_PER_PATTERN`` shortest
keys instead (an exact title or artist is the shortest key a word is in, and
ranks first), together with the keys every pattern of the query is in, so
"i love you baby" still finds ``i-love-you-baby``. On the full index the
slowest queries, of common words alone, then answer in 0.05-0.16 s instead of
0.3-1.4 s, with the same first hits (29 of 30 such queries had the same eight).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

KEYS_PER_PATTERN = 1000  # keys one pattern brings in at most: its shortest
_KEYS = "temp._ug_like"
_CREATE = "CREATE TEMP TABLE IF NOT EXISTS _ug_like (key TEXT PRIMARY KEY) WITHOUT ROWID"
_SHORTEST = "ORDER BY length(key), key LIMIT ?"
_BY_TRIGRAMS = (f"INSERT OR IGNORE INTO {_KEYS} SELECT key FROM ug_keys "
                f"WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?) {_SHORTEST}")
_BY_SCAN = f"INSERT OR IGNORE INTO {_KEYS} SELECT key FROM ug_keys WHERE key LIKE ? {_SHORTEST}"
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


def _every(patterns: Sequence[str]) -> str:
    """The keys every pattern is in, from the trigram index: the shortest ``KEYS_PER_PATTERN`` too."""
    likes = " AND ".join("key LIKE ?" for _ in patterns)
    return (f"INSERT OR IGNORE INTO {_KEYS} SELECT key FROM ug_keys "
            f"WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE {likes}) {_SHORTEST}")


def rows_like(conn: sqlite3.Connection, patterns: Sequence[str]) -> list[tuple[str, str, int]]:
    """(artist key, song key, rows) for each song key of an artist whose artist key or song key matches
    any of ``patterns`` (``LIKE``, without ``_`` or an escape): what ``SELECT artist_key, song_key,
    COUNT(*) FROM ug_index WHERE artist_key LIKE ? OR song_key LIKE ? … GROUP BY artist_key, song_key``
    gives, a pattern of more than ``KEYS_PER_PATTERN`` keys reading its shortest ones and the keys
    every pattern is in (see the module's docstring)."""
    if not patterns:
        return []
    conn.execute(_CREATE)
    conn.execute(f"DELETE FROM {_KEYS}")
    try:
        if len(patterns) > 1 and all(indexed(p) for p in patterns):
            conn.execute(_every(patterns), (*patterns, KEYS_PER_PATTERN))
        for pattern in patterns:
            conn.execute(_BY_TRIGRAMS if indexed(pattern) else _BY_SCAN, (pattern, KEYS_PER_PATTERN))
        return [(r[0], r[1], r[2]) for r in conn.execute(_ROWS)]
    finally:
        conn.execute(f"DELETE FROM {_KEYS}")
