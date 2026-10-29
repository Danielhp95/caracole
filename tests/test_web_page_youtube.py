"""A sheet from a YouTube video, asked for on the library page caracole serve serves, in a real browser.

A song with no human sheet has Sheet from a YouTube video under its line's "⋯": the video's address and Make the
sheet, which posts ``POST /youtube`` with the song, in place, its line then saying how the job goes, its stages as
steps. The request form has a YouTube video field, whose request makes the sheet in place of a lookup. Where this
caracole makes no such sheet, the card and the form say why, and offer nothing. A real ``caracole serve`` serves
the page; its queue runs ``FakeSheet``, which says the job's stages and makes nothing.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.fake_ytdlp import FakeYtDlp

import caracole.youtube_fetch as yf
from caracole import db
from caracole.config import AutochordsConfig
from caracole.get import PROGRESS_PREFIX
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here drives the page in Chromium

VIKINGOS = "lzN7Thn3FV4"
PASTED = f"https://www.youtube.com/watch?v={VIKINGOS}&pp=ygUQdmlraW5nb3MgdmVnYW5vcw%3D%3D"


JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x0b\x08\x01\x68\x01\xe0\x01\x01\x11\x00\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x12\x34\xff\xd9")


class FakeSheet:
    """``caracole youtube --sheet --progress``: its stages said, up to the chords, which run until ``hold`` is set.
    ``caracole youtube --search --progress`` (``searches``: the queries asked), once ``cfg`` is set: what the real one
    keeps, the video the owner gave as YouTube's first and its thumbnail, at once."""

    def __init__(self):
        self.ran: list[tuple[str, ...]] = []
        self.searches: list[str] = []
        self.hold = threading.Event()
        self.cfg = None

    def search(self, query, stage):
        from caracole.youtube_search import KV_PREFIX, query_key, thumb_path

        self.searches.append(query)
        stage("video", "running")
        conn = db.connect(self.cfg.db_path)
        try:
            from caracole.db import kv_set_json

            kv_set_json(conn, KV_PREFIX + query_key(query), {
                "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "query": query, "thumb": True,
                "video": {"id": VIKINGOS, "title": "Somos vikingos veganos - Hyperfanes", "channel": "kintanedu",
                          "duration": 222.0, "url": f"https://www.youtube.com/watch?v={VIKINGOS}"}})
            conn.commit()
        finally:
            conn.close()
        path = thumb_path(self.cfg, VIKINGOS)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(JPEG)
        stage("video", "done")
        stage("thumbnail", "done")
        return 0

    def __call__(self, args, emit):
        self.ran.append(tuple(args))

        def stage(name, state, detail=""):
            emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

        searching = next((a.split("=", 1)[1] for a in args if a.startswith("--search=")), None)
        if searching is not None:
            return self.search(searching, stage)
        for name in ("song", "audio", "lyrics"):
            stage(name, "running")
            stage(name, "done")
        stage("chords", "running")
        self.hold.wait(30)
        stage("chords", "done", "chords over LRCLIB's timed lyrics")
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
def able(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    return replace(cfg, ytdlp_bin=FakeYtDlp(tmp_path / "bin").bin, autochords=AutochordsConfig(**files))


def serve(cfg, runner):
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False,
                 timers={"poll": 100, "idle": 100, "undo": 100})
    posted = Posted()
    answer = app.handle

    def handle(request):
        if request.method == "POST":
            posted.append((request.target, {k: v[0] for k, v in parse_qs(request.body.decode()).items()}))
        return answer(request)

    app.handle = handle
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    return server, queue, f"http://127.0.0.1:{server.server_address[1]}/", posted


@pytest.fixture
def sheet():
    made = FakeSheet()
    yield made
    made.hold.set()


@pytest.fixture
def live(able, sheet):
    sheet.cfg = able
    server, queue, base, posted = serve(able, sheet)
    yield base, posted
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


def wanted(cfg):
    conn = db.connect(cfg.db_path)
    try:
        song = add_song(conn, "Nick Cani", "Vikingos veganos")
        conn.commit()
        return song
    finally:
        conn.close()


def line(song) -> str:
    return f'article.line[data-id="{song.id}"]'


def opened(browser, song) -> None:
    assert browser.wait(f"document.querySelector({json.dumps(line(song) + ' .line-more')}) !== null")
    browser.click(line(song) + " .line-more")


def test_a_songs_card_makes_its_sheet_from_the_video_pasted_and_its_line_follows_it(able, live, sheet, browser):
    base, posted = live
    song = wanted(able)
    browser.open(base)
    opened(browser, song)
    form = json.dumps(line(song) + " form.youtube-sheet")
    assert browser.wait(f"document.querySelector({form}) !== null")
    browser.js(f"document.querySelector({form} + ' input[name=youtube]').focus()")
    browser.type(PASTED)
    browser.click(line(song) + ' form.youtube-sheet button[type="submit"]')
    path, fields = posted.next(0)
    assert (path, fields) == ("/youtube", {"csrf": "tok", "song": str(song.id), "youtube": PASTED})
    # The line says how it goes, the stages as steps, the form gone while it runs.
    progress = json.dumps(line(song) + " .progress")
    assert browser.wait(f"(document.querySelector({progress}) || {{}}).textContent === "
                        "'Working out the chords…·3 of 5 done'"), \
        browser.js(f"(document.querySelector({progress}) || {{}}).textContent")
    chips = browser.js(f"[...document.querySelectorAll({json.dumps(line(song) + ' .step-chip')})]"
                       ".map((c) => c.textContent)")
    assert chips == ["✓ Song: done", "✓ Audio YouTube: done", "✓ Lyrics: done", "Chords: running", "PDF: waiting"]
    assert browser.js(f"document.querySelector({form})") is None
    assert sheet.ran == [("youtube", "--sheet", "--progress", f"--url=https://www.youtube.com/watch?v={VIKINGOS}",
                          "--song=Nick Cani - Vikingos veganos")]


def test_the_request_form_sends_its_youtube_video(able, live, sheet, browser):
    # The song searched for and not found: Request opens the form, filled in from the query; the video pasted.
    from test_web_page_search import answer_to, search, sites

    base, posted = live
    sites(able, ug=[("radiohead", "creep", 4)])
    browser.open(base)
    search(browser, "Nick Cani - Vikingos veganos")
    request = "document.querySelector('#results section.nothing .line-action button')"
    assert browser.wait(f"{answer_to('Nick Cani - Vikingos veganos')} && {request} !== null")
    browser.js(f"{request}.click()")
    assert browser.wait("document.getElementById('request-box').open")
    fields = browser.js("['artist', 'title'].map((n) => document.querySelector(`form.request-form [name=${n}]`).value)")
    assert fields == ["Nick Cani", "Vikingos veganos"]
    browser.js("document.querySelector('form.request-form input[name=youtube]').focus()")
    browser.type(PASTED)
    browser.click('form.request-form button[type="submit"]')
    path, fields = posted.next(0)
    assert path == "/request" and fields["youtube"] == PASTED and fields["artist"] == "Nick Cani"
    # A line under the bar says how it goes, and the form is empty again.
    assert browser.wait("(document.querySelector('#requested-list .progress') || {}).dataset.tone === 'running'")
    assert browser.js("document.querySelector('form.request-form input[name=youtube]').value") == ""


def test_where_no_sheet_can_be_made_the_form_says_why_and_nothing_offers_one(cfg, sheet, browser, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    server, queue, base, _ = serve(cfg, sheet)
    try:
        song = wanted(cfg)
        browser.open(base)
        opened(browser, song)
        assert browser.wait(f"!document.querySelector({json.dumps(line(song) + ' .line-panel')}).hidden")
        assert browser.js(f"document.querySelector({json.dumps(line(song) + ' .youtube-sheet')})") is None
        assert browser.js("document.querySelector('form.request-form input[name=youtube]')") is None
        hints = browser.js("[...document.querySelectorAll('form.request-form .hint')].map((p) => p.textContent)")
        assert "No sheets from YouTube here: auto-chords isn't installed." in hints, hints
    finally:
        server.shutdown()
        server.server_close()
        queue.stop()


def test_a_search_with_no_sheet_suggests_youtubes_first_video_and_fills_the_request_form_with_it(able, live, sheet,
                                                                                               browser):
    # The query settles: the page asks YouTube once (POST /youtube/search, a job), then shows the video's row, its
    # thumbnail from caracole serve; Make the sheet fills the request form in, for the owner to send.
    from test_web_page_search import answer_to, search, sites

    base, posted = live
    sites(able, ug=[("radiohead", "creep", 4)])
    browser.open(base)
    search(browser, "Nick Cani - Vikingos veganos")
    row = "document.querySelector('#found .youtube-row')"
    assert browser.wait(f"{answer_to('Nick Cani - Vikingos veganos')} && {row} !== null", timeout=20), \
        browser.js("document.getElementById('found').textContent")
    assert sheet.searches == ["Nick Cani - Vikingos veganos"]
    assert [p for p, _ in posted] == ["/youtube/search"]
    assert browser.wait(f"{row}.querySelector('img.yt-thumb') !== null && "
                        f"{row}.querySelector('img.yt-thumb').naturalWidth === 480")  # its thumbnail, served
    assert browser.js(f"{row}.querySelector('img').getAttribute('src')") == f"/youtube/thumb/{VIKINGOS}.jpg"
    assert browser.js(f"{row}.querySelector('.yt-meta').textContent") == "kintanedu · 3:42"
    title = browser.js(f"{row}.querySelector('.yt-title a').getAttribute('href')")
    assert title == f"https://www.youtube.com/watch?v={VIKINGOS}"
    browser.click("#found .youtube-row button")
    assert browser.wait("document.getElementById('request-box').open")
    fields = browser.js("['artist', 'title', 'youtube'].map((n) => "
                        "document.querySelector(`form.request-form [name=${n}]`).value)")
    assert fields == ["Nick Cani", "Vikingos veganos", f"https://www.youtube.com/watch?v={VIKINGOS}"]
    assert len(posted) == 1  # nothing sent until you press Request
    # Searched again, the row comes back from what was kept ("found": the page sends nothing for it).
    browser.press("Escape")
    search(browser, "vikingos veganos - nick cani")
    assert browser.wait(f"{answer_to('vikingos veganos - nick cani')} && {row} !== null")
    assert sheet.searches == ["Nick Cani - Vikingos veganos"] and len(posted) == 1
