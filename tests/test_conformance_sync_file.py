"""The ``.caracole`` file, for the phone: what peer_file.py writes, reads, refuses and takes, over the sync corpus's
fixture libraries, written for the Kotlin sync lane (core/sync/file: ``SyncFiles``, ``SyncFile``, ``FileSource``) to
agree with (docs/superpowers/plans/2026-11-03-sync-redesign.md §3.3).

**Files** (``vectors/sync/files/<name>.caracole``), each ``caracole.peer_file.export_file`` of a fixture replayed
(test_conformance_sync.py's ``Corpus``), its id ``EXPORTER``, made ``MADE``, the library called ``"Desk"``, by
caracole ``0.1.0``:

- ``full``: ``sync/fixtures/rich``, the library and the songbooks, with pages (the record's ``pages``: one of them
  Creep's kept sheet.txt, held once, under ``files/``), and two bases (kv ``sync:base:<id>``, the record's ``kv``),
  one of them with a kept answer for ``IMPORTER``;
- ``songbooks``: ``rich``'s songbooks alone, with the songs they list;
- ``indexes``: ``sync/fixtures/file_indexed`` (``plain`` with a gtptabs.com sitemap read), the three parts. Its
  ``indexes.sqlite`` is ``index_transfer.export``'s, its ``caracole_export`` row ``source`` empty;
- ``left``: ``rich``, the library and the songbooks, Karma Police's kept sheet.txt changed on disk (the record's
  ``changed``: ``{unit: {file name: its bytes now, base64}}``), so it is left out (``left``).

The fixtures this file adds (helpers.corpus's format, as the sync corpus's): ``sync/fixtures/file_conflict``, ``rich``
with Creep's and Karma Police's own versions changed, and ``file_indexed``.

**Vectors**: sync/file.jsonl, a header, then a record a line, ``{fn, case, …, out}``:

- ``export``: ``{fixture, id, kv, parts, now, name, version, pages, changed, file}``, ``pages`` the pages given
  (``{"manifest": …, "bytes": {path: base64}}``, or null), ``file`` the file written; ``out`` ``{members, manifest,
  state, bases, units, files, pages, page_blobs, left}``: the members' names in order, each JSON member parsed
  (``units`` a list of ``units.jsonl``'s lines), ``files`` and ``page_blobs`` the blobs' SHA-256 in order, and the
  songs left out, ``[unit, why]`` each (``peer_file.CHANGED``, ``TOO_BIG``);
- ``file_name``: ``in`` ``{name, when}`` (``when`` ISO 8601 with its offset, whose day the name takes), ``out`` the
  name;
- ``read``: ``{file}`` (a file above; with ``member``, that member of it, an index export, and ``name`` its name) or
  ``{bytes}`` (base64, with ``name`` for an index export; ``cut``: the file above less its last ``cut`` bytes),
  ``out`` ``{id, name, made, holds, index_only, units: {id: digest}, documents: [id]}``, or ``{"error": <the
  words>}``;
- ``unit``: ``{file, id}`` (with ``member``: an index export), ``FileSource.unit`` of a file above, ``out``
  ``{"unit": <its value's digest>}``, ``{"unit": null}`` (a unit of a part the file holds that its caracole hasn't
  got), or ``{"error": <the words>}`` (one it names but holds no document of, or of a part it doesn't hold);
- ``check_whole``: ``{bytes}``, a file read whole, ``out`` ``{"error": <the words> or null}``;
- ``check_importable``: ``{file, own, kv}`` (kv this side holds) or ``{bytes, name, own, kv}``, under TZ=UTC,
  ``out`` ``{"error": <the words> or null}``;
- ``import``: ``{here, id, kv, file, parts, choices, prefer}`` (with ``member``: an index export): ``here`` the
  fixture this side is (its id ``id``, its kv ``kv`` laid over it), the file, the parts asked, ``choices`` ``{unit:
  here|there|skip}``, ``prefer`` here, there or null for a conflict not chosen; ``out``
  ``{differences, scoped, taken, left, after, base_after, kept_after}``: ``compare_file``'s differences ``[id,
  proposal, why]`` (within the parts the file holds), those of the parts asked, the take's (``apply_units`` from a
  ``FileSource``, at ``TAKEN``) units taken and left ``[id, why]``, this side's digests after, and kv ``sync:base:<the
  file's id>``'s text after ``record_import`` (null: none) and its kept answers.

The answers are the same under any hash seed (``test_the_vectors_are_the_same_whatever_the_hash_seed``). Regenerate
with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pytest

from helpers.corpus import VECTORS, check, jsonl
from helpers.peer_libraries import Library
from test_conformance_sync import Corpus, build_plain, build_rich, fixture_records

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
MADE_BY = "tests/test_conformance_sync_file.py"
SYNC = VECTORS / "sync"
VECTOR = SYNC / "file.jsonl"
NOW = datetime(2026, 11, 3, 21, 10, tzinfo=UTC)
MADE = "2026-11-03T21:10:00Z"
TAKEN = "2026-11-04T09:00:00Z"  # when an import's take is made
T0, T1 = "2026-11-01T10:00:00Z", "2026-11-02T10:00:00Z"
EXPORTER, IMPORTER, FRESH, THIRD = "a1b2c3d4e5f60718", "0f1e2d3c4b5a6978", "2233445566778899", "1122334455667788"
CREEP, KARMA = "song/radiohead/creep", "song/radiohead/karma-police"
ZIP_DATE = (2026, 11, 3, 21, 10, 0)
FILES = ("full", "songbooks", "indexes", "left")
PARTS = ("library", "songbooks", "indexes")


# --- the fixtures this file adds --------------------------------------------------------------------------------------


def build_conflict(lib: Library) -> None:
    from caracole.overrides import add_version

    build_rich(lib)
    add_version(lib.cfg.overrides_file, "Radiohead - Creep", "key=Am&capo=0")
    add_version(lib.cfg.overrides_file, "Radiohead - Karma Police", "key=Bm&capo=0")


def build_indexed(lib: Library) -> None:
    from caracole import gtptabs_fetch, site_index

    build_plain(lib)
    site = gtptabs_fetch.SITE
    locs = ["https://gtptabs.com/tabs/2/blur.html", "https://gtptabs.com/tabs/2/blur/beetlebum.html"]
    site_index._store(lib.conn, site, "sitemap-tabs-1.xml", [site.row(loc) for loc in locs],
                      {"etag": '"1"', "last_modified": None}, datetime(2026, 11, 2, 8, 0, tzinfo=UTC))


HERE: dict[str, Callable[[Library], None]] = {"file_conflict": build_conflict, "file_indexed": build_indexed}


class FileCorpus(Corpus):
    """The sync corpus's fixtures, and this file's (``HERE``), built and replayed; the files exported, in
    ``workdir/files``."""

    def __init__(self, workdir: Path):
        super().__init__(workdir)
        self.exports: dict[str, Any] = {}  # each file's peer_file.Made

    def built(self, area: str, name: str) -> Library:
        if area == "sync" and name in HERE:
            if (area, name) not in self._built:
                lib = self.library(f"built/{area}/{name}")
                HERE[name](lib)
                self._texts[area, name] = jsonl(fixture_records(lib), corpus=f"{area}/fixtures/{name}",
                                                made_by=MADE_BY)
                self._built[area, name] = lib
            return self._built[area, name]
        return super().built(area, name)

    def file_path(self, name: str) -> Path:
        """The file ``name`` (``FILES``), exported once."""
        path = self.workdir / "files" / f"{name}.caracole"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            EXPORTS[name](self, path)
        return path


# --- the files ---------------------------------------------------------------------------------------------------------


def _pages(lib: Library) -> dict[str, Any]:
    """The pages ``full`` holds: its start page, Creep's sheet page, its PDF and its kept sheet.txt (which the file
    holds once, under ``files/``), and two that it leaves out (a page of a unit it hasn't got, one made of Karma
    Police as it was before)."""
    from caracole.library import song_dir
    from caracole.songs import find_song

    digests = lib.digests()
    data = {"index.html": b"<!doctype html><title>Desk</title>", "Radiohead/Creep/sheet.html": b"<p>Creep</p>",
            "Radiohead/Creep/sheet.pdf": b"%PDF-1.4 Creep", "Radiohead/Karma Police/sheet.html": b"<p>Karma</p>",
            "Gone/Away/sheet.html": b"<p>Gone</p>",
            "Radiohead/Creep/sheet.txt": (song_dir(lib.cfg.library_dir, find_song(lib.conn, "radiohead/creep"))
                                          / "sheet.txt").read_bytes()}

    def entry(path: str, unit: str | None = None, digest: str | None = None) -> dict[str, Any]:
        found = {"path": path, "url": "/" + path.replace(" ", "%20"), "size": len(data[path]),
                 "sha256": hashlib.sha256(data[path]).hexdigest(),
                 "type": "text/plain; charset=utf-8" if path.endswith(".txt") else "text/html; charset=utf-8",
                 "headers": {"Referrer-Policy": "same-origin"}}
        return found | ({"unit": unit, "digest": digest} if unit else {})

    manifest = {"format": 1, "start": "index.html", "files": [
        entry("index.html"), entry("Gone/Away/sheet.html", "song/gone/away", "0" * 64),
        entry("Radiohead/Creep/sheet.html", CREEP, digests[CREEP]),
        entry("Radiohead/Creep/sheet.pdf", CREEP, digests[CREEP]),
        entry("Radiohead/Creep/sheet.txt", CREEP, digests[CREEP]),
        entry("Radiohead/Karma Police/sheet.html", KARMA, "1" * 64)]}
    return {"manifest": manifest, "bytes": {p: base64.b64encode(b).decode("ascii") for p, b in data.items()}}


def _exporter(corpus: FileCorpus, fixture: str, tag: str, kv: dict[str, str]) -> Library:
    from caracole import db
    from caracole import peer_sync as sync

    lib = corpus.replayed("sync", fixture, tag=f"-export-{tag}")
    db.kv_set(lib.conn, sync.ID_KEY, EXPORTER)
    for key, value in kv.items():
        db.kv_set(lib.conn, key, value)
    return lib


def _bases(corpus: FileCorpus) -> dict[str, str]:
    """``full``'s bases: one for a third caracole, and one for ``IMPORTER``, no unit agreed and Karma Police kept
    there, as an import of ``IMPORTER``'s file (``file_conflict``) answered "keep mine"."""
    from caracole import peer_sync as sync

    rich, conflict = corpus.replayed("sync", "rich").digests(), corpus.replayed("sync", "file_conflict").digests()
    third = {"format": sync.FORMAT, "units": {CREEP: [rich[CREEP], T0]}}
    importer = {"format": sync.FORMAT, "units": {}, "kept": {KARMA: [rich[KARMA], conflict[KARMA], T1]}}
    return {sync.BASE_KEY + THIRD: json.dumps(third), sync.BASE_KEY + IMPORTER: json.dumps(importer)}


def _export(lib: Library, path: Path, parts: tuple[str, ...], pages: dict[str, Any] | None) -> Any:
    from caracole import index_transfer, peer_file

    given = None
    if pages is not None:
        data = {p: base64.b64decode(b) for p, b in pages["bytes"].items()}
        given = (pages["manifest"], data.__getitem__)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(index_transfer, "_db_path", lambda conn: None)  # the export's "source": no path of this run
        return peer_file.export_file(lib.conn, lib.cfg, lib.overrides(), lib.books(), path, list(parts), now=NOW,
                                     version="0.1.0", name="Desk", pages=given)


# Each file: its fixture, its parts, with pages, with bases, and the kept files changed on disk before it is made
# ({unit: {file name: bytes}}).
SPECS: dict[str, tuple[str, tuple[str, ...], bool, bool, dict[str, dict[str, bytes]]]] = {
    "full": ("rich", ("library", "songbooks"), True, True, {}),
    "songbooks": ("rich", ("songbooks",), False, False, {}),
    "indexes": ("file_indexed", PARTS, False, False, {}),
    "left": ("rich", ("library", "songbooks"), False, False, {KARMA: {"sheet.txt": b"[Em]Karma, edited elsewhere"}}),
}


def _changed(lib: Library, changed: dict[str, dict[str, bytes]]) -> None:
    from caracole.library import song_dir
    from caracole.songs import find_song

    for unit, files in changed.items():
        folder = song_dir(lib.cfg.library_dir, find_song(lib.conn, unit.partition("/")[2]))
        for name, data in files.items():
            (folder / name).write_bytes(data)


def _spec_export(name: str) -> Callable[[FileCorpus, Path], None]:
    def made(corpus: FileCorpus, path: Path) -> None:
        fixture, parts, pages, bases, changed = SPECS[name]
        lib = _exporter(corpus, fixture, name, _bases(corpus) if bases else {})
        _changed(lib, changed)
        corpus.exports[name] = _export(lib, path, parts, _pages(lib) if pages else None)
    return made


EXPORTS = {name: _spec_export(name) for name in FILES}


def _members(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as z:
        return [(info.filename, z.read(info)) for info in z.infolist()]


def export_records(corpus: FileCorpus) -> list[dict]:
    records = []
    for name in FILES:
        fixture, parts, pages, bases, changed = SPECS[name]
        path = corpus.file_path(name)
        got = dict(_members(path))
        lib = corpus.replayed("sync", fixture, tag=f"-export-{name}")
        records.append({
            "fn": "export", "case": name, "fixture": fixture, "id": EXPORTER, "kv": _bases(corpus) if bases else {},
            "parts": list(parts), "now": MADE, "name": "Desk", "version": "0.1.0",
            "pages": _pages(lib) if pages else None,
            "changed": {u: {n: base64.b64encode(b).decode("ascii") for n, b in files.items()}
                        for u, files in changed.items()},
            "file": f"files/{name}.caracole",
            "out": {"members": list(got), "manifest": json.loads(got["caracole.json"]),
                    "state": json.loads(got["state.json"]), "bases": json.loads(got["bases.json"]),
                    "units": [json.loads(line) for line in got["units.jsonl"].splitlines()],
                    "files": [n.partition("/")[2] for n in got if n.startswith("files/")],
                    "pages": json.loads(got["pages.json"]) if "pages.json" in got else None,
                    "page_blobs": [n.partition("/")[2] for n in got if n.startswith("pages/")],
                    "left": [list(x) for x in corpus.exports[name].left]}})
    return records


NAMES = [("horde_logbook", "2026-11-03T21:10:00+00:00"), ("a/b: c?", "2026-11-03T21:10:00+00:00"),
         (" .Canciones. ", "2026-11-03T21:10:00+00:00"), (None, "2026-11-03T21:10:00+00:00"),
         ("...", "2026-11-03T21:10:00+00:00"), ("斑" * 100, "2026-11-03T21:10:00+00:00"),
         ("Bad 🎸 Band\tlive", "2026-11-03T21:10:00+00:00"), ("‏مكتبة", "2026-11-03T21:10:00+00:00"),
         ("Desk", "2026-11-03T23:30:00-05:00"), ("Desk", "2026-01-09T00:30:00+01:00")]


def file_name_records(corpus: FileCorpus) -> list[dict]:
    from caracole import peer_file

    return [{"fn": "file_name", "case": f"{name!r} at {when}", "in": {"name": name, "when": when},
             "out": peer_file.file_name(name, datetime.fromisoformat(when))} for name, when in NAMES]


# --- reading, refusing -------------------------------------------------------------------------------------------------


def _read_out(path: Path, name: str | None = None) -> dict[str, Any]:
    from caracole import peer_file

    try:
        f = peer_file.read_file(path, name=name)
    except peer_file.FileError as e:
        return {"error": str(e)}
    with peer_file.FileSource(f, None, path.parent) as src:
        documents = sorted(src.documents())
    return {"id": f.id, "name": f.name, "made": f.made, "holds": list(f.holds), "index_only": f.index_only,
            "units": {} if f.state is None else {u: x.digest for u, x in sorted(f.state.units.items())},
            "documents": documents}


def _zip(members: list[tuple[str, bytes]], *, comment: bytes = b"", zip64: bool = False,
         methods: dict[str, int] | None = None) -> bytes:
    """A zip of ``members``, in order, each dated as the files are and deflated (or as ``methods`` names), as the
    corpus writes one; with ``comment`` after its end record; with ``zip64``, in zip64's records whole (each member's
    sizes and offset in its extra field, the zip64 end record and its locator), as zipfile writes a big one."""
    import warnings
    from unittest import mock

    out = io.BytesIO()
    limits = (mock.patch.object(zipfile, "ZIP64_LIMIT", 0), mock.patch.object(zipfile, "ZIP_FILECOUNT_LIMIT", 0)) \
        if zip64 else ()
    with warnings.catch_warnings(), contextlib.ExitStack() as stack:
        warnings.simplefilter("ignore")  # a member named twice, which zipfile warns of
        for limit in limits:
            stack.enter_context(limit)
        with zipfile.ZipFile(out, "w") as z:
            z.comment = comment
            for name, data in members:
                info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
                info.compress_type = (methods or {}).get(name, zipfile.ZIP_DEFLATED)
                info.external_attr = 0o644 << 16
                z.writestr(info, data)
    return out.getvalue()


def _entries(data: bytes) -> list[tuple[int, int]]:
    """Where each member's central directory entry and local header begin in the zip ``data``."""
    at = data.rfind(b"PK\x05\x06")
    count, start = int.from_bytes(data[at + 10:at + 12], "little"), int.from_bytes(data[at + 16:at + 20], "little")
    found = []
    for _ in range(count):
        n, m, k = (int.from_bytes(data[start + o:start + o + 2], "little") for o in (28, 30, 32))
        found.append((start, int.from_bytes(data[start + 42:start + 46], "little")))
        start += 46 + n + m + k
    return found


def _renamed_locally(data: bytes, index: int, name: bytes) -> bytes:
    """The zip ``data`` with its ``index``-th member's local header naming it ``name``, of its name's length."""
    data = bytearray(data)
    _, header = _entries(bytes(data))[index]
    assert int.from_bytes(data[header + 26:header + 28], "little") == len(name)
    data[header + 30:header + 30 + len(name)] = name
    return bytes(data)


def _flagged(data: bytes, index: int, *, set_bits: int = 0, clear_bits: int = 0) -> bytes:
    """The zip ``data`` with its ``index``-th member's general purpose flags changed in its central directory entry
    and its local header."""
    data = bytearray(data)
    central, header = _entries(bytes(data))[index]
    for at in (central + 8, header + 6):
        flags = (int.from_bytes(data[at:at + 2], "little") | set_bits) & ~clear_bits
        data[at:at + 2] = flags.to_bytes(2, "little")
    return bytes(data)


def _declaring(data: bytes, sizes: dict[str, int]) -> bytes:
    """The zip ``data`` with its central directory declaring each member of ``sizes`` that size."""
    data = bytearray(data)
    at = data.rfind(b"PK\x05\x06")
    count, start = int.from_bytes(data[at + 10:at + 12], "little"), int.from_bytes(data[at + 16:at + 20], "little")
    for _ in range(count):
        n, m, k = (int.from_bytes(data[start + o:start + o + 2], "little") for o in (28, 30, 32))
        if data[start + 46:start + 46 + n].decode() in sizes:
            data[start + 24:start + 28] = sizes[data[start + 46:start + 46 + n].decode()].to_bytes(4, "little")
        start += 46 + n + m + k
    return bytes(data)


def blob_named(n: int) -> str:
    return f"files/{hashlib.sha256(str(n).encode()).hexdigest()}"


def _refused(corpus: FileCorpus) -> list[tuple[str, bytes]]:
    """Files made by hand, most of them refused, each by why: their bytes."""
    from caracole import peer_file

    full = _members(corpus.file_path("full"))
    manifest = json.loads(dict(full)["caracole.json"])
    small = [(n, b) for n, b in full if n in ("caracole.json", "state.json", "bases.json", "units.jsonl")]

    def with_manifest(**change: Any) -> bytes:
        return _zip([("caracole.json", json.dumps(manifest | change).encode()), *small[1:]])

    blob = "files/" + "a" * 64
    return [
        ("something else", b"hello, this is no file of caracole's\n"),
        ("a zip of something else", _zip([("photo.jpg", b"\xff\xd8\xff"), *small])),
        ("a member outside its layout", _zip([*small, ("../evil", b"x")])),
        ("a blob name that isn't a SHA-256", _zip([*small, ("files/" + "A" * 64, b"x")])),
        ("a member twice", _zip([*small, ("state.json", dict(full)["state.json"])])),
        ("another format", with_manifest(format=2)),
        ("another sync's", with_manifest(sync=manifest["sync"] + 1)),
        ("a manifest that names no caracole", with_manifest(id=None)),
        ("a blob bigger than it may be", _declaring(_zip([*small, (blob, b"x")]), {blob: peer_file.FILE_MAX + 1})),
        ("more than 8 GiB in all", _declaring(_zip([*small, ("indexes.sqlite", b"x"), *((blob_named(i), b"x")
                                                                                       for i in range(65))]),
                                              {"indexes.sqlite": 2 ** 32 - 1}
                                              | {blob_named(i): peer_file.FILE_MAX for i in range(65)})),
        # How the zip itself is read, as zipfile reads it: a reader of its own on the phone, whose Android ZipFile
        # refuses at open a name with a ".." or a name twice.
        ("an encrypted member", _flagged(_zip(small), 1, set_bits=0x1)),
        ("a member compressed as caracole doesn't", _zip(small, methods={"bases.json": zipfile.ZIP_BZIP2})),
        ("a member's name in cp437", _flagged(_zip([*small, ("é", b"x")]), 4, clear_bits=0x800)),
        ("a member its local header names otherwise", _renamed_locally(_zip(small), 1, b"state.jsoX")),
        ("a member's name cut at a NUL", _zip([*small[:3], ("units.jsonlZx", dict(small)["units.jsonl"])])
         .replace(b"units.jsonlZx", b"units.jsonl\x00x")),
        ("a file with a comment after it", _zip(small, comment=b"made by hand")),
        ("a file whose comment holds an end record's signature", _zip(small, comment=b"by hand, PK\x05\x06 and all")),
        ("a file in zip64's records", _zip(small, zip64=True)),
        ("a file in zip64's records, its zip64 end record gone", _zip(small, zip64=True).replace(b"PK\x06\x06",
                                                                                                 b"PK\x06\x00")),
    ]


def _index_export_of_schema(path: Path, schema: int) -> bytes:
    """An index export at ``schema``: an SQLite file of ``index_transfer.META`` alone, as small as SQLite makes one,
    which is what a reader reads of an export before its tables."""
    import sqlite3

    from caracole import index_transfer

    path.unlink(missing_ok=True)
    file = sqlite3.connect(path)
    try:
        file.execute("PRAGMA page_size = 512")
        file.execute(f"CREATE TABLE {index_transfer.META} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        file.executemany(f"INSERT INTO {index_transfer.META} (key, value) VALUES (?, ?)", [
            ("format", str(index_transfer.FORMAT)), ("schema", str(schema)), ("keys", "1"), ("caracole", "0.1.0"),
            ("exported_at", MADE), ("sites", '["gtptabs"]'), ("source", "")])
        file.commit()
    finally:
        file.close()
    return path.read_bytes()


def other_schema(corpus: FileCorpus) -> bytes:
    from caracole import db

    return _index_export_of_schema(corpus.workdir / "files" / "old-schema.sqlite", db.SCHEMA_VERSION + 1)


def _sqlite_refused(corpus: FileCorpus) -> list[tuple[str, bytes]]:
    """SQLite files that are no index export, each by why: one with no export's table (sqlite3's OperationalError),
    and SQLite's header with no database after it (its DatabaseError), which a reader tells apart."""
    import sqlite3

    path = corpus.workdir / "files" / "no-export.sqlite"
    path.unlink(missing_ok=True)
    file = sqlite3.connect(path)
    try:
        file.execute("PRAGMA page_size = 512")
        file.execute("CREATE TABLE photos (name TEXT)")
        file.commit()
    finally:
        file.close()
    return [("an SQLite file with no export's table", path.read_bytes()),
            ("SQLite's header and no database after it", b"SQLite format 3\x00" + bytes(range(256)) * 2)]


def _indexes_at_another_schema(corpus: FileCorpus) -> bytes:
    """``indexes``' members with its manifest's schema another, its indexes.sqlite a stub (never read here)."""
    from caracole import db

    members = []
    for name, data in _members(corpus.file_path("indexes")):
        if name == "caracole.json":
            data = json.dumps(json.loads(data) | {"schema": db.SCHEMA_VERSION + 1}).encode()
        elif name == "indexes.sqlite":
            data = b"SQLite format 3\x00"
        members.append((name, data))
    return _zip(members)


def read_records(corpus: FileCorpus) -> list[dict]:
    records = []
    for name in FILES:
        path = corpus.file_path(name)
        records.append({"fn": "read", "case": f"the file {name}", "file": f"files/{name}.caracole",
                        "out": _read_out(path)})
    index = corpus.workdir / "files" / "indexes-member.sqlite"
    index.write_bytes(dict(_members(corpus.file_path("indexes")))["indexes.sqlite"])
    records.append({"fn": "read", "case": "an index export, a file of the indexes alone",
                    "file": "files/indexes.caracole", "member": "indexes.sqlite", "name": "i.sqlite",
                    "out": _read_out(index, "i.sqlite")})
    old = other_schema(corpus)
    records.append({"fn": "read", "case": "an index export of another schema holds nothing",
                    "bytes": base64.b64encode(old).decode("ascii"), "name": "old.sqlite",
                    "out": _read_out(corpus.workdir / "files" / "old-schema.sqlite", "old.sqlite")})
    for case, data in _sqlite_refused(corpus):
        path = corpus.workdir / "files" / "refused.sqlite"
        path.write_bytes(data)
        records.append({"fn": "read", "case": case, "bytes": base64.b64encode(data).decode("ascii"),
                        "name": "refused.sqlite", "out": _read_out(path, "refused.sqlite")})
    other = corpus.workdir / "files" / "other-schema.caracole"
    other.write_bytes(_indexes_at_another_schema(corpus))
    records.append({"fn": "read", "case": "a file made at another schema holds its units but not its indexes",
                    "bytes": base64.b64encode(other.read_bytes()).decode("ascii"), "out": _read_out(other)})
    full = corpus.file_path("full").read_bytes()
    cut = corpus.workdir / "files" / "cut.caracole"
    cut.write_bytes(full[:-500])
    records.append({"fn": "read", "case": "a file cut short", "file": "files/full.caracole", "cut": 500,
                    "out": _read_out(cut)})
    for case, data in _refused(corpus):
        path = corpus.workdir / "files" / "refused.caracole"
        path.write_bytes(data)
        records.append({"fn": "read", "case": case, "bytes": base64.b64encode(data).decode("ascii"),
                        "out": _read_out(path)})
    return records


UNITS: list[tuple[str, str, str | None]] = [  # the file, the unit asked, the member (an index export)
    ("full", CREEP, None), ("full", "song/not/here", None), ("full", "removed/not/here", None),
    ("songbooks", KARMA, None), ("songbooks", "songbook/campfire", None), ("songbooks", "songbook/not-here", None),
    ("songbooks", "song/宋冬野/斑马斑马", None), ("songbooks", "removed/oasis/wonderwall", None),
    ("left", KARMA, None), ("left", CREEP, None),
    ("indexes", "song/soda-stereo/de-musica-ligera", "indexes.sqlite"),
]


def unit_records(corpus: FileCorpus) -> list[dict]:
    from caracole import peer_file
    from caracole import peer_sync as sync

    records = []
    for name, unit_id, member in UNITS:
        path, read_as = corpus.file_path(name), None
        if member is not None:
            path, read_as = corpus.workdir / "files" / f"{name}-{member}", member
            path.write_bytes(dict(_members(corpus.file_path(name)))[member])
        with peer_file.FileSource(peer_file.read_file(path, name=read_as), None, path.parent) as src:
            try:
                doc = src.unit(unit_id)
                out: dict[str, Any] = {"unit": None if doc is None else sync.digest_of(
                    sync.value_of_document(unit_id, doc))}
            except sync.PeerError as e:
                out = {"error": str(e)}
        records.append({"fn": "unit", "case": f"{name}: {unit_id}", "file": f"files/{name}.caracole", "id": unit_id}
                       | ({"member": member} if member else {}) | {"out": out})
    return records


def check_whole_records(corpus: FileCorpus) -> list[dict]:
    from caracole import peer_file

    full = _members(corpus.file_path("full"))
    by_name = dict(full)
    lines = [json.loads(line) for line in by_name["units.jsonl"].splitlines()]
    lines[0]["unit"]["names"]["album"] = "another album"
    other_doc = b"".join(json.dumps(line, ensure_ascii=False).encode() + b"\n" for line in lines)
    first_blob = next(n for n, _ in full if n.startswith("files/"))
    crc = bytearray(corpus.file_path("full").read_bytes())
    at = crc.find(by_name[first_blob])
    crc[at] ^= 0xFF
    cases = [
        ("the file full, whole", corpus.file_path("full").read_bytes()),
        ("a blob whose bytes aren't its name", _zip([(n, b"other bytes" if n == first_blob else b) for n, b in full])),
        ("a blob damaged (its CRC)", bytes(crc)),
        ("a document that isn't what its state says", _zip([(n, other_doc if n == "units.jsonl" else b)
                                                            for n, b in full])),
        ("a kept file a song names that it lacks", _zip([(n, b) for n, b in full if n != first_blob])),
        ("a page it lists that it doesn't hold", _zip([(n, b) for n, b in full if not n.startswith("pages/")])),
    ]
    records = []
    for case, data in cases:
        path = corpus.workdir / "files" / "whole.caracole"
        path.write_bytes(data)
        try:
            peer_file.check_whole(peer_file.read_file(path))
            error = None
        except peer_file.FileError as e:
            error = str(e)
        records.append({"fn": "check_whole", "case": case, "bytes": base64.b64encode(data).decode("ascii"),
                        "out": {"error": error}})
    return records


def check_importable_records(corpus: FileCorpus) -> list[dict]:
    from caracole import peer_file
    from caracole import peer_sync as sync

    agreed = json.dumps({"format": sync.FORMAT, "units": {"song/x/y": ["1" * 64, "2026-11-02T08:00:00Z"]}})
    at_made = json.dumps({"format": sync.FORMAT, "units": {"song/x/y": ["1" * 64, MADE]}})
    kept_later = json.dumps({"format": sync.FORMAT, "units": {"song/x/y": ["1" * 64, T0]},
                             "kept": {"song/x/y": ["2" * 64, "3" * 64, "2026-11-04T09:00:00Z"]}})
    other_format = json.dumps({"format": 1, "units": {"song/x/y": ["1" * 64, "2026-11-05T08:00:00Z"]}})
    cases = [("this library's own export", EXPORTER, {}), ("never synced", IMPORTER, {}),
             ("synced before it was made", IMPORTER, {sync.BASE_KEY + EXPORTER: agreed}),
             ("synced as it was made", IMPORTER, {sync.BASE_KEY + EXPORTER: at_made}),
             ("a kept answer later than it", IMPORTER, {sync.BASE_KEY + EXPORTER: kept_later}),
             ("a base of another format is none", IMPORTER, {sync.BASE_KEY + EXPORTER: other_format})]
    records = []
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        old = other_schema(corpus)
        error = None
        try:
            lib = corpus.replayed("sync", "empty", tag="-importable-old-schema")
            peer_file.check_importable(peer_file.read_file(corpus.workdir / "files" / "old-schema.sqlite",
                                                           name="old.sqlite"), lib.conn, own=IMPORTER)
        except peer_file.FileError as e:
            error = str(e)
        records.append({"fn": "check_importable", "case": "an index export of another schema",
                        "bytes": base64.b64encode(old).decode("ascii"), "name": "old.sqlite", "own": IMPORTER,
                        "kv": {}, "out": {"error": error}})
        for case, own, kv in cases:
            lib = corpus.replayed("sync", "empty", tag=f"-importable-{case}")
            from caracole import db

            for key, value in kv.items():
                db.kv_set(lib.conn, key, value)
            try:
                peer_file.check_importable(peer_file.read_file(corpus.file_path("full")), lib.conn, own=own)
                error = None
            except peer_file.FileError as e:
                error = str(e)
            records.append({"fn": "check_importable", "case": case, "file": "files/full.caracole", "own": own,
                            "kv": kv, "out": {"error": error}})
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()
    return records


# --- an import --------------------------------------------------------------------------------------------------------


IMPORTS: list[tuple[str, dict[str, Any]]] = [
    ("a first import into an empty library takes everything",
     {"here": "empty", "id": FRESH, "file": "full"}),
    ("a conflict kept here is remembered, and the file's kept answer read with its sides swapped",
     {"here": "file_conflict", "id": IMPORTER, "file": "full", "choices": {CREEP: "here"}}),
    ("the same conflict taken from the file",
     {"here": "file_conflict", "id": IMPORTER, "file": "full", "choices": {CREEP: "there"}}),
    ("a conflict left unanswered is left, and nothing of it remembered",
     {"here": "file_conflict", "id": IMPORTER, "file": "full"}),
    ("a file of the songbooks alone brings the songs they list",
     {"here": "empty", "id": FRESH, "file": "songbooks"}),
    ("a file of the songbooks alone removes no song, and keeps the base of every unit it says nothing of",
     {"here": "plain", "id": FRESH, "file": "songbooks", "base": "plain"}),
    ("a song the file's library removed since the last sync is removed here",
     {"here": "plain", "id": FRESH, "file": "full", "base": "plain"}),
    ("the songbooks alone asked of a whole file", {"here": "empty", "id": FRESH, "file": "full",
                                                   "parts": ["songbooks"]}),
    ("a file of every part, its units", {"here": "empty", "id": FRESH, "file": "indexes"}),
    ("what the file would give, kept here as chosen, is remembered, and a conflict skipped is left unremembered",
     {"here": "file_conflict", "id": IMPORTER, "file": "full", "choices": {KARMA: "here", CREEP: "skip"}}),
    ("a conflict not chosen is settled as preferred: the file's",
     {"here": "file_conflict", "id": IMPORTER, "file": "full", "prefer": "there"}),
    ("a conflict not chosen is settled as preferred: this side's, and remembered",
     {"here": "file_conflict", "id": IMPORTER, "file": "full", "prefer": "here", "choices": {KARMA: "skip"}}),
    ("a song the file left out is left here, saying why", {"here": "empty", "id": FRESH, "file": "left"}),
    ("an index export holds no unit, and keeps no agreement",
     {"here": "plain", "id": FRESH, "file": "indexes", "member": "indexes.sqlite", "base": "plain"}),
]


def _as_chosen(found: list, choices: dict[str, str]) -> list:
    from dataclasses import replace

    sides = {"here": "mine", "there": "theirs"}
    return [d if choices.get(d.id) is None else replace(d, proposal=sides[choices[d.id]])
            for d in found if choices.get(d.id) != "skip"]


def import_records(corpus: FileCorpus) -> list[dict]:
    from caracole import db, peer_file
    from caracole import peer_sync as sync

    records = []
    for case, given in IMPORTS:
        here, choices, parts = given["here"], given.get("choices", {}), given.get("parts", list(PARTS))
        prefer, member = given.get("prefer"), given.get("member")
        lib = corpus.replayed("sync", here, tag=f"-import-{len(records)}")
        db.kv_set(lib.conn, sync.ID_KEY, given["id"])
        kv = {}
        if given.get("base"):  # this side agreed with the exporter, at T0, on what it holds now
            units = {u: [x.digest, T0] for u, x in sorted(lib.units().items())}
            kv = {sync.BASE_KEY + EXPORTER: json.dumps({"format": sync.FORMAT, "units": units})}
        for key, value in kv.items():
            db.kv_set(lib.conn, key, value)
        path = corpus.file_path(given["file"])
        if member is not None:
            path = corpus.workdir / "files" / f"{given['file']}-{member}"
            path.write_bytes(dict(_members(corpus.file_path(given["file"])))[member])
        f = peer_file.read_file(path, name=member)
        with peer_file.FileSource(f, lib.conn, lib.cfg.library_dir) as source:
            compared = peer_file.compare_file(lib.conn, lib.overrides(), lib.books(), f, source)
            scoped = peer_file.in_parts(compared, parts)
            take, keep = sync.decide(_as_chosen(scoped, choices), {"here": "mine", "there": "theirs"}.get(prefer))
            done = sync.apply_units(lib.conn, lib.cfg, source, [(d.id, d.theirs.digest if d.theirs else None)
                                                                for d in take], TAKEN,
                                    expected_here={d.id: d.mine.digest if d.mine else None for d in take})
            peer_file.record_import(lib.conn, f, lib.units(), peer_file.kept_answers(scoped, keep))
        records.append({
            "fn": "import", "case": case, "here": here, "id": given["id"], "kv": kv,
            "file": f"files/{given['file']}.caracole"} | ({"member": member} if member else {}) | {
            "parts": parts, "choices": choices, "prefer": prefer,
            "out": {"differences": [[d.id, d.proposal, d.why] for d in compared.found],
                    "scoped": [d.id for d in scoped], "taken": done.taken, "left": [list(x) for x in done.left],
                    "after": dict(sorted(lib.digests().items())),
                    "base_after": db.kv_get(lib.conn, sync.BASE_KEY + EXPORTER),
                    "kept_after": {u: list(v) for u, v in sorted(sync.kept_of(lib.conn, EXPORTER).items())}}})
    return records


MAKERS: dict[str, Callable[[FileCorpus], list[dict]]] = {
    "export": export_records, "file_name": file_name_records, "read": read_records, "unit": unit_records,
    "check_whole": check_whole_records, "check_importable": check_importable_records, "import": import_records,
}


def records(corpus: FileCorpus) -> list[dict]:
    return [record for maker in MAKERS.values() for record in maker(corpus)]


def every_file(workdir: Path) -> dict[Path, bytes]:
    """Every file this generator writes, by its path under tests/conformance/vectors, made in ``workdir``."""
    corpus = FileCorpus(workdir)
    try:
        made = {VECTOR: jsonl(records(corpus), corpus="sync/file", made_by=MADE_BY).encode("utf-8")}
        for name in FILES:
            made[SYNC / "files" / f"{name}.caracole"] = corpus.file_path(name).read_bytes()
        for name in HERE:
            made[SYNC / "fixtures" / f"{name}.jsonl"] = corpus.fixture_text("sync", name).encode("utf-8")
        return made
    finally:
        corpus.close()


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return every_file(tmp_path_factory.mktemp("sync-file-corpus"))


def test_file_jsonl_is_what_export_read_and_import_do(made):
    check(VECTOR, made[VECTOR])


@pytest.mark.parametrize("name", FILES)
def test_a_caracole_file_is_its_fixture_exported(made, name):
    check(SYNC / "files" / f"{name}.caracole", made[SYNC / "files" / f"{name}.caracole"])


@pytest.mark.parametrize("name", list(HERE))
def test_a_fixture_of_this_file_is_its_library_dumped(made, name):
    check(SYNC / "fixtures" / f"{name}.jsonl", made[SYNC / "fixtures" / f"{name}.jsonl"])


def _records(made) -> list[dict]:
    return [json.loads(line) for line in made[VECTOR].decode("utf-8").splitlines()[1:]]


def test_the_vectors_show_what_each_case_says(made):
    from caracole import db, peer_file
    from caracole import peer_sync as sync

    by = {(r["fn"], r["case"]): r for r in _records(made)}
    full = by["export", "full"]["out"]
    assert full["members"][:4] == ["caracole.json", "state.json", "bases.json", "units.jsonl"]
    assert full["members"][-1].startswith("pages/") and "pages.json" in full["members"]
    assert [e["path"] for e in full["pages"]["files"]] == ["index.html", "Radiohead/Creep/sheet.html",
                                                          "Radiohead/Creep/sheet.pdf", "Radiohead/Creep/sheet.txt"]
    sheet = full["pages"]["files"][-1]["sha256"]
    assert sheet in full["files"] and sheet not in full["page_blobs"] and len(full["page_blobs"]) == 3
    left = by["export", "left"]["out"]
    assert left["left"] == [[KARMA, peer_file.CHANGED]] and KARMA in left["state"]["units"]
    assert KARMA not in [u["id"] for u in left["units"]] and left["manifest"]["units"] == len(left["units"])
    assert sorted(full["bases"]) == [IMPORTER, THIRD]
    assert by["export", "indexes"]["out"]["members"][-1] == "indexes.sqlite"
    assert {r["out"]["holds"] == list(PARTS) for r in _records(made) if r["fn"] == "read"
            and r.get("file") == "files/indexes.caracole" and "member" not in r} == {True}
    reads = {r["case"]: r["out"] for r in _records(made) if r["fn"] == "read"}
    assert reads["an index export of another schema holds nothing"]["holds"] == []
    assert reads["a file made at another schema holds its units but not its indexes"]["holds"] == ["library",
                                                                                                  "songbooks"]
    units = {r["case"]: r["out"] for r in _records(made) if r["fn"] == "unit"}
    assert units["full: song/not/here"] == units["songbooks: songbook/not-here"] == {"unit": None}
    assert units["full: removed/not/here"] == {"unit": None} and units["left: " + CREEP]["unit"]
    assert units["left: " + KARMA]["error"].startswith("the file names it but doesn't hold it")
    assert units["songbooks: song/宋冬野/斑马斑马"]["error"] == units["songbooks: removed/oasis/wonderwall"][
        "error"] == "the file doesn't hold that part of its library, so it says nothing of it"
    errors = {r["case"]: r["out"].get("error") for r in _records(made) if r["fn"] == "read"}
    assert errors["something else"] == errors["a zip of something else"] == peer_file.NOT_A_FILE
    assert errors["another format"] == peer_file.OTHER_FORMAT.format(format=2)
    assert errors["more than 8 GiB in all"] == peer_file.UNREADABLE.format(why="it holds more than 8 GiB")
    assert all(errors[case].startswith("That file can't be read whole (") for case in (
        "a file cut short", "a member outside its layout", "a member twice", "a blob bigger than it may be",
        "more than 8 GiB in all", "a blob name that isn't a SHA-256", "a manifest that names no caracole"))
    whole = {r["case"]: r["out"]["error"] for r in _records(made) if r["fn"] == "check_whole"}
    assert whole.pop("the file full, whole") is None  # one of its pages held as a kept file, under files/
    assert all(e.startswith("That file can't be read whole (") for e in whole.values())
    importable = {r["case"]: r["out"]["error"] for r in _records(made) if r["fn"] == "check_importable"}
    assert importable == {
        "an index export of another schema": peer_file.OTHER_FORMAT.format(format=f"1, schema {db.SCHEMA_VERSION + 1}"),
        "this library's own export": peer_file.OWN_EXPORT, "never synced": None, "synced before it was made": None,
        "synced as it was made": peer_file.OLDER.format(name="Desk", day="03/11/26"),
        "a kept answer later than it": peer_file.OLDER.format(name="Desk", day="04/11/26"),
        "a base of another format is none": None}
    imports = {r["case"]: r["out"] for r in _records(made) if r["fn"] == "import"}
    kept, taken, unanswered = (imports[case] for case in (
        "a conflict kept here is remembered, and the file's kept answer read with its sides swapped",
        "the same conflict taken from the file", "a conflict left unanswered is left, and nothing of it remembered"))
    # the file keeps a base for this side (none of its units agreed): a sync after one, each side changed
    assert [d for d in kept["differences"]] == [[CREEP, "conflict", "both books changed it since the last share"],
                                                [KARMA, "theirs", sync.KEPT_THERE]]
    assert kept["taken"] == [KARMA] and list(kept["kept_after"]) == [CREEP]
    assert taken["taken"] == [CREEP, KARMA] and taken["kept_after"] == {}
    assert unanswered["taken"] == [KARMA] and unanswered["kept_after"] == {}
    songbooks = imports["a file of the songbooks alone removes no song, and keeps the base of every unit it says "
                        "nothing of"]
    assert songbooks["taken"] == [CREEP, KARMA, "songbook/campfire"]
    assert "song/soda-stereo/de-musica-ligera" in songbooks["after"]
    base = json.loads(songbooks["base_after"])["units"]
    assert base["song/soda-stereo/de-musica-ligera"][1] == base["removed/oasis/wonderwall"][1] == T0
    assert base["songbook/campfire"][1] == MADE
    removed = imports["a song the file's library removed since the last sync is removed here"]
    assert "song/soda-stereo/de-musica-ligera" in removed["taken"] and \
        "song/soda-stereo/de-musica-ligera" not in removed["after"]
    assert imports["the songbooks alone asked of a whole file"]["scoped"] == [CREEP, KARMA, "songbook/campfire"]
    chosen = imports["what the file would give, kept here as chosen, is remembered, and a conflict skipped is left "
                     "unremembered"]
    assert chosen["taken"] == [] and list(chosen["kept_after"]) == [KARMA]
    assert imports["a conflict not chosen is settled as preferred: the file's"]["taken"] == [CREEP, KARMA]
    preferred_here = imports["a conflict not chosen is settled as preferred: this side's, and remembered"]
    assert preferred_here["taken"] == [] and list(preferred_here["kept_after"]) == [CREEP]
    left_out = imports.pop("a song the file left out is left here, saying why")
    assert [unit for unit, _ in left_out["left"]] == [KARMA] and KARMA not in left_out["after"]
    assert left_out["left"][0][1].startswith("the file names it but doesn't hold it")
    index_only = imports["an index export holds no unit, and keeps no agreement"]
    assert index_only["differences"] == [] and json.loads(index_only["base_after"]) == json.loads(
        by["import", "an index export holds no unit, and keeps no agreement"]["kv"][sync.BASE_KEY + EXPORTER])
    for case, out in imports.items():
        assert out["left"] == [], case


@pytest.mark.slow  # the files made twice, in two processes
def test_the_vectors_are_the_same_whatever_the_hash_seed(tmp_path):
    from conftest import subprocess_pythonpath

    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(f"{SRC}{os.pathsep}{TESTS}"),
           "CARACOLE_YTDLP_BIN": str(tmp_path / "no-yt-dlp"), "CARACOLE_SERVICE_FILE": str(tmp_path / "no-service")}
    script = ("import sys, hashlib, test_conformance_sync_file as m; from pathlib import Path\n"
              "for p, b in sorted(m.every_file(Path(sys.argv[1])).items()): print(p.name, hashlib.sha256(b).hexdigest())")
    running = {seed: subprocess.Popen([sys.executable, "-c", script, str(tmp_path / f"work-{seed}")],
                                      env={**env, "PYTHONHASHSEED": seed}, cwd=TESTS, stdout=subprocess.PIPE,
                                      text=True) for seed in ("1", "2")}
    out = {seed: process.communicate(timeout=300)[0] for seed, process in running.items()}
    assert all(p.returncode == 0 for p in running.values())
    assert out["1"] == out["2"] and out["1"]
