"""The library page's line in the log, one a build: what it put on the page, from which database, how fast.

caracole serve builds the page at each ``GET /`` (web/library_routes.py), and every command that changes what it
shows writes ``index.html`` (``todo.write_pages``). Each build logs one line, at information level, which the
journal keeps at the default verbosity (logs.py ``JOURNAL_INFO``), so ``journalctl -u caracole-web | grep 'library
page'`` says what every page served showed, and ``journalctl -u caracole`` what the nightly run wrote::

    library page served to lenovo:8737: 120 songs (100 found, 15 wanted, 5 ignored; 3 in review), 2 songbooks;
    database /var/lib/caracole/caracole.sqlite, 12,582,912 bytes, modified 2026-10-29T03:14:07Z; 0.84 s

(one line), "written to /var/lib/caracole/library/index.html" for the file. The owner asked for it after the page
showed no songs twice right after an upgrade, with no cause found. A page with no songs, and a database that can't
be opened or read, is a warning instead, with what tells why: the database's path, whether it was there before the
build opened it (opening a missing one makes a new, empty one), its size, time and owner, its WAL's size, its schema
version and its ``songs`` rows as the file holds them, the state and library folders, and the process's uid and gid.
The page is answered as ever all the same.

A build costs one stat of the database more; a warning, a read-only connection of its own, which neither creates
nor migrates the file (``PRAGMA user_version`` and ``COUNT(*)`` of ``songs``). The standard library alone.
"""

from __future__ import annotations

import grp
import logging
import os
import pwd
import sqlite3
import time
from collections import Counter
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from caracole.logs import plural
from caracole.stamps import stamp

if TYPE_CHECKING:
    from caracole.config import Config

log = logging.getLogger(__name__)


class PageBuild:
    """One build of the library page, ``how`` ("served" or "written") ``to`` whom or where: its clock and the
    database as it was when it began, then its line (``done``, or ``failed``)."""

    def __init__(self, cfg: Config, how: str, to: str):
        self.cfg, self.how, self.to = cfg, how, to
        self.started = time.monotonic()
        self.before = _stat(cfg.db_path)
        self.songs, self.held = 0, ""

    def note(self, data: Mapping[str, Any]) -> None:
        """What the page holds, from its data once whole (``library_page.build_library_page``'s ``note``)."""
        cards = data.get("songs") or []
        status = Counter(card.get("status") for card in cards)
        review = sum(1 for card in cards if card.get("review"))
        books = data.get("songbooks") or {}
        self.songs = len(cards)
        self.held = (f"{plural(len(cards), 'song')} ({status['found']} found, {status['wanted']} wanted, "
                     f"{status['ignored']} ignored; {review} in review), "
                     + ("songbooks.toml unreadable" if books.get("error")
                        else plural(len(books.get("books") or []), "songbook")))

    def done(self) -> None:
        """Log the line: what the page holds; a page with no songs, a warning that says what tells why."""
        if not self.songs:
            log.warning("library page %s to %s with no songs: %s", self.how, self.to, self._why())
            return
        log.info("library page %s to %s: %s; database %s; %s", self.how, self.to, self.held,
                 _described(self.cfg.db_path, _stat(self.cfg.db_path) or self.before, owner=False), self._took())

    def failed(self, error: BaseException) -> None:
        """Log a warning that the database can't be opened or read, with ``error`` and what tells why."""
        log.warning("library page %s to %s failed: the database can't be read (%s: %s): %s", self.how, self.to,
                    type(error).__name__, " ".join(str(error).split()), self._why())

    def _took(self) -> str:
        return f"{time.monotonic() - self.started:.2f} s"

    def _why(self) -> str:
        cfg, path = self.cfg, self.cfg.db_path
        now = _stat(path)
        if self.before is None:
            there = f"database {path} missing before this build opened it, now " + (
                _described(None, now) if now else "missing still")
        else:
            there = "database " + _described(path, now or self.before)
        wal = _stat(path.with_name(path.name + "-wal"))
        version, rows = _read(path)
        return (f"{there}; WAL {'none' if wal is None else f'{wal.st_size:,} bytes'}; schema version {version}; "
                f"songs table {rows}; state_dir {cfg.state_dir}; library_dir {cfg.library_dir}; "
                f"process uid {os.getuid()} gid {os.getgid()}; {self._took()}")


def _stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _described(path: Path | None, st: os.stat_result | None, *, owner: bool = True) -> str:
    """A file as the line names it: "/p, 12,582,912 bytes, modified 2026-10-29T03:14:07Z, owner caracole:caracole
    (991:991)"."""
    named = "" if path is None else f"{path}, "
    if st is None:
        return f"{named}missing"
    text = f"{named}{st.st_size:,} bytes, modified {stamp(datetime.fromtimestamp(st.st_mtime, UTC))}"
    if owner:
        text += f", owner {_name(pwd.getpwuid, st.st_uid)}:{_name(grp.getgrgid, st.st_gid)} ({st.st_uid}:{st.st_gid})"
    return text


def _name(lookup: Any, number: int) -> str:
    try:
        return lookup(number)[0]
    except (KeyError, OverflowError):  # a uid or gid no user or group has, as a file synced from elsewhere may have
        return str(number)


def _read(path: Path) -> tuple[str, str]:
    """The database's schema version and its ``songs`` rows, read straight from the file through a read-only
    connection, which never creates or migrates it: each a number, or why it can't be read."""
    if not path.exists():
        return "none (no file)", "none (no file)"
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)) as conn:
            version = str(conn.execute("PRAGMA user_version").fetchone()[0])
            try:
                rows = plural(conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0], "row")
            except sqlite3.Error as e:
                rows = f"unreadable ({e})"
    except sqlite3.Error as e:
        return f"unreadable ({e})", f"unreadable ({e})"
    return version, rows
