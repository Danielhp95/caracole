"""peer_sync.py: an import's "keep mine" remembered beside the base (kv ``sync:base:<peer>``'s ``kept``), read back,
merged with the other side's, and compared with, so the next sync doesn't ask again while neither side changed it."""

import json

from caracole import peer_sync as sync
from caracole.db import kv_get, kv_set

U = lambda i, d: sync.Unit(i, i, d)  # noqa: E731
PEER, T0, T1, T2 = "0f1e2d3c4b5a6978", "2026-11-03T10:00:00Z", "2026-11-03T11:00:00Z", "2026-11-03T12:00:00Z"


def test_a_kept_answer_is_kept_beside_the_base_and_read_back(conn):
    sync.record_agreement(conn, PEER, {"song/a": U("song/a", "a1")}, {"song/a": U("song/a", "a1")}, T0)
    assert sync.record_kept(conn, PEER, {"song/b": ("bh", "bt")}, T1) == 1
    assert sync.kept_of(conn, PEER) == {"song/b": ("bh", "bt", T1)}
    assert sync.base_of(conn, PEER) == {"song/a": ("a1", T0)}


def test_a_unit_kept_here_and_changed_on_neither_side_is_this_sides_not_a_conflict():
    [d] = sync.compare({"song/b": U("song/b", "bh")}, {"song/b": U("song/b", "bt")}, {},
                       kept={"song/b": ("bh", "bt", "mine")})
    assert (d.proposal, d.why) == (sync.MINE, sync.KEPT_HERE)


def test_a_change_after_a_kept_answer_is_compared_as_usual():
    kept = {"song/b": ("bh", "bt", "mine")}

    def proposal(h, t):
        return sync.compare({"song/b": U("song/b", h)}, {"song/b": U("song/b", t)}, {}, kept=kept)[0].proposal

    assert (proposal("bh2", "bt"), proposal("bh", "bt2"), proposal("bh2", "bt2")) == (sync.MINE, sync.THEIRS,
                                                                                      sync.CONFLICT)


def test_a_change_after_a_kept_answer_says_so_in_the_usual_words():
    kept = {"song/b": ("bh", "bt", "mine")}
    [gone] = sync.compare({}, {"song/b": U("song/b", "bt")}, {}, kept=kept)
    [changed] = sync.compare({"song/b": U("song/b", "bh")}, {"song/b": U("song/b", "bt2")}, None, kept=kept)
    assert (gone.proposal, gone.why) == (sync.MINE, "gone here since the last sync")
    assert (changed.proposal, changed.why) == (sync.THEIRS, "changed there since the last sync")


def test_a_kept_unit_the_two_hold_alike_is_no_difference():
    assert sync.compare({"song/b": U("song/b", "bt")}, {"song/b": U("song/b", "bt")}, {},
                        kept={"song/b": ("bh", "bt", "mine")}) == []


def test_the_other_sides_kept_answer_is_read_with_its_sides_swapped():
    merged = sync.merged_kept(None, {}, None, {"song/b": ("bt", "bh", T1)})
    assert merged == {"song/b": ("bh", "bt", "theirs")}
    [d] = sync.compare({"song/b": U("song/b", "bh")}, {"song/b": U("song/b", "bt")}, None, kept=merged)
    assert (d.proposal, d.why) == (sync.THEIRS, sync.KEPT_THERE)


def test_the_later_of_an_agreement_and_a_kept_answer_counts_and_a_tie_is_the_agreements():
    kept = {"song/b": ("bh", "bt", T1)}
    assert sync.merged_kept({"song/b": ("same", T2)}, kept, None, {}) == {}
    assert sync.merged_kept({"song/b": ("same", T1)}, kept, None, {}) == {}
    assert sync.merged_kept({"song/b": ("same", T0)}, kept, None, {}) == {"song/b": ("bh", "bt", "mine")}


def test_the_other_sides_agreement_counts_too_and_two_kept_answers_at_once_are_this_sides():
    mine, theirs = {"song/b": ("bh", "bt", T1)}, {"song/b": ("th", "tt", T1)}
    assert sync.merged_kept(None, mine, {"song/b": ("same", T2)}, {}) == {}
    assert sync.merged_kept(None, mine, None, theirs) == {"song/b": ("bh", "bt", "mine")}
    assert sync.merged_kept(None, mine, None, {"song/b": ("th", "tt", T2)}) == {"song/b": ("tt", "th", "theirs")}


def test_an_agreement_drops_the_kept_answer_of_each_unit_it_agrees_on_and_keeps_the_others(conn):
    sync.record_kept(conn, PEER, {"song/b": ("bh", "bt"), "song/c": ("ch", "ct")}, T1)
    sync.record_agreement(conn, PEER, {"song/b": U("song/b", "bt"), "song/c": U("song/c", "ch")},
                          {"song/b": U("song/b", "bt"), "song/c": U("song/c", "ct")}, T2)
    assert sync.kept_of(conn, PEER) == {"song/c": ("ch", "ct", T1)}


def test_a_kept_unit_both_sides_lack_now_is_agreed_lacking_so_one_made_again_is_new_not_a_conflict(conn):
    # kept at a first import, so no base names it; then both sides lose it
    sync.record_kept(conn, PEER, {"song/x": ("xh", "xt")}, T1)
    assert sync.record_agreement(conn, PEER, {}, {}, T2) == 0
    assert sync.kept_of(conn, PEER) == {} and sync.base_of(conn, PEER) == {"song/x": (None, T2)}
    base, kept = sync.base_of(conn, PEER), sync.kept_of(conn, PEER)
    [d] = sync.compare({"song/x": U("song/x", "new")}, {}, sync.merged_base(base, None),
                       kept=sync.merged_kept(base, kept, None, {}))
    assert (d.proposal, d.why) == (sync.MINE, "new here since the last sync")


def test_a_base_with_no_kept_answer_is_written_as_before(conn):
    sync.record_agreement(conn, PEER, {"song/a": U("song/a", "a1")}, {"song/a": U("song/a", "a1")}, T0)
    assert json.loads(kv_get(conn, sync.BASE_KEY + PEER)) == {"format": sync.FORMAT,
                                                              "units": {"song/a": ["a1", T0]}}
    sync.record_kept(conn, PEER, {"song/b": ("bh", None)}, T1)
    sync.record_agreement(conn, PEER, {"song/b": U("song/b", "bt")}, {"song/b": U("song/b", "bt")}, T2)
    assert "kept" not in json.loads(kv_get(conn, sync.BASE_KEY + PEER))


def test_odd_kept_entries_and_a_base_of_another_format_are_read_as_none(conn):
    key = sync.BASE_KEY + PEER
    kv_set(conn, key, json.dumps({"format": sync.FORMAT, "units": {}, "kept": {
        "song/a": ["ah", None, T1], "song/b": ["bh", "bt"], "song/c": [1, "ct", T1], "song/d": "x",
        "song/e": [None, None, None]}}))
    assert sync.kept_of(conn, PEER) == {"song/a": ("ah", None, T1)}
    kv_set(conn, key, json.dumps({"format": 1, "units": {}, "kept": {"song/a": ["ah", None, T1]}}))
    assert sync.kept_of(conn, PEER) == {}
    kv_set(conn, key, "{nonsense")
    assert sync.kept_of(conn, PEER) == {}
    assert sync.kept_of(conn, "never") == {}


def test_no_answer_to_remember_writes_nothing(conn):
    assert sync.record_kept(conn, PEER, {}, T1) == 0
    assert kv_get(conn, sync.BASE_KEY + PEER) is None and sync.base_of(conn, PEER) is None


def test_a_kept_answer_recorded_again_takes_the_place_of_the_one_before(conn):
    sync.record_kept(conn, PEER, {"song/b": ("bh", "bt")}, T1)
    assert sync.record_kept(conn, PEER, {"song/b": ("bh2", "bt2")}, T2) == 1
    assert sync.kept_of(conn, PEER) == {"song/b": ("bh2", "bt2", T2)}


def test_the_state_document_carries_the_kept_answers_and_reads_them_back():
    doc = sync.state_document("a1b2c3d4e5f60718", "0.1.0", "Desk", {}, None, now=T2, kept={"song/b": ("bh", "bt", T1)})
    assert doc["kept"] == {"song/b": ["bh", "bt", T1]}
    assert sync.read_state_document(doc).kept == {"song/b": ("bh", "bt", T1)}
    assert sync.read_state_document({**doc, "kept": {"song/x": [1], "song/y": "z"}}).kept == {}


def test_a_state_document_given_no_kept_answers_is_as_before_and_reads_as_none():
    doc = sync.state_document("a1b2c3d4e5f60718", "0.1.0", "Desk", {}, None, now=T2)
    assert "kept" not in doc
    assert sync.read_state_document(doc).kept == {}
