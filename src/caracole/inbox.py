"""The inbox: the Guitar Pro files and the MuseScore scores you download yourself (plan §3).

A Guitar Pro or Power Tab file you got anywhere (``GP_EXTENSIONS``), dropped into
``Library/_inbox/`` named as the song is in caracole, "Artist - Title.gp5" (or the
title alone, when one song has it), is filed under its song as ``guitar-N.<ext>``,
N the lowest number no file of the song holds, as gtptabs.com's downloads are
(gtptabs_fetch.py): a file is never replaced. Its version is the song's one
``inbox`` version of its kind, ``guitar-pro`` (``power`` for a ``.ptb``): caracole
can't tell where you got the file.

MuseScore's downloads need a login, so its pages are listed too (musescore.py), and a
score you download there (``SCORE_EXTENSIONS``) is filed as the song's ``score-N.<ext>``,
N the lowest number no file of that extension holds: never as ``sheet.pdf``, which
caracole renders itself. A score is placed by its name as a Guitar Pro file is, and a
MusicXML one also by the title and creator its header gives (musicxml.py). Its version
is the song's one ``inbox`` version of kind ``score``.

Either is placed among every song that isn't ignored.

Anyone who can write to the library can put a symbolic link in the inbox, so
only regular files are read; a link is refused and left where it is. So is a
link in place of ``_inbox`` itself, and nothing it points at is touched.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from caracole.library import KeptFile, NotRegularFile, holds, keep_file, read_regular, safe_name, song_dir
from caracole.music import Names
from caracole.musicxml import header
from caracole.normalize import clean_title, compact, has_other_script, identity_key, slug_key
from caracole.songs import Song, get_song, list_songs, utc_now_iso
from caracole.versions import upsert_version

GP_EXTENSIONS = (".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb")
# The kinds of the versions a kept Guitar Pro or Power Tab file has: one you filed from the inbox, or one gtptabs.com
# gave.
GUITAR_FILE_KINDS = ("guitar-pro", "power")
# The Guitar Pro files caracole serve's Guitar Pro page shows (alphaTab reads them all): every kind but Power Tab's.
BROWSER_EXTENSIONS = (".gp3", ".gp4", ".gp5", ".gpx", ".gp")
# What MuseScore downloads: its own format, MusicXML (compressed or not), PDF and MIDI.
SCORE_EXTENSIONS = (".mscz", ".mxl", ".musicxml", ".pdf", ".mid", ".midi")
SCORE_KIND = "score"
_MUSICXML = (".mxl", ".musicxml")
_VERSION = re.compile(r"\(\s*ver\.?\s*(\d+)[^)]*\)", re.IGNORECASE)
_PARENS = re.compile(r"\s*\([^)]*\)")
_GUITAR_FILE = re.compile(r"guitar-(\d+)\.", re.IGNORECASE)
HARMONICA_FILE = re.compile(r"harmonica-(\d+)\.txt")  # a harmonica tab caracole kept (harptabs_fetch.py)
HARMONICA_KIND = "harmonica"  # its version's kind
_SCORE_FILE = re.compile(r"score-(\d+)(\.[A-Za-z0-9]+)")
_KEPT_GUITAR = re.compile(r"guitar-(\d+)(\.[A-Za-z0-9]+)")
MATCH_CUTOFF = 90  # music.Names.score is exact from 82 up (test_inbox.py)


@dataclass
class InboxStats:
    filed: list[Path] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)
    unmatched: list[Path] = field(default_factory=list)
    refused: list[Path] = field(default_factory=list)  # symbolic links (_inbox itself, if one), never read


@dataclass(frozen=True)
class GuitarFile:
    """A Guitar Pro or Power Tab file caracole keeps for a song (``guitar-N.<ext>``, recorded in ``files``):
    filed from the inbox, or downloaded from gtptabs.com. ``path``: where it is, relative to the library."""

    song_id: int
    name: str
    path: str
    number: int

    @property
    def in_browser(self) -> bool:
        """Whether caracole serve's Guitar Pro page shows it (``BROWSER_EXTENSIONS``): not a Power Tab file."""
        return Path(self.name).suffix.lower() in BROWSER_EXTENSIONS


def guitar_files(conn: sqlite3.Connection, song_id: int | None = None, *,
                 path: str | None = None) -> list[GuitarFile]:
    """The Guitar Pro and Power Tab files caracole keeps, ``guitar-N.<ext>`` recorded for a version of either kind
    (``GUITAR_FILE_KINDS``), of the song ``song_id`` or every song's, or the one at ``path``; by song, then N."""
    sql = ("SELECT f.song_id, f.name, f.path FROM files f JOIN versions v ON v.id = f.version_id "
           f"WHERE v.kind IN ({', '.join('?' * len(GUITAR_FILE_KINDS))})")
    args: list[object] = list(GUITAR_FILE_KINDS)
    if song_id is not None:
        sql += " AND f.song_id = ?"
        args.append(song_id)
    if path is not None:
        sql += " AND f.path = ?"
        args.append(path)
    found = []
    for row_song, name, at in conn.execute(sql, args):
        m = _KEPT_GUITAR.fullmatch(name)
        if m and m.group(2).lower() in GP_EXTENSIONS:
            found.append(GuitarFile(row_song, name, at, int(m.group(1))))
    return sorted(found, key=lambda f: (f.song_id, f.number, f.name))


@dataclass(frozen=True)
class HarmonicaFile:
    """A harmonica tab caracole keeps for a song (``harmonica-N.txt``, harptabs_fetch.py): its name, where it is
    (relative to the library), its N, and the key its page's Key chip names ("C": the song's on some tabs, the
    harp's on others), or None."""

    song_id: int
    name: str
    path: str
    number: int
    key: str | None = None


def harmonica_files(conn: sqlite3.Connection, song_id: int | None = None) -> list[HarmonicaFile]:
    """The harmonica tabs caracole keeps, of the song ``song_id`` or every song's; by song, then N."""
    sql = ("SELECT f.song_id, f.name, f.path, CASE WHEN json_valid(v.raw) THEN json_extract(v.raw, '$.key') END "
           "FROM files f JOIN versions v ON v.id = f.version_id WHERE v.kind = ?")
    args: list[object] = [HARMONICA_KIND]
    if song_id is not None:
        sql += " AND f.song_id = ?"
        args.append(song_id)
    found = []
    for row_song, name, at, key in conn.execute(sql, args):
        m = HARMONICA_FILE.fullmatch(name)
        if m:
            found.append(HarmonicaFile(row_song, name, at, int(m.group(1)), key if isinstance(key, str) else None))
    return sorted(found, key=lambda f: (f.song_id, f.number))


def parse_download_name(name: str) -> tuple[str | None, str, int | None]:
    """``"Artist - Title (ver 2).gp5"`` → ("Artist", "Title", 2).

    Bracketed words go, the version first, but not an original in another script: a site names a download
    after an artist and a song it may write in two scripts ("Jay Chou (周杰倫)"), and that part is the one
    that meets yours.
    """
    stem = Path(name).stem
    m = _VERSION.search(stem)
    version = int(m.group(1)) if m else None
    stem = _VERSION.sub("", stem)
    stem = _PARENS.sub(lambda g: g.group(0) if has_other_script(g.group(0)) else "", stem).strip()
    artist, sep, title = stem.partition(" - ")
    if sep and artist.strip() and title.strip():
        return artist.strip(), title.strip(), version
    return None, stem, version


def _match(artist: str | None, title: str, songs: list[Song]) -> Song | None:
    """The song a download is of: by identity, else the closest, by the forms of the names it was given
    (``normalize.name_forms``), which a site writes in two scripts for some artists."""
    if artist:
        key = identity_key(artist, title)
        for song in songs:
            if song.key == key:
                return song
    own = Names.of(artist or "", title)
    alike = own.score if artist else own.title_score
    scored = ((alike(Names.of(song.artist, song.title)), song) for song in songs)
    fits = [(score, song) for score, song in scored if score >= MATCH_CUTOFF]
    if not fits or (not artist and len(fits) > 1):
        return None  # a name without an artist is only trusted when exactly one song fits
    return max(fits, key=lambda fit: fit[0])[1]  # the first of the closest


def guitar_number(conn: sqlite3.Connection, library_dir: Path, song: Song) -> int:
    """The N of a new ``guitar-N`` file: the lowest number no file of the song holds, so that no file is ever
    replaced: a number is taken by any kept file, or any file in the folder, named ``guitar-N.*``, whatever its
    extension (one you put there yourself, say)."""
    taken = {int(m.group(1)) for n in _names_taken(conn, library_dir, song) if (m := _GUITAR_FILE.match(n))}
    return next(n for n in itertools.count(1) if n not in taken)


def harmonica_number(conn: sqlite3.Connection, library_dir: Path, song: Song) -> int:
    """The N of a new ``harmonica-N.txt``, a harmonica tab (harptabs_fetch.py): the lowest number no file of the
    song holds, kept or put in its folder by hand, so that no file is ever replaced."""
    taken = {int(m.group(1)) for n in _names_taken(conn, library_dir, song) if (m := HARMONICA_FILE.fullmatch(n))}
    return next(n for n in itertools.count(1) if n not in taken)


def score_number(conn: sqlite3.Connection, library_dir: Path, song: Song, ext: str) -> int:
    """The N of a new ``score-N<ext>`` file: the lowest number no file of the song with that
    extension holds, kept or put in the folder by hand. The formats of one score so take one
    number: ``score-1.mscz`` beside ``score-1.pdf``."""
    taken = {
        int(m.group(1)) for n in _names_taken(conn, library_dir, song)
        if (m := _SCORE_FILE.fullmatch(n)) and m.group(2).lower() == ext
    }
    return next(n for n in itertools.count(1) if n not in taken)


def _names_taken(conn: sqlite3.Connection, library_dir: Path, song: Song) -> set[str]:
    """The names of the song's files: every kept one's, every one in its folder, and every one another
    song keeps there (two songs whose names make one folder: ``library.SharedFolder``), lost or not."""
    folder = song_dir(library_dir, song)
    names = {r[0] for r in conn.execute("SELECT name FROM files WHERE song_id = ?", (song.id,))}
    # The paths in the folder: its own, then "/" (and "0" is the character after "/").
    at = folder.relative_to(library_dir).as_posix()
    names.update(PurePosixPath(r[0]).name for r in conn.execute(
        "SELECT path FROM files WHERE path >= ? AND path < ?", (f"{at}/", f"{at}0")))
    try:
        names.update(os.listdir(folder))
    except FileNotFoundError:
        pass
    return names


def _download_song(conn: sqlite3.Connection, name: str, ext: str, data: bytes) -> Song | None:
    """The song the download ``name`` is of, among every song not ignored: by its name, else, for a MusicXML
    score, by its header's title and creator, when exactly one song has both; None when it is no song's. Only
    reads."""
    songs = [s for s in list_songs(conn) if s.status != "ignored"]
    artist, title, _ = parse_download_name(name)
    found = _match(artist, title, songs)
    if found is not None:
        return found
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


def _inbox_version(conn: sqlite3.Connection, song: Song, kind: str) -> int:
    """The song's one version of ``kind`` for the files filed from the inbox: ``score``, ``guitar-pro`` or
    ``power``."""
    return upsert_version(
        conn, provider="inbox", tab_id=kind, song_id=song.id, slot="guitar", kind=kind, rating=0,
        votes=0, version=1, label=None, url="", raw={}, now=utc_now_iso(),
    )


def _place(conn: sqlite3.Connection, library_dir: Path, ext: str, song: Song) -> tuple[int, str, int]:
    """Where a download of the song goes: the version it is kept for, its name in the song's folder and its
    rank (its number)."""
    if ext in SCORE_EXTENSIONS:
        n = score_number(conn, library_dir, song, ext)
        return _inbox_version(conn, song, SCORE_KIND), f"score-{n}{ext}", n
    n = guitar_number(conn, library_dir, song)
    return _inbox_version(conn, song, "power" if ext == ".ptb" else "guitar-pro"), f"guitar-{n}{ext}", n


def _copies(conn: sqlite3.Connection, sha: str) -> list[KeptFile]:
    """The files caracole keeps whose recorded bytes are these, whether or not the library still holds them."""
    rows = conn.execute(
        "SELECT id, version_id, song_id, name, path, sha256, kept_rank FROM files WHERE sha256 = ? ORDER BY id",
        (sha,),
    )
    return [KeptFile(**dict(r)) for r in rows]


def _again(conn: sqlite3.Connection, library_dir: Path, copies: list[KeptFile],
           data: bytes) -> tuple[list[Path], bool]:
    """A download that is a file caracole kept: each of ``copies`` the library lost (nothing at its place
    now) is written back there, and listed; and whether the library still holds one as recorded. A copy
    whose place holds other bytes (yours, since) is left alone."""
    put_back: list[Path] = []
    held = False
    for copy in copies:
        song = get_song(conn, copy.song_id)
        place = song_dir(library_dir, song) / safe_name(copy.name)
        if holds(library_dir / copy.path, copy.sha256, len(data)):
            held = True
        elif not os.path.lexists(library_dir / copy.path) and not os.path.lexists(place):
            if keep_file(conn, library_dir, song=song, version_id=copy.version_id, name=copy.name, data=data,
                         rank=copy.kept_rank):
                put_back.append(place)
    return put_back, held


def file_inbox(conn: sqlite3.Connection, library_dir: Path) -> InboxStats:
    """File every Guitar Pro, Power Tab and score download in ``_inbox/`` under its song.

    A download with the bytes of a file caracole keeps is that file again, when its name is of no other
    song: a duplicate, removed, while the library holds the file; written back in its place when the
    library lost it (deleted on a synced device, say); left in the inbox when its place holds other bytes
    now. A download named for another song is filed for that song, whatever another song keeps.

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
                data = read_regular(Path(entry), dir_fd=inbox_fd)
            except NotRegularFile:  # swapped for a link since it was listed
                stats.refused.append(path)
                continue
            found = _download_song(conn, entry, ext, data)
            copies = _copies(conn, hashlib.sha256(data).hexdigest())
            if copies and (found is None or found.id in {c.song_id for c in copies}):
                # A file caracole kept, by its bytes: the song's own when its name says so, else any song's.
                mine = [c for c in copies if found is None or c.song_id == found.id]
                put_back, held = _again(conn, library_dir, mine, data)
                if put_back or held:
                    os.unlink(entry, dir_fd=inbox_fd)
                    stats.filed.extend(put_back)
                    if not put_back:
                        stats.duplicates.append(path)
                else:  # its place holds other bytes now: nothing is replaced, and the download stays
                    stats.unmatched.append(path)
                continue
            if found is None:
                stats.unmatched.append(path)
                continue
            version_id, name, rank = _place(conn, library_dir, ext, found)
            if keep_file(conn, library_dir, song=found, version_id=version_id, name=name, data=data, rank=rank):
                stats.filed.append(song_dir(library_dir, found) / name)
            else:
                stats.duplicates.append(path)
            os.unlink(entry, dir_fd=inbox_fd)
    finally:
        os.close(inbox_fd)
    return stats
