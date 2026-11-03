"""The schema, for the phone: tests/conformance/data/caracole/schema/migrations.json, db.py's migrations as the
phone's core.db.Database runs them.

Its format: ``{"schema": db.SCHEMA_VERSION, "statements": {"1": [statement, …], …}}``, each script of
``db._MIGRATIONS`` split into its statements with ``sqlite3.complete_statement`` (the bundled SQLite's prepare runs
the first statement of a text and drops the rest), each statement as the script writes it, its comments before it
included, its ``;`` kept. The phone runs each version's statements in ``BEGIN IMMEDIATE`` … ``PRAGMA
user_version = N`` … ``COMMIT``, as db.py runs a script.
"""

import json
import sqlite3

from caracole import db
from helpers.corpus import DATA, check

MIGRATIONS = DATA / "schema" / "migrations.json"


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
