"""A song's lyrics transcribed from its audio, asked for on the library page caracole serve serves, in a real browser.

A song offered a transcription (its audio from YouTube, every lyrics site missed: the served data's
``server.transcribe``) has Transcribe the lyrics on its card, and on its request that ended Ready in the Requests
tab: one press posts ``POST /transcribe`` with the song, in place, its line then saying how the job goes, its stages
as steps, and the offer is gone. Once a song's job ends the page reads the offer again (``GET /transcribe``), with no
reload: a sheet from a video that found no lyrics offers it at once, a transcription that failed on the GPU offers
it again. Where this caracole transcribes nothing, no card offers it. A real ``caracole serve`` serves the page; its
queue runs ``FakeTranscribe``, which says the job's stages and writes what the real one leaves in the library.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

import pytest
from helpers import cards
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.fake_ytdlp import FakeYtDlp
from test_autochords_transcript import youtube_song
from test_web_page_steps import bar_of, driven, one_row, wait_for, words_of
from test_web_page_youtube import serve

import caracole.youtube_fetch as yf
from caracole import db
from caracole.autochords.transcript import MODEL, Transcript, keep_transcript
from caracole.config import AutochordsConfig
from caracole.get import PROGRESS_PREFIX
from caracole.library import song_dir
from caracole.songs import get_song, update_song
from caracole.web.jobs import YOUTUBE_SHEET, youtube_sheet_steps

pytestmark = CHROMIUM_MARKS  # every test here drives the page in Chromium

DISPLAY = "Nick Cani - Vikingos veganos"
PASTED = "https://www.youtube.com/watch?v=lzN7Thn3FV4"
NO_RELOAD = "window.notReloaded === true"  # set once the page opened: gone, had it loaded again


class FakeTranscribe:
    """``caracole transcribe --progress``: its stages said, up to the words, which run until ``hold`` is set; then, as
    the real one leaves the library, the song's transcript kept and its auto sheet's PDF written, and the rest said
    done; with ``fail``, the words fail on the GPU and nothing is kept (exit 1). ``caracole youtube --sheet
    --progress``: a sheet made at once, chords only, every lyrics site having missed the song (its lyrics missing,
    asked now), as youtube_sheet.py leaves a song no site has words for."""

    def __init__(self):
        self.ran: list[tuple[str, ...]] = []
        self.hold = threading.Event()
        self.fail = False
        self.words_said: list[str] = []  # what the words say they do as they run, before the hold
        self.vocals_said: list[str] = []  # what the vocals say they do; with any, they wait for ``vocals_hold``
        self.vocals_hold = threading.Event()
        self.cfg = None
        self.song = None

    def _sheet(self) -> None:
        folder = song_dir(self.cfg.library_dir, self.song)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sheet (auto).pdf").write_bytes(b"%PDF-1.4\n")

    def _in_the_book(self, change) -> None:
        conn = db.connect(self.cfg.db_path)
        try:
            change(conn, get_song(conn, self.song.id))
        finally:
            conn.close()

    def __call__(self, args, emit):
        self.ran.append(tuple(args))

        def stage(name, state, detail=""):
            emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

        emit(PROGRESS_PREFIX + json.dumps({"song": {"id": self.song.id, "display": self.song.display}}))
        if args[0] == "youtube":
            for name, detail in (("song", "in the book"), ("audio", "downloaded")):
                stage(name, "running")
                stage(name, "done", detail)
            self._in_the_book(lambda conn, song: update_song(conn, song.id, lyrics_status="missing",
                                                              lyrics_at="2026-11-21T00:00:00Z"))
            stage("lyrics", "done", "LRCLIB has none; nor has Megalobiz; nor has AZLyrics")  # youtube_sheet's words
            self._sheet()
            for name, detail in (("chords", "chords only, no lyrics"), ("pdf", "made"), ("pages", "")):
                stage(name, "done", detail)
            return 0
        for name in ("song", "vocals"):
            stage(name, "running")
            if name == "vocals" and self.vocals_said:
                for said in self.vocals_said:
                    stage(name, "running", said)
                self.vocals_hold.wait(30)
            stage(name, "done", "in the book" if name == "song" else "sung from 9.3 s, 4 stretches")
        stage("words", "running")
        for said in self.words_said:
            stage("words", "running", said)
        self.hold.wait(30)
        if self.fail:
            stage("words", "failed", "the GPU failed: CUDA out of memory")
            for name in ("chords", "pdf"):
                stage(name, "skipped", "no transcript")
            return 1
        self._in_the_book(lambda conn, song: keep_transcript(conn, song, Transcript(
            lrc="[00:09.30]Somos vikingos\n", audio=song.audio_path, audio_mtime=song.audio_mtime, model=MODEL,
            language="es", device="cpu", words_dropped=3, made_at="2026-11-21T00:00:00Z")))
        stage("words", "done", "212 words in 31 lines (es), 3 dropped")
        self._sheet()
        for name, detail in (("chords", "chords over the transcribed lyrics"), ("pdf", "made"), ("pages", "")):
            stage(name, "done", detail)
        return 0


@pytest.fixture
def able(cfg, tmp_path, monkeypatch):
    """A caracole that makes a sheet from a video (auto-chords' packages and model files taken to be there, a
    FakeYtDlp never run) and transcribes (Whisper, its models and demucs-rs taken to be there), on the CPU."""
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    monkeypatch.setattr(yf, "transcribe_problem", lambda cfg: None)
    monkeypatch.delenv("CARACOLE_TORCH_CUDA", raising=False)
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    return replace(cfg, ytdlp_bin=FakeYtDlp(tmp_path / "bin").bin, autochords=AutochordsConfig(**files))


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
    made.vocals_hold.set()
    made.hold.set()


@pytest.fixture
def live(able, transcriber):
    server, queue, base, posted = serve(able, transcriber)
    yield base, posted, queue
    server.shutdown()
    server.server_close()
    transcriber.vocals_hold.set()  # a transcription still held lets go first: the queue stops at once
    transcriber.hold.set()
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


def read_again(posted, n: int = 1, timeout: float = 10.0) -> None:
    """Wait until the page has asked GET /transcribe ``n`` times."""
    deadline = time.monotonic() + timeout
    while posted.read.count("/transcribe") < n:
        assert time.monotonic() < deadline, posted.read[-5:]
        time.sleep(0.05)


def line(song) -> str:
    return f'article.line[data-id="{song.id}"]'


def opened(browser, song) -> str:
    assert browser.wait(f"document.querySelector({json.dumps(line(song) + ' .line-more')}) !== null")
    browser.click(cards.name_of(line(song)))
    return cards.open_card(browser, line(song))


def tone(song) -> str:
    return f"(document.querySelector({json.dumps(line(song) + ' .progress')}) || {{}}).dataset.tone"


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
    # Ready: its line drawn again, its card open again, the offer read again, and none: it is transcribed now.
    transcriber.hold.set()
    assert browser.wait(f"{tone(song)} === 'ready'")
    read_again(posted)
    again = cards.card_js(line(song))  # the card drawn again from the song as it is now, open as it was
    assert browser.wait(f"{again} !== null && {again}.querySelector('.card-head') !== null")
    assert not browser.wait("document.querySelector('form.transcribe') !== null", timeout=1.5)
    assert len(posted) == 1


def doing_of(song) -> str:
    """The expression for the words beside the song's running bar, [the step, its place, what it does], each with
    whether it is cut short (its text wider than its box)."""
    said = json.dumps(f"{line(song)} .progress.barred")
    return (f"(() => {{ const b = document.querySelector({said}); "
            "const t = (s) => { const e = b && b.querySelector(s); "
            "return e ? [e.textContent, e.scrollWidth > e.clientWidth] : ['', false]; }; "
            "return [t('.step-at'), t('.step-count'), t('.step-doing')]; })()")


@pytest.mark.parametrize("width", [1280, 390])
def test_the_bar_says_how_far_a_long_stage_is_beside_its_place(able, live, transcriber, tmp_path, width):
    # The separator and Whisper take up to half an hour on a CPU: the bar says what the running stage says it does,
    # the number first, after the step's place, in the bar's one row; on a phone too, neither the step nor its number
    # cut short. It is the eye's alone: a screen reader hears the step and its place change, not each window.
    base, posted, _ = live
    song = transcriber.song
    transcriber.vocals_said = ["2 of ~12 min"]
    transcriber.words_said = ["1:20 of 3:45"]
    page = driven(tmp_path, width)
    try:
        page.open(base)
        card = opened(page, song)
        page.click(card + ' form.transcribe button[type="submit"]')
        posted.next(0)
        wait_for(page, doing_of(song), [["Vocals", False], [" · 2 of 5", False], [" · 2 of ~12 min", False]])
        wait_for(page, bar_of(line(song)), ["done", "running", "waiting", "waiting", "waiting"])
        one_row(page, line(song))
        doing = json.dumps(line(song) + " .step-doing")
        assert page.js(f"document.querySelector({doing}).getAttribute('aria-hidden')") == "true"
        transcriber.vocals_hold.set()
        wait_for(page, doing_of(song), [["Words", False], [" · 3 of 5", False], [" · 1:20 of 3:45", False]])
        one_row(page, line(song))
        edge = page.js(f"(() => {{ const r = (s) => document.querySelector(s).getBoundingClientRect(); "
                       f"return [r({doing}).right, r({json.dumps(line(song))}).right]; }})()")
        assert edge[0] <= edge[1] + 0.5, edge
        transcriber.hold.set()
        assert page.wait(f"{tone(song)} === 'ready'")
        assert page.js(f"document.querySelector({doing})") is None
    finally:
        page.close()


def test_a_sheet_from_a_video_that_found_no_lyrics_offers_it_at_once_with_no_reload(able, live, transcriber,
                                                                                    browser):
    # The real flow: the page open first, the song's lyrics still to be asked for (nothing offered), its Sheet from a
    # YouTube video pressed; the sheet ends Ready, "Chords only, no lyrics.", every lyrics site having missed it. The
    # page reads the offer again: its card offers the transcription, and so does its request in the Journal.
    base, posted, _ = live
    song = transcriber.song
    conn = db.connect(able.db_path)
    try:
        update_song(conn, song.id, lyrics_status="pending", lyrics_at=None)  # not asked yet: no offer
    finally:
        conn.close()
    browser.open(base)
    browser.js("window.notReloaded = true")
    card = opened(browser, song)
    sheet_form = json.dumps(card + " form.youtube-sheet")
    assert browser.wait(f"document.querySelector({sheet_form}) !== null")
    assert browser.js("document.querySelector('form.transcribe')") is None
    browser.js(f"document.querySelector({sheet_form} + ' input[name=youtube]').focus()")
    browser.type(PASTED)
    browser.click(card + ' form.youtube-sheet button[type="submit"]')
    path, _ = posted.next(0)
    assert path == "/youtube"
    assert browser.wait(f"{tone(song)} === 'ready'")
    again = cards.card_js(line(song))
    assert browser.wait(f"{again} !== null && {again}.querySelector('form.transcribe') !== null"), posted.read[-5:]
    assert "/transcribe" in posted.read and browser.js(NO_RELOAD)  # read again, the page never loaded again
    assert browser.js(f"{again}.querySelector('form.transcribe .hint').textContent") == (
        "From the audio, up to half an hour.")
    # The Journal: the sheet's request, Ready, chords only, offers it after its reason.
    browser.click("#tab-requests")
    item = "#req-1"
    assert browser.wait(f"(document.querySelector({json.dumps(item + ' .req-says')}) || {{}}).textContent === 'Ready'")
    assert browser.js(f"document.querySelector({json.dumps(item + ' .req-reason')}).textContent") == (
        "Chords only, no lyrics.")
    assert browser.wait(f"document.querySelector({json.dumps(item + ' form.transcribe')}) !== null")
    assert browser.js(NO_RELOAD)
    # Pressed there: queued, and gone from both.
    browser.click(item + ' form.transcribe button[type="submit"]')
    path, fields = posted.next(1)
    assert (path, fields) == ("/transcribe", {"csrf": "tok", "song": str(song.id), "identity": song.key})
    assert browser.wait(f"document.querySelector({json.dumps(item + ' form.transcribe')}) === null")
    assert browser.wait("document.querySelector('form.transcribe') === null")
    assert transcriber.ran[-1] == ("transcribe", "--progress", f"--song={DISPLAY}")


def test_a_transcription_that_failed_on_the_gpu_is_offered_again(able, live, transcriber, browser):
    # The song stays offered after the GPU failed (the setup's failure files nothing against it): once the job is
    # over, the page reads the offer again and its card offers it again, with no reload.
    base, posted, _ = live
    song = transcriber.song
    transcriber.fail = True
    browser.open(base)
    browser.js("window.notReloaded = true")
    card = opened(browser, song)
    assert browser.wait(f"document.querySelector({json.dumps(card + ' form.transcribe')}) !== null")
    browser.click(card + ' form.transcribe button[type="submit"]')
    posted.next(0)
    assert browser.wait("document.querySelector('form.transcribe') === null")
    transcriber.hold.set()
    assert browser.wait(f"{tone(song)} === 'failed'")
    again = cards.card_js(line(song))
    assert browser.wait(f"{again} !== null && {again}.querySelector('form.transcribe') !== null")
    assert browser.js(NO_RELOAD)


def test_a_transcription_asked_in_the_requests_tab_that_failed_is_offered_there_again(able, live, transcriber,
                                                                                      browser):
    # Pressed on the Journal's Ready request, then failed on the GPU: the song stays offered, and the Journal offers
    # it again as its card does, with no reload (library.js's word, read again once the job is over).
    base, posted, queue = live
    song = transcriber.song
    transcriber.fail = True
    sheet, _ = queue.submit(f"Sheet from YouTube: {DISPLAY}", YOUTUBE_SHEET + song.key,
                            youtube_sheet_steps(DISPLAY, "https://www.youtube.com/watch?v=XFkzRNyygfk"),
                            display=DISPLAY)
    over(queue, sheet.id)
    offer = json.dumps(f"#req-{sheet.id} form.transcribe")
    browser.open(base + "#tab=requests")
    browser.js("window.notReloaded = true")
    assert browser.wait(f"document.querySelector({offer}) !== null")
    browser.click(f"#req-{sheet.id}" + ' form.transcribe button[type="submit"]')
    posted.next(0)
    assert browser.wait(f"document.querySelector({offer}) === null")
    transcriber.hold.set()
    read_again(posted)
    assert browser.wait(f"document.querySelector({offer}) !== null", timeout=10)
    assert browser.js(NO_RELOAD)
    browser.click("#tab-library")
    card = opened(browser, song)
    assert browser.wait(f"document.querySelector({json.dumps(card + ' form.transcribe')}) !== null")


def test_a_ready_request_of_a_song_offered_when_the_page_loaded_offers_it_in_the_requests_tab(able, live, transcriber,
                                                                                             browser):
    # A sheet from YouTube over, chords only, before the page loads (or after a reload): its request offers the
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
    server, queue, base, posted = serve(cfg, made)
    try:
        browser.open(base)
        card = opened(browser, made.song)
        assert browser.wait(f"!document.querySelector({json.dumps(card)}).hidden")
        assert browser.js(f"document.querySelector({json.dumps(card + ' form.transcribe')})") is None
        assert browser.js("document.querySelector('form.transcribe')") is None
        assert "/transcribe" not in posted.read  # it never asks the offer again where none can be made
    finally:
        made.hold.set()
        server.shutdown()
        server.server_close()
        queue.stop()
