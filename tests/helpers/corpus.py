"""The conformance corpus's helpers: what the Python suite writes for the Kotlin port to read
(docs/superpowers/specs/2026-11-03-conformance-corpus.md).

- ``VECTORS`` and ``DATA``: tests/conformance/vectors/ and tests/conformance/data/caracole/.
- ``versions()``: the header's ``versions``, what the answers were computed with.
- ``plain(obj)``: a value as a corpus writes it (a tuple an array, a dataclass or NamedTuple an object of its fields,
  a ``Song`` its key; a set refused).
- ``jsonl(records, corpus=, made_by=)``: a ``.jsonl`` vector's text, its header first, a record a line;
  ``json_document(obj, corpus=, made_by=)``: a ``.json`` vector's.
- ``check(path, content)``: the committed file must be ``content``, byte for byte; with ``CARACOLE_CORPUS=write`` it
  is written instead.
- ``dump_fixture(conn, library_dir=None)`` and ``replay_fixture(conn, records, library_dir=None)``: a database's rows,
  kv and library files as fixture records, and those records into a freshly migrated database, as Kotlin's
  ``Fixtures.load`` replays them.

A generator test builds its file in memory and calls ``check``:

    from helpers.corpus import VECTORS, check, jsonl

    check(VECTORS / "keys" / "identity.jsonl", jsonl(records, corpus="keys/identity",
                                                       made_by="tests/test_conformance_keys.py"))
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pytest

CONFORMANCE = Path(__file__).resolve().parents[1] / "conformance"
VECTORS = CONFORMANCE / "vectors"
DATA = CONFORMANCE / "data" / "caracole"
PHONE_SQL = DATA / "schema" / "phone.sql"

REGENERATE = "CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py"

# The base tables a fixture holds, parents first; then the phone's (when they exist) and kv.
FIXTURE_TABLES = (
    "songs", "versions", "files", "removed", "events", "ug_index", "ug_artist_tabs", "lacuerda_index",
    "gtptabs_index", "musescore_index", "harptabs_index", "harptabs_artists", "harptabs_artist_tabs",
    "gametabs_index", "gametabs_games", "gametabs_game_tabs",
)
PHONE_TABLES = ("phone_overrides", "phone_songbooks")
# Filled by ug_index's and ug_keys' triggers as the rows go in: never dumped, so a replay numbers them alike.
TRIGGER_FILLED = ("ug_keys", "ug_artists", "ug_key_words")


def versions() -> dict[str, str]:
    """What a corpus's answers were computed with: a bump of any makes every file stale."""
    import platform
    import unicodedata

    import pypinyin
    import rapidfuzz

    import caracole

    return {
        "caracole": caracole.__version__,
        "pypinyin": pypinyin.__version__,
        "python": platform.python_version(),
        "rapidfuzz": rapidfuzz.__version__,
        "sqlite": sqlite3.sqlite_version,
        "unicodedata": unicodedata.unidata_version,
    }


def plain(obj: Any) -> Any:
    """``obj`` as a corpus writes it: JSON's values, recursively."""
    from caracole.songs import Song

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Song):
        return obj.key
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, tuple) and hasattr(obj, "_fields"):  # a NamedTuple
        return {name: plain(getattr(obj, name)) for name in obj._fields}
    if isinstance(obj, (list, tuple)):
        return [plain(x) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError(f"a corpus object's keys are strings, not {key!r}")
            out[key] = plain(value)
        return out
    if isinstance(obj, (set, frozenset)):
        raise TypeError("a set has no order: sort it before it goes in a corpus")
    raise TypeError(f"no corpus form for {type(obj).__name__}: {obj!r}")


def _line(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        raise ValueError("a corpus holds no lone surrogate")
    return text


def _header(corpus: str, made_by: str) -> dict[str, Any]:
    return {"header": True, "corpus": corpus, "made_by": made_by, "versions": versions()}


def jsonl(records: Iterable[Any], *, corpus: str, made_by: str) -> str:
    """A ``.jsonl`` vector: the header, then each record (made ``plain``) a line, each line ending in ``\\n``."""
    lines = [_line(_header(corpus, made_by))]
    lines += [_line(plain(record)) for record in records]
    return "".join(line + "\n" for line in lines)


def json_document(obj: dict[str, Any], *, corpus: str, made_by: str) -> str:
    """A ``.json`` vector: ``obj`` (made ``plain``) with the header's fields as its ``header`` member."""
    body = plain(obj)
    if "header" in body:
        raise ValueError("a .json vector's header is its own")
    body["header"] = _header(corpus, made_by)
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    _line(body)  # the surrogate check
    return text


def check(path: Path | str, content: str | bytes) -> None:
    """The committed file at ``path`` (absolute, or relative to tests/conformance/) must hold ``content`` exactly.

    With ``CARACOLE_CORPUS=write`` it is written instead (only when it differs). A mismatch fails, naming the first
    line that differs and the command that regenerates every file.
    """
    path = Path(path)
    if not path.is_absolute():
        path = CONFORMANCE / path
    data = content.encode("utf-8") if isinstance(content, str) else content
    if os.environ.get("CARACOLE_CORPUS") == "write":
        if not path.is_file() or path.read_bytes() != data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return
    shown = path.relative_to(CONFORMANCE.parent.parent) if path.is_relative_to(CONFORMANCE.parent.parent) else path
    if not path.is_file():
        pytest.fail(f"{shown} is missing: regenerate it with {REGENERATE}", pytrace=False)
    old = path.read_bytes()
    if old == data:
        return
    old_lines, new_lines = old.split(b"\n"), data.split(b"\n")
    n = next((i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b), min(len(old_lines), len(new_lines)))
    pytest.fail(f"{shown} is stale from line {n + 1} on: regenerate it with {REGENERATE}", pytrace=False)


# --- fixtures ------------------------------------------------------------------------------------------------


def _base_tables(conn: sqlite3.Connection) -> list[str]:
    """Every base table of the database: no virtual table, FTS shadow table or SQLite's own."""
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
    virtual = [name for name, sql in rows if sql and sql.upper().startswith("CREATE VIRTUAL TABLE")]
    return [name for name, sql in rows
            if name not in virtual and not name.startswith("sqlite_")
            and not any(name.startswith(v + "_") for v in virtual)]


def unlisted_tables(conn: sqlite3.Connection) -> list[str]:
    """The base tables a fixture's list neither names nor excludes: a migration added one, and the list must say."""
    known = set(FIXTURE_TABLES) | set(PHONE_TABLES) | set(TRIGGER_FILLED) | {"kv"}
    return [name for name in _base_tables(conn) if name not in known]


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f"SELECT * FROM {_quoted(table)} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    out = []
    for row in cursor.fetchall():
        values = dict(zip(names, tuple(row)))
        if any(isinstance(v, bytes) for v in values.values()):
            raise TypeError(f"{table} holds a blob, which a fixture can't carry")
        out.append(values)
    return out


def _files(library_dir: Path | None) -> list[dict[str, str]]:
    if library_dir is None:
        return []
    out = []
    for path in sorted(p for p in Path(library_dir).rglob("*") if p.is_file() and not p.is_symlink()):
        name = path.relative_to(library_dir).as_posix()
        out.append({"file": name, "base64": base64.b64encode(path.read_bytes()).decode("ascii")})
    return out


def dump_fixture(conn: sqlite3.Connection, library_dir: Path | None = None, *, sync_id: bool = False,
                 raw: bool = False) -> list[dict[str, Any]]:
    """The fixture records of a migrated caracole database: the base tables of ``FIXTURE_TABLES`` (then the phone's,
    when they exist) row by row in rowid order, then kv by key, without ``sync:id`` unless ``sync_id``, then every
    regular file under ``library_dir`` by path.

    With ``raw``, a database that isn't caracole's (an index export): its ``CREATE`` statements first (tables, then
    indexes, as ``sqlite_master`` holds them), then every table's rows in that order.
    """
    if raw:
        base = set(_base_tables(conn))
        objects = conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table', 'index') AND sql IS NOT NULL "
            "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, rowid").fetchall()
        if any(kind == "table" and name not in base for kind, name, _ in objects):
            raise ValueError("a raw fixture holds plain tables alone, no virtual table")
        records: list[dict[str, Any]] = [{"sql": sql} for _, _, sql in objects]
        tables = [name for kind, name, _ in objects if kind == "table"]
        records += [{"table": t, "row": row} for t in tables for row in _rows(conn, t)]
        return records + _files(library_dir)
    unlisted = unlisted_tables(conn)
    if unlisted:
        raise ValueError(f"tables a fixture's list doesn't name: {', '.join(unlisted)} (helpers/corpus.py)")
    present = set(_base_tables(conn))
    records = []
    for table in FIXTURE_TABLES + tuple(t for t in PHONE_TABLES if t in present):
        records += [{"table": table, "row": row} for row in _rows(conn, table)]
    for key, value in conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall():
        if key == "sync:id" and not sync_id:
            continue
        records.append({"kv": key, "value": value})
    return records + _files(library_dir)


def read_fixture(text: str) -> list[dict[str, Any]]:
    """The records of a fixture's text, its header left out."""
    records = [json.loads(line) for line in text.splitlines() if line]
    return [r for r in records if not r.get("header")]


def phone_schema(conn: sqlite3.Connection) -> None:
    """The phone's own tables, from phone.sql, and kv ``phone:schema``, as core.db.PhoneSchema makes them."""
    statements = [s.strip() for s in _without_comments(PHONE_SQL.read_text("utf-8")).split(";")]
    conn.execute("SAVEPOINT phone_schema")
    try:
        for statement in statements:
            if statement:
                conn.execute(statement)
        conn.execute("INSERT INTO kv (key, value) VALUES ('phone:schema', '1') "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    except BaseException:
        conn.execute("ROLLBACK TO phone_schema")
        conn.execute("RELEASE phone_schema")
        raise
    conn.execute("RELEASE phone_schema")


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _without_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def replay_fixture(conn: sqlite3.Connection, records: Iterable[dict[str, Any]],
                   library_dir: Path | None = None) -> None:
    """``records`` into ``conn``, as Kotlin's ``Fixtures.load`` replays them: into a freshly migrated database, the
    phone's tables made first (phone.sql, unless they are there), one plain INSERT per row in order, kv lines as
    upserts, each file written under ``library_dir``. A fixture with ``sql`` lines goes into an empty database
    instead (``Fixtures.loadRaw``): its statements, then its rows."""
    records = [r for r in records if not r.get("header")]
    raw = any("sql" in r for r in records)
    if not raw:
        present = set(_base_tables(conn))
        if not set(PHONE_TABLES) <= present:
            phone_schema(conn)
    conn.execute("SAVEPOINT replay_fixture")
    try:
        for record in records:
            if "sql" in record:
                conn.execute(record["sql"])
            elif "table" in record:
                row = record["row"]
                names = list(row)
                columns = ", ".join(_quoted(n) for n in names)
                conn.execute(f"INSERT INTO {_quoted(record['table'])} ({columns}) "
                             f"VALUES ({', '.join('?' for _ in names)})", [row[n] for n in names])
            elif "kv" in record:
                conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (record["kv"], record["value"]))
            elif "file" in record:
                if library_dir is None:
                    raise ValueError("a fixture with files replays into a library folder")
                path = Path(library_dir) / record["file"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(record["base64"]))
            else:
                raise ValueError(f"not a fixture record: {record!r}")
    except BaseException:
        conn.execute("ROLLBACK TO replay_fixture")
        conn.execute("RELEASE replay_fixture")
        raise
    conn.execute("RELEASE replay_fixture")
