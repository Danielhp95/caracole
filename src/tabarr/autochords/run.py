"""Auto-chords over the library: ``sheet (auto).txt`` for songs you bought (plan §4).

``autochords_pending`` is what the ``tabarr-autochords`` unit runs, offline,
after the nightly run has linked new purchases (``music.scan_music``). A song
with linked audio is due when:

- its audio file exists;
- it has no human sheet (no kept ``sheet.txt``);
- it is not ignored;
- its audio changed since its last auto sheet, or that sheet was made before
  the song's lyrics arrived.

For each song due, BTC recognizes the chords, beat_this finds the beats, and
``merge.build_sheet`` lays the chords out over LRCLIB's lyrics: the synced ones
when their duration matches the audio's within 2 s (otherwise their timings
belong to another cut of the song), else the plain ones, else none (a chord
chart alone). The sheet is kept with a ``versions`` row of provider ``auto``,
and the song becomes found.

A failure, such as an audio file that won't decode, counts against that song
alone, which stays due for the next run. Missing or unusable model files fail
every song due, and are reported once.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from tabarr.autochords.beats import detect_beats
from tabarr.autochords.btc import BTCRecognizer
from tabarr.autochords.merge import ChordSegment, build_sheet
from tabarr.config import Config
from tabarr.library import keep_file, kept_files, write_info
from tabarr.lyrics import Lyrics, song_lyrics
from tabarr.music import read_audio
from tabarr.overrides import Overrides, load_overrides
from tabarr.songs import Song, get_song, list_songs, refresh_status, update_song
from tabarr.versions import get_version, upsert_version

log = logging.getLogger(__name__)

AUTO_SHEET = "sheet (auto).txt"
HUMAN_SHEET = "sheet.txt"
PROVIDER = "auto"
MODEL = "btc_large_voca"
SYNC_TOLERANCE_S = 2.0  # LRCLIB's own tolerance when it matches a duration


class Recognizer(Protocol):
    """Timed chords from an audio file, like ``btc.BTCRecognizer``."""

    def recognize(self, audio_path: Path | str) -> list[ChordSegment]: ...


BeatsFn = Callable[[Path], tuple[Sequence[float], Sequence[float]]]


class ModelsUnavailable(Exception):
    """The model files are not configured, not there or not usable; each arg is one reason."""


@dataclass
class AutoStats:
    """One run's outcome. Each song with linked audio counts once, in one of the three."""

    generated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One line for the journal or a notification: "1 generated, 4 skipped, 0 failed"."""
        return f"{self.generated} generated, {self.skipped} skipped, {self.failed} failed"


def autochords_pending(
    conn: sqlite3.Connection,
    cfg: Config,
    *,
    recognizer: Recognizer | None = None,
    beats_fn: BeatsFn | None = None,
    now: datetime | None = None,
    overrides: Overrides | None = None,
) -> AutoStats:
    """Generate the auto sheets that are due, and keep them in the library.

    ``recognizer`` defaults to a ``BTCRecognizer`` on ``cfg.autochords.btc_weights``,
    and ``beats_fn`` to ``detect_beats`` with ``cfg.autochords.beat_checkpoint``.
    They are set up once, when the first song turns out to be due, so a night
    with no new audio loads no model. ``overrides`` defaults to the file at
    ``cfg.overrides_file``; its ``[ignore]`` songs are skipped.
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if overrides is None:
        overrides = load_overrides(cfg.overrides_file)
    stats = AutoStats()
    models: tuple[Recognizer, BeatsFn] | None = None
    unavailable = False
    for song in list_songs(conn):
        if not song.audio_path:
            continue
        try:
            reason = _skip_reason(conn, song, overrides)
        except Exception as e:  # a song's bad data must not stop the others
            _failed(stats, song, e)
            continue
        if reason is not None:
            log.debug("%s: skipped (%s)", song.display, reason)
            stats.skipped += 1
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
        try:
            used = _generate(conn, cfg, song, *models, stamp)
        except Exception as e:  # one file's problem must not stop the others
            _failed(stats, song, e)
            continue
        stats.generated += 1
        log.info("%s: auto sheet written (%s lyrics)", song.display, used)
    return stats


def _failed(stats: AutoStats, song: Song, e: Exception) -> None:
    message = f"{type(e).__name__}: {e}"
    stats.failed += 1
    stats.errors.append(f"{song.display}: {message}")
    # Decoding and model errors are one line; anything else is likely a bug, so keep the trace.
    log.error(
        "%s: auto-chords failed on %s: %s",
        song.display,
        song.audio_path,
        message,
        exc_info=not isinstance(e, (OSError, RuntimeError, ValueError)),
    )


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

    Both defaults are tried, so ModelsUnavailable names every missing piece at once.
    """
    problems: list[str] = []
    if beats_fn is None:
        try:
            beats_fn = _default_beats(cfg)
        except ModelsUnavailable as e:
            problems += e.args
    if recognizer is None:
        try:
            recognizer = _default_recognizer(cfg)
        except ModelsUnavailable as e:
            problems += e.args
        except Exception as e:  # missing or broken weights, or torch failing to load
            problems.append(f"{type(e).__name__}: {e}")
    if problems or recognizer is None or beats_fn is None:
        raise ModelsUnavailable(*problems)
    return recognizer, beats_fn


def _unconfigured(what: str, env_var: str, key: str) -> str:
    return f"no {what} configured: set {env_var}, or {key} under [autochords] in tabarr.toml"


def _default_recognizer(cfg: Config) -> Recognizer:
    weights = cfg.autochords.btc_weights
    if weights is None:
        raise ModelsUnavailable(_unconfigured("BTC weights", "TABARR_BTC_WEIGHTS", "btc_weights"))
    return BTCRecognizer(weights, device=cfg.autochords.device)


def _default_beats(cfg: Config) -> BeatsFn:
    checkpoint = cfg.autochords.beat_checkpoint
    if checkpoint is None:
        raise ModelsUnavailable(
            _unconfigured("beat_this checkpoint", "TABARR_BEAT_CHECKPOINT", "beat_checkpoint")
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


def _generate(
    conn: sqlite3.Connection,
    cfg: Config,
    song: Song,
    recognizer: Recognizer,
    beats_fn: BeatsFn,
    stamp: str,
) -> str:
    """Write and keep one song's auto sheet; return which lyrics it used."""
    audio = Path(song.audio_path or "")
    segments = recognizer.recognize(audio)
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
    )
    used = "synced" if synced else "plain" if plain else "none"
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
        url="file://" + str(audio.absolute()),
        raw={"audio": song.audio_path, "model": MODEL, "lyrics": used},
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
    return used
