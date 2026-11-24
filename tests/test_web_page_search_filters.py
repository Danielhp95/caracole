"""The Filter panel while the sites' results show, in a real browser: its Matches (Chords, Guitar, Ukulele, Harmonica,
Score) keep the sites' songs as they keep yours, by what each one's rows have something for, its Status and Key your
songs alone; the panel opens over the results, stays open as you tap, and counts what they show.

The owner's ask of 2026-11-22: "I want to be able to do things like "search yoko kanno" while looking only for
harmonica songs." A real ``caracole serve`` serves the page (test_web_page_search.py's ``live``), over UG's index and
harptabs.com's (Billy Joel's page read: three of his songs, 98 tabs).
"""

from __future__ import annotations

import json

import pytest
from helpers.browser import CHROMIUM_MARKS
from test_web_page_search import (COUNTS, GRID, LINES, answer_to, browser, library, live, phone, same, search,  # noqa: F401
                                  sites)

from caracole import db
from caracole.library import song_dir

pytestmark = CHROMIUM_MARKS

PANEL = "document.getElementById('filter-panel')"
NOTE = "document.querySelector('#results p.filtered')"
CHIP = "#filter-panel [data-inst={}]"
# Each artist's group's tail: its buttons that show ("+ 1 more by billy joel on harptabs.com").
TAILS = ("[...document.querySelectorAll('#results .group-tail')].map((t) => [...t.children]"
         ".filter((c) => !c.hidden).map((c) => c.textContent))")


def harptabs(cfg):
    """harptabs.com's index, as test_search.py makes it: Billy Joel's page read, the Beatles' in part."""
    from test_search import harptabs_index

    conn = db.connect(cfg.db_path)
    harptabs_index(conn)
    conn.commit()
    conn.close()


def harmonica(cfg, song):
    """A harmonica tab of the song's, filed as harptabs.com's are (``harmonica-1.txt``)."""
    folder = song_dir(cfg.library_dir, song)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "harmonica-1.txt").write_bytes(b"4 -4 5\n")


def chip(page, name):
    """The Matches chip ``name``: whether it is pressed, its count, and whether it can be pressed."""
    q = json.dumps(CHIP.format(name))
    return page.js(f"(() => {{ const c = document.querySelector({q}); return [c.getAttribute('aria-pressed'), "
                   "c.querySelector('.n').textContent, !c.disabled]; })()")


# Under Filter: the panel's top a little below Filter's foot, its right edge Filter's.
UNDER_FILTER = ("(() => { const p = document.getElementById('filter-panel').getBoundingClientRect(), "
                "f = document.getElementById('filter').getBoundingClientRect(); "
                "return [Math.round(p.top - f.bottom), Math.round(p.right - f.right)]; })()")
STATUS = "document.getElementById('bar-status').textContent"
BILLY = [("billy-joel", "piano-man", 5), ("billy-joel", "uptown-girl", 3)]  # UG's: chords alone


def test_the_instruments_filter_the_sites_songs_in_the_results_too(cfg, live, browser):  # noqa: F811
    # With Harmonica on, the results are what has a harmonica tab: your songs with one, as in the list, and a site's
    # song by what its rows have: a UG song of chords alone has none.
    base, _, _ = live
    sites(cfg, ug=[("eagles", "take-it-easy", 2), ("eagles", "hotel-california", 3)])
    hotel, _ = library(cfg, ("Eagles", "Hotel California"), ("Eagles", "Desperado"))
    harmonica(cfg, hotel)
    browser.open(base + "#inst=harmonica")
    assert browser.js(GRID) == ["Hotel California"]
    search(browser, "eagles")
    assert browser.wait(f"{answer_to('eagles')} && {same(LINES, [['Eagles', [['Hotel California', 'yours']]]])}"), \
        browser.js(LINES)
    # The results' head says it, the toolbar stepping aside, and Show all lets it go: the sites' songs too.
    assert browser.js(f"{NOTE}.firstChild.textContent") == "With harmonica tab"
    assert browser.js(f"{NOTE}.lastChild.textContent") == "Show all"
    browser.click("#results p.filtered > button")
    assert browser.wait(f"{LINES}.length === 1 && {LINES}[0][1].length === 3"), browser.js(LINES)
    [(artist, lines)] = browser.js(LINES)
    assert sorted(map(tuple, lines)) == [("Desperado", "yours"), ("Hotel California", "yours"), ("Take It Easy", "ug")]
    assert "inst=" not in browser.js("location.hash") and browser.js(f"{NOTE}.hidden") is True


def test_searching_billy_joel_for_harmonica_tabs_the_panel_filters_the_results_as_you_tap(cfg, live, browser):  # noqa: F811
    base, _, _ = live
    sites(cfg, ug=BILLY)
    harptabs(cfg)
    library(cfg, ("Radiohead", "Creep"))  # none of yours has a harmonica tab: the results' songs count
    browser.open(base)
    search(browser, "billy joel")
    every = [["Billy Joel", [["Piano Man", "ug+harptabs"], ["Uptown Girl", "ug"], ["Vienna!", "harptabs"],
                             ["She's Always a Woman", "harptabs"]]]]
    assert browser.wait(f"{answer_to('billy joel')} && {same(LINES, every)}"), browser.js(LINES)
    # Filter opens over the results, under Filter; each chip counts the results' songs it would show.
    browser.click("#filter")
    assert browser.wait(f"{PANEL}.open")
    assert browser.js(UNDER_FILTER)[0] in range(4, 13), browser.js(UNDER_FILTER)
    assert [chip(browser, x) for x in ("sheet", "guitar", "harmonica")] == [
        ["false", "2", True], ["false", "0", False], ["false", "3", True]]
    # Harmonica: harptabs.com's three songs, Piano Man with UG's mark still; UG's Uptown Girl, chords alone, gone.
    browser.click(CHIP.format("harmonica"))
    harps = [["Billy Joel", [["Piano Man", "ug+harptabs"], ["Vienna!", "harptabs"], ["She's Always a Woman", "harptabs"]]]]
    assert browser.wait(same(LINES, harps)), browser.js(LINES)
    # The panel stays open, under Filter, saying how many the results show; harptabs.com's "+ 1 more" stays.
    assert browser.js(f"{PANEL}.open") is True and browser.js(UNDER_FILTER)[0] in range(4, 13)
    assert browser.js("document.getElementById('filter-live').textContent") == "3 songs"
    assert browser.js(TAILS) == [["+ 1 more by Billy Joel on harptabs.com"]]
    assert chip(browser, "harmonica") == ["true", "3", True]
    # The marks under the box count the lines shown, and the words say what keeps them.
    assert browser.js(COUNTS) == [["library", "done", 0], ["ug", "done", 1], ["harptabs", "partial", 3],
                                  ["rest", None, 0]]
    assert browser.js(STATUS).startswith("With harmonica tab: 1 on Ultimate Guitar · 3 on harptabs.com")
    assert browser.js(f"{NOTE}.firstChild.textContent") == "With harmonica tab"
    assert "inst=harmonica" in browser.js("location.hash")
    # Chords too: what has either, Uptown Girl back.
    browser.click(CHIP.format("sheet"))
    assert browser.wait(same(LINES, every)), browser.js(LINES)
    assert browser.js(f"{NOTE}.firstChild.textContent") == "With chord sheet or harmonica tab"
    browser.press("Escape")  # the panel closes, the focus back on Filter, the results as they are
    assert browser.wait(f"!{PANEL}.open && document.activeElement === document.getElementById('filter')")
    assert browser.js("document.body.classList.contains('searching-all')") is True


def test_matches_keep_the_sites_songs_and_the_status_your_songs_alone(cfg, live, browser):  # noqa: F811
    base, _, _ = live
    sites(cfg, ug=BILLY)
    harptabs(cfg)
    library(cfg, ("Billy Joel", "Honesty"))  # yours, wanted, with nothing yet
    browser.open(base + "#show=found&inst=harmonica")
    search(browser, "billy joel")
    harps = [["Billy Joel", [["Piano Man", "ug+harptabs"], ["Vienna!", "harptabs"], ["She's Always a Woman", "harptabs"]]]]
    assert browser.wait(f"{answer_to('billy joel')} && {same(LINES, harps)}"), browser.js(LINES)
    assert browser.js(f"{NOTE}.firstChild.textContent") == "With harmonica tab · yours here: found"


def test_what_the_matches_hide_whole_is_said_with_show_all(cfg, live, browser):  # noqa: F811
    base, _, _ = live
    sites(cfg, ug=BILLY)
    harptabs(cfg)
    browser.open(base + "#inst=score")  # no site has a score of his
    search(browser, "billy joel")
    said = "document.querySelector('#results .filtered-out')"
    assert browser.wait(f"{answer_to('billy joel')} && !!{said}")
    assert browser.js(f"{said}.querySelector('p').textContent") == "Nothing with score for “billy joel”."
    assert browser.js(LINES) == [] and browser.js(STATUS).startswith("Nothing with score")
    browser.click("#results .filtered-out button")  # Show all
    assert browser.wait(f"{LINES}.length === 1 && {LINES}[0][1].length === 4"), browser.js(LINES)
    assert browser.js(f"{said}") is None and "inst=" not in browser.js("location.hash")


def test_on_a_phone_the_sheet_opens_over_the_results_and_its_show_n_songs_counts_them(cfg, live, phone):  # noqa: F811
    base, _, _ = live
    sites(cfg, ug=BILLY)
    harptabs(cfg)
    phone.open(base)
    search(phone, "billy joel")
    assert phone.wait(f"{answer_to('billy joel')} && {LINES}.length === 1 && {LINES}[0][1].length === 4"), \
        phone.js(LINES)
    phone.click("#filter")
    assert phone.wait(f"{PANEL}.open && {PANEL}.matches(':modal')")
    assert phone.wait(f"Math.abs({PANEL}.getBoundingClientRect().bottom - innerHeight) <= 1")  # once it has slid up
    assert phone.js("document.getElementById('show-n').textContent") == "Show 4 songs"
    phone.click(CHIP.format("harmonica"))
    assert phone.wait("document.getElementById('show-n').textContent === 'Show 3 songs'"), \
        phone.js("document.getElementById('show-n').textContent")
    assert phone.js(f"{PANEL}.open") is True  # a tap filters, and the sheet stays
    phone.click("#show-n")
    assert phone.wait(f"!{PANEL}.open")
    assert phone.wait(f"{LINES}[0][1].map((l) => l[0]).join('|') === \"Piano Man|Vienna!|She's Always a Woman\""), \
        phone.js(LINES)
    assert phone.js("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize(("address", "show_all"), [("#inst=score", "#results .filtered-out button"),
                                                   ("#inst=harmonica", "#results p.filtered > button")],
                         ids=["nothing-with", "with"])
def test_show_all_pressed_from_the_keyboard_gives_the_focus_to_the_first_result(cfg, live, browser, address,  # noqa: F811
                                                                                show_all):
    # Show all under "Nothing with score for “billy joel”", and the results' head's: the button goes with what it
    # said, and the focus goes to the first of the results it shows, never lost to the page (the next Tab from its
    # top).
    base, _, _ = live
    sites(cfg, ug=BILLY)
    harptabs(cfg)
    browser.open(base + address)
    search(browser, "billy joel")
    button = json.dumps(show_all)
    assert browser.wait(f"{answer_to('billy joel')} && !!document.querySelector({button})")
    browser.js(f"document.querySelector({button}).focus()")
    browser.press("Enter")
    assert browser.wait(f"{LINES}.length === 1 && {LINES}[0][1].length === 4"), browser.js(LINES)
    assert browser.js("document.querySelector('#results article.line').contains(document.activeElement)"), \
        browser.js("[document.activeElement.tagName, document.activeElement.className]")
