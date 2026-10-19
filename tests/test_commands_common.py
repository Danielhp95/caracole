"""tabarr.commands._common: the database, the run lock, clients and the pages, for every command."""

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

from tabarr import db
from tabarr.cli import build_app
from tabarr.commands import _common
from tabarr.commands._common import exclusive, make_client, open_db, open_db_or_exit, write_pages
from tabarr.config import load_config
from tabarr.overrides import Overrides

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
    toml = tmp_path / "tabarr.toml"
    toml.write_text("".join(f'{k} = "{v}"\n' for k, v in paths.items()), encoding="utf-8")
    return toml


# --- folders tabarr can't write: a message with the path, never a traceback --------------------


@needs_permissions
def test_a_state_folder_tabarr_cant_create_names_the_database(tmp_path, capsys):
    with read_only(tmp_path / "locked") as locked:
        toml = write_config(tmp_path, state_dir=locked / "state")
        cfg = load_config(toml, env={"HOME": str(tmp_path)})
        with pytest.raises(typer.Exit) as raised:
            open_db_or_exit(cfg)
    assert raised.value.exit_code == 1
    db_path = locked / "state" / "tabarr.sqlite"
    assert f"can't open the database {db_path}: Permission denied ({locked / 'state'})" in (
        capsys.readouterr().err
    )


@needs_permissions
def test_a_database_tabarr_cant_write_names_it(tmp_path, cfg, capsys):
    open_db(cfg).close()
    # The database is there, but its folder can't take its journal.
    with read_only(cfg.state_dir), pytest.raises(typer.Exit) as raised:
        open_db_or_exit(cfg)
    assert raised.value.exit_code == 1
    assert f"can't open the database {cfg.db_path}: " in capsys.readouterr().err


@needs_permissions
def test_open_db_still_raises_for_a_caller_that_carries_on(tmp_path, cfg):
    # `tabarr add` keeps the line in wanted.txt and exits 0 when only the database fails.
    with read_only(cfg.state_dir.parent), pytest.raises(OSError):
        open_db(cfg)


@needs_permissions
def test_a_command_that_needs_the_database_says_so_instead_of_a_traceback(tmp_path, monkeypatch):
    import tabarr.commands.autochords as cmd

    monkeypatch.setattr(cmd, "find_spec", lambda name: object())  # the model packages "import"
    with read_only(tmp_path / "locked") as locked:
        toml = write_config(tmp_path, state_dir=locked / "state")
        result = CliRunner().invoke(build_app(), ["--config", str(toml), "autochords"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, OSError)
    assert "Permission denied" in result.output and str(locked / "state") in result.output


@needs_permissions
def test_a_library_tabarr_cant_write_names_the_page(tmp_path, cfg, conn, capsys):
    with read_only(cfg.library_dir), pytest.raises(typer.Exit) as raised:
        write_pages(conn, cfg, Overrides(), datetime(2026, 10, 19, tzinfo=UTC))
    assert raised.value.exit_code == 1
    assert f"can't write {cfg.library_dir / '_todo.md'}" in capsys.readouterr().err


def test_write_pages_writes_the_todo_page_and_the_index(cfg, conn):
    add_song(conn, "宋冬野", "斑马斑马")
    todo, index = write_pages(conn, cfg, Overrides(), datetime(2026, 10, 19, tzinfo=UTC))
    assert (todo, index) == (cfg.library_dir / "_todo.md", cfg.library_dir / "index.html")
    assert "1 song: 0 found, 1 wanted" in todo.read_text(encoding="utf-8")
    assert "斑马斑马" in index.read_text(encoding="utf-8")


# --- one tabarr at a time ------------------------------------------------------------------------


def lock_path(cfg) -> Path:
    return cfg.state_dir / "tabarr.lock"


def free(cfg) -> bool:
    """Whether another process could take tabarr's lock now (an open file of its own)."""
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
def another_tabarr(cfg, record: bytes = b"4242 run\n"):
    """Another tabarr holding the lock, as the nightly run would: its own open file, flocked."""
    lock_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path(cfg), os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.ftruncate(fd, 0)
    os.write(fd, record)
    try:
        yield
    finally:
        os.close(fd)


def test_a_second_tabarr_waits_for_the_first_and_says_so(cfg, capsys):
    started, done = threading.Event(), threading.Event()

    def second():
        started.set()
        with exclusive(cfg, "fetch"):
            done.set()

    with another_tabarr(cfg):
        thread = threading.Thread(target=second)
        thread.start()
        assert started.wait(5)
        assert not done.wait(0.5)  # waiting, not running beside it
    assert done.wait(5)
    thread.join(5)
    said = "Another tabarr is running (pid 4242: run); waiting for it to finish."
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
def test_a_lock_tabarr_cant_create_is_a_message(tmp_path, cfg, capsys):
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


def test_a_client_waits_for_another_tabarr(cfg, conn):
    made = threading.Event()
    clients = []

    def make():
        own = db.connect(cfg.db_path)  # a connection serves only the thread that made it
        try:
            clients.append(make_client(cfg, own, "lrclib", "run"))
            made.set()
        finally:
            own.close()

    with another_tabarr(cfg):
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


# --- the pause between two tabarr processes' requests ----------------------------------------


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
    [pause] = pauses
    assert 10 - 4 <= pause <= 20 - 3


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
