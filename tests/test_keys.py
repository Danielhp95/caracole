"""keys.py: a song's musical key, read from its tab or estimated from its chords."""

from __future__ import annotations

import pytest

from caracole.keys import chords_in_sheet, estimate_key, key_in_text, key_name, parse_key, same_key


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Am", "A minor"),
        ("A minor", "A minor"),
        ("A min", "A minor"),
        ("Amin", "A minor"),
        ("A Minor", "A minor"),
        ("F#m", "F# minor"),
        ("Bbm", "Bb minor"),
        ("Eb", "Eb"),
        ("E♭", "Eb"),
        ("C♯m", "C# minor"),
        ("C", "C"),
        ("C major", "C"),
        ("Cmaj", "C"),
        ("  G ", "G"),
        ("Do", "C"),
        ("do mayor", "C"),
        ("La menor", "A minor"),
        ("Lam", "A minor"),
        ("Sib", "Bb"),
        ("Fa#m", "F# minor"),
        ("Sol", "G"),
        ("Re menor", "D minor"),
    ],
)
def test_parse_key_reads_the_ways_tabs_write_a_key(text, key):
    assert parse_key(text) == key


@pytest.mark.parametrize("text", ["", "   ", "H", "Am7", "C/G", "Hello", "am", "A minor blues", "x2"])
def test_parse_key_refuses_what_is_not_a_key(text):
    assert parse_key(text) is None


def test_key_name_spells_out_the_mode():
    assert key_name("C") == "C major"
    assert key_name("F#") == "F# major"
    assert key_name("A minor") == "A minor"


def test_same_key_compares_enharmonic_spellings():
    assert same_key("F# minor", "Gb minor")
    assert same_key("C", "C")
    assert not same_key("A minor", "C")
    assert not same_key("A minor", "A")


# --- the tab's own word ------------------------------------------------------------------


def test_a_chordpro_key_directive_is_the_tabs_key():
    assert key_in_text("{title: Song}\n{key: Am}\n[Verse]\n[ch]Am[/ch] [ch]F[/ch]\nWords") == "A minor"


def test_a_key_line_before_the_first_chords_is_the_tabs_key():
    sheet = "Capo 2\nKey: G\n\n[Intro]\n[ch]G[/ch] [ch]C[/ch]\nWords here\n"
    assert key_in_text(sheet) == "G"


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("Tono: La menor", "A minor"),
        ("TONO: Re", "D"),
        ("Tonalidad: Mi menor", "E minor"),
        ("Tono original: Do", "C"),
        ("Key: [ch]F#m[/ch]", "F# minor"),
        ("Key of Bb", "Bb"),
        ("Key - Em (capo 3)", "E minor"),
        ("Tuning: E A D G B E, Key: Em", "E minor"),
        ("Key: Am  Capo: 2", "A minor"),
    ],
)
def test_key_lines_in_english_and_spanish(line, key):
    assert key_in_text(f"{line}\n\n[ch]Am[/ch] [ch]G[/ch]\nWords\n") == key


def test_a_key_line_after_the_chords_start_is_not_read():
    sheet = "[Verse]\n[ch]G[/ch]        [ch]C[/ch]\nKey: D is where it goes after\n"
    assert key_in_text(sheet) is None


@pytest.mark.parametrize(
    "line",
    ["The key: I lost it", "Key change: up a tone", "Monkey: G", "Keys: Am", "no key here"],
)
def test_lines_that_only_look_like_a_key_line(line):
    assert key_in_text(f"{line}\n[ch]G[/ch]\nWords\n") is None


# --- the chords --------------------------------------------------------------------------


def test_chords_in_sheet_reads_the_chord_tags_in_order_with_letter_names():
    sheet = "[Intro]\n[ch]Am[/ch]-[ch]F[/ch]\n[ch]Do[/ch]  [ch]Sol7[/ch]\nWords\n[ch]N.C.[/ch]"
    assert chords_in_sheet(sheet) == ["Am", "F", "C", "G7", "N.C."]


@pytest.mark.parametrize(
    ("progression", "key"),
    [
        ("G D Em C G D Em C", "G"),
        ("Am F C G Am F C G", "A minor"),
        ("C G Am F C G Am F", "C"),
        ("Em C G D Em C G D", "E minor"),
        ("D A Bm G D A Bm G", "D"),
        ("Am Dm E7 Am Am Dm E7 Am", "A minor"),
        ("A7 A7 A7 A7 D7 D7 A7 A7 E7 D7 A7 E7", "A"),
        ("F C Dm Bb F C Dm Bb", "F"),
        ("D A Bm F#m G D G A", "D"),
        ("Am G F E Am G F E", "A minor"),
        ("Dm Bb F C Dm Bb F C", "D minor"),
        ("Bm G D A Bm G D A", "B minor"),
        ("Am C D F Am C E Am", "A minor"),
        ("Cm Ab Eb Bb Cm Ab Eb Bb", "C minor"),
        ("F#m D A E F#m D A E", "F# minor"),
        ("Em D C B7 Em D C B7 Em", "E minor"),
        ("Gm F Eb D7 Gm", "G minor"),
        ("E A E B7 E A B7 E", "E"),
        ("Bm F# A E G D Em F#", "B minor"),
        ("G D Am G D C G D Am", "G"),
        ("Am G#+ C/G D/F# Fmaj7 G Am", "A minor"),
        ("F G C Am F G C", "C"),
        ("G G7 C Cm G D7 G", "G"),
        ("Am Am7 D7 Am Em Am", "A minor"),
        ("F5 Bb5 Ab5 Db5 F5 Bb5 Ab5 Db5", "F minor"),
        ("Lam Fa Do Sol", "A minor"),
    ],
)
def test_estimate_key_from_well_known_progressions(progression, key):
    assert estimate_key(progression.split()) == key


def test_the_estimate_spells_the_tonic_as_the_chords_do():
    assert estimate_key("C#m A E B C#m A E B".split()) == "C# minor"
    assert estimate_key("Gb Db Ebm Cb Gb Db Ebm Cb".split()) == "Gb"
    assert estimate_key("F# C# D#m B F# C# D#m B".split()) == "F#"


def test_the_estimate_weighs_each_chord_by_its_duration():
    # The same four chords: the one that rings longest is home.
    assert estimate_key([("Am", 1.0), ("C", 20.0), ("G", 4.0), ("F", 4.0), ("C", 20.0)]) == "C"
    assert estimate_key([("C", 1.0), ("Am", 20.0), ("G", 4.0), ("F", 4.0), ("Am", 20.0)]) == "A minor"


@pytest.mark.parametrize(
    "chords",
    [[], ["N.C.", "x2", "N"], ["C7", "F#7", "C7", "F#7"], ["C", "C#m", "D", "D#m", "E", "Fm", "F#"]],
)
def test_no_estimate_without_chords_or_from_chords_that_fit_no_key(chords):
    assert estimate_key(chords) is None
