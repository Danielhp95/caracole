"""The sheet viewer's chord shapes: the strip of every chord's shape above the song, and the chord's card.

The strip's diagrams are large enough to read at a glance; the fingers, too small to read there,
are on the chord's card.
"""

from __future__ import annotations

from pathlib import Path

from caracole.viewer import build_viewer

from helpers.browser import CHROMIUM_MARKS
from helpers.chromium import Chromium

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # G, D, Em, C, G/B, Am, F

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium


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
  note: document.getElementById("shape-note").textContent,
  count: document.querySelector("#diagram .count").textContent,
}))()"""


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
