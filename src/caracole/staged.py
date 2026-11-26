"""A job of stages over one song, reported as a lookup reports its own: what the jobs making a song's sheet in stages
share, a sheet from a YouTube video (youtube_sheet.py) and its lyrics transcribed from its audio (transcribe_job.py).

Each stage is said as it starts and as it ends (get.py's ``Progress``: with ``--progress`` a JSON line per event,
which caracole serve reads into the job's stages). A job is a subclass of ``StagedRun`` with its ``STAGES``, the song's
first, and a method a stage of the same name (``find_song`` for the song's); ``_run`` runs them in order under
caracole's lock, as asked for now:

- ``stage`` runs one, its end ``(state, detail)`` or a detail of ``done``; an exception it raises is a bug in
  caracole, said in its words, the stages after it going on as they can;
- ``_doing``: what a long stage is doing, said while it runs (a running event with that detail, each change once),
  which the song's line shows (web/status.py ``LONG_STAGES``): the models take minutes, and a line that never moves
  reads as no progress;
- ``_fail``: an end that waiting won't mend (``result.failed``, and the command exits 1);
- ``_check_readable``: the sheet said readable (``Progress.readable``) once the chords stage kept it, and again as
  its PDF and viewer come;
- ``_after_a_lookup``: before a long stage, a waiting lookup goes first (``_common.hand_over``), then overrides.toml
  and the song read again;
- ``_song_again``: the song read again; gone (removed, or merged into a song of the same name), the job ends there,
  ``_Stop``, before anything more is written for it;
- ``_refuse``: the job refused, its song stage failed with why, the stages that hadn't ended skipped;
- the stages both jobs end with: the song's auto sheet from auto-chords (``_autochords_sheet``, the chords stage's
  end, each of auto-chords' steps said as it starts), ``pdf`` and ``pages``.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
    """A job of ``STAGES`` (``(name, label)``, the song's stage first) over one song.

    ``runner`` runs chordpro, ``recognizer`` and ``beats_fn`` are auto-chords' models (None: built from ``cfg``),
    ``now`` the run's time."""

    STAGES: tuple[tuple[str, str], ...] = ()
    MAKING = "its sheet was made"  # what the job was doing, for a song that left the book meanwhile

    def __init__(self, cfg: Config, progress: Progress, result: StagedResult, *, runner: Callable = subprocess.run,
                 recognizer: Any = None, beats_fn: Any = None, now: datetime | None = None,
                 clock: Callable[[], float]):
        from caracole.commands._common import run_id_for, utcnow

        self.cfg, self.progress, self.result, self.clock = cfg, progress, result, clock
        self.runner, self.recognizer, self.beats_fn = runner, recognizer, beats_fn
        self.started = clock()
        self.now = (now or utcnow()).replace(microsecond=0)
        self.run_id = run_id_for(self.now)
        self.conn: Any = None
        self.overrides: Any = None
        self.song: Any = None
        self._told: dict[str, str] = {}  # what each stage said last while it ran

    # --- reporting ----------------------------------------------------------------------------------------

    def _report(self, name: str, state: str, detail: str = "") -> None:
        self.result.states[name] = state
        if state != "running":
            self.result.details[name] = detail
        self._told[name] = detail
        self.progress.stage(name, state, detail)

    def _doing(self, name: str, detail: str) -> None:
        """What the stage ``name``, running, is doing now: said once each time it changes."""
        if self.result.states.get(name) == "running" and self._told.get(name) != detail:
            self._report(name, "running", detail)

    def stage(self, name: str, run: Callable[[], tuple[str, str] | str]) -> None:
        """Run one stage; what it returns is its end, ``(state, detail)`` or a detail of ``done``."""
        self._report(name, "running")
        try:
            out = run()
        except _Stop:  # the song left the book: the job ends there (``_run``)
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

    def _refuse(self, why: str) -> StagedResult:
        """The job refused, its song stage failed with ``why``; the stages that hadn't ended, skipped."""
        self.result.refused = why
        self._report("song", "failed", why)
        for name, _ in self.STAGES[1:]:
            if self.result.states.get(name, "running") == "running":
                self._report(name, "skipped", "")
        self.result.seconds = self.clock() - self.started
        return self.result

    # --- between the stages ----------------------------------------------------------------------------------

    def _after_a_lookup(self) -> None:
        """A waiting lookup goes first, as the stage to come takes minutes; then overrides.toml and the song read
        again (``_song_again``)."""
        from caracole.commands._common import hand_over, handoffs, overrides_since

        handed = handoffs()
        hand_over(self.cfg, self.conn)
        self.overrides = overrides_since(self.cfg, self.overrides, handed)
        self._song_again()

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

    def _audio_length(self) -> float | None:
        """The song's audio's length in seconds: as yt-dlp reported it, else as its file says; None when neither
        tells (a length is a hint: the lyrics sites are asked without one)."""
        from caracole.music import read_audio
        from caracole.youtube_fetch import youtube_audio

        video = youtube_audio(self.conn, self.song)
        if video is not None and video.duration:
            return video.duration
        try:
            return read_audio(Path(self.song.audio_path or "")).duration_s
        except Exception as e:  # noqa: BLE001 - a length is a hint: LRCLIB is asked without one
            log.info("The length of %s can't be read: %s", self.song.audio_path, e)
            return None

    # --- the stages both jobs end with -------------------------------------------------------------------

    def _autochords_sheet(self) -> tuple[str, str]:
        """auto-chords for this song alone (``autochords_pending``'s ``only``), and what the sheet holds once kept:
        the chords stage's end."""
        from caracole.autochords.run import autochords_pending
        from caracole.songs import AUTO_SHEET
        from caracole.versions import get_version
        from caracole.youtube_sheet import holds

        stats = autochords_pending(self.conn, self.cfg, recognizer=self.recognizer, beats_fn=self.beats_fn,
                                   now=self.now, overrides=self.overrides, only={self.song.id},
                                   on_step=lambda said: self._doing("chords", said))
        self._song_again()
        if stats.errors:
            return self._fail(f"auto-chords can't run here ({stats.errors[0]})")
        if stats.failures:
            return self._fail("auto-chords can't read the audio")
        kept = self.conn.execute(
            "SELECT version_id FROM files WHERE song_id = ? AND name = ?", (self.song.id, AUTO_SHEET)).fetchone()
        made = kept is not None and self.song.autochords_mtime == self.song.audio_mtime
        if not made:
            return self._fail("auto-chords made no sheet (see the log)")
        held = holds(get_version(self.conn, kept[0]).raw)
        return "done", held if stats.generated else f"up to date: {held}"

    def pdf(self) -> tuple[str, str] | str:
        from caracole.render import render_all

        if self.result.states.get("chords") != "done":
            return "skipped", "no sheet"
        stats = render_all(self.conn, self.cfg, self.overrides, runner=self.runner, now=self.now,
                           song_ids={self.song.id})
        if stats.font_error:
            return "failed", stats.font_error
        if stats.failed:
            return "failed", "chordpro couldn't make the PDF (see the log)"
        return "made" if stats.rendered else "up to date"

    def pages(self) -> str:
        from caracole.todo import write_pages

        write_pages(self.conn, self.cfg, self.overrides, self.now)
        return "_todo.md and index.html rewritten"

    # --- the whole run --------------------------------------------------------------------------------

    def find_song(self) -> str:
        """The song stage: the song, or ``_Stop`` and why it is refused."""
        raise NotImplementedError

    def _cleanup(self) -> None:
        """What the job leaves to undo once it is over, however it ended."""

    def _run(self, what: str) -> None:
        """The stages in order under caracole's lock, as asked for now (``what`` says which caracole holds it); each
        after the song's is the method of its name. ``_cleanup`` comes last, however the job ended."""
        from caracole import db
        from caracole.commands._common import exclusive
        from caracole.overrides import OverridesError, load_overrides
        from caracole.songs import ensure_current_keys

        self._report("song", "running")

        def waiting(holder: str) -> None:
            self.progress.stage("song", "running", f"waiting for the book ({holder})")

        try:
            with exclusive(self.cfg, what, interactive=True, on_wait=waiting):
                try:  # once the lock is held: what another caracole wrote while this one waited is read
                    self.overrides = load_overrides(self.cfg.overrides_file)
                except OverridesError as e:
                    self._refuse(f"Can't read overrides.toml: {e}")
                    return
                with closing(db.connect(self.cfg.db_path)) as conn:
                    self.conn = conn
                    ensure_current_keys(conn)
                    try:
                        self._report("song", "done", self.find_song())
                        for name, _ in self.STAGES[1:]:
                            self.stage(name, getattr(self, name))
                    except _Stop as e:  # refused, or the song left the book as this one let a lookup have the lock
                        self._refuse(str(e))
                        return
        finally:
            self._cleanup()
        self.result.seconds = self.clock() - self.started
