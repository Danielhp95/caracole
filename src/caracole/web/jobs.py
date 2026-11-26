"""The requests ``caracole serve`` queues, each a few caracole commands: the queue's one at a time, the lookups' lane's
beside them.

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
time a song. A song's lyrics transcribed from its YouTube audio, then its auto sheet made again over them, is one
``caracole transcribe --progress`` (``transcribe_steps``), its JSON lines its stages (transcribe_job.py's), under a key
of its own too (``TRANSCRIBE`` and the song's identity key), as a sheet from YouTube's: it never joins the song's
lookup, nor a lookup it, and one at a time a song; it is the queue's, so two songs' run one after the other. A sheet
made from an audio file you uploaded is one ``caracole audio --progress`` (``audio_sheet_steps``: the upload by its
16-hex id, never a path), its JSON lines its stages (audio_sheet.py's), under ``AUDIO_SHEET`` and the song's identity
key, as a sheet from YouTube's, the queue's. A song's lyrics looked up under a name you typed is ``caracole lyrics
--song --as`` (``lyrics_search_steps``), the lane's, a job of no song's (``LYRICS_SEARCH`` and the song's identity
key, among ``INDEX_READS``) with no stages, its line its last line, though the lane sees its song (``song_of_job``),
so it never runs beside the song's pick or transcription; a record of that search picked is ``caracole lyrics --song
--record --progress`` (``lyrics_pick_steps``), its JSON lines its stages (lyrics_pick.py's), under ``LYRICS_PICK``
and the song's identity key, the queue's and the song's, joining no lookup, nor a lookup it. A video
suggested for a search is ``caracole youtube --search --progress`` (``youtube_search_steps``),
a job of no song's (``YOUTUBE_SEARCH`` and the query's key, among ``INDEX_READS``), whose stages are
``YOUTUBE_SEARCH_STAGES``, as are a pasted video's (``youtube_video_steps``: ``caracole youtube --video``, under
``YOUTUBE_SEARCH`` and ``video:<id>``). A UG link pasted into that box is read by ``caracole ug --link --progress``
(``ug_link_steps``), a job of no song's (``UG_LINK`` and the page's address, among ``INDEX_READS``), whose stages are
``UG_LINK_STAGES`` (an artist's link, the second alone). A push another caracole sent is taken by ``caracole peer take --progress``
(peer_routes.py), and a sync with another caracole is ``caracole peer sync --progress``: their JSON lines are their
stages (``PEER_TAKE_STAGES``, ``PEER_SYNC_STAGES``; an import's of a file staged here, ``caracole peer import
--progress``, commands/peer.py's ``PEER_IMPORT_STAGES``), each unit taken, given or left (``Job.units``) and, at the
end, what it did (``Job.report``, in memory alone, for the Sync tab's summary). The index
pages another caracole's lookups read, posted to ``/peer/index``, are merged by ``caracole index merge --delete
--progress -- FILE`` (``index_merge_job``): a job of no song's, one stage (``INDEX_MERGE_STAGES``). Each command
takes caracole's lock (a
lookup lets a nightly run hand it over at its next pause), keeps its pace,
budgets and cooldowns, exactly as from a terminal. One worker thread runs the
queue's jobs in order, and ``lane`` (``LANE``) more the lane's (below): lookups and
the search box's one-request reads, which start at once unless their song has a
job in the queue, and take turns with caracole's lock (commands/_common.py), so
the server is still no more aggressive than one lookup's pace a site. The
queue's worker starts a job only while no lane job runs or waits, which the lock
would make it wait for anyway, and a lane worker the first lane job whose song
has no job running (``song_of_job``: Make this my version and a harmonica tab's
reading are the song's jobs too): a song never has two jobs running.

A step that exits non-zero fails its job, and the job's other steps are
skipped; one the server ends as it stops (``stop``: Ctrl-C, systemd; every
command that runs) interrupts it (``INTERRUPTED``), as a restart does a job its
history left waiting or running. The queue holds ``limit`` jobs waiting or
running, one per song (a
lookup takes the place of the song's waiting add, since ``caracole get`` adds
the song itself, or follows it once it runs; a version you pick meanwhile
takes the place of the song's waiting lookup, or follows the running one, and a
lookup joins the song's Keep it, which never looks it up, or follows it: its
stages, which share names with Keep it's, start afresh when it does).
Given ``lane`` (``LANE``), the lookups' lane beside it holds
``lane`` running and ``lane_waiting`` (``LANE_WAITING``) waiting, its room
apart from the queue's: a request of the lane's commands alone (``lane_of``: a
lookup, a pasted UG link, LaCuerda's search, an artist's page on LaCuerda or
harptabs.com) is the lane's unless its song has a job in the queue, behind
which it waits in the queue (``Job.lane``, in memory alone). It remembers the last ``keep``
finished ones (``cancel`` takes one that hasn't started out of the queue, never one
that runs, and keeps it among those, cancelled), in memory and, given a
``history`` (history.py: caracole serve's ``state_dir/requests.jsonl``), in a
file it saves each job to as it changes, which the next server reads back: a
request is in wanted.txt from the moment it's made, so a restart loses no song,
and the history keeps what each request did. ``Job.as_json`` is a job as data,
for the page that shows a request's progress.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from caracole.get import read_progress_line

if TYPE_CHECKING:
    from caracole.web.history import History

Runner = Callable[[Sequence[str], Callable[[str], None]], int]
LIMIT = 20  # jobs waiting or running in the queue
LANE = 3  # the lookups' lane's jobs running at once beside the queue's one (``JobQueue(lane=LANE)``)
LANE_WAITING = 10  # and those waiting there for a slot, its room apart from the queue's ``LIMIT``
KEEP = 100  # finished jobs remembered, as the history keeps them (history.py)
MAX_LINES = 400  # output kept per step: the last lines
# A job the server stopped before it was over (``JobQueue.stop``, or a restart: history.py), and its step and stage
# that ran then: over, never run to its end; Try again queues its steps again.
INTERRUPTED = "interrupted"


class QueueFull(Exception):
    """The queue holds ``limit`` jobs already, or the lookups' lane its ``lane`` running and ``lane_waiting`` waiting,
    the request's place."""


class JobStarted(Exception):
    """A job asked to be cancelled that runs, or is over (``state``): a command is never stopped halfway."""

    def __init__(self, job_id: int, state: str):
        super().__init__(f"request {job_id} is {state}")
        self.state = state


@dataclass
class Step:
    label: str
    args: tuple[str, ...]
    state: str = "waiting"  # waiting, running, done, failed, skipped, interrupted
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
    state: str = "waiting"  # waiting, running, done, skipped, failed, interrupted
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
    # queued, running, done, failed, cancelled (before it ran: JobQueue.cancel), interrupted (the server stopped)
    state: str = "queued"
    queued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stages: list[Stage] = field(default_factory=list)  # a lookup's
    song_id: int | None = None
    song_display: str | None = None
    files: dict[str, str] = field(default_factory=dict)  # name -> path in the library, once readable
    seconds_to_sheet: float | None = None
    together: tuple[int, ...] = ()  # the jobs queued with it by one ``submit_all``, itself among them
    # A sync's units (``caracole peer take`` and ``peer sync --progress``), each (its id, "taken", "given" or
    # "left", why), as it said them
    units: list[tuple[str, str, str]] = field(default_factory=list)
    # What a sync or an import did, as its command says it at its end (``{"event": "report"}``, commands/peer.py),
    # for the Sync tab's summary (jobs_routes.py ``peer_outcome``): in memory alone, never in ``as_json`` nor the
    # history, so a job read back after a restart has none
    report: dict[str, Any] | None = field(default=None, compare=False)
    # Whether it is the lookups' lane's (``lane_of``, ``JobQueue.submit``), decided as it is queued: in memory alone,
    # never in ``as_json`` nor the history, as ``report``, so a job read back after a restart is the queue's
    lane: bool = field(default=False, compare=False)

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

    @property
    def from_audio(self) -> bool:
        """Whether it makes its song's sheet from an audio file you gave (``caracole audio``): its stages are
        audio_sheet.py's."""
        return any(_sheets_from_audio(step.args) for step in self.steps)

    @property
    def transcribes(self) -> bool:
        """Whether it transcribes its song's lyrics from its audio (``caracole transcribe``): its stages are
        transcribe_job.py's."""
        return any(_transcribes(step.args) for step in self.steps)

    @property
    def picks_lyrics(self) -> bool:
        """Whether it makes a record of its song's kept lyrics search its lyrics (``caracole lyrics --record``): its
        stages are lyrics_pick.py's."""
        return any(_picks_lyrics(step.args) for step in self.steps)

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
            "units": [list(unit) for unit in self.units],
        }

    def heard(self, event: Mapping[str, Any]) -> None:
        """Take in one event of ``caracole get --progress`` (get.py), or of a sync's (``{"event": "unit", "id",
        "outcome", "why"}`` and, at its end, ``{"event": "report", "report"}``, commands/peer.py)."""
        if event.get("event") == "unit":
            if isinstance(event.get("id"), str) and event.get("outcome") in ("taken", "given", "left"):
                self.units.append((event["id"], event["outcome"], str(event.get("why") or "")))
            return
        if event.get("event") == "report":
            report = event.get("report")
            self.report = dict(report) if isinstance(report, Mapping) else None
            return
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
    return [("Adding to the book", (*args, "--", artist, title))]


def fetch_steps(display: str) -> list[tuple[str, tuple[str, ...]]]:
    """Fetch one song now: match it (offline), fetch it from UG, render its PDF (offline)."""
    return [
        ("Matching", ("match",)),
        ("Fetching from UG", ("fetch", f"--song={display}")),
        ("Making the PDF", ("render", f"--song={display}")),
    ]


LOOKUP = "get"  # the command of a lookup


def lookup_steps(artist: str, title: str, *, album: str | None = None, duration_ms: int | None = None,
                 ug: str | None = None, tab: str | None = None, lacuerda: str | None = None,
                 harptabs: str | None = None, gametabs: str | None = None, ireal: str | None = None,
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
    if ireal:
        args.append(f"--ireal={ireal}")
    return [("Fetching", (*args, "--", artist, title))]


VERSIONS = "versions"  # the command that makes a song's version the one, keeps one, or takes its pin out


# Keep it's stages, as ``caracole versions --keep --progress`` reports them (versions_cmd.py), and ``--keep-more``'s
KEEP_STAGES = (
    ("song", "Find the song"),
    ("version", "Version from UG"),
    ("pdf", "Version's page"),
    ("pages", "The logbook page"),
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
        return [("Fetching the version from UG",
                 (VERSIONS, f"--keep={keep}", "--progress", "--", artist, title))]
    if keep_more:
        return [("Fetching versions from UG",
                 (VERSIONS, "--keep-more", "--progress", "--", artist, title))]
    return [("Going back to our pick", (VERSIONS, "--clear", "--progress", "--", artist, title))]


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
    --progress``, ``caracole lacuerda --search --progress``, ``caracole youtube --sheet --progress`` (``--search``,
    ``--video``), ``caracole ug --link --progress``, ``caracole transcribe --progress``, ``caracole audio --progress``,
    ``caracole lyrics --progress`` (a pick), or ``caracole peer take --progress``, ``peer sync --progress`` or ``index
    merge --progress``."""
    return args[:1] == (LOOKUP,) or (args[:1] in ((VERSIONS,), ("lacuerda",), ("youtube",), ("ug",), ("transcribe",),
                                                  ("audio",), ("lyrics",), (PEER,))
                                     and "--progress" in _options(args)) or (
        args[:2] == INDEX_MERGE_COMMAND and "--progress" in _options(args))


PEER = "peer"  # the command of a sync with another caracole: ``caracole peer take`` a push, ``peer sync``
# ``caracole peer take --progress``'s stages (commands/peer.py), a push another caracole sent taken here
PEER_TAKE_STAGES = (
    ("check", "What changed since compared"),
    ("take", "Taking what they wrote"),
    ("render", "Rendering what was taken"),
    ("agree", "Noting where the books agree"),
)
# ``caracole peer sync --progress``'s
PEER_SYNC_STAGES = (
    ("compare", "Comparing"),
    ("take", "Taking what they wrote"),
    ("give", "Giving what we wrote"),
    ("agree", "Noting where the books agree"),
    ("index", "Updating the indexes"),
)


# ``caracole index merge --delete --progress -- FILE``'s: the index pages another caracole's lookups read, merged
INDEX_MERGE_COMMAND = ("index", "merge")
INDEX_MERGE_STAGES = (("merge", "Merging the other scribe's index pages"),)
INDEX_MERGE = "index-merge:"  # an index export's merge: its job's key, the staged file's name after it


def _peer_stages(args: Sequence[str]) -> tuple[tuple[str, str], ...]:
    if args[:2] == INDEX_MERGE_COMMAND and "--progress" in _options(args):
        return INDEX_MERGE_STAGES
    if args[:1] != (PEER,) or "--progress" not in _options(args):
        return ()
    if args[1:2] == ("import",):  # a file staged by sync_file_routes.py, synced with
        from caracole.commands.peer import PEER_IMPORT_STAGES

        return PEER_IMPORT_STAGES
    return {"take": PEER_TAKE_STAGES, "sync": PEER_SYNC_STAGES}.get(args[1] if len(args) > 1 else "", ())


def index_merge_job(path: Path) -> dict[str, Any]:
    """The job that merges the index export staged at ``path`` (``POST /peer/index``, peer_routes.py) and deletes it
    after, as ``JobQueue.submit``'s arguments: ``caracole index merge --delete --progress -- FILE``, a job of no
    song's."""
    return {"title": "Index pages from another scribe", "song_key": INDEX_MERGE + path.name,
            "steps": [(INDEX_MERGE_STAGES[0][1], (*INDEX_MERGE_COMMAND, "--delete", "--progress", "--", str(path)))],
            "display": "Index pages from another scribe", "join": False}


LACUERDA_ARTIST = "lacuerda-artist:"  # a LaCuerda artist page's read: its job's key, the page's slug after it


def lacuerda_artist_steps(slug: str, name: str) -> list[tuple[str, tuple[str, ...]]]:
    """Read a LaCuerda artist's page into its index now: ``caracole lacuerda --artist``, one request."""
    return [(f"Reading {name}'s page on LaCuerda", ("lacuerda", f"--artist={slug}"))]


LACUERDA_SEARCH = "lacuerda-search:"  # a query of LaCuerda's search: its job's key, the query's key after it
HARPTABS_ARTIST = "harptabs-artist:"  # a harptabs.com artist page's read: its job's key, the page's path after it
YOUTUBE_SEARCH = "youtube-search:"  # a video suggested for a search: its job's key, the query's key after it
UG_LINK = "ug-link:"  # a UG link pasted into the library page's search box, read: its job's key, its page's address after
LYRICS_SEARCH = "lyrics-search:"  # a song's lyrics searched under a name: its job's key, the song's identity key after
# what a site's index reads, a search's suggestion, and a song's lyrics searched: jobs of no song's
INDEX_READS = (LACUERDA_ARTIST, LACUERDA_SEARCH, HARPTABS_ARTIST, YOUTUBE_SEARCH, UG_LINK, LYRICS_SEARCH)
SEARCH_STAGES = (("search", "Search LaCuerda"),)  # ``caracole lacuerda --search --progress``'s one stage
YOUTUBE_SEARCH_STAGES = (("video", "Search YouTube"), ("thumbnail", "Thumbnail"))  # ``caracole youtube --search``'s
UG_LINK_STAGES = (("tab", "Tab page"), ("artist", "Artist page"))  # ``caracole ug --link --progress``'s; an artist's: the second


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


def ug_link_steps(url: str) -> list[tuple[str, tuple[str, ...]]]:
    """A UG link pasted into the library page's search box, its page read now: ``caracole ug --link --progress``, a
    tab's page and its artist's lists, or an artist's lists, at the lookup pace (ug/link.py). ``url`` is the page's
    address as caracole asks for it (ug_urls.read_link's)."""
    return [("Reading the page on Ultimate Guitar", ("ug", f"--link={url}", "--progress"))]


def _ug_link_stages(args: Sequence[str]) -> tuple[tuple[str, str], ...]:
    """A step's stages when it reads a UG link (``caracole ug --link``): a tab's both, an artist's its lists alone."""
    from caracole.ug_urls import read_link

    if args[:1] != ("ug",):
        return ()
    link = next((read_link(a.removeprefix("--link=")) for a in args if a.startswith("--link=")), None)
    return () if link is None else UG_LINK_STAGES if link.kind == "tab" else UG_LINK_STAGES[1:]


def harptabs_artist_steps(path: str, name: str) -> list[tuple[str, tuple[str, ...]]]:
    """Read a harptabs.com artist's page into its index now: ``caracole harptabs --artist``, one request."""
    return [(f"Reading {name}'s page on harptabs", ("harptabs", f"--artist={path}"))]


def _searches(args: Sequence[str]) -> bool:
    """Whether a step's command is a query of LaCuerda's search."""
    return args[:1] == ("lacuerda",) and any(arg.startswith("--search=") for arg in args)


YOUTUBE_SHEET = "youtube:"  # a sheet from a YouTube video: its job's key, the song's identity key after it


def youtube_sheet_steps(display: str, url: str) -> list[tuple[str, tuple[str, ...]]]:
    """Make a song's auto sheet from a YouTube video now: ``caracole youtube --sheet --progress``, one process for
    every stage (youtube_sheet.py's ``STAGES``): the audio with yt-dlp, the lyrics, the words heard where no site has
    them, the chords, the PDF. ``url`` is
    the video's plain address (youtube_urls.watch_url)."""
    return [("Making the sheet",
             ("youtube", "--sheet", "--progress", f"--url={url}", f"--song={display}"))]


def _sheets_from_youtube(args: Sequence[str]) -> bool:
    """Whether a step's command makes a song's sheet from a YouTube video (``caracole youtube --sheet``)."""
    return args[:1] == ("youtube",) and "--sheet" in args


TRANSCRIBE = "transcribe:"  # lyrics transcribed from a song's audio: its job's key, the song's identity key after it


def transcribe_steps(display: str, *, force: bool = False, none: bool = False) -> list[tuple[str, tuple[str, ...]]]:
    """Transcribe a song's lyrics from its audio now, and make its auto sheet again over them: ``caracole transcribe
    --progress``, one process for every stage (transcribe_job.py's ``STAGES``): where the singing is, the words, the
    chords, the PDF. ``force``, Transcribe anyway (``--force``); ``none``, Not sung: chords only (``--none``), its
    transcript dropped and its chords made alone."""
    if none:
        return [("Making the chords alone", ("transcribe", "--progress", "--none", f"--song={display}"))]
    flags = ("--force",) if force else ()
    return [("Transcribing the lyrics", ("transcribe", "--progress", *flags, f"--song={display}"))]


def _transcribes(args: Sequence[str]) -> bool:
    """Whether a step's command transcribes a song's lyrics from its audio (``caracole transcribe``)."""
    return args[:1] == ("transcribe",)


def lyrics_search_steps(display: str, name: str) -> list[tuple[str, tuple[str, ...]]]:
    """Look a song's lyrics up now under ``name`` ("Artist - Title", the one you typed): ``caracole lyrics --song
    --as``, LRCLIB's, Megalobiz's and AZLyrics' records listed at the lookup pace (lyrics_search.py), kept for a pick;
    no ``--progress`` and no stages: its line is its last line."""
    return [(f"Looking for lyrics under “{name}”", ("lyrics", f"--song={display}", f"--as={name}"))]


LYRICS_PICK = "lyrics:"  # a record of a song's kept lyrics search picked: its job's key, the song's key after it


def lyrics_pick_steps(display: str, record: str) -> list[tuple[str, tuple[str, ...]]]:
    """Make a record of the song's kept lyrics search (``record``, ``SITE:ID``) its lyrics now, and its auto sheet
    again over them: ``caracole lyrics --song --record --progress``, one process for every stage (lyrics_pick.py's
    ``STAGES``)."""
    return [("Taking the lyrics", ("lyrics", f"--song={display}", f"--record={record}", "--progress"))]


def _picks_lyrics(args: Sequence[str]) -> bool:
    """Whether a step's command makes a record of a song's kept lyrics search its lyrics (``caracole lyrics --pick``
    or ``--record``)."""
    return args[:1] == ("lyrics",) and any(arg.startswith(("--pick=", "--record=")) for arg in _options(args))


AUDIO_SHEET = "audio:"  # a sheet from an audio file you gave: its job's key, the song's identity key after it


def audio_sheet_steps(display: str, upload: str) -> list[tuple[str, tuple[str, ...]]]:
    """Make a song's auto sheet from an audio file uploaded now: ``caracole audio --progress``, one process for every
    stage (audio_sheet.py's ``STAGES``): the file kept as the song's audio, the lyrics, the words heard where no site
    has them, the chords, the PDF. ``upload`` is the staged upload's 16-hex id (audio_store.py), never a path."""
    return [("Making the sheet", ("audio", "--progress", f"--upload={upload}", f"--song={display}"))]


def _sheets_from_audio(args: Sequence[str]) -> bool:
    """Whether a step's command makes a song's sheet from an audio file (``caracole audio``)."""
    return args[:1] == ("audio",)


def uploads_named(jobs: Sequence[Job]) -> set[str]:
    """The staged uploads (audio_store.py ids) the waiting and running jobs of ``jobs`` name (``--upload=``)."""
    return {arg.removeprefix("--upload=") for job in jobs if job.active for step in job.steps
            if _sheets_from_audio(step.args) for arg in step.args if arg.startswith("--upload=")}


def song_key_of(job_key: str) -> str:
    """The song's identity key in a job's key: a removal's, a sheet from YouTube's, a transcription's, a sheet from
    an audio file's and a lyrics pick's have theirs after a prefix."""
    return (job_key.removeprefix(REMOVING).removeprefix(YOUTUBE_SHEET).removeprefix(TRANSCRIBE)
            .removeprefix(AUDIO_SHEET).removeprefix(LYRICS_PICK))


def song_of_job(job_key: str) -> str:
    """The song a job is about, for the lane alone (``JobQueue``'s place for a request, and the song a lane worker
    sees running): ``song_key_of``'s, and the song's own changes, Make this my version (``EXPORTING``) and a harmonica
    tab's reading (``READING``), whose keys hold the song's identity key after their prefix, up to its first ":" (an
    identity key has none); and a lyrics search's (``LYRICS_SEARCH``), a job of no song's everywhere else, so that it
    never runs beside the song's pick or transcription, nor they beside it. The queue's joining and every other reader
    keep ``song_key_of`` and the whole key."""
    for prefix in (EXPORTING, READING):
        if job_key.startswith(prefix):
            return job_key.removeprefix(prefix).split(":", 1)[0]
    return song_key_of(job_key.removeprefix(LYRICS_SEARCH))


def _in_the_lane(args: Sequence[str]) -> bool:
    """Whether a step's command is one of the lookups' lane's (``lane_of``)."""
    options = _options(args)
    if args[:1] == (LOOKUP,):
        return "--no-songbooks" not in options
    if args[:1] == ("ug",):
        return any(arg.startswith("--link=") for arg in options)
    if args[:1] == ("lacuerda",):
        return any(arg.startswith(("--search=", "--artist=")) for arg in options)
    if args[:1] == ("harptabs",):
        return any(arg.startswith("--artist=") for arg in options)
    if args[:1] == ("lyrics",):
        return any(arg.startswith("--as=") for arg in options)
    return False


def lane_of(steps: Sequence[tuple[str, Sequence[str]]]) -> bool:
    """Whether a request of these steps is the lookups' lane's (``JobQueue(lane=…)``), its song's jobs in the queue
    aside (``JobQueue.submit``): every one a command asked for now that sends a lookup's few requests and takes turns
    at caracole's lock in the lane (commands/_common.py ``exclusive(..., lane=True)``): ``caracole get``, but for a
    songbook's Get the missing songs (``--no-songbooks``), which would fill the lane for minutes; ``ug --link``;
    ``lacuerda --search`` and ``--artist``; ``harptabs --artist``; ``lyrics --as``, a song's lyrics searched. A
    yt-dlp run (``youtube``), ``versions``, an add and every other command are the queue's, and so is a request with
    one of them."""
    return bool(steps) and all(_in_the_lane(tuple(args)) for _, args in steps)


def ahead(jobs: Sequence[Job], job: Job) -> int:
    """How many requests waiting or running a queued one waits for, of ``jobs`` in any order: a lane job, the lane's
    before it; a queue job, every one before it and every lane job, which goes first. With no lane job, every one
    before it, as a queue of no lane counts."""
    if job.lane:
        return sum(1 for j in jobs if j.active and j.lane and j.id < job.id)
    return sum(1 for j in jobs if j.active and j.id != job.id and (j.id < job.id or j.lane))


def _pick(steps: Sequence[Step]) -> tuple[str, ...]:
    """The Ultimate Guitar song and tab, the LaCuerda song, the harptabs.com tab, the gametabs.net tab and the iReal Pro
    chart a lookup's ``caracole get`` was given (``--ug``, ``--tab``, ``--lacuerda``, ``--harptabs``, ``--gametabs``,
    ``--ireal``), and what a ``caracole versions`` does (``--choose``,
    ``--keep``, ``--keep-more``, ``--clear``), if any."""
    picked: list[str] = []
    for step in steps:
        options = _options(step.args)
        if step.args[:1] == (LOOKUP,):
            picked += [arg for arg in options
                       if arg.startswith(("--ug=", "--tab=", "--lacuerda=", "--harptabs=", "--gametabs=", "--ireal="))]
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
    it's it hasn't, a search of LaCuerda's (``SEARCH_STAGES``), a sheet from a YouTube video's
    (youtube_sheet.py's ``STAGES``), a transcription's (transcribe_job.py's ``STAGES``), a sheet from an audio
    file's (audio_sheet.py's ``STAGES``), a lyrics pick's (lyrics_pick.py's ``STAGES``), a sync's with another
    caracole (``PEER_TAKE_STAGES``,
    ``PEER_SYNC_STAGES``, ``INDEX_MERGE_STAGES``), and a UG link's read (``UG_LINK_STAGES``); none for other
    commands."""
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
    if any(_transcribes(step.args) for step in steps):
        from caracole.transcribe_job import STAGES as TRANSCRIBE_STAGES

        names.update((name, label) for name, label in TRANSCRIBE_STAGES if name not in names)
    if any(_sheets_from_audio(step.args) for step in steps):
        from caracole.audio_sheet import STAGES as AUDIO_STAGES

        names.update((name, label) for name, label in AUDIO_STAGES if name not in names)
    if any(_picks_lyrics(step.args) for step in steps):
        from caracole.lyrics_pick import STAGES as PICK_STAGES

        names.update((name, label) for name, label in PICK_STAGES if name not in names)
    for step in steps:
        names.update((name, label) for name, label in _peer_stages(step.args) if name not in names)
        names.update((name, label) for name, label in _ug_link_stages(step.args) if name not in names)
    return [Stage(name, label) for name, label in names.items()]


def _as_much(mine: Sequence[Job], waiting: Job | None, new: Sequence[Step], *, fetching: bool,
             join: bool) -> Job | None:
    """Which of a song's jobs waiting or running (``mine``; ``waiting``, the first that waits) does as much as a
    request of ``new`` steps, and so is its answer (``JobQueue.submit``): for your pick joining them, only the song's
    last job, with the same pick; else one that looks the song up or fetches it, or, for a request that fetches
    nothing or mustn't join, any. None for none."""
    picked = _pick(new)
    if picked and join:  # your pick: only the song's last job, looking it up already, does as much
        last = waiting or next((job for job in mine if job.state == "running"), None)
        return last if last is not None and _pick(last.steps) == picked else None
    enough = next((job for job in mine if _fetches(job.steps)), None)  # a lookup or a fetch does the most
    if enough is None and (not fetching or not join) and mine:
        enough = mine[0]
    return enough


def _join(waiting: Job, new: Sequence[Step], title: str, note: str) -> None:
    """A request of ``new`` steps joins the song's job that still waits (``JobQueue.submit``): its ``caracole get``
    (or ``caracole versions --choose``) takes the place of the job's add and lookup, and the job gets each of its
    commands it doesn't run, with their stages; it fetches now, under the request's title, and keeps its note, else
    takes the request's."""
    # One `caracole get` does it all, as `caracole versions --choose` runs one
    if any(step.args[:1] == (LOOKUP,) or (_looks_up(step.args) and "--clear" not in step.args)
           for step in new):
        waiting.steps = [s for s in waiting.steps if s.args[:1] not in (("add",), (LOOKUP,))]
        waiting.stages = []
    runs = {step.args[0] for step in waiting.steps}
    commands = {step.args for step in waiting.steps}
    # Two versions kept, or a pin taken out after a version kept, are two commands
    waiting.steps += [step for step in new if step.args[0] not in runs
                      or (step.args[0] == VERSIONS and step.args not in commands)]
    had = {stage.name for stage in waiting.stages}  # a job waiting has heard nothing yet
    waiting.stages += [stage for stage in _stages(waiting.steps) if stage.name not in had]
    waiting.title, waiting.fetching = title, True
    waiting.note = waiting.note or note


REMOVING = "remove:"  # a removal's song_key: the song's key after it, so it never joins the song's add or fetch
EXPORTING = "export:"  # Make this my version's song_key (export_routes.py): the song's key and the version, then MINE,
MINE = ":mine"  # never the song's own key, so it joins no request of the song's
READING = "harmonica:"  # a harmonica tab's reading pinned (harmonica_routes.py): the song's key, the tab, the reading, MINE


def remove_steps(display: str) -> list[tuple[str, tuple[str, ...]]]:
    """``caracole remove --yes``: the page asked already, and showed what goes."""
    return [("Removing from the book", ("remove", "--yes", "--", display))]


def review_steps(display: str, *, pick: str | None = None,
                 seen: Sequence[str] = ()) -> list[tuple[str, tuple[str, ...]]]:
    """Answer a song's review as ``caracole review`` does, with no question: ``pick`` (a candidate's
    ARTIST/SONG), or, without it, none of the candidates ``seen``. It matches the song again (and,
    with an ``[alias]``, its artist's other songs) and rewrites the pages itself, so a fetch after it
    needs no ``caracole match``."""
    answer = (f"--pick={pick}",) if pick is not None else ("--none", *(f"--seen={ref}" for ref in seen))
    return [("Noting your answer in overrides.toml", ("review", f"--song={display}", *answer))]


class JobQueue:
    """Jobs in order, run by worker threads (``start``: the queue's one, and the lane's), or by ``run_pending`` in
    tests; with ``history``, those the last server left read back from it (history.py), and every job saved to it as
    it changes. ``lane``, the lookups' lane's jobs running at once (``LANE``), each on a worker of its own, and
    ``lane_waiting``, those waiting there: its room, apart from the queue's ``limit``; with ``lane`` 0, none, every
    request the queue's and one worker, as before the lane."""

    def __init__(self, runner: Runner, *, limit: int = LIMIT, keep: int = KEEP, max_lines: int = MAX_LINES,
                 history: History | None = None, lane: int = 0, lane_waiting: int = LANE_WAITING):
        self._runner = runner
        self._limit = limit
        self._lanes = lane
        self._lane_waiting = lane_waiting
        self._keep = keep
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._jobs: list[Job] = []
        self._next_id = 1
        self._stopping = False
        self._threads: list[threading.Thread] = []
        self.history = history
        if history is not None:
            self._jobs, self._next_id = history.load()

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
        once it is done.

        Given a lane (``lane``), a request of the lane's commands alone (``lane_of``) is the lane's, unless its song
        (``song_of_job``) has a job waiting or running in the queue (its removal, its sheet from YouTube, a
        songbook's lookup of it, its Keep it, a pick's review, Make this my version, a harmonica tab's reading): then
        it is the queue's, behind that job, by the rules
        above. A request joins only a job waiting in its own place: a lane request the song's lane job, a queue
        request never a lane job that waits (it is a job of its own in the queue), though a lane job that does as
        much is still its answer. Raises QueueFull when its place is full: the queue's ``limit`` jobs waiting or
        running, or the lane's ``lane`` running and ``lane_waiting`` waiting.
        """
        with self._lock:
            done = self._submit_locked(title, song_key, steps, fetching=fetching, note=note, display=display,
                                       join=join, song_id=song_id)
            self._save(done[0].id)
            return done

    def submit_all(self, requests: Sequence[dict[str, Any]]) -> list[tuple[Job, bool]]:
        """``submit`` of each request (a dict of its arguments: ``title``, ``song_key``, ``steps`` and the options),
        all or none, under the queue's one lock: when one finds its place full (the queue, or the lane: each
        request's own), QueueFull is raised and the queue is as it was, the jobs the earlier ones joined or queued
        as before. A request that joins a job already
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
                for job_id in dict.fromkeys(job.id for job, _ in done):  # saved once all are queued
                    self._save(job_id)
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
        """``submit`` under the queue's lock, held by its caller (``submit``, ``submit_all``), by ``submit``'s rules:
        its place (the lane or the queue), then the song's job that does as much (in either), else its job that still
        waits in that place, joined, else a job of its own there, room allowing."""
        new = [Step(label, tuple(args)) for label, args in steps]
        song = song_of_job(song_key)
        lane = self._lanes > 0 and lane_of(steps) and not any(
            job.active and not job.lane and song_of_job(job.song_key) == song for job in self._jobs)
        mine = [job for job in self._jobs if job.active and job.song_key == song_key]
        waiting = next((job for job in mine if job.state == "queued" and job.lane == lane), None)
        enough = _as_much(mine, waiting, new, fetching=fetching, join=join)
        if enough is not None:
            return copy.deepcopy(enough), False
        if waiting is not None:
            _join(waiting, new, title, note)
            return copy.deepcopy(waiting), False
        if lane:
            if sum(job.active and job.lane for job in self._jobs) >= self._lanes + self._lane_waiting:
                raise QueueFull(f"{self._lanes + self._lane_waiting} lookups are running or waiting already")
        elif sum(job.active and not job.lane for job in self._jobs) >= self._limit:
            raise QueueFull(f"{self._limit} requests are waiting already")
        job = Job(self._next_id, title, song_key, new, fetching=fetching, note=note, display=display or title,
                  stages=_stages(new), song_id=song_id,
                  song_display=(display or title) if song_id is not None else None, lane=lane)
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
                    self._save(j.id)
            self._forget()
            self._wake.notify_all()  # a lane job gone: the lane may be empty, the queue's next job free to start
            return copy.deepcopy(job)

    def snapshot(self) -> list[Job]:
        """Every job remembered, newest first, as copies."""
        with self._lock:
            return copy.deepcopy(self._jobs[::-1])

    def job(self, job_id: int) -> Job | None:
        """A job remembered, as a copy; None for one never queued, or forgotten."""
        with self._lock:
            return next((copy.deepcopy(j) for j in self._jobs if j.id == job_id), None)

    @property
    def lanes(self) -> int:
        """The lookups' lane's jobs that run at once (``JobQueue(lane=…)``); 0, no lane."""
        return self._lanes

    def active_count(self) -> int:
        """The jobs waiting or running, in the queue and in the lane."""
        with self._lock:
            return sum(job.active for job in self._jobs)

    def room(self) -> int:
        """How many more jobs the queue takes now: ``limit``, less those waiting or running in it (the lane's
        room is its own)."""
        with self._lock:
            return max(0, self._limit - sum(job.active and not job.lane for job in self._jobs))

    def fetching_keys(self) -> set[str]:
        """The songs a waiting or running job will fetch."""
        with self._lock:
            return {job.song_key for job in self._jobs if job.active and job.fetching}

    # --- the workers -----------------------------------------------------------------------------

    def start(self) -> None:
        """Start the queue's worker, and one worker a slot of the lane (``lanes``)."""
        self._threads = [threading.Thread(target=self._work, name="caracole-jobs", daemon=True)]
        self._threads += [threading.Thread(target=self._work, args=(True,), name=f"caracole-lane-{n}", daemon=True)
                          for n in range(1, self._lanes + 1)]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float = 10) -> None:
        """Stop the workers, ending every command they run (each job interrupted), and wait ``timeout`` seconds at
        most for them all."""
        with self._lock:
            self._stopping = True
            self._wake.notify_all()
        terminate = getattr(self._runner, "terminate", None)
        if terminate is not None:
            terminate()
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))

    def run_pending(self) -> None:
        """Run the queued jobs here and now, for tests, one at a time and each to its end: the lane's first, in order,
        then the queue's. The workers (``start``) start the lane's at once, several beside each other and beside the
        queue's running job, so this is one order they may take, never what they do at once."""
        while (job := self._next(True) or self._next(False)) is not None:
            self._run(job)

    def _work(self, lane: bool = False) -> None:
        """A worker: the queue's, or one of the lane's; it sleeps until a job it may start is there (``_take``),
        woken as a job is queued, cancelled or ends."""
        while True:
            with self._lock:
                while not self._stopping and (job := self._take(lane)) is None:
                    self._wake.wait()
                if self._stopping:
                    return
            self._run(job)

    def _next(self, lane: bool = False) -> Job | None:
        """The job a worker starts now (``_take``), marked running; None for none."""
        with self._lock:
            return self._take(lane)

    def _take(self, lane: bool) -> Job | None:
        """``_next`` under the queue's lock: for the queue's worker, its first queued job outside the lane, only while
        no lane job runs or waits (with no lane, its first queued job, as before the lane); for a lane worker, the
        first queued lane job whose song (``song_of_job``: its own changes among its jobs) has no job running."""
        if lane:
            running = {song_of_job(j.song_key) for j in self._jobs if j.state == "running"}
            job = next((j for j in self._jobs
                        if j.state == "queued" and j.lane and song_of_job(j.song_key) not in running), None)
        elif any(j.active and j.lane for j in self._jobs):
            job = None
        else:
            job = next((j for j in self._jobs if j.state == "queued" and not j.lane), None)
        if job is not None:
            job.state = "running"
            job.started_at = datetime.now(UTC)
            self._save(job.id)
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
                # A command ended as the server stops (``stop``) is interrupted, never failed
                step.state = "done" if code == 0 else INTERRUPTED if self._stopping else "failed"
                failed = failed or code != 0
        with self._lock:
            interrupted = self._stopping and any(s.state != "done" for s in job.steps)
            job.state = ("failed" if failed or any(s.state != "done" for s in job.steps) else "done"
                         ) if not interrupted else INTERRUPTED
            job.finished_at = datetime.now(UTC)
            for stage in job.stages:  # a lookup that ended early: nothing is left running or waiting
                if stage.state == "running":
                    stage.state = INTERRUPTED if interrupted else "failed" if job.state == "failed" else "done"
                elif stage.state == "waiting":
                    stage.state = "skipped"
            self._save(job.id)
            self._forget()
            self._wake.notify_all()  # its song free, the lane maybe empty: another worker may start a job

    def _save(self, job_id: int) -> None:
        """Save the job as it is now to the history, if there is one; under the queue's lock, so saves are in
        order."""
        if self.history is not None:
            job = next((j for j in self._jobs if j.id == job_id), None)
            if job is not None:
                self.history.save(job, self._jobs, self._next_id)

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
    """Runs ``python -P -m caracole -v [--config FILE | --home] ARGS…`` and hands each line it prints to ``emit``.

    ``home``: caracole serve runs on its home defaults, and its commands on them too, saying nothing of a
    service beside them (service.py): the server said it once, as it started.

    ``-m`` alone would put the working directory first on the child's
    ``sys.path``, which the ``caracole`` script never does: started from the
    synced library, the server would run any ``typer.py`` a device dropped
    there. ``-P`` (Python 3.11) leaves it out.
    """

    def __init__(self, config_path: Path | None, *, python: str = sys.executable, home: bool = False):
        self._argv = [python, "-P", "-m", "caracole", "-v",
                      *(["--config", str(config_path)] if config_path else ["--home"] if home else [])]
        self._env = child_env()
        self._lock = threading.Lock()
        self._processes: set[subprocess.Popen[str]] = set()  # a process a command running now, of every worker
        self._terminated = False  # ``terminate`` ran: the server stops, and no command starts after it

    def __call__(self, args: Sequence[str], emit: Callable[[str], None]) -> int:
        with self._lock:  # started and kept at once, so that ``terminate`` ends every process started before it
            if self._terminated:  # a worker past its check as the server stopped: ended, as ``terminate`` would
                return -15
            process = subprocess.Popen(
                [*self._argv, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=self._env,
            )
            self._processes.add(process)
        try:
            assert process.stdout is not None
            for line in process.stdout:
                emit(line.rstrip("\n"))
            return process.wait()
        finally:
            with self._lock:
                self._processes.discard(process)

    def terminate(self) -> None:
        """End every command running now, as Ctrl-C or systemd would: each lets go of the lock as it exits. A command
        asked after it starts no process and gives -15, as one ended so does (``JobQueue.stop``'s race: a worker
        that passed its check as the server stopped)."""
        with self._lock:
            self._terminated = True
            for process in self._processes:
                if process.poll() is None:
                    process.terminate()
