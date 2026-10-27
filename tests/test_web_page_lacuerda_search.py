"""LaCuerda's own search from the library page's bar and the lookup page, in a real browser.

A real ``caracole serve`` (as test_web_page_lacuerda.py's ``live``) serves the pages; its queue runs
``FakeSearch``: ``caracole lacuerda --search`` as the command takes LaCuerda's answer into its index, with no
request, saying how it goes as ``--progress`` does. LaCuerda's index holds Estopa (their page read); a query
whose song it lacks, "corazon de tiza", is LaCuerda's search's to answer: the page sends it by itself once the
query has settled (the box unchanged for 1.5 s), never while you type on, never twice; Enter sends it at once, by
hand, as the button does, and nothing else (no lookup); or, once the hour's share of such searches is spent,
offers it as a button (which Enter presses too), as it does under a search the route refused for that share, or
one that failed (``FakeSearch.fails``), which no page sends by itself again within the hour. How many searches a
page sent is what the server heard (``heard``, ``searches``), not the queue's jobs: the route joins a search still
running and refuses one asked already, which would hide a page sending it twice.

One LaCuerda button at a time, Ask LaCuerda: for a name LaCuerda's listings don't reach yet (Bunbury's B, which
``FakeSearch`` reads as ``caracole lacuerda --artist`` would), it sends LaCuerda's search while a search may go by
hand, and reads the name's page once it may not (asked, or failed lately); for a query alone, its search.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest
from conftest import add_song
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.lacuerda_site import search_page
from test_web_page_lacuerda import BUNBURY, LC_ROWS, LOOKUP_TITLES, TITLES, lacuerda
from test_web_page_search import sites

from caracole import db, stamps
from caracole import lacuerda_index as li
from caracole.db import kv_set_json
from caracole.get import PROGRESS_PREFIX
from caracole.health import record_block
from caracole.lacuerda import parse_search
from caracole.lacuerda_index import store_search
from caracole.lacuerda_search import KV_PREFIX, query_key, record_failure
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

pytestmark = CHROMIUM_MARKS

LINE = "((document.querySelector('.lacuerda-search') || {}).textContent || '')"
GO = ".lacuerda-search button.lacuerda-search-go"
ASK = ".ask-lacuerda"  # Ask LaCuerda, under the results or on the card of a search that found nothing
# The LaCuerda buttons on the screen, by their words.
BUTTONS = ("[...document.querySelectorAll('button')].filter((b) => /^(Ask|Search) LaCuerda/.test(b.textContent) && "
           "b.getClientRects().length).map((b) => b.textContent)")
GTP_BUNBURY = "https://gtptabs.com/tabs/2/bunbury/el-extranjero.html"  # a result for "bunbury": Ask under the results
BY_HAND = ("lacuerda", "--search=corazon de tiza", "--progress")  # the button's, and Enter's: no --auto
AUTO = (*BY_HAND, "--auto")  # the page's own, once the query has settled
SENT_BY_HAND = [("corazon de tiza", True)]  # what the server heard of it: one request, by hand
SENT_BY_ITSELF = [("corazon de tiza", False)]
ANSWERED = "document.getElementById('found').dataset.query === 'corazon de tiza'"
LOOKUP_ANSWERED = ("document.getElementById('status').textContent === 'Nothing matches.' || "
                   "!!document.querySelector('#results .nothing')")
# What LaCuerda's search answers, by query: a song of Los Imaginarios', else of the Eagles'.
ANSWERS = {"eagles": ("eagles", "Eagles", [("tequila_sunrise", "Tequila Sunrise", "R-3")])}
IMAGINARIOS = ("imaginarios", "Los Imaginarios", [("corazon_de_tiza", "Corazón de Tiza", "RT-12")])


class FakeSearch:
    """The queue's caracole: ``lacuerda --search`` takes a page of LaCuerda's answer into the index (``ANSWERS``) and
    records the query asked, as the command does, with no request, its stage said as ``--progress`` says it."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ran: list[tuple[str, ...]] = []
        self.fails = False  # LaCuerda answers what caracole can't read: the command records the failure

    def __call__(self, args, emit):
        self.ran.append(tuple(args))
        assert args[0] == "lacuerda" and args[1].startswith(("--search=", "--artist=")), args
        if args[1].startswith("--artist="):  # a page read by name: Bunbury's, whose B the listings haven't reached
            time.sleep(0.3)
            name = args[1].removeprefix("--artist=")
            if name != "bunbury":
                emit(f"Not found: LaCuerda has no artist page for {name}.")
                return 0
            conn = db.connect(self.cfg.db_path)
            try:
                li.store_artist_page(conn, "bunbury", BUNBURY)
                conn.commit()
            finally:
                conn.close()
            emit("Read: LaCuerda's page lists 2 songs, in the index now.")
            return 0
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
        query = args[1].removeprefix("--search=")
        try:
            answer = parse_search(search_page(ANSWERS.get(query, IMAGINARIOS), query=query))
            store_search(conn, answer)
            kv_set_json(conn, KV_PREFIX + query_key(query), {
                "at": stamps.stamp(datetime.now(UTC)), "songs": len(answer.songs), "artists": len(answer.artists)})
            conn.commit()
        finally:
            conn.close()
        said = f"Searched: LaCuerda has 1 song for “{query}”, in the index now."
        emit(PROGRESS_PREFIX + json.dumps({"stage": "search", "state": "done", "detail": said}))
        emit(said)
        return 0


@pytest.fixture
def heard():
    """What the server heard, in order: each request's method, target and form, as the pages sent it."""
    return []


@pytest.fixture
def live(cfg, heard):
    runner = FakeSearch(cfg)
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    answer = app.handle

    def handle(request):
        heard.append((request.method, request.target, parse_qs(request.body.decode("utf-8", "replace"))))
        return answer(request)

    app.handle = handle
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


def searches(heard) -> list[tuple[str, bool]]:
    """The pages' requests for LaCuerda's search, as the server heard them: each one's query, and whether by hand."""
    return [(form.get("q", [""])[0], form.get("by_hand") == ["1"]) for method, target, form in heard
            if method == "POST" and target.split("?")[0] == "/lacuerda/search"]


def until(check, timeout=10.0):
    """Whether ``check()`` holds within ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def type_into(browser, field, text):
    browser.js(f"document.getElementById('{field}').focus()")
    browser.type(text)


def put(browser, text):
    """``text`` put into the search box in one go, as a paste: no answer for a part of it ("bunb") on the way, whose
    Ask LaCuerda would be another name's."""
    browser.js("(() => { const q = document.getElementById('q'); q.focus(); q.value = " + json.dumps(text) + "; "
               "q.dispatchEvent(new Event('input', {bubbles: true})); })()")


def type_and_enter(browser, text, *after):
    """``text`` typed into the search box and Enter pressed in one go, then the keys ``after`` (Escape): before the
    query's answer, which the page asks for only once its timer, after the last key, has run."""
    browser.js("(() => { const q = document.getElementById('q'); q.focus(); q.value = " + json.dumps(text) + "; "
               "q.dispatchEvent(new Event('input', {bubbles: true})); "
               "for (const key of " + json.dumps(["Enter", *after]) + ") "
               "q.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true})); })()")


def keys_once(browser, ready, keys, seen="null"):
    """``keys`` (Enter, Escape) pressed in the search box by the page itself the moment ``ready`` holds, one after the
    other with nothing between them: no gap a busy machine may stretch past the 1.5 s after which a settled query's
    search goes by itself. Gives ``seen`` after each key."""
    said = browser.js(
        "new Promise((done) => { const q = document.getElementById('q'); const until = performance.now() + 10000; "
        "const go = () => { if (!(" + ready + ")) { if (performance.now() > until) done(null); "
        "else setTimeout(go, 5); return; } "
        "done(" + json.dumps(list(keys)) + ".map((key) => { "
        "q.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true})); "
        "return " + seen + "; })); }; go(); })")
    assert said is not None, f"never {ready}"
    return said


def test_a_query_that_settles_sends_lacuerdas_search_once_and_its_songs_arrive(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait("document.getElementById('found').dataset.query === 'corazon de tiza'")
    assert jobs(queue) == []  # the answer is in, and the query hasn't settled yet
    assert browser.wait(f"{LINE}.includes('Searching LaCuerda')", timeout=5)
    # Once it is over, the bar's search again: LaCuerda's song in its artist's group, and what LaCuerda answered.
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [AUTO]  # once its job is over: the line says it searches before the request is in
    assert browser.wait(f"{LINE}.startsWith('Searched: LaCuerda has 1 song')")
    time.sleep(2)  # settled again, with LaCuerda's answer: never sent twice
    assert len(jobs(queue)) == 1 and searches(heard) == SENT_BY_ITSELF


def test_typing_on_sends_nothing_and_enter_sends_it_at_once_by_hand_and_once(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon")
    for more in (" d", "e t", "iza"):  # a word every ~0.6 s: the box never settles
        time.sleep(0.6)
        browser.type(more)
    # Enter twice the moment the answer is in, long before the query settles: sent now, by hand, as the button sends
    # it, and once.
    keys_once(browser, ANSWERED, ["Enter", "Enter"])
    assert browser.wait(f"{LINE}.includes('Searching LaCuerda')", timeout=5)
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [BY_HAND]
    assert browser.wait(f"{LINE}.startsWith('Searched: LaCuerda has 1 song')")
    browser.js("document.getElementById('q').focus()")
    browser.press("Enter")  # again, the same query: asked already
    time.sleep(2)  # long past the 1.5 s a settled query waits: the page's own sends nothing more
    assert jobs(queue) == [BY_HAND]
    assert searches(heard) == SENT_BY_HAND  # nothing for the words typed on the way, one request for the query


def test_enter_moves_to_the_first_result_looks_nothing_up_and_the_focus_stays_as_lacuerdas_songs_arrive(
        cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    sites(cfg, ug=[("los-imaginarios", "corazon-de-tiza", 2)])  # Ultimate Guitar has it: LaCuerda's search still may
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    keys_once(browser, ANSWERED, ["Enter"])
    focused = "!!(document.activeElement && document.activeElement.closest('#found article'))"
    assert browser.wait(focused)
    assert browser.wait(f"{LINE}.startsWith('Searched: ')", timeout=10)
    assert browser.wait("!!document.querySelector('#found .line-sources .source[data-source=\"lacuerda\"]')")
    assert browser.js(focused)  # the answer drawn again: the focus on the line it was on
    assert jobs(queue) == [BY_HAND]  # LaCuerda's search alone: no song looked up
    assert searches(heard) == SENT_BY_HAND


def test_enter_before_the_answer_sends_it_with_the_answer_and_moves_to_the_first_result(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    sites(cfg, ug=[("los-imaginarios", "corazon-de-tiza", 2)])
    browser.open(base)
    type_and_enter(browser, "corazon de tiza", "Enter")  # twice, before the answer
    assert browser.js("document.getElementById('found').dataset.query") != "corazon de tiza"  # on its way
    assert browser.wait("!!(document.activeElement && document.activeElement.closest('#found article'))")
    assert browser.wait(f"{LINE}.startsWith('Searched: ')", timeout=10)
    time.sleep(2)  # long past the 1.5 s a settled query waits
    assert jobs(queue) == [BY_HAND]  # by hand, once, and no song looked up
    assert searches(heard) == SENT_BY_HAND


def test_enter_back_into_the_results_sends_it_once_their_answer_is_in(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    # The moment the answer is in, Escape (back to your songs, the query kept), then Enter: the results again, and
    # LaCuerda's search with their answer.
    hidden = "document.getElementById('results').hidden"
    assert keys_once(browser, ANSWERED, ["Escape", "Enter"], hidden) == [True, False]
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    time.sleep(2)
    assert jobs(queue) == [BY_HAND]
    assert searches(heard) == SENT_BY_HAND


def test_escape_before_the_answer_takes_back_the_enter_that_waited_for_it(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    conn = db.connect(cfg.db_path)
    add_song(conn)  # a song of yours: the list, with none that matches, offers the sites' search again
    conn.commit()
    conn.close()
    browser.open(base)
    type_and_enter(browser, "corazon de tiza", "Escape")  # Enter, then Escape, before the query's answer
    time.sleep(2)
    assert browser.js("document.getElementById('results').hidden") and searches(heard) == []
    # The sites' results again by the list's button, no Enter: the query waits to settle, as one typed does, and its
    # search goes by itself then.
    browser.js("[...document.querySelectorAll('button')].find((b) => b.textContent.startsWith('Search the sites for'))"
               ".click()")
    assert browser.wait(ANSWERED)
    assert browser.wait(f"{LINE}.startsWith('Searched: ')", timeout=10)
    assert searches(heard) == SENT_BY_ITSELF and jobs(queue) == [AUTO]


@pytest.mark.parametrize("page, titles", [("", TITLES), ("lookup", LOOKUP_TITLES)], ids=["library", "lookup"])
def test_with_the_hours_share_spent_enter_sends_it_by_hand(cfg, live, browser, heard, page, titles):
    base, queue, _ = live
    lacuerda(cfg)
    spend_the_share(cfg)
    browser.open(base + page)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait(f"!!document.querySelector('{GO}')", timeout=5)
    assert jobs(queue) == []
    browser.press("Enter")  # a person asking, as the button is
    assert browser.wait(f"{titles}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [BY_HAND] and searches(heard) == SENT_BY_HAND


@pytest.mark.parametrize("page", ["", "lookup"], ids=["library", "lookup"])
@pytest.mark.parametrize("state", ["failed", "spent"])
def test_enter_sends_nothing_once_its_search_failed_lately_or_while_lacuerdas_search_waits(
        cfg, live, browser, heard, page, state):
    base, queue, _ = live
    lacuerda(cfg)
    conn = db.connect(cfg.db_path)
    if state == "failed":  # within the hour: its button alone asks again
        record_failure(conn, query_key("corazon de tiza"), datetime.now(UTC), "LaCuerda failed: cut short")
    else:  # LaCuerda cools down after a block
        record_block(conn, "lacuerda", datetime.now(UTC), "LaCuerda blocked caracole")
    conn.commit()
    conn.close()
    browser.open(base + page)
    type_into(browser, "q", "corazon de tiza")
    said = f"!!document.querySelector('{GO}')" if state == "failed" else f"{LINE}.includes('search waits')"
    assert browser.wait(said, timeout=5)
    browser.press("Enter")
    time.sleep(2)
    assert searches(heard) == [] and jobs(queue) == []


@pytest.mark.parametrize("page", ["", "lookup"])
def test_enter_sends_nothing_for_a_query_asked_lately_or_one_lacuerdas_index_answers(cfg, live, browser, heard,
                                                                                      page):
    base, queue, _ = live
    lacuerda(cfg)
    conn = db.connect(cfg.db_path)
    kv_set_json(conn, KV_PREFIX + query_key("corazon de tiza"),
                {"at": stamps.stamp(datetime.now(UTC)), "songs": 0, "artists": 0})
    conn.commit()
    conn.close()
    for query, shown in (("corazon de tiza", "Nothing"), ("como camaron", "Como Camarón")):
        browser.open(base + page)
        type_into(browser, "q", query)
        assert browser.wait(f"document.body.textContent.includes({json.dumps(shown)})")
        browser.press("Enter")
        time.sleep(2)
        assert jobs(queue) == [] and searches(heard) == [], query
        assert browser.js("document.querySelector('.lacuerda-search-go')") is None


def test_with_the_hours_share_spent_the_page_offers_the_button(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    spend_the_share(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait(f"!!document.querySelector('{GO}')", timeout=5)
    time.sleep(2)
    assert jobs(queue) == [] and searches(heard) == []
    assert browser.js(BUTTONS) == ["Ask LaCuerda for “corazon de tiza” (1 request)"]  # the one button, its search
    browser.click(GO)
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [BY_HAND] and searches(heard) == SENT_BY_HAND


def test_a_search_the_route_refuses_for_the_spent_share_offers_the_button_its_refusal_names(cfg, live, browser,
                                                                                            heard):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait("document.getElementById('found').dataset.query === 'corazon de tiza'")
    # The share is spent between the answer's gate and the page's request, which the route refuses: "press Ask
    # LaCuerda", and the page shows it, with that button.
    spend_the_share(cfg)
    assert browser.wait(f"!!document.querySelector('{GO}')", timeout=6)
    assert "press Ask LaCuerda" in browser.js(LINE) and jobs(queue) == []
    assert browser.js(BUTTONS) == ["Ask LaCuerda for “corazon de tiza” (1 request)"]
    browser.click(GO)
    assert browser.wait(f"{TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [BY_HAND]
    assert searches(heard) == SENT_BY_ITSELF + SENT_BY_HAND  # the page's own, refused, then the button's


def test_a_search_that_failed_offers_the_button_and_no_page_sends_it_again_by_itself(cfg, live, browser, heard):
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
    assert len(jobs(queue)) == 1 and searches(heard) == SENT_BY_ITSELF


@pytest.mark.parametrize("page, query, label", [
    ("", "bunbury", "Ask LaCuerda for “bunbury” (1 request)"),  # under the results: gtptabs.com has a song of theirs
    ("", "caifanes", "Ask LaCuerda (1 request)"),  # on the card of a search that found nothing
    ("lookup", "bunbury", "Ask LaCuerda (1 request)"),
], ids=["library", "library-card", "lookup"])
def test_a_query_that_offers_its_search_and_a_names_page_shows_one_button_whose_press_sends_the_search(
        cfg, live, browser, heard, page, query, label):
    base, queue, runner = live
    lacuerda(cfg, complete=False)  # LaCuerda's listings read to E and J only: the name's page may say
    sites(cfg, gtptabs=[GTP_BUNBURY])
    spend_the_share(cfg)  # a search goes by hand alone
    browser.open(base + page)
    put(browser, query)
    assert browser.wait(f"!!document.querySelector('{ASK}')", timeout=5)
    time.sleep(0.5)
    assert browser.js(BUTTONS) == [label]  # one LaCuerda button, Ask LaCuerda's, where it was
    assert jobs(queue) == []
    browser.click(ASK)  # LaCuerda's search, which answers artists and songs both
    assert browser.wait(f"{LINE}.startsWith('Searched: ')", timeout=10)
    assert jobs(queue) == [("lacuerda", f"--search={query}", "--progress")] and searches(heard) == [(query, True)]
    # Asked: the one button reads the name's page now, as Ask LaCuerda did.
    assert browser.wait(f"!!document.querySelector('{ASK}:not([disabled])')", timeout=5)
    assert browser.js(BUTTONS) == [label]
    browser.click(ASK)
    assert until(lambda: len(runner.ran) == 2 and not queue.snapshot()[-1].active)
    # The queue's newest first: the page's read, after the search.
    assert jobs(queue) == [("lacuerda", f"--artist={query}"), ("lacuerda", f"--search={query}", "--progress")]
    assert searches(heard) == [(query, True)]


def test_the_one_button_pressed_before_the_query_settles_sends_the_search_by_hand_once(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg, complete=False)
    sites(cfg, gtptabs=[GTP_BUNBURY])
    browser.open(base)
    put(browser, "bunbury")
    # Pressed the moment it shows, long before the query settles: LaCuerda's search, by hand; the page's own then
    # sends nothing.
    pressed = browser.js(
        "new Promise((done) => { const until = performance.now() + 10000; const go = () => { "
        f"const ask = document.querySelector('{ASK}'); "
        "if (!ask) { if (performance.now() > until) done(null); else setTimeout(go, 5); return; } "
        f"const shown = {BUTTONS}; ask.click(); done(shown); }}; go(); }})")
    assert pressed == ["Ask LaCuerda for “bunbury” (1 request)"]
    assert browser.wait(f"{LINE}.startsWith('Searched: ')", timeout=10)
    time.sleep(2)  # long past the 1.5 s a settled query waits
    assert jobs(queue) == [("lacuerda", "--search=bunbury", "--progress")]
    assert searches(heard) == [("bunbury", True)]


@pytest.mark.parametrize("page, titles, label", [
    ("", TITLES, "Ask LaCuerda for “bunbury” (1 request)"), ("lookup", LOOKUP_TITLES, "Ask LaCuerda (1 request)")],
    ids=["library", "lookup"])
def test_with_its_search_failed_lately_the_one_button_reads_the_names_page(cfg, live, browser, heard, page, titles,
                                                                            label):
    base, queue, _ = live
    lacuerda(cfg, complete=False)
    sites(cfg, gtptabs=[GTP_BUNBURY])
    conn = db.connect(cfg.db_path)
    record_failure(conn, query_key("bunbury"), datetime.now(UTC), "LaCuerda failed: cut short")
    conn.commit()
    conn.close()
    browser.open(base + page)
    put(browser, "bunbury")
    assert browser.wait(f"!!document.querySelector('{ASK}')", timeout=5)
    assert browser.wait(f"{LINE}.startsWith('LaCuerda\\'s search for “bunbury” failed less than an hour ago')")
    assert browser.js(BUTTONS) == [label]  # why the search waits, and one button: the name's page
    browser.click(ASK)
    assert browser.wait(f"{titles}.length === 2", timeout=10)
    assert sorted(browser.js(titles)) == ["Infinito", "Lady Blue"]
    assert jobs(queue) == [("lacuerda", "--artist=bunbury")] and searches(heard) == []


def test_a_query_whose_song_lacuerdas_index_has_sends_nothing(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base)
    type_into(browser, "q", "como camaron")
    assert browser.wait(f"{TITLES}.includes('Como Camarón')")
    time.sleep(2)
    assert jobs(queue) == [] and browser.js("document.querySelector('.lacuerda-search')") is None
    assert searches(heard) == []


def test_the_lookup_page_sends_lacuerdas_search_once_a_query_settles(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base + "lookup")
    type_into(browser, "q", "corazon de tiza")
    assert browser.wait(LOOKUP_ANSWERED)
    assert jobs(queue) == []
    assert browser.wait(f"{LOOKUP_TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [AUTO]
    assert browser.wait(f"{LINE}.startsWith('Searched: ')")
    assert LC_ROWS  # the lookup page's LaCuerda rows are rows too
    time.sleep(2)  # settled again, with LaCuerda's answer: never sent twice
    assert searches(heard) == SENT_BY_ITSELF


def test_enter_on_the_lookup_page_sends_lacuerdas_search_at_once_by_hand_and_looks_nothing_up(cfg, live, browser,
                                                                                               heard):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base + "lookup")
    type_and_enter(browser, "corazon de tiza", "Enter")  # twice, before its answer: sent with it, once
    assert browser.wait(f"{LOOKUP_TITLES}.includes('Corazón de Tiza')", timeout=10)
    assert jobs(queue) == [BY_HAND]
    browser.js("document.getElementById('q').focus()")
    browser.press("Enter")  # its answer on the screen, asked already: nothing stands out, nothing asked
    time.sleep(2)
    assert jobs(queue) == [BY_HAND] and searches(heard) == SENT_BY_HAND


def test_enter_on_the_lookup_page_with_its_answer_shown_sends_it_by_hand(cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    browser.open(base + "lookup")
    type_into(browser, "q", "corazon de tiza")
    keys_once(browser, LOOKUP_ANSWERED, ["Enter", "Enter"])  # twice, the moment the answer is in
    assert browser.wait(f"{LOOKUP_TITLES}.includes('Corazón de Tiza')", timeout=10)
    time.sleep(2)  # long past the 1.5 s a settled query waits: the page's own sends nothing more
    assert jobs(queue) == [BY_HAND] and searches(heard) == SENT_BY_HAND


def test_enter_on_the_lookup_page_opens_the_leading_artist_whose_songs_stay_once_lacuerdas_search_is_over(
        cfg, live, browser, heard):
    base, queue, _ = live
    lacuerda(cfg)
    sites(cfg, ug=[("eagles", "hotel-california", 9), ("eagles", "desperado", 3)])
    browser.open(base + "lookup")
    type_into(browser, "q", "eagles")
    keys_once(browser, "!!document.querySelector('#results .artist-hit')", ["Enter"])
    name = "(document.querySelector('#results .artist-head h2') || {}).textContent"
    assert browser.wait(f"{name} === 'Eagles'")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (queue.snapshot() and not queue.snapshot()[-1].active):
        time.sleep(0.05)
    assert jobs(queue) == [("lacuerda", "--search=eagles", "--progress")]  # by hand; no lookup
    time.sleep(2)  # the page heard it is over
    assert browser.js(name) == "Eagles"  # their songs stay
    assert searches(heard) == [("eagles", True)]
    assert browser.js(f"{LOOKUP_TITLES}.includes('Eagles')") is False  # LaCuerda's index hasn't them yet
    browser.click("#results .artist-head button")  # All results: asked again, with what LaCuerda's search put in
    assert browser.wait(f"{LOOKUP_TITLES}.includes('Eagles')")  # their row on LaCuerda now, beside Ultimate Guitar's
    assert browser.js("!!document.querySelector('#results .artist-hit')")
