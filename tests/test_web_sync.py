"""The Sync tab's routes on caracole serve (web/sync_routes.py): GET /api/sync, POST /sync/test, POST /sync/compare,
GET /api/sync/unit, GET /api/sync/indexes and POST /sync/apply, between two computers' caracole serves, each a WebApp
whose queue runs its commands through the CLI in this process (``InProcess``), the other reached over HTTP through a
transport that hands each request to its app.

Test asks the other caracole what it holds and changes nothing; Compare answers every unit the two hold differently,
with each song's names, each side's change, its part and the songbooks that list it, each songbook difference's two
documents and the indexes newer on either side, and keeps the comparison, whose units' two documents it answers
after; Sync refuses an unchosen conflict of its parts, a part it doesn't know, a comparison past or one the two no
longer agree with, else queues ``caracole peer sync --push`` with the owner's choices and parts, whose view the tab
follows to its end: then the two hold the same, and the tab lists the other caracole."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from caracole import db, index_transfer
from caracole import peer_sync as sync
from caracole.songbook import load_songbooks, make_songbook, songbooks_file
from caracole.ug import index as ug_index
from caracole.web import jobs, sync_routes
from caracole.web.app import Request, WebApp, route_for
from caracole.web.jobs import PEER_SYNC_STAGES, PEER_TAKE_STAGES, Job, Stage, Step
from caracole.web.jobs_routes import view

from test_commands_peer import InProcess, Side, run, two_conflicts
from test_web_app import get, post

THERE = "http://localhost:8737"  # the other computer's caracole serve, as here reaches it
CREEP, WONDERWALL = "song/radiohead/creep", "song/oasis/wonderwall"
HYSTERIA, CALORRO = "song/muse/hysteria", "song/estopa/tu-calorro"


@pytest.fixture
def computers(tmp_path, monkeypatch):
    """Two computers' caracole serves: ``here`` (whose routes the test asks, as its library page does) and
    ``there``, which both the comparison and ``caracole peer sync`` reach at THERE; each runs what its queue holds
    through the CLI, there as it is asked how a job goes (a push's take). Renders are recorded, not made."""
    here, there = Side(tmp_path / "here", InProcess()), Side(tmp_path / "there", InProcess())
    asked: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.method, request.url.path))
        if request.url.path.startswith("/api/jobs/"):
            there.app.queue.run_pending()
        answer = there.app.handle(Request(request.method, request.url.raw_path.decode(), dict(request.headers),
                                          request.content))
        answer = WebApp.finish(answer)
        body = answer.body if answer.stream is None else answer.stream.read()  # an index streamed whole
        if answer.stream is not None:
            answer.stream.close()
        return httpx.Response(answer.status, headers=answer.headers, content=body)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    monkeypatch.setattr("caracole.commands.peer._sleep", lambda seconds: None)
    monkeypatch.setattr(sync_routes, "transport", lambda: transport)
    monkeypatch.setattr("caracole.render.render_all", lambda conn, cfg, overrides, **kw: None)
    yield here, there, asked
    here.conn.close()
    there.conn.close()


def script(app, path, fields=None):
    """The page's script asking ``path``: a GET with the form token in its header, or a form posted, JSON back."""
    if fields is None:
        answer = get(app, path, accept="application/json", **{"x-caracole-form-token": "tok"})
    else:
        answer = post(app, path, fields, accept="application/json")
    return answer.status, json.loads(answer.body)


def compared(here, address=THERE):
    status, found = script(here.app, "/sync/compare", {"address": address})
    assert status == 200, found
    return found


def by_label(found):
    return {d["label"]: d for d in found["differences"]}


def synced(here, there, prefer="here", **fields):
    """The two synced through the tab's routes, every conflict as ``prefer`` says; the job, done."""
    found = compared(here)
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": prefer,
                                                       "choices": "", **fields})
    assert status == 200, answer
    here.app.queue.run_pending()
    job = next(j for j in here.app.queue.snapshot() if j.id == answer["job"]["id"])
    assert job.state == "done", [s.output for s in job.steps]
    return job


def by_id(found):
    return {d["id"]: d for d in found["differences"]}


def kv_rows(side):
    return sorted(tuple(row) for row in side.conn.execute("SELECT key, value FROM kv"))


@pytest.fixture
def in_utc(monkeypatch):
    """The server's zone UTC, as the vectors' (a day is said in it)."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


# --- what the tab reads first ------------------------------------------------------------------------------------


def test_the_tab_reads_this_caracole_and_none_synced_before(computers):
    here, _, asked = computers
    status, state = script(here.app, "/api/sync")
    assert status == 200 and asked == []  # read here alone
    assert state == {"server": sync.own_id(here.conn), "name": here.cfg.library_name, "device": "computer",
                     "address": None, "peers": [], "songs": 0, "songbooks": 0}


def test_the_tab_reads_this_caracole_its_device_and_its_counts(computers):
    here, _, asked = computers
    here.song("Radiohead", "Creep")
    here.song("Oasis", "Wonderwall")
    make_songbook(songbooks_file(here.cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    status, state = script(here.app, "/api/sync")
    assert status == 200 and asked == []
    assert (state["device"], state["songs"], state["songbooks"]) == ("computer", 2, 1)
    # A songbooks.toml that won't parse stops the songbooks alone: no count of them, the rest as ever.
    songbooks_file(here.cfg.library_dir).write_text("[[not toml", encoding="utf-8")
    status, state = script(here.app, "/api/sync")
    assert status == 200 and (state["songs"], state["songbooks"]) == (2, None)


def test_the_peers_synced_before_are_listed_newest_first_and_the_newest_is_the_address(computers):
    here, _, _ = computers
    db.kv_set_json(here.conn, "sync:peer:aaaa", {"address": "http://10.0.0.7:8737", "name": "Studio",
                                                "synced_at": "2026-10-30T08:00:00Z"})
    db.kv_set_json(here.conn, "sync:peer:bbbb", {"address": "http://192.168.1.20:8737", "name": "Desk",
                                                "synced_at": "2026-11-02T21:04:00Z"})
    db.kv_set(here.conn, "sync:peer:cccc", "not a record")
    status, state = script(here.app, "/api/sync")
    assert status == 200 and state["address"] == "http://192.168.1.20:8737"
    assert state["peers"] == [
        {"address": "http://192.168.1.20:8737", "server": "bbbb", "name": "Desk", "synced_at": "2026-11-02T21:04:00Z"},
        {"address": "http://10.0.0.7:8737", "server": "aaaa", "name": "Studio", "synced_at": "2026-10-30T08:00:00Z"}]


# --- Test ----------------------------------------------------------------------------------------------------------


def test_test_asks_the_other_caracole_and_changes_nothing(computers, in_utc):
    here, there, asked = computers
    there.song("Radiohead", "Creep")
    there.song("Oasis", "Wonderwall")
    there.song("Muse", "Hysteria", version=None)
    make_songbook(songbooks_file(there.cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    db.kv_set(there.conn, ug_index.REFRESHED_KEY, "2026-11-01T03:30:00Z")
    db.kv_set(there.conn, "lacuerda:index:complete_at", "2026-11-02T12:00:00Z")  # its newest read
    there_id = sync.own_id(there.conn)
    db.kv_set_json(here.conn, f"sync:peer:{there_id}", {"address": THERE, "name": "Desk",
                                                        "synced_at": "2026-10-30T08:00:00Z"})
    before = kv_rows(here)
    status, said = script(here.app, "/sync/test", {"address": "localhost:8737"})  # typed with no scheme
    assert status == 200, said
    name = there.cfg.library_name
    assert said == {"peer": {"address": THERE, "server": there_id, "caracole": "0.1.0", "name": name},
                    "songs": 3, "songbooks": 1, "indexes": "2026-11-02T12:00:00Z",
                    "synced_at": "2026-10-30T08:00:00Z",
                    "said": f"{name} answered: 3 songs, 1 songbook, its indexes read 02/11/26"}
    assert asked == [("GET", "/api/peer/state")]
    assert kv_rows(here) == before and here.app.queue.snapshot() == []  # nothing written, nothing queued


def test_test_says_no_indexes_and_refuses_as_compare_does(computers, monkeypatch):
    here, there, _ = computers
    there.song("Radiohead", "Creep")
    status, said = script(here.app, "/sync/test", {"address": THERE})
    assert status == 200 and (said["indexes"], said["synced_at"]) == (None, None)
    assert said["said"] == f"{there.cfg.library_name} answered: 1 song, 0 songbooks, no indexes"

    status, said = script(here.app, "/sync/test", {"address": "ftp://desk"})
    assert status == 400 and "isn't the address of a caracole serve" in said["error"]
    db.kv_set(here.conn, sync.ID_KEY, sync.own_id(there.conn))  # a copy of the other's database
    status, said = script(here.app, "/sync/test", {"address": THERE})
    assert status == 409 and "is this one" in said["error"] and "caracole peer new-id" in said["error"]

    def refused(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(sync_routes, "transport", lambda: httpx.MockTransport(refused))
    status, said = script(here.app, "/sync/test", {"address": "192.168.1.20:8737"})
    assert status == 502 and said["error"].startswith("Nothing answered at http://192.168.1.20:8737")


def test_tested_words_say_one_song_and_one_songbook_and_the_day_in_the_servers_zone(in_utc):
    words = sync_routes.tested_words
    assert words("Studio", 3, 1, "2026-11-02T12:00:00Z") == "Studio answered: 3 songs, 1 songbook, its indexes " \
                                                             "read 02/11/26"
    assert words("Studio", 1, 0, None) == "Studio answered: 1 song, 0 songbooks, no indexes"
    assert words("http://10.0.0.7:8737", 96, 3, "2026-11-02T23:30:00Z") == (
        "http://10.0.0.7:8737 answered: 96 songs, 3 songbooks, its indexes read 02/11/26")
    assert sync_routes.newest_read({"ug": "2026-11-01T03:30:00Z", "lacuerda": "2026-11-02T12:00:00Z",
                                    "odd": "not a time"}) == "2026-11-02T12:00:00Z"
    assert sync_routes.newest_read({"odd": "not a time"}) is None and sync_routes.newest_read({}) is None


def test_the_days_are_said_in_the_servers_zone(monkeypatch):
    monkeypatch.setenv("TZ", "EST+05")  # five hours behind UTC, a POSIX rule: no zone files
    time.tzset()
    try:
        assert sync_routes.tested_words("Studio", 3, 1, "2026-11-02T03:00:00Z").endswith("read 01/11/26")
    finally:
        monkeypatch.undo()
        time.tzset()


# --- the comparison ----------------------------------------------------------------------------------------------


def test_a_comparison_lists_each_difference_with_its_kind_proposal_and_both_digests(computers):
    here, there, asked = computers
    unit = two_conflicts(here, there)
    found = compared(here, "localhost:8737")  # typed with no scheme
    assert asked == [("GET", "/api/peer/state")]
    assert len(found["comparison"]) == 16 and found["synced_before"] is None
    assert found["peer"] == {"address": THERE, "server": sync.own_id(there.conn), "caracole": "0.1.0",
                             "name": there.cfg.library_name, "kind": "server", "made": None}
    mine, theirs = here.units(), there.units()
    assert [(d["label"], d["kind"], d["proposal"], d["why"]) for d in found["differences"]] == [
        ("Estopa - Tu Calorro", "song", "theirs", "only in theirs"),
        ("Muse - Hysteria", "song", "mine", "only here"),
        ("Oasis - Wonderwall", "song", "conflict", "in both books, different, never shared"),
        ("Radiohead - Creep", "song", "conflict", "in both books, different, never shared")]
    creep = by_label(found)["Radiohead - Creep"]
    assert creep["id"] == unit["Radiohead - Creep"]
    assert (creep["here"], creep["there"]) == (mine[creep["id"]].digest, theirs[creep["id"]].digest)
    assert by_label(found)["Muse - Hysteria"]["there"] is None
    assert sync.base_of(here.conn, sync.own_id(there.conn)) is None  # nothing written
    assert here.app.queue.snapshot() == []


def test_a_comparison_refuses_an_address_nothing_answering_and_this_very_caracole(computers, monkeypatch):
    here, there, _ = computers
    status, said = script(here.app, "/sync/compare", {"address": "ftp://desk"})
    assert status == 400 and "isn't the address of a caracole serve" in said["error"]

    db.kv_set(here.conn, sync.ID_KEY, sync.own_id(there.conn))  # a copy of the other's database
    status, said = script(here.app, "/sync/compare", {"address": THERE})
    assert status == 409 and "is this one" in said["error"] and "caracole peer new-id" in said["error"]

    def refused(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(sync_routes, "transport", lambda: httpx.MockTransport(refused))
    status, said = script(here.app, "/sync/compare", {"address": "192.168.1.20:8737"})
    assert status == 502 and said["error"].startswith("Nothing answered at http://192.168.1.20:8737")


def test_a_comparison_names_each_songs_artist_and_title_and_each_sides_change_and_part(computers):
    here, there, asked = computers
    two_conflicts(here, there)
    found = compared(here)
    assert found["peer"]["kind"] == "server" and found["peer"]["made"] is None
    assert found["holds"] == ["library", "songbooks", "indexes"]
    assert found["songbooks"] == {} and found["indexes"] == []
    assert asked == [("GET", "/api/peer/state")]  # no songbook differs: nothing more asked
    seen = {d["id"]: (d["names"], d["change"], d["part"], d["with"]) for d in found["differences"]}
    assert seen == {  # never synced: a side's alone is new there, both's changed on both
        CALORRO: ({"artist": "Estopa", "title": "Tu Calorro"}, [None, "new"], "library", []),
        HYSTERIA: ({"artist": "Muse", "title": "Hysteria"}, ["new", None], "library", []),
        WONDERWALL: ({"artist": "Oasis", "title": "Wonderwall"}, ["changed", "changed"], "library", []),
        CREEP: ({"artist": "Radiohead", "title": "Creep"}, ["changed", "changed"], "library", [])}

    # Synced once, then each side changed what it changed since: here Creep's own key, there Wonderwall's, a song new
    # there, and Hysteria removed there (its song gone, its tombstone new).
    synced(here, there)
    from caracole.overrides import add_version

    add_version(here.cfg.overrides_file, "Radiohead - Creep", "key=Bm&capo=0")
    add_version(there.cfg.overrides_file, "Oasis - Wonderwall", "key=Dm&capo=0")
    there.song("Blur", "Song 2", version=None)
    assert run(there, "remove", "--yes", "--", "Muse - Hysteria").exit_code == 0
    found = compared(here)
    seen = {d["id"]: (d["proposal"], d["change"], d["part"], d["names"]) for d in found["differences"]}
    assert seen == {
        "song/blur/song-2": ("theirs", [None, "new"], "library", {"artist": "Blur", "title": "Song 2"}),
        HYSTERIA: ("theirs", [None, "gone"], "library", {"artist": "Muse", "title": "Hysteria"}),
        WONDERWALL: ("theirs", [None, "changed"], "library", {"artist": "Oasis", "title": "Wonderwall"}),
        CREEP: ("mine", ["changed", None], "library", {"artist": "Radiohead", "title": "Creep"}),
        "removed/muse/hysteria": ("theirs", [None, "new"], "library", None)}


def test_a_songbook_difference_carries_both_documents_and_lists_its_songs(computers):
    here, there, asked = computers
    two_conflicts(here, there)
    make_songbook(songbooks_file(here.cfg.library_dir), "Campfire", ["Radiohead - Creep", "Muse - Hysteria"])
    make_songbook(songbooks_file(there.cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    make_songbook(songbooks_file(there.cfg.library_dir), "Road", ["Estopa - Tu Calorro"])
    found = compared(here)
    assert sorted(asked) == [("GET", "/api/peer/state"), ("GET", "/api/peer/unit"), ("GET", "/api/peer/unit")]
    assert found["songbooks"] == {
        "songbook/campfire": {"here": {"name": "Campfire", "songs": [["Radiohead - Creep", {}],
                                                                     ["Muse - Hysteria", {}]]},
                              "there": {"name": "Campfire", "songs": [["Radiohead - Creep", {}]]}},
        "songbook/road": {"here": None, "there": {"name": "Road", "songs": [["Estopa - Tu Calorro", {}]]}}}
    seen = {d["id"]: (d["part"], d["with"], d["names"], d["change"]) for d in found["differences"]}
    assert seen["songbook/campfire"] == ("songbooks", [], None, ["changed", "changed"])
    assert seen["songbook/road"] == ("songbooks", [], None, [None, "new"])
    # The songs either side's songbooks list, read from both sides' documents.
    assert seen[CREEP][1] == ["songbook/campfire"] and seen[HYSTERIA][1] == ["songbook/campfire"]
    assert seen[CALORRO][1] == ["songbook/road"] and seen[WONDERWALL][1] == []


def test_the_indexes_newer_on_either_side_are_listed_in_the_sites_order(computers):
    from caracole import gtptabs_fetch, musescore_fetch

    here, there, _ = computers
    db.kv_set(here.conn, ug_index.REFRESHED_KEY, "2026-11-01T03:30:00Z")
    db.kv_set(there.conn, ug_index.REFRESHED_KEY, "2026-11-02T03:30:00Z")  # newer there
    db.kv_set(there.conn, "lacuerda:index:complete_at", "2026-10-20T03:30:00Z")  # there alone
    db.kv_set(here.conn, gtptabs_fetch.SITE.complete_key, "2026-10-21T03:30:00Z")  # here alone
    for side in (here, there):  # the same on both: not waiting
        db.kv_set(side.conn, musescore_fetch.SITE.complete_key, "2026-10-22T03:30:00Z")
    found = compared(here)
    assert found["differences"] == []
    assert found["indexes"] == [
        {"site": "ug", "title": "Ultimate Guitar", "here": "2026-11-01T03:30:00Z", "there": "2026-11-02T03:30:00Z",
         "newer": "there"},
        {"site": "lacuerda", "title": "LaCuerda", "here": None, "there": "2026-10-20T03:30:00Z", "newer": "there"},
        {"site": "gtptabs", "title": "gtptabs.com", "here": "2026-10-21T03:30:00Z", "there": None, "newer": "here"}]
    db.kv_set(here.conn, ug_index.REFRESHED_KEY, "2026-11-03T03:30:00Z")
    assert compared(here)["indexes"][0]["newer"] == "here"


def test_a_comparison_is_made_with_the_answers_an_import_kept(computers):
    here, there, _ = computers
    two_conflicts(here, there)
    mine, theirs = here.units(), there.units()
    there_id = sync.own_id(there.conn)
    # An import of there's file here answered Creep "keep mine": while neither side changes it, it is here's to give.
    sync.record_kept(here.conn, there_id, {CREEP: (mine[CREEP].digest, theirs[CREEP].digest)},
                     "2026-11-02T21:10:00Z")
    found = compared(here)
    creep = by_id(found)[CREEP]
    assert (creep["proposal"], creep["why"], creep["change"]) == ("mine", sync.KEPT_HERE, [None, None])
    assert by_id(found)[WONDERWALL]["proposal"] == "conflict"
    # Its Sync names the comparison made with them, and the sync gives Creep there.
    ids = {d["label"]: d["id"] for d in found["differences"]}
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "",
                                                       "choices": f"there\t{ids['Oasis - Wonderwall']}"})
    assert status == 200, answer
    kept = sync.merged_kept(None, sync.kept_of(here.conn, there_id), None, {})
    hash_ = sync.compared_hash(sync.compare(mine, theirs, None, kept))
    assert f"--compared={hash_}" in here.app.queue.snapshot()[0].steps[0].args
    here.app.queue.run_pending()
    assert here.app.queue.snapshot()[0].state == "done"
    assert there.units()[CREEP].digest == mine[CREEP].digest


def test_a_units_two_documents_are_answered_for_a_comparison_kept_and_refused_otherwise(computers):
    from caracole.overrides import load_overrides

    here, there, asked = computers
    two_conflicts(here, there)
    found = compared(here)
    asked.clear()
    status, answer = script(here.app, f"/api/sync/unit?comparison={found['comparison']}&id={CREEP}")
    assert status == 200, answer
    assert asked == [("GET", "/api/peer/unit")]

    def document(side, unit_id):
        books = load_songbooks(songbooks_file(side.cfg.library_dir))
        return sync.unit_document(side.conn, side.cfg, load_overrides(side.cfg.overrides_file), books,
                                  unit_id)["unit"]

    assert answer == {"id": CREEP, "here": document(here, CREEP), "there": document(there, CREEP)}
    assert answer["here"]["overrides"] != answer["there"]["overrides"]  # its own key, as each side holds it
    status, answer = script(here.app, f"/api/sync/unit?comparison={found['comparison']}&id={HYSTERIA}")
    assert status == 200 and answer["there"] is None and answer["here"] == document(here, HYSTERIA)

    status, said = script(here.app, f"/api/sync/unit?comparison={found['comparison']}&id=song/not/compared")
    assert status == 404 and "isn't one that comparison found" in said["error"]
    status, said = script(here.app, f"/api/sync/unit?comparison=0123456789abcdef&id={CREEP}")
    assert status == 409 and said["error"] == sync_routes.GONE
    assert route_for("GET", "/api/sync/unit").script_only  # it asks the other caracole: the page's script alone
    refused = get(here.app, f"/api/sync/unit?comparison={found['comparison']}&id={CREEP}", accept="application/json")
    assert refused.status == 403


def test_the_indexes_route_says_each_sites_newest_read_and_its_tabs(computers):
    from test_index_transfer import EARLY, ug_sitemap

    here, _, asked = computers
    status, answer = script(here.app, "/api/sync/indexes")
    assert status == 200 and asked == []
    assert answer == {"indexes": {site: {"read": None, "tabs": 0} for site in index_transfer.SITES}}
    ug_sitemap(here.conn, "1", ["radiohead/creep-chords-4169", "oasis/wonderwall-chords-27596"], EARLY)
    db.kv_set(here.conn, "lacuerda:index:complete_at", "2026-11-02T12:00:00Z")
    _, answer = script(here.app, "/api/sync/indexes")
    assert list(answer["indexes"]) == list(index_transfer.SITES)
    assert answer["indexes"]["ug"] == {"read": "2026-10-19T03:30:00Z", "tabs": 2}
    assert answer["indexes"]["lacuerda"] == {"read": "2026-11-02T12:00:00Z", "tabs": 0}
    # The phone reads it as a client, no page: it is answered with no form token, as GET /api/peer/state is.
    assert get(here.app, "/api/sync/indexes").status == 200


# --- the sync ----------------------------------------------------------------------------------------------------


def test_sync_refuses_an_unchosen_conflict_a_comparison_past_and_choices_it_cant_read(computers):
    here, there, _ = computers
    two_conflicts(here, there)
    found = compared(here)
    creep = by_label(found)["Radiohead - Creep"]["id"]
    for fields, status, words in [
        ({"comparison": "0123456789abcdef", "prefer": "", "choices": ""}, 409, "compare the two again"),
        ({"comparison": found["comparison"], "prefer": "", "choices": f"here\t{creep}"}, 409,
         "Choose a side for every conflict first: 1 has none."),
        ({"comparison": found["comparison"], "prefer": "", "choices": "maybe\tsong/x"}, 400, "isn't a choice"),
        ({"comparison": found["comparison"], "prefer": "", "choices": "here\tsong/not/compared"}, 400,
         "isn't a choice"),
        ({"comparison": found["comparison"], "prefer": "", "choices": f"here\t{creep}\nthere\t{creep}"}, 400,
         "chosen two ways"),
        ({"comparison": found["comparison"], "prefer": "both", "choices": ""}, 400, "prefer is here, there"),
    ]:
        answer, said = script(here.app, "/sync/apply", fields)
        assert (answer, words in said["error"]) == (status, True), (fields, said)
    assert here.app.queue.snapshot() == []
    assert route_for("POST", "/sync/apply").limit == 1024 * 1024  # a choice a line, for a whole library's units


def test_sync_refuses_a_comparison_the_two_no_longer_agree_with_before_anything_is_queued(computers):
    here, there, _ = computers
    two_conflicts(here, there)
    found = compared(here)
    there.song("Muse", "Uprising", version=None)  # there moved on since
    status, said = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "here",
                                                     "choices": ""})
    assert status == 409 and said["error"] == sync_routes.STALE
    assert here.app.queue.snapshot() == []
    status, said = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "here",
                                                     "choices": ""})
    assert status == 409 and said["error"] == sync_routes.GONE  # that comparison is gone


def test_two_computers_sync_through_the_tabs_routes_and_end_with_no_differences(computers):
    here, there, asked = computers
    two_conflicts(here, there)
    found = compared(here)
    ids = {d["label"]: d["id"] for d in found["differences"]}
    # As the tab sends them: every conflict's choice, and one proposal flipped (Muse, here alone, given there all the
    # same as proposed: a choice equal to the proposal changes nothing).
    choices = f"here\t{ids['Radiohead - Creep']}\nthere\t{ids['Oasis - Wonderwall']}\nhere\t{ids['Muse - Hysteria']}"
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "",
                                                       "choices": choices})
    assert status == 200, answer
    queued = answer["job"]
    assert queued["kind"] == "sync" and queued["display"] == f"Sync with {there.cfg.library_name}"
    assert queued["details"] == "#tab=sync" and queued["songId"] is None and queued["outcome"] is None
    assert [s["name"] for s in queued["steps"]] == [name for name, _ in PEER_SYNC_STAGES]
    (job,) = here.app.queue.snapshot()
    hash_ = sync.compared_hash(sync.compare(here.units(), there.units(), None))
    assert job.steps[0].args == ("peer", "sync", "--push", "--yes", "--progress", f"--compared={hash_}",
                                 f"--choose=here:{ids['Radiohead - Creep']}",
                                 f"--choose=there:{ids['Oasis - Wonderwall']}",
                                 f"--choose=here:{ids['Muse - Hysteria']}", "--", THERE)
    # A second Sync while it waits: refused, never a second job.
    again = compared(here)
    status, said = script(here.app, "/sync/apply", {"comparison": again["comparison"], "prefer": "here",
                                                     "choices": ""})
    assert status == 409 and "on its way already" in said["error"]

    asked.clear()
    here.app.queue.run_pending()
    (job,) = here.app.queue.snapshot()
    assert job.state == "done", [s.output for s in job.steps]
    assert ("POST", "/peer/pull") not in asked  # given by a push: there needn't reach here
    status, polled = script(here.app, f"/jobs.json?jobs={job.id}")
    (seen,) = polled["jobs"]
    assert seen["line"] == {"tone": "ready", "text": "Synced", "link": None, "details": None}
    assert [(s["name"], s["state"]) for s in seen["steps"]] == [("compare", "done"), ("take", "done"),
                                                                 ("give", "done"), ("agree", "done"),
                                                                 ("index", "skipped")]
    outcome = seen["outcome"]
    assert sorted(outcome["taken"]) == sorted([ids["Oasis - Wonderwall"], ids["Estopa - Tu Calorro"]])
    assert sorted(outcome["given"]) == sorted([ids["Radiohead - Creep"], ids["Muse - Hysteria"]])
    assert outcome["left"] == [] and outcome["indexed"] == [] and outcome["agreed"] == len(here.units())

    assert here.units() == there.units()
    after = compared(here)
    assert after["differences"] == [] and isinstance(after["synced_before"], str)
    status, state = script(here.app, "/api/sync")
    assert state["address"] == THERE and [(p["server"], p["name"]) for p in state["peers"]] == [
        (sync.own_id(there.conn), there.cfg.library_name)]
    # Nothing differing, Sync still runs: it keeps what the two agree on.
    status, answer = script(here.app, "/sync/apply", {"comparison": after["comparison"], "prefer": "", "choices": ""})
    assert status == 200, answer
    here.app.queue.run_pending()
    last = here.app.queue.snapshot()[0]
    assert last.state == "done" and [(s.name, s.state) for s in last.stages] == [
        ("compare", "done"), ("take", "skipped"), ("give", "skipped"), ("agree", "done"), ("index", "skipped")]


def test_sync_queues_its_parts_and_refuses_a_part_it_doesnt_know(computers):
    from caracole.commands.peer import NOT_A_PART

    here, there, _ = computers
    two_conflicts(here, there)
    found = compared(here)
    for parts in ("lyrics", "library,lyrics", "", " , "):
        status, said = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "here",
                                                         "choices": "", "parts": parts})
        assert (status, said["error"]) == (400, NOT_A_PART), parts
    assert sync_routes.NOT_A_PART == NOT_A_PART and here.app.queue.snapshot() == []
    # Every conflict is a song's: of the songbooks alone, none is to choose. The parts in their own order.
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "",
                                                       "choices": "", "parts": "indexes, songbooks"})
    assert status == 200, answer
    (job,) = here.app.queue.snapshot()
    assert job.steps[0].args[:6] == ("peer", "sync", "--push", "--yes", "--progress", "--parts=songbooks,indexes")
    assert job.steps[0].args[6].startswith("--compared=") and job.steps[0].args[-2:] == ("--", THERE)


def test_a_conflict_of_a_part_asked_for_still_needs_a_side(computers):
    here, there, _ = computers
    two_conflicts(here, there)
    make_songbook(songbooks_file(here.cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    found = compared(here)
    for parts in ("library", "songbooks"):  # Creep, a conflict, comes along with the songbook that lists it
        status, said = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "",
                                                         "choices": "", "parts": parts})
        assert status == 409 and said["error"].startswith("Choose a side for every conflict first"), parts
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "",
                                                       "choices": f"here\t{CREEP}", "parts": "songbooks"})
    assert status == 200, answer


def test_a_comparison_kept_without_its_differences_still_needs_a_side_for_every_conflict(computers):
    # One kept by another route with its proposals alone (``found`` left out): every conflict needs a side, whatever
    # the parts, rather than none.
    import dataclasses

    here, there, _ = computers
    two_conflicts(here, there)
    found = compared(here)
    kept = sync_routes._kept_one(here.app, found["comparison"])
    sync_routes._keep(here.app, dataclasses.replace(kept, found=()))
    made = list(sync_routes._kept[here.app])[-1]
    status, said = script(here.app, "/sync/apply", {"comparison": made, "prefer": "", "choices": "",
                                                     "parts": "indexes"})
    assert status == 409 and said["error"] == "Choose a side for every conflict first: 2 have none.", said


def test_a_units_two_documents_are_refused_for_a_comparison_of_a_file(computers):
    import dataclasses

    here, there, asked = computers
    two_conflicts(here, there)
    found = compared(here)
    kept = sync_routes._kept_one(here.app, found["comparison"])
    sync_routes._keep(here.app, dataclasses.replace(kept, source="file", kind="file"))
    made = list(sync_routes._kept[here.app])[-1]
    asked.clear()
    status, said = script(here.app, f"/api/sync/unit?comparison={made}&id={CREEP}")
    assert status == 409 and "is of a file" in said["error"] and asked == []


def test_two_computers_sync_songbooks_alone_through_the_routes(computers):
    here, there, _ = computers
    two_conflicts(here, there)
    make_songbook(songbooks_file(here.cfg.library_dir), "Campfire", ["Muse - Hysteria"])
    job = synced(here, there, prefer="", parts="songbooks")
    assert "--parts=songbooks" in job.steps[0].args
    # The songbook and the song it lists, given there; the library's other differences as they were.
    assert [b.texts for b in load_songbooks(songbooks_file(there.cfg.library_dir))] == [("Muse - Hysteria",)]
    mine, theirs = here.units(), there.units()
    assert theirs[HYSTERIA].digest == mine[HYSTERIA].digest and "songbook/campfire" in theirs
    assert CALORRO not in mine and mine[CREEP].digest != theirs[CREEP].digest
    left = [d["id"] for d in compared(here)["differences"]]
    assert left == [CALORRO, WONDERWALL, CREEP]


def test_a_sync_that_leaves_a_unit_says_how_many_and_why_and_its_next_step_is_a_comparison_afresh(computers):
    from caracole.web.outcome import outcome, steps
    from caracole.web.status import job_line

    here, there, _ = computers
    two_conflicts(here, there)
    found = compared(here)
    ids = {d["label"]: d["id"] for d in found["differences"]}
    choices = f"skip\t{ids['Radiohead - Creep']}\nthere\t{ids['Oasis - Wonderwall']}"
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "",
                                                       "choices": choices})
    assert status == 200, answer
    here.app.queue.run_pending()
    (job,) = here.app.queue.snapshot()
    _, polled = script(here.app, f"/jobs.json?jobs={job.id}")
    (seen,) = polled["jobs"]
    assert seen["line"] == {"tone": "waiting", "text": "Synced: 1 change left as it was", "link": None,
                            "details": f"#tab=requests&job={job.id}"}
    assert seen["outcome"]["left"] == [[ids["Radiohead - Creep"], "skipped, as you chose"]]
    said = outcome(job, job_line(job, None))
    assert (said.tone, said.word, said.reason) == ("waiting", "Synced", "Took 2 changes here and gave 1 change "
                                                                        "there. 1 change left as it was.")
    assert said.action.label == "Compare again" and said.action.href == "/#tab=sync"
    assert [(c.name, c.state) for c in steps(job)] == [("Compare", "done"), ("Take", "done"), ("Give", "done"),
                                                       ("Agree", "done")]


def test_the_library_page_has_the_sync_tab_last(computers):
    here, _, _ = computers
    page = get(here.app, "/").body.decode("utf-8")
    assert page.index('id="tab-requests"') < page.index('id="tab-sync"')
    assert '<section class="view sync" id="sync"' in page and page.count('<dialog class="sync-sheet" id="sync-sheet"') == 1


# --- the shapes the sheet's tests draw (test_sync_sheet.py's FakeSync), as the real routes answer them -----------


def shape(value):
    """A value's shape: an object's keys each with its value's shape (``songbooks``, a comparison's map by unit, its
    first value's alone), a list's first item's, else its type's name: a string "text", a null "null" (which stands
    where any value may)."""
    if isinstance(value, dict):
        return {k: ({"<unit>": shape(next(iter(v.values())))} if k == "songbooks" and isinstance(v, dict) and v
                    else shape(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return "null" if value is None else "text" if isinstance(value, str) else type(value).__name__


def fits(fake, real, *, whole: bool = True) -> bool:
    """Whether the shape ``fake`` (the sheet's fake's) is the shape ``real`` (the route's): an object's members each
    fitting, the same members (``whole``) or the fake's among the real's (a document the page reads some of); a list's
    first items; a null for any value, on either side; else the same."""
    if fake == "null" or real == "null":
        return True
    if isinstance(fake, dict):
        return isinstance(real, dict) and (not whole or set(fake) == set(real)) and all(
            k in real and fits(v, real[k], whole=whole) for k, v in fake.items())
    if isinstance(fake, list):
        return isinstance(real, list) and (not fake or not real or fits(fake[0], real[0], whole=whole))
    return fake == real


def unit_fits(fake, real) -> bool:
    """A GET /api/sync/unit's answer as the fake's: its members whole, each document's those the page reads."""
    return set(fake) == set(real) and all(fits(shape(fake[k]), shape(real[k]), whole=False)
                                          for k in ("here", "there")) and fake["id"].split("/")[0] == "song"


def polled(app, job_id):
    """A job's view once over, as /jobs.json gives it to the page, its queue run first."""
    app.queue.run_pending()
    _, seen = script(app, f"/jobs.json?jobs={job_id}")
    over = dict(seen["jobs"][0])
    over.pop("songbooks", None)  # the Songbooks tab's, which /jobs.json adds to a job asked about once it is over
    return over


def test_the_sheets_fake_answers_are_shaped_as_the_real_routes_answer(computers):
    """Every answer test_sync_sheet.py's FakeSync gives is shaped as the real route's: GET /api/sync, POST /sync/test,
    POST /sync/compare (a songbook and an index differing), GET /api/sync/unit (a network sync's and a file's), POST
    /sync/apply and the sync's view as it is queued and once over with its report, GET /api/sync/sizes, POST
    /sync/export, POST /sync/import/compare and a file's Sync, its view and its report."""
    from caracole import gtptabs_fetch, site_index

    from test_sync_sheet import (COMPARISON, EXPORTED, FILE_COMPARISON, FILE_REPORT, REPORT, SIZES, STATE, TESTED,
                                 UNITS, VIEWS)
    from test_web_sync_files import file_compared, sent
    from test_web_sync_files import script as json_script

    here, there, _ = computers
    two_conflicts(here, there)
    make_songbook(songbooks_file(there.cfg.library_dir), "Campfire", ["Radiohead - Creep"])  # a songbook differs
    site = gtptabs_fetch.SITE  # and an index, read there alone
    site_index._store(there.conn, site, "sitemap-tabs-1.xml", [site.row("https://gtptabs.com/tabs/2/blur.html")],
                      {"etag": '"1"', "last_modified": None}, datetime(2026, 11, 2, 8, tzinfo=UTC))
    db.kv_set_json(here.conn, f"sync:peer:{sync.own_id(there.conn)}", {
        "address": THERE, "name": "Desk", "synced_at": "2026-11-02T21:04:00Z"})
    status, state = script(here.app, "/api/sync")
    assert status == 200 and state["peers"] and fits(shape(STATE), shape(state))
    status, tested = script(here.app, "/sync/test", {"address": THERE})
    assert status == 200 and fits(shape(TESTED), shape(tested)), (shape(TESTED), shape(tested))
    found = compared(here)
    assert found["songbooks"] and found["indexes"] and by_id(found)[CREEP]["with"] == ["songbook/campfire"]
    assert fits(shape(COMPARISON), shape(dict(found, synced_before="2026-11-02T21:04:00Z"))), (
        shape(COMPARISON), shape(found))
    assert {d["kind"] for d in found["differences"]} <= set(sync_routes_kinds())
    status, unit = script(here.app, f"/api/sync/unit?comparison={found['comparison']}&id={CREEP}")
    fake_unit = {"id": "song/eagles/hotel california", **UNITS["song/eagles/hotel california"]}
    assert status == 200 and unit_fits(fake_unit, unit), (shape(fake_unit), shape(unit))

    # Export and import: there's library in a file, imported here as a sync with it.
    status, sizes = script(there.app, "/api/sync/sizes")
    assert status == 200 and fits(shape(SIZES), shape(sizes)), (shape(SIZES), shape(sizes))
    status, made = json_script(there.app, "/sync/export", {"parts": ["library", "songbooks"]})
    assert status == 200 and fits(shape(EXPORTED), shape(made)), made
    file = get(there.app, f"/api/sync/export?export={made['export']}")
    data = file.stream.read() if file.stream is not None else file.body
    if file.stream is not None:
        file.stream.close()
    status, from_file = file_compared(here.app, sent(here.app, data, made["name"]))
    assert status == 200 and fits(shape(FILE_COMPARISON), shape(from_file)), (shape(FILE_COMPARISON),
                                                                              shape(from_file))
    status, unit = script(here.app, f"/api/sync/unit?comparison={from_file['comparison']}&id={CREEP}")
    assert status == 200 and unit["there"] is not None and unit_fits(fake_unit, unit), unit
    choices = "\n".join(f"here\t{d['id']}" for d in from_file["differences"] if d["proposal"] == "conflict")
    status, answer = script(here.app, "/sync/apply", {"comparison": from_file["comparison"], "prefer": "",
                                                       "choices": choices})
    assert status == 200 and fits(shape(VIEWS[0]), shape(answer["job"])), (shape(VIEWS[0]), shape(answer["job"]))
    over = polled(here.app, answer["job"]["id"])
    assert over["state"] == "done", over
    assert fits(shape(VIEWS[-1]), shape(over)) and fits(shape(FILE_REPORT), shape(over["outcome"]["report"]))

    # The network sync, compared again since the import, its view queued and once over, with its report.
    found = compared(here)
    status, answer = script(here.app, "/sync/apply", {"comparison": found["comparison"], "prefer": "here",
                                                       "choices": ""})
    assert status == 200 and fits(shape(VIEWS[0]), shape(answer["job"])), (shape(VIEWS[0]), shape(answer["job"]))
    over = polled(here.app, answer["job"]["id"])
    assert over["state"] == "done", over
    report = over["outcome"]["report"]
    assert report["indexes"] and fits(shape(VIEWS[-1]), shape(over)), (shape(VIEWS[-1]), shape(over))
    assert fits(shape(REPORT), shape(report)), (shape(REPORT), shape(report))


def sync_routes_kinds():
    """The kinds a difference may be of, as the tab groups them: peer_sync's, in its order."""
    return ("song", "removed", "songbook", "alias", "artist_url", "block")


def test_the_kinds_the_tab_groups_are_peer_syncs():
    from caracole.library_assets import HERE

    assert sync._KINDS == sync_routes_kinds()
    script_text = (HERE / "sync.js").read_text(encoding="utf-8")
    assert all(f'["{kind}", ' in script_text for kind in sync._KINDS)


# --- jobs as the views and the vectors give them -----------------------------------------------------------------


def peer_job(kind: str, state: str, stages: dict[str, tuple[str, str]] | None = None, *, units=(), output=(),
             job_id: int = 41, name: str = "Desk", address: str = "http://192.168.1.20:8737") -> Job:
    """A sync's (``kind`` "sync"), a file's import ("import"), a take's ("peer-push") or an index export's merge
    ("index-merge") job of caracole serve's as its queue would hold it in ``state``: its stages as
    ``stages`` says (name: (state, detail); waiting else; a running one's detail its running detail too), its
    ``units`` as its command said them, ``output`` its step's last lines."""
    when = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)
    if kind == "index-merge":
        names = jobs.INDEX_MERGE_STAGES
        made = jobs.index_merge_job(Path("/state/peer/index-0123456789abcdef.sqlite"))
        title, key, (label, args) = made["title"], made["song_key"], made["steps"][0]
    elif kind == "sync":
        title = f"Sync with {name}"
        args = ("peer", "sync", "--push", "--yes", "--progress", "--compared=" + "0" * 64, "--", address)
        key, names, label = sync_routes.SYNCING + address, PEER_SYNC_STAGES, title
    elif kind == "import":  # a sync with a file (sync_file_routes.py), of kind "sync" as the page names it
        from caracole.commands.peer import PEER_IMPORT_STAGES

        title = f"Sync with a file from {name}"
        args = ("peer", "import", "--yes", "--progress", "--compared=" + "0" * 64, "--",
                "/state/peer/import-0123456789abcdef")
        key, names, label = sync_routes.IMPORTING + "0123456789abcdef", PEER_IMPORT_STAGES, title
    else:
        title = f"Changes from {name}"
        args = ("peer", "take", "--progress", "--", "/state/peer/push-0123456789abcdef")
        key, names, label = "peer-push:0f1e2d3c4b5a6978", PEER_TAKE_STAGES, "Taking 3 changes"
    made = []
    for stage, stage_label in names:
        said, detail = (stages or {}).get(stage, ("waiting", ""))
        made.append(Stage(stage, stage_label, said, detail, detail if said == "running" else ""))
    step_state = {"queued": "waiting", "running": "running", "done": "done", "failed": "failed",
                  "cancelled": "skipped", "interrupted": "interrupted"}[state]
    return Job(job_id, title, key, [Step(label, args, step_state, output=list(output))], display=title, state=state,
               queued_at=when, started_at=None if state in ("queued", "cancelled") else when,
               finished_at=when if state not in ("queued", "running") else None, stages=made,
               units=list(units))


def test_a_syncs_view_while_it_runs_is_its_running_stage_and_once_over_what_it_did():
    running = peer_job("sync", "running", {"compare": ("done", "4 differences"), "take": ("running", "2 changes")})
    seen = view(running, [running], None, None)
    assert seen["line"]["text"] == "Taking their entries…" and seen["outcome"] is None
    assert seen["steps"][1] == {"name": "take", "label": "Take", "state": "running", "detail": "2 changes"}
    # A crash in its take: the line is the error, never what the stage said while it ran.
    crashed = peer_job("sync", "failed", {"compare": ("done", "4 differences"), "take": ("running", "2 changes")},
                       output=["error: The caracole at http://192.168.1.20:8737 answered 500. Try again later."])
    crashed.stages[1].state = "failed"
    assert view(crashed, [crashed], None, None)["line"]["text"] == (
        "The caracole at http://192.168.1.20:8737 answered 500.")
    stale = peer_job("sync", "failed", {"compare": ("failed", sync_routes.STALE)},
                     output=["error: " + sync_routes.STALE])
    assert view(stale, [stale], None, None)["line"]["text"] == "The two changed since that comparison: compare " \
                                                                "them again, and choose again."
    taken = peer_job("peer-push", "done", {"check": ("done", "3 changes from Phone"), "take": ("done", "took 3"),
                                           "render": ("done", ""), "agree": ("done", "12 units the two agree on")},
                     units=[("song/a/b", "taken", ""), ("song/c/d", "taken", ""), ("songbook/e", "taken", "")])
    seen = view(taken, [taken], None, None)
    assert (seen["kind"], seen["line"]["text"]) == ("peer-push", "Taken")
    assert seen["outcome"] == {"taken": ["song/a/b", "song/c/d", "songbook/e"], "given": [], "left": [],
                               "agreed": 12, "indexed": []}
    nothing = peer_job("peer-push", "done", {"check": ("done", ""), "take": ("failed", "Nothing taken: no backup of "
                                             "the database first, not enough room.")},
                       units=[("song/a/b", "left", "Nothing taken: no backup of the database first, not enough room.")])
    assert view(nothing, [nothing], None, None)["line"] == {
        "tone": "waiting", "text": "Nothing taken: no backup of the database first, not enough room.", "link": None,
        "details": "#tab=requests&job=41"}


def test_another_caracoles_index_pages_are_a_job_of_no_song_with_one_stage():
    # skeleton-m4's job kind: caracole index merge --delete --progress -- FILE, whose command and route lane
    # index-push writes.
    queue = jobs.JobQueue(lambda args, say: 0)
    path = Path("/state/peer/index-0123456789abcdef.sqlite")
    made, new = queue.submit(**jobs.index_merge_job(path))
    assert new and made.song_id is None and [(s.name, s.state) for s in made.stages] == [("merge", "waiting")]
    assert made.steps[0].args == ("index", "merge", "--delete", "--progress", "--", str(path))
    running = peer_job("index-merge", "running", {"merge": ("running", "")})
    seen = view(running, [running], None, None)
    assert seen["kind"] == "index-merge" and seen["line"]["text"] == "Merging the other caracole's index pages…"
    assert seen["steps"] == [{"name": "merge", "label": "Merge", "state": "running", "detail": ""}]
    done = peer_job("index-merge", "done", {"merge": ("done", "merged 12 pages: ug, lacuerda")})
    assert view(done, [done], None, None)["line"]["text"] == "Merged"
