"""A song's auto sheet from an audio file you give it, now: ``caracole audio FILE`` (a file on disk, copied) and
``caracole audio --upload ID`` (a file caracole serve staged, moved), which caracole serve's "+" runs.

It is youtube_sheet.py's sheet with its download swapped for "keep this file" (``_AudioSheet``, a ``_Sheet``), in one
process, under caracole's lock as asked for now, its stages reported as a lookup reports its own (staged.py):

- ``song``: the song, found in the library or added to wanted.txt as ``caracole add`` adds it, with the file's album
  and length on a new line (so LRCLIB is asked with the file's length), then synced; refused when it is ignored or has
  a human sheet. A purchase linked, or YouTube's audio, is no refusal: a file you give a song is its audio whatever it
  had, the owner's decision of 2026-11-25. No ``[youtube]`` is read or written.
- ``audio``: the file kept as the song's audio in caracole's own folder (audio_store.py ``keep``: an upload moved, a
  file of your own copied, each read as an upload is), "kept as its audio: MP3, 3:18", saying which audio it replaces
  as the song's source (the bought audio, whose file stays in Music/; YouTube's, whose file the next youtube ``tidy``
  lets go of; the file given before, deleted); "has this file's audio already" for the same file again. A file
  caracole doesn't read, or an upload gone, fails it, and the command exits 1; but an upload gone for a song whose
  audio is a file given is taken as the one it became (Try again of a job past this stage, whose first run moved it
  into place: "has this file's audio already"). The smallest rule: nothing remembers which upload a kept file was, so
  a later upload for the same song, then Try again of the older job, makes the sheet from the later file, the song's
  audio then.
- ``lyrics``, ``vocals``, ``words``, ``chords``, ``pdf`` and ``pages``: the YouTube sheet's. The lyrics sites first,
  the words heard from the file only once every one missed, where this caracole can transcribe and ``[autochords]
  transcribe`` is on; a failure to hear ends its stage alone, never the sheet. Before vocals, words and chords a waiting
  lookup goes first, then the song is checked still this job's (``_still_ours``: not ignored, no human sheet), else the
  sheet ends there, a refusal.

``names_of`` is what a file names its song: the routes' guess and the command's.
"""

from __future__ import annotations

import sqlite3
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from caracole.config import Config
from caracole.get import Progress
from caracole.youtube_sheet import SheetResult, _Sheet

STAGES = (
    ("song", "Find the song"),
    ("audio", "Your audio file"),
    ("lyrics", "Lyrics"),
    ("vocals", "Where the singing is"),
    ("words", "Transcribing the lyrics"),
    ("chords", "Chords from the audio"),
    ("pdf", "PDF"),
    ("pages", "The logbook page"),
)
SAME_FILE = "has this file's audio already"


@dataclass(frozen=True)
class AudioRequest:
    """A song by name, and the audio file to make its sheet of: ``file``, a file on disk (copied), or ``upload``, the
    id of one caracole serve staged (moved); its ``album`` and its length in seconds (``duration``), for a new song's
    wanted.txt line."""

    artist: str
    title: str
    file: Path | None = None
    upload: str | None = None
    album: str | None = None
    duration: float | None = None

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


def names_of(conn: sqlite3.Connection | None, name: str, tags: Mapping[str, str | None]) -> tuple[str | None, str]:
    """The artist and the title an audio file names: its artist and title tags, the title cleaned as a video's is
    (song_names.py ``clean``); else its own name, less its extension and its track number (music.py's), read as the
    pages read a query (``read_names``); else that name as the title alone, its artist None. ``name`` is the file's
    name (an upload's, the name it was sent under), ``tags`` its artist, title and album as audio_store.py reads
    them."""
    from caracole.music import _TRACK_PREFIX
    from caracole.song_names import clean, read_names

    artist, title = (tags.get("artist") or "").strip(), (tags.get("title") or "").strip()
    if artist and title:
        return artist, clean(title) or title
    stem = Path(name).stem
    stem = _TRACK_PREFIX.sub("", stem).strip() or stem
    return read_names(conn, stem) or (None, clean(stem) or stem)


class _AudioSheet(_Sheet):
    STAGES = STAGES

    def _still_ours(self, song: Any) -> None:
        """Not ignored, with no human sheet: audio of its own is no refusal, as the file given replaces it."""
        self._unsheeted(song)

    def find_song(self) -> str:
        req = self.request
        duration_ms = round(req.duration * 1000) if req.duration and req.duration >= 1 else None
        song, said = self._the_song(album=req.album, duration_ms=duration_ms)
        self._still_ours(song)
        self.song = song
        self.result.song_id, self.result.display = song.id, song.display
        self.progress.song(song.id, song.display)
        return said

    def audio(self) -> tuple[str, str]:
        """The file kept as the song's audio, and which audio it replaces as its source."""
        from caracole import audio_store
        from caracole.wanted import format_duration
        from caracole.youtube_fetch import youtube_audio

        self._song_again()  # still in the book: the file is linked to it
        song, req = self.song, self.request
        before = audio_store.uploaded(self.cfg, song)
        if before is not None:
            replaced = "the file given before"
        elif song.audio_path and youtube_audio(self.conn, song) is not None:
            replaced = "YouTube's audio"
        elif song.audio_path:
            replaced = "the bought audio (its file in Music/ stays)"
        else:
            replaced = None
        move = req.upload is not None
        if move and before is not None and audio_store.gone(self.cfg, req.upload):
            # Moved into place by this job's first run (Try again after its Audio stage): the song's file given.
            return "done", SAME_FILE
        try:
            source = audio_store.staged(self.cfg, req.upload).path if move else req.file
            kept = audio_store.keep(self.cfg, self.conn, song, source, move=move, upload_id=req.upload)
            found = audio_store.examine(kept)
        except audio_store.AudioError as e:  # in its words, as a stage's: "not an audio file caracole reads (…)"
            said = str(e).rstrip(".")
            return self._fail(said[:1].lower() + said[1:])
        except OSError as e:  # the disk's, reading the file or writing its copy
            return self._fail(f"can't keep {req.file or 'the upload'}: {e.strerror or e}")
        self._song_again()  # its audio the kept file's now, for the stages after
        if kept == before:
            return "done", SAME_FILE
        said = f"kept as its audio: {found.format}, {format_duration(round(found.duration * 1000))}"
        return "done", said + (f"; it replaces {replaced} as the song's source" if replaced else "")

    def run(self) -> SheetResult:
        self._run(f"audio {self.request.display}")
        return self.result


def make_audio_sheet(cfg: Config, request: AudioRequest, progress: Progress | None = None, *,
                     runner: Callable = subprocess.run, recognizer: Any = None, beats_fn: Any = None,
                     separator: Any = None, transcriber: Any = None, hears: bool | None = None,
                     now: datetime | None = None, clock: Callable[[], float] = time.monotonic) -> SheetResult:
    """Make one song's auto sheet from an audio file now, stage by stage (see the module docstring), reporting to
    ``progress``; the models, ``hears``, ``now`` and ``clock`` as ``youtube_sheet.make_sheet`` takes them. The caller
    checks first that this caracole can make chords of audio (``youtube_fetch.autochords_problem``)."""
    return _AudioSheet(cfg, request, progress or Progress(), runner=runner, recognizer=recognizer, beats_fn=beats_fn,
                       separator=separator, transcriber=transcriber, hears=hears, now=now, clock=clock).run()
