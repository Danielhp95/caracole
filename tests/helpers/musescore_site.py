"""A fake musescore.com behind a real ``PoliteClient``.

The fixtures in tests/fixtures/musescore/: robots.txt as fetched on 19 October 2026; the
challenge page Cloudflare answered caracole's request for the song sitemap index with
that day, trimmed and without its tokens; the song sitemap index and sitemap_songs1.xml
as the Internet Archive kept them on 1 May 2026 (the live ones are behind that
challenge), trimmed to two children and to twelve song pages; and sitemap_songs18.xml,
synthetic, in the same shape, with titles a guitarist's library has.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "musescore"
BASE = "https://musescore.com"
INDEX = f"{BASE}/sitemaps/song-index.xml"
CHILD = f"{BASE}/sitemaps/song-index/sitemap_songs{{}}.xml"
NOW = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
XML = {"Content-Type": "text/xml; charset=UTF-8"}
HTML = {"Content-Type": "text/html; charset=UTF-8"}
# What Cloudflare sent with its challenge: HTTP 403 and this header.
CHALLENGE_HEADERS = {**HTML, "cf-mitigated": "challenge", "Server": "cloudflare"}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def challenge() -> tuple[int, str, dict[str, str]]:
    """Cloudflare's answer to caracole's request for a sitemap, as on 19 October 2026."""
    return 403, fixture("challenge.html"), CHALLENGE_HEADERS


def urlset(*paths: str) -> str:
    """A song sitemap listing these pages, in the shape of sitemap_songs1.xml."""
    urls = "".join(f"<url><loc>{BASE}/{p}</loc><lastmod>2026-04-27</lastmod><priority>0.8</priority></url>"
                   for p in paths)
    return ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            f'xmlns:xhtml="http://www.w3.org/1999/xhtml">{urls}</urlset>')


def sitemaps() -> dict[str, tuple[int, str, dict[str, str]]]:
    """The song sitemap index and its two children, each with an ETag."""
    return {
        INDEX: (200, fixture("song-index.xml"), {**XML, "ETag": 'W/"song-index"'}),
        CHILD.format(1): (200, fixture("sitemap_songs1.xml"), {**XML, "ETag": 'W/"songs1"'}),
        CHILD.format(18): (200, fixture("sitemap_songs18.xml"), {**XML, "ETag": 'W/"songs18"'}),
    }


class FakeMuseScore:
    """musescore.com: pages by URL, every request recorded.

    By default it has the song sitemaps. A sitemap asked for with the ETag it has answers
    304. Any other URL fails the test: caracole asked for something it shouldn't.
    """

    def __init__(self, pages=None):
        self.pages: dict[str, tuple[int, str | bytes, dict[str, str]]] = dict(sitemaps())
        self.pages.update(pages or {})
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url not in self.pages:
            raise AssertionError(f"unexpected request: {url}")
        status, body, headers = self.pages[url]
        if status == 200 and headers.get("ETag") and request.headers.get("if-none-match") == headers["ETag"]:
            return httpx.Response(304, headers=headers)
        content = body.encode("utf-8") if isinstance(body, str) else body
        return httpx.Response(status, content=content, headers=headers)

    def client(self, cache_dir: Path, *, budget: int = 10, now: datetime = NOW, events=None) -> PoliteClient:
        return PoliteClient(
            "musescore",
            ProviderPolicy(budget=budget, delay=(0.0, 0.0)),
            cache_dir,
            user_agent="caracole-test",
            transport=httpx.MockTransport(self.handler),
            sleep=lambda seconds: None,
            wall_clock=lambda: now,
            on_event=events.append if events is not None else None,
        )
