"""Ultimate Guitar's sitemaps, parsed into rows of the local tab index.

UG's sitemap index lists ``sitemap1``–``sitemapN`` and ``sitemap_last``, which
hold every tab page as ``tabs.ultimate-guitar.com/tab/{artist}/{song}-{type}-{id}``,
and ``sitemap_ukulele1``–``sitemap_ukuleleN``, which hold its "Ukulele Chords" pages
(``…/{song}-ukulele-{id}``, about 150,000 of them; ``sitemap_last`` lists the newest
too), next to news, forum and other sitemaps that hold no tabs.

A numbered sitemap is about 25 MB of XML, so ``<loc>`` elements are found with
a regular expression over bytes rather than an XML parser.
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator
from typing import NamedTuple
from xml.sax.saxutils import unescape

from caracole.normalize import ug_slug_key

# The types the index keeps: those caracole uses (ug/page.py ``KINDS``), UG's "Ukulele Chords" among them (a sheet
# for a song with no guitar chords, ug/fetch.py). Every other type's tab is counted, by type, and left out
# (``classify_tab_url``), Guitar Pro and Power Tab files among them.
KEEP_TYPES = frozenset({"chords", "tabs", "ukulele"})

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

# Why a tab URL has no index row (``classify_tab_url``), besides an unkept type's token.
BARE = "bare"  # /tab/{id}: no artist or song in the URL, so only the artist's page leads to it
UNRECOGNIZED = "unrecognized"  # no type token, an empty artist or song key, or not a tab page

_GZIP_MAGIC = b"\x1f\x8b"
_LOC = re.compile(rb"<loc>([^<]*)</loc>")
_TAB_URL = re.compile(r"https?://tabs\.ultimate-guitar\.com/tab/([^/]*)/([^/]*)-(\d+)")
_BARE_TAB_URL = re.compile(r"https?://tabs\.ultimate-guitar\.com/tab/\d+")
_TAB_SITEMAP = re.compile(r"/sitemap(\d+|_last|_ukulele\d+)\.xml\Z")
UKULELE = "ukulele"  # the short names of the ukulele sitemaps start so: "ukulele1"
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
    (bass, official, video, musescore, drums), and an artist or song
    whose key is empty once canonicalized (``/tab//autosmile-chords-65163``).
    ``classify_tab_url`` says which.
    """
    row = classify_tab_url(url)
    return row if isinstance(row, IndexRow) else None


def classify_tab_url(url: str) -> IndexRow | str:
    """The index row for a tab page URL, as ``parse_tab_url`` gives it, or why there is none:
    ``BARE`` for a bare ``/tab/{id}``, the type for a type the index doesn't keep (``"bass"``),
    or ``UNRECOGNIZED``."""
    m = _TAB_URL.fullmatch(url)
    if m is None:
        return BARE if _BARE_TAB_URL.fullmatch(url) else UNRECOGNIZED
    artist_slug, rest, tab_id = m.groups()
    peeled = _peel_type(rest)
    if peeled is None:
        return UNRECOGNIZED
    song_slug, kind = peeled
    if kind not in KEEP_TYPES:
        return kind
    artist_key, song_key = ug_slug_key(artist_slug), ug_slug_key(song_slug)
    if not artist_key or not song_key:
        return UNRECOGNIZED
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
    """The children that list tab pages: ``sitemapN`` in numeric order, then ``sitemap_ukuleleN`` in
    numeric order, then ``sitemap_last``."""
    by_name: dict[str, str] = {}
    for url in children:
        m = _TAB_SITEMAP.search(url)
        if m is not None:
            by_name.setdefault(m.group(1).lstrip("_"), url)
    return [by_name[n] for n in sorted(by_name, key=sitemap_order)]


def sitemap_order(name: str) -> tuple[int, int]:
    """Where a tab sitemap goes by its short name: the numbered ones, the ukulele ones, then ``last``."""
    if name.isdigit():
        return (0, int(name))
    if name.startswith(UKULELE) and name[len(UKULELE):].isdigit():
        return (1, int(name[len(UKULELE):]))
    return (2, 0)


def sitemap_name(url: str) -> str:
    """The short name of a tab sitemap: ``"40"`` for ``sitemap40.xml``, ``"ukulele1"`` for
    ``sitemap_ukulele1.xml``, ``"last"`` for ``sitemap_last.xml``. Any other sitemap is a ValueError."""
    m = _TAB_SITEMAP.search(url)
    if m is None:
        raise ValueError(f"not a tab sitemap: {url}")
    return m.group(1).lstrip("_")


def sitemap_label(name: str) -> str:
    """The file name of the tab sitemap with that short name: ``sitemap40.xml``, ``sitemap_ukulele1.xml``,
    ``sitemap_last.xml``."""
    return f"sitemap{name}.xml" if name.isdigit() else f"sitemap_{name}.xml"
