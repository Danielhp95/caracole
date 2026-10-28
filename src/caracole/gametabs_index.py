"""gametabs.net's game pages in a local index, so that a song is found by its composer as well as by its game.

gametabs.net's sitemaps (gametabs_fetch.py, ``gametabs_index``) name every tab by its game and its title alone.
Who composed it and what it is for are on its game's page (gametabs.py ``parse_game_page``), which robots.txt
allows: every tab of the game, 50 a page (its next pages, ``?page=2``…, the sitemap lists too), each with its
composers, its instruments, its views and its fun rating. Each page read goes into ``gametabs_games`` and
``gametabs_game_tabs`` (db.py, schema 13), its tabs in place of those it gave before, in one transaction; a page
that answers 404 keeps no tab, and its row says it is gone (no name). Never a tab page: those are read for your
songs alone (gametabs_fetch.py).

**Reading them** (``game_pass``): the sitemaps first, when due (site_index.py: once in 30 days), then each game
page not read in 30 days, those of your songs first (a game one of your songs' artists names, or one with a tab
titled as one of your songs), then the rest in the sitemap's order, by their paths. Every request is the
client's, with its budget and its pauses (10–20 s, never under robots.txt's 5 s), so a pass the budget cuts short
goes on where it stopped the next time: what it read is in the table, with when. A page is cached for good, as
every answer is, and asked for again after 30 days (``GAME_MAX_AGE``). ``caracole gametabs --index`` makes a pass
at the bulk pace with a budget of its own (``--budget``), and the nightly run's gametabs step spends what its
budget leaves on one. About 1,660 pages at 10–20 s a request: some 7 hours of requests in all.

A block propagates. A spent budget, or a client that gives up on the site for the run, ends a pass. Any other
provider error (a page that won't parse, fetched again included) counts as an error and leaves what the index
held of that page, to be asked for again on the next pass: an error is never a game without tabs.
``index_state`` says how far the index has got, for the step's line, the command and the pages' "where caracole
looked". After a change to caracole's keys (``normalize.KEY_VERSION``) the tabs' title keys are made again from
their titles, with no request (``ensure_current_keys``); the slugs' keys are the sitemaps', made again with them.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from caracole import normalize, site_index, stamps
from caracole.db import kv_get, kv_set, savepoint
from caracole.gametabs import (
    GAME,
    PROVIDER,
    TAB,
    GamePage,
    GameTabsParseError,
    page_url,
    parse_game_page,
    title_key,
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
from caracole.normalize import compact
from caracole.overrides import Overrides
from caracole.songs import list_songs

log = logging.getLogger(__name__)

GAME_MAX_AGE = timedelta(days=30)  # a game page is read again after this
KEYS_KEY = "gametabs:games:keys"  # the KEY_VERSION the tabs' title keys were made with
_ACCEPT = (200, 404)  # a 404 is an answer: the game is gone
_GAME_PATH = re.compile(r"tabs/([a-z0-9-]{1,200})(?:\?page=[1-9][0-9]{0,3})?")


@dataclass
class GamePassStats:
    """What one ``game_pass`` did: the sitemap reads stored, the game pages read (from the site or its cache;
    ``gone``, those that answered 404, among them), the errors (the sitemaps', ``sitemap_error``, and the pages'),
    and whether the budget ended it."""

    sitemaps: int = 0
    read: int = 0
    gone: int = 0
    errors: int = 0
    budget_exhausted: bool = False
    sitemap_error: bool = False


@dataclass(frozen=True)
class IndexState:
    """How far the index has got: the game pages the sitemaps list (``pages``), those caracole has read (``read``),
    and the tabs those pages listed (``tabs``)."""

    pages: int
    read: int
    tabs: int

    @property
    def complete(self) -> bool:
        """Every game page read, at least once."""
        return self.pages > 0 and self.read >= self.pages


# --- the table ------------------------------------------------------------------------------------------------------


def game_of(path: str) -> str:
    """A game page's game, its slug, from its path ("tabs/final-fantasy-vii?page=2": final-fantasy-vii)."""
    found = _GAME_PATH.fullmatch(path)
    return found.group(1) if found else ""


def store_game_page(conn: sqlite3.Connection, path: str, page: GamePage, now: datetime) -> None:
    """A game page's tabs into the index, in place of those it gave before, in one transaction."""
    ensure_current_keys(conn)
    game = game_of(path)
    with savepoint(conn, "gametabs_game_page"):
        conn.execute("DELETE FROM gametabs_game_tabs WHERE page = ?", (path,))
        conn.execute("INSERT OR REPLACE INTO gametabs_games (path, game, name, tabs, read_at) VALUES (?, ?, ?, ?, ?)",
                     (path, game, page.name, page.tabs, stamps.stamp(now)))
        conn.executemany(
            "INSERT OR REPLACE INTO gametabs_game_tabs (page, path, game, title, title_key, instruments, composers, "
            "views, rating, place) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(path, t.path, t.path.split("/")[1], t.title, title_key(t.title),
              json.dumps(list(t.instruments), ensure_ascii=False), json.dumps(list(t.composers), ensure_ascii=False),
              t.views, t.rating, n) for n, t in enumerate(page.listed)])


def store_gone(conn: sqlite3.Connection, path: str, now: datetime) -> None:
    """A game page that answered 404: no tab, no name, and when it answered."""
    store_game_page(conn, path, GamePage("", 0), now)


def ensure_current_keys(conn: sqlite3.Connection) -> int:
    """Make every tab's title key again from its title after a change to caracole's keys, once; no request.
    Returns how many rows changed."""
    version = str(normalize.KEY_VERSION)
    if kv_get(conn, KEYS_KEY) == version:
        return 0
    changed = 0
    with savepoint(conn, "gametabs_game_keys"):
        for page, path, title, old in conn.execute(
                "SELECT page, path, title, title_key FROM gametabs_game_tabs").fetchall():
            new = title_key(title)
            if new != old:
                conn.execute("UPDATE gametabs_game_tabs SET title_key = ? WHERE page = ? AND path = ?",
                             (new, page, path))
                changed += 1
        kv_set(conn, KEYS_KEY, version)
    return changed


def index_state(conn: sqlite3.Connection) -> IndexState:
    """The index's ``IndexState``; no request. A page the sitemaps no longer list counts in neither."""
    pages, read = conn.execute(
        "SELECT COUNT(*), COUNT(g.path) FROM gametabs_index i LEFT JOIN gametabs_games g ON g.path = i.path "
        "WHERE i.kind = ?", (GAME,)).fetchone()
    tabs = conn.execute("SELECT COUNT(*) FROM gametabs_game_tabs t WHERE EXISTS "
                        "(SELECT 1 FROM gametabs_index i WHERE i.path = t.page)").fetchone()[0]
    return IndexState(pages, read, tabs)


# --- reading pages --------------------------------------------------------------------------------------------------


def read_game(conn: sqlite3.Connection, client: Client, path: str, now: datetime) -> GamePage | None:
    """One game page into the index now; None when the site no longer has it (404). Read once in 30 days: a copy the
    cache holds from within them is read again, with no request. A cached copy that won't parse is asked for once
    more. Provider errors propagate; a spent budget is ``BudgetExhausted``."""
    return _read(conn, client, path, now, set())


def _read(conn: sqlite3.Connection, client: Client, path: str, now: datetime, fetched: set[str]) -> GamePage | None:
    url = page_url(path)
    resp = client.get(url, accept=_ACCEPT, max_age=GAME_MAX_AGE)
    if stale(resp, now, GAME_MAX_AGE):
        raise BudgetExhausted(PROVIDER)  # no answer for today: stop as the next request would have
    page = read_once_more(client, resp, url, _page, GameTabsParseError, fetched=fetched, accept=_ACCEPT)
    if page is None:
        store_gone(conn, path, now)
    else:
        store_game_page(conn, path, page, now)
    return page


def _page(resp: Response) -> GamePage | None:
    return None if resp.status == 404 else parse_game_page(resp.content, resp.url)


def game_pass(conn: sqlite3.Connection, client: Client, now: datetime, *, overrides: Overrides | None = None,
              refresh_index: bool = True) -> GamePassStats:
    """The sitemaps when due (``refresh_index``), then the game pages not read in 30 days, your songs' first, then in
    the sitemap's order, until the budget ends it; see the module docstring.

    ``ProviderBlocked`` propagates. A spent budget ends the pass (``budget_exhausted``), and so does a client that
    gives up on the site for the run. Any other ``ProviderError`` counts in ``errors``: the sitemaps' leaves the
    index as it was, and the pass reads the pages it lists; a page's leaves that page as the index has it."""
    from caracole.gametabs_fetch import SITE

    stats = GamePassStats()
    now = stamps.utc(now)
    ensure_current_keys(conn)

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
        log.info("gametabs.net is unavailable for the rest of this run: %s", e)
        return stats
    except ProviderError as e:
        stats.errors += 1
        stats.sitemap_error = True
        log.warning("gametabs.net's sitemaps: %s", e)
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
            log.info("gametabs.net is unavailable for the rest of this run: %s", e)
            break
        except ProviderError as e:
            stats.errors += 1
            log.warning("gametabs.net's page of %s: %s", path, e)
            continue
        stats.read += 1
        stats.gone += page is None
    return stats


def _due(conn: sqlite3.Connection, now: datetime, overrides: Overrides | None) -> list[str]:
    """The game pages to read, in turn: those never read, or not in 30 days, your songs' games first."""
    cutoff = now - GAME_MAX_AGE
    rows = conn.execute(
        "SELECT i.path, i.game, i.key, g.read_at FROM gametabs_index i LEFT JOIN gametabs_games g "
        "ON g.path = i.path WHERE i.kind = ?", (GAME,)).fetchall()
    due = [(path, game, key) for path, game, key, read_at in rows if stamps.before(read_at, cutoff)]
    if not due:
        return []
    yours = _your_games(conn, overrides)
    due.sort(key=lambda r: (r[1] not in yours, r[0]))
    return [path for path, _, _ in due]


def _your_games(conn: sqlite3.Connection, overrides: Overrides | None) -> set[str]:
    """The games of your songs (not an ignored song's), by their slugs: one an artist of theirs names, or one with a
    tab titled as one of them."""
    from caracole.gametabs_fetch import song_forms

    ignored = overrides.ignore if overrides is not None else frozenset()
    songs = [s for s in list_songs(conn) if s.status != "ignored" and s.key not in ignored]
    if not songs:
        return set()
    forms = set().union(*(song_forms(s) for s in songs))
    titles = {key for s in songs if (key := title_key(s.title))}
    found = {game for game, key in conn.execute("SELECT DISTINCT game, key FROM gametabs_index WHERE kind = ?",
                                                (GAME,)) if compact(key) in forms}
    found.update(game for game, key, whole in conn.execute(
        "SELECT game, key, slug_key FROM gametabs_index WHERE kind = ?", (TAB,)) if key in titles or whole in titles)
    return found
