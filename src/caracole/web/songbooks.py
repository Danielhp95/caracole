"""caracole serve's songbooks: the forms of the library page's Songbooks tab and Select bar.

    POST /songbook/make     name, songs (song ids, in order)   caracole songbook make NAME SONG...
    POST /songbook/add      name, songs                        caracole songbook add NAME SONG...
    POST /songbook/move     name, song, position               caracole songbook move NAME SONG POSITION
    POST /songbook/remove   name, song                         caracole songbook remove NAME SONG
    POST /songbook/set      name, song, key, mode, capo        caracole songbook set --key K --mode M --capo N
                            (or clear)                         NAME SONG (or --clear)
    POST /songbook/rename   name, new                          caracole songbook rename NAME NEW
    POST /songbook/delete   name                               caracole songbook delete NAME
    POST /songbook/get      name (and song, one song's id)     caracole get "ARTIST - TITLE", for each song
                                                               without a sheet (or that one); then caracole
                                                               songbook render NAME
    POST /songbook/add-song name, and song (an id), or the     caracole get ARTIST TITLE, for a song the library
                            artist, title, ug, tab and         hasn't got (in wanted.txt first, as Get it
                            lacuerda of a search's result      writes it); then caracole songbook add NAME SONG

A form is checked here against songbooks.toml and the database, both only read, so that one
that can't be done is refused at once (a name a songbook can't have, a songbook there isn't,
a song the library hasn't got); then it is queued as that command (jobs.py), which takes
caracole's lock, writes songbooks.toml, makes the songbook's files and rewrites the pages,
exactly as from a terminal. The server itself writes no songbook. ``songs`` are the ids of
the page's data, in the order picked; ``song`` is a song as songbooks.toml writes it
("Artist - Title"), so a song gone from the library can be moved or taken out too. ``--``
ends the command's options, so a name may start with "-".

A setting (``set``) comes from a song's chip in the tab, which always sends the capo with a key or a mode, as
``caracole songbook set`` keeps it: the setting names where the song plays, so a sheet that takes its place
plays there too. The page's Add a song (``add-song``, songbook_routes.py) adds a song of your library at
once, and looks a song of the indexes up first, as Get it does (``search_routes.queue_lookup``).

A job's key is its command (``KEY``, then the command's words; a setting's, its songbook and song before its
setting, as ``songbook_of`` reads every key), so the same change sent twice
is queued once; ``songbook_of`` reads back which songbook it changes, by its name before and
after, for the page that follows it (jobs_routes.py) and for its line (status.py): "Moving the song…",
its step's label, while it runs; "Moved" once it is done (``DONE``); "Made" and "Added" with its
songbook's page to open (``songbook_page``, ``OPENS``), as a song's "Ready" has its sheet.

Get the missing songs now (``missing_songs``) queues a lookup, one ``caracole get``, of each song of the
songbook the library has without a sheet yet, in the songbook's order (``songbook.songs_to_get``: not one
"not in the library", nor one overrides.toml ignores), as the card's Fetch now would, then ``caracole
songbook render NAME`` after them (``render_job``), so the songbook is made again with the sheets they got,
"Made" once it is done; a queue without room for them all gets the first ones, and the next tap the rest.
Its key names the last lookup it follows, so a tap again while they wait queues nothing new, and a tap
after a new lookup makes the songbook again after that one. A set list's Get it is the same for one song
(``song``, its id).

A songbook's page, ``_songbooks/<folder>/songbook.html``, is one of the pages caracole wrote
(app.py's ``written_pages``): it is sent only while it is the page caracole wrote there
(``songbook.pages_written``, read by ``files.read_written_page``), with its own policy
(``book.songbook_csp``), since anyone with a synced device can put a page in the library.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from caracole.web.pages import Refused

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.songbook import Songbook
    from caracole.songs import Song

ROUTES = ("/songbook/make", "/songbook/add", "/songbook/move", "/songbook/remove", "/songbook/set",
          "/songbook/rename", "/songbook/delete")
GET_MISSING = "/songbook/get"  # its songs without a sheet, looked up now (songbook_routes.py's own handler)
ADD_SONG = "/songbook/add-song"  # a song from the tab's search, looked up first when the library hasn't got it
MAX_POSITION = 100_000
KEY = "songbook\x1f"  # a songbook job's key: this, then its command's words, this character between them
# What a songbook job's line says once it is done, by its action.
DONE = {"make": "Made", "add": "Added", "move": "Moved", "remove": "Taken out", "set": "Changed",
        "rename": "Renamed", "delete": "Deleted", "render": "Made"}
# The changes whose line links the songbook's page once done ("Made · Open songbook"): its songs are new there.
# Moved, taken out, set or renamed, its set list sits beside the line already.
OPENS = frozenset({"make", "add", "render"})


@dataclass(frozen=True)
class SongbookJob:
    """A form, as the job to queue: its title on the requests page, its key (one job for the same
    change sent twice) and its one step."""

    title: str
    key: str
    steps: list[tuple[str, tuple[str, ...]]]


def songbook_job(route: str, form: Mapping[str, str], *, library_dir: Path,
                 connect: Callable[[], sqlite3.Connection]) -> SongbookJob:
    """The job a songbook form asks for; Refused when it can't be done, before anything is queued."""
    from caracole.songbook import SongbookError, check_free, check_name, same_entry

    action = route.rsplit("/", 1)[-1]
    name, books = _named(form, library_dir)
    if action == "make":
        try:
            check_free(books, name)
        except SongbookError as e:
            raise Refused(409, "Taken", str(e)) from e
        songs = _songs(form, connect)
        count = f"{len(songs)} song{'' if len(songs) == 1 else 's'}"
        return _job(f'Make the songbook "{name}" ({count})', "Making the songbook", "make", name, *songs)
    book = _book(books, name)
    name = book.name
    if action == "add":
        songs = _songs(form, connect)
        count = f"{len(songs)} song{'' if len(songs) == 1 else 's'}"
        return _job(f'Add {count} to "{name}"', "Adding to the songbook", "add", name, *songs)
    if action in ("move", "remove", "set"):
        song = " ".join(form.get("song", "").split())
        if not song:
            raise Refused(400, "Not a song", "Which song? The form names none.")
        entry = next((s for s in book.texts if same_entry(s, song)), None)
        if entry is None:
            raise Refused(404, "Not in the songbook", f'"{song}" isn\'t in the songbook "{name}": reload the '
                                                      "library to see what it holds.")
        if action == "remove":
            return _job(f'Take {entry} out of "{name}"', "Taking the song out", "remove", name, entry)
        if action == "set":
            return _setting_job(name, entry, form)
        try:
            position = int(form.get("position", ""))
        except ValueError:
            position = 0
        if not 1 <= position <= MAX_POSITION:
            raise Refused(400, "Not a position", "A position is a whole number from 1, the first song.")
        return _job(f'Move {entry} to {position} in "{name}"', "Moving the song", "move", name, entry,
                    str(position))
    if action == "rename":
        try:
            new = check_name(form.get("new", ""))
        except SongbookError as e:
            raise Refused(400, "Not a name", str(e)) from e
        try:
            check_free(books, new, but=book)
        except SongbookError as e:
            raise Refused(409, "Taken", str(e)) from e
        return _job(f'Rename "{name}" to "{new}"', "Renaming the songbook", "rename", name, new)
    return _job(f'Delete the songbook "{name}"', "Deleting the songbook", "delete", name)


def _named(form: Mapping[str, str], library_dir: Path) -> tuple[str, list[Songbook]]:
    """The name a form gives, as a songbook keeps it, and the songbooks of songbooks.toml; Refused for a
    name a songbook can't have, or a file that can't be read."""
    from caracole.songbook import SongbookError, SongbookFileError, check_name, load_songbooks, songbooks_file

    try:
        name = check_name(form.get("name", ""))
    except SongbookError as e:
        raise Refused(400, "Not a name", str(e)) from e
    try:
        return name, load_songbooks(songbooks_file(library_dir))
    except SongbookFileError as e:
        raise Refused(503, "songbooks.toml can't be read",
                      f"songbooks.toml can't be read: {e}. Fix it, then try again.") from e


def _book(books: list[Songbook], name: str) -> Songbook:
    """The songbook of that name, in any case; Refused when there is none."""
    from caracole.songbook import find_songbook

    book = find_songbook(books, name)
    if book is None:
        listed = ", ".join(f'"{b.name}"' for b in books)
        raise Refused(404, "No such songbook", f'No songbook named "{name}"'
                      + (f": there are {listed}." if listed else ": reload the library."))
    return book


def _job(title: str, label: str, action: str, *args: str) -> SongbookJob:
    """The job of one ``caracole songbook`` command; its label is its line while it runs ("Moving the song…")."""
    command = ("songbook", action, "--", *args)
    return SongbookJob(title, KEY + "\x1f".join(command), [(label, command)])


def add_job(name: str, song: str) -> SongbookJob:
    """``caracole songbook add NAME SONG``: a song put at the end of the songbook (the page's Add a song)."""
    return _job(f'Add {song} to "{name}"', "Adding to the songbook", "add", name, song)


def _setting_job(name: str, entry: str, form: Mapping[str, str]) -> SongbookJob:
    """``caracole songbook set``: the song's key, mode and capo in the songbook (``key``, ``mode``, ``capo``, each
    left out where the form says nothing), or ``clear`` for its own version; Refused for a setting that can't be
    one. Its options come before ``--``; its key names the songbook and the song first, as every songbook job's
    does, then the setting."""
    from caracole.songbook import SongbookError, check_setting

    if form.get("clear", "") in ("1", "on", "yes"):
        options: tuple[str, ...] = ("--clear",)
        said, parts = "its own version", ("clear",)
    else:
        key, mode, capo = (form.get(name, "").strip() for name in ("key", "mode", "capo"))
        if not (key or mode or capo):
            raise Refused(400, "Not a setting", "Give it a key, a mode or a capo, or play it in its own version.")
        try:
            setting = check_setting(key[:1].upper() + key[1:] if key else None, mode.lower() or None,
                                    (int(capo) if capo.isascii() and capo.isdigit() else capo) if capo else None,
                                    where="The setting")
        except SongbookError as e:
            raise Refused(400, "Not a setting", str(e)) from e
        named = [(flag, value) for flag, value in (("--key", setting.key), ("--mode", setting.mode),
                                                   ("--capo", setting.capo)) if value is not None]
        options = tuple(str(word) for pair in named for word in pair)
        where = " ".join(str(v) for v in (setting.key, setting.mode) if v)
        said = ", ".join(p for p in (where, f"capo {setting.capo}" if setting.capo is not None else "") if p)
        parts = tuple("" if v is None else str(v) for v in (setting.key, setting.mode, setting.capo))
    command = ("songbook", "set", *options, "--", name, entry)
    title = f'Play {entry} in its own version in "{name}"' if parts == ("clear",) else \
        f'Play {entry} in {said}, in "{name}"'
    return SongbookJob(title, KEY + "\x1f".join(("songbook", "set", "--", name, entry, *parts)),
                       [("Changing where it plays", command)])


def missing_songs(form: Mapping[str, str], *, library_dir: Path, connect: Callable[[], sqlite3.Connection],
                  overrides: Overrides) -> tuple[str, list[Song]]:
    """The songbook a Get the missing songs form names, as songbooks.toml has it, and the songs of it a lookup
    could get a sheet for now, in its order (``songbook.songs_to_get``; with ``song``, a set list's Get it, that
    song alone); Refused when there is no such songbook, or none of its songs to get."""
    from caracole.songbook import songbook_entries, songs_to_get

    name, books = _named(form, library_dir)
    book = _book(books, name)
    with closing(connect()) as conn:
        songs = songs_to_get(songbook_entries(conn, library_dir, overrides, book), overrides)
    one = form.get("song", "").strip()
    if one:  # a set list's Get it: that song alone
        songs = [s for s in songs if one.isascii() and one.isdigit() and s.id == int(one)]
        if not songs:
            raise Refused(409, "Nothing to get", f'That song of "{book.name}" has a sheet already, isn\'t in the '
                                                 "library, or is ignored in overrides.toml: reload the library.")
    if not songs:
        raise Refused(409, "Nothing to get", f'Every song of "{book.name}" that the library has has a sheet '
                                             "already, or is ignored in overrides.toml: reload the library.")
    return book.name, songs


def book_named(form: Mapping[str, str], library_dir: Path) -> str:
    """The songbook a form names, as songbooks.toml has it; Refused when there is none, or the file can't be read."""
    name, books = _named(form, library_dir)
    return _book(books, name).name


def render_job(name: str, after: int) -> SongbookJob:
    """``caracole songbook render NAME``, queued after the lookups of its missing songs, the last of which is job
    ``after``: its key names that one, so the same tap twice is queued once, and a tap after a newer lookup
    makes the songbook again after it."""
    command = ("songbook", "render", "--", name)
    return SongbookJob(f'Make "{name}" again, with the songs it got', KEY + "\x1f".join(command) + f"\x1f{after}",
                       [("Making the songbook", command)])


def songbook_of(key: str) -> dict[str, str | None] | None:
    """The songbook a job's key changes: ``action`` (make, add, move, remove, rename, delete, render), its ``name``
    as songbooks.toml has it, and ``after``, its name once the job is done (the new one for a rename, None
    for a deletion); None for a job of anything else. A songbook's name holds no control character
    (``songbook.check_name``), so the key's separators split it back."""
    if not key.startswith(KEY):
        return None
    words = key[len(KEY):].split("\x1f")
    if len(words) < 4 or words[0] != "songbook" or words[1] not in DONE or words[2] != "--":
        return None
    action, name = words[1], words[3]
    after = words[4] if action == "rename" and len(words) > 4 else None if action == "delete" else name
    return {"action": action, "name": name, "after": after}


def songbook_page(conn: sqlite3.Connection, key: str) -> str | None:
    """The page of the songbook a job's key changes, as it is named once the job is done (``after``),
    relative to the library page: ``_songbooks/<folder>/songbook.html``, while caracole has written one
    there (``songbook.written_page``, which a server sends); None for a job of anything else, a
    deletion, or a songbook with no page."""
    from caracole.library import safe_name
    from caracole.songbook import FOLDER, HTML_NAME, written_page

    book = songbook_of(key)
    if book is None or book["after"] is None:
        return None
    folder = safe_name(str(book["after"]))
    if written_page(conn, folder) is None:
        return None
    return f"{FOLDER}/{quote(folder, safe='')}/{HTML_NAME}"


def _songs(form: Mapping[str, str], connect: Callable[[], sqlite3.Connection]) -> list[str]:
    """The songs of the form's ``songs`` (ids, comma-separated, in order), each as the library names
    it ("Artist - Title"), once each."""
    from caracole.songs import get_song

    text = form.get("songs", "").strip()
    if not text:
        raise Refused(400, "No songs", "Pick a song or more for the songbook first.")
    try:
        ids = list(dict.fromkeys(int(part) for part in text.split(",")))
    except ValueError as e:
        raise Refused(400, "Not songs", "Which songs? The form's list can't be read: reload the library.") from e
    names = []
    with closing(connect()) as conn:
        for song_id in ids:
            try:
                names.append(get_song(conn, song_id).display)
            except KeyError as e:
                raise Refused(404, "No such song", "A song you picked isn't in the library any more: reload "
                                                   "the library and pick again.") from e
    return names

