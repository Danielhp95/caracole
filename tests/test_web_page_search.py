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
from urllib.parse import quote

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


class Asked(list):
    """The searches the server got; while ``held`` is an event, each next one answers once the test sets it.
    While ``lookups_held`` is one, each Get it's request is queued at once, and its answer to the page waits for
    the test to set it."""

    def __init__(self):
        super().__init__()
        self.held: threading.Event | None = None
        self.lookups_held: threading.Event | None = None


@pytest.fixture
def live(cfg):
    """The library page on a socket, its queue running ``FakeGet``; ``asked`` lists the searches it got."""
    queue = JobQueue(FakeGet(cfg))
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    asked = Asked()
    answer = app.handle

    def handle(request):
        if request.target.startswith("/api/search"):
            asked.append(request.target)
            held = asked.held
            if held is not None:
                held.wait(10)
        response = answer(request)
        if request.method == "POST" and request.target.startswith("/lookup"):
            held = asked.lookups_held
            if held is not None:
                held.wait(10)
        return response

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
    """The arguments of the first lookup the page posted (which the page may not have heard back about yet:
    ``answered``)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = queue.snapshot()
        if jobs:
            return jobs[-1].steps[0].args
        time.sleep(0.05)
    raise AssertionError("the page posted no lookup")


def answered(page, hit):
    """Whether the page has heard back about the request it posted from the result ``hit``: once it has, the
    request's line follows the job in the row, in place of its Get it, and the row is where its card comes from."""
    return page.wait(f"!document.querySelector({json.dumps(hit + ' .row-action button')})")


GRID = "[...document.querySelectorAll('#list article')].map((a) => a.querySelector('h3').textContent)"
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
    # Once done, the result's row is the song's own line, around its request line: its sheet its button.
    assert browser.js(f"{row}.querySelector('h3').textContent") == "Wonderwall"
    assert browser.wait(f"{row}.querySelector('.line-action a') && "
                        f"{row}.querySelector('.line-action a').textContent === 'Open PDF'")
    # Back to your songs: the new song has a line of its own above the list.
    browser.press("Escape")
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall'")


RYAN = "#results .hit[data-ug='ryan-adams/wonderwall']"
BUSY = "(document.getElementById('found').getAttribute('aria-busy') === 'true')"


def test_a_newer_answer_keeps_the_row_whose_request_runs_and_its_line(cfg, live, browser):
    # Enter again searches again: the list on the screen meanwhile is the older answer's. A Get it tapped there
    # keeps its row, and the row its line, when the newer answer is drawn; back to your songs, its card.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    browser.js(f"window.row = document.querySelector(\"{RYAN}\")")
    asked.held = threading.Event()  # the next answer waits until the page has the request
    browser.js("document.getElementById('q').focus()")
    browser.press("Enter")
    assert browser.wait(BUSY)  # the newer search on its way
    browser.click(f"{RYAN} .row-action button")  # on the older answer's row, as the newer is on its way
    posted(queue)
    assert browser.wait("!!window.row.querySelector('.progress')")
    assert answered(browser, RYAN)
    asked.held.set()
    assert browser.wait(f"!{BUSY}", timeout=10)  # the newer answer, drawn
    kept = browser.js(f"[document.querySelector(\"{RYAN}\") === window.row, window.row.isConnected, "
                      "!!window.row.querySelector('.progress')]")
    assert kept == [True, True, True]  # the same row, in the newer list, with its line
    assert browser.wait("window.row.querySelector('.progress').dataset.tone === 'ready'", timeout=20)
    browser.press("Escape")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall'")


def test_a_row_whose_request_runs_and_that_a_newer_answer_lacks_becomes_its_card(cfg, live, browser):
    # Typed over, the newer answer has no such row: the request's card comes under the bar, its line still going.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    asked.held = threading.Event()  # the answers wait until the page has the request
    browser.js("document.getElementById('q').select()")
    browser.type("hotel california")
    browser.press("Enter")
    assert browser.wait(BUSY)
    browser.click(f"{RYAN} .row-action button")
    posted(queue)
    assert answered(browser, RYAN)
    asked.held.set()
    assert browser.wait("document.getElementById('found').dataset.query === 'hotel california'", timeout=10)
    assert browser.js(f"document.querySelector(\"{RYAN}\")") is None  # not in the newer answer
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall' && "
                        "!!document.querySelector('#requested article .progress')")
    assert browser.wait("document.querySelector('#requested article .progress').dataset.tone === 'ready'",
                        timeout=20)


def test_a_hit_can_be_added_for_tonights_run_instead_of_got_now(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[*WONDERWALL["ug"], ("misc-mashups", "oasis-wonderwall", 1)], musescore=WONDERWALL["musescore"],
          gtptabs=[*WONDERWALL["gtptabs"], "https://gtptabs.com/tabs/18/ryan-adams/wonderwall.html"])
    library(cfg, ("Oasis", "Wonderwall"))
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 6")
    later = "#results .hit[data-ug='{}'] .row-panel .later button"
    assert browser.js(f"document.querySelector(\"{later.format('oasis/wonderwall')}\")") is None  # yours already
    # Under UG's misc-… names the song would be no one's: add it as you know it.
    assert browser.js(f"document.querySelector(\"{later.format('misc-mashups/oasis-wonderwall')}\")") is None
    assert browser.js("!!document.querySelector(\"#results .hit[data-ug='misc-mashups/oasis-wonderwall']\")")
    browser.click("#results .hit[data-ug='ryan-adams/wonderwall'] .row-more")
    browser.click(later.format("ryan-adams/wonderwall"))
    args = posted(queue)
    assert args == ("add", "--", "Ryan Adams", "Wonderwall")  # into wanted.txt, as caracole add writes it
    assert "Ryan Adams - Wonderwall" in cfg.wanted_file.read_text(encoding="utf-8")
    assert browser.wait("!!document.querySelector(\"#results .hit[data-ug='ryan-adams/wonderwall'] .progress\")")
    # gtptabs.com's songs too; MuseScore's pages are links alone.
    assert browser.js("[...document.querySelectorAll('#results .hit[data-source=\"gtptabs\"]')]"
                      ".map((h) => !!h.querySelector('.row-panel .later button'))") == [False, True]  # Oasis's is yours
    assert browser.js("document.querySelector('#results .hit[data-source=\"musescore\"] .later')") is None


def test_clearing_the_box_leaves_the_results_as_escape_does(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    browser.click("#results .hit[data-ug='ryan-adams/wonderwall'] .row-action button")
    posted(queue)
    assert answered(browser, "#results .hit[data-ug='ryan-adams/wonderwall']")
    browser.click("#clear")  # the ×: out of the results, the request on its way with a card of its own
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall'")
    assert browser.js("location.hash.includes('all=1')") is False
    # A search after it waits for its answer before what follows it shows, as after Escape.
    browser.js("window.waited = false; new MutationObserver(() => { window.waited = window.waited || "
               "document.body.classList.contains('waiting-sites'); }).observe(document.body, { attributes: true })")
    browser.type("creep")
    browser.press("Enter")
    assert browser.wait("document.getElementById('found').dataset.query === 'creep'")
    assert browser.js("window.waited") is True


@pytest.mark.parametrize("leave", ["clear", "escape", "typed over"])
def test_a_get_it_whose_row_leaves_the_results_before_the_page_hears_back_still_gets_its_card(cfg, live, browser,
                                                                                              leave):
    # Get it, then at once the ×, Escape or a newer search without the row, before the server's answer reaches the
    # page: once it does, the request has its card under the bar, its line going on there, as it would have had
    # if the answer had come first.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    asked.lookups_held = threading.Event()
    browser.click(f"{RYAN} .row-action button")
    posted(queue)  # queued; the page hasn't heard back
    if leave == "clear":
        browser.click("#clear")
        assert browser.wait("document.getElementById('results').hidden")
    elif leave == "escape":
        browser.js("document.getElementById('q').focus()")
        browser.press("Escape")
        assert browser.wait("document.getElementById('results').hidden")
    else:
        browser.js("document.getElementById('q').select()")
        browser.type("hotel california")
        browser.press("Enter")
        assert browser.wait("document.getElementById('found').dataset.query === 'hotel california'")
        assert browser.js(f"document.querySelector(\"{RYAN}\")") is None  # not in the newer answer
    assert browser.js("document.getElementById('requested').hidden") is True  # nothing to show yet
    asked.lookups_held.set()
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall' && "
                        "!!document.querySelector('#requested article .progress')")
    assert browser.wait("document.querySelector('#requested article .progress').dataset.tone === 'ready'",
                        timeout=20)
    assert browser.js("document.querySelectorAll('#requested article').length") == 1


def test_a_get_it_on_a_row_a_newer_answer_has_too_keeps_its_line_in_that_answers_row(cfg, live, browser):
    # Enter again while a Get it is on its way, and the newer answer drawn before the page hears back: the newer
    # answer's row for the song is the one that says how the request goes, and no card comes under the bar.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    browser.js(f"window.row = document.querySelector(\"{RYAN}\")")
    asked.lookups_held = threading.Event()
    browser.click(f"{RYAN} .row-action button")
    posted(queue)
    browser.js("document.getElementById('q').focus()")
    browser.press("Enter")
    assert browser.wait(f"!{BUSY} && document.querySelector(\"{RYAN}\") !== window.row")  # drawn anew
    asked.lookups_held.set()
    assert browser.wait(f"document.querySelector(\"{RYAN}\") === window.row && "
                        f"!!document.querySelector(\"{RYAN} .progress\")")
    assert browser.js(f"document.querySelectorAll(\"{RYAN}\").length") == 1
    assert browser.wait("window.row.querySelector('.progress').dataset.tone === 'ready'", timeout=20)
    assert browser.js("document.getElementById('requested').hidden") is True


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
    # Your song is the page's own line, with all it offers (Fetch now, served).
    assert browser.wait(f"{HITS} >= 1 && document.querySelector('#results .rows .line form.fetch') !== null")
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
                        "document.querySelector('#requested article h3').textContent === 'Hysteria'")


def test_the_line_for_an_artist_the_index_cant_see_shows_its_commands_as_code(cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    for url, hint in ((base + "#q=" + quote("宋冬野") + "&all=1", "#results .index-hint"),
                      (base + "lookup?q=" + quote("宋冬野"), "#results .hint")):
        browser.open(url)
        assert browser.wait(f"!!document.querySelector('{hint}')"), url
        assert "`" not in browser.js(f"document.querySelector('{hint}').textContent")
        assert "caracole add" in browser.js(f"[...document.querySelectorAll('{hint} code')].map((c) => c.textContent)")


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
