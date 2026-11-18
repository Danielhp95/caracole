"""iReal Pro's forum's offline index in the library page's bar and on the lookup page, in a real browser.

A real ``caracole serve`` (as test_web_page_harptabs.py's ``live``) serves the page, whose bar searches as you type
and puts iReal Pro's charts in the artist groups with the other sites', the composer as their artist, a chart's title a
line, its mark; its queue runs ``FakeGet``. The index holds the captured sitemap's threads, the Jazz 1460 Standards
and Thad Jones's Groove Merchant thread read (test_search.py's ``ireal_index``), or the sitemap's threads alone, known
by their names (``ireal_sitemaps``), each a line under the by-line its name gives after the query, whose Fetch reads it.
"""

from __future__ import annotations

import pytest
from helpers.browser import CHROMIUM_MARKS
from test_web_page_harptabs import browser, live, search  # noqa: F401  (its fixtures: caracole serve, a Chromium)
from test_web_page_search import posted

from caracole import db

pytestmark = CHROMIUM_MARKS

THREAD = "https://forums.irealpro.com/threads/"
IR_ROWS = "[...document.querySelectorAll('#results .hit[data-source=\"ireal\"]')]"


def ireal(cfg):
    """iReal Pro's forum's index, as test_search.py makes it, and Jerome Richardson an artist Ultimate Guitar's index
    names: his unread thread's by-line."""
    from test_search import ireal_index, ug_artists

    conn = db.connect(cfg.db_path)
    ireal_index(conn)
    ug_artists(conn, "jerome-richardson")
    conn.commit()
    conn.close()


def sitemaps(cfg):
    """iReal Pro's forum's index as its sitemaps leave it, no thread read, as test_search.py makes it, and both Groove
    Merchant threads' composers artists Ultimate Guitar's index names."""
    from test_search import ireal_sitemaps, ug_artists

    conn = db.connect(cfg.db_path)
    ireal_sitemaps(conn)
    ug_artists(conn, "thad-jones", "jerome-richardson")
    conn.commit()
    conn.close()


def test_a_thread_known_by_its_name_alone_is_a_line_under_its_by_line_whose_fetch_reads_it(cfg, live, browser):  # noqa: F811
    # "groove merchant": no thread read, its two threads by their names, each a line under the name its slug gives
    # after the title, the IR mark, a thread not read yet; nothing posted before a Fetch, which looks the song up by
    # those names with the thread's address as the iReal pick.
    base, queue, _ = live
    sitemaps(cfg)
    search(browser, base, "groove merchant")
    assert browser.wait(f"{IR_ROWS}.length === 2")
    said = browser.js(f"{IR_ROWS}.map((h) => [h.querySelector('h3').textContent, h.dataset.source, "
                      "h.querySelector('.line-sources .source').dataset.source, h.textContent])")
    assert [s[:3] for s in said] == [["Groove Merchant", "ireal", "ireal"]] * 2
    assert "Thad Jones" in said[0][3] and "Jerome Richardson" in said[1][3]
    assert all("thread not read yet" in s[3] for s in said)
    assert queue.snapshot() == []  # a search asks no site, and nothing is posted before Fetch
    browser.js(f"{IR_ROWS}[1].querySelector('.line-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--ireal={THREAD}groove-merchant-jerome-richardson.14294/")
    assert args[-2:] == ("Jerome Richardson", "Groove Merchant")
    # A name the query is in the middle of says no by-line: a title alone, apart, its thread to open.
    search(browser, base, "merchant")
    alone = "#results .hit[data-source=\"ireal\"][data-hit^=\"ireal:\"]"
    assert browser.wait(f"Boolean(document.querySelector({alone!r}))")
    assert browser.js(f"document.querySelector({alone!r}).querySelector('h3').textContent") == \
        "Groove Merchant Thad Jones"
    assert "a thread not read yet, its name alone" in browser.js(f"document.querySelector({alone!r}).textContent")
    assert browser.js(f"document.querySelector({alone!r}).querySelector('.line-action a').href") == \
        f"{THREAD}groove-merchant-thad-jones.9518/"
    # The lookup page says it alike: a row to open; and a by-line's row, where its names come from.
    browser.open(base + "lookup?q=merchant")
    assert browser.wait(f"{IR_ROWS}.length === 2")
    assert browser.js(f"{IR_ROWS}[0].querySelector('.row-sub').textContent") == "A thread not read yet, its name alone"
    assert browser.js(f"{IR_ROWS}[0].querySelector('.row-action a').href") == \
        f"{THREAD}groove-merchant-thad-jones.9518/"
    browser.open(base + "lookup?q=groove+merchant")
    assert browser.wait(f"{IR_ROWS}.length === 2")
    assert "Named from the thread's name: caracole hasn't read it yet." in browser.js(f"{IR_ROWS}[1].textContent")
    assert queue.snapshot()[1:] == []  # the one Fetch pressed alone


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
    assert browser.wait(f"{IR_ROWS}.length === 2")  # Thad Jones's chart, then Jerome Richardson's thread by its name
    assert browser.js(f"{IR_ROWS}[0].querySelector('.row-title').textContent") == "Groove Merchant"
    assert "2 charts" in browser.js(f"{IR_ROWS}[0].textContent")
    assert "thread not read yet" in browser.js(f"{IR_ROWS}[1].textContent")
    browser.js(f"{IR_ROWS}[0].querySelector('.row-action button').click()")
    args = posted(queue)
    assert f"--ireal={THREAD}groove-merchant-thad-jones.9518/post-38106" in args
    assert args[-2:] == ("Thad Jones", "Groove Merchant")


@pytest.mark.parametrize("width", [390, 1280], ids=["phone", "laptop"])
def test_irealpros_lines_and_rows_keep_the_calm_pages_look(cfg, live, tmp_path, width):  # noqa: F811
    # Stage 1f's look (test_page_calm.py) on iReal Pro's lines and rows: no corner radius but the four (its IR mark's a
    # token, ``--radius-s``), no outline around the results, a title semi-bold, a key in muted bold letters.
    from helpers.targets import odd_radii
    from test_page_calm import calm_in
    from test_web_page_steps import driven

    base, _, _ = live
    ireal(cfg)
    with driven(tmp_path, width) as page:
        search(page, base, "misty")
        assert page.wait(f"{IR_ROWS}.filter((h) => h.checkVisibility()).length >= 1", timeout=20)
        # Misty Roses's and Misty Blue's threads, which no name caracole knows ends: the title-alone group, drawn too.
        alone = f"{IR_ROWS}.filter((h) => h.dataset.hit.startsWith('ireal:') && h.checkVisibility())"
        assert page.wait(f"{alone}.length === 2", timeout=20)
        mark = f"{IR_ROWS}[0].querySelector('.line-sources .source')"
        assert page.js(f"[{mark}.dataset.source, getComputedStyle({mark}).borderTopLeftRadius]") == ["ireal", "4px"]
        assert page.js(odd_radii()) == [], "the library page's search"
        calm_in(page, "the library page's search", {"#results .groups": 1, "results' titles": 3})
        page.open(base + "lookup?q=groove+merchant")
        assert page.wait(f"{IR_ROWS}.filter((h) => h.checkVisibility()).length === 2", timeout=20)
        assert page.js(odd_radii()) == [], "the lookup page"
        calm_in(page, "the lookup page", {".rows": 1, "lines": 1, "titles": 1})
