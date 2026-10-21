"""The Music/ folder: tracks you bought, used only as audio for auto-chords.

Caracole never adds songs from here (plan §1); it only links a purchase to a
song you already want, by tags (or the file name) and duration.

A file that is the song by identity (its artist and title keys) is the
song's. Only failing one, a file whose names come close may be: names are
compared as slugs, and Chinese ones as pinyin too, so 斑馬斑馬 meets 斑马斑马;
a name tagged in two scripts also by each of its parts, so "Song Dongye
(宋冬野)" meets 宋冬野 (``normalize.name_forms``).
Such a fuzzy match must lead the next candidate clearly, both ways: of the
file's songs, and of the song's titles. Album siblings ("Pt. 1" and "Pt. 2")
score alike, so they cancel out instead of the first one on disk winning.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from caracole.normalize import clean_title, identity_key, name_forms
from caracole.songs import Song, list_songs, update_song

AUDIO_EXTENSIONS = (
    ".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus", ".wav", ".aiff", ".aif",
    ".wma", ".ape", ".wv",
)
DURATION_TOLERANCE_S = 3.0
MATCH_CUTOFF = 90
MATCH_MARGIN = 8  # a fuzzy match must lead the next one by this much, as in matching
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
    import mutagen  # here, not on import: inbox.py, which the pages import, compares names with Names

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


def _duration_ok(af: AudioFile, seconds: float | None) -> bool:
    if af.duration_s is None or seconds is None:
        return True
    return abs(af.duration_s - seconds) <= DURATION_TOLERANCE_S


def _expected_seconds(song: Song) -> float | None:
    """How long a fuzzy match's file must be: the song's own duration, else LRCLIB's.

    A wanted.txt line rarely gives a duration; LRCLIB's then keeps an album
    sibling with a close title out.
    """
    if song.duration_s is not None:
        return song.duration_s
    from caracole.lyrics import song_lyrics  # here: inbox.py, which the pages import, needs no lyrics

    try:
        lyrics = song_lyrics(song)
    except (TypeError, ValueError):  # stored lyrics that can't be read: no duration
        return None
    return lyrics.duration if lyrics is not None and lyrics.duration else None


@dataclass(frozen=True)
class Names:
    """An artist's and a title's forms, as a purchase or a download meets a song: slugs, plus pinyin
    slugs for Chinese names, and each part of a name tagged in two scripts (``normalize.name_forms``).
    The artist's are words, hyphens as spaces, for ``token_set_ratio``."""

    artists: tuple[str, ...]
    titles: tuple[str, ...]

    @classmethod
    def of(cls, artist: str, title: str) -> Names:
        return cls(tuple(k.replace("-", " ") for k in name_forms(artist)), name_forms(clean_title(title)))

    def title_score(self, other: Names) -> float:
        """How alike the titles are, 0-100."""
        return max((fuzz.ratio(x, y) for x in self.titles for y in other.titles), default=0.0)

    def artist_score(self, other: Names) -> float:
        """How alike the artists are, 0-100, compared as words and whole."""
        return max(
            (max(fuzz.ratio(x, y), fuzz.token_set_ratio(x, y)) for x in self.artists for y in other.artists),
            default=0.0,
        )

    def score(self, other: Names) -> float:
        """How alike two songs' names are, 0-100: the lower of the artist and title scores.

        A title too far off for any decision is the score, the artists not compared: most of a
        Music/ folder is other songs. Exact from MATCH_CUTOFF - MATCH_MARGIN up, all ``_matches``
        looks at, and inbox.py at its cutoff of 90.
        """
        title = self.title_score(other)
        if title < MATCH_CUTOFF - MATCH_MARGIN:
            return title
        return min(self.artist_score(other), title)


@dataclass(frozen=True)
class _Match:
    song_id: int
    audio: AudioFile
    exact: bool


def _matches(audio: Sequence[AudioFile], songs: Sequence[Song]) -> list[_Match]:
    """Every file that belongs to a song, and how.

    A file named or tagged as a wanted song is that song's when the song's own
    duration, if known, agrees; otherwise it is nobody's. Each other file goes
    to the song its names are closest to, at MATCH_CUTOFF or more with the
    durations agreeing, when that song leads the file's next one by
    MATCH_MARGIN. A song with a file of its own by identity keeps only those
    with its own title (its artist written another way) as copies; any other
    song takes the files of its closest title, when that title leads the next
    different one by MATCH_MARGIN (copies of one track share a title).
    """
    by_key = {s.key: s for s in songs}
    found: list[_Match] = []
    rest: list[AudioFile] = []
    for af in audio:
        if not af.artist or not af.title:
            continue
        song = by_key.get(identity_key(af.artist, af.title))
        if song is None:
            rest.append(af)
        elif _duration_ok(af, song.duration_s):
            found.append(_Match(song.id, af, exact=True))
    exact = {m.song_id for m in found}
    names = {s.id: Names.of(s.artist, s.title) for s in songs}
    seconds = {s.id: _expected_seconds(s) for s in songs}
    claims: dict[int, list[tuple[float, tuple[str, ...], AudioFile]]] = {}
    for af in rest:
        own = Names.of(af.artist or "", af.title or "")
        scored = sorted(
            ((own.score(names[s.id]), s.id) for s in songs if _duration_ok(af, seconds[s.id])),
            reverse=True,
        )
        if not scored or scored[0][0] < MATCH_CUTOFF:
            continue
        if len(scored) > 1 and scored[0][0] - scored[1][0] < MATCH_MARGIN:
            continue  # as close to another song
        score, song_id = scored[0]
        claims.setdefault(song_id, []).append((score, own.titles, af))
    for song_id, claimed in claims.items():  # a claimed file has a title: it scored 90 on it
        if song_id in exact:
            own_titles = set(names[song_id].titles)
            claimed = [c for c in claimed if own_titles & set(c[1])]
        else:
            best: dict[str, float] = {}
            for score, titles, _ in claimed:
                best[titles[0]] = max(best.get(titles[0], 0.0), score)
            (top, top_score), *others = sorted(best.items(), key=lambda kv: -kv[1])
            if others and top_score - others[0][1] < MATCH_MARGIN:
                continue  # two titles come as close: an album's parts, say
            claimed = [c for c in claimed if c[1][0] == top]
        found += [_Match(song_id, af, exact=False) for _, _, af in claimed]
    return found


def scan_music(conn: sqlite3.Connection, music_dir: Path) -> ScanStats:
    """Link purchased files to wanted songs (``songs.audio_path``); forget files that are gone.

    A song keeps its file while that file is one of its matches; it moves to
    a file that is the song by identity when the linked one isn't. A folder
    with no audio at all, or no folder, is taken for a disk that isn't there
    tonight, so nothing is unlinked.
    """
    stats = ScanStats()
    if not music_dir.is_dir():
        return stats
    paths = sorted(
        p for p in music_dir.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not paths:
        return stats
    songs = [s for s in list_songs(conn) if s.status != "ignored"]
    for s in songs:
        if s.audio_path and not Path(s.audio_path).exists():
            update_song(conn, s.id, audio_path=None, audio_mtime=None)
            s.audio_path, s.audio_mtime = None, None
    audio = [read_audio(p) for p in paths]
    stats.seen = len(audio)
    by_song: dict[int, list[_Match]] = {}
    for m in _matches(audio, songs):
        by_song.setdefault(m.song_id, []).append(m)
    matched = {m.audio.path for mine in by_song.values() for m in mine}
    stats.matched = len(matched)
    stats.unmatched = [p for p in paths if p not in matched]
    for s in songs:
        mine = by_song.get(s.id, [])
        files = [m.audio for m in mine if m.exact] or [m.audio for m in mine]
        if not files:
            continue
        af = next((f for f in files if str(f.path) == s.audio_path), files[0])
        if s.audio_path != str(af.path) or s.audio_mtime != af.mtime:
            update_song(conn, s.id, audio_path=str(af.path), audio_mtime=af.mtime)
    return stats
