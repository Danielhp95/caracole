"""A songbook's entries, where it plays each, its page and the Songbooks tab's data, for the phone
(docs/superpowers/specs/2026-11-03-conformance-corpus.md): what songbook.py, songbook_section.py and viewer/book.py
answer, written as vectors for the Kotlin port (server.songbooks.SongbookEntries, server.page.SongbookSection,
viewer.pages.SongbookPage) to replay, and checked here against the committed files.

The library, ``songbook/fixtures/entries-library.jsonl`` (the fixture ``entries-library``, helpers.corpus.dump_fixture's
records): songs whose UG sheets caracole kept and rendered (``render_all`` with a stand-in for chordpro: each sheet's
.cho as render.py writes it and its record, kv ``render:files:<song id>``), in keys major and minor, with a capo, in
Chinese, with no chord caracole can read, an auto sheet alone and one beside a human sheet, a .cho changed on disk
since it was written, songs with no sheet (one ignored by overrides.toml, one by its status), Guitar Pro and Power Tab
files; its songbooks both in songbooks.toml and in phone_songbooks, as the phone keeps them (each
``peer_sync.songbook_value``'s songs in canonical JSON), with settings of every kind. Its stamps are made ``NOW``, its
pages and PDFs stand-ins (``PLACEHOLDER``: nothing here reads them, and the tab only sees that they are there), and
its kv the records the entries read alone (``KEPT_KV``; of a render record, its .cho's entry), so a change to the
viewer's pages leaves it as it is. Every record is asked of that fixture replayed into a fresh database and
library folder (helpers.corpus.replay_fixture), as Kotlin's Fixtures.load replays it.

The overrides every record is asked with are entries.jsonl's first record (``overrides``: ``Overrides(version=,
transpose=, ignore=)``, written as ``{"version": {key: entry}, "transpose": {key: n}, "ignore": [key, …]}``): a song's
own version kept by its key, one that moves the sheet, one kept by a key on a sheet with none, a ``[transpose]``, an
ignored song.

An entry, as a record writes ``songbook.Entry``: ``{text, title, artist, song (its identity key, or null), cho (the
SHA-256 of its sheet's .cho as read, or null), missing, transpose, version (``version_query``), key, key_source,
setting (its parts that say something, as songbook_value writes them, or null), keeps_key, plays (``plays_in``),
played (``where_played``'s key and capo, ``[[tonic, mode] or null, capo]``, or null)}``. A setting is its parts that
say something (``{"key": "G", "capo": 0}``).

- songbook/entries.jsonl:
  - ``songbook_entries`` (``book`` names the fixture's songbook): its entries, in order;
  - ``songs_to_get`` of a songbook's entries: the songs' keys;
  - ``songbooks_listing`` of each song of the library (``song``, its key): the songbooks' names;
  - ``with_capo`` and ``on_instrument``, as ``caracole songbook set`` asks them: ``entry`` the songbook's song played
    with ``played`` (a setting, or null: ``commands/songbook._played``), and ``cases``, each the setting given (and
    for on_instrument ``key_given`` and ``capo_given``) and the setting it comes to, ``[given, …, out]``;
  - ``set_song_setting`` over the songbooks ``before`` (as the writers' records: ``{name, songs}``): ``args`` the name,
    the entry and the setting (null to take it off), ``out`` the songbooks after, or ``err`` and ``words`` for a
    SongbookError, songbook.py's words (a setting's problem as ``version.setting_problem`` says it).
- songbook/tab.jsonl:
  - ``songbooks_data`` with ``files=[("songbook.html", "Phone page")]``, the phone's (``times``: each songbook file's
    modification time, in seconds since the epoch, as the replay sets them): the Songbooks tab's data whole;
  - ``book_songs`` (this module's): each songbook's ``viewer.book.BookSong``s as ``render_songbooks`` makes them of
    its entries (``_song_id``, ``_start``), ``[title, artist, cho's SHA-256 or null, key, key_source, transpose,
    missing, id, start]``, and the phone's page of them (``build_songbook`` with no PDF and no .cho beside it):
    ``{sha256, size}``.
- viewer/songbook_pages.jsonl: ``build_songbook(name, songs, pdf=, cho=, pdf_traditional=)`` over the viewer corpus's
  sheets (``helpers.viewer_corpus``), songbooks drawn by ``SEED`` and edges (a songbook of none, of one, of missing
  songs alone, starts that name a ``t`` and starts that don't, names to escape, Chinese songs); each song
  ``{title, artist, cho, key, key_source, transpose, missing, id, start}``. ``out``: the page's ``sha256`` and
  ``size``, and its ``pieces``, the page cut at each JSON block: ``[name, digest]``, the text between two blocks
  named ``text`` and each block by its id, its digest the first ``PART`` hex digits of its text's SHA-256, a song's
  data block (``data-N``) its members' as viewer/pages_*.jsonl write a page's (``name=digest`` …), so a mismatch names
  the piece, and the member, at fault.

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import random
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from helpers import viewer_corpus
from helpers.corpus import VECTORS, check, dump_fixture, jsonl, plain, read_fixture, replay_fixture

MADE_BY = "tests/test_conformance_songbook_tab.py"
HELPER = "test_conformance_songbook_tab."
SONGBOOK = VECTORS / "songbook"
LIBRARY_FIXTURE = "entries-library"
NOW = "2026-11-03T12:00:00Z"
SEED = viewer_corpus.SEED + 900
PART = 16
DIGEST = 8
PLACEHOLDER = b"a stand-in"  # the bytes of every page and PDF of the fixture
PHONE_FILES = (("songbook.html", "Phone page"),)
# The modification time of the songbooks' files, in seconds since the epoch: 2025-11-02T08:30:00Z
TIME = 1762072200

# --- the library ----------------------------------------------------------------------------------------------------

A_MINOR = ("[Verse 1]\n[tab][ch]Am[/ch]          [ch]F[/ch]\nUna canción de prueba[/tab]\n"
           "[tab][ch]C[/ch]              [ch]G[/ch]\nsolo para el analizador[/tab]\n")
G_MAJOR = ("[Verse]\n[tab][ch]G[/ch]           [ch]D[/ch]\nPalabras de prueba[/tab]\n"
           "[tab][ch]Em[/ch]          [ch]C[/ch]\nsolo para el visor[/tab]\n"
           "[Chorus]\n[tab][ch]C[/ch]      [ch]D[/ch]     [ch]G[/ch]\nmade up words here[/tab]\n")
HOTEL = ("[Intro]\n[tab][ch]Am[/ch]   [ch]E7[/ch]   [ch]G[/ch]   [ch]D[/ch]\n[/tab]\n"
         "[Verse]\n[tab][ch]Am[/ch]                 [ch]E7[/ch]\nOn a made up test highway[/tab]\n"
         "[tab][ch]G[/ch]                   [ch]D[/ch]\nwords for the parser alone[/tab]\n"
         "[tab][ch]F[/ch]              [ch]C[/ch]\nsynthetic lines to sing[/tab]\n"
         "[tab][ch]Dm[/ch]               [ch]E[/ch]\nnothing but a test[/tab]\n")
CHINESE = "[Verse]\n[tab][ch]C[/ch]       [ch]G[/ch]\n这是一个合成的例子[/tab]\n[tab][ch]Am[/ch]    [ch]F[/ch]\n我们一起唱歌[/tab]\n"
KEYLESS = "[Verse]\nWords with no chord caracole reads\nla la la, and nothing else\n"
SEPTEMBER = "[Verse]\n[tab][ch]A[/ch]      [ch]C#m[/ch]\nDo you remember words[/tab]\n[tab][ch]F#m[/ch]  [ch]E[/ch]\nmade up[/tab]\n"
CHANGED = "[Verse]\n[tab][ch]D[/ch]   [ch]A[/ch]\nA sheet changed on a device[/tab]\n"

# (artist, title, markup, tonality, capo, tab id): the songs with a human sheet
SHEETS = (
    ("Soda Stereo", "De Música Ligera", A_MINOR, "Am", None, 85053),
    ("Oasis", "Wonderwall", G_MAJOR, "Em", 2, 85054),
    ("Eagles", "Hotel California", HOTEL, "A", 2, 85055),
    ("宋冬野", "斑马，斑马", CHINESE, "C", None, 85056),
    ("Nobody", "Keyless", KEYLESS, "", None, 85057),
    ("Earth - Wind - Fire", "September", SEPTEMBER, "A", None, 85058),
    ("Both", "Sheets", G_MAJOR, "G", None, 85059),
    ("Changed", "On Disk", CHANGED, "D", None, 85060),
    ("AC/DC", "T.N.T. (Live)", A_MINOR, "Am", 4, 85061),
)
AUTO = (("Placeholder Band", "Synthetic Song"), ("Both", "Sheets"), ("Changed", "On Disk"))
NO_SHEET = (("Muse", "Hysteria"), ("Radiohead", "Creep"), ("Blur", "Song 2"))
STATUS_IGNORED = ("Blur", "Song 2")
OVERRIDES_IGNORED = ("Radiohead", "Creep")
GUITAR = (("Oasis", "Wonderwall", "guitar-1.gp5", "guitar-pro"), ("Oasis", "Wonderwall", "guitar-2.ptb", "power"),
          ("Muse", "Hysteria", "guitar-1.ptb", "power"), ("Eagles", "Hotel California", "guitar-3.gpx", "guitar-pro"))

# The songbooks, in order: each song "Artist - Title", or (that, its setting's parts)
SONGBOOKS: tuple[tuple[str, tuple[Any, ...]], ...] = (
    ("Campfire", ("Soda Stereo - De Música Ligera", "oasis - WONDERWALL", "Muse - Hysteria", "Nobody - Nothing",
                  "Radiohead - Creep", "Blur - Song 2", "宋冬野 - 斑馬，斑馬", "Eagles - Hotel California (Live)",
                  "Changed - On Disk", "Both - Sheets", "Placeholder Band - Synthetic Song")),
    ("Settings", (("Soda Stereo - De Música Ligera", {"key": "G"}), ("Oasis - Wonderwall", {"mode": "dorian"}),
                  ("Eagles - Hotel California", {"key": "D", "mode": "dorian"}),
                  ("Nobody - Keyless", {"key": "G"}), ("宋冬野 - 斑马，斑马", {"capo": 3}),
                  ("Both - Sheets", {"instrument": "ukulele"}),
                  ("Earth - Wind - Fire - September", {"key": "Bb", "instrument": "piano"}),
                  ("Placeholder Band - Synthetic Song", {"key": "A", "mode": "aeolian", "instrument": "harmonica"}),
                  ("AC/DC - T.N.T. (Live)", {"instrument": "guitar"}), ("Muse - Hysteria", {"key": "E", "capo": 0}),
                  ("Nobody - Nothing", {"key": "C"}))),
    ("Road trip #1", ("Earth - Wind - Fire - September", ("AC/DC - T.N.T.", {"key": "F#", "capo": 1,
                                                                              "instrument": "baritone"}),
                      ("Nobody - Keyless", {"capo": 2}), "Both - Sheets")),
    ("Empty", ()),
)
# The overrides: (artist, title) and the entry, as overrides.toml's tables name a song
OWN_VERSIONS = ((("Soda Stereo", "De Música Ligera"), "key=Dm&capo=0"), (("Oasis", "Wonderwall"), "t=2&capo=1"),
                (("Nobody", "Keyless"), "key=G&capo=0"), (("Earth - Wind - Fire", "September"), "t=-1&mode=mixolydian"),
                (("Placeholder Band", "Synthetic Song"), "key=Am&mode=dorian"))
TRANSPOSED = ((("Eagles", "Hotel California"), -2), (("Both", "Sheets"), 3))


@functools.cache
def overrides_json() -> dict[str, Any]:
    """The overrides every record is asked with, by the songs' identity keys."""
    from caracole.normalize import identity_key

    return {"version": {identity_key(*song): entry for song, entry in OWN_VERSIONS},
            "transpose": {identity_key(*song): n for song, n in TRANSPOSED},
            "ignore": [identity_key(*OVERRIDES_IGNORED)]}


# The settings with_capo and on_instrument are asked with, and those on_instrument plays a song with first
SETTINGS = ({"key": "G"}, {"mode": "dorian"}, {"key": "D", "mode": "dorian"}, {"capo": 3}, {"key": "C", "capo": 0},
            {"key": "A", "instrument": "ukulele"}, {"key": "G", "instrument": "piano"},
            {"key": "E", "mode": "aeolian", "instrument": "harmonica"}, {"key": "B", "instrument": "guitar"},
            {"key": "F", "capo": 2, "instrument": "piano"}, {"instrument": "flute"}, {"key": "C#", "mode": "locrian"})
PLAYED = (None, {"instrument": "piano"}, {"key": "G", "instrument": "harmonica"}, {"key": "D", "capo": 4})
# set_song_setting's cases: (name, entry, setting or None)
SET_BEFORE = (("Gig", (("Radiohead - Creep", {}), ("Oasis - Wonderwall", {"key": "G", "capo": 2}),
                       ("Muse - Hysteria", {"instrument": "piano"}))),
              ("Picnic", (("Oasis - Wonderwall", {}),)))
SET_CASES = (
    ("Gig", "Radiohead - Creep", {"key": "D", "mode": "dorian", "capo": 0, "instrument": "ukulele"}),
    ("gig", "oasis - wonderwall", None), ("GIG", "Muse - Hysteria", {}), ("Gig", "Muse - Hysteria", {"capo": 11}),
    ("Picnic", "Oasis - Wonderwall (Live)", {"key": "Bb"}), ("Gig", "Muse - Uprising", {"key": "G"}),
    ("Nowhere", "Oasis - Wonderwall", {"key": "G"}), ("Nowhere", "Oasis - Wonderwall", {"capo": 12}),
    ("Gig", "Radiohead - Creep", {"key": "H"}), ("Gig", "Radiohead - Creep", {"key": "g"}),
    ("Gig", "Radiohead - Creep", {"key": "F##"}), ("Gig", "Radiohead - Creep", {"mode": "minor"}),
    ("Gig", "Radiohead - Creep", {"capo": -1}), ("Gig", "Radiohead - Creep", {"instrument": "banjo"}),
    ("Gig", "Radiohead - Creep", {"instrument": "Piano"}), ("Gig", "Radiohead - Creep", {"key": "C♯"}),
    ("Gig", "Radiohead - Creep", {"key": "Db", "mode": "lydian", "capo": 5, "instrument": "recorder"}),
)


def _setting(parts: dict[str, Any] | None):
    from caracole.viewer.version import Setting

    return None if parts is None else Setting(**parts)


def _parts(setting) -> dict[str, Any] | None:
    from caracole.peer_sync import songbook_value
    from caracole.songbook import Songbook, SongbookSong

    if setting is None:
        return None
    return songbook_value(Songbook("x", (SongbookSong("A - B", setting),)))["songs"][0][1]


def _overrides():
    from caracole.overrides import Overrides

    o = overrides_json()
    return Overrides(version=dict(o["version"]), transpose=dict(o["transpose"]), ignore=frozenset(o["ignore"]))


def _songbook(name: str, songs: tuple[Any, ...]):
    from caracole.songbook import Songbook, SongbookSong

    return Songbook(name, tuple(SongbookSong(s) if isinstance(s, str) else SongbookSong(s[0], _setting(s[1]))
                                for s in songs))


def _phone_songbooks(conn: sqlite3.Connection, books) -> None:
    """The songbooks as the phone keeps them, phone_songbooks' rows (core.library.SongbookStore)."""
    from caracole.canonical import dumps
    from caracole.peer_sync import songbook_value
    from caracole.songbook import name_key

    for position, book in enumerate(books):
        conn.execute("INSERT INTO phone_songbooks (key, name, songs, position) VALUES (?, ?, ?, ?)",
                     (name_key(book.name), book.name, dumps(songbook_value(book)["songs"]), position))


def _stamped(conn: sqlite3.Connection) -> None:
    """Every stamp of the fixture's tables made NOW, so the fixture is the same at every run."""
    from helpers.corpus import FIXTURE_TABLES

    for table in FIXTURE_TABLES:
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        for column in columns:
            if column.endswith("_at"):
                conn.execute(f'UPDATE "{table}" SET "{column}" = ? WHERE "{column}" IS NOT NULL', (NOW,))


# The kv records the entries and the tab read; the render's others (its inputs, its progressions) name the
# viewer's build, which no reader here needs, and so do its records' pages (only their .cho is kept).
KEPT_KV = ("render:files:", "songs:key_version")


def _build(conn: sqlite3.Connection, cfg) -> None:
    """The library, as the module's docstring says, in a migrated database and its library folder."""
    from caracole.autochords import ChordSegment, build_sheet
    from caracole.library import keep_file, song_dir
    from caracole.render import render_all
    from caracole.songbook import FILE_NAME, make_songbook, set_song_setting
    from caracole.songs import find_song
    from caracole.normalize import identity_key
    from caracole.versions import upsert_version
    from conftest import add_song
    from helpers.rendered import fake_chordpro
    from helpers.songbooks import keep_sheet

    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    for artist, title, markup, tonality, capo, tab in SHEETS:
        song = add_song(conn, artist, title, added_at=NOW)
        keep_sheet(conn, cfg, song, markup, tab_id=tab, tonality=tonality, capo=capo)
    for artist, title in AUTO:
        song = find_song(conn, identity_key(artist, title)) or add_song(conn, artist, title, added_at=NOW)
        text = build_sheet([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G"), ChordSegment(8.0, 12.0, "Am")],
                           title=title, artist=artist, synced="[00:00.00]made up words\n[00:04.00]for the test\n")
        vid = upsert_version(conn, provider="auto", tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet",
                             kind="auto", rating=0, votes=0, version=1, label=None, url="", raw={}, now=NOW)
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt",
                  data=text.encode("utf-8"), rank=1)
    for artist, title in NO_SHEET:
        add_song(conn, artist, title, added_at=NOW)
    conn.execute("UPDATE songs SET status = 'ignored' WHERE key = ?", (identity_key(*STATUS_IGNORED),))
    for artist, title, name, kind in GUITAR:
        song = find_song(conn, identity_key(artist, title))
        vid = upsert_version(conn, provider="inbox", tab_id=f"inbox-{song.id}-{kind}", song_id=song.id,
                             slot="guitar", kind=kind, rating=0, votes=0, version=1, label=None, url="", raw={},
                             now=NOW)
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=name, data=f"{name} bytes".encode(),
                  rank=1)
    stats = render_all(conn, cfg, _overrides(), runner=fake_chordpro)
    assert stats.failed == 0, stats
    changed = find_song(conn, identity_key("Changed", "On Disk"))
    (song_dir(cfg.library_dir, changed) / "sheet.cho").write_text("{title: changed on a device}\n", encoding="utf-8")
    books = [_songbook(name, songs) for name, songs in SONGBOOKS]
    path = cfg.library_dir / FILE_NAME
    for book in books:
        make_songbook(path, book.name, list(book.texts))
        for song in book.songs:
            if song.setting:
                set_song_setting(path, book.name, song.text, song.setting)
    _phone_songbooks(conn, books)
    for book in books[:3:2]:  # Campfire's and Road trip #1's: their files, as the computer made them
        folder = cfg.library_dir / "_songbooks" / book.folder
        folder.mkdir(parents=True, exist_ok=True)
        for file in ("songbook.html", "songbook.pdf", "songbook.cho"):
            (folder / file).write_bytes(PLACEHOLDER)
    for path in cfg.library_dir.rglob("*"):
        if path.is_file() and path.suffix in (".html", ".pdf"):
            path.write_bytes(PLACEHOLDER)
    _stamped(conn)
    conn.execute("DELETE FROM kv WHERE NOT (" + " OR ".join("key LIKE ?" for _ in KEPT_KV) + ")",
                 [f"{k}%" for k in KEPT_KV])
    # Of each render record, its .cho alone: its pages' entries name the viewer's bytes, which no reader here reads
    for key, value in conn.execute("SELECT key, value FROM kv WHERE key LIKE 'render:files:%'").fetchall():
        record = {name: entry for name, entry in json.loads(value).items() if name.endswith(".cho")}
        conn.execute("UPDATE kv SET value = ? WHERE key = ?", (json.dumps(record), key))


@functools.cache
def _fixture_text() -> str:
    """The fixture, as a jsonl file: the library built in a scratch folder, dumped."""
    import tempfile

    from caracole import db
    from caracole.config import load_config

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = load_config(None, env={"HOME": str(root / "home"), "STATE_DIRECTORY": str(root / "state"),
                                     "CACHE_DIRECTORY": str(root / "cache")})
        (root / "state").mkdir()
        with closing(db.connect(root / "state" / "caracole.sqlite")) as conn:
            from helpers.corpus import phone_schema

            phone_schema(conn)
            _build(conn, cfg)
            records = dump_fixture(conn, cfg.library_dir)
    return jsonl(records, corpus=f"songbook/fixtures/{LIBRARY_FIXTURE}", made_by=MADE_BY)


class _Library:
    """The fixture replayed into a fresh database and library folder, as the phone replays it."""

    def __init__(self, root: Path):
        from caracole import db
        from caracole.config import load_config

        self.cfg = load_config(None, env={"HOME": str(root / "home"), "STATE_DIRECTORY": str(root / "state"),
                                          "CACHE_DIRECTORY": str(root / "cache")})
        (root / "state").mkdir()
        self.cfg.library_dir.mkdir(parents=True)
        self.conn = db.connect(root / "state" / "caracole.sqlite")
        replay_fixture(self.conn, read_fixture(_fixture_text()), self.cfg.library_dir)
        for path in (self.cfg.library_dir / "_songbooks").rglob("*"):
            if path.is_file():
                os.utime(path, (TIME, TIME))

    def books(self):
        from caracole.songbook import load_songbooks, songbooks_file

        return load_songbooks(songbooks_file(self.cfg.library_dir))

    def times(self) -> dict[str, int]:
        return {p.relative_to(self.cfg.library_dir).as_posix(): TIME
                for p in sorted((self.cfg.library_dir / "_songbooks").rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    lib = _Library(tmp_path_factory.mktemp("entries"))
    yield lib
    lib.conn.close()


def _sha(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def entry_json(entry) -> dict[str, Any]:
    from caracole.songbook import where_played
    from caracole.viewer.version import version_query

    label, played = where_played(entry)
    return {"text": entry.text, "title": entry.title, "artist": entry.artist,
            "song": entry.song.key if entry.song is not None else None, "cho": _sha(entry.cho),
            "missing": entry.missing, "transpose": entry.transpose, "version": version_query(entry.version),
            "key": entry.key, "key_source": entry.key_source, "setting": _parts(entry.setting),
            "keeps_key": entry.keeps_key, "plays": label,
            "played": None if played is None else [None if played[0] is None else [played[0].tonic, played[0].mode],
                                                   played[1]]}


def _played(lib: _Library, book, text: str, setting):
    from dataclasses import replace

    from caracole.songbook import SongbookSong, songbook_entries

    (one,) = songbook_entries(lib.conn, lib.cfg.library_dir, _overrides(), replace(book, songs=(SongbookSong(text, setting),)))
    return one


def entries_records(lib: _Library) -> list[dict[str, Any]]:
    from caracole.songbook import on_instrument, songbook_entries, songbooks_listing, songs_to_get, with_capo
    from caracole.songs import list_songs

    S = "caracole.songbook."
    overrides = _overrides()
    books = lib.books()
    out: list[dict[str, Any]] = [{"fn": HELPER + "overrides", "out": overrides_json()}]
    for book in books:
        entries = songbook_entries(lib.conn, lib.cfg.library_dir, overrides, book)
        out.append({"fn": S + "songbook_entries", "book": book.name, "out": [entry_json(e) for e in entries]})
        out.append({"fn": S + "songs_to_get", "book": book.name,
                    "out": [s.key for s in songs_to_get(entries, overrides)]})
    for song in sorted(list_songs(lib.conn), key=lambda s: s.id):
        out.append({"fn": S + "songbooks_listing", "song": song.key,
                    "out": [b.name for b in songbooks_listing(lib.conn, books, song)]})
    for book in books[:3]:
        for text in book.texts:
            base = _played(lib, book, text, None)
            out.append({"fn": S + "with_capo", "book": book.name, "entry": text, "played": None,
                        "cases": [[given, _parts(with_capo(base, _setting(given), overrides))] for given in SETTINGS]})
            for first in PLAYED:
                played = _played(lib, book, text, _setting(first))
                cases = []
                for given in SETTINGS:
                    if "instrument" not in given:
                        continue
                    for key_given, capo_given in ((False, False), (True, False), (False, True)):
                        got = on_instrument(played, _setting(given), key_given=key_given, capo_given=capo_given)
                        cases.append([given, key_given, capo_given, _parts(got)])
                out.append({"fn": S + "on_instrument", "book": book.name, "entry": text, "played": first,
                            "cases": cases})
    return out


def set_records(tmp: Path) -> list[dict[str, Any]]:
    from caracole.peer_sync import songbook_value
    from caracole.songbook import SongbookError, load_songbooks, make_songbook, set_song_setting

    out = []
    for n, (name, entry, parts) in enumerate(SET_CASES):
        path = tmp / f"set-{n}" / "songbooks.toml"
        path.parent.mkdir()
        for book, songs in SET_BEFORE:
            make_songbook(path, book, [text for text, _ in songs])
            for text, setting in songs:
                if setting:
                    set_song_setting(path, book, text, _setting(setting))
        before = [songbook_value(b) for b in load_songbooks(path)]
        record: dict[str, Any] = {"fn": "caracole.songbook.set_song_setting", "before": before,
                                  "args": [name, entry, parts]}
        try:
            set_song_setting(path, name, entry, _setting(parts))
            record["out"] = [songbook_value(b) for b in load_songbooks(path)]
        except SongbookError as e:
            record.update(err=type(e).__name__, words=str(e))
            assert [songbook_value(b) for b in load_songbooks(path)] == before
        out.append(record)
    return out


def test_the_library_fixture_is_the_one_the_records_read():
    check(SONGBOOK / "fixtures" / f"{LIBRARY_FIXTURE}.jsonl", _fixture_text())


def test_every_entry_plays_as_songbook_py_plays_it(library, tmp_path):
    records = entries_records(library) + set_records(tmp_path)
    check(SONGBOOK / "entries.jsonl", jsonl(records, corpus="songbook/entries", made_by=MADE_BY))


def test_the_entries_cover_what_they_should(library):
    records = entries_records(library)
    entries = [e for r in records if r["fn"].endswith("songbook_entries") for e in r["out"]]
    missing = {e["missing"] for e in entries}
    assert {None, "no sheet yet", "not in the library"} <= missing
    assert any(e["plays"] == "key unknown, as written" for e in entries)
    assert any(e["keeps_key"] for e in entries) and any(e["key_source"] == "estimated" or e["key"] for e in entries)
    assert any(e["cho"] and e["key_source"] for e in entries)
    plays = [e["plays"] for e in entries if e["plays"]]
    assert any("capo" in p for p in plays) and any("piano" in p for p in plays), plays
    assert any(r["fn"].endswith("songs_to_get") and r["out"] for r in records)
    changes = {r["fn"] for r in records if r["fn"].endswith(("with_capo", "on_instrument"))
               for case in r["cases"] if case[-1] != case[0]}
    assert len(changes) == 2, "with_capo and on_instrument each change some setting"


# --- the Songbooks tab --------------------------------------------------------------------------------------------


def _book_songs(lib: _Library, book) -> list:
    from caracole.songbook import _song_id, _start, songbook_entries
    from caracole.viewer.book import BookSong

    return [BookSong(e.title, e.artist, cho=e.cho, key=e.key, key_source=e.key_source, transpose=e.transpose,
                     missing=e.missing, id=_song_id(e), start=_start(e))
            for e in songbook_entries(lib.conn, lib.cfg.library_dir, _overrides(), book)]


def tab_records(lib: _Library) -> list[dict[str, Any]]:
    from caracole.songbook_section import songbooks_data
    from caracole.viewer.book import build_songbook

    out: list[dict[str, Any]] = [{
        "fn": "caracole.songbook_section.songbooks_data", "kw": {"files": [list(f) for f in PHONE_FILES]},
        "times": lib.times(),
        "out": plain(songbooks_data(lib.conn, lib.cfg, _overrides(), files=PHONE_FILES))}]
    for book in lib.books():
        songs = _book_songs(lib, book)
        html = build_songbook(book.name, songs)
        out.append({"fn": HELPER + "book_songs", "book": book.name,
                    "out": {"songs": [[s.title, s.artist, _sha(s.cho), s.key, s.key_source, s.transpose, s.missing,
                                       s.id, s.start] for s in songs],
                            "page": {"sha256": _sha(html), "size": len(html.encode("utf-8"))}}})
    return out


def test_the_songbooks_tab_is_songbook_sections_with_the_phones_files(library):
    check(SONGBOOK / "tab.jsonl", jsonl(tab_records(library), corpus="songbook/tab", made_by=MADE_BY))


def test_the_tab_covers_what_it_should(library):
    [data, *pages] = tab_records(library)
    books = data["out"]["books"]
    assert data["out"]["fileLabels"] == ["Phone page"]
    assert any(b["files"] for b in books) and all(f["label"] == "Phone page" for b in books for f in b["files"])
    marks = [s["guitar"] for b in books for s in b["set"] if s["guitar"]]
    assert any(m["page"] for m in marks) and any(m["page"] is None for m in marks)
    assert any(s["get"] for b in books for s in b["set"]) and any(s["href"] for b in books for s in b["set"])
    assert any(s[8] for p in pages for s in p["out"]["songs"])  # a start
    assert any(s[8] is None and s[2] for p in pages for s in p["out"]["songs"])


# --- songbook pages ------------------------------------------------------------------------------------------------

STARTS = (None, "t=2", "mode=dorian", "?t=-1&mode=aeolian", "#capo=3", "t=0&capo=0&inst=ukulele", "inst=piano",
          "t=5&mode=mixolydian&capo=2&inst=guitar", "t=1&at=0.2", "capo=1&alt=ionian.0.9.m.")
MISSING = ("no sheet yet", "not in the library", None)
NAMES = ("Campfire", "Road trip #1", "<b>Rock</b> & \"Roll\" 'n'", "篝火晚会", "", "A " * 30)


def _book_song(rng: random.Random, sheet: viewer_corpus.CorpusSheet | None) -> dict[str, Any]:
    if sheet is None:
        title, artist = rng.choice((("Missing Song", "Nobody"), ("斑马，斑马", "宋冬野"), ("A <b>", "&amp;")))
        return {"title": title, "artist": artist, "cho": None, "key": None, "key_source": None,
                "transpose": 0, "missing": rng.choice(MISSING), "id": f"{rng.getrandbits(40):010x}", "start": None}
    return {"title": sheet.title or "Untitled", "artist": sheet.artist, "cho": sheet.cho, "key": sheet.key,
            "key_source": sheet.key_source, "transpose": rng.choice((0, 0, 0, 2, -3, 7)), "missing": None,
            "id": f"{rng.getrandbits(40):010x}", "start": rng.choice(STARTS)}


def _songbooks() -> list[tuple[str, list[dict[str, Any]], dict[str, Any]]]:
    rng = random.Random(SEED)
    sheets = viewer_corpus.sheets()
    pick = [s for s in sheets if {"chinese", "kana", "auto", "capo", "legend", "tab", "preamble", "define"}
            & set(s.tags)][:24] + rng.sample(sheets, 16)
    out: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = []
    for n in range(10):
        songs = [_book_song(rng, rng.choice(pick)) for _ in range(rng.randint(2, 5))]
        if rng.random() < 0.4:
            songs.insert(rng.randrange(len(songs) + 1), _book_song(rng, None))
        kw: dict[str, Any] = {}
        if rng.random() < 0.6:
            kw["pdf"] = "songbook.pdf"
            if rng.random() < 0.5:
                kw["pdf_traditional"] = "songbook (Traditional).pdf"
        if rng.random() < 0.5:
            kw["cho"] = "songbook.cho"
        out.append((NAMES[n % len(NAMES)] or f"Book {n}", songs, kw))
    chinese = [s for s in sheets if "chinese" in s.tags][:2]
    out += [
        ("Empty", [], {}),
        ("One", [_book_song(rng, sheets[0])], {"pdf": "songbook.pdf", "cho": "songbook.cho"}),
        ("Missing alone", [_book_song(rng, None), _book_song(rng, None)], {"pdf": "songbook.pdf"}),
        ("中文", [_book_song(rng, s) for s in chinese] + [_book_song(rng, sheets[1])],
         {"pdf": "songbook.pdf", "pdf_traditional": "songbook (Traditional).pdf"}),
        ("Phone", [_book_song(rng, s) for s in pick[:3]], {}),
    ]
    return out


_BLOCK = '<script type="application/json" id="'


def _members(payload: str) -> str:
    data = json.loads(payload)
    return " ".join(f"{name}={hashlib.sha256(json.dumps(v, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:DIGEST]}"
                    for name, v in data.items())


def pieces(html: str) -> list[list[str]]:
    """The page cut at its JSON blocks, as the module's docstring says."""
    out: list[list[str]] = []
    at = 0
    while (start := html.find(_BLOCK, at)) >= 0:
        out.append(["text", hashlib.sha256(html[at:start].encode()).hexdigest()[:PART]])
        name_end = html.index('">', start)
        name = html[start + len(_BLOCK):name_end]
        end = html.index("</script>", name_end)
        payload = html[name_end + 2:end]
        digest = _members(payload) if name.startswith("data-") else hashlib.sha256(payload.encode()).hexdigest()[:PART]
        out.append([name, digest])
        at = end
    out.append(["text", hashlib.sha256(html[at:].encode()).hexdigest()[:PART]])
    return out


def page_records() -> list[dict[str, Any]]:
    from caracole.viewer.book import BookSong, build_songbook

    out = []
    for name, songs, kw in _songbooks():
        html = build_songbook(name, [BookSong(**s) for s in songs], **kw)
        out.append({"fn": "caracole.viewer.book.build_songbook", "args": [name, songs], "kw": kw,
                    "out": {"sha256": _sha(html), "size": len(html.encode("utf-8")), "pieces": pieces(html)}})
    return out


def test_every_songbook_page_is_book_pys():
    check(VECTORS / "viewer" / "songbook_pages.jsonl",
          jsonl(page_records(), corpus="viewer/songbook_pages", made_by=MADE_BY))


def test_the_pieces_make_the_page():
    from caracole.viewer.book import BookSong, build_songbook

    for name, songs, kw in _songbooks()[:3]:
        html = build_songbook(name, [BookSong(**s) for s in songs], **kw)
        assert sum(1 for p in pieces(html) if p[0] != "text") == html.count(_BLOCK)
