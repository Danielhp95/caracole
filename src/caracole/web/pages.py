"""The pages caracole serve writes itself: the requests, the picker, the sign-in page, and errors.

They share index.html's look (``library_page.BASE_STYLE``), carry no script,
and every text in them is escaped. The requests page is one line per request,
the line its song's card shows (status.py), with the commands it ran and what
each printed folded away under it. It refreshes itself every 10 seconds while
a request waits or runs, with a meta refresh: no script. A reload closes what
the reader opened, so a request's output is open when the address asks for it
(``/jobs?job=N``, the cards' Details link), and "Stop refreshing"
(``refresh=0``) leaves the page still.

The picker (``picker_form``) is a song in review's candidates as a radio
group, the same markup and style (``library_page.PICKER_STYLE``) as the cards'
picker: on a page of its own (``review_page``), and under a request that ended
in a review. A reload would undo a choice half made, so a requests page that
refreshes itself links to the picker's page instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from typing import Any

from caracole.library_page import BASE_STYLE, PICKER_STYLE, sha256_source
from caracole.web.jobs import Job, Step
from caracole.web.status import Line

PAGE_STYLE = BASE_STYLE + PICKER_STYLE + """
.waits { display: grid; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
.waits > p { margin: 0; color: var(--review); font-weight: 600; }
.step-note { margin: 6px 0 0; color: var(--review); font-size: .85rem; }
.pick-page { max-width: 46rem; }
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


# --- the picker: a song in review's candidates ----------------------------------------------


@dataclass(frozen=True)
class Pick:
    """A song in review and its candidates (``library_page.review_choices``), for the picker; with
    ``search``, a song not found and what ``caracole search`` finds for it (none yet on the requests
    page, which links to them)."""

    song_id: int
    display: str
    title: str  # as the card shows it (normalize.clean_title)
    artist: str
    choices: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    search: bool = False


def picker_form(pick: Pick, csrf: str, *, focus: bool = False) -> str:
    """The picker's form, as the library page's script builds it on a card: a radio group of the
    candidates and "None of these" (not for search hits: nothing proposed them), "Fetch it now"
    (ticked) and Pick, posted to ``/review``. ``focus``: its first candidate takes the focus when the
    page opens (a page for this alone)."""
    rows = []
    for n, c in enumerate(pick.choices):
        why = " · ".join(str(part) for part in (c.get("why"), f"score {c.get('score') or 0}", c.get("tabs")) if part)
        name = f"{c.get('artist')} – {c.get('title')}"
        href = str(c.get("href") or "")
        page = (f'<a class="choice-link" href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer" '
                f'aria-label="{escape(name, quote=True)} on Ultimate Guitar, in a new tab">UG ↗</a>'
                if href.startswith(("https://", "http://")) else "")
        rows.append(_choice(str(c.get("ref")), f"{c.get('n')}. {name}", why, autofocus=focus and n == 0) + page
                    + "</div>")
    if pick.search:
        hint = ("Your pick goes into overrides.toml under [match], as caracole review --song --pick writes it, "
                "with no [alias]: a hit under another artist's name may be a cover. Fetch it now then asks "
                "Ultimate Guitar for it.")
    else:
        rows.append(_choice("none", "None of these", "caracole drops them for good and goes on looking for the "
                            "song", cls="choice none") + "</div>")
        hint = ("Your answer goes into overrides.toml, as caracole review writes it. Fetch it now then asks "
                "Ultimate Guitar for the song picked; None of these fetches nothing.")
    shown = " ".join(str(c.get("ref")) for c in pick.choices)
    question = f"Which Ultimate Guitar song is “{pick.title}” by {pick.artist}?"
    return (
        '<form class="pick-form" method="post" action="/review">\n'
        f'  <input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">\n'
        f'  <input type="hidden" name="song" value="{pick.song_id}">\n'
        f'  <input type="hidden" name="shown" value="{escape(shown, quote=True)}">\n'
        f'  <fieldset class="choices"><legend>{escape(question)}</legend>\n  ' + "\n  ".join(rows) + "\n  </fieldset>\n"
        '  <div class="pick-row"><label class="pick-check"><input type="checkbox" name="fetch" value="1" checked>'
        'Fetch it now</label><button class="btn primary" type="submit">Pick</button></div>\n'
        f'  <p class="pick-hint">{escape(hint)}</p>\n</form>'
    )


def _choice(value: str, name: str, why: str, *, cls: str = "choice", autofocus: bool = False) -> str:
    """One radio of the picker, in its row (left open, for the row's link)."""
    focus = " autofocus" if autofocus else ""
    return (f'<div class="{cls}"><label class="choice-pick"><input type="radio" name="pick" '
            f'value="{escape(value, quote=True)}" required{focus}><span class="choice-text">'
            f'<span class="choice-name">{escape(name)}</span><span class="choice-why">{escape(why)}</span>'
            "</span></label>")


def review_page(pick: Pick, csrf: str) -> str:
    """A song in review's picker on a page of its own, for the requests page to link to; or a song not
    found's, with what ``caracole search`` finds for it."""
    if pick.search:
        lede = (f'<p class="lede">Nothing in the offline Ultimate Guitar index matched {escape(pick.display)} '
                "closely enough. These are what <code>caracole search</code> finds for its artist and title: pick "
                "one only if it is the song, and caracole writes it under <code>[match]</code>.</p>")
    else:
        lede = (f'<p class="lede">caracole isn\'t sure which Ultimate Guitar song {escape(pick.display)} is. '
                "Pick it here, as <code>caracole review</code> would ask you.</p>")
    return page("Pick the match", f'<div class="pick-page">{lede}{picker_form(pick, csrf, focus=True)}</div>')


def jobs_page(jobs: list[Job], lines: Mapping[int, Line], *, opened: int | None = None,
              refresh: bool = True, picks: Mapping[str, Pick] | None = None, csrf: str = "") -> str:
    """Every request remembered, newest first, a line each (``lines``, by job id), with its commands'
    output folded away, open for ``opened``; ``refresh``: reload while one is active.

    ``picks`` holds the songs of finished requests that now wait for a pick, by song key: the newest
    request of each shows its picker (``picker_form``, posting ``csrf``) under its line, or, while the
    page reloads itself, which would undo a choice half made, a link to the picker's page.
    """
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
        waits = _waits(jobs, picks or {}, csrf, still=not (waiting and refresh))
        picking = {job.id for job in jobs if job.id in waits and _waits_for_pick(job, (picks or {}).get(job.song_key))}
        items = ('<ol class="jobs">\n' + "".join(_job(job, lines.get(job.id), opened=job.id == opened,
                                                      waits=waits.get(job.id, ""), picking=job.id in picking)
                                                 for job in jobs) + "</ol>")
    head = f'<meta http-equiv="refresh" content="{REFRESH}">\n' if waiting and refresh else ""
    return page("Requests", lede + items, head=head)


def _waits(jobs: list[Job], picks: Mapping[str, Pick], csrf: str, *, still: bool) -> dict[int, str]:
    """What the newest finished request of each song that waits for a pick shows under its steps."""
    shown: dict[int, str] = {}
    seen: set[str] = set()
    for job in jobs:  # newest first
        if job.song_key in seen:
            continue
        seen.add(job.song_key)
        pick = picks.get(job.song_key)
        if job.active or pick is None:
            continue
        if pick.search:  # a search costs a moment: the picker's page runs it
            head = "<p>Not in the offline Ultimate Guitar index under this name.</p>"
            body = (f'<p><a class="btn primary" href="/review?song={pick.song_id}">See what caracole search '
                    "finds</a></p>")
        else:
            head = (f"<p>caracole isn't sure which Ultimate Guitar song it is: "
                    f"{len(pick.choices)} candidate{'s' if len(pick.choices) != 1 else ''}.</p>")
            body = (picker_form(pick, csrf) if still else
                    f'<p><a class="btn primary" href="/review?song={pick.song_id}">Pick the match</a></p>')
        shown[job.id] = f'<div class="waits">{head}{body}</div>'
    return shown


# What `caracole fetch --song` says of a song that needs review first (commands/fetch.py).
_NEEDS_REVIEW = "needs review first"


def _waits_for_pick(job: Job, pick: Pick | None) -> bool:
    """Whether a finished request stopped only because its song needs a pick first: the one step that
    failed is its ``caracole fetch --song``, which refused the song as needing review, and the song's
    picker (``pick``) is right under it. Fetch it now is ticked by default, so a request whose
    ``caracole add`` found only candidates ends this way."""
    if pick is None or pick.search or job.state != "failed":
        return False
    failed = [step for step in job.steps if step.state == "failed"]
    return (len(failed) == 1 and failed[0].args[:1] == ("fetch",)
            and any(_NEEDS_REVIEW in line for line in failed[0].output))


def _when(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else ""


def _badge(state: str, text: str | None = None) -> str:
    return f'<span class="badge {escape(state)}">{escape(text or _STATE_TEXT.get(state, state))}</span>'


def _says(line: Line | None, job: Job) -> str:
    """The request's line, as its card says it."""
    if line is None:
        return f'<span class="says">{escape(_STATE_TEXT.get(job.state, job.state))}</span>'
    link = ""
    if line.link is not None:
        label, href = line.link
        link = f' · <a href="{escape(href, quote=True)}">{escape(label)}</a>'
    return f'<span class="says {escape(line.tone)}">{escape(line.text)}{link}</span>'


def _job(job: Job, line: Line | None, *, opened: bool = False, waits: str = "", picking: bool = False) -> str:
    """One line: the song and how its request goes; under it, folded, what each command printed, and, in
    ``waits``, its song's picker. ``picking``: it stopped only because the song needs a pick first
    (``_waits_for_pick``), so its fetch waits for one rather than failed."""
    meta = f"{escape(job.title)} · requested {_when(job.queued_at)}"
    if job.note:
        meta += f" · {escape(job.note)}"
    steps = "".join(_step(step, picking=picking and step.state == "failed") for step in job.steps)
    return (
        f'<li class="job" id="job-{job.id}">'
        f'<p class="line"><span class="song">{escape(job.display or job.title)}</span>{_says(line, job)}</p>'
        f'<details class="output"{" open" if opened else ""}><summary>Output</summary>'
        f'<p class="meta">{meta}</p><ol class="steps">{steps}</ol></details>{waits}</li>\n'
    )


def _step(step: Step, *, picking: bool = False) -> str:
    """A step: its label, how it went, and the last lines it printed; with ``picking``, the fetch that
    waits for a pick: a note before its error."""
    output = note = ""
    if picking:
        note = ('<p class="step-note">Not fetched yet: caracole fetch waits for the match. Pick it below, with '
                "Fetch it now ticked, and it is fetched then.</p>")
    if step.output or step.dropped:
        lines = ([f"… {step.dropped} earlier lines"] if step.dropped else []) + step.output
        output = "<pre>" + escape("\n".join(lines)) + "</pre>"
    badge = _badge("review", "Waits for a pick") if picking else _badge(step.state)
    return (f'<li class="step {escape(step.state)}"><div class="step-head"><span>{escape(step.label)}</span>'
            f"{badge}</div>{note}{output}</li>")


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
