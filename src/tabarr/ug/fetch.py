"""Per-song Ultimate Guitar fetch: rate every version, keep the best sheet, pick guitar parts.

For each song (plan §3, Task 15, amendment A6):

1. **Candidates.** The song's tabs in the local index, fetched at their
   slugged URLs (UG answers 404 for a slugged tab at the bare ``/tab/{id}``),
   and its pins, which replace the kind group they belong to and are fetched
   at the slugged address you pasted, if you pasted one. Blocked ids never
   compete. A not-found song is looked up on its artist's UG page, which also
   lists the bare-id tabs the index can't see (A6).
2. **Ratings.** A tab page lists the other versions of its type and part, so
   for each kind group (chords; Guitar Pro and Power Tab; tabs) tabarr reads
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

A kept file is replaced only when another version outranks it, and is not
rewritten when it wins again.

``rescore_kept_sheets`` scores the sheets kept before their song had lyrics,
without a request; the nightly run calls it before fetching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from rapidfuzz import fuzz

from tabarr import coverage
from tabarr.config import RankPolicy
from tabarr.db import kv_get, kv_set
from tabarr.http import BudgetExhausted, Client, ProviderBlocked, ProviderError, Response
from tabarr.library import drop_file, keep_file, kept_files, write_info
from tabarr.lyrics import song_lyrics
from tabarr.normalize import clean_title, compact, has_han, romanize, slug_key
from tabarr.overrides import Overrides
from tabarr.rank import Candidate, is_complete, rank_by_rating, rank_guitar, rank_sheets
from tabarr.songs import Song, get_song, list_songs, refresh_status, update_song
from tabarr.ug.artist import WWW, UGArtistPage, artist_page_url, parse_artist_page
from tabarr.ug.lookup import (
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
from tabarr.ug.page import (
    TAB_BASE_URL,
    PageParseError,
    UGTabPage,
    UGVersion,
    parse_tab_page,
    strip_markup,
)
from tabarr.versions import (
    SHEET_KINDS,
    VersionRow,
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
SHEET_FILES = ("sheet.txt", "sheet.json")
TAB_FILES = ("tab.txt", "tab.json")
AUTO_SHEET = "sheet (auto).txt"
_TAB_HOST = urlsplit(TAB_BASE_URL).netloc
_CLOSED_TAB_PATHS = frozenset({"download", "print"})  # robots.txt on the tabs host

# The artist-page route (A6).
ARTIST_PAGE = "artist_page"  # the match step of a song found on its artist's page
ARTIST_PAGE_MAX_AGE = timedelta(days=30)
ARTIST_PAGE_KINDS = ("chords", "guitar-pro", "power", "tabs")  # the sheet's list first
TITLE_MATCH = 90  # rapidfuzz ratio of title keys, the matcher's accept score
TITLE_MARGIN = 8  # a fuzzy title must lead the next different title by this much
LEARN_TRIES = 3  # slugged tabs read at most to learn an artist's page
_ARTIST_PATH = re.compile(r"/artist/[^/?#]+_\d+")


@dataclass
class FetchContext:
    """Everything one fetch run needs. ``client`` is the run's UG client.

    ``artist_pages_per_kind`` caps the artist-page list pages one song may
    fetch from UG per kind per run; cached pages don't count, so a long list
    is read over several runs.
    """

    conn: sqlite3.Connection
    client: Client
    overrides: Overrides
    rank: RankPolicy
    library_dir: Path
    now: datetime
    max_pages_per_group: int = 3
    artist_page_max_age: timedelta = ARTIST_PAGE_MAX_AGE
    artist_pages_per_kind: int = 3


@dataclass(frozen=True)
class SongFetchOutcome:
    """What one song's fetch kept: UG tab ids of the sheet, the Guitar Pro picks and the text tab.

    ``requests`` counts the requests sent to UG for the song (cache hits are free).
    """

    song_id: int
    sheet: int | None
    guitar_pro: tuple[int, ...]
    tab: int | None
    requests: int


@dataclass
class FetchStats:
    """A fetch run: songs finished, songs skipped after a provider error, and whether the budget ran out."""

    songs_done: int = 0
    songs_failed: int = 0
    budget_exhausted: bool = False


@dataclass
class _SongRun:
    """One song's fetch: the song, and the tab pages already read for it this run."""

    ctx: FetchContext
    song: Song
    pages: dict[int, UGTabPage | None] = field(default_factory=dict)

    @property
    def conn(self) -> sqlite3.Connection:
        return self.ctx.conn

    @property
    def artist_key(self) -> str:
        """The UG artist key the song is filed under: its match, else its own artist's key."""
        return self.song.match_artist_key or slug_key(self.song.artist)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slot(kind: str) -> str:
    return "sheet" if kind in SHEET_KINDS else "guitar"


# --- artist keys ------------------------------------------------------------------------------


def _name_keys(name: str) -> list[str]:
    """A name's keys: its slug key, plus its pinyin key when it is Chinese."""
    keys = [slug_key(name)]
    if has_han(name):
        keys.append(slug_key(romanize(name)))
    return [k for k in dict.fromkeys(keys) if k]


def artist_keys(song: Song, overrides: Overrides) -> list[str]:
    """The UG artist keys a song may be listed under: [alias] first, then each artist's own keys."""
    keys: list[str] = []
    for name in song.artists or [song.artist]:
        keys += overrides.alias.get(slug_key(name), ())
        keys += _name_keys(name)
    return [k for k in dict.fromkeys(keys) if k]


def artist_is_known(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> bool:
    """Whether the song's artist page can be found: pasted in [artist_url], learned, or in the index."""
    return any(
        k in overrides.artist_url or learned_artist_url(conn, k) or artist_known(conn, k)
        for k in artist_keys(song, overrides)
    )


# --- pages and versions ---------------------------------------------------------------------------


def _get_page[P: (UGTabPage, UGArtistPage)](
    client: Client, url: str, parse: Callable[..., P], *, max_age: timedelta | None = None
) -> tuple[P | None, bool]:
    """A UG page from the HTTP cache or UG (None when UG answers 404), and whether it was fetched now.

    UG's 404 page has no js-store, so the status is checked before parsing.
    A 200 is cached (tab pages forever), so a cached body that no longer
    parses (a truncated or maintenance page) is fetched once more instead of
    failing the song on every run.
    """

    def parsed(resp: Response) -> P | None:
        return None if resp.status == 404 else parse(resp.content, url=url)

    resp = client.get(url, accept=_PAGE_ACCEPT, max_age=max_age)
    try:
        return parsed(resp), not resp.from_cache
    except PageParseError:
        if not resp.from_cache:
            raise
    return parsed(client.get(url, accept=_PAGE_ACCEPT, cache=False)), True


def _upsert(run: _SongRun, v: UGVersion) -> int:
    assert v.kind is not None
    return upsert_version(
        run.conn, provider=PROVIDER, tab_id=str(v.tab_id), song_id=run.song.id, slot=_slot(v.kind), kind=v.kind,
        rating=v.rating, votes=v.votes, version=v.version, label=v.label, url=v.url, raw=v.raw,
        now=_iso(run.ctx.now),
    )


def _tab_page_url(url: str) -> bool:
    """Whether a link from UG's JSON is a plain tab page; robots.txt closes /tab/download and /tab/print."""
    parts = urlsplit(url)
    segments = parts.path.split("/")
    return (
        parts.scheme in ("http", "https") and parts.netloc == _TAB_HOST
        and len(segments) > 2 and segments[1] == "tab" and segments[2] not in _CLOSED_TAB_PATHS
    )


def _usable(run: _SongRun, v: UGVersion) -> bool:
    """A kind tabarr uses (never Official, which UG marks public too), public, not blocked, at a tab page."""
    return (
        v.kind is not None and v.access == "public" and v.tab_id not in run.ctx.overrides.block
        and _tab_page_url(v.url)
    )


def _known(run: _SongRun, tab_id: int) -> bool:
    return run.conn.execute(
        "SELECT 1 FROM versions WHERE provider = ? AND tab_id = ? AND song_id = ?", (PROVIDER, str(tab_id), run.song.id)
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


def _record_page(run: _SongRun, page: UGTabPage, *, fresh: bool) -> None:
    """Record the page's own tab and the versions it lists of the same kind group."""
    group = _GROUP_OF.get(page.tab.kind or "")
    if group is not None:
        _record(run, (v for v in (page.tab, *page.versions) if v.kind in group), fresh=fresh)


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
    """A UG artist page address (``https://www.ultimate-guitar.com/artist/<name>_<id>``), else None."""
    if not url:
        return None
    parts = urlsplit(urljoin(WWW + "/", url.strip()))
    path = parts.path.rstrip("/")
    if parts.netloc != urlsplit(WWW).netloc or not _ARTIST_PATH.fullmatch(path):
        return None
    return urlunsplit(("https", parts.netloc, path, "", ""))


def _same_artist(key: str, name: str) -> bool:
    return compact(key) in {compact(k) for k in _name_keys(name)}


def _learn_artist_url(conn: sqlite3.Connection, page: UGTabPage, also: Iterable[str] = ()) -> str | None:
    """Remember the artist page a tab page links to, under its artist's keys and ``also``; return it."""
    url = _artist_page_base(page.artist_url)
    if url is not None:
        for key in dict.fromkeys([*_name_keys(page.tab.artist_name), *also]):
            remember_artist_url(conn, key, url)
    return url


def _page(run: _SongRun, tab_id: int, url: str, kind: str | None = None) -> UGTabPage | None:
    """A tab page of this song, read once per run; None when UG says it's gone.

    ``kind`` (the index's type) lets a deleted tab that was never rated be
    remembered as gone. Every page also teaches tabarr its artist's UG page,
    filed under the song's artist only when the tab is by that artist.
    """
    if tab_id in run.pages:
        return run.pages[tab_id]
    page, fresh = _get_page(run.ctx.client, url, parse_tab_page)
    run.pages[tab_id] = page
    if page is None:
        _mark_gone(run, tab_id, url, kind)
        return None
    _record_page(run, page, fresh=fresh)
    mine = run.artist_key
    _learn_artist_url(run.conn, page, [mine] if mine and _same_artist(mine, page.tab.artist_name) else [])
    return page


# --- ratings and pins -------------------------------------------------------------------------------


def _seen_ids(run: _SongRun) -> set[int]:
    return {int(r.tab_id) for r in song_versions(run.conn, run.song.id, include_gone=True) if r.provider == PROVIDER}


def _rate_group(run: _SongRun, tabs: list[IndexTab]) -> None:
    """Read the page of the lowest unrated id until all are rated or the page cap is reached."""
    tried: set[int] = set()
    for _ in range(run.ctx.max_pages_per_group):
        seen = _seen_ids(run)
        todo = sorted((t for t in tabs if t.tab_id not in seen and t.tab_id not in tried), key=lambda t: t.tab_id)
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
    pasted comes first, unless robots.txt closes it. A bare ``/tab/{id}`` you
    pasted adds nothing: then UG's own link to the tab, else the index's path,
    else the bare page.
    """
    if pasted is not None and _tab_page_url(pasted) and _slugged_url(pasted, tab_id):
        return pasted
    return row.url if row is not None else tab_url_for(run.conn, tab_id)


def _fetch_pins(run: _SongRun, pins: list[tuple[int, str | None]]) -> dict[tuple[str, ...], list[int]]:
    """Read every pinned page; return the pinned ids of each kind group, in pinned order.

    A pin's kind comes from its page. A pin whose page is gone, Official or not
    public pins nothing.
    """
    groups: dict[tuple[str, ...], list[int]] = {}
    for tab_id, pasted in pins:
        row = _version_row(run, tab_id)
        known = index_tab(run.conn, tab_id)
        url = _pinned_url(run, tab_id, pasted, row)
        kind = row.kind if row is not None else known.type if known is not None else None
        page = _page(run, tab_id, url, kind)
        if page is None or not _usable(run, page.tab):
            continue
        groups.setdefault(_GROUP_OF[page.tab.kind], []).append(page.tab.tab_id)
    return groups


# --- the slots ---------------------------------------------------------------------------------------


def _rows(run: _SongRun, kinds: tuple[str, ...]) -> list[VersionRow]:
    """The song's live UG versions of these kinds; blocked ids never compete, even if seen earlier."""
    block = run.ctx.overrides.block
    return [
        r for r in song_versions(run.conn, run.song.id, kinds=kinds)
        if r.provider == PROVIDER and int(r.tab_id) not in block
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
    """A version's page with its text, or None when the page is gone."""
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
    """Keep one file, unless this version's identical bytes are kept already (no churn for Syncthing)."""
    sha = hashlib.sha256(data).hexdigest()
    if any(f.name == name and f.version_id == version_id and f.sha256 == sha
           for f in kept_files(run.conn, run.song.id)):
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


def _drop_if_blocked(run: _SongRun, names: tuple[str, str]) -> None:
    """Files kept from a UG version you have blocked since go, even when nothing replaces them."""
    kept = _kept_version(run.conn, run.song.id, names[0])
    if kept is not None and kept.provider == PROVIDER and int(kept.tab_id) in run.ctx.overrides.block:
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
    always wins. The sheet kept becomes the slot's only pick, and a complete
    one retires the auto-chords sheet.
    """
    policy = run.ctx.rank
    rows = _rows(run, CHORDS_KINDS)
    lines = _lyric_lines(run.song)
    by_id = {r.id: r for r in rows}
    pages: dict[int, UGTabPage] = {}

    def scored(c: Candidate) -> bool:
        """Fetch the sheet and score its coverage; False when its page is gone."""
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
                continue  # gone; the next one is scored instead
            alive.append(c)
        ranked = rank_sheets(alive, policy, variant=run.song.variant)
    best = _first_with_text(run, ranked, rows, pages)
    if best is None:
        set_picks(run.conn, run.song.id, CHORDS_KINDS, [])
        _drop_if_blocked(run, SHEET_FILES)
        return None
    c, page = best
    assert c.version_id is not None
    kept = _kept_version(run.conn, run.song.id, SHEET_FILES[0])
    if (kept is not None and kept.provider != PROVIDER and pinned is None
            and not replaces_sheet(c.coverage, kept.coverage, policy.coverage_threshold)):
        set_picks(run.conn, run.song.id, CHORDS_KINDS, [])  # the other site's sheet stays the pick
        return None
    _keep_text(run, c.version_id, page, SHEET_FILES)
    set_picks(run.conn, run.song.id, SHEET_KINDS, [c.version_id])
    if is_complete(c, policy):
        _retire_auto_sheet(run.conn, run.ctx.library_dir, run.song)
    return int(c.tab_id)


def _guitar_pro_slot(run: _SongRun, pinned: list[int] | None) -> tuple[int, ...]:
    """Pick the best Guitar Pro and Power Tab versions; nothing is downloaded (assisted mode)."""
    policy = run.ctx.rank
    rows = _rows(run, GUITAR_PRO_KINDS)
    if pinned is not None:
        ranked = [_candidate(r) for r in _in_order(rows, pinned)]
    else:
        ranked = rank_guitar([_candidate(r) for r in rows], policy, variant=run.song.variant)
    chosen = ranked[: policy.keep_guitar_pro]
    set_picks(run.conn, run.song.id, GUITAR_PRO_KINDS, [c.version_id for c in chosen if c.version_id is not None])
    return tuple(int(c.tab_id) for c in chosen)


def _tab_slot(run: _SongRun, pinned: list[int] | None) -> int | None:
    """Keep the best text tab (or the first pin) as tab.txt and tab.json."""
    rows = _rows(run, TAB_KINDS)
    if pinned is not None:
        ranked = [_candidate(r) for r in _in_order(rows, pinned)]
    else:
        ranked = rank_guitar([_candidate(r) for r in rows], run.ctx.rank, variant=run.song.variant)
    best = _first_with_text(run, ranked, rows, {})
    if best is None:
        set_picks(run.conn, run.song.id, TAB_KINDS, [])
        _drop_if_blocked(run, TAB_FILES)
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
    listed = _name_keys(clean_title(tab.song_name))
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
    """The artist page you pasted under [artist_url], else one learned from a tab page."""
    for key in keys:
        if key in overrides.artist_url:
            return overrides.artist_url[key]
    for key in keys:
        if url := learned_artist_url(conn, key):
            return url
    return None


def _learn_artist_page(run: _SongRun, keys: list[str]) -> str | None:
    """Read a slugged tab of the artist, from the index, for the artist page it links to.

    The tab is another song's, so none of its versions are recorded for this song.
    """
    for key in keys:
        for tab in artist_tabs(run.conn, key, limit=LEARN_TRIES):
            page, _ = _get_page(run.ctx.client, tab.url, parse_tab_page)
            if page is not None and (url := _learn_artist_url(run.conn, page, [key])):
                return url
    return None


def _read_list(run: _SongRun, base: str, kind: str, forms: list[str]) -> tuple[list[_Hit], bool, UGArtistPage | None]:
    """The song's entries in the artist's list of one kind.

    Returns the hits, whether the list was read far enough (False when this
    run's page cap stopped it), and the list's first page (None when UG
    answered 404). Lists are sorted by title, so the title's entries are
    consecutive: reading stops once they end, and goes on to the next page
    only when they reach the end of this one.
    """
    ctx = run.ctx
    hits: list[_Hit] = []
    first: UGArtistPage | None = None
    fetched, number, last = 0, 1, 1
    while number <= last:
        if fetched >= ctx.artist_pages_per_kind:
            return hits, False, first
        url = artist_page_url(base, kind=kind, page=number)
        page, fresh = _get_page(ctx.client, url, parse_artist_page, max_age=ctx.artist_page_max_age)
        fetched += fresh
        if page is None:
            break
        first = first or page
        last = max(last, page.pages)
        listed = [t for t in page.tabs if t.kind == kind]
        found = [h for t in listed if (h := _title_hit(t, forms, fresh)) is not None]
        hits += found
        if hits and not (found and found[-1].tab is listed[-1]):
            break
        number += 1
    return hits, True, first


def _offered_kinds(run: _SongRun, base: str) -> set[str] | None:
    """The kinds of list the artist page offers, read from its unfiltered first page; None when it's gone."""
    page, _ = _get_page(run.ctx.client, artist_page_url(base), parse_artist_page,
                        max_age=run.ctx.artist_page_max_age)
    if page is None:
        return None
    return set(page.filters) or set(ARTIST_PAGE_KINDS)


def _checked_key(song_id: int) -> str:
    return f"ug:artist_page_checked:{song_id}"


def _mark_checked(run: _SongRun) -> None:
    kv_set(run.conn, _checked_key(run.song.id), _iso(run.ctx.now))


def _forget_learned(run: _SongRun, keys: list[str], base: str) -> None:
    for key in keys:
        if learned_artist_url(run.conn, key) == base:
            forget_artist_url(run.conn, key)


def _accept_artist_page_match(run: _SongRun, hits: list[_Hit], artist_name: str) -> None:
    """Record the matching tabs as the song's versions, and the match itself (step ``artist_page``)."""
    _record(run, (h.tab for h in hits if h.fresh), fresh=True)
    _record(run, (h.tab for h in hits if not h.fresh), fresh=False)
    best = max(hits, key=lambda h: h.score)
    artist_key = slug_key(artist_name) or slug_key(best.tab.artist_name) or run.artist_key
    song_key = slug_key(clean_title(best.tab.song_name)) or slug_key(clean_title(run.song.title))
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
    comes from [artist_url], a learned address, or a slugged tab of the
    artist. The chords list is read first; its filter bar tells which guitar
    lists the artist has. A list cut short by the page cap leaves the song as
    it was, for the next run; otherwise the check is recorded, found or not.
    """
    keys = artist_keys(run.song, run.ctx.overrides)
    base = _known_artist_page(run.conn, keys, run.ctx.overrides) or _learn_artist_page(run, keys)
    if base is None:
        _mark_checked(run)
        return False
    forms = _name_keys(clean_title(run.song.title))
    hits: list[_Hit] = []
    name = ""
    offered: set[str] | None = None
    for kind in ARTIST_PAGE_KINDS:
        if offered is not None and kind not in offered:
            continue
        found, complete, first = _read_list(run, base, kind, forms)
        if not complete:
            return False
        if first is not None:
            name = name or first.name
            if offered is None and first.filters:
                offered = set(first.filters)
        elif offered is None:
            offered = _offered_kinds(run, base)  # an empty list may answer 404; the artist page tells
            if offered is None:
                log.warning("UG artist page %s answered 404; check [artist_url] for %s", base, run.song.artist)
                _forget_learned(run, keys, base)
                _mark_checked(run)
                return False
        hits += found
    _mark_checked(run)
    best = [h for h in _best_title(hits) if _usable(run, h.tab)]
    if not best:
        return False
    _accept_artist_page_match(run, best, name)
    return True


# --- one song, and a run ---------------------------------------------------------------------------


def process_song(ctx: FetchContext, song: Song) -> SongFetchOutcome:
    """Fetch, rank and keep one song's UG versions, one slot at a time.

    A not-found song is first looked up on its artist's UG page (A6), and goes
    on only when it is found there. Each kind group is rated and its slot
    filled before the next group is touched, so the sheet a singer needs most
    is settled before the budget goes to guitar parts.
    """
    start = ctx.client.requests_made
    run = _SongRun(ctx, song)
    if needs_artist_page(song):
        if not _artist_page_route(run):
            return SongFetchOutcome(song.id, None, (), None, ctx.client.requests_made - start)
        song = run.song
    block = ctx.overrides.block
    tabs = song_tabs(ctx.conn, song.match_artist_key, song.match_song_key) if song.match_song_key else []
    tabs = [t for t in tabs if t.tab_id not in block]
    pinned = _fetch_pins(run, _pins(ctx.overrides, song))

    def rated(group: tuple[str, ...]) -> list[int] | None:
        if group not in pinned:
            _rate_group(run, [t for t in tabs if t.type in group])
        return pinned.get(group)

    sheet = _sheet_slot(run, rated(CHORDS_KINDS))
    guitar_pro = _guitar_pro_slot(run, rated(GUITAR_PRO_KINDS))
    tab = _tab_slot(run, rated(TAB_KINDS))
    _finish(run)
    return SongFetchOutcome(song.id, sheet, guitar_pro, tab, ctx.client.requests_made - start)


def _finish(run: _SongRun) -> None:
    """Every slot is done: refresh the status, mark the song checked, and describe it in info.json."""
    refresh_status(run.conn, run.song.id, ignored=False)
    update_song(run.conn, run.song.id, ug_dirty=False, ug_checked_at=_iso(run.ctx.now))
    write_info(run.conn, run.ctx.library_dir, get_song(run.conn, run.song.id))


def _checked_within(conn: sqlite3.Connection, song_id: int, now: datetime, max_age: timedelta) -> bool:
    value = kv_get(conn, _checked_key(song_id))
    if value is None:
        return False
    checked = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return now - checked < max_age


def _ignored(song: Song, overrides: Overrides) -> bool:
    return song.status == "ignored" or song.match_decision == "ignored" or song.key in overrides.ignore


def needs_artist_page(song: Song) -> bool:
    """Whether the index can't settle this song, so its artist's UG page should be read (A6).

    That is a not-found song, or a review whose only candidates are other artists' songs of
    the same title: on the real index Soda Stereo's "De Música Ligera" (every tab a bare id)
    reviews as a Portuguese cover.
    """
    if song.match_decision == "not_found":
        return True
    candidates = song.match_candidates or []
    return song.match_decision == "review" and bool(candidates) and all(
        c.get("step") == "title_only" for c in candidates
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
      that stopped half-way).
    - Not-found songs whose artist is known (A6), so that its UG artist page,
      which lists bare-id tabs the index can't see, is searched for the
      title, at most once per ``artist_page_max_age``.
    """
    out = []
    for song in list_songs(conn):
        if _ignored(song, overrides):
            continue
        dirty = song.match_decision in ("accept", "pinned") and song.ug_dirty
        due = (
            needs_artist_page(song)
            and not _checked_within(conn, song.id, now, artist_page_max_age)
            and artist_is_known(conn, song, overrides)
        )
        if dirty or due:
            out.append(song)
    return out


def fetch_songs(
    ctx: FetchContext,
    songs: Iterable[Song],
    *,
    on_song: Callable[[Song, SongFetchOutcome], None] | None = None,
) -> FetchStats:
    """Process songs in order until the budget is spent; ``on_song`` hears about each song done.

    A block is re-raised (the caller cools the provider down). Any other
    provider error, a page that can't be parsed included, skips that song: it
    stays dirty and is never marked not found.
    """
    stats = FetchStats()
    for song in songs:
        try:
            outcome = process_song(ctx, song)
        except BudgetExhausted:
            stats.budget_exhausted = True
            break
        except ProviderBlocked:
            raise
        except ProviderError as e:
            log.warning("UG fetch failed for %s: %s", song.display, e)
            stats.songs_failed += 1
            continue
        stats.songs_done += 1
        if on_song is not None:
            on_song(song, outcome)
    return stats


# --- sheets kept before their lyrics ---------------------------------------------------------------


def rescore_kept_sheets(conn: sqlite3.Connection, library_dir: Path, rank: RankPolicy) -> int:
    """Score the kept sheets that have no coverage because their song had no lyrics yet; return how many.

    A sheet kept before LRCLIB answered has an unknown coverage forever
    otherwise: it never shows as partial on the to-do page, and only a complete
    sheet may replace it. Once its song has lyrics, the sheet's markup (the
    ``content`` of the ``sheet.json`` kept beside it, from UG or LaCuerda) is
    scored as the fetch would have scored it. No request is made. A sheet that
    proves complete retires the auto-chords sheet, as it would have on keeping.
    """
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
        if value is not None and value >= rank.coverage_threshold:
            _retire_auto_sheet(conn, library_dir, song)
        write_info(conn, library_dir, song)
        scored += 1
    return scored


def _kept_markup(conn: sqlite3.Connection, library_dir: Path, song: Song, version_id: int) -> str | None:
    """The markup in the song's kept ``sheet.json``, if it is that version's and can be read."""
    doc_file = next((f for f in kept_files(conn, song.id) if f.name == SHEET_FILES[1]), None)
    if doc_file is None or doc_file.version_id != version_id:
        return None
    path = library_dir / doc_file.path
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # ValueError: not UTF-8, or not JSON
        log.warning("cannot score %s: %s", path, e)
        return None
    content = doc.get("content") if isinstance(doc, dict) else None
    return content if isinstance(content, str) else None
