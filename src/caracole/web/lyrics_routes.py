"""caracole serve's lyrics of a song looked up under a name you type: what the lyrics sites list under it, one of
their records taken as the song's lyrics, and that pick taken back.

    POST /lyrics/search   a song's lyrics looked up under a name you type (``song``, its id, its ``identity``, and
                          ``artist`` and ``title``): ``caracole lyrics --song --as`` queued, a job of no song's under
                          ``jobs.LYRICS_SEARCH`` and the song's key, the lane's; a lookup the owner pressed, never
                          sent by the page by itself, within the lookups' hour (the command's clients)
    GET  /api/lyrics/search?song=ID
                          what the card's panel shows, with no request, no lock and no write: the song's ``[lyrics]``
                          name (``as``) and record (``picked``), why that record gives it no lyrics (``picked_why``),
                          the song's audio length, and its kept search (its rows, each site's words and state, how
                          many instrumental records were left out, the name it asked under and the length its rows
                          were scored against, whether it is still pickable, and its last line's words)
    POST /lyrics/pick     one of those rows taken as the song's lyrics (``song``, ``identity``, ``record``): ``caracole
                          lyrics --song --record --progress`` queued under ``jobs.LYRICS_PICK``, the queue's
    POST /lyrics/clear    the record you picked taken back (``song``, ``identity``): ``caracole lyrics --song --clear``
                          queued under ``jobs.LYRICS_CLEAR``, the queue's

**The name asked.** The page sends the artist and the title apart; the route joins them into ``--as "A - T"``, which
the command reads back through song_names.py and cleans (lyrics_search.py ``typed_name``: a title typed with a
video's tag, "Vikingos veganos (Video Oficial)", is asked as "Vikingos veganos"). So the route reads the name as the
command will and queues that one: its answer's ``as``, the job's label and its ``--as`` are the name the sites are
asked under, never the fields as typed, and ``GET /api/lyrics/search``'s ``search.as`` is the one the kept search was
made under, for the card's "Asked as …". The route's reading can't differ from the command's but by the library's
known artists changing in between, and then the kept search says the name it used.

**One at a time.** A search answers 202 ``{job, url: "/api/jobs/N", as}`` to the page's script (a form, a redirect to
its request in the Requests tab); while a search of the song waits or runs, that job is the answer, its ``as`` the name
it asks under, and, when that isn't the name just typed, ``said`` says so ("A search under “X” is on its way: ask under
“Y” once it is over."), so a second name is never taken for asked. A pick and a clear are posted in place
(``WebApp.queued``); the same record picked again while its pick waits or runs is that job, and another record is
refused (409, "A pick of this song is on its way: lrclib:1. …"), never dropped silently; a clear asked again is the
clear on its way.

Refused, with nothing queued (``pages.Refused``): a song not in the book (404), another song's ``identity`` (409,
``app.same_song``), an ignored one (409, ``app.not_ignored``), a full queue or lane (503); a search's name of no
artist or title, or one past 200 characters (400 "Which name? …"), an artist's name holding " - " (400), a name that
cleans to nothing (400); a pick of a record that isn't a row of the song's kept search, or of a search over a week old
(409 "Search again: …": the command checks it again as it runs), or of a site turned off (409); a clear of a song with
no record picked (409, the command's "… nothing to clear."). A pick needs nothing this caracole may lack: without
auto-chords its lyrics are kept all the same, the chords waiting for the nightly run. The phone has none of these
routes (lyrics are searched and picked on the computer, for now) and its page offers no control for them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from caracole.web.app import (
    Response,
    Route,
    WebApp,
    json_response,
    no_such_song,
    not_ignored,
    query,
    redirect,
    same_song,
    song_id,
    wants_json,
)
from caracole.web.jobs import (
    LYRICS_CLEAR,
    LYRICS_PICK,
    LYRICS_SEARCH,
    lyrics_clear_steps,
    lyrics_pick_steps,
    lyrics_search_steps,
)
from caracole.web.pages import Refused
from caracole.web.status import details_href

if TYPE_CHECKING:
    from caracole.lyrics_search import Search
    from caracole.songs import Song
    from caracole.web.jobs import Job

NAME_MOST = 200  # characters of each field of a name typed (lyrics.ASKED_MOST: as many as [lyrics]' ``as`` keeps)
WHICH_NAME = f"Which name? An artist and a title, 1 to {NAME_MOST} characters each."
SEARCH_AGAIN = "Search again: that record isn't among its last search's, or the search is over a week old."

ROUTES = (
    Route("POST", "/lyrics/search", lambda app, asked, form: search(app, form, json=wants_json(asked))),
    Route("GET", "/api/lyrics/search", lambda app, asked: api_search(app, query(asked))),
    Route("POST", "/lyrics/pick", lambda app, asked, form: pick(app, form)),
    Route("POST", "/lyrics/clear", lambda app, asked, form: clear(app, form)),
)


def _song(app: WebApp, form: dict[str, str]) -> Song:
    """The song a form names by its id (``song``), the one its ``identity`` names, not ignored."""
    from caracole.songs import get_song

    overrides = app.overrides()
    asked = song_id(form.get("song", ""))
    with no_such_song(), app.db() as conn:
        song = get_song(conn, asked)
    same_song(song, form)
    not_ignored(song, overrides)
    return song


def _as_json(name: tuple[str, str] | None) -> dict[str, str] | None:
    return {"artist": name[0], "title": name[1]} if name is not None else None


def _typed(app: WebApp, artist: str, title: str) -> tuple[str, str]:
    """The name the command will ask under for the fields typed (lyrics_search.py ``typed_name``); Refused (400)
    for fields of no name, too long, an artist holding " - ", or a name that cleans to nothing."""
    from caracole.lyrics_search import typed_name

    if not (1 <= len(artist) <= NAME_MOST and 1 <= len(title) <= NAME_MOST):
        raise Refused(400, "Which name?", WHICH_NAME)
    if " - " in artist:
        raise Refused(400, "Which name?", "An artist's name can't hold “ - ”.")
    text = f"{artist} - {title}"
    with app.db() as conn:
        name = typed_name(conn, text)
    if name is None:
        raise Refused(400, "Which name?", f"Which name? “{text}” names no artist and title once cleaned.")
    return name


def _asked_by(job: Job) -> str:
    """The name a search job asks under (its ``--as=``)."""
    return next((arg.removeprefix("--as=") for step in job.steps for arg in step.args if arg.startswith("--as=")), "")


def search(app: WebApp, form: dict[str, str], *, json: bool) -> Response:
    """``POST /lyrics/search``: the song's lyrics looked up under the name typed, queued (the module's docstring)."""
    from caracole.lyrics_search import typed_name

    song = _song(app, form)
    name = _typed(app, form.get("artist", "").strip(), form.get("title", "").strip())
    named = f"{name[0]} - {name[1]}"
    job, new = app.submit(f"Lyrics under “{named}”", LYRICS_SEARCH + song.key,
                          lyrics_search_steps(song.display, named), display=song.display)
    answer: dict[str, Any] = {"job": job.id, "url": f"/api/jobs/{job.id}", "as": _as_json(name)}
    asked = _asked_by(job)
    if not new and asked != named:  # another name on its way: said, never taken for the one just typed
        with app.db() as conn:
            answer["as"] = _as_json(typed_name(conn, asked))  # None for one that reads as no name now
        answer["said"] = f"A search under “{asked}” is on its way: ask under “{named}” once it is over."
    if json:
        return json_response(202, answer)
    return redirect(f"/{details_href(job.id)}")


def api_search(app: WebApp, asked: dict[str, list[str]], *, now: datetime | None = None) -> Response:
    """``GET /api/lyrics/search?song=ID``: what the card's panel shows of the song's lyrics search, read with no
    request and no lock, as of ``now`` (this moment by default)."""
    from caracole.autochords.transcript import picked_without_lyrics
    from caracole.lyrics_search import audio_length, last_search
    from caracole.overrides import override_key
    from caracole.songs import get_song

    overrides = app.overrides()
    wanted = song_id((asked.get("song") or [""])[0], where="address")
    with no_such_song(), app.db() as conn:
        song = get_song(conn, wanted)
        same_song(song, {"identity": (asked.get("identity") or [""])[0]})
        kept = last_search(conn, song.id)
        length = audio_length(conn, song)
    entry = overrides.lyrics.get(override_key(song.display))
    return json_response(200, {
        "song": song.id, "identity": song.key,
        "as": _as_json(entry.asked if entry is not None else None),
        "picked": entry.record.text if entry is not None and entry.record is not None else None,
        "picked_why": picked_without_lyrics(song, overrides),
        "length": length,
        "search": _search_json(kept, now or datetime.now(UTC)) if kept is not None else None,
    })


def _search_json(kept: Search, now: datetime) -> dict[str, Any]:
    from caracole.lyrics_search import last_line, pickable

    return {"at": kept.at, "as": _as_json(kept.asked), "length": kept.length,
            "rows": [row.as_json() for row in kept.rows], "said": dict(kept.said), "state": dict(kept.state),
            "instrumental": kept.instrumental, "pickable": pickable(kept, now), "line": last_line(kept)}


def _record_of(job: Job) -> str:
    """The record a pick job takes (its ``--record=``, else its ``--pick=`` row)."""
    return next((arg.split("=", 1)[1] for step in job.steps for arg in step.args
                 if arg.startswith(("--record=", "--pick="))), "")


def pick(app: WebApp, form: dict[str, str], *, now: datetime | None = None) -> Response:
    """``POST /lyrics/pick``: a row of the song's kept search taken as its lyrics, queued (the module's docstring)."""
    from caracole.logs import provider_name
    from caracole.lyrics_search import kept_search, row_of

    song = _song(app, form)
    record = form.get("record", "").strip()
    with app.db() as conn:
        kept = kept_search(conn, song.id, now or datetime.now(UTC))
    row = row_of(kept, record) if kept is not None else None
    if row is None:
        raise Refused(409, "Search again", SEARCH_AGAIN)
    if not app.cfg.provider(row.site).enabled:
        raise Refused(409, "Turned off", f"{provider_name(row.site)} is off (caracole.toml): nothing picked.")
    job, new = app.submit(f"Lyrics for {song.display}", LYRICS_PICK + song.key, lyrics_pick_steps(song.display, record),
                          display=song.display, join=False)
    on_its_way = _record_of(job)
    if not new and on_its_way != record:  # one pick of a song at a time: never dropped silently
        raise Refused(409, "On its way", f"A pick of this song is on its way: {on_its_way}. Pick another once it is "
                                         "over.")
    return app.queued(job)


def clear(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /lyrics/clear``: the record you picked for the song taken back, queued (the module's docstring)."""
    from caracole.lyrics import picked_record
    from caracole.lyrics_pick import NOTHING_TO_CLEAR

    song = _song(app, form)
    if picked_record(song, app.overrides().lyrics) is None:
        raise Refused(409, "Nothing to clear", f"{song.display} {NOTHING_TO_CLEAR}")
    job, _ = app.submit(f"Clear the lyrics record: {song.display}", LYRICS_CLEAR + song.key,
                        lyrics_clear_steps(song.display), display=song.display, join=False)
    return app.queued(job)
