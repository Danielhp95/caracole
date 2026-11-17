"""caracole serve's Ultimate Guitar link pasted into the library page's search box: what caracole knows of its page,
and its page read now (docs/superpowers/plans/2026-11-17-ug-link.md).

    GET  /api/ug/link?url=
                          a UG link pasted (``url``, any address of a tab's page or an artist's, as an address bar shows
                          it: ug_urls.read_link): its ``kind``, the page's ``url`` as caracole asks for it, a tab's
                          ``tab_id``; what caracole knows of it (ug/link.py ``known``), read from the database and the
                          HTTP cache alone, with no request and no lock: its ``state`` and, but ``found`` and ``auto``,
                          ``why``; what UG names a tab (``tab``), its artist's page and whether caracole read it
                          (``artist_page``), the names to fill the Artist and Title with (``guess``, as a search names a
                          song only an artist page lists), the library's song of it (``song``) and the songs it stands
                          for (``hits``, each as /api/search's ``index`` items: a tab's song, or an artist's songs)
    POST /ug/link         that page read now (``url``): ``caracole ug --link --progress`` queued, a job of no song's
                          (``jobs.UG_LINK`` and the page's address, among ``INDEX_READS``), when its state is ``auto``

The page reads a link by itself once it is pasted, once a link a page, and follows the job on /api/jobs, asking
``/api/ug/link`` again once its ``tab`` stage is done (the tab's names) and once it is over (its artist's songs). Its
Fetch this version posts the lookup the search's rows post (``POST /lookup`` with ``tab``: ``caracole get --tab``), so
the version pasted is the one kept. A read's end drops the answers the searches kept (``app._reads``), as an artist
page's read does, so a search finds the artist's songs at once. Refused, with nothing queued (``pages.Refused``): a text
that is no UG link (400), a link known already, of a type caracole keeps nothing of, or gone (409), and one that may not
be read now: a cooldown, the hour's lookups spent, a read that failed within the hour (429).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from caracole.web.app import Response, Route, WebApp, json_response, query, redirect, wants_json
from caracole.web.jobs import UG_LINK, ug_link_steps
from caracole.web.pages import Refused
from caracole.web.status import details_href

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.songs import Song
    from caracole.ug_urls import UgLink

LINK_LIMIT = 600  # characters of a pasted address

ROUTES = (
    Route("GET", "/api/ug/link", lambda app, asked: api_ug_link(app, query(asked))),
    Route("POST", "/ug/link", lambda app, asked, form: read_ug_link(app, form, json=wants_json(asked))),
)


def pasted_link(text: str) -> UgLink:
    """The UG page a pasted text links to (ug_urls.read_link); Refused (400) for anything else."""
    from caracole.ug_urls import read_link

    link = read_link(text) if len(text) <= LINK_LIMIT else None
    if link is None:
        raise Refused(400, "Not a UG link", "Not an Ultimate Guitar tab's page or artist's page.")
    return link


def api_ug_link(app: WebApp, asked: dict[str, list[str]], *, now: datetime | None = None) -> Response:
    """What the library page offers for a UG link pasted into its search box, with no request (the module's
    docstring), as of ``now`` (this moment by default)."""
    link = pasted_link((asked.get("url") or [""])[0])
    overrides = app.overrides()
    with app.db() as conn:
        return json_response(200, link_answer(app, conn, overrides, link, now or datetime.now(UTC)))


def link_answer(app: WebApp, conn: sqlite3.Connection, overrides: Overrides, link: UgLink,
                now: datetime) -> dict[str, Any]:
    """``GET /api/ug/link``'s answer for ``link``: what caracole knows of its page (ug/link.py ``known``) and how it
    names what the link stands for (``named``: its songs, the library's song of it, the names to fill in)."""
    from caracole.songs import list_songs
    from caracole.ug.link import known, named
    from caracole.web.search_routes import _hit_json, _rows

    was = known(app.cfg, conn, link, now)
    names = named(conn, was)
    rows = (_rows(app, conn, [], [_hit_json(conn, h) for h in names.hits], list_songs(conn))[1]
            if names.hits else [])
    return {
        **link.as_json(), "state": was.state, **({"why": was.why} if was.why else {}),
        "tab": was.tab.as_json() if was.tab is not None else None,
        "artist_page": {"url": was.page, "read": was.read_at is not None, "read_at": was.read_at or None}
        if was.page else None,
        "guess": {"artist": names.artist, "title": names.title},
        "song": _song_json(app, conn, overrides, names.song, link) if names.song is not None else None,
        "hits": rows,
    }


def _song_json(app: WebApp, conn: sqlite3.Connection, overrides: Overrides, song: Song, link: UgLink) -> dict[str, Any]:
    """The library's song of a link, as the panel names it: whether it has a sheet and the link to it, and whether this
    tab is that sheet or its pick (``this_tab``: ``[pin]``)."""
    from caracole.library_page import sheet_href
    from caracole.songs import HUMAN_SHEET

    sheet = conn.execute(
        "SELECT v.provider, v.tab_id FROM files f LEFT JOIN versions v ON v.id = f.version_id "
        "WHERE f.song_id = ? AND f.name = ?", (song.id, HUMAN_SHEET)).fetchone()
    this_tab = (sheet is not None and sheet[0] == "ug" and sheet[1] == str(link.tab_id)) or (
        link.tab_id in overrides.pin.get(song.key, ()))
    return {"id": song.id, "identity": song.key, "display": song.display, "has_sheet": sheet is not None,
            "sheet": sheet_href(app.cfg.library_dir, song) if sheet is not None else None, "this_tab": this_tab}


def read_ug_link(app: WebApp, form: dict[str, str], *, json: bool, now: datetime | None = None) -> Response:
    """A pasted UG link's page read now: ``caracole ug --link --progress`` queued, a job of no song's (asked again while
    it waits or runs, that job), when its state is ``auto``; refused otherwise (400 no UG link, 409 known already, of a
    type caracole keeps nothing of, or gone, 429 a cooldown, the hour's lookups spent, or a read failed lately)."""
    from caracole.ug.link import known

    link = pasted_link(form.get("url", "").strip())
    with app.db() as conn:
        was = known(app.cfg, conn, link, now or datetime.now(UTC))
    if was.state == "found":
        raise Refused(409, "Read already", "Read already: caracole knows this page.")
    if was.state in ("other", "gone"):
        raise Refused(409, "Nothing to read", f"Nothing to read: {was.why}.")
    if was.state != "auto":
        raise Refused(429, "Not now", f"Not now: {was.why}.")
    what = f"tab {link.tab_id}" if link.kind == "tab" else "an artist's page"
    job, _ = app.submit(f"Read {what} on Ultimate Guitar", UG_LINK + link.url, ug_link_steps(link.url),
                        display="A tab on Ultimate Guitar" if link.kind == "tab" else "An artist on Ultimate Guitar")
    with app._searching:
        app._reads.add(job.id)
    if json:
        return json_response(202, {"job": job.id, "url": f"/api/jobs/{job.id}"})
    return redirect(f"/{details_href(job.id)}")
