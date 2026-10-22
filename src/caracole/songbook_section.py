"""The library page's Songbooks tab: each songbook of songbooks.toml as data, in index.html
(library_page.py, the page's ``songbooks``) and in caracole serve's ``/jobs.json``, which gives it again
once a songbook's change is over (web/jobs_routes.py), for the page's script to draw the tab again.

library_assets/songbooks.js draws it, with songbooks.css: on the left the songbooks as lines (their
names, how many songs, how many still without a sheet, when caracole last made their files), on the right
the songbook opened as a set list, each song with where the songbook plays it (``songbook.plays_in``).
Every text is data, which the script puts in the page with ``textContent``.

``songbooks_data`` gives:

- ``books``: each songbook, in songbooks.toml's order: its ``name``; ``songs``, how many; ``missing``, how
  many have no sheet in it (not in the library, or no sheet yet); ``changed``, the day (UTC) caracole last
  wrote one of its files, None before it made any; ``files``, those it made, as links relative to
  index.html, percent-encoded (``label``: "PDF", "Phone page", "ChordPro", in that order); and ``set``, its
  songs in order, each with its place (``n``), its entry as songbooks.toml writes it (``entry``, which the
  forms name it by), its identity ``key`` (its song's, else its entry's: what the page knows a search's
  result in it by), its ``title`` and ``artist``, its song's ``id`` (None for one not in the library),
  ``missing`` (why it has no sheet in it, else None), ``get`` (a lookup could get its sheet now:
  ``songbook.songs_to_get``), ``plays`` (where the songbook plays it, in words, "G Dorian", "E Minor, capo 2"; None
  without a sheet), ``own`` (no setting of its own here: it follows the song's own version), ``at`` (where
  it plays, for the setting's menus: the key's ``tonic`` as a pitch class, its ``mode``, both None for a
  sheet with no key caracole can read, and its ``capo``; None without a sheet) and ``href`` (its sheet, as
  its line in the library opens it; None without one);
- ``error``: why songbooks.toml can't be read (then no songbooks), else None;
- ``keys``, ``modes`` and ``capoMax``: what a setting's menus offer: each pitch class's name as chord sheets
  write it most (``theory.spelling``), the modes with the viewer's names ("Major", "Dorian"...), and the
  highest capo (``songbook.CAPO_MAX``). A key or a mode a song plays in is the theory's to work out
  (viewer/theory.py, viewer/version.py): the page only shows the names it is given.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from caracole.config import Config
from caracole.overrides import Overrides

if TYPE_CHECKING:
    from caracole.songbook import Entry

log = logging.getLogger(__name__)

# A songbook's files, as its tab links them: the PDF, the page for the phone, the ChordPro file.
FILES = (("songbook.pdf", "PDF"), ("songbook.html", "Phone page"), ("songbook.cho", "ChordPro"))


def songbooks_data(conn: sqlite3.Connection, cfg: Config, overrides: Overrides) -> dict[str, Any]:
    """The songbooks as the Songbooks tab draws them (see the module's docstring). A songbooks.toml that can't
    be read is said (``error``), and costs the rest of the page nothing."""
    from caracole.songbook import CAPO_MAX, SongbookError, load_songbooks, songbooks_file
    from caracole.viewer.theory import MODES, spelling
    from caracole.viewer.version import MODE_NAMES

    shared: dict[str, Any] = {"keys": spelling(None), "modes": [[m, MODE_NAMES[m]] for m in MODES],
                              "capoMax": CAPO_MAX}
    try:
        books = load_songbooks(songbooks_file(cfg.library_dir))
    except SongbookError as e:
        return {"books": [], "error": f"songbooks.toml can't be read: {e}. Fix it, and the songbooks are back; "
                                      "until then each keeps its files.", **shared}
    return {"books": [_book(conn, cfg, overrides, book) for book in books], "error": None, **shared}


def _book(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, book: Any) -> dict[str, Any]:
    from caracole.library_page import sheet_href  # which imports this module
    from caracole.songbook import FOLDER, entry_keys, songbook_entries, songs_to_get

    entries = songbook_entries(conn, cfg.library_dir, overrides, book)
    getting = {song.id for song in songs_to_get(entries, overrides)}
    folder = cfg.library_dir / FOLDER / book.folder
    made = _made(folder)
    base = f"{FOLDER}/{quote(book.folder, safe='')}"
    songs = []
    for n, e in enumerate(entries, start=1):
        plays, at = _plays(e)
        songs.append({
            "n": n, "entry": e.text, "key": e.song.key if e.song is not None else min(entry_keys(e.text), default=""),
            "title": e.title, "artist": e.artist,
            "id": e.song.id if e.song is not None else None, "missing": e.missing,
            "get": e.song is not None and e.song.id in getting, "plays": plays, "own": not e.setting,
            "at": at, "href": sheet_href(cfg.library_dir, e.song) if e.song is not None and e.cho else None,
        })
    newest = max(made.values(), default=None)
    return {
        "name": book.name, "songs": len(entries), "missing": sum(1 for e in entries if e.missing),
        "changed": datetime.fromtimestamp(newest, UTC).strftime("%Y-%m-%d") if newest is not None else None,
        "files": [{"name": name, "label": label, "href": f"{base}/{quote(name)}"}
                  for name, label in FILES if name in made],
        "set": songs,
    }


def _made(folder: Any) -> dict[str, float]:
    """The songbook's files there are, regular files alone (no link followed), each with when it was written."""
    found = {}
    for name, _ in FILES:
        try:
            info = os.lstat(folder / name)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode):
            found[name] = info.st_mtime
    return found


def _plays(entry: Entry) -> tuple[str | None, dict[str, Any] | None]:
    """Where the songbook plays the song (``songbook.plays_in``, in words), and for the setting's menus the key of
    the shapes played (a pitch class and a mode, None for a sheet with no key) and the capo; None for a song
    without a sheet, or one the viewer's code can't read (a bug, logged with its traceback)."""
    from caracole.songbook import where_played

    label, played = where_played(entry)
    if played is None:
        return label, None
    key, capo = played
    return label, {"tonic": key.tonic if key else None, "mode": key.mode if key else None, "capo": capo}
