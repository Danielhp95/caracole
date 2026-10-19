"""The assisted Guitar Pro inbox (plan §3).

UG's download endpoint is disallowed for bots, so tabarr never downloads
Guitar Pro or Power Tab files. It lists the pages it picked on the to-do page;
you click Download and drop the files into ``Library/_inbox/``; this module
files each one under its song as ``guitar-<rank>.<ext>``, or under the lowest
free number when another file already holds that one: a file is never replaced.

Anyone who can write to the library can put a symbolic link in the inbox, so
only regular files are read; a link is refused and left where it is.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from tabarr.library import NotRegularFile, keep_file, read_regular, song_dir
from tabarr.normalize import clean_title, identity_key, slug_key
from tabarr.songs import Song, get_song
from tabarr.versions import VersionRow, picks

GP_EXTENSIONS = (".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb")
GUITAR_FILE_KINDS = ("guitar-pro", "power")
_VERSION = re.compile(r"\(\s*ver\.?\s*(\d+)[^)]*\)", re.IGNORECASE)
_PARENS = re.compile(r"\s*\([^)]*\)")
_GUITAR_FILE = re.compile(r"guitar-(\d+)\.", re.IGNORECASE)
MATCH_CUTOFF = 90


@dataclass
class InboxStats:
    filed: list[Path] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)
    unmatched: list[Path] = field(default_factory=list)
    refused: list[Path] = field(default_factory=list)  # symbolic links and the like, never read


def parse_download_name(name: str) -> tuple[str | None, str, int | None]:
    """``"Artist - Title (ver 2).gp5"`` → ("Artist", "Title", 2)."""
    stem = Path(name).stem
    m = _VERSION.search(stem)
    version = int(m.group(1)) if m else None
    stem = _PARENS.sub("", stem).strip()
    artist, sep, title = stem.partition(" - ")
    if sep and artist.strip() and title.strip():
        return artist.strip(), title.strip(), version
    return None, stem, version


def _open_picks(conn: sqlite3.Connection, song_id: int) -> list[VersionRow]:
    taken = {r[0] for r in conn.execute("SELECT version_id FROM files WHERE song_id = ?", (song_id,))}
    return [v for v in picks(conn, song_id, GUITAR_FILE_KINDS) if v.id not in taken]


def _songs_with_open_picks(conn: sqlite3.Connection) -> list[tuple[Song, list[VersionRow]]]:
    ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT song_id FROM versions WHERE kind IN ('guitar-pro', 'power') AND pick_rank IS NOT NULL"
    )]
    out = []
    for sid in ids:
        open_picks = _open_picks(conn, sid)
        if open_picks:
            out.append((get_song(conn, sid), open_picks))
    return out


def _match(artist: str | None, title: str, candidates: list[tuple[Song, list[VersionRow]]]):
    if artist:
        key = identity_key(artist, title)
        for song, open_picks in candidates:
            if song.key == key:
                return song, open_picks
        a = slug_key(artist).replace("-", " ")
    t = slug_key(clean_title(title))
    best, best_score = None, 0.0
    for song, open_picks in candidates:
        title_score = fuzz.ratio(t, slug_key(clean_title(song.title)))
        if artist:
            sa = slug_key(song.artist).replace("-", " ")
            score = min(title_score, max(fuzz.ratio(a, sa), fuzz.token_set_ratio(a, sa)))
        else:
            score = title_score
        if score >= MATCH_CUTOFF and score > best_score:
            best, best_score = (song, open_picks), score
    if best is None or artist:
        return best
    # A name without an artist is only trusted when exactly one song fits.
    fits = [c for c in candidates if fuzz.ratio(t, slug_key(clean_title(c[0].title))) >= MATCH_CUTOFF]
    return best if len(fits) == 1 else None


def _choose_pick(open_picks: list[VersionRow], version: int | None, ext: str) -> VersionRow:
    """The pick of the file's kind with its version number, else the first of its kind, else the first.

    UG numbers versions within each type, so a song's Guitar Pro and Power Tab
    picks are often both "ver 1": the number alone can't tell them apart.
    """
    wanted_kind = "power" if ext == ".ptb" else "guitar-pro"
    same_kind = [v for v in open_picks if v.kind == wanted_kind]
    if version is not None:
        for v in same_kind:
            if v.version == version:
                return v
    return same_kind[0] if same_kind else open_picks[0]


def _free_number(conn: sqlite3.Connection, library_dir: Path, song: Song, rank: int) -> int:
    """The N of a new ``guitar-N`` file: the pick's rank, or the lowest number no file holds.

    Picks are ranked again as versions appear, so the rank may be the number of
    a file you downloaded for another version, or put in the folder yourself.
    That file is never replaced. A number is taken by any kept file, or any file
    in the folder, named ``guitar-N.*``, whatever its extension.
    """
    names = {r[0] for r in conn.execute("SELECT name FROM files WHERE song_id = ?", (song.id,))}
    try:
        names.update(os.listdir(song_dir(library_dir, song)))
    except FileNotFoundError:
        pass
    taken = {int(m.group(1)) for n in names if (m := _GUITAR_FILE.match(n))}
    if rank not in taken:
        return rank
    return next(n for n in itertools.count(1) if n not in taken)


def file_inbox(conn: sqlite3.Connection, library_dir: Path) -> InboxStats:
    """File every Guitar Pro / Power Tab download in ``_inbox/`` under its song."""
    stats = InboxStats()
    inbox = library_dir / "_inbox"
    if not inbox.is_dir():
        return stats
    for path in sorted(p for p in inbox.iterdir() if not p.name.startswith(".")):
        if path.is_symlink():
            stats.refused.append(path)
            continue
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in GP_EXTENSIONS:
            stats.unmatched.append(path)
            continue
        try:
            data = read_regular(path)
        except NotRegularFile:  # swapped for a link since it was listed
            stats.refused.append(path)
            continue
        sha = hashlib.sha256(data).hexdigest()
        if conn.execute("SELECT 1 FROM files WHERE sha256 = ? LIMIT 1", (sha,)).fetchone():
            path.unlink()
            stats.duplicates.append(path)
            continue
        artist, title, version = parse_download_name(path.name)
        found = _match(artist, title, _songs_with_open_picks(conn))
        if found is None:
            stats.unmatched.append(path)
            continue
        song, open_picks = found
        chosen = _choose_pick(open_picks, version, ext)
        name = f"guitar-{_free_number(conn, library_dir, song, chosen.pick_rank or 1)}{ext}"
        if keep_file(conn, library_dir, song=song, version_id=chosen.id, name=name, data=data, rank=chosen.pick_rank or 1):
            stats.filed.append(song_dir(library_dir, song) / name)
        else:
            stats.duplicates.append(path)
        path.unlink()
    return stats
