"""iReal Pro's forum's offline index in the library page's bar and on the lookup page, in a real browser.

A real ``caracole serve`` (as test_web_page_harptabs.py's ``live``) serves the page, whose bar searches as you type
and puts iReal Pro's charts in the artist groups with the other sites', the composer as their artist, a chart's title a
line, its mark; its queue runs ``FakeGet``. The index holds the captured sitemap's threads, the Jazz 1460 Standards
and Thad Jones's Groove Merchant thread read (test_search.py's ``ireal_index``).
"""

from __future__ import annotations

from helpers.browser import CHROMIUM_MARKS
from test_web_page_harptabs import browser, live, search  # noqa: F401  (its fixtures: caracole serve, a Chromium)
from test_web_page_search import posted

from caracole import db

pytestmark = CHROMIUM_MARKS

THREAD = "https://forums.irealpro.com/threads/"
IR_ROWS = "[...document.querySelectorAll('#results .hit[data-source=\"ireal\"]')]"


def ireal(cfg):
    """iReal Pro's forum's index, as test_search.py makes it."""
    from test_search import ireal_index

    conn = db.connect(cfg.db_path)
    ireal_index(conn)
    conn.commit()
    conn.close()


def test_a_standards_chart_is_a_line_under_its_composer_whose_get_it_keeps_it_as_the_sheet(cfg, live, browser):  # noqa: F811
    base, queue, _ = live
    ireal(cfg)
    search(browser, base, "misty")
    assert browser.wait(f"{IR_ROWS}.length >= 1")
    line = f"{IR_ROWS}.find((h) => h.querySelector('h3').textContent === 'Misty')"
    assert browser.js(f"{line}.querySelector('.line-sources .source').dataset.source") == "ireal"
    assert "iReal Pro chart" in browser.js(f"{line}.textContent")
    assert queue.snapshot() == []  # a search asks no site
    browser.js(f"{line}.querySelector('.line-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--ireal={THREAD}jazz-1460-standards.12753/post-31492")
    assert args[-2:] == ("Erroll Garner", "Misty")


def test_a_line_whose_fetch_keeps_the_chart_is_irealpros_beside_a_guitar_pro_file(cfg, live, browser):  # noqa: F811
    # Its source is the one its Fetch keeps: iReal Pro's chart, never gtptabs.com's file beside it.
    from caracole.gtptabs import parse_page_url

    base, queue, _ = live
    ireal(cfg)
    conn = db.connect(cfg.db_path)
    conn.execute("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) "
                 "VALUES (?, ?, ?, ?, ?, '1')", tuple(parse_page_url("https://gtptabs.com/tabs/5/erroll-garner/misty.html")))
    conn.commit()
    conn.close()
    search(browser, base, "misty")
    line = f"{IR_ROWS}.find((h) => h.querySelector('h3').textContent === 'Misty')"
    assert browser.wait(f"Boolean({line})")
    assert "Guitar Pro file" in browser.js(f"{line}.textContent")
    browser.js(f"{line}.querySelector('.line-action button').click()")
    assert posted(queue)[:3] == ("get", "--progress", f"--ireal={THREAD}jazz-1460-standards.12753/post-31492")


def test_the_lookup_page_lists_irealpros_charts_last(cfg, live, browser):  # noqa: F811
    base, queue, _ = live
    ireal(cfg)
    browser.open(base + "lookup?q=groove+merchant")
    assert browser.wait(f"{IR_ROWS}.length === 1")
    assert browser.js(f"{IR_ROWS}[0].querySelector('.row-title').textContent") == "Groove Merchant"
    assert "2 charts" in browser.js(f"{IR_ROWS}[0].textContent")
    browser.js(f"{IR_ROWS}[0].querySelector('.row-action button').click()")
    args = posted(queue)
    assert f"--ireal={THREAD}groove-merchant-thad-jones.9518/post-38106" in args
    assert args[-2:] == ("Thad Jones", "Groove Merchant")
