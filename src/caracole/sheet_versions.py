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
lists the versions with both; ``in_library_of`` lists those of many songs in a few queries for
them all (the library page's every song), as ``in_library`` does each: both read the same way
(``_listings``). ``kept_by_you`` are the versions you asked to keep
(``caracole versions --keep``), which the fetch keeps beside the sheet whatever the ranking.
``sheet_pins`` are the song's ``[pin]`` tabs that choose its sheet, those ``caracole versions
--clear`` takes out.
"""

from __future__ import annotations

import json
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
from caracole.versions import GONE, STALE, VersionRow, get_version

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


def _note(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    folded = " ".join(text.split())
    return folded[:NOTE_LENGTH] or None


def _candidate(row: VersionRow) -> Candidate:
    return Candidate(
        provider=row.provider, tab_id=row.tab_id, kind=row.kind, rating=row.rating, votes=row.votes,
        version=row.version, label=row.label, coverage=row.coverage, version_id=row.id,
    )


# The UG versions of the sheet's kinds of the songs a JSON list names, found under their match (a STALE one is
# another song's), in each song's order of ids, each with its tabber's note as UG wrote it: its JSON's
# version_description, read by SQLite, as the rest of that JSON (a kilobyte a version) is never needed here.
_ROWS = (
    "SELECT id, provider, tab_id, song_id, slot, kind, rating, votes, version, label, coverage, url, fetched_at, "
    "pick_rank, gone, CASE WHEN json_valid(raw) THEN CASE json_type(raw, '$.version_description') WHEN 'text' "
    "THEN json_extract(raw, '$.version_description') END END FROM versions "
    f"WHERE provider = ? AND kind IN ({', '.join('?' for _ in KINDS)}) AND gone != ? "
    "AND song_id IN (SELECT value FROM json_each(?)) ORDER BY song_id, id"
)


def _rows_of(conn: sqlite3.Connection, ids: str) -> dict[int, list[tuple[VersionRow, str | None]]]:
    """The versions ``_ROWS`` reads of the songs ``ids`` names (a JSON list), by song id, each with its note
    (``_note``). Their ``raw`` is left empty: what a list shows of it is the note."""
    found: dict[int, list[tuple[VersionRow, str | None]]] = {}
    for r in conn.execute(_ROWS, (PROVIDER, *KINDS, STALE, ids)):
        row = VersionRow(id=r[0], provider=r[1], tab_id=r[2], song_id=r[3], slot=r[4], kind=r[5], rating=r[6],
                         votes=r[7], version=r[8], label=r[9], coverage=r[10], url=r[11], raw={}, fetched_at=r[12],
                         pick_rank=r[13], gone=r[14] == GONE)
        found.setdefault(row.song_id, []).append((row, _note(r[15])))
    return found


def _variants(conn: sqlite3.Connection, ids: str) -> dict[int, str | None]:
    return dict(conn.execute("SELECT id, variant FROM songs WHERE id IN (SELECT value FROM json_each(?))", (ids,)))


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
    ids = json.dumps([song_id])
    return _listed(_rows_of(conn, ids).get(song_id, []), policy, _variants(conn, ids).get(song_id),
                   chosen_tab=chosen_tab, kept_tabs=kept_tabs, same_as=same_as)


def _listed(found: Sequence[tuple[VersionRow, str | None]], policy: RankPolicy, variant: str | None, *,
            chosen_tab: str | None, kept_tabs: Collection[str],
            same_as: Mapping[str, str] | None) -> list[SheetVersion]:
    """``song_sheet_versions`` of a song's rows (``_rows_of``) and its ``variant``."""
    rows = [r for r, _ in found]
    notes = {r.id: note for r, note in found}
    group = group_of(rows, chosen_tab)
    rows = [r for r in rows if r.kind == group]
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
            label=row.label, note=notes[row.id], coverage=row.coverage,
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
    return _states(conn, json.dumps([song_id])).get(song_id, (None, ()))


def _states(conn: sqlite3.Connection, ids: str) -> dict[int, tuple[str | None, tuple[str, ...]]]:
    """``library_state`` of each song ``ids`` names (a JSON list) that has a ``sheet.txt`` or a
    ``version-*`` file, by song id, in one query."""
    chosen: dict[int, str | None] = {}
    kept: dict[int, list[tuple[int, str]]] = {}
    rows = conn.execute(
        "SELECT f.song_id, f.name, f.kept_rank, v.provider, v.kind, v.tab_id FROM files f "
        "JOIN versions v ON v.id = f.version_id WHERE f.song_id IN (SELECT value FROM json_each(?)) "
        "AND (f.name = ? OR substr(f.name, 1, ?) = ?)", (ids, HUMAN_SHEET, len(PREFIX), PREFIX))
    for song_id, name, kept_rank, provider, kind, tab_id in rows:
        chosen.setdefault(song_id, None)
        kept.setdefault(song_id, [])
        if name == HUMAN_SHEET:
            if provider == PROVIDER and kind in KINDS:
                chosen[song_id] = tab_id
        elif (tab := tab_of(name)) is not None and name == version_names(tab)[0]:
            kept[song_id].append((kept_rank, tab))
    return {song_id: (chosen[song_id], tuple(tab for _, tab in sorted(kept[song_id],
                                                                      key=lambda k: (k[0], len(k[1]), k[1]))))
            for song_id in chosen}


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
    return _same(kv_get_json(conn, same_key(song_id), default={}), *library_state(conn, song_id))


def _same(record: Any, chosen: str | None, kept: Collection[str]) -> dict[str, str]:
    """``same_pages`` of a song's record, the one ``chosen`` and the tabs ``kept`` beside it."""
    if not isinstance(record, dict):
        return {}
    pages = {version_names(t)[2] for t in kept} | ({SHEET_PAGE} if chosen is not None else set())
    return {str(t): p for t, p in record.items() if isinstance(p, str) and p in pages}


def _same_records(conn: sqlite3.Connection, ids: str) -> dict[int, Any]:
    """The ``same_pages`` record of each song ``ids`` names (a JSON list) that has one, by song id, in one query."""
    rows = conn.execute("SELECT key, value FROM kv WHERE key IN (SELECT ? || value FROM json_each(?))",
                        (SAME_KV, ids))
    return {int(key[len(SAME_KV):]): json.loads(value) for key, value in rows}


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

    # The list shows one group of versions (``group_of``); a keep keeps the group of the song's sheet (chords but
    # beside UG's ukulele sheet: ug.fetch.sheet_group). A song with no chords version but ukulele ones, and a sheet
    # that isn't UG's, lists the ukulele ones: none of them is one a keep may keep.
    live = [v for v in versions if not v.gone]
    if live and (get_version(conn, live[0].version_id).kind == "ukulele") != (sheet_kind(conn, song_id) == "ukulele"):
        return []
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
    return _listings(conn, [song_id], policy).get(song_id, [])


def in_library_of(conn: sqlite3.Connection, song_ids: Collection[int],
                  policy: RankPolicy) -> dict[int, list[SheetVersion]]:
    """``in_library`` of each of ``song_ids`` that has UG versions listed, by song id (a song with none is left out),
    in four queries for them all: the library page lists every song's, where a few queries a song would cost it a
    moment."""
    return {song_id: listed for song_id, listed in _listings(conn, song_ids, policy).items() if listed}


def _listings(conn: sqlite3.Connection, song_ids: Collection[int], policy: RankPolicy) -> dict[int, list[SheetVersion]]:
    """``in_library``'s list of each of ``song_ids`` with a version recorded, by song id: its rows, its library state,
    its ``same_pages`` record and its variant, each read for every song at once."""
    rows = _rows_of(conn, json.dumps(sorted(set(song_ids))))
    if not rows:
        return {}
    ids = json.dumps(sorted(rows))
    states, records, variants = _states(conn, ids), _same_records(conn, ids), _variants(conn, ids)
    out = {}
    for song_id, found in rows.items():
        chosen, kept = states.get(song_id, (None, ()))
        out[song_id] = _listed(found, policy, variants.get(song_id), chosen_tab=chosen, kept_tabs=kept,
                               same_as=_same(records.get(song_id, {}), chosen, kept))
    return out
