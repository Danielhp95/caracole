"""Lyrics that came after an auto sheet was made, put on it with no model.

A sheet auto-chords made of a song with no lyrics is its chart alone (version ``raw["lyrics"]`` "none"). Its chart is all
a sheet over plain lyrics adds them to (``merge.with_plain_lyrics``), so the words need neither the models nor the audio:
``render_all`` does this first, whichever way the lyrics came (LRCLIB, Megalobiz or AZLyrics; the nightly run, ``caracole
lyrics`` or a lookup), so that the song's page has them as soon as it is made again. The sheet's version then says
"plain", so timed lyrics stay what run.py's ``_skip_reason`` makes it due for: with those, the words go on here at
once and auto-chords puts each chord over its word at its next run. It also keeps the words' key (sheet.py's
``lyrics_key``), as sheet.py's ``raw_of`` keeps it for a sheet made over the song's lyrics, so that other words later
make it due as that one is.

That is for a sheet made before what was heard was kept (no ``raw["heard"]``). One that keeps it is laid out again
instead, right after (``relay_onto_sheets``, sheet.py's ``relay_due`` and ``relay``): over the song's words now, timed
ones and a transcript too, as the models would have made it, with no model and no audio; so its words never make it
the models' again (run.py ``_skip_reason``). No sheet is handled by both.

Imports no model, as ``merge`` and ``sheet`` do: render.py runs in a caracole without auto-chords too.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Collection, Mapping
from pathlib import Path

from caracole.autochords.merge import with_plain_lyrics
from caracole.autochords.sheet import Noted, noted_in, read_heard, relay, relay_due, raw_of
from caracole.autochords.sheet import lyrics_key  # sheet.py's, kept here for render.py and older callers
from caracole.config import Config
from caracole.library import SharedFolder, keep_file, kept_files, read_regular, write_info
from caracole.overrides import Overrides
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, Song, get_song
from caracole.versions import get_version, set_raw

log = logging.getLogger(__name__)


def _wanting(conn: sqlite3.Connection, overrides: Overrides,
             only: Collection[int] | None = None) -> list[tuple[Song, str]]:
    """Each song, of ``only`` when given, whose auto sheet has no lyrics and who has some, and those lyrics: a sheet
    that keeps no ``heard`` (one that keeps it is re-laid, ``relay_onto_sheets``, timed lyrics and all); not an
    ignored one, nor one with a human sheet, which is the one its pages show. A render runs this over the library, so
    a song with no such sheet costs it nothing, and lyrics stored that can't be read are none."""
    from caracole.lyrics import song_lyrics

    rows = conn.execute(
        "SELECT f.song_id FROM files f JOIN versions v ON v.id = f.version_id "
        "WHERE f.name = ? AND json_valid(v.raw) AND json_extract(v.raw, '$.lyrics') = 'none' "
        "AND COALESCE(json_type(v.raw, '$.heard'), 'null') = 'null'", (AUTO_SHEET,)
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
        set_raw(conn, version.id, {**version.raw, "lyrics": "plain", "lyrics_key": lyrics_key(plain)})
        write_info(conn, cfg.library_dir, song)
        done.append(song)
    return done


def noted_of(conn: sqlite3.Connection, song: Song, raw: Mapping[str, object]) -> Noted:
    """What this caracole notes of the words of the audio the sheet was heard from (sheet.py ``Noted``): its kv's
    transcript and nothing-sung verdict of the song's audio (transcript.py, as run.py's ``_generate`` reads them), where
    the sheet was heard from that very audio (the raw's ``audio`` the song's, and made since it last changed); else what
    the sheet was laid out with (``noted_in``): words heard from other audio (another caracole's, say) are never laid
    over it."""
    from caracole.autochords.transcript import heard_nothing, said_not_sung, transcript_of

    if raw.get("audio") != song.audio_path or song.autochords_mtime != song.audio_mtime or not song.audio_path:
        return noted_in(raw)
    transcript = transcript_of(conn, song)
    silent = transcript is None and heard_nothing(conn, song)
    return Noted(transcript, silent, silent and said_not_sung(conn, song))


_TOLD: set[tuple[int, str]] = set()  # the unreadable heard records said this process, by song and why


def relay_reason(conn: sqlite3.Connection, song: Song, raw: Mapping[str, object]) -> str | None:
    """Why the song's auto sheet (``raw``, its version's) is to be re-laid now (sheet.py ``relay_due`` over
    ``noted_of``), or None: always None for a sheet that keeps no ``heard`` (made before it was kept: the models'), and
    for one whose ``heard`` can't be read (``read_heard``: a newer caracole's contract, a damaged record), which is
    neither re-laid nor made due for its words; where it would have been, that is said once a process at WARNING, by
    song and reason, so a render a night says it, never each of a render's songs or a lookup's every render again."""
    if raw.get("heard") is None:
        return None
    why = relay_due(song, raw, noted_of(conn, song, raw))
    if why is None:
        return None
    try:
        read_heard(raw.get("heard"))
    except ValueError as e:
        if (song.id, str(e)) not in _TOLD:
            _TOLD.add((song.id, str(e)))
            log.warning("%s: its auto sheet isn't laid out again over its words (%s): what was heard can't be read "
                        "(%s); it stays as it is until its audio changes", song.display, why, e)
        return None
    return why


def _relay_candidates(conn: sqlite3.Connection, only: Collection[int] | None) -> list[int]:
    """The songs whose kept auto sheet keeps what was heard: one query, no file read."""
    rows = conn.execute(
        "SELECT f.song_id FROM files f JOIN versions v ON v.id = f.version_id "
        "WHERE f.name = ? AND json_valid(v.raw) AND COALESCE(json_type(v.raw, '$.heard'), 'null') != 'null' "
        "ORDER BY f.song_id", (AUTO_SHEET,)
    ).fetchall()
    return [song_id for (song_id,) in rows if only is None or song_id in only]


def relay_onto_sheets(conn: sqlite3.Connection, cfg: Config, overrides: Overrides | None = None,
                      only: Collection[int] | None = None, *,
                      between: Callable[[], bool] | None = None) -> list[Song]:
    """Lay each auto sheet that keeps what was heard out again over its song's words, where they changed
    (``relay_reason``), with no model and no audio (sheet.py ``relay``), and return the songs re-laid: of ``only``
    when given, not ignored, with no human sheet. Each song is read as it is just before its re-lay (a lookup let in
    ``between`` two may have changed it; overrides.toml is read again then too). The version's raw and the sheet are
    written in one savepoint, info.json after; one that can't be laid out or written is logged and left as it is,
    stopping no other, never a miss. render.py's ``render_all`` runs this right after ``lyrics_onto_sheets``."""
    from caracole.db import savepoint
    from caracole.overrides import OverridesError, load_overrides

    overrides = overrides or Overrides()
    done = []
    for n, song_id in enumerate(_relay_candidates(conn, only)):
        if n and between is not None and between():
            try:
                overrides = load_overrides(cfg.overrides_file)
            except OverridesError as e:
                log.info("overrides.toml couldn't be read again (%s); the re-lay goes on with what it read.", e)
        try:
            song = get_song(conn, song_id)
        except KeyError:  # gone meanwhile
            continue
        if song.status == "ignored" or song.key in overrides.ignore:
            continue
        files = kept_files(conn, song_id)
        auto = next((f for f in files if f.name == AUTO_SHEET), None)
        if auto is None or any(f.name == HUMAN_SHEET for f in files):
            continue
        version = get_version(conn, auto.version_id)
        why = relay_reason(conn, song, version.raw)
        if why is None:
            continue
        try:
            made = relay(song, version.raw, noted_of(conn, song, version.raw))
            raw = raw_of(song, made)
            with savepoint(conn, "relay"):
                set_raw(conn, version.id, raw)
                keep_file(conn, cfg.library_dir, song=song, version_id=version.id, name=AUTO_SHEET,
                          data=made.text.encode("utf-8"), rank=auto.kept_rank)
            write_info(conn, cfg.library_dir, get_song(conn, song_id))
        except (OSError, SharedFolder) as e:
            log.warning("%s's auto sheet couldn't be laid out again over its words (%s): %s", song.display, why, e)
            continue
        except Exception as e:  # noqa: BLE001 - a bug laying one out must cost the others nothing
            log.error("%s's auto sheet couldn't be laid out again over its words (%s): %s: %s", song.display, why,
                      type(e).__name__, e, exc_info=True)
            continue
        log.info("%s: its auto sheet laid out again from what was heard (%s), %s lyrics", song.display, why, made.used)
        done.append(get_song(conn, song_id))
    return done
