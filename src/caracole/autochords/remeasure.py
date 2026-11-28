"""Once, what was made from an MP3 whose length was guessed wrong is made again, with no one asking.

Before mpeg_frames.py, a VBR MP3 whose first frame names no length (no Xing/Info or VBRI header: a recorder's) was
as long as its first frame's bitrate guessed: libsndfile decoded the models' audio only that far (BTC's chords, and
the mix's loudness the words were kept within), the sheet stopping there, and mutagen's length (read_audio's,
audio_store's) was the same guess, too short or too long, which LRCLIB was asked with (the line ``caracole audio``
wrote for a file it was given) and timed lyrics were fitted to.

``remeasure_once``, at the start of the first bulk auto-chords pass after that (``caracole autochords``, the nightly
pass; never a staged job about one song), goes through every song once, kv ``autochords:remeasured`` its stamp after.
A song with no human sheet, not ignored, whose audio is such an MP3 whose guess is more than ``audio.DISAGREES_S`` off
its frames' length (``mpeg_frames.count``: its ``guessed``, every reader's guess, against its ``seconds``):

- its auto sheet, if it has one this caracole made, is due again (``autochords_mtime`` cleared, so
  ``run._skip_reason`` finds its audio new), the chords made over the whole of it, the lyrics fitted to its real
  length; one another caracole made (sheet_lyrics.py ``auto_made_elsewhere``) wasn't heard from this file, is never
  made again here by itself (R3, ``run.MADE_ELSEWHERE``), and is neither touched nor said made again;
- read short (the guess below its length), its transcript (kv ``transcript:``) is dropped, and caracole's verdict that
  nothing is sung (``transcribe:none:`` by "caracole"): both heard from the part read, words.py keeping no word past
  the mix's end. The song is offered its words again (the nightly pass hears it within its cap; its card offers
  Transcribe the lyrics), and its sheet meanwhile is made chords-only or over a site's lyrics, as ever. The owner's
  word that it isn't sung (``by`` "you") stands; so do a failed hearing (``transcribe:failed:``, its setup's, the
  stem being whole and never shorter than a short mix) and Whisper's refusal (``transcribe:unreadable:``: Whisper reads
  through the ffmpeg program, whole);
- its wanted.txt line is corrected only where it is exactly as caracole writes one with the guess
  (``wanted.retime_wanted``), the song's record with it, as the next sync would make it; and only then, LRCLIB having
  been asked with the wrong length, its lyrics, where none were found, are asked again at the next lyrics pass
  (``lyrics_at`` cleared, a miss's re-check due; Megalobiz's miss forgotten, as it is asked with the length too;
  AZLyrics asks with none). Lyrics found are kept: their timing is fitted to the real length as the sheet is made
  again (sheet.py ``synced_for``: as they are, shifted, else the plain ones).

Each song is a WARNING naming both lengths and what was done, and the run's summary and the to-do page name them
(run.py ``AutoStats.remeasured``); a song with a human sheet, or a file every reader agrees on, is left as it is.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from caracole.autochords.audio import DISAGREES_S
from caracole.autochords.sheet_lyrics import auto_made_elsewhere
from caracole.config import Config
from caracole.db import kv_delete, kv_get, kv_get_json, kv_set, savepoint
from caracole.library import kept_files
from caracole.mpeg_frames import count
from caracole.overrides import Overrides
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, update_song
from caracole.wanted import format_duration, retime_wanted

log = logging.getLogger(__name__)

KEY = "autochords:remeasured"  # kv: when every song's MP3 was measured by its frames, once


def remeasure_once(conn: sqlite3.Connection, cfg: Config, songs: Iterable[Song], overrides: Overrides,
                   stamp: str) -> list[str]:
    """The songs remeasured, each "Artist - Title" (the module docstring), once ever; [] after the first time."""
    if kv_get(conn, KEY) is not None:
        return []
    remeasured = sorted(song.display for song in songs if _remeasured(conn, cfg, song, overrides))
    kv_set(conn, KEY, stamp)
    return remeasured


def _remeasured(conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides) -> bool:
    if not song.audio_path or song.status == "ignored" or song.key in overrides.ignore:
        return False
    kept = {f.name for f in kept_files(conn, song.id)}
    if HUMAN_SHEET in kept:
        return False
    try:
        found = count(Path(song.audio_path))
    except OSError:  # gone or unreadable: the pass says so in its own turn
        return False
    if found is None or abs(found.guessed - found.seconds) <= DISAGREES_S:
        return False
    done: list[str] = []
    with savepoint(conn, "remeasure"):
        if AUTO_SHEET in kept and not auto_made_elsewhere(conn, song.id):  # another caracole's: never made here by
            update_song(conn, song.id, autochords_mtime=None)              # itself (R3, run.py ``MADE_ELSEWHERE``)
            done.append("its auto sheet is made again over the whole of it")
        if found.guessed < found.seconds and _words_dropped(conn, song):
            done.append("its words heard from the part read are dropped, to be heard again whole")
        if _retimed(conn, cfg, song, found.guessed, found.seconds):
            done.append("its line in wanted.txt corrected")
    if not done:
        return False
    log.warning("%s: its MP3 is %s long, not the %s its length was guessed at (it names none): %s.", song.display,
                format_duration(round(found.seconds * 1000)), format_duration(round(found.guessed * 1000)),
                ", ".join(done))
    return True


def _words_dropped(conn: sqlite3.Connection, song: Song) -> bool:
    """The song's transcript, and caracole's verdict that nothing is sung, dropped: both were heard from a mix cut
    short (words.py drops every word past the mix's end); whether there was either. The owner's word that it isn't
    sung stands, and so do a failed hearing (its setup's) and Whisper's refusal (FFmpeg's read, whole)."""
    from caracole.autochords.transcript import HEARD_NOTHING, TRANSCRIPT

    dropped = False
    if kv_get(conn, f"{TRANSCRIPT}{song.id}") is not None:
        kv_delete(conn, f"{TRANSCRIPT}{song.id}")
        dropped = True
    nothing = kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")
    if nothing is not None and not (isinstance(nothing, dict) and nothing.get("by") == "you"):
        kv_delete(conn, f"{HEARD_NOTHING}{song.id}")
        dropped = True
    return dropped


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
