"""One record of a song's kept lyrics search made its lyrics, and its auto sheet laid over them at once: ``caracole
lyrics --song X --pick N`` (the search's Nth row) or ``--record SITE:ID`` (one of its rows); and the pick taken back,
``--clear`` (``clear_pick``).

A record is named only by an id caracole saw in a kept search (lyrics_search.py ``kept_search``, ``row_of``): never
one built from the argument alone. The job's stages are reported as a lookup's (staged.py), under caracole's lock as
asked for now (as ``versions --keep`` holds it), its client a lookup's, at a lookup's pace:

- ``song``: the song, by its identity key, and the row: refused for a song not in the book or ignored, no search kept
  ("search … first"), a search over ``PICKABLE_FOR`` old, or a record its last search didn't list.
- ``lyrics``: the record read. LRCLIB's from the search's cached answer (its ``/api/search``, or its ``/api/get`` of
  the name and the audio's length), no request, else ``/api/get/{id}``, one; Megalobiz's ``/lrc/{id}``, AZLyrics' lyrics
  page, one each, through the cache. A record with no lyrics now (instrumental, empty, no timed line, its 404) keeps
  nothing, skipped; a site off, cooling down, out of its asks or blocking is a wait, skipped; its error fails the stage;
  none of them changes the song, its ``[lyrics]`` or its records: errors are never misses. Kept, in this order: the
  lyric files (``lyrics.txt``, ``lyrics.lrc``) written first; then the record noted under ``[lyrics]`` (its ``as``
  kept); then, in one savepoint, the question asked anew (lyrics_search.py ``ask_anew``), the song's lyrics found and
  its auto sheet made due where the words changed (its ``autochords_mtime`` cleared, as new audio clears it: a sheet
  made before it kept its words' key is remade too); then info.json. It replaces whatever the song had. Files or
  overrides.toml that can't be written put the lyric files back and keep nothing else, failing the job (its words say
  when the files couldn't be put back and may hold the new words); an info.json that can't be written after the keep
  leaves the lyrics kept, said so, and fails the job.
- ``chords``: the auto sheet made again over them now, or made for the first time (``_autochords_sheet``, after a
  waiting lookup went first); otherwise skipped, saying why: no new lyrics, a site's sheet, no audio, or auto-chords
  not here (tonight's run makes it again; a chart takes the words as plain lyrics at the PDF's render meanwhile,
  sheet_lyrics.py, no model).
- ``pdf``: ``render_all`` for the song whenever it keeps any sheet, so a human sheet's sung line lights too.
- ``pages``: _todo.md and index.html.

The command exits 0 once lyrics were kept or a site waited or failed; 1 for a refusal, a local failure (the lyric
files, overrides.toml or info.json unwritable), a chords or a PDF failure, or a bug.
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from caracole.config import Config
from caracole.get import Progress
from caracole.logs import provider_name
from caracole.overrides import LyricsRecord, Overrides
from caracole.songs import Song
from caracole.staged import StagedResult, StagedRun, _Stop

log = logging.getLogger(__name__)

STAGES = (
    ("song", "Find the song"),
    ("lyrics", "Lyrics"),
    ("chords", "Chords from the audio"),
    ("pdf", "PDF"),
    ("pages", "The logbook page"),
)
NO_NEW = "no new lyrics"
NOTHING_KEPT = "; nothing kept"
NO_LYRICS_NOW = " has no lyrics now"  # a record gone, its lyrics stage's words before NOTHING_KEPT: an answer, no wait
KEPT_FAILED_AFTER = "Lyrics kept; the job failed after"  # the command's last line for a failure after the keep
CLEARED = "Cleared the record you picked"  # how ``clear_pick``'s line begins, which caracole serve's request line reads
# ``--clear``'s refusal, after the song's name
NOTHING_TO_CLEAR = "has no lyrics record picked under [lyrics]: nothing to clear."
FAR = 10.0  # seconds between the record's length and the audio's past which the lyrics stage says so


@dataclass(frozen=True)
class PickRequest:
    """A song of the library by name, and the row of its kept search to take: ``pick``, its number (from 1), or
    ``record``, its record as ``[lyrics]`` writes it (``lrclib:28399373``)."""

    artist: str
    title: str
    pick: int | None = None
    record: str | None = None

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


def _possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _clock(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def _readable(song: Song) -> Any:
    from caracole.lyrics import song_lyrics

    try:
        return song_lyrics(song)
    except (TypeError, ValueError):  # lyrics stored that can't be read: as none
        return None


def _has_auto_sheet(conn: sqlite3.Connection, song: Song) -> bool:
    from caracole.library import kept_files
    from caracole.songs import AUTO_SHEET

    return any(f.name == AUTO_SHEET for f in kept_files(conn, song.id))


class _Pick(StagedRun):
    STAGES = STAGES
    MAKING = "its lyrics were picked"

    def __init__(self, cfg: Config, request: PickRequest, progress: Progress, **kw: Any):
        super().__init__(cfg, progress, StagedResult(display=request.display), **kw)
        self.request = request
        self.search: Any = None
        self.row: Any = None
        self.info_failed = ""  # the lyrics stage's last words when info.json couldn't be written after the keep

    # --- song ---------------------------------------------------------------------------------------------------

    def find_song(self) -> str:
        from caracole.db import kv_get_json
        from caracole import stamps
        from caracole.lyrics_search import KV, PICKABLE_FOR, kept_search, row_of
        from caracole.normalize import identity_key
        from caracole.songs import find_song

        req = self.request
        key = identity_key(req.artist, req.title)
        song = find_song(self.conn, key)
        if song is None:
            raise _Stop(f"{req.display} isn't in the book")
        if song.status == "ignored" or key in self.overrides.ignore:
            raise _Stop(f"{song.display} is ignored (overrides.toml)")
        search = kept_search(self.conn, song.id, self.now)
        if search is None:
            kept = kv_get_json(self.conn, f"{KV}{song.id}")
            at = stamps.parse(kept["at"]) if isinstance(kept, dict) and isinstance(kept.get("at"), str) else None
            if at is not None and stamps.utc(self.now) - at > PICKABLE_FOR:
                raise _Stop("its last search is over a week old: search again")
            raise _Stop(f"search {song.display}'s lyrics first (caracole lyrics --song … --as …)")
        if req.pick is not None:
            if not 1 <= req.pick <= len(search.rows):
                raise _Stop(f"its last search listed {len(search.rows)} records: there is no row {req.pick}")
            row = search.rows[req.pick - 1]
        else:
            row = row_of(search, req.record or "")
            if row is None:
                raise _Stop(f"“{req.record}” isn't among the records its last search listed")
        self.song, self.search, self.row = song, search, row
        self.result.song_id, self.result.display = song.id, song.display
        self.progress.song(song.id, song.display)
        return f"in the book; its last search's {row.record}"

    # --- lyrics -------------------------------------------------------------------------------------------------

    def _cached_lrclib(self, lrclib_id: int) -> Any:
        """LRCLIB's record of ``lrclib_id`` as the search's answers in the HTTP cache hold it (its search, then its
        get of the name and the audio's length), with no request; None when the cache no longer holds it."""
        import httpx

        from caracole.http import CachedAnswers
        from caracole.lyrics import LRCLIB_API, Lyrics, get_params

        cache = CachedAnswers("lrclib", self.cfg.cache_dir)
        artist, title = self.search.asked
        asked = [(f"{LRCLIB_API}/search", self.search.lrclib),
                 (f"{LRCLIB_API}/get", get_params(artist, title, album=None, duration_s=self.search.length))]
        for url, params in asked:
            answer = cache.cached(str(httpx.URL(url, params=params)) if params else url)
            if answer is None:
                continue
            try:
                found = answer.json()
            except (ValueError, RecursionError):
                continue
            for record in found if isinstance(found, list) else [found]:
                if isinstance(record, dict) and type(record.get("id")) is int and record["id"] == lrclib_id:
                    return Lyrics.from_record(record)
        return None

    def _read(self, record: LyricsRecord) -> tuple[Any, tuple[str, str] | None]:
        """The record's lyrics (None for none now), or the stage's end when its site couldn't be asked."""
        from caracole.azlyrics_fetch import fetch_azlyrics
        from caracole.commands._common import lookup_run_id, make_client
        from caracole.health import get_state, is_cooling, record_ok
        from caracole.http import BudgetExhausted, ProviderError
        from caracole.lyrics import fetch_lrclib_record
        from caracole.lyrics_search import BLOCKED, FAILED, stopped
        from caracole.megalobiz_fetch import fetch_record
        from caracole.stamps import shown

        site, name = record.site, provider_name(record.site)
        if site == "lrclib":
            cached = self._cached_lrclib(int(record.id))
            if cached is not None:
                return cached, None
        if not self.cfg.provider(site).enabled:
            return None, ("skipped", f"{name} is off (caracole.toml){NOTHING_KEPT}")
        if is_cooling(self.conn, site, self.now):
            until = shown(get_state(self.conn, site).cooldown_until)
            return None, ("skipped", f"waiting out {name} until {until}{NOTHING_KEPT}")
        client = make_client(self.cfg, self.conn, site, lookup_run_id(self.now), interactive=True)
        try:
            if site == "lrclib":
                lyrics = fetch_lrclib_record(client, int(record.id))
            elif site == "megalobiz":
                lyrics = fetch_record(client, int(record.id))
            else:
                lyrics = fetch_azlyrics(client, artist="", title="", page=record.page)
        except (ProviderError, BudgetExhausted) as e:
            state, said = stopped(self.cfg, self.conn, self.now, site, client, e, whose="this pick's", why=True)
            end = ", nothing kept" if state == BLOCKED else NOTHING_KEPT  # §4.5's words for a block
            return None, ("failed" if state == FAILED else "skipped", f"{said}{end}")
        finally:
            self.result.requests[site] = client.requests_made
            client.close()
        if client.answered_any():
            record_ok(self.conn, site, self.now)
        return lyrics, None

    def lyrics(self) -> tuple[str, str]:
        from caracole.overrides import LyricsRecord

        row = self.row
        site, _, record_id = row.record.partition(":")
        record = LyricsRecord(site, record_id)
        lyrics, stopped = self._read(record)
        if stopped is not None:
            return stopped
        if lyrics is None or not lyrics.has_lyrics or lyrics.instrumental:
            return "skipped", f"{_possessive(provider_name(site))} record {record_id}{NO_LYRICS_NOW}{NOTHING_KEPT}"
        self._song_again()
        before = _readable(self.song)
        kept = self._keep(record, lyrics, before)
        if kept is not None:
            return kept
        return "done", self._kept_said(lyrics, before) + self.info_failed

    def _keep(self, record: LyricsRecord, lyrics: Any, before: Any) -> tuple[str, str] | None:
        """The lyrics written first; only then the record noted under ``[lyrics]``, and, in one savepoint, the question
        asked anew, the lyrics found and the auto sheet made due where the words changed (``before``, the song's lyrics
        till now). A local failure (the files, overrides.toml) puts the files back and changes nothing else, and fails
        the job (``_fail``: exit 1); info.json, written last, fails the job after the keep (``info_failed``). None once
        kept, else the stage's end."""
        from caracole import stamps
        from caracole.db import savepoint
        from caracole.library import SharedFolder, song_dir, write_info
        from caracole.lyrics import write_lyrics
        from caracole.lyrics_search import ask_anew
        from caracole.overrides import OverridesError, load_overrides, set_lyrics_record
        from caracole.songs import get_song, update_song

        song = self.song
        folder = song_dir(self.cfg.library_dir, song)
        try:  # the lyrics on disk first: until they are, nothing else is written
            write_lyrics(folder, lyrics)
        except (OSError, SharedFolder) as e:
            return self._fail(f"couldn't write its lyrics ({e}){self._put_back(folder, before)}")
        try:
            set_lyrics_record(self.cfg.overrides_file, song.display, record.text)
            self.overrides = load_overrides(self.cfg.overrides_file)
        except OverridesError as e:  # the files written are taken back: the song stays as it was
            return self._fail(f"couldn't note the record in overrides.toml: {e}{self._put_back(folder, before)}")
        other_words = before is None or (before.plain, before.synced) != (lyrics.plain, lyrics.synced)
        due = {"autochords_mtime": None} if other_words and _has_auto_sheet(self.conn, song) else {}
        with savepoint(self.conn, "lyrics_pick"):
            ask_anew(self.conn, song)  # a record picked is a new question: what the sites missed before goes
            update_song(self.conn, song.id, lyrics_status="found", lyrics_json=lyrics.to_json(),
                        lyrics_at=stamps.stamp(self.now), **due)
        self.song = get_song(self.conn, song.id)
        try:  # its "lyrics_from": the link back to their page
            write_info(self.conn, self.cfg.library_dir, self.song)
        except (OSError, SharedFolder) as e:  # the lyrics are kept by now: the stage says so, the job fails after
            self.info_failed = f"; info.json couldn't be written ({e})"
            self.result.failed = self.result.failed or f"info.json couldn't be written ({e})"
        return None

    def _put_back(self, folder: Any, before: Any) -> str:
        """The song's lyric files as its stored lyrics had them (none for none), after a keep that couldn't finish;
        the stage's last words: nothing kept, or, when they couldn't be put back, that they may hold the new words."""
        from caracole.library import SharedFolder
        from caracole.lyrics import Lyrics, write_lyrics

        try:
            write_lyrics(folder, before or Lyrics(plain="", synced=None, instrumental=False, duration=None,
                                                  lrclib_id=None))
        except (OSError, SharedFolder) as e:
            log.warning("%s's lyric files couldn't be put back: %s", self.song.display, e)
            return f"; nothing else kept, but its lyric files may hold the new words (putting them back failed: {e})"
        return NOTHING_KEPT

    def _kept_said(self, lyrics: Any, before: Any) -> str:
        row = self.row
        name = provider_name(row.site)
        facts = [part for part in (row.album, _clock(lyrics.duration or row.duration or 0)
                                   if (lyrics.duration or row.duration) else "") if part]
        said = (f"{'timed' if lyrics.synced else 'plain'} lyrics from {name}: {row.artist or '(no artist)'} - "
                f"{row.title}" + (f" ({', '.join(facts)})" if facts else ""))
        if before is not None and before.has_lyrics:
            said += (f"; in place of {_possessive(provider_name(before.provider))} "
                     f"{'timed' if before.synced else 'plain'} lyrics")
        audio, length = self._audio_length(), lyrics.duration or row.duration
        if audio is not None and length is not None and abs(audio - length) > FAR:
            gap = round(abs(audio - length))
            said += f"; the audio is {gap} s {'longer' if audio > length else 'shorter'}"
        return said

    # --- chords, pdf --------------------------------------------------------------------------------------------

    def _why_no_chords(self) -> str | None:
        from pathlib import Path

        from caracole.library import kept_files
        from caracole.songs import HUMAN_SHEET

        if any(f.name == HUMAN_SHEET for f in kept_files(self.conn, self.song.id)):
            return "its sheet is a site's: no auto sheet to make again"
        if not self.song.audio_path or not Path(self.song.audio_path).is_file():
            return "no audio to make an auto sheet from"
        return None

    def chords(self) -> tuple[str, str]:
        from caracole import youtube_fetch

        if self.result.states.get("lyrics") != "done":
            return "skipped", NO_NEW
        why = self._why_no_chords()
        if why is not None:
            return "skipped", why
        problem = youtube_fetch.autochords_problem(self.cfg)
        if problem is not None:
            return "skipped", f"auto-chords isn't here ({problem}); tonight's run makes it again"
        self._after_a_lookup()  # the models take minutes: a waiting lookup goes first
        why = self._why_no_chords()  # what it did meanwhile: a site's sheet kept, say
        if why is not None:
            return "skipped", why
        return self._autochords_sheet()

    def pdf(self) -> tuple[str, str] | str:
        from caracole.library import kept_files
        from caracole.render import render_all
        from caracole.songs import AUTO_SHEET, HUMAN_SHEET

        if self.result.states.get("lyrics") != "done":
            return "skipped", NO_NEW
        if not any(f.name in (HUMAN_SHEET, AUTO_SHEET) for f in kept_files(self.conn, self.song.id)):
            return "skipped", "no sheet"
        stats = render_all(self.conn, self.cfg, self.overrides, runner=self.runner, now=self.now,
                           song_ids={self.song.id})
        if stats.font_error:
            return self._fail(stats.font_error)
        if stats.failed:
            return self._fail("chordpro couldn't make the PDF (see the log)")
        return "made" if stats.rendered else "up to date"

    def _check_readable(self) -> None:
        """The sheet said readable once its PDF or viewer comes, whatever the chords stage did."""
        from caracole.get import readable_files

        if self.song is None or self.result.states.get("lyrics") != "done":
            return
        files = readable_files(self.conn, self.cfg.library_dir, self.song)
        if files and files != self.result.files:
            self.result.files = files
            self.progress.readable(files, self.clock() - self.started)

    def run(self) -> StagedResult:
        self._run(f"lyrics --pick {self.request.display}")
        return self.result


def pick_lyrics(cfg: Config, request: PickRequest, progress: Progress | None = None, *,
                runner: Callable = subprocess.run, recognizer: Any = None, beats_fn: Any = None,
                now: datetime | None = None, clock: Callable[[], float] = time.monotonic) -> StagedResult:
    """Make one row of the song's kept search its lyrics now, stage by stage (the module docstring), reporting to
    ``progress``. ``runner`` runs chordpro, ``recognizer`` and ``beats_fn`` stand in for auto-chords' models (None:
    built from ``cfg``, only once the chords stage runs them), ``now`` is the run's time."""
    return _Pick(cfg, request, progress or Progress(), runner=runner, recognizer=recognizer, beats_fn=beats_fn,
                 now=now, clock=clock).run()


# --- --clear ------------------------------------------------------------------------------------------------------


def _gave(lyrics: Any, record: LyricsRecord) -> bool:
    """Whether the song's stored lyrics came from ``record``."""
    if lyrics is None or lyrics.provider != record.site:
        return False
    if record.site == "lrclib":
        return lyrics.lrclib_id is not None and str(lyrics.lrclib_id) == record.id
    if record.site == "megalobiz":
        return str(lyrics.raw.get("id")) == record.id
    return lyrics.url == record.page


def clear_pick(cfg: Config, conn: sqlite3.Connection, song: Song, overrides: Overrides) -> str | None:
    """Take the record you picked out of the song's ``[lyrics]`` (its ``as`` kept), with no request: the question asked
    anew (lyrics_search.py ``ask_anew``), and the lyrics that record gave dropped (their files too), the song pending,
    its auto sheet made due. What it did in one line, or None for a song with no record picked. The caller holds the
    lock as asked for now, and makes the pages after."""
    from caracole.db import savepoint
    from caracole.library import song_dir, write_info
    from caracole.lyrics import asked_name, picked_record
    from caracole.lyrics_search import ask_anew
    from caracole.overrides import clear_lyrics_record, load_overrides
    from caracole.songs import get_song, update_song

    record = picked_record(song, overrides.lyrics)
    if record is None:
        return None
    clear_lyrics_record(cfg.overrides_file, song.display)
    gave = _gave(_readable(song), record)
    with savepoint(conn, "lyrics_clear"):
        if gave:
            due = {"autochords_mtime": None} if _has_auto_sheet(conn, song) else {}
            update_song(conn, song.id, lyrics_status="pending", lyrics_json=None, lyrics_at=None, **due)
        ask_anew(conn, get_song(conn, song.id))
    stuck = ""
    if gave:
        folder = song_dir(cfg.library_dir, song)
        for name in ("lyrics.txt", "lyrics.lrc"):
            try:
                (folder / name).unlink(missing_ok=True)
            except OSError as e:  # the clear stands; the file is said
                stuck += f"; {name} couldn't be removed ({e.strerror or e})"
        write_info(conn, cfg.library_dir, get_song(conn, song.id))
    named = asked_name(song, load_overrides(cfg.overrides_file).lyrics)
    under = f"under “{named}”" if named else "under its own name"
    dropped = "; its lyrics from it dropped" if gave else ""
    return (f"{CLEARED} for {song.display} ({record.site} {record.id}){dropped}{stuck}; every "
            f"lyrics site is asked again {under}, tonight or at a lookup.")
