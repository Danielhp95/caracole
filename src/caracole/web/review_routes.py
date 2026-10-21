"""caracole serve's picker: a song in review's candidates, and the answer to it.

    GET  /review?song=ID  a song in review's picker, on a page of its own
    POST /review          a song in review's answer, as ``caracole review --song`` writes it

A pick from the picker is ``caracole review --song "A - T" --pick ARTIST/SONG``
(or ``--none --seen ARTIST/SONG…``), queued and answered like a fetch (to the
page's script, its job; to a form, its line on /jobs), and fetched after it
when asked: the server writes no overrides.toml itself. The candidates the
page showed must be the song's now, and the song's own request goes first.
The picker is on the cards too (library_page.py), and under a request on /jobs
that ended in a review (``picks_waiting``).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from caracole.web import pages
from caracole.web.app import Response, Route, WebApp, html_response, no_such_song, not_ignored, query, song_id
from caracole.web.jobs import Job, fetch_steps, review_steps
from caracole.web.pages import Refused

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.songs import Song


ROUTES = (
    Route("GET", "/review", lambda app, asked: picker(app, query(asked).get("song", [""])[0])),
    Route("POST", "/review", lambda app, asked, form: review(app, form)),
)


def picker(app: WebApp, song_field: str) -> Response:
    """A song in review's picker, on a page of its own."""
    from caracole.songs import get_song

    asked = song_id(song_field, where="address")
    overrides = app.overrides()
    with no_such_song(), app.db() as conn:
        song = get_song(conn, asked)
        pick = _offer(conn, song, overrides, search=True)
    if pick is None:
        not_ignored(song, overrides)
    if pick is None and song.review:
        raise Refused(409, "Nothing to pick", f"{song.display} has no candidates to pick: caracole review "
                                              "offers a pin or an ignore.")
    if pick is None:
        raise Refused(409, "Nothing to pick", f"{song.display} doesn't need review: there's nothing to pick.")
    if not pick.choices:
        raise Refused(409, "Nothing to pick", f"caracole search finds nothing close to {song.display} in the "
                                              "offline Ultimate Guitar index.")
    return html_response(200, pages.review_page(pick, app.csrf))


def review(app: WebApp, form: dict[str, str]) -> Response:
    """A song in review's answer, from the picker: ``caracole review --song`` queued with it.

    ``pick`` is a candidate's ARTIST/SONG, fetched at once with ``fetch``, or
    "none", which rejects the candidates ``shown``. They must be the song's
    candidates now: the nightly run may have matched it again since the page was
    loaded. A song not found takes one of its search hits, the same way. The
    song's own request, if one waits or runs, goes first.
    """
    from caracole.songs import get_song

    asked = song_id(form.get("song", ""))
    pick = form.get("pick", "").strip()
    overrides = app.overrides()
    with no_such_song(), app.db() as conn:
        song = get_song(conn, asked)
        offered = _offer(conn, song, overrides, search=True)
    not_ignored(song, overrides)
    if offered is None:
        raise Refused(409, "Nothing to pick", f"{song.display} doesn't need review any more: reload the "
                                              "library to see where it stands.")
    refs = [str(c["ref"]) for c in offered.choices]
    if not pick:
        raise Refused(400, "No answer", "Pick a candidate, or None of these.")
    if form.get("shown", "").split() != refs or not refs:
        raise Refused(409, "The candidates changed",
                      f"caracole matched {song.display} again since this page was loaded, and its "
                      "candidates changed: reload the library and pick again.")
    if pick == "none" and offered.search:
        raise Refused(400, "Not an answer", "A song not found takes one of its search hits, or nothing.")
    if pick != "none" and pick not in refs:
        raise Refused(400, "Not a candidate", f"{pick} isn't one of its candidates.")
    if pick == "none":
        title, steps, fetch = f"None of these for {song.display}", review_steps(song.display, seen=refs), False
    else:
        fetch = form.get("fetch") in ("1", "on", "yes")
        title, steps = f"Pick {pick} for {song.display}", review_steps(song.display, pick=pick)
        if fetch:  # caracole review matched it again already
            title += ", and fetch it"
            steps += [step for step in fetch_steps(song.display) if step[1][0] != "match"]
    # Never into the song's own request, nor after its fetch: checked under the queue's lock.
    job, new = app.submit(title, song.key, steps, fetching=fetch, join=False, display=song.display)
    if not new:
        raise Refused(409, "Wait for its request",
                      f"A request for {song.display} is waiting or running: pick once it ends.")
    return app.queued(job, f"/jobs#job-{job.id}")  # the card's line says how it goes, as Fetch now's


def review_first(song: Song, overrides: Overrides) -> bool:
    """Whether ``caracole fetch --song`` would refuse the song as needing review first (commands/fetch.py),
    and ``caracole get`` would find no sheet to fetch for it.

    A review that its artist's UG page settles can be fetched, and so can one
    that overrides.toml settles (``[match]``, ``[pin]``): the lookup's match
    stage (the job's ``caracole match``, before a pick's fetch) reads it first. A ``[reject]`` settles it only when it
    names every candidate the song has now: after None of these, the rematch
    may leave the song in review with candidates it hadn't shown, which the
    entry doesn't name, and ``caracole fetch --song`` would refuse it.
    """
    from caracole.review import candidates_of
    from caracole.ug.fetch import needs_artist_page

    if song.match_decision != "review" or needs_artist_page(song):
        return False
    if song.key in overrides.match or song.key in overrides.pin:
        return False
    rejected = overrides.reject.get(song.key)
    return rejected is None or not all((c["artist_key"], c["song_key"]) in rejected for c in candidates_of(song))


def picks_waiting(app: WebApp, jobs: list[Job]) -> dict[str, pages.Pick]:
    """The songs of finished requests that wait for a pick now, by key; none when the database or
    overrides.toml can't be read: the requests page still shows the requests."""
    from caracole.overrides import OverridesError, load_overrides
    from caracole.songs import find_song

    keys = {job.song_key for job in jobs if not job.active}
    if not keys:
        return {}
    picks = {}
    try:
        overrides = load_overrides(app.cfg.overrides_file)
        with closing(app.connect()) as conn:
            for key in sorted(keys):
                song = find_song(conn, key)
                pick = _offer(conn, song, overrides) if song is not None else None
                if pick is not None:
                    picks[key] = pick
    except (OverridesError, sqlite3.Error, OSError):
        return {}
    return picks


def _offer(conn: sqlite3.Connection, song: Song, overrides: Overrides, *, search: bool = False) -> pages.Pick | None:
    """What a song's picker offers: a review's candidates; for a song not found, with ``search``, what
    ``caracole search`` finds for it (a moment's work, for the picker's page alone), or without, no
    choices yet. None for a song with nothing to pick: ignored, settled, or a review without candidates."""
    from caracole.library_page import review_choices
    from caracole.normalize import clean_title
    from caracole.review import search_candidates

    if song.status == "ignored" or song.key in overrides.ignore:
        return None
    title = clean_title(song.title)
    if song.review:
        choices = review_choices(conn, song)
        return pages.Pick(song.id, song.display, title, song.artist, tuple(choices)) if choices else None
    if song.match_decision != "not_found":
        return None
    hits = search_candidates(conn, song, rejected=overrides.reject.get(song.key, frozenset())) if search else []
    return pages.Pick(song.id, song.display, title, song.artist, tuple(review_choices(conn, song, hits)),
                      search=True)
