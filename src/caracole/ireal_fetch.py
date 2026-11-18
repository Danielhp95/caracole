"""iReal Pro's forum in the nightly run: a chord chart as the sheet of each song the sheet sites left with none.

What the site looks like is in ireal.py, its index in ireal_index.py. A pass:

1. **The index.** The forum's sitemaps are read into ``ireal_index`` (db.py) by site_index.py: when they never were,
   again after 30 days, and at once after a change to caracole's keys. Each is asked for with its validators.
2. **Which songs.** Not ignored; with no human sheet kept (Ultimate Guitar's, LaCuerda's: iReal Pro's forum comes
   after them, for the songs they left with none, a song with an auto sheet alone among them); not asked about in the
   last 30 days (kv ``ireal:checked:<song id>``); and with a candidate (never a request): a chart of the song in a
   thread page caracole read, or a thread whose slug is the song's title and one of its artists' names
   ("groove-merchant-thad-jones" for "Thad Jones - Groove Merchant", ``ireal.begins_with``), or its title alone. A
   chart is the song's only when it is titled as the song is and one of its artists is its composer or the name its
   thread's slug gives after the title (``composer_fits``, ``names_an_artist``), or it comes from one of the jazz
   playlists caracole reads (the Jazz 1460 Standards and the jazz forum's playlist threads), where its title alone is
   enough, the standards' case ("Bill Evans - Autumn Leaves"); the owner's ruling of 2026-11-18, after titles alone
   gave "Ren - Patience" Guns N' Roses' chart. A song whose kept chart the library lost (deleted on a synced device) is
   asked about again whatever the date, and its chart written again.
3. **The candidates**, ``CANDIDATES`` pages at most: those caracole read that hold a chart of the song, from the
   cache with no request, then the threads named for it, a slug that names one of the song's artists after the title
   first, then the title alone, the oldest first; never a slug that names someone else. Once a chart whose composer is
   one of the song's artists is in hand (``composer_fits``), no thread more is asked for. Each page read goes into the
   index (``read_thread``). Every chart of the song is a version (provider ``ireal``, kind ``chords``, its tab id ``<thread>/<post>/<place>``, its address
   the thread's at the post), and the best is the song's sheet (``best``): a composer who is one of the song's artists
   (iReal Pro writes the composer last name first: "Jones Thad", ``ireal.composer_words``), then the curated playlist's
   (the Jazz 1460 Standards), then a thread whose slug names the composer, then the oldest thread, and in a thread the
   latest post (a repost is most often a correction: "the chart originally posted was missing the Coda").
4. **The sheet** is kept as ``sheet.txt`` and ``sheet.json`` (``content``: the chart in Ultimate Guitar's markup,
   ``ireal.Tune.chart``, its bars as a sheet's page draws them, with the tune as the link gave it), the slot's only
   pick; the version's ``tonality_name`` is the tune's key, which render.py writes as the sheet's. Its coverage of the
   lyrics is scored as every sheet's (a chart holds none: 0 for a song with lyrics), so another site's sheet with words
   replaces it by the shared rule (``versions.replaces_sheet``), and the auto sheet gives way to it only as to any
   complete one. info.json is rewritten.

**Your pick.** A chart you picked (``[ireal]`` in overrides.toml: ``caracole get --ireal``, the library page's Fetch
on an iReal Pro row) is read in place of the candidates, its thread's page alone, whoever its composer is: the post's
chart (one of the song's title, else its one chart), or the thread's chart of the title (else its one chart), kept in place of any sheet but one
you pinned on Ultimate Guitar or picked on LaCuerda, until it is the one kept (kv ``ireal:checked:<song id>:pick``, the
chart asked for).

Only songs in wanted.txt are looked up (and a lookup's song): never a thread for a song nobody asked for, never a
mirror of the forum. Errors are never misses: only candidates that all answered, none holding a chart of the song (or
each gone, 404), make the song a miss, asked about again after 30 days. A block propagates, and a spent budget ends the
pass. Any other provider error, a page that won't parse even fetched again included, leaves the song for the next run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from caracole import coverage, site_index, stamps
from caracole.config import RankPolicy
from caracole.db import kv_get, kv_set
from caracole.http import (
    BudgetExhausted,
    Client,
    ProviderBlocked,
    ProviderError,
    ProviderUnavailable,
    RobotsClosed,
)
from caracole.ireal import (
    JAZZ_1460,
    PROVIDER,
    SITEMAP_URL,
    IndexRow,
    ThreadPage,
    Tune,
    begins_with,
    composer_words,
    page_url,
    parse_page_url,
    sitemap_child,
    title_key,
)
from caracole.ireal_index import ensure_current_keys, playlists, read_thread
from caracole.library import (
    SharedFolder,
    drop_file,
    holds,
    keep_file,
    kept_already,
    kept_files,
    write_info,
)
from caracole.lyrics import song_lyrics
from caracole.normalize import slug_key
from caracole.overrides import IRealPick, Overrides
from caracole.provider_pass import PassStats, as_now, each_song
from caracole.site_index import Site
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, get_song, list_songs, refresh_status
from caracole.ug.page import strip_markup
from caracole.versions import (
    SHEET_KINDS,
    VersionRow,
    complete,
    get_version,
    set_coverage,
    set_picks,
    upsert_version,
)

log = logging.getLogger(__name__)

INDEX_MAX_AGE = timedelta(days=30)
RECHECK_AFTER = timedelta(days=30)  # a song none of whose candidates held its chart: asked about again after this
CANDIDATES = 3  # thread pages read for one song at most (the cache's among them)
KIND = "chords"  # the kind of its versions: a sheet's, as Ultimate Guitar's chords are
SHEET_DOCS = ("sheet.json", HUMAN_SHEET)  # what keeping a sheet writes, in that order

CHECKED_PREFIX = "ireal:checked:"  # + song id: when its candidates last answered for it
PICKED = ":pick"  # CHECKED_PREFIX + song id + this: the chart you picked that was asked for then

KEPT, MISSING = "kept", "missing"

# The forum's sitemaps, as site_index.py reads them into ireal_index: its numbered children, the threads of each.
SITE = Site(
    provider=PROVIDER, index_url=SITEMAP_URL, table="ireal_index", columns=IndexRow._fields,
    child=sitemap_child, row=parse_page_url, max_age=INDEX_MAX_AGE,
)


@dataclass
class IRealStats(PassStats):
    """What one ``ireal_sheets`` pass did. ``sitemaps`` counts the sitemap reads stored; ``tried`` the songs looked
    up, errors included; ``errors`` the songs' and the sitemaps'; ``failures`` the songs an error left; ``shared`` the
    songs that wait, as their sheet would go where another song keeps one (``library.SharedFolder``)."""

    sitemaps: int = 0
    kept: int = 0
    missing: int = 0
    shared: list[SharedFolder] = field(default_factory=list, compare=False, repr=False)

    @property
    def sitemap_errors(self) -> int:
        """The errors no song's failure stands for: the sitemaps'."""
        return self.errors - sum(not isinstance(e, ProviderUnavailable) for _, e in self.failures)


@dataclass(frozen=True)
class Chart:
    """A chart of a thread page: the page's path and id, the post's id, its place in the post, and its tune."""

    page: str
    thread: int
    post: int
    place: int
    tune: Tune

    @property
    def tab_id(self) -> str:
        return f"{self.thread}/{self.post}/{self.place}"

    @property
    def url(self) -> str:
        return f"{page_url(self.page)}#post-{self.post}"


def ireal_sheets(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    rank: RankPolicy,
    now: datetime,
    *,
    overrides: Overrides | None = None,
    only: Collection[int] | None = None,
    refresh_index: bool = True,
) -> IRealStats:
    """Refresh the index when due, then keep a chart as the sheet of each song that needs one and has a candidate.

    See the module docstring. With no song that wants a sheet, nothing is sent, not even for the sitemaps.
    ``ProviderBlocked`` propagates. ``BudgetExhausted`` ends the pass (``budget_exhausted``), and so does a client
    that gives up on the site for this run (``ProviderUnavailable``): the songs left are ``failures``. Any other
    ``ProviderError`` counts in ``errors``: one from the sitemaps leaves the index as it was, and one for a song leaves
    the song for the next run, in ``failures`` with its error.

    A lookup (``caracole get``) passes ``only`` its song's id, and ``refresh_index=False``: the sitemaps are the nightly
    run's to read. A song that got a sheet meanwhile (from a lookup the nightly run let go first) is passed over when
    its turn comes.
    """
    stats = IRealStats()
    now = stamps.utc(now)
    ensure_current_keys(conn)
    library_dir = Path(library_dir)
    wanting = [s for s in list_songs(conn) if (only is None or s.id in only)
               and _to_try(conn, library_dir, now, overrides, s)]
    if not wanting:
        return stats

    def read() -> None:
        stats.sitemaps += 1

    try:
        if refresh_index:
            site_index.refresh(conn, client, SITE, now, on_read=read)
    except ProviderBlocked:
        raise
    except BudgetExhausted:
        stats.budget_exhausted = True
        return stats
    except ProviderUnavailable as e:
        log.info("iReal Pro's forum is unavailable for the rest of this run: %s", e)
        stats.failures += [(song, e) for song in wanting if _pick(overrides, song) or candidates(conn, song)]
        return stats
    except ProviderError as e:
        stats.errors += 1
        log.warning("iReal Pro's forum's sitemaps: %s", e)
    run = _Pass(conn, client, library_dir, rank, now)
    songs = (s for s in as_now(conn, wanting, lambda s: _to_try(conn, library_dir, now, overrides, s))
             if _pick(overrides, s) or candidates(conn, s))
    for song, outcome in each_song(songs, stats, lambda song: _look_up(run, song, _pick(overrides, song)),
                                   site="iReal Pro's forum", level=logging.WARNING):
        if isinstance(outcome, SharedFolder):
            log.info("%s", outcome)
            stats.shared.append(outcome)
            continue
        stats.kept += outcome == KEPT
        stats.missing += outcome == MISSING
    return stats


# --- which songs ----------------------------------------------------------------------------------------------------


def wants_a_chart(conn: sqlite3.Connection, library_dir: Path, now: datetime, overrides: Overrides | None,
                  song: Song) -> bool:
    """Whether ``ireal_sheets`` would ask about the song now: it is one to try, with a pick or a candidate; no
    request, and nothing written but the charts' keys made current (a lookup asks first, and makes no client
    otherwise)."""
    ensure_current_keys(conn)
    return _to_try(conn, Path(library_dir), stamps.utc(now), overrides, song) and bool(
        _pick(overrides, song) or candidates(conn, song))


def _pick(overrides: Overrides | None, song: Song) -> IRealPick | None:
    """The chart you picked for the song (``[ireal]``), or None."""
    return overrides.ireal.get(song.key) if overrides is not None else None


def kept_sheet(conn: sqlite3.Connection, song_id: int) -> VersionRow | None:
    """The version kept as the song's ``sheet.txt`` (any site's), if any."""
    for f in kept_files(conn, song_id):
        if f.name == HUMAN_SHEET:
            return get_version(conn, f.version_id)
    return None


def _lost(conn: sqlite3.Connection, library_dir: Path, song_id: int) -> bool:
    """Whether a file of the song's kept chart is no longer in the library as kept (``library.holds``)."""
    return any(f.name in SHEET_DOCS and get_version(conn, f.version_id).provider == PROVIDER
               and not holds(library_dir / f.path, f.sha256) for f in kept_files(conn, song_id))


def _held_by_another_choice(overrides: Overrides | None, song: Song, kept: VersionRow) -> bool:
    """Whether the kept sheet is one you chose on another site: a UG tab you pinned, a LaCuerda sheet you picked."""
    if overrides is None:
        return False
    if kept.provider == "ug" and kept.tab_id.isdigit():
        return int(kept.tab_id) in overrides.pin.get(song.key, ())
    pick = overrides.lacuerda.get(song.key)
    return kept.provider == "lacuerda" and pick is not None and pick.holds(kept.tab_id)


def _to_try(conn: sqlite3.Connection, library_dir: Path, now: datetime, overrides: Overrides | None,
            song: Song) -> bool:
    """Whether iReal Pro's forum is worth asking about the song now (see the module docstring); never a request."""
    ignored = overrides.ignore if overrides is not None else frozenset()
    if song.status == "ignored" or song.key in ignored:
        return False
    kept = kept_sheet(conn, song.id)
    lost = kept is not None and kept.provider == PROVIDER and _lost(conn, library_dir, song.id)
    checked = not stamps.before(kv_get(conn, f"{CHECKED_PREFIX}{song.id}"), stamps.utc(now) - RECHECK_AFTER)
    pick = _pick(overrides, song)
    if pick is not None:
        if kept is not None and not lost and (
                (kept.provider == PROVIDER and pick.holds(kept.tab_id)) or _held_by_another_choice(overrides, song,
                                                                                                    kept)):
            return False
        return lost or not checked or kv_get(conn, f"{CHECKED_PREFIX}{song.id}{PICKED}") != pick.url
    if kept is not None and not lost:
        return False
    return lost or not checked


def candidates(conn: sqlite3.Connection, song: Song) -> list[str]:
    """The thread pages to read for the song, in turn, ``CANDIDATES`` at most; never a request: those caracole read that
    hold a chart of its title that is the song's (``matches``), their best chart first (``best``), then the threads
    whose slug is its title and a name of one of its artists after it, or its title alone (whose chart may be by one of
    them), the first before, then the oldest. A slug that names someone else after the title is never read: its
    chart is another song of that name ("open-arms-journey" for "Jorge Rivera-Herrans - Open Arms")."""
    key = title_key(song.title)
    if not key:
        return []
    curated = set(playlists(conn))
    known: dict[str, tuple] = {}
    for page, thread, post, place, composer in conn.execute(
            "SELECT c.page, t.thread, c.post, c.place, c.composer FROM ireal_charts c "
            "JOIN ireal_threads t ON t.path = c.page WHERE c.title_key = ?", (key,)):
        rest = _slug_rest(conn, page, key)
        if not _matching(song, page, composer, rest, curated):
            continue
        order = _order(song, page, thread, post, place, composer, rest)
        known[page] = min(known.get(page, order), order)
    pages = [page for page, _ in sorted(known.items(), key=lambda p: p[1])]
    unread = []
    for path, thread, slug in conn.execute(
            "SELECT i.path, i.thread, i.key FROM ireal_index i LEFT JOIN ireal_threads t ON t.path = i.path "
            "WHERE t.path IS NULL AND (i.key = ? OR (i.key >= ? AND i.key < ?))", (key, f"{key}-", f"{key}.")):
        if path in known or not begins_with(slug, key):
            continue
        rest = set(slug[len(key):].strip("-").split("-")) - {""}
        named = names_an_artist(song, rest)
        if named or not rest:
            unread.append((not named, thread, path))
    return [*pages, *(path for *_, path in sorted(unread))][:CANDIDATES]


def _words(name: str) -> frozenset[str]:
    return frozenset(w for w in slug_key(name).split("-") if w)


def names_an_artist(song: Song, words: Collection[str]) -> bool:
    """Whether some words name one of the song's artists: every word of the artist's name among them, in whatever
    order (iReal Pro writes a composer last name first, "Jones Thad"; a thread's slug names one after the title)."""
    theirs = set(words)
    return bool(theirs) and any(mine and mine <= theirs for mine in map(_words, song.artists or [song.artist]))


def composer_fits(song: Song, composer: str) -> bool:
    """Whether a chart's composer is one of the song's artists (``names_an_artist``: "Jobim Antonio-Carlos" is Antonio
    Carlos Jobim's)."""
    return names_an_artist(song, composer_words(composer))


def _matching(song: Song, page: str, composer: str, rest: set[str], curated: set[str]) -> bool:
    """Whether a chart titled as the song is the song's: one of its artists is the chart's composer or the name its
    thread's slug gives after the title, or the chart is one of the jazz playlists caracole reads (``curated``: the
    Jazz 1460 Standards and the jazz forum's playlist threads, ireal_index.py ``playlists``), where the title alone
    is enough: "Bill Evans - Autumn Leaves" is Kosma's standard. A title alone elsewhere is another song of that name
    as often as not ("Ren - Patience" is no Guns N' Roses song)."""
    return page in curated or composer_fits(song, composer) or names_an_artist(song, rest)


def _slug_rest(conn: sqlite3.Connection, page: str, key: str) -> set[str]:
    """The words of a thread's slug after the title's, when its slug begins with it (a song's thread: its composer, as
    the forum names it); none for another thread (a playlist's)."""
    row = conn.execute("SELECT key FROM ireal_index WHERE path = ?", (page,)).fetchone()
    slug = row[0] if row is not None else ""
    return set(slug[len(key):].strip("-").split("-")) - {""} if begins_with(slug, key) else set()


def _order(song: Song, page: str, thread: int, post: int, place: int, composer: str, rest: set[str]) -> tuple:
    """A chart's place among a song's (``best``): the lower, the better."""
    return (not composer_fits(song, composer), page != JAZZ_1460, rest.isdisjoint(composer_words(composer)), thread,
            -post, place)


# --- one song -------------------------------------------------------------------------------------------------------


@dataclass
class _Pass:
    conn: sqlite3.Connection
    client: Client
    library_dir: Path
    rank: RankPolicy
    now: datetime
    fetched: set[str] = field(default_factory=set)  # pages fetched from the site in this pass

    @property
    def stamp(self) -> str:
        return stamps.stamp(self.now)


def best(conn: sqlite3.Connection, song: Song, charts: list[Chart]) -> Chart:
    """The best of a song's charts (see the module docstring)."""
    key = title_key(song.title)
    return min(charts, key=lambda c: _order(song, c.page, c.thread, c.post, c.place, c.tune.composer,
                                            _slug_rest(conn, c.page, key)))


def _page(run: _Pass, path: str) -> ThreadPage | None:
    """A thread page, read from the cache when it holds one (whenever it is from), else asked for, into the index;
    None when the site no longer has it (404), or sends it where robots.txt closes."""
    try:
        return read_thread(run.conn, run.client, path, run.now, fetched=run.fetched, max_age=None)
    except RobotsClosed as e:
        log.info("iReal Pro's forum: %s", e)
        return None


def _charts_of(conn: sqlite3.Connection, song: Song, page: ThreadPage, key: str, pick: IRealPick | None) -> list[Chart]:
    """The charts of a page that are the song's: titled as it is, and its own (``_matching``); for a pick, any of the
    title, and else its post's (or the thread's) one chart whatever its title."""
    every = [Chart(page.path, page.thread, post.post, place, tune) for post, place, tune in page.charts()
             if tune.chart() and (pick is None or pick.post is None or post.post == pick.post)]
    titled = [c for c in every if title_key(c.tune.title) == key]
    if pick is not None:
        return titled or (every if len(every) == 1 else [])
    curated, rest = set(playlists(conn)), _slug_rest(conn, page.path, key)
    return [c for c in titled if _matching(song, c.page, c.tune.composer, rest, curated)]


def _look_up(run: _Pass, song: Song, pick: IRealPick | None = None) -> str | SharedFolder:
    """Read the song's candidates and keep its best chart: ``KEPT``; ``MISSING`` when none holds one. With ``pick``,
    read that thread alone and keep its chart."""
    key = title_key(song.title)
    found: list[Chart] = []
    for path in ([pick.path] if pick is not None else candidates(run.conn, song)):
        if pick is None and any(composer_fits(song, c.tune.composer) for c in found):
            break  # a chart by one of its artists is in hand: none of another thread is better
        page = _page(run, path)
        if page is not None:
            found += _charts_of(run.conn, song, page, key, pick)
    kv_set(run.conn, f"{CHECKED_PREFIX}{song.id}", run.stamp)
    if pick is not None:
        kv_set(run.conn, f"{CHECKED_PREFIX}{song.id}{PICKED}", pick.url)
    if not found:
        return MISSING
    try:
        _keep(run, song, found)
    except SharedFolder as e:  # nothing written over the other song's sheet: this one waits for the next run
        return e
    return KEPT


def _keep(run: _Pass, song: Song, charts: list[Chart]) -> None:
    """Record every chart as a version, and keep the best as the song's sheet, its coverage scored."""
    chosen = best(run.conn, song, charts)
    lyrics = song_lyrics(song)
    lines = coverage.lyric_lines(lyrics.plain) if lyrics is not None else []
    ids = {}
    for c in charts:
        ids[c.tab_id] = upsert_version(
            run.conn, provider=PROVIDER, tab_id=c.tab_id, song_id=song.id, slot="sheet", kind=KIND, rating=0,
            votes=0, version=1, label=None, url=c.url,
            raw={**c.tune.raw(), "thread": c.page, "post": c.post, "place": c.place}, now=run.stamp)
    vid = ids[chosen.tab_id]
    markup = chosen.tune.chart()
    value = coverage.coverage(markup, lines, line_match=run.rank.line_match)
    set_coverage(run.conn, vid, value)
    doc = {"provider": PROVIDER, "url": chosen.url, "content": markup,
           "tune": {"title": chosen.tune.title, "composer": chosen.tune.composer, "style": chosen.tune.style,
                    "key": chosen.tune.key, "scheme": chosen.tune.scheme, "music": chosen.tune.music,
                    "tempo": chosen.tune.tempo, "playlist": chosen.tune.playlist}}
    texts = dict(zip(SHEET_DOCS, (json.dumps(doc, ensure_ascii=False, indent=2) + "\n", strip_markup(markup)),
                     strict=True))
    for name, text in texts.items():
        data = text.encode("utf-8")
        if not kept_already(run.conn, run.library_dir, song=song, version_id=vid, name=name, data=data):
            keep_file(run.conn, run.library_dir, song=song, version_id=vid, name=name, data=data, rank=1)
    if complete(value, run.rank.coverage_threshold):
        drop_file(run.conn, run.library_dir, song=song, name=AUTO_SHEET)
    set_picks(run.conn, song.id, SHEET_KINDS, [vid])
    refresh_status(run.conn, song.id, ignored=False)
    write_info(run.conn, run.library_dir, get_song(run.conn, song.id))
