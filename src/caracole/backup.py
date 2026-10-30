"""Whole copies of the database, kept beside it: the nightly run's last step, ``caracole backup``, and the copy
``caracole index merge`` makes before it changes anything.

The indexes cost days of polite requests to build (UG's sitemaps, LaCuerda's listings, harptabs.com's artist
pages, gametabs.net's game pages), and the database holds them alone. A copy is
``state_dir/backups/caracole-<UTC time>.sqlite`` (``caracole-<UTC time>-before-merge.sqlite``, a merge's), made
with SQLite's ``VACUUM INTO`` on the connection given: one read transaction, so the copy is the database as it
stood when it began, whatever another connection commits meanwhile (WAL), and compacted. It is written under a
name of its own (``.part``), checked (``PRAGMA quick_check``), made 0600, and only then renamed; then the copies
beyond the newest ``KEEP`` go, so a copy cut short or failing its check never costs a good one. When the disk
lacks room for it (``needed``: the database's pages in use, and ``HEADROOM``), no copy is made and nothing is
deleted: ``Skipped`` says why, and the log warns. The folder is 0700: the database is caracole's alone, never
the synced library's. Its callers hold caracole's lock (``_common.exclusive``), so one copy is made at a time.
Restoring one is docs/deploy.md's. The standard library alone.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import disk_usage

log = logging.getLogger(__name__)

FOLDER = "backups"  # in the state directory
KEEP = 3  # the copies kept: about 430 MB each for the owner's database
HEADROOM = 64 * 1024 * 1024  # bytes left free on the disk once a copy is made, at least
MERGE = "before-merge"  # the label of the copy a merge makes first
_NAME = re.compile(r"caracole-(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})(\d{2})Z(?:-([a-z][a-z-]*))?\.sqlite")


class BackupError(Exception):
    """A copy that couldn't be made whole: SQLite's error, or its check's words."""


@dataclass(frozen=True)
class Backup:
    """A copy in the folder: its path, when it was made (by its name), its label (``MERGE``, or None) and size."""

    path: Path
    at: datetime
    label: str | None
    size: int


@dataclass(frozen=True)
class Made:
    """A copy made: it, the older copies deleted to keep ``kept``, and how long it took."""

    backup: Backup
    deleted: tuple[Path, ...]
    kept: int
    seconds: float


@dataclass(frozen=True)
class Skipped:
    """No copy, for lack of room: why, in words, and the bytes it needs and the disk has free."""

    reason: str
    needed: int
    free: int


def folder(state_dir: Path) -> Path:
    return state_dir / FOLDER


def name_of(at: datetime, label: str | None = None) -> str:
    """A copy's file name: ``caracole-2026-10-29T034512Z.sqlite``, with ``-<label>`` before the suffix."""
    return f"caracole-{at.astimezone(UTC).strftime('%Y-%m-%dT%H%M%SZ')}{'-' + label if label else ''}.sqlite"


def backups(state_dir: Path) -> list[Backup]:
    """The copies in the folder, oldest first, by their names alone: a file of another name is no copy."""
    try:
        entries = list(os.scandir(folder(state_dir)))
    except OSError:
        return []
    found = []
    for entry in entries:
        named = _NAME.fullmatch(entry.name)
        if named is None or not entry.is_file(follow_symlinks=False):
            continue
        at = datetime(*map(int, named.groups()[:6]), tzinfo=UTC)
        found.append(Backup(Path(entry.path), at, named.group(7), entry.stat(follow_symlinks=False).st_size))
    return sorted(found, key=lambda b: (b.at, b.path.name))


def needed(conn: sqlite3.Connection) -> int:
    """The room a copy needs: the database's pages in use (``VACUUM INTO`` leaves the free ones out), and
    ``HEADROOM``, so that the nightly run after it still finds room to write."""
    pages, unused, size = (conn.execute(f"PRAGMA {p}").fetchone()[0]
                           for p in ("page_count", "freelist_count", "page_size"))
    return (pages - unused) * size + HEADROOM


def make(conn: sqlite3.Connection, state_dir: Path, now: datetime, *, label: str | None = None,
         keep: int = KEEP) -> Made | Skipped:
    """A whole copy of the database ``conn`` is open on, then the newest ``keep`` kept (see the module docstring).
    ``conn`` must be in no transaction. ``Skipped`` when the disk lacks room; ``BackupError`` when the copy
    can't be made or fails its check, which leaves every copy there was."""
    started = time.monotonic()
    where = folder(state_dir)
    where.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(where, 0o700)
    for stale in where.glob("caracole-*.part"):  # what a copy cut short left
        stale.unlink(missing_ok=True)
    need, free = needed(conn), disk_usage(where).free
    if free < need:
        reason = (f"no room for a copy of the database in {where}: it needs {size_text(need)} and the disk has "
                  f"{size_text(free)} free; the copies there stay as they are")
        log.warning("No backup: %s.", reason)
        return Skipped(reason, need, free)
    target = where / name_of(now, label)
    part = where / f"{target.name}.{secrets.token_hex(6)}.part"
    try:
        conn.execute("VACUUM INTO ?", (str(part),))
        os.chmod(part, 0o600)
        problem = _check(part)
        if problem is not None:
            raise BackupError(f"the copy failed its check: {problem}")
        os.replace(part, target)
    except sqlite3.Error as e:
        raise BackupError(f"the copy couldn't be made: {e}") from e
    finally:
        part.unlink(missing_ok=True)
    copy = Backup(target, now.astimezone(UTC).replace(microsecond=0), label, target.stat().st_size)
    deleted = _rotate(state_dir, keep, copy)
    made = Made(copy, deleted, min(keep, len(backups(state_dir))), time.monotonic() - started)
    log.info("Backed up the database to %s (%s) in %.1f s; %d kept%s.", target, size_text(copy.size), made.seconds,
             made.kept, f", {len(deleted)} older deleted" if deleted else "")
    return made


def _check(path: Path) -> str | None:
    """None when SQLite's quick check finds the copy whole, else what it says."""
    check = sqlite3.connect(path)
    try:
        said = [row[0] for row in check.execute("PRAGMA quick_check")]
    finally:
        check.close()
    return None if said == ["ok"] else "\n".join(map(str, said))


def _rotate(state_dir: Path, keep: int, made: Backup) -> tuple[Path, ...]:
    """Delete the copies beyond the newest ``keep``, never the one just made; the paths deleted, oldest first."""
    every = backups(state_dir)
    old = [b for b in every if b.path != made.path][: max(0, len(every) - max(keep, 1))]
    for b in old:
        b.path.unlink(missing_ok=True)
    return tuple(b.path for b in old)


def size_text(n: int) -> str:
    """Bytes as people read them: "412 MB", "64 KB"."""
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= scale:
            return f"{n / scale:.1f}".removesuffix(".0") + f" {unit}"
    return f"{n} bytes"

