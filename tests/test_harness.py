"""The suite's own machinery: conftest.py's database, its pytest-xdist defaults and tmp_path in
memory, and the helpers that wait on caracole's lock (helpers/locks.py) and open pages in Chromium
(helpers/browser.py). Each makes the suite faster; these tests say it still tests the same."""

from __future__ import annotations

import fcntl
import gc
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import conftest
import pytest
from helpers import browser
from helpers.browser import in_chromium
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


# --- pytest-xdist ------------------------------------------------------------------------------


WHOLE_SUITE = pytest.Config.ArgsSource.TESTPATHS
GIVEN_PATHS = pytest.Config.ArgsSource.ARGS


def config(args_source=WHOLE_SUITE, *, xdist=True, worker=False, **options):
    """What pytest_cmdline_main reads of a pytest.Config, as pytest parsed a command line."""
    parsed = {"numprocesses": None, "tx": None, "dist": "no", "collectonly": False,
              "usepdb": False, "trace": False, "capture": "fd"}
    made = SimpleNamespace(
        option=SimpleNamespace(**{**parsed, **options}), args_source=args_source,
        pluginmanager=SimpleNamespace(hasplugin=lambda name: xdist and name == "xdist"),
    )
    if worker:
        made.workerinput = {}
    return made


@pytest.mark.parametrize("given, expected", [
    pytest.param({}, ("auto", "worksteal"), id="pytest"),
    pytest.param({"numprocesses": 4}, (4, "worksteal"), id="-n 4"),
    pytest.param({"args_source": GIVEN_PATHS, "numprocesses": 4}, (4, "worksteal"), id="paths -n 4"),
    pytest.param({"numprocesses": 4, "dist": "load"}, (4, "load"), id="-n 4 --dist load"),
    pytest.param({"numprocesses": 0}, (0, "no"), id="-n 0"),
    pytest.param({"args_source": GIVEN_PATHS}, (None, "no"), id="paths"),
    pytest.param({"collectonly": True}, (None, "no"), id="--collect-only"),
    pytest.param({"usepdb": True}, (None, "no"), id="--pdb"),
    pytest.param({"trace": True}, (None, "no"), id="--trace"),
    pytest.param({"capture": "no"}, (None, "no"), id="-s"),
    pytest.param({"worker": True}, (None, "no"), id="a worker"),
    pytest.param({"xdist": False}, (None, "no"), id="no xdist"),
])
def test_the_whole_suite_runs_on_workers_unless_told_otherwise(given, expected):
    parsed = config(**given)
    conftest.pytest_cmdline_main(parsed)
    assert (parsed.option.numprocesses, parsed.option.dist) == expected


def test_what_collection_made_is_out_of_the_garbage_collectors_way():
    # Every module, test and fixture lives for the whole session: gc.freeze() after collection
    # spares the collector walking them each time it looks for cycles.
    assert gc.get_freeze_count() > 10_000


def test_auto_means_the_cores_up_to_a_dozen(monkeypatch):
    monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: set(range(24)))
    assert conftest.pytest_xdist_auto_num_workers(None) == conftest.MAX_WORKERS == 12
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 1, 2})
    assert conftest.pytest_xdist_auto_num_workers(None) == 3
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "5")
    assert conftest.pytest_xdist_auto_num_workers(None) is None  # pytest-xdist's own hook reads it


# --- tmp_path in memory ------------------------------------------------------------------------


GiB = 1 << 30


def tmp_root_given(monkeypatch, tmp_path, *, noexec=False, free=16 * GiB, basetemp=None,
                   missing=False) -> str | None:
    """Where pytest_configure puts tmp_path when /dev/shm (here tmp_path) is a tmpfs so mounted:
    the PYTEST_DEBUG_TEMPROOT it sets, or None for pytest's own."""

    def statvfs(path):
        assert Path(path) == tmp_path
        if missing:
            raise FileNotFoundError(path)
        return SimpleNamespace(f_flag=os.ST_NOSUID | os.ST_NODEV | (os.ST_NOEXEC if noexec else 0),
                               f_frsize=4096, f_bsize=4096, f_bavail=free // 4096)

    monkeypatch.setattr(conftest, "MEMORY", tmp_path)
    monkeypatch.setattr(os, "statvfs", statvfs)
    monkeypatch.delenv("PYTEST_DEBUG_TEMPROOT", raising=False)  # restored when the test ends
    conftest.pytest_configure(SimpleNamespace(option=SimpleNamespace(basetemp=basetemp)))
    return os.environ.get("PYTEST_DEBUG_TEMPROOT")


def test_tmp_path_goes_to_a_roomy_tmpfs_that_runs_programs(monkeypatch, tmp_path):
    assert tmp_root_given(monkeypatch, tmp_path) == str(tmp_path)


@pytest.mark.parametrize("mounted", [
    # Docker's and podman's /dev/shm: a test's fake chordpro couldn't run there.
    pytest.param({"noexec": True, "free": 64 << 20}, id="docker"),
    pytest.param({"noexec": True}, id="noexec"),  # hardened hosts
    pytest.param({"free": GiB - 4096}, id="under a gigabyte free"),
    pytest.param({"missing": True}, id="no /dev/shm"),
    pytest.param({"basetemp": "/var/tmp/given"}, id="--basetemp"),
])
def test_tmp_path_stays_on_disk_where_memory_wont_do(monkeypatch, tmp_path, mounted):
    assert tmp_root_given(monkeypatch, tmp_path, **mounted) is None


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


# --- pages in Chromium -------------------------------------------------------------------------


PAGE = """<!doctype html><html><body><script>
document.body.dataset.seen = localStorage.getItem("harness") || "nothing";
localStorage.setItem("harness", "kept");
document.body.dataset.kept = localStorage.getItem("harness");
document.body.dataset.width = String(window.innerWidth);
setTimeout(() => { document.body.dataset.later = "ran"; }, 2500);
</script></body></html>
"""


def data(dom: str, name: str) -> str | None:
    found = re.search(rf'data-{name}="([^"]*)"', dom)
    return found.group(1) if found else None


@in_chromium
def test_each_page_opens_as_in_a_new_profile(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(PAGE, encoding="utf-8")
    first = browser.dump_dom(page.as_uri(), (800, 600))
    second = browser.dump_dom(page.as_uri(), (800, 600))
    assert data(first, "kept") == "kept"  # the page could keep something
    assert data(first, "seen") == data(second, "seen") == "nothing"  # and the next page never sees it


@in_chromium
def test_the_browser_looks_up_no_host_and_stays_off_the_desktop(tmp_path, monkeypatch):
    # Left alone, Chromium asks DNS for Google's update servers and connects to them, and to the
    # desktop's display and session bus. Twelve of them starting at once kept nscd busy for
    # seconds, and with it every process asking it for a user or a host: chordpro among them.
    for name, value in (("DISPLAY", ":0"), ("WAYLAND_DISPLAY", "wayland-1"),
                        ("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")):
        monkeypatch.setenv(name, value)
    browser.close()  # a browser of its own, started with this environment
    try:
        process = browser.browser().process
        args = process.args
        listed = Path(f"/proc/{process.pid}/environ").read_bytes().decode(errors="replace")
        environ = dict(line.split("=", 1) for line in listed.split("\0") if "=" in line)
    finally:
        browser.close()
    assert "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1" in args
    assert not {"DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"} & environ.keys()


@in_chromium
def test_a_page_gets_the_window_asked_for_and_its_timers_run(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(PAGE, encoding="utf-8")
    # Narrower than the 500 pixels chromium --window-size gives at the least.
    dom = browser.dump_dom(page.as_uri(), (390, 844), hide_scrollbars=True)
    assert data(dom, "width") == "390"
    assert data(dom, "later") == "ran"  # within the three seconds --virtual-time-budget gave
    assert dom.startswith("<!DOCTYPE html>")
