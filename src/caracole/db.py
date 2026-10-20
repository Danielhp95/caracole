"""The SQLite file: schema, migrations and a small key-value table.

Tables (plan §5, plus ``kv``):

- ``songs``: what you want to learn, and where each song stands.
- ``ug_index``: the local Ultimate Guitar index, built from sitemaps.
- ``gtptabs_index``: the pages gtptabs.com's sitemaps list, its artists and songs (schema 2).
- ``musescore_index``: the song pages MuseScore's sitemaps list, by title (schema 3).
- ``removed``: the songs ``caracole remove`` took out, which no source brings back
  until you ask for them again (schema 4).
- ``ug_keys`` and ``ug_keys_fts``: every key of ``ug_index``, with a trigram index for
  substring search (schema 5, ug/key_search.py).
- ``lacuerda_index``: LaCuerda's artists, from its listings, and the songs of the artist
  pages caracole has read (schema 6, lacuerda_index.py).
- ``versions``: every sheet, tab or Guitar Pro version seen for a song.
- ``files``: files kept in the library, with their SHA-256.
- ``events``: one row per network request.
- ``kv``: small state such as provider cooldowns, sitemap validators, learned
  artist page URLs and Spotify suggestions.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 6

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

# gtptabs.com's sitemaps, read by gtptabs_fetch.py: one row per artist or song page, keyed
# by its path ("tabs/2/blur/song-2-2.html"). An artist page has no title: '' in both title
# columns. base_key is title_key without a trailing version number ("song-2" for "song-2-2").
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS gtptabs_index (
  path TEXT PRIMARY KEY,
  artist_path TEXT NOT NULL,
  artist_key TEXT NOT NULL,
  title_key TEXT NOT NULL,
  base_key TEXT NOT NULL,
  sitemap TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS gtptabs_index_artist ON gtptabs_index(artist_key);
CREATE INDEX IF NOT EXISTS gtptabs_index_sitemap ON gtptabs_index(sitemap);
"""

# MuseScore's song sitemaps, read by musescore_fetch.py: one row per song page, keyed by
# MuseScore's id, the number ending its path ("song/wonderwall-1524"). The sitemaps name
# the title alone, so title_key is all there is to match on.
_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS musescore_index (
  page_id INTEGER PRIMARY KEY,
  path TEXT NOT NULL,
  title_key TEXT NOT NULL,
  sitemap TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS musescore_index_title ON musescore_index(title_key);
CREATE INDEX IF NOT EXISTS musescore_index_sitemap ON musescore_index(sitemap);
"""

# The songs `caracole remove` took out (removal.py): one row per song, under the identity key
# it had, with its display artist and title (to re-key it, as songs are re-keyed) and the
# source ids it had then, as songs.source_ids holds them. songs.upsert_song brings none of them
# back but for a wanted.txt line, or a Spotify track added after removed_at.
_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS removed (
  key TEXT PRIMARY KEY,
  artist TEXT NOT NULL,
  title TEXT NOT NULL,
  source_ids TEXT NOT NULL DEFAULT '{}',
  removed_at TEXT NOT NULL
);
"""

# Search as you type (caracole serve's lookup, caracole search): a trigram index over the
# distinct keys of ug_index, artist and song keys alike, so that a LIKE '%…%' pattern of three
# letters or more reads the index instead of 1.6 million rows twice (ug/key_search.py). The
# keys follow every row inserted or re-keyed; a key no row has any longer stays, matching
# nothing. detail=none: LIKE needs no positions, and the index is a third the size. The
# triggers test for the key first: an upsert's conflict handling would override OR IGNORE.
_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS ug_keys (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE
);
CREATE VIRTUAL TABLE IF NOT EXISTS ug_keys_fts USING fts5(
  key, content='ug_keys', content_rowid='id', tokenize='trigram', detail='none'
);
CREATE TRIGGER IF NOT EXISTS ug_keys_indexed AFTER INSERT ON ug_keys BEGIN
  INSERT INTO ug_keys_fts(rowid, key) VALUES (new.id, new.key);
END;
CREATE TRIGGER IF NOT EXISTS ug_index_keys_added AFTER INSERT ON ug_index BEGIN
  INSERT INTO ug_keys(key) SELECT new.artist_key WHERE NOT EXISTS (SELECT 1 FROM ug_keys WHERE key = new.artist_key);
  INSERT INTO ug_keys(key) SELECT new.song_key WHERE NOT EXISTS (SELECT 1 FROM ug_keys WHERE key = new.song_key);
END;
CREATE TRIGGER IF NOT EXISTS ug_index_keys_changed AFTER UPDATE OF artist_key, song_key ON ug_index
WHEN new.artist_key IS NOT old.artist_key OR new.song_key IS NOT old.song_key BEGIN
  INSERT INTO ug_keys(key) SELECT new.artist_key WHERE NOT EXISTS (SELECT 1 FROM ug_keys WHERE key = new.artist_key);
  INSERT INTO ug_keys(key) SELECT new.song_key WHERE NOT EXISTS (SELECT 1 FROM ug_keys WHERE key = new.song_key);
END;
INSERT OR IGNORE INTO ug_keys(key) SELECT artist_key FROM ug_index UNION SELECT song_key FROM ug_index;
CREATE INDEX IF NOT EXISTS events_provider_at ON events(provider, at);
"""

# LaCuerda's artist index, read by lacuerda_index.py. A row per artist of its listings, keyed
# by the path of their page ("estopa/"), and per song of an artist page caracole read
# ("estopa/como_camaron"); an artist's row has no title: '' in both title columns. The names
# are LaCuerda's, the keys their identity keys (Chinese in pinyin), made again from the names
# when caracole's keys change. songs: the songs an artist's listing counts; versions: a
# song's lcd letters, one per version; acordes: its best Letra y Acordes version, 0 for none;
# popular: its place in its artist page's order of popularity, 0 first. page: the listing
# page ("tabs/e/index0.html") or the artist page ("estopa/") the row was read from.
_SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS lacuerda_index (
  path TEXT PRIMARY KEY,
  artist_slug TEXT NOT NULL,
  artist TEXT NOT NULL,
  artist_key TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  title_key TEXT NOT NULL DEFAULT '',
  songs INTEGER NOT NULL DEFAULT 0,
  versions TEXT NOT NULL DEFAULT '',
  acordes INTEGER NOT NULL DEFAULT 0,
  popular INTEGER,
  page TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lacuerda_index_artist ON lacuerda_index(artist_key);
CREATE INDEX IF NOT EXISTS lacuerda_index_slug ON lacuerda_index(artist_slug);
CREATE INDEX IF NOT EXISTS lacuerda_index_page ON lacuerda_index(page);
"""

# Each script runs in one transaction with its PRAGMA user_version (see _migrate),
# so a script must not BEGIN or COMMIT itself.
_MIGRATIONS = {1: _SCHEMA_V1, 2: _SCHEMA_V2, 3: _SCHEMA_V3, 4: _SCHEMA_V4, 5: _SCHEMA_V5, 6: _SCHEMA_V6}


class DatabaseTooNew(sqlite3.DatabaseError):
    """The database was migrated by a newer caracole than this one."""


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database, apply migrations, and return it.

    Rows are ``sqlite3.Row``; each statement commits on its own (autocommit mode),
    where ``with conn:`` opens no transaction: writes that apply whole or not at
    all go in a ``savepoint``.

    Each migration applies whole or not at all, after the database is copied to
    ``<name>.v<N>.bak`` (N: the version it's migrated from). A database newer
    than this caracole, say after a NixOS rollback, raises DatabaseTooNew.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        # No fsync on each commit: a crash of the machine may lose the last commits, never the
        # database (WAL), and the owner chose the speed.
        conn.execute("PRAGMA synchronous = NORMAL")
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
        restore = ""
        if backup.exists():
            restore = f", or restore {backup.name}, the copy saved before it was migrated"
        raise DatabaseTooNew(
            f"{path} is at schema version {current}, but this caracole knows up to {SCHEMA_VERSION}: "
            f"a newer caracole migrated it. Run that caracole{restore}."
        )
    pending = sorted(v for v in _MIGRATIONS if v > current)
    if current and pending:
        backup = path.with_name(f"{path.name}.v{current}.bak")
        backup.unlink(missing_ok=True)  # VACUUM INTO won't overwrite an older copy
        conn.execute("VACUUM INTO ?", (str(backup),))
    for version in pending:
        # executescript adds no transaction of its own: without this one, each
        # statement would commit alone and a failure would leave half a migration.
        script = _MIGRATIONS[version]
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


@contextmanager
def savepoint(conn: sqlite3.Connection, name: str) -> Iterator[None]:
    """The block's writes, all or none: a transaction of its own, or one nested in the caller's.

    Any exception, a Ctrl-C too, undoes the block and goes on up; a caller's
    savepoint around it can still undo it. ``name`` is a constant identifier.
    """
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    conn.execute(f"RELEASE {name}")


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
