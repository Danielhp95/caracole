"""caracole serve's sheet from a YouTube video: a song's auto sheet, made now from the video you paste.

    POST /youtube         a song's auto sheet from the YouTube video ``youtube`` names: a song of the library
                          (``song``, its id: its card's Sheet from a YouTube video), or one by name (``artist``,
                          ``title``, and optionally ``album`` and ``duration``: written to wanted.txt first, as a
                          request is), with ``caracole youtube --sheet`` queued
    POST /youtube/search  YouTube's first video for a query (``q``), suggested beside the search's results:
                          ``caracole youtube --search --progress`` queued, one yt-dlp run and its thumbnail, when
                          its gate (youtube_search.py) says so
    GET  /youtube/thumb[/<id>.jpg]
                          a suggested video's thumbnail, as caracole kept it in its cache

The library page's request form sends its YouTube video here (``POST /request`` with ``youtube``, which
library_routes.py hands over: ``sheet_from_youtube``), in place of a lookup. The job is one ``caracole youtube
--sheet --progress`` (jobs.py ``youtube_sheet_steps``, youtube_sheet.py): the audio taken with yt-dlp, as the
youtube step takes it, within its budget and pauses, the lyrics from LRCLIB, the chords from the audio, the PDF
and the viewer. Its key is the song's after ``jobs.YOUTUBE_SHEET``, so it never joins the song's lookup, nor a
lookup it, and one at a time a song: asked again while one waits or runs, that one is the answer. Its view is the
song's (/jobs.json's ``kind`` "song"), so the song's line says how it goes, its stages as steps (outcome.py).

The video is given to the command as its plain address (``youtube_urls.watch_url``), never as pasted: no
playlist, no tracking. Refused, with nothing written or queued (``pages.Refused``): a link that is no YouTube
video's address (400), a caracole that can't make chords of the audio (``youtube_fetch.route_problem``, 409,
in its words, as the library page says it beside the field it then doesn't offer), and a song YouTube isn't
for (409: one with a human sheet, ignored, or with a purchase linked), as the command refuses it again when
it runs.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from caracole.web.app import (
    FRAMES,
    Response,
    Route,
    WebApp,
    address,
    json_response,
    no_such_song,
    not_ignored,
    redirect,
    song_id,
    wants_json,
)
from caracole.web.jobs import YOUTUBE_SEARCH, YOUTUBE_SHEET, youtube_search_steps, youtube_sheet_steps
from caracole.web.pages import Refused
from caracole.web.status import details_href

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.songs import Song

VIDEO_LIMIT = 600  # characters of a pasted address
NOT_HERE = "No sheets from YouTube here"  # how the page and a refusal begin, where none can be made

ROUTES = (
    Route("POST", "/youtube", lambda app, asked, form: sheet_from_youtube(app, form)),
    Route("POST", "/youtube/search", lambda app, asked, form: search_youtube(app, form, json=wants_json(asked))),
    Route("GET", "/youtube/thumb/", lambda app, asked: thumbnail(app, address(asked)[len("/youtube/thumb/"):]),
          under=True),
)
THUMB = "/youtube/thumb/"
QUERY_LIMIT = 200


def sheet_from_youtube(app: WebApp, form: dict[str, str]) -> Response:
    """A song's auto sheet from the video in ``youtube``, queued (see the module docstring): the song by its id
    (``song``), else by name, written to wanted.txt first."""
    from caracole.normalize import identity_key
    from caracole.songs import find_song, get_song
    from caracole.web.library_routes import wanted_line

    url = video_field(form)
    problem = youtube_problem(app)
    if problem is not None:
        raise Refused(409, "Not here", f"{NOT_HERE}: {problem}.")
    overrides = app.overrides()
    note = ""
    if form.get("song", "").strip():
        asked = song_id(form["song"])
        with no_such_song(), app.db() as conn:
            song = get_song(conn, asked)
            youtube_is_for(conn, song, overrides)
        display, key = song.display, song.key
    else:
        artist, title = form.get("artist", "").strip(), form.get("title", "").strip()
        if artist and title:  # one the library has: refused before its wanted.txt line is touched
            with app.db() as conn:
                known = find_song(conn, identity_key(artist, title))
                if known is not None:
                    youtube_is_for(conn, known, overrides)
        line, note = wanted_line(app, form)
        display, key = f"{line.artist} - {line.title}", line.identity
    job, _ = app.submit(f"YouTube sheet {display}", YOUTUBE_SHEET + key, youtube_sheet_steps(display, url),
                        display=display, note=note,
                        full=f"{note} The queue is full, so nothing was queued: ask again once it empties.".strip())
    return app.queued(job)


def video_field(form: dict[str, str]) -> str:
    """A form's ``youtube``, the video's plain address; Refused (400) for anything that is no YouTube video's."""
    from caracole.youtube_urls import video_id_from_url, watch_url

    value = form.get("youtube", "").strip()
    video = video_id_from_url(value) if len(value) <= VIDEO_LIMIT else None
    if video is None:
        raise Refused(400, "Not a video", "Not a YouTube video link.")
    return watch_url(video)


def youtube_problem(app: WebApp) -> str | None:
    """Why this caracole makes no sheet from a YouTube video, in a few words (``youtube_fetch.route_reason``), or None
    when it does."""
    from caracole.youtube_fetch import route_reason

    return route_reason(app.cfg)


def youtube_is_for(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> None:
    """Refused (409) for a song a sheet from YouTube isn't for: ignored, with a human sheet, or with a purchase
    linked, in the words ``caracole youtube --sheet`` refuses it in."""
    from caracole.songs import HUMAN_SHEET
    from caracole.youtube_fetch import youtube_audio

    not_ignored(song, overrides)
    if conn.execute("SELECT 1 FROM files WHERE song_id = ? AND name = ?", (song.id, HUMAN_SHEET)).fetchone():
        raise Refused(409, "Has a sheet", f"{song.display} already has a sheet.")
    if song.audio_path and youtube_audio(conn, song) is None:
        raise Refused(409, "Has its audio", f"{song.display} has bought audio in Music/: auto-chords uses that.")


# --- a video suggested for a search ---------------------------------------------------------------------


def suggested(app: WebApp, conn: sqlite3.Connection, q: str, *, on_screen: bool) -> dict[str, Any] | None:
    """What /api/search says of a YouTube video for ``q`` (youtube_search.py's ``gate``, with no request): None, or
    its ``state`` and, found, the video. ``on_screen``: the search's answer has a sheet for it already
    (``youtube_search.sheet_on_screen``)."""
    from datetime import UTC, datetime

    from caracole.youtube_search import gate, suggestion

    return suggestion(gate(app.cfg, conn, q, on_screen=on_screen, now=datetime.now(UTC)), q)


def _on_screen(conn: sqlite3.Connection, q: str) -> bool:
    """``youtube_search.sheet_on_screen`` for ``q``, its searches made now, as /api/search makes them."""
    from caracole.search import IndexFound, find_index, search_lacuerda, search_library
    from caracole.ug.index import index_count
    from caracole.youtube_search import sheet_on_screen

    index = find_index(conn, q) if index_count(conn) else IndexFound()
    lc_artists, lc_songs = search_lacuerda(conn, q, songs=5)
    return sheet_on_screen(search_library(conn, q, 10), index, lc_artists, lc_songs)


def search_youtube(app: WebApp, form: dict[str, str], *, json: bool) -> Response:
    """YouTube's first video for a query (``q``) and its thumbnail: ``caracole youtube --search --progress`` queued, a
    job of no song's (asked again while it waits or runs, that job), when its gate says ``auto``; refused otherwise
    (400 no query, 409 a sheet on the screen already, no sheet from a video here, or searched within 30 days, 429 a
    cooldown, the hour's searches spent, or one failed lately). The page follows it on /api/jobs, then searches again."""
    q = " ".join(form.get("q", "").split())
    if not q or len(q) > QUERY_LIMIT:
        raise Refused(400, "Not a query", f"Which query? 1 to {QUERY_LIMIT} characters.")
    with app.db() as conn:
        said = suggested(app, conn, q, on_screen=_on_screen(conn, q))
    if said is None:
        raise Refused(409, "Not for this", "No YouTube search for this.")
    if said["state"] in ("found", "none"):
        raise Refused(409, "Searched already", "Searched already this month.")
    if said["state"] != "auto":
        raise Refused(429, "Not now", f"Not now: {said.get('why', 'try again later')}.")
    job, _ = app.submit(f"Search YouTube for “{q}”", YOUTUBE_SEARCH + said["key"], youtube_search_steps(q),
                        display=f"“{q}” on YouTube")
    if json:
        return json_response(202, {"job": job.id, "url": f"/api/jobs/{job.id}"})
    return redirect(f"/{details_href(job.id)}")


def thumbnail(app: WebApp, name: str) -> Response:
    """A suggested video's thumbnail, ``<id>.jpg``, as caracole kept it (checked again: a JPEG alone), with a policy
    that lets it run nothing; 404 for any other name or a thumbnail not kept."""
    from caracole.youtube_search import read_thumbnail

    data = read_thumbnail(app.cfg, name.removesuffix(".jpg")) if name.endswith(".jpg") else None
    if data is None:
        return json_response(404, {"error": "No such thumbnail."})
    return Response(200, data, [("Content-Type", "image/jpeg"),
                                ("Content-Security-Policy", f"default-src 'none'; {FRAMES}")])
