"""The pages caracole serve writes itself: the picker, Remove's question, and errors.

They share index.html's look (library_assets/base.css, ``BASE_STYLE``), carry no script,
and every text in them is escaped. The requests are no page of their own: the library page's
Requests tab draws them (feed.py, library_assets/requests.js).

The picker (``picker_form``) is a song in review's candidates as a radio
group, the same markup and style (library_assets/picker.css) as the cards'
picker, on a page of its own (``review_page``): a request that ended in a
review links to it (its Pick the match).

A request the server turns down is ``Refused``, which a route raises and app.py
answers with ``message_page``, or, to a page's script, as data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from html import escape
from typing import Any

from caracole.inline import sha256_source
from caracole.library_assets import BASE_STYLE, PICKER_STYLE
from caracole.page_icon import LINK as PAGE_ICON
from caracole.web.top import top

PAGE_STYLE = BASE_STYLE + PICKER_STYLE + """
.pick-page { max-width: 46rem; }
.lede { max-width: 72ch; margin: 4px 0 20px; color: var(--muted); }
.says { padding: 2px 10px; border-radius: 999px; font-size: .8rem; font-weight: 650; white-space: nowrap;
  color: var(--ignored); background: var(--ignored-bg); }
.says.ready, .says.removed, .says.done { color: var(--found); background: var(--found-bg); }
.says.running, .says.added { color: var(--auto); background: var(--auto-bg); }
.says.waiting, .says.missing { color: var(--wanted); background: var(--wanted-bg); }
.says.review { color: var(--review); background: var(--review-bg); }
.says.failed { color: var(--failed); background: var(--failed-bg); }
.message { max-width: 72ch; }
.sub { margin: 18px 0 6px; font-size: 1rem; }
.plan { max-width: 72ch; margin: 0; padding-left: 1.2em; overflow-wrap: anywhere; }
.plan li + li { margin-top: 4px; }
.confirm { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
.readings { display: grid; gap: 10px; max-width: 72ch; margin: 0; padding: 0; list-style: none; }
.reading { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: 10px; overflow-wrap: anywhere; }
.reading.now { border-color: var(--found); }
.reading .said { flex: 1 1 16rem; font-weight: 600; }
.reading .q { color: var(--muted); font-size: .85rem; white-space: nowrap; }
.reading .confirm { margin-top: 0; }
.btn.danger { min-height: 44px; background: var(--failed); border-color: var(--failed); color: var(--bg);
  font-weight: 650; }
"""

# No script; forms post only to the server; nothing else loads. The one image is the page's icon, inline
# (page_icon.py).
PAGE_CSP = (f"default-src 'none'; style-src {sha256_source(PAGE_STYLE)}; img-src data:; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'")


def page(title: str, body: str, *, head: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="same-origin">\n'
        f"{head}{PAGE_ICON}<title>{escape(title)} · caracole</title>\n<style>{PAGE_STYLE}</style>\n</head>\n<body>\n"
        f'<div class="page">\n{top(title)}'
        f"{body}\n</div>\n</body>\n</html>\n"
    )


REFRESH = 10  # seconds between reloads of a page that follows a request while it waits or runs (versions, harmonica)


# --- the picker: a song in review's candidates ----------------------------------------------


@dataclass(frozen=True)
class Pick:
    """A song in review and its candidates (``library_page.review_choices``), for the picker; with
    ``search``, a song not found and what ``caracole search`` finds for it (none yet for the Requests tab,
    which links to them)."""

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
    """A song in review's picker on a page of its own, for the Requests tab to link to; or a song not
    found's, with what ``caracole search`` finds for it."""
    if pick.search:
        lede = (f'<p class="lede">Nothing in the offline Ultimate Guitar index matched {escape(pick.display)} '
                "closely enough. These are what <code>caracole search</code> finds for its artist and title: pick "
                "one only if it is the song, and caracole writes it under <code>[match]</code>.</p>")
    else:
        lede = (f'<p class="lede">caracole isn\'t sure which Ultimate Guitar song {escape(pick.display)} is. '
                "Pick it here, as <code>caracole review</code> would ask you.</p>")
    return page("Pick the match", f'<div class="pick-page">{lede}{picker_form(pick, csrf, focus=True)}</div>')


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
