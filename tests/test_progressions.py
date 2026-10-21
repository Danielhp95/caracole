"""progressions.py: each song's progressions, read as its sheet is rendered, and a progression typed or named."""

from __future__ import annotations

from caracole.db import kv_get_json, kv_set_json
from caracole.overrides import Overrides
from caracole.progressions import (
    KV,
    catalogue,
    label,
    library_progressions,
    read_progression,
    sheet_progressions,
    songs_with,
)
from caracole.render import render_all
from caracole.songs import _PER_SONG_KV, delete_song_kv

from conftest import add_song
from helpers.rendered import fake_chordpro, rendered_song

POP = "I V vi IV"
POP_MINOR = "i ♭VI ♭III ♭VII"  # the same four chords read in the relative minor
ANDALUSIAN = "V i ♭VII ♭VI"  # i ♭VII ♭VI V, turned to start where its numerals sort first

# In C: a verse that plays vi IV I V twice, a chorus I V vi IV, an outro of one chord.
CHO = (
    "{title: Synthetic Song}\n{artist: Placeholder Band}\n{key: C}\n"
    "{comment: Verse}\n"
    "[Am]Words to [F]sing, [C]only for the [G]test\n"
    "[Am]more [F]words, [C]still a [G]test\n"
    "{comment: Chorus}\n"
    "[C]la la [G]la, [Am]la la [F]la\n"
    "{comment: Outro}\n"
    "[C]end\n"
)


def test_a_sheets_sections_are_read_as_numerals_in_the_key_of_its_viewer():
    found = sheet_progressions(CHO, None)
    assert found["key"] == "C major"
    verse, chorus, outro = found["sections"]
    assert verse == {"section": "Verse", "numerals": ["vi", "IV", "I", "V"], "repeats": 2, "key": POP,
                     "name": "the pop progression", "ending": "half"}
    assert (chorus["section"], chorus["numerals"], chorus["key"]) == ("Chorus", ["I", "V", "vi", "IV"], POP)
    assert (outro["numerals"], outro["key"]) == (["I"], "I")


def test_the_key_given_wins_over_the_sheets_own_and_a_sheet_with_no_key_has_one_estimated():
    assert sheet_progressions(CHO, "Am")["key"] == "A minor"
    assert sheet_progressions(CHO, "Am")["sections"][0]["numerals"] == ["i", "♭VI", "♭III", "♭VII"]
    estimated = sheet_progressions(CHO.replace("{key: C}\n", ""), None)
    assert estimated["key"] in ("C major", "A minor")


def test_a_sheet_with_no_headings_no_chords_it_can_read_or_only_a_chord_legend():
    plain = "{title: X}\n[G]one [D]two\n[Em]three [C]four\n"
    (only,) = sheet_progressions(plain, "G")["sections"]
    assert (only["section"], only["key"]) == (None, POP)
    # N.C. is left out; a chord legend's line (its fingerings) is no chord played
    legend = "{title: X}\nCadd9 (x32033)\n{comment: Verse}\n[N.C.]hey [G]one [N.C.]two [D]three\n"
    (verse,) = sheet_progressions(legend, "G")["sections"]
    assert verse["numerals"] == ["I", "V"]
    assert sheet_progressions("{title: X}\nwords alone\n", None) is None
    assert sheet_progressions("{title: X}\n{comment: Intro}\n[N.C.]hey\n", "G") is None


def test_a_progression_typed_as_numerals_in_any_rotation_or_spelling():
    for typed in ("vi IV I V", "vi–IV–I–V", "I V vi IV", "vi, IV, I, V", "  IV I V vi "):
        wanted = read_progression(typed)
        assert wanted is not None, typed
        assert wanted.key == POP and wanted.name == "the pop progression"
        assert wanted.keys == frozenset({POP, POP_MINOR})  # its name's other reading too
        assert wanted.label == "I–V–vi–IV"
    flat = read_progression("I bVII IV")
    assert flat.key == "I ♭VII IV" and flat.name == "I–♭VII–IV"
    unnamed = read_progression("I iii IV")
    assert (unnamed.keys, unnamed.name, unnamed.label) == (frozenset({"I iii IV"}), None, "I–iii–IV")
    assert read_progression("Imaj7 vi7 ii7 V7").key == "I vi ii V"


def test_a_progression_named_from_the_catalogue():
    andalusian = read_progression("andalusian")
    # In a minor key, and read in the relative major (vi–V–IV–V/vi)
    assert andalusian.name == "the Andalusian cadence" and andalusian.keys == {ANDALUSIAN, "IV V/vi vi V"}
    assert andalusian.label == "the Andalusian cadence"
    assert read_progression("Andalusian Cadence").keys == andalusian.keys
    assert read_progression("the pop progression").keys == {POP, POP_MINOR}
    assert len(read_progression("blues").keys) == 4  # the 12-bar blues, in each of its forms
    assert read_progression("royal road").name == "the royal road"


def test_words_that_are_no_progression():
    for text in ("", "hello world", "I", "I I I", "V", "vi IV hello", "pop", "progression", "the cadence",
                 "Wonderwall", "via"):
        assert read_progression(text) is None, text


def test_the_catalogue_by_key_and_a_keys_label():
    names = catalogue()
    assert names[POP] == names[POP_MINOR] == "the pop progression"
    assert names[ANDALUSIAN] == "the Andalusian cadence"
    assert label("I V vi IV") == "I–V–vi–IV"


def test_rendering_a_sheet_records_its_progressions_for_the_library(conn, cfg):
    song = rendered_song(conn, cfg)  # G D Em C, in G
    record = kv_get_json(conn, f"{KV}{song.id}")
    assert record["key"] == "G major"
    assert [s["key"] for s in record["sections"]] == [POP]
    assert library_progressions(conn) == {song.id: [{"key": POP, "plays": "I–V–vi–IV"}]}


def test_an_auto_sheet_is_read_when_there_is_no_human_one_and_a_song_with_no_sheet_has_none(conn, cfg):
    auto = rendered_song(conn, cfg, "Placeholder Band", "Synthetic Song", auto=True)  # C G, estimated in G
    record = kv_get_json(conn, f"{KV}{auto.id}")
    assert record["key"] == "G major" and [s["numerals"] for s in record["sections"]] == [["IV", "I"]]
    bare = add_song(conn, "Nobody", "Nothing Kept")
    kv_set_json(conn, f"{KV}{bare.id}", {"key": "C major", "sections": []})  # from a sheet it kept once
    render_all(conn, cfg, Overrides(), runner=fake_chordpro)
    assert kv_get_json(conn, f"{KV}{bare.id}") is None


def test_a_songs_progressions_go_with_it(conn, cfg):
    song = rendered_song(conn, cfg)
    assert KV in _PER_SONG_KV
    delete_song_kv(conn, song.id)
    assert kv_get_json(conn, f"{KV}{song.id}") is None


def test_only_a_section_of_two_chords_or_more_is_a_progression_for_the_library(conn, cfg):
    song = add_song(conn)
    kv_set_json(conn, f"{KV}{song.id}", sheet_progressions(CHO, None))
    # The verse and the chorus play one cycle: once in the library's data, as the first section plays it.
    assert library_progressions(conn) == {song.id: [{"key": POP, "plays": "vi–IV–I–V"}]}


def test_songs_with_a_progression_and_the_sections_that_play_it(conn, cfg):
    pop = add_song(conn, "Placeholder Band", "Synthetic Song")
    kv_set_json(conn, f"{KV}{pop.id}", sheet_progressions(CHO, None))
    minor = add_song(conn, "Another Band", "In A Minor")
    kv_set_json(conn, f"{KV}{minor.id}", sheet_progressions(CHO, "Am"))
    other = add_song(conn, "Third Band", "Blues")
    kv_set_json(conn, f"{KV}{other.id}", sheet_progressions("{title: X}\n{comment: A}\n[C]a [F]b [G]c\n", "C"))
    kv_set_json(conn, f"{KV}999", {"key": "C major", "sections": [{"key": POP}]})  # no such song: left out
    found = songs_with(conn, read_progression("vi IV I V"))
    assert [(p.song.title, p.sections, p.key) for p in found] == [
        ("In A Minor", ["Verse", "Chorus"], "A minor"), ("Synthetic Song", ["Verse", "Chorus"], "C major")]
    assert [p.song.title for p in songs_with(conn, read_progression("I IV V"))] == ["Blues"]
    assert songs_with(conn, read_progression("ii V I")) == []


def test_a_record_a_device_or_an_older_caracole_left_odd_is_read_as_none(conn, cfg):
    song = add_song(conn)
    for odd in ([], "x", {"sections": "x"}, {"sections": [1, {"key": 2}, {"numerals": ["I"]}]}):
        kv_set_json(conn, f"{KV}{song.id}", odd)
        assert library_progressions(conn) == {} and songs_with(conn, read_progression(POP)) == []
