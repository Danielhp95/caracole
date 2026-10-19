"""LaCuerda (acordes.lacuerda.net): chord sheets for Spanish songs.

Ultimate Guitar's sitemaps hide every artist with an accented name behind bare
ids, but a LaCuerda artist URL can be built from the name. What the pages look
like (captured 18 October 2026):

- **Artist slugs** are the name lowercased, with accents stripped, "ñ" written
  "ni", each space turned into "_" and any other punctuation removed without a
  trace ("Fito & Fitipaldis" → ``fito__fitipaldis``). A leading article is
  dropped ("Las Pastillas del Abuelo" → ``pastillas_del_abuelo``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tabarr.http import ProviderError
from tabarr.normalize import fold

BASE_URL = "https://acordes.lacuerda.net"
PROVIDER = "lacuerda"

ACORDES = "R"
# Version types by lcd letter, labelled as the song page labels them. The artist
# page's filter bar also offers K, which no captured page labelled.
TYPE_NAMES = {
    "R": "Letra y Acordes",
    "T": "Tablatura",
    "B": "Tab p/Bajo",
    "D": "Batería",
    "H": "Armónica",
}


class LaCuerdaParseError(ProviderError):
    """A LaCuerda page without the expected markup: a provider error, never a miss."""

    def __init__(self, message: str, *, url: str | None = None):
        super().__init__(PROVIDER, url=url, message=message)


@dataclass(frozen=True)
class LCSong:
    """A song on a LaCuerda artist page.

    ``types`` has one letter per version, version 1 first ("RHRTTTDTB": version
    2 is a harmonica part). ``ranking`` lists the version numbers in LaCuerda's
    order, which groups them by type and puts the best first within a type.
    """

    slug: str
    title: str
    types: str
    ranking: tuple[int, ...]


def parse_lcd(lcd: str) -> tuple[str, tuple[int, ...]]:
    """Split an ``lcd`` code such as "RHRTTTDTB-314865972" into types and ranking.

    Each ranking character is read as a base-36 digit, so a tenth version would
    be "a" (no real page showed more than nine). A ranking that isn't one rank
    per version falls back to version order.
    """
    letters, _, digits = lcd.strip().partition("-")
    letters = letters.upper()
    in_order = tuple(range(1, len(letters) + 1))
    if len(digits) != len(letters):
        return letters, in_order
    try:
        ranking = tuple(int(c, 36) for c in digits)
    except ValueError:
        return letters, in_order
    if sorted(ranking) != list(in_order):
        return letters, in_order
    return letters, ranking


def best_acordes_version(song: LCSong) -> int | None:
    """The best-ranked "Letra y Acordes" version of a song, or None if it has none."""
    for n in song.ranking:
        if 1 <= n <= len(song.types) and song.types[n - 1] == ACORDES:
            return n
    return None

_ARTICLES = frozenset({"el", "la", "los", "las", "the"})
_NOT_SLUG = re.compile(r"[^a-z0-9 ]")
_AND_WORD = re.compile(r"(?i)(?<!\S)y(?!\S)")


def _words(name: str) -> list[str]:
    """The name's slug words. Removed punctuation leaves an empty word behind."""
    s = unicodedata.normalize("NFC", name).lower().replace("ñ", "ni")
    s = _NOT_SLUG.sub("", fold(" ".join(s.split())))
    return s.strip().split(" ") if s.strip() else []


def _join(words: list[str]) -> str:
    return "_".join(words)


def artist_slug(name: str) -> str:
    """LaCuerda's slug for an artist: "Joaquín Sabina" → ``joaquin_sabina``.

    Returns "" when nothing of the name survives (a name in Chinese characters,
    say); LaCuerda can't be asked about that artist.
    """
    words = _words(name)
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return _join(words)


def artist_slug_candidates(name: str) -> tuple[str, ...]:
    """Slugs worth trying for an artist, best guess first.

    After :func:`artist_slug` come the slug that keeps a leading article and the
    slug with "y" and "&" swapped, because sources disagree on both
    (Spotify's "Fito y Fitipaldis" is LaCuerda's ``fito__fitipaldis``). Each
    extra candidate costs a request only when the ones before it miss.
    """
    variants = [name]
    if _AND_WORD.search(name):
        variants.append(_AND_WORD.sub("&", name))
    if "&" in name:
        variants.append(name.replace("&", " y "))
    out: list[str] = []
    for variant in variants:
        for slug in (artist_slug(variant), _join(_words(variant))):
            if slug and slug not in out:
                out.append(slug)
    return tuple(out)


def artist_url(slug: str) -> str:
    """The artist page: ``artist_url("soda_stereo")`` → ".../soda_stereo/"."""
    if not slug:
        raise ValueError("empty LaCuerda artist slug")
    return f"{BASE_URL}/{slug}/"


def version_url(artist: str, song: str, n: int) -> str:
    """The page of version ``n`` of a song: ``song.shtml`` for 1, ``song-n.shtml`` after that."""
    if not artist or not song:
        raise ValueError("empty LaCuerda artist or song slug")
    if n < 1:
        raise ValueError(f"LaCuerda version numbers start at 1, not {n}")
    suffix = "" if n == 1 else f"-{n}"
    return f"{BASE_URL}/{artist}/{song}{suffix}.shtml"


def parse_artist_page(html: str, *, url: str | None = None) -> list[LCSong]:
    """The songs listed on an artist page, in page order.

    Raises :class:`LaCuerdaParseError` when the page has no ``ul#b_main``, so a
    changed or unexpected page is never read as "the artist has no songs".
    """
    tree = LexborHTMLParser(html)
    if tree.css_first("ul#b_main") is None:
        raise LaCuerdaParseError("no song list (ul#b_main)", url=url)
    songs = []
    for item in tree.css("ul#b_main > li[lcd]"):
        link = item.css_first("a[href]")
        slug = _slug_from_href(link.attributes.get("href") or "") if link else ""
        if not slug:
            continue
        types, ranking = parse_lcd(item.attributes.get("lcd") or "")
        songs.append(LCSong(slug=slug, title=_link_title(link), types=types, ranking=ranking))
    return songs


def _slug_from_href(href: str) -> str:
    """The last path segment: the real page links "de_musica_ligera" relatively."""
    segments = [s for s in urlsplit(href.strip()).path.split("/") if s]
    return segments[-1] if segments else ""


def _link_title(link: LexborNode) -> str:
    """The link text without its trailing <em>acordes</em> label."""
    nodes = list(link.iter(include_text=True))
    while nodes and nodes[-1].tag == "-text" and not (nodes[-1].text_content or "").strip():
        nodes.pop()
    if nodes and nodes[-1].tag == "em":
        nodes.pop()
    return " ".join("".join(n.text(deep=True) for n in nodes).split())
