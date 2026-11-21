"""caracole/web/transcribe_routes.py: a song's lyrics transcribed from its audio, asked for from the library page.

The route queues ``caracole transcribe --song --progress`` (transcribe_job.py, tested in test_transcribe_job.py);
here the queue records the commands, and nothing runs. "Able" is a caracole that transcribes
(``youtube_fetch.transcribe_problem`` says nothing against it: Whisper, its models and demucs-rs taken to be there).
A song offered a transcription is one whose audio came from YouTube and every lyrics site missed
(test_autochords_transcript.py's ``youtube_song``).
"""

import json
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
    assert answer(response)["error"] == ("Estopa - Como Camarón isn't offered a transcription: its audio isn't from "
                                         "YouTube.")
    assert queue.snapshot() == []


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
