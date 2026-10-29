"""caracole serve's sheet from a YouTube video: a song's auto sheet, made now from the video you paste.

    POST /youtube         a song's auto sheet from the YouTube video ``youtube`` names: a song of the library
                          (``song``, its id: its card's Sheet from a YouTube video), or one by name (``artist``,
                          ``title``, and optionally ``album`` and ``duration``: written to wanted.txt first, as a
                          request is), with ``caracole youtube --sheet`` queued
    POST /youtube/search  YouTube's first video for a query (``q``), suggested beside the search's results:
                          ``caracole youtube --search --progress`` queued, one yt-dlp run and its thumbnail, when
                          its gate (youtube_search.py) says so
    GET  /api/youtube/video?url=
                          a video pasted into the library page's search box (``url``, any link to it, or ``id``): its id and
                          plain address, what its gate says (youtube_search.video_gate), its title, channel, length
                          and thumbnail once read, the song's name guessed from them (youtube_names.py), and the
                          library's song of it (by its audio, its paste, or the name), with or without a sheet
    POST /youtube/video   that video's metadata read (``url`` or ``id``): ``caracole youtube --video --progress`` queued, one yt-dlp run
                          with no download and its thumbnail, when its gate says so
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
    query,
    redirect,
    song_id,
    wants_json,
)
from caracole.web.jobs import (
    YOUTUBE_SEARCH,
    YOUTUBE_SHEET,
    youtube_search_steps,
    youtube_sheet_steps,
    youtube_video_steps,
)
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
    Route("GET", "/api/youtube/video", lambda app, asked: pasted_video(app, query(asked))),
    Route("POST", "/youtube/video", lambda app, asked, form: read_pasted_video(app, form, json=wants_json(asked))),
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


# --- a video pasted into the search box ----------------------------------------------------------------------


def _pasted_id(link: str, video_id: str = "") -> str:
    """The id of the video a pasted link names (or ``video_id``, the id itself, as the page sends it once it read
    the link); Refused (400) for anything else."""
    from caracole.youtube_urls import VIDEO_ID, video_id_from_url

    if video_id:
        video = video_id if VIDEO_ID.fullmatch(video_id) else None
    else:
        video = video_id_from_url(link.strip()) if len(link) <= VIDEO_LIMIT else None
    if video is None:
        raise Refused(400, "Not a video", "Not a YouTube video link.")
    return video


def pasted_video(app: WebApp, asked: dict[str, list[str]]) -> Response:
    """What the library page offers for a video pasted into its search box, with no request: its ``id`` and plain
    ``url``; its gate's ``state`` (youtube_search.video_gate: ``found``, ``none``, ``auto``, ``spent``, ``failed``,
    ``off``) and ``why``; once read, the ``video`` (title, channel, length, the thumbnail's address) and the song's name
    guessed from them (``guess``, youtube_names.py: a library or offline index's artist turns a title round); and the
    library's song of it (``song``: by its audio or its paste, else by the guessed name), whether it has a human
    sheet, and the link to it."""
    from datetime import UTC, datetime

    from caracole.library_page import sheet_href
    from caracole.normalize import identity_key
    from caracole.songs import HUMAN_SHEET, find_song
    from caracole.youtube_names import guess
    from caracole.youtube_search import known_artist, song_of_video, video_gate
    from caracole.youtube_urls import watch_url

    video_id = _pasted_id((asked.get("url") or [""])[0], (asked.get("id") or [""])[0])
    overrides = app.overrides()
    with app.db() as conn:
        said = video_gate(app.cfg, conn, video_id, datetime.now(UTC))
        video = said.asked.get("video") if said.asked is not None else None
        video = video if isinstance(video, dict) else None
        artist, title = (guess(str(video.get("title") or ""), str(video.get("channel") or ""),
                               known=lambda name: known_artist(conn, name)) if video else ("", ""))
        song = song_of_video(conn, overrides, video_id)
        if song is not None:  # the library's own song of the video: its names
            artist, title = song.artist, song.title
        elif artist and title:
            song = find_song(conn, identity_key(artist, title))
        has_sheet = song is not None and conn.execute(
            "SELECT 1 FROM files WHERE song_id = ? AND name = ?", (song.id, HUMAN_SHEET)).fetchone() is not None
    why = said.why or (f"YouTube won't give it ({said.asked.get('unavailable')})"
                       if said.state == "none" and said.asked else "")
    return json_response(200, {
        "id": video_id, "url": watch_url(video_id), "state": said.state, **({"why": why} if why else {}),
        "video": {"title": video.get("title") or "", "channel": video.get("channel") or "",
                  "duration": video.get("duration"),
                  "thumb": f"{THUMB}{video_id}.jpg" if said.asked and said.asked.get("thumb") else None}
        if video else None,
        "guess": {"artist": artist, "title": title},
        "song": {"id": song.id, "display": song.display, "has_sheet": has_sheet,
                 "sheet": sheet_href(app.cfg.library_dir, song) if has_sheet else None} if song is not None else None,
    })


def read_pasted_video(app: WebApp, form: dict[str, str], *, json: bool) -> Response:
    """A pasted video's title, channel, length and thumbnail read now: ``caracole youtube --video --progress`` queued,
    a job of no song's (asked again while it waits or runs, that job), when its gate says ``auto``; refused otherwise
    (400 no video's link, 409 read already this month or no sheet from YouTube here, 429 a cooldown, the hour's
    lookups spent, or a failure lately). The page follows it on /api/jobs, then asks /api/youtube/video again."""
    from datetime import UTC, datetime

    from caracole.youtube_search import video_gate

    video_id = _pasted_id(form.get("url", ""), form.get("id", ""))
    with app.db() as conn:
        said = video_gate(app.cfg, conn, video_id, datetime.now(UTC))
    if said.state in ("found", "none"):
        raise Refused(409, "Read already", "Read already this month.")
    if said.state == "off":
        raise Refused(409, "Not here", f"{NOT_HERE}: {said.why}.")
    if said.state != "auto":
        raise Refused(429, "Not now", f"Not now: {said.why}.")
    job, _ = app.submit(f"Read YouTube video {video_id}", YOUTUBE_SEARCH + said.key, youtube_video_steps(video_id),
                        display=f"YouTube video {video_id}")
    if json:
        return json_response(202, {"job": job.id, "url": f"/api/jobs/{job.id}"})
    return redirect(f"/{details_href(job.id)}")
