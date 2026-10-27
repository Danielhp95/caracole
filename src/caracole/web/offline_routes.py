"""caracole serve's copy of the library for caracole's Android app, which reads it offline: what to copy, read-only.

    GET  /api/offline         the manifest: every file the app copies, each with its address here, its size, its
                              SHA-256, its type and the headers it is sent with
    GET  /offline/index.html  the library page caracole wrote, index.html at the library's top, while it is as
                              written (``/index.html`` is the page caracole serve makes itself, with its forms)

The app shows caracole's own pages as caracole wrote them into the library (the library page, the sheet viewers,
the songbooks' pages, the PDFs), from a copy on the phone that it brings up to date from the manifest::

    {"format": 1, "start": "index.html", "files": [
        {"path": "index.html", "url": "/offline/index.html", "size": 81234, "sha256": "<64 hex>",
         "type": "text/html; charset=utf-8", "headers": {"Content-Security-Policy": "...", ...}},
        {"path": "Estopa/Tu calorro/sheet.html", "url": "/Estopa/Tu%20calorro/sheet.html", ...}, ...]}

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

The app starts from the library page: without it as caracole wrote it (changed on a synced device, or written
before caracole recorded it: ``caracole todo`` writes it again), the manifest is refused (503), and the app keeps
the copy it has. It is a read, as a search is: no lock, no site asked, nothing written. Under ``/api/``, another
site's page can't read it (``security.own_page_read``); the app, which is no browser, can.
"""

from __future__ import annotations

import hashlib
import os
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
        left_out = _left_out(app)
        for path in sorted(set(linked_files(start.body)) - {PAGE_NAME}):
            parts = tuple(path.split("/"))
            if "\\" in path or any(parts[:len(folder)] == folder for folder in left_out):
                continue
            if route_for("GET", f"/{path}") is not None:  # its address is another route's
                continue
            response = app._file(f"/{path}")
            if response.status == 200:
                files.append(_entry(path, "/" + "/".join(quote(part, safe="") for part in parts), response))
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


def _left_out(app: WebApp) -> list[tuple[str, ...]]:
    """The library's folders the copy never holds, as their paths' parts: _inbox/ (inbox.py), and Music/ when it is
    inside the library."""
    folders = [("_inbox",)]
    try:
        music = Path(os.path.realpath(app.cfg.music_dir)).relative_to(os.path.realpath(app.cfg.library_dir)).parts
    except ValueError:  # elsewhere, as it is by default
        music = ()
    return folders + [music] if music else folders
