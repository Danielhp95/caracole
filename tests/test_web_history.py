"""caracole/web/history.py: the Requests tab's history, kept in state_dir/requests.jsonl across a restart of caracole
serve, its one writer: reloaded by the next server on the same state folder, what ran when it stopped interrupted,
capped and rewritten so that it never grows without bound, a line that can't be read skipped."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime, timedelta

import pytest
from helpers.browser import Browser, in_chromium

from caracole.get import PROGRESS_PREFIX
from caracole.web.app import WebApp
from caracole.web.history import FILE_NAME, History
from caracole.web.jobs import INTERRUPTED, Job, JobQueue, Stage, Step, add_steps, lookup_steps

from test_web_app import ALLOWED, answer, get_json, header, post


class Runner:
    """Each command's lines and exit status, as the fake caracole of test_web_jobs.py gives them."""

    def __init__(self, lines=None, codes=None):
        self.calls = []
        self.lines = lines or {}
        self.codes = codes or {}

    def __call__(self, args, emit):
        self.calls.append(list(args))
        for line in self.lines.get(args[0], [f"ran {args[0]}"]):
            emit(line)
        return self.codes.get(args[0], 0)


def progress(stage, state, detail=""):
    return PROGRESS_PREFIX + json.dumps({"stage": stage, "state": state, "detail": detail})


LOOKUP_LINES = [progress("song", "running"), "get: Radiohead - Creep is in the library",
                progress("song", "done", "in the library"), progress("sheet", "running", "asking Ultimate Guitar"),
                "get: tab 4169 from Ultimate Guitar", progress("sheet", "done", "tab 4169"),
                PROGRESS_PREFIX + json.dumps({"song": {"id": 7, "display": "Radiohead - Creep"},
                                              "files": {"pdf": "Radiohead/Creep/sheet.pdf"}, "seconds": 3.5})]


@pytest.fixture
def path(tmp_path):
    return tmp_path / "state" / FILE_NAME


def lines_of(path):
    return path.read_text(encoding="utf-8").splitlines()


def restart(path, runner=None, **options):
    """The next caracole serve on the same state folder: a new queue, its history read from the file."""
    return JobQueue(runner or Runner(), history=History(path, **options))


# --- what is kept -----------------------------------------------------------------------------------------------------


def test_a_finished_request_is_there_after_a_restart_as_it_was(path):
    queue = restart(path, Runner(lines={"get": LOOKUP_LINES, "add": ["ran add", "warning: a line"]},
                                 codes={"add": 1}))
    queue.submit("Fetch Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"), fetching=True,
                 display="Radiohead - Creep", note="Added to wanted.txt, line 3.")
    queue.submit("Add Oasis - Wonderwall", "oasis|wonderwall", add_steps("Oasis", "Wonderwall"))
    queue.run_pending()
    before = queue.snapshot()
    assert [j.state for j in before] == ["failed", "done"]
    sheet = next(stage for stage in before[1].stages if stage.name == "sheet")
    assert sheet.running_detail == "asking Ultimate Guitar" and before[1].song_id == 7
    after = restart(path).snapshot()
    assert after == before  # every field: steps and their output, stages, the song, its files, the times
    assert isinstance(after[0].steps[0].args, tuple) and after[0].queued_at.tzinfo is not None


def test_the_next_ids_follow_the_reloaded_ones(path):
    queue = restart(path)
    for n in range(3):
        queue.submit(f"Add A - {n}", f"a|{n}", add_steps("A", str(n)))
    queue.run_pending()
    again = restart(path)
    job, new = again.submit("Add B - 1", "b|1", add_steps("B", "1"))
    assert new and job.id == 4
    # Even once every request kept is older than the history keeps: a job=N link never names another request.
    later = restart(path, days=0)
    assert later.snapshot() == []
    assert later.submit("Add C - 1", "c|1", add_steps("C", "1"))[0].id == 5


def test_a_request_that_ran_or_waited_when_the_server_stopped_is_interrupted(path):
    # The server killed (a crash, a power cut): the file says what it last knew of each request.
    started = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
    running = Job(1, "Fetch Radiohead - Creep", "radiohead|creep",
                  [Step("Look it up now", lookup_steps("Radiohead", "Creep")[0][1], state="running",
                        output=["get: asking Ultimate Guitar"])],
                  fetching=True, display="Radiohead - Creep", state="running", queued_at=started,
                  started_at=started + timedelta(seconds=1),
                  stages=[Stage("song", "Find the song", "done", "in the library"),
                          Stage("sheet", "The sheet", "running", "asking Ultimate Guitar"),
                          Stage("pdf", "The PDF")])
    waiting = Job(2, "Add Oasis - Wonderwall", "oasis|wonderwall",
                  [Step("Adding to the library", add_steps("Oasis", "Wonderwall")[0][1])], queued_at=started)
    history = History(path)
    history.save(running, [running, waiting], 3)
    history.save(waiting, [running, waiting], 3)
    job, queued = restart(path).snapshot()[::-1]
    assert (job.state, [s.state for s in job.steps], [s.state for s in job.stages]) == (
        "interrupted", ["interrupted"], ["done", "interrupted", "skipped"])
    assert job.steps[0].output == ["get: asking Ultimate Guitar"] and job.finished_at is not None
    assert (queued.state, [s.state for s in queued.steps], queued.started_at) == ("interrupted", ["skipped"], None)
    # Read once more, it stays as it was: interrupted is written back.
    assert restart(path).snapshot()[::-1] == [job, queued]


def test_stopping_the_server_interrupts_the_running_request_and_keeps_what_it_printed(path):
    # Ctrl-C or systemd's stop: the queue ends the command it runs, which exits non-zero, and the request is
    # interrupted, never failed.
    printed, ended = threading.Event(), threading.Event()

    class Ended:
        def __call__(self, args, emit):
            emit("get: asking Ultimate Guitar")
            printed.set()
            ended.wait(10)
            return -15

        def terminate(self):
            ended.set()

    queue = restart(path, Ended())
    queue.submit("Fetch Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"), fetching=True)
    queue.submit("Add Oasis - Wonderwall", "oasis|wonderwall", add_steps("Oasis", "Wonderwall"))
    queue.start()
    assert printed.wait(10)
    queue.stop()
    assert [j.state for j in queue.snapshot()] == ["queued", "interrupted"]  # the next one never started
    queued, stopped = restart(path).snapshot()
    assert (stopped.state, stopped.steps[0].state, stopped.steps[0].code) == ("interrupted", "interrupted", -15)
    assert stopped.steps[0].output == ["get: asking Ultimate Guitar"]
    assert queued.state == "interrupted" and queued.started_at is None


# --- what the pages do with it ------------------------------------------------------------------------------------------


@pytest.fixture
def stopped(cfg, path):
    """A server that ran one request and was killed while running a second: its history, and a new server on it."""
    queue = restart(path, Runner(lines={"get": ["get: asking Ultimate Guitar", "error: Ultimate Guitar answered 503"]},
                                 codes={"get": 1}))
    queue.submit("Fetch Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"), fetching=True,
                 display="Radiohead - Creep")
    queue.run_pending()
    running = Job(2, "Fetch Oasis - Wonderwall", "oasis|wonderwall",
                  [Step("Look it up now", lookup_steps("Oasis", "Wonderwall")[0][1], state="running",
                        output=["get: looking up Oasis - Wonderwall"])],
                  fetching=True, display="Oasis - Wonderwall", state="running", started_at=datetime.now(UTC))
    History(path).save(running, [*queue.snapshot(), running], 3)
    runner = Runner()
    return WebApp(cfg, restart(path, runner), allowed=ALLOWED, csrf="tok"), runner


def test_the_requests_tab_shows_the_history_after_a_restart_with_try_again(stopped):
    app, _ = stopped
    fed = answer(get_json(app, "/requests.json?open=2"))
    shown = {r["id"]: r for g in fed["groups"] for r in g["requests"]}
    assert fed["active"] == 0 and set(shown) == {1, 2}
    assert shown[1]["says"] == {"tone": "failed", "text": "Failed"}
    assert shown[2]["says"] == {"tone": "waiting", "text": "Interrupted"}
    assert shown[2]["reason"] == "caracole serve stopped while it ran: run it again to finish it."
    assert shown[2]["actions"] == [{"label": "Try again", "primary": False, "post": "/jobs/again",
                                   "fields": {"job": "2"}}]
    assert shown[2]["output"]["steps"] == [{"label": "Look it up now", "badge": {"tone": "interrupted",
                                                                                "text": "Interrupted"},
                                            "lines": ["get: looking up Oasis - Wonderwall"]}]
    assert answer(get_json(app, "/api/jobs/2"))["state"] == "interrupted"


def test_try_again_and_cancel_on_a_reloaded_request(stopped):
    app, runner = stopped
    assert post(app, "/jobs/cancel", {"job": "2"}).status == 409  # over already: nothing to cancel
    response = post(app, "/jobs/again", {"job": "2"})
    assert response.status == 303 and header(response, "location") == "/#tab=requests"
    again = app.queue.snapshot()[0]
    assert (again.id, again.state, again.display) == (3, "queued", "Oasis - Wonderwall")
    assert [s.args for s in again.steps] == [lookup_steps("Oasis", "Wonderwall")[0][1]]
    app.queue.run_pending()
    assert runner.calls == [list(lookup_steps("Oasis", "Wonderwall")[0][1])]
    assert post(app, "/jobs/again", {"job": "1"}).status == 303  # the failed one, from before the restart, too


# --- the file ----------------------------------------------------------------------------------------------------------


def test_lines_that_cant_be_read_are_skipped_and_the_file_written_again_without_them(path):
    queue = restart(path)
    queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    queue.submit("Add A - 2", "a|2", add_steps("A", "2"))
    queue.run_pending()
    good = lines_of(path)
    record = json.loads(good[-1])
    wrong = dict(record, id="seven")
    with path.open("a", encoding="utf-8") as f:
        f.write("not json\n[1, 2]\n" + json.dumps(wrong) + "\n" + json.dumps({"v": 99, "id": 9}) + "\n\xff\n")
        f.write(json.dumps(dict(record, id=3, title="Add A - 3"))[:40])  # a line cut short by a crash
    jobs = restart(path).snapshot()
    assert [j.title for j in jobs] == ["Add A - 2", "Add A - 1"]
    written = lines_of(path)
    assert all(isinstance(json.loads(line), dict) for line in written)
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert restart(path).snapshot() == jobs


def test_what_a_command_printed_is_capped(path):
    many = [f"line {n} " + "x" * 3000 for n in range(500)]
    queue = restart(path, Runner(lines={"add": many}), lines=50, line_chars=100)
    queue.submit("Add A - B", "a|b", add_steps("A", "B"))
    queue.run_pending()
    step = restart(path).snapshot()[0].steps[0]
    assert len(step.output) == 50 and step.dropped == 450
    assert step.output[0].startswith("line 450 ") and step.output[-1].startswith("line 499 ")
    assert all(len(line) <= 100 and line.endswith("…") for line in step.output)


def test_the_newest_requests_of_the_last_days_are_kept(path):
    queue = restart(path, keep=3)
    for n in range(5):
        queue.submit(f"Add A - {n}", f"a|{n}", add_steps("A", str(n)))
    queue.run_pending()
    assert [j.title for j in restart(path, keep=3).snapshot()] == ["Add A - 4", "Add A - 3", "Add A - 2"]
    old = Job(9, "Add Old - One", "old|one", [Step("Adding to the library", ("add", "--", "Old", "One"),
                                                   state="done", code=0)], state="done",
              queued_at=datetime.now(UTC) - timedelta(days=31), finished_at=datetime.now(UTC) - timedelta(days=31))
    History(path).save(old, [old], 10)
    assert "Add Old - One" not in [j.title for j in restart(path, keep=10).snapshot()]


def test_the_file_never_grows_without_bound(path):
    queue = restart(path, Runner(lines={"add": ["ran add " + "y" * 200] * 20}), keep=5, max_bytes=40_000)
    for n in range(200):
        queue.submit(f"Add A - {n}", f"a|{n}", add_steps("A", str(n)))
        queue.run_pending()
        assert len(lines_of(path)) <= 3 * 5 + 4 and path.stat().st_size <= 2 * 40_000, n
    assert [j.title for j in restart(path, keep=5).snapshot()] == [f"Add A - {n}" for n in range(199, 194, -1)]
    # Its bytes too: the newest requests that fit.
    queue = restart(path, Runner(lines={"add": ["z" * 900] * 40}), keep=50, max_bytes=60_000)
    for n in range(10):
        queue.submit(f"Add B - {n}", f"b|{n}", add_steps("B", str(n)))
        queue.run_pending()
    kept = restart(path, keep=50, max_bytes=60_000).snapshot()
    assert path.stat().st_size <= 60_000 and kept and kept[0].title == "Add B - 9"


def test_a_rewrite_cut_short_leaves_the_file_as_it_was(path, monkeypatch):
    queue = restart(path)
    queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    queue.run_pending()
    before = path.read_bytes()

    def crash(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", crash)
    restart(path)  # its rewrite fails
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == [FILE_NAME]  # no half-written file left behind
    monkeypatch.undo()
    assert [j.title for j in restart(path).snapshot()] == ["Add A - 1"]


def test_a_history_that_cant_be_written_never_stops_a_request(tmp_path, caplog):
    blocked = tmp_path / "a-file"
    blocked.write_text("not a folder", encoding="utf-8")
    queue = restart(blocked / FILE_NAME, Runner())
    queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    queue.run_pending()
    assert queue.snapshot()[0].state == "done"
    assert "request history" in caplog.text


def test_the_file_is_private_to_caracole(path):
    queue = restart(path)
    queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    queue.run_pending()
    assert path.stat().st_mode & 0o077 == 0


# --- caracole serve -------------------------------------------------------------------------------------------------------


def test_serve_keeps_its_history_in_the_state_folder(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from caracole.cli import build_app

    seen = {}
    monkeypatch.setattr("caracole.web.server.serve", lambda app, address, port, *, announce: seen.update(app=app))
    config = tmp_path / "caracole.toml"
    config.write_text(f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
                      f'cache_dir = "{tmp_path / "cache"}"\n', encoding="utf-8")
    result = CliRunner().invoke(build_app(), ["--config", str(config), "serve"])
    assert result.exit_code == 0, result.output
    assert seen["app"].queue.history.path == tmp_path / "state" / FILE_NAME


# --- in a browser ----------------------------------------------------------------------------------------------------------


@in_chromium
def test_the_requests_tab_after_a_restart_in_a_browser(stopped, tmp_path):
    from caracole.web.security import allowed_hosts
    from caracole.web.server import make_server

    old, _ = stopped
    app = WebApp(old.cfg, old.queue, allowed=allowed_hosts("127.0.0.1"), searches_lacuerda=False)
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    says = "(document.querySelector('#req-{n} .req-says') || {{}}).textContent"
    try:
        with Browser(tmp_path / "chrome", width=390, height=844, mobile=True) as page:
            page.open(f"http://127.0.0.1:{server.server_address[1]}/#tab=requests&job=2")
            assert page.wait(says.format(n=2) + " === 'Interrupted'"), page.js("document.body.innerText")
            assert page.js(says.format(n=1)) == "Failed"
            # job=2 opened its output, with what its command printed before the server stopped
            assert page.wait("(document.querySelector('#req-2 .req-output pre') || {}).textContent === "
                             "'get: looking up Oasis - Wonderwall'")
            assert page.js("document.querySelector('#req-2 .req-reason').textContent") == (
                "caracole serve stopped while it ran: run it again to finish it.")
            page.click("#req-2 .req-next form button")  # Try again
            assert page.wait("document.querySelector('#req-3') !== null"), page.js("document.body.innerText")
            assert page.js("document.documentElement.scrollWidth <= innerWidth")
    finally:
        app.queue.stop()
        server.shutdown()
        server.server_close()


def test_the_pages_that_follow_a_request_say_it_was_interrupted():
    # The versions page and a harmonica tab's readings follow their request by its job: one a restart interrupted is
    # over, never still running.
    from caracole.web import harmonica_routes, versions_routes

    job = Job(4, "Keep a version", "a|b", [Step("Fetching the version", ("versions", "--keep=3"), state=INTERRUPTED)],
              state=INTERRUPTED, started_at=datetime.now(UTC))
    said, link = versions_routes._how_it_goes(None, "keep", None, job)
    assert said.startswith('<p class="says waiting">Interrupted: caracole serve stopped before it was over.')
    assert "#tab=requests&amp;job=4" in said and link == ""
    said = harmonica_routes._how_it_goes(None, job)
    assert said.startswith('<p class="says waiting">Interrupted: caracole serve stopped before it was over.')
