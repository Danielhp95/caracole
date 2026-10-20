"""caracole.viewer.voicings: the guitar fingerings the sheet viewer shows, from chords-db."""

from __future__ import annotations

import pytest

from caracole.viewer.theory import QUALITIES, Chord, parse_chord
from caracole.viewer.voicings import (
    LICENSE_FILE,
    chord_legend,
    load_voicings,
    notes_of,
    parse_define,
    parse_fingering,
    plays,
    subset_chords_db,
    voicing_keys,
)

# chords-db's lib/guitar.json, cut down: what subset_chords_db reads of it.
POSITION_C = {"frets": [-1, 3, 2, 0, 1, 0], "fingers": [0, 3, 2, 0, 1, 0], "baseFret": 1, "barres": []}
POSITION_C_BARRE = {"frets": [-1, 1, 3, 3, 3, 1], "fingers": [0, 1, 2, 3, 4, 1], "baseFret": 3,
                    "barres": [1], "capo": True}
WRONG = {"frets": [-1, 3, 3, 0, 1, 0], "fingers": [0, 3, 4, 0, 1, 0], "baseFret": 1, "barres": []}
DOC = {
    "main": {"strings": 6, "fretsOnChord": 4, "name": "guitar"},
    "tunings": {"standard": ["E2", "A2", "D3", "G3", "B3", "E4"]},
    "chords": {
        "C": [
            {"key": "C", "suffix": "major", "positions": [POSITION_C, WRONG, POSITION_C_BARRE]},
            {"key": "C", "suffix": "/E", "positions": [
                {"frets": [0, 3, 2, 0, 1, 0], "fingers": [0, 3, 2, 0, 1, 0], "baseFret": 1, "barres": []},
                POSITION_C,  # its lowest note is C, not E: not a C/E
            ]},
            {"key": "C", "suffix": "maj7b5", "positions": [POSITION_C]},  # a quality caracole hasn't
        ],
        "Csharp": [
            {"key": "C#", "suffix": "minor", "positions": [
                {"frets": [-1, 1, 3, 3, 2, 1], "fingers": [0, 1, 3, 4, 2, 1], "baseFret": 4,
                 "barres": [1], "capo": True},
            ]},
        ],
    },
}


def test_chords_db_positions_become_compact_and_filed_by_quality_and_root():
    data = subset_chords_db(DOC)
    assert data[""][0] == [["x32010", "032010", 1, []], ["x13331", "012341", 3, [1]]]
    assert data["m"][1] == [["x13321", "013421", 4, [1]]]
    assert data["/4"][0] == [["032010", "032010", 1, []]]
    assert "maj7b5" not in data
    assert all(len(roots) == 12 for roots in data.values())
    assert data[""][5] == []  # no F major in this little doc


def test_positions_are_read_as_the_notes_they_sound():
    assert notes_of(["x32010", "032010", 1, []]) == [48, 52, 55, 60, 64]
    assert notes_of(["x13331", "012341", 3, [1]]) == [48, 55, 60, 64, 67]


# --- the vendored data -------------------------------------------------------------------------

COMMON = ("", "m", "7", "maj7", "m7", "sus2", "sus4", "dim", "aug", "add9", "6", "m6", "9",
          "dim7", "m7b5", "7sus4", "5")


def test_every_vendored_position_plays_its_chord():
    for key, roots in load_voicings().items():
        quality, _, bass = key.partition("/")
        for root, positions in enumerate(roots):
            chord = Chord(root, quality, None if not bass else (root + int(bass)) % 12)
            for position in positions:
                notes = notes_of(position)
                assert {n % 12 for n in notes} <= chord.pitch_classes, (key, root, position)
                assert root in {n % 12 for n in notes}, (key, root, position)
                if bass:
                    assert min(notes) % 12 == chord.bass, (key, root, position)


def test_a_chord_never_shows_the_same_frets_twice():
    doc = {"chords": {"C": [{"key": "C", "suffix": "major", "positions": [POSITION_C, {
        **POSITION_C, "fingers": [0, 3, 2, 0, 1, 0]}, POSITION_C_BARRE]}]}}
    assert [p[0] for p in subset_chords_db(doc)[""][0]] == ["x32010", "x13331"]
    for roots in load_voicings().values():
        for positions in roots:
            assert len({p[0] for p in positions}) == len(positions)


@pytest.mark.parametrize("quality", COMMON)
def test_common_chords_have_fingerings_on_every_root(quality):
    roots = load_voicings()[quality]
    assert all(1 <= len(positions) <= 4 for positions in roots), quality


def test_the_open_shapes_come_first():
    data = load_voicings()
    assert data[""][0][0][0] == "x32010"  # C
    assert data[""][7][0][0] == "320003"  # G
    assert data["m"][9][0][0] == "x02210"  # Am


def test_the_licence_of_the_data_ships_with_it():
    text = LICENSE_FILE.read_text(encoding="utf-8")
    assert "MIT License" in text and "David Rubert" in text and "chords-db" in text


# --- which fingerings a chord shows -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "keys"),
    [
        ("Am7", ("m7", False)),
        ("CM7", ("maj7", False)),
        ("Cmaj7#11", ("maj7", True)),  # the nearest chord there are fingerings for
        ("Cm9b5", ("m7b5", True)),
        ("C7sus2", ("sus2", True)),
        ("C(b5)", ("", True)),
        ("Cfoo", ("", True)),
    ],
)
def test_a_chord_without_fingerings_shows_the_nearest_one_it_has(name, keys):
    chord = parse_chord(name, strict=False)
    assert voicing_keys(chord)[:2] == keys


def test_a_slash_chord_looks_for_its_own_fingerings_first():
    assert voicing_keys(parse_chord("C/E")) == ("", False, "/4")
    assert voicing_keys(parse_chord("Am/G")) == ("m", False, "m/10")
    assert voicing_keys(parse_chord("C")) == ("", False, None)


def test_every_quality_has_some_fingering_to_show():
    data = load_voicings()
    for quality in QUALITIES:
        assert voicing_keys(Chord(0, quality))[0] in data


# --- the fingerings a tab writes ----------------------------------------------------------------

NO_FINGERS = "000000"  # a tab says nothing of the fingers


@pytest.mark.parametrize(
    ("written", "position"),
    [
        ("x32033", ["x32033", NO_FINGERS, 1, []]),  # Cadd9, low E first
        ("(x32033)", ["x32033", NO_FINGERS, 1, []]),  # as a chord legend has it
        ("X32033", ["x32033", NO_FINGERS, 1, []]),
        ("x-3-2-0-3-3", ["x32033", NO_FINGERS, 1, []]),
        ("x 3 2 0 3 3", ["x32033", NO_FINGERS, 1, []]),
        ("( 022033 )", ["022033", NO_FINGERS, 1, []]),
        ("8 10 10 9 8 8", ["133211", NO_FINGERS, 8, []]),  # up the neck: counted from the lowest fret held
        ("(0-7-9-9-8-0)", ["013320", NO_FINGERS, 7, []]),
        ("x24442", ["x24442", NO_FINGERS, 1, []]),  # up to the 4th fret, from the nut
    ],
)
def test_a_fingering_as_a_tab_writes_it_becomes_a_position(written, position):
    assert parse_fingering(written) == position


@pytest.mark.parametrize("written", ["x2", "(x4)", "x3203", "1234567", "x-3-2-0-3", "xxxxxx", "", "Cadd9",
                                     "12 1 1 1 1 1", "(x32033", "x32033)", "0 2 2 0 3 30"])
def test_anything_else_is_no_fingering(written):
    assert parse_fingering(written) is None


def given(line: str) -> list[tuple]:
    return [(chord.root, chord.suffix, chord.bass, position[0]) for chord, position in chord_legend(line)]


@pytest.mark.parametrize(
    ("line", "entries"),
    [
        ("Dsus4   (xx0233)", [(2, "sus4", None, "xx0233")]),
        ("Dsus4/F#(2x0233)", [(2, "sus4", 6, "2x0233")]),
        ("Cadd9 x32033", [(0, "add9", None, "x32033")]),
        ("Cadd9: x32033", [(0, "add9", None, "x32033")]),
        ("Cadd9 = x32033", [(0, "add9", None, "x32033")]),
        ("Cadd9 - x32033", [(0, "add9", None, "x32033")]),
        ("  Em7 (022033)   G (320033)  ", [(4, "m7", None, "022033"), (7, "", None, "320033")]),
        ("Em7 022033 | G 320033", [(4, "m7", None, "022033"), (7, "", None, "320033")]),
        ("E5 0 2 2 x x x", [(4, "5", None, "022xxx")]),  # not an E with a 5th fret
        ("C x 3 2 0 1 0", [(0, "", None, "x32010")]),
        ("Bb 6 8 8 7 6 6", [(10, "", None, "133211")]),
    ],
)
def test_a_chord_legends_line_gives_each_chord_its_fingering(line, entries):
    assert given(line) == entries


@pytest.mark.parametrize("line", [
    "Capo 2. fret", "EADGBe", "This is the version that the band played that night",
    "Cadd9 (x32033) in the chorus",  # more than a legend: a note
    "G (x2)", "Em7", "x32033", "Hx32033", "Cadd9 x3203", "Em7 (022033) foo", "Cfoo x32033",  # no chord
    "", "   ",
])
def test_any_other_line_is_no_legend(line):
    assert chord_legend(line) == []


@pytest.mark.parametrize(
    ("value", "chord", "position"),
    [
        ("Cadd9 base-fret 1 frets x 3 2 0 3 3 fingers 0 2 1 0 3 4", "Cadd9", ["x32033", "021034", 1, []]),
        ("Ab base-fret 4 frets 1 3 3 2 1 1", "Ab", ["133211", NO_FINGERS, 4, []]),  # counted from the base fret
        ("Am7 frets x 0 2 0 1 0", "Am7", ["x02010", NO_FINGERS, 1, []]),
        ("D/F# frets 2 N 0 2 3 2 base-fret 1", "D/F#", ["2x0232", NO_FINGERS, 1, []]),
        ("G frets 3 2 0 0 3 3 fingers 2 1 - - 3 4", "G", ["320033", "210034", 1, []]),
        ("Em frets -1 2 2 0 0 0", "Em", ["x22000", NO_FINGERS, 1, []]),
    ],
)
def test_a_define_directive_gives_its_chord_a_position(value, chord, position):
    assert parse_define(value) == (parse_chord(chord), position)


@pytest.mark.parametrize("value", [
    "Cadd9", "Cadd9 base-fret 1", "Cadd9 frets x 3 2", "Hm frets x 0 2 2 1 0", "Cfoo frets x 3 2 0 3 3",
    "C frets x 3 2 0 1 12",  # a fret beyond the diagram's
    "C frets x x x x x x", "C keys 0 4 7", "C copy D", "",
])
def test_any_other_define_gives_none(value):
    assert parse_define(value) is None


def test_a_fingering_plays_a_chord_when_it_sounds_its_notes_alone():
    assert plays(parse_fingering("x32033"), parse_chord("Cadd9"))
    assert plays(parse_fingering("2x0233"), parse_chord("Dsus4/F#"))  # the bass lowest
    assert not plays(parse_fingering("x32033"), parse_chord("G"))  # a C in a G chord
    assert not plays(parse_fingering("xx0233"), parse_chord("Dsus4/F#"))  # no F# in the bass
