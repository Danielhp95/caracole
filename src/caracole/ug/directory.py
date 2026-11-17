"""Ultimate Guitar's artist directory: every artist UG's letter listings name, and every bare artist's page read.

UG's sitemaps list a tenth of its tabs by a bare ``/tab/{id}``, every tab of an artist whose name has a letter outside
ASCII among them (宋冬野, Joaquín Sabina, Кино), and no sitemap names an artist. An artist page's address needs UG's id
(``/artist/634073`` is 宋冬野's), which UG's letter listings give (ug/bands.py). So caracole reads them whole into
``ug_directory`` (db.py, schema 16), and then the page of every artist they name by a bare address, whose tabs only
that page names (ug/artist_tabs.py): a search finds such an artist by name, and once their page is read, their songs
by title; the nightly fetch finds a wanted song's artist page with no ``[artist_url]`` (ug/fetch.py
``_known_artist_page``). The design is docs/superpowers/specs/2026-11-17-ug-artist-directory-design.md, its owner's
decisions of 2026-11-17 above the rest.

**The pace** is the owner's choice of 2026-11-17, in their words "Ignore the politeness for this": the whole read in
about an hour, every listing page (about 3,500) and every bare artist's page (about 10,000–17,000), some 20,000
requests at about five a second, several in flight at once (``config.DirectoryPolicy``: ``[ug_directory]``'s
``concurrency``, ``delay`` and ``budget``, of its own beside UG's 60 a night). That departs from one request at a time
per provider, the bulk pace and UG's budget, for this pass alone. Everything else holds, the client's
(``http.ParallelClient``: PoliteClient's rules, none copied): robots.txt (``/bands/`` and ``/artist/`` alone),
caracole's own user agent, every 200 and 404 cached, each request an event of provider ``ug``, a block that stops
every worker at once (the caller records it: one cooldown for ``ug``, so the fetch and lookups cool too, and one
alert), and nothing retried around it. Workers fetch; this thread parses, stores and records, on its one connection.
Between two batches of requests (``BATCH`` a worker), with none in flight, a lookup that waits has caracole's lock
(``between``, ``_common.hand_over``), so a lookup never waits behind the hour.

**The listings** (``LETTERS``, 27): each letter's first ``FIRST_PAGES`` pages first, then the letters one by one, so
that the first requests give every letter's most popular artists. Each page is stored in one savepoint, its artists
upserted (``seen_at`` moved on, their place kept for namesakes), its letter's record moved on (kv
``ug:directory:letters``: its pages, its artists as UG counts them, the round's start, its next page, and when its last
whole round ended). The page's own ``page_count`` marks the letter's end. A listing never removes an artist: an
absence is no miss, as the order moves between nights and the count is approximate; only a 404 from the artist's own
page removes them. A letter is read again ``REFRESH`` (30 days) after its last whole read, each page cached until
then: a round asks again only for a page cached before it began. A page cut short, or one that won't parse, or a 404,
is an error, never a page of no artist: the letter's round stops there for the pass and goes on from that page the
next time (a cached copy that fails is asked for once more first, as ``http.read_once_more`` does).

**The bare artists' pages**, once no listing is left to read in the pass: each artist the directory names by a bare
address whose page caracole hasn't read, or whose row's ``tabs`` or ``updated_at`` moved since it did, never within
``REFRESH`` of the last read, most tabs first. Each page is read by ug/fetch.py's rules (``read_artist_page``: the
chords list, then the tabs list, ``PAGES_PER_KIND`` pages of 100 a kind at most, 30 days from the cache, every page kept
for searches, a list read whole kept whole), its requests made in parallel a batch at a time: the read runs here with a
client that sends nothing (``_Planned``), whose misses the workers fetch, then runs again, until every artist of the
batch is read, so no rule of the fetch's is written twice. Only names are read, never a tab page. A page UG answers 404
for removes the artist (``artist_tabs.forget``, and their row).

``caracole ug --directory`` (commands/ug.py) makes a pass, and the nightly run's ``ug-directory`` step one after the
index refresh (pipeline.py), each with the directory's budget. ``index_state`` says how far it has got, for ``caracole
index stats``, the Sites tab and the to-do page, with no request. ``ensure_current_keys`` makes every row's key and
forms again from its name after a change to caracole's keys (``normalize.KEY_VERSION``), with no request.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from caracole import normalize, stamps
from caracole.db import kv_get, kv_get_json, kv_set, kv_set_json, savepoint
from caracole.http import (
    BudgetExhausted,
    ProviderBlocked,
    ProviderError,
    ProviderUnavailable,
    Response,
    stale,
)
from caracole.normalize import compact, name_forms, slug_key
from caracole.ug.bands import LETTERS, PER_PAGE, ListingPage, ListingParseError, listing_url, parse_listing
from caracole.ug_urls import ARTIST_HOST

log = logging.getLogger(__name__)

PROVIDER = "ug"
LETTERS_KEY = "ug:directory:letters"  # {letter: {pages, artists, started, next, done}}: each listing's rounds
KEYS_KEY = "ug:directory:keys"  # the normalize.KEY_VERSION the keys were made with
REFRESH = timedelta(days=30)  # a letter read again this long after its last whole read; a bare page never sooner
FIRST_PAGES = 10  # each letter's first pages, read before any letter's rest
BATCH = 8  # requests a worker between two looks for a waiting lookup
PAGES_PER_KIND = 100  # an artist page's list pages a kind at most, in a pass (100 tabs a page)
_ACCEPT = (200, 404)
_SLACK = timedelta(minutes=1)
_COLUMNS = ("artist_id", "name", "slug", "letter", "place", "tabs", "updated_at", "artist_key", "forms", "seen_at")


# --- what the directory holds --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectoryArtist:
    """One artist of the directory: UG's id, their name as UG writes it, their page's slug ("" for a bare page), the
    listing that names them, their place there when last seen, the tabs UG counts of every type, when one last changed,
    the key they are filed under and when a listing last showed them."""

    artist_id: int
    name: str
    slug: str
    letter: str
    place: int
    tabs: int
    updated_at: str
    artist_key: str
    seen_at: str

    @property
    def url(self) -> str:
        """Their page's address, as ``ug_urls.artist_page_address`` writes it."""
        return page_address(self.artist_id, self.slug)

    @property
    def bare(self) -> bool:
        return not self.slug


_READ = ("artist_id", "name", "slug", "letter", "place", "tabs", "updated_at", "artist_key", "seen_at")
SELECT = f"SELECT {', '.join(_READ)} FROM ug_directory"


def _artist(row: Sequence[Any]) -> DirectoryArtist:
    return DirectoryArtist(*row)


def page_address(artist_id: int, slug: str) -> str:
    """An artist page's address from UG's id and the slug of it: ``/artist/{slug}_{id}``, or ``/artist/{id}``."""
    return f"{ARTIST_HOST}/artist/{slug + '_' if slug else ''}{artist_id}"


def forms_text(name: str, slug: str) -> str:
    """A row's forms, for the prefilter's ``LIKE``: its name's (``normalize.name_forms``: "Song Dongye (宋冬野)" is
    both its names, Chinese in pinyin too) and its slug's key, each hyphenated and written together, once each."""
    every = [*name_forms(name), *([slug_key(slug.replace("_", " "))] if slug else [])]
    every = [f for f in every if f]
    return " ".join(dict.fromkeys([*every, *(f.replace("-", "") for f in every)]))


def artist_key_of(conn: sqlite3.Connection, artist_id: int, name: str, slug: str) -> str:
    """The key an artist is filed under, as ug/artist_tabs.py files a page's tabs: the index's key where their slug is
    one of its keys (``simon_garfunkel`` is ``simon-garfunkel``), else their name's slug key ("Song Dongye (宋冬野)"
    is ``song-dongye-宋冬野``), so that the directory, ``ug_index`` and ``ug_artist_tabs`` meet on one key."""
    if slug:
        key = slug_key(slug.replace("_", " "))
        if key and conn.execute("SELECT 1 FROM ug_index WHERE artist_key = ? LIMIT 1", (key,)).fetchone():
            return key
    return slug_key(name) or (slug_key(slug.replace("_", " ")) if slug else "") or str(artist_id)


def ensure_current_keys(conn: sqlite3.Connection) -> int:
    """Make every row's key and forms again from its name after a change to caracole's keys, once; no request.
    Returns how many rows changed."""
    version = str(normalize.KEY_VERSION)
    if kv_get(conn, KEYS_KEY) == version:
        return 0
    changed = 0
    with savepoint(conn, "ug_directory_keys"):
        for artist_id, name, slug, key, forms in conn.execute(
                "SELECT artist_id, name, slug, artist_key, forms FROM ug_directory ORDER BY artist_id").fetchall():
            new = (artist_key_of(conn, artist_id, name, slug), forms_text(name, slug))
            if new != (key, forms):
                conn.execute("UPDATE ug_directory SET artist_key = ?, forms = ? WHERE artist_id = ?",
                             (*new, artist_id))
                changed += 1
        kv_set(conn, KEYS_KEY, version)
    return changed


@dataclass(frozen=True)
class LetterState:
    """A listing's round as kv ``ug:directory:letters`` holds it: its pages and artists as UG last counted them, when
    its round began (``started``), the next page to read (``next``), and when its last whole round ended (``done``,
    None before one did)."""

    letter: str
    pages: int = 0
    artists: int = 0
    started: str | None = None
    next: int = 1
    done: str | None = None

    @property
    def reading(self) -> bool:
        """A round begun and not ended yet."""
        started, done = stamps.parse(self.started), stamps.parse(self.done)
        return started is not None and (done is None or done < started)

    def as_json(self) -> dict[str, Any]:
        return {"pages": self.pages, "artists": self.artists, "started": self.started, "next": self.next,
                "done": self.done}


def _int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def letters(conn: sqlite3.Connection) -> dict[str, LetterState]:
    """Every listing's round, in ``LETTERS``' order (a letter never read: its first round not begun)."""
    held = kv_get_json(conn, LETTERS_KEY)
    held = held if isinstance(held, dict) else {}
    out = {}
    for letter in LETTERS:
        r = held.get(letter) if isinstance(held.get(letter), dict) else {}
        out[letter] = LetterState(letter, max(_int(r.get("pages"), 0), 0), max(_int(r.get("artists"), 0), 0),
                                  _text(r.get("started")), max(_int(r.get("next"), 1), 1), _text(r.get("done")))
    return out


def _save_letter(conn: sqlite3.Connection, state: LetterState) -> None:
    held = kv_get_json(conn, LETTERS_KEY)
    held = held if isinstance(held, dict) else {}
    held[state.letter] = state.as_json()
    kv_set_json(conn, LETTERS_KEY, {k: held[k] for k in sorted(held)})


@dataclass(frozen=True)
class DirectoryState:
    """How far the directory has got: each listing's round (``letters``), the artists it holds (``artists``) and of
    them those UG addresses by a bare page (``bare``), those of these whose page caracole read whole (``read``), and
    the artists UG's listings count in all (``counted``, approximate)."""

    letters: Mapping[str, LetterState]
    artists: int
    bare: int
    read: int

    @property
    def counted(self) -> int:
        return sum(s.artists for s in self.letters.values())

    @property
    def letters_read(self) -> int:
        """The listings read whole once at least."""
        return sum(s.done is not None for s in self.letters.values())

    @property
    def complete(self) -> bool:
        """Every listing read whole once at least: an artist the directory lacks is on no UG listing."""
        return self.letters_read == len(LETTERS)

    def letter_read(self, letter: str) -> bool:
        state = self.letters.get(letter)
        return state is not None and state.done is not None


def index_state(conn: sqlite3.Connection) -> DirectoryState:
    """The directory's ``DirectoryState``; no request."""
    artists, bare, read = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(slug = ''), 0), COALESCE(SUM(slug = '' AND read_at != ''), 0) "
        "FROM ug_directory").fetchone()
    return DirectoryState(letters(conn), artists, bare, read)


def letter_of(name: str) -> str:
    """The listing UG files a name under: its first letter when it is one of A–Z, else ``0-9`` (a digit, a symbol,
    another script, an accented letter: Кино, Édith Piaf). "The Beatles" is under T."""
    first = name.strip()[:1].lower()
    return first if "a" <= first <= "z" else "0-9"


def artist_page_for(conn: sqlite3.Connection, keys: Sequence[str]) -> str | None:
    """The page of the artist the directory names by one of an artist's ``keys`` (ug/fetch.py ``artist_keys``: a
    song's ``[alias]`` and its names' forms, its name's own key before the forms made of it), or None. Namesakes: the
    first of ``keys`` that names any; then a whole-name match (the key they are filed under, or their name's slug key)
    before one by a part of their name, and of parts the one that is more of the name ("宋冬野" is more of "Song
    Dongye (宋冬野)" than of "Song Dongye (宋冬野) & Friends"); then the most tabs, then the most popular."""
    wanted = list(dict.fromkeys(compact(k) for k in keys if k))
    if not wanted:
        return None
    found: list[tuple[int, float, int, int, int, str]] = []
    seen: set[int] = set()
    for key in wanted:
        pattern = "%" + key.replace("%", "").replace("_", "") + "%"
        for row in conn.execute(f"SELECT {', '.join(_READ)}, forms FROM ug_directory WHERE artist_key = ? OR forms "
                                "LIKE ? ORDER BY artist_id LIMIT 200", (key, pattern)):
            artist = _artist(row[:-1])
            if artist.artist_id in seen:
                continue
            forms = {compact(f) for f in row[-1].split()}
            first = next((n for n, k in enumerate(wanted) if k in forms), None)
            if first is None:
                continue
            seen.add(artist.artist_id)
            own = {compact(artist.artist_key), compact(slug_key(artist.name))}
            whole = max(len(compact(artist.artist_key)), len(compact(slug_key(artist.name))), 1)
            share = 1.0 if wanted[first] in own else min(len(wanted[first]) / whole, 0.99)
            found.append((first, -share, -artist.tabs, artist.place, artist.artist_id, artist.url))
    return min(found)[-1] if found else None


# --- one listing page stored ---------------------------------------------------------------------------------------


def store_page(conn: sqlite3.Connection, page: ListingPage, *, seen_at: str, started: str, now: datetime) -> tuple[int, int]:
    """A listing page's artists upserted (a later sight of an artist moves its row on, an earlier one never), and its
    letter's round, begun at ``started``, moved on past it (its last page ends the round ``now``), in one savepoint.
    Returns the artists stored and those of them new to the directory."""
    ensure_current_keys(conn)
    sql = (f"INSERT INTO ug_directory ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)}) "
           "ON CONFLICT (artist_id) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS[1:])
           + " WHERE excluded.seen_at >= ug_directory.seen_at")
    new = 0
    with savepoint(conn, "ug_directory_page"):
        for n, a in enumerate(page.artists):
            had = conn.execute("SELECT 1 FROM ug_directory WHERE artist_id = ?", (a.artist_id,)).fetchone()
            new += had is None
            updated = stamps.stamp(datetime.fromtimestamp(a.updated, UTC)) if a.updated else ""
            conn.execute(sql, (a.artist_id, a.name, a.slug, page.letter, (page.page - 1) * PER_PAGE + n, a.tabs,
                               updated, artist_key_of(conn, a.artist_id, a.name, a.slug),
                               forms_text(a.name, a.slug), seen_at))
        was = letters(conn)[page.letter]
        _save_letter(conn, LetterState(page.letter, page.pages, page.count, started, page.page + 1,
                                       stamps.stamp(now) if page.last else was.done))
    return len(page.artists), new


def _gone(conn: sqlite3.Connection, artist_id: int, page: str) -> None:
    """UG answered 404 for the artist's own page: their tabs go, their row, and every artist it was learned for
    learns it again."""
    from caracole.ug import artist_tabs
    from caracole.ug.lookup import ARTIST_URL_KV, forget_artist_url

    with savepoint(conn, "ug_directory_gone"):
        for (key,) in conn.execute("SELECT key FROM kv WHERE substr(key, 1, ?) = ? AND value = ? ORDER BY key",
                                   (len(ARTIST_URL_KV), ARTIST_URL_KV, page)).fetchall():
            forget_artist_url(conn, key[len(ARTIST_URL_KV):])
        artist_tabs.forget(conn, page)
        conn.execute("DELETE FROM ug_directory WHERE artist_id = ?", (artist_id,))


# --- the pass ------------------------------------------------------------------------------------------------------


@dataclass
class DirectoryStats:
    """What one ``directory_pass`` did: the listing pages stored, the artists they named and of them those new, the
    letters read whole, the bare artists' pages read whole and those gone (404), the errors, and whether the budget
    or the client's breaker ended it (``budget_exhausted``, ``unavailable``)."""

    pages: int = 0
    artists: int = 0
    new: int = 0
    letters_done: list[str] = field(default_factory=list)
    read: int = 0
    gone: int = 0
    errors: int = 0
    budget_exhausted: bool = False
    unavailable: bool = False

    @property
    def stopped(self) -> bool:
        return self.budget_exhausted or self.unavailable


@dataclass
class _Round:
    state: LetterState
    started: str
    stopped: bool = False  # an error this pass: the round goes on from its next page the next time


def _due_rounds(conn: sqlite3.Connection, now: datetime) -> dict[str, _Round]:
    """The listings to read this pass, each with its round: one begun and not ended goes on, one read whole
    ``REFRESH`` ago or more begins again, one never read begins."""
    due = {}
    for letter, state in letters(conn).items():
        if state.reading and state.started is not None:
            due[letter] = _Round(state, state.started)
        elif stamps.before(state.done, now - REFRESH):
            due[letter] = _Round(replace(state, next=1), stamps.stamp(now))
    return due


def _queue(rounds: Mapping[str, _Round], asked: set[tuple[str, int]]) -> list[tuple[str, int]]:
    """The listing pages still to ask for this pass, in order: every letter's pages up to its ``FIRST_PAGES``-th, then
    the letters one by one, each to its last page as UG last counted them; a letter never read, its first page alone,
    until that page says how many it has."""
    first, rest = [], []
    for letter, r in rounds.items():
        if r.stopped:
            continue
        last = max(r.state.pages, r.state.next) if r.state.pages else r.state.next
        for page in range(r.state.next, last + 1):
            if (letter, page) not in asked:
                (first if page <= FIRST_PAGES else rest).append((letter, page))
    return first + rest


def _batch_size(client: Any) -> int:
    return max(1, int(getattr(client, "workers", 1))) * BATCH


def _between(client: Any) -> None:
    """A lookup that waits has caracole's lock now, with no request in flight (the client's ``between``)."""
    between = getattr(client, "between", None)
    if between is not None:
        between()


def _get_many(client: Any, requests: Sequence[tuple[str, Mapping[str, Any]]]):
    """``client.get_many`` (http.ParallelClient), or the plain client's ``get`` one at a time (a test's fake)."""
    many = getattr(client, "get_many", None)
    if many is not None:
        yield from many(requests)
        return
    for url, kw in requests:
        try:
            yield url, client.get(url, **kw)
        except (ProviderError, BudgetExhausted) as e:
            yield url, e


def _raise_stop(answer: BaseException, stats: DirectoryStats) -> bool:
    """A block raises; a spent budget or a breaker that opened ends the pass (True); any other error is the page's."""
    if isinstance(answer, ProviderBlocked):
        raise answer
    if isinstance(answer, BudgetExhausted):
        stats.budget_exhausted = True
        return True
    if isinstance(answer, ProviderUnavailable):
        stats.unavailable = True
        log.info("Ultimate Guitar is unavailable for the rest of this pass: %s", answer)
        return True
    return False


def directory_pass(conn: sqlite3.Connection, client: Any, now: datetime, *, overrides: Any = None,
                   listings: bool = True, bare: bool = True, library_dir: Path | None = None) -> DirectoryStats:
    """The listings due (``listings``), then the bare artists' pages due (``bare``), until the budget ends it; see the
    module docstring. ``client`` is the pass's (``_common.make_parallel_client``: an ``http.ParallelClient``, its
    ``between`` handing caracole's lock to a waiting lookup). ``ProviderBlocked`` propagates."""
    stats = DirectoryStats()
    now = stamps.utc(now)
    ensure_current_keys(conn)
    if listings:
        _listings(conn, client, now, stats)
    if bare and not stats.stopped:
        _bare_pages(conn, client, now, stats, overrides=overrides, library_dir=library_dir)
    return stats


def _listings(conn: sqlite3.Connection, client: Any, now: datetime, stats: DirectoryStats) -> None:
    rounds = _due_rounds(conn, now)
    asked: set[tuple[str, int]] = set()
    size = _batch_size(client)
    while True:
        batch = _queue(rounds, asked)[:size]
        if not batch:
            return
        asked.update(batch)
        if _listing_batch(conn, client, now, rounds, batch, stats):
            return
        _between(client)


def _max_age(now: datetime, started: str) -> timedelta:
    """How old a cached listing page may be and be this round's: one cached since the round began."""
    began = stamps.parse(started) or now
    return max(now - began, timedelta(0)) + _SLACK


def _listing_batch(conn: sqlite3.Connection, client: Any, now: datetime, rounds: Mapping[str, _Round],
                   batch: Sequence[tuple[str, int]], stats: DirectoryStats) -> bool:
    """One batch of listing pages asked in parallel, then each read and stored in turn, in the order asked; True when
    the pass ends (a spent budget, the breaker). A block raises once the pages answered before it are stored."""
    urls = {listing_url(letter, page): (letter, page) for letter, page in batch}
    answers: dict[str, Response | BaseException] = {}
    block = _ask(client, [(url, {"accept": _ACCEPT, "max_age": _max_age(now, rounds[letter].started)})
                          for url, (letter, _) in urls.items()], answers, stats)
    again = [(url, {"accept": _ACCEPT, "cache": False}) for url, answer in answers.items()
             if isinstance(answer, Response) and answer.from_cache and _unreadable(answer, *urls[url])]
    if again and block is None and not stats.stopped:  # a cached copy that fails: asked for once more
        block = _ask(client, again, answers, stats)
    for url, (letter, page) in urls.items():
        r = rounds[letter]
        answer = answers.get(url)
        if answer is None or r.stopped or page != r.state.next:
            continue  # not asked (the pass ended), or the round stopped at a page before it
        if isinstance(answer, BaseException):
            if not isinstance(answer, (BudgetExhausted, ProviderUnavailable, ProviderBlocked)):
                _letter_error(letter, page, answer, stats)
            r.stopped = True
            continue
        if stale(answer, now, _max_age(now, r.started)):  # served only once the budget was spent: no answer
            stats.budget_exhausted = True
            r.stopped = True
            continue
        try:
            listed = _read(answer, letter, page)
        except ListingParseError as e:
            _letter_error(letter, page, e, stats)
            r.stopped = True
            continue
        stored, new = store_page(conn, listed, seen_at=answer.fetched_at or stamps.stamp(now), started=r.started,
                                 now=now)
        stats.pages += 1
        stats.artists += stored
        stats.new += new
        r.state = letters(conn)[letter]
        if listed.last:
            stats.letters_done.append(letter)
            r.stopped = True  # read whole: nothing more of it this pass
    if block is not None:
        raise block
    return stats.stopped


def _ask(client: Any, requests: Sequence[tuple[str, Mapping[str, Any]]], answers: dict[str, Any],
         stats: DirectoryStats) -> ProviderBlocked | None:
    """``requests`` asked in parallel, each answer into ``answers``; a spent budget or the breaker stops asking (noted
    in ``stats``), and a block too, which is returned for the caller to raise once it has stored what came before."""
    for url, answer in _get_many(client, requests):
        answers[url] = answer
        if isinstance(answer, ProviderBlocked):
            return answer
        if isinstance(answer, BaseException) and _raise_stop(answer, stats):
            return None
    return None


def _read(answer: Response, letter: str, page: int) -> ListingPage:
    if answer.status == 404:
        raise ListingParseError(PROVIDER, answer.url, 404, "UG answers 404 for a page its listing counts")
    return parse_listing(answer.content, letter, page, url=answer.url)


def _unreadable(answer: Response, letter: str, page: int) -> bool:
    try:
        _read(answer, letter, page)
    except ListingParseError:
        return True
    return False


def _letter_error(letter: str, page: int, error: BaseException, stats: DirectoryStats) -> None:
    stats.errors += 1
    log.warning("UG's listing %s, page %s: %s; it is asked for again on the next pass", letter, page, error)


# --- the bare artists' pages ---------------------------------------------------------------------------------------


class _Miss(Exception):
    """A request ``_Planned`` won't send itself: what the workers fetch before the read runs again."""

    def __init__(self, url: str, kwargs: Mapping[str, Any]):
        super().__init__(url)
        self.url = url
        self.kwargs = dict(kwargs)


class _Planned:
    """A client for ug/fetch.py's read of an artist page that sends nothing: what the workers fetched for the batch
    (``answers``, each as a fresh answer is: from UG, or what asking it raised), else the HTTP cache (a copy within
    ``max_age``), else ``_Miss``. The read then runs again with what it missed fetched, so it reads the pages as it
    would have one at a time."""

    def __init__(self, client: Any, now: datetime):
        self.client = client
        self.now = now
        self.answers: dict[str, Response | BaseException] = {}
        self.requests_made = 0

    def get(self, url: str, *, params: Mapping[str, Any] | None = None, cache: bool = True,
            conditional: bool = False, accept: Iterable[int] = (200,), max_age: timedelta | None = None) -> Response:
        accept = tuple(accept)
        if params:
            raise AssertionError("an artist page's lists are asked by their address alone")
        answer = self.answers.get(url)
        if answer is not None:
            if isinstance(answer, BaseException):
                raise answer
            if answer.status in accept:
                return answer
        if cache and answer is None:
            cached = self.client.cached(url, accept=accept) if hasattr(self.client, "cached") else None
            if cached is not None and not (max_age is not None and stale(cached, self.now, max_age)):
                return cached
        raise _Miss(url, {"cache": cache, "accept": accept, "max_age": max_age})


def due_bare(conn: sqlite3.Connection, now: datetime) -> list[DirectoryArtist]:
    """The bare artists whose page is due, most tabs first: never read, or read ``REFRESH`` ago or more and their row's
    ``tabs`` or ``updated_at`` moved since."""
    cutoff = stamps.stamp(stamps.utc(now) - REFRESH)
    rows = conn.execute(f"{SELECT} WHERE slug = '' AND (read_at = '' OR ((tabs != read_tabs OR updated_at != "
                        "read_updated) AND read_at < ?)) ORDER BY tabs DESC, artist_id", (cutoff,)).fetchall()
    return [_artist(r) for r in rows]


def _bare_pages(conn: sqlite3.Connection, client: Any, now: datetime, stats: DirectoryStats, *, overrides: Any,
                library_dir: Path | None) -> None:
    from caracole.config import RankPolicy
    from caracole.overrides import Overrides
    from caracole.ug.fetch import FetchContext

    planner = _Planned(client, now)
    ctx = FetchContext(conn=conn, client=planner, overrides=overrides or Overrides(), rank=RankPolicy(),
                       library_dir=library_dir or Path("."), now=now, artist_pages_per_kind=PAGES_PER_KIND)
    due = due_bare(conn, now)
    size = max(1, int(getattr(client, "workers", 1))) * BATCH // 2  # about two requests an artist
    for start in range(0, len(due), size):
        if _bare_batch(conn, client, ctx, planner, due[start:start + size], stats):
            return
        planner.answers.clear()
        _between(client)


def _bare_batch(conn: sqlite3.Connection, client: Any, ctx: Any, planner: _Planned,
                artists: Sequence[DirectoryArtist], stats: DirectoryStats) -> bool:
    """One batch of bare artists' pages, read as ug/fetch.py reads one, their requests made in parallel; True when
    the pass ends. A block raises once the artists read before it are noted."""
    from caracole.ug.fetch import read_artist_page

    pending = list(artists)
    block: ProviderBlocked | None = None
    while pending:
        missed: dict[str, Mapping[str, Any]] = {}
        waiting = []
        for artist in pending:
            try:
                listing = read_artist_page(ctx, artist.url)
            except _Miss as m:
                missed.setdefault(m.url, m.kwargs)
                waiting.append(artist)
                continue
            except ProviderBlocked as e:  # what came of this batch's requests before the block: its artists noted
                block = block or e
                continue
            except (BudgetExhausted, ProviderUnavailable) as e:
                _raise_stop(e, stats)
                return True
            except ProviderError as e:
                stats.errors += 1
                log.warning("UG's page of %s (%s): %s; it is asked for again on the next pass", artist.name,
                            artist.url, e)
                continue
            _read_whole(conn, artist, listing, ctx.now, stats)
        pending = waiting
        if not missed or block is not None:
            break
        block = _ask(client, list(missed.items()), planner.answers, stats)
        if stats.stopped and block is None:
            return True
    if block is not None:
        raise block
    return False


def _read_whole(conn: sqlite3.Connection, artist: DirectoryArtist, listing: Any, now: datetime,
                stats: DirectoryStats) -> None:
    """What reading an artist's page came to: gone (404), their row too; read whole, noted with the row's tabs and
    update as they were; a list the page cap cut short, left for the next pass."""
    if listing.gone:
        _gone(conn, artist.artist_id, artist.url)
        stats.gone += 1
        return
    if not listing.complete:
        return
    conn.execute("UPDATE ug_directory SET read_at = ?, read_tabs = ?, read_updated = ? WHERE artist_id = ?",
                 (stamps.stamp(now), artist.tabs, artist.updated_at, artist.artist_id))
    stats.read += 1
