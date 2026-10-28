"""The sheet viewer in text the browser draws larger than the page sets it, and nothing else larger: a minimum
font size (a browser's setting), or an app's text zoom (Android's WebView: the caracole app's pinch). The text grows
and so do its lines, but a length in em stays as the page set it: so the row a chord sits in, and the room a reading
takes over its character, are each a line of text in its own size (viewer.css), never an em length. Each chord stays
over its syllable, above its line and clear of the next; with Pinyin, above its reading, over its character; a row's
chords at one height.

Chromium's minimum font size stands in for the app's text zoom: both draw the text alone larger.
"""

from __future__ import annotations

from helpers.browser import in_chromium
from helpers.viewer_pages import viewer as open_viewer, written
from test_viewer_pinyin import LONG, assert_aligned, chords

LARGER = ["--blink-settings=minimumFontSize=40"]  # the lyrics' 18 px and the chords' 15 px drawn at 40 px
PHONE = {"width": 390, "height": 844, "mobile": True}
# Chords close together, which the viewer widens their columns for, and words with no chord between them.
SONG = """{title: Close Chords}
{artist: The Placeholders}
{key: G}
{comment: Verse}
[G]Tiny [D]test [Em]words [C]go here
Made [Em]up only for a [C]parser [G]and [D]more
[Cmaj7]A [G/B]b [Am7]c [D7sus4]d
"""

# What went wrong with the chords of the song's lines: one not over its syllable, one over its line, one running into
# the next on its row, a row's chords at several heights. And the size a chord is drawn at.
LAID_OUT = """(() => {
  const wrong = [];
  [...document.querySelectorAll('#sheet section.sec > p.l')].forEach((line, n) => {
    const rows = new Map();
    let before = null;
    for (const col of line.querySelectorAll(':scope > .s')) {
      const name = col.querySelector(':scope > .c').textContent;
      const c = col.querySelector(':scope > .c').getBoundingClientRect();
      const y = col.querySelector(':scope > .y').getBoundingClientRect();
      if (Math.abs(c.left - y.left) > 1) wrong.push(name + ' is not over its syllable');
      if (c.bottom > y.top + 1) wrong.push(name + ' is over its line by ' + (c.bottom - y.top).toFixed(1));
      if (before && Math.abs(before.top - c.top) < 2 && before.right > c.left + 0.5) wrong.push(before.name + ' runs into ' + name);
      before = {top: c.top, right: c.right, name: name};
      const row = Math.round(y.bottom);
      rows.set(row, (rows.get(row) || []).concat([c.top]));
    }
    for (const tops of rows.values()) {
      if (Math.max(...tops) - Math.min(...tops) > 1) wrong.push('line ' + n + ': chords at several heights');
    }
  });
  return {wrong: wrong, chord: parseFloat(getComputedStyle(document.querySelector('#sheet .c')).fontSize)};
})()"""


@in_chromium
def test_each_chord_stays_over_its_syllable_and_above_its_line_in_text_drawn_larger(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), **PHONE) as b:
        own = b.js(LAID_OUT)
    with open_viewer(tmp_path, written(tmp_path, SONG), **PHONE, args=LARGER) as b:
        larger = b.js(LAID_OUT)
    assert own["wrong"] == [] and own["chord"] < 20, own
    assert larger["chord"] == 40, larger  # the browser drew it larger
    assert larger["wrong"] == [], larger


@in_chromium
def test_with_pinyin_each_chord_stays_over_its_reading_over_its_character_in_text_drawn_larger(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE, args=LARGER) as b:
        off = chords(b)
    with open_viewer(tmp_path, written(tmp_path, LONG) + "#py=1", **PHONE, args=LARGER) as b:
        assert b.wait("document.querySelector('#sheet ruby.py') !== null")
        on = chords(b)
    assert_aligned(off, on)
