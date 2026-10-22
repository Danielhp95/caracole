"""caracole serve's export page: a sheet's PDF in the version its viewer was left in (key, capo, mode, shapes,
swaps), and Make this my version.

    GET  /export?sheet=   the version a sheet viewer's address holds (``sheet``: the viewer's library path,
                          then its address after #), with Make PDF and Make this my version
    POST /export          ``caracole render --song --version`` queued (with ``mine``, ``--mine`` too), and
                          back to the export page, which says how it goes and then links the PDF

``GET /export?sheet=<the viewer's library path>&<its address after #>`` names the version and offers Make
PDF, a form that ``POST``s to ``/export`` with the form token like the others. That queues
``caracole render --song=… --version=…`` (render.py ``render_version``), and the page, asked again with
``&job=<id>``, says how it goes and then links the PDF. Nothing here asks a site for anything: the export
is made from the sheet the library keeps.

Make this my version, unless the version is the song's own already, is the same form with ``mine=1``: it queues
``caracole render --song=… --version=… --mine``, which writes the song's ``[version]`` in overrides.toml
under caracole's lock (the server writes no overrides.toml itself), as the key it plays in (render.py
``ExportSheet.entry``), and renders the song in it: its PDF, its viewer and its songbooks then start there, on
whichever sheet the song has. An address naming no version is the song's own, as the viewer reads its own
(render.py ``export_version``), and one that plays the sheet as the song's own does is the song's own too. The
song's own kept as a move from the sheet (a ``t=`` entry, as caracole wrote one before it kept a key) is offered
as Keep it in this key, the same form: a sheet in another key in its place would move it.

An export is made from the song's human sheet, else its auto sheet (render.py ``export_viewer``). The auto
sheet's viewer kept beside a human sheet shows other chords: it offers no export, and one asked from it is
refused (409), as it would be the human sheet's PDF with the auto sheet's shapes and swaps, and Make this my
version would save them. So is one asked from a kept version's page (``version-<tab>.html``, sheet_versions.py),
another of Ultimate Guitar's sheets of the song: its export is made once it is the one (versions_routes.py, Make
this the one), from the song's own viewer.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from caracole.web import pages
from caracole.web.app import Response, Route, WebApp, html_response, redirect
from caracole.web.jobs import EXPORTING, MINE, Job
from caracole.web.pages import Refused

if TYPE_CHECKING:
    from pathlib import Path

    from caracole.songs import Song

MAX_QUERY = 2000  # characters: a version with every chord's shape and swap is a few hundred
YOURS = "yours"  # the version is the song's own, as it is kept
AS_A_MOVE = "as a move"  # the version is the song's own, kept as a move from the sheet (t=): it may be kept by its key

ROUTES = (
    Route("GET", "/export", lambda app, asked: export_page(app, asked.target)),
    Route("POST", "/export", lambda app, asked, form: export_post(app, form), page="the export page"),
)

_NOT_AN_ADDRESS = Refused(400, "Not an address", "That address can't be read.")
_BESIDE = ("This is the auto-chords sheet kept beside the song's own sheet, with chords of its own: a PDF in "
           "another version is made from the song's own sheet, so open that one from the library and export it.")
_VERSION = ("This is a version kept beside the song's own sheet, with chords of its own: a PDF in another version "
            "is made from the song's own sheet, so make this version the one first (Make this the one, under its "
            "Versions), then export it from the song's sheet.")


def export_page(app: WebApp, target: str) -> Response:
    """The page of ``GET /export?…`` (``target`` is the request's)."""
    try:
        params = parse_qsl(urlsplit(target).query, keep_blank_values=True, errors="strict", max_num_fields=60)
    except (UnicodeDecodeError, ValueError):
        raise _NOT_AN_ADDRESS from None
    sheet = next((v for k, v in params if k == "sheet"), "")
    job_id = next((v for k, v in params if k == "job"), None)
    shown = urlencode([(k, v) for k, v in params if k not in ("sheet", "job")])
    if any(_unreadable(v) for _, v in params):
        raise Refused(400, "Not a version", "That version can't be read.")
    if job_id is not None and not (job_id.isascii() and job_id.isdigit() and len(job_id) < 12):
        raise _NOT_AN_ADDRESS
    song, version, label, folder, mine = _version(app, sheet, shown)
    job = app.queue.job(int(job_id)) if job_id is not None else None
    if job is not None and job.song_key not in (_job_key(song, version), _job_key(song, version) + MINE):
        job = None  # another export's: not this page's to show
    pdf = None
    if job is not None and job.state == "done":
        pdf = _own_pdf(app, song, sheet) if job.song_key.endswith(MINE) else _pdf(app, song, label)
    return html_response(200, _body(app.csrf, song, sheet, shown, label, job, pdf, folder, mine))


def export_post(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /export``: queue the export, and go to the page that shows it."""
    sheet, asked = form.get("sheet", ""), form.get("v", "")
    song, version, _label, _folder, _mine = _version(app, sheet, asked)
    if form.get("mine") == "1":
        title, key = f"Make {song.display} your version", _job_key(song, version) + MINE
        steps = [("Making it your version", ("render", f"--song={song.display}", f"--version={version}", "--mine"))]
    else:
        title, key = f"Export {song.display}", _job_key(song, version)
        steps = [("Making the PDF", ("render", f"--song={song.display}", f"--version={version}"))]
    job, _ = app.submit(title, key, steps, display=song.display, song_id=song.id)
    query = urlencode([("sheet", sheet), *parse_qsl(asked, keep_blank_values=True), ("job", str(job.id))])
    return redirect(f"/export?{query}")


def _unreadable(text: str) -> bool:
    """Whether ``text`` holds a control character, which no sheet's address does."""
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def _job_key(song: Song, version: str) -> str:
    return f"{EXPORTING}{song.key}:{version}"


def _version(app: WebApp, sheet: str, query: str) -> tuple[Song, str, str, str, str | None]:
    """The song a viewer's path names, the version ``query`` holds as render.py writes it, its label, the
    song's folder in the library (as a path) and whether the version is the song's own (render.py
    ``ExportSheet.own``: its ``[version]``, else its ``[transpose]``, else as written), the one it plays its sheet
    in: ``YOURS``, ``AS_A_MOVE`` for one kept as a move from a sheet with a key (an older ``t=`` entry, which Make
    this my version would keep by its key), or None; raises Refused."""
    from caracole.library import song_dir
    from caracole.render import (
        AUTO_OUTPUTS,
        RenderError,
        export_query,
        export_sheet,
        export_version,
        export_viewer,
        keeps_key,
        written_file,
    )
    from caracole.songs import list_songs
    from caracole.web.app import version_page_tab, written_page

    try:
        readable = len(query) <= MAX_QUERY and not any(
            _unreadable(v) for _, v in parse_qsl(query, keep_blank_values=True, errors="strict", max_num_fields=60))
    except (UnicodeDecodeError, ValueError):
        readable = False
    if not readable or _unreadable(query):
        raise Refused(400, "Not a version", "That version can't be read.")
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
            source = export_sheet(conn, app.cfg, song)
            own = source.own(overrides)
            v = export_version(query, own)
            label = source.label(v)
            # where the song plays now: what Make this my version would keep of it is what its own is
            mine = YOURS if source.entry(own) == source.entry(v) else None
            if mine and song.key in overrides.version and not keeps_key(overrides, song) \
                    and source.shapes is not None and source.kept(v, overrides) is not None:
                mine = AS_A_MOVE
        except RenderError as e:
            raise Refused(404, "No sheet to export", str(e)) from e
    return song, export_query(v), label, "/".join(quote(p) for p in parts[:-1]), mine


def _pdf(app: WebApp, song: Song, label: str) -> str | None:
    """The export's PDF file name once it exists (render.py records it under its label)."""
    from caracole.db import kv_get_json
    from caracole.library import song_dir
    from caracole.render import EXPORT_KV

    try:
        with closing(app.connect()) as conn:
            record = kv_get_json(conn, f"{EXPORT_KV}{song.id}")
    except (sqlite3.Error, OSError):
        return None
    entry = record.get(label) if isinstance(record, dict) else None
    name = entry.get("pdf") if isinstance(entry, dict) else None
    if isinstance(name, str) and (song_dir(app.cfg.library_dir, song) / name).is_file():
        return name
    return None


def _own_pdf(app: WebApp, song: Song, sheet: str) -> str | None:
    """The PDF beside the sheet's viewer (``sheet.pdf`` beside ``sheet.html``) once it is there: the song's own,
    made in its version."""
    from caracole.library import song_dir

    name = sheet.rsplit("/", 1)[-1].removesuffix(".html") + ".pdf"
    return name if (song_dir(app.cfg.library_dir, song) / name).is_file() else None


def made_pdf(conn: sqlite3.Connection, library_dir: Path, song: Song, job: Job) -> str | None:
    """The PDF an export's job made (the version its ``--version`` names, as render.py records it), as a link
    relative to the library page, once it is in the song's folder; None for one that made none."""
    from caracole.db import kv_get_json
    from caracole.library import song_dir
    from caracole.render import EXPORT_KV

    asked = next((arg.removeprefix("--version=") for step in job.steps for arg in step.args
                  if arg.startswith("--version=")), None)
    record = kv_get_json(conn, f"{EXPORT_KV}{song.id}")
    if asked is None or not isinstance(record, dict):
        return None
    name = next((entry["pdf"] for entry in record.values()
                 if isinstance(entry, dict) and entry.get("query") == asked and isinstance(entry.get("pdf"), str)), None)
    folder = song_dir(library_dir, song)
    if name is None or not (folder / name).is_file():
        return None
    return "/".join(quote(part, safe="") for part in (*folder.relative_to(library_dir).parts, name))


def _body(csrf: str, song: Song, sheet: str, shown: str, label: str, job: Job | None,
          pdf: str | None, folder: str, mine: str | None) -> str:
    back = f"/{quote(sheet)}" + (f"#{shown}" if shown else "")
    hidden = "".join(f'  <input type="hidden" name="{name}" value="{escape(value, quote=True)}">\n'
                     for name, value in (("csrf", csrf), ("sheet", sheet), ("v", shown)))
    making = job is not None and job.song_key.endswith(MINE)
    states = {"queued": "Queued: it runs after the requests before it.",
              "cancelled": "Cancelled before it ran: make it again.",  # on the requests page
              "running": "Making it your version…" if making else "Making the PDF…",
              "done": "Done." if pdf else "Done, but no PDF was found: make it again."}
    if making:
        states["done"] = ("Done: it is your version now. Its PDF, its viewer and its songbooks start there."
                          if pdf else "Done, but no PDF was found: make it again.")
    says = ""
    if job is not None and job.state == "failed":
        last = next((line for step in job.steps for line in reversed(step.output) if line.strip()), "")
        says = f'<p class="says failed">Failed{": " + escape(last) if last else "."}</p>\n'
    elif job is not None:
        says = f'<p class="says {job.state}">{escape(states.get(job.state, job.state))}</p>\n'
    head = f'<meta http-equiv="refresh" content="{pages.REFRESH}">\n' if job is not None and job.active else ""
    links = ""
    if pdf:
        links += f'<a class="btn primary" href="/{folder}/{quote(pdf)}">Open the PDF</a>\n'
    links += f'<a class="btn" href="{escape(back, quote=True)}">Back to the sheet</a>'

    def keep(button: str) -> str:  # never str.format: the sheet's path in ``hidden`` may hold a brace
        return (f'<form class="confirm" method="post" action="/export">\n{hidden}'
                '  <input type="hidden" name="mine" value="1">\n'
                f'  <button class="btn" type="submit">{button}</button>\n</form>\n')

    if mine == YOURS:
        own = "<p>It is your version: the song's own PDF, its viewer and its songbooks are in it.</p>\n"
    elif mine == AS_A_MOVE:
        own = ("<p>It is your version, kept as a move from the sheet: a sheet in another key in its place would "
               "move it.</p>\n" + keep("Keep it in this key"))
    else:
        own = (keep("Make this my version") +
               "<p>Your version is where the song's own PDF, its viewer and its songbooks start, kept in "
               "overrides.toml (<code>[version]</code>).</p>\n")
    body = (f'<p class="lede">{escape(song.display)} in <strong>{escape(label)}</strong>. The PDF is written beside '
            "the sheet's own, and is made again when the sheet changes.</p>\n"
            f'<form class="confirm" method="post" action="/export">\n{hidden}'
            '  <button class="btn primary" type="submit">Make PDF</button>\n</form>\n'
            f'{own}{says}<div class="confirm">\n{links}\n</div>')
    return pages.page(f"Export {song.display}", body, head=head)
