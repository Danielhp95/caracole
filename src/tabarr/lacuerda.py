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
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from rapidfuzz import fuzz
from selectolax.lexbor import LexborHTMLParser, LexborNode

from tabarr.http import ProviderError
from tabarr.normalize import clean_title, fold, slug_key, ug_slug_key

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


def match_title(songs: Iterable[LCSong], title: str, *, cutoff: float = 90) -> LCSong | None:
    """The song on an artist page that is ``title``, or None.

    Compares slug keys of the cleaned title with each song's title and, as a
    second form, its slug, because a slug sometimes keeps what the title drops
    ("Algun día" is ``algun_diasomeday``). An exact key wins; otherwise the best
    rapidfuzz ratio, if it reaches ``cutoff``. On a tie, a song with an acordes
    version beats one without, then the first on the page wins.
    """
    query = slug_key(clean_title(title))
    if not query:
        return None
    best: LCSong | None = None
    best_key: tuple[float, bool] = (-1.0, False)
    for song in songs:
        score = max(fuzz.ratio(query, form) for form in _title_forms(song))
        key = (score, best_acordes_version(song) is not None)
        if key > best_key:
            best, best_key = song, key
    return best if best_key[0] >= cutoff else None


def _title_forms(song: LCSong) -> tuple[str, str]:
    return slug_key(song.title), ug_slug_key(song.slug.replace("_", "-"))


def parse_version_page(html: str, *, url: str | None = None) -> str:
    """The sheet on a version page, in UG markup, so UG's tools can read it.

    ``<A>Bm</A>`` becomes ``[ch]Bm[/ch]``. Every other tag is dropped and its
    text kept, ``<br>`` breaks the line, entities are decoded and non-breaking
    spaces become spaces. The lines, and the spaces that align chords over the
    lyrics, are kept exactly. Chord names stay as written, solfège included.

    Raises :class:`LaCuerdaParseError` when there is no ``div#t_body > pre`` or
    it holds no text.
    """
    pre = LexborHTMLParser(html).css_first("div#t_body > pre")
    if pre is None:
        raise LaCuerdaParseError("no sheet (div#t_body > pre)", url=url)
    sheet = _ug_markup(pre).replace("\xa0", " ")
    if not sheet.strip():
        raise LaCuerdaParseError("empty sheet", url=url)
    return sheet


def _ug_markup(node: LexborNode) -> str:
    out = []
    for child in node.iter(include_text=True):
        tag = child.tag
        if tag == "-text":
            out.append(child.text_content or "")
        elif tag == "a":
            out.append(_chord(child.text(deep=True)))
        elif tag == "br":
            out.append("\n")
        elif tag.startswith("-") or tag in ("script", "style"):
            continue  # comments and other non-text nodes
        else:
            out.append(_ug_markup(child))
    return "".join(out)


def _chord(text: str) -> str:
    """``[ch]Am[/ch]``, with any padding moved outside so the column stays put."""
    name = text.strip()
    if not name:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    return f"{lead}[ch]{name}[/ch]{trail}"


# Common function words, accent-folded. Words that both languages use ("a",
# "no", "me", "he", "son", "sin") and Portuguese's "o" and "e" count for neither.
_SPANISH_WORDS = frozenset(
    """
    de la que el en y los se del las un por con una su para es al lo como mas pero
    sus le ya este si porque esta entre cuando muy sobre tambien hasta hay donde
    quien desde todo nos todos uno les ni otro ese eso esto mi yo tu te ti tus mis
    nada ella ellos algo nosotros estoy estas estan eres soy fue era voy vas va
    tengo tienes tiene quiero puedo aqui asi ahora nunca siempre otra vez cada cual
    mucho poco tan tanto aunque contigo conmigo esa aquel nuestro nuestra hoy sea
    ser estar hacer puede
    """.split()
)
_ENGLISH_WORDS = frozenset(
    """
    the and of to in is it its you your youre i im ive ill id my we our us be been
    on for with are was were this that these those but not all so what can cant
    just do dont does did didnt know like when will wont would could should now up
    out if there they them their she her his at have has had from by one yeah never
    ever every more how why where who here about into over than then too very an or
    as got get gonna wanna say said see go
    """.split()
)
# A Latin word, or one character of any other script: Chinese has no spaces, and
# counting its characters keeps a Spanish phrase from tipping Chinese lyrics.
_TOKEN = re.compile(r"[a-z]+|[^\W\da-z_]")
_APOSTROPHE = re.compile(r"['’‘`´ʼ]")
# Real Spanish lyrics run at 45–53% of these words, and any four lines at 20% or
# more; real English lyrics at 3% or less (LRCLIB, 18 October 2026).
_MIN_SPANISH_SHARE = 0.15

_SPANISH_SIGNS = re.compile(r"[ñ¿¡]", re.IGNORECASE)
_SPANISH_ACCENTS = re.compile(r"[áéíóú]|gü", re.IGNORECASE)
_OTHER_ACCENTS = re.compile(r"[àèìòùâêîôûãõçëïöÿåøæœß]|(?<!g)ü", re.IGNORECASE)


def _language_counts(text: str) -> tuple[int, int, int]:
    """(Spanish words, English words, all words) in a text."""
    tokens = _TOKEN.findall(_APOSTROPHE.sub("", fold(text)))
    spanish = sum(t in _SPANISH_WORDS for t in tokens)
    english = sum(t in _ENGLISH_WORDS for t in tokens)
    return spanish, english, len(tokens)


def is_spanish(text: str) -> bool:
    """Whether a text reads as Spanish, by its share of Spanish function words.

    Spanish words must outnumber English ones and make up at least 15% of the
    words.
    """
    spanish, english, total = _language_counts(text)
    return spanish > english and spanish >= _MIN_SPANISH_SHARE * total


def looks_spanish(title: str, lyrics: str | None = None) -> bool:
    """Whether a song is probably Spanish. Its lyrics decide when it has any.

    Without lyrics the title decides: "ñ", "¿" or "¡"; or Spanish accents (á é í
    ó ú, "gü") with no other language's (à, ç, ö…) and no more English function
    words than Spanish ones; or else :func:`is_spanish` on the title.
    """
    if lyrics and lyrics.strip():
        return is_spanish(lyrics)
    return _spanish_spelling(title) or is_spanish(title)


def _spanish_spelling(title: str) -> bool:
    s = unicodedata.normalize("NFC", title)
    if _SPANISH_SIGNS.search(s):
        return True
    if not _SPANISH_ACCENTS.search(s) or _OTHER_ACCENTS.search(s):
        return False
    spanish, english, _ = _language_counts(s)
    return english <= spanish
