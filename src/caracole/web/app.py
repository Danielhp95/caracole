"""The routes of ``caracole serve``, as one function from a request to a response.

    GET  /, /index.html   the library page, with its forms (library_page, WebControls)
    GET  /lookup          look a song up as you type (lookup_page.py), and read its sheet
    GET  /jobs            the requests, a line each, and what each command printed
                          (?job=N: its output open; ?refresh=0: no reloading)
    GET  /jobs.json       the requests, a line each, for the page's script (?jobs=N,M: only those
                          jobs, each with its song's card once it is over)
    GET  /api/search?q=   your library and the offline indexes, as JSON (search.py): your songs, the
                          artists the query names, the UG index's songs, which comes first and the
                          row Enter may act on; gtptabs.com's and MuseScore's pages, and the
                          sites not searched, with why
    GET  /api/artist?key= an artist of the offline index: their songs, most tabbed first, 50 from
                          ``offset``, and yours by them
    GET  /api/jobs[/<id>] the requests as data: each step with its state (Job.as_json)
    GET  /review?song=ID  a song in review's picker, on a page of its own
    GET  /<file>          a file of the library (files.py), or a page caracole wrote there, such as
                          a sheet viewer, while it is as written (``written_pages``), in a sandbox
    POST /request         a song for wanted.txt; with ``fetch``, looked up now too
    POST /fetch           look a song of the library up now, unless it needs review first
    POST /lookup          look a song up now: the UG song (``ug``) or tab (``tab``) you picked
    POST /review          a song in review's answer, as ``caracole review --song`` writes it
    POST /remove          what removing a song takes; with ``confirm``, ``caracole remove`` queued, and
                          back to the library, at the song's card (to the page's script: what it takes,
                          as data, then the job)
    POST /songbook/…      make a songbook, add to it, move or take out a song, rename it, delete it
                          (songbooks.py); a songbook's page, _songbooks/<folder>/songbook.html, is
                          one of the ``written_pages``
    GET, POST /login      the sign-in page, with an access token

Every request must name the server by a name it answers to (421 otherwise).
Every POST must pass the cross-origin check and carry the form token (403),
be a form (415) and be small (413). /jobs.json, which no form asks for, must
pass the same cross-origin check and carry the form token in an
``X-Caracole-Form-Token`` header (403). With an access token, nothing but the
sign-in page is served before signing in (401).

A request is written to wanted.txt at once, with ``wanted.append_wanted``, the
function ``caracole add`` writes it with, and before the database: the line is
there even when the queue is full or the server stops. A request and a fetch
then queue their commands (jobs.py): a song looked up now (``fetch``, a
fetch, a lookup) is one ``caracole get --progress``. Without JavaScript, the
answer sends the browser to the request on /jobs, and a lookup's to the lookup
page, which follows it. The library page's script asks for JSON (``Accept:
application/json``) and gets the job, as /jobs.json gives it, so it stays on the
page and shows the song's progress on its card; the lookup page's gets the
job's address (202), which it follows on /api/jobs, and the job as the library
page reads it (``view``), so that a result's Get it there shows how it goes in
its row. To a page's script (it
accepts JSON, or asks ``/api/``), a refusal is then ``{"error": "one
sentence"}``, with the same status, and ``"reload": true`` when the page must
be reloaded (a form token older than the server, signing in).

A lookup of a song your library has (named by its id, or the UG song you
picked is its match or its names' own: ``_Mine``) runs under that song's own
names and writes nothing to wanted.txt: no second song for UG's spelling of
it, and no new source for a song from Spotify. A lookup and a removal of the
same song never join (``jobs.REMOVING``): they run in the order they were
asked for, and a lookup after a removal asks for the song again, as a
wanted.txt line does.

A pick from the picker is ``caracole review --song "A - T" --pick ARTIST/SONG``
(or ``--none --seen ARTIST/SONG…``), queued and answered like a fetch (to the
page's script, its job; to a form, its line on /jobs), and fetched after it
when asked: the server writes no overrides.toml itself. The candidates the
page showed must be the song's now, and the song's own request goes first.

A songbook form queues its ``caracole songbook`` command the same way
(songbooks.py): to a form, the answer is its line on /jobs; to the page's
script, its job, as a fetch's, which names the songbook it changes
(``songbook``: its name before and after); once the job is over, /jobs.json
gives it with the Songbooks section as the library page would draw it now
(``songbooks``: its HTML and the songbooks for the Select bar), which the
page puts in place of its own. A job says what it is about (``kind``: a
song's, a removal's, a songbook's), so the page shows each where it belongs.

A removal is asked on the song's card by the page's script: Remove… there
counts down five seconds, with Undo, while the card says what goes (the
question, answered as data: ``removal``), and only then sends the
confirmation, answered with the job, whose line the card shows, as a
fetch's: the job names its song even once the song is gone. Without
JavaScript, Remove… opens the question as a page, and the removal, confirmed,
goes back to the library page as it was left (``back``: its search, filters
and view, the part of its address after #, which the form sends along), at
the song's card (``song=ID``).

Searching reads, and sends no request: one search runs at a time, one asked
for meanwhile wins over the older ones still waiting (``superseded``: the
page asks again if it still wants it), and the offline indexes' answers are
kept a few minutes. A query of fewer than three letters (two in Chinese)
looks nowhere. Of gtptabs.com and MuseScore it reads only the tables their
sitemaps filled (``search.search_gtptabs``, ``search.search_musescore``), and
says why it left a site out (``skipped``): turned off, its index still empty,
MuseScore blocking caracole, or LaCuerda, which has no offline index at all.
"""

from __future__ import annotations

import itertools
import json
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlsplit

from caracole import db
from caracole.config import Config
from caracole.web import pages
from caracole.web.files import NotServed, read_library_file, read_written_page
from caracole.web.jobs import (
    REMOVING,
    Job,
    JobQueue,
    QueueFull,
    add_steps,
    fetch_steps,
    lookup_steps,
    remove_steps,
    review_steps,
)
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
from caracole.web.status import SongFacts, details_href, job_line

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.search import IndexFound, IndexHit, LibraryHit, SiteHit
    from caracole.songs import Song

MAX_BODY = 16 * 1024
TOKEN_HEADER = "x-caracole-form-token"  # /jobs.json's form token
MAX_ASKED = 50  # jobs one /jobs.json answer is asked about
LIMITS = {"artist": 200, "title": 300, "album": 300, "duration": 12}  # characters
PICK_LIMITS = {"ug": 300, "tab": 600}
QUERY_LIMIT = 200  # characters of a search
LIBRARY_HITS, INDEX_HITS, TABS_SHOWN, SITE_HITS = 5, 8, 24, 5
ARTIST_PAGE = 50  # an artist's songs /api/artist gives at a time
CACHE_SIZE, CACHE_SECONDS = 128, 300.0  # the offline index's answers kept
SEARCH_CHECK_STEPS = 20_000  # SQLite steps between two looks for a newer search, a millisecond or so
# The library page's own address after #, as its script writes it (URLSearchParams' characters alone).
_BACK = re.compile(r"[A-Za-z0-9%*._~+=&-]{0,512}")
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
    """``data``: the answer as JSON, for the page's script (``Accept: application/json``), if it has one."""

    status: int
    body: bytes = b""
    headers: list[tuple[str, str]] = field(default_factory=list)
    data: dict[str, Any] | None = None


def _html(status: int, html: str, *, csp: str = pages.PAGE_CSP) -> Response:
    return Response(status, html.encode("utf-8"), [("Content-Type", _HTML), ("Content-Security-Policy", csp)])


def _message(status: int, title: str, message: str) -> Response:
    response = _html(status, pages.message_page(title, message))
    response.data = {"error": message}
    return response


def _redirect(location: str, *extra: tuple[str, str]) -> Response:
    return Response(303, b"", [("Location", location), *extra])


def _json(status: int, data: Any) -> Response:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Response(status, body, [("Content-Type", "application/json; charset=utf-8")])


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


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
        self._ended: dict[int, tuple[int | None, SongFacts | None]] = {}  # job id -> its song's id and facts
        self._ended_lock = threading.Lock()
        self._searching = threading.Lock()  # one search at a time
        self._tickets = itertools.count(1)
        self._newest = 0  # the newest search asked for
        # A query's answer from the offline indexes, kept a while: (when, the answer, its songs and artists as
        # JSON, the hint, gtptabs.com's and MuseScore's pages).
        self._found: OrderedDict[str, tuple[float, IndexFound, list[dict[str, Any]], list[dict[str, Any]],
                                            str | None, list[SiteHit], list[SiteHit]]] = OrderedDict()
        self._song_forms: dict[tuple, tuple[frozenset[str], frozenset[str]]] = {}  # _Mine's, by a song's names

    def handle(self, request: Request) -> Response:
        response = self._route(request)
        if response.data is not None and _wants_json(request):  # the page's script: no redirect, no page
            response = _json(200 if response.status == 303 else response.status, response.data)
        return self.finish(response)

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
        data = _wants_json(request) or path.startswith("/api/")  # a page's script asks: it reads JSON
        if self._session is not None and not self._signed_in(request):
            if method == "POST" and path == "/login":
                return self._sign_in(request)
            if path.startswith("/api/"):  # data, whoever asks: no page to sign in on
                return _json(401, {"error": "Sign in first: reload the page, and sign in with the access token.",
                                   "reload": True})
            if method in ("GET", "HEAD"):
                signed_out = _html(401, pages.sign_in_page(self.csrf))
                signed_out.data = {"error": "Sign in again: reload the page.", "reload": True}
                return signed_out
            refused = _message(401, "Sign in first", "Sign in with the access token first.")
            refused.data = {**(refused.data or {}), "reload": True}
            return refused
        if method in ("GET", "HEAD"):
            if path in ("/", "/index.html"):
                return self._library()
            if path == "/lookup":
                from caracole.icons import page_icons
                from caracole.web.lookup_page import LOOKUP_CSP, lookup_page

                return _html(200, lookup_page(self.csrf, page_icons(self.cfg.cache_dir)), csp=LOOKUP_CSP)
            if path == "/jobs":
                return self._jobs_page(parse_qs(urlsplit(request.target).query))
            if path == "/jobs.json":
                return self._jobs_json(request)
            if path == "/review":
                return self._picker(parse_qs(urlsplit(request.target).query).get("song", [""])[0])
            if path.startswith("/api/") and not own_page_read(request.headers):
                return _json(403, {"error": "This came from another site, so caracole refused it."})
            if path == "/api/search":
                return self._search(parse_qs(urlsplit(request.target).query).get("q", [""])[0])
            if path == "/api/artist":
                asked = parse_qs(urlsplit(request.target).query)
                return self._artist(asked.get("key", [""])[0].strip(), asked.get("offset", ["0"])[0].strip())
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
            handler = {"/request": self._request, "/fetch": self._fetch, "/review": self._review,
                       "/remove": self._remove}.get(path)
            if path == "/lookup":
                handler = lambda form: self._lookup(form, wants_json=data)  # noqa: E731
            if handler is None and path.startswith("/songbook/"):
                handler = self._songbook_form(path)
            if handler is None:
                return _message(404, "Not here", "There's nothing to send to at this address.")
            form = self._form(request, page="the page" if path == "/lookup" else "the library")
            return form if isinstance(form, Response) else handler(form)
        return Response(405, b"", [("Allow", "GET, HEAD, POST")])

    def _form(self, request: Request, *, page: str = "the library") -> dict[str, str] | Response:
        """The fields of a POSTed form, or why it is refused; a form token older than the server says to
        reload ``page``, and tells a page's script so (``reload``)."""
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
            refused = _message(403, "Refused", "This form is older than the server, or not from its pages: "
                                               f"reload {page} and try again.")
            refused.data = {**(refused.data or {}), "reload": True}
            return refused
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
        # Lax: a sheet viewer's links (its PDF, the library) are navigations from the origin of its
        # sandbox, another site's to the browser, which a Strict cookie wouldn't go with. Lax still
        # keeps it from other sites' POSTs and subresources; no GET changes anything, and every
        # write must pass the cross-origin check and carry the form token anyway (_form).
        cookie = f"{SESSION_COOKIE}={self._session}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"
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

        jobs = self.queue.snapshot()
        try:
            with closing(self._connect()) as conn:
                busy = _song_ids(conn, self.queue.fetching_keys())
                held = frozenset(s.id for s in list_songs(conn) if review_first(s, overrides))
                removing = _song_ids(conn, {job.song_key.removeprefix(REMOVING) for job in jobs
                                            if job.active and job.song_key.startswith(REMOVING)})
                # Every request on its way, which the page's script shows where it belongs (``kind``): a
                # song's on its card, a removal's on its song's, a songbook's change on its songbook's.
                active = tuple(self._views(conn, overrides, jobs, only=[j for j in jobs if j.active]))
                controls = WebControls(self.csrf, busy, self.queue.active_count(), held, removing=removing,
                                       jobs=active)
                html = build_library_page(conn, self.cfg, overrides, datetime.now(UTC).replace(microsecond=0),
                                          controls=controls)
        except (sqlite3.Error, OSError) as e:  # DatabaseTooNew is an sqlite3.DatabaseError
            return _message(503, "The database can't be read", f"The database can't be read: {e}")
        # The page's own CSP is in its meta tag; a header CSP would apply on top of it.
        return _html(200, html, csp=_FRAMES)

    # --- the requests --------------------------------------------------------------------------

    def _jobs_page(self, query: dict[str, list[str]]) -> Response:
        """Every request, a line each, its output open only when asked for (``?job=N``)."""
        try:
            opened = int(query.get("job", [""])[0])
        except ValueError:
            opened = None
        jobs = self.queue.snapshot()
        facts: dict[int, SongFacts | None] = {}
        books: dict[int, str | None] = {}
        try:
            overrides = _overrides_or_none(self.cfg)
            with closing(self._connect()) as conn:
                self._forget_ended(jobs)
                facts = {job.id: self._song_of(conn, overrides, job)[1] for job in jobs}
                books = {job.id: _songbook_page(conn, job) for job in jobs}
        except (sqlite3.Error, OSError):  # the lines say only how the jobs went, then
            pass
        lines = {job.id: job_line(job, facts.get(job.id), ahead=_ahead(jobs, job), songbook_page=books.get(job.id))
                 for job in jobs}
        still = query.get("refresh") == ["0"]
        return _html(200, pages.jobs_page(jobs, lines, opened=opened, refresh=not still, picks=self._picks(jobs),
                                          csrf=self.csrf))

    def _jobs_json(self, request: Request) -> Response:
        """The requests for the page's script; refused to anything else, as a write would be."""
        if not cross_origin_ok("POST", request.headers, request.headers.get("host")):  # checked as a write
            return _message(403, "Refused", "This came from another site, so caracole refused it.")
        if not same_token(request.headers.get(TOKEN_HEADER), self.csrf):
            return _message(403, "Refused", "caracole serve has restarted since this page was opened: reload it.")
        asked = _job_ids(parse_qs(urlsplit(request.target).query).get("jobs"))
        from caracole.overrides import OverridesError, load_overrides

        try:
            overrides = load_overrides(self.cfg.overrides_file)
        except OverridesError as e:
            return _message(503, "overrides.toml can't be read",
                            f"overrides.toml can't be read: {e}. Fix it, then reload this page.")
        jobs = self.queue.snapshot()
        only = None if asked is None else [job for job in jobs if job.id in asked]
        try:
            with closing(self._connect()) as conn:
                self._forget_ended(jobs)
                views = self._views(conn, overrides, jobs, only=only, cards=asked or frozenset())
        except (sqlite3.Error, OSError) as e:
            return _message(503, "The database can't be read", f"The database can't be read: {e}")
        return _json(200, {"active": sum(j.active for j in jobs), "jobs": views})

    def _views(self, conn: sqlite3.Connection, overrides: Overrides | None, jobs: list[Job], *,
               only: list[Job] | None = None, cards: frozenset[int] = frozenset()) -> list[dict[str, Any]]:
        """Each job (of ``only``, else every one) as the page's script reads it: its song, its line and,
        for a job in ``cards`` that is over, its song's card as the page draws it now, or, for a
        songbook's change, the Songbooks section (``songbooks``).

        ``jobs`` is the whole queue, newest first, for the jobs ahead of a queued one;
        ``overrides`` None (overrides.toml unreadable) leaves the cards out.
        """
        from caracole.library_page import song_cards
        from caracole.songs import get_song

        views = []
        section: dict[str, Any] | None = None  # drawn once, for every songbook job that asks
        for job in jobs if only is None else only:
            song_id, facts = self._song_of(conn, overrides, job)
            view = _view(job, jobs, song_id, facts, songbook_page=_songbook_page(conn, job))
            if job.id in cards and not job.active and "songbook" in view and overrides is not None:
                section = section or self._songbooks(conn, overrides)
                view["songbooks"] = section
            if job.id in cards and not job.active and song_id is not None and overrides is not None:
                try:
                    song = get_song(conn, song_id)  # as it is now
                except KeyError:
                    views.append(view)
                    continue
                card = song_cards(conn, self.cfg, overrides, datetime.now(UTC).replace(microsecond=0), [song])[0]
                card["fetchable"] = not review_first(song, overrides)
                view["card"] = card
            views.append(view)
        return views

    def _songbooks(self, conn: sqlite3.Connection, overrides: Overrides) -> dict[str, Any]:
        """The Songbooks section as the library page draws it now (``html``; hidden, with no songbook), and
        the songbooks for its Select bar (``books``)."""
        from caracole.library_page import WebControls, songbooks_section

        html, books = songbooks_section(conn, self.cfg, overrides, WebControls(self.csrf))
        return {"html": html, "books": books}

    def _song_of(self, conn: sqlite3.Connection, overrides: Overrides | None,
                 job: Job) -> tuple[int | None, SongFacts | None]:
        """The id of the job's song, and what its line needs to know of it; None while the library has
        no such song.

        A fetch that is over and left no sheet is "Not found" only if it looked the
        song up during the job (``ug.fetch.checked_since``): a cooldown, a block, a
        spent budget or an error looks nothing up, and the song isn't missing. A job
        that is over doesn't change, so its answer is worked out once (``_ended``).
        """
        over = not job.active
        if over:
            with self._ended_lock:
                ended = self._ended.get(job.id)
            if ended is not None:
                return ended
        from caracole.library_page import sheet_href
        from caracole.songs import find_song

        removal = job.song_key.startswith(REMOVING)
        song = find_song(conn, job.song_key.removeprefix(REMOVING))
        facts = None
        if song is not None:
            ignored = song.status == "ignored" or (overrides is not None and song.key in overrides.ignore)
            sheet = sheet_href(self.cfg.library_dir, song)
            checked_now = False
            if over and job.fetching and not sheet and job.started_at is not None:
                from caracole.ug.fetch import checked_since

                checked_now = checked_since(conn, song, job.started_at) or (
                    bool(job.stages) and _nothing_to_ask(conn, song, overrides))
            picker = None
            if song.review and not ignored:
                from caracole.review import candidates_of

                picker = f"review?song={song.id}" if candidates_of(song) else None  # the card's, or its page
            facts = SongFacts(sheet=sheet, review=bool(song.review), not_found=song.match_decision == "not_found",
                              checked_now=checked_now, ignored=ignored, picker=picker)
        # A removal's song is gone once it is done: the job knows which it was.
        answer = (song.id if song is not None else job.song_id if removal else None, facts)
        if over and overrides is not None:  # with overrides.toml unreadable, "ignored" isn't known
            with self._ended_lock:
                self._ended[job.id] = answer
        return answer

    def _forget_ended(self, jobs: list[Job]) -> None:
        """Let go of the jobs the queue no longer remembers (``jobs``: the whole queue)."""
        kept = {job.id for job in jobs}
        with self._ended_lock:
            for job_id in [i for i in self._ended if i not in kept]:
                del self._ended[job_id]

    def _queued(self, job: Job, location: str | None = None) -> Response:
        """A request queued: to the browser, its line on /jobs (its output open, unless ``location`` says
        where else); to the page's script, the job itself."""
        response = _redirect(location or f"/{details_href(job.id)}")
        response.data = {"job": self._job_view(job)}
        return response

    def _job_view(self, job: Job) -> dict[str, Any]:
        """A job just queued, as /jobs.json gives it to the library page's script."""
        jobs = self.queue.snapshot()
        job = next((j for j in jobs if j.id == job.id), job)
        try:
            with closing(self._connect()) as conn:
                return self._views(conn, _overrides_or_none(self.cfg), jobs, only=[job])[0]
        except (sqlite3.Error, OSError):  # the job is queued all the same
            return _view(job, jobs, None, None)

    def _picker(self, song_field: str) -> Response:
        """A song in review's picker, on a page of its own."""
        from caracole.overrides import OverridesError, load_overrides
        from caracole.songs import get_song

        try:
            song_id = int(song_field)
        except ValueError:
            return _message(400, "Not a song", "Which song? The address names none.")
        try:
            overrides = load_overrides(self.cfg.overrides_file)
            with closing(self._connect()) as conn:
                song = get_song(conn, song_id)
                pick = _pick(conn, song, overrides, search=True)
        except (KeyError, OverflowError):  # OverflowError: an id beyond any SQLite integer
            return _message(404, "No such song", "That song isn't in the library.")
        except OverridesError as e:
            return _message(503, "overrides.toml can't be read", f"overrides.toml can't be read: {e}.")
        except (sqlite3.Error, OSError) as e:
            return _message(503, "The database can't be read", f"The database can't be read: {e}")
        if pick is None and (song.status == "ignored" or song.key in overrides.ignore):
            return _message(409, "Ignored", f"{song.display} is ignored in overrides.toml.")
        if pick is None and song.review:
            return _message(409, "Nothing to pick", f"{song.display} has no candidates to pick: caracole review "
                                                    "offers a pin or an ignore.")
        if pick is None:
            return _message(409, "Nothing to pick", f"{song.display} doesn't need review: there's nothing to pick.")
        if not pick.choices:
            return _message(409, "Nothing to pick", f"caracole search finds nothing close to {song.display} in the "
                                                    "offline Ultimate Guitar index.")
        return _html(200, pages.review_page(pick, self.csrf))

    def _picks(self, jobs: list[Job]) -> dict[str, pages.Pick]:
        """The songs of finished requests that wait for a pick now, by key; none when the database or
        overrides.toml can't be read: the requests page still shows the requests."""
        from caracole.overrides import OverridesError, load_overrides
        from caracole.songs import find_song

        keys = {job.song_key for job in jobs if not job.active}
        if not keys:
            return {}
        picks = {}
        try:
            overrides = load_overrides(self.cfg.overrides_file)
            with closing(self._connect()) as conn:
                for key in sorted(keys):
                    song = find_song(conn, key)
                    pick = _pick(conn, song, overrides) if song is not None else None
                    if pick is not None:
                        picks[key] = pick
        except (OverridesError, sqlite3.Error, OSError):
            return {}
        return picks

    def _file(self, path: str) -> Response:
        try:
            if not path.startswith("/"):
                raise NotServed(path)
            page = written_pages().get(path.rsplit("/", 1)[-1])
            if page is not None:
                try:
                    return self._written_page(path[1:], page)
                except NotServed:  # index.html links it all the same: say why it isn't sent
                    return _message(404, "Not sent", page.refused)
            data, kind, download = read_library_file(self.cfg.library_dir, path[1:],
                                                     hidden=(self.cfg.state_dir, self.cfg.cache_dir))
        except NotServed:
            return _message(404, "Not found", "There's no such page or file in the library.")
        headers = [("Content-Type", kind)]
        if download:
            headers.append(("Content-Disposition", "attachment"))
        return Response(200, data, headers)

    def _written_page(self, path: str, page: WrittenPage) -> Response:
        """A page caracole wrote into the library, while it is still as written
        (``files.read_written_page``), with its kind's Content-Security-Policy; NotServed otherwise."""
        library_dir = self.cfg.library_dir
        try:
            with closing(self._connect()) as conn:
                data = read_written_page(library_dir, path, lambda parts: page.written(conn, library_dir, parts),
                                         hidden=(self.cfg.state_dir, self.cfg.cache_dir))
        except (sqlite3.Error, OSError) as e:  # DatabaseTooNew is an sqlite3.DatabaseError
            return _message(503, "The database can't be read", f"The database can't be read: {e}")
        csp = f"{page.csp(data)}; {_FRAMES}"  # the policy of these very bytes, not this caracole's
        return Response(200, data, [("Content-Type", _HTML), ("Content-Security-Policy", csp)])

    # --- the forms ------------------------------------------------------------------------------

    def _songbook_form(self, path: str) -> Callable[[dict[str, str]], Response] | None:
        """The handler of a songbook form (songbooks.py): it queues its caracole songbook command."""
        from caracole.web.songbooks import ROUTES

        if path not in ROUTES:
            return None

        def handle(form: dict[str, str]) -> Response:
            from caracole.web.songbooks import FormRefused, songbook_job

            try:
                job = songbook_job(path, form, library_dir=self.cfg.library_dir, connect=self._connect)
            except FormRefused as e:
                return _message(e.status, e.title, e.message)
            except (sqlite3.Error, OSError) as e:
                return _message(503, "The database can't be read", f"The database can't be read: {e}")
            try:
                queued, _ = self.queue.submit(job.title, job.key, job.steps)
            except QueueFull:
                return _message(503, "The queue is full", "The queue is full: try again once it empties.")
            return self._queued(queued, f"/jobs#job-{queued.id}")  # its songbook's card says how it goes

        return handle

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
                                       fetching=fetch, note=note, display=display)
        except QueueFull:
            return _message(503, "The queue is full",
                            f"{note} The queue is full, so nothing else was queued: the nightly run looks for "
                            "the song, or request it again once the queue empties.")
        return self._queued(job)

    def _fetch(self, form: dict[str, str]) -> Response:
        """Look a song of the library up now: one ``caracole get``, as Fetch it now and the lookup page do."""
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
        except (KeyError, OverflowError):  # OverflowError: an id beyond any SQLite integer
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
                                       fetching=True, display=song.display)
        except QueueFull:
            return _message(503, "The queue is full", "The queue is full: try again once it empties.")
        return self._queued(job)

    def _remove(self, form: dict[str, str]) -> Response:
        """Say what removing a song takes and leaves, and ask; confirmed, queue ``caracole remove --yes``
        and go back to the library, at the song's card, as ``back`` left it (``_library_at``).

        The confirmation carries the song's key: a song id the database gave
        another song since the question was asked removes nothing. To the library
        page's script, the question is data (``removal``: the song's key, what goes
        in one sentence, ``brief``, and whole), which its card says while it counts
        down to Undo; the confirmation, the job, whose line its card shows: the
        page stays where it is. The question page is for a browser without it.
        """
        from caracole.removal import brief, describe, plan_removal
        from caracole.songs import get_song

        try:
            song_id = int(form.get("song", ""))
        except ValueError:
            return _message(400, "Not a song", "Which song? The form names none.")
        confirmed = form.get("confirm") == "1"
        back = _back(form.get("back", ""))
        try:
            with closing(self._connect()) as conn:
                song = get_song(conn, song_id)
                plan = None if confirmed else plan_removal(conn, self.cfg, song)
        except KeyError:
            return _message(404, "No such song", "That song isn't in the library: removed already, maybe.")
        except (sqlite3.Error, OSError) as e:
            return _message(503, "The database can't be read", f"The database can't be read: {e}")
        if plan is not None:
            goes, stays, notes = describe(plan, self.cfg)
            asked = _html(200, pages.remove_page(song.display, song.id, song.key, self.csrf, goes, stays, notes,
                                                 waiting=self.queue.active_count(), back=back,
                                                 library=_library_at(back, song.id)))
            asked.data = {"removal": {"song": song.id, "key": song.key, "display": song.display,
                                      "brief": brief(plan), "goes": goes, "stays": stays, "notes": notes}}
            return asked
        if form.get("key") != song.key:
            return _message(409, "Not that song", "The library changed since this page was made, so nothing was "
                                                  "removed: reload the library and try again.")
        try:
            job, _ = self.queue.submit(f"Remove {song.display}", REMOVING + song.key, remove_steps(song.display),
                                       display=song.display, song_id=song.id)
        except QueueFull:
            return _message(503, "The queue is full", "The queue is full: try again once it empties.")
        return self._queued(job, _library_at(back, song.id))  # its card says Removing…, then Removed

    def _review(self, form: dict[str, str]) -> Response:
        """A song in review's answer, from the picker: ``caracole review --song`` queued with it.

        ``pick`` is a candidate's ARTIST/SONG, fetched at once with ``fetch``, or
        "none", which rejects the candidates ``shown``. They must be the song's
        candidates now: the nightly run may have matched it again since the page was
        loaded. A song not found takes one of its search hits, the same way. The
        song's own request, if one waits or runs, goes first.
        """
        from caracole.overrides import OverridesError, load_overrides
        from caracole.songs import get_song

        try:
            song_id = int(form.get("song", ""))
        except ValueError:
            return _message(400, "Not a song", "Which song? The form names none.")
        pick = form.get("pick", "").strip()
        try:
            overrides = load_overrides(self.cfg.overrides_file)
        except OverridesError as e:
            return _message(503, "overrides.toml can't be read", f"overrides.toml can't be read: {e}.")
        try:
            with closing(self._connect()) as conn:
                song = get_song(conn, song_id)
                offered = _pick(conn, song, overrides, search=True)
        except (KeyError, OverflowError):  # OverflowError: an id beyond any SQLite integer
            return _message(404, "No such song", "That song isn't in the library.")
        except (sqlite3.Error, OSError) as e:
            return _message(503, "The database can't be read", f"The database can't be read: {e}")
        if song.status == "ignored" or song.key in overrides.ignore:
            return _message(409, "Ignored", f"{song.display} is ignored in overrides.toml.")
        if offered is None:
            return _message(409, "Nothing to pick", f"{song.display} doesn't need review any more: reload the "
                                                    "library to see where it stands.")
        refs = [str(c["ref"]) for c in offered.choices]
        if not pick:
            return _message(400, "No answer", "Pick a candidate, or None of these.")
        if form.get("shown", "").split() != refs or not refs:
            return _message(409, "The candidates changed",
                            f"caracole matched {song.display} again since this page was loaded, and its "
                            "candidates changed: reload the library and pick again.")
        if pick == "none" and offered.search:
            return _message(400, "Not an answer", "A song not found takes one of its search hits, or nothing.")
        if pick != "none" and pick not in refs:
            return _message(400, "Not a candidate", f"{pick} isn't one of its candidates.")
        if pick == "none":
            title, steps, fetch = f"None of these for {song.display}", review_steps(song.display, seen=refs), False
        else:
            fetch = form.get("fetch") in ("1", "on", "yes")
            title, steps = f"Pick {pick} for {song.display}", review_steps(song.display, pick=pick)
            if fetch:  # caracole review matched it again already
                title += ", and fetch it"
                steps += [step for step in fetch_steps(song.display) if step[1][0] != "match"]
        try:  # never into the song's own request, nor after its fetch: checked under the queue's lock
            job, new = self.queue.submit(title, song.key, steps, fetching=fetch, join=False, display=song.display)
        except QueueFull:
            return _message(503, "The queue is full", "The queue is full: try again once it empties.")
        if not new:
            return _message(409, "Wait for its request",
                            f"A request for {song.display} is waiting or running: pick once it ends.")
        return self._queued(job, f"/jobs#job-{job.id}")  # the card's line says how it goes, as Fetch now's

    # --- a song looked up now, and search as you type ----------------------------------------------

    def _lookup(self, form: dict[str, str], *, wants_json: bool) -> Response:
        """The song you picked on the lookup page, looked up now: a song of your library as it is (``song``,
        its id; or the one your pick or its name is already), else a new one, in wanted.txt at once."""
        from caracole.overrides import OverridesError, tab_id_from_url

        refused = _message  # a page's script hears it as data (handle)

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
        found = self._library_song(form, (artist_key, song_key) if pick["ug"] else None)
        if isinstance(found, tuple):
            return refused(*found)
        if found is not None:  # the song as your library has it: no second song, and no new source for it
            artist, title, album, duration_ms, key = found.artist, found.title, None, None, found.key
            note, display = f"In your library as {found.display}.", found.display
        else:
            written = self._wanted_line(form)
            if len(written) == 3:
                return refused(*written)
            line, note = written
            artist, title, album, duration_ms, key = line.artist, line.title, line.album, line.duration_ms, line.identity
            display = f"{artist} - {title}"
        steps = lookup_steps(artist, title, album=album, duration_ms=duration_ms,
                             ug=pick["ug"] or None, tab=pick["tab"] or None)
        try:
            job, _ = self.queue.submit(f"Fetch {artist} - {title}", key, steps, fetching=True, note=note,
                                       display=display)
        except QueueFull:
            return refused(503, "The queue is full", f"{note} The queue is full, so it wasn't looked up now: the "
                                                     "nightly run looks for it, or ask again once the queue empties.")
        if wants_json:  # the lookup page follows its address; the library page, its line (view)
            return _json(202, {"job": job.id, "url": f"/api/jobs/{job.id}", "view": self._job_view(job)})
        return _redirect(f"/lookup?job={job.id}")

    def _library_song(self, form: dict[str, str], ug: tuple[str, str] | None) -> Song | None | tuple[int, str, str]:
        """The library song a lookup is about: the one ``song`` names; else the one your UG pick is (matched
        to it, or by its names); else the one of the form's artist and title. None for a song new to the
        library; (status, title, message) when it can't be told."""
        from caracole.normalize import identity_key
        from caracole.songs import find_song, get_song, list_songs

        try:
            with closing(self._connect()) as conn:
                if form.get("song", "").strip():
                    try:
                        return get_song(conn, int(form["song"]))
                    except ValueError:
                        return 400, "Not a song", "Which song? The form names none."
                    except KeyError:
                        return 404, "No such song", "That song isn't in the library."
                artist, title = form.get("artist", "").strip(), form.get("title", "").strip()
                if ug is not None:
                    found = _Mine(list_songs(conn), self._song_forms).song_for(*ug, artist, title)
                    if found is not None:
                        return found
                if artist and title:
                    return find_song(conn, identity_key(artist, title))
                return None
        except (sqlite3.Error, OSError) as e:
            return 503, "The database can't be read", f"The database can't be read: {e}"

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
        """The search's answer (``search.found``'s): your songs, the artists the query names, the index's
        songs, which leads, and the row Enter may act on (``best``: a song of yours by its id, or an
        Ultimate Guitar song by its keys; None for none). A song of your library comes as its card
        has it (``_rows``)."""
        from caracole.search import LibraryHit, found, search_gtptabs, search_library, search_musescore
        from caracole.songs import list_songs

        mine = search_library(conn, q, LIBRARY_HITS)
        skipped = self._skipped(conn)
        left_out = {s["source"] for s in skipped}
        cached = self._found.get(q)
        if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
            index_found, index, artists, hint, gtptabs, musescore = cached[1:]
        else:
            index_found, index, artists, hint = self._index_hits(conn, q)
            gtptabs = search_gtptabs(conn, q, SITE_HITS) if "gtptabs" not in left_out else []
            musescore = search_musescore(conn, q, SITE_HITS) if "musescore" not in left_out else []
            self._found[q] = (time.monotonic(), index_found, index, artists, hint, gtptabs, musescore)
            while len(self._found) > CACHE_SIZE:
                self._found.popitem(last=False)
        answer = found(mine, index_found)
        songs = list_songs(conn)
        library, hits = self._rows(conn, mine, index, songs)
        best = answer.best
        pick = None if best is None else (
            {"library": best.song.id} if isinstance(best, LibraryHit) else {"ug": f"{best.artist_key}/{best.song_key}"})
        return {"query": q, "library": library, "index": hits, "artists": artists, "lead": answer.lead,
                "best": pick, "hint": hint,
                "gtptabs": self._gtptabs_rows(conn, gtptabs if "gtptabs" not in left_out else [], songs),
                "musescore": [{"source": h.source, "title": h.title, "url": h.url, "score": h.score}
                              for h in (musescore if "musescore" not in left_out else [])],
                "skipped": skipped}

    def _gtptabs_rows(self, conn: sqlite3.Connection, hits: Sequence[SiteHit], songs: list[Song]) -> list[dict[str, Any]]:
        """gtptabs.com's pages as the page draws them; one your library has (``_Mine``, by its names) names it,
        so that Get it looks it up as that song."""
        from caracole.library_page import result_cards

        owners_of = _Mine(songs, self._song_forms)
        owners = [owners_of.song_for(h.artist_key, h.title_key, h.artist, h.title) for h in hits]
        cards = result_cards(conn, self.cfg, list({s.id: s for s in owners if s}.values()))
        return [{"source": h.source, "artist": h.artist, "title": h.title, "url": h.url, "uploads": h.uploads,
                 "score": h.score, "via": h.via, "song": song.id if song else None,
                 "library": {"id": song.id, "artist": song.artist, "title": song.title, "display": song.display,
                             "links": cards[song.id]["links"]} if song else None}
                for h, song in zip(hits, owners)]

    def _skipped(self, conn: sqlite3.Connection) -> list[dict[str, str]]:
        """The sites a search leaves out, and why: one turned off, one whose index the nightly run hasn't
        filled yet (MuseScore's, while it blocks caracole), and LaCuerda, which has no offline index."""
        from caracole.health import get_state

        left = []
        for source, name, table in (("gtptabs", "gtptabs.com", "gtptabs_index"),
                                    ("musescore", "MuseScore", "musescore_index")):
            if not self.cfg.provider(source).enabled:
                why = "turned off in caracole.toml"
            elif conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
                continue
            elif source == "musescore" and get_state(conn, source).strikes:
                why = "MuseScore is blocking caracole, so its index is empty"
            else:
                why = "its index is empty: the nightly run reads its sitemaps"
            left.append({"source": source, "name": name, "why": why})
        left.append({"source": "lacuerda", "name": "LaCuerda", "why": "no offline index: Get it asks LaCuerda too"})
        return left

    def _rows(self, conn: sqlite3.Connection, mine: Sequence[LibraryHit], index: list[dict[str, Any]],
              songs: list[Song] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Your songs and the index's, as the page draws them. A song of your library comes as its card
        has it (``result_cards``): its files (``links``, its viewer the primary one), where its sheet
        came from, its key; and the files its sheet can be read in on the page (``files``). An index
        song your library has (``_Mine``) names it, with its links."""
        from caracole.get import readable_files
        from caracole.library_page import result_cards
        from caracole.songs import list_songs

        owners_of = _Mine(songs if songs is not None else list_songs(conn), self._song_forms)
        owners = [owners_of.song_for(*hit["ug"].split("/", 1), hit["artist"], hit["title"]) for hit in index]
        cards = result_cards(conn, self.cfg, list({s.id: s for s in [h.song for h in mine] + owners if s}.values()))
        library = [{"id": h.song.id, "display": h.song.display, "artist": h.song.artist, "title": h.song.title,
                    "status": h.song.status, "review": bool(h.song.review), "score": h.score, "via": h.via,
                    "files": readable_files(conn, self.cfg.library_dir, h.song), **cards[h.song.id]}
                   for h in mine]
        hits = [{**hit, "song": song.id if song else None,
                 "library": {"id": song.id, "artist": song.artist, "title": song.title, "display": song.display,
                             "links": cards[song.id]["links"]} if song else None}
                for hit, song in zip(index, owners)]
        return library, hits

    def _index_hits(self, conn: sqlite3.Connection, q: str) -> tuple[IndexFound, list[dict[str, Any]],
                                                                       list[dict[str, Any]], str | None]:
        from caracole.search import IndexFound, bare_id_hint, find_index
        from caracole.ug.index import index_count

        if index_count(conn) == 0:
            return (IndexFound(), [], [],
                    "The offline Ultimate Guitar index is empty: run caracole index build once (about 10 minutes).")
        answer = find_index(conn, q, songs=INDEX_HITS)
        artists = [{"artist_key": a.artist_key, "artist": a.artist, "score": a.score, "songs": a.songs, "tabs": a.tabs,
                    "top": [{"artist": h.artist, "title": h.title, "ug": f"{h.artist_key}/{h.song_key}",
                             "counts": dict(h.counts)} for h in a.top]}
                   for a in answer.artists]
        index = [self._hit_json(conn, h) for h in answer.songs]
        return answer, index, artists, bare_id_hint(q, [*answer.songs, *answer.artists])

    @staticmethod
    def _hit_json(conn: sqlite3.Connection, h: IndexHit) -> dict[str, Any]:
        """An Ultimate Guitar song of the index as the page draws it: its names, its tabs per type and
        its first ``TABS_SHOWN`` tabs, chords first; ``no_ones`` when its artist is one of UG's ``misc-…``
        keys, no one's name (``search.no_ones``)."""
        from caracole.search import TYPE_ORDER, no_ones
        from caracole.ug.lookup import song_tabs

        def rank(t) -> tuple:
            return (TYPE_ORDER.index(t.type) if t.type in TYPE_ORDER else len(TYPE_ORDER), t.label is not None,
                    t.tab_id)

        return {"artist": h.artist, "title": h.title, "ug": f"{h.artist_key}/{h.song_key}", "counts": dict(h.counts),
                "score": h.score, "url": h.url, "labels": list(h.labels), "via": h.via, "no_ones": no_ones(h.artist_key),
                "tabs": [{"id": t.tab_id, "type": t.type, "label": t.label, "url": t.url}
                         for t in sorted(song_tabs(conn, h.artist_key, h.song_key), key=rank)[:TABS_SHOWN]]}

    def _artist(self, key: str, offset: str) -> Response:
        """An artist of the offline index, for the lookup page: their songs, ``ARTIST_PAGE`` from
        ``offset``, most tabbed first, and yours by them (``search.library_by_artist``). It only reads,
        one at a time with the searches."""
        if not key:
            return _json(400, {"error": "Which artist? The address names none."})
        if not (offset.isascii() and offset.isdigit()):
            return _json(400, {"error": "That offset isn't a number."})
        with self._searching:
            try:
                with closing(self._connect()) as conn:
                    return self._artist_songs(conn, key, int(offset))
            except (sqlite3.Error, OSError) as e:
                return _json(503, {"error": f"The database can't be read: {e}"})

    def _artist_songs(self, conn: sqlite3.Connection, key: str, offset: int) -> Response:
        from caracole.search import LibraryHit, artist_songs, index_artist, library_by_artist
        from caracole.songs import list_songs

        named = index_artist(conn, key)
        if named is None:
            return _json(404, {"error": "The offline Ultimate Guitar index has no such artist."})
        hits, total = artist_songs(conn, key, limit=ARTIST_PAGE, offset=offset)
        songs = list_songs(conn)
        theirs = [LibraryHit(s, 100.0, "artist") for s in library_by_artist(songs, named.artist, key)]
        library, index = self._rows(conn, theirs, [self._hit_json(conn, h) for h in hits], songs)
        return _json(200, {"artist_key": key, "artist": named.artist, "songs": index, "total": total,
                           "offset": offset, "tabs": named.tabs, "library": library})


FORMS_KEPT = 10_000  # songs whose name forms _Mine keeps between two searches


class _Mine:
    """Your library's songs, to tell which one an Ultimate Guitar song of the offline index is.

    As ``caracole search --add`` tells it (commands/search.py): the song matched
    to it (an accepted or pinned match, a variant counted as its song), else the
    song its names are, by identity key or by ``normalize.name_forms`` (UG's
    "Acdc", "R E M" and "Song Dongye" are your AC/DC, R.E.M. and 宋冬野). A
    review's keys are only a candidate's, often a cover by another artist, so
    they make no song of yours. ``forms`` keeps each song's forms, by its names.
    """

    def __init__(self, songs: list[Song], forms: dict[tuple, tuple[frozenset[str], frozenset[str]]]):
        from caracole.normalize import split_variant

        self.songs = sorted(songs, key=lambda s: s.id)
        self.by_key = {s.key: s for s in self.songs}
        self.matched: dict[tuple[str, str], Song] = {}
        for s in self.songs:
            if s.match_decision in ("accept", "pinned") and s.match_artist_key and s.match_song_key:
                self.matched.setdefault((s.match_artist_key, split_variant(s.match_song_key)[0]), s)
        self.forms = forms

    def song_for(self, artist_key: str, song_key: str, artist: str, title: str) -> Song | None:
        from caracole.normalize import compact, identity_key, split_variant

        base = split_variant(song_key)[0]
        found = self.matched.get((artist_key, base)) or self.by_key.get(identity_key(artist, title))
        if found is not None:
            return found
        wanted_artist, wanted_title = compact(artist_key), compact(base)
        for song in self.songs:
            artists, titles = self._forms_of(song)
            if wanted_artist in artists and wanted_title in titles:
                return song
        return None

    def _forms_of(self, song: Song) -> tuple[frozenset[str], frozenset[str]]:
        from caracole.normalize import clean_title, compact, name_forms

        names = (song.artist, tuple(song.artists), song.title)
        forms = self.forms.get(names)
        if forms is None:
            if len(self.forms) >= FORMS_KEPT:
                self.forms.clear()
            artists = frozenset(compact(f) for a in dict.fromkeys(song.artists or [song.artist]) for f in name_forms(a))
            forms = (artists, frozenset(compact(f) for f in name_forms(clean_title(song.title))))
            self.forms[names] = forms
        return forms


def review_first(song: Song, overrides: Overrides) -> bool:
    """Whether ``caracole fetch --song`` would refuse the song as needing review first (commands/fetch.py),
    and ``caracole get`` would find no sheet to fetch for it.

    A review that its artist's UG page settles can be fetched, and so can one
    that overrides.toml settles (``[match]``, ``[pin]``): the lookup's match
    stage (the job's ``caracole match``, before a pick's fetch) reads it first. A ``[reject]`` settles it only when it
    names every candidate the song has now: after None of these, the rematch
    may leave the song in review with candidates it hadn't shown, which the
    entry doesn't name, and ``caracole fetch --song`` would refuse it.
    """
    from caracole.review import candidates_of
    from caracole.ug.fetch import needs_artist_page

    if song.match_decision != "review" or needs_artist_page(song):
        return False
    if song.key in overrides.match or song.key in overrides.pin:
        return False
    rejected = overrides.reject.get(song.key)
    return rejected is None or not all((c["artist_key"], c["song_key"]) in rejected for c in candidates_of(song))


def _pick(conn: sqlite3.Connection, song: Song, overrides: Overrides, *, search: bool = False) -> pages.Pick | None:
    """What a song's picker offers: a review's candidates; for a song not found, with ``search``, what
    ``caracole search`` finds for it (a moment's work, for the picker's page alone), or without, no
    choices yet. None for a song with nothing to pick: ignored, settled, or a review without candidates."""
    from caracole.library_page import review_choices
    from caracole.normalize import clean_title
    from caracole.review import search_candidates

    if song.status == "ignored" or song.key in overrides.ignore:
        return None
    title = clean_title(song.title)
    if song.review:
        choices = review_choices(conn, song)
        return pages.Pick(song.id, song.display, title, song.artist, tuple(choices)) if choices else None
    if song.match_decision != "not_found":
        return None
    hits = search_candidates(conn, song, rejected=overrides.reject.get(song.key, frozenset())) if search else []
    return pages.Pick(song.id, song.display, title, song.artist, tuple(review_choices(conn, song, hits)),
                      search=True)


@dataclass(frozen=True)
class WrittenPage:
    """A kind of page caracole writes into the library, which the server serves only while it is
    still the page caracole wrote (``files.read_written_page``).

    ``written`` is its record: given the database, the library folder and a path's parts,
    the SHA-256 and the length of each such page caracole wrote there, [] for none.
    ``csp`` gives the Content-Security-Policy it is served with, which ``frame-ancestors
    'none'`` joins, from the page's bytes as read and found as written: a page written by an
    older caracole carries the hashes of that one's script and style, which a policy built by
    this one wouldn't allow. Those bytes are caracole's own, so reading them is safe.
    ``refused`` is what the 404 says for a page by its name that isn't served: index.html
    links any file there, whatever it holds.
    """

    written: Callable[[sqlite3.Connection, Path, tuple[str, ...]], list[tuple[str, int]]]
    csp: Callable[[bytes], str]
    refused: str


def written_pages() -> dict[str, WrittenPage]:
    """The pages caracole writes into the library, by file name: each song's sheet viewers
    (render.py), served in a sandbox with their own policy (``viewer.viewer_csp``), and each
    songbook's page (songbook.py, ``_songbooks/<folder>/songbook.html``), with its own
    (``book.songbook_csp``). A new kind of page joins here with its own record."""
    from caracole import songbook
    from caracole.render import AUTO_OUTPUTS, HUMAN_OUTPUTS
    from caracole.viewer import viewer_csp
    from caracole.viewer.book import songbook_csp

    viewer = WrittenPage(_viewers_written, viewer_csp, _VIEWER_REFUSED)
    return {HUMAN_OUTPUTS[2]: viewer, AUTO_OUTPUTS[2]: viewer,  # "sheet.html", "sheet (auto).html"
            songbook.HTML_NAME: WrittenPage(songbook.pages_written, songbook_csp, songbook.PAGE_REFUSED)}


_VIEWER_REFUSED = ("This sheet viewer isn't the page caracole last wrote here (it was changed on a synced "
                   "device, say), so the server won't send it: the next caracole render writes it again. "
                   "The PDF is beside it.")


def _viewers_written(conn: sqlite3.Connection, library_dir: Path, parts: tuple[str, ...]) -> list[tuple[str, int]]:
    """The viewer ``parts`` names, as caracole last wrote it (``render.written_file``) for each song
    whose folder (``library.song_dir``, where render.py writes it) the path is in."""
    from caracole.library import song_dir
    from caracole.render import written_file
    from caracole.songs import list_songs

    *folder, name = parts
    found = []
    for song in list_songs(conn):
        if song_dir(library_dir, song).relative_to(library_dir).parts == tuple(folder):
            record = written_file(conn, song.id, name)
            if record is not None:
                found.append(record)
    return found


def _ahead(jobs: list[Job], job: Job) -> int:
    """How many jobs wait or run before a queued one."""
    return sum(1 for j in jobs if j.active and j.id < job.id)


def _songbook_page(conn: sqlite3.Connection, job: Job) -> str | None:
    """A songbook's change that is done: its songbook's page, for its line to open; None for any other job."""
    from caracole.web.songbooks import songbook_page

    return songbook_page(conn, job.song_key) if job.state == "done" else None


def _view(job: Job, jobs: list[Job], song_id: int | None, facts: SongFacts | None, *,
          songbook_page: str | None = None) -> dict[str, Any]:
    """A job as /jobs.json gives it; ``jobs`` is the whole queue. ``kind`` says what it is about: a song
    ("song"), a song's removal ("remove"), or a songbook ("songbook", which ``songbook`` names), whose
    ``songbook_page`` its line links once it is done."""
    from caracole.web.songbooks import songbook_of

    songbook = songbook_of(job.song_key)
    kind = "remove" if job.song_key.startswith(REMOVING) else "songbook" if songbook is not None else "song"
    line = job_line(job, facts, ahead=_ahead(jobs, job), songbook_page=songbook_page)
    view = {"id": job.id, "display": job.display or job.title, "songId": song_id, "kind": kind,
            "state": job.state, "fetching": job.fetching, "line": line.as_json(), "details": details_href(job.id)}
    if songbook is not None:
        view["songbook"] = songbook
    return view


def _back(text: str) -> str:
    """The library page's address after # that a form sends along (``back``), as its script wrote it, without
    a song to show (``song=``); "" for anything else, which is no address of the page's."""
    text = text.removeprefix("#")
    if not _BACK.fullmatch(text):
        return ""
    return "&".join(part for part in text.split("&") if part and not part.startswith("song="))


def _library_at(back: str, song_id: int) -> str:
    """The library page as ``back`` (``_back``) left it, at a song's card."""
    return f"/#{back}&song={song_id}" if back else f"/#song={song_id}"


def _nothing_to_ask(conn: sqlite3.Connection, song: Song, overrides: Overrides | None) -> bool:
    """Whether Ultimate Guitar can't be asked about the song at all: the offline index doesn't have it, and
    its artist's UG page isn't known. ``caracole fetch --song`` refuses such a song; a lookup's sheet stage
    skips it, and what it lacks, UG lacks as far as caracole can tell: not found, not a wait."""
    from caracole.ug.fetch import artist_is_known

    return (song.match_decision == "not_found" and overrides is not None
            and not artist_is_known(conn, song, overrides))


def _job_ids(values: list[str] | None) -> frozenset[int] | None:
    """The jobs ``?jobs=N,M`` asks about (plain digits only, ``MAX_ASKED`` at most); None when the
    address asks about none in particular."""
    if values is None:
        return None
    ids: set[int] = set()
    for part in values[0].split(","):
        part = part.strip()
        if part.isascii() and part.isdigit() and len(ids) < MAX_ASKED:
            ids.add(int(part))
    return frozenset(ids)


def _overrides_or_none(cfg: Config) -> Overrides | None:
    from caracole.overrides import OverridesError, load_overrides

    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError:
        return None


def _song_ids(conn: sqlite3.Connection, keys: set[str]) -> frozenset[int]:
    if not keys:
        return frozenset()
    marks = ",".join("?" * len(keys))
    return frozenset(row[0] for row in conn.execute(f"SELECT id FROM songs WHERE key IN ({marks})", sorted(keys)))
