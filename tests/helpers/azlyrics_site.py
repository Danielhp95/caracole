"""A fake azlyrics.com behind a real ``PoliteClient``.

It serves ``pages``, a path each and its text (:func:`artist_page` and :func:`lyrics_page` make them from
tests/fixtures/azlyrics/, the live markup with invented lyrics), and the site's 404 for any other path. ``failing`` maps
a path to the status it gets, or to "block" for the block page, which the site answers with a 200. Every request is
recorded, with the user agent it came with.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "azlyrics"
NOW = datetime(2026, 10, 30, 3, 30, tzinfo=UTC)
HTML = {"Content-Type": "text/html; charset=utf-8"}
ARTIST = "/p/pomme.html"
SONG = "/lyrics/pomme/mononoke.html"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def artist_page() -> str:
    return fixture("artist_pomme.html")


def lyrics_page() -> str:
    return fixture("lyrics_mononoke.html")


POMME = {ARTIST: artist_page(), SONG: lyrics_page()}


class FakeAzLyrics:
    def __init__(self, pages=None, *, failing=None):
        self.pages = dict(POMME if pages is None else pages)
        self.failing = dict(failing or {})
        self.requests: list[str] = []
        self.agents: list[str] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        self.agents.append(request.headers.get("user-agent", ""))
        failing = self.failing.get(path)
        if failing == "block":
            return httpx.Response(200, headers=HTML, text=fixture("block.html"))
        if failing is not None:
            return httpx.Response(failing, text="Bad Gateway")
        if path in self.pages:
            return httpx.Response(200, headers=HTML, text=self.pages[path])
        return httpx.Response(404, headers=HTML, text=fixture("not_found.html"))

    def client(self, cache_dir: Path, *, budget: int = 60, now: datetime = NOW,
               user_agent: str = "caracole-test") -> PoliteClient:
        return PoliteClient(
            "azlyrics", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), cache_dir, user_agent=user_agent,
            transport=httpx.MockTransport(self.handler), sleep=self.sleeps.append, wall_clock=lambda: now,
        )
