"""The Sync tab's answers and the views of the jobs the library page follows, for the phone: what android/server's
SyncRoutes (lane phone-sync-routes) and JobViews (lane jobs) answer to.

- ``vectors/web/sync_routes.jsonl``: caracole serve's three routes of the Sync tab (web/sync_routes.py), each record
  a request the tab's script makes and its answer, over two sides: ``here``, whose routes are asked (``fixture``, the
  sync corpus's fixture its database is, replayed, ``id`` its kv ``sync:id``, ``name`` its library's name, and
  ``kv`` more kv it holds: ``sync:peer:<id>``, ``sync:base:<id>``), and ``there``, the other caracole, as the
  comparison reads it: ``peer_state``, its ``GET /api/peer/state`` answer to here (its ``token`` masked,
  ``"<token>"``). Each record is ``{fn: "<METHOD> <path>", here, peer_state, form, status, out}``:

  - ``GET /api/sync``: ``out`` ``{server, name, address, peers}``;
  - ``POST /sync/compare``: ``form`` ``{address}``, ``out`` ``{comparison, peer, synced_before, differences}`` with
    the comparison's id masked (``"<comparison>"``);
  - ``POST /sync/apply``: ``compare`` the form of the comparison it follows (whose id ``form``'s ``comparison``
    names as ``"<comparison>"``; any other text is one no comparison has), ``peer_state_then`` the other side's state
    when Sync asks it again (null: as it was), ``out`` the refusal (``{error}``) or the job queued (``{job: view}``,
    the queue's first job, ``queued`` its command's arguments).

  A refusal's words are the routes'; the phone's routes say the same.
- ``vectors/web/job_views.jsonl``: ``caracole.web.jobs_routes.view`` over jobs of a sync (``caracole peer sync``),
  a push taken (``caracole peer take``: peer-push), another caracole's index pages merged (``caracole index merge
  --progress``: index-merge), an add and a removal, in every state (queued, ahead of others or
  not; running; done; failed, with an ``error:`` line, without, in a stage's words, or a stage the queue ended failed;
  cancelled; interrupted). ``job`` is the job as the phone would hold it: ``kind`` (its JobSpec's: sync, peer-push,
  index-merge, add, remove), ``id``, ``title``, ``display``, ``key``, ``state``, ``stages`` (``{name, label, state, detail,
  running_detail}``: a staged job's stages, else its commands as ``Job.as_json`` lists them as steps), ``output``
  (what it printed, its ``error:`` line among them), ``song_id`` (the song the view names, or null), ``ahead`` (the
  jobs waiting or running before it) and ``outcome`` (what it took, gave and left: ``jobs_routes.peer_outcome``, which
  the phone's job sets itself); ``out`` the view.

A change to sync_routes.py, jobs_routes.py's view, status.py's or outcome.py's words, or to the sync corpus's
fixtures makes these stale: regenerate them (§3 of docs/superpowers/plans/2026-11-03-android-port-m1-m3.md), and the
phone's tests read them again.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from helpers.corpus import VECTORS, check, jsonl

from caracole import __version__, db
from caracole import peer_sync as sync
from caracole.web import sync_routes
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue, Stage, Step
from caracole.web.jobs import Job as PyJob
from caracole.web.jobs_routes import peer_outcome, view
from caracole.web.status import SongFacts

from test_conformance_sync import Corpus
from test_web_app import ALLOWED, HOST, Recorder
from test_web_sync import peer_job

MADE_BY = "tests/test_conformance_sync_routes.py"
WEB = VECTORS / "web"
HERE_ID, THERE_ID = "a1b2c3d4e5f60718", "0f1e2d3c4b5a6978"
THERE = "http://192.168.1.20:8737"
THEN = "2026-11-03T09:30:00Z"  # the other side's clock in its state
AGREED_AT = "2026-11-01T20:00:00Z"
MASKED = "<comparison>"


# --- the Sync tab's routes ----------------------------------------------------------------------------------------


class Sides:
    """Here, a fixture of the sync corpus replayed (``Corpus.replayed``), and there, a state document the comparison
    is answered with."""

    def __init__(self, corpus: Corpus, fixture: str, tag: str, kv: dict[str, Any] | None = None):
        self.lib = corpus.replayed("sync", fixture, tag)
        db.kv_set(self.lib.conn, sync.ID_KEY, HERE_ID)
        self.kv = {key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
                   for key, value in (kv or {}).items()}
        for key, text in self.kv.items():
            db.kv_set(self.lib.conn, key, text)
        self.app = WebApp(self.lib.cfg, JobQueue(Recorder()), allowed=ALLOWED, csrf="tok")
        self.described = {"fixture": f"sync/fixtures/{fixture}", "id": HERE_ID, "name": self.lib.cfg.library_name,
                          "kv": self.kv}
        self.state: dict[str, Any] | None = None

    def ask(self, monkeypatch, method: str, path: str, form: dict[str, str] | None = None) -> tuple[int, Any]:
        """The tab's script asking here, the other side answering its state as ``self.state`` says."""
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == sync.STATE_PATH, request.url
            return httpx.Response(200, json=self.state)

        monkeypatch.setattr(sync_routes, "transport", lambda: httpx.MockTransport(handler))
        if method == "GET":
            headers = {"host": HOST, "accept": "application/json", "sec-fetch-site": "same-origin"}
            answer = self.app.handle(Request("GET", path, headers))
        else:
            from urllib.parse import urlencode

            headers = {"host": HOST, "content-type": "application/x-www-form-urlencoded",
                       "sec-fetch-site": "same-origin", "origin": f"http://{HOST}", "accept": "application/json"}
            answer = self.app.handle(Request("POST", path, headers, urlencode({"csrf": "tok", **(form or {})})
                                             .encode()))
        return answer.status, json.loads(answer.body)


def state_of(lib, *, name: str = "Desk", base: dict | None = None, changes=None) -> dict[str, Any]:
    """There's state as it answers here: ``lib``'s units (``changes`` {id: (label, digest) or None} on top), its
    base for here (``base``), its clock ``THEN``, its token masked."""
    units = dict(lib.units())
    for unit_id, unit in (changes or {}).items():
        if unit is None:
            units.pop(unit_id, None)
        else:
            units[unit_id] = sync.Unit(unit_id, *unit)
    return sync.state_document(THERE_ID, __version__, name, units, base, now=THEN, indexes={}) | {"token": "<token>"}


def route_records(corpus: Corpus, monkeypatch) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    peers = {f"sync:peer:{THERE_ID}": {"address": THERE, "name": "Desk", "synced_at": AGREED_AT},
             "sync:peer:9a8b7c6d5e4f3021": {"address": "http://10.0.0.7:8737", "name": "Studio",
                                            "synced_at": "2026-10-30T08:00:00Z"},
             "sync:peer:ffffffffffffffff": "not a record"}

    def get(sides: Sides, note: str) -> None:
        status, out = sides.ask(monkeypatch, "GET", "/api/sync")
        records.append({"fn": "GET /api/sync", "note": note, "here": sides.described, "peer_state": None,
                        "form": None, "status": status, "out": out})

    def compare(sides: Sides, note: str, address: str = THERE) -> dict[str, Any]:
        status, out = sides.ask(monkeypatch, "POST", "/sync/compare", {"address": address})
        shown = dict(out, comparison=MASKED) if "comparison" in out else out
        records.append({"fn": "POST /sync/compare", "note": note, "here": sides.described, "peer_state": sides.state,
                        "form": {"address": address}, "status": status, "out": shown})
        return out

    def apply(sides: Sides, note: str, form: dict[str, str], *, then: dict | None = None,
              address: str = THERE) -> None:
        compared = sides.ask(monkeypatch, "POST", "/sync/compare", {"address": address})[1]
        before = sides.state
        if then is not None:
            sides.state = then
        sent = dict(form, comparison=compared["comparison"] if form.get("comparison") == MASKED
                    else form.get("comparison", ""))
        status, out = sides.ask(monkeypatch, "POST", "/sync/apply", sent)
        queued = [list(step.args) for job in sides.app.queue.snapshot() for step in job.steps]
        records.append({"fn": "POST /sync/apply", "note": note, "here": sides.described, "peer_state": before,
                        "compare": {"address": address}, "peer_state_then": then, "form": form,
                        "status": status, "out": out, "queued": queued})
        sides.state = before

    # What the tab reads first.
    get(Sides(corpus, "plain", "-routes-none"), "synced with none")
    get(Sides(corpus, "plain", "-routes-peers", peers), "the peers synced with, newest first, an unreadable "
                                                         "record left out")

    # Two that never synced: every kind of unit on one side alone or on both, differently.
    first = Sides(corpus, "rich", "-routes-first")
    both = {"song/radiohead/creep": ("Radiohead - Creep", "9" * 64)}  # on both sides, held otherwise there
    first.state = state_of(corpus.replayed("sync", "plain"), changes=both)
    compare(first, "never synced: only here, only there, on both sides and different")
    compare(first, "an address typed with no scheme", "192.168.1.20:8737")
    compare(first, "not an address", "ftp://desk")
    first.state = dict(first.state, server=HERE_ID)
    compare(first, "this very caracole: its database copied")

    # Two that agreed once: each side's change since, and both's. Here is the fixture as it is; what each side held
    # when they agreed is the base, which both keep alike, and there is as its state says.
    creep, karma, campfire = "song/radiohead/creep", "song/radiohead/karma-police", "songbook/campfire"
    lib = corpus.replayed("sync", "rich", "-routes-there")
    units = lib.units()
    agreed_on = {u.id: (u.digest, AGREED_AT) for u in units.values()}
    agreed_on[karma] = ("0" * 64, AGREED_AT)  # here's changed since: there's is still that
    agreed_on[creep] = ("1" * 64, AGREED_AT)  # both changed since
    base = {"format": sync.FORMAT, "units": {k: list(v) for k, v in sorted(agreed_on.items())}}
    agreed = Sides(corpus, "rich", "-routes-agreed", {f"sync:base:{THERE_ID}": base, **{
        k: v for k, v in peers.items() if k == f"sync:peer:{THERE_ID}"}})
    agreed.state = state_of(lib, base=agreed_on,
                            changes={karma: ("Radiohead - Karma Police", "0" * 64),
                                     creep: ("Radiohead - Creep", "2" * 64),
                                     campfire: ("the songbook Campfire", "c" * 64),  # changed there since
                                     "song/muse/hysteria": ("Muse - Hysteria", "e" * 64),  # new there
                                     "block/4242": None})  # gone there
    found = compare(agreed, "synced before: changed here, there, on both sides, new there, gone there")
    conflicts = [d["id"] for d in found["differences"] if d["proposal"] == "conflict"]
    mine = [d["id"] for d in found["differences"] if d["proposal"] == "mine"]
    assert conflicts and mine, found

    # Sync, refused and queued.
    apply(agreed, "a comparison no comparison answered", {"comparison": "0123456789abcdef", "prefer": "",
                                                         "choices": ""})
    apply(agreed, "a conflict with no side", {"comparison": MASKED, "prefer": "", "choices": ""})
    apply(agreed, "a line that is no choice", {"comparison": MASKED, "prefer": "", "choices": "maybe\tsong/x"})
    apply(agreed, "a unit the comparison didn't find", {"comparison": MASKED, "prefer": "here",
                                                        "choices": "skip\tsong/not/compared"})
    apply(agreed, "a unit chosen two ways", {"comparison": MASKED, "prefer": "",
                                             "choices": f"here\t{conflicts[0]}\nthere\t{conflicts[0]}"})
    apply(agreed, "prefer, neither side", {"comparison": MASKED, "prefer": "both", "choices": ""})
    apply(agreed, "there changed since the comparison", {"comparison": MASKED, "prefer": "here", "choices": ""},
          then=dict(agreed.state, units={**agreed.state["units"], "song/muse/uprising": {
              "label": "Muse - Uprising", "digest": "f" * 64}}))
    choices = "\n".join([f"there\t{conflicts[0]}", f"skip\t{mine[0]}"])
    apply(agreed, "every conflict chosen, a proposal skipped", {"comparison": MASKED, "prefer": "",
                                                                "choices": choices})
    nothing = Sides(corpus, "plain", "-routes-same")
    nothing.state = state_of(nothing.lib)
    apply(nothing, "nothing differs: Sync all the same", {"comparison": MASKED, "prefer": "", "choices": ""})
    again = Sides(corpus, "rich", "-routes-prefer")
    again.state = state_of(corpus.replayed("sync", "plain"), changes=both)
    apply(again, "the conflicts left to prefer", {"comparison": MASKED, "prefer": "there", "choices": ""})
    return records


# --- the jobs' views ----------------------------------------------------------------------------------------------


WHEN = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)
SONG = ("Radiohead", "Creep")
KEY = "radiohead/creep"


def song_job(kind: str, state: str, *, output=(), job_id: int = 7, song_id: int | None = 12) -> PyJob:
    """An add's (``caracole add``) or a removal's (``caracole remove --yes``) job of caracole serve's, in ``state``."""
    display = " - ".join(SONG)
    if kind == "add":
        title, key, label, args = f"Add {display}", KEY, "Adding to the library", ("add", "--", *SONG)
    else:
        title, key, label, args = f"Remove {display}", "remove:" + KEY, "Removing from caracole", (
            "remove", "--yes", "--", display)
    step_state = {"queued": "waiting", "running": "running", "done": "done", "failed": "failed",
                  "cancelled": "skipped", "interrupted": "interrupted"}[state]
    return PyJob(job_id, title, key, [Step(label, args, step_state, output=list(output))], display=display,
                 state=state, queued_at=WHEN, started_at=None if state in ("queued", "cancelled") else WHEN,
                 finished_at=WHEN if state not in ("queued", "running") else None,
                 song_id=song_id if kind == "remove" else None)


def as_phone_job(job: PyJob, kind: str, song_id: int | None, ahead: int) -> dict[str, Any]:
    """The job as the phone would hold it (the module's docstring)."""
    if job.stages:
        stages = [{"name": s.name, "label": s.label, "state": s.state, "detail": s.detail,
                   "running_detail": s.running_detail} for s in job.stages]
    else:
        stages = [{"name": s.args[0], "label": s.label, "state": s.state, "detail": "", "running_detail": ""}
                  for s in job.steps]
    return {"kind": kind, "id": job.id, "title": job.title, "display": job.display, "key": job.song_key,
            "state": job.state, "stages": stages, "output": [line for s in job.steps for line in s.output],
            "song_id": song_id, "ahead": ahead, "outcome": peer_outcome(job) if kind in ("sync", "peer-push") else None}


def view_record(note: str, job: PyJob, kind: str, *, song_id: int | None = None, ahead: int = 0,
                facts: SongFacts | None = None) -> dict[str, Any]:
    queue = [PyJob(job.id - 1 - n, "Add Other", f"other/{n}", [Step("Adding to the library", ("add",))])
             for n in range(ahead)] + [job]
    out = view(job, queue[::-1], song_id, facts)
    return {"fn": "caracole.web.jobs_routes.view", "note": note, "job": as_phone_job(job, kind, song_id, ahead),
            "args": [], "kw": {}, "out": out}


SYNC_DONE = {"compare": ("done", "4 differences"), "take": ("done", "took 2"), "give": ("done", "gave 1"),
             "agree": ("done", "312 units the two agree on")}
TAKE_DONE = {"check": ("done", "3 changes from Phone"), "take": ("done", "took 3"), "render": ("done", ""),
             "agree": ("done", "40 units the two agree on")}
CRASH = "error: The caracole at http://192.168.1.20:8737 answered 500. It may be restarting."


def view_records() -> list[dict[str, Any]]:
    records = []
    for kind, done, names in (("sync", SYNC_DONE, ("compare", "take", "give", "agree")),
                              ("peer-push", TAKE_DONE, ("check", "take", "render", "agree"))):
        def job(state, stages=None, **kw):
            return peer_job(kind, state, stages, **kw)

        first, second = names[0], names[1]
        records += [
            view_record("queued, next", job("queued"), kind),
            view_record("queued behind two", job("queued"), kind, ahead=2),
            view_record("its first stage running", job("running", {first: ("running", "")}), kind),
            view_record("between two stages", job("running", {first: done[first]}), kind),
            view_record("its second stage running, with what it says",
                        job("running", {first: done[first], second: ("running", "2 changes")}), kind),
            view_record("done, nothing left", job("done", done, units=[("song/oasis/wonderwall", "taken", ""),
                                                                      ("song/estopa/tu-calorro", "taken", "")]
                                                  + ([("song/muse/hysteria", "given", "")] if kind == "sync" else [])),
                        kind),
            view_record("done, one left", job("done", done, units=[("song/oasis/wonderwall", "taken", ""), (
                "song/radiohead/creep", "left", "skipped, as chosen")]), kind),
            view_record("done, two left", job("done", done, units=[
                ("song/radiohead/creep", "left", "skipped, as chosen"),
                ("songbook/campfire", "left", sync.CHANGED_HERE)]), kind),
            view_record("done, nothing to take or give", job("done", {first: ("done", "0 differences"),
                                                                     "agree": ("done", "1 unit the two agree on")}
                                                              | {n: ("skipped", "") for n in names[1:-1]}), kind),
            view_record("failed in a stage's words", job("failed", {first: ("failed", sync_routes.STALE)},
                                                        output=["error: " + sync_routes.STALE]), kind),
            view_record("failed with an error line, its stage ended by the queue", _ended(job(
                "failed", {first: done[first], second: ("running", "2 changes")}, output=["Comparing…", CRASH]),
                second), kind),
        ]
        if kind == "sync":  # its command's label is its title, as the phone's job has no other (a take's is its own)
            records.append(view_record("failed with no error line", _ended(job(
                "failed", {first: ("running", "")}, output=["Traceback (most recent call last):"]), first), kind))
        records += [
            view_record("cancelled", _cancelled(job("cancelled")), kind),
            view_record("interrupted while it ran", _ended(job("interrupted", {first: done[first],
                                                                               second: ("running", "1 change")}),
                                                           second, "interrupted"), kind),
            view_record("interrupted before it ran", job("interrupted"), kind),
        ]
    for kind, stage, said in (("index-merge", "merge", "merged 12 pages: ug, lacuerda"),):
        def job(state, stages=None, **kw):
            return peer_job(kind, state, stages, **kw)

        records += [
            view_record("queued, next", job("queued"), kind),
            view_record("queued behind two", job("queued"), kind, ahead=2),
            view_record("running", job("running", {stage: ("running", "")}), kind),
            view_record("done", job("done", {stage: ("done", said)}), kind),
            view_record("done, its stage silent", job("done", {stage: ("done", "")}), kind),
            view_record("failed in its stage's words", job("failed", {stage: ("failed", "The file is not a "
                                                                                       "caracole's.")},
                                                         output=["error: The file is not a caracole's."]), kind),
            view_record("failed with an error line, its stage ended by the queue", _ended(job(
                "failed", {stage: ("running", "")}, output=["Taking…", "error: database is locked"]), stage), kind),
            view_record("cancelled", _cancelled(job("cancelled")), kind),
            view_record("interrupted while it ran", _ended(job("interrupted", {stage: ("running", "")}), stage,
                                                           "interrupted"), kind),
            view_record("interrupted before it ran", job("interrupted"), kind),
        ]
    nothing_taken = "Nothing taken: no backup of the database first, not enough room."
    records.append(view_record("done, its take failed with no backup first", peer_job(
        "peer-push", "done", {"check": ("done", "1 change from Phone"), "take": ("failed", nothing_taken),
                              "render": ("skipped", ""), "agree": ("skipped", "")},
        units=[("song/radiohead/creep", "left", nothing_taken)]), "peer-push"))
    for kind in ("add", "remove"):
        song = 12
        records += [
            view_record("queued, next", song_job(kind, "queued"), kind, song_id=None if kind == "add" else song),
            view_record("queued behind two", song_job(kind, "queued"), kind, ahead=2,
                        song_id=None if kind == "add" else song),
            view_record("running", song_job(kind, "running"), kind, song_id=song),
            view_record("done", song_job(kind, "done"), kind, song_id=song,  # a removal's: the song it was
                        facts=SongFacts() if kind == "add" else None),
            view_record("failed with an error line", song_job(kind, "failed", output=[
                "ran it", "error: The database is locked. Try again."]), kind, song_id=song),
            view_record("failed with no error line", song_job(kind, "failed", output=["Traceback"]), kind,
                        song_id=song),
            view_record("cancelled", song_job(kind, "cancelled"), kind, song_id=song if kind == "remove" else None),
            view_record("interrupted", song_job(kind, "interrupted"), kind, song_id=song),
        ]
    records.append(view_record("done, a song new to the library", song_job("add", "done"), "add", song_id=None))
    return records


def _ended(job: PyJob, name: str, state: str = "failed") -> PyJob:
    """``job`` with its running stage ``name`` ended by the queue (``JobQueue._run``), its waiting ones skipped."""
    for stage in job.stages:
        if stage.name == name:
            stage.state = state
        elif stage.state == "waiting":
            stage.state = "skipped"
    return job


def _cancelled(job: PyJob) -> PyJob:
    for stage in job.stages:
        stage.state = "skipped"
    return job


# --- the tests -----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    made = Corpus(tmp_path_factory.mktemp("sync-routes-corpus"))
    yield made
    made.close()


def test_sync_routes_jsonl_is_what_the_tabs_routes_answer(corpus, monkeypatch):
    records = route_records(corpus, monkeypatch)
    check(WEB / "sync_routes.jsonl", jsonl(records, corpus="web/sync_routes", made_by=MADE_BY))


def test_job_views_jsonl_is_what_the_views_say_of_each_kind_in_every_state():
    records = view_records()
    states = {(r["job"]["kind"], r["job"]["state"]) for r in records}
    for kind in ("sync", "peer-push", "index-merge", "add", "remove"):
        assert {state for k, state in states if k == kind} == {"queued", "running", "done", "failed", "cancelled",
                                                               "interrupted"}, kind
    check(WEB / "job_views.jsonl", jsonl(records, corpus="web/job_views", made_by=MADE_BY))


def test_a_view_record_is_the_queues_own_job():
    # A job as the queue makes it: what the records' jobs are made like (test_web_sync.peer_job, song_job here).
    queue = JobQueue(Recorder())
    made, _ = queue.submit("Add Radiohead - Creep", KEY, [("Adding to the library", ("add", "--", *SONG))],
                           display="Radiohead - Creep")
    built = song_job("add", "queued", job_id=made.id)
    assert (made.title, made.song_key, made.display, [(s.label, s.args, s.state) for s in made.steps]) == (
        built.title, built.song_key, built.display, [(s.label, s.args, s.state) for s in built.steps])
    assert Stage("take", "Taking what changed there").running_detail == ""
