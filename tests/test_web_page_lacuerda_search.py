"""LaCuerda's own search from the library page's bar and the lookup page, in a real browser.

A real ``caracole serve`` (as test_web_page_lacuerda.py's ``live``) serves the pages; its queue runs
``FakeSearch``: ``caracole lacuerda --search`` as the command takes LaCuerda's answer into its index, with no
request, saying how it goes as ``--progress`` does. LaCuerda's index holds Estopa (their page read); a query
whose song it lacks, "corazon de tiza", is LaCuerda's search's to answer: the page sends it by itself once the
query has settled (the box unchanged for 1.5 s), never while you type on, never on Enter, never twice; or, once
the hour's share of such searches is spent, offers it as a button, as it does under a search the route refused
for that share, or one that failed (``FakeSearch.fails``), which no page sends by itself again within the hour.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.lacuerda_site import search_page
from test_web_page_lacuerda import LC_ROWS, LOOKUP_TITLES, TITLES, lacuerda

from caracole import db
from caracole.get import PROGRESS_PREFIX
from caracole.lacuerda import parse_search
from caracole.lacuerda_index import store_search
from caracole.lacuerda_search import query_key, record_failure
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

pytestmark = CHROMIUM_MARKS

LINE = "((document.querySelector('.lacuerda-search') || {}).textContent || '')"
GO = ".lacuerda-search button.lacuerda-search-go"


class FakeSearch:
    """The queue's caracole: ``lacuerda --search`` takes a page of LaCuerda's answer into the index, as the command
    does, with no request, its stage said as ``--progress`` says it."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ran: list[tuple[str, ...]] = []
        self.fails = False  # LaCuerda answers what caracole can't read: the command records the failure

    def __call__(self, args, emit):
        self.ran.append(tuple(args))
        assert args[0] == "lacuerda" and args[1].startswith("--search="), args
        emit(PROGRESS_PREFIX + json.dumps({"stage": "search", "state": "running", "detail": "asking LaCuerda"}))
        time.sleep(0.4)  # long enough for the page to say it searches
        conn = db.connect(self.cfg.db_path)
        if self.fails:
            try:
                record_failure(conn, query_key(args[1].removeprefix("--search=")), datetime.now(UTC),
                               "LaCuerda failed: cut short")
                conn.commit()
            finally:
                conn.close()
            said = "Not searched: LaCuerda failed (cut short); nothing changed: try again later."
            emit(PROGRESS_PREFIX + json.dumps({"stage": "search", "state": "skipped", "detail": said}))
            emit(said)
            return 0
        try:
            store_search(conn, parse_search(search_page(
                ("imaginarios", "Los Imaginarios", [("corazon_de_tiza", "Corazón de Tiza", "RT-12")]))))
            conn.commit()
        finally:
            conn.close()
        said = "Searched: LaCuerda has 1 song for “corazon de tiza”, in the index now."
        emit(PROGRESS_PREFIX + json.dumps({"stage": "search", "state": "done", "detail": said}))
        emit(said)
        return 0


@pytest.fixture
def live(cfg):
    runner = FakeSearch(cfg)
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


def spend_the_share(cfg) -> None:
    """The hour's 20 searches the page sends by itself, sent."""
    conn = db.connect(cfg.db_path)
    conn.executemany("INSERT INTO events (run, at, provider, url, decision) VALUES (?, ?, 'lacuerda', 'x', 'ok')",
                     [("lookup:lacuerda-search:x", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))] * 20)
    conn.commit()
    conn.close()


def jobs(queue) -> list[tuple[str, ...]]:
    return [job.steps[0].args for job in queue.snapshot()]


def type_into(browser, field, text):
    browser.js(f"document.getElementById('{field}').focus()")
    browser.type(text)


def test_a_query_that_settles_sends_lacuerdas_search_once_and_its_songs_arrive(cfg, live, browser):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait("document.getElementById('found').dataset.query === 'corazon de tiza'")
    assert jobs(queue) == []  # the answer is in, and the query hasn't settled yet
    assert browser.wait(f"{LINE}.includes('Searching LaCuerda')", timeout=5)
    assert jobs(queue) == [("lacuerda", "--search=corazon de tiza", "--progress", "--auto")]
    # Once it is over, the bar's search again: LaCuerda's song in its artist's group, and what LaCuerda answered.
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert browser.wait(f"{LINE}.startsWith('Searched: LaCuerda has 1 song')")
    time.sleep(2)  # settled again, with LaCuerda's answer: never sent twice
    assert len(jobs(queue)) == 1


def test_typing_on_sends_nothing_and_neither_does_enter_which_leaves_the_button(cfg, live, browser):
    base, queue, runner = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon")
    for more in (" d", "e t", "iza"):  # a word every ~0.6 s: the box never settles
        time.sleep(0.6)
        browser.type(more)
    browser.press("Enter")
    assert browser.wait(f"!!document.querySelector('{GO}')", timeout=5)
    time.sleep(2.5)  # long past the 1.5 s a settled query waits
    assert jobs(queue) == [] and runner.ran == []
    assert browser.js(f"document.querySelector('{GO}').textContent") == \
        "Search LaCuerda for “corazon de tiza” (1 request)"
    browser.click(GO)  # by hand: past the share of the searches the page sends by itself
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [("lacuerda", "--search=corazon de tiza", "--progress")]


def test_with_the_hours_share_spent_the_page_offers_the_button(cfg, live, browser):
    base, queue, _ = live
    lacuerda(cfg)
    spend_the_share(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait(f"!!document.querySelector('{GO}')", timeout=5)
    time.sleep(2)
    assert jobs(queue) == []
    browser.click(GO)
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [("lacuerda", "--search=corazon de tiza", "--progress")]


def test_a_search_the_route_refuses_for_the_spent_share_offers_the_button_its_refusal_names(cfg, live, browser):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait("document.getElementById('found').dataset.query === 'corazon de tiza'")
    # The share is spent between the answer's gate and the page's request, which the route refuses: "press Search
    # LaCuerda", and the page shows it.
    spend_the_share(cfg)
    assert browser.wait(f"!!document.querySelector('{GO}')", timeout=6)
    assert "press Search LaCuerda" in browser.js(LINE) and jobs(queue) == []
    browser.click(GO)
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [("lacuerda", "--search=corazon de tiza", "--progress")]


def test_a_search_that_failed_offers_the_button_and_no_page_sends_it_again_by_itself(cfg, live, browser):
    base, queue, runner = live
    runner.fails = True
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait(f"!!document.querySelector('{GO}')", timeout=10)  # once its job is over
    assert browser.js(LINE).startswith("Not searched: LaCuerda failed") and len(jobs(queue)) == 1
    # Another page, the same query: it says why, offers the button, and sends nothing by itself.
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait(f"!!document.querySelector('{GO}')", timeout=5)
    assert browser.js(LINE).startswith("LaCuerda's search for “corazon de tiza” failed less than an hour ago")
    time.sleep(2)
    assert len(jobs(queue)) == 1


def test_a_query_whose_song_lacuerdas_index_has_sends_nothing(cfg, live, browser):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "como camaron")
    assert browser.wait(f"{TITLES}.includes('Como Camarón')")
    time.sleep(2)
    assert jobs(queue) == [] and browser.js("document.querySelector('.lacuerda-search')") is None


def test_the_lookup_page_sends_lacuerdas_search_once_a_query_settles(cfg, live, browser):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base + "lookup")
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait("document.getElementById('status').textContent === 'Nothing matches.' || "
                        "!!document.querySelector('#results .nothing')")
    assert jobs(queue) == []
    assert browser.wait(f"{LOOKUP_TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [("lacuerda", "--search=corazon de tiza", "--progress", "--auto")]
    assert browser.wait(f"{LINE}.startsWith('Searched: ')")
    assert LC_ROWS  # the lookup page's LaCuerda rows are rows too
