"""LaCuerda's artists in a local index, with the songs of the artist pages caracole has read.

LaCuerda has no sitemap. Its listings of every artist, an initial at a time and 100 artists
a page (lacuerda.py), are read into ``lacuerda_index`` (db.py): a row per artist, with the
name LaCuerda writes, the slug of their page, its identity key and the songs the listing
counts. The songs of an artist come from their page, whenever caracole has one, with no
request of their own: each page lacuerda_fetch.py reads (``store_artist_page``), and, as a
listing page is read, the cached pages of its artists. A song's row has its title and key,
its versions, its best Letra y Acordes version and its place in the artist's popularity.

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
possible match: ``NAMED`` (80), by "both", below a strong hit. While a letter's listing isn't
read whole, no artist found is no sign that LaCuerda lacks them: ``unread_letter`` says under
which letter a name would be, for a search to offer reading the page of that name.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
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
)
from caracole.lacuerda import (
    LETTERS,
    LaCuerdaParseError,
    LCArtist,
    LCSong,
    Listing,
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
READINGS = ("title", "both", "artist")  # how a query may name a song; a tie goes to the first
ARTIST_ROWS, SONG_ROWS, TOP_SONGS = 3, 5, 3  # what ``find`` gives by default
ROWS_READ = 2000  # rows the prefilter reads, at most: those that hold more of the query's words first
MAX_PATTERNS, MAX_EXTRA = 3, 2

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
    """What one ``index_pass`` did: the listing pages read into the index (one found unchanged isn't)."""

    pages: int = 0
    errors: int = 0
    budget_exhausted: bool = False


def index_pass(conn: sqlite3.Connection, client: Client, now: datetime) -> IndexStats:
    """Read LaCuerda's listings into the index when due, as the nightly lacuerda step does.

    ``ProviderBlocked`` propagates. A spent budget ends the pass (``budget_exhausted``), and
    so does a client that gives up on LaCuerda for the run; any other provider error counts in
    ``errors``. Either way the index keeps what it holds, and the next run goes on.
    """
    stats = IndexStats()

    def read() -> None:
        stats.pages += 1

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
    Calamaro before Andresito's), then to the one with more songs; and to the song with a Letra y Acordes
    version, then with more versions. A query of fewer than three letters (two Chinese characters) finds
    nothing. Reads only the table: nothing is asked of LaCuerda.
    """
    queries = _queries(query)
    patterns, extra = _patterns(query)
    if not queries or not patterns:
        return LaCuerdaFound()
    named: dict[str, tuple[float, str, _Row]] = {}
    by_name: dict[str, tuple[float, _Row]] = {}  # artists only their songs' rows matched
    found: list[tuple[float, str, _Row]] = []
    for row in _rows_like(conn, patterns, extra):
        names = row.artist_key.replace("-", " ")
        if not row.title:
            score, via = max((q.artist(names) for q in queries), key=lambda r: r[0])
            if score >= MIN_SCORE:
                named[row.artist_slug] = (score, via, row)
            continue
        score, via = _reading(q.readings(names, row.title_key.replace("-", " ")) for q in queries)
        if score < MIN_SCORE:
            continue
        if via == "artist":
            if score > by_name.get(row.artist_slug, (0.0, row))[0]:
                by_name[row.artist_slug] = (score, row)
        else:
            found.append((score, via, row))
    for slug, (score, row) in by_name.items():
        if slug not in named or named[slug][0] < score:
            own = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM lacuerda_index WHERE path = ?",
                               (f"{slug}/",)).fetchone()
            named[slug] = (score, "artist", _Row(*own) if own is not None else row)
    parts = {slug for slug, (_, _, row) in named.items()
             if any(q.part_of(row.artist_key.replace("-", " ")) for q in queries)}
    ranked = sorted(named.values(), key=lambda s: (-s[0], s[2].artist_slug not in parts, -_artist_songs(conn, s[2]),
                                                   s[2].artist.casefold(), s[2].artist_slug))
    found.sort(key=lambda s: (-s[0], s[2].acordes == 0, -len(s[2].versions), s[2].artist.casefold(),
                              s[2].title.casefold(), s[2].path))
    return LaCuerdaFound(
        artists=tuple(_artist_hit(conn, row, score, via, row.artist_slug in parts)
                      for score, via, row in ranked[:max(artists, 0)]),
        songs=tuple(_song_hit(row, score, via) for score, via, row in found[:max(songs, 0)]),
    )


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

    def artist(self, artist: str) -> tuple[float, str]:
        """How well the query names an artist, and the reading: 100 for the whole name, at most 90 for a
        part of it ("artist"); ``NAMED`` for the whole name, as words of its own, among other words of the
        query, which may be a title the index doesn't hold ("both")."""
        q, qc, a = self.text, self.compact, artist.replace(" ", "")
        best = 0.0
        if self.holds(artist):
            scale = PINYIN_PARTIAL_SCALE if self.runs else PARTIAL_SCALE
            best = max(fuzz.ratio(q, artist), fuzz.ratio(qc, a))
            if len(q) < len(artist):
                best = max(best, scale * fuzz.partial_ratio(q, artist))
            if len(qc) < len(a):
                best = max(best, scale * fuzz.partial_ratio(qc, a))
        words, name = q.split(), artist.split()
        if best < NAMED and 0 < len(name) < len(words) and any(
                words[i:i + len(name)] == name for i in range(len(words) - len(name) + 1)):
            return NAMED, "both"
        return best, "artist"

    def readings(self, artist: str, title: str) -> tuple[float, float, float]:
        """How well the query names a song, by reading, in ``READINGS``' order: as its title, as both its
        names (their words in any order), as its artist. A part of the names counts for the title or the
        artist when it lies within that name, else for both."""
        if self.runs and not self.holds(artist, title):
            return (0.0, 0.0, 0.0)
        q, qc = self.text, self.compact
        a, t = artist.replace(" ", ""), title.replace(" ", "")
        full = f"{artist} {title}"
        scale = PINYIN_PARTIAL_SCALE if self.runs else PARTIAL_SCALE
        by = {"title": max(fuzz.ratio(q, title), fuzz.ratio(qc, t)),
              "both": max(fuzz.token_sort_ratio(q, full), fuzz.ratio(qc, a + t)),
              "artist": max(fuzz.ratio(q, artist), fuzz.ratio(qc, a))}
        # Spaced, the title starts after the artist and a space; compact, right after the artist.
        for needle, names, edge, gap in ((q, full, len(artist), 1), (qc, a + t, len(a), 0)):
            if len(needle) < len(names):
                part = fuzz.partial_ratio_alignment(needle, names)
                where = ("title" if part.dest_start >= edge else
                         "artist" if part.dest_end <= edge + gap else "both")
                by[where] = max(by[where], scale * part.score)
        return by["title"], by["both"], by["artist"]


def _reading(scores: Iterable[tuple[float, float, float]]) -> tuple[float, str]:
    """The best of several (title, both, artist) readings, and which it is; a tie goes to the title, then both."""
    best, via = 0.0, READINGS[0]
    for triple in scores:
        for name, score in zip(READINGS, triple):
            if score > best:
                best, via = score, name
    return best, via
