"""A UG link pasted into the library page's search box: what caracole knows of its page, and its page read now.

UG's sitemaps list a tenth of its tabs by a bare ``/tab/{id}`` (every tab of 宋冬野's among them), so the offline index
has no name for them; only an artist page caracole read names them (ug/artist_tabs.py), and caracole reads one only for
a song of the library whose artist page it knows. A search asks no site. A link pasted breaks that circle, the owner's
choice of 2026-11-17 (docs/superpowers/plans/2026-11-17-ug-link.md): it is no query, and a link caracole hasn't read is
read by itself, once, at the lookup pace.

- ``known``: what caracole knows of a link's page, with no request and no lock: the database and the HTTP cache
  alone (``http.CachedAnswers``). Its ``state``: ``found`` (a tab's song is known: its ``ug_index`` row, its
  ``ug_artist_tabs`` row, or its page in the cache; an artist's page read), ``auto`` (not yet, and a read may go now),
  ``cooling`` (UG's cooldown), ``spent`` (the hour's lookups), ``failed`` (this link's read failed within the hour,
  kv ``ug:link-failed``, or its tab page won't parse, kv ``ug:unreadable:<tab id>``), ``other`` (a tab of a type
  caracole keeps nothing of, said with no request where its slug names its type, else once read; or a page robots.txt
  closes) and ``gone`` (UG answered 404 for the page: its cached 404).
- ``read``: the page read now (``caracole ug --link``, commands/ug.py, an interactive lookup): a tab link's page by
  ug/fetch.py's rules for a page (``read_tab_page``), its artist's page learned as the fetch learns it (kv
  ``ug:artist_url:<key>``, under UG's artist name's keys) and read as the fetch reads one (``read_artist_page``: the
  chords list, then the tabs list, every page of them kept for searches); an artist link's lists alone. A budget spent,
  a block or an error after a tab's page is no failure of the link: the tab is known, its artist's page waits.
- ``said``: what the read came to, in the words the command ends with: ``Read: ``, ``Not found: `` (404) or
  ``Not read: `` (nothing changed), as ``caracole harptabs --artist``'s, which caracole serve's request line reads
  (web/status.py).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from caracole import stamps
from caracole.db import kv_get_json, kv_set_json
from caracole.logs import plural
from caracole.ug_urls import SLUGGED, UgLink

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.http import Response
    from caracole.search import IndexHit
    from caracole.songs import Song
    from caracole.ug.fetch import FetchContext, Listing, TabRead
    from caracole.ug.page import UGTabPage

PROVIDER = "ug"
STATES = ("found", "auto", "cooling", "spent", "failed", "other", "gone")
FAILED_KEY = "ug:link-failed"  # {page's address: {"at", "error"}}: the links whose read failed within FAILED_FOR
FAILED_FOR = timedelta(hours=1)
ERROR_CHARS = 200
KEPT = frozenset({"chords", "tabs", "ukulele"})  # the slug tokens of the kinds caracole keeps (ug/sitemap.py)
# A type caracole keeps nothing of, in words: by the token its slug names, and by the type its page names.
_TOKEN_WORDS = {"guitar-pro": "a Guitar Pro file", "power": "a Power Tab file", "official": "an Official tab",
                "bass": "a bass tab", "drums": "a drum tab", "video": "a video lesson", "musescore": "a MuseScore score"}
_TYPE_WORDS = {"pro": "a Guitar Pro file", "power": "a Power Tab file", "official": "an Official tab",
               "bass tabs": "a bass tab", "drum tabs": "a drum tab", "video": "a video lesson"}
KEEPS = "caracole keeps UG's chords, tabs and ukulele chords alone"
_KIND_WORDS = {"chords": "chords", "tabs": "tab", "ukulele": "ukulele chords"}
GONE = "UG answers 404 for it"
ARTIST_SONGS = 50  # an artist's songs a link's answer gives, most tabbed first, as /api/artist gives them at a time
CLOSED = "robots.txt closes it to caracole"


@dataclass(frozen=True)
class Tab:
    """What UG names a tab: its artist and title as UG writes them, caracole's kind (``type``), its version (None
    where only an artist page named it) and its rating and votes (None for a tab nobody voted on)."""

    artist: str
    title: str
    type: str
    version: int | None
    rating: float | None
    votes: int | None

    def as_json(self) -> dict[str, Any]:
        return {"artist": self.artist, "title": self.title, "type": self.type, "version": self.version,
                "rating": self.rating, "votes": self.votes}


@dataclass(frozen=True)
class Known:
    """What caracole knows of a link's page (``known``): its ``state`` and, but ``found`` and ``auto``, why
    (``why``); a tab's names (``tab``), the song its tabs are filed under (``keys``: an artist key and a song key),
    the artist's page (``page``: a tab's, or the link's own), whether and when caracole read it (``read_at``),
    UG's name of the artist (``artist``) and the key an artist page's tabs are filed under (``artist_key``)."""

    link: UgLink
    state: str
    why: str = ""
    tab: Tab | None = None
    keys: tuple[str, str] | None = None
    page: str | None = None
    read_at: str | None = None
    artist: str = ""
    artist_key: str | None = None
    tabs: int = 0  # the tabs caracole holds of the artist page


# --- what caracole knows, with no request ------------------------------------------------------------------


def page_url(conn: sqlite3.Connection, link: UgLink) -> str:
    """The address a link's page is read at: an artist's, as given; a tab's, as given when slugged (UG serves a slugged
    tab only there), else the index's slugged path for its id, else the bare ``/tab/{id}`` (``ug.lookup.tab_url_for``),
    as a tab page pasted under ``[artist_url]`` is read."""
    from urllib.parse import urlsplit

    from caracole.ug.lookup import tab_url_for

    if link.kind != "tab" or link.tab_id is None or SLUGGED.fullmatch(urlsplit(link.url).path):
        return link.url
    return tab_url_for(conn, link.tab_id)


def known(cfg: Config, conn: sqlite3.Connection, link: UgLink, now: datetime) -> Known:
    """What caracole knows of the link's page now, with no request and no lock (the module's docstring)."""
    from caracole.http import CachedAnswers

    cache = CachedAnswers(PROVIDER, cfg.cache_dir)
    said = _tab_known(conn, cache, link, now) if link.kind == "tab" else _artist_known(conn, cache, link)
    if said.state != "auto":
        return said
    state, why = gate(cfg, conn, link, now)
    return Known(**{**said.__dict__, "state": state, "why": why})


def tab_keys(conn: sqlite3.Connection, tab_id: int) -> tuple[str, str] | None:
    """The keys a tab's song is filed under: as an artist page caracole read lists it (``ug_artist_tabs``), else as the
    index does (its song's key without a variant label); None for a tab neither names."""
    from caracole.normalize import split_variant
    from caracole.ug.artist_tabs import listed_tab

    listed = listed_tab(conn, tab_id)
    if listed is not None:
        return listed.artist_key, listed.song_key
    row = conn.execute("SELECT artist_key, song_key FROM ug_index WHERE tab_id = ?", (tab_id,)).fetchone()
    return (row[0], split_variant(row[1])[0]) if row is not None else None


def _read_lately(conn: sqlite3.Connection, page: str, now: datetime) -> bool:
    """Whether caracole read the artist page's lists within ``ug.fetch.ARTIST_PAGE_MAX_AGE`` (30 days): its tabs in
    ``ug_artist_tabs`` read since."""
    from caracole.ug.artist_tabs import page_artist
    from caracole.ug.fetch import ARTIST_PAGE_MAX_AGE

    held = page_artist(conn, page)
    return held is not None and not stamps.before(held[3], stamps.utc(now) - ARTIST_PAGE_MAX_AGE)


def _tab_known(conn: sqlite3.Connection, cache: Any, link: UgLink, now: datetime) -> Known:
    """A tab link's page as caracole knows it. Its song is known (``found``) by an artist page caracole read that
    lists it, by the index, or by its page in the cache, but a cached page that names an artist page caracole hasn't
    read within 30 days is ``auto``: the read takes the page from the cache and reads that artist's lists, so that
    every song of theirs is found by a search."""
    from caracole.http import robots_disallows
    from caracole.normalize import name_forms
    from caracole.ug.artist import artist_page_of
    from caracole.ug.artist_tabs import listed_tab
    from caracole.ug.lookup import learned_artist_url
    from caracole.ug.page import PageParseError, parse_tab_page

    if link.type is not None and link.type not in KEPT:
        return Known(link, "other", f"it is {_TOKEN_WORDS.get(link.type, 'a ' + link.type + ' tab')}: {KEEPS}")
    url = page_url(conn, link)
    if robots_disallows(url) is not None:
        return Known(link, "other", CLOSED)
    answer = cache.cached(url, accept=(200, 404))
    if answer is not None and answer.status == 404:
        return Known(link, "gone", GONE)
    page: UGTabPage | None = None
    if answer is not None:
        try:
            page = parse_tab_page(answer.content, url=url)
        except PageParseError:  # a copy cut short: read again, past the cache
            page = None
    if page is not None and page.tab.kind is None:
        return Known(link, "other", f"it is {_type_words(page.tab.type)}: {KEEPS}")
    assert link.tab_id is not None
    listed = listed_tab(conn, link.tab_id)
    keys = tab_keys(conn, link.tab_id)
    tab = (_tab_of(page) if page is not None else
           Tab(listed.artist, listed.title, listed.type, None, _rating(listed.rating, listed.votes),
               listed.votes or None) if listed is not None else None)
    artist = tab.artist if tab is not None else ""
    base = (artist_page_of(page.artist_url) if page is not None else None) or (listed.page if listed else None)
    if base is None and artist:
        base = next((u for key in name_forms(artist) if (u := learned_artist_url(conn, key))), None)
    read_at = _read_at(conn, cache, base) if base else None
    linked = artist_page_of(page.artist_url) if page is not None else None
    unread = linked is not None and not _read_lately(conn, linked, now)  # its artist's lists to read yet
    state = "found" if (keys is not None or page is not None) and not unread else "auto"
    return Known(link, state, tab=tab, keys=keys, page=base, read_at=read_at, artist=artist)


def _artist_known(conn: sqlite3.Connection, cache: Any, link: UgLink) -> Known:
    from caracole.ug.artist import artist_page_url
    from caracole.ug.artist_tabs import page_artist

    held = page_artist(conn, link.url)
    read_at = _read_at(conn, cache, link.url)
    if held is not None:
        name, key, tabs, _ = held
        return Known(link, "found", page=link.url, read_at=read_at, artist=name, artist_key=key, tabs=tabs)
    if read_at is not None:  # read, and none of its tabs is of a kind caracole keeps
        return Known(link, "found", page=link.url, read_at=read_at, artist=_cached_name(cache, link.url))
    unfiltered = cache.cached(artist_page_url(link.url), accept=(404,))
    if unfiltered is not None:
        return Known(link, "gone", GONE, page=link.url)
    return Known(link, "auto", page=link.url)


def _cached_name(cache: Any, page: str) -> str:
    """UG's name of the artist, from the first list of the page the cache holds; "" for none."""
    from caracole.ug.artist import artist_page_url, parse_artist_page
    from caracole.ug.page import PageParseError

    for kind in ("chords", "tabs", None):
        url = artist_page_url(page, kind=kind)
        answer = cache.cached(url, accept=(200,))
        if answer is not None:
            try:
                return parse_artist_page(answer.content, url=url).name
            except PageParseError:
                continue
    return ""


def _read_at(conn: sqlite3.Connection, cache: Any, page: str) -> str | None:
    """When caracole read the artist page: its tabs' latest read, else the cache's copy of one of its lists; None for
    a page it never read."""
    from caracole.ug.artist import artist_page_url
    from caracole.ug.artist_tabs import page_artist

    held = page_artist(conn, page)
    if held is not None:
        return held[3]
    for kind in ("chords", "tabs", None):
        answer: Response | None = cache.cached(artist_page_url(page, kind=kind), accept=(200,))
        if answer is not None:
            return answer.fetched_at or ""
    return None


def _rating(rating: float, votes: int) -> float | None:
    return round(float(rating), 2) if votes else None


def _tab_of(page: UGTabPage) -> Tab:
    v = page.tab
    assert v.kind is not None
    return Tab(v.artist_name, v.song_name, v.kind, v.version, _rating(v.rating, v.votes), v.votes or None)


def _type_words(ug_type: str) -> str:
    return _TYPE_WORDS.get(ug_type.strip().lower(), f"a {ug_type.strip() or 'nameless'} tab")


def gate(cfg: Config, conn: sqlite3.Connection, link: UgLink, now: datetime) -> tuple[str, str]:
    """Whether a link caracole doesn't know may be read now, with no request: its state and, but ``auto``, why. Not
    while UG cools down after a block (``cooling``) or the hour's lookups are spent (``spent``), nor once its read
    failed within the hour, or its tab page won't parse even fetched again until it is due (``failed``)."""
    from caracole.commands._common import lookup_requests_used
    from caracole.health import get_state, is_cooling
    from caracole.ug.fetch import unreadable_until

    if is_cooling(conn, PROVIDER, now):
        return "cooling", f"UG turned us back; no asks until {stamps.shown(get_state(conn, PROVIDER).cooldown_until)}"
    p = cfg.provider(PROVIDER)
    if p.lookup_requests < 1 or lookup_requests_used(conn, PROVIDER, now) >= p.lookup_per_hour:
        return "spent", f"no more asks of UG this hour ({p.lookup_per_hour} spent)"
    why = failed(conn, link.url, now)
    if why is not None:
        return "failed", why
    until = unreadable_until(conn, link.tab_id) if link.tab_id is not None else None
    if until is not None and not stamps.before(until, stamps.utc(now)):
        return "failed", f"UG's copy of it can't be read; caracole asks for it again after {until[:10]}"
    return "auto", ""


# --- how caracole names what a link stands for --------------------------------------------------------------


@dataclass(frozen=True)
class Named:
    """What a link stands for, named as caracole names it (``named``): the songs (``hits``: a tab's song, or an artist
    page's songs once read, as a search gives them), the library's song of a tab (``song``), and the artist and the
    title the panel fills in (``guess``), the line a read ends with says, and a search names the song by."""

    artist: str
    title: str
    hits: list[IndexHit] = field(default_factory=list)
    song: Song | None = None


def named(conn: sqlite3.Connection, was: Known) -> Named:
    """``was``'s songs and names: a tab's song by the keys it is filed under (``index_song``, its names a search's); an
    artist page's songs once read (``search.artist_songs``). The names are the library's song's, the one that holds the
    tab as a version of its own, else of those names (its ``song``); else the hit's; else UG's as a search names a song
    only an artist page lists (``search.listed_names``: your songs' name for the artist, else the original part of
    UG's; the title's original part, Chinese written together). An artist link's title is ""."""
    from caracole.normalize import identity_key
    from caracole.search import artist_songs, index_song, listed_names
    from caracole.songs import find_song

    link = was.link
    if link.kind == "artist":
        hits = (artist_songs(conn, was.artist_key, limit=ARTIST_SONGS)[0]
                if was.state == "found" and was.artist_key else [])
        return Named(listed_names(conn, was.artist, "")[0] if was.artist else "", "", hits)
    hit = index_song(conn, *was.keys, 100.0) if was.keys is not None and was.state not in ("other", "gone") else None
    hits = [hit] if hit is not None else []
    artist, title = ((hit.artist, hit.title) if hit is not None else
                     listed_names(conn, was.tab.artist, was.tab.title) if was.tab is not None else ("", ""))
    song = _song_of(conn, link) if was.state not in ("other", "gone") else None
    if song is None and artist and title and was.state not in ("other", "gone"):
        song = find_song(conn, identity_key(artist, title))
    if song is not None:  # the library's own song of it: its names
        artist, title = song.artist, song.title
    return Named(artist, title, hits, song)


def _song_of(conn: sqlite3.Connection, link: UgLink) -> Song | None:
    """The library's song that holds the tab as a version of its own (``versions``), if any."""
    from caracole.songs import get_song
    from caracole.versions import LIVE

    row = conn.execute("SELECT song_id FROM versions WHERE provider = 'ug' AND tab_id = ? AND gone = ? "
                       "ORDER BY song_id LIMIT 1", (str(link.tab_id), LIVE)).fetchone()
    if row is None:
        return None
    try:
        return get_song(conn, row[0])
    except KeyError:
        return None


def _a_tab(conn: sqlite3.Connection, link: UgLink, page: UGTabPage) -> str:
    """A tab read, as its line says it: its title by its artist, as caracole names them (``named``), and its kind
    ("斑马斑马 by 宋冬野, chords"), with no bracket: status.py reads the line up to its first."""
    assert link.tab_id is not None
    names = named(conn, Known(link, "found", tab=_tab_of(page), keys=tab_keys(conn, link.tab_id)))
    v = page.tab
    return f"{names.title or v.song_name} by {names.artist or v.artist_name}, {_KIND_WORDS.get(v.kind or '', v.kind)}"


def known_line(conn: sqlite3.Connection, was: Known) -> str:
    """What the command says of a link it reads nothing of (``known``: ``found``, ``other``, ``gone``), in the words a
    read ends with (``said``), caracole's names for the song (``named``)."""
    from caracole.ug.artist_tabs import page_artist

    link = was.link
    if was.state == "gone":
        return f"Not found: UG answers 404 for {link.url}."
    if was.state == "other":
        return f"Not read: {link.url}: {was.why}."
    held = page_artist(conn, was.page) if was.page else None
    tabs = held[2] if held is not None else 0
    names = named(conn, was)
    if link.kind == "artist":
        return f"Read: UG's page of {names.artist or 'the artist'} lists {plural(tabs, 'tab')}."
    song = f"{names.title} by {names.artist}" if names.title and names.artist else f"tab {link.tab_id}"
    if was.tab is None:
        return f"Read: {song}, in UG's index; nothing asked."
    their = (f"their page lists {plural(tabs, 'tab')}" if was.read_at is not None else
             "their page isn't read yet" if was.page else "it links to no artist page")
    return f"Read: {song}, {_KIND_WORDS.get(was.tab.type, was.tab.type)}; {their}."


# --- a read that failed ------------------------------------------------------------------------------------


def _failures(conn: sqlite3.Connection, now: datetime) -> dict[str, dict[str, str]]:
    said = kv_get_json(conn, FAILED_KEY)
    since = stamps.utc(now) - FAILED_FOR
    return {k: {"at": str(v.get("at")), "error": str(v.get("error") or "")} for k, v in said.items()
            if isinstance(k, str) and isinstance(v, dict) and not stamps.before(v.get("at"), since)
            } if isinstance(said, dict) else {}


def failed(conn: sqlite3.Connection, url: str, now: datetime) -> str | None:
    """Why the page doesn't read the link by itself now: its read failed within the hour; None when it didn't."""
    failure = _failures(conn, now).get(url)
    return f"reading it failed within the hour ({failure['error']})" if failure is not None else None


def record_failure(conn: sqlite3.Connection, url: str, now: datetime, error: str) -> None:
    """The link's read failed (kv ``ug:link-failed``): the page doesn't send it by itself again within the hour, and
    the failures older than that go."""
    failures = _failures(conn, now)
    failures[url] = {"at": stamps.stamp(now), "error": " ".join(error.split())[:ERROR_CHARS]}
    kv_set_json(conn, FAILED_KEY, failures)


def forget_failure(conn: sqlite3.Connection, url: str, now: datetime) -> None:
    """The link was read: its failure goes, and those older than the hour."""
    said = kv_get_json(conn, FAILED_KEY)
    failures = _failures(conn, now)
    gone = failures.pop(url, None) is not None
    if gone or (isinstance(said, dict) and len(said) != len(failures)):
        kv_set_json(conn, FAILED_KEY, failures)


# --- the page read now -------------------------------------------------------------------------------------


@dataclass
class LinkRead:
    """What reading a link's page came to (``read``): a tab's page (``tab``), the artist page learned or given
    (``page``), its lists (``listing``) and the tabs caracole holds of it (``tabs``), and what stopped its read, the
    tab known (``stopped``: a spent budget, a block, an error)."""

    link: UgLink
    url: str
    tab: TabRead | None = None
    page: str | None = None
    listing: Listing | None = None
    tabs: int = 0
    stopped: BaseException | None = field(default=None, repr=False)
    until: str | None = None  # when caracole asks again for a tab page that won't parse


Stage = Callable[[str, str, str], None]


def read(ctx: FetchContext, link: UgLink, stage: Stage) -> LinkRead:
    """The link's page read now (the module's docstring), ``stage(name, state, detail)`` told how each of its stages
    (``tab``, ``artist``) starts and ends. A block, a spent budget or an error before anything was read propagates;
    one during an artist page read after a tab's page is the read's ``stopped``."""
    from caracole.http import BudgetExhausted, ProviderError
    from caracole.ug.fetch import _learn_artist_url, read_artist_page, read_tab_page, unreadable_until

    done = LinkRead(link, page_url(ctx.conn, link))
    if link.kind == "tab":
        assert link.tab_id is not None
        stage("tab", "running", "asking Ultimate Guitar")
        done.tab = read_tab_page(ctx, link.tab_id, done.url)
        if done.tab.said in ("waits", "unreadable"):
            done.until = unreadable_until(ctx.conn, link.tab_id)
        page = done.tab.page
        if page is None or page.tab.kind is None:
            return done
        stage("tab", "done", _a_tab(ctx.conn, link, page))
        done.page = _learn_artist_url(ctx.conn, page)
        if done.page is None:
            return done
    else:
        done.page = link.url
    stage("artist", "running", "asking Ultimate Guitar")
    try:
        done.listing = read_artist_page(ctx, done.page)
    except (BudgetExhausted, ProviderError) as e:
        if link.kind != "tab":
            raise
        done.stopped = e
        return done
    if done.listing.gone:
        _page_gone(ctx.conn, done.page)
    else:
        from caracole.ug.artist_tabs import page_artist

        held = page_artist(ctx.conn, done.page)
        done.tabs = held[2] if held is not None else 0
    return done


def _page_gone(conn: sqlite3.Connection, page: str) -> None:
    """UG answered 404 for the artist page: its tabs go, and every artist it was learned for learns it again."""
    from caracole.ug import artist_tabs
    from caracole.ug.lookup import ARTIST_URL_KV, forget_artist_url

    for (key,) in conn.execute("SELECT key FROM kv WHERE substr(key, 1, ?) = ? AND value = ? ORDER BY key",
                               (len(ARTIST_URL_KV), ARTIST_URL_KV, page)).fetchall():
        forget_artist_url(conn, key[len(ARTIST_URL_KV):])
    artist_tabs.forget(conn, page)


def lists(tabs: int, listing: Listing | None) -> str:
    """What a tab's artist page read lists, in words."""
    if listing is not None and not listing.complete:
        return f"{plural(tabs, 'tab')} of their page read so far, the rest the next time"
    return f"their page lists {plural(tabs, 'tab')}"


def said(conn: sqlite3.Connection, done: LinkRead) -> str:
    """The line the read ends with (the module's docstring), ``Read: ``, ``Not found: `` or ``Not read: ``, the song
    and the artist named as caracole names them (``named``), with no bracket in the part status.py reads; a block, a
    spent budget or an error before anything was read is the command's to say."""
    from caracole.http import BudgetExhausted, ProviderBlocked
    from caracole.search import listed_names

    link, tab = done.link, done.tab
    if tab is not None:
        if tab.said == "gone":
            return f"Not found: UG answers 404 for {done.url}."
        if tab.said in ("closed", "redirected"):
            where = "closes it" if tab.said == "closed" else "closes where UG sends it"
            return f"Not read: robots.txt {where} to caracole ({done.url})."
        if tab.said in ("waits", "unreadable"):
            until = (done.until or "?")[:10]
            error = f" ({tab.error})" if tab.error is not None else ""
            return f"Not read: UG's copy of {done.url} can't be read{error}; caracole asks for it again after {until}."
        page = tab.page
        assert page is not None
        if page.tab.kind is None:
            artist, title = listed_names(conn, page.tab.artist_name, page.tab.song_name)
            return f"Read: {title} by {artist} is {_type_words(page.tab.type)}: {KEEPS}."
        named = _a_tab(conn, link, page)
        if done.page is None:
            return f"Read: {named}; it links to no artist page."
        if isinstance(done.stopped, BudgetExhausted):
            return f"Read: {named}; their page waits for the next lookup (its asks of UG are spent)."
        if isinstance(done.stopped, ProviderBlocked):
            return f"Read: {named}; UG turned us back on their page ({done.stopped})."
        if done.stopped is not None:
            return f"Read: {named}; their page failed ({done.stopped})."
        if done.listing is not None and done.listing.gone:
            return f"Read: {named}; their page is gone (UG answers 404 for it)."
        return f"Read: {named}; {lists(done.tabs, done.listing)}."
    if done.listing is not None and done.listing.gone:
        return f"Not found: UG answers 404 for {link.url}."
    ug_name = done.listing.name if done.listing is not None else ""
    name = listed_names(conn, ug_name, "")[0] if ug_name else "the artist"
    if done.listing is not None and not done.listing.complete:
        return f"Read: {plural(done.tabs, 'tab')} of UG's page of {name} so far, the rest the next time."
    return f"Read: UG's page of {name} lists {plural(done.tabs, 'tab')}."
