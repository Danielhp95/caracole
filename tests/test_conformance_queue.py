"""caracole serve's job queue and its request history, for the phone: what android/server's JobQueue, JobCommands and
JobHistory (lane jobs-queue) replay (QueueReplay, QueueVectorsTest).

- ``vectors/web/queue.jsonl``:
  - web/jobs.py's step builders, a record a call: ``{"fn": "caracole.web.jobs.<builder>", "args", "kw", "out":
    [[label, [arg, …]], …]}``;
  - its rules over a job's commands, a command a list of its arguments: ``{"fn": "caracole.web.jobs.<rule>", "args":
    [[[arg, …], …]], "out": …}`` for ``_looks_up`` (of one command), ``_reports`` (of one), ``_fetches``, ``_pick``
    and ``_stages`` (``[[name, label], …]``);
  - queues, a record each: ``{"fn": "caracole.web.jobs.JobQueue", "note", "kw": {"limit", "keep"}, "history": null |
    {"file": <the history's text before the queue starts, or null for none>}, "loaded": {"jobs", "file"}, "ops":
    […]}``. Every op is followed by what the queue answered (``out``), its jobs after it (``jobs``, oldest first, each as
    history.py's line holds it, its output whole; ``as_json``, each as ``Job.as_json`` gives it, ``/api/jobs/N``'s
    answer) and, for a queue with a history, the file's text after it (``file``). An op is one of:

    - ``{"op": "submit", "request": {title, song_key, steps, fetching, note, display, join, song_id}}``: ``out``
      ``{"job": N, "new": bool}`` or ``{"err": "QueueFull"}``;
    - ``{"op": "submit_all", "requests": […]}``: ``out`` ``[[N, new], …]`` or ``{"err": "QueueFull"}``;
    - ``{"op": "cancel", "job": N}``: ``out`` ``{"job": N}``, null, or ``{"err": "JobStarted", "state": …}``;
    - ``{"op": "again", "job": N}``: jobs_routes.again (Try again), ``out`` ``{"job": N}`` or ``{"err": <its
      refusal's status>}``;
    - ``{"op": "run", "steps": [<step>, …]}``: the next job that waits run here (JobQueue._next, _run), ``out`` its id
      or null; each of its commands that runs follows the next step: its ``args`` (what it is run with), its ``do`` in
      order (``{"event": {…}}`` a ``caracole get --progress`` line, of a command that writes them alone; ``{"line":
      …}`` a line it prints; ``{"stop": true}`` the queue stopped (its worker's end, the command ended by it: always
      last); any other an op as above, run while the command runs, with its ``out``, ``jobs`` and ``file``), then its
      exit status ``code`` (0, or null once stopped), a failing one printing ``error: <error>`` first.

  Every time caracole serve's queue and history read (``datetime.now``) is the next second from
  2026-11-03T09:30:00Z, as the phone's replay reads its clock.
- ``vectors/web/history.jsonl``: web/history.py's History (``kw``: keep, days, lines, line_chars, max_bytes) over a
  file (``file``, its text; ``file_b64`` for bytes that aren't text; null for none):
  ``{"fn": "caracole.web.history.History", "note", "kw", "file" | "file_b64", "ops": […]}``, each op with its ``out``:
  ``{"op": "load", "now"}`` (``out`` ``{"jobs", "next", "file"}``, the jobs as their lines hold them, the file after),
  ``{"op": "save", "job": <its line's record>, "jobs": [<records>], "next", "now"}`` (``job`` is ``jobs``' of its id
  when there is one; ``now`` is when a save that writes the file whole reads the time) and ``{"op": "rewrite", "jobs",
  "next"}``, their ``out`` ``{"file"}``: the file's text after it.
  And history.py's ``_time`` (``datetime.fromisoformat``, a naive time UTC) of a request's times, spellings of every
  kind: ``{"fn": "caracole.web.history._time", "args": [text], "out": <microseconds since 1970 UTC>}``, or ``"err":
  "ValueError"`` for one it can't read.
"""

from __future__ import annotations

import base64
import copy
import json
import random
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from helpers.corpus import VECTORS, check, jsonl

from caracole.get import PROGRESS_PREFIX
from caracole.web import history as history_module
from caracole.web import jobs, jobs_routes
from caracole.web.history import History, _job, _record
from caracole.web.jobs import (
    INDEX_MERGE_COMMAND,
    JobQueue,
    JobStarted,
    QueueFull,
    add_steps,
    fetch_steps,
    harptabs_artist_steps,
    lacuerda_artist_steps,
    lacuerda_search_steps,
    lookup_steps,
    remove_steps,
    review_steps,
    version_steps,
)
from caracole.web.pages import Refused

MADE_BY = "tests/test_conformance_queue.py"
WEB = VECTORS / "web"
START = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)
WHOLE = 10**9  # a snapshot's lines and characters: all of them


# --- the clock ----------------------------------------------------------------------------------------------------


class Clock:
    """The next second from START each time it is read."""

    def __init__(self):
        self.at = START - timedelta(seconds=1)

    def now(self) -> datetime:
        self.at += timedelta(seconds=1)
        return self.at


CLOCK = [Clock()]


class FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 (always UTC)
        return CLOCK[0].now()


@pytest.fixture
def ticking(monkeypatch):
    monkeypatch.setattr(jobs, "datetime", FakeDatetime)
    monkeypatch.setattr(history_module, "datetime", FakeDatetime)


# --- the builders and the rules -----------------------------------------------------------------------------------

TAB = "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-chords-6789"
TAB_B = "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-chords-6790"

BUILDERS = [
    (add_steps, ["Radiohead", "Creep"], {}),
    (add_steps, ["-Ñu-", "Song -- 2"], {"album": "Pablo Honey", "duration_ms": 238_499, "lacuerda": "ñu/song"}),
    (add_steps, ["A", "T"], {"album": "", "duration_ms": 0, "lacuerda": ""}),
    (add_steps, ["A", "T"], {"duration_ms": 3_599_500}),
    (add_steps, ["A", "T"], {"duration_ms": 3_725_000}),
    (fetch_steps, ["Radiohead - Creep"], {}),
    (lookup_steps, ["Radiohead", "Creep"], {}),
    (lookup_steps, ["Oasis", "Wonderwall"], {"album": "(What's the Story) Morning Glory?", "duration_ms": 258_600,
                                            "ug": "oasis/wonderwall", "tab": TAB, "lacuerda": "oasis/wonderwall",
                                            "harptabs": "/song/12", "gametabs": "/tab/3", "songbooks": False}),
    (lookup_steps, ["A", "T"], {"songbooks": False}),
    (lookup_steps, ["A", "T"], {"album": "", "ug": "", "tab": None}),
    (version_steps, ["Oasis", "Wonderwall"], {"choose": TAB}),
    (version_steps, ["Oasis", "Wonderwall"], {"keep": "6789"}),
    (version_steps, ["Oasis", "Wonderwall"], {"keep_more": True}),
    (version_steps, ["Oasis", "Wonderwall"], {}),
    (version_steps, ["A - B", "C"], {"choose": "", "keep": "1"}),
    (remove_steps, ["Radiohead - Creep"], {}),
    (review_steps, ["Radiohead - Creep"], {"pick": "radiohead/creep"}),
    (review_steps, ["Radiohead - Creep"], {"seen": ["a/b", "c/d"]}),
    (review_steps, ["Radiohead - Creep"], {}),
    (lacuerda_artist_steps, ["estopa", "Estopa"], {}),
    (lacuerda_search_steps, ["tu calorro"], {"auto": True}),
    (lacuerda_search_steps, ["tu calorro"], {"auto": False}),
    (harptabs_artist_steps, ["/artist/12", "Bob Dylan"], {}),
]


def builder_records() -> list[dict[str, Any]]:
    return [{"fn": f"caracole.web.jobs.{fn.__name__}", "args": args, "kw": kw,
             "out": [[label, list(argv)] for label, argv in fn(*args, **kw)]} for fn, args, kw in BUILDERS]


def _argv(steps) -> list[list[str]]:
    return [list(argv) for _, argv in steps]


COMMANDS: list[list[list[str]]] = [
    [],
    _argv(add_steps("A", "T")),
    _argv(lookup_steps("A", "T")),
    _argv(lookup_steps("A", "T", ug="a/t", tab=TAB, lacuerda="a/t", harptabs="/h", gametabs="/g")),
    _argv(add_steps("A", "T") + fetch_steps("A - T")),
    _argv(version_steps("A", "T", choose=TAB)),
    _argv(version_steps("A", "T", keep="12")),
    _argv(version_steps("A", "T", keep_more=True)),
    _argv(version_steps("A", "T")),
    _argv(version_steps("A", "T", keep="12") + lookup_steps("A", "T")),
    _argv(version_steps("A", "T", keep="12") + version_steps("A", "T", keep="13")),
    _argv(lacuerda_search_steps("q", auto=True)),
    _argv(lacuerda_artist_steps("estopa", "Estopa")),
    _argv(harptabs_artist_steps("/a/1", "Dylan")),
    _argv(review_steps("A - T", pick="a/t")),
    _argv(remove_steps("A - T")),
    [["youtube", "--sheet", "--progress", "--url=https://www.youtube.com/watch?v=x", "--song=A - T"]],
    [["youtube", "--search=a t", "--progress"]],
    [["youtube", "--video=dQw4w9WgXcQ", "--progress"]],
    [["peer", "take", "--progress", "/state/peer/push-1"]],
    [["peer", "sync", "--push", "--progress", "--compared", "ab", "--", "http://laptop:8737"]],
    [["peer", "import", "--yes", "--progress", "--compared=ab", "--", "/state/peer/import-0123456789abcdef"]],
    [["peer", "sync", "--", "--progress"]],
    [["peer", "pull", "--progress"]],
    [[*INDEX_MERGE_COMMAND, "--delete", "--progress", "--", "/x.sqlite"]],
    [["index", "merge", "--", "--progress"]],
    [["get", "--", "--ug=x", "--tab=y"]],
    [["versions", "--", "--clear", "--choose=x"]],
    [["versions", "--keep=1", "--progress"], ["get", "--progress", "--tab=2", "--", "A", "T"]],
    [["lacuerda", "--progress", "--", "--search=q"]],
    [["lacuerda", "--search=q"]],
    [["fetch", "--song=A - T"], ["render", "--song=A - T"]],
    [["get"]],
    [["match"]],
]


def rule_records() -> list[dict[str, Any]]:
    from caracole.web.jobs import Step, _fetches, _looks_up, _pick, _reports, _stages

    records = []
    for commands in COMMANDS:
        steps = [Step("x", tuple(argv)) for argv in commands]
        for argv in commands:
            records.append({"fn": "caracole.web.jobs._looks_up", "args": [argv], "out": _looks_up(tuple(argv))})
            records.append({"fn": "caracole.web.jobs._reports", "args": [argv], "out": _reports(tuple(argv))})
        records.append({"fn": "caracole.web.jobs._fetches", "args": [commands], "out": _fetches(steps)})
        records.append({"fn": "caracole.web.jobs._pick", "args": [commands], "out": list(_pick(steps))})
        records.append({"fn": "caracole.web.jobs._stages", "args": [commands],
                        "out": [[s.name, s.label] for s in _stages(steps)]})
    return records


# --- queues --------------------------------------------------------------------------------------------------------


def request(title: str, song_key: str, steps, *, fetching: bool = False, note: str = "", display: str = "",
            join: bool = True, song_id: int | None = None) -> dict[str, Any]:
    return {"title": title, "song_key": song_key, "steps": [[label, list(argv)] for label, argv in steps],
            "fetching": fetching, "note": note, "display": display, "join": join, "song_id": song_id}


def submit(*args, **kw) -> dict[str, Any]:
    return {"op": "submit", "request": request(*args, **kw)}


def submit_all(*requests) -> dict[str, Any]:
    return {"op": "submit_all", "requests": list(requests)}


def cancel(job: int) -> dict[str, Any]:
    return {"op": "cancel", "job": job}


def again(job: int) -> dict[str, Any]:
    return {"op": "again", "job": job}


def run(*steps) -> dict[str, Any]:
    return {"op": "run", "steps": list(steps)}


def step(args, *do, code: int | None = 0, error: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"args": list(args), "do": list(do), "code": code}
    if error is not None:
        out["error"] = error
    return out


def event(stage: str | None = None, state: str | None = None, detail: str = "", **more) -> dict[str, Any]:
    said = {} if stage is None else {"stage": stage, "state": state, "detail": detail}
    return {"event": {**said, **more}}


def line(text: str) -> dict[str, Any]:
    return {"line": text}


STOP = {"stop": True}


class _App:
    """What jobs_routes.again asks of caracole serve's WebApp: its queue, its submit (QueueFull a 503) and queued."""

    def __init__(self, queue: JobQueue):
        self.queue = queue
        self._searching = threading.Lock()
        self._reads: set[int] = set()

    def submit(self, title, song_key, steps, *, full: str = "", **options):
        try:
            return self.queue.submit(title, song_key, steps, **options)
        except QueueFull:
            raise Refused(503, "The queue is full", full) from None

    def queued(self, job, location=None):  # noqa: ARG002
        return job


class Script:
    """The queue's runner: each command it runs follows the next step of the op that runs it."""

    def __init__(self):
        self.pending: list[dict[str, Any]] = []
        self.queue: JobQueue | None = None
        self.perform = None
        self.errors: list[str] = []

    def __call__(self, args, emit) -> int | None:
        try:
            return self._follow(args, emit)
        except Exception as e:  # the queue would take it for a command that couldn't start: the script is wrong
            self.errors.append(f"{args}: {e!r}")
            raise

    def _follow(self, args, emit) -> int | None:
        step = self.pending.pop(0)
        assert step["args"] == list(args), (step["args"], args)
        for n, action in enumerate(step["do"]):
            if "event" in action:
                assert jobs._reports(tuple(args)), f"{args} writes no progress line"
                emit(PROGRESS_PREFIX + json.dumps(action["event"]))
            elif "line" in action:
                emit(action["line"])
            elif "stop" in action:
                assert n == len(step["do"]) - 1 and step["code"] is None and "error" not in step
                self.queue._stopping = True
            else:
                step["do"][n] = self.perform(action)
        if step.get("error") is not None:
            assert step["code"] not in (0, None)
            emit("error: " + step["error"])
        else:
            assert step["code"] == 0 or self.queue._stopping, "a failing command says why"
        return step["code"]


def queue_record(note: str, ops: list[dict[str, Any]], *, limit: int = jobs.LIMIT, keep: int = jobs.KEEP,
                 history: dict[str, Any] | None = None, tmp: Path) -> dict[str, Any]:
    CLOCK[0] = Clock()
    path = tmp / f"requests-{len(list(tmp.iterdir()))}.jsonl"
    hist = None
    if history is not None:
        if history.get("file") is not None:
            path.write_text(history["file"], encoding="utf-8")
        hist = History(path)
    script = Script()
    queue = JobQueue(script, limit=limit, keep=keep, history=hist)
    app = _App(queue)
    stopped = [False]

    def state() -> dict[str, Any]:
        out: dict[str, Any] = {"jobs": [_record(job, WHOLE, WHOLE) for job in queue._jobs],
                               "as_json": [job.as_json() for job in queue._jobs]}
        if hist is not None:
            out["file"] = path.read_text(encoding="utf-8") if path.exists() else None
        return out

    def perform(op: dict[str, Any]) -> dict[str, Any]:
        op = copy.deepcopy(op)
        kind = op["op"]
        if kind == "submit":
            try:
                job, new = queue.submit(**_kw(op["request"]))
                out: Any = {"job": job.id, "new": new}
            except QueueFull:
                out = {"err": "QueueFull"}
        elif kind == "submit_all":
            try:
                out = [[job.id, new] for job, new in queue.submit_all([_kw(r) for r in op["requests"]])]
            except QueueFull:
                out = {"err": "QueueFull"}
        elif kind == "cancel":
            try:
                job = queue.cancel(op["job"])
                out = {"job": job.id} if job is not None else None
            except JobStarted as e:
                out = {"err": "JobStarted", "state": e.state}
        elif kind == "again":
            try:
                out = {"job": jobs_routes.again(app, {"job": str(op["job"])}).id}
            except Refused as e:
                out = {"err": e.status}
        elif kind == "run":
            assert not stopped[0], "nothing runs once the queue stopped"
            script.pending = list(op["steps"])  # the steps stay in the record, their ops filled in
            job = queue._next()
            if job is not None:
                queue._run(job)
            assert not script.pending, f"steps left: {script.pending}"
            assert not script.errors, script.errors
            stopped[0] = queue._stopping
            out = job.id if job is not None else None
        else:
            raise AssertionError(f"no such op: {kind}")
        return {**op, "out": out, **state()}

    script.queue, script.perform = queue, perform
    record = {"fn": "caracole.web.jobs.JobQueue", "note": note, "kw": {"limit": limit, "keep": keep},
              "history": history, "loaded": state()}
    record["ops"] = [perform(op) for op in ops]
    return record


def _kw(req: dict[str, Any]) -> dict[str, Any]:
    return {"title": req["title"], "song_key": req["song_key"], "steps": [(label, tuple(a)) for label, a in req["steps"]],
            "fetching": req["fetching"], "note": req["note"], "display": req["display"], "join": req["join"],
            "song_id": req["song_id"]}


CREEP = ("Radiohead", "Creep")
KEY = "radiohead/creep"
WALL = "oasis/wonderwall"
GET_CREEP = lookup_steps(*CREEP)
ADD_CREEP = add_steps(*CREEP)
FETCH_CREEP = add_steps(*CREEP) + fetch_steps("Radiohead - Creep")
REVIEW = review_steps("Radiohead - Creep", pick="radiohead/creep")
GET_ARGS = GET_CREEP[0][1]


def lookup_events(*, fail: str | None = None) -> list[dict[str, Any]]:
    """What a `caracole get --progress` of Radiohead - Creep says, its sheet failing in [fail]'s words if given."""
    said = [event("song", "running"), event(song={"id": 7, "display": "Radiohead - Creep"}),
            event("song", "done", "added to wanted.txt, line 16"), event("match", "running"),
            event("match", "done", "matched to radiohead/creep"), event("sheet", "running", "asking Ultimate Guitar"),
            line("get: tab 4169 from Ultimate Guitar")]
    if fail is not None:
        return said + [event("sheet", "failed", fail)]
    return said + [event("sheet", "done", "tab 4169 from Ultimate Guitar"),
                   event(files={"sheet": "Radiohead/Creep/sheet.txt"}, seconds=2.25),
                   event("lyrics", "running")]


def scenarios() -> list[tuple[str, list[dict[str, Any]], dict[str, Any]]]:
    keep_it = version_steps("A", "T", keep="123")
    get_at = lookup_steps("A", "T")
    out: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = [
        ("a lookup takes the place of a waiting add of the same song", [
            submit("Add Radiohead - Creep", KEY, ADD_CREEP, note="Added to wanted.txt, line 3."),
            submit("Get Radiohead - Creep", KEY, GET_CREEP, fetching=True, note="a note of its own"),
            run(step(GET_ARGS, *lookup_events())),
            submit("Get Radiohead - Creep", KEY, GET_CREEP, fetching=True),  # over: a job of its own
        ], {}),
        ("an add never replaces a lookup, nor a fetch, of the same song", [
            submit("Get Radiohead - Creep", KEY, GET_CREEP, fetching=True),
            submit("Add Radiohead - Creep", KEY, ADD_CREEP),
            submit("Fetch Muse - Hysteria", "muse/hysteria", fetch_steps("Muse - Hysteria"), fetching=True),
            submit("Add Muse - Hysteria", "muse/hysteria", add_steps("Muse", "Hysteria")),
        ], {}),
        ("a fetch joins a waiting add, its add once whatever its album", [
            submit("Add Radiohead - Creep", KEY, add_steps(*CREEP, album="Pablo Honey"), note="line 3"),
            submit("Fetch Radiohead - Creep", KEY, FETCH_CREEP, fetching=True),
            run(step(add_steps(*CREEP, album="Pablo Honey")[0][1], line("added")), step(["match"]),
                step(["fetch", "--song=Radiohead - Creep"]), step(["render", "--song=Radiohead - Creep"])),
        ], {}),
        ("a fetch, then an add, asked while the song's add runs come after it", [
            submit("Add Radiohead - Creep", KEY, ADD_CREEP),
            run(step(ADD_CREEP[0][1], submit("Fetch Radiohead - Creep", KEY, FETCH_CREEP, fetching=True),
                     submit("Add Radiohead - Creep", KEY, ADD_CREEP), line("added"))),
            run(step(ADD_CREEP[0][1]), step(["match"]), step(["fetch", "--song=Radiohead - Creep"]),
                step(["render", "--song=Radiohead - Creep"])),
        ], {}),
        ("a lookup asked while the song's add runs comes after it, and the add after joins it", [
            submit("Add Radiohead - Creep", KEY, ADD_CREEP),
            run(step(ADD_CREEP[0][1], submit("Get Radiohead - Creep", KEY, GET_CREEP, fetching=True),
                     submit("Add Radiohead - Creep", KEY, ADD_CREEP))),
            run(step(GET_ARGS, event("song", "running"), event("song", "done"))),
        ], {}),
        ("a pick that mustn't join gets the song's job unchanged, waiting or running", [
            submit("Add Radiohead - Creep", KEY, ADD_CREEP),
            submit("Pick", KEY, REVIEW, fetching=True, join=False),
            run(step(ADD_CREEP[0][1], submit("Pick", KEY, REVIEW, fetching=True, join=False))),
            submit("Pick", KEY, REVIEW, join=False),  # once it ended
        ], {}),
        ("a version picked while the song's lookup runs is looked up after it", [
            submit("Fetch Oasis - Wonderwall", WALL, lookup_steps("Oasis", "Wonderwall", ug=WALL), fetching=True),
            run(step(lookup_steps("Oasis", "Wonderwall", ug=WALL)[0][1], event("song", "running"),
                     submit("Fetch Oasis - Wonderwall", WALL, lookup_steps("Oasis", "Wonderwall", ug=WALL, tab=TAB),
                            fetching=True),
                     submit("Fetch Oasis - Wonderwall", WALL, lookup_steps("Oasis", "Wonderwall", ug=WALL),
                            fetching=True))),
            run(step(lookup_steps("Oasis", "Wonderwall", ug=WALL)[0][1])),
        ], {}),
        ("a newer pick replaces the one still waiting, and the same pick is the same job", [
            submit("Fetch Oasis - Wonderwall", WALL, lookup_steps("Oasis", "Wonderwall", ug=WALL), fetching=True),
            submit("Fetch Oasis - Wonderwall", WALL, lookup_steps("Oasis", "Wonderwall", ug=WALL, tab=TAB),
                   fetching=True),
            submit("Fetch Oasis - Wonderwall", WALL, lookup_steps("Oasis", "Wonderwall", ug=WALL, tab=TAB),
                   fetching=True),
            submit("Fetch Oasis - Wonderwall", WALL, lookup_steps("Oasis", "Wonderwall"), fetching=True),
            submit("Fetch Oasis - Wonderwall", WALL, lookup_steps("Oasis", "Wonderwall", tab=TAB_B), fetching=True),
            submit("Make it the one", WALL, version_steps("Oasis", "Wonderwall", choose=TAB), fetching=True),
            submit("Back to caracole's pick", WALL, version_steps("Oasis", "Wonderwall"), fetching=True),
        ], {}),
        ("a lookup joins a waiting Keep it and starts its stages afresh after it", [
            submit("Keep it", "a/t", keep_it, fetching=True),
            submit("Fetch A - T", "a/t", get_at, fetching=True),
            submit("Fetch A - T", "a/t", get_at, fetching=True),
            submit("Keep another", "a/t", version_steps("A", "T", keep="124"), fetching=True),
            run(step(keep_it[0][1], event("song", "running"), event("song", "done", "in the library"),
                     event("version", "running"), event("version", "done", "tab 123 kept"),
                     event("pdf", "running"), event("pdf", "done", "made"), event("pages", "running"),
                     event("pages", "done")),
                step(get_at[0][1], event("song", "running"), event("song", "done", "in the library"),
                     event("match", "running"), event("match", "done", "matched to a/t"), event("sheet", "running"),
                     submit("Keep it", "a/t", keep_it, fetching=True)),
                step(version_steps("A", "T", keep="124")[0][1])),
        ], {}),
        ("a lookup asked while the song's Keep it runs comes after it", [
            submit("Keep it", "a/t", keep_it, fetching=True),
            run(step(keep_it[0][1], submit("Fetch A - T", "a/t", get_at, fetching=True),
                     submit("Fetch A - T", "a/t", get_at, fetching=True),
                     submit("Fetch them", "a/t", version_steps("A", "T", keep_more=True), fetching=False))),
            run(step(get_at[0][1]), step(version_steps("A", "T", keep_more=True)[0][1])),
        ], {}),
        ("a full queue takes no new job, a job that joins needs no room, a cancel makes room", [
            submit("Get A", "a/1", lookup_steps("A", "1"), fetching=True),
            submit("Get B", "b/1", lookup_steps("B", "1"), fetching=True),
            submit("Get C", "c/1", lookup_steps("C", "1"), fetching=True),
            submit("Get B", "b/1", lookup_steps("B", "1"), fetching=True),
            submit("Add A", "a/1", add_steps("A", "1")),
            cancel(2),
            submit("Get C", "c/1", lookup_steps("C", "1"), fetching=True),
        ], {"limit": 2}),
        ("cancel takes a waiting job out, never one that runs or is over", [
            submit("Get A", "a/1", lookup_steps("A", "1"), fetching=True),
            submit("Get B", "b/1", lookup_steps("B", "1"), fetching=True),
            run(step(lookup_steps("A", "1")[0][1], cancel(1), cancel(2), cancel(2), cancel(99))),
            cancel(1),
            submit("Get B", "b/1", lookup_steps("B", "1"), fetching=True),  # a cancelled job is nobody's answer
            run(step(lookup_steps("B", "1")[0][1])),
        ], {}),
        ("jobs queued together are cancelled together while they wait, and a full queue queues none", [
            submit("Get A", "a/1", lookup_steps("A", "1"), fetching=True),
            submit("Add B", "b/1", add_steps("B", "1")),
            submit_all(request("Get B", "b/1", lookup_steps("B", "1"), fetching=True),
                       request("Get C", "c/1", lookup_steps("C", "1"), fetching=True),
                       request("Get D", "d/1", lookup_steps("D", "1"), fetching=True),
                       request("Get E", "e/1", lookup_steps("E", "1"), fetching=True),
                       request("Get F", "f/1", lookup_steps("F", "1"), fetching=True)),
            submit_all(request("Get B", "b/1", lookup_steps("B", "1"), fetching=True),
                       request("Get C", "c/1", lookup_steps("C", "1"), fetching=True),
                       request("Add C - 1 to Campfire", "songbook\x1fsongbook\x1fadd\x1f--\x1fCampfire",
                               [("Adding to the songbook", ("songbook", "add", "--", "Campfire", "C - 1"))]),
                       request("Get D", "d/1", lookup_steps("D", "1"), fetching=True)),
            run(step(lookup_steps("A", "1")[0][1], cancel(4))),
            submit_all(request("Get A", "a/1", lookup_steps("A", "1"), fetching=True)),
            submit_all(),
        ], {"limit": 5}),
        ("the last jobs over are remembered, the others forgotten, and ids go on", [
            submit("Get A", "a/1", lookup_steps("A", "1"), fetching=True),
            submit("Get B", "b/1", lookup_steps("B", "1"), fetching=True),
            submit("Get C", "c/1", lookup_steps("C", "1"), fetching=True),
            run(step(lookup_steps("A", "1")[0][1])),
            run(step(lookup_steps("B", "1")[0][1])),
            cancel(3),
            submit("Get D", "d/1", lookup_steps("D", "1"), fetching=True),
            run(step(lookup_steps("D", "1")[0][1])),
            run(),
        ], {"keep": 2}),
        ("a command that fails stops its job, the rest skipped, its running stage failed", [
            submit("Fetch Radiohead - Creep", KEY, fetch_steps("Radiohead - Creep"), fetching=True),
            submit("Get Muse - Hysteria", "muse/hysteria", lookup_steps("Muse", "Hysteria"), fetching=True),
            submit("Get Blur - Song 2", "blur/song 2", lookup_steps("Blur", "Song 2"), fetching=True),
            run(step(["match"], line("matching")), step(["fetch", "--song=Radiohead - Creep"], line("asking UG"),
                                                         code=1, error="Ultimate Guitar answered 500.")),
            run(step(lookup_steps("Muse", "Hysteria")[0][1], *lookup_events(fail="Ultimate Guitar blocked caracole."),
                     code=2, error="Ultimate Guitar blocked caracole.")),
            run(step(lookup_steps("Blur", "Song 2")[0][1], event("song", "running"), event("song", "done"),
                     event("sheet", "running", "asking LaCuerda"), code=1, error="database is locked")),
        ], {}),
        ("versions --choose and --clear are lookups; Keep it and Fetch them aren't", [
            submit("Keep it", WALL, version_steps("Oasis", "Wonderwall", keep="6789"), fetching=True),
            submit("Fetch them", WALL, version_steps("Oasis", "Wonderwall", keep_more=True), fetching=True),
            submit("Make it the one", WALL, version_steps("Oasis", "Wonderwall", choose=TAB), fetching=True),
            submit("Make it the one", WALL, version_steps("Oasis", "Wonderwall", choose=TAB), fetching=True),
            submit("Back to caracole's pick", WALL, version_steps("Oasis", "Wonderwall"), fetching=True),
            submit("Get it", WALL, lookup_steps("Oasis", "Wonderwall"), fetching=True),
            submit("Keep it", "a/t", keep_it, fetching=True),
            submit("Keep it", "a/t", keep_it, fetching=True),
            submit("Back to caracole's pick", "a/t", version_steps("A", "T"), fetching=True),
            run(step(version_steps("Oasis", "Wonderwall", keep="6789")[0][1], event("version", "done", "kept")),
                step(version_steps("Oasis", "Wonderwall", keep_more=True)[0][1]),
                step(version_steps("Oasis", "Wonderwall", choose=TAB)[0][1], event("song", "running")),
                step(version_steps("Oasis", "Wonderwall")[0][1], event("sheet", "done", "tab 6789"))),
        ], {}),
        ("a site's index reads and LaCuerda's search are jobs of their own", [
            submit("LaCuerda's search for tu calorro", "lacuerda-search:calorro tu",
                   lacuerda_search_steps("tu calorro", auto=True)),
            submit("LaCuerda's search for tu calorro", "lacuerda-search:calorro tu",
                   lacuerda_search_steps("tu calorro", auto=False)),
            submit("Estopa on LaCuerda", "lacuerda-artist:estopa", lacuerda_artist_steps("estopa", "Estopa")),
            submit("Bob Dylan on harptabs.com", "harptabs-artist:/artist/12",
                   harptabs_artist_steps("/artist/12", "Bob Dylan")),
            run(step(lacuerda_search_steps("tu calorro", auto=True)[0][1], event("search", "running"),
                     line("searching"), event("search", "done", "12 songs"))),
            run(step(lacuerda_artist_steps("estopa", "Estopa")[0][1], line("Estopa: 31 songs"),
                     line(PROGRESS_PREFIX + json.dumps({"stage": "song", "state": "done"})))),
        ], {}),
        ("Try again queues a job over again, by hand, with its songbooks", [
            submit("Get Radiohead - Creep", KEY, lookup_steps(*CREEP, songbooks=False), fetching=True,
                   note="from Campfire", display="Radiohead - Creep", song_id=7),
            submit("LaCuerda's search for tu calorro", "lacuerda-search:calorro tu",
                   lacuerda_search_steps("tu calorro", auto=True)),
            submit("Pick", "muse/hysteria", review_steps("Muse - Hysteria", pick="muse/hysteria"), fetching=True,
                   join=False),
            again(1),
            again(99),
            run(step(lookup_steps(*CREEP, songbooks=False)[0][1], event("song", "running"),
                     code=1, error="Ultimate Guitar answered 500.")),
            again(1),
            again(1),
            run(step(lacuerda_search_steps("tu calorro", auto=True)[0][1], event("search", "done", "none"))),
            again(2),
            run(step(review_steps("Muse - Hysteria", pick="muse/hysteria")[0][1])),
            submit("Add Muse - Hysteria", "muse/hysteria", add_steps("Muse", "Hysteria")),
            again(3),
        ], {}),
        ("Try again of a full queue is refused", [
            submit("Get A", "a/1", lookup_steps("A", "1"), fetching=True),
            run(step(lookup_steps("A", "1")[0][1])),
            submit("Get B", "b/1", lookup_steps("B", "1"), fetching=True),
            again(1),
        ], {"limit": 1}),
        ("the queue's end interrupts the command that runs, the rest skipped", [
            submit("Fetch Radiohead - Creep", KEY, add_steps(*CREEP) + fetch_steps("Radiohead - Creep"), fetching=True),
            submit("Get Muse - Hysteria", "muse/hysteria", lookup_steps("Muse", "Hysteria"), fetching=True),
            run(step(ADD_CREEP[0][1]), step(["match"], line("matching"), STOP, code=None)),
            submit("Get Blur - Song 2", "blur/song 2", lookup_steps("Blur", "Song 2"), fetching=True),
            cancel(2),
        ], {}),
        ("a lookup interrupted while a stage runs", [
            submit("Get Radiohead - Creep", KEY, GET_CREEP, fetching=True),
            run(step(GET_ARGS, event("song", "running"), event("song", "done"), event("sheet", "running", "asking"),
                     STOP, code=None)),
        ], {}),
        ("a command's output keeps its last 400 lines", [
            submit("Fetch Radiohead - Creep", KEY, fetch_steps("Radiohead - Creep"), fetching=True),
            run(step(["match"], *[line(f"line {n}") for n in range(1, 404)]), step(["fetch", "--song=Radiohead - Creep"],
                line("the last line")), step(["render", "--song=Radiohead - Creep"])),
        ], {}),
        ("a lookup's progress: its song, its files, a stage it names that it has not", [
            submit("Get Radiohead - Creep", KEY, GET_CREEP, fetching=True),
            run(step(GET_ARGS, *lookup_events(), event("extra", "running", "more"),
                     event(files={"pdf": "Radiohead/Creep/sheet.pdf"}, seconds=9),
                     event("lyrics", "done", "plain lyrics", song={"id": 8, "display": "Radiohead - Creep (live)"}),
                     event("extra", "done"))),
        ], {}),
        ("the stages of a sheet from YouTube, a sync and an index merge", [
            submit("Make the sheet", "youtube:radiohead/creep",
                   jobs.youtube_sheet_steps("Radiohead - Creep", "https://www.youtube.com/watch?v=x")),
            submit("Search YouTube", "youtube-search:creep radiohead", jobs.youtube_search_steps("radiohead creep")),
            submit("Sync with Laptop", "sync:http://laptop:8737",
                   [("Sync with Laptop", ("peer", "sync", "--push", "--progress", "--", "http://laptop:8737"))],
                   join=False),
            submit("Index pages from another caracole", "index-merge:x.sqlite",
                   jobs.index_merge_job(Path("/state/peer/x.sqlite"))["steps"], join=False),
            submit("Sync with Laptop", "sync:http://laptop:8737",
                   [("Sync with Laptop", ("peer", "sync", "--push", "--progress", "--", "http://laptop:8737"))],
                   join=False),
        ], {}),
        ("a queue saves each job to its history as it changes", [
            submit("Add Radiohead - Creep", KEY, ADD_CREEP, note="line 3"),
            submit("Get Radiohead - Creep", KEY, GET_CREEP, fetching=True),
            submit("Get Muse - Hysteria", "muse/hysteria", lookup_steps("Muse", "Hysteria"), fetching=True),
            run(step(GET_ARGS, *lookup_events(), submit("Get Radiohead - Creep", KEY, GET_CREEP, fetching=True))),
            cancel(2),
            submit_all(request("Get A", "a/1", lookup_steps("A", "1"), fetching=True),
                       request("Get B", "b/1", lookup_steps("B", "1"), fetching=True)),
            cancel(4),
        ], {"history": {"file": None}}),
    ]
    restarted = _history_file([
        {"v": 1, "next": 9},
        {**_line(3, "Get Radiohead - Creep", KEY, GET_CREEP, "done", fetching=True), "song_id": 7,
         "song_display": "Radiohead - Creep", "files": {"sheet": "Radiohead/Creep/sheet.txt"},
         "seconds_to_sheet": 2.5},
        _line(5, "Get Muse - Hysteria", "muse/hysteria", lookup_steps("Muse", "Hysteria"), "running", fetching=True,
              step_state="running", stages=[["song", "Find the song", "done", "", ""],
                                            ["sheet", "The sheet", "running", "asking", "asking"],
                                            ["pdf", "The PDF", "waiting", "", ""]]),
        _line(6, "Get Blur - Song 2", "blur/song 2", lookup_steps("Blur", "Song 2"), "queued", fetching=True),
        _line(7, "LaCuerda's search", "lacuerda-search:q", lacuerda_search_steps("q", auto=True), "done"),
    ])
    out.append(("a queue starts from its history: what waited or ran interrupted, the ids after theirs", [
        submit("Get Muse - Hysteria", "muse/hysteria", lookup_steps("Muse", "Hysteria"), fetching=True),
        again(5),
        again(7),
        run(step(lookup_steps("Muse", "Hysteria")[0][1])),
        again(3),
    ], {"history": {"file": restarted}}))
    return out


def _line(job_id: int, title: str, key: str, steps, state: str, *, fetching: bool = False, step_state: str | None = None,
          stages: list[list[str]] | None = None) -> dict[str, Any]:
    """A request as caracole serve's history holds it: queued at 2026-11-02 08:00, started and over a minute later as
    its state says."""
    queued = "2026-11-02T08:00:00+00:00"
    started = "2026-11-02T08:01:00+00:00" if state != "queued" else None
    over = "2026-11-02T08:02:00+00:00" if state not in ("queued", "running") else None
    steps_state = step_state or {"done": "done", "failed": "failed", "queued": "waiting", "running": "running",
                                 "cancelled": "skipped", "interrupted": "interrupted"}[state]
    return {"v": 1, "id": job_id, "title": title, "song_key": key, "display": title, "state": state,
            "fetching": fetching, "note": "", "queued_at": queued, "started_at": started, "finished_at": over,
            "steps": [{"label": label, "args": list(argv), "state": steps_state, "code": 0 if state == "done" else None,
                       "output": ["ran"] if state != "queued" else [], "dropped": 0} for label, argv in steps],
            "stages": [{"name": n, "label": label, "state": s, "detail": d, "running_detail": r}
                       for n, label, s, d, r in (stages or [])],
            "song_id": None, "song_display": None, "files": {}, "seconds_to_sheet": None, "together": [], "units": []}


def _history_file(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in records)


def queue_records(tmp: Path) -> list[dict[str, Any]]:
    return [queue_record(note, ops, tmp=tmp, **options) for note, ops, options in scenarios()]


# --- the history ----------------------------------------------------------------------------------------------------


def _text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def history_record(note: str, ops: list[dict[str, Any]], *, file: str | bytes | None = None, tmp: Path,
                   **kw) -> dict[str, Any]:
    path = tmp / f"h-{len(list(tmp.iterdir()))}" / "requests.jsonl"
    path.parent.mkdir()
    if file is not None:
        path.write_bytes(file.encode("utf-8") if isinstance(file, str) else file)
    hist = History(path, **kw)
    done = []
    for op in ops:
        op = copy.deepcopy(op)
        if op["op"] == "load":
            jobs_, next_id = hist.load(datetime.fromisoformat(op["now"]))
            op["out"] = {"jobs": [_record(job, WHOLE, WHOLE) for job in jobs_], "next": next_id, "file": _text(path)}
        elif op["op"] == "save":
            listed = [_job(r) for r in op["jobs"]]
            job = next((j for j in listed if j.id == op["job"]["id"]), None) or _job(op["job"])
            CLOCK[0] = _Fixed(datetime.fromisoformat(op["now"]))
            hist.save(job, listed, op["next"])
            op["out"] = {"file": _text(path)}
        elif op["op"] == "rewrite":
            hist.rewrite([_job(r) for r in op["jobs"]], op["next"])
            op["out"] = {"file": _text(path)}
        done.append(op)
    record: dict[str, Any] = {"fn": "caracole.web.history.History", "note": note, "kw": kw}
    if isinstance(file, bytes):
        record["file_b64"] = base64.b64encode(file).decode("ascii")
    else:
        record["file"] = file
    record["ops"] = done
    return record


class _Fixed:
    def __init__(self, at: datetime):
        self.at = at

    def now(self) -> datetime:
        return self.at


NOW = "2026-11-03T12:00:00+00:00"
KW = {"keep": 100, "days": 30, "lines": 200, "line_chars": 1000, "max_bytes": 4 * 1024 * 1024}


def _job_line(job_id: int, state: str = "done", *, at: str = "2026-11-02T08:00:00+00:00", **more) -> dict[str, Any]:
    record = _line(job_id, f"Get Song {job_id}", f"artist/song {job_id}", lookup_steps("Artist", f"Song {job_id}"),
                   state, fetching=True)
    record["queued_at"] = at
    if record["started_at"]:
        record["started_at"] = at
    if record["finished_at"]:
        record["finished_at"] = at
    return {**record, **more}


def history_cases() -> list[tuple[str, list[dict[str, Any]], dict[str, Any]]]:
    load = {"op": "load", "now": NOW}
    good = [_job_line(1), _job_line(2, "failed"), _job_line(3, "cancelled")]
    lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in good]
    long_output = [f"line {n}" for n in range(250)] + ["x" * 1200, "é" * 999 + "🎸🎸", "🎸" * 1000]
    rich = _job_line(4)
    rich["steps"][0]["output"] = long_output
    rich["steps"][0]["dropped"] = 7
    rich.update({"files": {"sheet": "Artist/Song 4/sheet.txt", "pdf": "Artist/Song 4/sheet.pdf"},
                 "seconds_to_sheet": 3, "together": [4, 5], "units": [["song/a/b", "taken", ""],
                                                                       ["songbook/x", "left", "changed here"]],
                 "song_id": 12, "song_display": "Artist - Song 4", "note": "a note",
                 "stages": [{"name": "song", "label": "Find the song", "state": "done", "detail": "in the library",
                             "running_detail": "looking"}, {"name": "pdf", "label": "The PDF"}]})
    times = [_job_line(10, at="2026-11-02T09:00:00Z"), _job_line(11, at="2026-11-02T10:00:00+01:00"),
             _job_line(12, at="2026-11-02T09:00:00"), _job_line(13, at="2026-11-02T09:00:00.123456+00:00"),
             _job_line(14, at="2026-11-02T09:00:00.5+00:00"), _job_line(15, at="2026-11-02 09:00"),
             _job_line(16, at="20261102T090000"), _job_line(17, at="2026-11-02T09:00:00.1234567-02:30"),
             _job_line(18, at="2026-11-02T24:00:00")]
    bad = [
        '{"v":1,"id":20,"title":"cut sh',
        "not json at all",
        json.dumps({**_job_line(21), "v": 2}),
        json.dumps({k: v for k, v in _job_line(22).items() if k != "title"}),
        json.dumps({**_job_line(23), "id": "23"}),
        json.dumps({**_job_line(24), "id": 24.0}),
        json.dumps({**_job_line(25), "id": True}),
        json.dumps({**_job_line(26), "fetching": None}),
        json.dumps({**_job_line(27), "state": "weird"}),
        json.dumps({**_job_line(28), "steps": [{**_job_line(28)["steps"][0], "state": "nope"}]}),
        json.dumps({**_job_line(29), "units": [["song/a", "taken"]]}),
        json.dumps({**_job_line(30), "queued_at": "yesterday"}),
        json.dumps({**_job_line(31), "files": None}),
        json.dumps({**_job_line(32), "seconds_to_sheet": "3"}),
        json.dumps({**_job_line(33), "song_id": 3.5}),
        json.dumps([1, 2]),
        json.dumps({"v": 1, "next": "40"}),
        json.dumps({"v": 1, "next": 2.0}),
        json.dumps(_job_line(19)).replace('"v": 1', '"v": 01'),  # no JSON: json.loads refuses a leading zero
        '{"v":1,"next":01}',
        json.dumps({**_job_line(18), "seconds_to_sheet": 1}).replace('"seconds_to_sheet": 1', '"seconds_to_sheet": 1.5f'),
        "\ufeff" + json.dumps(_job_line(17)),  # a BOM: json.loads of a text refuses it
        json.dumps({**_job_line(16), "queued_at": "2026-11-02T09:00:00.5 +01:00"}),
    ]
    odd = [
        json.dumps({**_job_line(34), "v": 1.0}),
        json.dumps({**_job_line(35), "v": True}),
        json.dumps({**{k: v for k, v in _job_line(36).items()
                       if k not in ("fetching", "note", "display", "stages", "song_id", "song_display", "files",
                                    "seconds_to_sheet", "together", "units", "started_at", "finished_at")}}),
        json.dumps({**_job_line(37), "seconds_to_sheet": 1e-05, "extra": "ignored"}),
        json.dumps({**_job_line(38), "stages": [{"name": "song", "label": "Find the song", "state": "whatever"}]}),
        json.dumps({**_job_line(39), "seconds_to_sheet": float("nan"), "song_id": 2**40}),
        json.dumps({**_job_line(40), "seconds_to_sheet": 10**20}),
        json.dumps({**_job_line(41), "seconds_to_sheet": -0.0, "queued_at": "2026-11-02T09:00:00 +01:00"}),
        json.dumps({**_job_line(42), "queued_at": "2026-W45-1T09:00"}),
    ]
    old = [_job_line(n, at="2026-09-01T08:00:00+00:00") for n in (50, 51)]
    many = [_job_line(n, at=f"2026-11-0{1 + n % 3}T08:00:00+00:00") for n in range(60, 66)]
    small = {**KW, "keep": 3, "max_bytes": 2500}
    return [
        ("no file: nothing read, nothing written", [load], {}),
        ("an empty file: written whole", [load], {"file": ""}),
        ("the requests read back, the next id after theirs", [load], {"file": "".join(text + "\n" for text in lines)}),
        ("the next id a file written whole says, and the last line of a request", [load], {"file": _history_file(
            [{"v": 1, "next": 31}, *good, {**good[0], "state": "failed", "title": "the last line"}])}),
        ("a request that waited or ran is interrupted, its running step and stage too", [load], {"file": _history_file([
            _job_line(1, "queued"),
            {**_job_line(2, "running"), "stages": [
                {"name": "song", "label": "Find the song", "state": "done", "detail": "", "running_detail": ""},
                {"name": "sheet", "label": "The sheet", "state": "running", "detail": "asking", "running_detail": "a"},
                {"name": "pdf", "label": "The PDF", "state": "waiting", "detail": "", "running_detail": ""}],
             "steps": [{**_job_line(2, "running")["steps"][0]}, {**_job_line(2, "queued")["steps"][0]}]},
            {**_job_line(3, "running"), "finished_at": "2026-11-02T09:00:00+00:00"},
            {**_job_line(4, "queued"), "started_at": None}])}),
        ("lines that can't be read are skipped; blank lines and line ends of every kind", [load], {
            "file": "\n".join(bad[:5]) + "\r\n\r\n   \n" + "\r".join(bad[5:]) + "\n" + lines[0] + "\r\n" +
                    "\n".join(odd) + "\n" + lines[1]}),
        ("bytes that aren't UTF-8 are a line skipped", [load], {
            "file": (lines[0] + "\n").encode() + b'{"v":1,"id":9,"title":"\xff\xfe"}\n' + (lines[1] + "\n").encode()
                    + json.dumps({**_job_line(8), "title": "café 🎸"}).encode() + b"\n"}),
        ("a request's every field, its output cut to the lines and characters kept", [load], {
            "file": _history_file([rich])}),
        ("times as ISO writes them, read as UTC", [load], {"file": _history_file(times)}),
        ("the newest of those over within the days, those over long ago forgotten", [load], {
            "file": _history_file(old + many + [_job_line(70, "running", at="2026-09-01T08:00:00+00:00")]),
            **small}),
        ("a file over its size written whole without its oldest", [load], {
            "file": _history_file([_job_line(n) for n in range(80, 86)]), **small, "keep": 100}),
        ("a step's output and lines cut on writing", [load], {
            "file": _history_file([rich]), **KW, "lines": 5, "line_chars": 10}),
        ("a save appends a line; past three lines a request it writes the file whole", [
            load,
            {"op": "save", "job": _job_line(90, "queued"), "jobs": [_job_line(90, "queued")], "next": 91,
             "now": NOW},
            {"op": "save", "job": _job_line(90, "running"), "jobs": [_job_line(90, "running")], "next": 91,
             "now": NOW},
            {"op": "save", "job": _job_line(90, "done"), "jobs": [_job_line(90, "done")], "next": 91, "now": NOW},
            {"op": "save", "job": _job_line(91, "queued"), "jobs": [_job_line(90, "done"), _job_line(91, "queued")],
             "next": 92, "now": NOW},
            {"op": "save", "job": _job_line(91, "running"), "jobs": [_job_line(90, "done"), _job_line(91, "running")],
             "next": 92, "now": NOW},
            {"op": "save", "job": _job_line(91, "done"), "jobs": [_job_line(90, "done"), _job_line(91, "done")],
             "next": 92, "now": "2026-12-20T00:00:00+00:00"},
        ], {"file": "", "keep": 1, "max_bytes": 100_000}),
        ("a save past its bytes writes the file whole, the oldest over left out", [
            {"op": "save", "job": _job_line(1), "jobs": [_job_line(n) for n in (1, 2, 3)], "next": 4, "now": NOW},
            {"op": "save", "job": _job_line(4, "queued"), "jobs": [_job_line(n) for n in (1, 2, 3)]
             + [_job_line(4, "queued")], "next": 5, "now": NOW},
        ], {"keep": 50, "max_bytes": 1200}),
        ("a rewrite keeps the newest and those waiting or running, whatever their size", [
            {"op": "rewrite", "jobs": [_job_line(1, "running"), _job_line(2), _job_line(3, "queued"), _job_line(4)],
             "next": 7},
            {"op": "rewrite", "jobs": [], "next": 1},
        ], {"max_bytes": 10}),
    ]


def history_records(tmp: Path) -> list[dict[str, Any]]:
    out = []
    for note, ops, options in history_cases():
        options = dict(options)
        file = options.pop("file", None)
        out.append(history_record(note, ops, file=file, tmp=tmp, **{**KW, **options}))
    return out + time_records()


# --- a request's times, as fromisoformat reads them -----------------------------------------------------------------

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
DATES = ["2026-11-03", "20261103", "2026-W45-2", "2026W452", "2026-W45", "2026W45", "2026-W53-7", "2026W537",
         "2025-W53-1", "2020-W53-5", "2024-W53-1", "2026-W00-1", "2026-W45-0", "2026-W45-8", "0001-01-01", "0000-01-01",
         "9999-12-31", "9999-W52-5", "9999-W52-6", "0001-W01-1", "0000-W01-1", "2024-02-29", "2026-02-29", "2026-1-03",
         "2026-11-3", "2026-1103", "202611-03", "2026-13-01", "2026-00-10", "2026-11-00", "2026-11-31", "2026/11/03",
         "２０２６-11-03", "2026-110", "2026-307", "2026-W4", "2026W4x"]
SEPARATORS = ["T", " ", "t", "x", "é", "\u3000", "\U0001f3b8", "0", "-", "W", "\x00"]
CLOCKS = ["", "09", "0930", "09:30", "093000", "09:30:00", "09:30:00.5", "09:30:00,5", "09:30:00.123456",
          "09:30:00.1234567", "09:30:00.", "093000.5", "093000123", "09:3000", "0930:00", "24", "24:00", "24:00:00",
          "24:00:00.000001", "24:01", "23:59:59.999999", "23:60", "25:00", "9:30", "09:30:0", "09:30:00.5x", "09.5",
          "09:30.5", "09:30:00:00", "09::30", "093", "09:30:00.000000", "0930001", "09:30:00\x00", "09:30:00é"]
GAPS = ["", " ", "  ", "x", "\t"]
OFFSETS = ["", "Z", "z", "+00:00", "-00:00", "+01", "+0100", "+01:00", "+01:30:00", "+013000", "+01:30:00.12",
           "+01:30:00.123456", "+01:30:00.1234567", "+24:00", "-24:00", "+23:59:59.999999", "-23:59:59.999999", "+01:3",
           "+1", "-05:00", "+01:00Z", "Z+01:00", "+01:00 ", "+01:99", "+99:00", "+0130.5", "+01:30.5", "+01:30:00.",
           "+01:30:00,5", "ZZ", "+", "-", "+01:00:00:00", "+0130005", "Z\x00", "+00:00:00.000001", "-00:00:00.5"]


def time_spellings() -> list[str]:
    """Every date alone and with a time, every separator, every time with no offset, with Z and with one, every
    gap before every offset after three times, then a fixed draw of the rest of their product."""
    texts = ["", "2026", "2026-11", "202611", "2026W4", "2026-W", "2026-W45-", "2026-W45-1x", "2026-W45-123",
             "2026-W45-1T09", "2026W45T09", "2026W4509", "2026W451T09", "2026W45109", "2026-11-03T", "2026-11-03TT09"]
    texts += DATES + [f"{date}T09:30:00" for date in DATES]
    texts += [f"2026-11-03{sep}09:30:00" for sep in SEPARATORS] + [f"2026-W45-2{sep}09:30" for sep in SEPARATORS]
    texts += [f"2026-11-03T{clock}{offset}" for clock in CLOCKS for offset in ("", "Z", "+01:00")]
    texts += [f"2026-11-03T{clock}{gap}{offset}" for clock in ("09:30:00", "09:30:00.5", "0930")
              for gap in GAPS for offset in OFFSETS]
    draw = random.Random(20261103)
    for _ in range(700):
        texts.append(draw.choice(DATES) + draw.choice(SEPARATORS) + draw.choice(CLOCKS) + draw.choice(GAPS)
                     + draw.choice(OFFSETS))
    for _ in range(300):  # of parts that read, mostly
        texts.append(draw.choice(DATES[:11] + DATES[14:20]) + draw.choice(SEPARATORS[:8]) + draw.choice(CLOCKS[1:9])
                     + draw.choice(GAPS[:2]) + draw.choice(OFFSETS[:17]))
    return list(dict.fromkeys(texts))


def time_records() -> list[dict[str, Any]]:
    out = []
    for text in time_spellings():
        record: dict[str, Any] = {"fn": "caracole.web.history._time", "args": [text]}
        try:
            record["out"] = (history_module._time(text) - EPOCH) // timedelta(microseconds=1)
        except ValueError:
            record["err"] = "ValueError"
        out.append(record)
    return out


# --- the tests -----------------------------------------------------------------------------------------------------


def test_queue_jsonl_is_web_jobs_pys_builders_rules_and_queues(ticking, tmp_path):
    records = builder_records() + rule_records() + queue_records(tmp_path)
    check(WEB / "queue.jsonl", jsonl(records, corpus="web/queue", made_by=MADE_BY))


def test_history_jsonl_is_web_history_pys_reads_and_writes(ticking, tmp_path):
    check(WEB / "history.jsonl", jsonl(history_records(tmp_path), corpus="web/history", made_by=MADE_BY))


def test_the_queue_vectors_cover_every_kind_of_op():
    ops = {op["op"] for _, ops, _ in scenarios() for op in ops}
    assert ops == {"submit", "submit_all", "cancel", "again", "run"}
