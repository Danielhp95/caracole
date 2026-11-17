"""Ultimate Guitar's letter listings of artists, ``/bands/<letter>.htm``: one page read (``parse_listing``).

UG lists every artist under a letter, a page of 50 at a time: ``/bands/s.htm``, then ``/bands/s2.htm`` …
``/bands/s293.htm``, 27 listings, a–z and ``0-9`` (names that begin with a digit or a symbol, and every name whose
first letter isn't A–Z: Кино, Édith Piaf; "The Beatles" is under T). robots.txt opens ``/bands/`` to every crawler
(docs/superpowers/specs/2026-11-17-ug-artist-directory-design.md, "What UG has", checked on 2026-11-17). The page keeps
its data where UG's other pages do (``store.page.data``, ug/page.py ``read_page_data``):

- ``alpha`` (the listing: "S", "0-9"), ``current_page``, ``page_count``, ``artists_count`` (approximate: S's last page
  holds 23 where the count implies 25) and ``tabs_per_page`` (50);
- ``artists``, each ``{id, name, tabscount, artist_url, tabs_last_update_timestamp, localized_name}``, most popular
  first: ``tabscount`` counts every type of tab, Guitar Pro and bass included, and a bare ``artist_url``
  (``/artist/{id}``) is a name with a letter outside ASCII, an artist whose tabs UG's sitemaps list by bare ids alone.

A page that can't be read is a ``ListingParseError`` (a ``PageParseError``, a provider error, never a listing with no
artist): no data, a listing or a page other than the one asked for, or one cut short (fewer than ``tabs_per_page``
artists before the last page). An entry that names no artist (no id, no name, no artist page) is passed over: a
listing never removes an artist, so one row less is no miss either.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from caracole.ug.page import PageParseError, json_int, read_page_data
from caracole.ug_urls import ARTIST_HOST, artist_page_address

LETTERS = ("0-9", *"abcdefghijklmnopqrstuvwxyz")  # UG's 27 listings, in the order caracole reads them
PER_PAGE = 50  # artists a listing page holds but the last
_BARE = re.compile(r"/artist/\d+")
_SLUGGED = re.compile(r"/artist/(.+)_\d+")


class ListingParseError(PageParseError):
    """A listing page that can't be read: no data, another page than the one asked for, or one cut short."""


@dataclass(frozen=True)
class ListedArtist:
    """One artist a listing names: UG's id, its name as UG writes it, its page's slug (``slug``, "" for a bare page,
    ``/artist/{id}``), its page's address (``url``, as ``ug_urls.artist_page_address`` writes it), how many tabs of
    every type UG counts (``tabs``) and when one last changed (``updated``, seconds since the epoch; None for none)."""

    artist_id: int
    name: str
    slug: str
    url: str
    tabs: int
    updated: int | None

    @property
    def bare(self) -> bool:
        return not self.slug


@dataclass(frozen=True)
class ListingPage:
    """One page of a letter's listing (``parse_listing``): the listing (``letter``, caracole's: "s", "0-9"), its page
    and pages, how many artists UG says it has, and the artists of the page, in UG's order (popularity)."""

    letter: str
    page: int
    pages: int
    count: int
    artists: tuple[ListedArtist, ...]

    @property
    def last(self) -> bool:
        return self.page >= self.pages


def listing_url(letter: str, page: int = 1) -> str:
    """The address of a listing's page: ``/bands/s.htm`` for page 1, ``/bands/s2.htm`` for page 2."""
    if letter not in LETTERS:
        raise ValueError(f"no UG listing {letter!r}: they are {', '.join(LETTERS)}")
    if page < 1:
        raise ValueError(f"page must be 1 or more, not {page}")
    return f"{ARTIST_HOST}/bands/{letter}{page if page > 1 else ''}.htm"


def parse_listing(html: str | bytes, letter: str, page: int, *, url: str | None = None) -> ListingPage:
    """A listing page, the ``page``-th of ``letter``'s, or ``ListingParseError`` (the module's docstring)."""
    def bad(why: str) -> ListingParseError:
        return ListingParseError("ug", url, None, why)

    try:
        data = read_page_data(html, url=url)
    except PageParseError as e:
        raise bad(e.message or "no data") from e

    alpha = data.get("alpha")
    if not isinstance(alpha, str) or alpha.strip().lower() != letter:
        raise bad(f"the listing of {alpha!r}, not of {letter!r}")
    current, pages, count = (json_int(data.get(k)) for k in ("current_page", "page_count", "artists_count"))
    if current != page:
        raise bad(f"page {current!r} of the listing, not page {page}")
    if pages is None or pages < page:
        raise bad(f"a page count of {pages!r} for page {page}")
    entries = data.get("artists")
    if not isinstance(entries, list):
        raise bad("no list of artists")
    per_page = json_int(data.get("tabs_per_page")) or PER_PAGE
    if page < pages and len(entries) < per_page:
        raise bad(f"{len(entries)} artists on page {page} of {pages}: cut short")
    artists = tuple(a for a in map(_artist, entries) if a is not None)
    return ListingPage(letter, page, pages, max(count or 0, 0), artists)


def _artist(entry: Any) -> ListedArtist | None:
    """One entry of ``artists``, or None for one that names no artist with a page."""
    if not isinstance(entry, Mapping):
        return None
    artist_id = json_int(entry.get("id"))
    name = entry.get("name")
    link = entry.get("artist_url")
    if artist_id is None or artist_id < 1 or not isinstance(name, str) or not name.strip() or not isinstance(link, str):
        return None
    url = artist_page_address(ARTIST_HOST + link if link.startswith("/") else link)
    if url is None:
        return None
    path = url[len(ARTIST_HOST):]
    slugged = _SLUGGED.fullmatch(path)
    if slugged is None and not _BARE.fullmatch(path):
        return None
    updated = json_int(entry.get("tabs_last_update_timestamp"))
    return ListedArtist(artist_id, " ".join(name.split()), slugged.group(1) if slugged else "", url,
                        max(json_int(entry.get("tabscount")) or 0, 0), updated if updated and updated > 0 else None)
