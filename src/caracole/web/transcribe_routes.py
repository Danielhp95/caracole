"""caracole serve's lyrics transcribed from a song's audio: a song with audio of its own that every lyrics site missed, its words heard
from the audio now, and its auto sheet made again over them.

    POST /transcribe      a song's lyrics transcribed from its audio (``song``, its id, and its ``identity``: its
                          card's, or its request's in the Requests tab, Transcribe the lyrics), with ``caracole
                          transcribe`` queued; ``force=1``, the card's Transcribe anyway (``--force``), ``none=1``,
                          its Not sung: chords only (``--none``)
    GET  /transcribe      what the library page offers, for its script alone (as /jobs.json is asked): the served
                          page's ``server.transcribe`` as it would be built now (library_page.py
                          ``transcribe_member``: ``ok``, ``why``, ``songs``, ``nothing``, ``transcribed``,
                          ``time``), which the page reads again
                          once a song's job ends, so a song a sheet from a video left without lyrics is offered at
                          once, with no reload

The job is one ``caracole transcribe --progress`` (jobs.py ``transcribe_steps``, transcribe_job.py): where the
singing is (demucs-rs), the words (Whisper), the chords over them, the PDF and the viewer. Its key is the song's after
``jobs.TRANSCRIBE``, so it never joins the song's lookup, nor a lookup it, and one at a time a song: asked again while
one waits or runs, that one is the answer. It is the queue's, never the lookups' lane's, so two songs' run one after
the other, each under caracole's lock. Its view is the song's (/jobs.json's ``kind`` "song"), so the song's line says
how it goes, its stages as steps (outcome.py ``TRANSCRIBE_STEPS``).

Refused, with nothing queued (``pages.Refused``): a caracole that transcribes nothing
(``youtube_fetch.transcribe_reason``, 409, in its words: no auto-chords, no Whisper, a model file or demucs-rs
missing, a CUDA build without its GPU, as the library page then offers it on no card), and a song not offered a transcription (409, in
``transcript.why_not_offered``'s words: it has no audio, a lyrics site has its lyrics or hasn't been
asked, it was transcribed already…; with ``force``, as ``why_not_offered(anyway=True)`` says, nothing sung passed
over; with ``none``, ``transcript.why_not_unsung``'s: a song with no transcript of its audio), as the command refuses
it again when it runs (the library may change while it waits); both ``force`` and ``none``, 400.
"""

from __future__ import annotations

from caracole.web.app import Response, Route, WebApp, json_response, no_such_song, same_song, song_id
from caracole.web.jobs import TRANSCRIBE, transcribe_steps
from caracole.web.pages import Refused

NOT_HERE = "No lyrics transcribed here"  # how a refusal begins, where none can be

ROUTES = (
    Route("POST", "/transcribe", lambda app, asked, form: transcribe_song(app, form)),
    Route("GET", "/transcribe", lambda app, asked: offered(app), script_only=True),
)


def offered(app: WebApp) -> Response:
    """The library page's ``server.transcribe`` as of now (``library_page.transcribe_member``), read-only."""
    from caracole.library_page import transcribe_member

    overrides = app.overrides(" Fix it, then reload this page.")
    with app.db() as conn:
        return json_response(200, transcribe_member(conn, app.cfg, overrides))


def transcribe_song(app: WebApp, form: dict[str, str]) -> Response:
    """A song's lyrics transcribed from its audio, queued (see the module docstring): the song by its id (``song``),
    the one its ``identity`` names; ``force`` or ``none``, the owner's word over caracole's."""
    from caracole.autochords.transcript import refused_for, why_not_offered, why_not_unsung
    from caracole.songs import get_song
    from caracole.youtube_fetch import transcribe_reason

    problem = transcribe_reason(app.cfg)
    if problem is not None:
        raise Refused(409, "Not here", f"{NOT_HERE}: {problem}.")
    force, none = form.get("force") == "1", form.get("none") == "1"
    if force and none:
        raise Refused(400, "Not understood", "Transcribe anyway and Not sung say opposite things: nothing queued.")
    overrides = app.overrides()
    asked = song_id(form.get("song", ""))
    with no_such_song(), app.db() as conn:
        song = get_song(conn, asked)
        same_song(song, form)
        if none:
            why = why_not_unsung(conn, app.cfg, song, overrides)
        else:
            why = why_not_offered(conn, app.cfg, song, overrides, anyway=force)
    if why is not None and none:
        raise Refused(409, "Not offered", f"{song.display} can't be said not sung: {why}.")
    if why is not None:
        raise Refused(409, "Not offered", f"{song.display} isn't offered a transcription: {refused_for(why)}.")
    display = song.display
    title = f"Not sung, chords only: {display}" if none else f"Lyrics from the audio: {display}"
    job, _ = app.submit(title, TRANSCRIBE + song.key, transcribe_steps(display, force=force, none=none),
                        display=display,
                        full="The queue is full: nothing queued. Ask again once it empties.")
    return app.queued(job)
