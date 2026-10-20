"""The one line a request shows, on its song's card and on /jobs: its progress, then how it ended.

It is read from the job (jobs.py) and, once the job is over, from what the
library knows of its song (``SongFacts``), never from which commands the job
ran. So a job of other commands reads the same way:

- **Queued**: "Queued…", or "Queued behind 2 requests…".
- **Running**: its running step's label, as "Fetching from Ultimate Guitar…".
  A step's label is written to be this line.
- **Failed**: the error its failing command gave, in one short sentence (the
  log's last ``error:`` line, its first sentence). A command that printed no
  error is named by its step. A fetch that fails on a song with no sheet that
  needs review, or wasn't found, says so instead, as a done one would: those
  are the fetch's usual refusals, worded for a terminal.
- **Done**: "Ready", with a link to the song's sheet; "Needs review", with a
  link to the song's picker when its review has candidates to pick from
  ("Pick the match"), else to the to-do page; "Not found", with the to-do
  page's link, only for a song the
  fetch looked up during this request (``SongFacts.checked_now``); or "Not
  fetched yet", for one it didn't (a cooldown, a block, a spent budget or an
  error, all of which exit 0): an error is never a miss. A removal
  (``jobs.REMOVING``), whose song is gone once it is done, says "Removed".

A line that ends in a failure or a wait also links to the job's output on
/jobs (``Line.details``). Every link is relative to the library page, which
``caracole serve`` serves at /.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from caracole.web.jobs import REMOVING, Job, Step

TODO = "_todo.md"
MAX_TEXT = 160  # characters of an error's sentence
_ERROR = re.compile(r"^(?:<\d>)?error: (.+)$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


@dataclass(frozen=True)
class SongFacts:
    """What the library knows of a job's song once the job is over.

    ``sheet`` is the link to its sheet (its card's main file), ``review`` says
    its match needs review, ``not_found`` that its match found it nowhere in
    the index, ``checked_now`` that a fetch looked it up since the job started
    (``ug.fetch.checked_since``), and ``ignored`` that overrides.toml ignores it.
    ``picker`` is the link to its picker (``review?song=ID``) while its review
    has candidates to pick from.
    """

    sheet: str | None = None
    review: bool = False
    not_found: bool = False
    checked_now: bool = False
    ignored: bool = False
    picker: str | None = None


@dataclass(frozen=True)
class Line:
    """``tone``: queued, running, ready, added, removed, review, waiting, missing or failed; ``link``: (label, href),
    where to go next; ``details``: the job's output on /jobs, for a line that ends in a failure or a wait."""

    tone: str
    text: str
    link: tuple[str, str] | None = None
    details: str | None = None

    def as_json(self) -> dict[str, Any]:
        link = {"label": self.link[0], "href": self.link[1]} if self.link else None
        return {"tone": self.tone, "text": self.text, "link": link, "details": self.details}


def details_href(job_id: int) -> str:
    """The job's output on /jobs, open."""
    return f"jobs?job={job_id}#job-{job_id}"


def job_line(job: Job, song: SongFacts | None, *, ahead: int = 0) -> Line:
    """The job's line; ``song`` is None while the library has no such song; ``ahead``: the jobs before it."""
    if job.state == "queued":
        return Line("queued", f"Queued behind {_count(ahead, 'request')}…" if ahead else "Queued…")
    if job.state == "running":
        step = next((s for s in job.steps if s.state == "running"), None) or next(
            (s for s in job.steps if s.state == "waiting"), None)
        return Line("running", f"{step.label}…" if step else "Running…")
    details = details_href(job.id)
    if job.state == "failed":
        if job.fetching and song is not None and not song.sheet:
            if song.review:
                return Line("review", "Needs review", _review_link(song), details)
            if song.not_found:
                return Line("missing", "Not found", ("see the to-do page", TODO), details)
        return Line("failed", _failure(job.steps), details=details)
    if job.song_key.startswith(REMOVING):  # no song to read once it is done: that is what it did
        return Line("removed", "Removed")
    if song is not None and song.sheet:
        return Line("ready", "Ready", ("Open sheet", song.sheet))
    if song is not None and song.ignored:
        return Line("added", "Ignored in overrides.toml")
    if song is not None and song.review:
        return Line("review", "Needs review", _review_link(song))
    if not job.fetching or song is None:
        return Line("added", "Added: the nightly run looks for it")
    if song.checked_now:
        return Line("missing", "Not found", ("see the to-do page", TODO))
    return Line("waiting", "Not fetched yet", details=details)


def _review_link(song: SongFacts) -> tuple[str, str]:
    """Where a song in review goes next: its picker, or, with no candidates to pick, the to-do page."""
    return ("Pick the match", song.picker) if song.picker else ("see the to-do page", TODO)


def _failure(steps: list[Step]) -> str:
    failed = next((s for s in steps if s.state == "failed"), None)
    if failed is None:
        return "It stopped before it was done."
    said = next((m.group(1).strip() for line in reversed(failed.output) if (m := _ERROR.match(line))), None)
    if not said:
        return f"{failed.label} failed."
    return _short(_SENTENCE_END.split(said, maxsplit=1)[0])


def _short(text: str) -> str:
    if len(text) <= MAX_TEXT:
        return text
    cut = text[: MAX_TEXT - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "…"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
