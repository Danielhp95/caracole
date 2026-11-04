"""A library in a file, the ``.caracole`` file: written by ``caracole peer export`` (and the Sync tab's Export), read
back by ``caracole peer import``, which syncs this library with it as if the caracole that wrote it were here (the
design: docs/superpowers/specs/2026-11-03-sync-redesign-design.md; the plan's §3.3).

**What it is.** A recording of what a sync reads from the other side (peer_sync.py): a zip of its manifest, its
state document, the bases it keeps, each unit's document, the kept files those documents name, the pages caracole
made of them, and its site indexes. Its members, in this order:

- ``caracole.json``, the manifest: ``{"format": 1, "caracole", "schema", "sync", "id", "name", "made", "parts",
  "songs", "songbooks", "units", "files", "pages", "indexes"}``: the file's own format (``FORMAT``), the caracole and
  schema that wrote it, the sync's format (``peer_sync.FORMAT``), the library's id (kv ``sync:id``) and name, when it
  was made (a stamp), its parts (``peer_sync.PARTS``, in that order), how many songs, songbooks, unit documents, kept
  files and pages it holds, and the sites of its indexes;
- ``state.json``: ``peer_sync.state_document`` of the file's units, as of ``made``, with the newest read of its
  indexes when it holds them and no kept answer (``{}``);
- ``bases.json``: ``{"<peer id>": {"units", "kept"}}``, every base this library keeps (kv ``sync:base:*`` of
  ``peer_sync.FORMAT``), so that the caracole that imports it reads what the two agreed on, as a peer's state gives
  it;
- ``units.jsonl``: a line a unit, ``peer_sync.unit_document``'s answer, in ``peer_sync._order``;
- ``files/<sha256>``: each kept file the song documents name, once;
- ``pages.json``: the ``GET /api/offline`` manifest (web/offline_routes.py) cut to the file's units and its start
  page, ``pages/<sha256>`` each page's bytes once: the phone builds no page of its own yet, so a song taken from a
  file opens with the sheet its library made. None without the library;
- ``indexes.sqlite``: ``index_transfer.export`` of every site, with the indexes.

Its JSON members are deflated, written as ``json.dumps`` with sorted keys writes them (so each float stays a float),
the others stored; every member is dated ``made``. Its units are a library's (``Library``: every song, tombstone and
entry about an artist or a tab) and its songbooks with the songs they list (``Songbooks``: ``peer_sync.listed_songs``).
A song a kept file of which can no longer be read as recorded (``peer_sync.song_file`` reads none) is left out, its
pages with it, and said (``Made.left``); its state still names it, so that a file never reads as having lost it. It
is read in one read transaction, taking no lock, and written under a name of its own beside the file, then renamed.

**Reading it** (``read_file``): its manifest first (a zip whose first member isn't ``caracole.json`` is no file of
caracole's, ``NOT_A_FILE``; another ``format``, or another sync's, ``OTHER_FORMAT``), then its central directory,
every name in the layout above (``files/`` and ``pages/`` names 64 lowercase hex, nothing else, each once), each blob
at most ``FILE_MAX``, each JSON member at most ``JSON_MAX``, the whole at most ``IMPORT_MAX``, nothing encrypted
(``UNREADABLE``); then its state and its bases. The parts it holds (``SyncFile.holds``) are its manifest's, the
indexes only when its schema is this database's. A file of ``caracole index export`` (an SQLite file holding
``index_transfer.META``) is a file of the indexes alone, with no id, named by its own name. Blobs are read when asked
for, each checked by its SHA-256; ``check_whole`` reads every member through before an import takes anything (a CRC
error, a member cut short, a blob that isn't its name, a unit document that isn't what its state says, a file a song
names that the file lacks: ``UNREADABLE``), so a file that can't be read whole is refused whole.

**Importing it** is a sync with the file (commands/peer.py's ``peer import``): ``check_importable`` refuses a
library's own export (``OWN_EXPORT``) and a file no newer than this side's last sync with its caracole (``OLDER``:
its ``made`` no later than the latest time of this side's base for its id, its kept answers included);
``compare_file`` compares this library with the file's state, against the base merged with the one the file keeps
for this side (``bases.json``) and the answers both remembered (``peer_sync.merged_kept``), within the parts the file
holds (``peer_sync.in_scope``, so a part it lacks is never read as removed); ``FileSource`` is the take's
``peer_sync.UnitSource``, so a unit is taken from a file exactly as from a peer (a unit of a part the file holds that
its state lacks the file's caracole hasn't got; a unit it names but holds no document of, or of a part it doesn't
hold, a ``PeerError``, never a removal); and ``record_import`` keeps what the two now agree on, stamped ``made``,
with each conflict answered "keep mine" remembered (``peer_sync.record_kept``): the file can't take this side's
version back. The agreement is of the units the file speaks for, those of the parts it holds and those it carries:
the base of every other unit stays as it was.

The refusals are said in the same words on the phone (``core.sync.file.FileError``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from caracole import peer_sync as sync
from caracole import stamps

FORMAT = 1  # the file's own layout: changes only with it
SUFFIX = ".caracole"
MEDIA_TYPE = "application/vnd.caracole+zip"
MANIFEST = "caracole.json"
STATE = "state.json"
BASES = "bases.json"
UNITS = "units.jsonl"
PAGES = "pages.json"
FILES = "files/"  # then a kept file's SHA-256
PAGE_BLOBS = "pages/"  # then a page's SHA-256
INDEXES = "indexes.sqlite"
FILE_MAX = 64 * 1024 * 1024  # a kept file's or a page's bytes, at most (a push's file's)
JSON_MAX = 64 * 1024 * 1024  # a JSON member's, at most
IMPORT_MAX = 8 * 1024 ** 3  # a file's members together, at most
CHUNK = 1024 * 1024  # what a blob is copied by, never whole in memory
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SQLITE = b"SQLite format 3\x00"
_ZIP = b"PK\x03\x04"

NOT_A_FILE = "That isn't a file caracole exported: a .caracole file, or an index from caracole index export."
OTHER_FORMAT = "That file was made by another version of caracole (format {format}): export it again with this one."
OWN_EXPORT = ("That file is this library's own export: a library takes nothing from itself. caracole backup keeps "
              "copies of the computer's database to go back to.")
OLDER = "Nothing in this file is newer than your sync with {name} on {day}."
UNREADABLE = "That file can't be read whole ({why}): export it again."


class FileError(ValueError):
    """A file refused, or one that can't be written: what to tell the owner."""


@dataclass(frozen=True)
class Made:
    """An export written: its path, its parts, the songs and songbooks it holds, its size, and the songs left out
    (their unit ids: a kept file that can no longer be read as recorded)."""

    path: Path
    parts: tuple[str, ...]
    songs: int
    songbooks: int
    size: int
    left: tuple[str, ...]


# The pages a file holds: the exporter's GET /api/offline manifest, and a listed file's bytes by its path, as a GET of
# its url answers them (offline_routes.library_pages).
Pages = tuple[Mapping[str, Any], Callable[[str], bytes]]


def file_name(library_name: str | None, when: datetime) -> str:
    """The name an export of the library ``library_name`` made at ``when`` goes by: its name cleaned as a download's
    is (download_names.py: what a system refuses ``_``, cut to ``MAX_BYTES`` of UTF-8, no dot or space at either
    end), ``caracole`` for none, then the day, ``-dd-mm-yy``, and ``.caracole``."""
    from caracole.download_names import MAX_BYTES, _clean, _cut

    stem = _clean(library_name or "").strip(" .")
    stem = _cut(stem, MAX_BYTES).strip(" .") or "caracole"
    return f"{stem}-{when.strftime('%d-%m-%y')}{SUFFIX}"


def checked_parts(parts: Iterable[str]) -> tuple[str, ...]:
    """The parts named, each once, in ``peer_sync.PARTS``' order; FileError for one that isn't a part."""
    named = list(parts)
    unknown = [p for p in named if p not in sync.PARTS]
    if unknown:
        raise FileError(f"{unknown[0]!r} isn't a part: parts are library, songbooks or indexes")
    return tuple(p for p in sync.PARTS if p in named)


# --- a library written to a file -----------------------------------------------------------------------------------


@dataclass
class _Snapshot:
    """What an export reads of the database, in one read transaction."""

    own: str
    state: dict[str, sync.Unit]  # the file's units, its songs left out included
    documents: list[dict[str, Any]]  # the unit documents it holds, in order
    files: dict[str, tuple[str, int]]  # each kept file, by its SHA-256: its path in the library, its size
    bases: dict[str, Any]
    indexes: dict[str, str]
    left: tuple[str, ...]


def export_file(conn: sqlite3.Connection, cfg, overrides, books: Sequence, path: Path, parts: Sequence[str], *,
                now: datetime, version: str, name: str, pages: Pages | None = None) -> Made:
    """This library's ``parts`` written to a new file at ``path`` (see the module's docstring), made ``now``, by
    caracole ``version``, the library called ``name``; ``pages`` (``offline_routes.library_pages``), the pages it
    holds with the library. FileError for parts that aren't the library or the songbooks (with the indexes or not),
    for a file there already, or one that can't be written."""
    from caracole import index_transfer

    parts = checked_parts(parts)
    if not ({"library", "songbooks"} & set(parts)):
        raise FileError("an export holds the library or the songbooks, or both: the indexes alone are caracole index "
                        "export's")
    if os.path.lexists(path):
        raise FileError(f"{path} already exists: name a new file, or remove that one first")
    if not path.parent.is_dir():
        raise FileError(f"{path.parent} is no folder: name a file in one")
    made = stamps.stamp(now)
    part = path.with_name(f".{path.name}.{secrets.token_hex(6)}.part")
    indexes = path.with_name(f".{path.name}.{secrets.token_hex(6)}.indexes") if "indexes" in parts else None
    try:
        sites: tuple[str, ...] = ()
        if indexes is not None:
            try:
                sites = index_transfer.export(conn, indexes, now=now).sites
            except index_transfer.TransferError as e:
                raise FileError(f"its indexes can't be exported: {e}") from e
        snapshot = _snapshot(conn, cfg, overrides, books, parts)
        held = {d["id"] for d in snapshot.documents}
        listed = _pages_held(pages, snapshot.state, held) if pages is not None and "library" in parts else None
        manifest = {
            "format": FORMAT, "caracole": version, "schema": _schema(), "sync": sync.FORMAT, "id": snapshot.own,
            "name": name, "made": made, "parts": list(parts),
            "songs": sum(1 for d in snapshot.documents if d["id"].startswith("song/")),
            "songbooks": sum(1 for d in snapshot.documents if d["id"].startswith("songbook/")),
            "units": len(snapshot.documents), "files": len(snapshot.files),
            "pages": 0 if listed is None else len(listed[0]["files"]), "indexes": list(sites)}
        state = sync.state_document(snapshot.own, version, name, snapshot.state, None, now=made,
                                    indexes=snapshot.indexes if indexes is not None else {}, kept={})
        _write(part, made, cfg.library_dir, manifest, state, snapshot, listed, indexes)
        os.replace(part, path)
    except OSError as e:
        raise FileError(f"can't write {path}: {e}") from e
    finally:
        part.unlink(missing_ok=True)
        if indexes is not None:
            indexes.unlink(missing_ok=True)
    return Made(path, parts, manifest["songs"], manifest["songbooks"], path.stat().st_size, snapshot.left)


def _schema() -> int:
    from caracole import db

    return db.SCHEMA_VERSION


def _snapshot(conn: sqlite3.Connection, cfg, overrides, books: Sequence, parts: tuple[str, ...]) -> _Snapshot:
    """The file's units, their documents and kept files, the bases and the indexes' newest reads, in one read
    transaction (no lock: a writer goes on beside it)."""
    from caracole import index_transfer
    from caracole.songbook import name_key

    conn.execute("BEGIN")
    try:
        own = sync.own_id(conn)
        if own is None:
            raise FileError("this library has no id to sync by (kv sync:id): caracole peer new-id gives it one")
        every = sync.library_state(conn, overrides, books)
        chosen = {u for u in every if sync.part_of(u) in parts}
        if "songbooks" in parts:
            values = {f"songbook/{name_key(b.name)}": sync.songbook_value(b) for b in books}
            chosen |= set(sync.listed_songs(values, every))
        state = {u: every[u] for u in chosen}
        documents, files, left = [], {}, []
        for unit in sorted(state.values(), key=sync._order):
            doc = sync.unit_document(conn, cfg, overrides, books, unit.id)
            if doc is None or doc["digest"] != unit.digest:  # the library is read in one transaction: never
                raise FileError(f"{unit.id} changed while it was read: export again")
            kept = _kept_files(conn, cfg.library_dir, unit.id, doc) if unit.kind == "song" else {}
            if kept is None:
                left.append(unit.id)
                continue
            documents.append(json.loads(json.dumps(doc, ensure_ascii=False)))
            files.update(kept)
        bases = {}
        for (key,) in conn.execute("SELECT key FROM kv WHERE substr(key, 1, ?) = ? ORDER BY key",
                                   (len(sync.BASE_KEY), sync.BASE_KEY)).fetchall():
            peer = key[len(sync.BASE_KEY):]
            base = sync.base_of(conn, peer)
            if base is None:
                continue
            bases[peer] = {"units": {u: list(v) for u, v in sorted(base.items())},
                           "kept": {u: list(v) for u, v in sorted(sync.kept_of(conn, peer).items())}}
        indexes = index_transfer.newest(conn) if "indexes" in parts else {}
    finally:
        conn.execute("COMMIT")
    return _Snapshot(own, state, documents, files, bases, indexes, tuple(left))


def _kept_files(conn: sqlite3.Connection, library_dir: Path, unit_id: str,
                doc: Mapping[str, Any]) -> dict[str, tuple[str, int]] | None:
    """The song's kept files, each by its SHA-256 (its path, its size), once each is read through and is what was
    recorded; None when one isn't (changed or gone since, or no regular file)."""
    key = unit_id.partition("/")[2]
    found: dict[str, tuple[str, int]] = {}
    for version in doc["unit"]["versions"]:
        for f in version["files"]:
            row = conn.execute("SELECT files.path FROM files JOIN songs ON songs.id = files.song_id "
                               "WHERE songs.key = ? AND files.name = ?", (key, f["name"])).fetchone()
            if row is None:
                return None
            size = _hashed_size(library_dir / row[0], f["sha256"])
            if size is None:
                return None
            found.setdefault(f["sha256"], (row[0], size))
    return found


def _hashed_size(path: Path, sha256: str) -> int | None:
    """The size of the regular file at ``path`` (no link followed) when its bytes have that SHA-256, read through in
    chunks; None else."""
    from caracole.library import open_regular

    digest, size = hashlib.sha256(), 0
    try:
        with open(open_regular(path), "rb") as f:
            while chunk := f.read(CHUNK):
                digest.update(chunk)
                size += len(chunk)
    except (OSError, ValueError):
        return None
    return size if digest.hexdigest() == sha256 and size <= FILE_MAX else None


def _pages_held(pages: Pages, state: Mapping[str, sync.Unit], held: set[str]) -> Pages:
    """The pages a file holds: its start page and each page of a unit it holds as the manifest saw it (its digest
    the state's), each whose bytes are still what the manifest says; the manifest cut to them."""
    manifest, fetch = pages
    start = manifest.get("start")
    kept = []
    for entry in manifest.get("files") or ():
        unit = entry.get("unit")
        if unit is None:
            if entry.get("path") != start:
                continue
        elif unit not in held or entry.get("digest") != state[unit].digest:
            continue
        try:
            data = fetch(entry["path"])
        except (OSError, KeyError, ValueError):
            continue
        if hashlib.sha256(data).hexdigest() == entry.get("sha256") and len(data) <= FILE_MAX:
            kept.append(dict(entry))
    return {**manifest, "files": kept}, fetch


def _text(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _date(made: str) -> tuple[int, int, int, int, int, int]:
    when = stamps.parse(made)
    assert when is not None
    return when.timetuple()[:6]


def _write(part: Path, made: str, library_dir: Path, manifest: Mapping[str, Any], state: Mapping[str, Any],
           snapshot: _Snapshot, pages: Pages | None, indexes: Path | None) -> None:
    """The file written to ``part``, its members in the layout's order, then synced to the disk."""
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666)
    with open(fd, "wb") as raw:
        with zipfile.ZipFile(raw, "w") as z:
            out = _Out(z, _date(made))
            out.json(MANIFEST, manifest)
            out.json(STATE, state)
            out.json(BASES, snapshot.bases)
            out.text(UNITS, b"".join(_text(d) + b"\n" for d in snapshot.documents))
            for sha256, (path, size) in sorted(snapshot.files.items()):
                out.copy(FILES + sha256, library_dir / path, size, sha256)
            if pages is not None:
                listed, fetch = pages
                out.json(PAGES, listed)
                written = set()
                for entry in listed["files"]:
                    if entry["sha256"] not in written:
                        out.blob(PAGE_BLOBS + entry["sha256"], fetch(entry["path"]), entry["sha256"], entry["path"])
                        written.add(entry["sha256"])
            if indexes is not None:
                out.copy(INDEXES, indexes, indexes.stat().st_size, None)
        raw.flush()
        os.fsync(raw.fileno())


class _Out:
    """A file's members as they are written: each dated ``date``, JSON deflated, blobs stored and copied in chunks."""

    def __init__(self, z: zipfile.ZipFile, date: tuple[int, int, int, int, int, int]):
        self.z, self.date = z, date

    def _info(self, name: str, deflated: bool, size: int | None = None) -> zipfile.ZipInfo:
        member = zipfile.ZipInfo(name, date_time=self.date)
        member.compress_type = zipfile.ZIP_DEFLATED if deflated else zipfile.ZIP_STORED
        member.external_attr = 0o644 << 16
        if size is not None:
            member.file_size = size  # known first, so a member past 4 GiB is written as zip64
        return member

    def json(self, name: str, value: Any) -> None:
        self.text(name, _text(value))

    def text(self, name: str, data: bytes) -> None:
        self.z.writestr(self._info(name, True), data)

    def blob(self, name: str, data: bytes, sha256: str, shown: str) -> None:
        if hashlib.sha256(data).hexdigest() != sha256:
            raise FileError(f"{shown} changed while the file was made: export again")
        self.z.writestr(self._info(name, False), data)

    def copy(self, name: str, path: Path, size: int, sha256: str | None) -> None:
        """The file at ``path`` (a regular file, no link followed) as the member ``name``, checked against
        ``sha256`` when given."""
        from caracole.library import open_regular

        digest = hashlib.sha256()
        with open(open_regular(path), "rb") as f, self.z.open(self._info(name, False, size), "w") as out:
            while chunk := f.read(CHUNK):
                digest.update(chunk)
                out.write(chunk)
        if sha256 is not None and digest.hexdigest() != sha256:
            raise FileError(f"{name} changed while the file was made: export again")
