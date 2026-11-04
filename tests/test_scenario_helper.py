"""tests/helpers/scenario.py's records, and the two HTTP-only records it writes for the phone's http-client lane to
replay alone (vectors/http/scenario_helper.jsonl): a helper making two ``client.get`` calls, no site pass.

- "a miss, then the same page from the cache": the first get is sent and cached, the second read from the cache;
- "a cached page, then a 404": the first answered by what the cache held before (nothing sent), the second a 404
  accepted (and cached, as http.py caches every accepted 404).

Each record's ``fn`` is ``tests.test_scenario_helper.two_gets``: ``[[status, from_cache, text], …]`` of both gets.
"""

from datetime import UTC, datetime

import pytest

from caracole import db
from helpers.corpus import VECTORS, check, fixture_ref, jsonl
from helpers.scenario import record

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
FN = "tests.test_scenario_helper.two_gets"
PAGE = "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-chords-39144"
GONE = "https://tabs.ultimate-guitar.com/tab/oasis/gone-chords-1"
UG = {"ug": {"budget": 6, "delay": [0.0, 0.0]}}


def two_gets(client, first: str, second: str, accept=(200,)):
    out = []
    for url in (first, second):
        r = client.get(url, accept=set(accept))
        out.append([r.status, r.from_cache, r.text[:40]])
    return out


def records(tmp_path) -> list[dict]:
    made = []
    conn = db.connect(tmp_path / "one" / "caracole.sqlite")
    try:
        made.append(record(conn, tmp_path / "one" / "library", fn=FN, case="a miss, then the same page from the cache",
                           call=lambda c: two_gets(c["ug"], PAGE, PAGE), clients=UG, now=NOW,
                           kw={"first": PAGE, "second": PAGE},
                           answers={f"GET {PAGE}": {"status": 200, "headers": [["content-type", "text/html"]],
                                                    "body": "<html>Wonderwall</html>"}},
                           cache_dir=tmp_path / "one" / "cache"))
    finally:
        conn.close()
    conn = db.connect(tmp_path / "two" / "caracole.sqlite")
    try:
        made.append(record(conn, tmp_path / "two" / "library", fn=FN, case="a cached page, then a 404",
                           call=lambda c: two_gets(c["ug"], PAGE, GONE, accept=(200, 404)), clients=UG, now=NOW,
                           kw={"first": PAGE, "second": GONE, "accept": [200, 404]},
                           cache={"ug": {f"GET {PAGE}": {"status": 200, "fetched_at": "2026-11-01T08:00:00Z",
                                                         "body": fixture_ref("ug/tab_chords.html")}}},
                           answers={f"GET {GONE}": {"status": 404, "body": "not here"}},
                           cache_dir=tmp_path / "two" / "cache"))
    finally:
        conn.close()
    return made


def test_scenario_helper_jsonl_is_two_gets_recorded(tmp_path):
    check(VECTORS / "http" / "scenario_helper.jsonl",
          jsonl(records(tmp_path), corpus="http/scenario_helper", made_by="tests/test_scenario_helper.py"))


def test_a_record_holds_what_was_sent_the_events_and_the_cache_it_read(tmp_path):
    miss, cached = records(tmp_path)
    assert miss["out"]["requests"] == [f"GET {PAGE}"]
    assert [r[1] for r in miss["out"]["result"]] == [False, True]
    assert miss["out"]["events"] == [["ug", PAGE, 200, "ok"]]
    assert cached["out"]["requests"] == [f"GET {GONE}"]
    assert cached["out"]["result"][0][:2] == [200, True]
    assert cached["out"]["result"][1][:2] == [404, False]
    assert cached["cache"]["ug"][f"GET {PAGE}"]["body"] == {"fixture": "ug/tab_chords.html"}
    assert set(miss) >= {"fn", "case", "fixture", "kw", "now", "clients", "cache", "answers", "out"}


def test_a_request_the_scenario_doesnt_answer_fails_the_recording(tmp_path):
    conn = db.connect(tmp_path / "caracole.sqlite")
    try:
        with pytest.raises(AssertionError, match="answers none of"):
            record(conn, None, fn=FN, call=lambda c: two_gets(c["ug"], PAGE, GONE), clients=UG, now=NOW,
                   answers={f"GET {PAGE}": {"status": 200, "body": "x"}}, cache_dir=tmp_path / "cache")
    finally:
        conn.close()


def test_a_pass_that_raises_is_recorded_with_what_it_did_before(tmp_path):
    conn = db.connect(tmp_path / "caracole.sqlite")
    try:
        def boom(clients):
            clients["ug"].get(PAGE)
            raise ValueError("no sheet on the page")

        made = record(conn, None, fn=FN, call=boom, clients=UG, now=NOW,
                      answers={f"GET {PAGE}": {"status": 200, "body": "x"}}, cache_dir=tmp_path / "cache")
    finally:
        conn.close()
    assert made["raises"] == {"type": "ValueError", "message": "no sheet on the page"}
    assert made["after"]["requests"] == [f"GET {PAGE}"] and "out" not in made
