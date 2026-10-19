"""Per-song Ultimate Guitar fetch: rate every version, keep the best sheet, pick guitar parts.

For each matched song (plan §3, Task 15):

1. **Ratings.** UG lists a song's versions per (type, part) group on each tab
   page, so for every kind group tabarr fetches the page of the lowest id it
   has no rating for, and records that page's own tab plus the versions it
   lists, until every id has a rating or ``max_pages_per_group`` pages were read.
2. **Sheet.** The top ``scored_sheets`` sheets by rating are scored for lyric
   coverage against LRCLIB's lyrics, then ranked by completeness and rating; the
   best is kept as ``sheet.txt`` (markup stripped) and ``sheet.json``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tabarr import coverage
from tabarr.config import RankPolicy
from tabarr.http import Client
from tabarr.library import keep_file, write_info
from tabarr.lyrics import song_lyrics
from tabarr.overrides import Overrides
from tabarr.rank import Candidate, rank_by_rating, rank_guitar, rank_sheets
from tabarr.songs import Song, get_song, refresh_status, update_song
from tabarr.ug.lookup import IndexTab, index_tab, song_tabs, tab_url_for
from tabarr.ug.page import UGTabPage, UGVersion, parse_tab_page, strip_markup
from tabarr.versions import (
    VersionRow, get_version, mark_gone, set_coverage, set_picks, song_versions, upsert_version,
)

PROVIDER = "ug"
_PAGE_ACCEPT = (200, 404)
SHEET_KINDS = ("chords",)
GUITAR_PRO_KINDS = ("guitar-pro", "power")
TAB_KINDS = ("tabs",)
_GROUPS = (SHEET_KINDS, GUITAR_PRO_KINDS, TAB_KINDS)
_GROUP_OF = {kind: group for group in _GROUPS for kind in group}


@dataclass
class FetchContext:
    """Everything one fetch run needs. ``client`` is the run's UG client."""

    conn: sqlite3.Connection
    client: Client
    overrides: Overrides
    rank: RankPolicy
    library_dir: Path
    now: datetime
    max_pages_per_group: int = 3
    artist_page_max_age: timedelta = timedelta(days=30)


@dataclass(frozen=True)
class SongFetchOutcome:
    """What one song's fetch kept: UG tab ids of the sheet, Guitar Pro picks and text tab."""

    song_id: int
    sheet: int | None
    guitar_pro: tuple[int, ...]
    tab: int | None
    requests: int


@dataclass
class FetchStats:
    songs_done: int = 0
    songs_failed: int = 0
    budget_exhausted: bool = False


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slot(kind: str) -> str:
    return "sheet" if kind in SHEET_KINDS else "guitar"


@dataclass
class _SongRun:
    """One song's fetch: its pages read so far, and the tab ids that belong to it."""

    ctx: FetchContext
    song: Song
    pages: dict[int, UGTabPage | None] = field(default_factory=dict)

    @property
    def conn(self) -> sqlite3.Connection:
        return self.ctx.conn


def _upsert(run: _SongRun, v: UGVersion) -> int:
    assert v.kind is not None
    return upsert_version(
        run.conn, provider=PROVIDER, tab_id=str(v.tab_id), song_id=run.song.id, slot=_slot(v.kind), kind=v.kind,
        rating=v.rating, votes=v.votes, version=v.version, label=v.label, url=v.url, raw=v.raw,
        now=_iso(run.ctx.now),
    )


def _usable(run: _SongRun, v: UGVersion) -> bool:
    """A kind tabarr uses (never Official, which UG marks public too), public, and not blocked."""
    return v.kind is not None and v.access == "public" and v.tab_id not in run.ctx.overrides.block


def _record_page(run: _SongRun, page: UGTabPage) -> None:
    """Record the page's own tab and the versions it lists of the same kind group."""
    group = _GROUP_OF.get(page.tab.kind or "")
    if group is None:
        return
    for v in (page.tab, *page.versions):
        if _usable(run, v) and v.kind in group:
            _upsert(run, v)


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


def _page(run: _SongRun, tab_id: int, url: str, kind: str | None = None) -> UGTabPage | None:
    """A tab page, from this song's pages, the HTTP cache or UG; None when UG says it's gone.

    UG's 404 page has no js-store, so the status is checked before parsing.
    ``kind`` (the index's type) lets a deleted tab that was never rated be
    remembered as gone.
    """
    if tab_id in run.pages:
        return run.pages[tab_id]
    resp = run.ctx.client.get(url, accept=_PAGE_ACCEPT)
    if resp.status == 404:
        _mark_gone(run, tab_id, url, kind)
        run.pages[tab_id] = None
        return None
    page = parse_tab_page(resp.content, url=url)
    run.pages[tab_id] = page
    _record_page(run, page)
    return page


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


def _fetch_pins(run: _SongRun, pins: tuple[int, ...]) -> dict[tuple[str, ...], list[int]]:
    """Read every pinned page; return the pinned ids of each kind group, in pinned order.

    A pin's kind comes from its page. A pin whose page is gone, Official or not
    public pins nothing.
    """
    groups: dict[tuple[str, ...], list[int]] = {}
    for tab_id in pins:
        row = _version_row(run, tab_id)
        known = index_tab(run.conn, tab_id)
        url = row.url if row is not None else tab_url_for(run.conn, tab_id)
        kind = row.kind if row is not None else known.type if known is not None else None
        page = _page(run, tab_id, url, kind)
        if page is None or not _usable(run, page.tab):
            continue
        groups.setdefault(_GROUP_OF[page.tab.kind], []).append(page.tab.tab_id)
    return groups


def _in_order(rows: list[VersionRow], tab_ids: list[int]) -> list[VersionRow]:
    by_tab = {int(r.tab_id): r for r in rows}
    return [by_tab[t] for t in tab_ids if t in by_tab]


def _candidate(row: VersionRow) -> Candidate:
    return Candidate(
        provider=row.provider, tab_id=row.tab_id, kind=row.kind, rating=row.rating, votes=row.votes,
        version=row.version, label=row.label, coverage=row.coverage, version_id=row.id,
    )


def _content(run: _SongRun, row: VersionRow) -> str | None:
    """A version's sheet text, or None when its page is gone."""
    page = _page(run, int(row.tab_id), row.url, row.kind)
    return page.content if page is not None else None


def _keep_text(run: _SongRun, version_id: int, content: str, txt: str, doc: str) -> None:
    """Keep a sheet or tab: the text without UG's markup, and the version's JSON with the raw content."""
    row = get_version(run.conn, version_id)
    lib = run.ctx.library_dir
    keep_file(run.conn, lib, song=run.song, version_id=row.id, name=txt,
              data=strip_markup(content).encode("utf-8"), rank=1)
    body = {"version": row.raw, "content": content, "url": row.url}
    keep_file(run.conn, lib, song=run.song, version_id=row.id, name=doc,
              data=(json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), rank=1)


def _lyric_lines(song: Song) -> list[str]:
    lyrics = song_lyrics(song)
    return coverage.lyric_lines(lyrics.plain) if lyrics is not None else []


def _rows(run: _SongRun, kinds: tuple[str, ...]) -> list[VersionRow]:
    """The song's live UG versions of these kinds; blocked ids never compete, even if seen earlier."""
    block = run.ctx.overrides.block
    return [
        r for r in song_versions(run.conn, run.song.id, kinds=kinds)
        if r.provider == PROVIDER and int(r.tab_id) not in block
    ]


def _sheet_slot(run: _SongRun, pinned: list[int] | None) -> int | None:
    """Score the top sheets for lyric coverage, rank them, and keep the best (or the first pin)."""
    policy = run.ctx.rank
    rows = _rows(run, SHEET_KINDS)
    lines = _lyric_lines(run.song)
    by_id = {r.id: r for r in rows}
    contents: dict[int, str] = {}

    def scored(c: Candidate) -> bool:
        """Fetch the sheet and score its coverage; False when its page is gone."""
        assert c.version_id is not None
        content = _content(run, by_id[c.version_id])
        if content is None:
            return False
        contents[c.version_id] = content
        c.coverage = coverage.coverage(content, lines, line_match=policy.line_match)
        set_coverage(run.conn, c.version_id, c.coverage)
        return True

    ranked: Iterable[Candidate]
    if pinned is not None:
        ranked = (c for c in map(_candidate, _in_order(rows, pinned)) if scored(c))
    else:
        alive: list[Candidate] = []
        for c in rank_by_rating([_candidate(r) for r in rows], policy, variant=run.song.variant):
            if len(contents) < policy.scored_sheets and not scored(c):
                continue  # gone; the next one is scored instead
            alive.append(c)
        ranked = rank_sheets(alive, policy, variant=run.song.variant)
    for c in ranked:
        assert c.version_id is not None
        content = contents.get(c.version_id) or _content(run, by_id[c.version_id])
        if content is None:
            continue
        _keep_text(run, c.version_id, content, "sheet.txt", "sheet.json")
        set_picks(run.conn, run.song.id, SHEET_KINDS, [c.version_id])
        return int(c.tab_id)
    return None


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
    by_id = {r.id: r for r in rows}
    if pinned is not None:
        ranked = [_candidate(r) for r in _in_order(rows, pinned)]
    else:
        ranked = rank_guitar([_candidate(r) for r in rows], run.ctx.rank, variant=run.song.variant)
    for c in ranked:
        assert c.version_id is not None
        content = _content(run, by_id[c.version_id])
        if content is None:
            continue
        _keep_text(run, c.version_id, content, "tab.txt", "tab.json")
        set_picks(run.conn, run.song.id, TAB_KINDS, [c.version_id])
        return int(c.tab_id)
    return None


def process_song(ctx: FetchContext, song: Song) -> SongFetchOutcome:
    """Fetch, rank and keep one song's UG versions."""
    start = ctx.client.requests_made
    run = _SongRun(ctx, song)
    block = ctx.overrides.block
    tabs = song_tabs(ctx.conn, song.match_artist_key, song.match_song_key) if song.match_song_key else []
    tabs = [t for t in tabs if t.tab_id not in block]
    pinned = _fetch_pins(run, tuple(t for t in ctx.overrides.pin.get(song.key, ()) if t not in block))
    for group in _GROUPS:
        if group not in pinned:
            _rate_group(run, [t for t in tabs if t.type in group])
    sheet = _sheet_slot(run, pinned.get(SHEET_KINDS))
    guitar_pro = _guitar_pro_slot(run, pinned.get(GUITAR_PRO_KINDS))
    tab = _tab_slot(run, pinned.get(TAB_KINDS))
    _finish(run)
    return SongFetchOutcome(song.id, sheet, guitar_pro, tab, ctx.client.requests_made - start)


def _finish(run: _SongRun) -> None:
    """Every slot is done: refresh the status, mark the song checked, and describe it in info.json."""
    refresh_status(run.conn, run.song.id, ignored=False)
    update_song(run.conn, run.song.id, ug_dirty=False, ug_checked_at=_iso(run.ctx.now))
    write_info(run.conn, run.ctx.library_dir, get_song(run.conn, run.song.id))
