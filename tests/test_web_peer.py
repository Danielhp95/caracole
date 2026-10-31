"""caracole serve's side of a sync (web/sync_routes.py): ``GET /api/peer/state``, this library's units, read alone."""

import json

from conftest import add_song

from caracole import peer_sync as sync
from caracole.overrides import add_version
from caracole.songbook import make_songbook, songbooks_file
from caracole.web.app import WebApp

from test_web_app import ALLOWED, Recorder, get
from caracole.web.jobs import JobQueue


def state_of(app):
    response = get(app, "/api/peer/state")
    return response.status, json.loads(response.body)


def test_the_state_lists_each_unit_and_writes_nothing(cfg, conn):
    song = add_song(conn, "Radiohead", "Creep")
    add_version(cfg.overrides_file, "Radiohead - Creep", "key=Gm&capo=0")
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    app = WebApp(cfg, JobQueue(Recorder(), limit=3), allowed=ALLOWED, csrf="tok")
    status, doc = state_of(app)
    assert status == 200
    assert doc["format"] == sync.FORMAT and doc["server"] is None and doc["caracole"] == "0.1.0"
    assert doc["name"] == cfg.library_name
    assert set(doc["units"]) == {f"song/{song.key}", "songbook/campfire"}
    assert doc["units"][f"song/{song.key}"]["label"] == "Radiohead - Creep"
    assert sync.own_id(conn) is None  # no id made by a read

    made = sync.make_id(conn)
    assert state_of(app)[1]["server"] == made


def test_another_sites_page_cant_read_it(cfg, conn):
    app = WebApp(cfg, JobQueue(Recorder(), limit=3), allowed=ALLOWED, csrf="tok")
    assert get(app, "/api/peer/state", **{"sec-fetch-site": "cross-site"}).status == 403


def test_overrides_that_cant_be_read_are_said_as_data(cfg, conn):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text("[nonsense\n", encoding="utf-8")
    app = WebApp(cfg, JobQueue(Recorder(), limit=3), allowed=ALLOWED, csrf="tok")
    status, doc = state_of(app)
    assert status == 503 and "overrides.toml can't be read" in doc["error"]
