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
import re
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
         "requests; {pace}.",
         (("/api/", "its API"), ("/tabs?*", "filtered lists"),
          ("/preparing-tab-file-download", "downloads (a login's)")),
         terms="Its terms forbid bots. Read by your choice since 28 Oct 2026."),
    Site("youtube", "Audio for auto-chords", "youtube.com", (),
         "Closes /results and /youtubei/, which yt-dlp uses: caracole goes against them, by your choice.",
         (("/results", "search results"), ("/youtubei/", "the player's API")),
         terms="The one site whose closed paths caracole asks for, by your choice: a few of your songs a night, "
               "the videos you give it, and a search's first video.",
         asked="Searched song by song"),
)


# The pace a site's robots.txt asks for, where it asks one (gametabs.net's Crawl-delay, tests/fixtures/gametabs/
# robots.txt), which caracole reports beside its own: since d19226e no Crawl-delay is a floor.
CRAWL_DELAY_ASKED = {"gametabs": 5.0}


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
COUNTS_VERSION = 1  # of what ``_counted`` counts: a change to it counts every index again
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
    return hashlib.sha256(json.dumps([COUNTS_VERSION, [list(r) for r in rows]]).encode()).hexdigest()


def _stored(key: str, entry: Any, stamp: str) -> list[int] | None:
    """A site's counts as kept, when kept for its records as they are now (``stamp``) and of the shape ``_counted``
    gives; None for any other entry, which another caracole or a hand may have written: it is counted again."""
    counts = entry.get("counts") if isinstance(entry, dict) and entry.get("stamp") == stamp else None
    if (isinstance(counts, list) and len(counts) == (3 if key == "gametabs" else 2)
            and all(isinstance(n, int) and not isinstance(n, bool) for n in counts)):
        return counts
    return None


def _counts(conn: sqlite3.Connection, key: str, kept: dict[str, Any]) -> list[int]:
    counts = _stored(key, kept.get(key), _stamp(conn, key))
    return counts if counts is not None else _counted(conn, key)


def refresh_counts(conn: sqlite3.Connection) -> None:
    """Count again each index whose records changed since its counts were kept, and keep them. A writer's: caracole's
    lock held (todo.write_pages), never caracole serve building its page."""
    kept = kv_get_json(conn, COUNTS, default={}) or {}
    fresh = {}
    for key in _RECORDS:
        stamp = _stamp(conn, key)
        counts = _stored(key, kept.get(key), stamp)
        fresh[key] = {"stamp": stamp, "counts": counts if counts is not None else _counted(conn, key)}
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
    caracole.toml, or YouTube, or its image host, without auto-chords), cooling down after a block, errors since its
    last good run, else OK, or Indexing while its index is ``partial``."""
    from caracole.health import get_state
    from caracole.stamps import shown
    from caracole.youtube_fetch import route_problem

    if not cfg.provider(provider).enabled:
        return Status("off", "Off", f"[providers.{provider}] enabled = false")
    if provider in ("youtube", "ytimg") and (problem := route_problem(cfg)):
        return Status("off", "Off", problem)
    s = get_state(conn, provider)
    if s.cooldown_until and now < s.cooldown_until:
        blocks = f"{s.strikes} block{'s' if s.strikes != 1 else ''} in a row"
        why = f": {s.last_error}" if s.last_error else ""
        return Status("cooling", "Cooling down", f"Until {shown(s.cooldown_until, local=True)}, after {blocks}{why}")
    if s.last_error_at and (s.last_ok is None or s.last_ok < s.last_error_at):
        return Status("errors", "Errors", s.last_error)  # nothing has worked since the last error
    return Status("indexing", "Indexing") if partial else Status("ok", "OK")


# --- the tab's data -------------------------------------------------------------------------------------------------

_LYRICS = ("lyrics.txt", "lyrics.lrc")
# What a song keeps from each site, by its files' names (library_page's cards give each file's ``source``): a site
# whose things are files, each counted; the sheet's sites count songs by their sheet's source.
_FILES = {"gtptabs": (re.compile(r"guitar-\d+\..+"), "Guitar Pro files"),
          "harptabs": (re.compile(r"harmonica-\d+\.txt"), "harmonica tabs"),
          "gametabs": (re.compile(r"gametab-\d+\.txt"), "tabs")}
_SHEETS = {"ug": "sheets", "lacuerda": "sheets", "youtube": "auto sheets"}
_ONE = {"sheets": "sheet", "auto sheets": "auto sheet", "Guitar Pro files": "Guitar Pro file", "links": "link",
        "harmonica tabs": "harmonica tab", "tabs": "tab", "songs": "song", "tracks": "track", "requests": "request",
        "yt-dlp runs": "yt-dlp run"}


def _unit(n: int, units: str) -> str:
    """``units`` as one of them is named when ``n`` is 1 ("1 sheet"); lyrics are lyrics."""
    return _ONE.get(units, units) if n == 1 else units


def _kept(key: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    """What your library keeps from a site: how many of its things, in its unit, for how many of your songs."""
    detail = None
    if key in _SHEETS:
        mine = [c for c in cards if c.get("source") == key]
        count = len(mine)
        if key == "ug":
            beside = sum(max(len((c.get("versions") or {}).get("list") or []) - 1, 0) for c in mine)
            detail = f"+ {beside:,} other versions kept beside them" if beside else None
        return {"count": count, "unit": _unit(count, _SHEETS[key]), "songs": count, "detail": detail}
    if key == "lrclib":
        names = [{f.get("name") for f in c.get("files") or [] if f.get("source") == key} for c in cards]
        mine = [n for n in names if n & set(_LYRICS)]
        synced = sum(1 for n in mine if "lyrics.lrc" in n)
        return {"count": len(mine), "unit": "lyrics", "songs": len(mine),
                "detail": f"{synced:,} of them synced" if mine else None}
    if key == "musescore":  # the possible matches the to-do page and a song's card link: caracole downloads none
        links = [len(c.get("museScore") or []) for c in cards]
        return {"count": sum(links), "unit": _unit(sum(links), "links"), "songs": sum(1 for n in links if n),
                "detail": None}
    pattern, unit = _FILES[key]
    each = [sum(1 for f in c.get("files") or [] if f.get("source") == key and pattern.fullmatch(f.get("name") or ""))
            for c in cards]
    return {"count": sum(each), "unit": _unit(sum(each), unit), "songs": sum(1 for n in each if n), "detail": None}


def _spread(cfg: Config, key: str) -> str:
    low, high = cfg.provider(key).delay
    return f"{low:g} s" if low == high else f"{low:g}–{high:g} s"


def _pace(cfg: Config, key: str) -> str:
    return f"{_spread(cfg, key)} between {'runs' if key == 'youtube' else 'requests'}"


def _robots(cfg: Config, site: Site) -> str:
    """A site's robots.txt in words, gametabs.net's with the pace caracole keeps there: robots.txt's Crawl-delay is no
    floor (d19226e), so the sentence says whether caracole waits less, by the owner's choice, or more."""
    asked = CRAWL_DELAY_ASKED.get(site.key)
    if asked is None:
        return site.robots
    waits = f"caracole waits {_spread(cfg, site.key)}"
    return site.robots.format(pace=waits + (", by your choice" if cfg.provider(site.key).delay[0] < asked else ""))


def _shown(value: Any) -> str | None:
    from caracole.stamps import parse, shown

    at = parse(value) if isinstance(value, str) else None
    return shown(at, local=True) if at is not None else None


def _whole(conn: sqlite3.Connection, key: str) -> bool:
    """Whether a site's sitemaps were all read once: UG's index built whole, a site_index.py site's every sitemap read
    (``complete_at``), each read a budget at a time across nights; until then its count is partial."""
    if key == "ug":
        from caracole.ug.index import index_state

        return index_state(conn) == "complete"
    from caracole import gametabs_fetch, gtptabs_fetch, harptabs_fetch, musescore_fetch
    from caracole.site_index import complete_at

    read = {"gtptabs": gtptabs_fetch.SITE, "musescore": musescore_fetch.SITE, "harptabs": harptabs_fetch.SITE,
            "gametabs": gametabs_fetch.SITE}
    return key not in read or complete_at(conn, read[key]) is not None


def sites_data(conn: sqlite3.Connection, cfg: Config, cards: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """The Sites tab's data, the library page's ``data["sites"]``: the last nightly run (kv ``run:last``, which
    pipeline.py keeps of the nightly run alone: never a daytime command's run, whose run id is of the same shape),
    the totals, and a line a site. ``cards``: the page's songs (library_page.song_cards), what your library keeps
    from each site is counted from. Read with no request and nothing written."""
    from caracole.icons import SOURCES
    from caracole.lacuerda_index import index_state as listings

    run = kv_get_json(conn, "run:last", default=None)
    run = run if isinstance(run, dict) and run.get("started") else None
    requests = run.get("requests") if run and isinstance(run.get("requests"), dict) else {}
    budgets = run.get("budgets") if run and isinstance(run.get("budgets"), dict) else {}
    figures = index_figures(conn)
    lines = []
    for site in SITES:
        indexed, progress = figures[site.key]
        partial = (not listings(conn).complete if site.key == "lacuerda"
                   else progress is not None and progress.done < progress.of) or not _whole(conn, site.key)
        status = status_of(conn, cfg, site.key, now, partial=partial)
        night = None
        if run is not None and status.state != "off":
            budget = int(budgets.get(site.key, cfg.provider(site.key).budget))
            night = {"used": int(requests.get(site.key, 0)), "budget": budget,
                     "unit": _unit(budget, "yt-dlp runs" if site.key == "youtube" else "requests")}
        last = conn.execute("SELECT MAX(at) FROM events WHERE provider = ?", (site.key,)).fetchone()[0]
        lines.append({
            "key": site.key, "name": SOURCES[site.key].name, "role": site.role, "domain": site.domain,
            "indexed": None if indexed is None else {"songs": indexed.songs,
                                                     "unit": _unit(indexed.songs, indexed.unit),
                                                     "detail": indexed.detail},
            "asked": site.asked,
            "progress": None if progress is None else {"done": progress.done, "of": progress.of,
                                                       "what": progress.what},
            "kept": _kept(site.key, cards),
            "night": night,
            "status": {"state": status.state, "label": status.label, "detail": status.detail},
            "pace": _pace(cfg, site.key),
            "last": _shown(last),
            "robots": {"text": _robots(cfg, site), "paths": [list(p) for p in site.paths], "more": more_paths(site)},
            "terms": site.terms,
        })
    return {
        "run": None if run is None else {
            "started": _shown(run["started"]), "finished": _shown(run.get("finished")),
            "requests": sum(int(n) for p, n in requests.items() if p != "youtube")},
        "totals": {"sites": len(SITES), "indexed": sum(s["indexed"]["songs"] for s in lines if s["indexed"]),
                   # MuseScore's are links to open yourself: caracole keeps nothing of theirs
                   "kept": sum(s["kept"]["count"] for s in lines if s["key"] != "musescore")},
        "songs": len(cards),
        "list": lines,
    }
