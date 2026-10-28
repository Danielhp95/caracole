"""gametabs.net: text tabs of video game music caracole keeps for you, for the songs you want.

gametabs.net is the large free site of guitar (and bass) tabs of game music, with some anime, film and TV
music: about 8,550 tabs of 1,620 games on 28 October 2026. It files a tab under a game and a track, with its
composers, never a performing artist: a wanted.txt line meets it when its artist is the game ("Hollow Knight -
Resting Grounds") or the composer ("Yuzo Koshiro - Fillmore"). caracole indexes its sitemaps, reads its game
pages for each tab's composers and instruments (gametabs_index.py), matches your songs to its tabs by title, game
and composer, and keeps the text tab of the best (gametabs_fetch.py). What the site answered on 28 October 2026,
asked by hand with caracole's own user agent (``config.DEFAULT_USER_AGENT``): robots.txt, the sitemap index, its
first child, three game pages and two tab pages, all 200, from a plain nginx (no Cloudflare, no challenge):

- **robots.txt** gives its ``User-agent: *`` group ``Crawl-delay: 5`` (``http.ROBOTS_CRAWL_DELAY``) and closes
  ``/api/``, ``/admin/``, ``/*.log$``, ``/*.php$``, the pages behind a login (``/preparing-tab-file-download``,
  every attachment's download, among them), the filters ``/tabs?*``, ``/login?*`` and ``/create-account?*``, and
  retired paths (``http.ROBOTS_DISALLOW``); it names the sitemap index, and closes the whole site to the AI
  crawlers' own user agents (GPTBot, ClaudeBot, CCBot…), which caracole's is not.
- **The sitemaps**: an index, ``SITEMAP_URL``, of seven gzipped children, regenerated daily, with ETags:
  ``sitemap_static`` (the site's own pages, never read) and ``sitemap_1`` to ``sitemap_6`` (``sitemap_child``), of
  5,000 URLs at most. The first lists the top tabs, the A–Z lists of games, every game's page (``/tabs/<game>``,
  1,625, and ``/tabs/<game>?page=N`` for the 33 pages after a first), then the tabs in the order of their paths,
  ``/tabs/<game>/<tab>``, its slug the track's title alone; the next ones the rest of the tabs. A slug that repeats
  takes a number, across the whole site ("main-theme-108", the 108th "Main Theme"; "resting-grounds-2", the second
  "Resting Grounds"): one more tab of a title, never part of it (``IndexRow.key``), though a title may end in a
  number of its own ("Green Hill Zone Act 2", ``IndexRow.slug_key``).
- **A game page** (``/tabs/<game>``) is server-rendered: the game's name in its ``<h1>``, "Tabs: 240", and a card
  a tab, 50 a page (the rest at ``?page=2``…, which the sitemap lists and robots.txt allows): its page, "<track> -
  <game>", the platform, the instruments ("Guitar", "Guitar, Bass", "Ukulele"), the styles, "Composer: Yuzo
  Koshiro" (not on every card), "Tabber: @…", the fun rating and the views ("Views 11.2k"). Its shuffle dialog
  lists the site's instruments and styles by name (``data-prepopulated-instruments``), which tell a card's
  instruments from its styles (``parse_game_page``).
- **A tab page** serves its whole text tab to anyone, in ``<pre id="tab-text-view-text">``, and says what it is
  three ways: a ``data-tab`` JSON on ``#tab-page-wrapper`` (its id, name, slug, game, instruments, styles,
  composers, tabber, views, ratings and dates), schema.org microdata (a ``MusicRecording`` in a ``MusicAlbum``, the
  game, its composers under ``recordingOf``), and its heading and details (the tuning, there alone). Its files
  (Guitar Pro, MIDI, PDF) are behind a login, "(Log in to download files)": never caracole's.
- **Its terms** (updated 25 May 2026) forbid "Using automated means (bots, scrapers, etc.) to access or collect
  data from the Service without Our express written permission". Reading it anyway, on these rules, is the
  owner's choice (AGENTS.md, Politeness): the text tabs of your wanted songs, privately, never a mirror.

A page without the expected markup is ``GameTabsParseError``: a provider error, never a miss.
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

PROVIDER = "gametabs"
HOST = "gametabs.net"
BASE_URL = f"https://{HOST}"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

TAB, GAME = "tab", "game"  # the kinds of page the index keeps
PAGE_TABS = 50  # the tabs a game page lists; the rest on its next pages
# The site's instruments, as its shuffle dialog names them on 28 October 2026: what a card's instruments are told
# from its styles by, for a page that doesn't name them.
INSTRUMENTS = ("Guitar", "Bass", "Mandolin", "Banjo", "Ukulele")
# The slugs the sitemaps list are lowercase ASCII letters, digits and hyphens; a URL with anything else in it is no
# page caracole reads, and never lands in a link it writes.
_PAGE = re.compile(r"https://(?:www\.)?gametabs\.net/(tabs/([a-z0-9-]{1,200})(?:/([a-z0-9-]{1,200})|\?page=([1-9][0-9]{0,3}))?)")
_CHILD = re.compile(r"https://(?:www\.)?gametabs\.net/(sitemap_[1-9][0-9]{0,2})\.xml(?:\.gz)?")
_REPEAT = re.compile(r"-[0-9]{1,5}$")  # a slug's number: one more tab of a title the site has
_TAB_HREF = re.compile(r"https://(?:www\.)?gametabs\.net/(tabs/[a-z0-9-]{1,200}/[a-z0-9-]{1,200})/?")
_COUNT = re.compile(r"(\d+(?:\.\d+)?)\s*([kKmM]?)")
_SAID = re.compile(r"Tabs:\s*([\d,]+)")
_RATING = re.compile(r"(\d+(?:\.\d+)?) average fun rating")


class GameTabsParseError(ProviderError):
    """A gametabs.net page without the expected markup: a provider error, never a miss."""

    def __init__(self, message: str, *, url: str | None = None):
        super().__init__(PROVIDER, url=url, message=message)


# --- URLs and the index --------------------------------------------------------------------------------------------


def page_url(path: str) -> str:
    """The address of a page, from its path as the index keeps it (``tabs/actraiser/fillmore``)."""
    return f"{BASE_URL}/{path}"


def sitemap_child(url: str) -> str | None:
    """The name of a child sitemap the index lists that may list tabs (``sitemap_1``); None for the static one, which
    lists the site's own pages, and any other URL."""
    m = _CHILD.fullmatch(url)
    return m.group(1) if m else None


class IndexRow(NamedTuple):
    """One page of the sitemaps, as ``gametabs_index`` keeps it: its path, its kind (``TAB`` or ``GAME``), the game's
    slug, a tab's own slug ("" for a game page), a game page's number (1 for its first; 0 for a tab), and its keys, as
    Ultimate Guitar's slugs are keyed (``ug_slug_key``): a tab's title's, the slug less its number (``key``), and its
    whole slug's (``slug_key``, a title that ends in a number); a game page's, the game's slug's, both."""

    path: str
    kind: str
    game: str
    slug: str
    page: int
    key: str
    slug_key: str


def parse_page_url(url: str) -> IndexRow | None:
    """The index row of a game's page (or one of its next pages) or a tab's; None for any other URL, or a slug
    without a key."""
    m = _PAGE.fullmatch(url)
    if m is None:
        return None
    path, game, slug, page = m.groups()
    if slug is None:
        key = ug_slug_key(game)
        return IndexRow(path, GAME, game, "", int(page or 1), key, key) if key else None
    whole = ug_slug_key(slug)
    key = ug_slug_key(_REPEAT.sub("", slug)) or whole
    return IndexRow(path, TAB, game, slug, 0, key, whole) if whole else None


def title_key(title: str) -> str:
    """The key a song's title meets the tabs' titles with: its version suffixes go first (clean_title)."""
    return slug_key(clean_title(title))


# --- a tab page ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GameTab:
    """A tab page: the site's id of it (None when its page doesn't say), the track's title, the game's name and slug,
    the tab's own slug, the tab (``body``, the ``<pre>``'s text), and what the page says of it."""

    tab_id: int | None
    title: str
    game: str
    game_slug: str
    slug: str
    body: str
    composers: tuple[str, ...] = ()
    instruments: tuple[str, ...] = ()
    styles: tuple[str, ...] = ()
    tuning: str | None = None
    tabber: str | None = None
    views: int = 0
    rating: float | None = None
    ratings: int = 0
    created: str | None = None

    def raw(self) -> dict[str, Any]:
        """What a kept tab's version records of it."""
        return {"id": self.tab_id, "title": self.title, "game": self.game, "composers": list(self.composers),
                "instruments": list(self.instruments), "styles": list(self.styles), "tuning": self.tuning,
                "tabber": self.tabber, "views": self.views, "rating": self.rating, "ratings": self.ratings,
                "created": self.created}


def _text(node: LexborNode | None) -> str:
    return " ".join((node.text(deep=True) or "").split()) if node is not None else ""


def _names(items: Any) -> tuple[str, ...]:
    """The ``name`` of each of a JSON list's objects."""
    if not isinstance(items, list):
        return ()
    return tuple(name for i in items if isinstance(i, dict) and (name := " ".join(str(i.get("name") or "").split())))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _data_tab(wrapper: LexborNode | None) -> dict[str, Any]:
    """The page's ``data-tab`` JSON, or {}."""
    text = wrapper.attributes.get("data-tab") if wrapper is not None else None
    try:
        data = json.loads(text or "")
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _meta(node: LexborNode | None, prop: str) -> str:
    found = node.css_first(f'meta[itemprop="{prop}"]') if node is not None else None
    return " ".join((found.attributes.get("content") or "").split()) if found is not None else ""


def _details(tree: LexborHTMLParser) -> dict[str, str]:
    """The heading's details, "Tuning: EADGBE", by their label."""
    found = {}
    for p in tree.css(".tab-page-grid-details p"):
        label, sep, value = _text(p).partition(":")
        if sep:
            found[label.strip().lower()] = value.strip()
    return found


def _split(text: str) -> tuple[str, ...]:
    return tuple(part for p in text.split(",") if (part := " ".join(p.split())))


def parse_tab_page(html: str | bytes, url: str | None = None) -> GameTab:
    """A tab page's tab and what its ``data-tab`` says of it (its microdata and heading where it says nothing);
    ``GameTabsParseError`` for a page without a tab, a title or a game."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = LexborHTMLParser(html)
    pre = tree.css_first("pre#tab-text-view-text")
    body = pre.text(deep=True) if pre is not None else None
    if body is None or not body.strip():
        raise GameTabsParseError("no tab (pre#tab-text-view-text) on the page", url=url)
    wrapper = tree.css_first("#tab-page-wrapper")
    data = _data_tab(wrapper)
    game = data.get("game") if isinstance(data.get("game"), dict) else {}
    work = wrapper.css_first('[itemprop="recordingOf"]') if wrapper is not None else None
    album = wrapper.css_first('[itemprop="inAlbum"]') if wrapper is not None else None
    details = _details(tree)
    title = " ".join(str(data.get("name") or "").split()) or _meta(work, "name") or _text(
        tree.css_first("h1#tab-page-tab-name"))
    game_name = " ".join(str(game.get("name") or "").split()) or _meta(album, "name")
    if not title or not game_name:
        raise GameTabsParseError("no title or game on the page", url=url)
    link = album.css_first('link[itemprop="url"]') if album is not None else None
    found = _TAB_HREF.fullmatch(url or "")
    path = found.group(1) if found else ""
    game_slug = str(game.get("slug") or "")
    if not game_slug and link is not None:
        game_slug = (link.attributes.get("href") or "").rstrip("/").rpartition("/")[2]
    if not game_slug and path:
        game_slug = path.split("/")[1]
    composers = _names(data.get("composers")) or tuple(
        c for node in (work.css('[itemprop="composer"]') if work is not None else ()) if (c := _meta(node, "name")))
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    tab_id = data.get("id")
    views = _number(data.get("views"))
    ratings = _number(data.get("num_ratings_fun"))
    return GameTab(
        tab_id=tab_id if isinstance(tab_id, int) and not isinstance(tab_id, bool) else None,
        title=title, game=game_name, game_slug=game_slug,
        slug=str(data.get("slug") or "") or path.rpartition("/")[2],
        body=body.strip("\n") + "\n",
        composers=composers,
        instruments=_names(data.get("instruments")) or _split(details.get("instrument", "")),
        styles=_names(data.get("styles")) or _split(details.get("style", "")),
        tuning=details.get("tuning") or None,
        tabber=" ".join(str(user.get("display_username") or "").split()) or None,
        views=int(views) if views is not None and views >= 0 else 0,
        rating=_number(data.get("average_fun_rating")),
        ratings=int(ratings) if ratings is not None and ratings >= 0 else 0,
        created=str(data["created_at"]) if isinstance(data.get("created_at"), str) else None,
    )


# --- a game page ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ListedTab:
    """A tab a game page lists: its page's path (``tabs/actraiser/fillmore``), the track's title as the card writes
    it, less the game's name, and what the card says of it (empty, None or 0 where it says nothing)."""

    path: str
    title: str
    composers: tuple[str, ...] = ()
    instruments: tuple[str, ...] = ()
    styles: tuple[str, ...] = ()
    platform: str | None = None
    tabber: str | None = None
    views: int = 0
    rating: float | None = None


@dataclass(frozen=True)
class GamePage:
    """A game page: the game's name as the page heads it, the tabs it says the game has (``tabs``), those it lists
    (``listed``: ``PAGE_TABS`` at most), and how many pages its selector offers (``pages``, 1 with none)."""

    name: str
    tabs: int
    listed: tuple[ListedTab, ...] = ()
    pages: int = 1


def _views(text: str) -> int:
    """"11.2k" → 11,200; "1.1M" → 1,100,000; "692" → 692; 0 for none."""
    m = _COUNT.fullmatch(text.replace(",", "").strip())
    if m is None:
        return 0
    n = float(m.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()]
    return int(round(n)) if math.isfinite(n) else 0


def _vocabulary(tree: LexborHTMLParser) -> frozenset[str]:
    """The site's instruments, as the page's shuffle dialog names them; ``INSTRUMENTS`` when it doesn't."""
    dialog = tree.css_first("[data-prepopulated-instruments]")
    try:
        named = _names(json.loads(dialog.attributes.get("data-prepopulated-instruments") or "")) if dialog else ()
    except (ValueError, RecursionError):
        named = ()
    return frozenset(named or INSTRUMENTS)


def _card(card: LexborNode, game: str, instruments: frozenset[str]) -> ListedTab | None:
    """A card's tab, or None for one that links to no tab page."""
    found = _TAB_HREF.fullmatch(card.attributes.get("href") or "")
    left = card.css_first(".split-row-left")
    if found is None or left is None:
        return None
    spans = [s for s in left.iter() if s.tag == "span"]
    title = " ".join((card.attributes.get("title") or "").split()) or (_text(spans[0]) if spans else "")
    title = title.removesuffix(f" - {game}").strip()
    if not title:
        return None
    platform = tabber = None
    composers: tuple[str, ...] = ()
    said: list[tuple[str, ...]] = []
    for span in spans[1:]:
        text = _text(span)
        label, sep, value = text.partition(":")
        if "italic" in (span.attributes.get("style") or ""):
            platform = text or None
        elif sep and label in ("Composer", "Composers"):
            composers = _split(value)
        elif sep and label == "Tabber":
            tabber = value.strip().lstrip("@") or None
        elif text:
            said.append(_split(text))
    named = next((s for s in said if s and set(s) <= instruments), ())
    styles = next((s for s in said if s is not named), ())
    right = card.css_first(".split-row-right")
    views = next((_views(t.removeprefix("Views")) for s in (right.css("span") if right else ())
                  if (t := _text(s)).startswith("Views")), 0)
    rated = right.css_first('[title$="average fun rating"]') if right is not None else None
    rating = _RATING.fullmatch(rated.attributes.get("title") or "") if rated is not None else None
    return ListedTab(found.group(1), title, composers=composers, instruments=named, styles=styles, platform=platform,
                     tabber=tabber, views=views, rating=float(rating.group(1)) if rating else None)


def parse_game_page(html: str | bytes, url: str | None = None) -> GamePage:
    """A game page's name, the tabs it says the game has and those it lists; ``GameTabsParseError`` for a page
    without its heading (the name in its ``<h1>``), or one that says the game has tabs and lists none caracole can
    read (its cards changed, say: never a game without tabs)."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = LexborHTMLParser(html)
    wrapper = tree.css_first("#game-page-wrapper")
    name = _text(wrapper.css_first("h1")) if wrapper is not None else ""
    if not name:
        raise GameTabsParseError("no game's name (#game-page-wrapper h1) on the page", url=url)
    vocabulary = _vocabulary(tree)
    listed = tuple(tab for card in wrapper.css("#game-page-games-list .results-list > a")
                   if (tab := _card(card, name, vocabulary)) is not None)
    said = next((m for p in wrapper.css("p") if (m := _SAID.fullmatch(_text(p)))), None)
    tabs = int(said.group(1).replace(",", "")) if said is not None else len(listed)
    if tabs and not listed:
        raise GameTabsParseError(f"the page says {tabs} tabs and lists none caracole can read", url=url)
    pages = [int(n) for a in wrapper.css(".page-selector-wrapper a") if (n := _text(a)).isdigit()]
    return GamePage(name, max(tabs, len(listed)), tuple(dict((t.path, t) for t in listed).values()),
                    max(pages, default=1))
