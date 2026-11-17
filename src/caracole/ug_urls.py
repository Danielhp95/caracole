"""Ultimate Guitar's addresses as an address bar shows them: one reading of them, for overrides.toml and a link pasted.

The standard library alone, as youtube_urls.py: overrides.py reads every ``[pin]`` and ``[artist_url]`` with it
(``ug_path``, ``pin_url``, ``artist_page_address``), and the library page's search box a link pasted into it
(``read_link``, web/ug_link_routes.py), so neither loads an HTTP client or a page parser for it. library.js's
``ugLink`` reads the same shapes, held to ``read_link`` by tests/helpers/ug_links.py's one list.

- **A tab page**: ``/tab/{id}`` or ``/tab/{artist}/{song}-{type}-{id}`` on one of UG's hosts (``UG_HOST``: www,
  tabs, the bare domain, a language edition's), its query, fragment and trailing slash dropped; caracole asks for it
  on the tabs host (``pin_url``). A slugged one names its type (``TYPE_TOKENS``, as UG's sitemaps write them).
- **An artist page**: ``/artist/{name}_{id}`` or ``/artist/{id}``, asked for on the www host
  (``artist_page_address``), its ``?filter=`` and ``?page=`` dropped.
- Anything else (UG's home, ``/explore``, a search, a forum page, a tab's download or print page, a link with words
  around it) is no UG link.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

# UG's hosts as an address bar shows them, in any case: www and tabs, the bare domain, and a language edition's (UG's
# tab pages link to es.ultimate-guitar.com as their Spanish edition). Whichever host it was pasted from, caracole asks
# for a tab page on tabs and an artist page on www.
UG_HOST = re.compile(r"(?:(?:www|tabs|[a-z]{2})\.)?ultimate-guitar\.com")
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
# A tab page is /tab/<id> or /tab/<artist>/<song>-<type>-<id>.
TAB_PATH = re.compile(r"/tab/(?:[^/]+/)?(?:[^/]*-)?(\d+)")
# A slugged tab page, /tab/<artist>/<song>-<type>-<id>: UG serves one only there.
SLUGGED = re.compile(r"/tab/[^/]+/([^/]+)-\d+")
TAB_HOST = "https://tabs.ultimate-guitar.com"
# An artist page is /artist/<name>_<id> (/artist/soda_stereo_2946) or, for some artists, /artist/<id> alone (宋冬野's
# /artist/634073); /artist/<name> without the number answers 404.
ARTIST_PATH = re.compile(r"/artist/(?:[^/?#]+_)?\d+")
ARTIST_HOST = "https://www.ultimate-guitar.com"
# Every type token UG's sitemaps write in a slugged tab's address (ug/sitemap.py). "guitar-pro" comes first, so it is
# peeled off whole before any single-word token could match its last part.
TYPE_TOKENS = ("guitar-pro", "chords", "tabs", "bass", "ukulele", "power", "official", "video", "musescore", "drums")
# What surrounds a link pasted, and what a link never holds: controls, spaces and the like, the same characters
# library.js's ugLink names, so that both read a text alike (neither str.strip's nor JavaScript's \s, which differ).
SPACES = "\x00-\x20\x7f-\xa0  -     　﻿"
_EDGES = re.compile(f"^[{SPACES}]+|[{SPACES}]+$")
_SPACED = re.compile(f"[{SPACES}]")


def ug_path(url: Any) -> str | None:
    """The path of an address on one of UG's hosts (``UG_HOST``), without its query, fragment and trailing slash;
    None for anything else.

    It is taken as an address bar shows it: without ``https://``, without ``www.``, with capitals in the host, on a
    language edition's host. The query and fragment of a link (``?ref=``, the artist page's own ``?filter=chords``,
    ``?page=2``, ``#…``) go: caracole asks for the bare page.
    """
    if not isinstance(url, str):
        return None
    text = url.strip()
    if not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:  # a link urllib can't parse ("Invalid IPv6 URL"): no UG page
        return None
    if parts.scheme not in ("http", "https") or not UG_HOST.fullmatch(parts.netloc.lower()):
        return None
    return parts.path.rstrip("/")


def pin_url(value: str) -> str:
    """A pinned page's address: the URL as pasted, on the tabs host, over https and without its query, fragment and
    trailing slash; for a bare tab id, the bare ``/tab/{id}`` page. ``value`` passed ``overrides.tab_id_from_url``."""
    text = value.strip()
    if text.isdigit():
        return f"{TAB_HOST}/tab/{int(text)}"
    return TAB_HOST + (ug_path(text) or "")


def artist_page_address(url: Any) -> str | None:
    """A UG artist page's address, on the www host, over https and without its query, fragment and trailing slash;
    None if ``url`` isn't one.

    Both of UG's shapes are artist pages: ``/artist/<name>_<id>`` and ``/artist/<id>``. It may be written as an address
    bar shows it (``ug_path``).
    """
    path = ug_path(url)
    return ARTIST_HOST + path if path is not None and ARTIST_PATH.fullmatch(path) else None


@dataclass(frozen=True)
class UgLink:
    """A UG link pasted: its ``kind`` ("tab" or "artist"), the page's address as caracole asks for it (``url``:
    ``pin_url``'s for a tab, ``artist_page_address``'s for an artist), a tab's id (``tab_id``) and the type its slug
    names (``type``, one of ``TYPE_TOKENS``; None for a bare ``/tab/{id}`` or a slug that names none)."""

    kind: str
    url: str
    tab_id: int | None = None
    type: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "url": self.url, "tab_id": self.tab_id, "type": self.type}


def read_link(text: Any) -> UgLink | None:
    """The UG page a text pasted into a search box is a link to (the module's docstring), or None: the text, its
    spaces around it (``SPACES``) aside, is one address, with no space in it, on one of UG's hosts."""
    if not isinstance(text, str):
        return None
    link = _EDGES.sub("", text)
    if not link or _SPACED.search(link):
        return None
    path = ug_path(link)
    if path is None:
        return None
    tab = TAB_PATH.fullmatch(path)
    if tab is not None:
        return UgLink("tab", TAB_HOST + path, int(tab.group(1)), _slug_type(path))
    if ARTIST_PATH.fullmatch(path):
        return UgLink("artist", ARTIST_HOST + path)
    return None


def _slug_type(path: str) -> str | None:
    """The type a slugged tab page's address names (``/tab/radiohead/creep-chords-4169`` is "chords"), as UG's
    sitemaps write it; None for a bare ``/tab/{id}`` or a slug that names none."""
    slugged = SLUGGED.fullmatch(path)
    if slugged is None:
        return None
    rest = slugged.group(1)
    return next((token for token in TYPE_TOKENS if rest == token or rest.endswith("-" + token)), None)
