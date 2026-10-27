"""caracole.viewer.winds: the concert flute's and the soprano recorder's fingerings, the octave a melody is played
in, the notes of a key's scale and of a chord as a wind player reads them, with the tables a viewer's data carries."""

from __future__ import annotations

import dataclasses

import pytest

from caracole.viewer import harmony, harmony_tables, winds
from caracole.viewer.harmony_tables import SHIFTS, shifted
from caracole.viewer.theory import MODES, QUALITIES, Chord, Key, alternatives, map_chord, parse_chord, spelling
from caracole.viewer.winds import FLUTE, RECORDER, chord_notes, chord_steps, fingerings, fit, scale_notes, solfege

NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi(name: str) -> int:
    letter, octave = name[:-1], int(name[-1])
    return NAMES.index(letter) + 12 * (octave + 1)


def pressed(wind, name: str, system: str | None = None) -> set[str]:
    found = fingerings(wind, midi(name), system=system)[0]
    return {k for k, state in zip(wind.keys, found.states, strict=True) if state == "x"}


def pc_of(name: str) -> int:
    return (NAMES.index(name[0]) + name.count("#") - name.count("b")) % 12


# --- the flute ------------------------------------------------------------------------------------

HANDS = {"L1", "L2", "L3", "R1", "R2", "R3"}


def test_the_flute_reads_c4_to_c7_at_concert_pitch():
    assert (FLUTE.low, FLUTE.high, FLUTE.sounds) == (midi("C4"), midi("C7"), 0)
    assert all(fingerings(FLUTE, n) for n in range(FLUTE.low, FLUTE.high + 1))
    assert fingerings(FLUTE, FLUTE.low - 1) == [] and fingerings(FLUTE, FLUTE.high + 1) == []


@pytest.mark.parametrize(("note", "keys"), [
    ("C4", {"thumb", *HANDS, "C"}),  # every finger down, the little finger on the low C roller
    ("C#4", {"thumb", *HANDS, "C#"}),
    ("D4", {"thumb", *HANDS}),  # the one low note with no little finger
    ("D#4", {"thumb", *HANDS, "Eb"}),
    ("E4", {"thumb", "L1", "L2", "L3", "R1", "R2", "Eb"}),
    ("F4", {"thumb", "L1", "L2", "L3", "R1", "Eb"}),
    ("F#4", {"thumb", "L1", "L2", "L3", "R3", "Eb"}),  # the third finger, not the first two
    ("G4", {"thumb", "L1", "L2", "L3", "Eb"}),
    ("G#4", {"thumb", "L1", "L2", "L3", "G#", "Eb"}),
    ("A4", {"thumb", "L1", "L2", "Eb"}),
    ("A#4", {"thumb", "L1", "R1", "Eb"}),  # "one and one"
    ("B4", {"thumb", "L1", "Eb"}),
    ("C5", {"L1", "Eb"}),
    ("C#5", {"Eb"}),  # the open note
    ("D5", {"thumb", "L2", "L3", "R1", "R2", "R3"}),  # the first finger lifted to vent
    ("D#5", {"thumb", "L2", "L3", "R1", "R2", "R3", "Eb"}),
    ("D6", {"thumb", "L2", "L3", "Eb"}),
    ("D#6", {"thumb", "L1", "L2", "L3", "G#", "R1", "R2", "R3", "Eb"}),
    ("E6", {"thumb", "L1", "L2", "R1", "R2", "Eb"}),
    ("F6", {"thumb", "L1", "L3", "R1", "Eb"}),
    ("F#6", {"thumb", "L1", "L3", "R3", "Eb"}),
    ("G6", {"L1", "L2", "L3", "Eb"}),
    ("G#6", {"L2", "L3", "G#", "Eb"}),
    ("A6", {"thumb", "L2", "R1", "Eb"}),
    ("A#6", {"thumb", "R1", "trill-D"}),
    ("B6", {"thumb", "L1", "L3", "trill-D#"}),
    ("C7", {"L1", "L2", "L3", "G#", "R1"}),
])
def test_the_flutes_standard_fingerings(note, keys):
    assert pressed(FLUTE, note) == keys


def test_the_second_octave_is_the_first_overblown_but_d_and_e_flat_vent_the_first_finger():
    for low in ("E4", "F4", "F#4", "G4", "G#4", "A4", "A#4", "B4", "C5", "C#5"):
        assert fingerings(FLUTE, midi(low) + 12) == fingerings(FLUTE, midi(low)), low
    for low in ("D4", "D#4"):
        assert pressed(FLUTE, low) - pressed(FLUTE, low.replace("4", "5")) == {"L1"}


def test_the_little_finger_holds_the_e_flat_key_down_but_on_a_few_notes():
    without = [n for n in range(FLUTE.low, FLUTE.high + 1) if "Eb" not in pressed(FLUTE, NAMES[n % 12] + str(n // 12 - 1))]
    assert [NAMES[n % 12] + str(n // 12 - 1) for n in without] == ["C4", "C#4", "D4", "D5", "A#6", "B6", "C7"]


def test_b_flat_may_take_the_thumb_lever():
    for octave in ("4", "5"):
        standard, thumb = fingerings(FLUTE, midi("A#" + octave))
        assert {k for k, s in zip(FLUTE.keys, thumb.states, strict=True) if s == "x"} == {"thumb-Bb", "L1", "Eb"}
        assert standard.chart == "T 1--|1-- Eb" and thumb.chart == "Bb 1--|--- Eb"


# --- the soprano recorder -------------------------------------------------------------------------


def test_the_soprano_recorder_reads_c4_to_d6_and_sounds_an_octave_higher():
    assert (RECORDER.low, RECORDER.high, RECORDER.sounds) == (midi("C4"), midi("D6"), 12)
    for system in ("baroque", "german"):
        assert all(fingerings(RECORDER, n, system=system) for n in range(RECORDER.low, RECORDER.high + 1))
    assert fingerings(RECORDER, midi("D#6")) == []


@pytest.mark.parametrize(("note", "holes"), [
    ("C4", "xxxxxxxxo"),
    ("C#4", "xxxxxxxho"),  # one of the little finger's double holes
    ("D4", "xxxxxxxoo"),
    ("D#4", "xxxxxxhoo"),
    ("E4", "xxxxxxooo"),
    ("F4", "xxxxxoxxo"),  # forked: the baroque F
    ("F#4", "xxxxoxxoo"),
    ("G4", "xxxxooooo"),
    ("G#4", "xxxoxxhoo"),
    ("A4", "xxxoooooo"),
    ("A#4", "xxoxxoooo"),
    ("B4", "xxooooooo"),
    ("C5", "xoxoooooo"),
    ("C#5", "oxxoooooo"),
    ("D5", "ooxoooooo"),
    ("D#5", "ooxxxxxoo"),
    ("E5", "hxxxxxooo"),  # the thumb pinched from here up
    ("F5", "hxxxxoxoo"),
    ("F#5", "hxxxoxooo"),
    ("G5", "hxxxooooo"),
    ("G#5", "hxxoxoooo"),
    ("A5", "hxxoooooo"),
    ("A#5", "hxxoxxxoo"),
    ("B5", "hxxoxxooo"),
    ("C6", "hxooxxooo"),
    ("C#6", "hxoxxoxox"),  # the bell closed, on the knee
    ("D6", "hxoxxoxoo"),
])
def test_the_recorders_baroque_fingerings(note, holes):
    assert RECORDER.keys == ("thumb", "L1", "L2", "L3", "R1", "R2", "R3", "R4", "bell")
    assert fingerings(RECORDER, midi(note))[0].text == holes


def test_german_fingering_differs_only_on_f_f_sharp_and_g_sharp():
    differ = [NAMES[n % 12] + str(n // 12 - 1) for n in range(RECORDER.low, RECORDER.high + 1)
              if fingerings(RECORDER, n, system="german") != fingerings(RECORDER, n)]
    assert differ == ["F4", "F#4", "G#4", "F5", "F#5"]
    assert pressed(RECORDER, "F4", "german") == {"thumb", "L1", "L2", "L3", "R1"}  # no fork
    assert pressed(RECORDER, "F#4", "german") == {"thumb", "L1", "L2", "L3", "R2", "R3", "R4"}


def test_an_unknown_system_is_an_error():
    assert (FLUTE.systems, RECORDER.systems) == (("boehm",), ("baroque", "german"))
    for wind, system in ((RECORDER, "english"), (FLUTE, "baroque")):
        with pytest.raises(ValueError):
            fingerings(wind, midi("C5"), system=system)


# --- the octave a melody is played in -------------------------------------------------------------


def test_a_melody_a_flute_reads_is_played_where_it_is():
    found = fit([midi("G4"), midi("E5"), midi("C5")], FLUTE)
    assert (found.shift, found.written, found.outside) == (0, (midi("G4"), midi("E5"), midi("C5")), ())


def test_a_recorder_plays_a_sung_melody_an_octave_up_as_written():
    found = fit([midi("G4"), midi("E5")], RECORDER)
    assert (found.shift, found.written) == (12, (midi("G4"), midi("E5")))  # it sounds G5 to E6


def test_a_low_voices_melody_comes_up_into_the_instruments_range():
    low_voice = [midi("C3"), midi("E4")]
    assert (fit(low_voice, FLUTE).shift, fit(low_voice, FLUTE).written) == (12, (midi("C4"), midi("E5")))
    assert (fit(low_voice, RECORDER).shift, fit(low_voice, RECORDER).written) == (24, (midi("C4"), midi("E5")))


def test_a_melody_high_in_the_flutes_third_octave_comes_down_where_it_is_easy():
    assert fit([midi("E6"), midi("A6")], FLUTE).shift == -12
    assert fit([midi("D6")], FLUTE).shift == 0  # D6 is still easy


def test_a_melody_wider_than_the_range_leaves_the_fewest_notes_out():
    found = fit([midi("C3"), midi("G4"), midi("C5"), midi("G6"), midi("E7")], RECORDER)
    assert len(found.outside) == 2 and all(n < RECORDER.low or n > RECORDER.high for n in found.outside)


# --- what a wind player reads off a chord sheet ---------------------------------------------------


def test_a_keys_scale_starts_on_its_tonic_in_the_lowest_octave_both_instruments_read():
    assert scale_notes(Key(0, "ionian")) == [midi(n) for n in "C4 D4 E4 F4 G4 A4 B4 C5".split()]
    assert scale_notes(Key(9, "aeolian")) == [midi(n) for n in "A4 B4 C5 D5 E5 F5 G5 A5".split()]
    assert scale_notes(Key(11, "ionian"))[-1] == midi("B5")
    for mode in MODES:
        for tonic in range(12):
            found = scale_notes(Key(tonic, mode))
            assert found[0] == 60 + tonic and found[-1] == found[0] + 12 and found == sorted(found)
            for n in found:
                assert fingerings(FLUTE, n) and fingerings(RECORDER, n) and fingerings(RECORDER, n, system="german")


@pytest.mark.parametrize(("chord", "notes"), [
    ("C", "C4 E4 G4"),
    ("C7", "C4 E4 G4 A#4"),
    ("C9", "C4 E4 G4 A#4 D5"),  # each tone above the one before, in the order of its degrees
    ("Am", "A4 C5 E5"),
    ("G/B", "G4 B4 D5"),
    ("C/D", "C4 D4 E4 G4"),  # a bass that is no note of the chord in its place by degree
    ("C11", "C4 E4 G4 A#4 D5 F4"),  # an 11th or a 13th an octave lower, as a 4th or a 6th, in every key
    ("B11", "B4 D#5 F#5 A5 C#6 E5"),
    ("C13", "C4 E4 G4 A#4 D5 A4"),
    ("B13", "B4 D#5 F#5 A5 C#6 G#5"),
])
def test_a_chords_notes_go_up_from_its_root_in_the_lowest_octave(chord, notes):
    found = chord_notes(parse_chord(chord))
    assert found == [midi(n) for n in notes.split()]
    assert chord_steps(parse_chord(chord)) == [n - found[0] for n in found]


def test_every_chord_on_every_root_is_read_by_both_instruments_in_the_order_of_its_tones():
    for quality in QUALITIES:
        steps = chord_steps(Chord(0, quality))
        assert steps[0] == 0 and max(steps) <= 15, quality  # so the highest, on B4, is D6
        for root in range(12):
            chord = Chord(root, quality)
            found = chord_notes(chord)
            tones = harmony.chord_tones(chord, None)
            assert found == [60 + root + step for step in steps] and len(found) == len(tones), (root, quality)
            assert [n % 12 for n in found] == [pc_of(name) for name, _ in tones], (root, quality)
            assert all(fingerings(FLUTE, n) and fingerings(RECORDER, n) for n in found), (root, quality)


@pytest.mark.parametrize(("name", "said"), [
    ("C", "Do"), ("D", "Re"), ("E", "Mi"), ("F", "Fa"), ("G", "Sol"), ("A", "La"), ("B", "Si"),
    ("Bb", "Sib"), ("F#", "Fa#"), ("C##", "Do##"), ("Ebb", "Mibb"),
])
def test_solfege_names_a_note_as_spanish_speaking_players_read_it(name, said):
    assert solfege(name) == said


# --- the tables a viewer's data carries -----------------------------------------------------------


def test_the_fingering_data_is_each_note_from_c4_up():
    data = winds.fingering_data()
    assert data["low"] == 60
    assert data["flute"]["keys"] == list(FLUTE.keys) and len(data["flute"]["notes"]) == FLUTE.high - 59
    assert data["recorder"]["holes"] == list(RECORDER.keys)
    for system in ("baroque", "german"):
        assert len(data["recorder"][system]) == RECORDER.high - 59
        assert data["recorder"][system][midi("F4") - 60] == fingerings(RECORDER, midi("F4"), system=system)[0].text
    for n in range(FLUTE.low, FLUTE.high + 1):
        assert data["flute"]["notes"][n - 60] == [f.text for f in fingerings(FLUTE, n)]
    assert data["solfege"] == {"C": "Do", "D": "Re", "E": "Mi", "F": "Fa", "G": "Sol", "A": "La", "B": "Si"}
    assert all(set(t) <= {"x", "o", "h"} for t in data["recorder"]["baroque"])


IN_A_MINOR = [parse_chord(n) for n in "Am G F E7 Dm/F C9 Bb11".split()]


def sheet_tables(chords, key):
    mapped = {mode: [map_chord(c, key, mode) for c in chords] for mode in MODES} if key else {}
    alts = {mode: [alternatives(c, Key(key.tonic, mode)) for c in mapped[mode]] for mode in MODES} if key else {}
    places = [(i, 0) for i in range(len(chords))]
    return mapped, alts, harmony_tables.tables(chords, key, places, mapped, alts)


def test_the_tables_give_each_chords_steps_by_its_index_and_each_form_once():
    key = Key(9, "aeolian")
    mapped, alts, _ = sheet_tables(IN_A_MINOR, key)
    data = winds.tables(IN_A_MINOR, key, mapped, alts)
    forms = data["windForms"]
    assert len(forms) == len({tuple(f) for f in forms})
    for mode in MODES:
        assert [forms[i] for i in data["windChords"][mode]] == [chord_steps(c) for c in mapped[mode]]
        assert [[forms[i] for i in row] for row in data["windAlts"][mode]] == [
            [chord_steps(a) for a in options] for options in alts[mode]]
    bare = winds.tables(IN_A_MINOR + [None], None, {}, {})
    assert [None if i is None else bare["windForms"][i] for i in bare["windChords"][""]] == [
        chord_steps(c) for c in IN_A_MINOR] + [None]
    assert bare["windAlts"] == {}


@pytest.mark.parametrize("key", [Key(9, "aeolian"), None])
def test_the_page_finds_each_chords_notes_and_scale_on_every_transposition(key):
    """What the page does with the tables (a note is ``low`` + the root's pitch class as shown + a step, and a scale
    harmony_tables.py's ``keyScale`` from the tonic, then its octave) gives winds.py's answers in every key, one note
    for each name of harmony_tables.py's ``tones``."""
    mapped, alts, harmonies = sheet_tables(IN_A_MINOR, key)
    data = winds.tables(IN_A_MINOR, key, mapped, alts)
    low = winds.fingering_data()["low"]
    for mode in MODES if key else [""]:
        shown_chords = mapped[mode] if key else IN_A_MINOR
        for i, chord in enumerate(shown_chords):
            steps = data["windForms"][data["windChords"][mode][i]]
            for s in SHIFTS:
                shown = None if key is None else Key((key.tonic + s) % 12, mode)
                notes = [low + (chord.root + s) % 12 + step for step in steps]
                assert notes == chord_notes(shifted(chord, s))
                named = harmonies["tones"][harmony_tables.page_name(chord, spelling(shown), s)].split("|")[0]
                assert [n % 12 for n in notes] == [pc_of(t) for t in named.split()]
        if key:
            for s in SHIFTS:
                tonic = (key.tonic + s) % 12
                assert [low + tonic + step for step in harmonies["keyScale"][mode] + [12]] == scale_notes(
                    Key(tonic, mode))


def test_answers_are_frozen_and_a_list_handed_out_is_a_copy():
    with pytest.raises(dataclasses.FrozenInstanceError):
        FLUTE.low = 59
    with pytest.raises(dataclasses.FrozenInstanceError):
        fingerings(FLUTE, 60)[0].chart = ""
    for got in (fingerings(FLUTE, 70), scale_notes(Key(0, "ionian")), chord_notes(parse_chord("C")),
                chord_steps(parse_chord("C")), winds.fingering_data()["flute"]["notes"]):
        got.clear()
    assert len(fingerings(FLUTE, 70)) == 2
    assert scale_notes(Key(0, "ionian"))[0] == 60 and chord_notes(parse_chord("C")) == [60, 64, 67]
    assert chord_steps(parse_chord("C")) == [0, 4, 7] and winds.fingering_data()["flute"]["notes"]
