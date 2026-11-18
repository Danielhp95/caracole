"""The lane at caracole's lock (commands/_common.py): lookups taking turns, and everyone else waiting for an
empty lane."""

from __future__ import annotations

import fcntl
import os
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from helpers.lanes import HOLD, TURNS, WAITER, config_file, records, start, wait_for
from helpers.locks import waiting_for

from caracole import db
from caracole.commands import _common
from caracole.commands._common import exclusive

from test_commands_common import another_caracole, free


def in_the_lane(cfg) -> int:
    """A lookup in the lane, as another process holds it: a descriptor of the lane file, flocked shared."""
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(cfg.state_dir / _common.LANE_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_SH)
    return fd


def lane_is_empty(cfg) -> bool:
    """Whether another process could flock the lane file exclusively now: nobody in the lane."""
    probe = os.open(cfg.state_dir / _common.LANE_NAME, os.O_RDWR)
    try:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(probe)
    return True


def a_lookup_waiting_in_the_lane(cfg) -> Path:
    """A fresh lane ticket of this process, as a lookup's that waits to take caracole's lock in turn."""
    folder = cfg.state_dir / _common.WAITING_DIR
    folder.mkdir(mode=0o700, exist_ok=True)
    ticket = folder / f"{_common.LANE_TICKET}{time.time_ns():020d}.{os.getpid()}"
    ticket.write_text("get C - D\n", encoding="utf-8")
    return ticket


@contextmanager
def processes() -> Iterator[list[subprocess.Popen]]:
    """The processes a test starts, each killed at its end, however it ends."""
    started: list[subprocess.Popen] = []
    try:
        yield started
    finally:
        for p in started:
            p.kill()
            p.wait()


def until(seen: Callable[[], object], running: Callable[[], bool], timeout: float = 10.0) -> bool:
    """Whether ``seen()`` comes true while ``running()`` holds, within ``timeout`` seconds: a state waited for."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and running():
        if seen():
            return True
        time.sleep(0.005)
    return bool(seen())


def test_a_lookup_in_the_lane_takes_a_free_lock_at_once_and_leaves_the_lane_as_it_lets_go(cfg):
    with exclusive(cfg, "get Oasis - Wonderwall", lane=True):
        assert not lane_is_empty(cfg)  # a lookup is in the lane
        assert not free(cfg)  # and holds the lock, which nothing held: taken at once, with no ticket
        lock = cfg.state_dir / _common.LOCK_NAME
        assert lock.read_text(encoding="utf-8") == f"{os.getpid()} get Oasis - Wonderwall\n"
        assert not _common.lane_tickets(cfg)
    assert lane_is_empty(cfg)  # empty again: nothing of it left in this process
    assert free(cfg) and not _common._lane


@pytest.mark.parametrize("asked_now", [False, True], ids=["bulk", "asked now"])
def test_a_caracole_outside_the_lane_waits_for_it_to_empty_even_with_the_lock_free(cfg, asked_now):
    lane = in_the_lane(cfg)
    took = threading.Event()

    def other() -> None:
        with exclusive(cfg, "remove Radiohead - Creep --yes", interactive=asked_now):
            took.set()

    thread = threading.Thread(target=other, daemon=True)
    try:
        thread.start()
        assert waiting_for(cfg.state_dir / _common.LANE_NAME, thread.is_alive)  # blocked on the lane, or its ticket
        assert not took.is_set()
        if not asked_now:
            assert free(cfg)  # it waits for the lane holding nothing
    finally:
        os.close(lane)
    assert took.wait(5)
    thread.join(5)


def test_lane_tickets_go_oldest_first_passing_over_a_dead_or_stale_one(cfg):
    folder = cfg.state_dir / _common.WAITING_DIR
    folder.mkdir(parents=True)
    pid = os.getpid()
    dead, stale, first, second = (f"lane.{1:020d}.999999999", f"lane.{2:020d}.{pid}", f"lane.{3:020d}.{pid}",
                                  f"lane.{4:020d}.{pid}.1")
    for name in (second, stale, f"{pid}.0", dead, first):  # an asked now's ticket among them, not the lane's
        (folder / name).write_text("get A - B\n", encoding="utf-8")
    then = time.time() - _common.TICKET_STALE - 1
    os.utime(folder / stale, (then, then))
    assert [t.name for t in _common.lane_tickets(cfg)] == [first, second]
    assert not (folder / dead).exists()  # its process gone: dropped
    assert (folder / stale).exists()  # untouched a while: passed over, kept until it is forgotten
    (folder / f"{pid}.0").unlink()
    gone = folder / f"lane.{5:020d}.999999999"
    gone.write_text("get C - D\n", encoding="utf-8")
    assert _common.lookups_waiting(cfg)  # a lane ticket is a lookup waiting, for bulk work's pauses
    assert not gone.exists()  # and its pid read from its name: a gone one dropped at once


def test_a_lookup_joining_the_lane_waits_behind_an_older_ticket_even_with_the_lock_free(cfg):
    folder = cfg.state_dir / _common.WAITING_DIR
    folder.mkdir(parents=True)
    older = folder / f"lane.{1:020d}.{os.getpid()}"  # a lookup ahead of it in the lane, about to take the lock
    older.write_text("get A - B\n", encoding="utf-8")
    took = threading.Event()

    def lookup() -> None:
        with exclusive(cfg, "get C - D", lane=True):
            took.set()

    thread = threading.Thread(target=lookup, daemon=True)
    try:
        thread.start()
        assert until(lambda: len(_common.lane_tickets(cfg)) == 2, thread.is_alive)  # its ticket, behind the older
        assert not took.is_set() and free(cfg)
    finally:
        older.unlink()
    assert took.wait(5)  # its turn once the older one went
    thread.join(5)
    assert not _common.lane_tickets(cfg)


def test_a_waiting_lookup_tells_whom_it_waits_for_only_once_it_has_waited_a_moment(cfg, monkeypatch):
    told: list[str] = []

    def lookup() -> None:
        with exclusive(cfg, "get A - B", lane=True, on_wait=told.append):
            pass

    monkeypatch.setattr(_common, "WAIT_SAID", 2.0)
    with another_caracole(cfg):
        thread = threading.Thread(target=lookup, daemon=True)
        thread.start()
        assert until(lambda: _common.lane_tickets(cfg), thread.is_alive)  # it waits: let go at once, a turn's moment
    thread.join(5)
    assert not thread.is_alive() and told == []

    monkeypatch.setattr(_common, "WAIT_SAID", 0.3)
    with another_caracole(cfg):
        thread = threading.Thread(target=lookup, daemon=True)
        thread.start()
        assert until(lambda: told, thread.is_alive, timeout=5)
        assert told == ["pid 4242: run"]
    thread.join(5)
    assert not thread.is_alive() and told == ["pid 4242: run"]


def test_a_lock_taken_inside_the_lane_keeps_its_kind(cfg):
    done, still = threading.Event(), []

    def lookup() -> None:
        with exclusive(cfg, "get A - B", lane=True):
            with exclusive(cfg, "ug requests"):  # make_client's lock never waits for a lane its own process is in
                done.set()
            still.append(lane_is_empty(cfg))

    thread = threading.Thread(target=lookup, daemon=True)
    thread.start()
    assert done.wait(5)
    thread.join(5)
    assert still == [False]  # the inner one let go: the lookup still in the lane


def test_an_acquire_interrupted_as_it_waits_leaves_the_lane_empty(cfg, monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(_common, "_wait_announced", interrupted)
    with another_caracole(cfg):
        with pytest.raises(KeyboardInterrupt):
            with exclusive(cfg, "get A - B", lane=True):
                pass
        assert lane_is_empty(cfg)  # the failed acquire let go of the lane too
    assert not _common._held and not _common._lane


# --- turns ---------------------------------------------------------------------------------------


def test_no_turn_in_a_transaction_nor_outside_the_lane(cfg, conn, monkeypatch):
    waited: list[dict] = []

    def takes_it_back(cfg, what, fd, **kwargs) -> None:  # its turn come at once: the lock back
        waited.append(kwargs)
        fcntl.flock(fd, fcntl.LOCK_EX)

    lock = cfg.state_dir / _common.LOCK_NAME
    with exclusive(cfg, "get A - B", lane=True):
        a_lookup_waiting_in_the_lane(cfg)
        monkeypatch.setattr(_common, "_wait_announced", takes_it_back)
        handed = _common.handoffs()
        conn.execute("BEGIN")
        assert not _common.pass_turn(cfg, conn)
        conn.execute("ROLLBACK")
        with db.savepoint(conn, "half"):
            assert not _common.pass_turn(cfg, conn)
        assert waited == []  # no turn begun in either
        assert not _common.hand_over(cfg, conn)  # a lane process takes turns, never hands over (a render's between)
        assert _common.pass_turn(cfg, conn)  # in no transaction, a lookup waiting: a turn
        assert waited[0]["lane"] is True and waited[0]["ticket"].name.startswith(_common.LANE_TICKET)
        assert _common.handoffs() == handed + 1  # counted as a handoff: what reads again after one reads again
        assert lock.read_text(encoding="utf-8") == f"{os.getpid()} get A - B\n"  # its record written back
        assert not lane_is_empty(cfg)  # in the lane all along
    with exclusive(cfg, "run"):
        assert not _common.pass_turn(cfg, conn)  # bulk work hands over, it has no turns
    assert len(waited) == 1
    assert not _common.pass_turn(cfg)  # nothing held

    class Unread:
        def __getattr__(self, name):
            raise AssertionError(f"cfg.{name} read")

    assert not _common.pass_turn(Unread())  # nothing held: False before it reads anything of cfg


def test_a_turn_interrupted_as_it_waits_leaves_no_ticket_and_the_lock_free(cfg, monkeypatch):
    waited: list[dict] = []

    def interrupted(cfg, what, fd, **kwargs) -> None:
        waited.append(kwargs)
        raise KeyboardInterrupt

    handed = _common.handoffs()
    with pytest.raises(KeyboardInterrupt), exclusive(cfg, "get A - B", lane=True):
        other = a_lookup_waiting_in_the_lane(cfg)
        monkeypatch.setattr(_common, "_wait_announced", interrupted)
        _common.pass_turn(cfg)
    assert waited[0]["ticket"].name.startswith(_common.LANE_TICKET)  # interrupted waiting for its turn
    assert waited[0]["ticket"] != other
    assert not waited[0]["ticket"].exists()  # its own ticket gone
    assert _common.handoffs() == handed  # no turn taken
    assert not _common._held and not _common._lane and lane_is_empty(cfg)
    took = threading.Event()

    def removal() -> None:
        with exclusive(cfg, "remove A - B --yes"):
            took.set()

    thread = threading.Thread(target=removal, daemon=True)
    thread.start()
    assert took.wait(5)
    thread.join(5)


def test_a_lane_ticket_deleted_from_under_its_lookup_comes_back_in_its_place(cfg):
    took = threading.Event()

    def lookup() -> None:
        with exclusive(cfg, "get A - B", lane=True):
            took.set()

    with another_caracole(cfg):
        thread = threading.Thread(target=lookup, daemon=True)
        thread.start()
        assert until(lambda: len(_common.lane_tickets(cfg)) == 1, thread.is_alive)
        [own] = _common.lane_tickets(cfg)
        later = a_lookup_waiting_in_the_lane(cfg)  # a lookup that came after it, and still waits
        own.unlink()
        assert until(own.exists, thread.is_alive, timeout=5)  # announced again under its own name
        assert _common.lane_tickets(cfg) == [own, later]  # so still ahead of the one that came after it
    assert took.wait(5)
    thread.join(5)
    later.unlink()


@pytest.mark.slow
def test_two_lookups_in_the_lane_take_turns_at_the_lock(cfg, tmp_path):
    config, log = config_file(cfg, tmp_path), tmp_path / "lane.log"
    go = {name: tmp_path / f"go-{name}" for name in "ab"}
    with processes() as started:
        started += [start(TURNS, config, log, name, 6, go=go[name]) for name in "ab"]
        a, b = started
        for name in "ab":
            wait_for(log, "ready", name)
        with another_caracole(cfg):  # both asked while the lock is held: each waits in the lane, its ticket posted
            for path in go.values():
                path.touch()
            assert until(lambda: len(_common.lane_tickets(cfg)) == 2,
                         lambda: a.poll() is None and b.poll() is None)
        released_at = time.time()
        assert a.wait(30) == 0 and b.wait(30) == 0, (tmp_path / "lane.log.err").read_text()
    names = [r.name for r in records(log) if r.word == "turn"]
    assert names in (list("ab" * 6), list("ba" * 6))  # by turns, from the first: the other waits at each one
    assert wait_for(log, "turn", names[1]) - released_at < 2.0  # both move at once, the lock free


@pytest.mark.slow
def test_nothing_but_a_lookup_takes_the_lock_between_two_turns(cfg, tmp_path):
    config, log = config_file(cfg, tmp_path), tmp_path / "lane.log"
    go = {name: tmp_path / f"go-{name}" for name in ("bulk", "asked", "a", "b")}
    lock = cfg.state_dir / _common.LOCK_NAME
    with processes() as started:
        with another_caracole(cfg):
            started += [start(WAITER, config, log, "bulk", "bulk", go=go["bulk"]),
                        start(WAITER, config, log, "asked", "asked", go=go["asked"]),
                        start(TURNS, config, log, "a", 10, go=go["a"]),
                        start(TURNS, config, log, "b", 10, go=go["b"])]
            bulk, asked, a, b = started
            for name in go:
                wait_for(log, "ready", name)
            go["bulk"].touch()
            assert waiting_for(lock, lambda: bulk.poll() is None)  # blocked on the lock: no ticket exists yet
            assert not _common.lookups_waiting(cfg)
            go["asked"].touch()
            assert until(lambda: _common.lookups_waiting(cfg), lambda: asked.poll() is None)  # its ticket
            assert not _common.lane_tickets(cfg)
            go["a"].touch()
            go["b"].touch()
            assert until(lambda: len(_common.lane_tickets(cfg)) == 2,
                         lambda: a.poll() is None and b.poll() is None)
        # the lock let go: the lane's two first, by turns, then the others
        assert all(p.wait(60) == 0 for p in started), (tmp_path / "lane.log.err").read_text()
    lane_over = max(r.t for r in records(log) if r.word == "end")
    got = [r for r in records(log) if r.word == "got"]
    assert len([r for r in records(log) if r.word == "turn"]) == 20
    assert sorted(r.name for r in got) == ["asked", "bulk"] and all(r.t > lane_over for r in got)


@pytest.mark.slow
def test_a_lookup_killed_holding_the_lock_leaves_it_to_the_next_in_the_lane(cfg, tmp_path):
    config, log = config_file(cfg, tmp_path), tmp_path / "lane.log"
    go = {name: tmp_path / f"go-{name}" for name in ("a", "bulk", "b")}
    lock = cfg.state_dir / _common.LOCK_NAME
    with processes() as started:
        started += [start(HOLD, config, log, "a", go=go["a"]),
                    start(WAITER, config, log, "bulk", "bulk", go=go["bulk"]),
                    start(TURNS, config, log, "b", 2, go=go["b"])]
        a, bulk, b = started
        for name in go:
            wait_for(log, "ready", name)
        go["a"].touch()
        wait_for(log, "holding", "a")
        go["bulk"].touch()
        assert waiting_for(lock, lambda: bulk.poll() is None)  # blocked on the lock: no ticket exists yet
        assert not _common.lookups_waiting(cfg)
        go["b"].touch()
        assert until(lambda: _common.lane_tickets(cfg), lambda: b.poll() is None)  # b waits in the lane
        a.kill()
        killed_at = time.time()
        assert wait_for(log, "turn", "b") - killed_at < 2.0  # the next in the lane, at once
        assert wait_for(log, "got", "bulk") > wait_for(log, "end", "b")  # then the caracole outside it
        assert b.wait(30) == 0 and bulk.wait(30) == 0, (tmp_path / "lane.log.err").read_text()
    assert not _common.lookups_waiting(cfg)
