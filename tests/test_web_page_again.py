"""A song you have, looked up again from its line's "⋯" on the library page caracole serve serves, in a real browser.

Fetch again posts what the lookup page's Fetch again posts for the song (``POST /lookup`` with its id: one
``caracole get``), and Use LaCuerda's sheet what the lookup page's LaCuerda row of it posts (its id and that
LaCuerda page), the sheet your pick on LaCuerda names, or the one the bar's search finds LaCuerda has of it. Each
shows its request's line on the song's line. A real ``caracole serve`` serves both pages; it notes the body of
each ``POST /lookup``, and its queue runs ``FakeLookup``, which says a lookup's stages and keeps nothing new. The
file on disk, which can ask nothing, has neither.
"""

from __future__ import annotations

import json
import threading
import time
from urllib.parse import parse_qs, quote

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_web_page_lacuerda import LC, lacuerda
from test_web_page_search import sites

from caracole import db
from caracole.get import PROGRESS_PREFIX
from caracole.library import keep_file, song_dir
from caracole.overrides import add_lacuerda
from caracole.songs import update_song
from caracole.versions import upsert_version
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here drives the pages in Chromium


class FakeLookup:
    """``caracole get --progress`` of a song the library has: its stages said, nothing new kept."""

    def __init__(self):
        self.ran: list[tuple[str, ...]] = []
        self.hold = threading.Event()  # cleared, its sheet stage runs until a test sets it
        self.hold.set()

    def __call__(self, args, emit):
        self.ran.append(tuple(args))

        def stage(name, state, detail=""):
            emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

        stage("song", "running")
        stage("song", "done", "in the library")
        stage("sheet", "running")
        time.sleep(0.5)  # long enough for the page to show it
        self.hold.wait(30)
        stage("sheet", "done", "tab 1 from Ultimate Guitar")
        return 0


class Posted(list):
    """The body of each ``POST /lookup`` the server got, in order; ``next`` waits for the one after ``n``."""

    def next(self, n: int, timeout: float = 10.0) -> bytes:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self) > n:
                return self[n]
            time.sleep(0.05)
        raise AssertionError(f"the page posted no lookup after {n}")


@pytest.fixture
def lookup():
    return FakeLookup()


@pytest.fixture
def live(cfg, lookup):
    queue = JobQueue(lookup)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    posted = Posted()
    answer = app.handle

    def handle(request):
        if request.method == "POST" and request.target.startswith("/lookup"):
            posted.append(request.body)
        return answer(request)

    app.handle = handle
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", posted
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


def camaron(cfg):
    """Estopa - Como Camarón, found: its sheet from Ultimate Guitar, kept, and its PDF."""
    conn = db.connect(cfg.db_path)
    try:
        song = add_song(conn, "Estopa", "Como Camarón")
        vid = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="sheet", kind="chords",
                             rating=4.5, votes=12, version=1, label=None,
                             url="https://tabs.ultimate-guitar.com/tab/estopa/como-camaron-chords-1", raw={}, now="x")
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"Words\n", rank=1)
        (song_dir(cfg.library_dir, song) / "sheet.pdf").write_bytes(b"%PDF-1.4")
        update_song(conn, song.id, status="found")
        conn.commit()
        return song
    finally:
        conn.close()


USE = "Use LaCuerda's sheet"


def line(song) -> str:
    return f'article.line[data-id="{song.id}"]'  # in the list, or in the bar's results while it searches


def menu_button(song, label: str) -> str:
    """The expression for the button ``label`` under the song's line's "⋯", or null."""
    return (f"[...document.querySelectorAll({json.dumps(line(song) + ' .line-panel button')})]"
            f".find((b) => b.textContent === {json.dumps(label)}) || null")


def press_in_menu(browser, song, label: str) -> None:
    """The song's "⋯" opened, and its button ``label`` clicked, as a hand would."""
    assert browser.wait(f"document.querySelector({json.dumps(line(song) + ' .line-more')}) !== null")
    browser.click(line(song) + " .line-more")
    assert browser.wait(f"({menu_button(song, label)}) !== null")
    browser.js(f"({menu_button(song, label)}).dataset.pressMe = '1'")
    browser.click(line(song) + " .line-panel button[data-press-me]")


# The tones of a lookup's line that went as asked: queued, running, then kept (status.py); never "failed", which a
# refusal, or an answer the page couldn't read, would say on the line too.
ASKED = ("queued", "running", "ready", "added")


def shows_its_request(browser, song) -> bool:
    """Whether the song's line shows its lookup's line: past Sending…, as the server said it, the lookup's own."""
    progress = json.dumps(line(song) + " .progress")
    shown = browser.wait(f"(() => {{ const p = document.querySelector({progress}); "
                         "return Boolean(p && p.textContent && p.textContent !== 'Sending…' "
                         f"&& {json.dumps(ASKED)}.includes(p.dataset.tone)); }})()")
    assert shown, browser.js(f"(() => {{ const p = document.querySelector({progress}); "
                             "return p && [p.dataset.tone, p.textContent]; })()")
    return shown


def lookup_page_presses(browser, base, query: str, aria: str) -> None:
    """The lookup page, ``query`` searched, and its button named ``aria`` pressed."""
    browser.open(base + "lookup?q=" + quote(query))
    found = f"document.querySelector({json.dumps(f'#results button[aria-label={json.dumps(aria, ensure_ascii=False)}]')})"
    assert browser.wait(f"{found} !== null"), browser.js("document.getElementById('results').textContent")
    browser.js(f"{found}.click()")


def test_fetch_again_posts_what_the_lookup_pages_fetch_again_posts_and_shows_its_line(cfg, live, browser):
    base, posted = live
    sites(cfg)
    song = camaron(cfg)
    browser.open(base)
    press_in_menu(browser, song, "Fetch again")
    body = posted.next(0)
    assert parse_qs(body.decode()) == {"csrf": ["tok"], "song": [str(song.id)]}
    assert shows_its_request(browser, song)
    # The lookup page's Fetch again, for the same song, posts the very same form.
    lookup_page_presses(browser, base, "como camaron", "Fetch Estopa - Como Camarón again")
    assert posted.next(1) == body


def test_fetch_again_and_use_lacuerdas_sheet_are_gone_while_the_songs_lookup_runs(cfg, live, lookup, browser):
    # Asked for already, the song's line shows how it goes, and offers neither again until it is over.
    base, posted = live
    song = camaron(cfg)
    add_lacuerda(cfg.overrides_file, song.display, LC + "estopa/como_camaron")
    lookup.hold.clear()
    browser.open(base)
    press_in_menu(browser, song, "Fetch again")
    posted.next(0)
    assert browser.wait(f"(() => {{ const p = document.querySelector({json.dumps(line(song) + ' .progress')}); "
                        "return Boolean(p && p.dataset.tone === 'running'); })()")
    assert browser.js(f"document.querySelector({json.dumps(line(song) + ' .actions.again')})") is None
    assert browser.js(menu_button(song, "Fetch again")) is None
    assert browser.js(menu_button(song, USE)) is None
    lookup.hold.set()
    # Once it is over, the line is drawn again, with both.
    assert browser.wait(f"({menu_button(song, 'Fetch again')}) !== null && ({menu_button(song, USE)}) !== null")


def test_use_lacuerdas_sheet_posts_your_pick_as_the_lookup_pages_lacuerda_row_does(cfg, live, browser):
    base, posted = live
    sites(cfg)
    lacuerda(cfg)
    song = camaron(cfg)
    add_lacuerda(cfg.overrides_file, song.display, LC + "estopa/como_camaron")
    browser.open(base)
    press_in_menu(browser, song, USE)
    body = posted.next(0)
    assert parse_qs(body.decode()) == {"csrf": ["tok"], "song": [str(song.id)],
                                       "lacuerda": [LC + "estopa/como_camaron"]}
    assert shows_its_request(browser, song)
    # The lookup page's LaCuerda row of the song, Get it again, posts the very same form.
    lookup_page_presses(browser, base, "como camaron", "Get Estopa - Como Camarón again from LaCuerda")
    assert posted.next(1) == body


def test_the_bars_search_finding_lacuerdas_sheet_of_a_song_offers_it_under_its_menu(cfg, live, browser):
    base, posted = live
    sites(cfg)
    lacuerda(cfg)
    song = camaron(cfg)
    browser.open(base)
    assert browser.wait(f"document.querySelector({json.dumps(line(song))}) !== null")
    # Nothing tells the page LaCuerda has it, yet.
    assert browser.js(menu_button(song, USE)) is None
    assert browser.js(f"({menu_button(song, 'Fetch again')}) !== null")
    # Its "⋯" open, the search begins.
    browser.click(line(song) + " .line-more")
    browser.js("document.getElementById('q').focus()")
    browser.type("como camaron")
    # The search's LaCuerda row of it is folded into your song's line, which offers that sheet now, its "⋯" still
    # open under your hand.
    assert browser.wait(f"({menu_button(song, USE)}) !== null")
    panel = json.dumps(line(song) + " .line-panel")
    more = json.dumps(line(song) + " .line-more")
    assert browser.js(f"document.querySelector({panel}).hidden") is False
    assert browser.js(f"document.querySelector({more}).getAttribute('aria-expanded')") == "true"
    browser.js(f"({menu_button(song, USE)}).dataset.pressMe = '1'")
    browser.click(line(song) + " .line-panel button[data-press-me]")
    body = posted.next(0)
    assert parse_qs(body.decode()) == {"csrf": ["tok"], "song": [str(song.id)],
                                       "lacuerda": [LC + "estopa/como_camaron"]}
    assert shows_its_request(browser, song)
    lookup_page_presses(browser, base, "como camaron", "Get Estopa - Como Camarón again from LaCuerda")
    assert posted.next(1) == body


def test_a_wanted_song_has_its_fetch_now_and_no_fetch_again(cfg, live, browser):
    base, _ = live
    conn = db.connect(cfg.db_path)
    try:
        wanted = add_song(conn, "Radiohead", "Creep")
        conn.commit()
    finally:
        conn.close()
    browser.open(base)
    assert browser.wait(f"document.querySelector({json.dumps(line(wanted) + ' form.fetch')}) !== null")
    assert browser.js(menu_button(wanted, "Fetch again")) is None
