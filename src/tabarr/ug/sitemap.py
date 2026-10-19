"""Ultimate Guitar's sitemaps, parsed into rows of the local tab index.

UG's sitemap index lists ``sitemap1``–``sitemapN`` and ``sitemap_last``, which
hold every tab page as ``tabs.ultimate-guitar.com/tab/{artist}/{song}-{type}-{id}``,
next to ukulele, news, forum and other sitemaps that hold no guitar tabs.

A numbered sitemap is about 25 MB of XML, so ``<loc>`` elements are found with
a regular expression over bytes rather than an XML parser.
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator
from typing import NamedTuple
from xml.sax.saxutils import unescape

from tabarr.normalize import ug_slug_key

KEEP_TYPES = frozenset({"chords", "tabs", "guitar-pro", "power"})

# Every type token seen in the sitemaps. "guitar-pro" comes first, so it is peeled
# off whole before any single-word token could match its last part.
TYPE_TOKENS = (
    "guitar-pro",
    "chords",
    "tabs",
    "bass",
    "ukulele",
    "power",
    "official",
    "video",
    "musescore",
    "drums",
)

_GZIP_MAGIC = b"\x1f\x8b"
_LOC = re.compile(rb"<loc>([^<]*)</loc>")
_TAB_URL = re.compile(r"https?://tabs\.ultimate-guitar\.com/tab/([^/]*)/([^/]*)-(\d+)")
_TAB_SITEMAP = re.compile(r"/sitemap(\d+|_last)\.xml\Z")
_XML_ENTITIES = {"&quot;": '"', "&apos;": "'"}


class IndexRow(NamedTuple):
    """One tab of the local index.

    The keys are canonical (``ug_slug_key``), for matching. ``path`` is the URL
    path after ``/tab/`` exactly as the sitemap lists it: UG serves a slugged tab
    only at its slugged URL (the bare ``/tab/{id}`` answers 404), and canonical
    keys can't be turned back into slugs (``the-rifles`` → ``rifles``).
    """

    tab_id: int
    artist_key: str
    song_key: str
    type: str
    path: str


def _peel_type(rest: str) -> tuple[str, str] | None:
    """Split ``de-musica-ligera-chords`` into (``de-musica-ligera``, ``chords``)."""
    for token in TYPE_TOKENS:
        if rest == token:
            return "", token
        if rest.endswith(token) and rest[-len(token) - 1] == "-":
            return rest[: -len(token) - 1], token
    return None


def parse_tab_url(url: str) -> IndexRow | None:
    """The index row for a tab page URL, or None when the index has no use for it.

    None for: other hosts, bare ``/tab/{id}`` URLs, unknown or unkept types
    (bass, ukulele, official, video, musescore, drums), and an artist or song
    whose key is empty once canonicalized (``/tab//autosmile-chords-65163``).
    """
    m = _TAB_URL.fullmatch(url)
    if m is None:
        return None
    artist_slug, rest, tab_id = m.groups()
    peeled = _peel_type(rest)
    if peeled is None or peeled[1] not in KEEP_TYPES:
        return None
    song_slug, kind = peeled
    artist_key, song_key = ug_slug_key(artist_slug), ug_slug_key(song_slug)
    if not artist_key or not song_key:
        return None
    return IndexRow(int(tab_id), artist_key, song_key, kind, url.split("/tab/", 1)[1])


def iter_locs(data: bytes) -> Iterator[str]:
    """Every ``<loc>`` URL in a sitemap or sitemap index, gzipped or not."""
    if data[:2] == _GZIP_MAGIC:
        data = gzip.decompress(data)
    for m in _LOC.finditer(data):
        loc = m.group(1).decode("utf-8", errors="replace").strip()
        if "&" in loc:
            loc = unescape(loc, _XML_ENTITIES)
        yield loc


def parse_sitemap_index(data: bytes) -> list[str]:
    """The child sitemap URLs of a sitemap index, in document order."""
    return list(iter_locs(data))


def tab_sitemaps(children: list[str]) -> list[str]:
    """The children that list tab pages: ``sitemapN`` in numeric order, then ``sitemap_last``."""
    numbered: dict[int, str] = {}
    last: str | None = None
    for url in children:
        m = _TAB_SITEMAP.search(url)
        if m is None:
            continue
        if m.group(1) == "_last":
            last = last or url
        else:
            numbered.setdefault(int(m.group(1)), url)
    return [numbered[n] for n in sorted(numbered)] + ([last] if last else [])


def sitemap_name(url: str) -> str:
    """The short name of a tab sitemap: ``"40"`` for ``sitemap40.xml``, ``"last"`` for
    ``sitemap_last.xml``. Any other sitemap is a ValueError."""
    m = _TAB_SITEMAP.search(url)
    if m is None:
        raise ValueError(f"not a tab sitemap: {url}")
    return m.group(1).lstrip("_")
