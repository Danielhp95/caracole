"""caracole.viewer.voicings: the guitar fingerings the sheet viewer shows, from chords-db."""

from __future__ import annotations

import pytest

from caracole.viewer.theory import QUALITIES, Chord, parse_chord
from caracole.viewer.voicings import (
    LICENSE_FILE,
    load_voicings,
    notes_of,
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
