"""index.html's filters in one Filter button (take B.1), in a real browser: the toolbar's tags, Filter, Sort and
Select, and the panel Filter opens, a popover under it on a computer and a sheet from the bottom on a phone, with the
songs' Status, what they have something for and their Key."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from helpers import browser
from helpers.browser import CHROMIUM_MARKS

from caracole.library import keep_file, song_dir
from caracole.library_page import build_library_page, write_library_page
from caracole.overrides import Overrides
from caracole.songs import update_song
from caracole.versions import upsert_version

from conftest import add_song

pytestmark = CHROMIUM_MARKS

NOW = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)
TITLES = "[...document.querySelectorAll('#list article h3')].map((h) => h.textContent)"
PANEL = "document.getElementById('filter-panel')"
FILTER = "document.getElementById('filter')"
FOCUS_IN_PANEL = f"{PANEL}.contains(document.activeElement)"


def sheet(conn, cfg, song, key=None, *, tab_id, kind="chords"):
    """The song's chord sheet from Ultimate Guitar, as the fetch keeps it, in ``key`` (UG's tonality) or none."""
    v = upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="sheet", kind=kind, rating=4.5,
                       votes=12, version=1, label=None, url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}",
                       raw={"tonality_name": key} if key else {}, now="2026-10-27T00:00:00Z")
    doc = json.dumps({"content": "Words\n"}).encode()
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet.json", data=doc, rank=1)
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet.txt", data=b"Words\n", rank=1)


def put(cfg, song, *names):
    folder = song_dir(cfg.library_dir, song)
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


@pytest.fixture
def shelf(conn, cfg):
    """Nine songs: Hotel California holds one of everything (B minor); three harmonica songs with their sheets
    (Blowin' in the Wind in D, Like a Rolling Stone in C, Heart of Gold in E minor); Creep's sheet in G and a text tab;
    Riptide's Ukulele Chords, in no key; De Música Ligera's sheet in A minor, found and in review; Hysteria and
    Wonderwall wanted, with nothing yet."""
    from helpers.library_songs import hotel_california

    hotel_california(conn, cfg)
    for n, (artist, title, key) in enumerate((("Bob Dylan", "Blowin' in the Wind", "D"),
                                              ("Bob Dylan", "Like a Rolling Stone", "C"),
                                              ("Neil Young", "Heart of Gold", "Em")), start=1):
        song = add_song(conn, artist, title)
        sheet(conn, cfg, song, key, tab_id=n)
        put(cfg, song, "harmonica-1.txt")
        update_song(conn, song.id, status="found")
    creep = add_song(conn, "Radiohead", "Creep")
    sheet(conn, cfg, creep, "G", tab_id=4)
    put(cfg, creep, "tab.txt")
    update_song(conn, creep.id, status="found")
    riptide = add_song(conn, "Vance Joy", "Riptide")
    sheet(conn, cfg, riptide, tab_id=5, kind="ukulele")
    update_song(conn, riptide.id, status="found")
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    sheet(conn, cfg, soda, "Am", tab_id=6)
    update_song(conn, soda.id, status="found", review=True)
    add_song(conn, "Muse", "Hysteria")
    add_song(conn, "Oasis", "Wonderwall")
    return write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW))


@pytest.fixture
def laptop(tmp_path):
    with browser.Browser(tmp_path / "chrome", width=1280, height=900) as page:
        yield page


@pytest.fixture
def phone(tmp_path):
    with browser.Browser(tmp_path / "chrome-phone", width=390, height=844, mobile=True) as page:
        yield page


# Each control the toolbar shows, left to right: what it is, its words, and where it is.
TOOLBAR = """[...document.querySelectorAll('.toolbar button, .toolbar select, .toolbar .divider')]
  .filter((n) => n.checkVisibility() && !document.getElementById('filter-panel').contains(n))
  .map((n) => { const r = n.getBoundingClientRect();
    const g = n.querySelector('svg.glyph') || (n.matches('select') ? n.parentElement.querySelector('svg.glyph') : null);
    return { id: n.id || n.className, text: n.matches('select') ? n.selectedOptions[0].textContent
             : n.textContent.trim().replace(/\\s+/g, ' '), glyph: g ? g.getAttribute('class') : null,
             left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), height: Math.round(r.height) }; })
  .sort((a, b) => a.left - b.left)"""


def test_the_toolbar_is_tags_filter_sort_and_select(shelf, laptop):
    laptop.open(shelf.as_uri())
    tools = laptop.js(TOOLBAR)
    assert [t["id"] for t in tools] == ["filter", "sort", "divider", "tool pick-toggle"], tools
    assert [t["text"] for t in tools] == ["Filter", "Artist A–Z", "", "Select"], tools
    assert [t["glyph"] for t in tools if t["id"] != "divider"] == [
        "glyph glyph-sliders", "glyph glyph-sort", "glyph glyph-select"], tools
    assert max(t["top"] + t["height"] / 2 for t in tools) - min(t["top"] + t["height"] / 2 for t in tools) <= 2
    assert tools[0]["left"] > 1280 / 2  # at the right, the tags' room before them
    assert laptop.js(f"[{FILTER}.getAttribute('aria-expanded'), {FILTER}.getAttribute('aria-controls')]") == [
        "false", "filter-panel"]
    assert laptop.js(f"{PANEL}.tagName === 'DIALOG' && !{PANEL}.open")
    # A filter on: Filter counts it, in the accent.
    laptop.open(shelf.as_uri() + "#show=wanted")
    assert laptop.js(TOOLBAR)[0]["text"] == "Filter 1"
    assert laptop.js(f"{FILTER}.classList.contains('on')")
    assert laptop.js(f"getComputedStyle({FILTER}).borderTopColor") != laptop.js(
        "getComputedStyle(document.querySelector('.pick-toggle')).borderTopColor")


def test_filter_opens_a_popover_and_escape_closes_it_returning_focus(shelf, laptop):
    laptop.open(shelf.as_uri())
    laptop.click("#filter")
    assert laptop.wait(f"{PANEL}.open")
    assert laptop.js(f"{PANEL}.matches(':modal')") is False  # the list behind it stays, and filters as you tap
    assert laptop.js(f"{FILTER}.getAttribute('aria-expanded')") == "true"
    box = laptop.js(f"(() => {{ const p = {PANEL}.getBoundingClientRect(), f = {FILTER}.getBoundingClientRect();"
                    " return {left: p.left, right: p.right, top: p.top, under: f.bottom, width: innerWidth}; })()")
    assert 0 <= box["left"] and box["right"] <= box["width"] and box["top"] >= box["under"], box
    assert laptop.js("document.activeElement.dataset.show") == "all"  # the status chosen has the focus
    # The status, a segmented control: each with its count, the list behind filtering as you tap.
    counts = laptop.js("[...document.querySelectorAll('#filter-panel [data-show]')].filter((b) => b.checkVisibility())"
                       ".map((b) => b.textContent.replace(/\\s+/g, ' ').trim())")
    assert counts == ["All 9", "Found 7", "Wanted 2", "Review 1"], counts
    laptop.click("#filter-panel [data-show=wanted]")
    assert laptop.wait(f"JSON.stringify({TITLES}) === '[\"Hysteria\",\"Wonderwall\"]'"), laptop.js(TITLES)
    assert laptop.js(f"{PANEL}.open") and "show=wanted" in laptop.js("location.hash")
    assert laptop.js("document.querySelector('[data-show=wanted]').getAttribute('aria-checked')") == "true"
    # Arrow keys move within it, and choose as they go; Tab leaves it at once.
    laptop.press("ArrowRight")
    assert laptop.wait("document.activeElement.dataset.show === 'review'")
    assert laptop.wait(f"JSON.stringify({TITLES}) === '[\"De Música Ligera\"]'"), laptop.js(TITLES)
    laptop.press("ArrowLeft")
    laptop.press("ArrowLeft")
    assert laptop.wait("document.activeElement.dataset.show === 'found'")
    assert laptop.js("[...document.querySelectorAll('[data-show]')].filter((b) => b.tabIndex === 0)"
                     ".map((b) => b.dataset.show)") == ["found"]
    laptop.press("Escape")
    assert laptop.wait(f"!{PANEL}.open")
    assert laptop.js(f"document.activeElement === {FILTER} && {FILTER}.getAttribute('aria-expanded') === 'false'")
    assert "show=found" in laptop.js("location.hash")  # what was chosen stays
    # Filter again closes it, as it opened it.
    laptop.click("#filter")
    assert laptop.wait(f"{PANEL}.open")
    laptop.click("#filter")
    assert laptop.wait(f"!{PANEL}.open")
    assert laptop.js(f"document.activeElement === {FILTER}")


def test_a_click_outside_closes_the_popover(shelf, laptop):
    laptop.open(shelf.as_uri())
    laptop.click("#filter")
    assert laptop.wait(f"{PANEL}.open")
    laptop.click("#filter-panel [data-show=found]")  # a click inside keeps it
    assert laptop.js(f"{PANEL}.open")
    laptop.click(".masthead h1")
    assert laptop.wait(f"!{PANEL}.open")
    assert laptop.js(f"{FILTER}.getAttribute('aria-expanded')") == "false"
    assert laptop.js(f"document.activeElement === {FILTER}")  # the click took the focus nowhere: back to Filter


def test_below_720px_filter_opens_a_bottom_sheet_with_show_n_songs(shelf, phone):
    phone.open(shelf.as_uri())
    phone.click("#filter")
    assert phone.wait(f"{PANEL}.open")
    assert phone.js(f"{PANEL}.matches(':modal')")  # over a dimmed page, which takes no tap
    risen = f"Math.abs({PANEL}.getBoundingClientRect().bottom - innerHeight) <= 1"  # once it has slid up
    assert phone.wait(risen), phone.js(f"{PANEL}.getBoundingClientRect().bottom")
    box = phone.js(f"(() => {{ const p = {PANEL}.getBoundingClientRect();"
                   " return {left: p.left, right: p.right, top: p.top, width: innerWidth}; })()")
    assert box["left"] == 0 and box["right"] == box["width"] and box["top"] > 100, box
    shown = "document.getElementById('show-n')"
    assert phone.js(f"{shown}.checkVisibility() && {shown}.textContent") == "Show 9 songs"
    assert phone.js("document.getElementById('filter-live').checkVisibility()") is False
    phone.click("#filter-panel [data-show=wanted]")  # the list behind filters as you tap there too
    assert phone.wait(f"{shown}.textContent === 'Show 2 songs'")
    assert phone.js(TITLES) == ["Hysteria", "Wonderwall"]
    # The page behind stays where it is, and Tab keeps to the sheet.
    phone.js("document.body.style.paddingBottom = '2000px'")  # a page long enough to scroll
    wheel = dict(type="mouseWheel", x=195, y=60, deltaX=0, deltaY=600)  # over the page dimmed
    phone.send("Input.dispatchMouseEvent", **wheel)
    assert not phone.wait("window.scrollY > 0", timeout=1)
    for _ in range(16):
        phone.press("Tab")
        assert phone.js(FOCUS_IN_PANEL), phone.js("document.activeElement.outerHTML")
    phone.press("Escape")
    assert phone.wait(f"!{PANEL}.open")
    assert phone.js(f"document.activeElement === {FILTER}")
    phone.click("#filter")
    assert phone.wait(f"{PANEL}.open") and phone.wait(risen)
    phone.click("#show-n")
    assert phone.wait(f"!{PANEL}.open")
    assert phone.js(f"document.activeElement === {FILTER}") and phone.js(TITLES) == ["Hysteria", "Wonderwall"]
    phone.send("Input.dispatchMouseEvent", **wheel)  # closed, the same wheel scrolls the page
    assert phone.wait("window.scrollY > 0")


def test_the_sheets_controls_are_a_thumbs_target_on_a_touch_screen(shelf, phone):
    from helpers.targets import small_targets

    phone.open(shelf.as_uri())
    phone.click("#filter")
    assert phone.wait(f"{PANEL}.open")
    assert phone.wait(f"Math.abs({PANEL}.getBoundingClientRect().bottom - innerHeight) <= 1")
    assert phone.js(small_targets()) == []
    assert phone.js("document.documentElement.scrollWidth <= innerWidth")


def test_select_sits_last_and_still_starts_picking(shelf, laptop):
    laptop.open(shelf.as_uri() + "#show=wanted")
    tools = laptop.js(TOOLBAR)
    assert tools[-1]["id"] == "tool pick-toggle" and tools[-2]["id"] == "divider", tools
    laptop.click(".pick-toggle")
    assert laptop.wait("document.body.classList.contains('selecting') && !document.querySelector('.pickbar').hidden")
    laptop.click("#list article.line")  # a tap anywhere on a line picks it, on the filtered list
    assert laptop.wait("document.querySelector('.pick-count').textContent === '1 selected'")
    assert laptop.js("document.querySelector('#list article.picked h3').textContent") == "Hysteria"
    laptop.click(".pick-toggle")
    assert laptop.wait("!document.body.classList.contains('selecting')")
