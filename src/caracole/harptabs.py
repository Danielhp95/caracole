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
  link to the artist's page). A tab of no known artist (tabs 28841 and 29910) has no
  ``composer``, and its header says "by Unknown", linking nowhere: a page of no artist, never
  one that won't parse. Its chips: a key ("Key C", a link to ``/search?key=``), the song's on
  some tabs and the harp's on others (Juke's says E, its notes "I use an A harp"), the
  harp's type ("Diatonic", ``/search?harp=``, not on every page), the difficulty, the views
  ("1.1M") and the rating; and the tab in the one ``<pre>``, hole numbers ("6",
  blow; "-5", draw) over the lyrics. Its footer: "© Copyright 2004–2026 Harptabs.com · All
  rights reserved."
- **An artist page** (``/artist/{id}/{slug}``, which robots.txt allows) is server-rendered too: the
  name as the site spells it ("billy joel") in its ``<h1>``, how many tabs the artist has ("98
  tabs") under it, and a card a tab: its page and title, the key ("Key C") and a genre
  ("Rock"), either, both or neither, the views ("1.1M"), the rating (on rated tabs alone) and
  the difficulty (not on every card). It renders the first
  ``PAGE_TABS`` (30) of them, the most viewed first; the rest come from ``/api/artist/{id}/tabs``
  as the visitor scrolls, which robots.txt closes, so caracole knows an artist's 30 most viewed
  tabs and how many they have. The sitemap names one artist page with no slug, ``/artist/4``:
  the site's catch-all, "?", tabs of no known artist (no row of the index).
- **Its terms** (2004) say no one may "use, copy, or distribute any portion of the Web Site",
  and its API's ask not to "bulk-mirror" the corpus. Keeping the tabs of your own wanted
  songs, privately, is the owner's choice (AGENTS.md, Politeness): never a mirror, never a
  tab of a song nobody asked for. Its artist pages are read for the names of their tabs
  alone (harptabs_index.py), so that a search finds them as Ultimate Guitar's index does.

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
from caracole.normalize import clean_title, identity_key, placeholder_artist, romanize, slug_key, ug_slug_key

PROVIDER = "harptabs"
HOST = "www.harptabs.com"
BASE_URL = f"https://{HOST}"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

TAB, ARTIST = "tab", "artist"  # the kinds of page the index keeps
PAGE_TABS = 30  # the tabs an artist page renders, the most viewed first; the rest are its API's (robots.txt closes it)
# The slugs the sitemap lists are lowercase ASCII letters, digits and hyphens; a URL with anything else
# in it is no page caracole reads, and never lands in a link it writes.
_PAGE = re.compile(r"https://(?:www\.)?harptabs\.com/((tab|artist)/(\d{1,9})/([a-z0-9-]{1,200}))")
_COUNT = re.compile(r"(\d+(?:\.\d+)?)\s*([kKmM]?)")
_TAB_PATH = re.compile(r"/(tab/(\d{1,9})/[a-z0-9-]{1,200})")  # a card's link: a tab's page, as the sitemap lists it
_TABS_SAID = re.compile(r"([\d,]+)\s+tabs?")  # an artist page's header: "98 tabs", "1 tab"
_BRACKETED = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")  # a part of a title in brackets, the innermost first
_APOSTROPHE = re.compile(r"['’ʼ]")  # which a slug writes as nothing ("dont") or as a hyphen ("don-t")


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


def title_keys(title: str) -> list[str]:
    """The keys a song's title meets the sitemap's slugs with: ``title_key``'s, and for a title with an apostrophe,
    the key of the slug that writes it as a hyphen, as harptabs.com slugs most of its later tabs
    ("you-ain-t-goin-nowhere", "can-t-help-falling-in-love"; earlier ones, "knockin-on-heavens-door")."""
    return [key for key in dict.fromkeys((title_key(title), title_key(_APOSTROPHE.sub(" ", title)))) if key]


def song_title(title: str) -> str:
    """The song a tab's title names: the title less what it says in brackets, which is the tab's own
    ("Piano Man (C Harmonica)", "((((Piano Man (Harmonica Intro)" and "(harmonica riff) piano man" are
    Piano Man), a bracket left open gone too; the title as it is when nothing else is left."""
    text, before = title, None
    while text != before:
        before, text = text, _BRACKETED.sub(" ", text)
    text = " ".join(re.sub(r"[()\[\]]", " ", text).split())
    return text if any(c.isalnum() for c in text) else title.strip()


def song_key(title: str) -> str:
    """The title part of the identity key of the song a tab's title names (``song_title``), Chinese in
    pinyin: the tabs of one song by one artist share it, as their search line does."""
    return identity_key("", romanize(song_title(title))).partition("/")[2]


# --- a tab page ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class HarpTab:
    """A tab page: its title and artist as the site writes them (``artist`` None for a tab of no known artist,
    "by Unknown"), the tab (``body``, the ``<pre>``'s text), and its chips: the key ("C": the song's or the
    harp's, the page doesn't say), the harp's type ("Diatonic"), the difficulty, the views and the rating (None when the page shows none)."""

    title: str
    artist: str | None
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


def _by_line(tree: LexborHTMLParser) -> str:
    """The artist the header's line under the title names ("by Unknown · posted by …"): its first element's
    text, a link to the artist's page or not; "" with no such line."""
    line = tree.css_first("header h1 + p")
    if line is None or not _text(line).startswith("by "):
        return ""
    return next((_text(node) for node in line.iter() if node.tag in ("a", "span")), "")


def _pre_text(pre: LexborNode) -> str:
    """The tab's ``<pre>`` as its lines show: a ``<br>`` breaks a line, and so does the end of a line its site's
    editor writes as a ``<p>`` (or a ``<div>``) where no line break follows it in the page."""
    for node in pre.css("br"):
        node.replace_with("\n")
    for node in pre.css("p, div"):
        after = node.next
        if after is not None and not (after.is_text_node and (after.text_content or "").startswith("\n")):
            node.insert_after("\n")
    return pre.text(deep=True)


def parse_tab_page(html: str | bytes, url: str | None = None) -> HarpTab:
    """A tab page's title, artist, tab and chips; ``HarpTabsParseError`` for a page without a tab, a title, or an
    artist named. A page that names the site's catch-all ("Unknown", "?": ``normalize.placeholder_artist``) is of
    no artist: ``artist`` None."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = LexborHTMLParser(html)
    pre = tree.css_first('[role="region"][aria-label="Harmonica tab notation"] pre') or tree.css_first("pre")
    body = _pre_text(pre) if pre is not None else None
    if body is None or not body.strip():
        raise HarpTabsParseError("no tab (<pre>) on the page", url=url)
    work = _composition(tree)
    composer = work.get("composer")
    artist = str(composer.get("name") or "").strip() if isinstance(composer, dict) else ""
    artist = artist or _text(tree.css_first('header a[href^="/artist/"]')) or _by_line(tree)
    title = str(work.get("name") or "").strip() or _text(tree.css_first("header h1"))
    if not artist or not title:
        raise HarpTabsParseError("no title or artist on the page", url=url)
    key = _chip(tree, "key")
    return HarpTab(
        title=title, artist=None if placeholder_artist(artist) else artist, body=body.strip("\n") + "\n",
        key=key.removeprefix("Key").strip() or None if key else None,
        harp=_chip(tree, "harp"), difficulty=_chip(tree, "difficulty"),
        views=_views(_counted(tree, "lucide-eye")), rating=_rating(_counted(tree, "lucide-star")),
    )


# --- an artist page ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ListedTab:
    """A tab an artist page lists: the site's id, its page's path (``tab/25/piano-man``), its title as
    the card writes it, and its chips (None, or 0 for the views, when the card shows none)."""

    tab_id: int
    path: str
    title: str
    key: str | None = None
    difficulty: str | None = None
    views: int = 0
    rating: float | None = None


@dataclass(frozen=True)
class ArtistPage:
    """An artist page: the name as the page heads it, how many tabs it says the artist has (``tabs``),
    and the tabs it lists (``listed``: the first ``PAGE_TABS``, the most viewed first)."""

    name: str
    tabs: int
    listed: tuple[ListedTab, ...] = ()


def _card_chip(card: LexborNode, icon: str) -> str | None:
    """The text of a card's chip whose icon is ``icon`` (``lucide-eye``, ``lucide-star``)."""
    for node in card.css("span"):
        svg = node.css_first("svg")
        if svg is not None and icon in (svg.attributes.get("class") or "").split():
            return _text(node) or None
    return None


def _card(card: LexborNode) -> ListedTab | None:
    """A card's tab, or None for one that links to no tab page."""
    link = card.css_first('h3 a[href^="/tab/"]')
    found = _TAB_PATH.fullmatch(link.attributes.get("href") or "") if link is not None else None
    title = _text(link)
    if found is None or not title:
        return None
    line = card.css_first("h3 + p")
    said = [_text(span) for span in line.css("span")] if line is not None else []
    key = next((s.removeprefix("Key").strip() for s in said if s.startswith("Key ")), None)
    difficulty = card.css_first('span[class*="text-diff-"]')
    return ListedTab(int(found.group(2)), found.group(1), title, key=key or None,
                     difficulty=_text(difficulty) or None, views=_views(_card_chip(card, "lucide-eye")),
                     rating=_rating(_card_chip(card, "lucide-star")))


def parse_artist_page(html: str | bytes, url: str | None = None) -> ArtistPage:
    """An artist page's name, the tabs it says they have and those it lists; ``HarpTabsParseError`` for a page
    without its header (the name in its ``<h1>``), or one that says they have tabs and lists none caracole can
    read (its cards changed, say: never an artist without tabs)."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = LexborHTMLParser(html)
    name = _text(tree.css_first("main header h1"))
    if not name:
        raise HarpTabsParseError("no artist's name (main header h1) on the page", url=url)
    listed = tuple(tab for card in tree.css("main div.group") if (tab := _card(card)) is not None)
    said = _TABS_SAID.search(_text(tree.css_first("main header p")))
    tabs = int(said.group(1).replace(",", "")) if said is not None else len(listed)
    if tabs and not listed:  # its cards changed, say: no tab read is no artist without tabs
        raise HarpTabsParseError(f"the page says {tabs} tabs and lists none caracole can read", url=url)
    return ArtistPage(name, max(tabs, len(listed)), tuple(dict((t.tab_id, t) for t in listed).values()))
