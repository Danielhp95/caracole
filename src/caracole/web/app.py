"""The routes of ``caracole serve``, as one function from a request to a response.

    GET  /, /index.html   the library page, with its forms (library_page, WebControls)
    GET  /lookup          look a song up as you type (lookup_page.py), and read its sheet
    GET  /jobs            the requests, and what each command printed (?refresh=0: no reloading)
    GET  /api/search?q=   your library and the offline UG index, as JSON (search.py)
    GET  /api/jobs[/<id>] the requests as data: each step with its state (Job.as_json)
    GET  /<file>          a file of the library (files.py)
    POST /request         a song for wanted.txt; with ``fetch``, looked up now too
    POST /fetch           look a song of the library up now, unless it needs review first
    POST /lookup          look a song up now: the UG song (``ug``) or tab (``tab``) you picked
    GET, POST /login      the sign-in page, with an access token

Every request must name the server by a name it answers to (421 otherwise).
Every POST must pass the cross-origin check and carry the form token (403),
be a form (415) and be small (413). With an access token, nothing but the
sign-in page is served before signing in (401).

A request is written to wanted.txt at once, with ``wanted.append_wanted``, the
function ``caracole add`` writes it with, and before the database: the line is
there even when the queue is full or the server stops. A request and a fetch
then queue their commands (jobs.py), and the answer sends the browser to the
requests page. A song looked up now is one ``caracole get --progress``; asked
for by the lookup page's script (``Accept: application/json``), the answer is
the job's address as data (202), else the lookup page, which follows it.

Searching reads, and sends no request: one search runs at a time, one asked
for meanwhile wins over the older ones still waiting (``superseded``: the
page asks again if it still wants it), and the offline index's answers are
kept a few minutes. A query of fewer than three letters (two in Chinese)
looks nowhere.
"""

from __future__ import annotations

import itertools
import json
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlsplit

from caracole import db
from caracole.config import Config
from caracole.web import pages
from caracole.web.files import NotServed, read_library_file
from caracole.web.jobs import JobQueue, QueueFull, add_steps, lookup_steps
from caracole.web.security import (
    SESSION_COOKIE,
    answers_to,
    cross_origin_ok,
    host_name,
    own_page_read,
    same_token,
    session_cookie,
    session_value,
)

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.songs import Song

MAX_BODY = 16 * 1024
LIMITS = {"artist": 200, "title": 300, "album": 300, "duration": 12}  # characters
PICK_LIMITS = {"ug": 300, "tab": 600}
QUERY_LIMIT = 200  # characters of a search
LIBRARY_HITS, INDEX_HITS, TABS_SHOWN = 5, 8, 24
CACHE_SIZE, CACHE_SECONDS = 128, 300.0  # the offline index's answers kept
SEARCH_CHECK_STEPS = 20_000  # SQLite steps between two looks for a newer search, a millisecond or so
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


def _json(status: int, data: Any) -> Response:
    return Response(status, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                    [("Content-Type", "application/json; charset=utf-8")])


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


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
        self._searching = threading.Lock()  # one search at a time
        self._tickets = itertools.count(1)
        self._newest = 0  # the newest search asked for
        self._found: OrderedDict[str, tuple[float, list[dict[str, Any]], str | None]] = OrderedDict()

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
            if path == "/lookup":
                from caracole.web.lookup_page import LOOKUP_CSP, lookup_page

                return _html(200, lookup_page(self.csrf), csp=LOOKUP_CSP)
            if path == "/jobs":
                still = parse_qs(urlsplit(request.target).query).get("refresh") == ["0"]
                return _html(200, pages.jobs_page(self.queue.snapshot(), refresh=not still))
            if path.startswith("/api/") and not own_page_read(request.headers):
                return _json(403, {"error": "This came from another site, so caracole refused it."})
            if path == "/api/search":
                return self._search(parse_qs(urlsplit(request.target).query).get("q", [""])[0])
            if path == "/api/jobs":
                return _json(200, {"jobs": [job.as_json() for job in self.queue.snapshot()]})
            if path.startswith("/api/jobs/"):
                number = path[len("/api/jobs/"):]
                job = self.queue.job(int(number)) if number.isascii() and number.isdigit() else None
                return _json(200, job.as_json()) if job is not None else _json(404, {"error": "no such request"})
            if path == "/login":
                return _redirect("/")
            return self._file(path)
        if method == "POST":
            handler = {"/request": self._request, "/fetch": self._fetch}.get(path)
            if path == "/lookup":
                wants_json = _wants_json(request)
                handler = lambda form: self._lookup(form, wants_json=wants_json)  # noqa: E731
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

    def _wanted_line(self, form: dict[str, str]) -> tuple[Any, str] | tuple[int, str, str]:
        """The form's song written to wanted.txt, as ``caracole add`` writes it, with a note of where;
        or why it isn't, as (status, title, message)."""
        from caracole.wanted import append_wanted, find_wanted, parse_duration

        values = {name: form.get(name, "").strip() for name in LIMITS}
        for name, value in values.items():
            if len(value) > LIMITS[name]:
                return 400, "Too long", f"The {name} is too long: {LIMITS[name]} characters at most."
        artist, title, album = values["artist"], values["title"], values["album"] or None
        if not artist or not title:
            return 400, "Not a song", "A song needs an artist and a title."
        duration_ms = None
        if values["duration"]:
            try:
                duration_ms = parse_duration(values["duration"])
            except ValueError as e:
                return 400, "Not a length", f"The length is a {e}."
            if duration_ms is None:
                return 400, "Not a length", (f"The length {values['duration']!r} isn't a duration: "
                                             "write m:ss, h:mm:ss or whole seconds.")
        path = self.cfg.wanted_file
        with self._wanted:
            try:
                listed = find_wanted(path, artist, title) is not None
                line = append_wanted(path, artist, title, album, duration_ms)
            except ValueError as e:  # a song the file can't hold, such as an artist with " - " in it
                return 400, "Not added", f"caracole can't add this song: {e}"
            except OSError as e:
                return 500, "Not added", f"wanted.txt can't be written: {e.strerror or e}"
        return line, f"{'Already in' if listed else 'Added to'} wanted.txt, line {line.line_no}."

    def _request(self, form: dict[str, str]) -> Response:
        """A song for wanted.txt, as ``caracole add`` writes it, and its commands queued."""
        written = self._wanted_line(form)
        if len(written) == 3:
            return _message(*written)
        line, note = written
        display = f"{line.artist} - {line.title}"
        fetch = form.get("fetch") in ("1", "on", "yes")
        if fetch:  # `caracole get` adds the song itself
            steps = lookup_steps(line.artist, line.title, album=line.album, duration_ms=line.duration_ms)
        else:
            steps = add_steps(line.artist, line.title, album=line.album, duration_ms=line.duration_ms)
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
            job, _ = self.queue.submit(f"Fetch {song.display}", song.key, lookup_steps(song.artist, song.title),
                                       fetching=True)
        except QueueFull:
            return _message(503, "The queue is full", "The queue is full: try again once it empties.")
        return _redirect(f"/jobs#job-{job.id}")

    # --- a song looked up now, and search as you type ----------------------------------------------

    def _lookup(self, form: dict[str, str], *, wants_json: bool) -> Response:
        """The song you picked on the lookup page, in wanted.txt at once, then looked up now."""
        from caracole.overrides import OverridesError, tab_id_from_url

        def refused(status: int, title: str, message: str) -> Response:
            return _json(status, {"error": message}) if wants_json else _message(status, title, message)

        pick = {name: form.get(name, "").strip() for name in PICK_LIMITS}
        for name, value in pick.items():
            if len(value) > PICK_LIMITS[name]:
                return refused(400, "Too long", f"The {name} is too long: {PICK_LIMITS[name]} characters at most.")
        artist_key, sep, song_key = pick["ug"].partition("/")
        if pick["ug"] and (not sep or not artist_key or not song_key or "/" in song_key):
            return refused(400, "Not a pick", f"{pick['ug']!r} isn't an Ultimate Guitar song (artist-key/song-key).")
        if pick["tab"]:
            try:
                tab_id_from_url(pick["tab"])
            except OverridesError as e:
                return refused(400, "Not a pick", f"That isn't an Ultimate Guitar tab: {e}")
        written = self._wanted_line(form)
        if len(written) == 3:
            return refused(*written)
        line, note = written
        steps = lookup_steps(line.artist, line.title, album=line.album, duration_ms=line.duration_ms,
                             ug=pick["ug"] or None, tab=pick["tab"] or None)
        try:
            job, _ = self.queue.submit(f"Fetch {line.artist} - {line.title}", line.identity, steps, fetching=True,
                                       note=note)
        except QueueFull:
            return refused(503, "The queue is full", f"{note} The queue is full, so it wasn't looked up now: the "
                                                     "nightly run looks for it, or ask again once the queue empties.")
        if wants_json:
            return _json(202, {"job": job.id, "url": f"/api/jobs/{job.id}"})
        return _redirect(f"/lookup?job={job.id}")

    def _search(self, query: str) -> Response:
        """Your library and the offline UG index, for a query typed into the lookup page."""
        from caracole.normalize import has_han

        q = " ".join(query.split())[:QUERY_LIMIT]
        letters = sum(c.isalnum() for c in q)
        if letters < (2 if has_han(q) else 3):
            return _json(200, {"query": q, "library": [], "index": [], "short": True})
        ticket = next(self._tickets)
        self._newest = ticket
        superseded = {"query": q, "superseded": True}

        def typed_over() -> int:  # SQLite asks every few thousand steps: non-zero interrupts the query
            return int(ticket != self._newest)

        with self._searching:
            if typed_over():  # typed on meanwhile: the newer query goes first
                return _json(200, superseded)
            try:
                with closing(self._connect()) as conn:
                    conn.set_progress_handler(typed_over, SEARCH_CHECK_STEPS)
                    return _json(200, self._found_for(conn, q))
            except sqlite3.OperationalError as e:
                if typed_over():  # interrupted: the newer one reads now
                    return _json(200, superseded)
                return _json(503, {"query": q, "error": f"The database can't be read: {e}"})
            except (sqlite3.Error, OSError) as e:
                return _json(503, {"query": q, "error": f"The database can't be read: {e}"})

    def _found_for(self, conn: sqlite3.Connection, q: str) -> dict[str, Any]:
        from caracole.get import readable_files
        from caracole.search import search_library
        from caracole.songs import list_songs

        library = [{"id": h.song.id, "display": h.song.display, "artist": h.song.artist, "title": h.song.title,
                    "status": h.song.status, "score": h.score,
                    "files": readable_files(conn, self.cfg.library_dir, h.song)}
                   for h in search_library(conn, q, LIBRARY_HITS)]
        cached = self._found.get(q)
        if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
            index, hint = cached[1], cached[2]
        else:
            index, hint = self._index_hits(conn, q)
            self._found[q] = (time.monotonic(), index, hint)
            while len(self._found) > CACHE_SIZE:
                self._found.popitem(last=False)
        mine = {(s.match_artist_key, s.match_song_key): s.id for s in list_songs(conn) if s.match_song_key}
        hits = [{**hit, "song": mine.get(tuple(hit["ug"].split("/", 1)))} for hit in index]
        return {"query": q, "library": library, "index": hits, "hint": hint}

    def _index_hits(self, conn: sqlite3.Connection, q: str) -> tuple[list[dict[str, Any]], str | None]:
        from caracole.search import TYPE_ORDER, bare_id_hint, search_index
        from caracole.ug.index import index_count
        from caracole.ug.lookup import song_tabs

        if index_count(conn) == 0:
            return [], "The offline Ultimate Guitar index is empty: run caracole index build once (about 10 minutes)."
        hits = search_index(conn, q, INDEX_HITS)

        def rank(t) -> tuple:
            return (TYPE_ORDER.index(t.type) if t.type in TYPE_ORDER else len(TYPE_ORDER), t.label is not None,
                    t.tab_id)

        out = [{"artist": h.artist, "title": h.title, "ug": f"{h.artist_key}/{h.song_key}", "counts": dict(h.counts),
                "score": h.score, "url": h.url, "labels": list(h.labels),
                "tabs": [{"id": t.tab_id, "type": t.type, "label": t.label, "url": t.url}
                         for t in sorted(song_tabs(conn, h.artist_key, h.song_key), key=rank)[:TABS_SHOWN]]}
               for h in hits]
        return out, bare_id_hint(q, hits)


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
