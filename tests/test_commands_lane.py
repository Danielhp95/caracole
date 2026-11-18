"""The lane at caracole's lock (commands/_common.py): lookups taking turns, and everyone else waiting for an
empty lane."""

from __future__ import annotations

import fcntl
import os
import threading
import time
from collections.abc import Callable

import pytest
from helpers.locks import waiting_for

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
