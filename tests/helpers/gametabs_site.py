"""A fake gametabs.net behind a real ``PoliteClient``.

The pages are the ones caracole's own user agent got on 28 October 2026, in tests/fixtures/gametabs/:
robots.txt and the sitemap index as they are; its first child sitemap trimmed to 20 of its 5,000 URLs (the live
one gzipped, which the client decodes); three game pages trimmed to their heading, their list and the shuffle
dialog's vocabularies (Actraiser's 5 tabs, Hollow Knight's 6, and Final Fantasy VII's first page, 5 of its 50
cards, with its page selector); two tab pages trimmed to their data, their heading, their details and their tab,
its first block as written and two more with every digit scrambled (Actraiser's Fillmore, and Hollow Knight's
Resting Grounds, ``resting-grounds-2``, the second tab of that title). The second child sitemap is synthetic, made of
the Hollow Knight game page's links (the live one wasn't asked for), and so are the other children (the site's pages,
a URL each: what they list wasn't asked for either). Other tab pages are made from Fillmore's (:func:`tab_page`),
other game pages from Actraiser's (:func:`game_page`).
"""

from __future__ import annotations

import gzip
import html
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "gametabs"
BASE = "https://gametabs.net"
SITEMAP = f"{BASE}/sitemap.xml"
CHILDREN = [f"{BASE}/sitemap_{n}.xml.gz" for n in range(1, 7)]
NOW = datetime(2026, 10, 28, 3, 30, tzinfo=UTC)
HTML = {"Content-Type": "text/html; charset=utf-8"}
XML = {"Content-Type": "application/xml"}
GZIP = {"Content-Type": "application/x-gzip"}
FILLMORE = f"{BASE}/tabs/actraiser/fillmore"
RESTING = f"{BASE}/tabs/hollow-knight/resting-grounds-2"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def urlset(*paths: str) -> str:
    """A child sitemap in the live one's markup, listing these paths."""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"    <url>\n        <loc>{BASE}/{html.escape(p)}</loc>\n"
                      "        <lastmod>2026-10-01T00:00:00+00:00</lastmod>\n      </url>\n" for p in paths)
            + "</urlset>\n")


def tab_page(game: str, title: str, *, game_slug: str | None = None, slug: str | None = None,
             composers: Sequence[str] = ("Yuzo Koshiro",), instruments: Sequence[str] = ("Guitar",),
             views: int = 100, rating: float | None = 5.0, tab_id: int = 1,
             body: str = "e|--0--2--3--|\nB|--1--1--1--|\n") -> str:
    """A tab page in the captured one's markup (Fillmore's), of this game and title, its ``data-tab`` and its
    microdata saying so, with these composers, instruments, views and fun rating, and this tab."""
    page = fixture("tab_actraiser_fillmore.html")
    game_slug = game_slug or re.sub(r"[^a-z0-9]+", "-", game.lower()).strip("-")
    slug = slug or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    m = re.search(r'data-tab="([^"]*)"', page)
    data = json.loads(html.unescape(m.group(1)))
    data["game"].update(slug=game_slug, name=game)
    data.update(id=tab_id, name=title, slug=slug, views=views, average_fun_rating=rating,
                composers=[{"id": n, "name": c} for n, c in enumerate(composers, 1)],
                instruments=[{"id": n, "name": i} for n, i in enumerate(instruments, 1)])
    page = page[:m.start(1)] + html.escape(json.dumps(data), quote=True) + page[m.end(1):]
    head, _, rest = page.partition('<pre id="tab-text-view-text">')
    _, _, tail = rest.partition("</pre>")
    head = (head.replace("Fillmore", html.escape(title)).replace("Actraiser", html.escape(game))
            .replace("/tabs/actraiser", f"/tabs/{game_slug}").replace("/fillmore", f"/{slug}"))
    return head + '<pre id="tab-text-view-text">' + html.escape(body) + "</pre>" + tail


_CARD = re.compile(r'<a href="https://gametabs.net/tabs/actraiser/[^"]*"\s*title=.*?</a>\n', re.S)


def game_page(game: str, tabs: Sequence[tuple], *, game_slug: str | None = None, count: int | None = None) -> str:
    """A game page in the captured one's markup (Actraiser's), named ``game``, its "Tabs:" saying ``count`` (those
    listed, by default), and a card a tab of ``tabs``, each ``(slug, title)``, ``(slug, title, composer)`` or
    ``(slug, title, composer, instruments, views)`` ("Guitar, Bass", "11.2k"); ``composer`` "" for a card that names
    none."""
    page = fixture("game_actraiser.html")
    game_slug = game_slug or re.sub(r"[^a-z0-9]+", "-", game.lower()).strip("-")
    cards = list(_CARD.finditer(page))
    card = cards[-1].group(0)  # Sacrifices: Guitar, a composer, a fun rating, views
    made = []
    for tab in tabs:
        slug, title, composer, instruments, views = (*tab, *("Yuzo Koshiro", "Guitar", "1.2k")[len(tab) - 2:])
        one = re.sub(r'href="[^"]*"', f'href="{BASE}/tabs/{game_slug}/{slug}"', card, count=1)
        one = re.sub(r'title="[^"]*"\s*aria-label="[^"]*"',
                     f'title="{html.escape(title)} - {html.escape(game)}" '
                     f'aria-label="{html.escape(title)} - {html.escape(game)}"', one, count=1)
        one = re.sub(r"<span>[^<]*</span>", f"<span>{html.escape(title)} - {html.escape(game)}</span>", one, count=1)
        one = one.replace('<span class="font-size-small">Guitar</span>',
                          f'<span class="font-size-small">{html.escape(instruments)}</span>')
        one = re.sub(r"Views [0-9.kM]+", f"Views {views}", one)
        one = re.sub(r'<span class="font-size-small">Composer: [^<]*</span>',
                     f'<span class="font-size-small">Composer: {html.escape(composer)}</span>' if composer else "", one)
        made.append(one)
    n = len(tabs) if count is None else count
    out = page[:cards[0].start()] + "".join(made) + page[cards[-1].end():]
    return (out.replace("Actraiser", html.escape(game)).replace("Tabs: 5", f"Tabs: {n}"))


class FakeGameTabs:
    """gametabs.net: pages by URL, every request recorded. By default it has the captured sitemap index, its first
    child trimmed, the synthetic second, the other four of a URL each, the three captured game pages and the two
    captured tab pages; any other URL of the site answers 404, as a tab taken down does."""

    def __init__(self, pages: dict[str, tuple[int, bytes | str, dict[str, str]]] | None = None):
        self.pages: dict[str, tuple[int, bytes | str, dict[str, str]]] = {
            SITEMAP: (200, fixture("sitemap.xml"), XML),
            CHILDREN[0]: (200, fixture("sitemap_1.xml"), XML),
            CHILDREN[1]: (200, fixture("sitemap_2.xml"), XML),
            **{url: (200, urlset(f"profile/someone-{n}"), XML) for n, url in enumerate(CHILDREN[2:], 3)},
            f"{BASE}/tabs/actraiser": (200, fixture("game_actraiser.html"), HTML),
            f"{BASE}/tabs/hollow-knight": (200, fixture("game_hollow-knight.html"), HTML),
            f"{BASE}/tabs/final-fantasy-vii": (200, fixture("game_final-fantasy-vii.html"), HTML),
            FILLMORE: (200, fixture("tab_actraiser_fillmore.html"), HTML),
            RESTING: (200, fixture("tab_hollow-knight_resting-grounds-2.html"), HTML),
        }
        self.pages.update(pages or {})
        self.requests: list[str] = []
        self.agents: list[str] = []

    def page(self, path: str, body: str, status: int = 200) -> None:
        self.pages[f"{BASE}/{path}"] = (status, body, HTML)

    def gzipped(self, url: str) -> None:
        """Serve the sitemap at ``url`` as a gzip file, as an nginx without gzip encoding would."""
        status, body, _ = self.pages[url]
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.pages[url] = (status, gzip.compress(data), GZIP)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        self.agents.append(request.headers.get("user-agent", ""))
        status, body, headers = self.pages.get(url, (404, "<html><body>Not found</body></html>", HTML))
        return httpx.Response(status, content=body.encode("utf-8") if isinstance(body, str) else body,
                              headers=headers)

    def client(self, cache_dir: Path, *, budget: int = 20, now: datetime = NOW,
               user_agent: str = "caracole-test") -> PoliteClient:
        return PoliteClient(
            "gametabs", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), cache_dir, user_agent=user_agent,
            transport=httpx.MockTransport(self.handler), sleep=lambda seconds: None, wall_clock=lambda: now,
        )
