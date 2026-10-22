"""gtptabs.com: Guitar Pro files caracole may download for you.

Ultimate Guitar's robots.txt closes its download endpoint, and caracole uses none of its
Guitar Pro pages (inbox.py files a file you download anywhere yourself). gtptabs.com's
robots.txt leaves its download endpoint open, so caracole fetches one Guitar Pro or Power
Tab file there for each song that has none (gtptabs_fetch.py). What the site looked like on 19 October 2026:

- **robots.txt** closes /ru/ (a Russian copy of every page: half of each sitemap),
  /storage/ (each artist's "Download all" archive), /search/, /profile/, /message/,
  /index.php, /tabs/upload.html and /advertisement.html (``http.ROBOTS_DISALLOW``).
  Nothing else under /tabs/ is closed.
- **The sitemaps**, ``SITEMAP_INDEX_URL`` and its six children, all dated June 2015,
  list each artist page, ``/tabs/{letter}/{artist}.html``, and each song page,
  ``/tabs/{letter}/{artist}/{song}.html``, as they were then. Slugs are ASCII. People
  are filed last name first ("John, Elton": ``john-elton``), and a leading "The" goes
  last ("Beatles, The": ``beatles-the``). A second upload of a title adds ``-2``, a
  third ``-3``, so "Song 2 (2)" is ``song-2-2.html``: a trailing number may be either.
- **An artist page** lists every tab of the artist, uploads since 2015 included, on one
  page (Metallica's 1,102 too): for each, its page, its title with " (N)" after the
  N-th upload, its download id (``data-item``), its format (a class: gp3, gp4, gp5,
  gpx, gp), its stars (0 to 5), its size and, for newer uploads, its instruments.
- **A download**, ``/tabs/download/{id}.html``, answers the file itself, to anyone and
  with no login: HTTP 200, ``application/octet-stream``, ``Content-Disposition:
  attachment``. An id the site doesn't have answers 404.

What a downloaded file is, its first bytes tell (:func:`sniff`), never its name.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import NamedTuple

from selectolax.lexbor import LexborHTMLParser, LexborNode

from caracole.http import ProviderError, robots_disallows
from caracole.normalize import clean_title, fold, slug_key, ug_slug_key

PROVIDER = "gtptabs"
HOST = "gtptabs.com"
BASE_URL = f"https://{HOST}"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemapGoogle.xml"

# Every slug the sitemaps list is lowercase ASCII letters, digits and hyphens; a URL with
# anything else in it is no page caracole reads, and never lands in a link it writes.
_PAGE = re.compile(r"https?://gtptabs\.com/(tabs/\d{1,4}/([a-z0-9-]{1,200}))(?:/([a-z0-9-]{1,200}))?\.html")
_SITEMAP = re.compile(r"https?://gtptabs\.com/sitemapGoogle(\d{1,4})\.xml")
_VERSION = re.compile(r"(.+)-(\d{1,3})")  # a slug's upload number
_TITLE_VERSION = re.compile(r"(.*\S)\s*\((\d{1,3})\)")  # "Song 2 (2)"
_SIZE = re.compile(r"\(\s*(\d{1,7}(?:\.\d{1,3})?)\s*Kb\s*\)", re.IGNORECASE)
_ID = re.compile(r"[0-9]{1,12}")
_INSTRUMENTS = {
    "electroGuitarLabelSmall": "electric guitar",
    "acousticGuitarLabelSmall": "acoustic guitar",
    "bassGuitarLabelSmall": "bass",
    "drumsLabelSmall": "drums",
    "vocalsLabelSmall": "vocals",
    "keyboardsLabelSmall": "keyboards",
    "violinLabelSmall": "violin",
}
_GUITARS = frozenset({"electric guitar", "acoustic guitar"})


class GtpTabsParseError(ProviderError):
    """A gtptabs.com page without the expected markup: a provider error, never a miss."""

    def __init__(self, message: str, *, url: str | None = None):
        super().__init__(PROVIDER, url=url, message=message)


# --- URLs ------------------------------------------------------------------------------------


def page_url(path: str) -> str:
    """The address of a page, from its path as the index keeps it (``tabs/2/blur.html``)."""
    return f"{BASE_URL}/{path}"


def download_url(tab_id: int) -> str:
    return f"{BASE_URL}/tabs/download/{tab_id}.html"


def https(url: str) -> str:
    """A gtptabs.com address over https. The sitemaps list http:// ones, which the site also
    answers; asked for over https, each costs no redirect."""
    return "https://" + url[len("http://"):] if url.startswith(f"http://{HOST}/") else url


def sitemap_name(url: str) -> str | None:
    """``"6"`` for the child sitemap ``sitemapGoogle6.xml``; None for any other URL."""
    m = _SITEMAP.fullmatch(url)
    return m.group(1) if m else None


# --- the index ---------------------------------------------------------------------------------


class IndexRow(NamedTuple):
    """One page a sitemap lists, by its path: an artist page, or a song page.

    The keys are caracole's (normalize.py), for matching. An artist page has no title:
    ``title_key`` and ``base_key`` are "". ``base_key`` is the title without an upload
    number ("song-2" for ``song-2-2``), or the title when it has none.
    """

    path: str
    artist_path: str
    artist_key: str
    title_key: str
    base_key: str


def _artist_key(slug: str) -> str:
    """The key of an artist slug: ``ug_slug_key``'s, once the "the" the site puts last is gone."""
    words = [w for w in fold(slug).split("-") if w]
    if len(words) > 1 and words[-1] == "the":
        words = words[:-1]
    return ug_slug_key("-".join(words))


def _base(key: str) -> str:
    m = _VERSION.fullmatch(key)
    return m.group(1) if m is not None and int(m.group(2)) >= 2 else key


def parse_page_url(url: str) -> IndexRow | None:
    """The index row of a sitemap URL, or None when it is no artist or song page, or robots.txt
    closes it (every /ru/ copy)."""
    m = _PAGE.fullmatch(url)
    if m is None:
        return None
    base, artist_slug, song_slug = m.groups()
    artist_path = f"{base}.html"
    path = f"{base}/{song_slug}.html" if song_slug is not None else artist_path
    if robots_disallows(page_url(path)) is not None:
        return None
    artist = _artist_key(artist_slug)
    if not artist:
        return None
    if song_slug is None:
        return IndexRow(path, artist_path, artist, "", "")
    title = ug_slug_key(song_slug)
    if not title:
        return None
    return IndexRow(path, artist_path, artist, title, _base(title))


def artist_keys(name: str) -> tuple[str, ...]:
    """The keys an artist may have in the index: the name's own (``slug_key``) and, for a name
    of two words or more, the same with its last word first, as the site files people."""
    own = slug_key(name)
    if not own:
        return ()
    words = own.split("-")
    rotated = "-".join([words[-1], *words[:-1]]) if len(words) > 1 else own
    return tuple(dict.fromkeys((own, rotated)))


def title_key(title: str) -> str:
    """The key a song's title meets the site's titles with: Spotify's suffixes go first."""
    return slug_key(clean_title(title))


# --- artist pages ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class GtpTab:
    """One tab on an artist page. ``version`` is its upload number, 1 for the first."""

    tab_id: int
    title: str
    version: int
    path: str
    format: str
    stars: int
    size_kb: float | None
    instruments: tuple[str, ...]

    @property
    def guitar(self) -> bool:
        """Whether it may hold a guitar part: it lists one, or (an older upload) no instrument."""
        return not self.instruments or any(i in _GUITARS for i in self.instruments)


def parse_artist_page(html: str, url: str) -> list[GtpTab]:
    """Every tab an artist page lists. A page without the artist's heading and list (a notice
    served in its place, say) is a ``GtpTabsParseError``; an entry that doesn't read as a tab
    of this site (no download id, a link outside /tabs/) is left out."""
    tree = LexborHTMLParser(html)
    if tree.css_first("div.autorInfo h1") is None or tree.css_first("div.autorSongs") is None:
        raise GtpTabsParseError("not an artist page: no artist heading and list of tabs", url=url)
    tabs = []
    for node in tree.css("div.autorSongs div.autorSong"):
        tab = _tab(node)
        if tab is not None:
            tabs.append(tab)
    return tabs


def _tab(node: LexborNode) -> GtpTab | None:
    link = node.css_first("div.title > a[href]")
    rating = node.css_first("div.ratingSmall[data-item]")
    if link is None or rating is None:
        return None
    href = link.attributes.get("href") or ""
    row = parse_page_url(BASE_URL + href) if href.startswith("/tabs/") else None
    item = rating.attributes.get("data-item") or ""
    if row is None or not row.title_key or not _ID.fullmatch(item):
        return None
    classes = (node.attributes.get("class") or "").split()
    title, version = _title(" ".join(link.text().split()))
    info = node.css_first("div.songInfo")
    size = _SIZE.search(info.text() if info is not None else "")
    labels = (
        c for label in node.css("div.instrumentsSmall div.labelSmall")
        for c in (label.attributes.get("class") or "").split() if c != "labelSmall"
    )
    return GtpTab(
        tab_id=int(item),
        title=title,
        version=version,
        path=row.path,
        format=next((c for c in classes if c != "autorSong"), ""),
        stars=len(rating.css("a.active")),
        size_kb=float(size.group(1)) if size else None,
        instruments=tuple(_INSTRUMENTS.get(c, c.removesuffix("LabelSmall")) for c in labels),
    )


def _title(text: str) -> tuple[str, int]:
    """("Song 2", 2) for "Song 2 (2)"; a title without an upload number is the first upload."""
    m = _TITLE_VERSION.fullmatch(text)
    return (m.group(1), int(m.group(2))) if m is not None else (text, 1)


# --- files ---------------------------------------------------------------------------------------------

# Guitar Pro 3 to 5 start with their version, a length byte and a 30-byte field.
_GP_VERSION = re.compile(rb"FICHIER GUITAR PRO [vL]([345])\.\d{2}")
_ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError, NotImplementedError)


def sniff(data: bytes) -> str | None:
    """The extension of a Guitar Pro or Power Tab file (.gp3, .gp4, .gp5, .gpx, .gp, .ptb), told by its
    first bytes; None for anything else, such as an error page served in its place."""
    if data.startswith(b"ptab"):
        return ".ptb"
    if data[:4] in (b"BCFZ", b"BCFS"):  # Guitar Pro 6's container, compressed or not
        return ".gpx"
    if data.startswith(b"PK\x03\x04"):  # Guitar Pro 7 and later: a zip holding the score
        return ".gp" if _holds_a_score(data) else None
    if len(data) >= 31:
        m = _GP_VERSION.fullmatch(data[1:1 + data[0]])
        if m is not None:
            return f".gp{m.group(1).decode()}"
    return None


def _holds_a_score(data: bytes) -> bool:
    """Whether a zip lists Content/score.gpif, read from its directory alone: nothing is unpacked."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "Content/score.gpif" in z.namelist()
    except _ZIP_ERRORS:
        return False
