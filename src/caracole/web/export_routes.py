"""caracole serve's Export PDF: a sheet's PDF in the version its viewer was left in (key, capo, mode, shapes, swaps,
instrument), downloaded at once, and Make this my version.

    GET  /export.pdf?sheet=   the PDF of the version a sheet viewer's address holds (``sheet``: the viewer's library
                              path, then its address after #), as an attachment; with ``mine=1``, Make this my
                              version queued too

``GET /export.pdf?sheet=<the viewer's library path>&<its address after #>`` renders that version of the song's sheet
now, in this process, in a private folder under the cache (render.py ``version_pdf``, the PDF ``render_version`` would
make), and answers it as an attachment named for the song and the version ("Soda Stereo - De Música Ligera (A Major,
capo 0).pdf", download_names.py). Nothing is written into the library and nothing is recorded: no lock, no queue, no
PDF exports entry, as the owner asked ("Just download"). Nothing here asks a site for anything: the PDF is made from
the sheet the library keeps. A PDF that can't be made (chordpro failing, a CJK font needed and missing) is refused
with the reason, never a broken PDF. An address naming no version is the song's own, as the viewer reads its own
(render.py ``export_version``).

With ``mine=1`` it also queues ``caracole render --song=… --version=… --mine``, under the song's key
(``jobs.EXPORTING``, ``jobs.MINE``), which writes the song's ``[version]`` in overrides.toml under caracole's lock (the
server writes no overrides.toml itself), as the key it plays in (render.py ``ExportSheet.entry``), and renders the song
in it: its PDF, its viewer and its songbooks then start there, on whichever sheet the song has. It is a plain link,
which the sandboxed viewer follows, with no form token and no cross-origin check: the owner's explicit choice
(security.py says so). A site could change a song's saved version with a link of its own; nothing is lost, and Reset
or another version undoes it. The host-name check still holds, as for every request (app.py). A HEAD changes nothing.

An export is made from the song's human sheet, else its auto sheet (render.py ``export_viewer``). The auto sheet's
viewer kept beside a human sheet shows other chords: it offers no export, and one asked from it is refused (409), as it
would be the human sheet's PDF with the auto sheet's shapes and swaps, and Make this my version would save them. So is
one asked from a kept version's page (``version-<tab>.html``, sheet_versions.py), another of Ultimate Guitar's sheets
of the song: its export is made once it is the one (versions_routes.py, Make this the one), from the song's own viewer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit

from caracole.web.app import Response, Route, WebApp
from caracole.web.jobs import EXPORTING, MINE
from caracole.web.pages import Refused

if TYPE_CHECKING:
    from caracole.songs import Song
    from caracole.viewer.version import Version

MAX_QUERY = 2000  # characters: a version with every chord's shape and swap is a few hundred
PDF = "application/pdf"

ROUTES = (
    Route("GET", "/export.pdf", lambda app, asked: export_pdf(app, asked.target, change=asked.method == "GET")),
)

_NOT_AN_ADDRESS = Refused(400, "Not an address", "That address can't be read.")
_NOT_A_VERSION = Refused(400, "Not a version", "That version can't be read.")
_BESIDE = ("This is the auto-chords sheet kept beside the song's own sheet, with chords of its own: a PDF in "
           "another version is made from the song's own sheet, so open that one from the library and export it.")
_VERSION = ("This is a version kept beside the song's own sheet, with chords of its own: a PDF in another version "
            "is made from the song's own sheet, so make this version the one first (Make this the one, under its "
            "Versions), then export it from the song's sheet.")


def export_pdf(app: WebApp, target: str, *, change: bool = True) -> Response:
    """``GET /export.pdf?…`` (``target`` is the request's): the PDF, and with ``mine=1`` (unless ``change`` is
    False, for a HEAD) Make this my version queued."""
    from caracole.download_names import content_disposition, download_name
    from caracole.normalize import clean_title
    from caracole.render import RenderError, export_query, version_pdf

    query = urlsplit(target).query
    try:
        params = parse_qsl(query, keep_blank_values=True, errors="strict", max_num_fields=60)
    except (UnicodeDecodeError, ValueError):
        raise _NOT_AN_ADDRESS from None
    if len(query) > MAX_QUERY or any(_unreadable(v) for _, v in params):
        raise _NOT_A_VERSION
    sheet = next((v for k, v in params if k == "sheet"), "")
    mine = next((v for k, v in params if k == "mine"), "") == "1"
    song, v = _version(app, sheet, urlencode([(k, v) for k, v in params if k not in ("sheet", "mine")]))
    try:
        with app.db() as conn:
            label, data = version_pdf(conn, app.cfg, song, v)
    except (RenderError, OSError) as e:
        raise Refused(500, "No PDF", f"The PDF couldn't be made: {e}") from e
    if mine and change:
        version = export_query(v)
        app.submit(f"Make {song.display} your version", f"{EXPORTING}{song.key}:{version}{MINE}",
                   [("Making it your version", ("render", f"--song={song.display}", f"--version={version}", "--mine"))],
                   display=song.display, song_id=song.id)
    name = download_name(song.artist, f"{clean_title(song.title)} ({label})", "sheet.pdf")
    return Response(200, data, [("Content-Type", PDF), ("Content-Disposition", content_disposition(name))])


def _unreadable(text: str) -> bool:
    """Whether ``text`` holds a control character, which no sheet's address does."""
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def _version(app: WebApp, sheet: str, query: str) -> tuple[Song, Version]:
    """The song a viewer's path names, and the version ``query`` holds (render.py ``export_version``: one naming none
    is the song's own, where its viewer starts); raises Refused."""
    from caracole.library import song_dir
    from caracole.render import AUTO_OUTPUTS, RenderError, export_sheet, export_version, export_viewer, written_file
    from caracole.songs import list_songs
    from caracole.web.app import version_page_tab, written_page

    parts = tuple(sheet.split("/"))
    if len(parts) < 2 or not sheet or any(p in ("", ".", "..") for p in parts) or written_page(parts[-1]) is None:
        raise Refused(404, "Not found", "There's no such sheet in the library.")
    overrides = app.overrides()
    library = app.cfg.library_dir
    with app.db() as conn:
        song = next((s for s in list_songs(conn)
                     if song_dir(library, s).relative_to(library).parts == parts[:-1]
                     and written_file(conn, s.id, parts[-1]) is not None), None)
        if song is None:
            raise Refused(404, "Not found", "There's no such sheet in the library.")
        if parts[-1] != export_viewer(conn, song):
            if parts[-1] == AUTO_OUTPUTS[2]:  # beside the human sheet, whose PDF an export would be
                raise Refused(409, "Not this sheet", _BESIDE)
            if version_page_tab(parts[-1]) is not None:  # another sheet's chords, the human sheet's PDF
                raise Refused(409, "Not this sheet", _VERSION)
            raise Refused(404, "Not found", "There's no such sheet in the library.")
        try:
            return song, export_version(query, export_sheet(conn, app.cfg, song).own(overrides))
        except RenderError as e:
            raise Refused(404, "No sheet to export", str(e)) from e
