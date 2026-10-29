"""The library page's Requests tab, as data: every request the queue remembers, as library_assets/requests.js draws
it (``GET /requests.json``, jobs_routes.py).

Under **Now**, the request that runs, with how long ago it started, its line and its steps (outcome.py's ``steps``,
the chips the library page draws under a song's line), and those queued under it in order ("Queued, next",
"Queued, 2nd"), each with Cancel (``POST /jobs/cancel``); then the finished ones, newest first under **Today** and
**Earlier** (by when each ended, in the server's local time zone), each with its outcome (outcome.py's
``Outcome``: a word in its tone, a reason, its next step and the one beside it) and when it ended. A next step is
a link (``href``) or a form the tab posts with the form token (``post`` and its ``fields``); the ones that are the
request's way on are ``primary`` (``PRIMARY``).

Every request keeps what it ran (``output``): its title and when it was asked for (in the server's time zone,
named), a lookup's stages, each with its state and why, and each command it ran with its state; what each
command printed (``lines``) only for the requests the tab has opened (``opened``), so the answer the tab asks for
every second and a half while one runs stays small. A request that stopped only because its song needs a pick
first says so in its output ("Waits for a pick") rather than failed; its outcome's Pick the match opens the
picker's own page (``/review?song=ID``), and a song not found in the offline index gets what ``caracole search``
finds for it as a next step when its outcome has none that leads there.

The standard library, and outcome.py's words: no route, no database.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from caracole.stamps import shown, stamp

if TYPE_CHECKING:
    from caracole.web.jobs import Job, Stage, Step
    from caracole.web.outcome import Action, Outcome
    from caracole.web.pages import Pick
    from caracole.web.status import Line, SongFacts

STATE_TEXT = {"queued": "Queued", "running": "Running", "done": "Done", "failed": "Failed",
              "waiting": "Waiting", "skipped": "Skipped", "cancelled": "Cancelled"}
# The next steps that are the request's way on; the others (Try again, Request by name…) are plain buttons.
PRIMARY = frozenset({"Open", "Pick the match", "Get it from there", "Open songbook", "See what caracole search finds"})
SEARCH = "See what caracole search finds"
# What `caracole fetch --song` says of a song that needs review first (commands/fetch.py).
_NEEDS_REVIEW = "needs review first"
PICK_STAGE = ("Not fetched yet: its Ultimate Guitar sheet waits for the match. Pick the match, with Fetch it now "
              "ticked, and it is fetched then.")
PICK_STEP = ("Not fetched yet: caracole fetch waits for the match. Pick the match, with Fetch it now ticked, and it "
             "is fetched then.")


def feed(jobs: list[Job], lines: Mapping[int, Line], *, outcomes: Mapping[int, Outcome] | None = None,
         facts: Mapping[int, SongFacts | None] | None = None, picks: Mapping[str, Pick] | None = None,
         opened: Collection[int] = (), now: datetime | None = None) -> dict[str, Any]:
    """Every request remembered (``jobs``, newest first), as the tab draws it: ``active``, how many wait or run (the
    tab's count), and ``groups``, Now, Today and Earlier, each that has a request, with its ``requests``.

    ``lines`` are status.py's, by job id; ``outcomes`` outcome.py's for the finished ones (else read from their
    line); ``facts`` their songs' (where a running lookup's sheet came from); ``picks`` the songs of finished
    requests that wait for a pick now, by song key (review_routes.py's ``picks_waiting``); ``opened``, the requests
    whose output comes with what each command printed; ``now``, the answer's time (the clock's).
    """
    from caracole.web.outcome import outcome

    now = now or datetime.now(UTC)
    pending = _waiting_picks(jobs, picks or {})
    active = sorted((job for job in jobs if job.active), key=lambda job: (job.state != "running", job.id))
    queued = [job for job in active if job.state == "queued"]
    groups: dict[str, list[dict[str, Any]]] = {"Now": [], "Today": [], "Earlier": []}
    for job in active:
        shown_job = (_running(job, lines.get(job.id), (facts or {}).get(job.id), now) if job.state == "running"
                     else _queued(job, queued.index(job) + 1))
        groups["Now"].append(shown_job | {"output": _output(job, opened=job.id in opened)})
    today = now.astimezone().date()
    over = sorted((job for job in jobs if not job.active),
                  key=lambda job: (job.finished_at or job.queued_at, job.id), reverse=True)
    for job in over:
        said = (outcomes or {}).get(job.id)
        if said is None and job.id in lines:
            said = outcome(job, lines[job.id])
        ended = (job.finished_at or job.queued_at).astimezone()
        day = ended.date() != today
        pick = pending.get(job.id)
        picking = pick is not None and _waits_for_pick(job, pick)
        groups["Earlier" if day else "Today"].append(
            _finished(job, said, ended, pick, day=day) | {"output": _output(job, opened=job.id in opened,
                                                                            picking=picking)})
    return {"active": sum(job.active for job in jobs),
            "groups": [{"name": name, "requests": shown_jobs} for name, shown_jobs in groups.items() if shown_jobs]}


def _running(job: Job, line: Line | None, facts: SongFacts | None, now: datetime) -> dict[str, Any]:
    """The request that runs: its song, how long ago it started, its line, and its steps (outcome.steps), a running
    lookup's Sheet naming the site its song's sheet came from (``facts``)."""
    from caracole.web.outcome import steps

    shown_job = _head(job, "running", line.text if line is not None else STATE_TEXT["running"])
    if job.started_at is not None:
        shown_job["ago"] = f"started {_ago(job.started_at, now)}"
    shown_job["steps"] = [chip.as_json() for chip in steps(job, facts)]
    return shown_job


def _queued(job: Job, place: int) -> dict[str, Any]:
    """A request that waits: its place ("Queued, next", "Queued, 3rd") and Cancel, which takes it out of the queue."""
    shown_job = _head(job, "queued", f"Queued, {_ordinal(place)}")
    shown_job["actions"] = [{"label": "Cancel", "post": "/jobs/cancel", "fields": {"job": str(job.id)},
                             "aria": f"Cancel the request for {job.display or job.title}", "primary": False}]
    return shown_job


def _finished(job: Job, said: Outcome | None, ended: datetime, pick: Pick | None, *, day: bool) -> dict[str, Any]:
    """A finished request: its outcome in a word, the reason, its next steps and when it ended (with its day for one
    before today)."""
    if said is None:
        shown_job = _head(job, job.state, STATE_TEXT.get(job.state, job.state))
        actions: list[dict[str, Any]] = []
    else:
        shown_job = _head(job, said.tone, said.word)
        if said.reason:
            shown_job["reason"] = said.reason
        actions = [a for a in (_action(said.action), _action(said.also, primary=False)) if a is not None]
    if pick is not None and pick.search:  # a song the index didn't match: what caracole search finds, if not there
        href = f"/review?song={pick.song_id}"
        if not any(a.get("href") == href for a in actions):
            actions.append({"label": SEARCH, "href": href, "primary": False})
    if actions:
        shown_job["actions"] = actions
    shown_job["when"] = {"stamp": stamp(ended),
                         "text": f"{ended.day} {ended:%b}, {ended:%H:%M}" if day else f"{ended:%H:%M}"}
    return shown_job


def _head(job: Job, tone: str, text: str) -> dict[str, Any]:
    return {"id": job.id, "display": job.display or job.title, "state": job.state,
            "says": {"tone": tone, "text": text}}


def _action(a: Action | None, *, primary: bool = True) -> dict[str, Any] | None:
    """A next step as the tab draws it: a link, or a form it posts with the form token; None for none. ``primary``:
    drawn as the request's way on when it is one (``PRIMARY``); the one beside it is a plain button."""
    if a is None or (a.post is None and a.href is None):
        return None
    shown_action: dict[str, Any] = {"label": a.label, "primary": primary and a.label in PRIMARY}
    if a.post is not None:
        shown_action |= {"post": a.post, "fields": dict(a.fields)}
    else:
        shown_action["href"] = a.href
    return shown_action


def _output(job: Job, *, opened: bool, picking: bool = False) -> dict[str, Any]:
    """What the request ran: its title and when it was asked for, a lookup's stages, and each command with how it
    went; with ``opened``, what each printed (``lines``, those before them counted in their first). ``picking``: it
    stopped only because the song needs a pick first (``_waits_for_pick``), so its fetch waits for one rather than
    failed."""
    meta = f"{job.title} · requested {shown(job.queued_at, '', local=True)}"
    if job.note:
        meta += f" · {job.note}"
    if job.seconds_to_sheet is not None:
        meta += f" · sheet readable after {job.seconds_to_sheet:.1f} s"
    output: dict[str, Any] = {"meta": meta, "opened": opened,
                              "stages": [_stage(s, picking=picking and s.name == "sheet" and s.state == "skipped")
                                         for s in job.stages],
                              "steps": [_step(step, opened=opened, picking=picking and step.state == "failed")
                                        for step in job.steps]}
    return output


def _stage(stage: Stage, *, picking: bool = False) -> dict[str, Any]:
    """A lookup's stage: its label, how it went and why; with ``picking``, the sheet that waits for a pick."""
    shown_stage: dict[str, Any] = {"label": stage.label, "badge": _badge(stage.state, picking=picking)}
    if picking:
        shown_stage["note"] = PICK_STAGE
    if stage.detail:
        shown_stage["detail"] = stage.detail
    return shown_stage


def _step(step: Step, *, opened: bool, picking: bool = False) -> dict[str, Any]:
    """A command it ran: its label, how it went and, ``opened``, the last lines it printed; with ``picking``, the
    fetch that waits for a pick: a note before its error."""
    shown_step: dict[str, Any] = {"label": step.label, "badge": _badge(step.state, picking=picking)}
    if picking:
        shown_step["note"] = PICK_STEP
    if opened:
        shown_step["lines"] = ([f"… {step.dropped} earlier lines"] if step.dropped else []) + list(step.output)
    return shown_step


def _badge(state: str, *, picking: bool = False) -> dict[str, str]:
    if picking:
        return {"tone": "review", "text": "Waits for a pick"}
    return {"tone": state, "text": STATE_TEXT.get(state, state)}


def _ago(then: datetime, now: datetime) -> str:
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 60:
        return f"{seconds} s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600} h ago"


def _ordinal(n: int) -> str:
    """A queued request's place: "next", then "2nd", "3rd", "4th"…"""
    if n <= 1:
        return "next"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _waiting_picks(jobs: list[Job], picks: Mapping[str, Pick]) -> dict[int, Pick]:
    """The newest finished request of each song that waits for a pick now, and its song's pick."""
    pending: dict[int, Pick] = {}
    seen: set[str] = set()
    for job in jobs:  # newest first
        if job.song_key in seen:
            continue
        seen.add(job.song_key)
        pick = picks.get(job.song_key)
        if not job.active and pick is not None:
            pending[job.id] = pick
    return pending


def _waits_for_pick(job: Job, pick: Pick | None) -> bool:
    """Whether a finished request stopped only because its song needs a pick first: the one step that failed is its
    ``caracole fetch --song``, which refused the song as needing review, or, for a lookup (one ``caracole get``,
    Fetch it now's), its sheet stage was skipped; and the song has a picker (``pick``). Fetch it now is ticked by
    default, so a request whose match found only candidates ends this way."""
    if pick is None or pick.search:
        return False
    if job.stages:
        return job.state == "done" and any(s.name == "sheet" and s.state == "skipped" for s in job.stages)
    if job.state != "failed":
        return False
    failed = [step for step in job.steps if step.state == "failed"]
    return (len(failed) == 1 and failed[0].args[:1] == ("fetch",)
            and any(_NEEDS_REVIEW in line for line in failed[0].output))
