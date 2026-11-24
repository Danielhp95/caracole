"""Helpers shared by command modules: config, database, the run lock, clients, pages, clock.

Two paces (``config.ProviderPolicy``). Bulk work, every command but ``caracole
get``, ``caracole versions``, ``caracole ug --link``, ``caracole lacuerda
--artist`` and ``--search`` and ``caracole harptabs --artist``, keeps a
provider's ``delay`` (2.5-5 s for UG) between any two requests to it,
whichever caracole sent them, and its ``budget`` a run. An interactive lookup
(``caracole get``: one song asked for just now; ``caracole ug --link``: a UG
page pasted; ``caracole lacuerda --artist``: one LaCuerda artist's page;
``caracole lacuerda --search``: one query of LaCuerda's search; ``caracole
harptabs --artist``: one harptabs.com artist's page; ``caracole versions
--keep`` and ``--keep-more``: a song's versions kept now) takes
``make_client(..., interactive=True)``: ``lookup_delay``
(0.125-0.375 s) between two requests, ``lookup_requests`` for the song, and
``lookup_per_hour`` for every lookup of the last hour together, counted from
``events`` (runs named ``lookup:…``).

One caracole at a time, but a lookup never waits behind a whole nightly run:
it announces itself in ``state_dir/caracole.lock.waiting/`` (``exclusive(...,
interactive=True)``), and bulk work, which spends most of its time in its
pauses, hands the lock over during a pause (``hand_over``), takes it back once
the lane is empty and no lookup waits, and then waits a whole pause again before
its next request. Bulk work that sends no request (auto-chords, a pass of PDFs)
hands it over between two songs. The lookup touches its announcement while it
waits, so one a killed lookup left soon stops counting. Only lookups take it in a
handoff: another caracole waiting meanwhile takes it once the bulk work is done
(``_take_outside_handoffs``). What the owner asked for just now (one song's add,
removal, review, fetch or PDF, YouTube's search, what caracole serve queues) waits as
a lookup does, so that a lookup queued behind it never waits behind the whole run;
holding the lock, it hands it to the lane's lookups alone, at its own hand-over
points (a yt-dlp pause, a YouTube sheet before its models, ``fetch --song``'s
pauses), and takes it back once the lane is empty.

The interactive lookups (``get``, ``ug --link``, ``lacuerda --artist`` and
``--search``, ``harptabs --artist``) take the lock in a lane of their own
(``exclusive(..., lane=True)``, a shared flock of ``caracole.lock.lane``): while
one is there, no other caracole takes the lock. They take turns at it
(``pass_turn``): before each request but a client's first, and between two
stages (``get``'s, and ``ug --link``'s tab page and its artist's lists), one lets
the next in the lane have it, and takes it back in turn. Each one's good run is
what its own client was answered (``PoliteClient.answered_any``).
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

    from caracole.commands.get import _Lines
    from caracole.http import Event, PoliteClient
    from caracole.progress import Ticker
    from caracole.songs import Song
    from caracole.staged import StagedResult
    from caracole.youtube import YtDlp

LOCK_NAME = "caracole.lock"  # in the state directory
WAITING_DIR = "caracole.lock.waiting"  # in the state directory: a file per lookup waiting for the lock
HANDOFF_NAME = "caracole.lock.handoff"  # in the state directory: flocked while bulk work hands the lock over
LANE_NAME = "caracole.lock.lane"  # in the state directory: flocked shared by each lookup in the lane
LANE_TICKET = "lane."  # how a lane ticket's name starts: lane.<time.time_ns(), 20 digits>.<pid>[.<n>]
LOOKUP_RUN = "lookup:"  # how an interactive lookup's run id starts, in events
HANDOFF_SLICE = 0.25  # seconds of a bulk pause between two looks for a waiting lookup
HANDOFF_TAKE = 10.0  # seconds a lookup has to take the lock once it is handed over
WAIT_POLL = 0.05  # seconds between a waiting lookup's tries at the lock
TICKET_BEAT = 1.0  # seconds between two touches of a waiting lookup's ticket
TICKET_STALE = 5.0  # seconds untouched after which a ticket is no longer waited for
TICKET_FORGOTTEN = 3600.0  # seconds untouched after which a ticket is deleted
WAIT_SAID = 1.0  # seconds a lookup waits for the lock before ``on_wait`` hears whom it waits for
sleep = time.sleep  # tests replace it
_handoff_sleep = time.sleep  # the short waits of a handoff, which tests don't skip


def fail(message: str, code: int = 1) -> NoReturn:
    """A command's last word, an error on stderr, then exit ``code``."""
    logs.say(logging.ERROR, message)
    raise typer.Exit(code)


def warn(message: str) -> None:
    """A warning on stderr, the way the log writes one, for a command that carries on."""
    logs.say(logging.WARNING, message)


def staged_end(reporter: _Lines, result: StagedResult, *, progress: bool, refused: str, done: str) -> None:
    """A staged job's last lines (staged.py: ``caracole youtube --sheet``, ``caracole transcribe``), once its stages
    were said through ``reporter``: ``refused`` and what stopped it (its refusal, what failed, a bug), else ``done``;
    with ``progress``, the ``done`` event caracole serve reads; then exit 1 unless the job was ``ok``."""
    reporter.flush()
    stopped = result.refused or result.failed or (f"a bug in caracole ({result.bug})" if result.bug else None)
    typer.echo(f"{refused}: {stopped.rstrip('.')}." if stopped else done)
    if progress:
        typer.echo(reporter.event({"done": {"seconds": round(result.seconds, 3), "requests": result.requests,
                                            "ok": result.ok, "refused": result.refused}}))
    if not result.ok:
        raise typer.Exit(1)


_unwarned: str | None = None  # what a command on the home defaults beside the service says first (load_cfg)


def load_cfg(ctx: typer.Context, *, builds_index: str | None = None) -> Config:
    """The config, the one way a command reads it.

    With no config named (no ``--config``, no ``CARACOLE_CONFIG``) on a machine that runs caracole as a service
    (service.py), caracole's home defaults are another library than the service's: a command that builds an
    index, ``builds_index`` (its words, "gametabs --index"), exits 2 saying so, and any other owes a warning, said
    once before its first write (``warn_elsewhere``: as it takes caracole's lock), unless ``--home``.
    """
    from caracole import service

    global _unwarned
    path = ctx.obj.config_path if ctx.obj is not None else None
    try:
        cfg = load_config(path)
    except ConfigError as e:
        fail(f"config: {e}", 2)
    _unwarned = None
    home = ctx.obj is not None and getattr(ctx.obj, "home", False)
    found = None if home else service.elsewhere(cfg, os.environ, explicit=path is not None)
    if found is not None:
        if builds_index is not None:
            fail(service.refusal(cfg, found, builds_index), 2)
        _unwarned = service.warning(cfg, found, _command_words(ctx))
        ctx.call_on_close(_forget_warning)  # a command that only read leaves nothing owed to the next one
    return cfg


def _forget_warning() -> None:
    global _unwarned
    _unwarned = None


def _command_words(ctx: typer.Context) -> str:
    """The command as typed, without the program's name: "songbook add", "get"."""
    return " ".join(ctx.command_path.split()[1:]) or ctx.command_path


def warn_elsewhere() -> None:
    """The warning ``load_cfg`` found the command owes, said once: on the home defaults beside caracole's service.
    Taking caracole's lock says it (every command that writes or sends requests takes it); one that writes first
    (``caracole add``, ``caracole serve``) calls this itself."""
    global _unwarned
    if _unwarned is not None:
        said, _unwarned = _unwarned, None
        warn(said)


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


def read_song_text(cfg: Config, text: str) -> tuple[str, str] | None:
    """The artist and the title one text names, ``caracole add TEXT``'s or ``caracole get TEXT``'s: read as the pages
    read a query (song_names.py ``read_names``), and said ("Read “…” as Artist - Title.") unless they are the text
    as written; None for a text that doesn't say who its artist is. A database caracole can't open now knows no
    artist, and the text is read all the same (``caracole add`` keeps its line without one)."""
    from caracole.song_names import read_names

    try:
        conn: sqlite3.Connection | None = db.connect(cfg.db_path)
    except (OSError, sqlite3.Error):
        conn = None
    try:
        named = read_names(conn, text)
    finally:
        if conn is not None:
            conn.close()
    written = " ".join(text.split())
    if named is not None and f"{named[0]} - {named[1]}" != written:
        typer.echo(f"Read “{written}” as {named[0]} - {named[1]}.")
    return named


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
# Lock files this process took as interactive or in the lane: hands the lock to lane lookups alone (``hand_over``;
# one in the lane takes turns instead, ``pass_turn``).
_as_lookup: set[Path] = set()
_lane: dict[Path, int] = {}  # lock file -> the lane file's descriptor, flocked shared while this process is in the lane


def _acquire(cfg: Config, what: str, *, fatal: bool = True, interactive: bool = False, lane: bool = False,
             on_wait: Callable[[str], None] | None = None) -> Path:
    """Take caracole's lock, waiting for another process that holds it; see ``exclusive``.

    Held here already, it is taken again, of the outer one's kind. Else, three ways: ``lane``, a lookup in the
    lane, joins it (a shared flock of ``LANE_NAME``, blocking, as nothing holds it exclusively but for an instant)
    and takes the lock at once when it is free and no lane ticket waits, else waits announced, in the lane's
    order; ``interactive`` takes it at once when it is free and the lane empty, else waits announced; anything
    else waits outside handoffs and the lane (``_take_outside_handoffs``). An acquire that fails before it has the
    lock (Ctrl-C as it waits) lets go of the lane too, so a process that goes on is out of it."""
    warn_elsewhere()
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
    lane_fd: int | None = None
    try:
        if lane:
            lane_path = cfg.state_dir / LANE_NAME
            try:
                lane_fd = os.open(lane_path, os.O_RDWR | os.O_CREAT, 0o600)
            except OSError as e:
                if not fatal:
                    raise
                fail(f"can't open {lane_path}: {_reason(e)}")
            fcntl.flock(lane_fd, fcntl.LOCK_SH)  # in the lane: from now on, nobody outside it takes the lock
            if lane_tickets(cfg) or not _try_flock(fd):
                _warn_waiting(fd)
                _wait_announced(cfg, what, fd, lane=True, on_wait=on_wait)
        elif interactive:
            had = _try_flock(fd)
            if not (had and _lane_empty(cfg)):
                if had:  # free, but lookups are in the lane: theirs first
                    fcntl.flock(fd, fcntl.LOCK_UN)
                _warn_waiting(fd)
                _wait_announced(cfg, what, fd, on_wait=on_wait)
        else:
            _take_outside_handoffs(cfg, fd, fatal=fatal, on_wait=on_wait)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()} {what}\n".encode(), 0)
    except BaseException:
        os.close(fd)
        if lane_fd is not None:
            os.close(lane_fd)  # and with it the lane
        raise
    _held[path] = (fd, 1)
    if lane_fd is not None:
        _lane[path] = lane_fd
    if interactive or lane:
        _as_lookup.add(path)
    return path


def _try_flock(fd: int) -> bool:
    """Flock ``fd`` exclusively if nothing stands in the way, never waiting; True when it did."""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _warn_waiting(fd: int) -> None:
    """What a lookup, or what the owner asked for now, says as it starts to wait for caracole's lock (``fd``)."""
    warn(f"Another caracole is running ({_holder(fd)}); it lets a lookup go first at its next pause, "
         "or between two songs.")


def _take_outside_handoffs(cfg: Config, fd: int, *, fatal: bool,
                           on_wait: Callable[[str], None] | None) -> None:
    """Take caracole's lock (``fd``) as a caracole that isn't a lookup: once the one that holds it is done,
    and never while bulk work, or what the owner asked for now, has let go of it for a lookup (``hand_over``,
    which holds the flock of ``HANDOFF_NAME`` meanwhile). A lock taken then is let go at once, and taken again
    once the handoff is over: a `caracole-admin` command waiting for the nightly run takes it after the whole
    run, never in the middle of one of its steps, and never ahead of the lookup. Nor while a lookup is in the lane
    (``_lane_empty``): it lets go of a lock it took then, waits for the lane to empty holding nothing
    (``_wait_lane_empty``), and starts again."""
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
            if not _lane_empty(cfg):  # lookups in the lane: theirs, however long, then this one's
                fcntl.flock(fd, fcntl.LOCK_UN)
                said = said or say()
                _wait_lane_empty(cfg)
                continue
            return
    finally:
        os.close(gate)


def _lane_empty(cfg: Config) -> bool:
    """Whether no lookup is in the lane: the lane file flocked exclusively for an instant, on a descriptor of this
    call's own. A lane file that can't be opened has nobody in it (a lookup that can't open it never joins).
    A lane process never asks: it would find itself there."""
    try:
        fd = os.open(cfg.state_dir / LANE_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return True
    try:
        return _try_flock(fd)
    finally:
        os.close(fd)  # and with it the flock, had it


def _wait_lane_empty(cfg: Config) -> None:
    """Wait until no lookup is in the lane, however long its work: the lane file flocked exclusively, blocking, then
    let go at once. The caller holds nothing meanwhile. A lane process never calls it: it would wait for itself."""
    try:
        fd = os.open(cfg.state_dir / LANE_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    finally:
        os.close(fd)


def _announce(cfg: Config, what: str, *, lane: bool = False, again: Path | None = None) -> Path:
    """Say that a lookup waits for the lock: a file named after this process, which goes once it has it.
    A lane ticket (``lane``) is named by when it was made first, ``lane.<time.time_ns(), 20 digits>.<pid>``
    (``.<n>`` after it on a clash), so the lane's tickets sort oldest first (``lane_tickets``); any other is
    ``<pid>.<n>``. ``again``: a ticket deleted from under its lookup, made again under its own name while that
    name is free, so a lane ticket keeps its place in the lane."""
    folder = cfg.state_dir / WAITING_DIR
    folder.mkdir(mode=0o700, exist_ok=True)
    stem = f"{LANE_TICKET}{time.time_ns():020d}.{os.getpid()}" if lane else str(os.getpid())

    def names() -> Iterator[Path]:
        if again is not None:
            yield folder / again.name
        for n in range(1000):
            yield folder / (stem if lane and n == 0 else f"{stem}.{n}")

    for ticket in names():
        try:
            fd = os.open(ticket, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with open(fd, "w", encoding="utf-8") as f:
            f.write(f"{what}\n")
        return ticket
    raise OSError(f"too many lookups of this process wait in {folder}")


def _wait_announced(cfg: Config, what: str, fd: int, *, lane: bool = False, ticket: Path | None = None,
                    on_wait: Callable[[str], None] | None = None) -> None:
    """Wait for caracole's lock as a lookup: announced by a ticket (``ticket``, else a new one), touched every
    ``TICKET_BEAT`` seconds while this process tries for the lock, so that a ticket left by a lookup that was
    killed while it waited (its pid maybe another process's since) soon stops counting (``lookups_waiting``).

    A lane ticket (``lane``) tries for the lock only while it heads the lane (``lane_tickets``), so the lane's
    lookups go in the order they came; any other takes the lock only while the lane is empty, letting go at
    once of one it had. ``on_wait`` hears whom it waits for once, ``WAIT_SAID`` seconds after the wait began:
    a lookup that starts as another passes its turn says nothing."""
    ticket = ticket or _announce(cfg, what, lane=lane)
    began = beat = time.monotonic()
    told = on_wait is None
    try:
        while True:
            if not lane or lane_tickets(cfg)[:1] == [ticket]:
                if _try_flock(fd):
                    if lane or _lane_empty(cfg):
                        return
                    fcntl.flock(fd, fcntl.LOCK_UN)  # not the lane's, and lookups are in it: theirs first
            _handoff_sleep(WAIT_POLL)
            now = time.monotonic()
            if not told and now - began >= WAIT_SAID:
                told = True
                assert on_wait is not None
                on_wait(_holder(fd))
            if now - beat >= TICKET_BEAT:
                beat = now
                try:
                    os.utime(ticket)
                except FileNotFoundError:  # deleted from under it: announced again, in its place in the lane
                    ticket = _announce(cfg, what, lane=lane, again=ticket)
    finally:
        ticket.unlink(missing_ok=True)


def _ticket_pid(name: str) -> int | None:
    """The pid a ticket's name gives, ``<pid>.<n>`` or a lane ticket's ``lane.<time>.<pid>[.<n>]``; None for a
    name that isn't caracole's."""
    lane = name.startswith(LANE_TICKET)
    parts = name[len(LANE_TICKET):].split(".") if lane else name.split(".")
    try:
        pid = int(parts[1] if lane else parts[0])
    except (IndexError, ValueError):
        return None
    return pid if pid > 0 else None


def _live_tickets(cfg: Config) -> list[str]:
    """The names of the tickets in caracole's waiting folder that still wait: each of a live process, touched in the
    last ``TICKET_STALE`` seconds. A ticket a process that ended left is dropped, and so is one untouched for
    ``TICKET_FORGOTTEN``."""
    folder = cfg.state_dir / WAITING_DIR
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    live = []
    now = time.time()
    for name in names:
        ticket = folder / name
        pid = _ticket_pid(name)
        if pid is not None:  # else not caracole's name: its age tells
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                ticket.unlink(missing_ok=True)
                continue
            except (PermissionError, OverflowError):
                pass  # a process of another user, or no pid at all: its age tells
        try:
            age = now - ticket.stat().st_mtime
        except OSError:
            continue
        if age > TICKET_STALE:  # nothing waits on it any more: a lookup killed while it waited
            if age > TICKET_FORGOTTEN:
                ticket.unlink(missing_ok=True)
            continue
        live.append(name)
    return live


def lookups_waiting(cfg: Config) -> bool:
    """Whether a lookup waits for caracole's lock, in the lane or not: a ticket of a live process, touched in the
    last ``TICKET_STALE`` seconds (``_live_tickets``)."""
    return bool(_live_tickets(cfg))


def lane_tickets(cfg: Config) -> list[Path]:
    """The lane's tickets that still wait (``_live_tickets``), oldest first: the next to take caracole's lock
    first. A dead one is dropped at once, a stale one passed over."""
    folder = cfg.state_dir / WAITING_DIR
    return [folder / name for name in sorted(_live_tickets(cfg)) if name.startswith(LANE_TICKET)]


def handoffs() -> int:
    """How many times this process handed caracole's lock to a waiting lookup (``hand_over``), or passed it to the
    next lookup in the lane (``pass_turn``), and took it back."""
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


def pass_turn(cfg: Config, conn: sqlite3.Connection | None = None) -> bool:
    """Let the next lookup in the lane have caracole's lock now, and take it back in turn; True when one did.

    Only a lane process calls it, holding the lock, at a turn point, in no transaction: before a request but its
    client's first, and between two stages. With nothing held it is False before it reads anything of ``cfg``;
    False too outside the lane (bulk work, and what the owner asked for now, hand over: ``hand_over``), in a
    transaction (``conn``), or with no lane ticket waiting (``lane_tickets``). Else it writes a lane ticket of its
    own, the newest, so behind every lookup waiting in the lane; lets go of the lock, its depth kept and the lane's
    flock still held, so that nobody outside the lane takes it meanwhile; waits by that ticket until it heads the
    lane and has the lock again (``_wait_announced``); writes its record back; and counts a handoff
    (``handoffs()``), so whatever reads again after a handoff reads again after a turn. Interrupted as it waits
    (Ctrl-C, serve's stop), it holds nothing: its ticket goes, and no record is written."""
    global _handoffs
    if not _held:
        return False
    path = cfg.state_dir / LOCK_NAME
    held = _held.get(path)
    if held is None or path not in _lane or (conn is not None and conn.in_transaction) or not lane_tickets(cfg):
        return False
    if not _away_announced(cfg, held[0], lane=True, refused="No turn"):
        return False
    _handoffs += 1
    logging.getLogger(__name__).debug("Passed caracole's lock to the next lookup in the lane, and took it back.")
    return True


def _away_announced(cfg: Config, fd: int, *, lane: bool, refused: str) -> bool:
    """Let go of caracole's lock (``fd``) and take it back as a lookup, by a ticket written first, the newest
    (``_announce``; a lane ticket with ``lane``), so that whoever waits to take it back after this process sees it
    waiting; then wait by it (``_wait_announced``) and write the lock's record back; True. A ticket that can't be
    written lets go of nothing: ``refused`` says so in the log, and it is False. Interrupted as it waits, it holds
    nothing: its ticket goes, and no record is written."""
    record = os.pread(fd, 256, 0)
    what = record.decode("utf-8", "replace").strip().partition(" ")[2]
    try:
        ticket = _announce(cfg, what, lane=lane)
    except OSError as e:
        logging.getLogger(__name__).warning("%s: no ticket can be written in %s: %s.", refused, WAITING_DIR,
                                            _reason(e))
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        _wait_announced(cfg, what, fd, lane=lane, ticket=ticket)
    except BaseException:
        ticket.unlink(missing_ok=True)  # holding nothing, or about to: no record written
        raise
    os.ftruncate(fd, 0)
    os.pwrite(fd, record, 0)
    return True


def hand_over(cfg: Config, conn: sqlite3.Connection | None = None) -> bool:
    """Let a waiting lookup have caracole's lock now, and take it back once it is done; True when it did.

    Called at a hand-over point (a pause between two requests, between two songs, a YouTube sheet before its
    models), holding the lock, with ``conn`` in no transaction (the lookup must be able to write). A lane process
    never hands over: it takes turns (``pass_turn``). Two ways, by how the lock was taken:

    - Bulk work (the nightly run, a `caracole-admin` command) hands it to any lookup that waits
      (``lookups_waiting``). It holds the flock of ``HANDOFF_NAME`` meanwhile, waiting for it if it must, so that a
      caracole waiting for the lock that isn't a lookup leaves it to the lookups and this process
      (``_take_outside_handoffs``); lets go of the lock; and takes it back last, once the lane is empty and no
      lookup waits (``_take_back_last``: ``HANDOFF_TAKE`` bounds only a ticket nobody takes, never the lane's
      work). Interrupted meanwhile, it takes the lock back all the same: it is never left without it.
    - What the owner asked for now (``exclusive(..., interactive=True)``: a queue job such as ``fetch --song``,
      a YouTube search or sheet) hands it to the lane's lookups alone (``lane_tickets``): another caracole asked
      for now usually waits for its end, though one waiting as this one is away may take the lock first once the
      lane is empty, tickets outside the lane keeping no order. It takes the gate only if it is free, never
      waiting for it: held, it is the bulk work that let this one in, in its own handoff. It waits with a ticket
      of its own, written before it lets go, to take the lock back once the lane is empty (``_away_announced``),
      so the bulk work that let it in, waiting too, gives it back at its next pause rather than keeping it to its
      end. Interrupted as it waits, it holds nothing: its ticket goes, and no record is written.

    Either way, the lock's record (which caracole holds it) is written back and a handoff counted (``handoffs()``).
    Without the gate's file, nothing is handed over.
    """
    global _handoffs
    path = cfg.state_dir / LOCK_NAME
    held = _held.get(path)
    if held is None or path in _lane or (conn is not None and conn.in_transaction):
        return False
    asked_now = path in _as_lookup
    if not (lane_tickets(cfg) if asked_now else lookups_waiting(cfg)):
        return False
    fd, _ = held
    try:
        gate = os.open(cfg.state_dir / HANDOFF_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        logging.getLogger(__name__).info("No lookup goes first: %s can't be opened: %s.", HANDOFF_NAME, _reason(e))
        return False
    try:
        if asked_now:
            _try_flock(gate)  # free, it keeps others out; held, by the bulk work that let this one in
            if not _away_announced(cfg, fd, lane=False, refused="No lookup goes first"):
                return False
        else:
            fcntl.flock(gate, fcntl.LOCK_EX)
            record = os.pread(fd, 256, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
            try:
                _take_back_last(cfg, fd)
            finally:
                fcntl.flock(fd, fcntl.LOCK_EX)  # held again, or interrupted: never left without the lock
                os.ftruncate(fd, 0)
                os.pwrite(fd, record, 0)
    finally:
        os.close(gate)  # and with it its flock, had it
    _handoffs += 1
    logging.getLogger(__name__).info("Handed caracole's lock to %s, and took it back.",
                                     "the lane's lookups" if asked_now else "a lookup")
    return True


def _take_back_last(cfg: Config, fd: int) -> None:
    """Take caracole's lock (``fd``) back as bulk work that handed it over, last: once no ticket waits
    (``lookups_waiting``, ``HANDOFF_TAKE`` seconds at most: a ticket nobody takes) and the lane is empty, however
    long its work (``_wait_lane_empty``, holding nothing but the gate; then the tickets again, whoever waited
    behind the lane first), blocking, and let go again for a lookup that joined the lane meanwhile."""
    while True:
        for _ in range(int(HANDOFF_TAKE / 0.05)):
            if not lookups_waiting(cfg):
                break
            _handoff_sleep(0.05)
        if not _lane_empty(cfg):  # the lane's work, however long: then whoever waits behind it, first
            _wait_lane_empty(cfg)
            continue
        fcntl.flock(fd, fcntl.LOCK_EX)  # whatever holds it lets go at its end, or at its next hand-over point
        if _lane_empty(cfg):
            return
        fcntl.flock(fd, fcntl.LOCK_UN)  # a lookup joined the lane meanwhile: its turns first


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
    _as_lookup.discard(path)
    lane = _lane.pop(path, None)
    os.close(fd)  # and with it the lock
    if lane is not None:
        os.close(lane)  # and with it the lane: once the lock is free


def _holder(fd: int) -> str:
    """Who holds the lock, as its holder wrote it: "pid 4242: run"."""
    try:
        pid, _, what = os.pread(fd, 256, 0).decode("utf-8", "replace").strip().partition(" ")
    except OSError:
        return "pid unknown"
    return f"pid {pid}: {what}" if pid else "pid unknown"


@contextmanager
def exclusive(cfg: Config, what: str, *, fatal: bool = True, interactive: bool = False, lane: bool = False,
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

    ``interactive``: a lookup, or anything else the owner asked for just now (one song's
    add, removal, review, fetch, PDF or YouTube sheet, a YouTube search: what caracole serve
    queues, so that a lookup queued after it never waits behind a whole nightly run either),
    which announces that it waits, so that bulk work hands the lock over at its next pause, or
    between two songs (``hand_over``). Holding it, it hands it on to the lane's lookups alone,
    at its own hand-over points, and takes it back once the lane is empty. ``on_wait`` hears
    whom it waits for, when it must: at once for bulk work, and for one that waits announced once
    it has waited ``WAIT_SAID`` seconds.

    ``lane``: a lookup in the lane, which implies ``interactive``. It holds a shared flock of
    ``state_dir/caracole.lock.lane`` from before it asks for the lock until it lets go of it, and
    waits, when it must, behind the lane's tickets that came before its own (``lane_tickets``).
    While the lane holds anyone, no caracole outside it takes the lock: one that has it lets go
    and waits for the lane to empty, holding nothing. A lock this process holds already is taken
    again of the outer one's kind, so a lookup's clients never wait for a lane it is in.
    """
    path = _acquire(cfg, what, fatal=fatal, interactive=interactive or lane, lane=lane, on_wait=on_wait)
    try:
        yield
    finally:
        _release(path)


# --- clients ---------------------------------------------------------------------------------


def transport_for(provider: str) -> httpx.BaseTransport | None:
    """The transport for a provider's client; tests monkeypatch this to inject fakes."""
    return None


def alert_block(cfg: Config, provider: str, message: str, *, strikes: int) -> None:
    """The ntfy alert a block sends, titled as the nightly run titles one ("caracole: Ultimate Guitar
    blocked", ``logs.provider_name``) with the command's own message: once for the block, never per
    song, high priority; nothing without an ntfy URL. Only the first block of a streak sends one
    (``strikes``, the blocks in a row it leaves: ``health.alerts``). Sending never raises (notify.py)."""
    from caracole.health import alerts

    if not cfg.ntfy.url or not alerts(strikes):
        return
    from caracole.notify import Notifier  # httpx: only when there is an alert to send

    notifier = Notifier(cfg.ntfy.url, transport=transport_for("ntfy"))
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

        A lookup's in the lane (``lane``) passes a turn at the start of its pause before each
        request but its first (``pass_turn``), so the next lookup in the lane uses the pause.
        After a turn, in its pause or between two of its lookup's stages, it keeps what the other
        left as bulk work's does (its block, the pause after its last request), and its budget is
        cut to what is left: of ``lookup_per_hour``, every lookup's of the last hour, less its
        ``reserve`` (after the sheet, get.py keeps ``SHEETS_SHARE`` of the hour for sheets), and
        of the UTC day's ``per_day``; spent, its next request is never sent (``BudgetExhausted``,
        one ``budget`` event), and ``kept_back`` says when the reserve had a part in the cut: when the
        budget would be more without it.
        """

        def __init__(self, *args, lock: Path, cfg: Config | None = None,
                     conn: sqlite3.Connection | None = None, yields: bool = False, lane: bool = False,
                     seen: int | None = None, **kwargs):
            super().__init__(*args, **kwargs)
            self._lock: Path | None = lock
            self._cfg = cfg
            self._conn = conn
            self._yields = yields and cfg is not None
            self._lane = lane and cfg is not None and conn is not None
            self._seen = _handoffs if seen is None else seen  # the handoffs this client has looked at
            self.reserve = 0  # of lookup_per_hour, what a turn's cut leaves for sheets (get.py, after the sheet)
            self.kept_back = False  # whether a turn's cut came from the reserve: get.py says it was kept for sheets

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
            if self._lane and self.requests_made > 0:  # never before its first request
                assert self._cfg is not None
                pass_turn(self._cfg, self._conn)  # the next lookup in the lane goes first, in this pause
            self._after_a_lookup(url)  # one had the lock since this client last looked
            super()._pause(url)
            self._after_a_lookup(url)  # one went first in this very pause, which began again after it

        def _after_a_lookup(self, url: str) -> None:
            """What a lookup this process let go first, or the lookup whose turn it was, left, once there was one
            since the client last looked, before its next request: a block the lookup met (health.py, as the
            lookup recorded it) is this client's too, and nothing is sent; else the pause runs from the last
            request any caracole sent the site (kv ``http:last_request:``), the lookup's included, when that is
            later than its own; and a lane client's budget is what the other left (``_within_what_is_left``)."""
            if not (self._yields or self._lane) or self._conn is None or self._seen == _handoffs:
                return
            self._seen = _handoffs
            if is_cooling(self._conn, self.provider, self._wall_clock()):
                met = "met by a lookup caracole let go first" if self._yields else "met by another lookup at its turn"
                self._blocked = ProviderBlocked(self.provider, url, None, met)
                raise self._blocked
            last = _last_request(self._conn, self.provider)
            if last is not None:
                at = self._clock() - max(0.0, time.time() - last)
                if self._last_request is None or at > self._last_request:
                    self._last_request = at
            if self._lane:
                self._within_what_is_left(url)

        def _within_what_is_left(self, url: str) -> None:
            """A lane client's budget after another lookup's turn, read again as ``lookup_policy`` and
            ``within_the_day`` read it when the client was made, the other's requests now among them: no more
            than what the last hour's lookups left of ``lookup_per_hour`` less its ``reserve``, nor than what the
            UTC day left of a ``per_day``. Spent, ``BudgetExhausted`` before the request, its one ``budget``
            event. A turn that cuts it says whether the reserve had a part in the cut (``kept_back``): whether
            the budget would be more without it; the hour spent whole, or the day, is no reserve's."""
            assert self._cfg is not None and self._conn is not None
            now = self._wall_clock()
            used = lookup_requests_used(self._conn, self.provider, now)
            per_hour = self._cfg.provider(self.provider).lookup_per_hour
            day = (None if self.policy.per_day is None
                   else self.policy.per_day - requests_today(self._conn, self.provider, now))

            def cut(reserve: int) -> int:
                budget = min(self.policy.budget, self.requests_made + max(0, per_hour - reserve - used))
                return budget if day is None else min(budget, self.requests_made + max(0, day))

            budget = cut(self.reserve)
            if budget < self.policy.budget:  # this turn's cut: the reserve's, or the hour's or the day's
                self.kept_back = budget < cut(0)
            self.policy = replace(self.policy, budget=budget)
            self._check_budget(url)

        def close(self) -> None:
            try:
                super().close()
            finally:
                if self._lock is not None:
                    _release(self._lock)
                    self._lock = None

    return _LockedClient


# Events that were requests: a redirect too, followed or not, which reached the site as any other request did.
CONNECT_PATIENCE = 60.0  # s: how long bulk work tries again a connection that fails before any byte is sent
_SENT = ("ok", "not_modified", "redirect", "blocked", "error")
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


def requests_today(conn: sqlite3.Connection, provider: str, now: datetime | None = None) -> int:
    """How many requests every caracole sent the provider since UTC midnight: every run's, command's and lookup's
    (``events``)."""
    midnight = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT00:00:00Z")
    sent = ",".join("?" * len(_SENT))
    return conn.execute(
        f"SELECT COUNT(*) FROM events WHERE provider = ? AND at >= ? AND decision IN ({sent})",
        (provider, midnight, *_SENT),
    ).fetchone()[0]


def within_the_day(conn: sqlite3.Connection, provider: str, policy: ProviderPolicy,
                   now: datetime | None = None) -> ProviderPolicy:
    """``policy`` with no more requests than the UTC day leaves of its ``per_day`` (Megalobiz's API counts an
    address's requests a day, and resets at midnight UTC): a site with none keeps its budget."""
    if policy.per_day is None:
        return policy
    left = max(0, policy.per_day - requests_today(conn, provider, now))
    return policy if policy.budget <= left else replace(policy, budget=left)


def make_client(
    cfg: Config,
    conn: sqlite3.Connection,
    provider: str,
    run_id: str,
    *,
    policy: ProviderPolicy | None = None,
    on_event: Callable[[Event], None] | None = None,
    interactive: bool = False,
    ticker: Ticker | None = None,
) -> PoliteClient:
    """A polite client for one provider and one run, logging every request to ``events``.

    It holds caracole's lock (``exclusive``) until it is closed, so no other
    caracole sends requests meanwhile, and its first request keeps the pause
    after the provider's last one, made by this process or another. Every
    caller closes it. ``policy`` stands in for the provider's own (``caracole
    index build`` has a budget of its own), and ``on_event`` hears every
    event too, once it is logged.

    Bulk work's client keeps the provider's ``delay`` and ``budget``, and hands
    the lock to a waiting lookup in its pauses (under a lock taken as asked for now, as
    ``fetch --song`` takes it, to the lane's lookups alone). ``interactive``, a lookup's
    (``caracole get``), keeps ``lookup_policy``: a gap of a quarter of a second, and a
    few requests; its run id starts with ``lookup:`` so the hourly budget counts
    them, and it never hands the lock over. A lookup's client in the lane (its process holds
    the lock in the lane) passes a turn before each request but its first, and after one keeps
    what the other left: its block, its last request's pause, the hour, the day and its
    ``reserve``. Bulk work's tries a connection that fails before any byte is
    sent again for up to ``CONNECT_PATIENCE`` (a run that starts as the laptop wakes, before its Wi-Fi has
    an address); a lookup's says at once. Either way, a site with a ``per_day``
    (Megalobiz) gets no more than what the UTC day leaves of it (``within_the_day``).
    With a ``ticker`` (progress.py), the requests it sends are counted there against that budget
    (``progress.Requests``), which only counts: its pace and budget are what they would be without.
    """
    if interactive and not run_id.startswith(LOOKUP_RUN):
        run_id = LOOKUP_RUN + run_id
    lock = _acquire(cfg, f"{provider} requests", interactive=interactive)
    try:
        policy = policy or (lookup_policy(cfg, conn, provider) if interactive else cfg.provider(provider))
        policy = within_the_day(conn, provider, policy)
        seen = _handoffs  # a lookup let go first in the pause before its first request counts too
        _pause_after_last_request(conn, provider, policy.delay, cfg=None if interactive else cfg)
        log = EventLog(conn, run_id)
        heard = _heard(on_event, ticker, provider, policy)

        def logged(event: Event) -> None:
            log(event)
            if event.decision in _SENT:
                db.kv_set(conn, _LAST_SENT + provider, f"{time.time():.3f}")
            if heard is not None:
                heard(event)

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
            lane=interactive and lock in _lane,
            seen=seen,
            connect_patience=0.0 if interactive else CONNECT_PATIENCE,
        )
    except BaseException:
        _release(lock)
        raise


def _heard(on_event: Callable[[Event], None] | None, ticker: Ticker | None, provider: str, policy: ProviderPolicy, *,
           noun: str = "request", estimate: bool = True) -> Callable[[Event], None] | None:
    """What a client's events go to once logged: ``on_event``, then, with a ``ticker``, ``progress.Requests``
    counting them against ``policy``'s budget (none for ``NO_BUDGET``), with the time left unless ``estimate`` is
    False (yt-dlp's runs)."""
    if ticker is None:
        return on_event
    from caracole.config import NO_BUDGET
    from caracole.progress import Requests

    beat = Requests(ticker, provider, budget=None if policy.budget == NO_BUDGET else policy.budget,
                    delay=policy.delay, noun=noun, estimate=estimate)
    if on_event is None:
        return beat

    def both(event: Event) -> None:
        on_event(event)
        beat(event)

    return both


@functools.cache
def _locked_parallel() -> type:
    """The class of ``make_parallel_client``'s clients, made the first time a command makes one."""
    from caracole.http import ParallelClient, ProviderBlocked

    class _LockedParallel(ParallelClient):
        """A ParallelClient holding caracole's lock until it is closed. Its workers never hand the lock over (they
        never touch the database); between two batches of its requests, with none in flight, its caller does
        (``between``)."""

        def __init__(self, *args, lock: Path, cfg: Config, conn: sqlite3.Connection, **kwargs):
            super().__init__(*args, **kwargs)
            self._lock_file: Path | None = lock
            self._cfg = cfg
            self._conn = conn

        def between(self) -> bool:
            """Let a lookup that waits have caracole's lock now, and take it back; True when one did. Once one has, a
            block it met (health.py, as the lookup recorded it) is this client's too, and nothing more is sent; else
            its next request keeps the pause after the lookup's last one, as bulk work's client does."""
            self.drain()
            if not hand_over(self._cfg, self._conn):
                return False
            if is_cooling(self._conn, self.provider, self._wall_clock()):
                self._blocked = ProviderBlocked(self.provider, None, None, "met by a lookup caracole let go first")
                return True
            last = _last_request(self._conn, self.provider)
            if last is not None:
                self._last_request = self._clock() - max(0.0, time.time() - last)
            return True

        def close(self) -> None:
            try:
                super().close()
            finally:
                if self._lock_file is not None:
                    _release(self._lock_file)
                    self._lock_file = None

    return _LockedParallel


def make_parallel_client(
    cfg: Config,
    conn: sqlite3.Connection,
    provider: str,
    run_id: str,
    *,
    policy: ProviderPolicy,
    workers: int,
    on_event: Callable[[Event], None] | None = None,
) -> PoliteClient:
    """A client for bulk work that has several requests in flight at once (``http.ParallelClient``): UG's artist
    directory alone, the owner's choice of 2026-11-17 (ug/directory.py). As ``make_client``'s, it holds caracole's
    lock until it is closed, its first request keeps the pause after the provider's last one, and every request is
    logged to ``events`` and moves ``http:last_request:`` on, in this thread (the workers' events are drained into it).
    ``policy`` is the pass's own (its budget and pause), ``workers`` its requests in flight; between two batches, its
    caller hands the lock to a waiting lookup (its ``between``)."""
    lock = _acquire(cfg, f"{provider} directory requests")
    try:
        policy = within_the_day(conn, provider, policy)
        _pause_after_last_request(conn, provider, policy.delay, cfg=cfg)
        log = EventLog(conn, run_id)

        def logged(event: Event) -> None:
            log(event)
            if event.decision in _SENT:
                db.kv_set(conn, _LAST_SENT + provider, f"{time.time():.3f}")
            if on_event is not None:
                on_event(event)

        return _locked_parallel()(
            provider, policy, cfg.cache_dir, user_agent=cfg.user_agent, transport=transport_for(provider),
            sleep=lambda seconds: sleep(seconds), on_event=logged, workers=workers, lock=lock, cfg=cfg, conn=conn,
            connect_patience=CONNECT_PATIENCE,
        )
    except BaseException:
        _release(lock)
        raise


def directory_client(cfg: Config, conn: sqlite3.Connection, run_id: str, *, budget: int | None = None) -> PoliteClient:
    """UG's artist directory's client (ug/directory.py), with ``[ug_directory]``'s concurrency, pause and budget (or
    ``budget``): provider ``ug``, its every request counted as UG's."""
    d = cfg.ug_directory
    policy = replace(cfg.provider("ug"), budget=d.budget if budget is None else budget, delay=d.delay)
    return make_parallel_client(cfg, conn, "ug", run_id, policy=policy, workers=d.concurrency)


def make_youtube(
    cfg: Config,
    conn: sqlite3.Connection,
    run_id: str,
    *,
    on_event: Callable[[Event], None] | None = None,
    ticker: Ticker | None = None,
) -> YtDlp:
    """yt-dlp for one run (youtube.py), as ``make_client`` makes a provider's client: it holds
    caracole's lock until it is closed, its first run keeps the pause after the last one any
    caracole made, and every run is logged to ``events``, and counted on ``ticker`` as
    ``make_client``'s requests are. Every caller closes it.

    It is bulk work: each pause, its first included, hands the lock to a lookup that waits
    meanwhile (``hand_over``; under a lock taken as asked for now, a YouTube search's, to the
    lane's lookups alone), then starts again, whole."""
    from caracole.youtube import PROVIDER, YtDlp

    lock = _acquire(cfg, "youtube downloads")
    try:
        policy = cfg.provider(PROVIDER)
        _pause_after_last_request(conn, PROVIDER, policy.delay, cfg=cfg)
        log = EventLog(conn, run_id)
        heard = _heard(on_event, ticker, PROVIDER, policy, noun="yt-dlp run", estimate=False)  # a run: minutes

        def logged(event: Event) -> None:
            log(event)
            if heard is not None:
                heard(event)

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
