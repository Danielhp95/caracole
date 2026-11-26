"""caracole/web/jobs.py: the queue of requests, run one caracole command at a time, and the lookups' lane beside it."""

import collections
import json
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from caracole.web.jobs import (
    EXPORTING,
    INTERRUPTED,
    LANE,
    LANE_WAITING,
    LIMIT,
    MINE,
    READING,
    REMOVING,
    YOUTUBE_SHEET,
    CaracoleRunner,
    Job,
    JobQueue,
    JobStarted,
    QueueFull,
    add_steps,
    ahead,
    child_env,
    fetch_steps,
    harptabs_artist_steps,
    lacuerda_artist_steps,
    lacuerda_search_steps,
    lane_of,
    lookup_steps,
    remove_steps,
    ug_link_steps,
    version_steps,
    youtube_search_steps,
    youtube_sheet_steps,
    youtube_video_steps,
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
        ("Fetching", ("get", "--progress", "--no-songbooks", "--", "Radiohead", "Creep"))]


def test_a_request_is_caracole_add_and_a_fetch_is_match_fetch_render():
    # Each label is what the song's card says while the step runs: "Fetching from Ultimate Guitar…".
    assert add_steps("Radiohead", "Creep") == [("Adding to the book", ("add", "--", "Radiohead", "Creep"))]
    assert add_steps("-rf", "--help", album="OK Computer", duration_ms=239000) == [
        ("Adding to the book", ("add", "--album=OK Computer", "--duration=3:59", "--", "-rf", "--help"))]
    assert fetch_steps("Radiohead - Creep") == [
        ("Matching", ("match",)),
        ("Fetching from UG", ("fetch", "--song=Radiohead - Creep")),
        ("Making the PDF", ("render", "--song=Radiohead - Creep")),
    ]


def test_a_request_is_caracole_add_and_a_lookup_is_one_caracole_get():
    assert add_steps("Radiohead", "Creep") == [("Adding to the book", ("add", "--", "Radiohead", "Creep"))]
    assert add_steps("-rf", "--help", album="OK Computer", duration_ms=239000) == [
        ("Adding to the book", ("add", "--album=OK Computer", "--duration=3:59", "--", "-rf", "--help"))]
    # One process for the whole lookup, which reports its stages as JSON lines.
    assert lookup_steps("Radiohead", "Creep") == [("Fetching", ("get", "--progress", "--", "Radiohead", "Creep"))]
    assert lookup_steps("-rf", "--help", album="OK Computer", duration_ms=239000, ug="radiohead/creep",
                        tab="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169") == [
        ("Fetching", ("get", "--progress", "--album=OK Computer", "--duration=3:59", "--ug=radiohead/creep",
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

    review = [("Noting your answer in overrides.toml", ("review", "--song=Radiohead - Creep", "--pick=radiohead/creep"))]
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
TAB = TAB_A
VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


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


def test_a_lookup_that_joined_a_keep_it_starts_its_stages_afresh():
    # Keep it's stages share names with a lookup's (the song, the PDF, the library page): once it is over, the lookup
    # after it says each of its own from the start, never Keep it's PDF done while its own sheet is asked for.
    from caracole.web.outcome import progress
    from caracole.web.status import job_line

    seen = []

    def runner(args, emit):
        said = [("song", "running", ""), ("song", "done", "in the book")]
        said += ([("version", "running", ""), ("version", "done", "tab 3 kept"), ("pdf", "running", ""),
                  ("pdf", "done", "made"), ("pages", "running", ""), ("pages", "done", "")]
                 if args[0] == "versions" else
                 [("match", "running", ""), ("match", "done", "matched to a/t"), ("sheet", "running", "")])
        for stage, state, detail in said:
            emit(PROGRESS + json.dumps({"stage": stage, "state": state, "detail": detail}))
        if args[0] == "get":
            job = queue.snapshot()[0]
            seen.append({s.name: s.state for s in job.stages})
            seen.append(progress(job, job_line(job, None), None, now=job.started_at + timedelta(seconds=5)))
        return 0

    queue = JobQueue(runner)
    queue.submit("Keep it", "a|t", version_steps("A", "T", keep="3"), fetching=True)
    queue.submit("Fetch A - T", "a|t", lookup_steps("A", "T"), fetching=True)
    queue.run_pending()
    stages, shown = seen
    assert {name: stages[name] for name in ("song", "match", "sheet", "pdf", "lyrics", "pages")} == {
        "song": "done", "match": "done", "sheet": "running", "pdf": "waiting", "lyrics": "waiting",
        "pages": "waiting"}
    assert [(c["name"], c["state"]) for c in shown["steps"]][:4] == [
        ("Song", "done"), ("Match", "done"), ("Sheet", "running"), ("PDF", "waiting")]
    assert shown["count"] == "3 of 7"


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


def test_a_stage_keeps_what_it_said_last_while_it_ran_once_it_ends():
    # The site a sheet stage asked when it failed (get.SHEET_FROM): its Sheet step names it (outcome.py).
    queue = JobQueue(FakeRunner())
    job, _ = queue.submit("Get A - B", "a|b", lookup_steps("A", "B"), fetching=True)
    job = queue.job(job.id)
    job.heard({"stage": "sheet", "state": "running", "detail": ""})
    job.heard({"stage": "sheet", "state": "running", "detail": "from LaCuerda"})
    job.heard({"stage": "sheet", "state": "failed", "detail": "LaCuerda failed (lacuerda: 503); the nightly run "
                                                              "tries again"})
    sheet = next(s for s in job.stages if s.name == "sheet")
    assert (sheet.state, sheet.running_detail) == ("failed", "from LaCuerda")
    assert sheet.detail.startswith("LaCuerda failed")
    assert "running_detail" not in json.dumps(job.as_json())  # the request as data says what it ended with


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
    assert data["steps"][2] == {"name": "sheet", "label": "Sheet", "state": "done",
                                "detail": "tab 101 from Ultimate Guitar"}
    assert data["song"] == {"id": 7, "display": "Radiohead - Creep"}
    assert data["files"] == {"sheet": "Radiohead/Creep/sheet.txt"} and data["seconds_to_sheet"] == 2.25
    assert data["commands"] == [{"label": "Fetching", "args": ["get", "--progress", "--", "Radiohead", "Creep"],
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
    assert data["steps"] == [{"name": "add", "label": "Adding to the book", "state": "waiting", "detail": ""}]
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
def test_a_lookup_queued_behind_an_add_never_waits_behind_the_whole_nightly_run(tmp_path, monkeypatch):
    # serve runs its commands one at a time: an add (a request without Fetch) waiting for the run as bulk work
    # does would hold every lookup queued after it until the run's end. It waits as a lookup does instead, so
    # the run hands the lock over at its next pause, to it and then to the lookup.
    import time

    from caracole.commands import _common
    from caracole.config import load_config

    src = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", subprocess_pythonpath(src))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # a dead end: the lookup reaches no site
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    config = tmp_path / "caracole.toml"
    config.write_text(f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
                      f'cache_dir = "{tmp_path / "cache"}"\nmusic_dir = "{tmp_path / "music"}"\n', encoding="utf-8")
    cfg = load_config(config, env={"HOME": str(tmp_path / "home")})
    queue = JobQueue(CaracoleRunner(config, python=sys.executable))
    ended = ("done", "failed")
    with _common.exclusive(cfg, "run"):  # the nightly run holds caracole's lock, and pauses between requests
        queue.start()
        try:
            add, _ = queue.submit("Add Radiohead - Creep", "radiohead/creep", add_steps("Radiohead", "Creep"))
            get, _ = queue.submit("Fetch Muse - Uprising", "muse/uprising", lookup_steps("Muse", "Uprising"),
                                  fetching=True)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and queue.job(get.id).state not in ended:
                _common.hand_over(cfg)  # each of the run's pauses
                time.sleep(0.05)
            states = (queue.job(add.id).state, queue.job(get.id).state in ended)
        finally:
            queue.stop()
    assert states == ("done", True), [step.output for step in queue.job(add.id).steps]

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


# --- a sheet from a YouTube video ----------------------------------------------------------------------


def test_a_sheet_from_youtube_is_one_caracole_youtube_sheet_whose_progress_is_its_stages():
    from caracole.web.jobs import YOUTUBE_SHEET, song_key_of, youtube_sheet_steps
    from caracole.youtube_sheet import STAGES

    steps = youtube_sheet_steps("Nick Cani - Vikingos veganos", "https://www.youtube.com/watch?v=lzN7Thn3FV4")
    assert steps == [("Making the sheet", (
        "youtube", "--sheet", "--progress", "--url=https://www.youtube.com/watch?v=lzN7Thn3FV4",
        "--song=Nick Cani - Vikingos veganos"))]
    progress = ['caracole-progress: {"song":{"id":7,"display":"Nick Cani - Vikingos veganos"}}',
                'caracole-progress: {"stage":"audio","state":"running","detail":""}',
                "yt-dlp: downloading"]
    queue = JobQueue(FakeRunner(lines={"youtube": progress}))
    job, new = queue.submit("YouTube sheet", YOUTUBE_SHEET + "nick cani/vikingos veganos", steps,
                            display="Nick Cani - Vikingos veganos")
    assert new and [s.name for s in job.stages] == [name for name, _ in STAGES]
    assert song_key_of(job.song_key) == "nick cani/vikingos veganos"
    queue.run_pending()
    done = queue.job(job.id)
    assert done.state == "done" and done.song_id == 7 and done.from_youtube and not done.looks_up
    assert {s.name: s.state for s in done.stages}["audio"] == "done"  # over: nothing left running
    assert done.steps[0].output == ["yt-dlp: downloading"]  # its progress is data, not output


def test_a_sheet_from_youtube_never_joins_the_songs_lookup_nor_a_lookup_it():
    from caracole.web.jobs import YOUTUBE_SHEET, youtube_sheet_steps

    queue = JobQueue(FakeRunner())
    lookup, _ = queue.submit("Fetch Nick Cani - Vikingos veganos", "nick cani/vikingos veganos",
                             lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)
    sheet, new = queue.submit("YouTube sheet", YOUTUBE_SHEET + "nick cani/vikingos veganos",
                              youtube_sheet_steps("Nick Cani - Vikingos veganos", "https://youtu.be/x"))
    assert new and sheet.id != lookup.id
    again, new = queue.submit("YouTube sheet", YOUTUBE_SHEET + "nick cani/vikingos veganos",
                              youtube_sheet_steps("Nick Cani - Vikingos veganos", "https://youtu.be/y"))
    assert not new and again.id == sheet.id  # one at a time a song: the one waiting is the answer
    after, new = queue.submit("Fetch Nick Cani - Vikingos veganos", "nick cani/vikingos veganos",
                              lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)
    assert not new and after.id == lookup.id


# --- a sheet from an audio file you gave ------------------------------------------------------------------------


def test_a_sheet_from_an_audio_file_is_one_caracole_audio_of_the_queue_never_joining_a_lookup():
    from caracole.audio_sheet import STAGES
    from caracole.web.jobs import AUDIO_SHEET, _reports, audio_sheet_steps, song_key_of, song_of_job

    steps = audio_sheet_steps("Nick Cani - Vikingos veganos", "0123456789abcdef")
    assert steps == [("Making the sheet", ("audio", "--progress", "--upload=0123456789abcdef",
                                           "--song=Nick Cani - Vikingos veganos"))]
    assert _reports(steps[0][1]) and not lane_of(steps)
    progress = ['caracole-progress: {"song":{"id":7,"display":"Nick Cani - Vikingos veganos"}}',
                'caracole-progress: {"stage":"audio","state":"running","detail":""}',
                "kept"]
    queue = JobQueue(FakeRunner(lines={"audio": progress}), lane=LANE)
    lookup, _ = queue.submit("Fetch Nick Cani - Vikingos veganos", "nick cani/vikingos veganos",
                             lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)
    job, new = queue.submit("Sheet from an audio file", AUDIO_SHEET + "nick cani/vikingos veganos", steps,
                            display="Nick Cani - Vikingos veganos")
    assert new and job.id != lookup.id and not job.lane
    assert [s.name for s in job.stages] == [name for name, _ in STAGES]
    assert song_key_of(job.song_key) == song_of_job(job.song_key) == "nick cani/vikingos veganos"
    again, new = queue.submit("Sheet from an audio file", AUDIO_SHEET + "nick cani/vikingos veganos",
                              audio_sheet_steps("Nick Cani - Vikingos veganos", "fedcba9876543210"))
    assert not new and again.id == job.id  # one at a time a song: the one waiting is the answer
    queue.run_pending()
    done = queue.job(job.id)
    assert done.state == "done" and done.song_id == 7 and done.from_audio
    assert not done.looks_up and not done.from_youtube and not done.transcribes
    assert done.steps[0].output == ["kept"]  # its progress is data, not output


# --- a song's lyrics transcribed from its audio -----------------------------------------------------------------


def test_a_transcription_is_one_caracole_transcribe_whose_progress_is_its_stages():
    from caracole.transcribe_job import STAGES
    from caracole.web.jobs import TRANSCRIBE, _reports, song_key_of, song_of_job, transcribe_steps

    steps = transcribe_steps("Nick Cani - Vikingos veganos")
    assert steps == [("Transcribing the lyrics",
                      ("transcribe", "--progress", "--song=Nick Cani - Vikingos veganos"))]
    assert _reports(steps[0][1]) and not _reports(("transcribe", "--song=Nick Cani - Vikingos veganos"))
    assert not lane_of(steps)  # the queue's, one at a time: never beside another job in the lane
    progress = ['caracole-progress: {"song":{"id":7,"display":"Nick Cani - Vikingos veganos"}}',
                'caracole-progress: {"stage":"vocals","state":"running","detail":""}',
                "demucs: separating"]
    queue = JobQueue(FakeRunner(lines={"transcribe": progress}), lane=LANE)
    job, new = queue.submit("Lyrics from the audio: Nick Cani - Vikingos veganos",
                            TRANSCRIBE + "nick cani/vikingos veganos", steps, display="Nick Cani - Vikingos veganos")
    assert new and not job.lane and [s.name for s in job.stages] == [name for name, _ in STAGES]
    assert song_key_of(job.song_key) == song_of_job(job.song_key) == "nick cani/vikingos veganos"
    # A lookup of the song asked while it waits goes into the queue behind it, never beside it in the lane.
    lookup, new = queue.submit("Fetch Nick Cani - Vikingos veganos", "nick cani/vikingos veganos",
                               lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)
    assert new and not lookup.lane and lookup.id > job.id
    queue.run_pending()
    done = queue.job(job.id)
    assert done.state == "done" and done.song_id == 7 and done.transcribes
    assert not done.looks_up and not done.from_youtube
    assert {s.name: s.state for s in done.stages}["vocals"] == "done"  # over: nothing left running
    assert done.steps[0].output == ["demucs: separating"]  # its progress is data, not output


# --- a song's lyrics searched under a name, and a record of it picked --------------------------------------------

VIKINGOS = "nick cani/vikingos veganos"


def test_a_lyrics_search_is_the_lanes_and_no_songs():
    from caracole.web.jobs import INDEX_READS, LYRICS_SEARCH, _reports, lyrics_search_steps, song_key_of

    steps = lyrics_search_steps("Nick Cani - Vikingos veganos (Video Oficial)", "Nick Cani - Vikingos veganos")
    assert steps == [("Looking for lyrics under “Nick Cani - Vikingos veganos”",
                      ("lyrics", "--song=Nick Cani - Vikingos veganos (Video Oficial)",
                       "--as=Nick Cani - Vikingos veganos"))]
    assert lane_of(steps) and not _reports(steps[0][1])  # no --progress, no stages: its line is its last line
    assert not lane_of([("Clear", ("lyrics", "--song=A - T", "--clear"))])
    assert not lane_of([("The nightly pass", ("lyrics",))])
    key = LYRICS_SEARCH + VIKINGOS
    assert key.startswith(INDEX_READS) and song_key_of(key) == key  # no song's: the page follows it by its id
    queue = JobQueue(FakeRunner(lines={"lyrics": ["LRCLIB: 2 records", "Searched: 2 records, best fit first."]}),
                     lane=LANE)
    job, new = queue.submit("Lyrics under Nick Cani - Vikingos veganos", key, steps)
    assert new and job.lane and job.stages == []
    again, new = queue.submit("Lyrics under Nick Cani - Vikingos veganos", key, steps)
    assert not new and again.id == job.id  # pressed again: the one waiting is the answer
    queue.run_pending()
    done = queue.job(job.id)
    assert done.state == "done" and done.steps[0].output[-1] == "Searched: 2 records, best fit first."
    assert not done.picks_lyrics and not done.looks_up


def test_a_lyrics_pick_is_the_queues_and_its_songs():
    from caracole.lyrics_pick import STAGES
    from caracole.web.jobs import LYRICS_PICK, _reports, lyrics_pick_steps, song_key_of, song_of_job

    steps = lyrics_pick_steps("Nick Cani - Vikingos veganos (Video Oficial)", "lrclib:28399373")
    assert steps == [("Taking the lyrics", ("lyrics", "--song=Nick Cani - Vikingos veganos (Video Oficial)",
                                            "--record=lrclib:28399373", "--progress"))]
    assert _reports(steps[0][1]) and not lane_of(steps)
    key = LYRICS_PICK + VIKINGOS
    assert song_key_of(key) == song_of_job(key) == VIKINGOS
    progress = ['caracole-progress: {"song":{"id":7,"display":"Nick Cani - Vikingos veganos (Video Oficial)"}}',
                'caracole-progress: {"stage":"lyrics","state":"done","detail":"timed lyrics from LRCLIB"}',
                "kept"]
    queue = JobQueue(FakeRunner(lines={"lyrics": progress}), lane=LANE)
    job, new = queue.submit("Lyrics for Nick Cani - Vikingos veganos (Video Oficial)", key, steps,
                            display="Nick Cani - Vikingos veganos (Video Oficial)")
    assert new and not job.lane and [(s.name, s.label) for s in job.stages] == list(STAGES)
    again, new = queue.submit("Lyrics for Nick Cani - Vikingos veganos (Video Oficial)", key,
                              lyrics_pick_steps("Nick Cani - Vikingos veganos (Video Oficial)", "megalobiz:8"))
    assert not new and again.id == job.id  # one at a time a song: the one waiting is the answer
    # A lookup of the song asked while it waits goes into the queue behind it, never beside it in the lane.
    lookup, new = queue.submit("Fetch Nick Cani - Vikingos veganos", VIKINGOS,
                               lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)
    assert new and not lookup.lane and lookup.id > job.id
    queue.run_pending()
    done = queue.job(job.id)
    assert done.state == "done" and done.song_id == 7 and done.picks_lyrics
    assert not done.looks_up and not done.transcribes and not done.from_youtube
    assert {s.name: s.state for s in done.stages}["lyrics"] == "done"
    assert done.steps[0].output == ["kept"]  # its progress is data, not output


def test_a_lyrics_clear_is_the_queues_and_its_songs_with_no_stages():
    from caracole.web.jobs import LYRICS_CLEAR, LYRICS_PICK, _reports, lyrics_clear_steps, lyrics_pick_steps
    from caracole.web.jobs import song_key_of, song_of_job

    steps = lyrics_clear_steps("Nick Cani - Vikingos veganos (Video Oficial)")
    assert steps == [("Clearing the lyrics record you picked",
                      ("lyrics", "--song=Nick Cani - Vikingos veganos (Video Oficial)", "--clear"))]
    assert not _reports(steps[0][1]) and not lane_of(steps)
    key = LYRICS_CLEAR + VIKINGOS
    assert song_key_of(key) == song_of_job(key) == VIKINGOS  # its view is the song's
    queue = JobQueue(FakeRunner(), lane=LANE)
    pick, _ = queue.submit("Lyrics for …", LYRICS_PICK + VIKINGOS, lyrics_pick_steps("Nick Cani - Vikingos veganos",
                                                                                    "lrclib:1"), join=False)
    clear, new = queue.submit("Clear the lyrics record: …", key, steps, join=False)
    assert new and not clear.lane and clear.stages == [] and clear.id != pick.id  # after the pick, in the queue
    again, new = queue.submit("Clear the lyrics record: …", key, steps, join=False)
    assert not new and again.id == clear.id


def test_neither_joins_the_songs_lookup():
    from caracole.web.jobs import LYRICS_PICK, LYRICS_SEARCH, lyrics_pick_steps, lyrics_search_steps

    queue = JobQueue(FakeRunner())
    get, _ = queue.submit("Fetch Nick Cani - Vikingos veganos", VIKINGOS, lookup_steps("Nick Cani", "Vikingos veganos"),
                          fetching=True)
    search, new = queue.submit("Lyrics under …", LYRICS_SEARCH + VIKINGOS,
                               lyrics_search_steps("Nick Cani - Vikingos veganos", "Nick Cani - Vikingos"))
    assert new and search.id != get.id
    pick, new = queue.submit("Lyrics for …", LYRICS_PICK + VIKINGOS,
                             lyrics_pick_steps("Nick Cani - Vikingos veganos", "lrclib:1"), join=False)
    assert new and pick.id not in (get.id, search.id)
    assert [s.args[0] for s in queue.job(get.id).steps] == ["get"]  # the lookup as it was
    after, new = queue.submit("Fetch Nick Cani - Vikingos veganos", VIKINGOS,
                              lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)
    assert not new and after.id == get.id  # nor a lookup either of them


def test_a_lyrics_search_and_a_pick_or_transcription_of_one_song_never_run_at_once():
    from caracole.web.jobs import LYRICS_PICK, LYRICS_SEARCH, TRANSCRIBE, lyrics_pick_steps, lyrics_search_steps
    from caracole.web.jobs import transcribe_steps

    for first_key, first_steps in ((LYRICS_PICK + VIKINGOS, lyrics_pick_steps("Nick Cani - Vikingos veganos", "x:1")),
                                   (TRANSCRIBE + VIKINGOS, transcribe_steps("Nick Cani - Vikingos veganos"))):
        queue = JobQueue(FakeRunner(), lane=LANE)
        first, _ = queue.submit("First", first_key, first_steps)
        assert queue._next(False).id == first.id  # it runs, in the queue
        search, new = queue.submit("Lyrics under …", LYRICS_SEARCH + VIKINGOS,
                                   lyrics_search_steps("Nick Cani - Vikingos veganos", "Nick Cani - Vikingos"))
        assert new and not search.lane  # behind the song's job, in the queue
        assert queue._next(True) is None  # no lane worker starts it beside it; the queue's one runs it after
        other, _ = queue.submit("Lyrics under …", LYRICS_SEARCH + "muse/uprising",
                                lyrics_search_steps("Muse - Uprising", "Muse - Uprising"))
        assert other.lane and queue._next(True).id == other.id  # another song's: at once, in the lane
    queue = JobQueue(FakeRunner(), lane=LANE)
    search, _ = queue.submit("Lyrics under …", LYRICS_SEARCH + VIKINGOS,
                             lyrics_search_steps("Nick Cani - Vikingos veganos", "Nick Cani - Vikingos"))
    assert search.lane and queue._next(True).id == search.id
    pick, _ = queue.submit("Lyrics for …", LYRICS_PICK + VIKINGOS,
                           lyrics_pick_steps("Nick Cani - Vikingos veganos", "x:1"))
    assert not pick.lane and queue._next(False) is None  # it waits for the search to end


def test_a_lyrics_search_and_a_lookup_of_one_song_both_the_lanes_run_one_after_the_other():
    from caracole.web.jobs import LYRICS_SEARCH, lyrics_search_steps

    def search(queue):
        return queue.submit("Lyrics under …", LYRICS_SEARCH + VIKINGOS,
                            lyrics_search_steps("Nick Cani - Vikingos veganos", "Nick Cani - Vikingos"))[0]

    def get(queue):
        return queue.submit("Fetch Nick Cani - Vikingos veganos", VIKINGOS,
                            lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)[0]

    for first, second in ((search, get), (get, search)):
        queue = JobQueue(FakeRunner(), lane=LANE)
        one = first(queue)
        assert one.lane and queue._next(True).id == one.id
        two = second(queue)
        assert two.lane and two.id != one.id  # neither joins the other
        assert queue._next(True) is None  # never beside it: the song's job runs
        with queue._lock:
            next(job for job in queue._jobs if job.id == one.id).state = "done"
        assert queue._next(True).id == two.id  # then it, in the lane


# --- a sync's report, and an import's stages ------------------------------------------------------------------------

REPORT = {"with": {"name": "Studio", "kind": "server", "address": "http://192.168.1.20:8737"},
          "at": "2026-11-03T18:40:00Z", "parts": ["library", "songbooks", "indexes"],
          "indexes": [{"site": "ug", "title": "Ultimate Guitar", "direction": "taken", "before": 1503236,
                       "after": 1515576, "read": "2026-11-03T02:10:00Z"}]}
SYNC = ("peer", "sync", "--push", "--yes", "--progress", "--", "http://192.168.1.20:8737")


def sync_lines(report=REPORT):
    from caracole.get import PROGRESS_PREFIX

    return [PROGRESS_PREFIX + json.dumps({"stage": "compare", "state": "done", "detail": "1 difference"}),
            PROGRESS_PREFIX + json.dumps({"event": "unit", "id": "song/oasis/wonderwall", "outcome": "taken",
                                          "why": ""}),
            PROGRESS_PREFIX + json.dumps({"event": "report", "report": report}),
            "Took 1 change."]


def test_a_syncs_report_event_is_kept_on_its_job_and_never_in_its_history(tmp_path):
    from caracole.web.history import History

    path = tmp_path / "requests.jsonl"
    queue = JobQueue(FakeRunner(lines={"peer": sync_lines()}), history=History(path))
    job, _ = queue.submit("Sync with Studio", "sync:http://192.168.1.20:8737", [("Sync with Studio", SYNC)],
                          display="Sync with Studio", join=False)
    assert job.report is None  # nothing said yet
    queue.run_pending()
    done = queue.job(job.id)
    assert done.report == REPORT and done.units == [("song/oasis/wonderwall", "taken", "")]
    assert done.steps[0].output == ["Took 1 change."]  # data, never output
    assert "report" not in done.as_json() and "Ultimate Guitar" not in path.read_text(encoding="utf-8")
    again = JobQueue(FakeRunner(), history=History(path)).job(job.id)  # the next caracole serve
    assert again.report is None and again.units == done.units
    # a report that isn't an object is none
    queue = JobQueue(FakeRunner(lines={"peer": sync_lines(["not", "one"])}))
    job, _ = queue.submit("Sync with Studio", "sync:http://192.168.1.20:8737", [("Sync with Studio", SYNC)])
    queue.run_pending()
    assert queue.job(job.id).report is None


def test_a_syncs_view_carries_its_report_once_over_and_none_while_it_runs():
    from caracole.web.jobs_routes import peer_outcome, view

    from test_web_sync import peer_job

    running = peer_job("sync", "running", {"compare": ("done", "4 differences"), "take": ("running", "2 changes")})
    running.report = REPORT  # said, while its job is not over yet: nothing is shown of it
    assert view(running, [running], None, None)["outcome"] is None
    done = peer_job("sync", "done", {"compare": ("done", "4 differences"), "agree": ("done", "12 units the two agree "
                                                                                     "on")})
    before = view(done, [done], None, None)["outcome"]
    assert "report" not in before  # a job with none: its view as it was
    done.report = REPORT
    assert view(done, [done], None, None)["outcome"] == before | {"report": REPORT}
    assert peer_outcome(done)["report"] == REPORT


def test_an_imports_outcome_counts_what_the_two_agree_on_when_it_kept_an_answer_too():
    from caracole.web.jobs_routes import peer_outcome

    from test_web_sync import peer_job

    # commands/peer.py's import: "N units the books agree on", then ", M kept here" for each "keep mine" remembered
    kept = peer_job("import", "done", {"agree": ("done", "3 units the books agree on, 1 kept here")})
    assert peer_outcome(kept)["agreed"] == 3
    assert peer_outcome(peer_job("import", "done", {"agree": ("done", "1 unit the books agree on")}))["agreed"] == 1


def test_an_import_of_a_staged_file_is_followed_by_its_stages():
    from caracole.commands.peer import PEER_IMPORT_STAGES

    steps = [("Sync with a file from Desk", ("peer", "import", "--yes", "--progress", "--",
                                             "/state/peer/import-0123456789abcdef"))]
    job, _ = JobQueue(FakeRunner()).submit("Sync with a file from Desk", "import:0123456789abcdef", steps)
    assert [(s.name, s.label) for s in job.stages] == list(PEER_IMPORT_STAGES)
    assert [s.name for s in job.stages] == ["check", "take", "render", "agree", "index"]


# --- the lookups' lane: which requests go to it, and its room -------------------------------------------------------


def test_lookups_and_the_search_boxs_one_request_reads_are_the_lanes_and_the_rest_the_queues():
    assert all(lane_of(s) for s in (lookup_steps("Muse", "Uprising"), lookup_steps("Muse", "Uprising", tab=TAB),
                                    ug_link_steps(TAB), lacuerda_search_steps("calamaro flaca", auto=True),
                                    lacuerda_search_steps("calamaro flaca", auto=False),
                                    lacuerda_artist_steps("andres-calamaro", "Andrés Calamaro"),
                                    harptabs_artist_steps("/artist/9", "Muse"),
                                    lookup_steps("--no-songbooks", "Uprising")))  # a name, after "--"
    assert not any(lane_of(s) for s in (lookup_steps("Muse", "Uprising", songbooks=False),
                                        add_steps("Muse", "Uprising"),
                                        youtube_search_steps("muse uprising"), youtube_video_steps("dQw4w9WgXcQ"),
                                        youtube_sheet_steps("Muse - Uprising", VIDEO),
                                        version_steps("Muse", "Uprising", keep="1"),
                                        version_steps("Muse", "Uprising", choose=TAB),  # it runs get, from a sheet
                                        remove_steps("Muse - Uprising"), fetch_steps("Muse - Uprising"),
                                        [*add_steps("Muse", "Uprising"), *lookup_steps("Muse", "Uprising")],
                                        [("UG's directory", ("ug", "--directory"))],
                                        [("LaCuerda's listings", ("lacuerda", "--index"))], []))


def test_a_queue_of_no_lane_places_every_request_in_the_queue_as_today():
    queue = JobQueue(FakeRunner())
    job, _ = queue.submit("Fetch Muse - Uprising", "muse|uprising", lookup_steps("Muse", "Uprising"), fetching=True)
    assert queue.lanes == 0 and not job.lane
    assert queue.room() == LIMIT - 1 and queue.active_count() == 1


@pytest.mark.parametrize(("first", "how"), [("removal", "after"), ("sheet from youtube", "after"),
                                            ("songbook's lookup", "answered"), ("keep it", "joined")])
def test_a_lane_request_for_a_song_with_a_job_in_the_queue_goes_into_the_queue_behind_it(first, how):
    key = "muse|uprising"
    song_key, steps, options = {
        "removal": (REMOVING + key, remove_steps("Muse - Uprising"), {}),
        "sheet from youtube": (YOUTUBE_SHEET + key, youtube_sheet_steps("Muse - Uprising", VIDEO), {}),
        "songbook's lookup": (key, lookup_steps("Muse", "Uprising", songbooks=False), {"fetching": True}),
        "keep it": (key, version_steps("Muse", "Uprising", keep="1"), {}),
    }[first]
    queue = JobQueue(FakeRunner(), lane=LANE)
    songs, _ = queue.submit(first, song_key, steps, **options)
    assert not songs.lane
    get, new = queue.submit("Fetch Muse - Uprising", key, lookup_steps("Muse", "Uprising"), fetching=True)
    assert not get.lane  # in the queue by today's rules: answered, joined or after it
    if how == "after":
        assert new and get.id > songs.id
    else:
        assert not new and get.id == songs.id
    if how == "joined":
        assert [s.args[0] for s in get.steps] == ["versions", "get"]
    assert queue.submit("Fetch Oasis - Wonderwall", "oasis|wonderwall", lookup_steps("Oasis", "Wonderwall"),
                        fetching=True)[0].lane  # a song with nothing queued: the lane's


def test_a_songs_job_in_the_queue_keeps_its_lookups_there_while_it_runs_and_none_once_it_is_over():
    queue = JobQueue(FakeRunner(), lane=LANE)
    removal, _ = queue.submit("Remove Muse - Uprising", REMOVING + "muse|uprising", remove_steps("Muse - Uprising"))
    with queue._lock:
        queue._jobs[0].state = "running"
    get, new = queue.submit("Fetch Muse - Uprising", "muse|uprising", lookup_steps("Muse", "Uprising"), fetching=True)
    assert new and not get.lane and get.id > removal.id
    with queue._lock:
        for job in queue._jobs:
            job.state = "done"
    again, new = queue.submit("Fetch Muse - Uprising", "muse|uprising", lookup_steps("Muse", "Uprising"),
                              fetching=True)
    assert new and again.lane


def test_lane_requests_join_each_other_and_a_queue_request_never_joins_a_lane_job_that_waits():
    queue = JobQueue(FakeRunner(), lane=LANE)
    first, new = queue.submit("Fetch Muse - Uprising", "muse|uprising", lookup_steps("Muse", "Uprising"),
                              fetching=True)
    again, joined = queue.submit("Fetch Muse - Uprising", "muse|uprising", lookup_steps("Muse", "Uprising"),
                                 fetching=True)
    assert new and not joined and again.id == first.id and first.lane
    keep, made = queue.submit("Keep", "muse|uprising", version_steps("Muse", "Uprising", keep="1"))
    assert made and not keep.lane  # its own job, in the queue
    assert [s.args[0] for s in queue.job(first.id).steps] == ["get"]  # the lane job as it was
    add, made = queue.submit("Add", "muse|uprising", add_steps("Muse", "Uprising"))
    assert not made and add.id == first.id  # a lane job that does as much is its answer


def test_the_lane_has_room_of_its_own():
    queue = JobQueue(FakeRunner(), lane=LANE)
    adds = [queue.submit(f"Add A - {n}", f"a|{n}", add_steps("A", str(n)))[0] for n in range(LIMIT)]
    with pytest.raises(QueueFull):
        queue.submit("Add B - 0", "b|0", add_steps("B", "0"))
    assert queue.room() == 0
    lookups = [queue.submit(f"Fetch C - {n}", f"c|{n}", lookup_steps("C", str(n)), fetching=True)[0]
               for n in range(LANE + LANE_WAITING)]
    assert all(job.lane for job in lookups)
    with pytest.raises(QueueFull):
        queue.submit("Fetch D - 0", "d|0", lookup_steps("D", "0"), fetching=True)
    assert queue.active_count() == LIMIT + LANE + LANE_WAITING
    queue.cancel(adds[0].id)  # room in the queue: an add fits, a lookup still doesn't
    assert queue.room() == 1
    with pytest.raises(QueueFull):
        queue.submit("Fetch D - 0", "d|0", lookup_steps("D", "0"), fetching=True)
    assert not queue.submit("Add B - 0", "b|0", add_steps("B", "0"))[0].lane
    small = JobQueue(FakeRunner(), lane=1, lane_waiting=0)
    assert small.submit("Fetch C - 0", "c|0", lookup_steps("C", "0"), fetching=True)[0].lane
    with pytest.raises(QueueFull):
        small.submit("Fetch C - 1", "c|1", lookup_steps("C", "1"), fetching=True)


def test_requests_queued_together_each_take_their_own_lanes_room():
    together = [
        {"title": "Fetch B - 2", "song_key": "b|2", "steps": lookup_steps("B", "2"), "fetching": True},
        {"title": "Put B - 2 in a songbook", "song_key": "songbook|b|2", "steps": [("Adding", ("songbook", "add"))]}]
    full = JobQueue(FakeRunner(), lane=LANE)
    for n in range(LIMIT):
        full.submit(f"Add A - {n}", f"a|{n}", add_steps("A", str(n)))
    with pytest.raises(QueueFull):
        full.submit_all(together)
    assert full.active_count() == LIMIT and not any(job.lane for job in full.snapshot())  # neither queued
    queue = JobQueue(FakeRunner(), lane=LANE)
    (lookup, made), (change, made_too) = queue.submit_all(together)
    assert made and made_too and lookup.lane and not change.lane
    assert queue.job(lookup.id).together == queue.job(change.id).together == (lookup.id, change.id)
    for n in range(LANE + LANE_WAITING - 1):  # the lane full: the queue's room is no help to the lookup
        queue.submit(f"Fetch C - {n}", f"c|{n}", lookup_steps("C", str(n)), fetching=True)
    with pytest.raises(QueueFull):
        queue.submit_all([{**together[1], "song_key": "songbook|e|5"},
                          {**together[0], "song_key": "e|5", "steps": lookup_steps("E", "5")}])
    assert queue.active_count() == 2 + LANE + LANE_WAITING - 1  # the songbook's change taken back out


def test_a_request_counts_ahead_what_it_waits_for():
    def job(n: int, state: str, lane: bool = False) -> Job:
        return Job(n, f"Job {n}", f"song|{n}", [], state=state, lane=lane)

    jobs = [job(1, "running"), job(2, "running", True), job(3, "queued", True), job(4, "queued"),
            job(5, "queued", True), job(6, "done", True)]
    assert [ahead(jobs, jobs[i]) for i in (2, 4, 3)] == [1, 2, 4]
    assert ahead(jobs[::-1], jobs[3]) == 4  # in any order: a snapshot's, newest first
    # with no lane job, every active job before it, as today
    today = [job(1, "done"), job(2, "running"), job(3, "queued"), job(4, "queued")]
    assert [ahead(today, j) for j in today[1:]] == [0, 1, 2]


def test_a_jobs_lane_is_kept_in_memory_alone(tmp_path):
    from caracole.web.history import History

    path = tmp_path / "requests.jsonl"
    queue = JobQueue(FakeRunner(), history=History(path), lane=LANE)
    job, _ = queue.submit("Fetch Muse - Uprising", "muse|uprising", lookup_steps("Muse", "Uprising"), fetching=True)
    assert job.lane and "lane" not in job.as_json()
    assert all("lane" not in json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    again = JobQueue(FakeRunner(), history=History(path), lane=LANE).job(job.id)  # the next caracole serve
    assert again.state == "interrupted" and not again.lane


# --- the lane's workers -------------------------------------------------------------------------------------------


class Gated:
    """A runner whose commands each wait for their gate, their last argument (a lookup's title, an add's), until it
    is opened for them (``open``: once a command), and return -15 once terminated, as a command the server ends does;
    ``calls``, the commands in the order they started, and ``running``, those that run now."""

    def __init__(self):
        self._said = threading.Condition()
        self._opened = collections.Counter()
        self._ended = False
        self.calls = []
        self.running = []

    def __call__(self, args, emit):
        args, gate = list(args), args[-1]
        with self._said:
            self.calls.append(args)
            self.running.append(args)
            self._said.notify_all()
            opened = self._said.wait_for(lambda: self._opened[gate] > 0 or self._ended, timeout=30)
            self.running.remove(args)
            self._said.notify_all()
            if self._ended:
                return -15
            if not opened:
                return 1
            self._opened[gate] -= 1
            return 0

    def open(self, gate):
        with self._said:
            self._opened[gate] += 1
            self._said.notify_all()

    def terminate(self):
        with self._said:
            self._ended = True
            self._said.notify_all()

    def until(self, check, timeout=10):
        """Wait for ``check`` of the gates of the commands that run now, in the order they started."""
        with self._said:
            assert self._said.wait_for(lambda: check([args[-1] for args in self.running]), timeout), self.running


def until_states(queue, check, timeout=10):
    """Wait for ``check`` of every job's state (id -> state): the queue says so as each job ends."""
    with queue._wake:
        assert queue._wake.wait_for(lambda: check({job.id: job.state for job in queue._jobs}), timeout), [
            (job.id, job.state) for job in queue._jobs]


def lookup(queue, artist, title, **options):
    return queue.submit(f"Fetch {artist} - {title}", f"{artist.lower()}|{title.lower()}",
                        lookup_steps(artist, title, **options), fetching=True)[0]


def test_a_lookup_asked_while_a_long_request_runs_starts_at_once_and_a_request_after_it_waits_for_it():
    runner = Gated()
    queue = JobQueue(runner, lane=LANE)
    queue.start()
    try:
        long, _ = queue.submit("Add A - Long", "a|long", add_steps("A", "Long"))
        runner.until(lambda gates: gates == ["Long"])
        now = lookup(queue, "B", "Now")
        assert now.lane
        runner.until(lambda gates: gates == ["Long", "Now"])  # at once, beside it
        after, _ = queue.submit("Add C - After", "c|after", add_steps("C", "After"))
        assert not after.lane
        runner.open("Long")
        until_states(queue, lambda states: states[long.id] == "done")
        assert queue.job(after.id).state == "queued"  # the lane is busy: it waits for the lookup
        runner.open("Now")
        runner.until(lambda gates: gates == ["After"])
        assert queue.job(now.id).state == "done"
        runner.open("After")
        until_states(queue, lambda states: states[after.id] == "done")
    finally:
        queue.stop()
    assert [args[-1] for args in runner.calls] == ["Long", "Now", "After"]


def test_a_fourth_lookup_waits_for_a_slot_and_a_songs_second_job_for_its_first():
    runner = Gated()
    queue = JobQueue(runner, lane=LANE)
    queue.start()
    try:
        first, second, third, fourth = (lookup(queue, "A", n) for n in "1234")
        runner.until(lambda gates: sorted(gates) == ["1", "2", "3"])  # in any order: each its worker
        assert queue.job(fourth.id).state == "queued"  # LANE slots: it waits for one
        runner.open("1")
        runner.until(lambda gates: sorted(gates) == ["2", "3", "4"])
        runner.open("2")
        runner.open("3")
        until_states(queue, lambda states: states[second.id] == states[third.id] == "done")
        a = lookup(queue, "Oasis", "Wonderwall", tab=TAB_A)
        runner.until(lambda gates: sorted(gates) == ["4", "Wonderwall"])
        b = lookup(queue, "Oasis", "Wonderwall", tab=TAB_B)
        assert b.id != a.id and b.lane  # a job of its own, in the lane
        e = lookup(queue, "E", "Five")
        runner.until(lambda gates: sorted(gates) == ["4", "Five", "Wonderwall"])  # E goes past it
        assert queue.job(b.id).state == "queued"  # the song's first runs
        runner.open("Wonderwall")
        until_states(queue, lambda states: states[a.id] == "done")
        runner.until(lambda gates: sorted(gates) == ["4", "Five", "Wonderwall"])  # the song's second runs now
        assert queue.job(b.id).state == "running"
        for gate in ("4", "Five", "Wonderwall"):
            runner.open(gate)
        until_states(queue, lambda states: all(states[job.id] == "done" for job in (first, fourth, b, e)))
    finally:
        queue.stop()
    tabs = [arg for args in runner.calls for arg in args if arg.startswith("--tab=")]
    assert tabs == [f"--tab={TAB_A}", f"--tab={TAB_B}"]


def test_a_songs_own_job_keeps_its_order():
    runner = Gated()
    queue = JobQueue(runner, lane=LANE)
    queue.start()
    try:
        removal, _ = queue.submit("Remove Muse - Uprising", REMOVING + "muse|uprising", remove_steps("Muse - Uprising"))
        runner.until(lambda gates: gates == ["Muse - Uprising"])
        get, new = queue.submit("Fetch Muse - Uprising", "muse|uprising", lookup_steps("Muse", "Uprising"),
                                fetching=True)
        assert new and not get.lane  # a job in the queue, never the lane
        assert queue.job(get.id).state == "queued"
        runner.open("Muse - Uprising")
        runner.until(lambda gates: gates == ["Uprising"])  # once the removal is done, after it
        assert queue.job(removal.id).state == "done"
        runner.open("Uprising")
        until_states(queue, lambda states: states[get.id] == "done")
    finally:
        queue.stop()
    assert [args[0] for args in runner.calls] == ["remove", "get"]
    # that its wanted.txt line then brings the song back as new is test_songs.py's
    # test_a_wanted_line_brings_a_removed_song_back_as_new


def test_a_removal_asked_while_its_songs_lookup_runs_in_the_lane_starts_once_the_lookup_is_over():
    runner = FakeRunner()
    queue = JobQueue(runner, lane=LANE)
    get = lookup(queue, "Muse", "Uprising")
    running = queue._next(True)
    assert get.lane and running.id == get.id  # it runs, in the lane
    removal, new = queue.submit("Remove Muse - Uprising", REMOVING + "muse|uprising", remove_steps("Muse - Uprising"))
    assert new and not removal.lane
    assert queue._next(False) is None and queue._next(True) is None  # the queue's worker waits for the lane
    queue._run(running)
    assert queue._next(False).id == removal.id  # the lookup over: it starts
    assert [args[0] for args in runner.calls] == ["get"]


# A song's own changes, under keys of their own: Make this my version's (export_routes.py) and a harmonica tab's
# reading's (harmonica_routes.py), the song's identity key after their prefix
CHANGES = {
    "my version": (f"{EXPORTING}muse|uprising:key=G{MINE}",
                   [("Making it your version", ("render", "--song=Muse - Uprising", "--version=key=G", "--mine"))]),
    "a harmonica reading": (f"{READING}muse|uprising:harmonica-1.txt:clear{MINE}",
                            [("Going back to our guess", ("harmonica", "--tab=harmonica-1.txt", "--clear", "--",
                                                          "Muse", "Uprising"))]),
}


@pytest.mark.parametrize("how", ["waits", "runs"])
@pytest.mark.parametrize("change", CHANGES)
def test_a_lookup_asked_while_the_songs_own_change_waits_or_runs_goes_into_the_queue_behind_it(change, how):
    song_key, steps = CHANGES[change]
    queue = JobQueue(FakeRunner(), lane=LANE)
    mine, _ = queue.submit(change, song_key, steps, display="Muse - Uprising", song_id=1)
    assert not mine.lane
    if how == "runs":
        assert queue._next(False).id == mine.id
    get = lookup(queue, "Muse", "Uprising")
    assert not get.lane and get.id > mine.id  # a job of its own in the queue, after the song's change
    other = lookup(queue, "Oasis", "Wonderwall")
    assert other.lane and queue._next(True).id == other.id  # another song's: the lane's, the Muse lookup not


@pytest.mark.parametrize("change", CHANGES)
def test_a_lane_job_never_starts_beside_its_songs_own_change(change):
    song_key, steps = CHANGES[change]
    queue = JobQueue(FakeRunner(), lane=LANE)
    get = lookup(queue, "Muse", "Uprising")
    mine, _ = queue.submit(change, song_key, steps, display="Muse - Uprising", song_id=1)
    with queue._lock:  # running beside it, which the queue's worker never lets it: the lane worker's own check
        next(job for job in queue._jobs if job.id == mine.id).state = "running"
    assert queue._next(True) is None
    with queue._lock:
        next(job for job in queue._jobs if job.id == mine.id).state = "done"
    assert queue._next(True).id == get.id


def test_cancel_takes_out_a_lookup_waiting_for_a_slot_never_one_that_runs():
    runner = Gated()
    queue = JobQueue(runner, lane=LANE)
    queue.start()
    try:
        jobs = [lookup(queue, "A", n) for n in "1234"]
        runner.until(lambda gates: sorted(gates) == ["1", "2", "3"])  # in any order: each its worker
        cancelled = queue.cancel(jobs[3].id)
        assert cancelled is not None and cancelled.state == "cancelled"
        with pytest.raises(JobStarted):
            queue.cancel(jobs[0].id)
        for gate in "123":
            runner.open(gate)
        until_states(queue, lambda states: all(states[job.id] == "done" for job in jobs[:3]))
    finally:
        queue.stop()
    assert sorted(args[-1] for args in runner.calls) == ["1", "2", "3"]  # never run
    assert queue.job(jobs[3].id).state == "cancelled"


def test_a_stop_interrupts_every_running_request_and_a_restart_reads_them_back_so(tmp_path):
    from caracole.web.history import History

    path = tmp_path / "requests.jsonl"
    runner = Gated()
    queue = JobQueue(runner, history=History(path), lane=LANE)
    queue.start()
    try:
        add, _ = queue.submit("Add A - Long", "a|long", add_steps("A", "Long"))
        runner.until(lambda gates: gates == ["Long"])  # the queue's, before the lookups come
        jobs = [add, lookup(queue, "B", "1"), lookup(queue, "B", "2")]
        runner.until(lambda gates: sorted(gates) == ["1", "2", "Long"])
    finally:
        queue.stop()
    assert not any(thread.is_alive() for thread in queue._threads)  # every worker joined
    assert [queue.job(job.id).state for job in jobs] == [INTERRUPTED] * 3
    assert [queue.job(job.id).steps[0].state for job in jobs] == [INTERRUPTED] * 3
    again = JobQueue(FakeRunner(), history=History(path), lane=LANE)  # the next caracole serve
    assert [again.job(job.id).state for job in jobs] == [INTERRUPTED] * 3


def test_run_pending_runs_the_lane_before_the_queue():
    runner = FakeRunner()
    queue = JobQueue(runner, lane=LANE)
    queue.submit("Add A - B", "a|b", add_steps("A", "B"))
    lookup(queue, "C", "D")
    queue.run_pending()
    assert [args[0] for args in runner.calls] == ["get", "add"]
    assert [job.state for job in queue.snapshot()] == ["done", "done"]


def test_a_command_asked_once_the_runner_is_terminated_starts_no_process(monkeypatch):
    started = []

    def popen(*args, **kwargs):
        started.append(args)
        raise AssertionError("a process started after terminate")

    monkeypatch.setattr(subprocess, "Popen", popen)
    runner = CaracoleRunner(None)
    runner.terminate()
    assert runner(["add", "--", "A", "B"], lambda line: None) == -15
    # The stop race: a worker past _run's check as the server stops asks the runner after terminate
    real = CaracoleRunner(None)

    def stopping(args, emit):
        queue._stopping = True  # as stop() sets it, then terminates the runner
        real.terminate()
        return real(args, emit)

    queue = JobQueue(stopping)
    job, _ = queue.submit("Add A - B", "a|b", add_steps("A", "B"))
    queue._run(queue._next())
    assert started == []
    stopped = queue.job(job.id)
    assert stopped.state == INTERRUPTED and [(s.state, s.code) for s in stopped.steps] == [(INTERRUPTED, -15)]


@pytest.mark.slow
def test_the_runner_keeps_a_process_a_command_and_ends_them_all(tmp_path):
    script = tmp_path / "caracole"
    script.write_text(f'#!/bin/sh\n: > "{tmp_path}/started.$$"\nexec sleep 30\n', encoding="utf-8")
    script.chmod(0o755)
    runner = CaracoleRunner(None, python=str(script))
    codes = {}

    def run(n):
        codes[n] = runner([f"--song={n}"], lambda line: None)

    threads = [threading.Thread(target=run, args=(n,)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 10
    while len(list(tmp_path.glob("started.*"))) < 2:  # both running: each wrote its marker
        assert time.monotonic() < deadline
        threading.Event().wait(0.01)
    runner.terminate()
    for thread in threads:
        thread.join(5)
    assert codes == {1: -15, 2: -15}
