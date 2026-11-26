"""Once, the auto sheets made from an MP3 whose length was guessed wrong are made again, with no one asking.

Before mpeg_frames.py, a VBR MP3 whose first frame names no length (no Xing/Info or VBRI header: a recorder's) was
as long as its first frame's bitrate guessed: libsndfile decoded the chords' audio only that far, the sheet stopping
there, and mutagen's length (read_audio's, audio_store's) was the same guess, too short or too long, which LRCLIB was
asked with (the line ``caracole audio`` wrote for a file it was given) and timed lyrics were fitted to.

``remeasure_once``, at the start of the first auto-chords pass after that (``autochords_pending``), goes through every
song once, kv ``autochords:remeasured`` its stamp after: a song with an auto sheet and no human one, not ignored,
whose audio is such an MP3 whose guess is more than ``audio.DISAGREES_S`` off its frames' length (``mpeg_frames.count``:
its ``guessed``, every reader's guess, against its ``seconds``), is due again (``autochords_mtime`` cleared, so
``run._skip_reason`` finds its audio new), the chords made over the whole of it, the lyrics fitted to its real length.
Its wanted.txt line is corrected only where caracole wrote the guess there itself (``wanted.retime_wanted``: a line
exactly as caracole writes one, its length the guess to the second), the song's record with it, as the next sync
would make it; and only then, LRCLIB having been asked with the wrong length, its lyrics, where none were found, are
asked again at the next lyrics pass (``lyrics_at`` cleared, a miss's re-check due; Megalobiz's miss forgotten, as it
is asked with the length too; AZLyrics asks with none). Lyrics found are kept: their timing is fitted to the real
length as the sheet is made again (run.py ``_synced_for``: as they are, shifted, else the plain ones). Each song made
due is logged, with both lengths; a song with a human sheet, or a file every reader agrees on, is left as it is.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from caracole.autochords.audio import DISAGREES_S
from caracole.config import Config
from caracole.db import kv_delete, kv_get, kv_set, savepoint
from caracole.library import kept_files
from caracole.mpeg_frames import count
from caracole.overrides import Overrides
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, update_song
from caracole.wanted import format_duration, retime_wanted

log = logging.getLogger(__name__)

KEY = "autochords:remeasured"  # kv: when every song's MP3 was measured by its frames, once


def remeasure_once(conn: sqlite3.Connection, cfg: Config, songs: Iterable[Song], overrides: Overrides,
                   stamp: str) -> list[int]:
    """The ids of the songs made due again (the module docstring), once ever; [] after the first time."""
    if kv_get(conn, KEY) is not None:
        return []
    due = [song.id for song in songs if _remeasured(conn, cfg, song, overrides)]
    kv_set(conn, KEY, stamp)
    return due


def _remeasured(conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides) -> bool:
    if not song.audio_path or song.status == "ignored" or song.key in overrides.ignore:
        return False
    kept = {f.name for f in kept_files(conn, song.id)}
    if HUMAN_SHEET in kept or AUTO_SHEET not in kept:
        return False
    try:
        found = count(Path(song.audio_path))
    except OSError:  # gone or unreadable: the pass says so in its own turn
        return False
    if found is None or abs(found.guessed - found.seconds) <= DISAGREES_S:
        return False
    with savepoint(conn, "remeasure"):
        update_song(conn, song.id, autochords_mtime=None)
        retimed = _retimed(conn, cfg, song, found.guessed, found.seconds)
    log.info("%s: its MP3 is %s long, not the %s its length was guessed at (it names none): its auto sheet is "
             "made again over the whole of it%s.", song.display, format_duration(round(found.seconds * 1000)),
             format_duration(round(found.guessed * 1000)),
             ", its line in wanted.txt corrected" if retimed else "")
    return True


def _retimed(conn: sqlite3.Connection, cfg: Config, song: Song, guessed: float, seconds: float) -> bool:
    """The song's wanted.txt line and record corrected where caracole wrote the guess, and its missing lyrics asked
    again; whether they were."""
    from caracole.megalobiz_fetch import CHECKED  # here: the pass needs no site's module otherwise

    was = round(guessed * 1000)
    if song.duration_ms is None or song.duration_ms != (was + 500) // 1000 * 1000:
        return False
    try:
        if not retime_wanted(cfg.wanted_file, song.key, was, round(seconds * 1000)):
            return False
    except OSError as e:
        log.warning("%s: its length in wanted.txt couldn't be corrected (%s).", song.display, e)
        return False
    fields: dict[str, object] = {"duration_ms": (round(seconds * 1000) + 500) // 1000 * 1000}
    if song.lyrics_status == "missing":  # asked with the wrong length: asked again at the next lyrics pass
        fields["lyrics_at"] = None
        kv_delete(conn, f"{CHECKED}{song.id}")
    update_song(conn, song.id, **fields)
    return True
