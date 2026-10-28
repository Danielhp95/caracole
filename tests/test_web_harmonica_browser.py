"""How a harmonica tab is read, changed from its page, in Chromium: served by caracole serve, the page's Read as line
links its source to the server's page of readings (and a tab read by harptabs.com's own key, or shown as written, has
a "Change how it's read" link at its foot instead); from a file, no link; the readings page's form pins one, a command
queued, and its page says so once it is done."""

from __future__ import annotations

import threading
from pathlib import Path
from urllib.parse import quote

import pytest

from caracole import db
from caracole.render import render_all
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.rendered import fake_chordpro
from test_render_harmonica import keep_tab
from test_viewer_harptab_notation import SPOKEY
from test_web_harmonica import Pinning, load

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

STANDARD = "-4 -4 5 -5 6 -6 6 -5\nla la la la la la la la\n"  # read by harptabs.com's own key


@pytest.fixture
def served(cfg):
    """caracole serve on a free port, its queue running ``caracole harmonica`` as the real one does (Pinning): its
    address and the commands it ran."""
    runner = Pinning(cfg)
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False)
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", runner
    server.shutdown()
    server.server_close()
    queue.stop()


@pytest.fixture
def browser(tmp_path):
    try:
        page = Browser(tmp_path / "chrome", width=390, height=844, mobile=True)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    yield page
    page.close()


def kept(cfg, text: str, title: str = "Spokey Dokey"):
    """A song of Cowboy Bebop's with the harmonica tab ``text``, its page rendered; its page's library path."""
    conn = db.connect(cfg.db_path)
    try:
        song = add_song(conn, "Cowboy Bebop", title)
        keep_tab(conn, cfg, song, text)
        render_all(conn, cfg, load(cfg), runner=fake_chordpro)
        conn.commit()
    finally:
        conn.close()
    return f"Cowboy Bebop/{title}/harmonica-1.html"


LINKS = """[(() => { const a = document.getElementById('reading-src');
  return a ? [a.tagName, a.getAttribute('href'), a.textContent] : null; })(),
 (() => { const p = document.getElementById('reading-foot'), a = p && p.querySelector('a');
  return p ? [p.hidden, a.getAttribute('href'), a.textContent, a.getBoundingClientRect().height > 0] : null; })()]"""


def test_served_the_read_as_lines_source_opens_the_readings_and_one_is_pinned(cfg, served, browser):
    base, runner = served
    page = kept(cfg, SPOKEY)
    browser.open(f"{base}/{quote(page)}")
    assert browser.wait("document.documentElement.dataset.ready === '1'")
    source, foot = browser.js(LINKS)
    assert source == ["A", "/harmonica?page=" + quote(page, safe=""), "from the tab's own legend"]
    assert foot is None
    browser.js("window.before = true")
    browser.click("#reading-src")
    assert browser.wait("!window.before && location.pathname === '/harmonica'")
    listed = browser.js("[...document.querySelectorAll('li.reading')].map((li) => li.textContent.replace(/\\s+/g, ' ')"
                        ".trim())")
    assert listed[0].startswith("b blow · d draw · * bend · - joins · (h) hold · (w) wah Q 0.96 · now")
    browser.js("window.before = true")
    browser.js("[...document.querySelectorAll('button')].find((b) => b.textContent === 'Read it as letters').click()")
    assert browser.wait("!window.before && document.body.textContent.includes('Done: read as')", 15)
    said = browser.js("document.body.textContent.replace(/\\s+/g, ' ')")
    assert "Done: read as b blow · d draw · * bend · - joins, as you set it." in said
    assert runner.calls == [["harmonica", "--tab=harmonica-1.txt", "--as=letters", "--", "Cowboy Bebop",
                             "Spokey Dokey"]]
    browser.js("window.before = true")
    browser.js("[...document.querySelectorAll('a')].find((a) => a.textContent === 'Back to the tab').click()")
    assert browser.wait("!window.before && document.documentElement.dataset.ready === '1'")
    assert browser.js("document.getElementById('reading-src').textContent") == "as you set it"


def test_served_a_tab_in_harptabs_coms_own_notation_has_the_link_at_its_foot(cfg, served, browser):
    base, _ = served
    page = kept(cfg, STANDARD, "Standard Song")
    browser.open(f"{base}/{quote(page)}")
    assert browser.wait("document.documentElement.dataset.ready === '1'")
    source, foot = browser.js(LINKS)
    legend = browser.js("document.querySelector('.head .legend').textContent")
    assert source is None and legend.startswith("4 blow −4 draw −3′ bent (4 5) together")
    assert foot == [False, "/harmonica?page=" + quote(page, safe=""), "Change how it's read", True]
    browser.click("#reading-foot a")
    assert browser.wait("location.pathname === '/harmonica'")
    assert browser.js("document.querySelector('h1').textContent").startswith("How it's read")


def test_from_a_file_no_link_but_the_text(cfg, tmp_path):
    from helpers.browser import Browser as Own

    page = kept(cfg, STANDARD, "Standard Song")
    spokey = kept(cfg, SPOKEY)
    with Own(Path(tmp_path / "file-profile"), width=390, height=844, mobile=True) as b:
        b.open((cfg.library_dir / page).as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        standard = b.js(LINKS)
        b.open((cfg.library_dir / spokey).as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        legend = b.js(LINKS)
    assert standard[0] is None and standard[1][0] is True  # hidden
    assert legend[0] == ["SPAN", None, "from the tab's own legend"] and legend[1] is None
