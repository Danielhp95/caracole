"""iReal Pro's forum's thread pages in a local index, and its playlists read into it, so that a song meets a chart
whose thread isn't named for it.

The sitemaps (ireal_fetch.py, ``ireal_index``) name every thread by its slug alone: a song's thread is found by its
title's words, but a playlist's ("jazz-1460-standards") names none of its tunes. Each thread page caracole reads goes
into ``ireal_threads`` and ``ireal_charts`` (db.py, schema 17): its title, its forum, and each chart its posts hold,
with its title and composer, in place of those it gave before, in one transaction; a page that answers 404 keeps no
chart, and its row says it is gone (no title). A song's fetch reads these first, from the cache, with no request.

**Reading the playlists** (``playlist_pass``): the sitemaps first, when due (site_index.py: once in 30 days), then the
curated playlist, the Jazz 1460 Standards (``ireal.JAZZ_1460``), then the jazz forum's page (``ireal.PLAYLIST_FORUMS``),
whose sticky threads are its playlists (gypsy jazz, Dixieland, fusion, the Jazz 1460's New 50 and individual songs…),
kept in kv ``ireal:forums``, then each of those. Each page is read again after 30 days (``MAX_AGE``), its first page
alone, as every thread is. Every request is the client's, with its budget and its pauses, so a pass the budget cuts
short goes on where it stopped the next time. ``caracole ireal --index`` makes a pass at the bulk pace with a budget of
its own (``--budget``); the nightly run's ireal step reads the curated playlist before its songs (``first=1``), and
the rest with what its budget leaves after them.

A block propagates. A spent budget, or a client that gives up on the site for the run, ends a pass. Any other
provider error (a page that won't parse, fetched again included) counts as an error and leaves what the index held
of that page: an error is never a playlist without charts. ``index_state`` says how far it has got, for the step's
line, the command and the pages' "where caracole looked". After a change to caracole's keys (``normalize.KEY_VERSION``)
the charts' title keys are made again from their titles, with no request (``ensure_current_keys``); the slugs' keys
are the sitemaps', made again with them.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from caracole import normalize, site_index, stamps
from caracole.db import kv_get, kv_get_json, kv_set, kv_set_json, savepoint
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
from caracole.ireal import (
    JAZZ_1460,
    PLAYLIST_FORUMS,
    PROVIDER,
    IRealParseError,
    ThreadPage,
    page_url,
    parse_forum_page,
    parse_thread_page,
    thread_of,
    title_key,
)

log = logging.getLogger(__name__)

MAX_AGE = timedelta(days=30)  # a playlist's page and a forum's are read again after this
KEYS_KEY = "ireal:charts:keys"  # the KEY_VERSION the charts' title keys were made with
FORUMS_KEY = "ireal:forums"  # {forum path: {"read_at": stamp, "sticky": [thread paths]}}
_ACCEPT = (200, 404)  # a 404 is an answer: the thread, or the forum, is gone


@dataclass
class PlaylistStats:
    """What one ``playlist_pass`` did: the sitemap reads stored, the forum pages read, the playlist pages read (from
    the site or its cache; ``gone``, those that answered 404, among them), the errors (the sitemaps', ``sitemap_error``,
    and the pages'), and whether the budget ended it."""

    sitemaps: int = 0
    forums: int = 0
    read: int = 0
    gone: int = 0
    errors: int = 0
    budget_exhausted: bool = False
    sitemap_error: bool = False


@dataclass(frozen=True)
class IndexState:
    """How far the index has got: the threads the sitemaps list (``threads``), the thread pages read (``read``), the
    charts they held (``charts``), the playlist forums' pages read (``forums``), and the playlists caracole knows of
    (``playlists``: the curated one, and the sticky threads of the forums read) and has read (``playlists_read``)."""

    threads: int
    read: int
    charts: int
    forums: int
    playlists: int
    playlists_read: int

    @property
    def complete(self) -> bool:
        """Every playlist forum's page read, and every playlist, at least once."""
        return self.forums >= len(PLAYLIST_FORUMS) and self.playlists_read >= self.playlists > 0


# --- the tables -----------------------------------------------------------------------------------------------------


def store_thread_page(conn: sqlite3.Connection, page: ThreadPage, now: datetime) -> None:
    """A thread page's charts into the index, in place of those it gave before, in one transaction."""
    ensure_current_keys(conn)
    rows = [(page.path, post.post, place, tune.title, title_key(tune.title), tune.composer, tune.style, tune.key,
             tune.playlist) for post, place, tune in page.charts()]
    with savepoint(conn, "ireal_thread_page"):
        conn.execute("DELETE FROM ireal_charts WHERE page = ?", (page.path,))
        conn.execute("INSERT OR REPLACE INTO ireal_threads (path, thread, title, forum, charts, read_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (page.path, page.thread, page.title, page.forum, len(rows), stamps.stamp(now)))
        conn.executemany("INSERT OR REPLACE INTO ireal_charts (page, post, place, title, title_key, composer, style, "
                         "key, playlist) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def store_gone(conn: sqlite3.Connection, path: str, now: datetime) -> None:
    """A thread page that answered 404: no chart, no title, and when it answered."""
    store_thread_page(conn, ThreadPage(path, thread_of(path) or 0, "", "", ()), now)


def ensure_current_keys(conn: sqlite3.Connection) -> int:
    """Make every chart's title key again from its title after a change to caracole's keys, once; no request.
    Returns how many rows changed."""
    version = str(normalize.KEY_VERSION)
    if kv_get(conn, KEYS_KEY) == version:
        return 0
    changed = 0
    with savepoint(conn, "ireal_chart_keys"):
        for page, post, place, title, old in conn.execute(
                "SELECT page, post, place, title, title_key FROM ireal_charts").fetchall():
            new = title_key(title)
            if new != old:
                conn.execute("UPDATE ireal_charts SET title_key = ? WHERE page = ? AND post = ? AND place = ?",
                             (new, page, post, place))
                changed += 1
        kv_set(conn, KEYS_KEY, version)
    return changed


def playlists(conn: sqlite3.Connection) -> list[str]:
    """The playlists caracole reads, in turn: the curated one, then each playlist forum's sticky threads, in the order
    its page lists them (those of the forums read)."""
    forums = kv_get_json(conn, FORUMS_KEY, default={}) or {}
    found = [JAZZ_1460]
    for forum in PLAYLIST_FORUMS:
        entry = forums.get(forum) if isinstance(forums, dict) else None
        sticky = entry.get("sticky") if isinstance(entry, dict) else None
        found += [p for p in sticky or () if isinstance(p, str) and thread_of(p) is not None]
    return list(dict.fromkeys(found))


def index_state(conn: sqlite3.Connection) -> IndexState:
    """The index's ``IndexState``; no request."""
    threads = conn.execute("SELECT COUNT(*) FROM ireal_index").fetchone()[0]
    read, charts = conn.execute("SELECT COUNT(*), COALESCE(SUM(charts), 0) FROM ireal_threads").fetchone()
    forums = kv_get_json(conn, FORUMS_KEY, default={}) or {}
    known = playlists(conn)
    marks = ", ".join("?" for _ in known)
    done = conn.execute(f"SELECT COUNT(*) FROM ireal_threads WHERE path IN ({marks})", known).fetchone()[0]
    return IndexState(threads, read, charts, sum(f in forums for f in PLAYLIST_FORUMS) if isinstance(forums, dict)
                      else 0, len(known), done)


# --- reading pages --------------------------------------------------------------------------------------------------


def read_thread(conn: sqlite3.Connection, client: Client, path: str, now: datetime, *,
                fetched: set[str] | None = None, max_age: timedelta | None = MAX_AGE) -> ThreadPage | None:
    """One thread page into the index now; None when the site no longer has it (404). Read once in ``max_age``: a copy
    the cache holds from within it is read again, with no request (with None, the cache's copy, whenever it is from).
    A cached copy that won't parse is asked for once more. Provider errors propagate; a spent budget is
    ``BudgetExhausted``."""
    url = page_url(path)
    resp = client.get(url, accept=_ACCEPT, max_age=max_age) if max_age is not None else client.get(url, accept=_ACCEPT)
    if max_age is not None and stale(resp, now, max_age):
        raise BudgetExhausted(PROVIDER)  # no answer for today: stop as the next request would have
    page = read_once_more(client, resp, url, _thread, IRealParseError, fetched=fetched if fetched is not None else set(),
                          accept=_ACCEPT)
    if page is None:
        store_gone(conn, path, now)
    else:
        store_thread_page(conn, page, now)
    return page


def _thread(resp: Response) -> ThreadPage | None:
    return None if resp.status == 404 else parse_thread_page(resp.content, resp.url)


def _read_forum(conn: sqlite3.Connection, client: Client, forum: str, now: datetime, fetched: set[str]) -> None:
    url = page_url(forum)
    resp = client.get(url, accept=_ACCEPT, max_age=MAX_AGE)
    if stale(resp, now, MAX_AGE):
        raise BudgetExhausted(PROVIDER)
    page = read_once_more(client, resp, url, lambda r: None if r.status == 404 else parse_forum_page(r.content, r.url),
                          IRealParseError, fetched=fetched, accept=_ACCEPT)
    forums = kv_get_json(conn, FORUMS_KEY, default={}) or {}
    forums = forums if isinstance(forums, dict) else {}
    forums[forum] = {"read_at": stamps.stamp(now), "sticky": list(page.sticky) if page is not None else []}
    kv_set_json(conn, FORUMS_KEY, forums)


def _forums_due(conn: sqlite3.Connection, now: datetime) -> list[str]:
    forums = kv_get_json(conn, FORUMS_KEY, default={}) or {}
    forums = forums if isinstance(forums, dict) else {}
    cutoff = now - MAX_AGE
    return [f for f in PLAYLIST_FORUMS
            if stamps.before((forums.get(f) or {}).get("read_at") if isinstance(forums.get(f), dict) else None, cutoff)]


def _due(conn: sqlite3.Connection, now: datetime, known: list[str]) -> list[str]:
    cutoff = now - MAX_AGE
    read = dict(conn.execute("SELECT path, read_at FROM ireal_threads").fetchall())
    return [p for p in known if stamps.before(read.get(p), cutoff)]


def playlist_pass(conn: sqlite3.Connection, client: Client, now: datetime, *, refresh_index: bool = True,
                  first: int | None = None) -> PlaylistStats:
    """The sitemaps when due (``refresh_index``), then the playlists not read in 30 days, the curated one first, the
    playlist forums' pages before the threads they list, until the budget ends it; with ``first``, only that many of
    the playlists (``first=1``: the curated one alone). See the module docstring.

    ``ProviderBlocked`` propagates. A spent budget ends the pass (``budget_exhausted``), and so does a client that
    gives up on the site for the run. Any other ``ProviderError`` counts in ``errors``: the sitemaps' leaves the index
    as it was, and the pass reads its playlists; a page's leaves that page as the index has it."""
    from caracole.ireal_fetch import SITE

    stats = PlaylistStats()
    now = stamps.utc(now)
    ensure_current_keys(conn)

    def sitemap_read() -> None:
        stats.sitemaps += 1

    fetched: set[str] = set()

    def step(what, read) -> bool:
        """One read; False once the pass must end."""
        try:
            read()
        except ProviderBlocked:
            raise
        except BudgetExhausted:
            stats.budget_exhausted = True
            return False
        except ProviderUnavailable as e:
            log.info("iReal Pro's forum is unavailable for the rest of this run: %s", e)
            return False
        except ProviderError as e:
            stats.errors += 1
            log.warning("iReal Pro's forum, %s: %s", what, e)
        return True

    if refresh_index:
        try:
            site_index.refresh(conn, client, SITE, now, on_read=sitemap_read)
        except ProviderBlocked:
            raise
        except BudgetExhausted:
            stats.budget_exhausted = True
            return stats
        except ProviderUnavailable as e:
            log.info("iReal Pro's forum is unavailable for the rest of this run: %s", e)
            return stats
        except ProviderError as e:
            stats.errors += 1
            stats.sitemap_error = True
            log.warning("iReal Pro's forum's sitemaps: %s", e)

    def read(path: str) -> bool:
        """A playlist's page, when due; False once the pass must end."""
        if not _due(conn, now, [path]):
            return True
        result: list[ThreadPage | None] = []
        errors = stats.errors
        if not step(f"the thread {path}", lambda: result.append(read_thread(conn, client, path, now,
                                                                            fetched=fetched))):
            return False
        if stats.errors == errors:
            stats.read += 1
            stats.gone += result[0] is None
        return True

    if not read(JAZZ_1460) or first == 1:
        return stats
    for forum in _forums_due(conn, now):
        errors = stats.errors
        if not step(f"its forum {forum}", lambda forum=forum: _read_forum(conn, client, forum, now, fetched)):
            return stats
        stats.forums += stats.errors == errors
    for path in playlists(conn)[1:(first if first is not None else None)]:
        if not read(path):
            break
    return stats
