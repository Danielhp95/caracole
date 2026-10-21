"""Per-song Ultimate Guitar fetch: rate every version, keep the best sheet, pick guitar parts.

For each song (plan §3, Task 15, amendment A6):

1. **Candidates.** The song's tabs in the local index, fetched at their
   slugged URLs (UG answers 404 for a slugged tab at the bare ``/tab/{id}``),
   and its pins, which replace the kind group they belong to and are fetched
   at the slugged address you pasted, if you pasted one. Blocked ids never
   compete, and neither does a tab at a URL robots.txt closes
   (``caracole.http.robots_disallows``): such a URL is never asked for. Nor does
   one whose page UG redirects to such a URL (``caracole.http.RobotsClosed``),
   or one at a link that isn't a URL. A not-found song is looked up on its
   artist's UG page, which also lists the bare-id tabs the index can't see (A6).
2. **Ratings.** A tab page lists the other versions of its type and part, so
   for each kind group (chords; Guitar Pro and Power Tab; tabs) caracole reads
   the page of the lowest id it has no rating for, up to
   ``max_pages_per_group`` pages, recording the page's own tab and the
   versions it lists. Official, non-public and blocked versions are skipped.
3. **Slots, one at a time,** so the sheet a singer needs most is settled
   before the budget goes to guitar parts:
   - the sheet: the top ``scored_sheets`` chords versions by rating are
     scored for lyric coverage, ranked complete-first, and the best is kept
     as ``sheet.txt`` and ``sheet.json``; a complete one retires
     ``sheet (auto).txt``;
   - Guitar Pro and Power Tab: the best are picked, never downloaded
     (assisted mode: the to-do page lists them);
   - tabs: the best is kept as ``tab.txt`` and ``tab.json``.
4. Only when every slot is done is the song marked checked and clean, so a
   song interrupted by the budget resumes from the HTTP cache next run.

A run settles the sheet of every waiting song before it spends anything on
guitar parts (``fetch_songs``), and rates each guitar group from one page:
live, filling every slot song by song cost 8-12 requests a song.

A kept file is replaced only when another version outranks it, and is not
rewritten when it wins again, unless the library lost it (deleted on a synced
device, cut short by a power cut, a link in its place): then it is written
again, and only it.

``rescore_kept_sheets`` scores the sheets kept before their song had lyrics,
without a request, and sends a song whose kept sheet proves partial back to
have its sheets ranked again; the nightly run calls it before fetching. It
also sends back a song whose kept sheet or tab the library lost.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from rapidfuzz import fuzz

from caracole import coverage
from caracole.config import RankPolicy
from caracole.db import kv_delete, kv_get, kv_get_json, kv_set, kv_set_json
from caracole.http import (
    BudgetExhausted,
    Client,
    ProviderBlocked,
    ProviderError,
    Response,
    RobotsClosed,
    robots_disallows,
    stale,
)
from caracole.library import drop_file, holds, keep_file, kept_already, kept_files, read_json, write_info
from caracole.lyrics import song_lyrics
from caracole.match import ARTIST_PAGE, REVIEW_ONLY_STEPS
from caracole.normalize import clean_title, compact, listing_forms, name_forms, slug_key, without_featuring
from caracole.overrides import Overrides, artist_page_address, artist_url_entry, pasted_tab_id
from caracole.rank import Candidate, is_complete, rank_by_rating, rank_guitar, rank_sheets
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, get_song, list_songs, refresh_status, update_song
from caracole.ug import artist_tabs as listed_tabs  # ug.lookup.artist_tabs is another thing
from caracole.ug.artist import WWW, UGArtistPage, artist_page_url, parse_artist_page
from caracole.ug.lookup import (
    IndexTab,
    artist_known,
    artist_tabs,
    forget_artist_url,
    index_tab,
    learned_artist_url,
    remember_artist_url,
    song_tabs,
    tab_url_for,
)
from caracole.ug.page import (
    TAB_BASE_URL,
    PageParseError,
    UGTabPage,
    UGVersion,
    parse_tab_page,
    strip_markup,
)
from caracole.versions import (
    LIVE,
    SHEET_KINDS,
    STALE,
    VersionRow,
    complete,
    get_version,
    mark_gone,
    replaces_sheet,
    set_coverage,
    set_picks,
    song_versions,
    upsert_version,
)

log = logging.getLogger(__name__)

PROVIDER = "ug"
_PAGE_ACCEPT = (200, 404)
CHORDS_KINDS = ("chords",)  # UG's kinds for the sheet slot, which holds every site's SHEET_KINDS
GUITAR_PRO_KINDS = ("guitar-pro", "power")
TAB_KINDS = ("tabs",)
_GROUPS = (CHORDS_KINDS, GUITAR_PRO_KINDS, TAB_KINDS)
_GROUP_OF = {kind: group for group in _GROUPS for kind in group}
SHEET_FILES = (HUMAN_SHEET, "sheet.json")
TAB_FILES = ("tab.txt", "tab.json")
KEPT_TEXT = (*SHEET_FILES, *TAB_FILES)  # the files a kept UG sheet or tab is
_KEPT_TEXT_MARKS = ",".join("?" for _ in KEPT_TEXT)
_TAB_HOST = urlsplit(TAB_BASE_URL).netloc

# The artist-page route (A6): a song found on it has the match step ``ARTIST_PAGE``.
ARTIST_PAGE_MAX_AGE = timedelta(days=30)
ARTIST_PAGE_KINDS = ("chords", "guitar-pro", "power", "tabs")  # the sheet's list first
TITLE_MATCH = 90  # rapidfuzz ratio of title keys, the matcher's accept score
TITLE_MARGIN = 8  # a fuzzy title must lead the next different title by this much
LEARN_TRIES = 3  # slugged tabs read at most to learn an artist's page

# A tab page that won't parse, even fetched again, is asked for again after a week, then after
# twice as long each time it still won't.
UNREADABLE_RETRY = timedelta(days=7)
UNREADABLE_RETRY_MAX = timedelta(days=90)


class UnreadablePage(PageParseError):
    """A cached page that doesn't parse, fetched again and still not parsing: a provider error."""


@dataclass
class FetchContext:
    """Everything one fetch run needs. ``client`` is the run's UG client.

    ``artist_pages_per_kind`` caps the artist-page list pages one song may
    fetch from UG per kind per run; cached pages don't count, so a long list
    is read over several runs. ``max_pages_per_group`` caps the pages read to
    rate the chords group, ``guitar_pages_per_group`` each guitar group.
    """

    conn: sqlite3.Connection
    client: Client
    overrides: Overrides
    rank: RankPolicy
    library_dir: Path
    now: datetime
    max_pages_per_group: int = 3
    guitar_pages_per_group: int = 1
    artist_page_max_age: timedelta = ARTIST_PAGE_MAX_AGE
    artist_pages_per_kind: int = 3
    # overrides.toml read again, for ``fetch_songs`` once its client handed caracole's lock to a lookup.
    reload_overrides: Callable[[], Overrides] | None = None


@dataclass(frozen=True)
class SongFetchOutcome:
    """What one song's fetch kept: UG tab ids of the sheet, the Guitar Pro picks and the text tab.

    ``requests`` counts the requests sent to UG for the song (cache hits are free).
    ``settled`` says the sheet slot was decided (the guitar slots may still wait).
    """

    song_id: int
    sheet: int | None
    guitar_pro: tuple[int, ...]
    tab: int | None
    requests: int
    settled: bool = False


@dataclass
class FetchStats:
    """A fetch run: sheets settled, songs finished, songs skipped after a provider error, and
    whether the budget ran out."""

    songs_done: int = 0
    songs_failed: int = 0
    budget_exhausted: bool = False
    sheets_done: int = 0
    # The songs counted in songs_failed, each with its error, for the run's summary.
    failures: list[tuple[Song, ProviderError]] = field(default_factory=list, compare=False, repr=False)


@dataclass
class _SongRun:
    """One song's fetch: the song, the tab pages already read for it this run, and how many
    pages of each UG type were fetched from UG (cache hits are free)."""

    ctx: FetchContext
    song: Song
    pages: dict[int, UGTabPage | None] = field(default_factory=dict)
    fetched: Counter[str] = field(default_factory=Counter)
    unreadable: set[int] = field(default_factory=set)  # tabs whose pages couldn't be read this run

    @property
    def conn(self) -> sqlite3.Connection:
        return self.ctx.conn

    @property
    def artist_key(self) -> str:
        """The UG artist key the song is filed under: its match, else its own artist's key."""
        return self.song.match_artist_key or slug_key(self.song.artist)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _slot(kind: str) -> str:
    return "sheet" if kind in SHEET_KINDS else "guitar"


# --- artist keys ------------------------------------------------------------------------------


def artist_keys(song: Song, overrides: Overrides) -> list[str]:
    """The UG artist keys a song may be listed under: [alias] first, then each artist's own keys."""
    keys: list[str] = []
    for name in song.artists or [song.artist]:
        keys += overrides.alias.get(slug_key(name), ())
        keys += name_forms(name)
    return [k for k in dict.fromkeys(keys) if k]


def artist_is_known(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> bool:
    """Whether the song's artist page can be found: pasted in [artist_url] (a tab page there counts
    until reading it shows it leads to no artist page), learned, or in the index."""
    keys = artist_keys(song, overrides)
    if artist_url_entry(overrides, keys) is not None and _failed_paste(conn, keys, overrides) is None:
        return True
    return any(learned_artist_url(conn, k) or artist_known(conn, k) for k in keys)


def pasted_page_problem(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> tuple[str, str] | None:
    """The tab page you pasted under [artist_url] for the song's artist and what is wrong with it, when
    reading it gave no artist page (``PASTE_GONE``, ``PASTE_CLOSED``, ``PASTE_NO_ARTIST``) or it couldn't
    be read (``PASTE_UNREADABLE``, and when caracole asks for it again); else None."""
    return _paste_problem(conn, artist_keys(song, overrides), overrides)


def _paste_problem(conn: sqlite3.Connection, keys: list[str], overrides: Overrides) -> tuple[str, str] | None:
    """``pasted_page_problem`` for an artist's keys."""
    if (failed := _failed_paste(conn, keys, overrides)) is not None:
        return failed
    if (unread := _unread_paste(conn, keys, overrides)) is not None:
        return unread[0], f"{PASTE_UNREADABLE}; caracole asks for it again after {unread[1][:10]}"
    return None


# --- pages and versions ---------------------------------------------------------------------------


def _get_page[P: (UGTabPage, UGArtistPage)](
    client: Client,
    url: str,
    parse: Callable[..., P],
    *,
    max_age: timedelta | None = None,
    now: datetime | None = None,
) -> tuple[P | None, bool]:
    """A UG page from the HTTP cache or UG (None when UG answers 404), and whether it was fetched now.

    UG's 404 page has no js-store, so the status is checked before parsing.
    A 200 is cached (tab pages forever), so a cached body that no longer
    parses (a truncated or maintenance page) is fetched once more instead of
    failing the song on every run; when that copy doesn't parse either, UG
    keeps serving it, and the page is ``UnreadablePage``.

    With ``max_age``, a cached copy older than that is no answer for ``now``:
    PoliteClient serves one only once the budget is spent, so this stops as
    the next request would have (``BudgetExhausted``).
    """
    page, resp = _read_page(client, url, parse, max_age=max_age, now=now)
    return page, not resp.from_cache


def _read_page[P: (UGTabPage, UGArtistPage)](
    client: Client,
    url: str,
    parse: Callable[..., P],
    *,
    max_age: timedelta | None = None,
    now: datetime | None = None,
) -> tuple[P | None, Response]:
    """``_get_page``, with the answer the page was read from (its ``from_cache``, its ``fetched_at``)."""

    def parsed(resp: Response) -> P | None:
        return None if resp.status == 404 else parse(resp.content, url=url)

    resp = client.get(url, accept=_PAGE_ACCEPT, max_age=max_age)
    if max_age is not None and now is not None and stale(resp, now, max_age):
        raise BudgetExhausted(PROVIDER)
    try:
        return parsed(resp), resp
    except PageParseError:
        if not resp.from_cache:
            raise
    again = client.get(url, accept=_PAGE_ACCEPT, cache=False)
    try:
        return parsed(again), again
    except PageParseError as e:
        raise UnreadablePage(e.provider, e.url, e.status, e.message) from e


def _upsert(run: _SongRun, v: UGVersion) -> int:
    assert v.kind is not None
    return upsert_version(
        run.conn, provider=PROVIDER, tab_id=str(v.tab_id), song_id=run.song.id, slot=_slot(v.kind), kind=v.kind,
        rating=v.rating, votes=v.votes, version=v.version, label=v.label, url=v.url, raw=v.raw,
        now=_iso(run.ctx.now),
    )


def _closed(url: str) -> bool:
    """Whether robots.txt closes ``url`` (``robots_disallows``): caracole never asks for it, and a tab
    there is no candidate (neither gone nor unreadable: the song goes on with its other versions)."""
    return robots_disallows(url) is not None


def _on_tab_host(url: str) -> bool:
    """Whether a link points under ``/tab/`` on the tabs host, where UG's tab pages are (one urllib
    can't parse points nowhere: UG's JSON is data, and one broken link never ends the run)."""
    try:
        parts = urlsplit(url)
    except ValueError:  # "Invalid IPv6 URL", say
        return False
    segments = parts.path.split("/")
    return (
        parts.scheme in ("http", "https") and parts.netloc == _TAB_HOST
        and len(segments) > 2 and segments[1] == "tab"
    )


def _tab_page_url(url: str) -> bool:
    """Whether a link from UG's JSON is a tab page caracole may read: on the tabs host, and open in
    robots.txt, which closes /tab/download, /tab/print?, /tab/track/ and more (``ROBOTS_DISALLOW``)."""
    return _on_tab_host(url) and not _closed(url)


def _wanted(run: _SongRun, v: UGVersion) -> bool:
    """A kind caracole uses (never Official, which UG marks public too), public and not blocked."""
    return v.kind is not None and v.access == "public" and v.tab_id not in run.ctx.overrides.block


def _usable(run: _SongRun, v: UGVersion) -> bool:
    """A version caracole wants, at a tab page it may read."""
    return _wanted(run, v) and _tab_page_url(v.url)


def _links_a_tab_page(v: UGVersion) -> bool:
    """Whether a version links to a tab page: one caracole may read, or its own slugged page, which
    robots.txt may close (UG files every tab of the band Track under /tab/track/)."""
    return _tab_page_url(v.url) or (_on_tab_host(v.url) and _slugged_url(v.url, v.tab_id))


def _check_links(run: _SongRun, versions: Iterable[UGVersion], url: str) -> None:
    """Raise ``PageParseError`` when a page lists versions caracole wants and not one links to a tab page.

    Some links go elsewhere (robots.txt closes /tab/download); all of them
    going elsewhere means UG's links changed shape, which is an error, never
    "no versions". Versions at their own slugged pages, which robots.txt
    closes, are no change of shape: only versions caracole may not use.
    """
    wanted = [v for v in versions if _wanted(run, v)]
    if wanted and not any(_links_a_tab_page(v) for v in wanted):
        raise PageParseError(PROVIDER, url, None, "no version on the page links to a tab page")


def _known(run: _SongRun, tab_id: int) -> bool:
    """Whether the song has the version on record under its current match (a stale one isn't)."""
    return run.conn.execute(
        "SELECT 1 FROM versions WHERE provider = ? AND tab_id = ? AND song_id = ? AND gone != ?",
        (PROVIDER, str(tab_id), run.song.id, STALE),
    ).fetchone() is not None


def _record(run: _SongRun, versions: Iterable[UGVersion], *, fresh: bool) -> None:
    """Record usable versions of the song.

    Ratings change, and pages are cached forever, so only a page fetched from
    UG this run (``fresh``) may overwrite what is stored; a cached page only
    adds versions the song doesn't have yet.
    """
    for v in versions:
        if _usable(run, v) and (fresh or not _known(run, v.tab_id)):
            _upsert(run, v)


def _record_page(run: _SongRun, page: UGTabPage, url: str, *, fresh: bool) -> None:
    """Record the page's own tab and the versions it lists of the same kind group.

    The page's own tab was just read at ``url``, so it is recorded there
    should its own link go elsewhere (``_check_links``).
    """
    group = _GROUP_OF.get(page.tab.kind or "")
    if group is None:
        return
    tab, *listed = [v for v in (page.tab, *page.versions) if v.kind in group]
    _check_links(run, [tab, *listed], url)
    _record(run, (tab if _tab_page_url(tab.url) else replace(tab, url=url), *listed), fresh=fresh)


def _version_row(run: _SongRun, tab_id: int) -> VersionRow | None:
    for r in song_versions(run.conn, run.song.id, include_gone=True):
        if r.provider == PROVIDER and r.tab_id == str(tab_id):
            return r
    return None


def _mark_gone(run: _SongRun, tab_id: int, url: str, kind: str | None) -> None:
    """UG answered 404: the version is gone. An id known only from the index gets a row to say so."""
    row = _version_row(run, tab_id)
    if row is not None:
        version_id = row.id
    elif kind in _GROUP_OF:
        assert kind is not None
        version_id = upsert_version(
            run.conn, provider=PROVIDER, tab_id=str(tab_id), song_id=run.song.id, slot=_slot(kind), kind=kind,
            rating=0, votes=0, version=0, label=None, url=url, raw={}, now=_iso(run.ctx.now),
        )
    else:
        return
    mark_gone(run.conn, version_id)


def _artist_page_base(url: str | None) -> str | None:
    """The UG artist page a link of UG's points to (``https://www.ultimate-guitar.com/artist/<name>_<id>``
    or ``…/artist/<id>``, ``overrides.artist_page_address``), else None. A relative link is UG's own."""
    if not url:
        return None
    try:
        return artist_page_address(urljoin(WWW + "/", url.strip()))
    except ValueError:  # a link urllib can't parse ("Invalid IPv6 URL"): no artist page
        return None


def _a_pair(name: str) -> bool:
    """Whether the artist UG names ``name`` features another ("Ma Di (feat. 宋冬野)"): UG may give such a
    pair a page of its own, which lists neither artist's other songs."""
    return without_featuring(name) != name.strip()


def _same_artist(key: str, name: str) -> bool:
    """Whether the artist UG names ``name`` is the one filed under ``key``: they share a form, hyphens
    aside, as "宋冬野" and "Song Dongye (宋冬野)" do. A pair is neither of its artists."""
    if _a_pair(name):
        return False
    return not {compact(k) for k in name_forms(key)}.isdisjoint(compact(k) for k in name_forms(name))


def _learn_artist_url(conn: sqlite3.Connection, page: UGTabPage, also: Iterable[str] = ()) -> str | None:
    """Remember the artist page a tab page links to, under its artist's keys and ``also``; return it.

    A pair's page is filed under the pair's own name alone: under either artist's, it would stand in
    for that artist's own page (``_same_artist``)."""
    url = _artist_page_base(page.artist_url)
    if url is not None:
        name = page.tab.artist_name
        own = [slug_key(name)] if _a_pair(name) else name_forms(name)
        for key in dict.fromkeys([*own, *also]):
            if key:
                remember_artist_url(conn, key, url)
    return url


def _unreadable_key(tab_id: int) -> str:
    return f"ug:unreadable:{tab_id}"


def _waits(run: _SongRun, tab_id: int) -> bool:
    """Whether the tab's page proved unreadable and isn't due to be asked for again yet."""
    record = kv_get_json(run.conn, _unreadable_key(tab_id))
    try:
        return run.ctx.now < _parse_iso(record["until"])
    except (TypeError, KeyError, ValueError):
        return False


def _note_unreadable(run: _SongRun, tab_id: int, error: UnreadablePage) -> None:
    """Note when to ask for the tab's page again, which won't parse even fetched again: after a week, then
    after twice as long each time it still won't (``UNREADABLE_RETRY``)."""
    record = kv_get_json(run.conn, _unreadable_key(tab_id))
    strikes = int(record.get("strikes", 0) if isinstance(record, dict) else 0) + 1
    until = run.ctx.now + min(UNREADABLE_RETRY * 2 ** (strikes - 1), UNREADABLE_RETRY_MAX)
    kv_set_json(run.conn, _unreadable_key(tab_id), {"until": _iso(until), "strikes": strikes, "error": str(error)})
    log.warning("UG tab %s can't be read (%s); asked for again after %s", tab_id, error, _iso(until))


def _unreadable(run: _SongRun, tab_id: int, kind: str | None, error: UnreadablePage | None = None) -> None:
    """No page for the tab this run; with ``error``, note when to ask for it again.

    The tab is never taken for gone: the song goes on with its other versions,
    and stays dirty to read this one once it is due.
    """
    if error is not None:
        run.fetched[kind or "?"] += 1  # the request that fetched it again
        _note_unreadable(run, tab_id, error)
    run.pages[tab_id] = None
    run.unreadable.add(tab_id)


def _page(run: _SongRun, tab_id: int, url: str, kind: str | None = None) -> UGTabPage | None:
    """A tab page of this song, read once per run; None when UG says it's gone, or it can't be read.

    ``kind`` (the index's type) lets a deleted tab that was never rated be
    remembered as gone. Every page also teaches caracole its artist's UG page,
    filed under the song's artist only when the tab is by that artist. A page
    that won't parse even fetched again is left alone until it is due
    (``UNREADABLE_RETRY``). A page robots.txt closes is None without a request,
    and is neither gone nor unreadable; so is one UG redirects to where
    robots.txt closes (``RobotsClosed``), which isn't asked for again this run.
    """
    if tab_id in run.pages:
        return run.pages[tab_id]
    if _closed(url):
        return None
    if _waits(run, tab_id):
        _unreadable(run, tab_id, kind)
        return None
    try:
        page, fresh = _get_page(run.ctx.client, url, parse_tab_page)
    except UnreadablePage as e:
        _unreadable(run, tab_id, kind, e)
        return None
    except RobotsClosed:
        run.fetched[kind or "?"] += 1  # the request UG answered with the redirect
        run.pages[tab_id] = None
        return None
    kv_delete(run.conn, _unreadable_key(tab_id))
    run.pages[tab_id] = page
    if fresh:
        run.fetched[(page.tab.kind if page is not None else None) or kind or "?"] += 1
    if page is None:
        _mark_gone(run, tab_id, url, kind)
        return None
    _record_page(run, page, url, fresh=fresh)
    mine = run.artist_key
    _learn_artist_url(run.conn, page, [mine] if mine and _same_artist(mine, page.tab.artist_name) else [])
    return page


# --- ratings and pins -------------------------------------------------------------------------------


def _seen_ids(run: _SongRun) -> set[int]:
    """The tabs rated (or found gone) under the song's current match; a stale one is read again."""
    return {
        int(r.tab_id) for r in song_versions(run.conn, run.song.id, include_gone=True)
        if r.provider == PROVIDER and not r.stale
    }


def _rate_group(run: _SongRun, tabs: list[IndexTab], pages: int) -> None:
    """Read the page of the lowest unrated id until all are rated, or until ``pages`` pages of
    this type were fetched from UG this run (earlier steps' fetches count, cached pages don't).

    Tabs whose slug names no part (intro, solo, ...) go first: a page lists its own (type,
    part) group, so the full song's page rates the versions worth keeping.
    """
    tried: set[int] = set()
    kinds = {t.type for t in tabs}
    while sum(run.fetched[k] for k in kinds) < pages:
        seen = _seen_ids(run)
        todo = sorted(
            (t for t in tabs if t.tab_id not in seen and t.tab_id not in tried),
            key=lambda t: (t.label is not None, t.tab_id),
        )
        if not todo:
            return
        tried.add(todo[0].tab_id)
        _page(run, todo[0].tab_id, todo[0].url, todo[0].type)


def _pins(overrides: Overrides, song: Song) -> list[tuple[int, str | None]]:
    """The song's pins you haven't blocked, in pinned order, each with the address you pasted."""
    urls = overrides.pin_urls.get(song.key, ())
    return [
        (tab_id, urls[i] if i < len(urls) else None)
        for i, tab_id in enumerate(overrides.pin.get(song.key, ()))
        if tab_id not in overrides.block
    ]


def _slugged_url(url: str, tab_id: int) -> bool:
    """Whether a tab page URL is the slugged ``/tab/{artist}/{song}-{type}-{id}`` of ``tab_id``."""
    segments = urlsplit(url).path.split("/")
    return len(segments) == 4 and segments[3].endswith(f"-{tab_id}")


def _pinned_url(run: _SongRun, tab_id: int, pasted: str | None, row: VersionRow | None) -> str:
    """Where a pinned tab's page is.

    UG serves a slugged tab only at its slugged URL, so the slugged address you
    pasted comes first, even one robots.txt closes: the tab is then nowhere
    caracole may read it (its bare page would answer 404). A bare ``/tab/{id}``
    you pasted adds nothing: then UG's own link to the tab, else the index's
    path, else the bare page.
    """
    if pasted is not None and _on_tab_host(pasted) and _slugged_url(pasted, tab_id):
        return pasted
    return row.url if row is not None else tab_url_for(run.conn, tab_id)


def _fetch_pins(run: _SongRun, pins: list[tuple[int, str | None]]) -> dict[tuple[str, ...], list[int]]:
    """Read every pinned page; return the pinned ids of each kind group, in pinned order.

    A pin's kind comes from its page. A pin whose page is gone, Official or not
    public pins nothing, and so does one whose page robots.txt closes.
    """
    groups: dict[tuple[str, ...], list[int]] = {}
    for tab_id, pasted in pins:
        row = _version_row(run, tab_id)
        known = index_tab(run.conn, tab_id)
        url = _pinned_url(run, tab_id, pasted, row)
        kind = row.kind if row is not None else known.type if known is not None else None
        page = _page(run, tab_id, url, kind)
        if page is None or not _wanted(run, page.tab):  # read at a tab page, wherever its own link goes
            continue
        groups.setdefault(_GROUP_OF[page.tab.kind], []).append(page.tab.tab_id)
    return groups


# --- the slots ---------------------------------------------------------------------------------------


def _rows(run: _SongRun, kinds: tuple[str, ...]) -> list[VersionRow]:
    """The song's live UG versions of these kinds; blocked ids never compete, even if seen earlier,
    and neither does a version at a URL robots.txt closes (one recorded before caracole checked)."""
    block = run.ctx.overrides.block
    return [
        r for r in song_versions(run.conn, run.song.id, kinds=kinds)
        if r.provider == PROVIDER and int(r.tab_id) not in block and not _closed(r.url)
    ]


def _in_order(rows: list[VersionRow], tab_ids: list[int]) -> list[VersionRow]:
    by_tab = {int(r.tab_id): r for r in rows}
    return [by_tab[t] for t in tab_ids if t in by_tab]


def _candidate(row: VersionRow) -> Candidate:
    return Candidate(
        provider=row.provider, tab_id=row.tab_id, kind=row.kind, rating=row.rating, votes=row.votes,
        version=row.version, label=row.label, coverage=row.coverage, version_id=row.id,
    )


def _text_page(run: _SongRun, row: VersionRow) -> UGTabPage | None:
    """A version's page with its text, or None when the page is gone or can't be read now."""
    page = _page(run, int(row.tab_id), row.url, row.kind)
    return page if page is not None and page.content is not None else None


def _first_with_text(
    run: _SongRun, ranked: Iterable[Candidate], rows: list[VersionRow], pages: dict[int, UGTabPage]
) -> tuple[Candidate, UGTabPage] | None:
    """The best-ranked candidate whose page still has its text, with that page."""
    by_id = {r.id: r for r in rows}
    for c in ranked:
        assert c.version_id is not None
        page = pages.get(c.version_id) or _text_page(run, by_id[c.version_id])
        if page is not None:
            return c, page
    return None


def _keep(run: _SongRun, version_id: int, name: str, data: bytes) -> None:
    """Keep one file, unless this version's identical bytes are kept already, in the files table and
    in the library (``library.kept_already``): no churn for Syncthing, and a file the library lost is
    written again."""
    if kept_already(run.conn, run.ctx.library_dir, song=run.song, version_id=version_id, name=name, data=data):
        return
    keep_file(run.conn, run.ctx.library_dir, song=run.song, version_id=version_id, name=name, data=data, rank=1)


def _keep_text(run: _SongRun, version_id: int, page: UGTabPage, names: tuple[str, str]) -> None:
    """Keep a sheet or tab: the text without UG's markup, and the version's JSON with the raw content.

    The JSON also carries the page's ``meta``, where UG gives the capo.
    """
    assert page.content is not None
    txt, doc = names
    url = get_version(run.conn, version_id).url
    _keep(run, version_id, txt, strip_markup(page.content).encode("utf-8"))
    body = {"version": dict(page.tab.raw), "content": page.content, "url": url, "meta": dict(page.meta)}
    _keep(run, version_id, doc, (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _kept_version(conn: sqlite3.Connection, song_id: int, name: str) -> VersionRow | None:
    """The version a kept file came from, whichever step kept it."""
    for f in kept_files(conn, song_id):
        if f.name == name:
            return get_version(conn, f.version_id)
    return None


def _retire_auto_sheet(conn: sqlite3.Connection, library_dir: Path, song: Song) -> None:
    """A complete human sheet is kept: the auto-chords sheet, which only stands in for one, goes."""
    auto = _kept_version(conn, song.id, AUTO_SHEET)
    if auto is not None:
        drop_file(conn, library_dir, song=song, name=AUTO_SHEET)
        set_picks(conn, song.id, (auto.kind,), [])


def _drop_left_over(run: _SongRun, names: tuple[str, str]) -> None:
    """Files kept from a UG version you have blocked since, or that an earlier match found (another
    song's, by your correction), go even when nothing replaces them."""
    kept = _kept_version(run.conn, run.song.id, names[0])
    if kept is None or kept.provider != PROVIDER:
        return
    if kept.stale or int(kept.tab_id) in run.ctx.overrides.block:
        for name in names:
            drop_file(run.conn, run.ctx.library_dir, song=run.song, name=name)


def _lyric_lines(song: Song) -> list[str]:
    lyrics = song_lyrics(song)
    return coverage.lyric_lines(lyrics.plain) if lyrics is not None else []


def _sheet_slot(run: _SongRun, pinned: list[int] | None) -> int | None:
    """Score the top sheets for lyric coverage, rank them, and keep the best (or the first pin).

    A sheet another site gave (LaCuerda's) is replaced only as the shared rule
    says (``versions.replaces_sheet``): ratings can't be compared across sites,
    so coverage alone decides, and a tie keeps it. A pin is your decision and
    always wins; so is the LaCuerda sheet you picked (``[lacuerda]``), which no
    sheet but a pin replaces. The sheet kept becomes the slot's only pick, and a
    complete one retires the auto-chords sheet.
    """
    policy = run.ctx.rank
    rows = _rows(run, CHORDS_KINDS)
    lines = _lyric_lines(run.song)
    by_id = {r.id: r for r in rows}
    pages: dict[int, UGTabPage] = {}

    def scored(c: Candidate) -> bool:
        """Fetch the sheet and score its coverage; False when its page is gone or unreadable."""
        assert c.version_id is not None
        page = _text_page(run, by_id[c.version_id])
        if page is None:
            return False
        pages[c.version_id] = page
        assert page.content is not None
        c.coverage = coverage.coverage(page.content, lines, line_match=policy.line_match)
        set_coverage(run.conn, c.version_id, c.coverage)
        return True

    ranked: Iterable[Candidate]
    if pinned is not None:
        ranked = (c for c in map(_candidate, _in_order(rows, pinned)) if scored(c))
    else:
        alive: list[Candidate] = []
        for c in rank_by_rating([_candidate(r) for r in rows], policy, variant=run.song.variant):
            if len(pages) < policy.scored_sheets and not scored(c):
                continue  # gone or unreadable; the next one is scored instead
            alive.append(c)
        ranked = rank_sheets(alive, policy, variant=run.song.variant)
    best = _first_with_text(run, ranked, rows, pages)
    if best is None:
        set_picks(run.conn, run.song.id, CHORDS_KINDS, [])
        _drop_left_over(run, SHEET_FILES)
        return None
    c, page = best
    assert c.version_id is not None
    kept = _kept_version(run.conn, run.song.id, SHEET_FILES[0])
    chosen = run.ctx.overrides.lacuerda.get(run.song.key)
    if (kept is not None and kept.provider != PROVIDER and pinned is None
            and ((chosen is not None and kept.provider == "lacuerda" and chosen.holds(kept.tab_id))
                 or not replaces_sheet(c.coverage, kept.coverage, policy.coverage_threshold))):
        set_picks(run.conn, run.song.id, CHORDS_KINDS, [])  # the other site's sheet stays the pick
        return None
    _keep_text(run, c.version_id, page, SHEET_FILES)
    set_picks(run.conn, run.song.id, SHEET_KINDS, [c.version_id])
    if is_complete(c, policy):
        _retire_auto_sheet(run.conn, run.ctx.library_dir, run.song)
    return int(c.tab_id)


def _ranked_guitar(run: _SongRun, rows: list[VersionRow], pinned: list[int] | None) -> list[Candidate]:
    """A guitar slot's candidates: the pins in their order, else best rated first."""
    if pinned is not None:
        return [_candidate(r) for r in _in_order(rows, pinned)]
    return rank_guitar([_candidate(r) for r in rows], run.ctx.rank, variant=run.song.variant)


def _guitar_pro_slot(run: _SongRun, pinned: list[int] | None) -> tuple[int, ...]:
    """Pick the best Guitar Pro and Power Tab versions; nothing is downloaded (assisted mode)."""
    policy = run.ctx.rank
    ranked = _ranked_guitar(run, _rows(run, GUITAR_PRO_KINDS), pinned)
    chosen = ranked[: policy.keep_guitar_pro]
    set_picks(run.conn, run.song.id, GUITAR_PRO_KINDS, [c.version_id for c in chosen if c.version_id is not None])
    return tuple(int(c.tab_id) for c in chosen)


def _tab_slot(run: _SongRun, pinned: list[int] | None) -> int | None:
    """Keep the best text tab (or the first pin) as tab.txt and tab.json."""
    rows = _rows(run, TAB_KINDS)
    ranked = _ranked_guitar(run, rows, pinned)
    best = _first_with_text(run, ranked, rows, {})
    if best is None:
        set_picks(run.conn, run.song.id, TAB_KINDS, [])
        _drop_left_over(run, TAB_FILES)
        return None
    c, page = best
    assert c.version_id is not None
    _keep_text(run, c.version_id, page, TAB_FILES)
    set_picks(run.conn, run.song.id, TAB_KINDS, [c.version_id])
    return int(c.tab_id)


# --- the artist-page route (A6) ----------------------------------------------------------------


@dataclass(frozen=True)
class _Hit:
    """A tab whose listed title is the song's, on an artist page."""

    tab: UGVersion
    key: str  # the listed title's key
    score: float
    fresh: bool  # read from UG this run, not from the cache


def _title_score(forms: list[str], listed: list[str]) -> float:
    """100 for the same title (in either script, in pinyin, or once hyphens go), else rapidfuzz ratio."""
    best = 0.0
    for a in forms:
        for b in listed:
            if a == b or compact(a) == compact(b):
                return 100.0
            best = max(best, fuzz.ratio(a, b))
    return best


def _title_hit(tab: UGVersion, forms: list[str], fresh: bool) -> _Hit | None:
    listed = list(listing_forms(clean_title(tab.song_name)))
    if not listed or not forms:
        return None
    score = _title_score(forms, listed)
    return _Hit(tab, listed[0], score, fresh) if score >= TITLE_MATCH else None


def _best_title(hits: list[_Hit]) -> list[_Hit]:
    """The hits of the song's title: every exact one, else the best fuzzy title when it leads clearly."""
    exact = [h for h in hits if h.score >= 100]
    if exact or not hits:
        return exact
    scores: dict[str, float] = {}
    for h in hits:
        scores[h.key] = max(scores.get(h.key, 0.0), h.score)
    (key, best), *rest = sorted(scores.items(), key=lambda kv: -kv[1])
    if rest and best - rest[0][1] < TITLE_MARGIN:
        return []
    return [h for h in hits if h.key == key]


def _known_artist_page(conn: sqlite3.Connection, keys: list[str], overrides: Overrides) -> str | None:
    """The artist page you pasted under [artist_url] (or the one the tab page you pasted there links
    to, once read), else one learned from a tab page."""
    entry = artist_url_entry(overrides, keys)
    if entry is not None and (page := _pasted_page(conn, entry[1])) is not None:
        return page
    for key in keys:
        if url := learned_artist_url(conn, key):
            return url
    return None


# What reading a tab page you pasted under [artist_url] can find instead of an artist page (the
# to-do page says it, and asks for another page).
PASTE_GONE = "UG answers 404 for it"
PASTE_CLOSED = "robots.txt closes it to caracole"
PASTE_NO_ARTIST = "it doesn't link to its artist's page"
# A tab page you pasted that won't parse, even fetched again, is an error and no verdict: it is asked for
# again on the tab-page rule's dates (UNREADABLE_RETRY), and the to-do page says so meanwhile.
PASTE_UNREADABLE = "UG's copy of it can't be read"


def _pasted_key(tab_id: int) -> str:
    return f"ug:pasted_tab:{tab_id}"


def _pasted_record(conn: sqlite3.Connection, url: str) -> dict | None:
    """What reading the tab page at an [artist_url] address found, once it was read: the artist page
    it links to (``artist_url``), or what is wrong with it (``problem``). None for an artist page."""
    tab_id = pasted_tab_id(url)
    record = kv_get_json(conn, _pasted_key(tab_id)) if tab_id is not None else None
    return record if isinstance(record, dict) else None


def _pasted_page(conn: sqlite3.Connection, url: str) -> str | None:
    """The artist page an [artist_url] address gives: itself, or the one the tab page there links to,
    once that page is read (``_read_pasted_tab_page``)."""
    if pasted_tab_id(url) is None:
        return url
    page = (_pasted_record(conn, url) or {}).get("artist_url")
    return page if isinstance(page, str) and page else None


def _failed_paste(conn: sqlite3.Connection, keys: list[str], overrides: Overrides) -> tuple[str, str] | None:
    """Your [artist_url] address for an artist with these keys and what is wrong with it, when it is a
    tab page that reading showed leads to no artist page."""
    entry = artist_url_entry(overrides, keys)
    problem = (_pasted_record(conn, entry[1]) or {}).get("problem") if entry is not None else None
    return (entry[1], problem) if entry is not None and isinstance(problem, str) and problem else None


def _unread_paste(conn: sqlite3.Connection, keys: list[str], overrides: Overrides) -> tuple[str, str] | None:
    """Your [artist_url] address for an artist with these keys and when caracole asks for it again, when it
    is a tab page not read yet whose page won't parse, even fetched again (kv ``ug:unreadable:<tab id>``)."""
    entry = artist_url_entry(overrides, keys)
    tab_id = pasted_tab_id(entry[1]) if entry is not None else None
    if entry is None or tab_id is None or _pasted_record(conn, entry[1]) is not None:
        return None
    record = kv_get_json(conn, _unreadable_key(tab_id))
    until = record.get("until") if isinstance(record, dict) else None
    return (entry[1], until) if isinstance(until, str) and until else None


def _read_pasted_tab_page(run: _SongRun, keys: list[str]) -> None:
    """Read the tab page you pasted under [artist_url] for the song's artist, once, for the artist page
    it links to, and remember what it said (kv ``ug:pasted_tab:<tab id>``).

    It is a request like any other (budget, pause, robots.txt, block, the cache), and an error leaves
    it to be read next run; a page that won't parse, even fetched again, is asked for again on the
    tab-page rule's dates (``UNREADABLE_RETRY``), whichever song of the artist asks. A bare
    ``/tab/{id}`` of a slugged tab is read at the index's slugged path, where UG serves it. The artist
    page is filed under UG's names for the artist and under your entry's key. A page that gives none
    (gone, closed to caracole, or linking nowhere) is remembered as such: the to-do page asks for
    another one.
    """
    entry = artist_url_entry(run.ctx.overrides, keys)
    if entry is None:
        return
    key, url = entry
    tab_id = pasted_tab_id(url)
    if tab_id is None or _pasted_record(run.conn, url) is not None or _waits(run, tab_id):
        return
    target = url if _slugged_url(url, tab_id) else tab_url_for(run.conn, tab_id)
    artist, problem = None, PASTE_CLOSED  # unless read: robots.txt closes it, or where UG sends it
    if not _closed(target):
        try:
            page, _ = _get_page(run.ctx.client, target, parse_tab_page)
        except RobotsClosed:
            page = None
        except UnreadablePage as e:
            _note_unreadable(run, tab_id, e)
            return
        else:
            kv_delete(run.conn, _unreadable_key(tab_id))
            if page is None:
                problem = PASTE_GONE
            elif (artist := _learn_artist_url(run.conn, page, [key])) is None:
                problem = PASTE_NO_ARTIST
            else:
                problem = None
    if problem is not None:
        log.warning("UG tab page %s, under [artist_url] for %s: %s", url, run.song.artist, problem)
    kv_set_json(run.conn, _pasted_key(tab_id), {"artist_url": artist, "problem": problem, "at": _iso(run.ctx.now)})


def _learn_artist_page(run: _SongRun, keys: list[str]) -> str | None:
    """Read a slugged tab of the artist, from the index, for the artist page it links to.

    The tab is another song's, so none of its versions are recorded for this song.
    A tab whose page robots.txt closes, or redirects to where it does, is passed over.
    """
    for key in keys:
        for tab in artist_tabs(run.conn, key, limit=LEARN_TRIES):
            if _closed(tab.url):
                continue
            try:
                page, _ = _get_page(run.ctx.client, tab.url, parse_tab_page)
            except RobotsClosed:
                continue
            if page is not None and (url := _learn_artist_url(run.conn, page, [key])):
                return url
    return None


def _read_list(run: _SongRun, base: str, kind: str, forms: list[str]) -> tuple[list[_Hit], bool, UGArtistPage | None]:
    """The song's entries in the artist's list of one kind.

    Returns the hits, whether the list was read far enough (False when this
    run's page cap stopped it), and the list's first page (None when UG
    answered 404). Lists are sorted by title, so the title's entries are
    consecutive: reading stops once they end, and goes on to the next page
    only when they reach the end of this one. A page robots.txt closes, or
    redirects to where it does, ends the list, unread.

    Every page read is kept for searches (ug/artist_tabs.py ``store``), and a
    list read to its end, an empty one (404) included, is every tab of its kind
    the artist's page has (``keep_only``): one UG took down goes.
    """
    ctx = run.ctx
    hits: list[_Hit] = []
    first: UGArtistPage | None = None
    fetched, number, last = 0, 1, 1
    kept: list[int] = []
    oldest: str | None = None  # the earliest of the pages' reads
    whole = False
    while number <= last:
        if fetched >= ctx.artist_pages_per_kind:
            return hits, False, first
        url = artist_page_url(base, kind=kind, page=number)
        if _closed(url):
            break
        try:
            page, resp = _read_page(ctx.client, url, parse_artist_page, max_age=ctx.artist_page_max_age,
                                    now=ctx.now)
        except RobotsClosed:
            break
        fresh = not resp.from_cache
        fetched += fresh
        read_at = resp.fetched_at or _iso(ctx.now)
        oldest = min(oldest or read_at, read_at)
        if page is None:
            whole = number == 1  # an empty list may answer 404
            break
        first = first or page
        last = max(last, page.pages)
        listed = [t for t in page.tabs if t.kind == kind]
        _check_links(run, listed, url)
        kept += listed_tabs.store(run.conn, base, page.name, listed, read_at=read_at)
        found = [h for t in listed if (h := _title_hit(t, forms, fresh)) is not None]
        hits += found
        if hits and not (found and found[-1].tab is listed[-1]):
            whole = number >= last
            break
        number += 1
    else:
        whole = True
    if whole and oldest is not None:
        listed_tabs.keep_only(run.conn, base, kind, kept, read_at=oldest)
    return hits, True, first


def _offered_kinds(run: _SongRun, base: str) -> set[str] | None:
    """The kinds of list the artist page offers, read from its unfiltered first page; None when it's
    gone, and none when robots.txt closes it (or the page redirects to where it does)."""
    url = artist_page_url(base)
    if _closed(url):
        return set()
    try:
        page, resp = _read_page(run.ctx.client, url, parse_artist_page,
                                max_age=run.ctx.artist_page_max_age, now=run.ctx.now)
    except RobotsClosed:
        return set()
    if page is None:
        return None
    # Every kind, mixed: kept for searches, and never all of a kind's tabs (a filtered list is).
    listed_tabs.store(run.conn, base, page.name, page.tabs, read_at=resp.fetched_at or _iso(run.ctx.now))
    return set(page.filters) or set(ARTIST_PAGE_KINDS)


@dataclass
class _Listing:
    """What an artist's UG page lists for one song."""

    hits: list[_Hit] = field(default_factory=list)
    name: str = ""  # the artist's name, as UG writes it
    complete: bool = True  # False when this run's page cap cut a list short
    gone: bool = False  # UG answered 404 for the artist page itself


def _read_artist_page(run: _SongRun, base: str, kinds: tuple[str, ...], forms: list[str]) -> _Listing:
    """The song's entries in the artist's lists of these kinds, read in order.

    The first list read tells, from its filter bar, which of the other lists
    the artist has; the rest are skipped. An empty list may answer 404, so the
    unfiltered artist page tells then, and a 404 there too means it is gone.
    """
    listing = _Listing()
    offered: set[str] | None = None
    for kind in kinds:
        if offered is not None and kind not in offered:
            continue
        found, complete, first = _read_list(run, base, kind, forms)
        if not complete:
            listing.complete = False
            return listing
        if first is not None:
            listing.name = listing.name or first.name
            if offered is None and first.filters:
                offered = set(first.filters)
        elif offered is None:
            offered = _offered_kinds(run, base)
            if offered is None:
                listing.gone = True
                return listing
        listing.hits += found
    return listing


def _checked_key(song_id: int) -> str:
    return f"ug:artist_page_checked:{song_id}"


def _mark_checked(run: _SongRun) -> None:
    kv_set(run.conn, _checked_key(run.song.id), _iso(run.ctx.now))


def _artist_page_gone(run: _SongRun, keys: list[str], base: str) -> None:
    log.warning("UG artist page %s answered 404; check [artist_url] for %s", base, run.song.artist)
    for key in keys:
        if learned_artist_url(run.conn, key) == base:
            forget_artist_url(run.conn, key)
    listed_tabs.forget(run.conn, base)  # a search no longer finds what it listed


def _listed_keys(run: _SongRun, tab: UGVersion, artist_name: str) -> tuple[str, str]:
    """The UG keys of a tab on an artist's page: the page's artist (``artist_name``) and the tab's title,
    as the match a hit makes stores them, and as ``[reject]`` names them."""
    artist_key = slug_key(artist_name) or slug_key(tab.artist_name) or run.artist_key
    song_key = slug_key(clean_title(tab.song_name)) or slug_key(clean_title(run.song.title))
    return artist_key, song_key


def _usable_hits(run: _SongRun, hits: list[_Hit], artist_name: str) -> list[_Hit]:
    """The hits of the song's title (see ``_best_title``) that caracole may use.

    A UG song you rejected for the song (``[reject]``, "none of these" in
    ``caracole review``) drops out first, as it does in the matcher: never the
    song, it hides none of the page's other titles either.
    """
    rejected = run.ctx.overrides.reject.get(run.song.key, frozenset())
    allowed = [h for h in hits if _listed_keys(run, h.tab, artist_name) not in rejected]
    return [h for h in _best_title(allowed) if _usable(run, h.tab)]


def _record_hits(run: _SongRun, hits: list[_Hit]) -> None:
    """Record listed tabs as the song's versions; only a list read from UG this run updates ratings."""
    _record(run, (h.tab for h in hits if h.fresh), fresh=True)
    _record(run, (h.tab for h in hits if not h.fresh), fresh=False)


def _accept_artist_page_match(run: _SongRun, hits: list[_Hit], artist_name: str) -> None:
    """Record the matching tabs as the song's versions, and the match itself (step ``artist_page``)."""
    _record_hits(run, hits)
    best = max(hits, key=lambda h: h.score)
    artist_key, song_key = _listed_keys(run, best.tab, artist_name)
    update_song(
        run.conn, run.song.id, match_decision="accept", match_step=ARTIST_PAGE, match_score=best.score,
        match_artist_key=artist_key, match_song_key=song_key, review=False, matched_at=_iso(run.ctx.now),
        match_candidates=[{"artist_key": artist_key, "song_key": song_key, "score": best.score, "step": ARTIST_PAGE}],
        ug_dirty=True,
    )
    run.song = get_song(run.conn, run.song.id)


def _artist_page_route(run: _SongRun) -> bool:
    """Look a not-found song up on its artist's UG page (A6); True when it was found and accepted.

    The page lists bare-id tabs the sitemap index can't see. Its address
    comes from [artist_url] (the artist's page, or one of their tab pages,
    read once for the page it links to), a learned address, or a slugged tab
    of the artist. The chords list is read first; its filter bar tells which
    guitar lists the artist has. A list cut short by the page cap leaves the
    song as it was, for the next run; otherwise the check is recorded, found
    or not. Not found, the song loses what an undone match kept
    (``_drop_undone``). A tab page you pasted that leads to no artist page,
    or can't be read, records no check: the song wasn't looked for, and the
    to-do page says why.
    """
    keys = artist_keys(run.song, run.ctx.overrides)
    _read_pasted_tab_page(run, keys)
    base = _known_artist_page(run.conn, keys, run.ctx.overrides) or _learn_artist_page(run, keys)
    if base is None:
        if _paste_problem(run.conn, keys, run.ctx.overrides) is not None:
            return False
        return _not_on_artist_page(run)
    listing = _read_artist_page(run, base, ARTIST_PAGE_KINDS, name_forms(clean_title(run.song.title)))
    if not listing.complete:
        return False
    if listing.gone:
        _artist_page_gone(run, keys, base)
        return _not_on_artist_page(run)
    best = _usable_hits(run, listing.hits, listing.name)
    if not best:
        return _not_on_artist_page(run)
    _mark_checked(run)
    _accept_artist_page_match(run, best, listing.name)
    return True


def _not_on_artist_page(run: _SongRun) -> bool:
    """The artist's page settled it, for now: the song isn't there. The check is recorded (it is due
    again after ``artist_page_max_age``), and an undone match's files go (``_drop_undone``). False."""
    _mark_checked(run)
    _drop_undone(run)
    return False


def _undone(conn: sqlite3.Connection, song_id: int) -> bool:
    """Whether the song keeps a sheet or a tab from a UG version an earlier match found (``STALE``)."""
    return conn.execute(
        "SELECT 1 FROM files f JOIN versions v ON v.id = f.version_id "
        f"WHERE f.song_id = ? AND v.provider = ? AND v.gone = {STALE} AND f.name IN ({_KEPT_TEXT_MARKS}) LIMIT 1",
        (song_id, PROVIDER, *KEPT_TEXT),
    ).fetchone() is not None


def _drop_undone(run: _SongRun) -> None:
    """A song that has no UG match now (you rejected it, say) loses the sheet and the tab an earlier match
    kept, and their rows (``_drop_left_over``); its status then says what is left: a LaCuerda or an auto
    sheet, or nothing. Guitar Pro files you filed, and files caracole doesn't track, stay; so does every
    file of an ignored song."""
    if _ignored(run.song, run.ctx.overrides) or not _undone(run.conn, run.song.id):
        return
    _drop_left_over(run, SHEET_FILES)
    _drop_left_over(run, TAB_FILES)
    refresh_status(run.conn, run.song.id, ignored=False)
    write_info(run.conn, run.ctx.library_dir, get_song(run.conn, run.song.id))


def _matched_artist_keys(run: _SongRun) -> list[str]:
    """The UG artist keys of a matched song: its match's first, then its own artists'."""
    keys = [run.song.match_artist_key or "", *artist_keys(run.song, run.ctx.overrides)]
    return [k for k in dict.fromkeys(keys) if k]


def _matched_title_forms(song: Song) -> list[str]:
    """The keys a matched song's title may be listed under: its own title's, then its match's."""
    forms = [*name_forms(clean_title(song.title)), song.match_song_key or ""]
    return [f for f in dict.fromkeys(forms) if f]


def _learn_from_own_tabs(run: _SongRun, tabs: Sequence[IndexTab], keys: list[str]) -> str | None:
    """Read the song's own slugged tabs, which its guitar slots need anyway, for the artist page."""
    for tab in tabs[:LEARN_TRIES]:
        page = _page(run, tab.tab_id, tab.url, tab.type)
        if page is not None and (url := _known_artist_page(run.conn, keys, run.ctx.overrides)):
            return url
    return None


def _artist_page_versions(run: _SongRun, kinds: tuple[str, ...], own: Sequence[IndexTab] = ()) -> bool:
    """Read a matched song's entries in its artist's UG lists of these kinds, as its versions.

    For tabs the index can't watch, because they are bare ids: every list of a
    song accepted on its artist's page (fresh ratings, versions added since),
    or the chords list of a song whose index tabs hold no chords. The page's
    address comes from [artist_url] or a learned one, else from a tab page:
    the song's own index tabs (``own``) first, then the artist's others.
    ``songs_to_fetch`` brings these songs back once ``artist_page_max_age``
    has passed; the 30-day cache serves the lists in between, one request per
    artist. The match stands whatever the lists say. False when this run's
    page cap cut a list short: the song waits for the next run, as it was.

    The check is recorded once the lists are read, before the slots are
    filled, so the song is marked dirty first: a recheck the budget or an
    error cuts short resumes next run, and ``_finish`` makes it clean.
    """
    update_song(run.conn, run.song.id, ug_dirty=True)
    keys = _matched_artist_keys(run)
    _read_pasted_tab_page(run, keys)
    base = (_known_artist_page(run.conn, keys, run.ctx.overrides) or _learn_from_own_tabs(run, own, keys)
            or _learn_artist_page(run, keys))
    if base is not None:
        listing = _read_artist_page(run, base, kinds, _matched_title_forms(run.song))
        if not listing.complete:
            return False
        if listing.gone:
            _artist_page_gone(run, keys, base)
        else:
            _record_hits(run, _usable_hits(run, listing.hits, listing.name))
    _mark_checked(run)
    return True


def _song_index_tabs(conn: sqlite3.Connection, song: Song, block: frozenset[int]) -> list[IndexTab]:
    """The song's tabs in the index, under its match's keys; blocked ones left out, and ones whose
    page robots.txt closes."""
    tabs = song_tabs(conn, song.match_artist_key, song.match_song_key) if song.match_song_key else []
    return [t for t in tabs if t.tab_id not in block and not _closed(t.url)]


def _live_chords(conn: sqlite3.Connection, song: Song, tabs: list[IndexTab]) -> list[IndexTab]:
    """The chords tabs among the song's index ``tabs`` that UG hasn't since answered 404 for."""
    gone = {
        int(r.tab_id) for r in song_versions(conn, song.id, kinds=CHORDS_KINDS, include_gone=True)
        if r.provider == PROVIDER and r.gone
    }
    return [t for t in tabs if t.type in CHORDS_KINDS and t.tab_id not in gone]


# --- one song, and a run ---------------------------------------------------------------------------


def process_song(ctx: FetchContext, song: Song, *, guitar: bool = True) -> SongFetchOutcome:
    """Fetch, rank and keep one song's UG versions, one slot at a time.

    A not-found song is first looked up on its artist's UG page (A6), and goes
    on only when it is found there. A song found there before has its lists
    read again first (from the cache within 30 days), for fresh ratings and new
    versions; a song whose index tabs hold no chords (bare ids) has its sheet
    candidates read from its artist's chords list. Each kind group is rated and
    its slot filled before the next group is touched, so the sheet a singer
    needs most is settled before the budget goes to guitar parts. Any other
    song without a match (a review of other UG songs) only loses what an
    undone match kept (``_drop_undone``), with no request.
    """
    start = ctx.client.requests_made
    run = _SongRun(ctx, song)

    def unfinished() -> SongFetchOutcome:
        return SongFetchOutcome(song.id, None, (), None, ctx.client.requests_made - start)

    if needs_artist_page(song):
        if not _artist_page_route(run):
            return unfinished()
        song = run.song
    elif song.match_decision not in ("accept", "pinned"):
        _drop_undone(run)
        return unfinished()
    elif song.match_step == ARTIST_PAGE and not _artist_page_versions(run, ARTIST_PAGE_KINDS):
        return unfinished()
    tabs = _song_index_tabs(ctx.conn, song, ctx.overrides.block)
    pinned = _fetch_pins(run, _pins(ctx.overrides, song))

    def rated(group: tuple[str, ...]) -> list[int] | None:
        if group not in pinned:
            pages = ctx.max_pages_per_group if group == CHORDS_KINDS else ctx.guitar_pages_per_group
            for kind in group:  # UG lists versions per type: a Guitar Pro page never rates a Power Tab
                _rate_group(run, [t for t in tabs if t.type == kind], pages)
        return pinned.get(group)

    sheet_pins = rated(CHORDS_KINDS)
    if sheet_pins is None and song.match_step != ARTIST_PAGE and not _live_chords(ctx.conn, song, tabs):
        own = [t for t in tabs if t.type not in CHORDS_KINDS]
        if not _artist_page_versions(run, CHORDS_KINDS, own):
            return unfinished()
    sheet = _sheet_slot(run, sheet_pins)
    if not guitar:
        # The sheet pass of fetch_songs: the song stays dirty until its guitar slots are done.
        return SongFetchOutcome(song.id, sheet, (), None, ctx.client.requests_made - start, settled=True)
    guitar_pro = _guitar_pro_slot(run, rated(GUITAR_PRO_KINDS))
    tab = _tab_slot(run, rated(TAB_KINDS))
    _finish(run)
    return SongFetchOutcome(song.id, sheet, guitar_pro, tab, ctx.client.requests_made - start, settled=True)


def _finish(run: _SongRun) -> None:
    """Every slot is done: refresh the status, mark the song checked, and describe it in info.json.

    A song with a page that couldn't be read is neither checked nor clean (an
    error is never a miss): it is fetched again, from the cache, until that
    page is due and read. The tabs [block] left out are remembered, so that
    taking one out of [block] brings the song back (``songs_to_fetch``).
    """
    refresh_status(run.conn, run.song.id, ignored=False)
    if run.unreadable:
        update_song(run.conn, run.song.id, ug_dirty=True)
    else:
        update_song(run.conn, run.song.id, ug_dirty=False, ug_checked_at=_iso(run.ctx.now))
    left_out = _left_out(run)
    if left_out:
        kv_set_json(run.conn, _left_out_key(run.song.id), left_out)
    else:
        kv_delete(run.conn, _left_out_key(run.song.id))
    write_info(run.conn, run.ctx.library_dir, get_song(run.conn, run.song.id))


def _left_out_key(song_id: int) -> str:
    return f"ug:blocked:{song_id}"


def _left_out(run: _SongRun) -> list[int]:
    """The tabs you have blocked among the song's: its UG versions, its index tabs and its pins."""
    block = run.ctx.overrides.block
    if not block:
        return []
    song = run.song
    ids = {
        int(r.tab_id) for r in song_versions(run.conn, song.id, include_gone=True)
        if r.provider == PROVIDER and not r.stale  # an earlier match's: no candidate, blocked or not
    }
    ids |= {t.tab_id for t in _song_index_tabs(run.conn, song, frozenset())}
    ids |= set(run.ctx.overrides.pin.get(song.key, ()))
    return sorted(ids & block)


def _block_changed(conn: sqlite3.Connection, song: Song, block: frozenset[int]) -> bool:
    """Whether [block] changed for the song since its fetch finished.

    That is a tab it keeps (as ``sheet.txt`` or ``tab.txt``) or picks that
    you have blocked since, or a tab the fetch left out that you no longer
    block.
    """
    left_out = kv_get_json(conn, _left_out_key(song.id), default=[]) or []
    if any(t not in block for t in left_out):
        return True
    if not block:
        return False
    rows = conn.execute(
        "SELECT v.tab_id FROM versions v WHERE v.song_id = ? AND v.provider = ? AND (v.pick_rank IS NOT NULL "
        f"OR EXISTS (SELECT 1 FROM files f WHERE f.version_id = v.id AND f.name IN ({_KEPT_TEXT_MARKS})))",
        (song.id, PROVIDER, *KEPT_TEXT),
    )
    return any(int(r[0]) in block for r in rows)


def _last_checked(conn: sqlite3.Connection, song_id: int) -> datetime | None:
    """When the song was last looked up on its artist's UG page, if ever."""
    value = kv_get(conn, _checked_key(song_id))
    return _parse_iso(value) if value is not None else None


def _checked_within(conn: sqlite3.Connection, song_id: int, now: datetime, max_age: timedelta) -> bool:
    checked = _last_checked(conn, song_id)
    return checked is not None and now - checked < max_age


def _recheck_due(
    conn: sqlite3.Connection, song: Song, overrides: Overrides, now: datetime, max_age: timedelta
) -> bool:
    """Whether an accepted song is due to have its artist's UG page read again.

    That is a song accepted there, or one whose index tabs hold no chords, once
    ``max_age`` has passed since the page was last read for it.
    """
    if song.match_decision != "accept":
        return False
    checked = _last_checked(conn, song.id)
    if checked is None or now - checked < max_age:
        return False
    return song.match_step == ARTIST_PAGE or not _live_chords(
        conn, song, _song_index_tabs(conn, song, overrides.block)
    )


def _ignored(song: Song, overrides: Overrides) -> bool:
    return song.status == "ignored" or song.match_decision == "ignored" or song.key in overrides.ignore


def needs_artist_page(song: Song) -> bool:
    """Whether the index can't settle this song, so its artist's UG page should be read (A6).

    That is a not-found song, or a review whose only candidates come from the steps that never
    accept (``match.REVIEW_ONLY_STEPS``): other artists' songs of the same title (on the real
    index Soda Stereo's "De Música Ligera", every tab a bare id, reviews as a Portuguese cover),
    and names that aren't quite UG's.
    """
    if song.match_decision == "not_found":
        return True
    candidates = song.match_candidates or []
    return song.match_decision == "review" and bool(candidates) and all(
        c.get("step") in REVIEW_ONLY_STEPS for c in candidates
    )


def songs_to_fetch(
    conn: sqlite3.Connection,
    overrides: Overrides,
    now: datetime,
    *,
    artist_page_max_age: timedelta = ARTIST_PAGE_MAX_AGE,
) -> list[Song]:
    """The songs this run should fetch, newest first.

    - Accepted or pinned songs that are dirty (new match, new tabs, or a run
      that stopped half-way), or whose [block] changed since their fetch: a
      tab they keep or pick is blocked now, or one left out is no longer.
    - Not-found songs whose artist is known (A6), so that its UG artist page,
      which lists bare-id tabs the index can't see, is searched for the
      title, at most once per ``artist_page_max_age``.
    - Accepted songs whose versions come from their artist's UG page, once
      ``artist_page_max_age`` has passed since it was last read for them: the
      songs accepted there, and the songs whose chords the index lists only
      as bare ids. No index refresh can make those dirty, so this is how they
      get fresh ratings and new versions.
    - Songs whose UG match was undone (you rejected it, say) that still keep a
      sheet or a tab that match found: unless their artist's page finds them
      again, those go (``process_song``).
    """
    return [song for song in list_songs(conn)
            if fetch_due(conn, song, overrides, now, artist_page_max_age=artist_page_max_age)]


def fetch_due(
    conn: sqlite3.Connection,
    song: Song,
    overrides: Overrides,
    now: datetime,
    *,
    artist_page_max_age: timedelta = ARTIST_PAGE_MAX_AGE,
) -> bool:
    """Whether this run should fetch the song: ``songs_to_fetch``, for one song."""
    if _ignored(song, overrides):
        return False
    matched = song.match_decision in ("accept", "pinned")
    dirty = matched and (song.ug_dirty or _block_changed(conn, song, overrides.block))
    due = (
        needs_artist_page(song)
        and not _checked_within(conn, song.id, now, artist_page_max_age)
        and artist_is_known(conn, song, overrides)
    )
    undone = not matched and _undone(conn, song.id)
    return dirty or due or undone or _recheck_due(conn, song, overrides, now, artist_page_max_age)


def checked_since(conn: sqlite3.Connection, song: Song, since: datetime) -> bool:
    """Whether a fetch settled the song at ``since`` or after, so what it lacks now, UG lacks.

    A matched song is settled once its fetch finished (``ug_checked_at``, which
    a block, a spent budget or an error never sets); a song with no match yet,
    once its artist's UG page was read for it. Both are written to the second.
    """
    since = since.astimezone(UTC).replace(microsecond=0)
    if song.ug_checked_at:
        try:
            if _parse_iso(song.ug_checked_at) >= since:
                return True
        except ValueError:
            pass
    if song.match_decision in ("accept", "pinned"):
        return False
    checked = _last_checked(conn, song.id)
    return checked is not None and checked >= since


# --- a lookup while the nightly run waits ---------------------------------------------------------------

_LOOKED_UP = "lookup:songs"  # the last songs ``caracole get`` fetched, newest last
_LOOKED_UP_KEPT = 50


def note_looked_up(conn: sqlite3.Connection, song_id: int) -> None:
    """Note that a lookup (``caracole get``) fetched the song, for bulk work that handed it the lock."""
    ids = [i for i in kv_get_json(conn, _LOOKED_UP, default=[]) or [] if i != song_id]
    kv_set_json(conn, _LOOKED_UP, [*ids, song_id][-_LOOKED_UP_KEPT:])


def _looked_up(conn: sqlite3.Connection) -> set[int]:
    return set(kv_get_json(conn, _LOOKED_UP, default=[]) or [])


class _Handoffs:
    """What a fetch run must know once its client handed caracole's lock to a lookup (commands/_common.py).

    The lookup may have fetched songs this run listed, or pinned one in
    overrides.toml: after a handoff, overrides.toml is read again
    (``FetchContext.reload_overrides``), and each song is read again before its
    turn and skipped when nothing is left to do for it. A song the lookup
    fetched while this run was in the middle of it goes back to be fetched
    next run, since what this run kept was decided on what it had read before.
    """

    def __init__(self, ctx: FetchContext):
        self.ctx = ctx
        self.seen = self.count()
        self.since = False  # whether the lock was handed over during this run

    def count(self) -> int:
        return int(getattr(self.ctx.client, "handoffs", 0) or 0)

    def current(self, song: Song) -> Song | None:
        """The song to fetch now: itself, or after a handoff as it is now; None when there's nothing to do."""
        count = self.count()
        if count != self.seen:
            self.seen, self.since = count, True
            if self.ctx.reload_overrides is not None:
                try:
                    self.ctx.overrides = self.ctx.reload_overrides()
                except Exception as e:  # noqa: BLE001 (a file you are editing: the one read at the start stays)
                    log.info("overrides.toml couldn't be read again (%s); the fetch goes on with what it read.", e)
        if not self.since:
            return song
        try:
            fresh = get_song(self.ctx.conn, song.id)
        except KeyError:  # merged into another song meanwhile
            return None
        ctx = self.ctx
        due = fetch_due(ctx.conn, fresh, ctx.overrides, ctx.now, artist_page_max_age=ctx.artist_page_max_age)
        return fresh if due else None

    def after(self, song: Song, before: int) -> None:
        """A song a lookup fetched during this run's turn for it goes back to be fetched next run."""
        if self.count() != before and song.id in _looked_up(self.ctx.conn):
            update_song(self.ctx.conn, song.id, ug_dirty=True)


def fetch_songs(
    ctx: FetchContext,
    songs: Iterable[Song],
    *,
    on_song: Callable[[Song, SongFetchOutcome], None] | None = None,
) -> FetchStats:
    """Fetch songs in order until the budget is spent; ``on_song`` hears about each song done.

    Two passes: first the sheet of every song (what a singer needs most), then,
    with what's left of the budget, the guitar slots of the songs whose sheet
    was settled. The second pass re-reads the sheet pages from the HTTP cache,
    so it pays only for guitar parts.

    A block is re-raised (the caller cools the provider down). Any other
    provider error, a page that can't be parsed included, skips that song: it
    stays dirty and is never marked not found.

    Once the client hands caracole's lock to a lookup in one of its pauses,
    each song is read again before its turn (``_Handoffs``).
    """
    stats = FetchStats()
    handed = _Handoffs(ctx)
    settled: list[tuple[Song, int]] = []  # with the requests its sheet pass cost
    # Once the budget is spent each song still runs until its first uncached request, so
    # songs whose pages are cached are settled (and finished) for free.
    for listed in songs:
        done = _fetch_turn(ctx, handed, stats, listed, guitar=False)
        if done is None:
            continue
        song, outcome = done
        if outcome.settled:
            stats.sheets_done += 1
            settled.append((song, outcome.requests))
        else:
            stats.songs_done += 1  # nothing more to do this run (not on its artist page, say)
            if on_song is not None:
                on_song(song, outcome)
    for listed, sheet_requests in settled:
        done = _fetch_turn(ctx, handed, stats, listed, guitar=True)
        if done is None:
            continue
        song, outcome = done
        stats.songs_done += 1
        if on_song is not None:
            on_song(song, replace(outcome, requests=outcome.requests + sheet_requests))
    return stats


def _fetch_turn(
    ctx: FetchContext, handed: _Handoffs, stats: FetchStats, listed: Song, *, guitar: bool
) -> tuple[Song, SongFetchOutcome] | None:
    """One song's turn in one pass of ``fetch_songs``: the song and what it did, or None when there is
    nothing to count (a handoff left it nothing to do, the budget ran out, or UG failed for it).

    A block is re-raised; any other provider error skips the song, which stays dirty."""
    song = handed.current(get_song(ctx.conn, listed.id) if guitar else listed)
    if song is None:
        return None
    before = handed.count()
    try:
        outcome = process_song(ctx, song, guitar=guitar)
    except BudgetExhausted:
        stats.budget_exhausted = True
        return None
    except ProviderBlocked:
        raise
    except ProviderError as e:
        log.debug("UG fetch failed for %s: %s", song.display, e)
        stats.songs_failed += 1
        stats.failures.append((song, e))
        return None
    handed.after(song, before)
    return song, outcome


# --- sheets kept before their lyrics ---------------------------------------------------------------


def rescore_kept_sheets(conn: sqlite3.Connection, library_dir: Path, rank: RankPolicy) -> int:
    """Score the kept sheets that have no coverage because their song had no lyrics yet; return how many.

    A sheet kept before LRCLIB answered has an unknown coverage forever
    otherwise: it never shows as partial on the to-do page, and only a complete
    sheet may replace it. Once its song has lyrics, the sheet's markup (the
    ``content`` of the ``sheet.json`` kept beside it, from UG or LaCuerda) is
    scored as the fetch would have scored it. No request is made. A sheet that
    proves complete retires the auto-chords sheet, as it would have on keeping.

    A sheet that proves partial was chosen on rating alone, so its song is
    marked dirty when it has UG sheets that coverage never ranked: the next
    fetch ranks them again, from the cached pages.

    First, as the nightly run calls this before fetching, a song whose kept UG
    sheet or tab the library lost is sent back to the fetch (``_send_back_lost``).
    """
    _send_back_lost(conn, library_dir)
    rows = conn.execute(
        "SELECT f.song_id, f.version_id FROM files f JOIN versions v ON v.id = f.version_id "
        "WHERE f.name = ? AND v.coverage IS NULL ORDER BY f.song_id",
        (SHEET_FILES[0],),
    ).fetchall()
    scored = 0
    for row in rows:
        song = get_song(conn, row["song_id"])
        lines = _lyric_lines(song)
        content = _kept_markup(conn, library_dir, song, row["version_id"]) if lines else None
        if content is None:
            continue
        value = coverage.coverage(content, lines, line_match=rank.line_match)
        set_coverage(conn, row["version_id"], value)
        if complete(value, rank.coverage_threshold):
            _retire_auto_sheet(conn, library_dir, song)
        elif _unranked_rivals(conn, song.id, row["version_id"]):
            update_song(conn, song.id, ug_dirty=True)
        write_info(conn, library_dir, song)
        scored += 1
    return scored


def _send_back_lost(conn: sqlite3.Connection, library_dir: Path) -> None:
    """Mark dirty each clean, accepted or pinned song whose kept UG sheet or tab the library lost.

    That is a file no longer as kept (``library.holds``): deleted on a synced
    device, cut short by a power cut, or a link in its place. The database alone
    would have the fetch skip it forever; this way the next fetch writes it
    again (``_keep``), from the cached page. Only a live version's file counts,
    as only its page can give it back, and never a Guitar Pro file, which is
    yours to download (assisted mode). Each file is hashed; the files table
    keeps no length to compare first.
    """
    rows = conn.execute(
        "SELECT f.song_id, f.path, f.sha256 FROM files f JOIN versions v ON v.id = f.version_id "
        f"JOIN songs s ON s.id = f.song_id WHERE v.provider = ? AND v.gone = {LIVE} AND f.name IN ({_KEPT_TEXT_MARKS}) "
        "AND s.match_decision IN ('accept', 'pinned') AND s.ug_dirty = 0 AND s.status != 'ignored'",
        (PROVIDER, *KEPT_TEXT),
    ).fetchall()
    for song_id in sorted({r["song_id"] for r in rows if not holds(library_dir / r["path"], r["sha256"])}):
        update_song(conn, song_id, ug_dirty=True)


def _unranked_rivals(conn: sqlite3.Connection, song_id: int, kept_id: int) -> bool:
    """Whether the song has live UG sheets besides the kept one that lyric coverage hasn't ranked."""
    return any(
        r.provider == PROVIDER and r.id != kept_id and r.coverage is None
        for r in song_versions(conn, song_id, kinds=CHORDS_KINDS)
    )


def _kept_markup(conn: sqlite3.Connection, library_dir: Path, song: Song, version_id: int) -> str | None:
    """The markup in the song's kept ``sheet.json``, if it is that version's and can be read.

    It is read only as a regular file, never through a link (``library.read_json``):
    whatever another device planted there instead is no sheet, as a missing one is.
    """
    doc_file = next((f for f in kept_files(conn, song.id) if f.name == SHEET_FILES[1]), None)
    if doc_file is None or doc_file.version_id != version_id:
        return None
    path = library_dir / doc_file.path
    try:
        doc = read_json(path)
    except (OSError, ValueError) as e:  # ValueError: not UTF-8, not JSON, or nested too deep
        log.warning("cannot score %s: %s", path, e)
        return None
    content = doc.get("content") if isinstance(doc, dict) else None
    return content if isinstance(content, str) else None
