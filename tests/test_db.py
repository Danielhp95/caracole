"""Migrations apply whole or not at all, after a backup; a newer database is refused."""

import sqlite3

import pytest

from tabarr import db


@pytest.fixture
def v1(tmp_path):
    """A database at schema version 1, holding one kv row."""
    path = tmp_path / "state" / "tabarr.sqlite"
    c = db.connect(path)
    db.kv_set(c, "spotify:top_tracks", "[]")
    c.close()
    return path


@pytest.fixture
def v2(monkeypatch):
    """Pretend this tabarr knows schema version 2; returns a setter for its migration script."""
    monkeypatch.setattr(db, "SCHEMA_VERSION", 2)

    def script(sql: str) -> None:
        monkeypatch.setitem(db._MIGRATIONS, 2, sql)

    return script


def columns(path, table):
    """The table's column names and the database's user_version."""
    c = sqlite3.connect(path)
    try:
        names = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
        return names, c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


def test_a_migration_that_fails_midway_changes_nothing(v1, v2):
    v2("ALTER TABLE songs ADD COLUMN capo INTEGER;\nALTER TABLE songs ADD COLUMN capo INTEGER;")
    with pytest.raises(sqlite3.OperationalError, match="duplicate column"):
        db.connect(v1)
    cols, version = columns(v1, "songs")
    assert "capo" not in cols and version == 1
    # Fixed, the migration then applies on the next start, and nothing still holds the database.
    v2("ALTER TABLE songs ADD COLUMN capo INTEGER;")
    db.connect(v1).close()
    cols, version = columns(v1, "songs")
    assert "capo" in cols and version == 2


def test_the_database_is_backed_up_before_a_migration(v1, v2):
    v2("ALTER TABLE kv ADD COLUMN at TEXT;")
    db.connect(v1).close()
    backup = v1.with_name("tabarr.sqlite.v1.bak")
    cols, version = columns(backup, "kv")
    assert version == 1 and cols == ["key", "value"]
    b = sqlite3.connect(backup)
    assert b.execute("SELECT value FROM kv WHERE key = 'spotify:top_tracks'").fetchone()[0] == "[]"
    b.close()


def test_a_new_database_needs_no_backup(tmp_path):
    db.connect(tmp_path / "tabarr.sqlite").close()
    assert not list(tmp_path.glob("*.bak"))


def test_a_database_newer_than_this_tabarr_is_refused(v1):
    c = sqlite3.connect(v1)
    c.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    c.close()
    with pytest.raises(db.DatabaseTooNew, match=r"schema version 2.*tabarr knows up to 1") as e:
        db.connect(v1)
    # A DatabaseError: `tabarr add` reports it and keeps the line in wanted.txt.
    assert isinstance(e.value, sqlite3.DatabaseError)
    assert columns(v1, "kv")[1] == 2


def test_after_a_rollback_the_refusal_names_the_copy_saved_before(v1, v2, monkeypatch):
    v2("ALTER TABLE kv ADD COLUMN at TEXT;")
    db.connect(v1).close()
    monkeypatch.setattr(db, "SCHEMA_VERSION", 1)  # the older tabarr runs again
    with pytest.raises(db.DatabaseTooNew, match=r"restore tabarr\.sqlite\.v1\.bak"):
        db.connect(v1)
