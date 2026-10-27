"""A fake harptabs.com behind a real ``PoliteClient``.

The pages are the ones caracole's own user agent got on 27 October 2026, in tests/fixtures/harptabs/:
robots.txt, the sitemap trimmed to 17 of its 37,598 URLs (no ETag, as the live one sends none), three
tab pages trimmed to their head, header, chips and tab (Piano Man's lyric lines synthetic; Knockin' on
Heaven's Door's, 29910, a tab "by Unknown", its words synthetic, which no fake site serves unasked), and two
artist pages trimmed to their header and a few cards (Billy Joel's, 7 of the 30 it lists, and the
site's catch-all "?"). Other tab pages are made from Piano Man's (:func:`tab_page`), other artist
pages from Billy Joel's (:func:`artist_page`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import httpx

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "harptabs"
BASE = "https://www.harptabs.com"
SITEMAP = f"{BASE}/sitemap.xml"
NOW = datetime(2026, 10, 27, 3, 30, tzinfo=UTC)
HTML = {"Content-Type": "text/html; charset=utf-8"}
XML = {"Content-Type": "application/xml"}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def tab_page(title: str, artist: str, *, views: str = "1.1M", key: str = "C", body: str = "4 5 6\nsynthetic words\n",
             artist_path: str = "artist/1/someone") -> str:
    """A tab page in the captured one's markup (Piano Man's), with this title, artist, views, harp key and tab."""
    page = fixture("tab_25_piano-man.html")
    head, _, rest = page.partition("<code>")
    _, _, tail = rest.partition("</code>")
    return (head.replace('"name":"piano man"', f'"name":"{title}"')
            .replace('"name":"billy joel"', f'"name":"{artist}"')
            .replace(">piano man</h1>", f">{title}</h1>")
            .replace('href="/artist/1178/billy-joel">billy joel</a>', f'href="/{artist_path}">{artist}</a>')
            .replace("</svg>1.1M</span>", f"</svg>{views}</span>")
            .replace("Key <!-- -->C</a>", f"Key <!-- -->{key}</a>")
            + "<code>" + body + "</code>" + tail)


_CARD = '<div class="group relative block rounded-lg'
_FOOT = '<div class="flex justify-center py-8'


def artist_page(name: str, tabs: Sequence[tuple], *, count: int | None = None) -> str:
    """An artist page in the captured one's markup (Billy Joel's), named ``name``, its header saying ``count`` tabs
    (those listed, by default), and a card a tab of ``tabs``, each ``(id, slug, title)`` or ``(id, slug, title,
    views)`` ("57k"), with the first captured card's other chips (key C, rated 4.0, Beginner)."""
    page = fixture("artist_1178_billy-joel.html")
    head, _, rest = page.partition(_CARD)
    card, _, _ = rest.partition(_CARD)
    tail = page[page.index(_FOOT):]
    cards = []
    for tab in tabs:
        tab_id, slug, title, views = (*tab, "1.1M")[:4]
        cards.append(_CARD + card.replace('href="/tab/25/piano-man">piano man</a>',
                                          f'href="/tab/{tab_id}/{slug}">{escape(title)}</a>')
                     .replace("</svg>1.1M</span>", f"</svg>{views}</span>"))
    n = len(tabs) if count is None else count
    return (head.replace(">billy joel</h1>", f">{escape(name)}</h1>")
            .replace(">98 tabs</p>", f">{n} tab{'' if n == 1 else 's'}</p>") + "".join(cards) + tail)


class FakeHarpTabs:
    """harptabs.com: pages by URL, every request recorded. By default it has the captured sitemap, its two
    captured tab pages and Billy Joel's artist page; any other URL of the site answers 404, as a tab taken down
    does."""

    def __init__(self, pages: dict[str, tuple[int, str, dict[str, str]]] | None = None):
        self.pages: dict[str, tuple[int, str, dict[str, str]]] = {
            SITEMAP: (200, fixture("sitemap.xml"), XML),
            f"{BASE}/tab/25/piano-man": (200, fixture("tab_25_piano-man.html"), HTML),
            f"{BASE}/tab/89/la-bamba": (200, fixture("tab_89_la-bamba.html"), HTML),
            f"{BASE}/artist/1178/billy-joel": (200, fixture("artist_1178_billy-joel.html"), HTML),
        }
        self.pages.update(pages or {})
        self.requests: list[str] = []
        self.agents: list[str] = []

    def page(self, path: str, html: str, status: int = 200) -> None:
        self.pages[f"{BASE}/{path}"] = (status, html, HTML)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        self.agents.append(request.headers.get("user-agent", ""))
        status, body, headers = self.pages.get(url, (404, "<html><body>Not found</body></html>", HTML))
        return httpx.Response(status, content=body.encode("utf-8"), headers=headers)

    def client(self, cache_dir: Path, *, budget: int = 20, now: datetime = NOW,
               user_agent: str = "caracole-test") -> PoliteClient:
        return PoliteClient(
            "harptabs", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), cache_dir, user_agent=user_agent,
            transport=httpx.MockTransport(self.handler), sleep=lambda seconds: None, wall_clock=lambda: now,
        )
