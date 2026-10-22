"""LaCuerda's artists in a local index, with the songs of the artist pages caracole has read.

LaCuerda has no sitemap. Its listings of every artist, an initial at a time and 100 artists
a page (lacuerda.py), are read into ``lacuerda_index`` (db.py): a row per artist, with the
name LaCuerda writes, the slug of their page, its identity key and the songs the listing
counts. The songs of an artist come from their page, whenever caracole has one, with no
request of their own: each page lacuerda_fetch.py reads (``store_artist_page``), and, as a
listing page is read, the cached pages of its artists, and, each night, every artist page
the HTTP cache holds that the index hasn't read (``backfill_cached``). A song's row has its
title and key, its versions, its best Letra y Acordes version and its place in the artist's
popularity. LaCuerda's own search (lacuerda_search.py) adds the songs it answers, in the same
shape, and the artists it names that no listing read has yet (``store_search``): their page
is ``SEARCH_PAGE``, so an artist's songs from their own page are told from those a search
brought.

**The refresh** (``refresh``) reads the listings when they never were all read, and again
after 30 days, as site_index.py reads sitemaps: each letter's first page, which names the
letter's others, then those, with conditional requests (a page unchanged since costs one
request and isn't parsed). A refresh the budget cuts short goes on where it stopped: a page
read or found unchanged in this round isn't asked for again until 30 days have passed. Each
page is stored in one transaction, its artists in place of those it gave before; a page its
letter no longer lists leaves the index, and so do the artists of a page that answers 404.
Every request is the client's, with its budget and its pauses. A block, a spent budget or
any other ``ProviderError`` (a page that won't parse included) propagates, and what was
stored before stays: an error is never a letter without artists. A full read is about
200 requests (E alone has 7 pages); with LaCuerda's budget of 30 a run, it takes a week of
nights, each going on where the last stopped. The kv records are ``lacuerda:index:pages``
(each page's validators, rows, the letter's pages and when it was last checked),
``lacuerda:index:complete_at`` and ``lacuerda:index:keys``: after a change to caracole's
keys (``normalize.KEY_VERSION``), the keys are made again from the names, with no request.

**Searching** (``find``) reads the table alone and asks LaCuerda nothing. Names are compared
as search.py compares the Ultimate Guitar index's: as words, accents folded, the identity
keys' folding too (a leading "Los", an artist's "y", number words), Chinese as pinyin, with a
``LIKE`` prefilter on the query's three longest words, and rapidfuzz to rank. A query may be
an artist, a title or both: each hit says which reading scored it (``via``). The artists come
apart from the songs, and a song only its artist's name matched is in its artist's row
(``LaCuerdaHit.top``), never a hit of its own. As most artists' songs aren't in the index, an
artist whose whole name is words of the query among others ("estopa como camaron") is a
possible match: ``NAMED`` (80), by "both", below a strong hit; and so, below that, is one with
a word of their name at the query's start or end, the rest a title ("bunbury lady blue":
Enrique Bunbury, ``WORD_NAMED``), when an index knows that title of theirs, or they are well
known and few names hold the word, and no artist's whole name is in the query. Letters inside a word of a name or
a title score below a strong hit (``INSIDE_SCALE``: "maná" is no David Chumaña, nor "Esta
mañana"): only whole words, or a name's start as typed so far ("joaquin sab"), make one. While a
letter's listing isn't
read whole, no artist found is no sign that LaCuerda lacks them: ``unread_letter`` says under
which letter a name would be, for a search to offer reading the page of that name.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from caracole import normalize, stamps
from caracole.db import kv_get, kv_get_json, kv_set, kv_set_json, savepoint
from caracole.http import (
    BudgetExhausted,
    Client,
    ProviderBlocked,
    ProviderError,
    ProviderUnavailable,
    cached_answer,
)
from caracole.lacuerda import (
    BASE_URL,
    LETTERS,
    LaCuerdaParseError,
    LCArtist,
    LCSong,
    Listing,
    SearchAnswer,
    artist_slug_candidates,
    artist_url,
    best_acordes_version,
    is_missing_artist_page,
    listing_path,
    listing_url,
    parse_artist_name,
    parse_artist_page,
    parse_listing_page,
    parse_popularity,
    song_url,
    version_url,
)
from caracole.normalize import (
    PINYIN_PARTIAL_SCALE,
    fold,
    has_han,
    holds_run,
    identity_key,
    name_forms,
    name_words,
    romanize,
    slug_key,
)

log = logging.getLogger(__name__)

INDEX_MAX_AGE = timedelta(days=30)
PAGES_KEY = "lacuerda:index:pages"
COMPLETE_KEY = "lacuerda:index:complete_at"
KEYS_KEY = "lacuerda:index:keys"
_ACCEPT = (200, 404)

MIN_SCORE = 70  # below this a hit is noise
PARTIAL_SCALE = 0.9  # a query that is only part of a name tops out at 90
NAMED = 80.0  # an artist's whole name among the query's other words: a possible match, below a strong hit
WORD_NAMED = 75.0  # a word of an artist's name at the query's start or end, the rest a title: below NAMED
INSIDE_SCALE = 0.85  # letters inside a word of a name ("mana" of Chumaña): at most 85, never a strong hit
SEARCH_PAGE = "busca.php"  # the page of the rows LaCuerda's search answered (store_search)
READINGS = ("title", "both", "artist")  # how a query may name a song; a tie goes to the first
ARTIST_ROWS, SONG_ROWS, TOP_SONGS = 3, 5, 3  # what ``find`` gives by default
WORD_ARTISTS, WORD_SHARE = 10, 500  # a word in more names than this, and in more than 1 in 500 listed, is common
ROWS_READ = 2000  # rows the prefilter reads, at most: those that hold more of the query's words first
MAX_PATTERNS, MAX_EXTRA = 3, 2
CLOSE_LETTERS = 4  # a word of a name shorter than this, at the query's start or end, names no one (WORD_NAMED)
WORD_FEW, WORD_KNOWN = 2, 50  # a word in this many names at most names a well-known artist (this many songs) so

_COLUMNS = ("path", "artist_slug", "artist", "artist_key", "title", "title_key", "songs", "versions",
            "acordes", "popular", "page")


# --- keys -----------------------------------------------------------------------------------


def name_key(name: str) -> str:
    """An artist's key: the artist side of their identity key, Chinese in pinyin ("Los Enanitos
    Verdes" and "Enanitos Verdes" are ``enanitos-verdes``, 宋冬野 ``song-dong-ye``)."""
    return identity_key(romanize(name), "").partition("/")[0]


def title_key(title: str) -> str:
    """A song's key: the title side of its identity key, Chinese in pinyin ("Té para tres (En Vivo)"
    is ``te-para-3``)."""
    return identity_key("", romanize(title)).partition("/")[2]


def ensure_current_keys(conn: sqlite3.Connection) -> int:
    """Make every row's keys again from its names after a change to caracole's keys, once; no request.
    Returns how many rows changed."""
    version = str(normalize.KEY_VERSION)
    if kv_get(conn, KEYS_KEY) == version:
        return 0
    changed = 0
    with savepoint(conn, "lacuerda_index_keys"):
        rows = conn.execute("SELECT path, artist, title, artist_key, title_key FROM lacuerda_index").fetchall()
        for path, artist, title, old_artist, old_title in rows:
            keys = (name_key(artist), title_key(title) if title else "")
            if keys != (old_artist, old_title):
                conn.execute("UPDATE lacuerda_index SET artist_key = ?, title_key = ? WHERE path = ?", (*keys, path))
                changed += 1
        kv_set(conn, KEYS_KEY, version)
    return changed


# --- the table ------------------------------------------------------------------------------


def store_artists(conn: sqlite3.Connection, page: str, artists: Sequence[LCArtist]) -> None:
    """A listing page's artists in place of those it gave before (``page``: its path)."""
    rows = [(f"{a.slug}/", a.slug, a.name, name_key(a.name), "", "", a.songs, "", 0, None, page) for a in artists]
    _replace(conn, page, rows)


def store_songs(conn: sqlite3.Connection, slug: str, name: str | None, songs: Sequence[LCSong],
                popular: Mapping[str, int] | None = None) -> None:
    """An artist page's songs in place of those it gave before. ``name``: the artist's, as the page
    heads it; without one, the index's row names them, else their slug does."""
    if not name:
        row = conn.execute("SELECT artist FROM lacuerda_index WHERE path = ?", (f"{slug}/",)).fetchone()
        name = row[0] if row is not None else " ".join(w.capitalize() for w in slug.split("_") if w) or slug
    popular = popular or {}
    key = name_key(name)
    rows = [(f"{slug}/{s.slug}", slug, name, key, s.title, title_key(s.title), 0, s.types,
             best_acordes_version(s) or 0, popular.get(s.slug), f"{slug}/") for s in songs]
    _replace(conn, f"{slug}/", rows)


def store_artist_page(conn: sqlite3.Connection, slug: str, html: str) -> bool:
    """The songs of an artist page into the index, as lacuerda_fetch.py reads it. False, and nothing
    stored, for LaCuerda's "no such artist" body or a page that won't parse."""
    if is_missing_artist_page(html):
        return False
    try:
        songs = parse_artist_page(html)
    except LaCuerdaParseError:
        return False
    store_songs(conn, slug, parse_artist_name(html), songs, parse_popularity(html))
    return True


def store_search(conn: sqlite3.Connection, answer: SearchAnswer) -> int:
    """The rows of an answer of LaCuerda's search into the index, beside what it holds; how many it stored.

    Each song in the shape an artist page's has (its lcd letters, its best Letra y Acordes version), its page
    ``SEARCH_PAGE``; a song the index has already keeps its page and its place in the artist's popularity, and
    takes the answer's versions. Each artist of the answer that no listing read names yet gets a row of their own
    (``SEARCH_PAGE``), for searches and for the slugs a sheet is looked for under, which their listing's row
    replaces once it is read; a listing's row is never touched. In one transaction."""
    ensure_current_keys(conn)
    named: dict[str, tuple[str, int]] = {}
    for a in answer.artists:
        named[a.slug] = (a.name, a.songs)
    for s in answer.songs:
        named.setdefault(s.artist_slug, (s.artist, 0))
    with savepoint(conn, "lacuerda_index_search"):
        for s in answer.songs:
            conn.execute(
                f"INSERT INTO lacuerda_index ({', '.join(_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, ?) "
                "ON CONFLICT(path) DO UPDATE SET title = excluded.title, title_key = excluded.title_key, "
                "versions = excluded.versions, acordes = excluded.acordes",
                (f"{s.artist_slug}/{s.slug}", s.artist_slug, s.artist, name_key(s.artist), s.title, title_key(s.title),
                 s.song.types, best_acordes_version(s.song) or 0, SEARCH_PAGE))
        for slug, (name, songs) in named.items():
            conn.execute(
                f"INSERT INTO lacuerda_index ({', '.join(_COLUMNS)}) VALUES (?, ?, ?, ?, '', '', ?, '', 0, NULL, ?) "
                "ON CONFLICT(path) DO UPDATE SET songs = max(songs, excluded.songs) WHERE page = excluded.page",
                (f"{slug}/", slug, name, name_key(name), songs, SEARCH_PAGE))
    return len(answer.songs) + len(answer.artists)


_ARTIST_PAGE = re.compile(re.escape(BASE_URL) + r"/([a-z0-9_]+)/")


def backfill_cached(conn: sqlite3.Connection, client: Client) -> int:
    """The songs of every artist page the HTTP cache holds that the index hasn't read (no song of theirs comes from
    their page), stored from the cache alone (``store_artist_page``): no request, whatever the budget, a block or a
    cooldown. Returns how many pages it stored. A cache it can't read is none."""
    root = getattr(client, "cache_root", None)  # a PoliteClient's; a test's fake client may have none
    if root is None:
        return 0
    read = {r[0] for r in conn.execute("SELECT DISTINCT page FROM lacuerda_index WHERE title != '' AND page != ?",
                                       (SEARCH_PAGE,))}
    stored = 0
    try:
        metas = sorted(Path(root).glob("*/*.json"))
    except OSError:
        return 0
    for meta in metas:
        try:
            said = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found = _ARTIST_PAGE.fullmatch(str(said.get("url", ""))) if isinstance(said, dict) else None
        if found is None or said.get("status") != 200 or f"{found.group(1)}/" in read:
            continue
        cached = cached_answer(Path(root), found.group(0))
        if cached is not None and store_artist_page(conn, found.group(1), cached.text):
            stored += 1
    return stored


def artist_slugs(conn: sqlite3.Connection, name: str) -> list[str]:
    """The slugs of the artist pages the listings give for an artist's name, most songs first.

    LaCuerda's names meet yours by identity key, the name's own and that of each of its forms
    (``normalize.name_forms``), so a name in two scripts meets the listing's by either part.
    """
    keys = [k for k in dict.fromkeys([name_key(name), *(name_key(f) for f in name_forms(name))]) if k]
    if not keys:
        return []
    marks = ", ".join("?" for _ in keys)
    rows = conn.execute(f"SELECT artist_slug FROM lacuerda_index WHERE artist_key IN ({marks}) AND title = '' "
                        "ORDER BY songs DESC, artist_slug", keys)
    return [r[0] for r in rows]


def index_size(conn: sqlite3.Connection) -> tuple[int, int]:
    """How many artists and songs the index holds."""
    row = conn.execute("SELECT COUNT(*) FILTER (WHERE title = ''), COUNT(*) FILTER (WHERE title != '') "
                       "FROM lacuerda_index").fetchone()
    return row[0], row[1]


@dataclass(frozen=True)
class IndexState:
    """What the index holds, for a search to say: its artists and songs, whether every listing page was
    read (``complete``), and the letters (``LETTERS``) whose every page it holds so far (``letters_read``)."""

    artists: int
    songs: int
    complete: bool
    letters: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return self.artists == 0 and self.songs == 0


def index_state(conn: sqlite3.Connection) -> IndexState:
    """The index's ``IndexState``; no request."""
    artists, songs = index_size(conn)
    return IndexState(artists, songs, complete_at(conn) is not None, tuple(letters_read(conn)))


def letters_read(conn: sqlite3.Connection) -> list[str]:
    """The letters whose every listing page the index holds (read, found unchanged, or gone), in
    ``LETTERS``' order: a search finds every artist of those. A refresh the budget cut short leaves the
    letter it stopped in out until its other pages are read."""
    indexed = pages(conn)
    done = []
    for letter in LETTERS:
        first = indexed.get(listing_path(letter))
        if first is not None and all(listing_path(letter, p) in indexed for p in first.get("pages", ())):
            done.append(letter)
    return done


def unread_letter(conn: sqlite3.Connection, name: str) -> str | None:
    """The letter (``LETTERS``) whose listing an artist of this name would be in, while the index hasn't read
    it whole (an empty index has read none): no artist of theirs in the index is no sign that LaCuerda lacks
    them then, and their page can tell. The first unread letter of the slugs their page may have
    (``lacuerda.artist_slug_candidates``); None once those letters are read, or the whole index is, and for
    a name no slug can be made of."""
    if complete_at(conn) is not None:
        return None
    read = set(letters_read(conn))
    for slug in artist_slug_candidates(name):
        letter = "_num" if slug[0].isdigit() else slug[0]
        if letter in LETTERS and letter not in read:
            return letter
    return None


_LETTER_NAMES = {"_num": "#", "nn": "Ñ"}


def letters_text(letters: Sequence[str]) -> str:
    """Letters as LaCuerda's menu names them ("#" for a name that starts with a digit, "Ñ"), three in a row
    or more as a range: "#, A–C", "A, B, E"."""
    order = {letter: n for n, letter in enumerate(LETTERS)}
    runs: list[list[str]] = []
    for letter in sorted(dict.fromkeys(letters), key=lambda x: order.get(x, len(order))):
        if runs and letter != "_num" and runs[-1][-1] != "_num" and order.get(letter) == order.get(runs[-1][-1], -2) + 1:
            runs[-1].append(letter)
        else:
            runs.append([letter])
    name = lambda x: _LETTER_NAMES.get(x, x.upper())  # noqa: E731
    return ", ".join(f"{name(r[0])}–{name(r[-1])}" if len(r) > 2 else ", ".join(map(name, r)) for r in runs)


def _replace(conn: sqlite3.Connection, page: str, rows: Sequence[Sequence[Any]]) -> None:
    ensure_current_keys(conn)
    marks = ", ".join("?" for _ in _COLUMNS)
    with savepoint(conn, "lacuerda_index_store"):
        conn.execute("DELETE FROM lacuerda_index WHERE page = ?", (page,))
        conn.executemany(f"INSERT OR REPLACE INTO lacuerda_index ({', '.join(_COLUMNS)}) VALUES ({marks})", rows)


# --- the refresh ----------------------------------------------------------------------------


@dataclass
class IndexStats:
    """What one ``index_pass`` did: the listing pages read into the index (one found unchanged isn't), and the
    artist pages it took from the HTTP cache (``backfill_cached``)."""

    pages: int = 0
    cached: int = 0
    errors: int = 0
    budget_exhausted: bool = False


def index_pass(conn: sqlite3.Connection, client: Client, now: datetime) -> IndexStats:
    """Read LaCuerda's listings into the index when due, as the nightly lacuerda step does, after the artist pages
    the HTTP cache holds and the index hasn't read (``backfill_cached``, no request).

    ``ProviderBlocked`` propagates. A spent budget ends the pass (``budget_exhausted``), and
    so does a client that gives up on LaCuerda for the run; any other provider error counts in
    ``errors``. Either way the index keeps what it holds, and the next run goes on.
    """
    stats = IndexStats()

    def read() -> None:
        stats.pages += 1

    stats.cached = backfill_cached(conn, client)
    try:
        refresh(conn, client, now, on_read=read)
    except ProviderBlocked:
        raise
    except BudgetExhausted:
        stats.budget_exhausted = True
    except ProviderUnavailable as e:
        log.warning("LaCuerda is unavailable for the rest of this run: %s", e)
    except ProviderError as e:
        stats.errors += 1
        log.warning("LaCuerda's artist listings: %s", e)
    return stats


def refresh(conn: sqlite3.Connection, client: Client, now: datetime,
            on_read: Callable[[], None] = lambda: None) -> None:
    """Read LaCuerda's listings into the index when due (see the module docstring).

    ``on_read`` is called for each listing page stored (one found unchanged isn't), as it is
    stored, so a count survives a refresh the budget cuts short.
    """
    now = stamps.utc(now)
    ensure_current_keys(conn)
    complete = complete_at(conn)
    if complete is not None and now - complete < INDEX_MAX_AGE:
        return
    for name in [n for n in pages(conn) if _letter(n) not in LETTERS]:
        _forget(conn, name)
    for letter in LETTERS:
        first = listing_path(letter)
        listed = [listing_path(letter, p) for p in _read(conn, client, first, now, on_read)]
        for name in [n for n in pages(conn) if _letter(n) == letter and n != first and n not in listed]:
            _forget(conn, name)
        for name in listed:
            if name != first:
                _read(conn, client, name, now, on_read)
    kv_set(conn, COMPLETE_KEY, stamps.stamp(now))


def pages(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Each listing page in the index, by path: its validators, its rows, the letter's pages (a first
    page's) and when it was last checked."""
    return kv_get_json(conn, PAGES_KEY, default={}) or {}


def complete_at(conn: sqlite3.Connection) -> datetime | None:
    """When every listing page was last read or found unchanged; None before that."""
    return stamps.parse(kv_get(conn, COMPLETE_KEY))


def _read(conn: sqlite3.Connection, client: Client, name: str, now: datetime,
          on_read: Callable[[], None]) -> tuple[str, ...]:
    """One listing page into the index, unless checked in this round: the letter's pages it lists."""
    entry = pages(conn).get(name)
    if entry is not None and not stamps.before(entry.get("checked_at"), now - INDEX_MAX_AGE):
        return tuple(entry.get("pages", ()))
    url = listing_url(name)
    resp = client.get(url, cache=False, conditional=True, accept=_ACCEPT)
    validators = _validators(resp.headers)
    if resp.status == 304 and entry is not None and entry.get("rows") is not None and \
            _validators_of(entry) == validators:
        _record(conn, name, {**entry, "checked_at": stamps.stamp(now)})
        return tuple(entry.get("pages", ()))
    if resp.status == 404:  # no such page: its artists go, and it is checked for this round
        with savepoint(conn, "lacuerda_index_gone"):
            conn.execute("DELETE FROM lacuerda_index WHERE page = ?", (name,))
            _record(conn, name, {"checked_at": stamps.stamp(now), "gone": True})
        return ()
    listing = parse_listing_page(resp.text, url=url)
    _store(conn, name, listing, validators, now)
    _artist_pages_cached(conn, client, listing.artists)
    on_read()
    return listing.pages


def _store(conn: sqlite3.Connection, name: str, listing: Listing, validators: Mapping[str, str | None],
           now: datetime) -> None:
    """A listing page's artists and its record, in one transaction."""
    with savepoint(conn, "lacuerda_index_page"):
        store_artists(conn, name, listing.artists)
        _record(conn, name, {**validators, "checked_at": stamps.stamp(now), "rows": len(listing.artists),
                             "pages": list(listing.pages), "total": listing.total})


def _artist_pages_cached(conn: sqlite3.Connection, client: Client, artists: Iterable[LCArtist]) -> None:
    """The songs of the listed artists whose page the HTTP cache holds and the index doesn't: no request."""
    has_cached = getattr(client, "has_cached", None)  # a PoliteClient's; a test's fake client may have none
    if has_cached is None:
        return
    for artist in artists:
        page = f"{artist.slug}/"
        if conn.execute("SELECT 1 FROM lacuerda_index WHERE page = ? LIMIT 1", (page,)).fetchone():
            continue
        url = artist_url(artist.slug)
        if has_cached(url, accept=(200,)):
            store_artist_page(conn, artist.slug, client.get(url, accept=_ACCEPT).text)


def _record(conn: sqlite3.Connection, name: str, entry: Mapping[str, Any]) -> None:
    indexed = pages(conn)
    indexed[name] = dict(entry)
    kv_set_json(conn, PAGES_KEY, indexed)


def _forget(conn: sqlite3.Connection, name: str) -> None:
    """A listing page its letter no longer lists: its artists go, and its record."""
    with savepoint(conn, "lacuerda_index_forget"):
        conn.execute("DELETE FROM lacuerda_index WHERE page = ?", (name,))
        indexed = pages(conn)
        indexed.pop(name, None)
        kv_set_json(conn, PAGES_KEY, indexed)


def _letter(name: str) -> str:
    """The letter of a listing page's path: ``tabs/e/index0.html`` is e's."""
    parts = name.split("/")
    return parts[1] if len(parts) == 3 and parts[0] == "tabs" else ""


def _validators(headers: Mapping[str, str]) -> dict[str, str | None]:
    lower = {k.lower(): v for k, v in headers.items()}
    return {"etag": lower.get("etag"), "last_modified": lower.get("last-modified")}


def _validators_of(entry: Mapping[str, Any]) -> dict[str, str | None]:
    return {"etag": entry.get("etag"), "last_modified": entry.get("last_modified")}


# --- searching ------------------------------------------------------------------------------


@dataclass(frozen=True)
class LaCuerdaHit:
    """An artist or a song of LaCuerda's that the query matches, from the local index.

    ``artist`` is the name LaCuerda writes, ``artist_slug`` their page's slug; ``url`` is the
    artist's page, or the song's own (which lists its versions). ``score`` is 0–100, and
    ``via`` the reading of the query that gave it, as search.py's hits have them: the query as
    the song's "title", its "artist", or "both" (for an artist's hit, their name among other
    words of the query, which may be a title the index doesn't hold). An artist's hit counts
    its ``songs`` (as the listing does) and holds its ``top`` songs the index has: the most
    popular with a Letra y Acordes version. A song's hit has its ``title``, its lcd letters
    (``versions``, one per version) and its best Letra y Acordes version (``acordes``, 0 for
    none), whose page is ``sheet_url``. ``part`` is True for an artist whose name holds the query's words as
    words of its own among others ("sabina" of Joaquín Sabina), never letters inside a word.
    """

    artist: str
    artist_slug: str
    artist_key: str
    url: str
    score: float
    via: str = "artist"
    title: str = ""
    song_slug: str = ""
    title_key: str = ""
    songs: int = 0
    versions: str = ""
    acordes: int = 0
    top: tuple[LaCuerdaHit, ...] = ()
    source: str = "lacuerda"
    part: bool = False

    @property
    def kind(self) -> str:
        """"song" or "artist"."""
        return "song" if self.song_slug else "artist"

    @property
    def sheet_url(self) -> str | None:
        """The page of the song's best Letra y Acordes version, None for an artist or a song with none."""
        return version_url(self.artist_slug, self.song_slug, self.acordes) if self.song_slug and self.acordes else None


@dataclass(frozen=True)
class LaCuerdaFound:
    """What ``find`` answers: the artists, best first, then the songs."""

    artists: tuple[LaCuerdaHit, ...] = ()
    songs: tuple[LaCuerdaHit, ...] = ()


def find(conn: sqlite3.Connection, query: str, *, artists: int = ARTIST_ROWS,
         songs: int = SONG_ROWS) -> LaCuerdaFound:
    """LaCuerda's artists and songs the index holds that match ``query``, best first.

    Ties go to the artist whose name holds the query's words as words of its own ("andres" of Andrés
    Calamaro before Andresito's, ``LaCuerdaHit.part``), unless more than ``WORD_ARTISTS`` names, and more
    than a ``WORD_SHARE``th of the artists listed, do (as Ultimate Guitar's index counts a word in more than
    300 of its 148,705 names common): "band" is no word of Banda el Limón's, and their 184 songs still come
    before the Quartet de Baño Band's 44, a common word's whole words scoring as letters inside a word do. A word
    of a name at the query's start or end names that artist (``WORD_NAMED``) only where ``_word_names`` says so,
    and never beside an artist the query names whole. Then to the one with more songs; and to the song with a
    Letra y Acordes version, then with more versions. A query of fewer than three letters (two Chinese characters)
    finds nothing. Reads only the tables (Ultimate Guitar's index too, for a word of a name): nothing is asked of
    LaCuerda.
    """
    queries = _queries(query)
    patterns, extra = _patterns(query)
    if not queries or not patterns:
        return LaCuerdaFound()
    named: dict[str, tuple[float, str, _Row]] = {}
    by_name: dict[str, tuple[float, _Row]] = {}  # artists only their songs' rows matched
    by_word: dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]] = {}  # named by a word (WORD_NAMED): word, rest
    otherwise: dict[str, float] = {}  # what those score but for the word
    found: list[tuple[float, str, _Row]] = []
    for row in _rows_like(conn, patterns, extra):
        names = row.artist_key.replace("-", " ")
        if not row.title:
            score, via, word = max((q.artist(names) for q in queries), key=lambda r: r[0])
            if score >= MIN_SCORE:
                named[row.artist_slug] = (score, via, row)
                if word is not None:
                    by_word.setdefault(word[:2], set()).add(row.artist_slug)
                    otherwise[row.artist_slug] = word[2]
            continue
        score, via = _reading(q.readings(names, row.title_key.replace("-", " ")) for q in queries)
        if score < MIN_SCORE:
            continue
        if via == "artist":
            if score > by_name.get(row.artist_slug, (0.0, row))[0]:
                by_name[row.artist_slug] = (score, row)
        else:
            found.append((score, via, row))
    # Beside an artist the query names whole, its other words are a title: a word of them names no one.
    whole = any(via == "both" and score >= NAMED for score, via, _ in named.values())
    for (_, rest), slugs in by_word.items():
        for slug in slugs:
            row = named[slug][2]
            if whole or not _word_names(conn, row, rest, len(slugs) <= WORD_FEW):
                if otherwise[slug] >= MIN_SCORE:  # what the query scores against their name but for the word
                    named[slug] = (otherwise[slug], "artist", row)
                else:
                    named.pop(slug)
    for slug, (score, row) in by_name.items():
        if slug not in named or named[slug][0] < score:
            own = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM lacuerda_index WHERE path = ?",
                               (f"{slug}/",)).fetchone()
            named[slug] = (score, "artist", _Row(*own) if own is not None else row)
    parts = {slug for slug, (_, _, row) in named.items()
             if any(q.part_of(row.artist_key.replace("-", " ")) for q in queries)}
    if len(parts) > WORD_ARTISTS and len(parts) * WORD_SHARE > _listed_artists(conn):
        # A common word ("band", "los"): no name holds it as its own more than another, so its whole words count
        # as letters inside one do ("band" of Banda el Limón), and the artists' songs alone order them.
        for slug in parts:
            score, via, row = named[slug]
            if score <= 100 * PARTIAL_SCALE:
                named[slug] = (score * INSIDE_SCALE / PARTIAL_SCALE, via, row)
        parts = set()
    ranked = sorted(named.values(), key=lambda s: (-s[0], s[2].artist_slug not in parts, -_artist_songs(conn, s[2]),
                                                   s[2].artist.casefold(), s[2].artist_slug))
    found.sort(key=lambda s: (-s[0], s[2].acordes == 0, -len(s[2].versions), s[2].artist.casefold(),
                              s[2].title.casefold(), s[2].path))
    return LaCuerdaFound(
        artists=tuple(_artist_hit(conn, row, score, via, row.artist_slug in parts)
                      for score, via, row in ranked[:max(artists, 0)]),
        songs=tuple(_song_hit(row, score, via) for score, via, row in found[:max(songs, 0)]),
    )


def sheet_page(conn: sqlite3.Connection, artists: Sequence[str], title: str) -> str | None:
    """The page of the best Letra y Acordes version the index holds of a song, by its artists' names (each of
    their forms, ``name_forms``) and its title, compared by their keys: the sheet a lookup would keep with
    ``--lacuerda``; None when the index holds none. It reads the table alone, for the requests page, which
    offers it for a song Ultimate Guitar has no chords for (web/outcome.py)."""
    keys = [k for k in dict.fromkeys(name_key(form) for name in artists for form in (name, *name_forms(name))) if k]
    song = title_key(title)
    if not keys or not song:
        return None
    row = conn.execute(
        f"SELECT artist_slug, path, acordes FROM lacuerda_index WHERE artist_key IN ({', '.join('?' for _ in keys)}) "
        "AND title_key = ? AND acordes > 0 ORDER BY popular IS NULL, popular, path LIMIT 1", (*keys, song),
    ).fetchone()
    return version_url(row[0], row[1].partition("/")[2], row[2]) if row is not None else None


def artist_songs(conn: sqlite3.Connection, slug: str, *, limit: int | None = None,
                 acordes: bool = False) -> list[LaCuerdaHit]:
    """The songs the index holds of an artist, most popular first (LaCuerda's own order), then by
    title; with ``acordes``, only those with a Letra y Acordes version."""
    where = " AND acordes > 0" if acordes else ""
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM lacuerda_index WHERE artist_slug = ? AND title != ''{where} "
        "ORDER BY popular IS NULL, popular, title COLLATE NOCASE, path LIMIT ?", (slug, -1 if limit is None else limit))
    return [_song_hit(_Row(*r), 0.0, "artist") for r in rows]


class _Row:
    __slots__ = _COLUMNS

    def __init__(self, *values: Any):
        for name, value in zip(_COLUMNS, values, strict=True):
            setattr(self, name, value)


def _listed_artists(conn: sqlite3.Connection) -> int:
    """How many artists LaCuerda's listings the index holds name."""
    return conn.execute("SELECT COUNT(*) FROM lacuerda_index WHERE title = ''").fetchone()[0]


def _artist_songs(conn: sqlite3.Connection, row: _Row) -> int:
    """An artist's songs: as their listing counts them, else as many as the index holds."""
    if not row.title:
        return row.songs
    return conn.execute("SELECT COUNT(*) FROM lacuerda_index WHERE artist_slug = ? AND title != ''",
                        (row.artist_slug,)).fetchone()[0]


def _artist_hit(conn: sqlite3.Connection, row: _Row, score: float, via: str, part: bool = False) -> LaCuerdaHit:
    return LaCuerdaHit(
        artist=row.artist, artist_slug=row.artist_slug, artist_key=row.artist_key, url=artist_url(row.artist_slug),
        score=round(score, 1), via=via, songs=_artist_songs(conn, row),
        top=tuple(artist_songs(conn, row.artist_slug, limit=TOP_SONGS, acordes=True)), part=part,
    )


def _song_hit(row: _Row, score: float, via: str) -> LaCuerdaHit:
    song = row.path.partition("/")[2]
    return LaCuerdaHit(
        artist=row.artist, artist_slug=row.artist_slug, artist_key=row.artist_key,
        url=song_url(row.artist_slug, song), score=round(score, 1), via=via, title=row.title, song_slug=song,
        title_key=row.title_key, versions=row.versions, acordes=row.acordes,
    )


def _rows_like(conn: sqlite3.Connection, patterns: Sequence[str], extra: Sequence[str]) -> Iterator[_Row]:
    """The rows whose keys hold one of ``patterns``; those holding more of them and of ``extra`` first,
    then artists, then the shortest keys: at most ``ROWS_READ``."""
    def holds(n: int) -> str:
        # The keys hyphenated, and written together: "banma" is in "ban-ma-ban-ma", a Chinese name's pinyin.
        return (f"(artist_key LIKE ?{n} OR title_key LIKE ?{n} OR replace(artist_key, '-', '') LIKE ?{n} "
                f"OR replace(title_key, '-', '') LIKE ?{n})")

    every = [*patterns, *extra]
    where = " OR ".join(holds(n) for n in range(1, len(patterns) + 1))
    held = " + ".join(holds(n) for n in range(1, len(every) + 1))
    sql = (f"SELECT {', '.join(_COLUMNS)} FROM lacuerda_index WHERE {where} "
           f"ORDER BY {held} DESC, title != '', length(artist_key) + length(title_key), path LIMIT {ROWS_READ}")
    for values in conn.execute(sql, every):
        yield _Row(*values)


# --- words and scores, as search.py has them ------------------------------------------------

def _forms(text: str) -> list[str]:
    """The query as words: as written, as an identity key's title folds it (number words as digits) and
    as an artist's (a leading article and "y" dropped); Chinese in pinyin too."""
    forms = [" ".join(name_words(text)),
             title_key(text).replace("-", " "),
             name_key(text).replace("-", " ")]
    if has_han(text):
        forms.append(" ".join(fold(romanize(t)) if has_han(t) else t for t in name_words(text)))
    return [f for f in dict.fromkeys(forms) if f]


def _queries(text: str) -> list[_Query]:
    """The query's forms, ready to be scored. A Chinese query's forms all carry each Chinese word's pinyin
    (``_Query.runs``): the pinyin the keys make of it counts only as whole words of a name."""
    plain = "".join(name_words(text))
    if len(plain) < (2 if has_han(plain) else 3):
        return []
    runs = tuple("".join(fold(s) for s in romanize(t).split()) for t in name_words(text) if has_han(t))
    return [_Query(form, runs) for form in _forms(text)]


def _patterns(text: str) -> tuple[list[str], list[str]]:
    """The ``LIKE`` patterns the prefilter needs a row to hold one of (the query's two longest words), and
    up to two more that put the rows holding them first. Chinese words are their pinyin syllables in order;
    a name of initials is its hyphenated and its compact key."""
    found: list[tuple[int, str]] = []
    # A Chinese query's pinyin forms are its syllables apart: only the form that still holds the characters
    # makes patterns, so a word is its syllables in order and never one pattern per syllable.
    forms = [" ".join(name_words(text))] if has_han(text) else _forms(text)
    for form in forms:
        for token in form.split():
            if has_han(token):
                syllables = romanize(token).split()
                letters = sum(len(s) for s in syllables)
                if letters >= 4:
                    found.append((letters, "%" + "%".join(fold(s) for s in syllables) + "%"))
            elif len(token) >= 2:
                found.append((len(token), f"%{token}%"))
    long = [(n, p) for n, p in found if n >= 3]
    if not long:  # names made of initials
        latin = [t for t in name_words(text) if not has_han(t)]
        key = "-".join(latin)
        if len("".join(latin)) >= 2:
            long = [(len(key), f"%{key}%"), (len(key), f"%{key.replace('-', '')}%")]
    ordered = list(dict.fromkeys(p for _, p in sorted(long, key=lambda f: -f[0])))
    patterns = ordered[:MAX_PATTERNS]
    rest = [p for _, p in sorted(found, key=lambda f: -f[0]) if p not in patterns]
    return patterns, list(dict.fromkeys(rest))[:MAX_EXTRA]


class _Query:
    """One form of a query, ready to be scored against many rows (space-separated words)."""

    def __init__(self, text: str, runs: tuple[str, ...] = ()):
        self.text = text
        self.compact = text.replace(" ", "")
        self.runs = runs

    def holds(self, *names: str) -> bool:
        """Whether each Chinese word's pinyin is a whole run of the words of one of ``names`` (as search.py's
        ``_Query.holds``). True for a query with no Chinese."""
        words = [name.split() for name in names]
        return all(any(holds_run(w, run) for w in words) for run in self.runs)

    def part_of(self, artist: str) -> bool:
        """Whether the query's words are words of an artist's name among others (space-separated words), each
        Chinese word's pinyin a whole run of them: never letters inside a word, nor the whole name."""
        words, name = self.text.split(), artist.split()
        return len(words) < len(name) and all(w in name for w in words) and self.holds(artist)

    def artist(self, artist: str) -> tuple[float, str, tuple[tuple[str, ...], tuple[str, ...], float] | None]:
        """How well the query names an artist, the reading, and, when it names them only by a word of their name,
        that word (a run of the query's words), the rest of the query and the score the name has otherwise (for
        ``find`` to fall back on): 100 for the whole name, at most 90 for a
        part of it in whole words or its start as typed so far, at most 85 for letters inside a word (``_scale``)
        ("artist"); ``NAMED`` for the whole name, as words of its own, among other words of the query, which may be
        a title the index doesn't hold ("both"); ``WORD_NAMED`` for words of the name, fewer than all, as the
        query's first or last words among others ("both": "bunbury lady blue", Enrique Bunbury), which ``find``
        keeps only for an artist that word may name (``_word_names``)."""
        q, qc, a = self.text, self.compact, artist.replace(" ", "")
        words, name = q.split(), artist.split()
        best = 0.0
        if self.holds(artist):
            best = max(fuzz.ratio(q, artist), fuzz.ratio(qc, a))
            for needle, hay, together in ((q, artist, False), (qc, a, True)):
                if len(needle) < len(hay):
                    part = fuzz.partial_ratio_alignment(needle, hay)
                    best = max(best, self._scale(part, name, together, (name,)) * part.score)
        if best < NAMED and 0 < len(name) < len(words) and any(
                words[i:i + len(name)] == name for i in range(len(words) - len(name) + 1)):
            return NAMED, "both", None
        if best < WORD_NAMED and not self.runs:
            word = _word_of(words, name)
            if word is not None:
                return WORD_NAMED, "both", (*word, best)
        return best, "artist", None

    def _scale(self, part: Any, words: Sequence[str], together: bool, starts: Sequence[Sequence[str]]) -> float:
        """What a partial match counts for: ``PARTIAL_SCALE`` when it is whole words of ``words`` (spaced, or
        ``together``), or the query is the start of one of ``starts`` as typed so far (``_typed_start``);
        ``INSIDE_SCALE`` for letters inside a word; a Chinese query's pinyin, ``PINYIN_PARTIAL_SCALE``."""
        if self.runs:
            return PINYIN_PARTIAL_SCALE
        begins, ends = _bounds(words, together)
        if (part.dest_start in begins and part.dest_end in ends) or any(
                _typed_start(self.text.split(), w) for w in starts):
            return PARTIAL_SCALE
        return INSIDE_SCALE

    def readings(self, artist: str, title: str) -> tuple[float, float, float]:
        """How well the query names a song, by reading, in ``READINGS``' order: as its title, as both its
        names (their words in any order), as its artist. A part of the names counts for the title or the
        artist when it lies within that name, else for both."""
        if self.runs and not self.holds(artist, title):
            return (0.0, 0.0, 0.0)
        q, qc = self.text, self.compact
        a, t = artist.replace(" ", ""), title.replace(" ", "")
        full = f"{artist} {title}"
        words = full.split()
        by = {"title": max(fuzz.ratio(q, title), fuzz.ratio(qc, t)),
              "both": max(fuzz.token_sort_ratio(q, full), fuzz.ratio(qc, a + t)),
              "artist": max(fuzz.ratio(q, artist), fuzz.ratio(qc, a))}
        # Spaced, the title starts after the artist and a space; compact, right after the artist.
        for needle, names, edge, gap in ((q, full, len(artist), 1), (qc, a + t, len(a), 0)):
            if len(needle) < len(names):
                part = fuzz.partial_ratio_alignment(needle, names)
                where = ("title" if part.dest_start >= edge else
                         "artist" if part.dest_end <= edge + gap else "both")
                scale = self._scale(part, words, gap == 0, (title.split(), artist.split(), words))
                by[where] = max(by[where], scale * part.score)
        return by["title"], by["both"], by["artist"]


def _bounds(words: Sequence[str], together: bool) -> tuple[set[int], set[int]]:
    """Where each word starts, and where each ends, in ``words`` written spaced or ``together``."""
    begins, ends, at = set(), set(), 0
    for word in words:
        begins.add(at)
        at += len(word)
        ends.add(at)
        at += 0 if together else 1
    return begins, ends


def _typed_start(query: Sequence[str], name: Sequence[str]) -> bool:
    """Whether the query is the start of a name as typed so far: two words or more, each but the last a word of
    the name's start, the last the start of the next ("joaquin sab"). One word alone is letters of a word."""
    k = len(query)
    return 2 <= k <= len(name) and list(query[:-1]) == list(name[:k - 1]) and name[k - 1].startswith(query[-1])


def _word_of(words: Sequence[str], name: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """The longest run of the query's first or last words, fewer than all, that is a run of a name's words, fewer
    than all, with a word of ``CLOSE_LETTERS`` letters at least, and the query's other words: the query may name
    the artist by a word of theirs, the rest being a title ("bunbury lady blue": "bunbury" of Enrique Bunbury, and
    "lady blue"). None for none."""
    for n in range(min(len(words), len(name)) - 1, 0, -1):
        for run, rest in ((words[:n], words[n:]), (words[-n:], words[:-n])):
            if any(len(w) >= CLOSE_LETTERS for w in run) and any(
                    list(name[i:i + n]) == list(run) for i in range(len(name) - n + 1)):
                return tuple(run), tuple(rest)
    return None


def _word_names(conn: sqlite3.Connection, row: _Row, rest: Sequence[str], few: bool) -> bool:
    """Whether a word of an artist's name at the query's start or end names them (``WORD_NAMED``): when the rest of
    the query is a title an index knows of theirs exactly (LaCuerda's, or Ultimate Guitar's under their key: "lady
    blue" of Enrique Bunbury's), or when they are well known (``WORD_KNOWN`` songs) and the word is in ``few``
    names ("bunbury"). A word of titles ("vida", "nada", "corazon") is in more names than that, or in an unknown
    artist's: none of them is named so."""
    text = " ".join(rest)
    if text and (conn.execute("SELECT 1 FROM lacuerda_index WHERE artist_slug = ? AND title_key = ? LIMIT 1",
                              (row.artist_slug, title_key(text))).fetchone() or
                 conn.execute("SELECT 1 FROM ug_index WHERE artist_key = ? AND song_key = ? LIMIT 1",
                              (row.artist_key, slug_key(text))).fetchone()):
        return True
    return few and _artist_songs(conn, row) >= WORD_KNOWN


def _reading(scores: Iterable[tuple[float, float, float]]) -> tuple[float, str]:
    """The best of several (title, both, artist) readings, and which it is; a tie goes to the title, then both."""
    best, via = 0.0, READINGS[0]
    for triple in scores:
        for name, score in zip(READINGS, triple):
            if score > best:
                best, via = score, name
    return best, via
