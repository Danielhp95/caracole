"""caracole serve's songbook forms: each queued as its ``caracole songbook`` command (songbooks.py).

    POST /songbook/…      make a songbook, add to it, move or take out a song, rename it, delete it,
                          or get its songs without a sheet now (songbooks.py); a songbook's page,
                          _songbooks/<folder>/songbook.html, is one of app.py's ``written_pages``

A songbook form queues its ``caracole songbook`` command (songbooks.py checks
it first, against songbooks.toml and the database): to a form, the answer is
its line on /jobs; to the page's script, its job, as a fetch's, which names the
songbook it changes (``songbook``: its name before and after); once the job is
over, /jobs.json gives it with the Songbooks section as the library page would
draw it now (``songbooks``: its HTML and the songbooks for the Select bar,
jobs_routes.py), which the page puts in place of its own.
"""

from __future__ import annotations

import sqlite3

from caracole.web import songbooks
from caracole.web.app import QUEUE_FULL, Response, Route, WebApp, unreadable
from caracole.web.jobs import Job, QueueFull, lookup_steps
from caracole.web.pages import Refused

# Each songbook form's address (songbooks.ROUTES), and Get the missing songs now's.
ROUTES = (
    *(Route("POST", path, lambda app, asked, form, path=path: change(app, form, route=path))
      for path in songbooks.ROUTES),
    Route("POST", songbooks.GET_MISSING, lambda app, asked, form: get_missing(app, form)),
)


def change(app: WebApp, form: dict[str, str], *, route: str) -> Response:
    """A songbook made or changed (``route``, one of songbooks.ROUTES): its caracole songbook command queued."""
    from caracole.web.songbooks import songbook_job

    try:
        job = songbook_job(route, form, library_dir=app.cfg.library_dir, connect=app.connect)
    except (sqlite3.Error, OSError) as e:
        raise unreadable(e) from e
    queued, _ = app.submit(job.title, job.key, job.steps)
    return app.queued(queued, f"/jobs#job-{queued.id}")  # its songbook's card says how it goes


def get_missing(app: WebApp, form: dict[str, str]) -> Response:
    """A songbook's songs without a sheet, looked up now: one ``caracole get`` each, as a card's Fetch now
    queues it, in the songbook's order, then ``caracole songbook render NAME`` after them, which makes the
    songbook again with what they got (songbooks.py). To the page's script, the songbook's job, with each
    lookup's (``jobs``) and how many songs wait for another tap, the queue being full (``left``)."""
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
            job, _ = app.queue.submit(f"Fetch {song.display}", song.key, lookup_steps(song.artist, song.title),
                                      fetching=True, display=song.display)
        except QueueFull:
            break
        lookups.append(job)
    if not lookups:
        raise Refused(503, "The queue is full", QUEUE_FULL)
    book = render_job(name, max(job.id for job in lookups))
    # A queue full now refuses the songbook alone: the lookups run all the same, and the nightly run makes it.
    made, _ = app.submit(book.title, book.key, book.steps)
    response = app.queued(made, f"/jobs#job-{made.id}")  # its songbook's card says how it goes
    response.data = {**(response.data or {}), "jobs": [app.job_view(job) for job in lookups],  # each on its card
                     "left": len(songs) - len(lookups)}
    return response
