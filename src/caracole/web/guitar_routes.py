"""caracole serve's Guitar Pro page: a song's Guitar Pro file drawn and played in the browser, with alphaTab.

    GET  /guitar?file=    the page of a Guitar Pro file caracole keeps (``file``: its path in the library), with
                          the file's bytes inline (guitar_page.py)
    GET  /assets/alphatab[/<name>]  alphaTab's bundle (alphatab.py), which that page loads: to any origin,
                          kept for good

``/guitar`` shows only a file caracole recorded as a song's Guitar Pro file (``inbox.guitar_files``: a
``guitar-N.<ext>`` in the files table, filed from the inbox or downloaded from gtptabs.com) in a format alphaTab
reads (``inbox.BROWSER_EXTENSIONS``): any other path, a Power Tab file, a file gone from the library, a link in its
place or a folder of the path that is one (``files.read_library_file`` opens every part of the path without
following a link) is Refused (404). The page is made for each request, and nothing is written into the library. It
is served in a sandbox with its own policy (``guitar_page.policy``), which the route sets as its header.

The page loads the bundle by its address under ``/assets/alphatab/``, which names its hash, so the bundle is sent
with ``Cache-Control: immutable``; any other name there is 404. The page's sandbox gives it an origin of its own, so
the bundle is asked for by another origin: it is the same for anyone (alphaTab, its font and its SoundFont, all
published), so it is answered to any origin (``Access-Control-Allow-Origin: *``). Without alphaTab (``CARACOLE_ALPHATAB_DIR`` unset), ``/guitar`` says so (503),
the library page offers Guitar Pro files as downloads alone, and ``/assets/alphatab/`` answers 404.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from caracole.web.app import FRAMES, Response, Route, WebApp, address, html_response
from caracole.web.pages import Refused

if TYPE_CHECKING:
    from caracole.web.alphatab import AlphaTab

ASSETS = "/assets/alphatab/"
MAX_PATH = 1200  # characters: two names of 120 bytes and a file name, percent-encoded at worst
MAX_FILE = 8 * 1024 * 1024  # bytes: a Guitar Pro file is tens of kilobytes; the page holds it in base64
ONE_YEAR = 365 * 24 * 3600

ROUTES = (
    Route("GET", "/guitar", lambda app, asked: guitar(app, asked.target)),
    Route("GET", ASSETS, lambda app, asked: asset(app, address(asked)[len(ASSETS):]), under=True),
)

NOT_KEPT = Refused(404, "Not a Guitar Pro file", "That isn't a Guitar Pro file caracole keeps in the library.")
POWER_TAB = Refused(404, "A Power Tab file", "alphaTab can't read Power Tab files, so this one is a download alone: "
                                             "find it under its song's ⋯ in the library.")
NO_ALPHATAB = Refused(503, "No alphaTab here", "This caracole serve has no alphaTab (CARACOLE_ALPHATAB_DIR isn't set), "
                                               "so it can't show Guitar Pro files in the browser: download the file "
                                               "from its song's ⋯ in the library instead.")


def alphatab(app: WebApp) -> AlphaTab:
    """alphaTab's bundle; NO_ALPHATAB without it."""
    from caracole.web.alphatab import Missing, load

    try:
        return load(app.cfg.alphatab_dir)
    except Missing:
        raise NO_ALPHATAB from None


def guitar(app: WebApp, target: str) -> Response:
    """``GET /guitar?file=…``: the page of a song's Guitar Pro file."""
    from caracole.inbox import guitar_files
    from caracole.library_page import sheet_href
    from caracole.songs import get_song
    from caracole.web import guitar_page
    from caracole.web.app import no_such_song
    from caracole.web.files import NotServed, read_library_file

    try:
        fields = parse_qs(urlsplit(target).query, errors="strict", max_num_fields=4)
    except (UnicodeDecodeError, ValueError):
        raise Refused(400, "Not an address", "That address can't be read.") from None
    asked = fields.get("file", [])
    if len(asked) != 1 or not asked[0] or len(asked[0]) > MAX_PATH or any(ord(c) < 32 for c in asked[0]):
        raise NOT_KEPT
    path = asked[0]
    at = alphatab(app)
    with app.db() as conn:
        kept = guitar_files(conn, path=path)
        if not kept:
            raise NOT_KEPT
        file = kept[0]
        if not file.in_browser:
            raise POWER_TAB
        with no_such_song():
            song = get_song(conn, file.song_id)
    try:
        data, _kind, _download = read_library_file(app.cfg.library_dir, path,
                                                   hidden=(app.cfg.state_dir, app.cfg.cache_dir))
    except NotServed:
        raise Refused(404, "Not in the library", "That Guitar Pro file isn't in the library any more: the next "
                                                 "caracole run fetches it again, or files it from the inbox.") from None
    if len(data) > MAX_FILE:
        raise Refused(413, "Too large", "That Guitar Pro file is too large to show here: download it instead.")
    sheet = sheet_href(app.cfg.library_dir, song)
    viewer = _viewer_path(sheet)
    html = guitar_page.build_page(title=song.title, artist=", ".join(song.artists or [song.artist]), song_id=song.id,
                                  path=path, label=f"Guitar Pro {file.number}", data=data, at=at, sheet=viewer)
    # A sandbox, an origin of its own; downloads, for its Download link (the file is sent as an attachment).
    csp = f"sandbox allow-scripts allow-downloads; {guitar_page.policy(at)}; {FRAMES}"
    return html_response(200, html, csp=csp)


def _viewer_path(href: str | None) -> str | None:
    """The library path of the song's sheet viewer, from its sheet's link (``library_page.sheet_href``, percent-
    encoded), when that is a viewer; None else."""
    from urllib.parse import unquote

    if href is None or not href.endswith(".html"):
        return None
    return unquote(href)


def asset(app: WebApp, name: str) -> Response:
    """``GET /assets/alphatab/<name>``: alphaTab's bundle, by the name the page loads it by."""
    from caracole.web.alphatab import Missing, load

    try:
        at = load(app.cfg.alphatab_dir)
    except Missing:
        raise Refused(404, "Not found", "This caracole serve has no alphaTab (CARACOLE_ALPHATAB_DIR isn't set).") from None
    if name != at.name:
        raise Refused(404, "Not found", "There's no such file of alphaTab's here.")
    return Response(200, at.body, [
        ("Content-Type", "text/javascript; charset=utf-8"),
        ("Access-Control-Allow-Origin", "*"),
        ("Cross-Origin-Resource-Policy", "cross-origin"),
        ("Cache-Control", f"public, max-age={ONE_YEAR}, immutable"),
        ("Content-Security-Policy", f"default-src 'none'; {FRAMES}"),
    ])
