"""A song's transcript, kept apart from its lyrics, and which songs are offered one.

Whisper's words from a song's own audio (YouTube's or a purchase's) (when no lyrics site has the song's) are kept in kv
``transcript:<song id>``, never in ``songs.lyrics_json``: a site's lyrics always win, the transcript stays
kept, unused while the song has lyrics, and goes with the song (songs._PER_SONG_KV). It is the song's only while
its ``audio`` and ``audio_mtime`` are the song's own: other audio (another video pasted, a purchase dropped into
Music/) is no use to it, and the song is offered a transcript again. A song heard to have nothing sung keeps
``transcribe:none:<song id>`` instead, for that audio alone, with why and by whom (``by`` "caracole"); one the owner
said isn't sung (``caracole transcribe --none``, the card's Not sung: chords only) keeps it ``by`` "you", for that
audio alone too: a new file is a new start (often the sung version in place of an instrumental cut), heard again and
marked again if need be; until then they may say it is (``anyway``: Transcribe anyway). Each is said as whose it is:
the sheet's note (``SILENT``, ``NOT_SUNG``), the card's offer (``offers``' ``nothing`` and ``unsung``). Neither
crosses to another caracole. One whose audio can't be read keeps auto-chords' record of it,
``autochords:failed:<song id>`` (run.py's), and is offered none until it changes. Audio auto-chords reads and
Whisper's decoder (the ffmpeg program) refuses keeps ``transcribe:unreadable:<song id>`` (``note_whisper_cant_read``),
written by every hearing: offered none until it changes, its chords made, but asked for by hand (``anyway``, ``caracole
transcribe --force``: after an ffmpeg or Whisper upgrade, the one case where trying again is right).

This module imports nothing third-party: the transcribing itself is elsewhere, and ``why_not_offered`` runs on
every page build.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caracole.config import Config
from caracole.db import kv_delete, kv_get, kv_get_json, kv_set_json
from caracole.library import kept_files
from caracole.overrides import Overrides, override_key
from caracole.songs import HUMAN_SHEET, Song, list_songs

TRANSCRIPT = "transcript:"  # + song id: the Transcript kept for the song's audio
HEARD_NOTHING = "transcribe:none:"  # + song id: when the song's audio was transcribed to nothing
UNREADABLE = "autochords:failed:"  # + song id: audio auto-chords couldn't read (run.py writes it)
WHISPER_CANT_READ = "transcribe:unreadable:"  # + song id: audio Whisper can't load, which auto-chords reads
WHISPER_UNREADABLE_WHY = "Whisper can't read its audio"  # why_not_offered's word for it
# What the owner can do about it, said after it wherever a transcription is refused for it.
WHISPER_UNREADABLE_DO = ("a new file, or another video under [youtube], gets its words heard; after an ffmpeg or "
                         "Whisper upgrade, caracole transcribe --force tries it again")
SAID_NOT_SUNG = "you said it isn't sung"  # why_not_offered's word for a song the owner said isn't sung
NO_TRANSCRIPT = "it has no transcript"  # why_not_unsung's word for a song with no transcript of its audio kept
LYRICS_SOURCE = "transcript"  # a version's raw["lyrics_source"] when the sheet's words are the transcript's
NOTE = "Lyrics transcribed from the audio (Whisper), unverified"
SILENT = "Instrumental: nothing sung was heard in the audio"  # the sheet's note line over nothing sung
NOT_SUNG = "Chords only: you said it isn't sung"  # the sheet's note line over the owner's mark (``said_not_sung``)
# why_not_offered's words for a song whose picked lyrics record (``[lyrics]``) gave none (``picked_without_lyrics``)
PICKED_NONE = "the record you picked ({record}) has given no lyrics: pick another, or clear the pick"
PICKED_UNREAD = "the record you picked isn't read yet ({record}): tonight's run or a lookup reads it"
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
    """The song's transcript kept: its audio heard, so neither nothing sung nor Whisper's refusal of it stands."""
    kv_set_json(conn, f"{TRANSCRIPT}{song.id}", transcript.as_json())
    kv_delete(conn, f"{HEARD_NOTHING}{song.id}")
    kv_delete(conn, f"{WHISPER_CANT_READ}{song.id}")


def transcript_of(conn: sqlite3.Connection, song: Song) -> Transcript | None:
    """The kept transcript, only while its audio is the song's own."""
    kept = Transcript.from_json(kv_get_json(conn, f"{TRANSCRIPT}{song.id}"))
    if kept is None or not _own_audio(song, kept.audio, kept.audio_mtime):
        return None
    return kept


def note_heard_nothing(conn: sqlite3.Connection, song: Song, stamp: str, *, why: str, by: str) -> None:
    """The song's current audio noted to have nothing sung, at ``stamp``: ``why`` (words.py's "sung 6.2 s", "5 words
    in 1:10 sung", or "you said so") and ``by`` whom ("caracole", by those rules; "you", the owner's word:
    ``said_not_sung``)."""
    kv_set_json(conn, f"{HEARD_NOTHING}{song.id}",
                {"audio": song.audio_path, "audio_mtime": song.audio_mtime, "at": stamp, "why": why, "by": by})
    kv_delete(conn, f"{WHISPER_CANT_READ}{song.id}")


def said_not_sung(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the owner said the song's current audio isn't sung (``by`` "you"): a new file is a new start."""
    kept = kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")
    return (isinstance(kept, dict) and kept.get("by") == "you"
            and _own_audio(song, kept.get("audio"), kept.get("audio_mtime")))


def heard_nothing(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the song's current audio was transcribed to nothing, or the owner said it isn't sung."""
    kept = kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")
    return isinstance(kept, dict) and _own_audio(song, kept.get("audio"), kept.get("audio_mtime"))


def drop_transcript(conn: sqlite3.Connection, song: Song, stamp: str) -> None:
    """The owner's "it isn't sung": the song's transcript dropped, and its audio noted not sung by their word, so that
    nothing hears that audio again (the card's, the nightly pass's, a sheet from a video's) until they say it is."""
    kv_delete(conn, f"{TRANSCRIPT}{song.id}")
    note_heard_nothing(conn, song, stamp, why="you said so", by="you")


def note_whisper_cant_read(conn: sqlite3.Connection, song: Song, stamp: str, error: str) -> None:
    """The song's current audio noted as audio Whisper can't load, at ``stamp``, with its ``error`` in one line."""
    kv_set_json(conn, f"{WHISPER_CANT_READ}{song.id}",
                {"audio": song.audio_path, "audio_mtime": song.audio_mtime, "at": stamp, "error": error})


def whisper_cant_read(conn: sqlite3.Connection, song: Song) -> str | None:
    """Why Whisper couldn't load the song's current audio (its error, "" for none said), or None when it isn't
    noted so: a note of other audio is none."""
    kept = kv_get_json(conn, f"{WHISPER_CANT_READ}{song.id}")
    if not isinstance(kept, dict) or not _own_audio(song, kept.get("audio"), kept.get("audio_mtime")):
        return None
    error = kept.get("error")
    return error if isinstance(error, str) else ""


def unreadable(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the song's current audio is filed as audio that can't be read (run.py ``_unreadable``)."""
    kept = kv_get_json(conn, f"{UNREADABLE}{song.id}")
    return isinstance(kept, dict) and _own_audio(song, kept.get("audio"), kept.get("audio_mtime"))


def why_not_offered(conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides, *,
                    anyway: bool = False) -> str | None:
    """None when the song is due for an offer of a transcript, else one short reason. Any audio of the song's own
    counts, a purchase's as well as YouTube's; the lyrics sites always come first: a song with lyrics, or not asked
    them yet, is told that before anything a hearing left. ``anyway``, the owner's ask by hand (Transcribe anyway,
    ``caracole transcribe --force``), passes over nothing sung, caracole's verdict or the owner's own word, and audio
    Whisper couldn't load (after an ffmpeg or Whisper upgrade, the one case where trying again is right), and nothing
    else: never a song whose lyrics record you picked gave none (``picked_without_lyrics``)."""
    if not song.audio_path:
        return "it has no audio"
    if not Path(song.audio_path or "").is_file():
        return "its audio file is missing"
    if unreadable(conn, song):
        return "its audio can't be read"
    if song.status == "ignored" or song.key in overrides.ignore:
        return "ignored"
    if any(f.name == HUMAN_SHEET for f in kept_files(conn, song.id)):
        return "has a human sheet"
    picked = picked_without_lyrics(song, overrides)
    if picked is not None:
        return picked
    if song.lyrics_status != "missing":
        return f"its lyrics are {song.lyrics_status}"
    if not anyway and whisper_cant_read(conn, song) is not None:
        return WHISPER_UNREADABLE_WHY
    if not song.lyrics_at:
        return "LRCLIB hasn't been asked"
    for provider, prefix in _SITES:
        if cfg.provider(provider).enabled and kv_get(conn, f"{prefix}{song.id}") is None:
            return f"{provider} hasn't been asked"
    if transcript_of(conn, song) is not None:
        return ALREADY_TRANSCRIBED
    if not anyway and heard_nothing(conn, song):
        return SAID_NOT_SUNG if said_not_sung(conn, song) else "nothing sung was heard"
    return None


def picked_without_lyrics(song: Song, overrides: Overrides) -> str | None:
    """Why a song whose lyrics record you picked (``[lyrics]``' ``record``) and that has no lyrics is never heard,
    ``anyway`` or not, else None. A record picked is final: one record of one site is all that is ever asked about
    the song, and the other lyrics sites never are, so the owner's rule (the lyrics databases before Whisper) keeps
    it from Whisper until you pick another record or clear the pick. ``PICKED_NONE`` while its lyrics are missing,
    true whether its site answered the record a miss or hasn't asked it yet (a song missing under its own name when the
    record was written by hand waits its 30 days: ``lyrics_at`` can't tell the two apart); ``PICKED_UNREAD`` while it
    is pending (never asked yet, or its last ask an error); no ``checked:`` record is read, as one may be older than the
    pick."""
    pick = overrides.lyrics.get(override_key(song.display))
    if pick is None or pick.record is None or song.lyrics_status not in ("pending", "missing"):
        return None
    record = f"{pick.record.site} {pick.record.id}"
    return (PICKED_NONE if song.lyrics_status == "missing" else PICKED_UNREAD).format(record=record)


def without_picks(overrides: Overrides) -> Overrides:
    """``overrides`` with no ``[lyrics]`` record weighed: for Not sung, chords only (``why_not_unsung``, and its job's
    check before the chords), which runs no Whisper and only drops a transcript, so the databases-first rule
    (``picked_without_lyrics``) doesn't refuse it."""
    return dataclasses.replace(overrides, lyrics={})


def refused_for(why: str) -> str:
    """``why_not_offered``'s reason as a refusal says it: Whisper's refusal of the audio with what to do about it."""
    return f"{why} ({WHISPER_UNREADABLE_DO})" if why == WHISPER_UNREADABLE_WHY else why


def why_not_unsung(conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides) -> str | None:
    """None when the owner may say the song isn't sung (Not sung: chords only, ``caracole transcribe --none``): a song
    a transcription would be offered to but for the transcript of its own audio kept, its auto sheet over it; else one
    short reason."""
    why = why_not_offered(conn, cfg, song, without_picks(overrides), anyway=True)
    if why == ALREADY_TRANSCRIBED:
        return None
    return why if why is not None else NO_TRANSCRIPT


def offered_song_ids(conn: sqlite3.Connection, cfg: Config, overrides: Overrides) -> list[int]:
    return sorted(s.id for s in list_songs(conn) if why_not_offered(conn, cfg, s, overrides) is None)


def offers(conn: sqlite3.Connection, cfg: Config, overrides: Overrides) -> dict[str, list[int]]:
    """The served card's offers, by song id: ``songs`` a transcription (``why_not_offered``); Transcribe anyway,
    offered one but for nothing sung, told apart by whose word it is: ``nothing``, heard to have nothing sung, and
    ``unsung``, said not sung by the owner; ``transcribed`` Not sung: chords only (``why_not_unsung``). No model is
    asked."""
    songs, nothing, unsung, transcribed = [], [], [], []
    for s in list_songs(conn):
        why = why_not_offered(conn, cfg, s, overrides)
        if why is None:
            songs.append(s.id)
        elif why == ALREADY_TRANSCRIBED or (picked_without_lyrics(s, overrides) is not None
                                            and why_not_unsung(conn, cfg, s, overrides) is None):
            transcribed.append(s.id)  # Not sung: chords only, which a record picked since doesn't refuse
        elif heard_nothing(conn, s) and why_not_offered(conn, cfg, s, overrides, anyway=True) is None:
            (unsung if said_not_sung(conn, s) else nothing).append(s.id)
    return {"songs": sorted(songs), "nothing": sorted(nothing), "unsung": sorted(unsung),
            "transcribed": sorted(transcribed)}
