"""The Music/ folder: tracks you bought, used only as audio for auto-chords.

Tabarr never adds songs from here (plan §1); it only links a purchase to a
song you already want, by tags (or the file name) and duration.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mutagen
from rapidfuzz import fuzz

from tabarr.normalize import clean_title, identity_key, slug_key
from tabarr.songs import Song, list_songs, update_song

AUDIO_EXTENSIONS = (
    ".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus", ".wav", ".aiff", ".aif",
    ".wma", ".ape", ".wv",
)
DURATION_TOLERANCE_S = 3.0
MATCH_CUTOFF = 90
_TRACK_PREFIX = re.compile(r"^\d{1,3}(?:\s*[-.]\s*|\s+)")

_ARTIST_KEYS = ("artist", "albumartist", "TPE1", "TPE2", "©ART", "aART", "Author")
_TITLE_KEYS = ("title", "TIT2", "©nam", "Title")
_ALBUM_KEYS = ("album", "TALB", "©alb")


@dataclass(frozen=True)
class AudioFile:
    path: Path
    artist: str | None
    title: str | None
    album: str | None
    duration_s: float | None
    mtime: float


@dataclass
class ScanStats:
    seen: int = 0
    matched: int = 0
    unmatched: list[Path] = field(default_factory=list)


def _first(tags: Any, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        try:
            value = tags.get(key)
        except (KeyError, ValueError, TypeError):
            value = None
        if value is None:
            continue
        if hasattr(value, "text"):  # an ID3 frame
            value = value.text
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value and str(value).strip():
            return str(value).strip()
    return None


def _from_name(path: Path) -> tuple[str | None, str | None]:
    """"Artist - Title.ext", or "Artist/Album/03 - Title.ext"."""
    stem = path.stem
    left, sep, right = stem.partition(" - ")
    if sep and left.strip() and right.strip() and not left.strip().isdigit():
        return left.strip(), right.strip()
    title = _TRACK_PREFIX.sub("", stem).strip()
    if title.startswith("- "):
        title = title[2:].strip()
    artist = path.parent.parent.name if path.parent.parent != path.parent else None
    return (artist or None), (title or None)


def read_audio(path: Path) -> AudioFile:
    """Tags and duration of an audio file, falling back to its name when there are no tags."""
    try:
        f = mutagen.File(path, easy=True)
    except (mutagen.MutagenError, OSError, ValueError):
        f = None
    tags = getattr(f, "tags", None) if f is not None else None
    artist = _first(tags, _ARTIST_KEYS) if tags is not None else None
    title = _first(tags, _TITLE_KEYS) if tags is not None else None
    album = _first(tags, _ALBUM_KEYS) if tags is not None else None
    if not artist or not title:
        name_artist, name_title = _from_name(path)
        artist = artist or name_artist
        title = title or name_title
    info = getattr(f, "info", None) if f is not None else None
    length = getattr(info, "length", None)
    return AudioFile(
        path=path, artist=artist, title=title, album=album,
        duration_s=float(length) if length else None, mtime=os.stat(path).st_mtime,
    )


def _duration_ok(af: AudioFile, song: Song) -> bool:
    if af.duration_s is None or not song.duration_ms:
        return True
    return abs(af.duration_s - song.duration_ms / 1000) <= DURATION_TOLERANCE_S


def match_audio(af: AudioFile, songs: list[Song]) -> Song | None:
    """The wanted song a purchased file belongs to, or None."""
    if not af.artist or not af.title:
        return None
    key = identity_key(af.artist, af.title)
    for s in songs:
        if s.key == key:
            return s if _duration_ok(af, s) else None
    a_key = slug_key(af.artist).replace("-", " ")
    t_key = slug_key(clean_title(af.title))
    best, best_score = None, 0.0
    for s in songs:
        sa = slug_key(s.artist).replace("-", " ")
        artist_score = max(fuzz.ratio(a_key, sa), fuzz.token_set_ratio(a_key, sa))
        title_score = fuzz.ratio(t_key, slug_key(clean_title(s.title)))
        score = min(artist_score, title_score)
        if score >= MATCH_CUTOFF and score > best_score and _duration_ok(af, s):
            best, best_score = s, score
    return best


def scan_music(conn: sqlite3.Connection, music_dir: Path) -> ScanStats:
    """Link purchased files to wanted songs (``songs.audio_path``); forget files that are gone."""
    stats = ScanStats()
    songs = [s for s in list_songs(conn) if s.status != "ignored"]
    for s in songs:
        if s.audio_path and not Path(s.audio_path).exists():
            update_song(conn, s.id, audio_path=None, audio_mtime=None)
            s.audio_path, s.audio_mtime = None, None
    if not music_dir.is_dir():
        return stats
    for path in sorted(p for p in music_dir.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS):
        stats.seen += 1
        af = read_audio(path)
        song = match_audio(af, songs)
        if song is None:
            stats.unmatched.append(path)
            continue
        stats.matched += 1
        if song.audio_path and song.audio_path != str(path) and Path(song.audio_path).exists():
            continue  # already linked to another copy of the same track
        if song.audio_path != str(path) or song.audio_mtime != af.mtime:
            update_song(conn, song.id, audio_path=str(path), audio_mtime=af.mtime)
            song.audio_path, song.audio_mtime = str(path), af.mtime
    return stats
