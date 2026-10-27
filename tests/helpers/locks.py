"""Seeing a caracole wait for caracole's lock, rather than only giving it time to finish.

A test holding the lock used to start a command, give it half a second (three for a process of
its own), and call it waiting if it hadn't finished: on a busy machine, one that hadn't got as far
as the lock yet, which then took it unhindered once the test let go. Linux lists every flock
request that waits in /proc/locks, so the test sees the command blocked on the lock once it gets
there, however long that takes; a lookup, which tries for the lock again and again rather than
blocking (``_common._wait_announced``), says it waits with a ticket in the lock's waiting folder.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

from caracole.commands._common import WAITING_DIR

LOCKS = Path("/proc/locks")
# Seconds a command may take to get to the lock: one neither waiting nor over by then is stuck before it.
CEILING = 60.0


def waiting_for(lock: Path, running: Callable[[], bool], timeout: float = 0.5) -> bool:
    """Whether a command waits for the flock on ``lock``: true once /proc/locks lists a request for
    it waiting, or a lookup's ticket in the lock's waiting folder says one waits; false once
    ``running()`` no longer holds, the command over without either (or neither after ``CEILING``
    seconds). Where /proc/locks can't be read, whether ``running()`` still holds ``timeout``
    seconds later: all a test can tell there."""
    inode = str(os.stat(lock).st_ino)
    tickets = lock.parent / WAITING_DIR
    readable = _listed() is not None
    deadline = time.monotonic() + (CEILING if readable else timeout)
    while time.monotonic() < deadline and running():
        if _blocked(inode) or _ticket(tickets):
            return True
        time.sleep(0.005)
    return not readable and running()


def _listed() -> str | None:
    try:
        return LOCKS.read_text()
    except OSError:
        return None


def _blocked(inode: str) -> bool:
    """Whether /proc/locks lists a blocked flock request on the file with this inode.

    A line reads "3: -> FLOCK  ADVISORY  WRITE 4242 00:26:99373 0 EOF": "->" for a request
    that waits, then the file as major:minor:inode. The device is its superblock's, which stat
    doesn't give on a btrfs subvolume, so only the inode is compared.
    """
    for line in (_listed() or "").splitlines():
        fields = line.split()
        if (len(fields) > 6 and fields[1:3] == ["->", "FLOCK"]
                and fields[6].rsplit(":", 1)[-1] == inode):
            return True
    return False


def _ticket(folder: Path) -> bool:
    """Whether a lookup waiting for the lock has its ticket in ``folder``."""
    try:
        return any(folder.iterdir())
    except OSError:
        return False
