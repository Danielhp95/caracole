"""caracole serve's Export and Import a file (the library page's sync, library_assets/sync.js): this library written
to a ``.caracole`` file and sent to the browser to keep or to share, and a file another caracole exported sent here
in parts, staged for ``caracole peer import`` (peer_file.py, peer_import.py; the plan:
docs/superpowers/plans/2026-11-03-sync-redesign.md §3.4.2).

    GET  /api/sync/sizes      what an export of this library would hold: the library's name, its songs and songbooks,
                              when (``made``: now), the bytes of its library (its kept files, and the library page and
                              the files it links to), of its site indexes (``peer_file.indexes_size``; null where
                              SQLite has no dbstat) and the tabs they track
    POST /sync/export         This library's parts (JSON ``{"parts": [...]}``: the library or the songbooks, or both,
                              and the indexes or not) written to a new file of ``cache_dir/peer/``, one at a time:
                              ``{"export", "name", "size"}``, its id, the name it downloads under
                              (``peer_file.file_name``: the library's and the day's) and its size
    GET  /api/sync/export?export=   that file, an attachment by that name, streamed, and deleted once it is open: 404
                              after, and for one made more than an hour before
    POST /sync/import/open    A file to import opened (JSON ``{"size", "name"}``): its id and how big a part may be,
                              ``{"import", "part"}`` (``peer_import.open_import``: 413 past 8 GiB, 409 with one open
                              already)
    POST /sync/import/part?import=&at=   a part of that file, its bytes (8 MiB at most), written where what it has
                              ends: ``{"have"}``, how much it has then; 400 for a part that isn't the next one or
                              would pass its size
    POST /sync/import/compare this library and that file compared (form: ``import``), as ``POST /sync/compare``
                              answers a comparison with another caracole, kept for its Sync (``POST /sync/apply``,
                              which queues ``caracole peer import`` of its folder): the other side the file
                              (``peer.kind`` ``"file"``, its ``made``), ``holds`` the parts it holds; or the file
                              refused, in the owner's words (400 ``NOT_A_FILE``, ``OTHER_FORMAT``, ``UNREADABLE``;
                              409 ``OWN_EXPORT``, ``OLDER``), and deleted
    POST /sync/import/drop    that file deleted now (JSON ``{"import"}``: the page's Cancel, an upload that failed):
                              ``{"dropped"}``; 409 while an import takes it or its request waits

An export is a read, as ``GET /api/peer/index`` is: made in this process, taking no lock, its units from one read
transaction of the library and its indexes from one of their own (``peer_file.export_file``), its pages as ``GET
/api/offline`` sends them (``offline_routes.library_pages``), into ``cache_dir/peer/`` (0700; the file 0600), never
into the library. One is made at a time (503 while another is: each may be hundreds of MB), and one waits to be sent
at most: once an export is made, the one before it, never asked for, is deleted. Each is sent once: its file is
deleted as it is opened to be sent, and one never asked for is deleted an hour after (as the next export is made, or
its sizes asked), as is a part a process killed while it made one left (as the next export is made). Under
``/api/``, another site's page reads neither the sizes nor the file (``security.own_page_read``); a HEAD, which would
spend the file's one GET, is refused (405).

A file to import is the browser's (a phone's export, another server's; or a ``caracole peer sync`` giving its
indexes, peer_import.py ``Uploader``): sent in parts, since it holds a library's files and pages and maybe its
indexes, each a write with the form token in its header, into its staging folder (``state_dir/peer/import-<id>/``,
peer_import.py), one at a time; deleted once its import is over, or an hour after its last part unless an import holds
it, or sooner: dropped (the page's Cancel), or let go as another is opened when no request names it and it is whole
(compared, never synced) or its upload stopped (``peer_import.let_go``). Its comparison reads it whole first
(``peer_file.check_whole``), and a file refused is deleted; a unit's two documents on its comparison (``GET
/api/sync/unit``, a conflict's card) are this library's and the file's, read from it (``file_unit``). Nothing of it
reaches the library but through ``caracole peer import``, a queued command under caracole's lock, which reads it
whole again before it takes anything.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import threading
import time
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from caracole import peer_import
from caracole.web.app import MAX_BODY, Response, Route, WebApp, json_response
from caracole.web.pages import Refused
from caracole.web.peer_routes import _library, _params

FOLDER = "peer"  # cache_dir's folder an export is made in, as GET /api/peer/index's copies are
PREFIX = "export-"  # then its id and peer_file.SUFFIX
EXPIRES = 3600.0  # seconds an export never asked for (or a part a killed process left) is kept
SMALL = MAX_BODY  # a JSON body here: parts named, or a file's size and name
NOT_ALONE = ("An export holds the library or the songbooks, or both: the site indexes alone are caracole index "
             "export's.")
NO_PARTS = 'Which parts? {"parts": ["library", "songbooks", "indexes"]}, the library or the songbooks among them.'
BUSY = "Another export is being made: try again once it is."
GONE = ("No such export here: it was sent once already, or made more than an hour ago, or another made since, or "
        "caracole serve has restarted since. Export again.")
WAITS = "That file waits to be imported: cancel its request in the Requests tab first."
NOT_NAMED = 'Which file? {"import": "<its id>"}, as POST /sync/import/open named it.'
FILE_GONE = peer_import.GONE
_ID = re.compile(r"[0-9a-f]{16}")
_AT = re.compile(r"[0-9]{1,15}")

ROUTES = (
    Route("GET", "/api/sync/sizes", lambda app, asked: sizes(app)),
    Route("POST", "/sync/export", lambda app, asked, doc: export(app, doc), body="json", limit=SMALL),
    Route("GET", "/api/sync/export", lambda app, asked: download(app, asked, _params(asked.target))),
    Route("POST", "/sync/import/open", lambda app, asked, doc: import_open(app, doc), body="json", limit=SMALL),
    Route("POST", "/sync/import/part", lambda app, asked, data: import_part(app, _params(asked.target), data),
          body="bytes", limit=peer_import.PART_MAX),
    Route("POST", "/sync/import/compare", lambda app, asked, form: import_compare(app, form)),
    Route("POST", "/sync/import/drop", lambda app, asked, doc: import_drop(app, doc), body="json", limit=SMALL),
)

_making = threading.Lock()  # one export made at a time, of every server in this process
# Each server's exports made and not sent yet, by their ids: the file and the name it downloads under.
_made: weakref.WeakKeyDictionary[WebApp, dict[str, tuple[Path, str]]] = weakref.WeakKeyDictionary()
_made_lock = threading.Lock()


def _now() -> datetime:
    """The routes' clock: when an export is made, as its file says. Tests replace it."""
    return datetime.now(UTC)


# --- what an export would hold ------------------------------------------------------------------------------------


def sizes(app: WebApp) -> Response:
    """``GET /api/sync/sizes``: ``{name, songs, songbooks, made, library, indexes, tabs}`` (see the module's
    docstring), read here alone; or why the library can't be read, as JSON (503)."""
    from caracole import index_transfer, peer_file, stamps

    try:
        _, books = _library(app)
        with app.db() as conn:
            songs = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            library = _library_bytes(app, conn)
            indexes = peer_file.indexes_size(conn)
            tabs = sum(index_transfer.tab_counts(conn).values())
    except Refused as e:
        return json_response(e.status, {"error": e.message})
    _sweep(app)
    return json_response(200, {"name": app.cfg.library_name, "songs": songs, "songbooks": len(books),
                               "made": stamps.stamp(_now()), "library": library, "indexes": indexes, "tabs": tabs})


def _library_bytes(app: WebApp, conn) -> int:
    """About what an export's library takes: the bytes of each song's kept files and of the library page caracole
    wrote with every file it links to (the sheets' pages and PDFs, as ``GET /api/offline`` lists them), each file
    once, as its size on disk. A file gone, or no regular file, counts nothing."""
    from caracole.library_page import PAGE_NAME, linked_files
    from caracole.web.offline_routes import start_page

    paths = {path for (path,) in conn.execute("SELECT path FROM files")}
    start = start_page(app)
    if start.status == 200:
        paths |= {PAGE_NAME, *linked_files(start.body)}
    total = 0
    for path in paths:
        parts = PurePosixPath(path).parts
        if not parts or parts[0] == "/" or ".." in parts or "\\" in path:
            continue
        try:
            entry = os.lstat(app.cfg.library_dir.joinpath(*parts))
        except (OSError, ValueError):
            continue
        if stat.S_ISREG(entry.st_mode):
            total += entry.st_size
    return total


# --- the export ---------------------------------------------------------------------------------------------------


def export(app: WebApp, doc: Any) -> Response:
    """``POST /sync/export``: the parts ``doc`` names written to a new file of ``cache_dir/peer/``, kept for its one
    GET; 400 for parts that aren't the library or the songbooks (with the indexes or not), 503 while another export is
    made or for one that can't be made."""
    from caracole import __version__, peer_file
    from caracole.web.offline_routes import library_pages

    named = doc.get("parts") if isinstance(doc, dict) else None
    if not (isinstance(named, list) and named and all(isinstance(p, str) for p in named)):
        raise Refused(400, "Not exported", NO_PARTS)
    try:
        parts = peer_file.checked_parts(named)
    except peer_file.FileError:
        raise Refused(400, "Not exported", NO_PARTS) from None
    if not {"library", "songbooks"} & set(parts):
        raise Refused(400, "Not exported", NOT_ALONE)
    if not _making.acquire(blocking=False):
        raise Refused(503, "Not exported", BUSY)
    try:
        overrides, books = _library(app)
        folder = _folder(app)
        made_id = secrets.token_hex(8)
        path = folder / f"{PREFIX}{made_id}{peer_file.SUFFIX}"
        now = _now()
        pages = library_pages(app.cfg) if "library" in parts else None
        with app.db() as conn:
            made = peer_file.export_file(conn, app.cfg, overrides, books, path, parts, now=now,
                                         version=__version__, name=app.cfg.library_name, pages=pages)
        os.chmod(path, 0o600)
    except peer_file.FileError as e:
        raise Refused(503, "Not exported", f"The file couldn't be made: {e}.") from e
    except OSError as e:
        raise Refused(503, "Not exported", f"The file couldn't be made: {e}.") from e
    finally:
        _making.release()
    name = peer_file.file_name(app.cfg.library_name, now.astimezone())
    with _made_lock:
        kept = _made.setdefault(app, {})
        for earlier, (old, _) in list(kept.items()):  # never asked for: this one takes its place
            old.unlink(missing_ok=True)
            del kept[earlier]
        kept[made_id] = (path, name)
    return json_response(200, {"export": made_id, "name": name, "size": made.size})


def _folder(app: WebApp) -> Path:
    """``cache_dir/peer/``, made 0700, with what an hour has left there deleted first (``_sweep``, the parts a killed
    process left too: called while no export is made, under ``_making``)."""
    folder = app.cfg.cache_dir / FOLDER
    app.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    folder.mkdir(mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    _sweep(app, leftovers=True)
    return folder


def _sweep(app: WebApp, *, leftovers: bool = False) -> None:
    """Delete each export of ``cache_dir/peer/`` made more than ``EXPIRES`` ago, never sent, and, with
    ``leftovers`` (while no export is made: its parts' times stop moving as it reads them back), each part a
    process killed while it made one left (``.export-…``); and forget the exports whose files are gone."""
    from caracole import peer_file

    folder = app.cfg.cache_dir / FOLDER
    try:
        entries = list(os.scandir(folder))
    except OSError:
        entries = []
    now = time.time()
    for entry in entries:
        made = entry.name.startswith(PREFIX) and entry.name.endswith(peer_file.SUFFIX)
        left = leftovers and entry.name.startswith("." + PREFIX)
        try:
            if (made or left) and entry.is_file(follow_symlinks=False) and (
                    now - entry.stat(follow_symlinks=False).st_mtime > EXPIRES):
                os.unlink(entry.path)
        except OSError:
            continue
    with _made_lock:
        kept = _made.get(app, {})
        for made_id in [i for i, (path, _) in kept.items() if not os.path.lexists(path)]:
            del kept[made_id]


def download(app: WebApp, asked, params: dict[str, str]) -> Response:
    """``GET /api/sync/export``: the export ``export`` names, streamed (``Response.stream``), its file deleted as it
    is opened, so it is sent once; 404 for one sent, swept or never made; 405 for a HEAD."""
    from caracole import peer_file
    from caracole.download_names import content_disposition

    if asked.method == "HEAD":
        return Response(405, b"", [("Allow", "GET")])
    _sweep(app)
    made_id = params.get("export", "")
    with _made_lock:
        found = _made.get(app, {}).pop(made_id, None) if _ID.fullmatch(made_id) else None
    if found is None:
        return json_response(404, {"error": GONE})
    path, name = found
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return json_response(404, {"error": GONE})
    stream = open(fd, "rb")  # server.py closes it once it is sent
    path.unlink(missing_ok=True)
    return Response(200, headers=[("Content-Type", peer_file.MEDIA_TYPE),
                                  ("Content-Disposition", content_disposition(name))], stream=stream)


# --- a file to import, sent in parts ------------------------------------------------------------------------------


def _staging_refused(e: peer_import.StagingError) -> Refused:
    return Refused(e.status, "Not taken", str(e))


def import_open(app: WebApp, doc: Any) -> Response:
    """``POST /sync/import/open``: a file of ``size`` bytes named ``name`` opened for its parts
    (``peer_import.open_import``, which first deletes imports an hour has left), once the imports no request names
    that are whole or stopped are let go (``peer_import.let_go``)."""
    given = doc if isinstance(doc, dict) else {}
    try:
        peer_import.let_go(app.cfg.state_dir, _named(app))
        import_id = peer_import.open_import(app.cfg.state_dir, size=given.get("size"), name=given.get("name"))
    except peer_import.StagingError as e:
        raise _staging_refused(e) from None
    except OSError as e:
        raise Refused(503, "Not kept", f"The file couldn't be kept: {e}.") from e
    return json_response(200, {"import": import_id, "part": peer_import.PART_MAX})


def import_part(app: WebApp, params: dict[str, str], data: bytes) -> Response:
    """``POST /sync/import/part``: a part of the import ``import`` names, written at ``at``
    (``peer_import.add_part``)."""
    at = params.get("at", "")
    if not _AT.fullmatch(at):
        raise Refused(400, "Not taken", "Where does that part go? at is the number of bytes sent before it.")
    try:
        have = peer_import.add_part(app.cfg.state_dir, params.get("import", ""), int(at), data)
    except peer_import.StagingError as e:
        raise _staging_refused(e) from None
    except OSError as e:
        raise Refused(503, "Not kept", f"That part couldn't be kept: {e}.") from e
    return json_response(200, {"have": have})


def _named(app: WebApp) -> set[str]:
    """The imports a waiting or running request names (``sync_routes.IMPORTING``, then the staged file's id)."""
    from caracole.web.sync_routes import IMPORTING

    return {job.song_key[len(IMPORTING):] for job in app.queue.snapshot()
            if job.active and job.song_key.startswith(IMPORTING)}


def import_drop(app: WebApp, doc: Any) -> Response:
    """``POST /sync/import/drop``: the import ``import`` names deleted now (``peer_import.drop``); 409 while its
    request waits or an import takes it, 404 for none."""
    import_id = doc.get("import") if isinstance(doc, dict) else None
    if not isinstance(import_id, str):
        raise Refused(400, "Not dropped", NOT_NAMED)
    if import_id in _named(app):
        raise Refused(409, "Not dropped", WAITS)
    try:
        peer_import.drop(app.cfg.state_dir, import_id)
    except peer_import.StagingError as e:
        raise Refused(e.status, "Not dropped", str(e)) from None
    return json_response(200, {"dropped": import_id})


# --- an import's comparison ---------------------------------------------------------------------------------------


class _FileRefused(Exception):
    """The staged file refused, in the owner's words, with the status the route answers: it is deleted."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class _FileFound:
    """A staged file compared with this library (``_compare_staged``): the file, its folder, the comparison
    (``peer_file.Compared``), when the two last agreed, each songbook difference's two documents, and the indexes
    newer in the file."""

    file: Any
    folder: Path
    compared: Any
    synced: str | None
    songbooks: dict[str, tuple[Any, Any]]
    indexes: list[dict[str, Any]]


def _refusal_of(e: Exception) -> _FileRefused:
    """How a file refused is answered: 409 for one this library takes nothing from (its own export, one no newer
    than the last sync with its caracole), 400 for one that isn't a file, of another format, or can't be read."""
    from caracole import peer_file

    said = str(e)
    if said == peer_file.OWN_EXPORT or said.startswith(peer_file.OLDER.partition("{")[0]):
        return _FileRefused(409, said)
    return _FileRefused(400, said)


def _compare_staged(app: WebApp, import_id: str, *, documents: bool) -> _FileFound:
    """The file staged as ``import_id`` read and compared with this library, as ``caracole peer import`` compares
    it (``peer_file.read_file``, ``check_importable``, ``compare_file``), sending no request; with ``documents``,
    read whole first (``check_whole``) and each songbook difference's two documents and the indexes newer in it
    read too. A file refused is deleted, and Refused with its words; Refused (404, 409) for one gone or taken now,
    or (400) not whole yet."""
    try:
        folder = peer_import.folder_of(app.cfg.state_dir, import_id)
        with peer_import.held(folder, wait=False):
            path = peer_import.whole(app.cfg.state_dir, import_id)
            try:
                return _compared_file(app, folder, path, documents=documents)
            except _FileRefused:
                peer_import.remove(folder)
                raise
    except peer_import.StagingError as e:
        raise Refused(e.status, "Not compared", FILE_GONE if e.status == 404 else str(e)) from None
    except _FileRefused as e:
        raise Refused(e.status, "Not taken", str(e)) from None


def _compared_file(app: WebApp, folder: Path, path: Path, *, documents: bool) -> _FileFound:
    from caracole import index_transfer, peer_file
    from caracole import peer_sync as sync
    from caracole.web.sync_routes import _waiting

    try:
        file = peer_file.read_file(path, name=peer_import.opened_name(folder))
    except peer_file.FileError as e:
        raise _refusal_of(e) from None
    overrides, books = _library(app)  # this library's fault, not the file's: the file is kept
    with app.db() as conn, peer_file.FileSource(file, conn, app.cfg.library_dir) as source:
        own = sync.own_id(conn)
        try:
            peer_file.check_importable(file, conn, own=own)
            if documents:
                peer_file.check_whole(file)
            compared = peer_file.compare_file(conn, overrides, books, file, source)
        except (peer_file.FileError, sync.PeerError) as e:
            raise _refusal_of(e) from None
        here_base = sync.base_of(conn, file.id) if file.id else None
        file_base, _ = file.base_for(own)
        agreed = [at for b in (here_base, file_base) if b for _, at in b.values()]
        songbooks: dict[str, tuple[Any, Any]] = {}
        indexes: list[dict[str, Any]] = []
        if documents:
            for d in compared.found:
                if d.id.startswith("songbook/"):
                    here = sync.unit_document(conn, app.cfg, overrides, books, d.id) if d.mine else None
                    try:
                        there = source.unit(d.id) if d.theirs else None
                    except sync.PeerError as e:
                        raise _refusal_of(e) from None
                    songbooks[d.id] = (here["unit"] if here else None, there)
            if "indexes" in file.holds:
                indexes = [w for w in _waiting(index_transfer.newest(conn), _newest_in(file))
                           if w["newer"] == "there"]
    return _FileFound(file, folder, compared, max(agreed) if agreed else None, songbooks, indexes)


def _newest_in(file) -> dict[str, str]:
    """Each site's newest read in a file's indexes: a ``.caracole`` file's state says it (``peer_sync.state_document``'s
    ``indexes``); an index export's is read from it (``index_transfer.newest``), none for one of some sites alone,
    whose other sites' tables it hasn't got (``caracole index export --sites``, a sync's indexes given)."""
    import sqlite3

    from caracole import peer_file

    if file.state is not None:
        return dict(file.state.indexes)
    try:
        return peer_file._newest_of(file.path)
    except sqlite3.Error:
        return {}


def import_compare(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /sync/import/compare``: this library and the file staged as ``import`` compared, as ``POST
    /sync/compare`` answers (``sync_routes.comparison_answer``), the comparison kept for its Sync under the source
    ``import:<id>``: ``peer`` ``{address: null, server: the file's caracole's id, caracole, name, kind: "file",
    made}``, ``holds`` the parts the file holds, its differences those of these parts alone
    (``peer_file.compare_file``: a part it lacks is never a removal), whose hash its Sync checks again, and
    ``indexes`` the sites the file read more recently than this library (a file takes nothing back). The file
    refused: its words (400, 409), and it is deleted."""
    from caracole import peer_sync as sync
    from caracole.web.sync_routes import IMPORTING, Compared, _keep, comparison_answer

    import_id = form.get("import", "").strip()
    found = _compare_staged(app, import_id, documents=True)
    file, differences = found.file, found.compared.found
    kept = Compared(str(found.folder), file.name, sync.compared_hash(differences),
                    {d.id: d.proposal for d in differences}, time.monotonic(), source=IMPORTING + import_id,
                    holds=file.holds, listed=found.compared.listed, kind="file", found=tuple(differences))
    comparison = _keep(app, kept)
    peer = {"address": None, "server": file.id, "caracole": file.manifest.get("caracole"), "name": file.name,
            "kind": "file", "made": file.made}
    return json_response(200, comparison_answer(comparison, peer, found.synced, file.holds, differences,
                                                found.compared.base, found.compared.kept, found.compared.listed,
                                                found.songbooks, found.indexes))


def file_unit(app: WebApp, import_id: str, unit_id: str) -> dict[str, Any] | None:
    """A unit's document as the file staged as ``import_id`` holds it, for ``GET /api/sync/unit`` on its comparison
    (``peer_file.FileSource.unit``), read with no request, as the phone's ``SyncEngine.documents`` reads a file's:
    None for a unit it hasn't got, and for one it names but left out as it was exported, or of a part it doesn't
    hold (nothing of it to show). Refused 409 for a file gone or being imported now, or that can no longer be read."""
    from caracole import peer_file
    from caracole import peer_sync as sync

    try:
        folder = peer_import.folder_of(app.cfg.state_dir, import_id)
        with peer_import.held(folder, wait=False):
            path = peer_import.whole(app.cfg.state_dir, import_id)
            file = peer_file.read_file(path, name=peer_import.opened_name(folder))
            with peer_file.FileSource(file, None, app.cfg.library_dir) as source:
                try:
                    return source.unit(unit_id)
                except sync.PeerError:
                    return None
    except peer_import.StagingError as e:
        raise Refused(409, "Compare again", FILE_GONE if e.status == 404 else str(e)) from None
    except (peer_file.FileError, sync.PeerError) as e:
        raise Refused(409, "Compare again", str(e)) from None


def compared_again(app: WebApp, import_id: str) -> str:
    """The hash of the staged file's comparison with this library now (``peer_sync.compared_hash``), for its Sync
    to check against the one shown: read again, never whole, sending no request. Refused (409 ``FILE_GONE``) for a
    file gone, and as its comparison refuses it."""
    from caracole import peer_sync as sync

    try:
        found = _compare_staged(app, import_id, documents=False)
    except Refused as e:
        if e.status == 404:
            raise Refused(409, "Compare again", FILE_GONE) from None
        raise
    return sync.compared_hash(found.compared.found)
