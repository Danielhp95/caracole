"""The ``versions`` table: every sheet or tab version seen for a song, and each kept file's.

A version belongs to a slot ("sheet" or "guitar") and has a kind (chords,
acordes, auto; tabs; and guitar-pro, power or score for a file gtptabs.com gave
or you filed from the inbox, never a pick). ``pick_rank`` marks the versions
currently chosen for a slot: 1 is the best.

The sheet slot keeps one sheet, whichever site it comes from, so the rule for
replacing a kept sheet lives here too (``replaces_sheet``).

Only live versions compete (``song_versions`` lists only those unless asked).
The ``gone`` column says why one doesn't: ``GONE`` when the provider answered
404 for it (``mark_gone``), ``STALE`` when it was found under an earlier match
of its song (``mark_stale``) and the current match hasn't listed it since.
Recording a version again (``upsert_version``) makes it live.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from caracole.db import savepoint

# Every kind the sheet slot holds: UG chords, LaCuerda acordes, auto-chords. A kept
# sheet becomes the slot's only pick, so picks are cleared across all of them.
SHEET_KINDS = ("chords", "acordes", "auto")

# ``versions.gone``: a live version, one the provider says is gone, one an earlier match found.
LIVE, GONE, STALE = 0, 1, 2


@dataclass
class VersionRow:
    id: int
    provider: str
    tab_id: str
    song_id: int
    slot: str
    kind: str
    rating: float
    votes: int
    version: int
    label: str | None
    coverage: float | None
    url: str
    raw: dict[str, Any]
    fetched_at: str
    pick_rank: int | None
    gone: bool  # the provider answered 404 for it
    stale: bool = False  # found under an earlier match of the song, and not listed since


def _row(r: sqlite3.Row) -> VersionRow:
    d = dict(r)
    d["raw"] = json.loads(d["raw"] or "{}")
    state = d.pop("gone")
    return VersionRow(**d, gone=state == GONE, stale=state == STALE)


def upsert_version(
    conn: sqlite3.Connection,
    *,
    provider: str,
    tab_id: str,
    song_id: int,
    slot: str,
    kind: str,
    rating: float,
    votes: int,
    version: int,
    label: str | None,
    url: str,
    raw: Mapping[str, Any],
    now: str,
) -> int:
    """Insert or refresh a version (unique per provider, tab id and song), live; return its id."""
    conn.execute(
        "INSERT INTO versions (provider, tab_id, song_id, slot, kind, rating, votes, version, label, url, raw, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(provider, tab_id, song_id) DO UPDATE SET slot = excluded.slot, kind = excluded.kind, "
        "rating = excluded.rating, votes = excluded.votes, version = excluded.version, label = excluded.label, "
        f"url = excluded.url, raw = excluded.raw, fetched_at = excluded.fetched_at, gone = {LIVE}",
        (provider, str(tab_id), song_id, slot, kind, float(rating or 0), int(votes or 0), int(version or 1),
         label, url, json.dumps(raw, ensure_ascii=False), now),
    )
    row = conn.execute(
        "SELECT id FROM versions WHERE provider = ? AND tab_id = ? AND song_id = ?", (provider, str(tab_id), song_id)
    ).fetchone()
    return int(row[0])


def get_version(conn: sqlite3.Connection, version_id: int) -> VersionRow:
    row = conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
    if row is None:
        raise KeyError(f"no version with id {version_id}")
    return _row(row)


def song_versions(
    conn: sqlite3.Connection,
    song_id: int,
    *,
    slot: str | None = None,
    kinds: Iterable[str] | None = None,
    include_gone: bool = False,
) -> list[VersionRow]:
    sql = "SELECT * FROM versions WHERE song_id = ?"
    args: list[Any] = [song_id]
    if slot is not None:
        sql += " AND slot = ?"
        args.append(slot)
    if kinds is not None:
        kinds = list(kinds)
        sql += f" AND kind IN ({','.join('?' for _ in kinds)})"
        args.extend(kinds)
    if not include_gone:  # live versions only: neither gone nor stale
        sql += f" AND gone = {LIVE}"
    return [_row(r) for r in conn.execute(sql + " ORDER BY id", args)]


def set_coverage(conn: sqlite3.Connection, version_id: int, value: float | None) -> None:
    conn.execute("UPDATE versions SET coverage = ? WHERE id = ?", (value, version_id))


def mark_gone(conn: sqlite3.Connection, version_id: int) -> None:
    """The provider no longer has this version (it answered 404)."""
    conn.execute("UPDATE versions SET gone = ?, pick_rank = NULL WHERE id = ?", (GONE, version_id))


def mark_stale(conn: sqlite3.Connection, song_id: int, provider: str) -> int:
    """The song's match changed: its live versions from ``provider`` were found under the old one.

    They compete for no slot, and are no picks, until the new match lists
    them again (``upsert_version``). Returns how many there were.
    """
    cur = conn.execute(
        "UPDATE versions SET gone = ?, pick_rank = NULL WHERE song_id = ? AND provider = ? AND gone = ?",
        (STALE, song_id, provider, LIVE),
    )
    return cur.rowcount


def set_picks(conn: sqlite3.Connection, song_id: int, kinds: Sequence[str], version_ids: Sequence[int]) -> None:
    """Make ``version_ids`` the picks for these kinds, ranked 1..n in order; clear older picks.

    All or nothing, and inside a caller's savepoint, undone with it."""
    marks = ",".join("?" for _ in kinds)
    with savepoint(conn, "set_picks"):
        conn.execute(f"UPDATE versions SET pick_rank = NULL WHERE song_id = ? AND kind IN ({marks})", (song_id, *kinds))
        for rank, vid in enumerate(version_ids, start=1):
            conn.execute("UPDATE versions SET pick_rank = ? WHERE id = ? AND song_id = ?", (rank, vid, song_id))


def picks(conn: sqlite3.Connection, song_id: int, kinds: Sequence[str]) -> list[VersionRow]:
    marks = ",".join("?" for _ in kinds)
    rows = conn.execute(
        f"SELECT * FROM versions WHERE song_id = ? AND kind IN ({marks}) AND pick_rank IS NOT NULL ORDER BY pick_rank",
        (song_id, *kinds),
    )
    return [_row(r) for r in rows]


def complete(coverage: float | None, threshold: float) -> bool:
    return coverage is not None and coverage >= threshold


def replaces_sheet(new: float | None, kept: float | None, threshold: float) -> bool:
    """Whether a sheet covering ``new`` of the lyrics replaces a kept sheet covering ``kept``.

    Ratings can't be compared across sites, so a sheet from one site meets a
    sheet from another on lyric coverage alone (None: unknown, the song had no
    lyrics to compare with):

    - a complete sheet (coverage at or above ``threshold``) beats an incomplete one;
    - of two incomplete sheets, the one that covers more wins;
    - unknown coverage never displaces a known partial or complete sheet, and a
      partial sheet never displaces one of unknown coverage, which may be complete;
    - a tie keeps the kept sheet.
    """
    if complete(kept, threshold):
        return False
    if complete(new, threshold):
        return True
    return new is not None and kept is not None and new > kept
