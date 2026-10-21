"""``/export``: a sheet's PDF in the version its viewer was left in (key, capo, mode, shapes, swaps).

``GET /export?sheet=<the viewer's library path>&<its address after #>`` names the version and offers Make
PDF, a form that ``POST``s to ``/export`` with the form token like the others. That queues
``caracole render --song=… --version=…`` (render.py ``render_version``), and the page, asked again with
``&job=<id>``, says how it goes and then links the PDF. Nothing here asks a site for anything: the export
is made from the sheet the library keeps.

Make this my version, unless the version is the song's own already, is the same form with ``mine=1``: it queues
``caracole render --song=… --version=… --mine``, which writes the song's ``[version]`` in overrides.toml
under caracole's lock (the server writes no overrides.toml itself) and renders the song in it: its PDF, its
viewer and its songbooks then start there. An address naming no version is the song's own, as the viewer
reads its own (render.py ``export_version``).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from caracole.web import pages
from caracole.web.jobs import Job, QueueFull

if TYPE_CHECKING:
    from caracole.songs import Song
    from caracole.web.app import Response, WebApp

MAX_QUERY = 2000  # characters: a version with every chord's shape and swap is a few hundred
EXPORTING = "export:"  # a job's song_key, then the song's key and the version: never the song's own jobs'
MINE = ":mine"  # after an export's song_key: making that version the song's own


class _Refused(Exception):
    def __init__(self, status: int, title: str, message: str):
        super().__init__(message)
        self.status, self.title, self.message = status, title, message


def export_page(app: WebApp, target: str) -> Response:
    """The page of ``GET /export?…`` (``target`` is the request's)."""
    from caracole.web.app import _html, _message

    try:
        params = parse_qsl(urlsplit(target).query, keep_blank_values=True, errors="strict", max_num_fields=60)
    except (UnicodeDecodeError, ValueError):
        return _message(400, "Not an address", "That address can't be read.")
    sheet = next((v for k, v in params if k == "sheet"), "")
    job_id = next((v for k, v in params if k == "job"), None)
    shown = urlencode([(k, v) for k, v in params if k not in ("sheet", "job")])
    if any(_unreadable(v) for _, v in params):
        return _message(400, "Not a version", "That version can't be read.")
    try:
        if job_id is not None and not (job_id.isascii() and job_id.isdigit() and len(job_id) < 12):
            raise _Refused(400, "Not an address", "That address can't be read.")
        song, version, label, folder, mine = _version(app, sheet, shown)
    except _Refused as e:
        return _message(e.status, e.title, e.message)
    job = app.queue.job(int(job_id)) if job_id is not None else None
    if job is not None and job.song_key not in (_job_key(song, version), _job_key(song, version) + MINE):
        job = None  # another export's: not this page's to show
    pdf = None
    if job is not None and job.state == "done":
        pdf = _own_pdf(app, song, sheet) if job.song_key.endswith(MINE) else _pdf(app, song, label)
    return _html(200, _body(app.csrf, song, sheet, shown, label, job, pdf, folder, mine))


def export_post(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /export``: queue the export, and go to the page that shows it."""
    from caracole.web.app import _message, _redirect

    sheet, asked = form.get("sheet", ""), form.get("v", "")
    try:
        song, version, _label, _folder, _mine = _version(app, sheet, asked)
    except _Refused as e:
        return _message(e.status, e.title, e.message)
    if form.get("mine") == "1":
        title, key = f"Make {song.display} your version", _job_key(song, version) + MINE
        steps = [("Making it your version", ("render", f"--song={song.display}", f"--version={version}", "--mine"))]
    else:
        title, key = f"Export {song.display}", _job_key(song, version)
        steps = [("Making the PDF", ("render", f"--song={song.display}", f"--version={version}"))]
    try:
        job, _ = app.queue.submit(title, key, steps, display=song.display, song_id=song.id)
    except QueueFull:
        return _message(503, "The queue is full", "The queue is full: try again once it empties.")
    query = urlencode([("sheet", sheet), *parse_qsl(asked, keep_blank_values=True), ("job", str(job.id))])
    return _redirect(f"/export?{query}")


def _unreadable(text: str) -> bool:
    """Whether ``text`` holds a control character, which no sheet's address does."""
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def _job_key(song: Song, version: str) -> str:
    return f"{EXPORTING}{song.key}:{version}"


def _version(app: WebApp, sheet: str, query: str) -> tuple[Song, str, str, str, bool]:
    """The song a viewer's path names, the version ``query`` holds as render.py writes it, its label, the
    song's folder in the library (as a path) and whether the version is the song's own (render.py
    ``own_version``: its ``[version]``, else its ``[transpose]``, else as written); raises _Refused."""
    from caracole.library import song_dir
    from caracole.overrides import OverridesError, load_overrides
    from caracole.render import RenderError, export_label, export_query, export_version, own_version, written_file
    from caracole.songs import list_songs
    from caracole.web.app import written_pages

    try:
        readable = len(query) <= MAX_QUERY and not any(
            _unreadable(v) for _, v in parse_qsl(query, keep_blank_values=True, errors="strict", max_num_fields=60))
    except (UnicodeDecodeError, ValueError):
        readable = False
    if not readable or _unreadable(query):
        raise _Refused(400, "Not a version", "That version can't be read.")
    parts = tuple(sheet.split("/"))
    if len(parts) < 2 or not sheet or any(p in ("", ".", "..") for p in parts) or parts[-1] not in written_pages():
        raise _Refused(404, "Not found", "There's no such sheet in the library.")
    try:
        overrides = load_overrides(app.cfg.overrides_file)
    except OverridesError as e:
        raise _Refused(503, "overrides.toml can't be read", f"overrides.toml can't be read: {e}.") from e
    library = app.cfg.library_dir
    try:
        with closing(app._connect()) as conn:
            song = next((s for s in list_songs(conn)
                         if song_dir(library, s).relative_to(library).parts == parts[:-1]
                         and written_file(conn, s.id, parts[-1]) is not None), None)
            if song is None:
                raise _Refused(404, "Not found", "There's no such sheet in the library.")
            try:
                v = export_version(query, overrides, song)
                label = export_label(conn, app.cfg, song, v)
            except RenderError as e:
                raise _Refused(404, "No sheet to export", str(e)) from e
    except (sqlite3.Error, OSError) as e:
        raise _Refused(503, "The database can't be read", f"The database can't be read: {e}") from e
    mine = export_query(own_version(overrides, song)) == export_query(v)  # where the song plays now
    return song, export_query(v), label, "/".join(quote(p) for p in parts[:-1]), mine


def _pdf(app: WebApp, song: Song, label: str) -> str | None:
    """The export's PDF file name once it exists (render.py records it under its label)."""
    from caracole.library import song_dir
    from caracole.render import EXPORT_KV
    from caracole.db import kv_get_json

    try:
        with closing(app._connect()) as conn:
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


def _body(csrf: str, song: Song, sheet: str, shown: str, label: str, job: Job | None,
          pdf: str | None, folder: str, mine: bool) -> str:
    back = f"/{quote(sheet)}" + (f"#{shown}" if shown else "")
    hidden = "".join(f'  <input type="hidden" name="{name}" value="{escape(value, quote=True)}">\n'
                     for name, value in (("csrf", csrf), ("sheet", sheet), ("v", shown)))
    making = job is not None and job.song_key.endswith(MINE)
    states = {"queued": "Queued: it runs after the requests before it.",
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
    if mine:
        own = "<p>It is your version: the song's own PDF, its viewer and its songbooks are in it.</p>\n"
    else:
        own = (f'<form class="confirm" method="post" action="/export">\n{hidden}'
               '  <input type="hidden" name="mine" value="1">\n'
               '  <button class="btn" type="submit">Make this my version</button>\n</form>\n'
               "<p>Your version is where the song's own PDF, its viewer and its songbooks start, kept in "
               "overrides.toml (<code>[version]</code>).</p>\n")
    body = (f'<p class="lede">{escape(song.display)} in <strong>{escape(label)}</strong>. The PDF is written beside '
            "the sheet's own, and is made again when the sheet changes.</p>\n"
            f'<form class="confirm" method="post" action="/export">\n{hidden}'
            '  <button class="btn primary" type="submit">Make PDF</button>\n</form>\n'
            f'{own}{says}<div class="confirm">\n{links}\n</div>')
    return pages.page(f"Export {song.display}", body, head=head)
