"""caracole.viewer.sheet: the ChordPro caracole writes, read back for the sheet viewer."""

from __future__ import annotations

from pathlib import Path

from caracole.chordpro import to_chordpro
from caracole.viewer.sheet import Blank, ChordRow, Lyrics, Tab, Text, parse_sheet

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("utf-8")


def test_the_header_gives_title_artist_key_and_capo():
    sheet = parse_sheet(fixture("ug_sheet.cho"))
    assert (sheet.title, sheet.artist, sheet.key, sheet.capo, sheet.auto) == (
        "Synthetic Test Song", "The Placeholders", "G", 2, False)


def test_each_comment_opens_a_section_named_after_it():
    sheet = parse_sheet(fixture("ug_sheet.cho"))
    assert [s.label for s in sheet.sections] == ["Intro", "Verse 1", "Chorus", "Riff", "Outro"]
    assert [s.chorus for s in sheet.sections] == [False, False, True, False, False]


def test_chords_are_listed_once_in_the_order_they_first_appear():
    sheet = parse_sheet(fixture("ug_sheet.cho"))
    assert sheet.chords == ["G", "D", "Em", "C", "G/B", "Am", "F"]


def test_a_lyric_line_is_split_at_its_chords():
    verse = parse_sheet(fixture("ug_sheet.cho")).sections[1]
    assert verse.lines == [
        Lyrics([(0, "Tiny test "), (1, "words go here")]),
        Lyrics([(None, "Made "), (2, "up only for a "), (3, "parser")]),
    ]


def test_a_line_of_chords_alone_is_a_chord_row_with_its_marks():
    sheet = parse_sheet(fixture("ug_sheet.cho"))
    assert sheet.sections[0].lines == [ChordRow([0, 1, 2, 3, "x2"])]
    assert sheet.sections[4].lines == [ChordRow([0, 1, 3, "(x4)"])]


def test_a_mark_in_a_sung_line_stays_a_mark():
    sheet = parse_sheet("{title: T}\n[G]la la [*x2] [D]lo\n")
    assert sheet.sections[0].lines == [Lyrics([(0, "la la "), ("x2", " "), (1, "lo")])]


def test_tablature_is_kept_verbatim():
    riff = parse_sheet(fixture("ug_sheet.cho")).sections[3]
    assert riff.lines == [Tab(["e|-----0---0---|", "B|---1---1---1-|", "G|-2-----------|"])]


def test_blank_lines_separate_stanzas_but_never_start_or_end_a_section():
    text = "{title: T}\n{artist: A}\n{comment: Verse}\n\n[G]one\n\n[D]two\n\n{comment: Chorus}\nthree\n"
    sheet = parse_sheet(text)
    assert sheet.sections[0].lines == [Lyrics([(0, "one")]), Blank(), Lyrics([(1, "two")])]
    assert sheet.sections[1].lines == [Text("three")]


def test_lines_before_the_first_comment_make_an_unnamed_section():
    sheet = parse_sheet("{title: T}\n{artist: A}\nIntro words\n[G]Sing\n")
    assert [(s.label, s.lines) for s in sheet.sections] == [
        (None, [Text("Intro words"), Lyrics([(0, "Sing")])])]


def test_an_auto_sheet_is_marked_and_its_marker_is_no_section():
    text = to_chordpro("[ch]Am[/ch]\nla la", title="T", artist="A", auto=True)
    sheet = parse_sheet(text)
    assert sheet.auto
    assert [s.label for s in sheet.sections] == [None]


def test_escapes_chordpro_needed_are_undone_for_display():
    text = to_chordpro("Ends with \\\nWorth 100%{title}", title="Back\\slash", artist="A")
    sheet = parse_sheet(text)
    assert sheet.title == "Back\\slash"
    assert sheet.sections[0].lines == [Text("Ends with \\"), Text("Worth 100%(title)")]


def test_chorus_sections_are_told_by_their_name_in_several_languages():
    for label in ("Chorus", "Pre-Chorus 2", "Coro", "Estribillo", "Refrain", "副歌"):
        sheet = parse_sheet(f"{{title: T}}\n{{comment: {label}}}\nla\n")
        assert sheet.sections[0].chorus, label
    sheet = parse_sheet("{title: T}\n{start_of_chorus}\nla\n{end_of_chorus}\nlo\n")
    assert [(s.chorus, s.lines) for s in sheet.sections] == [(True, [Text("la")]), (False, [Text("lo")])]


def test_comment_lines_and_unknown_directives_are_skipped():
    sheet = parse_sheet("{title: T}\n# a note\n{tempo: 90}\n{new_page}\n[C]la\n")
    assert sheet.sections[0].lines == [Lyrics([(0, "la")])]


def test_a_chinese_sheet_keeps_its_text():
    text = to_chordpro(fixture("zh_sheet.txt"), title="斑马斑马", artist="宋冬野")
    sheet = parse_sheet(text)
    assert sheet.title == "斑马斑马"
    assert sheet.sections[0].lines[0] == Lyrics([(0, "这是一个"), (1, "合成的例子")])


def test_a_capo_that_is_no_number_is_none():
    assert parse_sheet("{title: T}\n{capo: two}\n").capo is None
    assert parse_sheet("{title: T}\n").capo is None
