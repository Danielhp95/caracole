"""Migrations apply whole or not at all, after a backup; a newer database is refused."""

import sqlite3

import pytest

from caracole import db

NOW = db.SCHEMA_VERSION  # the schema this caracole makes
NEXT = NOW + 1


@pytest.fixture
def current(tmp_path):
    """A database at this caracole's schema version, holding one kv row."""
    path = tmp_path / "state" / "caracole.sqlite"
    c = db.connect(path)
    db.kv_set(c, "spotify:top_tracks", "[]")
    c.close()
    return path


@pytest.fixture
def newer(monkeypatch):
    """Pretend this caracole knows one schema version more; returns a setter for its migration script."""
    monkeypatch.setattr(db, "SCHEMA_VERSION", NEXT)

    def script(sql: str) -> None:
        monkeypatch.setitem(db._MIGRATIONS, NEXT, sql)

    return script


def columns(path, table):
    """The table's column names and the database's user_version."""
    c = sqlite3.connect(path)
    try:
        names = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
        return names, c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


def test_a_migration_that_fails_midway_changes_nothing(current, newer):
    newer("ALTER TABLE songs ADD COLUMN capo INTEGER;\nALTER TABLE songs ADD COLUMN capo INTEGER;")
    with pytest.raises(sqlite3.OperationalError, match="duplicate column"):
        db.connect(current)
    cols, version = columns(current, "songs")
    assert "capo" not in cols and version == NOW
    # Fixed, the migration then applies on the next start, and nothing still holds the database.
    newer("ALTER TABLE songs ADD COLUMN capo INTEGER;")
    db.connect(current).close()
    cols, version = columns(current, "songs")
    assert "capo" in cols and version == NEXT


def test_the_database_is_backed_up_before_a_migration(current, newer):
    newer("ALTER TABLE kv ADD COLUMN at TEXT;")
    db.connect(current).close()
    backup = current.with_name(f"caracole.sqlite.v{NOW}.bak")
    cols, version = columns(backup, "kv")
    assert version == NOW and cols == ["key", "value"]
    b = sqlite3.connect(backup)
    assert b.execute("SELECT value FROM kv WHERE key = 'spotify:top_tracks'").fetchone()[0] == "[]"
    b.close()


def test_a_new_database_needs_no_backup(tmp_path):
    db.connect(tmp_path / "caracole.sqlite").close()
    assert not list(tmp_path.glob("*.bak"))


def test_a_database_newer_than_this_caracole_is_refused(current):
    c = sqlite3.connect(current)
    c.execute(f"PRAGMA user_version = {NEXT}")
    c.close()
    with pytest.raises(db.DatabaseTooNew, match=rf"schema version {NEXT}.*caracole knows up to {NOW}") as e:
        db.connect(current)
    # A DatabaseError: `caracole add` reports it and keeps the line in wanted.txt.
    assert isinstance(e.value, sqlite3.DatabaseError)
    assert columns(current, "kv")[1] == NEXT


def test_after_a_rollback_the_refusal_names_the_copy_saved_before(current, newer, monkeypatch):
    newer("ALTER TABLE kv ADD COLUMN at TEXT;")
    db.connect(current).close()
    monkeypatch.setattr(db, "SCHEMA_VERSION", NOW)  # the older caracole runs again
    with pytest.raises(db.DatabaseTooNew, match=rf"restore caracole\.sqlite\.v{NOW}\.bak"):
        db.connect(current)


def test_a_version_1_database_gains_the_gtptabs_index_and_keeps_its_songs(tmp_path):
    # As caracole 0.1 left it before gtptabs.com: schema 1, with a song in it.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript(db._MIGRATIONS[1] + "\nPRAGMA user_version = 1;")
    old.execute(
        "INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES ('blur/song-2', 'Blur', 'Song 2', '[\"Blur\"]', 'x', 'x', 'x')"
    )
    old.commit()
    old.close()

    db.connect(path).close()

    cols, version = columns(path, "gtptabs_index")
    assert version == NOW
    assert cols == ["path", "artist_path", "artist_key", "title_key", "base_key", "sitemap"]
    c = sqlite3.connect(path)
    assert c.execute("SELECT key FROM songs").fetchall() == [("blur/song-2",)]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v1.bak"), "gtptabs_index") == ([], 1)


def test_a_version_2_database_gains_the_musescore_index_and_keeps_its_gtptabs_rows(tmp_path):
    # As the gtptabs.com caracole left it: schema 2, with a row of gtptabs.com's index.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript(db._MIGRATIONS[1] + db._MIGRATIONS[2] + "\nPRAGMA user_version = 2;")
    old.execute("INSERT INTO gtptabs_index VALUES ('tabs/2/blur.html', 'tabs/2/blur.html', 'blur', '', '', '1')")
    old.commit()
    old.close()

    db.connect(path).close()

    cols, version = columns(path, "musescore_index")
    assert version == NOW
    assert cols == ["page_id", "path", "title_key", "sitemap"]
    c = sqlite3.connect(path)
    assert c.execute("SELECT artist_key FROM gtptabs_index").fetchall() == [("blur",)]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v2.bak"), "musescore_index") == ([], 2)


def test_a_version_3_database_gains_the_removed_songs_and_keeps_its_songs(tmp_path):
    # As the MuseScore caracole left it: schema 3, with a song in it.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript(db._MIGRATIONS[1] + db._MIGRATIONS[2] + db._MIGRATIONS[3] + "\nPRAGMA user_version = 3;")
    old.execute(
        "INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES ('blur/song-2', 'Blur', 'Song 2', '[\"Blur\"]', 'x', 'x', 'x')"
    )
    old.commit()
    old.close()

    db.connect(path).close()

    cols, version = columns(path, "removed")
    assert version == NOW
    assert cols == ["key", "artist", "title", "source_ids", "removed_at"]
    c = sqlite3.connect(path)
    assert c.execute("SELECT key FROM songs").fetchall() == [("blur/song-2",)]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v3.bak"), "removed") == ([], 3)


def test_a_version_3_database_gains_a_substring_index_of_its_ug_keys(tmp_path):
    # Typing into caracole serve's lookup searches 1.6 million index rows: a LIKE '%…%' scan of
    # both key columns took 0.4 s a pattern; the trigram index over the distinct keys answers in ms.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript(db._MIGRATIONS[1] + db._MIGRATIONS[2] + db._MIGRATIONS[3] + "\nPRAGMA user_version = 3;")
    old.executemany("INSERT INTO ug_index VALUES (?, ?, ?, 'chords', '1', 'x', '')",
                    [(1, "oasis", "wonderwall"), (2, "oasis", "wonderwall-acoustic"), (3, "radiohead", "creep")])
    old.commit()
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] >= 4
    assert sorted(r[0] for r in c.execute("SELECT key FROM ug_keys")) == [
        "creep", "oasis", "radiohead", "wonderwall", "wonderwall-acoustic"]
    found = c.execute("SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE '%derwa%')")
    assert sorted(r[0] for r in found) == ["wonderwall", "wonderwall-acoustic"]
    c.close()


def test_a_version_4_database_gains_the_substring_index_and_keeps_its_removed_songs(tmp_path):
    # As the remove caracole left it: schema 4, with an index row and a removed song.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in (1, 2, 3, 4)) + "\nPRAGMA user_version = 4;")
    old.execute("INSERT INTO ug_index VALUES (1, 'oasis', 'wonderwall', 'chords', '1', 'x', '')")
    old.execute("INSERT INTO removed VALUES ('blur/song-2', 'Blur', 'Song 2', '{}', 'x')")
    old.commit()
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW
    assert sorted(r[0] for r in c.execute("SELECT key FROM ug_keys")) == ["oasis", "wonderwall"]
    found = c.execute("SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE '%derwa%')")
    assert [r[0] for r in found] == ["wonderwall"]
    assert [tuple(r) for r in c.execute("SELECT key, artist, title FROM removed")] == [("blur/song-2", "Blur", "Song 2")]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v4.bak"), "ug_keys") == ([], 4)


def test_a_version_5_database_gains_the_lacuerda_index_and_keeps_its_ug_keys(tmp_path):
    # As the fast-lookup caracole left it: schema 5, with a song and an index row.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in (1, 2, 3, 4, 5)) + "\nPRAGMA user_version = 5;")
    old.execute("INSERT INTO ug_index VALUES (1, 'estopa', 'como-camaron', 'chords', '1', 'x', '')")
    old.execute(
        "INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES ('estopa/como-camaron', 'Estopa', 'Como Camarón', '[\"Estopa\"]', 'x', 'x', 'x')"
    )
    old.commit()
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW == 6
    c.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, page) "
              "VALUES ('estopa/', 'estopa', 'Estopa', 'estopa', 'tabs/e/index0.html')")
    row = c.execute("SELECT title, title_key, songs, versions, acordes, popular FROM lacuerda_index").fetchone()
    assert tuple(row) == ("", "", 0, "", 0, None)
    assert [r[0] for r in c.execute("SELECT key FROM songs")] == ["estopa/como-camaron"]
    assert sorted(r[0] for r in c.execute("SELECT key FROM ug_keys")) == ["como-camaron", "estopa"]
    c.close()
    cols, _ = columns(path, "lacuerda_index")
    assert cols == ["path", "artist_slug", "artist", "artist_key", "title", "title_key", "songs", "versions",
                    "acordes", "popular", "page"]
    assert columns(path.with_name("caracole.sqlite.v5.bak"), "lacuerda_index") == ([], 5)


def test_the_journal_trades_the_last_writes_before_a_power_cut_for_speed(conn):
    # WAL with synchronous NORMAL: a crash of the machine may lose the last commits, never the database.
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def test_a_savepoint_undoes_its_whole_block_and_nests(conn):
    def kv(key):
        return db.kv_get(conn, key)

    with db.savepoint(conn, "outer"):
        db.kv_set(conn, "a", "1")
        with pytest.raises(KeyboardInterrupt):  # any exception, a Ctrl-C too
            with db.savepoint(conn, "inner"):
                db.kv_set(conn, "b", "2")
                db.kv_set(conn, "a", "changed")
                raise KeyboardInterrupt
        assert conn.in_transaction and (kv("a"), kv("b")) == ("1", None)
        with db.savepoint(conn, "inner"):
            db.kv_set(conn, "c", "3")
    assert not conn.in_transaction
    assert (kv("a"), kv("b"), kv("c")) == ("1", None, "3")

    with pytest.raises(ValueError):
        with db.savepoint(conn, "outer"):
            db.kv_set(conn, "d", "4")
            db.kv_delete(conn, "a")
            raise ValueError
    assert not conn.in_transaction
    assert (kv("a"), kv("d")) == ("1", None)


def test_the_substring_index_follows_the_rows_a_sitemap_adds_or_renames(conn):
    from datetime import UTC, datetime

    from caracole.ug.index import upsert_rows

    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(1, "oasis", "wonderwall", "chords", "oasis/wonderwall-chords-1")], "1", when)
    upsert_rows(conn, [(1, "oasis", "wonderwal", "chords", "oasis/wonderwal-chords-1"),
                       (2, "blur", "song-2", "chords", "blur/song-2-chords-2")], "1", when)

    def like(pattern):
        return sorted(r[0] for r in conn.execute(
            "SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?)", (pattern,)))

    assert like("%wonderwal%") == ["wonderwal", "wonderwall"]  # an old key stays: it matches no row
    assert like("%song-2%") == ["song-2"] and like("%blur%") == ["blur"]
