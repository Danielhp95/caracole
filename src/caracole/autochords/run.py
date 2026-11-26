"""Auto-chords over the library: ``sheet (auto).txt`` for songs you bought (plan §4).

``autochords_pending`` is what the ``caracole-autochords`` unit runs, offline,
after the nightly run has linked new purchases (``music.scan_music``), or audio
it took from YouTube (``youtube_fetch.py``), which is linked the same way and
used the same way: such a sheet says which video its audio came from, on the
line after the song's name, and its version's URL is the video's. A song
with linked audio is due when:

- its audio file exists;
- it has no human sheet (no kept ``sheet.txt``);
- it is not ignored;
- its audio changed since its last auto sheet, or that sheet was made before
  the song's lyrics arrived, or over plain lyrics before its timed lyrics
  arrived (or beside other timed lyrics: its version's ``raw["synced_lyrics"]``,
  a hash of those it was made beside, isn't the song's now; an older caracole
  kept none), which can put each chord over its word, or by an older caracole
  over timed lyrics with a character not one column wide (Chinese, say), whose
  chords it wrote at their characters' indexes rather than their display
  columns (its version's ``raw`` has no ``columns``): once more, each, so timed
  lyrics that don't fit the audio make a plain sheet again once, never every
  night (plain lyrics that come after a sheet of none rarely get here: they need
  no model, and the next render puts them on it, sheet_lyrics.py);
- that file hasn't already failed;
- no other song keeps a ``sheet (auto).txt`` where its own would go (two songs
  whose names make one folder, ``library.SharedFolder``): such a song is skipped,
  with a warning, before any model runs, and waits.

For each song due, BTC recognizes the chords, beat_this finds the beats, and
``merge.build_sheet`` lays the chords out over LRCLIB's lyrics: the synced ones
when their duration matches the audio's within 2 s; when it doesn't (LRCLIB timed
them for another cut of the song: a video with a spoken intro, say), the synced
ones moved by the shift ``align.lyrics_offset`` finds from the chords and the
beats, word stamps and all, when it finds one clearly, which the sheet says on a
line after the song's name, after the video's for audio from YouTube (``Lyrics'
timing shifted 12.0 s later to fit this audio``), and the version's
``raw["lyrics_shift"]`` keeps; with each chord over the
word sung when it starts where they time each word (enhanced LRC); else the plain
ones, else none (a chord chart alone). The sheet is kept with a ``versions`` row
of provider ``auto``, and the song becomes found.

Two kinds of failure are told apart, because only one is the purchase's:

- **A file auto-chords can't read**, such as one that won't decode, fails that
  song alone. kv ``autochords:failed:<song id>`` keeps the file's path and
  mtime, so it isn't decoded again every night: the song is tried again once
  its file changes (a new download, a converted copy), and the record is
  dropped once the song's file changes or goes. A transcription that can't
  read the file files it the same way (transcribe_job.py), and transcript.py
  offers such a song no transcription.
- **A setup that can't work** blames no purchase: model files missing or
  unusable, models that fail on a generated test tone (a sandbox that stops
  them, a checkpoint that won't load), or a sheet that can't be kept in the
  library. The songs stay due, and ``caracole autochords`` exits 1.
- **A bug laying out the sheet**, once the models have heard the file (``_hear``),
  is caracole's, never the file's: that song stays due, and the run exits 1.

Before a song's chords, the words of a few songs no lyrics site has are heard
(``autochords_pending``'s ``hearing``), so that each sheet is made once, over them.

Each run is recorded in kv ``autochords:status`` for the to-do page:
``{"at", "generated", "skipped", "failed": [{"song", "error", "audio"}], "heard", "silent", "transcribe_problem"}``,
where ``failed`` lists every purchase whose current file can't be read, ``heard`` and ``silent`` count the songs
whose words were heard and those heard to have nothing sung, and ``transcribe_problem`` says why words a song
waited for weren't heard (None for none).
"""

from __future__ import annotations

import hashlib
import logging
import math
import sqlite3
import sys
import tempfile
import wave
from array import array
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from caracole.autochords.align import lyrics_offset, shifted_lrc
from caracole.autochords.beats import detect_beats
from caracole.autochords.btc import BTCRecognizer
from caracole.autochords.merge import (
    NO_CHORD,
    ChordSegment,
    LrcLine,
    build_sheet,
    parse_lrc,
    parse_lrc_words,
    youtube_credit,
)
from caracole.autochords.transcript import (
    LYRICS_SOURCE,
    NOTE,
    SILENT,
    UNREADABLE,
    Transcript,
    transcript_of,
    why_not_offered,
)
from caracole.autochords.transcript import heard_nothing as _heard_nothing
from caracole.chordpro import display_columns
from caracole.config import Config
from caracole.db import kv_delete, kv_get_json, kv_set_json
from caracole.keys import estimate_key
from caracole.library import SharedFolder, keep_file, keeper_of, kept_files, write_info
from caracole.lyrics import Lyrics, song_lyrics
from caracole.music import read_audio
from caracole.overrides import Overrides, load_overrides
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, get_song, list_songs, refresh_status, update_song
from caracole.versions import get_version, upsert_version
from caracole.youtube import Video
from caracole.youtube_fetch import transcribe_problem, youtube_audio

if TYPE_CHECKING:
    from caracole.autochords.hearing import Hearing

log = logging.getLogger(__name__)

PROVIDER = "auto"
MODEL = "btc_large_voca"
SYNC_TOLERANCE_S = 2.0  # LRCLIB's own tolerance when it matches a duration
STATUS_KEY = "autochords:status"  # kv: the last run, for the to-do page
COLUMNS = "display"  # what a sheet's chord lines count, in its version's raw: display columns (merge._on_words)
ERROR_CHARS = 300  # an error as the to-do page lists it: one line, if a long one
# What ``autochords_pending`` tells its ``on_step`` as each step starts: a song's chords, then, before them, its words
# where it hears them (``hearing``).
STEPS = ("setting up the models", "hearing the chords", "finding the beats", "writing the sheet",
         "separating the vocals", "hearing the words")
TONE_SECONDS = 2.0
TONE_HZ = (261.63, 329.63, 392.0)  # C major: C4, E4 and G4


class Recognizer(Protocol):
    """Timed chords from an audio file, like ``btc.BTCRecognizer``."""

    def recognize(self, audio_path: Path | str) -> list[ChordSegment]: ...


BeatsFn = Callable[[Path], tuple[Sequence[float], Sequence[float]]]


class ModelsUnavailable(Exception):
    """The models are not configured, not there or not working; each arg is one reason."""


@dataclass(frozen=True)
class Failure:
    """A purchase auto-chords couldn't read: the song, why (one short line), and the file."""

    song: str
    error: str
    audio: str


@dataclass
class AutoStats:
    """One run's outcome. Each song with linked audio counts once, in one of the three.

    ``failures`` are the purchases whose file can't be read, found this run or
    an earlier one (the file hasn't changed since); the to-do page lists them.
    ``errors`` are the setup's problems, which blame no purchase: the models
    couldn't run, or a sheet couldn't be kept. The songs they stopped count as
    failed and are tried again next run, and ``caracole autochords`` exits 1.

    ``heard`` and ``silent``: the songs whose words were heard this run, kept as their transcript, and those heard to
    have nothing sung. ``transcribe_problem``: why words a song waited for weren't heard, the setup's (the separator,
    the GPU, Whisper's model) or this machine's (``youtube_fetch.transcribe_problem``); no exit 1 on its account.
    """

    generated: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[Failure] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    heard: int = 0
    silent: int = 0
    transcribe_problem: str | None = None

    def summary(self) -> str:
        """One line for the journal or a notification: "1 generated, 4 skipped, 0 failed", then what was heard, or
        why nothing was, where anything was to hear ("; words heard for 1, nothing sung in 1")."""
        said = f"{self.generated} generated, {self.skipped} skipped, {self.failed} failed"
        if self.heard or self.silent:
            said += f"; words heard for {self.heard}, nothing sung in {self.silent}"
        if self.transcribe_problem is not None:
            said += f"; words not heard: {self.transcribe_problem}"
        return said


def _overrides_again(cfg: Config, overrides: Overrides) -> Overrides:
    """overrides.toml read again after a lookup had the lock; the one read before, if it can't be."""
    from caracole.overrides import OverridesError

    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError as e:
        log.info("overrides.toml couldn't be read again (%s); auto-chords goes on with what it read.", e)
        return overrides


def autochords_pending(
    conn: sqlite3.Connection,
    cfg: Config,
    *,
    recognizer: Recognizer | None = None,
    beats_fn: BeatsFn | None = None,
    now: datetime | None = None,
    overrides: Overrides | None = None,
    between: Callable[[], bool] | None = None,
    only: Collection[int] | None = None,
    on_step: Callable[[str], None] | None = None,
    hearing: Hearing | None = None,
    transcriptions: int = 0,
) -> AutoStats:
    """Generate the auto sheets that are due, keep them in the library, and record the run.

    ``recognizer`` defaults to a ``BTCRecognizer`` on ``cfg.autochords.btc_weights``,
    and ``beats_fn`` to ``detect_beats`` with ``cfg.autochords.beat_checkpoint``.
    They are set up once, when the first song turns out to be due, so a night
    with no new audio loads no model; the defaults must then read a test tone.
    ``overrides`` defaults to the file at ``cfg.overrides_file``; its
    ``[ignore]`` songs are skipped. The run is stamped with ``now``.

    ``between`` is called between two songs, in no transaction: the command
    hands caracole's lock to a waiting lookup there (``_common.hand_over``), as
    a song can take minutes. When it says it did, overrides.toml and each song
    after are read again, since the lookup may have changed them.

    ``only``: the ids of the songs to work on (``caracole autochords --song``, a sheet
    from a YouTube video); the others count nowhere, and the run's record keeps their
    failures as the last whole run left them.

    Before each song it works on, it logs which, and how many of those due it is
    ("Working out the chords of A - T (3 of 12)…"), a song taking minutes: the due
    counted as it starts, which a lookup let in between two songs may change.

    ``on_step`` is told each step as it starts, in a few words (``STEPS``): the models set
    up, then each song's chords, beats and sheet, for a job that says how it goes.

    ``hearing`` (autochords/hearing.py) hears the words of up to ``transcriptions`` songs a run, in turn, newest
    first, before their chords: a song with audio that ``transcript.why_not_offered`` offers them (every lyrics site
    asked and missed, in the nightly run's steps before this pass; not heard yet). Its vocals separated, a waiting
    lookup goes first (``between``), then, the song read again and still offered with the audio separated, its words,
    kept as its transcript or nothing sung noted, either making its sheet due (``_skip_reason``). A song past the cap
    gets its chords now and its words on a later run, its sheet then made again. The setup's failure (the separator,
    the GPU, Whisper's model) stops the hearing for the run, kept as ``transcribe_problem``, the chords going on;
    audio Whisper can't load (which the vocals read with auto-chords' own reader) is noted as Whisper's alone
    (transcript.py ``note_whisper_cant_read``), offered no words again until it changes, its chords made; a bug is
    one of the run's ``errors`` (exit 1), its chords made all the same. The cap counts the songs whose hearing
    started, one passed over after a lookup went first or stopped by a bug too: the separation's time was spent.
    With no ``hearing`` and a cap, a song offered its words says why this machine hears none
    (``youtube_fetch.transcribe_problem``: the nightly unit of the GPU build sees no GPU).
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if overrides is None:
        overrides = load_overrides(cfg.overrides_file)
    stats = AutoStats()
    told = on_step or (lambda said: None)
    models = _Models(cfg, recognizer, beats_fn)
    songs = [s for s in list_songs(conn) if only is None or s.id in only]
    hears = transcriptions if hearing is not None else 0
    due, worked = _count_due(conn, cfg, songs, overrides, hears), 0
    turns = _Turns(cfg, conn, overrides, between)
    listening = _Listening(hearing, transcriptions)
    for listed in turns.each(songs):
        song = listening.first(conn, cfg, listed, turns, stats, stamp, told)
        if song is None:  # left the book while a lookup went first, or a bug hearing it: counted as one
            continue
        overrides = turns.overrides
        failure = _known_failure(conn, song)  # first, so a failure goes when its file does
        if not song.audio_path or not _due(conn, cfg, song, overrides, failure, stats):
            continue
        loaded = models.load(stats, told)
        if loaded is None:  # the models can't run: the song stays due
            stats.failed += 1
            continue
        worked += 1
        due = max(due, worked)
        log.info("Working out the chords of %s%s…", song.display, f" ({worked} of {due})" if due > 1 else "")
        _generate(conn, cfg, song, loaded, stamp, stats, told)
    _record_run(conn, stats, stamp, only)
    return stats


def _songs_in_turn(conn: sqlite3.Connection, cfg: Config, songs: Iterable[Song], overrides: Overrides,
                   between: Callable[[], bool] | None) -> Iterator[tuple[Song, Overrides]]:
    """Each of ``songs`` in its turn, with overrides.toml as the run knows it then (``_Turns``)."""
    turns = _Turns(cfg, conn, overrides, between)
    for song in turns.each(songs):
        yield song, turns.overrides


@dataclass
class _Turns:
    """A pass's turns over its songs, and overrides.toml as it knows it now. ``between`` is called before each turn
    but the first, once the one before is over, and wherever the pass lets a lookup go first within one
    (``hand_over``), in no transaction; once it says it handed caracole's lock to a lookup, overrides.toml is read
    again, and so is each song after, as the lookup may have changed them: one merged into another meanwhile is
    passed over."""

    cfg: Config
    conn: sqlite3.Connection
    overrides: Overrides
    between: Callable[[], bool] | None
    handed: bool = False

    def hand_over(self) -> bool:
        """A waiting lookup let go first; whether one was, overrides.toml then read again."""
        if self.between is None or not self.between():
            return False
        self.handed = True
        self.overrides = _overrides_again(self.cfg, self.overrides)
        return True

    def each(self, songs: Iterable[Song]) -> Iterator[Song]:
        for n, listed in enumerate(songs):
            if n:
                self.hand_over()
            song = listed
            if self.handed:
                try:
                    song = get_song(self.conn, listed.id)
                except KeyError:  # merged into another song meanwhile
                    continue
            yield song


@dataclass
class _Listening:
    """A run's hearing of words: ``hearing``, up to ``cap`` songs (``tried`` so far), ``stopped`` once its setup
    failed; with no ``hearing``, why this machine hears none said once a song is offered its words (``asked``)."""

    hearing: Hearing | None
    cap: int
    tried: int = 0
    stopped: bool = False
    asked: bool = False

    def first(self, conn: sqlite3.Connection, cfg: Config, song: Song, turns: _Turns, stats: AutoStats, stamp: str,
              told: Callable[[str], None]) -> Song | None:
        """The song after its words were heard where they are to be (``autochords_pending``), read again; None for a
        song that left the book meanwhile."""
        if not self.cap or self.stopped or self.tried >= self.cap or not song.audio_path:
            return song
        if self.hearing is None and self.asked:  # said already: nothing more to hear or say this run
            return song
        if why_not_offered(conn, cfg, song, turns.overrides) is not None:
            return song
        if self.hearing is None:
            self.asked = True
            stats.transcribe_problem = transcribe_problem(cfg)
            return song
        return self._hear_words(conn, cfg, self.hearing, song, turns, stats, stamp, told)

    def _hear_words(self, conn: sqlite3.Connection, cfg: Config, hearing: Hearing, song: Song, turns: _Turns,
                    stats: AutoStats, stamp: str, told: Callable[[str], None]) -> Song | None:
        from caracole.autochords.hearing import HearingFailed, Nothing

        self.tried += 1
        log.info("Hearing the words of %s (%d of up to %d)…", song.display, self.tried, self.cap)
        separated = (song.audio_path, song.audio_mtime)
        told(STEPS[4])
        try:
            vocals = hearing.vocals(song, on_doing=_quiet)
        except HearingFailed as e:  # the setup's alone
            return self._stop(stats, song, e.words)
        except Exception as e:  # noqa: BLE001 - a bug: the run fails, the song's chords made all the same
            return _hearing_bug(conn, stats, song, e)
        if turns.hand_over():  # a lookup went first: the song as it left it, and still to hear
            try:
                song = get_song(conn, song.id)
            except KeyError:
                return None
            why = why_not_offered(conn, cfg, song, turns.overrides)
            if (song.audio_path, song.audio_mtime) != separated:
                why = "its audio changed"
            if why is not None:
                log.info("%s: its words aren't heard now (%s)", song.display, why)
                return song
        told(STEPS[5])
        try:  # audio Whisper can't load noted as Whisper's alone: the vocals read it as the chords do
            heard = hearing.words(conn, song, vocals, stamp, on_doing=_quiet, file_unreadable=False)
        except HearingFailed as e:
            if e.kind == "setup":
                return self._stop(stats, song, e.words)
            log.warning("%s: %s; its chords are made without its words", song.display, e.words)
            return _again(conn, song)
        except Exception as e:  # noqa: BLE001 - a bug: the run fails, the song's chords made all the same
            return _hearing_bug(conn, stats, song, e)
        if isinstance(heard, Nothing):
            stats.silent += 1
            log.info("%s: nothing sung was heard (%s)", song.display, heard.why)
        else:
            stats.heard += 1
            log.info("%s: words heard, %s", song.display, heard.said)
        return _again(conn, song)

    def _stop(self, stats: AutoStats, song: Song, words: str) -> Song:
        """The setup failed: no more words heard this run, why kept for the to-do page, the chords going on."""
        self.stopped = True
        stats.transcribe_problem = words
        log.warning("%s: its words can't be heard here (%s); no song's are heard this run", song.display, words)
        return song


def _again(conn: sqlite3.Connection, song: Song) -> Song | None:
    """The song read again after its hearing; None for one gone meanwhile."""
    try:
        return get_song(conn, song.id)
    except KeyError:
        return None


def _hearing_bug(conn: sqlite3.Connection, stats: AutoStats, song: Song, e: Exception) -> Song | None:
    """A bug hearing the song, caracole's or deep in Whisper: one of the run's errors (the command exits 1), logged
    with its traceback whatever it raised; the song read again, its chords made as ever, counted by them."""
    stats.errors.append(f"{song.display}: {type(e).__name__}: {e}")
    log.error("%s: hearing its words failed: %s: %s", song.display, type(e).__name__, e, exc_info=True)
    return _again(conn, song)


def _quiet(said: str) -> None:
    """What a long step of hearing is at, which a pass over the library says nowhere: a line a song is its log."""


def _count_due(conn: sqlite3.Connection, cfg: Config, songs: Iterable[Song], overrides: Overrides,
               hears: int = 0) -> int:
    """How many of ``songs`` are due now, for the "3 of 12" before each, as ``_due`` would find them, counting
    nothing in a run's stats; with the first ``hears`` songs offered their words counted due too, as hearing them
    makes their sheet due."""
    n = 0
    for song in songs:
        if not song.audio_path or _known_failure(conn, song) is not None:
            continue
        heard = hears > 0 and why_not_offered(conn, cfg, song, overrides) is None
        hears -= heard
        try:
            if _skip_reason(conn, song, overrides) is not None and not heard:
                continue
        except Exception:  # noqa: BLE001 - a song's bad data: ``_due`` says so as its turn comes
            continue
        if keeper_of(conn, cfg.library_dir, song, AUTO_SHEET) is None:
            n += 1
    return n


def _due(conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides, failure: Failure | None,
         stats: AutoStats) -> bool:
    """Whether a song with linked audio is due for an auto sheet now. One that isn't is counted in ``stats`` here:
    skipped (by ``_skip_reason``, or as another song keeps a sheet where its own would go), failed (its file failed
    before and hasn't changed: ``failure``), or an error (its data couldn't be read)."""
    try:
        reason = _skip_reason(conn, song, overrides)
    except Exception as e:  # noqa: BLE001 - a song's bad data must not stop the others
        _error(stats, song, e)
        return False
    if reason is not None:
        log.debug("%s: skipped (%s)", song.display, reason)
        stats.skipped += 1
        return False
    if failure is not None:
        log.info(
            "%s: not tried again until %s changes (%s)",
            song.display,
            song.audio_path,
            failure.error,
        )
        stats.failed += 1
        stats.failures.append(failure)
        return False
    other = keeper_of(conn, cfg.library_dir, song, AUTO_SHEET)
    if other is not None:  # its sheet would go where another song keeps one: no model is run for it
        log.warning("%s", SharedFolder(song, other, AUTO_SHEET))
        stats.skipped += 1
        return False
    return True


@dataclass
class _Models:
    """The run's recognizer and beat tracker (``_models``), set up when the first song turns out to be due, so a
    night with no new audio loads no model; once they can't be, they aren't tried again that run."""

    cfg: Config
    recognizer: Recognizer | None
    beats_fn: BeatsFn | None
    loaded: tuple[Recognizer, BeatsFn] | None = None
    unavailable: bool = False

    def load(self, stats: AutoStats, told: Callable[[str], None]) -> tuple[Recognizer, BeatsFn] | None:
        """The models, set up now for the first song due (``told`` so); None when they can't run, each reason one of
        the run's errors in ``stats``, logged once."""
        if self.loaded is None and not self.unavailable:
            told(STEPS[0])
            try:
                self.loaded = _models(self.cfg, self.recognizer, self.beats_fn)
            except ModelsUnavailable as e:
                self.unavailable = True
                for message in e.args:
                    stats.errors.append(message)
                    log.error("auto-chords cannot run: %s", message)
        return self.loaded


def _generate(conn: sqlite3.Connection, cfg: Config, song: Song, models: tuple[Recognizer, BeatsFn], stamp: str,
              stats: AutoStats, told: Callable[[str], None]) -> None:
    """The song's auto sheet, made from its audio and kept in the library, counted in ``stats``: generated, or
    failed, by its file (``_unreadable``: tried again once the file changes) or by caracole (``_error``: the song
    stays due, and the run fails); ``told`` each step as it starts."""
    video = youtube_audio(conn, song)  # audio youtube_fetch.py took, rather than a purchase
    try:
        heard = _hear(song, *models, told)
    except Exception as e:  # noqa: BLE001 - one file's problem must not stop the others
        stats.failed += 1
        stats.failures.append(_unreadable(conn, song, e, stamp))
        return
    told(STEPS[3])
    try:
        transcript = transcript_of(conn, song)
        made = _make_sheet(song, heard, source=_from_youtube(video), transcript=transcript,
                           silent=transcript is None and _heard_nothing(conn, song))
    except Exception as e:  # noqa: BLE001 - a bug laying it out is caracole's, never the file's: the song stays due
        _error(stats, song, e)
        return
    try:
        _keep(conn, cfg, song, made.text, made.used, made.key, stamp, video=video, shift=made.shift,
              transcript=made.transcript, silent=made.silent)
    except Exception as e:  # noqa: BLE001 - the library's problem, not the purchase's
        _error(stats, song, e)
        return
    stats.generated += 1
    log.info("%s: auto sheet written (%s lyrics)", song.display, made.used)


def _record_run(conn: sqlite3.Connection, stats: AutoStats, stamp: str, only: Collection[int] | None) -> None:
    """kv ``autochords:status``, the run's record for the to-do page, stamped ``stamp``. After a run over some songs
    (``only``), the other songs' failures stay listed, as the last whole run found them."""
    failed = [asdict(f) for f in stats.failures]
    record = {"at": stamp, "generated": stats.generated, "skipped": stats.skipped, "failed": failed,
              "heard": stats.heard, "silent": stats.silent, "transcribe_problem": stats.transcribe_problem}
    if only is not None:  # the other songs' failures stay listed, as the last whole run found them
        before = kv_get_json(conn, STATUS_KEY)
        before = before if isinstance(before, dict) else {}
        mine = {_failed_display(conn, i) for i in only}
        kept = [f for f in before.get("failed") or [] if isinstance(f, dict) and f.get("song") not in mine]
        record = {**before, "failed": kept + failed} if before else record
    kv_set_json(conn, STATUS_KEY, record)


def _failed_display(conn: sqlite3.Connection, song_id: int) -> str | None:
    """How the run's record names a song's failure: its "Artist - Title"; None for a song gone."""
    try:
        return get_song(conn, song_id).display
    except KeyError:
        return None


def _failed_key(song_id: int) -> str:
    """kv: the audio file of the song that couldn't be read, written here (and by the transcription job, through
    ``_unreadable``); transcript.py reads it too, offering such a song no transcription."""
    return f"{UNREADABLE}{song_id}"


def _known_failure(conn: sqlite3.Connection, song: Song) -> Failure | None:
    """The failure recorded for the song's audio file, while it is still the song's file.

    A failure recorded for a file the song no longer has (replaced, converted
    or gone) is forgotten, so whatever file comes next is tried.
    """
    key = _failed_key(song.id)
    record = kv_get_json(conn, key)
    if record is None:
        return None
    if (
        isinstance(record, dict)
        and song.audio_path is not None
        and record.get("audio") == song.audio_path
        and record.get("audio_mtime") == song.audio_mtime
    ):
        return Failure(song.display, str(record.get("error") or ""), song.audio_path)
    kv_delete(conn, key)
    return None


def _unreadable(conn: sqlite3.Connection, song: Song, e: Exception, stamp: str) -> Failure:
    """Record that the song's audio file couldn't be read; it is tried again once it changes."""
    audio = song.audio_path or ""
    failure = Failure(song.display, _short(e, audio), audio)
    kv_set_json(
        conn,
        _failed_key(song.id),
        {"audio": audio, "audio_mtime": song.audio_mtime, "error": failure.error, "at": stamp},
    )
    # Decoding and model errors are one line; anything else is likely a bug, so keep the trace.
    log.warning(
        "%s: auto-chords couldn't read %s, and tries again once it changes: %s: %s",
        song.display,
        audio,
        type(e).__name__,
        e,
        exc_info=not isinstance(e, (OSError, RuntimeError, ValueError)),
    )
    return failure


def _error(stats: AutoStats, song: Song, e: Exception) -> None:
    """Something other than the song's file went wrong: the song stays due, and the run fails."""
    message = f"{type(e).__name__}: {e}"
    stats.failed += 1
    stats.errors.append(f"{song.display}: {message}")
    log.error(
        "%s: auto-chords failed: %s",
        song.display,
        message,
        exc_info=not isinstance(e, (OSError, RuntimeError, ValueError)),
    )


def _short(e: BaseException, path: str) -> str:
    """An error as the to-do page lists it: its type and the first line of its message.

    The file at ``path`` is only named: the page shows where it is, and decoders
    can repeat a long path until the reason itself is cut off.
    """
    message = str(e).replace(path, Path(path).name) if path else str(e)
    first = next((line.strip() for line in message.splitlines() if line.strip()), "")
    text = f"{type(e).__name__}: {first}" if first else type(e).__name__
    return text if len(text) <= ERROR_CHARS else text[: ERROR_CHARS - 1] + "…"


def _skip_reason(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> str | None:
    """Why a song with linked audio is not due for an auto sheet, or None when it is."""
    if song.status == "ignored" or song.key in overrides.ignore:
        return "ignored"
    if not Path(song.audio_path or "").is_file():
        return "audio file missing"
    kept = {f.name: f for f in kept_files(conn, song.id)}
    if HUMAN_SHEET in kept:
        return "has a human sheet"
    # Not "newer than": Syncthing keeps the sender's mtime, so a replacement can be older.
    if song.autochords_mtime is None or song.audio_mtime != song.autochords_mtime:
        return None
    auto = kept.get(AUTO_SHEET)
    if auto is None:
        return None
    raw = get_version(conn, auto.version_id).raw
    if raw.get("lyrics") == "none" and _sung_lyrics(song):
        return None  # made before LRCLIB answered: once more, now with the words
    kept_transcript = transcript_of(conn, song)
    if raw.get("lyrics_source") == LYRICS_SOURCE:
        if _sung_lyrics(song) or _instrumental(song):
            return None  # a site has lyrics now, or says it is instrumental: they always win, once more over them
        if kept_transcript is None or raw.get("transcript_made_at") != kept_transcript.made_at:
            return None  # over a transcript that is not the one kept now (of other audio, or made again)
    elif raw.get("lyrics") == "none" and kept_transcript is not None and not _instrumental(song):
        return None  # a transcript of this audio came since: once more, over its words
    elif (raw.get("lyrics") == "none" and not raw.get("heard_nothing") and not _instrumental(song)
          and _heard_nothing(conn, song)):
        return None  # noted as having nothing sung since: once more, to say so
    if raw.get("lyrics") == "plain" and _synced_key(song) not in (None, raw.get("synced_lyrics")):
        return None  # timed lyrics came since: once more, with each chord over its word where they fit the audio
    if raw.get("lyrics") == "synced" and raw.get("columns") != COLUMNS and _wider_lines(song):
        return None  # its chords at their characters' indexes, before they went at display columns: once more
    return "up to date"


def _synced_key(song: Song) -> str | None:
    """A short hash of the song's timed lyrics, which its auto sheet's version keeps as ``synced_lyrics``: a sheet
    over plain lyrics is made again only once other timed lyrics than those come. None when it has none, or its
    lyrics can't be read."""
    try:
        lyrics = _sung_lyrics(song)
    except (TypeError, ValueError):
        return None
    if lyrics is None or not lyrics.synced:
        return None
    return hashlib.sha256(lyrics.synced.encode("utf-8")).hexdigest()[:16]


def _wider_lines(song: Song) -> bool:
    """Whether the song's timed lyrics have a line whose display columns aren't its characters' indexes: a
    Chinese character is two columns wide, a combining accent none. False for lyrics that can't be read."""
    try:
        lyrics = _sung_lyrics(song)
    except (TypeError, ValueError):
        return False
    if lyrics is None or not lyrics.synced:
        return False
    return any(display_columns(text) != list(range(len(text) + 1)) for _, text in parse_lrc(lyrics.synced))


def _models(
    cfg: Config, recognizer: Recognizer | None, beats_fn: BeatsFn | None
) -> tuple[Recognizer, BeatsFn]:
    """The recognizer and the beat tracker, defaults built from ``cfg``.

    Both defaults are tried, so ModelsUnavailable names every missing piece at
    once. Each default must then read a test tone: a model that fails on that
    would fail on every purchase (a sandbox that stops it, a checkpoint that
    won't load), which is the setup's problem rather than any file's.
    """
    problems: list[str] = []
    built: list[tuple[str, Callable[[Path], object]]] = []
    if beats_fn is None:
        try:
            beats_fn = _default_beats(cfg)
            built.append(("beat_this", beats_fn))
        except ModelsUnavailable as e:
            problems += e.args
    if recognizer is None:
        try:
            recognizer = _default_recognizer(cfg)
            built.append(("BTC", recognizer.recognize))
        except ModelsUnavailable as e:
            problems += e.args
        except Exception as e:  # noqa: BLE001 - missing or broken weights, or torch failing to load
            problems.append(f"{type(e).__name__}: {e}")
    problems += _test_tone(built)
    if problems or recognizer is None or beats_fn is None:
        raise ModelsUnavailable(*problems)
    return recognizer, beats_fn


def _test_tone(models: list[tuple[str, Callable[[Path], object]]]) -> list[str]:
    """Run each model on a test tone; what fails, one line each."""
    if not models:
        return []
    problems = []
    with tempfile.TemporaryDirectory(prefix="caracole-autochords-") as tmp:
        tone = _write_tone(Path(tmp) / "test-tone.wav")
        for name, model in models:
            try:
                model(tone)
            except Exception as e:  # noqa: BLE001 - what stops it here stops it on every purchase
                problems.append(f"{name} fails on a test tone: {_short(e, str(tone))}")
    return problems


def _write_tone(path: Path, rate: int = 22050) -> Path:
    """A C major chord as a 16-bit mono WAV, which every working setup can decode."""
    samples = array(
        "h",
        (
            round(8000 * sum(math.sin(2 * math.pi * hz * i / rate) for hz in TONE_HZ))
            for i in range(round(TONE_SECONDS * rate))
        ),
    )
    if sys.byteorder == "big":
        samples.byteswap()  # WAV samples are little-endian
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


def _unconfigured(what: str, env_var: str, key: str) -> str:
    return f"no {what} configured: set {env_var}, or {key} under [autochords] in caracole.toml"


def _default_recognizer(cfg: Config) -> Recognizer:
    weights = cfg.autochords.btc_weights
    if weights is None:
        raise ModelsUnavailable(_unconfigured("BTC weights", "CARACOLE_BTC_WEIGHTS", "btc_weights"))
    return BTCRecognizer(weights, device=cfg.autochords.device)


def _default_beats(cfg: Config) -> BeatsFn:
    checkpoint = cfg.autochords.beat_checkpoint
    if checkpoint is None:
        raise ModelsUnavailable(
            _unconfigured("beat_this checkpoint", "CARACOLE_BEAT_CHECKPOINT", "beat_checkpoint")
        )
    # detect_beats checks as well, but once per song; this reports it once.
    if not checkpoint.is_file():
        raise ModelsUnavailable(f"beat_this checkpoint not found: {checkpoint}")
    device = cfg.autochords.device
    return lambda path: detect_beats(path, checkpoint, device=device)


def _instrumental(song: Song) -> bool:
    """Whether a site says the song is instrumental: its verdict wins over a transcript, which it never gets."""
    if song.lyrics_status == "instrumental":
        return True
    lyrics = song_lyrics(song)
    return lyrics is not None and lyrics.instrumental and not lyrics.has_lyrics


def _sung_lyrics(song: Song) -> Lyrics | None:
    """The song's stored lyrics, when they have words (an instrumental has none)."""
    lyrics = song_lyrics(song)
    return lyrics if lyrics is not None and lyrics.has_lyrics else None


@dataclass(frozen=True)
class _Timed:
    """Synced lyrics that fit the audio: their LRC text and, when LRCLIB timed them for audio of
    another length, the seconds they were shifted by to fit it (``shift``, 0.0 for none) and how
    much longer the audio is (``longer``, less than 0 for shorter)."""

    text: str
    shift: float | None = None
    longer: float = 0.0

    def note(self) -> str | None:
        """What the sheet says of a shift, so that a wrong one shows; None for lyrics that fit as timed."""
        if self.shift is None:
            return None
        if self.shift:
            later = "later" if self.shift > 0 else "earlier"
            return f"Lyrics' timing shifted {abs(self.shift):.1f} s {later} to fit this audio"
        than = "shorter" if self.longer > 0 else "longer"
        return f"Lyrics' timing unshifted: LRCLIB's audio is {abs(self.longer):.1f} s {than}"


def _synced_for(
    song: Song,
    lyrics: Lyrics | None,
    audio: Path,
    heard: Sequence[ChordSegment],
    beats: Sequence[float],
    downbeats: Sequence[float],
) -> _Timed | None:
    """The synced lyrics, if their timings fit this audio file: as they are when the durations agree
    within 2 s, else moved by the shift ``align.lyrics_offset`` finds clearly from the chords heard
    and the beats; None when it finds none."""
    if lyrics is None or not lyrics.synced or lyrics.duration is None:
        return None
    duration = read_audio(audio).duration_s
    if duration is None:
        return None
    longer = duration - lyrics.duration
    if abs(longer) <= SYNC_TOLERANCE_S:
        return _Timed(lyrics.synced)
    lines = parse_lrc(lyrics.synced)
    try:
        found = lyrics_offset(lines, heard, beats, downbeats, audio_s=duration, lyrics_s=lyrics.duration)
    except Exception:  # noqa: BLE001 - a bug here must not pass for a purchase auto-chords can't read
        log.exception("%s: looking for how far to shift LRCLIB's timed lyrics failed; the plain lyrics instead",
                      song.display)
        return None
    than = "longer" if longer > 0 else "shorter"
    if found.offset is None:
        log.info("%s: the audio is %.1f s %s than LRCLIB's timed lyrics, and no shift fits them to it clearly "
                 "(%s): the plain lyrics instead", song.display, abs(longer), than, found.why)
        return None
    log.info("%s: the audio is %.1f s %s than LRCLIB's timed lyrics, which fit it shifted by %+.1f s (%s)",
             song.display, abs(longer), than, found.offset, found.why)
    text = shifted_lrc(lyrics.synced, found.offset) if found.offset else lyrics.synced
    return _Timed(text, found.offset, longer)


def _word_timed(synced: str | None) -> list[LrcLine] | None:
    """The synced lyrics read with their word stamps, when they time words (enhanced LRC)."""
    lines = parse_lrc_words(synced) if synced else []
    return lines if any(line.words for line in lines) else None


def _from_youtube(video: Video | None) -> str | None:
    """The sheet's line for audio taken from YouTube: which video it was, by its title and channel
    (``merge.youtube_credit``); the version keeps its address (``_keep``)."""
    if video is None:
        return None
    return youtube_credit(video.title, video.channel, video.id)


@dataclass(frozen=True)
class _Heard:
    """What the models heard in a song's audio file: its chords and its beats."""

    audio: Path
    segments: list[ChordSegment]
    beats: Sequence[float]
    downbeats: Sequence[float]


def _hear(song: Song, recognizer: Recognizer, beats_fn: BeatsFn, told: Callable[[str], None]) -> _Heard:
    """The models over the song's audio file: what fails here is the file's (one that won't decode, say), which
    ``_unreadable`` records; what fails after it, laying out the sheet, is a bug of caracole's."""
    audio = Path(song.audio_path or "")
    told(STEPS[1])
    segments = recognizer.recognize(audio)
    told(STEPS[2])
    beats, downbeats = beats_fn(audio)
    return _Heard(audio, list(segments), beats, downbeats)


@dataclass(frozen=True)
class _Made:
    """One song's auto sheet: its text, which lyrics it used ("synced", "plain" or "none"), the key of the chords
    heard (None when they fit no key), the seconds its timed lyrics were shifted by to fit the audio (None when
    LRCLIB timed them for audio of the same length, or they weren't used), and the transcript it was made over
    (None unless the words are Whisper's)."""

    text: str
    used: str
    key: str | None
    shift: float | None
    transcript: Transcript | None = None
    silent: bool = False


def _make_sheet(song: Song, heard: _Heard, *, source: str | None = None,
                transcript: Transcript | None = None, silent: bool = False) -> _Made:
    """One song's auto sheet, from its audio file. ``source`` says where that came from, when it wasn't a
    purchase, on the sheet's line after the song's name; the shift has the line after it.

    The song's lyrics from a site, whenever it has any (and a site's word that it is
    instrumental wins too), else its ``transcript`` (Whisper's words from this
    very audio: timed lyrics whose duration is the audio's, so they fit as they are and no shift is searched,
    with NOTE on the line after the shift's), else none. ``silent`` (the audio noted as having nothing sung)
    puts SILENT there instead, only where no site has lyrics, none says it is instrumental and no transcript is used.

    The key is estimated from the chords as recognized, each weighed by how long it sounds,
    before they are snapped to beats and laid out.
    """
    audio, segments, beats, downbeats = heard.audio, heard.segments, heard.beats, heard.downbeats
    key = estimate_key((s.label, s.end - s.start) for s in segments if s.label != NO_CHORD)
    lyrics = _sung_lyrics(song)
    over = transcript if lyrics is None and not _instrumental(song) else None
    timed = _Timed(over.lrc) if over is not None else _synced_for(song, lyrics, audio, segments, beats, downbeats)
    synced = timed.text if timed is not None else None
    plain = lyrics.plain if lyrics is not None else None
    # The shift on a line of its own after the credit: render.py takes that line for the credit, and the viewer of
    # a sheet from YouTube draws the video in its place, so the shift is the first of the sheet's own words
    silent = silent and lyrics is None and over is None and not _instrumental(song)
    notes = (source, timed.note() if timed is not None else None, NOTE if over is not None else None,
             SILENT if silent else None)
    note = "\n".join(part for part in notes if part)
    text = build_sheet(
        segments,
        title=song.title,
        artist=song.artist,
        synced=synced,
        synced_words=_word_timed(synced),
        plain=plain,
        beats=beats,
        downbeats=downbeats,
        source=note or None,
    )
    shift = timed.shift if timed is not None else None
    return _Made(text, "synced" if synced else "plain" if plain else "none", key, shift, over, silent)


def _keep(
    conn: sqlite3.Connection,
    cfg: Config,
    song: Song,
    text: str,
    used: str,
    key: str | None,
    stamp: str,
    *,
    video: Video | None = None,
    shift: float | None = None,
    transcript: Transcript | None = None,
    silent: bool = False,
) -> None:
    """Keep one song's auto sheet, under a version of provider ``auto``; the song becomes found.

    The key heard goes into the version's ``raw``, for ``keys.song_key``, and so does the shift
    of timed lyrics LRCLIB timed for audio of another length (``lyrics_shift``), what its
    chord lines' columns count (``columns``: ``COLUMNS``), and the timed lyrics the song had,
    used or not (``synced_lyrics``, ``_synced_key``). A sheet made over a transcript keeps it as
    ``lyrics_source``, ``transcript`` (its LRC, for the viewer's sung line) and ``transcript_made_at``
    (``_skip_reason`` compares it with the transcript kept now). Audio from
    YouTube (``video``) gives the version the video's address, so info.json names it, and its
    fields.
    """
    audio = Path(song.audio_path or "")
    raw: dict[str, object] = {"audio": song.audio_path, "model": MODEL, "lyrics": used, "columns": COLUMNS}
    if key is not None:
        raw["key"] = key
    if shift is not None:
        raw["lyrics_shift"] = shift
    if transcript is not None:
        raw["lyrics_source"] = LYRICS_SOURCE
        raw["transcript"] = transcript.lrc
        raw["transcript_made_at"] = transcript.made_at
    if silent:
        raw["heard_nothing"] = True
    synced = _synced_key(song)
    if synced is not None:
        raw["synced_lyrics"] = synced
    if video is not None:
        raw["youtube"] = video.as_json()
    version_id = upsert_version(
        conn,
        provider=PROVIDER,
        tab_id=str(song.id),
        song_id=song.id,
        slot="sheet",
        kind="auto",
        rating=0,
        votes=0,
        version=1,
        label=None,
        url=video.url if video is not None else "file://" + str(audio.absolute()),
        raw=raw,
        now=stamp,
    )
    keep_file(
        conn,
        cfg.library_dir,
        song=song,
        version_id=version_id,
        name=AUTO_SHEET,
        data=text.encode("utf-8"),
        rank=1,
    )
    refresh_status(conn, song.id, ignored=False)
    write_info(conn, cfg.library_dir, get_song(conn, song.id))
    # Last, so a run cut short anywhere above just does this song again.
    update_song(conn, song.id, autochords_mtime=song.audio_mtime)
