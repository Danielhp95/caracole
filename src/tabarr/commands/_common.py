"""Helpers shared by command modules: config, database, the run lock, clients, pages, clock."""

from __future__ import annotations

import fcntl
import os
import random
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import httpx
import typer

from tabarr import db
from tabarr.config import Config, ConfigError, load_config
from tabarr.health import EventLog
from tabarr.http import PoliteClient
from tabarr.overrides import Overrides, OverridesError, load_overrides

LOCK_NAME = "tabarr.lock"  # in the state directory
sleep = time.sleep  # tests replace it


def fail(message: str, code: int = 1) -> NoReturn:
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(code)


def load_cfg(ctx: typer.Context) -> Config:
    path = ctx.obj.config_path if ctx.obj is not None else None
    try:
        return load_config(path)
    except ConfigError as e:
        fail(f"config: {e}", 2)


def _reason(e: OSError | sqlite3.Error) -> str:
    return (e.strerror if isinstance(e, OSError) else None) or str(e)


def open_db(cfg: Config) -> sqlite3.Connection:
    """The database, the one way a command opens it; a state folder tabarr can't write exits 1,
    naming the path and why, and a database a newer tabarr migrated exits 2.

    ``tabarr add``, which keeps its wanted.txt line and exits 0 without the database,
    calls ``db.connect`` itself.
    """
    try:
        return db.connect(cfg.db_path)
    except db.DatabaseTooNew as e:  # a NixOS rollback, say: its message says what to do
        fail(f"database: {e}", 2)
    except (OSError, sqlite3.Error) as e:
        name = getattr(e, "filename", None)
        where = f" ({name})" if name and Path(name) != cfg.db_path else ""
        fail(f"can't open the database {cfg.db_path}: {_reason(e)}{where}")


open_db_or_exit = open_db  # its older name


def load_ovr(cfg: Config) -> Overrides:
    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError as e:
        fail(f"overrides: {e}", 2)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def run_id_for(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- one tabarr at a time --------------------------------------------------------------------

_held: dict[Path, tuple[int, int]] = {}  # lock file -> (its descriptor, how many hold it here)


def _acquire(cfg: Config, what: str) -> Path:
    """Take tabarr's lock, waiting for another process that holds it; see ``exclusive``."""
    path = cfg.state_dir / LOCK_NAME
    if path in _held:
        fd, depth = _held[path]
        _held[path] = (fd, depth + 1)
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        fail(f"can't open {path}: {_reason(e)}")
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            typer.secho(f"Another tabarr is running ({_holder(fd)}); waiting for it to finish.",
                        err=True, fg=typer.colors.YELLOW)
            fcntl.flock(fd, fcntl.LOCK_EX)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()} {what}\n".encode(), 0)
    except BaseException:
        os.close(fd)
        raise
    _held[path] = (fd, 1)
    return path


def _release(path: Path) -> None:
    fd, depth = _held[path]
    if depth > 1:
        _held[path] = (fd, depth - 1)
        return
    del _held[path]
    os.close(fd)  # and with it the lock


def _holder(fd: int) -> str:
    """Who holds the lock, as its holder wrote it: "pid 4242: run"."""
    try:
        pid, _, what = os.pread(fd, 256, 0).decode("utf-8", "replace").strip().partition(" ")
    except OSError:
        return "pid unknown"
    return f"pid {pid}: {what}" if pid else "pid unknown"


@contextmanager
def exclusive(cfg: Config, what: str) -> Iterator[None]:
    """Hold tabarr's lock, ``state_dir/tabarr.lock``, for a command that sends requests or writes.

    Two tabarr processes at once, such as the nightly run and a ``tabarr-admin
    fetch`` beside it, would each spend a whole request budget, each pace its
    requests alone, and write the same files. A second one waits for the
    first, saying which it is (``what``). The lock is an flock, so it goes
    with its process, whatever ends it. The process that holds it may take it
    again at no cost, so a command and the clients it makes nest.
    """
    path = _acquire(cfg, what)
    try:
        yield
    finally:
        _release(path)


# --- clients ---------------------------------------------------------------------------------


def transport_for(provider: str) -> httpx.BaseTransport | None:
    """The transport for a provider's client; tests monkeypatch this to inject fakes."""
    return None


class _LockedClient(PoliteClient):
    """A PoliteClient holding tabarr's lock until it is closed."""

    def __init__(self, *args, lock: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock: Path | None = lock

    def close(self) -> None:
        try:
            super().close()
        finally:
            if self._lock is not None:
                _release(self._lock)
                self._lock = None


_SENT = ("ok", "not_modified", "blocked", "error")  # events that were requests


def _pause_after_last_request(
    conn: sqlite3.Connection, provider: str, delay: tuple[float, float]
) -> None:
    """Wait out the pause after the provider's last logged request, whichever process sent it.

    A client paces only its own requests, so a command started right after
    another (or after the nightly run) would send its first one at once.
    """
    sent = ",".join("?" * len(_SENT))
    row = conn.execute(
        f"SELECT max(at) FROM events WHERE provider = ? AND decision IN ({sent})",
        (provider, *_SENT),
    ).fetchone()
    if row is None or row[0] is None:
        return
    try:
        last = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return
    remaining = random.uniform(*delay) - (datetime.now(UTC) - last).total_seconds()
    if remaining > 0:
        sleep(min(remaining, delay[1]))  # never longer than one pause, the clock set back or not


def make_client(cfg: Config, conn: sqlite3.Connection, provider: str, run_id: str) -> PoliteClient:
    """A polite client for one provider and one run, logging every request to ``events``.

    It holds tabarr's lock (``exclusive``) until it is closed, so no other
    tabarr sends requests meanwhile, and its first request keeps the pause
    after the provider's last one, made by this process or another.
    """
    lock = _acquire(cfg, f"{provider} requests")
    try:
        policy = cfg.provider(provider)
        _pause_after_last_request(conn, provider, policy.delay)
        return _LockedClient(
            provider,
            policy,
            cfg.cache_dir,
            user_agent=cfg.user_agent,
            transport=transport_for(provider),
            on_event=EventLog(conn, run_id),
            lock=lock,
        )
    except BaseException:
        _release(lock)
        raise


# --- the pages ---------------------------------------------------------------------------------


def write_pages(
    conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime
) -> tuple[Path, Path]:
    """Rewrite Library/_todo.md and Library/index.html; a library tabarr can't write exits 1."""
    from tabarr.library_page import PAGE_NAME, build_library_page, write_library_page
    from tabarr.todo import build_todo, write_todo

    todo_text = build_todo(conn, cfg, overrides, now)
    page_html = build_library_page(conn, cfg, overrides, now)
    written = []
    for name, write in (
        ("_todo.md", lambda: write_todo(cfg.library_dir, todo_text)),
        (PAGE_NAME, lambda: write_library_page(cfg.library_dir, page_html)),
    ):
        try:
            written.append(write())
        except OSError as e:
            fail(f"can't write {cfg.library_dir / name}: {_reason(e)}")
    todo, page = written
    return todo, page
