"""caracole/web/transcribe_routes.py: a song's lyrics transcribed from its audio, asked for from the library page.

The route queues ``caracole transcribe --song --progress`` (transcribe_job.py, tested in test_transcribe_job.py);
here the queue records the commands, and nothing runs. "Able" is a caracole that transcribes
(``youtube_fetch.transcribe_problem`` says nothing against it: Whisper, its models and demucs-rs taken to be there).
A song offered a transcription is one whose audio came from YouTube and every lyrics site missed
(test_autochords_transcript.py's ``youtube_song``).
"""

import json
import re
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from conftest import add_song
from test_autochords_transcript import youtube_song

import caracole.youtube_fetch as yf
from caracole.songs import update_song
from caracole.transcribe_job import STAGES
from caracole.web.app import Request, WebApp
from caracole.web.jobs import LANE, TRANSCRIBE, JobQueue, ahead, lookup_steps, transcribe_steps

HOST = "localhost:8737"
JSON_BLOCK = re.compile(r'<script type="application/json" id="songs">(.*?)</script>', re.S)
ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        return 0


@pytest.fixture
def able(cfg, monkeypatch):
    """A config this caracole transcribes with."""
    monkeypatch.setattr(yf, "transcribe_problem", lambda cfg: None)
    return cfg


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=3)


def app_for(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def post(app, fields, **headers):
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}", "accept": "application/json"} | headers
    return app.handle(Request("POST", "/transcribe", sent, urlencode({"csrf": "tok"} | fields).encode("utf-8")))


def answer(response):
    return json.loads(response.body)


def offers(app, **headers):
    """GET /transcribe as the page's script asks it: its own origin, the form token in a header."""
    sent = {"host": HOST, "accept": "application/json", "sec-fetch-site": "same-origin",
            "x-caracole-form-token": "tok"} | headers
    return app.handle(Request("GET", "/transcribe", {k: v for k, v in sent.items() if v is not None}))


# --- queued ---------------------------------------------------------------------------------------------


def test_an_offered_song_queues_one_caracole_transcribe(able, queue, conn, tmp_path):
    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    response = post(app_for(able, queue), {"song": str(song.id), "identity": song.key})
    assert response.status == 200, response.body
    view = answer(response)["job"]
    assert (view["kind"], view["songId"], view["identity"]) == ("song", song.id, song.key)
    assert view["line"] == {"tone": "queued", "text": "Queued…", "link": None, "details": None}
    [job] = queue.snapshot()
    assert job.song_key == TRANSCRIBE + song.key and job.display == "Nick Cani - Vikingos veganos"
    assert job.title == "Lyrics from the audio: Nick Cani - Vikingos veganos"
    assert [(s.label, s.args) for s in job.steps] == transcribe_steps("Nick Cani - Vikingos veganos")
    assert [s.name for s in job.stages] == [name for name, _ in STAGES] and job.transcribes
    queue.run_pending()
    assert queue._runner.calls == [["transcribe", "--progress", "--song=Nick Cani - Vikingos veganos"]]


def test_without_the_pages_script_it_goes_to_its_request_in_the_requests_tab(able, queue, conn, tmp_path):
    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    response = post(app_for(able, queue), {"song": str(song.id)}, accept="text/html")
    [job] = queue.snapshot()
    assert response.status == 303 and dict(response.headers)["Location"] == f"/#tab=requests&job={job.id}"


def test_asked_again_while_it_waits_the_one_waiting_is_the_answer(able, queue, conn, tmp_path):
    # The owner pressing Transcribe twice: one job a song, the second press answered with the first job, while it
    # waits and while it runs.
    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    app = app_for(able, queue)
    first = answer(post(app, {"song": str(song.id), "identity": song.key}))
    again = answer(post(app, {"song": str(song.id), "identity": song.key}))
    assert first["job"]["id"] == again["job"]["id"] and len(queue.snapshot()) == 1
    with queue._lock:
        queue._jobs[0].state = "running"
    running = answer(post(app, {"song": str(song.id), "identity": song.key}))
    assert running["job"]["id"] == first["job"]["id"] and len(queue.snapshot()) == 1


def test_two_songs_asked_at_once_queue_one_after_the_other(able, conn, tmp_path):
    # Transcribe on two songs: a job each, both the queue's (never the lookups' lane, which runs beside it), the
    # second waiting for the first; each takes caracole's lock as asked for now when it runs (test_commands_lock.py).
    queue = JobQueue(Recorder(), lane=LANE)
    app = app_for(able, queue)
    one = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    two = youtube_song(conn, tmp_path, "Estopa", "Como Camarón")
    first = answer(post(app, {"song": str(one.id), "identity": one.key}))["job"]
    second = answer(post(app, {"song": str(two.id), "identity": two.key}))["job"]
    assert first["id"] != second["id"]
    assert second["line"]["text"] == "Queued · 1 request ahead…"
    jobs = queue.snapshot()
    later = next(j for j in jobs if j.id == second["id"])
    assert [j.lane for j in jobs] == [False, False] and ahead(jobs, later) == 1
    queue.run_pending()
    assert queue._runner.calls == [["transcribe", "--progress", "--song=Nick Cani - Vikingos veganos"],
                                   ["transcribe", "--progress", "--song=Estopa - Como Camarón"]]


def test_a_transcription_never_joins_the_songs_lookup_nor_a_lookup_it(able, queue, conn, tmp_path):
    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    app = app_for(able, queue)
    lookup, _ = queue.submit("Fetch Nick Cani - Vikingos veganos", song.key,
                             lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)
    asked = answer(post(app, {"song": str(song.id), "identity": song.key}))["job"]
    assert asked["id"] != lookup.id and len(queue.snapshot()) == 2
    after, new = queue.submit("Fetch Nick Cani - Vikingos veganos", song.key,
                              lookup_steps("Nick Cani", "Vikingos veganos"), fetching=True)
    assert not new and after.id == lookup.id
    [transcription] = [j for j in queue.snapshot() if j.song_key.startswith(TRANSCRIBE)]
    assert [s.args[0] for s in transcription.steps] == ["transcribe"]


# --- refused, nothing queued -----------------------------------------------------------------------------------


def test_where_it_cant_run_it_says_why_and_queues_nothing(cfg, queue, conn, tmp_path, monkeypatch):
    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    response = post(app_for(cfg, queue), {"song": str(song.id), "identity": song.key})
    assert response.status == 409
    assert answer(response)["error"] == "No lyrics transcribed here: auto-chords isn't installed."
    monkeypatch.setattr(yf, "transcribe_problem", lambda cfg: "built without Whisper")
    response = post(app_for(cfg, queue), {"song": str(song.id), "identity": song.key})
    assert response.status == 409
    assert answer(response)["error"] == "No lyrics transcribed here: Whisper isn't installed."
    assert queue.snapshot() == []


def test_a_song_not_offered_is_refused_with_its_reason(able, queue, conn, tmp_path):
    found = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos", lyrics_status="found")
    response = post(app_for(able, queue), {"song": str(found.id), "identity": found.key})
    assert response.status == 409
    assert answer(response)["error"] == ("Nick Cani - Vikingos veganos isn't offered a transcription: its lyrics are "
                                         "found.")
    bought = add_song(conn, "Estopa", "Como Camarón")
    response = post(app_for(able, queue), {"song": str(bought.id), "identity": bought.key})
    assert response.status == 409
    assert answer(response)["error"] == ("Estopa - Como Camarón isn't offered a transcription: it has no audio.")
    assert queue.snapshot() == []


def test_a_purchases_song_is_accepted_once_offered(able, queue, conn, tmp_path):
    song = youtube_song(conn, tmp_path, "Estopa", "Como Camarón")
    conn.execute("DELETE FROM kv WHERE key = ?", (f"youtube:{song.id}",))  # a purchase: audio, no YouTube record
    response = post(app_for(able, queue), {"song": str(song.id), "identity": song.key})
    assert response.status == 200, response.body
    assert len(queue.snapshot()) == 1


def test_a_song_the_library_hasnt_or_another_by_its_id_is_refused(able, queue, conn, tmp_path):
    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    app = app_for(able, queue)
    assert post(app, {"song": "41"}).status == 404
    assert post(app, {"song": "x"}).status == 400
    other = post(app, {"song": str(song.id), "identity": "estopa/como camaron"})  # the page knew another by this id
    assert other.status == 409 and queue.snapshot() == []
    update_song(conn, song.id, status="ignored")
    ignored = post(app, {"song": str(song.id), "identity": song.key})
    assert ignored.status == 409 and queue.snapshot() == []


# --- the offer, read again by the page ------------------------------------------------------------------------------


def test_the_page_reads_the_offer_again_as_the_served_page_has_it(able, queue, conn, tmp_path, monkeypatch):
    # GET /transcribe answers the served page's server.transcribe member, built by the one function the page is
    # built with: a song that became due since the page loaded (a sheet from YouTube that found no lyrics) is in
    # it at once, and one transcribed since is gone.
    from caracole.autochords.transcript import Transcript, keep_transcript
    from caracole.library_page import WebControls, build_library_page
    from caracole.overrides import Overrides
    from caracole.songs import get_song

    monkeypatch.delenv("CARACOLE_TORCH_CUDA", raising=False)
    app = app_for(able, queue)
    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos", lyrics_status="pending", lyrics_at=None)
    response = offers(app)
    assert response.status == 200
    assert dict(response.headers)["Content-Type"] == "application/json; charset=utf-8"
    assert dict(response.headers)["Cache-Control"] == "no-store"
    assert answer(response) == {"ok": True, "why": None, "songs": [], "nothing": [], "unsung": [], "transcribed": [],
                                "time": "up to half an hour", "hears": True}
    update_song(conn, song.id, lyrics_status="missing", lyrics_at="2026-11-21T00:00:00Z")  # every site missed it
    assert answer(offers(app))["songs"] == [song.id]
    html = build_library_page(conn, able, Overrides(), datetime.now(UTC), controls=WebControls(csrf="tok"))
    assert json.loads(JSON_BLOCK.search(html).group(1))["server"]["transcribe"] == answer(offers(app))
    song = get_song(conn, song.id)
    keep_transcript(conn, song, Transcript(lrc="[00:01.00]hola\n", audio=song.audio_path,
                                           audio_mtime=song.audio_mtime, model="whisper-large-v3", language="es",
                                           device="cpu", words_dropped=0, made_at="2026-11-21T00:00:00Z"))
    assert answer(offers(app))["songs"] == []  # transcribed meanwhile (the command, from a terminal)


def test_where_it_cant_run_the_offer_says_why_and_offers_no_song(cfg, queue, conn, tmp_path, monkeypatch):
    youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    monkeypatch.setattr(yf, "transcribe_problem", lambda cfg: "built without Whisper")
    assert answer(offers(app_for(cfg, queue))) == {"ok": False, "why": "Whisper isn't installed", "songs": [],
                                                   "nothing": [], "unsung": [], "transcribed": [], "time": "", "hears": False}


def test_the_offer_is_read_by_the_pages_script_alone(able, queue, conn):
    app = app_for(able, queue)
    assert offers(app, **{"sec-fetch-site": "cross-site"}).status == 403  # another site's fetch
    assert offers(app, **{"x-caracole-form-token": None}).status == 403  # no form token: not the page's script
    assert offers(app, **{"x-caracole-form-token": "old"}).status == 403  # a page of a server before this one
    assert queue.snapshot() == []


# --- the owner's word over caracole's: Transcribe anyway, Not sung ------------------------------------------------


def heard_nothing_song(conn, tmp_path, artist="Nick Cani", title="Vikingos veganos"):
    from caracole.autochords.transcript import note_heard_nothing

    song = youtube_song(conn, tmp_path, artist, title)
    note_heard_nothing(conn, song, "2026-11-21T00:00:00Z", why="sung 6.2 s", by="caracole")
    return song


def transcribed_song(conn, tmp_path, artist="Estopa", title="Como Camarón"):
    from test_autochords_transcript import made

    from caracole.autochords.transcript import keep_transcript

    song = youtube_song(conn, tmp_path, artist, title)
    keep_transcript(conn, song, made(song))
    return song


def test_transcribe_anyway_queues_caracole_transcribe_force(able, queue, conn, tmp_path):
    song = heard_nothing_song(conn, tmp_path)
    app = app_for(able, queue)
    refused = post(app, {"song": str(song.id), "identity": song.key})  # not offered as it is: nothing sung
    assert refused.status == 409 and "nothing sung was heard" in answer(refused)["error"]
    response = post(app, {"song": str(song.id), "identity": song.key, "force": "1"})
    assert response.status == 200, response.body
    [job] = queue.snapshot()
    assert job.title == "Lyrics from the audio: Nick Cani - Vikingos veganos"
    assert [(s.label, s.args) for s in job.steps] == transcribe_steps(song.display, force=True)
    queue.run_pending()
    assert queue._runner.calls == [["transcribe", "--progress", "--force", "--song=Nick Cani - Vikingos veganos"]]


def test_not_sung_queues_caracole_transcribe_none(able, queue, conn, tmp_path):
    song = transcribed_song(conn, tmp_path)
    response = post(app_for(able, queue), {"song": str(song.id), "identity": song.key, "none": "1"})
    assert response.status == 200, response.body
    [job] = queue.snapshot()
    assert job.song_key == TRANSCRIBE + song.key and job.title == "Not sung, chords only: Estopa - Como Camarón"
    assert [s.name for s in job.stages] == [name for name, _ in STAGES] and job.transcribes
    queue.run_pending()
    assert queue._runner.calls == [["transcribe", "--progress", "--none", "--song=Estopa - Como Camarón"]]


def test_the_owners_word_is_refused_for_a_song_neither_applies_to(able, queue, conn, tmp_path):
    app = app_for(able, queue)
    found = youtube_song(conn, tmp_path, "Radiohead", "Creep", lyrics_status="found")
    offered_now = youtube_song(conn, tmp_path, "Soda Stereo", "Persiana americana")
    for song, field, said in (
            (found, "force", "Radiohead - Creep isn't offered a transcription: its lyrics are found."),
            (found, "none", "Radiohead - Creep can't be said not sung: its lyrics are found."),
            (offered_now, "none", "Soda Stereo - Persiana americana can't be said not sung: it has no transcript.")):
        response = post(app, {"song": str(song.id), "identity": song.key, field: "1"})
        assert (response.status, answer(response)["error"]) == (409, said)
    both = post(app, {"song": str(offered_now.id), "identity": offered_now.key, "force": "1", "none": "1"})
    assert both.status == 400
    assert queue.snapshot() == []


def test_the_offer_names_the_songs_heard_to_have_nothing_and_those_transcribed(able, queue, conn, tmp_path,
                                                                               monkeypatch):
    # Transcribe anyway's songs told apart by whose word it is: caracole's (``nothing``) or the owner's (``unsung``).
    from caracole.autochords.transcript import drop_transcript

    monkeypatch.delenv("CARACOLE_TORCH_CUDA", raising=False)
    nothing = heard_nothing_song(conn, tmp_path)
    transcribed = transcribed_song(conn, tmp_path)
    marked = transcribed_song(conn, tmp_path, "Estopa", "Vino tinto")
    drop_transcript(conn, marked, "2026-11-21T00:00:00Z")
    offered_now = youtube_song(conn, tmp_path, "Soda Stereo", "Persiana americana")
    youtube_song(conn, tmp_path, "Radiohead", "Creep", lyrics_status="found")  # a site's lyrics: none of the three
    assert answer(offers(app_for(able, queue))) == {
        "ok": True, "why": None, "songs": [offered_now.id], "nothing": [nothing.id], "unsung": [marked.id],
        "transcribed": [transcribed.id], "time": "up to half an hour", "hears": True}


def test_whisper_cant_read_its_audio_says_what_to_do_and_force_tries_it_again(able, queue, conn, tmp_path):
    from caracole.autochords.transcript import note_whisper_cant_read

    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    note_whisper_cant_read(conn, song, "2026-11-21T00:00:00Z", "RuntimeError: Failed to load audio")
    app = app_for(able, queue)
    refused = post(app, {"song": str(song.id), "identity": song.key})
    assert (refused.status, answer(refused)["error"]) == (409, (
        "Nick Cani - Vikingos veganos isn't offered a transcription: Whisper can't read its audio (a new file, or "
        "another video under [youtube], gets its words heard; after an ffmpeg or Whisper upgrade, caracole "
        "transcribe --force tries it again)."))
    assert answer(offers(app))["nothing"] == []  # the card offers no Transcribe anyway for it: that is by hand
    assert post(app, {"song": str(song.id), "identity": song.key, "force": "1"}).status == 200


def test_force_on_a_song_offered_a_transcription_simply_transcribes_it(able, queue, conn, tmp_path):
    # Forcing what is offered anyway is harmless: accepted, queued with --force.
    song = youtube_song(conn, tmp_path, "Nick Cani", "Vikingos veganos")
    response = post(app_for(able, queue), {"song": str(song.id), "identity": song.key, "force": "1"})
    assert response.status == 200, response.body
    queue.run_pending()
    assert queue._runner.calls == [["transcribe", "--progress", "--force", "--song=Nick Cani - Vikingos veganos"]]
