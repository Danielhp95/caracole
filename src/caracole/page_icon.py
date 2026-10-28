"""The mark in the tab of every page caracole writes and serves: an inverted question mark, "¿", as the
book has it.

It is drawn, never written (``mark()`` is the same "¿" for a page's bar): a dot and a hooked stroke, white on caracole's accent in a rounded square, so
it needs no font, reads at 16 px and stands out on a light tab bar and a dark one alike. A page carries it
inline (``LINK``, a ``data:`` URI in its head), so it loads nothing, and its policy allows it with
``img-src data:``. caracole serve answers a browser's own /favicon.ico with ``SVG`` too
(library_routes.py).

Here alone, and with the standard library alone: index.html (library_page.py), the viewer's pages
(viewer/page.py, which lists this file in ``BUILD_FILES``) and caracole serve's (web/pages.py,
web/lookup_page.py) all import it.
"""

from __future__ import annotations

import base64

ACCENT = "#b4441e"  # base.css's --accent, light

_DOT = '<circle cx="16" cy="6.6" r="2.8" fill="{0}"/>'
_HOOK = ('<path d="M16 12.8V15c0 2.4-6 2.9-6 6.9 0 3 2.5 4.6 6 4.6 2.9 0 5.1-1.4 5.8-3.9" fill="none" '
         'stroke="{0}" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"/>')
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    f'<rect width="32" height="32" rx="7" fill="{ACCENT}"/>' + _DOT.format("#fff") + _HOOK.format("#fff") + "</svg>"
)


def mark() -> str:
    """The "¿" alone, for a bar: the icon's dot and hook in the colour of the text around it (``currentColor``, so a
    page's accent colours it, in the dark too), inline in the page, with nothing to load and no style attribute for a
    policy to refuse. Hidden from a screen reader: the name beside it says it."""
    return ('<svg class="mark" viewBox="6 2 20 28" aria-hidden="true" focusable="false">'
            + _DOT.format("currentColor") + _HOOK.format("currentColor") + "</svg>")


DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(SVG.encode("utf-8")).decode("ascii")
LINK = f'<link rel="icon" type="image/svg+xml" href="{DATA_URI}">\n'  # for a page's <head>
