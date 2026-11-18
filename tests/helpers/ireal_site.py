"""A fake forums.irealpro.com behind a real ``PoliteClient``.

The pages are the ones caracole's own user agent got on 18 November 2026, in tests/fixtures/ireal/: robots.txt and
the sitemap index (``sitemap.php``) as they are; its first child trimmed to 24 of its 50,000 URLs (the home page,
three forums, a tag, 17 threads, two members; the other five children list members alone, and are made here, a URL
each); three thread pages trimmed to their head, breadcrumbs, title and a few posts, their prose scrambled, each chart
cut to a few bars and encoded again as the app writes it (Thad Jones's Groove Merchant and its repost with the coda;
Jerome Richardson's, in the old ``irealbook://`` format and in ``irealb://``; the Jazz 1460 Standards thread, ten of
its playlist's 1,460 tunes, two of the Jazz New 50 and two links of one tune); and the jazz forum's first page, its
seven sticky threads and two after them. Other thread pages are made from Thad Jones's (:func:`thread_page`), and
their charts by :func:`link`.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient
from caracole.ireal import MAGIC, unscramble

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ireal"
BASE = "https://forums.irealpro.com"
SITEMAP = f"{BASE}/sitemap.php"
CHILDREN = [f"{BASE}/sitemap-{n}.xml" for n in range(1, 7)]
NOW = datetime(2026, 11, 18, 3, 30, tzinfo=UTC)
HTML = {"Content-Type": "text/html; charset=utf-8"}
XML = {"Content-Type": "application/xml; charset=utf-8"}
THAD_JONES = "threads/groove-merchant-thad-jones.9518/"
RICHARDSON = "threads/groove-merchant-jerome-richardson.14294/"
JAZZ_1460 = "threads/jazz-1460-standards.12753/"
JAZZ_FORUM = "forums/jazz.6/"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def urlset(*paths: str) -> str:
    """A child sitemap in the live one's markup, listing these paths."""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"\t<url><loc>{BASE}/{html.escape(p)}</loc></url>\n" for p in paths) + "</urlset>\n")


def encode(music: str) -> str:
    """A chart's music as an ``irealb://`` link writes it: the app's three abbreviations, then scrambled (the scramble
    is its own inverse), after its magic."""
    raw = music.replace("| x", "Kcl").replace(" |", "LZ").replace("   ", "XyQ")
    return MAGIC + unscramble(raw)


def link(tunes: Sequence[tuple[str, str, str, str, str]], *, playlist: str | None = None) -> str:
    """An ``irealb://`` link of these tunes, each (title, composer, style, key, music as it reads unscrambled), and a
    playlist's name after them when one is given."""
    parts = ["=".join([title, composer, "", style, key, "", encode(music), "", "0", "0"])
             for title, composer, style, key, music in tunes]
    body = "===".join(parts) + (f"==={playlist}" if playlist is not None else "")
    return "irealb://" + urllib.parse.quote(body, safe="")


_POST = '<article class="message message--post '
_END = "\n</div>\n</div>\n</div>\n</body>"


def thread_page(title: str, posts: Sequence[tuple], *, path: str = THAD_JONES, forum: str = JAZZ_FORUM) -> str:
    """A thread page in the captured one's markup (Thad Jones's Groove Merchant), titled ``title``, at ``path``, in
    ``forum``, a post each of ``posts``: ``(post id, links)`` or ``(post id, links, links quoted from another post)``."""
    page = fixture("thread_groove-merchant-thad-jones.9518.html")
    starts = [m.start() for m in re.finditer(re.escape(_POST), page)]
    end = page.index(_END)
    template = page[starts[0]:starts[1]].rstrip("\n")
    made = []
    for post in posts:
        number, links, quoted = (*post, ())[:3]
        one = re.sub(r"post-23346", f"post-{number}", template)
        anchors = "".join(f'<a href="{html.escape(u, quote=True)}" target="_blank" class="link link--external" '
                          f'rel="nofollow ugc noopener">a chart</a><br />\n' for u in links)
        quotes = "".join(f'<blockquote class="bbCodeBlock bbCodeBlock--expandable bbCodeBlock--quote">'
                         f'<div class="bbCodeBlock-content"><a href="{html.escape(u, quote=True)}">a chart</a>'
                         f'</div></blockquote>' for u in quoted)
        one = re.sub(r'<div class="bbWrapper">.*?</div>', lambda _, q=quotes, a=anchors: f'<div class="bbWrapper">{q}{a}</div>',
                     one, count=1, flags=re.DOTALL)
        made.append(one)
    out = page[:starts[0]] + "\n".join(made) + page[end:]
    out = out.replace("Groove Merchant - Thad Jones", html.escape(title)).replace(THAD_JONES, path)
    return out.replace("/forums/jazz.6/", f"/{forum}")


class FakeIReal:
    """forums.irealpro.com: pages by URL, every request recorded. By default it has the captured sitemap index, its
    first child trimmed, the other five of a member each, the three captured thread pages and the jazz forum's page;
    any other URL of the site answers 404, as a thread taken down does."""

    def __init__(self, pages: dict[str, tuple[int, bytes | str, dict[str, str]]] | None = None):
        self.pages: dict[str, tuple[int, bytes | str, dict[str, str]]] = {
            SITEMAP: (200, fixture("sitemap.xml"), XML),
            CHILDREN[0]: (200, fixture("sitemap-1.xml"), XML),
            **{url: (200, urlset(f"members/someone.{n}/"), XML) for n, url in enumerate(CHILDREN[1:], 2)},
            f"{BASE}/{THAD_JONES}": (200, fixture("thread_groove-merchant-thad-jones.9518.html"), HTML),
            f"{BASE}/{RICHARDSON}": (200, fixture("thread_groove-merchant-jerome-richardson.14294.html"), HTML),
            f"{BASE}/{JAZZ_1460}": (200, fixture("thread_jazz-1460-standards.12753.html"), HTML),
            f"{BASE}/{JAZZ_FORUM}": (200, fixture("forum_jazz.6.html"), HTML),
        }
        self.pages.update(pages or {})
        self.requests: list[str] = []
        self.agents: list[str] = []

    def page(self, path: str, body: str, status: int = 200) -> None:
        self.pages[f"{BASE}/{path}"] = (status, body, HTML)

    def threads(self, *paths: str) -> None:
        """The first child sitemap listing these threads alone."""
        self.pages[CHILDREN[0]] = (200, urlset(*paths), XML)

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
            "ireal", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), cache_dir, user_agent=user_agent,
            transport=httpx.MockTransport(self.handler), sleep=lambda seconds: None, wall_clock=lambda: now,
        )
