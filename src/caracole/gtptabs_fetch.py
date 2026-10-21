"""gtptabs.com in the nightly run: a Guitar Pro file for each song that has none.

Ultimate Guitar's Guitar Pro pages stay yours to click: its robots.txt closes
/tab/download. gtptabs.com's leaves /tabs/download/ open, so this step downloads one
file there for each song that has no Guitar Pro or Power Tab file yet. What the site
looks like is in gtptabs.py. A pass:

1. **The index.** gtptabs.com's sitemaps are read into ``gtptabs_index`` (db.py) by
   site_index.py: when they never were, again after 30 days with conditional requests
   (a sitemap unchanged since it was indexed costs one request and isn't parsed), and
   at once after a change to caracole's keys. A pass the budget cuts short goes on
   where it stopped.
2. **Which songs.** Not ignored; with no Guitar Pro or Power Tab file in the files
   table (filed from _inbox or downloaded here, whether or not you deleted it since);
   by an artist the index knows, under the name's own key or the site's "Last,
   First" one; and not looked up in the last 30 days. Newest first, except that
   songs whose title the sitemaps list too come before those only their artist's
   page may list: the sitemaps date from 2015, the artist pages are current.
3. **The artist page**, cached for 30 days so one fetch serves every song by the
   artist, lists the uploads of the title. Candidates are those in a format the
   library files, of at most 5 MB, and with a guitar part (or no instrument listed):
   most stars first, then the first upload.
4. **The download**, from ``/tabs/download/{id}.html``, is kept only if its bytes are
   a Guitar Pro or Power Tab file (``gtptabs.sniff``): as ``guitar-N`` with the
   extension its bytes say, N the lowest number no file of the song holds
   (``inbox.guitar_number``), its version recorded (provider gtptabs, its page as the
   URL) and info.json rewritten. A 404, bytes that are no such file, or a redirect
   robots.txt closes pass that upload over for 30 days, and the next is tried: at
   most three downloads a song a pass.

Errors are never misses. Only an artist page that answered without a candidate makes
the song a miss, asked about again after 30 days (kv ``gtptabs:checked:<song id>``).
A block propagates, and a spent budget ends the pass. Any other provider error, an
artist page that won't parse even fetched again included, leaves the song for the
next run. Three downloads in a row answered with a page instead of a file end the
pass as an error, so a site turned into a login wall costs three requests. No file is
ever replaced or deleted: a song that has one gets no other.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from caracole import site_index
from caracole.db import kv_get, kv_set
from caracole.gtptabs import (
    PROVIDER,
    SITEMAP_INDEX_URL,
    GtpTab,
    GtpTabsParseError,
    IndexRow,
    artist_keys,
    download_url,
    https,
    page_url,
    parse_artist_page,
    parse_page_url,
    sitemap_name,
    sniff,
    title_key,
)
from caracole.http import (
    BudgetExhausted,
    Client,
    ProviderBlocked,
    ProviderError,
    ProviderUnavailable,
    Response,
    RobotsClosed,
    read_once_more,
    stale,
)
from caracole.inbox import GUITAR_FILE_KINDS, guitar_number
from caracole.library import keep_file, write_info
from caracole.normalize import compact, slug_key
from caracole.overrides import Overrides
from caracole.provider_pass import PassStats, each_song
from caracole.site_index import Site
from caracole.songs import Song, get_song, list_songs
from caracole.versions import upsert_version

log = logging.getLogger(__name__)

INDEX_MAX_AGE = timedelta(days=30)
ARTIST_PAGE_MAX_AGE = timedelta(days=30)
RECHECK_AFTER = timedelta(days=30)  # a song its artist's page had no candidate for
UNUSABLE_FOR = timedelta(days=30)  # an upload whose download gave no file
DOWNLOADS_PER_SONG = 3
PAGES_IN_A_ROW = 3  # downloads answered with a page, not a file, before the pass stops
MAX_SIZE_KB = 5 * 1024
FORMATS = frozenset({"gp3", "gp4", "gp5", "gpx", "gp", "ptb"})  # the artist page's classes the library files
_ACCEPT = (200, 404)  # a 404 is an answer: no such artist, or no such file

CHECKED_PREFIX = "gtptabs:checked:"  # + song id: when its artist's page last answered for it
_UNUSABLE_PREFIX = "gtptabs:unusable:"  # + tab id: when its download last gave no file

KEPT, MISSING, WAITING = "kept", "missing", "waiting"


@dataclass
class GtpTabsStats(PassStats):
    """What one ``gtptabs_files`` pass did. ``sitemaps`` counts the sitemaps read into the index
    (one found unchanged isn't); ``tried`` the songs looked up, errors included; ``errors`` the
    songs' and the sitemaps'; ``failures`` the songs an error left, as every pass names them
    (provider_pass.py)."""

    sitemaps: int = 0
    kept: int = 0
    missing: int = 0

    @property
    def sitemap_errors(self) -> int:
        """The errors no song's failure stands for: the sitemaps'. (A song left once the client
        gave up on the site was never asked about, and is no error.)"""
        return self.errors - sum(not isinstance(e, ProviderUnavailable) for _, e in self.failures)


class PagesNotFiles(ProviderError):
    """Downloads answered, several in a row, with a page instead of a file: the pass stops."""


def gtptabs_files(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    now: datetime,
    *,
    overrides: Overrides | None = None,
    only: Collection[int] | None = None,
    refresh_index: bool = True,
) -> GtpTabsStats:
    """Refresh the index when due, then download a file for each song that needs one, newest first.

    See the module docstring. With no song that wants a file, nothing is sent, not even
    for the sitemaps. ``ProviderBlocked`` propagates. ``BudgetExhausted`` ends the
    pass (``budget_exhausted``), and so does a client that gives up on the site for this run
    (``ProviderUnavailable``): the songs left are ``failures``. Any other ``ProviderError``
    counts in ``errors``: one from the sitemaps leaves the index as it was, and one for a song
    leaves the song for the next run, in ``failures`` with its error (provider_pass.py).

    A lookup (``caracole get``) passes ``only`` its song's id, and ``refresh_index=False``:
    the sitemaps are the nightly run's to read. A song that got a file meanwhile (from a
    lookup the nightly run let go first) is passed over when its turn comes.
    """
    stats = GtpTabsStats()
    now = _utc(now)
    wanting = [s for s in _songs_wanting_a_file(conn, now, overrides) if only is None or s.id in only]
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
    except ProviderUnavailable as e:  # every song left waits, named, as when the client gives up on a song's turn
        log.info("gtptabs.com is unavailable for the rest of this run: %s", e)
        stats.failures += [(song, e) for song in _songs_to_try(_Index(conn), wanting)]
        return stats
    except ProviderError as e:
        stats.errors += 1
        log.warning("gtptabs.com's sitemaps: %s", e)
    index = _Index(conn)
    run = _Pass(conn, client, Path(library_dir), now)
    # Each song is checked just before its turn: a lookup let in during a pause may have given it a file.
    songs = (s for s in _songs_to_try(index, wanting) if s.id not in songs_with_a_guitar_file(conn))
    for _, outcome in each_song(songs, stats, lambda song: _look_up(run, song, index), site="gtptabs.com",
                                level=logging.WARNING, stop_on=(PagesNotFiles,)):
        stats.kept += outcome == KEPT
        stats.missing += outcome == MISSING
    return stats


# --- the index ------------------------------------------------------------------------------------

# gtptabs.com's sitemaps, as site_index.py reads them into gtptabs_index.
SITE = Site(
    provider=PROVIDER, index_url=SITEMAP_INDEX_URL, table="gtptabs_index", columns=IndexRow._fields,
    child=sitemap_name, row=parse_page_url, max_age=INDEX_MAX_AGE, fetch_url=https,
)


class _Index:
    """``gtptabs_index`` as a pass reads it: every artist key with its pages, loaded once."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._pages: dict[str, set[str]] = {}
        self._by_compact: dict[str, set[str]] = {}
        for key, path in conn.execute("SELECT DISTINCT artist_key, artist_path FROM gtptabs_index"):
            self._pages.setdefault(key, set()).add(path)
            self._by_compact.setdefault(compact(key), set()).add(key)

    def keys(self, song: Song) -> list[str]:
        """The index's keys for the song's artists: their own and the site's "Last, First" ones, each
        also without its hyphens, so ``acdc`` meets ``ac-dc``."""
        found: dict[str, None] = {}
        for name in song.artists or [song.artist]:
            for key in artist_keys(name):
                if key in self._pages:
                    found.setdefault(key)
                for other in sorted(self._by_compact.get(compact(key), ())):
                    found.setdefault(other)
        return list(found)

    def artist_pages(self, song: Song) -> list[str]:
        return list(dict.fromkeys(path for key in self.keys(song) for path in sorted(self._pages[key])))

    def lists(self, song: Song) -> bool:
        """Whether the sitemaps list the song's title under one of its artists."""
        keys, title = self.keys(song), title_key(song.title)
        if not keys or not title:
            return False
        marks = ",".join("?" for _ in keys)
        return self.conn.execute(
            f"SELECT 1 FROM gtptabs_index WHERE artist_key IN ({marks}) AND (title_key = ? OR base_key = ?) LIMIT 1",
            (*keys, title, title),
        ).fetchone() is not None


# --- which songs ------------------------------------------------------------------------------------


def _songs_wanting_a_file(conn: sqlite3.Connection, now: datetime, overrides: Overrides | None) -> list[Song]:
    """The songs, newest first, that are not ignored, have no Guitar Pro or Power Tab file, and
    weren't looked up on gtptabs.com in the last 30 days."""
    ignored = overrides.ignore if overrides is not None else frozenset()
    with_file = songs_with_a_guitar_file(conn)
    cutoff = now - RECHECK_AFTER
    return [
        song for song in list_songs(conn)
        if song.status != "ignored" and song.key not in ignored and song.id not in with_file
        and _before(kv_get(conn, f"{CHECKED_PREFIX}{song.id}"), cutoff)
    ]


def _songs_to_try(index: _Index, wanting: list[Song]) -> list[Song]:
    """Of those, the songs by an artist the index knows: the ones whose title the sitemaps list first."""
    due = [song for song in wanting if index.artist_pages(song)]
    return sorted(due, key=lambda song: not index.lists(song))  # stable: newest first within each group


def songs_with_a_guitar_file(conn: sqlite3.Connection) -> set[int]:
    """The songs the files table holds a Guitar Pro or Power Tab file for, whoever kept it."""
    marks = ",".join("?" for _ in GUITAR_FILE_KINDS)
    return {r[0] for r in conn.execute(
        f"SELECT DISTINCT f.song_id FROM files f JOIN versions v ON v.id = f.version_id WHERE v.kind IN ({marks})",
        GUITAR_FILE_KINDS,
    )}


# --- one song --------------------------------------------------------------------------------------------


@dataclass
class _Pass:
    conn: sqlite3.Connection
    client: Client
    library_dir: Path
    now: datetime
    fetched: set[str] = field(default_factory=set)  # pages fetched from the site in this pass
    pages_in_a_row: int = 0  # downloads answered with a page instead of a file, one after another

    @property
    def stamp(self) -> str:
        return _iso(self.now)


def _look_up(run: _Pass, song: Song, index: _Index) -> str:
    """Download and keep a file for the song: ``KEPT``; ``MISSING`` when its artist's pages answered
    without a candidate; ``WAITING`` when every candidate tried gave no file, or none may be tried now."""
    tabs: list[GtpTab] = []
    for path in index.artist_pages(song):
        listed = _artist_tabs(run, page_url(path))
        if listed is not None:
            tabs += listed
    candidates = _candidates(song, tabs)
    if not candidates:
        kv_set(run.conn, f"{CHECKED_PREFIX}{song.id}", run.stamp)
        return MISSING
    usable = [tab for tab in candidates if _before(kv_get(run.conn, f"{_UNUSABLE_PREFIX}{tab.tab_id}"),
                                                   run.now - UNUSABLE_FOR)]
    for tab in usable[:DOWNLOADS_PER_SONG]:
        found = _download(run, tab)
        if found is not None:
            _keep(run, song, tab, *found)
            kv_set(run.conn, f"{CHECKED_PREFIX}{song.id}", run.stamp)
            return KEPT
    return WAITING


def _candidates(song: Song, tabs: list[GtpTab]) -> list[GtpTab]:
    """The uploads of the song's title worth downloading, best first (see the module docstring)."""
    wanted = title_key(song.title)
    if not wanted:
        return []

    def same_title(tab: GtpTab) -> bool:
        key = slug_key(tab.title)
        return key == wanted or compact(key) == compact(wanted)

    found = {
        tab.tab_id: tab for tab in tabs
        if same_title(tab) and tab.format in FORMATS and tab.guitar
        and (tab.size_kb is None or tab.size_kb <= MAX_SIZE_KB)
    }
    return sorted(found.values(), key=lambda tab: (-tab.stars, tab.version, tab.tab_id))


def _artist_tabs(run: _Pass, url: str) -> list[GtpTab] | None:
    """The tabs an artist page lists; None when the site has no such page any more.

    A cached page that doesn't parse (a notice served with HTTP 200, say) is fetched once
    more before it counts as an error, unless this pass fetched it already. A redirect
    robots.txt closes is no page at the first request, and an error at that second one.
    """
    try:
        resp = run.client.get(url, accept=_ACCEPT, max_age=ARTIST_PAGE_MAX_AGE)
    except RobotsClosed:  # redirected where caracole may not go: no page it may read
        return None
    if stale(resp, run.now, ARTIST_PAGE_MAX_AGE):
        raise BudgetExhausted(PROVIDER)  # no answer for today: stop as the next request would have
    return read_once_more(run.client, resp, url, _listing, GtpTabsParseError, fetched=run.fetched, accept=_ACCEPT)


def _listing(resp: Response) -> list[GtpTab] | None:
    return None if resp.status == 404 else parse_artist_page(resp.text, resp.url)


def _download(run: _Pass, tab: GtpTab) -> tuple[bytes, str] | None:
    """The upload's file and the extension its bytes say; None, and the upload passed over for
    30 days, when the site answers 404, a page, or a redirect robots.txt closes."""
    url = download_url(tab.tab_id)
    try:
        resp = run.client.get(url, accept=_ACCEPT, cache=False)
    except RobotsClosed as e:
        log.info("gtptabs.com: %s", e)
        resp = None
    ext = sniff(resp.content) if resp is not None and resp.status == 200 else None
    if ext is not None:
        run.pages_in_a_row = 0
        return resp.content, ext
    kv_set(run.conn, f"{_UNUSABLE_PREFIX}{tab.tab_id}", run.stamp)
    if resp is not None and resp.status == 200:
        run.pages_in_a_row += 1
        if run.pages_in_a_row >= PAGES_IN_A_ROW:
            raise PagesNotFiles(PROVIDER, url, 200,
                                f"{run.pages_in_a_row} downloads in a row answered with a page, not a file")
    return None


def _keep(run: _Pass, song: Song, tab: GtpTab, data: bytes, ext: str) -> str:
    """Keep the file as the song's next ``guitar-N``, with its version and info.json; return its name."""
    version_id = upsert_version(
        run.conn, provider=PROVIDER, tab_id=str(tab.tab_id), song_id=song.id, slot="guitar",
        kind="power" if ext == ".ptb" else "guitar-pro", rating=tab.stars, votes=0, version=tab.version,
        label=None, url=page_url(tab.path),
        raw={"title": tab.title, "format": tab.format, "size_kb": tab.size_kb,
             "instruments": list(tab.instruments), "download": download_url(tab.tab_id)},
        now=run.stamp,
    )
    number = guitar_number(run.conn, run.library_dir, song, 1)
    name = f"guitar-{number}{ext}"
    keep_file(run.conn, run.library_dir, song=song, version_id=version_id, name=name, data=data, rank=number)
    write_info(run.conn, run.library_dir, get_song(run.conn, song.id))
    return name


# --- small helpers --------------------------------------------------------------------------------------------


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str | None) -> datetime | None:
    try:
        return _utc(datetime.fromisoformat(value)) if value else None
    except ValueError:
        return None


def _before(stamp: str | None, cutoff: datetime) -> bool:
    """Whether a stored time is older than ``cutoff``; a missing or unreadable one is."""
    when = _parse(stamp)
    return when is None or when < cutoff
