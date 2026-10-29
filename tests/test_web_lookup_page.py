"""caracole/web/lookup_page.py: the page that searches as you type and shows a sheet the moment it's kept.

The page is served by a real ``caracole serve`` app on a socket and run in a headless
Chromium, when this machine has one. The queue's runner stands in for ``caracole get``:
it writes the sheet into the library and prints the progress the real one prints.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from urllib.parse import quote

import helpers.browser
import pytest
from helpers.browser import in_chromium

from caracole import db
from caracole.get import PROGRESS_PREFIX
from caracole.ug.index import mark_built, upsert_rows
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue, lookup_steps
from caracole.web.lookup_page import LOOKUP_CSP, SCRIPT, STYLE, lookup_page
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

SHEET = "[Intro]\nAm   F   C   G\nwalking down the river road tonight\n"


def test_the_page_carries_its_token_and_allows_its_own_script_and_style_alone():
    page = lookup_page('to"k<')
    assert 'data-csrf="to&quot;k&lt;"' in page and 'value="to&quot;k&lt;"' in page
    assert f"<script>{SCRIPT}</script>" in page and f"<style>{STYLE}</style>" in page
    assert "default-src 'none'" in LOOKUP_CSP and "connect-src 'self'" in LOOKUP_CSP
    assert "innerHTML" not in SCRIPT and "eval(" not in SCRIPT


def test_the_page_opens_with_the_one_line_header_and_no_paragraph_before_the_search():
    page = lookup_page("tok")
    header = re.search(r'<header class="top">(.*?)</header>', page, re.S).group(1)
    assert "<h1>Look up a song</h1>" in header and 'class="mark"' in header
    assert re.findall(r'<a class="navlink" href="([^"]*)">([^<]*)', header) == [("/", "Library"), ("/#tab=requests", "Requests")]
    assert 'class="lede"' not in page and "offline copies" not in page and 'class="masthead"' not in page


def test_a_screen_reader_hears_the_progress_line_and_not_the_whole_sheet_again():
    # The reader holds the sheet: a live region around it would read the whole sheet out at each step.
    page = lookup_page("tok")
    reader = re.search(r'<section class="reader"[^>]*>', page).group(0)
    assert "aria-live" not in reader
    said = re.search(r'<p class="said"[^>]*>', page)
    assert said and 'aria-live="polite"' in said.group(0) and 'role="status"' in said.group(0)
    assert 'id="said"' in said.group(0) and 'getElementById("said")' in SCRIPT  # the same node throughout


class FakeGet:
    """``caracole get``: keeps the sheet in the library, and says so as the real one does."""

    def __init__(self, cfg):
        self.cfg = cfg

    def __call__(self, args, emit):
        folder = self.cfg.library_dir / "Radiohead" / "Creep"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sheet.txt").write_text(SHEET + "<b>not markup</b>\n", encoding="utf-8")
        for event in ({"stage": "song", "state": "done", "detail": "added to wanted.txt, line 1"},
                      {"song": {"id": 1, "display": "Radiohead - Creep"}},
                      {"stage": "sheet", "state": "done", "detail": "tab 4169 from Ultimate Guitar"},
                      {"files": {"sheet": "Radiohead/Creep/sheet.txt"}, "seconds": 1.8}):
            emit(PROGRESS_PREFIX + json.dumps(event))
        return 0


@pytest.fixture
def served(cfg):
    queue = JobQueue(FakeGet(cfg))
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False)
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # stops within 10 ms
    yield server, queue
    server.shutdown()
    server.server_close()


def dump_dom(url: str, tmp_path) -> str:
    """The page's DOM once its timers ran for 5 s of virtual time, in a browser context of its own
    (helpers/browser.py)."""
    return helpers.browser.dump_dom(url, (1000, 900), budget_ms=5000)


def shown(dom: str, element: str, until: str | None = None) -> str:
    """What the browser shows in an element (up to ``until``, for one that holds others of its kind)."""
    end = re.escape(until) if until else f"</{element.split()[0]}>"
    found = re.search(rf'<{element}[^>]*>(.*?){end}', dom, re.S)
    assert found, dom[-3000:]
    return found.group(1)


@in_chromium
def test_a_lookup_shows_its_stages_and_the_sheet_in_a_real_browser(cfg, served, tmp_path):
    server, queue = served
    queue.submit("Fetch Radiohead - Creep", "radiohead/creep", lookup_steps("Radiohead", "Creep"), fetching=True)
    queue.run_pending()

    dom = dump_dom(f"http://127.0.0.1:{server.server_address[1]}/lookup?job=1", tmp_path)

    reader = shown(dom, 'section class="reader"')
    assert "Radiohead - Creep" in reader and "Done." in reader
    assert "walking down the river road tonight" in shown(dom, 'pre class="sheet"')
    assert "&lt;b&gt;not markup&lt;/b&gt;" in reader and "<b>not markup</b>" not in reader  # text, never markup
    assert re.search(r'class="stage done"[^>]*>The sheet<', reader)
    assert 'href="/Radiohead/Creep/sheet.txt"' in reader


@in_chromium
def test_a_lookup_cancelled_on_the_requests_page_says_so(cfg, served, tmp_path):
    server, queue = served
    queue.submit("Fetch Radiohead - Creep", "radiohead/creep", lookup_steps("Radiohead", "Creep"), fetching=True)
    queue.cancel(1)

    dom = dump_dom(f"http://127.0.0.1:{server.server_address[1]}/lookup?job=1", tmp_path)

    reader = shown(dom, 'section class="reader"')
    assert "Cancelled before it ran: look it up again to get it." in reader and "No sheet this time" not in reader


@in_chromium
def test_the_search_lists_the_offline_index_as_you_type_in_a_real_browser(cfg, served, tmp_path):
    server, _ = served
    conn = db.connect(cfg.db_path)
    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(4169, "radiohead", "creep", "chords", "radiohead/creep-chords-4169"),
                       (5001, "stone-temple-pilots", "creep", "chords", "stone-temple-pilots/creep-chords-5001")],
                "1", when)
    mark_built(conn, when)
    conn.close()

    dom = dump_dom(f"http://127.0.0.1:{server.server_address[1]}/lookup?q={quote('creep')}", tmp_path)

    results = shown(dom, 'div id="results"', until='<details class="by-name"')
    assert "On Ultimate Guitar" in results
    assert results.index("Radiohead") < results.index("Stone Temple Pilots")
    assert results.count(">Get it<") == 2 and "1 chords" in results
    # A screen reader moving through the buttons hears which song each one gets.
    assert 'aria-label="Get Radiohead - Creep from Ultimate Guitar"' in results
    assert 'aria-label="Versions of Stone Temple Pilots - Creep"' in results
    # Each version numbered in its kind, with a link to preview it on UG before picking it.
    assert ">Chords 1 of 1<" in results
    assert 'href="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"' in results


@in_chromium
def test_why_a_stage_waits_or_was_left_is_written_out_not_only_in_a_tooltip(cfg, tmp_path):
    release = threading.Event()

    def runner(args, emit):
        emit(PROGRESS_PREFIX + json.dumps({"stage": "song", "state": "running",
                                           "detail": "waiting for another caracole (pid 42: run)"}))
        release.wait(20)
        for event in ({"stage": "song", "state": "done", "detail": "in the library"},
                      {"stage": "sheet", "state": "skipped", "detail": "the lookup requests are spent"},
                      {"stage": "lacuerda", "state": "failed", "detail": "LaCuerda failed (HTTP 500)"}):
            emit(PROGRESS_PREFIX + json.dumps(event))
        return 0

    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False)
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # stops within 10 ms
    try:
        queue.submit("Fetch Radiohead - Creep", "radiohead/creep", lookup_steps("Radiohead", "Creep"), fetching=True)
        url = f"http://127.0.0.1:{server.server_address[1]}/lookup?job=1"
        waiting = dump_dom(url, tmp_path / "1")
        assert "waiting for another caracole (pid 42: run)" in shown(waiting, 'p class="said"')
        release.set()
        for _ in range(100):
            if not queue.active_count():
                break
            threading.Event().wait(0.05)
        done = dump_dom(url, tmp_path / "2")
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        queue.stop()
    why = shown(done, 'details class="why"')
    assert "the lookup requests are spent" in why and "LaCuerda failed (HTTP 500)" in why
    assert not re.search(r'<details class="why"[^>]*hidden', done)


# --- typing, pressing Enter, picking: a page driven as you would ----------------------------------------


def index_songs(cfg, songs):
    """The offline index: each (artist key, song key, how many chords versions)."""
    conn = db.connect(cfg.db_path)
    when = datetime(2026, 10, 19, tzinfo=UTC)
    rows, n = [], 1000
    for artist, song, versions in songs:
        for _ in range(versions):
            n += 1
            rows.append((n, artist, song, "chords", f"{artist}/{song}-chords-{n}"))
    upsert_rows(conn, rows, "1", when)
    mark_built(conn, when)
    conn.close()


@pytest.fixture
def live(cfg):
    """The lookup page on a socket, its queue running the fake ``caracole get``."""
    queue = JobQueue(FakeGet(cfg))
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False)
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # stops within 10 ms
    yield f"http://127.0.0.1:{server.server_address[1]}", queue
    server.shutdown()
    server.server_close()
    queue.stop()


@pytest.fixture
def browser(tmp_path):
    from helpers.browser import Browser, BrowserError

    try:
        page = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    yield page
    page.close()


@pytest.fixture
def phone(tmp_path):
    from helpers.browser import Browser, BrowserError

    try:
        page = Browser(tmp_path / "chrome-phone", width=390, height=844, mobile=True)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    yield page
    page.close()


def posted(queue, timeout=10.0):
    """The arguments of the first lookup the page posted."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = queue.snapshot()
        if jobs:
            return jobs[-1].steps[0].args
        time.sleep(0.05)
    raise AssertionError("the page posted no lookup")


HITS = "document.querySelectorAll('#results .hit').length"


@in_chromium
def test_enter_right_after_typing_looks_up_what_you_typed_not_the_results_before(cfg, live, browser):
    import time

    base, queue = live
    index_songs(cfg, [("eagles", "hotel-california", 9), ("eagles", "desperado", 3), ("eagles", "take-it-easy", 2)])
    browser.open(base + "/lookup")
    browser.type("eagles")
    assert browser.wait(f"{HITS} > 0")
    # An artist's name alone: the artist comes first, its most tabbed song said.
    assert browser.js("document.querySelector('#results .hit .row-title').textContent") == "Eagles"
    assert "Hotel California" in browser.js("document.querySelector('#results .artist-hit').textContent")
    browser.type(" desperado")
    browser.js("document.getElementById('q').dispatchEvent(new KeyboardEvent('keydown', "
               "{ key: 'Enter', keyCode: 229, isComposing: true, bubbles: true, cancelable: true }))")
    time.sleep(0.5)
    assert queue.snapshot() == []  # the Enter that ends a pinyin word is still typing
    browser.press("Enter")  # at once: the results on the screen are still the ones for "eagles"
    args = posted(queue)
    assert args[-2:] == ("Eagles", "Desperado"), args


@in_chromium
def test_a_page_left_open_across_a_restart_says_to_reload_it(cfg, browser):
    queue = JobQueue(FakeGet(cfg))
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False)
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # stops within 10 ms
    try:
        index_songs(cfg, [("radiohead", "creep", 2)])
        browser.open(f"http://127.0.0.1:{server.server_address[1]}/lookup")
        app.csrf = "the restarted server's"  # the page still holds the old form token
        browser.type("creep")
        assert browser.wait(f"{HITS} > 0")
        browser.click("#results .hit button.primary")
        assert browser.wait("/reload/i.test(document.getElementById('said').textContent)")
        said = browser.js("document.getElementById('said').textContent")
        link = browser.js("[...document.querySelectorAll('#files a')].map(a => a.textContent).join()")
    finally:
        server.shutdown()
        server.server_close()
    assert "older than the server" in said and "Unexpected token" not in said
    assert link == "Reload the page"
    assert queue.snapshot() == []


@in_chromium
def test_your_librarys_song_found_on_ug_under_another_name_is_looked_up_as_itself(cfg, live, browser):
    from caracole.songs import update_song

    from conftest import add_song

    base, queue = live
    index_songs(cfg, [("acdc", "back-in-black", 4)])
    conn = db.connect(cfg.db_path)
    acdc = add_song(conn, "AC/DC", "Back In Black")  # its line taken off wanted.txt since
    update_song(conn, acdc.id, match_decision="accept", match_artist_key="acdc", match_song_key="back-in-black")
    conn.close()
    browser.open(base + "/lookup")
    browser.type("back in black")
    assert browser.wait("[...document.querySelectorAll('#results .hit button')].some(b => /again/.test(b.textContent))")
    browser.click("#results .hit:last-child button.primary")
    args = posted(queue)
    assert args[-3:] == ("--", "AC/DC", "Back In Black") and "--ug=acdc/back-in-black" in args
    assert not cfg.wanted_file.exists()  # no second song, and no line back for it


SHEET_TOP = ("(() => { const s = document.getElementById('sheet'); if (s.hidden || !s.textContent) return null; "
             "const r = s.getBoundingClientRect(), bar = document.querySelector('.search').getBoundingClientRect(); "
             "return [r.top, bar.bottom, innerHeight]; })()")


@in_chromium
def test_on_a_phone_the_sheet_you_picked_is_on_the_screen_once_it_arrives(cfg, live, phone):
    import time

    base, _ = live
    index_songs(cfg, [(f"artist-{n}", "creep", 9 - n) for n in range(8)] + [("radiohead", "creep", 12)])
    conn = db.connect(cfg.db_path)
    from conftest import add_song

    for n in range(5):
        add_song(conn, f"Band {n}", "Creep", source_id=f"band-{n}")
    conn.close()
    phone.open(base + "/lookup")
    phone.type("creep")
    assert phone.wait(f"{HITS} >= 10")
    phone.click("#results .hits:nth-last-child(1 of .hits) .hit button.primary")  # the last list, whatever follows
    assert phone.wait(SHEET_TOP + " !== null")
    time.sleep(0.8)  # any smooth scroll ends
    top, bar, height = phone.js(SHEET_TOP)
    assert bar - 1 <= top and top + 24 <= height, (top, bar, height)  # its first line, below the search box


@in_chromium
def test_the_results_are_the_librarys_rows_and_a_song_you_have_opens_its_viewer(cfg, live, browser):
    from helpers.rendered import rendered_song

    base, queue = live
    conn = db.connect(cfg.db_path)
    rendered_song(conn, cfg)  # Soda Stereo - De Música Ligera, its viewer the one caracole wrote
    conn.close()
    index_songs(cfg, [("soda-stereo", "de-musica-ligera", 2)])
    browser.open(base + "/lookup")
    browser.type("musica ligera")
    assert browser.wait(f"{HITS} >= 2")
    # index.html's own row renderer and source marks (library_page.ROWS_SCRIPT): one look for every list.
    assert browser.js("Object.keys(window.caracole).sort().join()") == "icons,resultRow,sourceMark"
    assert browser.js("document.querySelectorAll('#results .rows > article.row.hit').length") >= 2
    marks = browser.js("[...document.querySelectorAll('#results .hit > .source')].map(m => m.dataset.source)")
    assert marks == ["ug", "ug"]  # your song's sheet came from UG, and so does the UG song
    main = browser.js("document.querySelector('#results .hit .row-action .primary').getAttribute('href')")
    assert main == "Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.html"
    # Its title opens the same, as in index.html; an Ultimate Guitar song's title is no link: it gets it, as Get it does.
    titles = browser.js("[...document.querySelectorAll('#results .hit .title-link')].map(a => a.getAttribute('href'))")
    assert titles == [main]
    browser.press("Enter")  # the first result: your song, opened as its card opens it
    assert browser.wait("location.pathname.endsWith('/sheet.html')")
    assert browser.wait("document.querySelector('h1') && document.querySelector('h1').textContent === "
                        "'De Música Ligera'")
    assert queue.snapshot() == []  # opening it asked for nothing


# Each row of the results: whether it is a song you have, its name's colour against the page's (--text, --muted), the
# wash behind it (--accent at --have-tint) and the width of its pill ("In your library", or "Found").
HAVE_ROWS = """
(() => {
  const probe = (css) => { const p = document.createElement('i'); p.style.cssText = css; document.body.appendChild(p);
    const s = getComputedStyle(p); const got = [s.color, s.backgroundColor]; p.remove(); return got; };
  const ink = probe('color: var(--text)')[0], quiet = probe('color: var(--muted)')[0];
  const tint = probe('background-color: color-mix(in srgb, var(--accent) var(--have-tint), var(--surface))')[1];
  return [...document.querySelectorAll('#results .rows > article.row.hit')].map((a) => {
    const name = getComputedStyle(a.querySelector('.row-title')), row = getComputedStyle(a), pill = a.querySelector('.badge.found');
    return { have: a.classList.contains('have'), ink: name.color === ink, quiet: name.color === quiet,
      tinted: row.backgroundColor === tint && tint !== 'rgba(0, 0, 0, 0)', pill: pill ? pill.getBoundingClientRect().width : null };
  });
})()
"""


@in_chromium
def test_a_song_you_have_stands_out_from_the_ones_you_have_not_on_the_lookup_page_too(cfg, live, browser):
    from helpers.rendered import rendered_song

    from caracole.songs import update_song
    from conftest import add_song

    base, _ = live
    conn = db.connect(cfg.db_path)
    found = rendered_song(conn, cfg)  # Soda Stereo - De Música Ligera, a sheet kept
    update_song(conn, found.id, status="found")
    wanted = add_song(conn, "Radiohead", "Creep")  # yours, nothing kept yet
    update_song(conn, wanted.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    conn.close()
    index_songs(cfg, [("soda-stereo", "de-musica-ligera", 2), ("radiohead", "creep", 2), ("oasis", "creep", 1)])
    browser.open(base + "/lookup")
    browser.type("musica ligera")
    assert browser.wait(f"{HITS} >= 2")
    rows = browser.js(HAVE_ROWS)
    assert len(rows) == 2 and all(r["have"] and r["ink"] and r["tinted"] for r in rows), rows  # its row and UG's
    assert all(0 < r["pill"] <= 1 for r in rows), rows  # "Found", "In your library": said to a screen reader alone
    browser.open(base + "/lookup")
    browser.type("creep")
    assert browser.wait(f"{HITS} >= 2")
    rows = browser.js(HAVE_ROWS)
    assert rows and not any(r["have"] or r["tinted"] or r["ink"] for r in rows) and all(r["quiet"] for r in rows), rows


@in_chromium
def test_a_row_for_one_instrument_says_which_on_the_lookup_page_too(cfg, live, browser):
    # UG's Ukulele Chords of a song, and a song of yours with a harmonica tab: each says its instrument, as the library
    # page's search does; a UG song of chords alone says nothing.
    from conftest import add_song

    from caracole.library import keep_file
    from caracole.versions import upsert_version

    base, queue = live
    index_songs(cfg, [("radiohead", "creep", 2), ("radiohead", "high-and-dry", 1)])
    conn = db.connect(cfg.db_path)
    upsert_rows(conn, [(9001, "radiohead", "creep", "ukulele", "radiohead/creep-ukulele-9001")], "ukulele1",
                datetime(2026, 10, 19, tzinfo=UTC))
    song = add_song(conn, "Radiohead", "Creep (Acoustic)")
    tab = upsert_version(conn, provider="harptabs", tab_id="5", song_id=song.id, slot="guitar", kind="harmonica",
                         rating=0, votes=0, version=1, label=None, url="https://www.harptabs.com/tab/5/creep", raw={},
                         now="2026-10-19T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=tab, name="harmonica-1.txt", data=b"4 5 6\n", rank=1)
    conn.commit()
    conn.close()
    browser.open(base + "/lookup")
    browser.type("radiohead creep")
    assert browser.wait(f"{HITS} >= 2")
    marks = browser.js("[...document.querySelectorAll('#results .hit')].map(a => [a.querySelector('h2').textContent, "
                       "[...a.querySelectorAll('.badge.instrument')].map(b => b.textContent)])")
    assert ["Creep (Acoustic)", ["Harmonica"]] in marks and ["Creep", ["Ukulele"]] in marks
    assert queue.snapshot() == []


# The page's fetch, each POST noted (its path and form) and never sent.
NOTE_POSTS = ("(() => { window.posts = []; const real = window.fetch; window.fetch = (url, init) => { "
              "if (init && init.method === 'POST') { window.posts.push([String(url), String(init.body)]); "
              "return new Promise(() => {}); } return real(url, init); }; })()")


@in_chromium
def test_a_songs_name_looks_it_up_as_its_get_it_does(cfg, live, browser):
    base, queue = live
    index_songs(cfg, [("radiohead", "creep", 3)])
    pressed = {}
    for what in ("get it", "name"):
        browser.js("window.before = true")
        browser.open(base + "/lookup")
        assert browser.wait("!window.before")
        browser.type("creep")
        assert browser.wait("!!document.querySelector(\"#results .hit[data-ug='radiohead/creep']\")")
        browser.js(NOTE_POSTS)
        hit = "#results .hit[data-ug='radiohead/creep']"
        browser.click(f"{hit} .row-title button.title-get" if what == "name" else f"{hit} .row-action button")
        assert browser.wait("window.posts.length === 1 && document.getElementById('reader-title').textContent === "
                            "'Radiohead - Creep'")
        pressed[what] = browser.js("window.posts")
    assert pressed["name"] == pressed["get it"] and pressed["name"][0][0] == "/lookup"
    name = "document.querySelector(\"#results .hit[data-ug='radiohead/creep'] .row-title button\")"
    assert browser.js(f"{name}.getAttribute('aria-label')") == "Get Radiohead - Creep"
    assert browser.js(f"{name}.closest('h2').textContent") == "Creep"
    assert queue.snapshot() == []  # noted, never sent


ARTIST_NAME = "(document.querySelector('#results .artist-head h2') || {}).textContent"


@in_chromium
def test_enter_on_an_artists_name_lists_their_songs_and_asks_for_nothing(cfg, live, browser):
    base, queue = live
    index_songs(cfg, [("eagles", "hotel-california", 9), ("eagles", "desperado", 3), ("third-day", "eagles", 2)])
    browser.open(base + "/lookup")
    browser.type("eagles")
    assert browser.wait(f"{HITS} > 0")
    browser.press("Enter")
    assert browser.wait(f"{ARTIST_NAME} === 'Eagles'")
    titles = browser.js("[...document.querySelectorAll('#results .hit .row-title')].map(t => t.textContent)")
    assert titles == ["Hotel California", "Desperado"]  # theirs, the most tabbed first: not Third Day's Eagles
    assert browser.js("document.getElementById('status').textContent") == "Eagles: 2 songs."
    browser.press("Enter")  # again: still nothing asked for
    import time

    time.sleep(0.5)
    assert queue.snapshot() == []
    browser.click("#results .artist-head button")  # All results
    assert browser.wait("document.querySelector('#results .artist-hit') !== null")
    assert browser.js("document.activeElement.id") == "q"


@in_chromium
def test_the_songs_of_an_artist_row_can_be_listed_and_got(cfg, live, browser):
    base, queue = live
    index_songs(cfg, [("wonderwall", "in-april", 2), ("oasis", "wonderwall", 9), ("ryan-adams", "wonderwall", 3)]
                + [("wonderwall", f"song-{n:02d}", 1) for n in range(60)])
    browser.open(base + "/lookup")
    browser.type("wonderwall")
    assert browser.wait(f"{HITS} > 0")
    rows = browser.js("[...document.querySelectorAll('#results .hit .row-title')].map(t => t.textContent)")
    assert rows == ["Wonderwall", "Wonderwall", "Wonderwall"] and browser.js(
        "[...document.querySelectorAll('#results .hit')].pop().classList.contains('artist-hit')")  # after the songs
    browser.click("#results .artist-hit button.primary")  # Songs
    assert browser.wait(f"{ARTIST_NAME} === 'Wonderwall'")
    assert browser.js("document.activeElement.textContent") == "Wonderwall"  # the list's heading, for a reader
    assert browser.js(HITS) == 50 and browser.js("document.querySelector('.more-songs button').textContent") == (
        "Show more (11 left)")
    browser.click(".more-songs button")
    assert browser.wait(f"{HITS} === 61 && !document.querySelector('.more-songs')")
    browser.click("#results .hit button.primary")  # its most tabbed song, In April: looked up now
    args = posted(queue)
    assert args[-2:] == ("Wonderwall", "In April") and "--ug=wonderwall/in-april" in args


@in_chromium
def test_enter_with_no_clear_best_asks_for_nothing_and_says_so(cfg, live, browser):
    import time

    base, queue = live
    index_songs(cfg, [("radiohead", "karma-police", 3)])
    browser.open(base + "/lookup")
    browser.type("police karma")
    assert browser.wait(f"{HITS} > 0")
    browser.press("Enter")
    assert browser.wait("/Nothing stands out/.test(document.getElementById('status').textContent)")
    time.sleep(0.5)
    assert queue.snapshot() == []


SKYNYRD = [("lynyrd-skynyrd", "free-bird", 4), ("lynyrd-skynyrd", "simple-man", 2), ("lynyrd-skynyrd", "tuesdays-gone", 1),
           ("lynyrd-skynyrd", "that-smell", 1), ("lynyrd-skynyrd", "workin-for-mca", 1), ("sam-grow", "skynyrd", 1)]


@in_chromium
def test_a_word_of_an_artists_name_leads_with_them_and_enter_lists_their_songs(cfg, live, browser):
    import time

    base, queue = live
    index_songs(cfg, SKYNYRD)
    browser.open(base + "/lookup")
    browser.type("skynyrd")
    assert browser.wait("document.querySelector('#results .artist-hit') !== null")
    groups = browser.js("[...document.querySelectorAll('#results h2.group')].map(h => h.textContent)")
    # The artist first, Sam Grow's song after; LaCuerda's listings not read to L, Ask LaCuerda under them.
    assert groups == ["Artists on Ultimate Guitar", "On Ultimate Guitar"]
    assert browser.js("document.querySelector('#results .looked-line .ask-lacuerda').textContent") == \
        "Ask LaCuerda for “Lynyrd Skynyrd” (1 request)"
    browser.press("Enter")
    assert browser.wait(f"{ARTIST_NAME} === 'Lynyrd Skynyrd'")
    time.sleep(0.5)
    assert queue.snapshot() == []


@in_chromium
def test_a_close_spelling_says_did_you_mean_and_the_name_lists_their_songs(cfg, live, browser):
    import time

    base, queue = live
    index_songs(cfg, SKYNYRD)
    browser.open(base + "/lookup")
    browser.type("lynrd")
    assert browser.wait("document.querySelector('#results .did-you-mean') !== null")
    # A group of the page's own, "Did you mean", an artist's row each (UG's mark, their songs counted, Their songs),
    # then what found nothing: its band and line.
    assert browser.js("[...document.querySelectorAll('#results h2.group')].map(h => h.textContent)") == [
        "Did you mean", "Not on the sites · searched 5"]
    assert browser.js("[...document.querySelectorAll('#results .suggestion')].map((s) => [s.querySelector("
                      "'.row-title').textContent, s.querySelector('.source').dataset.source, s.querySelector("
                      "'.row-facts').textContent, s.querySelector('.row-action button').textContent])") == [
        ["Lynyrd Skynyrd", "ug", "5 songs on UG", "Their songs"]]
    assert browser.js("[...document.querySelectorAll('#results > section')].map((s) => s.className)") == [
        "did-you-mean", "nothing"]
    assert browser.js(HITS) == 0
    browser.press("Enter")  # nothing stands out: Enter takes no suggestion, and asks for nothing
    time.sleep(0.5)
    assert browser.js(f"{ARTIST_NAME} === undefined") and queue.snapshot() == []
    browser.click("#results .did-you-mean .their-songs")
    assert browser.wait(f"{ARTIST_NAME} === 'Lynyrd Skynyrd'")
    assert browser.js("document.getElementById('by-name-box').checkVisibility()")  # their songs: the form under them
    assert browser.js("[...document.querySelectorAll('#results .hit .row-title')].map(t => t.textContent)") == [
        "Free Bird", "Simple Man", "That Smell", "Tuesdays Gone", "Workin For Mca"]
    assert queue.snapshot() == []


NO_SIDEWAYS = "document.documentElement.scrollWidth <= innerWidth"


@in_chromium
def test_an_artists_list_fits_a_phone_and_its_buttons_take_a_thumb(cfg, live, phone):
    base, _ = live
    index_songs(cfg, [("the-red-hot-chili-peppers-and-friends-of-the-band", f"a-rather-long-song-title-{n}", 3 - n % 3)
                      for n in range(60)])
    phone.open(base + "/lookup")
    phone.type("the red hot chili peppers and friends of the band")
    assert phone.wait(f"{HITS} > 0")
    assert phone.js(NO_SIDEWAYS)
    phone.press("Enter")
    assert phone.wait("document.querySelector('#results .artist-head') !== null")
    assert phone.js(NO_SIDEWAYS)
    heights = phone.js("[...document.querySelectorAll('.artist-head .btn, .more-songs .btn')]"
                       ".map(b => b.getBoundingClientRect().height)")
    assert len(heights) == 2 and min(heights) >= 44, heights
    small = phone.js("[...document.querySelectorAll('#results .row .btn, #results .row .row-more')]"
                     ".filter(b => b.getClientRects().length)"
                     ".map(b => [b.textContent.trim(), Math.round(b.getBoundingClientRect().width),"
                     " Math.round(b.getBoundingClientRect().height)]).filter(([, w, h]) => w < 44 || h < 44)")
    assert small == [], small  # each song's Get it and its "⋯" too


@in_chromium
def test_on_a_touch_phone_every_control_is_a_thumbs_size_and_every_field_has_an_edge(cfg, live, phone):
    from helpers.rendered import rendered_song
    from helpers.targets import UNFOLD, small_targets, weak_edges

    base, _ = live
    conn = db.connect(cfg.db_path)
    rendered_song(conn, cfg)  # a song of yours, its files under its row's "⋯"
    conn.close()
    index_songs(cfg, [("soda-stereo", "de-musica-ligera", 3)])  # and UG's, its versions under its "⋯"
    phone.open(base + "/lookup")
    phone.type("musica ligera")
    assert phone.wait(f"{HITS} >= 2")
    phone.js("(() => {" + UNFOLD + "})()")
    # The brand above the title goes where the Library link beside it goes, which is a thumb's size.
    short = phone.js(small_targets(".app a"))
    assert short == [], short
    phone.js("document.activeElement.blur()")  # every field at rest, the search field too
    for scheme in ("light", "dark"):
        phone.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
        weak = phone.js(weak_edges())  # the search field too: this page's own, a field like the others
        assert weak == [], (scheme, weak)


@in_chromium
def test_a_rows_artist_searches_for_them_as_typing_their_name_would(cfg, live, browser):
    base, queue = live
    index_songs(cfg, [("c-tangana", "los-tontos", 3), ("c-tangana", "tu-me-dejaste-de-querer", 5),
                      ("kase-o", "esto-no-para", 2)])
    browser.open(base + "/lookup")
    browser.type("los tontos")
    hit = "#results .hit[data-ug='c-tangana/los-tontos']"
    assert browser.wait(f"!!document.querySelector(\"{hit}\")")
    assert browser.js(f"document.querySelector(\"{hit} .row-artist\").textContent") == "C Tangana"
    browser.click(f"{hit} button.row-artist")
    assert browser.wait("document.getElementById('q').value === 'C Tangana'")
    # Their row first, as an artist's name typed whole leads, the box keeping the focus; nothing asked of a site.
    assert browser.wait("(document.querySelector('#results .hit .row-title') || {}).textContent === 'C Tangana'")
    assert browser.js("document.activeElement.id") == "q"
    assert queue.snapshot() == []


class Held:
    """The lookup page on a socket, whose answers to ``target`` wait until the test lets them go (``go``): a slow
    network, a poll or a sheet on its way. ``asked`` notes each request, and ``answered`` each held one sent."""

    def __init__(self, cfg, queue, target):
        import time

        self.go = threading.Event()
        self.asked: list[tuple[float, str]] = []
        self.answered: list[float] = []
        app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False)
        real = app.handle

        def handle(request):
            self.asked.append((time.monotonic(), request.target))
            if request.target != target:
                return real(request)
            self.go.wait(20)
            try:
                return real(request)
            finally:
                self.answered.append(time.monotonic())

        app.handle = handle
        self.server = make_server(app, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def polls(self, target, since=0.0):
        return sum(1 for at, asked in self.asked if asked == target and at > since)

    def until(self, check, timeout=10.0):
        import time

        deadline = time.monotonic() + timeout
        while not check():
            assert time.monotonic() < deadline, self.asked
            time.sleep(0.02)

    def close(self):
        self.go.set()
        self.server.shutdown()
        self.server.server_close()


ASKS_BY_NAME = ("(() => { const f = document.getElementById('by-name'); f.artist.value = 'Soda Stereo'; "
                "f.title.value = 'Musica Ligera'; f.requestSubmit(); })()")
TITLE = "document.getElementById('reader-title').textContent"


@in_chromium
def test_a_new_lookup_stops_following_the_one_before_even_with_its_answer_on_the_way(cfg, browser):
    # Job 1 waits in the queue, the page following it; its poll is on its way (a phone's slow Wi-Fi) when you look
    # another song up. Its answer, come late, is the old request's: the reader stays on the new one, and job 1 is
    # never asked about again.
    queue = JobQueue(FakeGet(cfg))  # never started: every job waits
    queue.submit("Fetch Radiohead - Creep", "radiohead/creep", lookup_steps("Radiohead", "Creep"), fetching=True,
                 display="Radiohead - Creep", song_id=1)
    held = Held(cfg, queue, "/api/jobs/1")
    try:
        browser.open(held.base + "/lookup?job=1")
        held.until(lambda: held.polls("/api/jobs/1"))  # its poll is on its way
        browser.js(ASKS_BY_NAME)
        assert browser.wait(f"{TITLE} === 'Soda Stereo - Musica Ligera'")
        held.until(lambda: held.polls("/api/jobs/2") >= 1)
        held.go.set()
        held.until(lambda: held.answered)
        heard = held.answered[0]
        held.until(lambda: held.polls("/api/jobs/2", since=heard) >= 3)  # the page has gone on a while since
        assert browser.js(TITLE) == "Soda Stereo - Musica Ligera"
        assert browser.js("document.getElementById('said').textContent") == "Waiting for the request before it…"
        assert held.polls("/api/jobs/1", since=heard) == 0, held.asked
    finally:
        held.close()


@in_chromium
def test_a_new_lookup_never_shows_the_sheet_of_the_one_before_come_late(cfg, browser):
    queue = JobQueue(FakeGet(cfg))
    queue.submit("Fetch Radiohead - Creep", "radiohead/creep", lookup_steps("Radiohead", "Creep"), fetching=True,
                 display="Radiohead - Creep")
    queue.run_pending()  # Creep's sheet is kept: the page reads it once it follows job 1
    held = Held(cfg, queue, "/Radiohead/Creep/sheet.txt")
    try:
        browser.open(held.base + "/lookup?job=1")
        held.until(lambda: held.polls("/Radiohead/Creep/sheet.txt"))  # its sheet is on its way
        browser.js(ASKS_BY_NAME)
        assert browser.wait(f"{TITLE} === 'Soda Stereo - Musica Ligera'")
        held.go.set()
        held.until(lambda: held.answered)
        held.until(lambda: held.polls("/api/jobs/2", since=held.answered[0]) >= 2)
        assert browser.js(TITLE) == "Soda Stereo - Musica Ligera"
        assert browser.js("[document.getElementById('sheet').hidden, document.getElementById('sheet').textContent]") \
            == [True, ""]
    finally:
        held.close()
