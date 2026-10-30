"""A fake Megalobiz API behind a real ``PoliteClient``.

Its records are made from tests/fixtures/megalobiz/lrc_24519.json (the live ``/lrc/{id}`` shape, invented words):
:func:`record` gives one of another title, artist, length or id. ``/search`` answers, as the live one's shape, the
records whose title holds the query's title or whose artist holds its artist (the live ranking is as loose: other
songs of the artist, other artists' songs of the title), the best first; ``/lrc/{id}`` the record, or its 404.
``failing`` maps an endpoint ("search", "lrc") to the status every request to it gets (a 429 with ``Retry-After``,
as its docs say). Every request is recorded, with the user agent it came with.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient
from caracole.normalize import fold

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "megalobiz"
NOW = datetime(2026, 10, 30, 3, 30, tzinfo=UTC)
JSON = {"Content-Type": "application/json; charset=utf-8"}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def record(*, lrc_id: int = 24519, title: str = "Hotel California", artist: str = "Eagles",
           duration: float | None = 391.55) -> dict:
    """A ``/lrc/{id}`` record in the captured shape, with these names, length and id; its page's address made from
    them as the live ones are."""
    data = json.loads(fixture("lrc_24519.json"))
    slug = "-".join(fold(title).lower().split())
    data.update(id=lrc_id, title=title, artist=artist, duration=duration,
                url=f"https://megalobiz.com/lrc/{lrc_id}/{slug}")
    data["lrc"] = data["lrc"].replace("[ar:Eagles]", f"[ar:{artist}]").replace("[ti:Hotel California]",
                                                                               f"[ti:{title}]")
    return data


class FakeMegalobiz:
    def __init__(self, records=(), *, failing=None):
        self.records = [record() if r is None else r for r in records]
        self.failing = dict(failing or {})
        self.requests: list[tuple[str, dict]] = []
        self.agents: list[str] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/public/v1/")
        endpoint = path.split("/")[0]
        params = dict(request.url.params)
        self.requests.append((endpoint, params))
        self.agents.append(request.headers.get("user-agent", ""))
        if endpoint in self.failing:
            status = self.failing[endpoint]
            if status == 429:
                return httpx.Response(429, headers={**JSON, "Retry-After": "30"}, text=fixture("rate_limited.json"))
            return httpx.Response(status, text="Bad Gateway")
        if endpoint == "search":
            title, artist = fold(params.get("title", "")).lower(), fold(params.get("artist", "")).lower()
            hits = [r for r in self.records
                    if title in fold(r["title"]).lower() or (artist and artist in fold(r["artist"]).lower())]
            results = [{"id": r["id"], "title": r["title"], "artist": r["artist"], "duration": r["duration"],
                        "sync": "manual", "score": 1, "url": r["url"],
                        "lrc_url": f"https://api.megalobiz.com/api/public/v1/lrc/{r['id']}?format=lrc"}
                       for r in hits][: int(params.get("limit", 10))]
            body = {"query": {"title": params.get("title"), "artist": params.get("artist")}, "count": len(results),
                    "results": results}
            return httpx.Response(200, headers=JSON, text=json.dumps(body, ensure_ascii=False))
        if endpoint == "lrc":
            lrc_id = int(path.split("/")[1])
            for r in self.records:
                if r["id"] == lrc_id:
                    return httpx.Response(200, headers=JSON, text=json.dumps(r, ensure_ascii=False))
            return httpx.Response(404, headers=JSON, text=fixture("lrc_not_found.json"))
        raise AssertionError(f"unexpected request: {request.url}")

    def endpoints(self) -> list[str]:
        return [endpoint for endpoint, _ in self.requests]

    def client(self, cache_dir: Path, *, budget: int = 60, now: datetime = NOW,
               user_agent: str = "caracole-test") -> PoliteClient:
        return PoliteClient(
            "megalobiz", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), cache_dir, user_agent=user_agent,
            transport=httpx.MockTransport(self.handler), sleep=self.sleeps.append, wall_clock=lambda: now,
        )
