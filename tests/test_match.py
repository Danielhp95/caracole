from datetime import UTC, datetime

import pytest

from caracole.config import MatchPolicy
from caracole.match import IndexSong, IndexView, MatchCandidate, MatchResult, match_all, match_song
from caracole.overrides import Overrides
from caracole.songs import get_song, update_song
from caracole.ug.index import mark_built
from caracole.versions import picks, set_picks, song_versions, upsert_version

from conftest import add_song

POLICY = MatchPolicy()


def index(conn, *rows, built=True):
    """Index rows (tab_id, artist_key, song_key, type), inserted directly, in an index a build
    finished; ``built=False`` leaves it partial, as a build stopped part-way does."""
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, ?, '1', 'x', ?)",
        [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows],
    )
    if built:
        mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))


def match(conn, artist, title, overrides=None, artists=None):
    song = add_song(conn, artist, title, artists=artists)
    return match_song(song, IndexView(conn), overrides or Overrides(), POLICY)


def summary(r: MatchResult):
    return r.decision, r.step, r.score, r.artist_key, r.song_key


# --- the index view ---------------------------------------------------------------------


def test_index_view_groups_tabs_by_song_and_splits_variant_labels(conn):
    index(conn, (3, "oasis", "wonderwall", "guitar-pro"), (1, "oasis", "wonderwall", "chords"),
          (2, "oasis", "wonderwall-acoustic", "chords"), (4, "radiohead", "creep", "chords"))
    view = IndexView(conn)
    assert view.songs_for_artist("oasis") == [
        IndexSong("wonderwall", "wonderwall", None, ((1, "chords"), (3, "guitar-pro"))),
        IndexSong("wonderwall-acoustic", "wonderwall", "acoustic", ((2, "chords"),)),
    ]
    assert view.songs_for_artist("nobody") == []
    assert view.artist_keys() == ["oasis", "radiohead"]
    assert view.title_keys() == ["creep", "wonderwall"]
    assert view.songs_for_title("wonderwall") == [
        ("oasis", IndexSong("wonderwall", "wonderwall", None, ((1, "chords"), (3, "guitar-pro")))),
        ("oasis", IndexSong("wonderwall-acoustic", "wonderwall", "acoustic", ((2, "chords"),))),
    ]


# --- the ladder ---------------------------------------------------------------------------


def test_exact_accept_collects_all_types(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwall", "tabs"),
          (3, "oasis", "wonderwall", "guitar-pro"), (4, "oasis", "champagne-supernova", "chords"))
    r = match(conn, "Oasis", "Wonderwall")
    assert summary(r) == ("accept", "exact", 100.0, "oasis", "wonderwall")
    assert r.candidates[0] == MatchCandidate("oasis", "wonderwall", 100.0, "exact")


def test_variant_slugs_join_the_same_song(conn):
    index(conn, (1, "oasis", "wonderwall-acoustic", "chords"), (2, "oasis", "wonderwall-intro", "tabs"),
          (3, "oasis", "wonderwall-ii", "chords"))
    r = match(conn, "Oasis", "Wonderwall")
    assert summary(r) == ("accept", "exact", 100.0, "oasis", "wonderwall")
    assert [(c.song_key, c.score) for c in r.candidates] == [("wonderwall", 100.0), ("wonderwall-ii", 87.0)]


def test_leading_the_and_remaster_suffix(conn):
    index(conn, (1, "beatles", "let-it-be", "chords"))
    assert summary(match(conn, "The Beatles", "Let It Be - Remastered 2009")) == (
        "accept", "exact", 100.0, "beatles", "let-it-be")


def test_exact_title_is_accepted_next_to_a_close_title(conn):
    index(conn, (1, "beatles", "yesterday", "chords"), (2, "beatles", "yesterdays", "chords"))
    assert summary(match(conn, "The Beatles", "Yesterday"))[:2] == ("accept", "exact")


def test_hyphenation_differences_are_exact(conn):
    # "E.T." keys as e-t; UG wrote the slug as "et"
    index(conn, (1, "katy-perry", "et", "chords"), (2, "katy-perry", "roar", "chords"))
    assert summary(match(conn, "Katy Perry", "E.T.")) == ("accept", "exact", 100.0, "katy-perry", "et")


def test_fuzzy_title_accept(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "champagne-supernova", "chords"))
    assert summary(match(conn, "Oasis", "Wonderwal")) == ("accept", "fuzzy_title", 94.7, "oasis", "wonderwall")


def test_close_second_title_forces_review(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwalls", "chords"))
    r = match(conn, "Oasis", "Wonderwal")
    assert summary(r) == ("review", "fuzzy_title", 94.7, "oasis", "wonderwall")
    assert [(c.song_key, c.score) for c in r.candidates] == [("wonderwall", 94.7), ("wonderwalls", 90.0)]


def test_the_same_title_under_another_of_the_songs_artists_is_no_rival(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "liam-gallagher", "wonderwall", "chords"))
    r = match(conn, "Oasis", "Wonderwal", artists=["Oasis", "Liam Gallagher"])
    assert summary(r) == ("accept", "fuzzy_title", 94.7, "oasis", "wonderwall")


def test_low_scores_are_not_found_but_kept_as_candidates(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"))
    r = match(conn, "Oasis", "Supersonic")
    assert summary(r) == ("not_found", None, 20.0, None, None)
    assert r.candidates == (MatchCandidate("oasis", "wonderwall", 20.0, "fuzzy_title"),)


def test_review_band(conn):
    index(conn, (1, "oasis", "champagne-supernova", "chords"))
    assert summary(match(conn, "Oasis", "Champagne Super")) == (
        "review", "fuzzy_title", 88.2, "oasis", "champagne-supernova")


def test_not_found(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"))
    r = match(conn, "Nobody", "Nothing Like It")
    assert (r.decision, r.artist_key, r.song_key, r.candidates) == ("not_found", None, None, ())


def test_fuzzy_artist(conn):
    index(conn, (1, "enanitos-verdes", "lamento-boliviano", "chords"),
          (2, "enanitos-verdes", "la-muralla-verde", "chords"))
    assert summary(match(conn, "Enanitos Verde", "Lamento Boliviano")) == (
        "accept", "fuzzy_artist", 96.6, "enanitos-verdes", "lamento-boliviano")


def test_fuzzy_artist_looks_past_the_artist_already_tried(conn):
    # UG files some tabs under a misspelt duplicate of an artist that also exists correctly spelt.
    index(conn, (1, "red-hot-chili-peppers", "californication", "chords"),
          (2, "red-hot-chilli-peppers", "under-the-bridge", "chords"))
    assert summary(match(conn, "Red Hot Chili Peppers", "Under the Bridge")) == (
        "accept", "fuzzy_artist", 97.7, "red-hot-chilli-peppers", "under-the-bridge")


def test_artist_below_the_gate_falls_through_to_title_only(conn):
    # "Los Enanitos" vs los-enanitos-verdes scores 77, below the gate of 90, and no article
    # form helps. (The real "Enanitos Verdes" case is accepted by the article rule.)
    index(conn, (1, "los-enanitos-verdes", "lamento-boliviano", "chords"),
          (2, "los-enanitos-verdes", "lamento-boliviano", "tabs"),
          (3, "toque-de-queda", "lamento-boliviano", "guitar-pro"))
    r = match(conn, "Los Enanitos", "Lamento Boliviano")
    assert summary(r) == ("review", "title_only", 100.0, "los-enanitos-verdes", "lamento-boliviano")


def test_alias_wins(conn):
    index(conn, (1, "soda", "persiana-americana", "chords"), (2, "soda-stereo", "persiana-americana", "chords"))
    aliased = Overrides(alias={"soda": ("soda-stereo",)})
    assert summary(match(conn, "Soda", "Persiana Americana", aliased)) == (
        "accept", "alias", 100.0, "soda-stereo", "persiana-americana")
    assert summary(match(conn, "Soda", "Persiana Americana - Remasterizado 2007"))[:4] == (
        "accept", "exact", 100.0, "soda")


def test_compact_artist_key(conn):
    index(conn, (1, "acdc", "highway-to-hell", "chords"))
    assert summary(match(conn, "AC/DC", "Highway to Hell")) == ("accept", "exact", 100.0, "acdc", "highway-to-hell")


def test_second_artist_used(conn):
    index(conn, (1, "rob-thomas", "smooth", "chords"))
    assert summary(match(conn, "Santana", "Smooth", artists=["Santana", "Rob Thomas"])) == (
        "accept", "exact", 100.0, "rob-thomas", "smooth")


def test_title_only_is_review(conn):
    index(conn, (1, "jeff-buckley", "hallelujah", "chords"), (2, "leonard-cohen", "hallelujah", "chords"),
          (3, "leonard-cohen", "hallelujah-live", "tabs"), (4, "leonard-cohen", "suzanne", "chords"))
    r = match(conn, "Someone Else", "Hallelujah")
    assert summary(r) == ("review", "title_only", 100.0, "leonard-cohen", "hallelujah")
    # the most-tabbed artist of the title comes first; its variant slugs count as the same song
    assert r.candidates == (MatchCandidate("leonard-cohen", "hallelujah", 100.0, "title_only"),
                            MatchCandidate("jeff-buckley", "hallelujah", 100.0, "title_only"))


def test_ignore_pin_and_match_overrides(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwall-acoustic", "chords"))
    ignore = frozenset({"oasis/wonderwall"})
    pin = {"oasis/wonderwall": (2, 999)}
    over = {"oasis/wonderwall": ("oasis", "wonderwall-ii")}
    song = add_song(conn, "Oasis", "Wonderwall")
    view = IndexView(conn)

    def m(**kw):
        return match_song(song, view, Overrides(**kw), POLICY)

    assert summary(m(ignore=ignore, pin=pin, match=over)) == ("ignored", "override", None, None, None)
    pinned = m(pin=pin)
    assert summary(pinned) == ("pinned", "pin", None, "oasis", "wonderwall") and pinned.pinned == (2, 999)
    assert summary(m(pin=pin, match=over)) == ("pinned", "pin", None, "oasis", "wonderwall-ii")
    assert summary(m(match=over)) == ("accept", "override", 100.0, "oasis", "wonderwall-ii")
    bare = m(pin={"oasis/wonderwall": (85053,)})
    assert summary(bare) == ("pinned", "pin", None, None, None) and bare.pinned == (85053,)


def test_rejected_covers_never_come_back_and_other_covers_still_can(conn):
    # "None of these" in caracole review, for a review on the title alone: UG lists Maná only by bare ids.
    index(conn, (1, "ana-gabriel", "rayando-el-sol", "chords"), (2, "pablo-alboran", "rayando-el-sol", "chords"),
          (3, "pablo-alboran", "rayando-el-sol", "tabs"))
    song = add_song(conn, "Maná", "Rayando el Sol")
    view = IndexView(conn)
    assert [c.artist_key for c in match_song(song, view, Overrides(), POLICY).candidates] == [
        "pablo-alboran", "ana-gabriel"]
    one = Overrides(reject={song.key: frozenset({("pablo-alboran", "rayando-el-sol")})})
    r = match_song(song, view, one, POLICY)
    assert summary(r) == ("review", "title_only", 100.0, "ana-gabriel", "rayando-el-sol")
    assert [c.artist_key for c in r.candidates] == ["ana-gabriel"]
    both = Overrides(reject={song.key: frozenset({("pablo-alboran", "rayando-el-sol"),
                                                  ("ana-gabriel", "rayando-el-sol")})})
    r = match_song(song, view, both, POLICY)
    assert (r.decision, r.candidates) == ("not_found", ())


def test_rejected_titles_of_the_songs_own_artist_never_come_back(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwalls", "chords"))
    song = add_song(conn, "Oasis", "Wonderwal")
    view = IndexView(conn)
    assert match_song(song, view, Overrides(), POLICY).decision == "review"
    # Without its rival, the other title leads clearly: it is accepted.
    r = match_song(song, view, Overrides(reject={song.key: frozenset({("oasis", "wonderwalls")})}), POLICY)
    assert summary(r) == ("accept", "fuzzy_title", 94.7, "oasis", "wonderwall")
    # Nor does a rejected title come back on the title alone.
    both = Overrides(reject={song.key: frozenset({("oasis", "wonderwall"), ("oasis", "wonderwalls")})})
    r = match_song(song, view, both, POLICY)
    assert (r.decision, r.candidates) == ("not_found", ())


def test_a_rejected_exact_title_is_accepted_through_no_step_but_your_match(conn):
    index(conn, (1, "soda-stereo", "persiana-americana", "chords"), (2, "soda", "persiana-americana", "chords"))
    song = add_song(conn, "Soda", "Persiana Americana")
    view = IndexView(conn)
    rejected = {song.key: frozenset({("soda-stereo", "persiana-americana")})}
    aliased = Overrides(alias={"soda": ("soda-stereo",)}, reject=rejected)
    assert summary(match_song(song, view, aliased, POLICY)) == ("accept", "exact", 100.0, "soda", "persiana-americana")
    matched = Overrides(match={song.key: ("soda-stereo", "persiana-americana")}, reject=rejected)
    assert summary(match_song(song, view, matched, POLICY)) == (
        "accept", "override", 100.0, "soda-stereo", "persiana-americana")


def test_pinyin_keys_meet_ug_slugs(conn):
    # A3: 宋冬野 → "song dong ye" → compact "songdongye" meets UG's song-dongye.
    index(conn, (1, "song-dongye", "ban-ma-ban-ma", "chords"), (2, "song-dongye", "an-he-qiao", "chords"))
    assert summary(match(conn, "宋冬野", "斑马，斑马")) == ("accept", "exact", 100.0, "song-dongye", "ban-ma-ban-ma")


def test_pinyin_title_compact_form(conn):
    index(conn, (1, "song-dongye", "banma-banma", "chords"))
    assert summary(match(conn, "宋冬野", "斑马斑马"))[:2] == ("accept", "exact")


def test_pinyin_title_is_also_compared_fuzzily_without_hyphens(conn):
    # 安和桥北 → an-he-qiao-bei; "anheqiaobei" against "anheqiao" scores 84.2 (78.3 with hyphens)
    index(conn, (1, "song-dongye", "anhe-qiao", "chords"))
    assert summary(match(conn, "宋冬野", "安和桥北")) == ("review", "fuzzy_title", 84.2, "song-dongye", "anhe-qiao")


def test_chinese_names_without_slugged_rows_are_not_found(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "song-joong-ki", "my-love", "chords"))
    assert match(conn, "宋冬野", "斑马，斑马").decision == "not_found"


def test_pinyin_titles_must_match_exactly_across_all_artists(conn):
    # Real index: "banmabanma" scored 80 against papon's "banao-banao", an unrelated song, so a
    # fuzzy pinyin title-only review hid 宋冬野 from the to-do page's "Artists to find".
    index(conn, (1, "papon", "banao-banao", "chords"), (2, "anitta", "banana", "chords"))
    r = match(conn, "宋冬野", "斑马，斑马")
    assert (r.decision, r.candidates) == ("not_found", ())


def test_pinyin_title_only_finds_covers_with_or_without_hyphens(conn):
    index(conn, (1, "li-zhi", "ban-ma-ban-ma", "chords"), (2, "li-zhi", "ban-ma-ban-ma", "tabs"),
          (3, "zhao-lei", "banma-banma", "chords"))
    r = match(conn, "宋冬野", "斑马，斑马")
    assert summary(r) == ("review", "title_only", 100.0, "li-zhi", "ban-ma-ban-ma")
    assert r.candidates == (MatchCandidate("li-zhi", "ban-ma-ban-ma", 100.0, "title_only"),
                            MatchCandidate("zhao-lei", "banma-banma", 100.0, "title_only"))


def test_fuzzy_artist_compares_pinyin_without_hyphens(conn):
    # "song-dong-ye" scores 87.0 against "sung-dongye", under the gate; "songdongye" scores 90.0.
    index(conn, (1, "sung-dongye", "ban-ma-ban-ma", "chords"))
    assert summary(match(conn, "宋冬野", "斑马，斑马")) == (
        "accept", "fuzzy_artist", 90.0, "sung-dongye", "ban-ma-ban-ma")


@pytest.mark.parametrize("artist,title,row", [
    # UG's sitemaps write names in Latin letters only; a name you write in two scripts meets them
    # on its Latin part, as on UG's artist pages (normalize.name_forms).
    ("DAOKO", "打上花火 (Uchiage Hanabi)", ("daoko", "uchiage-hanabi")),
    ("BTS", "봄날 (Spring Day)", ("bts", "spring-day")),
    ("Song Dongye (宋冬野)", "斑马斑马", ("song-dongye", "ban-ma-ban-ma")),
    ("Kino (Кино)", "Gruppa Krovi / Группа крови", ("kino", "gruppa-krovi")),
])
def test_names_written_in_two_scripts_meet_ugs_latin_slugs(conn, artist, title, row):
    index(conn, (1, *row, "chords"), (2, row[0], "another-song", "chords"))
    assert summary(match(conn, artist, title)) == ("accept", "exact", 100.0, *row)


def test_a_title_in_two_scripts_is_found_across_artists_only_exactly(conn):
    # As for pinyin: across every artist a romanized part fuzz-matches unrelated titles.
    index(conn, (1, "papon", "banao-banao", "chords"), (2, "zhao-lei", "banma-banma", "chords"))
    r = match(conn, "宋冬野", "斑马 斑马 Banma Banma Zebra Zebra")
    assert summary(r) == ("review", "title_only", 100.0, "zhao-lei", "banma-banma")
    assert [c.artist_key for c in r.candidates] == ["zhao-lei"]


def test_a_generic_part_of_a_title_matches_nothing_on_its_own(conn):
    index(conn, (1, "song-dongye", "remix", "chords"), (2, "other", "remix", "chords"))
    r = match(conn, "Song Dongye (宋冬野)", "斑马斑马 Remix")
    assert r.decision == "not_found" and all(c.score < POLICY.review for c in r.candidates)


def test_title_without_a_key_is_not_found(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"))
    assert match(conn, "Oasis", "!!!").decision == "not_found"


# --- match_all ------------------------------------------------------------------------------


def columns(conn, song_id):
    s = get_song(conn, song_id)
    return (s.match_decision, s.match_step, s.match_score, s.match_artist_key, s.match_song_key,
            s.match_candidates, s.review)


def test_match_all_writes_decisions_candidates_and_the_review_flag(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwalls", "chords"),
          (3, "radiohead", "creep", "chords"))
    creep = add_song(conn, "Radiohead", "Creep", added_at="2026-10-02T00:00:00Z")
    typo = add_song(conn, "Oasis", "Wonderwal")
    changes = match_all(conn, Overrides(), POLICY)
    assert [(c.song.id, c.old, c.new.decision) for c in changes] == [(creep.id, None, "accept"),
                                                                     (typo.id, None, "review")]
    assert columns(conn, creep.id) == ("accept", "exact", 100.0, "radiohead", "creep",
                                       [{"artist_key": "radiohead", "song_key": "creep", "score": 100.0,
                                         "step": "exact"}], False)
    assert columns(conn, typo.id) == ("review", "fuzzy_title", 94.7, "oasis", "wonderwall", [
        {"artist_key": "oasis", "song_key": "wonderwall", "score": 94.7, "step": "fuzzy_title"},
        {"artist_key": "oasis", "song_key": "wonderwalls", "score": 90.0, "step": "fuzzy_title"},
    ], True)
    assert get_song(conn, creep.id).matched_at is not None


def test_match_all_can_match_one_song_alone(conn):
    # `caracole get`: the song asked for now; the others keep what they had.
    index(conn, (1, "oasis", "wonderwall", "chords"), (3, "radiohead", "creep", "chords"))
    creep = add_song(conn, "Radiohead", "Creep")
    wall = add_song(conn, "Oasis", "Wonderwall")
    changes = match_all(conn, Overrides(), POLICY, songs=[wall])
    assert [(c.song.id, c.new.decision) for c in changes] == [(wall.id, "accept")]
    assert get_song(conn, creep.id).match_decision is None


def test_match_all_keeps_at_most_five_candidates(conn):
    index(conn, *[(i, "oasis", f"song-{i}", "chords") for i in range(1, 10)])
    s = add_song(conn, "Oasis", "Song")
    match_all(conn, Overrides(), POLICY)
    assert len(get_song(conn, s.id).match_candidates) == 5


def test_match_all_dry_run_writes_nothing(conn):
    index(conn, (1, "radiohead", "creep", "chords"))
    s = add_song(conn, "Radiohead", "Creep")
    before = conn.execute("SELECT * FROM songs").fetchall()
    changes = match_all(conn, Overrides(ignore=frozenset({"radiohead/creep"})), POLICY, dry_run=True)
    assert [tuple(r) for r in conn.execute("SELECT * FROM songs")] == [tuple(r) for r in before]
    assert [(c.song.id, c.old, c.new.decision) for c in changes] == [(s.id, None, "ignored")]


def test_match_all_marks_dirty_on_new_accept(conn):
    index(conn, (1, "radiohead", "creep", "chords"))
    creep = add_song(conn, "Radiohead", "Creep")
    match_all(conn, Overrides(), POLICY)
    update_song(conn, creep.id, ug_dirty=False)  # the fetch step finished it
    late = add_song(conn, "Oasis", "Wonderwall")
    match_all(conn, Overrides(), POLICY)
    update_song(conn, late.id, ug_dirty=False)
    assert get_song(conn, late.id).match_decision == "not_found"
    index(conn, (2, "oasis", "wonderwall", "chords"))  # the nightly refresh found it
    changes = match_all(conn, Overrides(), POLICY)
    assert {c.song.id: (c.old, c.new.decision) for c in changes} == {
        creep.id: ("accept", "accept"), late.id: ("not_found", "accept")}
    assert get_song(conn, late.id).ug_dirty is True
    assert get_song(conn, creep.id).ug_dirty is False  # unchanged match: nothing to refetch


def test_match_all_marks_dirty_when_a_review_becomes_an_accept_on_the_same_keys(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwalls", "chords"))
    s = add_song(conn, "Oasis", "Wonderwal")
    match_all(conn, Overrides(), POLICY)
    update_song(conn, s.id, ug_dirty=False)
    assert get_song(conn, s.id).match_decision == "review"
    match_all(conn, Overrides(), MatchPolicy(margin=4))  # you loosened the margin in caracole.toml
    assert (get_song(conn, s.id).match_decision, get_song(conn, s.id).ug_dirty) == ("accept", True)


def test_match_all_new_candidates_alone_need_no_refetch(conn):
    index(conn, (1, "radiohead", "creep", "chords"))
    s = add_song(conn, "Radiohead", "Creep")
    match_all(conn, Overrides(), POLICY)
    update_song(conn, s.id, ug_dirty=False)
    index(conn, (2, "radiohead", "creepy-crawl", "chords"))
    match_all(conn, Overrides(), POLICY)
    assert len(get_song(conn, s.id).match_candidates) == 2
    assert get_song(conn, s.id).ug_dirty is False


def test_match_all_marks_dirty_when_the_keys_or_pins_change(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwall-ii", "chords"))
    s = add_song(conn, "Oasis", "Wonderwall")
    match_all(conn, Overrides(), POLICY)
    update_song(conn, s.id, ug_dirty=False)
    match_all(conn, Overrides(match={"oasis/wonderwall": ("oasis", "wonderwall-ii")}), POLICY)
    assert get_song(conn, s.id).ug_dirty is True and get_song(conn, s.id).match_song_key == "wonderwall-ii"

    match_all(conn, Overrides(pin={"oasis/wonderwall": (1,)}), POLICY)
    update_song(conn, s.id, ug_dirty=False)
    match_all(conn, Overrides(pin={"oasis/wonderwall": (1,)}), POLICY)
    assert get_song(conn, s.id).ug_dirty is False
    match_all(conn, Overrides(pin={"oasis/wonderwall": (1, 7)}), POLICY)  # same song, another pinned page
    assert get_song(conn, s.id).ug_dirty is True


def version(conn, song, tab_id, kind="chords", provider="ug"):
    return upsert_version(conn, provider=provider, tab_id=str(tab_id), song_id=song.id,
                          slot="sheet" if kind in ("chords", "acordes") else "guitar", kind=kind, rating=4.5,
                          votes=10, version=1, label=None, url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}",
                          raw={}, now="2026-10-18T03:30:00Z")


def test_a_corrected_match_takes_the_old_matchs_ug_versions_out_of_the_running(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwall-ii", "chords"))
    s = add_song(conn, "Oasis", "Wonderwall")
    match_all(conn, Overrides(), POLICY)
    sheet, gp = version(conn, s, 1), version(conn, s, 3, "guitar-pro")
    lacuerda = version(conn, s, "oasis/wonderwall-1", "acordes", provider="lacuerda")
    set_picks(conn, s.id, ("chords",), [sheet])
    set_picks(conn, s.id, ("guitar-pro",), [gp])
    set_picks(conn, s.id, ("acordes",), [lacuerda])
    match_all(conn, Overrides(), POLICY)  # the same match: nothing changes
    assert len(song_versions(conn, s.id)) == 3

    match_all(conn, Overrides(match={s.key: ("oasis", "wonderwall-ii")}), POLICY)

    # UG's versions were the old match's; LaCuerda's are the song's whatever UG's index says.
    assert [v.tab_id for v in song_versions(conn, s.id)] == ["oasis/wonderwall-1"]
    assert [v.tab_id for v in song_versions(conn, s.id, include_gone=True) if v.stale] == ["1", "3"]
    assert [v.kind for v in picks(conn, s.id, ("chords", "acordes", "guitar-pro"))] == ["acordes"]
    assert get_song(conn, s.id).ug_dirty is True


def test_a_pin_is_stored_as_one_candidate_listing_its_tabs(conn):
    index(conn, (1, "oasis", "wonderwall", "chords"))
    s = add_song(conn, "Oasis", "Wonderwall")
    pins = (1, 11, 12, 13, 14, 15, 16)
    match_all(conn, Overrides(pin={s.key: pins}), POLICY)
    assert get_song(conn, s.id).match_candidates == [
        {"artist_key": "oasis", "song_key": "wonderwall", "score": None, "step": "pin", "tab_ids": list(pins)}]


def test_an_empty_index_keeps_what_the_ladder_found(conn):
    # An index never built, or emptied, can't tell a miss: earlier ladder results stay, overrides still apply.
    index(conn, (1, "radiohead", "creep", "chords"), (2, "oasis", "wonderwall", "chords"))
    creep = add_song(conn, "Radiohead", "Creep")
    wonderwall = add_song(conn, "Oasis", "Wonderwall")
    match_all(conn, Overrides(ignore=frozenset({wonderwall.key})), POLICY)
    update_song(conn, creep.id, ug_dirty=False)
    before = columns(conn, creep.id)
    conn.execute("DELETE FROM ug_index")
    hotel = add_song(conn, "Eagles", "Hotel California")
    newcomer = add_song(conn, "Soda Stereo", "Signos")
    changes = match_all(conn, Overrides(match={hotel.key: ("eagles", "hotel-california")}), POLICY)
    assert columns(conn, creep.id) == before and get_song(conn, creep.id).ug_dirty is False
    # The ignore you took out comes off; a song matched never isn't saved as a miss, and shows as one.
    assert {c.song.id: (c.old, c.new.decision) for c in changes} == {
        creep.id: ("accept", "accept"), wonderwall.id: ("ignored", "not_found"), hotel.id: (None, "accept"),
        newcomer.id: (None, "not_found")}
    assert get_song(conn, wonderwall.id).status == "wanted"
    assert get_song(conn, hotel.id).match_step == "override"
    assert get_song(conn, newcomer.id).match_decision is None


def test_a_partial_index_keeps_what_the_ladder_found_and_saves_no_new_miss(conn):
    # A build stopped part-way: a song whose tabs are in the sitemaps it didn't read isn't missing from
    # UG. match_all holds this for every caller, `caracole review`'s rematch among them.
    index(conn, (1, "radiohead", "creep", "chords"), (2, "oasis", "wonderwall", "chords"), built=False)
    earlier = add_song(conn, "Eagles", "Hotel California")  # matched before, in a sitemap not read yet
    update_song(conn, earlier.id, match_decision="accept", match_step="exact", match_score=100.0,
                match_artist_key="eagles", match_song_key="hotel-california", ug_dirty=False,
                match_candidates=[{"artist_key": "eagles", "song_key": "hotel-california", "score": 100.0,
                                   "step": "exact"}])
    before = columns(conn, earlier.id)
    creep = add_song(conn, "Radiohead", "Creep")
    missing = add_song(conn, "Soda Stereo", "Signos")
    pinned = add_song(conn, "Joaquín Sabina", "Contigo")
    changes = match_all(conn, Overrides(pin={pinned.key: (85053,)}), POLICY)
    assert columns(conn, earlier.id) == before and get_song(conn, earlier.id).ug_dirty is False
    assert get_song(conn, creep.id).match_decision == "accept"  # what the index has is still found
    assert get_song(conn, missing.id).match_decision is None  # not looked up yet, rather than a miss
    assert get_song(conn, pinned.id).match_decision == "pinned"  # and your overrides apply
    assert {c.song.id: c.new.decision for c in changes}[missing.id] == "not_found"  # as `match --dry-run` shows


def test_ignored_songs_get_status_ignored_and_come_back(conn):
    index(conn, (1, "radiohead", "creep", "chords"))
    s = add_song(conn, "Radiohead", "Creep")
    match_all(conn, Overrides(ignore=frozenset({"radiohead/creep"})), POLICY)
    assert get_song(conn, s.id).status == "ignored"
    match_all(conn, Overrides(), POLICY)
    assert (get_song(conn, s.id).status, get_song(conn, s.id).match_decision) == ("wanted", "accept")


def test_an_artist_page_match_is_not_undone_by_the_ladder(conn):
    # A6: the fetch step matched a bare-id song on its UG artist page; the local index can't see it.
    s = add_song(conn, "Joaquín Sabina", "19 Días y 500 Noches")
    update_song(conn, s.id, match_decision="accept", match_step="artist_page", match_score=100.0,
                match_artist_key="joaquin-sabina", match_song_key="19-dias-y-500-noches", ug_dirty=False)
    index(conn, (1, "sabina-ddumba", "19-dias-y-500-noches", "chords"))  # a title-only lookalike
    before = columns(conn, s.id)
    changes = match_all(conn, Overrides(), POLICY)
    assert columns(conn, s.id) == before
    assert (changes[0].old, changes[0].new.decision, changes[0].new.step) == ("accept", "accept", "artist_page")
    match_all(conn, Overrides(match={"joaquin-sabina/19-dias-y-500-noches": ("sabina-ddumba",
                                                                            "19-dias-y-500-noches")}), POLICY)
    assert get_song(conn, s.id).match_step == "override"


def test_none_of_these_leaves_the_song_not_found_for_the_fetch_to_look_further(conn):
    from caracole.ug.fetch import needs_artist_page

    index(conn, (1, "ana-gabriel", "rayando-el-sol", "chords"), (2, "pablo-alboran", "rayando-el-sol", "chords"))
    s = add_song(conn, "Maná", "Rayando el Sol")
    match_all(conn, Overrides(), POLICY)
    assert get_song(conn, s.id).review is True
    shown = frozenset((c["artist_key"], c["song_key"]) for c in get_song(conn, s.id).match_candidates)
    match_all(conn, Overrides(reject={s.key: shown}), POLICY)
    song = get_song(conn, s.id)
    assert (song.match_decision, song.review, song.status) == ("not_found", False, "wanted")
    assert needs_artist_page(song)  # its artist's UG page is read for it, as for any song not found


def test_an_artist_page_match_you_rejected_is_undone(conn):
    s = add_song(conn, "Joaquín Sabina", "19 Días y 500 Noches")
    update_song(conn, s.id, match_decision="accept", match_step="artist_page", match_score=100.0,
                match_artist_key="joaquin-sabina", match_song_key="19-dias-y-500-noches")
    index(conn, (1, "oasis", "wonderwall", "chords"))
    other = Overrides(reject={s.key: frozenset({("joaquin-sabina", "19-y-500")})})
    match_all(conn, other, POLICY)
    assert get_song(conn, s.id).match_step == "artist_page"  # another UG song's rejection: kept (A6)
    match_all(conn, Overrides(reject={s.key: frozenset({("joaquin-sabina", "19-dias-y-500-noches")})}), POLICY)
    assert (get_song(conn, s.id).match_decision, get_song(conn, s.id).match_step) == ("not_found", None)


def test_an_artist_page_match_yields_to_ignore(conn):
    s = add_song(conn, "Joaquín Sabina", "Pongamos Que Hablo de Madrid")
    update_song(conn, s.id, match_decision="accept", match_step="artist_page")
    match_all(conn, Overrides(ignore=frozenset({s.key})), POLICY)
    assert (get_song(conn, s.id).match_decision, get_song(conn, s.id).status) == ("ignored", "ignored")


def test_leading_spanish_article_on_either_side(conn):
    # UG files Enanitos Verdes as los-enanitos-verdes (262 rows, none under enanitos-verdes).
    index(conn, (1, "los-enanitos-verdes", "lamento-boliviano", "chords"), (2, "prisioneros", "tren-al-sur", "chords"))
    assert summary(match(conn, "Enanitos Verdes", "Lamento Boliviano"))[:2] == ("accept", "exact")
    assert match(conn, "Enanitos Verdes", "Lamento Boliviano").artist_key == "los-enanitos-verdes"
    assert summary(match(conn, "Los Prisioneros", "Tren al Sur"))[:2] == ("accept", "exact")
