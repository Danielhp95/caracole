"""LaCuerda's offline index in the library page's bar and on the lookup page, in a real browser.

A real ``caracole serve`` (as test_web_page_search.py's ``live``) serves the page; its queue runs
``FakeCaracole``: ``caracole get`` as ``FakeGet`` does it, and ``caracole lacuerda --artist`` as
the index would take the artist's page in, with no request. LaCuerda's index holds Estopa, whose
page caracole has read, and Joaquín Sabina, whose page it hasn't. The file on disk, which can ask
nothing, names the line to run, which searches LaCuerda's index too.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.lacuerda_site import artist_page
from test_web_page_search import GROUPS, FakeGet, library, posted, sites

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
            conn = db.connect(self.cfg.db_path)
            try:
                li.store_artist_page(conn, "joaquin_sabina", SABINA)
                conn.commit()
            finally:
                conn.close()
            emit("LaCuerda: Joaquín Sabina's page lists 2 songs, in the index now.")
            return 0
        if args[0] == "add":
            return 0
        return super().__call__(args, emit)


@pytest.fixture
def live(cfg):
    runner = FakeCaracole(cfg)
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
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
TITLES = f"{LC_ROWS}.map((h) => h.querySelector('.row-title').textContent)"


def search(browser, base, query):
    browser.open(base)
    browser.js("document.getElementById('q').focus()")
    browser.type(query)
    browser.press("Enter")


def test_estopa_lists_lacuerdas_artist_whose_songs_get_it_keeps(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg)
    search(browser, base, "estopa")
    assert browser.wait(f"{LC_ROWS}.length === 1")
    assert [g.split(" · ")[0] for g in browser.js(GROUPS)] == ["LaCuerda"]
    assert browser.js(f"{LC_ROWS}[0].querySelector('.source').dataset.source") == "lacuerda"  # LaCuerda's mark
    assert browser.js(f"{LC_ROWS}[0].querySelector('.row-sub').textContent").startswith("Artist · Como Camarón")
    assert "on LaCuerda" in browser.js("document.getElementById('bar-status').textContent")
    # Songs: those the index holds of theirs, LaCuerda's most popular first; no request.
    browser.click("#results .hit[data-slug='estopa'] .row-action button")
    assert browser.wait(f"{TITLES}.length === 2")
    assert sorted(browser.js(TITLES)) == ["Como Camarón", "Tu Calorro"]
    assert browser.js("document.querySelector('#results .artist-head h2').textContent") == "Estopa"
    # Get it: the song looked up now, keeping that LaCuerda sheet.
    browser.js(f"{LC_ROWS}.find((h) => h.querySelector('.row-title').textContent === 'Como Camarón')"
               ".querySelector('.row-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--lacuerda={LC}estopa/como_camaron")
    assert args[-2:] == ("Estopa", "Como Camarón")
    assert browser.wait("!!document.querySelector('#results .progress')")
    assert browser.wait("document.querySelector('#results .progress').dataset.tone === 'ready'", timeout=20)


def test_an_artist_whose_page_caracole_never_read_is_read_on_asking_then_listed(cfg, live, browser):
    base, queue, runner = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg, complete=False)
    search(browser, base, "joaquin sabina")
    assert browser.wait(f"{LC_ROWS}.length === 1")
    partly = browser.js("document.querySelector('#results .skipped.partial').textContent")
    assert "LaCuerda" in partly and "still being read" in partly and "E, J" in partly
    browser.click("#results .hit[data-slug='joaquin_sabina'] .row-action button")
    assert browser.wait("!!document.querySelector('#results .read-page button')")
    assert "241 songs" in browser.js("document.querySelector('#results .read-page').textContent")
    assert queue.snapshot() == []  # Songs asks nothing: reading their page is a button of its own
    browser.click("#results .read-page button")
    assert browser.wait(f"{TITLES}.length === 2", timeout=20)
    assert ("lacuerda", "--artist=joaquin_sabina") in runner.ran
    assert sorted(browser.js(TITLES)) == ["19 Días y 500 Noches", "Y Nos Dieron Las Diez"]
    assert "2 songs on LaCuerda" in browser.js("document.getElementById('bar-status').textContent")


def test_a_lacuerda_song_can_be_added_for_tonights_run_with_its_pick(cfg, live, browser):
    base, queue, _ = live
    sites(cfg, ug=[("radiohead", "creep", 4)])
    lacuerda(cfg)
    library(cfg, ("Estopa", "Tu Calorro"))
    search(browser, base, "estopa como camaron")
    assert browser.wait(f"{TITLES}.includes('Como Camarón')")
    row = "#results .hit[data-source='lacuerda']:not(.artist-hit)"
    assert browser.js(f"document.querySelector(\"{row} .row-facts\").textContent") == "3 versions"
    browser.click(f"{row} .row-more")
    browser.click(f"{row} .row-panel .later button")
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
    assert browser.wait(f"{TITLES}.length === 2")
    browser.js(f"{LC_ROWS}.find((h) => h.querySelector('.row-title').textContent === 'Tu Calorro')"
               ".querySelector('.row-action button').click()")
    args = posted(queue)
    assert args[:3] == ("get", "--progress", f"--lacuerda={LC}estopa/tu_calorro") and args[-2:] == ("Estopa", "Tu Calorro")


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
        assert phone.wait(f"{LC_ROWS}.length === 1")
        phone.click("#results .hit[data-slug='joaquin_sabina'] .row-action button")
        assert phone.wait("!!document.querySelector('#results .read-page button')")
        assert phone.js("document.documentElement.scrollWidth <= innerWidth")
        assert phone.js("document.querySelector('#results .read-page button').getBoundingClientRect().height") >= 44
        # The request form is filled in with the artist LaCuerda alone knows.
        search(phone, base, "joaquin sabina")
        assert phone.wait(f"{LC_ROWS}.length === 1")
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
    browser.press("Enter")
    assert browser.wait("!!document.querySelector('#results .file-answer, #list .file-answer, .file-answer')")
    said = browser.js("document.querySelector('.file-answer').textContent")
    assert "LaCuerda" in said and "caracole search 'estopa'" in said
    assert browser.js("performance.getEntriesByType('resource').length") == 0  # the file asks nothing
