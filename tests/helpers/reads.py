"""``Reads``: what a connection reads while a block runs, counted rather than timed, so that a test of
how much a search reads holds however busy the machine is.

    with Reads(conn) as read:
        found = search(conn, query)
    assert read.rows <= ...  # the rows its statements handed to Python
    assert read.scans("ug_index") == []  # the statements that read the table whole

``rows`` counts each row a statement hands to Python (through the connection's ``row_factory``, which
it keeps); ``statements`` lists each statement run, its values written in (``set_trace_callback``);
``scans(table, ...)`` those of them whose query plan reads one of those tables whole (or one of its
indexes whole), rather than searching it.
"""

from __future__ import annotations

import re
import sqlite3


class Reads:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.rows = 0
        self.statements: list[str] = []

    def __enter__(self) -> Reads:
        self._factory = self.conn.row_factory

        def counted(cursor, row):
            self.rows += 1
            return self._factory(cursor, row) if self._factory else row

        self.conn.row_factory = counted
        self.conn.set_trace_callback(self.statements.append)
        return self

    def __exit__(self, *exc) -> None:
        self.conn.set_trace_callback(None)
        self.conn.row_factory = self._factory

    def scans(self, *tables: str) -> list[str]:
        """The statements run (each once) whose plan reads one of ``tables`` whole: a step "SCAN ug_index", or
        "SCAN ug_index USING COVERING INDEX ...", where a search of it would be "SEARCH ug_index USING ...". What
        a full-text index runs inside a statement of the block, which the trace gives as a comment ("-- SELECT
        ..."), is its own to plan."""
        scan = re.compile(r"SCAN (?:TABLE )?(?:%s)\b" % "|".join(map(re.escape, tables)))
        return [s for s in dict.fromkeys(self.statements) if not s.startswith("--")
                and any(scan.match(step[3]) for step in self.conn.execute("EXPLAIN QUERY PLAN " + s))]
