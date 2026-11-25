"""A song's auto sheet from a YouTube video, now: ``caracole youtube --song --url --sheet``, which caracole
serve's sheet from a YouTube video runs (the library page's request form and a song's card).

The nightly run's youtube step and ``caracole autochords`` do this in bulk, a night apart; here it is one song
you chose the video of, in one process, under caracole's lock, its stages reported as a lookup reports its own
(get.py's ``Progress``: ``caracole youtube --sheet --progress`` writes a JSON line per event, which caracole
serve reads into the job's stages; staged.py's ``StagedRun`` is that reporting half):

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
  ``durations``). A song whose lyrics came earlier keeps them. Then Megalobiz, the same way, for the timed
  lyrics LRCLIB left the song without (megalobiz_fetch.py): they put each chord over its word. Then AZLyrics' plain
  ones, for a song still without any (azlyrics_fetch.py).
- ``vocals`` and ``words``: the song's words heard from the audio, transcribe_job.py's ``HearsWords`` stages (where
  someone sings, then Whisper over the mix, kept as the song's transcript, or nothing sung noted), only once every
  lyrics site was asked and missed (transcript.py ``why_not_offered``), where this caracole can transcribe
  (``youtube_fetch.transcribe_problem``) and ``[autochords] transcribe`` is on; else vocals skipped "not
  transcribed: why", and words "no vocals". A site's words or instrumental verdict is said first, whatever this
  caracole can do ("not transcribed: its lyrics are found"); only otherwise the setting off, or "not transcribed here:
  why" for this caracole's reason, then the offer's other reasons. A waiting lookup goes first before each, the song
  checked still one for YouTube and still offered after it. Their failing here (the separator, the GPU, Whisper's
  model, audio Whisper can't load) fails their stage alone, never the sheet (``WORDS_FAIL_THE_JOB``), and files
  nothing against the song: the chords are made chords-only by auto-chords' own reader, and the song stays offered
  Transcribe the lyrics.
- ``chords``: auto-chords for this song alone (``autochords_pending``'s ``only``), once the audio is the
  video's; a waiting lookup goes first (``_common.hand_over``), as the models take minutes. The chords go
  over the timed lyrics when their length fits the audio, else above the lyrics as a chart (merge.py), over the
  transcript where the words were heard, else alone. A song
  that left the book meanwhile (another caracole removed it, or merged it into a song of the same name), or is no
  longer one for YouTube (a human sheet kept, ignored, bought audio), or whose audio changed after its vocals were
  separated, ends the sheet there, before the models write anything: a refusal its song stage says, the stages left
  skipped.
- ``pdf``: the PDF and the viewer, ``sheet (auto).html``, for this song alone (``render_all``'s
  ``song_ids``): the sheet is readable from here on (``Progress.readable``).
- ``pages``: _todo.md and index.html.

While the audio, the vocals, the words and the chords run, each says what it does (staged.py ``_doing``), which the
song's line shows: the video downloaded or searched for, demucs-rs's minutes, how far Whisper has heard the mix, then
auto-chords' steps.

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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from caracole.autochords.hearing import Hearing, sweep
from caracole.config import Config
from caracole.get import Progress
from caracole.staged import StagedResult, StagedRun, _Stop
from caracole.transcribe_job import HearsWords

log = logging.getLogger(__name__)

PROVIDER = "youtube"
STAGES = (
    ("song", "Find the song"),
    ("audio", "Audio from YouTube"),
    ("lyrics", "Lyrics"),
    ("vocals", "Where the singing is"),
    ("words", "Transcribing the lyrics"),
    ("chords", "Chords from the audio"),
    ("pdf", "PDF"),
    ("pages", "The logbook page"),
)
TURNED_OFF = "not transcribed: turned off ([autochords] transcribe = false)"  # the vocals' skip, so set
SITES_ANSWERED = ("found", "instrumental")  # a song's lyrics status once a site gave words or its verdict
# What the chords stage says the sheet holds, by the lyrics auto-chords laid the chords over
# (autochords/run.py's version ``raw["lyrics"]``), which caracole serve's Ready says.
HOLDS = {
    "synced": "chords over the lyrics",
    "plain": "chords, then the lyrics",
    "none": "chords only, no lyrics",
    "silent": "chords only: nothing sung was heard",  # ``raw["heard_nothing"]``
    "transcript": "chords over the transcribed lyrics",  # synced, over Whisper's words (``raw["lyrics_source"]``)
}


def holds(raw: dict[str, object]) -> str:
    """What the auto sheet's version (its ``raw``) says the sheet holds."""
    if raw.get("lyrics_source") == "transcript":
        used = "transcript"
    elif raw.get("heard_nothing") and raw.get("lyrics") == "none":
        used = "silent"
    else:
        used = str(raw.get("lyrics"))
    return HOLDS.get(used, "chords")
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
class SheetResult(StagedResult):
    """What came of a sheet from a YouTube video: its stages' ends, its files once readable, the requests it sent."""


class _Sheet(HearsWords, StagedRun):
    STAGES = STAGES

    def __init__(self, cfg: Config, request: SheetRequest, progress: Progress, *, runner: Callable,
                 recognizer: Any, beats_fn: Any, separator: Any, transcriber: Any, hears: bool | None,
                 now: datetime | None, clock: Callable[[], float]):
        super().__init__(cfg, progress, SheetResult(display=request.display), runner=runner, recognizer=recognizer,
                         beats_fn=beats_fn, now=now, clock=clock)
        self.request = request
        self.hearing = Hearing(cfg, separator=separator, transcriber=transcriber)
        self.hears = hears  # None: as [autochords] transcribe and this caracole say (``_why_not_heard``)

    # --- whether its words are heard ----------------------------------------------------------------------

    def _why_not_heard(self) -> str | None:
        """Before the vocals: why the song's words aren't heard, or None to hear them. Not without the video's audio;
        not for a song a lyrics site gave words or its instrumental verdict, said first in the offer's words, whatever
        this caracole can do (a site's lyrics on a caracole that can't transcribe are no fault of its); not with
        ``[autochords] transcribe`` off, nor where this caracole can't transcribe (``hears`` True passes over both,
        False is off); and not unless every lyrics site was asked and missed, the lyrics stage's answer
        (``why_not_offered``)."""
        from caracole.youtube_fetch import transcribe_reason

        if self.result.states.get("audio") != "done":
            return NO_AUDIO
        if self.song.lyrics_status in SITES_ANSWERED:
            return self._not_offered()  # "not transcribed: its lyrics are found"
        if self.hears is False or (self.hears is None and not self.cfg.autochords.transcribe):
            return TURNED_OFF
        if self.hears is None and (reason := transcribe_reason(self.cfg)) is not None:
            return f"not transcribed here: {reason}"
        return self._not_offered()

    def _still_to_hear(self) -> str | None:
        """After a lookup went first: the song still one for YouTube, else the sheet ends there (``_Stop``); and
        still offered a transcription (a lookup may have found its lyrics meanwhile, which the chords then go over),
        else why not."""
        self._still_for_youtube(self.song)
        return self._not_offered()

    def _not_offered(self) -> str | None:
        from caracole.autochords.transcript import why_not_offered

        why = why_not_offered(self.conn, self.cfg, self.song, self.overrides)
        return None if why is None else f"not transcribed: {why}"

    # --- the stages -------------------------------------------------------------------------------

    def find_song(self) -> str:
        from caracole.normalize import identity_key
        from caracole.overrides import OverridesError, add_youtube, load_overrides
        from caracole.songs import find_song
        from caracole.wanted import append_wanted, sync_wanted
        from caracole.youtube_urls import watch_url

        sweep(self.cfg.cache_dir)  # the stems a killed job left under the cache, as a transcription sweeps them
        req = self.request
        key = identity_key(req.artist, req.title)
        if key in self.overrides.ignore:
            raise _Stop(f"{req.display} is ignored (overrides.toml)")
        song = find_song(self.conn, key)
        said = "in the book"
        if song is None:
            try:
                line = append_wanted(self.cfg.wanted_file, req.artist, req.title)
            except ValueError as e:  # a song the file can't hold, such as an artist with " - " in it
                raise _Stop(f"Can't add this song: {e}") from e
            except OSError as e:
                raise _Stop(f"Couldn't write wanted.txt: {e.strerror or e}") from e
            sync_wanted(self.conn, self.cfg.wanted_file, self.now)
            song = find_song(self.conn, line.identity)
            if song is None:
                raise _Stop(f"{req.display} is in wanted.txt, line {line.line_no}, but didn't reach the book")
            said = f"added to wanted.txt, line {line.line_no}"
        self._still_for_youtube(song)
        if req.url is None and song.key in self.overrides.youtube and self.overrides.youtube[song.key] is None:
            raise _Stop(f'[youtube] says "none" for {song.display}: give it a video')
        if req.url is not None:
            try:
                add_youtube(self.cfg.overrides_file, song.display, req.url)
                self.overrides = load_overrides(self.cfg.overrides_file)
            except OverridesError as e:
                raise _Stop(f"couldn't note the video in overrides.toml: {e}") from e
            said += f"; noted under [youtube]: {watch_url(self.overrides.youtube.get(song.key) or '')}"
        self.song = song
        self.result.song_id, self.result.display = song.id, song.display
        self.progress.song(song.id, song.display)
        return said

    def _still_for_youtube(self, song: Any) -> None:
        """The song still one whose auto sheet comes from YouTube, else the sheet ends there (``_Stop``): not ignored,
        with no human sheet and no bought audio; as it is found, and again before its models, as a lookup that went
        first may have kept UG's chords meanwhile (auto-chords would skip it: no failure of the sheet's)."""
        from caracole.songs import HUMAN_SHEET
        from caracole.youtube_fetch import youtube_audio

        if song.status == "ignored" or song.key in self.overrides.ignore:
            raise _Stop(f"{song.display} is ignored (overrides.toml)")
        if self.conn.execute("SELECT 1 FROM files WHERE song_id = ? AND name = ?", (song.id, HUMAN_SHEET)).fetchone():
            raise _Stop(f"{song.display} already has a sheet")
        if song.audio_path and youtube_audio(self.conn, song) is None:
            raise _Stop(f"{song.display} has bought audio in Music/; auto-chords uses that")

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
            return "done", f"has the audio of {video.url} already"
        if is_cooling(self.conn, PROVIDER, self.now):
            until = get_state(self.conn, PROVIDER).cooldown_until
            when = until.strftime("%Y-%m-%d %H:%M UTC") if until else "later"
            return "skipped", f"waiting out YouTube until {when}"
        downloading = "downloading the video's audio"
        self._doing("audio", downloading if pasted else "looking for a video on YouTube")
        heard: list[tuple[str, Record]] = []
        runner = make_youtube(self.cfg, self.conn, self.run_id)
        try:
            stats = youtube_pass(self.conn, runner, self.cfg, self.now, overrides=self.overrides, songs=[self.song],
                                 on_song=lambda song, outcome, record: heard.append((outcome, record)),
                                 on_download=lambda song, video: self._doing("audio", downloading))
        except ProviderBlocked as e:
            state = record_block(self.conn, PROVIDER, self.now, str(e))
            until = state.cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if state.cooldown_until else "later"
            message = (f"{e}\nNo more yt-dlp runs until {until} (block #{state.strikes}). Nothing was marked "
                       "missing.")
            alert_block(self.cfg, PROVIDER, message, strikes=state.strikes)
            return "skipped", f"YouTube turned us back; waiting until {until}"
        finally:
            self.result.requests[PROVIDER] = runner.requests_made
            runner.close()
        if answered_any(self.conn, self.run_id, PROVIDER, runner.requests_made):
            record_ok(self.conn, PROVIDER, self.now)
        self._song_again()
        if stats.budget_exhausted or not heard:
            budget = self.cfg.provider(PROVIDER).budget
            return "skipped", f"no YouTube runs left ({budget} spent); try again later"
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

    def lyrics(self) -> tuple[str, str]:
        """LRCLIB's lyrics, then Megalobiz's timed ones where LRCLIB left the song without (megalobiz_fetch.py):
        timed lyrics put each chord over its word. Then AZLyrics' plain ones where it still has none."""
        if self.song.lyrics_status == "instrumental":
            return "done", "already there"
        length = self._audio_length() if self.result.states.get("audio") == "done" else None
        lrclib = ("done", "already there") if self.song.lyrics_status == "found" else self._lrclib(length)
        return self._then(self._then(lrclib, self._megalobiz(length)), self._azlyrics())

    def _then(self, before: tuple[str, str], then: tuple[str, str] | None) -> tuple[str, str]:
        """What the stage says once one more site was asked after those before it (None: there was nothing to ask it)."""
        if then is None:
            return before
        self._song_again()
        if self.song.lyrics_status == "pending":  # none answered: the lyrics wait, as the last one to fail says
            return before if then[0] == "done" else then
        if before[0] != "done":  # the ones before failed, this one found them
            return then
        return "done", f"{before[1]}; {then[1]}"

    def _asked(self, provider: str, name: str, ask: Callable[[Any], Any], *, gap: str) -> Any:
        """One lyrics site asked about the song, at the bulk pace as LRCLIB is here: its stats, or the stage's
        (state, words) when it blocked, failed or its budget went; ``gap``, what the song still lacks then."""
        from caracole.commands._common import alert_block, make_client
        from caracole.health import answered_any, record_block, record_error, record_ok
        from caracole.http import BudgetExhausted, ProviderBlocked

        client = make_client(self.cfg, self.conn, provider, self.run_id)
        try:
            stats = ask(client)
        except ProviderBlocked as e:
            state = record_block(self.conn, provider, self.now, str(e))
            until = state.cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if state.cooldown_until else "later"
            alert_block(self.cfg, provider, f"{e}\nNo more requests to it until {until} (block #{state.strikes}).", strikes=state.strikes)
            return "skipped", f"{name} turned us back; waiting until {until}"
        except BudgetExhausted:
            return "skipped", f"no asks of {name} left; tonight's run asks"
        finally:
            self.result.requests[provider] = client.requests_made
            client.close()
        if answered_any(self.conn, self.run_id, provider, client.requests_made):
            record_ok(self.conn, provider, self.now)
        if stats.failures:
            record_error(self.conn, provider, self.now, str(stats.failures[0][1]))
            return "failed", f"no {gap} yet ({name} unavailable); tried again tonight"
        if stats.budget_exhausted:
            return "skipped", f"no asks of {name} left; tonight's run asks"
        return stats

    def _megalobiz(self, length: float | None) -> tuple[str, str] | None:
        """Megalobiz asked about the song; None when there is nothing to ask it (lyrics timed already, Megalobiz turned
        off or cooling down)."""
        from caracole.health import is_cooling
        from caracole.megalobiz_fetch import megalobiz_lyrics, songs_to_ask

        self._song_again()
        if (not self.cfg.provider("megalobiz").enabled or is_cooling(self.conn, "megalobiz", self.now)
                or not songs_to_ask(self.conn, self.now, only={self.song.id})):
            return None
        stats = self._asked("megalobiz", "Megalobiz", lambda client: megalobiz_lyrics(
            self.conn, client, self.cfg.library_dir, self.now, only={self.song.id},
            durations={self.song.id: length} if length else None), gap="timed lyrics")
        if isinstance(stats, tuple):
            return stats
        if stats.found:
            return "done", "found on Megalobiz, timed"
        if stats.timed:
            return "done", "timed from Megalobiz"
        return "done", "nor has Megalobiz" if self.song.lyrics_status == "missing" else "Megalobiz has no timed ones"

    def _azlyrics(self) -> tuple[str, str] | None:
        """AZLyrics asked about the song; None when there is nothing to ask it (lyrics there already, AZLyrics turned
        off or cooling down)."""
        from caracole.azlyrics_fetch import azlyrics_lyrics, songs_to_ask
        from caracole.health import is_cooling

        self._song_again()
        picks = self.overrides.azlyrics
        if (not self.cfg.provider("azlyrics").enabled or is_cooling(self.conn, "azlyrics", self.now)
                or not songs_to_ask(self.conn, self.now, picks=picks, only={self.song.id})):
            return None
        stats = self._asked("azlyrics", "AZLyrics", lambda client: azlyrics_lyrics(
            self.conn, client, self.cfg.library_dir, self.now, picks=picks, only={self.song.id}), gap="lyrics")
        if isinstance(stats, tuple):
            return stats
        return "done", "found on AZLyrics" if stats.found else "nor has AZLyrics"

    def _lrclib(self, length: float | None) -> tuple[str, str]:
        from caracole.commands._common import alert_block, make_client
        from caracole.health import answered_any, get_state, is_cooling, record_block, record_ok
        from caracole.http import ProviderBlocked
        from caracole.lyrics import fetch_pending_lyrics, song_lyrics

        if is_cooling(self.conn, "lrclib", self.now):
            until = get_state(self.conn, "lrclib").cooldown_until
            when = until.strftime("%Y-%m-%d %H:%M UTC") if until else "later"
            return "skipped", f"no lyrics yet (waiting out LRCLIB until {when})"
        client = make_client(self.cfg, self.conn, "lrclib", self.run_id)
        try:
            stats = fetch_pending_lyrics(self.conn, client, self.cfg.library_dir, self.now, only={self.song.id},
                                         durations={self.song.id: length} if length else None)
        except ProviderBlocked as e:
            state = record_block(self.conn, "lrclib", self.now, str(e))
            until = state.cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if state.cooldown_until else "later"
            alert_block(self.cfg, "lrclib", f"{e}\nNo more requests to it until {until} (block #{state.strikes}).", strikes=state.strikes)
            return "skipped", f"no lyrics yet (LRCLIB turned us back; waiting until {until})"
        finally:
            self.result.requests["lrclib"] = client.requests_made
            client.close()
        if answered_any(self.conn, self.run_id, "lrclib", client.requests_made):
            record_ok(self.conn, "lrclib", self.now)
        self._song_again()
        if stats.budget_exhausted:
            return "skipped", "no lyrics yet (no LRCLIB asks left); tried again tonight"
        if stats.failures:
            return "failed", "no lyrics yet (LRCLIB unavailable); tried again tonight"
        if stats.found:
            found = song_lyrics(self.song)
            return "done", "found, timed" if found is not None and found.synced else "found"
        if stats.instrumental:
            return "done", "an instrumental"
        if stats.missing:
            return "done", "LRCLIB has none"
        return "done", "not asked: LRCLIB answered for it lately"

    def chords(self) -> tuple[str, str] | str:
        if self.result.states.get("audio") != "done":
            return "skipped", NO_AUDIO
        self._after_a_lookup()  # the models take minutes: a waiting lookup goes first
        self._still_for_youtube(self.song)
        if self.voiced is not None:  # its words were heard of this audio
            self._same_audio()
        return self._autochords_sheet()

    def run(self) -> SheetResult:
        self._run(f"youtube --sheet {self.request.display}")
        return self.result


def make_sheet(cfg: Config, request: SheetRequest, progress: Progress | None = None, *,
               runner: Callable = subprocess.run, recognizer: Any = None, beats_fn: Any = None,
               separator: Any = None, transcriber: Any = None, hears: bool | None = None,
               now: datetime | None = None, clock: Callable[[], float] = time.monotonic) -> SheetResult:
    """Make one song's auto sheet from a YouTube video now, stage by stage (see the module docstring),
    reporting to ``progress``.

    ``runner`` runs chordpro, ``recognizer`` and ``beats_fn`` stand in for auto-chords' models, ``separator`` and
    ``transcriber`` for demucs-rs and Whisper (tests pass fakes; None builds each model from ``cfg``, as ``caracole
    autochords`` and ``caracole transcribe`` do); ``hears``, whether the words are heard where no lyrics site has
    them: None as ``[autochords] transcribe`` and ``youtube_fetch.transcribe_problem`` say, True whatever they say
    (tests, with the fakes), False never. ``now`` is the run's time. The caller checks first that this caracole can
    make chords of the audio (``youtube_fetch.route_problem``).
    """
    return _Sheet(cfg, request, progress or Progress(), runner=runner, recognizer=recognizer, beats_fn=beats_fn,
                  separator=separator, transcriber=transcriber, hears=hears, now=now, clock=clock).run()
