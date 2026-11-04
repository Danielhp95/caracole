"""The library page's Requests tab, for the phone: what android/server's ``Feed``, ``LibraryPage`` and
``RequestsRoutes`` (lane requests-feed) read and check themselves against (``RequestsReplay``, ``FeedTest``).

- ``data/caracole/page/requests.json``, the phone's runtime data of the tab:
  - ``tab`` and ``panel``: library_page.py's ``_requests_tab`` and ``_requests_panel`` as caracole serve fills them in,
    the tab's count left as ``count`` (``__N__``), which the phone fills in with how many requests wait or run, or with
    nothing for none, as ``_requests_tab`` does: exported from the two functions, never retyped
    (``test_the_tab_is_requests_tab_for_every_count``);
  - ``zones``: what Python's ``%Z`` names each time zone's offsets (``stamps.shown(local=True)``: the C library's
    abbreviation, read from tzdata), ``{zone: [[offset in seconds, abbreviation, since], …]}`` (``zone_labels``), for
    every zone tzdata has and every offset it uses from ``WINDOW[0]`` to ``WINDOW[1]``, but those tzdata names by
    their numbers (``-03``, ``+0545``: ``numeric``), which the phone writes itself; java.time and ICU name zones
    otherwise ("GMT+01:00").
- ``vectors/web/requests.jsonl``, a record a call:
  - ``{"fn": "tables", "out": {"STATE_TEXT", "PRIMARY", "SEARCH", "PICK_STAGE", "PICK_STEP"}}``: feed.py's words;
  - ``{"fn": "caracole.web.feed._ordinal", "args": [n], "out"}`` and ``{"fn": "caracole.web.feed._ago", "args":
    [then, now], "out"}`` (times as history.py writes them, ``isoformat``);
  - ``{"fn": "caracole.stamps.shown", "tz", "args": [time], "kw": {"local": true}, "out"}``: a time in the server's
    zone, named, under ``TZ=<tz>``, for zones of letters and of numbers, either side of a change of their clocks;
  - ``{"fn": "caracole.library_page._requests_tab", "active", "out"}``: the tab for a count;
  - ``{"fn": "caracole.web.feed.feed", "note", "tz", "now", "jobs", "lines", "outcomes", "steps", "picks", "opened",
    "out"}``: the Requests tab's answer (``out``: its text, as ``json_response`` writes it, so its key order too)
    under ``TZ=<tz>`` (UTC and Europe/Madrid), for ``jobs`` newest first, each as history.py's line holds it
    (``_record``, its output whole), which JobHistory.jobOf reads; ``lines``, status.py's line of each by its id
    (``Line.as_json``, with ``todo=None``, as the phone's lines are); ``outcomes``, outcome.py's of each over (``tone``, ``word``, ``reason``, ``action`` and
    ``also``, each ``{label, href, post, fields: [[name, value], …]}`` or null), given for every one as
    jobs_routes.requests_json gives them; ``steps``, the running one's chips (``outcome.steps``, ``Chip.as_json``),
    which feed.py works out of the job and its song's facts; ``picks``, the songs that wait for a pick by key
    (``song_id``, ``search``: ``pages.Pick``'s fields feed.py reads); ``opened``, the requests whose output comes with
    what each command printed.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_requests.py`` after a
change to feed.py, stamps.py's ``shown``, library_page.py's Requests tab, or tzdata (flake.lock's nixpkgs).
"""

from __future__ import annotations

import functools
import json
import os
import time
import zoneinfo
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from helpers.corpus import DATA, VECTORS, check, jsonl

from caracole import library_page
from caracole.library_page import WebControls
from caracole.stamps import shown
from caracole.web import feed as feed_module
from caracole.web.feed import feed
from caracole.web.history import _record
from caracole.web.jobs import (
    Job,
    Step,
    _stages,
    add_steps,
    fetch_steps,
    lacuerda_artist_steps,
    lacuerda_search_steps,
    lookup_steps,
    remove_steps,
)
from caracole.web.outcome import Action, Outcome, outcome, steps
from caracole.web.pages import Pick
from caracole.web.status import Line, SongFacts, job_line

MADE_BY = "tests/test_conformance_requests.py"
REQUESTS_DATA = DATA / "page" / "requests.json"
REQUESTS = VECTORS / "web" / "requests.jsonl"
COUNT = "__N__"  # the tab's count, filled in by the phone
WHOLE = 10**9  # a record's output: every line of it
WINDOW = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2032, 1, 1, tzinfo=UTC))  # the zones' offsets in use
FEED_ZONES = ("UTC", "Europe/Madrid")
# Zones whose clocks the shown() records read: of letters, of numbers, a half hour's and a quarter's, a change of a
# half hour (Lord Howe), one whose winter is its daylight time in tzdata (Dublin), and links to others; none whose
# rules a recent tzdata changed (Casablanca, Edmonton), which a phone's older tzdata reads otherwise.
SHOWN_ZONES = ("UTC", "Etc/UTC", "Europe/Madrid", "Europe/London", "Europe/Dublin", "America/New_York",
               "America/Sao_Paulo", "America/St_Johns", "Asia/Kolkata", "Asia/Kathmandu", "Asia/Shanghai",
               "Australia/Lord_Howe", "Pacific/Chatham", "US/Eastern", "Europe/Kyiv")


# --- the server's time zone -----------------------------------------------------------------------------------


def tzdata() -> str | None:
    """The tzdata Python's zoneinfo reads, which the C library is pointed at too (TZDIR), so ``%Z`` reads the same
    files in a shell and in the package's sandbox, where /etc/zoneinfo isn't."""
    return next((path for path in zoneinfo.TZPATH if Path(path, "Europe", "Madrid").is_file()), None)


@contextmanager
def local_zone(name: str) -> Iterator[None]:
    """The process in time zone ``name`` (``TZ``), as caracole serve runs under it; then as it was."""
    folder = tzdata()
    if folder is None:
        pytest.skip("no tzdata where zoneinfo looks")
    saved = {key: os.environ.get(key) for key in ("TZ", "TZDIR")}
    os.environ["TZDIR"], os.environ["TZ"] = folder, name
    time.tzset()
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        time.tzset()


def numeric(offset: int) -> str:
    """How tzdata names an offset it has no letters for, by its number: ``-03``, ``+0545`` (minutes only when there
    are some); the phone's rule for an offset ``zones`` doesn't name."""
    sign = "-" if offset < 0 else "+"
    hours, minutes = divmod(abs(offset) // 60, 60)
    return f"{sign}{hours:02d}{minutes:02d}" if minutes else f"{sign}{hours:02d}"


@functools.cache
def zone_labels() -> dict[str, list[list[Any]]]:
    """Every zone's abbreviations in ``WINDOW``, as ``%Z`` gives them: ``[[offset, label, since], …]``, the label an
    offset in seconds east of UTC has from ``since`` (a Unix time in seconds; null: from before the window) on, until
    a later entry of the same offset; read twice a day, which no clock's change lasts less than, and where a label of
    an offset changes (Edmonton's -06, MDT then CST), the second it changes found by halving. An offset named by its
    number alone is left out (``numeric``), but where it follows a label of letters. A zone of none is left out."""
    samples = []
    at = WINDOW[0]
    while at < WINDOW[1]:
        samples.append(int(at.timestamp()))
        at += timedelta(hours=12)
    table: dict[str, list[list[Any]]] = {}
    for zone in sorted(zoneinfo.available_timezones()):
        entries: list[list[Any]] = []
        with local_zone(zone):
            labels: dict[int, str] = {}
            before = samples[0]
            for stamp in samples:
                local = time.localtime(stamp)
                offset, label = local.tm_gmtoff, local.tm_zone
                if offset not in labels:
                    entries.append([offset, label, None])
                elif labels[offset] != label:
                    low, high = before, stamp  # the label isn't the new one at low, and is at high
                    while high - low > 1:
                        middle = (low + high) // 2
                        seen = time.localtime(middle)
                        low, high = (middle, high) if (seen.tm_gmtoff, seen.tm_zone) != (offset, label) else (
                            low, middle)
                    entries.append([offset, label, high])
                labels[offset] = label
                before = stamp
        named = [e for n, e in enumerate(entries)
                 if e[1] != numeric(e[0]) or any(o == e[0] for o, _, _ in entries[:n])]
        if named:
            table[zone] = sorted(named, key=lambda e: (e[2] is not None, e[2] or 0, e[0]))
    return table


def requests_json() -> str:
    """The phone's runtime data of the tab: its markup and the zones' names."""
    tab = library_page._requests_tab(WebControls("", active=COUNT))  # type: ignore[arg-type]
    panel = library_page._requests_panel(WebControls(""))
    data = {"count": COUNT, "tab": tab, "panel": panel, "zones": zone_labels()}
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


# --- jobs -----------------------------------------------------------------------------------------------------


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def job(job_id: int, made: list[tuple[str, tuple[str, ...]]], *, title: str, key: str, state: str, queued: str,
        started: str | None = None, finished: str | None = None, display: str = "", note: str = "",
        fetching: bool = False, stages: dict[str, tuple[str, str]] | None = None,
        steps_said: list[tuple[str, list[str], int]] | None = None, song_id: int | None = None,
        seconds_to_sheet: float | None = None) -> Job:
    """A request as the queue holds it: its commands (``made``, a step builder's), its state and times; ``stages``,
    each named one's state and detail; ``steps_said``, each command's state, the lines it printed and how many
    before them were dropped."""
    the_steps = [Step(label, args) for label, args in made]
    for step, (state_of, output, dropped) in zip(the_steps, steps_said or [], strict=False):
        step.state, step.output, step.dropped = state_of, list(output), dropped
        step.code = None if state_of in ("waiting", "running", "skipped") else 0 if state_of == "done" else 1
    the_stages = _stages(the_steps)
    for stage in the_stages:
        if stages and stage.name in stages:
            stage.state, stage.detail = stages[stage.name]
            if stage.name == "sheet" and stage.detail.startswith("from "):
                stage.running_detail = stage.detail
    return Job(job_id, title, key, the_steps, fetching=fetching, note=note, display=display, state=state,
               queued_at=at(queued), started_at=at(started) if started else None,
               finished_at=at(finished) if finished else None, stages=the_stages, song_id=song_id,
               seconds_to_sheet=seconds_to_sheet)


def lookup(job_id: int, artist: str, title: str, **kw: Any) -> Job:
    return job(job_id, lookup_steps(artist, title), title=f"Look up {artist} - {title}",
               key=f"{artist.lower()}/{title.lower()}", display=f"{artist} - {title}", fetching=True, **kw)


DONE_LOOKUP = {name: ("done", "") for name in ("song", "match", "sheet", "pdf", "lyrics", "ug", "lacuerda", "gtptabs",
                                               "harptabs", "gametabs", "pages", "songbooks")}
SHEET = "Radiohead/Creep/sheet.html"


def queue_at_work() -> tuple[str, list[tuple[Job, SongFacts | None, int | None]], dict[str, Pick]]:
    """A queue late in the evening, UTC (after midnight in Madrid): one request running, three waiting, and what
    ended today and before, every way a request ends; their songs' facts and ids. Newest first."""
    now = "2026-11-03T23:30:00.250000+00:00"
    running = lookup(20, "Radiohead", "Creep", state="running", queued="2026-11-03T23:27:00+00:00",
                     started="2026-11-03T23:27:59.750000+00:00",
                     stages={"song": ("done", "in the library"), "match": ("done", "matched in UG"),
                             "sheet": ("running", "from LaCuerda")},
                     steps_said=[("running", ["Looking Radiohead - Creep up", "Asking LaCuerda"], 0)])
    over = [
        (job(21, lacuerda_artist_steps("soda-stereo", "Soda Stereo"), title="Read LaCuerda's page for Soda Stereo",
             key="lacuerda-artist:soda-stereo", state="queued", queued="2026-11-03T23:28:00+00:00",
             display="Soda Stereo on LaCuerda"), None, None),
        (job(22, add_steps("Björk", "Jóga"), title="Add Björk - Jóga", key="bjork/joga", state="queued",
             queued="2026-11-03T23:29:00+00:00"), None, None),
        (job(23, remove_steps("Oasis - Wonderwall"), title="Remove Oasis - Wonderwall", key="remove:oasis/wonderwall",
             state="queued", queued="2026-11-03T23:29:30+00:00", display="Oasis - Wonderwall", song_id=4), None, 4),
        (lookup(19, "Radiohead", "Creep", state="done", queued="2026-11-03T22:40:00+00:00",
                started="2026-11-03T22:40:01+00:00", finished="2026-11-03T22:50:30.999999+00:00",
                stages=DONE_LOOKUP, seconds_to_sheet=2.25, note="your pick: UG's 4th version",
                steps_said=[("done", ["a"] * 3, 0)]),
         SongFacts(sheet=SHEET, sheet_from="UG"), 1),
        (lookup(18, "Soda Stereo", "De Música Ligera", state="failed", queued="2026-11-03T23:05:00+00:00",
                started="2026-11-03T23:05:01+00:00", finished="2026-11-03T23:10:00+00:00",
                stages={"song": ("done", ""), "match": ("done", ""),
                        "sheet": ("failed", "Ultimate Guitar failed (ReadTimeout); the nightly run tries again")},
                steps_said=[("failed", [f"line {n}" for n in range(5)], 195)]),
         SongFacts(), 2),
        (lookup(17, "Gustavo Cerati", "Crimen", state="done", queued="2026-10-24T11:59:00+00:00",
                started="2026-10-24T11:59:30+00:00", finished="2026-10-24T12:00:00+00:00",
                stages={**DONE_LOOKUP, "sheet": ("done", "not on Ultimate Guitar")}, seconds_to_sheet=0.05),
         SongFacts(not_found=True, checked_now=True, asked_ug=True), 3),
        (job(16, fetch_steps("Sigur Rós - Hoppípolla"), title="Fetch Sigur Rós - Hoppípolla",
             key="sigur ros/hoppipolla", state="interrupted", queued="2026-10-25T00:30:00+00:00",
             display="Sigur Rós - Hoppípolla", fetching=True), SongFacts(), 5),
        (job(15, fetch_steps("Sigur Rós - Glósóli"), title="Fetch Sigur Rós - Glósóli", key="sigur ros/glosoli",
             state="interrupted", queued="2026-10-25T01:30:00+00:00", started="2026-10-25T01:30:05+00:00",
             finished="2026-10-25T01:31:00+00:00", fetching=True,
             steps_said=[("done", [], 0), ("interrupted", ["Asking Ultimate Guitar"], 0), ("skipped", [], 0)]),
         SongFacts(), 6),
        (job(14, add_steps("Café Tacvba", "Eres"), title="Add Café Tacvba - Eres", key="cafe tacvba/eres",
             state="cancelled", queued="2026-11-03T20:00:00+00:00", finished="2026-11-03T20:00:02+00:00"), None, None),
        (lookup(13, "Caifanes", "La Negra Tomasa", state="done", queued="2026-11-02T10:00:00+00:00",
                started="2026-11-02T10:00:01+00:00", finished="2026-11-02T10:01:00+00:00",
                stages={**DONE_LOOKUP, "sheet": ("skipped", "needs review first")}),
         SongFacts(review=True, picker="review?song=7"), 7),
        (job(12, fetch_steps("Héroes del Silencio - Entre dos tierras"),
             title="Fetch Héroes del Silencio - Entre dos tierras", key="heroes del silencio/entre dos tierras",
             state="failed", queued="2026-11-01T09:00:00+00:00", started="2026-11-01T09:00:01+00:00",
             finished="2026-11-01T09:00:09+00:00", fetching=True,
             steps_said=[("done", ["matched"], 0),
                         ("failed", ["error: Héroes del Silencio - Entre dos tierras needs review first"], 0),
                         ("skipped", [], 0)]),
         SongFacts(review=True, picker="review?song=8"), 8),
        (lookup(11, "Los Prisioneros", "Tren al sur", state="done", queued="2026-10-30T18:00:00+00:00",
                started="2026-10-30T18:00:01+00:00", finished="2026-10-30T18:02:00+00:00",
                stages={**DONE_LOOKUP, "sheet": ("done", "not on Ultimate Guitar")}),
         SongFacts(not_found=True, checked_now=True), 9),
        (lookup(10, "Los Prisioneros", "Estrechez de corazón", state="done", queued="2026-10-30T17:00:00+00:00",
                started="2026-10-30T17:00:01+00:00", finished="2026-10-30T17:02:00+00:00",
                stages={**DONE_LOOKUP, "sheet": ("done", "not on Ultimate Guitar")}),
         SongFacts(not_found=True, checked_now=True, elsewhere=("lacuerda", "prisioneros/estrechez")), 10),
        (lookup(9, "Radiohead", "Creep", state="done", queued="2026-10-20T08:00:00+00:00",
                started="2026-10-20T08:00:01+00:00", finished="2026-10-20T08:01:00+00:00",
                stages={**DONE_LOOKUP, "sheet": ("skipped", "needs review first")}),
         SongFacts(review=True, picker="review?song=1"), 1),
        (job(8, lacuerda_search_steps("de musica ligera", auto=True), title="Search LaCuerda for de musica ligera",
             key="lacuerda-search:de ligera musica", state="done", queued="2026-11-03T21:00:00+00:00",
             started="2026-11-03T21:00:01+00:00", finished="2026-11-03T21:00:03+00:00",
             steps_said=[("done", ["Searched: 3 songs of LaCuerda's for de musica ligera"], 0)]), None, None),
    ]
    picks = {
        "caifanes/la negra tomasa": Pick(7, "Caifanes - La Negra Tomasa", "La Negra Tomasa", "Caifanes"),
        "heroes del silencio/entre dos tierras": Pick(8, "Héroes del Silencio - Entre dos tierras",
                                                      "Entre dos tierras", "Héroes del Silencio"),
        "los prisioneros/tren al sur": Pick(9, "Los Prisioneros - Tren al sur", "Tren al sur", "Los Prisioneros",
                                            search=True),
        "los prisioneros/estrechez de corazón": Pick(10, "Los Prisioneros - Estrechez de corazón",
                                                     "Estrechez de corazón", "Los Prisioneros", search=True),
        "gustavo cerati/crimen": Pick(3, "Gustavo Cerati - Crimen", "Crimen", "Gustavo Cerati", search=True),
        # a song not found, whose request failed: what caracole search finds, after Try again
        "soda stereo/de música ligera": Pick(2, "Soda Stereo - De Música Ligera", "De Música Ligera", "Soda Stereo",
                                             search=True),
        # a song whose newest request runs: its older one is no pick's
        "radiohead/creep": Pick(1, "Radiohead - Creep", "Creep", "Radiohead"),
    }
    jobs = sorted([(running, SongFacts(sheet_from=""), 1), *over], key=lambda found: -found[0].id)
    return now, jobs, picks


def mornings() -> tuple[str, list[tuple[Job, SongFacts | None, int | None]], dict[str, Pick]]:
    """Early in the morning, UTC: what ended late last night (today already in Madrid) and at midnight, the running
    request just started (no time yet, then a time after now), and a song of no facts."""
    now = "2026-11-03T06:30:00+00:00"
    jobs = [
        (lookup(34, "A", "Started", state="running", queued="2026-11-03T06:29:00+00:00",
                started="2026-11-03T06:30:00.500000+00:00", stages={"song": ("running", "")}), None, None),
        (job(33, add_steps("B", "Waits"), title="Add B - Waits", key="b/waits", state="queued",
             queued="2026-11-03T06:29:30+00:00"), None, None),
        (lookup(32, "C", "Midnight", state="done", queued="2026-11-02T22:59:00+00:00",
                started="2026-11-02T22:59:01+00:00", finished="2026-11-02T23:00:00+00:00",
                stages=DONE_LOOKUP, seconds_to_sheet=1.35), SongFacts(sheet="C/Midnight/sheet.html"), 11),
        (lookup(31, "D", "Late", state="done", queued="2026-11-02T23:29:00+00:00",
                started="2026-11-02T23:29:01+00:00", finished="2026-11-02T23:30:00+00:00",
                stages=DONE_LOOKUP, seconds_to_sheet=12.0), SongFacts(sheet="D/Late/sheet.html"), 12),
        (lookup(30, "E", "Earlier", state="done", queued="2026-11-02T21:00:00+00:00",
                started="2026-11-02T21:00:01+00:00", finished="2026-11-02T22:59:59+00:00",
                stages=DONE_LOOKUP), SongFacts(sheet="E/Earlier/sheet.html"), 13),
    ]
    return now, jobs, {}


def summer() -> tuple[str, list[tuple[Job, SongFacts | None, int | None]], dict[str, Pick]]:
    """A summer's day: Madrid's daylight time; a running request with no time, one started hours ago."""
    now = "2026-07-15T12:00:00+00:00"
    jobs = [
        (job(42, fetch_steps("F - Summer"), title="Fetch F - Summer", key="f/summer", state="running",
             queued="2026-07-15T08:00:00+00:00", started="2026-07-15T08:59:59+00:00", fetching=True,
             steps_said=[("done", ["x"], 0), ("running", ["y"], 0)]), SongFacts(), 14),
        (lookup(41, "G", "July", state="done", queued="2026-07-14T21:50:00+00:00",
                started="2026-07-14T21:50:01+00:00", finished="2026-07-14T22:10:00+00:00", stages=DONE_LOOKUP),
         SongFacts(sheet="G/July/sheet.html"), 15),
    ]
    return now, jobs, {}


def starting() -> tuple[str, list[tuple[Job, SongFacts | None, int | None]], dict[str, Pick]]:
    """A request that runs with no time yet, and none over."""
    now = "2026-11-03T12:00:00+00:00"
    started = job(50, add_steps("H", "Now"), title="Add H - Now", key="h/now", state="running",
                  queued="2026-11-03T11:59:59+00:00")
    return now, [(started, None, None)], {}


def outcome_json(said: Outcome | None) -> dict[str, Any] | None:
    def action(a: Action | None) -> dict[str, Any] | None:
        if a is None:
            return None
        return {"label": a.label, "href": a.href, "post": a.post, "fields": [list(pair) for pair in a.fields]}

    if said is None:
        return None
    return {"tone": said.tone, "word": said.word, "reason": said.reason, "action": action(said.action),
            "also": action(said.also)}


def feed_record(note: str, zone: str, now: str, found: list[tuple[Job, SongFacts | None, int | None]],
                picks: dict[str, Pick], opened: list[int], *, outcomes: dict[int, Outcome] | None = None,
                lines: dict[int, Line] | None = None) -> dict[str, Any]:
    """The Requests tab's answer for ``found`` (jobs newest first, with their songs' facts and ids), as
    jobs_routes.requests_json makes it: each job's line, each over one's outcome, under ``TZ=zone``; ``outcomes``
    and ``lines``, made up, in place of outcome.py's and status.py's."""
    jobs = [j for j, _, _ in found]
    facts = {j.id: f for j, f, _ in found}
    made_lines = {j.id: job_line(j, f, ahead=sum(1 for o in jobs if o.active and o.id < j.id), todo=None)
                  for j, f, _ in found}  # the phone's: no to-do page
    made_lines |= lines or {}
    said = {j.id: outcome(j, made_lines[j.id], f, song_id=song_id) for j, f, song_id in found
            if not j.active and j.id in made_lines}
    said |= outcomes or {}
    chips = {j.id: [chip.as_json() for chip in steps(j, facts.get(j.id))] for j in jobs if j.state == "running"}
    with local_zone(zone):
        out = feed(jobs, made_lines, outcomes=said, facts=facts, picks=picks, opened=opened, now=at(now))
    return {"fn": "caracole.web.feed.feed", "note": note, "tz": zone, "now": now,
            "jobs": [_record(j, WHOLE, WHOLE) for j in jobs],
            "lines": {str(i): line.as_json() for i, line in made_lines.items()},
            "outcomes": {str(i): outcome_json(o) for i, o in said.items()},
            "steps": {str(i): chips_of for i, chips_of in chips.items()},
            "picks": {key: {"song_id": pick.song_id, "search": pick.search} for key, pick in picks.items()},
            "opened": opened, "out": json.dumps(out, ensure_ascii=False, separators=(",", ":"))}


# Outcomes made up, for what outcome.py's never are: an action of neither link nor form, a form's fields twice the
# same name, a second way on that is a primary's label, and a link the search's would be.
MADE_UP = {
    19: Outcome("ready", "Ready", "", Action("Open", href="/Radiohead/Creep/sheet.html"),
                Action("Get it from there", post="/lookup", fields=(("song", "1"), ("lacuerda", "a"),
                                                                    ("song", "2")))),
    18: Outcome("failed", "Failed", "Ultimate Guitar failed.", Action("Nowhere")),
    17: Outcome("missing", "Not found", "", Action("Request by name", href="/#q=x"),
                Action("See what caracole search finds", href="/review?song=3")),
}


def feed_records() -> list[dict[str, Any]]:
    records = []
    for zone in FEED_ZONES:
        records.append(feed_record("no request", zone, "2026-11-03T12:00:00+00:00", [], {}, []))
        now, found, picks = queue_at_work()
        records.append(feed_record("a queue at work: one runs, three wait, every way one ends", zone, now, found,
                                   picks, [20, 18, 12, 99]))
        records.append(feed_record("the same, none opened", zone, now, found, picks, []))
        records.append(feed_record("the same, outcomes made up", zone, now, found, picks, [19],
                                   outcomes=MADE_UP))
        now, found, picks = mornings()
        records.append(feed_record("early morning: last night is today in Madrid", zone, now, found, picks, [32]))
        now, found, picks = summer()
        records.append(feed_record("summer: daylight time", zone, now, found, picks, [42]))
        now, found, picks = starting()
        records.append(feed_record("a request running with no time yet", zone, now, found, picks, []))
    records.extend(bare_records())
    return records


def bare_records() -> list[dict[str, Any]]:
    """Jobs over with no line and no outcome (feed.py says their state), and a running one with no line."""
    now = "2026-11-03T12:00:00+00:00"
    jobs = [job(63, add_steps("I", "Running"), title="Add I - Running", key="i/running", state="running",
                queued="2026-11-03T11:00:00+00:00", started="2026-11-03T11:00:00+00:00")]
    for job_id, state in ((62, "done"), (61, "failed"), (60, "interrupted")):
        jobs.append(job(job_id, add_steps("I", state), title=f"Add I - {state}", key=f"i/{state}", state=state,
                        queued="2026-11-03T10:00:00+00:00", finished="2026-11-03T10:00:01+00:00"))
    records = []
    for zone in FEED_ZONES:
        with local_zone(zone):
            out = feed(jobs, {}, now=at(now))
        records.append({"fn": "caracole.web.feed.feed", "note": "no line, no outcome", "tz": zone, "now": now,
                        "jobs": [_record(j, WHOLE, WHOLE) for j in jobs], "lines": {}, "outcomes": {},
                        "steps": {"63": [chip.as_json() for chip in steps(jobs[0])]}, "picks": {}, "opened": [],
                        "out": json.dumps(out, ensure_ascii=False, separators=(",", ":"))})
    return records


# --- the smaller rules ------------------------------------------------------------------------------------------


def ordinal_records() -> list[dict[str, Any]]:
    numbers = [*range(-1, 32), *range(99, 125), 1000, 1001, 1011, 1012, 1013, 1021, 1111, 2112, 10**12 + 3]
    return [{"fn": "caracole.web.feed._ordinal", "args": [n], "out": feed_module._ordinal(n)} for n in numbers]


def ago_records() -> list[dict[str, Any]]:
    now = datetime(2026, 11, 3, 12, 0, 0, 250000, tzinfo=UTC)
    gaps = [timedelta(seconds=s) for s in (-90, -0.5, 0, 0.249999, 0.25, 1, 59, 59.75, 60, 61, 3599, 3599.999999,
                                           3600, 7199, 7200, 86400, 86400 * 31 + 1)]
    gaps += [timedelta(microseconds=1), timedelta(days=-1), timedelta(seconds=59, microseconds=999999)]
    return [{"fn": "caracole.web.feed._ago", "args": [(now - gap).isoformat(), now.isoformat()],
             "out": feed_module._ago(now - gap, now)} for gap in gaps]


def shown_records() -> list[dict[str, Any]]:
    """A time in the server's zone, named, either side of a change of clocks of each zone's in 2026."""
    times = ["2026-01-15T12:00:00+00:00", "2026-07-15T12:00:00+00:00", "2026-03-29T00:59:59+00:00",
             "2026-03-29T01:00:00+00:00", "2026-10-25T00:59:59.999999+00:00", "2026-10-25T01:00:00+00:00",
             "2026-03-08T06:59:59+00:00", "2026-03-08T07:00:00+00:00", "2026-11-01T05:59:59+00:00",
             "2026-11-01T06:00:00+00:00", "2026-04-04T14:59:59+00:00", "2026-04-05T15:00:00+00:00",
             "2026-12-31T23:59:59+00:00", "2027-01-01T00:00:00+00:00"]
    records = []
    for zone in SHOWN_ZONES:
        with local_zone(zone):
            for text in times:
                records.append({"fn": "caracole.stamps.shown", "tz": zone, "args": [text], "kw": {"local": True},
                                "out": shown(at(text), "", local=True)})
            records.append({"fn": "caracole.stamps.shown", "tz": zone, "args": [None], "kw": {"local": True},
                            "out": shown(None, "", local=True)})
    return records


def tab_records() -> list[dict[str, Any]]:
    return [{"fn": "caracole.library_page._requests_tab", "active": n,
             "out": library_page._requests_tab(WebControls("tok", active=n))} for n in (0, 1, 2, 9, 10, 20, 100)]


def tables_record() -> dict[str, Any]:
    return {"fn": "tables", "out": {"STATE_TEXT": feed_module.STATE_TEXT, "PRIMARY": sorted(feed_module.PRIMARY),
                                    "SEARCH": feed_module.SEARCH, "PICK_STAGE": feed_module.PICK_STAGE,
                                    "PICK_STEP": feed_module.PICK_STEP}}


def records() -> list[dict[str, Any]]:
    return [tables_record(), *ordinal_records(), *ago_records(), *shown_records(), *tab_records(), *feed_records()]


# --- the files --------------------------------------------------------------------------------------------------


def test_requests_json_is_the_tabs_markup_and_the_zones_names():
    check(REQUESTS_DATA, requests_json())


def test_requests_jsonl_is_what_the_requests_tab_answers():
    check(REQUESTS, jsonl(records(), corpus="web/requests", made_by=MADE_BY))


# --- what the files rest on -------------------------------------------------------------------------------------


def test_the_tab_is_requests_tab_for_every_count():
    data = json.loads(requests_json())
    for n in range(0, 130):
        filled = data["tab"].replace(data["count"], str(n) if n else "")
        assert filled == library_page._requests_tab(WebControls("tok", active=n)), n
    assert data["tab"].count(data["count"]) == 1
    assert data["panel"] == library_page._requests_panel(WebControls("tok", sync=True))
    assert library_page._requests_tab(None) == library_page._requests_panel(None) == ""


def label_of(table: dict[str, list[list[Any]]], zone: str, when: datetime) -> str:
    """The phone's rule: the zone's offset then, named by the table's latest entry of that offset since then, else by
    its number."""
    with local_zone(zone):
        offset = time.localtime(when.timestamp()).tm_gmtoff
    moment = int(when.timestamp() // 1)
    named = [label for o, label, since in table.get(zone, []) if o == offset and (since is None or since <= moment)]
    return named[-1] if named else numeric(offset)


def test_the_zones_and_the_numeric_rule_name_every_time_as_percent_z_does():
    # The phone names a time's zone by the table, else by its offset's number: what %Z gives for every zone the
    # shown() records read, at every time they read.
    table = json.loads(requests_json())["zones"]
    for record in shown_records():
        if record["args"][0] is None:
            continue
        assert record["out"].endswith(" " + label_of(table, record["tz"], at(record["args"][0]))), record
    for zone, entries in table.items():  # and every change of a label the table holds, either side of it
        for _, _, since in entries:
            if since is not None:
                for moment in (since - 1, since):
                    when = datetime.fromtimestamp(moment, UTC)
                    with local_zone(zone):
                        assert shown(when, local=True).endswith(" " + label_of(table, zone, when)), (zone, moment)
    assert table["Europe/Madrid"] == [[3600, "CET", None], [7200, "CEST", None]]
    assert table["UTC"] == [[0, "UTC", None]] and "America/Sao_Paulo" not in table
    assert any(since is not None for entries in table.values() for _, _, since in entries)
    assert numeric(-3 * 3600) == "-03" and numeric(5 * 3600 + 45 * 60) == "+0545" and numeric(0) == "+00"


def test_the_feed_records_cover_what_the_tab_draws():
    feeds = [r for r in records() if r["fn"] == "caracole.web.feed.feed"]
    drawn = [json.loads(r["out"]) for r in feeds]
    groups = {g["name"] for d in drawn for g in d["groups"]}
    assert groups == {"Now", "Today", "Earlier"}
    requests = [req for d in drawn for g in d["groups"] for req in g["requests"]]
    assert {req["state"] for req in requests} == {"queued", "running", "done", "failed", "cancelled", "interrupted"}
    assert any(req.get("ago") for req in requests) and any("ago" not in req for req in requests
                                                            if req["state"] == "running")
    badges = {s["badge"]["text"] for req in requests for s in req["output"]["stages"] + req["output"]["steps"]}
    assert "Waits for a pick" in badges
    assert any(s.get("note") == feed_module.PICK_STAGE for req in requests for s in req["output"]["stages"])
    assert any(s.get("note") == feed_module.PICK_STEP for req in requests for s in req["output"]["steps"])
    assert any(s.get("lines", [""])[0].endswith("earlier lines") for req in requests for s in req["output"]["steps"])
    actions = [a for req in requests for a in req.get("actions", [])]
    assert {a["label"] for a in actions} >= {"Cancel", "Try again", "Open", feed_module.SEARCH, "Pick the match",
                                             "Get it from there"}
    assert any(a["primary"] for a in actions) and any(not a["primary"] for a in actions)
    assert any("post" in a for a in actions) and any("href" in a for a in actions)
    metas = [req["output"]["meta"] for req in requests]
    assert any("CET" in m for m in metas) and any("CEST" in m for m in metas) and any("UTC" in m for m in metas)
    assert any("sheet readable after 2.2 s" in m for m in metas)  # 2.25, rounded half to even as Python's
    whens = {req["when"]["text"] for req in requests if "when" in req}
    assert any("," in w for w in whens) and any("," not in w for w in whens)
    # the evening's request that ended at 22:50 UTC is today in UTC, yesterday in Madrid
    work = [json.loads(r["out"]) for r in feeds if r["note"].startswith("a queue at work")]
    days = [{req["id"]: g["name"] for g in d["groups"] for req in g["requests"]} for d in work]
    assert days[0][19] == "Today" and days[1][19] == "Earlier"
