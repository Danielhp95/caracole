"""The sheet viewer's preamble: what a tab says before its first section, folded out of the song's way.

UG tabs often open with the tabber's notes, a link and a chord legend (some 350 px on a phone, for
Wonderwall) before the first line you play. The viewer shows that text small and muted, two lines
of it, with More to read the rest: a <details>, so it opens without the script too.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import Browser, in_chromium
from helpers.chromium import Chromium

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
LEGEND = (FIXTURES / "legend_sheet.cho").read_text(encoding="utf-8")  # notes, a link, a legend, then the song
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # opens on its first section
HEAD = "{title: Short Song}\n{artist: The Placeholders}\n"


def sheet_of(html: str) -> str:
    found = re.search(r'<article[^>]*id="sheet"[^>]*>\n(.*?)</article>', html, re.S)
    assert found, "no sheet"
    return found.group(1)


def test_the_text_before_the_first_section_is_folded_after_two_lines():
    sheet = sheet_of(build_viewer(LEGEND))
    fold = re.match(r'<details class="pre">\n?<summary>(.*?)</summary>(.*?)</details>\n', sheet, re.S)
    assert fold, sheet[:300]
    summary, body = fold.groups()
    # the summary: the first two lines, to read at a glance, and More
    assert "This is a made-up note about the version" in summary
    assert "http://example.com/watch?v=placeholder&amp;amp;feature=related" in summary
    assert "and these are the chords" not in summary
    assert ">More<" in summary
    # inside: all of it, the legend's chords as any chord on the sheet
    assert "and these are the chords as they were played" in body and "Capo 2. fret" in body
    assert re.search(r'<b class="c" data-c="3"[^>]*>Cadd9</b> <i class="m">\(x32033\)</i>', body)
    assert "Dsus4/F#(2x0233)" in body
    # and the song, as before, after it
    assert sheet[fold.end():].startswith('<section class="sec">\n<h2 class="lbl">Intro</h2>')


def test_a_preamble_of_two_lines_shows_whole_with_nothing_to_open():
    sheet = sheet_of(build_viewer(HEAD + "A made-up note on this version\n\nCapo 2\n\n{comment: Verse}\n[G]Sung [D]words\n"))
    assert sheet.startswith('<div class="pre">\n<p class="l">A made-up note on this version</p>\n'
                            '<div class="gap"></div>\n<p class="l">Capo 2</p>\n</div>\n<section class="sec">')


VERSE = "\n{comment: Verse}\n[G]Sung words [D]here\n"


@pytest.mark.parametrize("cho", [
    UG_CHO,  # nothing before its first section
    HEAD + "A note\n[G]Sung words [D]here\n",  # no section at all: the whole song
    HEAD + "A note\n[G]Sung words [D]here\n\n{comment: Chorus}\n[C]More words\n",  # a verse before the first label
    HEAD + "[G] [D] [Em] [*x2]\n" + VERSE,  # the intro's chords, unlabelled
    HEAD + "A note\nand another\nand a third\n[G] [D] [Em] [*x2]\n" + VERSE,  # notes, then the intro's chords
    HEAD + "A note\nand another\nThe riff:\n{start_of_tab}\ne|--3--2--0--|\n{end_of_tab}\n" + VERSE,
], ids=["no-preamble", "no-section", "a-verse", "the-intro", "notes-then-the-intro", "notes-then-a-riff"])
def test_nothing_the_song_plays_is_folded(cho):
    sheet = sheet_of(build_viewer(cho))
    assert "<details" not in sheet and 'class="pre"' not in sheet


@pytest.mark.parametrize("legend", [
    "[Em7] [*(022033)]\n[G] [*(320033)]\n[Cadd9] [*(x32033)]\n",  # chords with their fingerings, as marks
    "[Em7] 022033\n[G] 320033\n[Cadd9] x32033\n",  # or as words
    "Em7 (022033)\nG (320033)\nCadd9 (x32033)\n",  # or as text
], ids=["marks", "words", "text"])
def test_a_chord_legend_alone_is_folded_too(legend):
    sheet = sheet_of(build_viewer(HEAD + legend + VERSE))
    assert sheet.startswith('<details class="pre">') and "x32033" in sheet[:sheet.index("</details>")]
    assert sheet[sheet.index("</details>"):].count("<section") == 1


def test_a_songbooks_song_folds_its_preamble_too():
    book = build_songbook("Campfire", [BookSong("Legend Song", "The Placeholders", cho=LEGEND, id="aaaa")])
    song = re.search(r'<article class="sheet" id="sheet-1"[^>]*>\n(.*?)</article>', book, re.S).group(1)
    assert song.startswith('<details class="pre">')


# --- in a real browser ---------------------------------------------------------------------------


def opened(browser: Chromium, html: str, tmp_path: Path, ready: str = "document.documentElement.dataset.ready === '1'"):
    page = tmp_path / "Library" / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")
    tab = browser.open(page.as_uri())
    tab.wait_for(ready)
    return tab


FOLD = """(() => {
  const sheet = document.getElementById("sheet");
  const pre = sheet.querySelector(".pre");
  const peek = pre.querySelector(".peek");
  const summary = pre.querySelector("summary");
  const legend = [...pre.querySelectorAll(".l")].find((l) => l.textContent === "Capo 2. fret");
  return {
    open: pre.open, height: pre.getBoundingClientRect().height, summary: summary.getBoundingClientRect().height,
    peek: peek.checkVisibility() ? peek.getBoundingClientRect().height : 0,
    lineHeight: parseFloat(getComputedStyle(peek).lineHeight), clamped: peek.scrollHeight > peek.clientHeight + 1,
    font: parseFloat(getComputedStyle(pre).fontSize), sheetFont: parseFloat(getComputedStyle(sheet).fontSize),
    colour: getComputedStyle(pre).color, textColour: getComputedStyle(sheet).color,
    legend: Boolean(legend && legend.checkVisibility()), label: summary.innerText.trim().split(/\\s+/).pop(),
    sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  };
})()"""


@in_chromium
@pytest.mark.parametrize("size", ["390,844", "1280,800"], ids=["phone", "desktop"])
def test_the_preamble_takes_two_small_muted_lines_until_more_opens_it(tmp_path, size):
    with Chromium(tmp_path / "profile", size=size) as browser:
        tab = opened(browser, build_viewer(LEGEND), tmp_path)
        folded = tab.eval(FOLD)
        tab.click("#sheet .pre summary")
        unfolded = tab.eval(FOLD)
        tab.click("#sheet .pre summary")
        again = tab.eval(FOLD)
    assert not folded["open"] and not folded["legend"], folded
    assert folded["clamped"] and folded["peek"] <= 2 * folded["lineHeight"] + 1, folded  # two lines, cut short
    assert folded["font"] < folded["sheetFont"] and folded["colour"] != folded["textColour"], folded
    assert 44 <= folded["summary"] and folded["height"] < 80, folded  # a thumb's target, and out of the way
    assert folded["label"] == "More" and not folded["sideways"], folded
    assert unfolded["open"] and unfolded["legend"] and unfolded["height"] > 200, unfolded
    assert unfolded["label"] == "Less" and not unfolded["peek"] and not unfolded["sideways"], unfolded
    assert again == folded


@in_chromium
def test_more_opens_the_preamble_without_the_script(tmp_path):
    html = re.sub(r"<script>.*?</script>\n", "", build_viewer(LEGEND), flags=re.S)
    with Chromium(tmp_path / "profile") as browser:
        tab = opened(browser, html, tmp_path, "document.readyState === 'complete'")
        folded = tab.eval(FOLD)
        tab.click("#sheet .pre summary")
        unfolded = tab.eval(FOLD)
    assert not folded["open"] and folded["clamped"] and folded["height"] < 80, folded
    assert unfolded["open"] and unfolded["legend"], unfolded


@in_chromium
def test_opening_the_preamble_measures_the_columns_again(tmp_path):
    # On a wide screen a short song reads in two columns; with forty lines of notes open, it no longer fits.
    notes = "".join(f"Note number {n} about this made-up version\n" for n in range(1, 41))
    cho = HEAD + notes + "\n{comment: Verse}\n[G]Tiny [D]words\n\n{comment: Chorus}\n[C]Sing it [G]out\n"
    with Chromium(tmp_path / "profile", size="1280,800") as browser:
        tab = opened(browser, build_viewer(cho), tmp_path)
        before = tab.eval("document.documentElement.dataset.columns")
        tab.click("#sheet .pre summary")
        tab.wait_for("document.documentElement.dataset.columns === '1'")
    assert before == "2"


@in_chromium
def test_the_keyboard_reaches_more_after_the_title_and_opens_it(tmp_path):
    page = tmp_path / "Library" / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer(LEGEND), encoding="utf-8")
    with Browser(tmp_path / "profile", width=1280, height=800) as browser:
        browser.open(page.as_uri())
        assert browser.wait("document.documentElement.dataset.ready === '1'")
        focused = []
        for _ in range(2):
            browser.press("Tab")
            focused.append(browser.js("document.activeElement.matches('.back') ? 'back'"
                                      " : document.activeElement.matches('.pre summary') ? 'more' : 'else'"))
        browser.press("Enter")
        opened_now = browser.js("document.querySelector('#sheet .pre').open")
    assert focused == ["back", "more"] and opened_now
