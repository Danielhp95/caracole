"""caracole/web/jobs.py: the queue of requests, run one caracole command at a time."""

import sys
import threading
from pathlib import Path

import pytest

from caracole.web.jobs import (
    CaracoleRunner,
    JobQueue,
    QueueFull,
    add_steps,
    child_env,
    fetch_steps,
)

from conftest import subprocess_pythonpath


class FakeRunner:
    """Records each command; ``codes`` gives a command's exit status, ``lines`` its output."""

    def __init__(self, codes=None, lines=None):
        self.calls = []
        self.codes = codes or {}
        self.lines = lines or {}
        self.terminated = False

    def __call__(self, args, emit):
        self.calls.append(list(args))
        for line in self.lines.get(args[0], [f"ran {args[0]}"]):
            emit(line)
        return self.codes.get(args[0], 0)

    def terminate(self):
        self.terminated = True


def test_a_request_is_caracole_add_and_a_fetch_is_match_fetch_render():
    assert add_steps("Radiohead", "Creep") == [("Add to the library", ("add", "--", "Radiohead", "Creep"))]
    assert add_steps("-rf", "--help", album="OK Computer", duration_ms=239000) == [
        ("Add to the library", ("add", "--album=OK Computer", "--duration=3:59", "--", "-rf", "--help"))]
    assert fetch_steps("Radiohead - Creep") == [
        ("Match against the index", ("match",)),
        ("Fetch from Ultimate Guitar", ("fetch", "--song=Radiohead - Creep")),
        ("Render the PDF", ("render",)),
    ]


def test_jobs_run_their_steps_in_order_one_job_at_a_time():
    runner = FakeRunner()
    queue = JobQueue(runner)
    first, new = queue.submit("Fetch Radiohead - Creep", "radiohead|creep",
                              add_steps("Radiohead", "Creep") + fetch_steps("Radiohead - Creep"), fetching=True)
    second, _ = queue.submit("Add Oasis - Wonderwall", "oasis|wonderwall", add_steps("Oasis", "Wonderwall"))
    assert new and [j.state for j in queue.snapshot()] == ["queued", "queued"]
    queue.run_pending()
    assert [c[0] for c in runner.calls] == ["add", "match", "fetch", "render", "add"]
    jobs = {j.id: j for j in queue.snapshot()}
    assert jobs[first.id].state == "done" and jobs[second.id].state == "done"
    assert [s.state for s in jobs[first.id].steps] == ["done"] * 4
    assert jobs[first.id].steps[2].output == ["ran fetch"] and jobs[first.id].steps[2].code == 0
    assert jobs[first.id].started_at is not None and jobs[first.id].finished_at is not None


def test_a_step_that_fails_stops_its_job():
    runner = FakeRunner(codes={"match": 1}, lines={"match": ["The UG index is empty: run `caracole index build` first."]})
    queue = JobQueue(runner)
    job, _ = queue.submit("Fetch Radiohead - Creep", "radiohead|creep", fetch_steps("Radiohead - Creep"))
    queue.run_pending()
    done = queue.snapshot()[0]
    assert done.state == "failed"
    assert [(s.state, s.code) for s in done.steps] == [("failed", 1), ("skipped", None), ("skipped", None)]
    assert [c[0] for c in runner.calls] == ["match"]
    assert "index is empty" in done.steps[0].output[0]


def test_a_runner_that_raises_fails_the_job_and_the_queue_goes_on():
    def broken(args, emit):
        raise OSError("no such program")

    queue = JobQueue(broken)
    queue.submit("Add A - B", "a|b", add_steps("A", "B"))
    queue.run_pending()
    step = queue.snapshot()[0].steps[0]
    assert step.state == "failed" and "no such program" in step.output[-1]


def test_one_job_per_song_at_a_time():
    queue = JobQueue(FakeRunner())
    job, new = queue.submit("Fetch Radiohead - Creep", "radiohead|creep", fetch_steps("Radiohead - Creep"))
    again, new_again = queue.submit("Fetch Radiohead - Creep", "radiohead|creep", fetch_steps("Radiohead - Creep"))
    assert new and not new_again and again.id == job.id
    queue.run_pending()
    later, new_later = queue.submit("Fetch Radiohead - Creep", "radiohead|creep", fetch_steps("Radiohead - Creep"))
    assert new_later and later.id != job.id  # the first one is done


def test_the_queue_holds_a_limited_number_of_requests():
    queue = JobQueue(FakeRunner(), limit=2)
    queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    queue.submit("Add A - 2", "a|2", add_steps("A", "2"))
    with pytest.raises(QueueFull):
        queue.submit("Add A - 3", "a|3", add_steps("A", "3"))
    queue.run_pending()
    queue.submit("Add A - 3", "a|3", add_steps("A", "3"))  # room again


def test_finished_jobs_are_forgotten_beyond_a_few():
    queue = JobQueue(FakeRunner(), keep=3)
    for n in range(5):
        queue.submit(f"Add A - {n}", f"a|{n}", add_steps("A", str(n)))
        queue.run_pending()
    assert [j.title for j in queue.snapshot()] == ["Add A - 4", "Add A - 3", "Add A - 2"]  # newest first


def test_the_songs_being_fetched_are_those_of_queued_or_running_fetches():
    queue = JobQueue(FakeRunner())
    queue.submit("Fetch Radiohead - Creep", "radiohead|creep", fetch_steps("Radiohead - Creep"), fetching=True)
    queue.submit("Add Oasis - Wonderwall", "oasis|wonderwall", add_steps("Oasis", "Wonderwall"))
    assert queue.fetching_keys() == {"radiohead|creep"}
    assert queue.active_count() == 2
    queue.run_pending()
    assert queue.fetching_keys() == set() and queue.active_count() == 0


def test_a_snapshot_is_a_copy():
    queue = JobQueue(FakeRunner())
    queue.submit("Add A - B", "a|b", add_steps("A", "B"))
    copy = queue.snapshot()[0]
    copy.steps[0].output.append("changed")
    copy.state = "done"
    assert queue.snapshot()[0].state == "queued" and queue.snapshot()[0].steps[0].output == []


def test_a_steps_output_keeps_its_last_lines():
    queue = JobQueue(FakeRunner(lines={"match": [f"line {n}" for n in range(1000)]}), max_lines=50)
    queue.submit("Fetch A - B", "a|b", fetch_steps("A - B"))
    queue.run_pending()
    step = queue.snapshot()[0].steps[0]
    assert step.output == [f"line {n}" for n in range(950, 1000)] and step.dropped == 950


def test_the_worker_runs_jobs_in_the_background_and_stops():
    started = threading.Event()
    release = threading.Event()

    class Slow(FakeRunner):
        def __call__(self, args, emit):
            started.set()
            release.wait(5)
            return super().__call__(args, emit)

    runner = Slow()
    queue = JobQueue(runner)
    queue.start()
    try:
        queue.submit("Add A - B", "a|b", add_steps("A", "B"))
        assert started.wait(5)
        assert queue.snapshot()[0].state == "running"
        release.set()
        for _ in range(100):
            if queue.snapshot()[0].state == "done":
                break
            threading.Event().wait(0.05)
        assert queue.snapshot()[0].state == "done"
    finally:
        queue.stop()
    assert runner.terminated


def test_the_child_finds_caracole_and_writes_each_line_at_once():
    env = child_env({"PATH": "/bin", "CARACOLE_CONFIG": "/etc/caracole.toml"})
    assert env["PATH"] == "/bin" and env["CARACOLE_CONFIG"] == "/etc/caracole.toml"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert str(Path(__import__("caracole").__file__).parents[1]) in env["PYTHONPATH"].split(":")


def test_the_runner_runs_the_caracole_command_line(tmp_path, monkeypatch):
    src = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", subprocess_pythonpath(src))
    config = tmp_path / "caracole.toml"
    config.write_text(f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
                      f'cache_dir = "{tmp_path / "cache"}"\n', encoding="utf-8")
    runner = CaracoleRunner(config, python=sys.executable)
    lines = []
    assert runner(["--version"], lines.append) == 0
    assert lines == ["caracole 0.1.0"]
    lines.clear()
    assert runner(["fetch", "--song=Nobody - Nothing"], lines.append) == 1
    assert any("No song" in line for line in lines), lines
