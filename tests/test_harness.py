"""The suite's own machinery: conftest.py's database, its pytest-xdist defaults and tmp_path in
memory, and the helpers that wait on caracole's lock (helpers/locks.py) and open pages in Chromium
(helpers/browser.py). Each makes the suite faster; these tests say it still tests the same."""

from __future__ import annotations

import fcntl
import gc
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import conftest
import pytest
from helpers import browser, chromium, locks
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
              "usepdb": False, "trace": False, "capture": "fd", "markexpr": ""}
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
    pytest.param({"markexpr": "not slow"}, ("auto", "worksteal"), id="-m 'not slow'"),
    # The model tests: torch, librosa and beat_this in each worker, a gigabyte or more apiece.
    pytest.param({"markexpr": "autochords"}, (None, "no"), id="-m autochords"),
    pytest.param({"markexpr": " autochords "}, (None, "no"), id="-m ' autochords '"),
    pytest.param({"markexpr": "not autochords"}, ("auto", "worksteal"), id="-m 'not autochords'"),
    pytest.param({"worker": True}, (None, "no"), id="a worker"),
    pytest.param({"xdist": False}, (None, "no"), id="no xdist"),
])
def test_the_whole_suite_runs_on_workers_unless_told_otherwise(given, expected):
    parsed = config(**given)
    conftest.pytest_cmdline_main(parsed)
    assert (parsed.option.numprocesses, parsed.option.dist) == expected


class Item:
    """What pytest_collection_modifyitems reads and writes of a test."""

    def __init__(self, *marks: str):
        self.marks = set(marks)

    def get_closest_marker(self, name):
        return name if name in self.marks else None

    def add_marker(self, mark):
        self.marks.add(mark.name)


def test_chordpro_and_the_models_are_slow():
    items = [Item(), Item("chordpro"), Item("autochords"), Item("slow")]
    conftest.pytest_collection_modifyitems(items)
    assert [item.marks for item in items] == [
        set(), {"chordpro", "slow"}, {"autochords", "slow"}, {"slow"}]


@pytest.mark.slow
def test_collecting_the_model_tests_loads_no_model_package():
    # Every pytest-xdist worker collects them, and torch, librosa and beat_this would cost each
    # worker seconds and a gigabyte or more: a test that needs them loads them (needs_libs).
    tests = Path(__file__).parent
    code = ("import sys, test_autochords_models; "
            "print(*(m for m in ('torch', 'librosa', 'beat_this') if m in sys.modules))")
    env = {**os.environ, "PYTHONPATH": conftest.subprocess_pythonpath(tests.parent / "src")}
    found = subprocess.run([sys.executable, "-c", code], cwd=tests, env=env, capture_output=True,
                           text=True, timeout=120)
    assert found.returncode == 0, found.stderr[-2000:]
    assert found.stdout.split() == []


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


@pytest.mark.skipif(not os.access(locks.LOCKS, os.R_OK), reason="no /proc/locks to read")
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
        assert waiting_for(lock, thread.is_alive, timeout=5)
        assert time.monotonic() - start < 5  # seen in /proc/locks, not given up on after 5 s
    finally:
        os.close(held)
    thread.join(10)
    assert not thread.is_alive()


def test_a_wait_is_seen_where_proc_locks_names_another_device(tmp_path, monkeypatch):
    # /proc/locks names a file by its superblock's device, which stat gives otherwise on a btrfs
    # subvolume (where tmp_path is with --basetemp in a btrfs home): the inode alone says which.
    lock = tmp_path / "caracole.lock"
    lock.touch()
    st = lock.stat()
    inode, other = st.st_ino, f"{os.major(st.st_dev) + 1:02x}:{os.minor(st.st_dev):02x}"
    listed = tmp_path / "locks"
    listed.write_text(
        f"1: FLOCK  ADVISORY  WRITE 4241 {other}:{inode} 0 EOF\n"  # caracole's, held
        f"1: -> FLOCK  ADVISORY  WRITE 4242 {other}:{inode} 0 EOF\n"  # another, waiting
        f"2: POSIX  ADVISORY  WRITE 4243 {other}:{inode + 1} 0 EOF\n"
    )
    monkeypatch.setattr(locks, "LOCKS", listed)
    start = time.monotonic()
    assert waiting_for(lock, lambda: True, timeout=5)
    assert time.monotonic() - start < 5


def test_a_lock_held_is_no_wait(tmp_path, monkeypatch):
    lock = tmp_path / "caracole.lock"
    lock.touch()
    inode = lock.stat().st_ino
    listed = tmp_path / "locks"
    listed.write_text(
        f"1: FLOCK  ADVISORY  WRITE 4241 00:2f:{inode} 0 EOF\n"
        f"2: -> FLOCK  ADVISORY  WRITE 4242 00:2f:{inode + 1} 0 EOF\n"  # a wait on another file
        f"3: -> POSIX  ADVISORY  WRITE 4243 00:2f:{inode} 0 EOF\n"  # caracole takes an flock
    )
    monkeypatch.setattr(locks, "LOCKS", listed)
    running = iter([True, True, False])  # finishes on its own, never seen waiting
    assert not waiting_for(lock, lambda: next(running, False), timeout=5)


def test_a_command_that_never_waited_is_not_waiting(tmp_path):
    lock = tmp_path / "caracole.lock"
    lock.touch()
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    assert not waiting_for(lock, thread.is_alive)


@pytest.mark.skipif(not os.access(locks.LOCKS, os.R_OK), reason="no /proc/locks to read")
def test_a_command_slow_to_get_to_the_lock_is_not_waiting_until_it_does(tmp_path):
    # A busy machine: still on its way to the lock after the timeout, it isn't waiting yet; once it waits, it is.
    lock = tmp_path / "caracole.lock"
    held = os.open(lock, os.O_RDWR | os.O_CREAT)
    fcntl.flock(held, fcntl.LOCK_EX)
    seen = []
    late = threading.Thread(target=lambda: seen.append(waiting_for(lock, lambda: True, timeout=0.05)), daemon=True)
    try:
        late.start()
        late.join(0.5)  # ten times the timeout: not taken for a wait
        assert late.is_alive() and seen == []
        fd = os.open(lock, os.O_RDWR)
        waiter = threading.Thread(target=lambda: fcntl.flock(fd, fcntl.LOCK_EX), daemon=True)
        waiter.start()
        late.join(10)
        assert seen == [True]
    finally:
        os.close(held)
    waiter.join(10)
    os.close(fd)


def test_a_lookup_waiting_for_the_lock_is_seen_by_its_ticket(tmp_path):
    # A lookup tries for the lock again and again, blocking nowhere: its ticket says it waits.
    lock = tmp_path / "caracole.lock"
    lock.touch()
    running = iter([True] * 5 + [False])
    assert not waiting_for(lock, lambda: next(running, False))
    (tmp_path / "caracole.lock.waiting").mkdir()
    (tmp_path / "caracole.lock.waiting" / "4242.0").write_text("get Oasis - Wonderwall\n", encoding="utf-8")
    assert waiting_for(lock, lambda: True)


def test_a_command_still_busy_after_the_timeout_counts_as_waiting_where_proc_locks_cant_be_read(
        tmp_path, monkeypatch):
    # Where /proc/locks can't be read, all a test can tell: the command hasn't finished.
    monkeypatch.setattr(locks, "LOCKS", tmp_path / "no-proc-locks")
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
def test_the_browsers_profile_goes_with_the_runs_other_folders(tmp_path_factory):
    # Under the basetemp, where pytest clears it with the rest, even after a test process died
    # without closing its browser.
    browser.browser()
    assert browser._profile.is_dir()
    assert browser._profile.is_relative_to(tmp_path_factory.getbasetemp())


def test_a_test_that_opens_pages_without_in_chromium_fails(monkeypatch):
    # Its browser's profile would have no folder in the basetemp, and the test no slow marker.
    monkeypatch.setattr(browser, "CHROMIUM", "chromium")  # found, or the test would only skip
    monkeypatch.setattr(browser, "_browser", None)  # this process's own, if any, is put back
    monkeypatch.setattr(browser, "profiles", None)
    with pytest.raises(pytest.fail.Exception, match="@in_chromium"):
        browser.browser()


@pytest.mark.parametrize("opens", ["dump_dom", "Browser", "Chromium"])
def test_a_test_without_in_chromium_fails_whichever_browser_it_starts_and_whatever_ran_before(
        opens, monkeypatch, tmp_path):
    # Unmarked, it would run in the quick loop, and fail rather than skip where no Chromium runs; so
    # it fails at once, even after a marked test left this process's browser and its profiles set.
    def started(*args, **kwargs):
        raise AssertionError("a browser started")

    monkeypatch.setattr(browser, "CHROMIUM", "chromium")  # found, or the test would only skip
    monkeypatch.setattr(chromium, "CHROMIUM", "chromium")
    monkeypatch.setattr(browser, "_browser", None)  # this process's own, if any, is put back
    monkeypatch.setattr(browser, "_profile", None)
    monkeypatch.setattr(browser, "profiles", tmp_path)
    monkeypatch.setattr(browser, "SharedBrowser", started)
    monkeypatch.setattr(subprocess, "Popen", started)
    start = {"dump_dom": lambda: browser.dump_dom("about:blank", (390, 844)),
             "Browser": lambda: browser.Browser(tmp_path / "profile"),
             "Chromium": lambda: chromium.Chromium(tmp_path / "profile")}[opens]
    with pytest.raises(pytest.fail.Exception, match="@in_chromium"):
        start()


@in_chromium
def test_a_page_gets_the_window_asked_for_and_its_timers_run(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(PAGE, encoding="utf-8")
    # Narrower than the 500 pixels chromium --window-size gives at the least.
    dom = browser.dump_dom(page.as_uri(), (390, 844), hide_scrollbars=True)
    assert data(dom, "width") == "390"
    assert data(dom, "later") == "ran"  # within the three seconds --virtual-time-budget gave
    assert dom.startswith("<!DOCTYPE html>")


@in_chromium
def test_a_wait_rides_out_a_page_still_loading_and_raises_at_once_on_one_that_has_loaded(tmp_path):
    # While a page loads, an element it hasn't parsed yet is null: a wait takes what that throws as "not yet".
    # Once it has loaded, a wait that throws is the test's mistake, said at once rather than at the timeout.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    rest = threading.Event()

    class Slow(BaseHTTPRequestHandler):
        def do_GET(self):  # the page's start, then its end once the test lets it go
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<!DOCTYPE html><p>first</p>" + b"<!-- -->" * 512)
            self.wfile.flush()
            rest.wait(10)
            self.wfile.write(b"<p id='late'>late</p>")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    try:
        with browser.Browser(tmp_path / "chrome") as b:
            b.send("Page.navigate", url=f"http://127.0.0.1:{server.server_address[1]}/")
            assert b.wait("document.readyState === 'loading' && !!document.querySelector('p')")
            started = time.monotonic()
            with pytest.raises(browser.PageError, match="TypeError"):  # throws while it loads, to the end
                b.wait("document.getElementById('late').textContent === 'late'", 0.3)
            assert time.monotonic() - started >= 0.3
            threading.Timer(0.3, rest.set).start()
            assert b.wait("document.getElementById('late').textContent === 'late'", 5)  # a TypeError until then
            assert b.wait("document.readyState === 'complete'", 5)
            started = time.monotonic()
            with pytest.raises(browser.PageError, match="ReferenceError"):
                b.wait("nothing_is_called_this", 5)  # loaded: at once, not in five seconds
            assert time.monotonic() - started < 2
            assert b.wait("Promise.resolve(document.getElementById('late') !== null)")  # a promise, awaited
    finally:
        rest.set()
        server.shutdown()
        server.server_close()


def test_every_chromium_the_helpers_start_plays_no_sound():
    # The sound and Harmony panel tests strum chords for real (strum.js): a Chromium started without
    # --mute-audio plays them through the machine's speakers, from a dozen workers at once.
    helpers = Path(__file__).parent / "helpers"
    launches = [(f.name, line) for f in sorted(helpers.glob("*.py"))
                for line in f.read_text(encoding="utf-8").splitlines() if '"--headless=new"' in line]
    assert launches
    assert [name for name, line in launches if '"--mute-audio"' not in line] == []
