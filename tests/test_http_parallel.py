"""http.py's ParallelClient: PoliteClient's rules with several requests in flight at once (UG's artist directory)."""

from __future__ import annotations

import threading
import time

import httpx
import pytest

from caracole.config import ProviderPolicy
from caracole.http import BudgetExhausted, ParallelClient, ProviderBlocked, RobotsClosed

WWW = "https://www.ultimate-guitar.com"


def _client(tmp_path, handler, *, workers=3, budget=100, events=None) -> ParallelClient:
    return ParallelClient("ug", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), tmp_path, user_agent="caracole-test",
                          transport=httpx.MockTransport(handler), workers=workers,
                          on_event=(events.append if events is not None else None), sleep=lambda s: None)


def _urls(n: int) -> list[str]:
    return [f"{WWW}/bands/s{k}.htm" for k in range(2, n + 2)]


def _workers_alive() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("ug-get")]


def test_its_requests_are_in_flight_at_once(tmp_path):
    workers = 4
    lock = threading.Condition()
    state = {"active": 0, "most": 0, "all": False}

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            state["active"] += 1
            state["most"] = max(state["most"], state["active"])
            if state["active"] >= workers:  # every worker's request at once
                state["all"] = True
                lock.notify_all()
            lock.wait_for(lambda: state["all"], timeout=5)
            state["active"] -= 1
        return httpx.Response(200, text="ok")

    with _client(tmp_path, handler, workers=workers) as client:
        answers = list(client.get_many(_urls(workers)))
    assert state["most"] == workers
    assert [a.status for _, a in answers] == [200] * workers
    assert not _workers_alive()


def test_answers_come_in_the_order_asked_and_events_in_the_callers_thread(tmp_path):
    events = []
    owner = threading.get_ident()
    seen_in = set()

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(str(request.url).rsplit("s", 1)[1].split(".")[0])
        time.sleep(0.02 * (10 - page))  # the later ones answer first
        return httpx.Response(200, text=str(page))

    def record(event):
        seen_in.add(threading.get_ident())
        events.append(event)

    with _client(tmp_path, handler, events=None) as client:
        client._deliver = record
        answers = list(client.get_many(_urls(6)))
    assert [url for url, _ in answers] == _urls(6)
    assert [a.text for _, a in answers] == [str(k) for k in range(2, 8)]
    assert seen_in == {owner} and len(events) == 6 and {e.decision for e in events} == {"ok"}


def test_the_budget_and_the_cache_are_its_own(tmp_path):
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, text="ok")

    urls = _urls(5)
    with _client(tmp_path, handler, budget=3) as client:
        answers = dict(client.get_many(urls))
        assert client.requests_made == 3
    assert sum(isinstance(a, BudgetExhausted) for a in answers.values()) == 2
    with _client(tmp_path, handler, budget=0) as client:  # what the cache holds costs nothing
        again = dict(client.get_many(urls))
    assert [a.from_cache for a in again.values() if not isinstance(a, BaseException)].count(True) == 3
    assert len(asked) == 3


def test_robots_txt_still_closes_a_page(tmp_path):
    with _client(tmp_path, lambda r: httpx.Response(200, text="ok")) as client:
        [(_, answer)] = list(client.get_many([f"{WWW}/search.php?value=x"]))
    assert isinstance(answer, RobotsClosed)


def test_a_block_stops_every_worker_and_nothing_more_is_sent(tmp_path):
    asked = []
    urls = _urls(12)

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if str(request.url) == urls[1]:
            return httpx.Response(429, text="slow down")
        time.sleep(0.2)
        return httpx.Response(200, text="ok")

    with _client(tmp_path, handler, workers=2) as client:
        answers = []
        for url, answer in client.get_many(urls):
            answers.append(answer)
            if isinstance(answer, ProviderBlocked):
                break
        with pytest.raises(ProviderBlocked):
            client.get(urls[-1])  # the client sends nothing more
    assert len(asked) <= 3 and urls[-1] not in asked
    assert any(isinstance(a, ProviderBlocked) for a in answers)
    assert not _workers_alive()


def test_a_pass_stopped_midway_leaves_no_worker_running(tmp_path):
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        time.sleep(0.05)
        return httpx.Response(200, text="ok")

    with _client(tmp_path, handler, workers=3) as client:
        answers = client.get_many(_urls(20))
        next(answers)
        answers.close()  # as Ctrl-C or a stop ends it
        assert not _workers_alive()
        made = client.requests_made
    assert made <= 4 and len(asked) == made
