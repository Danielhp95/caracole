"""caracole serve's side of a sync between two caracoles (peer_sync.py): what this library holds, unit by unit, each
unit whole, its kept files, a pull of another caracole's units queued, another caracole's push staged (peer_push.py),
and this library's site indexes.

    GET  /api/peer/state?peer=   this caracole's id, its version, its library's name, each unit of its library (a song,
                                 a removal, a songbook, an artist's alias or UG page, a blocked tab) with its label and
                                 its digest, and what it last agreed on with the caracole ``peer`` names (its id)
                                 and the answers "keep mine" its imports of that one's files remembered (``kept``):
                                 ``peer_sync.state_document``; its settings, which a phone takes
                                 (``politeness.settings_document``); and the form token, for a pull's form
    GET  /api/peer/unit?id=      a unit whole, as another caracole takes it: ``peer_sync.unit_document`` (404: no such
                                 unit here)
    GET  /api/peer/file?song=&name=   a song's kept file (``files``), while it is what caracole recorded (404 else)
    POST /peer/pull              Take these units from the caracole at ``from``: ``caracole peer pull FROM --unit=…``
                                 queued (``units``, one id a line), then to its line in the Requests tab
    POST /peer/push/new          A push opened (JSON ``{"format", "from", "files"}``): its id and the files of
                                 ``files`` this side needs sent, ``{"push", "need"}`` (``peer_push.new_push``)
    POST /peer/push/file?push=&sha256=   A file the push needs, its bytes (``peer_push.stage_file``): ``{"ok": true}``
    POST /peer/push?push=        The push sent (JSON: its document, ``peer_push.read_push_document``), checked and
                                 kept (``peer_push.send``), then ``caracole peer take --progress DIR`` queued, as
                                 Changes from <its library>: ``{"job": view}``
    GET  /api/peer/index[?sites=]   this library's site indexes (``sites``: those named, by commas; every one with
                                 none), as ``caracole index export`` writes them, a SQLite file streamed, one at a
                                 time
    POST /peer/index             The index pages another caracole's lookups read (the phone's: an index export of
                                 pages, its bytes, ``peer_push.stage_index``), staged and read as the merge takes it
                                 (``index_transfer.check_pages``: 400, 409 for another version), then ``caracole
                                 index merge --delete --progress -- FILE`` queued (``jobs.index_merge_job``): 202
                                 ``{"job": N}``

Another caracole reads the first three to compare the two and to take what the owner chose (``caracole peer``). They
are reads, as a search is: no lock, no site asked, nothing written. Under ``/api/``, another site's page can't read
them (``security.own_page_read``); a caracole, which is no browser, can. The pull is a write, as any: the form token
and the cross-origin check, then a command under caracole's lock, which asks the other caracole for each unit.

A push is the phone's, which can't be asked to pull: it sends this side the units it takes (peer_push.py), each
request a write with the form token in its header (a ``json`` or ``bytes`` route, web/app.py). Its files are staged
in ``state_dir/peer/``, never in the library, and checked by their SHA-256; its take is a command, queued under
``peer-push:<its id>`` as a job of its own, and one from the same caracole while another is waiting or running is
refused (409), that push left open. The index is read in one transaction into a file of ``cache_dir/peer/``, taking
no lock, and that file is gone once it is open to be sent. The index pages another caracole posts are staged in
``state_dir/peer/`` (at most two waiting) until their merge, a command under caracole's lock, deletes them: caracole
serve writes nothing else for a sync (AGENTS.md).
"""

from __future__ import annotations

import io
import os
import secrets
import threading
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from caracole import peer_push
from caracole.web.app import Response, Route, WebApp, json_response
from caracole.web.pages import Refused

PEER_PULL = "peer-pull:"  # a pull's job key: the address it takes from after it, so a second one joins it
PEER_PUSH = "peer-push:"  # a push's take's job key: the id of the caracole that pushed after it
MAX_UNITS = 5000  # a pull's units at most: a library's every unit, many times over
SQLITE = "application/vnd.sqlite3"
LEFTOVER = 3600.0  # seconds after which a copy of the indexes left in cache_dir/peer (its process killed) is deleted

ROUTES = (
    Route("GET", "/api/peer/state", lambda app, asked: state(app, _params(asked.target))),
    Route("GET", "/api/peer/unit", lambda app, asked: unit(app, _params(asked.target))),
    Route("GET", "/api/peer/file", lambda app, asked: song_file(app, _params(asked.target))),
    Route("POST", "/peer/pull", lambda app, asked, form: pull(app, form), limit=1024 * 1024),
    Route("POST", "/peer/push/new", lambda app, asked, doc: push_new(app, doc), body="json",
          limit=peer_push.NEW_MAX),
    Route("POST", "/peer/push/file", lambda app, asked, data: push_file(app, _params(asked.target), data),
          body="bytes", limit=peer_push.FILE_MAX),
    Route("POST", "/peer/push", lambda app, asked, doc: push(app, _params(asked.target), doc), body="json",
          limit=peer_push.DOCUMENT_MAX),
    Route("GET", "/api/peer/index", lambda app, asked: index(app, asked, _params(asked.target))),
    Route("POST", "/peer/index", lambda app, asked, data: push_index(app, data), body="bytes",
          limit=peer_push.INDEX_MAX),
)
# One copy of the indexes out at a time, from its making until it is sent (or dropped): each is as large as they are
_streaming = threading.Lock()


def _params(target: str) -> dict[str, str]:
    try:
        found = parse_qs(urlsplit(target).query, keep_blank_values=True, errors="strict", max_num_fields=10)
    except (UnicodeDecodeError, ValueError):
        return {}
    return {k: v[0] for k, v in found.items()}


def _library(app: WebApp):
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    overrides = app.overrides()
    try:
        books = load_songbooks(songbooks_file(app.cfg.library_dir))
    except SongbookError as e:
        raise Refused(503, "Can't read songbooks.toml", f"Can't read songbooks.toml: {e}.") from e
    return overrides, books


def state(app: WebApp, params: dict[str, str]) -> Response:
    """``GET /api/peer/state``: ``peer_sync.state_document`` of this library, with its base and its kept answers for
    the caracole ``peer`` names (none named: no base, no ``kept``), or why it can't be read, as JSON."""
    from caracole import __version__, index_transfer, politeness
    from caracole import peer_sync as sync

    try:
        overrides, books = _library(app)
        with app.db() as conn:
            units = sync.library_state(conn, overrides, books)
            server = sync.own_id(conn)
            base = sync.base_of(conn, params["peer"]) if params.get("peer") else None
            kept = sync.kept_of(conn, params["peer"]) if params.get("peer") else None
            indexes = index_transfer.newest(conn)
    except Refused as e:
        return json_response(e.status, {"error": e.message})
    # The settings, for a phone, which looks songs up with them (a reader that isn't one passes over them: the
    # sync's FORMAT is the same). The form token, for the pull the other caracole may post (POST /peer/pull) and a
    # push's requests: no wider than a page's, which any client that reaches the server reads, and another site's
    # page can read neither.
    return json_response(200, sync.state_document(server, __version__, app.cfg.library_name, units, base,
                                                  indexes=indexes, kept=kept)
                         | {"settings": politeness.settings_document(app.cfg), "token": app.csrf})


def unit(app: WebApp, params: dict[str, str]) -> Response:
    """``GET /api/peer/unit``: a unit whole (``peer_sync.unit_document``), or 404."""
    from caracole import peer_sync as sync

    unit_id = params.get("id", "")
    try:
        overrides, books = _library(app)
        with app.db() as conn:
            doc = sync.unit_document(conn, app.cfg, overrides, books, unit_id)
    except Refused as e:
        return json_response(e.status, {"error": e.message})
    if doc is None:
        return json_response(404, {"error": f"no unit {unit_id[:200]!r} here"})
    return json_response(200, doc)


def song_file(app: WebApp, params: dict[str, str]) -> Response:
    """``GET /api/peer/file``: a song's kept file, its bytes as recorded, or 404."""
    from caracole import peer_sync as sync

    try:
        with app.db() as conn:
            data = sync.song_file(conn, app.cfg.library_dir, params.get("song", ""), params.get("name", ""))
    except Refused as e:
        return json_response(e.status, {"error": e.message})
    if data is None:
        return json_response(404, {"error": "no such file kept, or it changed since"})
    return Response(200, data, [("Content-Type", "application/octet-stream")])


def pull(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /peer/pull``: ``caracole peer pull`` of the units the form names from the caracole at ``from``, queued."""
    from caracole import peer_sync as sync

    try:
        address = sync.peer_address(form.get("from", ""))
    except sync.PeerError as e:
        raise Refused(400, "Not an address", str(e)) from None
    units = [u.strip() for u in form.get("units", "").splitlines() if u.strip()]
    if not units or len(units) > MAX_UNITS or any("/" not in u or len(u) > 1000 for u in units):
        raise Refused(400, "No units", "Which units? The form names none we can take.")
    steps = [(f"Taking {len(units)} {'change' if len(units) == 1 else 'changes'} from {address}",
              ("peer", "pull", *(f"--unit={u}" for u in units), "--", address))]
    job, _ = app.submit(f"Share with {address}", PEER_PULL + address, steps, display=address, join=False)
    return app.queued(job)


def _refused(e: peer_push.PushError) -> Refused:
    return Refused(e.status, "Not taken", str(e))


def push_new(app: WebApp, doc: Any) -> Response:
    """``POST /peer/push/new``: a push opened, with the files this side needs sent."""
    from caracole import peer_sync as sync

    try:
        sender, files = peer_push.read_new(doc)
        with app.db() as conn:
            own = sync.own_id(conn)
            need = peer_push.needed(conn, app.cfg.library_dir, files)
        opened = peer_push.new_push(app.cfg.state_dir, sender=sender, files=files, need=need, own=own)
    except peer_push.PushError as e:
        raise _refused(e) from None
    except OSError as e:  # the staging folder's, not the database's (read above)
        raise Refused(503, "Not kept", f"Couldn't open the push: {e}.") from e
    return json_response(200, {"push": opened.push, "need": opened.need})


def push_file(app: WebApp, params: dict[str, str], data: bytes) -> Response:
    """``POST /peer/push/file``: a file the push needs, staged once its bytes are what its SHA-256 says."""
    try:
        peer_push.stage_file(app.cfg.state_dir, params.get("push", ""), params.get("sha256", ""), data)
    except peer_push.PushError as e:
        raise _refused(e) from None
    except OSError as e:
        raise Refused(503, "Not kept", f"Couldn't keep the file: {e}.") from e
    return json_response(200, {"ok": True})


def push(app: WebApp, params: dict[str, str], doc: Any) -> Response:
    """``POST /peer/push``: the push sent, checked, kept, and its take queued (``caracole peer take``)."""
    from caracole import peer_sync as sync

    state_dir = app.cfg.state_dir
    push_id = params.get("push", "")
    try:
        peer_push.check_id(push_id)
        sent = peer_push.read_push_document(doc)
        peer_push.sweep(state_dir)
        pending = peer_push.unstaged(state_dir, push_id, sent.files())
        with app.db() as conn:
            own = sync.own_id(conn)
            kept = {f for f in pending if peer_push.kept_copy(conn, app.cfg.library_dir, f) is not None}
        folder = peer_push.send(state_dir, push_id, sent, doc, own=own, kept=kept)
    except peer_push.PushError as e:
        raise _refused(e) from None
    except OSError as e:  # the staging folder's, not the database's (read above)
        raise Refused(503, "Not kept", f"Couldn't keep the push: {e}.") from e
    shown = f"Changes from {(sent.name.strip() or 'another caracole')[:120]}"
    count = len(sent.take)
    steps = [(f"Taking {count} {'change' if count == 1 else 'changes'}",
              ("peer", "take", "--progress", "--", str(folder)))]
    try:
        job, new = app.submit(shown, PEER_PUSH + sent.sender, steps, display=shown, join=False)
    except Refused:
        peer_push.unsend(state_dir, push_id)
        raise
    if not new:  # a take of this caracole's waits or runs: this push stays open, to send again once it is over
        peer_push.unsend(state_dir, push_id)
        raise Refused(409, "Taking already", f"{shown}: being taken already (request {job.id}). Send again once "
                                             "that's done.")
    return app.queued(job)


class _Streamed(io.BufferedReader):
    """A copy of the indexes, open to be sent: closed (server.py, once it is sent; or dropped), it lets the next
    copy be made."""

    def __init__(self, path, release):
        super().__init__(io.FileIO(path, "rb"))
        self._release = release

    def close(self) -> None:
        try:
            super().close()
        finally:
            release, self._release = self._release, None
            if release is not None:
                release()


def _leftovers(folder) -> None:
    """Delete the copies of the indexes a process killed while it made one left in ``folder``, an hour after."""
    import time

    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return
    for entry in entries:
        try:
            if (entry.name.startswith("index-") and entry.is_file(follow_symlinks=False)
                    and time.time() - entry.stat(follow_symlinks=False).st_mtime > LEFTOVER):
                os.unlink(entry.path)
        except OSError:
            continue


def index(app: WebApp, asked, params: dict[str, str]) -> Response:
    """``GET /api/peer/index``: this library's site indexes, as ``index_transfer.export`` writes them, from a file of
    ``cache_dir/peer/`` deleted once it is open, streamed (``Response.stream``): one copy at a time (503 while
    another is out), and none for a HEAD, which would make a whole copy only to say its length (405)."""
    from caracole import index_transfer

    if asked.method == "HEAD":
        return Response(405, b"", [("Allow", "GET")])
    try:
        sites = index_transfer.chosen([s.strip() for s in params.get("sites", "").split(",") if s.strip()])
    except index_transfer.TransferError as e:
        return json_response(400, {"error": str(e)})
    if not _streaming.acquire(blocking=False):
        return json_response(503, {"error": "Another index copy is on its way. Try again once it's sent."})
    folder = app.cfg.cache_dir / "peer"
    path = folder / f"index-{secrets.token_hex(8)}.sqlite"
    stream = None
    try:
        app.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        folder.mkdir(mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
        _leftovers(folder)
        with app.db() as conn:
            index_transfer.export(conn, path, sites, now=datetime.now(UTC))
        stream = _Streamed(path, _streaming.release)  # server.py closes it once it is sent
    except Refused as e:
        return json_response(e.status, {"error": e.message})
    except (index_transfer.TransferError, OSError) as e:
        return json_response(503, {"error": f"Couldn't copy the indexes: {e}"})
    finally:
        path.unlink(missing_ok=True)
        if stream is None:
            _streaming.release()
    return Response(200, headers=[("Content-Type", SQLITE),
                                  ("Content-Disposition", 'attachment; filename="caracole-index.sqlite"')],
                    stream=stream)


def push_index(app: WebApp, data: bytes) -> Response:
    """``POST /peer/index``: the index pages another caracole's lookups read, staged (``peer_push.stage_index``), and
    their merge queued, ``caracole index merge --delete --progress -- FILE``, a job of no song's; 202 with its id.
    Index exports left an hour that no waiting request names go first (``peer_push.sweep_indexes``).

    Before the 202, which the phone forgets its reads on, the file is read as the merge will take it
    (``index_transfer.check_pages``): an export of pages alone, of this caracole's layout, schema and columns. One
    that isn't is refused and deleted, 409 for another version (the phone keeps its reads until the two agree), 400
    for anything else, so that a file this side would refuse never costs the phone its reads, and nothing but pages
    reaches the merge from the network."""
    from caracole import index_transfer
    from caracole.web import jobs

    state_dir = app.cfg.state_dir
    try:
        named = {arg for job in app.queue.snapshot() if job.active for step in job.steps for arg in step.args}
        peer_push.sweep_indexes(state_dir, named)
        path = peer_push.stage_index(state_dir, data)
    except peer_push.PushError as e:
        raise _refused(e) from None
    except OSError as e:
        raise Refused(503, "Not kept", f"Couldn't keep the index pages: {e}.") from e
    try:
        with app.db() as conn:
            index_transfer.check_pages(conn, path)
        job, _ = app.submit(**jobs.index_merge_job(path))
    except index_transfer.OtherVersion as e:
        path.unlink(missing_ok=True)
        raise Refused(409, "Not merged", f"{_unstaged(e, path)} Bring both scribes to one version first.") from None
    except index_transfer.TransferError as e:
        path.unlink(missing_ok=True)
        raise Refused(400, "Not merged", _unstaged(e, path)) from None
    except Refused:
        path.unlink(missing_ok=True)
        raise
    return json_response(202, {"job": job.id})


def _unstaged(e: Exception, path) -> str:
    """A refusal of a staged export in words of the file posted, never of the path it was staged at."""
    said = str(e).replace(str(path), "The index export")
    return said[:1].upper() + said[1:] + ("" if said.endswith(".") else ".")
