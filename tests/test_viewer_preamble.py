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
    assert "http://example.com/watch?v=placeholder&amp;feature=related" in summary
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
    HEAD + "{start_of_tab}\ne|--3--2--0--|\n{end_of_tab}\nA note after it\n" + VERSE,  # a riff first
], ids=["no-preamble", "no-section", "a-verse", "the-intro", "notes-then-the-intro", "a-riff-first"])
def test_nothing_the_song_plays_is_folded(cho):
    sheet = sheet_of(build_viewer(cho))
    assert "<details" not in sheet and 'class="pre"' not in sheet


def test_the_notes_before_a_riff_are_folded_and_the_riff_stays_where_it_was():
    # UG often opens on a tab, its first label inside it ("[Intro]"): the notes before it are the preamble.
    riff = "{start_of_tab}\n[Intro] (x2)\ne|-0---0---|\n{end_of_tab}\n[G]Sung words\n"
    sheet = sheet_of(build_viewer(HEAD + "* = play softer\n** = hard strums\nand a third note\n\n" + riff + VERSE))
    fold, rest = sheet.split("</details>\n", 1)
    assert fold.startswith('<details class="pre">') and "and a third note" in fold and "e|-0" not in fold
    assert rest.startswith('<section class="sec">\n<pre class="tab">[Intro] (x2)\ne|-0---0---|</pre>\n'
                           '<p class="l"><span class="s"><b class="c" data-c="0"')
    assert rest.count("<section") == 2  # the riff's, then the verse


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
    named: summary.querySelector(".named").checkVisibility(),
    sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  };
})()"""


@in_chromium
@pytest.mark.parametrize("size", ["390,844", "1600,800"], ids=["phone", "desktop"])  # beside the rail of necks
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
    assert folded["label"] == "More" and not folded["named"] and not folded["sideways"], folded
    assert unfolded["open"] and unfolded["legend"] and unfolded["height"] > 200, unfolded
    assert unfolded["label"] == "Less" and not unfolded["peek"] and not unfolded["sideways"], unfolded
    assert unfolded["named"], unfolded  # what the open text is, beside Less
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
    with Chromium(tmp_path / "profile", size="1600,800") as browser:  # two columns fit beside the rail of necks
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
        for _ in range(3 + 1 + 2 + 6):
            browser.press("Tab")
            focused.append(browser.js("document.activeElement.matches('.back') ? 'back'"
                                      " : document.activeElement.matches('.artist a') ? 'artist'"
                                      " : document.activeElement.matches('.pre summary') ? 'more'"
                                      " : document.activeElement.closest('#necks') ? 'rail' : 'else'"))
        browser.press("Enter")
        opened_now = browser.js("document.querySelector('#sheet .pre').open")
    # The title's own: ‹ Library and the artist's name. From 1200 px the rail of necks comes between, on the left: its
    # Hide, the key's neck's Scale and Pentatonic, then one stop for each of the song's six chords.
    assert focused == ["back", "artist", *["rail"] * (1 + 2 + 6), "more"] and opened_now


# Printed: which of the notes' lines a reader sees, and whether the fold's own parts show.
PRINTED = """(() => {
  const pre = document.querySelector(".sheet:not([hidden]) .pre, section.song:not([hidden]) .pre");
  const shown = (el) => Boolean(el && el.checkVisibility());
  const line = (text) => [...pre.querySelectorAll(".l")].find((l) => l.textContent.includes(text));
  return {
    lines: ["This is a made-up note", "Capo 2. fret", "(x32033)", "Dsus4/F#(2x0233)"].map((t) => shown(line(t))),
    peek: shown(pre.querySelector(".peek")), more: shown(pre.querySelector(".more")), open: pre.open,
  };
})()"""


def print_preview(tmp_path: Path, html: str, fragment: str = "") -> dict:
    page = tmp_path / "Library" / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")
    with Browser(tmp_path / "profile", width=1280, height=800) as browser:
        browser.open(page.as_uri() + fragment)
        assert browser.wait("document.readyState === 'complete'")
        browser.send("Emulation.setEmulatedMedia", media="print")
        return browser.js(PRINTED)


@in_chromium
@pytest.mark.parametrize("page", ["sheet", "sheet-without-script", "songbook"])
def test_printed_the_notes_print_whole(tmp_path, page):
    # Paper has no More to press: the chord legend and the rest of the notes print, the peek doesn't.
    if page == "songbook":
        html = build_songbook("Campfire", [BookSong("Legend Song", "The Placeholders", cho=LEGEND, id="aaaa")])
        fragment = "#song-1"
    else:
        html = build_viewer(LEGEND)
        if page == "sheet-without-script":
            html = re.sub(r"<script>.*?</script>\n", "", html, flags=re.S)
        fragment = ""
    seen = print_preview(tmp_path, html, fragment)
    assert seen["lines"] == [True, True, True, True] and not seen["peek"] and not seen["more"], seen
    assert not seen["open"], seen  # on the screen, still folded


@in_chromium
def test_where_the_stylesheet_cant_open_the_fold_the_script_opens_it_to_print(tmp_path):
    # A browser without ::details-content: the script opens the notes for the printout, then folds them again.
    page = tmp_path / "Library" / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer(LEGEND), encoding="utf-8")
    with Browser(tmp_path / "profile", width=390, height=844) as browser:
        browser.send("Page.addScriptToEvaluateOnNewDocument",
                     source="CSS.supports = (s) => !String(s).includes('details-content');")
        browser.open(page.as_uri())
        assert browser.wait("document.documentElement.dataset.ready === '1'")
        fold = "document.querySelector('#sheet .pre').open"
        before = browser.js(fold)
        printing = browser.js(f"(() => {{ dispatchEvent(new Event('beforeprint')); return {fold}; }})()")
        after = browser.js(f"(() => {{ dispatchEvent(new Event('afterprint')); return {fold}; }})()")
        browser.click("#sheet .pre summary")  # one you opened yourself stays open
        browser.js("dispatchEvent(new Event('beforeprint')); dispatchEvent(new Event('afterprint'))")
        kept = browser.js(fold)
    assert (before, printing, after, kept) == (False, True, False, True)


@in_chromium
def test_the_open_legend_reads_in_one_size(tmp_path):
    # "Em7 (022033)", a line of chords, and "Dsus4   (xx0233)", a line of text: the same small size.
    with Chromium(tmp_path / "profile") as browser:
        tab = opened(browser, build_viewer(LEGEND), tmp_path)
        tab.click("#sheet .pre summary")
        sizes = tab.eval("""(() => {
          const pre = document.querySelector("#sheet .pre");
          const size = (el) => parseFloat(getComputedStyle(el).fontSize);
          const text = [...pre.querySelectorAll(".l")].find((l) => l.textContent.startsWith("Dsus4 "));
          const line = pre.querySelector(".l.chords");
          return {text: size(text), chord: size(line.querySelector(".c")), mark: size(line.querySelector(".m")),
                  pre: size(pre)};
        })()""")
    assert sizes["text"] == sizes["chord"] == sizes["mark"] == sizes["pre"], sizes
