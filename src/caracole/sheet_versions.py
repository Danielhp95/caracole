"""A song's Ultimate Guitar chords versions in rank order: which are kept, and which is the one.

UG lists many chords versions of a song (Wonderwall has 13). caracole scores the top
``RankPolicy.scored_sheets`` by rating for lyric coverage, keeps the best as ``sheet.txt``
(the one the title, the PDF, the viewer and songbooks use), and keeps the runners-up it
scored beside it, flat in the song's folder: ``version-<tab>.txt`` and ``.json``, and
render.py's viewer page ``version-<tab>.html`` (no PDF of their own).

A song with no chords on UG takes its sheet from UG's "Ukulele Chords" versions (ug/fetch.py),
and its versions are those: the versions listed are of the group the kept sheet comes from
(``group_of``), chords unless that is a ukulele version.

This module names those files (``version_names``, ``tab_of``) and lists the versions
(``song_sheet_versions``) in ``rank.rank_sheets`` order: the scored versions, complete ones
(coverage at or above ``coverage_threshold``) first, then by the rating weighed by votes
(``rank.bayes``); then the versions never scored, by that rating; then the versions UG no
longer has (``gone``), which stay listed, and their kept files kept, until the next fetch
drops them. A version an earlier match of the song found (``versions.STALE``) is another
song's and isn't listed.

``as_data`` is the JSON the viewer pages and the library page read. ``library_state`` reads
from the files table which version is the one and which are kept beside it, ``same_pages``
which versions are a kept one's very text (kept under one name only), and ``in_library``
lists the versions with both. ``kept_by_you`` are the versions you asked to keep
(``caracole versions --keep``), which the fetch keeps beside the sheet whatever the ranking.
``sheet_pins`` are the song's ``[pin]`` tabs that choose its sheet, those ``caracole versions
--clear`` takes out.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from caracole.config import RankPolicy
from caracole.db import kv_get_json, kv_set_json
from caracole.library import kept_files
from caracole.rank import Candidate, is_complete, rank_by_rating
from caracole.songs import HUMAN_SHEET
from caracole.versions import VersionRow, get_version, song_versions

PREFIX = "version-"
PROVIDER = "ug"
KINDS = ("chords", "ukulele")  # UG's kinds for the sheet slot: ukulele chords for a song with no chords
SHEET_PAGE = "sheet.html"  # the chosen version's viewer page, render.py's
NOTE_LENGTH = 200
SAME_KV = "sheet_versions:same:"  # + song id: the versions whose text is a kept one's, and its page
YOURS_KV = "sheet_versions:yours:"  # + song id: the versions you kept (caracole versions --keep)
UNKEEPABLE_KV = "sheet_versions:unkeepable:"  # + song id: the versions a keep found it can't keep

_NAME = re.compile(rf"{re.escape(PREFIX)}([0-9]+)\.(?:txt|json|html)")


def version_names(tab_id: str) -> tuple[str, str, str]:
    """A kept version's text, its JSON and its viewer page: ``version-<tab>.txt``, ``.json``, ``.html``."""
    stem = f"{PREFIX}{tab_id}"
    return f"{stem}.txt", f"{stem}.json", f"{stem}.html"


def tab_of(name: str) -> str | None:
    """The tab id of a version file's name, else None."""
    m = _NAME.fullmatch(name)
    return m.group(1) if m else None


@dataclass(frozen=True)
class SheetVersion:
    """One chords version of a song, as the switcher and the lists show it.

    ``number`` is UG's version number ("Ver 3"), ``note`` the first ``NOTE_LENGTH`` characters of
    the tabber's ``version_description``, whitespace folded. ``coverage`` and ``complete`` are
    None for a version never scored. ``rank`` is 1-based. ``page`` is the version's viewer page in
    the song's folder: ``sheet.html`` for the one, ``version-<tab>.html`` for one kept beside it,
    None for one not kept.
    """

    version_id: int
    tab_id: str
    number: int | None
    rating: float | None
    votes: int | None
    label: str | None
    note: str | None
    coverage: float | None
    complete: bool | None
    rank: int
    kept: bool
    chosen: bool
    gone: bool
    page: str | None
    url: str


def _note(raw: dict[str, Any]) -> str | None:
    text = raw.get("version_description")
    if not isinstance(text, str):
        return None
    folded = " ".join(text.split())
    return folded[:NOTE_LENGTH] or None


def _candidate(row: VersionRow) -> Candidate:
    return Candidate(
        provider=row.provider, tab_id=row.tab_id, kind=row.kind, rating=row.rating, votes=row.votes,
        version=row.version, label=row.label, coverage=row.coverage, version_id=row.id,
    )


def _variant(conn: sqlite3.Connection, song_id: int) -> str | None:
    row = conn.execute("SELECT variant FROM songs WHERE id = ?", (song_id,)).fetchone()
    return row[0] if row is not None else None


def _ranked(rows: Sequence[VersionRow], policy: RankPolicy, variant: str | None) -> list[Candidate]:
    """``rank_sheets`` order, with the versions never scored after those scored."""
    by_rating = rank_by_rating([_candidate(r) for r in rows], policy, variant=variant)
    order = {id(c): n for n, c in enumerate(by_rating)}
    return sorted(by_rating, key=lambda c: (c.coverage is None, not is_complete(c, policy), order[id(c)]))


def song_sheet_versions(
    conn: sqlite3.Connection,
    song_id: int,
    policy: RankPolicy,
    *,
    chosen_tab: str | None,
    kept_tabs: Collection[str],
    same_as: Mapping[str, str] | None = None,
) -> list[SheetVersion]:
    """The song's UG chords versions in rank order, gone ones last.

    ``chosen_tab`` is the tab kept as ``sheet.txt`` (None when the sheet is another site's, or
    auto-chords', or there is none); ``kept_tabs`` those kept beside it (``library_state``).
    ``same_as`` gives the versions whose text is a kept one's, by tab, with that one's page
    (``same_pages``): they are kept, and open that page.
    """
    rows = [
        r for r in song_versions(conn, song_id, kinds=KINDS, include_gone=True)
        if r.provider == PROVIDER and not r.stale
    ]
    group = group_of(rows, chosen_tab)
    rows = [r for r in rows if r.kind == group]
    variant = _variant(conn, song_id)
    live = _ranked([r for r in rows if not r.gone], policy, variant)
    gone = rank_by_rating([_candidate(r) for r in rows if r.gone], policy, variant=variant)
    by_id = {r.id: r for r in rows}
    kept = set(kept_tabs)
    same = dict(same_as or {})
    out = []
    for rank, c in enumerate([*live, *gone], start=1):
        assert c.version_id is not None
        row = by_id[c.version_id]
        chosen = chosen_tab is not None and row.tab_id == chosen_tab
        is_kept = chosen or row.tab_id in kept or row.tab_id in same
        if chosen:
            page: str | None = SHEET_PAGE
        elif row.tab_id in kept:
            page = version_names(row.tab_id)[2]
        else:
            page = same.get(row.tab_id)
        out.append(SheetVersion(
            version_id=row.id, tab_id=row.tab_id, number=row.version, rating=row.rating, votes=row.votes,
            label=row.label, note=_note(row.raw), coverage=row.coverage,
            complete=None if row.coverage is None else is_complete(c, policy),
            rank=rank, kept=is_kept, chosen=chosen, gone=row.gone, page=page, url=row.url,
        ))
    return out


def group_of(rows: Sequence[VersionRow], chosen_tab: str | None) -> str:
    """The kind of the versions a song's list shows: the chosen one's (``chords`` or ``ukulele``), else chords
    while the song has any live, else ukulele."""
    chosen = next((r.kind for r in rows if chosen_tab is not None and r.tab_id == chosen_tab), None)
    if chosen is not None:
        return chosen
    return "chords" if any(r.kind == "chords" and not r.gone for r in rows) or not rows else "ukulele"


def as_data(versions: Sequence[SheetVersion], total: int) -> dict:
    """The JSON the viewer pages and the library page read: ``total`` is UG's count of chords versions."""
    return {
        "total": total,
        "list": [
            {
                "tab": v.tab_id, "number": v.number, "rating": v.rating, "votes": v.votes, "label": v.label,
                "note": v.note, "rank": v.rank, "kept": v.kept, "chosen": v.chosen, "gone": v.gone,
                "page": v.page, "url": v.url,
            }
            for v in versions
        ],
    }


def library_state(conn: sqlite3.Connection, song_id: int) -> tuple[str | None, tuple[str, ...]]:
    """The UG tab kept as ``sheet.txt`` (None when the sheet is another site's or none), and the tabs
    kept beside it, by their ``kept_rank``: what the files table says caracole wrote."""
    chosen: str | None = None
    kept: list[tuple[int, str]] = []
    for f in kept_files(conn, song_id):
        if f.name == HUMAN_SHEET:
            row = get_version(conn, f.version_id)
            if row.provider == PROVIDER and row.kind in KINDS:
                chosen = row.tab_id
        elif (tab := tab_of(f.name)) is not None and f.name == version_names(tab)[0]:
            kept.append((f.kept_rank, tab))
    return chosen, tuple(tab for _, tab in sorted(kept, key=lambda k: (k[0], len(k[1]), k[1])))


def sheet_kind(conn: sqlite3.Connection, song_id: int) -> str:
    """The kind of the song's kept UG sheet: ``ukulele`` for a version of UG's Ukulele Chords type (a song with no
    chords there, ug/fetch.py), else ``chords``, whether its sheet is UG's, another site's or none."""
    for f in kept_files(conn, song_id):
        if f.name == HUMAN_SHEET:
            row = get_version(conn, f.version_id)
            return "ukulele" if row.provider == PROVIDER and row.kind == "ukulele" else "chords"
    return "chords"


def same_key(song_id: int) -> str:
    return f"{SAME_KV}{song_id}"


def same_pages(conn: sqlite3.Connection, song_id: int) -> dict[str, str]:
    """The song's versions whose text is a kept one's (two UG tabs, one text: ``library.keep_file`` keeps
    one text under one name), by tab, with the page that shows it: ``sheet.html`` or another version's.
    The fetch writes it (ug/fetch.py ``_keep_beside``); a page no longer kept is left out."""
    record = kv_get_json(conn, same_key(song_id), default={})
    if not isinstance(record, dict):
        return {}
    chosen, kept = library_state(conn, song_id)
    pages = {version_names(t)[2] for t in kept} | ({SHEET_PAGE} if chosen is not None else set())
    return {str(t): p for t, p in record.items() if isinstance(p, str) and p in pages}


def yours_key(song_id: int) -> str:
    return f"{YOURS_KV}{song_id}"


def kept_by_you(conn: sqlite3.Connection, song_id: int) -> tuple[str, ...]:
    """The tabs you asked to keep beside the song's sheet (``caracole versions --keep``), oldest first: the
    fetch keeps them whatever the ranking, while UG has them and you don't ``[block]`` them."""
    record = kv_get_json(conn, yours_key(song_id), default=[])
    return tuple(str(t) for t in record) if isinstance(record, list) else ()


def note_kept_by_you(conn: sqlite3.Connection, song_id: int, tab_id: str) -> None:
    tabs = kept_by_you(conn, song_id)
    if str(tab_id) not in tabs:
        kv_set_json(conn, yours_key(song_id), [*tabs, str(tab_id)])


def unkeepable_key(song_id: int) -> str:
    return f"{UNKEEPABLE_KV}{song_id}"


def unkeepable(conn: sqlite3.Connection, song_id: int) -> tuple[str, ...]:
    """The tabs a keep (``caracole versions --keep``, ``--keep-more``) read and found it can't keep: no sheet text
    on their page, or the very text of another file kept in the song's folder. A page that won't parse isn't one:
    it waits, as any does."""
    record = kv_get_json(conn, unkeepable_key(song_id), default=[])
    return tuple(str(t) for t in record) if isinstance(record, list) else ()


def note_unkeepable(conn: sqlite3.Connection, song_id: int, tab_id: str | int) -> None:
    tabs = unkeepable(conn, song_id)
    if str(tab_id) not in tabs:
        kv_set_json(conn, unkeepable_key(song_id), [*tabs, str(tab_id)])


def may_keep(conn: sqlite3.Connection, song_id: int, versions: Sequence[SheetVersion],
             block: Collection[int]) -> list[SheetVersion]:
    """The song's versions (``in_library``'s) a keep may still keep beside its sheet, in their order: neither kept
    nor the one nor gone, not under ``[block]`` (``block``), not at an address robots.txt closes, and none a keep
    found it can't keep (``unkeepable``). What the library page counts as not kept, and ``--keep-more`` keeps."""
    from caracole.http import robots_disallows

    cannot = set(unkeepable(conn, song_id))
    return [v for v in versions
            if not (v.kept or v.chosen or v.gone) and int(v.tab_id) not in block and v.tab_id not in cannot
            and robots_disallows(v.url) is None]


def sheet_pins(conn: sqlite3.Connection, song_id: int, pins: Sequence[int]) -> list[int]:
    """Of the song's ``[pin]`` tabs ``pins``, those that choose its sheet: chords versions, by the song's versions
    and the offline index, and a pin of a kind neither knows (not fetched yet). Any other stays: a text tab's."""
    out = []
    for tab in pins:
        row = conn.execute("SELECT kind FROM versions WHERE song_id = ? AND provider = ? AND tab_id = ?",
                           (song_id, PROVIDER, str(tab))).fetchone()
        kind = row[0] if row is not None else None
        if kind is None:
            indexed = conn.execute("SELECT type FROM ug_index WHERE tab_id = ?", (tab,)).fetchone()
            kind = indexed[0] if indexed is not None else None
        if kind is None or kind in KINDS:
            out.append(tab)
    return out


def in_library(conn: sqlite3.Connection, song_id: int, policy: RankPolicy) -> list[SheetVersion]:
    """``song_sheet_versions`` with the one, the kept versions and those that are a kept one's text, as the
    library holds them now. The JSON the pages read is ``as_data`` of it."""
    chosen, kept = library_state(conn, song_id)
    return song_sheet_versions(conn, song_id, policy, chosen_tab=chosen, kept_tabs=kept,
                               same_as=same_pages(conn, song_id))
