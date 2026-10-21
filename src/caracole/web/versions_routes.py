"""caracole serve's versions page: one of Ultimate Guitar's chords versions of a song's sheet, made the one the
title opens, kept beside the sheet, or the song taken back to caracole's pick.

    GET  /versions?sheet=&tab=&do=   the version (``sheet``: the library path of the viewer it was asked from;
                          ``tab``: its UG tab; ``do``: choose, keep or clear) with the one form that does it,
                          then, with ``&job=``, how it goes and a link to what it made
    POST /versions/choose  Make this the one: ``caracole versions --choose --progress`` queued (``caracole get
                          --tab`` with the tab's own page, recorded under ``[pin]``), and back to the versions page
    POST /versions/keep    Keep it: ``caracole versions --keep --progress`` queued (one tab page, at the lookup
                          pace)
    POST /versions/clear   Go back to caracole's pick: ``caracole versions --clear --progress`` queued, for a
                          song with a ``[pin]`` that chooses its sheet

A sheet viewer served from the library runs in a sandbox, with no way to post a form to the server, so its
switcher links ``GET /versions?…``, a page of the server's own with no script, whose form ``POST``s with the
form token like the others. Each post is one command queued under the song's key, as a lookup's is, so the
song's card shows it and its jobs join (jobs.py: a version made the one or kept, or the pin taken out, is a pick
of the song's as a lookup's ``--tab`` is): the same version asked twice is one job, Make this the one takes the place of the
song's lookup that still waits. The server writes no overrides.toml and keeps no file itself: the command does,
under caracole's lock, at the lookup pace and within its budgets. Its progress lines are the job's stages, as a
lookup's are. Once the job is done, the page says what it came to from the song's state, read again, never from
the command's exit (a block, a spent budget or the hour's cap exits 0, the sheet as it was): the version the
one, else its ``[pin]`` recorded for the nightly run, else nothing changed; a version kept or not; the ``[pin]``
gone or still there.

Each refusal is a ``Refused``: a sheet that is no viewer caracole wrote for a song of the library (404; a
version's page that went once that version became the one still names its song, and Back to the sheet opens
sheet.html), a tab
that isn't a number (400) or isn't one of the song's chords versions on Ultimate Guitar (404), and, posted, what
can't be done (409): Make this the one on the one, Keep it on a version kept already, either on a version UG no
longer has or one under ``[block]`` (as ``caracole versions`` refuses it), Go back to caracole's pick on a song
with no ``[pin]`` of its sheet (a Guitar Pro or tab pin stays, as ``caracole versions --clear`` leaves it), and an
ignored song. The page itself says
so for those, and offers no form.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from caracole.web import pages
from caracole.web.app import Response, Route, WebApp, html_response, not_ignored
from caracole.web.jobs import Job, version_steps
from caracole.web.pages import Refused
from caracole.web.status import details_href

if TYPE_CHECKING:
    from caracole.sheet_versions import SheetVersion
    from caracole.songs import Song

DOINGS = ("choose", "keep", "clear")
MAX_TAB = 12  # digits: UG's tab ids are seven or eight

ROUTES = (
    Route("GET", "/versions", lambda app, asked: versions_page(app, asked.target)),
    *(Route("POST", f"/versions/{do}", lambda app, asked, form, do=do: versions_post(app, do, form),
            page="the version's page") for do in DOINGS),
)

_NOT_AN_ADDRESS = Refused(400, "Not an address", "That address can't be read.")
_NO_SHEET = Refused(404, "Not found", "There's no such sheet in the library.")
_SOURCES = {"lacuerda": "LaCuerda's sheet", "auto": "the auto-chords sheet"}


@dataclass(frozen=True)
class _Asked:
    """What a versions page or post names: the song, the viewer it came from (its library path) and its folder (as
    a quoted address), the version (None for Go back to caracole's pick), every version, what the song's sheet is
    now, in words, the song's ``[pin]`` tabs that choose its sheet (``caracole versions --clear`` takes out those
    alone, never a Guitar Pro or tab pin) and every one it has, the tabs under ``[block]``, and the viewer Back to
    the sheet opens."""

    song: Song
    sheet: str
    folder: str
    version: SheetVersion | None
    versions: list[SheetVersion]
    the_one: str | None
    sheet_pins: tuple[int, ...]
    pins: tuple[int, ...]
    blocked: frozenset[int]
    back: str  # the viewer to go back to: ``sheet``, or sheet.html once the version whose page that was is the one

    @property
    def pinned(self) -> bool:
        return bool(self.sheet_pins)


def versions_page(app: WebApp, target: str) -> Response:
    """The page of ``GET /versions?…`` (``target`` is the request's)."""
    try:
        params = dict(parse_qsl(urlsplit(target).query, keep_blank_values=True, errors="strict", max_num_fields=10))
    except (UnicodeDecodeError, ValueError):
        raise _NOT_AN_ADDRESS from None
    do = params.get("do", "")
    if do not in DOINGS:
        raise Refused(400, "Not a version", "Make this the one, Keep it or Go back to caracole's pick? The address "
                                            "names none.")
    job_id = params.get("job")
    if job_id is not None and not (job_id.isascii() and job_id.isdigit() and len(job_id) < 12):
        raise _NOT_AN_ADDRESS
    asked = _asked(app, params.get("sheet", ""), params.get("tab", ""), do)
    job = app.queue.job(int(job_id)) if job_id is not None else None
    if job is not None and (job.song_key != asked.song.key or not _runs(job, _steps(do, asked))):
        job = None  # another request's: not this page's to show
    return html_response(200, _body(app, do, asked, job))


def versions_post(app: WebApp, do: str, form: dict[str, str]) -> Response:
    """``POST /versions/<do>``: queue the command, and go to the page that shows how it goes."""
    asked = _asked(app, form.get("sheet", ""), form.get("tab", ""), do)
    why = _cant(do, asked)
    if why is not None:
        raise Refused(409, "Nothing to do", why)
    not_ignored(asked.song, app.overrides())
    song = asked.song
    titles = {"choose": f"Make a version the one: {song.display}", "keep": f"Keep a version of {song.display}",
              "clear": f"Back to caracole's pick: {song.display}"}
    job, _ = app.submit(titles[do], song.key, _steps(do, asked), fetching=True, display=song.display)
    return app.queued(job, f"/versions?{_query(do, asked, job=job.id)}")


# --- what a page or a post names ---------------------------------------------------------------


def _asked(app: WebApp, sheet: str, tab: str, do: str) -> _Asked:
    """The song a viewer's library path names, as caracole wrote that viewer for it, and its version ``tab`` (not
    for ``clear``); raises Refused."""
    from caracole.library import songs_in_folder
    from caracole.render import AUTO_OUTPUTS, HUMAN_OUTPUTS, written_file
    from caracole.sheet_versions import SHEET_PAGE, in_library, sheet_pins
    from caracole.web.app import version_page_tab

    if do != "clear" and not (tab.isascii() and tab.isdigit() and len(tab) <= MAX_TAB):
        raise Refused(400, "Not a version", "Which version? The address names no Ultimate Guitar tab.")
    parts = tuple(sheet.split("/"))
    if len(parts) < 2 or any(p in ("", ".", "..") for p in parts) or not (
            parts[-1] in (HUMAN_OUTPUTS[2], AUTO_OUTPUTS[2]) or version_page_tab(parts[-1]) is not None):
        raise _NO_SHEET
    overrides = app.overrides()
    page_tab = version_page_tab(parts[-1])
    with app.db() as conn:
        songs = songs_in_folder(conn, parts[:-1])
        song = next((s for s in songs if written_file(conn, s.id, parts[-1])), None)
        if song is None and page_tab is not None:
            # A version's page goes once the version is the one (its viewer is sheet.html then): the page asked from
            # it, Make this the one's, still says how that went
            song = next((s for s in songs if any(v.tab_id == page_tab and v.chosen
                                                 for v in in_library(conn, s.id, app.cfg.rank))), None)
            back = f"{'/'.join(parts[:-1])}/{SHEET_PAGE}"
        else:
            back = sheet
        if song is None:
            raise _NO_SHEET
        versions = in_library(conn, song.id, app.cfg.rank)
        the_one = _the_one(conn, song.id, versions)
        pins = tuple(sheet_pins(conn, song.id, overrides.pin.get(song.key, ())))
    version = None
    if do != "clear":
        version = next((v for v in versions if v.tab_id == tab), None)
        if version is None:
            raise Refused(404, "No such version", f"Ultimate Guitar lists no such chords version of {song.display}.")
    return _Asked(song, sheet, "/".join(quote(p) for p in parts[:-1]), version, versions, the_one, pins,
                  tuple(overrides.pin.get(song.key, ())), overrides.block, back)


def _the_one(conn, song_id: int, versions: list[SheetVersion]) -> str | None:
    """The song's sheet now, in words: its UG version ("Ver 1 · 4.5★ (10)"), else the site or the auto-chords sheet
    it is; None for a song that keeps no sheet."""
    from caracole.library import kept_files
    from caracole.songs import AUTO_SHEET, HUMAN_SHEET
    from caracole.versions import get_version

    chosen = next((v for v in versions if v.chosen), None)
    if chosen is not None:
        return _line(chosen)
    files = {f.name: f for f in kept_files(conn, song_id)}
    if HUMAN_SHEET in files:
        provider = get_version(conn, files[HUMAN_SHEET].version_id).provider
        return _SOURCES.get(provider, f"{provider}'s sheet")
    return _SOURCES["auto"] if AUTO_SHEET in files else None


def _cant(do: str, asked: _Asked) -> str | None:
    """Why ``do`` can't be done for what the page names, in one sentence; None when it can."""
    v = asked.version
    if do == "clear":
        return None if asked.pinned else (f"caracole picks the sheet of {asked.song.display} already: no version "
                                          "of yours is pinned in overrides.toml.")
    assert v is not None
    if v.gone:
        return "Ultimate Guitar no longer has this version: it stays listed until the next fetch drops it."
    if int(v.tab_id) in asked.blocked and not v.chosen:
        return ("This version is under [block] in overrides.toml: caracole never uses it. Take it out of [block] "
                "first.")
    if do == "choose" and v.chosen:
        return "This version is the one already: the song's title opens it."
    if do == "keep" and v.kept:
        return ("This version is the one already: the song's title opens it." if v.chosen
                else "This version is kept already, beside the song's sheet.")
    return None


def _steps(do: str, asked: _Asked) -> list[tuple[str, tuple[str, ...]]]:
    """The command ``do`` queues, ``caracole versions``: Make this the one runs ``caracole get --tab`` with the
    tab's own page (UG answers a slugged tab at its slugged address alone), and checks again, when it runs, that
    the tab is still one of the song's versions, UG still has it and it isn't under ``[block]``."""
    song, v = asked.song, asked.version
    tab = v.tab_id if v is not None else None
    return version_steps(song.artist, song.title, keep=tab if do == "keep" else None,
                         choose=tab if do == "choose" else None)


def _runs(job: Job, steps: list[tuple[str, tuple[str, ...]]]) -> bool:
    """Whether the job runs these commands (another request of the song's may have joined it)."""
    held = {step.args for step in job.steps}
    return all(tuple(args) in held for _, args in steps)


def _query(do: str, asked: _Asked, *, job: int | None = None) -> str:
    fields = [("sheet", asked.sheet), ("tab", asked.version.tab_id if asked.version else ""), ("do", do)]
    return urlencode(fields + ([("job", str(job))] if job is not None else []))


# --- the page --------------------------------------------------------------------------------------


def _line(v: SheetVersion, total: int | None = None) -> str:
    """A version in a few words: "Ver 3 · 4.86★ (408)", or with ``total``, "Ver 3 of 13 · 4.86★ (408)"."""
    said = [(f"Ver {v.number}" if v.number else f"Tab {v.tab_id}") + (f" of {total}" if total else "")]
    if v.rating is not None:
        said.append(f"{v.rating:g}★" + (f" ({v.votes:,})" if v.votes is not None else ""))
    return " · ".join(said)


_LABELS = {"choose": "Make this the one", "keep": "Keep it", "clear": "Go back to caracole's pick"}
_TELLS = {
    "choose": ("It becomes the song's sheet: the title opens it, and its PDF and its songbooks use it. caracole looks "
               "the song up with this tab (<code>caracole versions --choose</code>, as <code>caracole get --tab</code> "
               "does) and keeps your choice in overrides.toml "
               "(<code>[pin]</code>)."),
    "keep": ("caracole fetches its page from Ultimate Guitar now (one request, at the lookup pace) and keeps it "
             "beside the song's sheet, with a viewer of its own; the song's sheet stays as it is."),
    "clear": ("caracole takes the song's <code>[pin]</code> out of overrides.toml and looks the song up again: the "
              "title then opens the version it ranks first."),
}
_RUNNING = {"choose": "Making it the one…", "keep": "Fetching the version…", "clear": "Going back to caracole's pick…"}


def _body(app: WebApp, do: str, asked: _Asked, job: Job | None) -> str:
    song, v = asked.song, asked.version
    if v is not None:
        lede = f"{escape(song.display)}: <strong>{escape(_line(v, len(asked.versions)))}</strong>."
        if v.note:
            lede += f" <q>{escape(v.note)}</q>"
    else:
        lede = f"{escape(song.display)}."
    lede = f'<p class="lede">{lede}</p>\n'
    if asked.the_one is not None:
        lede += f"<p>The one now: {escape(asked.the_one)}.</p>\n"
    why = _cant(do, asked)
    if why is not None:
        form = f"<p>{escape(why)}</p>\n"
    else:
        hidden = "".join(f'  <input type="hidden" name="{name}" value="{escape(value, quote=True)}">\n'
                         for name, value in (("csrf", app.csrf), ("sheet", asked.sheet),
                                             ("tab", v.tab_id if v is not None else "")))
        form = (f'<form class="confirm" method="post" action="/versions/{do}">\n{hidden}'
                f'  <button class="btn primary" type="submit">{_LABELS[do]}</button>\n</form>\n'
                f"<p>{_TELLS[do]}</p>\n")
    says, opens = _how_it_goes(app, do, asked, job)
    links = opens
    if v is not None and v.page is not None and v.kept and not v.chosen and not opens:
        links += f'<a class="btn" href="/{asked.folder}/{quote(v.page)}">Open it</a>\n'
    links += f'<a class="btn" href="/{escape(quote(asked.back), quote=True)}">Back to the sheet</a>'
    head = f'<meta http-equiv="refresh" content="{pages.REFRESH}">\n' if job is not None and job.active else ""
    title = {"choose": "Make this the one", "keep": "Keep a version", "clear": "Back to caracole's pick"}[do]
    return pages.page(f"{title} · {song.display}", f'{lede}{form}{says}<div class="confirm">\n{links}\n</div>',
                      head=head)


def _how_it_goes(app: WebApp, do: str, asked: _Asked, job: Job | None) -> tuple[str, str]:
    """The job's state in a sentence, and, once it is done, a link to what it made: the sheet, or the kept
    version's page once caracole wrote it."""
    if job is None:
        return "", ""
    if job.state == "failed":
        last = next((line for step in job.steps for line in reversed(step.output) if line.strip()), "")
        details = f' <a href="/{details_href(job.id)}">Output</a>'
        return f'<p class="says failed">Failed{": " + escape(last) if last else "."}{details}</p>\n', ""
    if job.state != "done":
        state = "Queued: it runs after the requests before it." if job.state == "queued" else _RUNNING[do]
        return f'<p class="says {job.state}">{escape(state)}</p>\n', ""
    if do == "keep":
        assert asked.version is not None
        page = _kept_page(app, asked)
        if page is None:
            why = _stage_detail(job, "version")
            return (f'<p class="says failed">Done, but it wasn\'t kept{": " + escape(why) if why else ""}. See the '
                    f'request\'s <a href="/{details_href(job.id)}">output</a>.</p>\n', "")
        return ('<p class="says done">Done: it is kept beside the sheet.</p>\n',
                f'<a class="btn primary" href="/{asked.folder}/{quote(page)}">Open it</a>\n')
    from caracole.sheet_versions import SHEET_PAGE

    # caracole get exits 0 on a block, a spent budget or the hour's cap, the sheet as it was: what the job did is
    # the song's state, read again, never the command's exit.
    output = f'<a href="/{details_href(job.id)}">output</a>'
    if do == "choose":
        assert asked.version is not None
        if not asked.version.chosen:
            why = _stage_detail(job, "sheet")
            if int(asked.version.tab_id) in asked.pins:
                said = ("Done, and your choice is recorded under [pin] in overrides.toml, but it isn't the song's "
                        "sheet yet: the nightly run, or a later lookup, makes it the one")
            else:
                said = "Done, but it isn't the one"
            return (f'<p class="says waiting">{escape(said)}{": " + escape(why) if why else "."} See the '
                    f"request's {output}.</p>\n", "")
        said = "Done: it is the one now."
    elif asked.pinned:
        return (f'<p class="says failed">Done, but the [pin] is still there: see the request\'s {output}.</p>\n', "")
    else:
        said = "Done: caracole picks the sheet again."
    return (f'<p class="says done">{said}</p>\n',
            f'<a class="btn primary" href="/{asked.folder}/{quote(SHEET_PAGE)}">Open the sheet</a>\n')


def _stage_detail(job: Job, name: str) -> str:
    """What the job's stage ``name`` said when it ended, when it ended skipped or failed ("" else)."""
    stage = next((s for s in job.stages if s.name == name), None)
    return stage.detail.strip().rstrip(".") if stage is not None and stage.state in ("skipped", "failed") else ""


def _kept_page(app: WebApp, asked: _Asked) -> str | None:
    """The kept version's page, once caracole wrote it for the song (render.py's record)."""
    from caracole.render import written_file
    from caracole.sheet_versions import version_names

    assert asked.version is not None
    name = version_names(asked.version.tab_id)[2]
    try:
        with app.db() as conn:
            return name if written_file(conn, asked.song.id, name) is not None else None
    except Refused:
        return None
