"""The one line a request shows, on its song's card and on /jobs: its progress, then how it ended.

It is read from the job (jobs.py) and, once the job is done, from what the
library knows of its song (``SongFacts``), never from which commands the job
ran. So a job of other commands reads the same way:

- **Queued**: "Queued…", or "Queued behind 2 requests…".
- **Running**: its running step's label, as "Fetching from Ultimate Guitar…".
  A step's label is written to be this line.
- **Failed**: the error its failing command gave, in one short sentence (the
  log's last ``error:`` line, its first sentence), with a link to the job's
  output on /jobs. A command that printed no error is named by its step.
- **Done**: "Ready", with a link to the song's sheet; "Needs review" or "Not
  found", with a link to the to-do page; or, for a song still to fetch after
  a fetch that exited 0 (a block, a spent budget, an error), "Not fetched
  yet": an error is never a miss.

Every link is relative to the library page, which ``caracole serve`` serves at /.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from caracole.web.jobs import Job, Step

TODO = "_todo.md"
MAX_TEXT = 160  # characters of an error's sentence
_ERROR = re.compile(r"^(?:<\d>)?error: (.+)$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


@dataclass(frozen=True)
class SongFacts:
    """What the library knows of a job's song once the job is done.

    ``sheet`` is the link to its sheet (its card's main file), ``review`` says
    its match needs review, ``to_fetch`` that it is still to be fetched, and
    ``ignored`` that overrides.toml ignores it.
    """

    sheet: str | None = None
    review: bool = False
    to_fetch: bool = False
    ignored: bool = False


@dataclass(frozen=True)
class Line:
    """``tone``: queued, running, ready, added, review, waiting, missing or failed; ``link``: (label, href)."""

    tone: str
    text: str
    link: tuple[str, str] | None = None

    def as_json(self) -> dict[str, Any]:
        link = {"label": self.link[0], "href": self.link[1]} if self.link else None
        return {"tone": self.tone, "text": self.text, "link": link}


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
    if job.state == "failed":
        return Line("failed", _failure(job.steps), ("Details", details_href(job.id)))
    if song is not None and song.sheet:
        return Line("ready", "Ready", ("Open sheet", song.sheet))
    if song is not None and song.ignored:
        return Line("added", "Ignored in overrides.toml")
    if song is not None and song.review:
        return Line("review", "Needs review", ("see the to-do page", TODO))
    if not job.fetching or song is None:
        return Line("added", "Added: the nightly run looks for it")
    if song.to_fetch:
        return Line("waiting", "Not fetched yet: it waits for the next run", ("Details", details_href(job.id)))
    return Line("missing", "Not found", ("see the to-do page", TODO))


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
