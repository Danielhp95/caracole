"""caracole.viewer.harptab: a harmonica tab laid out otherwise than rows of holes over their words: a line that
starts as a section's name but is sung, a line of holes that is no row's words, words written above their holes,
the tabber's words inside a line of holes.

The fixtures (tests/fixtures/harptabs/layout/) are tabs of the 146 a study read on 2026-10-28, made as
test_viewer_harptab.py's are: every line of holes and every section's name as the tabber wrote it (the words inside a
line of holes made up), every other line's letters made up (a vowel for a vowel, a consonant for a consonant, the
case, the spaces, the hyphens and the punctuation kept, so each word keeps its place and its syllables), addresses
example.com's, a harp's name and a repeat mark ("x2") kept. ``CHIPS`` is each one's harp chip, as its page shows it.
"""

from __future__ import annotations

from pathlib import Path

from caracole.viewer.harptab import Prose, Row, expand, parse

LAYOUT = Path(__file__).parent / "fixtures" / "harptabs" / "layout"
CHIPS = {"5370_19-dias-y-500-noches": "Diatonic", "12631_en-brazos-de-la-fiebre-with-lyric": "Diatonic",
         "16988_l-l-og-mere-l": "Diatonic", "29720_te-amar-a-massa-demais": None,
         "14346_william-tell-overture": "Diatonic"}


def text_of(stem: str) -> list[str]:
    """The fixture's lines as parse reads them: tabs and no-break spaces expanded, nothing after the last letter."""
    return [expand(line).rstrip() for line in (LAYOUT / f"{stem}.txt").read_text(encoding="utf-8").split("\n")]


def laid(stem: str):
    """A tab of tests/fixtures/harptabs/layout/, read with its page's harp chip."""
    return parse((LAYOUT / f"{stem}.txt").read_text(encoding="utf-8"), harp=CHIPS[stem])


# --- a section's name, or words sung; a line of holes, never a row's words -----------------------------------------


def test_a_line_sung_that_starts_as_a_sections_name_is_a_rows_words_beside_a_row():
    read = parse("4 5 6 6\nEnd of the road\n-4 -5 6\nBreak my heart\n")
    assert [r.lyric for r in read.rows()] == ["End of the road", "Break my heart"]
    assert [s.label for s in read.sections] == [None]


def test_a_sections_name_beside_a_row_is_a_section_still():
    # Each a heading the 146 tabs write right above or below a row
    for name in ("Chorus", "INTRO", "fade:", "(D harp):", "Synth 1:", "bar 12:", "Refr.:", "(Chorus)", "[V1]",
                 "2. Strophe:", "Harp: C", "A part:", "refrain :", "(Repetir 2x)", "Verse 2", "Harmonica solo",
                 "Repeat chorus x2"):
        read = parse(f"4 5 6\n{name}\n-4 -5 6\nla la la\n")
        assert read.rows()[0].lyric is None, name
        assert len(read.sections) == 2 and read.sections[1].label, name
    # away from a row, a line that starts as a section's name is one, as before
    assert parse("Break it down\n\n4 5 6\nla la la\n").sections[0].label == "Break it down"


def test_a_line_of_holes_under_a_row_is_never_its_words():
    # William Tell Overture's "do 3, slip to 6" between two rows: a line of holes too few to be a row
    read = laid("14346_william-tell-overture")
    row = next(r for r in read.rows() if r.line == 2)
    assert row.lyric is None
    assert any(isinstance(i, Prose) and i.text == "te 3, dbiz zi 6" for s in read.sections for i in s.items)
    # words that hold a number or two are words still
    assert parse("4 5 6 7\nI've got 99 problems now\n").rows()[0].lyric == "I've got 99 problems now"


# --- words written above their holes -------------------------------------------------------------------------------


def holes_of(row: Row) -> list[tuple[list[str], str]]:
    return [([g.label() for g in groups if g.holes], text) for groups, text in row.parts]


def test_19_dias_y_500_noches_writes_each_rows_words_above_it():
    read = laid("5370_19-dias-y-500-noches")
    lines = text_of("5370_19-dias-y-500-noches")
    rows = read.rows()
    assert all(r.above and r.lyric == lines[r.line - 1] for r in rows) and len(rows) == 74
    assert read.notes == []  # its first line is its first row's words, not the tabber's notes
    assert holes_of(rows[0]) == [(["−5"], "Xo "), (["−5"], "ruav"), (["5"], "tfi "), (["−4"], "ki"), (["4"], "pu")]


def test_a_tab_whose_words_sit_above_with_a_blank_line_under_each_row():
    read = laid("16988_l-l-og-mere-l")
    lines = text_of("16988_l-l-og-mere-l")
    assert len(read.rows()) == 12 and all(r.above and r.lyric == lines[r.line - 1] for r in read.rows())
    # "-55" over a word of two syllables, each on its own
    assert holes_of(read.rows()[0]) == [(["6"], "Ib, "), (["6"], "es "), (["−5"], "aq "), (["−5"], "xi"), (["5"], "wo "),
                                        (["5"], "ev.")]


def test_te_amar_writes_its_words_above_holes_written_together():
    read = laid("29720_te-amar-a-massa-demais")
    lines = text_of("29720_te-amar-a-massa-demais")
    rows = read.rows()
    assert rows[0].line == 0 and rows[0].lyric is None  # its intro, played alone
    assert all(r.above and r.lyric == lines[r.line - 1] for r in rows[1:]) and len(rows) == 31


def test_en_brazos_de_la_fiebre_writes_a_piece_of_a_word_above_each_row():
    read = laid("12631_en-brazos-de-la-fiebre-with-lyric")
    lines = text_of("12631_en-brazos-de-la-fiebre-with-lyric")
    rows = read.rows()
    assert len(rows) == 120 and all(r.lyric == lines[r.line - 1] for r in rows if r.lyric is not None)
    assert sum(r.lyric is not None for r in rows) >= 110
    assert (rows[0].lyric, rows[1].lyric) == ("Raw zog", "vjedap")


def test_words_under_their_rows_stay_under_them():
    # A title above the first row and words under each, in lines written one after another
    read = parse("A Title Here\n4 5 6 7\nla la la la\n5 6 7 8\nlo lo lo lo\n")
    assert [(r.lyric, r.above) for r in read.rows()] == [("la la la la", False), ("lo lo lo lo", False)]
    assert read.notes == ["A Title Here"]


def test_a_line_of_letters_above_each_row_is_no_words():
    # 8834's note lengths over its holes ("w = whole note", "q = quarter note"): no row's words
    read = parse(" w    q q  q  q\n-4 / -4 4 -3 -2\n\n h  q  q   q q q q\n-2 -1 -2 / -2 -1 -2 -1\n\n"
                 "  e  e e  e  h\n-4 -1 -4 -1 4\n")
    assert [r.lyric for r in read.rows()] == [None, None, None]
