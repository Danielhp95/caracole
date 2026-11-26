"""The library page at a larger text size, in a real browser: what is sized in the text's pixels (base.css ``--sp``) grows
with the text, a song's buttons and its line's row, its card's tiles, an artist's band, the search bar's tools; on a
phone, until a song's line fills its width, so that the line stays one row, its key on the screen.

The Android app's pinch sets the WebView's text zoom, which sizes the text and its line heights, never a length in px
or rem (measured on an emulator, WebView 133: at 200 % ``1rem`` and ``1em`` stay 16px, a root line height of 16px is
32px). Chromium on the computer has no text zoom: the tests grow the root's line height alone, as the text zoom does,
which is what ``--sp`` reads (``1rlh / 16``); PinchTest, on a device, pinches the real thing.
"""

from __future__ import annotations

import json
import re

import pytest
from helpers.browser import CHROMIUM_MARKS
from helpers.library_songs import hotel_california, with_versions
from test_library_assets import text_of
from test_library_card import SERVED, run
from test_library_filter import sheet as ug_sheet
from test_library_page import attribute_of, page, put
from test_library_plays import harmonica_song

from caracole.library_page import STYLESHEETS
from caracole.songs import update_song

from conftest import add_song

pytestmark = CHROMIUM_MARKS

# What a song's line shows, a line's row with nothing on it to press (Muse's Hysteria, wanted, on a page opened as a
# file: no Fetch), its artist's band, the bar's Filter and, its card opened, the card's first tile, each box's width
# and height (and a tile's gaps), at the root's line height ``lh``. The card opens after the line height is set: its
# tiles are a container whose queries are read as it is drawn.
SIZES = r"""
const box = (n) => { const r = n.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
const rowOf = (line) => { const s = getComputedStyle(line);
  return Math.round(line.getBoundingClientRect().height - parseFloat(s.borderTopWidth) - parseFloat(s.borderBottomWidth)); };
const sizes = (lh) => {
  document.documentElement.style.setProperty("line-height", lh);
  const line = lineOf("Hotel California");
  const out = { lh: getComputedStyle(document.documentElement).getPropertyValue("line-height"),
    play: box(line.querySelector(".line-plays > .play")), row: rowOf(lineOf("Hysteria")),
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


def test_at_twice_the_text_a_songs_buttons_row_band_and_tiles_are_twice_as_big(conn, cfg, tmp_path):
    songs(conn, cfg)
    own, twice = attribute_of(run(conn, cfg, tmp_path, SIZES, touch=True), "data-sizes")
    # At the pages' own size, a thumb's: the play tile 43 px (a tenth under 48, its target 45.6), a line's row 44 (as tall as its chevron made it), the
    # band 34, Filter 44 tall; the card's tile's icon 38 and chevron 44, its gaps 8 and 10 (the laptop's pane, 400 px
    # and more).
    assert own == {"lh": "16px", "play": [43, 43], "row": 44, "band": 34, "filter": 44,
                   "ico": [38, 38], "chevron": [44, 44], "gaps": ["8px", "10px"]}, own
    # Twice the text: each twice as big, on a window that has the room; the card, under 300 of the text's pixels now,
    # takes a narrow card's gaps.
    assert twice == {"lh": "32px", "play": [86, 86], "row": 88, "band": 68, "filter": 88,
                     "ico": [76, 76], "chevron": [88, 88], "gaps": ["12px", "16px"]}, twice


# Each line of the list: its title, whether its key (where it has one), its buttons and its action are on it and on the
# screen, and its first button's size.
LINES = r"""
const lines = () => Array.from(document.querySelectorAll("#list article.line")).map((line) => {
  const r = (n) => n.getBoundingClientRect(), at = r(line), keyed = line.querySelector(":scope > .line-key");
  const key = keyed ? r(keyed) : null;
  const title = r(line.querySelector("h3")), plays = Array.from(line.querySelectorAll(".line-plays > .play")).map(r);
  return { title: line.querySelector("h3").textContent,
    fits: (!key || key.right <= at.right + 0.5) && at.right <= innerWidth && plays.every((p) => p.right <= at.right + 0.5) &&
      line.querySelector(".line-action") .getBoundingClientRect().right <= at.right + 0.5,
    within: (!key || (key.top >= at.top - 0.5 && key.bottom <= at.bottom + 0.5)) && title.right <= at.right + 0.5,
    play: plays.length ? Math.round(plays[0].width) : 0 };
});
"""


@pytest.mark.parametrize("width", [390, 320])
def test_past_the_rooms_size_a_line_stays_one_row_on_a_phone_its_key_on_the_screen(conn, cfg, tmp_path, width):
    # Two and a half times the text, the most the app's pinch gives: the buttons grow until a line fills the phone's
    # width, and no more, by artist (bands and a folded artist) and by title (a flat list).
    songs(conn, cfg)
    script = LINES + r"""
    document.documentElement.style.setProperty("line-height", "40px");
    const byArtist = lines();
    const sort = document.getElementById("sort");
    sort.value = "title";
    sort.dispatchEvent(new Event("change"));
    const byTitle = lines();
    // A card opened: its box takes the line's margins and borders, the key inside them still.
    const creep = lineOf("Creep");
    openCardOf(creep);
    const edge = creep.getBoundingClientRect().right - parseFloat(getComputedStyle(creep).borderRightWidth);
    const opened = creep.querySelector(":scope > .line-key").getBoundingClientRect().right <= edge + 0.5;
    note("lines", { byArtist, byTitle, opened, wide: document.documentElement.scrollWidth <= innerWidth });"""
    drawn = attribute_of(run(conn, cfg, tmp_path, script, controls=SERVED, size=f"{width},800", touch=True),
                         "data-lines")
    room = round(43.2 * (width - 82) / 152)  # a tile at the most the room gives
    for by in ("byArtist", "byTitle"):
        assert sorted(line["title"] for line in drawn[by]) == ["Creep", "Hotel California", "Hysteria", "Take It Easy"]
        assert [line for line in drawn[by] if not (line["fits"] and line["within"])] == [], by
        assert {line["title"]: line["play"] for line in drawn[by]} == {
            "Creep": room, "Hotel California": room, "Hysteria": 0, "Take It Easy": room}, by
    assert drawn["opened"] is True and drawn["wide"] is True


# Each folded or flat line's title's width, and the least library.css gives it on a phone, 64 of the list's text's
# pixels less the gap (a probe sized so in the list, whose --sp Select mode caps).
TITLES = r"""
const titles = () => {
  const list = document.getElementById("list"), probe = document.createElement("div");
  probe.style.width = "calc(64 * var(--sp) - 6px)";
  list.append(probe);
  const least = probe.getBoundingClientRect().width;
  probe.remove();
  return Array.from(document.querySelectorAll("#list section.artist.folded article.line, #list section.flat article.line"))
    .map((line) => ({ title: line.querySelector("h3").textContent, least,
                      width: line.querySelector("h3").getBoundingClientRect().width }));
};
"""


@pytest.mark.parametrize("width", [390, 360])
@pytest.mark.parametrize("lh", ["24px", "32px"], ids=["150 %", "200 %"])
def test_in_select_mode_a_phones_line_keeps_its_titles_least_and_its_key_on_the_screen(conn, cfg, tmp_path, width,
                                                                                       lh):
    # Select mode's box beside each line takes room from the title: its columns in the text's pixels, as library.css's,
    # never in rem (a title cut to 58 px at 150 %), and the box's room taken from what the text's pixel may grow to,
    # so the line keeps its title's least, its buttons and its key on the screen, by artist and by title.
    songs(conn, cfg)
    script = LINES + TITLES + r"""
    document.documentElement.style.setProperty("line-height", "%s");
    document.body.classList.add("selecting");
    const byArtist = { lines: lines(), titles: titles() };
    const sort = document.getElementById("sort");
    sort.value = "title";
    sort.dispatchEvent(new Event("change"));
    document.body.classList.add("selecting");
    const byTitle = { lines: lines(), titles: titles() };
    note("lines", { byArtist, byTitle, wide: document.documentElement.scrollWidth <= innerWidth });""" % lh
    drawn = attribute_of(run(conn, cfg, tmp_path, script, controls=SERVED, size=f"{width},800", touch=True),
                         "data-lines")
    for by in ("byArtist", "byTitle"):
        assert [line for line in drawn[by]["lines"] if not (line["fits"] and line["within"])] == [], (by, drawn)
        assert drawn[by]["titles"] and [t for t in drawn[by]["titles"] if t["width"] < t["least"] - 0.5] == [], (
            by, drawn)
    assert {t["title"] for t in drawn["byTitle"]["titles"]} == {"Creep", "Hotel California", "Hysteria",
                                                               "Take It Easy"}
    assert drawn["wide"] is True


DECLARATIONS = re.compile(r"(?:^|[;{])\s*((?:font|font-size|line-height)\s*:[^;}]*)")


def test_the_texts_pixel_sizes_boxes_never_a_text_or_its_line_height():
    # The text zoom sizes a text and its line height already: one in --sp would grow twice (a line height of
    # calc(16 * var(--sp)) is 64px at 200 %, measured on the emulator).
    found = {name: [d for d in DECLARATIONS.findall(re.sub(r"/\*.*?\*/", "", text_of(name), flags=re.S))
                    if "--sp" in d]
             for name in STYLESHEETS}
    assert {name: ds for name, ds in found.items() if ds} == {}



# A band's line's title, its buttons, its key and the line: their widths and right edges, and how many rows its buttons
# take, at the root's line height ``lh``, as the list draws it and in Select mode.
BAND_TITLE = r"""
window.bandLine = (lh, selecting) => {
  const line = [...document.querySelectorAll("#list .line")].find((l) => l.querySelector("h3").textContent ===
    "Hotel California");
  const r = (n) => n.getBoundingClientRect();
  const sp = parseFloat(getComputedStyle(document.documentElement).lineHeight) / 16;
  const key = line.querySelector(":scope > .line-key");
  const plays = Array.from(line.querySelectorAll(".line-plays > .play"));
  return { lh, selecting, band: !line.closest("section.artist").classList.contains("folded"),
    title: Math.round(r(line.querySelector("h3")).width), least: 64 * sp,
    under: line.classList.contains("plays-under"), plays: plays.length,
    rows: new Set(plays.map((p) => Math.round(r(p).top))).size,
    fits: r(key).right <= r(line).right + 0.5 && r(line).right <= innerWidth + 0.5 &&
      plays.every((p) => r(p).right <= r(line).right + 0.5) };
};
"""
FRAMES = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(done))))"


@pytest.mark.parametrize(("size", "touch"), [("720,400", True), ("844,390", True), ("1024,768", True),
                                             ("1180,820", True), ("800,600", False)])
def test_from_720_px_a_bands_line_keeps_its_title_whatever_its_buttons_take(conn, cfg, tmp_path, size, touch):
    # From 720 px a band's line has its buttons in a column of their own: grown with the text (a landscape phone, a
    # tablet, the app's pinch, to 250 %), they never take the title's 64 of the text's pixels, so the song's name
    # never goes, in Select mode too; the key stays on the line; and where they would wrap beside the title, they go
    # under it (library.js placePlays: plays-under, placed again as the text's size or Select changes), never one a
    # row in their column. Each read once the page has placed its lines (a frame after the change).
    from helpers.browser import Browser, BrowserError

    from caracole.library_page import write_library_page

    songs(conn, cfg)
    url = write_library_page(cfg.library_dir, page(conn, cfg)).as_uri()
    width, height = (int(n) for n in size.split(","))
    try:
        b = Browser(tmp_path / "chrome", width=width, height=height)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    drawn = []
    try:
        if touch:
            b.send("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            b.send("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}])
        b.open(url)
        assert b.wait("document.querySelectorAll('#list article.line').length === 4")
        b.js(BAND_TITLE)
        for selecting in (False, True):
            for lh in ("16px", "32px", "40px"):
                b.js(f"document.documentElement.style.setProperty('line-height', '{lh}'); "
                     f"document.body.classList.toggle('selecting', {json.dumps(selecting)})")
                b.js(FRAMES)
                drawn.append(b.js(f"bandLine('{lh}', {json.dumps(selecting)})"))
    finally:
        b.close()
    said = json.dumps(drawn)
    assert all(m["band"] for m in drawn), said
    assert [m for m in drawn if m["title"] < m["least"] - 0.5 or not m["fits"]] == [], said
    assert [m for m in drawn if m["plays"] > 1 and m["rows"] >= m["plays"]] == [], said  # never one a row
    assert [m for m in drawn if not m["under"] and m["rows"] > 1] == [], said  # wrapped: under the title instead


@pytest.mark.parametrize("lh", ["16px", "32px"], ids=["100 %", "200 %"])
def test_on_a_phone_the_bars_plus_holds_one_row_beside_filter_and_sort(conn, cfg, tmp_path, monkeypatch, lh):
    # Served where a sheet can be made from an audio file, the bar has a third tool, the "+", sized as Filter is: the
    # field and the three tools one row at 390 px, at the pages' own text size and at twice it, nothing past the screen.
    import caracole.library_page as library_page
    from caracole.audio_store import AUDIO_MAX, TOO_BIG

    monkeypatch.setattr(library_page, "audio_member", lambda cfg: {"ok": True, "why": None, "limit": AUDIO_MAX,
                                                                       "too_big": TOO_BIG})
    songs(conn, cfg)
    script = r"""
    document.documentElement.style.setProperty("line-height", %s);
    const r = (id) => document.getElementById(id).getBoundingClientRect();
    const row = document.querySelector(".bar-row").getBoundingClientRect();
    const parts = [r("q"), r("add-audio"), r("filter"), r("sort")];
    note("bar", { plus: [Math.round(r("add-audio").width), Math.round(r("add-audio").height)],
      filter: [Math.round(r("filter").width), Math.round(r("filter").height)],
      text: document.getElementById("add-audio").textContent, glyph: getComputedStyle(document.getElementById("add-audio")).fontSize !== "0px",
      oneRow: parts.every((p) => p.top >= row.top - 0.5 && p.bottom <= row.bottom + 0.5 && p.top < parts[0].bottom),
      within: parts.every((p) => p.right <= innerWidth + 0.5), wide: document.documentElement.scrollWidth <= innerWidth });
    """ % json.dumps(lh)
    bar = attribute_of(run(conn, cfg, tmp_path, script, controls=SERVED, size="390,800", touch=True), "data-bar")
    assert bar["plus"] == bar["filter"] and bar["text"] == "+" and bar["glyph"], bar
    assert bar["oneRow"] and bar["within"] and bar["wide"], bar
