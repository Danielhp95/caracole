"""A song's words heard from its audio: the vocals separated, to find where someone sings, then Whisper over the mix,
its words kept where someone sings as the song's transcript, or nothing sung noted. The one place the separator and
Whisper run, for a job of stages over one song (transcribe_job.py's ``HearsWords``) or a pass over the library alike:
it knows nothing of a job's stages, only what it is at as it goes (``on_doing``).

- ``Hearing.vocals``: where the singing is. The mix's loudness frame by frame (``separate.frame_db``), the vocals
  separated by demucs-rs into the work folder, their loudness, then the sung spans (words.py ``sung_spans``), over as
  much of the song as both cover: a stem more than ``SHORT_STEM_FRAMES`` shorter than the mix is the separator's
  failure. One song's stem at a time: the next song's separation takes the last one's place.
- ``Hearing.words``: nothing sung, by words.py's rule, or the song's transcript. Under ``MIN_SUNG_S`` of spans
  (``too_little_sung``), Whisper isn't run: the guard would keep too few words to be lyrics. Else Whisper large-v3
  over the full mix, the language heard on the stem's first 30 s of singing; the words outside every sung span
  dropped (``guard``); under ``MIN_WORDS`` kept, or ``MIN_WORDS_A_MINUTE`` a minute of span (``too_few_words``),
  nothing is kept; else the words broken into lines and written as enhanced LRC, kept as the song's transcript
  (``keep_transcript``), never as its lyrics. Nothing sung is noted with why, by caracole (``note_heard_nothing``),
  so the song is offered again only once its audio changes. ``anyway``, the owner's "it is sung", skips both rules:
  Whisper runs whatever the spans, its words kept within them, or all of them with no span (the whole song one); only
  no word at all is nothing sung then.

Each model is built once a Hearing, at its first use, from ``cfg`` unless given: Whisper is run first on run.py's test
tone, as auto-chords checks its own, a model that fails there failing on every song; demucs-rs is not: a separator
that can't run fails on the song as it would on a tone, the setup's either way and filing nothing (the mix's loudness
has been read by then), and each of its runs costs about half a minute on the GPU, the tone's as much as the song's.

What fails is ``HearingFailed``, told apart as auto-chords tells it:

- ``"setup"``, which blames no song and records nothing, the song staying offered: the loudness reader failing on the
  mix, whatever it raises ("can't measure the audio here (...)", in its words: ``frame_db`` reads as BTC does,
  libsndfile, else FFmpeg for the AAC of YouTube's .m4a, so a failure there is no proof the audio is bad), the
  separator ("the separator can't run here (...)", demucs-rs's own words, or a stem it wrote that can't be read, by
  the loudness reader or by Whisper, which reads it first for the language), a GPU missing, busy or out of memory, or
  a Whisper model that won't load (``SetupFailed``, in its own words: "the GPU failed: ...", "Whisper's model won't
  load: ...");
- ``"audio"``: Whisper's own "Failed to load audio" on the mix (``transcribe.is_audio_error``, "Whisper can't read
  the audio"), noted as Whisper's alone (transcript.py ``note_whisper_cant_read``, kv ``transcribe:unreadable:<song
  id>``), so that no transcription is offered over that audio again, the card's nor the nightly pass's, until it
  changes or the owner asks for one by hand (``why_not_offered``'s ``anyway``). Never filed as audio auto-chords can't
  read: Whisper reads the mix through the ffmpeg program, auto-chords through its own reader, the one the vocals read
  the mix with already, which gives its own verdict as the chords are made.

``words`` refuses, before Whisper runs, vocals that aren't the Hearing's current stem of the song's audio as it is
(``_current``: another song's, of audio replaced since, or a stem the next song's separation removed): a caller's bug,
a ValueError in words of its own, never read as the separator's failure.

Anything else is a bug, caracole's or deep in Whisper, raised as it is and filing nothing against the song. Beside
Whisper's refusal of the audio, only nothing sung is recorded against the song.

The stems are in a work folder of the Hearing's own under the cache (``WORK_PREFIX``), its ``OWNER`` flocked while
the Hearing lives and gone with ``close``; ``sweep`` removes those a killed job left, no live one holds.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from caracole.config import Config
from caracole.logs import plural

if TYPE_CHECKING:
    from caracole.autochords.transcript import Transcript
    from caracole.autochords.words import Span
    from caracole.songs import Song

WHISPER_UNREADABLE = "Whisper can't read the audio"  # the audio's failure, in the words a job says it
WORK_PREFIX = "transcribe-"  # a Hearing's work folder under the cache, the stems in it
# A file in each work folder, flocked by the Hearing that made it for as long as it lives: a folder whose owner's lock
# anyone can take (its job killed: the kernel let go of it) is a killed job's, and swept.
OWNER = ".owner"
# demucs-rs writes the stem at its own rate: resampled, it may come out a frame or so shorter than the mix, read as
# far as both go. Shorter than this, the singing past its end would be lost: the separator's failure.
SHORT_STEM_FRAMES = 4  # 0.2 s

Doing = Callable[[str], None]  # told what a long step is at as it goes ("2 of ~12 min", "0:30 of 3:45")


class HearingFailed(Exception):
    """The song couldn't be heard: the setup's (``kind`` "setup", filing nothing) or the audio's ("audio", noted as
    Whisper's), in ``words``, the words a job says it in."""

    def __init__(self, kind: Literal["setup", "audio"], words: str):
        super().__init__(words)
        self.kind, self.words = kind, words


@dataclass(frozen=True)
class Vocals:
    """Where the song is sung: the ``audio`` separated (its path and mtime), the vocal ``stem``, the sung ``spans``,
    and the mix's ``length``, in seconds, as its loudness read it."""

    audio: tuple[str | None, float | None]
    stem: Path
    spans: list[Span]
    length: float

    @property
    def said(self) -> str:
        if not self.spans:
            return "no singing found"
        return f"sung from {self.spans[0].start:.1f} s, {plural(len(self.spans), 'stretch', 'stretches')}"


@dataclass(frozen=True)
class Kept:
    """The song's transcript, kept: of how many words, in how many lines, and how many were dropped."""

    transcript: Transcript
    words: int
    lines: int
    dropped: int

    @property
    def said(self) -> str:
        return (f"{plural(self.words, 'word')} in {plural(self.lines, 'line')} ({self.transcript.language}), "
                f"{self.dropped} dropped")


@dataclass(frozen=True)
class Nothing:
    """Nothing sung, noted: ``why``, words.py's ("sung 6.2 s", "5 words in 1:10 sung")."""

    why: str


class Hearing:
    """The separator and Whisper for a run, each built once at its first use (``separator`` and ``transcriber``
    stand in for demucs-rs and Whisper: tests pass fakes), and the work folder the stems go in, until ``close``."""

    def __init__(self, cfg: Config, *, separator: Any = None, transcriber: Any = None):
        self.cfg = cfg
        self.separator, self.transcriber = separator, transcriber
        self._work: tempfile.TemporaryDirectory[str] | None = None
        self._owner: int | None = None  # the descriptor of the work folder's OWNER, flocked while the Hearing lives

    def vocals(self, song: Song, *, on_doing: Doing) -> Vocals:
        """Where the song's audio is sung (the module docstring); ``HearingFailed`` the setup's."""
        from caracole.autochords import separate
        from caracole.autochords.words import FRAME_S, sung_spans
        from caracole.youtube_fetch import transcribes_on_the_gpu

        separator = self._the_separator()
        audio = (song.audio_path, song.audio_mtime)
        mix = Path(song.audio_path or "")
        try:
            mix_db = separate.frame_db(mix)
        except Exception as e:  # noqa: BLE001 - the reader's, whatever it is: no proof the audio is bad
            raise HearingFailed("setup", f"can't measure the audio here ({type(e).__name__}: {e})") from e
        length = len(mix_db) * FRAME_S
        takes = length * (separate.GPU_PACE if transcribes_on_the_gpu(self.cfg) else separate.CPU_PACE)
        on_doing(_separating(0.0, takes))
        try:
            stem = separator.vocals(mix, self._folder(song), on_tick=lambda ran: on_doing(_separating(ran, takes)))
        except separate.SeparatorFailed as e:
            raise HearingFailed("setup", f"the separator can't run here ({e})") from e
        try:
            stem_db = separate.frame_db(stem)
        except Exception as e:  # noqa: BLE001 - a stem the separator wrote and can't be read is the separator's
            raise HearingFailed("setup", f"the separator can't run here (its vocals can't be read: "
                                         f"{type(e).__name__}: {e})") from e
        short = len(mix_db) - len(stem_db)
        if short > SHORT_STEM_FRAMES:
            raise HearingFailed("setup", f"the separator can't run here (its vocals are "
                                         f"{round(short * FRAME_S, 2):g} s shorter than the song)")
        both = min(len(stem_db), len(mix_db))
        return Vocals(audio, stem, sung_spans(stem_db[:both], mix_db[:both]), length)

    def words(self, conn: sqlite3.Connection, song: Song, vocals: Vocals, stamp: str, *, on_doing: Doing,
              anyway: bool = False) -> Kept | Nothing:
        """The song's words heard where its ``vocals`` say it is sung, kept as its transcript made at ``stamp``, or
        nothing sung noted (the module docstring); ``HearingFailed`` the setup's or the audio's, the audio's noted as
        Whisper's against the song."""
        from caracole.autochords.transcribe import SetupFailed, is_audio_error
        from caracole.autochords.transcript import (
            MODEL,
            Transcript,
            keep_transcript,
            note_heard_nothing,
            note_whisper_cant_read,
        )
        from caracole.autochords.words import Span, guard, lines_of, to_lrc, too_few_words, too_little_sung

        def nothing(why: str) -> Nothing:
            note_heard_nothing(conn, song, stamp, why=why, by="caracole")
            return Nothing(why)

        self._current(song, vocals)
        if not anyway and (why := too_little_sung(vocals.spans)) is not None:
            return nothing(why)  # the guard would keep too few words to be lyrics: Whisper isn't run
        mix = Path(song.audio_path or "")
        try:
            transcriber = self._the_transcriber(on_doing)
            on_doing(_heard(0.0, vocals.length))
            heard = transcriber.hear(mix, vocals.stem, vocals.spans[0].start if vocals.spans else 0.0,
                                     on_progress=lambda done, whole: on_doing(_heard(done, whole)))
        except SetupFailed as e:
            raise HearingFailed("setup", str(e)) from e
        except RuntimeError as e:
            if not is_audio_error(e):
                raise  # a bug, deep in Whisper or in caracole: said as one, and nothing filed against the song
            from caracole.autochords.run import _short  # auto-chords' own reader says, as the chords are made

            note_whisper_cant_read(conn, song, stamp, _short(e, song.audio_path or ""))
            raise HearingFailed("audio", WHISPER_UNREADABLE) from e
        spans = vocals.spans or [Span(0.0, vocals.length)]  # no span (``anyway`` alone gets here): the whole song
        kept, dropped = guard(heard.words, spans)
        why = too_few_words(kept, spans)
        if why is not None and not (anyway and kept):
            return nothing(why)
        lines = lines_of(kept)
        transcript = Transcript(
            lrc=to_lrc(lines), audio=song.audio_path or "", audio_mtime=song.audio_mtime, model=MODEL,
            language=heard.language, device=str(getattr(transcriber, "device", "unknown")),
            words_dropped=len(dropped), made_at=stamp)
        keep_transcript(conn, song, transcript)
        return Kept(transcript, len(kept), len(lines), len(dropped))

    def _current(self, song: Song, vocals: Vocals) -> None:
        """``vocals`` this Hearing separated for ``song``'s audio as it is, their stem still there, else a caller's
        bug, refused in its own words (ValueError) before Whisper runs: one song's stem at a time, the next song's
        separation removing the last one's, a stem gone would read as the separator's failure."""
        if self._work is None or not vocals.stem.is_relative_to(Path(self._work.name) / str(song.id)):
            raise ValueError(f"the vocals given aren't {song.display}'s")
        if vocals.audio != (song.audio_path, song.audio_mtime):
            raise ValueError(f"the vocals of {song.display} were separated from other audio than its own now")
        if not vocals.stem.is_file():
            raise ValueError(f"the vocals of {song.display} are no longer its current stem: separate them again")

    def close(self) -> None:
        """The work folder gone, the stems with it, and its owner's lock let go."""
        if self._work is not None:
            self._work.cleanup()
            self._work = None
        if self._owner is not None:
            os.close(self._owner)
            self._owner = None

    # --- the default models ----------------------------------------------------------------------------------

    def _the_separator(self) -> Any:
        """The separator given, else demucs-rs from ``cfg``, with no test tone first (the module docstring)."""
        if self.separator is None:
            from caracole.autochords.separate import DemucsSeparator

            self.separator = DemucsSeparator(self.cfg.demucs_bin, self.cfg.autochords.separator_model,
                                             self.cfg.cache_dir)
        return self.separator

    def _the_transcriber(self, on_doing: Doing) -> Any:
        """The transcriber given, else Whisper from ``cfg`` on the device it resolves to, which must hear a test
        tone first: a SetupFailed there says itself, any other failure is said as the tone's."""
        if self.transcriber is None:
            from caracole.autochords.run import _test_tone
            from caracole.autochords.transcribe import SetupFailed, WhisperTranscriber, resolve_device

            on_doing("loading Whisper")
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

    # --- the work folder ---------------------------------------------------------------------------------

    def _folder(self, song: Song) -> Path:
        """The song's folder in the Hearing's own under the cache, its ``OWNER`` flocked while the Hearing lives, an
        earlier song's stem removed first. Made under caracole's lock, as ``sweep`` runs: no sweep sees the work
        folder before its owner's lock is taken."""
        if self._work is None:
            self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
            self._work = tempfile.TemporaryDirectory(prefix=WORK_PREFIX, dir=self.cfg.cache_dir)
            self._owner = os.open(Path(self._work.name) / OWNER, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
            fcntl.flock(self._owner, fcntl.LOCK_EX)
        work = Path(self._work.name)
        for earlier in work.iterdir():
            if earlier.is_dir() and not earlier.is_symlink():
                shutil.rmtree(earlier, ignore_errors=True)
        return work / str(song.id)


def sweep(cache_dir: Path) -> None:
    """The work folders a killed job left under the cache, its stem in each, removed: those no live Hearing holds
    (``_held``). Not every one there: another job may have one, as it lets the lookups have caracole's lock before its
    words, and a job asked for now may take the lock meanwhile."""
    if cache_dir.is_dir():
        for leftover in cache_dir.glob(f"{WORK_PREFIX}*"):
            if leftover.is_dir() and not leftover.is_symlink() and not _held(leftover):
                shutil.rmtree(leftover, ignore_errors=True)


def _held(folder: Path) -> bool:
    """Whether a live Hearing holds the work folder: its ``OWNER`` flocked. A folder with none (an older caracole's,
    or one a job was killed in as it made it) is held by none; one whose owner file can't be opened, kept."""
    try:
        fd = os.open(folder / OWNER, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def _separating(ran: float, takes: float) -> str:
    """What the vocals say while demucs-rs runs, the number first and nothing a step's name says already (a phone's
    bar has room for little more than "2 of ~12 min"): about how long it ``takes`` here, then how long it has run, in
    whole minutes, against that; once past it, how long it has run alone."""
    about = round(takes / 60)
    if ran < 60:
        return f"~{max(about, 1)} min"
    minutes = int(ran // 60)
    if minutes < about:
        return f"{minutes} of ~{about} min"
    return f"{minutes} min so far"


def _heard(done: float, whole: float | None) -> str:
    """What the words say while Whisper hears the mix, the number first: how far into it, of its length."""
    def clock(seconds: float) -> str:
        whole_s = int(seconds)
        return f"{whole_s // 60}:{whole_s % 60:02d}"

    return f"{clock(done)} of {clock(whole)}" if whole else f"{clock(done)} heard"
