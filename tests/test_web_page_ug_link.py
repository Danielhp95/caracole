"""An Ultimate Guitar link pasted into the library page's search box, on the page caracole serve serves, in a real
browser.

A UG link is no query: its own panel takes the results' place, nothing is searched for it, and a page caracole hasn't
read is read by itself, once (``POST /ug/link``: ``caracole ug --link``, run here in the queue's worker as the command
is, Ultimate Guitar being ``FakeUG``, helpers/ug_pages.py, behind ``_common.transport_for``). Its Fetch this version
posts the lookup a search's row posts, with the tab, which the queue records and doesn't run.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from unittest import mock
from urllib.parse import parse_qs

import httpx
import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.ug_links import SHAPES
from helpers.ug_pages import SONG_DONGYE_CHORDS_URL, SONG_DONGYE_TABS_URL, SONG_DONGYE_URL, FakeUG

from caracole import db
from caracole.commands import _common
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

pytestmark = CHROMIUM_MARKS  # every test here drives the page in Chromium

TAB = "https://tabs.ultimate-guitar.com/tab/"
FOUND = f"{TAB}4180894"
PASTE = ("(() => { const q = document.getElementById('q'); q.focus(); q.value = %s; "
         "q.dispatchEvent(new Event('input', { bubbles: true })); })()")
PANEL = "document.querySelector('#found .ug-panel')"
NOTE = f"{PANEL}.querySelector('.link-note')"


class Runner:
    """caracole serve's queue: ``caracole ug --link`` run as the command is, its lines its output; any other command
    (a lookup's ``caracole get``) recorded alone."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ran: list[tuple[str, ...]] = []
        self.hold = threading.Event()
        self.hold.set()

    def __call__(self, args, emit):
        from caracole.commands.ug import _read
        from caracole.ug_urls import read_link

        self.ran.append(tuple(args))
        if args[:1] != ("ug",):
            return 0
        self.hold.wait(30)
        with mock.patch("typer.echo", lambda message="", **k: emit(str(message))):
            _read(self.cfg, read_link(args[1].removeprefix("--link=")), progress=True)
        return 0


class Posted(list):
    """The path and body of each POST the server got, in order; ``next`` waits for the one after ``n``."""

    def next(self, n: int, timeout: float = 10.0) -> tuple[str, dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self) > n:
                return self[n]
            time.sleep(0.05)
        raise AssertionError(f"the page posted nothing after {n}")


@pytest.fixture
def ug(monkeypatch):
    site = FakeUG()
    monkeypatch.setattr(_common, "transport_for", lambda provider: httpx.MockTransport(site.handler))
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    return site


@pytest.fixture
def live(cfg, ug):
    runner = Runner(cfg)
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False,
                 timers={"poll": 100, "idle": 100, "undo": 100})
    posted = Posted()
    posted.read = []  # the addresses of every GET the server answered
    answer = app.handle

    def handle(request):
        if request.method == "POST":
            posted.append((request.target, {k: v[0] for k, v in parse_qs(request.body.decode()).items()}))
        else:
            posted.read.append(request.target)
        return answer(request)

    app.handle = handle
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", posted, runner
    runner.hold.set()
    server.shutdown()
    server.server_close()
    queue.stop()


@pytest.fixture
def browser(tmp_path):
    try:
        page = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    yield page
    page.close()


def paste(browser, text):
    """``text`` pasted into the search box: one input event, as a paste is."""
    browser.js(PASTE % json.dumps(text))


def cooling(cfg) -> None:
    from caracole.health import record_block

    conn = db.connect(cfg.db_path)
    try:
        record_block(conn, "ug", datetime.now(UTC), "403")
        conn.commit()
    finally:
        conn.close()


def test_a_pasted_tab_link_is_read_by_itself_once_and_fetch_keeps_that_version(cfg, live, ug, browser):
    base, posted, runner = live
    browser.open(base)
    paste(browser, FOUND)
    names = f"['artist', 'title'].map((n) => {PANEL}.querySelector(`input[name=${{n}}]`).value)"
    assert browser.wait(f"{PANEL} !== null && {names}.join('|') === '宋冬野|斑马斑马'", timeout=20), \
        (browser.js("document.getElementById('found').textContent"), posted, posted.read, runner.ran)
    assert [p for p, _ in posted] == ["/ug/link"] and posted[0][1]["url"] == FOUND  # read once, by itself
    assert ug.requests == [FOUND, SONG_DONGYE_CHORDS_URL, SONG_DONGYE_TABS_URL]
    assert browser.js(f"{PANEL}.querySelector('.yt-title').textContent") == "斑马 斑马 Banma Banma Zebra Zebra ↗"
    assert browser.js(f"{PANEL}.querySelector('.yt-meta').textContent") == (
        "Song Dongye (宋冬野) · Chords · version 1 · 4.8★ (120 votes)")
    assert browser.js(f"{PANEL}.querySelector('.yt-title a').href") == FOUND
    assert browser.js(f"{NOTE}.textContent") == "Check the name, then fetch this version."
    # A link is no words to search: no site search, no LaCuerda, no YouTube suggestion for it, no marks.
    assert not any(t.startswith("/api/search") for t in posted.read)
    assert browser.js("document.getElementById('bar-status').textContent") == "A tab on Ultimate Guitar"
    assert browser.js("document.getElementById('bar-counts').checkVisibility()") is False
    # Fetch this version: the lookup a search's row posts, with the tab pasted.
    browser.click("#found .ug-panel button[type=submit]")
    path, fields = posted.next(1)
    assert path == "/lookup" and (fields["artist"], fields["title"], fields["tab"]) == ("宋冬野", "斑马斑马", FOUND)
    assert browser.wait("(document.querySelector('#found .ug-panel .link-line .progress') || {}).textContent > ''")
    deadline = time.monotonic() + 10
    while not any(a[:1] == ("get",) for a in runner.ran) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert any(a[:1] == ("get",) and f"--tab={FOUND}" in a for a in runner.ran), runner.ran
    # Pasted again: known now, nothing more asked.
    paste(browser, "nada")
    assert browser.wait("!document.getElementById('results').classList.contains('link-mode')")
    paste(browser, f"{FOUND}?ref=share")
    assert browser.wait(f"{PANEL} !== null && {names}.join('|') === '宋冬野|斑马斑马'")
    assert [p for p, _ in posted].count("/ug/link") == 1 and len(ug.requests) == 3


def test_the_panel_says_reading_while_the_job_runs_and_names_the_tab_once_its_page_is_read(cfg, live, ug, browser):
    base, posted, runner = live
    runner.hold.clear()  # the job waits
    browser.open(base)
    paste(browser, FOUND)
    assert browser.wait(f"{PANEL} !== null && {NOTE}.textContent === 'Reading the tab page…'")
    assert browser.wait("document.querySelectorAll('#found .ug-panel input').length === 2")
    runner.hold.set()
    assert browser.wait(f"{NOTE}.textContent === 'Check the name, then fetch this version.'", timeout=20)


def test_an_artist_link_shows_their_songs_as_search_lines(cfg, live, ug, browser):
    base, posted, runner = live
    browser.open(base)
    paste(browser, f"{SONG_DONGYE_URL}?filter=chords")
    lines = f"[...{PANEL}.querySelectorAll('.link-hits .hit .line-title, .link-hits .hit .row-title')]"
    assert browser.wait(f"{PANEL} !== null && {lines}.length === 6", timeout=20), \
        browser.js("document.getElementById('found').textContent")
    titles = browser.js(f"{lines}.map((t) => t.textContent)")
    assert titles[:2] == ["斑马斑马", "董小姐"]
    assert browser.js(f"{PANEL}.querySelector('form').hidden") is True
    assert browser.js(f"{PANEL}.querySelector('.yt-meta').textContent") == "6 songs on Ultimate Guitar"
    assert browser.js("document.getElementById('bar-status').textContent") == "An artist on Ultimate Guitar"
    assert ug.requests == [SONG_DONGYE_CHORDS_URL, SONG_DONGYE_TABS_URL]


def test_a_link_ug_cant_be_read_now_says_why_and_offers_the_names_empty(cfg, live, ug, browser):
    cooling(cfg)
    base, posted, runner = live
    browser.open(base)
    paste(browser, FOUND)
    assert browser.wait(f"{PANEL} !== null && {NOTE}.textContent.startsWith('Not read now')")
    assert browser.js(f"{NOTE}.textContent").endswith("). Name it, then fetch this version.")
    assert "UG turned us back; no asks until " in browser.js(f"{NOTE}.textContent")
    assert browser.js(f"[...{PANEL}.querySelectorAll('input')].map((i) => i.value)") == ["", ""]
    assert posted == [] and ug.requests == []


def test_a_tab_of_a_type_caracole_keeps_nothing_of_says_so_and_offers_nothing(cfg, live, ug, browser):
    base, posted, runner = live
    browser.open(base)
    paste(browser, f"{TAB}metallica/one-guitar-pro-225441")
    assert browser.wait(f"{PANEL} !== null && {NOTE}.textContent.startsWith('Nothing to fetch')")
    assert browser.js(f"{NOTE}.textContent") == (
        "Nothing to fetch: it is a Guitar Pro file: caracole keeps UG's chords, tabs and ukulele chords alone.")
    assert browser.js(f"{PANEL}.querySelector('form').hidden") is True
    assert posted == [] and ug.requests == []


def test_the_box_reads_a_ug_link_in_every_shape_as_ug_urls_does(cfg, live, ug, browser):
    # helpers/ug_links.py's shapes, the same list test_ug_urls.py holds read_link to: a UG link is its panel, with the
    # kind, the page's path and the type library.js's ugLink read; anything else is words to search (a video's link, its
    # own panel). UG cools down, so no link is read.
    cooling(cfg)
    base, posted, runner = live
    browser.open(base)
    mode = "document.getElementById('results').classList.contains('link-mode')"
    normal = "String(%s).trim().replace(/\\s+/g, ' ')"
    for text, read in SHAPES:
        if not text.strip():
            continue
        paste(browser, "nada")  # words: the panel shown before goes, so the next is made afresh
        assert browser.wait(f"!{mode}")
        paste(browser, text)
        if read is not None:  # the page's path: its host, the server's to say (tabs for a tab, www for an artist)
            kind, url, _, type_ = read
            path = url.removeprefix("https://tabs.ultimate-guitar.com").removeprefix("https://www.ultimate-guitar.com")
            said = f"[{PANEL}.dataset.ugKind, {PANEL}.dataset.ugPath, {PANEL}.dataset.ugType]"
            assert browser.wait(f"{PANEL} !== null && {said}.join('|') === {json.dumps(f'{kind}|{path}|{type_ or ''}')}"
                                ), (text, browser.js(f"{PANEL} && {said}"))
        elif "youtube.com" in text:
            assert browser.wait(f"{mode} && {PANEL} === null && document.querySelector('#found .link-panel') !== null")
        else:
            query = normal % json.dumps(text)
            assert browser.wait(f"!{mode} && document.getElementById('found').dataset.query === {query}"), text
    assert posted == [] and ug.requests == []


def test_the_panel_names_the_tab_as_soon_as_its_page_is_read_before_its_artists_page(cfg, live, ug, browser):
    # The job's tab stage done (caracole serve's queue reads its progress lines), the panel asks /api/ug/link again:
    # the tab's names come while its artist's page is still being read.
    base, posted, runner = live
    artist_page = threading.Event()
    answer = ug.handler

    def handler(request):
        if str(request.url) == SONG_DONGYE_CHORDS_URL:
            artist_page.wait(20)
        return answer(request)

    ug.handler = handler
    try:
        browser.open(base)
        paste(browser, FOUND)
        names = f"['artist', 'title'].map((n) => {PANEL}.querySelector(`input[name=${{n}}]`).value)"
        assert browser.wait(f"{PANEL} !== null && {names}.join('|') === '宋冬野|斑马斑马'", timeout=20)
        assert not artist_page.is_set() and ug.requests == [FOUND]  # its artist's chords list still waits
    finally:
        artist_page.set()
