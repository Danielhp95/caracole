"""Cooldowns, events and the lookup pace, for the phone: what health.py and commands/_common.py's lookup pace answer
for given kv records, events and times, written for the Kotlin port's core.health (``Health``, ``EventLog``) and
core.lookup's ``Pace`` to agree with (docs/superpowers/plans/2026-11-03-android-port-m4-m6.md, lane health-pace).

Each caracole's politeness is its own (the owner's choice of 2026-11-03): the schema stays 15, ``events`` has no
origin, and every event a database holds is its own side's.

Every record's times are stamps in UTC, ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z`` (``datetime.fromisoformat``, Kotlin's
``Instant.parse``); an answer's times are ``datetime.isoformat``'s (``2026-10-18T03:30:00+00:00``, microseconds when
there are any). A float the JSON can't hold is the text ``"inf"``, ``"-inf"`` or ``"nan"``. An event of a record's
``events`` is a row of the table, ``[run, at, provider, url, status, decision, message]``, inserted in order into a
database that holds no other (with an eighth element ``n``, that row ``n`` times over); ``kv`` is ``{key: text}``, put
there first. Each record's database starts with neither.

**Vectors**:

- health/state.jsonl: ``{fn: "caracole.health", case, kw: {provider, kv, steps}, out}``: the kv
  ``provider:<provider>`` holds ``kv`` (a text, or null for none), then each step of ``steps`` runs in order,
  ``[op, now, message]``: ``block`` (``record_block(conn, provider, now, message)``), ``ok`` (``record_ok``),
  ``error`` (``record_error``), ``cooling`` (``is_cooling``) or ``state`` (``get_state``; its ``now`` null). ``out``
  is a step's answer each: ``{"kv": the record's text after it, byte for byte, or null}`` with the state it returned
  (``"state": {provider, strikes, cooldown_until, last_ok, last_error, last_error_at}``) or ``"cooling"``; a step
  that raised is ``{"err": its class}``, and the steps stop there. The cooldown is 24 h × 2^(k−1) + 2 h after the
  k-th block in a row, and a running one stays as it is, its strikes too.
- health/answered.jsonl: ``{fn: "caracole.health.answered_any", kw: {events, run, provider, requests}, out}``.
- health/events.jsonl: ``{fn: "caracole.health.EventLog", kw: {run, clock, events}, out}``: an ``EventLog(conn, run,
  clock=…)`` whose clock gives the times of ``clock`` in turn, called with each event of ``events``, ``[provider,
  url, status, decision, message]``; ``out`` the rows it wrote, ``[run, at, provider, url, status, decision,
  message]``.
- pace/run_id.jsonl: ``{fn: "caracole.commands._common.lookup_run_id", args: [now], out}``.
- pace/counts.jsonl: ``{fn, kw: {events, provider, now, run?}, out}``, ``fn`` ``…lookup_requests_used`` (``run``
  given only where the record names one) or ``…requests_today``.
- pace/policy.jsonl: ``{fn: "caracole.commands._common.lookup_policy", kw: {providers, events, provider, now}, out:
  {lookup_policy, within_the_day, bulk_within_the_day}}``: a config whose providers are ``config.DEFAULT_PROVIDERS``
  with ``providers``' fields over theirs (``{name: {field: value}}``); ``out`` the provider's lookup policy, then
  ``within_the_day`` of it, then ``within_the_day`` of the provider's own (bulk) policy, each a ``ProviderPolicy``'s
  fields in order (a pair a list, ``config.NO_BUDGET`` the number it is).
- pace/last_request.jsonl: ``{fn: "caracole.commands._common._last_request", kw: {kv, events, provider}, out}``:
  kv ``http:last_request:<provider>`` holding ``kv`` (null: none), ``out`` the float, or null.
- pace/pause.jsonl: ``{fn: "caracole.commands._common._pause_after_last_request", kw: {kv, events, provider, delay,
  u, wall}, out}``: as last_request.jsonl's, with ``random.uniform(a, b)`` answering ``a + (b - a) * u`` and
  ``time.time()`` ``wall``; ``out`` the pauses it slept, in seconds (none, or one).
"""

from __future__ import annotations

import dataclasses
import math
import sqlite3
import types
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from caracole import config, health
from caracole.commands import _common
from caracole.http import Event
from helpers.corpus import VECTORS, check, jsonl

MADE_BY = "tests/test_conformance_health.py"
T0 = "2026-10-18T03:30:00Z"
NOW = "2026-11-03T12:00:00Z"


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def shown(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def later(text: str, **delta: float) -> str:
    moved = at(text) + timedelta(**delta)
    return moved.isoformat().replace("+00:00", "Z")


def number(x: float) -> float | str:
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return x


def fresh(conn: sqlite3.Connection, events: list[list[Any]] = (), kv: dict[str, str] | None = None) -> None:
    """The record's database: no event and no kv record but its own."""
    conn.execute("DELETE FROM events")
    conn.execute("DELETE FROM kv WHERE key LIKE 'provider:%' OR key LIKE 'http:last_request:%'")
    for row in events:
        for _ in range(row[7] if len(row) > 7 else 1):
            conn.execute("INSERT INTO events (run, at, provider, url, status, decision, message) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", row[:7])
    for key, value in (kv or {}).items():
        conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (key, value))


def policy_fields(p: config.ProviderPolicy) -> dict[str, Any]:
    return {f.name: list(v) if isinstance(v := getattr(p, f.name), tuple) else v for f in dataclasses.fields(p)}


# --- health/state.jsonl -------------------------------------------------------------------------------------------


def state_fields(s: health.ProviderState) -> dict[str, Any]:
    return {"provider": s.provider, "strikes": s.strikes, "cooldown_until": shown(s.cooldown_until),
            "last_ok": shown(s.last_ok), "last_error": s.last_error, "last_error_at": shown(s.last_error_at)}


def run_steps(conn: sqlite3.Connection, provider: str, steps: list[list[Any]]) -> list[dict[str, Any]]:
    out = []
    key = f"provider:{provider}"
    for op, now, *message in steps:
        try:
            if op == "block":
                answer = {"state": state_fields(health.record_block(conn, provider, at(now), message[0]))}
            elif op == "ok":
                answer = {"state": state_fields(health.record_ok(conn, provider, at(now)))}
            elif op == "error":
                answer = {"state": state_fields(health.record_error(conn, provider, at(now), message[0]))}
            elif op == "cooling":
                answer = {"cooling": health.is_cooling(conn, provider, at(now))}
            elif op == "state":
                answer = {"state": state_fields(health.get_state(conn, provider))}
            else:
                raise AssertionError(op)
        except Exception as e:  # noqa: BLE001 (the record says what Python raised)
            out.append({"err": type(e).__name__})
            break
        answer["kv"] = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        answer["kv"] = answer["kv"][0] if answer["kv"] else None
        out.append(answer)
    return out


def nights(n: int, late_minutes: int = 0) -> str:
    return later(T0, days=n, minutes=late_minutes)


MESSAGE = 'Ünïcödé — “quotes” "q" back\\slash\nline\ttab \x01\x1f control 🎸 \u2028 sep \x7f'

STATE_CASES: list[tuple[str, str, str | None, list[list[Any]]]] = [
    ("a first block cools 26 hours", "ug", None, [
        ["block", T0, "403 on /tab/1"], ["cooling", later(T0, hours=25, minutes=59)],
        ["cooling", later(T0, hours=26, seconds=-1)], ["cooling", later(T0, hours=26)],
        ["cooling", later(T0, hours=26, seconds=1)], ["state", None]]),
    ("the cooldown doubles, each 2 hours longer, until a good run resets it", "ug", None, [
        ["block", nights(0), "403 on /tab/1"], ["block", nights(2), "429"], ["block", nights(5), "403"],
        ["cooling", later(nights(5), hours=97, minutes=59)], ["cooling", later(nights(5), hours=98)],
        ["ok", nights(10)], ["state", None], ["cooling", nights(10)]]),
    ("four blocks in a row, each the first night it could ask again", "lrclib", None, [
        ["block", nights(0), "429"], ["block", nights(1, 45), "429"], ["block", nights(4), "429"],
        ["block", nights(9), "429"], ["cooling", later(nights(9), hours=193)], ["cooling", later(nights(9), hours=194)]]),
    ("a block while it cools keeps the cooldown and its strikes", "ug", None, [
        ["block", T0, "403"], ["block", later(T0, hours=1), "429 meanwhile"], ["block", later(T0, hours=25), "403"],
        ["block", later(T0, hours=26), "403 again"]]),
    ("a good run while it cools leaves the cooldown, after it clears it", "ug", None, [
        ["block", T0, "403"], ["ok", later(T0, hours=1)], ["ok", later(T0, hours=26, seconds=-1)],
        ["ok", later(T0, hours=26)], ["state", None]]),
    ("a block after a reset is a first strike", "lacuerda", None, [
        ["block", T0, "403"], ["ok", later(T0, days=2)], ["block", later(T0, days=3), "challenge page"]]),
    ("blocks with no good run between them keep counting", "ug", None, [
        ["block", T0, "403"], ["block", later(T0, days=30), "403"], ["block", later(T0, days=60), "403"]]),
    ("an error starts no cooldown, and keeps one", "megalobiz", None, [
        ["error", T0, "HTTP 502"], ["cooling", T0], ["state", None], ["block", later(T0, hours=1), "429"],
        ["error", later(T0, hours=2), "connection reset"], ["cooling", later(T0, hours=2)],
        ["ok", later(T0, days=3)], ["error", later(T0, days=4), "HTTP 500"]]),
    ("messages are written as json.dumps writes them", "azlyrics", None, [
        ["error", T0, MESSAGE], ["block", later(T0, minutes=1), ""], ["error", later(T0, minutes=2), "ascii only"],
        ["block", later(T0, days=2), "𝄞 música ♪ 宋冬野"]]),
    ("a time's microseconds are kept in the state and dropped in the record", "gtptabs", None, [
        ["block", "2026-10-18T03:30:00.999999Z", "403"], ["cooling", "2026-10-19T05:29:59.999999Z"],
        ["cooling", "2026-10-19T05:30:00.000001Z"], ["state", None],
        ["ok", "2026-10-20T00:00:00.123456Z"], ["error", "2026-10-21T00:00:00.5Z", "late"]]),
    ("providers are apart", "harptabs", None, [
        ["block", T0, "403"], ["cooling", T0], ["state", None]]),
    ("no record", "gametabs", None, [["state", None], ["cooling", T0], ["ok", T0]]),
    ("a last_error that isn't text is written back as it was", "ug",
     ('{"strikes": 1, "last_error": {"status": 5, "why": [1, 2.50, true, null]}, '
      '"last_error_at": "2026-10-18T03:30:00Z"}'),
     [["state", None], ["ok", NOW], ["state", None], ["error", later(NOW, hours=1), "502"]]),
    ("a last_error that is a number", "ug", '{"last_error": 5}', [["ok", NOW], ["block", later(NOW, hours=1), "403"]]),
    ("strikes past a 32-bit int are read and written back", "ug",
     '{"strikes": 1e10, "cooldown_until": "2026-11-04T00:00:00Z"}',
     [["state", None], ["cooling", NOW], ["error", NOW, "502"], ["block", NOW, "403"], ["ok", later(NOW, days=1)]]),
    ("strikes of twenty digits", "ug", '{"strikes": "12345678901234567890"}',
     [["state", None], ["cooling", NOW], ["error", NOW, "502"], ["ok", NOW]]),
]

SEEDED: list[tuple[str, str]] = [
    ("an empty record", "{}"),
    ("null", "null"),
    ("an empty list", "[]"),
    ("zero", "0"),
    ("false", "false"),
    ("an empty text", '""'),
    ("two strikes and no cooldown", '{"strikes": 2}'),
    ("strikes as a float", '{"strikes": 2.7}'),
    ("strikes as a text", '{"strikes": "4"}'),
    ("strikes as true", '{"strikes": true}'),
    ("strikes below zero", '{"strikes": -1}'),
    ("strikes well below zero", '{"strikes": -3}'),
    ("strikes far below zero", '{"strikes": -60}'),
    ("twenty-one strikes", '{"strikes": 21}'),
    ("twenty-two strikes: the next cooldown ends after 9999", '{"strikes": 22}'),
    ("forty strikes: the next cooldown is past timedelta's days", '{"strikes": 40}'),
    ("strikes that aren't a number", '{"strikes": "x"}'),
    ("strikes after a separator control, which int() keeps", '{"strikes": "\\u001c5"}'),
    ("strikes after a unit separator", '{"strikes": "5\\u001f"}'),
    ("strikes after an em space, which int() strips", '{"strikes": "\\u20035 "}'),
    ("strikes in other scripts' digits", '{"strikes": "\\u0663"}'),
    ("strikes as a text past int()'s 4,300 digits", '{"strikes": "' + "1" * 4301 + '"}'),
    ("strikes NaN", '{"strikes": NaN}'),
    ("strikes Infinity", '{"strikes": -Infinity}'),
    ("strikes so far below zero the power is none", '{"strikes": -2000}'),
    ("strikes too far below zero for a float", '{"strikes": -1' + "0" * 400 + '}'),
    ("strikes null", '{"strikes": null}'),
    ("a whole record", ('{"strikes": 1, "cooldown_until": "2026-10-19T05:30:00Z", "last_ok": "2026-10-01T03:30:00Z", '
                        '"last_error": "403", "last_error_at": "2026-10-18T03:30:00Z"}')),
    ("its own spacing and order", ('{"last_error_at":"2026-10-18T03:30:00Z","strikes":1,"last_error":"403",'
                                   '"cooldown_until":"2026-10-19T05:30:00Z"}')),
    ("a key caracole doesn't write", '{"strikes": 1, "extra": [1, 2], "cooldown_until": "2026-10-17T00:00:00Z"}'),
    ("single digits", '{"cooldown_until": "2026-10-19T5:3:0Z"}'),
    ("a space before a day or an hour", '{"cooldown_until": "2026-10- 9T 5:30:00Z"}'),
    ("lowercase t and z", '{"cooldown_until": "2026-10-19t05:30:00z"}'),
    ("other scripts' digits", '{"cooldown_until": "２０２６-10-19T1٥:30:0५Z"}'),
    ("an empty time", '{"cooldown_until": "", "last_ok": null}'),
    ("a time of zero", '{"cooldown_until": 0}'),
    ("a time that is a number", '{"cooldown_until": 5}'),
    ("a space for the T", '{"cooldown_until": "2026-10-19 05:30:00Z"}'),
    ("an offset for the Z", '{"last_ok": "2026-10-19T05:30:00+00:00"}'),
    ("no such day", '{"cooldown_until": "2026-02-30T00:00:00Z"}'),
    ("the 29th of February of a leap year", '{"cooldown_until": "2028-02-29T00:00:00Z"}'),
    ("a 60th second", '{"cooldown_until": "2026-10-19T05:30:60Z"}'),
    ("hour 24", '{"cooldown_until": "2026-10-19T24:00:00Z"}'),
    ("month 13", '{"cooldown_until": "2026-13-01T00:00:00Z"}'),
    ("year 0", '{"cooldown_until": "0000-01-01T00:00:00Z"}'),
    ("year 1", '{"cooldown_until": "0001-01-01T00:00:00Z"}'),
    ("something after the Z", '{"cooldown_until": "2026-10-19T05:30:00ZZ"}'),
    ("a list", '[1]'),
    ("a text", '"x"'),
    ("a number", '1'),
    ("not JSON", "not json"),
]


def state_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cases = list(STATE_CASES)
    for case, kv in SEEDED:
        cases.append((f"a record that reads: {case}", "ug", kv, [
            ["state", None], ["cooling", NOW], ["error", NOW, "502"], ["block", NOW, "403"], ["ok", later(NOW, days=40)]]))
    records = []
    for case, provider, kv, steps in cases:
        fresh(conn, kv={f"provider:{provider}": kv} if kv is not None else None)
        records.append({"fn": "caracole.health", "case": case, "kw": {"provider": provider, "kv": kv, "steps": steps},
                        "out": run_steps(conn, provider, steps)})
    return records


def test_state_jsonl(conn):
    records = state_records(conn)
    seeded = {r["case"].removeprefix("a record that reads: "): r["out"] for r in records}
    assert seeded["twenty-two strikes: the next cooldown ends after 9999"][3:] == [{"err": "OverflowError"}]
    assert seeded["strikes below zero"][3]["state"]["cooldown_until"] == "2026-11-04T02:00:00+00:00"  # 12 h + 2 h
    assert seeded["not JSON"] == [{"err": "JSONDecodeError"}]
    assert seeded["strikes after a separator control, which int() keeps"] == [{"err": "ValueError"}]
    assert seeded["strikes after an em space, which int() strips"][0]["state"]["strikes"] == 5
    assert seeded["strikes NaN"] == [{"err": "ValueError"}]
    assert seeded["strikes too far below zero for a float"][3:] == [{"err": "OverflowError"}]
    kept = next(r["out"] for r in records if r["case"] == "a last_error that isn't text is written back as it was")
    assert '"last_error": {"status": 5, "why": [1, 2.5, true, null]}' in kept[1]["kv"]
    check(VECTORS / "health" / "state.jsonl", jsonl(records, corpus="health/state", made_by=MADE_BY))


# --- health/answered.jsonl and events.jsonl ---------------------------------------------------------------------

RUN = "lookup:2026-11-03T12:00:00Z"
URL = "https://tabs.ultimate-guitar.com/tab/1"


def event(decision: str, *, run: str = RUN, provider: str = "ug", at_: str = NOW, status: int | None = 200,
          message: str | None = None, url: str | None = URL) -> list[Any]:
    return [run, at_, provider, url, status, decision, message]


ANSWERED: list[tuple[str, list[list[Any]], str, str, int]] = [
    ("no event, one request", [], RUN, "ug", 1),
    ("no event, no request", [], RUN, "ug", 0),
    ("one answer", [event("ok")], RUN, "ug", 1),
    ("an error of two", [event("ok"), event("error", status=502)], RUN, "ug", 2),
    ("every request failed", [event("error", status=502), event("blocked", status=403)], RUN, "ug", 2),
    ("more failures than requests", [event("error", status=None, message="timeout")] * 3, RUN, "ug", 2),
    ("another run's failures", [event("error", run="2026-11-03T03:30:00Z")] * 2, RUN, "ug", 1),
    ("another provider's failures", [event("blocked", provider="lrclib")] * 2, RUN, "ug", 1),
    ("decisions that are no failure", [event("cached"), event("robots", status=None), event("not_modified", status=304)],
     RUN, "ug", 1),
    ("a run named like another", [event("error", run="lookup:%")], RUN, "ug", 1),
    ("a run id with LIKE's signs", [event("error", run="lookup:%")], "lookup:%", "ug", 1),
    ("the case of a run id", [event("error", run=RUN.upper())], RUN, "ug", 1),
    ("requests below zero", [], RUN, "ug", -1),
]


def test_answered_jsonl(conn):
    records = []
    for case, events, run, provider, requests in ANSWERED:
        fresh(conn, events)
        records.append({"fn": "caracole.health.answered_any", "case": case,
                        "kw": {"events": events, "run": run, "provider": provider, "requests": requests},
                        "out": health.answered_any(conn, run, provider, requests)})
    assert [r["out"] for r in records[:5]] == [True, False, True, True, False]
    check(VECTORS / "health" / "answered.jsonl", jsonl(records, corpus="health/answered", made_by=MADE_BY))


EVENTS: list[tuple[str, str, list[str], list[list[Any]]]] = [
    ("a lookup's requests", RUN, [NOW, later(NOW, seconds=1)], [
        ["ug", URL, 200, "ok", None], ["ug", URL + "?x=1", 404, "ok", None]]),
    ("no status, a message", "2026-11-03T03:30:00Z", ["2026-11-03T03:31:07.654321Z"], [
        ["lrclib", "https://lrclib.net/api/get?artist_name=Soda+Stereo", None, "error", "ConnectTimeout: timed out"]]),
    ("every decision", RUN, [NOW] * 6, [
        ["ug", URL, 200, "ok", None], ["ug", URL, 304, "not_modified", None], ["ug", URL, 403, "blocked", "HTTP 403"],
        ["ug", URL, 502, "error", "HTTP 502"], ["ug", URL, None, "cached", None], ["ug", URL, None, "robots", "/tab/print?"]]),
    ("text beyond ASCII", "lookup:lacuerda-search:2026-11-03T12:00:00Z", ["2026-12-31T23:59:59.999999Z"], [
        ["lacuerda", "https://acordes.lacuerda.net/busca.php?exp=m%C3%BAsica", 200, "ok", "música 宋冬野 🎸"]]),
]


def test_events_jsonl(conn):
    records = []
    for case, run, clock, events in EVENTS:
        fresh(conn)
        times = iter(clock)
        log = health.EventLog(conn, run, clock=lambda times=times: at(next(times)))
        for e in events:
            log(Event(*e))
        rows = conn.execute("SELECT run, at, provider, url, status, decision, message FROM events ORDER BY id").fetchall()
        records.append({"fn": "caracole.health.EventLog", "case": case,
                        "kw": {"run": run, "clock": clock, "events": events}, "out": [list(r) for r in rows]})
    assert records[1]["out"][0][1] == "2026-11-03T03:31:07Z"
    check(VECTORS / "health" / "events.jsonl", jsonl(records, corpus="health/events", made_by=MADE_BY))


# --- pace/ ------------------------------------------------------------------------------------------------------


def test_run_id_jsonl():
    nows = [NOW, "2026-11-03T12:00:00.999999Z", "2026-01-01T00:00:00Z", "2026-12-31T23:59:59.5Z", "1999-02-28T07:08:09Z",
            "9999-12-31T23:59:59.999999Z", "0001-01-01T00:00:00Z", "2028-02-29T12:34:56Z"]
    records = [{"fn": "caracole.commands._common.lookup_run_id", "args": [now],
                "out": _common.lookup_run_id(at(now))} for now in nows]
    assert records[1]["out"] == "lookup:2026-11-03T12:00:00Z"
    check(VECTORS / "pace" / "run_id.jsonl", jsonl(records, corpus="pace/run_id", made_by=MADE_BY))


HOUR_AGO = later(NOW, hours=-1)


def lookups(n: int, *, provider: str = "ug", at_: str = NOW, decision: str = "ok",
            run: str = RUN) -> list[list[Any]]:
    """``n`` requests alike: one row, its count the eighth element when it is more than one."""
    row = event(decision, provider=provider, at_=at_, run=run)
    return [row + [n] if n > 1 else row]


COUNT_EVENTS = (
    lookups(2) + lookups(1, at_=HOUR_AGO) + lookups(1, at_=later(HOUR_AGO, seconds=-1))
    + lookups(1, decision="not_modified") + lookups(1, decision="blocked") + lookups(1, decision="error")
    + lookups(1, decision="cached") + lookups(1, decision="robots")
    + lookups(2, run="lookup:lacuerda-search:2026-11-03T11:30:00Z", provider="lacuerda")
    + lookups(1, run="lookup:2026-11-03T11:00:00Z", provider="lacuerda")
    + lookups(3, run="2026-11-03T03:30:00Z", at_="2026-11-03T03:31:00Z")
    + lookups(1, run="2026-11-03T03:30:00Z", at_="2026-11-02T23:59:59Z")
    + lookups(1, run="LOOKUP:2026-11-03T11:59:00Z", at_="2026-11-03T11:59:00Z")
    + lookups(1, run="lookupx", at_="2026-11-03T11:59:00Z")
    + lookups(1, at_="2026-11-03 11:30:00", provider="lrclib") + lookups(1, at_="2026-11-03T00:00:00Z", provider="lrclib")
    + lookups(1, at_="2026-11-03T12:00:00.5Z", provider="lrclib") + lookups(1, at_="2026-11-04T00:00:00Z", provider="lrclib")
    + lookups(2, provider="megalobiz", run="2026-11-03T03:30:00Z", at_="2026-11-03T04:00:00Z")
)

COUNTS: list[tuple[str, str, str, str | None]] = [
    ("ug within the hour", "ug", NOW, None),
    ("ug an hour later", "ug", later(NOW, hours=1), None),
    ("ug with microseconds", "ug", "2026-11-03T12:00:00.999999Z", None),
    ("ug a second earlier", "ug", later(NOW, seconds=-1), None),
    ("lacuerda's lookups", "lacuerda", NOW, None),
    ("lacuerda's searches", "lacuerda", NOW, "lookup:lacuerda-search:"),
    ("a run named with LIKE's signs", "ug", NOW, "lookup_"),
    ("a run matched without case", "ug", NOW, "LOOKUP:"),
    ("lrclib's odd times", "lrclib", NOW, None),
    ("no event of the provider", "gtptabs", NOW, None),
    ("megalobiz's nightly run", "megalobiz", NOW, None),
]


def test_counts_jsonl(conn):
    fresh(conn, COUNT_EVENTS)
    records = []
    for case, provider, now, run in COUNTS:
        kw: dict[str, Any] = {"events": COUNT_EVENTS, "provider": provider, "now": now}
        if run is not None:
            kw["run"] = run
            used = _common.lookup_requests_used(conn, provider, at(now), run=run)
        else:
            used = _common.lookup_requests_used(conn, provider, at(now))
        records.append({"fn": "caracole.commands._common.lookup_requests_used", "case": case, "kw": kw, "out": used})
    for case, provider, now in [
        ("ug today", "ug", NOW), ("ug just before midnight", "ug", "2026-11-03T23:59:59.999999Z"),
        ("ug the day after", "ug", "2026-11-04T00:00:00Z"), ("ug the day before", "ug", "2026-11-02T23:59:59Z"),
        ("lrclib's odd times", "lrclib", NOW), ("lrclib at midnight", "lrclib", "2026-11-04T00:00:00Z"),
        ("megalobiz today", "megalobiz", NOW), ("lacuerda today", "lacuerda", NOW), ("no event", "gtptabs", NOW),
    ]:
        records.append({"fn": "caracole.commands._common.requests_today", "case": case,
                        "kw": {"events": COUNT_EVENTS, "provider": provider, "now": now},
                        "out": _common.requests_today(conn, provider, at(now))})
    by_case = {r["case"]: r["out"] for r in records}
    assert by_case["ug within the hour"] == 7 and by_case["lacuerda's searches"] == 2
    check(VECTORS / "pace" / "counts.jsonl", jsonl(records, corpus="pace/counts", made_by=MADE_BY))


POLICIES: list[tuple[str, str, dict[str, dict[str, Any]], list[list[Any]]]] = [
    ("ug with no lookup this hour", "ug", {}, []),
    ("ug with 57 lookup requests this hour", "ug", {}, lookups(57)),
    ("ug with 60", "ug", {}, lookups(60)),
    ("ug with 70: never below none", "ug", {}, lookups(70)),
    ("ug's nightly run counts for no lookup", "ug", {}, lookups(70, run="2026-11-03T03:30:00Z")),
    ("an hour's lookups below the song's", "lrclib", {"lrclib": {"lookup_requests": 10, "lookup_per_hour": 8}}, []),
    ("a lookup's pace of none", "gtptabs", {"gtptabs": {"lookup_delay": [0, 0]}}, []),
    ("megalobiz with no request today", "megalobiz", {}, []),
    ("megalobiz with 898 today", "megalobiz", {}, lookups(898, provider="megalobiz", run="2026-11-03T03:30:00Z",
                                                          at_="2026-11-03T04:00:00Z")),
    ("megalobiz with 900 today", "megalobiz", {}, lookups(900, provider="megalobiz", run="2026-11-03T03:30:00Z",
                                                          at_="2026-11-03T04:00:00Z")),
    ("megalobiz with 901 today, yesterday's apart", "megalobiz", {"megalobiz": {"per_day": 905}},
     lookups(901, provider="megalobiz", run="2026-11-03T03:30:00Z", at_="2026-11-03T04:00:00Z")
     + lookups(50, provider="megalobiz", run="2026-11-02T03:30:00Z", at_="2026-11-02T04:00:00Z")),
    ("a day's cap of 3, two sent", "lrclib", {"lrclib": {"per_day": 3}}, lookups(2, provider="lrclib")),
    ("azlyrics with no budget", "azlyrics", {}, lookups(3, provider="azlyrics")),
    ("azlyrics with a day's cap", "azlyrics", {"azlyrics": {"per_day": 1000}}, lookups(3, provider="azlyrics")),
    ("ytimg", "ytimg", {}, []),
]


def test_policy_jsonl(conn, cfg):
    records = []
    for case, provider, overrides, events in POLICIES:
        fresh(conn, events)
        providers = {name: replace(policy, **{k: tuple(v) if isinstance(v, list) else v
                                              for k, v in overrides.get(name, {}).items()})
                     for name, policy in config.DEFAULT_PROVIDERS.items()}
        c = replace(cfg, providers=providers)
        now = at(NOW)
        lookup = _common.lookup_policy(c, conn, provider, now)
        records.append({"fn": "caracole.commands._common.lookup_policy", "case": case,
                        "kw": {"providers": overrides, "events": events, "provider": provider, "now": NOW},
                        "out": {"lookup_policy": policy_fields(lookup),
                                "within_the_day": policy_fields(_common.within_the_day(conn, provider, lookup, now)),
                                "bulk_within_the_day": policy_fields(
                                    _common.within_the_day(conn, provider, c.provider(provider), now))}})
    by_case = {r["case"]: r["out"] for r in records}
    assert by_case["ug with 57 lookup requests this hour"]["lookup_policy"]["budget"] == 3
    assert by_case["megalobiz with 898 today"]["bulk_within_the_day"]["budget"] == 2
    check(VECTORS / "pace" / "policy.jsonl", jsonl(records, corpus="pace/policy", made_by=MADE_BY))


LAST_EVENTS = (
    lookups(1, provider="ug", at_="2026-11-03T11:59:58Z") + lookups(1, provider="ug", at_="2026-11-03T11:59:59Z",
                                                                    decision="error")
    + lookups(1, provider="ug", at_="2026-11-03T12:00:30Z", decision="cached")
    + lookups(1, provider="lrclib", at_="2026-11-03T11:00:00Z")
    + lookups(1, provider="lrclib", at_="2026-11-03T11:30:00")  # the greater text, which no stamp reads
    + lookups(1, provider="lacuerda", at_="2026-11-03T5:6:7Z")  # strptime's single digits
    + lookups(1, provider="gametabs", at_="2026-11-03T11:59:59Z", decision="robots")
)

FLOAT_TEXTS = [
    "1762171199.250", "1762171199", " 1762171199.5\n", "1_762_171_199.5", "1e9", "+5", "-5.", ".5", "1.e5",
    "-.5e-3", "1e1_0", "inf", "-iNfInItY", "+INF", "nan", "-nan", "1e400", "", " ", ".", "1__0", "_1", "1_",
    "1_e10", "1e_10", "1._5", "0x10", "1.5f", "1d", "infinityx", "+-1", "1e", "e5", "abc", "١٢٣", "١_٢", "５.５",
    "\u2003 7 \u2003", "\u00a07", "7\u200b", "1 0", "NaN", "Infinity",
]


def test_last_request_jsonl(conn):
    records = []
    cases: list[tuple[str, str | None, str]] = [(f"kv {text!r}", text, "ug") for text in FLOAT_TEXTS]
    cases += [("no kv: ug's last sent request", None, "ug"), ("no kv: a time that is no stamp", None, "lrclib"),
              ("no kv: single digits", None, "lacuerda"), ("no kv: nothing sent", None, "gametabs"),
              ("no kv: no event", None, "gtptabs"), ("a kv that isn't a float: the events", "soon", "lrclib")]
    for case, kv, provider in cases:
        fresh(conn, LAST_EVENTS, {f"http:last_request:{provider}": kv} if kv is not None else None)
        value = _common._last_request(conn, provider)
        records.append({"fn": "caracole.commands._common._last_request", "case": case,
                        "kw": {"kv": kv, "events": LAST_EVENTS, "provider": provider},
                        "out": None if value is None else number(value)})
    by_case = {r["case"]: r["out"] for r in records}
    assert by_case["no kv: ug's last sent request"] == at("2026-11-03T11:59:59Z").timestamp()
    assert by_case["kv '١_٢'"] == 12.0 and by_case["kv 'abc'"] == by_case["no kv: ug's last sent request"]
    check(VECTORS / "pace" / "last_request.jsonl", jsonl(records, corpus="pace/last_request", made_by=MADE_BY))


PAUSES: list[tuple[str, str | None, str, list[float], float, float]] = [
    ("no request yet", None, "gtptabs", [2.5, 5.0], 0.5, 1000.0),
    ("a second after the last, half a pause", "999.0", "ug", [2.5, 5.0], 0.5, 1000.0),
    ("long after the last", "100.0", "ug", [2.5, 5.0], 0.99, 1000.0),
    ("exactly the pause", "996.25", "ug", [2.5, 5.0], 0.5, 1000.0),
    ("the clock set back: one pause at most", "2000.0", "ug", [2.5, 5.0], 0.5, 1000.0),
    ("a lookup's pace", "1762171199.875", "ug", [0.125, 0.375], 0.3, 1762171200.0),
    ("a lookup's, the last request the same instant", "1762171200.0", "ug", [0.125, 0.375], 0.0, 1762171200.0),
    ("no pause at all", "1762171200.0", "azlyrics", [0.0, 0.0], 0.7, 1762171200.0),
    ("no pause, the clock set back", "1762171300.0", "azlyrics", [0.0, 0.0], 0.7, 1762171200.0),
    ("a draw near one", "1762171199.9", "lrclib", [0.25, 0.5], 0.999999, 1762171200.0),
    ("the last request from the events", None, "ug", [2.5, 5.0], 0.25, at("2026-11-03T12:00:01Z").timestamp()),
    ("an infinite last request", "inf", "ug", [2.5, 5.0], 0.5, 1000.0),
    ("a last request that is no number", "nan", "ug", [2.5, 5.0], 0.5, 1000.0),
    ("a fraction a float can't hold", "1762171199.1", "lrclib", [0.25, 0.5], 0.1, 1762171199.3),
]


def test_pause_jsonl(conn, monkeypatch):
    records = []
    for case, kv, provider, delay, u, wall in PAUSES:
        fresh(conn, LAST_EVENTS, {f"http:last_request:{provider}": kv} if kv is not None else None)
        slept: list[float] = []
        monkeypatch.setattr(_common, "random", types.SimpleNamespace(uniform=lambda a, b, u=u: a + (b - a) * u))
        monkeypatch.setattr(_common, "time", types.SimpleNamespace(time=lambda wall=wall: wall))
        monkeypatch.setattr(_common, "sleep", slept.append)
        _common._pause_after_last_request(conn, provider, tuple(delay))
        records.append({"fn": "caracole.commands._common._pause_after_last_request", "case": case,
                        "kw": {"kv": kv, "events": LAST_EVENTS, "provider": provider, "delay": delay, "u": u,
                               "wall": wall},
                        "out": [number(s) for s in slept]})
    by_case = {r["case"]: r["out"] for r in records}
    assert by_case["a second after the last, half a pause"] == [2.75]
    assert by_case["the clock set back: one pause at most"] == [5.0]
    check(VECTORS / "pace" / "pause.jsonl", jsonl(records, corpus="pace/pause", made_by=MADE_BY))
