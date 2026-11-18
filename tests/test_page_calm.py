"""Stage 1f, a calmer page (library_assets/), in Chromium: four corner radii, one set of tokens in base.css.

The page is served (a real server, a lookup running and one queued), so that the tray, the Requests tab, the Songbooks
tab, the Sync sheet and a search's results hold what is measured: each state names what must be shown, and how many."""

from __future__ import annotations

import json

import pytest
from helpers.browser import CHROMIUM_MARKS
from helpers.targets import odd_radii
from test_web_page_steps import driven, live  # noqa: F401  (``live``: a fixture)

from caracole.library import keep_file, song_dir
from caracole.songbook import make_songbook, songbooks_file
from caracole.songs import update_song
from caracole.versions import upsert_version

from conftest import add_song

pytestmark = CHROMIUM_MARKS

# The elements of a lane not merged yet (the card's, lane 3b's, whose own radii come to the tokens with its merge).
OTHER_LANES = (".line-panel", ".play")


# What a state shows: a selector, and at least how many of it are rendered (checkVisibility), so that a state that
# drew nothing fails rather than passes by having nothing to measure.
SHOWN = "Array.from(document.querySelectorAll(%s)).filter((n) => n.checkVisibility()).length"


def put_sheet(conn, cfg, song, tab_id):
    v = upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="sheet", kind="chords",
                       rating=4.5, votes=12, version=1, label=None, url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}",
                       raw={}, now="2026-10-27T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet.txt", data=b"Words\n", rank=1)
    folder = song_dir(cfg.library_dir, song)
    (folder / "sheet.html").write_bytes(b"x")
    update_song(conn, song.id, status="found")


@pytest.fixture
def library(conn, cfg):
    """Three songs with sheets (Oasis twice, so a band), a songbook of two of them, and two songs wanted (Creep, matched
    to Ultimate Guitar, and Hysteria) whose lines offer Fetch now."""
    for n, (artist, title) in enumerate((("Oasis", "Wonderwall"), ("Oasis", "Live Forever"), ("Eagles", "Desperado"))):
        put_sheet(conn, cfg, add_song(conn, artist, title), n + 1)
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    add_song(conn, "Muse", "Hysteria")
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Oasis - Wonderwall", "Eagles - Desperado"])
    return creep


def odd_in(page, where: str, selector: str, floor: int) -> None:
    """Wait for ``selector`` to be rendered ``floor`` times or more, then: no corner radius but the four, but in the
    lanes not merged yet."""
    shown = SHOWN % json.dumps(selector)
    assert page.wait(f"{shown} >= {floor}", timeout=20), (where, selector, page.js(shown))
    assert page.js(odd_radii(OTHER_LANES)) == [], where


@pytest.mark.parametrize("size", [(390, 844), (1280, 900)], ids=["phone", "laptop"])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_library_page_has_four_corner_radii(library, live, tmp_path, size, scheme):  # noqa: F811
    base, runner = live
    from test_web_page_steps import FROM_UG

    runner.script = FROM_UG
    width, _ = size
    with driven(tmp_path, width) as page:
        page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme},
                                                          {"name": "prefers-reduced-motion", "value": "reduce"}])
        page.open(base)
        odd_in(page, "library", "#list article.line", 5)
        # A lookup running and one waiting: a bar on a line, the tray (it shows from two requests), the Requests tab.
        for title in ("Creep", "Hysteria"):
            line = page.js("Array.from(document.querySelectorAll('#list article.line')).find((l) => "
                           f"l.querySelector('h3').textContent.includes({json.dumps(title)})).dataset.id")
            page.click(f"#list article.line[data-id='{line}'] form.fetch button")
        odd_in(page, "lines with a bar", "#list .progress.barred .step-segs", 1)
        odd_in(page, "the tray", "#tray:not([hidden]) .tray-toggle", 1)
        page.click("#tray-toggle")
        odd_in(page, "the tray open", "#tray-list:not([hidden]) li", 2)
        page.click("#tray-toggle")
        # The Filter panel.
        page.click("#filter")
        odd_in(page, "the filter panel", "#filter-panel[open] .seg", 1)
        page.press("Escape")
        assert page.wait("!document.getElementById('filter-panel').open")
        # A search's results.
        page.click("#q")
        page.type("wonder")
        odd_in(page, "a search", "body.search-mode #results article.line", 1)
        page.click("#leave")
        # Each tab.
        page.js("location.hash = '#tab=songbooks'")
        odd_in(page, "songbooks", "#songbooks .book-line", 1)
        page.click("#songbooks .book-line")
        odd_in(page, "a songbook opened", "#songbooks .set-line", 2)
        for tab, selector, floor in (("sites", "#sites .site-row", 3),
                                     ("requests", "#requests .req", 2),
                                     ("sync", "#sync .sync-panel", 1)):
            page.js(f"location.hash = '#tab={tab}'")
            odd_in(page, tab, selector, floor)
        page.js("location.hash = '#sheet=sync'")
        odd_in(page, "the sync sheet", "#sync-sheet[open] .sync-top", 1)
