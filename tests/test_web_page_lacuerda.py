"""LaCuerda's offline index in the library page's bar and on the lookup page, in a real browser.

A real ``caracole serve`` (as test_web_page_search.py's ``live``) serves the page, whose bar searches as you
type and puts LaCuerda's artists and songs in the artist groups with the other sites'; its queue runs
``FakeCaracole``: ``caracole get`` as ``FakeGet`` does it, and ``caracole lacuerda --artist`` as
the index would take the artist's page in, with no request. LaCuerda's index holds Estopa, whose
page caracole has read, and Joaquín Sabina, whose page it hasn't; a name under a letter its
listings aren't read to yet (Bunbury's B) is read by name, and Caifanes has no page. The file on
disk, which can ask nothing, names the line to run, which searches LaCuerda's index too, and a
song picked on LaCuerda says on its card that tonight's run gets that sheet.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.lacuerda_site import artist_page
from test_web_page_search import GROUPS, FakeGet, answer_to, library, posted, sites

from caracole import db
from caracole import lacuerda_index as li
from caracole.db import kv_set_json
from caracole.lacuerda import LCArtist
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

pytestmark = CHROMIUM_MARKS

LC = "https://acordes.lacuerda.net/"
SABINA = artist_page("Joaquín Sabina", "joaquin_sabina", ("y_nos_dieron_las_diez", "Y Nos Dieron Las Diez", "R-1"),
                     ("19_dias_y_500_noches", "19 Días y 500 Noches", "RT-12"))
BUNBURY = artist_page("Bunbury", "bunbury", ("lady_blue", "Lady Blue", "R-1"), ("infinito", "Infinito", "RT-2"))


class FakeCaracole(FakeGet):
    """The queue's caracole: ``get`` as FakeGet does it; ``lacuerda --artist`` takes Joaquín Sabina's page into the
    index, as the command does, with no request."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.ran: list[tuple[str, ...]] = []

    def __call__(self, args, emit):
        self.ran.append(tuple(args))
        if args[0] == "lacuerda":
            time.sleep(0.3)  # long enough for the page to say it reads
            if args[1] == "--artist=caifanes":  # the page LaCuerda doesn't have
                emit("Not found: LaCuerda has no artist page for caifanes.")
                return 0
            conn = db.connect(self.cfg.db_path)
            try:
                if args[1] == "--artist=joaquin_sabina":
                    li.store_artist_page(conn, "joaquin_sabina", SABINA)
                else:  # a page read by name: Bunbury's, whose B LaCuerda's listings haven't reached
                    li.store_artist_page(conn, "bunbury", BUNBURY)
                conn.commit()
            finally:
                conn.close()
            emit("Read: LaCuerda's page lists 2 songs, in the index now.")
            return 0
        if args[0] == "add":
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


def lacuerda(cfg, *, complete=True):
    """LaCuerda's index: Estopa (their page read) and Joaquín Sabina (not yet), E and J read whole."""
    conn = db.connect(cfg.db_path)
    li.store_artists(conn, "tabs/e/index0.html", [LCArtist("estopa", "Estopa", 159)])
    li.store_artists(conn, "tabs/j/index0.html", [LCArtist("joaquin_sabina", "Joaquín Sabina", 241)])
    li.store_artist_page(conn, "estopa", artist_page(
        "Estopa", "estopa", ("como_camaron", "Como Camarón", "RRT-213"), ("tu_calorro", "Tu Calorro", "R-1")))
    kv_set_json(conn, li.PAGES_KEY, {f"tabs/{x}/index0.html": {"pages": ["index0.html"]} for x in "ej"})
    if complete:
        db.kv_set(conn, li.COMPLETE_KEY, "2026-10-19T03:00:00Z")
    conn.commit()
    conn.close()


LC_ROWS = "[...document.querySelectorAll('#results .hit[data-source=\"lacuerda\"]')]"
TITLES = f"{LC_ROWS}.map((h) => h.querySelector('h3').textContent)"
# The lookup page's rows, which stay rows.
LOOKUP_TITLES = f"{LC_ROWS}.map((h) => h.querySelector('.row-title').textContent)"


def search(browser, base, query):
    """The library page, ``query`` typed into its bar: it searches as you type, no Enter needed."""
    browser.open(base)
    browser.js("document.getElementById('q').focus()")
    browser.type(query)


def test_estopa_is_lacuerdas_artist_with_their_songs_whose_get_it_keeps_that_sheet(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg)
    search(browser, base, "estopa")
    assert browser.wait(f"{answer_to('estopa')} && {LC_ROWS}.length === 2")
    # Their group: how many songs LaCuerda lists, and the songs the index holds of theirs, the most popular first.
    assert browser.js(GROUPS) == ["Estopa · LaCuerda 159"]
    assert sorted(browser.js(TITLES)) == ["Como Camarón", "Tu Calorro"]
    assert browser.js(f"{LC_ROWS}[0].querySelector('.line-sources .source').dataset.source") == "lacuerda"
    assert "on LaCuerda" in browser.js("document.getElementById('bar-status').textContent")
    assert browser.js("document.querySelector('#results .more-by, #results .read-page')") is None  # all it holds
    assert queue.snapshot() == []
    # Get it: the song looked up now, keeping that LaCuerda sheet.
    browser.js(f"{LC_ROWS}.find((h) => h.querySelector('h3').textContent === 'Como Camarón')"
               ".querySelector('.line-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--lacuerda={LC}estopa/como_camaron")
    assert args[-2:] == ("Estopa", "Como Camarón")
    assert browser.wait("!!document.querySelector('#results .progress')")
    assert browser.wait("document.querySelector('#results .progress').dataset.tone === 'ready'", timeout=20)


def test_an_artists_header_counts_their_songs_on_every_site_while_searching(cfg, live, browser):
    # "Estopa · UG 2 · LaCuerda 159 · Guitar Pro 2": what each index lists of theirs, gtptabs.com's uploads of a
    # title one song.
    base, queue, _ = live
    gtp = "https://gtptabs.com/tabs/31/estopa/"
    sites(cfg, ug=[("estopa", "como-camaron", 3), ("estopa", "tu-calorro", 1)],
          gtptabs=[gtp + "como-camaron.html", gtp + "como-camaron-2.html", gtp + "la-raja-de-tu-falda.html"])
    lacuerda(cfg)
    search(browser, base, "estopa")
    assert browser.wait("document.getElementById('found').dataset.query === 'estopa'")
    assert browser.js(GROUPS) == ["Estopa · UG 2 · LaCuerda 159 · Guitar Pro 2"]
    assert queue.snapshot() == []


def test_an_artist_whose_page_caracole_never_read_is_read_on_asking_then_listed_in_their_group(cfg, live, browser):
    base, queue, runner = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg, complete=False)
    search(browser, base, "joaquin sabina")
    assert browser.wait(f"{answer_to('joaquin sabina')} && "
                        "!!document.querySelector('#results section.artist .read-page button')")
    assert browser.js(GROUPS) == ["Joaquín Sabina · LaCuerda 241"]
    mark = browser.js("(() => { const c = document.querySelector('#bar-counts li[data-state=partial]'); "
                      "return [c.dataset.source, c.firstElementChild.getAttribute('aria-label'), c.title]; })()")
    assert mark[:2] == ["lacuerda", "1 on LaCuerda: index in part, E, J only"] and "still being read" in mark[2]
    assert "E, J read whole" in mark[2]
    assert "241 songs" in browser.js("document.querySelector('#results .read-page').textContent")
    assert queue.snapshot() == []  # the search asks nothing: reading their page is a button of its own
    browser.click("#results .read-page button")
    assert browser.wait(f"{TITLES}.length === 2", timeout=20)
    assert ("lacuerda", "--artist=joaquin_sabina") in runner.ran
    assert sorted(browser.js(TITLES)) == ["19 Días y 500 Noches", "Y Nos Dieron Las Diez"]
    assert browser.js(GROUPS) == ["Joaquín Sabina · LaCuerda 241"]  # in their group, the offer gone
    assert browser.js("document.querySelector('#results .read-page')") is None
    assert "2 songs on LaCuerda" in browser.js("document.getElementById('bar-status').textContent")


def test_a_close_spelling_of_a_lacuerda_artist_opens_their_group_with_the_offer_to_read_their_page(cfg, live, browser):
    base, queue, runner = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg)
    search(browser, base, "sabinna")
    assert browser.wait(f"{answer_to('sabinna')} && !!document.querySelector('#results section.meant')")
    assert browser.js(GROUPS) == ["Did you mean Joaquín Sabina · 241 songs on LaCuerda"]
    assert browser.js("document.querySelector('#results section.meant .their-songs').textContent") == (
        "Their 241 songs on LaCuerda›")
    browser.click("#results section.meant .their-songs")
    assert browser.wait("!!document.querySelector('#results section.artist .read-page button')")
    assert browser.js(GROUPS) == ["Did you mean Joaquín Sabina · LaCuerda 241"]
    assert browser.js("document.activeElement.matches('#results section.artist')")
    assert queue.snapshot() == [] and runner.ran == []  # their page is read only once asked to


def test_a_name_under_a_letter_lacuerda_hasnt_listed_yet_is_read_on_asking_then_listed(cfg, live, browser):
    # The owner's "estopa", with LaCuerda's listings read as far as E and J only: the index can't tell, the page can.
    base, queue, runner = live
    sites(cfg, ug=[("radiohead", "creep", 4)], gtptabs=["https://gtptabs.com/tabs/2/bunbury/el-extranjero.html"])
    lacuerda(cfg, complete=False)
    search(browser, base, "bunbury")
    ask = "#results .notes-line .ask-lacuerda"  # gtptabs.com has a song of theirs: under the results
    assert browser.wait(f"{answer_to('bunbury')} && !!document.querySelector('{ask}')")
    offer = browser.js(f"document.querySelector('{ask}').title")
    assert offer.startswith("LaCuerda's list doesn't reach B yet") and "“bunbury”" in offer
    assert browser.js(f"document.querySelector('{ask}').textContent") == "Ask LaCuerda for “bunbury” (1 request)"
    assert queue.snapshot() == []  # the search asked nothing: reading the page is the button's
    browser.click(ask)
    assert browser.wait(f"{TITLES}.length === 2", timeout=20)
    assert ("lacuerda", "--artist=bunbury") in runner.ran
    assert sorted(browser.js(TITLES)) == ["Infinito", "Lady Blue"]
    header = browser.js(GROUPS)[0]  # a group of their own, first, which counts their songs on gtptabs.com too
    assert header.startswith("Bunbury · LaCuerda") and header.endswith(" · Guitar Pro 1"), header
    assert browser.js("document.querySelector('#results .ask-lacuerda')") is None
    # A name LaCuerda has no page for, which nothing else has either: Ask LaCuerda, under the chevron of what found
    # nothing, says what LaCuerda answered, there, and rests.
    search(browser, base, "caifanes")
    ask = "#results .nothing .ask-lacuerda"
    assert browser.wait(f"{answer_to('caifanes')} && !!document.querySelector('{ask}')")
    browser.click("#results .nothing .line-more")
    browser.click(ask)
    assert browser.wait("!!document.querySelector('#results .nothing .read-outcome')", timeout=20)
    said = browser.js("document.querySelector('#results .read-outcome').textContent")
    assert said.startswith("Not found: LaCuerda has no artist page for caifanes.") and "See what it answered" in said
    assert browser.js(f"document.querySelector('{ask}').disabled")


def test_the_lookup_page_offers_to_read_a_name_lacuerda_hasnt_listed_yet(cfg, live, browser):
    base, queue, runner = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg, complete=False)
    browser.open(base + "lookup?q=bunbury")
    assert browser.wait("!!document.querySelector('#results .nothing .ask-lacuerda')")
    browser.click("#results .nothing .row-more")
    browser.click("#results .nothing .ask-lacuerda")
    assert browser.wait(f"{LOOKUP_TITLES}.length === 2", timeout=20)
    assert ("lacuerda", "--artist=bunbury") in runner.ran


def test_a_lacuerda_song_can_be_added_for_tonights_run_with_its_pick(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg)
    library(cfg, ("Estopa", "Tu Calorro"))
    search(browser, base, "estopa como camaron")
    assert browser.wait(f"{answer_to('estopa como camaron')} && {TITLES}.includes('Como Camarón')")
    row = "#results .hit[data-source='lacuerda'][data-hit$='/como-camaron']"
    assert browser.js(f"document.querySelector(\"{row} .line-facts\").textContent") == "LaCuerda ×3"
    # Your Tu Calorro, which LaCuerda's Estopa lists too, is your own line in their group.
    assert browser.js("[...document.querySelectorAll('#results section.artist .line[data-id] h3')]"
                      ".map((h) => h.textContent)") == ["Tu Calorro"]
    browser.click(f"{row} .line-more")
    browser.click(f"{row} .line-panel .later button")
    assert posted(queue) == ("add", f"--lacuerda={LC}estopa/como_camaron", "--", "Estopa", "Como Camarón")
    assert "Estopa - Como Camarón" in cfg.wanted_file.read_text(encoding="utf-8")


def test_the_lookup_page_lists_lacuerda_after_ultimate_guitar(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("estopa", "la-raja-de-tu-falda", 2)])
    lacuerda(cfg)
    browser.open(base + "lookup?q=estopa")
    assert browser.wait("[...document.querySelectorAll('#results .group')].length >= 2")
    groups = browser.js("[...document.querySelectorAll('#results .group')].map((g) => g.textContent)")
    assert groups.index("On LaCuerda") > groups.index("Artists on Ultimate Guitar"), groups
    browser.click("#results .hit[data-slug='estopa'] .row-action button")
    assert browser.wait(f"{LOOKUP_TITLES}.length === 2")
    browser.js(f"{LC_ROWS}.find((h) => h.querySelector('.row-title').textContent === 'Tu Calorro')"
               ".querySelector('.row-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--lacuerda={LC}estopa/tu_calorro") and args[-2:] == ("Estopa", "Tu Calorro")


def calamaro(cfg):
    """Ultimate Guitar's index knows only Javier Calamaro; LaCuerda's listings have Andrés Calamaro, page unread."""
    sites(cfg, ug=[("javier-calamaro", "amapolas", 3), ("javier-calamaro", "euforia-y-furia", 2)])
    lacuerda(cfg)
    conn = db.connect(cfg.db_path)
    li.store_artists(conn, "tabs/a/index0.html", [LCArtist("andres_calamaro", "Andrés Calamaro", 325)])
    conn.commit()
    conn.close()


def test_lacuerda_comes_first_with_the_artist_it_alone_has_by_that_name(cfg, live, browser):
    # "andres calamaro": Ultimate Guitar's weak rows (Javier Calamaro's) come after LaCuerda's Andrés Calamaro.
    base, _, _ = live
    calamaro(cfg)
    search(browser, base, "andres calamaro")
    assert browser.wait(f"{answer_to('andres calamaro')} && !!document.querySelector('#results section.artist .read-page')")
    assert [g.split(" · ")[0] for g in browser.js(GROUPS)] == ["Andrés Calamaro", "Javier Calamaro"]


def test_enter_on_the_lookup_page_opens_the_artist_lacuerda_alone_has_by_that_name(cfg, live, browser):
    base, queue, _ = live
    calamaro(cfg)
    browser.open(base + "lookup?q=andres%20calamaro")
    assert browser.wait(f"{LC_ROWS}.length === 1")  # the lookup page's artist row
    groups = browser.js("[...document.querySelectorAll('#results .group')].map((g) => g.textContent)")
    assert groups == ["On LaCuerda", "On Ultimate Guitar"], groups
    browser.js("document.getElementById('q').focus()")
    browser.press("Enter")
    assert browser.wait("!!document.querySelector('#results .artist-head h2')")
    assert browser.js("document.querySelector('#results .artist-head h2').textContent") == "Andrés Calamaro"
    assert browser.wait("!!document.querySelector('#results .read-page button')")
    assert queue.snapshot() == []  # Enter asked nothing: reading their page is the button's


def test_lacuerdas_rows_and_the_offer_to_read_a_page_fit_a_phone(cfg, live, tmp_path):
    base, _, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg)
    try:
        phone = Browser(tmp_path / "phone", width=390, height=844, mobile=True)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    try:
        search(phone, base, "joaquin sabina")
        assert phone.wait(f"{answer_to('joaquin sabina')} && "
                          "!!document.querySelector('#results section.artist .read-page button')")
        assert phone.js("document.documentElement.scrollWidth <= innerWidth")
        assert phone.js("document.querySelector('#results .read-page button').getBoundingClientRect().height") >= 44
        # The request form is filled in with the artist LaCuerda alone knows.
        assert phone.wait("document.querySelector('form.request-form [name=artist]').value === 'joaquin sabina'")
    finally:
        phone.close()


def test_the_file_page_names_the_line_that_searches_lacuerda_too(cfg, tmp_path, browser):
    from caracole.library_page import build_library_page, write_library_page
    from caracole.overrides import Overrides
    from conftest import add_song

    conn = db.connect(cfg.db_path)
    add_song(conn, "Radiohead", "Creep")
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), datetime.now(UTC)))
    conn.close()
    browser.open(path.as_uri())
    browser.js("document.getElementById('q').focus()")
    browser.type("estopa")
    browser.press("Enter")  # the file can't search: Enter shows the line that does
    assert browser.wait("!!document.querySelector('#results .file-answer, #list .file-answer, .file-answer')")
    said = browser.js("document.querySelector('.file-answer').textContent")
    assert "LaCuerda" in said and "caracole search 'estopa'" in said
    assert browser.js("performance.getEntriesByType('resource').length") == 0  # the file asks nothing


def test_a_song_picked_on_lacuerda_says_on_its_card_that_tonights_run_gets_that_sheet(cfg, browser):
    # UG has no song of theirs by that name, which is no matter: the card says what comes, not that it's missing.
    from caracole.library_page import build_library_page, write_library_page
    from caracole.overrides import LaCuerdaPick, Overrides
    from caracole.songs import update_song
    from conftest import add_song

    conn = db.connect(cfg.db_path)
    song = add_song(conn, "Andrés Calamaro", "Flaca")
    update_song(conn, song.id, match_decision="not_found")
    picked = Overrides(lacuerda={song.key: LaCuerdaPick("andres_calamaro", "flaca")})
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, picked, datetime.now(UTC)))
    conn.close()
    browser.open(path.as_uri())
    assert browser.wait("!!document.querySelector('.lacuerda-pick')")
    assert browser.js("document.querySelector('.lacuerda-pick').textContent").startswith(
        "Tonight's run gets the sheet you picked on LaCuerda")
    assert browser.js("document.querySelector('.lacuerda-pick a').href") == LC + "andres_calamaro/flaca"
    assert not browser.js("!!document.querySelector('.pick-hint')")  # not "Not in the offline Ultimate Guitar index"
