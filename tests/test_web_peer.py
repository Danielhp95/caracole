"""caracole serve's side of a sync (web/peer_routes.py): this library's units, a unit whole, a kept file, read alone;
and a pull of another caracole's units, queued as ``caracole peer pull``."""

import json

from conftest import add_song

from caracole import peer_sync as sync
from caracole import stamps
from caracole.db import kv_set_json
from caracole.library import keep_file
from caracole.overrides import add_version
from caracole.songbook import make_songbook, songbooks_file
from caracole.versions import upsert_version
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue

from test_web_app import ALLOWED, Recorder, get, get_json, post

NOW = "2026-10-31T00:00:00Z"


def an_app(cfg):
    return WebApp(cfg, JobQueue(Recorder(), limit=3), allowed=ALLOWED, csrf="tok")


def answer(app, path):
    response = get(app, path)
    return response.status, json.loads(response.body) if response.body[:1] == b"{" else response.body


def a_song_with_a_sheet(cfg, conn):
    song = add_song(conn, "Radiohead", "Creep")
    vid = upsert_version(conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url="https://u/101", raw={"x": 1}, now=NOW)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"[Am]Creep", rank=1)
    add_version(cfg.overrides_file, "Radiohead - Creep", "key=Gm&capo=0")
    return song


def test_the_state_lists_each_unit_with_this_sides_id_and_its_base_with_the_peer_that_asks(cfg, conn):
    song = a_song_with_a_sheet(cfg, conn)
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    kv_set_json(conn, sync.BASE_KEY + "phone", {"format": 2, "units": {f"song/{song.key}": ["d", NOW]}})
    app = an_app(cfg)
    status, doc = answer(app, "/api/peer/state")
    assert status == 200
    assert doc["format"] == sync.FORMAT == 2 and doc["server"] == sync.own_id(conn) and doc["caracole"] == "0.1.0"
    assert doc["name"] == cfg.library_name and doc["token"] == "tok" and doc["base"] is None
    assert stamps.parse(doc["now"]) is not None and stamps.stamp(stamps.parse(doc["now"])) == doc["now"]
    assert isinstance(doc["indexes"], dict)
    assert sync.read_state_document(doc).now == doc["now"]
    assert set(doc["units"]) == {f"song/{song.key}", "songbook/campfire"}
    assert doc["units"][f"song/{song.key}"]["label"] == "Radiohead - Creep"
    assert answer(app, "/api/peer/state?peer=phone")[1]["base"] == {f"song/{song.key}": ["d", NOW]}


def test_a_unit_is_answered_whole_with_the_digest_the_state_gives_it(cfg, conn):
    song = a_song_with_a_sheet(cfg, conn)
    app = an_app(cfg)
    units = answer(app, "/api/peer/state")[1]["units"]
    status, doc = answer(app, f"/api/peer/unit?id=song/{song.key}")
    assert status == 200 and doc["format"] == 2 and doc["digest"] == units[f"song/{song.key}"]["digest"]
    assert sync.digest_of(sync.value_of_document(doc["id"], doc["unit"])) == doc["digest"]
    unit = doc["unit"]
    assert unit["names"]["title"] == "Creep" and unit["overrides"] == {"version": "key=Gm&capo=0"}
    assert [(v["provider"], v["tab_id"], [f["name"] for f in v["files"]]) for v in unit["versions"]] == [
        ("ug", "101", ["sheet.txt"])]
    assert answer(app, "/api/peer/unit?id=song/nobody")[0] == 404
    assert answer(app, "/api/peer/unit?id=nonsense")[0] == 404


def test_a_kept_file_is_sent_while_it_is_as_kept_and_no_other_file(cfg, conn):
    song = a_song_with_a_sheet(cfg, conn)
    app = an_app(cfg)
    assert answer(app, f"/api/peer/file?song={song.key}&name=sheet.txt") == (200, b"[Am]Creep")
    assert answer(app, f"/api/peer/file?song={song.key}&name=info.json")[0] == 404  # caracole made it: no kept file
    (cfg.library_dir / "Radiohead" / "Creep" / "sheet.txt").write_bytes(b"changed on a synced device")
    assert answer(app, f"/api/peer/file?song={song.key}&name=sheet.txt")[0] == 404


def test_another_sites_page_reads_none_of_them(cfg, conn):
    app = an_app(cfg)
    for path in ("/api/peer/state", "/api/peer/unit?id=song/x", "/api/peer/file?song=x&name=y"):
        assert get(app, path, **{"sec-fetch-site": "cross-site"}).status == 403


def test_a_pull_is_queued_as_caracole_peer_pull_with_the_form_token_alone(cfg, conn):
    app = an_app(cfg)
    fields = {"from": "192.168.1.20:8737", "units": "song/radiohead/creep\nsongbook/campfire"}
    assert post(app, "/peer/pull", fields, csrf="wrong").status == 403
    response = post(app, "/peer/pull", fields, accept="application/json")
    assert response.status == 200
    job = app.queue.snapshot()[0]
    assert [list(s.args) for s in job.steps] == [["peer", "pull", "--unit=song/radiohead/creep",
                                                  "--unit=songbook/campfire", "--", "http://192.168.1.20:8737"]]
    for feed in ("/jobs.json", "/requests.json"):  # the Requests tab draws it as any request
        assert get_json(app, feed).status == 200, feed
    assert post(app, "/peer/pull", {"from": "ftp://x", "units": "song/a"}).status == 400
    assert post(app, "/peer/pull", {"from": "phone:8737", "units": ""}).status == 400


def test_overrides_that_cant_be_read_are_said_as_data(cfg, conn):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text("[nonsense\n", encoding="utf-8")
    status, doc = answer(an_app(cfg), "/api/peer/state")
    assert status == 503 and "overrides.toml can't be read" in doc["error"]
