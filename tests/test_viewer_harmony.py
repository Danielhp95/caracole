"""caracole.viewer.harmony: numerals, relations, families, glossary lines, chord tones, scales and
progressions, on top of viewer/theory.py."""

from __future__ import annotations

import dataclasses
import re

import pytest

from caracole.viewer import harmony, page
from caracole.viewer.harmony import (
    CATALOGUE,
    Contained,
    Numeral,
    Progression,
    Relation,
    chord_tones,
    explain,
    family,
    glossary,
    key_scale,
    numeral,
    pentatonic,
    name_of,
    progression_key,
    progressions,
    read_typed,
    relation,
    solo_scale,
)
from caracole.viewer.theory import _NATURAL, QUALITIES, SCALES, Chord, Key, parse_chord, scale

C = Key(0, "ionian")
A_MINOR = Key(9, "aeolian")


def ch(name: str) -> Chord:
    chord = parse_chord(name)
    assert chord is not None, name
    return chord


def texts(names: str, key: Key) -> list[str]:
    """Each chord's numeral, each read with the next one as the chord it goes to."""
    chords = [ch(n) for n in names.split()]
    return [numeral(c, key, chords[i + 1] if i + 1 < len(chords) else None).text
            for i, c in enumerate(chords)]


def section(names: str) -> list[Chord | None]:
    return [None if n == "N.C." else ch(n) for n in names.split()]


def pc(name: str) -> int:
    """The pitch class of a note's name, double sharps and flats too: "B#" is 0, "Ebb" is 2."""
    return (_NATURAL[name[0]] + name.count("#") - name.count("b")) % 12


# --- numerals -----------------------------------------------------------------------------------


def test_c_majors_triads_and_sevenths():
    assert texts("C Dm Em F G Am Bdim", C) == ["I", "ii", "iii", "IV", "V", "vi", "vii°"]
    assert texts("Cmaj7 Dm7 Em7 Fmaj7 G7 Am7 Bm7b5", C) == [
        "Imaj7", "ii7", "iii7", "IVmaj7", "V7", "vi7", "viiø7"]


def test_a_minors_triads_are_written_against_the_major_scale_and_its_dominant_is_major():
    assert texts("Am Bdim C Dm Em F G", A_MINOR) == ["i", "ii°", "♭III", "iv", "v", "♭VI", "♭VII"]
    assert numeral(ch("E7"), A_MINOR).text == "V7"
    assert relation(ch("E7"), A_MINOR) == Relation("in", None, None)
    assert numeral(ch("G#dim7"), A_MINOR).text == "vii°7"
    assert relation(ch("G#dim7"), A_MINOR).kind == "in"


def test_the_numerals_fields():
    assert numeral(ch("Bb"), C) == Numeral("♭", "VII", "", "", None, None)
    assert numeral(ch("Bm7b5"), C) == Numeral("", "vii", "ø", "7", None, None)
    assert numeral(ch("Bdim7"), C).text == "vii°7"
    assert numeral(ch("Caug"), C) == Numeral("", "I", "+", "", None, None)
    assert numeral(ch("G7"), C).text == "V7"


def test_c_mixolydians_b_flat_is_its_own_flat_seven():
    mixolydian = Key(0, "mixolydian")
    assert numeral(ch("Bb"), mixolydian).text == "♭VII"
    assert relation(ch("Bb"), mixolydian).kind == "in"


@pytest.mark.parametrize(("name", "text"), [
    ("C5", "I5"), ("Csus4", "Isus4"), ("Csus2", "Isus2"), ("C6", "I6"), ("Cadd9", "Iadd9"),
    ("Am6", "vi6"), ("G9", "V9"), ("G7sus4", "V7sus4"), ("Dm9", "ii9"), ("C6/9", "I69"),
    ("Cmaj9", "Imaj9"), ("Am(maj7)", "vimaj7"), ("G13", "V13"), ("G7b9", "V7♭9"),
    ("Cmaj7#11", "Imaj7♯11"),
])
def test_extensions_are_written_as_the_chord_name_has_them(name, text):
    assert numeral(ch(name), C).text == text


def test_every_quality_has_its_shape():
    assert set(harmony._SHAPES) == set(QUALITIES)


def test_a_suffix_caracole_cant_read_gives_the_triads_numeral():
    assert numeral(parse_chord("Cfoo", strict=False), C).text == "I"
    assert numeral(parse_chord("Amfoo", strict=False), C).text == "vi"


@pytest.mark.parametrize(("name", "text", "bass"), [
    ("C/E", "I/3", "3"), ("C/G", "I/5", "5"), ("C/D", "I/2", "2"), ("G/F", "V/♭7", "♭7"),
    ("G7/F", "V7/♭7", "♭7"), ("Am/G", "vi/♭7", "♭7"), ("G/B", "V/3", "3"), ("C/B", "I/7", "7"),
    ("F/G", "IV/2", "2"), ("C/C", "I", None), ("Am/C", "vi/♭3", "♭3"), ("Cadd9/D", "Iadd9/2", "2"),
])
def test_a_slash_chords_bass_is_its_degree_above_the_chords_root_chord_tone_or_not(name, text, bass):
    found = numeral(ch(name), C)
    assert (found.text, found.bass) == (text, bass)


def test_a_secondary_dominant_is_the_v_of_the_chord_it_leads_to():
    d7 = numeral(ch("D7"), C, ch("G"))
    assert (d7.roman, d7.extension, d7.of, d7.text) == ("V", "7", "V", "V7/V")
    assert relation(ch("D7"), C, ch("G")) == Relation("secondary", None, "G")
    assert texts("E7 Am", C)[0] == "V7/vi"
    assert relation(ch("E7"), C, ch("Am")) == Relation("secondary", None, "Am")
    assert texts("A7 Dm", C)[0] == "V7/ii"
    assert texts("D/F# G", C)[0] == "V/V/3"


def test_a_dominant_no_mode_on_the_tonic_holds_is_secondary_even_when_it_goes_elsewhere():
    # E major is in no mode on C: it is the V of vi wherever it goes, and leads to Am only there.
    assert numeral(ch("E"), C, ch("F")).text == "V/vi"
    assert relation(ch("E"), C, ch("F")) == Relation("secondary", None, "Am")
    assert numeral(ch("E"), C).text == "V/vi"


def test_a_dominant_a_mode_on_the_tonic_holds_is_secondary_only_when_it_resolves():
    # D in C goes to G: V/V. Going elsewhere it is C Lydian's II (the "Lydian II" of rock).
    assert numeral(ch("D"), C, ch("C")).text == "II"
    assert relation(ch("D"), C, ch("C")) == Relation("borrowed", "C Lydian", None)
    assert numeral(ch("D"), C).text == "II"


def test_a_tonic_dominant_seventh_going_to_iv_is_its_v7_but_a_blues_i7_iv7_stays():
    # C7 F7 in a blues is I7 IV7: both dominant sevenths, neither resolves.
    assert numeral(ch("C7"), C, ch("F7")).text == "I7"
    assert relation(ch("C7"), C, ch("F7")) == Relation("borrowed", "C Mixolydian", None)
    # "Something": C Cmaj7 C7 F, the textbook V7/IV; the same in a minor key, V7/iv.
    assert texts("C Cmaj7 C7 F", C) == ["I", "Imaj7", "V7/IV", "IV"]
    assert relation(ch("C7"), C, ch("F")) == Relation("secondary", None, "F")
    assert texts("Am A7 Dm", A_MINOR) == ["i", "V7/iv", "iv"]
    # A tonic triad, or a seventh going elsewhere, stays on the tonic.
    assert numeral(ch("C7"), C, ch("G")).text == "I7"
    assert numeral(ch("C7"), C).text == "I7"


def test_a_dominant_seventh_of_the_key_that_resolves_a_fifth_down_is_secondary():
    # G7 to C in A minor is V7/♭III, as D to G there is V/♭VII; G7 going elsewhere is ♭VII7.
    assert texts("G7 C", A_MINOR)[0] == "V7/♭III"
    assert relation(ch("G7"), A_MINOR, ch("C")) == Relation("secondary", None, "C")
    assert texts("D G", A_MINOR)[0] == "V/♭VII"
    assert texts("G7 Am", A_MINOR)[0] == "♭VII7"
    assert numeral(ch("G7"), A_MINOR).text == "♭VII7"
    assert texts("E7 Am", A_MINOR)[0] == "V7"
    # The triad stays a chord of the key.
    assert texts("G C", A_MINOR)[0] == "♭VII"


def test_a_secondary_leading_tone_chord():
    assert texts("C#dim7 Dm", C)[0] == "vii°7/ii"
    assert relation(ch("C#dim7"), C, ch("Dm")) == Relation("leading", None, "Dm")
    assert texts("F#m7b5 G", C)[0] == "viiø7/V"
    assert texts("G#dim7 Am", C)[0] == "vii°7/vi"
    assert relation(ch("G#dim7"), C, ch("Am")).kind == "leading"


def test_borrowed_chords_come_from_the_parallel_key_first():
    # A major key borrows from its parallel minor first (modal mixture: bIII, iv, bVI, bVII),
    # then from the modes nearest it.
    for name, text in [("Bb", "♭VII"), ("Eb", "♭III"), ("Ab", "♭VI"), ("Fm", "iv"),
                       ("Ddim", "ii°"), ("Bdim7", "vii°7"), ("G7b9", "V7♭9")]:
        assert numeral(ch(name), C).text == text, name
        assert relation(ch(name), C) == Relation("borrowed", "C minor", None), name
    assert relation(ch("Bb"), C, ch("C")) == Relation("borrowed", "C minor", None)
    assert (numeral(ch("Db"), C).text, relation(ch("Db"), C).source) == ("♭II", "C Phrygian")
    assert (numeral(ch("F7"), C).text, relation(ch("F7"), C).source) == ("IV7", "C Dorian")


def test_a_minor_key_borrows_from_the_modes_nearest_it_first_then_the_parallel_major():
    # The "Dorian IV" of rock, the Phrygian bII, then the Picardy third.
    assert (numeral(ch("D"), A_MINOR).text, relation(ch("D"), A_MINOR).source) == ("IV", "A Dorian")
    assert (numeral(ch("Bb"), A_MINOR).text, relation(ch("Bb"), A_MINOR).source) == ("♭II", "A Phrygian")
    assert (numeral(ch("A"), A_MINOR).text, relation(ch("A"), A_MINOR).source) == ("I", "A major")


def test_a_borrowed_chord_names_its_key_as_the_home_key_spells_its_tonic():
    e_flat, a_flat, d_flat = Key(3, "ionian"), Key(8, "ionian"), Key(1, "ionian")
    assert relation(ch("Db"), e_flat).source == "Eb minor"
    assert explain(ch("Db"), e_flat).endswith("; borrowed from Eb minor")
    assert relation(ch("Fm"), a_flat).kind == "in"
    assert relation(ch("Dbm"), a_flat).source == "Ab minor"
    assert relation(ch("Gbm"), d_flat).source == "Db minor"
    assert relation(ch("Ab"), e_flat).kind == "in"


def test_the_minor_keys_tonic_with_a_major_seventh_is_its_own():
    # i(maj7), of harmonic and melodic minor: in A minor, and borrowed from C minor in C.
    assert relation(ch("Am(maj7)"), A_MINOR) == Relation("in", None, None)
    assert family(ch("Am(maj7)"), A_MINOR) == "home"
    assert numeral(ch("Cm(maj7)"), C).text == "imaj7"
    assert relation(ch("Cm(maj7)"), C) == Relation("borrowed", "C minor", None)
    assert solo_scale(ch("Cm(maj7)"), C) == ("C melodic minor", ("C", "D", "Eb", "F", "G", "A", "B"))
    assert [s for s, _, _ in glossary([ch("Cm(maj7)")], C)] == ["I–VII", "i", "maj7"]


def test_a_chord_in_no_mode_and_no_secondary_is_outside_the_key():
    assert relation(ch("F#"), C) == Relation("outside", None, None)
    assert numeral(ch("F#"), C).text == "♯IV"
    assert numeral(ch("Eb"), A_MINOR).text == "♭V"


def test_no_chord_no_numeral():
    assert parse_chord("N.C.") is None
    found = progressions([("Verse", section("C N.C. G"))], C)
    assert found[0][1].numerals == ("I", "V")


def test_every_quality_gets_a_numeral_an_explanation_and_a_scale_that_holds_it():
    for root in (0, 2, 6):
        for quality in sorted(QUALITIES):
            chord = Chord(root, quality)
            assert numeral(chord, C).text
            assert explain(chord, C).startswith(numeral(chord, C).text + ": ")
            name, notes = solo_scale(chord, C)
            assert chord.pitch_classes <= {pc(n) for n in notes}, (root, quality, name)
            assert {pc(n) for n, _ in chord_tones(chord, C)} == chord.pitch_classes


# --- relations and families ---------------------------------------------------------------------


def test_families_of_the_chords_in_the_key():
    assert [family(ch(n), C) for n in "C Em Am F Dm G Bdim".split()] == [
        "home", "home", "home", "away", "away", "pull", "pull"]
    assert [family(ch(n), A_MINOR) for n in "Am C F Dm Bdim E7 G".split()] == [
        "home", "home", "home", "away", "away", "pull", "pull"]
    assert family(ch("Bb"), C) is None
    assert family(ch("E7"), C) is None


# --- the glossary's lines -----------------------------------------------------------------------


def test_explain_says_the_degree_the_quality_and_the_key_it_is_read_in():
    assert explain(ch("Am"), C) == "vi: the 6th chord of C major, minor (lower case)"
    assert explain(ch("Am"), A_MINOR) == "i: the 1st chord of A minor, minor (lower case)"
    assert explain(ch("Bb"), C) == (
        "♭VII: built on the lowered 7th degree of C major, major (upper case); borrowed from C minor")
    assert explain(ch("D"), C, ch("G")) == "V/V: the V of V in C major, major (upper case); leads to G"
    assert explain(ch("E"), C, ch("F")) == (
        "V/vi: the V of vi in C major, major (upper case); points to Am")
    assert explain(ch("G7"), C) == "V7: the 5th chord of C major, major (upper case) with a 7th (7)"
    assert explain(ch("F#"), C) == "♯IV: built on the raised 4th degree of C major, major (upper case); outside C major"


def test_explain_says_what_the_bass_is():
    assert explain(ch("C/E"), C) == "I/3: the 1st chord of C major, major (upper case); E in the bass, its 3rd"
    assert explain(ch("C/D"), C) == (
        "I/2: the 1st chord of C major, major (upper case); D in the bass, the 2nd above its root, "
        "not a note of the chord")
    assert explain(ch("G/F"), C).endswith("; F in the bass, the lowered 7th above its root, not a note of the chord")
    assert explain(ch("G7/F"), C).endswith("; F in the bass, its 7th")
    assert explain(ch("Am/C"), C).endswith("; C in the bass, its 3rd")
    assert explain(ch("Cadd9/D"), C).endswith("; D in the bass, its 9th")


def test_the_glossary_lists_only_the_symbols_the_chords_use_with_their_own_chords_as_examples():
    plain = glossary([ch("C"), ch("Am"), ch("G7"), ch("C")], C)
    assert [symbol for symbol, _, _ in plain] == ["I–VII", "I", "i", "7"]
    assert "C major" in plain[0][1]
    assert plain[3][2] == "G7 = V7"
    rich = glossary([ch(n) for n in "C Bb D7 G C/E Bm7b5 E Am".split()], C)
    symbols = [symbol for symbol, _, _ in rich]
    assert symbols == ["I–VII", "I", "i", "♭", "ø", "7", "/3", "V/x"]
    assert dict((s, e) for s, _, e in rich)["V/x"] == "D7 = V7/V"
    assert glossary([], C) == []


def test_the_glossary_names_the_key_the_numerals_are_read_in():
    chords = [ch(n) for n in "Am F C G".split()]
    assert "A minor" in glossary(chords, A_MINOR)[0][1]
    assert "C major" in glossary(chords, C)[0][1]


# --- chord tones and scales ---------------------------------------------------------------------


def test_chord_tones_name_each_note_and_its_interval():
    assert chord_tones(ch("C7"), C) == [("C", "R"), ("E", "3"), ("G", "5"), ("Bb", "♭7")]
    assert chord_tones(ch("Am7b5"), None) == [("A", "R"), ("C", "♭3"), ("Eb", "♭5"), ("G", "♭7")]
    assert chord_tones(ch("E7"), C) == [("E", "R"), ("G#", "3"), ("B", "5"), ("D", "♭7")]
    assert chord_tones(ch("Cadd9"), C) == [("C", "R"), ("E", "3"), ("G", "5"), ("D", "9")]
    assert chord_tones(ch("Csus4"), C) == [("C", "R"), ("F", "4"), ("G", "5")]
    assert chord_tones(ch("C/D"), C) == [("C", "R"), ("D", "2"), ("E", "3"), ("G", "5")]
    assert chord_tones(ch("Caug"), C) == [("C", "R"), ("E", "3"), ("G#", "♯5")]


def test_the_scale_for_a_solo_over_each_chord():
    assert solo_scale(ch("Dm7"), C) == ("D Dorian", ("D", "E", "F", "G", "A", "B", "C"))
    assert solo_scale(ch("C"), C) == ("C major", ("C", "D", "E", "F", "G", "A", "B"))
    assert solo_scale(ch("G7"), C)[0] == "G Mixolydian"
    assert solo_scale(ch("Am"), C)[0] == "A minor"
    assert solo_scale(ch("Bm7b5"), C)[0] == "B Locrian"
    # Borrowed: the mode of the key it came from, on its root. Bb from C minor: Bb Mixolydian.
    assert solo_scale(ch("Bb"), C) == ("Bb Mixolydian", ("Bb", "C", "D", "Eb", "F", "G", "Ab"))
    # A secondary dominant: Mixolydian. E7 in C is the V of vi wherever it goes.
    assert solo_scale(ch("E7"), C) == ("E Mixolydian", ("E", "F#", "G#", "A", "B", "C#", "D"))
    # By quality otherwise.
    # C#m7b5 is not spelled Db in C: from Db its notes would need Fb, Abb and Cb.
    assert chord_tones(ch("C#m7b5"), C) == [("C#", "R"), ("E", "♭3"), ("G", "♭5"), ("B", "♭7")]
    assert solo_scale(ch("C#m7b5"), C) == ("C# Locrian", ("C#", "D", "E", "F#", "G", "A", "B"))
    # C#dim7 to Dm is its leading-tone chord: C#, a half step below D.
    assert solo_scale(ch("C#dim7"), C)[0] == "C# diminished (whole-half)"
    # The raised seventh of a minor key's dominant: Phrygian dominant.
    assert solo_scale(ch("E7"), A_MINOR) == ("E Phrygian dominant", ("E", "F", "G#", "A", "B", "C", "D"))


def test_notes_keep_one_letter_per_degree():
    # G#7, the V7 of C# minor and the V7/vi of E major: its 3rd is B#, not C.
    c_sharp_minor, e_major = Key(1, "aeolian"), Key(4, "ionian")
    g_sharp_7 = [("G#", "R"), ("B#", "3"), ("D#", "5"), ("F#", "♭7")]
    assert chord_tones(ch("G#7"), c_sharp_minor) == g_sharp_7
    assert chord_tones(ch("G#7"), e_major) == g_sharp_7
    assert solo_scale(ch("G#7"), c_sharp_minor) == (
        "G# Phrygian dominant", ("G#", "A", "B#", "C#", "D#", "E", "F#"))
    assert chord_tones(ch("C#"), Key(9, "ionian")) == [("C#", "R"), ("E#", "3"), ("G#", "5")]
    assert solo_scale(ch("F#"), C) == ("F# major", ("F#", "G#", "A#", "B", "C#", "D#", "E#"))
    assert solo_scale(ch("Db"), Key(3, "ionian")) == (
        "Db Mixolydian", ("Db", "Eb", "F", "Gb", "Ab", "Bb", "Cb"))


def test_every_seven_note_scale_and_chord_has_a_letter_per_degree_in_every_key():
    for tonic in range(12):
        for mode in ("ionian", "aeolian"):
            key = Key(tonic, mode)
            for root in range(12):
                for quality in ("", "m", "7", "maj7", "m7", "m7b5", "dim7", "aug", "mmaj7", "7b9"):
                    chord = Chord(root, quality)
                    name, notes = solo_scale(chord, key)
                    if len(notes) == 7:
                        assert len({n[0] for n in notes}) == 7, (key, chord, name, notes)
                    assert chord.pitch_classes <= {pc(n) for n in notes}, (key, chord, name, notes)
                    tones = chord_tones(chord, key)
                    letters = [n[0] for n, _ in tones]
                    assert len(set(letters)) == len(letters), (key, chord, tones)
                    assert {pc(n) for n, _ in tones} == chord.pitch_classes


def test_a_secondary_chords_root_is_spelled_from_the_chord_it_leads_to():
    # G#dim7 to Am in C: the leading tone of A is G#, not Ab.
    assert dict((s, e) for s, _, e in glossary([ch("G#dim7"), ch("Am")], C))["vii°/x"] == "G#dim7 = vii°7/vi"
    assert solo_scale(ch("G#dim7"), C)[0] == "G# diminished (whole-half)"
    assert chord_tones(ch("G#dim7"), C) == [("G#", "R"), ("B", "♭3"), ("D", "♭5"), ("F", "♭♭7")]


def test_d7_in_c_takes_d_mixolydian_as_the_v_of_v_or_as_c_lydians_ii():
    assert solo_scale(ch("D7"), C) == ("D Mixolydian", ("D", "E", "F#", "G", "A", "B", "C"))


def test_the_keys_scale_and_its_pentatonic():
    assert key_scale(C) == (0, 2, 4, 5, 7, 9, 11)
    assert key_scale(A_MINOR) == (9, 11, 0, 2, 4, 5, 7)
    assert pentatonic(C) == (0, 2, 4, 7, 9)
    assert pentatonic(A_MINOR) == (9, 0, 2, 4, 7)
    for mode in SCALES:
        for tonic in range(12):
            key = Key(tonic, mode)
            assert set(pentatonic(key)) <= scale(key) and len(pentatonic(key)) == 5
            assert key_scale(key)[0] == tonic and set(key_scale(key)) == scale(key)


# --- progressions -------------------------------------------------------------------------------

POP = ("C", "G", "Am", "F")


@pytest.mark.parametrize("tonic", range(12))
def test_the_pop_progression_is_named_in_every_rotation_and_key(tonic):
    key = Key(tonic, "ionian")
    chords = [Chord((ch(n).root + tonic) % 12, ch(n).quality) for n in POP]
    for turn in range(4):
        turned = chords[turn:] + chords[:turn]
        [(name, found)] = progressions([("Chorus", turned)], key)
        assert (name, found.name) == ("Chorus", "the pop progression")


def test_the_pop_progression_read_in_the_relative_minor_is_named_too():
    [(_, found)] = progressions([("Chorus", section("Am F C G"))], A_MINOR)
    assert (found.numerals, found.name) == (("i", "♭VI", "♭III", "♭VII"), "the pop progression")


def test_repeats_are_folded():
    [(_, found)] = progressions([("Chorus", section("Am F C G " * 4))], C)
    assert found == Progression(("vi", "IV", "I", "V"), 4, "the pop progression", "half")


def test_a_chord_held_over_two_lines_is_one_chord_of_the_progression():
    [(_, found)] = progressions([("Verse", section("C C G G Am Am F F"))], C)
    assert (found.numerals, found.repeats) == (("I", "V", "vi", "IV"), 1)


def test_the_andalusian_cadence_in_a_minor():
    [(_, found)] = progressions([("Intro", section("Am G F E"))], A_MINOR)
    assert found == Progression(("i", "♭VII", "♭VI", "V"), 1, "the Andalusian cadence", "half")


@pytest.mark.parametrize("names", [
    "C7 F7 C7 G7 F7 C7",
    "C7 F7 C7 G7 F7 C7 G7",
    "C7 F7 C7 F7 C7 G7 F7 C7",
    "C F C G F C",
    "C7 F C7 G7 F C7",
])
def test_the_twelve_bar_blues(names):
    [(_, found)] = progressions([("Verse", section(names))], C)
    assert found.name == "the 12-bar blues"


@pytest.mark.parametrize(("names", "key", "name"), [
    ("C Am F G", C, "the '50s progression"),
    ("Dm7 G7 Cmaj7", C, "ii–V–I"),
    ("Bm7b5 E7 Am", A_MINOR, "the minor ii–V–i"),
    ("C F G", C, "I–IV–V"),
    ("C Bb F", C, "the double-plagal progression"),
    ("Am Dm G C", C, "the circle of fifths"),
    ("C G Am Em F C F G", C, "Pachelbel's Canon"),
    ("E7 A7 D7 G7", C, "the ragtime progression"),
    ("F G Em Am", C, "the royal road"),
    ("C Dm Em F", C, None),
    ("C E7 A7 D7 G7 C", C, "the ragtime progression"),
    ("Am G F E", C, "the Andalusian cadence"),
    ("Am Dm G C", A_MINOR, "the circle of fifths"),
    ("F G Em Am", A_MINOR, "the royal road"),
    ("C G Am F C", C, "the pop progression"),
    ("C G F C F", C, None),
])
def test_the_catalogue(names, key, name):
    [(_, found)] = progressions([("Verse", section(names))], key)
    assert found.name == name


@pytest.mark.parametrize(("names", "ending"), [
    ("Dm G C", "authentic"),
    ("Am E Am", "authentic"),
    ("C F C", "plagal"),
    ("C F G", "half"),
    ("C F G Am", "deceptive"),
    ("C Am", None),
    ("G", None),
])
def test_how_a_section_ends(names, ending):
    key = A_MINOR if names == "Am E Am" else C
    [(_, found)] = progressions([("Verse", section(names))], key)
    assert found.ending == ending


def test_sections_keep_their_order_and_a_section_with_no_chords_has_no_progression():
    found = progressions([("Intro", []), ("Verse", section("C G")), ("Bridge", section("N.C.")),
                          ("Chorus", section("Am F"))], C)
    assert [name for name, _ in found] == ["Verse", "Chorus"]
    assert progressions([], C) == []


def test_a_secondary_dominant_reads_the_next_sections_first_chord():
    found = progressions([("Verse", section("C D")), ("Chorus", section("G C"))], C)
    assert found[0][1].numerals == ("I", "V/V")


def test_a_chord_held_before_it_resolves_reads_the_chord_it_goes_to():
    [(_, found)] = progressions([("Verse", section("C D D7 G"))], C)
    assert found.numerals == ("I", "V/V", "V7/V", "V")
    symbols = [s for s, _, _ in glossary([ch("D"), ch("D"), ch("G")], C)]
    assert "V/x" in symbols


def test_the_catalogue_is_numerals_each_with_its_source():
    for name, numerals, source in CATALOGUE:
        assert name and len(numerals) >= 3 and source
        assert progression_key(numerals)
        assert name_of(numerals) == name  # a name stands for its numerals typed, as they are written


# --- every progression of the catalogue, where songs play it ------------------------------------

_STEPS = {"I": 0, "II": 2, "III": 4, "IV": 5, "V": 7, "VI": 9, "VII": 11}
_ROW = re.compile(r"([♭♯]?)(VII|VI|V|IV|III|II|I|vii|vi|v|iv|iii|ii|i)(°?)(?:/([♭♯]?)(VII|VI|V|IV|III|II|I|vii|vi|v|iv|iii|ii|i))?$")
# Names read only on their own tonic, never in the relative key: the blues are major, the Aeolian cadence read
# in the relative major is a deceptive IV–V–vi, and a name that is numerals says where its tonic is.
ON_ITS_TONIC = {"the 12-bar blues", "the 8-bar blues", "the Aeolian cadence", "ii–V–I", "the minor ii–V–i", "I–IV–V"}
# The rows that loop, so that a section may start on any of their chords; the others go somewhere and start on their
# first: the royal road and the circle of fifths's vi–ii–V–I among them (iii–vi–IV–V, I–vi–ii–V are neither).
LOOPS = {("I", "V", "vi", "IV"), ("I", "vi", "IV", "V"), ("I", "IV", "vii°", "iii", "vi", "ii", "V", "I"),
         ("i", "iv", "♭VII", "♭III", "♭VI", "ii°", "V", "i"), ("I", "V", "vi", "iii", "IV", "I", "IV", "V"),
         ("♭VII", "IV", "I"), ("I", "V/vi", "IV", "iv"), ("i", "♭VII", "♭VI", "♭VII")}
ROWS = [(name, numerals) for name, numerals, _ in CATALOGUE]
IDS = [f"{name} {' '.join(numerals)}" for name, numerals in ROWS]


def played(numerals, tonic: int) -> list[Chord]:
    """The triads a row of the catalogue names on ``tonic``, worked out here rather than by harmony.py: a
    numeral's root up the major scale, a V/x a fifth above x."""
    chords = []
    for text in numerals:
        accidental, roman, dim, of_accidental, of = _ROW.match(text).groups()
        root = _STEPS[roman.upper()] + {"♭": -1, "♯": 1, "": 0}[accidental]
        if of:
            root += _STEPS[of.upper()] + {"♭": -1, "♯": 1, "": 0}[of_accidental]
        chords.append(Chord((tonic + root) % 12, "dim" if dim else "m" if roman.islower() else ""))
    return chords


def own_key(numerals) -> Key:
    """A row with a minor tonic (i) is in A minor, the others in C major."""
    return A_MINOR if "i" in numerals else C


def named(chords, key: Key) -> Progression:
    [(_, found)] = progressions([("Verse", chords)], key)
    return found


@pytest.mark.parametrize(("name", "numerals"), ROWS, ids=IDS)
def test_every_catalogue_progression_is_named_in_its_own_key_and_in_the_relative_one(name, numerals):
    key = own_key(numerals)
    chords = played(numerals, key.tonic)
    assert named(chords, key).name == name
    relative = C if key == A_MINOR else A_MINOR
    assert named(chords, relative).name == (None if name in ON_ITS_TONIC else name)
    # In another key altogether, the same.
    up = [Chord((c.root + 5) % 12, c.quality) for c in chords]
    assert named(up, Key((key.tonic + 5) % 12, key.mode)).name == name


@pytest.mark.parametrize(("name", "numerals"), ROWS, ids=IDS)
def test_a_progression_that_loops_is_named_from_any_of_its_chords_one_that_goes_somewhere_only_from_its_first(
        name, numerals):
    key = own_key(numerals)
    chords = played(numerals, key.tonic)
    closed = chords[0] == chords[-1]
    cycle, written = (chords[:-1], numerals[:-1]) if closed else (chords, numerals)
    rows = {ns for n, ns in ROWS if n == name}
    for turn in range(1, len(cycle)):
        turned = cycle[turn:] + cycle[:turn]
        if numerals in LOOPS:
            assert named(turned, key).name == name, turn
        elif tuple(written[turn:] + written[:turn]) not in rows:  # the ragtime progression from its I, or to it
            assert named(turned, key).name != name, turn


def test_the_loops_are_rows_of_the_catalogue():
    assert LOOPS <= {numerals for _, numerals in ROWS}


@pytest.mark.parametrize(("name", "numerals"), ROWS, ids=IDS)
def test_every_catalogue_progression_is_found_inside_a_longer_section(name, numerals):
    key = own_key(numerals)
    # Two chords before it and one after that start no progression of the catalogue with it: ♯IV° and ♭II
    # are in no row.
    odd = [Chord((key.tonic + 6) % 12, "dim"), Chord((key.tonic + 1) % 12, "")]
    found = named(odd + played(numerals, key.tonic) + odd[:1], key)
    assert found.name is None
    assert [c.name for c in found.contains] == [name]
    assert found.contains[0].times == 1


def test_extensions_inversions_suspensions_and_power_chords_dont_stop_a_name():
    for names in ("Cmaj7 G/B Am7 Fadd9", "C G7sus4 Am F/A", "C5 G5 A5 F5", "Csus2 G Asus4 F"):
        assert named(section(names), C).name == "the pop progression", names
    # A suspended chord has no third: Asus4 is vi as well as VI, and Dsus4 ii as well as II.
    assert named(section("Dsus4 G C"), C).name == "ii–V–I"
    assert named(section("Am7 G/B Fmaj7 E7"), A_MINOR).name == "the Andalusian cadence"
    # A chord held a while, or played with its suspension first, is one chord of the progression.
    assert named(section("C C/E G Gsus4 G Am Am7 F Fmaj7"), C).name == "the pop progression"


def test_wonderwalls_verse_folds_with_its_one_variation_and_is_no_famous_progression():
    # Oasis's verse as sheets write it (capo 2): Em7 G Dsus4 A7sus4, with one pass on Cadd9 in place of its first
    # two chords (one chord changed, one left out). In E minor, i–♭III–♭VII–IV: three rising fifths back to the
    # tonic (G D A E), the IV a Dorian IV (A7sus4 has no third: IV or iv); from its G, ♭III–♭VII–IV–i, the last four
    # chords of the extended plagal progression's chain of fifths (♭VI–♭III–♭VII–IV–I, "Hey Joe") come home to a
    # minor tonic, which that progression's major I is not. No progression of the catalogue: in G major it is
    # vi–I–V–II, and its ♭VII–IV–i is no double plagal, which comes home to a major I.
    verse = "Em7 G Dsus4 A7sus4 " * 3 + "Cadd9 Dsus4 A7sus4 " + "Em7 G Dsus4 A7sus4 " * 4
    e_minor = Key(4, "aeolian")
    assert named(section(verse), e_minor) == Progression(("i7", "♭III", "♭VIIsus4", "IV7sus4"), 8, None, None,
                                                         variations=1)
    in_g = named(section(verse), Key(7, "ionian"))
    assert (in_g.numerals, in_g.name, in_g.contains) == (("vi7", "I", "Vsus4", "II7sus4"), None, ())
    # Its pre-chorus's Cadd9 Dsus4 Em7 is the Aeolian cadence, three times. Its Cadd9 Dsus4 G Em7 then (in G
    # major, IV–V–I–vi) is the '50s progression from its IV played once: a cadence, no doo-wop loop.
    pre = named(section("Cadd9 Dsus4 Em7 " * 3 + "Cadd9 Dsus4 G G/F# Em7 Dsus4/F# A7sus4"), e_minor)
    assert pre.contains == (Contained("the Aeolian cadence", 3, ("♭VIadd9", "♭VIIsus4", "i7"), "i ♭VI ♭VII"),)


def test_a_famous_progression_inside_a_longer_section_is_named_with_the_times_it_is_played():
    found = named(section("Dm C G Am F Bb C G Am F"), C)
    assert (found.name, found.repeats) == (None, 1)
    assert found.contains == (Contained("the pop progression", 2, ("I", "V", "vi", "IV"), "I V vi IV"),)
    # Two in one section, each by the times it is played, in the order they come.
    found = named(section("Dm7 G7 Cmaj7 Am G F E7 Am G F E7"), C)
    assert [(c.name, c.times) for c in found.contains] == [("ii–V–I", 1), ("the Andalusian cadence", 2)]
    # A blues played twice shares the I it ends on with the next.
    found = named(section("C7 F7 C7 G7 F7 C7 F7 C7 G7 F7 C7 Am"), C)
    assert [(c.name, c.times) for c in found.contains] == [("the 12-bar blues", 2)]
    # A section that is the progression whole is named so, and contains nothing else.
    found = named(section("Am F C G " * 2), C)
    assert (found.name, found.contains) == ("the pop progression", ())


def test_a_near_miss_is_not_named():
    for names, key in (("C G Am Em", C),  # I–V–vi–iii: half of the Canon
                       ("F G Am C", C),  # IV–V–vi: the Aeolian cadence comes home to its own tonic only
                       ("F G E7 Am", A_MINOR)):  # ♭VI–♭VII–V–i: no royal road (♭VI–♭VII–v–i), no Aeolian cadence
        found = named(section(names), key)
        assert (found.name, found.contains) == (None, ()), names
    assert named(section("F G Em7 Am7"), A_MINOR).name == "the royal road"
    # i–♭VII–♭VI–♭VII is the Aeolian shuttle, and i–♭VII–♭VI–v the lament, never the Andalusian cadence.
    assert named(section("Am G F G"), A_MINOR).name == "the Aeolian shuttle"
    assert named(section("Am G F Em " * 2), A_MINOR).name == "the lament"
    assert named(section("G B C Cm"), Key(7, "ionian")).name == "the Creep progression"
    assert named(section("G Bm C Cm"), Key(7, "ionian")).name is None  # iii is no III


def test_the_andalusian_cadence_in_any_minor_key_and_read_in_the_relative_major():
    assert named(section("Am G F E"), A_MINOR).name == "the Andalusian cadence"
    assert named(section("Dm C Bb A"), Key(2, "aeolian")).name == "the Andalusian cadence"
    assert named(section("F#m E D C#7"), Key(6, "aeolian")).name == "the Andalusian cadence"
    assert named(section("Am G F E"), C).name == "the Andalusian cadence"  # vi–V–IV–V/vi
    assert named(section("Em D C B7"), Key(7, "ionian")).name == "the Andalusian cadence"


@pytest.fixture
def catalogue_of(monkeypatch):
    """Read progressions with the catalogue a test gives (rows that loop none), the kept answers cleared before and
    after."""
    def clear():
        for v in vars(harmony).values():
            if callable(getattr(v, "cache_clear", None)) and getattr(v, "__module__", "") == harmony.__name__:
                v.cache_clear()

    def use(rows):
        monkeypatch.setattr(harmony, "CATALOGUE", rows)
        monkeypatch.setattr(harmony, "_LOOPS", frozenset())
        clear()

    yield use
    monkeypatch.undo()
    clear()


def test_a_chord_lent_to_the_next_run_is_held_once(catalogue_of):
    # A run that ends on the chord it starts with (the blues, on I) lends that chord to the next run: I–IV–I then
    # I–V–vi hold five chords, not six, as many as one run of I–IV–I–V–vi, which is read, being one run.
    catalogue_of((("the lending row", ("I", "IV", "I"), "a test"), ("the next row", ("I", "V", "vi"), "a test"),
                  ("the long row", ("I", "IV", "I", "V", "vi"), "a test")))
    found = named(section("Db C F C G Am"), C)  # ♭II first: the section is no row whole
    assert [(c.name, c.times) for c in found.contains] == [("the long row", 1)]


def test_the_lament_is_the_andalusian_cadences_descent_onto_a_minor_v():
    # Open Music Theory's lament, i–♭VII–♭VI–v (Eva Simons's "I Don't Like You"), in A minor, in D minor, and read
    # in C major (vi–V–IV–iii); with V, the Andalusian cadence.
    assert named(section("Am G F Em"), A_MINOR) == Progression(("i", "♭VII", "♭VI", "v"), 1, "the lament", None)
    assert named(section("Dm7 C Bb Am7"), Key(2, "aeolian")).name == "the lament"
    assert named(section("Am G F Em"), C).name == "the lament"
    assert named(section("Am G F E7"), A_MINOR).name == "the Andalusian cadence"


@pytest.mark.parametrize(("names", "key", "contains"), [
    # An I–V–IV vamp, its last pass cut short before the chorus, or played three times: no 8-bar blues.
    ("G D C G D C G D", Key(7, "ionian"), []),
    ("C G F " * 3, C, []),
    # iii–vi–IV–V (F#m Bm G A in D, "Hey There Delilah") is no royal road, which starts on its IV.
    ("Em Am F G", C, []),
    ("F#m Bm G A", Key(2, "ionian"), []),
    # I–vi–ii–V, jazz's turnaround, and V–I–vi–ii are no circle of fifths, which is vi–ii–V–I.
    ("C Am Dm G", C, []),
    ("G C Am Dm", C, []),
    # Played round and round, a cycle is read from where each pass starts: the vi–ii–V–I and the ii–V–I across
    # the seam of I–vi–ii–V are no progression of it, nor the ii–V–I across V–I–ii's.
    ("C Am Dm G " * 4 + "C", C, []),
    ("G C Dm " * 2, C, []),
    # A major key's IV–V–vi–V is no Aeolian shuttle, which circles on a minor tonic.
    ("F G Am G", C, []),
    ("C F G Am G F C", C, ["I–IV–V"]),
    # A loop played once from another of its chords within a longer section is a cadence there ("Yesterday",
    # vi–IV–V–I), no '50s progression.
    ("F Em7 A7 Dm Dm/C Bb C7 F", Key(5, "ionian"), []),
])
def test_no_name_for_a_vamp_or_a_turn_its_sources_dont_give(names, key, contains):
    found = named(section(names), key)
    assert (found.name, [c.name for c in found.contains]) == (None, contains)


def test_a_progression_within_each_pass_of_a_loop_and_a_turned_loop_played_twice_are_named():
    found = named(section("Dm7 G7 Cmaj7 A7 " * 4), C)  # ii–V–I–V/ii: a ii–V–I in every pass
    assert (found.repeats, found.contains) == (4, (Contained("ii–V–I", 4, ("ii7", "V7", "Imaj7"), "I ii V"),))
    found = named(section("Am F G C " * 2 + "E7"), C)  # vi–IV–V–I twice, then somewhere else
    assert [(c.name, c.times) for c in found.contains] == [("the '50s progression", 2)]


def test_typed_numerals_are_named_as_a_section_is():
    for typed in ("I V IV I V IV I V", "iii vi IV V", "IV V vi V", "I vi ii V", "V I vi ii"):
        assert name_of(typed) is None, typed
    assert name_of("vi IV I V") == "the pop progression"
    assert name_of("i bVII bVI bVII") == "the Aeolian shuttle"


def test_numerals_typed_in_a_minor_keys_own_way_are_named():
    # Written against the natural minor scale, as Wikipedia writes the minor circle (i–iv–VII–III–VI–ii°–V–i), an
    # unaltered III, VI and VII of a minor tonic are its ♭III, ♭VI and ♭VII.
    assert read_typed("i VII VI VII") == ("i", "♭VII", "♭VI", "♭VII")
    assert read_typed("i7–iv–VII7") == ("i7", "iv", "♭VII7")
    assert name_of("i VII VI VII") == "the Aeolian shuttle"
    assert name_of("i–iv–VII–III–VI–ii°–V–i") == "the circle of fifths"
    assert name_of("i VII VI V") == "the Andalusian cadence"
    assert name_of("i VII VI v") == "the lament"
    # With a major tonic, or an accidental typed, the numerals are as written: VII is the major chord on the 7th.
    assert read_typed("I VII IV") == ("I", "VII", "IV") and name_of("I VII IV") is None
    assert read_typed(["i", "bVII", "VI"]) == ("i", "bVII", "VI")


def test_a_sections_repeats_fold_even_when_one_pass_varies_a_chord():
    found = named(section("C G Am F " * 3 + "C G Am Dm"), C)
    assert (found.numerals, found.repeats, found.variations, found.name) == (
        ("I", "V", "vi", "IV"), 4, 1, "the pop progression")
    # A pass with a chord more, or one less, is a variation too, and in a cycle of four chords or more, one with a
    # chord changed besides.
    assert named(section("C G Am F " * 2 + "C G Em Am F " + "C G Am F"), C).variations == 1
    assert named(section("C G Am F " * 2 + "C Am F " + "C G Am F"), C).variations == 1
    assert named(section("C G Am F " * 2 + "C Em Am F G " + "C G Am F"), C).variations == 1
    # Two chords changed are another line, half of a cycle of four: no variation.
    other = named(section("C G Am F " * 3 + "Dm G C F"), C)
    assert (other.repeats, other.variations, [c.name for c in other.contains]) == (
        1, 0, ["the pop progression", "ii–V–I"])
    # Played whole every time, there is no variation, and a cycle twice varied still folds with both.
    assert named(section("C G Am F " * 4), C).variations == 0
    eight = named(section("C G Am F C G Am Dm " * 3), C)  # the whole eight chords, three times
    assert (len(eight.numerals), eight.repeats, eight.variations) == (8, 3, 0)
    twice = named(section("C G Am F " * 4 + "C G Am Dm " + "C G Am F " + "C G Am Dm"), C)
    assert (twice.repeats, twice.variations) == (7, 2)
    # A variation needs the cycle at least twice besides, and more often than not.
    assert named(section("C G Am F C G Am Em"), C).repeats == 1
    assert named(section("C G Am F C G Am Em C G Am Dm"), C).repeats == 1
    # The section may end on the cycle's first chord: home, not a pass.
    ends = named(section("C G Am F " * 2 + "C"), C)
    assert (ends.numerals, ends.repeats, ends.variations) == (("I", "V", "vi", "IV"), 2, 0)


# --- the progression's search key ---------------------------------------------------------------


def test_a_progressions_key_is_the_same_for_every_rotation_and_repeat():
    pop = progression_key(("I", "V", "vi", "IV"))
    assert pop == "I V vi IV"
    assert progression_key(("vi", "IV", "I", "V")) == pop
    assert progression_key(("IV", "I", "V", "vi", "IV", "I", "V", "vi")) == pop
    assert progression_key(("Imaj7", "V7", "vi7", "IVadd9")) == pop
    assert progression_key("vi IV I V") == pop
    assert progression_key("vi–IV–I–V") == pop
    assert progression_key(("bVII", "IV", "I")) == progression_key(("I", "♭VII", "IV"))
    assert progression_key(("I", "vi", "IV", "V")) != pop
    assert progression_key(("V7/V", "V", "I")) != progression_key(("V", "V", "I"))
    assert progression_key(("I/3", "IV", "V")) == progression_key(("I", "IV", "V"))
    # A cycle that comes back to its first chord at the end plays that chord once.
    assert progression_key("I V vi IV I") == pop
    assert progression_key("I I") == "I"
    # A V/IV is built on the tonic: its root is the I's.
    assert progression_key(("I", "V7/IV", "IV", "V")) == progression_key(("I", "IV", "V"))
    assert progression_key(("i", "V7/iv", "iv")) == progression_key(("i", "I", "iv"))


# --- kept answers -------------------------------------------------------------------------------


def test_answers_are_frozen_and_a_list_handed_out_is_a_copy():
    with pytest.raises(dataclasses.FrozenInstanceError):
        numeral(ch("C"), C).roman = "V"
    first = glossary([ch("C"), ch("G")], C)
    first.clear()
    assert glossary([ch("C"), ch("G")], C)
    tones = chord_tones(ch("C"), C)
    tones.append(("X", "?"))
    assert chord_tones(ch("C"), C) == [("C", "R"), ("E", "3"), ("G", "5")]
    sections = [("Verse", section("C G"))]
    found = progressions(sections, C)
    found.clear()
    assert progressions(sections, C)


def test_the_kept_answers_are_the_answers_asked_anew():
    kept = [v for v in vars(harmony).values()
            if callable(getattr(v, "cache_clear", None)) and v.__module__ == harmony.__name__]
    assert kept
    chords = [ch(n) for n in "C Dm7 E7 Am Bb D7 G C/E F#m7b5 G#dim7".split()]
    keys = (C, A_MINOR, Key(0, "mixolydian"))

    def answers():
        return [(numeral(c, k, n).text, relation(c, k, n), family(c, k), explain(c, k, n),
                 chord_tones(c, k), solo_scale(c, k))
                for k in keys for c, n in zip(chords, chords[1:] + [None], strict=True)] + [
            glossary(chords, k) for k in keys] + [progressions([("V", chords)], k) for k in keys] + [
            name_of(("vi", "IV", "I", "V")), name_of(("i", "♭VI", "♭III", "♭VII"))]

    for function in kept:
        function.cache_clear()
    assert answers() == answers()


def test_harmony_is_part_of_what_a_page_is_made_from():
    assert page.HERE / "harmony.py" in page.BUILD_FILES
