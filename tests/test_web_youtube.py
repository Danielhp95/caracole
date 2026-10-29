"""caracole/web/youtube_routes.py: a song's auto sheet from a YouTube video, asked for from the library page.

The route queues ``caracole youtube --sheet`` (youtube_sheet.py, tested in test_youtube_sheet.py); here the queue
records the commands, and nothing runs. "Able" is a caracole that can make chords of the audio: auto-chords'
packages taken to be there, model files, and a yt-dlp (``FakeYtDlp``, never run here).
"""

import json
import re
from dataclasses import replace
from urllib.parse import urlencode

import pytest
from conftest import add_song
from helpers.fake_ytdlp import FakeYtDlp

import caracole.youtube_fetch as yf
from caracole.config import AutochordsConfig
from caracole.library import keep_file
from caracole.normalize import identity_key
from caracole.songs import update_song
from caracole.versions import upsert_version
from caracole.web.app import Request, WebApp
from caracole.web.jobs import YOUTUBE_SHEET, JobQueue, youtube_sheet_steps

HOST = "localhost:8737"
ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})
VIKINGOS = "lzN7Thn3FV4"
PASTED = f"https://www.youtube.com/watch?v={VIKINGOS}&pp=ygUQdmlraW5nb3MgdmVnYW5vcw%3D%3D"
WATCH = f"https://www.youtube.com/watch?v={VIKINGOS}"
JSON_BLOCK = re.compile(r'<script type="application/json" id="songs">(.*?)</script>', re.S)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        return 0


@pytest.fixture
def able(cfg, tmp_path, monkeypatch):
    """A config this caracole can make chords of the audio with."""
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    return replace(cfg, ytdlp_bin=FakeYtDlp(tmp_path / "bin").bin, autochords=AutochordsConfig(**files))


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=3)


def app_for(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def post(app, path, fields, **headers):
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}"} | headers
    return app.handle(Request("POST", path, sent, urlencode({"csrf": "tok"} | fields).encode("utf-8")))


def answer(response):
    return json.loads(response.body)


def page_data(app):
    response = app.handle(Request("GET", "/", {"host": HOST}))
    assert response.status == 200
    body = response.body.decode("utf-8")
    return body, json.loads(JSON_BLOCK.search(body).group(1))


def keep_human_sheet(conn, cfg, song):
    vid = upsert_version(conn, provider="ug", tab_id="85053", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=100, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x",
                         raw={}, now="2026-10-18T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"[ch]G[/ch]\nHi", rank=1)


# --- queued ---------------------------------------------------------------------------------------------


def test_a_song_of_the_library_gets_its_sheet_from_the_video_pasted_on_its_card(able, queue, conn):
    song = add_song(conn, "Nick Cani", "Vikingos veganos")
    app = app_for(able, queue)
    response = post(app, "/youtube", {"song": str(song.id), "youtube": PASTED}, accept="application/json")
    assert response.status == 200, response.body
    view = answer(response)["job"]
    assert (view["kind"], view["songId"], view["identity"]) == ("song", song.id, song.key)
    assert view["line"] == {"tone": "queued", "text": "Queued…", "link": None, "details": None}
    [job] = queue.snapshot()
    assert job.song_key == YOUTUBE_SHEET + song.key and job.display == "Nick Cani - Vikingos veganos"
    # The video goes to the command as its plain address: never the playlist, the search or the tracking.
    assert [(s.label, s.args) for s in job.steps] == youtube_sheet_steps("Nick Cani - Vikingos veganos", WATCH)
    queue.run_pending()
    assert queue._runner.calls == [list(youtube_sheet_steps("Nick Cani - Vikingos veganos", WATCH)[0][1])]


def test_a_song_by_name_goes_into_wanted_txt_first_as_a_request_does(able, queue, conn):
    app = app_for(able, queue)
    response = post(app, "/youtube", {"artist": "Nick Cani", "title": "Vikingos veganos", "youtube": PASTED})
    assert response.status == 303
    assert "Nick Cani - Vikingos veganos" in able.wanted_file.read_text(encoding="utf-8")
    [job] = queue.snapshot()
    assert job.song_key == YOUTUBE_SHEET + identity_key("Nick Cani", "Vikingos veganos")
    assert job.note.startswith("Added to wanted.txt, line ")
    assert [s.args for s in job.steps] == [youtube_sheet_steps("Nick Cani - Vikingos veganos", WATCH)[0][1]]


def test_the_request_form_with_a_video_makes_the_sheet_in_place_of_a_lookup(able, queue, conn):
    app = app_for(able, queue)
    response = post(app, "/request", {"artist": "Nick Cani", "title": "Vikingos veganos", "album": "Pruebas",
                                      "fetch": "1", "youtube": f"youtu.be/{VIKINGOS}"}, accept="application/json")
    assert response.status == 200, response.body
    assert answer(response)["job"]["display"] == "Nick Cani - Vikingos veganos"
    [job] = queue.snapshot()
    assert job.song_key.startswith(YOUTUBE_SHEET) and [s.args[0] for s in job.steps] == ["youtube"]
    assert "Nick Cani - Vikingos veganos | Pruebas" in able.wanted_file.read_text(encoding="utf-8")


def test_asked_again_while_it_waits_the_one_waiting_is_the_answer(able, queue, conn):
    song = add_song(conn, "Nick Cani", "Vikingos veganos")
    app = app_for(able, queue)
    first = answer(post(app, "/youtube", {"song": str(song.id), "youtube": PASTED}, accept="application/json"))
    again = answer(post(app, "/youtube", {"song": str(song.id), "youtube": "https://youtu.be/oNOFfl3Hx3s"},
                        accept="application/json"))
    assert first["job"]["id"] == again["job"]["id"] and len(queue.snapshot()) == 1


# --- refused, nothing written ---------------------------------------------------------------------------------


def test_a_link_that_isnt_a_youtube_video_is_refused(able, queue, conn):
    app = app_for(able, queue)
    for value in ("https://vimeo.com/1", "", "https://www.youtube.com/@nickcani"):
        response = post(app, "/youtube", {"artist": "Nick Cani", "title": "Vikingos veganos", "youtube": value},
                        accept="application/json")
        assert response.status == 400, value
        assert answer(response)["error"] == "Not a YouTube video link."
    assert queue.snapshot() == [] and not able.wanted_file.exists()


def test_where_no_chords_can_be_made_it_says_why_and_queues_nothing(cfg, queue, conn, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    app = app_for(cfg, queue)
    response = post(app, "/youtube", {"artist": "Nick Cani", "title": "Vikingos veganos", "youtube": PASTED},
                    accept="application/json")
    assert response.status == 409
    assert answer(response)["error"] == "No sheets from YouTube here: auto-chords isn't installed."
    assert queue.snapshot() == [] and not cfg.wanted_file.exists()


@pytest.mark.parametrize("case,said", [
    ("human", "Nick Cani - Vikingos veganos already has a sheet."),
    ("ignored", "Nick Cani - Vikingos veganos is ignored in overrides.toml."),
    ("purchase", "Nick Cani - Vikingos veganos has bought audio in Music/: auto-chords uses that."),
])
def test_a_song_youtube_isnt_for_is_refused(able, queue, conn, case, said):
    song = add_song(conn, "Nick Cani", "Vikingos veganos")
    if case == "human":
        keep_human_sheet(conn, able, song)
    elif case == "ignored":
        able.overrides_file.parent.mkdir(parents=True, exist_ok=True)
        able.overrides_file.write_text('[ignore]\nsongs = ["Nick Cani - Vikingos veganos"]\n', encoding="utf-8")
    else:
        bought = able.music_dir / "Nick Cani - Vikingos veganos.flac"
        bought.parent.mkdir(parents=True)
        bought.write_bytes(b"bought")
        update_song(conn, song.id, audio_path=str(bought), audio_mtime=bought.stat().st_mtime)
    app = app_for(able, queue)
    for fields in ({"song": str(song.id)}, {"artist": "Nick Cani", "title": "Vikingos veganos"}):
        response = post(app, "/youtube", fields | {"youtube": PASTED}, accept="application/json")
        assert response.status == 409 and answer(response)["error"] == said
    assert queue.snapshot() == [] and not able.wanted_file.exists()


def test_a_song_the_library_hasnt_is_refused_by_its_id(able, queue, conn):
    response = post(app_for(able, queue), "/youtube", {"song": "41", "youtube": PASTED}, accept="application/json")
    assert response.status == 404


# --- the library page ---------------------------------------------------------------------------------------


def test_the_library_page_offers_it_where_chords_can_be_made(able, queue, conn):
    none_yet = add_song(conn, "Nick Cani", "Vikingos veganos")
    charted = add_song(conn, "Radiohead", "Creep")
    keep_human_sheet(conn, able, charted)
    body, data = page_data(app_for(able, queue))
    assert data["server"]["youtube"] == {"ok": True, "why": None, "off": False}
    assert '<input name="youtube"' in body  # the request form's field
    cards = {s["id"]: s for s in data["songs"]}
    assert cards[none_yet.id]["youtubeSheet"] is True and cards[charted.id]["youtubeSheet"] is False


def test_where_it_cant_the_request_form_says_why_and_offers_no_field(cfg, queue, conn, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    add_song(conn, "Nick Cani", "Vikingos veganos")
    body, data = page_data(app_for(cfg, queue))
    assert data["server"]["youtube"]["ok"] is False
    assert data["server"]["youtube"]["why"] == "auto-chords isn't installed"
    assert '<input name="youtube"' not in body
    assert '<p class="hint">No sheets from YouTube here: auto-chords isn&#x27;t installed.</p>' in body


def test_the_file_on_disk_offers_none_of_it(able, conn):
    from datetime import UTC, datetime

    from caracole.library_page import build_library_page
    from caracole.overrides import Overrides

    add_song(conn, "Nick Cani", "Vikingos veganos")
    html = build_library_page(conn, able, Overrides(), datetime(2026, 10, 29, tzinfo=UTC))
    assert '<input name="youtube"' not in html and '<p class="hint">No sheets from YouTube' not in html
    assert "server" not in json.loads(JSON_BLOCK.search(html).group(1))
