"""Songbooks: named, ordered lists of your songs, and what caracole makes of each one.

A songbook is a table of ``songbooks.toml``, in the library, so it syncs and you can
edit it by hand: its header is the songbook's name, and ``songs`` its songs in order,
each "Artist - Title" as overrides.toml writes a song::

    ["Campfire"]
    songs = [
      "Soda Stereo - De Música Ligera",
      "宋冬野 - 斑马，斑马",
    ]

The file is treated as overrides.toml is. It is read only when it is a regular file
(``library.read_text``): a symbolic link there could point at caracole's private
files. It is written only through this module's writers (``make_songbook``,
``add_to_songbook``, ``remove_from_songbook``, ``move_in_songbook``, ``rename_songbook``,
``delete_songbook``): tomlkit, so your comments and layout survive, then
``library.write_atomic``. A file that won't parse is a ``SongbookError`` naming it and
the line; it stops the songbooks and nothing else.

A song may carry its own setting, an inline table in place of the string: its key (a tonic as written),
its mode (one of ``theory.MODES``) and its capo, each left out where it says nothing::

    songs = ["Oasis - Wonderwall", { song = "Soda Stereo - De Música Ligera", key = "G", mode = "dorian", capo = 0 }]

A song with no setting stays a plain string, in the file and after any change to it. The songbook's files
play each song in its setting (``in_setting``): its key is the key of the shapes played, as an export's name
gives one ("G Dorian, capo 0"), so a sheet in another key in its place plays there too; what the setting
leaves out is the song's own version's (``render.own_version``), and a song with no setting is in its own
version, as its sheet's PDF is.

Two songs are the same when their identity keys are (``same_entry``): accents, case,
Traditional or Simplified characters and a version suffix don't count. A name is a
folder too, ``Library/_songbooks/<name>/`` (``library.safe_name``), so two names that
would share one are refused, in any case: a phone's file system may not tell them apart.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import subprocess
import tomllib
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit
from tomlkit.exceptions import TOMLKitError

from caracole.chordpro import directive_text
from caracole.db import kv_delete, kv_get_json, kv_set_json
from caracole.keys import sheet_keys
from caracole.library import (
    holds,
    kept_files,
    read_regular,
    read_text,
    safe_name,
    song_dir,
    write_atomic,
)
from caracole.logs import plural
from caracole.normalize import clean_title, identity_key
from caracole.overrides import TOO_DEEP

# The render step's own pieces: a songbook is rendered the way a sheet is, and right after the sheets.
from caracole.render import (
    AUTO_OUTPUTS,
    AUTO_SHEET,
    FONT_HINT,
    HUMAN_OUTPUTS,
    HUMAN_SHEET,
    STYLE_FILE,
    TIMEOUT,
    RenderError,
    Runner,
    _cjk_font,
    _font_options,
    _sheet_text,
    _style,
    export_query,
    keeps_key,
    own_version,
    pdf_font,
    private_dir,
    run_chordpro,
    written_entry,
    written_file,
)
from caracole.viewer.page import viewer_key
from caracole.viewer.sheet import directive, parse_sheet
from caracole.viewer.theory import Key
from caracole.viewer.version import (
    CAPO_MAX,
    Setting,
    Version,
    apply_version,
    in_setting,
    places,
    played_key,
    played_label,
    setting_problem,
)

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.overrides import Overrides
    from caracole.songs import Song

log = logging.getLogger(__name__)

FILE_NAME = "songbooks.toml"  # in the library
FOLDER = "_songbooks"  # in the library: a folder per songbook
MAX_NAME = 80  # characters
_KEYS = ("songs",)
_SETTING_KEYS = ("song", "key", "mode", "capo")
_HEADER = (
    "Your songbooks. Each [table] is one: its header is the songbook's name, and songs",
    'its songs in order, each "Artist - Title". Edit it by hand, or with caracole songbook',
    "(make, add, remove, move, set, rename, delete); caracole render makes each songbook into",
    "Library/_songbooks/<name>/: songbook.pdf, songbook.html and songbook.cho.",
)


class SongbookError(Exception):
    """songbooks.toml can't be read or written, or a change to it can't be made; the message says why."""


class SongbookFileError(SongbookError):
    """songbooks.toml itself can't be read: not a regular file, not UTF-8, not TOML, or not songbooks."""


@dataclass(frozen=True)
class SongbookSong:
    """A songbook's entry: its "Artist - Title" and the setting it carries, if any. (viewer/book.py's
    ``BookSong`` is a song as a songbook page draws it.)"""

    text: str
    setting: Setting | None = None


@dataclass(frozen=True)
class Songbook:
    """A songbook: its name and its songs, in order, as songbooks.toml writes them. Given plain strings,
    it takes each for a song with no setting."""

    name: str
    songs: tuple[SongbookSong, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "songs", tuple(SongbookSong(s) if isinstance(s, str) else s for s in self.songs))

    @property
    def texts(self) -> tuple[str, ...]:
        """Its songs' "Artist - Title", in order."""
        return tuple(s.text for s in self.songs)

    @property
    def folder(self) -> str:
        """Its folder's name, under ``Library/_songbooks/``."""
        return safe_name(self.name)


def songbooks_file(library_dir: Path) -> Path:
    return library_dir / FILE_NAME


# --- names and songs ---------------------------------------------------------------------------


def check_name(name: str) -> str:
    """A songbook's name as kept: its spaces trimmed and collapsed. SongbookError for one that can't
    name a folder in the library: empty, too long, hidden (a leading dot), with a line break or
    another control character, or with no letter or digit."""
    text = unicodedata.normalize("NFC", str(name))
    if any(unicodedata.category(c) in ("Cc", "Cf") and c not in " \t" for c in text):
        raise SongbookError(f"A songbook's name can't hold a line break or a control character: {name!r}")
    text = " ".join(text.split())
    if not text:
        raise SongbookError("A songbook needs a name")
    if len(text) > MAX_NAME:
        raise SongbookError(f"A songbook's name is {MAX_NAME} characters at most: {text[:MAX_NAME]!r}…")
    if text.startswith("."):
        raise SongbookError(f"A songbook's name can't start with a dot (its folder would be hidden): {text!r}")
    if not any(c.isalnum() for c in safe_name(text)):
        raise SongbookError(f"A songbook's name needs a letter or a digit: {text!r}")
    return text


def name_key(name: str) -> str:
    """How names are compared: "campfire" finds "Campfire"."""
    return " ".join(unicodedata.normalize("NFC", str(name)).split()).casefold()


def _folder_key(name: str) -> str:
    return safe_name(name).casefold()


def find_songbook(books: Iterable[Songbook], name: str) -> Songbook | None:
    """The songbook of this name, in any case."""
    key = name_key(name)
    return next((b for b in books if name_key(b.name) == key), None)


def entry_keys(text: str) -> frozenset[str]:
    """The identity keys an "Artist - Title" may stand for: one for each " - " it could be cut at,
    as an artist's name may hold one ("Earth - Wind - Fire")."""
    parts = str(text).split(" - ")
    keys = set()
    for i in range(1, len(parts)):
        artist, title = " - ".join(parts[:i]).strip(), " - ".join(parts[i:]).strip()
        if artist and title:
            keys.add(identity_key(artist, title))
    return frozenset(keys)


def same_entry(a: str, b: str) -> bool:
    """Whether two "Artist - Title" name one song: their identity keys meet (``entry_keys``)."""
    return not entry_keys(a).isdisjoint(entry_keys(b))


@dataclass(frozen=True)
class Found:
    """A song of the library a text names: ``exact`` when by its "Artist - Title", else by a search."""

    song: Song
    exact: bool = True


class NotInLibrary(SongbookError):
    """Songs the library hasn't got (``texts``), each with what it may have meant."""

    def __init__(self, texts: list[str], hints: list[list[str]]):
        self.texts = texts
        lines = []
        for text, near in zip(texts, hints):
            meant = f": did you mean {_either(near)}?" if near else "."
            lines.append(f'No song "{text}" in the library{meant}')
        lines.append("A songbook holds songs of your library: find one with caracole search, or add it with "
                     "caracole add ARTIST TITLE first.")
        super().__init__("\n".join(lines))


SEARCH_MARGIN = 5  # a search finds a song when no other one scores within this of it


def find_entry_song(conn: sqlite3.Connection, text: str) -> Song | None:
    """The song of the library an entry of songbooks.toml names, by its "Artist - Title" alone
    (``entry_keys``: accents, case, Traditional characters and a version suffix aside), or None.

    Never by a search: an entry whose song is gone from the library (or one typed with a typo) is
    missing, not another song with a title like it ("Karma Police Live" is not "Karma Police").
    """
    from caracole.songs import find_song

    for key in sorted(entry_keys(text)):
        song = find_song(conn, key)
        if song is not None:
            return song
    return None


def find_library_song(conn: sqlite3.Connection, text: str) -> Found | None:
    """The song of the library ``text``, typed on the command line, names, the way other commands
    find one, or None.

    First by its "Artist - Title" (``find_entry_song``), then by a search of the library
    (``search.search_library``: pinyin for Chinese, a typo), when one song answers it well
    (``search.STRONG``) by its title, or by its artist and title, and no other comes close.
    An artist's name alone names no song, even with one song of theirs in the library. Only
    for what you type: an entry of songbooks.toml is found by ``find_entry_song`` alone.
    """
    song = find_entry_song(conn, text)
    if song is not None:
        return Found(song)
    from caracole.search import STRONG, search_library  # rapidfuzz, only when a search is needed

    hits = search_library(conn, text, limit=2)
    if hits and hits[0].score >= STRONG and hits[0].via != "artist" and (
            len(hits) == 1 or hits[1].score <= hits[0].score - SEARCH_MARGIN):
        return Found(hits[0].song, exact=False)
    return None


def library_songs(conn: sqlite3.Connection, texts: Sequence[str]) -> list[Found]:
    """The songs ``texts`` name, in order (``find_library_song``); NotInLibrary for any the library
    lacks, naming every one with what it may have meant."""
    from caracole.search import search_library

    found: list[Found] = []
    missing: list[str] = []
    hints: list[list[str]] = []
    for text in texts:
        one = find_library_song(conn, text)
        if one is None:
            missing.append(text)
            hints.append([hit.song.display for hit in search_library(conn, text, limit=3)])
        else:
            found.append(one)
    if missing:
        raise NotInLibrary(missing, hints)
    return found


def _either(names: Sequence[str]) -> str:
    quoted = [f'"{n}"' for n in names]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " or " + quoted[-1]


def _entry(value: Any, where: str) -> str:
    text = " ".join(str(value).split()) if isinstance(value, str) else None
    if text is None or not entry_keys(text):
        raise SongbookError(f'{where}: expected "Artist - Title", got {value!r}')
    return text


def check_setting(key: Any = None, mode: Any = None, capo: Any = None, *, where: str = "a setting") -> Setting:
    """The setting these parts make (``version.Setting``: how a songbook plays one song, each part None where it
    says nothing, the song's own version's); SongbookError naming ``where`` for a part that can't be one
    (``version.setting_problem``). ``caracole songbook set`` gives a key or a mode the capo it plays at
    (``with_capo``), so that a sheet in place of the song's keeps the key it sounds in."""
    if (problem := setting_problem(key, mode, capo)) is not None:
        raise SongbookError(f"{where}: {problem}")
    return Setting(key, mode, capo)


def _song_of(value: Any, where: str) -> SongbookSong:
    """An entry of ``songs`` as the file has it: a string, or a table with ``song`` and a setting."""
    if isinstance(value, Mapping):
        unknown = [k for k in value if k not in _SETTING_KEYS]
        if unknown:
            raise SongbookError(f"{where}: unknown key(s) in a song: {', '.join(map(repr, unknown))}; expected "
                                '{ song = "Artist - Title", key = "G", mode = "dorian", capo = 0 }')
        text = _entry(value.get("song"), where)
        setting = check_setting(value.get("key"), value.get("mode"), value.get("capo"), where=f'{where}, "{text}"')
        return SongbookSong(text, setting or None)
    return SongbookSong(_entry(value, where))


def _item(song: SongbookSong):
    """The song as the document writes it: a plain string with no setting, else an inline table."""
    setting = song.setting
    if not setting:
        return song.text
    table = tomlkit.inline_table()
    table["song"] = song.text
    for name in ("key", "mode", "capo"):
        if (value := getattr(setting, name)) is not None:
            table[name] = value
    return table


def _text_of(item: Any) -> str:
    return str(item["song"]) if isinstance(item, Mapping) else str(item)


# --- reading -----------------------------------------------------------------------------------




def load_songbooks(path: Path) -> list[Songbook]:
    """The songbooks in songbooks.toml, in the file's order; none when there is no file. Every error
    names the file."""
    text = read_text(path, SongbookFileError)
    if text is None:
        return []
    try:
        return _parse(tomllib.loads(text))
    except tomllib.TOMLDecodeError as e:
        raise SongbookFileError(f"{path}: {e}") from e
    except RecursionError:  # what a synced device wrote stops nothing else
        raise SongbookFileError(f"{path}: {TOO_DEEP}") from None
    except SongbookError as e:
        raise SongbookFileError(f"{path}: {e}") from e


def _parse(data: Mapping[str, Any]) -> list[Songbook]:
    books: list[Songbook] = []
    names: dict[str, str] = {}
    folders: dict[str, str] = {}
    for header, table in data.items():
        where = f"[{_quoted(header)}]"
        if not isinstance(table, Mapping):
            raise SongbookError(f"{header!r} must be a table: a songbook is [\"Name\"] then songs = [...]")
        try:
            name = check_name(header)
        except SongbookError as e:
            raise SongbookError(f"{where}: {e}") from e
        unknown = [k for k in table if k not in _KEYS]
        if unknown:
            raise SongbookError(f"unknown key(s) in {where}: {', '.join(map(repr, unknown))}; "
                                'expected songs = ["Artist - Title", ...]')
        songs = table.get("songs", [])
        if not isinstance(songs, list) or not all(isinstance(s, (str, Mapping)) for s in songs):
            raise SongbookError(f'{where}: songs must be a list of "Artist - Title" strings or '
                                '{ song = "Artist - Title", key = ..., mode = ..., capo = ... } tables')
        if name_key(name) in names:
            raise SongbookError(f"{where} and [{_quoted(names[name_key(name)])}] are one songbook written "
                                "twice: merge them")
        if _folder_key(name) in folders:
            raise SongbookError(f"{where} and [{_quoted(folders[_folder_key(name)])}] would share the folder "
                                f"{FOLDER}/{safe_name(name)}: rename one")
        names[name_key(name)] = folders[_folder_key(name)] = header
        books.append(Songbook(name, tuple(_song_of(s, where) for s in songs)))
    return books


def _quoted(name: str) -> str:
    return '"' + str(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


# --- writing -----------------------------------------------------------------------------------


def _edit[T](path: Path, change: Callable[[Any, list[Songbook]], T]) -> T:
    """Apply ``change`` to the file's document and its songbooks, then write the file if it changed.

    A file that can't be read is an error and is left alone: a change never builds on a broken file.
    """
    old = read_text(path, SongbookFileError)
    try:
        books = [] if old is None else _parse(tomllib.loads(old))
        doc = tomlkit.parse(old) if old is not None and old.strip() else _new_document()
    except (tomllib.TOMLDecodeError, TOMLKitError, SongbookError) as e:
        raise SongbookFileError(f"{path}: {e}") from e
    except RecursionError:
        raise SongbookFileError(f"{path}: {TOO_DEEP}") from None
    result = change(doc, books)
    text = tomlkit.dumps(doc)
    if text != old:
        write_atomic(path, text.encode("utf-8"))
    return result


def _new_document():
    doc = tomlkit.document()
    for line in _HEADER:
        doc.add(tomlkit.comment(line))
    doc.add(tomlkit.nl())
    return doc


def _header(doc, name: str) -> str:
    """The header the document writes this songbook under, in any case; SongbookError if none."""
    key = name_key(name)
    found = next((k for k in doc if name_key(k) == key), None)
    if found is None:
        raise SongbookError(f'No songbook named "{" ".join(str(name).split())}" in {FILE_NAME}: '
                            "caracole songbook list shows them")
    return found


def _songs(doc, header: str):
    table = doc[header]
    if "songs" not in table:
        songs = tomlkit.array()
        songs.multiline(True)
        table["songs"] = songs
    return table["songs"]


def check_free(books: Sequence[Songbook], name: str, *, but: Songbook | None = None) -> None:
    """Refuse a name another songbook has, or whose folder another songbook's would be."""
    for book in books:
        if book is but:
            continue
        if name_key(book.name) == name_key(name):
            raise SongbookError(f'A songbook named "{book.name}" is there already: pick another name, or add '
                                "songs to it with caracole songbook add")
        if _folder_key(book.name) == _folder_key(name):
            raise SongbookError(f'"{name}" would share the folder {FOLDER}/{safe_name(name)} with the songbook '
                                f'"{book.name}": pick another name')


def make_songbook(path: Path, name: str, entries: Sequence[str]) -> Songbook:
    """Add a songbook of these songs, in this order, after the others; return it. A song named twice
    (``same_entry``) is in it once, where it is first named, as ``add_to_songbook`` keeps it."""
    clean = check_name(name)
    songs: list[str] = []
    for text in entries:
        entry = _entry(text, f"[{_quoted(clean)}]")
        if not any(same_entry(entry, s) for s in songs):
            songs.append(entry)

    def change(doc, books: list[Songbook]) -> Songbook:
        check_free(books, clean)
        table = tomlkit.table()
        array = tomlkit.array()
        array.extend(songs)
        array.multiline(True)
        table["songs"] = array
        doc[clean] = table
        return Songbook(clean, tuple(songs))

    return _edit(path, change)


def add_to_songbook(path: Path, name: str, entries: Sequence[str]) -> list[str]:
    """Append the songs the songbook hasn't got (``same_entry``), in order; return those added."""
    wanted = [_entry(e, "a song") for e in entries]

    def change(doc, _books) -> list[str]:
        songs = _songs(doc, _header(doc, name))
        added: list[str] = []
        for entry in wanted:
            if not any(same_entry(entry, _text_of(s)) for s in [*songs, *added]):
                added.append(entry)
        songs.extend(added)
        return added

    return _edit(path, change)


def remove_from_songbook(path: Path, name: str, entries: Sequence[str]) -> list[str]:
    """Take these songs out of the songbook, every time it names them; return them as it wrote them."""

    def change(doc, _books) -> list[str]:
        songs = _songs(doc, _header(doc, name))
        removed: list[str] = []
        for i in reversed(range(len(songs))):
            if any(same_entry(_text_of(songs[i]), e) for e in entries):
                removed.insert(0, _text_of(songs[i]))
                del songs[i]
        return removed

    return _edit(path, change)


def move_in_songbook(path: Path, name: str, entry: str, position: int) -> int:
    """Put the song at ``position``, counted from 1 (past the end: last); return where it went."""
    if position < 1:
        raise SongbookError(f"A position counts from 1, the songbook's first song: got {position}")

    def change(doc, _books) -> int:
        header = _header(doc, name)
        songs = _songs(doc, header)
        at = next((i for i, s in enumerate(songs) if same_entry(_text_of(s), entry)), None)
        if at is None:
            raise SongbookError(f'"{entry}" isn\'t in the songbook "{header}": caracole songbook show lists its songs')
        to = min(position, len(songs)) - 1
        if to != at:
            _move_item(songs, at, to)
        return to + 1

    return _edit(path, change)


def _move_item(songs, at: int, to: int) -> None:
    """Move the array's item at ``at`` to ``to`` as it is written, with the comment after it on its line
    (``"Radiohead - Creep",  # capo 3``): tomlkit keeps that comment with the item's place, not the item,
    so it is taken along by hand. A comment on a line of its own stays where it is."""
    comment = songs._value[songs._index_map[at]].comment
    item = songs[at]
    del songs[at]
    songs.insert(to, item)
    if comment is not None:
        songs._value[songs._index_map[to]].comment = comment


def set_song_setting(path: Path, name: str, entry: str, setting: Setting | None) -> None:
    """Give the song its setting, in place; ``None`` (or an empty one) takes it off, and the song is a plain
    string again. SongbookError if the songbook doesn't hold the song. Its place and the rest of the file stay."""
    setting = check_setting(setting.key, setting.mode, setting.capo) if setting else None

    def change(doc, _books) -> None:
        header = _header(doc, name)
        songs = _songs(doc, header)
        at = next((i for i, s in enumerate(songs) if same_entry(_text_of(s), entry)), None)
        if at is None:
            raise SongbookError(f'"{entry}" isn\'t in the songbook "{header}": caracole songbook show lists its songs')
        songs[at] = _item(SongbookSong(_text_of(songs[at]), setting or None))

    _edit(path, change)


def rename_songbook(path: Path, name: str, new: str) -> Songbook:
    """Give the songbook another name, in its place in the file; return it."""
    clean = check_name(new)

    def change(doc, books: list[Songbook]) -> Songbook:
        header = _header(doc, name)
        book = find_songbook(books, header)
        check_free(books, clean, but=book)
        if header != clean:
            doc._replace(header, clean, doc[header])  # tomlkit's way to keep the table, comments and place
        return Songbook(clean, book.songs if book else ())

    return _edit(path, change)


def delete_songbook(path: Path, name: str) -> Songbook:
    """Take the songbook out of the file; return it."""

    def change(doc, books: list[Songbook]) -> Songbook:
        header = _header(doc, name)
        book = find_songbook(books, header) or Songbook(header)
        del doc[header]
        return book

    return _edit(path, change)


# --- what a songbook is made into -------------------------------------------------------------

PDF_NAME = "songbook.pdf"  # every sheet, through one chordpro run, after a title page and the contents
HTML_NAME = "songbook.html"  # the contents, then each song in the sheet viewer (viewer/book.py)
CHO_NAME = "songbook.cho"  # every sheet, in its key, split by {new_song}: for a songbook app
OUTPUTS = (CHO_NAME, PDF_NAME, HTML_NAME)  # in the order they are made: the page links the others
RECORD_KEY = "songbook:"  # kv, then the songbook's folder name: what its files were made from, and are
CONTENTS_TEMPLATE = "contents.cho"  # the title page, then the contents' heading (chordpro's ToC template)
BOOK_CONFIG_NAME = "songbook.json"
MISSING_SHEET = "no sheet yet"
MISSING_SONG = "not in the library"
PER_SONG_TIMEOUT = 10  # seconds of chordpro's time per song, on top of render.TIMEOUT

# What chordpro adds to caracole's look (render.STYLE_FILE) for a songbook: one table of contents, in
# the songbook's order, opening on a title page (CONTENTS_TEMPLATE), and no blank page to start each
# song on a right-hand page: a songbook is read on a screen as often as on paper.
BOOK_CONFIG = {
    "contents": [{
        "fields": ["songindex"], "label": "Contents", "line": "%{title}%{artist| · %{}}", "pageno": "%{page}",
        "fold": False, "omit": False, "template": CONTENTS_TEMPLATE,
    }],
    "pdf": {"pagealign-songs": 0, "fonts": {"toc": {"name": "Helvetica", "size": 12}}},
}
# The elements whose font file a CJK font replaces: render.FONT_ELEMENTS, and the contents, whose
# font chordpro's own config names.
BOOK_FONT_ELEMENTS = ("text", "title", "toc")


@dataclass(frozen=True)
class Entry:
    """One song of a songbook as it is rendered: its sheet's ChordPro (``cho``), as caracole wrote it
    beside the song's PDF, or why it has none (``missing``). ``setting`` is the songbook's for it, if any, and
    ``version`` where the songbook plays it: in that setting (``in_setting``), else in the song's own version
    on that sheet (``render.own_version``: its ``[version]``, else its ``[transpose]``); ``transpose`` is that
    version's ``t``. ``keeps_key``: whether the song's own version is kept by its key (``render.keeps_key``),
    which a sheet with no key can't take, as it can't a setting's key. ``plays_in(entry)`` says where, in words."""

    text: str  # as songbooks.toml writes it
    title: str
    artist: str
    song: Song | None = None
    cho: str | None = None
    missing: str | None = None
    transpose: int = 0
    version: Version = field(default_factory=Version)
    key: str | None = None
    key_source: str | None = None
    setting: Setting | None = None
    keeps_key: bool = False


@dataclass
class SongbookStats:
    """One pass over the songbooks: ``rendered`` songbooks had a file written, ``skipped`` ones were up
    to date, ``failed`` names those with a file that couldn't be made, ``font_error`` says once which
    wait for a CJK font, ``error`` why songbooks.toml can't be read, and ``removed`` counts the
    songbooks gone from it whose files went too."""

    rendered: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)
    font_error: str | None = None
    error: str | None = None
    removed: int = 0


def songbook_entries(conn: sqlite3.Connection, library_dir: Path, overrides: Overrides,
                     book: Songbook) -> list[Entry]:
    """The songbook's songs, in order, each with its sheet or why it has none: a song the library
    hasn't got (removed since, say) or one without a sheet is missing, never an error. Each is
    found by its "Artist - Title" alone (``find_entry_song``), never by a search."""
    return [_entry_of(conn, library_dir, overrides, song) for song in book.songs]


def songs_to_get(entries: Iterable[Entry], overrides: Overrides) -> list[Song]:
    """The songs of a songbook's entries a lookup could get a sheet for now (caracole serve's Get the missing
    songs now): those the library has with no sheet yet, in the songbook's order, once each, but those
    overrides.toml ignores. A song "not in the library" is no one's to look up."""
    songs: dict[int, Song] = {}
    for e in entries:
        song = e.song
        if (e.missing == MISSING_SHEET and song is not None and song.status != "ignored"
                and song.key not in overrides.ignore):
            songs.setdefault(song.id, song)
    return list(songs.values())


def _entry_of(conn: sqlite3.Connection, library_dir: Path, overrides: Overrides, entry: SongbookSong) -> Entry:
    text, setting = entry.text, entry.setting
    song = find_entry_song(conn, text)
    if song is None:
        artist, _, title = text.partition(" - ")
        return Entry(text, title.strip() or text, artist.strip(), missing=MISSING_SONG, setting=setting)
    title = clean_title(song.title)
    sheet = _sheet_of(conn, library_dir, song)
    if sheet is None:
        return Entry(text, title, song.artist, song, missing=MISSING_SHEET, setting=setting)
    name, cho = sheet
    human, auto = sheet_keys(conn, library_dir, song)
    found = auto if name == AUTO_OUTPUTS[0] else human
    key, source = (found.key, found.source) if found else (None, None)
    version = _played_in(text, cho, key, source, own_version(overrides, song, cho, key, source), setting)
    return Entry(text, title, song.artist, song, cho=cho, transpose=version.t, version=version, key=key,
                 key_source=source, setting=setting, keeps_key=keeps_key(overrides, song))


def _played_in(text: str, cho: str, key: str | None, key_source: str | None, own: Version,
               setting: Setting | None) -> Version:
    """Where the songbook plays the song (``in_setting``), ``key`` being its sheet's (``keys.sheet_keys``) and
    ``key_source`` where it came from. A sheet the viewer's code can't read (a bug, logged with its traceback) is
    in its own version here, and never stops the songbook's entries: its files run that code too, and fail as for
    any song."""
    if not setting:
        return own
    try:
        return in_setting(own, setting, viewer_key(cho, key, key_source), parse_sheet(cho).capo)
    except Exception:
        log.warning("%s: cannot place it in its songbook setting", text, exc_info=True)
        return own


def with_capo(entry: Entry, setting: Setting, overrides: Overrides) -> Setting:
    """``setting`` for the song of ``entry`` with the capo it plays at now on its sheet, where the setting names
    a key or a mode and no capo (``caracole songbook set``): a setting's key is the key of the shapes played, so
    without its capo a sheet in place of this one, with another capo, would play them at that capo, in another
    key for the singer. As given for a song without a sheet, or one the viewer's code can't read (a bug, logged
    with its traceback), or a setting naming its capo."""
    if setting.capo is not None or not places(setting) or entry.cho is None or entry.song is None:
        return setting
    try:
        own = own_version(overrides, entry.song, entry.cho, entry.key, entry.key_source)
        version = _played_in(entry.text, entry.cho, entry.key, entry.key_source, own, setting)
        _, capo = played_key(version, viewer_key(entry.cho, entry.key, entry.key_source), parse_sheet(entry.cho).capo)
    except Exception:
        log.warning("%s: cannot say at which capo its songbook plays it", entry.text, exc_info=True)
        return setting
    return replace(setting, capo=capo) if capo <= CAPO_MAX else setting


KEY_UNKNOWN = "key unknown, as written"  # what plays_in says of a setting or a key a sheet with no key can't take


def plays_in(entry: Entry) -> str | None:
    """Where the songbook plays the song, in words, for its set list: its version's ``played_label`` ("G
    Dorian", "E Minor, capo 2", nothing of a capo it plays without; "Transposed +2" for a sheet with no key), or
    ``KEY_UNKNOWN`` for a setting with a key or a mode, or an own version kept by its key, that its sheet, which
    has no key, can't take; None for a song without a sheet, or one the viewer's code can't read (a bug, logged
    with its traceback)."""
    return where_played(entry)[0]


def where_played(entry: Entry) -> tuple[str | None, tuple[Key | None, int] | None]:
    """``plays_in``'s words and, for the set list's menus, the key of the shapes played (a pitch class and a mode,
    None for a sheet with no key) and the capo (``version.played_key``), from one reading of the sheet; both None
    for a song without a sheet, or one the viewer's code can't read (a bug, logged with its traceback)."""
    if entry.cho is None:
        return None, None
    try:
        shapes = viewer_key(entry.cho, entry.key, entry.key_source)
        capo = parse_sheet(entry.cho).capo
        played = played_key(entry.version, shapes, capo)
        if shapes is None and (places(entry.setting) or entry.keeps_key):
            return KEY_UNKNOWN, played
        return played_label(entry.version, shapes, capo), played
    except Exception:
        log.warning("%s: cannot say where its songbook plays it", entry.text, exc_info=True)
        return None, None


def _sheet_of(conn: sqlite3.Connection, library_dir: Path, song: Song) -> tuple[str, str] | None:
    """The .cho of the song's human sheet, else of its auto sheet, as render.py last wrote it
    (``render.written_file``): (its name, its text). One that is no longer those bytes (changed on a
    device, a link in its place) counts as none: only caracole's sheets go into a songbook."""
    kept = {f.name for f in kept_files(conn, song.id)}
    for sheet, cho in ((HUMAN_SHEET, HUMAN_OUTPUTS[0]), (AUTO_SHEET, AUTO_OUTPUTS[0])):
        written = written_file(conn, song.id, cho) if sheet in kept else None
        if written is None:
            continue
        try:
            data = read_regular(song_dir(library_dir, song) / cho)
        except OSError:
            continue
        if len(data) == written[1] and hashlib.sha256(data).hexdigest() == written[0]:
            try:
                return cho, data.decode("utf-8")
            except UnicodeDecodeError:
                continue
    return None


def songbooks_listing(conn: sqlite3.Connection, books: Iterable[Songbook], song: Song) -> list[Songbook]:
    """The songbooks whose entries name ``song``, found as ``songbook_entries`` finds each (never by a search):
    keep it matching exactly what ``songbook_entries`` and ``songs_to_get`` match (``find_entry_song``)."""
    return [b for b in books if any((found := find_entry_song(conn, e.text)) is not None and found.id == song.id
                                    for e in b.songs)]


def render_songbooks(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, *,
                     runner: Runner = subprocess.run, force: bool = False,
                     only: str | Iterable[str] | None = None) -> SongbookStats:
    """Make every songbook of songbooks.toml (``only``: that one, or those) into its files in
    ``Library/_songbooks/<name>/``, each only when what it is made from changed or it is no longer as
    written; then take away the files of the songbooks gone from the file.

    A songbooks.toml that can't be read is ``error``, logged, and leaves every songbook's files as
    they are. A songbook whose file can't be made is logged and ``failed``; the others go on.
    """
    stats = SongbookStats()
    only_keys = None if only is None else {name_key(n) for n in ([only] if isinstance(only, str) else only)}
    try:
        books = load_songbooks(songbooks_file(cfg.library_dir))
    except SongbookError as e:
        stats.error = str(e)
        log.warning("no songbooks: %s", e)
        return stats
    font, font_problem = _cjk_font(cfg.cjk_font)
    waiting: list[str] = []
    for book in books:
        if only_keys is not None and name_key(book.name) not in only_keys:
            continue
        done = _render_book(conn, cfg, overrides, book, font=font, runner=runner, force=force)
        if done.no_font:
            waiting.append(f"{book.name} ({done.no_font} U+{ord(done.no_font):04X})")
        if done.failed:
            stats.failed.append(book.name)
        elif done.written:
            stats.rendered += 1
        else:
            stats.skipped += 1
    if waiting:
        reason = f"{font_problem}; " if font_problem else ""
        stats.font_error = f"{reason}{FONT_HINT} to render the songbook PDF of {', '.join(waiting)}"
        log.warning("%s", stats.font_error)
    stats.removed = _remove_gone(conn, cfg.library_dir, {b.folder for b in books})
    return stats


@dataclass
class _BookDone:
    written: bool = False  # a file was written
    failed: bool = False  # a file couldn't be made (logged)
    no_font: str | None = None  # the PDF waits for a CJK font: the first letter it needs


def _render_book(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, book: Songbook, *,
                 font: Path | None, runner: Runner, force: bool) -> _BookDone:
    """Make the songbook's files: songbook.cho, songbook.pdf, then songbook.html, which links them."""
    done = _BookDone()
    entries = songbook_entries(conn, cfg.library_dir, overrides, book)
    try:
        folder = _book_folder(cfg.library_dir, book)
    except SongbookError as e:
        log.warning("songbook %s: %s", book.name, e)
        done.failed = True
        return done
    record = _record(conn, book.folder)
    try:
        _make_files(cfg, book, entries, folder, record, done, font=font, runner=runner, force=force)
    finally:  # what was written stays recorded, whatever stopped the rest
        kv_set_json(conn, f"{RECORD_KEY}{book.folder}", record)
    return done


def _make_files(cfg: Config, book: Songbook, entries: list[Entry], folder: Path, record: dict[str, Any],
                done: _BookDone, *, font: Path | None, runner: Runner, force: bool) -> None:
    """songbook.cho, songbook.pdf, then songbook.html, into ``folder``, each written in ``record``."""
    playable = [e for e in entries if e.cho is not None]

    def make(name: str, inputs: Any, build: Callable[[], bytes | None]) -> None:
        """Write ``name`` from ``build`` unless it was made from these ``inputs`` and is still as written.
        A file that can't be made or written (chordpro failed; a folder in its place, a full disk) is
        logged and fails the songbook, and the others are still made."""
        digest = _digest(inputs)
        files, made = record["files"], record["inputs"]
        if not force and made.get(name) == digest and _holds(folder / name, files.get(name)):
            return
        try:
            data = build()
            if data is None:  # nothing to make: what caracole wrote there goes
                _drop(folder / name, files.get(name))
                files.pop(name, None)
                made.pop(name, None)
                return
            if not holds(folder / name, hashlib.sha256(data).hexdigest(), len(data)):  # one more sync, else none
                write_atomic(folder / name, data)
                done.written = True
        except (RenderError, OSError) as e:
            log.warning("songbook %s: no %s: %s", book.name, name, e)
            done.failed = True
            return
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        made[name] = digest

    # What chordpro reads and prints of each song: made from more than its .cho (its key, its version, the
    # viewer's theory and shapes), so the files' inputs hold these texts; the PDF's font is the one they need
    try:
        texts = [_song_file(e) for e in playable]
    except RenderError as e:
        log.warning("songbook %s: no %s: %s", book.name, CHO_NAME, e)
        done.failed = True
        texts = None
    if texts is not None:
        make(CHO_NAME, {"songs": texts, "v": 4}, lambda: _chordpro_file(cfg, texts, runner) if texts else None)

    try:
        printed = [_song_file(e, pdf=True) for e in entries]
    except RenderError as e:
        log.warning("songbook %s: no %s: %s", book.name, PDF_NAME, e)
        done.failed = True
        printed = None
    if printed is not None:
        text = "\n".join([book.name, *printed])
        book_font, lost = pdf_font(text, font)
        if lost is not None:
            done.no_font = lost
        else:
            pdf_inputs = {
                "name": book.name, "songs": printed, "style": _style(), "book": BOOK_CONFIG,
                "font": str(book_font) if book_font else None, "v": 5,
            }
            make(PDF_NAME, pdf_inputs, lambda: _pdf(cfg, book, entries, printed, runner, font=book_font)
                 if playable else None)

    from caracole.viewer.book import BookSong, assets_version, build_songbook

    present = {name for name in (PDF_NAME, CHO_NAME) if _holds(folder / name, record["files"].get(name))}
    book_songs = [BookSong(e.title, e.artist, cho=e.cho, key=e.key, key_source=e.key_source, transpose=e.transpose,
                           missing=e.missing, id=_song_id(e), start=_start(e.version)) for e in entries]
    page_inputs = {"name": book.name, "songs": [list(vars(s).values()) for s in book_songs],
                   "files": sorted(present), "assets": assets_version()}

    def page() -> bytes:
        try:
            html = build_songbook(book.name, book_songs, pdf=PDF_NAME if PDF_NAME in present else None,
                                  cho=CHO_NAME if CHO_NAME in present else None)
        except Exception as e:  # a sheet the viewer can't read must never cost the songbook its other files
            log.warning("songbook %s: cannot build %s", book.name, HTML_NAME, exc_info=True)
            raise RenderError(f"cannot build {HTML_NAME}: {type(e).__name__}: {e}") from e
        return html.encode("utf-8")

    make(HTML_NAME, page_inputs, page)


def _start(version: Version) -> str | None:
    """The version as the viewer's address writes it, where the phone page starts the song (``export_query``);
    None for one that only moves it, where its ``transpose`` starts it."""
    return None if version == Version(t=version.t) else export_query(version)


def _song_id(entry: Entry) -> str:
    """A short id for the song on the phone page, the same wherever the songbook puts it."""
    key = entry.song.key if entry.song is not None else entry.text
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]


def _digest(inputs: Any) -> str:
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _holds(path: Path, entry: Any) -> bool:
    """Whether the file at ``path`` is still what the record ``entry`` says caracole wrote."""
    return (written := written_entry(entry)) is not None and holds(path, *written)


def _drop(path: Path, entry: Any) -> None:
    """Remove the file caracole wrote at ``path`` while it is still as written; one of yours stays."""
    if _holds(path, entry):
        path.unlink(missing_ok=True)


def _record(conn: sqlite3.Connection, folder: str) -> dict[str, Any]:
    """kv ``songbook:<folder>``: {"inputs": {file: digest}, "files": {file: {"sha256", "size"}}}."""
    record = kv_get_json(conn, f"{RECORD_KEY}{folder}")
    if not isinstance(record, dict):
        record = {}
    for part in ("inputs", "files"):
        if not isinstance(record.get(part), dict):
            record[part] = {}
    return record


def written_page(conn: sqlite3.Connection, folder: str) -> tuple[str, int] | None:
    """The SHA-256 and the length of the songbook.html caracole last wrote in ``_songbooks/<folder>/``,
    or None: as ``render.written_file`` does for a sheet's viewer, so that a server serves the page
    only while it is still those bytes (``pages_written``)."""
    return written_entry(_record(conn, folder)["files"].get(HTML_NAME))


def pages_written(conn: sqlite3.Connection, library_dir: Path, parts: tuple[str, ...]) -> list[tuple[str, int]]:
    """The record of the songbook page a server is asked for, by its path's parts in the library
    (``("_songbooks", "Campfire", "songbook.html")``): the SHA-256 and the length of the page caracole
    last wrote there (``written_page``), [] for any other path or none written.

    Anyone with a synced device can put a page in the library, whose script would run as the
    server's: a server sends a songbook's page only while it is still those bytes, read without
    following a link, with ``viewer.book.songbook_csp`` of them as its policy (web/songbooks.py).
    ``library_dir`` goes unused (the record is by folder name, as render_songbooks keeps it): the
    lookups of the server's pages all take the same arguments.
    """
    if len(parts) != 3 or parts[0] != FOLDER or parts[2] != HTML_NAME:
        return []
    folder = parts[1]
    if not folder or folder.startswith(".") or "\x00" in folder or "/" in folder:
        return []
    written = written_page(conn, folder)
    return [] if written is None else [written]


# What a server says for a songbook page it won't send: index.html links it whatever is there.
PAGE_REFUSED = ("This songbook page isn't the one caracole last wrote here (it was changed on a synced device, "
                "say, or caracole has no record of it), so the server won't send it: caracole songbook render "
                "writes it again. The songbook's PDF is beside it.")


def _book_folder(library_dir: Path, book: Songbook) -> Path:
    """``Library/_songbooks/<folder>/``, made if need be; SongbookError when either is a symbolic link
    (caracole doesn't follow one there), not a folder, or can't be made."""
    path = library_dir
    for part in (FOLDER, book.folder):
        path = path / part
        if path.is_symlink():
            raise SongbookError(f"{path} is a symbolic link, which caracole doesn't follow: put a folder there")
        try:
            path.mkdir(parents=True, exist_ok=True)
        except FileExistsError as e:
            raise SongbookError(f"{path} isn't a folder") from e
        except OSError as e:  # no permission, a full disk, a read-only file system
            raise SongbookError(f"can't make the folder {path}: {e.strerror or e}") from e
        if path.is_symlink() or not path.is_dir():
            raise SongbookError(f"{path} isn't a folder")
    return path


def _remove_gone(conn: sqlite3.Connection, library_dir: Path, folders: set[str]) -> int:
    """Take away the files of the songbooks no longer in songbooks.toml, each only while it is still as
    caracole wrote it, then their folder when nothing else is in it; return how many songbooks went.
    Nothing is removed through a symbolic link, in place of ``Library/_songbooks`` or of a folder."""
    rows = conn.execute("SELECT key FROM kv WHERE key LIKE ? ESCAPE '\\'", (_like_prefix(RECORD_KEY),)).fetchall()
    books_dir = library_dir / FOLDER
    if books_dir.is_symlink() or (books_dir.exists() and not books_dir.is_dir()):
        return 0  # nothing is removed through a link: the records stay, for when a folder is back
    gone = 0
    for (key,) in rows:
        folder = key[len(RECORD_KEY):]
        if folder in folders:
            continue
        where = library_dir / FOLDER / folder
        if folder and not folder.startswith(".") and "/" not in folder and not where.is_symlink() and where.is_dir():
            try:
                for name, entry in _record(conn, folder)["files"].items():
                    if name in OUTPUTS:
                        _drop(where / name, entry)
            except OSError as e:  # no permission, say: the record stays, and the next render tries again
                log.warning("songbook folder %s: can't remove caracole's files: %s", where, e)
                continue
            try:
                where.rmdir()  # only when empty: a file of yours stays, and so does its folder
            except OSError:
                pass
        kv_delete(conn, key)
        gone += 1
    return gone


def _like_prefix(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# --- the chordpro runs -------------------------------------------------------------------------


def _song_file(entry: Entry, *, pdf: bool = False) -> str:
    """One song for chordpro: its sheet where the songbook plays it (``Entry.version``), each chord named as its
    viewer names it there (``apply_version``: chordpro moves nothing, and its A# would be the viewer's Bb); for
    the PDF, that sheet's PDF text (``render._sheet_text``), with the viewer's shapes as its diagrams; for
    songbook.cho, without the chord definitions an app may not read. Or a page naming it as missing, which the
    contents then name too. A text that can't be made (a bug in the viewer's code it runs) is a RenderError,
    logged with its traceback: it costs the files it is in, and no more."""
    if entry.cho is not None:
        try:
            return (_sheet_text(entry.cho, key=entry.key, key_source=entry.key_source, version=entry.version) if pdf
                    else _app_text(entry))
        except Exception as e:
            log.warning("%s: cannot make its text for the songbook %s", entry.text, "PDF" if pdf else "ChordPro file",
                        exc_info=True)
            raise RenderError(f"cannot make the text of {entry.text}: {type(e).__name__}: {e}") from e
    why = ("caracole has no sheet for this song yet." if entry.missing == MISSING_SHEET
           else "This song isn't in the library.")
    who = f"{entry.artist} · missing: {entry.missing}" if entry.artist else f"missing: {entry.missing}"
    return (f"{{title: {directive_text(entry.title)}}}\n{{artist: {directive_text(who)}}}\n"
            f"{{subtitle: {directive_text(who)}}}\n{{comment: {directive_text(why)}}}\n")


def _app_text(entry: Entry) -> str:
    """The song's sheet for songbook.cho: as written, or in its version (``apply_version``) without the
    ``{define}`` of each chord's shape that gives the PDF its diagrams."""
    if entry.version == Version():
        return entry.cho
    moved = apply_version(entry.cho, entry.version, key=viewer_key(entry.cho, entry.key, entry.key_source),
                          capo_sheet=parse_sheet(entry.cho).capo)
    return "".join(line for line in moved.splitlines(keepends=True)
                   if (found := directive(line)) is None or found[0] != "define")


def _contents_file(book: Songbook, entries: Sequence[Entry]) -> str:
    """chordpro's template for the contents: the title page, then the contents' heading."""
    missing = sum(1 for e in entries if e.cho is None)
    count = plural(len(entries), "song")
    if missing:
        count += f", {missing} without a sheet yet"
    return (f"{{title: {directive_text(book.name)}}}\n{{artist: {directive_text(count)}}}\n{{subtitle: {directive_text(count)}}}\n\n"
            "A caracole songbook\n{new_page}\n{comment: Contents}\n")


def _book_config(book: Songbook) -> dict[str, Any]:
    """BOOK_CONFIG, and the PDF's document title (its Info /Title, the name a viewer or a phone shows):
    the songbook's name, whose braces are swapped as on its title page (``directive_text``), so no
    ``%{...}`` in it reads as a substitution. chordpro's own is ``%{title}``, the first song's title."""
    info = {"title": " ".join(book.name.split()).translate(_BRACES)}
    return {**BOOK_CONFIG, "pdf": {**BOOK_CONFIG["pdf"], "info": info}}


_BRACES = str.maketrans("{}", "()")


def _pdf(cfg: Config, book: Songbook, entries: Sequence[Entry], printed: Sequence[str], runner: Runner, *,
         font: Path | None) -> bytes:
    """songbook.pdf: every song, in order (``printed``: each one's ``_song_file`` for the PDF), through
    one chordpro run, in caracole's look."""
    with private_dir(cfg.cache_dir, "songbook-") as tmp:
        files = _write_songs(tmp, printed)
        (tmp / CONTENTS_TEMPLATE).write_text(_contents_file(book, entries), encoding="utf-8")
        config = tmp / BOOK_CONFIG_NAME
        config.write_text(json.dumps(_book_config(book), ensure_ascii=False), encoding="utf-8")
        out = tmp / PDF_NAME
        cmd = [cfg.chordpro_bin, "--nodefaultconfigs", f"--config={STYLE_FILE}", f"--config={config}"]
        if font is not None:
            cmd += _font_options(font, BOOK_FONT_ELEMENTS)  # a missing file or a collection is a RenderError
        run_chordpro([*cmd, f"--output={out}", *map(str, files)], out, runner=runner,
                     timeout=TIMEOUT + PER_SONG_TIMEOUT * len(files), chordpro_bin=cfg.chordpro_bin)
        return out.read_bytes()


def _chordpro_file(cfg: Config, texts: Sequence[str], runner: Runner) -> bytes:
    """songbook.cho: the sheets (``texts``: each one's ``_song_file``), each in its key, as chordpro's own
    ChordPro backend writes them, split by {new_song}, without the chord definitions an app may not read
    (--diagrams=none)."""
    with private_dir(cfg.cache_dir, "songbook-") as tmp:
        files = _write_songs(tmp, texts)
        out = tmp / CHO_NAME
        run_chordpro([cfg.chordpro_bin, "--nodefaultconfigs", "--diagrams=none", f"--output={out}", *map(str, files)],
                     out, runner=runner, timeout=TIMEOUT + PER_SONG_TIMEOUT * len(files), chordpro_bin=cfg.chordpro_bin)
        return out.read_bytes()


def _write_songs(tmp: Path, texts: Sequence[str]) -> list[Path]:
    files = []
    for n, text in enumerate(texts, start=1):
        path = tmp / f"{n:03d}.cho"
        path.write_text(text, encoding="utf-8")
        files.append(path)
    return files
