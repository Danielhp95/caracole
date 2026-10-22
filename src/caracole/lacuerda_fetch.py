"""LaCuerda in the nightly run: chord sheets for Spanish songs (plan §4, amendment A6).

UG lists every artist with an accented name only by bare ids, but a LaCuerda
artist URL can be built from the name. A song is tried when it isn't ignored,
has no complete human sheet, looks Spanish, and LaCuerda hasn't answered for it
in the last 30 days (``songs.lacuerda_checked_at``); or, whatever its sheet and
the date, when the library lost the LaCuerda sheet kept for it (deleted on a
synced device, cut short by a power cut), which is then written again. Per song:

1. **The artist page.** The slugs LaCuerda's listings give the artist's name
   (lacuerda_index.py) are tried first, then the slugs built from it, best
   guess first; a 404, or LaCuerda's HTTP 200 "aqui llega:" body, moves on to
   the next. The page is cached for 30 days, so one fetch serves every song by
   the artist, and its songs go into the index, for searches to suggest.
2. **The version.** The title is matched against the page's list, and the best
   "acordes" (Letra y Acordes) version is fetched; version pages are cached
   forever. No artist page, no matching title, no acordes version or a version
   that is gone is a miss, asked again after 30 days.
3. **Keeping it.** The sheet's coverage of the song's lyrics decides, by the
   rule UG's sheets go by too (``versions.replaces_sheet``): it is kept as
   ``sheet.txt`` and ``sheet.json`` when no sheet is kept, when it is complete
   and the kept one isn't, or when neither is complete and it covers more. A
   complete sheet also replaces the auto-chords sheet.

**Your pick.** A song you picked on LaCuerda (``[lacuerda]`` in overrides.toml,
which ``caracole get --lacuerda`` and ``caracole add --lacuerda`` write) is tried
whatever its language and its sheet until that sheet is the one kept, then never
again: the version you picked, its page alone, or the song's best "acordes"
version, which the index names when it holds the artist's page, else the artist
page does. It is kept whatever its coverage, in place of any sheet but one you
pinned on Ultimate Guitar (``[pin]``), and a miss waits 30 days as any does.
``read_artist_page`` reads one artist's page into the index, for caracole serve's
Songs of a LaCuerda artist (``caracole lacuerda --artist``).

**The most popular artists.** Once LaCuerda's listings are read whole, what the
sheets and the listings leave of the night's budget (LaCuerda's 30 requests)
reads the pages of the artists the listings count most songs of, a page not
read in 30 days, ``POPULAR_PAGES`` (10) a night at most (``popular_pages``), so
that their songs are in the index for searches; one the cache holds, younger,
is read from the cache.

Errors are never misses: a page that doesn't parse, or any other provider
error, leaves the song to be tried again next run. A cached page that doesn't
parse (a maintenance notice served with HTTP 200, say) is fetched once more
before it counts as an error, so one bad night isn't replayed from the cache.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from caracole import coverage, stamps
from caracole.config import RankPolicy
from caracole.http import (
    BudgetExhausted,
    Client,
    ProviderBlocked,
    ProviderError,
    ProviderUnavailable,
    Response,
    read_once_more,
    stale,
)
from caracole.lacuerda import (
    PROVIDER,
    LaCuerdaParseError,
    LCSong,
    artist_slug_candidates,
    artist_url,
    best_acordes_version,
    is_missing_artist_page,
    looks_spanish,
    match_title,
    parse_artist_name,
    parse_artist_page,
    parse_popularity,
    parse_version_page,
    version_url,
)
from caracole.lacuerda_index import artist_slugs, complete_at, store_artist_page, store_songs
from caracole.library import drop_file, holds, keep_file, kept_already, kept_files, write_info
from caracole.lyrics import song_lyrics
from caracole.normalize import clean_title
from caracole.overrides import LaCuerdaPick, Overrides, OverridesError
from caracole.provider_pass import PassStats, each_song
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, get_song, list_songs, refresh_status, update_song
from caracole.ug.page import strip_markup
from caracole.versions import (
    SHEET_KINDS,
    VersionRow,
    complete,
    get_version,
    replaces_sheet,
    set_coverage,
    set_picks,
    upsert_version,
)

log = logging.getLogger(__name__)

ARTIST_PAGE_MAX_AGE = timedelta(days=30)
RECHECK_AFTER = timedelta(days=30)
POPULAR_PAGES = 10  # the most popular artists' pages a night reads, of what the sheets and listings leave
POPULAR_SCAN = 2000  # the most popular artists it looks among for a page not read in 30 days
_ACCEPT = (200, 404)  # a 404 is an answer: no such artist, or no such version
SHEET_DOCS = ("sheet.json", HUMAN_SHEET)  # what keeping a sheet writes, in that order
_SLUG = re.compile(r"[a-z0-9_]+")  # an artist's name written as LaCuerda's slug of their page


@dataclass
class LaCuerdaStats(PassStats):
    """What one ``lacuerda_sheets`` pass did: ``tried`` (misses and errors too), ``errors`` and
    ``failures`` as every pass counts them (provider_pass.py), the sheets kept and the misses."""

    kept: int = 0
    missing: int = 0


def lacuerda_sheets(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    rank: RankPolicy,
    now: datetime,
    *,
    overrides: Overrides | None = None,
    reload_overrides: Callable[[], Overrides] | None = None,
    only: Collection[int] | None = None,
) -> LaCuerdaStats:
    """Ask LaCuerda for the songs that need a sheet, newest first, and keep what helps.

    See the module docstring for which songs are tried and when a sheet is kept.
    With ``overrides``, songs ignored there since the last match are skipped too,
    and a sheet you pinned is never replaced. ``only``: the ids of the songs that
    may be tried (a lookup's one song), when the rules above would try them.

    The nightly run's client hands caracole's lock to a waiting lookup in its pauses
    (``handoffs``, commands/_common.py), and the lookup may pin a tab, pick a LaCuerda
    sheet or keep one: after a handoff, overrides.toml is read again
    (``reload_overrides``; the copy read before when it can't be), and each song is
    read again before its turn and passed over when it is no longer one to try. A
    handoff in the pauses of a song's own turn reads both again before what LaCuerda
    answered is recorded: unless the song is still one to try, with the pick the turn
    asked for, the answer is left unrecorded (in the HTTP cache), and the song as the
    lookup left it.

    Errors are never misses (provider_pass.py): ``ProviderBlocked`` propagates.
    ``BudgetExhausted`` ends the pass (``budget_exhausted``), and so does a client
    that gives up on LaCuerda for this run (``ProviderUnavailable``). Any other
    ``ProviderError``, parse errors included, counts in ``errors`` and leaves the
    song for the next run.
    """
    stats = LaCuerdaStats()
    stamp = stamps.stamp(now)
    fetched: set[str] = set()  # URLs fetched from LaCuerda in this pass
    lookups = _Lookups(client, overrides, reload_overrides)

    def turn(song: Song) -> tuple[LaCuerdaPick | None, _Sheet | None]:
        """The pick the turn asked for, and what LaCuerda answered."""
        pick = lookups.picks.get(song.key)
        if pick is not None:
            return pick, _picked_sheet(conn, client, pick, song, now, fetched)
        return None, _find_sheet(conn, client, song.artists[0], song.title, now, fetched)

    def still_to_try(song: Song) -> Song | None:
        """The song as it is now, when LaCuerda is still worth asking about it."""
        try:
            fresh = get_song(conn, song.id)
        except KeyError:  # merged into another song, or removed, meanwhile
            return None
        return fresh if _to_try(conn, library_dir, rank, now, lookups.overrides, fresh) else None

    def songs() -> Iterator[Song]:
        """The songs to try, each just before its turn, as it is then after a handoff."""
        for song in _songs_to_try(conn, library_dir, rank, now, overrides):
            if only is not None and song.id not in only:
                continue
            lookups.look()
            if lookups.since:
                fresh = still_to_try(song)
                if fresh is None:
                    continue
                song = fresh
            yield song

    for song, (pick, sheet) in each_song(songs(), stats, turn, site="LaCuerda"):
        if lookups.look():  # a lookup went first in a pause of this very turn
            fresh = still_to_try(song)
            if fresh is None or lookups.picks.get(fresh.key) != pick:
                continue
            song = fresh
        if sheet is None:
            stats.missing += 1
            update_song(conn, song.id, lacuerda_checked_at=stamp)
        elif _record(conn, library_dir, rank, song, sheet, stamp, picked=pick is not None):
            stats.kept += 1
    return stats


def read_artist_page(conn: sqlite3.Connection, client: Client, artist: str, now: datetime) -> tuple[str, int] | None:
    """One artist's page into the index (``lacuerda_index.store_songs``), as caracole serve's Songs of a
    LaCuerda artist asks for it: under ``artist`` first when it is written as a slug (``soda_stereo``),
    then under the slugs for that name, as the step tries them (the listings' first). Returns the slug
    that answered and the songs its page lists (each once); None when LaCuerda has no page by any of them.
    The page is cached for 30 days, as the step's are. Provider errors propagate."""
    found = _artist_songs(conn, client, artist, now, set(), first=[artist] if _SLUG.fullmatch(artist) else [])
    return (found[0], len({s.slug for s in found[1]})) if found is not None else None


@dataclass
class PopularStats:
    """What one ``popular_pages`` pass did: the artist pages it asked LaCuerda for, the errors among them, and
    whether it stopped at the budget."""

    read: int = 0
    errors: int = 0
    budget_exhausted: bool = False


def popular_pages(conn: sqlite3.Connection, client: Client, now: datetime, *,
                  limit: int = POPULAR_PAGES) -> PopularStats:
    """The pages of the most popular artists, by the songs LaCuerda's listings count, into the index, once the
    listings are read whole: each one not read in 30 days, up to ``limit`` requests, with what the budget leaves;
    one the cache holds, read within 30 days and not in the index, from the cache alone.

    ``ProviderBlocked`` propagates. A spent budget ends the pass (``budget_exhausted``), and so does a client that
    gives up on LaCuerda for the run; any other provider error, a page that won't parse included, counts in
    ``errors`` and the pass goes on."""
    stats = PopularStats()
    if complete_at(conn) is None or limit <= 0:
        return stats
    cached = getattr(client, "cached", None)  # a PoliteClient's; a test's fake client may have none
    fetched: set[str] = set()
    slugs = [r[0] for r in conn.execute("SELECT artist_slug FROM lacuerda_index WHERE title = '' "
                                        "ORDER BY songs DESC, artist_slug LIMIT ?", (POPULAR_SCAN,))]
    for slug in slugs:
        if stats.read >= limit:
            break
        url = artist_url(slug)
        copy = cached(url, accept=_ACCEPT) if cached is not None else None
        if copy is not None and not stale(copy, now, ARTIST_PAGE_MAX_AGE):
            if copy.status == 200 and conn.execute("SELECT 1 FROM lacuerda_index WHERE page = ? AND title != '' "
                                                   "LIMIT 1", (f"{slug}/",)).fetchone() is None:
                store_artist_page(conn, slug, copy.text)
            continue
        try:
            _artist_page(conn, client, slug, now, fetched)
        except ProviderBlocked:
            raise
        except BudgetExhausted:
            stats.budget_exhausted = True
            break
        except ProviderUnavailable as e:
            log.warning("LaCuerda is unavailable for the rest of this run: %s", e)
            break
        except ProviderError as e:
            stats.errors += 1
            log.warning("LaCuerda's page of %s: %s", slug, e)
        stats.read += 1
    return stats


# --- which songs ---------------------------------------------------------------------


def _songs_to_try(
    conn: sqlite3.Connection, library_dir: Path, rank: RankPolicy, now: datetime, overrides: Overrides | None
) -> list[Song]:
    """Songs worth asking LaCuerda about, newest first.

    Not ignored; no kept human sheet that is complete or that you pinned; one LaCuerda
    may have (``may_ask``); and not asked about in the last 30 days. A song whose kept
    LaCuerda sheet the library lost (``_lost``) is asked about whatever its sheet and
    the date, so that the sheet is written again.
    """
    return [song for song in list_songs(conn) if _to_try(conn, library_dir, rank, now, overrides, song)]


def _to_try(
    conn: sqlite3.Connection, library_dir: Path, rank: RankPolicy, now: datetime, overrides: Overrides | None,
    song: Song,
) -> bool:
    """Whether LaCuerda is worth asking about the song now (``_songs_to_try``)."""
    cutoff = stamps.utc(now) - RECHECK_AFTER
    ignored = overrides.ignore if overrides is not None else frozenset()
    picks = overrides.lacuerda if overrides is not None else {}
    if song.status == "ignored" or song.key in ignored:
        return False
    kept = _kept_sheet(conn, song.id)
    pick = picks.get(song.key)
    if pick is not None:  # your pick: until its sheet is the one kept, unless you pinned a UG sheet
        lost = kept is not None and kept.provider == PROVIDER and _lost(conn, library_dir, song.id)
        if kept is not None and not lost and (
                _pinned(overrides, song, kept) or (kept.provider == PROVIDER and pick.holds(kept.tab_id))):
            return False
        return lost or stamps.before(song.lacuerda_checked_at, cutoff)
    if not (kept is not None and kept.provider == PROVIDER and _lost(conn, library_dir, song.id)):
        if not stamps.before(song.lacuerda_checked_at, cutoff):  # asked about in the last 30 days
            return False
        if kept is not None and (_complete(kept.coverage, rank) or _pinned(overrides, song, kept)):
            return False
    return may_ask(song)


def asked_lately(song: Song, now: datetime) -> bool:
    """Whether LaCuerda was asked about the song in the last 30 days, so that a pass, a lookup's among them,
    leaves it alone until they are over (``_songs_to_try``), your pick too; for the requests page, which then
    offers no LaCuerda sheet (web/outcome.py)."""
    return not stamps.before(song.lacuerda_checked_at, stamps.utc(now) - RECHECK_AFTER)


def may_ask(song: Song) -> bool:
    """Whether LaCuerda may have the song, the rule the step and the to-do page go by: it looks
    Spanish (by its lyrics when it has any, else its title), and a slug of LaCuerda's can be built
    from its artist's name."""
    lyrics = song_lyrics(song)
    return looks_spanish(clean_title(song.title), lyrics.plain if lyrics is not None else None) and bool(
        artist_slug_candidates(song.artists[0]))


def _kept_sheet(conn: sqlite3.Connection, song_id: int) -> VersionRow | None:
    """The version kept as the song's ``sheet.txt`` (UG's or LaCuerda's), if any."""
    for f in kept_files(conn, song_id):
        if f.name == HUMAN_SHEET:
            return get_version(conn, f.version_id)
    return None


def _lost(conn: sqlite3.Connection, library_dir: Path, song_id: int) -> bool:
    """Whether a file of the song's kept LaCuerda sheet is no longer in the library as kept
    (``library.holds``): deleted on a synced device, cut short by a power cut, a link in its place.
    Each is hashed; the files table keeps no length to compare first."""
    return any(
        f.name in SHEET_DOCS and get_version(conn, f.version_id).provider == PROVIDER
        and not holds(library_dir / f.path, f.sha256)
        for f in kept_files(conn, song_id)
    )


def _handoffs(client: Client) -> int:
    """How many times the client's process has handed caracole's lock to a lookup (commands/_common.py's
    clients; another client, none)."""
    return int(getattr(client, "handoffs", 0) or 0)


class _Lookups:
    """What a pass knows of the lookups its client let go first (``_handoffs``): overrides.toml as the last
    one left it, read again after each (``reload_overrides``; the copy read before when it can't be), and
    whether there was one at all (``since``), after which each song is read again before it is asked about."""

    def __init__(self, client: Client, overrides: Overrides | None,
                 reload_overrides: Callable[[], Overrides] | None):
        self.client, self.overrides, self.reload = client, overrides, reload_overrides
        self.seen, self.since = _handoffs(client), False

    @property
    def picks(self) -> Mapping[str, LaCuerdaPick]:
        """Your LaCuerda picks, by song key, as overrides.toml holds them now."""
        return self.overrides.lacuerda if self.overrides is not None else {}

    def look(self) -> bool:
        """Whether a lookup went first since the last look; overrides.toml is read again when one did."""
        count = _handoffs(self.client)
        if count == self.seen:
            return False
        self.seen, self.since = count, True
        if self.reload is not None:
            try:
                self.overrides = self.reload()
            except OverridesError as e:
                log.info("overrides.toml couldn't be read again (%s); LaCuerda goes on with what it read.", e)
        return True


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


def _find_sheet(
    conn: sqlite3.Connection, client: Client, artist: str, title: str, now: datetime, fetched: set[str]
) -> _Sheet | None:
    """The best "acordes" version LaCuerda has of a song, or None when it has none."""
    found = _artist_songs(conn, client, artist, now, fetched)
    if found is None:
        return None
    slug, songs = found
    lc_song = match_title(songs, title)
    n = best_acordes_version(lc_song) if lc_song is not None else None
    if lc_song is None or n is None:
        return None
    url = version_url(slug, lc_song.slug, n)
    markup = read_once_more(client, client.get(url, accept=_ACCEPT), url, _version_sheet, LaCuerdaParseError,
                            fetched=fetched, accept=_ACCEPT)
    return _Sheet(slug, lc_song, n, url, markup) if markup is not None else None


def _artist_songs(
    conn: sqlite3.Connection, client: Client, artist: str, now: datetime, fetched: set[str],
    first: Collection[str] = (),
) -> tuple[str, list[LCSong]] | None:
    """The first artist page LaCuerda has among the artist's slugs, with its songs, which go into
    the index (``lacuerda_index.store_songs``).

    The slugs are ``first``'s, then those LaCuerda's listings give the name, then those built
    from it. A 404, or LaCuerda's HTTP 200 "aqui llega:" body, means no artist by that slug: the
    next slug is tried. None when no slug has a page.
    """
    for slug in dict.fromkeys([*first, *artist_slugs(conn, artist), *artist_slug_candidates(artist)]):
        songs = _artist_page(conn, client, slug, now, fetched)
        if songs is not None:
            return slug, songs
    return None


def _artist_page(conn: sqlite3.Connection, client: Client, slug: str, now: datetime,
                 fetched: set[str]) -> list[LCSong] | None:
    """The songs of the artist page of ``slug``, stored in the index; None when LaCuerda has no artist by it."""
    url = artist_url(slug)
    resp = client.get(url, accept=_ACCEPT, max_age=ARTIST_PAGE_MAX_AGE)
    if stale(resp, now, ARTIST_PAGE_MAX_AGE):
        raise BudgetExhausted(PROVIDER)  # no answer for today: stop as the next request would have
    page = read_once_more(client, resp, url, _artist_page_songs, LaCuerdaParseError, fetched=fetched,
                          accept=_ACCEPT)
    if page is None:
        return None
    songs, html = page
    store_songs(conn, slug, parse_artist_name(html), songs, parse_popularity(html))
    return songs


def _picked_sheet(conn: sqlite3.Connection, client: Client, pick: LaCuerdaPick, song: Song, now: datetime,
                  fetched: set[str]) -> _Sheet | None:
    """The sheet of the LaCuerda song or version you picked, or None when LaCuerda has no such page, or
    the song no "acordes" version. A version costs its own page; a song, its best "acordes" version's,
    which the index names when it holds the artist's page, else the artist's page does first."""
    row = conn.execute("SELECT title, versions, acordes FROM lacuerda_index WHERE path = ?",
                       (f"{pick.artist}/{pick.song}",)).fetchone()
    lc_song = LCSong(pick.song, row[0] if row else song.title, row[1] if row else "", ())
    n = pick.version
    if n is None and row is not None:
        n = row[2] or None  # the index names the song's best "acordes" version, 0 for none
    elif n is None:
        songs = _artist_page(conn, client, pick.artist, now, fetched)
        lc_song = next((s for s in songs or () if s.slug == pick.song), None)
        n = best_acordes_version(lc_song) if lc_song is not None else None
    if lc_song is None or n is None:
        return None
    url = version_url(pick.artist, pick.song, n)
    markup = read_once_more(client, client.get(url, accept=_ACCEPT), url, _version_sheet, LaCuerdaParseError,
                            fetched=fetched, accept=_ACCEPT)
    return _Sheet(pick.artist, lc_song, n, url, markup) if markup is not None else None


def _artist_page_songs(resp: Response) -> tuple[list[LCSong], str] | None:
    """The songs on an artist page, and the page; None when LaCuerda has no artist by that slug."""
    if resp.status == 404 or is_missing_artist_page(resp.text):
        return None
    return parse_artist_page(resp.text, url=resp.url), resp.text


def _version_sheet(resp: Response) -> str | None:
    """The sheet on a version page; None when the page is gone (listed by a cached artist page)."""
    return None if resp.status == 404 else parse_version_page(resp.text, url=resp.url)


# --- keeping the sheet -------------------------------------------------------------------


def _record(
    conn: sqlite3.Connection, library_dir: Path, rank: RankPolicy, song: Song, sheet: _Sheet,
    stamp: str, *, picked: bool = False,
) -> bool:
    """Record LaCuerda's version with its coverage; keep it if it beats the kept sheet, or you picked it.

    The sheet already kept, met again, is only rescored: the lyrics may have
    arrived since, and once it proves complete the auto-chords sheet gives way,
    as it would have on keeping. A kept LaCuerda sheet the library lost
    (``_lost``) counts as none, so the sheet met is kept: the same one is
    written again. Returns whether the sheet was kept now.
    """
    lyrics = song_lyrics(song)
    lines = coverage.lyric_lines(lyrics.plain) if lyrics is not None else []
    value = coverage.coverage(sheet.markup, lines, line_match=rank.line_match)
    kept = _kept_sheet(conn, song.id)
    if kept is not None and kept.provider == PROVIDER and _lost(conn, library_dir, song.id):
        kept = None
    vid = upsert_version(
        conn, provider=PROVIDER, tab_id=sheet.tab_id, song_id=song.id, slot="sheet", kind="acordes",
        rating=0, votes=0, version=sheet.version, label=None, url=sheet.url,
        raw={"lcd": sheet.song.lcd, "title": sheet.song.title}, now=stamp,
    )
    set_coverage(conn, vid, value)
    already_kept = kept is not None and kept.id == vid
    keep = kept is None or (
        not already_kept and (picked or replaces_sheet(value, kept.coverage, rank.coverage_threshold))
    )
    if keep:
        _keep(conn, library_dir, song, vid, sheet, complete=_complete(value, rank))
    elif already_kept and _complete(value, rank):
        _retire_auto_sheet(conn, library_dir, song, vid)
    update_song(conn, song.id, lacuerda_checked_at=stamp)
    if keep or already_kept:  # info.json lists the kept sheet's coverage
        write_info(conn, library_dir, get_song(conn, song.id))
    return keep


def _keep(
    conn: sqlite3.Connection, library_dir: Path, song: Song, version_id: int, sheet: _Sheet, *,
    complete: bool,
) -> None:
    """Keep the sheet as ``sheet.txt`` (no markup) and ``sheet.json``, and pick it for the slot.

    ``sheet.json`` goes first: ``sheet.txt`` is what makes the song found. A file
    of this version kept already, and still in the library, isn't written again
    (``library.kept_already``). A complete sheet replaces the auto-chords sheet,
    which only stands in for a human sheet until one covers the lyrics.
    """
    doc = {
        "provider": PROVIDER, "url": sheet.url, "content": sheet.markup, "version": sheet.version,
    }
    files = dict(zip(SHEET_DOCS, (json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                  strip_markup(sheet.markup)), strict=True))
    for name, text in files.items():
        data = text.encode("utf-8")
        if not kept_already(conn, library_dir, song=song, version_id=version_id, name=name, data=data):
            keep_file(conn, library_dir, song=song, version_id=version_id, name=name, data=data, rank=1)
    if complete:
        _retire_auto_sheet(conn, library_dir, song, version_id)
    set_picks(conn, song.id, SHEET_KINDS, [version_id])
    refresh_status(conn, song.id, ignored=False)


def _retire_auto_sheet(
    conn: sqlite3.Connection, library_dir: Path, song: Song, version_id: int
) -> None:
    """The kept sheet is complete: ``sheet (auto).txt`` goes; the kept sheet is the only pick."""
    drop_file(conn, library_dir, song=song, name=AUTO_SHEET)
    set_picks(conn, song.id, SHEET_KINDS, [version_id])


# --- small helpers -----------------------------------------------------------------------


def _complete(value: float | None, rank: RankPolicy) -> bool:
    return complete(value, rank.coverage_threshold)
