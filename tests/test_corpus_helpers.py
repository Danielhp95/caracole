"""helpers/corpus.py: the conformance corpus's frame (docs/superpowers/specs/2026-11-03-conformance-corpus.md).

It also writes vectors/corpus/fixtures/library.jsonl, a small library with UG index rows, which the Kotlin side's
``Fixtures.load`` replays (android/core's CorpusFrameTest)."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pytest

from caracole import db
from helpers import corpus
from helpers.corpus import VECTORS, check, dump_fixture, jsonl, plain, read_fixture, replay_fixture

FIXTURE = VECTORS / "corpus" / "fixtures" / "library.jsonl"
STAMP = "2026-11-03T10:00:00Z"
FTS_TABLES = ("ug_artists_fts", "ug_index_fts", "ug_keys_fts")


def fresh(path: Path) -> sqlite3.Connection:
    return db.connect(path)


def a_library(conn: sqlite3.Connection, library: Path) -> None:
    """A library made with fixed values alone, so its fixture is the same on every run."""
    for song_id, key, artist, title in ((1, "radiohead|creep", "Radiohead", "Creep"),
                                        (2, "song dongye|an he qiao", "宋冬野", "安和桥")):
        conn.execute(
            "INSERT INTO songs (id, key, artist, title, artists, added_at, created_at, updated_at, lyrics_json, "
            "match_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (song_id, key, artist, title, json.dumps([artist], ensure_ascii=False), STAMP, STAMP, STAMP,
             '{"plain": "line\\n"}' if song_id == 1 else None, 91.5 if song_id == 1 else None))
    conn.execute("INSERT INTO versions (id, provider, tab_id, song_id, slot, kind, url, raw, fetched_at) "
                 "VALUES (1, 'ug', '123', 1, 'sheet', 'chords', 'https://example.invalid/tab', '{\"capo\": 2}', ?)",
                 (STAMP,))
    conn.execute("INSERT INTO files (id, version_id, song_id, name, path, sha256, kept_rank, created_at) "
                 "VALUES (1, 1, 1, 'sheet.txt', 'Radiohead/Creep/sheet.txt', ?, 0, ?)", ("0" * 64, STAMP))
    conn.execute("INSERT INTO removed (key, artist, title, removed_at) VALUES ('eagles|hotel california', "
                 "'Eagles', 'Hotel California', ?)", (STAMP,))
    for tab_id, artist_key, song_key in ((10, "radiohead", "creep"), (11, "radiohead", "karma-police"),
                                         (12, "song-dongye", "an-he-qiao"), (13, "eagles", "hotel-california")):
        conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, ?, ?, 'Chords', 'tabs1.xml', ?, ?)",
                     (tab_id, artist_key, song_key, STAMP, f"tab/{artist_key}/{song_key}-chords-{tab_id}"))
    conn.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, page) "
                 "VALUES ('soda_stereo/', 'soda_stereo', 'Soda Stereo', 'soda stereo', 's')")
    db.kv_set_json(conn, "render:1", {"pdf": "sheet.pdf", "at": STAMP})
    db.kv_set(conn, "ug:index:done", "1")
    folder = library / "Radiohead" / "Creep"
    folder.mkdir(parents=True)
    (folder / "sheet.txt").write_text("[Am]Creep\n", "utf-8")


def fts_checked(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    for table in FTS_TABLES:
        conn.execute(f"INSERT INTO {table}({table}) VALUES ('integrity-check')")


def test_a_library_round_trips_through_its_fixture_and_passes_the_integrity_checks(tmp_path):
    first = fresh(tmp_path / "a" / "caracole.sqlite")
    a_library(first, tmp_path / "a" / "library")
    records = dump_fixture(first, tmp_path / "a" / "library")
    text = jsonl(records, corpus="corpus/fixtures/library", made_by="tests/test_corpus_helpers.py")
    check(FIXTURE, text)  # the fixture the Kotlin side replays

    second = fresh(tmp_path / "b" / "caracole.sqlite")
    replay_fixture(second, read_fixture(text), tmp_path / "b" / "library")
    fts_checked(second)
    again = dump_fixture(second, tmp_path / "b" / "library")
    # The replay holds the phone's tables (empty) and kv phone:schema, as the phone's database does.
    assert {"kv": "phone:schema", "value": "1"} in again
    assert [r for r in again if r.get("kv") != "phone:schema"] == records
    # The triggers numbered what they fill alike.
    for table in corpus.TRIGGER_FILLED:
        assert ([tuple(r) for r in first.execute(f"SELECT * FROM {table} ORDER BY id")]
                == [tuple(r) for r in second.execute(f"SELECT * FROM {table} ORDER BY id")])
    hits = second.execute("SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?)",
                          ("%police%",)).fetchall()
    assert [tuple(r) for r in hits] == [("karma-police",)]
    assert (tmp_path / "b" / "library" / "Radiohead" / "Creep" / "sheet.txt").read_text("utf-8") == "[Am]Creep\n"


def test_a_fixture_leaves_out_the_id_unless_it_pins_it(conn):
    (sync_id,) = conn.execute("SELECT value FROM kv WHERE key = 'sync:id'").fetchone()
    assert not any(r.get("kv") == "sync:id" for r in dump_fixture(conn))
    assert {"kv": "sync:id", "value": sync_id} in dump_fixture(conn, sync_id=True)


def test_the_fixed_list_names_every_base_table_of_the_schema(conn):
    assert corpus.unlisted_tables(conn) == []
    listed = set(corpus.FIXTURE_TABLES) | set(corpus.TRIGGER_FILLED) | {"kv"}
    assert set(corpus._base_tables(conn)) == listed  # no phone table in Python's own schema


def test_a_migration_that_adds_an_unlisted_table_fails_the_dump(conn):
    conn.execute("CREATE TABLE new_thing (x)")
    conn.execute("CREATE VIRTUAL TABLE new_fts USING fts5(x)")  # its shadow tables are no base tables
    assert corpus.unlisted_tables(conn) == ["new_thing"]
    with pytest.raises(ValueError, match="new_thing"):
        dump_fixture(conn)


def test_a_raw_fixture_carries_its_tables_statements_and_replays_into_an_empty_file(tmp_path):
    export = sqlite3.connect(tmp_path / "export.sqlite", isolation_level=None)
    export.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    export.execute("CREATE INDEX kv_value ON kv(value)")
    export.execute("INSERT INTO kv VALUES ('a', '1'), ('b', '2')")
    records = dump_fixture(export, raw=True)
    assert [r for r in records if "sql" in r] == [
        {"sql": "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)"},
        {"sql": "CREATE INDEX kv_value ON kv(value)"}]
    empty = sqlite3.connect(tmp_path / "empty.sqlite", isolation_level=None)
    replay_fixture(empty, records)
    assert empty.execute("SELECT * FROM kv ORDER BY key").fetchall() == [("a", "1"), ("b", "2")]
    assert not empty.execute("SELECT 1 FROM sqlite_master WHERE name = 'phone_overrides'").fetchall()


def test_kv_lines_replay_as_upserts(conn):
    replay_fixture(conn, [{"kv": "sync:id", "value": "00000000000000aa"}, {"kv": "x", "value": "1"},
                          {"kv": "x", "value": "2"}])
    assert db.kv_get(conn, "sync:id") == "00000000000000aa" and db.kv_get(conn, "x") == "2"


class Pair(NamedTuple):
    a: int
    b: tuple


@dataclass
class Hit:
    name: str
    pair: Pair
    score: float


def test_plain_writes_values_as_a_corpus_does(conn):
    from conftest import add_song

    song = add_song(conn, "Radiohead", "Creep")
    assert plain(Hit("x", Pair(1, (2, 3)), 0.5)) == {"name": "x", "pair": {"a": 1, "b": [2, 3]}, "score": 0.5}
    assert plain({"song": song, "list": (song,)}) == {"song": song.key, "list": [song.key]}
    with pytest.raises(TypeError, match="set"):
        plain({1, 2})


def test_a_jsonl_vector_is_its_header_then_a_sorted_compact_line_a_record():
    text = jsonl([{"fn": "f", "args": ["é", (1, 2)], "kw": {}, "out": 1.5}], corpus="x/y", made_by="tests/t.py")
    header, line = text.splitlines()
    assert text.endswith("\n") and "\r" not in text
    assert json.loads(header) == {"header": True, "corpus": "x/y", "made_by": "tests/t.py",
                                  "versions": corpus.versions()}
    assert set(corpus.versions()) == {"python", "unicodedata", "sqlite", "pypinyin", "rapidfuzz", "caracole"}
    assert line == '{"args":["é",[1,2]],"fn":"f","kw":{},"out":1.5}'
    with pytest.raises(ValueError, match="surrogate"):
        jsonl([{"out": "\ud800"}], corpus="x/y", made_by="t")


def test_check_passes_an_equal_file_fails_a_stale_or_missing_one_and_writes_on_demand(tmp_path, monkeypatch):
    path = tmp_path / "v" / "a.jsonl"
    monkeypatch.delenv("CARACOLE_CORPUS", raising=False)
    with pytest.raises(pytest.fail.Exception, match="missing.*CARACOLE_CORPUS=write"):
        check(path, "one\n")
    monkeypatch.setenv("CARACOLE_CORPUS", "write")
    check(path, "one\ntwo\n")
    assert path.read_bytes() == b"one\ntwo\n"
    monkeypatch.delenv("CARACOLE_CORPUS")
    check(path, "one\ntwo\n")
    with pytest.raises(pytest.fail.Exception, match="stale from line 2"):
        check(path, "one\nthree\n")
    assert path.read_bytes() == b"one\ntwo\n"  # checking writes nothing
