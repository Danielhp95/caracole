"""The sheet's lines on the page (page.py ``_line_html``, viewer.css), in Chromium: a line of chords alone that writes
bars (``sheet.BAR``) is a row of bar cells (``span.barcell``), each with its chords and a dot (``.beat``) for each
beat after a chord's first (``sheet.bars``: four a bar, shared evenly); the row wraps between cells, never inside one.
A line of chords without bars is spaced evenly, as before."""

from __future__ import annotations

from helpers.browser import CHROMIUM_MARKS
from helpers.viewer_pages import tap_at, viewer as open_viewer, written

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

INTRO = (
    "{title: Greensleeves}\n{artist: Traditional}\n{key: Am}\n{comment: Intro}\n"
    "[Am] [C] [*|] [G] [Em] [*|] [Am] [*|] [E] [*|]\n"
    "{comment: Verse}\n[Am]Alas, my [C]love, you [G]do me [Em]wrong,\n[Am]To cast me [E]off dis[Am]courteously.\n"
    "{comment: Outro}\n[Am] [E] [Am]\n"
)

# Each bar cell of the intro's row: its chords' names and its count of beat dots, and its box's top, left and right.
CELLS = """[...document.querySelectorAll('#sheet .l.bars .barcell')].map((cell) => {
  const r = cell.getBoundingClientRect();
  return {chords: [...cell.querySelectorAll('.c')].map((c) => c.textContent), beats: cell.querySelectorAll('.beat').length,
          top: Math.round(r.top), left: r.left, right: r.right,
          tops: [...cell.querySelectorAll('.c')].map((c) => Math.round(c.getBoundingClientRect().top))};
})"""


def middle(b, selector: str) -> tuple[float, float]:
    """The centre of the first element ``selector`` finds."""
    return b.js(f"""(() => {{ const r = document.querySelector({selector!r}).getBoundingClientRect();
      return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")


def test_an_intro_written_in_bars_is_a_row_of_bar_cells_with_its_beats(tmp_path):
    url = written(tmp_path, INTRO)
    with open_viewer(tmp_path, url, width=390, height=844) as b:
        cells = b.js(CELLS)
        assert [(c["chords"], c["beats"]) for c in cells] == [
            (["Am", "C"], 2), (["G", "Em"], 2), (["Am"], 3), (["E"], 3)]
        assert len({c["top"] for c in cells}) == 1, cells  # one row, at 18 px in 358 px
        assert b.js("getComputedStyle(document.querySelector('#sheet .l.bars')).fontSize") == "18px"
        outro = "[...document.querySelectorAll('#sheet section.sec')].pop().querySelector('p.l')"
        assert b.js(f"{outro}.matches('.l.chords:not(.bars)')") is True
    with open_viewer(tmp_path, url, width=320, height=640) as b:
        assert b.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth") is True
        cells = b.js(CELLS)
        assert all(len(set(c["tops"])) == 1 for c in cells), cells  # a cell never wraps inside
        assert all(c["right"] <= 320 for c in cells), cells


def test_a_bar_cells_chords_transpose_and_open_their_card(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, INTRO), width=390, height=844) as b:
        first = "[...document.querySelectorAll('#sheet .l.bars .c')].slice(0, 4).map((c) => c.textContent)"
        sung = "[...document.querySelectorAll('#sheet section.sec')][1].querySelector('p.l')"
        sung_chords = f"[...{sung}.querySelectorAll('.c')].map((c) => c.textContent)"
        assert b.js(first) == b.js(sung_chords) == ["Am", "C", "G", "Em"]
        b.click("#t-up")
        assert b.wait(f"JSON.stringify({first}) !== JSON.stringify(['Am', 'C', 'G', 'Em'])")
        assert b.js(first) == b.js(sung_chords)
        tap_at(b, *middle(b, "#sheet .l.bars .c"))
        assert b.wait("!document.getElementById('card').hidden")
