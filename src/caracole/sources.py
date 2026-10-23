"""Song sources: what a source shares with the song repository, and ``sync_sources``, which runs them.

``wanted.txt`` is caracole's one source of songs (wanted.py). Its sync hands
each song to ``songs.upsert_song``, which keeps one record per song, with the
album and duration your line gives now. The repository functions are
injected, so a source can be tested without a database; by default they are
imported from ``caracole.songs`` and ``caracole.db`` on first use.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from caracole.config import Config
from caracole.logs import plural
from caracole.stamps import stamp as utc_stamp  # under its old name: wanted.py imports it

# Where sync_sources records how wanted.txt's sync went, as JSON, for the to-do page.
WANTED_STATUS_KEY = "source:wanted"


@dataclass
class SyncStats:
    """What one sync of one source did.

    ``seen`` counts distinct songs read, ``new`` the ones the repository created.
    ``errors`` are messages for the run report; nothing in them is fatal.
    ``line_errors`` repeats wanted.txt's bad lines as ``(line_no, message)``.
    """

    seen: int = 0
    new: int = 0
    errors: list[str] = field(default_factory=list)
    line_errors: list[tuple[int, str]] = field(default_factory=list)


class Upsert(Protocol):
    """``songs.upsert_song``: insert or merge a song, returning ``(song_id, created)``."""

    def __call__(
        self,
        conn: sqlite3.Connection,
        *,
        artists: Sequence[str],
        title: str,
        album: str | None,
        duration_ms: int | None,
        isrc: str | None,
        source: str,
        source_id: str,
        added_at: str,
    ) -> tuple[int, bool]: ...


KvGet = Callable[[sqlite3.Connection, str], str | None]
KvSet = Callable[[sqlite3.Connection, str, str], None]


def default_upsert() -> Upsert:
    """The song repository's ``upsert_song``, imported on first use."""
    from caracole.songs import upsert_song

    return upsert_song


def default_kv_get() -> KvGet:
    """``db.kv_get``, imported on first use."""
    from caracole.db import kv_get

    return kv_get


def default_kv_set() -> KvSet:
    """``db.kv_set``, imported on first use."""
    from caracole.db import kv_set

    return kv_set


@dataclass
class SourcesReport:
    """How one ``sync_sources`` went: wanted.txt's ``SyncStats``."""

    wanted: SyncStats

    def summary(self) -> str:
        """One line for the run report and ``caracole sync``; the lines' problems aren't in it."""
        w = self.wanted
        line = f"wanted.txt {plural(w.seen, 'song')}, {w.new} new"
        if w.errors:
            line += f", {plural(len(w.errors), 'problem')}"
        return line


def sync_sources(
    conn: sqlite3.Connection,
    cfg: Config,
    now: datetime,
    *,
    upsert: Upsert | None = None,
    kv_get: KvGet | None = None,
    kv_set: KvSet | None = None,
) -> SourcesReport:
    """Sync wanted.txt, and record how it went as JSON in the kv table under "source:wanted"."""
    from caracole.wanted import sync_wanted

    kv_get = kv_get or default_kv_get()
    kv_set = kv_set or default_kv_set()
    wanted = sync_wanted(conn, cfg.wanted_file, now, upsert=upsert, kv_get=kv_get, kv_set=kv_set)
    if cfg.wanted_file.exists():  # before it exists, the to-do page says how to create it
        errors = [[n, m] for n, m in wanted.line_errors] or [[0, m] for m in wanted.errors]
        _record(
            kv_set,
            conn,
            WANTED_STATUS_KEY,
            {"at": utc_stamp(now), "lines": wanted.seen, "new": wanted.new, "errors": errors},
        )
    return SourcesReport(wanted=wanted)


def _record(kv_set: KvSet, conn: sqlite3.Connection, key: str, value: Any) -> None:
    kv_set(conn, key, json.dumps(value, ensure_ascii=False))

