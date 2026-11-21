"""A YouTube song's lyrics transcribed from its audio, then its auto sheet made again over them: ``caracole
transcribe --song``.

For a song whose audio came from YouTube and that every lyrics site switched on missed (transcript.py
``why_not_offered``), in one process, under caracole's lock as asked for now, its stages reported as a lookup reports
its own (staged.py; ``--progress`` writes a JSON line per event, which caracole serve reads into the job's stages):

- ``song``: the song, by its identity key, never added to wanted.txt; refused when it isn't offered a transcription.
- ``vocals``: where the singing is. The mix's loudness frame by frame (``separate.frame_db``), the vocals separated
  by demucs-rs into a temporary folder under the cache, their loudness, then the sung spans (words.py
  ``sung_spans``).
- ``words``: Whisper large-v3 over the full mix, the language heard on the stem's first 30 s of singing; the words
  outside every sung span dropped (``guard``), the rest broken into lines and written as enhanced LRC, kept as the
  song's transcript (``keep_transcript``), never as its lyrics. Nothing kept, or no sung span to keep a word in
  (then Whisper isn't run): ``note_heard_nothing``, so the song is offered again only once its audio changes.
- ``chords``: auto-chords for this song alone (``autochords_pending``'s ``only``), which lays the chords over the
  transcript now.
- ``pdf``: the PDF and the viewer, for this song alone (``render_all``'s ``song_ids``).
- ``pages``: _todo.md and index.html.

Before each of vocals, words and chords, the long stages, a waiting lookup goes first (``_common.hand_over``); then
the song is read again, checked still offered before vocals and words, and its audio still the one vocals separated
before words and chords. A song that left the book, is offered no more or has other audio ends the job there, a
refusal its song stage says, before the next model runs.

The models default to demucs-rs and Whisper from ``cfg``, each built at its first stage and run first on run.py's
test tone, as auto-chords checks its own: a model that fails there would fail on every song.

What fails is told apart as auto-chords tells it:

- the setup's, which blames no song and records nothing, the song staying offered: the separator ("the separator
  can't run here (...)", demucs-rs's own words), a GPU missing, busy or out of memory, or a Whisper model that won't
  load (``SetupFailed``, in its own words: "the GPU failed: ...");
- the audio's: the mix that librosa or Whisper can't read ("can't read the audio"), filed as auto-chords files a
  file it can't read (run.py ``_unreadable``: kv ``autochords:failed:<song id>``), so the song is offered no
  transcription, nor auto-chords tried on it, until its audio changes;
- a bug: caracole's, said as such.

Beside the audio's, only "no singing heard" is recorded against the song (``note_heard_nothing``).

Each is ``TranscribeResult.failed`` (or ``bug``), and the command exits 1. The caller checks first that lyrics can
be transcribed here (``youtube_fetch.transcribe_problem``).
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from caracole.config import Config
from caracole.get import Progress
from caracole.logs import plural
from caracole.staged import StagedResult, StagedRun, _Stop

STAGES = (
    ("song", "Find the song"),
    ("vocals", "Where the singing is"),
    ("words", "Transcribing the lyrics"),
    ("chords", "Chords from the audio"),
    ("pdf", "PDF"),
    ("pages", "The logbook page"),
)
UNREADABLE = "can't read the audio"


@dataclass(frozen=True)
class TranscribeRequest:
    """A song of the library, by name."""

    artist: str
    title: str

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


@dataclass
class TranscribeResult(StagedResult):
    """What came of a transcription: its stages' ends, and the sheet's files once readable."""


class _Transcription(StagedRun):
    STAGES = STAGES
    MAKING = "its lyrics were transcribed"

    def __init__(self, cfg: Config, request: TranscribeRequest, progress: Progress, *, separator: Any,
                 transcriber: Any, recognizer: Any, beats_fn: Any, runner: Callable, now: datetime | None,
                 clock: Callable[[], float]):
        super().__init__(cfg, progress, TranscribeResult(display=request.display), runner=runner,
                         recognizer=recognizer, beats_fn=beats_fn, now=now, clock=clock)
        self.request = request
        self.separator, self.transcriber = separator, transcriber
        self.work: tempfile.TemporaryDirectory[str] | None = None  # the stem and the test tones, for the job
        self.audio: tuple[str | None, float | None] = (None, None)  # the audio separated: its path and mtime
        self.stem: Path | None = None
        self.spans: list[Any] = []

    def stage(self, name: str, run: Callable[[], tuple[str, str] | str]) -> None:
        """A stage, where a SetupFailed (the GPU, Whisper's model) ends it in its own words, as the setup's."""
        from caracole.autochords.transcribe import SetupFailed

        def guarded() -> tuple[str, str] | str:
            try:
                return run()
            except SetupFailed as e:
                return self._fail(str(e))

        super().stage(name, guarded)

    # --- between the stages ---------------------------------------------------------------------------------

    def _not_offered(self, why: str) -> _Stop:
        return _Stop(f"{self.song.display} isn't offered a transcription: {why}")

    def _still_offered(self) -> None:
        from caracole.autochords.transcript import why_not_offered

        why = why_not_offered(self.conn, self.cfg, self.song, self.overrides)
        if why is not None:
            raise self._not_offered(why)

    def _same_audio(self) -> None:
        """The song's audio still the one its vocals were separated from (another caracole may replace it while this
        one lets the lookups have the lock), else the job ends there, a refusal: the stem and the sung spans are no
        use to other audio, which is offered a transcription of its own."""
        if (self.song.audio_path, self.song.audio_mtime) != self.audio:
            raise _Stop(f"{self.song.display}: its audio changed while its lyrics were transcribed")

    def _folder(self, name: str) -> Path:
        """A folder of the job's own under the cache, gone with the job."""
        if self.work is None:
            self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
            self.work = tempfile.TemporaryDirectory(prefix="transcribe-", dir=self.cfg.cache_dir)
        return Path(self.work.name) / name

    def _unreadable(self, e: Exception) -> tuple[str, str]:
        """The audio's: filed as auto-chords files a file it can't read (run.py ``_unreadable``), so the song is
        offered no transcription, nor auto-chords tried on it, until its audio changes; the job fails."""
        from caracole.autochords.run import _unreadable as file_unreadable

        file_unreadable(self.conn, self.song, e, self.run_id)
        return self._fail(UNREADABLE)

    # --- the default models ----------------------------------------------------------------------------------

    def _the_separator(self) -> Any:
        """The separator given, else demucs-rs from ``cfg``, which must separate a test tone first."""
        if self.separator is None:
            from caracole.autochords.run import _test_tone
            from caracole.autochords.separate import DemucsSeparator, SeparatorFailed, frame_db

            separator = DemucsSeparator(self.cfg.demucs_bin, self.cfg.autochords.separator_model, self.cfg.cache_dir)
            work = self._folder("tone")
            problems = _test_tone([("demucs-rs", lambda tone: frame_db(separator.vocals(tone, work)))])
            if problems:
                raise SeparatorFailed(problems[0])
            self.separator = separator
        return self.separator

    def _the_transcriber(self) -> Any:
        """The transcriber given, else Whisper from ``cfg`` on the device it resolves to, which must hear a test
        tone first: a SetupFailed there says itself, any other failure is said as the tone's."""
        if self.transcriber is None:
            from caracole.autochords.run import _test_tone
            from caracole.autochords.transcribe import SetupFailed, WhisperTranscriber, resolve_device

            auto = self.cfg.autochords
            transcriber = WhisperTranscriber(auto.whisper_model, device=resolve_device(auto.transcribe_device),
                                             cache_dir=self.cfg.cache_dir)
            setup: list[SetupFailed] = []

            def hears(tone: Path) -> None:
                try:
                    transcriber.hear(tone, tone, 0.0)
                except SetupFailed as e:
                    setup.append(e)

            problems = _test_tone([("Whisper", hears)])
            if setup:
                raise setup[0]
            if problems:
                raise SetupFailed(problems[0])
            self.transcriber = transcriber
        return self.transcriber

    # --- the stages ----------------------------------------------------------------------------------------

    def find_song(self) -> str:
        from caracole.normalize import identity_key
        from caracole.songs import find_song

        req = self.request
        song = find_song(self.conn, identity_key(req.artist, req.title))
        if song is None:
            raise _Stop(f"{req.display} isn't in the book")
        self.song = song
        self._still_offered()
        self.result.song_id, self.result.display = song.id, song.display
        self.progress.song(song.id, song.display)
        return "in the book"

    def vocals(self) -> tuple[str, str] | str:
        from caracole.autochords import separate
        from caracole.autochords.words import sung_spans

        self._after_a_lookup()
        self._still_offered()
        try:
            separator = self._the_separator()
        except separate.SeparatorFailed as e:
            return self._fail(f"the separator can't run here ({e})")
        self.audio = (self.song.audio_path, self.song.audio_mtime)
        mix = Path(self.song.audio_path or "")
        try:
            mix_db = separate.frame_db(mix)
        except Exception as e:  # noqa: BLE001 - the audio's, as auto-chords tells it
            return self._unreadable(e)
        try:
            self.stem = separator.vocals(mix, self._folder("song"))
        except separate.SeparatorFailed as e:
            return self._fail(f"the separator can't run here ({e})")
        stem_db = separate.frame_db(self.stem)
        both = min(len(stem_db), len(mix_db))  # the stem, at demucs-rs's own rate, may come out a frame shorter
        self.spans = sung_spans(stem_db[:both], mix_db[:both])
        if not self.spans:
            return "done", "no singing found"
        return "done", f"sung from {self.spans[0].start:.1f} s, {plural(len(self.spans), 'stretch', 'stretches')}"

    def words(self) -> tuple[str, str] | str:
        from caracole.autochords.transcribe import SetupFailed
        from caracole.autochords.transcript import MODEL, Transcript, keep_transcript, note_heard_nothing
        from caracole.autochords.words import guard, lines_of, to_lrc

        if self.result.states.get("vocals") != "done" or self.stem is None:
            return "skipped", "no vocals"
        if not self.spans:  # the guard would drop every word Whisper heard: it isn't run
            note_heard_nothing(self.conn, self.song, self.run_id)
            return self._fail("no singing heard")
        self._after_a_lookup()
        self._same_audio()
        self._still_offered()
        transcriber = self._the_transcriber()
        mix = Path(self.song.audio_path or "")
        try:
            heard = transcriber.hear(mix, self.stem, self.spans[0].start)
        except SetupFailed:  # the GPU's, said by ``stage``
            raise
        except Exception as e:  # noqa: BLE001 - anything else Whisper raises is the audio's, as auto-chords tells it
            return self._unreadable(e)
        kept, dropped = guard(heard.words, self.spans)
        if not kept:
            note_heard_nothing(self.conn, self.song, self.run_id)
            return self._fail("no singing heard")
        lines = lines_of(kept)
        keep_transcript(self.conn, self.song, Transcript(
            lrc=to_lrc(lines), audio=self.song.audio_path or "", audio_mtime=self.song.audio_mtime, model=MODEL,
            language=heard.language, device=str(getattr(transcriber, "device", "unknown")),
            words_dropped=len(dropped), made_at=self.run_id))
        return "done", (f"{plural(len(kept), 'word')} in {plural(len(lines), 'line')} ({heard.language}), "
                        f"{len(dropped)} dropped")

    def chords(self) -> tuple[str, str] | str:
        if self.result.states.get("words") != "done":
            return "skipped", "no transcript"
        self._after_a_lookup()
        self._same_audio()
        return self._autochords_sheet()

    # --- the whole run --------------------------------------------------------------------------------

    def _cleanup(self) -> None:
        if self.work is not None:
            self.work.cleanup()

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
