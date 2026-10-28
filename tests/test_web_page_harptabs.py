"""harptabs.com's offline index in the library page's bar and on the lookup page, in a real browser.

A real ``caracole serve`` (as test_web_page_search.py's ``live``) serves the page, whose bar searches as you
type and puts harptabs.com's artists and songs in the artist groups with the other sites', a song a line, its
mark and the Harmonica badge; its queue runs ``FakeCaracole``: ``caracole get`` as ``FakeGet`` does it, and
``caracole harptabs --artist`` as the index would take the artist's page in, with no request. harptabs.com's
index holds its captured sitemap, Billy Joel's captured artist page (7 of his 98 tabs, of 4 songs) and the
Beatles', and not Ritchie Valens's.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_web_page_search import GROUPS, LINES, FakeGet, posted, sites

from caracole import db
from caracole.harptabs import ArtistPage, ListedTab
from caracole.harptabs_index import store_artist_page
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

pytestmark = CHROMIUM_MARKS

HT = "https://www.harptabs.com/"
VALENS = ArtistPage("Ritchie Valens", 3, (ListedTab(89, "tab/89/la-bamba", "La Bamba", key="C", views=57_000),
                                          ListedTab(90, "tab/90/donna", "Donna (intro)", key="G", views=2_000)))


class FakeCaracole(FakeGet):
    """The queue's caracole: ``get`` as FakeGet does it; ``harptabs --artist`` takes Ritchie Valens's page into the
    index, as the command does, with no request."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.ran: list[tuple[str, ...]] = []
        self.fails = False  # ``harptabs --artist`` ends in an error, as a bug would, and reads nothing

    def __call__(self, args, emit):
        self.ran.append(tuple(args))
        if args[0] == "harptabs" and self.fails:
            emit("error: harptabs.com's page couldn't be read.")
            return 1
        if args[0] == "harptabs":
            time.sleep(0.3)  # long enough for the page to say it reads
            conn = db.connect(self.cfg.db_path)
            try:
                store_artist_page(conn, "artist/7829/ritchie-valens", VALENS, datetime.now(UTC))
                conn.commit()
            finally:
                conn.close()
            emit("Read: harptabs.com's page of Ritchie Valens lists their 2 tabs, in the index now.")
            return 0
        return super().__call__(args, emit)


@pytest.fixture
def live(cfg):
    runner = FakeCaracole(cfg)
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", searches_lacuerda=False)
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", queue, runner
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


def harptabs(cfg):
    """harptabs.com's index, as test_search.py makes it."""
    from test_search import harptabs_index

    conn = db.connect(cfg.db_path)
    harptabs_index(conn)
    conn.commit()
    conn.close()


HT_ROWS = "[...document.querySelectorAll('#results .hit[data-source=\"harptabs\"]')]"
TITLES = f"{HT_ROWS}.map((h) => h.querySelector('h3').textContent)"
LOOKUP_TITLES = f"{HT_ROWS}.map((h) => h.querySelector('.row-title').textContent)"


def search(browser, base, query):
    """The library page, ``query`` typed into its bar: it searches as you type, no Enter needed."""
    browser.open(base)
    browser.js("document.getElementById('q').focus()")
    browser.type(query)


def test_billy_joel_is_harptabs_coms_artist_with_his_songs_whose_get_it_keeps_that_tab(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    harptabs(cfg)
    search(browser, base, "billy joel")
    assert browser.wait(f"{HT_ROWS}.length === 3")
    # His group: the tabs his page says he has, and his most viewed songs, a line a song with harptabs.com's mark.
    assert browser.js(GROUPS) == ["billy joel · Harmonica 98"]
    assert browser.js(TITLES) == ["piano man", "Vienna!", "She's Always a Woman"]
    assert browser.js(f"{HT_ROWS}[0].querySelector('.line-sources .source').dataset.source") == "harptabs"
    assert browser.js(f"{HT_ROWS}.map((h) => h.querySelector('.badge.instrument').textContent)") == ["Harmonica"] * 3
    assert "harmonica tab ×4" in browser.js(f"{HT_ROWS}[0].textContent")
    assert "on harptabs.com" in browser.js("document.getElementById('bar-status').textContent")
    assert queue.snapshot() == []
    # "+ 1 more": the song of his the index holds that the row left out, from /api/artist, asking no site.
    assert browser.js("document.querySelector('#results .more-by').textContent") == "+ 1 more by billy joel on harptabs.com"
    browser.click("#results .more-by")
    assert browser.wait(f"{HT_ROWS}.length === 4")
    assert browser.js(TITLES)[-1] == "New York State Of Mind" and queue.snapshot() == []
    # Get it: the song looked up now, keeping that harmonica tab.
    browser.js(f"{HT_ROWS}.find((h) => h.querySelector('h3').textContent === 'Vienna!')"
               ".querySelector('.line-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--harptabs={HT}tab/8767/vienna") and args[-2:] == ("billy joel", "Vienna!")
    assert browser.wait("!!document.querySelector('#results .progress')")


def test_a_song_two_sites_have_is_one_line_its_harmonica_tabs_under_its_dots(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("billy-joel", "piano-man", 5)])
    harptabs(cfg)
    search(browser, base, "billy joel piano man")
    assert browser.wait("document.getElementById('found').dataset.query === 'billy joel piano man'")
    assert browser.wait(f"{HT_ROWS}.length >= 1")
    [group] = [g for g in browser.js(LINES) if g[0].lower() == "billy joel"]
    assert group[1][0] == ["Piano Man", "ug+harptabs"]  # Ultimate Guitar's names first, both marks
    line = "[...document.querySelectorAll('#results article.line')].find((a) => a.dataset.hit === 'billy-joel/piano-man')"
    assert browser.js(f"{line}.querySelector('.badge.instrument').textContent") == "Harmonica"
    browser.js(f"{line}.querySelector('.line-more').click()")
    tabs = browser.js(f"[...{line}.querySelectorAll('.line-panel .versions button')].map((b) => b.textContent)")
    assert [t.split(" · ")[0] for t in tabs[-4:]] == ["piano man", "Piano Man (C Harmonica)",
                                                      "((((Piano Man (Harmonica Intro)", "Piano Man (Harp Intro)"]
    browser.js(f"[...{line}.querySelectorAll('.line-panel .versions button')]"
               ".find((b) => b.textContent.startsWith('Piano Man (C Harmonica)')).click()")
    args = posted(queue)
    assert f"--harptabs={HT}tab/23862/piano-man-c-harmonica" in args and args[-2:] == ("Billy Joel", "Piano Man")


def test_an_artist_whose_page_caracole_never_read_is_read_on_asking_then_listed_in_their_group(cfg, live, browser):
    base, queue, runner = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    harptabs(cfg)
    search(browser, base, "ritchie valens")
    assert browser.wait("!!document.querySelector('#results section.artist .read-page button')")
    mark = browser.js("(() => { const c = document.querySelector('#results .looked-line li[data-state=partial]'); "
                      "return [c.dataset.source, c.firstElementChild.getAttribute('aria-label'), c.title]; })()")
    assert mark[:2] == ["harptabs", "harptabs.com: 2 of 3 artists"] and "still being read" in mark[2]
    assert queue.snapshot() == []  # the search asks nothing: reading their page is a button of its own
    browser.click("#results .read-page button")
    assert browser.wait(f"{TITLES}.length === 2", timeout=20)
    assert ("harptabs", "--artist=artist/7829/ritchie-valens") in runner.ran
    assert browser.js(TITLES) == ["La Bamba", "Donna"]
    assert browser.js("document.querySelector('#results .read-page')") is None


def test_an_artist_whose_page_was_read_listing_no_tab_is_never_offered_to_read_it(cfg, live, browser):
    # Their page read, and listing none: no tab in the index, yet read, as /api/artist says. Neither page says it
    # wasn't, nor offers to read it again.
    base, queue, runner = live
    harptabs(cfg)
    conn = db.connect(cfg.db_path)
    store_artist_page(conn, "artist/7829/ritchie-valens", ArtistPage("Ritchie Valens", 0), datetime.now(UTC))
    conn.commit()
    conn.close()
    browser.open(base + "lookup?q=ritchie%20valens")
    assert browser.wait(f"{HT_ROWS}.length === 1")
    assert "page not read yet" not in browser.js(f"{HT_ROWS}[0].textContent")
    search(browser, base, "ritchie valens")
    assert browser.wait("document.getElementById('bar-status').textContent.includes('on harptabs.com')")  # answered
    assert browser.js("document.querySelector('#results .read-page')") is None


def test_a_read_that_left_no_songs_names_harptabs_com_never_lacuerda(cfg, live, browser):
    # A read that ended in an error, and left no songs to list: what the line under the offer says names the site it
    # read, as the library page's and the lookup page's.
    base, queue, runner = live
    runner.fails = True
    harptabs(cfg)
    search(browser, base, "ritchie valens")
    assert browser.wait("!!document.querySelector('#results section.artist .read-page button')")
    browser.click("#results .read-page button")
    assert browser.wait("!!document.querySelector('#results .read-outcome')", timeout=20)
    said = browser.js("document.querySelector('#results .read-outcome').textContent")
    assert "LaCuerda" not in said and said.startswith("harptabs.com "), said
    browser.open(base + "lookup?q=ritchie%20valens")
    assert browser.wait(f"{HT_ROWS}.length === 1")
    browser.click("#results .hit[data-slug='artist/7829/ritchie-valens'] .row-action button")
    assert browser.wait("!!document.querySelector('#results .read-page button')")
    browser.click("#results .read-page button")
    assert browser.wait("!!document.querySelector('#results .read-outcome')", timeout=20)
    said = browser.js("document.querySelector('#results .read-outcome').textContent")
    assert "LaCuerda" not in said and said.startswith("harptabs.com "), said


def test_the_lookup_page_lists_harptabs_com_last_and_its_artists_songs(cfg, live, browser):
    base, queue, runner = live
    sites(cfg, ug=[("billy-joel", "uptown-girl", 2)])
    harptabs(cfg)
    browser.open(base + "lookup?q=billy%20joel")
    assert browser.wait("[...document.querySelectorAll('#results .group')].some((g) => g.textContent === "
                        "'On harptabs.com')")
    groups = browser.js("[...document.querySelectorAll('#results .group')].map((g) => g.textContent)")
    assert groups[-1] == "On harptabs.com", groups
    browser.click("#results .hit[data-slug='artist/1178/billy-joel'] .row-action button")
    assert browser.wait(f"{LOOKUP_TITLES}.length === 4")
    browser.js(f"{HT_ROWS}.find((h) => h.querySelector('.row-title').textContent === 'Vienna!')"
               ".querySelector('.row-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--harptabs={HT}tab/8767/vienna") and args[-2:] == ("billy joel", "Vienna!")


def test_the_lookup_page_reads_an_artists_page_on_asking(cfg, live, browser):
    base, queue, runner = live
    harptabs(cfg)
    browser.open(base + "lookup?q=ritchie%20valens")
    assert browser.wait(f"{HT_ROWS}.length === 1")
    browser.click("#results .hit[data-slug='artist/7829/ritchie-valens'] .row-action button")
    assert browser.wait("!!document.querySelector('#results .read-page button')")
    browser.click("#results .read-page button")
    assert browser.wait(f"{LOOKUP_TITLES}.length === 2", timeout=20)
    assert ("harptabs", "--artist=artist/7829/ritchie-valens") in runner.ran
