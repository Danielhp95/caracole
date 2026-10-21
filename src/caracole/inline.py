"""What a page caracole writes holds inline: a script or a stylesheet its Content-Security-Policy
allows by its hash, and a block of data for its script.

The standard library alone, so a page imports it at no cost: sheet.html's and songbook.html's
builders (viewer/page.py and viewer/book.py, whose ``BUILD_FILES`` list this file), index.html's
(library_page.py) and those of caracole serve's own pages (web/lookup_page.py, web/pages.py).
"""

from __future__ import annotations

import base64
import hashlib
import json
from html import escape
from typing import Any


def sha256_source(text: str) -> str:
    """A CSP source allowing exactly this inline script or stylesheet."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def json_block(element_id: str, data: Any) -> str:
    """``data`` as a ``<script type="application/json">`` block with this id, and a line break.

    Every ``<`` in the JSON is written ``\\u003c``, which JSON reads back as ``<``: no text in it, a
    song's title of ``</script>`` or ``<!--`` among them, can end the block or open another element.
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'<script type="application/json" id="{escape(element_id)}">{payload}</script>\n'
