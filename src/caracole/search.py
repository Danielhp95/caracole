"""Offline search: your library, and the local Ultimate Guitar index (amendment A7).

``caracole search`` never touches the network. It looks in two places:

- **Your library** (``search_library``): every song, whatever its status,
  scored against its artists and its title.
- **The UG index** (``search_index``): the ``ug_index`` table built from UG's
  sitemaps, about 1.6 million rows. A SQL ``LIKE`` prefilter keeps the
  candidates to a few thousand, and rapidfuzz ranks them. It reads the
  trigram index of the keys (ug/key_search.py), not the rows; the prefilter
  uses at most two patterns:
  the query's two longest words (a typo in one of them still finds the song),
  or, for names made of initials, the hyphenated and the compact key
  (UG writes R.E.M. as ``r-e-m`` but AC/DC as ``acdc``). Variant slugs such as
  ``creep-acoustic`` are grouped under their song. A song of a catch-all
  artist (``misc-musicals``…) is also scored on its title alone, with and
  without words such as "the musical": "epic not sorry for loving you" is
  ``misc-musicals/epic-the-musical-not-sorry-for-loving-you``.

Both sides are compared as words made the way slug keys are made (accents
folded, apostrophes, "and" and a leading "the" dropped), and Chinese is also
compared as pinyin: "宋冬野" meets UG's ``song-dongye``, and "ban ma" finds
斑马，斑马. A Chinese word's syllables are matched in order with ``%``
between them, so ``song-dongye``, ``songdongye`` and ``song-dong-ye`` all match.
As in the matcher (match.py), pinyin counts only where it is words of a name:
each Chinese word's pinyin must be a whole run of the artist's or the title's
words, hyphens aside, never letters inside a word (斑马 is in neither
``suburban-male`` nor ``band-maid``), and a pinyin match of only part of a
name tops out below a strong hit.

**Either one.** A query may be the artist alone, the title alone, or both, in
any order: each hit says which reading scored it (``via``: "title",
"artist" or "both"; a tie goes to the title, then both), with the score it
always had. ``find_index`` gives the index's answer, and ``found`` the one
the pages show, with your songs (``search_library``): your songs, the
artists the query names (``ArtistHit``: the query as the artist's whole name
scores 90 or more, never a catch-all's, with its songs and tabs counted and
its most tabbed songs), and the index's songs, those it holds only
through an artist's name folded into that artist's row. ``lead`` says which
comes first, and ``best`` is the one row Enter may act on: a song of yours read
by its title (or both), not under a placeholder artist such as "misc", else
the first song of the index if it scores 90 or more by its title (or both) and
isn't a catch-all's, and None when an artist leads or nothing is that good.
Beside an artist whose whole name is the query, one whose name is only near it
("Beagles" for "eagles") is left out, with the songs only its name matched.
``artist_songs`` lists all of an artist's songs, and ``library_by_artist``
yours. The only popularity the index holds is how many
tabs a song or an artist has, so that orders the ties, and the artist with a
more tabbed song than any song titled like it leads. Nothing here asks any
site: an artist the index doesn't know is the user's to type.

**Other sites' indexes.** ``search_gtptabs`` reads gtptabs.com's song pages
(``gtptabs_index``, from its sitemaps), scored as the index's songs are, and
``search_musescore`` MuseScore's (``musescore_index``), which give a title
alone: a page there is one whose whole title is the query, or the query less
an artist's name on either side, where that artist has a song of that title in
the Ultimate Guitar index, gtptabs.com's or your library; a possible match,
never more. Both only read the local tables: nothing here asks gtptabs.com or MuseScore
anything, and MuseScore's pages are for the user to open. ``search_lacuerda`` reads
LaCuerda's (``lacuerda_index``, from its listings of every artist and the artist pages
caracole has read): its songs as ``SiteHit``s, each with the page of the sheet a lookup
keeps (``sheet``), and the artists the query names as rows of their own (``SiteArtist``),
since the index holds every artist but the songs only of the artists whose page caracole
has read. ``lacuerda_artist`` and ``lacuerda_songs`` give one of its artists and the songs
the index holds of theirs. While its listings aren't read whole, ``lacuerda_unlisted`` names the
page that may tell whether LaCuerda has an artist it doesn't list, and ``lacuerda_leads`` says when
its group comes first. LaCuerda has no search caracole uses: nothing here asks it.

UG's sitemaps list artists with accented or non-Latin names only by bare ids,
so the index can't see their tabs; ``bare_id_hint`` says what to do then.
**The artist pages caracole read** fill that gap (ug/artist_tabs.py: every tab
each page listed, with UG's names, type, rating and page, kept as the fetch
read it): ``find_index`` scores their songs and artists with the index's, on
every form of UG's names (``normalize.name_forms``: "Song Dongye (宋冬野)" is
宋冬野 and Song Dongye, "斑马 斑马 Banma Banma Zebra Zebra" 斑马斑马 and Banma
Banma), Chinese as pinyin as whole words alone, and a song both list is one
hit, its tabs counted once (``IndexHit.page``, ``rating``). Such a song is named
as your songs name its artist, so its ``caracole add`` line is ``"宋冬野"
"斑马斑马"``, and no bare-id hint comes with a query these tabs answer well.

Where a name isn't quite UG's, a library song in review shows its first
candidates (``did_you_mean``), and a hit under one of UG's catch-all artists,
such as ``misc-musicals``, says so (``IndexHit.catch_all``): its title holds
the show's name, and its artist is no one's.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Iterator, Mapping, NamedTuple, Sequence

from rapidfuzz import fuzz

from caracole.config import RankPolicy
from caracole.match import CATCH_ALL_PREFIX, SHOW_WORDS, is_catch_all
from caracole.normalize import (
    clean_title,
    compact,
    fold,
    PINYIN_PARTIAL_SCALE,
    has_han,
    holds_run,
    name_forms,
    name_words,
    original_part,
    placeholder_artist,
    romanize,
    split_variant,
)
from caracole.overrides import ARTIST_PAGE_SHAPE, Overrides, artist_url_entry
from caracole.rank import bayes, prior_mean
from caracole.songs import Song, list_removed, list_songs
from caracole.ug.key_search import rows_like
from caracole.ug.lookup import IndexTab, song_tabs

if TYPE_CHECKING:
    from caracole.lacuerda_index import LaCuerdaHit
    from caracole.ug.artist_tabs import ListedTab

MIN_SCORE = 70  # below this a hit is noise
STRONG = 90  # a hit this good is the song you meant
PARTIAL_SCALE = 0.9  # a query that is only part of a name tops out at 90
TYPE_ORDER = ("chords", "tabs", "guitar-pro", "power")
MAX_PATTERNS = 2
SHOWN_CANDIDATES = 3  # a review's candidates shown under its song: the rest are in `caracole review`
READINGS = ("title", "both", "artist")  # how a query may name a song; a tie goes to the first
TOP_SONGS = 3  # an artist row's most tabbed songs
ARTIST_ROWS, SONG_ROWS = 3, 8  # what ``find_index`` gives by default
SITE_ROWS = 5  # a site's pages search_gtptabs and search_musescore give by default
SITE_ROWS_READ = 2000  # rows of gtptabs_index the prefilter reads, at most

_SHELL_SPECIAL = re.compile(r'(["\\$`])')


@dataclass(frozen=True)
class LibraryHit:
    """A song of yours that matches the query; ``score`` is 0–100, and ``via`` the reading that
    gave it: the query as the song's "title", its "artist", or "both"."""

    song: Song
    score: float
    via: str = "both"


@dataclass(frozen=True)
class IndexHit:
    """A song in the offline UG index.

    ``song_key`` is the song's base key: its variant slugs (``-acoustic``,
    ``-intro``…) are counted with it, and their labels are in ``labels``.
    ``counts`` gives the tabs per type, best type first. ``url`` is a sample
    tab page. ``artist`` and ``title`` are made from UG's own slugs, which keep
    a leading "the" and an "and" that the keys drop, to show and to paste into
    ``caracole add``. ``via`` is the reading of the query that scored it, as
    ``LibraryHit``'s.

    A song an artist page caracole read lists (ug/artist_tabs.py: bare ids
    the sitemaps name nowhere, and the slugged tabs beside them) counts those
    tabs too, and ``page`` is that artist page: ``url`` is then its best tab,
    the best type first, then the best rated, its rating weighed by its votes
    as a fetch weighs them (rank.py), with its ``rating`` (None when nobody
    voted) and ``votes`` (unless the index has a tab of a better type: that
    one, unrated).
    Of a song only an artist page lists, ``artist`` is named as your songs
    name them (``_Yours``) and ``title`` is UG's original name.
    """

    artist_key: str
    song_key: str
    counts: Mapping[str, int]
    score: float
    url: str
    labels: tuple[str, ...] = ()
    artist: str = ""
    title: str = ""
    via: str = "both"
    rating: float | None = None
    votes: int = 0
    page: str = ""

    @property
    def catch_all(self) -> bool:
        """Whether UG files this song under a catch-all artist (``misc-musicals``…), the show's name
        in its title: added under UG's names, the song's artist would be that catch-all."""
        return is_catch_all(self.artist_key)

    @property
    def tabs(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class ArtistHit:
    """An artist of the offline UG index the query names: an artist reading of ``STRONG`` or more.

    ``artist`` is the name as UG's slugs write it ("The Beatles" keeps its
    "The"); ``songs`` counts its songs (a song's variants with it) and ``tabs``
    its rows; ``top`` holds its ``TOP_SONGS`` most tabbed songs, most first.
    Never one of UG's catch-alls (``misc-…``), which are no one's name.
    ``page`` is the artist page caracole read of theirs, if any: its tabs are
    counted with the index's.
    """

    artist_key: str
    artist: str
    score: float
    songs: int
    tabs: int
    top: tuple[IndexHit, ...] = ()
    page: str = ""

    @property
    def top_tabs(self) -> int:
        """The tabs of its most tabbed song: what an artist is weighed by against a song of its name."""
        return self.top[0].tabs if self.top else 0


@dataclass(frozen=True)
class IndexFound:
    """What the offline index answers a query (``find_index``).

    ``songs`` leaves out the songs of an artist in ``artists`` that only its
    name matched: they are in its row. ``lead`` is "artist" when the first
    artist outweighs the first song (a better score, or the same and a more
    tabbed song of its own), "song" otherwise, None for no hit; ``best`` is
    the first song when it scores ``STRONG`` or more by its title (or both)
    and isn't a catch-all's (added under UG's names, its artist would be no
    one's), and None when an artist leads.
    """

    artists: tuple[ArtistHit, ...] = ()
    songs: tuple[IndexHit, ...] = ()
    lead: str | None = None
    best: IndexHit | None = None


@dataclass(frozen=True)
class Found:
    """``found``'s answer: your songs, then the index's artists and songs, what comes first, and the
    row Enter may act on (``best``: a song of yours first, as it costs no request)."""

    library: tuple[LibraryHit, ...]
    artists: tuple[ArtistHit, ...]
    songs: tuple[IndexHit, ...]
    lead: str | None
    best: LibraryHit | IndexHit | None


@dataclass(frozen=True)
class SiteHit:
    """A page of another site's offline index the query matches.

    ``source`` is "gtptabs" (a song page of gtptabs.com: an artist and a title,
    named from its slugs, its uploads of the title counted in ``uploads``),
    "musescore" (a song page of MuseScore: a title alone, as its sitemaps give
    it, so ``artist`` is "" and the page a possible match) or "lacuerda" (a song
    of LaCuerda's, named as LaCuerda names it, its versions counted in
    ``uploads``, and ``sheet`` the page of its best Letra y Acordes version, the
    sheet a lookup keeps; None for a song without chords there). ``url`` is the
    page, for the user to open; ``score`` and ``via`` are as ``IndexHit``'s.
    """

    source: str
    title: str
    url: str
    score: float
    artist: str = ""
    artist_key: str = ""
    title_key: str = ""
    uploads: int = 1
    via: str = "title"
    sheet: str | None = None


@dataclass(frozen=True)
class SiteArtist:
    """An artist of another site's offline index the query names: LaCuerda's (``source``).

    ``artist`` is the name the site writes, ``slug`` its own name for their page,
    ``url`` the page; ``songs`` counts their songs as the site's listing does, and
    ``known`` how many of them the index holds, 0 until caracole has read their
    page; ``top`` holds the most popular with chords. ``score`` and ``via`` are as
    ``IndexHit``'s.
    """

    source: str
    artist: str
    slug: str
    url: str
    score: float
    songs: int = 0
    known: int = 0
    via: str = "artist"
    top: tuple[SiteHit, ...] = ()


def display_from_keys(artist_key: str, song_key: str) -> tuple[str, str]:
    """An artist and a title made from UG keys or slugs: each word capitalized.

    ``("soda-stereo", "de-musica-ligera")`` gives ``("Soda Stereo", "De Musica Ligera")``.
    Only a word's first letter changes, so "3am" stays "3am".
    """
    return _title_words(artist_key), _title_words(song_key)


def did_you_mean(song: Song, limit: int = SHOWN_CANDIDATES) -> list[dict]:
    """A song in review's first candidates, best first (``songs.match_candidates`` rows): the UG songs
    the matcher thinks it may be. Empty for a song not in review."""
    if not song.review:
        return []
    return [c for c in song.match_candidates or [] if c.get("artist_key") and c.get("song_key")][:limit]


def search_library(conn: sqlite3.Connection, query: str, limit: int = 10, *,
                   reading: str | None = None) -> list[LibraryHit]:
    """Your songs that match ``query``, best first, whatever their status; with ``reading``
    ("title"), only as that reading scores them."""
    queries = _queries(query)
    if not queries:
        return []
    hits = []
    for song in list_songs(conn):
        score, via = _song_reading(queries, song, reading)
        if score >= MIN_SCORE:
            hits.append(LibraryHit(song, round(score, 1), via))
    hits.sort(key=lambda h: (-h.score, h.song.display.casefold(), h.song.id))
    return hits[:limit]


@dataclass(frozen=True)
class RemovedHit:
    """A song ``caracole remove`` took out that matches the query. It is never a library hit, and
    never ``lead`` or ``best``: it is shown as removed, with the line that asks for it again."""

    artist: str
    title: str
    key: str
    removed_at: str
    score: float
    via: str = "both"


def search_removed(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[RemovedHit]:
    """The removed songs (the ``removed`` table's names) that match ``query``, scored as
    ``search_library`` scores your songs, best first, the latest removed first among equals."""
    queries = _queries(query)
    if not queries:
        return []
    hits = []
    for gone in list_removed(conn):
        score, via = _names_reading(queries, [gone.artist], gone.title)
        if score >= MIN_SCORE:
            hits.append(RemovedHit(gone.artist, gone.title, gone.key, gone.removed_at, round(score, 1), via))
    hits.sort(key=lambda h: -h.score)  # stable: the latest removed first among equals
    return hits[:limit]


def search_index(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[IndexHit]:
    """Songs in the offline UG index that match ``query``, best first, by any reading.

    Ties go to the song with more tabs, which is usually the one you mean
    ("creep" is Radiohead's before Stone Temple Pilots'), then to the artist
    with more of the rows.
    """
    scored, _ = _scored_rows(conn, query)
    return _hits(conn, scored[:limit])


def find_index(conn: sqlite3.Connection, query: str, *, artists: int = ARTIST_ROWS, songs: int = SONG_ROWS,
               reading: str | None = None) -> IndexFound:
    """The offline index's artists and songs for ``query`` (``IndexFound``); with ``reading`` "title",
    songs of that title alone, by any artist, and no artist rows."""
    scored, named = _scored_rows(conn, query, reading)
    if any(n.score >= 100 for n in named.values()):
        # A name only near the query's ("Beagles" for "eagles") is noise beside the one that is it: its row goes,
        # and the songs only its name matched.
        near = {k for k, n in named.items() if n.score < 100}
        named = {k: n for k, n in named.items() if k not in near}
        scored = [s for s in scored if not (s.via == "artist" and s.artist_key in near)]
    rows: list[ArtistHit] = []
    if artists > 0:
        # Weighed first by what the rows hold of each (every row of an artist whose key a pattern
        # matched), then counted exactly for the few that may be shown.
        order = sorted(named, key=lambda k: (-named[k].score, -named[k].top, -named[k].tabs, k))
        yours = _Yours(conn)
        rows = [a for a in (_artist_hit(conn, k, named[k].score, yours) for k in order[:artists + 2]) if a is not None]
        rows = sorted(rows, key=lambda a: (-a.score, -a.top_tabs, -a.tabs, a.artist_key))[:artists]
    shown = {a.artist_key for a in rows}
    hits = _hits(conn, [s for s in scored if not (s.via == "artist" and s.artist_key in shown)][:songs])
    if not rows and not hits:
        return IndexFound()
    if rows and (not hits or (rows[0].score, rows[0].top_tabs) > (hits[0].score, hits[0].tabs)):
        return IndexFound(tuple(rows), tuple(hits), "artist", None)
    first = hits[0]
    # Never one only an artist's name matched, nor one of a catch-all's: its artist is no one's name.
    best = first if first.score >= STRONG and first.via != "artist" and not first.catch_all else None
    return IndexFound(tuple(rows), tuple(hits), "song", best)


def found(library: Sequence[LibraryHit], index: IndexFound) -> Found:
    """Your songs with the index's answer: a song of yours read by its title (or both) at ``STRONG``
    or more comes first and is ``best``; one read only by its artist is never the song you meant,
    nor one under a placeholder artist ("misc - 斑马"), which nothing can find."""
    yours = next((h for h in library
                  if h.via != "artist" and h.score >= STRONG and not placeholder_artist(h.song.artist)), None)
    if yours is not None:
        return Found(tuple(library), index.artists, index.songs, "song", yours)
    lead = index.lead or ("song" if library else None)
    return Found(tuple(library), index.artists, index.songs, lead, index.best)


def artist_songs(conn: sqlite3.Connection, artist_key: str, *, limit: int = 50, offset: int = 0,
                 title: str | None = None) -> tuple[list[IndexHit], int]:
    """Every song of an artist of the offline index, most tabbed first (a song's variants counted
    with it): ``limit`` of them from ``offset``, and how many there are. With ``title``, only those
    whose title it matches, best first."""
    groups = [(100.0, base, n) for base, n in _artist_groups(conn, artist_key)]
    via = "artist"
    queries = _queries(title or "")
    if queries:
        scored = [(max(q.score("", base.replace("-", " ")) for q in queries), base, n) for _, base, n in groups]
        groups = sorted((g for g in scored if g[0] >= MIN_SCORE), key=lambda g: (-g[0], -g[2], g[1]))
        via = "title"
    page = groups[max(offset, 0):max(offset, 0) + max(limit, 0)]
    yours = _Yours(conn)
    hits = (_index_hit(conn, artist_key, base, score, via, yours) for score, base, _ in page)
    return [h for h in hits if h is not None], len(groups)


def search_gtptabs(conn: sqlite3.Connection, query: str, limit: int = SITE_ROWS) -> list[SiteHit]:
    """gtptabs.com's song pages that match ``query``, best first, by any reading, as the index's songs
    are scored; a title's uploads under one artist ("-2", "-3") are one hit, on its first upload's page.
    Ties go to the title uploaded more often. The artist is named as Ultimate Guitar's index names them
    (``_gtptabs_artist``), the title from its slug."""
    from caracole.gtptabs import page_url

    patterns = _patterns(name_words(query))
    if not patterns:
        return []
    queries = _queries(query)
    # The page's path holds the artist's slug and the title's, whose words the keys are made of: one
    # LIKE a pattern over one column, the cheapest scan of a table without a trigram index.
    where = " OR ".join("path LIKE ?" for _ in patterns)
    rows = conn.execute(
        f"SELECT path, artist_key, title_key, base_key FROM gtptabs_index WHERE title_key != '' AND ({where}) "
        "LIMIT ?", (*patterns, SITE_ROWS_READ))
    groups: dict[tuple[str, str], list[tuple[bool, str]]] = {}
    for path, artist_key, title_key, base in rows:
        groups.setdefault((artist_key, base), []).append((title_key != base, path))
    scored = []
    for (artist_key, base), pages in groups.items():
        score, via = _reading(q.readings(artist_key.replace("-", " "), base.replace("-", " ")) for q in queries)
        if score >= MIN_SCORE:
            scored.append((score, len(pages), artist_key, base, min(pages)[1], via))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2], s[3]))
    names: dict[str, str] = {}
    hits = []
    for score, uploads, artist_key, base, path, via in scored[:max(limit, 0)]:
        if artist_key not in names:
            names[artist_key] = _gtptabs_artist(conn, artist_key)
        hits.append(SiteHit("gtptabs", _title_words(base), page_url(path), round(score, 1), names[artist_key],
                            artist_key, base, uploads, via))
    return hits


def _gtptabs_artist(conn: sqlite3.Connection, artist_key: str) -> str:
    """A gtptabs.com artist's name: as Ultimate Guitar's slugs write it, under the key or the key with its
    first word last (gtptabs.com files people last name first: "Elton John" is ``john-elton``), else
    from the key as it is."""
    words = artist_key.split("-")
    for key in dict.fromkeys([artist_key, "-".join(words[1:] + words[:1])]):
        row = conn.execute("SELECT path FROM ug_index WHERE artist_key = ? AND path != '' LIMIT 1", (key,)).fetchone()
        if row is not None:
            slug = row[0].partition("/")[0]
            if slug:
                return _title_words(slug)
    return _title_words(artist_key)


def search_musescore(conn: sqlite3.Connection, query: str, limit: int = SITE_ROWS) -> list[SiteHit]:
    """MuseScore's song pages whose title is the query, or the query with an artist's name on either side
    ("oasis wonderwall", "live forever oasis"): the sitemaps give titles alone, so each is a possible match.
    A run of the query's words is a title only when the rest names the artist of a song by that title, one
    the Ultimate Guitar index, gtptabs.com's or your library has (``_known_song``): "oasis live forever" is
    never a page titled "Oasis" or "Forever". The whole query first, then the longer titles; a title's pages
    oldest first, as ``musescore.song_pages`` lists a song's. Exact keys alone, so it reads the title index,
    never every row."""
    from caracole.musescore import SongPage, title_key

    words = name_words(query)
    runs = [(words, [])] + [(words[:n], words[n:]) for n in range(len(words) - 1, 0, -1)] + \
        [(words[-n:], words[:-n]) for n in range(len(words) - 1, 0, -1)]
    runs.sort(key=lambda run: -len(run[0]))  # stable: the whole query, then each length's start before its end
    hits: list[SiteHit] = []
    seen: set[str] = set()
    mine: list[set[tuple[str, str]]] = []  # your songs' artists and titles, read once, when a run needs them
    for run, rest in runs:
        text = " ".join(run)
        for key in (title_key(text), title_key(romanize(text)) if has_han(text) else ""):  # its slugs are ASCII
            if not key or key in seen:
                continue
            rows = conn.execute("SELECT page_id, path, title_key FROM musescore_index WHERE title_key = ? "
                                "ORDER BY page_id LIMIT ?", (key, max(limit, 0))).fetchall()
            if not rows or (rest and not _known_song(conn, " ".join(rest), key, mine)):
                continue
            seen.add(key)
            for row in rows:
                page = SongPage(*row)
                hits.append(SiteHit("musescore", _title_words(key), page.url, 100.0, title_key=key,
                                    via="both" if rest else "title"))
        if len(hits) >= limit:
            break
    return hits[:max(limit, 0)]


def search_lacuerda(conn: sqlite3.Connection, query: str, *, songs: int = SITE_ROWS,
                    artists: int = ARTIST_ROWS) -> tuple[list[SiteArtist], list[SiteHit]]:
    """LaCuerda's artists and songs in its index that match ``query``, best first (``lacuerda_index.find``):
    an artist's songs that only their name matched are in their row, and beside an artist whose whole name
    is the query, one whose name is only near it ("Andrés Canalla" for "andres calamaro") is left out, as
    ``find_index`` leaves it out. It reads the table alone."""
    from caracole.lacuerda_index import find

    found = find(conn, query, artists=artists, songs=songs)
    named = [a for a in found.artists if a.score >= 100] or found.artists
    return [_lacuerda_artist(conn, a) for a in named], [_lacuerda_song(h) for h in found.songs]


def lacuerda_artist(conn: sqlite3.Connection, slug: str) -> SiteArtist | None:
    """One artist of LaCuerda's index, by the slug of their page, as ``search_lacuerda`` gives them (score
    100); None for one it doesn't know."""
    from caracole.lacuerda_index import LaCuerdaHit, artist_songs
    from caracole.lacuerda import artist_url

    row = conn.execute("SELECT artist, artist_key, songs FROM lacuerda_index WHERE artist_slug = ? "
                       "ORDER BY title != '' LIMIT 1", (slug,)).fetchone()
    if row is None:
        return None
    hit = LaCuerdaHit(row[0], slug, row[1], artist_url(slug), 100.0, songs=row[2],
                      top=tuple(artist_songs(conn, slug, limit=TOP_SONGS, acordes=True)))
    return _lacuerda_artist(conn, hit)


def lacuerda_artist_named(conn: sqlite3.Connection, name: str) -> SiteArtist | None:
    """One artist of LaCuerda's index by their name, as LaCuerda writes it or as you do (``lacuerda_index.name_key``,
    of each of the name's forms too), as ``lacuerda_artist`` gives them: the one the index holds most of; None
    for a name it has no artist by."""
    from caracole.lacuerda_index import name_key

    keys = [k for k in dict.fromkeys([name_key(name), *(name_key(f) for f in name_forms(name))]) if k]
    if not keys:
        return None
    marks = ", ".join("?" for _ in keys)
    row = conn.execute(f"SELECT artist_slug FROM lacuerda_index WHERE artist_key IN ({marks}) GROUP BY artist_slug "
                       "ORDER BY COUNT(*) DESC, artist_slug LIMIT 1", keys).fetchone()
    return lacuerda_artist(conn, row[0]) if row is not None else None


def lacuerda_songs(conn: sqlite3.Connection, slug: str, *, title: str | None = None) -> list[SiteHit]:
    """The songs LaCuerda's index holds of an artist, most popular first, as LaCuerda orders them; none
    until caracole has read their page. With ``title``, only those whose title it matches, best first."""
    from dataclasses import replace

    from caracole.lacuerda_index import artist_songs

    hits = [_lacuerda_song(h) for h in artist_songs(conn, slug)]
    queries = _queries(title or "")
    if not queries:
        return hits
    scored = [(max(q.score("", h.title_key.replace("-", " ")) for q in queries), n, h) for n, h in enumerate(hits)]
    return [replace(h, score=round(score, 1), via="title")
            for score, _, h in sorted((s for s in scored if s[0] >= MIN_SCORE), key=lambda s: (-s[0], s[1]))]


def lacuerda_left_out(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """Why a search of LaCuerda's index finds less than LaCuerda has, worded to follow "LaCuerda's": ("empty",
    …) before the nightly run read any of its listings or artist pages, ("partial", …) while it reads its
    listings, with the letters read whole so far (the artists counted include those of a letter read in part);
    None once every listing page was read."""
    from caracole.lacuerda_index import index_state, letters_text

    state = index_state(conn)
    if state.empty:
        return "empty", "index is empty: the nightly run reads its listings of every artist"
    if state.complete:
        return None
    letters = letters_text(state.letters)
    whole = f", with {letters} read whole" if letters else ""
    return "partial", (f"index is still being read: {state.artists:,} artist{'' if state.artists == 1 else 's'} so "
                       f"far{whole}; the nightly run reads the rest")


def lacuerda_unlisted(conn: sqlite3.Connection, query: str, artists: Sequence[ArtistHit] = (),
                      songs: Sequence[IndexHit] = (), lead: str | None = None, *,
                      lacuerda: Sequence[SiteHit | SiteArtist] = (), artist: bool = False) -> tuple[str, str] | None:
    """For a query LaCuerda's index has no artist by, while it hasn't read whole the listing of the letter their
    name would be in (``lacuerda_index.unread_letter``): the name whose page can tell whether LaCuerda has them,
    and that letter as LaCuerda's menu names it ("E"). None when the index can tell.

    LaCuerda's own answer (``lacuerda``: ``search_lacuerda``'s artists and songs) tells first: a strong artist is
    the name, listed, and a strong song by its title alone ("como camaron") is a title, by its artist's name
    (and its title: "estopa como camaron") an artist the index holds, so none. Then the Ultimate Guitar
    index's answer (``artists``, ``songs``, ``lead``, as ``find_index`` gives them): a song by its title alone
    that leads ("creep", beside the artist The Creep) is no name, so none; else the artist that leads, or the
    artist of a strong song by its artist and title, or by part of the artist's name ("Enrique Bunbury" for
    "bunbury"). Else none when LaCuerda has an artist whose whole name is among the query's words (their row,
    ``lacuerda_index.NAMED``, says it); else the artist of an Ultimate Guitar song read by both its names,
    however weakly, whose whole name starts or ends the query (``_named_at_an_end``: "Estopa" for "estopa como
    camaron", whose page may hold the title Ultimate Guitar lacks); else the query. With ``artist``
    (``--artist NAME``) the query is the name."""
    from caracole.lacuerda_index import letters_text, unread_letter

    if any(h.score >= STRONG for h in lacuerda):
        return None
    name = query
    if not artist:
        strong = [h for h in songs if h.score >= STRONG]
        first = strong[0] if strong else None
        if artists and (lead == "artist" or first is None or first.via != "title"):
            name = artists[0].artist
        elif first is not None and first.via != "title" and first.artist and not no_ones(first.artist_key):
            name = first.artist
        elif first is not None and first.via == "title":
            return None
        elif any(isinstance(a, SiteArtist) and a.via == "both" for a in lacuerda):
            return None
        else:
            name = _named_at_an_end(query, songs) or query
    letter = unread_letter(conn, name)
    return (name, letters_text([letter])) if letter is not None else None


def _named_at_an_end(query: str, songs: Sequence[IndexHit]) -> str | None:
    """The artist of an Ultimate Guitar song the search read by both its names (``songs``, however weak), whose
    whole name is a run of the query's words at its start or its end, fewer than all of them: the longest run's,
    the better song's at a tie. None for none. An artist the search didn't read so is none: "Fito" is no
    answer for "fito paez", nor "Heroes" for "heroes del silencio entre dos tierras"."""
    words = name_words(query)
    runs: dict[str, int] = {}
    for n in range(len(words) - 1, 0, -1):
        for run in (words[:n], words[-n:]):
            for form in name_forms(" ".join(run)):
                runs.setdefault(compact(form), n)
    best: tuple[int, str] | None = None
    for h in songs:
        n = runs.get(compact(h.artist_key), 0) if h.via == "both" and h.artist and not no_ones(h.artist_key) else 0
        if n and (best is None or n > best[0]):
            best = n, h.artist
    return best[1] if best is not None else None


def lacuerda_leads(ug: IndexFound, lacuerda: Sequence[SiteArtist]) -> bool:
    """Whether LaCuerda's group comes before Ultimate Guitar's: it has an artist whose whole name is the query
    ("andres calamaro"), and the Ultimate Guitar index has no artist the query names and no strong song (only
    Javier Calamaro's). The lookup page's Enter then opens that artist's songs, which asks nothing."""
    return (any(a.score >= 100 for a in lacuerda) and not ug.artists
            and not any(h.score >= STRONG for h in ug.songs))


def _lacuerda_song(h: LaCuerdaHit) -> SiteHit:
    return SiteHit("lacuerda", h.title, h.url, h.score, h.artist, h.artist_key, h.title_key,
                   uploads=len(h.versions), via=h.via, sheet=h.sheet_url)


def _lacuerda_artist(conn: sqlite3.Connection, a: LaCuerdaHit) -> SiteArtist:
    known = conn.execute("SELECT COUNT(*) FROM lacuerda_index WHERE artist_slug = ? AND title != ''",
                         (a.artist_slug,)).fetchone()[0]
    return SiteArtist("lacuerda", a.artist, a.artist_slug, a.url, a.score, max(a.songs, known), known, a.via,
                      tuple(_lacuerda_song(t) for t in a.top))


def _known_song(conn: sqlite3.Connection, artist: str, title_key: str, mine: list[set[tuple[str, str]]]) -> bool:
    """Whether ``artist`` names the artist of a song titled ``title_key`` (a MuseScore title key) in the
    Ultimate Guitar index, gtptabs.com's (which files people last name first) or your library. ``mine``
    caches your songs' (artist form, title key) pairs, filled on the first call that needs them."""
    from caracole.musescore import title_key as key_of

    forms = [f for f in name_forms(artist) if f and not no_ones(f) and not placeholder_artist(f)]
    for form in forms:
        if conn.execute("SELECT 1 FROM ug_index WHERE artist_key = ? AND song_key = ? LIMIT 1",
                        (form, title_key)).fetchone() is not None:
            return True
        words = form.split("-")
        filed = list(dict.fromkeys([form, "-".join([words[-1], *words[:-1]])]))  # as gtptabs.artist_keys files them
        if conn.execute(f"SELECT 1 FROM gtptabs_index WHERE artist_key IN ({', '.join('?' * len(filed))}) "
                        "AND base_key = ? LIMIT 1", (*filed, title_key)).fetchone() is not None:
            return True
    if not forms:
        return False
    if not mine:
        pairs = set()
        for song in list_songs(conn):
            titles = {key_of(song.title), key_of(romanize(song.title))} - {""}
            for name in dict.fromkeys(song.artists or [song.artist]):
                pairs |= {(compact(f), t) for f in name_forms(name) for t in titles}
        mine.append(pairs)
    return any((compact(f), title_key) in mine[0] for f in forms)


def no_ones(artist_key: str) -> bool:
    """Whether an artist key is no one's name: every ``misc-…`` of UG's, ``misc-mashups`` too (two
    songs in one title), which never makes an artist row."""
    return artist_key.startswith(CATCH_ALL_PREFIX)


def library_by_artist(songs: Sequence[Song], name: str, artist_key: str | None = None) -> list[Song]:
    """Your songs by an artist, as ``name`` or UG's ``artist_key`` writes them (``normalize.name_forms``:
    UG's "Song Dongye" is your 宋冬野), or matched to that artist's songs; by title."""
    wanted = {compact(f) for f in name_forms(name)} | ({compact(artist_key)} if artist_key else set())
    wanted.discard("")
    mine = []
    for song in songs:
        forms = {compact(f) for a in dict.fromkeys(song.artists or [song.artist]) for f in name_forms(a)}
        matched = artist_key is not None and song.match_decision in ("accept", "pinned") \
            and song.match_artist_key == artist_key
        if forms & wanted or matched:
            mine.append(song)
    return sorted(mine, key=lambda s: (clean_title(s.title).casefold(), s.id))


def bare_id_hint(query: str, hits: Sequence[IndexHit | ArtistHit], *, artist: str | None = None,
                 overrides: Overrides | None = None) -> str | None:
    """What to do when the index can't see an artist, or None when the search went fine.

    Artists with accents or non-Latin letters in their names (Joaquín Sabina,
    Maná, 宋冬野) have no slugged rows in UG's sitemaps. The hint names the
    ``[artist_url]`` override, with a line to paste for ``artist`` (by default
    the query itself). It's given when nothing matches well, and, more briefly,
    for a query with such letters even when something does, but never when a
    strong hit comes from an artist page caracole read (``page``): caracole
    sees that artist's tabs. ``hits`` are the
    search's songs and artists. A query that is the line's key may be a title
    as well as an artist's name: the hint then says so, and that caracole
    needs the song's artist too, which no site is asked for. With ``artist``
    (``caracole search --artist``, or a song of yours the query found), the
    name is known to be the artist's.

    ``overrides`` is the file's (None when there is none to read). As on the
    to-do page, a table or a key declared twice makes it unreadable, so the line
    comes with the table's header only when it has no such table, and there is
    no line for an artist whose page it has, under any form of their name
    (``overrides.artist_url_entry``): the hint says so instead. The address may
    be the artist's page or one of their tab pages.
    """
    strong = any(h.score >= STRONG for h in hits)
    if strong and not any(c.isalpha() and not c.isascii() for c in query):
        return None
    if any(h.score >= STRONG and h.page for h in hits):  # an artist page caracole read answers it: it sees them
        return None
    lead = (
        "UG's sitemaps list artists with accented or non-Latin names only by bare ids." if strong else
        "Nothing in the offline Ultimate Guitar index matches well. UG's sitemaps list some artists only "
        "by bare ids, usually because of accents or non-Latin letters (Joaquín Sabina, Maná, 宋冬野), so "
        "caracole can't see their tabs."
    )
    shown = artist or " ".join(query.split())
    entry = artist_url_entry(overrides, name_forms(shown)) if overrides is not None else None
    if entry is not None:
        return (f"{lead} overrides.toml has {shown}'s page already ({entry[1]}): the nightly run looks "
                "there for the songs you add by them.")
    name = shown.replace("\\", "\\\\").replace('"', '\\"')
    line = f'"{name}" = "{ARTIST_PAGE_SHAPE}"'
    if overrides is not None and overrides.artist_url:
        where = (", under the [artist_url] table it has already (a second [artist_url] header would make "
                 "the file unreadable)")
        block = f"    {line}"
    else:
        where, block = "", f"    [artist_url]\n    {line}"
    if strong:
        return (
            f"{lead} If the one you want isn't above, find their page on ultimate-guitar.com, or one of "
            f"their tab pages, and paste its address, as your browser shows it, into overrides.toml"
            f"{where}:\n\n{block}"
        )
    find = "Find the artist's page" if artist else f"If {shown} is the artist's name, find their page"
    hint = (
        f"{lead} {find} on ultimate-guitar.com once, or one of their tab pages, and "
        f"paste its address, as your browser shows it (an artist page's ends in the artist's number, "
        f"as …/artist/634073 does), into overrides.toml{where}:\n\n{block}\n\n"
        "The key is the artist's name as your songs write it, so take any title words out of it. "
        "Then add the song with `caracole add`; the nightly run looks for its tabs on that page."
    )
    if not artist:  # the query may be the song's title: no site is asked for its artist
        hint += f"\n\nIf {shown} is a title, caracole needs its artist too: `caracole add ARTIST {_shell(shown)}`."
    return hint


# --- words, pinyin and scores -----------------------------------------------------------


def _forms(text: str) -> list[str]:
    """The text as space-separated words; Chinese gets a second form, in pinyin."""
    tokens = name_words(text)
    plain = " ".join(tokens)
    if not plain:
        return []
    if not has_han(plain):
        return [plain]
    return [plain, " ".join(fold(romanize(t)) if has_han(t) else t for t in tokens)]


def _patterns(tokens: list[str]) -> list[str]:
    """At most two ``LIKE`` patterns for the SQL prefilter, the most selective first.

    The tokens come from ``_tokens``, which splits on ``_`` and ``%``, so they
    never hold a ``LIKE`` wildcard.
    """
    found: list[tuple[int, str]] = []
    for token in tokens:
        if has_han(token):
            syllables = romanize(token).split()
            letters = sum(len(s) for s in syllables)
            if letters >= 4:
                found.append((letters, "%" + "%".join(fold(s) for s in syllables) + "%"))
        elif len(token) >= 3:
            found.append((len(token), f"%{token}%"))
    if not found:  # names made of initials
        latin = [t for t in tokens if not has_han(t)]
        if latin and len("".join(latin)) >= 2:
            key = "-".join(latin)
            found = [(len(key), f"%{key}%"), (len(key), f"%{key.replace('-', '')}%")]
    patterns: list[str] = []
    for _, pattern in sorted(found, key=lambda f: -f[0]):
        if pattern not in patterns:
            patterns.append(pattern)
    return patterns[:MAX_PATTERNS]


def _queries(text: str) -> list[_Query]:
    """The query's forms, ready to be scored: its words, and for Chinese its pinyin too, which carries
    each Chinese word's pinyin (``_Query.runs``) for the rule that pinyin counts only as words."""
    forms = _forms(text)
    if len(forms) < 2:
        return [_Query(f) for f in forms]
    runs = tuple("".join(fold(s) for s in romanize(t).split()) for t in name_words(text) if has_han(t))
    return [_Query(forms[0]), _Query(forms[1], runs)]


class _Query:
    """One form of a query, ready to be scored against many songs.

    ``runs`` is set on the pinyin form of a Chinese query: each Chinese word's
    pinyin, its syllables written together ("宋冬野" is ``songdongye``). That
    form counts for a song only where each of them is a whole run of the
    artist's words or of the title's (``holds``), as in the matcher, and a part
    of a name it matches tops out at ``PINYIN_PARTIAL_SCALE``, below a strong hit.
    """

    def __init__(self, text: str, runs: tuple[str, ...] = ()):
        self.text = text
        self.compact = text.replace(" ", "")
        self.runs = runs

    def holds(self, *names: str) -> bool:
        """Whether each Chinese word's pinyin is a whole run of the words of one of ``names`` (space-
        separated words), hyphens aside: ``song dongye``, ``songdongye`` and ``song dong ye`` hold
        宋冬野, and ``suburban male`` holds no 斑马. True for a form with no Chinese."""
        words = [name.split() for name in names]
        return all(any(holds_run(w, run) for w in words) for run in self.runs)

    def score(self, artist: str, title: str) -> float:
        """How well this query matches a song, 0–100 (artist and title are space-separated words).

        100 for the exact title, the exact artist, or both in either order; a
        typo costs a few points; a query that is only part of a name ("creep"
        in "creeping death", "musica" in "de musica ligera") gets at most 90.
        Everything is compared once more without spaces, so "ac dc" meets
        "acdc" and "banma" meets "ban ma".
        """
        return max(self.readings(artist, title))

    def readings(self, artist: str, title: str) -> tuple[float, float, float]:
        """``score`` split by the reading that gives it, in ``READINGS``' order: the query as the
        song's title, as both its names (their words in any order), as its artist. A part of the
        names counts for the title or the artist when it lies within that name, else for both:
        the same comparisons as one score, so the best of the three is ``score``."""
        if self.runs and not self.holds(artist, title):
            return (0.0, 0.0, 0.0)
        q, qc = self.text, self.compact
        a, t = artist.replace(" ", ""), title.replace(" ", "")
        full = f"{artist} {title}"
        by = {"title": max(fuzz.ratio(q, title), fuzz.ratio(qc, t)),
              "both": max(fuzz.token_sort_ratio(q, full), fuzz.ratio(qc, a + t)),
              "artist": max(fuzz.ratio(q, artist), fuzz.ratio(qc, a))}
        scale = PINYIN_PARTIAL_SCALE if self.runs else PARTIAL_SCALE
        # Spaced, the title starts after the artist and a space; compact, right after the artist.
        for needle, names, edge, gap in ((q, full, len(artist), 1), (qc, a + t, len(a), 0)):
            if len(needle) < len(names):
                part = fuzz.partial_ratio_alignment(needle, names)
                where = ("title" if part.dest_start >= edge else
                         "artist" if part.dest_end <= edge + gap else "both")
                by[where] = max(by[where], scale * part.score)
        return by["title"], by["both"], by["artist"]

    def name(self, artist: str) -> float:
        """How well this query is an artist's whole name, never a part of it: what makes an artist row."""
        if self.runs and not self.holds(artist):
            return 0.0
        return max(fuzz.ratio(self.text, artist), fuzz.ratio(self.compact, artist.replace(" ", "")))


def _reading(scores: Iterable[tuple[float, float, float]], reading: str | None = None) -> tuple[float, str]:
    """The best of several (title, both, artist) readings, and which reading it is; a tie goes to the
    title, then both. With ``reading``, that reading's alone."""
    best, via = 0.0, READINGS[0]
    for triple in scores:
        for name, score in zip(READINGS, triple):
            if score > best and reading in (None, name):
                best, via = score, name
    return best, via


def _song_reading(queries: list[_Query], song: Song, reading: str | None = None) -> tuple[float, str]:
    """The best score over a song's artists, each paired with its title, plain and in pinyin, and the
    reading that gave it."""
    return _names_reading(queries, song.artists or [song.artist], song.title, reading)


def _names_reading(queries: list[_Query], artists_: Sequence[str], title: str,
                   reading: str | None = None) -> tuple[float, str]:
    """``_song_reading`` for bare names: each artist paired with the title."""
    titles = _forms(clean_title(title)) or [""]
    scores = []
    for artist in dict.fromkeys(artists_):
        artists = _forms(artist) or [""]
        # Plain words with plain words, pinyin with pinyin (a form missing on one side is its plain one).
        for a, t in {(artists[0], titles[0]), (artists[-1], titles[-1])}:
            scores += [q.readings(a, t) for q in queries]
    return _reading(scores, reading)


# --- the index's rows, scored ------------------------------------------------------------------


class _Row(NamedTuple):
    """A song of the rows the prefilter read (its variants with it), scored."""

    score: float
    tabs: int
    artist_tabs: int  # the artist's tabs among the rows
    artist_key: str
    base: str
    via: str


class _Named(NamedTuple):
    """An artist of the rows whose whole name the query is, with what the rows hold of theirs."""

    score: float
    top: int  # the tabs of its most tabbed song
    tabs: int


def _scored_rows(conn: sqlite3.Connection, query: str,
                 reading: str | None = None) -> tuple[list[_Row], dict[str, _Named]]:
    """Every song of the rows the prefilter reads scored against the query, best first (ties to more
    tabs, then to the artist with more of the rows), and the artists the query names (none with
    ``reading``)."""
    patterns = _patterns(name_words(query))
    if not patterns:
        return [], {}
    queries = _queries(query)
    # Every row whose artist or song key matches a pattern, read from the keys' trigram index.
    groups: dict[tuple[str, str], int] = {}
    for artist_key, song_key, n in rows_like(conn, patterns):
        key = (artist_key, split_variant(song_key)[0])
        groups[key] = groups.get(key, 0) + n
    tabs: dict[str, int] = {}
    top: dict[str, int] = {}
    for (artist_key, _), n in groups.items():
        tabs[artist_key] = tabs.get(artist_key, 0) + n
        top[artist_key] = max(top.get(artist_key, 0), n)

    scored = []
    for (artist_key, base), n in groups.items():
        artist, title = artist_key.replace("-", " "), base.replace("-", " ")
        score, via = _reading((q.readings(artist, title) for q in queries), reading)
        if is_catch_all(artist_key):  # no one's name: the title holds the show's, so it is scored alone
            show = " ".join(w for w in base.split("-") if w not in SHOW_WORDS)
            alone = max((q.score("", t) for q in queries for t in (title, show) if t), default=0.0)
            if alone > score:
                score, via = alone, "title"
        if score >= MIN_SCORE:
            scored.append(_Row(score, n, tabs[artist_key], artist_key, base, via))

    named: dict[str, _Named] = {}
    if reading is None:
        for artist_key in tabs:
            if no_ones(artist_key):
                continue
            score = max(q.name(artist_key.replace("-", " ")) for q in queries)
            if score >= STRONG:
                named[artist_key] = _Named(score, top[artist_key], tabs[artist_key])
    listed, listed_named = _listed_rows(conn, queries, patterns, reading)
    scored = _merged(scored, listed)
    for artist_key, n in listed_named.items():
        old = named.get(artist_key)
        named[artist_key] = n if old is None else _Named(max(old.score, n.score), max(old.top, n.top),
                                                         max(old.tabs, n.tabs))
    scored.sort(key=lambda s: (-s.score, -s.tabs, -s.artist_tabs, s.artist_key, s.base))
    return scored, named


def _listed_rows(conn: sqlite3.Connection, queries: list[_Query], patterns: list[str],
                 reading: str | None) -> tuple[list[_Row], dict[str, _Named]]:
    """The songs of the artist pages caracole read (ug/artist_tabs.py) whose names hold a pattern, scored as
    the index's are but on every form of UG's names (``normalize.name_forms``: "Song Dongye (宋冬野)" is
    宋冬野 and Song Dongye), and their artists the query names (none with ``reading``)."""
    from caracole.ug.artist_tabs import rows_like

    songs: dict[tuple[str, str], dict[int, ListedTab]] = {}
    for tab in rows_like(conn, patterns):
        songs.setdefault((tab.artist_key, tab.song_key), {}).setdefault(tab.tab_id, tab)
    tabs: Counter[str] = Counter()
    top: Counter[str] = Counter()
    for (artist_key, _), group in songs.items():
        tabs[artist_key] += len(group)
        top[artist_key] = max(top[artist_key], len(group))
    scored = []
    for (artist_key, base), group in songs.items():
        names = {(t.artist_forms, t.title_forms) for t in group.values()}
        score, via = _reading((r for a, t in names for r in _forms_readings(queries, a, t)), reading)
        if score >= MIN_SCORE:
            scored.append(_Row(score, len(group), tabs[artist_key], artist_key, base, via))
    named: dict[str, _Named] = {}
    if reading is None:
        forms: dict[str, set[str]] = {}
        for (artist_key, _), group in songs.items():
            forms.setdefault(artist_key, set()).update(f for t in group.values() for f in t.artist_forms)
        for artist_key, names_ in forms.items():
            if no_ones(artist_key):
                continue
            score = max((q.name(f.replace("-", " ")) for q in queries for f in _same_script(q, names_)), default=0.0)
            if score >= STRONG:
                named[artist_key] = _Named(score, top[artist_key], tabs[artist_key])
    return scored, named


def _same_script(q: _Query, forms: Iterable[str]) -> list[str]:
    """The forms worth scoring against a form of the query: in Latin letters alone for a query in Latin
    letters alone (its pinyin, say), the others for one in another script."""
    return [f for f in forms if f.isascii() == q.text.isascii()]


def _forms_readings(queries: list[_Query], artist_forms: Sequence[str],
                    title_forms: Sequence[str]) -> Iterator[tuple[float, float, float]]:
    """Each query form's readings of each pair of an artist's form and a title's, of its script (a name with
    none of that script is no name for it, and a song with neither is no song for that form)."""
    for q in queries:
        artists, titles = _same_script(q, artist_forms), _same_script(q, title_forms)
        if not artists and not titles:
            continue
        for a in artists or [""]:
            for t in titles or [""]:
                yield q.readings(a.replace("-", " "), t.replace("-", " "))


def _merged(rows: list[_Row], listed: list[_Row]) -> list[_Row]:
    """The index's songs with the artist pages', one row a song: the better score, and the more tabs."""
    merged = {(r.artist_key, r.base): r for r in rows}
    for r in listed:
        old = merged.get((r.artist_key, r.base))
        if old is not None:
            best = r if r.score > old.score else old
            r = best._replace(tabs=max(r.tabs, old.tabs), artist_tabs=max(r.artist_tabs, old.artist_tabs))
        merged[(r.artist_key, r.base)] = r
    return list(merged.values())


def _hits(conn: sqlite3.Connection, rows: Sequence[_Row]) -> list[IndexHit]:
    yours = _Yours(conn)
    hits = (_index_hit(conn, r.artist_key, r.base, r.score, r.via, yours) for r in rows)
    return [h for h in hits if h is not None]


def _artist_groups(conn: sqlite3.Connection, artist_key: str) -> list[tuple[str, int]]:
    """Each song of an artist with its tabs (a song's variants counted with it), most tabbed first: the
    index's, with the tabs only an artist page caracole read lists (ug/artist_tabs.py)."""
    from caracole.ug.artist_tabs import unindexed_songs

    groups: dict[str, int] = {}
    for song_key, n in conn.execute(
        "SELECT song_key, COUNT(*) FROM ug_index WHERE artist_key = ? GROUP BY song_key", (artist_key,)
    ):
        base = split_variant(song_key)[0]
        groups[base] = groups.get(base, 0) + n
    for base, n in unindexed_songs(conn, artist_key).items():
        groups[base] = groups.get(base, 0) + n
    return sorted(groups.items(), key=lambda g: (-g[1], g[0]))


def _artist_hit(conn: sqlite3.Connection, artist_key: str, score: float,
                yours: _Yours | None = None) -> ArtistHit | None:
    """An artist with its songs and tabs counted and its most tabbed songs; None for no tab of theirs."""
    from caracole.ug.artist_tabs import artist_page

    groups = _artist_groups(conn, artist_key)
    if not groups:
        return None
    yours = yours or _Yours(conn)
    top = tuple(h for h in (_index_hit(conn, artist_key, base, score, "artist", yours) for base, _ in groups[:TOP_SONGS])
                if h is not None)
    name = top[0].artist if top else _title_words(artist_key)
    return ArtistHit(artist_key, name, round(score, 1), len(groups), sum(n for _, n in groups), top,
                     artist_page(conn, artist_key) or "")


# --- index hits ---------------------------------------------------------------------------


def _type_rank(kind: str) -> tuple[int, str]:
    return (TYPE_ORDER.index(kind) if kind in TYPE_ORDER else len(TYPE_ORDER), kind)


def index_song(conn: sqlite3.Connection, artist_key: str, song_key: str, score: float = 0.0) -> IndexHit | None:
    """One UG song of the index as a hit, as a search shows it: its tabs per type, a sample page and
    its names as UG writes them. None when the index has no tab of it."""
    return _index_hit(conn, artist_key, song_key, score)


def index_artist(conn: sqlite3.Connection, artist_key: str) -> ArtistHit | None:
    """One artist of the index as ``find_index`` gives it (score 100): its songs and tabs counted, its most
    tabbed songs and its name as UG writes it. None when the index has no tab of theirs."""
    return _artist_hit(conn, artist_key, 100.0)


def _index_hit(conn: sqlite3.Connection, artist_key: str, song_key: str, score: float,
               via: str = "both", yours: _Yours | None = None) -> IndexHit | None:
    """Every tab of the song, counted per type, with a sample page and names to show: the index's, and those
    an artist page caracole read lists (ug/artist_tabs.py), each tab once."""
    from caracole.ug.artist_tabs import song_tabs as listed_tabs

    tabs = song_tabs(conn, artist_key, song_key)
    listed = listed_tabs(conn, artist_key, song_key)
    if not tabs and not listed:
        return None
    ids = {t.tab_id for t in tabs}
    others = [t for t in listed if t.tab_id not in ids]
    counts = Counter(t.type for t in tabs) + Counter(t.type for t in others)
    ordered = {kind: counts[kind] for kind in sorted(counts, key=_type_rank)}
    labels = tuple(sorted({t.label for t in [*tabs, *others] if t.label}))
    rating, votes, page = None, 0, ""
    if tabs:
        sample = min(tabs, key=lambda t: (t.label is not None, _type_rank(t.type), t.tab_id))
        url = sample.url
        artist, title = _names_from_path(sample) or display_from_keys(artist_key, song_key)
    if listed:  # UG's ratings: the page's best tab, of the best type, unless the index has a better type
        best = _best_listed(listed)
        page = best.page
        if not tabs or (best.label is not None, _type_rank(best.type)) <= (sample.label is not None,
                                                                           _type_rank(sample.type)):
            url, rating, votes = best.url, best.rating if best.votes else None, best.votes  # no vote: unrated
        if not tabs:
            artist, title = (yours or _Yours(conn)).artist(best.artist), _original_title(best.title)
    return IndexHit(artist_key, song_key, ordered, round(score, 1), url, labels, artist, title, via, rating, votes,
                    page)


def _best_listed(listed: Sequence[ListedTab]) -> ListedTab:
    """The tab a song's hit shows of those an artist page lists: of the best type (no part or "acoustic"
    label first), the best rated as a fetch rates versions (rank.py ``bayes``): each rating is pulled toward
    the vote-weighted mean of those tabs, the more the fewer votes it has."""

    def kind(t: ListedTab) -> tuple[bool, tuple[int, str]]:
        return (t.label is not None, _type_rank(t.type))

    first = min(kind(t) for t in listed)
    group = [t for t in listed if kind(t) == first]
    prior, m = prior_mean(group), RankPolicy().prior_votes
    return min(group, key=lambda t: (-bayes(t.rating, t.votes, prior, m), -t.votes, t.tab_id))


class _Yours:
    """Your songs' artists, those you removed too, read once: a song only an artist page lists is named as
    your songs name its artist (UG's "Song Dongye (宋冬野)" is your 宋冬野, or your "Song Dong Ye"), else by
    the original of UG's two names (``normalize.original_part``)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._names: list[tuple[str, set[str]]] | None = None

    def artist(self, name: str) -> str:
        if self._names is None:
            names: list[str] = []
            for artist, artists in self.conn.execute("SELECT artist, artists FROM songs ORDER BY id"):
                names += [artist, *_json_names(artists)]
            names += [r[0] for r in self.conn.execute("SELECT artist FROM removed ORDER BY removed_at DESC")]
            self._names = [(n, {compact(f) for f in name_forms(n)}) for n in dict.fromkeys(names) if n]
        wanted = {compact(f) for f in name_forms(name)}
        return next((n for n, forms in self._names if forms & wanted), None) or original_part(name)


def _json_names(value: str) -> list[str]:
    try:
        names = json.loads(value)
    except ValueError:
        return []
    return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []


_HAN_SPACE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])")


def _original_title(title: str) -> str:
    """A title as UG lists it on an artist page, by its original name: "斑马斑马" for "斑马 斑马 Banma Banma
    Zebra Zebra" (Chinese written together, as its key is), a title in one script as it is."""
    return _HAN_SPACE.sub("", original_part(clean_title(title)))


def _names_from_path(tab: IndexTab) -> tuple[str, str] | None:
    """Artist and title from the tab's sitemap path (``the-rifles/local-boy-chords-123``).

    The path keeps UG's slugs as written, so "The Rifles" keeps its "The". A
    variant's label is cut off the title. None for a bare or unexpected path.
    """
    artist_slug, sep, rest = tab.path.partition("/")
    suffix = f"-{tab.type}-{tab.tab_id}"
    if not sep or not rest.endswith(suffix):
        return None
    song_slug = rest[: -len(suffix)]
    if tab.label and song_slug.endswith(f"-{tab.label}"):
        song_slug = song_slug[: -len(tab.label) - 1]
    artist, title = display_from_keys(artist_slug, song_slug)
    return (artist, title) if artist and title else None


def _shell(s: str) -> str:
    """Double-quoted for a POSIX shell, as the lines to paste are printed."""
    return '"' + _SHELL_SPECIAL.sub(r"\\\1", s) + '"'


def _title_words(key: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in key.split("-") if w)
