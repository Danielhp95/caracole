"""caracole serve's Export and Import a file (web/sync_file_routes.py): what an export of this library would hold,
the file made in ``cache_dir/peer/`` and sent once, and a file to import sent here in parts, staged in
``state_dir/peer/import-<id>/`` (peer_import.py), each asked as the page's script asks it, over a socket."""

from __future__ import annotations

import http.client
import io
import json
import os
import stat
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caracole import peer_file, peer_import, site_index
from caracole.songbook import load_songbooks, make_songbook, songbooks_file
from caracole.web import sync_file_routes

from test_commands_peer import CREEP
from test_commands_peer_file import Lib
from test_peer_push import Served

JSON = "application/json"
BYTES = "application/octet-stream"
MADE = datetime(2026, 11, 3, 18, 40, tzinfo=UTC)
HOURS_AGO = 2 * 3600


@pytest.fixture
def served(tmp_path, monkeypatch):
    """The library horde_logbook, a song kept in it and a songbook, its caracole serve on a socket; the routes'
    clock at 3 November 2026, 18:40, in UTC."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    monkeypatch.setattr(sync_file_routes, "_now", lambda: MADE)
    lib = Lib(tmp_path / "desk", "horde_logbook")
    lib.song()
    make_songbook(songbooks_file(lib.cfg.library_dir), "Campfire", [CREEP])
    serving = Served(lib.app)
    serving.lib = lib
    yield serving
    serving.close()
    lib.conn.close()
    monkeypatch.undo()
    time.tzset()


def asked(served, path, **headers):
    status, said, body = served.ask("GET", path, **headers)
    return status, json.loads(body) if said.get("Content-Type", "").startswith(JSON) else body


def posted(served, path, doc, **options):
    status, _, body = served.ask("POST", path, json.dumps(doc).encode(), kind=JSON, **options)
    return status, json.loads(body)


def gtptabs_rows(lib, locs):
    from caracole import gtptabs_fetch

    site = gtptabs_fetch.SITE
    site_index._store(lib.conn, site, "sitemap-tabs-1.xml", [site.row(loc) for loc in locs],
                      {"etag": '"1"', "last_modified": None}, MADE)


def peer_folder(lib) -> Path:
    return lib.cfg.cache_dir / "peer"


# --- what an export would hold ------------------------------------------------------------------------------------


def test_sizes_say_the_librarys_bytes_its_songbooks_and_the_indexes(served):
    from caracole.commands._common import write_pages
    from caracole.overrides import Overrides

    lib = served.lib
    status, sizes = asked(served, "/api/sync/sizes")
    assert status == 200, sizes
    assert sizes["name"] == "horde_logbook" and sizes["songs"] == 1 and sizes["songbooks"] == 1
    assert sizes["made"] == "2026-11-03T18:40:00Z"
    assert sizes["library"] == len(b"[Am]Creep")  # its kept sheet: no library page written yet
    assert sizes["tabs"] == 0 and isinstance(sizes["indexes"], int)
    empty = sizes["indexes"]
    page = lib.conn.execute("PRAGMA page_size").fetchone()[0]
    assert empty >= page * 2 and empty % page == 0  # each site's tables and their keys: a root page each at least

    locs = [f"https://gtptabs.com/tabs/2/{n}/a-song-of-theirs-{n}.html" for n in range(2000)]
    gtptabs_rows(lib, locs)
    write_pages(lib.conn, lib.cfg, Overrides(), MADE)
    status, sizes = asked(served, "/api/sync/sizes")
    assert sizes["tabs"] == 2000 and sizes["indexes"] >= empty + 10 * page  # 2,000 rows take pages of their own
    pages = lib.cfg.library_dir / "index.html"
    assert sizes["library"] >= len(b"[Am]Creep") + pages.stat().st_size  # the library page and what it links


def test_without_sqlites_dbstat_the_indexes_size_is_none(served):
    class NoDbstat:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            if sql.strip().upper().startswith("PRAGMA COMPILE_OPTIONS"):
                return iter([("THREADSAFE=1",)])
            return self.conn.execute(sql, *args)

    assert peer_file.indexes_size(NoDbstat(served.lib.conn)) is None
    assert isinstance(peer_file.indexes_size(served.lib.conn), int)


# --- the export ---------------------------------------------------------------------------------------------------


def test_an_export_is_made_named_for_the_library_and_the_day_and_sent_once(served):
    lib = served.lib
    status, made = posted(served, "/sync/export", {"parts": ["library", "songbooks"]})
    assert status == 200, made
    assert len(made["export"]) == 16 and made["name"] == "horde_logbook-03-11-26.caracole"
    path = peer_folder(lib) / f"export-{made['export']}.caracole"
    assert made["size"] == path.stat().st_size
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(peer_folder(lib).stat().st_mode) == 0o700

    status, said, body = served.ask("GET", f"/api/sync/export?export={made['export']}", token=None)
    assert status == 200 and said["Content-Type"] == peer_file.MEDIA_TYPE
    assert said["Content-Disposition"] == ('attachment; filename="horde_logbook-03-11-26.caracole"; '
                                           "filename*=UTF-8''horde_logbook-03-11-26.caracole")
    assert len(body) == made["size"]
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        manifest = json.loads(z.read("caracole.json"))
    assert manifest["name"] == "horde_logbook" and manifest["parts"] == ["library", "songbooks"]
    assert manifest["made"] == "2026-11-03T18:40:00Z" and manifest["songs"] == 1 and manifest["songbooks"] == 1

    assert list(peer_folder(lib).iterdir()) == []  # deleted once it was open
    status, gone = asked(served, f"/api/sync/export?export={made['export']}", token=None)
    assert status == 404 and "Export again" in gone["error"]


def test_an_export_with_the_indexes_holds_them(served):
    gtptabs_rows(served.lib, ["https://gtptabs.com/tabs/2/blur.html"])
    status, made = posted(served, "/sync/export", {"parts": ["indexes", "library"]})
    assert status == 200, made
    _, _, body = served.ask("GET", f"/api/sync/export?export={made['export']}", token=None)
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert json.loads(z.read("caracole.json"))["parts"] == ["library", "indexes"]
        assert "indexes.sqlite" in z.namelist()


def test_an_export_needs_the_token_and_the_page_and_refuses_indexes_alone(served):
    doc = {"parts": ["library"]}
    status, said = posted(served, "/sync/export", doc, token=None)
    assert status == 403 and said["reload"] is True
    status, _ = posted(served, "/sync/export", doc, Origin="http://evil.example")
    assert status == 403
    status, said = posted(served, "/sync/export", {"parts": ["indexes"]})
    assert status == 400 and "caracole index export" in said["error"]
    for wrong in ({"parts": ["library", "photos"]}, {"parts": "library"}, {}, ["library"]):
        status, said = posted(served, "/sync/export", wrong)
        assert status == 400, (wrong, said)
    assert not peer_folder(served.lib).exists() or list(peer_folder(served.lib).iterdir()) == []


def test_a_second_export_while_one_is_made_is_refused(served, monkeypatch):
    seen = []
    export_file = peer_file.export_file

    def meanwhile(*args, **kwargs):  # a second Export pressed while the first is being made
        seen.append(posted(served, "/sync/export", {"parts": ["songbooks"]}))
        return export_file(*args, **kwargs)

    monkeypatch.setattr(peer_file, "export_file", meanwhile)
    status, made = posted(served, "/sync/export", {"parts": ["library"]})
    assert status == 200, made
    assert seen == [(503, {"error": "Another export is being made: try again once it is."})]
    monkeypatch.setattr(peer_file, "export_file", export_file)
    assert posted(served, "/sync/export", {"parts": ["songbooks"]})[0] == 200  # once it is made


def test_an_export_never_asked_for_is_deleted_an_hour_after(served):
    lib = served.lib
    _, made = posted(served, "/sync/export", {"parts": ["library"]})
    path = peer_folder(lib) / f"export-{made['export']}.caracole"
    left = peer_folder(lib) / ".export-0123456789abcdef.caracole.0123456789ab.part"  # a killed process's
    left.write_bytes(b"half")
    then = time.time() - HOURS_AGO
    for old in (path, left):
        os.utime(old, (then, then))
    assert asked(served, "/api/sync/sizes")[0] == 200
    assert list(peer_folder(lib).iterdir()) == [left]  # a part is swept only while no export is made: as one is
    assert asked(served, f"/api/sync/export?export={made['export']}", token=None)[0] == 404
    _, again = posted(served, "/sync/export", {"parts": ["songbooks"]})
    assert list(peer_folder(lib).iterdir()) == [peer_folder(lib) / f"export-{again['export']}.caracole"]


def test_a_part_an_export_being_made_reads_back_is_never_swept_meanwhile(served, monkeypatch):
    # An export of a big library reads back its .indexes part long after it last wrote it: its time stops moving.
    export_file = peer_file.export_file
    seen = []

    def slowly(conn, cfg, overrides, books, path, *args, **kwargs):
        part = path.with_name(f".{path.name}.0123456789ab.indexes")
        part.write_bytes(b"indexes, as the export reads them back")
        then = time.time() - HOURS_AGO
        os.utime(part, (then, then))
        seen.append((asked(served, "/api/sync/sizes")[0], part.exists()))  # the page asks meanwhile
        part.unlink()
        return export_file(conn, cfg, overrides, books, path, *args, **kwargs)

    monkeypatch.setattr(peer_file, "export_file", slowly)
    assert posted(served, "/sync/export", {"parts": ["library"]})[0] == 200
    assert seen == [(200, True)]


def test_one_export_waits_to_be_sent_at_most(served):
    # Export pressed again and again, never downloaded: each takes the place of the one before, never a pile.
    lib = served.lib
    made = [posted(served, "/sync/export", {"parts": ["library", "songbooks"]})[1] for _ in range(3)]
    assert len({m["export"] for m in made}) == 3
    assert list(peer_folder(lib).iterdir()) == [peer_folder(lib) / f"export-{made[-1]['export']}.caracole"]
    for earlier in made[:-1]:
        status, gone = asked(served, f"/api/sync/export?export={earlier['export']}", token=None)
        assert status == 404 and "another made since" in gone["error"]
    assert asked(served, f"/api/sync/export?export={made[-1]['export']}", token=None)[0] == 200


def test_another_sites_fetch_reads_neither_sizes_nor_the_file(served):
    _, made = posted(served, "/sync/export", {"parts": ["library"]})
    for path in ("/api/sync/sizes", f"/api/sync/export?export={made['export']}"):
        status, _ = asked(served, path, token=None, **{"Sec-Fetch-Site": "cross-site"})
        assert status == 403, path
    status, said, _ = served.ask("HEAD", f"/api/sync/export?export={made['export']}", token=None)
    assert status == 405 and said["Allow"] == "GET"  # a HEAD would spend the one GET
    assert asked(served, f"/api/sync/export?export={made['export']}", token=None)[0] == 200  # still there
    assert asked(served, "/api/sync/export?export=../../etc", token=None)[0] == 404


# --- a file to import, sent in parts ------------------------------------------------------------------------------


def opened(served, size, name="d.caracole", **options):
    return posted(served, "/sync/import/open", {"size": size, "name": name}, **options)


def part(served, import_id, at, data, **options):
    status, _, body = served.ask("POST", f"/sync/import/part?import={import_id}&at={at}", data, kind=BYTES,
                                 **options)
    return status, json.loads(body)


def staged(lib, import_id) -> Path:
    return lib.cfg.state_dir / "peer" / f"import-{import_id}"


def test_a_file_is_sent_in_parts_and_staged_as_sent(served):
    lib = served.lib
    data = os.urandom(3000)
    status, said = opened(served, len(data), "horde_logbook-03-11-26.caracole")
    assert status == 200 and said["part"] == 8 * 1024 * 1024 and len(said["import"]) == 16
    import_id = said["import"]
    for at in range(0, len(data), 1000):
        assert part(served, import_id, at, data[at:at + 1000]) == (200, {"have": at + 1000})
    folder = staged(lib, import_id)
    assert peer_import.whole(lib.cfg.state_dir, import_id).read_bytes() == data
    assert peer_import.opened_name(folder) == "horde_logbook-03-11-26.caracole"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_a_part_out_of_order_too_big_or_without_the_token_is_refused(served):
    lib = served.lib
    _, said = opened(served, 2000)
    import_id = said["import"]
    assert part(served, import_id, 0, b"x" * 1000) == (200, {"have": 1000})
    status, refused = part(served, import_id, 0, b"y" * 1000)  # sent again: not the next one
    assert status == 400 and refused["error"] == peer_import.NOT_NEXT
    status, refused = part(served, import_id, 1000, b"y" * 1001)  # past the size it said
    assert status == 400 and refused["error"] == peer_import.NOT_NEXT
    for at in ("", "-1", "1e3", "%C2%B2", "1%2B1"):
        assert part(served, import_id, at, b"y")[0] == 400, at
    status, refused = part(served, import_id, 1000, b"y" * 1000, token=None)
    assert status == 403 and refused["reload"] is True
    assert part(served, import_id, 1000, b"y" * 1000, Origin="http://evil.example")[0] == 403
    status, _ = part(served, "0123456789abcdef", 0, b"y")
    assert status == 404
    assert part(served, "../../../etc", 0, b"y")[0] == 400
    conn = http.client.HTTPConnection("127.0.0.1", served.server.server_address[1], timeout=10)
    try:  # 8 MiB and a byte, claimed: answered at once, unread
        conn.putrequest("POST", f"/sync/import/part?import={import_id}&at=1000")
        conn.putheader("Content-Type", BYTES)
        conn.putheader("X-Caracole-Form-Token", "tok")
        conn.putheader("Content-Length", str(8 * 1024 * 1024 + 1))
        conn.endheaders()
        assert conn.getresponse().status == 413
    finally:
        conn.close()
    assert (staged(lib, import_id) / peer_import.FILE).read_bytes() == b"x" * 1000  # as it was


def test_an_import_is_opened_one_at_a_time_and_8_gib_at_most(served):
    status, said = opened(served, 8 * 1024 ** 3 + 1)
    assert status == 413 and said["error"] == peer_import.TOO_BIG
    for wrong in ({"size": "big", "name": "d.caracole"}, {"size": 10}, {"size": 0, "name": "d.caracole"}, []):
        assert posted(served, "/sync/import/open", wrong)[0] == 400, wrong
    assert opened(served, 10, token=None)[0] == 403
    assert opened(served, 10)[0] == 200
    status, said = opened(served, 10)
    assert status == 409 and said["error"] == peer_import.BUSY


def test_a_staged_import_never_applied_is_swept_an_hour_after(served):
    lib = served.lib
    _, said = opened(served, 4)
    first = said["import"]
    part(served, first, 0, b"half")
    folder = staged(lib, first)
    then = time.time() - HOURS_AGO
    for path in (folder / peer_import.FILE, folder / peer_import.OPENED, folder):
        os.utime(path, (then, then))
    status, said = opened(served, 10)
    assert status == 200 and said["import"] != first and not folder.exists()


# --- a file to import, compared, and synced with -----------------------------------------------------------------


@pytest.fixture
def pair(tmp_path, monkeypatch):
    """Desk, whose file is imported, and Studio, which imports it through its caracole serve's routes (asked in this
    process, as its page's script asks them), whose queue runs what it queued through the CLI; renders recorded,
    not made, and each ``caracole peer`` command's clock a second after the last one's."""
    import itertools
    from datetime import timedelta

    from test_commands_peer import InProcess

    desk, studio = Lib(tmp_path / "desk", "Desk", InProcess()), Lib(tmp_path / "studio", "Studio", InProcess())
    ticks, start = itertools.count(), datetime.now(UTC).replace(microsecond=0)
    monkeypatch.setattr("caracole.commands.peer.utcnow", lambda: start + timedelta(seconds=next(ticks)))
    monkeypatch.setattr("caracole.render.render_all", lambda conn, cfg, overrides, **kw: None)
    yield desk, studio
    desk.conn.close()
    studio.conn.close()


def script(app, path, doc=None, *, data=None, kind=JSON, token="tok"):
    """The page's script posting ``doc`` (JSON) or ``data`` (bytes) with the form token in its header."""
    from caracole.web.app import Request

    from test_web_app import HOST

    headers = {"host": HOST, "content-type": kind, "accept": JSON, "sec-fetch-site": "same-origin"} | (
        {"x-caracole-form-token": token} if token else {})
    answer = app.handle(Request("POST", path, headers, json.dumps(doc).encode() if data is None else data))
    return answer.status, json.loads(answer.body)


def sent(app, data: bytes, name="Desk-03-11-26.caracole", *, step=64 * 1024) -> str:
    """``data`` sent to ``app``'s Import a file, as the page sends a file: opened, then in parts; its import's id."""
    status, opened_ = script(app, "/sync/import/open", {"size": len(data), "name": name})
    assert status == 200, opened_
    for at in range(0, len(data), step):
        status, said = script(app, f"/sync/import/part?import={opened_['import']}&at={at}",
                              data=data[at:at + step], kind=BYTES)
        assert status == 200, said
    return opened_["import"]


def file_compared(app, import_id):
    from test_web_app import post

    answer = post(app, "/sync/import/compare", {"import": import_id}, accept=JSON)
    return answer.status, json.loads(answer.body)


def applied(app, comparison, **fields):
    from test_web_app import post

    answer = post(app, "/sync/apply", {"comparison": comparison, "prefer": "", "choices": "", **fields},
                  accept=JSON)
    return answer.status, json.loads(answer.body)


def staged_imports(lib):
    return peer_import._imports(lib.cfg.state_dir / "peer")


def desk_file(desk, tmp_path, *args) -> bytes:
    from test_commands_peer import run

    path = tmp_path / f"desk-{len(list(tmp_path.glob('desk-*')))}.caracole"
    result = run(desk, "peer", "export", *args, str(path))
    assert result.exit_code == 0, result.output
    return path.read_bytes()


def two_differences(desk, studio):
    """Creep on both, chorded differently (a conflict: the two never synced), Wonderwall at Desk alone."""
    desk.song("Radiohead", "Creep", version="key=Am&capo=0")
    studio.song("Radiohead", "Creep", version="key=Gm&capo=0")
    desk.song("Oasis", "Wonderwall", sheet=b"[Em]Today", version=None)


CREEP_UNIT, WONDERWALL_UNIT = "song/radiohead/creep", "song/oasis/wonderwall"


def test_a_file_sent_in_parts_is_compared_as_a_sync_with_it(pair, tmp_path):
    from caracole import __version__

    desk, studio = pair
    two_differences(desk, studio)
    data = desk_file(desk, tmp_path)
    made = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("caracole.json"))["made"]
    import_id = sent(studio.app, data)
    status, found = file_compared(studio.app, import_id)
    assert status == 200, found
    assert len(found["comparison"]) == 16 and found["synced_before"] is None
    assert found["peer"] == {"address": None, "server": desk.id(), "caracole": __version__, "name": "Desk",
                             "kind": "file", "made": made}
    assert found["holds"] == ["library", "songbooks"] and found["indexes"] == [] and found["songbooks"] == {}
    by = {d["id"]: d for d in found["differences"]}
    assert set(by) == {CREEP_UNIT, WONDERWALL_UNIT}
    assert (by[CREEP_UNIT]["proposal"], by[WONDERWALL_UNIT]["proposal"]) == ("conflict", "theirs")
    assert by[WONDERWALL_UNIT]["names"] == {"artist": "Oasis", "title": "Wonderwall"}
    assert by[WONDERWALL_UNIT]["change"] == [None, "new"] and by[WONDERWALL_UNIT]["part"] == "library"
    assert by[CREEP_UNIT]["here"] == studio.units()[CREEP_UNIT].digest
    assert by[CREEP_UNIT]["there"] == desk.units()[CREEP_UNIT].digest
    assert [f.name for f in staged_imports(studio)] == [f"import-{import_id}"]  # kept for its Sync
    # The comparison is of a file: its units are the file's, never asked of a caracole serve.
    from test_web_app import get_json

    refused = get_json(studio.app, f"/api/sync/unit?comparison={found['comparison']}&id={CREEP_UNIT}")
    assert refused.status == 409


def test_a_songbooks_only_file_compares_no_song_it_doesnt_hold(pair, tmp_path):
    desk, studio = pair
    desk.song("Radiohead", "Creep")
    make_songbook(songbooks_file(desk.cfg.library_dir), "Campfire", [CREEP])
    studio.song("Oasis", "Wonderwall", version=None)  # Studio's alone: no removal the file could say
    import_id = sent(studio.app, desk_file(desk, tmp_path, "--parts", "songbooks"))
    status, found = file_compared(studio.app, import_id)
    assert status == 200, found
    assert found["holds"] == ["songbooks"]
    assert {d["id"]: d["proposal"] for d in found["differences"]} == {"songbook/campfire": "theirs",
                                                                       CREEP_UNIT: "theirs"}
    assert found["songbooks"]["songbook/campfire"]["here"] is None
    assert found["songbooks"]["songbook/campfire"]["there"]["name"] == "Campfire"
    assert {d["id"]: d["with"] for d in found["differences"]}[CREEP_UNIT] == ["songbook/campfire"]


def test_a_file_refused_says_its_words_and_is_deleted(pair, tmp_path, monkeypatch):
    from test_commands_peer import run

    desk, studio = pair
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        studio.song()
        own = tmp_path / "own.caracole"
        assert run(studio, "peer", "export", str(own)).exit_code == 0
        status, said = file_compared(studio.app, sent(studio.app, own.read_bytes()))
        assert (status, said["error"]) == (409, peer_file.OWN_EXPORT) and staged_imports(studio) == []

        desk.song("Oasis", "Wonderwall", version=None)
        data = desk_file(desk, tmp_path)
        (tmp_path / "again.caracole").write_bytes(data)
        assert run(studio, "peer", "import", "--yes", str(tmp_path / "again.caracole")).exit_code == 0
        status, said = file_compared(studio.app, sent(studio.app, data))  # the same file again: no newer
        assert status == 409 and said["error"].startswith("Nothing in this file is newer than your sync with Desk on")
        assert staged_imports(studio) == []

        status, said = file_compared(studio.app, sent(studio.app, b"hello, not a file", name="notes.txt"))
        assert (status, said["error"]) == (400, peer_file.NOT_A_FILE) and staged_imports(studio) == []

        status, said = file_compared(studio.app, sent(studio.app, data[:len(data) // 2]))  # cut short
        assert status == 400 and said["error"].startswith("That file can't be read whole")
        assert staged_imports(studio) == []
    finally:
        monkeypatch.undo()
        time.tzset()


def test_a_file_not_whole_or_gone_is_compared_never_and_kept_or_said_gone(pair, tmp_path):
    desk, studio = pair
    desk.song()
    data = desk_file(desk, tmp_path)
    _, opened_ = script(studio.app, "/sync/import/open", {"size": len(data), "name": "d.caracole"})
    script(studio.app, f"/sync/import/part?import={opened_['import']}&at=0", data=data[:100], kind=BYTES)
    status, said = file_compared(studio.app, opened_["import"])
    assert (status, said["error"]) == (400, peer_import.NOT_WHOLE) and len(staged_imports(studio)) == 1
    assert file_compared(studio.app, "0123456789abcdef") == (404, {"error": peer_import.GONE})
    assert file_compared(studio.app, "../../etc")[0] == 400


def test_sync_on_an_import_queues_peer_import_of_its_folder_and_its_view_is_a_sync(pair, tmp_path):
    from caracole import peer_sync as sync
    from caracole.commands.peer import PEER_IMPORT_STAGES
    from caracole.overrides import load_overrides, override_key

    from test_web_app import get_json

    desk, studio = pair
    two_differences(desk, studio)
    import_id = sent(studio.app, desk_file(desk, tmp_path))
    _, found = file_compared(studio.app, import_id)
    status, said = applied(studio.app, found["comparison"])
    assert status == 409 and "Choose a side for every conflict first" in said["error"]
    status, answer = applied(studio.app, found["comparison"], choices=f"here\t{CREEP_UNIT}")
    assert status == 200, answer
    queued = answer["job"]
    assert queued["kind"] == "sync" and queued["display"] == "Sync with a file from Desk"
    assert queued["details"] == "#tab=sync" and queued["outcome"] is None
    assert [s["name"] for s in queued["steps"]] == [name for name, _ in PEER_IMPORT_STAGES]
    (job,) = studio.app.queue.snapshot()
    folder = studio.cfg.state_dir / "peer" / f"import-{import_id}"
    assert job.song_key == f"import:{import_id}"
    with peer_file.FileSource(peer_file.read_file(folder / peer_import.FILE), studio.conn,
                              studio.cfg.library_dir) as source:
        shown = peer_file.compare_file(studio.conn, load_overrides(studio.cfg.overrides_file),
                                       load_songbooks(songbooks_file(studio.cfg.library_dir)),
                                       peer_file.read_file(folder / peer_import.FILE), source)
    assert job.steps[0].args == ("peer", "import", "--yes", "--progress",
                                 f"--compared={sync.compared_hash(shown.found)}", f"--choose=here:{CREEP_UNIT}", "--",
                                 str(folder))

    studio.app.queue.run_pending()
    (job,) = studio.app.queue.snapshot()
    assert job.state == "done", [s.output for s in job.steps]
    assert WONDERWALL_UNIT in studio.units() and staged_imports(studio) == []  # taken, then its folder deleted
    assert load_overrides(studio.cfg.overrides_file).version[override_key(CREEP)] == "key=Gm&capo=0"  # kept
    assert CREEP_UNIT in sync.kept_of(studio.conn, desk.id())
    polled = json.loads(get_json(studio.app, f"/jobs.json?jobs={job.id}").body)["jobs"][0]
    assert polled["line"]["text"] == "Synced"
    assert polled["outcome"]["taken"] == [WONDERWALL_UNIT]
    report = polled["outcome"]["report"]
    assert report["with"] == {"name": "Desk", "kind": "file", "address": None}
    assert report["parts"] == ["library", "songbooks"] and report["indexes"] == []


def test_sync_on_an_import_refuses_a_comparison_this_library_moved_from(pair, tmp_path):
    from caracole.web import sync_routes

    desk, studio = pair
    two_differences(desk, studio)
    _, found = file_compared(studio.app, sent(studio.app, desk_file(desk, tmp_path)))
    studio.song("Muse", "Hysteria", version=None)  # Studio moved on since
    status, said = applied(studio.app, found["comparison"], prefer="there")
    assert (status, said["error"]) == (409, sync_routes.STALE) and studio.app.queue.snapshot() == []
    assert applied(studio.app, found["comparison"], prefer="there")[0] == 409  # that comparison is gone


def test_two_computers_one_imports_the_others_export_through_the_routes(pair):
    desk, studio = pair
    two_differences(desk, studio)
    make_songbook(songbooks_file(desk.cfg.library_dir), "Campfire", [CREEP])
    status, made = script(desk.app, "/sync/export", {"parts": ["library", "songbooks"]})
    assert status == 200, made
    from caracole.web.app import Request, WebApp

    from test_web_app import HOST

    answer = WebApp.finish(desk.app.handle(Request("GET", f"/api/sync/export?export={made['export']}",
                                                   {"host": HOST, "accept": JSON})))
    data = answer.stream.read()
    answer.stream.close()
    assert len(data) == made["size"]

    import_id = sent(studio.app, data, name=made["name"])
    status, found = file_compared(studio.app, import_id)
    assert status == 200 and found["peer"]["name"] == "Desk", found
    status, answer = applied(studio.app, found["comparison"], prefer="there")
    assert status == 200, answer
    studio.app.queue.run_pending()
    (job,) = studio.app.queue.snapshot()
    assert job.state == "done", [s.output for s in job.steps]
    assert studio.units() == desk.units()
    assert staged_imports(studio) == [] and list(peer_folder(desk).iterdir()) == []


def test_a_file_compared_and_left_gives_way_to_the_next_one_chosen(pair, tmp_path):
    desk, studio = pair
    desk.song()
    data = desk_file(desk, tmp_path)
    first = sent(studio.app, data)
    assert file_compared(studio.app, first)[0] == 200  # compared, then Cancel, or the page closed
    second = sent(studio.app, data)
    assert [f.name for f in staged_imports(studio)] == [f"import-{second}"]
    status, said = file_compared(studio.app, first)
    assert (status, said["error"]) == (404, peer_import.GONE)


def test_a_file_being_sent_is_never_let_go_but_one_whose_upload_stopped_is(pair, tmp_path):
    desk, studio = pair
    desk.song()
    data = desk_file(desk, tmp_path)
    _, opened_ = script(studio.app, "/sync/import/open", {"size": len(data), "name": "d.caracole"})
    script(studio.app, f"/sync/import/part?import={opened_['import']}&at=0", data=data[:100], kind=BYTES)
    status, said = script(studio.app, "/sync/import/open", {"size": 10, "name": "e.caracole"})
    assert (status, said["error"]) == (409, peer_import.BUSY)  # another tab sends one now
    folder = studio.cfg.state_dir / "peer" / f"import-{opened_['import']}"
    then = time.time() - peer_import.STOPPED - 60
    for path in (folder / peer_import.FILE, folder / peer_import.OPENED, folder):
        os.utime(path, (then, then))
    assert script(studio.app, "/sync/import/open", {"size": 10, "name": "e.caracole"})[0] == 200
    assert not folder.exists()


def test_a_file_whose_import_waits_is_kept_until_its_request_is_cancelled(pair, tmp_path):
    desk, studio = pair
    desk.song()
    data = desk_file(desk, tmp_path)
    import_id = sent(studio.app, data)
    _, found = file_compared(studio.app, import_id)
    status, answer = applied(studio.app, found["comparison"])
    assert status == 200, answer
    status, said = script(studio.app, "/sync/import/open", {"size": len(data), "name": "d.caracole"})
    assert (status, said["error"]) == (409, peer_import.BUSY)
    status, said = script(studio.app, "/sync/import/drop", {"import": import_id})
    assert (status, said["error"]) == (409, sync_file_routes.WAITS)
    studio.app.queue.cancel(answer["job"]["id"])
    assert script(studio.app, "/sync/import/open", {"size": len(data), "name": "d.caracole"})[0] == 200
    assert [f.name for f in staged_imports(studio)] != [f"import-{import_id}"]


def test_a_file_is_dropped_at_once_as_the_page_cancels(pair, tmp_path):
    desk, studio = pair
    desk.song()
    import_id = sent(studio.app, desk_file(desk, tmp_path))
    assert script(studio.app, "/sync/import/drop", {"import": import_id}, token=None)[0] == 403
    assert script(studio.app, "/sync/import/drop", {"id": import_id})[0] == 400
    assert script(studio.app, "/sync/import/drop", {"import": import_id}) == (200, {"dropped": import_id})
    assert staged_imports(studio) == []
    status, said = script(studio.app, "/sync/import/drop", {"import": import_id})
    assert (status, said["error"]) == (404, peer_import.NO_SUCH)
    assert script(studio.app, "/sync/import/drop", {"import": "../x"})[0] == 400
