"""The HTML5 named character references, for the phone: tests/conformance/data/caracole/html/entities.json, Python's
``html.entities.html5`` (what ``html.unescape`` reads) in its own order, which the phone's ``core.py.PyHtml`` and
``core.html``'s tokenizer read (docs/superpowers/specs/2026-11-03-html-parsing.md).

Its format: ``{"entities": [[name, text], …]}``, a pair a line: each name as the table has it (with its ``;``, or without for the
legacy references the table also lists bare, ``amp`` beside ``amp;``), and the text it stands for (one or two code
points).
"""

import html.entities
import json

from helpers.corpus import DATA, check

ENTITIES = DATA / "html" / "entities.json"


def entities_json() -> str:
    rows = (json.dumps([name, text], ensure_ascii=False) for name, text in html.entities.html5.items())
    return '{"entities": [\n' + ",\n".join(rows) + "\n]}\n"


def test_entities_json_is_pythons_html5_table():
    check(ENTITIES, entities_json())


def test_the_table_holds_the_legacy_names_bare_and_every_name_once():
    names = [name for name, _ in json.loads(entities_json())["entities"]]
    assert len(names) == len(set(names)) == len(html.entities.html5)
    assert {"amp", "amp;", "AMP", "lt", "lt;", "nbsp", "nbsp;"} <= set(names)
    assert html.entities.html5["NotEqualTilde;"] == "≂̸"  # two code points
