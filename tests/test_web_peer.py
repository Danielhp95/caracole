"""caracole serve's side of a sync (web/peer_routes.py): this library's units, a unit whole, a kept file, read alone;
and a pull of another caracole's units, queued as ``caracole peer pull``."""

import dataclasses
import json

import pytest
from conftest import add_song

from caracole import peer_sync as sync
from caracole import stamps
from caracole.db import kv_set, kv_set_json
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
    kv_set_json(conn, sync.BASE_KEY + "phone", {"format": sync.FORMAT, "units": {f"song/{song.key}": ["d", NOW]}})
    app = an_app(cfg)
    status, doc = answer(app, "/api/peer/state")
    assert status == 200
    assert doc["format"] == sync.FORMAT == 3 and doc["server"] == sync.own_id(conn) and doc["caracole"] == "0.1.0"
    assert doc["name"] == cfg.library_name and doc["token"] == "tok" and doc["base"] is None
    assert stamps.parse(doc["now"]) is not None and stamps.stamp(stamps.parse(doc["now"])) == doc["now"]
    assert isinstance(doc["indexes"], dict)
    assert sync.read_state_document(doc).now == doc["now"]
    assert set(doc["units"]) == {f"song/{song.key}", "songbook/campfire"}
    assert doc["units"][f"song/{song.key}"]["label"] == "Radiohead - Creep"
    assert answer(app, "/api/peer/state?peer=phone")[1]["base"] == {f"song/{song.key}": ["d", NOW]}


def test_the_state_gives_this_sides_settings_for_the_phone_and_a_reader_of_the_state_passes_over_them(cfg, conn):
    """The settings a phone takes at a sync (politeness.settings_document): this caracole.toml's, a switch turned
    off among them; a computer that syncs with this one reads the state as before (the sync's FORMAT is 2 still)."""
    from caracole import politeness

    cfg = dataclasses.replace(cfg, name="Canciones", providers={
        **cfg.providers, "megalobiz": dataclasses.replace(cfg.provider("megalobiz"), enabled=False)})
    status, doc = answer(an_app(cfg), "/api/peer/state")
    assert status == 200 and doc["format"] == sync.FORMAT
    assert doc["settings"] == politeness.settings_document(cfg)
    assert doc["settings"]["name"] == "Canciones" and doc["settings"]["providers"]["megalobiz"]["enabled"] is False
    assert sync.read_state_document(doc).name == "Canciones"


def test_the_state_document_gives_the_asker_the_kept_answers_this_side_keeps_for_it(cfg, conn):
    """What this side's imports of the asker's files answered "keep mine" (kv ``sync:base:<id>``'s ``kept``), as
    stored, ``here`` this side's digest: the asker's sync reads it (``PeerState.kept``) and gives this side its
    version no more. An asker that names no id is given none, and one this side kept nothing for an empty one."""
    song = a_song_with_a_sheet(cfg, conn)
    unit = f"song/{song.key}"
    sync.record_kept(conn, "phone", {unit: ("d-here", "d-phone")}, NOW)
    app = an_app(cfg)
    status, doc = answer(app, "/api/peer/state?peer=phone")
    assert status == 200 and doc["kept"] == {unit: ["d-here", "d-phone", NOW]}
    assert sync.read_state_document(doc).kept == {unit: ("d-here", "d-phone", NOW)}
    assert answer(app, "/api/peer/state?peer=desk")[1]["kept"] == {}
    assert "kept" not in answer(app, "/api/peer/state")[1]


def test_nothing_of_this_sides_politeness_is_in_the_state_or_a_unit(cfg, conn):
    """The owner's choice of 2026-11-03: each caracole's politeness is its own. A cooldown, the requests sent, the
    pace's last request and the records that gate a request (LaCuerda's searches and their failures, a 30-day check,
    an artist's UG page learned) stay on this side: the state has its members and its settings alone, a song's unit
    carries none of them, and none of them moves a unit's digest."""
    from datetime import UTC, datetime

    from caracole import health, http
    from caracole.lacuerda_search import FAILED_KEY

    song = a_song_with_a_sheet(cfg, conn)
    app = an_app(cfg)
    before = answer(app, "/api/peer/state")[1]["units"]
    unit_before = answer(app, f"/api/peer/unit?id=song/{song.key}")[1]
    blocked_at = datetime(2026, 10, 29, 7, 8, 9, tzinfo=UTC)
    cooling = health.record_block(conn, "ug", blocked_at, "HTTP 403 from the politeness test")
    health.EventLog(conn, "lookup:politeness-test", clock=lambda: blocked_at)(
        http.Event("ug", "https://www.ultimate-guitar.com/politeness-test", 403, "blocked", "politeness test"))
    kv_set(conn, "http:last_request:ug", "1730185689.250")
    kv_set_json(conn, FAILED_KEY, {"politenesstestquery": {"at": "2026-10-29T07:08:09Z", "error": "cut short"}})
    kv_set_json(conn, "lacuerda:search:politenesstestquery", {"at": "2026-10-29T07:08:09Z", "artists": []})
    kv_set(conn, f"megalobiz:checked:{song.id}", "2026-10-29T07:08:09Z")
    kv_set(conn, "ug:artist_url:politenesstestartist", "https://www.ultimate-guitar.com/artist/politeness_1")

    state = get(app, "/api/peer/state")
    doc = json.loads(state.body)
    assert set(doc) == {"format", "server", "caracole", "name", "now", "indexes", "units", "base", "settings", "token"}
    assert doc["format"] == sync.FORMAT and doc["units"] == before
    unit = get(app, f"/api/peer/unit?id=song/{song.key}")
    assert json.loads(unit.body) == unit_before
    for body in (state.body.decode(), unit.body.decode()):
        for kept_here in (health.get_state(conn, "ug").cooldown_until.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "2026-10-29T07:08:09Z", "politeness test", "politeness-test", "1730185689",
                          "politenesstest", "provider:ug", "http:last_request", "lacuerda:search", "megalobiz:checked",
                          "ug:artist_url", "health", "events", "strikes", "cooldown"):
            assert kept_here not in body, kept_here
    assert cooling.cooldown_until is not None and health.is_cooling(conn, "ug", blocked_at)


def test_a_unit_is_answered_whole_with_the_digest_the_state_gives_it(cfg, conn):
    song = a_song_with_a_sheet(cfg, conn)
    app = an_app(cfg)
    units = answer(app, "/api/peer/state")[1]["units"]
    status, doc = answer(app, f"/api/peer/unit?id=song/{song.key}")
    assert status == 200 and doc["format"] == 3 and doc["digest"] == units[f"song/{song.key}"]["digest"]
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
    assert status == 503 and "Can't read overrides.toml" in doc["error"]


# --- POST /peer/index: the index pages a phone's lookups read -------------------------------------------------------


def _index_export(tmp_path, name="reads.sqlite"):
    """An export of a phone's reads (index_transfer.export(pages=)), as the phone posts one."""
    from datetime import UTC, datetime

    import test_index_transfer as tt

    from caracole import index_transfer

    phone = tt.database(tmp_path, f"phone-{name}")
    try:
        tt.harp_page(phone, "artist/1178/billy-joel", ["Piano Man"], tt.LATE)
        path = tmp_path / name
        index_transfer.export(phone, path, now=datetime(2026, 11, 3, tzinfo=UTC),
                              pages={"harptabs": ["artist/1178/billy-joel"]})
    finally:
        phone.close()
    return path.read_bytes()


@pytest.fixture
def phone_side(cfg):
    from test_peer_push import Served
    from test_web_server import Recorder as Runner

    from caracole.web.security import allowed_hosts

    runner = Runner()
    serving = Served(WebApp(cfg, JobQueue(runner), allowed=allowed_hosts("127.0.0.1"), csrf="tok"))
    serving.runner = runner
    yield serving
    serving.close()


def _staged(cfg):
    from caracole import peer_push

    return peer_push.staged_indexes(cfg.state_dir)


def test_the_phones_index_pages_are_staged_privately_and_their_merge_queued(phone_side, cfg, tmp_path):
    import stat

    from caracole.web import jobs

    data = _index_export(tmp_path)

    status, _, body = phone_side.ask("POST", "/peer/index", data, kind="application/octet-stream")

    assert status == 202, body
    job_id = json.loads(body)["job"]
    [path] = _staged(cfg)
    assert path.parent == cfg.state_dir / "peer" and path.read_bytes() == data
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    [job] = [j for j in phone_side.app.queue.snapshot() if j.id == job_id]
    assert job.song_key == jobs.INDEX_MERGE + path.name and job.title == "Index pages from another scribe"
    assert [s.args for s in job.steps] == [("index", "merge", "--delete", "--progress", "--", str(path))]


def test_index_pages_need_the_form_token_and_come_from_no_other_site(phone_side, cfg, tmp_path):
    data = _index_export(tmp_path)
    status, _, body = phone_side.ask("POST", "/peer/index", data, kind="application/octet-stream", token=None)
    assert status == 403 and json.loads(body)["reload"] is True
    status, _, _ = phone_side.ask("POST", "/peer/index", data, kind="application/octet-stream",
                                  Origin="http://evil.example")
    assert status == 403
    status, _, _ = phone_side.ask("POST", "/peer/index", data, kind="application/json")
    assert status == 415
    assert _staged(cfg) == [] and phone_side.runner.calls == []


def test_index_pages_past_64_mib_are_refused_unread_and_bytes_that_are_no_export_are_refused(phone_side, cfg):
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", phone_side.server.server_address[1], timeout=10)
    try:  # 64 MiB and a byte, claimed: answered at once, unread
        conn.putrequest("POST", "/peer/index")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("X-Caracole-Form-Token", "tok")
        conn.putheader("Content-Length", str(64 * 1024 * 1024 + 1))
        conn.endheaders()
        assert conn.getresponse().status == 413
    finally:
        conn.close()
    status, _, body = phone_side.ask("POST", "/peer/index", b"not a database", kind="application/octet-stream")
    assert status == 400 and "isn't an index export" in json.loads(body)["error"]
    assert _staged(cfg) == []


def test_an_export_this_side_would_refuse_is_refused_before_the_phone_forgets_its_reads(phone_side, cfg, tmp_path):
    """The phone forgets its reads on a 202: an export the merge would refuse is refused here, unstaged, 409 for
    another version (the phone keeps its reads until the two agree), 400 for one that isn't of pages alone."""
    import sqlite3
    from datetime import UTC, datetime

    import test_index_transfer as tt

    from caracole import db, index_transfer

    path = tmp_path / "newer.sqlite"
    path.write_bytes(_index_export(tmp_path))
    out = sqlite3.connect(path)
    out.execute(f"UPDATE {index_transfer.META} SET value = ? WHERE key = 'schema'", (str(db.SCHEMA_VERSION + 1),))
    out.commit()
    out.close()
    status, _, body = phone_side.ask("POST", "/peer/index", path.read_bytes(), kind="application/octet-stream")
    said = json.loads(body)["error"]
    assert status == 409 and said.startswith("The index export was exported at schema version")
    assert "Bring both scribes to one version first." in said and str(cfg.state_dir) not in said

    home = tt.database(tmp_path, "home")
    try:
        tt.full(home)  # a whole export: the sitemaps' rows and records, which a merge would take as the phone's
        index_transfer.export(home, tmp_path / "whole.sqlite", ["ug"], now=datetime(2026, 11, 3, tzinfo=UTC))
    finally:
        home.close()
    status, _, body = phone_side.ask("POST", "/peer/index", (tmp_path / "whole.sqlite").read_bytes(),
                                     kind="application/octet-stream")
    assert status == 400 and "ug_index holds rows, and an export of pages none" in json.loads(body)["error"]
    assert _staged(cfg) == [] and phone_side.runner.calls == []


def test_two_index_exports_wait_at_most_and_one_left_an_hour_that_no_request_names_goes(cfg, tmp_path):
    import os
    import time

    from caracole import peer_push

    data = _index_export(tmp_path)
    first, second = peer_push.stage_index(cfg.state_dir, data), peer_push.stage_index(cfg.state_dir, data)
    with pytest.raises(peer_push.PushError) as refused:
        peer_push.stage_index(cfg.state_dir, data)
    assert refused.value.status == 409
    hours_ago = time.time() - 2 * 3600
    os.utime(first, (hours_ago, hours_ago))
    os.utime(second, (hours_ago, hours_ago))

    assert peer_push.sweep_indexes(cfg.state_dir, {str(second)}) == [first.name]  # its merge still waits

    assert _staged(cfg) == [second]
    third = peer_push.stage_index(cfg.state_dir, data)
    assert _staged(cfg) == sorted([second, third])
    (cfg.state_dir / "peer" / "index-not-one.sqlite").write_bytes(data)  # no name of caracole's: never touched
    assert peer_push.sweep_indexes(cfg.state_dir, set(), now=time.time() + 2 * 3600) == sorted(
        [second.name, third.name])
    assert (cfg.state_dir / "peer" / "index-not-one.sqlite").exists()


def test_index_pages_merged_by_the_queued_command_reach_this_library_and_the_file_goes(tmp_path, monkeypatch):
    """The whole way: posted to caracole serve, staged, then the command it queued run as its queue runs it."""
    from test_commands_peer import Side, run
    from test_peer_push import Served

    from caracole.get import read_progress_line
    from caracole.web.security import allowed_hosts

    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    computer = Side(tmp_path / "computer")
    served = Served(WebApp(computer.cfg, JobQueue(Recorder()), allowed=allowed_hosts("127.0.0.1"), csrf="tok"))
    try:
        status, _, body = served.ask("POST", "/peer/index", _index_export(tmp_path), kind="application/octet-stream")
        assert status == 202, body
        [job] = [j for j in served.app.queue.snapshot() if j.id == json.loads(body)["job"]]
    finally:
        served.close()
    (step,) = job.steps

    result = run(computer, *step.args)

    assert result.exit_code == 0, result.output
    said = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    assert said[-1] == {"stage": "merge", "state": "done", "detail": "harptabs.com: 1 artist page"}
    assert _staged(computer.cfg) == []
    assert [tuple(r) for r in computer.conn.execute("SELECT title FROM harptabs_artist_tabs")] == [("Piano Man",)]
    computer.conn.close()
