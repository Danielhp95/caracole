"""Helpers shared by command modules: config, database, the run lock, clients, pages, clock.

Two paces (``config.ProviderPolicy``). Bulk work, every command but ``caracole
get``, ``caracole lacuerda --artist`` and ``caracole lacuerda --search``, keeps
a provider's ``delay`` (10-20 s for UG) between any two requests to it,
whichever caracole sent them, and its ``budget`` a run. An interactive lookup
(``caracole get``: one song asked for just now; ``caracole lacuerda
--artist``: one LaCuerda artist's page; ``caracole lacuerda --search``: one
query of LaCuerda's search) takes
``make_client(..., interactive=True)``: ``lookup_delay`` (about a second)
between two requests, ``lookup_requests`` for the song, and ``lookup_per_hour``
for every lookup of the last hour together, counted from ``events`` (runs named
``lookup:…``).

One caracole at a time, but a lookup never waits behind a whole nightly run:
it announces itself in ``state_dir/caracole.lock.waiting/`` (``exclusive(...,
interactive=True)``), and bulk work, which spends most of its time in its
pauses, hands the lock over during a pause (``hand_over``), takes it back once
the lookup is done, and then waits a whole pause again before its next request.
Bulk work that sends no request (auto-chords, a pass of PDFs) hands it over
between two songs. The lookup touches its announcement while it waits, so one
a killed lookup left soon stops counting. Only lookups take it in a handoff:
another caracole waiting meanwhile takes it once the bulk work is done
(``_take_outside_handoffs``).
"""

from __future__ import annotations

import fcntl
import functools
import logging
import os
import random
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import typer

from caracole import db, logs
from caracole.config import Config, ConfigError, ProviderPolicy, load_config
from caracole.health import EventLog, is_cooling
from caracole.overrides import Overrides, OverridesError, load_overrides, override_key

if TYPE_CHECKING:  # the HTTP client waits for a command that makes one (``make_client``)
    import httpx

    from caracole.http import Event, PoliteClient
    from caracole.songs import Song
    from caracole.youtube import YtDlp

LOCK_NAME = "caracole.lock"  # in the state directory
WAITING_DIR = "caracole.lock.waiting"  # in the state directory: a file per lookup waiting for the lock
HANDOFF_NAME = "caracole.lock.handoff"  # in the state directory: flocked while bulk work hands the lock over
LOOKUP_RUN = "lookup:"  # how an interactive lookup's run id starts, in events
HANDOFF_SLICE = 0.25  # seconds of a bulk pause between two looks for a waiting lookup
HANDOFF_TAKE = 10.0  # seconds a lookup has to take the lock once it is handed over
WAIT_POLL = 0.05  # seconds between a waiting lookup's tries at the lock
TICKET_BEAT = 1.0  # seconds between two touches of a waiting lookup's ticket
TICKET_STALE = 5.0  # seconds untouched after which a ticket is no longer waited for
TICKET_FORGOTTEN = 3600.0  # seconds untouched after which a ticket is deleted
sleep = time.sleep  # tests replace it
_handoff_sleep = time.sleep  # the short waits of a handoff, which tests don't skip


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


def load_ovr(cfg: Config) -> Overrides:
    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError as e:
        fail(f"overrides: {e}", 2)


def song_named(conn: sqlite3.Connection, display: str, overrides: Overrides) -> Song:
    """The song a command's ``--song`` names (fetch, render, youtube), one not ignored; otherwise
    say why there is none: a name that isn't "Artist - Title" exits 2, a song not in the library
    or ignored 1. Each command adds its own checks."""
    from caracole.songs import find_song

    try:
        key = override_key(display)
    except OverridesError as e:
        fail(str(e), 2)
    song = find_song(conn, key)
    if song is None:
        fail(f'No song "{display}" in the library. Add it with `caracole add` first.')
    if song.status == "ignored" or key in overrides.ignore:
        fail(f'"{song.display}" is ignored in overrides.toml.')
    return song


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def run_id_for(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def lookup_run_id(now: datetime) -> str:
    """An interactive lookup's run id: ``lookup:`` and the time, so its requests count in the hourly budget."""
    return LOOKUP_RUN + run_id_for(now)


# --- one caracole at a time --------------------------------------------------------------------

_held: dict[Path, tuple[int, int]] = {}  # lock file -> (its descriptor, how many hold it here)
_handoffs = 0  # how many times this process handed the lock to a waiting lookup and took it back


def _acquire(cfg: Config, what: str, *, fatal: bool = True, interactive: bool = False,
             on_wait: Callable[[str], None] | None = None) -> Path:
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
        if interactive:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                holder = _holder(fd)
                if on_wait is not None:
                    on_wait(holder)
                warn(f"Another caracole is running ({holder}); it lets a lookup go first at its next pause, "
                     "or between two songs.")
                _wait_announced(cfg, what, fd)
        else:
            _take_outside_handoffs(cfg, fd, fatal=fatal, on_wait=on_wait)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()} {what}\n".encode(), 0)
    except BaseException:
        os.close(fd)
        raise
    _held[path] = (fd, 1)
    return path


def _take_outside_handoffs(cfg: Config, fd: int, *, fatal: bool,
                           on_wait: Callable[[str], None] | None) -> None:
    """Take caracole's lock (``fd``) as a caracole that isn't a lookup: once the one that holds it is done,
    and never while bulk work has let go of it for a lookup (``hand_over``, which holds the flock of
    ``HANDOFF_NAME`` meanwhile). A lock taken then is let go at once, and taken again once the handoff is
    over: a `caracole-admin` command waiting for the nightly run takes it after the whole run, never in the
    middle of one of its steps, and never ahead of the lookup."""
    path = cfg.state_dir / HANDOFF_NAME
    try:
        gate = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        if not fatal:
            raise
        fail(f"can't open {path}: {_reason(e)}")
    said = False

    def say() -> bool:
        holder = _holder(fd)
        if on_wait is not None:
            on_wait(holder)
        warn(f"Another caracole is running ({holder}); waiting for it to finish.")
        return True

    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                said = said or say()
                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                fcntl.flock(gate, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:  # let go for a lookup: the lookup's now, then the bulk work's again
                fcntl.flock(fd, fcntl.LOCK_UN)
                said = said or say()
                fcntl.flock(gate, fcntl.LOCK_SH)  # until the bulk work holds it again
                fcntl.flock(gate, fcntl.LOCK_UN)
                continue
            fcntl.flock(gate, fcntl.LOCK_UN)
            return
    finally:
        os.close(gate)


def _announce(cfg: Config, what: str) -> Path:
    """Say that a lookup waits for the lock: a file named after this process, which goes once it has it."""
    folder = cfg.state_dir / WAITING_DIR
    folder.mkdir(mode=0o700, exist_ok=True)
    for n in range(1000):
        ticket = folder / f"{os.getpid()}.{n}"
        try:
            fd = os.open(ticket, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with open(fd, "w", encoding="utf-8") as f:
            f.write(f"{what}\n")
        return ticket
    raise OSError(f"too many lookups of this process wait in {folder}")


def _wait_announced(cfg: Config, what: str, fd: int) -> None:
    """Wait for caracole's lock as a lookup: announced by a ticket, touched every ``TICKET_BEAT`` seconds
    while this process tries for the lock, so that a ticket left by a lookup that was killed while it
    waited (its pid maybe another process's since) soon stops counting (``lookups_waiting``)."""
    ticket = _announce(cfg, what)
    beat = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                pass
            _handoff_sleep(WAIT_POLL)
            if time.monotonic() - beat >= TICKET_BEAT:
                beat = time.monotonic()
                try:
                    os.utime(ticket)
                except FileNotFoundError:  # deleted from under it: announce it again
                    ticket = _announce(cfg, what)
    finally:
        ticket.unlink(missing_ok=True)


def lookups_waiting(cfg: Config) -> bool:
    """Whether a lookup waits for caracole's lock: a ticket of a live process, touched in the last
    ``TICKET_STALE`` seconds. A ticket a process that ended left is dropped, and so is one untouched
    for ``TICKET_FORGOTTEN``."""
    folder = cfg.state_dir / WAITING_DIR
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    waiting = False
    now = time.time()
    for name in names:
        ticket = folder / name
        try:
            os.kill(int(name.split(".")[0]), 0)
        except ProcessLookupError:
            ticket.unlink(missing_ok=True)
            continue
        except (ValueError, PermissionError):
            pass  # not caracole's name, or a process of another user: its age tells
        try:
            age = now - ticket.stat().st_mtime
        except OSError:
            continue
        if age > TICKET_STALE:  # nothing waits on it any more: a lookup killed while it waited
            if age > TICKET_FORGOTTEN:
                ticket.unlink(missing_ok=True)
            continue
        waiting = True
    return waiting


def handoffs() -> int:
    """How many times this process handed caracole's lock to a waiting lookup (``hand_over``)."""
    return _handoffs


def overrides_since(cfg: Config, overrides: Overrides, handed: int) -> Overrides:
    """``overrides``, read when this process had handed caracole's lock over ``handed`` times (``handoffs()``
    then), as bulk work holds them now: overrides.toml read again when it has handed the lock to a lookup since,
    as the lookup may have pinned a tab or picked a LaCuerda sheet that what the work does next keeps to. The
    copy read before stays when the file can't be read now."""
    if handoffs() == handed:
        return overrides
    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError as e:
        logging.getLogger(__name__).info("overrides.toml couldn't be read again (%s); going on with what was "
                                         "read before.", e)
        return overrides


def hand_over(cfg: Config, conn: sqlite3.Connection | None = None) -> bool:
    """Let a waiting lookup have caracole's lock now, and take it back once it is done; True when it did.

    Only bulk work calls it, during a pause between two requests, when it holds
    the lock and ``conn`` is in no transaction (the lookup must be able to write).
    The lock is let go, each waiting lookup takes it in turn (each has
    ``HANDOFF_TAKE`` seconds to), and this process waits until it is free again.
    Its record (which caracole holds it) is written back. Meanwhile it holds the
    flock of ``HANDOFF_NAME``, so that a caracole waiting for the lock that isn't a
    lookup (a `caracole-admin` command) leaves it to the lookups and this process
    (``_take_outside_handoffs``); without that file, nothing is handed over.
    """
    global _handoffs
    path = cfg.state_dir / LOCK_NAME
    held = _held.get(path)
    if held is None or (conn is not None and conn.in_transaction) or not lookups_waiting(cfg):
        return False
    fd, _ = held
    try:
        gate = os.open(cfg.state_dir / HANDOFF_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        logging.getLogger(__name__).info("No lookup goes first: %s can't be opened: %s.", HANDOFF_NAME, _reason(e))
        return False
    try:
        fcntl.flock(gate, fcntl.LOCK_EX)
        record = os.pread(fd, 256, 0)
        fcntl.flock(fd, fcntl.LOCK_UN)
        try:
            for _ in range(int(HANDOFF_TAKE / 0.05)):
                if not lookups_waiting(cfg):
                    break
                _handoff_sleep(0.05)
        finally:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.ftruncate(fd, 0)
            os.pwrite(fd, record, 0)
    finally:
        os.close(gate)  # and with it its flock
    _handoffs += 1
    logging.getLogger(__name__).info("Handed caracole's lock to a lookup, and took it back.")
    return True


def _patient_sleep(cfg: Config, conn: sqlite3.Connection | None, seconds: float,
                   again: Callable[[], float], nap: Callable[[float], None]) -> None:
    """Sleep ``seconds`` holding caracole's lock, in slices, handing it to a lookup that waits meanwhile;
    after a handoff, the pause starts again, ``again()`` seconds long."""
    left = seconds
    while left > 0:
        if hand_over(cfg, conn):
            left = again()
            continue
        chunk = min(left, HANDOFF_SLICE)
        nap(chunk)
        left -= chunk


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
def exclusive(cfg: Config, what: str, *, fatal: bool = True, interactive: bool = False,
              on_wait: Callable[[str], None] | None = None) -> Iterator[None]:
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

    ``interactive``: a lookup, which announces that it waits, so that bulk work
    hands the lock over at its next pause, or between two songs (``hand_over``). ``on_wait`` hears
    whom it waits for, when it must.
    """
    path = _acquire(cfg, what, fatal=fatal, interactive=interactive, on_wait=on_wait)
    try:
        yield
    finally:
        _release(path)


# --- clients ---------------------------------------------------------------------------------


def transport_for(provider: str) -> httpx.BaseTransport | None:
    """The transport for a provider's client; tests monkeypatch this to inject fakes."""
    return None


def alert_block(cfg: Config, provider: str, message: str) -> None:
    """The ntfy alert a block sends, titled as the nightly run titles one ("caracole: Ultimate Guitar
    blocked", ``logs.provider_name``) with the command's own message: once for the block, never per
    song, high priority; nothing without an ntfy URL. Sending never raises (notify.py)."""
    if not cfg.ntfy.url:
        return
    from caracole.notify import Notifier  # httpx: only when there is an alert to send

    notifier = Notifier(cfg.ntfy.url, cfg.ntfy.token, transport=transport_for("ntfy"))
    notifier.send(f"caracole: {logs.provider_name(provider)} blocked", message, priority="high", tags=["warning"])


@functools.cache
def _locked_client() -> type[PoliteClient]:
    """The class of ``make_client``'s clients, made the first time a command makes one: a
    command that sends no request never imports PoliteClient, and with it httpx."""
    from caracole.http import PoliteClient, ProviderBlocked

    class _LockedClient(PoliteClient):
        """A PoliteClient holding caracole's lock until it is closed.

        Bulk work's (``yields``) spends each pause handing the lock to a lookup that
        waits (``hand_over``); after one, its pause starts again, whole. Once a lookup
        has had the lock, in this client's pause or another's of the process, it sends
        nothing more to a site that blocked the lookup, and waits the whole pause after
        the lookup's last request to its site, not only after its own (``_after_a_lookup``).
        """

        def __init__(self, *args, lock: Path, cfg: Config | None = None,
                     conn: sqlite3.Connection | None = None, yields: bool = False, **kwargs):
            super().__init__(*args, **kwargs)
            self._lock: Path | None = lock
            self._cfg = cfg
            self._conn = conn
            self._yields = yields and cfg is not None
            self._seen = _handoffs  # the handoffs this client has looked at

        @property
        def handoffs(self) -> int:
            """How many times this process has handed caracole's lock to a lookup (``_common.handoffs``)."""
            return _handoffs

        def _wait(self, seconds: float) -> None:
            if not self._yields:
                super()._wait(seconds)
                return
            assert self._cfg is not None

            def again() -> float:
                self._last_request = self._clock()
                return self._rng.uniform(*self.policy.delay)

            _patient_sleep(self._cfg, self._conn, seconds, again, self._sleep)

        def _pause(self, url: str) -> None:
            self._after_a_lookup(url)  # one had the lock since this client last looked
            super()._pause(url)
            self._after_a_lookup(url)  # one went first in this very pause, which began again after it

        def _after_a_lookup(self, url: str) -> None:
            """What a lookup this process let go first left, once there was one since the client last looked,
            before its next request: a block the lookup met (health.py, as the lookup recorded it) is this
            client's too, and nothing is sent; else the pause runs from the last request any caracole sent
            the site (kv ``http:last_request:``), the lookup's included, when that is later than its own."""
            if not self._yields or self._conn is None or self._seen == _handoffs:
                return
            self._seen = _handoffs
            if is_cooling(self._conn, self.provider, self._wall_clock()):
                self._blocked = ProviderBlocked(self.provider, url, None, "met by a lookup caracole let go first")
                raise self._blocked
            last = _last_request(self._conn, self.provider)
            if last is not None:
                at = self._clock() - max(0.0, time.time() - last)
                if self._last_request is None or at > self._last_request:
                    self._last_request = at

        def close(self) -> None:
            try:
                super().close()
            finally:
                if self._lock is not None:
                    _release(self._lock)
                    self._lock = None

    return _LockedClient


_SENT = ("ok", "not_modified", "blocked", "error")  # events that were requests
_LAST_SENT = "http:last_request:"  # + provider: when any caracole last sent it a request, in seconds


def _last_request(conn: sqlite3.Connection, provider: str) -> float | None:
    """When any caracole last sent the provider a request, as a ``time.time()``: kv ``http:last_request:``,
    to the fraction of a second, else the last request in ``events`` (to the second)."""
    value = db.kv_get(conn, _LAST_SENT + provider)
    if value is not None:
        try:
            return float(value)
        except ValueError:
            pass
    sent = ",".join("?" * len(_SENT))
    row = conn.execute(
        f"SELECT max(at) FROM events WHERE provider = ? AND decision IN ({sent})",
        (provider, *_SENT),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _pause_after_last_request(
    conn: sqlite3.Connection, provider: str, delay: tuple[float, float], *, cfg: Config | None = None,
) -> None:
    """Wait out the pause after the provider's last request, whichever process sent it.

    A client paces only its own requests, so a command started right after
    another (or after the nightly run) would send its first one at once. With
    ``cfg``, bulk work's, the wait hands the lock to a lookup that waits
    meanwhile (``hand_over``).
    """
    last = _last_request(conn, provider)
    if last is None:
        return
    remaining = random.uniform(*delay) - (time.time() - last)
    if remaining <= 0:
        return
    remaining = min(remaining, delay[1])  # never longer than one pause, the clock set back or not
    if cfg is None:
        sleep(remaining)
    else:
        _patient_sleep(cfg, conn, remaining, lambda: random.uniform(*delay), lambda s: sleep(s))


def lookup_requests_used(conn: sqlite3.Connection, provider: str, now: datetime | None = None, *,
                         run: str = LOOKUP_RUN) -> int:
    """How many requests every lookup of the last hour sent the provider, this one's so far included; with
    ``run``, those of the lookups whose run is named so (``lookup:lacuerda-search:``, LaCuerda's searches)."""
    since = ((now or datetime.now(UTC)) - timedelta(hours=1)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    sent = ",".join("?" * len(_SENT))
    return conn.execute(
        f"SELECT COUNT(*) FROM events WHERE provider = ? AND run LIKE ? AND at >= ? AND decision IN ({sent})",
        (provider, run + "%", since, *_SENT),
    ).fetchone()[0]


def lookup_policy(cfg: Config, conn: sqlite3.Connection, provider: str, now: datetime | None = None) -> ProviderPolicy:
    """The provider's interactive pace: its ``lookup_delay``, and a budget of ``lookup_requests``, or what
    the last hour's lookups left of ``lookup_per_hour`` when that is less."""
    p = cfg.provider(provider)
    used = lookup_requests_used(conn, provider, now)
    return replace(p, budget=max(0, min(p.lookup_requests, p.lookup_per_hour - used)), delay=p.lookup_delay)


def make_client(
    cfg: Config,
    conn: sqlite3.Connection,
    provider: str,
    run_id: str,
    *,
    policy: ProviderPolicy | None = None,
    on_event: Callable[[Event], None] | None = None,
    interactive: bool = False,
) -> PoliteClient:
    """A polite client for one provider and one run, logging every request to ``events``.

    It holds caracole's lock (``exclusive``) until it is closed, so no other
    caracole sends requests meanwhile, and its first request keeps the pause
    after the provider's last one, made by this process or another. Every
    caller closes it. ``policy`` stands in for the provider's own (``caracole
    index build`` has a budget of its own), and ``on_event`` hears every
    event too, once it is logged.

    Bulk work's client keeps the provider's ``delay`` and ``budget``, and hands
    the lock to a waiting lookup in its pauses. ``interactive``, a lookup's
    (``caracole get``), keeps ``lookup_policy``: a gap of about a second, and a
    few requests; its run id starts with ``lookup:`` so the hourly budget counts
    them, and it never hands the lock over.
    """
    if interactive and not run_id.startswith(LOOKUP_RUN):
        run_id = LOOKUP_RUN + run_id
    lock = _acquire(cfg, f"{provider} requests", interactive=interactive)
    try:
        policy = policy or (lookup_policy(cfg, conn, provider) if interactive else cfg.provider(provider))
        _pause_after_last_request(conn, provider, policy.delay, cfg=None if interactive else cfg)
        log = EventLog(conn, run_id)

        def logged(event: Event) -> None:
            log(event)
            if event.decision in _SENT:
                db.kv_set(conn, _LAST_SENT + provider, f"{time.time():.3f}")
            if on_event is not None:
                on_event(event)

        return _locked_client()(
            provider,
            policy,
            cfg.cache_dir,
            user_agent=cfg.user_agent,
            transport=transport_for(provider),
            sleep=lambda seconds: sleep(seconds),  # this module's, which tests replace
            on_event=logged,
            lock=lock,
            cfg=cfg,
            conn=conn,
            yields=not interactive,
        )
    except BaseException:
        _release(lock)
        raise


def make_youtube(
    cfg: Config,
    conn: sqlite3.Connection,
    run_id: str,
    *,
    on_event: Callable[[Event], None] | None = None,
) -> YtDlp:
    """yt-dlp for one run (youtube.py), as ``make_client`` makes a provider's client: it holds
    caracole's lock until it is closed, its first run keeps the pause after the last one any
    caracole made, and every run is logged to ``events``. Every caller closes it.

    It is bulk work: each pause, its first included, hands the lock to a lookup that waits
    meanwhile (``hand_over``), then starts again, whole."""
    from caracole.youtube import PROVIDER, YtDlp

    lock = _acquire(cfg, "youtube downloads")
    try:
        policy = cfg.provider(PROVIDER)
        _pause_after_last_request(conn, PROVIDER, policy.delay, cfg=cfg)
        log = EventLog(conn, run_id)

        def logged(event: Event) -> None:
            log(event)
            if on_event is not None:
                on_event(event)

        def pause(seconds: float) -> None:
            _patient_sleep(cfg, conn, seconds, lambda: random.uniform(*policy.delay), lambda s: sleep(s))

        return YtDlp(cfg.ytdlp_bin, policy, cfg.cache_dir, on_event=logged, sleep=pause,
                     on_close=lambda: _release(lock))
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
