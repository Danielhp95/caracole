"""A song's lyrics transcribed from its audio, asked for on the library page caracole serve serves, in a real browser.

A song offered a transcription (its audio from YouTube, every lyrics site missed: the served data's
``server.transcribe``) has Transcribe the lyrics on its card, and on its request that ended Ready in the Requests
tab: one press posts ``POST /transcribe`` with the song, in place, its line then saying how the job goes, its stages
as steps, and the offer is gone. Where this caracole transcribes nothing, no card offers it. A real ``caracole serve``
serves the page; its queue runs ``FakeTranscribe``, which says the job's stages and makes nothing but the sheet's
file.
"""

from __future__ import annotations

import json
import threading
import time

import pytest
from helpers import cards
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_autochords_transcript import youtube_song
from test_web_page_steps import bar_of, wait_for, words_of
from test_web_page_youtube import serve

import caracole.youtube_fetch as yf
from caracole import db
from caracole.get import PROGRESS_PREFIX
from caracole.library import song_dir
from caracole.web.jobs import YOUTUBE_SHEET, youtube_sheet_steps

pytestmark = CHROMIUM_MARKS  # every test here drives the page in Chromium

DISPLAY = "Nick Cani - Vikingos veganos"


class FakeTranscribe:
    """``caracole transcribe --progress``: its stages said, up to the words, which run until ``hold`` is set, then the
    song's auto sheet's PDF written (``cfg``'s library) and the rest said done. ``caracole youtube --sheet
    --progress``: a sheet made at once, chords only, its lyrics missed."""

    def __init__(self):
        self.ran: list[tuple[str, ...]] = []
        self.hold = threading.Event()
        self.cfg = None
        self.song = None

    def _sheet(self) -> None:
        folder = song_dir(self.cfg.library_dir, self.song)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sheet (auto).pdf").write_bytes(b"%PDF-1.4\n")

    def __call__(self, args, emit):
        self.ran.append(tuple(args))

        def stage(name, state, detail=""):
            emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

        emit(PROGRESS_PREFIX + json.dumps({"song": {"id": self.song.id, "display": self.song.display}}))
        if args[0] == "youtube":
            for name, detail in (("song", "in the book"), ("audio", "downloaded")):
                stage(name, "running")
                stage(name, "done", detail)
            stage("lyrics", "failed", "LRCLIB has no lyrics for it")
            self._sheet()
            for name, detail in (("chords", "chords only, no lyrics"), ("pdf", "made"), ("pages", "")):
                stage(name, "done", detail)
            return 0
        for name in ("song", "vocals"):
            stage(name, "running")
            stage(name, "done", "in the book" if name == "song" else "sung from 9.3 s, 4 stretches")
        stage("words", "running")
        self.hold.wait(30)
        stage("words", "done", "212 words in 31 lines (es), 3 dropped")
        self._sheet()
        for name, detail in (("chords", "chords over the transcribed lyrics"), ("pdf", "made"), ("pages", "")):
            stage(name, "done", detail)
        return 0


@pytest.fixture
def able(cfg, monkeypatch):
    """A caracole that transcribes (Whisper, its models and demucs-rs taken to be there), on the CPU."""
    monkeypatch.setattr(yf, "transcribe_problem", lambda cfg: None)
    monkeypatch.delenv("CARACOLE_TORCH_CUDA", raising=False)
    return cfg


def offered(cfg, tmp_path):
    """Vikingos veganos, its audio from YouTube and every lyrics site asked: offered a transcription."""
    conn = db.connect(cfg.db_path)
    try:
        return youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    finally:
        conn.close()


@pytest.fixture
def transcriber(able, tmp_path):
    made = FakeTranscribe()
    made.cfg, made.song = able, offered(able, tmp_path)
    yield made
    made.hold.set()


@pytest.fixture
def live(able, transcriber):
    server, queue, base, posted = serve(able, transcriber)
    yield base, posted, queue
    server.shutdown()
    server.server_close()
    transcriber.hold.set()  # a transcription still held lets go first: the queue stops at once
    queue.stop()


@pytest.fixture
def browser(tmp_path):
    try:
        page = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    yield page
    page.close()


def over(queue, job_id: int, timeout: float = 10.0) -> None:
    """Wait until the queue's job ``job_id`` is over."""
    deadline = time.monotonic() + timeout
    while queue.job(job_id).active:
        assert time.monotonic() < deadline, queue.job(job_id)
        time.sleep(0.05)


def line(song) -> str:
    return f'article.line[data-id="{song.id}"]'


def opened(browser, song) -> str:
    assert browser.wait(f"document.querySelector({json.dumps(line(song) + ' .line-more')}) !== null")
    browser.click(line(song) + " .line-more")
    return cards.open_card(browser, line(song))


def test_a_songs_card_offers_a_transcription_and_its_line_follows_it(able, live, transcriber, browser):
    base, posted, _ = live
    song = transcriber.song
    browser.open(base)
    card = opened(browser, song)
    form = json.dumps(card + " form.transcribe")
    assert browser.wait(f"document.querySelector({form}) !== null")
    assert browser.js(f"document.querySelector({form} + ' .hint').textContent") == (
        "From the audio, up to half an hour.")
    assert browser.js(f"document.querySelector({form} + ' button').textContent") == "Transcribe the lyrics"
    browser.click(card + ' form.transcribe button[type="submit"]')
    path, fields = posted.next(0)
    assert (path, fields) == ("/transcribe", {"csrf": "tok", "song": str(song.id), "identity": song.key})
    # The line is a bar of the job's steps while it runs (Song, Vocals, Words, Chords, PDF), the offer gone.
    wait_for(browser, bar_of(line(song)), ["done", "done", "running", "waiting", "waiting"])
    wait_for(browser, words_of(line(song)), ["Words", " · 3 of 5"])
    assert browser.js(f"document.querySelector({form})") is None
    assert transcriber.ran == [("transcribe", "--progress", f"--song={DISPLAY}")]
    # Ready: its line drawn again, its card open again, and no second offer: it was asked for already.
    transcriber.hold.set()
    assert browser.wait(f"(document.querySelector({json.dumps(line(song) + ' .progress')}) || {{}})"
                        ".dataset.tone === 'ready'")
    again = cards.card_js(line(song))  # the card drawn again from the song as it is now, open as it was
    assert browser.wait(f"{again} !== null && {again}.querySelector('.card-head') !== null")
    assert browser.js(f"{again}.querySelector('form.transcribe')") is None
    assert browser.js("document.querySelector('form.transcribe')") is None and len(posted) == 1


def test_a_ready_request_of_a_song_offered_one_offers_it_in_the_requests_tab(able, live, transcriber, browser):
    # A sheet from YouTube that ended Ready with chords only, its lyrics missed: its request offers the
    # transcription after its Ready line, and one press follows the new request, the offer gone.
    base, posted, queue = live
    song = transcriber.song
    sheet, _ = queue.submit(f"Sheet from YouTube: {DISPLAY}", YOUTUBE_SHEET + song.key,
                            youtube_sheet_steps(DISPLAY, "https://www.youtube.com/watch?v=XFkzRNyygfk"),
                            display=DISPLAY)
    over(queue, sheet.id)
    item = f"#req-{sheet.id}"
    browser.open(base + "#tab=requests")
    assert browser.wait(f"(document.querySelector({json.dumps(item + ' .req-says')}) || {{}}).textContent === 'Ready'")
    offer = json.dumps(item + " form.transcribe")
    assert browser.wait(f"document.querySelector({offer}) !== null")
    order = browser.js(f"[...document.querySelector({json.dumps(item)}).children].map((n) => n.className)")
    assert order.index("req-reason") < order.index("transcribe") < order.index("req-next"), order
    assert browser.js(f"document.querySelector({offer} + ' .hint').textContent") == (
        "From the audio, up to half an hour.")
    browser.click(item + ' form.transcribe button[type="submit"]')
    path, fields = posted.next(0)
    assert (path, fields) == ("/transcribe", {"csrf": "tok", "song": str(song.id), "identity": song.key})
    assert browser.wait(f"document.querySelector({offer}) === null")
    assert browser.wait("[...document.querySelectorAll('.req-group.now .req-song')]"
                        f".some((n) => n.textContent === {json.dumps(DISPLAY)})")
    assert transcriber.ran[-1] == ("transcribe", "--progress", f"--song={DISPLAY}")


def test_where_it_cant_run_no_card_offers_one(cfg, tmp_path, browser, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    made = FakeTranscribe()
    made.cfg, made.song = cfg, offered(cfg, tmp_path)
    server, queue, base, _ = serve(cfg, made)
    try:
        browser.open(base)
        card = opened(browser, made.song)
        assert browser.wait(f"!document.querySelector({json.dumps(card)}).hidden")
        assert browser.js(f"document.querySelector({json.dumps(card + ' form.transcribe')})") is None
        assert browser.js("document.querySelector('form.transcribe')") is None
    finally:
        made.hold.set()
        server.shutdown()
        server.server_close()
        queue.stop()
