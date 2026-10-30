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


# --- a video suggested for a search ----------------------------------------------------------------------

SEARCHED = "Nick Cani - Vikingos veganos"
JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x0b\x08\x01\x68\x01\xe0\x01\x01\x11\x00\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x12\x34\xff\xd9")


def get(app, path, **headers):
    return app.handle(Request("GET", path, {"host": HOST, **headers}))


def search_answer(app, q=SEARCHED):
    from urllib.parse import quote

    response = get(app, f"/api/search?q={quote(q)}", accept="application/json")
    assert response.status == 200, response.body
    return answer(response)


def searched_already(conn, *, thumb=True, video=True):
    from caracole.db import kv_set_json
    from caracole.youtube_search import query_key

    kv_set_json(conn, f"youtube-search:{query_key(SEARCHED)}", {
        "at": "2026-10-29T10:00:00Z", "query": SEARCHED, "thumb": thumb,
        "video": {"id": VIKINGOS, "title": "Somos vikingos veganos - Hyperfanes", "channel": "kintanedu",
                  "duration": 222.0, "url": WATCH} if video else None})


def test_a_search_with_no_sheet_says_youtube_may_be_searched_for_it(able, queue, conn):
    from caracole.youtube_search import query_key

    said = search_answer(app_for(able, queue))["youtube"]
    assert said == {"state": "auto", "query": SEARCHED, "key": query_key(SEARCHED)}


def test_a_search_with_a_sheet_or_where_none_can_be_made_says_nothing_of_youtube(able, cfg, queue, conn):
    add_song(conn, "Nick Cani", "Vikingos veganos")  # yours, by its title: a sheet on the screen
    assert search_answer(app_for(able, queue))["youtube"] is None
    assert search_answer(app_for(cfg, queue), "Someone - Something")["youtube"] is None  # no yt-dlp here


def test_a_video_found_this_month_comes_back_with_its_thumbnail_and_no_request(able, queue, conn):
    searched_already(conn)
    said = search_answer(app_for(able, queue), "vikingos veganos nick cani")["youtube"]
    assert said["state"] == "found" and said["video"] == {
        "id": VIKINGOS, "title": "Somos vikingos veganos - Hyperfanes", "channel": "kintanedu", "duration": 222.0,
        "url": WATCH, "thumb": f"/youtube/thumb/{VIKINGOS}.jpg"}
    assert queue.snapshot() == []


def test_the_search_of_youtube_is_one_job_of_no_songs(able, queue, conn):
    from caracole.web.jobs import YOUTUBE_SEARCH, youtube_search_steps
    from caracole.youtube_search import query_key

    app = app_for(able, queue)
    response = post(app, "/youtube/search", {"q": SEARCHED}, accept="application/json")
    assert response.status == 202, response.body
    [job] = queue.snapshot()
    assert answer(response) == {"job": job.id, "url": f"/api/jobs/{job.id}"}
    assert job.song_key == YOUTUBE_SEARCH + query_key(SEARCHED)
    assert [(s.label, s.args) for s in job.steps] == youtube_search_steps(SEARCHED)
    again = post(app, "/youtube/search", {"q": "vikingos veganos nick cani"}, accept="application/json")
    assert answer(again)["job"] == job.id and len(queue.snapshot()) == 1  # the one on its way


def test_the_search_of_youtube_is_refused_where_its_gate_refuses_it(able, queue, conn):
    from datetime import UTC, datetime

    from caracole.health import record_block

    app = app_for(able, queue)
    assert post(app, "/youtube/search", {"q": ""}, accept="application/json").status == 400
    searched_already(conn)
    assert post(app, "/youtube/search", {"q": SEARCHED}, accept="application/json").status == 409
    add_song(conn, "Estopa", "Como Camarón")
    assert post(app, "/youtube/search", {"q": "Estopa - Como Camarón"}, accept="application/json").status == 409
    record_block(conn, "youtube", datetime.now(UTC), "bot check")
    refused = post(app, "/youtube/search", {"q": "Someone - Something"}, accept="application/json")
    assert refused.status == 429 and "paused after a block" in answer(refused)["error"]
    assert queue.snapshot() == []


def test_a_kept_thumbnail_is_served_as_an_image_that_runs_nothing(able, queue, conn):
    from caracole.youtube_search import thumb_path

    app = app_for(able, queue)
    assert get(app, f"/youtube/thumb/{VIKINGOS}.jpg").status == 404  # not kept
    path = thumb_path(able, VIKINGOS)
    path.parent.mkdir(parents=True)
    path.write_bytes(JPEG)
    response = get(app, f"/youtube/thumb/{VIKINGOS}.jpg")
    assert response.status == 200 and response.body == JPEG
    headers = dict(response.headers)
    assert headers["Content-Type"] == "image/jpeg" and headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Security-Policy"].startswith("default-src 'none'")
    path.write_bytes(b"<svg onload=alert(1)>")  # a file there that is no JPEG is never sent
    assert get(app, f"/youtube/thumb/{VIKINGOS}.jpg").status == 404
    for name in ("../../caracole.sqlite", f"{VIKINGOS}.png", "x.jpg", ""):
        assert get(app, f"/youtube/thumb/{name}").status == 404, name


def test_the_served_page_may_show_images_of_the_server_alone_and_the_file_none(able, queue, conn):
    from datetime import UTC, datetime

    from caracole.library_page import build_library_page
    from caracole.overrides import Overrides

    policy = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">')
    body, _ = page_data(app_for(able, queue))
    assert "img-src data: 'self';" in policy.search(body).group(1)
    html = build_library_page(conn, able, Overrides(), datetime(2026, 10, 29, tzinfo=UTC))
    assert "img-src data:;" in policy.search(html).group(1)


# --- a pasted video ------------------------------------------------------------------------------------------


def video_answer(app, link=PASTED):
    from urllib.parse import quote

    response = get(app, f"/api/youtube/video?url={quote(link)}", accept="application/json")
    return response.status, answer(response)


def known_video(conn, *, thumb=True, title="Somos vikingos veganos - Hyperfanes", channel="kintanedu"):
    from caracole.db import kv_set_json

    kv_set_json(conn, f"youtube-search:video:{VIKINGOS}", {
        "at": "2026-10-29T10:00:00Z", "thumb": thumb,
        "video": {"id": VIKINGOS, "title": title, "channel": channel, "duration": 222.0, "url": WATCH}})


def test_a_pasted_video_not_read_yet_may_be_read(able, queue, conn):
    status, said = video_answer(app_for(able, queue))
    assert status == 200
    assert said == {"id": VIKINGOS, "url": WATCH, "state": "auto", "video": None, "guess": {"artist": "", "title": ""},
                    "song": None}
    assert queue.snapshot() == []  # reading the answer asks nothing


def test_a_known_video_comes_with_its_guessed_name_and_thumbnail(able, queue, conn):
    known_video(conn)
    _, said = video_answer(app_for(able, queue), f"youtu.be/{VIKINGOS}?si=x")
    assert said["state"] == "found" and said["video"] == {
        "title": "Somos vikingos veganos - Hyperfanes", "channel": "kintanedu", "duration": 222.0,
        "thumb": f"/youtube/thumb/{VIKINGOS}.jpg"}
    assert said["guess"] == {"artist": "Somos vikingos veganos", "title": "Hyperfanes"}
    # One song of a one-word band, with no sheet, is no proof of the band (song_names.py: a mistaken line would do);
    # two are, and the title is read the other way round.
    add_song(conn, "Hyperfanes", "Otra")
    assert video_answer(app_for(able, queue))[1]["guess"] == {"artist": "Somos vikingos veganos", "title": "Hyperfanes"}
    add_song(conn, "Hyperfanes", "Una más")
    assert video_answer(app_for(able, queue))[1]["guess"] == {"artist": "Hyperfanes", "title": "Somos vikingos veganos"}


def test_a_video_whose_song_has_a_sheet_says_so(able, queue, conn):
    known_video(conn, title="Nick Cani - Vikingos veganos", channel="Nick Cani")
    song = add_song(conn, "Nick Cani", "Vikingos veganos")
    _, said = video_answer(app_for(able, queue))
    assert said["song"] == {"id": song.id, "display": "Nick Cani - Vikingos veganos", "has_sheet": False,
                            "sheet": None}
    keep_human_sheet(conn, able, song)
    said = video_answer(app_for(able, queue))[1]["song"]
    assert said["has_sheet"] is True and said["sheet"].endswith("sheet.txt")


def test_where_no_sheet_can_be_made_a_pasted_video_says_why(cfg, queue, conn, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    _, said = video_answer(app_for(cfg, queue))
    assert (said["state"], said["why"]) == ("off", "auto-chords isn't installed")


def test_a_link_that_is_no_video_is_refused(able, queue, conn):
    status, said = video_answer(app_for(able, queue), "https://www.youtube.com/@nickcani")
    assert status == 400 and said["error"] == "Not a YouTube video link."


def test_reading_a_pasted_video_is_one_job_of_no_songs(able, queue, conn):
    from caracole.web.jobs import YOUTUBE_SEARCH, youtube_video_steps

    app = app_for(able, queue)
    response = post(app, "/youtube/video", {"url": PASTED}, accept="application/json")
    assert response.status == 202, response.body
    [job] = queue.snapshot()
    assert answer(response) == {"job": job.id, "url": f"/api/jobs/{job.id}"}
    assert job.song_key == f"{YOUTUBE_SEARCH}video:{VIKINGOS}"
    assert [(s.label, s.args) for s in job.steps] == youtube_video_steps(VIKINGOS)
    assert job.steps[0].args == ("youtube", f"--video={VIKINGOS}", "--progress")
    assert answer(post(app, "/youtube/video", {"url": f"youtu.be/{VIKINGOS}"}, accept="application/json"))["job"] == job.id
    known_video(conn)
    assert post(app, "/youtube/video", {"url": "https://youtu.be/oNOFfl3Hx3s"}, accept="application/json").status == 202
    assert post(app, "/youtube/video", {"url": PASTED}, accept="application/json").status == 409  # read already


@pytest.mark.parametrize("link", [
    f"https://m.youtube.com/watch?v={VIKINGOS}&si=abc", f"music.youtube.com/watch?v={VIKINGOS}&list=RD1",
    f"https://www.youtube.com/shorts/{VIKINGOS}", f"youtu.be/{VIKINGOS}?si=x", f"https://youtube.com/live/{VIKINGOS}",
])
def test_the_request_forms_youtube_field_takes_a_videos_every_link(able, queue, conn, link):
    post(app_for(able, queue), "/request", {"artist": "Nick Cani", "title": "Vikingos veganos", "youtube": link})
    [job] = queue.snapshot()
    assert f"--url={WATCH}" in job.steps[0].args  # its plain address, whatever was pasted


def test_a_video_the_library_has_a_song_of_is_named_as_that_song(able, queue, conn):
    from caracole.db import kv_set_json

    known_video(conn)  # its title says "Somos vikingos veganos - Hyperfanes"
    song = add_song(conn, "Nick Cani", "Vikingos veganos")
    kv_set_json(conn, f"youtube:{song.id}", {"video": {"id": VIKINGOS, "title": "x"}, "source": "pasted"})
    said = video_answer(app_for(able, queue))[1]
    assert said["guess"] == {"artist": "Nick Cani", "title": "Vikingos veganos"}
    assert said["song"]["display"] == "Nick Cani - Vikingos veganos" and said["song"]["has_sheet"] is False
