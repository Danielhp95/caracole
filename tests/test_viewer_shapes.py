"""The sheet viewer's chord shapes: the strip of every chord's shape above the song, the chord's card,
and the tab's own fingerings first.

The strip's diagrams are large enough to read at a glance; the fingers, too small to read there,
are on the chord's card. A tab often says how it plays its chords, in a legend before the song
("Cadd9 (x32033)"), and a ChordPro sheet may say it with {define}: that shape is the one the song
was charted with, so it comes before chords-db's, in the strip and on the card, wherever the chord
shown is the very chord the sheet gave it for.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook
from caracole.viewer.voicings import load_voicings

from helpers.browser import in_chromium
from helpers.chromium import Chromium

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # G, D, Em, C, G/B, Am, F; no legend
LEGEND = (FIXTURES / "legend_sheet.cho").read_text(encoding="utf-8")  # a Wonderwall-like legend, made-up words
CADD9 = 3  # its index among the legend sheet's chords: Em7, G, A7sus4, Cadd9, Dsus4, Dsus4/F#
CAPO = "With the capo on fret 2."  # the legend sheet's capo, which every shape of it is played with
TABS = "As the tab plays it. " + CAPO
NONE = "000000"  # a tab says nothing of the fingers
DB = load_voicings()


def data_of(html: str, block: str = "song") -> dict:
    found = re.search(rf'<script type="application/json" id="{block}">(.*?)</script>', html, re.S)
    assert found, "no song data"
    return json.loads(found.group(1))


# --- what the page holds -------------------------------------------------------------------------


def test_the_tabs_legend_gives_its_chords_shapes_first():
    shapes = data_of(build_viewer(LEGEND))["shapes"]
    # by root, suffix and bass, as the chord is shown
    assert set(shapes) == {"4,m7,", "7,,", "2,sus4,", "9,7sus4,", "0,add9,", "2,sus4,6"}
    assert shapes["0,add9,"] == {"mine": 1, "list": [["x32033", NONE, 1, []], *DB["add9"][0]]}
    assert shapes["7,,"] == {"mine": 1, "list": [["320033", NONE, 1, []], *DB[""][7]]}  # G, as the tab plays it
    # "Dsus4/F#(2x0233)", a line of text; then chords-db's Dsus4, to play with F# in the bass
    assert shapes["2,sus4,6"] == {"mine": 1, "list": [["2x0233", NONE, 1, []], *DB["sus4"][2]]}


def test_a_shape_chords_db_has_too_is_shown_once_with_its_fingers():
    dsus4 = data_of(build_viewer(LEGEND))["shapes"]["2,sus4,"]  # "Dsus4   (xx0233)": chords-db's first too
    assert dsus4 == {"mine": 1, "list": DB["sus4"][2]}
    assert dsus4["list"][0] == ["xx0233", "000123", 1, []]


def test_a_fingering_that_doesnt_play_its_chord_is_left_out():
    shapes = data_of(build_viewer(LEGEND.replace("[G] [*(320033)]", "[G] [*(x32033)]")))["shapes"]
    assert "7,," not in shapes  # a C in a G chord: a slip, or not a fingering at all


def test_a_sheets_define_comes_first_with_its_fingers():
    cho = ("{title: Defined}\n{define: Cadd9 base-fret 1 frets x 3 2 0 3 3 fingers 0 2 1 0 3 4}\n"
           "Cadd9 (x32033)\nCadd9 (x32030)\n\n{comment: Verse}\n[Cadd9]Made up [G]words\n")
    shapes = data_of(build_viewer(cho))["shapes"]
    # the define, then the legend's other shape, chords-db's x32030 with its fingers, and chords-db's others
    assert shapes == {"0,add9,": {"mine": 2, "list": [["x32033", "021034", 1, []], *DB["add9"][0]]}}


def test_a_sheet_without_a_legend_has_chords_dbs_shapes_alone():
    assert data_of(build_viewer(UG_CHO))["shapes"] == {}  # its repeat marks ("x2", "(x4)") are no fingerings


def test_a_songbooks_song_keeps_its_tabs_shapes():
    book = build_songbook("Campfire", [BookSong("Legend Song", "The Placeholders", cho=LEGEND, id="aaaa")])
    assert data_of(book, "data-1")["shapes"]["0,add9,"]["mine"] == 1


# --- in a real browser ---------------------------------------------------------------------------


def opened(browser: Chromium, html: str, tmp_path: Path, fragment: str = ""):
    page = tmp_path / "Library" / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")
    tab = browser.open(page.as_uri() + fragment)
    tab.wait_for("document.documentElement.dataset.ready === '1'")
    return tab


STRIP = """(() => {
  const strip = document.getElementById("strip");
  const buttons = [...strip.querySelectorAll("button")];
  return {
    names: buttons.map((b) => b.lastChild.textContent),
    widths: [...strip.querySelectorAll("svg")].map((s) => Math.round(s.getBoundingClientRect().width)),
    heights: buttons.map((b) => Math.round(b.getBoundingClientRect().height)),
    fingers: strip.querySelectorAll(".dg-finger").length,
    sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  };
})()"""

CARD = """(() => ({
  name: document.getElementById("card-name").textContent,
  dots: document.querySelectorAll("#diagram .dg-dot").length,
  fingers: document.querySelectorAll("#diagram .dg-finger").length,
  note: document.getElementById("shape-note").innerText,
  count: document.querySelector("#diagram .count").textContent,
}))()"""


@in_chromium
def test_the_strip_draws_larger_diagrams_without_the_fingers(tmp_path):
    with Chromium(tmp_path / "profile") as browser:
        tab = opened(browser, build_viewer(UG_CHO), tmp_path)
        tab.eval("document.getElementById('strip-toggle').click()")
        seen = tab.eval(STRIP)
        tab.click("#strip button")  # G: its card, with the fingers
        card = tab.eval(CARD)
    assert seen["names"] == ["G", "D", "Em", "C", "G/B", "Am", "F"], seen
    assert len(seen["widths"]) == 7 and all(72 <= w <= 80 for w in seen["widths"]), seen  # was 58
    assert all(h >= 44 for h in seen["heights"]), seen  # each a target for a thumb
    assert seen["fingers"] == 0, seen  # too small to read there
    assert not seen["sideways"], seen
    assert card["name"] == "G" and card["fingers"] == card["dots"] > 0, card


@in_chromium
def test_the_strip_shows_the_tabs_own_shapes(tmp_path):
    with Chromium(tmp_path / "profile") as browser:
        tab = opened(browser, build_viewer(LEGEND), tmp_path)
        tab.eval("document.getElementById('strip-toggle').click()")
        dots = tab.eval("""Object.fromEntries([...document.querySelectorAll("#strip button")].map((b) =>
          [b.lastChild.textContent, b.querySelectorAll(".dg-dot").length]))""")
    assert dots["Cadd9"] == 4 and dots["G"] == 4, dots  # x32033 and 320033, the tab's; chords-db's have three


@in_chromium
def test_the_card_shows_the_tabs_shape_first_then_chords_dbs(tmp_path):
    with Chromium(tmp_path / "profile") as browser:
        tab = opened(browser, build_viewer(LEGEND), tmp_path, f"#chord={CADD9}")
        first = tab.eval(CARD)
        tab.click("#next")
        second = tab.eval(CARD)
    assert first == {"name": "Cadd9", "dots": 4, "fingers": 0, "note": TABS, "count": "1 of 5"}
    assert second == {"name": "Cadd9", "dots": 3, "fingers": 3, "note": CAPO, "count": "2 of 5"}  # chords-db's x32030


@in_chromium
def test_a_chord_the_tab_gave_no_shape_for_shows_chords_dbs(tmp_path):
    # The tab's x32033 is a Cadd9's: up two, the chord is a Dadd9, which the tab gave no shape for.
    with Chromium(tmp_path / "profile") as browser:
        seen = opened(browser, build_viewer(LEGEND), tmp_path, f"#t=2&chord={CADD9}").eval(CARD)
    assert seen["name"] == "Dadd9" and seen["note"] == CAPO and seen["count"] == f"1 of {len(DB['add9'][2])}", seen


# Where the card and its parts are on the screen: top and height.
CARD_PLACE = """(() => Object.fromEntries(["card", "card-name", "prev", "diagram", "next"].map((id) => {
  const r = document.getElementById(id).getBoundingClientRect();
  return [id, [Math.round(r.top), Math.round(r.height)]];
})))()"""


@in_chromium
@pytest.mark.parametrize("size", ["390,844", "1280,800"], ids=["phone", "desktop"])
def test_stepping_from_the_tabs_shape_to_chords_dbs_never_moves_the_card(tmp_path, size):
    # The card stands on the foot of the screen: a note on the tab's shape alone would move it, and ‹ ›
    # from under the thumb, between two taps.
    with Chromium(tmp_path / "profile", size=size) as browser:
        tab = opened(browser, build_viewer(LEGEND), tmp_path, f"#chord={CADD9}")
        places, notes = [tab.eval(CARD_PLACE)], [tab.eval(CARD)["note"]]
        for button in ("#next", "#next", "#prev", "#prev"):
            tab.click(button)
            places.append(tab.eval(CARD_PLACE))
            notes.append(tab.eval(CARD)["note"])
    assert notes == [TABS, CAPO, CAPO, CAPO, TABS]
    assert all(place == places[0] for place in places), places
