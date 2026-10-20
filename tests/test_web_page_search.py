"""The library page's one bar, served by a real ``caracole serve`` and driven in a real browser.

Typing filters your songs on the page, asking the server nothing; Enter, or Search all, lists your
songs, then what the offline indexes hold of Ultimate Guitar, gtptabs.com and MuseScore
(``/api/search``), following what you type; Get it looks a song up in its own row. The queue
runs ``FakeGet``, which does what ``caracole get`` does with no request: it adds the song from
wanted.txt and keeps a sheet.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError

from caracole import db
from caracole.get import PROGRESS_PREFIX
from caracole.library import song_dir
from caracole.overrides import override_key
from caracole.songs import find_song, update_song
from caracole.ug.index import mark_built, upsert_rows
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here drives the page in Chromium


class FakeGet:
    """``caracole get --progress``: the song added from wanted.txt, a sheet.pdf kept, its stages said."""

    def __init__(self, cfg):
        self.cfg = cfg

    def __call__(self, args, emit):
        from caracole.wanted import sync_wanted

        def stage(name, state, detail=""):
            emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

        conn = db.connect(self.cfg.db_path)
        try:
            stage("song", "running")
            sync_wanted(conn, self.cfg.wanted_file, datetime.now(UTC))
            stage("song", "done", "in the library")
            stage("sheet", "running")
            time.sleep(0.3)  # long enough for the page to show it
            song = find_song(conn, override_key(f"{args[-2]} - {args[-1]}"))
            folder = song_dir(self.cfg.library_dir, song)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "sheet.pdf").write_bytes(b"%PDF-1.4")
            update_song(conn, song.id, status="found", ug_dirty=False)
            stage("sheet", "done", "tab 1 from Ultimate Guitar")
            return 0
        finally:
            conn.close()


@pytest.fixture
def live(cfg):
    """The library page on a socket, its queue running ``FakeGet``; ``asked`` lists the searches it got."""
    queue = JobQueue(FakeGet(cfg))
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    asked = []
    answer = app.handle

    def handle(request):
        if request.target.startswith("/api/search"):
            asked.append(request.target)
        return answer(request)

    app.handle = handle
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # stops within 10 ms
    yield f"http://127.0.0.1:{server.server_address[1]}/", queue, asked
    server.shutdown()
    server.server_close()
    queue.stop()


def driven(tmp_path, **size):
    try:
        return Browser(tmp_path / "chrome", **size)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")


@pytest.fixture
def browser(tmp_path):
    page = driven(tmp_path)
    yield page
    page.close()


@pytest.fixture
def phone(tmp_path):
    page = driven(tmp_path, width=390, height=844, mobile=True)
    yield page
    page.close()


def sites(cfg, ug=(), gtptabs=(), musescore=()):
    """The offline indexes: UG's (artist key, song key, chords versions), gtptabs.com's and MuseScore's pages."""
    from caracole.gtptabs import parse_page_url
    from caracole.musescore import parse_song_url

    conn = db.connect(cfg.db_path)
    when = datetime(2026, 10, 19, tzinfo=UTC)
    rows, n = [], 1000
    for artist, song, versions in ug:
        for _ in range(versions):
            n += 1
            rows.append((n, artist, song, "chords", f"{artist}/{song}-chords-{n}"))
    upsert_rows(conn, rows, "1", when)
    mark_built(conn, when)
    conn.executemany("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) "
                     "VALUES (?, ?, ?, ?, ?, '1')", [tuple(parse_page_url(u)) for u in gtptabs])
    conn.executemany("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES (?, ?, ?, '1')",
                     [tuple(parse_song_url(u)) for u in musescore])
    conn.commit()
    conn.close()


def library(cfg, *songs):
    conn = db.connect(cfg.db_path)
    made = [add_song(conn, artist, title) for artist, title in songs]
    conn.close()
    return made


def posted(queue, timeout=10.0):
    """The arguments of the first lookup the page posted."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = queue.snapshot()
        if jobs:
            return jobs[-1].steps[0].args
        time.sleep(0.05)
    raise AssertionError("the page posted no lookup")


GRID = "[...document.querySelectorAll('#list article')].map((a) => a.querySelector('h2').textContent)"
STATUS = "document.getElementById('bar-status').textContent"
HITS = "document.querySelectorAll('#results .hit').length"
GROUPS = "[...document.querySelectorAll('#results .group')].map((g) => g.textContent)"
WONDERWALL = dict(ug=[("oasis", "wonderwall", 9), ("ryan-adams", "wonderwall", 3), ("eagles", "hotel-california", 5)],
                  gtptabs=["https://gtptabs.com/tabs/15/oasis/wonderwall.html"],
                  musescore=["https://musescore.com/song/wonderwall-1524"])


def test_typing_filters_your_songs_and_enter_lists_the_sites_under_them(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    library(cfg, ("Eagles", "Hotel California"), ("Radiohead", "Creep"))
    browser.open(base)
    browser.js("document.getElementById('q').focus()")
    browser.type("wonderwall")
    assert browser.wait(f"{GRID}.length === 0")
    assert "Search all" in browser.js(STATUS) or "Enter" in browser.js(STATUS)
    time.sleep(0.4)
    assert asked == []  # typing filters the page's own songs: the server hears nothing
    browser.press("Enter")
    assert browser.wait(f"{HITS} >= 4")
    groups = browser.js(GROUPS)
    assert [g.split(" · ")[0] for g in groups] == ["Ultimate Guitar", "Guitar Pro on gtptabs.com", "MuseScore"], groups
    assert browser.js("[...document.querySelectorAll('#results .hit > .source')].map((m) => m.dataset.source)") == [
        "ug", "ug", "gtptabs", "musescore"]
    link = browser.js("(() => { const a = document.querySelector('#results .hit[data-source=\"musescore\"] .row-action a');"
                      " return [a.href, a.target, a.rel]; })()")
    assert link == ["https://musescore.com/song/wonderwall-1524", "_blank", "noopener noreferrer"]  # a link alone
    assert browser.js("document.querySelector('.toolbar').offsetParent") is None  # the grid's tools step aside
    assert browser.js("document.activeElement.id") == "q"
    assert "LaCuerda" in browser.js("document.querySelector('#results .skipped').textContent")
    # Typing on follows: your songs first, then the sites, the newest query's alone.
    browser.js("document.getElementById('q').select()")
    browser.type("hotel")
    assert browser.wait("(document.querySelector('#results .group') || {}).textContent === 'In your library · 1'")
    assert browser.wait("[...document.querySelectorAll('#results .hit .row-title')].some((t) => "
                        "t.textContent === 'Hotel California' && t.closest('.hit').dataset.ug)")
    mine = browser.js("[...document.querySelectorAll('#results .hit')].find((h) => h.dataset.ug === "
                      "'eagles/hotel-california').textContent")
    assert "In your library" in mine and "Wonderwall" not in browser.js("document.getElementById('results').textContent")
    assert queue.snapshot() == []  # Enter asked for nothing


def test_get_it_looks_the_song_up_and_its_row_says_how_it_goes(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")  # the address keeps the search, as it keeps the rest
    assert browser.wait(f"{HITS} >= 2")
    browser.click("#results .hit[data-ug='ryan-adams/wonderwall'] .row-action button")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", "--ug=ryan-adams/wonderwall") and args[-2:] == ("Ryan Adams", "Wonderwall")
    row = "document.querySelector('#results .progress').closest('article')"
    assert browser.wait("!!document.querySelector('#results .progress')")
    assert browser.wait(f"{row}.querySelector('.progress').dataset.tone === 'ready'", timeout=20)
    assert browser.js(f"{row}.querySelector('.row-title').textContent") == "Wonderwall"
    assert browser.wait(f"{row}.querySelector('.row-action a') && "
                        f"{row}.querySelector('.row-action a').textContent.startsWith('Sheet PDF')")
    # Back to your songs: the new song has a card of its own above the grid.
    browser.press("Escape")
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h2').textContent === 'Wonderwall'")


def test_enter_never_requests_a_song(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    browser.open(base)
    browser.js("document.getElementById('q').focus()")
    browser.type("radiohead creep")
    browser.press("Enter")
    assert browser.wait(f"{HITS} >= 1")
    browser.press("Enter")  # again, on a clear best: still a search, never a request
    time.sleep(0.6)
    assert queue.snapshot() == [] and len(asked) >= 1


def test_results_typed_over_show_only_the_newest_query(cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4), ("radiohead", "karma-police", 2), ("muse", "hysteria", 3)])
    browser.open(base)
    browser.js("document.getElementById('q').focus()")
    browser.type("creep")
    browser.press("Enter")
    browser.js("document.getElementById('q').select()")
    browser.type("karma police")  # typed over while the first answers may still be on their way
    assert browser.wait("[...document.querySelectorAll('#results .hit .row-title')].map((t) => t.textContent)"
                        ".join() === 'Karma Police'")
    time.sleep(0.5)
    assert browser.js("[...document.querySelectorAll('#results .hit .row-title')].map((t) => t.textContent)"
                      ".join()") == "Karma Police"
    assert browser.js("document.getElementById('found').dataset.query") == "karma police"


def test_escape_returns_to_the_grid_with_its_filter(cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    library(cfg, ("Radiohead", "Creep"), ("Oasis", "Wonderwall"))
    browser.open(base + "#show=wanted")
    browser.js("document.getElementById('q').focus()")
    browser.type("creep")
    browser.press("Enter")
    # Your song is the page's own row, with what its card offers (Fetch now, served).
    assert browser.wait(f"{HITS} >= 1 && document.querySelector('#results .rows .row form.fetch') !== null")
    browser.press("Escape")
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.js("document.getElementById('q').value") == "creep"
    assert browser.js(GRID) == ["Creep"]
    assert browser.js("document.querySelector('.chip[data-show=\"wanted\"]').getAttribute('aria-pressed')") == "true"
    assert browser.js("location.hash.includes('all=1')") is False
    browser.press("Escape")  # again: the search clears
    assert browser.wait(f"{GRID}.length === 2")


def test_not_in_the_list_requests_a_song_by_name_filled_in_from_the_query(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    browser.open(base)
    browser.js("document.getElementById('q').focus()")
    browser.type("Muse - Hysteria")
    browser.press("Enter")
    # Under the sites' answer, once it is in: shown before it, the answer would push it down.
    assert browser.wait("document.getElementById('request-box').getClientRects().length > 0")
    browser.click("#request-box > summary")
    fields = browser.js("['artist', 'title'].map((n) => document.querySelector(`form.request-form [name=${n}]`).value)")
    assert fields == ["Muse", "Hysteria"]
    browser.click("form.request-form button[type=submit]")
    args = posted(queue)
    assert args[-2:] == ("Muse", "Hysteria")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h2').textContent === 'Hysteria'")


NO_SIDEWAYS = "document.documentElement.scrollWidth <= innerWidth"


def test_the_bar_and_its_results_fit_a_phone(cfg, live, phone):
    base, _, _ = live
    sites(cfg, ug=[("the-red-hot-chili-peppers-and-friends", f"a-rather-long-song-title-{n}", 2) for n in range(6)],
          gtptabs=["https://gtptabs.com/tabs/18/the-red-hot-chili-peppers-and-friends/a-rather-long-song-title-1.html"],
          musescore=["https://musescore.com/song/a_rather_long_song_title_1-5"])
    phone.open(base)
    bar = ("(() => { const q = document.getElementById('q').getBoundingClientRect(), "
           "b = document.getElementById('all').getBoundingClientRect(); return [q.top, b.top, b.height, q.right <= b.left]; })()")
    q_top, button_top, button_height, side_by_side = phone.js(bar)
    assert side_by_side and abs(q_top - button_top) < 8 and button_height >= 44
    phone.js("document.getElementById('q').focus()")
    phone.type("a rather long song title 1")
    phone.press("Enter")
    assert phone.wait(f"{HITS} >= 3")
    assert phone.js(NO_SIDEWAYS)
    small = phone.js("[...document.querySelectorAll('#results button, #results a, #results summary')]"
                     ".filter((e) => e.offsetParent).map((e) => [e.textContent.trim(), e.getBoundingClientRect().height])"
                     ".filter(([, h]) => h < 44)")
    assert small == [], small


FOOTER = "(() => { const f = document.querySelector('.footer'); return f.getClientRects().length ? " \
         "Math.round(f.getBoundingClientRect().top) : null; })()"


def test_a_search_opened_from_the_address_moves_nothing_when_its_answer_comes(cfg, live, phone):
    base, _, _ = live
    sites(cfg, **WONDERWALL)
    library(cfg, ("Oasis", "Wonderwall"))
    phone.open(base + "#q=wonderwall&all=1")
    before = phone.js(FOOTER)  # the page as first drawn, before the sites' answer
    assert phone.wait(f"{HITS} >= 4 && document.querySelector('.footer').getClientRects().length > 0")
    after = phone.js(FOOTER)
    # What follows the answer waits for it: shown at once, it would jump down when the answer came.
    assert before is None or before == after, (before, after)
