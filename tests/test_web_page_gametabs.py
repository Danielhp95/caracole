"""gametabs.net's offline index in the library page's bar and on the lookup page, in a real browser.

A real ``caracole serve`` (as test_web_page_harptabs.py's ``live``) serves the page, whose bar searches as you type
and puts gametabs.net's tracks in the artist groups with the other sites', the game as their artist, a track a line,
its mark and its instruments' badges; its queue runs ``FakeGet``. gametabs.net's index holds its captured sitemaps,
and Actraiser's and Hollow Knight's game pages read (test_search.py's ``gametabs_index``).
"""

from __future__ import annotations

from helpers.browser import CHROMIUM_MARKS
from test_web_page_harptabs import browser, live, search  # noqa: F401  (its fixtures: caracole serve, a Chromium)
from test_web_page_search import GROUPS, posted

from caracole import db

pytestmark = CHROMIUM_MARKS

GT = "https://gametabs.net/tabs/"
GT_ROWS = "[...document.querySelectorAll('#results .hit[data-source=\"gametabs\"]')]"


def gametabs(cfg):
    """gametabs.net's index, as test_search.py makes it."""
    from test_search import gametabs_index

    conn = db.connect(cfg.db_path)
    gametabs_index(conn)
    conn.commit()
    conn.close()


def test_a_games_tracks_are_its_group_each_a_line_whose_get_it_keeps_that_tab(cfg, live, browser):  # noqa: F811
    base, queue, _ = live
    gametabs(cfg)
    search(browser, base, "hollow knight")
    assert browser.wait(f"{GT_ROWS}.length >= 3")
    assert browser.js(GROUPS)[0].startswith("Hollow Knight")
    assert browser.js(f"{GT_ROWS}[0].querySelector('.line-sources .source').dataset.source") == "gametabs"
    assert "Guitar" in browser.js(f"{GT_ROWS}.map((h) => h.querySelector('.badge.instrument').textContent)")
    assert "on gametabs.net" in browser.js("document.getElementById('bar-status').textContent")
    assert queue.snapshot() == []  # a search asks no site
    browser.js(f"{GT_ROWS}.find((h) => h.querySelector('h3').textContent === 'Resting Grounds')"
               ".querySelector('.line-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--gametabs={GT}hollow-knight/resting-grounds")
    assert args[-2:] == ("Hollow Knight", "Resting Grounds")


def test_a_tracks_other_tab_is_under_its_dots(cfg, live, browser):  # noqa: F811
    base, queue, _ = live
    gametabs(cfg)
    search(browser, base, "resting grounds")
    assert browser.wait(f"{GT_ROWS}.length === 1")
    line = f"{GT_ROWS}[0]"
    browser.js(f"{line}.querySelector('.line-more').click()")
    tabs = browser.js(f"[...{line}.querySelectorAll('.line-panel .versions button')].map((b) => b.textContent)")
    assert [t.split(" · ")[0] for t in tabs] == ["Tab 1", "Tab 2"] and "by Christopher Larkin" in tabs[1]
    browser.js(f"[...{line}.querySelectorAll('.line-panel .versions button')][1].click()")
    args = posted(queue)
    assert f"--gametabs={GT}hollow-knight/resting-grounds-2" in args


def test_the_lookup_page_lists_gametabs_nets_tracks_last(cfg, live, browser):  # noqa: F811
    base, queue, _ = live
    gametabs(cfg)
    browser.open(base + "lookup?q=fillmore")
    assert browser.wait(f"{GT_ROWS}.length === 1")
    assert browser.js(f"{GT_ROWS}[0].querySelector('.row-title').textContent") == "Fillmore"
    assert "by Yuzo Koshiro" in browser.js(f"{GT_ROWS}[0].textContent")
    browser.js(f"{GT_ROWS}[0].querySelector('.row-action button').click()")
    args = posted(queue)
    assert f"--gametabs={GT}actraiser/fillmore" in args and args[-2:] == ("Actraiser", "Fillmore")
