"""The suite's own machinery: conftest.py's database, and the helper that waits on
caracole's lock (helpers/locks.py). Each makes the suite faster; these tests say it still
tests the same."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import threading
import time

import conftest
from helpers.locks import waiting_for

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


# --- waiting for the lock ----------------------------------------------------------------------


def test_a_wait_for_the_lock_is_seen_as_soon_as_it_starts(tmp_path):
    lock = tmp_path / "caracole.lock"
    held = os.open(lock, os.O_RDWR | os.O_CREAT)
    fcntl.flock(held, fcntl.LOCK_EX)

    def wait():
        fd = os.open(lock, os.O_RDWR)  # an open file of its own, as another caracole has
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        finally:
            os.close(fd)

    thread = threading.Thread(target=wait, daemon=True)
    try:
        thread.start()
        start = time.monotonic()
        assert waiting_for(lock, thread.is_alive, timeout=30)
        assert time.monotonic() - start < 10  # seen in /proc/locks, not given up on after 30 s
    finally:
        os.close(held)
    thread.join(10)
    assert not thread.is_alive()


def test_a_command_that_never_waited_is_not_waiting(tmp_path):
    lock = tmp_path / "caracole.lock"
    lock.touch()
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    assert not waiting_for(lock, thread.is_alive)


def test_a_command_still_busy_after_the_timeout_counts_as_waiting(tmp_path):
    # Where /proc/locks says nothing, all a test can tell: the command hasn't finished.
    lock = tmp_path / "caracole.lock"
    lock.touch()
    assert waiting_for(lock, lambda: True, timeout=0.05)
