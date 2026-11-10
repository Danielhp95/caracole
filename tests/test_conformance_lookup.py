"""A lookup's frame, its envelope and its words, for the phone: what get.py's ``_Lookup`` answers when a site is off,
blocked, cooling, spent or failing, how it keeps half of an hour's lookups for sheets, how its sheet and lyrics stages
put their sites' answers together, and the lines ``caracole get`` prints, written for the Kotlin port's core.lookup
(``InteractiveAsk``, ``LookupWords``, ``Lookup``) to agree with (docs/superpowers/plans/2026-11-03-android-port-m4-m6.md,
lane lookup).

Each record's database starts with no event and no kv record of politeness but its own (``kv``, ``{key: text}``, and
``events``, rows of the table as tests/test_conformance_health.py writes them: ``[run, at, provider, url, status,
decision, message]``, an eighth element the row's count); its config is ``config.DEFAULT_PROVIDERS`` with
``providers``' fields over theirs (``{name: {field: value}}``, config.py's names). A stage's end is get.py's: a text
(the site answered: ``done`` with those words) or ``[state, detail]``. Times are UTC stamps.

**Vectors**:

- lookup/words.jsonl:
  - ``{fn: "caracole.get", case: "constants", out}``: get.py's STAGES, NAMES, SHEETS_SHARE, SHEET_FROM and the
    stages' words other lanes and caracole serve read (MATCH_NOT_FOUND, GTPTABS_KEPT, HARPTABS_KEPT, GAMETABS_KEPT,
    NOT_IN_INDEX), and the words of a caracole with no PDFs (ADDED, NO_PDFS, PAGES_MADE, LIBRARY_PAGE);
  - ``{fn: "caracole.get._Lookup._then", kw: {out, then, has_lyrics}, out}``: the lyrics stage's end once one more
    site was asked after those before it (``then`` null: there was nothing to ask it), the song's lyrics found or not
    by then;
  - ``{fn: "caracole.get._Lookup.sheet", kw: {picked, kept, ug, lacuerda}, out: {sheet,
    lacuerda_stage, asked, running}}``: the sheet stage's order over its sites' answers, then the lacuerda stage's:
    ``picked`` whether the song has a LaCuerda pick, ``kept`` the sheet it keeps before (null, "ug" or "lacuerda": a
    LaCuerda sheet is the pick's), and each site's scripted answer ``{end, asked, keeps}`` (``asked``: whether the
    site was asked, so its work ran; ``keeps``: the sheet it keeps then, "ug" or "lacuerda"; LaCuerda answers the
    lacuerda stage as it would the sheet's); ``asked`` lists ``provider:how`` in order (``asking``, or ``after`` for
    ``after_the_sheet``), ``running`` the sheet stage's running details;
  - ``{fn: "caracole.get._Lookup.pdf"}``, ``…lacuerda`` (asked already) and ``…songbooks``: the frame's own words;
  - ``{fn: "caracole.commands.get._Lines", kw: {library, events}, out}``: the lines ``caracole get`` prints for
    the events of a lookup (``["stage", name, state, detail]``, ``["readable", files, seconds]``, ``["flush"]``);
  - ``{fn: "caracole.commands.get._totals", kw: {requests, seconds, refused}, out}``, ``requests`` each site's
    ``[provider, count]`` in the order the lookup made its clients.
- lookup/asking.jsonl: ``{fn: "caracole.get._Lookup.asking", case, kw: {provider, providers, kv, events, now, blocked,
  failed, kept_for_sheets, song, outcome}, out: {end, kv, ug_dirty, blocked, failed}}``: one site asked, ``outcome``
  what its work did (``{"returns": end}`` or ``{"raises": {class, ...}}``: an http.py error's ``provider``, ``url``,
  ``status``, ``message``; a site's parse error's ``message`` and ``url``; ``SharedFolder``'s two songs as ``[artist,
  title]`` and the file's ``name``; ``BudgetExhausted``'s ``provider``), the lookup's song ``{artist, title,
  match_decision, ug_dirty}`` or null, its client made at the lookup's policy of ``now``; ``out`` the end, the
  provider's kv ``provider:<name>`` after (null: none), the song's ``ug_dirty`` after (null: no song), and the sites
  blocked and failed in the lookup after.
- lookup/after_the_sheet.jsonl: ``{fn: "caracole.get._Lookup.after_the_sheet", case, kw: {provider, providers, kv,
  events, now, requests_made, work}, out: {end, left, budget, kept_for_sheets}}``: what follows the sheet asked
  within SHEETS_SHARE of the hour's lookup requests, the provider's client having sent ``requests_made`` already;
  ``work`` ``returns`` (its words, "asked") or ``spends`` (BudgetExhausted); ``out`` the end, ``left`` (the hour's
  requests the share leaves), the budget the work saw (null: it didn't run) and whether the client was held to the
  share.
"""

from __future__ import annotations

import math
import sqlite3
import types
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import add_song

from caracole import config, get
from caracole.commands import _common
from caracole.commands import get as get_cmd
from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError, ProviderUnavailable, RobotsClosed
from helpers.corpus import VECTORS, check, jsonl

MADE_BY = "tests/test_conformance_lookup.py"
NOW = "2026-11-03T12:00:00Z"
RUN = "lookup:2026-11-03T12:00:00Z"
UG_URL = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"
LRCLIB_URL = "https://lrclib.net/api/get?artist_name=Radiohead&track_name=Creep"
LACUERDA_URL = "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera.shtml"


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def fresh(conn: sqlite3.Connection, events: list[list[Any]] = (), kv: dict[str, str] | None = None) -> None:
    """The record's database: no event, no kv record of politeness and no song but its own."""
    conn.execute("DELETE FROM events")
    conn.execute("DELETE FROM kv WHERE key LIKE 'provider:%' OR key LIKE 'http:last_request:%'")
    conn.execute("DELETE FROM songs")
    for row in events:
        for _ in range(row[7] if len(row) > 7 else 1):
            conn.execute("INSERT INTO events (run, at, provider, url, status, decision, message) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", row[:7])
    for key, value in (kv or {}).items():
        conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (key, value))


def lookups(n: int, *, provider: str = "ug", at_: str = NOW, run: str = RUN) -> list[list[Any]]:
    """``n`` lookup requests alike that the provider answered: one row, its count the eighth element."""
    row = [run, at_, provider, f"https://example.invalid/{provider}", 200, "ok", None]
    return [row + [n] if n > 1 else row]


def configured(cfg, overrides: dict[str, dict[str, Any]]):
    providers = {name: replace(policy, **{k: tuple(v) if isinstance(v, list) else v
                                          for k, v in overrides.get(name, {}).items()})
                 for name, policy in config.DEFAULT_PROVIDERS.items()}
    return replace(cfg, providers=providers)


def lookup_of(cfg, conn: sqlite3.Connection, now: str = NOW) -> get._Lookup:
    lk = get._Lookup(cfg, get.LookupRequest("Radiohead", "Creep"), get.Progress(), runner=None, now=at(now),
                     clock=lambda: 0.0)
    lk.conn = conn
    return lk


def ended(out: tuple[str, str] | str) -> list[str] | str:
    return list(out) if isinstance(out, tuple) else out


def frozen(monkeypatch, now: str) -> None:
    """_common's clock at ``now``: the hour's lookups counted then, as the phone's lookup counts them."""
    fixed = at(now)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)

    monkeypatch.setattr(_common, "datetime", Frozen)


def interactive_policy(cfg, conn: sqlite3.Connection, provider: str, now: str):
    """The policy ``make_client(..., interactive=True)`` gives a lookup's client at ``now``: make_client itself, run
    with caracole's lock, its pause and its client class stood in for and its policies' clock at ``now``, so that a
    change to how it makes a lookup's policy changes these vectors."""
    from unittest import mock

    made: dict[str, Any] = {}

    class Made:
        def __init__(self, provider, policy, *_args, **_kwargs):
            made["policy"] = policy

    lookup_policy, within_the_day = _common.lookup_policy, _common.within_the_day
    with mock.patch.object(_common, "_acquire", lambda *_a, **_k: None), \
            mock.patch.object(_common, "_release", lambda *_a, **_k: None), \
            mock.patch.object(_common, "_pause_after_last_request", lambda *_a, **_k: None), \
            mock.patch.object(_common, "_locked_client", lambda: Made), \
            mock.patch.object(_common, "lookup_policy",
                              lambda c, cn, p, _now=None: lookup_policy(c, cn, p, at(now))), \
            mock.patch.object(_common, "within_the_day",
                              lambda cn, p, policy, _now=None: within_the_day(cn, p, policy, at(now))):
        _common.make_client(cfg, conn, provider, RUN, interactive=True)
    return made["policy"]


class FakeClient:
    """A lookup's client as make_client(..., interactive=True) makes it at ``now`` (its policy make_client's own,
    ``interactive_policy``), which sends nothing itself."""

    def __init__(self, cfg, conn, provider: str, now: str, requests_made: int = 0):
        self.provider = provider
        self.policy = interactive_policy(cfg, conn, provider, now)
        self.requests_made = requests_made

    def close(self) -> None:
        pass


# --- lookup/asking.jsonl --------------------------------------------------------------------------------------------

COOLING = ('{"strikes": 1, "cooldown_until": "2026-11-04T14:00:00Z", "last_ok": null, "last_error": "403", '
           '"last_error_at": "2026-11-03T12:00:00Z"}')
COOLED = ('{"strikes": 1, "cooldown_until": "2026-11-03T11:59:59Z", "last_ok": null, "last_error": "403", '
          '"last_error_at": "2026-11-02T09:59:59Z"}')
TWO_STRIKES = ('{"strikes": 2, "cooldown_until": "2026-11-01T00:00:00Z", "last_ok": "2026-10-01T03:30:00Z", '
               '"last_error": "403", "last_error_at": "2026-10-29T22:00:00Z"}')
ACCEPTED = {"artist": "Radiohead", "title": "Creep", "match_decision": "accept", "ug_dirty": False}


def raised(cls: str, **fields: Any) -> dict[str, Any]:
    return {"raises": {"class": cls, **fields}}


def http_error(cls: str, provider: str, url: str | None = None, status: int | None = None,
               message: str | None = None) -> dict[str, Any]:
    return raised(cls, provider=provider, url=url, status=status, message=message)


ASKING: list[tuple[str, str, dict, dict, list, dict]] = [
    # case, provider, providers, kv, events, extra kw (blocked, failed, kept_for_sheets, song, outcome)
    ("a site that answers", "lrclib", {}, {}, [], {"outcome": {"returns": "found"}}),
    ("a site that has nothing to do", "gtptabs", {}, {}, [],
     {"outcome": {"returns": ["skipped", "no file wanted, or gtptabs.com's index doesn't know the artist"]}}),
    ("a site's own failure, as its work words it", "harptabs", {}, {}, [],
     {"outcome": {"returns": ["failed", "something of its own"]}}),
    ("a site off in caracole.toml", "megalobiz", {"megalobiz": {"enabled": False}}, {}, [],
     {"outcome": {"returns": "found"}}),
    ("UG blocked earlier in the lookup", "ug", {}, {}, [], {"blocked": ["ug"], "outcome": {"returns": "x"}}),
    ("LaCuerda failed earlier in the lookup", "lacuerda", {}, {}, [], {"failed": ["lacuerda"],
                                                                         "outcome": {"returns": "x"}}),
    ("off comes before blocked", "gametabs", {"gametabs": {"enabled": False}}, {}, [],
     {"blocked": ["gametabs"], "failed": ["gametabs"], "outcome": {"returns": "x"}}),
    ("blocked comes before failed", "harptabs", {}, {}, [], {"blocked": ["harptabs"], "failed": ["harptabs"],
                                                            "outcome": {"returns": "x"}}),
    ("another site blocked earlier", "lrclib", {}, {}, [], {"blocked": ["ug"], "outcome": {"returns": "found"}}),
    ("cooling down after a block", "ug", {}, {"provider:ug": COOLING}, [], {"outcome": {"returns": "x"}}),
    ("a cooldown over a second ago", "ug", {}, {"provider:ug": COOLED}, [], {"outcome": {"returns": "tab 4169"}}),
    ("a first block", "ug", {}, {}, [], {"outcome": http_error("ProviderBlocked", "ug", UG_URL, 403, "HTTP 403")}),
    ("a third block in a row", "ug", {}, {"provider:ug": TWO_STRIKES}, [],
     {"outcome": http_error("ProviderBlocked", "ug", UG_URL, 403, "HTTP 403")}),
    ("a challenge page", "azlyrics", {}, {}, [],
     {"outcome": http_error("ProviderBlocked", "azlyrics", "https://www.azlyrics.com/r/radiohead.html", 200,
                            "a challenge page")}),
    ("a block with no status", "lrclib", {}, {}, [],
     {"outcome": http_error("ProviderBlocked", "lrclib", None, None, "rate limited")}),
    ("the lookup's requests spent", "ug", {}, {}, [], {"outcome": raised("BudgetExhausted", provider="ug")}),
    ("this hour's lookups spent", "ug", {}, {}, lookups(57), {"outcome": raised("BudgetExhausted", provider="ug")}),
    ("the hour spent to the last request", "lrclib", {}, {}, lookups(194, provider="lrclib"),
     {"outcome": raised("BudgetExhausted", provider="lrclib")}),
    ("an hour of a smaller share", "lacuerda", {"lacuerda": {"lookup_requests": 4, "lookup_per_hour": 10}}, {},
     lookups(7, provider="lacuerda"), {"outcome": raised("BudgetExhausted", provider="lacuerda")}),
    ("kept for sheets", "ug", {}, {}, [], {"kept_for_sheets": ["ug"],
                                          "outcome": raised("BudgetExhausted", provider="ug")}),
    ("kept for sheets of another site", "lacuerda", {}, {}, [], {"kept_for_sheets": ["ug"],
                                                                  "outcome": raised("BudgetExhausted",
                                                                                    provider="lacuerda")}),
    ("Megalobiz's day spent", "megalobiz", {}, {},
     lookups(900, provider="megalobiz", run="2026-11-03T03:30:00Z", at_="2026-11-03T04:00:00Z"),
     {"outcome": raised("BudgetExhausted", provider="megalobiz")}),
    ("a server error", "lrclib", {}, {}, [],
     {"outcome": http_error("ProviderError", "lrclib", LRCLIB_URL, 502, "HTTP 502")}),
    ("a timeout", "lacuerda", {}, {}, [],
     {"outcome": http_error("ProviderError", "lacuerda", LACUERDA_URL, None, "ReadTimeout: timed out")}),
    ("an error with nothing but its provider", "gtptabs", {}, {}, [], {"outcome": http_error("ProviderError",
                                                                                           "gtptabs")}),
    ("too many errors", "harptabs", {}, {}, [],
     {"outcome": http_error("ProviderUnavailable", "harptabs", None, None, "3 errors in a row")}),
    ("robots.txt closes the page", "ug", {}, {}, [],
     {"outcome": http_error("RobotsClosed", "ug", "https://tabs.ultimate-guitar.com/tab/print?id=1", None,
                            "/tab/print?")}),
    ("a page that won't parse", "ug", {}, {}, [],
     {"outcome": http_error("PageParseError", "ug", UG_URL, None, "no js-store")}),
    ("LaCuerda's page that won't parse", "lacuerda", {}, {}, [],
     {"outcome": raised("LaCuerdaParseError", message="its table isn't closed", url=LACUERDA_URL)}),
    ("gametabs.net's page that won't parse", "gametabs", {}, {}, [],
     {"outcome": raised("GameTabsParseError", message="no data-tab", url=None)}),
    ("LRCLIB's answer that isn't JSON", "lrclib", {}, {}, [],
     {"outcome": http_error("LrclibParseError", "lrclib", LRCLIB_URL, 200, "not JSON")}),
    ("a file where another song keeps one", "ug", {}, {}, [],
     {"song": ACCEPTED, "outcome": raised("SharedFolder", song=["Radiohead", "Creep"],
                                          other=["Radiohead", "Creep (Acoustic)"], name="sheet.txt")}),
    ("a block owes a matched song its fetch", "ug", {}, {}, [],
     {"song": ACCEPTED, "outcome": http_error("ProviderBlocked", "ug", UG_URL, 429, "HTTP 429")}),
    ("a cooldown owes it too", "ug", {}, {"provider:ug": COOLING}, [], {"song": ACCEPTED,
                                                                         "outcome": {"returns": "x"}}),
    ("a spent budget owes it too", "ug", {}, {}, [], {"song": ACCEPTED,
                                                      "outcome": raised("BudgetExhausted", provider="ug")}),
    ("an error owes it too", "ug", {}, {}, [], {"song": ACCEPTED,
                                                "outcome": http_error("ProviderError", "ug", UG_URL, 500, "HTTP 500")}),
    ("a pinned song is owed it", "ug", {}, {}, [],
     {"song": {**ACCEPTED, "match_decision": "pinned"}, "blocked": ["ug"], "outcome": {"returns": "x"}}),
    ("a song in review is owed nothing", "ug", {}, {}, [],
     {"song": {**ACCEPTED, "match_decision": "review"}, "blocked": ["ug"], "outcome": {"returns": "x"}}),
    ("a song not found is owed nothing", "ug", {}, {}, [],
     {"song": {**ACCEPTED, "match_decision": "not_found"}, "blocked": ["ug"], "outcome": {"returns": "x"}}),
    ("a song owed already", "ug", {}, {}, [],
     {"song": {**ACCEPTED, "ug_dirty": True}, "blocked": ["ug"], "outcome": {"returns": "x"}}),
    ("an answer owes nothing", "ug", {}, {}, [], {"song": ACCEPTED, "outcome": {"returns": "tab 4169 from UG"}}),
    ("another site's block owes UG nothing", "lrclib", {}, {}, [],
     {"song": ACCEPTED, "outcome": http_error("ProviderBlocked", "lrclib", LRCLIB_URL, 403, "HTTP 403")}),
]


def exception(conn: sqlite3.Connection, spec: dict[str, Any]) -> Exception:
    from caracole.gametabs import GameTabsParseError
    from caracole.lacuerda import LaCuerdaParseError
    from caracole.library import SharedFolder
    from caracole.lyrics import LrclibParseError
    from caracole.normalize import identity_key
    from caracole.songs import find_song, get_song
    from caracole.ug.page import PageParseError

    cls = spec["class"]
    errors = {"ProviderBlocked": ProviderBlocked, "ProviderError": ProviderError,
              "ProviderUnavailable": ProviderUnavailable, "RobotsClosed": RobotsClosed,
              "PageParseError": PageParseError, "LrclibParseError": LrclibParseError}
    if cls in errors:
        return errors[cls](spec["provider"], url=spec["url"], status=spec["status"], message=spec["message"])
    if cls == "LaCuerdaParseError":
        return LaCuerdaParseError(spec["message"], url=spec["url"])
    if cls == "GameTabsParseError":
        return GameTabsParseError(spec["message"], url=spec["url"])
    if cls == "BudgetExhausted":
        return BudgetExhausted(spec["provider"])
    if cls == "SharedFolder":
        song = find_song(conn, identity_key(*spec["song"])) or add_song(conn, *spec["song"])
        other = add_song(conn, *spec["other"])
        return SharedFolder(get_song(conn, song.id), get_song(conn, other.id), spec["name"])
    raise AssertionError(cls)


def asking_record(cfg, conn, case: str, provider: str, providers: dict, kv: dict, events: list,
                  extra: dict) -> dict[str, Any]:
    from caracole.songs import get_song, update_song

    fresh(conn, events, kv)
    c = configured(cfg, providers)
    lk = lookup_of(c, conn)
    lk.blocked = set(extra.get("blocked", ()))
    lk.failed = set(extra.get("failed", ()))
    lk.kept_for_sheets = set(extra.get("kept_for_sheets", ()))
    song = extra.get("song")
    if song is not None:
        s = add_song(conn, song["artist"], song["title"])
        update_song(conn, s.id, match_decision=song["match_decision"], ug_dirty=song["ug_dirty"])
        lk.song = get_song(conn, s.id)
    lk.client = lambda p: FakeClient(c, conn, p, NOW)
    outcome = extra["outcome"]

    def work(client) -> Any:
        if "raises" in outcome:
            raise exception(conn, outcome["raises"])
        return tuple(outcome["returns"]) if isinstance(outcome["returns"], list) else outcome["returns"]

    end = ended(lk.asking(provider, work))
    after = conn.execute("SELECT value FROM kv WHERE key = ?", (f"provider:{provider}",)).fetchone()
    return {"fn": "caracole.get._Lookup.asking", "case": case,
            "kw": {"provider": provider, "providers": providers, "kv": kv, "events": events, "now": NOW,
                   "blocked": extra.get("blocked", []), "failed": extra.get("failed", []),
                   "kept_for_sheets": extra.get("kept_for_sheets", []), "song": song, "outcome": outcome},
            "out": {"end": end, "kv": after[0] if after else None,
                    "ug_dirty": get_song(conn, lk.song.id).ug_dirty if song is not None else None,
                    "blocked": sorted(lk.blocked), "failed": sorted(lk.failed)}}


def test_asking_jsonl(cfg, conn, monkeypatch):
    frozen(monkeypatch, NOW)
    records = [asking_record(cfg, conn, *case) for case in ASKING]
    by_case = {r["case"]: r["out"] for r in records}
    assert by_case["a first block"]["end"] == [
        "skipped", "Ultimate Guitar blocked caracole (ug: 403: " + UG_URL + ": HTTP 403): no more requests to it until "
        "2026-11-04 14:00 UTC. Nothing was marked not found."]
    assert by_case["this hour's lookups spent"]["end"] == [
        "skipped", "this hour's 60 lookup requests to Ultimate Guitar are spent; the nightly run does the rest"]
    assert by_case["kept for sheets"]["end"][1].startswith("this hour's lookups have spent half of their 60")
    assert by_case["a block owes a matched song its fetch"]["ug_dirty"] is True
    assert by_case["a song in review is owed nothing"]["ug_dirty"] is False
    assert by_case["a file where another song keeps one"]["end"][0] == "failed"
    check(VECTORS / "lookup" / "asking.jsonl", jsonl(records, corpus="lookup/asking", made_by=MADE_BY))


# --- lookup/after_the_sheet.jsonl -----------------------------------------------------------------------------------

AFTER: list[tuple[str, str, dict, dict, list, int, str]] = [
    # case, provider, providers, kv, events, requests_made, work
    ("no lookup this hour", "ug", {}, {}, [], 0, "returns"),
    ("27 sent this hour: three left for what follows", "ug", {}, {}, lookups(27), 0, "returns"),
    ("27 sent: the three spent", "ug", {}, {}, lookups(27), 0, "spends"),
    ("29 sent: one left", "ug", {}, {}, lookups(29), 0, "spends"),
    ("30 sent: none left, nothing asked", "ug", {}, {}, lookups(30), 0, "returns"),
    ("35 sent: below none", "ug", {}, {}, lookups(35), 0, "returns"),
    ("none left, and cooling: the cooldown says why", "ug", {}, {"provider:ug": COOLING}, lookups(30), 0, "returns"),
    ("none left, and off", "lacuerda", {"lacuerda": {"enabled": False}}, {}, lookups(30, provider="lacuerda"), 0,
     "returns"),
    ("left, and cooling", "ug", {}, {"provider:ug": COOLING}, lookups(3), 0, "returns"),
    ("the sheet sent two, 25 this hour", "ug", {}, {}, lookups(25), 2, "returns"),
    ("the sheet sent two, 28 this hour", "ug", {}, {}, lookups(28), 2, "spends"),
    ("the sheet sent two, 27 this hour", "ug", {}, {}, lookups(27), 2, "returns"),
    ("an odd hour's share", "lacuerda", {"lacuerda": {"lookup_per_hour": 7, "lookup_requests": 6}}, {},
     lookups(1, provider="lacuerda"), 0, "spends"),
    ("an hour of one request", "lacuerda", {"lacuerda": {"lookup_per_hour": 1}}, {}, [], 0, "returns"),
    ("an hour of none", "lacuerda", {"lacuerda": {"lookup_per_hour": 0}}, {}, [], 0, "returns"),
    ("a lookup of more than the share", "ug", {"ug": {"lookup_requests": 40}}, {}, [], 0, "spends"),
    ("another provider's lookups count for none", "ug", {}, {}, lookups(40, provider="lacuerda"), 0, "returns"),
    ("an hour ago counts", "ug", {}, {}, lookups(30, at_="2026-11-03T11:00:00Z"), 0, "returns"),
    ("more than an hour ago counts for none", "ug", {}, {}, lookups(30, at_="2026-11-03T10:59:59Z"), 0, "returns"),
    ("the nightly run counts for none", "ug", {}, {}, lookups(30, run="2026-11-03T03:30:00Z"), 0, "returns"),
]


def after_record(cfg, conn, case: str, provider: str, providers: dict, kv: dict, events: list, requests_made: int,
                 work_does: str) -> dict[str, Any]:
    fresh(conn, events, kv)
    c = configured(cfg, providers)
    lk = lookup_of(c, conn)
    lk.client = lambda p: FakeClient(c, conn, p, NOW, requests_made)
    seen: list[int] = []

    def work(client) -> str:
        seen.append(client.policy.budget)
        if work_does == "spends":
            raise BudgetExhausted(provider)
        return "asked"

    end = ended(lk.after_the_sheet(provider, work))
    p = c.provider(provider)
    left = p.lookup_per_hour - math.ceil(p.lookup_per_hour * get.SHEETS_SHARE) - _common.lookup_requests_used(
        conn, provider, at(NOW))
    return {"fn": "caracole.get._Lookup.after_the_sheet", "case": case,
            "kw": {"provider": provider, "providers": providers, "kv": kv, "events": events, "now": NOW,
                   "requests_made": requests_made, "work": work_does},
            "out": {"end": end, "left": left, "budget": seen[0] if seen else None,
                    "kept_for_sheets": provider in lk.kept_for_sheets}}


def test_after_the_sheet_jsonl(cfg, conn, monkeypatch):
    frozen(monkeypatch, NOW)
    records = [after_record(cfg, conn, *case) for case in AFTER]
    by_case = {r["case"]: r["out"] for r in records}
    assert by_case["27 sent this hour: three left for what follows"] == {
        "end": "asked", "left": 3, "budget": 3, "kept_for_sheets": True}
    assert by_case["30 sent: none left, nothing asked"]["budget"] is None
    assert by_case["none left, and cooling: the cooldown says why"]["end"][1].startswith("Ultimate Guitar is cooling")
    assert by_case["the sheet sent two, 28 this hour"]["budget"] == 4
    check(VECTORS / "lookup" / "after_the_sheet.jsonl",
          jsonl(records, corpus="lookup/after_the_sheet", made_by=MADE_BY))


# --- lookup/words.jsonl ---------------------------------------------------------------------------------------------


def constants() -> dict[str, Any]:
    return {"fn": "caracole.get", "case": "constants", "out": {
        "STAGES": [list(s) for s in get.STAGES], "NAMES": get.NAMES, "SHEETS_SHARE": get.SHEETS_SHARE,
        "SHEET_FROM": get.SHEET_FROM, "MATCH_NOT_FOUND": get.MATCH_NOT_FOUND, "GTPTABS_KEPT": get.GTPTABS_KEPT,
        "HARPTABS_KEPT": get.HARPTABS_KEPT, "GAMETABS_KEPT": get.GAMETABS_KEPT, "NOT_IN_INDEX": get.NOT_IN_INDEX,
        "ADDED": get.ADDED, "NO_PDFS": get.NO_PDFS, "PAGES_MADE": get.PAGES_MADE, "LIBRARY_PAGE": get.LIBRARY_PAGE}}


LRCLIB_ENDS: list[Any] = [
    "found", "LRCLIB has none", "an instrumental", "already there",
    ("skipped", "LRCLIB is cooling down after a block, until 2026-11-04 14:00 UTC"),
    ("failed", "LRCLIB failed (lrclib: 502: " + LRCLIB_URL + ": HTTP 502); the nightly run tries again"),
    ("skipped", "this hour's 200 lookup requests to LRCLIB are spent; the nightly run does the rest"),
]
THEN_ENDS: list[Any] = [
    None, "timed lyrics from Megalobiz", "Megalobiz has no timed ones",
    ("failed", "Megalobiz failed (megalobiz: 500); the nightly run tries again"),
    ("skipped", "Megalobiz is off in caracole.toml"),
]


def then_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    from caracole.songs import get_song, update_song

    fresh(conn)
    song = add_song(conn, "Radiohead", "Creep")
    lk = get._Lookup(config.Config.__new__(config.Config), get.LookupRequest("Radiohead", "Creep"), get.Progress(),
                     runner=None, now=at(NOW), clock=lambda: 0.0)
    lk.conn = conn
    records = []
    for out in LRCLIB_ENDS:
        for then in THEN_ENDS:
            for has_lyrics in (True, False):
                update_song(conn, song.id, lyrics_status="found" if has_lyrics else "pending")
                lk.song = get_song(conn, song.id)
                said = lk._then(out, then)
                records.append({"fn": "caracole.get._Lookup._then",
                                "kw": {"out": ended(out), "then": ended(then) if then is not None else None,
                                       "has_lyrics": has_lyrics}, "out": ended(said)})
    return records


# The sheet stage's sites, scripted: each its end, whether it was asked (its work ran) and the sheet it keeps then.
def site(end: Any, *, asked: bool = True, keeps: str | None = None) -> dict[str, Any]:
    return {"end": ended(end) if not isinstance(end, str) else end, "asked": asked, "keeps": keeps}


UG_KEPT = site("tab 4169 from Ultimate Guitar", keeps="ug")
UG_NONE = site("Ultimate Guitar has no sheet to keep")
UG_READY = site(("skipped", get.NOT_IN_INDEX), asked=False)
UG_REVIEW = site(("skipped", "caracole isn't sure which Ultimate Guitar song this is: pick it on the lookup page, "
                             "or run caracole review"), asked=False)
UG_BLOCKED = site(("skipped", "Ultimate Guitar blocked caracole (ug: 403): no more requests to it until 2026-11-04 "
                              "14:00 UTC. Nothing was marked not found."))
UG_FAILED = site(("failed", "Ultimate Guitar failed (ug: 502); the nightly run tries again"))
UG_COOLING = site(("skipped", "Ultimate Guitar is cooling down after a block, until 2026-11-04 14:00 UTC"),
                  asked=False)
LC_KEPT = site("sheet kept from LaCuerda", keeps="lacuerda")
LC_MISSING = site("not on LaCuerda")
LC_NOT_FOR = site(("skipped", "not a song for LaCuerda: not Spanish, a complete sheet already, or asked this month"))
LC_PINNED = site(("skipped", "the Ultimate Guitar tab you pinned is kept over your LaCuerda pick"))
LC_HOLDS = site(("done", "the LaCuerda sheet you picked is the sheet already"))
LC_FAILED = site(("failed", "LaCuerda failed (lacuerda: 500); the nightly run tries again"))
LC_SPENT = site(("skipped", "the lookup's 6 requests to LaCuerda are spent; the nightly run does the rest"))
LC_COOLING = site(("skipped", "LaCuerda is cooling down after a block, until 2026-11-04 14:00 UTC"), asked=False)
LC_AGAIN = site("kept what it had")

SHEETS: list[tuple[str, bool, str | None, dict, dict]] = [
    # case, picked, kept before, ug, lacuerda
    ("UG's sheet", False, None, UG_KEPT, LC_KEPT),
    ("UG has none, LaCuerda's", False, None, UG_NONE, LC_KEPT),
    ("UG has none, nor LaCuerda", False, None, UG_NONE, LC_MISSING),
    ("UG has none, LaCuerda isn't for it", False, None, UG_NONE, LC_NOT_FOR),
    ("UG can't be asked, LaCuerda's", False, None, UG_READY, LC_KEPT),
    ("UG can't be asked, nor LaCuerda", False, None, UG_READY, LC_MISSING),
    ("in review, LaCuerda fails", False, None, UG_REVIEW, LC_FAILED),
    ("UG blocked, LaCuerda's", False, None, UG_BLOCKED, LC_KEPT),
    ("UG blocked, LaCuerda has none", False, None, UG_BLOCKED, LC_MISSING),
    ("UG failed, LaCuerda spent", False, None, UG_FAILED, LC_SPENT),
    ("UG cooling, LaCuerda cooling", False, None, UG_COOLING, LC_COOLING),
    ("a sheet kept before, UG has no better", False, "ug", UG_NONE, LC_AGAIN),
    ("a sheet kept before, UG blocked", False, "ug", UG_BLOCKED, LC_AGAIN),
    ("a LaCuerda sheet kept before", False, "lacuerda", UG_NONE, LC_AGAIN),
    ("your pick kept", True, None, UG_KEPT, LC_KEPT),
    ("your pick kept already", True, "lacuerda", UG_KEPT, LC_HOLDS),
    ("your pick missing, UG's", True, None, UG_KEPT, LC_MISSING),
    ("your pick failed, UG's", True, None, UG_KEPT, LC_FAILED),
    ("your pick failed, UG has none", True, None, UG_NONE, LC_FAILED),
    ("your pick under a pinned tab", True, "ug", UG_KEPT, LC_PINNED),
    ("your pick cooling, UG blocked", True, None, UG_BLOCKED, LC_COOLING),
    ("your pick spent, UG can't be asked", True, None, UG_READY, LC_SPENT),
    ("your pick waits, UG's kept before", True, "ug", UG_NONE, site(("skipped", "your pick on LaCuerda waits: it "
                                                                                "was asked for this month"))),
]


def sheet_record(conn: sqlite3.Connection, monkeypatch, case: str, picked: bool, kept: str | None, ug: dict,
                 lc: dict) -> dict[str, Any]:
    from caracole import songs

    fresh(conn)
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    reported: list[tuple[str, str, str]] = []

    class Heard(get.Progress):
        def stage(self, name: str, state: str, detail: str = "") -> None:
            reported.append((name, state, detail))

    lk = get._Lookup(config.Config.__new__(config.Config), get.LookupRequest("Soda Stereo", "De Música Ligera"),
                     Heard(), runner=None, now=at(NOW), clock=lambda: 0.0)
    lk.conn, lk.song = conn, song
    state = {"kept": kept}
    asked: list[str] = []
    monkeypatch.setattr(songs, "get_song", lambda _conn, _id: song)
    lk._picked = lambda: object() if picked else None
    lk._kept_sheet = lambda: state["kept"]
    lk._holds_pick = lambda: picked and state["kept"] == "lacuerda"
    lk._ug_ready = lambda: None
    script = {"ug": ug, "lacuerda": lc}

    def answer(provider: str, how: str) -> Any:
        s = script[provider]
        asked.append(f"{provider}:{how}")
        if s["asked"]:
            lk._sheet_from(provider)
        if s["keeps"] is not None:
            state["kept"] = s["keeps"]
        return tuple(s["end"]) if isinstance(s["end"], list) else s["end"]

    lk.asking = lambda provider, work: answer(provider, "asking")
    lk.after_the_sheet = lambda provider, work: answer(provider, "after")
    lk._check_readable = lambda: None
    lk.stage("sheet", lk.sheet)
    sheet_end = [lk.result.states["sheet"], lk.result.details["sheet"]]
    lk.stage("lacuerda", lk.lacuerda)
    lacuerda_end = [lk.result.states["lacuerda"], lk.result.details["lacuerda"]]
    return {"fn": "caracole.get._Lookup.sheet", "case": case,
            "kw": {"picked": picked, "kept": kept, "ug": ug, "lacuerda": lc},
            "out": {"sheet": sheet_end, "lacuerda_stage": lacuerda_end, "asked": asked,
                    "running": [d for n, s, d in reported if n == "sheet" and s == "running"]}}


def frame_records(conn: sqlite3.Connection, monkeypatch) -> list[dict[str, Any]]:
    """The frame's own words: the pdf stage with no sheet, LaCuerda asked again for the lacuerda stage, and the
    songbooks stage's."""
    from caracole import songbook

    records = []
    lk = get._Lookup(config.Config.__new__(config.Config), get.LookupRequest("Radiohead", "Creep"), get.Progress(),
                     runner=None, now=at(NOW), clock=lambda: 0.0)
    lk._kept_sheet = lambda: None
    records.append({"fn": "caracole.get._Lookup.pdf", "case": "no sheet yet", "out": ended(lk.pdf())})
    for said in (("done", "sheet kept from LaCuerda"), ("done", ""), ("skipped", "not on LaCuerda: x"),
                 ("failed", "LaCuerda failed (lacuerda: 500); the nightly run tries again")):
        lk.lacuerda_asked, lk.lacuerda_said = True, said
        records.append({"fn": "caracole.get._Lookup.lacuerda", "case": "asked already, for the sheet",
                        "kw": {"said": list(said)}, "out": ended(lk.lacuerda())})

    class Book:
        def __init__(self, name: str):
            self.name = name

    cases = [
        ("songbooks.toml can't be read", {"error": "line 3: a bad key"}),
        ("left to the job that makes them once", {"songbooks": False, "listing": ["Campfire"]}),
        ("no songbook lists it", {"listing": []}),
        ("made again", {"listing": ["Campfire", "Fogón"], "stats": {"rendered": 2}}),
        ("up to date", {"listing": ["Campfire"], "stats": {}}),
        ("a file that couldn't be made", {"listing": ["Campfire", "Fogón"], "stats": {"rendered": 1,
                                                                                     "failed": ["Fogón"]}}),
        ("waiting for a CJK font", {"listing": ["宋冬野"], "stats": {"font_error": "no CJK font: set CARACOLE_CJK_FONT"}}),
    ]
    for case, kw in cases:
        heard: list[tuple[str, str, str]] = []

        class Heard(get.Progress):
            def stage(self, name: str, state: str, detail: str = "") -> None:
                heard.append((name, state, detail))

        lk = get._Lookup(config.Config.__new__(config.Config),
                         get.LookupRequest("Radiohead", "Creep", songbooks=kw.get("songbooks", True)), Heard(),
                         runner=None, now=at(NOW), clock=lambda: 0.0)
        lk.cfg = types.SimpleNamespace(library_dir=Path("/library"))
        lk.overrides = None

        def load(_path, kw=kw):
            if "error" in kw:
                raise songbook.SongbookError(kw["error"])
            return []

        stats = kw.get("stats", {})
        monkeypatch.setattr(songbook, "load_songbooks", load)
        monkeypatch.setattr(songbook, "songbooks_listing", lambda *_a, kw=kw: [Book(n) for n in kw.get("listing", [])])
        monkeypatch.setattr(songbook, "render_songbooks", lambda *_a, stats=stats, **_k: types.SimpleNamespace(
            rendered=stats.get("rendered", 0), failed=stats.get("failed", []), font_error=stats.get("font_error")))
        monkeypatch.setattr("caracole.todo.write_pages", lambda *_a, **_k: None)
        end = ended(lk.songbooks())
        records.append({"fn": "caracole.get._Lookup.songbooks", "case": case, "kw": kw,
                        "out": {"end": end, "running": [d for n, s, d in heard if s == "running"]}})
    return records


LINES: list[tuple[str, list[list[Any]]]] = [
    ("a lookup, its sheet readable", [
        ["stage", "song", "running", ""], ["stage", "song", "done", "in the library"],
        ["stage", "match", "running", ""], ["stage", "match", "done", "matched to radiohead/creep"],
        ["stage", "sheet", "running", ""], ["stage", "sheet", "running", "from Ultimate Guitar"],
        ["stage", "sheet", "done", "tab 4169 from Ultimate Guitar"],
        ["readable", {"sheet": "Radiohead/Creep/sheet.txt"}, 2.04],
        ["stage", "pdf", "running", ""], ["stage", "pdf", "skipped", get.NO_PDFS],
        ["stage", "lyrics", "running", ""], ["stage", "lyrics", "done", "found"],
        ["stage", "ug", "running", ""], ["stage", "ug", "failed", "Ultimate Guitar failed (ug: 502); the nightly run "
                                                                  "tries again"],
        ["stage", "pages", "running", ""], ["stage", "pages", "done", get.LIBRARY_PAGE],
        ["stage", "songbooks", "running", ""], ["stage", "songbooks", "skipped", ""]]),
    ("a sheet with no page yet, then its page", [
        ["stage", "sheet", "running", ""], ["stage", "sheet", "done", "sheet kept from LaCuerda"],
        ["stage", "pdf", "running", ""],
        ["readable", {"sheet": "Soda Stereo/De Música Ligera/sheet.txt"}, 0.05],
        ["readable", {"sheet": "Soda Stereo/De Música Ligera/sheet.txt",
                      "viewer": "Soda Stereo/De Música Ligera/sheet.html"}, 1.25],
        ["stage", "pdf", "done", get.PAGES_MADE]]),
    ("a better sheet replaced it", [
        ["stage", "sheet", "done", "tab 1 from Ultimate Guitar"], ["readable", {"sheet": "A/B/sheet.txt"}, 1.0],
        ["readable", {"sheet": "A/B/sheet.txt"}, 9.95]]),
    ("a sheet that waits, said at the next stage", [
        ["stage", "sheet", "done", "tab 1 from Ultimate Guitar"], ["stage", "pdf", "running", ""]]),
    ("a sheet said at the end", [["stage", "sheet", "done", "tab 1 from Ultimate Guitar"], ["flush"]]),
    ("a refusal", [
        ["stage", "song", "running", ""], ["stage", "song", "failed", "Radiohead - Creep is ignored in overrides.toml: "
                                                                      "take it out of [ignore] to look it up"],
        ["stage", "match", "skipped", ""], ["stage", "sheet", "skipped", ""]]),
    ("a state with no detail", [["stage", "lacuerda", "skipped", ""], ["stage", "gtptabs", "done", ""]]),
    ("a stage of another command", [["stage", "audio", "done", "from YouTube"], ["stage", "search", "done", "x"]]),
    ("a rounding of the seconds", [["stage", "sheet", "done", "x"], ["readable", {"sheet": "a.txt"}, 0.25]]),
    ("half a tenth up", [["stage", "sheet", "done", "x"], ["readable", {"sheet": "a.txt"}, 0.35]]),
]


def lines_records(capsys) -> list[dict[str, Any]]:
    records = []
    for case, events in LINES:
        lines = get_cmd._Lines(Path("/library"), show=False, json_lines=False)
        for e in events:
            if e[0] == "stage":
                lines.stage(*e[1:])
            elif e[0] == "readable":
                lines.readable(e[1], e[2])
            else:
                lines.flush()
        out = capsys.readouterr().out.splitlines()
        records.append({"fn": "caracole.commands.get._Lines", "case": case,
                        "kw": {"library": "/library", "events": events}, "out": out})
    return records


TOTALS: list[tuple[str, dict[str, int], float, str | None]] = [
    ("no request", {}, 0.04, None),
    ("one request", {"ug": 1}, 1.0, None),
    ("each site's", {"ug": 3, "lrclib": 1, "lacuerda": 0, "megalobiz": 2}, 12.349, None),
    ("a site of no name", {"ytimg": 2}, 3.05, None),
    ("a refusal", {}, 0.0, "Radiohead - Creep is ignored in overrides.toml: take it out of [ignore] to look it up"),
    ("long", {"ug": 6}, 125.75, None),
]


def totals_records() -> list[dict[str, Any]]:
    records = []
    for case, requests, seconds, refused in TOTALS:
        result = get.LookupResult(requests=dict(requests), seconds=seconds, refused=refused)
        records.append({"fn": "caracole.commands.get._totals", "case": case,
                        "kw": {"requests": [list(item) for item in requests.items()], "seconds": seconds,
                               "refused": refused},
                        "out": get_cmd._totals(result)})
    return records


def test_words_jsonl(conn, monkeypatch, capsys):
    records = [constants()]
    records += then_records(conn)
    with pytest.MonkeyPatch.context() as mp:
        records += [sheet_record(conn, mp, *case) for case in SHEETS]
    records += frame_records(conn, monkeypatch)
    records += lines_records(capsys)
    records += totals_records()
    sheets = {r["case"]: r["out"] for r in records if r["fn"] == "caracole.get._Lookup.sheet"}
    assert sheets["UG has none, LaCuerda's"]["sheet"] == ["done", "sheet kept from LaCuerda"]
    assert sheets["UG has none, nor LaCuerda"]["sheet"] == ["skipped", "Ultimate Guitar has no sheet to keep"]
    assert sheets["UG's sheet"]["lacuerda_stage"] == ["done", "sheet kept from LaCuerda"]
    assert sheets["UG's sheet"]["asked"] == ["ug:asking", "lacuerda:after"]
    assert sheets["your pick missing, UG's"]["sheet"] == ["done", "not on LaCuerda; tab 4169 from Ultimate Guitar"]
    assert sheets["your pick kept"]["running"] == ["", "from LaCuerda"]
    check(VECTORS / "lookup" / "words.jsonl", jsonl(records, corpus="lookup/words", made_by=MADE_BY))
