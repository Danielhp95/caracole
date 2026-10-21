"""pdf_text.py: the text a sheet's PDF is made from, and the viewer's key line in words."""

from __future__ import annotations

import json
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
# A chord legend in a section after the first: the viewer reads its shapes wherever it is.
LATER = ("{title: Later}\n{artist: The Placeholders}\n\n{comment: Verse}\n[Em7]Words [Cadd9]to sing\n\n"
         "{comment: Chords}\nEm7 022033  Cadd9 x32033\n\n{comment: Chorus}\n[Cadd9]More [Em7]words\n")
# The sheet's own {define}s, one with no fingers, which the viewer takes from chords-db.
DEFINED = ("{title: Defined}\n{artist: The Placeholders}\n{define: Am base-fret 1 frets x 0 2 2 1 0}\n"
           "{define: E base-fret 1 frets 0 2 2 1 0 0 fingers 0 2 3 1 0 0}\n\n{comment: Verse}\n[Am]Words to [E]sing\n")
# Shapes the viewer leaves out, or that chords-db has too, and two for one chord.
SHAPES = ("{title: Shapes}\n{artist: The Placeholders}\nA#m (x13321)\nG (x02220)\nC (x32010)\n"
          "D (xx0232)  D (x57775)\n\n{comment: Verse}\n[Bbm]Words [G]to [D]sing\n{comment: Chorus}\n[Bbm]more\n")
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
        "{define: Dsus4 base-fret 1 frets x x 0 2 3 3 fingers 0 0 0 1 2 3}",  # chords-db's fingers
        "{define: A7sus4 base-fret 1 frets x 0 2 0 3 3 fingers 0 0 0 0 0 0}",
        "{define: Cadd9 base-fret 1 frets x 3 2 0 3 3 fingers 0 0 0 0 0 0}",
        "{define: Dsus4/F# base-fret 1 frets 2 x 0 2 3 3 fingers 0 0 0 0 0 0}",
    ]
    assert "[Em7]Made up words f[G]or the test" in lines
    assert "[Cadd9]Still more [Dsus4/F#]words to sing" in lines


def defines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("{define")]


def test_a_legend_shape_is_written_for_the_chord_as_the_song_names_it():
    # A shape that doesn't play its chord is left out, as the viewer leaves it out; a chord the song
    # never plays gets none; the first of two shapes for one chord is the one used, and a shape
    # chords-db has too takes its fingers, as the viewer shows it.
    assert defines(pdf_text(SHAPES, key=None, capo=None)) == [
        "{define: Bbm base-fret 1 frets x 1 3 3 2 1 fingers 0 1 3 4 2 1}",
        "{define: D base-fret 1 frets x x 0 2 3 2 fingers 0 0 0 1 3 2}",
    ]


def test_a_legend_after_the_first_section_gives_its_shapes_too():
    # It stays in the song, where the tab put it, and its shapes are the chord diagrams.
    text = pdf_text(LATER, key=None, capo=None)
    assert defines(text) == [
        "{define: Em7 base-fret 1 frets 0 2 2 0 3 3 fingers 0 0 0 0 0 0}",
        "{define: Cadd9 base-fret 1 frets x 3 2 0 3 3 fingers 0 0 0 0 0 0}",
    ]
    assert "Em7 022033  Cadd9 x32033" in text.splitlines()


def test_the_sheets_own_defines_are_written_as_the_viewer_shows_them():
    # One given without fingers takes chords-db's, as in the viewer. chordpro draws a chord's last
    # {define}, so the sheet's own go: one in the song would draw over the viewer's shape.
    cho = DEFINED + "{comment: Chorus}\n{define: Am base-fret 5 frets 1 3 3 1 1 1}\n[Am]More\n"
    text = pdf_text(cho, key=None, capo=None)
    assert defines(text) == [
        "{define: Am base-fret 1 frets x 0 2 2 1 0 fingers 0 0 2 3 1 0}",
        "{define: E base-fret 1 frets 0 2 2 1 0 0 fingers 0 2 3 1 0 0}",
    ]
    lines = text.splitlines()
    assert lines[lines.index("{comment: CHORUS}") + 1] == "[Am]More"


@pytest.mark.parametrize("cho", [LEGEND, LATER, DEFINED, SHAPES, UG_CHO, MINOR], ids=[
    "legend", "legend-later", "defines", "shapes", "no-shapes", "no-legend"])
def test_the_chord_diagrams_are_the_shapes_the_viewer_shows(cho):
    # For each chord the song plays, the first shape the viewer shows for it when the sheet gives
    # one (its data's "shapes", by the chord as shown: "<root>,<suffix>,<bass>"), and no other.
    data = json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>',
                                build_viewer(cho), re.S).group(1))
    shown = {}
    for name, chord in zip(parse_sheet(cho).chords, data["chords"], strict=True):
        entry = chord and data["shapes"].get(f"{chord[0]},{chord[1]},{'' if chord[2] is None else chord[2]}")
        if entry and entry["mine"]:
            frets, fingers, base, _ = entry["list"][0]
            shown[name] = f"base-fret {base} frets {' '.join(frets)} fingers {' '.join(fingers)}"
    drawn = dict(line[len("{define: "):-1].split(" ", 1) for line in defines(pdf_text(cho, key=None, capo=None)))
    assert drawn == shown


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


@pytest.mark.parametrize(("note", "subtitle"), [
    ("Tuning: Eb standard", "{subtitle: The Placeholders · Key Em · Eb standard}"),
    ("Please drop a comment and rate!", "{subtitle: The Placeholders · Key Em}"),
    ("drop by my channel", "{subtitle: The Placeholders · Key Em}"),
    ("Let the chorus drop down soft", "{subtitle: The Placeholders · Key Em}"),
    ("I'm not sure about the tuning here, tell me in the comments", "{subtitle: The Placeholders · Key Em}"),
], ids=["eb-standard", "drop-a-comment", "drop-by", "drop-down", "talks-about-tuning"])
def test_only_a_tuning_the_notes_name_goes_into_the_header(note, subtitle):
    # A song in standard tuning must not read as if in another: a tabber's chat stays out with the notes.
    cho = ("{title: Tuned}\n{artist: The Placeholders}\n{key: Em}\n" + note + "\n\n"
           "{comment: Verse}\n[Em]Words to sing\n{comment: Chorus}\n[G]More words\n")
    lines = pdf_text(cho, key=EM, capo=None).splitlines()
    assert [line for line in lines if line.startswith("{subtitle")] == [subtitle]
    assert note not in lines


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


# --- chord names: numerals beside the chords, or in their place ------------------------------------------

C_MAJOR = Key(0, "ionian")
# In C: D goes to G first (V/V), then to C (C Lydian's II); a chord caracole can't read stays as written.
SONG = ("{title: Numbered}\n{artist: The Placeholders}\n{key: C}\n\n{comment: Verse}\n"
        "[C]Words [Am]to [F]sing [G]here\n[D]more [G]words [D]and [C]home\n[N.C.]hey\n")


def legend(text: str) -> list[str]:
    lines = text.splitlines()
    return lines[lines.index("{comment: THE NUMERALS, IN C MAJOR}") + 1:]


def test_a_numerals_chart_has_numerals_in_the_chords_place_its_key_under_the_title_and_no_diagrams():
    lines = pdf_text(SONG, key=C_MAJOR, capo=None, names="numerals").splitlines()
    # Each chord's numeral in its place, a chord chordpro knows no shape of.
    assert "[I]Words [vi]to [IV]sing [V]here" in lines and "[V/V]more [V]words [II]and [I]home" in lines
    assert [line for line in lines if line.startswith("{define")] == [
        "{define: I}", "{define: vi}", "{define: IV}", "{define: V}", "{define: V/V}", "{define: II}"]
    assert "[N.C.]hey" in lines  # shown as written
    assert "{subtitle: The Placeholders · Key C · numerals in C major}" in lines
    assert "{diagrams: off}" in lines


def test_both_names_each_chord_and_its_numeral_with_the_viewers_shape():
    text = pdf_text(SONG, key=C_MAJOR, capo=None, names="both")
    lines = text.splitlines()
    # A chord that plays two roles is two chords for chordpro, each named for its own.
    assert "[C]Words [Am]to [F]sing [G]here" in lines and "[D]more [G]words [D~1]and [C]home" in lines
    assert "[N.C.]hey" in lines
    shown = {line.split(" ", 2)[1]: line for line in lines if line.startswith("{define")}
    assert shown["C"] == '{define: C base-fret 1 frets x 3 2 0 1 0 fingers 0 3 2 0 1 0 display "C · I"}'
    assert shown["D"].endswith(' display "D · V/V"}') and shown["D~1"].endswith(' display "D · II"}')
    assert shown["D"].split(" display")[0].split(" ", 2)[2] == shown["D~1"].split(" display")[0].split(" ", 2)[2]
    assert "N.C." not in shown
    assert "{subtitle: The Placeholders · Key C · numerals in C major}" in lines and "{diagrams: off}" not in lines


def test_both_keeps_the_shape_the_sheet_gives_a_chord():
    sheet = SONG.replace("{key: C}\n", "{key: C}\n{define: G base-fret 3 frets 1 3 3 2 1 1 fingers 1 3 4 2 1 1}\n")
    shown = [line for line in pdf_text(sheet, key=C_MAJOR, capo=None, names="both").splitlines()
             if line.startswith("{define: G ")]
    assert shown == ['{define: G base-fret 3 frets 1 3 3 2 1 1 fingers 1 3 4 2 1 1 display "G · V"}']


@pytest.mark.parametrize("names", ["both", "numerals"])
def test_numerals_end_with_a_legend_of_the_symbols_the_song_uses(names):
    found = legend(pdf_text(SONG, key=C_MAJOR, capo=None, names=names))
    assert found[0].startswith("I–VII: Roman numerals: the chord's root counted up the scale of C major")
    assert any(line.startswith("i: lower case: a minor chord (Am = vi)") for line in found)
    assert any(line.startswith("V/x: ") for line in found)
    assert not any(line.startswith(("♭", "°", "ø", "+")) for line in found)  # symbols the song doesn't use


def test_chord_names_alone_or_a_sheet_with_no_key_print_as_before():
    plain = pdf_text(SONG, key=C_MAJOR, capo=None)
    assert pdf_text(SONG, key=C_MAJOR, capo=None, names="chords") == plain
    assert "numerals" not in plain and "display" not in plain
    nokey = "{title: X}\n{artist: A}\n[N.C.]words alone\n"
    assert pdf_text(nokey, key=None, capo=None, names="numerals") == pdf_text(nokey, key=None, capo=None)
    with pytest.raises(ValueError):
        pdf_text(SONG, key=C_MAJOR, capo=None, names="roman")
