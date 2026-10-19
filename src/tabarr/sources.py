"""What every song source shares: its result, and the repository calls it makes.

Two sources feed the song table. ``wanted.txt`` is always available; Spotify is
optional. Each sync hands its songs to ``songs.upsert_song``, which merges a song
that arrives from several sources into one record. The repository functions are
injected, so a source can be tested without a database; by default they are
imported from ``tabarr.songs`` and ``tabarr.db`` on first use.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence


@dataclass
class SyncStats:
    """What one sync of one source did.

    ``seen`` counts distinct songs read, ``new`` the ones the repository created.
    ``errors`` are messages for the run report; nothing in them is fatal.
    ``line_errors`` repeats wanted.txt's bad lines as ``(line_no, message)``.
    ``missing_playlists`` lists configured Spotify playlists that couldn't be read.
    """

    seen: int = 0
    new: int = 0
    errors: list[str] = field(default_factory=list)
    missing_playlists: list[str] = field(default_factory=list)
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
    from tabarr.songs import upsert_song

    return upsert_song


def default_kv_get() -> KvGet:
    """``db.kv_get``, imported on first use."""
    from tabarr.db import kv_get

    return kv_get


def default_kv_set() -> KvSet:
    """``db.kv_set``, imported on first use."""
    from tabarr.db import kv_set

    return kv_set


def utc_stamp(now: datetime) -> str:
    """``now`` as ISO 8601 UTC to the second ("2026-10-18T03:30:00Z"). Naive times are UTC."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
