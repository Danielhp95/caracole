"""The tabs UG's artist pages list, kept as caracole reads them, for searches (``ug_artist_tabs``, schema 7).

UG's sitemaps list a tenth of its tabs by a bare ``/tab/{id}``, every tab of an artist with an
accent or a non-Latin letter in their name among them (宋冬野, Joaquín Sabina, Maná), so the
offline index has no name for them (ug/index.py). An artist page names every tab: its title and
its artist as UG writes them ("斑马 斑马 Banma Banma Zebra Zebra", "Song Dongye (宋冬野)"), its type,
rating, votes and page. Each list page caracole reads, from UG or from its HTTP cache, is kept here
under the artist page's address (ug/fetch.py, both places it parses one, ``caracole get``
included), so that a search finds those tabs too, with no request (search.py ``find_index``).

- ``store``: a list page's tabs, added or brought up to date; an older read never overwrites a
  newer one (``read_at``, when UG gave the list). Only public tabs of the kinds caracole uses
  (chords and tabs: ug/page.py ``KINDS``), at a tab page, are kept.
- ``keep_only``: a list of one kind read whole: the page's tabs of that kind it no longer lists
  go (a tab UG dropped). A list the page cap cut short only adds.
- ``forget``: an artist page UG answers 404 for: its tabs go.
- ``backfill``: once, what caracole's HTTP cache already holds of the lists of every artist page
  caracole knows (kv ``ug:artist_url:<key>``, and ``[artist_url]`` artist pages), with no
  request: it needs only the cache, so it works while UG cools down and spends no budget.
- ``ensure_current_keys``: after a change to caracole's keys (``normalize.KEY_VERSION``), the
  keys and forms are made again from the names, with no request.

A tab is filed under the index's keys where the index lists one of its page's tabs (the artist,
by the key most of them have) or of its song's (the song, by that tab's), so that a song with both
slugged and bare-id tabs is one search hit; else under its names' slug keys, as a song accepted on
its artist page is matched (``'song-dongye-宋冬野'``, ``'斑马斑马-banma-banma-zebra-zebra'``). Its
names' forms (``normalize.name_forms``: "Song Dongye (宋冬野)" is both its names, Chinese in pinyin
too) are kept beside, for the search's prefilter and its scores.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from caracole import normalize
from caracole.db import kv_get, kv_set, kv_set_json, savepoint
from caracole.http import Response
from caracole.normalize import clean_title, listing_forms, name_forms, slug_key, split_variant
from caracole.overrides import Overrides, artist_page_address, pasted_tab_id
from caracole.ug.artist import KIND_FILTERS, artist_page_url, parse_artist_page
from caracole.ug.lookup import ARTIST_URL_KV
from caracole.ug.page import TAB_BASE_URL, PageParseError, UGVersion

log = logging.getLogger(__name__)

KEYS_KEY = "ug:artist_tabs:keys"  # the normalize.KEY_VERSION the keys were made with
BACKFILL_KEY = "ug:artist_tabs:backfill"  # set once the backfill has read the cache
KINDS = tuple(KIND_FILTERS)  # the lists of an artist page caracole reads: chords, tabs
ROWS_READ = 2000  # rows the prefilter reads, at most
_TAB_HOST = urlsplit(TAB_BASE_URL).netloc
_COLUMNS = ("page", "tab_id", "type", "artist", "title", "label", "rating", "votes", "url", "artist_key",
            "song_key", "artist_forms", "title_forms", "forms", "read_at")
_READ = tuple(c for c in _COLUMNS if c != "forms")  # what a ListedTab holds
_SELECT = f"SELECT {', '.join(_READ)} FROM ug_artist_tabs"


@dataclass(frozen=True)
class ListedTab:
    """A tab an artist page listed. ``page`` is that page's address; ``artist`` and ``title`` are UG's
    names, ``type`` caracole's kind and ``label`` its part or "acoustic" (None for none); ``url`` its
    page. ``artist_key`` and ``song_key`` are what it is filed under, ``artist_forms`` and
    ``title_forms`` its names' forms, ``read_at`` when UG gave the list."""

    page: str
    tab_id: int
    type: str
    artist: str
    title: str
    label: str | None
    rating: float
    votes: int
    url: str
    artist_key: str
    song_key: str
    artist_forms: tuple[str, ...]
    title_forms: tuple[str, ...]
    read_at: str


def _listed(row: Sequence) -> ListedTab:
    values = dict(zip(_READ, row, strict=True))
    values["artist_forms"] = tuple(values["artist_forms"].split())
    values["title_forms"] = tuple(values["title_forms"].split())
    return ListedTab(**values)


# --- writing --------------------------------------------------------------------------------


def _kept(tab: UGVersion) -> bool:
    """A public tab of a kind caracole uses, at a tab page: never Official, nor a link to UG's app."""
    if tab.kind is None or tab.access != "public":
        return False
    try:
        parts = urlsplit(tab.url)
    except ValueError:  # a link urllib can't parse: no tab page
        return False
    return parts.scheme in ("http", "https") and parts.netloc == _TAB_HOST and parts.path.startswith("/tab/")


def _names(artist: str, title: str) -> tuple[str, str, str | None, str, str, str]:
    """A tab's slug keys (the artist's, the song's without a variant label, and that label), its names'
    forms, space-separated, and every form both hyphenated and written together, for the prefilter
    ("banma" is in ``ban-ma-ban-ma``, a Chinese name's pinyin)."""
    base, variant = split_variant(slug_key(clean_title(title)))
    named = (name_forms(artist), listing_forms(clean_title(title)))
    every = [f for group in named for f in group]
    forms = " ".join(dict.fromkeys([*every, *(f.replace("-", "") for f in every)]))
    return slug_key(artist), base, variant, " ".join(named[0]), " ".join(named[1]), forms


def store(conn: sqlite3.Connection, page: str, name: str, tabs: Iterable[UGVersion], *, read_at: str) -> list[int]:
    """A list page's tabs, of the artist page at ``page`` (its address) whose artist UG names ``name``, as
    UG gave them at ``read_at``: added, or in place of an older read of them. Returns the ids kept."""
    kept = [t for t in tabs if _kept(t)]
    if not kept:
        return []
    ensure_current_keys(conn)
    sql = (f"INSERT INTO ug_artist_tabs ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)}) "
           "ON CONFLICT (page, tab_id) DO UPDATE SET "
           + ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS[2:])
           + " WHERE excluded.read_at >= ug_artist_tabs.read_at")
    with savepoint(conn, "ug_artist_tabs_store"):
        for t in kept:
            artist = name or t.artist_name
            artist_key, song_key, variant, artist_forms, title_forms, forms = _names(artist, t.song_name)
            conn.execute(sql, (page, t.tab_id, t.kind, artist, t.song_name, t.label or variant, t.rating, t.votes,
                               t.url, artist_key, song_key, artist_forms, title_forms, forms, read_at))
        _file(conn, page)
    return [t.tab_id for t in kept]


def keep_only(conn: sqlite3.Connection, page: str, kind: str, ids: Iterable[int], *, read_at: str) -> int:
    """The page's list of ``kind``, read whole at ``read_at``, lists ``ids`` alone: its other tabs of that kind
    go, unless a later read gave them. Returns how many went."""
    with savepoint(conn, "ug_artist_tabs_keep"):
        gone = conn.execute(
            "DELETE FROM ug_artist_tabs WHERE page = ? AND type = ? AND read_at <= ? "
            "AND tab_id NOT IN (SELECT value FROM json_each(?))",
            (page, kind, read_at, json.dumps(sorted(set(ids))))).rowcount
        if gone:
            _file(conn, page)
    return gone


def forget(conn: sqlite3.Connection, page: str) -> None:
    """UG answers 404 for the artist page at ``page``: its tabs go."""
    conn.execute("DELETE FROM ug_artist_tabs WHERE page = ?", (page,))


def _file(conn: sqlite3.Connection, page: str) -> None:
    """File the page's tabs: the artist under the index's key of most of the page's tabs the index lists, a
    song under the index's key of one of its tabs, and the rest under their names' slug keys."""
    rows = conn.execute("SELECT tab_id, artist, title FROM ug_artist_tabs WHERE page = ? ORDER BY tab_id",
                        (page,)).fetchall()
    if not rows:
        return
    indexed = {r[0]: (r[1], split_variant(r[2])[0]) for r in conn.execute(
        "SELECT i.tab_id, i.artist_key, i.song_key FROM ug_index i JOIN ug_artist_tabs a ON a.tab_id = i.tab_id "
        "WHERE a.page = ? ORDER BY i.tab_id", (page,))}
    own = {tab_id: _names(artist, title)[:2] for tab_id, artist, title in rows}
    artists = Counter(key for key, _ in indexed.values()) or Counter(key for key, _ in own.values())
    artist_key = artists.most_common(1)[0][0]
    songs: dict[str, str] = {}  # a song's own key → the index's
    for tab_id, (_, base) in indexed.items():
        songs.setdefault(own[tab_id][1], base)
    conn.executemany("UPDATE ug_artist_tabs SET artist_key = ?, song_key = ? WHERE page = ? AND tab_id = ?",
                     [(artist_key, songs.get(song, song), page, tab_id) for tab_id, (_, song) in own.items()])


def ensure_current_keys(conn: sqlite3.Connection) -> int:
    """Make every row's keys and forms again from its names after a change to caracole's keys, once; no
    request. Returns how many rows changed."""
    version = str(normalize.KEY_VERSION)
    if kv_get(conn, KEYS_KEY) == version:
        return 0
    made = "SELECT page, tab_id, artist_key, song_key, artist_forms, title_forms, forms FROM ug_artist_tabs"
    with savepoint(conn, "ug_artist_tabs_keys"):
        before = {(r[0], r[1]): tuple(r[2:]) for r in conn.execute(made)}
        for page, tab_id, artist, title in conn.execute(
                "SELECT page, tab_id, artist, title FROM ug_artist_tabs").fetchall():
            artist_key, song_key, _, artist_forms, title_forms, forms = _names(artist, title)
            conn.execute("UPDATE ug_artist_tabs SET artist_key = ?, song_key = ?, artist_forms = ?, title_forms = ?, "
                         "forms = ? WHERE page = ? AND tab_id = ?",
                         (artist_key, song_key, artist_forms, title_forms, forms, page, tab_id))
        for page in sorted({page for page, _ in before}):
            _file(conn, page)
        after = {(r[0], r[1]): tuple(r[2:]) for r in conn.execute(made)}
        kv_set(conn, KEYS_KEY, version)
    return sum(after[k] != v for k, v in before.items())


# --- the backfill ---------------------------------------------------------------------------------


def known_pages(conn: sqlite3.Connection, overrides: Overrides) -> list[str]:
    """Every artist page caracole knows: learned from a tab page (kv ``ug:artist_url:<key>``), and the ones
    ``[artist_url]`` names (a tab page there is read once, and its artist page learned)."""
    learned = [r[0] for r in conn.execute("SELECT value FROM kv WHERE substr(key, 1, ?) = ?",
                                          (len(ARTIST_URL_KV), ARTIST_URL_KV))]
    pasted = [url for url in overrides.artist_url.values() if pasted_tab_id(url) is None]
    return sorted({page for page in map(artist_page_address, [*learned, *pasted]) if page})


def backfill(conn: sqlite3.Connection, client: object, overrides: Overrides) -> int:
    """Once, the lists caracole's HTTP cache holds of every artist page it knows (``known_pages``) into the
    table, as a database from before it lacks them; returns how many tabs it stored. ``client`` reads the
    cache (``cached``: a ``PoliteClient``'s, or ``http.CachedAnswers``); nothing is sent, so it works while
    UG cools down and spends no budget. A list the cache lacks, or one that won't parse, is left to the
    next time caracole reads that page. The keys are made current first (``ensure_current_keys``)."""
    ensure_current_keys(conn)
    cached: Callable[..., Response | None] | None = getattr(client, "cached", None)  # a test's fake may have none
    if cached is None or kv_get(conn, BACKFILL_KEY) is not None:
        return 0
    pages = known_pages(conn, overrides)
    stored: set[tuple[str, int]] = set()
    for page in pages:
        for kind in (*KINDS, None):  # the unfiltered list last: the filtered ones give every tab of a kind
            stored |= {(page, tab_id) for tab_id in _cached_list(conn, cached, page, kind)}
    kv_set_json(conn, BACKFILL_KEY, {"pages": len(pages), "tabs": len(stored)})
    return len(stored)


def _cached_list(conn: sqlite3.Connection, cached: Callable[..., Response | None], page: str,
                 kind: str | None) -> list[int]:
    """The tabs of one of the page's lists, from as many of its pages as the cache holds in a row, stored."""
    ids: list[int] = []
    number, last = 1, 1
    while number <= last:
        url = artist_page_url(page, kind=kind, page=number)
        answer = cached(url, accept=(200,))
        if answer is None:
            break
        try:
            listed = parse_artist_page(answer.content, url=url)
        except PageParseError as e:
            log.debug("UG artist page %s, in the cache, can't be read: %s", url, e)
            break
        last = max(last, listed.pages)
        tabs = listed.tabs if kind is None else [t for t in listed.tabs if t.kind == kind]
        ids += store(conn, page, listed.name, tabs, read_at=answer.fetched_at or "")
        number += 1
    return ids


# --- reading, for searches ---------------------------------------------------------------------------


def rows_like(conn: sqlite3.Connection, patterns: Sequence[str]) -> list[ListedTab]:
    """The tabs whose names' forms hold one of the ``LIKE`` patterns, hyphens and all or written together
    ("banma" is in ``ban-ma-ban-ma``): those holding more of them first, then the shortest names, at most
    ``ROWS_READ``."""
    if not patterns:
        return []
    where = " OR ".join(f"forms LIKE ?{n}" for n in range(1, len(patterns) + 1))
    held = " + ".join(f"(forms LIKE ?{n})" for n in range(1, len(patterns) + 1))
    rows = conn.execute(f"{_SELECT} WHERE {where} ORDER BY {held} DESC, length(forms), page, tab_id "
                        f"LIMIT {ROWS_READ}", list(patterns))
    return [_listed(r) for r in rows]


def song_tabs(conn: sqlite3.Connection, artist_key: str, song_key: str) -> list[ListedTab]:
    """The tabs of a song, as it is filed, each once (its latest read), by id."""
    rows = conn.execute(f"{_SELECT} WHERE artist_key = ? AND song_key = ? ORDER BY tab_id, read_at DESC",
                        (artist_key, song_key))
    tabs: dict[int, ListedTab] = {}
    for row in rows:
        tab = _listed(row)
        tabs.setdefault(tab.tab_id, tab)
    return list(tabs.values())


def unindexed_songs(conn: sqlite3.Connection, artist_key: str) -> dict[str, int]:
    """Each song of an artist, as filed, with its tabs the offline index doesn't list (bare ids)."""
    rows = conn.execute(
        "SELECT song_key, COUNT(DISTINCT tab_id) FROM ug_artist_tabs a WHERE artist_key = ? "
        "AND NOT EXISTS (SELECT 1 FROM ug_index i WHERE i.tab_id = a.tab_id) GROUP BY song_key", (artist_key,))
    return {song_key: n for song_key, n in rows}


def artist_page(conn: sqlite3.Connection, artist_key: str) -> str | None:
    """The artist page that lists most of an artist's tabs, as filed; None when none does."""
    row = conn.execute("SELECT page FROM ug_artist_tabs WHERE artist_key = ? GROUP BY page "
                       "ORDER BY COUNT(*) DESC, page LIMIT 1", (artist_key,)).fetchone()
    return row[0] if row is not None else None
