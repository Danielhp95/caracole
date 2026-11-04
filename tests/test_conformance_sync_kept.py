"""The remembered answer and a sync's parts, for the phone: what peer_sync.py answers for an import's "keep mine",
kept beside the base, and for a sync of some of the three parts, written for the Kotlin sync lane (core/sync's
Compare and Scope) to agree with (docs/superpowers/plans/2026-11-03-sync-redesign.md, §3.1 and §3.2).

**Vectors**: ``helpers.corpus.jsonl``'s, a header, then a record a line, ``{fn, case, in, out}``: ``fn`` the function
of ``caracole.peer_sync``, ``case`` what the record shows, ``in`` its arguments by name, ``out`` what it answers (a
tuple as an array). No fixture: the functions that read the database read one kv, which ``in`` gives.

- sync/kept.jsonl:
  - ``merged_kept``: ``in`` ``{mine, mine_kept, theirs, theirs_kept}``, each side's base ``{id: [digest or null,
    when]}`` (or null) and its kept answers ``{id: [here, there, when]}``, ``here`` that side's; ``out`` ``{id:
    [here, there, chooser]}``, ``here`` this side's, ``chooser`` ``"mine"`` or ``"theirs"``. Stamps are compared as
    Python compares strings, by code point;
  - ``compare``: ``in`` ``{mine, theirs, base, kept}``, each side's units ``{id: {id, label, digest}}``, the merged
    base ``{id: digest or null}`` (or null: never synced) and ``merged_kept``'s answer (or null); ``out`` each
    difference ``[id, proposal, why]``, in order;
  - ``record_kept`` and ``record_agreement``: ``in`` ``{kv, peer, args}``, ``kv`` the text kv ``sync:base:<peer>``
    holds before (null: none), ``args`` ``[chosen, at]`` (``chosen`` ``{id: [here, there]}``) or ``[mine, theirs,
    at]`` (as ``in.mine`` of ``compare``); ``out`` that kv's text after, byte for byte (null: none), and
    ``returned`` what the function returned;
  - ``kept_of``: ``in`` ``{kv, peer}``, ``out`` ``{id: [here, there, when]}``;
  - ``read_state_document``: ``in`` ``{doc}``, a state document, ``out`` its ``PeerState.kept``.
- sync/scope.jsonl:
  - ``in_scope``: ``in`` ``{found, parts, listed, holds}``, ``found`` differences ``{id, label, mine, theirs,
    proposal, why}`` (each side ``{id, label, digest}`` or null), ``listed`` ``{song unit: [songbook units]}``,
    ``holds`` a file's parts (each null when not given); ``out`` the ids kept, in order;
  - ``listed_songs``: ``in`` ``{books, units}``, ``books`` ``{songbook unit: its value}``, ``units`` a list of unit
    ids; ``out`` ``{song unit: [songbook units]}``;
  - ``change_of``: ``in`` ``{d, base, kept}`` (``d`` as ``found``'s, ``base`` ``{id: digest or null}`` or null,
    ``kept`` ``{id: [here, there, chooser]}`` or null), ``out`` ``[here, there]``;
  - ``names_of``: ``in`` ``{unit_id, label}``, ``out`` ``[artist, title]`` or null.

The bases the cases start from are of ``peer_sync.FORMAT`` (those of another format beside it, ``_format``), so a
FORMAT bump regenerates vectors that show what they did. Names in other scripts come from the keys corpus's
``EDGES`` (test_conformance_keys.py). The answers are the same under any hash seed
(``test_the_vectors_are_the_same_whatever_the_hash_seed``). Regenerate with ``CARACOLE_CORPUS=write``
(tests/conformance/README.md).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from helpers.corpus import VECTORS, check, jsonl, plain

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
MADE_BY = "tests/test_conformance_sync_kept.py"
KEPT, SCOPE = VECTORS / "sync" / "kept.jsonl", VECTORS / "sync" / "scope.jsonl"
T0, T1, T2, T3 = "2026-11-03T10:00:00Z", "2026-11-03T11:00:00Z", "2026-11-03T12:00:00Z", "2026-11-03T13:00:00Z"
PEER = "0f1e2d3c4b5a6978"
WIDE, NARROW = "song/\U0001f600", "song/｡"  # code-point order puts the supplementary letter last; UTF-16's first


def _record(fn: str, case: str, given: dict[str, Any], call: Callable[[], Any], **extra: Any) -> dict[str, Any]:
    return {"fn": fn, "case": case, "in": plain(given), "out": plain(call()), **extra}


def _u(unit_id: str, digest: str | None, label: str | None = None):
    from caracole import peer_sync as sync

    return None if digest is None else sync.Unit(unit_id, unit_id if label is None else label, digest)


def _units(**digests: str) -> dict:
    return {f"song/{name}": _u(f"song/{name}", digest) for name, digest in digests.items()}


def _d(unit_id: str, mine: str | None = "m", theirs: str | None = "t", label: str | None = None,
       proposal: str = "conflict", why: str = ""):
    from caracole import peer_sync as sync

    return sync.Difference(unit_id, unit_id if label is None else label, _u(unit_id, mine, label),
                           _u(unit_id, theirs, label), proposal, why)


def _song(artist: str, title: str) -> str:
    from caracole.normalize import identity_key

    return f"song/{identity_key(artist, title)}"


# --- kept.jsonl ----------------------------------------------------------------------------------------------------


def merged_kept_records() -> list[dict]:
    from caracole import peer_sync as sync

    a = "song/a"
    cases = [
        ("nothing kept on either side: none, whatever the bases", {a: ("1", T0)}, {}, {a: ("1", T1)}, {}),
        ("this side's kept answer alone: this side's, as stored", None, {a: ("h", "t", T1)}, None, {}),
        ("the other side's alone: read with its two digests swapped", None, {}, None, {a: ("t", "h", T1)}),
        ("this side's agreement later than its kept answer: the agreement", {a: ("x", T2)}, {a: ("h", "t", T1)},
         None, {}),
        ("this side's agreement at the same time: the agreement", {a: ("x", T1)}, {a: ("h", "t", T1)}, None, {}),
        ("this side's agreement earlier: the kept answer", {a: ("x", T0)}, {a: ("h", "t", T1)}, None, {}),
        ("the other side's agreement later than this side's kept answer: the agreement", None, {a: ("h", "t", T1)},
         {a: ("x", T2)}, {}),
        ("the other side's agreement at the same time as its kept answer: the agreement", None, {}, {a: ("x", T1)},
         {a: ("t", "h", T1)}),
        ("an agreement at the same time as the other side's kept answer, this side's: the agreement",
         {a: (None, T1)}, {}, None, {a: ("t", "h", T1)}),
        ("the other side's agreement at the same time as this side's kept answer: the agreement", None,
         {a: ("h", "t", T1)}, {a: ("x", T1)}, {}),
        ("both sides' kept answers at the same time: this side's", None, {a: ("h", "t", T1)}, None,
         {a: ("t2", "h2", T1)}),
        ("the other side's kept answer later than this side's: the other's, swapped", None, {a: ("h", "t", T1)},
         None, {a: ("t2", "h2", T2)}),
        ("this side's kept answer later than the other's: this side's", None, {a: ("h", "t", T2)}, None,
         {a: ("t2", "h2", T1)}),
        ("a lack kept, on either side", None, {"song/a": (None, "t", T1)}, None, {"song/b": ("t", None, T1)}),
        ("stamps compared as text, by code point: a supplementary letter after U+FF61",
         {a: ("x", "2026-11-03T10:00:00｡")}, {a: ("h", "t", "2026-11-03T10:00:00\U0001f600")}, None, {}),
        ("stamps compared as text: an offset sorts before Z", {a: ("x", T0)},
         {a: ("h", "t", "2026-11-03T10:00:00+00:00")}, None, {}),
        ("a unit a base alone names is no kept answer", {"song/z": ("1", T0)}, {a: ("h", "t", T1)},
         {"song/y": ("2", T3)}, {}),
        ("several units, each by its own records, in code-point order",
         {"song/b": ("x", T2), "song/c": ("y", T0)},
         {"song/b": ("bh", "bt", T1), "song/c": ("ch", "ct", T1), WIDE: ("wh", "wt", T1), NARROW: ("nh", "nt", T1)},
         {"song/d": ("z", T3)}, {"song/d": ("dt", "dh", T2), "song/e": ("et", "eh", T1), "song/c": ("c2", "c1", T0)}),
    ]
    return [_record("merged_kept", case, {"mine": mine, "mine_kept": mine_kept, "theirs": theirs,
                                          "theirs_kept": theirs_kept},
                    lambda: sync.merged_kept(mine, mine_kept, theirs, theirs_kept))
            for case, mine, mine_kept, theirs, theirs_kept in cases]


def compare_records() -> list[dict]:
    from caracole import peer_sync as sync

    a = "song/a"
    here, there = ("h", "t", "mine"), ("h", "t", "theirs")
    cases = [
        ("kept here, changed on neither side since: this side's", _units(a="h"), _units(a="t"), {}, {a: here}),
        ("kept there, changed on neither side since: the other's", _units(a="h"), _units(a="t"), {}, {a: there}),
        ("kept here, changed here since: this side's, as usual", _units(a="h2"), _units(a="t"), {}, {a: here}),
        ("kept here, changed there since: the other's", _units(a="h"), _units(a="t2"), {}, {a: here}),
        ("kept there, changed here since: this side's", _units(a="h2"), _units(a="t"), {}, {a: there}),
        ("kept here, changed on both sides since: a conflict", _units(a="h2"), _units(a="t2"), {}, {a: here}),
        ("kept, alike on both sides now: no difference", _units(a="x"), _units(a="x"), {}, {a: here}),
        ("kept, gone here since", {}, _units(a="t"), {}, {a: here}),
        ("kept, gone there since", _units(a="h"), {}, {}, {a: there}),
        ("a lack kept here, the other's version not taken: this side's", {}, _units(a="t"), {},
         {a: (None, "t", "mine")}),
        ("a lack kept here, new here since", _units(a="h"), _units(a="t"), {}, {a: (None, "t", "mine")}),
        ("a lack kept there, new there since", _units(a="h"), _units(a="t"), {}, {a: ("h", None, "theirs")}),
        ("kept with no base at all: the kept answer still counts", _units(a="h"), _units(a="t"), None, {a: there}),
        ("kept with no base, beside units compared as a first sync: only here, only there, never synced",
         _units(a="h", c="c", e="e1"), _units(a="t", d="d", e="e2"), None, {a: here}),
        ("kept over a base that makes it a conflict: the kept answer", _units(a="h"), _units(a="t"), {a: "0"},
         {a: here}),
        ("kept beside units compared as usual, in order",
         {"song/a": _u("song/a", "h", "Zed - A"), "song/b": _u("song/b", "b2", "Alpha - B"),
          "removed/x/y": _u("removed/x/y", "r", "X - Y (removed)")},
         {"song/a": _u("song/a", "t", "Zed - A"), "song/b": _u("song/b", "b1", "Alpha - B"),
          "song/c": _u("song/c", "c", "Beta - C"), "removed/x/y": _u("removed/x/y", "r2", "X - Y (removed)")},
         {"song/b": "b1"}, {"song/a": here, "removed/x/y": ("r", "r2", "theirs"), "song/z": here}),
        ("no kept answers: as usual", _units(a="h"), _units(a="t"), {a: "0"}, None),
        ("an empty map of kept answers: as usual", _units(a="h"), _units(a="t"), {a: "0"}, {}),
    ]
    return [_record("compare", case, {"mine": mine, "theirs": theirs, "base": base, "kept": kept},
                    lambda: [[d.id, d.proposal, d.why] for d in sync.compare(mine, theirs, base, kept=kept)])
            for case, mine, theirs, base, kept in cases]


def _format(offset: int = 0) -> int:
    """``peer_sync.FORMAT``, or a format beside it (another format's base is none), so that bumping it regenerates
    vectors that show what they did."""
    from caracole import peer_sync as sync

    return sync.FORMAT + offset


def _stored(units: dict | None = None, kept: dict | None = None, fmt: int | None = None) -> str:
    doc: dict[str, Any] = {"format": _format() if fmt is None else fmt, "units": units or {}}
    if kept is not None:
        doc["kept"] = kept
    return json.dumps(doc, ensure_ascii=False)


ODD_KEPT = {"song/a": ["ah", None, T1], "song/b": ["bh", "bt"], "song/c": [1, "ct", T1], "song/d": "x",
            "song/e": [None, None, None], "song/f": ["fh", "ft", T1, "more"], "song/g": {"here": "gh"}}


def _with_kv(conn: sqlite3.Connection, before: str | None, call: Callable[[], Any]) -> tuple[Any, str | None]:
    from caracole import db
    from caracole import peer_sync as sync

    key = sync.BASE_KEY + PEER
    conn.execute("DELETE FROM kv WHERE key = ?", (key,))
    if before is not None:
        db.kv_set(conn, key, before)
    returned = call()
    return returned, db.kv_get(conn, key)


def record_kept_records(conn: sqlite3.Connection) -> list[dict]:
    from caracole import peer_sync as sync

    cases = [
        ("no base before: an empty base, the answers beside it", None, {"song/b": ("bh", "bt")}, T1),
        ("a base before: its units as they were, the answers beside them", _stored({"song/a": ["a1", T0]}),
         {"song/b": ("bh", "bt")}, T1),
        ("answers before: one answered again takes its place, the others stay",
         _stored({"song/a": ["a1", T0]}, {"song/b": ["b0", "t0", T0], "song/c": ["ch", "ct", T0]}),
         {"song/b": ("bh", "bt"), "song/d": ("dh", "dt")}, T2),
        ("a lack kept, on either side", _stored({}), {"song/x": (None, "t"), "song/y": ("h", None)}, T1),
        ("a base of another format before is none",
         _stored({"song/a": ["a1", T0]}, {"song/c": ["c", "c", T0]}, _format(-1)),
         {"song/b": ("bh", "bt")}, T1),
        ("an untagged base before is none", json.dumps({"song/old": ["x", T0]}), {"song/b": ("bh", "bt")}, T1),
        ("a base that isn't JSON is none", "{nonsense", {"song/b": ("bh", "bt")}, T1),
        ("odd kept answers before are left out", _stored({}, ODD_KEPT), {"song/z": ("zh", "zt")}, T1),
        ("nothing to remember, no base: nothing written", None, {}, T1),
        ("nothing to remember, a base: as it was, byte for byte",
         '{"format": %d, "units": {"song/b": ["x", "y"]}}' % _format(), {}, T1),
        ("keys in code-point order: a supplementary letter after U+FF61", None,
         {WIDE: ("w", "w2"), NARROW: ("n", "n2"), "song/a": ("a", "a2")}, T1),
    ]
    out = []
    for case, before, chosen, at in cases:
        returned, after = _with_kv(conn, before, lambda: sync.record_kept(conn, PEER, chosen, at))
        out.append({"fn": "record_kept", "case": case, "in": plain({"kv": before, "peer": PEER, "args": [chosen, at]}),
                    "out": after, "returned": returned})
    return out


def record_agreement_records(conn: sqlite3.Connection) -> list[dict]:
    from caracole import peer_sync as sync

    kept = {"song/b": ["bh", "bt", T1], "song/c": ["ch", "ct", T1]}
    cases = [
        ("an agreed unit drops its kept answer, the others stay", _stored({}, kept), _units(b="bt", c="ch"),
         _units(b="bt", c="ct")),
        ("a unit both lack that the base names drops its kept answer",
         _stored({"song/g": ["x", T0]}, {"song/g": ["gh", "gt", T1], "song/c": ["ch", "ct", T1]}), _units(c="ch"),
         _units(c="ct")),
        ("a kept unit both lack, the base naming none: agreed lacking, its answer dropped", _stored({}, kept), {},
         {}),
        ("a kept unit both lack, beside one still held otherwise: the one lacking agreed, the other kept",
         _stored({"song/a": ["a0", T0]}, kept), _units(a="a0", c="ch"), _units(a="a0", c="ct2")),
        ("a kept unit the two still hold otherwise stays kept, its base too",
         _stored({"song/b": ["b0", T0]}, kept), _units(b="bh", c="ch"), _units(b="bt", c="ct")),
        ("every kept answer dropped: no kept member", _stored({}, {"song/b": ["bh", "bt", T1]}), _units(b="x"),
         _units(b="x")),
        ("an agreement on units no answer was kept for leaves every kept answer as it was",
         _stored({"song/a": ["a0", T0]}, kept), _units(a="a1", b="bh", c="ch"), _units(a="a1", b="bt", c="ct")),
        ("a kept unit one side lacks now stays kept", _stored({}, kept), _units(b="bh"), _units(c="ct")),
        ("no kept answer before: as before", _stored({"song/a": ["a1", T0]}), _units(a="a2", b="b"),
         _units(a="a2", b="c")),
        ("odd kept answers before are left out", _stored({}, ODD_KEPT), _units(z="1", a="ah"),
         _units(z="1", a="at")),
        ("kept answers in a base of another format are none", _stored({}, kept, _format(-1)), _units(c="2"),
         _units(c="3")),
        ("keys in code-point order: a supplementary letter after U+FF61",
         _stored({}, {WIDE: ["w", "w2", T1], NARROW: ["n", "n2", T1], "song/a": ["a", "a2", T1]}),
         {"song/x": _u("song/x", "1"), WIDE: _u(WIDE, "w"), NARROW: _u(NARROW, "n"), "song/a": _u("song/a", "a")},
         {"song/x": _u("song/x", "1"), WIDE: _u(WIDE, "w2"), NARROW: _u(NARROW, "n2"), "song/a": _u("song/a", "a2")}),
    ]
    out = []
    for case, before, mine, theirs in cases:
        returned, after = _with_kv(conn, before, lambda: sync.record_agreement(conn, PEER, mine, theirs, T2))
        out.append({"fn": "record_agreement", "case": case,
                    "in": plain({"kv": before, "peer": PEER, "args": [mine, theirs, T2]}), "out": after,
                    "returned": returned})
    return out


def kept_of_records(conn: sqlite3.Connection) -> list[dict]:
    from caracole import peer_sync as sync

    cases = [
        ("no base: none", None),
        ("a base with no kept answer: none", _stored({"song/a": ["a1", T0]})),
        ("kept answers, a lack among them", _stored({}, {"song/a": ["ah", None, T1], "song/b": [None, "bt", T1]})),
        ("odd entries left out", _stored({}, ODD_KEPT)),
        ("a kept member that isn't an object: none", _stored({}, [["song/a", "h", "t", T1]])),
        ("a base of another format: none", _stored({}, {"song/a": ["ah", "at", T1]}, _format(1))),
        ("an untagged base: none", json.dumps({"kept": {"song/a": ["ah", "at", T1]}})),
        ("a base that isn't JSON: none", "{nonsense"),
        ("a base that isn't an object: none", "[2]"),
    ]
    out = []
    for case, before in cases:
        read, _ = _with_kv(conn, before, lambda: sync.kept_of(conn, PEER))
        out.append({"fn": "kept_of", "case": case, "in": {"kv": before, "peer": PEER}, "out": plain(read)})
    return out


def state_records() -> list[dict]:
    from caracole import peer_sync as sync

    doc = sync.state_document("a1b2c3d4e5f60718", "0.1.0", "Desk", {}, None, now=T2, indexes={})
    cases = [
        ("no kept member: none", ...),
        ("an empty one: none", {}),
        ("kept answers, a lack among them", {"song/a": ["ah", None, T1], "song/b": [None, "bt", T1]}),
        ("odd entries left out", ODD_KEPT),
        ("a kept member that isn't an object: none", [["song/a", "h", "t", T1]]),
        ("a null one: none", None),
    ]
    out = []
    for case, kept in cases:
        given = dict(doc) if kept is ... else {**doc, "kept": kept}
        out.append(_record("read_state_document", case, {"doc": given},
                           lambda: sync.read_state_document(given).kept))
    return out


def kept_records(conn: sqlite3.Connection) -> list[dict]:
    return [*merged_kept_records(), *compare_records(), *record_kept_records(conn), *record_agreement_records(conn),
            *kept_of_records(conn), *state_records()]


# --- scope.jsonl ---------------------------------------------------------------------------------------------------

SONG, OTHER, BOOK, BOOK2 = "song/eagles/hotel california", "song/pomme/mononoke", "songbook/campfire", "songbook/z"


def in_scope_records() -> list[dict]:
    from caracole import peer_sync as sync

    every = [_d(SONG), _d(OTHER), _d("removed/x/y"), _d("alias/x"), _d("artist_url/x"), _d("block/7"), _d(BOOK),
             _d(BOOK2), _d("unknown/x")]
    lacking = [_d(SONG, theirs=None), _d(OTHER), _d("removed/x/y", theirs=None), _d("block/7", theirs=None),
               _d(BOOK, theirs=None), _d(BOOK2), _d("unknown/x", theirs=None)]
    parts = list(sync.PARTS)
    cases = [
        ("every part: every known unit, in the order found", every, parts, None, None),
        ("the library alone: songs, tombstones and the entries about artists and tabs, no songbook", every,
         ["library"], None, None),
        ("the songbooks alone, listing nothing: the songbooks alone", every, ["songbooks"], None, None),
        ("the songbooks alone bring the songs they list and no other", every, ["songbooks"], {SONG: [BOOK]}, None),
        ("a listed tombstone or entry isn't brought: songs alone are", every, ["songbooks"],
         {"removed/x/y": [BOOK], "alias/x": [BOOK], OTHER: [BOOK2]}, None),
        ("songs listed, the songbooks not asked: not brought", every, ["indexes"], {SONG: [BOOK]}, None),
        ("no part: nothing", every, [], {SONG: [BOOK]}, None),
        ("the indexes alone: no unit", every, ["indexes"], None, None),
        ("parts in any order, one twice, one unknown", every, ["songbooks", "library", "library", "lyrics"], None,
         None),
        ("a song only here and one only there, listed, in a sync of the songbooks: both come along",
         [_d(SONG, theirs=None, proposal="mine", why="only here"),
          _d(OTHER, mine=None, proposal="theirs", why="new there since the last sync")],
         ["songbooks"], {SONG: [BOOK], OTHER: [BOOK]}, None),
        ("a listed song gone on a side, in a sync of the songbooks: never removed, given, taken or asked",
         [_d("song/x/a", theirs=None, proposal="theirs", why="gone there since the last sync"),
          _d("song/x/b", mine=None, proposal="mine", why="gone here since the last sync"),
          _d("song/x/c", mine=None, proposal="conflict", why="changed on both sides since the last sync"),
          _d("song/x/d", theirs=None, proposal="conflict", why="changed on both sides since the last sync"),
          _d("song/x/e", proposal="conflict"), _d(BOOK, theirs=None, proposal="theirs")],
         ["songbooks"], {f"song/x/{n}": [BOOK] for n in "abcde"}, None),
        ("a listed song gone on a side, the library asked too: as the library's",
         [_d("song/x/a", theirs=None, proposal="theirs"), _d("song/x/b", mine=None, proposal="mine"),
          _d("song/x/c", mine=None, proposal="conflict")],
         ["songbooks", "library"], {f"song/x/{n}": [BOOK] for n in "abc"}, None),
        ("a file of the songbooks alone never reads a song it lacks as removed",
         [_d(SONG, theirs=None), _d(OTHER), _d(BOOK)], ["songbooks"], {SONG: [BOOK], OTHER: [BOOK]}, ["songbooks"]),
        ("a file of the library alone may remove a song, never a songbook", lacking, parts, None, ["library"]),
        ("a file of the songbooks alone may remove a songbook, never a song", lacking, parts, None, ["songbooks"]),
        ("a file of the indexes alone removes nothing", lacking, parts, None, ["indexes"]),
        ("a file holding no part removes nothing", lacking, parts, None, []),
        ("a file holding every part may remove anything known", lacking, parts, None, parts),
        ("a unit of a part a file doesn't hold, which it has, is still compared", [_d(BOOK), _d(SONG, mine=None)],
         parts, None, ["library"]),
        ("nothing found: nothing", [], parts, None, None),
    ]
    return [_record("in_scope", case, {"found": found, "parts": asked, "listed": listed, "holds": holds},
                    lambda: [d.id for d in sync.in_scope(found, asked, listed=listed, holds=holds)])
            for case, found, asked, listed, holds in cases]


def _book(name: str, *texts: str) -> dict[str, Any]:
    return {"name": name, "songs": [[text, {}] for text in texts]}


def listed_songs_records() -> list[dict]:
    from caracole import peer_sync as sync
    from test_conformance_keys import EDGES

    eagles = _song("Eagles", "Hotel California")
    earth, cut_other_way = _song("Earth - Wind", "Fire"), _song("Earth", "Wind - Fire")
    zebra = _song("宋冬野", "斑马斑马")
    pairs = [(EDGES[i], EDGES[(i * 37 + 11) % len(EDGES)]) for i in range(0, len(EDGES), 9)]
    named = [f"{artist} - {title}" for artist, title in pairs]
    held = [_song(artist, title) for artist, title in pairs[::2]]
    cases = [
        ("an entry by its artist and title", {BOOK: _book("Campfire", "Eagles - Hotel California")}, [eagles, OTHER]),
        ("an entry by any cut of its name: an artist's name holding ' - '",
         {BOOK: _book("Campfire", "Earth - Wind - Fire")}, [earth, OTHER]),
        ("an entry two cuts of which are songs of the units: both listed",
         {BOOK: _book("Campfire", "Earth - Wind - Fire")}, [earth, cut_other_way]),
        ("an entry written otherwise: Traditional characters, case, spaces",
         {BOOK: _book("Campfire", "宋冬野 - 斑馬斑馬", "EAGLES  -  hotel california")}, [zebra, eagles]),
        ("a song two songbooks list, one twice: each songbook once, sorted",
         {BOOK2: _book("Z", "Eagles - Hotel California", "eagles - hotel california"),
          BOOK: _book("Campfire", "Eagles - Hotel California", "Nobody - Here")}, [eagles]),
        ("an entry with a setting lists as one without",
         {BOOK: {"name": "Campfire", "songs": [["Eagles - Hotel California", {"key": "G", "capo": 2}]]}}, [eagles]),
        ("an entry the units don't hold lists nothing", {BOOK: _book("Campfire", "Nobody - Here")}, [eagles]),
        ("an entry with nothing on a side of its cut, or no cut, lists nothing",
         {BOOK: _book("Campfire", " - Hotel California", "Eagles - ", "Eagles-Hotel California",
                      "Eagles — Hotel California", "Eagles Hotel California")}, [eagles, _song("Eagles-Hotel", "x")]),
        ("songbooks and entries that can't be read list nothing",
         {BOOK: {"name": "x", "songs": "Eagles - Hotel California"}, BOOK2: None, "songbook/c": {"name": "c"},
          "songbook/d": {"songs": [["Eagles - Hotel California"], [7, {}], "Eagles - Hotel California",
                                   ["Eagles - Hotel California", {}, "more"], {"text": "Eagles - Hotel California"}]},
          "songbook/e": ["Eagles - Hotel California"]}, [eagles]),
        ("an entry is read by its text alone, whatever its setting is: null, a number, a list",
         {BOOK: {"name": "Campfire", "songs": [["Eagles - Hotel California", None]]},
          BOOK2: {"name": "Z", "songs": [["Eagles - Hotel California", 7]]},
          "songbook/c": {"name": "C", "songs": [["Eagles - Hotel California", ["x"]]]}}, [eagles]),
        ("a songbook with no name, or one that isn't text, lists its songs",
         {BOOK: {"songs": [["Eagles - Hotel California", {}]]},
          BOOK2: {"name": 7, "songs": [["Eagles - Hotel California", {}]]}}, [eagles]),
        ("a unit of another kind with a song's key isn't listed",
         {BOOK: _book("Campfire", "Eagles - Hotel California")}, [f"removed/{eagles[5:]}", f"songbook/{eagles[5:]}"]),
        ("no songbook", {}, [eagles]),
        ("no unit", {BOOK: _book("Campfire", "Eagles - Hotel California")}, []),
        ("names from the keys corpus's edges, half of them held", {BOOK: _book("Edges", *named),
                                                                    BOOK2: _book("Z", *named[::3])}, held),
    ]
    return [_record("listed_songs", case, {"books": books, "units": units},
                    lambda: sync.listed_songs(books, units)) for case, books, units in cases]


def change_of_records() -> list[dict]:
    from caracole import peer_sync as sync

    base = {SONG: "b"}
    cases = [
        ("changed there alone", _d(SONG, "b", "t"), base, None),
        ("changed here alone", _d(SONG, "m", "b"), base, None),
        ("changed on both sides", _d(SONG, "m", "t"), base, None),
        ("gone here, changed there", _d(SONG, None, "t"), base, None),
        ("gone there, here as agreed", _d(SONG, "b", None), base, None),
        ("new here, both lacked it", _d(SONG, "m", None), {SONG: None}, None),
        ("new on both sides: the base doesn't name it", _d(SONG, "m", "t"), {}, None),
        ("new there, the base naming another unit", _d(SONG, None, "t"), {OTHER: "x"}, None),
        ("no base: on this side alone, new here", _d(SONG, "m", None), None, None),
        ("no base: on the other side alone, new there", _d(SONG, None, "t"), None, None),
        ("no base: on both, changed on both", _d(SONG, "m", "t"), None, None),
        ("since a kept answer: changed here", _d(SONG, "bh2", "bt"), {}, {SONG: ("bh", "bt", "mine")}),
        ("since a kept answer: changed on neither side", _d(SONG, "bh", "bt"), None, {SONG: ("bh", "bt", "theirs")}),
        ("since a kept answer: gone here, new there", _d(SONG, None, "t"), base, {SONG: ("bh", None, "mine")}),
        ("since a kept lack: new here", _d(SONG, "h", "t"), None, {SONG: (None, "t", "mine")}),
        ("a kept answer of another unit: the base counts", _d(SONG, "m", "b"), base, {OTHER: ("x", "y", "mine")}),
        ("a songbook, by the same rules", _d(BOOK, "m", None, "the songbook Campfire"), {BOOK: "m"}, None),
    ]
    return [_record("change_of", case, {"d": d, "base": given, "kept": kept},
                    lambda: sync.change_of(d, given, kept)) for case, d, given, kept in cases]


def names_of_records() -> list[dict]:
    from caracole import peer_sync as sync
    from test_conformance_keys import EDGES

    cases = [
        ("a song's label, cut at its one ' - '", _song("Eagles", "Hotel California"), "Eagles - Hotel California"),
        ("the cut whose key is the unit's: an artist's name holding ' - '", _song("Earth - Wind", "Fire"),
         "Earth - Wind - Fire"),
        ("the cut whose key is the unit's: a title holding ' - '", _song("Earth", "Wind - Fire"),
         "Earth - Wind - Fire"),
        ("no cut whose key is the unit's: the first", "song/x/y", "A - B - C"),
        ("a label written otherwise than the key: its cut", _song("宋冬野", "斑马斑马"), "宋冬野 - 斑馬斑馬"),
        ("a label with no ' - ': no names", "song/x/y", "Nameless"),
        ("a label cut with no spaces: no names", "song/x/y", "Eagles-Hotel California"),
        ("an empty label: no names", "song/x/y", ""),
        ("a label of nothing but its cut", "song//", " - "),
        ("a cut with spaces kept as written", _song("Eagles", "Hotel California"), "Eagles  -  Hotel California"),
        ("a tombstone: no names", "removed/eagles/hotel california", "Eagles - Hotel California (removed)"),
        ("a songbook: no names", BOOK, "the songbook Campfire"),
        ("an alias: no names", "alias/eagles", "the alias of eagles"),
        ("an unknown kind: no names", "unknown/x - y", "X - Y"),
    ]
    for i in range(0, len(EDGES), 5):
        artist, title = EDGES[i], EDGES[(i * 37 + 11) % len(EDGES)]
        cases.append(("a name of the keys corpus's edges", _song(artist, title), f"{artist} - {title}"))
    return [_record("names_of", case, {"unit_id": unit_id, "label": label},
                    lambda: sync.names_of(unit_id, label)) for case, unit_id, label in cases]


def scope_records() -> list[dict]:
    return [*in_scope_records(), *listed_songs_records(), *change_of_records(), *names_of_records()]


# --- the tests -----------------------------------------------------------------------------------------------------


def kept_text(conn: sqlite3.Connection) -> str:
    return jsonl(kept_records(conn), corpus="sync/kept", made_by=MADE_BY)


def scope_text() -> str:
    return jsonl(scope_records(), corpus="sync/scope", made_by=MADE_BY)


def test_kept_jsonl_is_what_the_rules_answer(conn):
    check(KEPT, kept_text(conn))


def test_scope_jsonl_is_what_the_rules_answer():
    check(SCOPE, scope_text())


def test_each_function_has_ten_cases_or_more_and_each_case_a_name_of_its_own(conn):
    for records in (kept_records(conn), scope_records()):
        by_fn: dict[str, list[str]] = {}
        for r in records:
            by_fn.setdefault(r["fn"], []).append(r["case"])
        for fn, cases in by_fn.items():
            if fn in ("kept_of", "read_state_document"):
                assert len(cases) >= 6, fn
            else:
                assert len(cases) >= 10, fn
            if fn not in ("names_of",):
                assert len(set(cases)) == len(cases), fn


def test_the_vectors_show_what_the_design_says(conn):
    from caracole import peer_sync as sync

    kept = {(r["fn"], r["case"]): r["out"] for r in kept_records(conn)}
    assert kept["compare", "kept here, changed on neither side since: this side's"] == [
        ["song/a", sync.MINE, sync.KEPT_HERE]]
    assert kept["compare", "kept there, changed on neither side since: the other's"] == [
        ["song/a", sync.THEIRS, sync.KEPT_THERE]]
    assert kept["compare", "kept, alike on both sides now: no difference"] == []
    assert kept["merged_kept", "the other side's alone: read with its two digests swapped"] == {
        "song/a": ["h", "t", "theirs"]}
    assert kept["merged_kept", "stamps compared as text, by code point: a supplementary letter after U+FF61"] == {
        "song/a": ["h", "t", "mine"]}
    assert "kept" not in json.loads(kept["record_agreement", "every kept answer dropped: no kept member"])
    assert kept["record_kept", "nothing to remember, no base: nothing written"] is None
    # the bases the cases start from are of this FORMAT, so the answers merge into them
    assert json.loads(kept["record_kept", "a base before: its units as they were, the answers beside them"]) == {
        "format": sync.FORMAT, "units": {"song/a": ["a1", T0]}, "kept": {"song/b": ["bh", "bt", T1]}}
    assert kept["kept_of", "kept answers, a lack among them"] == {"song/a": ["ah", None, T1],
                                                                 "song/b": [None, "bt", T1]}
    assert json.loads(kept["record_agreement", "a kept unit both lack, the base naming none: agreed lacking, its "
                                               "answer dropped"]) == {
        "format": sync.FORMAT, "units": {"song/b": [None, T2], "song/c": [None, T2]}}
    assert kept["merged_kept", "the other side's agreement at the same time as this side's kept answer: the "
                               "agreement"] == {}
    assert kept["compare", "kept with no base, beside units compared as a first sync: only here, only there, never "
                           "synced"] == [["song/a", sync.MINE, sync.KEPT_HERE], ["song/c", sync.MINE, "only here"],
                                         ["song/d", sync.THEIRS, "only there"],
                                         ["song/e", sync.CONFLICT, "on both sides, different, and never synced"]]
    scope = {(r["fn"], r["case"]): r["out"] for r in scope_records() if r["fn"] != "names_of"}
    assert scope["in_scope", "a file of the songbooks alone never reads a song it lacks as removed"] == [OTHER, BOOK]
    assert scope["in_scope", "a file of the indexes alone removes nothing"] == [OTHER, BOOK2]
    assert scope["in_scope", "a listed song gone on a side, in a sync of the songbooks: never removed, given, taken "
                             "or asked"] == ["song/x/e", BOOK]
    assert scope["listed_songs", "an entry two cuts of which are songs of the units: both listed"] == {
        _song("Earth - Wind", "Fire"): [BOOK], _song("Earth", "Wind - Fire"): [BOOK]}
    names = [r for r in scope_records() if r["fn"] == "names_of"]
    assert {r["case"] for r in names if r["case"].startswith("a name of")} and all(
        r["out"] is None or r["in"]["label"] == " - ".join(r["out"]) for r in names)


@pytest.mark.slow  # the vectors made twice, in two processes
def test_the_vectors_are_the_same_whatever_the_hash_seed(tmp_path):
    from conftest import subprocess_pythonpath

    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(f"{SRC}{os.pathsep}{TESTS}"),
           "CARACOLE_YTDLP_BIN": str(tmp_path / "no-yt-dlp"), "CARACOLE_SERVICE_FILE": str(tmp_path / "no-service")}
    script = "import sys, test_conformance_sync_kept as m; m.write_all(sys.argv[1])"
    running = {seed: subprocess.Popen([sys.executable, "-c", script, str(tmp_path / f"seed-{seed}")],
                                      env={**env, "PYTHONHASHSEED": seed}, cwd=TESTS) for seed in ("1", "2")}
    made = {}
    for seed, process in running.items():
        assert process.wait(timeout=300) == 0, seed
        out = tmp_path / f"seed-{seed}"
        made[seed] = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
    assert made["1"] == made["2"] and sorted(made["1"]) == ["kept.jsonl", "scope.jsonl"]


def write_all(out: str) -> None:
    """Both vectors written into ``out``, over a database migrated there: what the hash seed test compares."""
    from caracole import db

    folder = Path(out)
    folder.mkdir(parents=True)
    (state := folder.with_name(folder.name + "-state")).mkdir()
    conn = db.connect(state / "caracole.sqlite")
    try:
        (folder / "kept.jsonl").write_text(kept_text(conn), encoding="utf-8")
        (folder / "scope.jsonl").write_text(scope_text(), encoding="utf-8")
    finally:
        conn.close()
