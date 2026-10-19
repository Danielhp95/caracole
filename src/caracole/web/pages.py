"""The pages caracole serve writes itself: the requests, the sign-in page, and errors.

They share index.html's look (``library_page.BASE_STYLE``), carry no script,
and every text in them is escaped. The requests page refreshes itself every
10 seconds while a request waits or runs, with a meta refresh: no script. A
reload closes what the reader opened, so the newest request's output is open
already, with any step's that runs or failed, and "Stop refreshing"
(``/jobs?refresh=0``) leaves the page still.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from caracole.library_page import BASE_STYLE, sha256_source
from caracole.web.jobs import Job, Step

PAGE_STYLE = BASE_STYLE + """
.lede { max-width: 72ch; margin: 4px 0 20px; color: var(--muted); }
.jobs { display: grid; gap: 12px; }
.job { padding: 14px 16px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface);
  box-shadow: var(--shadow); }
.job-head, .step-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.job h2 { margin: 0; font-size: 1.05rem; line-height: 1.3; overflow-wrap: anywhere; }
.meta { margin: 4px 0 10px; color: var(--muted); font-size: .85rem; }
.steps { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.step { padding: 8px 10px; border-radius: 10px; background: var(--raised); }
.step-head { align-items: center; font-size: .92rem; font-weight: 600; }
.badge.waiting, .badge.skipped { color: var(--ignored); background: var(--ignored-bg); }
details summary { margin-top: 6px; color: var(--muted); font-size: .82rem; font-weight: 600; cursor: pointer; }
pre { max-height: 22rem; margin: 6px 0 0; padding: 10px; overflow: auto; border-radius: 8px; background: var(--bg);
  font: .8rem/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.empty { margin: 24px 0; }
.sign-in { display: grid; gap: 14px; max-width: 26rem; padding: 16px; border: 1px solid var(--border);
  border-radius: 16px; background: var(--surface); }
.error { margin: 0; color: var(--failed); font-weight: 600; }
.message { max-width: 72ch; }
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


def jobs_page(jobs: list[Job], *, refresh: bool = True) -> str:
    """Every request remembered, newest first, with each step's output; ``refresh``: reload while one is active."""
    waiting = any(job.active for job in jobs)
    if not waiting:
        note = ""
    elif refresh:
        note = (f"This page refreshes itself every {REFRESH} seconds while one waits or runs. "
                '<a href="/jobs?refresh=0">Stop refreshing</a>')
    else:
        note = 'This page stays as it is: <a href="/jobs">refresh it</a> to see how they go.'
    lede = (
        '<p class="lede">Requests run one at a time, each a caracole command under its lock, with the same '
        f"pauses between requests as from a terminal. {note}</p>"
    )
    if not jobs:
        items = '<p class="empty">No requests yet. Request a song from <a href="/">the library</a>.</p>'
    else:
        items = '<div class="jobs">' + "".join(_job(job, newest=n == 0) for n, job in enumerate(jobs)) + "</div>"
    head = f'<meta http-equiv="refresh" content="{REFRESH}">\n' if waiting and refresh else ""
    return page("Requests", lede + items, head=head)


def _when(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else ""


def _badge(state: str) -> str:
    return f'<span class="badge {escape(state)}">{escape(_STATE_TEXT.get(state, state))}</span>'


def _job(job: Job, *, newest: bool = False) -> str:
    meta = f"Requested {_when(job.queued_at)}"
    if job.note:
        meta += f" · {escape(job.note)}"
    steps = "".join(_step(step, shown=newest) for step in job.steps)
    return (
        f'<article class="job" id="job-{job.id}">\n'
        f'  <div class="job-head"><h2>{escape(job.title)}</h2>{_badge(job.state)}</div>\n'
        f'  <p class="meta">{meta}</p>\n  <ol class="steps">{steps}</ol>\n</article>\n'
    )


def _step(step: Step, *, shown: bool = False) -> str:
    """A step, its output open when ``shown`` (the newest request's) or when it runs or failed."""
    output = ""
    if step.output or step.dropped:
        lines = ([f"… {step.dropped} earlier lines"] if step.dropped else []) + step.output
        opened = " open" if shown or step.state in ("running", "failed") else ""
        output = (f"<details{opened}><summary>Output</summary><pre>"
                  + escape("\n".join(lines)) + "</pre></details>")
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


def message_page(title: str, message: str) -> str:
    """An error, said plainly, and the way back."""
    return page(title, f'<p class="message">{escape(message)}</p>\n'
                       '<p><a class="btn" href="/">Back to the library</a></p>')
