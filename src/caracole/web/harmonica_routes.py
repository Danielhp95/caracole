"""caracole serve's page of how a harmonica tab is read: the readings caracole weighs for it, best first, each with
its Q, and the one that reads it now; any of them pinned in overrides.toml's ``[harmonica]``, harptabs.com's own
notation among them, or the pin taken out, back to caracole's guess.

    GET  /harmonica?page=&job=   the readings of the tab whose page ``page`` is (its library path, a
                          ``harmonica-N.html`` caracole wrote), each with a form that pins it; then, with ``&job=``,
                          how it goes
    POST /harmonica/pin    Read it so: ``caracole harmonica --tab=… --as=… [--symbol=…]`` queued (``as``: a notation's
                          name, "legend", or a table as JSON, ``{"as": "signs", "*": "bend"}``), and back to the page
    POST /harmonica/clear  Back to caracole's guess: ``caracole harmonica --tab=… --clear`` queued

A harmonica tab's page served from the library runs in a sandbox, with no way to post a form to the server, so its
Read as line (or, for a tab read by harptabs.com's own key or shown as written, a link at its foot) links ``GET
/harmonica?page=…``, a page of the server's own with no script, whose forms ``POST`` with the form token like the
others (harptab.js makes the link, served alone). Each post is one command queued, under a key of its own (the song's
key, the tab and the reading, ``jobs.READING``…``jobs.MINE``), so it joins no request of the song's, and the same reading
asked twice is one job. The server writes no overrides.toml itself: the command does, under caracole's lock, then
renders the song again. Once the job is done, the page says what it came to from overrides.toml and the tab, read
again, never from the command's exit.

Each refusal is a ``Refused``: a page that is no harmonica tab's page caracole wrote for a song of the library (404),
a reading that is none (400: no notation's name, no table harptab.py's ``check_spec`` takes), the tab read so already
or no pin to take out (409), and an ignored song.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from caracole.web import pages
from caracole.web.app import Response, Route, WebApp, html_response, not_ignored
from caracole.web.jobs import INTERRUPTED, MINE, READING, Job
from caracole.web.pages import Refused
from caracole.web.status import details_href

if TYPE_CHECKING:
    from caracole.inbox import HarmonicaFile
    from caracole.songs import Song
    from caracole.viewer.harptab import Reading

COMMAND = "harmonica"

ROUTES = (
    Route("GET", "/harmonica", lambda app, asked: harmonica_page(app, asked.target)),
    Route("POST", "/harmonica/pin", lambda app, asked, form: harmonica_post(app, "pin", form),
          page="the tab's page of readings"),
    Route("POST", "/harmonica/clear", lambda app, asked, form: harmonica_post(app, "clear", form),
          page="the tab's page of readings"),
)

_NOT_AN_ADDRESS = Refused(400, "Not an address", "That address can't be read.")
_NO_TAB = Refused(404, "Not found", "There's no such harmonica tab in the library.")
_NOT_A_READING = Refused(400, "Not a reading", "How should it be read? The form names no notation caracole knows.")


@dataclass(frozen=True)
class _Asked:
    """What a page or a post names: the song, the tab's page (its library path) and its folder (quoted), the tab,
    its text, how overrides.toml has it read (``pin``, None for caracole's guess), and how it is read now."""

    song: Song
    page: str
    folder: str
    tab: HarmonicaFile
    text: str
    pin: Any
    now: Reading


def harmonica_page(app: WebApp, target: str) -> Response:
    """The page of ``GET /harmonica?…`` (``target`` is the request's)."""
    try:
        params = dict(parse_qsl(urlsplit(target).query, keep_blank_values=True, errors="strict", max_num_fields=10))
    except (UnicodeDecodeError, ValueError):
        raise _NOT_AN_ADDRESS from None
    job_id = params.get("job")
    if job_id is not None and not (job_id.isascii() and job_id.isdigit() and len(job_id) < 12):
        raise _NOT_AN_ADDRESS
    asked = _asked(app, params.get("page", ""))
    job = app.queue.job(int(job_id)) if job_id is not None else None
    if job is not None and not (job.song_key.startswith(f"{READING}{asked.song.key}:{asked.tab.name}:")
                                and job.steps and job.steps[0].args[:1] == (COMMAND,)):
        job = None  # another request's: not this page's to show
    return html_response(200, _body(app, asked, job))


def harmonica_post(app: WebApp, do: str, form: dict[str, str]) -> Response:
    """``POST /harmonica/<do>``: the command queued, and back to the page, which says how it goes."""
    asked = _asked(app, form.get("page", ""))
    spec = _reading(form.get("as", "")) if do == "pin" else None
    if do == "pin" and spec == asked.pin:
        raise Refused(409, "Nothing to do", "It is read so already, as you set it.")
    if do == "clear" and asked.pin is None:
        raise Refused(409, "Nothing to do", "caracole guesses how it is read already: no [harmonica] entry in "
                                            "overrides.toml pins it.")
    not_ignored(asked.song, app.overrides())
    song, tab = asked.song, asked.tab
    if spec is None:
        title, label, options = f"Back to caracole's guess: {tab.name} of {song.display}", "Going back to " \
            "caracole's guess", ("--clear",)
    else:
        options = (f"--as={spec}",) if isinstance(spec, str) else (
            f"--as={spec.get('as', 'signs')}", *(f"--symbol={k}={v}" for k, v in spec.items() if k != "as"))
        title, label = f"Read {tab.name} of {song.display} as you set it", "Reading the harmonica tab as you set it"
    steps = [(label, (COMMAND, f"--tab={tab.name}", *options, "--", song.artist, song.title))]
    said = "clear" if spec is None else json.dumps(spec, sort_keys=True, ensure_ascii=False)
    job, _ = app.submit(title, f"{READING}{song.key}:{tab.name}:{said}{MINE}", steps, display=song.display,
                        song_id=song.id)
    return app.queued(job, "/harmonica?" + urlencode([("page", asked.page), ("job", str(job.id))]))


# --- what a page or a post names ---------------------------------------------------------------


def _reading(text: str) -> Any:
    """The reading a form posts: a notation's name, "legend", or a table as JSON; Refused (400) else."""
    from caracole.viewer.harptab import check_spec

    spec: Any = text
    if text.startswith("{"):
        try:
            spec = json.loads(text)
        except ValueError:
            raise _NOT_A_READING from None
    try:
        check_spec(spec)
    except ValueError:
        raise _NOT_A_READING from None
    return spec


def _asked(app: WebApp, page: str) -> _Asked:
    """The song and the harmonica tab a page's library path names, as caracole wrote that page for it; raises
    Refused."""
    from caracole.harmonica_cmd import tab_text
    from caracole.inbox import HARMONICA_PAGE, harmonica_files
    from caracole.library import songs_in_folder
    from caracole.render import written_file
    from caracole.viewer.harptab import parse, pinned

    parts = tuple(page.split("/"))
    if len(parts) != 3 or any(p in ("", ".", "..") for p in parts) or not HARMONICA_PAGE.fullmatch(parts[-1]):
        raise _NO_TAB
    overrides = app.overrides()
    with app.db() as conn:
        song = next((s for s in songs_in_folder(conn, parts[:-1]) if written_file(conn, s.id, parts[-1])), None)
        tab = next((t for t in harmonica_files(conn, song.id) if t.page == parts[-1]), None) if song else None
        text = tab_text(app.cfg, conn, song, tab) if tab is not None else None
    if song is None or tab is None or text is None:
        raise _NO_TAB
    pin = overrides.harmonica.get(song.key, {}).get(tab.name)
    notation = None
    if pin is not None:
        try:
            notation = pinned(pin, text)
        except ValueError:
            notation = None
    now = parse(text, harp=tab.harp, notation=notation).reading
    return _Asked(song, page, "/".join(quote(p) for p in parts[:-1]), tab, text, pin, now)


# --- the page --------------------------------------------------------------------------------------


def _said(reading: Reading) -> str:
    return reading.said() or "no hole read"


def _source(reading: Reading) -> str:
    from caracole.harmonica_cmd import SOURCES

    return SOURCES[reading.source]


def _button(spec: Any, reading: Reading) -> str:
    if spec == "legend":
        return "Read it by its own legend"
    if spec == "signs":
        return "As harptabs.com writes it"
    if isinstance(spec, str):
        return f"Read it as {spec}"
    return f"Read it so: {_said(reading)}"


def _form(app: WebApp, asked: _Asked, action: str, button: str, spec: Any = None, *, primary: bool = False) -> str:
    fields = [("csrf", app.csrf), ("page", asked.page)]
    if spec is not None:
        fields.append(("as", spec if isinstance(spec, str) else json.dumps(spec, ensure_ascii=False)))
    hidden = "".join(f'  <input type="hidden" name="{name}" value="{escape(value, quote=True)}">\n'
                     for name, value in fields)
    return (f'<form class="confirm" method="post" action="{action}">\n{hidden}'
            f'  <button class="btn{" primary" if primary else ""}" type="submit">{escape(button)}</button>\n</form>\n')


def _body(app: WebApp, asked: _Asked, job: Job | None) -> str:
    from caracole.normalize import clean_title
    from caracole.viewer.harptab import parse, pinned, readings, spec_of

    song, tab, now = asked.song, asked.tab, asked.now
    items = []
    listed = readings(asked.text, harp=tab.harp)
    specs = [spec_of(r) for r in listed]
    current = asked.pin if asked.pin is not None else specs[0]
    weighed = listed[specs.index(current)].q if current in specs else now.q  # its Q among the others'
    lede = (f'<p class="lede">{escape(clean_title(song.title))} · {escape(song.artist)}, {escape(tab.name)}</p>\n'
            f"<p>Now: {escape(_said(now))}, {escape(_source(now))} (Q {weighed:.2f}).</p>\n")
    if asked.pin is not None and asked.pin not in specs:  # a pin of yours caracole weighs no candidate for
        listed.insert(0, now)
        specs.insert(0, asked.pin)
    if "signs" not in specs:  # harptabs.com's own key, always offered: a reading alike, but less common, took its place
        listed.append(parse(asked.text, harp=tab.harp, notation=pinned("signs", asked.text)).reading)
        specs.append("signs")
    for reading, spec in zip(listed, specs):
        mine = spec == current
        form = "" if mine and asked.pin is not None else _form(app, asked, "/harmonica/pin", _button(spec, reading),
                                                                spec)
        items.append(f'<li class="reading{" now" if mine else ""}"><span class="said">{escape(_said(reading))}</span> '
                     f'<span class="q">Q {reading.q:.2f}{" · now" if mine else ""}</span>\n{form}</li>')
    body = (lede + '<h2 class="sub">The ways caracole weighs, best first</h2>\n<ul class="readings">\n'
            + "\n".join(items) + "\n</ul>\n")
    if asked.pin is not None:
        body += _form(app, asked, "/harmonica/clear", "Back to caracole's guess")
    body += ("<p>caracole reads a harmonica tab in each notation it knows and keeps the one that explains the most "
             "of it as notes a harmonica plays (Q). One you choose here is kept in overrides.toml "
             "(<code>[harmonica]</code>), and the tab's page is made again.</p>\n")
    body += _how_it_goes(asked, job)
    head = f'<meta http-equiv="refresh" content="{pages.REFRESH}">\n' if job is not None and job.active else ""
    back = f'<a class="btn" href="/{asked.folder}/{quote(tab.page)}">Back to the tab</a>'
    return pages.page(f"How it's read · {song.display}", f'{body}<div class="confirm">\n{back}\n</div>', head=head,
                      library_name=app.library_name)


def _how_it_goes(asked: _Asked, job: Job | None) -> str:
    """The job's state in a sentence, and once it is done, what it came to: overrides.toml, read again."""
    if job is None:
        return ""
    if job.state == "failed":
        last = next((line for step in job.steps for line in reversed(step.output) if line.strip()), "")
        return (f'<p class="says failed">Failed{": " + escape(last) if last else "."} '
                f'<a href="/{escape(details_href(job.id), quote=True)}">Output</a></p>\n')
    if job.state == "cancelled":
        return '<p class="says cancelled">Cancelled before it ran.</p>\n'
    if job.state == INTERRUPTED:  # a restart stopped it before it was over (history.py)
        details = f' <a href="/{escape(details_href(job.id), quote=True)}">Output</a>'
        return ('<p class="says waiting">Interrupted: caracole serve stopped before it was over.'
                f'{details}</p>\n')
    if job.state != "done":
        state = ("Queued: it runs after the requests before it." if job.state == "queued"
                 else "Reading it as you set it…")
        return f'<p class="says {job.state}">{escape(state)}</p>\n'
    clearing = "--clear" in job.steps[0].args
    if clearing:
        if asked.pin is None:
            return '<p class="says done">Done: caracole guesses how it is read again.</p>\n'
        return (f'<p class="says failed">Done, but the [harmonica] entry is still there: see the request\'s '
                f'<a href="/{escape(details_href(job.id), quote=True)}">output</a>.</p>\n')
    if asked.pin is None:
        return (f'<p class="says failed">Done, but no [harmonica] entry pins it: see the request\'s '
                f'<a href="/{escape(details_href(job.id), quote=True)}">output</a>.</p>\n')
    return f'<p class="says done">Done: read as {escape(_said(asked.now))}, as you set it.</p>\n'
