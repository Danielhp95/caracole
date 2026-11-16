"""A form that names a song by its id, sent from a page made before that id was given another song (songs.id has
no AUTOINCREMENT: once the newest song is removed, the next one added gets its id), does nothing to that other song:
the page sends the song's identity key beside its id, and the route answers 409 (web/app.py ``same_song``); a
finished request's next step, worked out once, is worked out again once its id is another song's
(jobs_routes.py ``song_of``)."""

import json
from dataclasses import replace

import pytest

from caracole.config import AutochordsConfig
from caracole.removal import plan_removal, remove_song
from caracole.songs import update_song
from caracole.web.app import NOT_THAT_SONG, WebApp
from caracole.web.jobs import JobQueue

from conftest import add_song
from helpers.fake_ytdlp import FakeYtDlp
from test_web_app import ALLOWED, JSON, JSON_BLOCK, Recorder, answer, get, get_json, post, text

SAID = "another has its place"
assert SAID in NOT_THAT_SONG


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=5)


@pytest.fixture
def app(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def given_again(app, cfg, conn):
    """The page's line of the newest song, "Radiohed - Creap", then that song removed elsewhere and another
    added, which gets its id: the line, as the page still has it, and the song that has the id now."""
    add_song(conn, "Oasis", "Wonderwall")
    typo = add_song(conn, "Radiohed", "Creap")
    page = json.loads(JSON_BLOCK.search(text(get(app, "/"))).group(1))
    line = next(s for s in page["songs"] if s["id"] == typo.id)
    remove_song(conn, cfg, plan_removal(conn, cfg, typo))
    creep = add_song(conn, "Radiohead", "Creep")
    assert creep.id == typo.id and line["identity"] == typo.key != creep.key
    return line, creep


def refused(response, queue):
    assert response.status == 409, response.body[:300]
    assert SAID in text(response)
    assert queue.snapshot() == []


def test_remove_on_a_page_made_before_the_id_was_given_again_removes_nothing(app, cfg, conn, queue):
    line, _ = given_again(app, cfg, conn)
    # library.js: the question, by the line's id and identity...
    refused(post(app, "/remove", {"song": str(line["id"]), "identity": line["identity"]}, accept=JSON), queue)
    # ...and the confirmation with the line's key, never the one the question's answer gave
    response = post(app, "/remove", {"song": str(line["id"]), "key": line["identity"], "confirm": "1"}, accept=JSON)
    assert response.status == 409 and queue.snapshot() == []


def test_the_question_of_a_song_still_its_ids_is_answered(app, cfg, conn):
    song = add_song(conn, "Radiohead", "Creep")
    response = post(app, "/remove", {"song": str(song.id), "identity": song.key}, accept=JSON)
    assert response.status == 200 and answer(response)["removal"]["key"] == song.key


@pytest.mark.parametrize("path, more", [
    ("/fetch", {}),
    ("/lookup", {"lacuerda": "https://acordes.lacuerda.net/radiohed/creap.shtml"}),
    ("/versions/clear", {}),
    ("/review", {"pick": "none", "shown": ""}),
])
def test_a_songs_form_by_an_id_another_song_has_now_does_nothing(app, cfg, conn, queue, path, more):
    line, _ = given_again(app, cfg, conn)
    refused(post(app, path, {"song": str(line["id"]), "identity": line["identity"], **more}, accept=JSON), queue)


def test_a_sheet_from_youtube_by_an_id_another_song_has_now_is_made_for_none(cfg, conn, queue, tmp_path, monkeypatch):
    import caracole.youtube_fetch as yf

    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    able = replace(cfg, ytdlp_bin=FakeYtDlp(tmp_path / "bin").bin, autochords=AutochordsConfig(**files))
    app = WebApp(able, queue, allowed=ALLOWED, csrf="tok")
    line, _ = given_again(app, able, conn)
    refused(post(app, "/youtube", {"song": str(line["id"]), "identity": line["identity"],
                                   "youtube": "https://www.youtube.com/watch?v=XFkzRNyygfk"}, accept=JSON), queue)


def test_a_song_put_in_a_songbook_by_an_id_another_song_has_now_is_put_in_none(app, cfg, conn, queue):
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    (cfg.library_dir / "songbooks.toml").write_text('[Campfire]\nsongs = []\n')
    line, _ = given_again(app, cfg, conn)
    refused(post(app, "/songbook/add-song", {"name": "Campfire", "song": str(line["id"]),
                                             "identity": line["identity"]}, accept=JSON), queue)


def test_a_set_lists_get_it_by_an_id_another_song_has_now_gets_nothing(app, cfg, conn, queue):
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    (cfg.library_dir / "songbooks.toml").write_text(
        '[Campfire]\nsongs = ["Radiohead - Creep"]\n')
    line, creep = given_again(app, cfg, conn)
    response = post(app, "/songbook/get", {"name": "Campfire", "song": str(creep.id), "identity": line["identity"]},
                    accept=JSON)
    assert response.status == 409 and queue.snapshot() == []
    made = post(app, "/songbook/get", {"name": "Campfire", "song": str(creep.id), "identity": creep.key},
                accept=JSON)
    assert made.status in (200, 202), made.body[:300]


def by_id(fed):
    return {r["id"]: r for g in fed["groups"] for r in g["requests"]}


def test_a_finished_requests_next_step_never_names_the_song_that_has_its_id_now(app, cfg, conn, queue):
    conn.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, versions, "
                 "acordes, page) VALUES ('estopa/como_camaron', 'estopa', 'Estopa', 'estopa', 'Como Camarón', "
                 "'como-camaron', 'lcd', 1, 'e')")
    post(app, "/request", {"artist": "Estopa", "title": "Como Camarón", "fetch": "1"})
    camaron = add_song(conn, "Estopa", "Como Camarón")
    update_song(conn, camaron.id, match_decision="not_found")
    queue.run_pending()
    step = by_id(answer(get_json(app, "/requests.json")))[1]["actions"][0]
    assert step["label"] == "Fetch from there"
    assert step["fields"]["song"] == str(camaron.id) and step["fields"]["identity"] == camaron.key

    remove_song(conn, cfg, plan_removal(conn, cfg, camaron))
    creep = add_song(conn, "Radiohead", "Creep")
    assert creep.id == camaron.id
    item = by_id(answer(get_json(app, "/requests.json")))[1]
    assert all(a.get("fields", {}).get("song") != str(creep.id) for a in item.get("actions", []) if a)
    # and the step the tab showed before, posted all the same, looks nothing up
    before = len(queue.snapshot())
    response = post(app, "/lookup", step["fields"], accept=JSON)
    assert response.status == 409 and SAID in text(response) and len(queue.snapshot()) == before
