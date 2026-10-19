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
    assert version == NOW == 4
    assert cols == ["key", "artist", "title", "source_ids", "removed_at"]
    c = sqlite3.connect(path)
    assert c.execute("SELECT key FROM songs").fetchall() == [("blur/song-2",)]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v3.bak"), "removed") == ([], 3)
