"""The line being sung, lit while the song scrolls by itself (viewer.js's lyrics clock, viewer.css ``.l.sung``).

A song whose timed lyrics meet its lines (the data's ``sung``, viewer/sung.py: tests/test_viewer_sung.py) lights the
line being sung while autoscroll is on: the clock starts once the count-in is over, a pause stops it with the line
still lit, the end puts it back to the start with none lit, and a tap on a line's words sets it at that line. A song
with no timed lyrics, or whose lyrics meet too few of its lines, lights nothing. Each test runs a Chromium of its own
on real time (helpers/viewer_pages.py's ``viewer``): the scroll and the clock move on each frame.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest

from helpers.browser import Browser, in_chromium
from helpers.viewer_pages import click_at, rest, spot, tap, tap_at, viewer, written
from test_viewer_numerals import contrast
from test_viewer_pinyin import ZH, ZH_LINES, assert_over_their_characters, chords, han, places
from test_viewer_scroll import look, start_now
from test_viewer_theme import hexrgb

# Eight sung lines in two sections, four each (synthetic words).
SONG = """{title: Sung Song}
{artist: Synthetic}
{key: G}
{start_of_verse: Verse}
[G]Morning comes over the [D]harbour
[Em]Paper boats drift on the [C]water
[G]Nobody counts the [D]hours
[Em]Lanterns are swaying [C]slowly
{end_of_verse}
{start_of_chorus: Chorus}
[C]Sing it back to me [G]softly
[D]Over the hills and [Em]home
[C]Every window is [G]open
[D]Carry the tune till [G]dawn
{end_of_chorus}
"""
LINES = ["Morning comes over the harbour", "Paper boats drift on the water", "Nobody counts the hours",
         "Lanterns are swaying slowly", "Sing it back to me softly", "Over the hills and home",
         "Every window is open", "Carry the tune till dawn"]
# Its timed lyrics, a line every 0.8 s from the start.
TIMED = [(0.8 * k, text) for k, text in enumerate(LINES)]
# Timed lyrics that meet two of its lines alone: too few to light any.
TOO_FEW = [(0.0, LINES[0]), (0.8, LINES[1]), (1.6, "Something else entirely here"), (2.4, "Nothing like the sheet"),
           (3.2, "A verse of another song")]
# test_viewer_pinyin's Chinese sheet, its lines with words timed in Traditional characters.
ZH_TIMED = [(0.8 * k, text) for k, text in enumerate(["這是一個合成的例子，ok", "沒有和弦的一行", "la la la", "長城和成長"])]

LIT = "[...document.querySelectorAll('#sheet section.sec > p.l')].findIndex((l) => l.classList.contains('sung'))"
# Every change of what is lit, from now on, with when (the page's clock): ``window.litLog``, the lines lit by index,
# as it is now first.
WATCH = """(() => {
  window.litLog = [];
  const lines = [...document.querySelectorAll('#sheet section.sec > p.l')];
  const note = () => {
    const lit = [...document.querySelectorAll('.sung')].map((l) => lines.indexOf(l));
    const last = litLog[litLog.length - 1];
    if (!last || last[1].join() !== lit.join()) litLog.push([performance.now(), lit]);
  };
  note();
  new MutationObserver(note).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class']});
  window.goAt = [];
  document.getElementById('go').addEventListener('click', () => goAt.push(performance.now()), true);
})()"""
# What the page's clock reads ``ms`` from now: an expression, settled then.
LATER = "new Promise((done) => setTimeout(() => done(EXPRESSION), MS))"


def later(b: Browser, expression: str, ms: int) -> object:
    """``expression``'s value ``ms`` milliseconds from now by the page's own clock."""
    return b.js(LATER.replace("EXPRESSION", expression).replace("MS", str(ms)))


def lit_log(b: Browser) -> list[list[int]]:
    """The lines lit, change by change, since ``WATCH``."""
    return [lit for _, lit in b.js("litLog")]


def words(n: int) -> str:
    """The words of SONG's line ``n`` (none under a chord), four lines a section."""
    return f"#sheet section.sec:nth-of-type({n // 4 + 1}) > p.l:nth-of-type({n % 4 + 1}) .w"


def chord_of(b: Browser, n: int) -> list[float]:
    """The middle of the first chord of line ``n``, where it is now."""
    return b.js(f"""(() => {{ const c = document.querySelectorAll('#sheet section.sec > p.l')[{n}].querySelector('.c');
      const r = c.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")


def data_of(url: str) -> dict:
    """The data of the page ``written`` wrote at ``url``."""
    html = Path(url2pathname(urlparse(url).path)).read_text(encoding="utf-8")
    return json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S).group(1))


@in_chromium
def test_the_line_being_sung_is_lit_from_the_count_in_on(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG, timed=TIMED)) as b:
        b.js(WATCH)
        before = b.js(LIT)
        b.click("#scroll")
        counting = [b.js(LIT)]
        assert b.wait("document.getElementById('tick').textContent === '2'")
        counting.append(b.js(LIT))
        b.click("#go")  # at once
        assert b.wait(f"{LIT} >= 1", 2)
        assert b.wait(f"{LIT} >= 3", 4)
        log = lit_log(b)
    assert before == -1 and counting == [-1, -1]  # nothing before ▶, nor while it counts in
    assert log[:5] == [[], [0], [1], [2], [3]]  # from the first line on as it runs, one line at a time


@in_chromium
def test_a_pause_stops_the_clock_and_a_tap_on_a_line_sets_it_there(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG, timed=TIMED)) as b:
        start_now(b)
        assert b.wait(f"{LIT} >= 0")
        tap(b, words(5))  # a finger on the page pauses it, and sets the clock at the line it is on
        paused = look(b)["go"]
        tapped = b.js(LIT)
        still = later(b, LIT, 1500)
        b.js(WATCH)
        tap_at(b, *chord_of(b, 2))  # a chord's card, and the clock left where it was
        assert b.wait("!document.getElementById('card').hidden")
        with_card = b.js(LIT)
        b.press("Escape")
        assert b.wait("document.getElementById('card').hidden")
        rest(b)  # the page still, once the card is away
        b.click("#go")
        b.click("#go")  # resumed at once
        assert b.wait(f"{LIT} === 7", 5)  # the last line, lit from then on
        resumed = lit_log(b)
        times = b.js("[goAt[goAt.length - 1], litLog.find((e) => e[1].join() === '6')[0]]")
        running = look(b)["go"]

        mark = b.js("litLog.length")
        click_at(b, *spot(b, words(2)))  # the mouse pauses nothing: the clock goes on from the line clicked
        clicked = b.js(f"[{LIT}, document.getElementById('go').getAttribute('aria-label')]")
        assert b.wait(f"litLog.length >= {mark} + 2", 3)
        on = lit_log(b)[mark:mark + 2]
    assert paused == "Resume" and tapped == 5 and still == 5 and with_card == 5
    assert resumed == [[5], [6], [7]] and running == "Pause"
    assert times[1] - times[0] >= 750  # line 6 came at its own time after line 5's, the clock run from there
    assert clicked == [2, "Pause"] and on == [[2], [3]]


@in_chromium
def test_ended_nothing_is_lit_and_the_clock_starts_over(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG, timed=TIMED)) as b:
        start_now(b)
        assert b.wait(f"{LIT} >= 2", 5)
        b.click("#pill-end")
        ended = b.js(f"[{LIT}, document.querySelectorAll('.sung').length]")
        b.js(WATCH)
        start_now(b)
        assert b.wait(f"{LIT} >= 1", 3)
        again = lit_log(b)
    assert ended == [-1, 0]
    assert again[:3] == [[], [0], [1]]


@in_chromium
@pytest.mark.parametrize("timed", [(), TOO_FEW], ids=["no timed lyrics", "too few lines met"])
def test_no_timed_lyrics_or_too_few_matches_light_nothing(tmp_path, timed):
    url = written(tmp_path, SONG, timed=timed)
    assert "sung" not in data_of(url)
    with viewer(tmp_path, url) as b:
        b.js(WATCH)
        start_now(b)
        running = later(b, f"[{LIT}, document.getElementById('go').getAttribute('aria-label')]", 2000)
        tap(b, words(5))
        tapped = b.js(f"[{LIT}, document.getElementById('go').getAttribute('aria-label')]")
        log = lit_log(b)
        error = b.js("document.documentElement.dataset.error || null")
    assert running == [-1, "Pause"] and tapped == [-1, "Resume"]
    assert log == [[]] and error is None  # nothing lit throughout, nothing broken


@in_chromium
def test_a_chinese_sheet_lights_its_lines_with_pinyin_shown(tmp_path):
    url = written(tmp_path, ZH, timed=ZH_TIMED)
    assert data_of(url)["sung"] == [[0, 0], [800, 2], [1600, 3], [2400, 4]]  # the line of chords alone skipped
    with viewer(tmp_path, url + "#py=1") as b:
        assert b.wait("document.querySelector('#sheet ruby.py') !== null")
        before = chords(b)
        b.js(WATCH)
        start_now(b)
        assert b.wait(f"{LIT} === 4", 6)
        b.click("#go")  # paused, the last line lit
        lit = b.js("document.querySelector('#sheet p.l.sung').textContent")
        on = chords(b)
        log = lit_log(b)
    assert log == [[], [0], [2], [3], [4]]
    assert han(lit) == han(ZH_LINES[4])  # 長城和成長's line, shown in the sheet's own characters
    # The lit line keeps its columns: each chord over its character, its reading between them, where it was.
    assert places(on) == places(before)
    assert [round(c["c"]["left"], 1) for c in on] == [round(c["c"]["left"], 1) for c in before]
    assert_over_their_characters(on)


LIT_COLOURS = """(() => { const l = document.querySelector('#sheet p.l.sung'), css = (e) => getComputedStyle(e);
  return {band: css(l).backgroundColor, shadow: css(l).boxShadow,
    words: [...l.querySelectorAll('.y, .w')].map((e) => css(e).color),
    chords: [...l.querySelectorAll('.c')].map((e) => css(e).color)}; })()"""


@in_chromium
@pytest.mark.parametrize("system,theme,band", [("dark", "light", "#fdf1e4"), ("light", "dark", "#2f2418")])
def test_the_lit_line_reads_at_4_5_to_1_in_both_themes(tmp_path, system, theme, band):
    with viewer(tmp_path, written(tmp_path, SONG, timed=TIMED) + f"#theme={theme}") as b:
        b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": system},
                                                       {"name": "prefers-reduced-motion", "value": "no-preference"}])
        start_now(b)
        assert b.wait(f"{LIT} >= 0")
        b.click("#go")
        seen = b.js(LIT_COLOURS)
    assert seen["band"] == hexrgb(band) and hexrgb(band) in seen["shadow"], seen
    assert seen["words"] and seen["chords"], seen
    for colour in seen["words"] + seen["chords"]:
        assert contrast(colour, seen["band"]) >= 4.5, (colour, seen["band"])


@in_chromium
def test_with_reduced_motion_the_light_moves_with_no_transition(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG, timed=TIMED), reduced=True) as b:
        b.js(WATCH)
        start_now(b)
        assert b.wait(f"{LIT} >= 1", 3)
        seen = b.js("getComputedStyle(document.querySelector('#sheet p.l.sung')).transitionDuration")
        log = lit_log(b)
    assert seen == "0s"
    assert log[:3] == [[], [0], [1]]
