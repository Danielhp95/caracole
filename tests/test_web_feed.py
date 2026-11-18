"""What a queued request's line (/jobs.json, jobs_routes.view) and the Journal (/requests.json, web/feed.py) count once
lookups run in a lane beside the queue (web/jobs.py ``JobQueue(lane=…)``): a lookup waits for the lookups before it,
any other request for every one before it and every lookup, and each says its place among those of its own place."""

from datetime import UTC, datetime

from caracole.web import jobs_routes
from caracole.web.feed import feed
from caracole.web.jobs import LANE, Job, JobQueue, add_steps, lookup_steps


class Runner:
    """Runs nothing: the jobs here are only placed, started (``_next``) and shown."""

    def __call__(self, args, emit):
        return 0


def requests(fed: dict, group: str) -> list[dict]:
    """The requests of one of the feed's groups (Now, Today, Earlier), in order; [] for a group not there."""
    return next((g["requests"] for g in fed["groups"] if g["name"] == group), [])


def by_id(fed: dict) -> dict[int, dict]:
    return {r["id"]: r for g in fed["groups"] for r in g["requests"]}


def five(lane: int = LANE) -> dict[int, Job]:
    """Five requests, by id: 1 an add that runs, 2 a lookup that runs beside it, 3 a lookup waiting for a slot, 4 an
    add waiting in the queue, 5 a lookup after it; with ``lane`` 0, all five in the queue, 1 running. The queue's own
    snapshot (newest first, as the routes give it) is ``list(five().values())``."""
    queue = JobQueue(Runner(), lane=lane)

    def add(n: int) -> None:
        queue.submit(f"Add A - {n}", f"a|{n}", add_steps("A", str(n)), display=f"A - {n}")

    def lookup(n: int) -> None:
        queue.submit(f"Fetch B - {n}", f"b|{n}", lookup_steps("B", str(n)), fetching=True, display=f"B - {n}")

    add(1)
    assert queue._next(False).id == 1
    lookup(2)
    if lane:
        assert queue._next(True).id == 2
    lookup(3)
    add(4)
    lookup(5)
    return {job.id: job for job in queue.snapshot()}


def test_a_lookup_waiting_for_a_slot_counts_the_lane_ahead_and_a_queued_request_the_lane_too():
    jobs = five()
    assert [jobs[n].lane for n in range(1, 6)] == [False, True, True, False, True]
    assert [jobs[n].state for n in range(1, 6)] == ["running", "running", "queued", "queued", "queued"]
    queue = list(jobs.values())
    assert [jobs_routes.view(jobs[n], queue, None, None)["line"]["text"] for n in (3, 5, 4)] == [
        "Queued · 1 request ahead…", "Queued · 2 requests ahead…", "Queued · 4 requests ahead…"]


def test_queued_requests_say_their_place_in_their_lane_and_every_running_one_is_now():
    fed = feed(list(five().values()), {}, now=datetime.now(UTC))
    shown = by_id(fed)
    assert [shown[n]["says"]["text"] for n in (3, 5, 4)] == ["Queued · next", "Queued · 2nd", "Queued · next"]
    assert [r["id"] for r in requests(fed, "Now")][:2] == [1, 2]  # every running one, oldest first
    assert [shown[n]["says"]["text"] for n in (1, 2)] == ["Running", "Running"]
    assert fed["active"] == 5


def test_with_no_lane_every_request_counts_and_places_as_one_queue():
    jobs = five(lane=0)
    assert not any(job.lane for job in jobs.values())
    queue = list(jobs.values())
    assert [jobs_routes.view(jobs[n], queue, None, None)["line"]["text"] for n in (2, 3, 4, 5)] == [
        "Queued · 1 request ahead…", "Queued · 2 requests ahead…", "Queued · 3 requests ahead…",
        "Queued · 4 requests ahead…"]
    shown = by_id(feed(queue, {}, now=datetime.now(UTC)))
    assert [shown[n]["says"]["text"] for n in (2, 3, 4, 5)] == ["Queued · next", "Queued · 2nd", "Queued · 3rd",
                                                                "Queued · 4th"]
