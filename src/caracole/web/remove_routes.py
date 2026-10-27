"""caracole serve's removal of a song: the question, then ``caracole remove --yes`` queued.

    POST /remove          what removing a song takes; with ``confirm``, ``caracole remove`` queued, and
                          back to the library, at the song's card (to the page's script: what it takes,
                          as data, then the job)

A removal is asked on the song's card by the page's script: Remove there
counts down five seconds, with Undo, while the card says what goes (the
question, answered as data: ``removal``), and only then sends the
confirmation, answered with the job, whose line the card shows, as a
fetch's: the job names its song even once the song is gone. Without
JavaScript, Remove opens the question as a page, and the removal, confirmed,
goes back to the library page as it was left (``back``: its search, filters
and view, the part of its address after #, which the form sends along), at
the song's card (``song=ID``). The job's key is the song's after
``jobs.REMOVING``, so it never joins the song's lookup, nor a lookup it.
"""

from __future__ import annotations

import re

from caracole.web import pages
from caracole.web.app import Response, Route, WebApp, html_response, no_such_song, song_id
from caracole.web.jobs import REMOVING, remove_steps
from caracole.web.pages import Refused

# The library page's own address after #, as its script writes it (URLSearchParams' characters alone).
_BACK = re.compile(r"[A-Za-z0-9%*._~+=&-]{0,512}")

ROUTES = (Route("POST", "/remove", lambda app, asked, form: remove(app, form)),)


def remove(app: WebApp, form: dict[str, str]) -> Response:
    """Say what removing a song takes and leaves, and ask; confirmed, queue ``caracole remove --yes``
    and go back to the library, at the song's card, as ``back`` left it (``_library_at``).

    The confirmation carries the song's key: a song id the database gave
    another song since the question was asked removes nothing. To the library
    page's script, the question is data (``removal``: the song's key, what goes
    in one sentence, ``brief``, and whole), which its card says while it counts
    down to Undo; the confirmation, the job, whose line its card shows: the
    page stays where it is. The question page is for a browser without it.
    """
    from caracole.removal import brief, describe, plan_removal
    from caracole.songs import get_song

    asked = song_id(form.get("song", ""))
    confirmed = form.get("confirm") == "1"
    back = _back(form.get("back", ""))
    with no_such_song("That song isn't in the library: removed already, maybe."), app.db() as conn:
        song = get_song(conn, asked)
        plan = None if confirmed else plan_removal(conn, app.cfg, song)
    if plan is not None:
        goes, stays, notes = describe(plan, app.cfg)
        question = html_response(200, pages.remove_page(song.display, song.id, song.key, app.csrf, goes, stays,
                                                        notes, waiting=app.queue.active_count(), back=back,
                                                        library=_library_at(back, song.id)))
        question.data = {"removal": {"song": song.id, "key": song.key, "display": song.display,
                                     "brief": brief(plan), "goes": goes, "stays": stays, "notes": notes}}
        return question
    if form.get("key") != song.key:
        raise Refused(409, "Not that song", "The library changed since this page was made, so nothing was "
                                            "removed: reload the library and try again.")
    job, _ = app.submit(f"Remove {song.display}", REMOVING + song.key, remove_steps(song.display),
                        display=song.display, song_id=song.id)
    return app.queued(job, _library_at(back, song.id))  # its card says Removing…, then Removed


def _back(text: str) -> str:
    """The library page's address after # that a form sends along (``back``), as its script wrote it, without
    a song to show (``song=``); "" for anything else, which is no address of the page's."""
    text = text.removeprefix("#")
    if not _BACK.fullmatch(text):
        return ""
    return "&".join(part for part in text.split("&") if part and not part.startswith("song="))


def _library_at(back: str, song: int) -> str:
    """The library page as ``back`` (``_back``) left it, at a song's card (``song``, its id)."""
    return f"/#{back}&song={song}" if back else f"/#song={song}"
