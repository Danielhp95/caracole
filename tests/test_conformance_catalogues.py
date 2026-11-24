"""The catalogue file's names and the Keep rule, for the phone: tests/conformance/vectors/catalogues/names.jsonl.

Each record is ``{"name", "schema", "at"}`` (``catalogues.read_name``: null and null for a name that isn't one) or
``{"kept": {names, schema, now, keep_days}, "out": [...]}`` (``catalogues.kept``, sorted).
"""

from datetime import UTC, datetime

from helpers.corpus import VECTORS, check, jsonl

from caracole import catalogues, stamps

MADE_BY = "tests/test_conformance_catalogues.py"


def at(y, m, d, hh=3, mm=12):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def names() -> list[str]:
    good = [catalogues.name_for(17, at(2026, 11, 24)), catalogues.name_for(16, at(2026, 11, 3)),
            catalogues.name_for(1, at(2000, 1, 1, 0, 0)), catalogues.name_for(123, at(2026, 12, 31, 23, 59)),
            catalogues.name_for(17, at(2024, 2, 29)), catalogues.name_for(17, at(2026, 11, 24, 23, 59))]
    for m, last in enumerate([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], 1):
        good.append(catalogues.name_for(17, at(2026, m, last, 23, 59)))
    bad = ["indexes.json", "indexes.json.prev", "indexes-s17-20261124T0312Z.sqlite.gz.next",
           "indexes2-s17-20261124T0312Z.sqlite.gz", "indexes-s17-20261340T0312Z.sqlite.gz",
           "indexes-sx-20261124T0312Z.sqlite.gz", "indexes-s17-20260229T0312Z.sqlite.gz",
           "indexes-s17-20261124T2460Z.sqlite.gz", "indexes-s17-20261124T0312Z.sqlite", "indexes-s-20261124T0312Z.sqlite.gz",
           "indexes-s17-20261124T0312.sqlite.gz", "Indexes-s17-20261124T0312Z.sqlite.gz", ""]
    return good + bad


def test_the_names_corpus():
    records = []
    for name in names():
        named = catalogues.read_name(name)
        records.append({"name": name, "schema": named.schema if named else None,
                        "at": stamps.stamp(named.at) if named else None})
    listed = [catalogues.name_for(17, at(2026, 11, 24)), catalogues.name_for(17, at(2026, 11, 17)),
              catalogues.name_for(17, at(2026, 11, 10)), catalogues.name_for(16, at(2026, 11, 3)),
              catalogues.name_for(15, at(2026, 4, 1)), "indexes.json"]
    cases = [(listed, 17, at(2026, 11, 24), 180), (listed, 17, at(2026, 11, 24), 10), (listed, 18, at(2026, 11, 24), 180),
             (listed[:1], 17, at(2026, 11, 24), 180), (listed[4:5], 17, at(2027, 6, 1), 180), ([], 17, at(2026, 11, 24), 180)]
    for given, schema, now, days in cases:
        out = sorted(catalogues.kept(given, schema=schema, now=now, keep_days=days))
        records.append({"kept": {"names": given, "schema": schema, "now": stamps.stamp(now), "keep_days": days},
                        "out": out})
    check(VECTORS / "catalogues" / "names.jsonl", jsonl(records, corpus="catalogues/names", made_by=MADE_BY))
