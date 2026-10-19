"""The SQLite file: schema, migrations and a small key-value table.

Tables (plan §5, plus ``kv``):

- ``songs``: what you want to learn, and where each song stands.
- ``ug_index``: the local Ultimate Guitar index, built from sitemaps.
- ``versions``: every sheet, tab or Guitar Pro version seen for a song.
- ``files``: files kept in the library, with their SHA-256.
- ``events``: one row per network request.
- ``kv``: small state such as provider cooldowns, sitemap validators, learned
  artist page URLs and Spotify suggestions.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS songs (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  artist TEXT NOT NULL,
  title TEXT NOT NULL,
  artists TEXT NOT NULL,
  album TEXT,
  duration_ms INTEGER,
  isrc TEXT,
  source_ids TEXT NOT NULL DEFAULT '{}',
  added_at TEXT NOT NULL,
  variant TEXT,
  status TEXT NOT NULL DEFAULT 'wanted' CHECK (status IN ('wanted', 'found', 'ignored')),
  review INTEGER NOT NULL DEFAULT 0,
  match_decision TEXT,
  match_step TEXT,
  match_score REAL,
  match_artist_key TEXT,
  match_song_key TEXT,
  match_candidates TEXT NOT NULL DEFAULT '[]',
  matched_at TEXT,
  ug_dirty INTEGER NOT NULL DEFAULT 1,
  ug_checked_at TEXT,
  lyrics_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (lyrics_status IN ('pending', 'found', 'missing', 'instrumental')),
  lyrics_json TEXT,
  lyrics_at TEXT,
  lacuerda_checked_at TEXT,
  audio_path TEXT,
  audio_mtime REAL,
  autochords_mtime REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS songs_added ON songs(added_at);

CREATE TABLE IF NOT EXISTS ug_index (
  tab_id INTEGER PRIMARY KEY,
  artist_key TEXT NOT NULL,
  song_key TEXT NOT NULL,
  type TEXT NOT NULL,
  sitemap TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  path TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ug_index_artist ON ug_index(artist_key, song_key);
CREATE INDEX IF NOT EXISTS ug_index_song ON ug_index(song_key);

CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  tab_id TEXT NOT NULL,
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  slot TEXT NOT NULL CHECK (slot IN ('sheet', 'guitar')),
  kind TEXT NOT NULL,
  rating REAL NOT NULL DEFAULT 0,
  votes INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  label TEXT,
  coverage REAL,
  url TEXT NOT NULL,
  raw TEXT NOT NULL DEFAULT '{}',
  fetched_at TEXT NOT NULL,
  pick_rank INTEGER,
  gone INTEGER NOT NULL DEFAULT 0,
  UNIQUE (provider, tab_id, song_id)
);
CREATE INDEX IF NOT EXISTS versions_song ON versions(song_id, slot);

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL,
  kept_rank INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (song_id, name)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  run TEXT NOT NULL,
  at TEXT NOT NULL,
  provider TEXT NOT NULL,
  url TEXT,
  status INTEGER,
  decision TEXT NOT NULL,
  message TEXT
);
CREATE INDEX IF NOT EXISTS events_run ON events(run);

CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# Each script runs in one transaction with its PRAGMA user_version (see _migrate),
# so a script must not BEGIN or COMMIT itself.
_MIGRATIONS = {1: _SCHEMA_V1}


class DatabaseTooNew(sqlite3.DatabaseError):
    """The database was migrated by a newer tabarr than this one."""


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database, apply migrations, and return it.

    Rows are ``sqlite3.Row``; statements commit automatically (autocommit mode)
    unless the caller opens a transaction with ``with conn:``.

    Each migration applies whole or not at all, after the database is copied to
    ``<name>.v<N>.bak`` (N: the version it's migrated from). A database newer
    than this tabarr, say after a NixOS rollback, raises DatabaseTooNew.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        _migrate(conn, path)
    except BaseException:
        conn.close()
        raise
    return conn


def _migrate(conn: sqlite3.Connection, path: Path) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        backup = path.with_name(f"{path.name}.v{SCHEMA_VERSION}.bak")
        restore = f", or restore {backup.name}, the copy saved before it was migrated" if backup.exists() else ""
        raise DatabaseTooNew(
            f"{path} is at schema version {current}, but this tabarr knows up to {SCHEMA_VERSION}: "
            f"a newer tabarr migrated it. Run that tabarr{restore}."
        )
    pending = sorted(v for v in _MIGRATIONS if v > current)
    if current and pending:
        backup = path.with_name(f"{path.name}.v{current}.bak")
        backup.unlink(missing_ok=True)  # VACUUM INTO won't overwrite an older copy
        conn.execute("VACUUM INTO ?", (str(backup),))
    for version in pending:
        # executescript adds no transaction of its own: without this one, each
        # statement would commit alone and a failure would leave half a migration.
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{_MIGRATIONS[version]}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def kv_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def kv_delete(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM kv WHERE key = ?", (key,))


def kv_get_json(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    value = kv_get(conn, key)
    return json.loads(value) if value is not None else default


def kv_set_json(conn: sqlite3.Connection, key: str, value: Any) -> None:
    kv_set(conn, key, json.dumps(value, ensure_ascii=False))
