"""index.html's stylesheets, scripts and templates (library_page.py), and the ones caracole serve's
own pages share with it (web/pages.py, web/lookup_page.py), as files: real .css, .js and .html, laid
out as viewer/'s are, each read once, at import, and inlined exactly as it is, so a page's
Content-Security-Policy holds the hash of the very text it inlines. Nothing here is served as a
file, and none of it loads anything from the network.

- base.css (``BASE_STYLE``): colours, type and buttons, every page's. ``--border`` is the soft
  line of cards and dividers; ``--control-edge`` the edge that tells a field, a menu or a box from
  what is around it, at 3:1 or more against every background (WCAG 1.4.11). On a touch screen
  (``pointer: coarse``) every button is a thumb's target, 44 px; a mouse keeps the compact ones.
- picker.css (``PICKER_STYLE``): the picker of a song in review's candidates, on the cards and on
  the pages caracole serve writes itself (web/pages.py), which build the same markup.
- rows.css and rows.js (``ROWS_STYLE``, ``ROWS_SCRIPT``): a list's rows and the marks of where each
  thing came from, ``caracoleRows``: index.html's Rows view, and the results of caracole serve's
  lookup page (web/lookup_page.py), which runs rows.js before its own script.
- library.css, library-screens.css and library.js: index.html's own. library-screens.css comes
  after rows.css, as its scroll margin and its thumb's targets are a row's too.
- songbooks.css and select.js: the Songbooks section, and the Select mode that makes a songbook.
  select.js runs after library.js: it finds the cards by their song's id (any element of ``#list``
  with a ``data-id``: a row too), puts a box on each and a bar to name the songbook, and builds
  everything with createElement and textContent, as the page does. While it is on, a tap anywhere
  on a card picks it (the stylesheet puts its files and actions away, and lets the taps through to
  the card). The bar is one line: on a phone, "2 selected · Make songbook…", which unfolds the menu
  and the name field. On caracole serve the bar posts the songbook (the server's token, the songs'
  ids in the order picked) with library.js's forms (its "caracole:sent" says how the server
  answered: on its way, the picks go and the mode ends; refused, the bar says why), and its menu
  follows the Songbooks section as the page draws it again ("caracole:songbooks"); on the file on
  disk it shows the caracole songbook command to run instead, folded beside Copy.

- head.html, body.html, request.html and requested.html: index.html's skeleton, whose
  ``__BLANKS__`` library_page.py fills in: the policy, the style, the masthead's links, the
  Songbooks section and, served, the request form and the songs just requested.

index.html inlines the stylesheets and the scripts in the order of ``library_page.STYLESHEETS`` and
``library_page.SCRIPTS``, and fills in the templates of ``library_page.TEMPLATES``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

HERE = Path(__file__).parent


@cache
def read(name: str) -> str:
    """A file of this folder, as its bytes say (read as bytes, so no line's end is turned into another),
    read once."""
    return (HERE / name).read_bytes().decode("utf-8")


BASE_STYLE = read("base.css")
PICKER_STYLE = read("picker.css")
ROWS_STYLE = read("rows.css")
ROWS_SCRIPT = read("rows.js")
