"""Seeing a caracole wait for caracole's lock, rather than only giving it time to finish.

A test holding the lock used to start a command, give it half a second (three for a process of
its own), and call it waiting if it hadn't finished. Linux lists every flock request that waits
in /proc/locks, so the test can see the command blocked on the lock as soon as it gets there.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

LOCKS = Path("/proc/locks")


def waiting_for(lock: Path, running: Callable[[], bool], timeout: float = 0.5) -> bool:
    """Whether a command waits for the flock on ``lock``: true once /proc/locks lists a request
    for it waiting, else whether ``running()`` still holds ``timeout`` seconds later (all a test
    could tell before, and all it can where /proc/locks says nothing)."""
    st = os.stat(lock)
    file = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and running():
        if _blocked(file):
            return True
        time.sleep(0.005)
    return running()


def _blocked(file: str) -> bool:
    """Whether /proc/locks lists a blocked flock request on ``file`` (major:minor:inode).

    A line reads "3: -> FLOCK  ADVISORY  WRITE 4242 00:26:99373 0 EOF": "->" for a request
    that waits, then the file.
    """
    try:
        listed = LOCKS.read_text()
    except OSError:
        return False
    for line in listed.splitlines():
        fields = line.split()
        if len(fields) > 6 and fields[1:3] == ["->", "FLOCK"] and fields[6] == file:
            return True
    return False
