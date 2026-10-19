"""The assisted inbox: Guitar Pro files from Ultimate Guitar, and scores from MuseScore (plan §3).

UG's download endpoint is disallowed for bots, so caracole never downloads
Guitar Pro or Power Tab files there. It lists the pages it picked on the to-do page;
you click Download and drop the files into ``Library/_inbox/``; this module
files each one under its song as ``guitar-<rank>.<ext>``, or under the lowest
free number when another file already holds that one: a file is never replaced.

MuseScore's downloads need a login, so its pages are listed too (musescore.py), and a
score you download there (``SCORE_EXTENSIONS``) is filed as the song's ``score-N.<ext>``,
N the lowest number no file of that extension holds: never as ``sheet.pdf``, which
caracole renders itself. A score is placed by its name, "Artist - Title.ext" (or the
title alone, when one song has it), and a MusicXML one also by the title and creator its
header gives (musicxml.py). Its version is the song's one ``inbox`` version of kind
``score``: caracole can't tell where you got the file.

Anyone who can write to the library can put a symbolic link in the inbox, so
only regular files are read; a link is refused and left where it is. So is a
link in place of ``_inbox`` itself, and nothing it points at is touched.
"""

from __future__ import annotations

import errno
import hashlib
import itertools
import os
import re
import sqlite3
import stat
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from caracole.library import NotRegularFile, keep_file, song_dir
from caracole.musicxml import header
from caracole.normalize import clean_title, compact, identity_key, name_forms, slug_key
from caracole.songs import Song, get_song, list_songs, utc_now_iso
from caracole.versions import VersionRow, picks, upsert_version

GP_EXTENSIONS = (".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb")
GUITAR_FILE_KINDS = ("guitar-pro", "power")
# What MuseScore downloads: its own format, MusicXML (compressed or not), PDF and MIDI.
SCORE_EXTENSIONS = (".mscz", ".mxl", ".musicxml", ".pdf", ".mid", ".midi")
SCORE_KIND = "score"
_MUSICXML = (".mxl", ".musicxml")
_VERSION = re.compile(r"\(\s*ver\.?\s*(\d+)[^)]*\)", re.IGNORECASE)
_PARENS = re.compile(r"\s*\([^)]*\)")
_GUITAR_FILE = re.compile(r"guitar-(\d+)\.", re.IGNORECASE)
_SCORE_FILE = re.compile(r"score-(\d+)(\.[A-Za-z0-9]+)")
MATCH_CUTOFF = 90


@dataclass
class InboxStats:
    filed: list[Path] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)
    unmatched: list[Path] = field(default_factory=list)
    refused: list[Path] = field(default_factory=list)  # symbolic links (_inbox itself, if one), never read


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
    """The song a download is of: by identity, else the closest, by the forms of the names UG gave
    it (``normalize.name_forms``), which it writes in two scripts for some artists."""
    if artist:
        key = identity_key(artist, title)
        for song, open_picks in candidates:
            if song.key == key:
                return song, open_picks
    titles = name_forms(clean_title(title))
    best, best_score = None, 0.0
    for song, open_picks in candidates:
        score = _title_score(titles, song)
        if artist:
            score = min(score, _artist_score(artist, song.artist))
        if score >= MATCH_CUTOFF and score > best_score:
            best, best_score = (song, open_picks), score
    if best is None or artist:
        return best
    # A name without an artist is only trusted when exactly one song fits.
    fits = [c for c in candidates if _title_score(titles, c[0]) >= MATCH_CUTOFF]
    return best if len(fits) == 1 else None


def _title_score(titles: tuple[str, ...], song: Song) -> float:
    """How alike a download's title forms and a song's title are, 0-100."""
    return max((fuzz.ratio(t, s) for t in titles for s in name_forms(clean_title(song.title))), default=0.0)


def _artist_score(artist: str, other: str) -> float:
    """How alike two artists' names are, compared as words (``token_set_ratio``) and whole."""
    words = [k.replace("-", " ") for k in name_forms(other)]
    return max(
        (max(fuzz.ratio(a, b), fuzz.token_set_ratio(a, b))
         for a in (k.replace("-", " ") for k in name_forms(artist)) for b in words),
        default=0.0,
    )


def _choose_pick(open_picks: list[VersionRow], version: int | None, ext: str) -> VersionRow:
    """The pick of the file's kind and version number, else the first of its kind, else the first.

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


def guitar_number(conn: sqlite3.Connection, library_dir: Path, song: Song, rank: int) -> int:
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


def score_number(conn: sqlite3.Connection, library_dir: Path, song: Song, ext: str) -> int:
    """The N of a new ``score-N<ext>`` file: the lowest number no file of the song with that
    extension holds, kept or put in the folder by hand. The formats of one score so take one
    number: ``score-1.mscz`` beside ``score-1.pdf``."""
    names = {r[0] for r in conn.execute("SELECT name FROM files WHERE song_id = ?", (song.id,))}
    try:
        names.update(os.listdir(song_dir(library_dir, song)))
    except FileNotFoundError:
        pass
    taken = {int(m.group(1)) for n in names if (m := _SCORE_FILE.fullmatch(n)) and m.group(2).lower() == ext}
    return next(n for n in itertools.count(1) if n not in taken)


def _score_song(conn: sqlite3.Connection, name: str, ext: str, data: bytes) -> Song | None:
    """The song a score is of: by its name, as for a Guitar Pro file but among every song not
    ignored, else (MusicXML) by its header's title and creator, when exactly one song has both."""
    songs = [s for s in list_songs(conn) if s.status != "ignored"]
    artist, title, _ = parse_download_name(name)
    found = _match(artist, title, [(s, []) for s in songs])
    if found is not None:
        return found[0]
    head = header(data, ext) if ext in _MUSICXML else None
    if head is None:
        return None
    wanted = slug_key(clean_title(head.title))
    creators = {key for c in head.creators if (key := slug_key(c))}
    fits = [
        s for s in songs
        if _same_key(slug_key(clean_title(s.title)), wanted)
        and any(_same_key(slug_key(a), c) for a in (s.artists or [s.artist]) for c in creators)
    ]
    return fits[0] if wanted and len(fits) == 1 else None


def _same_key(a: str, b: str) -> bool:
    return bool(a) and (a == b or compact(a) == compact(b))


def _score_version(conn: sqlite3.Connection, song: Song) -> int:
    """The song's one version for the scores filed from the inbox."""
    return upsert_version(
        conn, provider="inbox", tab_id=SCORE_KIND, song_id=song.id, slot="guitar", kind=SCORE_KIND, rating=0,
        votes=0, version=1, label=None, url="", raw={}, now=utc_now_iso(),
    )


def _read_entry(inbox_fd: int, name: str) -> bytes:
    """The bytes of the regular file ``name`` in the inbox open at ``inbox_fd``, read the way
    ``library.read_regular`` reads a path: never through a link, never waiting on a FIFO."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=inbox_fd)
    except OSError as e:
        if e.errno == errno.ELOOP:  # O_NOFOLLOW's answer for a link
            raise NotRegularFile(e.errno, "a symbolic link, which caracole doesn't follow", name) from None
        raise
    with open(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise NotRegularFile(errno.EINVAL, "not a regular file", name)
        return f.read()


def file_inbox(conn: sqlite3.Connection, library_dir: Path) -> InboxStats:
    """File every Guitar Pro / Power Tab download in ``_inbox/`` under its song.

    The folder is opened without following a link, then listed, read and emptied through that
    descriptor. A link in place of ``_inbox`` is refused (``refused`` holds it): nothing in the
    folder it points at is read, filed or deleted.
    """
    stats = InboxStats()
    inbox = library_dir / "_inbox"
    try:
        inbox_fd = os.open(inbox, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        if inbox.is_symlink():  # Linux answers ENOTDIR for a link here, whatever it points at
            stats.refused.append(inbox)
            return stats
        if isinstance(e, (FileNotFoundError, NotADirectoryError)):  # no inbox yet, or a file of that name
            return stats
        raise
    try:
        with os.scandir(inbox_fd) as found:
            entries = sorted((e.name, e.is_symlink(), e.is_file(follow_symlinks=False))
                             for e in found if not e.name.startswith("."))
        for entry, link, regular in entries:
            path = inbox / entry  # for the stats: the file itself is only ever reached through inbox_fd
            if link:
                stats.refused.append(path)
                continue
            if not regular:
                continue
            ext = path.suffix.lower()
            if ext not in GP_EXTENSIONS and ext not in SCORE_EXTENSIONS:
                stats.unmatched.append(path)
                continue
            try:
                data = _read_entry(inbox_fd, entry)
            except NotRegularFile:  # swapped for a link since it was listed
                stats.refused.append(path)
                continue
            sha = hashlib.sha256(data).hexdigest()
            if conn.execute("SELECT 1 FROM files WHERE sha256 = ? LIMIT 1", (sha,)).fetchone():
                os.unlink(entry, dir_fd=inbox_fd)
                stats.duplicates.append(path)
                continue
            if ext in SCORE_EXTENSIONS:
                song = _score_song(conn, entry, ext, data)
                if song is None:
                    stats.unmatched.append(path)
                    continue
                n = score_number(conn, library_dir, song, ext)
                name = f"score-{n}{ext}"
                if keep_file(conn, library_dir, song=song, version_id=_score_version(conn, song), name=name,
                             data=data, rank=n):
                    stats.filed.append(song_dir(library_dir, song) / name)
                else:
                    stats.duplicates.append(path)
                os.unlink(entry, dir_fd=inbox_fd)
                continue
            artist, title, version = parse_download_name(entry)
            found = _match(artist, title, _songs_with_open_picks(conn))
            if found is None:
                stats.unmatched.append(path)
                continue
            song, open_picks = found
            chosen = _choose_pick(open_picks, version, ext)
            name = f"guitar-{guitar_number(conn, library_dir, song, chosen.pick_rank or 1)}{ext}"
            if keep_file(conn, library_dir, song=song, version_id=chosen.id, name=name, data=data,
                         rank=chosen.pick_rank or 1):
                stats.filed.append(song_dir(library_dir, song) / name)
            else:
                stats.duplicates.append(path)
            os.unlink(entry, dir_fd=inbox_fd)
    finally:
        os.close(inbox_fd)
    return stats
