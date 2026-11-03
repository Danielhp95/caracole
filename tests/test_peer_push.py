"""A push from another caracole (the phone's), staged by caracole serve (peer_push.py, web/peer_routes.py): a push
opened with the files it names (POST /peer/push/new), each file this side lacks sent and checked by its SHA-256
(POST /peer/push/file), its ids checked before any path is built of them, at most two open at once, one left an
hour deleted; its document read back as ``caracole peer take`` reads it (``StagedSource``); and this side's site
indexes streamed to another caracole (GET /api/peer/index).

The pushes go through a real WebApp on a socket in a thread, as the phone sends them."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import sqlite3
import stat
import time
from urllib.parse import urlencode

import pytest
from conftest import add_song

from caracole import db, peer_push
from caracole import peer_sync as sync
from caracole.library import keep_file
from caracole.versions import upsert_version
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts

from test_web_server import Recorder, running

NOW = "2026-11-03T00:00:00Z"
PHONE = "0123456789abcdef"  # the phone's sync id
JSON = "application/json"
BYTES = "application/octet-stream"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Served:
    """caracole serve on a socket, asked as the phone asks it: JSON and bytes with the form token in a header."""

    def __init__(self, app: WebApp):
        self.app = app
        self.server = running(app)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def ask(self, method: str, path: str, body: bytes | None = None, *, kind: str | None = None,
            token: str | None = "tok", **headers: str) -> tuple[int, dict, bytes]:
        sent = {"Accept": JSON} | ({"Content-Type": kind} if kind else {}) | (
            {"X-Caracole-Form-Token": token} if token is not None else {}) | headers
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=30)
        try:
            conn.request(method, path, body=body, headers=sent)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def new(self, files: list[str], *, sender: str = PHONE, **fields) -> tuple[int, dict]:
        doc = {"format": sync.FORMAT, "from": sender, "files": files} | fields
        status, _, body = self.ask("POST", "/peer/push/new", json.dumps(doc).encode(), kind=JSON)
        return status, json.loads(body)

    def file(self, push: str, sha256: str, data: bytes, **options) -> tuple[int, dict]:
        status, _, body = self.ask("POST", "/peer/push/file?" + urlencode({"push": push, "sha256": sha256}), data,
                                   kind=BYTES, **options)
        return status, json.loads(body)


@pytest.fixture
def served(cfg):
    app = WebApp(cfg, JobQueue(Recorder()), allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    serving = Served(app)
    yield serving
    serving.close()


def a_kept_file(cfg, conn, data: bytes = b"[Am]Creep"):
    song = add_song(conn, "Radiohead", "Creep")
    vid = upsert_version(conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url="https://u/101", raw={"x": 1}, now=NOW)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=data, rank=1)
    return song


def pushes(cfg) -> list[str]:
    folder = cfg.state_dir / "peer"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


# --- a push opened ----------------------------------------------------------------------------------------------


def test_a_push_opens_a_private_folder_and_needs_the_files_this_side_has_no_readable_copy_of(served, cfg, conn):
    a_kept_file(cfg, conn, b"[Am]Creep")
    before = sorted(p.relative_to(cfg.library_dir) for p in cfg.library_dir.rglob("*"))
    new = sha(b"[C]A new sheet")
    status, answer = served.new([sha(b"[Am]Creep"), new, new])
    assert status == 200 and answer["need"] == [new]
    push = answer["push"]
    assert len(push) == 16 and int(push, 16) >= 0
    folder = cfg.state_dir / "peer" / f"push-{push}"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and stat.S_IMODE(folder.parent.stat().st_mode) == 0o700
    assert sorted(p.relative_to(cfg.library_dir) for p in cfg.library_dir.rglob("*")) == before  # nothing there

    # a kept file changed on a synced device since is no copy of what was kept
    (cfg.library_dir / "Radiohead" / "Creep" / "sheet.txt").write_bytes(b"changed")
    assert served.new([sha(b"[Am]Creep")])[1]["need"] == [sha(b"[Am]Creep")]


def test_a_push_new_that_isnt_one_is_refused(served, cfg, conn):
    good = sha(b"x")
    for doc in ({"format": sync.FORMAT + 1, "from": PHONE, "files": []},
                {"format": sync.FORMAT, "from": "phone", "files": []},
                {"format": sync.FORMAT, "from": PHONE.upper(), "files": []},
                {"format": sync.FORMAT, "from": PHONE, "files": [good.upper()]},
                {"format": sync.FORMAT, "from": PHONE, "files": [good[:-1]]},
                {"format": sync.FORMAT, "from": PHONE, "files": good},
                {"format": sync.FORMAT, "from": PHONE},
                [good]):
        status, _, body = served.ask("POST", "/peer/push/new", json.dumps(doc).encode(), kind=JSON)
        assert status == 400 and "error" in json.loads(body), doc
    own = sync.own_id(conn)
    status, answer = served.new([], sender=own)
    assert status == 400 and "this caracole" in answer["error"]
    assert pushes(cfg) == []


def test_a_push_is_written_with_the_form_token_in_its_header_from_no_other_site(served, cfg):
    doc = json.dumps({"format": sync.FORMAT, "from": PHONE, "files": []}).encode()
    status, _, body = served.ask("POST", "/peer/push/new", doc, kind=JSON, token="old")
    assert status == 403 and json.loads(body)["reload"] is True
    status, _, _ = served.ask("POST", "/peer/push/new", doc, kind=JSON, **{"Sec-Fetch-Site": "cross-site"})
    assert status == 403
    status, _, _ = served.ask("POST", "/peer/push/new", b"csrf=tok", kind="application/x-www-form-urlencoded")
    assert status == 415
    assert pushes(cfg) == []


def test_at_most_two_pushes_are_open_at_once_and_one_left_an_hour_is_deleted(served, cfg):
    first, second = served.new([])[1]["push"], served.new([])[1]["push"]
    status, answer = served.new([])
    assert status == 409 and "two" in answer["error"].lower()
    folder = cfg.state_dir / "peer" / f"push-{first}"
    hours_ago = time.time() - 2 * 3600
    for path in (folder, folder / "files", folder / peer_push.NEW):
        os.utime(path, (hours_ago, hours_ago))
    status, answer = served.new([])
    assert status == 200 and pushes(cfg) == sorted([f"push-{second}", f"push-{answer['push']}"])


def test_a_push_a_take_holds_is_never_deleted_however_old(cfg):
    opened = peer_push.new_push(cfg.state_dir, None, cfg.library_dir, sender=PHONE, files=[], own=None)
    folder = cfg.state_dir / "peer" / f"push-{opened.push}"
    (folder / peer_push.DOCUMENT).write_text("{}", encoding="utf-8")
    hours_ago = time.time() - 30 * 3600
    for path in (folder, folder / "files", folder / peer_push.NEW, folder / peer_push.DOCUMENT):
        os.utime(path, (hours_ago, hours_ago))
    with peer_push.held(folder):
        peer_push.sweep(cfg.state_dir)
        assert folder.is_dir()
    peer_push.sweep(cfg.state_dir)
    assert not folder.exists()
    with pytest.raises(peer_push.PushError, match="gone"), peer_push.held(folder):
        pass


# --- its files ----------------------------------------------------------------------------------------------------


def test_a_needed_file_is_staged_once_its_bytes_are_what_its_sha256_says(served, cfg):
    data = b"\x00guitar pro\xff" * 1000
    push = served.new([sha(data)])[1]["push"]
    assert served.file(push, sha(data), b"other bytes") == (400, {"error": "Those bytes aren't the file of that "
                                                                          "SHA-256."})
    assert served.file(push, sha(data), data) == (200, {"ok": True})
    staged = cfg.state_dir / "peer" / f"push-{push}" / "files" / sha(data)
    assert staged.read_bytes() == data and stat.S_IMODE(staged.stat().st_mode) == 0o600
    assert served.file(push, sha(data), data) == (200, {"ok": True})  # again: as it was
    other = b"not named"
    status, answer = served.file(push, sha(other), other)
    assert status == 400 and "doesn't need" in answer["error"]
    assert sorted(p.name for p in staged.parent.iterdir()) == [sha(data)]


def test_a_bad_push_id_or_sha256_is_refused_before_any_path_is_built(served, cfg, monkeypatch):
    built = []
    folder = peer_push._folder
    monkeypatch.setattr(peer_push, "_folder", lambda state_dir, push_id: built.append(push_id) or folder(
        state_dir, push_id))
    push = served.new([sha(b"x")])[1]["push"]
    built.clear()
    for push_id, sha256 in (("../../../etc", sha(b"x")), (push.upper(), sha(b"x")), (push[:-1], sha(b"x")),
                            (push + "0", sha(b"x")), (push, "../" + sha(b"x")[3:]), (push, sha(b"x").upper()),
                            (push, ""), ("", sha(b"x")), (push + "\n", sha(b"x")), (push, sha(b"x") + "\n")):
        status, answer = served.file(push_id, sha256, b"x")
        assert status == 400 and "error" in answer, (push_id, sha256)
    assert built == []
    status, _, body = served.ask("POST", "/peer/push/file?sha256=" + sha(b"x"), b"x", kind=BYTES)
    assert status == 400 and built == []
    # a push of 16 hex that isn't open
    assert served.file("f" * 16, sha(b"x"), b"x")[0] == 400


def test_a_file_too_long_is_refused_unread_and_a_push_past_its_bytes_is_refused(served, cfg, monkeypatch):
    big = sha(b"big")
    push = served.new([big, sha(b"12345"), sha(b"123456")])[1]["push"]
    conn = http.client.HTTPConnection("127.0.0.1", served.server.server_address[1], timeout=10)
    try:  # 64 MiB and a byte, claimed: answered at once, unread
        conn.putrequest("POST", f"/peer/push/file?push={push}&sha256={big}")
        conn.putheader("Content-Type", BYTES)
        conn.putheader("Content-Length", str(64 * 1024 * 1024 + 1))
        conn.endheaders()
        assert conn.getresponse().status == 413
    finally:
        conn.close()
    monkeypatch.setattr(peer_push, "PUSH_MAX", 10)
    assert served.file(push, sha(b"12345"), b"12345") == (200, {"ok": True})
    status, answer = served.file(push, sha(b"123456"), b"123456")
    assert status == 400 and "2 GiB" in answer["error"]


def test_a_push_sent_already_takes_no_more_files(served, cfg):
    push = served.new([sha(b"x")])[1]["push"]
    (cfg.state_dir / "peer" / f"push-{push}" / peer_push.DOCUMENT).write_text("{}", encoding="utf-8")
    status, answer = served.file(push, sha(b"x"), b"x")
    assert status == 400 and "sent" in answer["error"]


# --- its document, as caracole peer take reads it ----------------------------------------------------------------


def a_push_document(units: dict, take: list) -> dict:
    return {"format": sync.FORMAT, "from": PHONE, "name": "Phone", "caracole": "0.1.0", "at": NOW,
            "units": units, "take": take}


def test_a_push_document_is_read_back_whole_and_refused_when_it_isnt_one():
    digest = "d" * 64
    doc = a_push_document({"song/radiohead/creep": {"label": "Radiohead - Creep", "digest": digest}},
                          [{"id": "song/radiohead/creep", "expected": None, "digest": digest,
                            "unit": {"key": "radiohead/creep"}},
                           {"id": "song/estopa/tu-calorro", "expected": "e" * 64, "digest": None, "unit": None}])
    push = peer_push.read_push_document(doc)
    assert push.sender == PHONE and push.name == "Phone" and push.version == "0.1.0" and push.at == NOW
    assert push.units["song/radiohead/creep"].digest == digest
    assert [(t.id, t.expected, t.digest, t.unit) for t in push.take] == [
        ("song/radiohead/creep", None, digest, {"key": "radiohead/creep"}),
        ("song/estopa/tu-calorro", "e" * 64, None, None)]

    def broken(**change):
        return a_push_document(doc["units"], doc["take"]) | change

    entry = doc["take"][0]
    for bad in (broken(format=sync.FORMAT + 1), broken(**{"from": "phone"}), broken(at=None), broken(units=[]),
                broken(units={"nonsense": {"label": "x", "digest": digest}}), broken(take={}),
                broken(take=[entry, entry]),  # a unit twice
                broken(take=[entry | {"digest": None}]),  # a document with no digest
                broken(take=[entry | {"unit": None}]),  # a digest with no document
                broken(take=[entry | {"digest": "f" * 64}]),  # another digest than its state gives it
                broken(take=[entry | {"expected": 3}]), broken(take=[entry | {"id": "nonsense"}]),
                broken(take=[{"id": "song/x", "expected": None, "digest": None, "unit": None}] * 1 + ["x"]),
                "nonsense"):
        with pytest.raises(peer_push.PushError):
            peer_push.read_push_document(bad)


def test_the_files_a_push_names_are_its_song_documents_kept_files():
    doc = a_push_document({}, [
        {"id": "song/a/b", "expected": None, "digest": None, "unit": None},
        {"id": "songbook/campfire", "expected": None, "digest": None, "unit": None}])
    assert peer_push.read_push_document(doc).files() == set()
    song = {"versions": [{"files": [{"name": "sheet.txt", "sha256": "1" * 64, "kept_rank": 1}]},
                         {"files": [{"name": "guitar-1.gp5", "sha256": "2" * 64, "kept_rank": None}]}]}
    units = {"song/a/b": {"label": "a - b", "digest": "d" * 64}}
    doc = a_push_document(units, [{"id": "song/a/b", "expected": None, "digest": "d" * 64, "unit": song}])
    assert peer_push.read_push_document(doc).files() == {"1" * 64, "2" * 64}
    for versions in ([{"files": [{"name": "x", "sha256": "nope"}]}], "x", [{"files": "x"}]):
        doc["take"][0]["unit"] = {"versions": versions}
        with pytest.raises(peer_push.PushError):
            peer_push.read_push_document(doc).files()


def test_a_staged_source_gives_each_unit_and_each_file_staged_or_kept_here(served, cfg, conn):
    a_kept_file(cfg, conn, b"[Am]Creep")
    sent = b"[C]sent with the push"
    push = served.new([sha(b"[Am]Creep"), sha(sent)])[1]["push"]
    assert served.file(push, sha(sent), sent)[0] == 200
    folder = cfg.state_dir / "peer" / f"push-{push}"
    units = {"song/a/b": {"label": "a - b", "digest": "d" * 64}}
    doc = a_push_document(units, [{"id": "song/a/b", "expected": None, "digest": "d" * 64, "unit": {"key": "a/b"}},
                                  {"id": "song/c/d", "expected": "e" * 64, "digest": None, "unit": None}])
    source = peer_push.StagedSource(folder, peer_push.read_push_document(doc), conn, cfg.library_dir)
    assert source.unit("song/a/b") == {"format": sync.FORMAT, "id": "song/a/b", "digest": "d" * 64,
                                       "unit": {"key": "a/b"}}
    assert source.unit("song/c/d") is None and source.unit("song/nowhere") is None
    assert source.file("a/b", "sheet.txt", sha(sent)) == sent
    assert source.file("a/b", "sheet.txt", sha(b"[Am]Creep")) == b"[Am]Creep"  # kept here already
    with pytest.raises(sync.PeerError):
        source.file("a/b", "sheet.txt", sha(b"never sent"))
    (folder / "files" / sha(sent)).write_bytes(b"changed since")
    with pytest.raises(sync.PeerError):
        source.file("a/b", "sheet.txt", sha(sent))


# --- the site indexes, streamed ----------------------------------------------------------------------------------


def test_the_indexes_are_streamed_from_a_temporary_export_merged_into_another_database(served, cfg, conn, tmp_path):
    from datetime import UTC, datetime

    from caracole import index_transfer
    from conftest import migrated_database

    from test_index_transfer import ug_listed, ug_sitemap

    at = datetime(2026, 10, 28, 3, 30, tzinfo=UTC)
    ug_sitemap(conn, "tabs-1.xml", ["radiohead/creep-chords-4169", "eagles/hotel-california-chords-46190"], at)
    ug_listed(conn, ["tabs-1.xml"], at)
    status, headers, body = served.ask("GET", "/api/peer/index", token=None)
    assert status == 200 and headers["Content-Type"] == "application/vnd.sqlite3"
    assert int(headers["Content-Length"]) == len(body) and body.startswith(b"SQLite format 3\x00")
    assert list((cfg.cache_dir / "peer").iterdir()) == []  # the export gone once sent
    assert stat.S_IMODE((cfg.cache_dir / "peer").stat().st_mode) == 0o700

    (tmp_path / "phone").mkdir()
    fetched = tmp_path / "phone" / "index.sqlite"
    fetched.write_bytes(body)
    phone_db = tmp_path / "phone" / "caracole.sqlite"
    phone_db.write_bytes(migrated_database())
    phone = db.connect(phone_db)
    try:
        merged = index_transfer.merge(phone, fetched, state_dir=tmp_path / "phone" / "state",
                                      now=datetime(2026, 11, 3, tzinfo=UTC))
        assert merged.changed
        assert phone.execute("SELECT COUNT(*) FROM ug_index").fetchone()[0] == 2
    finally:
        phone.close()

    # some sites alone
    status, _, body = served.ask("GET", "/api/peer/index?sites=harptabs,gametabs", token=None)
    assert status == 200
    fetched = tmp_path / "some.sqlite"
    fetched.write_bytes(body)
    with sqlite3.connect(fetched) as file:
        sites = json.loads(file.execute("SELECT value FROM caracole_export WHERE key = 'sites'").fetchone()[0])
        tables = {name for (name,) in file.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert sites == ["harptabs", "gametabs"] and "ug_index" not in tables
    status, _, body = served.ask("GET", "/api/peer/index?sites=ug,nowhere", token=None)
    assert status == 400 and "nowhere" in json.loads(body)["error"]


def test_another_sites_page_reads_no_index(served):
    status, _, _ = served.ask("GET", "/api/peer/index", token=None, **{"Sec-Fetch-Site": "cross-site"})
    assert status == 403


def test_an_index_that_cant_be_made_leaves_nothing_behind(served, cfg, monkeypatch):
    from caracole import index_transfer

    def failing(conn, path, sites=None, *, now):
        path.write_bytes(b"half")
        raise index_transfer.TransferError(f"can't write {path}: disk full")

    monkeypatch.setattr(index_transfer, "export", failing)
    status, _, body = served.ask("GET", "/api/peer/index", token=None)
    assert status == 503 and "disk full" in json.loads(body)["error"]
    assert list((cfg.cache_dir / "peer").iterdir()) == []
