"""The local Ultimate Guitar index, built from UG's sitemaps (plan §2).

``tabarr index build`` reads every tab sitemap once (about 42 requests, or
local files with ``from_dir``). The nightly refresh asks again only for the
sitemap index, ``sitemap_last``, the highest-numbered sitemap and any numbered
sitemap this database has never indexed, because new tabs appear only there.

Every sitemap is fetched with a conditional GET. A 304 skips parsing only when
this database indexed exactly that copy; otherwise the cached body is parsed.
That covers a fresh database next to a warm HTTP cache, and a run that died
after a download but before its rows were stored.

Each sitemap is stored in one transaction: its rows, the songs its new tabs
make dirty, and its entry in ``kv['ug:sitemaps']`` (the validators of the
indexed copy, when, and how many rows). A failure later in the run loses
nothing already stored.
"""

from __future__ import annotations

import re
import sqlite3
import zlib
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tabarr.db import kv_get, kv_get_json, kv_set, kv_set_json
from tabarr.http import Client, ProviderError
from tabarr.songs import update_song
from tabarr.ug.lookup import song_tabs
from tabarr.ug.sitemap import IndexRow, iter_locs, parse_tab_url, sitemap_name, tab_sitemaps

SITEMAP_INDEX_URL = "https://www.ultimate-guitar.com/sitemap.xml"

_SITEMAPS_KEY = "ug:sitemaps"
_BUILT_KEY = "ug:index:built_at"
_REFRESHED_KEY = "ug:index:refreshed_at"
_SITEMAP_FILE = re.compile(r"sitemap(\d+|_last)\.xml(?:\.gz)?")
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
class IndexStats:
    """What a build or refresh did.

    ``sitemaps_fetched`` counts the sitemaps parsed into the index, and
    ``sitemaps_unchanged`` those that answered 304 for the copy already
    indexed. ``rows`` counts the index rows read from the parsed sitemaps, and
    ``new_tab_ids`` the tabs the index didn't have before, in the order seen.
    """

    sitemaps_fetched: int = 0
    sitemaps_unchanged: int = 0
    rows: int = 0
    new_tab_ids: tuple[int, ...] = ()


# Called after each sitemap with its short name ("12", "last") and what it did.
Progress = Callable[[str, IndexStats], None]


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _transaction(conn: sqlite3.Connection, name: str) -> Iterator[None]:
    """A savepoint: a transaction of its own, or a nested one inside the caller's."""
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    conn.execute(f"RELEASE {name}")


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
    with _transaction(conn, "ug_upsert"):
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


def mark_dirty_for_new(conn: sqlite3.Connection, tab_ids: Iterable[int]) -> int:
    """Flag accepted and pinned songs that new tabs belong to; return how many there are.

    A song covers a tab when the tab is listed under the song's matched keys,
    or under a variant of its title (``creep-intro`` for ``creep``), exactly
    as ``ug.lookup.song_tabs`` reads them. Flagged songs get ``ug_dirty = 1``,
    so the fetch step ranks their versions again.
    """
    new = set(tab_ids)
    if not new:
        return 0
    songs = conn.execute(
        "SELECT id, match_artist_key, match_song_key FROM songs WHERE match_decision IN ('accept', 'pinned') "
        "AND status != 'ignored' AND match_artist_key IS NOT NULL AND match_song_key IS NOT NULL"
    ).fetchall()
    marked = 0
    for s in songs:
        if any(t.tab_id in new for t in song_tabs(conn, s["match_artist_key"], s["match_song_key"])):
            update_song(conn, s["id"], ug_dirty=True)
            marked += 1
    return marked


# --- reading sitemaps ---------------------------------------------------------------


def _locs(data: bytes, where: str, status: int | None) -> list[str]:
    try:
        locs = list(iter_locs(data))
    except (OSError, EOFError, zlib.error) as e:  # a truncated or corrupt gzip body
        raise ProviderError("ug", where, status, f"unreadable sitemap: {e}") from e
    if not locs:
        raise ProviderError("ug", where, status, "not a sitemap (no <loc> entries)")
    return locs


def _rows(data: bytes, where: str, status: int | None = None) -> list[IndexRow]:
    return [r for r in map(parse_tab_url, _locs(data, where, status)) if r is not None]


def _validators(headers: Mapping[str, str]) -> dict[str, str | None]:
    lower = {k.lower(): v for k, v in headers.items()}
    return {"etag": lower.get("etag"), "last_modified": lower.get("last-modified")}


def _validators_of(entry: Mapping[str, Any]) -> dict[str, str | None]:
    return {"etag": entry.get("etag"), "last_modified": entry.get("last_modified")}


def _indexed(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return kv_get_json(conn, _SITEMAPS_KEY, default={}) or {}


def _store(conn: sqlite3.Connection, name: str, rows: list[IndexRow], validators: Mapping[str, str | None],
           now: datetime) -> list[int]:
    """Index one sitemap's rows, flag the songs its new tabs belong to, and record it, atomically."""
    with _transaction(conn, "ug_sitemap"):
        new = upsert_rows(conn, rows, name, now)
        mark_dirty_for_new(conn, new)
        indexed = _indexed(conn)
        indexed[name] = {**validators, "indexed_at": _iso(now), "rows": len(rows)}
        kv_set_json(conn, _SITEMAPS_KEY, indexed)
    return new


def _tab_sitemap_urls(client: Client) -> list[str]:
    resp = client.get(SITEMAP_INDEX_URL, cache=False, conditional=True)
    urls = tab_sitemaps(_locs(resp.content, SITEMAP_INDEX_URL, resp.status))
    if not urls:
        raise ProviderError("ug", SITEMAP_INDEX_URL, resp.status, "the sitemap index lists no tab sitemaps")
    return urls


def _index_sitemaps(conn: sqlite3.Connection, client: Client, urls: list[str], now: datetime,
                    progress: Progress | None) -> IndexStats:
    fetched = unchanged = count = 0
    new: list[int] = []
    for url in urls:
        name = sitemap_name(url)
        resp = client.get(url, cache=False, conditional=True)
        validators = _validators(resp.headers)
        done = _indexed(conn).get(name)
        if resp.status == 304 and done is not None and _validators_of(done) == validators:
            unchanged += 1
            if progress is not None:
                progress(name, IndexStats(sitemaps_unchanged=1))
            continue
        rows = _rows(resp.content, url, resp.status)
        added = _store(conn, name, rows, validators, now)
        new += added
        fetched += 1
        count += len(rows)
        if progress is not None:
            progress(name, IndexStats(sitemaps_fetched=1, rows=len(rows), new_tab_ids=tuple(added)))
    return IndexStats(sitemaps_fetched=fetched, sitemaps_unchanged=unchanged, rows=count, new_tab_ids=tuple(new))


def _sitemap_files(directory: Path) -> list[tuple[str, Path]]:
    found: dict[str, Path] = {}
    for p in sorted(directory.iterdir()):
        m = _SITEMAP_FILE.fullmatch(p.name)
        if m and p.is_file():
            found.setdefault(m.group(1).lstrip("_"), p)
    if not found:
        raise FileNotFoundError(f"no sitemap files (sitemapN.xml[.gz], sitemap_last.xml[.gz]) in {directory}")
    numbered = sorted((n for n in found if n != "last"), key=int)
    return [(n, found[n]) for n in [*numbered, *(["last"] if "last" in found else [])]]


def _index_files(conn: sqlite3.Connection, directory: Path, now: datetime, progress: Progress | None) -> IndexStats:
    fetched = count = 0
    new: list[int] = []
    for name, path in _sitemap_files(directory):
        try:
            rows = _rows(path.read_bytes(), str(path))
        except ProviderError as e:
            raise ValueError(f"{path}: {e.message}") from e
        added = _store(conn, name, rows, _NO_VALIDATORS, now)
        new += added
        fetched += 1
        count += len(rows)
        if progress is not None:
            progress(name, IndexStats(sitemaps_fetched=1, rows=len(rows), new_tab_ids=tuple(added)))
    return IndexStats(sitemaps_fetched=fetched, rows=count, new_tab_ids=tuple(new))


# --- the public steps ---------------------------------------------------------------


def build_index(conn: sqlite3.Connection, client: Client | None, now: datetime, *,
                from_dir: Path | None = None, progress: Progress | None = None) -> IndexStats:
    """Index every tab sitemap UG lists, or the sitemap files in ``from_dir`` (no network).

    The files are ``sitemapN.xml`` and ``sitemap_last.xml``, gzipped or not.
    ``progress`` is called after each sitemap. Raises ``ProviderError``
    (including blocks) and ``BudgetExhausted`` from the client; sitemaps
    stored before the error stay stored.
    """
    if from_dir is not None:
        stats = _index_files(conn, Path(from_dir), now, progress)
    else:
        if client is None:
            raise ValueError("build_index needs a client unless from_dir is given")
        stats = _index_sitemaps(conn, client, _tab_sitemap_urls(client), now, progress)
    kv_set(conn, _BUILT_KEY, _iso(now))
    return stats


def refresh_index(conn: sqlite3.Connection, client: Client, now: datetime, *,
                  progress: Progress | None = None) -> IndexStats:
    """Revalidate the sitemaps where new tabs appear: ``sitemap_last``, the highest-numbered
    sitemap, and any numbered sitemap this database has never indexed.

    ``progress`` is called after each sitemap. Errors propagate as in ``build_index``.
    """
    urls = _tab_sitemap_urls(client)
    indexed = _indexed(conn)
    numbered = [u for u in urls if sitemap_name(u) != "last"]
    highest = numbered[-1] if numbered else None
    wanted = [u for u in urls if sitemap_name(u) == "last" or u == highest or sitemap_name(u) not in indexed]
    stats = _index_sitemaps(conn, client, wanted, now, progress)
    kv_set(conn, _REFRESHED_KEY, _iso(now))
    return stats


def index_count(conn: sqlite3.Connection) -> int:
    """How many tabs the index holds (0 means ``tabarr index build`` hasn't run)."""
    return conn.execute("SELECT COUNT(*) FROM ug_index").fetchone()[0]


def index_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Rows by type, distinct artists, sitemaps indexed, and when the index was built and refreshed."""
    types = {
        r[0]: r[1] for r in conn.execute("SELECT type, COUNT(*) FROM ug_index GROUP BY type ORDER BY COUNT(*) DESC")
    }
    return {
        "rows": sum(types.values()),
        "types": types,
        "artists": conn.execute("SELECT COUNT(DISTINCT artist_key) FROM ug_index").fetchone()[0],
        "newest_tab_id": conn.execute("SELECT MAX(tab_id) FROM ug_index").fetchone()[0],
        "sitemaps": len(_indexed(conn)),
        "built_at": kv_get(conn, _BUILT_KEY),
        "refreshed_at": kv_get(conn, _REFRESHED_KEY),
    }
