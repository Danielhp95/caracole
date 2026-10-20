"""The suite's own machinery: conftest.py's database. It makes the suite faster; these
tests say it still tests the same."""

from __future__ import annotations

import sqlite3

import conftest

from caracole import db

# --- the database ------------------------------------------------------------------------------


def schema(c: sqlite3.Connection) -> tuple:
    rows = c.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    return [tuple(r) for r in rows], c.execute("PRAGMA user_version").fetchone()[0]


def test_conn_is_the_database_db_connect_makes(conn, tmp_path):
    made = db.connect(tmp_path / "made" / "caracole.sqlite")
    try:
        assert schema(conn) == schema(made) and schema(conn)[1] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        made.close()
    assert not list((tmp_path / "state").glob("*.bak"))  # a new database, not a migrated one


def test_what_a_test_writes_stays_in_its_own_copy(conn, tmp_path):
    db.kv_set(conn, "harness:written", "1")
    other = tmp_path / "other.sqlite"
    other.write_bytes(conftest.migrated_database())
    c = sqlite3.connect(other)
    try:
        assert c.execute("SELECT count(*) FROM kv").fetchone()[0] == 0
    finally:
        c.close()


def test_a_patched_migration_gets_a_database_of_its_own(monkeypatch, tmp_path):
    before = conftest.migrated_database()
    monkeypatch.setattr(db, "SCHEMA_VERSION", db.SCHEMA_VERSION + 1)
    monkeypatch.setitem(db._MIGRATIONS, db.SCHEMA_VERSION, "CREATE TABLE harness (x TEXT);")
    path = tmp_path / "patched.sqlite"
    path.write_bytes(conftest.migrated_database())
    c = sqlite3.connect(path)
    try:
        tables, version = schema(c)
        assert ("table", "harness", "CREATE TABLE harness (x TEXT)") in tables
        assert version == db.SCHEMA_VERSION
    finally:
        c.close()
    monkeypatch.undo()
    assert conftest.migrated_database() == before
