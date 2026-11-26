"""caracole/web/audio_routes.py: an audio file uploaded from the library page, and its song's sheet queued.

The routes stage the file (audio_store.py, tested in test_audio_store.py) and queue ``caracole audio --upload``
(audio_sheet.py, tested in test_audio_sheet.py); here the queue records the commands, and nothing runs. "Able" is a
caracole that can make chords of audio: auto-chords' packages taken to be there, and its model files; no yt-dlp.
"""

import http.client
import json
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import quote, urlencode

import pytest
from conftest import add_song
from helpers.audio_files import audio, given, write
from test_peer_push import Served
from test_web_youtube import keep_human_sheet

import caracole.youtube_fetch as yf
from caracole import audio_store
from caracole.config import AutochordsConfig
from caracole.normalize import identity_key
from caracole.songs import update_song
from caracole.web.app import Request, WebApp
from caracole.web.jobs import AUDIO_SHEET, JobQueue, audio_sheet_steps

HOST = "localhost:8737"
ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})
BYTES = "application/octet-stream"
NICK = ("Nick Cani", "Vikingos veganos")


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        return 0


@pytest.fixture(autouse=True)
def room(monkeypatch):
    """Room on the disk for every file staged (audio_store's ``ROOM`` is a GiB)."""
    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**15, used=0, free=10**15))


@pytest.fixture
def able(cfg, tmp_path, monkeypatch):
    """A config this caracole can make chords of audio with: no yt-dlp is needed."""
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    return replace(cfg, ytdlp_bin=str(tmp_path / "no-yt-dlp-here"), autochords=AutochordsConfig(**files))


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=3)


def app_for(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def upload(app, data: bytes, name: str = "vikingos.mp3", **headers):
    """``POST /audio/upload`` as the page's script sends it: the file's bytes, the form token in its header."""
    sent = {"host": HOST, "content-type": BYTES, "sec-fetch-site": "same-origin", "origin": f"http://{HOST}",
            "accept": "application/json", "x-caracole-form-token": "tok"} | headers
    sent = {k: v for k, v in sent.items() if v is not None}
    return app.handle(Request("POST", f"/audio/upload?name={quote(name)}", sent, data))


def post(app, fields, **headers):
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}", "accept": "application/json"} | headers
    return app.handle(Request("POST", "/audio", sent, urlencode({"csrf": "tok"} | fields).encode("utf-8")))


def drop(app, doc):
    sent = {"host": HOST, "content-type": "application/json", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}", "accept": "application/json", "x-caracole-form-token": "tok"}
    return app.handle(Request("POST", "/audio/drop", sent, json.dumps(doc).encode()))


def answer(response):
    return json.loads(response.body)


def staged_ids(cfg) -> set[str]:
    folder = cfg.state_dir / "audio"
    return {p.name[len(".upload-"):][:16] for p in folder.iterdir()
            if p.name.startswith(".upload-")} if folder.exists() else set()


def tagged(tmp_path, fmt="MP3", **tags) -> bytes:
    return write(tmp_path / "made" / f"x.{fmt.lower()}", fmt, 198.2, **tags).read_bytes()


# --- the upload -------------------------------------------------------------------------------------------------


def test_an_upload_needs_the_form_token_and_is_refused_unread_past_the_limit(able, queue, tmp_path):
    app = app_for(able, queue)
    data = audio("MP3", 10.0)
    response = upload(app, data, **{"x-caracole-form-token": None})
    assert response.status == 403 and answer(response)["reload"] is True
    assert upload(app, data, origin="http://evil.example", **{"sec-fetch-site": "cross-site"}).status == 403
    assert upload(app, data, **{"content-type": "audio/mpeg"}).status == 415  # a bytes route's kind alone
    assert staged_ids(able) == set()
    serving = Served(app)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", serving.server.server_address[1], timeout=10)
        try:  # 128 MiB and a byte, claimed: answered at once, unread
            conn.putrequest("POST", "/audio/upload?name=big.wav")
            conn.putheader("Content-Type", BYTES)
            conn.putheader("X-Caracole-Form-Token", "tok")
            conn.putheader("Content-Length", str(audio_store.AUDIO_MAX + 1))
            conn.endheaders()
            assert conn.getresponse().status == 413
        finally:
            conn.close()
        status, _, body = serving.ask("POST", "/audio/upload?name=vikingos.mp3", data, kind=BYTES)
        assert status == 200, body
    finally:
        serving.close()
    assert len(staged_ids(able)) == 1


def test_an_upload_of_a_non_audio_file_is_415(able, queue):
    app = app_for(able, queue)
    for data in (b"<html>not a song</html>", b"ID3" + b"\0" * 200):  # a page; an ID3 tag over nothing
        response = upload(app, data, "song.mp3")
        assert response.status == 415, response.body
        assert answer(response) == {"error": audio_store.NOT_AUDIO}
    assert upload(app, b"", "song.mp3").status == 400
    response = upload(app, audio("MP3", 1.0), "")
    assert response.status == 400 and answer(response) == {"error": audio_store.NO_NAME}
    assert staged_ids(able) == set()


def test_a_file_longer_than_30_minutes_or_with_no_room_is_refused_as_data(able, queue, monkeypatch):
    app = app_for(able, queue)
    response = upload(app, audio("WAV", audio_store.MAX_SECONDS + 1), "long.wav")
    assert response.status == 422 and answer(response) == {"error": audio_store.TOO_LONG}
    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**9, used=0, free=10**6))
    response = upload(app, audio("MP3", 1.0))
    assert response.status == 507 and answer(response) == {"error": audio_store.NO_ROOM}


def test_an_upload_answers_its_guess_and_the_librarys_song(able, queue, conn, tmp_path):
    app = app_for(able, queue)
    data = tagged(tmp_path, artist="Nick Cani", title="Vikingos veganos (Official Audio)", album="Pruebas")
    response = upload(app, data, "../../etc/03 whatever.mp3")
    assert response.status == 200, response.body
    said = answer(response)
    assert len(said["upload"]) == 16 and said["upload"] in staged_ids(able)
    assert said["name"] == "03 whatever.mp3"  # a name to show, never a path
    assert (said["size"], said["format"]) == (len(data), "MP3") and abs(said["duration"] - 198.2) < 1  # MP3's frames
    assert said["tags"] == {"artist": "Nick Cani", "title": "Vikingos veganos (Official Audio)", "album": "Pruebas"}
    assert said["guess"] == {"artist": "Nick Cani", "title": "Vikingos veganos"}
    assert said["song"] is None  # not in the library

    song = add_song(conn, *NICK)
    said = answer(upload(app, data))
    assert said["song"] == {"id": song.id, "display": "Nick Cani - Vikingos veganos", "identity": song.key,
                            "has_sheet": False, "sheet": None, "audio": None}
    given(conn, able.state_dir, song)  # a file given before
    assert answer(upload(app, data))["song"]["audio"] == "upload"
    bought = tmp_path / "Music" / "vikingos.flac"
    bought.parent.mkdir()
    bought.write_bytes(audio("FLAC"))
    update_song(conn, song.id, audio_path=str(bought), audio_mtime=bought.stat().st_mtime)
    assert answer(upload(app, data))["song"]["audio"] == "purchase"  # the file will replace it
    keep_human_sheet(conn, able, song)
    shown = answer(upload(app, data))["song"]
    assert shown["has_sheet"] is True and shown["sheet"].startswith("Nick%20Cani/Vikingos%20veganos/sheet.")

    # No tags: the file's own name, less its track number, read as a query is.
    said = answer(upload(app, audio("WAV", 2.0), "07 - Nick Cani - Vikingos veganos.wav"))
    assert said["guess"] == {"artist": "Nick Cani", "title": "Vikingos veganos"} and said["song"]["id"] == song.id
    said = answer(upload(app, audio("WAV", 2.0), "07 Vikingos.wav"))
    assert said["guess"] == {"artist": "", "title": "Vikingos"} and said["song"] is None


def test_a_new_upload_lets_go_of_an_earlier_one_no_job_names(able, queue):
    app = app_for(able, queue)
    first = answer(upload(app, audio("MP3")))["upload"]
    second = answer(upload(app, audio("MP3")))["upload"]
    assert staged_ids(able) == {second} and first != second
    post(app, {"upload": second, "artist": NICK[0], "title": NICK[1]})
    third = answer(upload(app, audio("MP3")))["upload"]
    assert staged_ids(able) == {second, third}  # the one a waiting job names stays


# --- the sheet --------------------------------------------------------------------------------------------------


def test_make_sheet_queues_one_job_by_id_never_by_path(able, queue, conn):
    app = app_for(able, queue)
    up = answer(upload(app, audio("MP3", 198.0), "song.mp3"))["upload"]
    response = post(app, {"upload": up, "artist": NICK[0], "title": NICK[1]})
    assert response.status == 200, response.body
    view = answer(response)["job"]
    assert view["kind"] == "song" and view["line"]["text"] == "Queued…"
    [job] = queue.snapshot()
    assert job.song_key == AUDIO_SHEET + identity_key(*NICK) and job.display == "Nick Cani - Vikingos veganos"
    assert job.title == "Sheet from an audio file: Nick Cani - Vikingos veganos"
    assert [(s.label, s.args) for s in job.steps] == audio_sheet_steps("Nick Cani - Vikingos veganos", up)
    assert job.steps[0].args == ("audio", "--progress", f"--upload={up}", "--song=Nick Cani - Vikingos veganos")
    assert not any(str(able.state_dir) in arg for arg in job.steps[0].args)
    assert job.from_audio and not job.lane
    assert [s.name for s in job.stages] == ["song", "audio", "lyrics", "vocals", "words", "chords", "pdf", "pages"]
    # A new song's line written first, with the file's length (and its album, when it has one).
    assert "Nick Cani - Vikingos veganos | 3:18" in able.wanted_file.read_text(encoding="utf-8")
    queue.run_pending()
    assert queue._runner.calls == [list(job.steps[0].args)]

    # A song of the library, by its id and identity; a purchase linked is no refusal.
    song = add_song(conn, "Nick Cani", "Otra")
    update_song(conn, song.id, audio_path="/music/otra.mp3", audio_mtime=1.0)
    up = answer(upload(app, audio("MP3")))["upload"]
    response = post(app, {"upload": up, "song": str(song.id), "identity": song.key})
    assert response.status == 200, response.body
    assert queue.snapshot()[0].steps[0].args == ("audio", "--progress", f"--upload={up}", "--song=Nick Cani - Otra")
    assert post(app, {"upload": up, "song": str(song.id), "identity": "someone/else"}).status == 409


@pytest.mark.parametrize("upload_id,status", [("", 400), ("../../etc/passwd", 400), ("0123456789abcdef", 404)])
def test_an_upload_that_isnt_staged_is_refused(able, queue, upload_id, status):
    response = post(app_for(able, queue), {"upload": upload_id, "artist": NICK[0], "title": NICK[1]})
    assert response.status == status and "error" in answer(response)
    assert queue.snapshot() == [] and not able.wanted_file.exists()


def test_an_ignored_song_or_one_with_a_sheet_is_refused(able, queue, conn):
    app = app_for(able, queue)
    song = add_song(conn, *NICK)
    keep_human_sheet(conn, able, song)
    up = answer(upload(app, audio("MP3")))["upload"]
    for fields in ({"song": str(song.id)}, {"artist": NICK[0], "title": NICK[1]}):
        response = post(app, {"upload": up} | fields)
        assert response.status == 409 and answer(response) == {"error": f"{song.display} already has a sheet."}
    other = add_song(conn, "Nick Cani", "Ignorada")
    able.overrides_file.write_text('[ignore]\nsongs = ["Nick Cani - Ignorada"]\n', encoding="utf-8")
    response = post(app, {"upload": up, "song": str(other.id)})
    assert response.status == 409 and "ignored" in answer(response)["error"]
    assert queue.snapshot() == []


def test_a_second_ask_while_one_waits_is_that_one(able, queue):
    app = app_for(able, queue)
    first = answer(upload(app, audio("MP3")))["upload"]
    one = answer(post(app, {"upload": first, "artist": NICK[0], "title": NICK[1]}))["job"]
    second = answer(upload(app, audio("WAV")))["upload"]
    again = answer(post(app, {"upload": second, "artist": NICK[0], "title": NICK[1]}))["job"]
    assert again["id"] == one["id"] and len(queue.snapshot()) == 1
    assert staged_ids(able) == {first}  # the second file let go
    assert queue.snapshot()[0].steps[0].args[2] == f"--upload={first}"


def test_drop_deletes_it_unless_a_job_names_it(able, queue):
    app = app_for(able, queue)
    up = answer(upload(app, audio("MP3")))["upload"]
    response = drop(app, {"upload": up})
    assert response.status == 200 and answer(response) == {"dropped": up}
    assert staged_ids(able) == set()
    assert drop(app, {"upload": up}).status == 404
    assert drop(app, {"upload": "../x"}).status == 400
    assert drop(app, {"nothing": 1}).status == 400
    up = answer(upload(app, audio("MP3")))["upload"]
    post(app, {"upload": up, "artist": NICK[0], "title": NICK[1]})
    response = drop(app, {"upload": up})
    assert response.status == 409 and "error" in answer(response)
    assert staged_ids(able) == {up}


def test_no_auto_chords_is_409(cfg, queue, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    app = app_for(cfg, queue)
    response = upload(app, audio("MP3"))
    assert response.status == 409
    assert answer(response) == {"error": "No sheets from audio files here: auto-chords isn't installed."}
    assert staged_ids(cfg) == set()
    response = post(app, {"upload": "0123456789abcdef", "artist": NICK[0], "title": NICK[1]})
    assert response.status == 409 and queue.snapshot() == []


def test_an_upload_from_another_tab_while_make_sheet_queues_never_lets_go_of_its_file(able, queue, monkeypatch):
    # Make sheet checks the upload is staged, then queues it: a second upload arriving between the two (another tab)
    # waits for the queueing, so the job it lets go of nothing that names the first file.
    import threading

    app = app_for(able, queue)
    first = answer(upload(app, audio("MP3")))["upload"]
    other: list = []
    sent = threading.Thread(target=lambda: other.append(upload(app, audio("WAV"), "other.wav")))
    submit = app.submit

    def submit_while_another_uploads(*args, **kwargs):
        sent.start()
        sent.join(timeout=1.0)  # without the store held, it is staged by now, the first file let go
        return submit(*args, **kwargs)

    monkeypatch.setattr(app, "submit", submit_while_another_uploads)
    response = post(app, {"upload": first, "artist": NICK[0], "title": NICK[1]})
    assert response.status == 200, response.body
    sent.join(timeout=10)
    assert other, "the other upload never ended"
    second = answer(other[0])["upload"]
    assert staged_ids(able) == {first, second}  # the queued job's file stays
    assert queue.snapshot()[0].steps[0].args[2] == f"--upload={first}"
