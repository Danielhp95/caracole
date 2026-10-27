"""harptabs.com: harmonica tabs caracole keeps for you, for the songs you want.

harptabs.com is the one large free source of harmonica tabs (hole numbers over the lyrics),
and Ultimate Guitar has none. caracole indexes its one sitemap, matches your songs to its
tabs by title, reads a candidate's page for its artist, and keeps the tab of the one by
your song's artist (harptabs_fetch.py). What the site answered on 27 October 2026, asked by
hand with caracole's own user agent (``config.DEFAULT_USER_AGENT``): robots.txt, the sitemap
and two tab pages all answered 200; the sitemap answered 530 once (Cloudflare could not reach
the site: an error, never a block) and 200 a minute later. So caracole asks with its own
user agent, as everywhere else:

- **robots.txt** allows everything but ``/login``, ``/signup``, ``/recover``, ``/settings``,
  ``/submit``, ``/admin/``, ``/messages/``, ``/favorites``, ``/following``, ``/tab/*/edit``,
  ``/tab/*/upload``, ``/api/`` (its API, whose keys are given on request), ``/search`` and
  ``/*?*_rsc=`` (``http.ROBOTS_DISALLOW``), and names the sitemap.
- **The sitemap**, ``SITEMAP_URL``, one file and no index: 6.4 MB of XML (660 KB on the wire),
  with no ETag and no Last-Modified, so each read is a whole one. It lists 27,115 tab pages,
  ``/tab/{id}/{slug}``, the slug the title alone ("piano-man"), never the artist; 10,439
  artist pages, ``/artist/{id}/{slug}`` (a few with no slug, a name in another script); 30
  genres and the site's own pages. Titles repeat: "yesterday" is several tabs, by several
  artists, and one song may have several tabs (the intro, the whole song).
- **A tab page** is server-rendered: the title and the artist in its JSON-LD
  (``MusicComposition``: ``name``, ``composer.name``) and in its header ("by billy joel", a
  link to the artist's page); the harp's key ("Key C", a link to ``/search?key=``), the
  harp's type ("Diatonic", ``/search?harp=``, not on every page), the difficulty, the views
  ("1.1M") and the rating, each a chip; and the tab in the one ``<pre>``, hole numbers ("6",
  blow; "-5", draw) over the lyrics. Its footer: "© Copyright 2004–2026 Harptabs.com · All
  rights reserved."
- **Its terms** (2004) say no one may "use, copy, or distribute any portion of the Web Site",
  and its API's ask not to "bulk-mirror" the corpus. Keeping the tabs of your own wanted
  songs, privately, is the owner's choice (AGENTS.md, Politeness): never a mirror, never a
  tab of a song nobody asked for.

A page without the expected markup is ``HarpTabsParseError``: a provider error, never a miss.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, NamedTuple

from selectolax.lexbor import LexborHTMLParser, LexborNode

from caracole.http import ProviderError
from caracole.normalize import clean_title, slug_key, ug_slug_key

PROVIDER = "harptabs"
HOST = "www.harptabs.com"
BASE_URL = f"https://{HOST}"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

TAB, ARTIST = "tab", "artist"  # the kinds of page the index keeps
# The slugs the sitemap lists are lowercase ASCII letters, digits and hyphens; a URL with anything else
# in it is no page caracole reads, and never lands in a link it writes.
_PAGE = re.compile(r"https://(?:www\.)?harptabs\.com/((tab|artist)/(\d{1,9})/([a-z0-9-]{1,200}))")
_COUNT = re.compile(r"(\d+(?:\.\d+)?)\s*([kKmM]?)")


class HarpTabsParseError(ProviderError):
    """A harptabs.com page without the expected markup: a provider error, never a miss."""

    def __init__(self, message: str, *, url: str | None = None):
        super().__init__(PROVIDER, url=url, message=message)


# --- URLs and the index --------------------------------------------------------------------------


def page_url(path: str) -> str:
    """The address of a page, from its path as the index keeps it (``tab/25/piano-man``)."""
    return f"{BASE_URL}/{path}"


class IndexRow(NamedTuple):
    """One page of the sitemap, as ``harptabs_index`` keeps it: its path, its kind (``TAB`` or ``ARTIST``),
    the site's id and its key: a tab's title's (``title_key``), an artist's name's, as Ultimate Guitar's slugs
    are keyed (``ug_slug_key``)."""

    path: str
    kind: str
    page_id: int
    key: str


def parse_page_url(url: str) -> IndexRow | None:
    """The index row of a tab's or an artist's page; None for any other URL, or a slug without a key."""
    m = _PAGE.fullmatch(url)
    if m is None:
        return None
    path, kind, page_id, slug = m.groups()
    key = ug_slug_key(slug)
    return IndexRow(path, kind, int(page_id), key) if key else None


def title_key(title: str) -> str:
    """The key a song's title meets the tabs' titles with: its version suffixes go first (clean_title)."""
    return slug_key(clean_title(title))


# --- a tab page ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class HarpTab:
    """A tab page: its title and artist as the site writes them, the tab (``body``, the ``<pre>``'s text),
    and its chips: the harp's key ("C"), its type ("Diatonic"), the difficulty, the views and the rating
    (None when the page shows none)."""

    title: str
    artist: str
    body: str
    key: str | None = None
    harp: str | None = None
    difficulty: str | None = None
    views: int = 0
    rating: float | None = None

    def raw(self) -> dict[str, Any]:
        """What a kept tab's version records of it."""
        return {"title": self.title, "artist": self.artist, "key": self.key, "harp": self.harp,
                "difficulty": self.difficulty, "views": self.views, "rating": self.rating}


def _text(node: LexborNode | None) -> str:
    return " ".join((node.text(deep=True) or "").split()) if node is not None else ""


def _composition(tree: LexborHTMLParser) -> dict[str, Any]:
    """The page's JSON-LD ``MusicComposition``, or {}."""
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text(deep=True) or "")
        except (ValueError, RecursionError):
            continue
        if isinstance(data, dict) and data.get("@type") == "MusicComposition":
            return data
    return {}


def _chip(tree: LexborHTMLParser, query: str) -> str | None:
    """The text of the chip that links to ``/search?<query>=``: "Key C", "Diatonic"."""
    node = tree.css_first(f'a[href^="/search?{query}="]')
    return _text(node) or None


def _counted(tree: LexborHTMLParser, icon: str) -> str | None:
    """The text of the chip whose icon is ``icon`` (``lucide-eye``: the views; ``lucide-star``: the rating)."""
    for node in tree.css("li > span"):
        svg = node.css_first("svg")
        if svg is not None and icon in (svg.attributes.get("class") or "").split():
            return _text(node) or None
    return None


def _views(text: str | None) -> int:
    """"1.1M" → 1,100,000; "57k" → 57,000; "974" → 974; 0 for none."""
    m = _COUNT.fullmatch((text or "").replace(",", "").strip())
    if m is None:
        return 0
    n = float(m.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()]
    return int(n) if math.isfinite(n) else 0


def _rating(text: str | None) -> float | None:
    try:
        value = float((text or "").strip())
    except ValueError:
        return None
    return value if math.isfinite(value) and 0 <= value <= 5 else None


def parse_tab_page(html: str | bytes, url: str | None = None) -> HarpTab:
    """A tab page's title, artist, tab and chips; ``HarpTabsParseError`` for a page without a tab or an artist."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = LexborHTMLParser(html)
    pre = tree.css_first('[role="region"][aria-label="Harmonica tab notation"] pre') or tree.css_first("pre")
    body = pre.text(deep=True) if pre is not None else None
    if body is None or not body.strip():
        raise HarpTabsParseError("no tab (<pre>) on the page", url=url)
    work = _composition(tree)
    composer = work.get("composer")
    artist = str(composer.get("name") or "").strip() if isinstance(composer, dict) else ""
    artist = artist or _text(tree.css_first('header a[href^="/artist/"]'))
    title = str(work.get("name") or "").strip() or _text(tree.css_first("header h1"))
    if not artist or not title:
        raise HarpTabsParseError("no title or artist on the page", url=url)
    key = _chip(tree, "key")
    return HarpTab(
        title=title, artist=artist, body=body.strip("\n") + "\n",
        key=key.removeprefix("Key").strip() or None if key else None,
        harp=_chip(tree, "harp"), difficulty=_chip(tree, "difficulty"),
        views=_views(_counted(tree, "lucide-eye")), rating=_rating(_counted(tree, "lucide-star")),
    )
