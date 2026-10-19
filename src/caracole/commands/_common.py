"""Helpers shared by command modules: config, database, the run lock, clients, pages, clock."""

from __future__ import annotations

import fcntl
import logging
import os
import random
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import httpx
import typer

from caracole import db, logs
from caracole.config import Config, ConfigError, ProviderPolicy, load_config
from caracole.health import EventLog
from caracole.http import Event, PoliteClient
from caracole.overrides import Overrides, OverridesError, load_overrides

LOCK_NAME = "caracole.lock"  # in the state directory
sleep = time.sleep  # tests replace it


def fail(message: str, code: int = 1) -> NoReturn:
    """A command's last word, an error on stderr, then exit ``code``."""
    logs.say(logging.ERROR, message)
    raise typer.Exit(code)


def warn(message: str) -> None:
    """A warning on stderr, the way the log writes one, for a command that carries on."""
    logs.say(logging.WARNING, message)


def load_cfg(ctx: typer.Context) -> Config:
    """The config, the one way a command reads it; its secrets are kept out of the log from then on."""
    path = ctx.obj.config_path if ctx.obj is not None else None
    try:
        cfg = load_config(path)
    except ConfigError as e:
        fail(f"config: {e}", 2)
    logs.add_secrets(cfg.spotify.client_secret, cfg.ntfy.token)
    return cfg


def _reason(e: OSError | sqlite3.Error) -> str:
    return (e.strerror if isinstance(e, OSError) else None) or str(e)


def open_db(cfg: Config) -> sqlite3.Connection:
    """The database, the one way a command opens it; a state folder caracole can't write exits 1,
    naming the path and why, and a database a newer caracole migrated exits 2.

    Its songs are re-keyed first when the normalizer changed since they were keyed
    (``songs.ensure_current_keys``), before anything reads them: wanted.txt's sync, for
    one, reads a line's first-seen time under its key. ``caracole add``, which keeps its
    wanted.txt line and exits 0 without the database, calls ``db.connect`` itself.
    """
    from caracole.songs import ensure_current_keys

    try:
        conn = db.connect(cfg.db_path)
    except db.DatabaseTooNew as e:  # a NixOS rollback, say: its message says what to do
        fail(f"database: {e}", 2)
    except (OSError, sqlite3.Error) as e:
        name = getattr(e, "filename", None)
        where = f" ({name})" if name and Path(name) != cfg.db_path else ""
        fail(f"can't open the database {cfg.db_path}: {_reason(e)}{where}")
    ensure_current_keys(conn)
    return conn


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


# --- one caracole at a time --------------------------------------------------------------------

_held: dict[Path, tuple[int, int]] = {}  # lock file -> (its descriptor, how many hold it here)


def _acquire(cfg: Config, what: str, *, fatal: bool = True) -> Path:
    """Take caracole's lock, waiting for another process that holds it; see ``exclusive``."""
    path = cfg.state_dir / LOCK_NAME
    if path in _held:
        fd, depth = _held[path]
        _held[path] = (fd, depth + 1)
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        if not fatal:
            raise
        fail(f"can't open {path}: {_reason(e)}")
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            warn(f"Another caracole is running ({_holder(fd)}); waiting for it to finish.")
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
def exclusive(cfg: Config, what: str, *, fatal: bool = True) -> Iterator[None]:
    """Hold caracole's lock, ``state_dir/caracole.lock``, for a command that sends requests or writes.

    Two caracole processes at once, such as the nightly run and a ``caracole-admin
    fetch`` beside it, would each spend a whole request budget, each pace its
    requests alone, and write the same files. A second one waits for the
    first, saying which it is (``what``). The lock is an flock, so it goes
    with its process, whatever ends it. The process that holds it may take it
    again at no cost, so a command and the clients it makes nest.

    A command takes it before it reads what another caracole may change, such as
    a provider's cooldown. A lock file caracole can't open exits 1, naming it;
    ``fatal=False`` raises the OSError instead, for a caller that carries on
    without the state folder (``caracole add``).
    """
    path = _acquire(cfg, what, fatal=fatal)
    try:
        yield
    finally:
        _release(path)


# --- clients ---------------------------------------------------------------------------------


def transport_for(provider: str) -> httpx.BaseTransport | None:
    """The transport for a provider's client; tests monkeypatch this to inject fakes."""
    return None


class _LockedClient(PoliteClient):
    """A PoliteClient holding caracole's lock until it is closed."""

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


def make_client(
    cfg: Config,
    conn: sqlite3.Connection,
    provider: str,
    run_id: str,
    *,
    policy: ProviderPolicy | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> PoliteClient:
    """A polite client for one provider and one run, logging every request to ``events``.

    It holds caracole's lock (``exclusive``) until it is closed, so no other
    caracole sends requests meanwhile, and its first request keeps the pause
    after the provider's last one, made by this process or another. Every
    caller closes it. ``policy`` stands in for the provider's own (``caracole
    index build`` has a budget of its own), and ``on_event`` hears every
    event too, once it is logged.
    """
    lock = _acquire(cfg, f"{provider} requests")
    try:
        policy = policy or cfg.provider(provider)
        _pause_after_last_request(conn, provider, policy.delay)
        log = EventLog(conn, run_id)

        def logged(event: Event) -> None:
            log(event)
            if on_event is not None:
                on_event(event)

        return _LockedClient(
            provider,
            policy,
            cfg.cache_dir,
            user_agent=cfg.user_agent,
            transport=transport_for(provider),
            on_event=logged,
            lock=lock,
        )
    except BaseException:
        _release(lock)
        raise


# --- the pages ---------------------------------------------------------------------------------


def write_pages(
    conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime, *,
    fatal: bool = True,
) -> tuple[Path, Path] | None:
    """Rewrite Library/_todo.md and Library/index.html (``todo.write_pages``), the way every
    command does, and return their paths.

    A library caracole can't write exits 1, naming the page; ``fatal=False`` only
    warns, and returns None, for a command whose own work is done and must
    still say so (``caracole add`` and ``caracole sync``).
    """
    from caracole import todo

    try:
        return todo.write_pages(conn, cfg, overrides, now)
    except OSError as e:
        message = f"can't write {_page_named(e, cfg.library_dir)}: {_reason(e)}"
        if fatal:
            fail(message)
        warn(message)
        return None


def _page_named(e: OSError, library_dir: Path) -> Path:
    """The page an error writing the pages is about, else the library folder.

    Each page is written through a temporary file beside it, named after it
    (``library.write_atomic``), so the error names one or the other.
    """
    from caracole.library_page import PAGE_NAME

    names = [Path(f).name for f in (e.filename, e.filename2) if f]
    return next(
        (library_dir / page for page in ("_todo.md", PAGE_NAME) for name in names if page in name),
        library_dir,
    )
