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
import zlib
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


# --- a file read back ----------------------------------------------------------------------------------------------

_JSON_MEMBERS = (MANIFEST, STATE, BASES, UNITS, PAGES)
_NAMED = (*_JSON_MEMBERS, INDEXES)
_ID = re.compile(r"[0-9a-f]{16}")


def _unreadable(why: str) -> FileError:
    return FileError(UNREADABLE.format(why=why))


@dataclass(frozen=True)
class SyncFile:
    """A file read back (``read_file``): its path, its manifest, its state (None for an index export), the bases it
    keeps (``{peer id: {"units", "kept"}}``), the parts it holds, and whether it is an index export alone. It holds
    no open file."""

    path: Path
    manifest: dict[str, Any]
    state: sync.PeerState | None
    bases: dict[str, dict]
    holds: tuple[str, ...]
    index_only: bool

    @property
    def id(self) -> str | None:
        """The id of the caracole that made it (kv ``sync:id``); None for an index export."""
        found = self.manifest.get("id")
        return found if isinstance(found, str) and _ID.fullmatch(found) else None

    @property
    def name(self) -> str:
        """The name of the library it is of; an index export's own file name."""
        found = self.manifest.get("name")
        return found if isinstance(found, str) else ""

    @property
    def made(self) -> str | None:
        """When it was made, a stamp."""
        found = self.manifest.get("made")
        return found if isinstance(found, str) else None

    def base_for(self, peer: str | None) -> tuple[sync.Base | None, sync.Kept]:
        """What the file's caracole last agreed on with ``peer`` (None: never) and the answers it kept for it, as
        ``peer_sync.base_of`` and ``kept_of`` read them there; here the file's, there ``peer``'s."""
        entry = self.bases.get(peer) if peer is not None else None
        if not isinstance(entry, Mapping):
            return None, {}
        return sync._read_units(entry.get("units")), sync._read_kept(entry.get("kept"))


def read_file(path: Path, *, name: str | None = None) -> SyncFile:
    """The file at ``path`` read back (see the module's docstring): its central directory and its manifest, state
    and bases, each checked; FileError, in the owner's words, for a file that isn't one, of another format, or that
    can't be read whole. ``name``: an index export's own name, when ``path`` isn't it (an upload staged)."""
    try:
        with open(path, "rb") as f:
            head = f.read(len(_SQLITE))
    except OSError:
        raise FileError(NOT_A_FILE) from None
    if head.startswith(_SQLITE):
        return _index_file(path, name or Path(path).name)
    if not head.startswith(_ZIP):
        raise FileError(NOT_A_FILE)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, EOFError, ValueError):
        raise _unreadable("it is cut short, or no whole zip") from None
    with z:
        infos = z.infolist()
        if not infos or infos[0].filename != MANIFEST:
            raise FileError(NOT_A_FILE)
        manifest = _json_member(z, infos[0])
        if not isinstance(manifest, dict):
            raise _unreadable("its manifest is no object")
        if manifest.get("format") != FORMAT:
            raise FileError(OTHER_FORMAT.format(format=manifest.get("format")))
        if manifest.get("sync") != sync.FORMAT:
            raise FileError(OTHER_FORMAT.format(format=f"{FORMAT}, its sync's {manifest.get('sync')}"))
        _check_layout(infos)
        _check_manifest(manifest)
        names = {info.filename: info for info in infos}
        for needed in (STATE, UNITS):
            if needed not in names:
                raise _unreadable(f"it has no {needed}")
        try:
            state = sync.read_state_document(_json_member(z, names[STATE]))
        except sync.StateError as e:
            raise _unreadable(f"its state: {e}") from None
        if state.server != manifest["id"]:
            raise _unreadable("its state is another caracole's than its manifest names")
        bases = _json_member(z, names[BASES]) if BASES in names else {}
        if not isinstance(bases, dict):
            raise _unreadable("its bases are no object")
    asked = set(manifest["parts"])
    holds = tuple(p for p in sync.PARTS if p in asked and (
        p != "indexes" or (INDEXES in names and manifest.get("schema") == _schema())))
    return SyncFile(Path(path), manifest, state, bases, holds, False)


def _check_layout(infos: Sequence[zipfile.ZipInfo]) -> None:
    """Every member a name of the layout, once, of a size it may be, stored or deflated, nothing encrypted, the
    whole within ``IMPORT_MAX``."""
    seen: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        blob = name.startswith((FILES, PAGE_BLOBS)) and _SHA256.fullmatch(name.partition("/")[2]) is not None
        if name not in _NAMED and not blob:
            raise _unreadable(f"a member outside its layout, {name[:80]!r}")
        if name in seen:
            raise _unreadable(f"{name[:80]} twice")
        seen.add(name)
        if info.flag_bits & 0x1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise _unreadable(f"{name[:80]} is encrypted, or compressed as caracole doesn't")
        most = FILE_MAX if blob else JSON_MAX if name in _JSON_MEMBERS else IMPORT_MAX
        if info.file_size > most:
            raise _unreadable(f"{name[:80]} is bigger than it may be")
        total += info.file_size
    if total > IMPORT_MAX:
        raise _unreadable("it holds more than 8 GiB")


def _check_manifest(manifest: Mapping[str, Any]) -> None:
    """A manifest's fields as an import reads them: its caracole's id, when it was made, and its parts."""
    if not (isinstance(manifest.get("id"), str) and _ID.fullmatch(manifest["id"])):
        raise _unreadable("its manifest names no caracole")
    if not isinstance(manifest.get("made"), str) or stamps.parse(manifest["made"]) is None:
        raise _unreadable("its manifest says no time it was made")
    parts = manifest.get("parts")
    if not (isinstance(parts, list) and all(isinstance(p, str) for p in parts)):
        raise _unreadable("its manifest names no parts")
    if not isinstance(manifest.get("name"), str):
        raise _unreadable("its manifest names no library")


def _json_member(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> Any:
    if info.file_size > JSON_MAX:
        raise _unreadable(f"{info.filename} is bigger than it may be")
    try:
        with z.open(info) as f:
            data = f.read(JSON_MAX + 1)
    except (zipfile.BadZipFile, EOFError, OSError, ValueError, RuntimeError, zlib.error) as e:
        raise _unreadable(f"{info.filename}: {e}") from None
    if len(data) > JSON_MAX:
        raise _unreadable(f"{info.filename} is bigger than it may be")
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        raise _unreadable(f"{info.filename} is no JSON") from None


def _index_file(path: Path, name: str) -> SyncFile:
    """An index export (``caracole index export``'s), as a file of the indexes alone."""
    from caracole import index_transfer

    try:
        file = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            meta = dict(file.execute(f"SELECT key, value FROM {index_transfer.META}").fetchall())
        finally:
            file.close()
    except sqlite3.OperationalError:
        raise FileError(NOT_A_FILE) from None
    except sqlite3.Error as e:
        raise _unreadable(str(e)) from None
    if meta.get("format") != str(index_transfer.FORMAT):
        raise FileError(OTHER_FORMAT.format(format=meta.get("format")))
    try:
        sites = [s for s in json.loads(meta.get("sites", "[]")) if isinstance(s, str)]
    except ValueError:
        sites = []
    schema = int(meta["schema"]) if str(meta.get("schema", "")).isdigit() else meta.get("schema")
    manifest = {"format": FORMAT, "caracole": meta.get("caracole"), "schema": schema, "name": name,
                "made": meta.get("exported_at"), "parts": ["indexes"], "indexes": sites}
    holds = ("indexes",) if schema == _schema() else ()
    return SyncFile(Path(path), manifest, None, {}, holds, True)


# --- refused, and read whole -----------------------------------------------------------------------------------------


def check_importable(file: SyncFile, conn: sqlite3.Connection, *, own: str | None) -> None:
    """FileError, in the owner's words, for a file this library takes nothing from: its own export (``own``, this
    caracole's id), one no newer than this side's last sync with its caracole (its ``made`` no later than the
    latest time this side's base for it records, a kept answer's included), and an index export of another
    schema."""
    if file.index_only:
        if not file.holds:
            raise FileError(OTHER_FORMAT.format(format=f"{FORMAT}, schema {file.manifest.get('schema')}"))
        return
    if own is not None and file.id == own:
        raise FileError(OWN_EXPORT)
    if file.id is None:
        return
    whens = [when for _, when in (sync.base_of(conn, file.id) or {}).values()]
    whens += [when for _, _, when in sync.kept_of(conn, file.id).values()]
    times = [t for t in map(stamps.parse, whens) if t is not None]
    made = stamps.parse(file.made)
    if times and made is not None and made <= max(times):
        day = max(times).astimezone().strftime("%d/%m/%y")
        raise FileError(OLDER.format(name=file.name or "its caracole", day=day))


def check_whole(file: SyncFile) -> None:
    """Every member of ``file`` read through (its CRC and its size as the zip declares them), each blob what its
    name says, each unit document what the state says of it, and each kept file a song names held; FileError
    (``UNREADABLE``) else. An index export: SQLite's ``quick_check``."""
    if file.index_only:
        _check_sqlite(file.path)
        return
    assert file.state is not None
    try:
        with zipfile.ZipFile(file.path) as z:
            names = set(z.namelist())
            for info in z.infolist():
                digest = hashlib.sha256()
                with z.open(info) as f:
                    while chunk := f.read(CHUNK):
                        digest.update(chunk)
                blob = info.filename.partition("/")[2]
                if info.filename.startswith((FILES, PAGE_BLOBS)) and digest.hexdigest() != blob:
                    raise _unreadable(f"{info.filename} isn't the file its name says")
            named = _documents(z, file.state)
    except (zipfile.BadZipFile, EOFError, OSError, ValueError, RuntimeError, zlib.error) as e:
        if isinstance(e, FileError):
            raise
        raise _unreadable(str(e)) from None
    for unit_id, doc in named.items():
        if unit_id.partition("/")[0] != "song":
            continue
        for version in doc["unit"]["versions"]:
            for f in version["files"]:
                if f"{FILES}{f['sha256']}" not in names:
                    raise _unreadable(f"{unit_id} keeps a file it doesn't hold")


def _check_sqlite(path: Path) -> None:
    try:
        file = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            (answer,) = file.execute("PRAGMA quick_check").fetchone()
        finally:
            file.close()
    except sqlite3.Error as e:
        raise _unreadable(str(e)) from None
    if answer != "ok":
        raise _unreadable(str(answer))


def _documents(z: zipfile.ZipFile, state: sync.PeerState) -> dict[str, dict[str, Any]]:
    """``units.jsonl``'s documents by unit id, each of a unit the state names, once, with the digest the state gives
    it, its value read from it alone (``peer_sync.value_of_document``) of that digest; FileError else."""
    found: dict[str, dict[str, Any]] = {}
    info = z.getinfo(UNITS)
    if info.file_size > JSON_MAX:
        raise _unreadable(f"{UNITS} is bigger than it may be")
    with z.open(info) as f:
        data = f.read(JSON_MAX + 1)
    for number, line in enumerate(data.splitlines(), 1):
        try:
            doc = json.loads(line)
        except (ValueError, RecursionError):
            raise _unreadable(f"{UNITS}'s line {number} is no JSON") from None
        unit_id = doc.get("id") if isinstance(doc, dict) else None
        if not (isinstance(unit_id, str) and unit_id in state.units and unit_id not in found
                and doc.get("format") == sync.FORMAT and isinstance(doc.get("unit"), dict)):
            raise _unreadable(f"{UNITS}'s line {number} is no document of a unit its state names")
        try:
            digest = sync.digest_of(sync.value_of_document(unit_id, doc["unit"]))
        except (sync.UnitError, ValueError) as e:
            raise _unreadable(f"{unit_id[:80]}: {e}") from None
        if digest != state.units[unit_id].digest or doc.get("digest") != digest:
            raise _unreadable(f"{unit_id[:80]} isn't what its state says")
        found[unit_id] = doc
    return found


# --- taken from ------------------------------------------------------------------------------------------------------


class FileSource:
    """A file's units as ``peer_sync.apply_units`` takes them, as it takes a peer's (its ``UnitSource``, as
    ``peer_sync.Peer`` and ``peer_push.StagedSource`` are): each unit's document from ``units.jsonl``, each kept file
    from ``files/``, else a copy kept here (``peer_push.kept_copy``), checked by its SHA-256; and its indexes and
    pages. Holds the file open until closed."""

    def __init__(self, file: SyncFile, conn: sqlite3.Connection | None, library_dir: Path):
        self.sync_file = file  # ``file`` is the UnitSource's method
        self._conn = conn
        self._library_dir = library_dir
        self._zip: zipfile.ZipFile | None = None
        self._documents: dict[str, dict[str, Any]] | None = None

    def __enter__(self) -> FileSource:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def _opened(self) -> zipfile.ZipFile:
        if self._zip is None:
            try:
                self._zip = zipfile.ZipFile(self.sync_file.path)
            except (zipfile.BadZipFile, OSError) as e:
                raise sync.PeerError(UNREADABLE.format(why=str(e))) from None
        return self._zip

    def _read(self, name: str, most: int) -> bytes:
        try:
            info = self._opened().getinfo(name)
            if info.file_size > most:
                raise sync.PeerError(UNREADABLE.format(why=f"{name} is bigger than it may be"))
            with self._opened().open(info) as f:
                data = f.read(most + 1)
        except KeyError:
            raise
        except (zipfile.BadZipFile, EOFError, OSError, ValueError, RuntimeError, zlib.error) as e:
            raise sync.PeerError(UNREADABLE.format(why=f"{name}: {e}")) from None
        if len(data) > most:
            raise sync.PeerError(UNREADABLE.format(why=f"{name} is bigger than it may be"))
        return data

    def documents(self) -> dict[str, dict[str, Any]]:
        """The unit documents it holds, by unit id (``units.jsonl``'s, checked as ``check_whole`` checks them)."""
        if self.sync_file.index_only:
            return {}
        if self._documents is None:
            assert self.sync_file.state is not None
            try:
                self._documents = _documents(self._opened(), self.sync_file.state)
            except FileError as e:
                raise sync.PeerError(str(e)) from None
            except (zipfile.BadZipFile, EOFError, OSError, ValueError, RuntimeError, zlib.error) as e:
                raise sync.PeerError(UNREADABLE.format(why=str(e))) from None
        return self._documents

    def unit(self, unit_id: str) -> dict[str, Any] | None:
        """The unit's document, as ``GET /api/peer/unit``'s ``"unit"``; None for a unit of a part the file holds
        that its state doesn't name (its caracole hasn't got it: a song it removed); PeerError for a unit its state
        names that it holds no document of (left out as it was exported) and for one of a part it doesn't hold,
        which a take must leave as it is, never take as gone."""
        doc = self.documents().get(unit_id)
        if doc is not None:
            return dict(doc["unit"])
        state = self.sync_file.state
        if state is not None and unit_id in state.units:
            raise sync.PeerError("the file names it but doesn't hold it: it was left out as it was exported (a file "
                                 "it keeps had changed there)")
        if sync.part_of(unit_id) in self.sync_file.holds and "/" in unit_id:
            return None
        raise sync.PeerError("the file doesn't hold that part of its library, so it says nothing of it")

    def file(self, key: str, name: str, sha256: str) -> bytes:
        """A kept file of the song of ``key``, by its SHA-256: from the file, or kept here; PeerError else."""
        from caracole import peer_push

        data: bytes | None
        if not _SHA256.fullmatch(sha256):
            raise sync.PeerError(f"{name}: no SHA-256 to find it by")
        try:
            data = self._read(FILES + sha256, FILE_MAX)
        except KeyError:
            data = peer_push.kept_copy(self._conn, self._library_dir, sha256)
        if data is None or hashlib.sha256(data).hexdigest() != sha256:
            raise sync.PeerError(f"{name} isn't in the file as its song says, nor kept here: the song is left as it "
                                 "was here.")
        return data

    def indexes(self, to: Path) -> bool:
        """Its indexes copied to ``to`` (a new file), in chunks; False, nothing written, when it holds none this
        database can merge (``SyncFile.holds``)."""
        if "indexes" not in self.sync_file.holds:
            return False
        if self.sync_file.index_only:
            source: Any = open(self.sync_file.path, "rb")
        else:
            try:
                source = self._opened().open(INDEXES)
            except KeyError:
                return False
        fd = os.open(to, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with source, open(fd, "wb") as out:
                while chunk := source.read(CHUNK):
                    out.write(chunk)
        except (zipfile.BadZipFile, EOFError, ValueError, RuntimeError, zlib.error) as e:
            Path(to).unlink(missing_ok=True)
            raise sync.PeerError(UNREADABLE.format(why=f"{INDEXES}: {e}")) from None
        except BaseException:
            Path(to).unlink(missing_ok=True)
            raise
        return True

    def pages(self) -> dict[str, Any] | None:
        """Its ``pages.json``, the pages its caracole made of its units; None when it holds none."""
        if self.sync_file.index_only:
            return None
        try:
            data = self._read(PAGES, JSON_MAX)
        except KeyError:
            return None
        try:
            found = json.loads(data)
        except (ValueError, RecursionError):
            raise sync.PeerError(UNREADABLE.format(why=f"{PAGES} is no JSON")) from None
        return found if isinstance(found, dict) else None

    def page(self, sha256: str) -> bytes:
        """A page's bytes, by its SHA-256; PeerError when the file holds none of it."""
        if not _SHA256.fullmatch(sha256):
            raise sync.PeerError("no SHA-256 to find that page by")
        try:
            data = self._read(PAGE_BLOBS + sha256, FILE_MAX)
        except KeyError:
            raise sync.PeerError("the file holds no such page") from None
        if hashlib.sha256(data).hexdigest() != sha256:
            raise sync.PeerError(UNREADABLE.format(why=f"{PAGE_BLOBS}{sha256} isn't the page its name says"))
        return data


# --- an import: the comparison, and what the two agree on after ------------------------------------------------------


@dataclass(frozen=True)
class Compared:
    """This library compared with a file (``compare_file``): the differences within the parts the file holds, in
    ``peer_sync._order``; this side's units; the base and the kept answers they were compared against; the songs
    the two sides' songbooks list (``peer_sync.listed_songs``); whether the two synced before."""

    found: list[sync.Difference]
    mine: dict[str, sync.Unit]
    base: dict[str, str | None] | None
    kept: dict[str, sync.KeptPair]
    listed: dict[str, list[str]]

    @property
    def synced_before(self) -> bool:
        return self.base is not None


def compare_file(conn: sqlite3.Connection, overrides, books: Sequence, file: SyncFile, source: FileSource
                 ) -> Compared:
    """This library (``overrides``, ``books``: songbook.py's) and ``file`` compared, as a sync compares two sides:
    against this side's base for the file's caracole merged with the one the file keeps for this side, with the
    answers both remembered, within the parts the file holds (see the module's docstring). PeerError when the file's
    documents can't be read. An index export: no difference."""
    from caracole.songbook import name_key

    mine = sync.library_state(conn, overrides, books)
    if file.index_only or file.state is None:
        return Compared([], mine, None, {}, {})
    own = sync.own_id(conn)
    here_base = sync.base_of(conn, file.id) if file.id else None
    file_base, file_kept = file.base_for(own)
    base = sync.merged_base(here_base, file_base)
    kept = sync.merged_kept(here_base, sync.kept_of(conn, file.id) if file.id else {}, file_base, file_kept)
    found = sync.compare(mine, file.state.units, base, kept)
    units = set(mine) | set(file.state.units)
    listed: dict[str, set[str]] = {}
    here_books = {f"songbook/{name_key(b.name)}": sync.songbook_value(b) for b in books}
    file_books = {u: doc["unit"] for u, doc in source.documents().items() if u.startswith("songbook/")}
    for books_of in (here_books, file_books):
        for song, by in sync.listed_songs(books_of, units).items():
            listed.setdefault(song, set()).update(by)
    listed_songs = {song: sorted(by) for song, by in sorted(listed.items())}
    holds = file.holds
    return Compared(sync.in_scope(found, holds, listed=listed_songs, holds=holds), mine, base, kept, listed_songs)


def in_parts(compared: Compared, parts: Iterable[str]) -> list[sync.Difference]:
    """The differences of ``compared`` an import of ``parts`` is about (``peer_sync.in_scope``)."""
    return sync.in_scope(compared.found, parts, listed=compared.listed)


def speaks_for(file: SyncFile, unit_id: str) -> bool:
    """Whether ``file`` says what its caracole holds of the unit: one of a part it holds, or one it carries (a song
    its songbooks list). Of any other unit it says nothing, and an import keeps no agreement of it."""
    return (file.state is not None and unit_id in file.state.units) or sync.part_of(unit_id) in file.holds


def record_import(conn: sqlite3.Connection, file: SyncFile, mine: Mapping[str, sync.Unit],
                  kept_here: Mapping[str, tuple[str | None, str | None]]) -> int:
    """After an import of ``file``, keep, as agreed with its caracole at its ``made``, each unit the file speaks for
    (``speaks_for``) that this library (``mine``, its whole state now) and the file hold the same, or both lack;
    then remember each answer "keep mine" (``kept_here``: a unit's digest here and the file's, as compared) beside
    the base (``peer_sync.record_kept``). The base and the kept answer of every unit the file says nothing of stay as
    they were. Return how many units were agreed; an index export records nothing."""
    from caracole.db import savepoint

    if file.index_only or file.state is None or file.id is None or file.made is None:
        return 0
    peer, made = file.id, file.made
    with savepoint(conn, "peer_import_agreement"):
        before_base, before_kept = sync.base_of(conn, peer) or {}, sync.kept_of(conn, peer)
        agreed = sync.record_agreement(conn, peer, {u: x for u, x in mine.items() if speaks_for(file, u)},
                                       {u: x for u, x in file.state.units.items() if speaks_for(file, u)}, made)
        base, kept = sync.base_of(conn, peer) or {}, sync.kept_of(conn, peer)
        for unit_id in set(base) | set(before_base):
            if not speaks_for(file, unit_id):
                if unit_id in before_base:
                    base[unit_id] = before_base[unit_id]
                else:
                    base.pop(unit_id, None)
        for unit_id in set(kept) | set(before_kept):
            if not speaks_for(file, unit_id):
                if unit_id in before_kept:
                    kept[unit_id] = before_kept[unit_id]
                else:
                    kept.pop(unit_id, None)
        sync._write_base(conn, peer, base, kept)
        sync.record_kept(conn, peer, kept_here, made)
    return agreed
