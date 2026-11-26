"""A song's lyrics transcribed from its own audio, then its auto sheet made again over them: ``caracole
transcribe --song``.

For a song with audio of its own (YouTube's or a purchase's) that every lyrics site switched on missed (transcript.py
``why_not_offered``), in one process, under caracole's lock as asked for now, its stages reported as a lookup reports
its own (staged.py; ``--progress`` writes a JSON line per event, which caracole serve reads into the job's stages):

- ``song``: the song, by its identity key, never added to wanted.txt; refused when it isn't offered a transcription.
  ``force`` (``--force``, the card's Transcribe anyway: the owner's "it is sung") offers it whatever caracole heard or
  was told of it (``why_not_offered``'s ``anyway``: nothing sung, by caracole's verdict or the owner's word, and audio
  Whisper couldn't load), and hears it so (hearing.py's ``anyway``: neither rule of nothing sung, Whisper over the
  whole song with no span). ``none`` (``--none``, the card's Not sung: chords only) is for a song with a transcript of
  its own audio kept (``why_not_unsung``), refused otherwise.
  First, the work folders a killed job left under the cache are swept (hearing.py ``sweep``): those no live job
  holds. A song whose own audio has its transcript kept already, but no auto sheet over it (the chords stage failed
  or was cut off after the words kept it: Try again runs the same command), goes straight to the chords: vocals
  skipped and the words the transcript kept (``_sheet_to_make``), neither model run again.
- ``vocals``: where the singing is (skipped with ``none``, "you said nothing is sung"), autochords/hearing.py's
  ``Hearing.vocals``: the vocals separated by demucs-rs into a work folder under the cache, and the sung spans from
  their loudness against the mix's.
- ``words``: ``Hearing.words``: Whisper large-v3 over the full mix, the words outside every sung span dropped, the
  rest kept as the song's transcript (``keep_transcript``), never as its lyrics. Nothing sung, by words.py's rule (no
  sung span or under ``MIN_SUNG_S`` of them, and then Whisper isn't run; too few words kept, under ``MIN_WORDS`` or
  ``MIN_WORDS_A_MINUTE``), is noted with why (``note_heard_nothing``), so the song is offered again only once its
  audio changes, and the job fails "no singing heard". With ``none``, done "transcript dropped": the transcript gone
  and the song's audio noted not sung by the owner's word (``drop_transcript``), never heard again, at night or by a
  sheet from a video, until they ask for it (``force``) or a new file comes (a new file is a new start).
- ``chords``: auto-chords for this song alone (``autochords_pending``'s ``only``), which lays the chords over the
  transcript now (with ``none``, the chords alone: a sheet over a transcript gone is due, run.py ``_skip_reason``).
- ``pdf``: the PDF and the viewer, for this song alone (``render_all``'s ``song_ids``).
- ``pages``: _todo.md and index.html.

While each of the long stages runs, it says how far it is (staged.py ``_doing``), which the song's line shows: the
vocals how long demucs-rs has been at it against about how long it takes here, the words Whisper loading, then how far
it has heard the mix (hearing.py's ``on_doing``), the chords auto-chords' steps.

Before each of vocals, words and chords, the long stages, a waiting lookup goes first (``_common.hand_over``); then
the song is read again, checked still offered (before the chords, its transcript kept no refusal:
``_still_due_its_sheet``), and its audio still the one vocals separated before words and chords. A song that left the
book, is offered no more (a human sheet kept meanwhile, ignored, lyrics found) or has other audio ends the job there,
a refusal its song stage says, before the next model runs. Once the chords begin, the song's transcript is kept for
its audio, whatever comes of them (``TranscribeResult.transcript_kept``: a refusal or a failure there the command's
"Transcript kept; no sheet made").

The vocals and words stages are the ``HearsWords`` mixin's, a job's of stages over one song, on hearing.py's
``Hearing``, whose docstring says how the models are built and what fails: the setup's, which records nothing, the
song staying offered; the audio's, noted as Whisper's alone (``transcribe:unreadable:``); a bug, filing nothing.
Here each fails the job (``WORDS_FAIL_THE_JOB``), as nothing sung does: ``TranscribeResult.failed`` (or ``bug``),
and the command exits 1; audio Whisper can't load in words that say what to do (``WHISPER_UNREADABLE_DO``). The
caller checks first that lyrics can be transcribed here (``youtube_fetch.transcribe_problem``).
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from caracole.autochords.hearing import Hearing, HearingFailed, Nothing, Vocals, sweep
from caracole.config import Config
from caracole.get import Progress
from caracole.staged import StagedResult, StagedRun, _Stop

log = logging.getLogger(__name__)

STAGES = (
    ("song", "Find the song"),
    ("vocals", "Where the singing is"),
    ("words", "Transcribing the lyrics"),
    ("chords", "Chords from the audio"),
    ("pdf", "PDF"),
    ("pages", "The logbook page"),
)
NO_SINGING = "no singing heard"  # the words stage's failure when nothing is sung, in a job they fail


@dataclass(frozen=True)
class TranscribeRequest:
    """A song of the library, by name; ``force``, heard whatever caracole heard or was told of it; ``none``, said not
    sung: its transcript dropped and its chords made alone."""

    artist: str
    title: str
    force: bool = False
    none: bool = False

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


@dataclass
class TranscribeResult(StagedResult):
    """What came of a transcription: its stages' ends, and the sheet's files once readable; ``transcript_kept``, its
    chords begun with its own audio's transcript kept (heard now, or before), so that a refusal or a failure from there
    on leaves it kept (the command's "Transcript kept; no sheet made")."""

    transcript_kept: bool = False


class HearsWords:
    """The vocals and words stages of a ``StagedRun`` over one song, on its ``hearing`` (autochords/hearing.py), which
    goes with the job (``_cleanup``).

    Before each, a waiting lookup goes first, and the song is checked still the job's and still to hear
    (``_still_to_hear``); before the words, its audio still the one the vocals were separated from (``_same_audio``).
    The job says whether it hears the song at all (``_why_not_heard``), and whether its words not coming fail it
    (``WORDS_FAIL_THE_JOB``): the setup's failure, the audio's and nothing sung then fail the job (``_fail``, the
    command exits 1); else they end their stage alone, nothing sung done "nothing sung was heard (why)". Either way
    audio Whisper can't load is noted as Whisper's alone (hearing.py), never as audio auto-chords can't read: auto-
    chords' own reader gives its verdict as the chords are made. ``anyway``: heard whatever the spans (hearing.py's
    ``anyway``)."""

    WORDS_FAIL_THE_JOB = False
    anyway = False
    hearing: Hearing
    voiced: Vocals | None = None  # what the vocals stage heard
    separated: tuple[str | None, float | None] = (None, None)  # the audio the vocals were separated from: path, mtime

    def _why_not_heard(self) -> str | None:
        """Why the song's words aren't heard, the vocals stage's skip in its words, or None to hear them."""
        raise NotImplementedError

    def _still_to_hear(self) -> str | None:
        """After a lookup went first, before the vocals and the words: None for the song still one the job hears; why
        it isn't heard now, that stage's skip in its words; or the job ends there (``_Stop``)."""
        raise NotImplementedError

    def _same_audio(self) -> None:
        """The song's audio still the one its vocals were separated from (another caracole may replace it while this
        one lets the lookups have the lock), else the job ends there, a refusal: the stem and the sung spans are no
        use to other audio, which is offered a transcription of its own."""
        if (self.song.audio_path, self.song.audio_mtime) != self.separated:
            raise _Stop(f"{self.song.display}: its audio changed while its lyrics were transcribed")

    def _not_heard(self, failed: HearingFailed) -> tuple[str, str]:
        if not self.WORDS_FAIL_THE_JOB:
            return "failed", failed.words
        if failed.kind == "audio":
            from caracole.autochords.transcript import WHISPER_UNREADABLE_DO

            return self._fail(f"{failed.words}: {WHISPER_UNREADABLE_DO}")
        return self._fail(failed.words)

    def vocals(self) -> tuple[str, str] | str:
        why = self._why_not_heard()
        if why is not None:
            return "skipped", why
        self._after_a_lookup()
        if (why := self._still_to_hear()) is not None:
            return "skipped", why
        self.separated = (self.song.audio_path, self.song.audio_mtime)
        try:
            self.voiced = self.hearing.vocals(self.song, on_doing=lambda said: self._doing("vocals", said))
        except HearingFailed as e:
            return self._not_heard(e)
        return "done", self.voiced.said

    def words(self) -> tuple[str, str] | str:
        if self.result.states.get("vocals") != "done" or self.voiced is None:
            return "skipped", "no vocals"
        self._after_a_lookup()
        self._same_audio()
        if (why := self._still_to_hear()) is not None:
            return "skipped", why
        try:
            heard = self.hearing.words(self.conn, self.song, self.voiced, self.run_id,
                                       on_doing=lambda said: self._doing("words", said), anyway=self.anyway)
        except HearingFailed as e:
            return self._not_heard(e)
        if isinstance(heard, Nothing):
            if self.WORDS_FAIL_THE_JOB:
                return self._fail(NO_SINGING)
            return "done", f"nothing sung was heard ({heard.why})"
        return "done", heard.said

    def _cleanup(self) -> None:
        self.hearing.close()
        super()._cleanup()  # the StagedRun's after it


class _Transcription(HearsWords, StagedRun):
    STAGES = STAGES
    MAKING = "its lyrics were transcribed"
    WORDS_FAIL_THE_JOB = True

    def __init__(self, cfg: Config, request: TranscribeRequest, progress: Progress, *, separator: Any,
                 transcriber: Any, recognizer: Any, beats_fn: Any, runner: Callable, now: datetime | None,
                 clock: Callable[[], float]):
        super().__init__(cfg, progress, TranscribeResult(display=request.display), runner=runner,
                         recognizer=recognizer, beats_fn=beats_fn, now=now, clock=clock)
        self.request = request
        self.anyway = request.force
        self.hearing = Hearing(cfg, separator=separator, transcriber=transcriber)
        self.kept = False  # its transcript kept already, its sheet over it to make: the chords alone run

    # --- between the stages ---------------------------------------------------------------------------------

    def _song_again(self) -> None:
        """The song read again; one that left the book took its transcript with it (``transcript_kept`` no more)."""
        try:
            super()._song_again()
        except _Stop:
            self.result.transcript_kept = False
            raise

    def _not_offered(self, why: str) -> _Stop:
        from caracole.autochords.transcript import refused_for

        return _Stop(f"{self.song.display} isn't offered a transcription: {refused_for(why)}")

    def _still_offered(self) -> None:
        """The song still offered a transcription, else the job ends there (``_Stop``)."""
        from caracole.autochords.transcript import why_not_offered

        if self.request.none:
            self._still_unsung()
            return
        why = why_not_offered(self.conn, self.cfg, self.song, self.overrides, anyway=self.request.force)
        if why is not None:
            raise self._not_offered(why)

    def _still_unsung(self) -> None:
        """With ``none``, the song still one with a transcript to drop, else the job ends there (``_Stop``)."""
        from caracole.autochords.transcript import why_not_unsung

        why = why_not_unsung(self.conn, self.cfg, self.song, self.overrides)
        if why is not None:
            raise _Stop(f"{self.song.display} can't be said not sung: {why}")

    def _still_due_its_sheet(self) -> None:
        """Before the chords, the song still one a sheet over its transcript is made for: offered a transcription but
        for the one of its own audio kept, else the job ends there, a refusal that says the transcript is kept (a
        lookup that went first kept a human sheet, it was ignored, its lyrics came)."""
        from caracole.autochords.transcript import ALREADY_TRANSCRIBED, why_not_offered

        if self.request.none:
            from caracole.autochords.transcript import SAID_NOT_SUNG

            why = why_not_offered(self.conn, self.cfg, self.song, self.overrides)
            if why != SAID_NOT_SUNG:  # its word kept: ignored, a human sheet or lyrics since say otherwise
                raise _Stop(f"{self.song.display} needs no sheet of its chords alone now: {why}")
            return
        why = why_not_offered(self.conn, self.cfg, self.song, self.overrides, anyway=self.request.force)
        if why is not None and why != ALREADY_TRANSCRIBED:
            raise _Stop(f"{self.song.display} needs no sheet over its transcript now: {why}")

    def _sheet_to_make(self) -> bool:
        """Whether the song, offered no transcription for the one of its own audio kept already, has no auto sheet over
        it yet (auto-chords would make one: run.py ``_skip_reason``), so the job goes straight to its chords. A song
        record that can't be read ends the job, a refusal in its words, as auto-chords counts it an error (``_due``)."""
        from caracole.autochords.run import _skip_reason
        from caracole.autochords.transcript import ALREADY_TRANSCRIBED, why_not_offered

        if self.request.none or (why_not_offered(self.conn, self.cfg, self.song, self.overrides,
                                                 anyway=self.request.force) != ALREADY_TRANSCRIBED):
            return False
        try:
            return _skip_reason(self.conn, self.song, self.overrides) is None
        except Exception as e:  # noqa: BLE001 - a record another device wrote: the song's, never a bug's traceback
            log.error("%s: its auto sheet's record can't be read: %s: %s", self.song.display, type(e).__name__, e,
                      exc_info=not isinstance(e, (OSError, RuntimeError, ValueError)))
            raise _Stop(f"{self.song.display}: its auto sheet's record can't be read ({type(e).__name__}: "
                        f"{e})") from e

    def _why_not_heard(self) -> str | None:
        """Its own audio's transcript kept already, or the owner saying it isn't sung: neither model runs."""
        if self.request.none:
            return "you said nothing is sung"
        return "transcribed already" if self.kept else None

    def _still_to_hear(self) -> None:
        self._still_offered()  # offered no more ends the job: its transcription is all it does

    # --- the stages ----------------------------------------------------------------------------------------

    def find_song(self) -> str:
        from caracole.normalize import identity_key
        from caracole.songs import find_song

        sweep(self.cfg.cache_dir)
        req = self.request
        song = find_song(self.conn, identity_key(req.artist, req.title))
        if song is None:
            raise _Stop(f"{req.display} isn't in the book")
        self.song = song
        said = "in the book"
        if self.request.none:
            self._still_unsung()
            self.separated = (song.audio_path, song.audio_mtime)
        elif self._sheet_to_make():
            self.kept, self.separated = True, (song.audio_path, song.audio_mtime)
            said += "; transcribed already, its sheet to make"
        else:
            self._still_offered()
        self.result.song_id, self.result.display = song.id, song.display
        self.progress.song(song.id, song.display)
        return said

    def words(self) -> tuple[str, str] | str:
        if self.request.none:
            from caracole.autochords.transcript import drop_transcript

            self._same_audio()
            self._still_unsung()
            drop_transcript(self.conn, self.song, self.run_id)
            return "done", "transcript dropped"
        if self.kept:
            return "done", "the transcript kept"
        return super().words()

    def chords(self) -> tuple[str, str] | str:
        if self.result.states.get("words") != "done":
            return "skipped", "no transcript"
        self._after_a_lookup()
        self._same_audio()
        # Its transcript, for this audio, in the book: whatever comes of the chords, it stays (none with ``none``).
        self.result.transcript_kept = not self.request.none
        self._still_due_its_sheet()  # a human sheet kept meanwhile, ignored: auto-chords would skip it
        return self._autochords_sheet()

    # --- the whole run --------------------------------------------------------------------------------

    def run(self) -> TranscribeResult:
        self._run(f"transcribe {self.request.display}")
        return self.result


def make_transcript(cfg: Config, request: TranscribeRequest, progress: Progress | None = None, *,
                    separator: Any = None, transcriber: Any = None, recognizer: Any = None, beats_fn: Any = None,
                    runner: Callable = subprocess.run, now: datetime | None = None,
                    clock: Callable[[], float] = time.monotonic) -> TranscribeResult:
    """Transcribe one song's lyrics from its audio and make its auto sheet again over them, stage by stage (see the
    module docstring), reporting to ``progress``.

    ``separator`` (a ``separate.Separator``) and ``transcriber`` (a ``transcribe.Transcriber``) stand in for
    demucs-rs and Whisper, ``recognizer`` and ``beats_fn`` for auto-chords' models, ``runner`` for chordpro (tests
    pass fakes; None builds each model from ``cfg``); ``now`` is the run's time.
    """
    return _Transcription(cfg, request, progress or Progress(), separator=separator, transcriber=transcriber,
                          recognizer=recognizer, beats_fn=beats_fn, runner=runner, now=now, clock=clock).run()
