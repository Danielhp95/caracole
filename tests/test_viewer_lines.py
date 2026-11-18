"""The sheet's lines on the page (page.py ``_line_html``, viewer.css), in Chromium: a line of chords alone that writes
bars (``sheet.BAR``) is a row of bar cells (``span.barcell``), each with its chords and a dot (``.beat``) for each
beat after a chord's first (``sheet.bars``: four a bar, shared evenly); the row wraps between cells, never inside one.
A line of chords without bars is spaced evenly, as before. A word a chord falls inside ("dis[E]courteously") is one
group of its columns (``span.word``), which wraps whole, and keeps the readings' room with Pinyin on."""

from __future__ import annotations

import pytest

from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import CHROMIUM_MARKS
from helpers.viewer_pages import tap_at, viewer as open_viewer, written
from test_viewer_text_size import LAID_OUT

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


# The sung line's columns (``p.l .s, p.l .w``, in a ``span.word`` or not), each with its text (a ``.s``'s ``.y``'s),
# its box and whether it is a chord's; the line's box; and whether the page scrolls sideways.
COLUMNS = """(() => {
  const line = document.querySelector('#sheet section.sec > p.l');
  const box = (el) => { const r = el.getBoundingClientRect();
    return {left: r.left, right: r.right, bottom: r.bottom, height: r.height}; };
  return {line: box(line), sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          cols: [...line.querySelectorAll('.s, .w')].map((col) => Object.assign(box(col), {s: col.classList.contains('s'),
            text: col.classList.contains('s') ? col.querySelector('.y').textContent : col.textContent}))};
})()"""


def sung(tmp_path, line: str, **size) -> dict:
    """``COLUMNS`` of a sheet of the one sung ``line``, at 30 px, in a window of ``size``."""
    cho = "{title: Greensleeves}\n{artist: Traditional}\n{key: Am}\n{comment: Verse}\n" + line + "\n"
    with open_viewer(tmp_path, written(tmp_path, cho) + "#fs=30", **size) as b:
        assert b.wait("getComputedStyle(document.querySelector('#sheet')).fontSize === '30px'")
        return b.js(COLUMNS)


def test_a_chord_inside_a_word_never_parts_the_word_across_rows(tmp_path):
    seen = sung(tmp_path, "[Am]To cast me [E]off dis[E7]courteously", width=390, height=844)
    cols = seen["cols"]
    dis = next(c for c in cols if c["text"] == "dis")
    rest = next(c for c in cols if c["s"] and c["text"] == "courteously")
    assert abs(dis["bottom"] - rest["bottom"]) <= 1 and abs(dis["right"] - rest["left"]) <= 1, seen
    assert abs(dis["left"] - seen["line"]["left"]) <= 1, seen  # the word starts its row, whole
    assert seen["line"]["height"] >= 2 * dis["height"], seen  # the line wraps
    assert seen["sideways"] is False, seen

    seen = sung(tmp_path / "wo", "[Am]To cast me [E]off wo[G][D]rd", width=390, height=844)
    cols = seen["cols"]
    at = next(k for k, c in enumerate(cols) if c["text"] == "wo")
    word = cols[at:at + 3]  # "wo", G's column with no text, D's over "rd"
    assert word[1]["s"] and word[1]["text"] == "" and word[2]["s"] and word[2]["text"].startswith("rd"), seen
    assert max(c["bottom"] for c in word) - min(c["bottom"] for c in word) <= 1, seen
    assert all(abs(a["right"] - b["left"]) <= 1 for a, b in zip(word, word[1:])), seen
    assert seen["sideways"] is False, seen


def test_a_word_longer_than_the_line_wraps_inside_its_group_rather_than_widen_the_page(tmp_path):
    seen = sung(tmp_path, "[G]Supercalifragilistic[D]expialidocious", width=320, height=640)
    assert seen["sideways"] is False, seen


def test_chords_close_together_inside_a_word_never_run_into_each_other(tmp_path):
    cho = "{title: T}\n{artist: A}\n{key: C}\n{comment: Verse}\n[C]Sweet [Cmaj7]a[G/B]la[D7sus4]bama, [Am]home\n"
    with open_viewer(tmp_path, written(tmp_path, cho), width=390, height=844) as b:
        laid = b.js(LAID_OUT)  # fit() widens a column inside the group as anywhere: "a" for Cmaj7
        assert b.js("document.querySelectorAll('#sheet .word').length") == 1
    assert laid["wrong"] == [], laid


def test_with_pinyin_a_word_a_chord_falls_inside_keeps_the_readings_room(tmp_path):
    cho = "{title: 合成}\n{artist: 示例}\n{key: C}\n{comment: Verse}\n[C]你好 Ala[G]bama [Am]世界 dis[F]courteously\n"
    with open_viewer(tmp_path, written(tmp_path, cho) + "#py=1", width=390, height=844) as b:
        assert b.wait("document.querySelector('#sheet ruby.py') !== null")
        laid = b.js(LAID_OUT)
        assert b.js("document.querySelectorAll('#sheet .l.py .word').length") == 2
    assert laid["wrong"] == [], laid  # each chord over its syllable, a row's chords at one height


# The first column's text of each chord that fit() widened: whether it is marked as an extender, and its width.
EXT = """[...document.querySelectorAll('#sheet .s > .y')].map((y) => ({ext: y.classList.contains('ext'),
  widened: y.style.minWidth !== '', text: y.textContent, ruby: y.querySelector('ruby') !== null}))"""


def test_a_gap_fit_opens_inside_a_word_is_marked_an_extender_and_a_gap_between_words_is_not(tmp_path):
    cho = ("{title: T}\n{artist: A}\n{key: C}\n{comment: Verse}\n"
           "[Cmaj7sus4]a [Dmaj7sus4]b [Am]wo[G][D]rd\n")
    with open_viewer(tmp_path, written(tmp_path, cho), width=390, height=844) as b:
        ys = b.js(EXT)
        wo = next(k for k, y in enumerate(ys) if y["text"] == "wo")
        assert ys[wo + 1]["widened"] is True and ys[wo + 1]["ext"] is True, ys  # G's, before D in the same word
        assert ys[0]["widened"] is True and ys[0]["ext"] is False, ys  # "a": a widened column outside a word
        assert ys[wo]["ext"] is ys[wo]["widened"], ys  # "wo" too, when Am's column was widened for G
        b.click("#t-up")
        assert b.wait("document.querySelector('#sheet .s .c').textContent !== 'Cmaj7sus4'")
        again = b.js(EXT)
        wo = next(k for k, y in enumerate(again) if y["text"] == "wo")
        assert [k for k, y in enumerate(again) if y["ext"]] and again[wo + 1]["ext"] is True, again
        assert all(y["widened"] and wo <= k <= wo + 1 for k, y in enumerate(again) if y["ext"]), again
        b.click("#t-down")
        assert b.wait("document.querySelector('#sheet .s .c').textContent === 'Cmaj7sus4'")
        assert [y["ext"] for y in b.js(EXT)] == [y["ext"] for y in ys]  # fit() re-marks after each change


def test_with_pinyin_no_leader_is_drawn_under_a_readings_ruby(tmp_path):
    cho = "{title: 合成}\n{artist: 示例}\n{key: C}\n{comment: Verse}\n[C]你好 Al[Gmaj7sus4][Dmaj7sus4]a [Am]世界\n"
    with open_viewer(tmp_path, written(tmp_path, cho) + "#py=1", width=390, height=844) as b:
        assert b.wait("document.querySelector('#sheet ruby.py') !== null")
        leaders = b.js("""[...document.querySelectorAll('#sheet .y.ext')].map((y) =>
          [y.querySelector('ruby') !== null, getComputedStyle(y, '::after').borderBottomWidth])""")
        assert leaders, "a gap opened inside the word"
        assert all(width == "0px" for ruby, width in leaders), leaders  # none drawn, ext or not
        assert b.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth") is True


HARD_TIMES = ("{title: Hard Times}\n{artist: Stephen Foster}\n{key: D}\n{comment: Verse 1}\n"
              "[D]Let us pause in [G]life's pleasures and [D]count its many [A]tears,\n"
              "[D]While we [D]all sup sor[G]row with the [D]poor;\n")

# Each sung line of the first section: its columns grouped into rows by their bottoms (within 2 px), each row's top,
# bottom and first column's left; the line's left; its font size.
ROWS = """[...document.querySelectorAll('#sheet section.sec')[0].querySelectorAll(':scope > p.l')].map((line) => {
  const cols = [...line.querySelectorAll('.s, .w')].map((c) => c.getBoundingClientRect());
  const rows = [];
  for (const r of cols) {
    const row = rows.find((x) => Math.abs(x.bottom - r.bottom) <= 2);
    if (!row) rows.push({top: r.top, bottom: r.bottom, left: r.left});
    else { row.top = Math.min(row.top, r.top); row.left = Math.min(row.left, r.left); }
  }
  return {rows, left: line.getBoundingClientRect().left, fs: parseFloat(getComputedStyle(line).fontSize)};
})"""


def lines_stand_apart(lines) -> None:
    first, second = lines[:2]
    assert len(first["rows"]) >= 2, first  # it wraps at 390 px
    assert first["rows"][1]["top"] - first["rows"][0]["bottom"] <= 1, first  # a line's rows touch
    assert abs(second["rows"][0]["top"] - first["rows"][-1]["bottom"] - 0.4 * first["fs"]) <= 1, lines
    assert all(abs(r["left"] - first["left"]) <= 1 for r in first["rows"]), first  # no hanging indent


@pytest.mark.parametrize("where", ["sheet", "songbook"])
def test_a_wrapped_tail_starts_flush_left_closer_to_its_line_than_the_next_line_is(tmp_path, where):
    if where == "sheet":
        url = written(tmp_path, HARD_TIMES)
    else:
        html = build_songbook("Campfire", [BookSong("Hard Times", "Stephen Foster", cho=HARD_TIMES, id="aaaa")])
        path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        url = path.as_uri() + "#song-1"
    with open_viewer(tmp_path, url, width=390, height=844) as b:
        lines_stand_apart(b.js(ROWS))


def test_with_pinyin_too_a_lines_rows_touch_and_lines_stand_apart(tmp_path):
    from test_viewer_pinyin import LONG

    with open_viewer(tmp_path, written(tmp_path, LONG) + "#py=1", width=390, height=844) as b:
        assert b.wait("document.querySelector('#sheet ruby.py') !== null")
        lines_stand_apart(b.js(ROWS))


# The first sung line's chords' tops, its columns' bottoms, and what each extender draws.
TOPS = """(() => {
  const line = document.querySelector('#sheet section.sec > p.l');
  const bottoms = [...line.querySelectorAll('.s, .w')].map((c) => Math.round(c.getBoundingClientRect().bottom));
  return {chords: [...line.querySelectorAll('.c')].map((c) => Math.round(c.getBoundingClientRect().top)), bottoms,
          leaders: [...line.querySelectorAll('.y.ext')].map((y) => {
            const s = getComputedStyle(y, '::before');
            return {pos: s.position, border: s.borderBottomWidth, left: parseFloat(s.left), width: y.getBoundingClientRect().width,
                    h: y.getBoundingClientRect().height};
          })};
})()"""


def test_an_extender_takes_no_room_so_every_chord_of_the_row_stands_at_one_height(tmp_path):
    cho = "{title: T}\n{artist: A}\n{key: C}\n{comment: Verse}\n[Am]wo[G][D]rd\n"
    for fs in ("", "#fs=30"):
        with open_viewer(tmp_path / (fs or "base"), written(tmp_path / (fs or "base"), cho) + fs,
                         width=390, height=844) as b:
            seen = b.js(TOPS)
        assert max(seen["chords"]) - min(seen["chords"]) <= 1, seen  # G does not sink into the lyric row
        assert max(seen["bottoms"]) - min(seen["bottoms"]) <= 1, seen
        assert seen["leaders"] and all(x["pos"] == "absolute" and x["border"] == "1px" for x in seen["leaders"]), seen
        assert all(x["h"] > 10 for x in seen["leaders"]), seen  # each keeps its line's height, empty or not
        assert seen["leaders"][0]["left"] > 0  # from the end of "wo", not under it
