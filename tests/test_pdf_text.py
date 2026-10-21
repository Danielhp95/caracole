"""pdf_text.py: the text a sheet's PDF is made from, and the viewer's key line in words."""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

import pytest

from caracole.chordpro import to_chordpro
from caracole.pdf_text import pdf_text
from caracole.viewer import build_viewer
from caracole.viewer.page import key_line_text, viewer_key
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import Key

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
LEGEND = (FIXTURES / "legend_sheet.cho").read_text(encoding="utf-8")
RIFF = "{start_of_tab}\ne|-----0---0---|\nB|---3-------3-|\n{end_of_tab}\n"
EM = Key(4, "aeolian")

# The cases of test_viewer.py's key line (test_the_bar_and_the_settings_say_what_the_key_line_says).
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")
MINOR = to_chordpro(
    "[ch]Cm[/ch]      [ch]Ab[/ch]\nTiny minor words\n[ch]Bb[/ch]     [ch]G7[/ch]\nand back home",
    title="Minor", artist="Placeholders", key="Cm",
)
WALL = to_chordpro(
    "[ch]Em7[/ch]      [ch]G[/ch]\nSynthetic words go here\n[ch]Dsus4[/ch]     [ch]A7sus4[/ch]\nmade up for the test\n"
    "[ch]Cadd9[/ch]  [ch]D[/ch]  [ch]Em7[/ch]\nand home",
    title="Wall", artist="Synthetic", capo=2,
)


def test_the_notes_go_the_tab_blocks_stay():
    # The legend sheet with a riff after its notes, where the viewer's preamble ends.
    cho = LEGEND.replace("\n\n{comment: Intro}", "\n\n" + RIFF + "\n{comment: Intro}")
    lines = pdf_text(cho, key=EM, capo=2).splitlines()
    text = "\n".join(lines)
    for note in ("This is a made-up note", "http://example.com/watch?v=placeholder&feature=related",
                 "and these are the chords", "Capo 2. fret", "EADGBe", "[Em7] [*(022033)]", "Dsus4   (xx0233)"):
        assert note not in text
    assert RIFF + "\n{comment: INTRO}" in text
    assert [line for line in lines if line.startswith("{define")] == [
        "{define: Em7 base-fret 1 frets 0 2 2 0 3 3 fingers 0 0 0 0 0 0}",
        "{define: G base-fret 1 frets 3 2 0 0 3 3 fingers 0 0 0 0 0 0}",
        "{define: Dsus4 base-fret 1 frets x x 0 2 3 3 fingers 0 0 0 0 0 0}",
        "{define: A7sus4 base-fret 1 frets x 0 2 0 3 3 fingers 0 0 0 0 0 0}",
        "{define: Cadd9 base-fret 1 frets x 3 2 0 3 3 fingers 0 0 0 0 0 0}",
        "{define: Dsus4/F# base-fret 1 frets 2 x 0 2 3 3 fingers 0 0 0 0 0 0}",
    ]
    assert "[Em7]Made up words f[G]or the test" in lines
    assert "[Cadd9]Still more [Dsus4/F#]words to sing" in lines


def test_a_legend_shape_is_written_for_the_chord_as_the_song_names_it():
    # A shape that doesn't play its chord is left out, as the viewer leaves it out; a chord the song
    # never plays gets none; the first of two shapes for one chord is the one used.
    cho = ("{title: Shapes}\n{artist: The Placeholders}\nA#m (x13321)\nG (x02220)\nC (x32010)\n"
           "D (xx0232)  D (x57775)\n\n{comment: Verse}\n[Bbm]Words [G]to [D]sing\n{comment: Chorus}\n[Bbm]more\n")
    defines = [line for line in pdf_text(cho, key=None, capo=None).splitlines() if line.startswith("{define")]
    assert defines == [
        "{define: Bbm base-fret 1 frets x 1 3 3 2 1 fingers 0 0 0 0 0 0}",
        "{define: D base-fret 1 frets x x 0 2 3 2 fingers 0 0 0 0 0 0}",
    ]


def test_the_header_reads_like_the_viewer():
    cho = LEGEND.replace("{artist: The Placeholders}", "{artist: Oasis}")
    lines = pdf_text(cho, key=EM, capo=2).splitlines()
    assert lines[:4] == [
        "{title: Legend Song}",
        "{artist: Oasis}",
        "{capo: 2}",
        "{subtitle: Oasis · Em shapes · capo 2 · sounds F#m}",
    ]


def test_a_tuning_note_goes_into_the_header():
    cho = ("{title: Tuned}\n{artist: The Placeholders}\n{key: Em}\nTuning: Eb Ab Db Gb Bb Eb (half step down)\n\n"
           "{comment: Verse}\n[Em]Words to sing\n{comment: Chorus}\n[G]More words\n")
    text = pdf_text(cho, key=EM, capo=None)
    assert "{subtitle: The Placeholders · Key Em · half step down}" in text.splitlines()
    assert "Tuning:" not in text


def test_a_capo_note_goes_into_the_header_of_a_sheet_without_a_capo():
    # The notes go, and a capo they name must not go with them: a capo the guitarist can't see
    # means playing in the wrong key. A sheet with a capo of its own says it in the key line.
    cho = ("{title: Capo}\n{artist: The Placeholders}\nCapo 3, to play along with the record\n\n"
           "{comment: Verse}\n[Em]Words to sing\n{comment: Chorus}\n[G]More words\n")
    assert "{subtitle: The Placeholders · Key Em · Capo 3}" in pdf_text(cho, key=EM, capo=None).splitlines()
    assert "{subtitle: The Placeholders · Em shapes · capo 2 · sounds F#m}" in pdf_text(
        cho, key=EM, capo=2).splitlines()


def test_a_header_with_nothing_to_say_has_no_subtitle():
    cho = "{title: Bare}\n{artist: }\n{comment: Verse}\nno chords here\n"
    assert not any(line.startswith("{subtitle") for line in pdf_text(cho, key=None, capo=None).splitlines())


def test_sections_are_capitals_and_the_song_is_in_two_columns():
    lines = pdf_text(LEGEND, key=EM, capo=2).splitlines()
    assert "{comment: VERSE}" in lines and "{comment: CHORUS}" in lines
    assert "{comment: Verse}" not in lines
    columns = lines.index("{columns: 2}")
    assert lines[columns - 1].startswith("{define: Dsus4/F#")  # after the header: its directives and shapes
    assert lines[columns + 1] == "{comment: INTRO}"  # then the song
    assert "{columns" not in pdf_text(LEGEND, key=EM, capo=2, columns=1)


def test_a_section_name_keeps_what_chordpro_needs_escaped():
    # A backslash at a value's end is written \ (chordpro.directive_text); capitals keep it so.
    cho = "{title: Escapes}\n{artist: A}\n" + "{comment: Verse ünd ß \\u005c}\n[Em]la\n"
    assert "{comment: VERSE ÜND SS \\u005c}" in pdf_text(cho, key=EM, capo=None).splitlines()


def test_the_auto_sheets_notice_stays_as_written_in_the_header():
    cho = "{title: Heard}\n{artist: The Placeholders}\n{comment: auto-generated, unverified}\n[C]made up words\n"
    assert pdf_text(cho, key=Key(0, "ionian"), capo=None).splitlines() == [
        "{title: Heard}",
        "{artist: The Placeholders}",
        "{comment: auto-generated, unverified}",
        "{subtitle: The Placeholders · Key C}",
        "{columns: 2}",
        "[C]made up words",
    ]


def test_a_sheet_without_notes_keeps_every_line():
    lines = pdf_text(MINOR, key=Key(0, "aeolian"), capo=None).splitlines()
    assert lines == [
        "{title: Minor}", "{artist: Placeholders}", "{key: Cm}", "{subtitle: Placeholders · Key Cm}",
        "{columns: 2}", *MINOR.splitlines()[3:],
    ]


@pytest.mark.parametrize(
    ("cho", "label"),
    [
        (UG_CHO, "G shapes · capo 2 · sounds A"),
        (WALL, "Em shapes · capo 2 · sounds F#m"),
        (MINOR, "Key Cm"),
        ("{title: No key}\n{capo: 3}\nwords alone\n", "Capo 3"),
        ("{title: Nothing}\nwords alone\n", ""),
    ],
    ids=["capo", "capo-on-open-shapes", "no-capo", "no-key", "nothing"],
)
def test_key_line_text_matches_the_viewers_facts(cho, label):
    # The viewer's key line, its markup and where the key came from left out.
    facts = re.search(r'<p class="facts" id="facts">(.*?)</p>', build_viewer(cho), re.S).group(1)
    said = unescape(re.sub(r"<[^>]+>", "", re.sub(r'(?: · )?<span class="from">.*?</span>', "", facts))).strip()
    assert key_line_text(viewer_key(cho), parse_sheet(cho).capo) == said == label
