"""The Sync tab's routes on caracole serve (web/sync_routes.py): GET /api/sync, POST /sync/compare and POST
/sync/apply, between two computers' caracole serves, each a WebApp whose queue runs its commands through the CLI in
this process (``InProcess``), the other reached over HTTP through a transport that hands each request to its app.

Compare answers every unit the two hold differently and keeps the comparison; Sync refuses an unchosen conflict, a
comparison past or one the two no longer agree with, else queues ``caracole peer sync --push`` with the owner's
choices, whose view the tab follows to its end: then the two hold the same, and the tab lists the other caracole."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from caracole import db
from caracole import peer_sync as sync
from caracole.web import jobs, sync_routes
from caracole.web.app import Request, WebApp, route_for
from caracole.web.jobs import PEER_SYNC_STAGES, PEER_TAKE_STAGES, Job, Stage, Step
from caracole.web.jobs_routes import view

from test_commands_peer import InProcess, Side, two_conflicts
from test_web_app import get, post

THERE = "http://localhost:8737"  # the other computer's caracole serve, as here reaches it


@pytest.fixture
def computers(tmp_path, monkeypatch):
    """Two computers' caracole serves: ``here`` (whose routes the test asks, as its library page does) and
    ``there``, which both the comparison and ``caracole peer sync`` reach at THERE; each runs what its queue holds
    through the CLI, there as it is asked how a job goes (a push's take). Renders are recorded, not made."""
    here, there = Side(tmp_path / "here", InProcess()), Side(tmp_path / "there", InProcess())
    asked: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.method, request.url.path))
        if request.url.path.startswith("/api/jobs/"):
            there.app.queue.run_pending()
        answer = there.app.handle(Request(request.method, request.url.raw_path.decode(), dict(request.headers),
                                          request.content))
        answer = WebApp.finish(answer)
        return httpx.Response(answer.status, headers=answer.headers, content=answer.body)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    monkeypatch.setattr(sync_routes, "transport", lambda: transport)
    monkeypatch.setattr("caracole.render.render_all", lambda conn, cfg, overrides, **kw: None)
    yield here, there, asked
    here.conn.close()
    there.conn.close()


def script(app, path, fields=None):
    """The page's script asking ``path``: a GET with the form token in its header, or a form posted, JSON back."""
    if fields is None:
        answer = get(app, path, accept="application/json", **{"x-caracole-form-token": "tok"})
    else:
        answer = post(app, path, fields, accept="application/json")
    return answer.status, json.loads(answer.body)


def compared(here, address=THERE):
    status, found = script(here.app, "/sync/compare", {"address": address})
    assert status == 200, found
    return found


def by_label(found):
    return {d["label"]: d for d in found["differences"]}


# --- what the tab reads first ------------------------------------------------------------------------------------


def test_the_tab_reads_this_caracole_and_none_synced_before(computers):
    here, _, asked = computers
    status, state = script(here.app, "/api/sync")
    assert status == 200 and asked == []  # read here alone
    assert state == {"server": sync.own_id(here.conn), "name": here.cfg.library_name, "address": None, "peers": []}


def test_the_peers_synced_before_are_listed_newest_first_and_the_newest_is_the_address(computers):
    here, _, _ = computers
    db.kv_set_json(here.conn, "sync:peer:aaaa", {"address": "http://10.0.0.7:8737", "name": "Studio",
                                                "synced_at": "2026-10-30T08:00:00Z"})
    db.kv_set_json(here.conn, "sync:peer:bbbb", {"address": "http://192.168.1.20:8737", "name": "Desk",
                                                "synced_at": "2026-11-02T21:04:00Z"})
    db.kv_set(here.conn, "sync:peer:cccc", "not a record")
    status, state = script(here.app, "/api/sync")
    assert status == 200 and state["address"] == "http://192.168.1.20:8737"
    assert state["peers"] == [
        {"address": "http://192.168.1.20:8737", "server": "bbbb", "name": "Desk", "synced_at": "2026-11-02T21:04:00Z"},
        {"address": "http://10.0.0.7:8737", "server": "aaaa", "name": "Studio", "synced_at": "2026-10-30T08:00:00Z"}]


# --- the comparison ----------------------------------------------------------------------------------------------


def test_a_comparison_lists_each_difference_with_its_kind_proposal_and_both_digests(computers):
    here, there, asked = computers
    unit = two_conflicts(here, there)
    found = compared(here, "localhost:8737")  # typed with no scheme
    assert asked == [("GET", "/api/peer/state")]
    assert len(found["comparison"]) == 16 and found["synced_before"] is None
    assert found["peer"] == {"address": THERE, "server": sync.own_id(there.conn), "caracole": "0.1.0",
                             "name": there.cfg.library_name}
    mine, theirs = here.units(), there.units()
    assert [(d["label"], d["kind"], d["proposal"], d["why"]) for d in found["differences"]] == [
        ("Estopa - Tu Calorro", "song", "theirs", "only there"),
        ("Muse - Hysteria", "song", "mine", "only here"),
        ("Oasis - Wonderwall", "song", "conflict", "on both sides, different, and never synced"),
        ("Radiohead - Creep", "song", "conflict", "on both sides, different, and never synced")]
    creep = by_label(found)["Radiohead - Creep"]
    assert creep["id"] == unit["Radiohead - Creep"]
    assert (creep["here"], creep["there"]) == (mine[creep["id"]].digest, theirs[creep["id"]].digest)
    assert by_label(found)["Muse - Hysteria"]["there"] is None
    assert sync.base_of(here.conn, sync.own_id(there.conn)) is None  # nothing written
    assert here.app.queue.snapshot() == []


def test_a_comparison_refuses_an_address_nothing_answering_and_this_very_caracole(computers, monkeypatch):
    here, there, _ = computers
    status, said = script(here.app, "/sync/compare", {"address": "ftp://desk"})
    assert status == 400 and "isn't the address of a caracole serve" in said["error"]

    db.kv_set(here.conn, sync.ID_KEY, sync.own_id(there.conn))  # a copy of the other's database
    status, said = script(here.app, "/sync/compare", {"address": THERE})
    assert status == 409 and "is this one" in said["error"] and "caracole peer new-id" in said["error"]

    def refused(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(sync_routes, "transport", lambda: httpx.MockTransport(refused))
    status, said = script(here.app, "/sync/compare", {"address": "192.168.1.20:8737"})
    assert status == 502 and said["error"].startswith("Nothing answered at http://192.168.1.20:8737")


# --- the sync ----------------------------------------------------------------------------------------------------


def test_sync_refuses_an_unchosen_conflict_a_comparison_past_and_choices_it_cant_read(computers):
    here, there, _ = computers
    two_conflicts(here, there)
    found = compared(here)
    creep = by_label(found)["Radiohead - Creep"]["id"]
    for fields, status, words in [
        ({"comparison": "0123456789abcdef", "prefer": "", "choices": ""}, 409, "compare the two again"),
        ({"comparison": found["comparison"], "prefer": "", "choices": f"here\t{creep}"}, 409,
         "Choose a side for every conflict first: 1 has none."),
        ({"comparison": found["comparison"], "prefer": "", "choices": "maybe\tsong/x"}, 400, "isn't a choice"),
        ({"comparison": found["comparison"], "prefer": "", "choices": "here\tsong/not/compared"}, 400,
         "isn't a choice"),
        ({"comparison": found["comparison"], "prefer": "", "choices": f"here\t{creep}\nthere\t{creep}"}, 400,
         "chosen two ways"),
        ({"comparison": found["comparison"], "prefer": "both", "choices": ""}, 400, "prefer is here, there"),
    ]:
        answer, said = script(here.app, "/sync/apply", fields)
        assert (answer, words in said["error"]) == (status, True), (fields, said)
    assert here.app.queue.snapshot() == []
    assert route_for("POST", "/sync/apply").limit == 1024 * 1024  # a choice a line, for a whole library's units


def test_sync_refuses_a_comparison_the_two_no_longer_agree_with_before_anything_is_queued(computers):
    here, there, _ = computers
    two_conflicts(here, there)
    found = compared(here)
    there.song("Muse", "Uprising", version=None)  # there moved on since
    status, said = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "here",
                                                     "choices": ""})
    assert status == 409 and said["error"] == sync_routes.STALE
    assert here.app.queue.snapshot() == []
    status, said = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "here",
                                                     "choices": ""})
    assert status == 409 and said["error"] == sync_routes.GONE  # that comparison is gone


def test_two_computers_sync_through_the_tabs_routes_and_end_with_no_differences(computers):
    here, there, asked = computers
    two_conflicts(here, there)
    found = compared(here)
    ids = {d["label"]: d["id"] for d in found["differences"]}
    # As the tab sends them: every conflict's choice, and one proposal flipped (Muse, here alone, given there all the
    # same as proposed: a choice equal to the proposal changes nothing).
    choices = f"here\t{ids['Radiohead - Creep']}\nthere\t{ids['Oasis - Wonderwall']}\nhere\t{ids['Muse - Hysteria']}"
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "",
                                                       "choices": choices})
    assert status == 200, answer
    queued = answer["job"]
    assert queued["kind"] == "sync" and queued["display"] == f"Sync with {there.cfg.library_name}"
    assert queued["details"] == "#tab=sync" and queued["songId"] is None and queued["outcome"] is None
    assert [s["name"] for s in queued["steps"]] == [name for name, _ in PEER_SYNC_STAGES]
    (job,) = here.app.queue.snapshot()
    hash_ = sync.compared_hash(sync.compare(here.units(), there.units(), None))
    assert job.steps[0].args == ("peer", "sync", "--push", "--yes", "--progress", f"--compared={hash_}",
                                 f"--choose=here:{ids['Radiohead - Creep']}",
                                 f"--choose=there:{ids['Oasis - Wonderwall']}",
                                 f"--choose=here:{ids['Muse - Hysteria']}", "--", THERE)
    # A second Sync while it waits: refused, never a second job.
    again = compared(here)
    status, said = script(here.app, "/sync/apply", {"comparison": again["comparison"], "prefer": "here",
                                                     "choices": ""})
    assert status == 409 and "on its way already" in said["error"]

    asked.clear()
    here.app.queue.run_pending()
    (job,) = here.app.queue.snapshot()
    assert job.state == "done", [s.output for s in job.steps]
    assert ("POST", "/peer/pull") not in asked  # given by a push: there needn't reach here
    status, polled = script(here.app, f"/jobs.json?jobs={job.id}")
    (seen,) = polled["jobs"]
    assert seen["line"] == {"tone": "ready", "text": "Synced", "link": None, "details": None}
    assert [(s["name"], s["state"]) for s in seen["steps"]] == [("compare", "done"), ("take", "done"),
                                                                 ("give", "done"), ("agree", "done")]
    outcome = seen["outcome"]
    assert sorted(outcome["taken"]) == sorted([ids["Oasis - Wonderwall"], ids["Estopa - Tu Calorro"]])
    assert sorted(outcome["given"]) == sorted([ids["Radiohead - Creep"], ids["Muse - Hysteria"]])
    assert outcome["left"] == [] and outcome["indexed"] == [] and outcome["agreed"] == len(here.units())

    assert here.units() == there.units()
    after = compared(here)
    assert after["differences"] == [] and isinstance(after["synced_before"], str)
    status, state = script(here.app, "/api/sync")
    assert state["address"] == THERE and [(p["server"], p["name"]) for p in state["peers"]] == [
        (sync.own_id(there.conn), there.cfg.library_name)]
    # Nothing differing, Sync still runs: it keeps what the two agree on.
    status, answer = script(here.app, "/sync/apply", {"comparison": after["comparison"], "prefer": "", "choices": ""})
    assert status == 200, answer
    here.app.queue.run_pending()
    last = here.app.queue.snapshot()[0]
    assert last.state == "done" and [(s.name, s.state) for s in last.stages] == [
        ("compare", "done"), ("take", "skipped"), ("give", "skipped"), ("agree", "done")]


def test_a_sync_that_leaves_a_unit_says_how_many_and_why_and_its_next_step_is_a_comparison_afresh(computers):
    from caracole.web.outcome import outcome, steps
    from caracole.web.status import job_line

    here, there, _ = computers
    two_conflicts(here, there)
    found = compared(here)
    ids = {d["label"]: d["id"] for d in found["differences"]}
    choices = f"skip\t{ids['Radiohead - Creep']}\nthere\t{ids['Oasis - Wonderwall']}"
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "",
                                                       "choices": choices})
    assert status == 200, answer
    here.app.queue.run_pending()
    (job,) = here.app.queue.snapshot()
    _, polled = script(here.app, f"/jobs.json?jobs={job.id}")
    (seen,) = polled["jobs"]
    assert seen["line"] == {"tone": "waiting", "text": "Synced: 1 change left as it was", "link": None,
                            "details": f"#tab=requests&job={job.id}"}
    assert seen["outcome"]["left"] == [[ids["Radiohead - Creep"], "skipped, as chosen"]]
    said = outcome(job, job_line(job, None))
    assert (said.tone, said.word, said.reason) == ("waiting", "Synced", "Took 2 changes here and gave 1 change "
                                                                        "there. 1 change left as it was.")
    assert said.action.label == "Compare again" and said.action.href == "/#tab=sync"
    assert [(c.name, c.state) for c in steps(job)] == [("Compare", "done"), ("Take", "done"), ("Give", "done"),
                                                       ("Agree", "done")]


def test_the_library_page_has_the_sync_tab_before_requests(computers):
    here, _, _ = computers
    page = get(here.app, "/").body.decode("utf-8")
    assert page.index('id="tab-sync"') < page.index('id="tab-requests"')
    assert '<section class="view sync" id="sync"' in page


# --- the shapes the tab's tests draw (test_sync_tab.py's FakeSync), as the real routes answer them ---------------


def shape(value):
    """A value's shape: an object's keys each with its value's shape, a list's first item's, else its type's name
    (a null and a string alike: either may stand where the other does)."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return "text" if value is None or isinstance(value, str) else type(value).__name__


def test_the_tabs_fake_answers_are_shaped_as_the_real_routes_answer(computers):
    from test_sync_tab import COMPARISON, STATE, VIEWS

    here, there, _ = computers
    two_conflicts(here, there)
    db.kv_set_json(here.conn, "sync:peer:0f1e2d3c4b5a6978", {"address": THERE, "name": "Desk",
                                                            "synced_at": "2026-11-02T21:04:00Z"})
    assert shape(script(here.app, "/api/sync")[1]) == shape(STATE)
    found = compared(here)
    assert shape(dict(found, synced_before="2026-11-02T21:04:00Z")) == shape(COMPARISON)
    assert {d["kind"] for d in found["differences"]} <= set(sync_routes_kinds())
    ids = {d["label"]: d["id"] for d in found["differences"]}
    status, answer = script(here.app, "/sync/apply", {
        "comparison": found["comparison"], "prefer": "here",
        "choices": f"there\t{ids['Oasis - Wonderwall']}\nskip\t{ids['Radiohead - Creep']}"})
    assert shape(answer["job"]) == shape(VIEWS[0])
    here.app.queue.run_pending()
    _, polled = script(here.app, f"/jobs.json?jobs={answer['job']['id']}")
    over = dict(polled["jobs"][0])
    over.pop("songbooks")  # the Songbooks tab's, which /jobs.json adds to a job asked about once it is over
    assert shape(over) == shape(VIEWS[-1])


def sync_routes_kinds():
    """The kinds a difference may be of, as the tab groups them: peer_sync's, in its order."""
    return ("song", "removed", "songbook", "alias", "artist_url", "block")


def test_the_kinds_the_tab_groups_are_peer_syncs():
    from caracole.library_assets import HERE

    assert sync._KINDS == sync_routes_kinds()
    script_text = (HERE / "sync.js").read_text(encoding="utf-8")
    assert all(f'["{kind}", ' in script_text for kind in sync._KINDS)


# --- jobs as the views and the vectors give them -----------------------------------------------------------------


def peer_job(kind: str, state: str, stages: dict[str, tuple[str, str]] | None = None, *, units=(), output=(),
             job_id: int = 41, name: str = "Desk", address: str = "http://192.168.1.20:8737") -> Job:
    """A sync's (``kind`` "sync"), a take's ("peer-push") or an index export's merge ("index-merge") job of caracole serve's as its queue would hold it in ``state``: its stages as
    ``stages`` says (name: (state, detail); waiting else; a running one's detail its running detail too), its
    ``units`` as its command said them, ``output`` its step's last lines."""
    when = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)
    if kind == "index-merge":
        names = jobs.INDEX_MERGE_STAGES
        made = jobs.index_merge_job(Path("/state/peer/index-0123456789abcdef.sqlite"))
        title, key, (label, args) = made["title"], made["song_key"], made["steps"][0]
    elif kind == "sync":
        title = f"Sync with {name}"
        args = ("peer", "sync", "--push", "--yes", "--progress", "--compared=" + "0" * 64, "--", address)
        key, names, label = sync_routes.SYNCING + address, PEER_SYNC_STAGES, title
    else:
        title = f"Changes from {name}"
        args = ("peer", "take", "--progress", "--", "/state/peer/push-0123456789abcdef")
        key, names, label = "peer-push:0f1e2d3c4b5a6978", PEER_TAKE_STAGES, "Taking 3 changes"
    made = []
    for stage, stage_label in names:
        said, detail = (stages or {}).get(stage, ("waiting", ""))
        made.append(Stage(stage, stage_label, said, detail, detail if said == "running" else ""))
    step_state = {"queued": "waiting", "running": "running", "done": "done", "failed": "failed",
                  "cancelled": "skipped", "interrupted": "interrupted"}[state]
    return Job(job_id, title, key, [Step(label, args, step_state, output=list(output))], display=title, state=state,
               queued_at=when, started_at=None if state in ("queued", "cancelled") else when,
               finished_at=when if state not in ("queued", "running") else None, stages=made,
               units=list(units))


def test_a_syncs_view_while_it_runs_is_its_running_stage_and_once_over_what_it_did():
    running = peer_job("sync", "running", {"compare": ("done", "4 differences"), "take": ("running", "2 changes")})
    seen = view(running, [running], None, None)
    assert seen["line"]["text"] == "Taking what changed there…" and seen["outcome"] is None
    assert seen["steps"][1] == {"name": "take", "label": "Take", "state": "running", "detail": "2 changes"}
    # A crash in its take: the line is the error, never what the stage said while it ran.
    crashed = peer_job("sync", "failed", {"compare": ("done", "4 differences"), "take": ("running", "2 changes")},
                       output=["error: The caracole at http://192.168.1.20:8737 answered 500. Try again later."])
    crashed.stages[1].state = "failed"
    assert view(crashed, [crashed], None, None)["line"]["text"] == (
        "The caracole at http://192.168.1.20:8737 answered 500.")
    stale = peer_job("sync", "failed", {"compare": ("failed", sync_routes.STALE)},
                     output=["error: " + sync_routes.STALE])
    assert view(stale, [stale], None, None)["line"]["text"] == "The two changed since that comparison: compare " \
                                                                "them again, and choose again."
    taken = peer_job("peer-push", "done", {"check": ("done", "3 changes from Phone"), "take": ("done", "took 3"),
                                           "render": ("done", ""), "agree": ("done", "12 units the two agree on")},
                     units=[("song/a/b", "taken", ""), ("song/c/d", "taken", ""), ("songbook/e", "taken", "")])
    seen = view(taken, [taken], None, None)
    assert (seen["kind"], seen["line"]["text"]) == ("peer-push", "Taken")
    assert seen["outcome"] == {"taken": ["song/a/b", "song/c/d", "songbook/e"], "given": [], "left": [],
                               "agreed": 12, "indexed": []}
    nothing = peer_job("peer-push", "done", {"check": ("done", ""), "take": ("failed", "Nothing taken: no backup of "
                                             "the database first, not enough room.")},
                       units=[("song/a/b", "left", "Nothing taken: no backup of the database first, not enough room.")])
    assert view(nothing, [nothing], None, None)["line"] == {
        "tone": "waiting", "text": "Nothing taken: no backup of the database first, not enough room.", "link": None,
        "details": "#tab=requests&job=41"}


def test_another_caracoles_index_pages_are_a_job_of_no_song_with_one_stage():
    # skeleton-m4's job kind: caracole index merge --delete --progress -- FILE, whose command and route lane
    # index-push writes.
    queue = jobs.JobQueue(lambda args, say: 0)
    path = Path("/state/peer/index-0123456789abcdef.sqlite")
    made, new = queue.submit(**jobs.index_merge_job(path))
    assert new and made.song_id is None and [(s.name, s.state) for s in made.stages] == [("merge", "waiting")]
    assert made.steps[0].args == ("index", "merge", "--delete", "--progress", "--", str(path))
    running = peer_job("index-merge", "running", {"merge": ("running", "")})
    seen = view(running, [running], None, None)
    assert seen["kind"] == "index-merge" and seen["line"]["text"] == "Merging the other caracole's index pages…"
    assert seen["steps"] == [{"name": "merge", "label": "Merge", "state": "running", "detail": ""}]
    done = peer_job("index-merge", "done", {"merge": ("done", "merged 12 pages: ug, lacuerda")})
    assert view(done, [done], None, None)["line"]["text"] == "Merged"
