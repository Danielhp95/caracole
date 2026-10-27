"""harptabs.com in the nightly run: a harmonica tab for each song you want that has none.

What the site looks like is in harptabs.py. A pass:

1. **The index.** harptabs.com's one sitemap is read into ``harptabs_index`` (db.py) by
   site_index.py: when it never was, again after 30 days, and at once after a change to
   caracole's keys. It has no ETag, so each read is the whole sitemap: one request.
2. **Which songs.** Not ignored; with no harmonica tab in the files table (kept here, whether
   or not you deleted it since); not looked up in the last 30 days; and with a candidate: a tab
   whose title is the song's (the sitemap's slugs carry the title alone), by an artist the
   sitemap lists under one of the song's artists' names (never a request). Newest first.
3. **The candidates**, at most ``CANDIDATES``, lowest id first, each read at its page (cached
   for good, as every page is), for its artist, which is kept only when it is one of the
   song's (``normalize.name_forms``, as Ultimate Guitar's artists are compared). Of those
   that are, the most viewed is kept (then the best rated, then the first posted).
4. **The tab** is kept as the song's lowest free ``harmonica-N.txt`` (``inbox.harmonica_number``),
   the page's ``<pre>`` as it is, under a version of provider ``harptabs`` and kind
   ``harmonica`` (its page the URL; its key, harp, difficulty, views and rating in ``raw``), and
   info.json is rewritten. The library page lists it under the song's files, and its viewer's
   data names it (``harmonicaTabs``).

Only songs in wanted.txt are looked up (and a lookup's song): never a page for a song nobody
asked for, never a mirror of the site. Errors are never misses: only candidates that all
answered, none by the song's artist (or each gone, 404), make the song a miss, asked about again
after 30 days (kv ``harptabs:checked:<song id>``). A block propagates, and a spent budget ends
the pass. Any other provider error, a page that won't parse even fetched again included, leaves
the song for the next run. No file is ever replaced or deleted: a song that has a harmonica tab
gets no other.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from caracole import site_index, stamps
from caracole.db import kv_get, kv_set
from caracole.harptabs import (
    ARTIST,
    PROVIDER,
    SITEMAP_URL,
    TAB,
    HarpTab,
    HarpTabsParseError,
    IndexRow,
    page_url,
    parse_page_url,
    parse_tab_page,
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
)
from caracole.inbox import HARMONICA_KIND, harmonica_number
from caracole.library import keep_file, write_info
from caracole.normalize import compact, name_forms
from caracole.overrides import Overrides
from caracole.provider_pass import PassStats, each_song
from caracole.site_index import Site
from caracole.songs import Song, get_song, list_songs
from caracole.versions import upsert_version

log = logging.getLogger(__name__)

INDEX_MAX_AGE = timedelta(days=30)
RECHECK_AFTER = timedelta(days=30)  # a song whose candidates were none of its artist's
CANDIDATES = 8  # a title's tabs read for one song at most, lowest id first
_ACCEPT = (200, 404)  # a 404 is an answer: the tab is gone

CHECKED_PREFIX = "harptabs:checked:"  # + song id: when its candidates last answered for it

KEPT, MISSING = "kept", "missing"


@dataclass
class HarpTabsStats(PassStats):
    """What one ``harptabs_tabs`` pass did. ``sitemaps`` counts the sitemap reads stored; ``tried`` the songs
    looked up, errors included; ``errors`` the songs' and the sitemap's; ``failures`` the songs an error left,
    as every pass names them (provider_pass.py)."""

    sitemaps: int = 0
    kept: int = 0
    missing: int = 0

    @property
    def sitemap_errors(self) -> int:
        """The errors no song's failure stands for: the sitemap's."""
        return self.errors - sum(not isinstance(e, ProviderUnavailable) for _, e in self.failures)


def harptabs_tabs(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    now: datetime,
    *,
    overrides: Overrides | None = None,
    only: Collection[int] | None = None,
    refresh_index: bool = True,
) -> HarpTabsStats:
    """Refresh the index when due, then keep a harmonica tab for each song that needs one and has a candidate.

    See the module docstring. With no song that wants a tab, nothing is sent, not even for the sitemap.
    ``ProviderBlocked`` propagates. ``BudgetExhausted`` ends the pass (``budget_exhausted``), and so does a
    client that gives up on the site for this run (``ProviderUnavailable``): the songs left are ``failures``.
    Any other ``ProviderError`` counts in ``errors``: one from the sitemap leaves the index as it was, and one
    for a song leaves the song for the next run, in ``failures`` with its error.

    A lookup (``caracole get``) passes ``only`` its song's id, and ``refresh_index=False``: the sitemap is the
    nightly run's to read. A song that got a tab meanwhile (from a lookup the nightly run let go first) is
    passed over when its turn comes.
    """
    stats = HarpTabsStats()
    now = stamps.utc(now)
    wanting = [s for s in _songs_wanting_a_tab(conn, now, overrides) if only is None or s.id in only]
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
        log.info("harptabs.com is unavailable for the rest of this run: %s", e)
        index = _Index(conn)
        stats.failures += [(song, e) for song in wanting if index.candidates(song)]
        return stats
    except ProviderError as e:
        stats.errors += 1
        log.warning("harptabs.com's sitemap: %s", e)
    index = _Index(conn)
    run = _Pass(conn, client, Path(library_dir), now)
    # Each song is checked just before its turn: a lookup let in during a pause may have given it a tab.
    songs = (s for s in wanting if index.candidates(s) and s.id not in songs_with_a_harmonica_tab(conn))
    for _, outcome in each_song(songs, stats, lambda song: _look_up(run, song, index), site="harptabs.com",
                                level=logging.WARNING):
        stats.kept += outcome == KEPT
        stats.missing += outcome == MISSING
    return stats


# --- the index ------------------------------------------------------------------------------------

# harptabs.com's one sitemap, as site_index.py reads it into harptabs_index: no sitemap index (``child`` None).
SITE = Site(
    provider=PROVIDER, index_url=SITEMAP_URL, table="harptabs_index", columns=IndexRow._fields,
    child=None, row=parse_page_url, max_age=INDEX_MAX_AGE,
)


class _Index:
    """``harptabs_index`` as a pass reads it: the artists' keys, hyphens aside, loaded once."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.artists = {compact(r[0]) for r in conn.execute("SELECT key FROM harptabs_index WHERE kind = ?",
                                                            (ARTIST,))}

    def candidates(self, song: Song) -> list[tuple[int, str]]:
        """The tabs titled as the song is, ``(id, path)`` lowest id first, at most ``CANDIDATES``; none when
        the sitemap lists no artist by one of the song's artists' names, as then no tab there is theirs."""
        key = title_key(song.title)
        if not key or not any(compact(form) in self.artists for form in _forms(song)):
            return []
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT page_id, path FROM harptabs_index WHERE kind = ? AND key = ? ORDER BY page_id LIMIT ?",
            (TAB, key, CANDIDATES))]


def _forms(song: Song) -> list[str]:
    """The keys the song's artists are compared by (``normalize.name_forms``)."""
    return [form for name in song.artists or [song.artist] for form in name_forms(name) if form]


def same_artist(song: Song, artist: str) -> bool:
    """Whether the artist a tab page names is one of the song's: they share a form, hyphens aside."""
    return not {compact(f) for f in _forms(song)}.isdisjoint(compact(f) for f in name_forms(artist) if f)


# --- which songs ------------------------------------------------------------------------------------


def _songs_wanting_a_tab(conn: sqlite3.Connection, now: datetime, overrides: Overrides | None) -> list[Song]:
    """The songs, newest first, that are not ignored, have no harmonica tab, and weren't looked up on
    harptabs.com in the last 30 days."""
    ignored = overrides.ignore if overrides is not None else frozenset()
    with_tab = songs_with_a_harmonica_tab(conn)
    cutoff = now - RECHECK_AFTER
    return [
        song for song in list_songs(conn)
        if song.status != "ignored" and song.key not in ignored and song.id not in with_tab
        and stamps.before(kv_get(conn, f"{CHECKED_PREFIX}{song.id}"), cutoff)
    ]


def songs_with_a_harmonica_tab(conn: sqlite3.Connection) -> set[int]:
    """The songs the files table holds a harmonica tab for."""
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT f.song_id FROM files f JOIN versions v ON v.id = f.version_id WHERE v.kind = ?",
        (HARMONICA_KIND,))}


# --- one song --------------------------------------------------------------------------------------------


@dataclass
class _Pass:
    conn: sqlite3.Connection
    client: Client
    library_dir: Path
    now: datetime
    fetched: set[str] = field(default_factory=set)  # pages fetched from the site in this pass

    @property
    def stamp(self) -> str:
        return stamps.stamp(self.now)


def _look_up(run: _Pass, song: Song, index: _Index) -> str:
    """Read the song's candidates and keep the most viewed by its artist: ``KEPT``; ``MISSING`` when none is."""
    found: list[tuple[int, str, HarpTab]] = []
    for page_id, path in index.candidates(song):
        tab = _tab(run, page_url(path))
        if tab is not None and same_artist(song, tab.artist):
            found.append((page_id, path, tab))
    if found:
        page_id, path, tab = min(found, key=lambda f: (-f[2].views, -(f[2].rating or 0.0), f[0]))
        _keep(run, song, page_id, path, tab)
    kv_set(run.conn, f"{CHECKED_PREFIX}{song.id}", run.stamp)
    return KEPT if found else MISSING


def _tab(run: _Pass, url: str) -> HarpTab | None:
    """A tab page, read; None when the site no longer has it (404), or sends it where robots.txt closes. A cached
    page that won't parse is asked for once more before it is an error (``http.read_once_more``)."""
    try:
        resp = run.client.get(url, accept=_ACCEPT)
    except RobotsClosed as e:
        log.info("harptabs.com: %s", e)
        return None
    return read_once_more(run.client, resp, url, _page, HarpTabsParseError, fetched=run.fetched, accept=_ACCEPT)


def _page(resp: Response) -> HarpTab | None:
    return None if resp.status == 404 else parse_tab_page(resp.content, resp.url)


def _keep(run: _Pass, song: Song, page_id: int, path: str, tab: HarpTab) -> str:
    """Keep the tab as the song's next ``harmonica-N.txt``, with its version and info.json; return its name."""
    version_id = upsert_version(
        run.conn, provider=PROVIDER, tab_id=str(page_id), song_id=song.id, slot="guitar", kind=HARMONICA_KIND,
        rating=tab.rating or 0.0, votes=tab.views, version=1, label=None, url=page_url(path), raw=tab.raw(),
        now=run.stamp,
    )
    number = harmonica_number(run.conn, run.library_dir, song)
    name = f"harmonica-{number}.txt"
    keep_file(run.conn, run.library_dir, song=song, version_id=version_id, name=name, data=tab.body.encode("utf-8"),
              rank=number)
    write_info(run.conn, run.library_dir, get_song(run.conn, song.id))
    return name
