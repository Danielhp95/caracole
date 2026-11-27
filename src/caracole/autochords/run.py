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
  columns (its version's ``raw`` has no ``columns``), or over the song's lyrics
  before they became other words (its version's ``raw["lyrics_key"]``, the key
  of the words it was made over, sheet.py's ``song_lyrics_key``, isn't the song's now: a pick
  of other lyrics; a sheet an older caracole made keeps none, and isn't made
  again for it): once more, each, so timed
  lyrics that don't fit the audio make a plain sheet again once, never every
  night (plain lyrics that come after a sheet of none rarely get here: they need
  no model, and the next render puts them on it, sheet_lyrics.py, with their key);
- the words' reasons above are a sheet's that keeps no ``heard`` alone (made before
  what was heard was kept): one that keeps it is laid out again over new words
  with no model, in render's first step (sheet_lyrics.py ``relay_onto_sheets``),
  and is due here only once its audio changes;
- that file hasn't already failed;
- no other song keeps a ``sheet (auto).txt`` where its own would go (two songs
  whose names make one folder, ``library.SharedFolder``): such a song is skipped,
  with a warning, before any model runs, and waits.

For each song due, BTC recognizes the chords, beat_this finds the beats (``_hear``, with the
audio's length as ``music.read_audio`` reads it: a ``sheet.Heard``), and sheet.py's ``make_sheet``, which
reads no audio, has ``merge.build_sheet`` lay the chords out over LRCLIB's lyrics: the synced ones
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
  dropped once the song's file changes or goes. transcript.py offers such a
  song no transcription. (Whisper's decoder refusing a file auto-chords reads
  is Whisper's alone: transcript.py ``note_whisper_cant_read``.)
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

from caracole.autochords import beats as beat_this
from caracole.autochords.audio import sha16
from caracole.autochords.beats import detect_beats
from caracole.autochords.btc import BTCRecognizer
from caracole.autochords.merge import ChordSegment, youtube_credit
from caracole.autochords.remeasure import remeasure_once
from caracole.autochords.sheet import (
    COLUMNS,
    Heard,
    Made,
    Maker,
    instrumental,
    make_sheet,
    raw_of,
    song_lyrics_key,
    sung_lyrics,
    synced_key,
    wider_lines,
)
from caracole.autochords.sheet_lyrics import relay_onto_sheets, relay_reason
from caracole.autochords.transcript import (
    LYRICS_SOURCE,
    UNREADABLE,
    Transcript,
    hearing_failed,
    said_not_sung,
    transcript_of,
    why_not_offered,
)
from caracole.autochords.transcript import heard_nothing as _heard_nothing
from caracole.config import Config
from caracole.db import kv_delete, kv_get_json, kv_set_json
from caracole.library import SharedFolder, keep_file, keeper_of, kept_files, write_info
from caracole.music import read_audio
from caracole.overrides import Overrides, load_overrides
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, get_song, list_songs, refresh_status, update_song
from caracole.stamps import parse as parse_stamp
from caracole.versions import AUTO, auto_version_of, auto_versions_beside, get_version, upsert_version
from caracole.youtube import Video
from caracole.youtube_fetch import transcribe_problem, youtube_audio

if TYPE_CHECKING:
    from caracole.autochords.hearing import Hearing

log = logging.getLogger(__name__)

PROVIDER = AUTO
MADE_ON = "computer"  # the side an auto sheet made here was made on (its raw's ``made_on``; the phone's "phone")
RELAID = "its words are laid out again from what was heard"  # ``_skip_reason``'s, for a re-lay's words
STATUS_KEY = "autochords:status"  # kv: the last run, for the to-do page
ERROR_CHARS = 300  # an error as the to-do page lists it: one line, if a long one
# What ``autochords_pending`` tells its ``on_step`` as each step starts: a song's chords, then, before them, its words
# where it hears them (``hearing``).
STEPS = ("setting up the models", "hearing the chords", "finding the beats", "writing the sheet",
         "separating the vocals", "hearing the words")
TONE_SECONDS = 2.0
TONE_HZ = (261.63, 329.63, 392.0)  # C major: C4, E4 and G4


class Recognizer(Protocol):
    """Timed chords from an audio file, like ``btc.BTCRecognizer``, which also says its ``name`` and ``runtime``
    (an auto sheet's raw keeps them where a recognizer says them)."""

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
    ``remeasured``: the songs whose MP3's guessed length the run put right, once ever (remeasure.py), by name.
    ``relaid``: the sheets that keep what was heard laid out again over their song's new words, no model (``_due``);
    counted apart from the three.
    """

    generated: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[Failure] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    heard: int = 0
    silent: int = 0
    transcribe_problem: str | None = None
    remeasured: list[str] = field(default_factory=list)
    relaid: int = 0

    def summary(self) -> str:
        """One line for the journal or a notification: "1 generated, 4 skipped, 0 failed", then what was heard, or
        why nothing was, where anything was to hear ("; words heard for 1, nothing sung in 1")."""
        said = f"{self.generated} generated, {self.skipped} skipped, {self.failed} failed"
        if self.relaid:
            said += f", {self.relaid} laid out again over new words"
        if self.heard or self.silent:
            said += f"; words heard for {self.heard}, nothing sung in {self.silent}"
        if self.transcribe_problem is not None:
            said += f"; words not heard: {self.transcribe_problem}"
        if self.remeasured:
            said += (f"; remeasured {len(self.remeasured)} whose MP3 names no length, made again: "
                     + ", ".join(self.remeasured))
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
    remeasure: bool = False,
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

    ``remeasure``, the bulk command's alone (``caracole autochords`` over every song): first, once ever, what was made
    from an MP3 whose length was guessed wrong made again (remeasure.py), those songs in ``stats.remeasured``.
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if overrides is None:
        overrides = load_overrides(cfg.overrides_file)
    stats = AutoStats()
    told = on_step or (lambda said: None)
    models = _Models(cfg, recognizer, beats_fn)
    if remeasure:  # once ever: an MP3 whose length was guessed (remeasure.py)
        stats.remeasured = remeasure_once(conn, cfg, list_songs(conn), overrides, stamp)
    songs = [s for s in list_songs(conn) if only is None or s.id in only]
    hears = transcriptions if hearing is not None else 0
    due, worked = _count_due(conn, cfg, songs, overrides, hears, parse_stamp(stamp)), 0
    turns = _Turns(cfg, conn, overrides, between)
    listening = _Listening(hearing, transcriptions)
    for listed in turns.each(songs):
        song = listening.first(conn, cfg, listed, turns, stats, stamp, told)
        if song is None:  # left the book while its words were heard and a lookup went first
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
        failed = hearing_failed(conn, song, parse_stamp(stamp) or datetime.now(UTC))
        if failed is not None:  # its hearing failed lately: passed over, no slot taken, till a new file or 30 days
            log.info("%s: its words aren't heard tonight (its hearing failed lately: %s)", song.display, failed)
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
            return self._stop(conn, stats, song, e.words, stamp)
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
            heard = hearing.words(conn, song, vocals, stamp, on_doing=_quiet)
        except HearingFailed as e:
            if e.kind == "setup":
                return self._stop(conn, stats, song, e.words, stamp)
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
        turns.hand_over()  # a waiting lookup goes first before the chords, as the jobs let it; the song read again
        return _again(conn, song)

    def _stop(self, conn: sqlite3.Connection, stats: AutoStats, song: Song, words: str, stamp: str) -> Song:
        """The setup failed: no more words heard this run, why kept for the to-do page, the chords going on; the song's
        audio noted (``note_hearing_failed``), so that the next nights pass over it for a while and hear the others,
        should the failure be its file's."""
        from caracole.autochords.transcript import note_hearing_failed

        self.stopped = True
        note_hearing_failed(conn, song, stamp, words)
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
               hears: int = 0, now: datetime | None = None) -> int:
    """How many of ``songs`` are due now, for the "3 of 12" before each, as ``_due`` would find them, counting
    nothing in a run's stats; with the first ``hears`` songs offered their words counted due too, as hearing them
    makes their sheet due (not one whose hearing failed lately: ``_Listening.first`` passes over it)."""
    now = now or datetime.now(UTC)
    n = 0
    for song in songs:
        if not song.audio_path or _known_failure(conn, song) is not None:
            continue
        heard = (hears > 0 and why_not_offered(conn, cfg, song, overrides) is None
                 and hearing_failed(conn, song, now) is None)
        hears -= heard
        heard = heard and not _keeps_heard(conn, song)  # its words heard re-lay it, no model
        try:
            if _skip_reason(conn, song, overrides) is not None and not heard:
                continue
        except Exception:  # noqa: BLE001 - a song's bad data: ``_due`` says so as its turn comes
            continue
        if keeper_of(conn, cfg.library_dir, song, AUTO_SHEET) is None:
            n += 1
    return n


def _keeps_heard(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the song's kept auto sheet keeps what was heard (``raw["heard"]``): its words alone never make it the
    models' again."""
    auto = next((f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET), None)
    return auto is not None and get_version(conn, auto.version_id).raw.get("heard") is not None


def _due(conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides, failure: Failure | None,
         stats: AutoStats) -> bool:
    """Whether a song with linked audio is due for an auto sheet now. One that isn't is counted in ``stats`` here:
    skipped (by ``_skip_reason``, or as another song keeps a sheet where its own would go), failed (its file failed
    before and hasn't changed: ``failure``), or an error (its data couldn't be read). One whose sheet keeps what was
    heard and whose words alone changed (``RELAID``: its words heard just before, or lyrics a render hasn't put on it
    yet) is laid out again here, with no model (sheet_lyrics.py ``relay_onto_sheets``), and counted ``relaid``."""
    try:
        reason = _skip_reason(conn, song, overrides)
    except Exception as e:  # noqa: BLE001 - a song's bad data must not stop the others
        _error(stats, song, e)
        return False
    if reason == RELAID:  # its words alone changed (its words heard just now, say): laid out again, no model
        bugs: list[str] = []
        if relay_onto_sheets(conn, cfg, overrides, only={song.id}, errors=bugs):
            stats.relaid += 1
        elif bugs:  # a bug laying it out: one of the run's errors (exit 1), as a hearing's is
            stats.failed += 1
            stats.errors.extend(bugs)
        else:  # logged where it failed: the next render tries again
            stats.skipped += 1
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
    except _LengthUnread as e:  # the models read the file: its length read after them is caracole's, never the file's
        _error(stats, song, e.read)
        return
    except Exception as e:  # noqa: BLE001 - one file's problem must not stop the others
        stats.failed += 1
        stats.failures.append(_unreadable(conn, song, e, stamp))
        return
    told(STEPS[3])
    try:
        maker = _maker(conn, song, *models, video)  # the audio hashed once a hearing, after the models read it
        transcript = transcript_of(conn, song)
        silent = transcript is None and _heard_nothing(conn, song)
        made = make_sheet(song, heard, source=_from_youtube(video), transcript=transcript, silent=silent,
                          said=silent and said_not_sung(conn, song))
    except Exception as e:  # noqa: BLE001 - a bug laying it out is caracole's, never the file's: the song stays due
        _error(stats, song, e)
        return
    try:
        _keep(conn, cfg, song, made.text, made.used, made.key, stamp, video=video, shift=made.shift,
              transcript=made.transcript, silent=made.silent, said=made.said, heard=made.heard, maker=maker)
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
              "heard": stats.heard, "silent": stats.silent, "transcribe_problem": stats.transcribe_problem,
              "remeasured": stats.remeasured}
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
    """kv: the audio file of the song that couldn't be read, written here (``_unreadable``); transcript.py reads it
    too, offering such a song no transcription."""
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
    """Why a song with linked audio is not due for an auto sheet, or None when it is. A sheet that keeps what was heard
    (``raw["heard"]``) is never due for its words alone: they re-lay it with no model (sheet_lyrics.py
    ``relay_onto_sheets``, ``RELAID`` the reason while that is due); only its audio's change (or a sheet gone) makes it
    the models' again. A sheet made before ``heard`` was kept is due for its words as ever."""
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
    if raw.get("heard") is not None:  # what was heard is kept: its words alone re-lay it (sheet_lyrics.py), no model
        return RELAID if relay_reason(conn, song, raw) is not None else "up to date"
    if raw.get("lyrics") == "none" and sung_lyrics(song):
        return None  # made before LRCLIB answered: once more, now with the words
    kept_transcript = transcript_of(conn, song)
    if raw.get("lyrics_source") == LYRICS_SOURCE:
        if sung_lyrics(song) or instrumental(song):
            return None  # a site has lyrics now, or says it is instrumental: they always win, once more over them
        if kept_transcript is None or raw.get("transcript_made_at") != kept_transcript.made_at:
            return None  # over a transcript that is not the one kept now (of other audio, or made again)
    elif raw.get("lyrics") == "none" and kept_transcript is not None and not instrumental(song):
        return None  # a transcript of this audio came since: once more, over its words
    elif (raw.get("lyrics") == "none" and not raw.get("heard_nothing") and not instrumental(song)
          and _heard_nothing(conn, song)):
        return None  # noted as having nothing sung since: once more, to say so
    words = raw.get("lyrics_key")  # none on a sheet an older caracole made: up to date, as it was
    if (words is not None and raw.get("lyrics") in ("synced", "plain") and raw.get("lyrics_source") != LYRICS_SOURCE
            and song_lyrics_key(song) not in (None, words)):
        return None  # the song's lyrics are other words now (another pick): once more, over them
    if raw.get("lyrics") == "plain" and synced_key(song) not in (None, raw.get("synced_lyrics")):
        return None  # timed lyrics came since: once more, with each chord over its word where they fit the audio
    if raw.get("lyrics") == "synced" and raw.get("columns") != COLUMNS and wider_lines(song):
        return None  # its chords at their characters' indexes, before they went at display columns: once more
    return "up to date"


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
    return _Beats(checkpoint, cfg.autochords.device)


class _Beats:
    """beat_this's beats with the configured checkpoint, and its ``name`` for an auto sheet's raw."""

    def __init__(self, checkpoint: Path, device: str):
        self.checkpoint, self.device = checkpoint, device
        self.name = beat_this.model_name(checkpoint)

    def __call__(self, path: Path) -> tuple[Sequence[float], Sequence[float]]:
        return detect_beats(path, self.checkpoint, device=self.device)


def _maker(conn: sqlite3.Connection, song: Song, recognizer: Recognizer, beats_fn: BeatsFn,
           video: Video | None) -> Maker:
    """Who made the song's auto sheet here, from what: this side, this caracole's id (peer_sync.py ``own_id``), the
    models' names and runtime where they say them, the audio file's name (a purchase's own; for a file you gave, the
    name it was given under, audio_store.py ``given_name``, none for one kept before that was recorded; none for
    YouTube's) and its bytes' hash, read once."""
    from caracole.audio_store import given_file, given_name
    from caracole.peer_sync import own_id

    audio = Path(song.audio_path or "")
    models = {part: name for part, name in (("chords", getattr(recognizer, "name", None)),
                                            ("beats", getattr(beats_fn, "name", None))) if isinstance(name, str)}
    runtime = getattr(recognizer, "runtime", None)
    name = None if video is not None else given_name(conn, song) if given_file(song.audio_path) else audio.name
    return Maker(MADE_ON, own_id(conn), models, runtime if isinstance(runtime, str) else None, name, sha16(audio))


def _from_youtube(video: Video | None) -> str | None:
    """The sheet's line for audio taken from YouTube: which video it was, by its title and channel
    (``merge.youtube_credit``); the version keeps its address (``_keep``)."""
    if video is None:
        return None
    return youtube_credit(video.title, video.channel, video.id)


class _LengthUnread(Exception):
    """``read_audio`` failing on a file the models just read (gone between the two, say): caracole's error, the song
    still due, never a failure filed against its audio (``read``, what it raised)."""

    def __init__(self, read: Exception):
        super().__init__(str(read))
        self.read = read


def _hear(song: Song, recognizer: Recognizer, beats_fn: BeatsFn, told: Callable[[str], None]) -> Heard:
    """The models over the song's audio file, and its length as ``music.read_audio`` reads it, the one the sheet is
    laid out against (sheet.py, which reads no audio): what the models fail on is the file's (one that won't decode,
    say), which ``_unreadable`` records; the length's read failing after them is caracole's (``_LengthUnread``), as is
    what fails after it, laying out the sheet."""
    audio = Path(song.audio_path or "")
    told(STEPS[1])
    segments = recognizer.recognize(audio)
    told(STEPS[2])
    beats, downbeats = beats_fn(audio)
    try:
        duration = read_audio(audio).duration_s
    except Exception as e:  # noqa: BLE001 - whatever it raises: the song stays due
        raise _LengthUnread(e) from e
    return Heard(list(segments), beats, downbeats, duration)


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
    said: bool = False,
    heard: Heard | None = None,
    maker: Maker | None = None,
) -> None:
    """Keep one song's auto sheet, under a version of provider ``auto`` whose ``raw`` is sheet.py's ``raw_of`` (what
    was ``heard`` and its ``maker`` with it); the song becomes found. Audio from YouTube (``video``) gives the version
    the video's address, so info.json names it.

    A song keeps one auto version, whoever made it: the sheet goes into the one it has (versions.py
    ``auto_version_of``: one another caracole made keeps that caracole's tab id), else one of tab id its song id; a
    second one a song held from before (a sheet made here beside one taken at a sync) that no kept file names is let
    go of, logged, so that its unit lists the one."""
    audio = Path(song.audio_path or "")
    raw = raw_of(song, Made(text, used, key, shift, transcript, silent, said, heard), video=video, maker=maker)
    current = auto_version_of(conn, song.id)
    version_id = upsert_version(
        conn,
        provider=PROVIDER,
        tab_id=current.tab_id if current is not None else str(song.id),
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
    for other in auto_versions_beside(conn, song.id, version_id):
        conn.execute("DELETE FROM versions WHERE id = ?", (other.id,))
        log.warning("%s: a second auto version (tab %s, made %s) let go of: the sheet is kept in tab %s, a song keeps "
                    "one", song.display, other.tab_id, other.fetched_at, current.tab_id if current else song.id)
    refresh_status(conn, song.id, ignored=False)
    write_info(conn, cfg.library_dir, get_song(conn, song.id))
    # Last, so a run cut short anywhere above just does this song again.
    update_song(conn, song.id, autochords_mtime=song.audio_mtime)
