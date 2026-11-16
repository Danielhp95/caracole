"""caracole's mark, its logo (docs/logo/caracole_icon.png) drawn in SVG: in the tab of every page caracole writes and
serves, and at the start of the bar of every page that has one.

It is drawn, never an image: the master's black and its copper, each traced into one path (docs/logo/trace.py) in a
square of ``SIDE``.

- ``SVG``, the tab's icon: the drawing on the master's cream in a rounded square, so it stands out on a light tab bar
  and a dark one alike. A page carries it inline (``LINK``, a ``data:`` URI in its head), so it loads nothing, and its
  policy allows it with ``img-src data:``. caracole serve answers a browser's own /favicon.ico with ``SVG`` too
  (library_routes.py).
- ``mark()``, the bar's: the drawing alone, its black in the colour of the text around it and its copper the
  master's.
- ``icon()``, the tab's icon in other colours: library_name.py's, for a library with a badge.

Here alone, and with the standard library alone: index.html (library_page.py), the viewer's pages
(viewer/page.py, which lists this file in ``BUILD_FILES``) and caracole serve's (web/pages.py,
web/lookup_page.py) all import it.
"""

from __future__ import annotations

import base64

CREAM = "#f6e9db"  # the master's colours, read off it
BLACK = "#242322"
COPPER = "#af6233"
SIDE = 640  # the square the drawing is in, which fills 95 % of its height
MARK_BOX = "118 16 404 608"  # the drawing's own box in it: the bar's mark

_BLACK = (
    "M476 17c-11 7-2 22 9 17 9-4 5-18-5-18-1 0-3 1-4 1zM494 43c-3 2-5 5-5 9 1 13 19 12 19 0 0-6-4-10-9-10-1 0-3 1-5 1"
    "zM422 44c-17 4-28 24-22 38 1 3 1 2 0-1-6-17 17-36 34-27 22 10 23 43 3 89-2 5-7 17-11 27-33 83-61 119-139 178-56"
    " 42-75 68-79 108-1 9 1 30 3 32 0 0 0-6 0-13 0-47 20-77 83-125 69-52 97-87 129-162 4-10 8-18 18-37 10-20 15-31"
    " 18-42 10-37-10-71-37-65"
    "zM502 73c-6 4-7 13 0 17 2 1 7 1 9 0 11-7 2-22-9-17zM499 104c-6 3-6 13 1 17 8 4 16-5 13-13-2-4-9-6-14-4zM423 118"
    "c-15 61-57 124-116 176-9 9-22 20-25 22-5 5 2 0 15-10 52-39 91-89 114-147 6-15 13-36 14-45 1-5 0-4-2 4zM429 132"
    "c-24 81-68 142-143 196-46 33-62 48-77 71-28 43-25 96 7 134 5 6 12 13 10 10-24-36-30-82-17-118 12-33 30-53 80-92"
    " 44-34 66-56 88-87 23-32 42-73 52-111 3-12 3-14 0-3"
    "zM489 133c-8 5-5 18 4 18 6 0 10-4 10-10 0-7-7-11-14-8zM473 160c-5 3-6 10-2 15 4 3 10 3 13 0 8-8-2-20-11-15"
    "zM456 186c-2 1-4 6-4 9 2 7 11 10 16 5 8-8-2-20-12-14zM298 209c17 7 4 43-29 82l-6 7 4-3c28-23 45-48 45-69"
    " 0-12-4-18-13-17-3 0-3 0-1 0"
    "zM442 215c-11 25-28 55-41 71-23 29-42 44-94 75-40 25-61 45-72 70-18 39 3 79 42 82 25 1 50-19 51-43 1-4 1-4"
    " 0-1-3 13-14 26-28 31-36 13-68-20-56-57 9-24 27-42 75-71 76-46 105-81 123-153 4-12 3-13 0-4"
    "zM192 273c-24 25-42 45-57 63-6 8-17 22-16 22 0 0 3-1 6-2 8-3 23-8 23-8 0 1 0 5 0 10-3 28 0 61 6 83 2 6 8 21 8"
    " 21 0 0 0-4-1-8-4-33 7-66 29-94"
    "l4-5 0-4c0-2 1-16 2-30 2-33 2-30-1-27-1 2-8 9-15 17-7 7-13 14-13 14 0 1-2 28-3 46 0 9 0 11-2 14-1 2-2 6-3 10-1"
    " 3-2 6-3 5 0 0 0-32 1-48 0-9 1-16 1-16-1-1-11 3-14 4-1 1-1 1-1 1 0-2 27-33 52-58"
    "l10-11 2 5c4 10 13 20 21 25 4 3 5 2-3 8-6 5-14 13-20 19l-3 4 0 6 0 6 4-5c8-10 26-27 38-35 3-2 4-3 2-3 0"
    " 0-3-1-6-2-15-7-26-20-30-37-1-3-2-6-2-6 0 0-7 7-16 16"
    "zM189 313c0 1-1 14-2 33 0 4-1 4-5 10-2 3-6 7-7 9-2 3-3 5-4 5 0 0 1-6 1-12 1-7 1-16 1-21l1-8 2-3c5-5 12-14 12-14"
    " 0 0 1-1 1-1 0 0 1 1 0 2"
    "zM448 300c-18 26-44 47-80 65l-12 7 4 1c36 10 55 46 48 94-2 14 21-51 29-83 5-17 12-59 12-60-1-1-2 2-4 5-14 20-31"
    " 35-51 43"
    "l-6 2-6-2c-4-1-7-2-7-2 0 0 2-1 5-2 32-13 69-47 71-66 1-7 1-7-3-2zM431 369c-2 11-6 24-11 43-1 4-2 6-2 4"
    " 0-7-10-25-18-32-3-3-3-4-2-4 5 0 23-12 32-20 2-2 4-4 4-4 0 0-1 6-3 13"
    "zM323 389c-8 4-15 7-14 7 0 0 1 0 4 0 41-7 73 27 69 72-2 22-11 49-23 68-3 4-3 4 3-1 55-58"
    " 46-140-17-153-7-1-7-1-22 7"
    "zM311 406c-11 1-23 7-31 15l-4 3 4-2c36-18 76 10 73 51-4 59-74 83-114 40-6-7-9-11-16-25-1-3 0 13 1 21 5 20 13 36"
    " 33 58 17 20 27 35 32 51"
    "l2 6 2-7c6-17 15-31 38-62 30-41 39-60 39-89-1-39-25-63-59-60zM268 548c17 5 35 3 51-5 7-3 7-3 3 1-10 12-20 27-26"
    " 40-5 10-5 10-7 5-4-9-10-17-24-32-9-11-13-16-13-16 0-1 3 1 6 2 3 2 8 4 10 5"
    "z"
)
_COPPER = (
    "M425 30c-22 5-38 31-30 51 1 3 1 1 0-4-2-16 9-33 25-37 25-6 46 14 48 45 0 18-5 37-20 65-12 20-17 31-24 49-19"
    " 50-35 76-65 107-16 15-50 43-64 52-1 1-2 1-1 1 1 1 28-16 41-25 42-30 70-64 93-114 4-7 8-18 11-23 5-11 10-20"
    " 20-35 19-28 26-44 28-66 4-42-26-73-62-66"
    "zM392 64c-3 4-2 18 1 24 8 14 29 10 29-6 0-11-13-16-18-7-6 8 3 18 12 13 1-1 1-1 0 0-9 12-24 0-24-18 1-6 1-7 0-6"
    "zM291 183c-6 3-8 12-5 17 7 10 22 5 21-7-1-8-9-13-16-10zM282 201c-2 6 6 12 15 11 6-1 4-2-4-4-4"
    " 0-7-2-9-6-1-3-2-3-2-1"
    "zM315 216c2 6 2 19 0 26-7 21-19 36-56 66-30 25-48 44-61 64-33 49-33 103-1 145 7 10 9 10 3 2-12-19-20-49-19-71"
    " 3-43 24-76 77-119 17-14 19-16 27-23 30-27 43-64 31-89-2-5-3-5-1-1"
    "zM458 286l-6 9-1 9c-2 19-3 24-5 34-6 41-21 94-35 125-2 5-1 4 6-6 26-39 42-96 47-168 1-14 1-14-6-3zM205 287"
    "c0 4-2 39-2 42-1 4 0 3 6-3 5-7 10-11 18-17 6-5 6-5 0-5-6 0-13-6-18-15-3-4-4-5-4-2zM218 306c1 0 2 1 0 1-1 0-3"
    " 1-3 1-1 0-1 0-2-2 0-1-1-3-1-4 0 0 1 0 2 2 1 1 3 2 4 2"
    "zM188 312c0 0-7 9-12 14l-2 3-1 8c0 5 0 14-1 21 0 6-1 12-1 12 1 0 2-2 4-5 1-2 5-6 7-9 4-6 5-6 5-10 1-19 2-32"
    " 2-33 1-1 0-2 0-2 0 0-1 1-1 1"
    "zM430 360c-9 8-27 20-32 20-1 0-1 1 2 4 8 7 18 25 18 32 0 2 1 0 2-4 8-27 14-55 14-56 0 0-2 2-4 4zM423 375"
    "c0 1-2 4-3 6-1 3-3 5-3 5 0 0-2-1-5-2l-4-1 4-1c4-1 5-1 9-6 4-4 4-4 2-1zM305 430c0 0 1 1 3 3 16 15 8 45-15 53-27"
    " 8-50-16-41-43 2-5 1-6-1-1-11 23 1 50 24 58 38 12 71-36 43-63-4-4-13-9-13-7"
    "zM341 467c0 27-27 57-52 57-1 0-2 0-3 1 0 0 2 0 7 0 24 0 44-16 49-40 1-5 1-19 0-20 0-1-1 0-1 2zM319 543c-16 8-36"
    " 10-50 5-6-2-7-2-2 1 8 5 19 17 23 26 2 3 2 3 6-3 3-6 15-18 22-25 8-6 8-7 1-4"
    "z"
)


def icon(background: str = CREAM, black: str = BLACK, copper: str = COPPER) -> str:
    """The drawing in a rounded square of ``background``, its black and its copper in those colours."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIDE} {SIDE}">'
            f'<rect width="{SIDE}" height="{SIDE}" rx="{SIDE * 7 // 32}" fill="{background}"/>'
            f'<path fill="{black}" d="{_BLACK}"/><path fill="{copper}" d="{_COPPER}"/></svg>')


SVG = icon()


def mark() -> str:
    """The drawing alone, for a bar: its black in the colour of the text around it (``currentColor``, which base.css
    sets to the text's, so it reads in the dark too), its copper the master's, inline in the page, with nothing to load
    and no style attribute for a policy to refuse. Hidden from a screen reader: the name beside it says it."""
    return (f'<svg class="mark" viewBox="{MARK_BOX}" aria-hidden="true" focusable="false">'
            f'<path fill="currentColor" d="{_BLACK}"/><path fill="{COPPER}" d="{_COPPER}"/></svg>')


def data_uri(svg: str) -> str:
    """``svg`` as a ``data:`` URI, for a page's head."""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def link(svg: str) -> str:
    """The ``<link rel="icon">`` of ``svg``, for a page's head."""
    return f'<link rel="icon" type="image/svg+xml" href="{data_uri(svg)}">\n'


DATA_URI = data_uri(SVG)
LINK = link(SVG)  # for a page's <head>
