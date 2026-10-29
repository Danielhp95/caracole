"""The library page's Sites tab: each website caracole reads, what it has from it, and what keeps it out.

One line a site (``SITES``, icons.SOURCES' order less the audio model and the inbox, which are no site): what it is
for, robots.txt in a sentence, the closed paths worth naming with what each closes, and its terms where the owner
chose to read it all the same (AGENTS.md's two exceptions, harptabs.com and gametabs.net, and YouTube). Those words
are written here by hand; the paths are caracole's own table's (``http.ROBOTS_DISALLOW``, pinned to each live
robots.txt by tests), so the page never names a rule caracole doesn't keep. YouTube is the one site whose named paths
aren't in that table: caracole goes against them, by the owner's choice, and its sentence says so.

Everything here is read from the database, the config and caracole's tables: the tab sends no request, and building
the page asks none.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from caracole.db import kv_get_json, kv_set_json
from caracole.http import ROBOTS_DISALLOW

if TYPE_CHECKING:
    from caracole.config import Config


@dataclass(frozen=True)
class Site:
    """A website caracole reads: ``key`` as icons.SOURCES names it (its name and icon are there), what it is
    for, its home's domain, the hosts whose robots rules are its, robots.txt in words, the closed paths named with
    what each closes, its terms note, and, for a site with no index, how it is asked instead."""

    key: str
    role: str
    domain: str
    hosts: tuple[str, ...]
    robots: str
    paths: tuple[tuple[str, str], ...] = ()
    terms: str | None = None
    asked: str | None = None


SITES: tuple[Site, ...] = (
    Site("ug", "Chord sheets and text tabs", "ultimate-guitar.com",
         ("www.ultimate-guitar.com", "tabs.ultimate-guitar.com"),
         "Closes its search, downloads and print pages. caracole matches songs against its sitemap, on your machine.",
         (("/search.php", "its search"), ("/tab/download", "downloads"), ("/tab/print?", "print pages"),
          ("/download/public/", "public downloads"))),
    Site("lacuerda", "Spanish-language chord sheets", "acordes.lacuerda.net", (),
         "Its robots.txt is empty: nothing is closed. caracole keeps its own pace all the same."),
    Site("lrclib", "Lyrics, many synced to the music", "lrclib.net", (),
         "An API with no robots rules: nothing is closed to caracole.", asked="Asked song by song"),
    Site("gtptabs", "Guitar Pro files", "gtptabs.com", ("gtptabs.com",),
         "Closes its Russian half, its search and its storage (an artist's “Download all”).",
         (("/ru/", "the Russian half of the site"), ("/search/", "its search"),
          ("/storage/", "“Download all” archives"))),
    Site("musescore", "Scores, as links you open yourself", "musescore.com", ("musescore.com",),
         "Closes its API, downloads, search and embeds. caracole reads only its sitemaps.",
         (("/api/jmuse", "its API"), ("/score/*/download/*", "downloads"), ("/sheetmusic?", "its search"),
          ("/oembed/*", "embeds"))),
    Site("harptabs", "Harmonica tabs", "harptabs.com", ("www.harptabs.com", "harptabs.com"),
         "Closes its search, its API and its app's data. Artist and tab pages are open.",
         (("/search", "its search"), ("/api/", "its API"), ("/*?*_rsc=", "the app's data requests")),
         terms="Its terms forbid copying. Kept by your choice: one tab a song, privately."),
    Site("gametabs", "Video-game music tabs", "gametabs.net", ("gametabs.net", "www.gametabs.net"),
         "Closes its API, its filters and every download behind a login. Its robots.txt asks for 5 s between "
         "requests; caracole asks once a second, by your choice.",
         (("/api/", "its API"), ("/tabs?*", "filtered lists"),
          ("/preparing-tab-file-download", "downloads (a login's)")),
         terms="Its terms forbid bots. Read by your choice since 28 Oct 2026."),
    Site("youtube", "Audio for auto-chords", "youtube.com", (),
         "Closes /results and /youtubei/, which yt-dlp uses: caracole goes against them, by your choice.",
         (("/results", "search results"), ("/youtubei/", "the player's API")),
         terms="The one site caracole goes against robots.txt for: a few of your songs a night.",
         asked="Searched song by song"),
)


def more_paths(site: Site) -> int:
    """How many paths caracole's robots table closes for ``site``'s hosts beyond those it names."""
    every = {path for host in site.hosts for path in ROBOTS_DISALLOW.get(host, ())}
    return len(every - {path for path, _ in site.paths})


# --- what each index holds ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Indexed:
    """What a site's index holds: its songs (distinct song keys; gametabs.net's ``tracks``), and the smaller line,
    what the site counts itself."""

    songs: int
    unit: str
    detail: str


@dataclass(frozen=True)
class Progress:
    """How far an index read a little each night has got: ``done`` of ``of`` ``what``."""

    done: int
    of: int
    what: str


Figures = tuple[Indexed | None, Progress | None]

# Counting a million rows (UG's index, MuseScore's) takes longer than building the rest of the page, and the page is
# built on every served load. So the counts of the indexes read from sitemaps are kept in kv ``COUNTS``, each with
# the stamp of the index's own records when counted: every change to such a table comes with a change to its
# ``<provider>:sitemaps`` record, written in the same transaction (ug/index.py, site_index.py), and harptabs.com's
# rows keyed again with its ``harptabs:index:keys``. ``refresh_counts`` keeps them, under caracole's lock, as
# todo.write_pages writes the pages; ``index_figures`` only reads, and counts again whatever stamp has moved since,
# so the figures are never stale, only slower until the next write.
COUNTS = "sites:counts"
_RECORDS = {
    "ug": ("ug:sitemaps",),
    "gtptabs": ("gtptabs:sitemaps",),
    "musescore": ("musescore:sitemaps",),
    "harptabs": ("harptabs:sitemaps", "harptabs:index:keys"),
    "gametabs": ("gametabs:sitemaps",),
}


def _one(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> int:
    return conn.execute(sql, args).fetchone()[0] or 0


def _counted(conn: sqlite3.Connection, key: str) -> list[int]:
    """What ``index_figures`` counts of a site's table: its songs, its rows, and gametabs.net's games."""
    if key == "ug":
        return [_one(conn, "SELECT COUNT(*) FROM (SELECT DISTINCT artist_key, song_key FROM ug_index)"),
                _one(conn, "SELECT COUNT(*) FROM ug_index")]
    if key == "gtptabs":
        return [_one(conn, "SELECT COUNT(*) FROM (SELECT DISTINCT artist_key, title_key FROM gtptabs_index)"),
                _one(conn, "SELECT COUNT(*) FROM gtptabs_index")]
    if key == "musescore":  # its sitemaps give a score's title alone, never its artist: songs are titles
        return [_one(conn, "SELECT COUNT(DISTINCT title_key) FROM musescore_index"),
                _one(conn, "SELECT COUNT(*) FROM musescore_index")]
    if key == "harptabs":
        from caracole.harptabs import TAB

        return list(conn.execute("SELECT COUNT(DISTINCT key), COUNT(*) FROM harptabs_index WHERE kind = ?",
                                 (TAB,)).fetchone())
    from caracole.gametabs import GAME, TAB

    # A track is a game's title: a slug's number (main-theme-108) is one more tab of it, never part of its key.
    tracks, tabs = conn.execute("SELECT COUNT(*), COALESCE(SUM(n), 0) FROM (SELECT COUNT(*) AS n FROM gametabs_index "
                                "WHERE kind = ? GROUP BY game, key)", (TAB,)).fetchone()
    return [tracks, tabs, _one(conn, "SELECT COUNT(*) FROM gametabs_index WHERE kind = ?", (GAME,))]


def _stamp(conn: sqlite3.Connection, key: str) -> str:
    rows = conn.execute(f"SELECT key, value FROM kv WHERE key IN ({','.join('?' * len(_RECORDS[key]))}) "
                        "ORDER BY key", _RECORDS[key]).fetchall()
    return hashlib.sha256(json.dumps([list(r) for r in rows]).encode()).hexdigest()


def _counts(conn: sqlite3.Connection, key: str, kept: dict[str, Any]) -> list[int]:
    entry = kept.get(key)
    if isinstance(entry, dict) and entry.get("stamp") == _stamp(conn, key) and isinstance(entry.get("counts"), list):
        return [int(n) for n in entry["counts"]]
    return _counted(conn, key)


def refresh_counts(conn: sqlite3.Connection) -> None:
    """Count again each index whose records changed since its counts were kept, and keep them. A writer's: caracole's
    lock held (todo.write_pages), never caracole serve building its page."""
    kept = kv_get_json(conn, COUNTS, default={}) or {}
    fresh = {}
    for key in _RECORDS:
        stamp = _stamp(conn, key)
        entry = kept.get(key)
        fresh[key] = (entry if isinstance(entry, dict) and entry.get("stamp") == stamp
                      else {"stamp": stamp, "counts": _counted(conn, key)})
    if fresh != kept:
        kv_set_json(conn, COUNTS, fresh)


def index_figures(conn: sqlite3.Connection) -> dict[str, Figures]:
    """What each site's index holds, and how far it has got, by site, in ``SITES``' order: (None, None) for a site
    with no index (LRCLIB and YouTube, asked song by song). Reads alone: nothing is written."""
    from caracole.gametabs_index import index_state as game_pages
    from caracole.harptabs_index import index_state as artist_pages
    from caracole.lacuerda import LETTERS
    from caracole.lacuerda_index import index_size, letters_read
    from caracole.ug.index import index_coverage

    kept = kv_get_json(conn, COUNTS, default={}) or {}
    figures: dict[str, Figures] = {s.key: (None, None) for s in SITES}

    songs, tabs = _counts(conn, "ug", kept)
    coverage = index_coverage(conn)  # while a build or refresh has sitemaps left, how many it has read
    progress = None
    if coverage.listed and coverage.left:
        progress = Progress(len(coverage.listed) - len(coverage.left), len(coverage.listed), "sitemaps read")
    figures["ug"] = Indexed(songs, "songs", f"{tabs:,} tabs, from its sitemap"), progress

    # The songs caracole knows (the artist pages read, its search's), never the site's own total, which the listings
    # give each artist and the smaller line sums; and the letters whose every listing page is read.
    artists, known = index_size(conn)
    listed = _one(conn, "SELECT SUM(songs) FROM lacuerda_index WHERE title = ''")
    figures["lacuerda"] = (Indexed(known, "songs", f"of {listed:,} its listings count, {artists:,} artists"),
                           Progress(len(letters_read(conn)), len(LETTERS), "letters read"))

    songs, tabs = _counts(conn, "gtptabs", kept)
    figures["gtptabs"] = Indexed(songs, "songs", f"{tabs:,} tabs, from its sitemaps"), None

    songs, scores = _counts(conn, "musescore", kept)
    figures["musescore"] = Indexed(songs, "songs", f"titles of {scores:,} scores, from its sitemaps"), None

    songs, tabs = _counts(conn, "harptabs", kept)
    state = artist_pages(conn)
    figures["harptabs"] = (Indexed(songs, "songs", f"{tabs:,} tabs, from its sitemap"),
                           Progress(state.read, state.artists, "artist pages read") if state.artists else None)

    tracks, tabs, games = _counts(conn, "gametabs", kept)
    pages = game_pages(conn)
    figures["gametabs"] = (Indexed(tracks, "tracks", f"{tabs:,} tabs of {games:,} games"),
                           Progress(pages.read, pages.pages, "game pages read") if pages.pages else None)
    return figures


# --- a site's status ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Status:
    """Where a site stands: ``state`` one of "ok", "indexing", "cooling", "errors", "off"; ``label`` its badge's word;
    ``detail`` why, in a line, or None."""

    state: str
    label: str
    detail: str | None = None


def status_of(conn: sqlite3.Connection, cfg: Config, provider: str, now: datetime, *, partial: bool = False) -> Status:
    """A provider's status, one rule for the Sites tab and the to-do page's health table: off (turned off in
    caracole.toml, or YouTube without auto-chords), cooling down after a block, errors since its last good run, else
    OK, or Indexing while its index is ``partial``."""
    from caracole.health import get_state
    from caracole.stamps import shown
    from caracole.youtube_fetch import route_problem

    if not cfg.provider(provider).enabled:
        return Status("off", "Off", f"[providers.{provider}] enabled = false")
    if provider == "youtube" and (problem := route_problem(cfg)):
        return Status("off", "Off", problem)
    s = get_state(conn, provider)
    if s.cooldown_until and now < s.cooldown_until:
        blocks = f"{s.strikes} block{'s' if s.strikes != 1 else ''} in a row"
        why = f": {s.last_error}" if s.last_error else ""
        return Status("cooling", "Cooling down", f"Until {shown(s.cooldown_until, local=True)}, after {blocks}{why}")
    if s.last_error_at and (s.last_ok is None or s.last_ok < s.last_error_at):
        return Status("errors", "Errors", s.last_error)  # nothing has worked since the last error
    return Status("indexing", "Indexing") if partial else Status("ok", "OK")
