"""caracole.viewer.harmony: numerals, relations, families, glossary lines, chord tones, scales and
progressions, on top of viewer/theory.py."""

from __future__ import annotations

import dataclasses

import pytest

from caracole.viewer import harmony, page
from caracole.viewer.harmony import (
    CATALOGUE,
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
    progression_key,
    progressions,
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
    ("C Bb F", C, "I–♭VII–IV"),
    ("Am Dm G C", C, "the circle of fifths"),
    ("C G Am Em F C F G", C, "the Canon"),
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


def test_the_catalogue_is_numerals():
    for name, numerals in CATALOGUE:
        assert name and len(numerals) >= 3
        assert progression_key(numerals)


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
            glossary(chords, k) for k in keys] + [progressions([("V", chords)], k) for k in keys]

    for function in kept:
        function.cache_clear()
    assert answers() == answers()


def test_harmony_is_part_of_what_a_page_is_made_from():
    assert page.HERE / "harmony.py" in page.BUILD_FILES
