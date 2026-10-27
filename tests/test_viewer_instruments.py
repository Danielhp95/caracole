"""caracole.viewer.instruments: the instruments the viewer draws chords for (guitar, the ukuleles, piano), their
shapes, the piano's voicings, the easy keys, and what a page's data carries for them; version.py's capo folded in
for an instrument that takes none."""

from __future__ import annotations

import pytest

from caracole.viewer import instruments, page
from caracole.viewer.instruments import (
    BARITONE,
    GUITAR,
    INSTRUMENTS,
    PIANO,
    UKULELE,
    UKULELE_LOW_G,
    chord_shapes,
    easy_keys,
    is_easy,
    piano_key,
    piano_positions,
    stacked,
    ukulele_quality,
)
from caracole.viewer.page import key_line_text, viewer_key
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import QUALITIES, Chord, Key, parse_chord
from caracole.viewer.version import Version, _shapes, for_instrument, played_key
from caracole.viewer.voicings import LICENSE_FILE, load_voicings, notes_of, plays, subset_chords_db


# --- the instruments --------------------------------------------------------------------------------------


def test_the_instruments_the_viewer_offers_in_its_menus_order():
    assert [(i.id, i.name, i.kind) for i in INSTRUMENTS] == [
        ("guitar", "Guitar", "strings"), ("ukulele", "Ukulele", "strings"),
        ("ukulele-low-g", "Ukulele, low G", "strings"), ("baritone", "Baritone ukulele", "strings"),
        ("piano", "Piano", "keys")]
    assert GUITAR.tuning == (40, 45, 50, 55, 59, 64)  # E2 A2 D3 G3 B3 E4
    assert UKULELE.tuning == (67, 60, 64, 69)  # G4 C4 E4 A4: the G string high, re-entrant
    assert UKULELE_LOW_G.tuning == (55, 60, 64, 69)  # G3
    assert BARITONE.tuning == (50, 55, 59, 64)  # D3 G3 B3 E4: the guitar's top four
    assert [i.capo for i in INSTRUMENTS] == [True, True, True, True, False]
    assert PIANO.tuning == () and all(i.sounds == 0 for i in INSTRUMENTS)  # all at concert pitch
    assert all(i.about for i in INSTRUMENTS)


def test_an_address_names_an_instrument_or_gets_the_guitar():
    assert instruments.instrument("ukulele") is UKULELE
    assert instruments.instrument("piano") is PIANO
    assert instruments.instrument(None) is GUITAR and instruments.instrument("kazoo") is GUITAR


# --- the ukuleles' shapes -----------------------------------------------------------------------------------

# chords-db's lib/ukulele.json, cut down: its roots spelled with flats, its own standard tuning.
UKE_DOC = {
    "main": {"strings": 4, "fretsOnChord": 4, "name": "ukulele"},
    "tunings": {"standard": ["G4", "C4", "E4", "A4"]},
    "chords": {
        "Db": [{"key": "Db", "suffix": "major", "positions": [
            {"frets": [1, 1, 1, 4], "fingers": [1, 1, 1, 4], "baseFret": 1, "barres": [1]},
            {"frets": [1, 1, 1, 1], "fingers": [1, 1, 1, 1], "baseFret": 1, "barres": [1]},  # Ab Db F Bb: not Db
        ]}],
        "C": [{"key": "C", "suffix": "minor", "positions": [
            {"frets": [0, 3, 3, 3], "fingers": [0, 1, 2, 3], "baseFret": 1, "barres": []},
        ]}, {"key": "C", "suffix": "13b9", "positions": [  # a quality caracole hasn't
            {"frets": [0, 0, 0, 3], "fingers": [0, 0, 0, 3], "baseFret": 1, "barres": []},
        ]}],
    },
}


def test_chords_db_ukulele_shapes_are_read_on_its_own_tuning_with_its_roots_spelled_flat():
    data = subset_chords_db(UKE_DOC)
    assert data[""][1] == [["1114", "1114", 1, [1]]]  # Db: Ab4 Db4 F4 Db5
    assert data["m"][0] == [["0333", "0123", 1, []]]  # Cm: G4 Eb4 G4 C5
    assert "13b9" not in data and all(len(roots) == 12 for roots in data.values())


def test_every_vendored_ukulele_shape_plays_its_chord_with_the_g_string_high_or_low():
    data = load_voicings("ukulele")
    assert len(data) >= 19 and sum(len(p) for roots in data.values() for p in roots) > 800
    for quality, roots in data.items():
        assert "/" not in quality  # chords-db's ukulele has no slash chords
        for root, positions in enumerate(roots):
            assert len(positions) <= 4
            chord = Chord(root, quality)
            for position in positions:
                assert len(position[0]) == 4, position
                for inst in (UKULELE, UKULELE_LOW_G):
                    assert plays(position, chord, inst.tuning), (inst.id, quality, root, position)


def test_the_baritone_plays_the_ukuleles_shapes_a_fourth_lower_each_one_its_chord():
    # Its strings are a ukulele's a fourth lower (DGBE, the 4th string low): a ukulele's shape for the root five
    # semitones up sounds the chord on it.
    data = load_voicings("ukulele")
    for quality in data:
        for root in range(12):
            shapes = chord_shapes(BARITONE, Chord(root, quality))
            assert shapes == data[quality][(root + 5) % 12]
            for position in shapes:
                assert plays(position, Chord(root, quality), BARITONE.tuning), (quality, root, position)
    assert chord_shapes(BARITONE, Chord(7, ""))[0][0] == "0003"  # G is a ukulele's C shape
    assert notes_of(["0003", "0003", 1, []], BARITONE.tuning) == [50, 55, 59, 67]  # D3 G3 B3 G4


def test_the_ukuleles_open_shapes_come_first():
    shape = lambda name: chord_shapes(UKULELE, parse_chord(name))[0][0]  # noqa: E731
    assert [shape(n) for n in ("C", "Am", "F", "G", "Dm", "G7", "Bb", "A")] == [
        "0003", "2000", "2010", "0232", "2210", "0212", "3211", "2100"]
    assert notes_of(["0003", "0003", 1, []], UKULELE.tuning) == [67, 60, 64, 72]  # G4 C4 E4 C5
    assert notes_of(["0003", "0003", 1, []], UKULELE_LOW_G.tuning) == [55, 60, 64, 72]


def test_a_quality_the_ukulele_has_no_shapes_for_shows_its_nearest():
    assert ukulele_quality("m7") == "m7" and ukulele_quality("") == ""
    assert ukulele_quality("5") == ""  # no power chords: the plain chord
    assert ukulele_quality("9") == "7" and ukulele_quality("m9") == "m7"
    assert ukulele_quality("13") == "6"  # the first of the largest it has, as the guitar's nearest is chosen
    assert ukulele_quality("add11") == ""
    # chords-db's four-string ninths, elevenths and thirteenths leave the root out: none is kept.
    assert not {"9", "11", "13", "m9", "maj9", "5", "add11"} & set(load_voicings("ukulele"))


def test_a_slash_chord_on_a_ukulele_shows_the_plain_chord():
    assert chord_shapes(UKULELE, parse_chord("C/E")) == chord_shapes(UKULELE, parse_chord("C"))
    assert chord_shapes(UKULELE, parse_chord("Am/G")) == chord_shapes(UKULELE, parse_chord("Am"))


def test_the_ukuleles_shapes_come_with_chords_dbs_licence():
    text = LICENSE_FILE.read_text(encoding="utf-8")
    assert "voicings-ukulele.json" in text and "lib/ukulele.json" in text
    assert "df06fa7b425cf5fd29485ff6591236b3557e3fac" in text and "MIT License" in text


# --- the piano's -------------------------------------------------------------------------------------------


def test_a_piano_chord_is_its_root_position_then_two_inversions_with_its_root_in_the_bass():
    assert piano_positions(parse_chord("C")) == [
        [48, 60, 64, 67],  # C3; C4 E4 G4
        [48, 64, 67, 72],  # E4 G4 C5
        [48, 55, 60, 64],  # G3 C4 E4
    ]
    assert piano_positions(parse_chord("Am")) == [[45, 57, 60, 64], [45, 60, 64, 69], [45, 64, 69, 72]]
    assert piano_positions(parse_chord("C5")) == [[48, 60, 67], [48, 55, 60]]  # two notes: one inversion


def test_a_slash_chords_bass_is_the_lowest_note_and_the_left_hands():
    c_e = piano_positions(parse_chord("C/E"))
    assert [p[0] for p in c_e] == [52] * 3  # E3
    assert [p[1:] for p in c_e] == [p[1:] for p in piano_positions(parse_chord("C"))]
    am_g = piano_positions(parse_chord("Am/G"))
    assert am_g[0] == [43, 57, 60, 64]  # G2; A3 C4 E4: the right hand plays the chord's own notes


@pytest.mark.parametrize(("name", "stack"), [
    ("C13", [0, 4, 7, 10, 2, 9]),  # C E G Bb, then D and A above the octave
    ("Cadd9", [0, 4, 7, 2]),
    ("C6", [0, 4, 7, 9]),
    ("C6/9", [0, 4, 7, 9, 2]),
    ("Csus2", [0, 2, 7]),
    ("C9sus4", [0, 5, 7, 10, 2]),
    ("C7#9", [0, 4, 7, 10, 3]),
    ("Cdim7", [0, 3, 6, 9]),
    ("Cm7b5", [0, 3, 6, 10]),
    ("Cmaj7#11", [0, 4, 7, 11, 6]),
    ("C11", [0, 4, 7, 10, 2, 5]),
])
def test_a_pianist_stacks_a_chord_up_from_its_root(name, stack):
    assert stacked(parse_chord(name)) == stack
    root_position = piano_positions(parse_chord(name))[0][1:]
    assert [(n - 60) % 12 for n in root_position] == stack and root_position == sorted(root_position)


def test_every_piano_position_plays_its_chord_in_the_hands_ranges():
    for quality in QUALITIES:
        for root in range(12):
            for bass in (None, (root + 4) % 12, (root + 10) % 12):
                chord = Chord(root, quality, bass)
                positions = piano_positions(chord)
                assert len(positions) == min(3, len(chord.intervals)), chord
                for low, *right in positions:
                    assert {n % 12 for n in right} == {(root + i) % 12 for i in chord.intervals}, chord
                    assert right == sorted(right) and len(set(right)) == len(right)
                    assert 53 <= right[0] <= 64 and 41 <= low <= 52 and low < right[0]
                    assert low % 12 == (root if bass is None else bass)
                assert len({tuple(p) for p in positions}) == len(positions)


def test_the_piano_files_a_chord_by_its_suffix_and_its_bass():
    assert piano_key(parse_chord("Am7")) == "piano:m7|"
    assert piano_key(parse_chord("C/E")) == "piano:|4"
    assert piano_key(parse_chord("Dm/C")) == "piano:m|10"
    assert chord_shapes(PIANO, parse_chord("C"), 2) == piano_positions(parse_chord("D"))


def test_an_answer_kept_is_handed_out_as_a_copy():
    table = instruments.piano_table(parse_chord("C"))
    table[0][0].append(99)
    table[1].clear()
    keys = easy_keys("ukulele")
    keys["ionian"][0].append("changed")
    keys["aeolian"].clear()
    assert instruments.piano_table(parse_chord("C"))[0][0] == [48, 60, 64, 67]
    assert instruments.piano_table(parse_chord("C"))[1] == piano_positions(parse_chord("Db"))
    assert easy_keys("ukulele")["ionian"][0] == [0, "C"] and easy_keys("ukulele")["aeolian"]


# --- easy keys --------------------------------------------------------------------------------------------


def test_the_ukuleles_easy_keys_and_the_baritones():
    uke = easy_keys("ukulele")
    assert uke["ionian"] == [[0, "C"], [5, "F"], [7, "G"], [10, "Bb"]]
    assert uke["aeolian"] == [[2, "Dm"], [9, "Am"]]
    assert uke["dorian"] == [[0, "C dorian"], [2, "D dorian"], [7, "G dorian"], [9, "A dorian"]]  # C, F, G, Bb's notes
    bari = easy_keys("baritone")
    assert bari["ionian"] == [[0, "C"], [2, "D"], [5, "F"], [7, "G"]]
    assert bari["aeolian"] == [[4, "Em"], [9, "Am"]]
    assert is_easy("ukulele", Key(9, "aeolian")) and not is_easy("ukulele", Key(4, "aeolian"))
    assert is_easy("baritone", Key(4, "aeolian"))


# --- what a chord shows, as viewer.js shows it ---------------------------------------------------------------


def test_the_guitars_shapes_are_versions():
    sheet = parse_sheet("{title: T}\n{define: G base-fret 1 frets 3 2 0 0 3 3}\n[G]la [C/E]la [Cmaj7#11]la\n")
    given = page.shapes_of(sheet)
    for name in ("G", "C/E", "Cmaj7#11", "Am"):
        for shift in (0, 2):
            assert chord_shapes(GUITAR, parse_chord(name), shift, given) == _shapes(parse_chord(name), shift, given)
    assert chord_shapes(GUITAR, parse_chord("G"), 0, given)[0][0] == "320033"  # the sheet's own first


# --- the capo, folded in for an instrument that takes none ----------------------------------------------------

CAPO_2 = "{title: Capo}\n{artist: Synthetic}\n{key: Em}\n{capo: 2}\n[Em]la [C]la [G]la [D]la\n"


def test_an_instrument_with_no_capo_plays_the_version_as_it_sounds():
    key, capo_sheet = viewer_key(CAPO_2), 2
    guitar = played_key(for_instrument(Version(), GUITAR), key, capo_sheet)
    piano = played_key(for_instrument(Version(), PIANO), key, capo_sheet)
    assert guitar == (Key(4, "aeolian"), 2) and key_line_text(*guitar) == "Em shapes · capo 2 · sounds F#m"
    assert piano == (Key(6, "aeolian"), 0) and key_line_text(*piano) == "Key F#m"
    # Another capo and a move: the piano plays where they sound; the guitar's version keeps its capo.
    moved = Version(t=1, capo=4)
    assert played_key(for_instrument(moved, PIANO), key, capo_sheet) == (Key(7, "aeolian"), 0)  # Gm
    assert for_instrument(moved, GUITAR) is moved and for_instrument(moved, UKULELE) is moved
    assert for_instrument(moved, PIANO).capo == 0 and for_instrument(moved, PIANO).t == 1
