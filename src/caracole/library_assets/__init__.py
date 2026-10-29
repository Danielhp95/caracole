"""index.html's stylesheets, scripts and templates (library_page.py), and the ones caracole serve's
own pages share with it (web/pages.py, web/lookup_page.py), as files: real .css, .js and .html, laid
out as viewer/'s are, each read once, at import, and inlined exactly as it is, so a page's
Content-Security-Policy holds the hash of the very text it inlines. Nothing here is served as a
file, and none of it loads anything from the network.

- base.css (``BASE_STYLE``): colours, type and buttons, every page's. ``--border`` is the soft
  line of boxes and dividers; ``--control-edge`` the edge that tells a field, a menu or a box from
  what is around it, at 3:1 or more against every background (WCAG 1.4.11). On a touch screen
  (``pointer: coarse``) every button is a thumb's target, 44 px; a mouse keeps the compact ones.
- picker.css (``PICKER_STYLE``): the picker of a song in review's candidates, under a song's "⋯" and on
  the pages caracole serve writes itself (web/pages.py), which build the same markup.
- steps.css (``STEPS_STYLE``): a request's steps as chips (web/outcome.py's): on index.html the Requests tab's
  running request (requests.js), and a song's line, or a search result's row, while its lookup runs (library.js),
  the same markup.
- rows.css and rows.js (``ROWS_STYLE``, ``ROWS_SCRIPT``): a list's rows and dense lines, the marks
  of where each thing came from and the pages' glyphs (``glyph``: inline SVG, a stroke in the text's colour, made
  with createElementNS), ``caracoleRows``: index.html's songs (``resultRow``'s ``dense`` lines)
  and its search's results, and those of caracole serve's lookup page (web/lookup_page.py), which runs
  rows.js before its own script.
- card.css and card.js (``caracoleCard``): a song of yours opened on index.html, a card under its line (library.js
  ``lineFor`` puts its parts in the line's panel): what you play from it as tiles, each source's versions of each as
  chips that open one drawer under the row of tiles that holds its tile, its progressions, where else to find it, and
  its foot, Remove at its end. Drawn from the page's data alone: a chip or a drawer asks nothing of anyone; what a
  drawer's versions do (Use this one, Fetch them, Back to caracole's pick) library.js makes, served.
- library.css, library-screens.css and library.js: index.html's own. library-screens.css comes
  after rows.css, as its scroll margin and its thumb's targets are a line's too. filter.css, after
  library.css: the toolbar over the songs (body.html's ``.toolbar``: the filters on as tags, then
  Filter, Sort and Select) and the panel Filter opens (``#filter-panel``, a ``<dialog>``: a popover
  from 720 px, a sheet from the bottom on a phone), which library.js fills and opens.
- songbooks.css, select.js and songbooks.js: the Songbooks tab, and the Select mode that makes a songbook.
  select.js runs after library.js: it finds the songs' lines by their song's id (any element of
  ``#list`` with a ``data-id``), puts a box on each and a bar to name the songbook, and builds
  everything with createElement and textContent, as the page does. While it is on, a tap anywhere
  on a line picks it (the stylesheet puts its action and its chevron away, and lets the taps through to
  the line). A line's "Add to a songbook…" turns it on with that song picked ("caracole:pick"). The
  bar is one line: on a phone, "2 selected · Make songbook…", which unfolds the menu and the name
  field. On caracole serve songbooks.js posts the bar's songbook (the server's token, the songs' ids in
  the order picked; its "caracole:sent" says how the server answered: on its way, the picks go and the
  mode ends; refused, the bar says why), and its menu follows the songbooks once a request is over
  ("caracole:songbooks"); on the file on disk it shows the caracole songbook command to run instead,
  folded beside Copy. The Songbooks tab's "+ New songbook" turns it on ("caracole:new-songbook").
  songbooks.js runs after select.js and tabs.js: the Songbooks tab (``book=`` in the address), drawn from the
  data's ``songbooks``
  (songbook_section.py) with createElement and textContent: the songbooks as lines, the one opened as a
  set list. library.js gives it its seam, ``window.caracoleLibrary``: ``track`` follows a job it posted as
  the page's own are, and every job's view is told back ("caracole:job"); ``showLine`` writes a request's
  line.

- tabs.js, before songbooks.js: the page's tabs (body.html's tablist in the masthead: Library, Songbooks and, served,
  Requests, the last), each a ``tab-NAME`` button whose ``aria-controls`` names its panel, ``#tab=NAME`` in the
  address (none for the library); clicked, or with the tablist's keys, a tab shows its panel and hides the others,
  as a link to the page that names a tab does (a request line's Details), and Back to an address that names another.
  Its seam, ``window.caracoleTabs`` (``show``, ``current``), and "caracole:tab", which every tab's script hears: a
  tab put in body.html is one more, with no change to it.
- requests.css and requests.js, after songbooks.js: the Requests tab, on the page caracole serve serves alone (the
  file on disk has neither tab nor panel): every request the server remembers, drawn from ``/requests.json``
  (web/feed.py) with createElement and textContent, asked again while it shows (each request drawn again only
  when it changed, its Output as you left it); its Cancel, Try again and Get it from there post with fetch(), the
  request they queue followed on its song's line (``caracoleLibrary.track``).

- drawn.js: the last script, once every other has drawn what it draws: the page shows. Until then
  library.css keeps it unseen (its body is ``drawing``), so a slow machine that paints it before its
  scripts have run shows nothing that moves once they have (the list empty, the request form open,
  the library shown though you left the Songbooks tab open); two seconds on, it shows all the same.

- head.html, body.html, request.html and requested.html: index.html's skeleton, whose
  ``__BLANKS__`` library_page.py fills in: the policy, the style and, served, the Requests tab and its panel,
  the request form and the songs just requested. body.html also holds the guitar a set list marks a
  song with a Guitar Pro file by (``#guitar-glyph``, an inline SVG in a template songbooks.js clones:
  the HTML parser gives it its namespace).

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
STEPS_STYLE = read("steps.css")
ROWS_STYLE = read("rows.css")
ROWS_SCRIPT = read("rows.js")
