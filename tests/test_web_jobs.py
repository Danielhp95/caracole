"""caracole/web/jobs.py: the queue of requests, run one caracole command at a time."""

import json
import sys
import threading
from pathlib import Path

import pytest

from caracole.web.jobs import (
    CaracoleRunner,
    JobQueue,
    JobStarted,
    QueueFull,
    add_steps,
    child_env,
    fetch_steps,
    lookup_steps,
    version_steps,
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


def test_a_lookup_can_leave_its_songbooks_to_a_later_job():
    assert lookup_steps("Radiohead", "Creep", songbooks=False) == [
        ("Look it up now", ("get", "--progress", "--no-songbooks", "--", "Radiohead", "Creep"))]


def test_a_request_is_caracole_add_and_a_fetch_is_match_fetch_render():
    # Each label is what the song's card says while the step runs: "Fetching from Ultimate Guitar…".
    assert add_steps("Radiohead", "Creep") == [("Adding to the library", ("add", "--", "Radiohead", "Creep"))]
    assert add_steps("-rf", "--help", album="OK Computer", duration_ms=239000) == [
        ("Adding to the library", ("add", "--album=OK Computer", "--duration=3:59", "--", "-rf", "--help"))]
    assert fetch_steps("Radiohead - Creep") == [
        ("Looking it up", ("match",)),
        ("Fetching from Ultimate Guitar", ("fetch", "--song=Radiohead - Creep")),
        ("Rendering the sheet", ("render", "--song=Radiohead - Creep")),
    ]


def test_a_request_is_caracole_add_and_a_lookup_is_one_caracole_get():
    assert add_steps("Radiohead", "Creep") == [("Adding to the library", ("add", "--", "Radiohead", "Creep"))]
    assert add_steps("-rf", "--help", album="OK Computer", duration_ms=239000) == [
        ("Adding to the library", ("add", "--album=OK Computer", "--duration=3:59", "--", "-rf", "--help"))]
    # One process for the whole lookup, which reports its stages as JSON lines.
    assert lookup_steps("Radiohead", "Creep") == [("Look it up now", ("get", "--progress", "--", "Radiohead", "Creep"))]
    assert lookup_steps("-rf", "--help", album="OK Computer", duration_ms=239000, ug="radiohead/creep",
                        tab="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169") == [
        ("Look it up now", ("get", "--progress", "--album=OK Computer", "--duration=3:59", "--ug=radiohead/creep",
                            "--tab=https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169", "--", "-rf",
                            "--help"))]


def test_a_job_keeps_the_song_it_is_for():
    queue = JobQueue(FakeRunner())
    add, _ = queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep"),
                          display="Radiohead - Creep")
    assert add.display == "Radiohead - Creep"
    fetch, _ = queue.submit("Fetch Radiohead - Creep", "radiohead|creep", fetch_steps("Radiohead - Creep"),
                            fetching=True, display="Radiohead - Creep")
    assert fetch.id == add.id and fetch.display == "Radiohead - Creep"
    other, _ = queue.submit("Add Oasis - Wonderwall", "oasis|wonderwall", add_steps("Oasis", "Wonderwall"))
    assert other.display == "Add Oasis - Wonderwall"  # none given: its title


def test_jobs_run_their_steps_in_order_one_job_at_a_time():
    runner = FakeRunner()
    queue = JobQueue(runner)
    first, new = queue.submit("Get Radiohead - Creep", "radiohead|creep",
                              add_steps("Radiohead", "Creep") + lookup_steps("Radiohead", "Creep"), fetching=True)
    second, _ = queue.submit("Add Oasis - Wonderwall", "oasis|wonderwall", add_steps("Oasis", "Wonderwall"))
    assert new and [j.state for j in queue.snapshot()] == ["queued", "queued"]
    queue.run_pending()
    assert [c[0] for c in runner.calls] == ["add", "get", "add"]
    jobs = {j.id: j for j in queue.snapshot()}
    assert jobs[first.id].state == "done" and jobs[second.id].state == "done"
    assert [s.state for s in jobs[first.id].steps] == ["done"] * 2
    assert jobs[first.id].steps[1].output == ["ran get"] and jobs[first.id].steps[1].code == 0
    assert jobs[first.id].started_at is not None and jobs[first.id].finished_at is not None


def test_a_step_that_fails_stops_its_job():
    runner = FakeRunner(codes={"add": 1}, lines={"add": ["can't update wanted.txt: Permission denied"]})
    queue = JobQueue(runner)
    job, _ = queue.submit("Get Radiohead - Creep", "radiohead|creep",
                          add_steps("Radiohead", "Creep") + lookup_steps("Radiohead", "Creep"))
    queue.run_pending()
    done = queue.snapshot()[0]
    assert done.state == "failed"
    assert [(s.state, s.code) for s in done.steps] == [("failed", 1), ("skipped", None)]
    assert [c[0] for c in runner.calls] == ["add"]
    assert "Permission denied" in done.steps[0].output[0]


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
    job, new = queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"))
    again, new_again = queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"))
    assert new and not new_again and again.id == job.id
    queue.run_pending()
    later, new_later = queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"))
    assert new_later and later.id != job.id  # the first one is done


def test_a_lookup_takes_the_place_of_a_waiting_add_of_the_same_song():
    # `caracole get` adds the song itself: one process, not two start-ups.
    queue = JobQueue(FakeRunner())
    add, _ = queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep"),
                          note="Added to wanted.txt, line 3.")
    lookup, new = queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"),
                               fetching=True)
    assert not new and lookup.id == add.id
    assert lookup.title == "Get Radiohead - Creep" and lookup.fetching and lookup.note == "Added to wanted.txt, line 3."
    assert [s.args[0] for s in lookup.steps] == ["get"]
    assert [s.name for s in lookup.stages][:3] == ["song", "match", "sheet"]
    assert queue.fetching_keys() == {"radiohead|creep"} and queue.active_count() == 1


def test_an_add_never_replaces_a_lookup_of_the_same_song():
    queue = JobQueue(FakeRunner())
    lookup, _ = queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"),
                             fetching=True)
    add, new = queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep"))
    assert not new and add.id == lookup.id and add.title == "Get Radiohead - Creep"
    assert [s.args[0] for s in add.steps] == ["get"]


def test_a_fetch_joins_a_waiting_add_of_the_same_song():
    queue = JobQueue(FakeRunner())
    add, _ = queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep"),
                          note="Added to wanted.txt, line 3.")
    fetch, new = queue.submit("Fetch Radiohead - Creep", "radiohead|creep",
                              add_steps("Radiohead", "Creep") + fetch_steps("Radiohead - Creep"), fetching=True)
    assert not new and fetch.id == add.id
    assert fetch.title == "Fetch Radiohead - Creep" and fetch.fetching and fetch.note == "Added to wanted.txt, line 3."
    assert [s.args[0] for s in fetch.steps] == ["add", "match", "fetch", "render"]  # the add once
    assert queue.fetching_keys() == {"radiohead|creep"} and queue.active_count() == 1


def test_a_fetch_that_joins_an_add_runs_caracole_add_once_whatever_its_album():
    # The server wrote wanted.txt already; a second `caracole add` would leave the line as it is.
    queue = JobQueue(FakeRunner())
    queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep", album="Pablo Honey"))
    job, _ = queue.submit("Fetch Radiohead - Creep", "radiohead|creep",
                          add_steps("Radiohead", "Creep") + fetch_steps("Radiohead - Creep"), fetching=True)
    assert [s.args for s in job.steps] == [("add", "--album=Pablo Honey", "--", "Radiohead", "Creep"), ("match",),
                                           ("fetch", "--song=Radiohead - Creep"), ("render", "--song=Radiohead - Creep")]


def test_an_add_never_replaces_a_fetch_of_the_same_song():
    queue = JobQueue(FakeRunner())
    fetch, _ = queue.submit("Fetch Radiohead - Creep", "radiohead|creep", fetch_steps("Radiohead - Creep"),
                            fetching=True)
    add, new = queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep"))
    assert not new and add.id == fetch.id and add.title == "Fetch Radiohead - Creep"
    assert [s.args[0] for s in add.steps] == ["match", "fetch", "render"]


def test_a_fetch_asked_for_while_the_songs_add_runs_comes_after_it():
    asked = []
    calls = []

    def runner(args, emit):  # requests that arrive while `caracole add` runs
        if args[0] == "add" and not asked:
            asked.append(queue.submit("Fetch Radiohead - Creep", "radiohead|creep",
                                      add_steps("Radiohead", "Creep") + fetch_steps("Radiohead - Creep"),
                                      fetching=True))
            asked.append(queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep")))
        calls.append(args[0])
        return 0

    queue = JobQueue(runner)
    first, _ = queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep"))
    queue.run_pending()
    (fetch, new), (again, new_again) = asked
    assert new and fetch.id != first.id and fetch.fetching
    assert not new_again and again.id == fetch.id  # it joins the fetch, which does more
    assert calls == ["add", "add", "match", "fetch", "render"]
    assert [j.state for j in queue.snapshot()] == ["done", "done"]


def test_a_lookup_asked_for_while_the_songs_add_runs_comes_after_it():
    asked = []
    calls = []

    def runner(args, emit):  # requests that arrive while `caracole add` runs
        if args[0] == "add" and not asked:
            asked.append(queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"),
                                      fetching=True))
            asked.append(queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep")))
        calls.append(args[0])
        return 0

    queue = JobQueue(runner)
    first, _ = queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep"))
    queue.run_pending()
    (lookup, new), (again, new_again) = asked
    assert new and lookup.id != first.id and lookup.fetching
    assert not new_again and again.id == lookup.id  # it joins the lookup, which does more
    assert calls == ["add", "get"]
    assert [j.state for j in queue.snapshot()] == ["done", "done"]


@pytest.mark.parametrize("state", ["queued", "running"])
def test_a_job_that_mustnt_join_another_gets_the_songs_job_unchanged(state):
    # A pick: its `caracole review` must come after the song's own request, never be dropped into it.
    asked = []

    def runner(args, emit):
        if state == "running" and not asked:
            asked.append(queue.submit("Pick", "radiohead|creep", review, fetching=True, join=False))
        return 0

    review = [("Writing the answer to overrides.toml", ("review", "--song=Radiohead - Creep", "--pick=radiohead/creep"))]
    queue = JobQueue(runner)
    add, _ = queue.submit("Add Radiohead - Creep", "radiohead|creep", add_steps("Radiohead", "Creep"))
    if state == "queued":
        asked.append(queue.submit("Pick", "radiohead|creep", review, fetching=True, join=False))
    queue.run_pending()
    [(job, new)] = asked
    assert not new and job.id == add.id and job.title == "Add Radiohead - Creep" and not job.fetching
    assert [[s.args[0] for s in j.steps] for j in queue.snapshot()] == [["add"]]
    assert queue.submit("Pick", "radiohead|creep", review, join=False)[1]  # once it ended


TAB_A = "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-chords-6789"
TAB_B = "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-chords-6790"


def test_a_version_picked_while_the_songs_lookup_runs_is_looked_up_after_it():
    # Get it, read the first sheet, find it's the wrong version, pick another while the lookup goes on.
    picked = []
    calls = []

    def runner(args, emit):
        if not picked:
            picked.append(queue.submit("Fetch Oasis - Wonderwall", "oasis/wonderwall",
                                       lookup_steps("Oasis", "Wonderwall", ug="oasis/wonderwall", tab=TAB_A),
                                       fetching=True))
        calls.append(list(args))
        return 0

    queue = JobQueue(runner)
    first, _ = queue.submit("Fetch Oasis - Wonderwall", "oasis/wonderwall",
                            lookup_steps("Oasis", "Wonderwall", ug="oasis/wonderwall"), fetching=True)
    queue.run_pending()
    [(pick, new)] = picked
    assert new and pick.id != first.id
    assert [c for c in calls[1] if c.startswith("--tab")] == [f"--tab={TAB_A}"]
    assert [j.state for j in queue.snapshot()] == ["done", "done"]


def test_a_newer_pick_replaces_the_one_still_waiting_and_the_same_pick_is_the_same_job():
    queue = JobQueue(FakeRunner())
    first, _ = queue.submit("Fetch Oasis - Wonderwall", "oasis/wonderwall",
                            lookup_steps("Oasis", "Wonderwall", ug="oasis/wonderwall"), fetching=True)
    pick, new = queue.submit("Fetch Oasis - Wonderwall", "oasis/wonderwall",
                             lookup_steps("Oasis", "Wonderwall", ug="oasis/wonderwall", tab=TAB_A), fetching=True)
    assert not new and pick.id == first.id  # nothing ran yet: the waiting job looks the pick up instead
    assert [s.args for s in pick.steps] == [lookup_steps("Oasis", "Wonderwall", ug="oasis/wonderwall", tab=TAB_A)[0][1]]
    same, new_same = queue.submit("Fetch Oasis - Wonderwall", "oasis/wonderwall",
                                  lookup_steps("Oasis", "Wonderwall", ug="oasis/wonderwall", tab=TAB_A), fetching=True)
    assert not new_same and same.id == first.id
    plain, new_plain = queue.submit("Fetch Oasis - Wonderwall", "oasis/wonderwall",
                                    lookup_steps("Oasis", "Wonderwall"), fetching=True)
    assert not new_plain and plain.id == first.id  # no pick: the waiting one does as much
    other, _ = queue.submit("Fetch Oasis - Wonderwall", "oasis/wonderwall",
                            lookup_steps("Oasis", "Wonderwall", tab=TAB_B), fetching=True)
    assert other.id == first.id and other.steps[0].args[2] == f"--tab={TAB_B}"
    assert queue.active_count() == 1


def test_a_lookup_asked_for_while_the_songs_keep_it_waits_joins_it():
    # Keep it fetches one tab page and keeps it beside the sheet: it never looks the song up, so it doesn't do as
    # much as Fetch now, which must still run.
    queue = JobQueue(FakeRunner())
    keep, _ = queue.submit("Keep it", "a|t", version_steps("A", "T", keep="123"), fetching=True)
    fetch, new = queue.submit("Fetch A - T", "a|t", lookup_steps("A", "T"), fetching=True)
    assert not new and fetch.id == keep.id
    assert [s.args[0] for s in fetch.steps] == ["versions", "get"]
    assert {"song", "sheet", "version"} <= {s.name for s in fetch.stages}
    again, new_again = queue.submit("Fetch A - T", "a|t", lookup_steps("A", "T"), fetching=True)
    assert not new_again and again.id == keep.id and [s.args[0] for s in again.steps] == ["versions", "get"]
    queue.run_pending()
    assert [call[0] for call in queue._runner.calls] == ["versions", "get"]


def test_a_lookup_asked_for_while_the_songs_keep_it_runs_comes_after_it():
    asked = []

    def runner(args, emit):
        if args[0] == "versions" and not asked:
            asked.append(queue.submit("Fetch A - T", "a|t", lookup_steps("A", "T"), fetching=True))
            asked.append(queue.submit("Fetch A - T", "a|t", lookup_steps("A", "T"), fetching=True))
        calls.append(args[0])
        return 0

    calls = []
    queue = JobQueue(runner)
    keep, _ = queue.submit("Keep it", "a|t", version_steps("A", "T", keep="123"), fetching=True)
    queue.run_pending()
    (fetch, new), (again, new_again) = asked
    assert new and fetch.id != keep.id and not new_again and again.id == fetch.id
    assert calls == ["versions", "get"]


PROGRESS = "caracole-progress: "


def lookup_output():
    """What `caracole get --progress` prints for a song looked up now."""
    events = [
        {"stage": "song", "state": "running", "detail": ""},
        {"song": {"id": 7, "display": "Radiohead - Creep"}},
        {"stage": "song", "state": "done", "detail": "added to wanted.txt, line 16"},
        {"stage": "sheet", "state": "running", "detail": ""},
        {"stage": "sheet", "state": "done", "detail": "tab 101 from Ultimate Guitar"},
        {"files": {"sheet": "Radiohead/Creep/sheet.txt"}, "seconds": 2.25},
        {"stage": "lyrics", "state": "running", "detail": ""},
    ]
    lines = [PROGRESS + json.dumps(e) for e in events]
    return lines[:5] + ["Sheet: tab 101 from Ultimate Guitar: /lib/Radiohead/Creep/sheet.txt"] + lines[5:]


def test_a_lookups_progress_becomes_its_stages_and_stays_out_of_its_output():
    queue = JobQueue(FakeRunner(lines={"get": lookup_output()}))
    queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"), fetching=True)
    queue.run_pending()
    job = queue.snapshot()[0]
    states = {s.name: (s.state, s.detail) for s in job.stages}
    assert states["song"] == ("done", "added to wanted.txt, line 16")
    assert states["sheet"] == ("done", "tab 101 from Ultimate Guitar")
    assert states["lyrics"][0] == "done" and states["pdf"][0] == "skipped"  # the fake stopped there, as it ended
    assert (job.song_id, job.files, job.seconds_to_sheet) == (7, {"sheet": "Radiohead/Creep/sheet.txt"}, 2.25)
    assert job.steps[0].output == ["Sheet: tab 101 from Ultimate Guitar: /lib/Radiohead/Creep/sheet.txt"]


def test_a_job_is_data_its_steps_each_with_a_state():
    queue = JobQueue(FakeRunner(lines={"get": lookup_output()}))
    job, _ = queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"),
                          fetching=True)
    queued = queue.job(job.id).as_json()
    assert queued["state"] == "queued" and queued["steps"][0] == {
        "name": "song", "label": "Find the song", "state": "waiting", "detail": ""}
    queue.run_pending()
    data = queue.job(job.id).as_json()
    json.dumps(data)  # plain data
    assert (data["id"], data["title"], data["state"]) == (job.id, "Get Radiohead - Creep", "done")
    assert data["steps"][2] == {"name": "sheet", "label": "The sheet", "state": "done",
                                "detail": "tab 101 from Ultimate Guitar"}
    assert data["song"] == {"id": 7, "display": "Radiohead - Creep"}
    assert data["files"] == {"sheet": "Radiohead/Creep/sheet.txt"} and data["seconds_to_sheet"] == 2.25
    assert data["commands"] == [{"label": "Look it up now", "args": ["get", "--progress", "--", "Radiohead", "Creep"],
                                 "state": "done", "code": 0}]
    assert queue.job(999) is None


def test_a_lookup_that_ends_early_leaves_no_stage_running():
    lines = [PROGRESS + json.dumps({"stage": "song", "state": "running", "detail": ""}), "Traceback (most recent ..."]
    queue = JobQueue(FakeRunner(codes={"get": 1}, lines={"get": lines}))
    queue.submit("Get A - B", "a|b", lookup_steps("A", "B"), fetching=True)
    queue.run_pending()
    job = queue.snapshot()[0]
    assert job.state == "failed"
    assert [s.state for s in job.stages] == ["failed"] + ["skipped"] * (len(job.stages) - 1)


def test_a_job_of_commands_is_data_too():
    queue = JobQueue(FakeRunner())
    job, _ = queue.submit("Add Oasis - Wonderwall", "oasis|wonderwall", add_steps("Oasis", "Wonderwall"))
    data = queue.job(job.id).as_json()
    assert data["steps"] == [{"name": "add", "label": "Adding to the library", "state": "waiting", "detail": ""}]
    assert data["song"] is None and data["files"] == {}


def test_the_queue_holds_a_limited_number_of_requests():
    queue = JobQueue(FakeRunner(), limit=2)
    queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    queue.submit("Add A - 2", "a|2", add_steps("A", "2"))
    with pytest.raises(QueueFull):
        queue.submit("Add A - 3", "a|3", add_steps("A", "3"))
    queue.run_pending()
    queue.submit("Add A - 3", "a|3", add_steps("A", "3"))  # room again


def test_a_job_that_has_not_started_can_be_cancelled_never_one_that_runs_or_ended():
    started = threading.Event()
    go_on = threading.Event()

    def slow(args, emit):
        started.set()
        go_on.wait(10)
        return 0

    queue = JobQueue(slow)
    first, _ = queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    second, _ = queue.submit("Add A - 2", "a|2", add_steps("A", "2"))
    third, _ = queue.submit("Add A - 3", "a|3", add_steps("A", "3"))
    queue.start()
    try:
        assert started.wait(10)
        # The running one is never stopped halfway: JobStarted, and it goes on.
        with pytest.raises(JobStarted):
            queue.cancel(first.id)
        cancelled = queue.cancel(second.id)
        assert cancelled is not None and cancelled.id == second.id and cancelled.title == "Add A - 2"
        # Over, never run: it stays in the history, so that a page following it hears that it ended.
        assert cancelled.state == "cancelled" and not cancelled.active and cancelled.finished_at is not None
        assert [s.state for s in cancelled.steps] == ["skipped"]
        assert [(j.id, j.state) for j in queue.snapshot()] == [(third.id, "queued"), (second.id, "cancelled"),
                                                                (first.id, "running")]
        assert queue.cancel(second.id) is None  # cancelled already: nothing to cancel
        assert queue.cancel(99) is None
    finally:
        go_on.set()
        queue.stop()
    assert {j.id: j.state for j in queue.snapshot()} == {third.id: "queued", second.id: "cancelled",
                                                         first.id: "done"}
    with pytest.raises(JobStarted):  # over: it stays in the history
        queue.cancel(first.id)


def test_jobs_queued_together_are_cancelled_together_while_they_wait():
    queue = JobQueue(FakeRunner())
    alone, _ = queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    (first, _), (second, _) = queue.submit_all([
        {"title": "Fetch B - 2", "song_key": "b|2", "steps": add_steps("B", "2"), "fetching": True},
        {"title": "Put B - 2 in a songbook", "song_key": "songbook|b|2", "steps": [("Adding", ("songbook", "add"))]}])
    assert queue.cancel(second.id).id == second.id
    assert [(j.id, j.state) for j in queue.snapshot()] == [(second.id, "cancelled"), (first.id, "cancelled"),
                                                            (alone.id, "queued")]
    # One of them running: the one that waits still goes, and the running one runs on.
    (first, _), (second, _) = queue.submit_all([
        {"title": "Fetch C - 3", "song_key": "c|3", "steps": add_steps("C", "3"), "fetching": True},
        {"title": "Put C - 3 in a songbook", "song_key": "songbook|c|3", "steps": [("Adding", ("songbook", "add"))]}])
    with queue._lock:
        next(j for j in queue._jobs if j.id == first.id).state = "running"
    queue.cancel(second.id)
    assert sorted(j.id for j in queue.snapshot() if j.state != "cancelled") == [alone.id, first.id]
    assert next(j for j in queue.snapshot() if j.id == second.id).state == "cancelled"


def test_a_cancelled_job_makes_room_in_the_queue():
    queue = JobQueue(FakeRunner(), limit=2)
    queue.submit("Add A - 1", "a|1", add_steps("A", "1"))
    waiting, _ = queue.submit("Add A - 2", "a|2", add_steps("A", "2"))
    with pytest.raises(QueueFull):
        queue.submit("Add A - 3", "a|3", add_steps("A", "3"))
    queue.cancel(waiting.id)
    queue.submit("Add A - 3", "a|3", add_steps("A", "3"))
    queue.run_pending()
    assert sorted((j.title, j.state) for j in queue.snapshot()) == [
        ("Add A - 1", "done"), ("Add A - 2", "cancelled"), ("Add A - 3", "done")]


def test_finished_jobs_are_forgotten_beyond_a_few():
    queue = JobQueue(FakeRunner(), keep=3)
    for n in range(5):
        queue.submit(f"Add A - {n}", f"a|{n}", add_steps("A", str(n)))
        queue.run_pending()
    assert [j.title for j in queue.snapshot()] == ["Add A - 4", "Add A - 3", "Add A - 2"]  # newest first


def test_the_songs_being_fetched_are_those_of_queued_or_running_fetches():
    queue = JobQueue(FakeRunner())
    queue.submit("Get Radiohead - Creep", "radiohead|creep", lookup_steps("Radiohead", "Creep"), fetching=True)
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
    queue = JobQueue(FakeRunner(lines={"get": [f"line {n}" for n in range(1000)]}), max_lines=50)
    queue.submit("Get A - B", "a|b", lookup_steps("A", "B"))
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


@pytest.mark.slow
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


@pytest.mark.slow
def test_the_child_never_imports_a_module_from_the_folder_it_runs_in(tmp_path, monkeypatch):
    # `cd ~/Tabs && caracole serve`: a typer.py dropped into the synced library must not run.
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / "typer.py").write_text("import sys\nprint('PLANTED typer.py RAN')\nsys.exit(7)\n", encoding="utf-8")
    src = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", subprocess_pythonpath(src))
    monkeypatch.chdir(planted)
    runner = CaracoleRunner(None, python=sys.executable)
    lines = []
    assert runner(["--version"], lines.append) == 0, lines
    assert lines == ["caracole 0.1.0"]
