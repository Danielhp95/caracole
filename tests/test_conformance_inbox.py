"""A file shared to the phone, filed as inbox.py files an ``_inbox/`` entry, for the Kotlin lane inbox-share (core.inbox's
``Inbox`` and ``MusicNames``): the names a download is read by, the song it is of, and what filing it writes, each
Python's to the byte, since a kept file's SHA-256 and its version are in its song's sync unit.

The phone reads a score by its name alone: MusicXML's header (musicxml.py) is left out there (the plan's §11, Q12), so
no record is one inbox.py files by its header (``test_no_record_is_filed_by_a_musicxml_header``).

**Vectors** (vectors/inbox/), a header, then a record a line:

- ``names.jsonl``: ``{fn: "caracole.inbox.parse_download_name", args: [name], out: [artist, title, version]}`` over
  every download name tests/test_inbox.py writes (each string literal of it with an extension inbox.py files, read
  with ``ast``: an edit there regenerates the corpus) and the edges below (``NAMES``); and ``{fn:
  "caracole.music.Names", kw: {a: [artist, title], b: [artist, title]}, out: {artists, titles, title_score,
  artist_score, score}}``, ``Names.of(*a)``'s forms and its scores against ``Names.of(*b)``.
- ``match.jsonl``: ``{fn: "caracole.inbox._match", kw: {artist, title, songs: [[artist, title, key]…]}, out: i}``,
  the song a download's names are of, by its index in ``songs`` (null: none), the songs as list_songs gives them
  (newest first).
- ``file.jsonl``: one file filed over the fixture library (``file_fixture_library.jsonl``, helpers.corpus's format:
  songs of wanted.txt, some keeping Guitar Pro files and scores, some put in their folders by hand, one ignored),
  ``{fn: "caracole.inbox.file", case, fixture, kw: {name, data, now}, changes, out, after}``: the fixture replayed
  into a fresh database and library folder, ``changes`` made to the folder (``{path: null}`` deletes a file,
  ``{path: {"base64"}}`` writes one), then the file dropped into ``_inbox/`` and ``file_inbox`` run; ``out`` what it
  came to, ``{"filed": "kept", "song": key, "name"}`` (kept for the song under that name), ``{"filed": "put_back",
  "paths": [path…]}`` (a file the library lost written back, each path relative to the library), ``{"filed":
  "duplicate", "song": key, "name"}`` (a file the library holds already: the first of its copies, by id, that holds
  it) or ``{"filed": "unmatched"}`` (no song fits, or its copy's place holds other bytes now: it waits); ``after``
  the rows of ``songs``, ``versions`` and ``files`` it wrote (new, or other than before) whole, by table, and each
  regular file of the library (``_inbox/`` aside) it wrote, by path with its SHA-256.

Stamps: the time inbox.py reads from the clock (songs.utc_now_iso, the inbox version's ``fetched_at``) is ``kw.now``,
and ``files.created_at``, SQLite's clock, is checked to be now and recorded as ``kw.now``, which the phone's
``Inbox.file`` is given.

The answers are the same on every run (``test_the_vectors_are_the_same_on_another_run``). Regenerate with
``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from helpers.corpus import VECTORS, check, dump_fixture, jsonl, read_fixture, replay_fixture
from helpers.peer_libraries import NOW, Library

MADE_BY = "tests/test_conformance_inbox.py"
INBOX = VECTORS / "inbox"
NAMES_FILE = INBOX / "names.jsonl"
MATCH_FILE = INBOX / "match.jsonl"
FILE_FILE = INBOX / "file.jsonl"
FIXTURE_FILE = INBOX / "file_fixture_library.jsonl"
TEST_INBOX = Path(__file__).with_name("test_inbox.py")
TOP_FILES = ("wanted.txt", "overrides.toml", "songbooks.toml")  # the computer's: the phone has none
TABLES = ("songs", "versions", "files")
LATER = "2026-11-03T12:00:00Z"  # a filing's now: after every stamp of the fixture
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

# Download names beyond tests/test_inbox.py's: the version's spellings, the separator's, brackets of other scripts,
# names a path reads otherwise (no stem, dots alone, a folder), other scripts, a version past any machine word.
NAMES = (
    "Artist - Title (VER.3).gp5", "Artist - Title (Ver. 12 by someone) (live).gp5", "Artist - Title(ver 2).gp5",
    "Artist - Title ( ver 2 ).gp5", "Artist - Title (ver \u0663).gp5", "Artist - Title (version 2).gp5",
    "Artist - Title (ver 2)(ver 3).gp5", "Artist - Title (ver 99999999999999999999).gp5",
    "Artist - Title (ver 007).gp5", "A - B - C.gp5", " - Title.gp5", "Artist - .gp5", "Artist -Title.gp5",
    "Artist \u2013 Title.gp5", "Artist  -  Title.gp5", "Artist\u00a0-\u00a0Title.gp5", "Artist\t-\tTitle.gp5",
    "Title (feat. Someone).gp5", "(intro).gp5", "(ver 2).gp5", "a.b.c.gp5", ".gp5", "...gp5", "noext", "trailing.",
    "x/y/Artist - Title.gp5", "Artist - Title.tar.gz", "   .gp5", "Ünïcödé - Fïlé.GP5", "Кино - Группа крови.gp5",
    "Кино (Kino) - Группа крови (Gruppa Krovi) (ver 2).gp5", "Artist - Title [live].gp5",
    "Artist - Title ((nested)).gp5", "Artist - Title (unclosed.gp5", "Artist - Title ).gp5", "😀 - Song (😀).gp5",
    "봄날 (Spring Day) - BTS (방탄소년단).mxl", "米津玄師 - Lemon (レモン).musicxml", "Oasis - Wonderwall (1).pdf",
    "Oasis - Wonderwall (2) (ver 4).mscz", "Oasis - Wonderwall.MID", "download (3).pdf", "score.musicxml",
)

# music.Names, (artist, title) against (artist, title): exact, hyphens and words, close titles either side of the
# cutoff and of the margin below it, another script and its romanization, a name in two scripts, a title alone.
PAIRS = (
    (("Soda Stereo", "De Musica Ligera"), ("Soda Stereo", "De Música Ligera")),
    (("Soda-Stereo", "De Musica Ligera"), ("Soda Stereo", "De Música Ligera")),
    (("Stereo Soda", "De Musica Ligera"), ("Soda Stereo", "De Música Ligera")),
    (("Soda Stereo y amigos", "De Musica Ligera"), ("Soda Stereo", "De Música Ligera")),
    (("Oasis", "Wonderwal"), ("Oasis", "Wonderwall")),
    (("Oasys", "Wonderwall"), ("Oasis", "Wonderwall")),
    (("Oasis", "Wondrwl"), ("Oasis", "Wonderwall")),
    (("Oasis", "Wonder"), ("Oasis", "Wonderwall")),
    (("Oasis", "Champagne Supernova"), ("Oasis", "Wonderwall")),
    (("Radiohead", "Creep (Acoustic)"), ("Radiohead", "Creep")),
    (("", "creep"), ("Radiohead", "Creep")),
    (("Song Dongye (宋冬野)", "斑马 斑马 Banma Banma Zebra Zebra"), ("宋冬野", "斑马，斑马")),
    (("宋冬野", "斑马斑马"), ("宋冬野", "斑马，斑马")),
    (("Song Dongye", "Banma Banma"), ("宋冬野", "斑马，斑马")),
    (("宋冬野", "董小姐"), ("宋冬野", "斑马，斑马")),
    (("Jay Chou (周杰倫)", "晴天"), ("周杰伦", "晴天")),
    (("米津玄師", "Lemon (レモン)"), ("米津玄師", "Lemon")),
    (("Кино", "Группа крови"), ("Кино (Kino)", "Группа крови (Gruppa Krovi)")),
    (("Joaquín Rodrigo", "Concierto de Aranjuez"), ("Joaquin Rodrigo", "Concierto de Aranjuez (Adagio)")),
    (("!!!", "???"), ("Oasis", "Wonderwall")),
    (("Oasis", ""), ("Oasis", "")),
)

# The songs of the library a download is matched among (list_songs': newest first), and those of _match's own cases.
LONG = "Concierto de Aranjuez para guitarra y orquesta, segundo movimiento: Adagio, arreglo para guitarra sola de Narciso"
SONGS = {  # the fixture's songs, by the name the cases give each; added in this order
    "ligera": ("Soda Stereo", "De Música Ligera"), "persiana": ("Soda Stereo", "Persiana Americana"),
    "creep": ("Radiohead", "Creep"), "tlc": ("TLC", "Creep"), "wall": ("Oasis", "Wonderwall"),
    "zebra": ("宋冬野", "斑马，斑马"), "miss": ("宋冬野", "董小姐"), "sunny": ("周杰伦", "晴天"),
    "one": ("Joaquín Rodrigo", LONG + ", part one"), "two": ("Joaquín Rodrigo", LONG + ", part two"),
    "song2": ("Blur", "Song 2"), "metallica": ("Metallica", "One"),
}
IGNORED = ("metallica",)


def key(name: str) -> str:
    """The identity key of the fixture's song ``name``."""
    from caracole.normalize import identity_key

    return identity_key(*SONGS[name])


def b64(data: bytes) -> dict[str, str]:
    return {"base64": base64.b64encode(data).decode("ascii")}


def unb64(value: dict[str, str]) -> bytes:
    return base64.b64decode(value["base64"])


# --- names ----------------------------------------------------------------------------------------------------------


def inbox_test_names() -> list[str]:
    """Every download name tests/test_inbox.py writes: each string literal with an extension inbox.py files."""
    from caracole.inbox import GP_EXTENSIONS, SCORE_EXTENSIONS

    kept = (*GP_EXTENSIONS, *SCORE_EXTENSIONS)
    found: list[str] = []
    for node in ast.walk(ast.parse(TEST_INBOX.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in found:
            if Path(node.value).suffix.lower() in kept and "\n" not in node.value:
                found.append(node.value)
    return found


def names_records() -> list[dict[str, Any]]:
    from caracole.inbox import parse_download_name
    from caracole.music import Names

    out: list[dict[str, Any]] = []
    for name in dict.fromkeys([*inbox_test_names(), *NAMES]):
        out.append({"fn": "caracole.inbox.parse_download_name", "args": [name],
                    "out": list(parse_download_name(name))})
    for a, b in PAIRS:
        own, other = Names.of(*a), Names.of(*b)
        out.append({"fn": "caracole.music.Names", "kw": {"a": list(a), "b": list(b)},
                    "out": {"artists": list(own.artists), "titles": list(own.titles),
                            "title_score": own.title_score(other), "artist_score": own.artist_score(other),
                            "score": own.score(other)}})
    return out


# --- _match ---------------------------------------------------------------------------------------------------------


def _songs(pairs) -> list[SimpleNamespace]:
    from caracole.normalize import identity_key

    return [SimpleNamespace(artist=a, title=t, key=identity_key(a, t)) for a, t in pairs]


def match_records() -> list[dict[str, Any]]:
    from caracole.inbox import _match, parse_download_name

    library = _songs(reversed(list(SONGS.values())))  # list_songs': the newest first
    two = _songs([("Oasis", "Wonderwall"), ("Ryan Adams", "Wonderwall")])
    alike = _songs([("Oasis", "Wonderwall"), ("Oasis", "Wonderwal"), ("Oasis", "Wonderwall!")])
    out: list[dict[str, Any]] = []

    def rec(artist: str | None, title: str, songs, case: str) -> None:
        found = _match(artist, title, songs)
        out.append({"fn": "caracole.inbox._match", "case": case,
                    "kw": {"artist": artist, "title": title, "songs": [[s.artist, s.title, s.key] for s in songs]},
                    "out": None if found is None else next(i for i, s in enumerate(songs) if s is found)})

    for name in dict.fromkeys([*inbox_test_names(), *NAMES]):
        artist, title, _ = parse_download_name(name)
        rec(artist, title, library, f"the names of {name!r} among the library's songs")
    rec("Oasis", "Wonderwall", two, "by identity")
    rec(None, "Wonderwall", two, "a title alone two songs have: none")
    rec(None, "Wonderwall", two[:1], "a title alone one song has")
    rec("oasis", "WONDERWALL", alike, "identity first, whatever case")
    rec("Oasis", "Wonderwalll", alike, "the closest of those that fit")
    rec("Oasis", "Wonderwal", alike[::-1], "the identity's song, though another comes first")
    rec("Oasys", "Wonderwal", alike, "artist too far")
    rec(None, "Wonderwal", alike, "a title alone close to two: none")
    rec("Oasis", "Wonderwall", [], "no song")
    rec("", "Wonderwall", two[:1], "an empty artist is none")
    return out


# --- filing one file ------------------------------------------------------------------------------------------------


def _version(lib: Library, song: str, provider: str, tab: str, kind: str) -> int:
    from caracole.songs import find_song
    from caracole.versions import upsert_version

    return upsert_version(lib.conn, provider=provider, tab_id=tab, song_id=find_song(lib.conn, key(song)).id,
                          slot="guitar", kind=kind, rating=0, votes=0, version=1, label=None, url="", raw={}, now=NOW)


def _keep(lib: Library, song: str, version_id: int, name: str, data: bytes, rank: int = 1) -> None:
    from caracole.library import keep_file
    from caracole.songs import find_song

    assert keep_file(lib.conn, lib.cfg.library_dir, song=find_song(lib.conn, key(song)), version_id=version_id,
                     name=name, data=data, rank=rank)


def _by_hand(lib: Library, song: str, name: str, data: bytes) -> None:
    from caracole.library import song_dir
    from caracole.songs import find_song

    path = song_dir(lib.cfg.library_dir, find_song(lib.conn, key(song))) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


SAME = b"SAME BYTES, TWO SONGS"
SONG2_GP = b"FICHIER GUITAR PRO v5.00 song 2"
WALL_PDF = b"%PDF-1.4 wonderwall score"


def build_library(lib: Library) -> None:
    from caracole.library import song_dir
    from caracole.songs import find_song, update_song

    for artist, title in SONGS.values():
        lib.song(artist, title, sheet=None, lyrics=None)
    for name in IGNORED:
        update_song(lib.conn, find_song(lib.conn, key(name)).id, status="ignored")
    one, two = (find_song(lib.conn, key(n)) for n in ("one", "two"))
    assert one.key != two.key and song_dir(lib.cfg.library_dir, one) == song_dir(lib.cfg.library_dir, two)
    # One file's bytes kept by two songs: a download of them under no song's name is either's.
    _keep(lib, "persiana", _version(lib, "persiana", "inbox", "guitar-pro", "guitar-pro"), "guitar-1.gp5", SAME)
    _keep(lib, "creep", _version(lib, "creep", "gtptabs", "9", "guitar-pro"), "guitar-1.gp5", SAME)
    # Blur - Song 2: a Guitar Pro file and a score filed, their kin put there by hand.
    _keep(lib, "song2", _version(lib, "song2", "inbox", "guitar-pro", "guitar-pro"), "guitar-1.gp5", SONG2_GP)
    _keep(lib, "song2", _version(lib, "song2", "inbox", "score", "score"), "score-1.pdf", b"%PDF-1.4 song 2")
    for name in ("guitar-2.gpx", "score-2.pdf", "notes.txt"):
        _by_hand(lib, "song2", name, f"by hand: {name}".encode())
    # Oasis - Wonderwall: a score filed.
    _keep(lib, "wall", _version(lib, "wall", "inbox", "score", "score"), "score-1.pdf", WALL_PDF)
    # Two songs of one folder: the first keeps guitar-1.
    _keep(lib, "one", _version(lib, "one", "inbox", "guitar-pro", "guitar-pro"), "guitar-1.gp5", b"GP of part one")


def _settled(conn) -> None:
    """Every stamp caracole writes as now, made ``NOW``: the fixture is the same on every run."""
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (NOW, NOW))
    conn.execute("UPDATE files SET created_at = ?", (NOW,))


def filing(case: str, name: str, data: bytes, changes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"fn": "caracole.inbox.file", "case": case, "fixture": "library",
            "kw": {"name": name, "data": b64(data), "now": LATER}, "changes": changes}


def cases() -> list[dict[str, Any]]:
    gone = "Blur/Song 2/guitar-1.gp5"
    return [
        filing("a Guitar Pro file named as the song is: guitar-1, the song's inbox version", "Soda Stereo - De Musica "
            "Ligera.gp5", b"GP-DATA"),
        filing("a Power Tab file: its power version", "Soda Stereo - De Musica Ligera.ptb", b"ptab-data"),
        filing("a version number in the name still names the song",
            "Soda Stereo - De Musica Ligera (ver 2 by Pelusteriano).gp5", b"GP-DATA v2"),
        filing("an extension in capitals is kept in lower case", "Oasis - Wonderwall.GP5", b"GP-CAPS"),
        filing("1 kept and 2 put there by hand: 3, the version kept", "Blur - Song 2.gpx", b"GPX of song 2"),
        filing("a score: its number of its extension, 1 kept and 2 by hand", "Blur - Song 2.pdf", b"%PDF new"),
        filing("a score of an extension the song has none of: 1", "Blur - Song 2.mscz", b"PK-MSCZ"),
        filing("another score of a pdf: 2", "Oasis - Wonderwall (1).pdf", b"%PDF-1.4 another"),
        filing("a MusicXML file named as the song is", "Oasis - Wonderwall.musicxml", b"MusicXML bytes, unread"),
        filing("a compressed MusicXML file", "Oasis - Wonderwall.mxl", b"PK-not-a-real-mxl"),
        filing("MIDI, of either extension", "Oasis - Wonderwall.midi", b"MThd-midi"),
        filing("the other song of a folder keeps 1: 2", f"Joaquín Rodrigo - {LONG}, part two.gp5", b"GP of part two"),
        filing("the bytes of a file the song keeps: a duplicate", "Blur - Song 2 (1).gp5", SONG2_GP),
        filing("the same bytes under no song's name: a duplicate, the first copy that holds them",
            "download.gp5", SAME),
        filing("a file the library lost, dropped again: put back", "Blur - Song 2.gp5", SONG2_GP, {gone: None}),
        filing("a lost score under a name no song has: put back by its bytes", "download (3).pdf", WALL_PDF,
            {"Oasis/Wonderwall/score-1.pdf": None}),
        filing("bytes two songs keep, one lost: put back there, the other held",
            "download.gp5", SAME, {"Soda Stereo/Persiana Americana/guitar-1.gp5": None}),
        filing("bytes two songs keep, both lost: both put back", "download.gp5", SAME,
            {"Soda Stereo/Persiana Americana/guitar-1.gp5": None, "Radiohead/Creep/guitar-1.gp5": None}),
        filing("bytes of a kept file whose place holds other bytes now: nothing replaced, it waits",
            "Blur - Song 2.gp5", SONG2_GP, {gone: b64(b"edited on the laptop")}),
        filing("another song's bytes named for this song: filed for this one", "Soda Stereo - De Musica Ligera.gp5",
            SAME),
        filing("a name in Chinese meets its song", "宋冬野 - 斑马斑马.gp", b"GP7-zebra"),
        filing("a name in two scripts meets its song", "Song Dongye (宋冬野) - 斑马 斑马 Banma Banma Zebra Zebra "
            "(ver 1 by someone).gp5", b"GP-two-scripts"),
        filing("a Traditional artist meets the Simplified one's song", "Jay Chou (周杰倫) - 晴天 (ver 1).gp5", b"GP-sunny"),
        filing("a title alone one song has", "wonderwall.gp5", b"GP-title-alone"),
        filing("a title alone two songs have: it waits", "creep.gp5", b"GP-creep"),
        filing("an artist names the one of two", "Radiohead - Creep.gp4", b"GP4-creep"),
        filing("a title a letter short meets its song", "Oasis - Wonderwal.gp5", b"GP-typo"),
        filing("an artist too far off: it waits", "Oasys - Wonderwall.gp5", b"GP-oasys"),
        filing("an ignored song gets nothing", "Metallica - One.gp5", b"GP-one"),
        filing("no song of that name", "Somebody Else - Unknown Song.gp5", b"GP-unknown"),
        filing("an extension inbox.py files nothing of", "Oasis - Wonderwall.txt", b"lyrics"),
        filing("no extension", "Oasis - Wonderwall", b"GP-no-extension"),
        filing("a MusicXML file whose name is no song's: it waits", "score.musicxml", b"not xml at all"),
        filing("empty bytes are a file too", "Blur - Song 2.gp3", b""),
    ]


def _rows(conn, table: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, tuple(row))) for row in cursor.fetchall()]


def _library(root: Path) -> dict[str, str]:
    """Every regular file of the library, ``_inbox/`` aside, by path with its SHA-256."""
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink() and p.relative_to(root).parts[0] != "_inbox"}


def _stamped(before: list[dict[str, Any]], after: list[dict[str, Any]], now: str) -> None:
    """keep_file's ``created_at``, SQLite's clock: each row it wrote holds a time of that form now, recorded as
    ``now``, the time the phone's Inbox.file is given."""
    old = {r["id"]: r["created_at"] for r in before}
    for row in after:
        if old.get(row["id"]) == row["created_at"]:
            continue
        stamp = row["created_at"]
        assert STAMP.fullmatch(stamp), stamp
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs(datetime.now(UTC) - at) < timedelta(minutes=5), stamp
        row["created_at"] = now


def file_one(lib: Library, name: str, data: bytes) -> dict[str, Any]:
    """``name`` with ``data`` dropped into ``_inbox/`` and filed as file_inbox files it, and what it came to."""
    from caracole import inbox
    from caracole.library import holds
    from caracole.songs import get_song

    root = lib.cfg.library_dir
    folder = root / "_inbox"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    again: list[tuple[list, tuple[list[Path], bool]]] = []
    real = inbox._again

    def heard(conn, library_dir, copies, data):
        answer = real(conn, library_dir, copies, data)
        again.append((list(copies), answer))
        return answer

    with mock.patch.object(inbox, "_again", heard):
        stats = inbox.file_inbox(lib.conn, root)
    left = (folder / name).exists()
    for p in folder.iterdir():
        p.unlink()
    folder.rmdir()
    if again:
        (copies, (put_back, held)), = again
        if put_back:
            assert not left and stats.filed == put_back
            return {"filed": "put_back", "paths": [p.relative_to(root).as_posix() for p in put_back]}
        if held:
            assert not left and stats.duplicates
            first = next(c for c in copies if holds(root / c.path, c.sha256, len(data)))
            return {"filed": "duplicate", "song": get_song(lib.conn, first.song_id).key, "name": first.name}
        assert left and stats.unmatched
        return {"filed": "unmatched"}
    if stats.unmatched:
        assert left
        return {"filed": "unmatched"}
    assert not left and not stats.duplicates, "a duplicate by keep_file alone: a copy of the song is in _copies"
    (path,) = stats.filed
    kept = lib.conn.execute("SELECT s.key, f.name FROM files f JOIN songs s ON s.id = f.song_id WHERE f.path = ?",
                            (path.relative_to(root).as_posix(),)).fetchone()
    return {"filed": "kept", "song": kept[0], "name": kept[1]}


class Filing:
    """The fixture, built and replayed in ``workdir``, and the records made over it."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.text: str | None = None
        self.n = 0

    def fixture_text(self) -> str:
        if self.text is None:
            lib = Library(self.workdir / "built")
            try:
                build_library(lib)
                _settled(lib.conn)
                records = [r for r in dump_fixture(lib.conn, lib.cfg.library_dir) if r.get("file") not in TOP_FILES]
                self.text = jsonl(records, corpus="inbox/file_fixture_library", made_by=MADE_BY)
            finally:
                lib.close()
        return self.text

    @contextmanager
    def replayed(self) -> Iterator[Library]:
        self.n += 1
        lib = Library(self.workdir / f"replayed/{self.n}")
        try:
            replay_fixture(lib.conn, read_fixture(self.fixture_text()), lib.cfg.library_dir)
            yield lib
        finally:
            lib.close()

    def answer(self, spec: dict[str, Any]) -> dict[str, Any]:
        record = json.loads(json.dumps(spec, ensure_ascii=False, sort_keys=True))
        kw = record["kw"]
        with self.replayed() as lib:
            root = lib.cfg.library_dir
            for path, change in (record["changes"] or {}).items():
                target = root / path
                if change is None:
                    target.unlink()
                else:
                    target.write_bytes(unb64(change))
            before = {t: _rows(lib.conn, t) for t in TABLES}
            files_before = _library(root)
            with mock.patch("caracole.inbox.utc_now_iso", lambda: kw["now"]):
                record["out"] = file_one(lib, kw["name"], unb64(kw["data"]))
            after = {t: _rows(lib.conn, t) for t in TABLES}
            _stamped(before["files"], after["files"], kw["now"])
            files_after = _library(root)
            record["after"] = {"rows": {}, "gone": {},
                               "library": {p: files_after.get(p) for p in sorted(files_before.keys() | files_after.keys())
                                           if files_after.get(p) != files_before.get(p)}}
            for t in TABLES:
                old = {r["id"]: r for r in before[t]}
                ids = {r["id"] for r in after[t]}
                if wrote := [r for r in after[t] if old.get(r["id"]) != r]:
                    record["after"]["rows"][t] = wrote
                if deleted := [i for i in old if i not in ids]:
                    record["after"]["gone"][t] = deleted
        return record

    def records(self) -> list[dict[str, Any]]:
        return [self.answer(spec) for spec in cases()]


def every_file(workdir: Path) -> dict[Path, str]:
    filing = Filing(workdir)
    return {
        NAMES_FILE: jsonl(names_records(), corpus="inbox/names", made_by=MADE_BY),
        MATCH_FILE: jsonl(match_records(), corpus="inbox/match", made_by=MADE_BY),
        FILE_FILE: jsonl(filing.records(), corpus="inbox/file", made_by=MADE_BY),
        FIXTURE_FILE: filing.fixture_text(),
    }


# --- the tests -----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return every_file(tmp_path_factory.mktemp("inbox"))


@pytest.mark.parametrize("path", [NAMES_FILE, MATCH_FILE, FILE_FILE, FIXTURE_FILE], ids=lambda p: p.stem)
def test_the_vector_is_what_inbox_py_does(made, path):
    check(path, made[path])


def _records(made, path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in made[path].splitlines()[1:]]


def test_every_name_of_test_inbox_and_every_way_filing_ends_is_in_the_vectors(made):
    names = {r["args"][0] for r in _records(made, NAMES_FILE) if r["fn"].endswith("parse_download_name")}
    assert set(inbox_test_names()) <= names and "Soda Stereo - De Musica Ligera.gp5" in names
    files = _records(made, FILE_FILE)
    assert {r["out"]["filed"] for r in files} == {"kept", "put_back", "duplicate", "unmatched"}
    assert any(len(r["out"].get("paths", [])) == 2 for r in files)  # two songs' copies put back at once
    assert any("versions" in r["after"]["rows"] for r in files)  # an inbox version made
    matches = _records(made, MATCH_FILE)
    assert {r["out"] is None for r in matches} == {True, False}


def test_no_record_is_filed_by_a_musicxml_header(made):
    # The phone reads a score by its name alone: a record inbox.py files by its header would be no answer of the
    # phone's.
    from caracole.inbox import _MUSICXML
    from caracole.musicxml import header

    for r in _records(made, FILE_FILE):
        ext = Path(r["kw"]["name"]).suffix.lower()
        if ext in _MUSICXML:
            assert header(unb64(r["kw"]["data"]), ext) is None, r["case"]


def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    assert every_file(tmp_path) == made
