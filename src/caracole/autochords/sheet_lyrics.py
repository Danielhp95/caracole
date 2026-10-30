"""Lyrics that came after an auto sheet was made, put on it with no model.

A sheet auto-chords made of a song with no lyrics is its chart alone (version ``raw["lyrics"]`` "none"). Its chart is all
a sheet over plain lyrics adds them to (``merge.with_plain_lyrics``), so the words need neither the models nor the audio:
``render_all`` does this first, whichever way the lyrics came (LRCLIB, Megalobiz or AZLyrics; the nightly run, ``caracole
lyrics`` or a lookup), so that the song's page has them as soon as it is made again. The sheet's version then says
"plain", so timed lyrics stay what run.py's ``_skip_reason`` makes it due for: with those, the words go on here at
once and auto-chords puts each chord over its word at its next run.

Imports no model, as ``merge`` does: render.py runs in a caracole without auto-chords too.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection
from pathlib import Path

from caracole.autochords.merge import with_plain_lyrics
from caracole.config import Config
from caracole.library import SharedFolder, keep_file, kept_files, read_regular, write_info
from caracole.overrides import Overrides
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, get_song
from caracole.versions import get_version, set_raw

log = logging.getLogger(__name__)


def _wanting(conn: sqlite3.Connection, overrides: Overrides,
             only: Collection[int] | None = None) -> list[tuple[Song, str]]:
    """Each song, of ``only`` when given, whose auto sheet has no lyrics and who has some, and those lyrics: not an
    ignored one, nor one with a human sheet, which is the one its pages show. A render runs this over the library, so
    a song with no such sheet costs it nothing, and lyrics stored that can't be read are none."""
    from caracole.lyrics import song_lyrics

    rows = conn.execute(
        "SELECT f.song_id FROM files f JOIN versions v ON v.id = f.version_id "
        "WHERE f.name = ? AND json_valid(v.raw) AND json_extract(v.raw, '$.lyrics') = 'none'", (AUTO_SHEET,)
    ).fetchall()
    found = []
    for (song_id,) in rows:
        if only is not None and song_id not in only:
            continue
        song = get_song(conn, song_id)
        if song.status == "ignored" or song.key in overrides.ignore:
            continue
        try:
            lyrics = song_lyrics(song)
        except (TypeError, ValueError):
            continue
        if lyrics is None or not lyrics.has_lyrics or lyrics.instrumental:
            continue
        if not any(f.name == HUMAN_SHEET for f in kept_files(conn, song_id)):
            found.append((song, lyrics.plain))
    return found


def sheets_wanting_lyrics(conn: sqlite3.Connection, overrides: Overrides,
                          only: Collection[int] | None = None) -> list[Song]:
    """The songs whose auto sheets would take lyrics now (``lyrics_onto_sheets``)."""
    return [song for song, _ in _wanting(conn, overrides, only)]


def lyrics_onto_sheets(conn: sqlite3.Connection, cfg: Config, overrides: Overrides | None = None,
                       only: Collection[int] | None = None) -> list[Song]:
    """Put each song's lyrics on its auto sheet (``_wanting``) and return the songs that took them. A sheet
    that can't be read or written is logged and stays as it is, for the next pass or the models, and stops no other."""
    done = []
    for song, plain in _wanting(conn, overrides or Overrides(), only):
        auto = next(f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET)
        try:
            text = read_regular(Path(cfg.library_dir) / auto.path).decode("utf-8")
            keep_file(conn, cfg.library_dir, song=song, version_id=auto.version_id, name=AUTO_SHEET,
                      data=with_plain_lyrics(text, plain).encode("utf-8"), rank=auto.kept_rank)
        except FileNotFoundError:
            log.info("%s's auto sheet is gone from its folder: auto-chords makes it again.", song.display)
            continue
        except (OSError, ValueError, SharedFolder) as e:
            log.warning("%s's lyrics couldn't go on its auto sheet: %s", song.display, e)
            continue
        version = get_version(conn, auto.version_id)
        set_raw(conn, version.id, {**version.raw, "lyrics": "plain"})
        write_info(conn, cfg.library_dir, song)
        done.append(song)
    return done
