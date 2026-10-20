"""caracole serve's songbooks: the forms of the library page's Songbooks section and Select bar,
and each songbook's page.

    POST /songbook/make     name, songs (song ids, in order)   caracole songbook make NAME SONG...
    POST /songbook/add      name, songs                        caracole songbook add NAME SONG...
    POST /songbook/move     name, song, position               caracole songbook move NAME SONG POSITION
    POST /songbook/remove   name, song                         caracole songbook remove NAME SONG
    POST /songbook/rename   name, new                          caracole songbook rename NAME NEW
    POST /songbook/delete   name                               caracole songbook delete NAME
    GET  /_songbooks/<folder>/songbook.html                    the page, while it is caracole's

A form is checked here against songbooks.toml and the database, both only read, so that one
that can't be done is refused at once (a name a songbook can't have, a songbook there isn't,
a song the library hasn't got); then it is queued as that command (jobs.py), which takes
caracole's lock, writes songbooks.toml, makes the songbook's files and rewrites the pages,
exactly as from a terminal. The server itself writes no songbook. ``songs`` are the ids of
the page's data, in the order picked; ``song`` is a song as songbooks.toml writes it
("Artist - Title"), so a song gone from the library can be moved or taken out too. ``--``
ends the command's options, so a name may start with "-".

``read_page`` reads a songbook's page only while it is the page caracole wrote there
(``songbook.pages_written``), as ``files.read_written_page`` will once the served sheet
viewers are in: anyone with a synced device can put a page in the library, whose script
would run as the server's.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from collections.abc import Callable, Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from caracole.web.files import MAX_BYTES, NotServed, _is_hidden, _open

ROUTES = ("/songbook/make", "/songbook/add", "/songbook/move", "/songbook/remove", "/songbook/rename",
          "/songbook/delete")
PAGE_NAME = "songbook.html"  # songbook.HTML_NAME, without importing songbook.py on every start
MAX_POSITION = 100_000


class FormRefused(Exception):
    """A songbook form that can't be done: its status, a title and what to do."""

    def __init__(self, status: int, title: str, message: str):
        super().__init__(message)
        self.status, self.title, self.message = status, title, message


@dataclass(frozen=True)
class SongbookJob:
    """A form, as the job to queue: its title on the requests page, its key (one job for the same
    change sent twice) and its one step."""

    title: str
    key: str
    steps: list[tuple[str, tuple[str, ...]]]


def songbook_job(route: str, form: Mapping[str, str], *, library_dir: Path,
                 connect: Callable[[], sqlite3.Connection]) -> SongbookJob:
    """The job a songbook form asks for; FormRefused when it can't be done, before anything is queued."""
    from caracole.songbook import (
        SongbookError,
        SongbookFileError,
        check_free,
        check_name,
        find_songbook,
        load_songbooks,
        same_entry,
        songbooks_file,
    )

    action = route.rsplit("/", 1)[-1]
    try:
        name = check_name(form.get("name", ""))
    except SongbookError as e:
        raise FormRefused(400, "Not a name", str(e)) from e
    try:
        books = load_songbooks(songbooks_file(library_dir))
    except SongbookFileError as e:
        raise FormRefused(503, "songbooks.toml can't be read",
                          f"songbooks.toml can't be read: {e}. Fix it, then try again.") from e
    if action == "make":
        try:
            check_free(books, name)
        except SongbookError as e:
            raise FormRefused(409, "Taken", str(e)) from e
        songs = _songs(form, connect)
        count = f"{len(songs)} song{'' if len(songs) == 1 else 's'}"
        return _job(f'Make the songbook "{name}" ({count})', "Make the songbook", "make", name, *songs)
    book = find_songbook(books, name)
    if book is None:
        listed = ", ".join(f'"{b.name}"' for b in books)
        raise FormRefused(404, "No such songbook", f'No songbook named "{name}"'
                          + (f": there are {listed}." if listed else ": reload the library."))
    name = book.name
    if action == "add":
        songs = _songs(form, connect)
        count = f"{len(songs)} song{'' if len(songs) == 1 else 's'}"
        return _job(f'Add {count} to "{name}"', "Add to the songbook", "add", name, *songs)
    if action in ("move", "remove"):
        song = " ".join(form.get("song", "").split())
        if not song:
            raise FormRefused(400, "Not a song", "Which song? The form names none.")
        entry = next((s for s in book.songs if same_entry(s, song)), None)
        if entry is None:
            raise FormRefused(404, "Not in the songbook", f'"{song}" isn\'t in the songbook "{name}": reload the '
                                                          "library to see what it holds.")
        if action == "remove":
            return _job(f'Take {entry} out of "{name}"', "Take the song out", "remove", name, entry)
        try:
            position = int(form.get("position", ""))
        except ValueError:
            position = 0
        if not 1 <= position <= MAX_POSITION:
            raise FormRefused(400, "Not a position", "A position is a whole number from 1, the first song.")
        return _job(f'Move {entry} to {position} in "{name}"', "Move the song", "move", name, entry, str(position))
    if action == "rename":
        try:
            new = check_name(form.get("new", ""))
        except SongbookError as e:
            raise FormRefused(400, "Not a name", str(e)) from e
        try:
            check_free(books, new, but=book)
        except SongbookError as e:
            raise FormRefused(409, "Taken", str(e)) from e
        return _job(f'Rename "{name}" to "{new}"', "Rename the songbook", "rename", name, new)
    return _job(f'Delete the songbook "{name}"', "Delete the songbook", "delete", name)


def _job(title: str, label: str, action: str, *args: str) -> SongbookJob:
    command = ("songbook", action, "--", *args)
    return SongbookJob(title, "songbook\x1f" + "\x1f".join(command), [(label, command)])


def _songs(form: Mapping[str, str], connect: Callable[[], sqlite3.Connection]) -> list[str]:
    """The songs of the form's ``songs`` (ids, comma-separated, in order), each as the library names
    it ("Artist - Title"), once each."""
    from caracole.songs import get_song

    text = form.get("songs", "").strip()
    if not text:
        raise FormRefused(400, "No songs", "Pick a song or more for the songbook first.")
    try:
        ids = list(dict.fromkeys(int(part) for part in text.split(",")))
    except ValueError as e:
        raise FormRefused(400, "Not songs", "Which songs? The form's list can't be read: reload the library.") from e
    names = []
    with closing(connect()) as conn:
        for song_id in ids:
            try:
                names.append(get_song(conn, song_id).display)
            except KeyError as e:
                raise FormRefused(404, "No such song", "A song you picked isn't in the library any more: reload "
                                                       "the library and pick again.") from e
    return names


# --- the page ----------------------------------------------------------------------------------


def is_page(path: str) -> bool:
    """Whether the server reads ``path`` (in the library, ``/``-separated) as a songbook's page: by its
    name, wherever it is, as index.html links any file of that name; ``read_page`` says if it's sent."""
    return path.rsplit("/", 1)[-1] == PAGE_NAME


def songbook_page(conn: sqlite3.Connection, library_dir: Path, path: str, *,
                  hidden: Iterable[Path] = ()) -> tuple[bytes, str]:
    """A songbook's page, and the Content-Security-Policy to send it with (``book.songbook_csp`` of
    those very bytes); NotServed unless it is still the page caracole wrote (``read_page``)."""
    from caracole.songbook import pages_written
    from caracole.viewer.book import songbook_csp

    data = read_page(library_dir, path, lambda parts: pages_written(conn, library_dir, parts), hidden=hidden)
    return data, songbook_csp(data)


def read_page(library_dir: Path, path: str, written: Callable[[tuple[str, ...]], Iterable[object]], *,
              hidden: Iterable[Path] = ()) -> bytes:
    """The bytes of the page at ``path`` while it is a page caracole wrote there, as it wrote it;
    NotServed for anything else.

    ``written`` is the record of the page's kind: given the path's parts, the SHA-256 and the
    length of each page caracole recorded writing there. A path is checked as
    ``files.read_library_file`` checks one, and nothing is opened for a path with no record. The
    file is then opened as any file is (no link followed, at any step), and must be a regular
    file of a recorded length, whose bytes, read once, have its SHA-256: the test
    ``library.holds`` makes, on the very bytes served.
    """
    parts = path.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") or "\x00" in p for p in parts):
        raise NotServed(path)
    if _is_hidden(library_dir, parts, hidden):
        raise NotServed(path)
    records = {(r[0], r[1]) for r in written(tuple(parts))
               if isinstance(r, (tuple, list)) and len(r) == 2 and isinstance(r[0], str) and type(r[1]) is int}
    if not records:
        raise NotServed(path)
    try:
        with open(_open(library_dir, parts), "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise NotServed(path)
            if not any(size == info.st_size for _, size in records):
                raise NotServed(path)
            data = f.read(MAX_BYTES + 1)
    except OSError as e:
        raise NotServed(path) from e
    if (hashlib.sha256(data).hexdigest(), len(data)) not in records:
        raise NotServed(path)
    return data
