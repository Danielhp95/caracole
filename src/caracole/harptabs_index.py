"""harptabs.com's artist pages in a local index, so that a search finds its tabs by artist as well as by title.

harptabs.com's sitemap (harptabs_fetch.py, ``harptabs_index``) names every tab by its title alone and
every artist by a slug. What tabs an artist has is on their page (harptabs.py ``parse_artist_page``),
which robots.txt allows: its 30 most viewed tabs, and how many the artist has (the rest come from the
site's API, which robots.txt closes). Each page read goes into ``harptabs_artists`` and
``harptabs_artist_tabs`` (db.py, schema 11), its tabs in place of those it gave before, in one
transaction; a page that answers 404 keeps no tab, and its row says it is gone (no name).

**Reading them** (``artist_pass``): the sitemap first, when due (site_index.py: once in 30 days), then
each artist page not read in 30 days, the artists of your songs first (their names' forms,
``normalize.name_forms``, meeting the slugs' keys, hyphens aside), then the rest in the sitemap's order,
by the site's ids. Every request is the client's, with its budget and its pauses, so a pass the budget
cuts short goes on where it stopped the next time: what it read is in the table, with when. A page is
cached for good, as every answer is, and asked for again after 30 days (``ARTIST_MAX_AGE``). ``caracole
harptabs --index`` makes a pass at the bulk pace with a budget of its own (``--budget``), and the
nightly run's harptabs step spends what its budget leaves on one. About 10,400 artists at 10–20 s a
request: some 44 hours of requests in all.

**One page now** (``read_artist``): what an artist's Songs on caracole serve's pages asks for, as
``caracole harptabs --artist`` (a lookup's pace), once in 30 days too.

A block propagates. A spent budget, or a client that gives up on the site for the run, ends a pass. Any
other provider error (a page that won't parse, fetched again included) counts as an error and leaves
what the index held of that artist, to be asked for again on the next pass: an error is never an artist
without tabs. ``index_state`` says how far the index has got, for ``caracole index stats`` and the
pages' "where caracole looked". After a change to caracole's keys (``normalize.KEY_VERSION``) the songs'
keys are made again from the tabs' titles, with no request (``ensure_current_keys``); the slugs' keys
are the sitemap's, made again with it.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from caracole import normalize, site_index, stamps
from caracole.db import kv_get, kv_set, savepoint
from caracole.harptabs import (
    ARTIST,
    PROVIDER,
    ArtistPage,
    HarpTabsParseError,
    page_url,
    parse_artist_page,
    parse_page_url,
    song_key,
)
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
from caracole.normalize import compact, name_forms
from caracole.overrides import Overrides
from caracole.songs import list_songs

log = logging.getLogger(__name__)

ARTIST_MAX_AGE = timedelta(days=30)  # an artist page is read again after this
KEYS_KEY = "harptabs:artists:keys"  # the KEY_VERSION the songs' keys were made with
_ACCEPT = (200, 404)  # a 404 is an answer: the artist is gone
_ADDRESS = re.compile(r"(?:https?://)?(?:www\.)?harptabs\.com/(artist/\d{1,9}/[a-z0-9-]{1,200})/?")


@dataclass
class ArtistPassStats:
    """What one ``artist_pass`` did: the sitemap reads stored, the artist pages read (from the site or its cache;
    ``gone``, those that answered 404, among them), the errors (the sitemap's, ``sitemap_error``, and the
    pages'), and whether the budget ended it."""

    sitemaps: int = 0
    read: int = 0
    gone: int = 0
    errors: int = 0
    budget_exhausted: bool = False
    sitemap_error: bool = False


@dataclass(frozen=True)
class IndexState:
    """How far the index has got: the artists the sitemap lists (``artists``), those whose page caracole has read
    (``read``), and the tabs those pages listed (``tabs``)."""

    artists: int
    read: int
    tabs: int

    @property
    def complete(self) -> bool:
        """Every artist's page read, at least once."""
        return self.artists > 0 and self.read >= self.artists


# --- the table ------------------------------------------------------------------------------------------------


def _row_of(path: str) -> tuple[int, str]:
    """An artist page's id and its slug's key, from its path."""
    row = parse_page_url(page_url(path))
    if row is not None:
        return row.page_id, row.key
    found = re.match(r"artist/(\d+)", path)
    return (int(found.group(1)) if found else 0), ""


def store_artist_page(conn: sqlite3.Connection, path: str, page: ArtistPage, now: datetime) -> None:
    """An artist page's tabs into the index, in place of those it gave before, in one transaction."""
    ensure_current_keys(conn)
    page_id, key = _row_of(path)
    with savepoint(conn, "harptabs_artist_page"):
        conn.execute("DELETE FROM harptabs_artist_tabs WHERE artist = ?", (path,))
        conn.execute("INSERT OR REPLACE INTO harptabs_artists (path, page_id, key, name, tabs, read_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (path, page_id, key, page.name, page.tabs, stamps.stamp(now)))
        conn.executemany(
            "INSERT OR REPLACE INTO harptabs_artist_tabs (artist, tab_id, path, title, song_key, harp_key, "
            "difficulty, views, rating, place) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(path, t.tab_id, t.path, t.title, song_key(t.title), t.key, t.difficulty, t.views, t.rating, n)
             for n, t in enumerate(page.listed)])


def store_gone(conn: sqlite3.Connection, path: str, now: datetime) -> None:
    """An artist page that answered 404: no tab, no name, and when it answered."""
    store_artist_page(conn, path, ArtistPage("", 0), now)


def ensure_current_keys(conn: sqlite3.Connection) -> int:
    """Make every tab's song key again from its title after a change to caracole's keys, once; no request.
    Returns how many rows changed."""
    version = str(normalize.KEY_VERSION)
    if kv_get(conn, KEYS_KEY) == version:
        return 0
    changed = 0
    with savepoint(conn, "harptabs_artist_keys"):
        for artist, tab_id, title, old in conn.execute(
                "SELECT artist, tab_id, title, song_key FROM harptabs_artist_tabs").fetchall():
            new = song_key(title)
            if new != old:
                conn.execute("UPDATE harptabs_artist_tabs SET song_key = ? WHERE artist = ? AND tab_id = ?",
                             (new, artist, tab_id))
                changed += 1
        kv_set(conn, KEYS_KEY, version)
    return changed


def index_state(conn: sqlite3.Connection) -> IndexState:
    """The index's ``IndexState``; no request. An artist the sitemap no longer lists counts in neither."""
    artists, read = conn.execute(
        "SELECT COUNT(*), COUNT(a.path) FROM harptabs_index i LEFT JOIN harptabs_artists a ON a.path = i.path "
        "WHERE i.kind = ?", (ARTIST,)).fetchone()
    tabs = conn.execute("SELECT COUNT(*) FROM harptabs_artist_tabs t WHERE EXISTS "
                        "(SELECT 1 FROM harptabs_index i WHERE i.path = t.artist)").fetchone()[0]
    return IndexState(artists, read, tabs)


def artist_paths(conn: sqlite3.Connection, name: str) -> list[str]:
    """The artist pages the sitemap lists for ``name``: its page's path or address as it is, else the artists
    whose slug's key is one of the name's forms (``normalize.name_forms``), hyphens aside, lowest id first."""
    text = " ".join(name.split())
    found = _ADDRESS.fullmatch(text) or re.fullmatch(r"(artist/\d{1,9}/[a-z0-9-]{1,200})", text)
    if found is not None:
        listed = conn.execute("SELECT path FROM harptabs_index WHERE path = ? AND kind = ?",
                              (found.group(1), ARTIST)).fetchone()
        return [listed[0]] if listed is not None else []
    forms = {compact(f) for f in name_forms(text) if f}
    if not forms:
        return []
    rows = conn.execute("SELECT path, key FROM harptabs_index WHERE kind = ? ORDER BY page_id", (ARTIST,))
    return [path for path, key in rows if compact(key) in forms]


# --- reading pages --------------------------------------------------------------------------------------------


def read_artist(conn: sqlite3.Connection, client: Client, path: str, now: datetime) -> ArtistPage | None:
    """One artist page into the index now, as an artist's Songs asks for it; None when the site no longer has it
    (404). Read once in 30 days: a copy the cache holds from within them is read again, with no request. A cached
    copy that won't parse is asked for once more. Provider errors propagate; a spent budget is
    ``BudgetExhausted``."""
    return _read(conn, client, path, now, set())


def _read(conn: sqlite3.Connection, client: Client, path: str, now: datetime, fetched: set[str]) -> ArtistPage | None:
    url = page_url(path)
    resp = client.get(url, accept=_ACCEPT, max_age=ARTIST_MAX_AGE)
    if stale(resp, now, ARTIST_MAX_AGE):
        raise BudgetExhausted(PROVIDER)  # no answer for today: stop as the next request would have
    page = read_once_more(client, resp, url, _page, HarpTabsParseError, fetched=fetched, accept=_ACCEPT)
    if page is None:
        store_gone(conn, path, now)
    else:
        store_artist_page(conn, path, page, now)
    return page


def _page(resp: Response) -> ArtistPage | None:
    return None if resp.status == 404 else parse_artist_page(resp.content, resp.url)


def artist_pass(conn: sqlite3.Connection, client: Client, now: datetime, *, overrides: Overrides | None = None,
                refresh_index: bool = True) -> ArtistPassStats:
    """The sitemap when due (``refresh_index``), then the artist pages not read in 30 days, your songs' artists
    first, then in the sitemap's order, until the budget ends it; see the module docstring.

    ``ProviderBlocked`` propagates. A spent budget ends the pass (``budget_exhausted``), and so does a client that
    gives up on the site for the run. Any other ``ProviderError`` counts in ``errors``: the sitemap's leaves the
    index as it was, and the pass reads the artists it lists; a page's leaves that artist as the index has them."""
    from caracole.harptabs_fetch import SITE

    stats = ArtistPassStats()
    now = stamps.utc(now)

    def sitemap_read() -> None:
        stats.sitemaps += 1

    try:
        if refresh_index:
            site_index.refresh(conn, client, SITE, now, on_read=sitemap_read)
    except ProviderBlocked:
        raise
    except BudgetExhausted:
        stats.budget_exhausted = True
        return stats
    except ProviderUnavailable as e:
        log.info("harptabs.com is unavailable for the rest of this run: %s", e)
        return stats
    except ProviderError as e:
        stats.errors += 1
        stats.sitemap_error = True
        log.warning("harptabs.com's sitemap: %s", e)
    fetched: set[str] = set()
    for path in _due(conn, now, overrides):
        try:
            page = _read(conn, client, path, now, fetched)
        except ProviderBlocked:
            raise
        except BudgetExhausted:
            stats.budget_exhausted = True
            break
        except ProviderUnavailable as e:
            log.info("harptabs.com is unavailable for the rest of this run: %s", e)
            break
        except ProviderError as e:
            stats.errors += 1
            log.warning("harptabs.com's page of %s: %s", path, e)
            continue
        stats.read += 1
        stats.gone += page is None
    return stats


def _due(conn: sqlite3.Connection, now: datetime, overrides: Overrides | None) -> list[str]:
    """The artist pages to read, in turn: those never read, or not in 30 days, your songs' artists first."""
    cutoff = now - ARTIST_MAX_AGE
    rows = conn.execute(
        "SELECT i.path, i.page_id, i.key, a.read_at FROM harptabs_index i LEFT JOIN harptabs_artists a "
        "ON a.path = i.path WHERE i.kind = ?", (ARTIST,)).fetchall()
    due = [(path, page_id, key) for path, page_id, key, read_at in rows if stamps.before(read_at, cutoff)]
    if not due:
        return []
    yours = _your_artists(conn, overrides)
    due.sort(key=lambda r: (compact(r[2]) not in yours, r[1]))
    return [path for path, _, _ in due]


def _your_artists(conn: sqlite3.Connection, overrides: Overrides | None) -> set[str]:
    """Your songs' artists, as compact keys of their names' forms; not an ignored song's."""
    ignored = overrides.ignore if overrides is not None else frozenset()
    return {compact(form) for song in list_songs(conn) if song.status != "ignored" and song.key not in ignored
            for name in song.artists or [song.artist] for form in name_forms(name) if form}

