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
  the song's lyrics arrived;
- that file hasn't already failed.

For each song due, BTC recognizes the chords, beat_this finds the beats, and
``merge.build_sheet`` lays the chords out over LRCLIB's lyrics: the synced ones
when their duration matches the audio's within 2 s (otherwise their timings
belong to another cut of the song), else the plain ones, else none (a chord
chart alone). The sheet is kept with a ``versions`` row of provider ``auto``,
and the song becomes found.

Two kinds of failure are told apart, because only one is the purchase's:

- **A file auto-chords can't read**, such as one that won't decode, fails that
  song alone. kv ``autochords:failed:<song id>`` keeps the file's path and
  mtime, so it isn't decoded again every night: the song is tried again once
  its file changes (a new download, a converted copy), and the record is
  dropped once the song's file changes or goes.
- **A setup that can't work** blames no purchase: model files missing or
  unusable, models that fail on a generated test tone (a sandbox that stops
  them, a checkpoint that won't load), or a sheet that can't be kept in the
  library. The songs stay due, and ``caracole autochords`` exits 1.

Each run is recorded in kv ``autochords:status`` for the to-do page:
``{"at", "generated", "skipped", "failed": [{"song", "error", "audio"}]}``,
where ``failed`` lists every purchase whose current file can't be read.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import sys
import tempfile
import wave
from array import array
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from caracole.autochords.beats import detect_beats
from caracole.autochords.btc import BTCRecognizer
from caracole.autochords.merge import NO_CHORD, ChordSegment, build_sheet
from caracole.config import Config
from caracole.db import kv_delete, kv_get_json, kv_set_json
from caracole.keys import estimate_key
from caracole.library import keep_file, kept_files, write_info
from caracole.lyrics import Lyrics, song_lyrics
from caracole.music import read_audio
from caracole.overrides import Overrides, load_overrides
from caracole.songs import Song, get_song, list_songs, refresh_status, update_song
from caracole.versions import get_version, upsert_version
from caracole.youtube import Video
from caracole.youtube_fetch import youtube_audio

log = logging.getLogger(__name__)

AUTO_SHEET = "sheet (auto).txt"
HUMAN_SHEET = "sheet.txt"
PROVIDER = "auto"
MODEL = "btc_large_voca"
SYNC_TOLERANCE_S = 2.0  # LRCLIB's own tolerance when it matches a duration
STATUS_KEY = "autochords:status"  # kv: the last run, for the to-do page
ERROR_CHARS = 300  # an error as the to-do page lists it: one line, if a long one
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
    """

    generated: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[Failure] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One line for the journal or a notification: "1 generated, 4 skipped, 0 failed"."""
        return f"{self.generated} generated, {self.skipped} skipped, {self.failed} failed"


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
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if overrides is None:
        overrides = load_overrides(cfg.overrides_file)
    stats = AutoStats()
    models: tuple[Recognizer, BeatsFn] | None = None
    unavailable = False
    handed = False
    for n, listed in enumerate(list_songs(conn)):
        if n and between is not None and between():
            handed = True
            overrides = _overrides_again(cfg, overrides)
        song = listed
        if handed:
            try:
                song = get_song(conn, listed.id)
            except KeyError:  # merged into another song meanwhile
                continue
        failure = _known_failure(conn, song)  # first, so a failure goes when its file does
        if not song.audio_path:
            continue
        try:
            reason = _skip_reason(conn, song, overrides)
        except Exception as e:  # noqa: BLE001 - a song's bad data must not stop the others
            _error(stats, song, e)
            continue
        if reason is not None:
            log.debug("%s: skipped (%s)", song.display, reason)
            stats.skipped += 1
            continue
        if failure is not None:
            log.info(
                "%s: not tried again until %s changes (%s)",
                song.display,
                song.audio_path,
                failure.error,
            )
            stats.failed += 1
            stats.failures.append(failure)
            continue
        if models is None and not unavailable:
            try:
                models = _models(cfg, recognizer, beats_fn)
            except ModelsUnavailable as e:
                unavailable = True
                for message in e.args:
                    stats.errors.append(message)
                    log.error("auto-chords cannot run: %s", message)
        if models is None:
            stats.failed += 1
            continue
        video = youtube_audio(conn, song)  # audio youtube_fetch.py took, rather than a purchase
        try:
            text, used, key = _make_sheet(song, *models, source=_from_youtube(video))
        except Exception as e:  # noqa: BLE001 - one file's problem must not stop the others
            stats.failed += 1
            stats.failures.append(_unreadable(conn, song, e, stamp))
            continue
        try:
            _keep(conn, cfg, song, text, used, key, stamp, video=video)
        except Exception as e:  # noqa: BLE001 - the library's problem, not the purchase's
            _error(stats, song, e)
            continue
        stats.generated += 1
        log.info("%s: auto sheet written (%s lyrics)", song.display, used)
    kv_set_json(
        conn,
        STATUS_KEY,
        {
            "at": stamp,
            "generated": stats.generated,
            "skipped": stats.skipped,
            "failed": [asdict(f) for f in stats.failures],
        },
    )
    return stats


def _failed_key(song_id: int) -> str:
    """kv: the audio file of the song that couldn't be read (written and read only here)."""
    return f"autochords:failed:{song_id}"


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
    if get_version(conn, auto.version_id).raw.get("lyrics") == "none" and _sung_lyrics(song):
        return None  # made before LRCLIB answered: once more, now with the words
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
    device = cfg.autochords.device
    return lambda path: detect_beats(path, checkpoint, device=device)


def _sung_lyrics(song: Song) -> Lyrics | None:
    """The song's stored lyrics, when they have words (an instrumental has none)."""
    lyrics = song_lyrics(song)
    return lyrics if lyrics is not None and lyrics.has_lyrics else None


def _synced_for(lyrics: Lyrics | None, audio: Path) -> str | None:
    """The synced lyrics, if their timings fit this audio file: the durations agree within 2 s."""
    if lyrics is None or not lyrics.synced or lyrics.duration is None:
        return None
    duration = read_audio(audio).duration_s
    if duration is None or abs(lyrics.duration - duration) > SYNC_TOLERANCE_S:
        return None
    return lyrics.synced


def _from_youtube(video: Video | None) -> str | None:
    """The sheet's line for audio taken from YouTube: which video it was."""
    if video is None:
        return None
    named = f"{video.title} ({video.channel})" if video.channel else video.title or video.id
    return f"Audio from YouTube: {named}, {video.url}"


def _make_sheet(
    song: Song, recognizer: Recognizer, beats_fn: BeatsFn, *, source: str | None = None
) -> tuple[str, str, str | None]:
    """One song's auto sheet, which lyrics it used, and the key of the chords heard (None when
    they fit no key); all of it comes from its audio file. ``source`` says where that came
    from, when it wasn't a purchase.

    The key is estimated from the chords as recognized, each weighed by how long it sounds,
    before they are snapped to beats and laid out.
    """
    audio = Path(song.audio_path or "")
    segments = recognizer.recognize(audio)
    key = estimate_key((s.label, s.end - s.start) for s in segments if s.label != NO_CHORD)
    beats, downbeats = beats_fn(audio)
    lyrics = _sung_lyrics(song)
    synced = _synced_for(lyrics, audio)
    plain = lyrics.plain if lyrics is not None else None
    text = build_sheet(
        segments,
        title=song.title,
        artist=song.artist,
        synced=synced,
        plain=plain,
        beats=beats,
        downbeats=downbeats,
        source=source,
    )
    return text, "synced" if synced else "plain" if plain else "none", key


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
) -> None:
    """Keep one song's auto sheet, under a version of provider ``auto``; the song becomes found.

    The key heard goes into the version's ``raw``, for ``keys.song_key``. Audio from YouTube
    (``video``) gives the version the video's address, so info.json names it, and its fields.
    """
    audio = Path(song.audio_path or "")
    raw: dict[str, object] = {"audio": song.audio_path, "model": MODEL, "lyrics": used}
    if key is not None:
        raw["key"] = key
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
