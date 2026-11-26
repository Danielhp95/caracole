"""What a sync or an import took and gave, for the phone's Journal: commands/peer.py's words for a unit taken or given
(``done_line``, ``done_lines``), stated once as data and held by a vector the Kotlin sync replays (core.sync's
SyncSaid, the server's SyncRoutes.said).

**Runtime data** (tests/conformance/data/caracole/sync/said.json): ``done``, the word of a unit ``taken`` and
``given`` (peer.DONE's); ``removed_label``, a removal's name around the unit's (peer_sync.REMOVED_LABEL, ``{}`` the
name); ``conflict_came``, what a conflict settled says after it, by the way it went (peer.CONFLICT_CAME); ``most``,
the units said by name a way (peer.DONE_MOST); ``more``, the line after them (peer.DONE_MORE, ``{}`` how many more).

**Vector** (tests/conformance/vectors/sync/said.jsonl): ``helpers.corpus.jsonl``'s, a header, then a record a line,
``{fn: "done_lines", case, in, out}``: ``in`` ``{taken, given, left, found}``, a sync's units taken and given (ids, in
order), left (``[id, why]``) and the differences as compared (scope.jsonl's ``found``); ``out`` ``{done, said}``:
``done_lines``' answer, and ``said``, the lines the phone's Journal says of that outcome, those, then ``left_line``'s
of each change left (none for ``SONG_HERE``; no unsettled conflict among them, whose words are each device's own).
Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import json
from typing import Any

from helpers.corpus import DATA, VECTORS, check, jsonl, plain

MADE_BY = "tests/test_conformance_sync_said.py"
SAID_DATA, SAID = DATA / "sync" / "said.json", VECTORS / "sync" / "said.jsonl"


def said_json() -> str:
    from caracole import peer_sync as sync
    from caracole.commands import peer

    data = {"done": {way: peer.DONE[way] for way in ("taken", "given")}, "removed_label": sync.REMOVED_LABEL,
            "conflict_came": dict(peer.CONFLICT_CAME), "most": peer.DONE_MOST, "more": peer.DONE_MORE}
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def _unit(unit_id: str, label: str, digest: str | None):
    from caracole import peer_sync as sync

    return None if digest is None else sync.Unit(unit_id, label, digest)


def _d(unit_id: str, label: str, mine: str | None, theirs: str | None, proposal: str, why: str = ""):
    from caracole import peer_sync as sync

    return sync.Difference(unit_id, label, _unit(unit_id, label, mine), _unit(unit_id, label, theirs), proposal, why)


def said_records() -> list[dict[str, Any]]:
    from caracole import peer_sync as sync
    from caracole.commands import peer

    creep = _d("song/radiohead/creep", "Radiohead - Creep", None, "t", sync.THEIRS, "new there since the last share")
    hysteria = _d("song/muse/hysteria", "Muse - Hysteria", "m", None, sync.MINE, "new here since the last share")
    gone = _d("song/oasis/wonderwall", "Oasis - Wonderwall", "m", None, sync.THEIRS,
              "gone there since the last share")
    tomb = _d("removed/oasis/wonderwall", "Oasis - Wonderwall (removed)", None, "t", sync.THEIRS,
              "new there since the last share")
    alone = _d("removed/blur/song-2", "Blur - Song 2 (removed)", None, "t", sync.THEIRS,
               "new there since the last share")
    given_gone = _d("song/estopa/tu-calorro", "Estopa - Tu Calorro", None, "t", sync.MINE,
                    "gone here since the last share")
    book = _d("songbook/campfire", "songbook Campfire", "m", "t", sync.THEIRS, "changed there since the last share")
    book_gone = _d("songbook/wedding", "songbook Wedding", "m", None, sync.THEIRS, "gone there since the last share")
    both = _d("song/blur/song-2", "Blur - Song 2", "m", "t", sync.CONFLICT, "both books changed it since the last share")
    other = _d("song/pulp/disco-2000", "Pulp - Disco 2000", "m", "t", sync.CONFLICT,
               "both books changed it since the last share")
    spaced = _d("songbook/wedding-set", "songbook Wedding\n set", "m", "t", sync.THEIRS)
    many = [_d(f"song/band/song-{n:02d}", f"Band - Song {n:02d}", None, "t", sync.THEIRS) for n in range(1, 26)]
    many_given = [_d(f"song/group/tune-{n:02d}", f"Group - Tune {n:02d}", "m", None, sync.MINE) for n in range(1, 22)]
    ids = lambda ds: [d.id for d in ds]  # noqa: E731
    cases = [
        ("took only", [creep], [], [], [creep]),
        ("gave only", [], [hysteria], [], [hysteria]),
        ("took and gave", [creep], [hysteria], [], [creep, hysteria]),
        ("a removal taken: the song's line alone, its tombstone going with it", [tomb, gone], [], [], [tomb, gone]),
        ("a tombstone taken alone: by its label, which names the removal", [alone], [], [], [alone]),
        ("a removal given", [], [given_gone], [], [given_gone]),
        ("a songbook taken, and one removed", [book, book_gone], [], [], [book, book_gone]),
        ("a conflict settled each way: the side that came", [both], [other], [], [both, other]),
        ("one left: said as left alone, never as taken", [creep], [], [(hysteria.id, sync.CHANGED_HERE)],
         [creep, hysteria]),
        ("a tombstone left because its song is here: no line", [creep], [], [(tomb.id, sync.SONG_HERE)],
         [creep, tomb]),
        ("nothing taken or given: nothing said", [], [], [], [creep]),
        ("a unit not among the differences: by its id", [], [], [], []),
        ("a name over two lines: on one", [spaced], [], [(book.id, peer.SKIPPED)], [spaced, book]),
        (f"more than {peer.DONE_MOST} a way: the first by name, then how many more", many, many_given, [],
         many + many_given),
        (f"{peer.DONE_MOST} exactly: every one by name", many[:peer.DONE_MOST], [], [], many),
    ]
    records = []
    for case, taken, given, left, found in cases:
        taken_ids, given_ids = ids(taken), ids(given)
        if case.startswith("a unit not among"):
            taken_ids, given_ids = ["alias/Oasis"], ["block/4242"]
        done = peer.done_lines(taken_ids, given_ids, found)
        labels = {d.id: d.label for d in found}
        said = done + [peer.left_line(labels.get(u) or u, why) for u, why in left if why != sync.SONG_HERE]
        records.append({"fn": "done_lines", "case": case,
                        "in": plain({"taken": taken_ids, "given": given_ids, "left": [list(e) for e in left],
                                     "found": found}),
                        "out": {"done": done, "said": said}})
    return records


def said_text() -> str:
    return jsonl(said_records(), corpus="sync/said", made_by=MADE_BY)


def test_said_json_is_peer_pys_words():
    check(SAID_DATA, said_json())


def test_said_jsonl_is_what_done_lines_answers():
    check(SAID, said_text())


def test_the_vector_shows_what_the_words_say():
    records = {r["case"]: r["out"] for r in said_records()}
    assert records["took and gave"]["done"] == ["Took Radiohead - Creep", "Gave Muse - Hysteria"]
    assert records["a removal taken: the song's line alone, its tombstone going with it"]["done"] == [
        "Took Oasis - Wonderwall (removed)"]
    assert records["a conflict settled each way: the side that came"]["done"] == [
        "Took Blur - Song 2: changed on both sides, theirs kept", "Gave Pulp - Disco 2000: changed on both sides, ours kept"]
    assert records["one left: said as left alone, never as taken"]["said"] == [
        "Took Radiohead - Creep", "Left as it was: Muse - Hysteria: changed here since compared"]
    assert records["nothing taken or given: nothing said"] == {"done": [], "said": []}
    bounded = records["more than 20 a way: the first by name, then how many more"]["done"]
    assert len(bounded) == 42 and bounded[20] == "Took … and 5 more" and bounded[-1] == "Gave … and 1 more"
