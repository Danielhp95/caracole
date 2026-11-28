"""A song's transcript, kept apart from its lyrics, and which songs are offered one.

Whisper's words from a song's own audio (YouTube's or a purchase's) (when no lyrics site has the song's) are kept in kv
``transcript:<song id>``, never in ``songs.lyrics_json``: a site's lyrics always win, the transcript stays
kept, unused while the song has lyrics, and goes with the song (songs._PER_SONG_KV). It is the song's only while
it is of the song's own audio (``of_audio``, the one rule every record here is read by): its ``audio`` and
``audio_mtime`` the song's, or, those changed, the same bytes (the owner's "yes" of 2026-11-27: a purchase moved,
renamed or touched keeps what was heard of it), by the record's content key (``audio_key``: ``audio_size`` and
``audio_sha256``, a given file's 16 hex digits read from its kept name, any other file's SHA-256 read once on demand,
after its size agrees); other audio (another video pasted, a purchase dropped into Music/) is no use to it, and the
song is offered a transcript again. A read answers by content and writes nothing; ``follow_audio``, where a write is
allowed (music.py ``scan_music`` right after it links a song's file again, and the nightly pass), re-points such a
record to the song's audio and keys one of before that holds none. A song heard to have nothing sung keeps
``transcribe:none:<song id>`` instead, for that audio alone, with why and by whom (``by`` "caracole"); one the owner
said isn't sung (``caracole transcribe --none``, the card's Not sung: chords only) keeps it ``by`` "you", for that
audio alone too: a new file is a new start (often the sung version in place of an instrumental cut), heard again and
marked again if need be; until then they may say it is (``anyway``: Transcribe anyway). Each is said as whose it is:
the sheet's note (``SILENT``, ``NOT_SUNG``), the card's offer (``offers``' ``nothing`` and ``unsung``). Neither
crosses to another caracole. One whose audio can't be read keeps auto-chords' record of it,
``autochords:failed:<song id>`` (run.py's), and is offered none until it changes. Audio auto-chords reads and
Whisper's decoder (the ffmpeg program) refuses keeps ``transcribe:unreadable:<song id>`` (``note_whisper_cant_read``),
written by every hearing: offered none until it changes, its chords made, but asked for by hand (``anyway``, ``caracole
transcribe --force``: after an ffmpeg or Whisper upgrade, the one case where trying again is right). A hearing that
failed for a setup-type reason (the separator, a stem cut short or unreadable, Whisper's setup: hearing.py's
``"setup"``) keeps ``transcribe:failed:<song id>`` (``note_hearing_failed``), for that audio alone, with when and the
words: the nightly pass passes over such a song (``hearing_failed``) until its audio changes or ``RETRY_DAYS`` (30)
go by, so one song that fails can't stop every night's hearing; by hand it stays offered as ever, and any hearing
that comes to something (a transcript, nothing sung, Whisper's refusal of the audio) drops it.

This module imports nothing third-party: the transcribing itself is elsewhere, and ``why_not_offered`` runs on
every page build.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import sqlite3
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from caracole.config import Config
from caracole.db import kv_delete, kv_get, kv_get_json, kv_set_json
from caracole.library import kept_files
from caracole.overrides import Overrides, override_key
from caracole.songs import HUMAN_SHEET, Song, list_songs
from caracole.stamps import before

TRANSCRIPT = "transcript:"  # + song id: the Transcript kept for the song's audio
HEARD_NOTHING = "transcribe:none:"  # + song id: when the song's audio was transcribed to nothing
UNREADABLE = "autochords:failed:"  # + song id: audio auto-chords couldn't read (run.py writes it)
WHISPER_CANT_READ = "transcribe:unreadable:"  # + song id: audio Whisper can't load, which auto-chords reads
HEARING_FAILED = "transcribe:failed:"  # + song id: a hearing of its audio that failed for a setup-type reason
RETRY_DAYS = 30  # the nightly pass tries a song whose hearing failed again after this long, as the sites are asked
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
# The reason the phone hears no song's words ("not transcribed here: …", youtube_sheet.py ``NOT_HERE``): it runs no
# separator and no Whisper (android/'s chords from audio). Recorded in the conformance corpus, used by nothing here.
PHONE = "the phone hears no words"
LYRICS_ARE = "its lyrics are {status}"  # why_not_offered's word for a song whose lyrics aren't missing
ALREADY_TRANSCRIBED = "already transcribed"  # why_not_offered's word for a song whose own audio has a transcript
MODEL = "whisper-large-v3"
# Words win (the phone's chords design, §11.5, its recommendation in force until the owner says otherwise): where every
# lyrics site missed and this side hears words from its own audio of a song whose auto sheet another caracole made
# over none (the phone's), the nightly pass hears them as any song's (``why_not_offered`` offers it as ever) and its
# sheet over them, made here from this side's audio, replaces that one (run.py ``_skip_reason``). False: never by
# itself; the nightly pass hears no words for such a song, and the card's Transcribe the lyrics, an ask, does it by
# hand.
WORDS_WIN = True

# The records kept of a song's audio, which follow it by its content (``of_audio``, ``follow_audio``). auto-chords' own
# record of audio it can't read (``UNREADABLE``, run.py's) isn't one: run.py drops it once the file changes, and a
# file moved is tried by the models once more.
RECORDS = (TRANSCRIPT, HEARD_NOTHING, WHISPER_CANT_READ, HEARING_FAILED)
AUDIO_SIZE = "audio_size"  # a record's audio's size in bytes, beside its path and mtime
# Its SHA-256: 64 hex digits, or the 16 a given file's kept name holds (audio_store.py ``given_sha16``).
AUDIO_SHA256 = "audio_sha256"
_HEX = re.compile(r"[0-9a-f]{16,64}")
_HASHED: dict[tuple[str, int, int, int, int], str] = {}  # a file's SHA-256 by its path and stat, read once a process
_HASHED_MOST = 256  # files remembered, then forgotten all at once
_BLOCK = 1 << 20

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


def _read_sha256(path: str) -> str:
    """The SHA-256 of the file's bytes, read a MiB at a time."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _sha256(path: str, st: os.stat_result) -> str | None:
    """The file's SHA-256, read at most once a process while its stat stays (``_HASHED``); None when it can't be
    read."""
    seen = (path, st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev)
    if seen not in _HASHED:
        try:
            sha = _read_sha256(path)
        except OSError:  # no verdict: the reader answers "other audio" this once, and nothing of it is kept
            return None
        if len(_HASHED) >= _HASHED_MOST:
            _HASHED.clear()
        _HASHED[seen] = sha
    return _HASHED[seen]


def audio_key(audio_path: str | None, audio_mtime: float | None) -> dict[str, Any]:
    """The content key of the file at ``audio_path``, a record's members (``AUDIO_SIZE``, ``AUDIO_SHA256``), only while
    the file is the one the record names: its mtime ``audio_mtime`` (the review of 2026-11-27: a file changed during a
    hearing, or replaced in place since the song's row was read, would key the record with bytes it wasn't heard
    from). A file you gave a song by its kept name's digits (no read), any other by its bytes, read whole; {} for no
    regular file, another mtime, or one that can't be read: the record stays unkeyed, other audio once it moves."""
    from caracole.audio_store import given_sha16

    if not audio_path or audio_mtime is None:
        return {}
    try:
        st = os.stat(audio_path)
    except OSError:
        return {}
    if not stat.S_ISREG(st.st_mode) or st.st_mtime != audio_mtime:
        return {}
    sha = given_sha16(audio_path) or _sha256(audio_path, st)
    return {AUDIO_SIZE: st.st_size, AUDIO_SHA256: sha} if sha is not None else {}


def _agree(a: str, b: str) -> bool:
    """Two digests of one file: the shorter (a given file's 16 digits) begins the longer."""
    n = min(len(a), len(b))
    return n >= 16 and a[:n] == b[:n]


def _same_bytes(song: Song, record: Mapping[str, object]) -> bool:
    """Whether the song's audio file holds the bytes ``record``'s key names: a given file by its name (nothing read);
    any other, a size that differs other audio (nothing read), else its SHA-256 (read once, ``_sha256``)."""
    from caracole.audio_store import given_sha16

    sha, size = record.get(AUDIO_SHA256), record.get(AUDIO_SIZE)
    if not isinstance(sha, str) or not _HEX.fullmatch(sha) or not song.audio_path:
        return False
    given = given_sha16(song.audio_path)
    if given is not None:
        return _agree(sha, given)
    try:
        st = os.stat(song.audio_path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if isinstance(size, int) and not isinstance(size, bool) and size != st.st_size:
        return False
    now = _sha256(song.audio_path, st)
    return now is not None and _agree(sha, now)


def of_audio(song: Song, record: object) -> bool:
    """Whether a record kept of a song's audio (``RECORDS``: a dict with its ``audio``, ``audio_mtime`` and content
    key) is of the song's audio as it is now: its path and mtime the song's; else the same bytes by its key
    (``_same_bytes``), a record with none (kept before keys were) other audio, as nothing proves its bytes. The one
    rule every reader here keeps, writing nothing: a file is read only where path or mtime moved, the record has a key
    and the sizes agree, once a process while the file stays (``_HASHED``). Its worst case is a page build after
    files were moved or touched in bulk between two scans (which re-point them, ``follow_audio``): one whole read of
    each such song's file with a keyed record, once a caracole serve process, its later builds answered from
    ``_HASHED``."""
    if not isinstance(record, Mapping):
        return False
    if _own_audio(song, record.get("audio"), record.get("audio_mtime")):
        return True
    return _same_bytes(song, record)


def follow_audio(conn: sqlite3.Connection, song: Song) -> int:
    """Each record of the song's audio (``RECORDS``) made the song's audio's as it is now where its bytes are: one of
    the same bytes elsewhere, or of another mtime, re-pointed (its ``audio`` and ``audio_mtime`` the song's, its key
    the file's); one of the song's path and mtime with no key (kept before keys were) keyed, lazily; other audio left
    as it is, unused. For a caller that may write (music.py ``scan_music`` after it links a song's file again, the
    nightly pass): never a page build. How many records it wrote."""
    written = 0
    for prefix in RECORDS:
        record = kv_get_json(conn, f"{prefix}{song.id}")
        if not isinstance(record, dict) or not song.audio_path:
            continue
        if _own_audio(song, record.get("audio"), record.get("audio_mtime")):
            if isinstance(record.get(AUDIO_SHA256), str):
                continue
            key = audio_key(song.audio_path, song.audio_mtime)
            if not key:
                continue
            followed = {**record, **key}
        elif _same_bytes(song, record):
            followed = {**record, "audio": song.audio_path, "audio_mtime": song.audio_mtime,
                        **audio_key(song.audio_path, song.audio_mtime)}
        else:
            continue
        kv_set_json(conn, f"{prefix}{song.id}", followed)
        written += 1
    return written


def _noted(song: Song) -> dict[str, Any]:
    """A record's members naming the song's audio as it is now: its path, mtime and content key."""
    key = audio_key(song.audio_path, song.audio_mtime)
    return {"audio": song.audio_path, "audio_mtime": song.audio_mtime, **key}


def keep_transcript(conn: sqlite3.Connection, song: Song, transcript: Transcript) -> None:
    """The song's transcript kept, with its audio's content key: its audio heard, so neither nothing sung nor
    Whisper's refusal of it stands."""
    kv_set_json(conn, f"{TRANSCRIPT}{song.id}", {**transcript.as_json(), **audio_key(transcript.audio, transcript.audio_mtime)})
    kv_delete(conn, f"{HEARD_NOTHING}{song.id}")
    kv_delete(conn, f"{WHISPER_CANT_READ}{song.id}")
    kv_delete(conn, f"{HEARING_FAILED}{song.id}")


def transcript_of(conn: sqlite3.Connection, song: Song) -> Transcript | None:
    """The kept transcript, only while its audio is the song's own."""
    record = kv_get_json(conn, f"{TRANSCRIPT}{song.id}")
    kept = Transcript.from_json(record)
    if kept is None or not of_audio(song, record):
        return None
    return kept


def note_heard_nothing(conn: sqlite3.Connection, song: Song, stamp: str, *, why: str, by: str) -> None:
    """The song's current audio noted to have nothing sung, at ``stamp``: ``why`` (words.py's "sung 6.2 s", "5 words
    in 1:10 sung", or "you said so") and ``by`` whom ("caracole", by those rules; "you", the owner's word:
    ``said_not_sung``)."""
    kv_set_json(conn, f"{HEARD_NOTHING}{song.id}", {**_noted(song), "at": stamp, "why": why, "by": by})
    kv_delete(conn, f"{WHISPER_CANT_READ}{song.id}")
    kv_delete(conn, f"{HEARING_FAILED}{song.id}")


def said_not_sung(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the owner said the song's current audio isn't sung (``by`` "you"): a new file is a new start."""
    kept = kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")
    return isinstance(kept, dict) and kept.get("by") == "you" and of_audio(song, kept)


def heard_nothing(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the song's current audio was transcribed to nothing, or the owner said it isn't sung."""
    kept = kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")
    return of_audio(song, kept)


def drop_transcript(conn: sqlite3.Connection, song: Song, stamp: str) -> None:
    """The owner's "it isn't sung": the song's transcript dropped, and its audio noted not sung by their word, so that
    nothing hears that audio again (the card's, the nightly pass's, a sheet from a video's) until they say it is."""
    kv_delete(conn, f"{TRANSCRIPT}{song.id}")
    note_heard_nothing(conn, song, stamp, why="you said so", by="you")


def note_whisper_cant_read(conn: sqlite3.Connection, song: Song, stamp: str, error: str) -> None:
    """The song's current audio noted as audio Whisper can't load, at ``stamp``, with its ``error`` in one line: its
    words were never heard, so no verdict of nothing sung on it stands either, nor a failed hearing."""
    kv_set_json(conn, f"{WHISPER_CANT_READ}{song.id}", {**_noted(song), "at": stamp, "error": error})
    kv_delete(conn, f"{HEARD_NOTHING}{song.id}")
    kv_delete(conn, f"{HEARING_FAILED}{song.id}")


def note_hearing_failed(conn: sqlite3.Connection, song: Song, stamp: str, words: str) -> None:
    """The song's current audio noted as one whose hearing failed for a setup-type reason, at ``stamp``, in
    ``words``: the nightly pass passes over it for ``RETRY_DAYS``, or until the audio changes."""
    kv_set_json(conn, f"{HEARING_FAILED}{song.id}", {**_noted(song), "at": stamp, "words": words})


def hearing_failed(conn: sqlite3.Connection, song: Song, now: datetime) -> str | None:
    """Why the song's current audio failed to be heard within ``RETRY_DAYS`` of ``now`` (its words, "" for none
    said), or None: no such note, one of other audio, or one older than that."""
    kept = kv_get_json(conn, f"{HEARING_FAILED}{song.id}")
    if not isinstance(kept, dict) or not of_audio(song, kept):
        return None
    if before(kept.get("at") if isinstance(kept.get("at"), str) else None, now - timedelta(days=RETRY_DAYS)):
        return None
    words = kept.get("words")
    return words if isinstance(words, str) else ""


def whisper_cant_read(conn: sqlite3.Connection, song: Song) -> str | None:
    """Why Whisper couldn't load the song's current audio (its error, "" for none said), or None when it isn't
    noted so: a note of other audio is none."""
    kept = kv_get_json(conn, f"{WHISPER_CANT_READ}{song.id}")
    if not isinstance(kept, dict) or not of_audio(song, kept):
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
        return LYRICS_ARE.format(status=song.lyrics_status)
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
        elif (heard_nothing(conn, s) and whisper_cant_read(conn, s) is None
              and why_not_offered(conn, cfg, s, overrides, anyway=True) is None):
            (unsung if said_not_sung(conn, s) else nothing).append(s.id)
    return {"songs": sorted(songs), "nothing": sorted(nothing), "unsung": sorted(unsung),
            "transcribed": sorted(transcribed)}
