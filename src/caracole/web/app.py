"""The routes of ``caracole serve``, as one function from a request to a response: the router, the shapes
of its answers, what every route shares and the checks every request passes.

Each area's routes are a module of its own, a ``*_routes.py`` of caracole.web, whose ``ROUTES`` (each a
``Route``: a method, an address and what answers it) the router gathers from every such module, and whose
docstring lists them and says how they answer: library_routes.py (the library page, a song requested,
Fetch now), review_routes.py (the picker), jobs_routes.py (the Requests tab's data, Cancel and Try again,
/jobs.json, /api/jobs),
search_routes.py (the lookup page, search as you type, a song looked up now, a LaCuerda artist's page
read, LaCuerda's own search), remove_routes.py (Remove), songbook_routes.py (the songbook forms), export_routes.py (a
sheet's PDF in the version its viewer was left in, downloaded at once, and Make this my version), versions_routes.py
(a sheet's Ultimate Guitar versions: Make this the one, Keep it, back to caracole's pick), harmonica_routes.py (how
a harmonica tab is read: its readings, one pinned, back to caracole's guess), guitar_routes.py
(a song's Guitar Pro file in the browser, and alphaTab's bundle), offline_routes.py (what caracole's Android
app copies of the library, and the library page it starts from) and youtube_routes.py (a song's auto sheet from a
YouTube video pasted on the library page). A new route, or a new module of them, changes
nothing here. This module answers the rest:

    GET  /<file>          a file of the library (files.py), or a page caracole wrote there, such as
                          a sheet viewer, a kept version's or a harmonica tab's, while it is as written
                          (``written_page``), in a sandbox

There is no sign-in: whoever can reach the server may use it (security.py).
Every request must name the server by a name it answers to (421 otherwise).
Every POST must pass the cross-origin check and carry the form token (403),
be a form (415) and be small (413). /jobs.json and /requests.json, which no form asks for, must
pass the same cross-origin check and carry the form token in an
``X-Caracole-Form-Token`` header (403). One GET changes something, with
neither, by the owner's choice (security.py): ``/export.pdf?…&mine=1``
(export_routes.py), a plain link from the sandboxed viewer, which queues Make
this my version.

A route that turns a request down raises ``Refused`` (pages.py: a status, a
title and one sentence), which ``WebApp.handle`` answers with the message page.
To a page's script (it accepts JSON, or asks ``/api/``), a refusal is then
``{"error": "one sentence"}``, with the same status, and ``"reload": true`` when
the page must be reloaded (a form token older than the server). A
request queued is answered alike (``WebApp.queued``): to a form, a redirect; to
the page's script, the job, as /jobs.json gives it.

The route modules are the app's parts: each handler takes the ``WebApp`` and
reads and keeps what it shares between requests there (its config, its queue,
the search's answers kept).
"""

from __future__ import annotations

import importlib
import itertools
import json
import pkgutil
import secrets
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlsplit

from caracole import db
from caracole.config import Config
from caracole.web import pages
from caracole.web.files import NotServed, read_library_file, read_written_page
from caracole.web.jobs import Job, JobQueue, QueueFull
from caracole.web.pages import Refused
from caracole.web.security import answers_to, cross_origin_ok, host_name, own_page_read, same_token
from caracole.web.status import SongFacts, details_href

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.search import IndexFound, SiteArtist, SiteHit, Suggestion
    from caracole.songs import Song

MAX_BODY = 16 * 1024
TOKEN_HEADER = "x-caracole-form-token"  # /jobs.json's form token
_COMMON_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    # The page's origin to the server alone, never to another site: a form posted over plain HTTP to a LAN address
    # (no Sec-Fetch-Site there) carries its Origin, which security.cross_origin_ok compares with Host; under
    # no-referrer it said "null", and every form from a phone on the LAN was refused.
    ("Referrer-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cache-Control", "no-store"),
]
FRAMES = "frame-ancestors 'none'"
HTML = "text/html; charset=utf-8"
QUEUE_FULL = "The queue is full: try again once it empties."
NO_SUCH_SONG = "That song isn't in the library."


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


@dataclass(frozen=True)
class Route:
    """An address one of the route modules answers (its ``ROUTES``), and what answers it: ``answer(app,
    request)`` a GET or HEAD; ``answer(app, request, form)`` a POST, once the form passed every check
    (``page``: what a refusal of the form calls the page it came from). ``under``: every address that
    starts with ``path`` too. ``script_only``: a read the page's own script alone makes, checked as a write
    is (/jobs.json, /requests.json)."""

    method: str  # "GET" (which answers HEAD too) or "POST"
    path: str
    answer: Callable[..., Response]
    page: str = "the library"
    under: bool = False
    script_only: bool = False


@cache
def routes() -> dict[tuple[str, str], Route]:
    """Every route of every ``*_routes.py`` of caracole.web, by its method and address: one each."""
    from caracole import web

    found: dict[tuple[str, str], Route] = {}
    for module in sorted(m.name for m in pkgutil.iter_modules(web.__path__) if m.name.endswith("_routes")):
        for route in importlib.import_module(f"caracole.web.{module}").ROUTES:
            if (route.method, route.path) in found:
                raise RuntimeError(f"{route.method} {route.path} is answered twice ({module})")
            found[route.method, route.path] = route
    return found


def route_for(method: str, path: str) -> Route | None:
    """The route that answers ``method`` at ``path``: its own, else the one ``under`` which it is."""
    every = routes()
    if (method, path) in every:
        return every[method, path]
    return next((r for (m, _), r in every.items() if m == method and r.under and path.startswith(r.path)), None)


def address(request: Request) -> str:
    """The request's address, decoded (the router has read it already, and refused one it couldn't)."""
    return unquote(urlsplit(request.target).path, errors="strict")


# --- the answers ------------------------------------------------------------------------------


def html_response(status: int, html: str, *, csp: str = pages.PAGE_CSP) -> Response:
    return Response(status, html.encode("utf-8"), [("Content-Type", HTML), ("Content-Security-Policy", csp)])


def message_response(status: int, title: str, message: str) -> Response:
    response = html_response(status, pages.message_page(title, message))
    response.data = {"error": message}
    return response


def redirect(location: str) -> Response:
    return Response(303, b"", [("Location", location)])


def json_response(status: int, data: Any) -> Response:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Response(status, body, [("Content-Type", "application/json; charset=utf-8")])


def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


def query(request: Request) -> dict[str, list[str]]:
    """The fields of the request's address after ``?``."""
    return parse_qs(urlsplit(request.target).query)


# --- what the routes share --------------------------------------------------------------------


def unreadable(e: Exception) -> Refused:
    """The database can't be read (503): ``e``, an sqlite3.Error (DatabaseTooNew is one) or an OSError."""
    return Refused(503, "The database can't be read", f"The database can't be read: {e}")


def song_id(text: str, *, where: str = "form") -> int:
    """The song a form (or an address, ``where``) names by its id; Refused (400) when it names none."""
    try:
        return int(text)
    except ValueError:
        raise Refused(400, "Not a song", f"Which song? The {where} names none.") from None


@contextmanager
def no_such_song(message: str = NO_SUCH_SONG) -> Iterator[None]:
    """A KeyError in the block, ``songs.get_song``'s for an id no song has, Refused (404) with ``message``."""
    try:
        yield
    except KeyError:
        raise Refused(404, "No such song", message) from None


def not_ignored(song: Song, overrides: Overrides) -> None:
    """Refused (409) for a song ignored, in the database or in overrides.toml."""
    if song.status == "ignored" or song.key in overrides.ignore:
        raise Refused(409, "Ignored", f"{song.display} is ignored in overrides.toml.")


def overrides_or_none(cfg: Config) -> Overrides | None:
    """overrides.toml, for a page that does without it; None when it can't be read."""
    from caracole.overrides import load_overrides_or_none

    return load_overrides_or_none(cfg.overrides_file)


class WebApp:
    """The server's state: the config, the queue, the names it answers to and its form token, and what its
    routes keep between two requests."""

    def __init__(self, cfg: Config, queue: JobQueue, *, allowed: frozenset[str], csrf: str | None = None,
                 timers: Mapping[str, int] | None = None, searches_lacuerda: bool = True,
                 searches_youtube: bool = True):
        self.cfg = cfg
        self.queue = queue
        self.allowed = allowed
        self.csrf = csrf or secrets.token_urlsafe(32)
        self.timers = timers  # the library page script's, for the tests alone (``WebControls.timers``)
        # Whether the pages may send LaCuerda's own search (search_routes.py): False for the tests alone that drive
        # the pages for something else, whose queue it would join; caracole serve never sets it.
        self.searches_lacuerda = searches_lacuerda
        # Whether the library page may send YouTube's search for a query with no sheet (youtube_routes.py): False for
        # the tests alone that drive the page for something else where a sheet from a video can be made.
        self.searches_youtube = searches_youtube
        self._wanted = threading.Lock()  # one append to wanted.txt at a time, of the server's threads
        self._ended: dict[int, tuple[int | None, SongFacts | None]] = {}  # job id -> its song's id and facts
        self._ended_lock = threading.Lock()
        self._searching = threading.Lock()  # one search at a time
        self._tickets = itertools.count(1)
        # The newest search each search box asked for (search_routes.py: a box's id, "" for none), the last ones
        # asked of, in order.
        self._newest: OrderedDict[str, int] = OrderedDict()
        self._newest_lock = threading.Lock()
        # A query's answer from the offline indexes, kept a while: (when, the answer, its songs and artists as
        # JSON, the hint, gtptabs.com's and MuseScore's pages, LaCuerda's artists and songs, the artists spelled
        # close to the query).
        self._found: OrderedDict[str, tuple[float, IndexFound, list[dict[str, Any]], list[dict[str, Any]],
                                            str | None, list[SiteHit], list[SiteHit], list[SiteArtist],
                                            list[SiteHit], list[Suggestion]]] = OrderedDict()
        # The search's _Mine keeps each song's name forms here, by the song's names.
        self._song_forms: dict[tuple, tuple[frozenset[str], frozenset[str]]] = {}
        self._reads: set[int] = set()  # LaCuerda artist pages being read (jobs): the answers kept go once one is

    def handle(self, request: Request) -> Response:
        try:
            response = self._route(request)
        except Refused as e:  # a route's refusal: its page, or, to the page's script, data
            response = message_response(e.status, e.title, e.message)
        if response.data is not None and wants_json(request):  # the page's script: no redirect, no page
            response = json_response(200 if response.status == 303 else response.status, response.data)
        return self.finish(response)

    @staticmethod
    def finish(response: Response) -> Response:
        """Add the headers every answer has: no framing, no sniffing, no referrer to another site, no cache; each unless the answer
        has its own (alphaTab's bundle, kept for good and loaded by any origin: guitar_routes.py)."""
        if not any(name == "Content-Security-Policy" for name, _ in response.headers):
            response.headers.append(("Content-Security-Policy", FRAMES))
        own = {name.lower() for name, _ in response.headers}
        response.headers.extend((name, value) for name, value in _COMMON_HEADERS
                                if name.lower() not in own)
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
            return message_response(400, "Not an address", "That address can't be read.")
        method = request.method
        if method in ("GET", "HEAD"):
            if path.startswith("/api/") and not own_page_read(request.headers):
                return json_response(403, {"error": "This came from another site, so caracole refused it."})
            route = route_for("GET", path)
            if route is not None:
                return (route.script_only and self._script_read_refused(request)) or route.answer(self, request)
            return self._file(path)
        if method == "POST":
            route = route_for("POST", path)
            if route is None:
                return message_response(404, "Not here", "There's nothing to send to at this address.")
            form = self._form(request, page=route.page)
            return form if isinstance(form, Response) else route.answer(self, request, form)
        return Response(405, b"", [("Allow", "GET, HEAD, POST")])

    def _script_read_refused(self, request: Request) -> Response | None:
        """Why a read only the page's script makes (/jobs.json, /requests.json) is refused to anything else, as a write would be;
        None for the page's script."""
        if not cross_origin_ok("POST", request.headers, request.headers.get("host")):  # checked as a write
            return message_response(403, "Refused", "This came from another site, so caracole refused it.")
        if not same_token(request.headers.get(TOKEN_HEADER), self.csrf):
            return message_response(403, "Refused", "caracole serve has restarted since this page was opened: "
                                                    "reload it.")
        return None

    def _form(self, request: Request, *, page: str = "the library") -> dict[str, str] | Response:
        """The fields of a POSTed form, or why it is refused; a form token older than the server says to
        reload ``page``, and tells a page's script so (``reload``)."""
        headers = request.headers
        if not cross_origin_ok("POST", headers, headers.get("host")):
            return message_response(403, "Refused", "This came from another site, so caracole refused it.")
        kind = headers.get("content-type", "").split(";")[0].strip().lower()
        if kind != "application/x-www-form-urlencoded":
            return message_response(415, "Not a form", "caracole reads only forms sent from its own pages.")
        if len(request.body) > MAX_BODY:
            return message_response(413, "Too long", "That form is too long.")
        try:
            fields = parse_qs(request.body.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
        except (UnicodeDecodeError, ValueError):
            return message_response(400, "Not a form", "That form can't be read.")
        form = {name: values[0] for name, values in fields.items()}
        if not same_token(form.get("csrf"), self.csrf):
            refused = message_response(403, "Refused", "This form is older than the server, or not from its "
                                                       f"pages: reload {page} and try again.")
            refused.data = {**(refused.data or {}), "reload": True}
            return refused
        return form

    # --- what the routes share ---------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        return db.connect(self.cfg.db_path)

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        """The database, closed after the block; one that can't be read, there or in the block, Refused (503).
        Only for a block where every OSError means just that."""
        try:
            with closing(self.connect()) as conn:
                yield conn
        except (sqlite3.Error, OSError) as e:  # DatabaseTooNew is an sqlite3.DatabaseError
            raise unreadable(e) from e

    def overrides(self, then: str = "") -> Overrides:
        """overrides.toml; Refused (503) when it can't be read, with ``then`` after what is wrong with it."""
        from caracole.overrides import OverridesError, load_overrides

        try:
            return load_overrides(self.cfg.overrides_file)
        except OverridesError as e:
            raise Refused(503, "overrides.toml can't be read", f"overrides.toml can't be read: {e}.{then}") from e

    def submit(self, title: str, song_key: str, steps: Sequence[tuple[str, Sequence[str]]], *,
               full: str = QUEUE_FULL, **options: Any) -> tuple[Job, bool]:
        """``JobQueue.submit``; Refused (503) with ``full`` when the queue is full."""
        try:
            return self.queue.submit(title, song_key, steps, **options)
        except QueueFull:
            raise Refused(503, "The queue is full", full) from None

    def queued(self, job: Job, location: str | None = None) -> Response:
        """A request queued: to the browser, its line in the library page's Requests tab (its output open, unless ``location`` says
        where else); to the page's script, the job itself."""
        response = redirect(location or f"/{details_href(job.id)}")
        response.data = {"job": self.job_view(job)}
        return response

    def job_view(self, job: Job) -> dict[str, Any]:
        """A job just queued, as /jobs.json gives it to the library page's script (jobs_routes.py)."""
        from caracole.web.jobs_routes import view, views

        jobs = self.queue.snapshot()
        job = next((j for j in jobs if j.id == job.id), job)
        try:
            with closing(self.connect()) as conn:
                return views(self, conn, overrides_or_none(self.cfg), jobs, only=[job])[0]
        except (sqlite3.Error, OSError):  # the job is queued all the same
            return view(job, jobs, None, None)

    # --- the library's files, and the pages caracole wrote there -----------------------------------

    def _file(self, path: str) -> Response:
        try:
            if not path.startswith("/"):
                raise NotServed(path)
            page = written_page(path.rsplit("/", 1)[-1])
            if page is not None:
                try:
                    return self._written_page(path[1:], page)
                except NotServed:  # index.html links it all the same: say why it isn't sent
                    return message_response(404, "Not sent", page.refused)
            data, kind, download = read_library_file(self.cfg.library_dir, path[1:],
                                                     hidden=(self.cfg.state_dir, self.cfg.cache_dir))
        except NotServed:
            return message_response(404, "Not found", "There's no such page or file in the library.")
        headers = [("Content-Type", kind)]
        if download:
            headers.append(("Content-Disposition", self._download_header(path[1:])))
        return Response(200, data, headers)

    def _download_header(self, path: str) -> str:
        """A download's Content-Disposition: named for the song whose folder it is in, "Eagles - Hotel California
        (2).gp5" (download_names.py), else, with no such song or no database to read, as the file is named."""
        from caracole.download_names import content_disposition, download_name
        from caracole.library import songs_in_folder
        from caracole.normalize import clean_title

        *folder, name = path.split("/")
        try:
            with closing(self.connect()) as conn:
                songs = songs_in_folder(conn, tuple(folder))
        except (sqlite3.Error, OSError):  # the file is sent all the same
            songs = []
        song = songs[0] if songs else None
        return content_disposition(download_name(song.artist, clean_title(song.title), name) if song else name)

    def _written_page(self, path: str, page: WrittenPage) -> Response:
        """A page caracole wrote into the library, while it is still as written
        (``files.read_written_page``), with its kind's Content-Security-Policy; NotServed otherwise."""
        library_dir = self.cfg.library_dir
        with self.db() as conn:
            data = read_written_page(library_dir, path, lambda parts: page.written(conn, library_dir, parts),
                                     hidden=(self.cfg.state_dir, self.cfg.cache_dir))
        csp = f"{page.csp(data)}; {FRAMES}"  # the policy of these very bytes, not this caracole's
        return Response(200, data, [("Content-Type", HTML), ("Content-Security-Policy", csp)])


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
    (render.py), served in a sandbox with their own policy (``viewer.viewer_csp``), each
    songbook's page (songbook.py, ``_songbooks/<folder>/songbook.html``), with its own
    (``book.songbook_csp``), and the library page, index.html at the library's top (library_page.py), with
    the policy it holds and no sandbox (``library_page.page_csp``): ``/`` and ``/index.html`` are the page
    caracole serve makes itself, so the file is sent at ``/offline/index.html`` alone (offline_routes.py).
    A new kind of page joins here with its own record. A kept version's page, named by its tab, is a viewer
    too, and a harmonica tab's page (``harmonica-N.html``, render.py), recorded as a viewer is, is served as one,
    in a sandbox with its own policy (``written_page``): their names are numbered."""
    from caracole import library_page, songbook
    from caracole.render import AUTO_OUTPUTS, HUMAN_OUTPUTS
    from caracole.viewer import viewer_csp
    from caracole.viewer.book import songbook_csp

    viewer = WrittenPage(_viewers_written, viewer_csp, _VIEWER_REFUSED)
    return {HUMAN_OUTPUTS[2]: viewer, AUTO_OUTPUTS[2]: viewer,  # "sheet.html", "sheet (auto).html"
            songbook.HTML_NAME: WrittenPage(songbook.pages_written, songbook_csp, songbook.PAGE_REFUSED),
            library_page.PAGE_NAME: WrittenPage(library_page.pages_written, library_page.page_csp,
                                                library_page.PAGE_REFUSED)}


_VIEWER_REFUSED = ("This sheet viewer isn't the page caracole last wrote here (it was changed on a synced "
                   "device, say), so the server won't send it: the next caracole render writes it again. "
                   "The PDF is beside it.")
_VERSION_REFUSED = ("This version's viewer isn't the page caracole last wrote here (it was changed on a synced "
                    "device, say), so the server won't send it: the next caracole render writes it again. "
                    "The song's own sheet.html is beside it.")
_HARMONICA_REFUSED = ("This harmonica tab's page isn't the page caracole last wrote here (it was changed on a synced "
                      "device, say), so the server won't send it: the next caracole render writes it again. "
                      "The tab's text is beside it.")


def written_page(name: str) -> WrittenPage | None:
    """The kind of page caracole writes into the library under the file name ``name``: one of
    ``written_pages``, or, for a kept version's page (sheet_versions.py, ``version-<tab>.html``), a
    sheet viewer, and for a harmonica tab's page (``inbox.HARMONICA_PAGE``, ``harmonica-N.html``:
    viewer/harptab_page.py), a page of its own served as a viewer is, in a sandbox with the policy it holds
    (``viewer_csp``), each recorded as the others are (render.py); None for any other name."""
    page = written_pages().get(name)
    if page is None and version_page_tab(name) is not None:
        from caracole.viewer import viewer_csp

        page = WrittenPage(_viewers_written, viewer_csp, _VERSION_REFUSED)
    if page is None and harmonica_page_number(name) is not None:
        from caracole.viewer import viewer_csp

        page = WrittenPage(_viewers_written, viewer_csp, _HARMONICA_REFUSED)
    return page


def harmonica_page_number(name: str) -> int | None:
    """The N of a harmonica tab's page by its name ("harmonica-2.html"), else None."""
    from caracole.inbox import HARMONICA_PAGE

    found = HARMONICA_PAGE.fullmatch(name)
    return int(found.group(1)) if found else None


def version_page_tab(name: str) -> str | None:
    """The Ultimate Guitar tab of a kept version's viewer page by its name ("version-39144.html"), else None."""
    from caracole.sheet_versions import tab_of, version_names

    tab = tab_of(name)
    return tab if tab is not None and version_names(tab)[2] == name else None


def _viewers_written(conn: sqlite3.Connection, library_dir: Path, parts: tuple[str, ...]) -> list[tuple[str, int]]:
    """The viewer ``parts`` names, as caracole last wrote it (``render.written_file``) for each song
    whose folder (``library.song_dir``, where render.py writes it) the path is in."""
    from caracole.library import songs_in_folder
    from caracole.render import written_file

    *folder, name = parts
    found = []
    for song in songs_in_folder(conn, tuple(folder)):
        record = written_file(conn, song.id, name)
        if record is not None:
            found.append(record)
    return found
