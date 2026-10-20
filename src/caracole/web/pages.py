"""The pages caracole serve writes itself: the requests, the sign-in page, and errors.

They share index.html's look (``library_page.BASE_STYLE``), carry no script,
and every text in them is escaped. The requests page is one line per request,
the line its song's card shows (status.py), with the commands it ran and what
each printed folded away under it. It refreshes itself every 10 seconds while
a request waits or runs, with a meta refresh: no script. A reload closes what
the reader opened, so a request's output is open when the address asks for it
(``/jobs?job=N``, the cards' Details link), and "Stop refreshing"
(``refresh=0``) leaves the page still.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from html import escape

from caracole.library_page import BASE_STYLE, sha256_source
from caracole.web.jobs import Job, Step
from caracole.web.status import Line

PAGE_STYLE = BASE_STYLE + """
.lede { max-width: 72ch; margin: 4px 0 20px; color: var(--muted); }
.jobs { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.job { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 2px 12px;
  padding: 10px 14px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface);
  box-shadow: var(--shadow); scroll-margin-top: 16px; }
.job .line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 10px; min-height: 32px; margin: 0;
  padding-top: 5px; overflow-wrap: anywhere; }
.job .song { font-weight: 650; }
.says { color: var(--muted); font-size: .92rem; }
.says.ready { color: var(--found); }
.says.queued, .says.running, .says.waiting { color: var(--wanted); }
.says.review { color: var(--review); }
.says.failed { color: var(--failed); }
.says a { font-weight: 600; }
.output > summary { display: flex; align-items: center; min-height: 32px; color: var(--muted); font-size: .85rem;
  font-weight: 600; list-style: none; cursor: pointer; }
.output > summary::-webkit-details-marker { display: none; }
.output > summary::before { content: "›"; display: inline-block; width: 1em; font-size: 1.15rem; line-height: 1;
  text-align: center; }
.output[open] > summary::before { transform: rotate(90deg); }
.output[open] { grid-column: 1 / -1; }
.meta { margin: 2px 0 8px; color: var(--muted); font-size: .85rem; }
.steps { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.step { padding: 8px 10px; border-radius: 10px; background: var(--raised); }
.step-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: .92rem;
  font-weight: 600; }
.badge.waiting, .badge.skipped { color: var(--ignored); background: var(--ignored-bg); }
pre { max-height: 22rem; margin: 6px 0 0; padding: 10px; overflow: auto; border-radius: 8px; background: var(--bg);
  font: .8rem/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.empty { margin: 24px 0; }
.sign-in { display: grid; gap: 14px; max-width: 26rem; padding: 16px; border: 1px solid var(--border);
  border-radius: 16px; background: var(--surface); }
.error { margin: 0; color: var(--failed); font-weight: 600; }
.message { max-width: 72ch; }
.sub { margin: 18px 0 6px; font-size: 1rem; }
.plan { max-width: 72ch; margin: 0; padding-left: 1.2em; overflow-wrap: anywhere; }
.plan li + li { margin-top: 4px; }
.confirm { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
.btn.danger { min-height: 44px; background: var(--failed); border-color: var(--failed); color: var(--bg);
  font-weight: 650; }
"""

# No script; forms post only to the server; nothing else loads.
PAGE_CSP = (f"default-src 'none'; style-src {sha256_source(PAGE_STYLE)}; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'")

_STATE_TEXT = {"queued": "Queued", "running": "Running", "done": "Done", "failed": "Failed",
               "waiting": "Waiting", "skipped": "Skipped"}


def page(title: str, body: str, *, head: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="no-referrer">\n'
        f"{head}<title>{escape(title)} · caracole</title>\n<style>{PAGE_STYLE}</style>\n</head>\n<body>\n"
        '<div class="page">\n<header class="masthead">\n  <div>\n'
        '    <p class="app"><a href="/">caracole</a></p>\n'
        f"    <h1>{escape(title)}</h1>\n  </div>\n"
        '  <nav class="links" aria-label="Pages"><a class="navlink" href="/">Library</a></nav>\n</header>\n'
        f"{body}\n</div>\n</body>\n</html>\n"
    )


REFRESH = 10  # seconds between reloads while a request waits or runs


def jobs_page(jobs: list[Job], lines: Mapping[int, Line], *, opened: int | None = None,
              refresh: bool = True) -> str:
    """Every request remembered, newest first, a line each (``lines``, by job id), with its commands'
    output folded away, open for ``opened``; ``refresh``: reload while one is active."""
    waiting = any(job.active for job in jobs)
    kept = f"job={opened}&" if opened is not None else ""
    if not waiting:
        note = ""
    elif refresh:
        note = (f"This page refreshes itself every {REFRESH} seconds while one waits or runs. "
                f'<a href="/jobs?{escape(kept)}refresh=0">Stop refreshing</a>')
    else:
        again = f"/jobs?job={opened}" if opened is not None else "/jobs"
        note = f'This page stays as it is: <a href="{again}">refresh it</a> to see how they go.'
    lede = (
        '<p class="lede">Requests run one at a time, each a caracole command under its lock, with the same '
        f"pauses between requests as from a terminal. {note}</p>"
    )
    if not jobs:
        items = '<p class="empty">No requests yet. Request a song from <a href="/">the library</a>.</p>'
    else:
        items = ('<ol class="jobs">\n' + "".join(_job(job, lines.get(job.id), opened=job.id == opened)
                                                 for job in jobs) + "</ol>")
    head = f'<meta http-equiv="refresh" content="{REFRESH}">\n' if waiting and refresh else ""
    return page("Requests", lede + items, head=head)


def _when(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else ""


def _badge(state: str) -> str:
    return f'<span class="badge {escape(state)}">{escape(_STATE_TEXT.get(state, state))}</span>'


def _says(line: Line | None, job: Job) -> str:
    """The request's line, as its card says it."""
    if line is None:
        return f'<span class="says">{escape(_STATE_TEXT.get(job.state, job.state))}</span>'
    link = ""
    if line.link is not None:
        label, href = line.link
        link = f' · <a href="{escape(href, quote=True)}">{escape(label)}</a>'
    return f'<span class="says {escape(line.tone)}">{escape(line.text)}{link}</span>'


def _job(job: Job, line: Line | None, *, opened: bool = False) -> str:
    """One line: the song and how its request goes; under it, folded, what each command printed."""
    meta = f"{escape(job.title)} · requested {_when(job.queued_at)}"
    if job.note:
        meta += f" · {escape(job.note)}"
    steps = "".join(_step(step) for step in job.steps)
    return (
        f'<li class="job" id="job-{job.id}">'
        f'<p class="line"><span class="song">{escape(job.display or job.title)}</span>{_says(line, job)}</p>'
        f'<details class="output"{" open" if opened else ""}><summary>Output</summary>'
        f'<p class="meta">{meta}</p><ol class="steps">{steps}</ol></details></li>\n'
    )


def _step(step: Step) -> str:
    """A step: its label, how it went, and the last lines it printed."""
    output = ""
    if step.output or step.dropped:
        lines = ([f"… {step.dropped} earlier lines"] if step.dropped else []) + step.output
        output = "<pre>" + escape("\n".join(lines)) + "</pre>"
    return (f'<li class="step {escape(step.state)}"><div class="step-head"><span>{escape(step.label)}</span>'
            f"{_badge(step.state)}</div>{output}</li>")


def sign_in_page(csrf: str, *, failed: bool = False) -> str:
    error = '<p class="error">That isn\'t the access token.</p>' if failed else ""
    form = (
        '<form class="sign-in" method="post" action="/login">\n'
        f'  <input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">\n'
        '  <label class="f">Access token<input type="password" name="token" required '
        'autocomplete="current-password"></label>\n'
        f'  {error}<button class="btn primary" type="submit">Sign in</button>\n</form>'
    )
    lede = ('<p class="lede">This caracole asks for the access token its owner set '
            "(<code>--token-file</code>). Your browser keeps you signed in.</p>")
    return page("Sign in", lede + form)


def remove_page(display: str, song_id: int, key: str, csrf: str, goes: list[str], stays: list[str],
                notes: list[str], *, waiting: int = 0) -> str:
    """Whether to remove a song, with what goes and what stays (``removal.describe``); the form confirms it."""
    after = (f" It runs after the {waiting} request{'s' if waiting != 1 else ''} queued before it."
             if waiting else "")
    lede = ('<p class="lede">Remove it queues <code>caracole remove</code> for this song, as every request is '
            f"queued.{escape(after)}</p>")

    def items(heading: str, lines: list[str]) -> str:
        if not lines:
            return ""
        return (f'<h2 class="sub">{escape(heading)}</h2>\n<ul class="plan">'
                + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ul>\n")

    hidden = "".join(f'  <input type="hidden" name="{name}" value="{escape(str(value), quote=True)}">\n'
                     for name, value in (("csrf", csrf), ("song", song_id), ("key", key), ("confirm", "1")))
    form = ('<form class="confirm" method="post" action="/remove">\n' + hidden
            + '  <button class="btn danger" type="submit">Remove it</button>\n'
            '  <a class="btn" href="/">Keep it</a>\n</form>')
    said = "".join(f'<p class="message">{escape(note)}</p>\n' for note in notes)
    return page(f"Remove {display}?", lede + items("It takes", goes) + items("It leaves", stays) + said + form)


def message_page(title: str, message: str) -> str:
    """An error, said plainly, and the way back."""
    return page(title, f'<p class="message">{escape(message)}</p>\n'
                       '<p><a class="btn" href="/">Back to the library</a></p>')
