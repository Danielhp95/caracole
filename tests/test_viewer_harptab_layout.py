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

from caracole.viewer.harptab import Prose, parse

LAYOUT = Path(__file__).parent / "fixtures" / "harptabs" / "layout"
CHIPS = {"14346_william-tell-overture": "Diatonic"}


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
