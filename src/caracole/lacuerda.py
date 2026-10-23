"""LaCuerda (acordes.lacuerda.net): chord sheets for Spanish songs.

Ultimate Guitar's sitemaps list every artist with an accented name only as bare
ids, but a LaCuerda artist URL can be built from the name. One artist page then
serves every song by that artist, and one version page gives the sheet. What
the pages look like (captured 18 October 2026; robots.txt is empty):

- **Artist slugs** are the name lowercased, with accents stripped, "ñ" written
  "ni", each space turned into "_" and any other punctuation removed without a
  trace ("Fito & Fitipaldis" → ``fito__fitipaldis``). A leading article is
  dropped ("Las Pastillas del Abuelo" → ``pastillas_del_abuelo``). Song slugs
  follow the same rules but keep their articles, and can't always be predicted
  ("Algun día" → ``algun_diasomeday``), so songs are matched by title.
- **The artist page** ``/{artist}/`` lists each song as ``ul#b_main > li[lcd]``
  with a relative link to the song slug and the title, followed by
  ``<em>acordes</em>``. An unknown artist gets HTTP 200 and a 54-byte body,
  "aqui llega:../tabs/z/<slug>/index.html" (:func:`is_missing_artist_page`).
- **The lcd code**, such as "RHRTTTDTB-314865972", has one type letter per
  version, version 1 first, then the version numbers in the order the song page
  shows them: grouped by type (R, then T, B, D, then H and K), best first within
  a type. The letters seen are R (Letra y Acordes), T (Tablatura), B (Tab p/Bajo),
  D (Batería), H (Armónica) and K (offered by the filter bar, never labelled).
- **Version pages** are ``/{artist}/{song}.shtml`` for version 1 and
  ``/{artist}/{song}-{n}.shtml`` after that. The sheet is ``div#t_body > pre``,
  with chords as ``<A>Bm</A>`` and an empty ``<div></div>`` before each chord line.
  A song's own page, ``/{artist}/{song}``, lists its versions.
- **The artist listings** (checked 20 October 2026): LaCuerda has no sitemap
  (``/sitemap.xml`` and ``/sitemap_index.xml`` answer 404, and robots.txt names
  none), but ``/tabs/`` links a listing for each initial (:data:`LETTERS`).
  ``/tabs/{letter}/`` shows the 50 most popular artists only; every artist is
  on ``/tabs/{letter}/index0.html``, ``index100.html``…, 100 a page, in
  ``ul#i_main > li``: a link to ``/{slug}/``, the name after an
  ``<em>Acordes de</em>`` label, and the songs counted in a ``<span>``. Each
  page's ``div.multipag`` links every page of the letter and counts its
  artists (E: 7 pages, 639 artists). The listings are static files: they
  answer with a ``Last-Modified``. The name is LaCuerda's, and the slug its
  own: "Los Ecos" is filed under E as ``ecos``, "Enanitos Verdes" as
  ``enanitos``, which :func:`artist_slug` couldn't guess.
- **The search** (checked 22 October 2026): ``/busca.php?exp=…&canc=…&ord=0&ini=0``
  (:func:`search_url`), where ``canc`` is 0 for a general search, 1 for songs
  and 2 for artists, and ``ini`` the first result. It reads only the words of
  four letters or more, accents folded and every symbol a break
  (:func:`search_words`), and a general search answers the artists whose
  names match first, if any, in place of the songs. ``div.s_res`` counts the
  results ("2 resultados"). Songs are ``table#s_main`` rows, an artist's
  link (``/mana/``) and their songs, each a ``li[lcd]`` with the title, whose
  id (``r000``) numbers it; the song slugs are in the page's script,
  ``var hds=[…]; var fns=[…]; var NMAX=1;``, in reverse order: song ``rN`` is
  ``fns[NMAX-N]``. Artists are ``ul#i_main``, as the listings have it. The
  server sometimes ends an answer early (a page cut after
  ``<ul id=i_main class=s_blist>``, checked live): :func:`parse_search`
  refuses one whose list isn't closed, whose arrays are missing or disagree,
  or that has fewer rows than it counts, so a page cut short is never "no
  results".
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from rapidfuzz import fuzz
from selectolax.lexbor import LexborHTMLParser, LexborNode

from caracole.http import ProviderError
from caracole.normalize import clean_title, fold, slug_key, ug_slug_key

BASE_URL = "https://acordes.lacuerda.net"
PROVIDER = "lacuerda"

ACORDES = "R"  # the lcd letter of a "Letra y Acordes" version


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
    ``lcd`` is the code both were read from, as the page wrote it.
    """

    slug: str
    title: str
    types: str
    ranking: tuple[int, ...]
    lcd: str = field(default="", repr=False, compare=False)


@dataclass(frozen=True)
class LCArtist:
    """An artist of a letter's listing: the slug of their page, their name as LaCuerda
    writes it ("Los Ecos"), and how many songs the listing counts."""

    slug: str
    name: str
    songs: int


@dataclass(frozen=True)
class Listing:
    """A page of a letter's listing: its artists, in page order; every page of the letter
    (``index0.html``…) it links, its own included when its address is known; and how many
    artists the letter has, as it counts them (None when it doesn't say)."""

    artists: tuple[LCArtist, ...]
    pages: tuple[str, ...]
    total: int | None


# --- slugs and URLs ----------------------------------------------------------

_ARTICLES = frozenset({"el", "la", "los", "las", "the"})
_NOT_SLUG = re.compile(r"[^a-z0-9 ]")
_AND_WORD = re.compile(r"(?i)(?<!\S)y(?!\S)")


def _words(name: str) -> list[str]:
    """The name's slug words. Removed punctuation leaves an empty word behind."""
    s = unicodedata.normalize("NFC", name).lower().replace("ñ", "ni")
    s = _NOT_SLUG.sub("", fold(" ".join(s.split()))).strip()
    return s.split(" ") if s else []


def artist_slug(name: str) -> str:
    """LaCuerda's slug for an artist: "Joaquín Sabina" → ``joaquin_sabina``.

    Returns "" when nothing of the name survives (a name in Chinese characters,
    say); LaCuerda can't be asked about that artist.
    """
    words = _words(name)
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return "_".join(words)


def artist_slug_candidates(name: str) -> tuple[str, ...]:
    """Slugs worth trying for an artist, best guess first.

    After :func:`artist_slug` come the slug that keeps a leading article and the
    slug with "y" and "&" swapped, because names disagree on both ("Fito y
    Fitipaldis" is LaCuerda's ``fito__fitipaldis``). Each extra
    candidate costs a request only when the ones before it miss.
    """
    variants = [name]
    if _AND_WORD.search(name):
        variants.append(_AND_WORD.sub("&", name))
    if "&" in name:
        variants.append(name.replace("&", " y "))
    out: list[str] = []
    for variant in variants:
        for slug in (artist_slug(variant), "_".join(_words(variant))):
            if slug and slug not in out:
                out.append(slug)
    return tuple(out)


def artist_url(slug: str) -> str:
    """The artist page: ``artist_url("soda_stereo")`` → ".../soda_stereo/"."""
    if not slug:
        raise ValueError("empty LaCuerda artist slug")
    return f"{BASE_URL}/{slug}/"


def version_url(artist: str, song: str, n: int) -> str:
    """The page of version ``n``: ``{song}.shtml`` for 1, ``{song}-{n}.shtml`` after that."""
    if not artist or not song:
        raise ValueError("empty LaCuerda artist or song slug")
    if n < 1:
        raise ValueError(f"LaCuerda version numbers start at 1, not {n}")
    suffix = "" if n == 1 else f"-{n}"
    return f"{BASE_URL}/{artist}/{song}{suffix}.shtml"


def song_url(artist: str, song: str) -> str:
    """A song's own page, which lists its versions: ``.../soda_stereo/de_musica_ligera``."""
    if not artist or not song:
        raise ValueError("empty LaCuerda artist or song slug")
    return f"{BASE_URL}/{artist}/{song}"


# LaCuerda's initials, as the menu of /tabs/ links them: "#" (a name that starts with a
# digit) is _num, and "ñ" is nn.
LETTERS = ("_num", *"abcdefghijklmn", "nn", *"opqrstuvwxyz")
FIRST_PAGE = "index0.html"


def listing_path(letter: str, page: str = FIRST_PAGE) -> str:
    """The path of a page of a letter's listing of every artist: ``tabs/e/index0.html``."""
    return f"tabs/{letter}/{page}"


def listing_url(path: str) -> str:
    """The address of a listing page from its path (:func:`listing_path`)."""
    return f"{BASE_URL}/{path}"


# --- the artist page ---------------------------------------------------------

# LaCuerda answers an unknown artist with HTTP 200 and a 54-byte body,
# "aqui llega:../tabs/z/<slug>/index.html" (checked live). Real artist pages,
# even with one song, carry kilobytes of navigation around the list.
_SOFT_404 = re.compile(r"\s*aqu[ií] llega:", re.IGNORECASE)
_SOFT_404_MAX_BYTES = 1024


def is_missing_artist_page(html: str) -> bool:
    """Whether an artist page that came back with HTTP 200 says "no such artist".

    Only LaCuerda's short "aqui llega:…" body does. Any other page without the
    song list, however small (a PHP or database error page, say), is not a
    miss: :func:`parse_artist_page` reports it as a parse error.
    """
    small = len(html.encode("utf-8")) < _SOFT_404_MAX_BYTES
    return small and _SOFT_404.match(html) is not None


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


def parse_artist_page(html: str, *, url: str | None = None) -> list[LCSong]:
    """The songs listed on an artist page, in page order.

    Raises :class:`LaCuerdaParseError` when the page has no ``ul#b_main``, or
    when the list has items but none with an lcd code and a link, so a changed
    or unexpected page is never read as "the artist has no songs".
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
        lcd = item.attributes.get("lcd") or ""
        types, ranking = parse_lcd(lcd)
        title = _link_title(link)
        songs.append(LCSong(slug=slug, title=title, types=types, ranking=ranking, lcd=lcd))
    if not songs and tree.css_first("ul#b_main > li") is not None:
        raise LaCuerdaParseError("no song in the list has an lcd code and a link", url=url)
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


_POP_ORDER = re.compile(r"var\s+popOrder\s*=\s*\[([^\]]*)\]")


def parse_popularity(html: str) -> dict[str, int]:
    """Each song's place in the artist page's order of popularity, by slug, 0 the most popular.

    The page's script (``var popOrder = [5,9,11,…]``) numbers the items of ``ul#b_main`` in
    page order, most popular first. A number past the list is skipped; a page without the
    order, or with one that isn't numbers, gives none.
    """
    found = _POP_ORDER.search(html)
    if found is None:
        return {}
    try:
        order = [int(n) for n in found.group(1).split(",") if n.strip()]
    except ValueError:
        return {}
    items = LexborHTMLParser(html).css("ul#b_main > li")
    slugs = []
    for item in items:
        link = item.css_first("a[href]")
        slugs.append(_slug_from_href(link.attributes.get("href") or "") if link is not None else "")
    places: dict[str, int] = {}
    for place, n in enumerate(order):
        if 0 <= n < len(slugs) and slugs[n] and slugs[n] not in places:
            places[slugs[n]] = place
    return places


def parse_artist_name(html: str) -> str | None:
    """The artist's name as their page heads it (``div.bTit > h1``), or None without one."""
    heading = LexborHTMLParser(html).css_first("div.bTit > h1")
    name = " ".join(heading.text(deep=True).split()) if heading is not None else ""
    return name or None


# --- the artist listings -------------------------------------------------------

_PAGE_NAME = re.compile(r"index(\d+)\.html")
_LEADING_NUMBER = re.compile(r"\s*(\d+)")
_SLUG = re.compile(r"[a-z0-9_]+")


def parse_listing_page(html: str, *, url: str | None = None) -> Listing:
    """A page of a letter's listing of every artist (``/tabs/{letter}/index0.html``…).

    The pages come from the first ``div.multipag``, ordered by number, with this page's
    own name taken from ``url``. Raises :class:`LaCuerdaParseError` when there is no
    ``ul#i_main``, or when it has items but none with a link to an artist page, so a
    changed page is never read as a letter without artists. An empty list is a listing.
    """
    tree = LexborHTMLParser(html)
    main = tree.css_first("ul#i_main")
    if main is None:
        raise LaCuerdaParseError("no artist list (ul#i_main)", url=url)
    artists = _listed_artists(main, url)
    pages = set()
    total = None
    multipag = tree.css_first("div.multipag")
    if multipag is not None:
        for item in multipag.css("li[onclick]"):
            found = _PAGE_NAME.search(item.attributes.get("onclick") or "")
            if found:
                pages.add(found.group(0))
        counted = multipag.css_first("li.last")
        number = _LEADING_NUMBER.match(counted.text(deep=True)) if counted is not None else None
        total = int(number.group(1)) if number else None
    own = _PAGE_NAME.fullmatch(urlsplit(url).path.rsplit("/", 1)[-1]) if url else None
    if own:
        pages.add(own.group(0))
    ordered = tuple(sorted(pages, key=lambda p: int(_PAGE_NAME.fullmatch(p).group(1))))
    return Listing(tuple(artists), ordered, total)


def _listed_artists(main: LexborNode, url: str | None) -> list[LCArtist]:
    """The artists of a ``ul#i_main``, as a listing (and a search that answers artists) writes them: a link to
    their page, their name after an ``<em>`` label, their songs counted in a ``<span>``. Raises
    :class:`LaCuerdaParseError` for a list with items but none with a link to an artist page."""
    artists = []
    items = main.css("li")
    for item in items:
        link = item.css_first("a[href]")
        slug = _artist_slug_from_href(link.attributes.get("href") or "") if link is not None else ""
        if not slug:
            continue
        name = " ".join("".join(n.text(deep=True) for n in link.iter(include_text=True)
                                if n.tag != "em").replace("\xa0", " ").split())
        count = item.css_first("span")
        number = _LEADING_NUMBER.match(count.text(deep=True)) if count is not None else None
        artists.append(LCArtist(slug, name or slug, int(number.group(1)) if number else 0))
    if items and not artists:
        raise LaCuerdaParseError("no artist in the list has a link to their page", url=url)
    return artists


def _artist_slug_from_href(href: str) -> str:
    """The slug of an artist page's link, ``/estopa/`` (or its full address); "" for any other link."""
    segments = [s for s in urlsplit(href.strip()).path.split("/") if s]
    return segments[0] if len(segments) == 1 and _SLUG.fullmatch(segments[0]) else ""


# --- the search ----------------------------------------------------------------------------

SEARCH_LETTERS = 4  # LaCuerda's search reads no shorter word
_SEARCH_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SearchSong:
    """A song of an answer of LaCuerda's search: the slug of their artist's page and their name, as the row's
    link has them, and the song as an artist page's would be (its slug from the page's script)."""

    artist_slug: str
    artist: str
    song: LCSong

    @property
    def title(self) -> str:
        return self.song.title

    @property
    def slug(self) -> str:
        return self.song.slug

    @property
    def url(self) -> str:
        """The song's own page, which lists its versions."""
        return song_url(self.artist_slug, self.song.slug)

    @property
    def sheet_url(self) -> str | None:
        """The page of its best Letra y Acordes version; None for a song with none."""
        n = best_acordes_version(self.song)
        return version_url(self.artist_slug, self.song.slug, n) if n is not None else None


@dataclass(frozen=True)
class SearchAnswer:
    """What a page of LaCuerda's search answers: its songs, or the artists a general search lists in their
    place, in page order; and how many results it counts (``stated``), which a page of many may hold only some of."""

    songs: tuple[SearchSong, ...] = ()
    artists: tuple[LCArtist, ...] = ()
    stated: int = 0


def search_words(query: str) -> list[str]:
    """The words LaCuerda's search reads of a query: accents folded, "ñ" as "n" (as its own script folds them),
    every symbol a break between words, and only words of ``SEARCH_LETTERS`` letters or more ("y", "o", "la" and
    every shorter word are none). Each once, in the query's order; none for a query of Chinese characters."""
    words = _SEARCH_WORD.findall(fold(unicodedata.normalize("NFC", query)))
    return list(dict.fromkeys(w for w in words if len(w) >= SEARCH_LETTERS))


def search_url(query: str, *, songs_only: bool = True) -> str:
    """The first page of LaCuerda's search for the words it reads of ``query`` (``search_words``): of its songs
    (``canc=1``), or, with ``songs_only`` False, a general search (``canc=0``), which answers the artists whose
    names match first. ValueError for a query it reads no word of."""
    words = search_words(query)
    if not words:
        raise ValueError(f"LaCuerda's search reads no word of {query!r}: none has {SEARCH_LETTERS} letters")
    return f"{BASE_URL}/busca.php?exp={'+'.join(words)}&canc={1 if songs_only else 0}&ord=0&ini=0"


_STATED = re.compile(r"(\d[\d.,]*)\s+resultados?\b", re.IGNORECASE)
_SONG_TABLE = re.compile(r"<table\b[^>]*\bid=['\"]?s_main\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)
_ARTIST_LIST = re.compile(r"<ul\b[^>]*\bid=['\"]?i_main\b.*?</ul\s*>", re.IGNORECASE | re.DOTALL)
_NMAX = re.compile(r"\bvar\s+NMAX\s*=\s*(-?\d+)\s*;")
_QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")
_ROW_ID = re.compile(r"r(\d+)")


def parse_search(html: str, *, url: str | None = None) -> SearchAnswer:
    """A page of LaCuerda's search: its songs, or the artists it lists in their place, and how many results it
    counts (module docstring). "0 resultados" is an answer with none.

    Raises :class:`LaCuerdaParseError` for a page that doesn't count its results, whose results table or list
    isn't closed, whose script lacks the song slugs or has arrays that disagree with each other or the rows, with
    a row whose link is no artist's page, or with fewer rows than it counts while it links no other page of
    them: a page cut short is never "no results"."""
    tree = LexborHTMLParser(html)
    said = tree.css_first("div.s_res")
    counted = _STATED.search(said.text(deep=True)) if said is not None else None
    if counted is None:
        raise LaCuerdaParseError("no count of results (div.s_res)", url=url)
    stated = int(re.sub(r"[.,]", "", counted.group(1)))
    if stated == 0:
        return SearchAnswer()
    if tree.css_first("table#s_main") is not None:
        if _SONG_TABLE.search(html) is None:
            raise LaCuerdaParseError("the results table isn't closed: the page was cut short", url=url)
        found = SearchAnswer(songs=tuple(_search_songs(tree, html, url)), stated=stated)
        rows = len(found.songs)
    elif (main := tree.css_first("ul#i_main")) is not None:
        if _ARTIST_LIST.search(html) is None:
            raise LaCuerdaParseError("the list of artists isn't closed: the page was cut short", url=url)
        found = SearchAnswer(artists=tuple(_listed_artists(main, url)), stated=stated)
        rows = len(found.artists)
    else:
        raise LaCuerdaParseError(f"neither songs (table#s_main) nor artists (ul#i_main) for the {stated} results "
                                 "it counts", url=url)
    if rows < stated and not _other_pages(tree) or rows == 0:
        raise LaCuerdaParseError(f"{rows} rows of the {stated} results it counts, on its only page of them", url=url)
    return found


def _search_songs(tree: LexborHTMLParser, html: str, url: str | None) -> list[SearchSong]:
    """The songs of table#s_main, their slugs from the script's arrays (``fns[NMAX-N]`` for song ``rN``)."""
    hds, fns, nmax = _strings(html, "hds"), _strings(html, "fns"), _NMAX.search(html)
    if hds is None or fns is None or nmax is None:
        raise LaCuerdaParseError("no song slugs in the page's script (var hds, fns, NMAX)", url=url)
    last = int(nmax.group(1))
    if len(hds) != len(fns) or last != len(fns) - 1:
        raise LaCuerdaParseError(f"the script's arrays disagree: {len(hds)} artists, {len(fns)} songs, "
                                 f"NMAX={last}", url=url)
    songs = []
    for row in tree.css("table#s_main tr"):
        items = row.css("ul.b_main > li")
        if not items:
            continue
        link = row.css_first("td a[href]")
        slug = _artist_slug_from_href(link.attributes.get("href") or "") if link is not None else ""
        if not slug:
            raise LaCuerdaParseError("a row of results whose link is no artist's page", url=url)
        name = " ".join(link.text(deep=True).replace("\xa0", " ").split()) or slug
        for item in items:
            number = _ROW_ID.fullmatch(item.attributes.get("id") or "")
            n = int(number.group(1)) if number else -1
            if not 0 <= n <= last:
                raise LaCuerdaParseError(f"a song numbered past the script's {len(fns)} slugs", url=url)
            song = fns[last - n]
            if not _SLUG.fullmatch(song):
                raise LaCuerdaParseError(f"no song slug: {song!r}", url=url)
            lcd = item.attributes.get("lcd") or ""
            types, ranking = parse_lcd(lcd)
            title = " ".join(item.text(deep=True).replace("\xa0", " ").split())
            songs.append(SearchSong(slug, name, LCSong(slug=song, title=title, types=types, ranking=ranking, lcd=lcd)))
    if len(songs) != len(fns):
        raise LaCuerdaParseError(f"{len(songs)} songs in the table for the script's {len(fns)} slugs", url=url)
    return songs


def _strings(html: str, name: str) -> list[str] | None:
    """The quoted strings of the page script's array ``var NAME=[…];``; None without one."""
    found = re.search(rf"\bvar\s+{name}\s*=\s*\[([^\]]*)\]\s*;", html)
    if found is None:
        return None
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in _QUOTED.finditer(found.group(1))]


def _other_pages(tree: LexborHTMLParser) -> bool:
    """Whether the answer's ``div.multipag`` links another page of results than this one."""
    multipag = tree.css_first("div.multipag")
    if multipag is None:
        return False
    return any(not ({"sel", "last"} & set((li.attributes.get("class") or "").split())) for li in multipag.css("li"))


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


# --- the version page --------------------------------------------------------


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


# --- is it Spanish? ------------------------------------------------------------

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
    """.split()  # noqa: SIM905 - a word list reads better as text
)
_ENGLISH_WORDS = frozenset(
    """
    the and of to in is it its you your youre i im ive ill id my we our us be been
    on for with are was were this that these those but not all so what can cant
    just do dont does did didnt know like when will wont would could should now up
    out if there they them their she her his at have has had from by one yeah never
    ever every more how why where who here about into over than then too very an or
    as got get gonna wanna say said see go
    """.split()  # noqa: SIM905
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
    words, where each character of Chinese and other unspaced scripts counts as
    a word.
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
