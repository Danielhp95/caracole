"""The routes of ``caracole serve``, as one function from a request to a response.

    GET  /, /index.html   the library page, with its forms (library_page, WebControls)
    GET  /jobs            the requests, and what each command printed
    GET  /<file>          a file of the library (files.py)
    POST /request         a song for wanted.txt; with ``fetch``, fetched now too
    POST /fetch           fetch a song of the library now, unless it needs review first
    GET, POST /login      the sign-in page, with an access token

Every request must name the server by a name it answers to (421 otherwise).
Every POST must pass the cross-origin check and carry the form token (403),
be a form (415) and be small (413). With an access token, nothing but the
sign-in page is served before signing in (401).

A request is written to wanted.txt at once, with ``wanted.append_wanted``, the
function ``caracole add`` writes it with, and before the database: the line is
there even when the queue is full or the server stops. A request and a fetch
then queue their commands (jobs.py), and the answer sends the browser to the
requests page.
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

from caracole import db
from caracole.config import Config
from caracole.web import pages
from caracole.web.files import NotServed, read_library_file
from caracole.web.jobs import JobQueue, QueueFull, add_steps, fetch_steps
from caracole.web.security import (
    SESSION_COOKIE,
    answers_to,
    cross_origin_ok,
    host_name,
    same_token,
    session_cookie,
    session_value,
)

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.songs import Song

MAX_BODY = 16 * 1024
LIMITS = {"artist": 200, "title": 300, "album": 300, "duration": 12}  # characters
_COMMON_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cache-Control", "no-store"),
]
_FRAMES = "frame-ancestors 'none'"
_HTML = "text/html; charset=utf-8"


@dataclass(frozen=True)
class Request:
    method: str
    target: str  # the path and query, as sent
    headers: Mapping[str, str]  # lowercase names
    body: bytes = b""


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: list[tuple[str, str]] = field(default_factory=list)


def _html(status: int, html: str, *, csp: str = pages.PAGE_CSP) -> Response:
    return Response(status, html.encode("utf-8"), [("Content-Type", _HTML), ("Content-Security-Policy", csp)])


def _message(status: int, title: str, message: str) -> Response:
    return _html(status, pages.message_page(title, message))


def _redirect(location: str, *extra: tuple[str, str]) -> Response:
    return Response(303, b"", [("Location", location), *extra])


class WebApp:
    """The server's state: the config, the queue, the names it answers to and its tokens."""

    def __init__(self, cfg: Config, queue: JobQueue, *, allowed: frozenset[str], csrf: str | None = None,
                 access_token: str | None = None):
        self.cfg = cfg
        self.queue = queue
        self.allowed = allowed
        self.csrf = csrf or secrets.token_urlsafe(32)
        self._session = session_value(access_token) if access_token else None
        self._wanted = threading.Lock()  # one append to wanted.txt at a time, of the server's threads

    def handle(self, request: Request) -> Response:
        return self.finish(self._route(request))

    @staticmethod
    def finish(response: Response) -> Response:
        """Add the headers every answer has: no framing, no sniffing, no referrer, no cache."""
        if not any(name == "Content-Security-Policy" for name, _ in response.headers):
            response.headers.append(("Content-Security-Policy", _FRAMES))
        response.headers.extend(_COMMON_HEADERS)
        return response

    # --- routing -----------------------------------------------------------------------------------

    def _route(self, request: Request) -> Response:
        if not answers_to(host_name(request.headers.get("host")), self.allowed):
            return Response(421, b"caracole serve doesn't answer to this host name; "
                                 b"start it with --allow-host NAME to add one.\n",
                            [("Content-Type", "text/plain; charset=utf-8")])
        try:
            path = unquote(urlsplit(request.target).path, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return _message(400, "Not an address", "That address can't be read.")
        method = request.method
        if self._session is not None and not self._signed_in(request):
            if method == "POST" and path == "/login":
                return self._sign_in(request)
            if method in ("GET", "HEAD"):
                return _html(401, pages.sign_in_page(self.csrf))
            return _message(401, "Sign in first", "Sign in with the access token first.")
        if method in ("GET", "HEAD"):
            if path in ("/", "/index.html"):
                return self._library()
            if path == "/jobs":
                return _html(200, pages.jobs_page(self.queue.snapshot()))
            if path == "/login":
                return _redirect("/")
            return self._file(path)
        if method == "POST":
            handler = {"/request": self._request, "/fetch": self._fetch}.get(path)
            if handler is None:
                return _message(404, "Not here", "There's nothing to send to at this address.")
            form = self._form(request)
            return form if isinstance(form, Response) else handler(form)
        return Response(405, b"", [("Allow", "GET, HEAD, POST")])

    def _form(self, request: Request) -> dict[str, str] | Response:
        """The fields of a POSTed form, or why it is refused."""
        headers = request.headers
        if not cross_origin_ok("POST", headers, headers.get("host")):
            return _message(403, "Refused", "This came from another site, so caracole refused it.")
        kind = headers.get("content-type", "").split(";")[0].strip().lower()
        if kind != "application/x-www-form-urlencoded":
            return _message(415, "Not a form", "caracole reads only forms sent from its own pages.")
        if len(request.body) > MAX_BODY:
            return _message(413, "Too long", "That form is too long.")
        try:
            fields = parse_qs(request.body.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
        except (UnicodeDecodeError, ValueError):
            return _message(400, "Not a form", "That form can't be read.")
        form = {name: values[0] for name, values in fields.items()}
        if not same_token(form.get("csrf"), self.csrf):
            return _message(403, "Refused", "This form is older than the server, or not from its pages: "
                                            "reload the library and try again.")
        return form

    # --- an access token -------------------------------------------------------------------------

    def _signed_in(self, request: Request) -> bool:
        return same_token(session_cookie(request.headers.get("cookie")), self._session or "")

    def _sign_in(self, request: Request) -> Response:
        form = self._form(request)
        if isinstance(form, Response):
            return form
        if not same_token(session_value(form.get("token", "")), self._session or ""):
            return _html(401, pages.sign_in_page(self.csrf, failed=True))
        cookie = f"{SESSION_COOKIE}={self._session}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
        return _redirect("/", ("Set-Cookie", cookie))

    # --- the pages and the files -----------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        return db.connect(self.cfg.db_path)

    def _library(self) -> Response:
        from caracole.library_page import WebControls, build_library_page
        from caracole.overrides import OverridesError, load_overrides

        try:
            overrides = load_overrides(self.cfg.overrides_file)
        except OverridesError as e:
            return _message(503, "overrides.toml can't be read",
                            f"overrides.toml can't be read: {e}. Fix it, then reload this page.")
        from caracole.songs import list_songs

        try:
            with closing(self._connect()) as conn:
                busy = _song_ids(conn, self.queue.fetching_keys())
                held = frozenset(s.id for s in list_songs(conn) if review_first(s, overrides))
                controls = WebControls(self.csrf, busy, self.queue.active_count(), held)
                html = build_library_page(conn, self.cfg, overrides, datetime.now(UTC).replace(microsecond=0),
                                          controls=controls)
        except (sqlite3.Error, OSError) as e:  # DatabaseTooNew is an sqlite3.DatabaseError
            return _message(503, "The database can't be read", f"The database can't be read: {e}")
        # The page's own CSP is in its meta tag; a header CSP would apply on top of it.
        return _html(200, html, csp=_FRAMES)

    def _file(self, path: str) -> Response:
        try:
            if not path.startswith("/"):
                raise NotServed(path)
            data, kind, download = read_library_file(self.cfg.library_dir, path[1:],
                                                     hidden=(self.cfg.state_dir, self.cfg.cache_dir))
        except NotServed:
            return _message(404, "Not found", "There's no such page or file in the library.")
        headers = [("Content-Type", kind)]
        if download:
            headers.append(("Content-Disposition", "attachment"))
        return Response(200, data, headers)

    # --- the forms ------------------------------------------------------------------------------

    def _request(self, form: dict[str, str]) -> Response:
        """A song for wanted.txt, as ``caracole add`` writes it, and its commands queued."""
        from caracole.wanted import append_wanted, find_wanted, parse_duration

        values = {name: form.get(name, "").strip() for name in LIMITS}
        for name, value in values.items():
            if len(value) > LIMITS[name]:
                return _message(400, "Too long", f"The {name} is too long: {LIMITS[name]} characters at most.")
        artist, title, album = values["artist"], values["title"], values["album"] or None
        if not artist or not title:
            return _message(400, "Not a song", "A song needs an artist and a title.")
        duration_ms = None
        if values["duration"]:
            try:
                duration_ms = parse_duration(values["duration"])
            except ValueError as e:
                return _message(400, "Not a length", f"The length is a {e}.")
            if duration_ms is None:
                return _message(400, "Not a length", f"The length {values['duration']!r} isn't a duration: "
                                                     "write m:ss, h:mm:ss or whole seconds.")
        path = self.cfg.wanted_file
        with self._wanted:
            try:
                listed = find_wanted(path, artist, title) is not None
                line = append_wanted(path, artist, title, album, duration_ms)
            except ValueError as e:  # a song the file can't hold, such as an artist with " - " in it
                return _message(400, "Not added", f"caracole can't add this song: {e}")
            except OSError as e:
                return _message(500, "Not added", f"wanted.txt can't be written: {e.strerror or e}")
        note = f"{'Already in' if listed else 'Added to'} wanted.txt, line {line.line_no}."
        display = f"{line.artist} - {line.title}"
        fetch = form.get("fetch") in ("1", "on", "yes")
        steps = add_steps(line.artist, line.title, album=line.album, duration_ms=line.duration_ms)
        if fetch:
            steps += fetch_steps(display)
        try:
            job, _ = self.queue.submit(f"{'Fetch' if fetch else 'Add'} {display}", line.identity, steps,
                                       fetching=fetch, note=note)
        except QueueFull:
            return _message(503, "The queue is full",
                            f"{note} The queue is full, so nothing else was queued: the nightly run looks for "
                            "the song, or request it again once the queue empties.")
        return _redirect(f"/jobs#job-{job.id}")

    def _fetch(self, form: dict[str, str]) -> Response:
        """Fetch a song of the library now."""
        from caracole.overrides import OverridesError, load_overrides
        from caracole.songs import get_song

        try:
            song_id = int(form.get("song", ""))
        except ValueError:
            return _message(400, "Not a song", "Which song? The form names none.")
        try:
            overrides = load_overrides(self.cfg.overrides_file)
        except OverridesError as e:
            return _message(503, "overrides.toml can't be read", f"overrides.toml can't be read: {e}.")
        try:
            with closing(self._connect()) as conn:
                song = get_song(conn, song_id)
        except KeyError:
            return _message(404, "No such song", "That song isn't in the library.")
        except (sqlite3.Error, OSError) as e:
            return _message(503, "The database can't be read", f"The database can't be read: {e}")
        if song.status == "ignored" or song.key in overrides.ignore:
            return _message(409, "Ignored", f"{song.display} is ignored in overrides.toml.")
        if review_first(song, overrides):
            return _message(409, "Review it first",
                            f"caracole isn't sure which Ultimate Guitar song {song.display} is, so it can't "
                            "fetch it yet: run caracole review, or settle it in overrides.toml, then fetch it.")
        try:
            job, _ = self.queue.submit(f"Fetch {song.display}", song.key, fetch_steps(song.display),
                                       fetching=True)
        except QueueFull:
            return _message(503, "The queue is full", "The queue is full: try again once it empties.")
        return _redirect(f"/jobs#job-{job.id}")


def review_first(song: Song, overrides: Overrides) -> bool:
    """Whether ``caracole fetch --song`` would refuse the song as needing review first (commands/fetch.py).

    A review that its artist's UG page settles can be fetched, and so can one
    that overrides.toml settles (``[match]``, ``[pin]``, ``[reject]``): the
    job's ``caracole match`` reads it before the fetch.
    """
    from caracole.ug.fetch import needs_artist_page

    if song.match_decision != "review" or needs_artist_page(song):
        return False
    return not any(song.key in table for table in (overrides.match, overrides.pin, overrides.reject))


def _song_ids(conn: sqlite3.Connection, keys: set[str]) -> frozenset[int]:
    if not keys:
        return frozenset()
    marks = ",".join("?" * len(keys))
    return frozenset(row[0] for row in conn.execute(f"SELECT id FROM songs WHERE key IN ({marks})", sorted(keys)))
