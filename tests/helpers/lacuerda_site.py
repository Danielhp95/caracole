"""A fake acordes.lacuerda.net for its artist listings and artist pages, behind a real ``PoliteClient``.

The fixtures in tests/fixtures/lacuerda/, as captured on 20 October 2026: robots.txt (empty);
not_found.html, the 404 page /sitemap.xml answered; tabs.html, /tabs/ with its menu of
initials; and letter_e.html, the first page of E's listing of every artist, cut down to 12 of
its 100. ``listing_page`` makes other listing pages in that page's shape, and ``artist_page``
artist pages in the shape of artist.html (18 October).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "lacuerda"
BASE = "https://acordes.lacuerda.net"
NOW = datetime(2026, 10, 20, 3, 30, tzinfo=UTC)
HTML = {"Content-Type": "text/html; charset=UTF-8"}
# What the listings answered with: they are static files.
LAST_MODIFIED = "Fri, 22 May 2026 19:02:51 GMT"

_MULTIPAG = re.compile(r"<div class='multipag'>.*?</div>(?=\n)", re.DOTALL)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def listing_page(artists: Sequence[tuple[str, str, int]], *, pages: int = 1, page: int = 0,
                 total: int | None = None) -> str:
    """A page of a letter's listing in the shape of letter_e.html: ``(slug, name, songs)`` per artist,
    the letter's ``pages`` pages linked (``index0.html``…), this one the ``page``-th, and ``total``
    artists counted (by default the ones on this page)."""
    html = fixture("letter_e.html")
    start = html.index("<ul id=i_main>") + len("<ul id=i_main>")
    end = html.index("</ul>", start)
    items = "\n".join(
        f"<li onclick='w.location=\"/{slug}/\"'><img src='//cdn.lacuerda.net/FOTOS/{slug}.jpg' class='bFoto'>"
        f"<a HREF=\"/{slug}/\"><em>Acordes de &nbsp;</em>{name}</a><span>{songs}<em>&nbsp; canciones</em></span>"
        "<br clear=all></li>"
        for slug, name, songs in artists
    )
    html = f"{html[:start]}\n{items}\n{html[end:]}"
    links = "".join(
        f"<li class='sel'>{n + 1}</li>" if n == page
        else f"<li onclick=\"w.location='index{n * 100}.html'\">{n + 1}</li>"
        for n in range(pages)
    )
    counted = len(artists) if total is None else total
    multipag = (f"<div class='multipag'><div class='first'>Indice:</div><ul>{links}"
                f"<li class=last><font color=#000000>{counted}</font> Artistas</li></ul><br clear=all></div>")
    return _MULTIPAG.sub(lambda m: multipag, html)


def artist_page(name: str, slug: str, *songs: tuple[str, str, str]) -> str:
    """artist.html made over for another artist: ``(song slug, title, lcd)`` per song."""
    page = fixture("artist.html").replace("Soda Stereo", name).replace("soda_stereo", slug)
    start = page.index("<ul id=b_main")
    head, end = page.index(">", start) + 1, page.index("</ul>", start)
    items = "\n".join(
        f"<li id='r{i:03}' lcd='{lcd}'><a href=\"{song}\">{title} <em>acordes</em></A></li>"
        for i, (song, title, lcd) in enumerate(songs)
    )
    return f"{page[:head]}\n{items}\n{page[end:]}"


class LaCuerdaSite:
    """acordes.lacuerda.net: pages by URL, every request recorded with its headers.

    ``letter`` puts a letter's listing up, a page per list of artists. A listing page answers
    304 to a request that has its ``Last-Modified``; one the site doesn't have answers its 404
    page, as /sitemap.xml did. Any other URL not put up fails the test.
    """

    def __init__(self):
        self.pages: dict[str, tuple[int, str, dict[str, str]]] = {}
        self.requests: list[str] = []
        self.conditional: list[str] = []  # the requests sent with If-Modified-Since
        self.status: int | None = None  # every request answered with this status, when set

    def letter(self, letter: str, *pages: Sequence[tuple[str, str, int]], modified: str = LAST_MODIFIED,
               total: int | None = None) -> None:
        counted = sum(len(p) for p in pages) if total is None else total
        for n, artists in enumerate(pages):
            html = listing_page(artists, pages=len(pages), page=n, total=counted)
            self.pages[f"{BASE}/tabs/{letter}/index{n * 100}.html"] = (200, html, {**HTML, "Last-Modified": modified})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if request.headers.get("if-modified-since"):
            self.conditional.append(url)
        if self.status is not None:
            return httpx.Response(self.status, text="nope", headers=HTML)
        if url not in self.pages:
            if request.url.path.startswith("/tabs/"):
                return httpx.Response(404, text=fixture("not_found.html"), headers=HTML)
            raise AssertionError(f"unexpected request: {url}")
        status, body, headers = self.pages[url]
        if status == 200 and headers.get("Last-Modified") and \
                request.headers.get("if-modified-since") == headers["Last-Modified"]:
            return httpx.Response(304, headers=headers)
        return httpx.Response(status, text=body, headers=headers)

    def client(self, cache_dir: Path, *, budget: int = 100, now: datetime = NOW, events=None) -> PoliteClient:
        return PoliteClient(
            "lacuerda",
            ProviderPolicy(budget=budget, delay=(0.0, 0.0)),
            cache_dir,
            user_agent="caracole-test",
            transport=httpx.MockTransport(self.handler),
            sleep=lambda seconds: None,
            wall_clock=lambda: now,
            on_event=events.append if events is not None else None,
        )
