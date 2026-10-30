"""The names each page fills in for a text, in a real browser: every path reads them on the server (song_names.py) and
no page splits a text itself, so the same text gives the same artist and title wherever it is typed or pasted.

The paths: the library page's request form, filled in from a query; its Make the sheet, from the YouTube video
suggested for the query; the lookup page's form by name (Look up); a pasted YouTube link's panel, from the video's
title and channel. A real ``caracole serve`` serves both pages (test_web_page_youtube.py's: its queue a FakeSheet that
answers YouTube's searches and video reads with the video a test sets).
"""

from __future__ import annotations

import json
from urllib.parse import quote

from helpers.browser import CHROMIUM_MARKS
from test_web_page_search import REQUEST_FIELDS, answer_to, search, sites
from test_web_page_youtube import (  # noqa: F401 (fixtures)
    SILVANA_VIDEO,
    VIKINGOS,
    VIKINGOS_VIDEO,
    able,
    browser,
    live,
    paste,
    sheet,
)

pytestmark = CHROMIUM_MARKS  # every test here drives the pages in Chromium

BY_NAME = "['artist', 'title'].map((n) => document.querySelector(`#by-name [name=${n}]`).value)"
LOOK_UP = "#results .nothing .row-action button"  # the lookup page's Look up, where the sites found nothing
PANEL = "document.querySelector('#found .link-panel')"
PANEL_FIELDS = f"['artist', 'title'].map((n) => {PANEL}.querySelector(`input[name=${{n}}]`).value)"
YOUTUBE_ROW = "document.querySelector('#found .youtube-row')"
ESTOPA_VIDEO = {"id": "Wq3F0vFeYbU", "title": "Estopa - Como Camarón [Videoclip Oficial] HD", "channel": "EstopaVEVO",
                "duration": 214.0}
CREEP_VIDEO = {"id": "XFkzRNyygfk", "title": "Creep", "channel": "Radiohead - Topic", "duration": 238.0}


def same(expression: str, names: list[str]) -> str:
    """Whether the fields ``expression`` reads hold ``names``."""
    return f"{expression}.join('|') === {json.dumps('|'.join(names))}"


def on_the_library_page(page, base, query, names, *, video=False):
    """``query`` searched on the library page: its request form filled in with ``names`` (once the YouTube video
    suggested for it shows, with ``video``)."""
    page.open(base)
    search(page, query)
    shown = f"{answer_to(query)} && {YOUTUBE_ROW} !== null" if video else answer_to(query)
    assert page.wait(shown, timeout=20), page.js("document.getElementById('found').textContent")
    assert page.wait(same(REQUEST_FIELDS, names)), (query, page.js(REQUEST_FIELDS))


def on_the_lookup_page(page, base, query, names):
    """``query`` searched on the lookup page: its form by name filled in with ``names``, and so when Look up opens it,
    where the sites found nothing."""
    page.open(base + "lookup?q=" + quote(query))
    assert page.wait(f"document.getElementById('results').children.length > 0 && {same(BY_NAME, names)}"), (
        query, page.js(BY_NAME))
    if page.js(f"document.querySelector('{LOOK_UP}') !== null"):
        page.click(LOOK_UP)
        assert page.wait("document.getElementById('by-name-box').open")
        assert page.js(BY_NAME) == names, query


def pasted(page, base, video_id, names):
    """A link to the video ``video_id`` pasted into the library page's box: its panel's names, once it is read."""
    page.open(base)
    paste(page, f"https://www.youtube.com/watch?v={video_id}")
    assert page.wait(f"{PANEL} !== null && {PANEL}.querySelector('img.yt-thumb') !== null", timeout=20), \
        page.js("document.getElementById('found').textContent")
    assert page.wait(same(PANEL_FIELDS, names)), page.js(PANEL_FIELDS)


def test_artist_dash_title_with_any_dash_fills_both_pages_forms_alike(live, sheet, browser):  # noqa: F811
    base, posted = live
    for query in ("Silvana Estrada – Que problema", "Silvana Estrada — Que problema", "宋冬野 - 斑马斑马"):
        names = ["宋冬野", "斑马斑马"] if query.startswith("宋") else ["Silvana Estrada", "Que problema"]
        on_the_library_page(browser, base, query, names)
        on_the_lookup_page(browser, base, query, names)
    assert not [p for p, _ in posted if p in ("/request", "/lookup")]  # filled in, for you to check: nothing sent


def test_the_video_suggested_for_a_query_gives_the_same_names_everywhere(live, sheet, browser):  # noqa: F811
    # The owner's "silvana estrada que problema" with no index at all: YouTube's first video is her own upload, whose
    # channel names her, so every path fills her in, as the channel writes her name, and the rest as the title.
    base, posted = live
    sheet.example = SILVANA_VIDEO
    query, names = "silvana estrada que problema", ["Silvana Estrada", "que problema"]
    on_the_library_page(browser, base, query, names, video=True)
    browser.click("#found .youtube-row button")  # Make the sheet
    assert browser.wait("document.getElementById('request-box').open")
    assert browser.js(REQUEST_FIELDS) == names
    on_the_lookup_page(browser, base, query, names)  # the video kept for the query: the same answer
    # "creep", whose video is Radiohead's "Creep" from "Radiohead - Topic": the video is the query's song.
    sheet.example = CREEP_VIDEO
    on_the_library_page(browser, base, "creep", ["Radiohead", "creep"], video=True)
    browser.click("#found .youtube-row button")
    assert browser.wait("document.getElementById('request-box').open")
    assert browser.js(REQUEST_FIELDS) == ["Radiohead", "creep"]
    on_the_lookup_page(browser, base, "creep", ["Radiohead", "creep"])
    pasted(browser, base, CREEP_VIDEO["id"], ["Radiohead", "Creep"])  # its link pasted: the video's own names
    assert not [p for p, _ in posted if p in ("/request", "/lookup")]


def test_a_videos_title_pasted_as_its_link_or_typed_gives_the_same_names(live, sheet, browser):  # noqa: F811
    # The owner's Estopa video: its link pasted, or its title typed into either page's box.
    base, posted = live
    sheet.example = ESTOPA_VIDEO
    names = ["Estopa", "Como Camarón"]
    pasted(browser, base, ESTOPA_VIDEO["id"], names)
    on_the_library_page(browser, base, ESTOPA_VIDEO["title"], names)
    on_the_lookup_page(browser, base, ESTOPA_VIDEO["title"], names)


def test_a_fans_song_dash_band_turns_round_everywhere_once_the_band_is_known(able, live, sheet, browser):  # noqa: F811
    # The owner's "Somos vikingos veganos - Hyperfanes" from kintanedu, once an index knows Hyperfanes.
    base, posted = live
    sites(able, ug=[("hyperfanes", f"song-{i}", 1) for i in range(5)])
    sheet.example = VIKINGOS_VIDEO
    names = ["Hyperfanes", "Somos vikingos veganos"]
    pasted(browser, base, VIKINGOS, names)
    on_the_library_page(browser, base, VIKINGOS_VIDEO["title"], names)
    on_the_lookup_page(browser, base, VIKINGOS_VIDEO["title"], names)


def test_a_field_you_typed_into_keeps_what_you_typed_on_both_pages(live, sheet, browser):  # noqa: F811
    # The sites find nothing: each page's Request (Look up) opens its form, the artist typed in, then another search.
    base, posted = live
    for page, fields, form, opener in (
            (base + "lookup", BY_NAME, "#by-name", LOOK_UP),
            (base, REQUEST_FIELDS, "form.request-form", "#results section.nothing .line-action button")):
        browser.open(page)
        search(browser, "Que problema")
        assert browser.wait(f"document.querySelector({json.dumps(opener)}) !== null && "
                            f"{same(fields, ['', 'Que problema'])}"), browser.js(fields)
        browser.click(opener)
        assert browser.wait(f"document.activeElement === document.querySelector('{form} [name=artist]')")
        browser.type("Nick Cani")
        search(browser, "Silvana Estrada – Tregua")
        assert browser.wait(same(fields, ["Nick Cani", "Tregua"])), (page, browser.js(fields))
