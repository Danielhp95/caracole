"""caracole.commands._common: the database, the run lock, clients and the pages, for every command."""

from __future__ import annotations

import fcntl
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.commands._common import exclusive, make_client, open_db, open_db_or_exit, write_pages
from caracole.config import load_config
from caracole.overrides import Overrides

from conftest import add_song

needs_permissions = pytest.mark.skipif(
    os.geteuid() == 0, reason="root writes into read-only folders"
)


@contextmanager
def read_only(folder: Path):
    """``folder`` made read-only (mode 555) for the block, as a mount or a wrong owner would."""
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o555)
    try:
        yield folder
    finally:
        folder.chmod(0o755)


def write_config(tmp_path: Path, **dirs: Path) -> Path:
    paths = {"library_dir": tmp_path / "lib", "state_dir": tmp_path / "state",
             "cache_dir": tmp_path / "cache", **dirs}
    toml = tmp_path / "caracole.toml"
    toml.write_text("".join(f'{k} = "{v}"\n' for k, v in paths.items()), encoding="utf-8")
    return toml


# --- folders caracole can't write: a message with the path, never a traceback --------------------


@needs_permissions
def test_a_state_folder_caracole_cant_create_names_the_database(tmp_path, capsys):
    with read_only(tmp_path / "locked") as locked:
        toml = write_config(tmp_path, state_dir=locked / "state")
        cfg = load_config(toml, env={"HOME": str(tmp_path)})
        with pytest.raises(typer.Exit) as raised:
            open_db(cfg)
    assert raised.value.exit_code == 1
    db_path = locked / "state" / "caracole.sqlite"
    assert f"can't open the database {db_path}: Permission denied ({locked / 'state'})" in (
        capsys.readouterr().err
    )


@needs_permissions
def test_a_database_caracole_cant_write_names_it(tmp_path, cfg, capsys):
    db.connect(cfg.db_path).close()
    # The database is there, but its folder can't take its journal.
    with read_only(cfg.state_dir), pytest.raises(typer.Exit) as raised:
        open_db(cfg)
    assert raised.value.exit_code == 1
    assert f"can't open the database {cfg.db_path}: " in capsys.readouterr().err


def test_open_db_is_the_one_way_to_open_the_database():
    # The older name stays for callers that still use it; `caracole add`, which carries on
    # without the database, opens it with db.connect itself.
    assert open_db_or_exit is open_db


@needs_permissions
def test_a_command_that_needs_the_database_says_so_instead_of_a_traceback(tmp_path, monkeypatch):
    import caracole.commands.autochords as cmd

    monkeypatch.setattr(cmd, "find_spec", lambda name: object())  # the model packages "import"
    with read_only(tmp_path / "locked") as locked:
        toml = write_config(tmp_path, state_dir=locked / "state")
        result = CliRunner().invoke(build_app(), ["--config", str(toml), "autochords"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, OSError)
    assert "Permission denied" in result.output and str(locked / "state") in result.output


# Every command that opens the database, as you'd type it ({tmp} is the test's folder).
DB_COMMANDS = [
    ["run"], ["sync"], ["fetch"], ["fetch", "--song", "Radiohead - Creep"], ["lyrics"],
    ["lacuerda"], ["render"], ["match"], ["match", "--dry-run"],
    ["index", "build", "--from", "{tmp}"], ["index", "refresh"], ["index", "stats"],
    ["search", "creep"], ["search", "creep", "--add", "1"], ["todo"], ["review"], ["scan"],
]


def invoke(tmp_path: Path, *args: str):
    toml = write_config(tmp_path, music_dir=tmp_path / "music")
    argv = [arg.format(tmp=tmp_path) for arg in args]
    return CliRunner().invoke(build_app(), ["--config", str(toml), *argv])


@pytest.mark.parametrize("args", DB_COMMANDS, ids=" ".join)
def test_every_command_names_a_state_folder_it_cant_use(tmp_path, args):
    # A file where the state folder should be, as a wrong mount would leave it (root too).
    state = tmp_path / "state"
    state.write_text("not a folder", encoding="utf-8")
    result = invoke(tmp_path, *args)
    assert result.exit_code == 1, result.output
    assert not isinstance(result.exception, OSError), result.exception  # a message, no traceback
    assert "can't open" in result.output and str(state) in result.output


def newer_database(path: Path) -> int:
    """A database a newer caracole migrated, as a NixOS rollback leaves it; returns its version."""
    conn = db.connect(path)
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    conn.close()
    return db.SCHEMA_VERSION + 1


def test_a_database_a_newer_caracole_migrated_exits_2(cfg, capsys):
    version = newer_database(cfg.db_path)
    with pytest.raises(typer.Exit) as raised:
        open_db(cfg)
    assert raised.value.exit_code == 2
    assert f"database: {cfg.db_path} is at schema version {version}" in capsys.readouterr().err


@pytest.mark.parametrize("args", DB_COMMANDS, ids=" ".join)
def test_every_command_exits_2_on_a_database_a_newer_caracole_migrated(tmp_path, args):
    version = newer_database(tmp_path / "state" / "caracole.sqlite")
    result = invoke(tmp_path, *args)
    assert result.exit_code == 2, result.output
    assert not isinstance(result.exception, db.DatabaseTooNew), result.exception
    assert f"is at schema version {version}, but this caracole knows up to" in result.output


def test_add_keeps_its_line_beside_a_database_a_newer_caracole_migrated(tmp_path):
    # wanted.txt is the source of truth: the line is kept, and the database waits for that caracole.
    newer_database(tmp_path / "state" / "caracole.sqlite")
    result = invoke(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert "a newer caracole migrated it" in result.output
    wanted = (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
    assert wanted.endswith("\nRadiohead - Creep\n")


@needs_permissions
def test_a_library_caracole_cant_write_names_the_page(tmp_path, cfg, conn, capsys):
    with read_only(cfg.library_dir), pytest.raises(typer.Exit) as raised:
        write_pages(conn, cfg, Overrides(), datetime(2026, 10, 19, tzinfo=UTC))
    assert raised.value.exit_code == 1
    assert f"can't write {cfg.library_dir / '_todo.md'}" in capsys.readouterr().err


def test_write_pages_writes_what_the_to_do_module_writes(cfg, conn, monkeypatch):
    # One way to write the pages: the commands' is todo.write_pages, with a message on failure.
    import caracole.todo

    calls = []
    monkeypatch.setattr(caracole.todo, "write_pages", lambda *args: calls.append(args) or ("t", "i"))
    now = datetime(2026, 10, 19, tzinfo=UTC)
    overrides = Overrides()
    assert write_pages(conn, cfg, overrides, now) == ("t", "i")
    assert calls == [(conn, cfg, overrides, now)]


def test_a_page_caracole_cant_replace_is_named(cfg, conn, capsys):
    (cfg.library_dir / "_todo.md").mkdir(parents=True)  # a folder where the page goes (root too)
    with pytest.raises(typer.Exit) as raised:
        write_pages(conn, cfg, Overrides(), datetime(2026, 10, 19, tzinfo=UTC))
    assert raised.value.exit_code == 1
    assert f"can't write {cfg.library_dir / '_todo.md'}: Is a directory" in capsys.readouterr().err


def test_write_pages_writes_the_todo_page_and_the_index(cfg, conn):
    add_song(conn, "宋冬野", "斑马斑马")
    todo, index = write_pages(conn, cfg, Overrides(), datetime(2026, 10, 19, tzinfo=UTC))
    assert (todo, index) == (cfg.library_dir / "_todo.md", cfg.library_dir / "index.html")
    assert "1 song: 0 found, 1 wanted" in todo.read_text(encoding="utf-8")
    assert "斑马斑马" in index.read_text(encoding="utf-8")


# --- one caracole at a time ------------------------------------------------------------------------


def lock_path(cfg) -> Path:
    return cfg.state_dir / "caracole.lock"


def free(cfg) -> bool:
    """Whether another process could take caracole's lock now (an open file of its own)."""
    lock_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path(cfg), os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


@contextmanager
def another_caracole(cfg, record: bytes = b"4242 run\n"):
    """Another caracole holding the lock, as the nightly run would: its own open file, flocked."""
    lock_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path(cfg), os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.ftruncate(fd, 0)
    os.write(fd, record)
    try:
        yield
    finally:
        os.close(fd)


def test_a_second_caracole_waits_for_the_first_and_says_so(cfg, capsys):
    started, done = threading.Event(), threading.Event()

    def second():
        started.set()
        with exclusive(cfg, "fetch"):
            done.set()

    with another_caracole(cfg):
        thread = threading.Thread(target=second)
        thread.start()
        assert started.wait(5)
        assert not done.wait(0.5)  # waiting, not running beside it
    assert done.wait(5)
    thread.join(5)
    said = "Another caracole is running (pid 4242: run); waiting for it to finish."
    assert said in capsys.readouterr().err


def test_the_lock_is_held_for_the_block_and_names_its_holder(cfg):
    with exclusive(cfg, "autochords"):
        assert not free(cfg)
        assert lock_path(cfg).read_text(encoding="utf-8") == f"{os.getpid()} autochords\n"
    assert free(cfg)


def test_the_lock_is_taken_again_at_no_cost_by_its_holder(cfg):
    with exclusive(cfg, "run"):
        with exclusive(cfg, "render"):
            assert not free(cfg)
        assert not free(cfg)  # still the outer block's
    assert free(cfg)


@needs_permissions
def test_a_lock_caracole_cant_create_is_a_message(tmp_path, cfg, capsys):
    with read_only(cfg.state_dir), pytest.raises(typer.Exit) as raised, exclusive(cfg, "run"):
        pass
    assert raised.value.exit_code == 1
    assert f"can't open {lock_path(cfg)}: Permission denied" in capsys.readouterr().err


def test_a_client_holds_the_lock_until_it_is_closed(cfg, conn):
    client = make_client(cfg, conn, "ug", "2026-10-19T03:30:00Z")
    assert not free(cfg)
    client.close()
    assert free(cfg)
    client.close()  # twice is harmless


def test_a_client_waits_for_another_caracole(cfg, conn):
    made = threading.Event()
    clients = []

    def make():
        own = db.connect(cfg.db_path)  # a connection serves only the thread that made it
        try:
            clients.append(make_client(cfg, own, "lrclib", "run"))
            made.set()
        finally:
            own.close()

    with another_caracole(cfg):
        thread = threading.Thread(target=make)
        thread.start()
        assert not made.wait(0.5)
    assert made.wait(5)
    thread.join(5)
    clients[0].close()


def test_a_command_holding_the_lock_makes_clients(cfg, conn):
    with exclusive(cfg, "run"):
        client = make_client(cfg, conn, "ug", "run")
        client.close()
        assert not free(cfg)
    assert free(cfg)


# --- the pause between two caracole processes' requests ----------------------------------------


def log_request(conn, provider: str, ago: float, decision: str = "ok") -> None:
    at = (datetime.now(UTC) - timedelta(seconds=ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, ?, ?, ?)",
        ("earlier", at, provider, "https://example.invalid/", 200, decision),
    )


@pytest.fixture
def pauses(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(_common, "sleep", slept.append)
    return slept


def test_a_new_client_pauses_after_another_process_s_last_request(cfg, conn, pauses):
    # UG's policy: 10-20 s between requests, whichever process sends them.
    log_request(conn, "ug", ago=3)
    make_client(cfg, conn, "ug", "run").close()
    pause = sum(pauses)  # slept in slices, each a chance to hand the lock to a lookup
    assert 10 - 4 <= pause <= 20 - 3
    assert max(pauses) <= _common.HANDOFF_SLICE


def test_a_request_logged_in_the_future_costs_one_pause_at_most(cfg, conn, pauses):
    log_request(conn, "ug", ago=-3600)  # the clock was set back since
    make_client(cfg, conn, "ug", "run").close()
    assert sum(pauses) <= 20


@pytest.mark.parametrize(
    "provider,ago,decision",
    [("ug", 25, "ok"), ("lrclib", 1, "ok"), ("ug", 1, "budget")],
    ids=["long-ago", "another-provider", "not-a-request"],
)
def test_no_pause_without_a_recent_request_to_the_provider(
    cfg, conn, pauses, provider, ago, decision
):
    log_request(conn, provider, ago=ago, decision=decision)
    make_client(cfg, conn, "ug", "run").close()
    assert pauses == []


# --- two paces: bulk work, and one song looked up now ------------------------------------------------


class Site:
    """A site answering every request with 200, recording each."""

    def __init__(self):
        self.requests: list[str] = []

    def transport(self, provider: str):
        import httpx

        def answer(request):
            self.requests.append(str(request.url))
            return httpx.Response(200, text="ok")

        return httpx.MockTransport(answer)


@pytest.fixture
def site(monkeypatch) -> Site:
    s = Site()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    return s


def log_lookup_request(conn, provider: str, ago: float) -> None:
    at = (datetime.now(UTC) - timedelta(seconds=ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, ?, ?, ?)",
        ("lookup:2026-10-19T12:00:00Z", at, provider, "https://tabs.ultimate-guitar.com/tab/1", 200, "ok"),
    )


def test_an_interactive_client_keeps_the_lookup_pace(cfg, conn, site):
    now = _common.utcnow()
    client = make_client(cfg, conn, "ug", _common.lookup_run_id(now), interactive=True)
    try:
        ug = cfg.provider("ug")
        assert client.policy.delay == ug.lookup_delay == (0.5, 1.5)
        assert client.policy.budget == ug.lookup_requests == 6
    finally:
        client.close()
    assert _common.lookup_run_id(now).startswith(_common.LOOKUP_RUN)


def test_a_lookup_sends_at_most_a_few_requests_to_a_site(cfg, conn, site, monkeypatch):
    from caracole.http import BudgetExhausted

    client = make_client(cfg, conn, "ug", _common.lookup_run_id(_common.utcnow()), interactive=True,
                         policy=None)
    client._sleep = lambda seconds: None  # the gap itself is another test's
    try:
        for n in range(6):
            client.get(f"https://tabs.ultimate-guitar.com/tab/{n}")
        with pytest.raises(BudgetExhausted):
            client.get("https://tabs.ultimate-guitar.com/tab/99")
    finally:
        client.close()
    assert len(site.requests) == 6
    runs = {r[0] for r in conn.execute("SELECT run FROM events WHERE provider = 'ug'")}
    assert all(run.startswith(_common.LOOKUP_RUN) for run in runs)  # the hourly budget counts them


def test_lookups_share_a_budget_per_site_per_hour(cfg, conn, site):
    for ago in range(58):
        log_lookup_request(conn, "ug", ago=60 + ago)
    log_lookup_request(conn, "ug", ago=3700)  # more than an hour ago
    log_lookup_request(conn, "lrclib", ago=10)  # another site
    log_request(conn, "ug", ago=4000)  # the nightly run's: bulk work has its own budget
    client = make_client(cfg, conn, "ug", _common.lookup_run_id(_common.utcnow()), interactive=True)
    try:
        assert client.policy.budget == 2  # 60 an hour, 58 spent
    finally:
        client.close()
    spent = make_client(cfg, conn, "lrclib", _common.lookup_run_id(_common.utcnow()), interactive=True)
    try:
        assert spent.policy.budget == 6
    finally:
        spent.close()


def test_a_lookups_first_request_waits_only_the_short_gap_after_the_last_one(cfg, conn, site, pauses):
    bulk = make_client(cfg, conn, "ug", "2026-10-19T03:30:00Z")
    bulk.get("https://tabs.ultimate-guitar.com/tab/1")
    bulk.close()
    client = make_client(cfg, conn, "ug", _common.lookup_run_id(_common.utcnow()), interactive=True)
    client.close()
    # UG's bulk pause is 10-20 s; a lookup's gap is 0.5-1.5 s, counted to the fraction of a second.
    assert 0.3 <= sum(pauses) <= 1.5


def test_bulk_work_after_a_lookup_keeps_the_long_pause(cfg, conn, site, pauses):
    lookup = make_client(cfg, conn, "ug", _common.lookup_run_id(_common.utcnow()), interactive=True)
    lookup._sleep = lambda seconds: None
    lookup.get("https://tabs.ultimate-guitar.com/tab/1")
    lookup.close()
    make_client(cfg, conn, "ug", "2026-10-19T03:30:00Z").close()
    assert 9.5 <= sum(pauses) <= 20


def test_a_waiting_lookup_says_whom_it_waits_for_and_is_announced(cfg, capsys):
    took = threading.Event()

    def lookup():
        with exclusive(cfg, "get Oasis - Wonderwall", interactive=True):
            took.set()

    with another_caracole(cfg):
        thread = threading.Thread(target=lookup)
        thread.start()
        assert not took.wait(0.5)
        assert _common.lookups_waiting(cfg)  # what the nightly run checks in its pauses
    assert took.wait(5)
    thread.join(5)
    assert not _common.lookups_waiting(cfg)  # it took the lock: its announcement went
    assert ("Another caracole is running (pid 4242: run); it lets a lookup go first at its next pause, "
            "or between two songs.") in capsys.readouterr().err


def test_an_announcement_a_dead_lookup_left_is_not_waited_for(cfg):
    waiting = cfg.state_dir / _common.WAITING_DIR
    waiting.mkdir(parents=True)
    (waiting / "999999999.1").write_text("get A - B\n", encoding="utf-8")  # no such process
    assert not _common.lookups_waiting(cfg)
    assert not any(waiting.iterdir())


def test_a_ticket_no_waiting_lookup_keeps_alive_is_given_up_after_one_try(cfg, conn, monkeypatch):
    # A lookup killed while it waited leaves its ticket, and its pid may be another process's by now.
    import time

    monkeypatch.setattr(_common, "TICKET_STALE", 0.4)
    waiting = cfg.state_dir / _common.WAITING_DIR
    waiting.mkdir(parents=True)
    (waiting / f"{os.getpid()}.7").write_text("get A - B\n", encoding="utf-8")  # a live pid; nothing waits
    with exclusive(cfg, "run"):
        began = time.monotonic()
        assert _common.hand_over(cfg, conn)  # once: the lock is let go, and nobody takes it
        assert time.monotonic() - began < 3  # not the whole HANDOFF_TAKE
        assert not _common.hand_over(cfg, conn)  # then it is no longer waited for
    assert not _common.lookups_waiting(cfg)


def test_a_lookup_waiting_long_keeps_its_ticket_alive(cfg, monkeypatch):
    import time

    monkeypatch.setattr(_common, "TICKET_STALE", 0.4)
    monkeypatch.setattr(_common, "TICKET_BEAT", 0.1)
    took = threading.Event()

    def lookup():
        with exclusive(cfg, "get Oasis - Wonderwall", interactive=True):
            took.set()

    with another_caracole(cfg):
        thread = threading.Thread(target=lookup)
        thread.start()
        time.sleep(1.2)  # three times TICKET_STALE
        assert not took.is_set() and _common.lookups_waiting(cfg)
    assert took.wait(5)
    thread.join(5)


def test_nothing_is_handed_over_when_no_lookup_waits_or_mid_transaction(cfg, conn):
    with exclusive(cfg, "run"):
        assert not _common.hand_over(cfg, conn)
        waiting = cfg.state_dir / _common.WAITING_DIR
        waiting.mkdir(parents=True, exist_ok=True)
        (waiting / f"{os.getpid()}.1").write_text("get A - B\n", encoding="utf-8")
        conn.execute("BEGIN")
        try:
            assert not _common.hand_over(cfg, conn)  # a lookup can't write while this transaction is open
        finally:
            conn.execute("ROLLBACK")
    assert _common.hand_over(cfg, conn) is False  # nothing held, nothing to give


HOLDER = r"""
import sys, time
from pathlib import Path
import httpx
from caracole.commands import _common
from caracole.config import load_config
from caracole import db

cfg = load_config(Path(sys.argv[1]))
out = open(sys.argv[2], "w", buffering=1)
_common.transport_for = lambda provider: httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
conn = db.connect(cfg.db_path)
with _common.exclusive(cfg, "run"):
    client = _common.make_client(cfg, conn, "ug", "2026-10-19T03:30:00Z")
    client.get("https://tabs.ultimate-guitar.com/tab/1")
    out.write(f"first {time.time()}\n")
    client.get("https://tabs.ultimate-guitar.com/tab/2")  # after a 4 s pause, handed over meanwhile
    out.write(f"second {time.time()} {client.handoffs}\n")
    client.close()
"""


def test_the_nightly_run_hands_the_lock_to_a_lookup_during_its_pause(tmp_path, cfg):
    import subprocess
    import sys
    import time

    from conftest import subprocess_pythonpath

    config = tmp_path / "caracole.toml"
    config.write_text(f'state_dir = "{cfg.state_dir}"\ncache_dir = "{cfg.cache_dir}"\n'
                      f'library_dir = "{cfg.library_dir}"\n[providers.ug]\ndelay = [4, 4]\n', encoding="utf-8")
    log = tmp_path / "holder.log"
    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(Path(__file__).parents[1] / "src")}
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(config), str(log)], env=env)
    try:
        deadline = time.time() + 20
        while "first" not in (log.read_text() if log.exists() else "") and time.time() < deadline:
            time.sleep(0.05)
        asked = time.time()
        with exclusive(cfg, "get Oasis - Wonderwall", interactive=True):
            took = time.time()
            time.sleep(0.5)
        released = time.time()
        assert holder.wait(30) == 0
    finally:
        holder.kill()
    first, second = log.read_text().splitlines()
    assert took - asked < 1.5  # not the 4 s the run had left to pause, let alone its whole run
    _, sent, handoffs = second.split()
    assert float(sent) >= released + 3.5  # the run waited a whole pause again after the lookup
    assert int(handoffs) == 1


def test_the_youtube_steps_pauses_hand_the_lock_to_a_waiting_lookup_too(cfg, conn, tmp_path, monkeypatch):
    # The nightly run's youtube step holds caracole's lock for minutes, 15 to 30 seconds between two yt-dlp
    # runs: a lookup waiting meanwhile goes first in that pause, as in a client's, and the pause starts again.
    import dataclasses

    from helpers.fake_ytdlp import FakeYtDlp

    fake = FakeYtDlp(tmp_path / "bin")
    on = dataclasses.replace(cfg, ytdlp_bin=fake.bin)
    handed, naps = [], []
    monkeypatch.setattr(_common, "hand_over", lambda c, k=None: handed.append(k is conn) or len(handed) == 1)
    monkeypatch.setattr(_common, "sleep", naps.append)
    with exclusive(on, "run"):
        runs = _common.make_youtube(on, conn, "2026-10-19T03:30:00Z")
        try:
            runs.search("Radiohead Creep")
            runs.search("Oasis Wonderwall")  # after a pause, in which the lookup went first
        finally:
            runs.close()
    assert handed and handed[0] is True  # asked, with the run's connection, during the pause
    assert sum(naps) >= on.provider("youtube").delay[0]  # then a whole pause again
    assert len(fake.calls()) == 2
