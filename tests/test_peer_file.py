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


# --- a file read back, refused, and taken from -----------------------------------------------------------------------


@pytest.fixture
def exported(desk, tmp_path):
    return export(desk, tmp_path / "desk.caracole")


@pytest.fixture
def studio(tmp_path):
    """Another library, Studio, whose file desk imports."""
    lib = Library(tmp_path / "studio", sync_id=OTHER_ID)
    lib.song("Radiohead", "Creep", sheet=b"[G]Creep, as Studio plays it")
    yield lib
    lib.close()


@pytest.fixture
def in_utc(monkeypatch):
    """The server's zone UTC, as the vectors' (a day is said in it)."""
    import time

    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def by_studio(studio: Library, path: Path) -> Path:
    return peer_file.export_file(studio.conn, studio.cfg, studio.overrides(), studio.books(), path,
                                 ["library", "songbooks"], now=NOW, version="0.1.0", name="Studio").path


def zip_with(folder: Path, members: dict[str, bytes], name: str = "made.caracole") -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as z:
        for member, data in members.items():
            z.writestr(member, data)
    return path


def rewritten(source: Path, target: Path, change: dict[str, bytes | None]) -> Path:
    """``source``'s members, in order, each ``change`` names replaced (None: left out), those it adds at the end."""
    with zipfile.ZipFile(source) as z, zipfile.ZipFile(target, "w") as out:
        for info in z.infolist():
            if info.filename in change:
                if change[info.filename] is not None:
                    out.writestr(info, change[info.filename])
            else:
                out.writestr(info, z.read(info))
        for name, data in change.items():
            if name not in z.namelist() and data is not None:
                out.writestr(name, data)
    return target


def declaring(path: Path, sizes: dict[str, int]) -> Path:
    """The zip at ``path`` with its central directory declaring each member of ``sizes`` that size."""
    data = bytearray(path.read_bytes())
    at = data.rfind(b"PK\x05\x06")
    count, start = int.from_bytes(data[at + 10:at + 12], "little"), int.from_bytes(data[at + 16:at + 20], "little")
    for _ in range(count):
        assert data[start:start + 4] == b"PK\x01\x02"
        n, m, k = (int.from_bytes(data[start + o:start + o + 2], "little") for o in (28, 30, 32))
        name = data[start + 46:start + 46 + n].decode()
        if name in sizes:
            data[start + 24:start + 28] = sizes[name].to_bytes(4, "little")
        start += 46 + n + m + k
    path.write_bytes(bytes(data))
    return path


MANIFEST_OK = json.dumps({"format": 1, "caracole": "0.1.0", "schema": db.SCHEMA_VERSION, "sync": sync.FORMAT,
                          "id": OWN_ID, "name": "Desk", "made": MADE, "parts": ["library"], "songs": 0,
                          "songbooks": 0, "units": 0, "files": 0, "pages": 0, "indexes": []}).encode()
STATE_OK = json.dumps(sync.state_document(OWN_ID, "0.1.0", "Desk", {}, None, now=MADE, kept={})).encode()
SMALL = {"caracole.json": MANIFEST_OK, "state.json": STATE_OK, "bases.json": b"{}", "units.jsonl": b""}


def test_a_file_read_back_is_what_was_exported_unit_for_unit(exported, desk, tmp_path):
    f = peer_file.read_file(exported.path)
    with peer_file.FileSource(f, None, tmp_path) as src:
        for unit_id, unit in f.state.units.items():
            assert sync.digest_of(sync.value_of_document(unit_id, src.unit(unit_id))) == unit.digest
    assert (f.id, f.name, f.made, f.holds, f.index_only) == (OWN_ID, "Desk", MADE, ("library", "songbooks"), False)
    assert f.state.units == desk.units() and f.manifest["songs"] == 2 and f.path == exported.path
    peer_file.check_whole(f)


def test_reading_a_file_leaves_no_file_open(exported):
    import os

    before = len(os.listdir("/proc/self/fd"))
    f = peer_file.read_file(exported.path)
    assert len(os.listdir("/proc/self/fd")) == before
    peer_file.check_whole(f)
    assert len(os.listdir("/proc/self/fd")) == before


def test_its_kept_files_are_read_by_their_sha256_and_checked(desk, exported, tmp_path):
    f = peer_file.read_file(exported.path)
    sha = kept_shas(desk, "radiohead/creep")[0]
    with peer_file.FileSource(f, None, tmp_path) as src:
        assert hashlib.sha256(src.file("radiohead/creep", "sheet.txt", sha)).hexdigest() == sha
        with pytest.raises(sync.PeerError):
            src.file("radiohead/creep", "sheet.txt", "0" * 64)  # neither in the file nor kept here
    # a file it lacks, kept here already, comes from here
    with peer_file.FileSource(f, desk.conn, desk.cfg.library_dir) as src:
        missing = rewritten(exported.path, tmp_path / "lacks.caracole", {f"files/{sha}": None})
        with peer_file.FileSource(peer_file.read_file(missing), desk.conn, desk.cfg.library_dir) as lacking:
            assert lacking.file("radiohead/creep", "sheet.txt", sha) == src.file("radiohead/creep", "sheet.txt", sha)


def test_a_blob_whose_bytes_arent_its_name_is_refused_when_read(exported, desk, tmp_path):
    sha = kept_shas(desk, "radiohead/creep")[0]
    bad = rewritten(exported.path, tmp_path / "bad.caracole", {f"files/{sha}": b"other bytes"})
    f = peer_file.read_file(bad)
    with peer_file.FileSource(f, None, tmp_path) as src, pytest.raises(sync.PeerError):
        src.file("radiohead/creep", "sheet.txt", sha)
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.check_whole(f)


def test_a_unit_of_a_part_the_file_holds_that_its_state_lacks_is_one_its_caracole_hasnt_got(exported, tmp_path):
    with peer_file.FileSource(peer_file.read_file(exported.path), None, tmp_path) as src:
        assert src.unit("song/not/here") is None and src.unit("songbook/nothing") is None


def test_a_unit_the_file_doesnt_speak_for_is_an_error_never_a_removal(desk, tmp_path):
    songbooks = peer_file.read_file(export(desk, tmp_path / "s.caracole", ["songbooks"]).path)
    with peer_file.FileSource(songbooks, None, tmp_path) as src:
        with pytest.raises(sync.PeerError):
            src.unit(WONDERWALL)  # a song of the library, which the file doesn't hold
        with pytest.raises(sync.PeerError):
            src.unit("alias/radiohead")
        assert src.unit(CREEP) is not None  # the song its songbook lists, which it carries
    wonderwall = desk.conn.execute("SELECT id FROM songs WHERE key = 'oasis/wonderwall'").fetchone()[0]
    from caracole.songs import get_song

    (song_dir(desk.cfg.library_dir, get_song(desk.conn, wonderwall)) / "sheet.txt").write_bytes(b"edited elsewhere")
    left = peer_file.read_file(export(desk, tmp_path / "left.caracole").path)
    with peer_file.FileSource(left, None, tmp_path) as src, pytest.raises(sync.PeerError, match="left out"):
        src.unit(WONDERWALL)  # named by its state, its document left out


@pytest.mark.parametrize("bad", ["../evil", "files/notahash", "extra.txt", "files/" + "A" * 64, "/etc/passwd",
                                 "pages/" + "a" * 63, "files/" + "a" * 64 + "/x", "files/"])
def test_a_member_outside_the_layout_is_refused_whole(tmp_path, bad):
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.read_file(zip_with(tmp_path, {**SMALL, bad: b"x"}))


def test_a_member_named_twice_is_refused_whole(tmp_path):
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile warns of the duplicate it writes
        path = tmp_path / "twice.caracole"
        with zipfile.ZipFile(path, "w") as z:
            for name, data in SMALL.items():
                z.writestr(name, data)
            z.writestr("state.json", STATE_OK)
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.read_file(path)


def test_a_file_cut_short_or_declaring_more_than_it_may_is_refused(tmp_path, exported):
    cut = tmp_path / "cut.caracole"
    cut.write_bytes(exported.path.read_bytes()[:-500])
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.read_file(cut)
    blob = "files/" + "a" * 64
    big = declaring(zip_with(tmp_path, {**SMALL, blob: b"x"}, "big.caracole"), {blob: peer_file.FILE_MAX + 1})
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.read_file(big)
    blobs = {f"files/{c * 64}": b"x" for c in "abc"}
    many = declaring(zip_with(tmp_path, {**SMALL, **blobs}, "many.caracole"), dict.fromkeys(blobs, 3 * 1024 ** 3))
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.read_file(many)
    state = declaring(zip_with(tmp_path, SMALL, "state.caracole"), {"state.json": peer_file.JSON_MAX + 1})
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.read_file(state)


def test_a_crc_error_is_found_before_anything_is_taken(desk, exported, tmp_path):
    data = bytearray(exported.path.read_bytes())
    sheet = b"[Em]Today is gonna be the day"
    at = data.find(sheet)
    data[at] ^= 0xFF
    broken = tmp_path / "crc.caracole"
    broken.write_bytes(bytes(data))
    f = peer_file.read_file(broken)  # its directory and JSON whole: the blob is read when asked for
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.check_whole(f)


def test_a_document_or_a_file_that_isnt_as_its_state_says_is_refused_whole(desk, exported, tmp_path):
    lines = lines_of(members(exported.path)["units.jsonl"])
    lines[0]["unit"]["names"]["album"] = "another album"
    other = rewritten(exported.path, tmp_path / "doc.caracole",
                      {"units.jsonl": b"".join(json.dumps(line).encode() + b"\n" for line in lines)})
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.check_whole(peer_file.read_file(other))
    sha = kept_shas(desk, "radiohead/creep")[0]
    lacking = rewritten(exported.path, tmp_path / "lacks.caracole", {f"files/{sha}": None})
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.check_whole(peer_file.read_file(lacking))
    extra = rewritten(exported.path, tmp_path / "extra.caracole",
                      {"units.jsonl": members(exported.path)["units.jsonl"] + json.dumps(
                          {"format": sync.FORMAT, "id": "song/not/named", "digest": "0" * 64, "unit": {}}).encode()})
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.check_whole(peer_file.read_file(extra))


@pytest.mark.parametrize("content", [b"hello", b"", b"PK\x05\x06" + bytes(18)])
def test_something_else_is_not_a_file_caracole_exported(tmp_path, content):
    (tmp_path / "x").write_bytes(content)
    with pytest.raises(peer_file.FileError, match="isn't a file caracole exported"):
        peer_file.read_file(tmp_path / "x")


def test_a_zip_of_something_else_or_a_folder_is_not_a_file_caracole_exported(tmp_path):
    with pytest.raises(peer_file.FileError, match="isn't a file caracole exported"):
        peer_file.read_file(zip_with(tmp_path, {"photo.jpg": b"\xff\xd8", "caracole.json": MANIFEST_OK}))
    with pytest.raises(peer_file.FileError, match="isn't a file caracole exported"):
        peer_file.read_file(tmp_path)
    plain = tmp_path / "plain.sqlite"
    sqlite3.connect(plain).execute("CREATE TABLE t (x)").connection.close()
    with pytest.raises(peer_file.FileError, match="isn't a file caracole exported"):
        peer_file.read_file(plain)


def test_another_format_is_said_by_its_number(tmp_path):
    other = json.loads(MANIFEST_OK) | {"format": 2}
    with pytest.raises(peer_file.FileError, match=r"another version of caracole \(format 2\)"):
        peer_file.read_file(zip_with(tmp_path, {**SMALL, "caracole.json": json.dumps(other).encode()}, "f2"))
    later = json.loads(MANIFEST_OK) | {"sync": sync.FORMAT + 1}
    with pytest.raises(peer_file.FileError, match="another version of caracole"):
        peer_file.read_file(zip_with(tmp_path, {**SMALL, "caracole.json": json.dumps(later).encode()}, "s3"))


@pytest.mark.parametrize("change", [{"id": None}, {"id": "nothex"}, {"made": "yesterday"}, {"parts": "library"}])
def test_a_manifest_that_cant_be_read_is_refused(tmp_path, change):
    manifest = json.loads(MANIFEST_OK) | change
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.read_file(zip_with(tmp_path, {**SMALL, "caracole.json": json.dumps(manifest).encode()}))


def test_the_indexes_are_held_only_at_this_databases_schema(desk, tmp_path):
    made = export(desk, tmp_path / "i.caracole", ["library", "songbooks", "indexes"])
    assert peer_file.read_file(made.path).holds == ("library", "songbooks", "indexes")
    manifest = json.loads(members(made.path)["caracole.json"]) | {"schema": db.SCHEMA_VERSION - 1}
    older = rewritten(made.path, tmp_path / "older.caracole", {"caracole.json": json.dumps(manifest).encode()})
    assert peer_file.read_file(older).holds == ("library", "songbooks")


def test_an_index_export_is_an_import_of_indexes_alone(conn, tmp_path):
    index_transfer.export(conn, tmp_path / "i.sqlite", now=NOW)
    f = peer_file.read_file(tmp_path / "i.sqlite")
    assert (f.index_only, f.holds, f.id, f.state, f.bases) == (True, ("indexes",), None, None, {})
    assert (f.name, f.made) == ("i.sqlite", MADE)
    assert peer_file.read_file(tmp_path / "i.sqlite", name="phone-indexes.sqlite").name == "phone-indexes.sqlite"
    peer_file.check_importable(f, conn, own=OWN_ID)
    peer_file.check_whole(f)
    with peer_file.FileSource(f, None, tmp_path) as src:
        assert src.indexes(tmp_path / "copy.sqlite") and (tmp_path / "copy.sqlite").read_bytes() == (
            tmp_path / "i.sqlite").read_bytes()
        assert src.pages() is None


def test_an_index_export_of_another_schema_holds_nothing_and_is_refused(conn, tmp_path):
    index_transfer.export(conn, tmp_path / "i.sqlite", now=NOW)
    file = sqlite3.connect(tmp_path / "i.sqlite")
    file.execute(f"UPDATE {index_transfer.META} SET value = '3' WHERE key = 'schema'")
    file.commit()
    file.close()
    f = peer_file.read_file(tmp_path / "i.sqlite")
    assert f.holds == ()
    with pytest.raises(peer_file.FileError, match="another version of caracole"):
        peer_file.check_importable(f, conn, own=OWN_ID)


def test_its_indexes_are_copied_out_once_it_holds_them(desk, tmp_path):
    made = export(desk, tmp_path / "i.caracole", ["library", "songbooks", "indexes"])
    with peer_file.FileSource(peer_file.read_file(made.path), None, tmp_path) as src:
        assert src.indexes(tmp_path / "out.sqlite")
        assert (tmp_path / "out.sqlite").read_bytes() == members(made.path)["indexes.sqlite"]
    with peer_file.FileSource(peer_file.read_file(export(desk, tmp_path / "n.caracole").path), None,
                              tmp_path) as src:
        assert not src.indexes(tmp_path / "none.sqlite") and not (tmp_path / "none.sqlite").exists()


def test_its_pages_are_read_by_their_sha256(desk, tmp_path):
    page = b"<html>the library</html>"
    sha = hashlib.sha256(page).hexdigest()
    manifest = {"format": 1, "start": "index.html", "files": [
        {"path": "index.html", "url": "/offline/index.html", "size": len(page), "sha256": sha, "type": "text/html",
         "headers": {}}]}
    f = peer_file.read_file(export(desk, tmp_path / "p.caracole", pages=(manifest, lambda path: page)).path)
    with peer_file.FileSource(f, None, tmp_path) as src:
        assert src.pages() == manifest and src.page(sha) == page
        with pytest.raises(sync.PeerError):
            src.page("0" * 64)


def test_its_bases_are_each_peers_units_and_kept_answers(desk, tmp_path):
    sync.record_agreement(desk.conn, OTHER_ID, desk.units(), desk.units(), "2026-11-01T10:00:00Z")
    sync.record_kept(desk.conn, OTHER_ID, {"song/x/y": ("h", "t")}, "2026-11-02T10:00:00Z")
    f = peer_file.read_file(export(desk, tmp_path / "b.caracole").path)
    base, kept = f.base_for(OTHER_ID)
    assert base == sync.base_of(desk.conn, OTHER_ID) and kept == {"song/x/y": ("h", "t", "2026-11-02T10:00:00Z")}
    assert f.base_for("1122334455667788") == (None, {}) and f.base_for(None) == (None, {})


def test_own_export_and_one_no_newer_than_the_last_sync_are_refused(desk, studio, exported, tmp_path, in_utc):
    with pytest.raises(peer_file.FileError, match="this library's own export"):
        peer_file.check_importable(peer_file.read_file(exported.path), desk.conn, own=OWN_ID)
    theirs = peer_file.read_file(by_studio(studio, tmp_path / "studio.caracole"))
    peer_file.check_importable(theirs, desk.conn, own=OWN_ID)  # never synced: newer than nothing
    agreed = {"song/x/y": sync.Unit("song/x/y", "X - Y", "1" * 64)}
    sync.record_agreement(desk.conn, OTHER_ID, agreed, agreed, "2026-11-02T08:00:00Z")
    peer_file.check_importable(theirs, desk.conn, own=OWN_ID)  # synced before the file was made
    sync.record_agreement(desk.conn, OTHER_ID, agreed, agreed, MADE)  # the file's made, or later
    with pytest.raises(peer_file.FileError,
                       match=r"^Nothing in this file is newer than your sync with Studio on 03/11/26\.$"):
        peer_file.check_importable(theirs, desk.conn, own=OWN_ID)


def test_a_kept_answer_later_than_the_file_makes_it_older_too(desk, studio, tmp_path, in_utc):
    theirs = peer_file.read_file(by_studio(studio, tmp_path / "studio.caracole"))
    sync.record_kept(desk.conn, OTHER_ID, {CREEP: ("h", "t")}, "2026-11-04T09:00:00Z")
    with pytest.raises(peer_file.FileError, match="your sync with Studio on 04/11/26"):
        peer_file.check_importable(theirs, desk.conn, own=OWN_ID)
