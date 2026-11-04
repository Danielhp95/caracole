"""The ``.caracole`` file (peer_file.py): a library written to one (``export_file``), read back (``read_file``,
``SyncFile``), refused in the owner's words (``check_importable``), checked whole, and taken from as a sync takes a
peer's units (``FileSource``); the plan: docs/superpowers/plans/2026-11-03-sync-redesign.md §3.3."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caracole import db, index_transfer, peer_file
from caracole import peer_sync as sync
from caracole.library import song_dir
from helpers.peer_libraries import Library

OWN_ID, OTHER_ID = "a1b2c3d4e5f60718", "0f1e2d3c4b5a6978"
NOW = datetime(2026, 11, 3, 21, 10, tzinfo=UTC)
MADE = "2026-11-03T21:10:00Z"
CREEP, WONDERWALL, CAMPFIRE = "song/radiohead/creep", "song/oasis/wonderwall", "songbook/campfire"
LAYOUT = ["caracole.json", "state.json", "bases.json", "units.jsonl"]


@pytest.fixture
def desk(tmp_path):
    """Two songs, each with a kept sheet, and a songbook listing one of them."""
    lib = Library(tmp_path / "desk", sync_id=OWN_ID)
    lib.song("Radiohead", "Creep")
    lib.song("Oasis", "Wonderwall", sheet=b"[Em]Today is gonna be the day")
    lib.songbook("Campfire", ["Radiohead - Creep"])
    yield lib
    lib.close()


def export(lib: Library, path: Path, parts=("library", "songbooks"), **kw) -> peer_file.Made:
    return peer_file.export_file(lib.conn, lib.cfg, lib.overrides(), lib.books(), path, list(parts), now=NOW,
                                 version="0.1.0", name="Desk", **kw)


def members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {info.filename: z.read(info) for info in z.infolist()}


def lines_of(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.splitlines()]


def kept_shas(lib: Library, key: str | None = None) -> list[str]:
    rows = lib.conn.execute("SELECT DISTINCT files.sha256 FROM files JOIN songs ON songs.id = files.song_id"
                            + (" WHERE songs.key = ?" if key else ""), (key,) if key else ())
    return sorted(sha for (sha,) in rows)


# --- a library written to a file ------------------------------------------------------------------------------------


def test_an_export_holds_its_manifest_state_units_and_each_kept_file_once(desk, tmp_path):
    made = export(desk, tmp_path / "x.caracole")
    assert made.path == tmp_path / "x.caracole" and made.parts == ("library", "songbooks")
    assert (made.songs, made.songbooks, made.left) == (2, 1, ()) and made.size == made.path.stat().st_size
    with zipfile.ZipFile(made.path) as z:
        infos = z.infolist()
    names = [i.filename for i in infos]
    assert names == LAYOUT + [f"files/{s}" for s in kept_shas(desk)]
    assert {i.date_time for i in infos} == {(2026, 11, 3, 21, 10, 0)}
    assert {i.filename: i.compress_type for i in infos if i.filename.endswith(("json", "jsonl"))} == dict.fromkeys(
        LAYOUT, zipfile.ZIP_DEFLATED)
    assert {i.compress_type for i in infos if i.filename.startswith("files/")} == {zipfile.ZIP_STORED}

    got = members(made.path)
    manifest = json.loads(got["caracole.json"])
    assert manifest == {"format": 1, "caracole": "0.1.0", "schema": db.SCHEMA_VERSION, "sync": sync.FORMAT,
                        "id": OWN_ID, "name": "Desk", "made": MADE, "parts": ["library", "songbooks"], "songs": 2,
                        "songbooks": 1, "units": 3, "files": 2, "pages": 0, "indexes": []}
    state = sync.read_state_document(json.loads(got["state.json"]))
    assert state.units == desk.units() and (state.server, state.name, state.now, state.indexes) == (
        OWN_ID, "Desk", MADE, {})
    assert json.loads(got["state.json"])["kept"] == {}
    units = lines_of(got["units.jsonl"])
    assert [u["id"] for u in units] == [u.id for u in sorted(state.units.values(), key=sync._order)]
    for line in units:
        assert line == json.loads(json.dumps(desk.document(line["id"])))
    for sha in kept_shas(desk):
        assert hashlib.sha256(got[f"files/{sha}"]).hexdigest() == sha
    assert json.loads(got["bases.json"]) == {}
    assert not list(tmp_path.glob(".x.caracole.*"))  # its temporary name gone


def test_songbooks_alone_bring_the_songs_they_list_and_their_files(desk, tmp_path):
    made = export(desk, tmp_path / "s.caracole", ["songbooks"])
    got = members(made.path)
    state = sync.read_state_document(json.loads(got["state.json"]))
    assert sorted(state.units) == [CREEP, CAMPFIRE]
    assert [u["id"] for u in lines_of(got["units.jsonl"])] == [CREEP, CAMPFIRE]
    assert sorted(n for n in got if n.startswith("files/")) == [f"files/{s}" for s in kept_shas(desk, "radiohead/creep")]
    manifest = json.loads(got["caracole.json"])
    assert (manifest["parts"], manifest["songs"], manifest["songbooks"]) == (["songbooks"], 1, 1)
    assert (made.songs, made.songbooks) == (1, 1)


def test_indexes_come_only_when_asked_and_are_the_index_export(desk, tmp_path):
    db.kv_set(desk.conn, "gtptabs:index:complete_at", "2026-11-02T08:00:00Z")
    assert "indexes.sqlite" not in members(export(desk, tmp_path / "no.caracole").path)
    made = export(desk, tmp_path / "i.caracole", ["library", "songbooks", "indexes"])
    got = members(made.path)
    assert list(got)[-1] == "indexes.sqlite"
    with zipfile.ZipFile(made.path) as z:
        assert z.getinfo("indexes.sqlite").compress_type == zipfile.ZIP_STORED
    (tmp_path / "out.sqlite").write_bytes(got["indexes.sqlite"])
    file = sqlite3.connect(tmp_path / "out.sqlite")
    meta = dict(file.execute(f"SELECT key, value FROM {index_transfer.META}"))
    file.close()
    assert json.loads(meta["sites"]) == list(index_transfer.SITES) and meta["exported_at"] == MADE
    manifest = json.loads(got["caracole.json"])
    assert manifest["parts"] == ["library", "songbooks", "indexes"] and manifest["indexes"] == list(
        index_transfer.SITES)
    assert json.loads(got["state.json"])["indexes"] == index_transfer.newest(desk.conn) == {
        "gtptabs": "2026-11-02T08:00:00Z"}
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".i.caracole")]


def test_a_song_whose_kept_file_changed_on_disk_is_left_out_and_said(desk, tmp_path):
    wonderwall = desk.conn.execute("SELECT id FROM songs WHERE key = 'oasis/wonderwall'").fetchone()[0]
    from caracole.songs import get_song

    (song_dir(desk.cfg.library_dir, get_song(desk.conn, wonderwall)) / "sheet.txt").write_bytes(b"edited elsewhere")
    made = export(desk, tmp_path / "x.caracole")
    assert made.left == (WONDERWALL,) and made.songs == 1
    got = members(made.path)
    assert [u["id"] for u in lines_of(got["units.jsonl"])] == [CREEP, CAMPFIRE]
    assert sorted(n for n in got if n.startswith("files/")) == [f"files/{s}" for s in kept_shas(desk, "radiohead/creep")]
    # still named by its state, so that a file never says it is gone: an import leaves it, saying why
    assert WONDERWALL in json.loads(got["state.json"])["units"]
    assert json.loads(got["caracole.json"])["units"] == 2


def test_every_base_this_side_keeps_goes_into_bases_json(desk, tmp_path):
    third = "1122334455667788"
    sync.record_agreement(desk.conn, OTHER_ID, desk.units(), desk.units(), "2026-11-01T10:00:00Z")
    sync.record_kept(desk.conn, OTHER_ID, {"song/x/y": ("h", "t")}, "2026-11-02T10:00:00Z")
    sync.record_agreement(desk.conn, third, {}, {CREEP: desk.units()[CREEP]}, "2026-11-01T11:00:00Z")
    db.kv_set_json(desk.conn, sync.BASE_KEY + "ffffffffffffffff", {"format": 1, "units": {}})  # another format's
    bases = json.loads(members(export(desk, tmp_path / "x.caracole").path)["bases.json"])
    assert sorted(bases) == [OTHER_ID, third]
    assert bases[OTHER_ID]["units"][CREEP] == [desk.units()[CREEP].digest, "2026-11-01T10:00:00Z"]
    assert bases[OTHER_ID]["kept"] == {"song/x/y": ["h", "t", "2026-11-02T10:00:00Z"]}
    assert bases[third] == {"units": {}, "kept": {}}


def test_a_files_pages_are_those_of_its_units_and_its_start_page(desk, tmp_path):
    digests = desk.digests()
    page = {"index.html": b"<html>the library</html>", "Radiohead/Creep/sheet.html": b"<html>Creep</html>",
            "Radiohead/Creep/sheet.pdf": b"%PDF Creep", "Oasis/Wonderwall/sheet.html": b"<html>Wonderwall</html>",
            "Gone/Away/sheet.html": b"<html>gone</html>", "Radiohead/Creep/again.pdf": b"%PDF Creep"}

    def entry(path, unit=None, digest=None):
        found = {"path": path, "url": "/" + path, "size": len(page[path]),
                 "sha256": hashlib.sha256(page[path]).hexdigest(), "type": "text/html", "headers": {}}
        return found | ({"unit": unit, "digest": digest} if unit else {})

    manifest = {"format": 1, "start": "index.html", "files": [
        entry("index.html"),
        entry("Gone/Away/sheet.html", "song/gone/away", "0" * 64),  # a unit the file hasn't got
        entry("Oasis/Wonderwall/sheet.html", WONDERWALL, "1" * 64),  # made of the song as it was before
        entry("Radiohead/Creep/again.pdf", CREEP, digests[CREEP]),  # the same bytes as sheet.pdf: one blob
        entry("Radiohead/Creep/sheet.html", CREEP, digests[CREEP]),
        entry("Radiohead/Creep/sheet.pdf", CREEP, digests[CREEP]),
    ]}
    asked = []

    def fetch(path):
        asked.append(path)
        return page[path]

    made = export(desk, tmp_path / "x.caracole", pages=(manifest, fetch))
    got = members(made.path)
    listed = json.loads(got["pages.json"])
    assert listed["format"] == 1 and listed["start"] == "index.html"
    assert [e["path"] for e in listed["files"]] == ["index.html", "Radiohead/Creep/again.pdf",
                                                   "Radiohead/Creep/sheet.html", "Radiohead/Creep/sheet.pdf"]
    blobs = sorted(n for n in got if n.startswith("pages/"))
    assert blobs == sorted({f"pages/{hashlib.sha256(page[p]).hexdigest()}" for p in
                            ("index.html", "Radiohead/Creep/sheet.html", "Radiohead/Creep/sheet.pdf")})
    names = list(got)
    assert names.index("pages.json") > max(names.index(n) for n in names if n.startswith("files/"))
    assert names.index("pages.json") < min(names.index(n) for n in blobs)
    assert json.loads(got["caracole.json"])["pages"] == 4
    assert "Gone/Away/sheet.html" not in asked

    without = members(export(desk, tmp_path / "s.caracole", ["songbooks"], pages=(manifest, fetch)).path)
    assert "pages.json" not in without and not [n for n in without if n.startswith("pages/")]


def test_a_page_that_changed_since_its_manifest_is_left_out(desk, tmp_path):
    good = b"<html>the library</html>"
    manifest = {"format": 1, "start": "index.html", "files": [
        {"path": "index.html", "url": "/offline/index.html", "size": 3, "sha256": hashlib.sha256(good).hexdigest(),
         "type": "text/html", "headers": {}},
        {"path": "Radiohead/Creep/sheet.html", "url": "/x", "size": 3, "sha256": "2" * 64, "type": "text/html",
         "headers": {}, "unit": CREEP, "digest": desk.digests()[CREEP]}]}
    got = members(export(desk, tmp_path / "x.caracole", pages=(manifest, lambda path: good)).path)
    assert [e["path"] for e in json.loads(got["pages.json"])["files"]] == ["index.html"]


def test_the_file_name_is_the_librarys_name_and_the_day():
    assert peer_file.file_name("horde_logbook", datetime(2026, 11, 3, 21, 10, tzinfo=UTC)) == \
        "horde_logbook-03-11-26.caracole"
    assert peer_file.file_name("a/b: c?", NOW) == "a_b_ c_-03-11-26.caracole"  # download_names' cleaning
    assert peer_file.file_name(" .Canciones. ", NOW) == "Canciones-03-11-26.caracole"
    assert peer_file.file_name(None, NOW) == "caracole-03-11-26.caracole"
    assert peer_file.file_name("...", NOW) == "caracole-03-11-26.caracole"
    long = peer_file.file_name("斑" * 100, NOW)
    assert len(long.removesuffix("-03-11-26.caracole").encode("utf-8")) <= 150 and long.startswith("斑")


@pytest.mark.parametrize("parts", [[], ["indexes"], ["library", "lyrics"]])
def test_parts_other_than_the_three_or_the_indexes_alone_are_refused(desk, tmp_path, parts):
    with pytest.raises(peer_file.FileError):
        export(desk, tmp_path / "x.caracole", parts)
    assert list(tmp_path.glob("*.caracole")) == [] and not list(tmp_path.glob(".x.caracole*"))


def test_a_file_there_already_is_never_written_over(desk, tmp_path):
    (tmp_path / "x.caracole").write_bytes(b"mine")
    with pytest.raises(peer_file.FileError, match="already"):
        export(desk, tmp_path / "x.caracole")
    assert (tmp_path / "x.caracole").read_bytes() == b"mine"


def test_the_same_library_exported_twice_is_the_same_file(desk, tmp_path):
    a, b = export(desk, tmp_path / "a.caracole"), export(desk, tmp_path / "b.caracole")
    assert a.path.read_bytes() == b.path.read_bytes()
