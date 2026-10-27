"""caracole serve's requests: the requests page, /jobs.json for the pages' scripts, and the API's jobs.

    GET  /jobs            the requests, a line each, and what each command printed
                          (?job=N: its output open; ?refresh=0: no reloading)
    GET  /jobs.json       the requests, a line each, for the page's script (?jobs=N,M: only those
                          jobs, each with its song's card once it is over)
    GET  /api/jobs[/<id>] the requests as data: each step with its state (Job.as_json)
    POST /jobs/cancel     a request that hasn't started (``job``), taken out of the queue: never one that
                          runs, nor one that is over; an add's wanted.txt line stays
    POST /jobs/again      a request that is over (``job``), its steps queued again: Try again

The requests page (pages.py) shows the request that runs with its steps and those queued under it, each
with Cancel, then the finished ones newest first, each as outcome.py says it: its outcome, a reason, when
it finished and its next step (Open, Pick the match, Get it from there, Request by name, Try again…), read
from its line and its song (``song_of``: for a song a fetch left without a sheet, what the local indexes
have elsewhere, ``outcome.elsewhere``).

Each job is shown as the page's script reads it (``views``): its song (its id, and its identity key, which
an id songs.id gives again once the newest song is removed never shares), its line (status.py, as a song's
line says it: ``song_line``), a lookup's steps and how many are over (outcome.py's ``progress``) and, once
it is over and the page asks (``?jobs=``), its song's card as the library page draws it now, and the
songbooks as its Songbooks tab has them now, which the page draws again: a songbook's change, a lookup
(``caracole get`` makes the songbooks its song is in again) and a removal each change them. A job says
what it is about (``kind``: a song's, a removal's, a songbook's), so the page shows each where it
belongs. Every route that queues a job answers the page's script with its view (``WebApp.queued``).
app.py checks that /jobs.json is asked for by the page's own script, as a write would be.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from caracole.web import pages
from caracole.web.app import (
    Response,
    Route,
    WebApp,
    address,
    html_response,
    json_response,
    overrides_or_none,
    query,
    redirect,
)
from caracole.web.jobs import EXPORTING, LACUERDA_READS, LACUERDA_SEARCH, LOOKUP, REMOVING, Job, JobStarted
from caracole.web.pages import Refused
from caracole.web.review_routes import picks_waiting, review_first
from caracole.web.status import SongFacts, details_href, job_line, song_line

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.songs import Song

MAX_ASKED = 50  # jobs one /jobs.json answer is asked about


ROUTES = (
    Route("GET", "/jobs", lambda app, asked: jobs_page(app, query(asked))),
    Route("GET", "/jobs.json", lambda app, asked: jobs_json(app, query(asked)), script_only=True),
    Route("GET", "/api/jobs", lambda app, asked: api_jobs(app)),
    Route("GET", "/api/jobs/", lambda app, asked: api_job(app, address(asked)[len("/api/jobs/"):]), under=True),
    Route("POST", "/jobs/cancel", lambda app, asked, form: cancel(app, form), page="the requests page"),
    Route("POST", "/jobs/again", lambda app, asked, form: again(app, form), page="the requests page"),
)


def jobs_page(app: WebApp, asked: dict[str, list[str]]) -> Response:
    """Every request: the one that runs and those queued, then the finished ones, each with its outcome and
    its next step (outcome.py); its output open only when asked for (``?job=N``)."""
    from caracole.web.outcome import outcome

    try:
        opened = int(asked.get("job", [""])[0])
    except ValueError:
        opened = None
    jobs = app.queue.snapshot()
    songs: dict[int, tuple[int | None, SongFacts | None]] = {}
    books: dict[int, str | None] = {}
    try:
        overrides = overrides_or_none(app.cfg)
        with closing(app.connect()) as conn:
            forget_ended(app, jobs)
            songs = {job.id: song_of(app, conn, overrides, job) for job in jobs}
            books = {job.id: _songbook_page(conn, job) for job in jobs}
    except (sqlite3.Error, OSError):  # the lines say only how the jobs went, then
        pass
    facts = {job_id: found[1] for job_id, found in songs.items()}
    lines = {job.id: job_line(job, facts.get(job.id), ahead=_ahead(jobs, job), songbook_page=books.get(job.id))
             for job in jobs}
    outcomes = {job.id: outcome(job, lines[job.id], facts.get(job.id), song_id=songs.get(job.id, (None,))[0])
                for job in jobs if not job.active}
    still = asked.get("refresh") == ["0"]
    return html_response(200, pages.jobs_page(jobs, lines, outcomes=outcomes, facts=facts, opened=opened,
                                              refresh=not still, picks=picks_waiting(app, jobs), csrf=app.csrf))


def cancel(app: WebApp, form: dict[str, str]) -> Response:
    """A request that hasn't started, taken out of the queue (``JobQueue.cancel``); back to the requests page.
    One that runs is never stopped halfway, and one that is over stays in the history."""
    job_id = _form_job(form)
    try:
        job = app.queue.cancel(job_id)
    except JobStarted as e:
        if e.state == "running":
            raise Refused(409, "Running already", "That request has started, and caracole never stops a command "
                                                  "halfway: it runs to its end.") from None
        raise Refused(409, "Over already", "That request is over: there's nothing left to cancel.") from None
    if job is None:
        raise Refused(404, "No such request", "That request isn't queued any more: reload the requests page.")
    response = redirect("/jobs")
    response.data = {"cancelled": job.id}
    return response


def again(app: WebApp, form: dict[str, str]) -> Response:
    """A request that is over, its steps queued again as a new request (Try again); back to the requests page.
    It is queued as any request is (``JobQueue.submit``): a song's request waiting or running is the answer. A
    LaCuerda artist's read, or a query of its search, is one of ``app._reads``, as the search's Read is, so the
    answers the searches kept go once it is over; a search the page sent by itself is asked by hand now, past the
    share of those (no ``--auto``). A lookup Get the missing songs queued (``--no-songbooks``, its songbook made
    after them all) runs alone now, with nothing after it: it makes the songbooks its song is in again itself, as
    a song's Fetch now does. A failed removal's Try again asks what goes first (outcome.py: ``POST
    /remove``)."""
    job_id = _form_job(form)
    job = app.queue.job(job_id)
    if job is None:
        raise Refused(404, "No such request", "caracole serve no longer remembers that request: ask for it again "
                                              "from the library.")
    if job.active:
        raise Refused(409, "Not over yet", "That request is still queued or running.")
    steps = [(step.label, step.args) for step in job.steps]
    if job.song_key.startswith(LACUERDA_SEARCH):  # you ask for it now: by hand
        steps = [(label, tuple(arg for arg in args if arg != "--auto")) for label, args in steps]
    steps = [(label, _with_songbooks(args)) for label, args in steps]
    picked = any(step.args[:1] == ("review",) for step in job.steps)  # a pick comes after the song's own request
    queued, _ = app.submit(job.title, job.song_key, steps, fetching=job.fetching, note=job.note,
                           display=job.display, join=not picked, song_id=job.song_id)
    if job.song_key.startswith(LACUERDA_READS):  # once read, the searches' answers kept go, as a first read's
        with app._searching:
            app._reads.add(queued.id)
    return app.queued(queued, "/jobs")


def _with_songbooks(args: tuple[str, ...]) -> tuple[str, ...]:
    """A lookup's command with its songbooks stage (no ``--no-songbooks`` before ``--``): the render that followed
    it is no longer after it."""
    if args[:1] != (LOOKUP,) or "--" not in args:
        return args
    end = args.index("--")
    return tuple(arg for arg in args[:end] if arg != "--no-songbooks") + args[end:]


def _form_job(form: dict[str, str]) -> int:
    """The request a form names (``job``); Refused (400) when it names none."""
    text = form.get("job", "").strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 12:
        raise Refused(400, "Not a request", "Which request? The form names none.")
    return int(text)


def jobs_json(app: WebApp, asked: dict[str, list[str]]) -> Response:
    """The requests for the page's script."""
    ids = _job_ids(asked.get("jobs"))
    overrides = app.overrides(" Fix it, then reload this page.")
    jobs = app.queue.snapshot()
    only = None if ids is None else [job for job in jobs if job.id in ids]
    with app.db() as conn:
        forget_ended(app, jobs)
        shown = views(app, conn, overrides, jobs, only=only, cards=ids or frozenset())
    return json_response(200, {"active": sum(j.active for j in jobs), "jobs": shown})


def api_jobs(app: WebApp) -> Response:
    return json_response(200, {"jobs": [job.as_json() for job in app.queue.snapshot()]})


def api_job(app: WebApp, number: str) -> Response:
    job = app.queue.job(int(number)) if number.isascii() and number.isdigit() else None
    if job is None:
        return json_response(404, {"error": "no such request"})
    if job.song_key.startswith(LACUERDA_READS):  # no song's: its line says what LaCuerda answered
        return json_response(200, job.as_json() | {"line": job_line(job, None).as_json()})
    return json_response(200, job.as_json())


def views(app: WebApp, conn: sqlite3.Connection, overrides: Overrides | None, jobs: list[Job], *,
          only: list[Job] | None = None, cards: frozenset[int] = frozenset()) -> list[dict[str, Any]]:
    """Each job (of ``only``, else every one) as the page's script reads it: its song, its line and,
    for a job in ``cards`` that is over, its song's card as the page draws it now, and the songbooks
    as the Songbooks tab has them (``songbooks``): a songbook's change, a song's lookup, which makes
    the songbooks it is in again, and a removal all change them. A LaCuerda artist's read changes none.

    ``jobs`` is the whole queue, newest first, for the jobs ahead of a queued one;
    ``overrides`` None (overrides.toml unreadable) leaves the cards out.
    """
    from caracole.library_page import song_cards
    from caracole.songs import get_song

    shown = []
    section: dict[str, Any] | None = None  # read once, for every job that asks
    for job in jobs if only is None else only:
        song_id, facts = song_of(app, conn, overrides, job)
        seen = view(job, jobs, song_id, facts, songbook_page=_songbook_page(conn, job))
        if (job.id in cards and not job.active and overrides is not None
                and not job.song_key.startswith(LACUERDA_READS)):
            section = section or _songbooks(app, conn, overrides)
            seen["songbooks"] = section
        if job.id in cards and not job.active and song_id is not None and overrides is not None:
            try:
                song = get_song(conn, song_id)  # as it is now
            except KeyError:
                shown.append(seen)
                continue
            card = song_cards(conn, app.cfg, overrides, datetime.now(UTC).replace(microsecond=0), [song])[0]
            card["fetchable"] = not review_first(song, overrides)
            seen["card"] = card
        shown.append(seen)
    return shown


def view(job: Job, jobs: list[Job], song_id: int | None, facts: SongFacts | None, *,
         songbook_page: str | None = None) -> dict[str, Any]:
    """A job as /jobs.json gives it; ``jobs`` is the whole queue. ``kind`` says what it is about: a song
    ("song"), a song's removal ("remove"), an export of a song's sheet ("export", which is no song's line: its
    ``songId`` is None), or a songbook ("songbook", which ``songbook`` names), whose ``songbook_page`` its line
    links once it is done. A song's job names it by its id (``songId``) and its identity key (``identity``, the
    job's key: ``song_of`` finds the song by it): songs.id has no AUTOINCREMENT, so once the newest song is
    removed the next one added gets its id again, and a page that knew the one by that id tells the other by its
    identity.

    Its ``line`` is as a song's line says it (``song_line``): Ready alone, and its sheet as ``sheet``, which the
    list of requests opens by the song's name. A lookup's ``steps`` and, while it runs, its ``count`` are
    outcome.py's ``progress``: none once it ends Ready."""
    from caracole.web.outcome import progress
    from caracole.web.songbooks import songbook_of

    songbook = songbook_of(job.song_key)
    kind = ("remove" if job.song_key.startswith(REMOVING) else "export" if job.song_key.startswith(EXPORTING)
            else "songbook" if songbook is not None else "song")
    line = job_line(job, facts, ahead=_ahead(jobs, job), songbook_page=songbook_page)
    shown = song_line(line) if kind == "song" else line
    seen = {"id": job.id, "display": job.display or job.title, "songId": song_id, "kind": kind,
            "state": job.state, "fetching": job.fetching, "line": shown.as_json(), "details": details_href(job.id)}
    if shown is not line and line.link is not None:
        seen["sheet"] = line.link[1]
    if kind == "song":
        seen.update(progress(job, line, facts))
    if song_id is not None and songbook is None:
        seen["identity"] = job.song_key.removeprefix(REMOVING)
    if songbook is not None:
        seen["songbook"] = songbook
    return seen


def _songbooks(app: WebApp, conn: sqlite3.Connection, overrides: Overrides) -> dict[str, Any]:
    """The songbooks as the library page's Songbooks tab has them now (songbook_section.py), which its Select
    bar's menu follows too."""
    from caracole.songbook_section import songbooks_data

    return songbooks_data(conn, app.cfg, overrides)


def song_of(app: WebApp, conn: sqlite3.Connection, overrides: Overrides | None,
            job: Job) -> tuple[int | None, SongFacts | None]:
    """The id of the job's song, and what its line needs to know of it; None while the library has
    no such song.

    A fetch that is over and left no sheet is "Not found" only if it looked the
    song up during the job (``ug.fetch.checked_since``): a cooldown, a block, a
    spent budget or an error looks nothing up, and the song isn't missing; for the
    requests page, it says whether that fetch asked Ultimate Guitar at all
    (``asked_ug``: not for a song the offline index lacks whose artist's page isn't
    known) and what the local indexes have of the song elsewhere
    (``outcome.elsewhere``). An export (``jobs.EXPORTING``) is about the song its
    job names (``Job.song_id``) and is none of its requests: no id, and, once it is
    over, the PDF it made (``SongFacts.pdf``). A job that is over doesn't change, so
    its answer is worked out once (``app._ended``).
    """
    over = not job.active
    if over:
        with app._ended_lock:
            ended = app._ended.get(job.id)
        if ended is not None:
            return ended
    from caracole.library_page import sheet_href
    from caracole.songs import find_song

    removal = job.song_key.startswith(REMOVING)
    export = job.song_key.startswith(EXPORTING)
    song = _song_by_id(conn, job.song_id) if export else find_song(conn, job.song_key.removeprefix(REMOVING))
    facts = None
    if song is not None:
        ignored = song.status == "ignored" or (overrides is not None and song.key in overrides.ignore)
        sheet = sheet_href(app.cfg.library_dir, song)
        checked_now = asked_ug = False
        if over and job.fetching and not sheet and job.started_at is not None:
            from caracole.ug.fetch import checked_since

            asked_ug = checked_since(conn, song, job.started_at)
            checked_now = asked_ug or (bool(job.stages) and _nothing_to_ask(conn, song, overrides))
        picker = None
        if song.review and not ignored:
            from caracole.review import candidates_of

            picker = f"review?song={song.id}" if candidates_of(song) else None  # the card's, or its page
        picked = overrides is not None and song.key in overrides.lacuerda and song.lacuerda_checked_at is None
        sheet_from = _sheet_from(conn, song) if sheet and job.stages else ""
        elsewhere = None
        if over and job.fetching and not sheet and not song.review and not ignored:
            from caracole.web.outcome import elsewhere as other_sites

            elsewhere = other_sites(conn, app.cfg, song, job, datetime.now(UTC))
        pdf = None
        if over and export:
            from caracole.web.export_routes import made_pdf

            pdf = made_pdf(conn, app.cfg.library_dir, song, job)
        facts = SongFacts(sheet=sheet, review=bool(song.review), not_found=song.match_decision == "not_found",
                          checked_now=checked_now, ignored=ignored, picker=picker, lacuerda=picked,
                          elsewhere=elsewhere, asked_ug=asked_ug, pdf=pdf, sheet_from=sheet_from)
    # A removal's song is gone once it is done: the job knows which it was.
    answer = (None if export else song.id if song is not None else job.song_id if removal else None, facts)
    if over and overrides is not None:  # with overrides.toml unreadable, "ignored" isn't known
        with app._ended_lock:
            app._ended[job.id] = answer
    return answer


def _sheet_from(conn: sqlite3.Connection, song: Song) -> str:
    """Where the song's kept sheet came from, its site's tag ("UG", "LaCuerda": icons.py), for a lookup's Sheet step;
    "" without one."""
    from caracole.get import kept_sheet
    from caracole.icons import tag
    from caracole.versions import get_version

    kept = kept_sheet(conn, song)
    return tag(get_version(conn, kept.version_id).provider) if kept is not None else ""


def _song_by_id(conn: sqlite3.Connection, song_id: int | None) -> Song | None:
    from caracole.songs import get_song

    if song_id is None:
        return None
    try:
        return get_song(conn, song_id)
    except KeyError:
        return None


def forget_ended(app: WebApp, jobs: list[Job]) -> None:
    """Let go of the jobs the queue no longer remembers (``jobs``: the whole queue)."""
    kept = {job.id for job in jobs}
    with app._ended_lock:
        for job_id in [i for i in app._ended if i not in kept]:
            del app._ended[job_id]


def _ahead(jobs: list[Job], job: Job) -> int:
    """How many jobs wait or run before a queued one."""
    return sum(1 for j in jobs if j.active and j.id < job.id)


def _songbook_page(conn: sqlite3.Connection, job: Job) -> str | None:
    """A songbook's change that is done: its songbook's page, for its line to open; None for any other job."""
    from caracole.web.songbooks import songbook_page

    return songbook_page(conn, job.song_key) if job.state == "done" else None


def _nothing_to_ask(conn: sqlite3.Connection, song: Song, overrides: Overrides | None) -> bool:
    """Whether Ultimate Guitar can't be asked about the song at all: the offline index doesn't have it, and
    its artist's UG page isn't known. ``caracole fetch --song`` refuses such a song; a lookup's sheet stage
    skips it, and what it lacks, UG lacks as far as caracole can tell: not found, not a wait."""
    from caracole.ug.fetch import artist_is_known

    return (song.match_decision == "not_found" and overrides is not None
            and not artist_is_known(conn, song, overrides))


def _job_ids(values: list[str] | None) -> frozenset[int] | None:
    """The jobs ``?jobs=N,M`` asks about (plain digits only, ``MAX_ASKED`` at most); None when the
    address asks about none in particular."""
    if values is None:
        return None
    ids: set[int] = set()
    for part in values[0].split(","):
        part = part.strip()
        if part.isascii() and part.isdigit() and len(ids) < MAX_ASKED:
            ids.add(int(part))
    return frozenset(ids)
