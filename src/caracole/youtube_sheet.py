"""A song's auto sheet from a YouTube video, now: ``caracole youtube --song --url --sheet``, which caracole
serve's sheet from a YouTube video runs (the library page's request form and a song's card).

The nightly run's youtube step and ``caracole autochords`` do this in bulk, a night apart; here it is one song
you chose the video of, in one process, under caracole's lock, its stages reported as a lookup reports its own
(get.py's ``Progress``: ``caracole youtube --sheet --progress`` writes a JSON line per event, which caracole
serve reads into the job's stages):

- ``song``: the song, found in the library or added to wanted.txt as ``caracole add`` adds it, then synced;
  refused when it is ignored, has a human sheet or has a purchase linked, and, without a video given, when
  ``[youtube]`` says "none" for it. The video given is written under ``[youtube]`` in overrides.toml, as
  ``caracole youtube --url`` writes it.
- ``audio``: the song's audio from YouTube, as the youtube step takes it (youtube_fetch.py), for this song
  alone: yt-dlp through ``make_youtube``, so its budget, its pauses, the lock and every term of the YouTube
  exception hold (youtube.py). Nothing is asked when the song has that video's audio already, nor while
  YouTube cools down after a block. A block starts (or extends) the cooldown and sends one ntfy alert.
- ``lyrics``: LRCLIB, for a song with none yet, at the bulk pace, asked with the audio's length when the
  song's line gives none, so the timed lyrics LRCLIB picks fit the audio (``fetch_pending_lyrics``'s
  ``durations``). A song whose lyrics came earlier keeps them.
- ``chords``: auto-chords for this song alone (``autochords_pending``'s ``only``), once the audio is the
  video's; a waiting lookup goes first (``_common.hand_over``), as the models take minutes. The chords go
  over the timed lyrics when their length fits the audio, else above the lyrics as a chart (merge.py).
- ``pdf``: the PDF and the viewer, ``sheet (auto).html``, for this song alone (``render_all``'s
  ``song_ids``): the sheet is readable from here on (``Progress.readable``).
- ``pages``: _todo.md and index.html.

A stage that can't go on skips those after it that need it, saying why. A block, a cooldown, a spent budget
or a site's error is a wait, never a failure, and the command exits 0, as every command does. What waiting
won't mend is ``SheetResult.failed``, and the command exits 1: a song refused, a video YouTube won't give
(a login, or given up after its downloads failed), audio auto-chords can't read, auto-chords that can't
run here, or a bug.

caracole get never runs yt-dlp: this is a command of its own, at the bulk pace, which the page starts as
it starts any other (web/jobs.py).
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from caracole.config import Config
from caracole.get import Progress, readable_files

log = logging.getLogger(__name__)

PROVIDER = "youtube"
STAGES = (
    ("song", "Find the song"),
    ("audio", "The audio from YouTube"),
    ("lyrics", "Lyrics from LRCLIB"),
    ("chords", "The chords, from the audio"),
    ("pdf", "The PDF"),
    ("pages", "The library page"),
)
# What the chords stage says the sheet holds, by the lyrics auto-chords laid the chords over
# (autochords/run.py's version ``raw["lyrics"]``), which caracole serve's Ready says.
HOLDS = {"synced": "chords over the lyrics", "plain": "chords, then the lyrics", "none": "chords only, no lyrics"}
NO_AUDIO = "no audio"


@dataclass(frozen=True)
class SheetRequest:
    """A song by name, and the video to take its audio from (``url``: a YouTube address; None, the one
    ``[youtube]`` names for it, else the one its search picks)."""

    artist: str
    title: str
    url: str | None = None

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


@dataclass
class SheetResult:
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
    """The song can't have a sheet from YouTube: said in the song stage, the others skipped."""


class _Sheet:
    def __init__(self, cfg: Config, request: SheetRequest, progress: Progress, *, runner: Callable,
                 recognizer: Any, beats_fn: Any, now: datetime | None, clock: Callable[[], float]):
        from caracole.commands._common import run_id_for, utcnow

        self.cfg, self.request, self.progress = cfg, request, progress
        self.runner, self.recognizer, self.beats_fn, self.clock = runner, recognizer, beats_fn, clock
        self.started = clock()
        self.now = (now or utcnow()).replace(microsecond=0)
        self.run_id = run_id_for(self.now)
        self.result = SheetResult(display=request.display)
        self.conn: Any = None
        self.overrides: Any = None
        self.song: Any = None

    # --- reporting --------------------------------------------------------------------------------

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
        from caracole.songs import get_song

        self.song = get_song(self.conn, self.song.id)

    # --- the stages -------------------------------------------------------------------------------

    def find_song(self) -> str:
        from caracole.normalize import identity_key
        from caracole.overrides import OverridesError, add_youtube, load_overrides
        from caracole.songs import HUMAN_SHEET, find_song
        from caracole.wanted import append_wanted, sync_wanted
        from caracole.youtube_fetch import youtube_audio
        from caracole.youtube_urls import watch_url

        req = self.request
        key = identity_key(req.artist, req.title)
        if key in self.overrides.ignore:
            raise _Stop(f"{req.display} is ignored in overrides.toml")
        song = find_song(self.conn, key)
        said = "in the library"
        if song is None:
            try:
                line = append_wanted(self.cfg.wanted_file, req.artist, req.title)
            except ValueError as e:  # a song the file can't hold, such as an artist with " - " in it
                raise _Stop(f"caracole can't add this song: {e}") from e
            except OSError as e:
                raise _Stop(f"wanted.txt can't be written: {e.strerror or e}") from e
            sync_wanted(self.conn, self.cfg.wanted_file, self.now)
            song = find_song(self.conn, line.identity)
            if song is None:
                raise _Stop(f"{req.display} is in wanted.txt, line {line.line_no}, but couldn't be synced")
            said = f"added to wanted.txt, line {line.line_no}"
        if song.status == "ignored":
            raise _Stop(f"{song.display} is ignored in overrides.toml")
        if self.conn.execute("SELECT 1 FROM files WHERE song_id = ? AND name = ?", (song.id, HUMAN_SHEET)).fetchone():
            raise _Stop(f"{song.display} already has a sheet")
        if song.audio_path and youtube_audio(self.conn, song) is None:
            raise _Stop(f"{song.display} has bought audio in Music/: auto-chords uses that")
        if req.url is None and song.key in self.overrides.youtube and self.overrides.youtube[song.key] is None:
            raise _Stop(f'[youtube] says "none" for {song.display}: give it a video')
        if req.url is not None:
            try:
                add_youtube(self.cfg.overrides_file, song.display, req.url)
                self.overrides = load_overrides(self.cfg.overrides_file)
            except OverridesError as e:
                raise _Stop(f"the video can't be recorded in overrides.toml: {e}") from e
            said += f"; recorded under [youtube]: {watch_url(self.overrides.youtube.get(song.key) or '')}"
        self.song = song
        self.result.song_id, self.result.display = song.id, song.display
        self.progress.song(song.id, song.display)
        return said

    def audio(self) -> tuple[str, str] | str:
        from caracole.commands._common import alert_block, make_youtube
        from caracole.health import answered_any, get_state, is_cooling, record_block, record_ok
        from caracole.http import ProviderBlocked
        from caracole.youtube_fetch import (
            DOWNLOADED_NOW,
            GAVE_UP,
            MISSED,
            PASSED_OVER,
            Record,
            youtube_audio,
            youtube_pass,
        )

        video = youtube_audio(self.conn, self.song)
        pasted = self.overrides.youtube.get(self.song.key)
        if video is not None and (not pasted or pasted == video.id):
            return "done", f"it has the audio of {video.url} already"
        if is_cooling(self.conn, PROVIDER, self.now):
            until = get_state(self.conn, PROVIDER).cooldown_until
            when = until.strftime("%Y-%m-%d %H:%M UTC") if until else "later"
            return "skipped", f"YouTube is paused after a block, until {when}"
        heard: list[tuple[str, Record]] = []
        runner = make_youtube(self.cfg, self.conn, self.run_id)
        try:
            stats = youtube_pass(self.conn, runner, self.cfg, self.now, overrides=self.overrides, songs=[self.song],
                                 on_song=lambda song, outcome, record: heard.append((outcome, record)))
        except ProviderBlocked as e:
            state = record_block(self.conn, PROVIDER, self.now, str(e))
            until = state.cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if state.cooldown_until else "later"
            message = (f"{e}\nNo more yt-dlp runs until {until} (block #{state.strikes}). Nothing was marked "
                       "missing.")
            alert_block(self.cfg, PROVIDER, message)
            return "skipped", f"YouTube blocked caracole; paused until {until}"
        finally:
            self.result.requests[PROVIDER] = runner.requests_made
            runner.close()
        if answered_any(self.conn, self.run_id, PROVIDER, runner.requests_made):
            record_ok(self.conn, PROVIDER, self.now)
        self._song_again()
        if stats.budget_exhausted or not heard:
            budget = self.cfg.provider(PROVIDER).budget
            return "skipped", f"YouTube's budget of {budget} runs is spent; try again later"
        outcome, record = heard[-1]
        got = record.video
        if outcome == DOWNLOADED_NOW and got is not None:
            named = f"{got.title} ({got.channel})" if got.channel else got.title or got.id
            return "done", f"downloaded {named}, {got.url}"
        if outcome == MISSED:
            return self._fail("no video fits; give it one")
        if outcome == PASSED_OVER:
            return self._fail("can't download this video; try another")
        if outcome == GAVE_UP:
            return self._fail("can't download this video; try another")
        return "failed", "download failed; try again later"

    def _audio_length(self) -> float | None:
        """The audio's length in seconds: as yt-dlp reported it, else as its file says."""
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

    def lyrics(self) -> tuple[str, str] | str:
        from caracole.commands._common import alert_block, make_client
        from caracole.health import answered_any, get_state, is_cooling, record_block, record_ok
        from caracole.http import ProviderBlocked
        from caracole.lyrics import fetch_pending_lyrics, song_lyrics

        if self.song.lyrics_status in ("found", "instrumental"):
            return "done", "already there"
        if is_cooling(self.conn, "lrclib", self.now):
            until = get_state(self.conn, "lrclib").cooldown_until
            when = until.strftime("%Y-%m-%d %H:%M UTC") if until else "later"
            return "skipped", f"no lyrics yet (LRCLIB paused until {when})"
        length = self._audio_length() if self.result.states.get("audio") == "done" else None
        client = make_client(self.cfg, self.conn, "lrclib", self.run_id)
        try:
            stats = fetch_pending_lyrics(self.conn, client, self.cfg.library_dir, self.now, only={self.song.id},
                                         durations={self.song.id: length} if length else None)
        except ProviderBlocked as e:
            state = record_block(self.conn, "lrclib", self.now, str(e))
            until = state.cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if state.cooldown_until else "later"
            alert_block(self.cfg, "lrclib", f"{e}\nNo more requests to it until {until} (block #{state.strikes}).")
            return "skipped", f"no lyrics yet (LRCLIB blocked caracole; paused until {until})"
        finally:
            self.result.requests["lrclib"] = client.requests_made
            client.close()
        if answered_any(self.conn, self.run_id, "lrclib", client.requests_made):
            record_ok(self.conn, "lrclib", self.now)
        self._song_again()
        if stats.budget_exhausted:
            return "skipped", "no lyrics yet (LRCLIB's budget spent); tonight's run tries again"
        if stats.failures:
            return "failed", "no lyrics yet (LRCLIB unavailable); tonight's run tries again"
        if stats.found:
            found = song_lyrics(self.song)
            return "done", "found, timed" if found is not None and found.synced else "found"
        if stats.instrumental:
            return "done", "an instrumental"
        if stats.missing:
            return "done", "LRCLIB has none"
        return "done", "not asked: LRCLIB answered for it lately"

    def chords(self) -> tuple[str, str] | str:
        from caracole.autochords.run import autochords_pending
        from caracole.commands._common import hand_over, handoffs, overrides_since
        from caracole.songs import AUTO_SHEET
        from caracole.versions import get_version

        if self.result.states.get("audio") != "done":
            return "skipped", NO_AUDIO
        handed = handoffs()
        hand_over(self.cfg, self.conn)  # the models take minutes: a waiting lookup goes first
        self.overrides = overrides_since(self.cfg, self.overrides, handed)
        self._song_again()
        stats = autochords_pending(self.conn, self.cfg, recognizer=self.recognizer, beats_fn=self.beats_fn,
                                   now=self.now, overrides=self.overrides, only={self.song.id})
        self._song_again()
        if stats.errors:
            return self._fail(f"auto-chords can't run here ({stats.errors[0]})")
        if stats.failures:
            return self._fail("auto-chords can't read the audio")
        kept = self.conn.execute(
            "SELECT version_id FROM files WHERE song_id = ? AND name = ?", (self.song.id, AUTO_SHEET)).fetchone()
        made = kept is not None and self.song.autochords_mtime == self.song.audio_mtime
        if not made:
            return self._fail("auto-chords made no sheet; see the log")
        used = get_version(self.conn, kept[0]).raw.get("lyrics")
        holds = HOLDS.get(str(used), "chords")
        return "done", holds if stats.generated else f"up to date: {holds}"

    def pdf(self) -> tuple[str, str] | str:
        from caracole.render import render_all

        if self.result.states.get("chords") != "done":
            return "skipped", "no sheet"
        stats = render_all(self.conn, self.cfg, self.overrides, runner=self.runner, now=self.now,
                           song_ids={self.song.id})
        if stats.font_error:
            return "failed", stats.font_error
        if stats.failed:
            return "failed", "chordpro couldn't make the PDF; the log says why"
        return "made" if stats.rendered else "up to date"

    def pages(self) -> str:
        from caracole.todo import write_pages

        write_pages(self.conn, self.cfg, self.overrides, self.now)
        return "_todo.md and index.html rewritten"

    # --- the whole run --------------------------------------------------------------------------------

    def run(self) -> SheetResult:
        from caracole import db
        from caracole.commands._common import exclusive
        from caracole.overrides import OverridesError, load_overrides
        from caracole.songs import ensure_current_keys

        self._report("song", "running")
        try:
            self.overrides = load_overrides(self.cfg.overrides_file)
        except OverridesError as e:
            return self._refuse(f"overrides.toml can't be read: {e}")

        def waiting(holder: str) -> None:
            self.progress.stage("song", "running", f"waiting for another caracole ({holder})")

        with exclusive(self.cfg, f"youtube --sheet {self.request.display}", on_wait=waiting):
            with closing(db.connect(self.cfg.db_path)) as conn:
                self.conn = conn
                ensure_current_keys(conn)
                try:
                    self._report("song", "done", self.find_song())
                except _Stop as e:
                    return self._refuse(str(e))
                for name, work in (("audio", self.audio), ("lyrics", self.lyrics), ("chords", self.chords),
                                   ("pdf", self.pdf), ("pages", self.pages)):
                    self.stage(name, work)
        self.result.seconds = self.clock() - self.started
        return self.result

    def _refuse(self, why: str) -> SheetResult:
        self.result.refused = why
        self._report("song", "failed", why)
        for name, _ in STAGES[1:]:
            self._report(name, "skipped", "")
        self.result.seconds = self.clock() - self.started
        return self.result


def make_sheet(cfg: Config, request: SheetRequest, progress: Progress | None = None, *,
               runner: Callable = subprocess.run, recognizer: Any = None, beats_fn: Any = None,
               now: datetime | None = None, clock: Callable[[], float] = time.monotonic) -> SheetResult:
    """Make one song's auto sheet from a YouTube video now, stage by stage (see the module docstring),
    reporting to ``progress``.

    ``runner`` runs chordpro, and ``recognizer`` and ``beats_fn`` stand in for auto-chords' models (tests pass
    fakes; None builds the models from ``cfg``, as ``caracole autochords`` does); ``now`` is the run's time.
    The caller checks first that this caracole can make chords of the audio (``youtube_fetch.route_problem``).
    """
    return _Sheet(cfg, request, progress or Progress(), runner=runner, recognizer=recognizer, beats_fn=beats_fn,
                  now=now, clock=clock).run()
