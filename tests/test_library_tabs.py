"""tabs.js and the masthead's tab row, in Chromium: a thumb's tabs on a phone, the row scrolling sideways when they
don't fit, the chosen tab brought into its view; leaving Library a step Back returns from, the other tabs replacing
one another."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from helpers import browser
from helpers.browser import CHROMIUM_MARKS

from caracole.library_page import WebControls, build_library_page, write_library_page
from caracole.overrides import Overrides
from caracole.songbook import make_songbook, songbooks_file

from conftest import add_song

pytestmark = CHROMIUM_MARKS

NOW = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)
TABS = """(() => { const row = document.querySelector('.masthead .tabs');
  return { row: [row.scrollWidth, row.clientWidth, getComputedStyle(row).overflowX, row.getBoundingClientRect().left,
                 row.getBoundingClientRect().right],
    tabs: [...row.querySelectorAll('[role=tab]')].map((t) => { const r = t.getBoundingClientRect();
      return [t.id, r.height, parseFloat(getComputedStyle(t).paddingLeft), r.left, r.right, Math.round(r.top)]; }),
    page: document.documentElement.scrollWidth <= innerWidth }; })()"""
CURRENT = "window.caracoleTabs.current()"
MARKED = "Boolean(history.state && history.state.tab)"  # tabs.js's entry, rule 1's marker


def library(conn, cfg, served=False):
    """The page with two songs, as a file: caracole serve's markup (``served``: Journal among its tabs) or the plain
    file's (three tabs)."""
    add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Muse", "Hysteria")
    controls = WebControls(csrf="tok") if served else None
    return write_library_page(cfg.library_dir, build_library_page(
        conn, cfg, Overrides(), NOW, controls=controls)).as_uri()


@pytest.mark.parametrize("width", [320, 390])
@pytest.mark.parametrize("sync", ["tab", None])  # five tabs (caracole serve's, Share last), or four
def test_on_a_phone_each_tab_is_48px_tall_and_a_row_too_wide_scrolls_on_its_own(conn, cfg, tmp_path, width, sync):
    served = write_library_page(cfg.library_dir, build_library_page(
        conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", active=1, sync=sync)))
    with browser.Browser(tmp_path / "chrome", width=width, height=844, mobile=True) as phone:
        phone.open(served.as_uri())
        assert phone.js("matchMedia('(pointer: coarse)').matches")
        seen = phone.js(TABS)
        assert all(h >= 48 and pad >= 10 for _, h, pad, *_ in seen["tabs"]), seen
        assert len({top for *_, top in seen["tabs"]}) == 1 and seen["page"], seen  # one row, the page never sideways
        assert seen["row"][2] == "auto"
        if sync == "tab":
            assert seen["row"][0] > seen["row"][1]  # five don't fit: the row scrolls
            phone.js("window.caracoleTabs.show('sync')")  # the last, past the row's edge: chosen, it comes into view
            left, right = phone.js("(() => { const r = document.getElementById('tab-sync').getBoundingClientRect(); "
                                   "return [r.left, r.right]; })()")
            assert seen["row"][3] - 0.5 <= left and right <= seen["row"][4] + 0.5


@pytest.mark.parametrize("served", [True, False])  # the served markup (Journal) or the plain file (three tabs)
def test_leaving_library_is_one_step_back_and_the_other_tabs_replace_it(conn, cfg, tmp_path, served):
    url = library(conn, cfg, served)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url + "#sort=title")
        n = page.js("history.length")
        page.click("#tab-sites")
        assert page.wait(f"{CURRENT} === 'sites'") and page.js("history.length") == n + 1
        assert page.js("history.state && history.state.tab") == 1  # rule 1's marker
        assert page.js("[...new URLSearchParams(location.hash.slice(1))].sort().join()") == "sort,title,tab,sites"
        page.click("#tab-songbooks")  # between other tabs: replaced
        assert page.wait(f"{CURRENT} === 'songbooks'") and page.js("history.length") == n + 1
        assert page.js("history.state && history.state.tab") == 1  # a replace keeps the entry's marker
        page.js("history.back()")
        assert page.wait(f"{CURRENT} === 'library'") and page.js("location.hash") == "#sort=title"
        assert page.js("document.querySelector('#list section.flat') !== null")  # the list as its address had it
        assert page.js(MARKED) is False
        page.click("#tab-sites")
        page.click("#tab-library")  # Library pressed: the step taken back, no step added
        assert page.wait(f"{CURRENT} === 'library'") and page.js("history.length") == n + 1
        assert page.js(f"[{MARKED}, location.hash]") == [False, "#sort=title"]
        # Nothing of the page's left to go back to: the page before it (the browser's blank one here), or none.
        page.js("window.before = true; setTimeout(() => history.back(), 0)")
        assert page.wait("window.before === undefined && document.readyState === 'complete'")


def test_the_tabs_keys_leave_library_with_a_step_and_come_back_with_it(conn, cfg, tmp_path):
    url = library(conn, cfg)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url)
        n = page.js("history.length")
        state = f"[{CURRENT}, document.activeElement.id, history.length, {MARKED}]"
        page.js("document.getElementById('tab-library').focus()")
        page.press("ArrowRight")  # Songbooks: a step
        assert page.js(state) == ["songbooks", "tab-songbooks", n + 1, True]
        page.press("ArrowRight")  # Sites: replaced
        assert page.js(state) == ["sites", "tab-sites", n + 1, True]
        page.press("Home")  # Library: the step taken back, the focus on its tab once it shows
        assert page.wait(f"{CURRENT} === 'library' && document.activeElement.id === 'tab-library'")
        assert page.js(state) == ["library", "tab-library", n + 1, False] and page.js("location.hash") == ""
        page.press("End")  # and out again: a step again, the one before it gone
        assert page.js(state) == ["sites", "tab-sites", n + 1, True]
        page.press("ArrowLeft")
        page.press("ArrowLeft")  # Library by ←
        assert page.wait(f"{CURRENT} === 'library' && document.activeElement.id === 'tab-library'")
        assert page.js(state) == ["library", "tab-library", n + 1, False]


def test_an_address_that_names_a_tab_opens_it_with_no_step(conn, cfg, tmp_path):
    url = library(conn, cfg)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url)
        n = page.js("history.length")
        page.open(url + "?again#tab=sites")  # a document of its own, one entry more: the browser's
        assert page.wait(f"{CURRENT} === 'sites'")
        assert page.js(f"[history.length, location.hash, {MARKED}]") == [n + 1, "#tab=sites", False]
        page.click("#tab-library")  # no step left Library here: the tab changes in place
        assert page.wait(f"{CURRENT} === 'library'")
        assert page.js("[history.length, location.hash]") == [n + 1, ""]


def test_where_the_browser_refuses_a_step_the_tabs_change_all_the_same(conn, cfg, tmp_path):
    url = library(conn, cfg)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url)
        n = page.js("history.length")
        page.js("window.errors = []; addEventListener('error', (e) => errors.push(String(e.message)));"
                "history.pushState = () => { throw new DOMException('denied', 'SecurityError'); }")
        page.click("#tab-sites")
        assert page.wait(f"{CURRENT} === 'sites'") and page.js("location.hash") == "#tab=sites"
        page.click("#tab-library")  # no step was taken: replaced back
        assert page.wait(f"{CURRENT} === 'library'")
        assert page.js("[history.length, location.hash]") == [n, ""]
        assert page.js("errors") == []


def test_a_step_out_of_library_in_search_mode_is_one_more_of_its_steps(conn, cfg, tmp_path):
    url = library(conn, cfg)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url)
        page.js("document.body.classList.add('search-mode'); history.replaceState({ search: 2 }, '', location.href)")
        page.click("#tab-sites")
        assert page.wait(f"{CURRENT} === 'sites'")
        assert page.js("JSON.stringify(history.state)") == '{"tab":1,"search":3}'
        page.click("#tab-songbooks")  # a replace never touches it
        assert page.js("JSON.stringify(history.state)") == '{"tab":1,"search":3}'
        page.click("#tab-library")
        assert page.wait(f"{CURRENT} === 'library'") and page.js("JSON.stringify(history.state)") == '{"search":2}'


def test_library_pressed_twice_before_back_is_heard_takes_one_step_back(conn, cfg, tmp_path):
    url = library(conn, cfg)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url)
        n = page.js("history.length")
        page.click("#tab-sites")
        assert page.wait(f"{CURRENT} === 'sites'")
        page.js("window.before = true; const t = document.getElementById('tab-library'); t.click(); t.click()")
        assert page.wait(f"window.before === true && {CURRENT} === 'library'")  # still this page: one step back
        assert page.js(f"[history.length, {MARKED}, location.hash]") == [n + 1, False, ""]
        page.js("history.forward()")  # the step out of it is still the one after
        assert page.wait(f"{CURRENT} === 'sites'") and page.js("window.before") is True


def test_forward_to_the_step_out_of_library_and_library_pressed_is_back_again(conn, cfg, tmp_path):
    url = library(conn, cfg)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url)
        n = page.js("history.length")
        page.click("#tab-sites")
        assert page.wait(f"{CURRENT} === 'sites'")
        page.js("history.back()")
        assert page.wait(f"{CURRENT} === 'library'")
        page.js("history.forward()")  # the step out of the library again, by Forward
        assert page.wait(f"{CURRENT} === 'sites'") and page.js(MARKED) is True
        page.js("window.before = true")
        page.click("#tab-library")  # Back, as from the step taken by hand: no Library entry twice
        assert page.wait(f"window.before === true && {CURRENT} === 'library'")  # this document still
        assert page.js(f"[history.length, {MARKED}, location.hash]") == [n + 1, False, ""]
        page.js("history.forward()")  # and the step is still after it
        assert page.wait(f"{CURRENT} === 'sites'") and page.js("window.before") is True
        page.click("#tab-library")
        assert page.wait(f"window.before === true && {CURRENT} === 'library'")
        # Back once more is never a dead press on a second Library entry: nothing of the page's is left before it.
        page.js("setTimeout(() => history.back(), 0)")
        assert page.wait("window.before === undefined && document.readyState === 'complete'")


def test_a_songbook_opened_keeps_the_step_out_of_library(conn, cfg, tmp_path):
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    url = library(conn, cfg)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url)
        page.click("#tab-songbooks")
        assert page.wait(f"{CURRENT} === 'songbooks'") and page.js(MARKED) is True
        page.click('#songbooks .book-line[data-book="Campfire"]')  # songbooks.js writes book= in place
        assert page.wait("location.hash.includes('book=Campfire')")
        assert page.js("history.state && history.state.tab") == 1


def test_where_the_browser_refuses_back_the_library_tab_shows_the_library_all_the_same(conn, cfg, tmp_path):
    url = library(conn, cfg)
    with browser.Browser(tmp_path / "chrome") as page:
        page.open(url)
        page.click("#tab-sites")
        assert page.wait(f"{CURRENT} === 'sites'")
        page.js("window.errors = []; addEventListener('error', (e) => errors.push(String(e.message)));"
                "history.back = () => { throw new DOMException('denied', 'SecurityError'); }")
        page.click("#tab-library")  # no Back on its way: the tab changes in place
        assert page.wait(f"{CURRENT} === 'library'") and page.js("[location.hash, errors]") == ["", []]
        page.click("#tab-sites")  # and the next press isn't held for a Back that never came
        page.click("#tab-library")
        assert page.wait(f"{CURRENT} === 'library'")
