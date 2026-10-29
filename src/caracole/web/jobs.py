"""The requests ``caracole serve`` queues, each a few caracole commands, run one at a time.

A job is a list of steps; a step is one run of the ``caracole`` command line, in
a child process with the server's environment and config, at ``-v``, so the
Requests tab has the whole story. A step's label is what the song's card says
while it runs ("Adding to the library…": status.py), and a job keeps the song
it is for (``display``), for the page's list of requests. A request is
``caracole add``; a song looked up now (Fetch it now, a card's Fetch now, the
lookup page) is one ``caracole get --progress`` (``lookup_steps``), a single
process for the whole lookup, whose JSON lines become the job's ``stages``
(get.py's: the song, the match, the sheet, ...), its song and the library files
it can be read in, and stay out of the step's output; the card's line is then
the running stage's (status.py). A pick from a song's picker that asks for a
fetch adds ``caracole fetch --song`` and ``caracole render --song`` (offline) after its
``caracole review`` (``fetch_steps``). A LaCuerda song you pick goes to ``caracole
get`` or ``caracole add`` with ``--lacuerda``, and a LaCuerda artist's page is read
by ``caracole lacuerda --artist`` (``lacuerda_artist_steps``), a job of its own
(``LACUERDA_ARTIST`` and the page's slug), one request at the lookup pace, and a
query of LaCuerda's search is ``caracole lacuerda --search --progress``
(``lacuerda_search_steps``), a job of its own too (``LACUERDA_SEARCH`` and the
query's key), whose one stage is ``SEARCH_STAGES``. A harptabs.com tab you pick goes to
``caracole get`` with ``--harptabs``, and a harptabs.com artist's page is read by
``caracole harptabs --artist`` (``harptabs_artist_steps``), a job of its own
(``HARPTABS_ARTIST`` and the page's path). Those reads of a site's index are no song's
(``INDEX_READS``). A version of a song's sheet made the
one, kept, its versions not kept fetched (Fetch them, ``--keep-more``), or its pin taken out, is ``caracole versions
--progress`` (``version_steps``), a pick of the song's as a lookup's ``--tab`` is, so the song's jobs join it as they
would that; its JSON lines are the job's stages too (Keep it's and Fetch them's ``KEEP_STAGES``, and a lookup's for
``--choose`` and ``--clear``, which run one). A harmonica tab's reading pinned, or taken out, is ``caracole
harmonica`` (harmonica_routes.py), under a key of its own (``READING``), the song's change, as Make this my
version's (``EXPORTING``). A sheet made from a YouTube video is one ``caracole youtube --sheet --progress``
(``youtube_sheet_steps``), its JSON lines its stages (youtube_sheet.py's), under a key of its own too
(``YOUTUBE_SHEET`` and the song's identity key), so it never joins the song's lookup, nor a lookup it; one at a
time a song. A video suggested for a search is ``caracole youtube --search --progress`` (``youtube_search_steps``),
a job of no song's (``YOUTUBE_SEARCH`` and the query's key, among ``INDEX_READS``), whose stages are
``YOUTUBE_SEARCH_STAGES``, as are a pasted video's (``youtube_video_steps``: ``caracole youtube --video``, under
``YOUTUBE_SEARCH`` and ``video:<id>``). Each command takes caracole's lock (a
lookup lets a nightly run hand it over at its next pause), keeps its pace,
budgets and cooldowns, exactly as from a terminal. One worker thread runs the
jobs in order, so the server never runs two commands at once: it can be no
more aggressive than someone typing them.

A step that exits non-zero fails its job, and the job's other steps are
skipped. The queue holds ``limit`` jobs waiting or running, one per song (a
lookup takes the place of the song's waiting add, since ``caracole get`` adds
the song itself, or follows it once it runs; a version you pick meanwhile
takes the place of the song's waiting lookup, or follows the running one, and a
lookup joins the song's Keep it, which never looks it up, or follows it: its
stages, which share names with Keep it's, start afresh when it does),
and remembers the last ``keep``
finished ones, in memory only (``cancel`` takes one that hasn't started out of the queue, never one
that runs, and keeps it among those, cancelled): a request is in wanted.txt from the moment it's
made, so a restart loses no song, only the lookup that would have come before
the nightly run. ``Job.as_json`` is a job as data, for the page that shows a
request's progress.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from caracole.get import read_progress_line

Runner = Callable[[Sequence[str], Callable[[str], None]], int]
LIMIT = 20  # jobs waiting or running
KEEP = 30  # finished jobs remembered
MAX_LINES = 400  # output kept per step: the last lines


class QueueFull(Exception):
    """The queue holds ``limit`` jobs already."""


class JobStarted(Exception):
    """A job asked to be cancelled that runs, or is over (``state``): a command is never stopped halfway."""

    def __init__(self, job_id: int, state: str):
        super().__init__(f"request {job_id} is {state}")
        self.state = state


@dataclass
class Step:
    label: str
    args: tuple[str, ...]
    state: str = "waiting"  # waiting, running, done, failed, skipped
    code: int | None = None
    output: list[str] = field(default_factory=list)  # its last lines
    dropped: int = 0  # the lines before them


@dataclass
class Stage:
    """A stage of a lookup (get.py's ``STAGES``), as its ``caracole get --progress`` reports it: ``detail``, what it
    says now; ``running_detail``, what it said last while it ran (a sheet stage, the site it asks: get.SHEET_FROM),
    kept once it ends, so a sheet that failed names the site it asked (outcome.py)."""

    name: str
    label: str
    state: str = "waiting"  # waiting, running, done, skipped, failed
    detail: str = ""
    running_detail: str = ""


@dataclass
class Job:
    id: int
    title: str
    song_key: str
    steps: list[Step]
    fetching: bool = False
    note: str = ""
    display: str = ""  # "Artist - Title"; its title when none was given
    state: str = "queued"  # queued, running, done, failed, cancelled (before it ran: JobQueue.cancel)
    queued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stages: list[Stage] = field(default_factory=list)  # a lookup's
    song_id: int | None = None
    song_display: str | None = None
    files: dict[str, str] = field(default_factory=dict)  # name -> path in the library, once readable
    seconds_to_sheet: float | None = None
    together: tuple[int, ...] = ()  # the jobs queued with it by one ``submit_all``, itself among them

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")

    @property
    def looks_up(self) -> bool:
        """Whether one of its commands looks its song up: ``caracole get``, or ``caracole versions --choose`` or
        ``--clear``, which run one (its stages are a lookup's)."""
        return any(_looks_up(step.args) for step in self.steps)

    @property
    def from_youtube(self) -> bool:
        """Whether it makes its song's sheet from a YouTube video (``caracole youtube --sheet``): its stages are
        youtube_sheet.py's."""
        return any(_sheets_from_youtube(step.args) for step in self.steps)

    def as_json(self) -> dict[str, Any]:
        """The job as plain data: its steps, each with a state (a lookup's stages; else its commands)."""
        if self.stages:
            steps = [{"name": s.name, "label": s.label, "state": s.state, "detail": s.detail} for s in self.stages]
        else:
            steps = [{"name": s.args[0] if s.args else "", "label": s.label, "state": s.state, "detail": ""}
                     for s in self.steps]

        def when(dt: datetime | None) -> str | None:
            return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None

        return {
            "id": self.id, "title": self.title, "display": self.display or self.title, "state": self.state,
            "active": self.active, "note": self.note,
            "queued_at": when(self.queued_at), "started_at": when(self.started_at),
            "finished_at": when(self.finished_at), "steps": steps,
            "commands": [{"label": s.label, "args": list(s.args), "state": s.state, "code": s.code}
                         for s in self.steps],
            "song": {"id": self.song_id, "display": self.song_display} if self.song_id is not None else None,
            "files": dict(self.files), "seconds_to_sheet": self.seconds_to_sheet,
        }

    def heard(self, event: Mapping[str, Any]) -> None:
        """Take in one event of ``caracole get --progress`` (get.py)."""
        if isinstance(event.get("stage"), str):
            stage = next((s for s in self.stages if s.name == event["stage"]), None)
            if stage is None:
                stage = Stage(event["stage"], event["stage"])
                self.stages.append(stage)
            stage.state = str(event.get("state") or stage.state)
            stage.detail = str(event.get("detail") or "")
            if stage.state == "running":
                stage.running_detail = stage.detail
        song = event.get("song")
        if isinstance(song, Mapping) and isinstance(song.get("id"), int):
            self.song_id, self.song_display = song["id"], str(song.get("display") or "")
        files = event.get("files")
        if isinstance(files, Mapping):
            self.files = {str(k): str(v) for k, v in files.items()}
            if self.seconds_to_sheet is None and isinstance(event.get("seconds"), (int, float)):
                self.seconds_to_sheet = float(event["seconds"])


def add_steps(artist: str, title: str, *, album: str | None = None,
              duration_ms: int | None = None, lacuerda: str | None = None) -> list[tuple[str, tuple[str, ...]]]:
    """``caracole add``, as you'd type it; ``--`` ends the options, so a name may start with "-"."""
    from caracole.wanted import format_duration

    args = ["add"]
    if album:
        args.append(f"--album={album}")
    if duration_ms is not None:
        args.append(f"--duration={format_duration(duration_ms)}")
    if lacuerda:
        args.append(f"--lacuerda={lacuerda}")
    return [("Adding to the library", (*args, "--", artist, title))]


def fetch_steps(display: str) -> list[tuple[str, tuple[str, ...]]]:
    """Fetch one song now: match it (offline), fetch it from UG, render its PDF (offline)."""
    return [
        ("Looking it up", ("match",)),
        ("Fetching from Ultimate Guitar", ("fetch", f"--song={display}")),
        ("Rendering the sheet", ("render", f"--song={display}")),
    ]


LOOKUP = "get"  # the command of a lookup


def lookup_steps(artist: str, title: str, *, album: str | None = None, duration_ms: int | None = None,
                 ug: str | None = None, tab: str | None = None, lacuerda: str | None = None,
                 harptabs: str | None = None, gametabs: str | None = None,
                 songbooks: bool = True) -> list[tuple[str, tuple[str, ...]]]:
    """Look one song up now: ``caracole get --progress``, one process for every stage (get.py)."""
    from caracole.wanted import format_duration

    args = [LOOKUP, "--progress"]
    if not songbooks:  # Get the missing songs makes the songbook once, after all its lookups
        args.append("--no-songbooks")
    if album:
        args.append(f"--album={album}")
    if duration_ms is not None:
        args.append(f"--duration={format_duration(duration_ms)}")
    if ug:
        args.append(f"--ug={ug}")
    if tab:
        args.append(f"--tab={tab}")
    if lacuerda:
        args.append(f"--lacuerda={lacuerda}")
    if harptabs:
        args.append(f"--harptabs={harptabs}")
    if gametabs:
        args.append(f"--gametabs={gametabs}")
    return [("Look it up now", (*args, "--", artist, title))]


VERSIONS = "versions"  # the command that makes a song's version the one, keeps one, or takes its pin out


# Keep it's stages, as ``caracole versions --keep --progress`` reports them (versions_cmd.py), and ``--keep-more``'s
KEEP_STAGES = (
    ("song", "Find the song"),
    ("version", "The version from Ultimate Guitar"),
    ("pdf", "The version's page"),
    ("pages", "The library page"),
)


def version_steps(artist: str, title: str, *, keep: str | None = None,
                  choose: str | None = None, keep_more: bool = False) -> list[tuple[str, tuple[str, ...]]]:
    """``caracole versions --progress``: make the Ultimate Guitar tab ``choose`` the song's sheet (``--choose``:
    ``caracole get --tab`` with its own page, recorded under ``[pin]``, a lookup's stages), keep the tab ``keep``
    beside it (one tab page, at the lookup pace), keep the versions not kept yet (``keep_more``: as many as one
    lookup may, Keep it's stages too), or, with none, take the song's ``[pin]`` out and look it up again
    (``--clear``, a lookup's stages). The song is its artist and title as two words, so a " - " in either stays
    where it is."""
    if choose is not None:
        return [("Making it the one", (VERSIONS, f"--choose={choose}", "--progress", "--", artist, title))]
    if keep is not None:
        return [("Fetching the version from Ultimate Guitar",
                 (VERSIONS, f"--keep={keep}", "--progress", "--", artist, title))]
    if keep_more:
        return [("Fetching versions from Ultimate Guitar",
                 (VERSIONS, "--keep-more", "--progress", "--", artist, title))]
    return [("Going back to caracole's pick", (VERSIONS, "--clear", "--progress", "--", artist, title))]


def _options(args: Sequence[str]) -> Sequence[str]:
    return args[:list(args).index("--")] if "--" in args else args


def _looks_up(args: Sequence[str]) -> bool:
    """Whether a step's command is a lookup of its song: ``caracole get``, or ``caracole versions --choose`` or
    ``--clear``, which run one."""
    return args[:1] == (LOOKUP,) or (args[:1] == (VERSIONS,) and any(
        arg == "--clear" or arg.startswith("--choose=") for arg in _options(args)))


def _fetches(steps: Sequence[Step]) -> bool:
    """Whether a job looks its song up (``_looks_up``) or fetches it (``caracole fetch``): Keep it, which asks
    Ultimate Guitar for one tab page and keeps it beside the sheet, does neither, nor does Fetch them
    (``--keep-more``), which asks it for the pages of the versions not kept."""
    return any(_looks_up(step.args) or step.args[:1] == ("fetch",) for step in steps)


def _reports(args: Sequence[str]) -> bool:
    """Whether a step's command writes ``caracole get --progress`` lines: a lookup, ``caracole versions
    --progress``, ``caracole lacuerda --search --progress``, or ``caracole youtube --sheet --progress``."""
    return args[:1] == (LOOKUP,) or (args[:1] in ((VERSIONS,), ("lacuerda",), ("youtube",))
                                     and "--progress" in _options(args))


LACUERDA_ARTIST = "lacuerda-artist:"  # a LaCuerda artist page's read: its job's key, the page's slug after it


def lacuerda_artist_steps(slug: str, name: str) -> list[tuple[str, tuple[str, ...]]]:
    """Read a LaCuerda artist's page into its index now: ``caracole lacuerda --artist``, one request."""
    return [(f"Reading LaCuerda's page for {name}", ("lacuerda", f"--artist={slug}"))]


LACUERDA_SEARCH = "lacuerda-search:"  # a query of LaCuerda's search: its job's key, the query's key after it
HARPTABS_ARTIST = "harptabs-artist:"  # a harptabs.com artist page's read: its job's key, the page's path after it
YOUTUBE_SEARCH = "youtube-search:"  # a video suggested for a search: its job's key, the query's key after it
# what a site's index reads, and a search's suggestion: jobs of no song's
INDEX_READS = (LACUERDA_ARTIST, LACUERDA_SEARCH, HARPTABS_ARTIST, YOUTUBE_SEARCH)
SEARCH_STAGES = (("search", "Search LaCuerda"),)  # ``caracole lacuerda --search --progress``'s one stage
YOUTUBE_SEARCH_STAGES = (("video", "Search YouTube"), ("thumbnail", "Its thumbnail"))  # ``caracole youtube --search``'s


def lacuerda_search_steps(query: str, *, auto: bool) -> list[tuple[str, tuple[str, ...]]]:
    """Ask LaCuerda's search for a query's songs now: ``caracole lacuerda --search --progress``, one request;
    ``auto``, sent by the page by itself, within its share of the hour's lookups (``--auto``)."""
    return [("Searching LaCuerda", ("lacuerda", f"--search={query}", "--progress", *(("--auto",) if auto else ())))]


def youtube_search_steps(query: str) -> list[tuple[str, tuple[str, ...]]]:
    """YouTube's first video for a query, suggested beside the search's results: ``caracole youtube --search
    --progress``, one yt-dlp run and the video's thumbnail (youtube_search.py)."""
    return [("Searching YouTube", ("youtube", f"--search={query}", "--progress"))]


def youtube_video_steps(video_id: str) -> list[tuple[str, tuple[str, ...]]]:
    """A video pasted into the library page's search box, its title, channel and length read for its song's name:
    ``caracole youtube --video --progress``, one yt-dlp run with no download, and its thumbnail (youtube_search.py)."""
    return [("Reading the video", ("youtube", f"--video={video_id}", "--progress"))]


def harptabs_artist_steps(path: str, name: str) -> list[tuple[str, tuple[str, ...]]]:
    """Read a harptabs.com artist's page into its index now: ``caracole harptabs --artist``, one request."""
    return [(f"Reading harptabs.com's page for {name}", ("harptabs", f"--artist={path}"))]


def _searches(args: Sequence[str]) -> bool:
    """Whether a step's command is a query of LaCuerda's search."""
    return args[:1] == ("lacuerda",) and any(arg.startswith("--search=") for arg in args)


YOUTUBE_SHEET = "youtube:"  # a sheet from a YouTube video: its job's key, the song's identity key after it


def youtube_sheet_steps(display: str, url: str) -> list[tuple[str, tuple[str, ...]]]:
    """Make a song's auto sheet from a YouTube video now: ``caracole youtube --sheet --progress``, one process for
    every stage (youtube_sheet.py's ``STAGES``): the audio with yt-dlp, the lyrics, the chords, the PDF. ``url`` is
    the video's plain address (youtube_urls.watch_url)."""
    return [("Making the sheet",
             ("youtube", "--sheet", "--progress", f"--url={url}", f"--song={display}"))]


def _sheets_from_youtube(args: Sequence[str]) -> bool:
    """Whether a step's command makes a song's sheet from a YouTube video (``caracole youtube --sheet``)."""
    return args[:1] == ("youtube",) and "--sheet" in args


def song_key_of(job_key: str) -> str:
    """The song's identity key in a job's key: a removal's and a sheet from YouTube's have theirs after a prefix."""
    return job_key.removeprefix(REMOVING).removeprefix(YOUTUBE_SHEET)


def _pick(steps: Sequence[Step]) -> tuple[str, ...]:
    """The Ultimate Guitar song and tab, the LaCuerda song, the harptabs.com tab and the gametabs.net tab, a lookup's
    ``caracole get`` was given (``--ug``, ``--tab``, ``--lacuerda``, ``--harptabs``, ``--gametabs``), and what a ``caracole versions`` does (``--choose``,
    ``--keep``, ``--keep-more``, ``--clear``), if any."""
    picked: list[str] = []
    for step in steps:
        options = _options(step.args)
        if step.args[:1] == (LOOKUP,):
            picked += [arg for arg in options
                       if arg.startswith(("--ug=", "--tab=", "--lacuerda=", "--harptabs=", "--gametabs="))]
        elif step.args[:1] == (VERSIONS,):
            picked += [arg for arg in options
                       if arg.startswith(("--choose=", "--keep=")) or arg in ("--clear", "--keep-more")]
    return tuple(picked)


def _afresh(stages: Sequence[Stage]) -> None:
    """A lookup's stages (get.py's ``STAGES``) as they are before it starts, all waiting: a lookup that joined the
    song's Keep it (``JobQueue.submit``) runs after it, and Keep it says its song, its PDF and the library page under
    the same names."""
    from caracole.get import STAGES

    names = {name for name, _ in STAGES}
    for stage in stages:
        if stage.name in names:
            stage.state, stage.detail, stage.running_detail = "waiting", "", ""


def _stages(steps: Sequence[Step]) -> list[Stage]:
    """A job's stages, all waiting: a lookup's (``caracole versions --choose`` and ``--clear`` run one), then Keep
    it's it hasn't, a search of LaCuerda's (``SEARCH_STAGES``), and a sheet from a YouTube video's
    (youtube_sheet.py's ``STAGES``); none for other commands."""
    from caracole.get import STAGES

    names: dict[str, str] = {}
    if any(_looks_up(step.args) for step in steps):
        names.update(STAGES)
    if any(_searches(step.args) for step in steps):
        names.update(SEARCH_STAGES)
    if any(step.args[:1] == ("youtube",) and any(a.startswith(("--search=", "--video=")) for a in step.args)
           for step in steps):
        names.update(YOUTUBE_SEARCH_STAGES)
    if any(step.args[:1] == (VERSIONS,) and not _looks_up(step.args) for step in steps):
        names.update((name, label) for name, label in KEEP_STAGES if name not in names)
    if any(_sheets_from_youtube(step.args) for step in steps):
        from caracole.youtube_sheet import STAGES as SHEET_STAGES

        names.update((name, label) for name, label in SHEET_STAGES if name not in names)
    return [Stage(name, label) for name, label in names.items()]


REMOVING = "remove:"  # a removal's song_key: the song's key after it, so it never joins the song's add or fetch
EXPORTING = "export:"  # Make this my version's song_key (export_routes.py): the song's key and the version, then MINE,
MINE = ":mine"  # never the song's own key, so it joins no request of the song's
READING = "harmonica:"  # a harmonica tab's reading pinned (harmonica_routes.py): the song's key, the tab, the reading, MINE


def remove_steps(display: str) -> list[tuple[str, tuple[str, ...]]]:
    """``caracole remove --yes``: the page asked already, and showed what goes."""
    return [("Removing from caracole", ("remove", "--yes", "--", display))]


def review_steps(display: str, *, pick: str | None = None,
                 seen: Sequence[str] = ()) -> list[tuple[str, tuple[str, ...]]]:
    """Answer a song's review as ``caracole review`` does, with no question: ``pick`` (a candidate's
    ARTIST/SONG), or, without it, none of the candidates ``seen``. It matches the song again (and,
    with an ``[alias]``, its artist's other songs) and rewrites the pages itself, so a fetch after it
    needs no ``caracole match``."""
    answer = (f"--pick={pick}",) if pick is not None else ("--none", *(f"--seen={ref}" for ref in seen))
    return [("Writing the answer to overrides.toml", ("review", f"--song={display}", *answer))]


class JobQueue:
    """Jobs in order, run by one worker thread (``start``), or by ``run_pending`` in tests."""

    def __init__(self, runner: Runner, *, limit: int = LIMIT, keep: int = KEEP, max_lines: int = MAX_LINES):
        self._runner = runner
        self._limit = limit
        self._keep = keep
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._jobs: list[Job] = []
        self._next_id = 1
        self._stopping = False
        self._thread: threading.Thread | None = None

    # --- what the pages ask -------------------------------------------------------------------

    def submit(self, title: str, song_key: str, steps: Sequence[tuple[str, Sequence[str]]], *,
               fetching: bool = False, note: str = "", display: str = "",
               join: bool = True, song_id: int | None = None) -> tuple[Job, bool]:
        """Queue a job, and say whether it is new: one per song, unless a fetch must come after an add.

        A song's waiting or running job that does as much (one that looks the
        song up or fetches it, or any when the new job fetches nothing) is the
        answer. A fetch joins a song's add that still waits: the add gets the
        fetch's steps of the commands it doesn't run (one ``caracole add``,
        whatever its album: the server wrote wanted.txt already), and a lookup
        takes the add's place, since ``caracole get`` adds the song itself. One
        asked for while the add runs comes after it, as a job of its own; so
        with Keep it, which fetches one tab page but never looks the song up. With ``join=False`` (a pick,
        whose ``caracole review`` must come after the song's own request), any
        waiting or running job of the song is the answer, left as it is.

        A lookup of a song or tab you picked (``--ug``, ``--tab``) that the
        song's jobs don't look up yet is never dropped: it takes the place of
        the song's lookup that still waits, or comes after the one that runs,
        as a job of its own. ``song_id`` is the library's song the job is about,
        when it is known before the job runs: a removal's, whose song is gone
        once it is done. Raises QueueFull when ``limit`` jobs are waiting or
        running.
        """
        with self._lock:
            return self._submit_locked(title, song_key, steps, fetching=fetching, note=note, display=display,
                                       join=join, song_id=song_id)

    def submit_all(self, requests: Sequence[dict[str, Any]]) -> list[tuple[Job, bool]]:
        """``submit`` of each request (a dict of its arguments: ``title``, ``song_key``, ``steps`` and the options),
        all or none, under the queue's one lock: when one finds the queue full, QueueFull is raised and the queue
        is as it was, the jobs the earlier ones joined or queued as before. A request that joins a job already
        queued needs no room. The jobs it makes are queued ``together``: cancelling one cancels those of them
        that haven't started (``cancel``). The copies it gives back were made before that is said."""
        with self._lock:
            waiting = {job.id: (list(job.steps), list(job.stages), job.title, job.fetching, job.note)
                       for job in self._jobs if job.state == "queued"}
            count, next_id = len(self._jobs), self._next_id
            done: list[tuple[Job, bool]] = []
            try:
                for request in requests:
                    done.append(self._submit_locked(**request))
                made = tuple(job.id for job, new in done if new)
                if len(made) > 1:  # both or neither: cancelled so too
                    for job in self._jobs:
                        if job.id in made:
                            job.together = made
            except QueueFull:
                del self._jobs[count:]
                self._next_id = next_id
                for job in self._jobs:
                    if job.id in waiting:
                        job.steps, job.stages, job.title, job.fetching, job.note = waiting[job.id]
                raise
            return done

    def _submit_locked(self, title: str, song_key: str, steps: Sequence[tuple[str, Sequence[str]]], *,
                       fetching: bool = False, note: str = "", display: str = "",
                       join: bool = True, song_id: int | None = None) -> tuple[Job, bool]:
        new = [Step(label, tuple(args)) for label, args in steps]
        mine = [job for job in self._jobs if job.active and job.song_key == song_key]
        enough = next((job for job in mine if _fetches(job.steps)), None)  # a lookup or a fetch does the most
        if enough is None and (not fetching or not join) and mine:
            enough = mine[0]
        waiting = next((job for job in mine if job.state == "queued"), None)
        picked = _pick(new)
        if picked and join:  # your pick: only the song's last job, looking it up already, does as much
            last = waiting or next((job for job in mine if job.state == "running"), None)
            enough = last if last is not None and _pick(last.steps) == picked else None
        if enough is not None:
            return copy.deepcopy(enough), False
        if waiting is not None:
            # One `caracole get` does it all, as `caracole versions --choose` runs one
            if any(step.args[:1] == (LOOKUP,) or (_looks_up(step.args) and "--clear" not in step.args) for step in new):
                waiting.steps = [s for s in waiting.steps if s.args[:1] not in (("add",), (LOOKUP,))]
                waiting.stages = []
            runs = {step.args[0] for step in waiting.steps}
            # Two versions kept, or a pin taken out after a version kept, are two commands
            waiting.steps += [step for step in new if step.args[0] not in runs
                              or (step.args[0] == VERSIONS and step.args not in {s.args for s in waiting.steps})]
            had = {stage.name for stage in waiting.stages}  # a job waiting has heard nothing yet
            waiting.stages += [stage for stage in _stages(waiting.steps) if stage.name not in had]
            waiting.title, waiting.fetching = title, True
            waiting.note = waiting.note or note
            return copy.deepcopy(waiting), False
        if sum(job.active for job in self._jobs) >= self._limit:
            raise QueueFull(f"{self._limit} requests are waiting already")
        job = Job(self._next_id, title, song_key, new, fetching=fetching, note=note, display=display or title,
                  stages=_stages(new), song_id=song_id,
                  song_display=(display or title) if song_id is not None else None)
        self._next_id += 1
        self._jobs.append(job)
        self._wake.notify_all()
        return copy.deepcopy(job), True

    def cancel(self, job_id: int) -> Job | None:
        """Take a job that hasn't started out of the queue, and give it back, as a copy; None for one never
        queued, cancelled already or forgotten. Raises JobStarted for one that runs or is over: the command
        it runs is never stopped halfway, and a finished one stays in the history. The jobs queued
        ``together`` with it that haven't started go too (a songbook's Add a song: the lookup and the
        songbook's change, both or neither). A cancelled job is over, never run ("cancelled", its steps
        and stages skipped), and stays in the history as a finished one does: a page that follows it (the
        library page on another device) hears that it ended. A cancelled add leaves its wanted.txt line,
        which the server wrote when it was asked for: the nightly run looks for the song."""
        with self._lock:
            job = next((j for j in self._jobs if j.id == job_id), None)
            if job is None or job.state == "cancelled":
                return None
            if job.state != "queued":
                raise JobStarted(job_id, job.state)
            now = datetime.now(UTC)
            for j in self._jobs:
                if j is job or (j.id in job.together and j.state == "queued"):
                    j.state, j.finished_at = "cancelled", now
                    for part in (*j.steps, *j.stages):
                        part.state = "skipped"
            self._forget()
            return copy.deepcopy(job)

    def snapshot(self) -> list[Job]:
        """Every job remembered, newest first, as copies."""
        with self._lock:
            return copy.deepcopy(self._jobs[::-1])

    def job(self, job_id: int) -> Job | None:
        """A job remembered, as a copy; None for one never queued, or forgotten."""
        with self._lock:
            return next((copy.deepcopy(j) for j in self._jobs if j.id == job_id), None)

    def active_count(self) -> int:
        with self._lock:
            return sum(job.active for job in self._jobs)

    def room(self) -> int:
        """How many more jobs the queue takes now: ``limit``, less those waiting or running."""
        with self._lock:
            return max(0, self._limit - sum(job.active for job in self._jobs))

    def fetching_keys(self) -> set[str]:
        """The songs a waiting or running job will fetch."""
        with self._lock:
            return {job.song_key for job in self._jobs if job.active and job.fetching}

    # --- the worker ------------------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, name="caracole-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        """Stop the worker, ending the command it runs."""
        with self._lock:
            self._stopping = True
            self._wake.notify_all()
        terminate = getattr(self._runner, "terminate", None)
        if terminate is not None:
            terminate()
        if self._thread is not None:
            self._thread.join(timeout)

    def run_pending(self) -> None:
        """Run the queued jobs here and now, in order."""
        while (job := self._next()) is not None:
            self._run(job)

    def _work(self) -> None:
        while True:
            with self._lock:
                while not self._stopping and not any(j.state == "queued" for j in self._jobs):
                    self._wake.wait()
                if self._stopping:
                    return
            job = self._next()
            if job is not None:
                self._run(job)

    def _next(self) -> Job | None:
        with self._lock:
            job = next((j for j in self._jobs if j.state == "queued"), None)
            if job is not None:
                job.state = "running"
                job.started_at = datetime.now(UTC)
            return job

    def _run(self, job: Job) -> None:
        failed = False
        for step in job.steps:
            with self._lock:
                if failed or self._stopping:
                    step.state = "skipped"
                    continue
                step.state = "running"
                if _looks_up(step.args):  # after Keep it, whose stages share its stages' names: its own, afresh
                    _afresh(job.stages)

            def emit(line: str, step: Step = step) -> None:
                event = read_progress_line(line) if _reports(step.args) else None
                with self._lock:
                    if event is not None:  # a lookup's progress: data, not output
                        job.heard(event)
                        return
                    step.output.append(line)
                    if len(step.output) > self._max_lines:
                        del step.output[0]
                        step.dropped += 1

            try:
                code = self._runner(step.args, emit)
            except Exception as e:  # noqa: BLE001 (the child couldn't start: the job fails, the queue goes on)
                emit(f"caracole couldn't start: {e}")
                code = None
            with self._lock:
                step.code = code
                step.state = "done" if code == 0 else "failed"
                failed = failed or code != 0
        with self._lock:
            job.state = "failed" if failed or any(s.state != "done" for s in job.steps) else "done"
            job.finished_at = datetime.now(UTC)
            for stage in job.stages:  # a lookup that ended early: nothing is left running or waiting
                if stage.state == "running":
                    stage.state = "failed" if job.state == "failed" else "done"
                elif stage.state == "waiting":
                    stage.state = "skipped"
            self._forget()

    def _forget(self) -> None:
        """Keep the last ``keep`` finished jobs."""
        finished = [j for j in self._jobs if not j.active]
        for job in finished[: max(0, len(finished) - self._keep)]:
            self._jobs.remove(job)


# --- the caracole command line, in a child process ---------------------------------------------


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's environment: the server's, with this Python's path, its output unbuffered.

    The Nix wrapper adds caracole's dependencies to ``sys.path`` inside its script,
    not through the environment, so the child gets the path this process runs with.
    """
    env = dict(os.environ if base is None else base)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    env["PYTHONUNBUFFERED"] = "1"  # so each line shows in the Requests tab as it is printed
    return env


class CaracoleRunner:
    """Runs ``python -P -m caracole -v [--config FILE] ARGS…`` and hands each line it prints to ``emit``.

    ``-m`` alone would put the working directory first on the child's
    ``sys.path``, which the ``caracole`` script never does: started from the
    synced library, the server would run any ``typer.py`` a device dropped
    there. ``-P`` (Python 3.11) leaves it out.
    """

    def __init__(self, config_path: Path | None, *, python: str = sys.executable):
        self._argv = [python, "-P", "-m", "caracole", "-v",
                      *(["--config", str(config_path)] if config_path else [])]
        self._env = child_env()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def __call__(self, args: Sequence[str], emit: Callable[[str], None]) -> int:
        process = subprocess.Popen(
            [*self._argv, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=self._env,
        )
        with self._lock:
            self._process = process
        try:
            assert process.stdout is not None
            for line in process.stdout:
                emit(line.rstrip("\n"))
            return process.wait()
        finally:
            with self._lock:
                self._process = None

    def terminate(self) -> None:
        """End the command running now, as Ctrl-C or systemd would: it lets go of the lock as it exits."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
