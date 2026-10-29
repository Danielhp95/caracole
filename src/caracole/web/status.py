"""The one line a request shows on its song's card: its progress, then how it ended; the Requests tab says it its
own way.

It is read from the job (jobs.py) and, once the job is over, from what the
library knows of its song (``SongFacts``), never from which commands the job
ran. So a job of other commands reads the same way:

- **Queued**: "Queued…", or "Queued behind 2 requests…".
- **Running**: its running step's label, as "Adding to the library…". A
  step's label is written to be this line. A lookup, one ``caracole get``,
  says its running stage's line instead (``STAGE_LINES``), as "Fetching from
  Ultimate Guitar…" ("Fetching from LaCuerda…" while its sheet stage says it
  asks LaCuerda, ``get.SHEET_FROM``), or "Waiting for another caracole…"
  while its lock is held by a nightly run that lets it go first at its next
  pause.
- **Cancelled**: taken out of the queue before it ran (``JobQueue.cancel``),
  whatever it was for.
- **Failed**: the error its failing command gave, in one short sentence (the
  log's last ``error:`` line, its first sentence; a lookup's, its failed
  stage's words). A command that printed no error is named by its step. A fetch that fails on a song with no sheet that
  needs review, or wasn't found, says so instead, as a done one would: those
  are the fetch's usual refusals, worded for a terminal.
- **Done**: "Ready", with a link to the song's sheet (the Requests tab's Open;
  on the library page the song's line opens it itself, and its request's line
  says "Ready" alone: ``song_line``); "Needs review", with a
  link to the song's picker when its review has candidates to pick from
  ("Pick the match"), else to the to-do page; "Not found", with the to-do
  page's link, only for a song the
  fetch looked up during this request (``SongFacts.checked_now``); or "Not
  fetched yet", for one it didn't (a cooldown, a block, a spent budget or an
  error, all of which exit 0): an error is never a miss. A removal
  (``jobs.REMOVING``), whose song is gone once it is done, says "Removed";
  Make this my version (``jobs.EXPORTING``, export_routes.py), none of its
  song's own requests, what it made: "Your version now", with a link to the
  song's sheet;
  a songbook's change (songbooks.py), which has no song, what it did:
  "Made", "Moved", "Changed", "Renamed"…, "Made" and "Added" with a link to
  the songbook's page ("Open songbook") once caracole has written it (a move,
  a song taken out, a setting or a new name shows in the songbook's set list,
  beside its line); never a song's "Added"; and a LaCuerda artist page's read
  (``jobs.LACUERDA_ARTIST``), no song's, what LaCuerda answered, in the words
  ``caracole lacuerda --artist`` ends with ("Read: …", "Not found: …", or "Not
  read: …" for a cooldown, a block, a spent budget or an error), and a query
  of LaCuerda's search (``jobs.LACUERDA_SEARCH``) in the words ``caracole
  lacuerda --search`` ends with ("Searched: …", "Found already: …", "Nothing
  found: …", or "Not searched: …"); while it runs, "Searching LaCuerda…"; and a
  harptabs.com artist page's read (``jobs.HARPTABS_ARTIST``), as a LaCuerda
  one's, in the words ``caracole harptabs --artist`` ends with. An add of a
  song whose sheet you picked on LaCuerda says that tonight's run gets that sheet.
  A sheet from a YouTube video (``jobs.YOUTUBE_SHEET``) says Ready once its
  chords stage made the sheet (an auto sheet of an earlier video is none of
  its doing), else "Not made yet" (a block, a cooldown, a spent budget or a
  site's error, which exit 0), the Requests tab saying which stage stopped it.

A line that ends in a failure or a wait also links to the job's output in
the library page's Requests tab (``Line.details``, ``#tab=requests&job=N``). Every link is relative to the
library page, which ``caracole serve`` serves at /. The Requests tab (feed.py) reads the same line and says
it as an outcome, a reason and the next step (outcome.py), and a lookup's steps
under it, which the library page draws under the song's line too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from caracole.get import SHEET_FROM
from caracole.logs import plural
from caracole.web.jobs import EXPORTING, INDEX_READS, READING, REMOVING, YOUTUBE_SHEET, Job, Stage, Step
from caracole.web.songbooks import DONE, OPENS, songbook_of

TODO = "_todo.md"
REQUESTS = "#tab=requests"  # the library page's Requests tab
READY = "Ready"  # a song's request that ended with its sheet there
MAX_TEXT = 160  # characters of an error's sentence
_ERROR = re.compile(r"^(?:<\d>)?error: (.+)$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")
# What a song's card says while a stage of a lookup (get.STAGES) runs, as a step's label would.
STAGE_LINES = {
    "song": "Finding the song",
    "match": "Looking it up",
    "sheet": "Fetching from Ultimate Guitar",
    "version": "Fetching the version from Ultimate Guitar",  # caracole versions --keep's (jobs.KEEP_STAGES)
    "pdf": "Rendering the sheet",
    "lyrics": "Fetching the lyrics from LRCLIB",
    "ug": "Fetching from Ultimate Guitar",
    "lacuerda": "Fetching from LaCuerda",
    "gtptabs": "Fetching from gtptabs.com",
    "harptabs": "Fetching from harptabs.com",
    "gametabs": "Fetching from gametabs.net",
    "pages": "Writing the library page",
    "songbooks": "Remaking its songbooks",
    "search": "Searching LaCuerda",  # caracole lacuerda --search's (jobs.SEARCH_STAGES)
    "audio": "Getting the audio",  # caracole youtube --sheet's (youtube_sheet.STAGES)
    "chords": "Working out the chords",
    "video": "Searching YouTube",  # caracole youtube --search's (jobs.YOUTUBE_SEARCH_STAGES)
    "thumbnail": "Getting the thumbnail",
}
_WAITING = "waiting for another caracole"  # how get.py's song stage begins while the lock is held
_SHEET_LINES = {said: f"Fetching {said}" for said in SHEET_FROM.values()}  # a running sheet stage's, by its site
# How ``caracole lacuerda --artist`` and ``--search`` end, by what LaCuerda answered, and the tone of the line.
_READ_TONES = {"Read: ": "added", "Not found: ": "missing", "Not read: ": "waiting",
               "Searched: ": "added", "Found already: ": "added", "Nothing found: ": "missing",
               "Not searched: ": "waiting"}


def _harmonica_page(job: Job) -> str | None:
    """The page of the harmonica tab a pin's job names (``--tab=`` and the song's artist and title after "--"), as a
    link the library's pages follow (a sheet's link's shape: relative, each name quoted)."""
    from urllib.parse import quote

    from caracole.inbox import harmonica_page
    from caracole.library import song_folder

    args = job.steps[0].args if job.steps else ()
    tab = next((a.split("=", 1)[1] for a in args if a.startswith("--tab=")), "")
    page = harmonica_page(tab)
    if page is None or "--" not in args or len(args) < args.index("--") + 3:
        return None
    artist, title = args[args.index("--") + 1:args.index("--") + 3]
    return "/".join(quote(part) for part in (*song_folder(artist, title), page))


@dataclass(frozen=True)
class SongFacts:
    """What the library knows of a job's song now: once the job is over, how it ended; while it runs, where its
    sheet came from once its sheet stage is done.

    ``sheet`` is the link to its sheet (its card's main file), ``review`` says
    its match needs review, ``not_found`` that its match found it nowhere in
    the index, ``checked_now`` that a fetch looked it up since the job started
    (``ug.fetch.checked_since``), or that a lookup found Ultimate Guitar can't be
    asked about it at all (not in the index, its artist's page unknown, which
    ``caracole fetch --song`` refuses as such), and ``ignored`` that
    overrides.toml ignores it.
    ``picker`` is the link to its picker (``review?song=ID``) while its review
    has candidates to pick from. ``lacuerda`` says the sheet you picked on
    LaCuerda (``[lacuerda]``) is still to be asked for. ``elsewhere`` is, for a song a
    fetch left without a sheet, what the local indexes have of it on another site (a
    source and its page: ``outcome.elsewhere``), and ``asked_ug`` that the fetch
    itself asked Ultimate Guitar (``checked_since``), so that what the song lacks, UG
    lacks; both the Requests tab alone says, and the line here never reads them.
    ``sheet_from`` is where its sheet came from,
    the site's tag ("UG", "LaCuerda": ``icons.tag``, its kept sheet's version), for a
    lookup's Sheet step (outcome.py); "" without a sheet.
    """

    sheet: str | None = None
    review: bool = False
    not_found: bool = False
    checked_now: bool = False
    ignored: bool = False
    picker: str | None = None
    lacuerda: bool = False
    elsewhere: tuple[str, str] | None = None
    asked_ug: bool = False
    sheet_from: str = ""


@dataclass(frozen=True)
class Line:
    """``tone``: queued, running, ready, added, removed, review, waiting, missing, failed or cancelled; ``link``: (label, href),
    where to go next; ``details``: the job's output in the Requests tab, for a line that ends in a failure or a
    wait."""

    tone: str
    text: str
    link: tuple[str, str] | None = None
    details: str | None = None

    def as_json(self) -> dict[str, Any]:
        link = {"label": self.link[0], "href": self.link[1]} if self.link else None
        return {"tone": self.tone, "text": self.text, "link": link, "details": self.details}


def details_href(job_id: int) -> str:
    """The job's output in the library page's Requests tab, open (relative to the library page, as every link here
    is: ``/`` before it from any other page)."""
    return f"{REQUESTS}&job={job_id}"


def job_line(job: Job, song: SongFacts | None, *, ahead: int = 0, songbook_page: str | None = None) -> Line:
    """The job's line; ``song`` is None while the library has no such song; ``ahead``: the jobs before it;
    ``songbook_page``: for a songbook's change, its songbook's page (``songbooks.songbook_page``), if any."""
    if job.state == "queued":
        return Line("queued", f"Queued behind {plural(ahead, 'request')}…" if ahead else "Queued…")
    if job.state == "running":
        if job.stages:
            return Line("running", _stage_line(job.stages, new=song is None))
        step = next((s for s in job.steps if s.state == "running"), None) or next(
            (s for s in job.steps if s.state == "waiting"), None)
        return Line("running", f"{step.label}…" if step else "Running…")
    if job.state == "cancelled":  # it never ran: nothing to read from its song
        return Line("cancelled", "Cancelled")
    details = details_href(job.id)
    if job.state == "failed":
        if job.fetching and song is not None and not song.sheet:
            if song.review:
                return Line("review", "Needs review", _review_link(song), details)
            if song.not_found:
                return Line("missing", "Not found", ("see the to-do page", TODO), details)
        return Line("failed", _stage_failure(job.stages) or _failure(job.steps), details=details)
    if job.song_key.startswith(REMOVING):  # no song to read once it is done: that is what it did
        return Line("removed", "Removed")
    if job.song_key.startswith(EXPORTING):  # Make this my version, none of the song's own requests: what it made
        return Line("ready", "Your version now", ("Open sheet", song.sheet) if song and song.sheet else None)
    if job.song_key.startswith(READING):  # a harmonica tab's reading pinned or cleared (harmonica_routes.py)
        page = _harmonica_page(job)
        said = "read as caracole guesses" if any("--clear" in s.args for s in job.steps) else "read as you set it"
        return Line("ready", f"Its harmonica tab {said}", ("Open the tab", page) if page else None)
    songbook = songbook_of(job.song_key)
    if songbook is not None:  # a songbook's change: no song at all; a deletion says so as a removal does
        action = str(songbook["action"])
        if action == "delete":
            return Line("removed", DONE[action])
        opens = songbook_page if action in OPENS else None  # moved, set or renamed: its set list is right there
        return Line("ready", DONE[action], ("Open songbook", opens) if opens else None)
    if job.song_key.startswith(INDEX_READS):  # no song's: its command's last word says what the site answered
        return _artist_read(job.steps, details)
    if job.song_key.startswith(YOUTUBE_SHEET):  # Ready once its chords are made, never on an earlier sheet
        made = any(stage.name == "chords" and stage.state == "done" for stage in job.stages)
        if made and song is not None and song.sheet:
            return Line("ready", READY, ("Open sheet", song.sheet))
        return Line("waiting", "Not made yet", details=details)
    if song is not None and song.sheet:
        return Line("ready", READY, ("Open sheet", song.sheet))
    if song is not None and song.ignored:
        return Line("added", "Ignored in overrides.toml")
    if song is not None and song.review:
        return Line("review", "Needs review", _review_link(song))
    if not job.fetching and song is not None and song.lacuerda:
        return Line("added", "Added: tonight's run gets the sheet you picked on LaCuerda")
    if not job.fetching or song is None:
        return Line("added", "Added: the nightly run looks for it")
    if song.checked_now:
        return Line("missing", "Not found", ("see the to-do page", TODO))
    return Line("waiting", "Not fetched yet", details=details)


def song_line(line: Line) -> Line:
    """The line as the library page says it under a song's line, or a result's row (/jobs.json's view): "Ready"
    alone, with no link, as the song's line opens its sheet itself (its title, its Open), and the list of requests
    by the song's name; any other line as it is, its link the next step."""
    return replace(line, link=None) if line.tone == "ready" and line.text == READY else line


def _artist_read(steps: list[Step], details: str) -> Line:
    """A LaCuerda artist page's read, or a query of its search, or a harptabs.com artist page's read, over: the
    sentence ``caracole lacuerda --artist`` (or ``--search``, or ``caracole harptabs --artist``) ends with
    (commands/lyrics.py), up to its first "; " or bracket. "Read: …", "Searched: …" and
    "Found already: …" are done, "Not found: …" and "Nothing found: …" LaCuerda's answer that it has no such page or
    song, and "Not read: …" and "Not searched: …" a cooldown, a block, a spent budget or an error, each a wait; any
    other ending, "Done"."""
    said = next((line.strip() for step in reversed(steps) for line in reversed(step.output)
                 if line.startswith(tuple(_READ_TONES))), None)
    if said is None:
        return Line("added", "Done", details=details)
    tone = next(t for prefix, t in _READ_TONES.items() if said.startswith(prefix))
    text = said.split("; ", 1)[0].split(" (", 1)[0].rstrip(".") + "."
    return Line(tone, _short(text), details=None if tone == "added" else details)


def _review_link(song: SongFacts) -> tuple[str, str]:
    """Where a song in review goes next: its picker, or, with no candidates to pick, the to-do page."""
    return ("Pick the match", song.picker) if song.picker else ("see the to-do page", TODO)


def _stage_line(stages: list[Stage], *, new: bool = False) -> str:
    """A running lookup's line: its running stage's, else the next one's, as between two steps. ``new``: a
    song the library doesn't have yet, which the song stage adds, as ``caracole add`` would."""
    stage = next((s for s in stages if s.state == "running"), None) or next(
        (s for s in stages if s.state == "waiting"), None)
    if stage is None:
        return "Running…"
    if stage.state == "running" and stage.detail.startswith(_WAITING):
        return "Waiting for another caracole…"
    if stage.name == "song" and new:
        return "Adding to the library…"
    if stage.state == "running" and stage.name == "sheet" and stage.detail in _SHEET_LINES:
        return f"{_SHEET_LINES[stage.detail]}…"
    if stage.state == "running" and stage.name == "songbooks" and stage.detail:
        return f"Remaking songbook {stage.detail}…"
    return f"{STAGE_LINES.get(stage.name, stage.label)}…"


def _stage_failure(stages: list[Stage]) -> str | None:
    """A lookup's failure, in its failed stage's words (a refusal, a bug); None without one."""
    failed = next((s for s in stages if s.state == "failed" and s.detail), None)
    if failed is None:
        return None
    said = _short(_SENTENCE_END.split(failed.detail.strip(), maxsplit=1)[0])
    return said if said.endswith((".", "!", "?", "…")) else said + "."


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
