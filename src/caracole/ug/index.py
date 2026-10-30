"""The local Ultimate Guitar index, built from UG's sitemaps (plan §2).

``caracole index build`` reads every tab sitemap once (about 46 requests, or
local files with ``from_dir``): the numbered ones, the ukulele ones
(``sitemap_ukulele1``–``N``, UG's "Ukulele Chords") and ``sitemap_last``. The
nightly refresh asks again only for the sitemap index, ``sitemap_last``, the
highest-numbered sitemap of each run (``sitemapN``, ``sitemap_ukuleleN``) and any
tab sitemap this database has never indexed, because new tabs appear only there.
A database indexed before caracole kept ukulele tabs reads the ukulele sitemaps at
its next refresh, as sitemaps it never indexed.

Every sitemap is fetched with a conditional GET. A 304 skips parsing only when
this database indexed exactly that copy; otherwise the cached body is parsed.
That covers a fresh database next to a warm HTTP cache, and a run that died
after a download but before its rows were stored.

Each sitemap is stored in one transaction: its rows, the songs its new tabs
make dirty, and its entry in ``kv['ug:sitemaps']`` (the validators of the
indexed copy, when, how many rows, and what all its URLs became: ``TabCounts``).
A failure later in the run loses nothing already stored.

A build that stops part-way (a block, the budget, Ctrl-C) leaves the index
partial until a refresh reads the sitemaps it left, or another build
finishes: only then is ``kv['ug:index:built_at']`` set. Songs are matched
only against a complete index (``index_state``). The sitemaps the sitemap
index listed when last read are kept in ``kv['ug:index:listed']``, so
``index_coverage`` can say what is left, and where a refresh resumes.

A tab whose page robots.txt closes (``caracole.http.robots_disallows``: the
band Track's, under ``/tab/track/``) is never indexed, so no song matches a
page caracole may never read; a build or refresh drops any indexed earlier.

A build or refresh reports what it does to ``progress``, if given: an
``IndexPlan`` once it knows which sitemaps it reads, before it asks for the
first, then a ``SitemapRead`` for each. Nothing here prints: commands/index.py
turns them into lines.
"""

from __future__ import annotations

import re
import sqlite3
import zlib
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from caracole.db import kv_get, kv_get_json, kv_set, kv_set_json, savepoint
from caracole.http import ROBOTS_DISALLOW, Client, ProviderError, robots_disallows
from caracole.songs import update_song
from caracole.ug.lookup import song_tabs
from caracole.ug.page import TAB_BASE_URL, page_url
from caracole.ug.sitemap import (
    BARE,
    UNRECOGNIZED,
    IndexRow,
    classify_tab_url,
    iter_locs,
    sitemap_label,
    sitemap_name,
    sitemap_order,
    tab_sitemaps,
)

SITEMAP_INDEX_URL = "https://www.ultimate-guitar.com/sitemap.xml"
# The most URLs one sitemap may list (sitemaps.org); UG fills every numbered tab sitemap.
SITEMAP_MAX_URLS = 50_000

SITEMAPS_KEY = "ug:sitemaps"
LISTED_KEY = "ug:index:listed"
BUILT_KEY = "ug:index:built_at"
REFRESHED_KEY = "ug:index:refreshed_at"
_SITEMAP_FILE = re.compile(r"sitemap(\d+|_last|_ukulele\d+)\.xml(?:\.gz)?")
_NO_VALIDATORS = {"etag": None, "last_modified": None}

_CREATE_BATCH = (
    "CREATE TEMP TABLE IF NOT EXISTS _ug_batch (tab_id INTEGER PRIMARY KEY, artist_key TEXT NOT NULL, "
    "song_key TEXT NOT NULL, type TEXT NOT NULL, path TEXT NOT NULL)"
)
_NEW_IN_BATCH = (
    "SELECT b.tab_id FROM temp._ug_batch b "
    "WHERE NOT EXISTS (SELECT 1 FROM ug_index u WHERE u.tab_id = b.tab_id) ORDER BY b.tab_id"
)
# Rows already indexed keep their sitemap and first_seen; a tab whose slugs changed gets its new keys and path.
_UPSERT_BATCH = (
    "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
    "SELECT tab_id, artist_key, song_key, type, ?, ?, path FROM temp._ug_batch WHERE true "
    "ON CONFLICT (tab_id) DO UPDATE SET artist_key = excluded.artist_key, song_key = excluded.song_key, "
    "type = excluded.type, path = excluded.path "
    "WHERE ug_index.artist_key != excluded.artist_key OR ug_index.song_key != excluded.song_key "
    "OR ug_index.type != excluded.type OR ug_index.path != excluded.path"
)


@dataclass(frozen=True)
class TabCounts:
    """What a sitemap's URLs became.

    ``urls`` counts every one; ``indexed`` the index rows (a tab listed twice counts
    twice); ``bare`` the bare ids (``/tab/{id}``), which name no artist or song, so the
    index can't hold them and only artist pages lead to them; ``other`` the tabs of the
    types the index doesn't keep (bass, ukulele, ...), by type; ``closed`` the tabs whose
    page robots.txt closes; and ``unrecognized`` the rest (no type, an empty artist or
    song key, or no tab page at all).
    """

    urls: int = 0
    indexed: int = 0
    bare: int = 0
    other: Mapping[str, int] = field(default_factory=dict)
    closed: int = 0
    unrecognized: int = 0

    @property
    def other_total(self) -> int:
        return sum(self.other.values())

    def __add__(self, more: TabCounts) -> TabCounts:
        other = Counter(self.other)
        other.update(more.other)
        return TabCounts(self.urls + more.urls, self.indexed + more.indexed, self.bare + more.bare, dict(other),
                         self.closed + more.closed, self.unrecognized + more.unrecognized)

    def as_json(self) -> dict[str, Any]:
        return {"urls": self.urls, "indexed": self.indexed, "bare": self.bare, "other": dict(self.other),
                "closed": self.closed, "unrecognized": self.unrecognized}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> TabCounts:
        return cls(int(data.get("urls", 0)), int(data.get("indexed", 0)), int(data.get("bare", 0)),
                   {str(k): int(v) for k, v in dict(data.get("other") or {}).items()},
                   int(data.get("closed", 0)), int(data.get("unrecognized", 0)))


@dataclass(frozen=True)
class IndexStats:
    """What a build or refresh did.

    ``sitemaps_fetched`` counts the sitemaps parsed into the index (``parsed``
    names them, in order), and ``sitemaps_unchanged`` those that answered 304
    for the copy already indexed. ``rows`` counts the index rows read from the
    parsed sitemaps, and ``new_tab_ids`` the tabs the index didn't have
    before, in the order seen. ``songs_marked`` holds the ids of the accepted
    and pinned songs those new tabs belong to, flagged to fetch again as each
    sitemap was stored (``mark_dirty_for_new``). ``completed``: this call made
    the index complete (``index_state``).
    """

    sitemaps_fetched: int = 0
    sitemaps_unchanged: int = 0
    rows: int = 0
    new_tab_ids: tuple[int, ...] = ()
    parsed: tuple[str, ...] = ()
    songs_marked: frozenset[int] = frozenset()
    completed: bool = False

    def summary(self, refetch: int | None = None) -> str:
        """One line for ``caracole index refresh`` and the nightly run's index step:
        "1 of 2 sitemaps changed (sitemap_last.xml): +259 tabs, 2 songs to refetch".

        ``refetch`` is how many songs the new tabs marked to fetch again
        (``len(songs_marked)``), when the caller knows.
        """
        checked = self.sitemaps_fetched + self.sitemaps_unchanged
        if not self.sitemaps_fetched:
            line = f"{_count(checked, 'sitemap')} checked, none changed"
        else:
            new = len(self.new_tab_ids)
            which = f" ({describe_sitemaps(self.parsed)})" if self.parsed else ""
            line = (f"{self.sitemaps_fetched} of {_count(checked, 'sitemap')} changed{which}: "
                    + (f"+{_count(new, 'tab')}" if new else "no new tabs"))
            if refetch is not None:
                line += ", " + (f"{_count(refetch, 'song')} to refetch" if refetch else "no song to refetch")
        if self.completed:
            line += "; the index is now complete"
        return line


@dataclass(frozen=True)
class IndexPlan:
    """What a build or refresh is about to read: reported once, before it asks for a tab sitemap.

    ``listed`` names every tab sitemap the sitemap index lists (or every file
    found), and ``reads`` the ones this run reads, in order. Of those,
    ``indexed`` are in this database already, so each is asked for again with
    a conditional request and skipped when unchanged; and ``cached``, not
    indexed, are in the HTTP cache, so an unchanged one is read from there.
    The rest are downloaded (``downloads``). ``dropped`` counts the indexed
    tabs dropped first, as robots.txt closes their pages.
    """

    listed: tuple[str, ...]
    reads: tuple[str, ...]
    indexed: tuple[str, ...] = ()
    cached: tuple[str, ...] = ()
    dropped: int = 0

    @property
    def downloads(self) -> tuple[str, ...]:
        """The sitemaps to download: neither indexed nor in the HTTP cache."""
        known = {*self.indexed, *self.cached}
        return tuple(n for n in self.reads if n not in known)

    @property
    def expected_urls(self) -> int:
        """About how many URLs the sitemaps not indexed yet hold: ``SITEMAP_MAX_URLS`` each."""
        return SITEMAP_MAX_URLS * (len(self.reads) - len(self.indexed))


@dataclass(frozen=True)
class SitemapRead:
    """One tab sitemap done: reported once it is stored, or found unchanged.

    ``position`` counts from 1 among the ``total`` sitemaps this run reads, and
    ``label`` is its file's name (``sitemap7.xml``, or the file read).
    ``unchanged``: it answered 304 for the copy already indexed, so nothing
    was parsed. ``from_cache``: it answered 304 for a copy this database never
    indexed, which was read from the HTTP cache.
    """

    position: int
    total: int
    name: str
    label: str
    unchanged: bool = False
    from_cache: bool = False
    tabs: TabCounts = field(default_factory=TabCounts)
    new_tab_ids: tuple[int, ...] = ()


# Called with an IndexPlan, then a SitemapRead for each sitemap.
Progress = Callable[[IndexPlan | SitemapRead], None]


def _tell(progress: Progress | None, event: IndexPlan | SitemapRead) -> None:
    if progress is not None:
        progress(event)


def describe_sitemaps(names: Sequence[str], *, most: int = 4) -> str:
    """Tab sitemaps by short name, for people: "sitemap1.xml to sitemap40.xml and sitemap_last.xml".

    A run of three or more consecutive numbers (of the numbered sitemaps, or of the ukulele ones) is a
    range. Past ``most`` parts, the rest are counted: "..., sitemap12.xml and 2 more".
    """
    parts: list[str] = []
    run: list[str] = []

    def close_run() -> None:
        if len(run) >= 3:
            parts.append(f"{sitemap_label(run[0])} to {sitemap_label(run[-1])}")
        else:
            parts.extend(sitemap_label(n) for n in run)
        run.clear()

    for name in names:
        group, number = sitemap_order(name)
        if group < 2 and run and sitemap_order(run[-1]) == (group, number - 1):
            run.append(name)
            continue
        close_run()
        if group < 2:
            run.append(name)
        else:
            parts.append(sitemap_label(name))
    close_run()
    if len(parts) > most:
        parts = [*parts[: most - 1], f"{len(parts) - most + 1} more"]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _count(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- storing rows -------------------------------------------------------------------


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[IndexRow | Sequence[Any]], sitemap: str,
                now: datetime) -> list[int]:
    """Store index rows read from one sitemap; return the tab ids that are new, ascending.

    A tab listed twice in ``rows`` is stored once (the first listing wins).
    New rows record ``sitemap`` and ``now`` as where and when they were first
    seen; known rows keep those and take the new keys and path. New ids come
    from an anti-join against a temporary table, so a 50,000-row sitemap is a
    handful of statements.
    """
    with savepoint(conn, "ug_upsert"):
        conn.execute(_CREATE_BATCH)
        conn.execute("DELETE FROM temp._ug_batch")
        conn.executemany(
            "INSERT OR IGNORE INTO temp._ug_batch (tab_id, artist_key, song_key, type, path) VALUES (?, ?, ?, ?, ?)",
            ((r[0], r[1], r[2], r[3], r[4]) for r in rows),
        )
        new = [r[0] for r in conn.execute(_NEW_IN_BATCH)]
        conn.execute(_UPSERT_BATCH, (sitemap, _iso(now)))
        conn.execute("DELETE FROM temp._ug_batch")
    return new


def mark_dirty_for_new(conn: sqlite3.Connection, tab_ids: Iterable[int]) -> set[int]:
    """Flag accepted and pinned songs that new tabs belong to; return their ids.

    A song covers a tab when the tab is listed under the song's matched keys,
    or under a variant of its title (``creep-intro`` for ``creep``), exactly
    as ``ug.lookup.song_tabs`` reads them. Flagged songs get ``ug_dirty = 1``,
    so the fetch step ranks their versions again.
    """
    new = set(tab_ids)
    if not new:
        return set()
    songs = conn.execute(
        "SELECT id, match_artist_key, match_song_key FROM songs WHERE match_decision IN ('accept', 'pinned') "
        "AND status != 'ignored' AND match_artist_key IS NOT NULL AND match_song_key IS NOT NULL"
    ).fetchall()
    marked: set[int] = set()
    for s in songs:
        if any(t.tab_id in new for t in song_tabs(conn, s["match_artist_key"], s["match_song_key"])):
            update_song(conn, s["id"], ug_dirty=True)
            marked.add(s["id"])
    return marked


# --- tabs robots.txt closes ---------------------------------------------------------------------

_TAB_HOST, _TAB_PATH = urlsplit(TAB_BASE_URL).netloc, urlsplit(TAB_BASE_URL).path


def _closed_starts() -> tuple[str, ...]:
    """How the index paths of the tabs whose page robots.txt may close start ("" when any may).

    A Disallow rule of the tabs host closes the paths under ``/tab/`` that start
    with its text up to its first ``*``. "." stands for a dot segment, which a
    URL drops before the rules see it (``./download-…`` is ``download-…``).
    """
    starts = ["."]
    for rule in ROBOTS_DISALLOW.get(_TAB_HOST, ()):
        text = rule.split("*", 1)[0]
        if text.startswith(_TAB_PATH):
            starts.append(text[len(_TAB_PATH):])
        elif _TAB_PATH.startswith(text):
            starts.append("")
    return tuple(dict.fromkeys(starts))


_CLOSED_STARTS = _closed_starts()


def _closed(tab_id: int, path: str) -> bool:
    """Whether robots.txt closes the tab's page (``robots_disallows``), which caracole may then never read."""
    return path.startswith(_CLOSED_STARTS) and robots_disallows(page_url(tab_id, path)) is not None


def _drop_closed(conn: sqlite3.Connection) -> list[int]:
    """Delete the indexed tabs whose page robots.txt closes, indexed before caracole checked; return their ids.

    Only the rows whose path starts as a closed one may (``_closed_starts``) are
    read, so the check doesn't walk the whole index every night.
    """
    where = " OR ".join("substr(path, 1, ?) = ?" for _ in _CLOSED_STARTS)
    starts = [x for start in _CLOSED_STARTS for x in (len(start), start)]
    rows = conn.execute(f"SELECT tab_id, path FROM ug_index WHERE {where}", starts).fetchall()
    closed = [r[0] for r in rows if _closed(r[0], r[1])]
    with savepoint(conn, "ug_closed"):
        conn.executemany("DELETE FROM ug_index WHERE tab_id = ?", [(t,) for t in closed])
    return closed


# --- reading sitemaps ---------------------------------------------------------------


def _locs(data: bytes, where: str, status: int | None) -> list[str]:
    try:
        locs = list(iter_locs(data))
    except (OSError, EOFError, zlib.error) as e:  # a truncated or corrupt gzip body
        raise ProviderError("ug", where, status, f"unreadable sitemap: {e}") from e
    if not locs:
        raise ProviderError("ug", where, status, "not a sitemap (no <loc> entries)")
    return locs


def _rows(data: bytes, where: str, status: int | None = None) -> tuple[list[IndexRow], TabCounts]:
    """A sitemap's index rows (its tab pages, less the ones robots.txt closes), and what all its URLs became."""
    locs = _locs(data, where, status)
    rows: list[IndexRow] = []
    other: Counter[str] = Counter()
    bare = closed = unrecognized = 0
    for loc in locs:
        row = classify_tab_url(loc)
        if isinstance(row, IndexRow):
            if _closed(row.tab_id, row.path):
                closed += 1
            else:
                rows.append(row)
        elif row == BARE:
            bare += 1
        elif row == UNRECOGNIZED:
            unrecognized += 1
        else:
            other[row] += 1
    return rows, TabCounts(len(locs), len(rows), bare, dict(other), closed, unrecognized)


def _validators(headers: Mapping[str, str]) -> dict[str, str | None]:
    lower = {k.lower(): v for k, v in headers.items()}
    return {"etag": lower.get("etag"), "last_modified": lower.get("last-modified")}


def _validators_of(entry: Mapping[str, Any]) -> dict[str, str | None]:
    return {"etag": entry.get("etag"), "last_modified": entry.get("last_modified")}


def _indexed(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return kv_get_json(conn, SITEMAPS_KEY, default={}) or {}


def _store(conn: sqlite3.Connection, name: str, rows: list[IndexRow], tabs: TabCounts,
           validators: Mapping[str, str | None], now: datetime) -> tuple[list[int], set[int]]:
    """Index one sitemap's rows, flag the songs its new tabs belong to, and record it, atomically.

    Returns the new tabs' ids and the flagged songs' ids.
    """
    with savepoint(conn, "ug_sitemap"):
        new = upsert_rows(conn, rows, name, now)
        marked = mark_dirty_for_new(conn, new)
        indexed = _indexed(conn)
        indexed[name] = {**validators, "indexed_at": _iso(now), "rows": len(rows), "tabs": tabs.as_json()}
        kv_set_json(conn, SITEMAPS_KEY, indexed)
    return new, marked


def _tab_sitemap_urls(conn: sqlite3.Connection, client: Client) -> list[str]:
    """The tab sitemaps the sitemap index lists, which are kept as the last listing seen."""
    resp = client.get(SITEMAP_INDEX_URL, cache=False, conditional=True)
    urls = tab_sitemaps(_locs(resp.content, SITEMAP_INDEX_URL, resp.status))
    if not urls:
        raise ProviderError("ug", SITEMAP_INDEX_URL, resp.status, "the sitemap index lists no tab sitemaps")
    kv_set_json(conn, LISTED_KEY, [sitemap_name(u) for u in urls])
    return urls


def _plan(conn: sqlite3.Connection, client: Client, urls: list[str], reads: list[str], dropped: int) -> IndexPlan:
    indexed = _indexed(conn)
    has_cached = getattr(client, "has_cached", None)  # a PoliteClient's; a test's fake client may have none
    return IndexPlan(
        listed=tuple(sitemap_name(u) for u in urls),
        reads=tuple(sitemap_name(u) for u in reads),
        indexed=tuple(sitemap_name(u) for u in reads if sitemap_name(u) in indexed),
        cached=tuple(sitemap_name(u) for u in reads
                     if sitemap_name(u) not in indexed and has_cached is not None and has_cached(u)),
        dropped=dropped,
    )


def _index_sitemaps(conn: sqlite3.Connection, client: Client, urls: list[str], now: datetime,
                    progress: Progress | None) -> IndexStats:
    unchanged = count = 0
    new: list[int] = []
    songs: set[int] = set()
    parsed: list[str] = []
    for position, url in enumerate(urls, 1):
        name = sitemap_name(url)
        resp = client.get(url, cache=False, conditional=True)
        validators = _validators(resp.headers)
        done = _indexed(conn).get(name)
        if resp.status == 304 and done is not None and _validators_of(done) == validators:
            unchanged += 1
            _tell(progress, SitemapRead(position, len(urls), name, sitemap_label(name), unchanged=True))
            continue
        rows, tabs = _rows(resp.content, url, resp.status)
        added, marked = _store(conn, name, rows, tabs, validators, now)
        new += added
        songs |= marked
        parsed.append(name)
        count += len(rows)
        _tell(progress, SitemapRead(position, len(urls), name, sitemap_label(name), from_cache=resp.status == 304,
                                    tabs=tabs, new_tab_ids=tuple(added)))
    return IndexStats(sitemaps_fetched=len(parsed), sitemaps_unchanged=unchanged, rows=count,
                      new_tab_ids=tuple(new), parsed=tuple(parsed), songs_marked=frozenset(songs))


def _sitemap_files(directory: Path) -> list[tuple[str, Path]]:
    found: dict[str, Path] = {}
    for p in sorted(directory.iterdir()):
        m = _SITEMAP_FILE.fullmatch(p.name)
        if m and p.is_file():
            found.setdefault(m.group(1).lstrip("_"), p)
    if not found:
        raise FileNotFoundError(
            f"no sitemap files (sitemapN.xml[.gz], sitemap_ukuleleN.xml[.gz], sitemap_last.xml[.gz]) in {directory}")
    return [(n, found[n]) for n in sorted(found, key=sitemap_order)]


def _index_files(conn: sqlite3.Connection, files: list[tuple[str, Path]], now: datetime,
                 progress: Progress | None) -> IndexStats:
    count = 0
    new: list[int] = []
    songs: set[int] = set()
    parsed: list[str] = []
    for position, (name, path) in enumerate(files, 1):
        try:
            rows, tabs = _rows(path.read_bytes(), str(path))
        except ProviderError as e:
            raise ValueError(f"{path}: {e.message}") from e
        added, marked = _store(conn, name, rows, tabs, _NO_VALIDATORS, now)
        new += added
        songs |= marked
        parsed.append(name)
        count += len(rows)
        _tell(progress, SitemapRead(position, len(files), name, path.name, tabs=tabs, new_tab_ids=tuple(added)))
    return IndexStats(sitemaps_fetched=len(parsed), rows=count, new_tab_ids=tuple(new), parsed=tuple(parsed),
                      songs_marked=frozenset(songs))


def _refresh_names(listed: Sequence[str], indexed: Collection[str]) -> list[str]:
    """What a refresh reads, in listed order: ``sitemap_last``, the highest-numbered sitemap of each run
    (``sitemapN``, ``sitemap_ukuleleN``), and every one not indexed yet."""
    highest: dict[int, tuple[int, str]] = {}
    for n in listed:
        group, number = sitemap_order(n)
        if group < 2 and number >= highest.get(group, (-1, ""))[0]:
            highest[group] = (number, n)
    tops = {n for _, n in highest.values()}
    return [n for n in listed if n == "last" or n in tops or n not in indexed]


# --- the public steps ---------------------------------------------------------------


def build_index(conn: sqlite3.Connection, client: Client | None, now: datetime, *,
                from_dir: Path | None = None, progress: Progress | None = None) -> IndexStats:
    """Index every tab sitemap UG lists, or the sitemap files in ``from_dir`` (no network).

    The files are ``sitemapN.xml`` and ``sitemap_last.xml``, gzipped or not.
    ``progress`` hears the plan, then each sitemap. Raises ``ProviderError``
    (including blocks) and ``BudgetExhausted`` from the client; sitemaps
    stored before the error stay stored. Indexed tabs whose page robots.txt
    closes are dropped first.
    """
    dropped = len(_drop_closed(conn))
    first = kv_get(conn, BUILT_KEY) is None
    if from_dir is not None:
        files = _sitemap_files(Path(from_dir))
        names = tuple(name for name, _ in files)
        _tell(progress, IndexPlan(listed=names, reads=names, dropped=dropped))
        stats = _index_files(conn, files, now, progress)
    else:
        if client is None:
            raise ValueError("build_index needs a client unless from_dir is given")
        urls = _tab_sitemap_urls(conn, client)
        if progress is not None:
            progress(_plan(conn, client, urls, urls, dropped))
        stats = _index_sitemaps(conn, client, urls, now, progress)
    mark_built(conn, now)
    return replace(stats, completed=first)


def refresh_index(conn: sqlite3.Connection, client: Client, now: datetime, *,
                  progress: Progress | None = None) -> IndexStats:
    """Revalidate the sitemaps where new tabs appear: ``sitemap_last``, the highest-numbered
    sitemap, and any numbered sitemap this database has never indexed.

    The last of those are what a stopped build left: once every tab sitemap is
    indexed, the build counts as finished (``mark_built``). ``progress`` hears
    the plan, then each sitemap. Errors propagate as in ``build_index``, and
    indexed tabs whose page robots.txt closes are dropped first, as there.
    """
    dropped = len(_drop_closed(conn))
    urls = _tab_sitemap_urls(conn, client)
    wanted_names = set(_refresh_names([sitemap_name(u) for u in urls], _indexed(conn)))
    wanted = [u for u in urls if sitemap_name(u) in wanted_names]
    if progress is not None:
        progress(_plan(conn, client, urls, wanted, dropped))
    stats = _index_sitemaps(conn, client, wanted, now, progress)
    kv_set(conn, REFRESHED_KEY, _iso(now))
    if kv_get(conn, BUILT_KEY) is None:
        done = _indexed(conn)
        if all(sitemap_name(u) in done for u in urls):
            mark_built(conn, now)
            stats = replace(stats, completed=True)
    return stats


def mark_built(conn: sqlite3.Connection, now: datetime) -> None:
    """Record that the index holds every tab sitemap: a build finished, or a refresh read what one left."""
    kv_set(conn, BUILT_KEY, _iso(now))


def index_state(conn: sqlite3.Connection) -> str:
    """``"empty"`` (never built), ``"partial"`` (a build stopped part-way) or ``"complete"``.

    Nothing may be matched against a partial index: a song whose tabs are in the
    sitemaps not read yet would be marked not found (and put on the buy list), and
    an incomplete index is no more evidence of absence than an empty one.
    """
    if conn.execute("SELECT 1 FROM ug_index LIMIT 1").fetchone() is None:
        return "empty"
    return "complete" if kv_get(conn, BUILT_KEY) is not None else "partial"


def index_count(conn: sqlite3.Connection) -> int:
    """How many tabs the index holds (0 means ``caracole index build`` hasn't run)."""
    return conn.execute("SELECT COUNT(*) FROM ug_index").fetchone()[0]


def index_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Rows by type (most first), distinct artists, sitemaps indexed, and when the index was built
    and refreshed."""
    types = {
        r[0]: r[1]
        for r in conn.execute("SELECT type, COUNT(*) FROM ug_index GROUP BY type ORDER BY COUNT(*) DESC, type")
    }
    return {
        "rows": sum(types.values()),
        "types": types,
        "artists": conn.execute("SELECT COUNT(DISTINCT artist_key) FROM ug_index").fetchone()[0],
        "newest_tab_id": conn.execute("SELECT MAX(tab_id) FROM ug_index").fetchone()[0],
        "sitemaps": len(_indexed(conn)),
        "built_at": kv_get(conn, BUILT_KEY),
        "refreshed_at": kv_get(conn, REFRESHED_KEY),
    }


@dataclass(frozen=True)
class Coverage:
    """How much of UG's tab sitemaps the index holds (``index_coverage``).

    ``listed`` is what the sitemap index listed when last read (None before any
    build or refresh over the network). ``indexed`` names the sitemaps the index
    holds, and ``left`` those listed but not indexed yet: what a stopped build
    left. ``refresh`` is what ``caracole index refresh`` (and the nightly run)
    reads next, in order: ``left``, the highest-numbered sitemap and
    ``sitemap_last``. ``tabs`` sums what the indexed sitemaps' URLs became,
    over those indexed since caracole counts it.
    """

    listed: tuple[str, ...] | None
    indexed: tuple[str, ...]
    left: tuple[str, ...]
    refresh: tuple[str, ...]
    tabs: TabCounts


def index_coverage(conn: sqlite3.Connection) -> Coverage:
    """What the index holds of UG's tab sitemaps, what is left, and what a refresh reads next."""
    entries = _indexed(conn)
    tabs = sum((TabCounts.from_json(e["tabs"]) for e in entries.values() if isinstance(e.get("tabs"), dict)),
               TabCounts())
    known = tuple(sorted(entries, key=sitemap_order))
    listed = kv_get_json(conn, LISTED_KEY)
    if not isinstance(listed, list):
        return Coverage(None, known, (), (), tabs)
    listed = tuple(str(n) for n in listed)
    indexed = (*(n for n in listed if n in entries), *(n for n in known if n not in listed))
    left = tuple(n for n in listed if n not in entries)
    return Coverage(listed, indexed, left, tuple(_refresh_names(listed, entries)), tabs)
