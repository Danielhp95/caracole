"""caracole serve's side of a sync between two caracoles (peer_sync.py): what this library holds, unit by unit, each
unit whole, its kept files, and a pull of another caracole's units queued.

    GET  /api/peer/state?peer=   this caracole's id, its version, its library's name, each unit of its library (a song,
                                 a removal, a songbook, an artist's alias or UG page, a blocked tab) with its label and
                                 its digest, and what it last agreed on with the caracole ``peer`` names (its id):
                                 ``peer_sync.state_document``; and the form token, for a pull's form
    GET  /api/peer/unit?id=      a unit whole, as another caracole takes it: ``peer_sync.unit_document`` (404: no such
                                 unit here)
    GET  /api/peer/file?song=&name=   a song's kept file (``files``), while it is what caracole recorded (404 else)
    POST /peer/pull              Take these units from the caracole at ``from``: ``caracole peer pull FROM --unit=…``
                                 queued (``units``, one id a line), then to its line in the Requests tab

Another caracole reads the first three to compare the two and to take what the owner chose (``caracole peer``). They
are reads, as a search is: no lock, no site asked, nothing written. Under ``/api/``, another site's page can't read
them (``security.own_page_read``); a caracole, which is no browser, can. The pull is a write, as any: the form token
and the cross-origin check, then a command under caracole's lock, which asks the other caracole for each unit.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from caracole.web.app import Response, Route, WebApp, json_response
from caracole.web.pages import Refused

PEER_PULL = "peer-pull:"  # a pull's job key: the address it takes from after it, so a second one joins it
MAX_UNITS = 5000  # a pull's units at most: a library's every unit, many times over

ROUTES = (
    Route("GET", "/api/peer/state", lambda app, asked: state(app, _params(asked.target))),
    Route("GET", "/api/peer/unit", lambda app, asked: unit(app, _params(asked.target))),
    Route("GET", "/api/peer/file", lambda app, asked: song_file(app, _params(asked.target))),
    Route("POST", "/peer/pull", lambda app, asked, form: pull(app, form), limit=1024 * 1024),
)


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
        raise Refused(503, "songbooks.toml can't be read", f"songbooks.toml can't be read: {e}.") from e
    return overrides, books


def state(app: WebApp, params: dict[str, str]) -> Response:
    """``GET /api/peer/state``: ``peer_sync.state_document`` of this library, or why it can't be read, as JSON."""
    from caracole import __version__
    from caracole import peer_sync as sync

    try:
        overrides, books = _library(app)
        with app.db() as conn:
            units = sync.library_state(conn, overrides, books)
            server = sync.own_id(conn)
            base = sync.base_of(conn, params["peer"]) if params.get("peer") else None
    except Refused as e:
        return json_response(e.status, {"error": e.message})
    # The form token, for the pull the other caracole may post (POST /peer/pull): no wider than a page's, which any
    # client that reaches the server reads, and another site's page can read neither.
    return json_response(200, sync.state_document(server, __version__, app.cfg.library_name, units, base)
                         | {"token": app.csrf})


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
        return json_response(404, {"error": "no such file kept, or it changed since caracole kept it"})
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
        raise Refused(400, "No units", "Which units? The form names none caracole can take.")
    steps = [(f"Taking {len(units)} {'change' if len(units) == 1 else 'changes'} from {address}",
              ("peer", "pull", *(f"--unit={u}" for u in units), "--", address))]
    job, _ = app.submit(f"Sync with {address}", PEER_PULL + address, steps, display=address, join=False)
    return app.queued(job)
