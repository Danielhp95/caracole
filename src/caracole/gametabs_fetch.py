"""gametabs.net in the nightly run: a text tab of game music for each song you want that has none.

What the site looks like is in gametabs.py. A pass:

1. **The index.** gametabs.net's sitemaps are read into ``gametabs_index`` (db.py) by site_index.py:
   when they never were, again after 30 days, and at once after a change to caracole's keys. Each is
   asked for with its validators, so one unchanged costs a request and isn't parsed.
2. **Which songs.** Not ignored; with no gametabs.net tab in the files table (kept here, whether or
   not you deleted it since); not looked up in the last 30 days; and with a candidate (never a
   request): a tab whose title is the song's, of a game one of the song's artists names (its slug in
   the sitemap, or its name on its page once caracole read it: "Hollow Knight - Resting Grounds"), or
   whose composer one of them is, by the game pages caracole read (gametabs_index.py: "Yuzo Koshiro -
   Fillmore"). Newest first.
3. **The candidates**, at most ``CANDIDATES``, the most viewed first (as the game pages read say; the
   sitemap's order for the rest). Each is read at its page (cached for good, as every page is) and kept
   only when its page agrees: the track's title is the song's (``gametabs.title_key``, so a slug's number
   never stands for a title's), and its game or one of its composers is one of the song's artists
   (``normalize.name_forms``; a game's name with "OST" or "Soundtrack" after it too: ``game_forms``). Of
   those that do, the most viewed is kept (then the best rated, then the first by its page).
4. **The tab** is kept as the song's lowest free ``gametab-N.txt`` (``inbox.gametab_number``), the page's
   ``<pre>`` as it is, under a version of provider ``gametabs`` and kind ``gametab`` (its tab id the page's
   path, ``tabs/actraiser/fillmore``; its page the URL; what the page says of it in ``raw``), and info.json is
   rewritten. The library page lists it with the song's files, a guitar tab, opened as text as Ultimate
   Guitar's ``tab.txt`` is.

A tab you picked (``[gametabs]`` in overrides.toml: caracole serve's Get it on a gametabs.net row,
``caracole get --gametabs``) is read in place of the candidates, for a song that hasn't kept that tab yet,
and kept whatever its page names: beside the song's other tabs from there, never in place of one.

Only songs in wanted.txt are looked up (and a lookup's song): never a tab page for a song nobody asked
for, never a mirror of the site. Errors are never misses: only candidates that all answered, none the
song's (or each gone, 404), make the song a miss, asked about again after 30 days (kv
``gametabs:checked:<song id>``); a tab you picked that is gone too, unless you pick another (kv
``gametabs:checked:<song id>:pick``, the tab asked for). A block propagates, and a spent budget ends the
pass. Any other provider error, a page that won't parse even fetched again included, leaves the song for
the next run. No file is ever replaced or deleted: a song that has a tab from gametabs.net gets no other.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from caracole import site_index, stamps
from caracole.db import kv_get, kv_set
from caracole.gametabs import (
    GAME,
    PROVIDER,
    SITEMAP_URL,
    TAB,
    GameTab,
    GameTabsParseError,
    IndexRow,
    page_url,
    parse_page_url,
    parse_tab_page,
    sitemap_child,
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
from caracole.inbox import GAMETAB_KIND, gametab_number
from caracole.library import keep_file, write_info
from caracole.normalize import compact, name_forms
from caracole.overrides import GameTabsPick, Overrides
from caracole.provider_pass import PassStats, each_song
from caracole.site_index import Site
from caracole.songs import Song, get_song, list_songs
from caracole.versions import upsert_version

log = logging.getLogger(__name__)

INDEX_MAX_AGE = timedelta(days=30)
RECHECK_AFTER = timedelta(days=30)  # a song whose candidates were none of its
CANDIDATES = 4  # a title's tabs read for one song at most, the most viewed first
_ACCEPT = (200, 404)  # a 404 is an answer: the tab is gone
# What follows a game's name in a wanted.txt line that names its music: "Hollow Knight OST", "Celeste (Original
# Soundtrack)", "Chrono Trigger Original Game Soundtrack".
_SOUNDTRACK = re.compile(r"[\s(\[-]+(?:original\s+)?(?:game\s+|video\s+game\s+)?(?:ost|soundtrack)[)\]]?\s*$",
                         re.IGNORECASE)

CHECKED_PREFIX = "gametabs:checked:"  # + song id: when its candidates last answered for it
PICKED = ":pick"  # CHECKED_PREFIX + song id + this: the tab you picked that was asked for then

KEPT, MISSING = "kept", "missing"


@dataclass
class GameTabsStats(PassStats):
    """What one ``gametabs_tabs`` pass did. ``sitemaps`` counts the sitemap reads stored; ``tried`` the songs
    looked up, errors included; ``errors`` the songs' and the sitemaps'; ``failures`` the songs an error left,
    as every pass names them (provider_pass.py)."""

    sitemaps: int = 0
    kept: int = 0
    missing: int = 0

    @property
    def sitemap_errors(self) -> int:
        """The errors no song's failure stands for: the sitemaps'."""
        return self.errors - sum(not isinstance(e, ProviderUnavailable) for _, e in self.failures)


def gametabs_tabs(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    now: datetime,
    *,
    overrides: Overrides | None = None,
    only: Collection[int] | None = None,
    refresh_index: bool = True,
) -> GameTabsStats:
    """Refresh the index when due, then keep a text tab for each song that needs one and has a candidate.

    See the module docstring. With no song that wants a tab, nothing is sent, not even for the sitemaps.
    ``ProviderBlocked`` propagates. ``BudgetExhausted`` ends the pass (``budget_exhausted``), and so does a
    client that gives up on the site for this run (``ProviderUnavailable``): the songs left are ``failures``.
    Any other ``ProviderError`` counts in ``errors``: one from the sitemaps leaves the index as it was, and one
    for a song leaves the song for the next run, in ``failures`` with its error.

    A lookup (``caracole get``) passes ``only`` its song's id, and ``refresh_index=False``: the sitemaps are the
    nightly run's to read. A song that got a tab meanwhile (from a lookup the nightly run let go first) is
    passed over when its turn comes.
    """
    from caracole.gametabs_index import ensure_current_keys

    stats = GameTabsStats()
    now = stamps.utc(now)
    ensure_current_keys(conn)
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
        log.info("gametabs.net is unavailable for the rest of this run: %s", e)
        index = _Index(conn)
        stats.failures += [(song, e) for song in wanting if _pick(overrides, song) or index.candidates(song)]
        return stats
    except ProviderError as e:
        stats.errors += 1
        log.warning("gametabs.net's sitemaps: %s", e)
    index = _Index(conn)
    run = _Pass(conn, client, Path(library_dir), now)
    # Each song is checked just before its turn: a lookup let in during a pause may have given it a tab.
    songs = (s for s in wanting if (_pick(overrides, s) or index.candidates(s)) and _wants(conn, s, overrides))
    for _, outcome in each_song(songs, stats, lambda song: _look_up(run, song, index, _pick(overrides, song)),
                                site="gametabs.net", level=logging.WARNING):
        stats.kept += outcome == KEPT
        stats.missing += outcome == MISSING
    return stats


# --- the index ------------------------------------------------------------------------------------------------------

# gametabs.net's sitemaps, as site_index.py reads them into gametabs_index: its numbered children, never the static one.
SITE = Site(
    provider=PROVIDER, index_url=SITEMAP_URL, table="gametabs_index", columns=IndexRow._fields,
    child=sitemap_child, row=parse_page_url, max_age=INDEX_MAX_AGE,
)


def game_forms(name: str) -> list[str]:
    """The keys a game's name is compared by (``normalize.name_forms``), and those of the name less what says it
    is its music ("Hollow Knight OST", "Celeste (Original Soundtrack)")."""
    names = [name, _SOUNDTRACK.sub("", name)]
    return [form for n in dict.fromkeys(names) if n.strip() for form in name_forms(n) if form]


def song_forms(song: Song) -> set[str]:
    """The keys the song's artists are compared by, hyphens aside: as a game's names and as a composer's."""
    return {compact(form) for name in song.artists or [song.artist] for form in game_forms(name)}


def _named(names: Iterable[str]) -> set[str]:
    """The keys some names are compared by, hyphens aside."""
    return {compact(form) for name in names for form in game_forms(name)}


def _listed(text: str | None) -> list[str]:
    """A JSON array of names, as gametabs_game_tabs keeps them."""
    try:
        names = json.loads(text or "[]")
    except (ValueError, RecursionError):
        return []
    return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []


class _Index:
    """``gametabs_index`` and the game pages read, as a pass reads them: each game by the keys of its slug and of
    its name once its page was read, hyphens aside, loaded once."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.games: dict[str, set[str]] = {}
        for game, key in conn.execute("SELECT DISTINCT game, key FROM gametabs_index WHERE kind = ?", (GAME,)):
            self.games.setdefault(compact(key), set()).add(game)
        for game, name in conn.execute("SELECT DISTINCT game, name FROM gametabs_games WHERE name != ''"):
            for form in _named([name]):
                self.games.setdefault(form, set()).add(game)

    def candidates(self, song: Song) -> list[str]:
        """The paths of the tabs titled as the song is, at most ``CANDIDATES``, the most viewed first: those of a game
        one of the song's artists names, and those whose composer one of them is (by the game pages read)."""
        key = title_key(song.title)
        if not key:
            return []
        forms = song_forms(song)
        games = sorted(set().union(*(self.games.get(f, ()) for f in forms)))
        found: dict[str, int] = {}
        if games:
            marks = ", ".join("?" for _ in games)
            for path, views in self.conn.execute(
                    f"SELECT i.path, MAX(COALESCE(t.views, 0)) FROM gametabs_index i LEFT JOIN gametabs_game_tabs t "
                    f"ON t.path = i.path WHERE i.kind = ? AND i.game IN ({marks}) AND (i.key = ? OR i.slug_key = ?) "
                    "GROUP BY i.path", (TAB, *games, key, key)):
                found[path] = max(found.get(path, 0), views)
        for path, game, composers, views in self.conn.execute(
                "SELECT path, game, composers, views FROM gametabs_game_tabs WHERE title_key = ?", (key,)):
            if game in games or not forms.isdisjoint(_named(_listed(composers))):
                found[path] = max(found.get(path, 0), views)
        return [path for path, _ in sorted(found.items(), key=lambda f: (-f[1], f[0]))][:CANDIDATES]


def fits(song: Song, tab: GameTab) -> bool:
    """Whether a tab page is the song's: its track's title is the song's, and its game or one of its composers is one
    of the song's artists."""
    if not title_key(tab.title) or title_key(tab.title) != title_key(song.title):
        return False
    forms = song_forms(song)
    theirs = _named([tab.game, *tab.composers]) | ({compact(tab.game_slug)} if tab.game_slug else set())
    return not forms.isdisjoint(theirs)


# --- which songs ----------------------------------------------------------------------------------------------------


def _songs_wanting_a_tab(conn: sqlite3.Connection, now: datetime, overrides: Overrides | None) -> list[Song]:
    """The songs, newest first, that are not ignored, have no tab from gametabs.net (or not the one you picked),
    and weren't looked up there in the last 30 days."""
    ignored = overrides.ignore if overrides is not None else frozenset()
    with_tab = songs_with_a_gametab(conn)
    cutoff = now - RECHECK_AFTER
    return [
        song for song in list_songs(conn)
        if song.status != "ignored" and song.key not in ignored
        and (song.id not in with_tab if _pick(overrides, song) is None else _wants(conn, song, overrides))
        and (stamps.before(kv_get(conn, f"{CHECKED_PREFIX}{song.id}"), cutoff) or _newly_picked(conn, song, overrides))
    ]


def _newly_picked(conn: sqlite3.Connection, song: Song, overrides: Overrides | None) -> bool:
    """Whether you picked a tab for the song that wasn't asked for yet: it is, at once."""
    pick = _pick(overrides, song)
    return pick is not None and kv_get(conn, f"{CHECKED_PREFIX}{song.id}{PICKED}") != pick.path


def _pick(overrides: Overrides | None, song: Song) -> GameTabsPick | None:
    """The gametabs.net tab you picked for the song (``[gametabs]``), or None."""
    return overrides.gametabs.get(song.key) if overrides is not None else None


def _wants(conn: sqlite3.Connection, song: Song, overrides: Overrides | None) -> bool:
    """Whether the song still wants a tab: the one you picked, while it hasn't kept it; else any, while it has none."""
    pick = _pick(overrides, song)
    if pick is None:
        return song.id not in songs_with_a_gametab(conn)
    return conn.execute(
        "SELECT 1 FROM files f JOIN versions v ON v.id = f.version_id WHERE f.song_id = ? AND v.provider = ? "
        "AND v.kind = ? AND v.tab_id = ? LIMIT 1", (song.id, PROVIDER, GAMETAB_KIND, pick.path)
    ).fetchone() is None


def songs_with_a_gametab(conn: sqlite3.Connection) -> set[int]:
    """The songs the files table holds a tab from gametabs.net for."""
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT f.song_id FROM files f JOIN versions v ON v.id = f.version_id WHERE v.kind = ?",
        (GAMETAB_KIND,))}


# --- one song -------------------------------------------------------------------------------------------------------


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


def _look_up(run: _Pass, song: Song, index: _Index, pick: GameTabsPick | None = None) -> str:
    """Read the song's candidates and keep the most viewed that is the song's: ``KEPT``; ``MISSING`` when none is.
    With ``pick``, read that tab alone and keep it, whatever its page names: ``MISSING`` when the site no longer has
    it."""
    if pick is not None:
        tab = _tab(run, pick.url)
        if tab is not None:
            _keep(run, song, pick.path, tab)
        kv_set(run.conn, f"{CHECKED_PREFIX}{song.id}", run.stamp)
        kv_set(run.conn, f"{CHECKED_PREFIX}{song.id}{PICKED}", pick.path)
        return KEPT if tab is not None else MISSING
    found: list[tuple[str, GameTab]] = []
    for path in index.candidates(song):
        tab = _tab(run, page_url(path))
        if tab is not None and fits(song, tab):
            found.append((path, tab))
    if found:
        path, tab = min(found, key=lambda f: (-f[1].views, -(f[1].rating or 0.0), f[0]))
        _keep(run, song, path, tab)
    kv_set(run.conn, f"{CHECKED_PREFIX}{song.id}", run.stamp)
    return KEPT if found else MISSING


def _tab(run: _Pass, url: str) -> GameTab | None:
    """A tab page, read; None when the site no longer has it (404), or sends it where robots.txt closes. A cached
    page that won't parse is asked for once more before it is an error (``http.read_once_more``)."""
    try:
        resp = run.client.get(url, accept=_ACCEPT)
    except RobotsClosed as e:
        log.info("gametabs.net: %s", e)
        return None
    return read_once_more(run.client, resp, url, _page, GameTabsParseError, fetched=run.fetched, accept=_ACCEPT)


def _page(resp: Response) -> GameTab | None:
    return None if resp.status == 404 else parse_tab_page(resp.content, resp.url)


def _keep(run: _Pass, song: Song, path: str, tab: GameTab) -> str:
    """Keep the tab as the song's next ``gametab-N.txt``, with its version and info.json; return its name."""
    version_id = upsert_version(
        run.conn, provider=PROVIDER, tab_id=path, song_id=song.id, slot="guitar", kind=GAMETAB_KIND,
        rating=tab.rating or 0.0, votes=tab.views, version=1, label=None, url=page_url(path), raw=tab.raw(),
        now=run.stamp,
    )
    number = gametab_number(run.conn, run.library_dir, song)
    name = f"gametab-{number}.txt"
    keep_file(run.conn, run.library_dir, song=song, version_id=version_id, name=name, data=tab.body.encode("utf-8"),
              rank=number)
    write_info(run.conn, run.library_dir, get_song(run.conn, song.id))
    return name
