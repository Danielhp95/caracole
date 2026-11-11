"""The songbooks' names, entries and writers, for the phone (docs/superpowers/specs/2026-11-03-conformance-corpus.md):
what songbook.py answers, written as vectors under tests/conformance/vectors/songbook/ for the Kotlin port
(core.songbooks.Songbooks) to replay, and checked here against the committed files.

Each record is ``{fn, args, kw, out}``, or ``err`` (the exception's class, ``SongbookError``) with ``words``, its
message, songbook.py's words exactly; ``case`` says what a record shows:

- songbook/writers_names.jsonl: ``caracole.songbook.check_name`` (``out`` the name as kept), ``name_key`` and
  ``_folder_key`` of each name of ``NAMES``: NFC, no Cc or Cf character but a space or a tab, whitespace collapsed,
  80 characters (code points) at most, no leading dot, a letter or a digit in its folder's name;
- songbook/writers_entries.jsonl: ``caracole.songbook.entry_keys`` (``out`` the keys sorted, as Python sorts text),
  ``same_entry`` of two entries, and ``find_entry_song`` over the library of ``fixture`` (``out`` the song's key, or
  null): by an identity key of a cut at " - " alone, the first in sorted order the library has, never by a search;
  asked of that fixture replayed into a fresh database (helpers.corpus.replay_fixture), as Kotlin's Fixtures.load
  replays it;
- songbook/fixtures/writers-library.jsonl: that library, the fixture ``writers-library`` (helpers.corpus.dump_fixture's
  records), a fixture's file where the spec puts them, never a vector of records;
- songbook/writers.jsonl: each writer over the songbooks ``before`` (songbooks.toml made of them in order, each
  ``peer_sync.songbook_value``'s ``{name, songs: [[entry, parts]]}``): ``make_songbook``, ``add_to_songbook``,
  ``remove_from_songbook``, ``move_in_songbook``, ``rename_songbook``, ``delete_songbook`` and ``put_songbook``
  (``args`` as the function takes them after the file, a songbook's songs as songbook_value writes them, null for
  put_songbook's none), ``out`` ``{result, books, units}``: what the writer returned (a songbook as its value, a
  list of entries, a position, or null), the songbooks after in their order, and their units as
  ``peer_sync.library_state`` lists them (``{id: {label, digest}}``, a songbook's document being its value). A
  refusal leaves the songbooks as they were.

Every songbook a writer leaves (each record's ``out.books``) is a unit the computer takes: a take of every one of
them into a computer with no songbooks takes each (``peer_sync.apply_units``, through ``put_songbook``) and reads
them back as they are; and a take, from the songbooks ``before``, of the units the writer changed comes to the same
songbooks, a unit a take left taken by the next one (``test_every_songbook_the_phone_makes_is_taken_by_the_computer``:
a rename to a name of the songbook's own folder is taken in two, as ``apply_units`` takes the new unit before it
drops the old one, whose folder it shares).

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from helpers.corpus import VECTORS, check, dump_fixture, jsonl, plain, read_fixture, replay_fixture

MADE_BY = "tests/test_conformance_songbook.py"
SONGBOOK = VECTORS / "songbook"
NOW = "2026-11-03T12:00:00Z"
LIBRARY_FIXTURE = "writers-library"  # vectors/songbook/fixtures/writers-library.jsonl

# --- names ----------------------------------------------------------------------------------------------------------

NAMES = [
    "Campfire", "campfire", "  Camp \t fire  ", "Camp　fire", "Camp fire", "Camp fire",
    "Camp\x1cfire", "Camp\x85fire", "Camp​fire", "Camp﻿fire", "Camp­fire", "؀Camp",
    "Camp\U000e0001", "‍", "tab\x00name", "new\nline", "Camp\rfire", "Camp\x7ffire", "", "   ", "\t\t",
    ".hidden", "  .hidden", ".", "..", "...", "---", "///", "?*", "<>:|", "\U0001f525", "\U0001f525 Fire",
    "篝火", "宋冬野", "Ⅻ", "²", "٣", "ǅ", "Café", "Café", "Straße", "İstanbul", "a:b", "Fire.", "Fire. ",
    "AC/DC", "Camp/Fire", "Camp-Fire", "Camp: Fire", "Camp - Fire", "a" * 80, "a" * 81, "é" * 80, "é" * 81,
    "é" * 80, "é" * 81, "x" * 79 + "\U0001f525", "x" * 80 + "\U0001f525", "x" * 79 + "\U0001f525" * 2,
    "\U0001f525" * 81, "  " + "a" * 80 + "  ", "a " * 40, "a " * 41, ".It's", '."quoted"', ".a\\b", "It's \"it\"",
    "\n" + "a" * 90, "a" * 90 + "\n", "Dad's \"best\" \\ songs", "ﬁre", "Σίσυφος", "ΣΊΣΥΦΟΣ", "\U0001d509ire",
]


def _answer(call: Callable[[], Any]) -> dict[str, Any]:
    """What a call answered, as a record holds it: ``out``, or ``err`` and ``words`` for a SongbookError."""
    from caracole.songbook import SongbookError

    try:
        return {"out": plain(call())}
    except SongbookError as e:
        return {"err": type(e).__name__, "words": str(e)}


def name_records() -> list[dict]:
    from caracole import songbook

    out = []
    for name in NAMES:
        for fn in ("check_name", "name_key", "_folder_key"):
            out.append({"fn": f"caracole.songbook.{fn}", "args": [name], "kw": {},
                        **_answer(lambda fn=fn, name=name: getattr(songbook, fn)(name))})
    return out


# --- entries --------------------------------------------------------------------------------------------------------

ENTRIES = [
    "Radiohead - Creep", "radiohead - creep", "Earth - Wind - Fire - September", "A - B - C", "Creep", " - Creep",
    "Radiohead - ", "Radiohead -Creep", "Radiohead- Creep", "a  -  b", "A - B", "A - B - ", "- A - B",
    " - A - B", "A -  - B", "A - - B", "Soda Stereo - De Música Ligera (Remastered 2007)",
    "Soda Stereo - De Musica Ligera", "宋冬野 - 斑馬，斑馬", "宋冬野 - 斑马，斑马", "Ⓐ - Ⓑ", "\U0001f600 - \U0001f3b5",
    "Café - Ça va", "Café - Ça va", "AC/DC - T.N.T.", "Ⅻ - 二", "  Oasis   -   Wonderwall  ",
    "Oasis\t-\tWonderwall", "Oasis - Wonderwall - Live", "Oasis - Wonderwall (Live)", "", " - ", "-", "a - b",
]

SAME = [
    ("Soda Stereo - De Musica Ligera", "soda stereo - De Música Ligera (Remastered 2007)"),
    ("宋冬野 - 斑馬，斑馬", "宋冬野 - 斑马，斑马"),
    ("Radiohead - Creep", "Stone Temple Pilots - Creep"),
    ("Earth - Wind - Fire", "Earth - Wind - Fire"),
    ("Earth - Wind - Fire - September", "Earth - Wind - Fire - September"),
    ("A - B - C", "A - B - C"),
    ("A - B - C", "A - B"),
    ("A - B - C", "A - B C"),
    ("Creep", "Creep"),
    ("Creep", "Radiohead - Creep"),
    ("", ""),
    ("Oasis - Wonderwall", "  oasis -  WONDERWALL "),
    ("Oasis - Wonderwall", "Oasis - Wonderwall (Live)"),
    ("Café - Ça va", "Café - Ça va"),
    ("Café - Ça va", "Cafe - Ca va"),
]

# The library find_entry_song reads: songs whose names hold " - ", accents, Chinese, a version suffix.
LIBRARY = [
    ("Radiohead", "Karma Police"), ("Radiohead", "Creep"), ("宋冬野", "斑马，斑马"),
    ("Soda Stereo", "De Música Ligera - Remasterizado 2007"), ("Earth - Wind - Fire", "September"),
    ("A", "B - C"), ("A - B", "C"), ("Oasis", "Wonderwall"),
]

FOUND = [
    "radiohead - karma police", "Radiohead - Karma Police", "宋冬野 - 斑馬，斑馬", "Radiohead - Karma Police Live",
    "ban ma ban ma", "Song Dongye - Ban Ma Ban Ma", "Earth - Wind - Fire - September", "Earth - Wind - Fire",
    "A - B - C", "A - B", "Soda Stereo - De Musica Ligera", "Soda Stereo - De Música Ligera (Remastered 2007)",
    "Nobody - Nothing", "", "Creep", "Oasis - Wonderwall", "Oasis  -  Wonderwall", "oasis - wonderwall (live)",
]


def library_fixture(conn) -> list[dict]:
    """The library find_entry_song's records read, its stamps made ``NOW``."""
    from conftest import add_song

    for artist, title in LIBRARY:
        add_song(conn, artist, title, added_at=NOW)
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (NOW, NOW))
    return dump_fixture(conn)


def entry_records(conn) -> list[dict]:
    """``ENTRIES``, ``SAME`` and ``FOUND``, ``find_entry_song`` asked of ``conn``: the library fixture replayed."""
    from caracole.songbook import entry_keys, find_entry_song, same_entry

    out = []
    for text in ENTRIES:
        out.append({"fn": "caracole.songbook.entry_keys", "args": [text], "kw": {},
                    **_answer(lambda text=text: sorted(entry_keys(text)))})
    for a, b in SAME:
        for x, y in ((a, b), (b, a)):
            out.append({"fn": "caracole.songbook.same_entry", "args": [x, y], "kw": {},
                        **_answer(lambda x=x, y=y: same_entry(x, y))})
    for text in FOUND:
        out.append({"fn": "caracole.songbook.find_entry_song", "fixture": LIBRARY_FIXTURE, "args": [text], "kw": {},
                    **_answer(lambda text=text: find_entry_song(conn, text))})
    return out


# --- the writers ----------------------------------------------------------------------------------------------------

# A songbook as a record holds it: its name, and its songs, [entry, parts] each (peer_sync.songbook_value).
CREEP = ["Radiohead - Creep", {"key": "G", "capo": 2}]
WONDERWALL = ["Oasis - Wonderwall", {}]
SODA = ["Soda Stereo - De Música Ligera", {"key": "G", "mode": "dorian", "capo": 0}]
HOTEL = ["Eagles - Hotel California", {"instrument": "ukulele"}]
KARMA = ["Radiohead - Karma Police", {}]
ZH = ["宋冬野 - 斑马，斑马", {"key": "C"}]
CAMPFIRE = {"name": "Campfire", "songs": [CREEP, WONDERWALL, SODA]}
WEDDINGS = {"name": "Weddings", "songs": [HOTEL]}
ROAD = {"name": "Road trip", "songs": [ZH, KARMA]}
SLASHED = {"name": "Camp/Fire", "songs": [WONDERWALL]}
THREE = [CAMPFIRE, WEDDINGS, ROAD]
TWICE = {"name": "Twice", "songs": [["A - B", {}], ["C - D", {"capo": 1}], ["a - b", {"key": "D"}]]}

WRITERS: list[tuple[str, list[dict], str, list[Any]]] = [
    # make_songbook
    ("make: after the others, a song named twice once where it is first named", THREE, "make_songbook",
     ["Picnic", ["Radiohead - Creep", "radiohead - creep", "Oasis -  Wonderwall",
                 "Soda Stereo - De Musica Ligera (Remastered 2007)", "Oasis - Wonderwall", "  Muse  -  Hysteria "]]),
    ("make: the first songbook", [], "make_songbook", ["Campfire", ["Radiohead - Creep"]]),
    ("make: with no songs", THREE, "make_songbook", ["Empty", []]),
    ("make: the name trimmed and collapsed", THREE, "make_songbook", ["  Late \t night   songs ", ["A - B"]]),
    ("make: a name taken, in any case", THREE, "make_songbook", ["CAMPFIRE", ["A - B"]]),
    ("make: a name taken, its spaces aside", THREE, "make_songbook", ["  Road   trip ", ["A - B"]]),
    ("make: a name taken, in another normal form", [{"name": "Café", "songs": []}], "make_songbook",
     ["Café", []]),
    ("make: a name whose folder another songbook's is", [SLASHED], "make_songbook", ["Camp-Fire", []]),
    ("make: a name whose folder another's is, in another case", [SLASHED], "make_songbook", ["CAMP-FIRE", []]),
    ("make: a colon's folder is a dash's", [{"name": "Camp - Fire", "songs": []}], "make_songbook",
     ["Camp: Fire", []]),
    ("make: the first songbook that clashes is named", [WEDDINGS, SLASHED, {"name": "camp-fire x", "songs": []}],
     "make_songbook", ["camp-fire", []]),
    ("make: a name taken, its folder too: the name is said",
     [{"name": "Camp-Fire", "songs": []}, {"name": "Zed", "songs": []}], "make_songbook", ["camp-fire", []]),
    ("make: a song that isn't Artist - Title", THREE, "make_songbook", ["Picnic", ["Radiohead - Creep", "Creep"]]),
    ("make: the songbook a bad song is in, quoted", THREE, "make_songbook",
     ["Dad's \"best\" \\ songs", ["Radiohead -Creep"]]),
    ("make: a bad song before a name taken", THREE, "make_songbook", ["Campfire", [" - Creep"]]),
    ("make: a bad name before a bad song", THREE, "make_songbook", ["", ["Creep"]]),
    ("make: a name with a line break", THREE, "make_songbook", ["Camp\nfire", []]),
    ("make: a name too long", THREE, "make_songbook", ["x" * 79 + "\U0001f525" * 2, []]),
    ("make: a name of 80 characters, one beyond the BMP", THREE, "make_songbook", ["x" * 79 + "\U0001f525", []]),
    ("make: a hidden name", THREE, "make_songbook", [".Campfire", []]),
    ("make: a name with no letter or digit", THREE, "make_songbook", ["\U0001f525", []]),
    ("make: Chinese", THREE, "make_songbook", ["篝火", ["宋冬野 - 斑馬，斑馬", "宋冬野 - 斑马，斑马"]]),
    # add_to_songbook
    ("add: the songs it hasn't got, in order, its own kept with their settings", THREE, "add_to_songbook",
     ["Campfire", ["Oasis - Wonderwall", "Radiohead - Karma Police", "radiohead - karma police",
                   "Muse - Hysteria", "soda stereo - de musica ligera"]]),
    ("add: nothing new", THREE, "add_to_songbook", ["Campfire", ["radiohead - creep", "Oasis - Wonderwall"]]),
    ("add: found in any case, its spaces aside", THREE, "add_to_songbook", ["  ROAD   trip ", ["A - B"]]),
    ("add: a name's spaces are no space it lacks", THREE, "add_to_songbook", ["CAMP fire", ["A - B"]]),
    ("add: found in any case, written as it is", THREE, "add_to_songbook", ["campfire", ["A - B"]]),
    ("add: a song's spaces collapsed", THREE, "add_to_songbook", ["Weddings", ["Radiohead  -  Karma   Police"]]),
    ("add: to a songbook that isn't there", THREE, "add_to_songbook", ["  Pic\tnic ", ["A - B"]]),
    ("add: a bad song before a songbook that isn't there", THREE, "add_to_songbook", ["Picnic", ["Creep"]]),
    ("add: to no songbooks", [], "add_to_songbook", ["Campfire", ["A - B"]]),
    ("add: to a songbook of no songs", [{"name": "Empty", "songs": []}], "add_to_songbook",
     ["Empty", ["A - B", "C - D"]]),
    ("add: Chinese, Traditional for Simplified", THREE, "add_to_songbook", ["Road trip", ["宋冬野 - 斑馬，斑馬"]]),
    # remove_from_songbook
    ("remove: as it wrote them", THREE, "remove_from_songbook", ["Campfire", ["oasis - wonderwall"]]),
    ("remove: a song with its setting", THREE, "remove_from_songbook",
     ["Campfire", ["Soda Stereo - De Musica Ligera (Remastered 2007)"]]),
    ("remove: every time it names them, in order", [TWICE], "remove_from_songbook", ["twice", ["A - B"]]),
    ("remove: nothing it has", THREE, "remove_from_songbook", ["Campfire", ["Muse - Hysteria", "Creep", ""]]),
    ("remove: a song's spaces aside", THREE, "remove_from_songbook", ["Campfire", ["Oasis  -  Wonderwall"]]),
    ("remove: several", THREE, "remove_from_songbook",
     ["Campfire", ["Radiohead - Creep", "Soda Stereo - De Música Ligera"]]),
    ("remove: the last song", THREE, "remove_from_songbook", ["Weddings", ["Eagles - Hotel California"]]),
    ("remove: from a songbook that isn't there", THREE, "remove_from_songbook", ["Picnic", ["Creep"]]),
    # move_in_songbook
    ("move: to the first place", THREE, "move_in_songbook", ["Campfire", "oasis - wonderwall", 1]),
    ("move: past the end is last", THREE, "move_in_songbook", ["Campfire", "Radiohead - Creep", 99]),
    ("move: to the last place", THREE, "move_in_songbook", ["Campfire", "Radiohead - Creep", 3]),
    ("move: to its own place", THREE, "move_in_songbook", ["Campfire", "Oasis - Wonderwall", 2]),
    ("move: backwards, its setting with it", THREE, "move_in_songbook",
     ["campfire", "Soda Stereo - De Musica Ligera", 1]),
    ("move: the first a songbook names twice", [TWICE], "move_in_songbook", ["Twice", "a - b", 3]),
    ("move: the only song", THREE, "move_in_songbook", ["Weddings", "Eagles - Hotel California", 5]),
    ("move: a song the songbook hasn't got, named as written", THREE, "move_in_songbook",
     ["campfire", "Muse  -  Hysteria", 1]),
    ("move: in a songbook of no songs", [{"name": "Empty", "songs": []}], "move_in_songbook", ["Empty", "A - B", 1]),
    ("move: to position 0", THREE, "move_in_songbook", ["Campfire", "Radiohead - Creep", 0]),
    ("move: a position below 0, before a songbook that isn't there", THREE, "move_in_songbook",
     ["Picnic", "Radiohead - Creep", -3]),
    ("move: in a songbook that isn't there", THREE, "move_in_songbook", ["Picnic", "Radiohead - Creep", 1]),
    # rename_songbook
    ("rename: in its place", THREE, "rename_songbook", ["Weddings", "Fireside"]),
    ("rename: in another case", THREE, "rename_songbook", ["campfire", "CAMPFIRE"]),
    ("rename: to its own name", THREE, "rename_songbook", ["Campfire", "Campfire"]),
    ("rename: the new name trimmed", THREE, "rename_songbook", ["Road trip", "  Long   road  "]),
    ("rename: to a name another has", THREE, "rename_songbook", ["Campfire", "weddings"]),
    ("rename: to its own folder", [WEDDINGS, SLASHED], "rename_songbook", ["camp/fire", "Camp-Fire"]),
    ("rename: to a folder another's is", [WEDDINGS, SLASHED, ROAD], "rename_songbook", ["Road trip", "camp-fire"]),
    ("rename: to a bad name", THREE, "rename_songbook", ["Campfire", "."]),
    ("rename: a bad name before a songbook that isn't there", THREE, "rename_songbook", ["Picnic", ""]),
    ("rename: a songbook that isn't there", THREE, "rename_songbook", ["Picnic", "Lunch"]),
    ("rename: Chinese", THREE, "rename_songbook", ["Road trip", "篝火"]),
    # delete_songbook
    ("delete: the others keep their places", THREE, "delete_songbook", ["weddings"]),
    ("delete: the last songbook", [CAMPFIRE], "delete_songbook", ["Campfire"]),
    ("delete: one with settings returns them", THREE, "delete_songbook", ["  CAMPFIRE "]),
    ("delete: a songbook that isn't there", THREE, "delete_songbook", ["Picnic"]),
    # put_songbook, a sync's take
    ("put: a new one after the others", THREE, "put_songbook", ["Picnic", [KARMA, ZH]]),
    ("put: in its place, found in any case, written under the name given", THREE, "put_songbook",
     ["WEDDINGS", [WONDERWALL, HOTEL]]),
    ("put: the same songs again", THREE, "put_songbook", ["Campfire", [CREEP, WONDERWALL, SODA]]),
    ("put: none takes it out", THREE, "put_songbook", ["campfire", None]),
    ("put: none of one that isn't there", THREE, "put_songbook", ["Picnic", None]),
    ("put: the name trimmed", THREE, "put_songbook", ["  Late   night ", [KARMA]]),
    ("put: a name whose folder another's is", [SLASHED], "put_songbook", ["Camp-Fire", [KARMA]]),
    ("put: a bad name", THREE, "put_songbook", ["Camp\nfire", [KARMA]]),
    ("put: a bad name, even for none", THREE, "put_songbook", ["", None]),
    ("put: a song twice, as a hand-edited file may hold it", THREE, "put_songbook",
     ["Twice", [["A - B", {}], ["a - b", {"capo": 3}]]]),
    ("put: no songs", THREE, "put_songbook", ["Road trip", []]),
]


def _songs(songs: Sequence[Sequence[Any]]):
    """A record's songs, ``[[entry, parts]]``, as songbook.py's SongbookSongs."""
    from caracole.songbook import SongbookSong, check_setting

    return [SongbookSong(text, check_setting(**dict(parts)) or None) for text, parts in songs]


def _books(path: Path) -> list[dict[str, Any]]:
    from caracole import peer_sync as sync
    from caracole.songbook import load_songbooks

    return [sync.songbook_value(b) for b in load_songbooks(path)]


def _start(path: Path, before: Sequence[Mapping[str, Any]]) -> None:
    """songbooks.toml holding ``before``, in order, as a sync puts each songbook."""
    from caracole.songbook import put_songbook

    path.unlink(missing_ok=True)
    for book in before:
        put_songbook(path, book["name"], _songs(book["songs"]))
    assert _books(path) == [dict(b) for b in before] if before else not path.exists()


def _result(fn: str, result: Any) -> Any:
    from caracole import peer_sync as sync

    if fn in ("make_songbook", "rename_songbook", "delete_songbook"):
        return sync.songbook_value(result)
    return result


def writer_records(phone) -> list[dict]:
    """Each case of ``WRITERS`` over ``phone`` (a helpers.peer_libraries.Library with no song)."""
    from caracole import peer_sync as sync
    from caracole import songbook
    from caracole.overrides import Overrides
    from caracole.songbook import SongbookError, songbooks_file

    path = songbooks_file(phone.cfg.library_dir)
    out = []
    for case, before, fn, args in WRITERS:
        _start(path, before)
        start = path.read_bytes() if path.exists() else None
        call = list(args)
        if fn == "put_songbook":
            call[1] = None if args[1] is None else _songs(args[1])
        record = {"fn": f"caracole.songbook.{fn}", "case": case, "before": before, "args": args, "kw": {}}
        try:
            result = getattr(songbook, fn)(path, *call)
        except SongbookError as e:
            assert (path.read_bytes() if path.exists() else None) == start, f"{case}: a refusal wrote the file"
            record.update(err=type(e).__name__, words=str(e))
            out.append(record)
            continue
        books = phone.books()
        units = {unit_id: {"label": unit.label, "digest": unit.digest}
                 for unit_id, unit in sync.library_state(phone.conn, Overrides(), books).items()
                 if unit_id.startswith("songbook/")}
        record["out"] = {"result": _result(fn, result), "books": [sync.songbook_value(b) for b in books],
                         "units": units}
        out.append(record)
    return out


# --- the corpus -----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> dict[str, str]:
    """Every vector's text, made once: {file name under vectors/songbook/: its text}."""
    from caracole import db
    from conftest import migrated_database
    from helpers.peer_libraries import Library

    root = tmp_path_factory.mktemp("songbook-corpus")
    built, replayed = root / "built.sqlite", root / "replayed.sqlite"
    for state in (built, replayed):
        state.write_bytes(migrated_database())
    library = f"fixtures/{LIBRARY_FIXTURE}.jsonl"
    phone = Library(root / "phone")
    phone.cfg.library_dir.mkdir(parents=True, exist_ok=True)
    try:
        with closing(db.connect(built)) as conn:
            fixture = jsonl(library_fixture(conn), corpus=f"songbook/fixtures/{LIBRARY_FIXTURE}", made_by=MADE_BY)
        with closing(db.connect(replayed)) as conn:
            replay_fixture(conn, read_fixture(fixture))
            entries = jsonl(entry_records(conn), corpus="songbook/writers_entries", made_by=MADE_BY)
        texts = {
            "writers_names.jsonl": jsonl(name_records(), corpus="songbook/writers_names", made_by=MADE_BY),
            library: fixture,
            "writers_entries.jsonl": entries,
            "writers.jsonl": jsonl(writer_records(phone), corpus="songbook/writers", made_by=MADE_BY),
        }
    finally:
        phone.close()
    return texts


VECTOR_FILES = ("writers_names.jsonl", f"fixtures/{LIBRARY_FIXTURE}.jsonl", "writers_entries.jsonl", "writers.jsonl")


@pytest.mark.parametrize("name", VECTOR_FILES)
def test_a_vector_is_what_songbook_py_answers(corpus, name):
    check(SONGBOOK / name, corpus[name])


def _records(corpus, name: str) -> list[dict]:
    return [json.loads(line) for line in corpus[name].split("\n")[1:] if line]  # never splitlines: U+2028 is text


def test_every_rule_of_a_name_is_in_the_vectors(corpus):
    words = {r["words"].split(":")[0] for r in _records(corpus, "writers_names.jsonl") if "words" in r}
    assert words == {"A songbook's name can't hold a line break or a control character", "A songbook needs a name",
                     "A songbook's name is 80 characters at most",
                     "A songbook's name can't start with a dot (its folder would hide)",
                     "A songbook's name needs a letter or a digit"}


def test_every_writer_answers_and_refuses_in_the_vectors(corpus):
    records = _records(corpus, "writers.jsonl")
    for fn in ("make_songbook", "add_to_songbook", "remove_from_songbook", "move_in_songbook", "rename_songbook",
               "delete_songbook", "put_songbook"):
        mine = [r for r in records if r["fn"] == f"caracole.songbook.{fn}"]
        assert any("out" in r for r in mine) and any("err" in r for r in mine), fn
    refusals = " ".join(r["words"] for r in records if "words" in r)
    for words in ("is there already", "would share the folder", "No songbook named", "isn't in the songbook",
                  "A position counts from 1", 'expected "Artist - Title"', "A songbook needs a name"):
        assert words in refusals, words


class _Phone:
    """A peer_sync.UnitSource answering the phone's songbook units: each one's document, its value."""

    def __init__(self, docs: Mapping[str, Any]):
        self.docs = docs

    def unit(self, unit_id: str):
        doc = self.docs.get(unit_id)
        return None if doc is None else json.loads(json.dumps(doc, ensure_ascii=False))

    def file(self, key: str, name: str, sha256: str) -> bytes:
        raise AssertionError("a songbook unit names no file")


def _take(computer, docs: Mapping[str, Any], wanted: Sequence[str]):
    from caracole import peer_sync as sync

    pairs = [(unit_id, None if docs.get(unit_id) is None else
              sync.digest_of(sync.value_of_document(unit_id, docs[unit_id]))) for unit_id in wanted]
    return sync.apply_units(computer.conn, computer.cfg, _Phone(docs), pairs, NOW)


def _by_key(books: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from caracole.songbook import name_key

    return {f"songbook/{name_key(b['name'])}": dict(b) for b in books}


def test_every_songbook_the_phone_makes_is_taken_by_the_computer(corpus, tmp_path):
    from helpers.peer_libraries import Library

    from caracole.songbook import songbooks_file

    computer = Library(tmp_path / "computer")
    computer.cfg.library_dir.mkdir(parents=True, exist_ok=True)
    path = songbooks_file(computer.cfg.library_dir)
    in_two = []
    try:
        for r in _records(corpus, "writers.jsonl"):
            if "out" not in r:
                continue
            after = _by_key(r["out"]["books"])
            assert set(after) == set(r["out"]["units"]), r["case"]
            # Every songbook the phone holds then, into a computer with none: each taken, each read back as it is.
            path.unlink(missing_ok=True)
            done = _take(computer, after, sorted(after))
            assert done.left == [] and sorted(done.taken) == sorted(after), (r["case"], done.left)
            assert _by_key(_books(path)) == after, r["case"]
            # The units the writer changed, from the songbooks before: the next take takes what one left.
            _start(path, r["before"])
            before = _by_key(r["before"])
            changed = sorted(u for u in set(before) | set(after) if before.get(u) != after.get(u))
            done = _take(computer, after, changed)
            if done.left:
                assert all("would share the folder" in why for _, why in done.left), (r["case"], done.left)
                in_two.append(r["case"])
                done = _take(computer, after, [u for u, _ in done.left])
            assert done.left == [], (r["case"], done.left)
            assert _by_key(_books(path)) == after, r["case"]
    finally:
        computer.close()
    # apply_units takes songbook/camp-fire before it drops songbook/camp/fire ("-" sorts before "/"), whose folder the
    # new name shares: the next sync takes it.
    assert in_two == ["rename: to its own folder"]
