"""caracole serve's side of a sync between two caracoles (peer_sync.py): what this library holds, unit by unit.

    GET  /api/peer/state   this caracole's id (null before its first sync), its version, its library's name, and
                           each unit of its library (a song, a removal, a songbook, an artist's alias or UG page, a
                           blocked tab) with its label and its digest: ``peer_sync.state_document``

Another caracole reads it to compare the two (``caracole peer diff ADDRESS``) with no change to either. It is a read,
as a search is: no lock, no site asked, nothing written. Under ``/api/``, another site's page can't read it
(``security.own_page_read``); a caracole, which is no browser, can.
"""

from __future__ import annotations

from caracole.web.app import Response, Route, WebApp, json_response
from caracole.web.pages import Refused

ROUTES = (
    Route("GET", "/api/peer/state", lambda app, asked: state(app)),
)


def state(app: WebApp) -> Response:
    """``GET /api/peer/state``: ``peer_sync.state_document`` of this library, or why it can't be read, as JSON."""
    from caracole import __version__
    from caracole import peer_sync as sync
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    try:
        overrides = app.overrides()
        try:
            books = load_songbooks(songbooks_file(app.cfg.library_dir))
        except SongbookError as e:
            raise Refused(503, "songbooks.toml can't be read", f"songbooks.toml can't be read: {e}.") from e
        with app.db() as conn:
            units = sync.library_state(conn, overrides, books)
            server = sync.own_id(conn)
    except Refused as e:
        return json_response(e.status, {"error": e.message})
    return json_response(200, sync.state_document(server, __version__, app.cfg.library_name, units))
