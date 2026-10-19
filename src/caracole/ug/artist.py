"""Ultimate Guitar artist pages: every tab of an artist, bare-id tabs included.

About a tenth of UG's tabs are listed in the sitemaps as a bare ``/tab/{id}``,
including every tab by an artist whose name isn't ASCII, so the local index
can't see them. The artist page lists them all with their ``song_name`` in the
original script, 100 tabs per page, filterable by type
(``?filter=chords|tabs|guitar_pro|power&page=N``).

The page keeps its data where tab pages do (``store.page.data``):
``data.artist`` (id, name, ``name_stripped``), ``data.other_tabs`` (tab dicts
shaped like a tab page's versions, mixed with links to UG's paid app, which
have no ``type``), ``data.pagination`` and ``data.filters.types``. Their links
are relative, such as ``/artist/soda_stereo_2946?filter=chords``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from caracole.ug.page import PageParseError, UGVersion, json_int, read_page_data, read_versions

WWW = "https://www.ultimate-guitar.com"

# caracole's kind → the value of the artist page's ``filter`` parameter.
KIND_FILTERS = {"chords": "chords", "tabs": "tabs", "guitar-pro": "guitar_pro", "power": "power"}
_FILTER_KINDS = {value: kind for kind, value in KIND_FILTERS.items()}


@dataclass(frozen=True)
class UGArtistPage:
    """One page of an artist's tab list.

    ``url`` is the artist's page without filter or page number. ``tabs`` are
    the tabs on this page, of every type; links to UG's paid app are left out.
    ``page`` is this page's number and ``pages`` the highest page number UG
    links to. ``filters`` takes each kind UG offers a filter for (chords, tabs,
    guitar-pro, power) to the absolute URL of that filtered list.
    """

    artist_id: int
    name: str
    url: str
    tabs: tuple[UGVersion, ...]
    page: int
    pages: int
    filters: Mapping[str, str]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _entries(value: Any) -> list[Mapping[str, Any]]:
    """The dicts of a JSON list, such as ``pagination.pages`` or ``filters.types``."""
    return [e for e in value if isinstance(e, Mapping)] if isinstance(value, list) else []


def _links(entries: list[Mapping[str, Any]]) -> list[str]:
    return [e["url"] for e in entries if isinstance(e.get("url"), str) and e["url"]]


def _without_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _filters(entries: list[Mapping[str, Any]], base: str) -> dict[str, str]:
    """kind → absolute URL, read from each filter link's ``filter`` parameter."""
    filters: dict[str, str] = {}
    for link in _links(entries):
        absolute = urljoin(base, link)
        kind = _FILTER_KINDS.get(parse_qs(urlsplit(absolute).query).get("filter", [""])[0])
        if kind is not None:
            filters.setdefault(kind, absolute)
    return filters


def parse_artist_page(html: str | bytes, *, url: str | None = None) -> UGArtistPage:
    """Parse an artist page. ``url`` is the page's address; UG's relative links resolve against it.

    The artist's ``url`` is taken from the path UG's own links use, else from
    ``url``, else built from ``name_stripped`` and the id.
    """
    data = read_page_data(html, url=url)
    artist = _mapping(data.get("artist"))
    artist_id = json_int(artist.get("id"))
    if artist_id is None:
        raise PageParseError("ug", url, None, "no usable data.artist")
    tabs = read_versions(data, "other_tabs", url=url)
    base = url or WWW
    pagination = _mapping(data.get("pagination"))
    page_entries = _entries(pagination.get("pages"))
    filter_entries = _entries(_mapping(data.get("filters")).get("types"))

    links = _links(page_entries) + _links(filter_entries)
    if links:
        artist_url = _without_query(urljoin(base, links[0]))
    elif url:
        artist_url = _without_query(url)
    else:
        artist_url = f"{WWW}/artist/{artist.get('name_stripped') or ''}_{artist_id}"

    page = json_int(pagination.get("current")) or json_int(data.get("current_page")) or 1
    listed = [json_int(e.get("page")) for e in page_entries]
    return UGArtistPage(
        artist_id=artist_id,
        name=str(artist.get("name") or ""),
        url=artist_url,
        tabs=tabs,
        page=page,
        pages=max([page, *(n for n in listed if n)]),
        filters=_filters(filter_entries, base),
    )


def artist_page_url(base_url: str, *, kind: str | None = None, page: int = 1) -> str:
    """The URL of one page of an artist's tab list, optionally filtered to one kind.

    ``artist_page_url(".../artist/soda_stereo_2946", kind="chords", page=2)`` is
    ``.../artist/soda_stereo_2946?filter=chords&page=2``. Page 1 has no page
    parameter. Any query already on ``base_url`` is replaced.
    """
    if kind is not None and kind not in KIND_FILTERS:
        raise ValueError(f"no artist-page filter for kind {kind!r}")
    if page < 1:
        raise ValueError(f"page must be 1 or more, not {page}")
    query = [("filter", KIND_FILTERS[kind])] if kind else []
    if page > 1:
        query.append(("page", str(page)))
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), urlencode(query), ""))
