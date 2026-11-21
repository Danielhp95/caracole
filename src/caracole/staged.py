"""A job of stages over one song, reported as a lookup reports its own: the half that the jobs making a song's sheet
in stages share, a sheet from a YouTube video (youtube_sheet.py) and its lyrics transcribed from its audio
(transcribe_job.py).

Each stage is said as it starts and as it ends (get.py's ``Progress``: with ``--progress`` a JSON line per event,
which caracole serve reads into the job's stages); the job's own subclass of ``StagedRun`` holds the stages and
runs them under caracole's lock:

- ``stage`` runs one, its end ``(state, detail)`` or a detail of ``done``; an exception it raises is a bug in
  caracole, said in its words, the stages after it going on as they can;
- ``_fail``: an end that waiting won't mend (``result.failed``, and the command exits 1);
- ``_check_readable``: the sheet said readable (``Progress.readable``) once the chords stage kept it, and again as
  its PDF and viewer come;
- ``_song_again``: the song read again after the job let a lookup have the lock; gone (removed, or merged into a
  song of the same name), the job ends there, ``_Stop``, before anything more is written for it;
- ``_refuse``: the job refused, its song stage failed with why, the stages that hadn't ended skipped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from caracole.config import Config
from caracole.get import Progress, readable_files

log = logging.getLogger(__name__)


@dataclass
class StagedResult:
    song_id: int | None = None
    display: str = ""
    states: dict[str, str] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)  # name -> library-relative path, once readable
    seconds: float = 0.0
    requests: dict[str, int] = field(default_factory=dict)
    refused: str | None = None  # the song stage's refusal
    failed: str | None = None  # what waiting won't mend: the command exits 1
    bug: str | None = None

    @property
    def ok(self) -> bool:
        return self.refused is None and self.failed is None and self.bug is None


class _Stop(Exception):
    """The job can't go on for the song: said in the song stage, the others skipped."""


class StagedRun:
    """The reporting half of a job of ``STAGES`` (``(name, label)``, the song's stage first) over one song."""

    STAGES: tuple[tuple[str, str], ...] = ()
    MAKING = "its sheet was made"  # what the job was doing, for a song that left the book meanwhile

    def __init__(self, cfg: Config, progress: Progress, result: StagedResult, *, clock: Callable[[], float]):
        self.cfg, self.progress, self.result, self.clock = cfg, progress, result, clock
        self.started = clock()
        self.conn: Any = None
        self.song: Any = None

    def _report(self, name: str, state: str, detail: str = "") -> None:
        self.result.states[name] = state
        if state != "running":
            self.result.details[name] = detail
        self.progress.stage(name, state, detail)

    def stage(self, name: str, run: Callable[[], tuple[str, str] | str]) -> None:
        """Run one stage; what it returns is its end, ``(state, detail)`` or a detail of ``done``."""
        self._report(name, "running")
        try:
            out = run()
        except _Stop:  # the song left the book: the job ends there (``run``)
            raise
        except Exception as e:  # a bug: say so, and leave the stages after it
            log.error("The %s stage failed: %s: %s. That's a bug in caracole; its traceback follows.", name,
                      type(e).__name__, e, exc_info=True)
            self.result.bug = self.result.bug or f"{name}: {type(e).__name__}: {e}"
            self._report(name, "failed", f"a bug in caracole: {type(e).__name__}: {e}")
            return
        state, detail = out if isinstance(out, tuple) else ("done", out or "")
        self._report(name, state, detail)
        self._check_readable()

    def _check_readable(self) -> None:
        """Say the sheet is readable once its auto sheet is kept, and again when its PDF or viewer comes."""
        if self.song is None or self.result.states.get("chords") != "done":
            return
        files = readable_files(self.conn, self.cfg.library_dir, self.song)
        if files and files != self.result.files:
            self.result.files = files
            self.progress.readable(files, self.clock() - self.started)

    def _fail(self, detail: str) -> tuple[str, str]:
        """A stage's end that waiting won't mend: the command exits 1."""
        self.result.failed = self.result.failed or detail
        return "failed", detail

    def _song_again(self) -> None:
        """The song read again; gone (another caracole removed it, or merged it into a song of the same name, while
        this one let a lookup have the lock), the job ends there, a refusal (``_Stop``), before anything more is
        written for it."""
        from caracole.songs import get_song

        try:
            self.song = get_song(self.conn, self.song.id)
        except KeyError:
            raise _Stop(f"{self.song.display} left the book while {self.MAKING} (removed, or merged into a song "
                        "of the same name)") from None

    def _refuse(self, why: str) -> StagedResult:
        """The job refused, its song stage failed with ``why``; the stages that hadn't ended, skipped."""
        self.result.refused = why
        self._report("song", "failed", why)
        for name, _ in self.STAGES[1:]:
            if self.result.states.get(name, "running") == "running":
                self._report(name, "skipped", "")
        self.result.seconds = self.clock() - self.started
        return self.result
