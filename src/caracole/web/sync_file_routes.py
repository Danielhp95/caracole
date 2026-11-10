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

An export is a read, as ``GET /api/peer/index`` is: made in this process from one read transaction of the library
(``peer_file.export_file``, which takes no lock), its pages as ``GET /api/offline`` sends them
(``offline_routes.library_pages``), into ``cache_dir/peer/`` (0700; the file 0600), never into the library. One is
made at a time (503 while another is: each may be hundreds of MB), and each is sent once: its file is deleted as it
is opened to be sent, and one never asked for, or a part a process killed while it made one left, is deleted an hour
after (as the next export is made, or its sizes asked). Under ``/api/``, another site's page reads neither the sizes
nor the file (``security.own_page_read``); a HEAD, which would spend the file's one GET, is refused (405).

A file to import is the browser's (a phone's export, another server's): sent in parts, since it holds a library's
files and pages and maybe its indexes, each a write with the form token in its header, into its staging folder
(``state_dir/peer/import-<id>/``, peer_import.py), one at a time, deleted an hour after its last part unless an import
holds it. Nothing of it reaches the library but through ``caracole peer import``, a queued command under caracole's
lock, which reads it whole before it takes anything.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import threading
import time
import weakref
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
GONE = ("No such export here: it was sent once already, or made more than an hour ago, or caracole serve has "
        "restarted since. Export again.")
_ID = re.compile(r"[0-9a-f]{16}")
_AT = re.compile(r"[0-9]{1,15}")

ROUTES = (
    Route("GET", "/api/sync/sizes", lambda app, asked: sizes(app)),
    Route("POST", "/sync/export", lambda app, asked, doc: export(app, doc), body="json", limit=SMALL),
    Route("GET", "/api/sync/export", lambda app, asked: download(app, asked, _params(asked.target))),
    Route("POST", "/sync/import/open", lambda app, asked, doc: import_open(app, doc), body="json", limit=SMALL),
    Route("POST", "/sync/import/part", lambda app, asked, data: import_part(app, _params(asked.target), data),
          body="bytes", limit=peer_import.PART_MAX),
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
    from caracole import peer_file, stamps

    try:
        _, books = _library(app)
        with app.db() as conn:
            songs = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            library = _library_bytes(app, conn)
            indexes = peer_file.indexes_size(conn)
            tabs = sum(_tab_counts(conn).values())
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


def _tab_counts(conn) -> dict[str, int]:
    """The tabs each site's index tracks, the rows of its first table (waiting on sync-routes'
    ``index_transfer.tab_counts``, the same count)."""
    from caracole import index_transfer

    return {name: conn.execute(f"SELECT COUNT(*) FROM main.{site.tables[0]}").fetchone()[0]
            for name, site in index_transfer.SITES.items()}


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
        _made.setdefault(app, {})[made_id] = (path, name)
    return json_response(200, {"export": made_id, "name": name, "size": made.size})


def _folder(app: WebApp) -> Path:
    """``cache_dir/peer/``, made 0700, with what an hour has left there deleted first (``_sweep``)."""
    folder = app.cfg.cache_dir / FOLDER
    app.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    folder.mkdir(mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    _sweep(app)
    return folder


def _sweep(app: WebApp) -> None:
    """Delete each export of ``cache_dir/peer/`` made more than ``EXPIRES`` ago, never sent, and each part a process
    killed while it made one left (``.export-…``), and forget the exports whose files are gone."""
    from caracole import peer_file

    folder = app.cfg.cache_dir / FOLDER
    try:
        entries = list(os.scandir(folder))
    except OSError:
        entries = []
    now = time.time()
    for entry in entries:
        made = entry.name.startswith(PREFIX) and entry.name.endswith(peer_file.SUFFIX)
        left = entry.name.startswith("." + PREFIX)
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
    (``peer_import.open_import``, which first deletes imports an hour has left)."""
    given = doc if isinstance(doc, dict) else {}
    try:
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
