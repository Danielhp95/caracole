"""The library page's search mode (library.js ``searchMode``, ``enterSearch``, ``leaveSearch``, ``backFromSearch``),
in Chromium: the box, the ← at its left (``#leave``), Back, Escape in the empty box, × that clears and stays; served
by a real ``caracole serve`` or opened as the file."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_web_page_search import answer_to, browser, library, live, search, sites  # noqa: F401  (fixtures)

from caracole.library_page import build_library_page, write_library_page
from caracole.overrides import Overrides

from conftest import add_song

pytestmark = CHROMIUM_MARKS

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)
MODE = "document.body.classList.contains('search-mode')"
LEAVE_SHOWN = "document.getElementById('leave').checkVisibility()"
BOX = "document.getElementById('q')"
# A browser that refuses a step of its history (a local file's, in some browsers), and the page's errors meanwhile.
REFUSE = ("window.errors = []; addEventListener('error', (e) => errors.push(String(e.message)));"
          "history.pushState = () => { throw new DOMException('denied', 'SecurityError'); }")
# Every control a person can press that says "Back to your songs", by its name: its id.
NAMED_BACK = ("[...document.querySelectorAll('button, a[href], [role=button]')].filter((b) => b.checkVisibility() && "
              "(b.getAttribute('aria-label') || b.textContent.trim()) === 'Back to your songs').map((b) => b.id)")
BACK_ROW = ("[...document.querySelectorAll('#results button')].some((b) => "
            "b.textContent.trim() === 'Back to your songs')")
C_TANGANA = [("c-tangana", "los-tontos", 3), ("c-tangana", "tu-me-dejaste-de-querer", 5),
             ("c-tangana", "demasiadas-mujeres", 2)]
THEIR_NAME = "#results section.artist.folded article.line button.artist-search"  # one line: their name its overline


def opened(tmp_path, url, **size):
    try:
        page = Browser(tmp_path / "chrome", **size)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    page.open(url)
    return page


def the_file(conn, cfg):
    """The page as a file, with no caracole serve: three songs of yours, two of one artist's."""
    add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Radiohead", "Karma Police")
    add_song(conn, "Muse", "Hysteria")
    return write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW)).as_uri()


@pytest.fixture
def phone_page(conn, cfg, tmp_path):
    """The file, on a phone."""
    page = opened(tmp_path, the_file(conn, cfg), width=390, height=844, mobile=True)
    yield page
    page.close()


@pytest.fixture
def file_page(conn, cfg, tmp_path):
    """The file, on a laptop."""
    page = opened(tmp_path, the_file(conn, cfg))
    yield page
    page.close()


def test_focusing_the_empty_box_is_one_step_that_back_and_the_arrow_take_back(phone_page):
    n = phone_page.js("history.length")
    assert phone_page.js(f"[{MODE}, {LEAVE_SHOWN}]") == [False, False]  # at rest: no ←
    phone_page.js(f"{BOX}.focus()")
    assert phone_page.wait(MODE) and phone_page.js("history.length") == n + 1
    assert phone_page.js("history.state.search") == 1
    assert phone_page.js(LEAVE_SHOWN)
    phone_page.type("creep")
    assert phone_page.wait("location.hash === '#q=creep'")
    assert phone_page.js("history.length") == n + 1  # typing adds no step
    assert phone_page.js("history.state.search") == 1  # the address written in place keeps the step's marker
    phone_page.js("history.back()")
    assert phone_page.wait(f"!{MODE}") and phone_page.js(f"{BOX}.value") == ""
    assert phone_page.js("document.activeElement.id") != "q"
    assert phone_page.js(LEAVE_SHOWN) is False
    phone_page.js(f"{BOX}.focus()")
    assert phone_page.wait(MODE) and phone_page.js("history.length") == n + 1  # the step again, the one after gone
    phone_page.click("#leave")
    assert phone_page.wait(f"!{MODE}") and phone_page.js("history.state") is None
    assert phone_page.js("document.activeElement.id") != "q" and phone_page.js(LEAVE_SHOWN) is False


def test_a_blur_leaves_search_on_and_a_focus_then_adds_no_step(file_page):
    n = file_page.js("history.length")
    file_page.js(f"{BOX}.focus()")
    assert file_page.wait(MODE)
    file_page.js(f"{BOX}.blur()")
    assert file_page.js(f"[{MODE}, {LEAVE_SHOWN}]") == [True, True]
    file_page.js(f"{BOX}.focus()")
    assert file_page.js(f"[{MODE}, history.length, history.state.search]") == [True, n + 1, 1]


def test_the_arrow_leaves_search_from_any_number_of_steps_in(cfg, live, browser):  # noqa: F811
    base, queue, _ = live
    sites(cfg, ug=C_TANGANA)
    browser.open(base)
    n = browser.js("history.length")
    search(browser, "los tontos")
    assert browser.wait(f"{answer_to('los tontos')} && !!document.querySelector({json.dumps(THEIR_NAME)})")
    browser.click(THEIR_NAME)  # their name searches for them: a second step
    assert browser.wait(answer_to("C Tangana"))
    assert browser.js("[history.length, history.state.search]") == [n + 2, 2]
    browser.click("#leave")  # every step of the search taken back at once
    assert browser.wait(f"!{MODE}")
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.js(f"[{BOX}.value, history.state, location.hash, {LEAVE_SHOWN}]") == ["", None, "", False]
    assert browser.js("document.activeElement.id") != "q" and queue.snapshot() == []


def test_a_query_the_address_holds_is_search_and_the_arrow_leaves_it_from_a_step_after_it(conn, cfg, tmp_path):
    url = the_file(conn, cfg)
    page = opened(tmp_path, url + "#q=creep")
    try:
        n = page.js("history.length")
        assert page.js(f"[{MODE}, {LEAVE_SHOWN}, {BOX}.value]") == [True, True, "creep"]  # no step: none to take back
        page.click("#list section.artist.folded article.line button.artist-search")  # Creep's artist: one step
        assert page.wait(f"{BOX}.value === 'Radiohead'") and page.js("[history.length, history.state.search]") == [
            n + 1, 1]
        page.click("#leave")  # the step taken back, then out of the search the address had
        assert page.wait(f"!{MODE}")
        assert page.js(f"[{BOX}.value, location.hash, history.length]") == ["", "", n + 1]
        page.open(url + "?again#q=creep")
        page.click("#leave")  # no step at all: out of it in place
        assert page.wait(f"!{MODE}") and page.js(f"[{BOX}.value, location.hash]") == ["", ""]
    finally:
        page.close()


def test_clear_empties_the_box_and_keeps_the_focus_in_search(phone_page):
    n = phone_page.js("history.length")
    phone_page.js(f"{BOX}.focus()")
    phone_page.type("creep")
    assert phone_page.wait("!document.getElementById('clear').hidden")
    phone_page.click("#clear")
    assert phone_page.wait(f"{BOX}.value === ''")
    assert phone_page.js(f"[document.activeElement.id, {MODE}, {LEAVE_SHOWN}, history.length]") == [
        "q", True, True, n + 1]


def test_escape_in_the_empty_box_leaves_search(cfg, live, browser):  # noqa: F811
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    library(cfg, ("Radiohead", "Creep"), ("Oasis", "Wonderwall"))
    browser.open(base)
    n = browser.js("history.length")
    search(browser, "creep")
    assert browser.wait(f"{answer_to('creep')} && !document.getElementById('results').hidden")
    browser.press("Escape")  # as before: the sites' results closed, your songs it finds, the search kept
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.js(f"[{BOX}.value, {MODE}, document.activeElement.id]") == ["creep", True, "q"]
    browser.press("Escape")  # again: the search cleared, still searching
    assert browser.wait(f"{BOX}.value === ''")
    assert browser.js(f"[{MODE}, document.activeElement.id, history.length]") == [True, "q", n + 1]
    browser.press("Escape")  # in the empty box: out of the search, its step taken back
    assert browser.wait(f"!{MODE}") and browser.js("history.state") is None
    assert browser.js("document.activeElement.id") != "q" and browser.js(LEAVE_SHOWN) is False


def test_where_the_browser_refuses_a_step_search_still_comes_and_goes(file_page):
    n = file_page.js("history.length")
    file_page.js(REFUSE)
    file_page.js(f"{BOX}.focus()")
    assert file_page.wait(MODE) and file_page.js("[history.length, errors]") == [n, []]
    file_page.type("creep")
    file_page.click("#leave")  # no step to take back: out of the search in place
    assert file_page.wait(f"!{MODE}")
    assert file_page.js(f"[{BOX}.value, history.length, location.hash, errors]") == ["", n, "", []]


def test_a_tab_left_and_come_back_to_in_search_is_still_search(file_page):
    file_page.js(f"{BOX}.focus()")
    assert file_page.wait(MODE)
    file_page.click("#tab-sites")  # tabs.js's step, one more of the search's
    assert file_page.wait("window.caracoleTabs.current() === 'sites'")
    assert file_page.js("JSON.stringify(history.state)") == '{"tab":1,"search":2}'
    file_page.click("#tab-library")  # its step taken back: still searching, the box empty
    assert file_page.wait("window.caracoleTabs.current() === 'library'")
    assert file_page.js(f"[{MODE}, history.state.search]") == [True, 1]
    file_page.click("#leave")
    assert file_page.wait(f"!{MODE}") and file_page.js("history.state") is None


def test_no_row_over_the_results_says_back_to_your_songs_the_arrow_does(cfg, live, browser):  # noqa: F811
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    library(cfg, ("Radiohead", "Creep"))
    browser.open(base)
    search(browser, "creep")
    assert browser.wait(f"{answer_to('creep')} && !document.getElementById('results').hidden")
    assert browser.js(BACK_ROW) is False
    assert browser.js(NAMED_BACK) == ["leave"]
    # At the box's left, 44 × 44, in the muted colour; the text typed starts after it.
    seen = browser.js("""(() => { const l = document.getElementById('leave'), q = document.getElementById('q');
      const a = l.getBoundingClientRect(), b = q.getBoundingClientRect(), s = getComputedStyle(l);
      const p = document.createElement('p'); p.style.color = 'var(--muted)'; document.body.append(p);
      const muted = getComputedStyle(p).color; p.remove();
      return [a.left - b.left, a.top - b.top, a.width, a.height, s.color === muted,
              parseFloat(getComputedStyle(q).paddingLeft), l.querySelector('[aria-hidden=true]').textContent]; })()""")
    assert seen[0] <= 2 and 0 <= seen[1] <= 2 and seen[2:5] == [44, 44, True] and seen[5] >= 44, seen
    assert seen[6] == "←"
