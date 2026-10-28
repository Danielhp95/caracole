"""The header of the pages caracole serve writes itself (pages.py's, lookup_page.py's, guitar_page.py's): one line,
the "¿" and the name, which lead home, the page's title after them and its links at the end; ``sub``, a muted line
under it for what the page is of (a song's artist). The library page's bar (library_page.py) is the same line with
its tabs. On a phone the mark alone leads home (base.css's ``.top``).

The standard library alone, as page_icon.py, whose ``mark`` it draws.
"""

from __future__ import annotations

from caracole.page_icon import mark

LIBRARY = '<a class="navlink" href="/">Library</a>'


def top(title: str, links: str = LIBRARY, *, label: str = "Pages", sub: str = "") -> str:
    """The header: ``links``, the page's links as markup (``navlink`` anchors), named ``label`` to a screen reader;
    ``sub``, markup the caller has escaped."""
    return (
        '<header class="top">\n'
        f'  <a class="app" href="/">{mark()}<span class="word">caracole</span></a>\n'
        '  <span class="sep" aria-hidden="true">›</span>\n'
        f"  <h1>{_escape(title)}</h1>\n"
        f'  <nav class="links" aria-label="{_escape(label)}">{links}</nav>\n</header>\n'
        + (f'<p class="top-sub">{sub}</p>\n' if sub else "")
    )


def _escape(text: str) -> str:
    from html import escape

    return escape(text, quote=True)
