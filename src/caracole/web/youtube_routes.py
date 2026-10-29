"""caracole serve's sheet from a YouTube video: a song's auto sheet, made now from the video you paste.

    POST /youtube         a song's auto sheet from the YouTube video ``youtube`` names: a song of the library
                          (``song``, its id: its card's Sheet from a YouTube video), or one by name (``artist``,
                          ``title``, and optionally ``album`` and ``duration``: written to wanted.txt first, as a
                          request is), with ``caracole youtube --sheet`` queued

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

from typing import TYPE_CHECKING

from caracole.web.app import Response, Route, WebApp, no_such_song, not_ignored, song_id
from caracole.web.jobs import YOUTUBE_SHEET, youtube_sheet_steps
from caracole.web.pages import Refused

if TYPE_CHECKING:
    import sqlite3

    from caracole.overrides import Overrides
    from caracole.songs import Song

VIDEO_LIMIT = 600  # characters of a pasted address
NOT_HERE = "No sheets from YouTube here"  # how the page and a refusal begin, where none can be made

ROUTES = (Route("POST", "/youtube", lambda app, asked, form: sheet_from_youtube(app, form)),)


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
