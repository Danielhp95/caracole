"""UG's letter listings of artists, faked as UG builds them (tests/fixtures/ug/bands/ holds real ones, 2026-11-17).

A listing page is UG's page store (helpers.ug_pages ``store_page_html``) whose ``store.page.data`` holds ``alpha``
("S", "0-9"), ``current_page``, ``page_count``, ``artists_count``, ``tabs_per_page`` (50) and ``artists``, 50 a page,
most popular first, each ``{id, name, tabscount, artist_url, tabs_last_update_timestamp, localized_name}``::

    from helpers.ug_bands import FakeDirectory, listed

    site = FakeDirectory({"s": [listed(634073, "Song Dongye (宋冬野)", tabs=42, bare=True), *fillers("s", 60)]})
    transport = httpx.MockTransport(site.handler)

``FakeDirectory`` answers every letter's pages (a letter it isn't given: one page, one artist), and for anything else
asks ``FakeUG`` (helpers.ug_pages: 宋冬野's artist page and tab pages, UG's 404 page else). It records each address asked
(``requests``), how many were in flight at once at most (``most``), and answers an address with another status where
``status`` says so (``{url: code}``) or with a page cut short where ``cut`` names it. With ``workers``, its first
requests wait for one another until that many are in flight (``hold`` seconds at most), so that a test sees whether
they are.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from caracole.ug.bands import LETTERS, PER_PAGE, listing_url
from helpers.ug_pages import NOT_FOUND, FakeUG, name_stripped, store_page_html

UPDATED = 1_790_000_000  # a tabs_last_update_timestamp: 2026-09-21


def listed(artist_id: int, name: str, *, tabs: int = 3, bare: bool | None = None,
           updated: int | None = UPDATED) -> dict[str, Any]:
    """One artist as a listing names them: a bare ``/artist/{id}`` for a name with a letter outside ASCII (``bare``
    says otherwise), else ``/artist/{name_stripped}_{id}``."""
    bare = not name.isascii() if bare is None else bare
    path = f"/artist/{artist_id}" if bare else f"/artist/{name_stripped(name)}_{artist_id}"
    return {"id": artist_id, "name": name, "tabscount": tabs, "artist_url": path,
            "tabs_last_update_timestamp": updated, "localized_name": name}


def fillers(letter: str, n: int, *, start: int = 1000) -> list[dict[str, Any]]:
    """``n`` artists of a letter, with slugged pages: "Sa 1000", "Sa 1001"…"""
    first = letter[0].upper() if letter != "0-9" else "9"
    return [listed(start + k, f"{first}a {start + k}", tabs=1) for k in range(n)]


def make_listing_html(letter: str, page: int, entries: list[dict[str, Any]], *, pages: int,
                      count: int | None = None) -> str:
    """One page of a letter's listing, as UG writes it."""
    return store_page_html({
        "artists": entries, "alpha": letter.upper(), "last_tabs": [], "current_page": page,
        "artists_count": count if count is not None else pages * PER_PAGE, "tabs_per_page": PER_PAGE,
        "page_count": pages,
    }, title="Bands Listing @ Ultimate-Guitar.Com")


class FakeDirectory:
    """UG's listings of ``listings`` ({letter: artists, most popular first}; every other letter one page of one
    artist, ``fillers``) and FakeUG's pages (the module's docstring). ``hold`` (seconds) keeps each request open, until
    ``workers`` are in flight at once, for a test of what is in flight."""

    def __init__(self, listings: dict[str, list[dict[str, Any]]] | None = None, *, ug: FakeUG | None = None,
                 hold: float = 0.0, workers: int = 0):
        self.listings = {letter: fillers(letter, 1, start=1000 + 100 * n) for n, letter in enumerate(LETTERS)}
        self.listings.update(listings or {})
        self.ug = ug or FakeUG()
        self.requests: list[str] = []
        self.status: dict[str, int] = {}
        self.cut: set[str] = set()
        self.hold, self.workers = hold, workers
        self.active = self.most = 0
        self._opened = False
        self._lock = threading.Condition()
        self.pages: dict[str, str] = {}
        self.build()

    def build(self) -> None:
        """Make the pages again from ``listings`` (after a test changes them)."""
        self.pages = {}
        for letter, artists in self.listings.items():
            pages = max(1, -(-len(artists) // PER_PAGE))
            for page in range(1, pages + 1):
                part = artists[(page - 1) * PER_PAGE:page * PER_PAGE]
                self.pages[listing_url(letter, page)] = make_listing_html(letter, page, part, pages=pages,
                                                                         count=len(artists))

    def asked(self, url: str) -> int:
        return self.requests.count(url)

    def handler(self, request: Any) -> Any:
        import httpx

        url = str(request.url)
        with self._lock:
            self.requests.append(url)
            self.active += 1
            self.most = max(self.most, self.active)
            if self.workers and not self._opened:  # the first ``workers`` requests wait for one another
                if self.active >= self.workers:
                    self._opened = True
                    self._lock.notify_all()
                self._lock.wait_for(lambda: self._opened, timeout=self.hold or 2.0)
        try:
            if self.hold and not self.workers:
                time.sleep(self.hold)
            if url in self.status:
                return httpx.Response(self.status[url], text=self.pages.get(url, NOT_FOUND))
            if url in self.pages:
                text = self.pages[url]
                if url in self.cut:  # its artists cut off: a page UG's server cut short
                    text = text.replace("&quot;artists&quot;:[", "&quot;artists&quot;:[],&quot;was&quot;:[", 1)
                return httpx.Response(200, text=text)
            if "/bands/" in url:
                return httpx.Response(404, text=NOT_FOUND)
            return self.ug.handler(request)
        finally:
            with self._lock:
                self.active -= 1
