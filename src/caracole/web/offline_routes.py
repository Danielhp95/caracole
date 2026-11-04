"""caracole serve's copy of the library for caracole's Android app, which reads it offline: what to copy, read-only.

    GET  /api/offline         the manifest: every file the app copies, each with its address here, its size, its
                              SHA-256, its type, the headers it is sent with, and the sync unit it is of
    GET  /offline/index.html  the library page caracole wrote, index.html at the library's top, while it is as
                              written (``/index.html`` is the page caracole serve makes itself, with its forms)

The app shows caracole's own pages as caracole wrote them into the library (the library page, the sheet viewers,
the songbooks' pages, the PDFs), from a copy on the phone that it brings up to date from the manifest::

    {"format": 1, "start": "index.html", "files": [
        {"path": "index.html", "url": "/offline/index.html", "size": 81234, "sha256": "<64 hex>",
         "type": "text/html; charset=utf-8", "headers": {"Content-Security-Policy": "...", ...}},
        {"path": "Estopa/Tu calorro/sheet.html", "url": "/Estopa/Tu%20calorro/sheet.html", ...,
         "unit": "song/estopa/tu-calorro", "digest": "<64 hex>"}, ...]}

``format`` changes only with the manifest's shape. The files: the library page (``start``) first, then, by path,
each file it links to (``library_page.linked_files``: every song's files, its kept versions' pages and its harmonica
tabs' pages, every songbook's files) that caracole serve sends now: a page caracole wrote (app.py's ``written_pages``:
a sheet viewer, a kept version's, a harmonica tab's, a songbook's) only while it holds the bytes caracole recorded, any other file only of a kind
files.py sends (PDFs, text, ChordPro, lyrics, info.json, Guitar Pro files and scores). The viewers and the
songbooks' pages link nothing more of the library: their PDFs and the versions' pages are the library page's
links too. Never a file in Music/ or _inbox/ (should a song's folder be there), at an address another route
answers (a song "jobs" by an artist "api"), or that files.py refuses: a hidden name, caracole's state or cache, a
symbolic link, a file gone.

Each entry is the file as a GET of its ``url`` answers it now, made by the same code (``WebApp._file``): its bytes
(``size``, and ``sha256``, lowercase hex), its Content-Type (``type``), and of its headers those that change how a
browser treats it (``HEADERS``): a written page's Content-Security-Policy, the sandbox in it, and every answer's
``Referrer-Policy`` and ``X-Content-Type-Options``. A ``path`` is the file's in the library, ``/``-separated and
decoded, as the pages link each other, so the copy's links resolve as the folder's do; a ``url``, the path
percent-encoded. The same library gives the same answer.

Each file of a song or a songbook names the sync unit it is made from (peer_sync.py), so that a phone whose own
caracole changed or removed the song since serves the computer's page no longer: ``unit``, ``song/<identity key>``
for a file in a song's folder (``library.song_folder``) and ``songbook/<name key>`` for one in a songbook's (under
``_songbooks/``), and ``digest``, the unit's digest as ``peer_sync.library_state`` gives it when the manifest is made,
the digest a sync compares. In a folder two songs share (two titles alike up to a folder name's length), where each
may keep files of other names (``library.SharedFolder`` refuses a file of the same name alone), each file is the
song's caracole wrote it for: its kept files and what caracole made of them, as a removal reads them
(``removal._caracoles``); a file both could be (their info.json, say) is no one song's. A file of no unit carries
neither: the library page itself, such a file in a shared folder, a songbook's that songbooks.toml no longer names.
The units are read as a sync reads them (peer_routes.py's ``_library``), from the database, overrides.toml and
songbooks.toml: while either file can't be read, the manifest is refused (503), and the app keeps the copy it has
rather than one it can't gate. The format stays 1: a reader of the manifest before the units ignores keys it
doesn't know.

The app starts from the library page: without it as caracole wrote it (changed on a synced device, or written
before caracole recorded it: ``caracole todo`` writes it again), the manifest is refused (503), and the app keeps
the copy it has. It is a read, as a search is: no lock, no site asked, nothing written. Under ``/api/``, another
site's page can't read it (``security.own_page_read``); the app, which is no browser, can.

``manifest_of`` is the manifest as data, and ``library_pages`` the pages an export of the library holds
(peer_file.py): the manifest and each listed file's bytes as a GET of its ``url`` answers them, read by a ``WebApp``
of its own, made for reading alone (``caracole peer export`` runs no server).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote

from caracole.web.app import Response, Route, WebApp, json_response, route_for
from caracole.web.pages import Refused

FORMAT = 1
START = "/offline/index.html"
# The headers an entry names, as the app hands them to its WebView with the file.
HEADERS = ("Content-Security-Policy", "Referrer-Policy", "X-Content-Type-Options")
NO_START = ("The library page isn't as caracole last wrote it (it was changed on a synced device, say, or caracole "
            "has no record of it yet), so there is nothing to copy: caracole todo writes it again.")

ROUTES = (
    Route("GET", "/api/offline", lambda app, asked: manifest(app)),
    Route("GET", START, lambda app, asked: start_page(app)),
)


def start_page(app: WebApp) -> Response:
    """The library page caracole wrote, as any page it wrote is sent (app.py's ``written_pages``), or why not (404)."""
    from caracole.library_page import PAGE_NAME

    return app._file(f"/{PAGE_NAME}")


def manifest(app: WebApp) -> Response:
    """``GET /api/offline``: the files the app copies (see the module's docstring), or why there are none, as JSON."""
    try:
        return json_response(200, manifest_of(app))
    except Refused as e:  # no library page as written, or the database or the units can't be read
        return json_response(e.status, {"error": e.message})


def manifest_of(app: WebApp) -> dict[str, Any]:
    """What ``GET /api/offline`` answers (see the module's docstring), as data; Refused (503) as it refuses: no
    library page as caracole wrote it, or a database, overrides.toml or songbooks.toml that can't be read."""
    from caracole.library_page import PAGE_NAME, linked_files

    start = start_page(app)
    if start.status != 200:
        raise Refused(503, "Nothing to copy", NO_START)
    files = [_entry(PAGE_NAME, START, start)]
    units = _Units.now(app)
    left_out = _left_out(app)
    for path in sorted(set(linked_files(start.body)) - {PAGE_NAME}):
        parts = tuple(path.split("/"))
        if "\\" in path or any(parts[:len(folder)] == folder for folder in left_out):
            continue
        if route_for("GET", f"/{path}") is not None:  # its address is another route's
            continue
        response = app._file(f"/{path}")
        if response.status == 200:
            url = "/" + "/".join(quote(part, safe="") for part in parts)
            files.append(_entry(path, url, response) | units.of(parts))
    return {"format": FORMAT, "start": PAGE_NAME, "files": files}


def library_pages(cfg) -> tuple[dict[str, Any], Callable[[str], bytes]] | None:
    """The pages a ``.caracole`` file of this library holds (peer_file.py's ``Pages``): the manifest as ``GET
    /api/offline`` answers it now, and a listed file's bytes by its path, as a GET of its ``url`` answers them; None
    while there is no copy to make (the library page isn't as caracole wrote it, or the library can't be read). Read
    as caracole serve reads it, by a ``WebApp`` made for reading alone: its queue never started, nothing written."""
    from caracole.web.jobs import JobQueue

    app = WebApp(cfg, JobQueue(_runs_nothing), allowed=frozenset())
    try:
        listed = manifest_of(app)
    except Refused:
        return None
    urls = {entry["path"]: entry["url"] for entry in listed["files"]}

    def fetch(path: str) -> bytes:
        response = WebApp.finish(start_page(app) if urls.get(path) == START else app._file(f"/{path}"))
        if response.status != 200:
            raise OSError(f"{path} isn't sent now")
        return response.body

    return listed, fetch


def _runs_nothing(args, emit) -> int:  # noqa: ARG001 - library_pages' queue is never started
    raise AssertionError("library_pages runs no job")


def _entry(path: str, url: str, response: Response) -> dict[str, Any]:
    """A file's entry, from the answer a GET of ``url`` gets, with the headers every answer gets."""
    response = WebApp.finish(response)
    kind = next(value for name, value in response.headers if name == "Content-Type")
    headers: dict[str, str] = {}
    for name, value in response.headers:
        if name in HEADERS:
            headers[name] = f"{headers[name]}, {value}" if name in headers else value
    return {"path": path, "url": url, "size": len(response.body), "sha256": hashlib.sha256(response.body).hexdigest(),
            "type": kind, "headers": headers}


@dataclass(frozen=True)
class _Units:
    """The unit each file is of, and each unit's digest now (see the module's docstring)."""

    songs: dict[tuple[str, str], str]  # a song's folder, one song's alone: its unit
    shared: dict[tuple[str, str, str], str]  # a file in a folder songs share: the unit of the one song that wrote it
    books: dict[str, str]  # a songbook's folder, under _songbooks/: its unit
    digests: dict[str, str]

    @classmethod
    def now(cls, app: WebApp) -> _Units:
        """The library's units as a sync reads them now; Refused (503) while overrides.toml or songbooks.toml can't
        be read."""
        from caracole.library import song_folder
        from caracole.peer_sync import library_state
        from caracole.songbook import name_key
        from caracole.web.peer_routes import _library

        overrides, books = _library(app)
        found: dict[tuple[str, str], list[tuple[int, str]]] = {}
        shared: dict[tuple[str, str, str], str] = {}
        with app.db() as conn:
            state = library_state(conn, overrides, books)
            for song_id, key, artist, title in conn.execute("SELECT id, key, artist, title FROM songs ORDER BY id"):
                found.setdefault(song_folder(artist, title), []).append((song_id, key))
            for folder, here in found.items():
                if len(here) > 1:
                    shared |= _written_for(conn, folder, here)
        songs = {folder: f"song/{here[0][1]}" for folder, here in found.items() if len(here) == 1}
        return cls(songs, shared, {book.folder: f"songbook/{name_key(book.name)}" for book in books},
                   {unit.id: unit.digest for unit in state.values()})

    def of(self, parts: tuple[str, ...]) -> dict[str, str]:
        """The unit and digest of the file at ``parts`` (a path's), or nothing for a file of no unit."""
        from caracole.songbook import FOLDER

        if len(parts) != 3:
            return {}
        if parts[0] == FOLDER:
            unit = self.books.get(parts[1])
        else:
            unit = self.songs.get((parts[0], parts[1])) or self.shared.get((parts[0], parts[1], parts[2]))
        if unit is None or unit not in self.digests:
            return {}
        return {"unit": unit, "digest": self.digests[unit]}


def _written_for(conn: sqlite3.Connection, folder: tuple[str, str],
                 here: list[tuple[int, str]]) -> dict[tuple[str, str, str], str]:
    """In a folder songs share (``here``: each one's id and key), each file caracole wrote for one of them alone, by
    its path's parts: its unit. A file two of them could be is none of theirs."""
    from caracole.removal import _caracoles, _kept_files
    from caracole.songs import get_song

    claimed: dict[str, set[str]] = {}
    for song_id, key in here:
        song = get_song(conn, song_id)
        kept_here, _ = _kept_files(conn, song, PurePosixPath(*folder))
        for name in _caracoles(conn, song, kept_here):
            claimed.setdefault(name, set()).add(f"song/{key}")
    return {(*folder, name): next(iter(units)) for name, units in claimed.items() if len(units) == 1}


def _left_out(app: WebApp) -> list[tuple[str, ...]]:
    """The library's folders the copy never holds, as their paths' parts: _inbox/ (inbox.py), and Music/ when it is
    inside the library."""
    folders = [("_inbox",)]
    try:
        music = Path(os.path.realpath(app.cfg.music_dir)).relative_to(os.path.realpath(app.cfg.library_dir)).parts
    except ValueError:  # elsewhere, as it is by default
        music = ()
    return folders + [music] if music else folders
