"""The site indexes between two computers' caracoles: what ``caracole peer sync`` asks the other side for and gives it
of them (peer_sync.py ``Peer.index``, peer_import.py ``Uploader``), against the other library's caracole serve (a
WebApp in this process), as tests/test_commands_peer.py asks it."""

from __future__ import annotations

import json
import sqlite3
import stat
from datetime import UTC, datetime

import httpx
import pytest

from caracole import backup, index_transfer, peer_import, site_index
from caracole import peer_sync as sync
from caracole.web import sync_file_routes
from caracole.web.app import Request, WebApp

from test_commands_peer import HOST, InProcess, Side, run
from test_commands_peer_file import exported, gtptabs_index, libraries  # noqa: F401  (the fixture)

THERE = f"http://{HOST}"
# Its routes' limits are read as it is imported: before any test here makes the parts smaller (PART_MAX).
assert sync_file_routes.ROUTES
READ = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)


@pytest.fixture
def sides(tmp_path, monkeypatch):
    """This library (here) and another's (there), whose caracole serve answers at THERE: each request it is sent
    recorded, by its method and path."""
    here, there = Side(tmp_path / "here"), Side(tmp_path / "there", InProcess())
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.method, request.url.path))
        answer = WebApp.finish(there.app.handle(Request(request.method, request.url.raw_path.decode(),
                                                        dict(request.headers), request.content)))
        body = answer.body if answer.stream is None else answer.stream.read()
        if answer.stream is not None:
            answer.stream.close()
        return httpx.Response(answer.status, headers=answer.headers, content=body)

    transport = httpx.MockTransport(handler)
    yield here, there, asked, transport
    here.conn.close()
    there.conn.close()


def gtptabs_rows(side, locs, at=READ):
    from caracole import gtptabs_fetch

    site = gtptabs_fetch.SITE
    site_index._store(side.conn, site, "sitemap-tabs-1.xml", [site.row(loc) for loc in locs],
                      {"etag": '"1"', "last_modified": None}, at)


def rows_of(path, table):
    file = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return file.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        file.close()


# --- the other side's indexes, taken ------------------------------------------------------------------------------


def test_the_others_indexes_of_the_sites_asked_are_streamed_into_a_file_of_their_own(sides, tmp_path):
    _, there, asked, transport = sides
    gtptabs_rows(there, ["https://gtptabs.com/tabs/2/blur.html", "https://gtptabs.com/tabs/2/blur/beetlebum.html"])
    to = tmp_path / "theirs.sqlite"
    with sync.Peer(THERE, transport=transport) as peer:
        peer.index(to, ["gtptabs"])
    assert asked == [("GET", "/api/peer/index")]
    assert stat.S_IMODE(to.stat().st_mode) == 0o600
    assert index_transfer._meta(to)["sites"] == '["gtptabs"]' and rows_of(to, "gtptabs_index") == 2


def test_a_refused_ask_for_the_indexes_is_said_and_leaves_no_file(sides, tmp_path):
    _, _, _, transport = sides
    to = tmp_path / "theirs.sqlite"
    with sync.Peer(THERE, transport=transport) as peer, pytest.raises(sync.PeerError, match="answered 400: no site"):
        peer.index(to, ["nosuch"])
    assert not to.exists()

    def older(request):  # a caracole serve older than the route
        return httpx.Response(404, json={"error": "Not found"})

    with sync.Peer(THERE, transport=httpx.MockTransport(older)) as peer, pytest.raises(sync.PeerError):
        peer.index(to, [])
    assert not to.exists()


# --- this side's indexes, given ----------------------------------------------------------------------------------


def test_an_upload_sends_a_file_to_the_others_import_in_parts_as_its_page_does(sides, tmp_path, monkeypatch):
    _, there, asked, transport = sides
    monkeypatch.setattr(peer_import, "PART_MAX", 1000)  # the parts there say they may be: 1000 bytes
    data = bytes(range(256)) * 10
    path = tmp_path / "caracole-index.sqlite"
    path.write_bytes(data)
    with peer_import.Uploader(THERE, transport=transport) as uploader:
        import_id = uploader.upload(path)
    assert asked == [("GET", "/api/peer/state"), ("POST", "/sync/import/open"),
                     *[("POST", "/sync/import/part")] * 3]
    assert peer_import.whole(there.cfg.state_dir, import_id).read_bytes() == data
    folder = there.cfg.state_dir / "peer" / f"import-{import_id}"
    assert peer_import.opened_name(folder) == "caracole-index.sqlite"


def test_an_upload_the_other_side_refuses_is_said(sides, tmp_path):
    _, there, _, transport = sides
    path = tmp_path / "caracole-index.sqlite"
    path.write_bytes(b"x" * 10)
    peer_import.open_import(there.cfg.state_dir, size=4, name="another.caracole")  # one is open there already
    with peer_import.Uploader(THERE, transport=transport) as uploader:
        with pytest.raises(sync.PeerError, match="answered 409: " + peer_import.BUSY.split(":")[0]):
            uploader.upload(path)


def test_an_upload_that_fails_partway_is_dropped_there_and_the_next_one_opens_at_once(sides, tmp_path,
                                                                                     monkeypatch):
    _, there, asked, transport = sides
    monkeypatch.setattr(peer_import, "PART_MAX", 1000)
    path = tmp_path / "caracole-index.sqlite"
    path.write_bytes(b"x" * 2500)
    real = peer_import.add_part
    parts = []

    def refused_second(state_dir, import_id, at, data):
        parts.append(at)
        if len(parts) == 2:
            raise peer_import.StagingError(peer_import.NOT_NEXT)
        return real(state_dir, import_id, at, data)

    monkeypatch.setattr(peer_import, "add_part", refused_second)
    with peer_import.Uploader(THERE, transport=transport) as uploader, pytest.raises(sync.PeerError):
        uploader.upload(path)
    assert ("POST", "/sync/import/drop") in asked
    assert peer_import._imports(there.cfg.state_dir / "peer") == []  # dropped there, not left an hour
    monkeypatch.setattr(peer_import, "add_part", real)
    with peer_import.Uploader(THERE, transport=transport) as uploader:
        import_id = uploader.upload(path)
    assert peer_import.whole(there.cfg.state_dir, import_id).read_bytes() == b"x" * 2500


# --- peer sync's index stage, both ways --------------------------------------------------------------------------


@pytest.fixture
def syncing(tmp_path, monkeypatch):
    """Here and there, each a library with its caracole serve; ``caracole peer`` here asks there's over HTTP, whose
    queue runs what it queued through the CLI as it is asked how a job goes (an import of the indexes given, a push's
    take). Each request there recorded; renders recorded, not made."""
    here, there = Side(tmp_path / "here", InProcess()), Side(tmp_path / "there", InProcess())
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.method, request.url.path))
        if request.url.path.startswith("/api/jobs/"):
            there.app.queue.run_pending()
        answer = WebApp.finish(there.app.handle(Request(request.method, request.url.raw_path.decode(),
                                                        dict(request.headers), request.content)))
        body = answer.body if answer.stream is None else answer.stream.read()
        if answer.stream is not None:
            answer.stream.close()
        return httpx.Response(answer.status, headers=answer.headers, content=body)

    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr("caracole.commands.peer._sleep", lambda seconds: None)
    monkeypatch.setattr("caracole.render.render_all", lambda conn, cfg, overrides, **kw: None)
    yield here, there, asked
    here.conn.close()
    there.conn.close()


BLUR = ["https://gtptabs.com/tabs/2/blur.html", "https://gtptabs.com/tabs/2/blur/beetlebum.html"]


def synced(here, *args):
    from caracole.get import read_progress_line

    result = run(here, "peer", "sync", THERE, "--push", "--yes", "--progress", *args)
    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    return result, events


def stage(events, name):
    return [(e["state"], e.get("detail", "")) for e in events if e.get("stage") == name]


def reports(events):
    return [e["report"] for e in events if e.get("event") == "report"]


def leftovers(side):
    folder = side.cfg.cache_dir / "peer"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_a_site_read_more_recently_there_is_taken_and_counted(syncing):
    here, there, asked = syncing
    gtptabs_rows(there, BLUR)
    result, events = synced(here)
    assert result.exit_code == 0, result.output
    assert stage(events, "index") == [
        ("running", "taking 1"), ("running", "Comparing with this database's indexes"),
        ("running", "Backing up the database first"), ("running", "gtptabs.com"),
        ("running", "gtptabs.com · 1 sitemap"), ("done", "took 1 index")]
    assert index_transfer.tab_counts(here.conn)["gtptabs"] == 2
    assert index_transfer.newest(here.conn)["gtptabs"] == index_transfer.newest(there.conn)["gtptabs"]
    assert ("GET", "/api/peer/index") in asked and ("POST", "/sync/import/open") not in asked
    (report,) = reports(events)
    assert report["with"] == {"name": there.cfg.library_name, "kind": "server", "address": THERE}
    assert report["parts"] == ["library", "songbooks", "indexes"] and report["at"].endswith("Z")
    assert report["indexes"] == [{"site": "gtptabs", "title": "gtptabs.com", "direction": "taken", "before": 0,
                                  "after": 2, "read": "2026-11-02T08:00:00Z"}]
    assert leftovers(here) == []  # the copy taken, deleted once merged
    assert [b.label for b in backup.backups(here.cfg.state_dir)] == [backup.MERGE]  # the merge's, first


def test_a_site_read_more_recently_here_is_given_through_the_others_import_and_counted_there(syncing):
    here, there, asked = syncing
    gtptabs_rows(here, BLUR)
    result, events = synced(here)
    assert result.exit_code == 0, result.output
    assert stage(events, "index") == [
        ("running", "giving 1"), ("running", "Exporting 1 index to give"),
        ("running", "Sending 1 index to the other side"),
        ("running", "Waiting for the other side to merge 1 index"), ("done", "gave 1 index")]
    assert index_transfer.tab_counts(there.conn)["gtptabs"] == 2
    assert index_transfer.newest(there.conn)["gtptabs"] == "2026-11-02T08:00:00Z"
    posted = [p for m, p in asked if m == "POST"]
    assert posted == ["/sync/import/open", "/sync/import/part", "/sync/import/compare", "/sync/apply"]
    assert asked.count(("GET", "/api/sync/indexes")) == 2  # before it is given, and once its import is over
    (job,) = there.app.queue.snapshot()
    assert job.state == "done" and job.display.startswith("Sync with a file from ")
    assert job.steps[0].args[:4] == ("peer", "import", "--yes", "--progress")
    assert "--parts=indexes" in job.steps[0].args
    assert job.song_key.startswith("import:") and job.report["indexes"][0]["site"] == "gtptabs"
    (report,) = reports(events)
    assert report["indexes"] == [{"site": "gtptabs", "title": "gtptabs.com", "direction": "given", "before": 0,
                                  "after": 2, "read": "2026-11-02T08:00:00Z"}]
    assert leftovers(here) == [] and peer_import._imports(there.cfg.state_dir / "peer") == []


def musescore_rows(side, locs, at=READ):
    from caracole import musescore_fetch

    site = musescore_fetch.SITE
    site_index._store(side.conn, site, "song-1", [site.row(loc) for loc in locs],
                      {"etag": '"1"', "last_modified": None}, at)


def test_a_sync_that_takes_and_gives_says_the_give_once_the_take_is_merged(syncing):
    """The take's merge says its steps; the give then says its own, so the take's last never stands for the give."""
    here, there, asked = syncing
    gtptabs_rows(there, BLUR)
    musescore_rows(here, ["https://musescore.com/song/wonderwall-1524"])
    result, events = synced(here)
    assert result.exit_code == 0, result.output
    said = stage(events, "index")
    assert said[0] == ("running", "taking 1, giving 1") and said[-1] == ("done", "took 1 index, gave 1 index")
    merged = said.index(("running", "gtptabs.com · 1 sitemap"))
    assert said[merged + 1:-1] == [
        ("running", "Exporting 1 index to give"), ("running", "Sending 1 index to the other side"),
        ("running", "Waiting for the other side to merge 1 index")]
    assert index_transfer.tab_counts(here.conn)["gtptabs"] == 2
    assert index_transfer.tab_counts(there.conn)["musescore"] == 1


def test_nothing_newer_skips_the_index_stage(syncing):
    here, there, asked = syncing
    result, events = synced(here)
    assert result.exit_code == 0, result.output
    assert stage(events, "index") == [("skipped", "no index is newer on either side")]
    assert reports(events)[0]["indexes"] == []
    gtptabs_rows(here, BLUR)
    gtptabs_rows(there, BLUR)  # read at the same time on both sides: neither newer
    asked.clear()
    result, events = synced(here)
    assert stage(events, "index") == [("skipped", "no index is newer on either side")]
    assert ("GET", "/api/peer/index") not in asked and ("POST", "/sync/import/open") not in asked
    gtptabs_rows(there, BLUR, at=datetime(2026, 11, 3, 8, 0, tzinfo=UTC))
    result, events = synced(here, "--parts=library,songbooks")  # newer there, but the indexes aren't synced
    assert stage(events, "index") == [("skipped", "Site indexes aren't synced this time")]
    assert reports(events)[0]["parts"] == ["library", "songbooks"] and reports(events)[0]["indexes"] == []


def test_indexes_that_cant_be_given_say_so_and_the_sync_exits_1_once_the_rest_is_done(syncing, monkeypatch):
    here, there, _ = syncing
    here.song()
    gtptabs_rows(here, BLUR)
    peer_import.open_import(there.cfg.state_dir, size=4, name="another.caracole")  # being sent there: busy
    peer_import.add_part(there.cfg.state_dir, peer_import._imports(there.cfg.state_dir / "peer")[0].name[7:], 0,
                         b"ha")
    result, events = synced(here)
    assert result.exit_code == 1
    assert stage(events, "agree")[-1][0] == "done" and here.units() == there.units()  # the rest is done
    (state, detail), = [s for s in stage(events, "index") if s[0] == "failed"]
    assert "answered 409" in detail and "The indexes weren't brought up to date" in result.output
    assert reports(events)[0]["indexes"] == [] and leftovers(here) == []


def test_after_an_import_keeps_a_conflict_there_a_sync_from_its_files_caracole_takes_it(syncing, tmp_path):
    # The state's kept member (GET /api/peer/state?peer=): there imported here's file and kept its own Creep, so a
    # sync from here proposes there's, as there chose, and takes it.
    here, there, _ = syncing
    here.song(version="key=Am&capo=0")
    there.song(version="key=Gm&capo=0")
    unit = "song/radiohead/creep"
    exported = tmp_path / "here.caracole"
    assert run(here, "peer", "export", str(exported)).exit_code == 0
    taken = run(there, "peer", "import", "--yes", f"--choose=here:{unit}", str(exported))
    assert taken.exit_code == 0, taken.output
    assert unit in sync.kept_of(there.conn, sync.own_id(here.conn))
    diff = json.loads(run(here, "peer", "diff", THERE, "--json").output)
    assert [(d["id"], d["proposal"], d["why"]) for d in diff["differences"]] == [(unit, "theirs", sync.KEPT_THERE)]
    result, _ = synced(here)
    assert result.exit_code == 0, result.output
    assert here.units() == there.units() and sync.kept_of(here.conn, sync.own_id(there.conn)) == {}
    assert "Nothing differs." in run(here, "peer", "diff", THERE).output


# --- the copies a sync or an import works on, swept once a killed one left them ---------------------------------

KILLED = """
import os, signal, sys
import caracole.commands.peer as peer
def killed(*args, **kw):  # the service restarts as the merge runs: SIGTERM, Python's default, no finally run
    os.kill(os.getpid(), signal.SIGTERM)
peer._merge_told = killed
from caracole.cli import main
sys.argv = ["caracole", *sys.argv[1:]]
main()
"""
COPIES = ["sync-indexes-0123456789ab.sqlite", "give-indexes-0123456789ab.sqlite", "import-indexes-0123456789ab.sqlite",
          "sync-indexes-0123456789ab.sqlite-journal", "import-indexes-0123456789ab.sqlite-wal",
          "give-indexes-0123456789ab.sqlite-shm", "give-indexes-abcdef012345.sqlite.0123456789ab.part",
          "give-indexes-abcdef012345.sqlite.0123456789ab.part-journal"]
NOT_COPIES = ["sync-indexes-0123456789ab.sqlite.bak", "sync-indexes-XYZ.sqlite", "import-indexes-01234.sqlite",
              "mine.sqlite", "export-0123456789abcdef.caracole"]


def aged(path, seconds=2 * 3600):
    import os
    import time

    then = time.time() - seconds
    os.utime(path, (then, then), follow_symlinks=False)


def test_the_sweep_deletes_a_syncs_copies_and_their_side_files_alone_once_an_hour_old(tmp_path):
    from caracole import peer_push

    folder = tmp_path / "peer"
    folder.mkdir()
    for name in COPIES + NOT_COPIES:
        (folder / name).write_bytes(b"x")
        aged(folder / name)
    (folder / "sync-indexes-ba9876543210.sqlite").write_bytes(b"fresh")  # being downloaded: its time moves
    (tmp_path / "outside.sqlite").write_bytes(b"x")
    (folder / "import-indexes-aaaaaaaaaaaa.sqlite").symlink_to(tmp_path / "outside.sqlite")
    aged(folder / "import-indexes-aaaaaaaaaaaa.sqlite")
    (folder / "sync-indexes-bbbbbbbbbbbb.sqlite").mkdir()
    aged(folder / "sync-indexes-bbbbbbbbbbbb.sqlite")
    assert sorted(peer_push.sweep_copies(folder)) == sorted(COPIES)
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        NOT_COPIES + ["sync-indexes-ba9876543210.sqlite", "import-indexes-aaaaaaaaaaaa.sqlite",
                      "sync-indexes-bbbbbbbbbbbb.sqlite"])
    assert (tmp_path / "outside.sqlite").exists()
    assert peer_push.sweep_copies(tmp_path / "none") == []


def test_a_copy_its_command_holds_is_never_swept_however_old(tmp_path):
    from caracole import peer_push

    folder = tmp_path / "peer"
    folder.mkdir()
    copy, journal = folder / "import-indexes-0123456789ab.sqlite", folder / "import-indexes-0123456789ab.sqlite-journal"
    copy.write_bytes(b"x")
    with peer_push.holding_copy(copy):  # a merge reading it for over an hour: its time doesn't move
        journal.write_bytes(b"j")
        aged(copy)
        aged(journal)
        assert peer_push.sweep_copies(folder) == [] and copy.exists() and journal.exists()
    assert sorted(peer_push.sweep_copies(folder)) == [copy.name, journal.name]


def test_an_index_copy_a_killed_import_left_is_swept_an_hour_after(libraries, tmp_path):  # noqa: F811
    import os
    import subprocess
    import sys
    from pathlib import Path

    from conftest import subprocess_pythonpath

    from caracole.web import peer_routes

    desk, studio, _ = libraries
    desk.song()
    gtptabs_index(desk, READ, ["https://gtptabs.com/tabs/2/blur.html"])
    f = exported(desk, tmp_path / "i.caracole", "--parts", "library,songbooks,indexes")
    src = Path(__file__).resolve().parents[1] / "src"
    config = str(studio.root / "caracole.toml")
    done = subprocess.run([sys.executable, "-c", KILLED, "--config", config, "peer", "import", "--yes", "--parts",
                           "indexes", str(f)], env={**os.environ, "PYTHONPATH": subprocess_pythonpath(src)},
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == -15, done.stdout + done.stderr
    folder = studio.cfg.cache_dir / "peer"
    (left,) = [p for p in folder.iterdir() if p.name.startswith("import-indexes-")]
    peer_routes._leftovers(folder)
    assert left.exists()  # an hour not passed yet: it may still be another's, working
    aged(left)
    peer_routes._leftovers(folder)  # caracole serve's sweep of cache_dir/peer, as GET /api/peer/index comes
    assert list(folder.iterdir()) == []


def test_peer_import_and_peer_sync_sweep_the_copies_left_as_they_start(libraries, tmp_path):  # noqa: F811
    desk, studio, _ = libraries
    desk.song()
    folder = studio.cfg.cache_dir / "peer"
    folder.mkdir(parents=True, exist_ok=True)
    # The import takes Desk's Creep, then the sync with Desk's caracole serve (the fixture's) finds nothing to do.
    for command, said in ((["peer", "import", "--yes", str(exported(desk, tmp_path / "d.caracole"))],
                           "Took song/radiohead/creep"),
                          (["peer", "sync", HOST, "--yes"], "Nothing differs.")):
        left = folder / "give-indexes-0123456789ab.sqlite"
        left.write_bytes(b"x")
        aged(left)
        out = run(studio, *command)
        assert out.exit_code == 0 and said in out.output, out.output
        assert not left.exists(), command


def merges_seeing_their_copy_swept(monkeypatch) -> list:
    """Each merge of a copy, as another caracole starting meanwhile sweeps it an hour on (its time doesn't move as
    the merge reads it): ``(its kind, whether it is still there)``."""
    from caracole import peer_push
    import caracole.commands.peer as peer

    merge, seen = peer._merge_told, []

    def slow(conn, cfg, path, *args, **kw):
        aged(path)
        peer_push.sweep_copies(path.parent)
        seen.append((path.name.partition("-indexes-")[0], path.exists()))
        return merge(conn, cfg, path, *args, **kw)

    monkeypatch.setattr(peer, "_merge_told", slow)
    return seen


def test_the_copy_an_imports_merge_reads_for_over_an_hour_is_never_swept_meanwhile(libraries, tmp_path,  # noqa: F811
                                                                                     monkeypatch):
    seen = merges_seeing_their_copy_swept(monkeypatch)
    desk, studio, _ = libraries
    desk.song()
    gtptabs_index(desk, READ, ["https://gtptabs.com/tabs/2/blur.html"])
    f = exported(desk, tmp_path / "i.caracole", "--parts", "library,songbooks,indexes")
    out = run(studio, "peer", "import", "--yes", "--parts", "indexes", str(f))
    assert out.exit_code == 0, out.output
    assert seen == [("import", True)] and list((studio.cfg.cache_dir / "peer").iterdir()) == []


def test_the_copy_a_syncs_merge_reads_for_over_an_hour_is_never_swept_meanwhile(syncing, monkeypatch):
    seen = merges_seeing_their_copy_swept(monkeypatch)
    here, there, _ = syncing
    gtptabs_rows(there, BLUR)
    result, _ = synced(here)
    assert result.exit_code == 0, result.output
    assert seen == [("sync", True)] and leftovers(here) == []


def test_the_copy_a_give_sends_and_waits_on_is_never_swept_meanwhile(syncing, monkeypatch):
    from caracole import peer_push

    here, there, _ = syncing
    gtptabs_rows(here, BLUR)
    upload, seen = peer_import.Uploader.upload, []

    def slow(self, path, **kw):
        aged(path)
        peer_push.sweep_copies(path.parent)
        seen.append(path.exists())
        return upload(self, path, **kw)

    monkeypatch.setattr(peer_import.Uploader, "upload", slow)
    result, _ = synced(here)
    assert result.exit_code == 0, result.output
    assert seen == [True] and leftovers(here) == []
