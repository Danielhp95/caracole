"""caracole serve's songbook forms: each queued as its ``caracole songbook`` command (songbooks.py).

    POST /songbook/…      make a songbook, add to it, move or take out a song, set where it plays a song,
                          rename it, delete it, or get its songs without a sheet now (or one of them), or
                          add a song from the Songbooks tab's search (songbooks.py); a songbook's page,
                          _songbooks/<folder>/songbook.html, is one of app.py's ``written_pages``

A songbook form queues its ``caracole songbook`` command (songbooks.py checks
it first, against songbooks.toml and the database): to a form, the answer is
its line on /jobs; to the page's script, its job, as a fetch's, which names the
songbook it changes (``songbook``: its name before and after); once the job is
over, /jobs.json gives it with the songbooks as the library page's Songbooks tab
has them now (``songbooks``, jobs_routes.py), which the page draws again.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from caracole.web import songbooks
from caracole.web.app import QUEUE_FULL, Response, Route, WebApp, unreadable
from caracole.web.jobs import Job, QueueFull, lookup_steps
from caracole.web.pages import Refused

# Each songbook form's address (songbooks.ROUTES), Get the missing songs now's and Add a song's.
ROUTES = (
    *(Route("POST", path, lambda app, asked, form, path=path: change(app, form, route=path))
      for path in songbooks.ROUTES),
    Route("POST", songbooks.GET_MISSING, lambda app, asked, form: get_missing(app, form)),
    Route("POST", songbooks.ADD_SONG, lambda app, asked, form: add_song(app, form)),
)


def change(app: WebApp, form: dict[str, str], *, route: str) -> Response:
    """A songbook made or changed (``route``, one of songbooks.ROUTES): its caracole songbook command queued."""
    from caracole.web.songbooks import songbook_job

    try:
        job = songbook_job(route, form, library_dir=app.cfg.library_dir, connect=app.connect)
    except (sqlite3.Error, OSError) as e:
        raise unreadable(e) from e
    queued, _ = app.submit(job.title, job.key, job.steps)
    return app.queued(queued, f"/jobs#job-{queued.id}")  # its songbook says how it goes


def get_missing(app: WebApp, form: dict[str, str]) -> Response:
    """A songbook's songs without a sheet (with ``song``, a set list's Get it: that one), looked up now: one
    ``caracole get --no-songbooks`` each, as a song's Fetch now queues it, in the songbook's order, then ``caracole songbook
    render NAME`` after them, which makes the songbook again with what they got (songbooks.py). To the page's
    script, the songbook's job, with each lookup's (``jobs``) and how many songs wait for another tap, the queue
    being full (``left``)."""
    from caracole.web.songbooks import missing_songs, render_job

    overrides = app.overrides()
    try:
        name, songs = missing_songs(form, library_dir=app.cfg.library_dir, connect=app.connect,
                                    overrides=overrides)
    except (sqlite3.Error, OSError) as e:
        raise unreadable(e) from e
    lookups: list[Job] = []
    for song in songs[: max(0, app.queue.room() - 1)]:  # room for the songbook after them
        try:
            job, _ = app.queue.submit(f"Fetch {song.display}", song.key, lookup_steps(song.artist, song.title, songbooks=False),
                                      fetching=True, display=song.display)
        except QueueFull:
            break
        lookups.append(job)
    if not lookups:
        raise Refused(503, "The queue is full", QUEUE_FULL)
    book = render_job(name, max(job.id for job in lookups))
    # A queue full now refuses the songbook alone: the lookups run all the same, and the nightly run makes it.
    made, _ = app.submit(book.title, book.key, book.steps)
    response = app.queued(made, f"/jobs#job-{made.id}")  # its songbook says how it goes
    response.data = {**(response.data or {}), "jobs": [app.job_view(job) for job in lookups],  # each on its line
                     "left": len(songs) - len(lookups)}
    return response


def add_song(app: WebApp, form: dict[str, str]) -> Response:
    """A song put in a songbook from the Songbooks tab's search: one of your library (``song``, its id, or the
    one a result of the indexes is: its UG pick or its names), with ``caracole songbook add`` alone; one the
    library hasn't got, written to wanted.txt and looked up now as Get it does (``search_routes.lookup_request``,
    one ``caracole get``), then added once it is in the library: the queue runs them in turn. Nothing is queued
    unless both fit (``JobQueue.submit_all``). To the page's script, the songbook's job, with the lookup's (``jobs``)."""
    from caracole.web.search_routes import library_song, lookup_request
    from caracole.web.songbooks import add_job, book_named

    try:
        name = book_named(form, app.cfg.library_dir)
    except (sqlite3.Error, OSError) as e:
        raise unreadable(e) from e
    song = library_song(app, form)
    requests: list[dict[str, Any]] = []
    full = QUEUE_FULL
    if song is not None:
        display = song.display
    else:
        if not (form.get("artist", "").strip() and form.get("title", "").strip()):
            raise Refused(400, "Not a song", "Which song? The form names none.")
        lookup, display, full = lookup_request(app, form)
        requests.append(lookup)
    job = add_job(name, display)
    requests.append({"title": job.title, "song_key": job.key, "steps": job.steps})
    try:  # the lookup and the songbook's change, or neither (a lookup that joins a queued job needs no room)
        queued = app.queue.submit_all(requests)
    except QueueFull:
        raise Refused(503, "The queue is full", full) from None
    response = app.queued(queued[-1][0], f"/jobs#job-{queued[-1][0].id}")
    response.data = {**(response.data or {}), "jobs": [app.job_view(j) for j, _ in queued[:-1]]}
    return response
