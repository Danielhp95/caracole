"""caracole serve's sheet from an audio file: a song's auto sheet, made now from a file uploaded from the library page.

    POST /audio/upload?name=   the file's bytes, one body (``bytes``, ``audio_store.AUDIO_MAX`` at most, the form token
                          in its header), staged in ``state_dir/audio/`` (audio_store.py ``stage``): its id, the
                          name it was sent under, size, format, length and tags, the song its tags or its name
                          name (``guess``, audio_sheet.py ``names_of``), and the library's song of it (``song``: its
                          id, identity, whether it has a human sheet and its link, and the audio it has: "purchase",
                          "youtube", "upload" or null)
    POST /audio           the song's auto sheet from a staged upload (``upload``, its id): a song of the library
                          (``song`` and ``identity``), or one by name (``artist``, ``title``, and optionally
                          ``album`` and ``duration``, else the file's: written to wanted.txt first, as a request
                          is), with ``caracole audio --upload`` queued
    POST /audio/drop      a staged upload deleted now (JSON ``{"upload"}``: the dialog's Cancel)

The job is one ``caracole audio --progress --upload=<id> --song=<display>`` (jobs.py ``audio_sheet_steps``,
audio_sheet.py): the file kept as the song's audio, the lyrics from the lyrics sites, else the words heard from the
file where caracole can transcribe, the chords from the file, the PDF and the viewer. Its key is the song's after
``jobs.AUDIO_SHEET``, so it never joins the song's lookup, nor a lookup it, and one at a time a song: asked again
while one waits or runs, that one is the answer, and the second file staged is let go. Its view is the song's
(/jobs.json's ``kind`` "song"), so the song's line says how it goes, its stages as steps (outcome.py
``AUDIO_STEPS``).

The client never names a path: ``name`` is a name to show, the upload is named by its 16-hex id, checked whole, and
nothing is served back from the folder. A new upload lets go of every earlier one no waiting or running job names
(``jobs.uploads_named``), and one left an hour is swept. Refused, as data to the page's script (``pages.Refused``),
in audio_store.py's words where they are its: a caracole that makes no chords (409, "No sheets from audio files
here: …", ``youtube_fetch.autochords_problem``; neither YouTube nor yt-dlp is needed), a file with no name or no bytes
(400), past the limit (413, unread: server.py), not an audio file caracole reads (415), longer than 30 minutes (422),
no room (507); an upload that isn't staged (400 not an id, 404 gone); a song an audio file's sheet isn't for (409:
ignored, or with a human sheet; a purchase linked or YouTube's audio is no refusal, as the file replaces it, the
owner's decision of 2026-11-25), as the command refuses it again when it runs; and a drop while a job names the
upload (409). Each route holds the store's lock (``audio_store.held``) from what it reads of the queue to what it
changes, so that an upload from another tab never lets go of a file Make sheet is queueing.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from caracole.audio_store import AUDIO_MAX
from caracole.web.app import (
    MAX_BODY,
    Response,
    Route,
    WebApp,
    json_response,
    no_such_song,
    not_ignored,
    query,
    same_song,
    song_id,
)
from caracole.web.jobs import AUDIO_SHEET, audio_sheet_steps, uploads_named
from caracole.web.pages import Refused

if TYPE_CHECKING:
    from caracole.audio_store import AudioError
    from caracole.config import Config
    from caracole.overrides import Overrides
    from caracole.songs import Song

NOT_HERE = "No sheets from audio files here"  # how a refusal begins, where none can be made
WAITS = "That file waits for its sheet: cancel its request in the Journal first."
NOT_NAMED = 'Which upload? {"upload": "<its id>"}, as POST /audio/upload named it.'

ROUTES = (
    Route("POST", "/audio/upload", lambda app, asked, data: upload(app, query(asked), data), body="bytes",
          limit=AUDIO_MAX),
    Route("POST", "/audio", lambda app, asked, form: sheet_from_audio(app, form)),
    Route("POST", "/audio/drop", lambda app, asked, doc: drop(app, doc), body="json", limit=MAX_BODY),
)


def audio_reason(cfg: Config) -> str | None:
    """Why this caracole makes no sheet from an audio file, in a few words (``youtube_fetch.autochords_reason``), or
    None when it does."""
    from caracole.youtube_fetch import autochords_problem, autochords_reason

    problem = autochords_problem(cfg)
    return None if problem is None else autochords_reason(problem)


def _can_make(app: WebApp) -> None:
    reason = audio_reason(app.cfg)
    if reason is not None:
        raise Refused(409, "Not here", f"{NOT_HERE}: {reason}.")


def _refused(e: AudioError, title: str) -> Refused:
    return Refused(e.status, title, str(e))


def upload(app: WebApp, params: dict[str, list[str]], data: bytes) -> Response:
    """``POST /audio/upload``: the file staged, and what it is and names (see the module docstring)."""
    from caracole import audio_store
    from caracole.audio_sheet import names_of
    from caracole.normalize import identity_key
    from caracole.songs import find_song

    _can_make(app)
    try:
        with audio_store.held():  # the uploads jobs name, as they are while this one is staged
            named = uploads_named(app.queue.snapshot())
            audio_store.sweep(app.cfg, named)
            up = audio_store.stage(app.cfg, data, (params.get("name") or [""])[0], named=named)
    except audio_store.AudioError as e:
        raise _refused(e, "Not taken") from None
    except OSError as e:
        raise Refused(503, "Not kept", f"The file couldn't be kept: {e.strerror or e}.") from e
    with app.db() as conn:
        artist, title = names_of(conn, up.name, up.tags)
        song = find_song(conn, identity_key(artist, title)) if artist else None
        shown = _song(app.cfg, conn, song) if song is not None else None
    return json_response(200, {
        "upload": up.id, "name": up.name, "size": up.size, "format": up.format, "duration": up.duration,
        "tags": up.tags, "guess": {"artist": artist or "", "title": title}, "song": shown})


def _song(cfg: Config, conn: sqlite3.Connection, song: Song) -> dict[str, Any]:
    """The library's song of an upload, as the dialog shows it: its human sheet, and the audio the file replaces."""
    from caracole.library_page import sheet_href

    has_sheet = _has_sheet(conn, song)
    return {"id": song.id, "display": song.display, "identity": song.key, "has_sheet": has_sheet,
            "sheet": sheet_href(cfg.library_dir, song) if has_sheet else None, "audio": _audio_of(cfg, conn, song)}


def _has_sheet(conn: sqlite3.Connection, song: Song) -> bool:
    from caracole.songs import HUMAN_SHEET

    return conn.execute("SELECT 1 FROM files WHERE song_id = ? AND name = ?",
                        (song.id, HUMAN_SHEET)).fetchone() is not None


def _audio_of(cfg: Config, conn: sqlite3.Connection, song: Song) -> str | None:
    """The song's audio as its source: a file you gave ("upload"), YouTube's ("youtube"), a purchase linked from
    Music/ ("purchase"), or none."""
    from caracole import audio_store
    from caracole.youtube_fetch import youtube_audio

    if not song.audio_path:
        return None
    if audio_store.uploaded(cfg, song) is not None:
        return "upload"
    return "youtube" if youtube_audio(conn, song) is not None else "purchase"


def audio_is_for(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> None:
    """Refused (409) for a song a sheet from an audio file isn't for: ignored, or with a human sheet, in the words
    ``caracole audio`` refuses it in. Audio of its own (a purchase, YouTube's, a file given before) is no refusal: the
    file replaces it as the song's source."""
    not_ignored(song, overrides)
    if _has_sheet(conn, song):
        raise Refused(409, "Has a sheet", f"{song.display} already has a sheet.")


def sheet_from_audio(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /audio``: a song's auto sheet from the staged upload ``upload``, queued (see the module docstring): the
    song by its id (``song``), else by name, written to wanted.txt first with the file's album and length unless the
    form gives its own."""
    from caracole import audio_store

    _can_make(app)
    # Held from the check to the job queued: an upload from another tab meanwhile would let go of this one.
    with audio_store.held():
        try:
            up = audio_store.staged(app.cfg, form.get("upload", "").strip())
        except audio_store.AudioError as e:
            raise _refused(e, "Not made") from None
        return _queue_sheet(app, form, up)


def _queue_sheet(app: WebApp, form: dict[str, str], up: Any) -> Response:
    """``POST /audio``'s song, refused or written to wanted.txt, and its job queued, for the staged upload ``up``."""
    from caracole import audio_store
    from caracole.normalize import identity_key
    from caracole.songs import find_song, get_song
    from caracole.wanted import format_duration
    from caracole.web.library_routes import wanted_line

    overrides = app.overrides()
    note = ""
    if form.get("song", "").strip():
        asked = song_id(form["song"])
        with no_such_song(), app.db() as conn:
            song = get_song(conn, asked)
            same_song(song, form)
            audio_is_for(conn, song, overrides)
        display, key = song.display, song.key
    else:
        artist, title = form.get("artist", "").strip(), form.get("title", "").strip()
        if artist and title:  # one the library has: refused before its wanted.txt line is touched
            with app.db() as conn:
                known = find_song(conn, identity_key(artist, title))
                if known is not None:
                    audio_is_for(conn, known, overrides)
        fields = dict(form)
        if not fields.get("album", "").strip():
            fields["album"] = up.tags.get("album") or ""
        if not fields.get("duration", "").strip() and up.duration >= 1:
            fields["duration"] = format_duration(round(up.duration * 1000))
        line, note = wanted_line(app, fields)
        display, key = f"{line.artist} - {line.title}", line.identity
    job, new = app.submit(f"Sheet from an audio file: {display}", AUDIO_SHEET + key,
                          audio_sheet_steps(display, up.id), display=display, note=note,
                          full=f"{note} The queue is full: nothing queued. Ask again once it empties.".strip())
    if not new and up.id not in uploads_named(app.queue.snapshot()):  # that job is the answer: this file let go
        try:
            audio_store.drop(app.cfg, up.id)
        except audio_store.AudioError:
            pass
    return app.queued(job)


def drop(app: WebApp, doc: Any) -> Response:
    """``POST /audio/drop``: the staged upload ``upload`` names deleted now (``audio_store.drop``); 409 while a job
    names it, 404 for none, 400 for no id."""
    from caracole import audio_store

    upload_id = doc.get("upload") if isinstance(doc, dict) else None
    if not isinstance(upload_id, str):
        raise Refused(400, "Not dropped", NOT_NAMED)
    with audio_store.held():  # no job queued for it between the check and the drop
        if upload_id in uploads_named(app.queue.snapshot()):
            raise Refused(409, "Not dropped", WAITS)
        try:
            audio_store.drop(app.cfg, upload_id)
        except audio_store.AudioError as e:
            raise _refused(e, "Not dropped") from None
    return json_response(200, {"dropped": upload_id})
