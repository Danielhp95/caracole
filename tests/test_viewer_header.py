"""The song's header: the title block's ‹ (viewer.css `.back`), a back arrow alone, its words in aria-label and title, a
thumb's target; and the song's facts on three lines, Tuning, Capo and Key (page.py ``facts_html``, ``dl.facts``), as
viewer.js draws them again for the song as it is played (``drawFacts``): the capo set, the transposition, the
instrument's strings, no Tuning or Capo line on one with no strings or no capo, and an instrument's own line."""

from __future__ import annotations

import json
import re
from pathlib import Path

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook
from caracole.viewer.harp import header_line
from caracole.viewer.harptab_page import build_harmonica_viewer
from caracole.viewer.theory import Key, parse_chord

from helpers.browser import in_chromium
from helpers.viewer_pages import viewer as open_viewer, written
from test_viewer_instruments_page import choose

UG_CHO = (Path(__file__).parent / "fixtures" / "chordpro" / "ug_sheet.cho").read_text(encoding="utf-8")  # G, capo 2
# The facts as the page shows them: each line's name and its value's text.
ROWS = "[...document.querySelectorAll('#facts .fact')].map((r) => [r.dataset.fact, r.querySelector('dd').textContent])"
SAYS = "document.querySelector('#key-now .d').textContent"  # what the bar says changed, under its key


def test_the_title_block_opens_with_a_back_arrow_alone():
    html = build_viewer("{title: T}\n[Am]la la\n")
    assert '<a class="back" href="../../index.html" aria-label="Library" title="Library">‹</a>' in html
    harp = build_harmonica_viewer("4 5 6\n", title="T", tab_file="harmonica-1.txt", back="sheet.html")
    assert '<a class="back" href="sheet.html" data-sheet aria-label="Chord sheet" title="Chord sheet">‹</a>' in harp
    assert ">‹ Library</a>" not in html and ">‹ Chord sheet</a>" not in harp


@in_chromium
def test_the_back_arrow_is_48_px(tmp_path):
    url = written(tmp_path, "{title: T}\n[Am]la la\n")
    for width in (320, 390):
        with open_viewer(tmp_path, url, width=width) as b:
            box = b.js("(() => { const r = document.querySelector('.head .back').getBoundingClientRect();"
                       " return [r.width, r.height, r.left]; })()")
            assert box[0] == 48 and box[1] == 48 and box[2] >= 0, (width, box)


# --- the song's facts: Tuning, Capo and Key (page.py facts_html) ------------------------------------------------------

TUNED = ("{title: Tuned}\n{artist: The Placeholders}\n{key: Dm}\nTuning: Drop D\n\n"
         "{comment: Verse}\n[Dm]Words to sing\n{comment: Chorus}\n[F]More words\n")


def _data(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S).group(1))


def test_the_facts_are_tuning_capo_and_key():
    from caracole.viewer.page import GUITAR_STRINGS, facts_html

    assert GUITAR_STRINGS == "E A D G B E"
    assert facts_html(Key(9, "aeolian"), "from the tab", 0, None, chords=True) == (
        '<dl class="facts" id="facts">\n<div class="fact" data-fact="tuning"><dt>Tuning</dt><dd>E A D G B E</dd></div>\n'
        '<div class="fact" data-fact="capo"><dt>Capo</dt><dd>none</dd></div>\n<div class="fact" data-fact="key"><dt>Key'
        '</dt><dd><b>Am</b> · <span class="from">from the tab</span></dd></div>\n</dl>\n')
    # where the key came from unknown: the key alone; a value escaped
    plain = facts_html(Key(9, "aeolian"), None, 0, 'Open <G> & "low"', chords=True)
    assert '<dd>Open &lt;G&gt; &amp; &quot;low&quot;</dd>' in plain and "<dd><b>Am</b></dd>" in plain


def test_with_a_capo_the_key_says_the_shapes_and_the_sound():
    from caracole.viewer.page import facts_html

    html = facts_html(Key(4, "aeolian"), "from the tab", 2, None, chords=True)
    assert '<div class="fact" data-fact="capo"><dt>Capo</dt><dd>2</dd></div>' in html
    assert ('<div class="fact" data-fact="key"><dt>Key</dt>'
            '<dd><b>Em</b> shapes · sounds <b>F#m</b> · <span class="from">key from the tab</span></dd></div>') in html
    assert "Key <b>" not in html and "capo <b>" not in html  # "Key Em" never alone; the Capo row says the capo


def test_a_tuning_the_sheet_names_is_its_tuning_line():
    html = build_viewer(TUNED)
    assert '<div class="fact" data-fact="tuning"><dt>Tuning</dt><dd>Drop D</dd></div>' in html
    assert _data(html)["tuningName"] == "Drop D"
    plain = build_viewer(TUNED.replace("Tuning: Drop D\n\n", ""))
    assert "tuningName" not in _data(plain) and "<dd>E A D G B E</dd>" in plain
    assert '<dl class="facts" id="facts">' in html and '<p class="facts"' not in html


TAB_ALONE = "{title: T}\n{artist: A}\n{capo: 2}\n{start_of_tab}\ne|--0--2--3--|\nB|--1--3--3--|\n{end_of_tab}\n"


def test_no_key_no_key_line_and_no_chords_no_facts_but_a_capo():
    from caracole.viewer.page import facts_html

    html = facts_html(None, None, 3, None, chords=True)
    assert re.findall(r'data-fact="(\w+)"', html) == ["tuning", "capo"] and "<dd>3</dd>" in html
    # A sheet with no chords (a tab alone) says its capo as the PDF does ("Capo 2"), and nothing else.
    assert facts_html(Key(0, "ionian"), "from the sheet", 2, "Drop D", chords=False) == (
        '<dl class="facts" id="facts">\n<div class="fact" data-fact="capo"><dt>Capo</dt><dd>2</dd></div>\n</dl>\n')
    assert facts_html(None, None, 5, None, chords=False, suffix="-3").startswith('<dl class="facts" id="facts-3">\n')
    assert facts_html(None, None, 0, None, chords=False, suffix="-3") == ""
    assert 'id="facts"' not in build_viewer("{title: T}\n{artist: A}\nOnly words\n")
    tab = build_viewer(TAB_ALONE)
    assert '<dl class="facts" id="facts">\n<div class="fact" data-fact="capo"><dt>Capo</dt><dd>2</dd></div>\n</dl>\n' in tab
    assert '<dd>3</dd>' in build_viewer("{title: T}\n{artist: A}\n{capo: 3}\nOnly words\n")


def test_a_songbook_song_has_the_three_lines():
    from caracole.viewer.book import BookSong, build_songbook

    html = build_songbook("Campfire", [BookSong("Minor Song", "Placeholders", cho="{title: Minor Song}\n[Am]la [E]la\n",
                                                key="Am", key_source="tab"),
                                       BookSong("Tuned", "The Placeholders", cho=TUNED, id="b")])
    song = re.search(r'<section class="song" id="song-2".*?</header>', html, re.S).group(0)
    assert ('<dl class="facts" id="facts-2">\n<div class="fact" data-fact="tuning"><dt>Tuning</dt><dd>Drop D</dd></div>\n'
            '<div class="fact" data-fact="capo"><dt>Capo</dt><dd>none</dd></div>\n<div class="fact" data-fact="key">'
            '<dt>Key</dt><dd><b>Dm</b> · <span class="from">from the sheet</span></dd></div>\n</dl>\n</header>') in song
    assert '<dl class="facts" id="facts-1">' in html and '<p class="facts"' not in html


# --- the facts as the song is played (viewer.js drawFacts) ----------------------------------------------------------


def _page(tmp_path: Path, html: str, name: str = "Title") -> str:
    """``html`` written as Artist/<name>/sheet.html under ``tmp_path``; its address."""
    page = tmp_path / "Artist" / name / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")
    return page.as_uri()


@in_chromium
def test_the_facts_follow_the_capo_and_the_transposition(tmp_path):
    html = build_viewer(UG_CHO, key="G", key_source="tab")  # G shapes, capo 2: the song sounds in A
    up = _data(html)["keyNames"][_data(html)["key"]["mode"]][10]  # A up one, as the page names it
    with open_viewer(tmp_path, _page(tmp_path, html)) as b:
        first = b.js(ROWS)
        b.click("#more")
        b.click("#capo-down")
        b.click("#capo-down")
        off = [b.js(ROWS), b.js(SAYS)]
        b.click("#up")
        moved = [b.js(ROWS), b.js(SAYS)]
        bold = b.js("document.querySelector('#facts [data-fact=key] dd b').textContent")
    assert first == [["tuning", "E A D G B E"], ["capo", "2"], ["key", "G shapes · sounds A · key from the tab"]]
    # No capo: the key the song sounds in, alone, and the Capo line says none; the chords you see moved two frets up
    # (A for G), which the Key line says as the bar does.
    assert off == [[["tuning", "E A D G B E"], ["capo", "none"], ["key", "A (+2) · from the tab"]], "no capo · +2"]
    # Moved: the key it sounds in now, how far the chords moved after it.
    assert moved == [[["tuning", "E A D G B E"], ["capo", "none"], ["key", f"{up} (+3) · from the tab"]],
                     "no capo · +3"]
    assert bold == up


@in_chromium
def test_a_tab_alone_keeps_its_capo_line_as_written(tmp_path):
    # No chords: nothing to transpose or to play on another instrument (the piano chosen on another page), so the
    # page's script leaves the facts page.py wrote, the capo the tab is played at.
    piano = "localStorage.setItem('caracole-viewer-instrument', 'piano')"
    with open_viewer(tmp_path, _page(tmp_path, build_viewer(TAB_ALONE)), before=[piano]) as b:
        rows = b.js(ROWS)
    assert rows == [["capo", "2"]]


def _harps(b, key: Key) -> str:
    """The harps for the song as the page names its chords, as harp.py's header line names them, without its label:
    the facts' Harmonica row says that."""
    names = b.js("[...document.querySelectorAll('#sheet .c')].map((c) => c.textContent)")
    return header_line(key, [parse_chord(n) for n in names]).removeprefix("Harmonica: ")


@in_chromium
def test_another_instrument_has_its_own_strings_and_one_with_none_has_no_tuning_or_capo(tmp_path):
    html = build_viewer(UG_CHO, key="G", key_source="tab")
    with open_viewer(tmp_path, _page(tmp_path, html)) as b:
        choose(b, "Ukulele")
        uke = b.js(ROWS)
        choose(b, "Baritone ukulele")
        baritone = b.js(ROWS)
        choose(b, "Piano")
        piano = b.js(ROWS)
        choose(b, "Harmonica")
        harmonica = [b.js(ROWS), b.js("document.querySelector('#facts [data-fact=inst] dt').textContent"),
                     _harps(b, Key(9, "ionian"))]
        choose(b, "Flute")
        flute = b.js(ROWS)
        choose(b, "Guitar")
        guitar = b.js(ROWS)
    key = ["key", "G shapes · sounds A · key from the tab"]
    assert uke == [["tuning", "G C E A"], ["capo", "2"], key]  # a ukulele keeps the capo
    assert baritone == [["tuning", "D G B E"], ["capo", "2"], key]
    # The piano takes no capo and has no strings: the key the song sounds in, the capo folded in.
    assert piano == [["key", "A · from the tab"]]
    # The harmonica, no strings and no capo either, has its own line, under the key: the harps for the song.
    assert harmonica[0] == [["key", "A · from the tab"], ["inst", harmonica[2]]] and harmonica[1] == "Harmonica"
    assert harmonica[2].startswith("A harp (1st position) · D harp (2nd)")
    assert flute == [["key", "A · from the tab"]]  # the winds have no line of their own
    assert guitar == [["tuning", "E A D G B E"], ["capo", "2"], key]


@in_chromium
def test_a_tuning_the_sheet_names_stays_the_guitars_and_goes_on_a_ukulele(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, TUNED)) as b:
        first = b.js(ROWS)
        choose(b, "Ukulele")
        uke = b.js(ROWS)
        choose(b, "Guitar")
        guitar = b.js(ROWS)
    assert first == guitar == [["tuning", "Drop D"], ["capo", "none"], ["key", "Dm · from the sheet"]]
    assert uke[0] == ["tuning", "G C E A"]  # the sheet's tuning is the guitar's


# A Chinese sheet (test_viewer_pinyin.py's), with a capo, its title and its artist 120 characters long.
LONG_ZH = ("{title: " + "长城和成长" * 24 + "}\n{artist: " + "示例乐队" * 30 + "}\n{key: C}\n{capo: 2}\n"
           "{comment: Verse}\n[C]这是一[G]个合成的[Am]例子，ok\n[F]  [G]\n没有和弦的一行\nla [C]la la\n\n"
           "{comment: Chorus}\n[F]长城和[C]成长\n")
FIT = """(() => {
  const h1 = document.querySelector('.head h1'), lines = document.createRange();
  lines.selectNodeContents(h1);
  return { scroll: document.documentElement.scrollWidth, width: innerWidth,
    dds: [...document.querySelectorAll('#facts dd')].map((d) => [d.getBoundingClientRect().left,
      d.getBoundingClientRect().right]),
    lines: new Set([...lines.getClientRects()].map((r) => Math.round(r.top))).size,
    h1: h1.textContent, artist: document.querySelector('.head .artist').textContent.trim() };
})()"""


@in_chromium
def test_a_long_name_and_a_chinese_sheet_fit_a_320_px_phone(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG_ZH) + "#py=1&trad=1", width=320, height=640) as b:
        rows = b.js(ROWS)
        seen = b.js(FIT)
    assert rows == [["tuning", "E A D G B E"], ["capo", "2"], ["key", "C shapes · sounds D · key from the sheet"]]
    assert seen["scroll"] <= seen["width"] == 320, seen  # no sideways scroll
    assert seen["dds"] and all(0 <= left and right <= 320 for left, right in seen["dds"]), seen["dds"]
    assert seen["lines"] > 1  # the title wrapped
    assert seen["h1"] == "長城和成長" * 24 and seen["artist"] == "示例樂隊" * 30  # in the characters chosen


@in_chromium
def test_a_songbook_song_draws_its_facts_too(tmp_path):
    minor = "{title: Minor Song}\n{artist: Placeholders}\n[Am]la [F]la [C]la [G]la\n"
    html = build_songbook("Campfire", [BookSong("Synthetic Test Song", "The Placeholders", cho=UG_CHO, id="aaaa"),
                                       BookSong("Minor Song", "Placeholders", cho=minor, key="Am", key_source="tab",
                                                transpose=2, id="bbbb")])
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-2") as b:
        second = b.js(ROWS)
    with open_viewer(tmp_path, path.as_uri() + "#song-1") as b:
        first = b.js(ROWS)
        b.click("#more")
        b.click("#capo-down")
        lower = b.js(ROWS)
    data = json.loads(re.search(r'<script type="application/json" id="data-1">(.*?)</script>', html, re.S).group(1))
    shapes = data["keyNames"][data["key"]["mode"]][8]  # G's shapes a fret lower, as the page names them
    # Its [transpose]: two up, as the bar says it.
    assert second == [["tuning", "E A D G B E"], ["capo", "none"], ["key", "Bm (+2) · from the tab"]]
    assert first == [["tuning", "E A D G B E"], ["capo", "2"], ["key", "G shapes · sounds A · key from the sheet"]]
    # A fret lower, the chords you see a semitone up from the sheet's G, as the bar's "capo 1 · +1": the shapes moved,
    # the song still sounds in A
    assert lower == [["tuning", "E A D G B E"], ["capo", "1"],
                     ["key", f"{shapes} shapes (+1) · sounds A · key from the sheet"]]
