"""The library's writers, for the phone: what library.py, versions.py, songs.py, inbox.py and provider_pass.py do to a
library (its rows, its files, its sync units), written for the Kotlin lane library-writes (core.library's ``Kept``,
``Versions``, ``Numbering`` and ``Passes``) to agree with: every site's pass writes through these, and a kept file's
SHA-256, a version's raw and a song's columns are in its sync unit, so they must be Python's to the byte.

**Fixtures** (``vectors/library/writes_fixture_<name>.jsonl``, helpers.corpus's format): a library built with
caracole's own writers (wanted.txt lines synced into songs, ``versions.upsert_version``, ``library.keep_file``,
``versions.mark_gone`` and ``set_picks``), every stamp caracole writes as now made ``NOW``, then dumped
(``dump_fixture``) with its files, wanted.txt left out. Files put in a song's folder by hand are in it too, as files no
row names. ``library``: a song with a sheet, a text tab, a Guitar Pro file and versions live, gone and picked; a song
of other scripts with nothing kept; two songs whose names make one folder; a song with harmonica, game-music and score
files, kept and put there by hand; a song with no folder.

**Vectors**: library/writes.jsonl, a header, then a record a line, ``{fn, case, fixture, kw, changes, out | err,
message, after}``:

- ``fixture`` the fixture's name (null: none, for ``each_song``), replayed into a fresh database and library folder
  (``replay_fixture``); ``changes`` what is done to the library folder then, before the call (``{path: null}``
  deletes the file, ``{path: {"base64"}}`` writes one), or null;
- ``kw`` the call's arguments: ``song`` a song's identity key (its record is found by it), ``data`` a file's bytes
  (``{"base64"}``), ``raw`` a version's raw as the JSON text it is given in (``json.loads``'s, so its members keep
  their order), ``path`` a path under the library; the rest by Python's names;
- ``out`` what the function returned (a song a key, a version or a kept file a row, an exception a record's ``err``
  instead: its class's name, and ``message`` its words);
- ``after``, what the call changed: ``rows``, by table (``songs``, ``versions``, ``files``), each row it wrote (new,
  or other than before) whole, as ``dump_fixture`` reads them, in rowid order, and ``gone``, by table, the ids of the
  rows it deleted (every other row is as before the call); ``library``, each regular file of the library folder it
  wrote (new, or other bytes than before) by path with its SHA-256, or null for one it deleted (every other file is
  as before); ``units``, ``peer_sync.library_state``'s digests then, by unit id (no overrides, no songbooks: the
  fixture has none).

Stamps: ``now`` in ``kw`` is the time a writer is given, or the clock's time it reads (songs.utc_now_iso, made
``now``). library.keep_file stamps ``created_at`` with SQLite's clock, which no record can fix: a row it wrote is
checked to hold a time of that form now, then recorded as ``kw.now``, which the phone's ``Kept.keepFile`` is given.

``each_song``'s records have no fixture: ``kw`` ``{songs, turns, stop_on}``, each song by its name, each song's turn
a word (``ok``: it answers ``"<name> done"``; ``error``, ``robots``, ``pages``, ``blocked``, ``unavailable``: it
raises ``ProviderError``, ``RobotsClosed``, gtptabs_fetch's ``PagesNotFiles``, ``ProviderBlocked`` or
``ProviderUnavailable`` with provider ``site``, status 500, URL ``https://s/<name>`` and the message ``busy``;
``budget``: ``BudgetExhausted("site")``), ``stop_on`` the words whose errors end the pass; ``out`` ``{events, raised,
stats}``: what happened in order (``read <name>`` as the pass takes a song, ``turn <name>``, ``got <name> <outcome>``
as the caller gets one, ``error <name> <class>`` as ``on_error`` hears one), the class of what the pass raised (null:
none) and the stats ``{tried, errors, budget_exhausted, failures: [[name, class, message]]}``.

The answers are the same on every run (``test_the_vectors_are_the_same_on_another_run``): no set's order goes into
them. Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from helpers.corpus import VECTORS, check, dump_fixture, jsonl, plain, read_fixture, replay_fixture
from helpers.peer_libraries import NOW, Library

MADE_BY = "tests/test_conformance_library_writes.py"
LIBRARY = VECTORS / "library"
WRITES = LIBRARY / "writes.jsonl"
TOP_FILES = ("wanted.txt", "overrides.toml", "songbooks.toml")  # the computer's: the phone has none
TABLES = ("songs", "versions", "files")
LATER = "2026-11-03T12:00:00Z"  # a call's now: after every stamp of the fixtures
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

LONG = "Concierto de Aranjuez para guitarra y orquesta, segundo movimiento: Adagio, arreglo para guitarra sola de Narciso"
SONGS = {  # the fixture's songs, by the name the cases give each
    "creep": ("Radiohead", "Creep"), "zebra": ("宋冬野", "斑马，斑马"), "one": ("Joaquín Rodrigo", LONG + ", part one"),
    "two": ("Joaquín Rodrigo", LONG + ", part two"), "song2": ("Blur", "Song 2"), "wall": ("Oasis", "Wonderwall"),
}


def key(name: str) -> str:
    """The identity key of the fixture's song ``name``."""
    from caracole.normalize import identity_key

    return identity_key(*SONGS[name])


def b64(data: bytes) -> dict[str, str]:
    return {"base64": base64.b64encode(data).decode("ascii")}


def unb64(value: dict[str, str]) -> bytes:
    return base64.b64decode(value["base64"])


# --- the fixtures ---------------------------------------------------------------------------------------------------


def _version(lib: Library, song: str, provider: str, tab: str, slot: str, kind: str, *, rating: float = 4.5,
             votes: int = 10, raw: dict | None = None, label: str | None = None) -> int:
    from caracole.songs import find_song
    from caracole.versions import upsert_version

    song = find_song(lib.conn, key(song))
    return upsert_version(lib.conn, provider=provider, tab_id=tab, song_id=song.id, slot=slot, kind=kind,
                          rating=rating, votes=votes, version=1, label=label, url=f"https://{provider}/{tab}",
                          raw=raw if raw is not None else {"x": 1}, now=NOW)


def _keep(lib: Library, song: str, version_id: int, name: str, data: bytes, rank: int = 1) -> None:
    from caracole.library import keep_file
    from caracole.songs import find_song

    assert keep_file(lib.conn, lib.cfg.library_dir, song=find_song(lib.conn, key(song)), version_id=version_id,
                     name=name, data=data, rank=rank)


def _by_hand(lib: Library, song: str, name: str, data: bytes) -> None:
    """A file put in the song's folder by hand: no row names it."""
    from caracole.library import song_dir
    from caracole.songs import find_song

    path = song_dir(lib.cfg.library_dir, find_song(lib.conn, key(song))) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build_library(lib: Library) -> None:
    from caracole.library import song_dir
    from caracole.songs import find_song
    from caracole.versions import mark_gone, set_picks

    for artist, title in SONGS.values():
        lib.song(artist, title, sheet=None, lyrics=None)
    one, two = (find_song(lib.conn, key(n)) for n in ("one", "two"))
    assert one.key != two.key and song_dir(lib.cfg.library_dir, one) == song_dir(lib.cfg.library_dir, two)
    # Radiohead - Creep: a sheet, a text tab, a Guitar Pro file, a version gone and a pick, a raw of its own order.
    sheet = _version(lib, "creep", "ug", "101", "sheet", "chords", raw={"z": 1, "a": [1.5, None, "é"], "m": {"b": 2}})
    _keep(lib, "creep", sheet, "sheet.txt", b"[Am]Creep")
    tab = _version(lib, "creep", "ug", "202", "guitar", "tabs", rating=3.0, votes=2)
    _keep(lib, "creep", tab, "tab.txt", b"e|--0--|")
    gp = _version(lib, "creep", "gtptabs", "55", "guitar", "guitar-pro", rating=0, votes=0, raw={})
    _keep(lib, "creep", gp, "guitar-1.gp5", b"FICHIER GUITAR PRO v5.00")
    gone = _version(lib, "creep", "lacuerda", "radiohead/creep", "sheet", "acordes", rating=0, votes=0)
    mark_gone(lib.conn, gone)
    other = _version(lib, "creep", "ug", "303", "sheet", "chords", rating=4.9, votes=99, label="Acoustic")
    set_picks(lib.conn, find_song(lib.conn, key("creep")).id, ("chords",), [other, sheet])
    _by_hand(lib, "creep", "guitar-3.GP5", b"by hand")
    _by_hand(lib, "creep", "notes.txt", b"mine")
    # Two songs of one folder: the first keeps a sheet and a Guitar Pro file there, the second a Guitar Pro file.
    first = _version(lib, "one", "ug", "7", "sheet", "chords")
    _keep(lib, "one", first, "sheet.txt", b"[Em]Adagio")
    _keep(lib, "one", first, "guitar-1.gp5", b"GP of part one")
    second = _version(lib, "two", "gtptabs", "8", "guitar", "guitar-pro", rating=0, votes=0)
    _keep(lib, "two", second, "guitar-3.gp5", b"GP of part two")
    # Blur - Song 2: an auto sheet, a harmonica tab, a game tab, a score kept; their kin put there by hand.
    auto = _version(lib, "song2", "autochords", "auto", "sheet", "auto", rating=0, votes=0)
    _keep(lib, "song2", auto, "sheet (auto).txt", b"[E]Woo-hoo")
    harp = _version(lib, "song2", "harptabs", "1234", "guitar", "harmonica", rating=0, votes=0)
    _keep(lib, "song2", harp, "harmonica-1.txt", b"4 -4 5")
    game = _version(lib, "song2", "gametabs", "zelda/main-theme", "guitar", "gametab", rating=0, votes=0)
    _keep(lib, "song2", game, "gametab-1.txt", b"e|--3--|")
    score = _version(lib, "song2", "inbox", "score", "guitar", "score", rating=0, votes=0)
    _keep(lib, "song2", score, "score-1.pdf", b"%PDF-1.4 score")
    for name in ("harmonica-2.html", "harmonica-4.txt", "Harmonica-3.txt", "gametab-3.txt", "gametab-2.TXT",
                 "score-2.PDF", "score-3.mscz", "score-x.pdf", "guitar-\u0661.gp5", "GUITAR-02.gp5", "guitar-4",
                 "guitar-5.tar.gz"):
        _by_hand(lib, "song2", name, name.encode("utf-8"))


FIXTURES: dict[str, Callable[[Library], None]] = {"library": build_library}


def _settled(conn) -> None:
    """Every stamp caracole writes as now, made ``NOW``: a fixture is the same on every run."""
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (NOW, NOW))
    conn.execute("UPDATE files SET created_at = ?", (NOW,))


def fixture_path(name: str) -> Path:
    return LIBRARY / f"writes_fixture_{name}.jsonl"


# --- a call over a fixture ------------------------------------------------------------------------------------------


def rec(fn: str, case: str, kw: dict[str, Any], *, fixture: str | None = "library",
        changes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"fn": fn, "case": case, "fixture": fixture, "kw": kw, "changes": changes}


def _song(conn, key: str):
    from caracole.songs import find_song

    song = find_song(conn, key)
    assert song is not None, key
    return song


def _rows(conn, table: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, tuple(row))) for row in cursor.fetchall()]


def _library(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def _units(conn) -> dict[str, str]:
    from caracole import peer_sync
    from caracole.overrides import Overrides

    return {unit_id: unit.digest for unit_id, unit in peer_sync.library_state(conn, Overrides(), []).items()}


def _version_out(v) -> dict[str, Any] | None:
    return None if v is None else plain(v)


CALLS: dict[str, Callable[[Library, dict[str, Any]], Any]] = {}


def calls(fn: str):
    def register(f):
        CALLS[fn] = f
        return f
    return register


@calls("caracole.library.keep_file")
def _keep_file(lib, kw):
    from caracole.library import keep_file

    return keep_file(lib.conn, lib.cfg.library_dir, song=_song(lib.conn, kw["song"]), version_id=kw["version_id"],
                     name=kw["name"], data=unb64(kw["data"]), rank=kw["rank"])


@calls("caracole.library.kept_already")
def _kept_already(lib, kw):
    from caracole.library import kept_already

    return kept_already(lib.conn, lib.cfg.library_dir, song=_song(lib.conn, kw["song"]), version_id=kw["version_id"],
                        name=kw["name"], data=unb64(kw["data"]))


@calls("caracole.library.kept_files")
def _kept_files(lib, kw):
    from caracole.library import kept_files

    return kept_files(lib.conn, _song(lib.conn, kw["song"]).id)


@calls("caracole.library.keeper_of")
def _keeper_of(lib, kw):
    from caracole.library import keeper_of

    other = keeper_of(lib.conn, lib.cfg.library_dir, _song(lib.conn, kw["song"]), kw["name"])
    return None if other is None else other.key


@calls("caracole.library.holds")
def _holds(lib, kw):
    from caracole.library import holds

    return holds(lib.cfg.library_dir / kw["path"], kw["sha256"], kw["size"])


@calls("caracole.library.drop_file")
def _drop_file(lib, kw):
    from caracole.library import drop_file

    return drop_file(lib.conn, lib.cfg.library_dir, song=_song(lib.conn, kw["song"]), name=kw["name"])


@calls("caracole.library.write_atomic")
def _write_atomic(lib, kw):
    from caracole.library import write_atomic

    return write_atomic(lib.cfg.library_dir / kw["path"], unb64(kw["data"]))


@calls("caracole.versions.upsert_version")
def _upsert_version(lib, kw):
    from caracole.versions import upsert_version

    return upsert_version(lib.conn, provider=kw["provider"], tab_id=kw["tab_id"],
                          song_id=_song(lib.conn, kw["song"]).id, slot=kw["slot"], kind=kw["kind"],
                          rating=kw["rating"], votes=kw["votes"], version=kw["version"], label=kw["label"],
                          url=kw["url"], raw=json.loads(kw["raw"]), now=kw["now"])


@calls("caracole.versions.song_versions")
def _song_versions(lib, kw):
    from caracole.versions import song_versions

    return [_version_out(v) for v in song_versions(lib.conn, _song(lib.conn, kw["song"]).id, slot=kw["slot"],
                                                   kinds=kw["kinds"], include_gone=kw["include_gone"])]


@calls("caracole.versions.get_version")
def _get_version(lib, kw):
    from caracole.versions import get_version

    return _version_out(get_version(lib.conn, kw["version_id"]))


@calls("caracole.versions.set_raw")
def _set_raw(lib, kw):
    from caracole.versions import set_raw

    return set_raw(lib.conn, kw["version_id"], json.loads(kw["raw"]))


@calls("caracole.versions.set_coverage")
def _set_coverage(lib, kw):
    from caracole.versions import set_coverage

    return set_coverage(lib.conn, kw["version_id"], kw["value"])


@calls("caracole.versions.mark_gone")
def _mark_gone(lib, kw):
    from caracole.versions import mark_gone

    return mark_gone(lib.conn, kw["version_id"])


@calls("caracole.versions.mark_stale")
def _mark_stale(lib, kw):
    from caracole.versions import mark_stale

    return mark_stale(lib.conn, _song(lib.conn, kw["song"]).id, kw["provider"])


@calls("caracole.versions.set_picks")
def _set_picks(lib, kw):
    from caracole.versions import set_picks

    return set_picks(lib.conn, _song(lib.conn, kw["song"]).id, kw["kinds"], kw["version_ids"])


@calls("caracole.versions.picks")
def _picks(lib, kw):
    from caracole.versions import picks

    return [_version_out(v) for v in picks(lib.conn, _song(lib.conn, kw["song"]).id, kw["kinds"])]


@calls("caracole.songs.update_song")
def _update_song(lib, kw):
    from caracole import songs

    with mock.patch.object(songs, "utc_now_iso", lambda: kw["now"]):
        return songs.update_song(lib.conn, _song(lib.conn, kw["song"]).id, **kw["fields"])


@calls("caracole.songs.refresh_status")
def _refresh_status(lib, kw):
    from caracole import songs

    with mock.patch.object(songs, "utc_now_iso", lambda: kw["now"]):
        return songs.refresh_status(lib.conn, _song(lib.conn, kw["song"]).id, ignored=kw["ignored"])


def _numbering(name: str):
    def number(lib, kw):
        from caracole import inbox

        song = _song(lib.conn, kw["song"])
        if name == "score_number":
            return inbox.score_number(lib.conn, lib.cfg.library_dir, song, kw["ext"])
        return getattr(inbox, name)(lib.conn, lib.cfg.library_dir, song)
    return number


for _name in ("guitar_number", "harmonica_number", "gametab_number", "score_number"):
    CALLS[f"caracole.inbox.{_name}"] = _numbering(_name)


# --- provider_pass.each_song ----------------------------------------------------------------------------------------


class _Named:
    """A song as each_song reads one: its display alone."""

    def __init__(self, name: str):
        self.display = name


def _raised(word: str, name: str) -> Exception:
    from caracole import http
    from caracole.gtptabs_fetch import PagesNotFiles

    kinds = {"error": http.ProviderError, "robots": http.RobotsClosed, "pages": PagesNotFiles,
             "blocked": http.ProviderBlocked, "unavailable": http.ProviderUnavailable}
    if word == "budget":
        return http.BudgetExhausted("site")
    return kinds[word]("site", f"https://s/{name}", 500, "busy")


def each_song_answer(kw: dict[str, Any]) -> dict[str, Any]:
    from caracole.gtptabs_fetch import PagesNotFiles
    from caracole.http import ProviderError, RobotsClosed
    from caracole.provider_pass import PassStats, each_song

    events: list[str] = []
    stop = {"error": ProviderError, "robots": RobotsClosed, "pages": PagesNotFiles}

    def songs() -> Iterator[_Named]:
        for name in kw["songs"]:
            events.append(f"read {name}")
            yield _Named(name)

    def turn(song: _Named) -> str:
        events.append(f"turn {song.display}")
        word = kw["turns"].get(song.display, "ok")
        if word != "ok":
            raise _raised(word, song.display)
        return f"{song.display} done"

    def heard(song: _Named, e: Exception) -> None:
        events.append(f"error {song.display} {type(e).__name__}")

    stats = PassStats()
    raised = None
    try:
        for song, outcome in each_song(songs(), stats, turn, site="site", on_error=heard,
                                       stop_on=tuple(stop[w] for w in kw["stop_on"])):
            events.append(f"got {song.display} {outcome}")
    except Exception as e:  # noqa: BLE001 (what the pass raises is an answer)
        raised = type(e).__name__
    return {"events": events, "raised": raised,
            "stats": {"tried": stats.tried, "errors": stats.errors, "budget_exhausted": stats.budget_exhausted,
                      "failures": [[s.display, type(e).__name__, str(e)] for s, e in stats.failures]}}


# --- the records ----------------------------------------------------------------------------------------------------


def _fixture_ids(lib: Library) -> dict[str, int]:
    """The fixture's version ids by "provider/tab", for the cases to name."""
    return {f"{p}/{t}": i for i, p, t in lib.conn.execute("SELECT id, provider, tab_id FROM versions ORDER BY id")}


def cases(v: dict[str, int]) -> list[dict[str, Any]]:
    """Every record, ``v`` the fixture's version ids."""
    creep, zebra, one, two, song2, wall = (key(n) for n in SONGS)
    sheet, tab, gp, gone, other = v["ug/101"], v["ug/202"], v["gtptabs/55"], v["lacuerda/radiohead/creep"], v["ug/303"]
    first, second = v["ug/7"], v["gtptabs/8"]
    harp = v["harptabs/1234"]
    creep_sheet = "Radiohead/Creep/sheet.txt"
    sha = hashlib.sha256(b"[Am]Creep").hexdigest()
    raw = '{"z": 1, "a": [1.5, null, "é"], "m": {"b": 2}}'
    k = "caracole.library."
    out = [
        # keep_file
        rec(k + "keep_file", "a new file in a folder that isn't there yet",
            {"song": wall, "version_id": sheet, "name": "sheet.txt", "data": b64(b"[G]Today"), "rank": 1, "now": LATER}),
        rec(k + "keep_file", "a kept name, new bytes and another version: replaced in place",
            {"song": creep, "version_id": other, "name": "sheet.txt", "data": b64(b"[C]Creep"), "rank": 2,
             "now": LATER}),
        rec(k + "keep_file", "the same bytes under the same name: written again",
            {"song": creep, "version_id": sheet, "name": "sheet.txt", "data": b64(b"[Am]Creep"), "rank": 1,
             "now": LATER}),
        rec(k + "keep_file", "the same bytes under another name of the song: a duplicate, nothing written",
            {"song": creep, "version_id": tab, "name": "copy.txt", "data": b64(b"e|--0--|"), "rank": 1, "now": LATER}),
        rec(k + "keep_file", "bytes another song keeps: kept",
            {"song": zebra, "version_id": sheet, "name": "sheet.txt", "data": b64(b"[Am]Creep"), "rank": 1,
             "now": LATER}),
        rec(k + "keep_file", "a file another song keeps in the folder they share: SharedFolder, nothing written",
            {"song": two, "version_id": second, "name": "sheet.txt", "data": b64(b"[Em]part two"), "rank": 1,
             "now": LATER}),
        rec(k + "keep_file", "a name no other song keeps in the folder they share: kept",
            {"song": two, "version_id": second, "name": "guitar-2.gp5", "data": b64(b"GP2 of part two"), "rank": 1,
             "now": LATER}),
        rec(k + "keep_file", "a name a folder can't hold: its safe name in the path, the name as given",
            {"song": song2, "version_id": harp, "name": " a/b\\c: d?*.txt. ", "data": b64(b"odd"), "rank": 3,
             "now": LATER}),
        rec(k + "keep_file", "a song of other scripts, empty bytes",
            {"song": zebra, "version_id": sheet, "name": "斑马.txt", "data": b64(b""), "rank": 1, "now": LATER}),
        rec(k + "keep_file", "a name kept whose file is gone: written again",
            {"song": creep, "version_id": tab, "name": "tab.txt", "data": b64(b"e|--0--|"), "rank": 1, "now": LATER},
            changes={"Radiohead/Creep/tab.txt": None}),
        rec(k + "keep_file", "a file put there by hand under the name: replaced",
            {"song": creep, "version_id": gp, "name": "notes.txt", "data": b64(b"kept now"), "rank": 1, "now": LATER}),
        # kept_already
        rec(k + "kept_already", "kept by this version, as kept",
            {"song": creep, "version_id": sheet, "name": "sheet.txt", "data": b64(b"[Am]Creep")}),
        rec(k + "kept_already", "kept by another version",
            {"song": creep, "version_id": other, "name": "sheet.txt", "data": b64(b"[Am]Creep")}),
        rec(k + "kept_already", "other bytes",
            {"song": creep, "version_id": sheet, "name": "sheet.txt", "data": b64(b"[Am]Creep!")}),
        rec(k + "kept_already", "the file deleted from the library",
            {"song": creep, "version_id": sheet, "name": "sheet.txt", "data": b64(b"[Am]Creep")},
            changes={creep_sheet: None}),
        rec(k + "kept_already", "the file cut short",
            {"song": creep, "version_id": sheet, "name": "sheet.txt", "data": b64(b"[Am]Creep")},
            changes={creep_sheet: b64(b"[Am]")}),
        rec(k + "kept_already", "the file replaced by other bytes of its length",
            {"song": creep, "version_id": sheet, "name": "sheet.txt", "data": b64(b"[Am]Creep")},
            changes={creep_sheet: b64(b"[Em]Creep")}),
        rec(k + "kept_already", "a name the song doesn't keep",
            {"song": creep, "version_id": sheet, "name": "notes.txt", "data": b64(b"mine")}),
        # kept_files, keeper_of
        rec(k + "kept_files", "a song's kept files, by name", {"song": creep}),
        rec(k + "kept_files", "a song with none", {"song": wall}),
        rec(k + "keeper_of", "the other song of the folder keeps the name", {"song": two, "name": "sheet.txt"}),
        rec(k + "keeper_of", "the song keeps it itself", {"song": one, "name": "sheet.txt"}),
        rec(k + "keeper_of", "nobody keeps it", {"song": two, "name": "tab.txt"}),
        # holds
        rec(k + "holds", "the bytes, their size given", {"path": creep_sheet, "sha256": sha, "size": 9}),
        rec(k + "holds", "the bytes, no size", {"path": creep_sheet, "sha256": sha, "size": None}),
        rec(k + "holds", "another size", {"path": creep_sheet, "sha256": sha, "size": 10}),
        rec(k + "holds", "other bytes", {"path": "Radiohead/Creep/tab.txt", "sha256": sha, "size": None}),
        rec(k + "holds", "no file there", {"path": "Radiohead/Creep/none.txt", "sha256": sha, "size": None}),
        rec(k + "holds", "a folder there", {"path": "Radiohead/Creep", "sha256": sha, "size": None}),
        # drop_file
        rec(k + "drop_file", "a kept file: its row and its file go", {"song": creep, "name": "tab.txt"}),
        rec(k + "drop_file", "a name the song doesn't keep: nothing", {"song": creep, "name": "notes.txt"}),
        rec(k + "drop_file", "a kept file already gone: its row goes", {"song": creep, "name": "tab.txt"},
            changes={"Radiohead/Creep/tab.txt": None}),
        rec(k + "drop_file", "the song's own file in a folder it shares", {"song": one, "name": "guitar-1.gp5"}),
        # write_atomic
        rec(k + "write_atomic", "a new file in new folders", {"path": "New/Folder/a.txt", "data": b64(b"new")}),
        rec(k + "write_atomic", "over a file", {"path": "Radiohead/Creep/notes.txt", "data": b64(b"over")}),
    ]
    k = "caracole.versions."
    upsert = {"provider": "ug", "tab_id": "404", "song": creep, "slot": "sheet", "kind": "chords", "rating": 4.25,
              "votes": 12, "version": 2, "label": None, "url": "https://ug/404", "raw": raw, "now": LATER}
    out += [
        rec(k + "upsert_version", "a new version", upsert),
        rec(k + "upsert_version", "a version again: refreshed, live, its pick and coverage kept",
            {**upsert, "tab_id": "303", "rating": 4.0, "votes": 100, "label": "Live", "kind": "ukulele",
             "raw": '{"b": 1e-07, "a": -0.0, "c": 2.5e+20}'}),
        rec(k + "upsert_version", "a version gone, recorded again: live",
            {**upsert, "provider": "lacuerda", "tab_id": "radiohead/creep", "kind": "acordes", "rating": 0,
             "votes": 0, "version": 0, "raw": "{}"}),
        rec(k + "upsert_version", "a number 0 for its version is 1; a rating of 0 is 0.0",
            {**upsert, "tab_id": "405", "rating": 0, "votes": 0, "version": 0, "label": "Ver 0"}),
        rec(k + "upsert_version", "the same tab for another song is another version",
            {**upsert, "song": zebra, "tab_id": "101", "slot": "guitar", "kind": "tabs"}),
        rec(k + "upsert_version", "a raw of other scripts and escapes",
            {**upsert, "tab_id": "406", "raw": '{"名": "斑马\\u0000\\n\\"", "😀": [true, false, {}], "": []}'}),
        rec(k + "song_versions", "a song's live versions, by id",
            {"song": creep, "slot": None, "kinds": None, "include_gone": False}),
        rec(k + "song_versions", "every version, gone ones too",
            {"song": creep, "slot": None, "kinds": None, "include_gone": True}),
        rec(k + "song_versions", "a slot", {"song": creep, "slot": "guitar", "kinds": None, "include_gone": False}),
        rec(k + "song_versions", "kinds", {"song": creep, "slot": None, "kinds": ["chords", "acordes"],
                                           "include_gone": True}),
        rec(k + "song_versions", "no kinds", {"song": creep, "slot": "sheet", "kinds": [], "include_gone": True}),
        rec(k + "song_versions", "a song with none", {"song": wall, "slot": None, "kinds": None,
                                                      "include_gone": True}),
        rec(k + "get_version", "a version", {"version_id": sheet}),
        rec(k + "get_version", "a version gone", {"version_id": gone}),
        rec(k + "get_version", "no such version", {"version_id": 9999}),
        rec(k + "set_raw", "a raw replaced, its order kept", {"version_id": sheet, "raw": '{"b": [], "a": 0.5}'}),
        rec(k + "set_coverage", "a coverage", {"version_id": sheet, "value": 0.875}),
        rec(k + "set_coverage", "a whole coverage, an integer", {"version_id": sheet, "value": 1}),
        rec(k + "set_coverage", "none", {"version_id": sheet, "value": None}),
        rec(k + "mark_gone", "a picked version gone: no pick", {"version_id": other}),
        rec(k + "mark_stale", "a provider's live versions stale", {"song": creep, "provider": "ug"}),
        rec(k + "mark_stale", "a gone version stays gone", {"song": creep, "provider": "lacuerda"}),
        rec(k + "mark_stale", "a provider with none", {"song": creep, "provider": "harptabs"}),
        rec(k + "set_picks", "picks ranked in order, the older cleared",
            {"song": creep, "kinds": ["chords"], "version_ids": [sheet, other]}),
        rec(k + "set_picks", "over every sheet kind",
            {"song": creep, "kinds": ["chords", "ukulele", "acordes", "auto"], "version_ids": [gone]}),
        rec(k + "set_picks", "none: the kinds' picks cleared", {"song": creep, "kinds": ["chords"], "version_ids": []}),
        rec(k + "set_picks", "another kind's picks stay", {"song": creep, "kinds": ["tabs"], "version_ids": [tab]}),
        rec(k + "set_picks", "another song's version is no pick of this one",
            {"song": creep, "kinds": ["chords"], "version_ids": [first, sheet]}),
        rec(k + "picks", "a song's picks, best first", {"song": creep, "kinds": ["chords"]}),
        rec(k + "picks", "kinds with none", {"song": creep, "kinds": ["tabs", "harmonica"]}),
    ]
    k = "caracole.songs."
    out += [
        rec(k + "update_song", "text columns", {"song": creep, "now": LATER,
                                                "fields": {"status": "found", "lyrics_status": "missing"}}),
        rec(k + "update_song", "JSON columns: lists and dicts as JSON",
            {"song": creep, "now": LATER, "fields": {"match_candidates": [{"z": 1, "a": "é"}, 2.5],
                                                     "source_ids": {"wanted": ["radiohead/creep", "x"]},
                                                     "artists": ["Radiohead", "宋冬野"]}}),
        rec(k + "update_song", "a JSON column given a text: the text as JSON",
            {"song": creep, "now": LATER, "fields": {"match_candidates": "[]"}}),
        rec(k + "update_song", "booleans as 0 and 1, whatever they are given as",
            {"song": creep, "now": LATER, "fields": {"review": True, "ug_dirty": 0}}),
        rec(k + "update_song", "a boolean given a text is 1, given null 0",
            {"song": zebra, "now": LATER, "fields": {"review": "yes", "ug_dirty": None}}),
        rec(k + "update_song", "a boolean given a list", {"song": zebra, "now": LATER, "fields": {"review": [0]}}),
        rec(k + "update_song", "numbers and nulls",
            {"song": creep, "now": LATER, "fields": {"match_score": 91.5, "duration_ms": 238000, "audio_mtime": 3,
                                                     "match_step": None, "lyrics_json": None}}),
        rec(k + "update_song", "updated_at given: the clock's wins",
            {"song": creep, "now": LATER, "fields": {"updated_at": "2020-01-01T00:00:00Z"}}),
        rec(k + "update_song", "no field: nothing, updated_at too", {"song": creep, "now": LATER, "fields": {}}),
        rec(k + "update_song", "an unknown field", {"song": creep, "now": LATER,
                                                    "fields": {"status": "found", "zeta": 1, "alpha": 2}}),
        rec(k + "update_song", "the id", {"song": creep, "now": LATER, "fields": {"id": 7}}),
        rec(k + "refresh_status", "a human sheet: found", {"song": creep, "ignored": False, "now": LATER}),
        rec(k + "refresh_status", "an auto sheet alone: found", {"song": song2, "ignored": False, "now": LATER}),
        rec(k + "refresh_status", "a Guitar Pro file alone: wanted", {"song": two, "ignored": False, "now": LATER}),
        rec(k + "refresh_status", "ignored, whatever it keeps", {"song": creep, "ignored": True, "now": LATER}),
        rec(k + "refresh_status", "nothing kept: wanted", {"song": wall, "ignored": False, "now": LATER}),
    ]
    k = "caracole.inbox."
    out += [
        rec(k + "guitar_number", "kept 1, 3 put there by hand in capitals: 2", {"song": creep}),
        rec(k + "guitar_number", "digits of other scripts, leading zeros, any case and extension; no dot, none",
            {"song": song2}),
        rec(k + "guitar_number", "another song keeps 1 in the folder they share, the song 3: 2", {"song": two}),
        rec(k + "guitar_number", "a song with no folder", {"song": wall}),
        rec(k + "guitar_number", "a kept file whose file is gone still holds its number", {"song": creep},
            changes={"Radiohead/Creep/guitar-1.gp5": None, "Radiohead/Creep/guitar-3.GP5": None}),
        rec(k + "guitar_number", "a folder in the song's folder counts by its name, the files in it don't",
            {"song": wall}, changes={"Oasis/Wonderwall/guitar-2.gp5/guitar-1.gp5": b64(b"in a folder")}),
        rec(k + "harmonica_number", "a tab kept, a page and a tab by hand; another case is no tab", {"song": song2}),
        rec(k + "harmonica_number", "none", {"song": creep}),
        rec(k + "gametab_number", "kept 1, 3 by hand, 2 in another case is none", {"song": song2}),
        rec(k + "score_number", "a pdf: 1 kept, 2 in capitals", {"song": song2, "ext": ".pdf"}),
        rec(k + "score_number", "an mscz: 3 by hand", {"song": song2, "ext": ".mscz"}),
        rec(k + "score_number", "an extension with none", {"song": song2, "ext": ".mid"}),
        rec(k + "score_number", "an extension asked in capitals matches none", {"song": song2, "ext": ".PDF"}),
    ]
    k = "caracole.provider_pass.each_song"
    songs = ["a", "b", "c", "d"]
    for case, turns, stop_on in (
            ("every song answers", {}, []),
            ("an error is counted, named and heard, and the pass goes on", {"b": "error"}, []),
            ("robots.txt's refusal is an error like any", {"a": "robots", "c": "robots"}, []),
            ("an error the pass stops on ends it after it is counted", {"b": "pages", "c": "pages"}, ["pages"]),
            ("a block propagates", {"c": "blocked"}, []),
            ("a spent budget ends the pass, the song not counted", {"b": "error", "c": "budget"}, []),
            ("unavailable: that song and every one left are failures, never asked", {"b": "unavailable"}, []),
            ("unavailable at the first song", {"a": "unavailable"}, []),
            ("unavailable at the last song", {"b": "error", "d": "unavailable"}, ["robots"]),
            ("errors of every kind but the one stopped on", {"a": "error", "b": "robots", "c": "pages"}, ["error"]),
    ):
        out.append(rec(k, case, {"songs": songs, "turns": turns, "stop_on": stop_on}, fixture=None))
    out.append(rec(k, "no song", {"songs": [], "turns": {}, "stop_on": []}, fixture=None))
    return out


class Writes:
    """The fixtures, built and replayed in ``workdir``, and the records made over them."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.texts: dict[str, str] = {}
        self.ids: dict[str, dict[str, int]] = {}
        self.libraries: list[Library] = []
        self.n = 0

    def close(self) -> None:
        for lib in self.libraries:
            lib.close()

    def library(self, where: str) -> Library:
        lib = Library(self.workdir / where)
        self.libraries.append(lib)
        return lib

    def fixture_text(self, name: str) -> str:
        if name not in self.texts:
            lib = self.library(f"built/{name}")
            FIXTURES[name](lib)
            _settled(lib.conn)
            self.ids[name] = _fixture_ids(lib)
            records = [r for r in dump_fixture(lib.conn, lib.cfg.library_dir) if r.get("file") not in TOP_FILES]
            self.texts[name] = jsonl(records, corpus=f"library/writes_fixture_{name}", made_by=MADE_BY)
        return self.texts[name]

    @contextmanager
    def replayed(self, name: str) -> Iterator[Library]:
        self.n += 1
        lib = self.library(f"replayed/{self.n}")
        try:
            replay_fixture(lib.conn, read_fixture(self.fixture_text(name)), lib.cfg.library_dir)
            yield lib
        finally:
            lib.close()
            self.libraries.remove(lib)

    def answer(self, spec: dict[str, Any]) -> dict[str, Any]:
        # What the record says, its members in the record's order, is what the call is given.
        record = json.loads(json.dumps(spec, ensure_ascii=False, sort_keys=True))
        if record["fixture"] is None:
            return {**record, "out": each_song_answer(record["kw"])}
        with self.replayed(record["fixture"]) as lib:
            root = lib.cfg.library_dir
            for path, change in (record["changes"] or {}).items():
                target = root / path
                if change is None:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(unb64(change))
            before = {t: _rows(lib.conn, t) for t in TABLES}
            files_before = _library(root)
            try:
                record["out"] = plain(CALLS[record["fn"]](lib, record["kw"]))
            except Exception as e:  # noqa: BLE001 (an exception is an answer too)
                record["err"], record["message"] = type(e).__name__, str(e)
            after = {t: _rows(lib.conn, t) for t in TABLES}
            _stamped(before["files"], after["files"], record["kw"].get("now"))
            files_after = _library(root)
            record["after"] = {"rows": {}, "gone": {}, "units": _units(lib.conn),
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
        self.fixture_text("library")
        return [self.answer(spec) for spec in cases(self.ids["library"])]


def _stamped(before: list[dict[str, Any]], after: list[dict[str, Any]], now: str | None) -> None:
    """keep_file's ``created_at``, SQLite's clock: each row it wrote holds a time of that form now, recorded as
    ``now``, the time the phone's writer is given."""
    old = {r["id"]: r["created_at"] for r in before}
    for row in after:
        if old.get(row["id"]) == row["created_at"]:
            continue
        stamp = row["created_at"]
        assert STAMP.fullmatch(stamp), stamp
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs(datetime.now(UTC) - at) < timedelta(minutes=5), stamp
        assert now is not None
        row["created_at"] = now


def every_file(workdir: Path) -> dict[Path, str]:
    writes = Writes(workdir)
    try:
        records = writes.records()
        files = {fixture_path(name): writes.fixture_text(name) for name in FIXTURES}
        files[WRITES] = jsonl(records, corpus="library/writes", made_by=MADE_BY)
    finally:
        writes.close()
    return files


# --- the tests -----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return every_file(tmp_path_factory.mktemp("library-writes"))


@pytest.mark.parametrize("name", [*FIXTURES, "writes"])
def test_the_vector_is_what_the_library_writers_do(made, name):
    path = WRITES if name == "writes" else fixture_path(name)
    check(path, made[path])


def test_every_writer_and_rung_of_the_ladder_is_in_the_vectors(made):
    records = [json.loads(line) for line in made[WRITES].splitlines()[1:]]
    assert {r["fn"] for r in records} == {*CALLS, "caracole.provider_pass.each_song"}
    assert {r.get("err") for r in records} >= {"SharedFolder", "ValueError", "KeyError"}
    passes = [r["out"] for r in records if r["fn"].endswith("each_song")]
    assert {p["raised"] for p in passes} == {None, "ProviderBlocked"}
    assert any(p["stats"]["budget_exhausted"] for p in passes)
    assert any(f[1] == "ProviderUnavailable" for p in passes for f in p["stats"]["failures"])
    # Each record's writes show in its units: a change to a song's kept files or versions changes its digest.
    fixture = read_fixture(made[fixture_path("library")])
    assert any(r["fn"].endswith("keep_file") and "files" in r["after"]["rows"] for r in records)
    assert any(r["fn"].endswith("drop_file") and "files" in r["after"]["gone"] for r in records)
    assert any(None in r["after"]["library"].values() for r in records if r["fixture"])
    assert all(r["after"]["units"] for r in records if r["fixture"]) and fixture


def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    assert every_file(tmp_path) == made
