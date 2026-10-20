"""Song sources: what they share, and ``sync_sources``, which runs them all.

Two sources feed the song table. ``wanted.txt`` is always available; Spotify is
optional. Each sync hands its songs to ``songs.upsert_song``, which merges a song
that arrives from several sources into one record, with the album and duration
your wanted.txt line gives now, else Spotify's. The repository functions are
injected, so a source can be tested without a database; by default they are
imported from ``caracole.songs`` and ``caracole.db`` on first use.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from caracole.config import Config

if TYPE_CHECKING:
    from caracole.spotify import SpotifyAPI

# Where sync_sources records how each source went, as JSON, for the to-do page.
WANTED_STATUS_KEY = "source:wanted"
SPOTIFY_STATUS_KEY = "source:spotify"
# Until when Spotify asked caracole to wait after an HTTP 429 (ISO 8601 UTC); not asked before.
SPOTIFY_RETRY_KEY = "spotify:retry_after_until"


@dataclass
class SyncStats:
    """What one sync of one source did.

    ``seen`` counts distinct songs read, ``new`` the ones the repository created.
    ``errors`` are messages for the run report; nothing in them is fatal.
    ``line_errors`` repeats wanted.txt's bad lines as ``(line_no, message)``.
    ``missing_playlists`` lists configured Spotify playlists that couldn't be read.
    ``retry_after_until`` is when Spotify's rate limit lets caracole ask again
    (ISO 8601 UTC), when a sync stopped at one that said how long to wait.
    ``removed`` counts the songs you removed (``caracole remove``) that the
    source still lists and that stayed out (``songs.SongRemoved``); ``seen``
    leaves them out.
    """

    seen: int = 0
    new: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)
    missing_playlists: list[str] = field(default_factory=list)
    line_errors: list[tuple[int, str]] = field(default_factory=list)
    retry_after_until: str | None = None


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


def utc_stamp(now: datetime) -> str:
    """``now`` as ISO 8601 UTC to the second ("2026-10-18T03:30:00Z"). Naive times are UTC."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SourcesReport:
    """How one ``sync_sources`` went.

    ``spotify_state`` is "off" (not configured), "ok", "setup_needed" (configured
    in part, such as without its client secret), "auth_needed" or "error".
    ``spotify_message`` says what went wrong; for "auth_needed" it leaves out the
    advice to run ``caracole auth spotify``, which callers add where they show it.
    For "setup_needed" that advice would not help: the message says what to set.
    """

    wanted: SyncStats
    spotify: SyncStats | None = None
    spotify_state: str = "off"
    spotify_message: str | None = None

    def summary(self) -> str:
        """One line for the run report and ``caracole sync``; the lines' problems aren't in it."""
        w = self.wanted
        line = f"wanted.txt {_count(w.seen, 'song')}, {w.new} new"
        if w.errors:
            line += f", {_count(len(w.errors), 'problem')}"
        parts = [line]
        if self.spotify_state == "off":
            parts.append("Spotify off")
        elif self.spotify_state == "auth_needed":
            parts.append("Spotify needs authorization (run `caracole auth spotify`)")
        elif self.spotify_state == "setup_needed":
            line = "Spotify isn't fully set up"
            parts.append(f"{line} ({self.spotify_message})" if self.spotify_message else line)
        else:
            s = self.spotify
            line = (
                f"Spotify {_count(s.seen, 'song')}, {s.new} new"
                if s is not None
                else "Spotify failed"
            )
            if s is not None and s.removed:
                line += f", {_count(s.removed, 'removed song')} left out"
            if self.spotify_state == "error" and self.spotify_message:
                line += f" ({self.spotify_message})"
            parts.append(line)
        return "; ".join(parts)


def sync_sources(
    conn: sqlite3.Connection,
    cfg: Config,
    now: datetime,
    *,
    spotify: SpotifyAPI | None = None,
    upsert: Upsert | None = None,
    kv_get: KvGet | None = None,
    kv_set: KvSet | None = None,
) -> SourcesReport:
    """Sync wanted.txt, then Spotify when it's configured, and record how each went.

    ``spotify`` is the client from ``spotify.client_from_config``, or None when
    there is none. wanted.txt always syncs, and no Spotify failure raises: it
    becomes the report's ``spotify_state``. Each source's outcome is stored as
    JSON in the kv table under "source:wanted" and "source:spotify". After a
    rate limit that said how long to wait, Spotify isn't asked until then
    (kv ``spotify:retry_after_until``).
    """
    from caracole.wanted import sync_wanted

    kv_get = kv_get or default_kv_get()
    kv_set = kv_set or default_kv_set()
    stamp = utc_stamp(now)
    wanted = sync_wanted(conn, cfg.wanted_file, now, upsert=upsert, kv_get=kv_get, kv_set=kv_set)
    if cfg.wanted_file.exists():  # before it exists, the to-do page says how to create it
        errors = [[n, m] for n, m in wanted.line_errors] or [[0, m] for m in wanted.errors]
        _record(
            kv_set,
            conn,
            WANTED_STATUS_KEY,
            {"at": stamp, "lines": wanted.seen, "new": wanted.new, "errors": errors},
        )
    report = SourcesReport(wanted=wanted)
    if not cfg.spotify.enabled:
        return report

    from caracole.spotify import (
        SpotifyAuthError,
        SpotifyError,
        SpotifySetupError,
        no_client_error,
        sync_spotify,
    )

    def needs(e: SpotifyAuthError) -> tuple[str, str]:
        state = "setup_needed" if isinstance(e, SpotifySetupError) else "auth_needed"
        return state, _sentence(e.problem)

    wait_until = _stamp_or_none(kv_get(conn, SPOTIFY_RETRY_KEY))
    if spotify is None:
        report.spotify_state, report.spotify_message = needs(no_client_error(cfg))
    elif wait_until and stamp < wait_until:
        report.spotify = SyncStats()
        report.spotify_state = "error"
        report.spotify_message = (
            f"Spotify asked caracole to wait until {wait_until} (HTTP 429); not asked before then"
        )
    else:
        try:
            report.spotify = sync_spotify(
                conn, spotify, cfg.spotify, now, upsert=upsert, kv_set=kv_set
            )
        except SpotifyAuthError as e:
            report.spotify_state, report.spotify_message = needs(e)
        except SpotifyError as e:
            report.spotify_state, report.spotify_message = "error", str(e)
        else:
            if report.spotify.retry_after_until:
                kv_set(conn, SPOTIFY_RETRY_KEY, report.spotify.retry_after_until)
            problems = list(report.spotify.errors)
            if missing := report.spotify.missing_playlists:
                names = ", ".join(repr(ref) for ref in missing)
                problems.insert(
                    0,
                    f"can't read playlist {names}: check the name, and that the "
                    "playlist is yours or you collaborate on it",
                )
            report.spotify_state = "error" if problems else "ok"
            report.spotify_message = "; ".join(problems) or None
    s = report.spotify
    _record(
        kv_set,
        conn,
        SPOTIFY_STATUS_KEY,
        {
            "state": report.spotify_state,
            "at": stamp,
            "seen": s.seen if s else 0,
            "new": s.new if s else 0,
            "message": report.spotify_message,
            "missing_playlists": list(s.missing_playlists) if s else [],
        },
    )
    return report


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _stamp_or_none(value: str | None) -> str | None:
    """``value`` when it is a ``utc_stamp``, so it compares in time order as a string."""
    try:
        datetime.strptime(value or "", "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return value


def _record(kv_set: KvSet, conn: sqlite3.Connection, key: str, value: Any) -> None:
    kv_set(conn, key, json.dumps(value, ensure_ascii=False))


def _sentence(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] + ("" if text.endswith(".") else ".")
