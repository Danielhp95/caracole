"""The viewer's pages printed: in the light palette whatever the screen's scheme, with margins on every side.

A sheet, a songbook and a harmonica tab's page print from the browser (and on the phone, through Android's print
framework, which gives a page no margin of its own). Printed from a screen in dark mode they used to keep the dark
palette's variables, light grey text on white paper; and with no ``@page`` margin, a WebView's printout ran to the
paper's edges. viewer.css, which every one of the three inlines first, keeps its dark palette for the screen alone,
prints in the light one (``color-scheme: light``) and gives the paper its margins (``@page``), so book.css and
harptab.css, which hold no palette of their own, print in it too. Chromium's print emulation
(``Emulation.setEmulatedMedia``, ``media="print"``) reads each page as the printout lays it out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook
from caracole.viewer.harptab_page import build_harmonica_viewer

from helpers.browser import CHROMIUM_MARKS, Browser

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

FIXTURES = Path(__file__).parent / "fixtures"
LEGEND = (FIXTURES / "chordpro" / "legend_sheet.cho").read_text(encoding="utf-8")  # notes, a legend, the song
TAB = (FIXTURES / "harptabs" / "tabs" / "124_heart-of-gold.txt").read_text(encoding="utf-8")
KINDS = ("sheet", "songbook", "harmonica")

# What the printout's colours are: every custom property of the light palette (viewer.css's first ``:root`` rule
# that sets --bg), the root's color-scheme, and the colours of what a sheet, a songbook and a tab's page print.
COLOURS = """(() => {
  const root = [...document.styleSheets].flatMap((s) => [...s.cssRules])
    .find((r) => r.selectorText === ":root" && r.style.getPropertyValue("--bg"));
  const names = [...root.style].filter((n) => n.startsWith("--")).sort();
  const css = getComputedStyle(document.documentElement);
  const vars = Object.fromEntries(names.map((n) => [n, css.getPropertyValue(n).trim()]));
  const shown = {};
  for (const sel of ["body", "h1", ".artist a", ".facts", ".facts .from", ".lbl", ".l", ".c", ".tab", ".pre",
                     ".pre .l", ".notice", ".pos", ".toc .a", ".h .b", ".h .d", ".note", ".why", ".legend"]) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const s = getComputedStyle(el);
    shown[sel] = [s.color, s.backgroundColor, s.borderTopColor];
  }
  return { scheme: css.colorScheme, vars, shown };
})()"""

# The paper's margins: each ``@page`` rule's, in the order the page's stylesheets give them.
PAGE_RULES = """[...document.styleSheets].flatMap((s) => [...s.cssRules])
  .filter((r) => r instanceof CSSPageRule)
  .map((r) => ({ top: r.style.marginTop, right: r.style.marginRight, bottom: r.style.marginBottom,
                 left: r.style.marginLeft }))"""


def _written(tmp_path: Path, kind: str) -> tuple[str, str]:
    """The page of ``kind`` written where render.py writes it, and the address fragment it opens on."""
    folder = tmp_path / "Library" / "The Placeholders" / "Legend Song"
    folder.mkdir(parents=True, exist_ok=True)
    if kind == "sheet":
        html, name, fragment = build_viewer(LEGEND, pdf="sheet.pdf"), "sheet.html", ""
    elif kind == "songbook":
        html = build_songbook("Campfire", [BookSong("Legend Song", "The Placeholders", cho=LEGEND, id="aaaa")])
        name, fragment = "songbook.html", "#song-1"
    else:
        html = build_harmonica_viewer(TAB, title="Legend Song", artist="The Placeholders",
                                      tab_file="harmonica-1.txt", page_key="G")
        (folder / "harmonica-1.txt").write_text(TAB, encoding="utf-8")
        name, fragment = "harmonica-1.html", ""
    (folder / name).write_text(html, encoding="utf-8")
    return (folder / name).as_uri(), fragment


def _seen(tmp_path: Path, kind: str, media: str, scheme: str) -> dict:
    url, fragment = _written(tmp_path, kind)
    with Browser(tmp_path / f"profile-{kind}-{media}-{scheme}", width=1280, height=900) as b:
        b.open(url + fragment)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        b.send("Emulation.setEmulatedMedia", media=media,
               features=[{"name": "prefers-color-scheme", "value": scheme}])
        assert b.wait(f"matchMedia('{media} and (prefers-color-scheme: {scheme})').matches")
        return b.js(COLOURS)


@pytest.mark.parametrize("kind", KINDS)
def test_a_page_prints_in_the_light_palette_from_a_dark_screen(tmp_path, kind):
    dark = _seen(tmp_path, kind, "print", "dark")
    light = _seen(tmp_path, kind, "print", "light")
    on_screen = _seen(tmp_path, kind, "screen", "light")
    assert dark["scheme"] == "light", dark["scheme"]  # the browser's own parts, light on paper too
    assert dark["vars"] == on_screen["vars"], {n: v for n, v in dark["vars"].items() if on_screen["vars"][n] != v}
    assert dark == light
    assert dark["shown"] and dark["shown"]["body"][:2] == ["rgb(0, 0, 0)", "rgb(255, 255, 255)"]


@pytest.mark.parametrize("kind", KINDS)
def test_the_screen_keeps_its_dark_palette(tmp_path, kind):
    dark = _seen(tmp_path, kind, "screen", "dark")
    light = _seen(tmp_path, kind, "screen", "light")
    assert dark["vars"]["--bg"] != light["vars"]["--bg"] and dark["vars"]["--text"] != light["vars"]["--text"]


@pytest.mark.parametrize("kind", KINDS)
def test_the_paper_has_margins_on_every_side(tmp_path, kind):
    url, fragment = _written(tmp_path, kind)
    with Browser(tmp_path / "profile", width=1280, height=900) as b:
        b.open(url + fragment)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        rules = b.js(PAGE_RULES)
    assert rules, "no @page rule"
    margins = rules[-1]
    assert margins["left"] == margins["right"] and margins["top"] == margins["bottom"], margins
    assert all(value.endswith("mm") and float(value[:-2]) >= 10 for value in margins.values()), margins
