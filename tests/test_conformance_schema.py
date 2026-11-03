"""The schema, for the phone: tests/conformance/data/caracole/schema/migrations.json, db.py's migrations as the
phone's core.db.Database runs them.

Its format: ``{"schema": db.SCHEMA_VERSION, "statements": {"1": [statement, …], …}}``, each script of
``db._MIGRATIONS`` split into its statements with ``sqlite3.complete_statement`` (the bundled SQLite's prepare runs
the first statement of a text and drops the rest), each statement as the script writes it, its comments before it
included, its ``;`` kept. The phone runs each version's statements in ``BEGIN IMMEDIATE`` … ``PRAGMA
user_version = N`` … ``COMMIT``, as db.py runs a script.

What that makes, for the phone's DatabaseTest to meet (vectors/schema/, through ``helpers.corpus.check``):

- vectors/schema/sqlite_master.json: ``{"objects": [{"type", "name", "tbl_name", "sql"}, …]}``, every row of a freshly
  migrated database's ``sqlite_master`` (tables, indexes, triggers, virtual tables and their shadow tables), sorted by
  type, then name;
- vectors/schema/pragmas.json: ``{"tables": {name: [{"cid", "name", "type", "notnull", "dflt_value", "pk"}, …]}}``,
  each table's ``PRAGMA table_info``, by name.
"""

import json
import sqlite3

import pytest

from caracole import db
from helpers.corpus import DATA, VECTORS, check, json_document

MIGRATIONS = DATA / "schema" / "migrations.json"
SQLITE_MASTER = VECTORS / "schema" / "sqlite_master.json"
PRAGMAS = VECTORS / "schema" / "pragmas.json"
MADE_BY = "tests/test_conformance_schema.py"


def statements(script: str) -> list[str]:
    """``script``'s statements, split where SQLite says one is complete (a ``;`` in a string, a comment or a
    trigger's body ends none)."""
    out, start = [], 0
    for i, c in enumerate(script):
        if c == ";" and sqlite3.complete_statement(script[start:i + 1]):
            out.append(script[start:i + 1].strip())
            start = i + 1
    rest = "\n".join(line for line in script[start:].splitlines() if not line.strip().startswith("--"))
    assert not rest.strip(), f"a statement without its ';': {rest.strip()[:80]}"
    return out


def migrations_json() -> str:
    data = {"schema": db.SCHEMA_VERSION,
            "statements": {str(v): statements(db._MIGRATIONS[v]) for v in sorted(db._MIGRATIONS)}}
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def test_migrations_json_is_db_pys_migrations_statement_by_statement():
    check(MIGRATIONS, migrations_json())


def test_its_statements_one_at_a_time_make_the_schema_db_py_makes(tmp_path):
    made = db.connect(tmp_path / "py.sqlite")
    split = sqlite3.connect(tmp_path / "split.sqlite", isolation_level=None)
    data = json.loads(migrations_json())
    assert data["schema"] == db.SCHEMA_VERSION == max(int(v) for v in data["statements"])
    for version, stmts in data["statements"].items():
        split.execute("BEGIN IMMEDIATE")
        for statement in stmts:
            assert sqlite3.complete_statement(statement)
            split.execute(statement)  # one statement each, or sqlite3 refuses it
        split.execute(f"PRAGMA user_version = {version}")
        split.execute("COMMIT")
    schema = "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    assert split.execute(schema).fetchall() == [tuple(row) for row in made.execute(schema)]
    assert split.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def sqlite_master(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    return [{"type": t, "name": n, "tbl_name": tbl, "sql": sql} for t, n, tbl, sql in rows]


def table_info(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    names = [n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    fields = ("cid", "name", "type", "notnull", "dflt_value", "pk")
    return {name: [dict(zip(fields, tuple(row))) for row in conn.execute(f'PRAGMA table_info("{name}")')]
            for name in names}


def test_sqlite_master_json_is_a_freshly_migrated_database(tmp_path):
    conn = db.connect(tmp_path / "caracole.sqlite")
    check(SQLITE_MASTER, json_document({"objects": sqlite_master(conn)}, corpus="schema/sqlite_master",
                                       made_by=MADE_BY))


def test_pragmas_json_is_each_tables_columns(tmp_path):
    conn = db.connect(tmp_path / "caracole.sqlite")
    check(PRAGMAS, json_document({"tables": table_info(conn)}, corpus="schema/pragmas", made_by=MADE_BY))


def test_migrations_json_says_db_pys_schema_version():
    assert json.loads(MIGRATIONS.read_text("utf-8"))["schema"] == db.SCHEMA_VERSION
    assert sorted(int(v) for v in json.loads(MIGRATIONS.read_text("utf-8"))["statements"]) == sorted(db._MIGRATIONS)


def test_the_schema_vectors_hold_every_kind_of_object(tmp_path):
    objects = sqlite_master(db.connect(tmp_path / "caracole.sqlite"))
    kinds = {o["type"] for o in objects}
    assert kinds == {"table", "index", "trigger"}
    names = {o["name"] for o in objects}
    assert {"ug_keys_fts", "ug_artists_fts", "ug_artist_words", "ug_index_fts", "ug_key_words", "kv"} <= names
    assert not any(name.startswith("phone_") for name in names)  # the phone's own are phone.sql's


@pytest.mark.parametrize("change", ["a statement more", "a version more"])
def test_a_migration_changed_without_regenerating_fails(monkeypatch, tmp_path, change):
    """db.py's migrations changed and the corpus not written again: the check fails, naming the command."""
    if change == "a statement more":
        monkeypatch.setitem(db._MIGRATIONS, 15, db._MIGRATIONS[15] + "\nCREATE TABLE later (x TEXT);\n")
    else:
        monkeypatch.setitem(db._MIGRATIONS, 16, "CREATE TABLE later (x TEXT);\n")
        monkeypatch.setattr(db, "SCHEMA_VERSION", 16)
    monkeypatch.delenv("CARACOLE_CORPUS", raising=False)
    with pytest.raises(pytest.fail.Exception, match="CARACOLE_CORPUS=write"):
        test_migrations_json_is_db_pys_migrations_statement_by_statement()
    with pytest.raises(pytest.fail.Exception, match="stale"):
        test_sqlite_master_json_is_a_freshly_migrated_database(tmp_path)
