"""The library page at a larger text size, in a real browser: what is sized in the text's pixels (base.css ``--sp``) grows
with the text, a song's buttons and chevron, its card's tiles, an artist's band, the search bar's tools; on a phone,
until a song's line fills its width, so that the line stays one row, its chevron on the screen.

The Android app's pinch sets the WebView's text zoom, which sizes the text and its line heights, never a length in px
or rem (measured on an emulator, WebView 133: at 200 % ``1rem`` and ``1em`` stay 16px, a root line height of 16px is
32px). Chromium on the computer has no text zoom: the tests grow the root's line height alone, as the text zoom does,
which is what ``--sp`` reads (``1rlh / 16``); PinchTest, on a device, pinches the real thing.
"""

from __future__ import annotations

import re

import pytest
from helpers.browser import CHROMIUM_MARKS
from helpers.library_songs import hotel_california, with_versions
from test_library_assets import text_of
from test_library_card import SERVED, run
from test_library_filter import sheet as ug_sheet
from test_library_page import attribute_of, put
from test_library_plays import harmonica_song

from caracole.library_page import STYLESHEETS
from caracole.songs import update_song

from conftest import add_song

pytestmark = CHROMIUM_MARKS

# What a song's line shows, its artist's band, the bar's Filter and, its card opened, the card's first tile, each box's
# width and height (and a tile's gaps), at the root's line height ``lh``. The card opens after the line height is set:
# its tiles are a container whose queries are read as it is drawn.
SIZES = r"""
const box = (n) => { const r = n.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
const sizes = (lh) => {
  document.documentElement.style.setProperty("line-height", lh);
  const line = lineOf("Hotel California");
  const out = { lh: getComputedStyle(document.documentElement).getPropertyValue("line-height"),
    play: box(line.querySelector(".line-plays > .play")), more: box(line.querySelector(":scope > .line-more")),
    band: box(line.closest("section.artist").querySelector(".artist-title"))[1],
    filter: box(document.getElementById("filter"))[1] };
  const card = cardOf(openCard("Hotel California"));
  const tile = card.querySelector(".tiles > .tile");
  out.ico = box(tile.querySelector(".tile-ico"));
  out.chevron = box(tile.querySelector(":scope > .tile-more"));
  out.gaps = [getComputedStyle(tile).columnGap, getComputedStyle(tile.querySelector(".tile-open")).columnGap];
  closeCard(line);
  return out;
};
note("sizes", [sizes("16px"), sizes("32px")]);
"""


def songs(conn, cfg):
    """Eagles' two songs under their band, Hotel California with its five buttons; Radiohead's Creep, folded, with its
    sheet in G minor (a key on its line, as wide as the key's column lets it be); Muse's Hysteria, wanted, its Fetch
    on its line."""
    with_versions(conn, cfg, hotel_california(conn, cfg))
    harmonica_song(conn, cfg)
    creep = add_song(conn, "Radiohead", "Creep")
    ug_sheet(conn, cfg, creep, "Gm", tab_id=4)
    put(cfg, creep, "sheet.html")
    update_song(conn, creep.id, status="found")
    add_song(conn, "Muse", "Hysteria")


def test_at_twice_the_text_a_songs_buttons_chevron_band_and_tiles_are_twice_as_big(conn, cfg, tmp_path):
    songs(conn, cfg)
    own, twice = attribute_of(run(conn, cfg, tmp_path, SIZES, touch=True), "data-sizes")
    # At the pages' own size, a thumb's: the play tile 48 px, the chevron 44, the band 34, Filter 44 tall; the card's
    # tile's icon 38 and chevron 44, its gaps 8 and 10 (the laptop's pane, 400 px and more).
    assert own == {"lh": "16px", "play": [48, 48], "more": [44, 44], "band": 34, "filter": 44,
                   "ico": [38, 38], "chevron": [44, 44], "gaps": ["8px", "10px"]}, own
    # Twice the text: each twice as big, on a window that has the room; the card, under 300 of the text's pixels now,
    # takes a narrow card's gaps.
    assert twice == {"lh": "32px", "play": [96, 96], "more": [88, 88], "band": 68, "filter": 88,
                     "ico": [76, 76], "chevron": [88, 88], "gaps": ["12px", "16px"]}, twice


# Each line of the list: its title, whether its chevron, its buttons and its action are on it and on the screen, and its
# first button's size.
LINES = r"""
const lines = () => Array.from(document.querySelectorAll("#list article.line")).map((line) => {
  const r = (n) => n.getBoundingClientRect(), at = r(line), more = r(line.querySelector(":scope > .line-more"));
  const title = r(line.querySelector("h3")), plays = Array.from(line.querySelectorAll(".line-plays > .play")).map(r);
  return { title: line.querySelector("h3").textContent,
    fits: more.right <= at.right + 0.5 && at.right <= innerWidth && plays.every((p) => p.right <= at.right + 0.5) &&
      line.querySelector(".line-action") .getBoundingClientRect().right <= at.right + 0.5,
    within: more.top >= at.top - 0.5 && more.bottom <= at.bottom + 0.5 && title.right <= at.right + 0.5,
    play: plays.length ? Math.round(plays[0].width) : 0 };
});
"""


@pytest.mark.parametrize("width", [390, 320])
def test_past_the_rooms_size_a_line_stays_one_row_on_a_phone_its_chevron_on_the_screen(conn, cfg, tmp_path, width):
    # Two and a half times the text, the most the app's pinch gives: the buttons and the chevron grow until a line
    # fills the phone's width, and no more, by artist (bands and a folded artist) and by title (a flat list).
    songs(conn, cfg)
    script = LINES + r"""
    document.documentElement.style.setProperty("line-height", "40px");
    const byArtist = lines();
    const sort = document.getElementById("sort");
    sort.value = "title";
    sort.dispatchEvent(new Event("change"));
    const byTitle = lines();
    // A card opened: its box takes the line's margins and borders, the chevron inside them still.
    const creep = lineOf("Creep");
    openCardOf(creep);
    const edge = creep.getBoundingClientRect().right - parseFloat(getComputedStyle(creep).borderRightWidth);
    const opened = creep.querySelector(":scope > .line-more").getBoundingClientRect().right <= edge + 0.5;
    note("lines", { byArtist, byTitle, opened, wide: document.documentElement.scrollWidth <= innerWidth });"""
    drawn = attribute_of(run(conn, cfg, tmp_path, script, controls=SERVED, size=f"{width},800", touch=True),
                         "data-lines")
    room = round(48 * (width - 88) / 192)  # a tile at the most the room gives
    for by in ("byArtist", "byTitle"):
        assert sorted(line["title"] for line in drawn[by]) == ["Creep", "Hotel California", "Hysteria", "Take It Easy"]
        assert [line for line in drawn[by] if not (line["fits"] and line["within"])] == [], by
        assert {line["title"]: line["play"] for line in drawn[by]} == {
            "Creep": room, "Hotel California": room, "Hysteria": 0, "Take It Easy": room}, by
    assert drawn["opened"] is True and drawn["wide"] is True


DECLARATIONS = re.compile(r"(?:^|[;{])\s*((?:font|font-size|line-height)\s*:[^;}]*)")


def test_the_texts_pixel_sizes_boxes_never_a_text_or_its_line_height():
    # The text zoom sizes a text and its line height already: one in --sp would grow twice (a line height of
    # calc(16 * var(--sp)) is 64px at 200 %, measured on the emulator).
    found = {name: [d for d in DECLARATIONS.findall(re.sub(r"/\*.*?\*/", "", text_of(name), flags=re.S))
                    if "--sp" in d]
             for name in STYLESHEETS}
    assert {name: ds for name, ds in found.items() if ds} == {}

