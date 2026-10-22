"""caracole serve's library page and its forms: a song requested, and a song of the library fetched now.

    GET  /, /index.html   the library page, with its forms (library_page, WebControls)
    POST /request         a song for wanted.txt; with ``fetch``, looked up now too
    POST /fetch           look a song of the library up now, unless it needs review first
    GET  /favicon.ico     the pages' icon (page_icon.py), for a browser that asks for it by this name

A request is written to wanted.txt at once, with ``wanted.append_wanted``, the
function ``caracole add`` writes it with, and before the database: the line is
there even when the queue is full or the server stops (``wanted_line``, which
the lookup page's requests share, search_routes.py). A request and a fetch
then queue their commands (jobs.py): a song looked up now (``fetch``, a
fetch, a lookup) is one ``caracole get --progress``. Without JavaScript, the
answer sends the browser to the request on /jobs. The library page's script
asks for JSON (``Accept: application/json``) and gets the job, as /jobs.json
gives it (``WebApp.queued``), so it stays on the page and shows the song's
progress on its card.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from caracole.web.app import FRAMES, Response, Route, WebApp, html_response, no_such_song, not_ignored, song_id
from caracole.web.jobs import LACUERDA_ARTIST, REMOVING, add_steps, lookup_steps
from caracole.web.jobs_routes import views
from caracole.web.pages import Refused
from caracole.web.review_routes import review_first

if TYPE_CHECKING:
    from caracole.wanted import WantedLine

LIMITS = {"artist": 200, "title": 300, "album": 300, "duration": 12}  # characters
PICK_LIMITS = {"ug": 300, "tab": 600, "lacuerda": 600}


ROUTES = (
    Route("GET", "/", lambda app, asked: library(app)),
    Route("GET", "/index.html", lambda app, asked: library(app)),
    Route("POST", "/request", lambda app, asked, form: request(app, form)),
    Route("POST", "/fetch", lambda app, asked, form: fetch(app, form)),
    Route("GET", "/favicon.ico", lambda app, asked: icon()),
)


def library(app: WebApp) -> Response:
    from caracole.library_page import WebControls, build_library_page
    from caracole.web.alphatab import available

    overrides = app.overrides(" Fix it, then reload this page.")
    from caracole.songs import list_songs

    jobs = app.queue.snapshot()
    with app.db() as conn:
        busy = _song_ids(conn, app.queue.fetching_keys())
        held = frozenset(s.id for s in list_songs(conn) if review_first(s, overrides))
        removing = _song_ids(conn, {job.song_key.removeprefix(REMOVING) for job in jobs
                                    if job.active and job.song_key.startswith(REMOVING)})
        # Every request on its way, which the page's script shows where it belongs (``kind``): a
        # song's on its card, a removal's on its song's, a songbook's change on its songbook's. A
        # LaCuerda artist page's read is no song's: the result row it was asked from follows it.
        active = tuple(views(app, conn, overrides, jobs, only=[
            j for j in jobs if j.active and not j.song_key.startswith(LACUERDA_ARTIST)]))
        controls = WebControls(app.csrf, busy, app.queue.active_count(), held, removing=removing, jobs=active,
                               timers=app.timers, guitar=available(app.cfg.alphatab_dir))
        html = build_library_page(conn, app.cfg, overrides, datetime.now(UTC).replace(microsecond=0),
                                  controls=controls)
    # The page's own CSP is in its meta tag; a header CSP would apply on top of it.
    return html_response(200, html, csp=FRAMES)


def icon() -> Response:
    """The mark every page carries inline, for a browser that asks for /favicon.ico anyway: an SVG, which,
    opened as a page of its own, may load and run nothing."""
    from caracole.page_icon import SVG

    return Response(200, SVG.encode("utf-8"), [("Content-Type", "image/svg+xml"),
                                                ("Content-Security-Policy", f"default-src 'none'; {FRAMES}")])


def request(app: WebApp, form: dict[str, str]) -> Response:
    """A song for wanted.txt, as ``caracole add`` writes it, and its commands queued; with ``lacuerda``, the
    LaCuerda song you picked, which its command records for the nightly run (Add for tonight's run)."""
    lacuerda = lacuerda_field(form)
    line, note = wanted_line(app, form)
    display = f"{line.artist} - {line.title}"
    fetch = form.get("fetch") in ("1", "on", "yes")
    if fetch:  # `caracole get` adds the song itself
        steps = lookup_steps(line.artist, line.title, album=line.album, duration_ms=line.duration_ms,
                             lacuerda=lacuerda)
    else:
        steps = add_steps(line.artist, line.title, album=line.album, duration_ms=line.duration_ms,
                          lacuerda=lacuerda)
    job, _ = app.submit(f"{'Fetch' if fetch else 'Add'} {display}", line.identity, steps, fetching=fetch,
                        note=note, display=display,
                        full=f"{note} The queue is full, so nothing else was queued: the nightly run looks for "
                             "the song, or request it again once the queue empties.")
    return app.queued(job)


def fetch(app: WebApp, form: dict[str, str]) -> Response:
    """Look a song of the library up now: one ``caracole get``, as Fetch it now and the lookup page do."""
    from caracole.songs import get_song

    asked = song_id(form.get("song", ""))
    overrides = app.overrides()
    with no_such_song(), app.db() as conn:
        song = get_song(conn, asked)
    not_ignored(song, overrides)
    if review_first(song, overrides):
        raise Refused(409, "Review it first",
                      f"caracole isn't sure which Ultimate Guitar song {song.display} is, so it can't "
                      "fetch it yet: run caracole review, or settle it in overrides.toml, then fetch it.")
    job, _ = app.submit(f"Fetch {song.display}", song.key, lookup_steps(song.artist, song.title), fetching=True,
                        display=song.display)
    return app.queued(job)


def wanted_line(app: WebApp, form: dict[str, str]) -> tuple[WantedLine, str]:
    """The form's song written to wanted.txt, as ``caracole add`` writes it, with a note of where;
    Refused when it isn't."""
    from caracole.wanted import append_wanted, find_wanted, parse_duration

    values = {name: form.get(name, "").strip() for name in LIMITS}
    for name, value in values.items():
        if len(value) > LIMITS[name]:
            raise Refused(400, "Too long", f"The {name} is too long: {LIMITS[name]} characters at most.")
    artist, title, album = values["artist"], values["title"], values["album"] or None
    if not artist or not title:
        raise Refused(400, "Not a song", "A song needs an artist and a title.")
    duration_ms = None
    if values["duration"]:
        try:
            duration_ms = parse_duration(values["duration"])
        except ValueError as e:
            raise Refused(400, "Not a length", f"The length is a {e}.") from e
        if duration_ms is None:
            raise Refused(400, "Not a length", (f"The length {values['duration']!r} isn't a duration: "
                                                "write m:ss, h:mm:ss or whole seconds."))
    path = app.cfg.wanted_file
    with app._wanted:
        try:
            listed = find_wanted(path, artist, title) is not None
            line = append_wanted(path, artist, title, album, duration_ms)
        except ValueError as e:  # a song the file can't hold, such as an artist with " - " in it
            raise Refused(400, "Not added", f"caracole can't add this song: {e}") from e
        except OSError as e:
            raise Refused(500, "Not added", f"wanted.txt can't be written: {e.strerror or e}") from e
    return line, f"{'Already in' if listed else 'Added to'} wanted.txt, line {line.line_no}."


def lacuerda_field(form: dict[str, str]) -> str | None:
    """A form's ``lacuerda``, the LaCuerda song or version picked, written as caracole asks for it; None for
    none; Refused for one that is no LaCuerda song's page."""
    from caracole.overrides import OverridesError, lacuerda_pick_from_url

    value = form.get("lacuerda", "").strip()
    if not value:
        return None
    if len(value) > PICK_LIMITS["lacuerda"]:
        raise Refused(400, "Too long", f"The lacuerda is too long: {PICK_LIMITS['lacuerda']} characters at most.")
    try:
        return lacuerda_pick_from_url(value).url
    except OverridesError as e:
        raise Refused(400, "Not a pick", f"That isn't a LaCuerda song: {e}") from e


def _song_ids(conn: sqlite3.Connection, keys: set[str]) -> frozenset[int]:
    if not keys:
        return frozenset()
    marks = ",".join("?" * len(keys))
    return frozenset(row[0] for row in conn.execute(f"SELECT id FROM songs WHERE key IN ({marks})", sorted(keys)))
