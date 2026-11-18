"""Stage 1e of the library page's redesign, long lists, in a real browser: what makes a list of thousands of songs
cheap to draw (rows.js, rows.css)."""

from __future__ import annotations

import json
import re

from helpers.browser import CHROMIUM_MARKS
from test_library_card import run
from test_library_page import attribute_of
from test_web_lookup_page import browser, index_songs, live  # noqa: F401  (fixtures)

from caracole import library_assets
from caracole.songs import update_song

from conftest import add_song

pytestmark = CHROMIUM_MARKS

# The sprite and every glyph drawn from it: how many sprites, the symbols, a path under any svg.glyph, and each
# glyph's use (its href's symbol there, its box).
SPRITE = r"""
const sprites = document.querySelectorAll("svg.glyph-sprite");
// the glyphs on show: one in a closed card or a hidden panel has no box to measure
const glyphs = [...document.querySelectorAll("svg.glyph")].filter((g) => g.getClientRects().length);
const symbols = [...document.querySelectorAll("svg.glyph-sprite symbol")];
const sprite = sprites[0];
return {
  sprites: sprites.length, hidden: sprite ? sprite.getAttribute("aria-hidden") : null,
  symbols: symbols.map((s) => s.id), box: symbols.every((s) => s.getAttribute("viewBox") === "0 0 24 24"),
  inside: symbols.every((s) => s.querySelectorAll("path").length > 0),
  loose: glyphs.filter((g) => g.querySelector("path")).length,
  uses: glyphs.map((g) => {
    const use = g.querySelector("use"), href = use ? use.getAttribute("href") || "" : "";
    return [g.querySelectorAll("use").length, href, !!sprite && href.length > 1 && !!sprite.querySelector(href),
      use ? use.getBBox().width : 0];
  }),
  count: glyphs.length,
};
"""


def glyph_names() -> list[str]:
    rows = (library_assets.ROWS_SCRIPT)
    body = re.search(r"const GLYPHS = \{(.*?)\n  \};", rows, re.S).group(1)
    return re.findall(r"^    (\w+): \[", body, re.M)


def check(found, shown=0):
    names = glyph_names()
    assert len(names) >= 20
    assert found["sprites"] == 1 and found["hidden"] == "true"
    assert sorted(found["symbols"]) == sorted(f"glyph-{n}" for n in names)
    assert found["box"] and found["inside"]
    assert found["loose"] == 0  # no path outside the sprite
    assert found["count"] >= shown
    for n_use, href, there, width in found["uses"]:
        assert n_use == 1 and href.startswith("#glyph-") and there and width > 0, (href, width)


def test_every_glyph_is_one_use_of_one_sprite(conn, cfg, tmp_path):
    for n in range(50):
        song = add_song(conn, f"Artist {n % 20}", f"Title {n}")
        update_song(conn, song.id, status="found")
    script = ('document.querySelector("#filter").click();'
              'for (const m of [...document.querySelectorAll("article.line > .line-more")].slice(0, 3)) m.click();'
              f'note("sprite", (() => {{ {SPRITE} }})());')
    dom = run(conn, cfg, tmp_path, script)
    check(attribute_of(dom, "data-sprite"), shown=6)


def test_the_lookup_page_draws_its_glyphs_from_the_sprite_too(cfg, live, browser):  # noqa: F811
    base, _ = live
    index_songs(cfg, [("eagles", "hotel-california", 9), ("eagles", "desperado", 3)])
    browser.open(base + "/lookup")
    browser.type("eagles")
    assert browser.wait("document.querySelectorAll('#results .hit').length > 0")
    found = json.loads(browser.js(f"JSON.stringify((() => {{ {SPRITE} }})())"))
    check(found)
