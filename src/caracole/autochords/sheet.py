"""The sheet half of auto-chords: a song's auto sheet laid out from what the models heard, with no model and no audio.

run.py hears a song's audio (``_hear``: BTC's chords, beat_this's beats and downbeats, and the audio's length as
``music.read_audio`` reads it) into a ``Heard``; everything after that is here, and reads nothing but the song's
record and what was heard: ``make_sheet`` lays the chords out over the song's lyrics (``synced_for``: its timed ones
where they fit the length heard, as LRCLIB timed them or shifted by ``align.lyrics_offset``; else its plain ones, else
a transcript of its audio, else none), and ``raw_of`` is the record its version keeps. ``synced_key``,
``lyrics_key`` and ``wider_lines`` are what that record keeps of the song's lyrics, which run.py's ``_skip_reason``
compares with the song's now.

Imports no model and no audio reader (music.py, mutagen), and the lyrics module only where a song's are read:
sheet_lyrics.py, which render.py imports in any package, takes ``lyrics_key`` from here.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from caracole.autochords.align import lyrics_offset, shifted_lrc
from caracole.autochords.merge import (
    NO_CHORD,
    ChordSegment,
    LrcLine,
    build_sheet,
    parse_lrc,
    parse_lrc_words,
)
from caracole.autochords.transcript import LYRICS_SOURCE, NOT_SUNG, NOTE, SILENT, Transcript
from caracole.chordpro import display_columns
from caracole.keys import estimate_key
from caracole.songs import Song

if TYPE_CHECKING:
    from caracole.lyrics import Lyrics
    from caracole.youtube import Video

log = logging.getLogger(__name__)

MODEL = "btc_large_voca"
SYNC_TOLERANCE_S = 2.0  # LRCLIB's own tolerance when it matches a duration
COLUMNS = "display"  # what a sheet's chord lines count, in its version's raw: display columns (merge._on_words)


@dataclass(frozen=True)
class Heard:
    """What the models heard in a song's audio: its chords, its beats and downbeats, and its length in seconds as
    ``music.read_audio`` reads the file (None when it names none), the one length the sheet is laid out against."""

    segments: list[ChordSegment]
    beats: Sequence[float]
    downbeats: Sequence[float]
    duration: float | None


@dataclass(frozen=True)
class Timed:
    """Synced lyrics that fit the audio: their LRC text and, when LRCLIB timed them for audio of
    another length, the seconds they were shifted by to fit it (``shift``, 0.0 for none) and how
    much longer the audio is (``longer``, less than 0 for shorter)."""

    text: str
    shift: float | None = None
    longer: float = 0.0

    def note(self) -> str | None:
        """What the sheet says of a shift, so that a wrong one shows; None for lyrics that fit as timed."""
        if self.shift is None:
            return None
        if self.shift:
            later = "later" if self.shift > 0 else "earlier"
            return f"Lyrics' timing shifted {abs(self.shift):.1f} s {later} to fit this audio"
        than = "shorter" if self.longer > 0 else "longer"
        return f"Lyrics' timing unshifted: LRCLIB's audio is {abs(self.longer):.1f} s {than}"


@dataclass(frozen=True)
class Made:
    """One song's auto sheet: its text, which lyrics it used ("synced", "plain" or "none"), the key of the chords
    heard (None when they fit no key), the seconds its timed lyrics were shifted by to fit the audio (None when
    LRCLIB timed them for audio of the same length, or they weren't used), and the transcript it was made over
    (None unless the words are Whisper's)."""

    text: str
    used: str
    key: str | None
    shift: float | None
    transcript: Transcript | None = None
    silent: bool = False
    said: bool = False  # silent by the owner's word, not by what was heard


def instrumental(song: Song) -> bool:
    """Whether a site says the song is instrumental: its verdict wins over a transcript, which it never gets."""
    from caracole.lyrics import song_lyrics

    if song.lyrics_status == "instrumental":
        return True
    lyrics = song_lyrics(song)
    return lyrics is not None and lyrics.instrumental and not lyrics.has_lyrics


def sung_lyrics(song: Song) -> Lyrics | None:
    """The song's stored lyrics, when they have words (an instrumental has none)."""
    from caracole.lyrics import song_lyrics

    lyrics = song_lyrics(song)
    return lyrics if lyrics is not None and lyrics.has_lyrics else None


def lyrics_key(plain: str) -> str:
    """The key of the words an auto sheet was made over, kept as its version's ``raw["lyrics_key"]``: 16 hex digits of
    the SHA-256 of the plain lyrics with each line stripped of the spaces around it, every run of blank lines one
    blank line and none at either end. So the same words stored again (timed otherwise, a stanza break of two lines, a
    trailing space, CRLF) keep their key, and any other letter, case or punctuation, which the sheet shows, is other
    words."""
    lines: list[str] = []
    for line in plain.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


def song_lyrics_key(song: Song) -> str | None:
    """The key of the song's stored lyrics' words (``lyrics_key`` of their plain text), which an auto sheet made over
    them keeps as ``lyrics_key``: it is made again once they are other words. None when the song has no words, or its
    lyrics can't be read."""
    try:
        lyrics = sung_lyrics(song)
    except (TypeError, ValueError):
        return None
    return lyrics_key(lyrics.plain) if lyrics is not None else None


def synced_key(song: Song) -> str | None:
    """A short hash of the song's timed lyrics, which its auto sheet's version keeps as ``synced_lyrics``: a sheet
    over plain lyrics is made again only once other timed lyrics than those come. None when it has none, or its
    lyrics can't be read."""
    try:
        lyrics = sung_lyrics(song)
    except (TypeError, ValueError):
        return None
    if lyrics is None or not lyrics.synced:
        return None
    return hashlib.sha256(lyrics.synced.encode("utf-8")).hexdigest()[:16]


def wider_lines(song: Song) -> bool:
    """Whether the song's timed lyrics have a line whose display columns aren't its characters' indexes: a
    Chinese character is two columns wide, a combining accent none. False for lyrics that can't be read."""
    try:
        lyrics = sung_lyrics(song)
    except (TypeError, ValueError):
        return False
    if lyrics is None or not lyrics.synced:
        return False
    return any(display_columns(text) != list(range(len(text) + 1)) for _, text in parse_lrc(lyrics.synced))


def synced_for(song: Song, lyrics: Lyrics | None, heard: Heard) -> Timed | None:
    """The synced lyrics, if their timings fit the audio heard (``heard.duration``): as they are when the durations
    agree within 2 s, else moved by the shift ``align.lyrics_offset`` finds clearly from the chords heard and the
    beats; None when it finds none."""
    if lyrics is None or not lyrics.synced or lyrics.duration is None:
        return None
    duration = heard.duration
    if duration is None:
        return None
    longer = duration - lyrics.duration
    if abs(longer) <= SYNC_TOLERANCE_S:
        return Timed(lyrics.synced)
    lines = parse_lrc(lyrics.synced)
    try:
        found = lyrics_offset(lines, heard.segments, heard.beats, heard.downbeats, audio_s=duration,
                              lyrics_s=lyrics.duration)
    except Exception:  # noqa: BLE001 - a bug here must not pass for a purchase auto-chords can't read
        log.exception("%s: looking for how far to shift LRCLIB's timed lyrics failed; the plain lyrics instead",
                      song.display)
        return None
    than = "longer" if longer > 0 else "shorter"
    if found.offset is None:
        log.info("%s: the audio is %.1f s %s than LRCLIB's timed lyrics, and no shift fits them to it clearly "
                 "(%s): the plain lyrics instead", song.display, abs(longer), than, found.why)
        return None
    log.info("%s: the audio is %.1f s %s than LRCLIB's timed lyrics, which fit it shifted by %+.1f s (%s)",
             song.display, abs(longer), than, found.offset, found.why)
    text = shifted_lrc(lyrics.synced, found.offset) if found.offset else lyrics.synced
    return Timed(text, found.offset, longer)


def _word_timed(synced: str | None) -> list[LrcLine] | None:
    """The synced lyrics read with their word stamps, when they time words (enhanced LRC)."""
    lines = parse_lrc_words(synced) if synced else []
    return lines if any(line.words for line in lines) else None


def make_sheet(song: Song, heard: Heard, *, source: str | None = None, transcript: Transcript | None = None,
               silent: bool = False, said: bool = False) -> Made:
    """One song's auto sheet, from what was heard in its audio. ``source`` says where that came from, when it wasn't
    a purchase, on the sheet's line after the song's name; the shift has the line after it.

    The song's lyrics from a site, whenever it has any (and a site's word that it is
    instrumental wins too), else its ``transcript`` (Whisper's words from this
    very audio: timed lyrics whose duration is the audio's, so they fit as they are and no shift is searched,
    with NOTE on the line after the shift's), else none. ``silent`` (the audio noted as having nothing sung)
    puts SILENT there instead, only where no site has lyrics, none says it is instrumental and no transcript is used;
    NOT_SUNG where it is the owner's word (``said``, ``transcript.said_not_sung``), not what was heard.

    The key is estimated from the chords as recognized, each weighed by how long it sounds,
    before they are snapped to beats and laid out.
    """
    segments, beats, downbeats = heard.segments, heard.beats, heard.downbeats
    key = estimate_key((s.label, s.end - s.start) for s in segments if s.label != NO_CHORD)
    lyrics = sung_lyrics(song)
    over = transcript if lyrics is None and not instrumental(song) else None
    timed = Timed(over.lrc) if over is not None else synced_for(song, lyrics, heard)
    synced = timed.text if timed is not None else None
    plain = lyrics.plain if lyrics is not None else None
    # The shift on a line of its own after the credit: render.py takes that line for the credit, and the viewer of
    # a sheet from YouTube draws the video in its place, so the shift is the first of the sheet's own words
    silent = silent and lyrics is None and over is None and not instrumental(song)
    said = said and silent
    notes = (source, timed.note() if timed is not None else None, NOTE if over is not None else None,
             (NOT_SUNG if said else SILENT) if silent else None)
    note = "\n".join(part for part in notes if part)
    text = build_sheet(
        segments,
        title=song.title,
        artist=song.artist,
        synced=synced,
        synced_words=_word_timed(synced),
        plain=plain,
        beats=beats,
        downbeats=downbeats,
        source=note or None,
    )
    shift = timed.shift if timed is not None else None
    return Made(text, "synced" if synced else "plain" if plain else "none", key, shift, over, silent, said)


def raw_of(song: Song, made: Made, *, video: Video | None = None) -> dict:
    """The record an auto sheet's version keeps (its ``raw``). The key heard goes into it, for ``keys.song_key``, and
    so does the shift of timed lyrics LRCLIB timed for audio of another length (``lyrics_shift``), what its chord
    lines' columns count (``columns``: ``COLUMNS``), and the timed lyrics the song had, used or not
    (``synced_lyrics``, ``synced_key``); a sheet over those lyrics, the key of their words (``lyrics_key``,
    ``song_lyrics_key``). A sheet made over a transcript keeps it as ``lyrics_source``, ``transcript`` (its LRC, for
    the viewer's sung line) and ``transcript_made_at`` (``_skip_reason`` compares it with the transcript kept now).
    Audio from YouTube (``video``) keeps the video's fields."""
    raw: dict[str, object] = {"audio": song.audio_path, "model": MODEL, "lyrics": made.used, "columns": COLUMNS}
    if made.key is not None:
        raw["key"] = made.key
    if made.shift is not None:
        raw["lyrics_shift"] = made.shift
    if made.transcript is not None:
        raw["lyrics_source"] = LYRICS_SOURCE
        raw["transcript"] = made.transcript.lrc
        raw["transcript_made_at"] = made.transcript.made_at
    if made.silent:
        raw["heard_nothing"] = True
    if made.silent and made.said:
        raw["not_sung_by"] = "you"  # the owner's word, not what was heard (youtube_sheet.HOLDS["said"])
    synced = synced_key(song)
    if synced is not None:
        raw["synced_lyrics"] = synced
    words = song_lyrics_key(song) if made.used in ("synced", "plain") and made.transcript is None else None
    if words is not None:
        raw["lyrics_key"] = words
    if video is not None:
        raw["youtube"] = video.as_json()
    return raw
