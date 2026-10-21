"""caracole.inline: what a page caracole writes holds inline, a script or stylesheet allowed by its
hash and a block of data its script reads."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from html.parser import HTMLParser

from caracole.inline import json_block, sha256_source


def test_a_source_allows_exactly_that_text():
    script = "document.title = 'é';\n"
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
    assert sha256_source(script) == f"'sha256-{digest}'"
    assert sha256_source(script + " ") != sha256_source(script)


class _Elements(HTMLParser):
    """What a browser's parser makes of a page: each element's start tag and the text it holds."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, dict, str]] = []

    def handle_starttag(self, tag, attrs):
        self.found.append((tag, dict(attrs), ""))

    def handle_data(self, data):
        if self.found:
            tag, attrs, text = self.found[-1]
            self.found[-1] = (tag, attrs, text + data)


def test_a_script_end_in_a_title_stays_inside_the_block():
    data = {"title": "</script><script>alert(1)</script>", "other": "<!-- <b> 斑马 &  ",
            "list": [1, None, True]}
    block = json_block("song", data)
    assert block.endswith("</script>\n") and block.count("</script>") == 1
    assert "<" not in block[len('<script type="application/json" id="song">'):-len("</script>\n")]
    parser = _Elements()
    parser.feed("<body>" + block + "<p>after</p></body>")
    parser.close()
    tags = [(tag, attrs) for tag, attrs, _ in parser.found]
    assert tags == [("body", {}), ("script", {"type": "application/json", "id": "song"}), ("p", {})]
    assert json.loads(parser.found[1][2]) == data  # every character as it was, unescaped by JSON alone


def test_a_block_is_compact_and_keeps_its_text_as_written():
    block = json_block("data-3", {"a": "斑马", "b": [1, 2]})
    assert block == '<script type="application/json" id="data-3">{"a":"斑马","b":[1,2]}</script>\n'


def test_the_blocks_name_is_an_attribute_and_nothing_more():
    block = json_block('x" onload="alert(1)', {})
    assert re.fullmatch(r'<script type="application/json" id="[^"]*">\{\}</script>\n', block)
