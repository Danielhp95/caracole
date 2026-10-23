"""The pages caracole serve writes itself: the requests, the picker, Remove's question, and errors.

They share index.html's look (library_assets/base.css, ``BASE_STYLE``), carry no script,
and every text in them is escaped. The requests page (``jobs_page``) says, under
Now, the request that runs, as a card with its steps (outcome.py's), and those
queued under it in order, each with Cancel (a form, posted with the form token);
then the finished ones, newest first under Today and Earlier (when each ended, in
the server's local time zone), each with its outcome as a coloured word, its
reason, when it ended and its next step, a link or a one-button form
(outcome.py's ``Outcome``). Every request keeps the commands it ran and what each
printed folded away under Output (a lookup's stages first, each with how it went
and why). It refreshes itself every 10 seconds while a request waits or runs,
with a meta refresh: no script. A reload closes what the reader opened, so a
request's output is open when the address asks for it (``/jobs?job=N``, the
cards' Details link), and "Stop refreshing" (``refresh=0``) leaves the page still.

The picker (``picker_form``) is a song in review's candidates as a radio
group, the same markup and style (library_assets/picker.css) as the cards'
picker: on a page of its own (``review_page``), and under a request that ended
in a review. A reload would undo a choice half made, so a requests page that
refreshes itself leaves it out: the request's Pick the match opens the picker's page.

A request the server turns down is ``Refused``, which a route raises and app.py
answers with ``message_page``, or, to a page's script, as data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING, Any

from caracole.inline import sha256_source
from caracole.library_assets import BASE_STYLE, PICKER_STYLE
from caracole.page_icon import LINK as PAGE_ICON
from caracole.stamps import shown, stamp

if TYPE_CHECKING:  # songbooks.py imports Refused, and status.py imports songbooks.py
    from caracole.web.jobs import Job, Stage, Step
    from caracole.web.outcome import Action, Outcome
    from caracole.web.status import Line

PAGE_STYLE = BASE_STYLE + PICKER_STYLE + """
.waits { display: grid; grid-column: 1 / -1; gap: 8px; margin-top: 12px; padding-top: 12px;
  border-top: 1px solid var(--border); }  /* under the whole request: its line and its Output */
.waits > p { margin: 0; color: var(--review); font-weight: 600; }
.step-note { margin: 6px 0 0; color: var(--review); font-size: .85rem; }
.pick-page { max-width: 46rem; }
.lede { max-width: 72ch; margin: 4px 0 20px; color: var(--muted); }
.group { margin: 22px 0 8px; color: var(--muted); font-size: .78rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; }
.jobs { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.job { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 6px 12px;
  padding: 10px 14px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface);
  box-shadow: var(--shadow); scroll-margin-top: 16px; }
.job .line { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; min-height: 32px; margin: 0;
  overflow-wrap: anywhere; }
.job .song { font-weight: 650; }
.job .ago { color: var(--muted); font-size: .88rem; }
.says { padding: 2px 10px; border-radius: 999px; font-size: .8rem; font-weight: 650; white-space: nowrap;
  color: var(--ignored); background: var(--ignored-bg); }
.says.ready, .says.removed, .says.done { color: var(--found); background: var(--found-bg); }
.says.running, .says.added { color: var(--auto); background: var(--auto-bg); }
.says.waiting, .says.missing { color: var(--wanted); background: var(--wanted-bg); }
.says.review { color: var(--review); background: var(--review-bg); }
.says.failed { color: var(--failed); background: var(--failed-bg); }
.reason { margin: 0; color: var(--muted); font-size: .9rem; overflow-wrap: anywhere; }
.next { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.next form { margin: 0; }
.btn.act { min-height: 44px; }
.when { color: var(--muted); font-size: .85rem; white-space: nowrap; font-variant-numeric: tabular-nums; }
.card.running { padding: 14px 16px; border-color: color-mix(in srgb, var(--auto) 45%, var(--border)); }
.card.running .song { font-size: 1.15rem; }
.progress { display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0 0; padding: 0; list-style: none; }
.chip { flex: 1 1 auto; min-width: 4.5rem; padding: 5px 8px; border-radius: 8px; background: var(--raised);
  color: var(--muted); font-size: .8rem; font-weight: 600; text-align: center; }
.chip.done { color: var(--found); background: var(--found-bg); }
.chip.running { color: var(--auto); background: var(--auto-bg); font-weight: 750;
  box-shadow: inset 0 0 0 1px var(--auto); }
.chip.failed { color: var(--failed); background: var(--failed-bg); }
/* On a phone, a request's parts stack: its line, the reason, the steps; its next step with Output beside it. */
.job .line, .reason, .progress, .waits, .output, .output[open] { grid-column: 1 / -1; }
.job .next { grid-column: 1; }
.job.over .output:not([open]), .job.queued .output:not([open]) { grid-column: 2; }
@media (min-width: 640px) {
  /* The song's line and the reason; beside them the next step, when it ended, and Output, which unfolds under
     the whole request. */
  .job { grid-template-columns: minmax(0, 1fr) auto auto; }
  .job .line .says { margin-left: auto; }  /* the outcome at the end of the song's line */
  .job.over .line, .job.queued .line { grid-column: 1; grid-row: 1; }
  .job.over .reason { grid-column: 1; grid-row: 2; }
  .job .next { grid-column: 2; grid-row: 1 / span 2; justify-content: flex-end; }
  .job.over .output:not([open]), .job.queued .output:not([open]) { grid-column: 3; grid-row: 1 / span 2; }
  .output[open] { grid-row: 3; }
  .card.running .line, .progress { grid-column: 1 / -1; }
}
.output > summary { display: inline-flex; align-items: center; min-height: 44px; color: var(--muted); font-size: .85rem;
  font-weight: 600; list-style: none; cursor: pointer; }
.output > summary::-webkit-details-marker { display: none; }
.output > summary::before { content: "›"; display: inline-block; width: 1em; font-size: 1.15rem; line-height: 1;
  text-align: center; }
.output[open] > summary::before { transform: rotate(90deg); }
.meta { margin: 2px 0 8px; color: var(--muted); font-size: .85rem; }
.steps { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.steps.stages { margin-bottom: 8px; }  /* a lookup's stages, above the one command that ran them */
.step { padding: 8px 10px; border-radius: 10px; background: var(--raised); }
.step-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: .92rem;
  font-weight: 600; }
.badge.waiting, .badge.skipped { color: var(--ignored); background: var(--ignored-bg); }
pre { max-height: 22rem; margin: 6px 0 0; padding: 10px; overflow: auto; border-radius: 8px; background: var(--bg);
  font: .8rem/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.empty { margin: 24px 0; }
.message { max-width: 72ch; }
.sub { margin: 18px 0 6px; font-size: 1rem; }
.plan { max-width: 72ch; margin: 0; padding-left: 1.2em; overflow-wrap: anywhere; }
.plan li + li { margin-top: 4px; }
.confirm { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
.btn.danger { min-height: 44px; background: var(--failed); border-color: var(--failed); color: var(--bg);
  font-weight: 650; }
"""

# No script; forms post only to the server; nothing else loads. The one image is the page's icon, inline
# (page_icon.py).
PAGE_CSP = (f"default-src 'none'; style-src {sha256_source(PAGE_STYLE)}; img-src data:; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'")

_STATE_TEXT = {"queued": "Queued", "running": "Running", "done": "Done", "failed": "Failed",
               "waiting": "Waiting", "skipped": "Skipped"}


def page(title: str, body: str, *, head: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="same-origin">\n'
        f"{head}{PAGE_ICON}<title>{escape(title)} · caracole</title>\n<style>{PAGE_STYLE}</style>\n</head>\n<body>\n"
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


def jobs_page(jobs: list[Job], lines: Mapping[int, Line], *, outcomes: Mapping[int, Outcome] | None = None,
              opened: int | None = None, refresh: bool = True, picks: Mapping[str, Pick] | None = None,
              csrf: str = "", now: datetime | None = None) -> str:
    """Every request remembered (``jobs``, newest first): now, the one that runs, as a card with its steps,
    and those queued under it in order, each with Cancel; then the feed, the finished ones newest first
    under Today and Earlier (by when each finished, in the server's local time zone), each with its
    outcome (``outcomes``, by job id: outcome.py's, else read from its line in ``lines``), its reason,
    when it finished and its next step. Every request keeps its commands' output folded away, open for
    ``opened``; ``refresh``: reload while one is active; ``now``: the page's time (the clock's).

    ``picks`` holds the songs of finished requests that now wait for a pick, by song key: the newest
    request of each shows its picker (``picker_form``, posting ``csrf``) under its line while the page
    stays still; while it reloads itself, which would undo a choice half made, its Pick the match is
    the way to the picker's page.
    """
    from caracole.web.outcome import outcome

    now = now or datetime.now(UTC)
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
        '<p class="lede">Requests run one at a time, each a caracole command under its lock, as from a '
        "terminal: a song looked up now is one <code>caracole get</code>, a few requests about a second apart. "
        f"{note}</p>"
    )
    if not jobs:
        items = '<p class="empty">No requests yet. Request a song from <a href="/">the library</a>.</p>'
        return page("Requests", lede + items)
    pending = _waiting_picks(jobs, picks or {})
    waits = _waits(pending, csrf, still=not (waiting and refresh))
    picking = {job_id for job_id, pick in pending.items()
               if _waits_for_pick(next(job for job in jobs if job.id == job_id), pick)}

    def output(job: Job) -> str:
        return _output(job, opened=job.id == opened, picking=job.id in picking)

    active = sorted((job for job in jobs if job.active), key=lambda job: (job.state != "running", job.id))
    queued = [job for job in active if job.state == "queued"]
    now_items = [
        _running(job, lines.get(job.id), now, output(job)) if job.state == "running"
        else _queued(job, queued.index(job) + 1, csrf, output(job)) for job in active]
    over = sorted((job for job in jobs if not job.active),
                  key=lambda job: (job.finished_at or job.queued_at, job.id), reverse=True)
    today = now.astimezone().date()
    groups: dict[str, list[str]] = {"Today": [], "Earlier": []}
    for job in over:
        said = (outcomes or {}).get(job.id)
        if said is None:
            line = lines.get(job.id)
            said = outcome(job, line) if line is not None else None
        ended = (job.finished_at or job.queued_at).astimezone()
        group = "Today" if ended.date() == today else "Earlier"
        shown_below = waits.get(job.id, "")
        if said is not None and pending.get(job.id) is not None and pending[job.id].search and _leads(
                said, f"/review?song={pending[job.id].song_id}"):
            shown_below = ""  # what caracole search finds is its next step already, in its row
        groups[group].append(_finished(job, said, ended, csrf, output(job), shown_below, day=group != "Today"))
    sections = []
    if now_items:
        sections.append(_section("now", "Now", now_items))
    sections += [_section(name.lower(), name, shown) for name, shown in groups.items() if shown]
    head = f'<meta http-equiv="refresh" content="{REFRESH}">\n' if waiting and refresh else ""
    return page("Requests", lede + "\n".join(sections), head=head)


def _section(slug: str, name: str, items: list[str]) -> str:
    return (f'<section class="requests {slug}" aria-labelledby="h-{slug}"><h2 class="group" id="h-{slug}">'
            f'{escape(name)}</h2>\n<ol class="jobs">\n{"".join(items)}</ol></section>')


def _says(tone: str, text: str) -> str:
    return f'<span class="says {escape(tone)}">{escape(text)}</span>'


def _song(job: Job) -> str:
    return f'<span class="song">{escape(job.display or job.title)}</span>'


def _running(job: Job, line: Line | None, now: datetime, output: str) -> str:
    """The request that runs: its song, how long ago it started, its line, and its steps (outcome.steps)."""
    from caracole.web.outcome import steps

    text = line.text if line is not None else _STATE_TEXT["running"]
    ago = (f'<span class="ago">started {_ago(job.started_at, now)}</span>' if job.started_at is not None else "")
    chips = []
    for chip in steps(job):
        mark = {"done": "✓ ", "failed": "✕ "}.get(chip.state, "")
        current = ' aria-current="step"' if chip.state == "running" else ""
        state = f'<span class="visually-hidden">: {escape(_STATE_TEXT.get(chip.state, chip.state).lower())}</span>'
        chips.append(f'<li class="chip {escape(chip.state)}"{current}><span aria-hidden="true">{mark}</span>'
                     f"{escape(chip.name)}{state}</li>")
    progress = f'<ol class="progress" aria-label="Steps">{"".join(chips)}</ol>' if chips else ""
    return (f'<li class="job card running" id="job-{job.id}"><p class="line">{_song(job)}{ago}'
            f'{_says("running", text)}</p>{progress}{output}</li>\n')


def _queued(job: Job, place: int, csrf: str, output: str) -> str:
    """A request that waits: its song, its place ("next", "3rd") and Cancel, which takes it out of the queue."""
    cancel = _form("/jobs/cancel", (("job", str(job.id)),), "Cancel", csrf,
                   aria=f"Cancel the request for {job.display or job.title}")
    return (f'<li class="job card queued" id="job-{job.id}"><p class="line">{_song(job)}'
            f'{_says("queued", f"Queued, {_ordinal(place)}")}</p><div class="next">{cancel}</div>{output}</li>\n')


# The next steps that are the request's way on; the others (Try again, Request by name…) are plain buttons.
_PRIMARY = frozenset({"Open", "Pick the match", "Get it from there", "Open songbook", "See what caracole search finds"})


def _leads(said: Outcome, href: str) -> bool:
    """Whether an outcome's next step, or the one beside it, is a link to ``href``."""
    return any(a is not None and a.href == href for a in (said.action, said.also))


def _finished(job: Job, said: Outcome | None, ended: datetime, csrf: str, output: str, waits: str, *,
              day: bool) -> str:
    """A finished request: its song and outcome, the reason, its next step and when it finished (with its day
    for one before today)."""
    if said is None:
        said_html, reason, action = _says(job.state, _STATE_TEXT.get(job.state, job.state)), "", ""
    else:
        said_html = _says(said.tone, said.word)
        reason = f'<p class="reason">{escape(said.reason)}</p>' if said.reason else ""
        action = _action(said.action, csrf) + _action(said.also, csrf, primary=False)
    shown = f"{ended.day} {ended:%b}, {ended:%H:%M}" if day else f"{ended:%H:%M}"
    when = f'<time class="when" datetime="{stamp(ended)}">{escape(shown)}</time>'
    return (f'<li class="job over {escape(job.state)}" id="job-{job.id}"><p class="line">{_song(job)}{said_html}'
            f'</p>{reason}<div class="next">{action}{when}</div>{output}{waits}</li>\n')


def _action(a: Action | None, csrf: str, *, primary: bool = True) -> str:
    """A next step: a link, or a one-button form posted with the form token; "" for none. ``primary``: drawn as
    the request's way on when it is one (``_PRIMARY``); the one beside it is a plain button."""
    if a is None:
        return ""
    cls = "btn act primary" if primary and a.label in _PRIMARY else "btn act"
    if a.post is not None:
        return _form(a.post, a.fields, a.label, csrf, cls=cls)
    if a.href is not None:
        return f'<a class="{cls}" href="{escape(a.href, quote=True)}">{escape(a.label)}</a>'
    return ""


def _form(action: str, fields: Sequence[tuple[str, str]], label: str, csrf: str, *, cls: str = "btn act",
          aria: str = "") -> str:
    """A one-button form posted with the form token; ``aria``: the button's name for a screen reader."""
    hidden = "".join(f'<input type="hidden" name="{escape(name, quote=True)}" value="{escape(value, quote=True)}">'
                     for name, value in (("csrf", csrf), *fields))
    named = f' aria-label="{escape(aria, quote=True)}"' if aria else ""
    return (f'<form class="act-form" method="post" action="{escape(action, quote=True)}">{hidden}'
            f'<button class="{escape(cls, quote=True)}" type="submit"{named}>{escape(label)}</button></form>')


def _ago(then: datetime, now: datetime) -> str:
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 60:
        return f"{seconds} s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600} h ago"


def _ordinal(n: int) -> str:
    """A queued request's place: "next", then "2nd", "3rd", "4th"…"""
    if n <= 1:
        return "next"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _waiting_picks(jobs: list[Job], picks: Mapping[str, Pick]) -> dict[int, Pick]:
    """The newest finished request of each song that waits for a pick now, and its song's pick."""
    pending: dict[int, Pick] = {}
    seen: set[str] = set()
    for job in jobs:  # newest first
        if job.song_key in seen:
            continue
        seen.add(job.song_key)
        pick = picks.get(job.song_key)
        if not job.active and pick is not None:
            pending[job.id] = pick
    return pending


def _waits(pending: Mapping[int, Pick], csrf: str, *, still: bool) -> dict[int, str]:
    """What those requests show under their line: for a song the index didn't match, the way to what caracole
    search finds for it; for a song in review, its picker while the page stays still (its Pick the match
    leads to the picker's page otherwise, as a reload would undo a choice half made)."""
    shown: dict[int, str] = {}
    for job_id, pick in pending.items():
        if pick.search:  # a search costs a moment: the picker's page runs it
            shown[job_id] = (f'<div class="waits"><p><a class="btn act" href="/review?song={pick.song_id}">See what '
                             "caracole search finds</a></p></div>")
        elif still:
            head = (f"<p>caracole isn't sure which Ultimate Guitar song it is: "
                    f"{len(pick.choices)} candidate{'s' if len(pick.choices) != 1 else ''}.</p>")
            shown[job_id] = f'<div class="waits">{head}{picker_form(pick, csrf)}</div>'
    return shown


# What `caracole fetch --song` says of a song that needs review first (commands/fetch.py).
_NEEDS_REVIEW = "needs review first"


def _waits_for_pick(job: Job, pick: Pick | None) -> bool:
    """Whether a finished request stopped only because its song needs a pick first: the one step that
    failed is its ``caracole fetch --song``, which refused the song as needing review, or, for a lookup
    (one ``caracole get``, Fetch it now's), its sheet stage was skipped; and the song's picker (``pick``)
    is right under it. Fetch it now is ticked by default, so a request whose match found only candidates
    ends this way."""
    if pick is None or pick.search:
        return False
    if job.stages:
        return job.state == "done" and any(s.name == "sheet" and s.state == "skipped" for s in job.stages)
    if job.state != "failed":
        return False
    failed = [step for step in job.steps if step.state == "failed"]
    return (len(failed) == 1 and failed[0].args[:1] == ("fetch",)
            and any(_NEEDS_REVIEW in line for line in failed[0].output))


def _badge(state: str, text: str | None = None) -> str:
    return f'<span class="badge {escape(state)}">{escape(text or _STATE_TEXT.get(state, state))}</span>'


def _output(job: Job, *, opened: bool = False, picking: bool = False) -> str:
    """What the request ran, folded away under Output: when it was asked for, a lookup's stages, and each
    command with what it printed. ``picking``: it stopped only because the song needs a pick first
    (``_waits_for_pick``), so its fetch waits for one rather than failed."""
    meta = f"{escape(job.title)} · requested {shown(job.queued_at, "", local=True)}"
    if job.note:
        meta += f" · {escape(job.note)}"
    if job.seconds_to_sheet is not None:
        meta += f" · sheet readable after {job.seconds_to_sheet:.1f} s"
    stages = ""
    if job.stages:  # a lookup's, as `caracole get --progress` reports them
        stages = '<ol class="steps stages">' + "".join(
            _stage(s, picking=picking and s.name == "sheet" and s.state == "skipped") for s in job.stages) + "</ol>"
    steps = "".join(_step(step, picking=picking and step.state == "failed") for step in job.steps)
    return (f'<details class="output"{" open" if opened else ""}><summary>Output</summary>'
            f'<p class="meta">{meta}</p>{stages}<ol class="steps">{steps}</ol></details>')


def _stage(stage: Stage, *, picking: bool = False) -> str:
    """A lookup's stage: its label, how it went and why; with ``picking``, the sheet that waits for a pick."""
    note = ('<p class="step-note">Not fetched yet: its Ultimate Guitar sheet waits for the match. Pick it below, '
            "with Fetch it now ticked, and it is fetched then.</p>") if picking else ""
    badge = _badge("review", "Waits for a pick") if picking else _badge(stage.state)
    detail = f'<p class="meta">{escape(stage.detail)}</p>' if stage.detail else ""
    return (f'<li class="step {escape(stage.state)}"><div class="step-head"><span>{escape(stage.label)}</span>'
            f"{badge}</div>{note}{detail}</li>")


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


def remove_page(display: str, song_id: int, key: str, csrf: str, goes: list[str], stays: list[str],
                notes: list[str], *, waiting: int = 0, back: str = "", library: str = "/") -> str:
    """Whether to remove a song, with what goes and what stays (``removal.describe``); the form confirms it.
    Both answers go back to ``library``, the library page as it was left: ``back``, its address after #,
    goes along with the form."""
    after = (f" It runs after the {waiting} request{'s' if waiting != 1 else ''} queued before it."
             if waiting else "")
    lede = ('<p class="lede">Remove it queues <code>caracole remove</code> for this song, as every request is '
            f"queued.{escape(after)}</p>")

    def items(heading: str, lines: list[str]) -> str:
        if not lines:
            return ""
        return (f'<h2 class="sub">{escape(heading)}</h2>\n<ul class="plan">'
                + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ul>\n")

    fields = (("csrf", csrf), ("song", song_id), ("key", key), ("confirm", "1"), *((("back", back),) if back else ()))
    hidden = "".join(f'  <input type="hidden" name="{name}" value="{escape(str(value), quote=True)}">\n'
                     for name, value in fields)
    form = ('<form class="confirm" method="post" action="/remove">\n' + hidden
            + '  <button class="btn danger" type="submit">Remove it</button>\n'
            f'  <a class="btn" href="{escape(library, quote=True)}">Keep it</a>\n</form>')
    said = "".join(f'<p class="message">{escape(note)}</p>\n' for note in notes)
    return page(f"Remove {display}?", lede + items("It takes", goes) + items("It leaves", stays) + said + form)


class Refused(Exception):
    """A request the server turns down: its status, a title and one sentence, said on ``message_page``."""

    def __init__(self, status: int, title: str, message: str):
        super().__init__(message)
        self.status, self.title, self.message = status, title, message


def message_page(title: str, message: str) -> str:
    """An error, said plainly, and the way back."""
    return page(title, f'<p class="message">{escape(message)}</p>\n'
                       '<p><a class="btn" href="/">Back to the library</a></p>')
