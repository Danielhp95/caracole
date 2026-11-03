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
the digest a sync compares. A folder two songs share (two titles alike up to a folder name's length) is the song's
that keeps files there, as only one may (``library.SharedFolder``). A file of no unit carries neither: the library
page itself, a file in a folder no one song's, a songbook's that songbooks.toml no longer names. The units are read
as a sync reads them, from the database, overrides.toml and songbooks.toml: while either file can't be read, the
manifest is refused (503), and the app keeps the copy it has rather than one it can't gate. The format stays 1: a
reader of the manifest before the units ignores keys it doesn't know.

The app starts from the library page: without it as caracole wrote it (changed on a synced device, or written
before caracole recorded it: ``caracole todo`` writes it again), the manifest is refused (503), and the app keeps
the copy it has. It is a read, as a search is: no lock, no site asked, nothing written. Under ``/api/``, another
site's page can't read it (``security.own_page_read``); the app, which is no browser, can.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
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
    from caracole.library_page import PAGE_NAME, linked_files

    try:
        start = start_page(app)
        if start.status != 200:
            return json_response(503, {"error": NO_START})
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
    except Refused as e:  # the database can't be read
        return json_response(e.status, {"error": e.message})
    return json_response(200, {"format": FORMAT, "start": PAGE_NAME, "files": files})


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
    """The unit each folder's files are of, and each unit's digest now (see the module's docstring)."""

    songs: dict[tuple[str, str], str | None]  # a song's folder: its unit (None: no one song's)
    books: dict[str, str]  # a songbook's folder, under _songbooks/: its unit
    digests: dict[str, str]

    @classmethod
    def now(cls, app: WebApp) -> _Units:
        """The library's units as a sync reads them now; Refused (503) while overrides.toml or songbooks.toml can't
        be read."""
        from caracole.library import song_folder
        from caracole.peer_sync import library_state
        from caracole.songbook import SongbookError, load_songbooks, name_key, songbooks_file

        overrides = app.overrides(" The copy needs it to know which pages are still their songs'.")
        try:
            books = load_songbooks(songbooks_file(app.cfg.library_dir))
        except SongbookError as e:
            raise Refused(503, "songbooks.toml can't be read", f"songbooks.toml can't be read: {e}.") from e
        found: dict[tuple[str, str], list[tuple[int, str]]] = {}
        with app.db() as conn:
            state = library_state(conn, overrides, books)
            keeping = {song_id for (song_id,) in conn.execute("SELECT DISTINCT song_id FROM files")}
            for song_id, key, artist, title in conn.execute("SELECT id, key, artist, title FROM songs ORDER BY id"):
                found.setdefault(song_folder(artist, title), []).append((song_id, key))
        songs: dict[tuple[str, str], str | None] = {}
        for folder, here in found.items():
            if len(here) > 1:  # a folder songs share is the files' of the one that keeps files there
                here = [song for song in here if song[0] in keeping]
            songs[folder] = f"song/{here[0][1]}" if len(here) == 1 else None
        return cls(songs, {book.folder: f"songbook/{name_key(book.name)}" for book in books},
                   {unit.id: unit.digest for unit in state.values()})

    def of(self, parts: tuple[str, ...]) -> dict[str, str]:
        """The unit and digest of the file at ``parts`` (a path's), or nothing for a file of no unit."""
        from caracole.songbook import FOLDER

        if len(parts) != 3:
            return {}
        unit = self.books.get(parts[1]) if parts[0] == FOLDER else self.songs.get((parts[0], parts[1]))
        if unit is None or unit not in self.digests:
            return {}
        return {"unit": unit, "digest": self.digests[unit]}


def _left_out(app: WebApp) -> list[tuple[str, ...]]:
    """The library's folders the copy never holds, as their paths' parts: _inbox/ (inbox.py), and Music/ when it is
    inside the library."""
    folders = [("_inbox",)]
    try:
        music = Path(os.path.realpath(app.cfg.music_dir)).relative_to(os.path.realpath(app.cfg.library_dir)).parts
    except ValueError:  # elsewhere, as it is by default
        music = ()
    return folders + [music] if music else folders
