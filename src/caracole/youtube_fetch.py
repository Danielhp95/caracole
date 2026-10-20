"""YouTube in the nightly run: the audio of each song nobody has charted, for auto-chords.

A song is due when it is on the to-do page's list of songs with no human sheet
(``todo.songs_to_buy``: UG and LaCuerda have nothing, nothing is still to come, and no
purchase is linked), when it isn't ignored, and when its search didn't find nothing in
the last 30 days. A video pasted under ``[youtube]`` in overrides.toml is used instead of
a search, also for a song whose search found nothing; one pasted for a song whose audio
came from another video replaces it; "none" never takes the song's audio from YouTube,
and lets go of any it has. Newest first, as far as the budget goes.

For each, yt-dlp (youtube.py) searches ``ytsearch8:<artist> <title>`` and ``choose``
picks the video, or the pasted or earlier pick is taken; the download goes to a folder of
its own under ``cache_dir/youtube/``, then to ``<song id>-<video id>.m4a`` there, and the
song's ``audio_path`` points at it, as at a purchase. The synced library never holds the
audio: it is bulky, and it is caracole's. ``caracole autochords`` (its unit, after the
nightly run) works out the chords from it as from a purchase, and a purchase linked
later (music.py) takes its place, as a human sheet found later takes the auto sheet's.

What was picked is kept in kv ``youtube:<song id>`` (``Record``): the video (id, title,
channel, URL) for the to-do page, index.html and the auto sheet, and why a song waits.

Errors are never misses. Only a search that answered without a video that fits makes a
song a miss, asked about again after 30 days. A video YouTube won't give without a login
(``VideoUnavailable``) is passed over for the next search's pick; a pasted one waits for
another paste. A block propagates and a spent budget ends the pass; any other error
leaves the song for the next run, after the songs whose last try didn't fail. A video
whose download fails ``GIVE_UP_AFTER`` times, the network aside, is given up as one
YouTube won't give: the next run searches again, or waits for another paste.

The route is off, and nothing is asked of YouTube, without auto-chords: this caracole
must have torch, librosa and beat_this, both model files, and yt-dlp (``route_problem``).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from caracole.config import Config
from caracole.db import kv_get_json, kv_set_json
from caracole.health import get_state, is_cooling
from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
from caracole.lyrics import song_lyrics
from caracole.overrides import Overrides
from caracole.songs import Song, get_song, list_songs, update_song
from caracole.youtube import PROVIDER, Video, VideoUnavailable, YtDlp, choose, search_query

log = logging.getLogger(__name__)

RECORD_PREFIX = "youtube:"  # + song id, in songs._PER_SONG_KV
AUDIO_FOLDER = "youtube"  # in cache_dir
RECHECK_AFTER = timedelta(days=30)  # a song whose search found nothing that fits
GIVE_UP_AFTER = 3  # downloads of one video that failed, the network aside, before it is given up
# yt-dlp's words for a network that failed, rather than the video: no count against it.
_NETWORK = re.compile(r"\[Errno|Temporary failure|timed out|Connection (?:reset|refused|aborted)|Network is unreachable"
                      r"|Remote end closed|HTTP Error 5\d\d", re.IGNORECASE)
_PART_PREFIX = ".part-"  # a download's own folder, until its file is in place
HUMAN_SHEET, AUTO_SHEET = "sheet.txt", "sheet (auto).txt"

# Where a song without a human sheet stands, for the to-do page and index.html.
QUEUED = "queued"  # due: the next run looks for it, within its budget
BLOCKED = "blocked"  # due, but YouTube is cooling down after a block
DOWNLOADED = "downloaded"  # its audio is here: auto-chords is next
CHORDS = "chords"  # its auto sheet is made from this audio
MISSING = "missing"  # the search found no video that fits, lately
UNUSABLE = "unusable"  # the pasted video can't be had without a login
DECLINED = "declined"  # [youtube] says "none"

# What one song's turn came to; GAVE_UP and "error" come with an error.
DOWNLOADED_NOW, MISSED, PASSED_OVER, GAVE_UP = "downloaded", "missing", "unavailable", "gave up"


class DownloadsFailed(ProviderError):
    """The video's download failed ``GIVE_UP_AFTER`` times, the network aside: a searched video
    is passed over for the next search's pick, a pasted one waits for another paste. An error
    all the same, never a miss."""


def autochords_missing() -> list[str]:
    """The auto-chords packages this Python can't import; nothing is imported to find out."""
    from caracole.commands.autochords import missing_packages

    return missing_packages()


def route_problem(cfg: Config) -> str | None:
    """Why caracole takes no song's audio from YouTube here, or None when it does.

    Off with ``[providers.youtube] enabled = false``, and without what makes chords of
    the audio: a download auto-chords can't use is no use to anyone.
    """
    if not cfg.provider(PROVIDER).enabled:
        return f"turned off ([providers.{PROVIDER}] enabled = false)"
    missing = autochords_missing()
    if missing:
        return (f"this caracole was built without auto-chords (missing: {', '.join(missing)}), so it has nothing "
                "to make of the audio")
    for what, path, verb in (("BTC weights", cfg.autochords.btc_weights, "aren't"),
                             ("beat_this checkpoint", cfg.autochords.beat_checkpoint, "isn't")):
        if path is None:
            return f"auto-chords has no {what} configured"
        if not path.is_file():
            return f"auto-chords' {what} {verb} there ({path})"
    if shutil.which(cfg.ytdlp_bin) is None:
        return f"yt-dlp isn't there ({cfg.ytdlp_bin})"
    return None


def audio_dir(cfg: Config) -> Path:
    return cfg.cache_dir / AUDIO_FOLDER


# --- what is kept for a song ---------------------------------------------------------------------------


@dataclass
class Record:
    """kv ``youtube:<song id>``: the video picked or pasted (``source``), the file its audio
    went to, when its search last found nothing, the videos passed over, the last error,
    a pasted video that can't be had, and how many downloads of each video failed (the
    network aside) since it last came."""

    video: Video | None = None
    source: str | None = None  # "search" or "pasted"
    audio: str | None = None
    downloaded_at: str | None = None
    missing_at: str | None = None
    query: str | None = None
    skip: list[str] = field(default_factory=list)
    error: str | None = None
    error_at: str | None = None
    unusable: str | None = None
    unusable_reason: str | None = None
    failures: dict[str, int] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"video": self.video.as_json() if self.video else None, "source": self.source,
                               "audio": self.audio, "downloaded_at": self.downloaded_at, "query": self.query,
                               "skip": self.skip, "error": self.error, "error_at": self.error_at,
                               "unusable": self.unusable, "unusable_reason": self.unusable_reason,
                               "failures": self.failures}
        if self.missing_at:
            out["missing_at"] = self.missing_at
        return out


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def load_record(conn: sqlite3.Connection, song_id: int) -> Record:
    raw = kv_get_json(conn, f"{RECORD_PREFIX}{song_id}")
    if not isinstance(raw, dict):
        return Record()
    skip, failures = raw.get("skip"), raw.get("failures")
    return Record(
        video=Video.from_json(raw.get("video")), source=_text(raw.get("source")), audio=_text(raw.get("audio")),
        downloaded_at=_text(raw.get("downloaded_at")), missing_at=_text(raw.get("missing_at")),
        query=_text(raw.get("query")), skip=[s for s in skip if isinstance(s, str)] if isinstance(skip, list) else [],
        error=_text(raw.get("error")), error_at=_text(raw.get("error_at")), unusable=_text(raw.get("unusable")),
        unusable_reason=_text(raw.get("unusable_reason")),
        failures={k: n for k, n in failures.items() if isinstance(k, str) and isinstance(n, int)}
        if isinstance(failures, dict) else {},
    )


def _save(conn: sqlite3.Connection, song_id: int, record: Record) -> None:
    kv_set_json(conn, f"{RECORD_PREFIX}{song_id}", record.as_json())


def _own_audio(song: Song, record: Record) -> bool:
    """Whether the song's linked audio is the file YouTube gave it."""
    return bool(record.audio) and song.audio_path == record.audio


def youtube_audio(conn: sqlite3.Connection, song: Song) -> Video | None:
    """The video the song's linked audio came from, when it came from YouTube; None for a purchase."""
    record = load_record(conn, song.id)
    return record.video if _own_audio(song, record) else None


def videos_by_audio(conn: sqlite3.Connection) -> dict[str, Video]:
    """Each file of audio YouTube gave, and the video it came from."""
    found = {}
    for row in conn.execute("SELECT key FROM kv WHERE key LIKE ?", (f"{RECORD_PREFIX}%",)):
        song_id = row[0].removeprefix(RECORD_PREFIX)
        if song_id.isdigit():
            record = load_record(conn, int(song_id))
            if record.audio and record.video is not None:
                found[record.audio] = record.video
    return found


def _kept(conn: sqlite3.Connection, song_id: int, name: str) -> bool:
    return conn.execute("SELECT 1 FROM files WHERE song_id = ? AND name = ? LIMIT 1", (song_id, name)).fetchone() is not None


# --- which songs -------------------------------------------------------------------------------------


def _ignored(song: Song, overrides: Overrides) -> bool:
    return song.status == "ignored" or song.key in overrides.ignore


def _declined(song: Song, overrides: Overrides) -> bool:
    return song.key in overrides.youtube and overrides.youtube[song.key] is None


def _recent(stamp: str | None, now: datetime) -> bool:
    when = _parse(stamp)
    return when is not None and when > now - RECHECK_AFTER


def _to_buy(conn: sqlite3.Connection, songs: list[Song], overrides: Overrides, now: datetime) -> list[Song]:
    from caracole.todo import songs_to_buy  # it shows what this module keeps

    return songs_to_buy(conn, songs, overrides, now)[0]


def songs_for_youtube(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime) -> list[Song]:
    """The songs due for their audio from YouTube, newest first, those whose last try failed
    after the others, so they never hold up the rest (see the module docstring)."""
    now = _utc(now)
    songs = list_songs(conn)
    buy = {s.id for s in _to_buy(conn, songs, overrides, now)}
    due: list[Song] = []
    failed: set[int] = set()
    for song in songs:
        if _ignored(song, overrides) or _declined(song, overrides):
            continue
        record = load_record(conn, song.id)
        if record.error:
            failed.add(song.id)
        pasted = overrides.youtube.get(song.key)
        if _own_audio(song, record):
            if (pasted and (record.video is None or pasted != record.video.id) and record.unusable != pasted
                    and not _kept(conn, song.id, HUMAN_SHEET)):
                due.append(song)
        elif song.id not in buy:
            continue
        elif pasted:
            if record.unusable != pasted:
                due.append(song)
        elif not _recent(record.missing_at, now):
            due.append(song)
    return sorted(due, key=lambda s: s.id in failed)  # stable: newest first within each


def expected_seconds(song: Song) -> float | None:
    """How long the song is: its own duration, else LRCLIB's."""
    if song.duration_ms:
        return song.duration_ms / 1000
    try:
        lyrics = song_lyrics(song)
    except (TypeError, ValueError):  # stored lyrics that can't be read: no duration
        return None
    return lyrics.duration if lyrics is not None and lyrics.duration else None


# --- a pass -------------------------------------------------------------------------------------------


@dataclass
class YouTubeStats:
    """What one pass did: songs ``tried`` (errors included), audio ``downloaded``, searches that
    found nothing (``missing``), videos ``unavailable``, and the songs an error left, with it."""

    tried: int = 0
    downloaded: int = 0
    missing: int = 0
    unavailable: int = 0
    errors: int = 0
    budget_exhausted: bool = False
    failures: list[tuple[Song, ProviderError]] = field(default_factory=list)


def youtube_pass(
    conn: sqlite3.Connection,
    runner: YtDlp,
    cfg: Config,
    now: datetime,
    *,
    overrides: Overrides,
    songs: list[Song] | None = None,
    on_song: Callable[[Song, str, Record], None] | None = None,
) -> YouTubeStats:
    """Take the audio of the due songs (or of ``songs``) from YouTube; see the module docstring.

    ``on_song`` hears each song's outcome (``DOWNLOADED_NOW``, ``MISSED``, ``PASSED_OVER``,
    ``GAVE_UP`` or "error") with its record. ``ProviderBlocked`` propagates; ``BudgetExhausted`` ends
    the pass (``budget_exhausted``); any other ``ProviderError`` leaves its song for the
    next run. Before any of it, audio no song needs any more goes (``tidy``).
    """
    now = _utc(now)
    stats = YouTubeStats()
    tidy(conn, cfg, overrides)
    for song in songs if songs is not None else songs_for_youtube(conn, cfg, overrides, now):
        try:
            outcome = _one(conn, runner, cfg, song, overrides, now)
        except ProviderBlocked:
            raise
        except BudgetExhausted:
            stats.budget_exhausted = True
            break
        except ProviderError as e:
            stats.tried += 1
            stats.errors += 1
            stats.failures.append((song, e))
            record = load_record(conn, song.id)
            record.error, record.error_at = e.message or str(e), _iso(now)
            _save(conn, song.id, record)
            log.warning("YouTube for %s: %s", song.display, e)
            if on_song is not None:
                on_song(song, GAVE_UP if isinstance(e, DownloadsFailed) else "error", record)
            continue
        stats.tried += 1
        stats.downloaded += outcome == DOWNLOADED_NOW
        stats.missing += outcome == MISSED
        stats.unavailable += outcome == PASSED_OVER
        if on_song is not None:
            on_song(song, outcome, load_record(conn, song.id))
    return stats


def _one(conn: sqlite3.Connection, runner: YtDlp, cfg: Config, song: Song, overrides: Overrides,
         now: datetime) -> str:
    stamp = _iso(now)
    record = load_record(conn, song.id)
    pasted = overrides.youtube.get(song.key)
    if pasted:
        video, source = (record.video if record.video and record.video.id == pasted else Video(pasted)), "pasted"
    elif record.video is not None and record.source == "search" and not _own_audio(song, record) \
            and record.video.id not in record.skip:
        video, source = record.video, "search"  # picked before a spent budget stopped its download
    else:
        query = search_query(song)
        picked = choose(song, runner.search(query), expected_seconds(song), skip=record.skip)
        record.query, record.error, record.error_at = query, None, None
        if picked is None:
            record.missing_at = stamp
            _save(conn, song.id, record)
            log.info("YouTube for %s: no video fits (%s)", song.display, query)
            return MISSED
        video, source = picked, "search"
        record.video, record.source, record.missing_at = picked, source, None
        _save(conn, song.id, record)
    try:
        path, got = _download(runner, cfg, song, video)
    except VideoUnavailable as e:
        if source == "pasted":
            record.unusable, record.unusable_reason = video.id, e.message or str(e)
        else:
            record.skip.append(video.id)
            record.video = record.source = None
        record.error = record.error_at = None
        record.failures.pop(video.id, None)
        _save(conn, song.id, record)
        log.info("YouTube for %s: %s can't be had (%s)", song.display, video.url, e.message)
        return PASSED_OVER
    except ProviderBlocked:
        raise
    except ProviderError as e:
        given_up = _count_failure(record, video, source, e)
        _save(conn, song.id, record)
        if given_up is not None:
            raise given_up from e
        raise
    old = record.audio if _own_audio(song, record) else None
    update_song(conn, song.id, audio_path=str(path), audio_mtime=path.stat().st_mtime)
    record.video = Video(video.id, got.title or video.title, got.channel or video.channel,
                         got.duration if got.duration is not None else video.duration)
    record.source, record.audio, record.downloaded_at = source, str(path), stamp
    record.error = record.error_at = record.unusable = record.unusable_reason = None
    record.failures.pop(video.id, None)
    _save(conn, song.id, record)
    if old and old != str(path):
        _delete(Path(old))
    log.info("YouTube for %s: %s (%s, %s) downloaded", song.display, record.video.url, record.video.title,
             record.video.channel)
    return DOWNLOADED_NOW


def _count_failure(record: Record, video: Video, source: str, error: ProviderError) -> DownloadsFailed | None:
    """Count a failed download against its video, unless the network failed; at ``GIVE_UP_AFTER``,
    give the video up (a searched one goes to ``skip``, and the next run searches again; a pasted
    one is unusable) and return the error that says so."""
    reason = error.message or str(error)
    if _NETWORK.search(reason):
        return None
    failed = record.failures[video.id] = record.failures.get(video.id, 0) + 1
    if failed < GIVE_UP_AFTER:
        return None
    del record.failures[video.id]
    if source == "pasted":
        record.unusable, record.unusable_reason = video.id, f"its download failed {failed} times: {reason}"
        then = "it waits for another video under [youtube]"
    else:
        record.skip.append(video.id)
        record.video = record.source = None
        then = "the next run picks another"
    return DownloadsFailed(PROVIDER, error.url, error.status,
                           f"{reason} ({video.url} failed {failed} times: {then})")


def _download(runner: YtDlp, cfg: Config, song: Song, video: Video) -> tuple[Path, Video]:
    """The video's audio, in place as ``<song id>-<video id>.<ext>``: it comes into a folder of
    its own, so a download cut short is never anybody's audio."""
    folder_root = audio_dir(cfg)
    folder_root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=f"{_PART_PREFIX}{song.id}-", dir=folder_root))
    try:
        got = runner.download(video.id, folder)
        path = folder_root / f"{song.id}-{video.id}{got.path.suffix.lower()}"
        os.replace(got.path, path)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return path, got.video


def tidy(conn: sqlite3.Connection, cfg: Config, overrides: Overrides) -> bool:
    """Let go of YouTube audio no song needs: a song whose ``[youtube]`` says "none", or that
    has a human sheet now, is unlinked from it, and a file no song's audio is any more (a
    purchase took its place) goes, with any download a stopped caracole left half-done and
    any file no song or record names (a song merged into another took its record).

    A song whose file is gone from the cache is unlinked from it too, as the scan unlinks a
    purchase that is gone: one with no auto sheet yet is due again, for the video it had.

    Whether a song or its record changed, which the pages show."""
    changed = False
    root = audio_dir(cfg)
    if root.is_dir():
        for leftover in root.glob(f"{_PART_PREFIX}*"):
            shutil.rmtree(leftover, ignore_errors=True)  # under caracole's lock: no other download runs
    named: set[str] = set()
    for song in list_songs(conn):
        named.add(Path(song.audio_path).name if song.audio_path else "")
        record = load_record(conn, song.id)
        if not record.audio:
            continue
        if _own_audio(song, record) and (_declined(song, overrides) or _kept(conn, song.id, HUMAN_SHEET)
                                         or not Path(record.audio).is_file()):
            update_song(conn, song.id, audio_path=None, audio_mtime=None)
            song = get_song(conn, song.id)
        if not _own_audio(song, record):
            _delete(Path(record.audio))
            record.audio = None
            _save(conn, song.id, record)
            changed = True
        else:
            named.add(Path(record.audio).name)
    if root.is_dir():
        for path in root.iterdir():
            if path.name not in named and not path.name.startswith(_PART_PREFIX) and not path.is_dir():
                _delete(path)
    return changed


def _delete(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Couldn't delete %s: %s", path, e)


# --- where each song stands --------------------------------------------------------------------------


@dataclass(frozen=True)
class SongState:
    """``video`` is the one the state is about (picked, pasted, downloaded); ``audio_from``, for a
    pasted video that can't be had, the one the song's audio still comes from, if any."""

    state: str
    video: Video | None = None
    detail: str | None = None
    audio_from: Video | None = None


def song_state(conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides, now: datetime) -> SongState:
    """Where a song with no human sheet stands on the YouTube route (``QUEUED`` and the rest).

    A pasted video that can't be had is ``UNUSABLE`` even when the song has audio from
    another video: that one stays, and the paste waits for another."""
    now = _utc(now)
    record = load_record(conn, song.id)
    if _declined(song, overrides):
        return SongState(DECLINED)
    pasted = overrides.youtube.get(song.key)
    own = _own_audio(song, record)
    if pasted and record.unusable == pasted:
        return SongState(UNUSABLE, Video(pasted), record.unusable_reason, record.video if own else None)
    if own:
        made = _kept(conn, song.id, AUTO_SHEET) and song.autochords_mtime == song.audio_mtime
        return SongState(CHORDS if made else DOWNLOADED, record.video)
    if not pasted and _recent(record.missing_at, now):
        again = _parse(record.missing_at) + RECHECK_AFTER
        return SongState(MISSING, None, f"asked again from {again.strftime('%Y-%m-%d')}")
    video = Video(pasted) if pasted and not (record.video and record.video.id == pasted) else record.video
    if is_cooling(conn, PROVIDER, now):
        until = get_state(conn, PROVIDER).cooldown_until
        return SongState(BLOCKED, video, f"until {until.strftime('%Y-%m-%d %H:%M UTC')}" if until else None)
    return SongState(QUEUED, video, record.error)


def song_states(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime) -> dict[int, SongState]:
    """Every song on the YouTube route's list, newest first: the songs with no human sheet the
    to-do page lists (``todo.songs_to_buy``), and those whose audio YouTube gave, until a human
    sheet turns up."""
    songs = list_songs(conn)
    listed = {s.id for s in _to_buy(conn, songs, overrides, now)}
    out = {}
    for song in songs:
        youtube_gave = (not _ignored(song, overrides) and _own_audio(song, load_record(conn, song.id))
                        and not _kept(conn, song.id, HUMAN_SHEET))
        if song.id in listed or youtube_gave:
            out[song.id] = song_state(conn, cfg, song, overrides, now)
    return out


# --- small helpers -------------------------------------------------------------------------------------------


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str | None) -> datetime | None:
    try:
        return _utc(datetime.fromisoformat(value)) if value else None
    except ValueError:
        return None
