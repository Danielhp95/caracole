"""A sheet from an audio file of yours, asked for on the library page caracole serve serves, in a real browser.

Where this caracole makes chords (the served data's ``server.audio``), the search bar has a "+": a file chosen (or
dropped on the Library) is sent at once to ``POST /audio/upload`` (its bytes, the form token in its header), and a
dialog shows what it is and the song it names, Artist and Title filled with that guess; Make sheet posts ``POST /audio``
as the request form posts a request, a line under the bar then saying how it goes; Cancel drops the file (``POST
/audio/drop``). A song's card, not ignored and with no human sheet, has Sheet from an audio file…, the same chooser and
dialog for that song, its Make sheet posting the song and its identity. The file on disk and the phone have no "+". A
real ``caracole serve`` serves the page; its queue runs ``FakeAudio``, which says the job's stages and makes nothing.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote

import pytest
from helpers import cards
from helpers.audio_files import write
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_library_card import run
from test_library_page import attribute_of
from test_web_page_steps import bar_of, wait_for
from test_web_youtube import keep_human_sheet

import caracole.library_page as library_page
import caracole.youtube_fetch as yf
from caracole import audio_store, db
from caracole.config import AutochordsConfig
from caracole.get import PROGRESS_PREFIX
from caracole.library_page import WebControls
from caracole.songs import update_song
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here drives the page in Chromium

NICK = ("Nick Cani", "Vikingos veganos")


class FakeAudio:
    """``caracole audio --progress --upload=… --song=…``: its stages said, up to the chords, which run until ``hold``
    is set."""

    def __init__(self):
        self.ran: list[tuple[str, ...]] = []
        self.hold = threading.Event()

    def __call__(self, args, emit):
        self.ran.append(tuple(args))

        def stage(name, state, detail=""):
            emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

        for name, detail in (("song", "in the book"), ("audio", "kept as its audio: MP3, 3:18"),
                             ("lyrics", "found, timed")):
            stage(name, "running")
            stage(name, "done", detail)
        stage("vocals", "skipped", "not transcribed: its lyrics are found")
        stage("words", "skipped", "no vocals")
        stage("chords", "running")
        self.hold.wait(30)
        stage("chords", "done", "chords over LRCLIB's timed lyrics")
        return 0


class Posted(list):
    """Each POST the server got, in order: its target, headers and body; ``next`` waits for the one after ``n``."""

    def next(self, n: int, timeout: float = 10.0) -> SimpleNamespace:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self) > n:
                return self[n]
            time.sleep(0.05)
        raise AssertionError(f"the page posted nothing after {n}")


@pytest.fixture(autouse=True)
def room(monkeypatch):
    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**15, used=0, free=10**15))


@pytest.fixture
def able(cfg, tmp_path, monkeypatch):
    """A config this caracole can make chords of audio with: auto-chords' packages taken to be there, its model files;
    no yt-dlp."""
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    return replace(cfg, ytdlp_bin=str(tmp_path / "no-yt-dlp"), autochords=AutochordsConfig(**files))


def serve(cfg, runner):
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False,
                 timers={"poll": 100, "idle": 100, "undo": 100})
    posted = Posted()
    answer = app.handle

    def handle(request):
        if request.method == "POST":
            posted.append(SimpleNamespace(target=request.target, headers=dict(request.headers), body=request.body))
        return answer(request)

    app.handle = handle
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    return server, queue, f"http://127.0.0.1:{server.server_address[1]}/", posted


@pytest.fixture
def made():
    fake = FakeAudio()
    yield fake
    fake.hold.set()


@pytest.fixture
def live(able, made):
    server, queue, base, posted = serve(able, made)
    yield base, posted
    server.shutdown()
    server.server_close()
    made.hold.set()
    queue.stop()


@pytest.fixture
def browser(tmp_path):
    try:
        page = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    page.send("Page.setInterceptFileChooserDialog", enabled=True)  # a chooser opened is the test's, never a window
    yield page
    page.close()


def mp3(tmp_path, name="03 whatever.mp3", **tags):
    return write(tmp_path / "files" / name, "MP3", 198.2, **tags)


def choose(page: Browser, path) -> None:
    """A file picked in #audio-file, as the browser's chooser picks one."""
    root = page.send("DOM.getDocument")["root"]["nodeId"]
    node = page.send("DOM.querySelector", nodeId=root, selector="#audio-file")["nodeId"]
    page.send("DOM.setFileInputFiles", files=[str(path)], nodeId=node)


def form_of(post) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(post.body.decode()).items()}


def staged_ids(cfg) -> set[str]:
    folder = cfg.state_dir / "audio"
    return {p.name[len(".upload-"):][:16] for p in folder.iterdir()
            if p.name.startswith(".upload-")} if folder.exists() else set()


SETTLED = "document.getAnimations().length === 0"  # a press lands where the dialog is, not where it slides from
SAID = "document.querySelector('#audio-sheet .audio-said').textContent"
FIELDS = "['artist', 'title'].map((n) => document.querySelector(`#audio-sheet [name=${n}]`).value)"


def test_the_plus_shows_only_where_a_sheet_can_be_made_from_a_file(able, live, browser, conn, cfg, tmp_path,
                                                                  monkeypatch):
    base, _ = live
    browser.open(base)
    assert browser.wait("document.getElementById('add-audio') !== null")
    plus = browser.js("(() => { const b = document.getElementById('add-audio'); return [b.textContent, "
                      "b.getAttribute('aria-label'), b.title, b.nextElementSibling.id, "
                      "document.getElementById('audio-file').accept]; })()")
    assert plus == ["+", "Make a sheet from an audio file", "Make a sheet from an audio file", "filter",
                    "audio/*,.mp3,.m4a,.flac,.wav,.ogg,.aif,.aiff"]
    probe = 'note("plus", [!!document.getElementById("add-audio"), !!document.getElementById("audio-file")]);'
    # The file on disk: none.
    assert attribute_of(run(conn, cfg, tmp_path, probe), "data-plus") == [False, False]
    # Served where no chords are made, and with the phone's member: none.
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    assert attribute_of(run(conn, able, tmp_path, probe, controls=WebControls(csrf="tok")), "data-plus") == \
        [False, False]
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    monkeypatch.setattr(library_page, "audio_member",
                        lambda cfg: {"ok": False, "why": "auto-chords isn't on the phone", "limit": 0})
    assert attribute_of(run(conn, able, tmp_path, probe, controls=WebControls(csrf="tok")), "data-plus") == \
        [False, False]


def test_a_file_chosen_uploads_with_the_token_and_shows_its_guess(able, live, browser, tmp_path):
    base, posted = live
    browser.open(base)
    assert browser.wait("document.getElementById('audio-file') !== null")
    path = mp3(tmp_path, artist=NICK[0], title="Vikingos veganos (Official Audio)")
    choose(browser, path)
    sent = posted.next(0)
    assert unquote(sent.target) == "/audio/upload?name=03 whatever.mp3"
    assert sent.headers["content-type"] == "application/octet-stream"  # never the file's own type, which is refused
    assert sent.headers["x-caracole-form-token"] == "tok" and sent.body == path.read_bytes()
    assert browser.wait("document.getElementById('audio-sheet').open")
    assert browser.wait(f"{SAID} === '03 whatever.mp3 · MP3 · 3:18'"), browser.js(SAID)
    assert browser.js(FIELDS) == list(NICK)
    assert browser.js("document.activeElement.name") == "title"
    hint = browser.js("document.querySelector('#audio-sheet .hint').textContent")
    assert hint.startswith("Chords from the file; lyrics from the lyrics sites, else heard from it.")
    assert len(staged_ids(able)) == 1


def test_make_sheet_with_names_corrected_posts_and_shows_the_requests_line(able, live, made, browser, tmp_path):
    base, posted = live
    browser.open(base)
    assert browser.wait("document.getElementById('audio-file') !== null")
    choose(browser, mp3(tmp_path, "07 - Nick Cani - Vikingos.mp3"))
    assert browser.wait("document.querySelector('#audio-sheet [name=title]') !== null")
    assert browser.js(FIELDS) == ["Nick Cani", "Vikingos"]
    browser.js("const t = document.querySelector('#audio-sheet [name=title]'); t.focus(); t.select()")
    browser.type("Vikingos veganos")
    assert browser.wait(SETTLED)
    browser.click("#audio-sheet button[type=submit]")
    sent = posted.next(1)
    fields = form_of(sent)
    assert sent.target == "/audio" and fields.pop("csrf") == "tok"
    assert set(fields) == {"upload", "artist", "title"} and (fields["artist"], fields["title"]) == NICK
    assert fields["upload"] in staged_ids(able)
    assert browser.wait("!document.getElementById('audio-sheet').open")
    # A line under the bar says how it goes, the job's steps as a bar while it runs.
    assert browser.wait("(document.querySelector('#requested-list .progress') || {}).dataset.tone === 'running'")
    wait_for(browser, bar_of("#requested-list article"), ["done", "done", "done", "skipped", "running", "waiting"])
    assert made.ran == [("audio", "--progress", f"--upload={fields['upload']}",
                         "--song=Nick Cani - Vikingos veganos")]
    assert "Nick Cani - Vikingos veganos" in able.wanted_file.read_text(encoding="utf-8")


def test_cancel_drops_it(able, live, browser, tmp_path):
    base, posted = live
    browser.open(base)
    assert browser.wait("document.getElementById('audio-file') !== null")
    choose(browser, mp3(tmp_path))
    assert browser.wait("document.querySelector('#audio-sheet [name=title]') !== null")
    [upload] = staged_ids(able)
    assert browser.wait(SETTLED)
    browser.click("#audio-sheet .audio-form button[type=button]")  # Cancel
    sent = posted.next(1)
    assert sent.target == "/audio/drop" and json.loads(sent.body) == {"upload": upload}
    assert sent.headers["x-caracole-form-token"] == "tok"
    assert browser.wait("!document.getElementById('audio-sheet').open")
    deadline = time.monotonic() + 10
    while staged_ids(able) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert staged_ids(able) == set()
    assert browser.js("document.activeElement.id") == "add-audio"  # the focus back where the dialog came from


def test_a_dropped_file_opens_the_dialog(able, live, browser, tmp_path):
    base, posted = live
    browser.open(base)
    assert browser.wait("document.getElementById('add-audio') !== null")
    data = base64.b64encode(mp3(tmp_path, artist=NICK[0], title=NICK[1]).read_bytes()).decode()
    # Something else dropped (text) is the browser's: no dialog, nothing sent.
    left = browser.js("""(() => { const t = new DataTransfer(); t.setData("text/plain", "hello");
      const over = new DragEvent("dragover", { dataTransfer: t, bubbles: true, cancelable: true });
      document.getElementById("list").dispatchEvent(over);
      const drop = new DragEvent("drop", { dataTransfer: t, bubbles: true, cancelable: true });
      document.getElementById("list").dispatchEvent(drop);
      return [over.defaultPrevented, drop.defaultPrevented]; })()""")
    assert left == [False, False] and not browser.js("document.getElementById('audio-sheet').open")
    taken = browser.js(f"""(() => {{ const bytes = Uint8Array.from(atob({json.dumps(data)}), (c) => c.charCodeAt(0));
      const t = new DataTransfer(); t.items.add(new File([bytes], "dropped.mp3", {{ type: "audio/mpeg" }}));
      const over = new DragEvent("dragover", {{ dataTransfer: t, bubbles: true, cancelable: true }});
      document.getElementById("list").dispatchEvent(over);
      const drop = new DragEvent("drop", {{ dataTransfer: t, bubbles: true, cancelable: true }});
      document.getElementById("list").dispatchEvent(drop);
      return [over.defaultPrevented, drop.defaultPrevented]; }})()""")
    assert taken == [True, True]
    assert browser.wait("document.getElementById('audio-sheet').open")
    assert browser.wait(f"{SAID} === 'dropped.mp3 · MP3 · 3:18'"), browser.js(SAID)
    assert browser.js(FIELDS) == list(NICK)
    assert unquote(posted.next(0).target) == "/audio/upload?name=dropped.mp3"


def test_a_cards_entry_makes_a_sheet_for_that_song_from_a_file(able, live, made, browser, tmp_path):
    base, posted = live
    conn = db.connect(able.db_path)
    try:
        song = add_song(conn, *NICK)
        update_song(conn, song.id, audio_path=str(tmp_path / "Music" / "vikingos.flac"), audio_mtime=1.0)  # bought
        sheeted = add_song(conn, "Radiohead", "Creep")
        keep_human_sheet(conn, able, sheeted)
        conn.commit()
    finally:
        conn.close()

    line = f'article.line[data-id="{song.id}"]'
    browser.open(base)
    assert browser.wait(f"document.querySelector({json.dumps(line + ' .line-more')}) !== null")
    browser.click(cards.name_of(line))
    card = cards.open_card(browser, line)
    entry = card + " form.audio-sheet button"
    assert browser.wait(f"document.querySelector({json.dumps(entry)}) !== null")
    assert browser.js(f"document.querySelector({json.dumps(entry)}).textContent") == "Sheet from an audio file…"
    browser.click(entry)
    choose(browser, mp3(tmp_path, "anything.mp3"))
    assert browser.wait(f"{SAID} === 'anything.mp3 · MP3 · 3:18'"), browser.js(SAID)
    names = browser.js("document.querySelector('#audio-sheet .audio-names').textContent")
    assert names == "Nick Cani - Vikingos veganos"
    assert browser.js("document.querySelector('#audio-sheet [name=title]')") is None  # its names, not to edit
    assert browser.wait(SETTLED)
    browser.click("#audio-sheet button[type=submit]")
    sent = posted.next(1)
    fields = form_of(sent)
    assert sent.target == "/audio"
    assert fields == {"csrf": "tok", "song": str(song.id), "identity": song.key, "upload": fields["upload"]}
    assert len(fields["upload"]) == 16
    wait_for(browser, bar_of(line), ["done", "done", "done", "skipped", "running", "waiting"])
    assert made.ran[0][-1] == "--song=Nick Cani - Vikingos veganos"
    # A song with a human sheet offers none.
    other = f'article.line[data-id="{sheeted.id}"]'
    browser.click(cards.name_of(other))
    card = cards.open_card(browser, other)
    assert browser.wait(f"document.querySelector({json.dumps(card + ' .card-foot, ' + card + ' .tiles')}) !== null")
    assert browser.js(f"document.querySelector({json.dumps(card + ' form.audio-sheet')})") is None
