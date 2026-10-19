"""LaCuerda in the nightly run: chord sheets for Spanish songs (plan §4, amendment A6).

UG lists every artist with an accented name only by bare ids, but a LaCuerda
artist URL can be built from the name. A song is tried when it isn't ignored,
has no complete human sheet, looks Spanish, and LaCuerda hasn't answered for it
in the last 30 days (``songs.lacuerda_checked_at``). Per song:

1. **The artist page.** Its slugs are tried best guess first; a 404, or
   LaCuerda's HTTP 200 "aqui llega:" body, moves on to the next. The page is
   cached for 30 days, so one fetch serves every song by the artist.
2. **The version.** The title is matched against the page's list, and the best
   "acordes" (Letra y Acordes) version is fetched; version pages are cached
   forever. No artist page, no matching title, no acordes version or a version
   that is gone is a miss, asked again after 30 days.
3. **Keeping it.** The sheet's coverage of the song's lyrics decides: it is kept
   as ``sheet.txt`` and ``sheet.json`` when no sheet is kept, when it is
   complete and the kept one isn't, or when neither is complete and it covers
   more. A complete sheet also replaces the auto-chords sheet.

Errors are never misses: a page that doesn't parse, or any other provider
error, leaves the song to be tried again next run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tabarr import coverage
from tabarr.config import RankPolicy
from tabarr.http import (
    BudgetExhausted,
    Client,
    ProviderBlocked,
    ProviderError,
    ProviderUnavailable,
    Response,
)
from tabarr.lacuerda import (
    PROVIDER,
    LCSong,
    artist_slug_candidates,
    artist_url,
    best_acordes_version,
    is_missing_artist_page,
    looks_spanish,
    match_title,
    parse_artist_page,
    parse_version_page,
    version_url,
)
from tabarr.library import drop_file, keep_file, kept_files, write_info
from tabarr.lyrics import song_lyrics
from tabarr.normalize import clean_title
from tabarr.overrides import Overrides
from tabarr.songs import SHEET_FILE_NAMES, Song, get_song, list_songs, refresh_status, update_song
from tabarr.ug.page import strip_markup
from tabarr.versions import VersionRow, get_version, set_coverage, set_picks, upsert_version

log = logging.getLogger(__name__)

ARTIST_PAGE_MAX_AGE = timedelta(days=30)
RECHECK_AFTER = timedelta(days=30)
_ACCEPT = (200, 404)  # a 404 is an answer: no such artist, or no such version
HUMAN_SHEET, AUTO_SHEET = SHEET_FILE_NAMES  # "sheet.txt", "sheet (auto).txt"
# Every kind the sheet slot holds; keeping a sheet makes it the slot's only pick.
SHEET_KINDS = ("chords", "acordes", "auto")


@dataclass
class LaCuerdaStats:
    """What one ``lacuerda_sheets`` pass did. ``tried`` counts misses and errors too."""

    tried: int = 0
    kept: int = 0
    missing: int = 0
    errors: int = 0
    budget_exhausted: bool = False


def lacuerda_sheets(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    rank: RankPolicy,
    now: datetime,
    *,
    overrides: Overrides | None = None,
) -> LaCuerdaStats:
    """Ask LaCuerda for the songs that need a sheet, newest first, and keep what helps.

    See the module docstring for which songs are tried and when a sheet is kept.
    With ``overrides``, songs ignored there since the last match are skipped too,
    and a sheet you pinned is never replaced.

    ``ProviderBlocked`` propagates. ``BudgetExhausted`` ends the pass
    (``budget_exhausted``), and so does a client that gives up on LaCuerda for
    this run (``ProviderUnavailable``). Any other ``ProviderError``, parse errors
    included, counts in ``errors`` and leaves the song for the next run.
    """
    stats = LaCuerdaStats()
    stamp = _stamp(now)
    for song in _songs_to_try(conn, rank, now, overrides):
        try:
            sheet = _find_sheet(client, song.artists[0], song.title, now)
        except ProviderBlocked:
            raise
        except BudgetExhausted:
            stats.budget_exhausted = True
            break
        except ProviderUnavailable as e:
            log.warning("LaCuerda is unavailable for the rest of this run: %s", e)
            break
        except ProviderError as e:
            stats.tried += 1
            stats.errors += 1
            log.warning("LaCuerda for %s: %s", song.display, e)
            continue
        stats.tried += 1
        if sheet is None:
            stats.missing += 1
            update_song(conn, song.id, lacuerda_checked_at=stamp)
        elif _record(conn, library_dir, rank, song, sheet, stamp):
            stats.kept += 1
    return stats


# --- which songs ---------------------------------------------------------------------


def _songs_to_try(
    conn: sqlite3.Connection, rank: RankPolicy, now: datetime, overrides: Overrides | None
) -> list[Song]:
    """Songs worth asking LaCuerda about, newest first.

    Not ignored; no kept human sheet that is complete or that you pinned; probably
    Spanish (the lyrics decide when there are any, else the title); an artist name
    a slug can be built from; and not asked about in the last 30 days.
    """
    cutoff = _utc(now) - RECHECK_AFTER
    ignored = overrides.ignore if overrides is not None else frozenset()
    songs = []
    for song in list_songs(conn):
        recent = not _before(song.lacuerda_checked_at, cutoff)
        if song.status == "ignored" or song.key in ignored or recent:
            continue
        kept = _kept_sheet(conn, song.id)
        if kept is not None and (_complete(kept.coverage, rank) or _pinned(overrides, song, kept)):
            continue
        lyrics = song_lyrics(song)
        if not looks_spanish(clean_title(song.title), lyrics.plain if lyrics is not None else None):
            continue
        if artist_slug_candidates(song.artists[0]):
            songs.append(song)
    return songs


def _kept_sheet(conn: sqlite3.Connection, song_id: int) -> VersionRow | None:
    """The version kept as the song's ``sheet.txt`` (UG's or LaCuerda's), if any."""
    for f in kept_files(conn, song_id):
        if f.name == HUMAN_SHEET:
            return get_version(conn, f.version_id)
    return None


def _pinned(overrides: Overrides | None, song: Song, kept: VersionRow) -> bool:
    """Whether the kept sheet is a UG tab you pinned for the song in overrides.toml."""
    if overrides is None or kept.provider != "ug" or not kept.tab_id.isdigit():
        return False
    return int(kept.tab_id) in overrides.pin.get(song.key, ())


# --- asking LaCuerda --------------------------------------------------------------------


@dataclass(frozen=True)
class _Sheet:
    """LaCuerda's best "acordes" version of a song, as fetched."""

    artist: str  # the artist slug that answered
    song: LCSong
    version: int
    url: str
    markup: str  # UG markup: chords in [ch]…[/ch]

    @property
    def tab_id(self) -> str:
        return f"{self.artist}/{self.song.slug}-{self.version}"


def _find_sheet(client: Client, artist: str, title: str, now: datetime) -> _Sheet | None:
    """The best "acordes" version LaCuerda has of a song, or None when it has none."""
    found = _artist_songs(client, artist, now)
    if found is None:
        return None
    slug, songs = found
    lc_song = match_title(songs, title)
    n = best_acordes_version(lc_song) if lc_song is not None else None
    if lc_song is None or n is None:
        return None
    url = version_url(slug, lc_song.slug, n)
    resp = client.get(url, accept=_ACCEPT)
    if resp.status == 404:
        return None  # listed by a cached artist page, since removed
    return _Sheet(slug, lc_song, n, url, parse_version_page(resp.text, url=url))


def _artist_songs(client: Client, artist: str, now: datetime) -> tuple[str, list[LCSong]] | None:
    """The first artist page LaCuerda has among the artist's slugs, with its songs.

    A 404, or LaCuerda's HTTP 200 "aqui llega:" body, means no artist by that
    slug: the next slug is tried. None when no slug has a page.
    """
    for slug in artist_slug_candidates(artist):
        url = artist_url(slug)
        resp = client.get(url, accept=_ACCEPT, max_age=ARTIST_PAGE_MAX_AGE)
        if _stale(resp, now):
            # PoliteClient serves a copy past max_age only once the budget is spent.
            # It is no answer for today: stop as the next request would have.
            raise BudgetExhausted(PROVIDER)
        if resp.status == 404 or is_missing_artist_page(resp.text):
            continue
        return slug, parse_artist_page(resp.text, url=url)
    return None


def _stale(resp: Response, now: datetime) -> bool:
    """Whether a cached artist page is older than ``ARTIST_PAGE_MAX_AGE``."""
    if not resp.from_cache or not resp.fetched_at:
        return False
    fetched = datetime.strptime(resp.fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return _utc(now) - fetched > ARTIST_PAGE_MAX_AGE


# --- keeping the sheet -------------------------------------------------------------------


def _record(
    conn: sqlite3.Connection, library_dir: Path, rank: RankPolicy, song: Song, sheet: _Sheet,
    stamp: str,
) -> bool:
    """Record LaCuerda's version with its coverage; keep it if it beats the kept sheet.

    The sheet already kept, met again, is only rescored: the lyrics may have
    arrived since. Returns whether the sheet was kept now.
    """
    lyrics = song_lyrics(song)
    lines = coverage.lyric_lines(lyrics.plain) if lyrics is not None else []
    value = coverage.coverage(sheet.markup, lines, line_match=rank.line_match)
    kept = _kept_sheet(conn, song.id)
    vid = upsert_version(
        conn, provider=PROVIDER, tab_id=sheet.tab_id, song_id=song.id, slot="sheet", kind="acordes",
        rating=0, votes=0, version=sheet.version, label=None, url=sheet.url,
        raw={"lcd": sheet.song.lcd, "title": sheet.song.title}, now=stamp,
    )
    set_coverage(conn, vid, value)
    already_kept = kept is not None and kept.id == vid
    keep = kept is None or (not already_kept and _better(value, kept.coverage, rank))
    if keep:
        _keep(conn, library_dir, song, vid, sheet, complete=_complete(value, rank))
    update_song(conn, song.id, lacuerda_checked_at=stamp)
    if keep or already_kept:  # info.json lists the kept sheet's coverage
        write_info(conn, library_dir, get_song(conn, song.id))
    return keep


def _better(value: float | None, kept: float | None, rank: RankPolicy) -> bool:
    """Whether a sheet covering ``value`` of the lyrics beats a kept one covering ``kept``.

    A complete sheet beats one that isn't; of two partial sheets, the one that
    covers more wins. An unknown coverage is never complete, and never shown to
    be smaller than a partial sheet's, so a partial sheet doesn't replace it.
    """
    if _complete(kept, rank):
        return False
    if _complete(value, rank):
        return True
    return value is not None and kept is not None and value > kept


def _keep(
    conn: sqlite3.Connection, library_dir: Path, song: Song, version_id: int, sheet: _Sheet, *,
    complete: bool,
) -> None:
    """Keep the sheet as ``sheet.txt`` (no markup) and ``sheet.json``, and pick it for the slot.

    ``sheet.json`` goes first: ``sheet.txt`` is what makes the song found. A
    complete sheet replaces the auto-chords sheet, which only stands in for a
    human sheet until one covers the lyrics.
    """
    doc = {
        "provider": PROVIDER, "url": sheet.url, "content": sheet.markup, "version": sheet.version,
    }
    files = {
        "sheet.json": json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        HUMAN_SHEET: strip_markup(sheet.markup),
    }
    for name, text in files.items():
        keep_file(conn, library_dir, song=song, version_id=version_id, name=name,
                  data=text.encode("utf-8"), rank=1)
    if complete:
        drop_file(conn, library_dir, song=song, name=AUTO_SHEET)
    set_picks(conn, song.id, SHEET_KINDS, [version_id])
    refresh_status(conn, song.id, ignored=False)


# --- small helpers -----------------------------------------------------------------------


def _complete(value: float | None, rank: RankPolicy) -> bool:
    return value is not None and value >= rank.coverage_threshold


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _stamp(now: datetime) -> str:
    """``now`` as stored in ``songs.lacuerda_checked_at``; naive times are UTC."""
    return _utc(now).strftime("%Y-%m-%dT%H:%M:%SZ")


def _before(stamp: str | None, cutoff: datetime) -> bool:
    """Whether a stored time is older than ``cutoff``; a missing or unreadable one is."""
    try:
        return stamp is None or _utc(datetime.fromisoformat(stamp)) < cutoff
    except ValueError:
        return True
