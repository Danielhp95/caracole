"""A song's transcript, kept apart from its lyrics, and which songs are offered one.

Whisper's words from a YouTube song's audio (when no lyrics site has the song's) are kept in kv
``transcript:<song id>``, never in ``songs.lyrics_json``: a site's lyrics always win, the transcript stays
kept, unused while the song has lyrics, and goes with the song (songs._PER_SONG_KV). It is the song's only while
its ``audio`` and ``audio_mtime`` are the song's own: other audio (another video pasted, a purchase dropped into
Music/) is no use to it, and the song is offered a transcript again. A song heard to have nothing sung keeps
``transcribe:none:<song id>`` instead, for that audio alone, with why and by whom; one whose audio can't be read,
auto-chords' record of it, ``autochords:failed:<song id>`` (run.py's, which the transcription files too), and is
offered none until it changes.

This module imports nothing third-party: the transcribing itself is elsewhere, and ``why_not_offered`` runs on
every page build.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caracole.config import Config
from caracole.db import kv_delete, kv_get, kv_get_json, kv_set_json
from caracole.library import kept_files
from caracole.overrides import Overrides
from caracole.songs import HUMAN_SHEET, Song, list_songs
from caracole.youtube_fetch import youtube_audio

TRANSCRIPT = "transcript:"  # + song id: the Transcript kept for the song's audio
HEARD_NOTHING = "transcribe:none:"  # + song id: when the song's audio was transcribed to nothing
UNREADABLE = "autochords:failed:"  # + song id: audio auto-chords or a transcription couldn't read (run.py writes it)
LYRICS_SOURCE = "transcript"  # a version's raw["lyrics_source"] when the sheet's words are the transcript's
NOTE = "Lyrics transcribed from the audio (Whisper), unverified"
ALREADY_TRANSCRIBED = "already transcribed"  # why_not_offered's word for a song whose own audio has a transcript
MODEL = "whisper-large-v3"

# The lyrics sites that are switched on: (provider, the kv prefix of the song's miss).
_SITES = (("megalobiz", "megalobiz:checked:"), ("azlyrics", "azlyrics:checked:"))


@dataclass(frozen=True)
class Transcript:
    """What Whisper heard: timed lines (``lrc``), of which audio (path and mtime), by what, and when."""

    lrc: str
    audio: str
    audio_mtime: float | None
    model: str
    language: str
    device: str
    words_dropped: int
    made_at: str

    def as_json(self) -> dict[str, Any]:
        return {"lrc": self.lrc, "audio": self.audio, "audio_mtime": self.audio_mtime, "model": self.model,
                "language": self.language, "device": self.device, "words_dropped": self.words_dropped,
                "made_at": self.made_at}

    @staticmethod
    def from_json(value: Any) -> Transcript | None:
        if not isinstance(value, dict):
            return None
        texts = {name: value.get(name) for name in ("lrc", "audio", "model", "language", "device", "made_at")}
        mtime, dropped = value.get("audio_mtime"), value.get("words_dropped")
        if not all(isinstance(t, str) for t in texts.values()):
            return None
        if isinstance(mtime, bool) or not (mtime is None or isinstance(mtime, int | float)):
            return None
        if isinstance(dropped, bool) or not isinstance(dropped, int):
            return None
        return Transcript(audio_mtime=None if mtime is None else float(mtime), words_dropped=dropped, **texts)


def _own_audio(song: Song, audio: object, audio_mtime: object) -> bool:
    return audio == song.audio_path and audio_mtime == song.audio_mtime


def keep_transcript(conn: sqlite3.Connection, song: Song, transcript: Transcript) -> None:
    kv_set_json(conn, f"{TRANSCRIPT}{song.id}", transcript.as_json())
    kv_delete(conn, f"{HEARD_NOTHING}{song.id}")


def transcript_of(conn: sqlite3.Connection, song: Song) -> Transcript | None:
    """The kept transcript, only while its audio is the song's own."""
    kept = Transcript.from_json(kv_get_json(conn, f"{TRANSCRIPT}{song.id}"))
    if kept is None or not _own_audio(song, kept.audio, kept.audio_mtime):
        return None
    return kept


def note_heard_nothing(conn: sqlite3.Connection, song: Song, stamp: str, *, why: str, by: str) -> None:
    """The song's current audio noted to have nothing sung, at ``stamp``: ``why`` (words.py's "sung 6.2 s", "5 words
    in 1:10 sung") and ``by`` whom ("caracole", by those rules)."""
    kv_set_json(conn, f"{HEARD_NOTHING}{song.id}",
                {"audio": song.audio_path, "audio_mtime": song.audio_mtime, "at": stamp, "why": why, "by": by})


def heard_nothing(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the song's current audio was transcribed to nothing."""
    kept = kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")
    return isinstance(kept, dict) and _own_audio(song, kept.get("audio"), kept.get("audio_mtime"))


def unreadable(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the song's current audio is filed as audio that can't be read (run.py ``_unreadable``)."""
    kept = kv_get_json(conn, f"{UNREADABLE}{song.id}")
    return isinstance(kept, dict) and _own_audio(song, kept.get("audio"), kept.get("audio_mtime"))


def why_not_offered(conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides) -> str | None:
    """None when the song is due for an offer of a transcript, else one short reason."""
    if youtube_audio(conn, song) is None:
        return "its audio isn't from YouTube"
    if not Path(song.audio_path or "").is_file():
        return "its audio file is missing"
    if unreadable(conn, song):
        return "its audio can't be read"
    if song.status == "ignored" or song.key in overrides.ignore:
        return "ignored"
    if any(f.name == HUMAN_SHEET for f in kept_files(conn, song.id)):
        return "has a human sheet"
    if song.lyrics_status != "missing":
        return f"its lyrics are {song.lyrics_status}"
    if not song.lyrics_at:
        return "LRCLIB hasn't been asked"
    for provider, prefix in _SITES:
        if cfg.provider(provider).enabled and kv_get(conn, f"{prefix}{song.id}") is None:
            return f"{provider} hasn't been asked"
    if transcript_of(conn, song) is not None:
        return ALREADY_TRANSCRIBED
    if heard_nothing(conn, song):
        return "nothing sung was heard"
    return None


def offered_song_ids(conn: sqlite3.Connection, cfg: Config, overrides: Overrides) -> list[int]:
    return sorted(s.id for s in list_songs(conn) if why_not_offered(conn, cfg, s, overrides) is None)
