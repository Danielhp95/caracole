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
from caracole.songbook import make_songbook, songbooks_file
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

    gtptabs_rows(lib, ["https://gtptabs.com/tabs/2/blur.html", "https://gtptabs.com/tabs/2/blur/beetlebum.html"])
    write_pages(lib.conn, lib.cfg, Overrides(), MADE)
    status, sizes = asked(served, "/api/sync/sizes")
    assert sizes["tabs"] == 2 and sizes["indexes"] >= empty
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
    assert list(peer_folder(lib).iterdir()) == []
    assert asked(served, f"/api/sync/export?export={made['export']}", token=None)[0] == 404


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
