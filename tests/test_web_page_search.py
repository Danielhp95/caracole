"""The library page's one bar, served by a real ``caracole serve`` and driven in a real browser.

Typing searches as you type, no Enter needed: your songs that match, then what the offline indexes hold of
Ultimate Guitar, gtptabs.com and MuseScore (``/api/search``), all under the same artist headers, a song the
sites have twice one line with each site's mark; Get it looks a song up in its own line, and Enter only
moves to the first result. The queue runs ``FakeGet``, which does what ``caracole get`` does with no
request: it adds the song from wanted.txt and keeps a sheet.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.targets import small_targets

from caracole import db
from caracole.get import PROGRESS_PREFIX
from caracole.library import song_dir
from caracole.overrides import override_key
from caracole.songs import find_song, mark_removed, update_song
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
    """The searches the server got; while ``held`` is an event, each next one (only those for the query ``only``,
    when it is set) answers once the test sets it. While ``lookups_held`` is one, each Get it's request is queued at
    once, and its answer to the page waits for the test to set it."""

    def __init__(self):
        super().__init__()
        self.held: threading.Event | None = None
        self.only: str | None = None
        self.lookups_held: threading.Event | None = None

    def queries(self) -> list[str]:
        return [parse_qs(urlsplit(target).query).get("q", [""])[0] for target in self]


@pytest.fixture
def live(cfg):
    """The library page on a socket, its queue running ``FakeGet``; ``asked`` lists the searches it got."""
    queue = JobQueue(FakeGet(cfg))
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False)
    asked = Asked()
    answer = app.handle

    def handle(request):
        if request.target.startswith("/api/search"):
            asked.append(request.target)
            held = asked.held
            q = parse_qs(urlsplit(request.target).query).get("q", [""])[0]
            if held is not None and (asked.only is None or q == asked.only):
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


def removed(cfg, artist, title, when="2026-10-20T09:00:00+00:00"):
    """A song caracole removed: its tombstone, and no record."""
    conn = db.connect(cfg.db_path)
    song = add_song(conn, artist, title)
    mark_removed(conn, song, when)
    conn.execute("DELETE FROM songs WHERE id = ?", (song.id,))
    conn.commit()
    conn.close()
    return song


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
    request's line follows the job in the line, in place of its Get it, and the line is where its card comes from."""
    return page.wait(f"!document.querySelector({json.dumps(hit + ' .line-action button')})")


def search(page, query):
    """``query`` typed into the bar, a key at a time, and no Enter."""
    page.js("document.getElementById('q').focus()")
    page.js("document.getElementById('q').select()")
    page.type(query)


def answer_to(query):
    """The sites' answer to ``query`` drawn: typed a key at a time, a query may have the answer to its first keys drawn
    first, a key coming more than the page's pause after the one before it on a busy machine, and that answer holds
    much of what its own does."""
    return f"document.getElementById('found').dataset.query === {json.dumps(query)}"


GRID = "[...document.querySelectorAll('#list article')].map((a) => a.querySelector('h3').textContent)"
STATUS = "document.getElementById('bar-status').textContent"
HITS = "document.querySelectorAll('#results .hit').length"
# Each group of the results: its header, and its lines (a title, and whose: "yours", or the sites' marks).
GROUPS = "[...document.querySelectorAll('#results section.artist')].map((g) => g.querySelector('.artist-title').textContent)"
LINES = ("[...document.querySelectorAll('#results section.artist')].map((g) => [g.querySelector('.artist-name')"
         ".textContent, [...g.querySelectorAll('article.line')].map((a) => [a.querySelector('h3').textContent, "
         "a.dataset.id ? 'yours' : [...a.querySelectorAll('.line-sources .source')].map((m) => m.dataset.source)"
         ".join('+')])])")
TITLES = "[...document.querySelectorAll('#results .hit h3')].map((t) => t.textContent)"
WONDERWALL = dict(ug=[("oasis", "wonderwall", 9), ("ryan-adams", "wonderwall", 3), ("eagles", "hotel-california", 5)],
                  gtptabs=["https://gtptabs.com/tabs/15/oasis/wonderwall.html"],
                  musescore=["https://musescore.com/song/wonderwall-1524"])
RYAN = "#results .hit[data-ug='ryan-adams/wonderwall']"
# The row of marks under the search box (rows.js countMarks): each mark's site ("library" for yours), its state, and
# the count beside it (none where the site wasn't searched: blocked, or turned off).
COUNTS = ("[...document.querySelectorAll('#bar-counts > li')].map((c) => [c.dataset.source, c.dataset.state, "
          "c.dataset.n === undefined ? null : Number(c.dataset.n)])")
# Each mark's name for a screen reader, its tooltip, its description.
COUNT_WORDS = ("[...document.querySelectorAll('#bar-counts > li')].map((c) => { const m = c.firstElementChild; "
               "return [m.getAttribute('aria-label') || m.getAttribute('alt'), c.title, "
               "m.getAttribute('aria-description')]; })")
# What each mark shows beside its icon: its count (or "off"), and the glyphs that say a state without its colour.
COUNT_SHOWN = ("[...document.querySelectorAll('#bar-counts > li')].map((c) => [(c.querySelector('.count-n, .count-off') "
               "|| { textContent: '' }).textContent, [...c.querySelectorAll('svg.glyph')].map((g) => "
               "g.getAttribute('class').replace('glyph glyph-', ''))])")
COUNTS_SHOWN = "document.getElementById('bar-counts').checkVisibility()"
# Whether the words under the box show, or are there for a screen reader alone, as the marks say them.
WORDS_SHOWN = "(document.getElementById('bar-status').getBoundingClientRect().width > 1)"
# No line under the results says where caracole looked: the marks under the box say it, once.
NO_SEARCHED_LINE = ("!document.querySelector('#results .looked, #results .looked-line, #results .count-mark') && "
                    "!/Searched/.test(document.getElementById('results').textContent)")
BUSY = "(document.getElementById('found').getAttribute('aria-busy') === 'true')"
# The lookup page's words under its box, and whether they show.
LOOKUP_STATUS = "document.getElementById('status').textContent"
LOOKUP_WORDS_SHOWN = "(document.getElementById('status').getBoundingClientRect().width > 1)"


def test_typing_lists_your_songs_and_the_indexes_without_enter(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=[*WONDERWALL["ug"], ("eagles", "take-it-easy", 2)], gtptabs=WONDERWALL["gtptabs"],
          musescore=WONDERWALL["musescore"])
    library(cfg, ("Eagles", "Hotel California"), ("Radiohead", "Creep"))
    browser.open(base)
    assert "Search all" not in browser.js("document.body.textContent") and browser.js("document.getElementById('all')") is None
    search(browser, "eagles")  # an artist: your song of theirs, then the index's, under one header
    assert browser.wait(f"{answer_to('eagles')} && {HITS} >= 1")
    assert asked.queries()[-1] == "eagles" and queue.snapshot() == []  # searched, nothing looked up
    assert browser.js(GROUPS) == ["Eagles · you have 1 · UG 2"]
    assert browser.js(LINES) == [["Eagles", [["Hotel California", "yours"], ["Take It Easy", "ug"]]]]
    assert browser.js("document.querySelector('.toolbar').offsetParent") is None  # the list's tools step aside
    assert browser.js("document.activeElement.id") == "q"  # the focus stays in the box
    # Typing on follows: the newest query's answer alone, a song your library hasn't under its artist's own header.
    search(browser, "wonderwall")
    assert browser.wait("document.getElementById('found').dataset.query === 'wonderwall'")
    assert browser.js(LINES) == [["Oasis", [["Wonderwall", "ug+gtptabs"]]], ["Ryan Adams", [["Wonderwall", "ug"]]],
                                 ["MuseScore", [["Wonderwall", "musescore"]]]]
    # What each site found, a mark and a count under the box: LaCuerda's, harptabs.com's and gametabs.net's indexes are
    # empty, the rest searched whole; none of yours.
    assert browser.js(COUNTS) == [["library", "done", 0], ["ug", "done", 2], ["gtptabs", "done", 1],
                                  ["lacuerda", "empty", 0], ["musescore", "done", 1], ["harptabs", "empty", 0],
                                  ["gametabs", "empty", 0]]
    assert browser.js(STATUS) == "2 on Ultimate Guitar · 1 on gtptabs.com · 1 on MuseScore"
    assert browser.js(NO_SEARCHED_LINE)
    assert browser.js("document.querySelectorAll('#results .notes p, #results .nothing').length") == 0
    link = browser.js("(() => { const a = document.querySelector('#results .hit[data-source=\"musescore\"] .line-action a');"
                      " return [a.href, a.target, a.rel]; })()")
    assert link == ["https://musescore.com/song/wonderwall-1524", "_blank", "noopener noreferrer"]  # a link alone
    assert "Hotel California" not in browser.js("document.getElementById('results').textContent")
    assert queue.snapshot() == []


# Each hit's instrument marks (rows.js instrumentBadges), by its title and its first site's mark.
MARKS = ("[...document.querySelectorAll('#results article.line')].map((a) => [a.querySelector('h3').textContent, "
         "[...a.querySelectorAll('.badge.instrument')].map((b) => b.textContent)])")


def test_a_hit_for_one_instrument_says_which_and_nothing_is_left_out_for_it(cfg, live, browser):
    # UG's Ukulele Chords, a harmonica tab of harptabs.com, a MuseScore page: each says the instrument it is for, and
    # every chord sheet stays, with no mark; a song of yours with a harmonica tab and a score holds them, its glyphs.
    from caracole.harptabs import parse_page_url as harp_row
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    base, queue, asked = live
    sites(cfg, ug=[("oasis", "wonderwall", 2), ("ryan-adams", "wonderwall", 1)],
          musescore=["https://musescore.com/song/wonderwall-1524"])
    conn = db.connect(cfg.db_path)
    upsert_rows(conn, [(3001, "oasis", "wonderwall", "ukulele", "oasis/wonderwall-ukulele-3001")], "ukulele1",
                datetime(2026, 10, 19, tzinfo=UTC))
    conn.execute("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) VALUES (?, ?, ?, ?, 'sitemap')",
                 tuple(harp_row("https://www.harptabs.com/tab/77/wonderwall")))
    [mine] = [add_song(conn, "Blur", "Wonderwall Remix")]
    tab = upsert_version(conn, provider="harptabs", tab_id="5", song_id=mine.id, slot="guitar", kind="harmonica",
                         rating=0, votes=0, version=1, label=None, url="https://www.harptabs.com/tab/5/x", raw={},
                         now="2026-10-19T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=mine, version_id=tab, name="harmonica-1.txt", data=b"4 5 6\n", rank=1)
    (song_dir(cfg.library_dir, mine) / "score-1.pdf").write_bytes(b"%PDF-1.4")
    conn.commit()
    conn.close()
    browser.open(base)
    search(browser, "wonderwall")
    assert browser.wait("document.getElementById('found').dataset.query === 'wonderwall'")
    assert browser.wait("document.querySelectorAll('#results article.line').length >= 5")
    marks = dict(browser.js(MARKS))
    assert marks["Wonderwall Remix"] == []  # a song of yours says it by what its line holds
    assert browser.js("[...document.querySelectorAll('#results article.line[data-id] .line-holds svg')]"
                      ".map((g) => g.getAttribute('aria-label'))") == ["Harmonica tab", "Score"]
    lines = browser.js(LINES)
    assert ["Oasis", [["Wonderwall", "ug"]]] in lines and ["Ryan Adams", [["Wonderwall", "ug"]]] in lines
    rows = browser.js(MARKS)
    assert ["Wonderwall", ["Ukulele"]] in rows and ["Wonderwall", []] in rows  # Oasis's has UG's ukulele chords
    assert browser.js(GROUPS)[-2:] == ["MuseScore · 1 page by that title", "harptabs.com · 1 harmonica tab by that title"]
    harp = browser.js("[...document.querySelectorAll('#results .hit[data-source=\"harptabs\"]')].map((a) => "
                      "[a.querySelector('h3').textContent, a.querySelector('.badge.instrument').textContent, "
                      "a.querySelector('.line-action a').href])")
    assert harp == [["Wonderwall", "Harmonica", "https://www.harptabs.com/tab/77/wonderwall"]]
    score = browser.js("document.querySelector('#results .hit[data-source=\"musescore\"] .badge.instrument')"
                       ".textContent")
    assert score == "Score"
    assert "1 on harptabs.com" in browser.js(STATUS)
    assert queue.snapshot() == []


def test_one_song_from_two_sites_is_one_line_with_two_icons(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("oasis", "wonderwall", 9), ("oasis", "live-forever", 2)],
          gtptabs=["https://gtptabs.com/tabs/15/oasis/wonderwall.html"])
    browser.open(base)
    search(browser, "oasis wonderwall")
    assert browser.wait(f"{answer_to('oasis wonderwall')} && {HITS} >= 1")
    line = "#results .hit[data-ug='oasis/wonderwall']"
    assert browser.js(f"document.querySelectorAll(\"{line}\").length") == 1
    assert browser.js(f"[...document.querySelectorAll(\"{line} .line-sources .source\")].map((m) => m.getAttribute('alt')"
                      " || m.getAttribute('aria-label'))") == ["from Ultimate Guitar", "from gtptabs.com"]
    assert browser.js(f"document.querySelector(\"{line} .line-facts\").textContent") == "chords ×9 · Guitar Pro file"
    # Under its "⋯", each site's: UG's versions, gtptabs.com's page.
    browser.click(f"{line} .line-more")
    panel = browser.js(f"document.querySelector(\"{line} .line-panel\").textContent")
    assert "Chords 1 of 9" in panel and "On gtptabs.com" in panel
    assert browser.js(f"document.querySelector(\"{line} .line-panel a[href*='gtptabs.com']\").href") == \
        "https://gtptabs.com/tabs/15/oasis/wonderwall.html"
    # Its Get it is Ultimate Guitar's song, whose lookup gets the Guitar Pro file from gtptabs.com too.
    browser.click(f"{line} .line-action button")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", "--ug=oasis/wonderwall") and args[-2:] == ("Oasis", "Wonderwall")


def test_the_sites_rows_of_an_artist_of_yours_go_under_your_artists_header_and_a_covers_never_do(cfg, live, browser):
    # UG's slugs write AC/DC as "Acdc": their rows are under your AC/DC's header. Your Ryan Adams cover matched to
    # Oasis's tab is your song, in your Ryan Adams group, and Oasis's other songs stay under Oasis.
    base, _, _ = live
    sites(cfg, ug=[("acdc", "thunderstruck", 3), ("acdc", "highway-to-hell", 2), ("oasis", "wonderwall", 9),
                   ("oasis", "live-forever", 2)])
    acdc, cover = library(cfg, ("AC/DC", "Thunderstruck"), ("Ryan Adams", "Wonderwall"))
    conn = db.connect(cfg.db_path)
    update_song(conn, cover.id, match_decision="accept", match_artist_key="oasis", match_song_key="wonderwall")
    conn.close()
    browser.open(base)
    search(browser, "acdc")
    assert browser.wait(f"{answer_to('acdc')} && {HITS} >= 1")
    assert browser.js(LINES) == [["AC/DC", [["Thunderstruck", "yours"], ["Highway To Hell", "ug"]]]]
    assert browser.js(GROUPS) == ["AC/DC · you have 1 · UG 2"]
    search(browser, "oasis")
    assert browser.wait("document.getElementById('found').dataset.query === 'oasis'")
    # The artist the query names first, as the answer ranks it; your cover in your Ryan Adams group.
    assert browser.js(LINES) == [["Oasis", [["Live Forever", "ug"]]], ["Ryan Adams", [["Wonderwall", "yours"]]]]


def test_an_artist_group_shows_a_few_index_songs_then_more(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=[("estopa", f"cancion-{n:02}", 3 if n < 3 else 1) for n in range(60)])
    browser.open(base)
    search(browser, "estopa")
    assert browser.wait(f"{answer_to('estopa')} && {HITS} === 3")
    assert browser.js(GROUPS) == ["Estopa · UG 60"]
    assert browser.js(TITLES) == ["Cancion 00", "Cancion 01", "Cancion 02"]  # the most tabbed first
    more = "#results section.artist .more-by"
    assert browser.js(f"document.querySelector('{more}').textContent") == "+ 57 more by Estopa"
    browser.click(more)  # all of them, fifty at a time (/api/artist), in the group itself
    assert browser.wait(f"{HITS} === 50")
    assert browser.js(f"document.querySelector('{more}').textContent") == "+ 10 more by Estopa"
    browser.click(more)
    assert browser.wait(f"{HITS} === 60")
    assert browser.js(f"document.querySelector('{more}')") is None
    titles = browser.js(TITLES)
    assert titles[:3] == ["Cancion 00", "Cancion 01", "Cancion 02"] and len(set(titles)) == 60
    assert browser.js(GROUPS) == ["Estopa · UG 60"] and queue.snapshot() == []  # listing them asked no site


def test_index_lines_show_tab_counts_not_stars(cfg, live, browser):
    base, _, _ = live
    sites(cfg, **WONDERWALL)
    browser.open(base)
    search(browser, "wonderwall")
    assert browser.wait(f"{answer_to('wonderwall')} && !!document.querySelector(\"{RYAN}\")")
    assert browser.js(f"document.querySelector(\"{RYAN} .line-facts\").textContent") == "chords ×3"
    text = browser.js("document.getElementById('results').textContent")
    assert "★" not in text and "rating" not in text.lower() and "votes" not in text.lower()


def sent(asked, query, timeout=10.0):
    """Waits until the server got a search for ``query``."""
    deadline = time.monotonic() + timeout
    while query not in asked.queries():
        if time.monotonic() > deadline:
            raise AssertionError(f"the page never searched {query!r}: {asked.queries()}")
        time.sleep(0.02)


def test_typing_fast_shows_only_the_newest_answer(cfg, live, browser):
    # Review Focus 3: the newest query's answer alone, whatever comes late; and your songs that match show at once
    # and stay throughout, the sites' answer on its way, drawn, or an older one arriving late.
    base, _, asked = live
    sites(cfg, ug=[("radiohead", "creep", 4), ("radiohead", "karma-police", 2), ("muse", "hysteria", 3)])
    library(cfg, ("Radiohead", "Creep"), ("Easy Star All-Stars", "Karma Police"))
    yours = ("[...document.querySelectorAll('#results article.line[data-id]')].filter((a) => a.offsetParent !== null)"
             ".map((a) => a.querySelector('h3').textContent)")
    browser.open(base)
    first = asked.held = threading.Event()  # the first query's answer comes late
    asked.only = "creep"
    search(browser, "creep")
    sent(asked, "creep")
    assert browser.js(yours) == ["Creep"] and browser.js(TITLES) == []  # yours, while the sites' answer is on its way
    asked.held, asked.only = threading.Event(), None  # every later answer waits too, until the test lets it go
    search(browser, "karma police")  # typed over while the first answer is on its way
    sent(asked, "karma police")
    assert browser.js(yours) == ["Karma Police"] and browser.js(TITLES) == []  # at once, no answer yet
    assert browser.js(BUSY)
    asked.held.set()
    assert browser.wait(f"{TITLES}.join() === 'Karma Police'")
    assert browser.js(yours) == ["Karma Police"]
    first.set()  # the older answer, late: never drawn
    time.sleep(0.6)
    assert browser.js(f"{TITLES}.join()") == "Karma Police" and browser.js(yours) == ["Karma Police"]
    assert browser.js("document.getElementById('found').dataset.query") == "karma police"
    assert browser.js(LINES) == [["Easy Star All-Stars", [["Karma Police", "yours"]]],
                                 ["Radiohead", [["Karma Police", "ug"]]]]


def test_two_people_searching_at_once_each_get_their_answer(cfg, live, browser, tmp_path, monkeypatch):
    # A sing-along: one searches on the library page, another on the lookup page, at the same moment, and each search
    # takes a while (common words, a slow host). Neither page's search stops the other's: each waits its turn and
    # shows its answer, where they used to stop each other's, and both pages asked again for ever.
    import caracole.search

    base, _, asked = live
    sites(cfg, ug=[("love", "night-song", 3), ("blue", "heart-song", 2)])
    real = caracole.search.find_index

    def slow(conn, query, **kwargs):  # long enough for the other page's search to come in while it reads
        time.sleep(0.4)
        conn.execute("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 200000) "
                     "SELECT count(*) FROM n").fetchone()  # SQLite looks for a newer search on the way
        return real(conn, query, **kwargs)

    monkeypatch.setattr(caracole.search, "find_index", slow)
    lookup = driven(tmp_path / "other")
    try:
        browser.open(base)
        lookup.open(base + "lookup")
        typed = ("(() => {{ const q = document.getElementById('q'); q.focus(); q.value = {}; "
                 "q.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()")
        browser.js(typed.format(json.dumps("love night")))
        lookup.js(typed.format(json.dumps("blue heart")))
        assert browser.wait(f"{TITLES}.join() === 'Night Song'", timeout=20), asked.queries()
        assert lookup.wait("[...document.querySelectorAll('#results .hit .row-title')].some((t) => "
                           "t.textContent === 'Heart Song')", timeout=20), asked.queries()
    finally:
        lookup.close()
    boxes = {parse_qs(urlsplit(target).query).get("box", [""])[0] for target in asked}
    assert len(boxes) == 2 and "" not in boxes, asked  # each page's box: an id of its own
    assert len(asked) <= 6, asked  # an answer each, at most a search or two asked again while typing settled


def test_typing_never_asks_a_music_site(cfg, live, browser):
    # The page asks its own server alone, and the server reads its indexes: typing looks nothing up.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base)
    search(browser, "wonderwall")
    assert browser.wait(f"{HITS} === 3")  # Oasis's (on UG and gtptabs.com: one line), Ryan Adams's, MuseScore's
    search(browser, "hotel california")
    assert browser.wait("document.getElementById('found').dataset.query === 'hotel california'")
    origins = browser.js("[...new Set(performance.getEntriesByType('resource').map((r) => new URL(r.name).origin))]")
    assert origins == [base.rstrip("/")], origins
    assert queue.snapshot() == [] and len(asked) >= 2


def test_get_it_looks_the_song_up_and_its_line_says_how_it_goes(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")  # the address keeps the search, as it keeps the rest
    assert browser.wait(f"{HITS} >= 2")
    browser.click(f"{RYAN} .line-action button")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", "--ug=ryan-adams/wonderwall") and args[-2:] == ("Ryan Adams", "Wonderwall")
    line = "document.querySelector('#results .progress').closest('article')"
    assert browser.wait("!!document.querySelector('#results .progress')")
    assert browser.wait(f"{line}.querySelector('.progress').dataset.tone === 'ready'", timeout=20)
    # Once done, the result's line is the song's own line, around its request line: its sheet its button.
    assert browser.js(f"{line}.querySelector('h3').textContent") == "Wonderwall"
    assert browser.wait(f"{line}.querySelector('.line-action a') && "
                        f"{line}.querySelector('.line-action a').textContent === 'Open PDF'")
    # Back to your songs: the new song has a line of its own above the list.
    browser.press("Escape")
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall'")


# A line's "⋯" opened, and the names of the buttons it holds.
OFFERS = ("((a) => { a.querySelector('.line-more').click(); "
          "return [...a.querySelectorAll('.line-panel button')].map((b) => b.textContent); })")


def test_a_song_get_it_brought_offers_no_songbook_until_the_page_is_loaded_again(cfg, live, browser):
    # Select knows the songs the page was loaded with: on a song Get it brought, Add to a songbook… would do nothing,
    # so its lines leave it out until the page is loaded again; a song of yours among the results has it.
    base, queue, _ = live
    sites(cfg, **WONDERWALL)
    library(cfg, ("Oasis", "Wonderwall"))
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"!!document.querySelector(\"{RYAN}\")")
    browser.click(f"{RYAN} .line-action button")
    posted(queue)
    line = "document.querySelector('#results .progress').closest('article')"
    assert browser.wait("!!document.querySelector('#results .progress')")
    assert browser.wait(f"{line}.querySelector('.progress').dataset.tone === 'ready'", timeout=20)
    assert browser.wait(f"{line}.querySelector('.line-action a') && "
                        f"{line}.querySelector('.line-action a').textContent === 'Open PDF'")  # the song's line now
    assert "Add to a songbook…" not in browser.js(f"{OFFERS}({line})")
    oasis = ("[...document.querySelectorAll('#results section.artist')].find((g) => "
             "g.querySelector('.artist-name').textContent === 'Oasis').querySelector('article.line')")
    assert "Add to a songbook…" in browser.js(f"{OFFERS}({oasis})")
    browser.press("Escape")  # its line under the bar, as the new song's
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall'")
    assert "Add to a songbook…" not in browser.js(f"{OFFERS}(document.querySelector('#requested article'))")


def test_a_newer_answer_keeps_the_line_whose_request_runs_and_its_request_line(cfg, live, browser):
    # Typed on, the list on the screen is the older answer's until the newer comes. A Get it tapped there keeps its
    # line, and the line its request line, when the newer answer is drawn; back to your songs, its card.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    browser.js(f"window.row = document.querySelector(\"{RYAN}\")")
    asked.held = threading.Event()  # the next answer waits until the page has the request
    search(browser, "ryan adams wonderwall")
    assert browser.wait(BUSY)  # the newer search on its way
    browser.click(f"{RYAN} .line-action button")  # on the older answer's line, as the newer is on its way
    posted(queue)
    assert browser.wait("!!window.row.querySelector('.progress')")
    assert answered(browser, RYAN)
    asked.held.set()
    assert browser.wait(f"!{BUSY} && document.getElementById('found').dataset.query === 'ryan adams wonderwall'")
    kept = browser.js(f"[document.querySelector(\"{RYAN}\") === window.row, window.row.isConnected, "
                      "!!window.row.querySelector('.progress')]")
    assert kept == [True, True, True]  # the same line, in the newer list, with its request line
    assert browser.wait("window.row.querySelector('.progress').dataset.tone === 'ready'", timeout=20)
    browser.press("Escape")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall'")


def test_a_line_whose_request_runs_and_that_a_newer_answer_lacks_becomes_its_card(cfg, live, browser):
    # Typed over, the newer answer has no such song: the request's card comes under the bar, its line still going.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    asked.held = threading.Event()  # the answers wait until the page has the request
    search(browser, "hotel california")
    assert browser.wait(BUSY)
    browser.click(f"{RYAN} .line-action button")
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
    assert browser.wait(f"{HITS} >= 3")
    # Yours already: the sites' rows of it are your own line, whose "⋯" has all it offers.
    assert browser.js(LINES)[0] == ["Oasis", [["Wonderwall", "yours"]]]
    later = "#results .hit[data-ug='{}'] .line-panel .later button"
    # Under UG's misc-… names the song would be no one's: add it as you know it.
    assert browser.js(f"document.querySelector(\"{later.format('misc-mashups/oasis-wonderwall')}\")") is None
    assert browser.js("!!document.querySelector(\"#results .hit[data-ug='misc-mashups/oasis-wonderwall']\")")
    assert browser.js(f"[...document.querySelectorAll(\"{RYAN} .line-sources .source\")].map((m) => m.dataset.source)"
                      ) == ["ug", "gtptabs"]  # Ultimate Guitar's and gtptabs.com's, one line
    browser.click(f"{RYAN} .line-more")
    browser.click(later.format("ryan-adams/wonderwall"))
    args = posted(queue)
    assert args == ("add", "--", "Ryan Adams", "Wonderwall")  # into wanted.txt, as caracole add writes it
    assert "Ryan Adams - Wonderwall" in cfg.wanted_file.read_text(encoding="utf-8")
    assert browser.wait(f"!!document.querySelector(\"{RYAN} .progress\")")
    assert browser.js("document.querySelector('#results .hit[data-source=\"musescore\"] .later')") is None  # links


def test_a_removed_song_shows_among_the_results_and_add_again_brings_it_back(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "karma-police", 2)])
    gone = removed(cfg, "Radiohead", "Creep")
    browser.open(base)
    search(browser, "radiohead")
    assert browser.wait(f"{answer_to('radiohead')} && !!document.querySelector('#results .removed-hit')")
    assert browser.js(LINES) == [["Radiohead", [["Creep", ""], ["Karma Police", "ug"]]]]  # its artist's group
    line = "#results .removed-hit"
    assert browser.js(f"document.querySelector('{line} .line-status').textContent") == "Removed 2026-10-20"
    assert browser.js(f"document.querySelector('{line} .line-action button').textContent") == "Add again"
    browser.press("Enter")  # never what Enter acts on: it moves to the first result, and asks for nothing
    assert browser.js("document.activeElement.closest('article') && document.activeElement.closest('article')"
                      ".querySelector('h3').textContent") == "Creep"
    time.sleep(0.3)
    assert queue.snapshot() == []
    browser.click(f"{line} .line-action button")  # asked for again as the request form asks: a wanted.txt line
    args = posted(queue)
    assert args[0] == "get" and args[-2:] == ("Radiohead", "Creep")
    assert "Radiohead - Creep" in cfg.wanted_file.read_text(encoding="utf-8")
    assert browser.wait("document.querySelector('#results .progress') && "
                        "document.querySelector('#results .progress').dataset.tone === 'ready'", timeout=20)
    conn = db.connect(cfg.db_path)
    try:
        assert find_song(conn, gone.key) is not None  # back in the library
    finally:
        conn.close()


# A result's song name, which does what its Get it does: a button in its heading.
NAME = "{} h3 button.title-get"
# The page's fetch, each POST noted (its path and form) and never sent: its line stays "Sending…".
NOTE_POSTS = ("(() => { window.posts = []; const real = window.fetch; window.fetch = (url, init) => { "
              "if (init && init.method === 'POST') { window.posts.push([String(url), String(init.body)]); "
              "return new Promise(() => {}); } return real(url, init); }; })()")
# An Ultimate Guitar song alone, one UG and gtptabs.com have (one line, two marks), and a gtptabs.com song alone.
OASIS = "#results .hit[data-ug='oasis/wonderwall']"
NOEL = "#results .hit[data-source='gtptabs']"


def test_a_results_name_posts_what_its_get_it_posts(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=WONDERWALL["ug"], gtptabs=[*WONDERWALL["gtptabs"],
                                            "https://gtptabs.com/tabs/20/noel-gallagher/wonderwall.html"])
    pressed = {}
    browser.open(base + "#q=wonderwall&all=1")
    for what in ("name", "get it"):
        if pressed:
            browser.js("window.before = true; location.reload()")  # the page anew, its lines as they came
        assert browser.wait(f"!window.before && {HITS} >= 3 && !!document.querySelector(\"{NOEL}\")")
        browser.js(NOTE_POSTS)
        for hit in (RYAN, OASIS, NOEL):
            browser.click(NAME.format(hit) if what == "name" else f"{hit} .line-action button")
            assert browser.wait(f"window.posts.length && !!document.querySelector(\"{hit} .progress\")")
        pressed[what] = browser.js("window.posts")
    assert pressed["name"] == pressed["get it"]
    assert [path for path, _ in pressed["name"]] == ["lookup"] * 3
    forms = [parse_qs(body) for _, body in pressed["name"]]
    assert forms[0]["ug"] == ["ryan-adams/wonderwall"] and forms[1]["ug"] == ["oasis/wonderwall"]
    assert forms[2]["artist"] == ["Noel Gallagher"] and "ug" not in forms[2]
    assert queue.snapshot() == []  # noted, never sent
    # Named for what it does, and looking like the name it is.
    assert browser.js(f"document.querySelector(\"{NAME.format(RYAN)}\").getAttribute('aria-label')"
                      ) == "Get Ryan Adams - Wonderwall"
    assert browser.js(f"document.querySelector(\"{NAME.format(RYAN)}\").title").startswith("Get Ryan Adams - Wonderwall")
    assert browser.js(f"document.querySelector(\"{RYAN} h3\").textContent") == "Wonderwall"


def test_a_results_name_looks_the_song_up_and_cant_be_pressed_twice(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    name = f"document.querySelector(\"{NAME.format(RYAN)}\")"
    assert browser.js(f"{name}.disabled") is False
    asked.lookups_held = threading.Event()  # the page hears back once the test says so
    browser.js(f"{name}.focus()")
    browser.press("Enter")  # a key on the name, as a click on it
    args = posted(queue)
    assert args[:3] == ("get", "--progress", "--ug=ryan-adams/wonderwall") and args[-2:] == ("Ryan Adams", "Wonderwall")
    assert browser.wait(f"{name}.disabled && document.querySelector(\"{RYAN} .line-action button\").disabled")
    browser.click(NAME.format(RYAN))  # pressed again while its request is on its way: nothing more
    asked.lookups_held.set()
    assert answered(browser, RYAN)  # its request line in its Get it's place
    assert browser.wait(f"!{name} || {name}.disabled")
    assert browser.wait("document.querySelector('#results .progress').dataset.tone === 'ready'", timeout=20)
    assert len(queue.snapshot()) == 1


def test_a_song_of_yours_keeps_its_title_link_and_a_removed_songs_name_adds_it_again(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 2), ("radiohead", "karma-police", 2)])
    removed(cfg, "Radiohead", "Creep")
    (mine,) = library(cfg, ("Radiohead", "Karma Police"))
    conn = db.connect(cfg.db_path)
    folder = song_dir(cfg.library_dir, mine)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sheet.pdf").write_bytes(b"%PDF-1.4")
    update_song(conn, mine.id, status="found")
    conn.close()
    browser.open(base)
    search(browser, "radiohead")
    assert browser.wait(f"{answer_to('radiohead')} && !!document.querySelector('#results .removed-hit') && "
                        "!!document.querySelector('#results .line[data-id]')")
    yours = "#results .line[data-id]"
    assert browser.js(f"!!document.querySelector(\"{yours} a.line-title h3\")") is True  # opens its sheet
    assert browser.js(f"document.querySelector(\"{yours} .title-get\")") is None
    gone = "#results .removed-hit"
    assert browser.js(f"document.querySelector(\"{NAME.format(gone)}\").getAttribute('aria-label')"
                      ) == "Add Radiohead - Creep again"
    browser.click(NAME.format(gone))  # as its Add again: asked for as the request form asks
    args = posted(queue)
    assert args[0] == "get" and args[-2:] == ("Radiohead", "Creep")
    assert "Radiohead - Creep" in cfg.wanted_file.read_text(encoding="utf-8")


# What each line of the results looks like, read from the page: whether it is a song you have, its name's colour and
# weight against the page's own (--text, --muted), the wash behind it and the edge (--accent at --have-tint), and the
# width of its "In your library" pill, which a song you have shows to a screen reader alone.
HAVE = """
(() => {
  const probe = (css) => { const p = document.createElement('i'); p.style.cssText = css; document.body.appendChild(p);
    const s = getComputedStyle(p); const got = [s.color, s.backgroundColor]; p.remove(); return got; };
  const ink = probe('color: var(--text)')[0], quiet = probe('color: var(--muted)')[0];
  const tint = probe('background-color: color-mix(in srgb, var(--accent) var(--have-tint), var(--surface))')[1];
  return [...document.querySelectorAll('#results article.line')].map((a) => {
    const name = getComputedStyle(a.querySelector('h3')), line = getComputedStyle(a), pill = a.querySelector('.badge.found');
    return [a.querySelector('h3').textContent, { have: a.classList.contains('have'), ink: name.color === ink,
      quiet: name.color === quiet, weight: name.fontWeight, tinted: line.backgroundColor === tint && tint !== 'rgba(0, 0, 0, 0)',
      edge: line.boxShadow !== 'none', pill: pill ? pill.getBoundingClientRect().width : null }];
  });
})()
"""


def keep_sheet(cfg, song):
    conn = db.connect(cfg.db_path)
    folder = song_dir(cfg.library_dir, song)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sheet.pdf").write_bytes(b"%PDF-1.4")
    update_song(conn, song.id, status="found")
    conn.close()


def test_a_song_you_have_stands_out_from_the_ones_you_have_not(cfg, live, browser):
    # A found song: its name in the text's colour on a wash of the accent with an edge, no pill to see. Every other
    # line, a wanted song of yours or a site's: a muted name on a plain line. The weight is the same for all.
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "karma-police", 2), ("radiohead", "airbag", 2), ("radiohead", "no-surprises", 2)])
    (karma, _) = library(cfg, ("Radiohead", "Karma Police"), ("Radiohead", "Creep"))
    keep_sheet(cfg, karma)
    browser.open(base)
    (airbag,) = library(cfg, ("Radiohead", "Airbag"))  # kept since the page loaded: the page has no line of it yet
    keep_sheet(cfg, airbag)
    search(browser, "radiohead")
    assert browser.wait(f"{answer_to('radiohead')} && document.querySelectorAll('#results article.line').length >= 4")
    lines = dict(browser.js(HAVE))
    assert lines["Karma Police"] == {"have": True, "ink": True, "quiet": False, "weight": "500", "tinted": True,
                                     "edge": True, "pill": None}, lines  # yours, with its own line
    assert lines["Airbag"]["have"] and lines["Airbag"]["tinted"] and lines["Airbag"]["edge"], lines
    assert lines["Airbag"]["ink"] and 0 < lines["Airbag"]["pill"] <= 1, lines  # the sites' row says it, to a screen reader
    for title in ("Creep", "No Surprises"):  # a wanted song of yours, and one only a site has
        assert lines[title] == {"have": False, "ink": False, "quiet": True, "weight": "500", "tinted": False,
                                "edge": False, "pill": None}, (title, lines)


def test_clearing_the_box_leaves_the_results_as_escape_does(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    browser.click(f"{RYAN} .line-action button")
    posted(queue)
    assert answered(browser, RYAN)
    browser.click("#clear")  # the ×: out of the results, the request on its way with a card of its own
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Wonderwall'")
    assert browser.js("location.hash.includes('all=1')") is False
    # A search after it waits for its answer before what follows it shows, as after Escape.
    browser.js("window.waited = false; new MutationObserver(() => { window.waited = window.waited || "
               "document.body.classList.contains('waiting-sites'); }).observe(document.body, { attributes: true })")
    browser.type("creep")
    assert browser.wait("document.getElementById('found').dataset.query === 'creep'")
    assert browser.js("window.waited") is True


@pytest.mark.parametrize("leave", ["clear", "escape", "typed over"])
def test_a_get_it_whose_line_leaves_the_results_before_the_page_hears_back_still_gets_its_card(cfg, live, browser,
                                                                                               leave):
    # Get it, then at once the ×, Escape or a newer search without the song, before the server's answer reaches the
    # page: once it does, the request has its card under the bar, its line going on there, as it would have had
    # if the answer had come first.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    asked.lookups_held = threading.Event()
    browser.click(f"{RYAN} .line-action button")
    posted(queue)  # queued; the page hasn't heard back
    if leave == "clear":
        browser.click("#clear")
        assert browser.wait("document.getElementById('results').hidden")
    elif leave == "escape":
        browser.js("document.getElementById('q').focus()")
        browser.press("Escape")
        assert browser.wait("document.getElementById('results').hidden")
    else:
        search(browser, "hotel california")
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


def test_a_get_it_on_a_line_a_newer_answer_has_too_keeps_its_request_line_in_that_answers_line(cfg, live, browser):
    # Typed on while a Get it is on its way, and the newer answer drawn before the page hears back: the newer
    # answer's line for the song is the one that says how the request goes, and no card comes under the bar.
    base, queue, asked = live
    sites(cfg, **WONDERWALL)
    browser.open(base + "#q=wonderwall&all=1")
    assert browser.wait(f"{HITS} >= 2")
    browser.js(f"window.row = document.querySelector(\"{RYAN}\")")
    asked.lookups_held = threading.Event()
    browser.click(f"{RYAN} .line-action button")
    posted(queue)
    search(browser, "ryan adams wonderwall")
    assert browser.wait(f"!{BUSY} && document.getElementById('found').dataset.query === 'ryan adams wonderwall' && "
                        f"document.querySelector(\"{RYAN}\") !== window.row")  # drawn anew
    asked.lookups_held.set()
    assert browser.wait(f"document.querySelector(\"{RYAN}\") === window.row && "
                        f"!!document.querySelector(\"{RYAN} .progress\")")
    assert browser.js(f"document.querySelectorAll(\"{RYAN}\").length") == 1
    assert browser.wait("window.row.querySelector('.progress').dataset.tone === 'ready'", timeout=20)
    assert browser.js("document.getElementById('requested').hidden") is True


def test_enter_moves_to_the_first_result_and_never_requests_a_song(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    browser.open(base)
    search(browser, "radiohead creep")
    assert browser.wait(f"{answer_to('radiohead creep')} && {HITS} >= 1")
    browser.press("Enter")  # on a clear best: the focus on its line, never a request
    assert browser.js("document.activeElement.matches('#results article.hit')")
    browser.press("Enter")  # again: still nothing asked for
    time.sleep(0.6)
    assert queue.snapshot() == [] and len(asked) >= 1


SKYNYRD = [("lynyrd-skynyrd", "free-bird", 4), ("lynyrd-skynyrd", "sweet-home-alabama", 3),
           ("lynyrd-skynyrd", "simple-man", 2), ("lynyrd-skynyrd", "tuesdays-gone", 1),
           ("lynyrd-skynyrd", "that-smell", 1), ("sam-grow", "skynyrd", 1)]
DID_YOU_MEAN = "document.querySelector('#results .did-you-mean')"


def test_a_word_of_an_artists_name_puts_their_header_first_and_enter_asks_for_nothing(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=SKYNYRD)
    browser.open(base)
    search(browser, "skynyrd")
    assert browser.wait("document.getElementById('found').dataset.query === 'skynyrd'")
    assert browser.js(GROUPS) == ["Lynyrd Skynyrd · UG 5", "Sam Grow"]  # the artist first, the song titled so after
    assert browser.js(TITLES) == ["Free Bird", "Sweet Home Alabama", "Simple Man", "Skynyrd"]
    assert browser.js("document.querySelector('#results .more-by').textContent") == "+ 2 more by Lynyrd Skynyrd"
    assert browser.js(DID_YOU_MEAN) is None
    browser.press("Enter")
    assert browser.wait("document.activeElement.matches('#results article.hit')")
    time.sleep(0.5)
    assert queue.snapshot() == []


def test_the_instruments_filter_your_songs_in_the_results_never_the_sites(cfg, live, browser):
    # With Harmonica on, your songs among the results are those with a harmonica tab, as in the list; a site's song
    # stays whatever it is for: the filters are your songs'.
    base, _, _ = live
    sites(cfg, ug=[("eagles", "take-it-easy", 2), ("eagles", "hotel-california", 3)])
    hotel, _ = library(cfg, ("Eagles", "Hotel California"), ("Eagles", "Desperado"))
    folder = song_dir(cfg.library_dir, hotel)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "harmonica-1.txt").write_bytes(b"4 -4 5\n")
    browser.open(base + "#inst=harmonica")
    assert browser.js(GRID) == ["Hotel California"]
    search(browser, "eagles")
    assert browser.wait("document.getElementById('found').dataset.query === 'eagles'")
    [(artist, lines)] = browser.js(LINES)
    assert artist == "Eagles" and ["Hotel California", "yours"] in lines and ["Take It Easy", "ug"] in lines, lines
    assert "Desperado" not in [title for title, _ in lines], lines  # yours, with no harmonica tab
    assert browser.js("document.querySelector('#results p.filtered > span').textContent") == (
        "Your songs here: with a harmonica tab")  # the results' head says it, as the toolbar steps aside


def test_escape_returns_to_the_list_with_its_filter(cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    library(cfg, ("Radiohead", "Creep"), ("Oasis", "Wonderwall"))
    browser.open(base + "#show=wanted")
    search(browser, "creep")
    # Your song is the page's own line, with all it offers (Fetch now, served), in its artist's group.
    assert browser.wait("document.querySelector('#results section.artist .line[data-id] form.fetch') !== null")
    browser.press("Escape")
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.js("document.getElementById('q').value") == "creep"
    assert browser.js(GRID) == ["Creep"]
    assert browser.js("document.querySelector('[data-show=\"wanted\"]').getAttribute('aria-checked')") == "true"
    assert browser.js("location.hash.includes('all=1')") is False
    browser.press("Escape")  # again: the search clears
    assert browser.wait(f"{GRID}.length === 2")


def played(cfg, *songs):
    """Songs of yours whose last render read a progression in their sheets: (artist, title, chords, key)."""
    from caracole.db import kv_set_json
    from caracole.progressions import KV, sheet_progressions

    conn = db.connect(cfg.db_path)
    for artist, title, chords, key in songs:
        song = add_song(conn, artist, title)
        sheet = "{title: X}\n{comment: Verse}\n" + " ".join(f"[{c}]la" for c in chords.split()) + "\n"
        kv_set_json(conn, f"{KV}{song.id}", sheet_progressions(sheet, key))
    conn.commit()
    conn.close()


PROG_NOTE = "document.querySelector('#results .prog-found:not([hidden])')"


def test_a_progression_typed_or_named_finds_your_songs_that_play_it(cfg, live, browser):
    base, queue, asked = live
    played(cfg, ("Placeholder Band", "Synthetic Song", "Am F C G", "C"),
           ("Another Band", "Minor Song", "Am F C G", "Am"), ("Third Band", "Spanish Song", "Am G F E", "Am"))
    library(cfg, ("Radiohead", "Creep"))
    browser.open(base)
    search(browser, "vi IV I V")
    assert browser.wait(f"{answer_to('vi IV I V')} && {PROG_NOTE} !== null")
    assert browser.js(f"{PROG_NOTE}.textContent") == "Your songs with I–V–vi–IV, the pop progression: 2Show them"
    # Your songs that play it are among the results, as your songs are: under their artists.
    assert browser.wait(same("[...document.querySelectorAll('#results article.line[data-id] h3')]"
                             ".map((h) => h.textContent).sort()", ["Minor Song", "Synthetic Song"]))
    browser.click("#results .prog-found button")  # Show them: the list, of those songs alone
    assert browser.wait("document.getElementById('results').hidden")
    assert browser.wait(same(f"{GRID}.sort()", ["Minor Song", "Synthetic Song"]))
    assert browser.js("document.getElementById('prog').textContent") == (
        "Songs with I–V–vi–IV, the pop progression · Show all")
    assert browser.js("location.hash.includes('prog=I+V+vi+IV')") and browser.js("document.getElementById('q').value") == ""
    browser.click("#prog button")
    assert browser.wait(f"{GRID}.length === 4")
    search(browser, "andalusian")  # a name from the catalogue
    assert browser.wait(f"{answer_to('andalusian')} && {PROG_NOTE} !== null && "
                        f"{PROG_NOTE}.textContent.includes('Andalusian')")
    assert browser.js(f"{PROG_NOTE}.textContent") == "Your songs with the Andalusian cadence: 1Show them"
    assert queue.snapshot() == []


def same(expression, value):
    """A JavaScript condition: the expression's value, as JSON, is ``value``'s."""
    return f"JSON.stringify({expression}) === {json.dumps(json.dumps(value, separators=(',', ':'), ensure_ascii=False))}"


def test_your_songs_among_the_results_keep_to_the_status_buttons_and_the_artist_and_the_results_say_so(cfg, live,
                                                                                                       browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4), ("stone-temple-pilots", "creep", 2)])
    creep, _, _ = library(cfg, ("Radiohead", "Creep"), ("Radiohead", "Karma Police"), ("Stone Temple Pilots", "Creep"))
    conn = db.connect(cfg.db_path)
    update_song(conn, creep.id, status="found")
    conn.commit()
    conn.close()
    note = "document.querySelector('#results .filtered')"
    browser.open(base + "#show=wanted")
    search(browser, "creep")
    assert browser.wait(f"!{BUSY} && document.getElementById('found').dataset.query === 'creep'")
    # Wanted pressed: of your songs, the wanted Creep alone; Radiohead's, found, nowhere, though UG has it.
    assert browser.wait(same(LINES, [["Stone Temple Pilots", [["Creep", "yours"]]]])), browser.js(LINES)
    assert browser.js(f"{note}.firstChild.textContent") == "Your songs here: wanted"
    browser.click("#results .filtered button")  # Show all of yours
    every = [["Radiohead", [["Creep", "yours"]]], ["Stone Temple Pilots", [["Creep", "yours"]]]]
    assert browser.wait(same(LINES, every)), browser.js(LINES)
    assert browser.js(f"{note}.hidden") is True and "show=" not in browser.js("location.hash")
    # An artist's funnel pressed in the list, then a search typed: their songs alone of yours, whatever the sites have.
    browser.press("Escape")
    assert browser.wait("document.getElementById('results').hidden")
    browser.click("#list section.artist button.artist-only")  # Radiohead
    search(browser, "creep")
    assert browser.wait(same(LINES, [["Radiohead", [["Creep", "yours"]]]])), browser.js(LINES)
    assert browser.js(f"{note}.firstChild.textContent") == "Your songs here: by Radiohead"


def test_not_in_the_list_requests_a_song_by_name_filled_in_from_the_query(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4), ("muse", "hysteria-live", 2)])  # a result: the form is under it
    browser.open(base)
    search(browser, "Muse - Hysteria")
    # Under the sites' answer, once it is in: shown before it, the answer would push it down.
    assert browser.wait(f"{answer_to('Muse - Hysteria')} && "
                        "document.getElementById('request-box').getClientRects().length > 0")
    browser.click("#request-box > summary")
    fields = browser.js("['artist', 'title'].map((n) => document.querySelector(`form.request-form [name=${n}]`).value)")
    assert fields == ["Muse", "Hysteria"]
    browser.click("form.request-form button[type=submit]")
    args = posted(queue)
    assert args[-2:] == ("Muse", "Hysteria")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Hysteria'")


SILVANA = [("silvana-estrada", "tregua", 1), ("silvana-estrada", "te-guardo", 2), ("silvanas", "adio-maria", 1),
           ("marisa-monte", "na-estrada", 2), ("que", "algo", 1)]
REQUEST_FIELDS = "['artist', 'title'].map((n) => document.querySelector(`form.request-form [name=${n}]`).value)"


def test_a_query_with_no_dash_fills_the_request_form_in_with_the_artist_an_index_knows(cfg, live, browser):
    # The owner's "Silvana Estrada Que problema": the artist the Ultimate Guitar index knows, then the title it lacks,
    # never the query cut at its first space; a query no known artist starts is the title alone, to be edited.
    base, queue, _ = live
    sites(cfg, ug=SILVANA)
    browser.open(base)
    for query, fields in (("Que problema", ["", "Que problema"]),
                          ("Silvana Estrada Qué problema", ["Silvana Estrada", "Qué problema"])):
        search(browser, query)
        assert browser.wait(answer_to(query))
        assert browser.js(REQUEST_FIELDS) == fields, query  # filled in as the answer is drawn
    assert browser.js("document.getElementById('request-box').getClientRects().length > 0")  # under the results
    browser.click("#request-box > summary")
    browser.click("form.request-form button[type=submit]")
    assert posted(queue)[-2:] == ("Silvana Estrada", "Qué problema")
    assert browser.wait("!document.getElementById('requested').hidden && "
                        "document.querySelector('#requested article h3').textContent === 'Qué problema'")


def keyed(page, text):
    """``text`` typed with real keys, each pressed and let go: a key the page's script takes is never typed."""
    for character in text:
        page.send("Input.dispatchKeyEvent", type="keyDown", key=character, text=character)
        page.send("Input.dispatchKeyEvent", type="keyUp", key=character)


def test_a_slash_typed_in_the_request_form_is_the_fields(cfg, live, browser):
    # "/" elsewhere on the page goes to the search box; in a field of the form, "AC/DC" or "Either/Or" is typed.
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4), ("muse", "hysteria-live", 2)])  # a result: the form is under it
    browser.open(base)
    search(browser, "Muse - Hysteria")
    assert browser.wait(f"{answer_to('Muse - Hysteria')} && "
                        "document.getElementById('request-box').getClientRects().length > 0")
    browser.click("#request-box > summary")
    for name, text in (("artist", "AC/DC"), ("title", "Either/Or")):
        browser.js(f"(() => {{ const f = document.querySelector('form.request-form [name={name}]'); f.focus(); "
                   "f.select(); })()")
        keyed(browser, text)
        field = f"document.querySelector('form.request-form [name={name}]')"
        assert browser.wait(f"{field}.value === {json.dumps(text)}"), browser.js(f"{field}.value")
        assert browser.js(f"document.activeElement === {field}")
    assert browser.js("document.getElementById('q').value") == "Muse - Hysteria"
    assert browser.js("document.getElementById('request-box').getClientRects().length > 0")
    # Anywhere else, "/" still goes to the search box, its text selected, and types nothing.
    browser.js("document.activeElement.blur()")
    keyed(browser, "/")
    assert browser.wait("document.activeElement === document.getElementById('q')")
    assert browser.js("document.getElementById('q').value") == "Muse - Hysteria"


def test_the_fold_for_an_artist_the_index_cant_see_shows_its_commands_as_code(cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    fold = "#results .nothing details.why-unseen"
    for url in (base + "#q=" + quote("宋冬野") + "&all=1", base + "lookup?q=" + quote("宋冬野")):
        browser.open(url)
        assert browser.wait(f"!!document.querySelector('{fold}')"), url
        assert browser.js(f"document.querySelector('{fold}').open") is False  # folded
        assert "`" not in browser.js(f"document.querySelector('{fold}').textContent")
        assert browser.js(f"[...document.querySelectorAll('{fold} code')].map((c) => c.textContent)") == [
            '[artist_url]\n"宋冬野" = "https://www.ultimate-guitar.com/artist/…"', 'caracole add ARTIST "宋冬野"']


def read_to(cfg, letters):
    """LaCuerda's listings read whole for ``letters`` alone (an artist in the last one), the rest not yet."""
    from caracole import lacuerda_index as li
    from caracole.db import kv_set_json
    from caracole.lacuerda import LCArtist

    conn = db.connect(cfg.db_path)
    li.store_artists(conn, f"tabs/{letters[-1]}/index0.html", [LCArtist("calle_13", "Calle 13", 80)])
    kv_set_json(conn, li.PAGES_KEY, {f"tabs/{x}/index0.html": {"pages": ["index0.html"]} for x in letters})
    conn.commit()
    conn.close()


def blocking(cfg, source):
    """``source`` blocked caracole once, as a 403 would."""
    from caracole.health import record_block

    conn = db.connect(cfg.db_path)
    record_block(conn, source, datetime(2026, 10, 19, tzinfo=UTC), "HTTP 403: a challenge")
    conn.commit()
    conn.close()


NOTHING = "#results .nothing"
# A search that found nothing on the sites: its band, its line's query, its Request (its words, and its name for a
# screen reader), and whether it shows marks of its own (none: the row under the box has them).
MISS = ("(() => { const s = document.querySelector('#results .nothing'); const l = s.querySelector('article'); "
        "const go = l.querySelector('.line-action button, .row-action button'); "
        "return { band: s.querySelector('h2').textContent, query: l.querySelector('h2, h3').textContent, "
        "request: [go.textContent, go.getAttribute('aria-label')], "
        "marks: s.querySelectorAll('.source, .looked, .count-mark').length }; })()")
# What its chevron (its "⋯" on the lookup page) holds: whether it is open, its buttons, and the fold of why caracole
# may not see an artist (its summary, folded or not, its code).
DRAWER = ("(() => { const s = document.querySelector('#results .nothing'); const p = s.querySelector('.line-panel, "
          ".row-panel'); const f = s.querySelector('details.why-unseen'); return { open: p ? !p.hidden : null, "
          "buttons: p ? [...p.querySelectorAll('button')].map((b) => b.textContent) : [], "
          "why: f ? f.querySelector('summary').textContent : null, folded: f ? !f.open : null, "
          "code: f ? [...f.querySelectorAll('code')].map((x) => x.textContent) : [] }; })()")
# What the results show that requests a song by name, by its words.
REQUESTS = ("[...document.querySelectorAll('#results button, #results summary')].filter((b) => b.checkVisibility() && "
            "/Request/.test(b.textContent)).map((b) => b.textContent.replace(/^[+]/, '').trim())")
BACK = ("[...document.querySelectorAll('#results button')].some((b) => b.textContent === 'Back to your songs' && "
        "b.checkVisibility())")
OLD_NOTES = "document.querySelectorAll('#results .skipped, #results .index-hint, #results .read-page.unlisted').length"
# What nothing found looks like under the box, with LaCuerda's listings read to C and MuseScore blocking caracole:
# none of yours, nothing where it searched, MuseScore not searched.
NOWHERE = [["library", "done", 0], ["ug", "done", 0], ["gtptabs", "empty", 0], ["lacuerda", "partial", 0],
           ["musescore", "blocked", None], ["harptabs", "empty", 0], ["gametabs", "empty", 0]]
NOWHERE_SAID = ["0 of your songs", "0 on Ultimate Guitar", "0 on gtptabs.com: index empty",
                "0 on LaCuerda: index in part, up to C", "MuseScore: blocked", "0 on harptabs.com: index empty",
                "0 on gametabs.net: index empty"]
# The colour and the fill of the mark under the box of a site in STATE, or of SOURCE's.
SHADE = ("(() => { const s = getComputedStyle(document.querySelector('#bar-counts li[data-state=\"STATE\"]')); "
         "return [s.color, s.backgroundColor]; })()")
COUNT_COLOUR = ("getComputedStyle(document.querySelector('#bar-counts li[data-source=\"SOURCE\"] .count-n')).color")


def css_colour(page, value):
    """The colour a CSS value (``var(--artist)``) computes to on the page."""
    return page.js("(() => { const p = document.createElement('p'); p.style.color = " + json.dumps(value) + "; "
                   "document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; })()")


def test_a_query_that_finds_nothing_is_one_line_under_a_quiet_band_its_request_where_open_sits(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    read_to(cfg, ("_num", "a", "b", "c"))
    blocking(cfg, "musescore")
    browser.open(base)
    search(browser, "lynrd")
    assert browser.wait(f"{answer_to('lynrd')} && !!document.querySelector('{NOTHING}')")
    # Its band says so in words, and its line has no marks of its own: the row under the box has each site, at 0.
    assert browser.js(MISS) == {"band": "Not on the sites", "query": "“lynrd”",
                                "request": ["Request", "Request “lynrd” by name"], "marks": 0}
    # A line of the list's, in the groups' box where an artist's band would be; no result of the sites.
    assert browser.js(f"document.querySelector('{NOTHING}').parentElement.matches('#results .groups')")
    assert browser.js(f"document.querySelector('{NOTHING} article').matches('.line:not(.hit)') && {HITS} === 0")
    assert browser.js(COUNTS) == NOWHERE
    # Each mark: its count and its site, and how far where it wasn't searched whole; its detail in its tooltip, after
    # its name, and its description.
    words = browser.js(COUNT_WORDS)
    assert [w[0] for w in words] == NOWHERE_SAID
    assert all(w[1] == w[0] + "\n" + w[2] for w in words[1:]), words
    assert "still being read: 1 artist so far, with #, A–C read whole" in words[3][1]
    assert words[4][2] == "MuseScore is blocking caracole, so its index is empty."
    # Quiet where it found nothing (an index empty yet too), amber in part, red only where a site blocks caracole.
    done, empty, partial, blocked = (browser.js(SHADE.replace("STATE", state))
                                     for state in ("done", "empty", "partial", "blocked"))
    assert done == empty and done[0] == css_colour(browser, "var(--muted)"), (done, empty)
    assert partial[0] == css_colour(browser, "var(--wanted)") and blocked[0] == css_colour(browser, "var(--failed)")
    # One Request; no Back to your songs (the box's × and Escape go back); the words under the box a screen reader's.
    assert browser.js(REQUESTS) == ["Request"]
    assert browser.js("document.getElementById('request-box').checkVisibility()") is False
    assert browser.js(BACK) is False
    assert browser.js(STATUS) == "Nothing on the sites" and browser.js(WORDS_SHOWN) is False
    assert browser.js(NO_SEARCHED_LINE)
    assert browser.js(OLD_NOTES) == 0 and browser.js("document.querySelector('#results .did-you-mean')") is None
    # Its chevron opens the rest: Ask LaCuerda (L is unread), and why caracole may not see an artist, folded.
    assert browser.js(DRAWER)["open"] is False
    browser.click(f"{NOTHING} .line-more")
    assert browser.js(DRAWER) == {
        "open": True, "buttons": ["Ask LaCuerda · 1 request"], "why": "Why can't caracole find it?", "folded": True,
        "code": ['[artist_url]\n"lynrd" = "https://www.ultimate-guitar.com/artist/…"', 'caracole add ARTIST "lynrd"']}
    assert browser.js(f"document.querySelector('{NOTHING} .ask-lacuerda').title").startswith(
        "LaCuerda's list doesn't reach L yet")
    # Enter spends nothing: on to the line, as to a result's, and no request is made.
    browser.js("document.getElementById('q').focus()")
    browser.press("Enter")
    assert browser.wait(f"document.activeElement === document.querySelector('{NOTHING} article')")
    time.sleep(0.6)
    assert queue.snapshot() == []
    # Request: the form, filled in from the query, open and in view, the focus on the artist it lacks.
    browser.click(f"{NOTHING} .line-action button")
    assert browser.wait("document.getElementById('request-box').open")
    fields = browser.js("['artist', 'title'].map((n) => document.querySelector(`form.request-form [name=${n}]`).value)")
    assert fields == ["", "lynrd"]
    assert browser.wait("document.activeElement === document.querySelector('form.request-form [name=artist]')")
    assert browser.wait("(() => { const r = document.getElementById('request-box').getBoundingClientRect(); "
                        "return r.top >= 0 && r.top < innerHeight; })()")
    assert queue.snapshot() == []  # opening the form asks nothing
    # Folded again, the form goes, and the focus is back on Request.
    browser.click("#request-box > summary")
    assert browser.wait("!document.getElementById('request-box').checkVisibility()")
    assert browser.wait(f"document.activeElement === document.querySelector('{NOTHING} .line-action button')")


def test_ask_lacuerda_is_offered_only_for_a_name_under_a_letter_its_listings_dont_reach(cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    read_to(cfg, ("_num", "a", "b", "c"))
    browser.open(base)
    search(browser, "camilo sesto")  # C is read whole: LaCuerda has no Camilo Sesto
    assert browser.wait(f"!!document.querySelector('{NOTHING}') && "
                        "document.getElementById('found').dataset.query === 'camilo sesto'")
    assert browser.js(MISS)["request"] == ["Request", "Request “camilo sesto” by name"]
    assert browser.js(DRAWER)["buttons"] == []


def game_and_harp_indexes(cfg):
    """gametabs.net's index (two of its seven game pages read) and harptabs.com's (two of its three artists' pages), as
    test_search.py makes them."""
    from test_search import gametabs_index, harptabs_index

    conn = db.connect(cfg.db_path)
    gametabs_index(conn)
    harptabs_index(conn)
    conn.commit()
    conn.close()


# Where each part of the bar is, top to bottom: the box, the row of marks, the results; and whether the row is in the
# bar kept at the top.
PLACES = ("(() => { const at = (s) => document.querySelector(s).getBoundingClientRect(); return { field: at('.searchbar "
          ".field').bottom, top: at('#bar-counts').top, bottom: at('#bar-counts').bottom, results: at('#results .groups')"
          ".top, kept: document.querySelector('.searchbar').contains(document.getElementById('bar-counts')) }; })()")


def test_what_each_site_found_is_its_mark_and_count_under_the_box_and_no_line_under_the_results_says_it_again(
        cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    read_to(cfg, ("_num", "a", "b", "c"))
    blocking(cfg, "musescore")
    game_and_harp_indexes(cfg)
    library(cfg, ("Hollow Knight", "Resting Grounds"))
    browser.open(base)
    search(browser, "hollow knight")
    assert browser.wait(f"{answer_to('hollow knight')} && {HITS} >= 1 && {COUNTS_SHOWN}")
    # Under the box, in the bar kept at the top, above the results: your songs first (the page's own mark), then each
    # site in the order caracole searches them, and how many it found there.
    place = browser.js(PLACES)
    assert place["field"] <= place["top"] < place["bottom"] <= place["results"] and place["kept"], place
    assert browser.js(COUNTS) == [["library", "done", 1], ["ug", "done", 0], ["gtptabs", "empty", 0],
                                  ["lacuerda", "partial", 0], ["musescore", "blocked", None],
                                  ["harptabs", "partial", 0], ["gametabs", "partial", 5]]
    assert browser.js("document.querySelector('#bar-counts li[data-source=library] svg.yours-mark') !== null")
    # Its count beside each; a glyph for what its colour says too: in part (a ring not yet whole), blocked (a ban).
    # Nothing where it wasn't searched.
    assert browser.js(COUNT_SHOWN) == [["1", []], ["0", []], ["0", []], ["0", ["part"]], ["", ["blocked"]],
                                       ["0", ["part"]], ["5", ["part"]]]
    # Each mark's name, for a screen reader: its count on its site, and how far its index has got; its detail in its
    # tooltip, after the name, and its description.
    words = browser.js(COUNT_WORDS)
    assert [w[0] for w in words] == [
        "1 of your songs", "0 on Ultimate Guitar", "0 on gtptabs.com: index empty",
        "0 on LaCuerda: index in part, up to C", "MuseScore: blocked",
        "0 on harptabs.com: index in part, 2 of 3 artists", "5 on gametabs.net: index in part, 2 of 7 games"]
    assert words[0] == ["1 of your songs", "1 of your songs", None]
    assert words[5][1:] == [
        "0 on harptabs.com: index in part, 2 of 3 artists\nharptabs.com's artist pages are still being read: 2 of 3 "
        "artists so far; caracole harptabs --index reads the rest.",
        "harptabs.com's artist pages are still being read: 2 of 3 artists so far; caracole harptabs --index reads the "
        "rest."]
    assert browser.js("document.getElementById('bar-counts').getAttribute('aria-label')") == "Found on each site"
    # In the text's colour where it found something, muted where it found nothing; amber in part, red blocked.
    assert browser.js(COUNT_COLOUR.replace("SOURCE", "library")) == css_colour(browser, "var(--text)")
    assert browser.js(COUNT_COLOUR.replace("SOURCE", "ug")) == css_colour(browser, "var(--muted)")
    assert browser.js(SHADE.replace("STATE", "partial"))[0] == css_colour(browser, "var(--wanted)")
    assert browser.js(SHADE.replace("STATE", "blocked"))[0] == css_colour(browser, "var(--failed)")
    # The words a screen reader hears as the answer comes, which the box is described by: the counts that aren't 0.
    assert browser.js(STATUS) == "1 of your songs · 5 on gametabs.net"
    assert browser.js(WORDS_SHOWN) is False
    assert browser.js("document.getElementById('bar-status').getAttribute('aria-live')") == "polite"
    assert browser.js("document.getElementById('q').getAttribute('aria-describedby')") == "bar-status"
    # Nothing under the results says it again; what stays there is what may find more: Ask LaCuerda (H is unread),
    # and why caracole may not see an artist.
    assert browser.js(NO_SEARCHED_LINE)
    assert browser.js("document.querySelector('#results .notes-line .ask-lacuerda').textContent") == (
        "Ask LaCuerda for “hollow knight” (1 request)")
    assert browser.js("!!document.querySelector('#results .notes-line details.why-unseen')")
    assert browser.js(OLD_NOTES) == 0
    # Under results the request form is the one Request, and Back to your songs the way back.
    assert browser.js(REQUESTS) == ["Not in the list? Request it by name"]
    assert browser.js(BACK) is True
    # Another answer, other counts: heard as words, the marks drawn again. A site's count is its songs, as its lines
    # show them: the three of Billy Joel's group (his artist's, his most viewed songs), never one for the artist.
    search(browser, "billy joel")
    assert browser.wait(f"{answer_to('billy joel')} && {HITS} >= 1")
    harp = browser.js("Number(document.querySelector('#bar-counts li[data-source=harptabs]').dataset.n)")
    lines = browser.js("document.querySelectorAll('#results article.line .line-sources .source[data-source=harptabs]')"
                       ".length")
    assert harp == lines == 3 and browser.js(STATUS) == "3 on harptabs.com"
    assert browser.js(NO_SEARCHED_LINE)


def test_the_row_under_the_box_says_in_words_what_no_mark_can(cfg, live, browser):
    # Before anything is typed nothing; a hint in words before three letters; "Searching the sites…" in words until the
    # first answer; then the marks, which stay (dimmed) while the next query's answer comes; Escape leaves them.
    base, _, asked = live
    sites(cfg, ug=[("radiohead", "creep", 4), ("radiohead", "karma-police", 2)])
    browser.open(base)
    assert browser.js(STATUS) == "" and browser.js(COUNTS_SHOWN) is False
    search(browser, "ra")
    assert browser.wait(f"{STATUS} === 'None of yours match: three letters search the sites too'")
    assert browser.js(WORDS_SHOWN) and browser.js(COUNTS_SHOWN) is False
    asked.held = threading.Event()
    browser.type("d")
    assert browser.wait(f"{STATUS} === 'Searching the sites…'")
    assert browser.js(WORDS_SHOWN) and browser.js(COUNTS_SHOWN) is False  # no answer yet: words alone
    asked.held.set()
    assert browser.wait(f"{answer_to('rad')} && {COUNTS_SHOWN}")
    assert browser.js(WORDS_SHOWN) is False
    counts = browser.js(COUNTS)
    asked.held = threading.Event()
    browser.type("io")
    assert browser.wait(f"{STATUS} === 'Searching the sites…'")
    # The answer before stays until the next one comes, dimmed; the words are a screen reader's.
    assert browser.js(COUNTS) == counts and browser.js(COUNTS_SHOWN) and browser.js(WORDS_SHOWN) is False
    assert browser.js("document.querySelector('.searchbar .bar-said').classList.contains('busy')")
    assert float(browser.js("getComputedStyle(document.getElementById('bar-counts')).opacity")) < 1
    asked.held.set()
    asked.held = None
    assert browser.wait(f"{answer_to('radio')} && !document.querySelector('.searchbar .bar-said.busy')")
    assert browser.js(COUNTS_SHOWN) and float(browser.js(
        "getComputedStyle(document.getElementById('bar-counts')).opacity")) == 1
    browser.press("Escape")  # your songs again: the line says what typing and Enter do
    assert browser.wait(f"!{COUNTS_SHOWN}")
    assert browser.js(WORDS_SHOWN) and browser.js(STATUS) == "None of yours match: Enter searches the sites"


def test_what_follows_an_answer_is_said_in_words_beside_its_marks(cfg, live, browser):
    # "+ 3 more by Estopa": what it listed, in words after the marks, which stay, as the answer does, Ultimate
    # Guitar's counting the songs its lines show now.
    base, _, _ = live
    sites(cfg, ug=[("estopa", f"cancion-{n}", 1) for n in range(6)])
    browser.open(base)
    search(browser, "estopa")
    assert browser.wait(f"{answer_to('estopa')} && !!document.querySelector('#results .more-by') && {COUNTS_SHOWN}")
    counts = browser.js(COUNTS)
    assert counts[1] == ["ug", "done", 3] and browser.js(STATUS) == "3 on Ultimate Guitar"
    browser.click("#results .more-by")
    assert browser.wait(f"{STATUS} === 'Estopa: 6 songs on Ultimate Guitar'")
    assert browser.js(WORDS_SHOWN) and browser.js(COUNTS_SHOWN)
    assert browser.js(COUNTS) == [counts[0], ["ug", "done", 6]] + counts[2:]
    row = browser.js("(() => { const c = document.getElementById('bar-counts').getBoundingClientRect(); "
                     "const w = document.getElementById('bar-status').getBoundingClientRect(); "
                     "return [w.left >= c.right, Math.abs((w.top + w.bottom) - (c.top + c.bottom)) < 8]; })()")
    assert row == [True, True], row  # beside the marks, on their line


def test_a_typo_is_an_artist_band_first_whose_row_lists_their_songs_then_the_miss(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=SKYNYRD)
    browser.open(base)
    search(browser, "lynrd")
    assert browser.wait(f"{answer_to('lynrd')} && !!document.querySelector('#results section.meant')")
    # The artist it may have meant: a band as an artist's, their songs on UG counted, then the miss's band.
    assert browser.js(GROUPS) == ["Did you mean Lynyrd Skynyrd · 5 songs on UG"]
    assert browser.js("[...document.querySelectorAll('#results .groups > section')].map((s) => s.className)") == [
        "artist meant", "nothing"]
    assert browser.js("getComputedStyle(document.querySelector('#results section.meant .artist-name')).color") == (
        css_colour(browser, "var(--artist)"))
    their = "#results section.meant .their-songs"
    assert browser.js(f"document.querySelector('{their}').textContent") == "Their 5 songs on UG›"
    assert browser.js(f"document.querySelector('{their} [aria-hidden=true]').textContent") == "›"
    assert browser.js(STATUS) == "Nothing on the sites · did you mean Lynyrd Skynyrd?"
    assert browser.js(DID_YOU_MEAN) is None and browser.js(HITS) == 0 and browser.js(BACK) is False
    searched = len(asked)
    browser.click(their)  # their songs, in their band, as an artist's are
    assert browser.wait(f"{HITS} === 5")
    assert browser.js(GROUPS) == ["Did you mean Lynyrd Skynyrd · UG 5"]
    assert browser.js(TITLES) == ["Free Bird", "Sweet Home Alabama", "Simple Man", "That Smell", "Tuesdays Gone"]
    assert browser.js("document.activeElement.matches('#results section.artist')")
    # Results now: the miss gives way, what was listed said in words beside the marks under the box, and no line
    # under the results says where caracole looked.
    assert browser.js("document.querySelector('#results .nothing')") is None
    assert browser.js(STATUS) == "Lynyrd Skynyrd: 5 songs on Ultimate Guitar" and browser.js(WORDS_SHOWN)
    assert browser.js(COUNTS_SHOWN) and browser.js(NO_SEARCHED_LINE)
    assert browser.js(COUNTS)[1] == ["ug", "done", 5]  # the songs its lines show now
    assert len(asked) == searched and queue.snapshot() == []  # their songs came from /api/artist: no search, no site


def test_a_typos_band_is_the_one_of_the_artist_you_have_songs_of(cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=SKYNYRD)
    library(cfg, ("Lynyrd Skynyrd", "Free Bird"))
    browser.open(base)
    search(browser, "lynrd")
    assert browser.wait(f"{answer_to('lynrd')} && !!document.querySelector('#results section.meant')")
    assert browser.js(GROUPS) == ["Did you mean Lynyrd Skynyrd · 5 songs on UG · you have 1"]
    browser.click("#results section.meant .their-songs")
    assert browser.wait(f"{HITS} === 4")  # your Free Bird is your own line, in their band
    assert browser.js(LINES) == [["Lynyrd Skynyrd", [["Free Bird", "yours"], ["Sweet Home Alabama", "ug"],
                                                     ["Simple Man", "ug"], ["That Smell", "ug"],
                                                     ["Tuesdays Gone", "ug"]]]]


def test_the_lookup_page_shows_the_same_band_and_line(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    browser.open(base + "lookup?q=lynrd")
    assert browser.wait(f"!!document.querySelector('{NOTHING}')")
    assert browser.js(MISS) == {"band": "Not on the sites", "query": "“lynrd”",
                                "request": ["Look up", "Look up “lynrd” by name"], "marks": 0}
    assert browser.js(f"document.querySelector('{NOTHING} article').matches('.row:not(.hit)')")
    # The same row of marks under its box, each site at 0, and the words a screen reader's.
    assert browser.js(COUNTS) == [["library", "done", 0], ["ug", "done", 0], ["gtptabs", "empty", 0],
                                  ["lacuerda", "empty", 0], ["musescore", "empty", 0], ["harptabs", "empty", 0],
                                  ["gametabs", "empty", 0]]
    assert browser.js(LOOKUP_STATUS) == "Nothing on the sites" and browser.js(LOOKUP_WORDS_SHOWN) is False
    assert browser.js(NO_SEARCHED_LINE)
    assert browser.js("document.getElementById('by-name-box').checkVisibility()") is False  # one Look up
    browser.click(f"{NOTHING} .row-more")
    assert browser.js(DRAWER)["buttons"] == ["Ask LaCuerda · 1 request"]  # LaCuerda's listings: none read
    browser.click(f"{NOTHING} .row-action button")  # its form by name, filled in, open, the focus in it
    assert browser.wait("document.getElementById('by-name-box').open")
    assert browser.js("document.getElementById('by-name-box').checkVisibility()")
    assert browser.js("[document.querySelector('#by-name [name=artist]').value, "
                      "document.querySelector('#by-name [name=title]').value]") == ["", "lynrd"]
    assert browser.js("document.activeElement.name") == "artist"
    assert browser.js("document.querySelector('#results .did-you-mean')") is None  # no artist spelled close to it
    assert queue.snapshot() == []


def test_the_lookup_page_says_what_each_site_found_as_the_library_page_does(cfg, live, browser):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    read_to(cfg, ("_num", "a", "b", "c"))
    blocking(cfg, "musescore")
    game_and_harp_indexes(cfg)
    library(cfg, ("Hollow Knight", "Resting Grounds"))
    browser.open(base + "lookup?q=hollow%20knight")
    assert browser.wait(f"{HITS} >= 1 && {COUNTS_SHOWN}")
    assert browser.js(COUNTS) == [["library", "done", 1], ["ug", "done", 0], ["gtptabs", "empty", 0],
                                  ["lacuerda", "partial", 0], ["musescore", "blocked", None],
                                  ["harptabs", "partial", 0], ["gametabs", "partial", 5]]
    assert [w[0] for w in browser.js(COUNT_WORDS)][-1] == "5 on gametabs.net: index in part, 2 of 7 games"
    place = browser.js("(() => { const c = document.getElementById('bar-counts').getBoundingClientRect(); return "
                       "[document.querySelector('.search').contains(document.getElementById('bar-counts')), "
                       "c.top >= document.getElementById('q').getBoundingClientRect().bottom, "
                       "c.bottom <= document.getElementById('results').getBoundingClientRect().top]; })()")
    assert place == [True, True, True]
    assert browser.js(LOOKUP_STATUS) == "1 of your songs · 5 on gametabs.net"
    assert browser.js(LOOKUP_WORDS_SHOWN) is False
    assert browser.js(NO_SEARCHED_LINE)  # no muted line under the rows says it again: Ask LaCuerda is there alone
    assert browser.js("document.querySelector('#results .notes-line .ask-lacuerda').textContent") == (
        "Ask LaCuerda for “hollow knight” (1 request)")


def test_a_query_found_nowhere_whose_artist_an_index_lists_fills_both_forms_by_name_in_with_them(cfg, live, browser):
    # harptabs.com's sitemap lists Silvana Estrada, whose page caracole hasn't read: no site has the song, and both
    # pages' Request (Look up) fill their form in with her name, then the title.
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    conn = db.connect(cfg.db_path)
    conn.execute("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) "
                 "VALUES ('artist/4321/silvana-estrada', 'artist', 4321, 'silvana-estrada', 'sitemap')")
    conn.commit()
    conn.close()
    query = "Silvana Estrada Que problema"
    browser.open(base)
    search(browser, query)
    assert browser.wait(f"{answer_to(query)} && !!document.querySelector('{NOTHING} .line-action button')")
    browser.click(f"{NOTHING} .line-action button")
    assert browser.wait("document.getElementById('request-box').open")
    assert browser.js(REQUEST_FIELDS) == ["Silvana Estrada", "Que problema"]
    assert browser.wait("document.activeElement === document.querySelector('form.request-form [name=artist]')")
    browser.open(base + "lookup?q=" + quote(query))
    assert browser.wait(f"!!document.querySelector('{NOTHING} .row-action button')")
    browser.click(f"{NOTHING} .row-action button")
    assert browser.wait("document.getElementById('by-name-box').open")
    assert browser.js("[document.querySelector('#by-name [name=artist]').value, "
                      "document.querySelector('#by-name [name=title]').value]") == ["Silvana Estrada", "Que problema"]
    assert queue.snapshot() == []  # filled in, for you to check: nothing sent


EAGLES = [("eagles", "hotel-california", 6), ("eagles", "take-it-easy", 2), ("gipsy-kings", "hotel-california", 1)]
MEANT_LINE = "#results section.meant article.hit"


def test_a_title_spelled_close_is_a_line_in_its_artists_band_whose_get_it_looks_it_up(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=EAGLES)
    browser.open(base)
    search(browser, "hotl califronia")
    assert browser.wait(f"{answer_to('hotl califronia')} && !!document.querySelector('{MEANT_LINE}')")
    # The song it may have meant: a line in its artist's band, their songs on UG counted, then the miss's band.
    assert browser.js(GROUPS) == ["Did you mean Eagles · 2 songs on UG"]
    assert browser.js(LINES) == [["Eagles", [["Hotel California", "ug"]]]]
    assert browser.js("[...document.querySelectorAll('#results .groups > section')].map((s) => s.className)") == [
        "artist meant", "nothing"]
    assert browser.js(STATUS) == "Nothing on the sites · did you mean Hotel California by Eagles?"
    assert browser.js(f"document.querySelector('{MEANT_LINE} .line-facts').textContent") == "chords ×6"
    assert browser.js(f"document.querySelector('{MEANT_LINE} .line-action button').textContent") == "Get it"
    assert browser.js(f"document.querySelector('{MEANT_LINE} h3 .title-get').getAttribute('aria-label')") == (
        "Get Eagles - Hotel California")  # its name gets it, as its Get it does
    assert browser.js("document.querySelector('#results section.meant .their-songs').textContent") == (
        "Their 2 songs on UG›")
    browser.press("Enter")  # to the first line: a suggestion is never what Enter asks for
    assert browser.wait(f"document.activeElement === document.querySelector('{MEANT_LINE}')")
    time.sleep(0.3)
    assert queue.snapshot() == []
    searched = len(asked)
    browser.click(f"{MEANT_LINE} .line-action button")  # Get it: the search's lookup of that Ultimate Guitar song
    args = posted(queue)
    assert args[:3] == ("get", "--progress", "--ug=eagles/hotel-california") and args[-2:] == ("Eagles",
                                                                                                 "Hotel California")
    assert len(asked) == searched


def test_a_title_spelled_close_that_you_have_is_your_own_line_in_its_band(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=EAGLES)
    (mine,) = library(cfg, ("Eagles", "Hotel California"))
    conn = db.connect(cfg.db_path)
    folder = song_dir(cfg.library_dir, mine)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sheet.pdf").write_bytes(b"%PDF-1.4")
    update_song(conn, mine.id, status="found")
    conn.close()
    browser.open(base)
    search(browser, "hotl califrnai")  # two typos: among your songs, though not well, and suggested
    assert browser.wait(f"{answer_to('hotl califrnai')} && !!document.querySelector('#results section.meant')")
    assert browser.js(GROUPS) == ["Did you mean Eagles · 2 songs on UG · you have 1"]
    assert browser.js(LINES) == [["Eagles", [["Hotel California", "yours"]]]]  # one line: your own, which opens it
    assert browser.js("document.querySelector('#results section.meant article.line[data-id] .line-action a')"
                      ".textContent") == "Open PDF"
    # Your song is among the results: the words say it first, as the marks do.
    assert browser.js(STATUS) == "1 of your songs · nothing on the sites · did you mean Hotel California by Eagles?"
    assert browser.js(COUNTS)[0] == ["library", "done", 1]
    assert queue.snapshot() == []


def test_the_lookup_page_suggests_a_title_as_a_row_whose_get_it_looks_it_up(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=EAGLES)
    browser.open(base + "lookup?q=hotl%20califronia")
    assert browser.wait("!!document.querySelector('#results .did-you-mean .hit')")
    assert browser.js("[...document.querySelectorAll('#results h2.group')].map(h => h.textContent)") == [
        "Did you mean", "Not on the sites"]
    row = "#results .did-you-mean .hit"
    assert browser.js(f"[document.querySelector('{row} .row-title').textContent, document.querySelector('{row} "
                      f".row-artist').textContent, document.querySelector('{row} .source').dataset.source, "
                      f"document.querySelector('{row} .row-action button').textContent]") == [
        "Hotel California", "Eagles", "ug", "Get it"]
    assert browser.js(LOOKUP_STATUS) == "Nothing on the sites · did you mean Hotel California by Eagles?"
    assert browser.js(LOOKUP_WORDS_SHOWN) is False and browser.js(COUNTS_SHOWN)
    browser.click(f"{row} .row-action button")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", "--ug=eagles/hotel-california") and args[-2:] == ("Eagles",
                                                                                                 "Hotel California")


NO_SIDEWAYS = "document.documentElement.scrollWidth <= innerWidth"


def test_the_bar_and_its_results_fit_a_phone(cfg, live, phone):
    base, _, _ = live
    sites(cfg, ug=[*[("the-red-hot-chili-peppers-and-friends", f"a-rather-long-song-title-{n}", 2) for n in range(6)],
                   *[("estopa", f"cancion-{n}", 1) for n in range(6)]],
          gtptabs=["https://gtptabs.com/tabs/18/the-red-hot-chili-peppers-and-friends/a-rather-long-song-title-1.html"],
          musescore=["https://musescore.com/song/a_rather_long_song_title_1-5"])
    removed(cfg, "The Red Hot Chili Peppers and Friends", "A Rather Long Song Title 9")
    phone.open(base + "#show=found")  # Found pressed: the results' head says so, with Show all of yours
    # The box, a thumb's height, and Filter, Sort and Select beside it across the bar: typing searches, so no button for that.
    field = phone.js("(() => { const q = document.getElementById('q').getBoundingClientRect(); "
                     "return [q.left, innerWidth - document.getElementById('tools').getBoundingClientRect().right, q.height]; })()")
    assert field[0] <= 17 and field[1] <= 17 and field[2] >= 44, field
    search(phone, "a rather long song title")
    assert phone.wait(f"{answer_to('a rather long song title')} && {HITS} >= 4 && "
                      "!!document.querySelector('#results .removed-hit')")
    assert phone.js("document.querySelector('#results .filtered').getClientRects().length") == 1
    assert phone.js(NO_SIDEWAYS)
    small = phone.js(small_targets())
    assert small == [], small
    for line in phone.js("[...document.querySelectorAll('#results .hit')].map((a) => a.getBoundingClientRect().height)"):
        assert line <= 2 * 44 + 12, line  # two lines a song, as yours are
    search(phone, "estopa")  # an artist: their group, and its "+ 3 more by Estopa"
    assert phone.wait(f"{answer_to('estopa')} && !!document.querySelector('#results .more-by')")
    assert phone.js(NO_SIDEWAYS) and phone.js(small_targets()) == []


# What the miss and a typo's band say, against what is behind them: WCAG's ratio of each text's colour to the first
# solid background under it (a mark's letters on its own fill); and how light the line's box is.
READS = """(() => {
  const rgb = (text) => (/^rgba?\\(([\\d.]+),\\s*([\\d.]+),\\s*([\\d.]+)(?:,\\s*([\\d.]+))?\\)$/.exec(text) || []).slice(1)
    .map(Number);
  const lum = (c) => {
    const f = (v) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const behind = (n) => {
    for (let at = n; at; at = at.parentElement) {
      const c = rgb(getComputedStyle(at).backgroundColor);
      if (c.length && !(c[3] < 1)) return c;
    }
    return [255, 255, 255];
  };
  const ratio = (n) => {
    const [hi, lo] = [lum(rgb(getComputedStyle(n).color)), lum(behind(n))].sort((a, b) => b - a);
    return Math.round((hi + 0.05) / (lo + 0.05) * 100) / 100;
  };
  const read = {};
  for (const [name, selector] of [["band", ".nothing > h2"],
      ["query", ".nothing article h3"], ["request", ".nothing .line-action button"],
      ["name", "section.meant .artist-name"], ["counts", "section.meant .artist-counts"], ["their", ".their-songs"],
      ["done", "#bar-counts li[data-source=ug] .count-n"], ["empty", "#bar-counts li[data-state=empty] .source"],
      ["partial", "#bar-counts li[data-state=partial] .count-n"],
      ["blocked", "#bar-counts li[data-state=blocked] .source"], ["ask", ".nothing .ask-lacuerda"],
      ["why", ".nothing .why-unseen summary"]]) {
    const n = document.querySelector(selector.startsWith("#") ? selector : "#results " + selector);
    read[name] = n ? ratio(n) : null;
  }
  read.box = Math.round(lum(behind(document.querySelector("#results .nothing article"))) * 1000) / 1000;
  return read;
})()"""


def test_a_title_suggestion_fits_a_phone(cfg, live, phone):
    base, _, _ = live
    sites(cfg, ug=EAGLES)
    phone.open(base)
    search(phone, "hotl califronia")
    assert phone.wait(f"{answer_to('hotl califronia')} && !!document.querySelector('{MEANT_LINE}') && "
                      f"!!document.querySelector('{NOTHING}')")
    assert phone.js(NO_SIDEWAYS)
    assert phone.js(small_targets()) == []  # the band's name, Their songs, the line's name and Get it, Request
    assert phone.js(f"document.querySelector('{MEANT_LINE}').getBoundingClientRect().height") <= 2 * 44 + 12


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("width", [320, 390])
def test_the_miss_and_a_typos_band_fit_a_phone_and_read_in_light_and_dark(cfg, live, tmp_path, width, dark):
    base, _, _ = live
    sites(cfg, ug=SKYNYRD)
    read_to(cfg, ("_num", "a", "b", "c"))
    blocking(cfg, "musescore")
    phone = driven(tmp_path, width=width, height=844, mobile=True)
    try:
        if dark:
            phone.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        phone.open(base)
        search(phone, "lynrd")
        assert phone.wait(f"{answer_to('lynrd')} && !!document.querySelector('{NOTHING}') && "
                          "!!document.querySelector('#results section.meant')")
        assert phone.js(NO_SIDEWAYS)
        assert phone.js(small_targets()) == []  # the band's name, Their songs, Request, the chevron: a thumb's each
        phone.click(f"{NOTHING} .line-more")
        phone.click(f"{NOTHING} details.why-unseen > summary")
        assert phone.wait(f"document.querySelector('{NOTHING} details.why-unseen').open")
        assert phone.js(NO_SIDEWAYS) and phone.js(small_targets()) == []  # Ask LaCuerda, the fold's summary too
        reads = phone.js(READS)
        weak = {name: value for name, value in reads.items() if name != "box" and (value is None or value < 4.5)}
        assert weak == {}, reads
        assert (reads["box"] < 0.05) if dark else (reads["box"] > 0.8), reads  # its own mode: no white box at night
    finally:
        phone.close()


# How the row of marks under the box sits on a phone: each mark whole, within the page's 16 px gutters, none over
# another, and on how many lines.
ROW_FITS = """(() => {
  const items = [...document.querySelectorAll('#bar-counts > li')];
  const marks = items.map((c) => c.getBoundingClientRect());
  const apart = (a, b) => a.right <= b.left + 0.5 || b.right <= a.left + 0.5 || a.bottom <= b.top + 0.5 ||
    b.bottom <= a.top + 0.5;
  return { n: marks.length, inside: marks.every((r) => r.left >= 15.5 && r.right <= innerWidth - 15.5),
    apart: marks.every((a, i) => marks.every((b, j) => i === j || apart(a, b))),
    whole: items.every((c) => c.scrollWidth <= c.clientWidth + 1),
    lines: new Set(marks.map((r) => Math.round(r.top))).size };
})()"""
# What each mark's count (or "off") and letters say against what is behind them: WCAG's ratio, as READS has it.
COUNT_READS = READS.split("  const read = {};")[0] + """  return [...document.querySelectorAll('#bar-counts > li')]
    .flatMap((c) => [...c.querySelectorAll('.count-n, .count-off, span.source')].map((n) => [c.dataset.source + ' ' +
      n.className, ratio(n)]));
})()"""


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("where", ["library", "lookup"])
def test_the_row_of_marks_wraps_cleanly_on_a_phone_and_reads_in_light_and_dark(cfg, live, tmp_path, where, dark):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    read_to(cfg, ("_num", "a", "b", "c"))
    blocking(cfg, "musescore")
    game_and_harp_indexes(cfg)
    library(cfg, ("Hollow Knight", "Resting Grounds"))
    phone = driven(tmp_path, width=390, height=844, mobile=True)
    try:
        if dark:
            phone.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        if where == "library":
            phone.open(base)
            search(phone, "hollow knight")
            assert phone.wait(f"{answer_to('hollow knight')} && {COUNTS_SHOWN}")
        else:
            phone.open(base + "lookup?q=hollow%20knight")
            assert phone.wait(f"{HITS} >= 1 && {COUNTS_SHOWN}")
        assert phone.js(NO_SIDEWAYS)
        fits = phone.js(ROW_FITS)
        assert fits["n"] == 7 and fits["inside"] and fits["apart"] and fits["whole"] and fits["lines"] <= 2, fits
        weak = [(what, ratio) for what, ratio in phone.js(COUNT_READS) if ratio < 4.5]
        assert weak == [], weak
        assert phone.js(small_targets()) == []  # a mark is no control: nothing here to tap
    finally:
        phone.close()


FOOTER = "(() => { const f = document.querySelector('.footer'); return f.getClientRects().length ? " \
         "Math.round(f.getBoundingClientRect().top) : null; })()"


def test_a_search_opened_from_the_address_moves_nothing_when_its_answer_comes(cfg, live, phone):
    base, _, _ = live
    sites(cfg, **WONDERWALL)
    library(cfg, ("Oasis", "Wonderwall"))
    phone.open(base + "#q=wonderwall&all=1")
    before = phone.js(FOOTER)  # the page as first drawn, before the sites' answer
    assert phone.wait(f"{HITS} >= 2 && document.querySelector('.footer').getClientRects().length > 0")
    after = phone.js(FOOTER)
    # What follows the answer waits for it: shown at once, it would jump down when the answer came.
    assert before is None or before == after, (before, after)


@pytest.mark.parametrize("size,dark", [((1280, 800), False), ((1280, 800), True), ((390, 844), True)])
def test_the_results_read_in_light_and_dark_and_line_up_with_your_songs(cfg, live, tmp_path, size, dark):
    # In dark mode as in light, the results' groups have the list's look; on a laptop a site's line has its
    # columns where your songs' lines have theirs.
    base, _, _ = live
    sites(cfg, ug=[("eagles", "hotel-california", 5), ("eagles", "take-it-easy", 2)])
    library(cfg, ("Eagles", "Hotel California"))
    page = driven(tmp_path, width=size[0], height=size[1], mobile=size[0] < 500)
    try:
        if dark:
            page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        page.open(base)
        search(page, "eagles")
        assert page.wait(f"{HITS} >= 1")
        colours = page.js("(() => { const s = (q) => getComputedStyle(document.querySelector(q)); return ["
                          "s('body').backgroundColor, s('#results .groups').backgroundColor, "
                          "s('#results .hit h3').color]; })()")
        assert colours[0] != colours[1] and colours[1] != colours[2], colours
        assert (sum(int(n) for n in colours[1][4:-1].split(",")[:3]) > 384) is not dark, colours  # its own mode
        if size[0] > 1000:  # your song's line and the site's: the same columns
            cols = page.js("(() => { const at = (q) => document.querySelector(q).getBoundingClientRect(); return "
                           "[at('#results .line[data-id] .line-action').right, at('#results .hit .line-action').right,"
                           " at('#results .line[data-id] .line-more').left, at('#results .hit .line-more').left];"
                           " })()")
            assert abs(cols[0] - cols[1]) < 1 and abs(cols[2] - cols[3]) < 1, cols
        assert page.js(NO_SIDEWAYS)
    finally:
        page.close()


# --- an artist's name searches for them -------------------------------------------------------------------------

C_TANGANA = [("c-tangana", "los-tontos", 3), ("c-tangana", "tu-me-dejaste-de-querer", 5),
             ("c-tangana", "demasiadas-mujeres", 2), ("kase-o", "esto-no-para", 2)]
FIRST_GROUP = "document.querySelector('#results section.artist .artist-title').textContent"


def test_an_artists_name_in_the_results_searches_for_them_and_back_brings_the_query_again(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=C_TANGANA)
    browser.open(base)
    search(browser, "los tontos")
    assert browser.wait(same(LINES, [["C Tangana", [["Los Tontos", "ug"]]]])), browser.js(LINES)
    name = "#results section.artist h2 button.artist-search"
    assert browser.js(f"document.querySelector({json.dumps(name)}).textContent") == "C Tangana"
    browser.click(name)
    # The box says their name, the search runs as typing it would: their group first, every song of theirs in it.
    assert browser.wait("document.getElementById('found').dataset.query === 'C Tangana'")
    assert browser.js("document.getElementById('q').value") == "C Tangana"
    assert browser.wait(f"{FIRST_GROUP}.startsWith('C Tangana')"), browser.js(GROUPS)
    assert sorted(t for t, _ in browser.js(LINES)[0][1]) == ["Demasiadas Mujeres", "Los Tontos",
                                                             "Tu Me Dejaste De Querer"], browser.js(LINES)
    assert browser.js("document.activeElement.id") == "q"
    assert asked.queries()[-1] == "C Tangana" and queue.snapshot() == []  # the indexes alone: nothing looked up
    # Back: the query before it, and its answer.
    browser.js("history.back()")
    assert browser.wait("document.getElementById('q').value === 'los tontos'")
    assert browser.wait("document.getElementById('found').dataset.query === 'los tontos'")
    assert browser.wait(same(LINES, [["C Tangana", [["Los Tontos", "ug"]]]])), browser.js(LINES)
    assert queue.snapshot() == []


def test_an_artists_name_in_your_list_searches_for_them_and_its_funnel_shows_their_songs_alone(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=C_TANGANA)
    library(cfg, ("C Tangana", "Demasiadas Mujeres"), ("Radiohead", "Creep"))
    browser.open(base)
    head = "#list section.artist h2"  # C Tangana's, first
    assert browser.js(f"document.querySelector('{head} .artist-name').textContent") == "C Tangana"
    assert browser.js(f"document.querySelector('{head} .artist-only').getAttribute('aria-label')") == \
        "Only C Tangana's songs"
    browser.click(f"{head} button.artist-search")
    assert browser.wait("document.getElementById('found').dataset.query === 'C Tangana'")
    assert browser.js("document.getElementById('q').value") == "C Tangana"
    assert browser.wait(f"{FIRST_GROUP} === 'C Tangana · you have 1 · UG 3'"), browser.js(GROUPS)
    assert browser.js(LINES)[0][1][0] == ["Demasiadas Mujeres", "yours"]
    assert browser.js("document.activeElement.id") == "q" and queue.snapshot() == []
    # Escape: your songs again; there the funnel shows theirs alone, as the name did before.
    browser.press("Escape")
    assert browser.wait("document.getElementById('results').hidden")
    browser.click("#list section.artist h2 button.artist-only")
    assert browser.wait(f"JSON.stringify({GRID}) === '[\"Demasiadas Mujeres\"]'"), browser.js(GRID)
    assert browser.js("document.getElementById('q').value") == ""
    assert browser.js("document.getElementById('artist').hidden") is False
    assert asked.queries() == ["C Tangana"] and queue.snapshot() == []
    # Sorted by title, a line names its artist: the name searches there too, the funnel beside it.
    browser.js("document.getElementById('artist').click()")
    browser.js("(() => { const s = document.getElementById('sort'); s.value = 'title';"
               " s.dispatchEvent(new Event('change')); })()")
    by = "#list article.line .line-by.artist-pair"
    assert browser.wait(f"document.querySelectorAll('{by}').length === 2")
    assert browser.js(f"[...document.querySelector('{by}').children].map((b) => b.className)") == [
        "artist artist-search", "artist-only"]


def test_back_after_an_artists_name_and_its_funnel_brings_the_whole_address_again(cfg, live, browser):
    base, queue, asked = live
    sites(cfg, ug=C_TANGANA)
    library(cfg, ("C Tangana", "Demasiadas Mujeres"), ("Radiohead", "Creep"))
    browser.open(base)
    browser.click("#list section.artist h2 button.artist-search")  # C Tangana: the search for them
    assert browser.wait("document.getElementById('found').dataset.query === 'C Tangana'")
    funnel = "#results section.artist h2 button.artist-only"
    assert browser.wait(f"document.querySelector({json.dumps(funnel)}) !== null")
    browser.click(funnel)  # their songs of yours alone, the search left
    assert browser.wait(f"JSON.stringify({GRID}) === '[\"Demasiadas Mujeres\"]'"), browser.js(GRID)
    assert "artist=c-tangana" in browser.js("location.hash")
    # Back: the page as it was before the name, every song and no chip, as its address says.
    browser.js("history.back()")
    assert browser.wait("!location.hash.includes('artist=')")
    assert browser.wait("document.getElementById('artist').hidden === true")
    assert browser.wait(f"JSON.stringify({GRID}) === '[\"Demasiadas Mujeres\",\"Creep\"]'"), browser.js(GRID)
    assert browser.js("document.getElementById('q').value") == ""
    assert browser.js("document.getElementById('results').hidden") is True
    # Forward: the funnel's step again, its chip on.
    browser.js("history.forward()")
    assert browser.wait("document.getElementById('artist').hidden === false")
    assert browser.wait(f"JSON.stringify({GRID}) === '[\"Demasiadas Mujeres\"]'"), browser.js(GRID)
    assert queue.snapshot() == []


# --- a sheet's artist searches for them too -----------------------------------------------------------------------

# Where a finger may press the artist's name under a sheet's title: its box, and what the screen has at its top and
# bottom edges, a few pixels in (the name's own line is shorter than a thumb).
ARTIST_TARGET = """(() => {
  const a = document.querySelector(".head .artist a");
  const r = a.getBoundingClientRect();
  const at = (y) => document.elementFromPoint(r.x + r.width / 2, y) === a;
  return { width: r.width, height: r.height, x: r.x + r.width / 2, top: r.top + 3,
           edges: at(r.top + 3) && at(r.bottom - 3) };
})()"""


def test_a_sheets_artist_searches_for_them_on_the_library_page_and_back_returns_to_the_sheet(cfg, live, phone):
    # The served viewer, in its sandbox: a finger on the artist's name under the title, even at the edge of its thumb's
    # target, opens the library page searching for them as their name there does, which asks no site (their group
    # first, your song of theirs and every index's songs of theirs); Back is the sheet again, as it was.
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCSong
    from helpers.rendered import rendered_song

    base, queue, asked = live
    sites(cfg, ug=C_TANGANA, gtptabs=["https://gtptabs.com/tabs/15/c-tangana/los-tontos.html"])
    conn = db.connect(cfg.db_path)
    try:
        li.store_songs(conn, "c_tangana", "C Tangana", [LCSong("nunca_estoy", "Nunca Estoy", "R", (1,))])
        conn.commit()
        rendered_song(conn, cfg, "C Tangana", "Demasiadas Mujeres")
    finally:
        conn.close()
    phone.open(base + quote("C Tangana/Demasiadas Mujeres/sheet.html") + "#t=2")
    assert phone.wait("document.documentElement.dataset.ready === '1'")
    assert phone.js("document.querySelector('.head .artist').textContent") == "C Tangana"
    assert phone.js(NO_SIDEWAYS)
    target = phone.js(ARTIST_TARGET)
    assert target["width"] >= 44 and target["height"] >= 44 and target["edges"], target
    phone.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": target["x"], "y": target["top"]}])
    phone.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    assert phone.wait("location.pathname === '/index.html' && document.readyState === 'complete'")
    assert phone.wait("document.getElementById('found').dataset.query === 'C Tangana'")
    assert phone.js("document.getElementById('q').value") == "C Tangana"
    assert phone.js(GROUPS)[0] == "C Tangana · you have 1 · UG 3 · LaCuerda 1 · Guitar Pro 1", phone.js(GROUPS)
    assert phone.js(LINES)[0] == ["C Tangana", [
        ["Demasiadas Mujeres", "yours"], ["Tu Me Dejaste De Querer", "ug"], ["Los Tontos", "ug+gtptabs"],
        ["Nunca Estoy", "lacuerda"]]], phone.js(LINES)
    assert asked.queries() == ["C Tangana"] and queue.snapshot() == []  # the indexes alone: nothing looked up
    assert phone.js("location.hash") == "#q=C+Tangana&all=1"  # the page's own address for it: a reload keeps it
    assert phone.js(NO_SIDEWAYS)
    phone.js("history.back()")
    assert phone.wait("location.pathname.endsWith('/sheet.html') && document.documentElement.dataset.ready === '1'")
    assert phone.js("location.hash") == "#t=2"
    assert phone.js("document.getElementById('key-now').textContent").startswith("A")  # still two semitones up
