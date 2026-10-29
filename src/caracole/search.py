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
  A song's tabs, and an artist's songs and tabs, are chords and text tabs:
  the index keeps no other type (ug/sitemap.py ``KEEP_TYPES``).

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
yours. ``request_names`` says which words of a query are the artist and which
the title, for the pages' forms by name, only where the query tells: "Artist -
Title", "Title by Artist", or a known artist's whole name first ("Silvana
Estrada Que problema"; the suggested YouTube video's channel a name it knows
too), never a cut at the first space. The only popularity
the index holds is how many tabs a song or an artist has, so that orders the
ties, and the artist with a
more tabbed song than any song titled like it leads. Nothing here asks any
site: an artist the index doesn't know is the user's to type.

**By a word of the name.** An artist whose name holds every word of the query
as words of its own, among others ("lynyrd" or "skynyrd": Lynyrd Skynyrd;
"horse": Horse the Band), is an artist row too, after those the query is the
whole name of (``ArtistHit.part``, scored ``PART``), unless well known and with
many more songs than one of those (``_with_parts``: "dylan" is Bob Dylan before
Dylan), their songs in their row, by their songs weighed by how much of the
name the query is (``_parts``, bounded so that a word in hundreds of names,
"the" or "band", names no one that way). Such an artist leads when their songs
are most of the songs the query matched (``MOST_SONGS`` of them at least), or
when they have ``WELL_KNOWN`` songs and one more tabbed than any song read by
its title (``_part_leads``): "skynyrd" is Lynyrd Skynyrd, with Sam Grow's song
"Skynyrd" still listed. The index of every artist key's words
(``ug_artists_fts``, db.py) finds them without reading the rows.

**Close spellings.** For a query nothing matches well, ``suggestions`` gives up
to ``SUGGESTED`` artists whose names are spelled close to it
(``suggest_artists``: "lynrd" is Lynyrd Skynyrd, "metalica" Metallica), from
the words of the index's artists' names (``ug_artist_words``), LaCuerda's
listings and harptabs.com's sitemap, and songs whose titles are
(``suggest_titles``: "hotl califronia" is the Eagles' Hotel California,
"wonderwal oasys" Oasis's Wonderwall), from the index's rows by the words of
their keys (``ug_index_fts``), those words once each (``ug_key_words``,
``_Vocabulary``), LaCuerda's songs and harptabs.com's, ranked together, never a
site; the pages say "Did you mean" them.

**Other sites' indexes.** ``search_gtptabs`` reads gtptabs.com's song pages
(``gtptabs_index``, from its sitemaps), scored as the index's songs are, and
``search_musescore`` MuseScore's (``musescore_index``), which give a title
alone: a page there is one whose whole title is the query, or the query less
an artist's name on either side, where that artist has a song of that title in
the Ultimate Guitar index, gtptabs.com's or your library; a possible match,
never more. ``search_harptabs`` reads harptabs.com's index as the Ultimate Guitar index is
read: its artists (the sitemap's, named from their page once caracole has read it,
harptabs_index.py), the query as their whole name or a word of it (``SiteArtist``, with
the tabs their page says they have and their most viewed songs), and the tabs of the
artist pages read, a song a hit (``SiteHit``: the tabs of one title by one artist, the
title less what it says in brackets, ``harptabs.song_title``, the most viewed first, in
``tabs``), by any reading; then the sitemap's tabs whose artist no page read names, by
their title alone, as MuseScore's pages. ``harptabs_artist`` and ``harptabs_songs`` give
one of its artists and their songs. ``search_gametabs`` reads gametabs.net's (``gametabs_index``, from its
sitemaps, and the game pages caracole read, gametabs_index.py): a track of a game a hit (``SiteHit``, the game as
its artist, its tabs the most viewed first in ``tabs``), by its game, its title or a composer of its tabs (a game
page's alone say who). ``gtptabs_songs`` counts the songs gtptabs.com's index lists by an
artist, for an artist the query names. They only read the local tables: nothing here asks gtptabs.com or MuseScore
anything, and MuseScore's pages are for the user to open. ``search_lacuerda`` reads
LaCuerda's (``lacuerda_index``, from its listings of every artist and the artist pages
caracole has read): its songs as ``SiteHit``s, each with the page of the sheet a lookup
keeps (``sheet``), and the artists the query names as rows of their own (``SiteArtist``),
since the index holds every artist but the songs only of the artists whose page caracole
has read. ``lacuerda_artist`` and ``lacuerda_songs`` give one of its artists and the songs
the index holds of theirs. While its listings aren't read whole, ``lacuerda_unlisted`` names the
page that may tell whether LaCuerda has an artist it doesn't list, and ``lacuerda_leads`` says when
its group comes first. Nothing here asks LaCuerda: its own search is lacuerda_search.py's, a lookup
of its own, whose answers go into that index.

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
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator, Mapping, NamedTuple, Sequence

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
    identity_key,
    name_forms,
    name_words,
    original_part,
    placeholder_artist,
    romanize,
    slug_key,
    split_variant,
)
from caracole.overrides import ARTIST_PAGE_SHAPE, Overrides, artist_url_entry
from caracole.rank import bayes, prior_mean
from caracole.songs import Song, list_removed, list_songs
from caracole.ug.key_search import rows_like
from caracole.ug.lookup import IndexTab, song_tabs
from caracole.ug.page import KINDS

if TYPE_CHECKING:
    from caracole.lacuerda_index import LaCuerdaHit
    from caracole.ug.artist_tabs import ListedTab

MIN_SCORE = 70  # below this a hit is noise
STRONG = 90  # a hit this good is the song you meant
PARTIAL_SCALE = 0.9  # a query that is only part of a name tops out at 90
TYPE_ORDER = KINDS  # chords, then tabs
MAX_PATTERNS = 2
SHOWN_CANDIDATES = 3  # a review's candidates shown under its song: the rest are in `caracole review`
READINGS = ("title", "both", "artist")  # how a query may name a song; a tie goes to the first
TOP_SONGS = 3  # an artist row's most tabbed songs
ARTIST_ROWS, SONG_ROWS = 3, 8  # what ``find_index`` gives by default
SITE_ROWS = 5  # a site's pages search_gtptabs and search_musescore give by default
SITE_ROWS_READ = 2000  # rows of gtptabs_index the prefilter reads, at most
PART = round(PARTIAL_SCALE * 100, 1)  # an artist whose name holds the query's words among others: a part of a name
WORD_LETTERS = 3  # a query with no word this long (or Chinese word of four letters of pinyin) names no artist in part
WORD_ARTISTS = 300  # more artists than this hold the query's words: a common word ("band", "john"), no row
WELL_KNOWN = 50  # an artist with this many songs whose word the query is leads, unless a song titled so is more tabbed
MOST_SONGS = 5  # an artist a word names with fewer songs than this never leads by having most of the songs matched
OUTWEIGHS = 4  # a well-known artist a word names, with this many times the songs, goes before one the query names whole
SUGGESTED = 3  # the close spellings ``suggest_artists`` gives, at most
CLOSE = 80  # fuzz.ratio of a query's word and a name's word that makes them one spelled two ways
CLOSE_LETTERS = 4  # a word shorter than this is spelled close to too much: it must be the name's word itself
CLOSE_WORDS = 20  # the words of artists' names, spelled close to one of the query's, a suggestion looks among
CLOSE_ARTISTS = 1000  # the artists with those words it reads, at most
CLOSE_MARGIN = 8  # a suggestion this much less close than the closest is noise beside it ("lynrd": no Lynda Lemay)
SUGGEST_SHARE = 10  # a suggestion weighing less than a tenth of the first one's is noise beside it ("metalika": no Malika)
CLOSE_TABS = 5000  # rows a title is suggested from at most: more hold the query's words, too common to name a title
CLOSE_PATTERNS = 2  # the close spellings of the query's longest word another site's songs are looked for by
TAB_SONGS = 5  # a song's tab weighs as five of an artist's songs (on the full index: 1.4 tabs a song, 7.2 songs an artist)

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
    counted with the index's. ``part`` is True for an artist the query names
    only in part, as words of their name among others ("skynyrd" of Lynyrd
    Skynyrd), scored ``PART``.
    """

    artist_key: str
    artist: str
    score: float
    songs: int
    tabs: int
    top: tuple[IndexHit, ...] = ()
    page: str = ""
    part: bool = False

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
    tabbed song of its own; one the query names in part, by ``_part_leads``),
    "song" otherwise, None for no hit; ``best`` is
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
class HarpTabHit:
    """One tab of a song on harptabs.com: its title as the site writes it, its page, and the chips its artist's
    page showed (the views, the rating, the key, the difficulty)."""

    title: str
    url: str
    views: int = 0
    rating: float | None = None
    key: str | None = None
    difficulty: str | None = None


@dataclass(frozen=True)
class GameTabHit:
    """One tab of a track on gametabs.net: its title, its page, and what its game's page said of it (nothing before
    caracole read that page): its views, its fun rating, its instruments and its composers."""

    title: str
    url: str
    views: int = 0
    rating: float | None = None
    instruments: tuple[str, ...] = ()
    composers: tuple[str, ...] = ()


@dataclass(frozen=True)
class SiteHit:
    """A page of another site's offline index the query matches.

    ``source`` is "gtptabs" (a song page of gtptabs.com: an artist and a title,
    named from its slugs, its uploads of the title counted in ``uploads``),
    "musescore" (a song page of MuseScore: a title alone, as its sitemaps give
    it, so ``artist`` is "" and the page a possible match), "harptabs" (a song's
    harmonica tabs on harptabs.com, the most viewed first in ``tabs``, ``url`` the
    first's, by the artist whose page caracole read, ``page``; or a tab of its sitemap
    whose artist no page read names, a title alone, as MuseScore's), "gametabs" (a track of a
    game on gametabs.net, the game its ``artist``, its tabs the most viewed first in ``tabs``,
    ``url`` the first's, ``page`` the game's slug) or "lacuerda" (a song
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
    tabs: tuple[HarpTabHit | GameTabHit, ...] = ()
    page: str = ""


@dataclass(frozen=True)
class SiteArtist:
    """An artist of another site's offline index the query names: LaCuerda's or harptabs.com's (``source``).

    ``artist`` is the name the site writes, ``slug`` its own name for their page,
    ``url`` the page; ``songs`` counts their songs as the site's listing does, and
    ``known`` how many of them the index holds from their page, 0 until caracole has
    read it (the songs LaCuerda's search brought alone leave it 0); ``top`` holds the
    most popular with chords. On harptabs.com, ``slug`` is their page's path
    (``artist/1178/billy-joel``), ``songs`` the tabs their page says they have (0 until
    it is read: the sitemap counts none), ``known`` the tabs of theirs the index holds
    (the 30 their page lists at most), ``top`` their most viewed songs, and ``read`` whether caracole has read
    their page (one that lists no tab too, its ``known`` 0). ``score`` and ``via`` are as ``IndexHit``'s, and
    ``part`` as ``ArtistHit``'s (``LaCuerdaHit.part``).
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
    part: bool = False
    read: bool = False


@dataclass(frozen=True)
class Suggestion:
    """An artist whose name is spelled close to the query (``suggest_artists``), or a song whose title is
    (``suggest_titles``: its ``title``, and the song on each index that has it, ``hits``, Ultimate Guitar's
    ``IndexHit`` first, then LaCuerda's, gtptabs.com's and harptabs.com's ``SiteHit``), under its artist. The artist
    is Ultimate Guitar's (``source`` "ug", ``key`` their artist key, which /api/artist takes), LaCuerda's
    ("lacuerda", ``key`` the slug of their page) or harptabs.com's ("harptabs", ``key`` their page's path).
    ``artist`` is the name to show, ``songs`` how many songs the index (or LaCuerda's listing) has of theirs, the
    tabs their page says they have on harptabs.com, and ``score`` how close the query's words are to the name's (a
    song's: to its title's and its artist's), 0–100."""

    source: str
    artist: str
    key: str
    songs: int
    score: float
    title: str = ""
    hits: tuple[IndexHit | SiteHit, ...] = ()


def display_from_keys(artist_key: str, song_key: str) -> tuple[str, str]:
    """An artist and a title made from UG keys or slugs: each word capitalized.

    ``("soda-stereo", "de-musica-ligera")`` gives ``("Soda Stereo", "De Musica Ligera")``.
    Only a word's first letter changes, so "3am" stays "3am".
    """
    return _title_words(artist_key), _title_words(song_key)


def did_you_mean(song: Song, limit: int = SHOWN_CANDIDATES) -> list[dict]:
    """A song in review's first candidates, best first (``songs.match_candidates`` rows): the UG songs
    the matcher thinks it may be. Empty for a song not in review."""
    from caracole.review import candidates_of

    return candidates_of(song)[:limit] if song.review else []


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
    scored, _, _ = _scored_rows(conn, query)
    return _hits(conn, scored[:limit])


def find_index(conn: sqlite3.Connection, query: str, *, artists: int = ARTIST_ROWS, songs: int = SONG_ROWS,
               reading: str | None = None) -> IndexFound:
    """The offline index's artists and songs for ``query`` (``IndexFound``); with ``reading`` "title",
    songs of that title alone, by any artist, and no artist rows."""
    scored, named, parts = _scored_rows(conn, query, reading)
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
        rows = _with_parts(rows, _part_rows(conn, {k: c for k, c in parts.items() if k not in named}, artists, yours),
                           artists)
    shown = {a.artist_key for a in rows}
    hits = _hits(conn, [s for s in scored if not (s.via == "artist" and s.artist_key in shown)][:songs])
    if not rows and not hits:
        return IndexFound()
    if rows and (_part_leads(rows[0], scored, hits) if rows[0].part else
                 not hits or (rows[0].score, rows[0].top_tabs) > (hits[0].score, hits[0].tabs)):
        return IndexFound(tuple(rows), tuple(hits), "artist", None)
    if not hits:  # only artists a word names, none of whom leads
        return IndexFound(tuple(rows), (), "song", None)
    first = hits[0]
    # Never one only an artist's name matched, nor one of a catch-all's: its artist is no one's name.
    best = first if first.score >= STRONG and first.via != "artist" and not first.catch_all else None
    return IndexFound(tuple(rows), tuple(hits), "song", best)


def _part_rows(conn: sqlite3.Connection, parts: Mapping[str, float], n: int, yours: _Yours) -> list[ArtistHit]:
    """Up to ``n`` of the artists the query names in part (``parts``: each with how much of the name the query's
    letters are), by their songs weighed by that share: Horse the Band's 30 songs before Horse Jumper of Love's 30,
    whose longer name "horse" is less of. Weighed first by their keys' songs in the index, then counted exactly for
    the few that may be shown."""
    if n <= 0 or not parts:
        return []
    counts = _song_counts(conn, list(parts))
    order = sorted(parts, key=lambda k: (-counts.get(k, 0) * parts[k], k))[:n + 2]
    rows = [a for a in (_artist_hit(conn, k, PART, yours, part=True) for k in order) if a is not None]
    return sorted(rows, key=lambda a: (-a.songs * parts[a.artist_key], -a.tabs, a.artist_key))[:n]


def _with_parts(rows: Sequence[ArtistHit], parts: Sequence[ArtistHit], n: int) -> list[ArtistHit]:
    """Up to ``n`` of the artists the query names (``rows``: whole names, or names near it) and those it names in
    part (``parts``), in one order: the second after the first, except that an artist named in part and well known
    goes before each one named whole that they outweigh (``_outweighs``): "dylan" is Bob Dylan (638 songs) before
    Dylan (27), "swift" Taylor Swift before Swift, "clapton" Eric Clapton before Claptone, a name near it; Prince
    stays before Prince Royce. The order among those named in part is kept, and those named whole keep their place
    in the ``n`` before any named in part but the first: "nelson" is Willie Nelson, Ricky Nelson, then Nelson (12
    songs), and Hawk Nelson is left out."""
    out = list(rows)
    at = 0  # an artist named in part goes after the one before them
    for p in parts:
        i = next((i for i in range(at, len(out)) if not out[i].part and _outweighs(p.songs, out[i].songs)), len(out))
        out.insert(i, p)
        at = i + 1
    while len(out) > max(n, 0):
        out.pop(max((i for i, a in enumerate(out) if a.part and i > 0), default=len(out) - 1))
    return out


def _outweighs(part: int, whole: int) -> bool:
    """Whether an artist named in part, with ``part`` songs, is the one meant before one named whole with ``whole``:
    well known (``WELL_KNOWN`` songs or more) and with ``OUTWEIGHS`` times their songs. On the full index the
    namesakes a famous artist's word finds have a tenth of their songs or less (Bob Dylan 638 and Dylan 27, Willie
    Nelson 737 and Nelson 12, Neil Young 477 and Youngr 2, John Lennon 125 and Lennon 12), while a band whose name is
    the word keeps its place beside a singer with it (Prince beside Prince Royce, Bush beside Kate Bush)."""
    return part >= WELL_KNOWN and part > OUTWEIGHS * whole


def _part_leads(artist: ArtistHit, scored: Sequence[_Row], hits: Sequence[IndexHit]) -> bool:
    """Whether an artist the query names in part comes before the songs: when their songs are most of the songs the
    query matched ("skynyrd": Lynyrd Skynyrd's 139 of 142) and they have ``MOST_SONGS`` or more (one song of La
    Naranja Metalica's for "metalica" takes no Enter), or when they are well known (``WELL_KNOWN`` songs or more)
    and have a song tabbed more than the first song read by its title (or both), the song that would lead: "zeppelin"
    is Led Zeppelin, "young" Neil Young before Hollywood Undead's "Young", "jones" George Jones before Brian
    McFadden's "Jones" (a soundtrack's "Davy Jones", more tabbed, holds the word among others), as an artist whose
    whole name is the query leads a song of that title only with a more tabbed song of their own ("imagine": John
    Lennon's song before Imagine Dragons)."""
    if not artist.part:
        return False
    if artist.songs >= MOST_SONGS and 2 * sum(1 for s in scored if s.artist_key == artist.artist_key) > len(scored):
        return True
    titled = next((h.tabs for h in hits if h.via != "artist"), 0)
    return artist.songs >= WELL_KNOWN and artist.top_tabs > titled


def _song_counts(conn: sqlite3.Connection, keys: Sequence[str]) -> dict[str, int]:
    """How many song keys the index has of each artist key (a song's variants each one), and the artist pages
    caracole read: what orders the artists before they are counted exactly."""
    counts: Counter[str] = Counter()
    for start in range(0, len(keys), 500):
        part = keys[start:start + 500]
        marks = ", ".join("?" * len(part))
        for table in ("ug_index", "ug_artist_tabs"):
            counts.update(dict(conn.execute(f"SELECT artist_key, COUNT(DISTINCT song_key) FROM {table} "
                                            f"WHERE artist_key IN ({marks}) GROUP BY artist_key", part).fetchall()))
    return dict(counts)


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


def suggest_artists(conn: sqlite3.Connection, query: str, limit: int = SUGGESTED, *,
                    lacuerda: bool = True, harptabs: bool = True) -> list[Suggestion]:
    """The artists whose name is spelled close to the query, for a query that matches nothing well: "lynrd" is
    Lynyrd Skynyrd, "metalica" Metallica, "beatels" the Beatles. Every word of the query must be close to a word of
    the name (``CLOSE`` by ``fuzz.ratio``; a word shorter than ``CLOSE_LETTERS`` the name's own word), and one of
    ``CLOSE_LETTERS`` letters or more must be in it; the most songs first, weighed by how much of the name the query
    is, as the artists a word names are ranked, none ``CLOSE_MARGIN`` less close than the closest, nor one weighing
    less than a ``SUGGEST_SHARE``th of the first ("metalika": Metallica, and no Malika Ayane). Up to ``limit`` of
    them, from the Ultimate Guitar index and, with ``lacuerda``, LaCuerda's, and with ``harptabs``, harptabs.com's
    (its sitemap's artists, by the tabs their page says they have, none before caracole reads it), ranked together
    ("beyonse": LaCuerda's Beyonce before Ultimate Guitar's Burst of Bonse, a longer name), an artist several have
    once, as Ultimate Guitar's, else as LaCuerda's (``_cut``).

    It reads the index of the artists' words alone (``ug_artist_words``, db.py): a long word's close spellings
    are looked for among the words that begin with its letter, a couple of letters longer or shorter (a typo in
    a name's first letter is no suggestion), then the artists with those words. Never a site, and nothing for
    Chinese, whose pinyin a typo can't be told in."""
    words = _suggestible(query)
    if words is None:
        return []
    return [s for _, s in _cut(_artist_suggestions(conn, words, lacuerda=lacuerda, harptabs=harptabs), limit)]


def suggest_titles(conn: sqlite3.Connection, query: str, limit: int = SUGGESTED, *, lacuerda: bool = True,
                   harptabs: bool = True, gtptabs: bool = True) -> list[Suggestion]:
    """The songs whose title is spelled close to the query, for a query that matches nothing well, each under its
    artist (``Suggestion.title``, and the song on each index that has it, ``hits``): "hotl califronia" is the Eagles'
    Hotel California, "stairwy to heavn" Led Zeppelin's Stairway To Heaven; an artist's words may stand beside the
    title's ("wonderwal oasys": Oasis's Wonderwall). Every word of the query must be close to a word of the title or
    of its artist (``CLOSE``, as an artist's; a short word that word itself), one at least of the title's; the most
    tabbed first, weighed by how much of the title the words close to it are (``_weighed``: "heavn" is Heaven's whole
    title, a third of Stairway To Heaven's), as ``suggest_artists`` ranks artists, and cut as it cuts them (``_cut``):
    a title once, by its most tabbed artist (a cover, or the title spelled another way, Heavy Nopal's "Hotel
    Califonia", gives way to the Eagles' song), none of UG's catch-alls, which are no one's.

    From the Ultimate Guitar index, by the words of its keys (``ug_index_fts``, db.py): each word of the query with
    its close spellings among the words of every key (``_near``), a row holding one of each, at most ``CLOSE_TABS``
    rows (a word that common names no title); with ``lacuerda``, LaCuerda's songs, and with ``harptabs``,
    harptabs.com's of the artist pages caracole read, both by the query's longest word (``_needles``);
    a song on several of them one suggestion, their counts together, under Ultimate Guitar's artist, else LaCuerda's,
    else harptabs.com's. With ``gtptabs``, a song gtptabs.com's index lists under its artist and title is one of its
    hits too (a mark on the pages). MuseScore's pages, titles alone, have no artist to suggest a song under. Never a
    site, and nothing for Chinese."""
    words = _suggestible(query)
    if words is None:
        return []
    found = _title_suggestions(conn, words, lacuerda=lacuerda, harptabs=harptabs, gtptabs=gtptabs)
    return [s for _, s in _cut(found, limit)]


def suggestions(conn: sqlite3.Connection, query: str, index: IndexFound, sites: Sequence[SiteHit | SiteArtist] = (),
                *, lacuerda: bool = True, harptabs: bool = True, gtptabs: bool = True) -> list[Suggestion]:
    """``suggest_artists`` and ``suggest_titles`` for a query nothing matches well, as the pages offer them ("Did you
    mean"), ranked together (a song's tabs against an artist's songs, each weighed by how much of the name the query
    is: "yesterdy" is the Beatles' Yesterday before Trading Yesterday), at most ``SUGGESTED`` in all, cut as
    ``_cut`` cuts them. None when the Ultimate Guitar index (``index``, ``find_index``'s answer) or another site's
    (``sites``: LaCuerda's and harptabs.com's artists and songs, gtptabs.com's and MuseScore's pages) has an artist
    whose whole name the query is (or a name near it, at ``STRONG`` or more on Ultimate Guitar's, above ``PART`` on
    another's, where a name the query is only inside of, "adelle" of La Banda del Lechuga, scores 85 and leaves room
    for Adele), or a song whose title (or title and artist) the query is whole, scored 100. A title that only begins
    with the query, or holds a word that does (scored 90), leaves room for one: "eminen" is the start of The Who's
    "Eminence Front", and Eminem is suggested. Any page of MuseScore's is a title someone wrote out as the query (its
    pages match by their exact title alone): no suggestion beside it. An artist the query names in part may be
    shown ("metalica": La Naranja Metalica): an artist suggested then is one with more songs than any artist shown,
    and none of them (Metallica). A song of the Ultimate Guitar index found near the query already (``STRONG`` or more
    by its title, or its title and artist: "hotel califronia" is the Eagles' Hotel California, scored 94) leaves no
    room for a title, nor is a song suggested whose every hit the results show; one another site's index found, a
    harmonica tab of harptabs.com, may still be suggested with the Ultimate Guitar song the search missed ("sweet chld
    o mine")."""
    for a in index.artists:
        if not a.part:
            return []
    if any(h.score >= 100 and h.via != "artist" for h in index.songs):
        return []
    titled = any(h.score >= STRONG and h.via != "artist" for h in index.songs)
    shown: list[tuple[str, int]] = [(compact(name_words_key(a.artist)), a.songs) for a in index.artists]
    for h in sites:
        if isinstance(h, SiteArtist):
            if h.score > PART and not h.part:  # another site's whole name, or a name near it: a part tops out at PART
                return []
            shown.append((compact(name_words_key(h.artist)), h.songs))
        elif h.source == "musescore" or (h.score >= 100 and h.via != "artist"):
            return []
    words = _suggestible(query)
    if words is None:
        return []
    most = max((n for _, n in shown), default=0)
    names = {name for name, _ in shown}
    artists = [(w, s) for w, s in _cut(_artist_suggestions(conn, words, lacuerda=lacuerda, harptabs=harptabs))
               if s.songs > most and compact(name_words_key(s.artist)) not in names]
    hits = {("ug", h.artist_key, h.song_key) for h in index.songs} | {
        (h.source, h.url) for h in sites if isinstance(h, SiteHit)}
    titles = [] if titled else [
        (w, s) for w, s in _cut(_title_suggestions(conn, words, lacuerda=lacuerda, harptabs=harptabs, gtptabs=gtptabs))
        if not all(_shown(h) in hits for h in s.hits)]
    return [s for _, s in _cut(artists + titles)]


def _shown(hit: IndexHit | SiteHit) -> tuple[str, ...]:
    """What tells a hit among the results: an Ultimate Guitar song by its keys, another site's page by its address."""
    return ("ug", hit.artist_key, hit.song_key) if isinstance(hit, IndexHit) else (hit.source, hit.url)


def name_words_key(name: str) -> str:
    """A name's words written together, as a suggestion is told from another of the same artist."""
    return "".join(name_words(name))


def _suggestible(query: str) -> list[str] | None:
    """The query's words a close spelling is looked for by: None for none, Chinese (whose pinyin a typo can't be told
    in), or no word of ``CLOSE_LETTERS`` letters or more."""
    words = name_words(query)
    if not words or any(has_han(w) for w in words) or not any(len(w) >= CLOSE_LETTERS for w in words):
        return None
    return words


SUGGESTING = ("ug", "lacuerda", "harptabs")  # an artist several indexes have is suggested once: as the first's


def _cut(close: Sequence[tuple[float, Suggestion]], limit: int = SUGGESTED) -> list[tuple[float, Suggestion]]:
    """The weighed suggestions worth showing, the heaviest first (``_ranked``), at most ``limit``: none ``CLOSE_MARGIN``
    less close than the closest ("lynrd": no Lynda Lemay), an artist several indexes have once (as Ultimate Guitar's,
    else LaCuerda's: ``SUGGESTING``), a title once (its heaviest song's: a cover, or a title spelled close to it,
    ``CLOSE``, gives way), and none weighing less than a ``SUGGEST_SHARE``th of the first ("metalika": no Malika
    Ayane, nor a song titled Malika)."""
    closest = max((s.score for _, s in close), default=0.0)
    close = [(w, s) for w, s in close if s.score >= closest - CLOSE_MARGIN]
    first: dict[str, int] = {}  # the first index of SUGGESTING that has an artist of each name
    for _, s in close:
        if not s.title:
            name = compact(name_words_key(s.artist))
            first[name] = min(first.get(name, len(SUGGESTING)), _suggesting(s.source))
    kept: list[tuple[float, Suggestion]] = []
    names: set[str] = set()
    titles: list[str] = []
    for w, s in _ranked(close):
        if s.title:
            title = compact(name_words_key(s.title))
            if any(fuzz.ratio(title, t) >= CLOSE for t in titles):
                continue
            titles.append(title)
        else:
            name = compact(name_words_key(s.artist))
            if name in names or _suggesting(s.source) != first[name]:
                continue
            names.add(name)
        kept.append((w, s))
    top = kept[0][0] if kept else 0.0
    return [(w, s) for w, s in kept if w * SUGGEST_SHARE >= top][:max(limit, 0)]


def _suggesting(source: str) -> int:
    return SUGGESTING.index(source) if source in SUGGESTING else len(SUGGESTING)


def _closeness(words: Sequence[str], name: Sequence[str]) -> float | None:
    """How close the query's words are to a name's words, the mean of each one's closest (0–100); None when one has
    none close (``CLOSE``), a short one none equal."""
    scores = []
    for w in words:
        if len(w) < CLOSE_LETTERS:
            best = 100.0 if w in name else 0.0
        else:
            best = max((fuzz.ratio(w, n) for n in name), default=0.0)
        if best < CLOSE:
            return None
        scores.append(best)
    return sum(scores) / len(scores)


def _close_words(conn: sqlite3.Connection, word: str) -> list[str]:
    """The words of the index's artists' names spelled close to ``word``: of its first letter, at most two letters
    longer or shorter, ``CLOSE`` or more, the closest ``CLOSE_WORDS``."""
    from rapidfuzz import process

    start = word[0]
    terms = [t for (t,) in conn.execute("SELECT term FROM ug_artist_words WHERE term >= ? AND term < ?",
                                        (start, chr(ord(start) + 1))) if abs(len(t) - len(word)) <= 2]
    return [t for t, _, _ in process.extract(word, terms, scorer=fuzz.ratio, score_cutoff=CLOSE, limit=CLOSE_WORDS)]


def _weighed(songs: int, letters: int, name: str) -> float:
    """A suggestion's weight: their songs, weighed by how much of the name (its letters) the query's letters are."""
    return songs * min(1.0, letters / max(len(compact(name)), 1))


def _ranked(close: Iterable[tuple[float, Suggestion]]) -> list[tuple[float, Suggestion]]:
    """Weighed suggestions (``_weighed``), the heaviest first, then the closest; every index's together."""
    return sorted(close, key=lambda c: (-c[0], -c[1].score, c[1].artist.casefold(), c[1].title.casefold(),
                                        _suggesting(c[1].source)))


def _artist_suggestions(conn: sqlite3.Connection, words: Sequence[str], *, lacuerda: bool = True,
                        harptabs: bool = True) -> list[tuple[float, Suggestion]]:
    return (_ug_suggestions(conn, words) + (_lacuerda_suggestions(conn, words) if lacuerda else [])
            + (_harptabs_suggestions(conn, words) if harptabs else []))


def _ug_suggestions(conn: sqlite3.Connection, words: Sequence[str]) -> list[tuple[float, Suggestion]]:
    """The Ultimate Guitar index's artists spelled close to the query, each weighed (``_weighed``): the heaviest few,
    counted exactly."""
    longest = max((w for w in words if len(w) >= CLOSE_LETTERS), key=len)
    close = _close_words(conn, longest)
    if not close:
        return []
    match = " OR ".join(f'"{t}"' for t in close)
    keys = [r[0] for r in conn.execute(
        "SELECT artist_key FROM ug_artists WHERE id IN (SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?) "
        "LIMIT ?", (match, CLOSE_ARTISTS))]
    scored = {k: c for k in keys if not no_ones(k) and (c := _closeness(words, k.split("-"))) is not None}
    if not scored:
        return []
    counts = _song_counts(conn, list(scored))
    letters = sum(len(w) for w in words)
    ranked = _ranked((_weighed(counts[k], letters, k), Suggestion("ug", "", k, 0, round(c, 1)))
                     for k, c in scored.items() if counts.get(k, 0))
    out = []
    for _, s in ranked[:SUGGESTED * 2]:
        hit = _artist_hit(conn, s.key, s.score)
        if hit is not None:
            out.append((_weighed(hit.songs, letters, s.key), Suggestion("ug", hit.artist, s.key, hit.songs, s.score)))
    return out


def _lacuerda_suggestions(conn: sqlite3.Connection, words: Sequence[str]) -> list[tuple[float, Suggestion]]:
    """LaCuerda's artists spelled close to the query, from its listings: the artists with a word of a long word's
    first letter (a ``LIKE`` on their keys), the query folded as those keys are (``lacuerda_index.name_key``)."""
    from caracole.lacuerda_index import name_key

    words = [w for w in name_key(" ".join(words)).split("-") if w] or list(words)
    firsts = sorted({w[0] for w in words if len(w) >= CLOSE_LETTERS})
    if not firsts:
        return []
    where = " OR ".join("artist_key LIKE ? OR artist_key LIKE ?" for _ in firsts)
    rows = conn.execute(f"SELECT artist, artist_slug, artist_key, songs FROM lacuerda_index WHERE title = '' "
                        f"AND ({where})", [p for c in firsts for p in (f"{c}%", f"%-{c}%")])
    letters = sum(len(w) for w in words)
    close = []
    for artist, slug, key, songs in rows:
        c = _closeness(words, key.split("-"))
        if c is not None:
            close.append((_weighed(songs, letters, key), Suggestion("lacuerda", artist, slug, songs, round(c, 1))))
    return _ranked(close)[:SUGGESTED * 2]


def _harptabs_suggestions(conn: sqlite3.Connection, words: Sequence[str]) -> list[tuple[float, Suggestion]]:
    """harptabs.com's artists spelled close to the query, from its sitemap (``harptabs_index``): those whose key (their
    name's) holds a needle of the query's longest word (``_needles``), by their key's words, of each long word's first
    letter; weighed by the tabs their page says they have, none before it is read (the sitemap counts none)."""
    longest = max(words, key=len)
    needles = _needles(words, [_near(conn, w) if w == longest else [w] for w in words])
    rows = [_HarpArtist(*r) for r in conn.execute(
        "SELECT i.path, i.page_id, i.key, a.name, a.tabs, a.read_at FROM harptabs_index i LEFT JOIN harptabs_artists a "
        f"ON a.path = i.path WHERE i.kind = 'artist' AND {_holds('i.key', needles)}", needles)]
    letters = sum(len(w) for w in words)
    close = []
    for row in rows:
        if row.read_at is not None and not row.name:  # a page gone names no one
            continue
        name = row.key.split("-")
        if not all(any(n[:1] == w[:1] for n in name) for w in words if len(w) >= CLOSE_LETTERS):
            continue
        c = _closeness(words, name)
        if c is not None:
            songs = row.tabs or 0
            close.append((_weighed(songs, letters, row.key), Suggestion("harptabs", row.shown, row.path, songs,
                                                                         round(c, 1))))
    return _ranked(close)[:SUGGESTED * 2]


# --- close spellings of a title ---------------------------------------------------------------------------------


class _Titled(NamedTuple):
    """A song of one index a title suggestion may be: its weight (by its tabs, versions or harmonica tabs, and how
    much of its title the query's words close to it are), how close those words are, the keys it is told from another
    song by (its artist's and its title's, compact), its ``source``, its artist there (``band``: Ultimate Guitar's
    artist key, the slug of their LaCuerda page, the path of their harptabs.com page), and what makes its hit:
    Ultimate Guitar's song key, LaCuerda's ``SiteHit``, harptabs.com's song key."""

    weight: float
    score: float
    artist: str
    title: str
    source: str
    band: str
    hit: str | SiteHit


def _title_suggestions(conn: sqlite3.Connection, words: Sequence[str], *, lacuerda: bool = True, harptabs: bool = True,
                       gtptabs: bool = True) -> list[tuple[float, Suggestion]]:
    """The songs spelled close to the query on each index (``suggest_titles``), a song several have once, weighed
    together (a tab as ``TAB_SONGS`` of an artist's songs, as a title is weighed against an artist): those ``_cut``
    may keep, each made a ``Suggestion``."""
    near = [_near(conn, w) for w in words]
    found = _ug_titled(conn, words, near)
    if lacuerda:
        found += _lacuerda_titled(conn, words, near)
    if harptabs:
        found += _harptabs_titled(conn, words, near)
    songs: dict[tuple[str, str], list[_Titled]] = {}
    for t in found:
        songs.setdefault((t.artist, t.title), []).append(t)
    merged = [(TAB_SONGS * sum(t.weight for t in ts), max(t.score for t in ts),
               sorted(ts, key=lambda t: _suggesting(t.source))) for ts in songs.values()]
    closest = max((score for _, score, _ in merged), default=0.0)
    merged.sort(key=lambda m: (-m[0], -m[1], m[2][0].artist, m[2][0].title))
    kept: list[tuple[float, float, list[_Titled]]] = []
    titles: list[str] = []
    for weight, score, ts in merged:  # as _cut keeps them, before each is made
        if score < closest - CLOSE_MARGIN or any(fuzz.ratio(ts[0].title, t) >= CLOSE for t in titles):
            continue
        titles.append(ts[0].title)
        if weight * SUGGEST_SHARE < (kept[0][0] if kept else weight) or len(kept) >= SUGGESTED:
            break
        kept.append((weight, score, ts))
    yours = _Yours(conn)
    made = ((weight, _title_suggestion(conn, ts, score, yours, gtptabs=gtptabs)) for weight, score, ts in kept)
    return [(weight, s) for weight, s in made if s is not None]


def _title_suggestion(conn: sqlite3.Connection, songs: Sequence[_Titled], score: float, yours: _Yours, *,
                      gtptabs: bool = True) -> Suggestion | None:
    """A song spelled close to the query, from each index that has it (Ultimate Guitar's first, one hit an index),
    under the artist of the first: their songs counted, as an artist's suggestion counts them."""
    from dataclasses import replace

    hits: list[IndexHit | SiteHit] = []
    band: tuple[str, str, str, int] | None = None
    for t in songs:
        if any(_source_of(h) == t.source for h in hits):
            continue
        if t.source == "ug":
            hit = _index_hit(conn, t.band, t.hit, score, "title", yours)
            if hit is not None:
                hits.append(hit)
                band = band or ("ug", hit.artist, t.band, len(_artist_groups(conn, t.band)))
            continue
        if t.source == "lacuerda":
            hit, artist = t.hit, lacuerda_artist(conn, t.band)
        else:
            hit = next(iter(_harp_grouped(conn, "t.artist = ? AND t.song_key = ?", [t.band, t.hit])), None)
            artist = harptabs_artist(conn, t.band)
        if hit is not None and artist is not None:
            hits.append(replace(hit, score=round(score, 1), via="title"))
            band = band or (t.source, artist.artist, artist.slug, artist.songs)
    if band is None:
        return None
    if gtptabs:
        hits += _gtptabs_titled(conn, hits[0], score)
    return Suggestion(*band, round(score, 1), title=hits[0].title, hits=tuple(hits))


def _source_of(hit: IndexHit | SiteHit) -> str:
    return "ug" if isinstance(hit, IndexHit) else hit.source


def _near(conn: sqlite3.Connection, word: str) -> list[str]:
    """``word`` and the words of the index's keys spelled close to it (``CLOSE`` or more, the closest ``CLOSE_WORDS``):
    of its first letter, at most two letters longer or shorter, among the words every key holds (``_Vocabulary``). A
    word shorter than ``CLOSE_LETTERS`` is itself alone."""
    if len(word) < CLOSE_LETTERS:
        return [word]
    from rapidfuzz import process

    terms = _vocabulary(conn).among(conn, word)
    close = process.extract(word, terms, scorer=fuzz.ratio, score_cutoff=CLOSE, limit=CLOSE_WORDS)
    return list(dict.fromkeys([word, *(t for t, _, _ in close)]))


def _word_closeness(word: str, other: str) -> float:
    """How close a word of the query is to a word of a name (0–100): ``fuzz.ratio`` for a long one of the same first
    letter, as ``_near`` finds them; a short one is the word itself or nothing."""
    if len(word) < CLOSE_LETTERS:
        return 100.0 if word == other else 0.0
    return fuzz.ratio(word, other) if other[:1] == word[:1] else 0.0


def _title_closeness(words: Sequence[str], title: Sequence[str],
                     artist: Sequence[str]) -> tuple[float, float] | None:
    """How close the query's words are to a song's title and artist (their words), the mean of each one's closest, as
    ``_closeness`` has it; and what the song's tabs are weighed by: how much of the title the query is (the letters of
    its words close to the query's over all its letters), squared, as a title the query is only a part of is seldom
    the one meant ("yesterdy": Yesterday, and no Yesterday Once More); times as much of the artist's name, where words
    of the query are close to it ("hotl califronia" is little of Red Hot Chili Peppers' Dani California: "hot" of
    their name); times how close it is, from nothing at ``MIN_SCORE`` to all at 100, so that a title spelled no closer
    than an artist's name gives way to it ("metalika": Metallica, and no Malaika, at 80). None when a word is close to
    no word of either, or none is closer to a word of the title than of the artist: the artist's name alone is an
    artist's suggestion."""
    scores: list[float] = []
    held: set[int] = set()
    named: set[int] = set()
    for w in words:
        by_title, at = max(((_word_closeness(w, t), i) for i, t in enumerate(title)), default=(0.0, -1))
        by_artist, of = max(((_word_closeness(w, a), i) for i, a in enumerate(artist)), default=(0.0, -1))
        best = max(by_title, by_artist)
        if best < CLOSE:
            return None
        if by_title >= by_artist:
            held.add(at)
        else:
            named.add(of)
        scores.append(best)
    letters = sum(len(t) for t in title)
    if not held or not letters:
        return None
    closeness = sum(scores) / len(scores)
    share = (sum(len(title[i]) for i in held) / letters) ** 2
    if named:
        share *= sum(len(artist[i]) for i in named) / sum(len(a) for a in artist)
    return closeness, share * max(closeness - MIN_SCORE, 0.0) / (100 - MIN_SCORE)


def _ug_titled(conn: sqlite3.Connection, words: Sequence[str], near: Sequence[Sequence[str]]) -> list[_Titled]:
    """The Ultimate Guitar index's songs spelled close to the query: the rows holding a word close to each of its
    words (``ug_index_fts``), at most ``CLOSE_TABS`` (more, and the words are too common to suggest a title by), a
    song's variants with it, the most tabbed first; none of a catch-all's. Read until a song's tabs can no longer weigh
    a ``SUGGEST_SHARE``th of the heaviest's."""
    match = " AND ".join("(" + " OR ".join('"' + t.replace('"', '""') + '"' for t in n) + ")" for n in near)
    rows = conn.execute("SELECT artist_key, song_key FROM ug_index WHERE tab_id IN "
                        "(SELECT rowid FROM ug_index_fts WHERE ug_index_fts MATCH ? LIMIT ?)",
                        (match, CLOSE_TABS + 1)).fetchall()
    if len(rows) > CLOSE_TABS:
        return []
    tabs = Counter((artist_key, split_variant(song_key)[0]) for artist_key, song_key in rows)
    titled = {t for n in near for t in n}  # a title that holds none was found by its artist's name alone
    found: list[_Titled] = []
    heaviest = 0.0
    for (artist_key, base), n in sorted(tabs.items(), key=lambda t: (-t[1], t[0])):
        if n * SUGGEST_SHARE < heaviest:
            break
        if no_ones(artist_key) or titled.isdisjoint(base.split("-")):
            continue
        read = _title_closeness(words, base.split("-"), artist_key.split("-"))
        if read is None:
            continue
        weight = n * read[1]
        heaviest = max(heaviest, weight)
        found.append(_Titled(weight, read[0], compact(artist_key), compact(base), "ug", artist_key, base))
    return found


SITE_TITLES_READ = 2000  # another site's songs a title suggestion reads at most


def _needles(words: Sequence[str], near: Sequence[Sequence[str]]) -> list[str]:
    """What another site's songs are looked for by: their keys holding the query's longest word's first three letters,
    or one of its close spellings among the Ultimate Guitar index's words that doesn't (a typo in its second or third
    letter: ``CLOSE_PATTERNS`` of them at most)."""
    longest = max(range(len(words)), key=lambda i: len(words[i]))
    start = words[longest][:3]
    return [start, *[t for t in near[longest] if start not in t][:CLOSE_PATTERNS]]


def _holds(column: str, needles: Sequence[str]) -> str:
    """SQL: whether ``column`` holds one of ``needles`` (as many parameters)."""
    return "(" + " OR ".join(f"instr({column}, ?) > 0" for _ in needles) + ")"


def _lacuerda_titled(conn: sqlite3.Connection, words: Sequence[str], near: Sequence[Sequence[str]]) -> list[_Titled]:
    """LaCuerda's songs spelled close to the query (``lacuerda_index.songs_like``), by their versions there."""
    from caracole.lacuerda_index import songs_like

    found = []
    for h in songs_like(conn, [f"%{n}%" for n in _needles(words, near)], SITE_TITLES_READ):
        read = _title_closeness(words, h.title_key.split("-"), h.artist_key.split("-"))
        if read is not None:
            found.append(_Titled(max(len(h.versions), 1) * read[1], read[0], compact(h.artist_key),
                                 compact(h.title_key), "lacuerda", h.artist_slug, _lacuerda_song(h)))
    return found


def _harptabs_titled(conn: sqlite3.Connection, words: Sequence[str], near: Sequence[Sequence[str]]) -> list[_Titled]:
    """harptabs.com's songs spelled close to the query, of the artist pages caracole read: those whose title's key holds
    a needle (``_needles``: the query's longest word is the title's, as a title's words are most of a query's), by
    their harmonica tabs, the hit made once suggested."""
    from caracole.normalize import identity_key

    needles = _needles(words, near)
    rows = conn.execute(  # the song keys read from their index alone
        "SELECT artist, song_key, COUNT(*) FROM harptabs_artist_tabs WHERE song_key IN (SELECT DISTINCT song_key FROM "
        "harptabs_artist_tabs WHERE " + _holds("song_key", needles) + ") GROUP BY artist, song_key LIMIT ?",
        (*needles, SITE_TITLES_READ)).fetchall()
    paths = sorted({r[0] for r in rows})
    names = {path: (key, name) for path, key, name in conn.execute(
        f"SELECT path, key, name FROM harptabs_artists WHERE path IN ({', '.join('?' * len(paths))})", paths)} \
        if paths else {}
    found = []
    for path, song_key, tabs in rows:
        key, name = names.get(path, ("", ""))
        read = _title_closeness(words, song_key.split("-"), key.split("-"))
        if read is not None and name:
            artist_key = identity_key(name, "").partition("/")[0]
            found.append(_Titled(tabs * read[1], read[0], compact(artist_key), compact(song_key), "harptabs", path,
                                 song_key))
    return found


def _gtptabs_titled(conn: sqlite3.Connection, hit: IndexHit | SiteHit, score: float) -> list[SiteHit]:
    """gtptabs.com's page of a song (its artist's name and its title), as ``search_gtptabs`` gives one: by the keys of
    the name's forms, each also last word first, as the site files people, and the title's key; none for none."""
    from caracole.gtptabs import page_url

    keys: list[str] = []
    for form in name_forms(hit.artist):
        if form and not no_ones(form) and not placeholder_artist(form):
            words = form.split("-")
            keys += [form, "-".join([words[-1], *words[:-1]])]
    keys = list(dict.fromkeys(keys))
    base = split_variant(hit.song_key)[0] if isinstance(hit, IndexHit) else slug_key(hit.title)
    if not keys or not base:
        return []
    rows = conn.execute(f"SELECT path, artist_key FROM gtptabs_index WHERE artist_key IN ({', '.join('?' * len(keys))}) "
                        "AND base_key = ? AND title_key != '' ORDER BY path", (*keys, base)).fetchall()
    if not rows:
        return []
    return [SiteHit("gtptabs", _title_words(base), page_url(rows[0][0]), round(score, 1), hit.artist, rows[0][1], base,
                    len(rows), "title")]


class _Vocabulary:
    """The words of the Ultimate Guitar index's keys (``ug_key_words``, db.py), by first letter and length, as a process
    keeps them: a letter's words are read the first time a word of a query begins with it, and then only the words the
    table gained since (it only grows), so that a search reads no word twice. ``last``: the newest word's id read."""

    def __init__(self) -> None:
        self.last = 0
        self.letters: dict[str, dict[int, list[str]]] = {}
        self.lock = threading.Lock()

    def among(self, conn: sqlite3.Connection, word: str) -> list[str]:
        """The words that begin with ``word``'s letter, at most two letters longer or shorter."""
        with self.lock:
            top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM ug_key_words").fetchone()[0]
            if top < self.last:  # another database, made since at that path
                self.letters, self.last = {}, 0
            if top > self.last:
                new = conn.execute("SELECT term FROM ug_key_words WHERE id > ? AND id <= ?",
                                   (self.last, top)).fetchall() if self.letters else []
                for (term,) in new:
                    if term[:1] in self.letters:
                        self.letters[term[:1]].setdefault(len(term), []).append(term)
                self.last = top
            start = word[0]
            if start not in self.letters:
                by_length: dict[int, list[str]] = {}
                for (term,) in conn.execute("SELECT term FROM ug_key_words WHERE term >= ? AND term < ? AND id <= ?",
                                            (start, chr(ord(start) + 1), top)):
                    by_length.setdefault(len(term), []).append(term)
                self.letters[start] = by_length
            letter = self.letters[start]
            return [t for n in range(len(word) - 2, len(word) + 3) for t in letter.get(n, ())]


VOCABULARIES = 4  # the databases whose words a process keeps (``_Vocabulary``)
_VOCABULARIES: OrderedDict[str, _Vocabulary] = OrderedDict()
_VOCABULARIES_LOCK = threading.Lock()


def _vocabulary(conn: sqlite3.Connection) -> _Vocabulary:
    """The words this process keeps of the database ``conn`` is open on (by its file; one in memory keeps none)."""
    path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    if not path:
        return _Vocabulary()
    with _VOCABULARIES_LOCK:
        kept = _VOCABULARIES.pop(path, None) or _Vocabulary()
        _VOCABULARIES[path] = kept
        while len(_VOCABULARIES) > VOCABULARIES:
            _VOCABULARIES.popitem(last=False)
    return kept


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


def gtptabs_songs(conn: sqlite3.Connection, artist: str) -> int:
    """How many songs gtptabs.com's index lists by ``artist``: the song pages under the keys of the name's forms
    (``normalize.name_forms``), each also with its last word first, as the site files people ("Elton John" is
    ``john-elton``, as ``gtptabs.artist_keys`` has it); a title's uploads ("-2", "-3") one song, an artist's page
    none. By the table's artist index alone: no scan, so ``ac-dc`` there never meets an ``acdc`` here."""
    keys: list[str] = []
    for form in name_forms(artist):
        if form and not no_ones(form) and not placeholder_artist(form):
            words = form.split("-")
            keys += [form, "-".join([words[-1], *words[:-1]])]
    keys = list(dict.fromkeys(keys))
    if not keys:
        return 0
    return conn.execute(f"SELECT COUNT(DISTINCT base_key) FROM gtptabs_index WHERE artist_key IN "
                        f"({', '.join('?' * len(keys))}) AND title_key != ''", keys).fetchone()[0]


def search_musescore(conn: sqlite3.Connection, query: str, limit: int = SITE_ROWS) -> list[SiteHit]:
    """MuseScore's song pages whose title is the query, or the query with an artist's name on either side
    ("oasis wonderwall", "live forever oasis"): the sitemaps give titles alone, so each is a possible match.
    A run of the query's words is a title only when the rest names the artist of a song by that title, one
    the Ultimate Guitar index, gtptabs.com's or your library has (``_known_song``): "oasis live forever" is
    never a page titled "Oasis" or "Forever". The whole query first, then the longer titles; a title's pages
    oldest first, as ``musescore.song_pages`` lists a song's. Exact keys alone, so it reads the title index,
    never every row."""
    from caracole.musescore import SongPage, title_key

    def pages(key: str, n: int) -> list[str]:
        rows = conn.execute("SELECT page_id, path, title_key FROM musescore_index WHERE title_key = ? "
                            "ORDER BY page_id LIMIT ?", (key, n)).fetchall()
        return [SongPage(*row).url for row in rows]

    return _title_pages(conn, query, limit, "musescore", title_key, pages)


def search_gametabs(conn: sqlite3.Connection, query: str, limit: int = SITE_ROWS) -> list[SiteHit]:
    """gametabs.net's tracks in its index that match ``query``, best first, by any reading, as the index's songs are
    scored: a track of a game a hit, the game as its artist, the game's name or a composer of its tabs (by the game
    pages caracole read) as its artist's names; its tabs (``tabs``) the most viewed first, its ``url`` the first's.
    Ties go to the most viewed. The game is named as its page heads it once caracole read it, else from its slug, and
    the track as a card writes it, else from its slug (less the number a repeated title takes). It reads the tables
    alone."""
    from caracole.gametabs import TAB, page_url, title_key
    from caracole.normalize import identity_key

    patterns = _patterns(name_words(query))
    queries = _queries(query)
    if not patterns or not queries:
        return []
    paths = {r[0] for r in conn.execute(
        f"SELECT path FROM gametabs_index WHERE kind = ? AND ({' OR '.join('path LIKE ?' for _ in patterns)}) LIMIT ?",
        (TAB, *patterns, SITE_ROWS_READ))}
    paths.update(r[0] for r in conn.execute(
        f"SELECT path FROM gametabs_game_tabs WHERE {' OR '.join('composers LIKE ?' for _ in patterns)} LIMIT ?",
        (*patterns, SITE_ROWS_READ)))
    if not paths:
        return []
    marks = ", ".join("?" for _ in paths)
    listed = {r[0]: tuple(r)[1:] for r in conn.execute(
        f"SELECT path, title, views, rating, instruments, composers FROM gametabs_game_tabs WHERE path IN ({marks})",
        list(paths))}
    keyed = {r[0]: tuple(r)[1:] for r in conn.execute(
        f"SELECT path, game, key FROM gametabs_index WHERE kind = ? AND path IN ({marks})", (TAB, *paths))}
    games = {game for game, _ in keyed.values()} | {path.split("/")[1] for path in listed}
    marks = ", ".join("?" for _ in games)
    names = {r[0]: r[1] for r in conn.execute(f"SELECT game, name FROM gametabs_games WHERE name != '' AND game IN "
                                              f"({marks}) ORDER BY path", list(games))} if games else {}
    tracks: dict[tuple[str, str], list[tuple[str, str | None, tuple]]] = {}
    for path in paths:
        game = path.split("/")[1]
        row = listed.get(path)
        title = row[0] if row is not None else None
        key = title_key(title) if title else (keyed[path][1] if path in keyed else "")
        if key:
            tracks.setdefault((game, key), []).append((path, title, row or ()))
    scored = []
    for (game, key), tabs in tracks.items():
        name = names.get(game) or _title_words(game.replace("_", "-"))
        composers = list(dict.fromkeys(c for _, _, row in tabs for c in _listed_names(row[4] if row else None)))
        artists = [" ".join(name_words(name)), re.sub(r"[-_]", " ", game), *(" ".join(name_words(c)) for c in composers)]
        score, via = _reading(q.readings(a, key.replace("-", " ")) for q in queries for a in dict.fromkeys(artists) if a)
        if score >= MIN_SCORE:
            views = max((row[1] for _, _, row in tabs if row), default=0)
            scored.append((round(score, 1), views, name, key, game, tabs, via))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2], s[3]))
    hits = []
    for score, _, name, key, game, tabs, via in scored[:max(limit, 0)]:
        tabs.sort(key=lambda t: (-(t[2][1] if t[2] else 0), t[0]))
        title = next((t for _, t, _ in tabs if t), None) or _title_words(key)
        hits.append(SiteHit(
            "gametabs", title, page_url(tabs[0][0]), score, artist=name,
            artist_key=identity_key(name, "").partition("/")[0], title_key=key, uploads=len(tabs), via=via,
            tabs=tuple(GameTabHit(t or title, page_url(path), *((row[1], row[2], tuple(_listed_names(row[3])),
                                                                  tuple(_listed_names(row[4]))) if row else ()))
                       for path, t, row in tabs),
            page=game))
    return hits


def _listed_names(text: str | None) -> list[str]:
    """The names of a JSON array gametabs_game_tabs keeps (its instruments, its composers)."""
    try:
        names = json.loads(text or "[]")
    except (ValueError, RecursionError):
        return []
    return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []


def search_harptabs(conn: sqlite3.Connection, query: str, *, songs: int = SITE_ROWS,
                    artists: int = ARTIST_ROWS) -> tuple[list[SiteArtist], list[SiteHit]]:
    """harptabs.com's artists and songs in its index that match ``query``, as the Ultimate Guitar index answers it:
    the artists the query names whole (``STRONG`` or more) or by a word of their name (``PART``), beside one named
    whole only those named whole or in part; then the songs of the artist pages caracole read, by any reading, best
    first (a song only its artist's name matched is in that artist's row), at most ``songs``; then, at most ``songs``
    more, the sitemap's tabs whose artist no page read names, whose title is the query or the query less an artist's
    name (``_title_pages``), possible matches. It reads the tables alone."""
    from caracole.harptabs import TAB, joined, page_url, title_key

    queries = _queries(query)
    patterns = _patterns(name_words(query))
    named: list[SiteArtist] = []
    hits: list[SiteHit] = []
    if queries and patterns:
        named = _harp_artists(conn, query, queries, patterns, artists)
        theirs = {a.slug for a in named}
        hits = [h for h in _harp_songs(conn, queries, patterns) if not (h.via == "artist" and h.page in theirs)]

    def pages(key: str, n: int) -> list[str]:
        # Its tabs' keys join a contraction's end to its word (harptabs.joined), and a row keyed before has the key
        # as it is, until the next harptabs.com pass keys it again (harptabs_fetch.ensure_current_keys).
        keys = list(dict.fromkeys((joined(key), key)))
        rows = conn.execute(
            f"SELECT path FROM harptabs_index i WHERE kind = ? AND key IN ({', '.join('?' for _ in keys)}) AND NOT "
            "EXISTS (SELECT 1 FROM harptabs_artist_tabs t WHERE t.tab_id = i.page_id) ORDER BY page_id LIMIT ?",
            (TAB, *keys, n)).fetchall()
        return [page_url(row[0]) for row in rows]

    return named, hits[:max(songs, 0)] + _title_pages(conn, query, songs, "harptabs", title_key, pages)


def harptabs_artist(conn: sqlite3.Connection, path: str) -> SiteArtist | None:
    """One artist of harptabs.com's index, by their page's path, as ``search_harptabs`` gives them (score 100); None
    for one its sitemap doesn't list, or whose page is gone."""
    row = conn.execute(
        "SELECT i.path, i.page_id, i.key, a.name, a.tabs, a.read_at FROM harptabs_index i LEFT JOIN harptabs_artists a "
        "ON a.path = i.path WHERE i.path = ? AND i.kind = 'artist'", (path,)).fetchone()
    return _harp_artist(conn, _HarpArtist(*row), 100.0) if row is not None and (row[5] is None or row[3]) else None


def harptabs_songs(conn: sqlite3.Connection, path: str, *, title: str | None = None) -> list[SiteHit]:
    """The songs harptabs.com's index holds of an artist (their page's path), most viewed first: none until caracole
    has read their page. With ``title``, only those whose title it matches, best first."""
    from dataclasses import replace

    hits = _harp_grouped(conn, "t.artist = ?", [path])
    queries = _queries(title or "")
    if not queries:
        return hits
    scored = [(max(q.score("", h.title_key.replace("-", " ")) for q in queries), n, h) for n, h in enumerate(hits)]
    return [replace(h, score=round(score, 1), via="title")
            for score, _, h in sorted((s for s in scored if s[0] >= MIN_SCORE), key=lambda s: (-s[0], s[1]))]


class _HarpArtist(NamedTuple):
    """An artist row of harptabs.com's index, with what their page said once read (``name`` "" before, and for a
    page gone)."""

    path: str
    page_id: int
    key: str
    name: str | None
    tabs: int | None
    read_at: str | None

    @property
    def shown(self) -> str:
        return self.name or _title_words(self.key)

    def forms(self) -> list[str]:
        """The name's words to score: the slug's key, and the page's name once read."""
        forms = [self.key.replace("-", " ")]
        if self.name:
            forms.append(" ".join(name_words(self.name)))
        return [f for f in dict.fromkeys(forms) if f]


def _harp_artists(conn: sqlite3.Connection, query: str, queries: list[_Query], patterns: list[str],
                  limit: int) -> list[SiteArtist]:
    """The artists the query names: as their whole name, scored, else by words of their name among others (``PART``),
    unless more than ``WORD_ARTISTS`` names hold them; beside one named whole, only those named whole or in part."""
    where = " OR ".join("i.key LIKE ?" for _ in patterns)
    rows = [_HarpArtist(*r) for r in conn.execute(
        "SELECT i.path, i.page_id, i.key, a.name, a.tabs, a.read_at FROM harptabs_index i LEFT JOIN harptabs_artists a "
        f"ON a.path = i.path WHERE i.kind = 'artist' AND ({where}) LIMIT ?", (*patterns, SITE_ROWS_READ))]
    rows = [r for r in rows if r.read_at is None or r.name]  # a page gone names no one
    words = set(name_words(query))
    whole: list[tuple[float, _HarpArtist]] = []
    parts: list[_HarpArtist] = []
    for row in rows:
        score = max(q.name(f) for q in queries for f in row.forms())
        if score >= STRONG:
            whole.append((round(score, 1), row))
        elif all(len(w) >= WORD_LETTERS for w in words) and any(words <= set(f.split()) for f in row.forms()):
            parts.append(row)
    if len(parts) > WORD_ARTISTS:  # a common word ("band", "john") names no one in part
        parts = []
    found = [(score, False, row) for score, row in whole] + [(PART, True, row) for row in parts]
    if any(score >= 100 for score, _, _ in found):
        found = [f for f in found if f[0] >= 100 or f[1]]
    known = _harp_known(conn, [row.path for _, _, row in found])
    found.sort(key=lambda f: (-f[0], -known.get(f[2].path, 0), -(f[2].tabs or 0), f[2].page_id))
    return [_harp_artist(conn, row, score, part=part, known=known.get(row.path, 0)) for score, part, row in
            found[:max(limit, 0)]]


def _harp_known(conn: sqlite3.Connection, paths: Sequence[str]) -> dict[str, int]:
    """How many tabs the index holds of each artist (their page's path)."""
    if not paths:
        return {}
    marks = ", ".join("?" for _ in paths)
    return {r[0]: r[1] for r in conn.execute(
        f"SELECT artist, COUNT(*) FROM harptabs_artist_tabs WHERE artist IN ({marks}) GROUP BY artist", list(paths))}


def _harp_artist(conn: sqlite3.Connection, row: _HarpArtist, score: float, *, part: bool = False,
                 known: int | None = None) -> SiteArtist:
    """An artist row as ``SiteArtist``, with their ``TOP_SONGS`` most viewed songs."""
    from caracole.harptabs import page_url

    if known is None:
        known = _harp_known(conn, [row.path]).get(row.path, 0)
    top = tuple(_harp_grouped(conn, "t.artist = ?", [row.path])[:TOP_SONGS]) if known else ()
    return SiteArtist("harptabs", row.shown, row.path, page_url(row.path), score, songs=row.tabs or 0, known=known,
                      top=top, part=part, read=row.read_at is not None)


def _harp_songs(conn: sqlite3.Connection, queries: list[_Query], patterns: list[str]) -> list[SiteHit]:
    """The songs of the artist pages read that the query matches by any reading, best first, then most viewed."""
    from dataclasses import replace

    where = " OR ".join("t.song_key LIKE ? OR a.key LIKE ?" for _ in patterns)
    hits = _harp_grouped(conn, where, [p for p in patterns for _ in (0, 1)], SITE_ROWS_READ)
    pages = sorted({h.page for h in hits})
    slugs = dict(conn.execute(f"SELECT path, key FROM harptabs_artists WHERE path IN ({', '.join('?' * len(pages))})",
                              pages).fetchall()) if pages else {}
    scored = []
    for n, hit in enumerate(hits):
        names = {(slugs.get(hit.page, "").replace("-", " "), hit.title_key.replace("-", " ")),
                 (" ".join(name_words(hit.artist)), hit.title_key.replace("-", " "))}
        score, via = _reading(q.readings(a, t) for q in queries for a, t in names)
        if score >= MIN_SCORE:
            scored.append((round(score, 1), n, replace(hit, score=round(score, 1), via=via)))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [hit for _, _, hit in scored]


def _harp_grouped(conn: sqlite3.Connection, where: str, args: Sequence[Any], limit: int | None = None) -> list[SiteHit]:
    """The tabs of the artist pages read that ``where`` keeps (``t``, the tab; ``a``, its artist), a song a hit: the
    tabs of one title by one artist, the most viewed first; the songs most viewed first."""
    from caracole.harptabs import page_url, song_title
    from caracole.normalize import identity_key

    rows = conn.execute(
        "SELECT t.artist, t.path, t.title, t.song_key, t.views, t.rating, t.harp_key, t.difficulty, a.name "
        "FROM harptabs_artist_tabs t JOIN harptabs_artists a ON a.path = t.artist "
        f"WHERE {where} ORDER BY t.views DESC, t.place" + (" LIMIT ?" if limit is not None else ""),
        (*args, *(() if limit is None else (limit,)))).fetchall()
    songs: dict[tuple[str, str], list] = {}
    for row in rows:
        songs.setdefault((row[0], row[3]), []).append(row)
    hits = []
    for (page, key), tabs in songs.items():
        best = tabs[0]
        name = best[8]
        hits.append(SiteHit(
            "harptabs", song_title(best[2]), page_url(best[1]), 100.0, artist=name,
            artist_key=identity_key(name, "").partition("/")[0], title_key=key, uploads=len(tabs), via="title",
            tabs=tuple(HarpTabHit(t[2], page_url(t[1]), t[4], t[5], t[6], t[7]) for t in tabs), page=page))
    return hits


def _title_pages(conn: sqlite3.Connection, query: str, limit: int, source: str, title_key: Callable[[str], str],
                 pages: Callable[[str, int], list[str]]) -> list[SiteHit]:
    """A site's pages by title alone (MuseScore's, harptabs.com's: ``pages(key, n)``, their addresses), whose title
    is the query or the query less an artist's name on either side, that artist having a song of that title in
    the Ultimate Guitar index, gtptabs.com's or your library (``_known_song``). The whole query first, then the
    longer titles."""
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
            urls = pages(key, max(limit, 0))
            if not urls or (rest and not _known_song(conn, " ".join(rest), key, mine)):
                continue
            seen.add(key)
            for url in urls:
                hits.append(SiteHit(source, _title_words(key), url, 100.0, title_key=key,
                                    via="both" if rest else "title"))
        if len(hits) >= limit:
            break
    return hits[:max(limit, 0)]


def search_lacuerda(conn: sqlite3.Connection, query: str, *, songs: int = SITE_ROWS,
                    artists: int = ARTIST_ROWS) -> tuple[list[SiteArtist], list[SiteHit]]:
    """LaCuerda's artists and songs in its index that match ``query``, best first (``lacuerda_index.find``):
    an artist's songs that only their name matched are in their row, and beside an artist whose whole name
    is the query, one whose name is only near it ("Andrés Canalla" for "andres calamaro") is left out, as
    ``find_index`` leaves it out; one whose name holds the query's words among others stays ("Andrés
    Calamaro" beside "Andrés" for "andres"). It reads the table alone."""
    from caracole.lacuerda_index import find

    found = find(conn, query, artists=artists, songs=songs)
    whole = [a for a in found.artists if a.score >= 100]
    named = [a for a in found.artists if a.score >= 100 or a.part] if whole else found.artists
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
    "bunbury"), never one whose name puts other words between the query's ("Silvio Martinez Rodriguez" is no
    Silvio Rodríguez: ``_named_in_a_run``). Else none when LaCuerda has an artist whose whole name is among the
    query's words (their row, ``lacuerda_index.NAMED``, says it); else the artist of an Ultimate Guitar song read
    by both its names, however weakly, whose whole name starts or ends the query (``_named_at_an_end``: "Estopa"
    for "estopa como camaron", whose page may hold the title Ultimate Guitar lacks); else the query less a title
    an index knows at its end or its start (``_less_a_title``: "mana" for "mana rayando el sol"); else the query.
    With ``artist`` (``--artist NAME``) the query is the name. A name LaCuerda's listings give, under any of its
    spellings, is no page to read (``lacuerda_index.artist_slugs``: Ultimate Guitar's Los Enanitos Verdes are its
    Enanitos Verdes)."""
    from caracole.lacuerda_index import NAMED, artist_slugs, letters_text, unread_letter

    if any(h.score >= STRONG for h in lacuerda):
        return None
    name = query
    if not artist:
        strong = [h for h in songs if h.score >= STRONG]
        first = strong[0] if strong else None
        named = [a for a in artists if not a.part or _named_in_a_run(query, a.artist_key)]
        if named and (lead == "artist" or first is None or first.via != "title"):
            name = named[0].artist
        elif first is not None and first.via != "title" and first.artist and not no_ones(first.artist_key):
            name = first.artist
        elif first is not None and first.via == "title":
            return None
        elif any(isinstance(a, SiteArtist) and a.via == "both" and a.score >= NAMED for a in lacuerda):
            return None
        else:
            name = _named_at_an_end(query, songs) or _less_a_title(conn, query) or query
    if artist_slugs(conn, name):  # LaCuerda lists them: their row says it, under the name it writes
        return None
    letter = unread_letter(conn, name)
    return (name, letters_text([letter])) if letter is not None else None


def _named_in_a_run(query: str, artist_key: str) -> bool:
    """Whether the query's words are a run of an artist's name's words (Ultimate Guitar's key): "bunbury" of Enrique
    Bunbury, never "silvio rodriguez" of Silvio Martinez Rodriguez, whose name puts a word between them."""
    words, name = name_words(query), artist_key.split("-")
    return bool(words) and any(name[i:i + len(words)] == words for i in range(len(name) - len(words) + 1))


TITLE_WORDS = 2  # a title at a query's end that leaves the rest as its artist: two words at least, as one is no proof


def _less_a_title(conn: sqlite3.Connection, query: str) -> str | None:
    """The query less the longest run of its last (else first) words that is a title Ultimate Guitar's index or
    LaCuerda's knows exactly, of ``TITLE_WORDS`` words or more, one of four letters, and fewer than all: the
    words left, as typed, name the artist ("héroes del silencio" for "héroes del silencio entre dos tierras",
    "mana" for "mana rayando el sol"). None for none. "joaquin sabina" is no artist "joaquin" and a title
    "sabina": a title of one word is no proof. By the indexes' keys alone, no scan."""
    from caracole.lacuerda_index import title_key

    typed = query.split()
    for n in range(len(typed) - 1, TITLE_WORDS - 1, -1):
        for run, rest in ((typed[-n:], typed[:-n]), (typed[:n], typed[n:])):
            words = name_words(" ".join(run))
            if len(words) < TITLE_WORDS or not any(len(w) >= 4 for w in words) or not name_words(" ".join(rest)):
                continue
            text = " ".join(run)
            if conn.execute("SELECT 1 FROM ug_index WHERE song_key = ? LIMIT 1", (slug_key(text),)).fetchone() or \
                    conn.execute("SELECT 1 FROM lacuerda_index WHERE title_key = ? AND title != '' LIMIT 1",
                                 (title_key(text),)).fetchone():
                return " ".join(rest)
    return None


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
    """Whether LaCuerda's group comes before Ultimate Guitar's: the Ultimate Guitar index has no artist whose whole
    name (or a name near it) the query is and no strong song, and LaCuerda has an artist whose whole name the query
    is ("andres calamaro", where Ultimate Guitar has only Javier Calamaro's songs; "antonio josé", beside Ultimate
    Guitar's José Antonio Méndez, one song, named in part), or one a word names who is well known (``WELL_KNOWN``
    songs) and has more songs than any Ultimate Guitar artist the query names in part ("calamaro": Andrés Calamaro's
    325 before Javier Calamaro's 25; "paez": Fito Páez). An Ultimate Guitar artist named in part who leads and
    outweighs LaCuerda's whole name (``_outweighs``) keeps the lead ("dylan": Bob Dylan, not LaCuerda's Dylan). The
    lookup page's Enter then opens that artist's songs, which asks nothing."""
    if any(not a.part for a in ug.artists) or any(h.score >= STRONG for h in ug.songs):
        return False
    rival = max((a.songs for a in ug.artists), default=0)
    whole = next((a for a in lacuerda if a.score >= 100), None)
    if whole is not None:
        return not (ug.lead == "artist" and _outweighs(ug.artists[0].songs, whole.songs))
    return any(a.part and a.songs >= WELL_KNOWN and a.songs > rival for a in lacuerda[:1])


def _lacuerda_song(h: LaCuerdaHit) -> SiteHit:
    return SiteHit("lacuerda", h.title, h.url, h.score, h.artist, h.artist_key, h.title_key,
                   uploads=len(h.versions), via=h.via, sheet=h.sheet_url)


def _lacuerda_artist(conn: sqlite3.Connection, a: LaCuerdaHit) -> SiteArtist:
    # Their songs from their own page: those LaCuerda's search brought alone leave it to be read.
    known = conn.execute("SELECT COUNT(*) FROM lacuerda_index WHERE artist_slug = ? AND title != '' AND page = ?",
                         (a.artist_slug, f"{a.artist_slug}/")).fetchone()[0]
    return SiteArtist("lacuerda", a.artist, a.artist_slug, a.url, a.score, max(a.songs, known), known, a.via,
                      tuple(_lacuerda_song(t) for t in a.top), a.part)


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


# --- the names a request is filled in with ----------------------------------------------------------

ONE_WORD_ARTIST = 5  # a one-word name starting a query is its artist with this many songs in an index, or yours
_DASH = re.compile(r"\s+[-–—]\s+")  # "Artist - Title", as wanted.txt reads it
_BY = re.compile(r"\s+by\s+", re.IGNORECASE)  # "Title by Artist"


def request_names(conn: sqlite3.Connection, query: str, songs: Sequence[Song] = (), *,
                  names: Sequence[str] = ()) -> tuple[str, str] | None:
    """The artist and the title a search's query names, for the request form the pages fill in from it: "Artist -
    Title" (a dash with a space on each side, as wanted.txt reads it), whoever the artist; "Title by Artist", the
    words after its last " by " a known artist's whole name ("Que problema by Silvana Estrada"); else the longest
    run of its first words that is a known artist's whole name, the rest the title ("Silvana Estrada Que
    problema"). Known: an artist of your library (``songs``), of Ultimate Guitar's index or the artist pages
    caracole read, of LaCuerda's listings, or of gtptabs.com's or harptabs.com's index (``_known_artist``), or one of
    ``names``, any of one word or more: the channel of the YouTube video suggested for the query, which named the
    artist the owner typed in lower case ("Silvana Estrada", for "silvana estrada que problema"). Each as typed, its
    spaces folded, but an artist of yours as your library writes them, else one of ``names`` as it is written.

    None for a query that says nothing of it, which the pages fill in as the title (or as the artist, when an
    artist leads), to be edited: never a cut at the first space ("Silvana" and "Estrada"). So none for a query
    no known artist starts (or ends, after " by "), nor for a song's title whole, yours or an index's ("Love Me
    Tender" is no song "Me Tender" by Love); and a one-word name is a known artist only of yours or with
    ``ONE_WORD_ARTIST`` songs in an index ("Que problema" is no song "problema" by Que, an artist of one song on
    Ultimate Guitar). A name never ends with a word names leave out ("Joaquín Sabina y …": ``identity_key``)."""
    text = " ".join(query.split())
    dash = _DASH.search(text)
    if dash is not None and name_words(text[:dash.start()]) and name_words(text[dash.end():]):
        return text[:dash.start()], text[dash.end():]
    words = text.split()
    for by in reversed(list(_BY.finditer(text))):
        title, artist = text[:by.start()], text[by.end():]
        known = _known_artist(conn, artist, songs, names) if name_words(title) else None
        if known is not None:
            return (known, title) if not _known_title(conn, text, songs) else None
    for n in range(len(words) - 1, 0, -1):
        artist, title = " ".join(words[:n]), " ".join(words[n:])
        if n > 1 and identity_key(artist, "") == identity_key(" ".join(words[:n - 1]), ""):
            continue  # "Joaquín Sabina y nos dieron las diez": "y" ends no name
        known = _known_artist(conn, artist, songs, names) if name_words(title) else None
        if known is not None:
            return (known, title) if not _known_title(conn, text, songs) else None
    return None


def _known_artist(conn: sqlite3.Connection, name: str, songs: Sequence[Song],
                  names: Sequence[str] = ()) -> str | None:
    """The artist ``name`` is, as your library writes them (``library_by_artist``), else as one of ``names`` writes
    them, else as written; None for a name no index knows as an artist's whole name, or a one-word one with fewer
    than ``ONE_WORD_ARTIST`` songs in every index. No one's name ("misc", ``no_ones``) is none."""
    from caracole.lacuerda_index import name_key

    if placeholder_artist(name) or not name_words(name):
        return None
    wanted = {compact(f) for f in name_forms(name)} - {""}
    for song in library_by_artist(songs, name):
        for artist in dict.fromkeys(song.artists or [song.artist]):
            if wanted & {compact(f) for f in name_forms(artist)}:
                return artist
    for given in names:
        if not placeholder_artist(given) and wanted & {compact(f) for f in name_forms(given)}:
            return " ".join(given.split())
    forms = [f for f in name_forms(name) if f and not no_ones(f)]
    if not forms:
        return None
    least = ONE_WORD_ARTIST if len(name_words(name)) == 1 else 1
    marks = ", ".join("?" * len(forms))
    counts = [max(_song_counts(conn, forms).values(), default=0), gtptabs_songs(conn, name)]
    lc_keys = list(dict.fromkeys(k for k in (name_key(f) for f in [name, *forms]) if k))
    if lc_keys:  # LaCuerda's listings: an artist's row counts their songs
        counts.append(conn.execute(f"SELECT COALESCE(MAX(songs), 0) FROM lacuerda_index WHERE artist_key IN "
                                   f"({', '.join('?' * len(lc_keys))}) AND title = ''", lc_keys).fetchone()[0])
    # harptabs.com's artists, by their page's key: as many tabs as their page says once read, else one, a name
    counts.append(conn.execute(
        "SELECT COALESCE(MAX(COALESCE(a.tabs, 1)), 0) FROM harptabs_index i LEFT JOIN harptabs_artists a "
        f"ON a.path = i.path WHERE i.kind = 'artist' AND i.key IN ({marks}) AND (a.name IS NULL OR a.name != '')",
        forms).fetchone()[0])
    return " ".join(name.split()) if max(counts) >= least else None


def _known_title(conn: sqlite3.Connection, title: str, songs: Sequence[Song]) -> bool:
    """Whether ``title``, whole, is a song's title: yours, Ultimate Guitar's or LaCuerda's."""
    from caracole.lacuerda_index import title_key

    mine = identity_key("", title).partition("/")[2]
    if mine and any(s.key.partition("/")[2] == mine for s in songs):
        return True
    key = slug_key(title)
    if key and conn.execute("SELECT 1 FROM ug_index WHERE song_key = ? LIMIT 1", (key,)).fetchone():
        return True
    lc = title_key(title)
    return bool(lc and conn.execute("SELECT 1 FROM lacuerda_index WHERE title_key = ? AND title != '' LIMIT 1",
                                    (lc,)).fetchone())


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
    strong = _unseen(query, hits)
    if strong is None:
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
    if overrides is not None and overrides.has_table("artist_url"):
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


def _unseen(query: str, hits: Sequence[IndexHit | ArtistHit]) -> bool | None:
    """Whether the query may name an artist the index can't see (``bare_id_hint``): None when not, else whether
    something matched it strongly all the same."""
    strong = any(h.score >= STRONG for h in hits)
    if strong and not any(c.isalpha() and not c.isascii() for c in query):
        return None
    if any(h.score >= STRONG and h.page for h in hits):  # an artist page caracole read answers it: it sees them
        return None
    return strong


def bare_id_unseen(query: str, hits: Sequence[IndexHit | ArtistHit]) -> dict[str, object] | None:
    """``bare_id_hint``'s case as facts, for the pages' "Why can't caracole find it?", which word it themselves:
    ``strong`` (something matched well all the same), the ``[artist_url]`` lines to paste into overrides.toml for
    the query as the artist's name (``entry``), and the line that adds a song by its title (``add``). None when
    there is no hint. Like ``caracole serve``'s hint, it reads no overrides.toml."""
    strong = _unseen(query, hits)
    if strong is None:
        return None
    shown = " ".join(query.split())
    name = shown.replace("\\", "\\\\").replace('"', '\\"')
    return {"strong": strong, "entry": f'[artist_url]\n"{name}" = "{ARTIST_PAGE_SHAPE}"',
            "add": f"caracole add ARTIST {_shell(shown)}"}


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
                 reading: str | None = None) -> tuple[list[_Row], dict[str, _Named], dict[str, float]]:
    """Every song of the rows the prefilter reads scored against the query, best first (ties to more
    tabs, then to the artist with more of the rows), the artists the query names, and those it names in
    part (``_parts``), each with how much of their name the query is (none of either with ``reading``)."""
    patterns = _patterns(name_words(query))
    if not patterns:
        return [], {}, {}
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
    listed, listed_named, listed_forms = _listed_rows(conn, queries, patterns, reading)
    scored = _merged(scored, listed)
    for artist_key, n in listed_named.items():
        old = named.get(artist_key)
        named[artist_key] = n if old is None else _Named(max(old.score, n.score), max(old.top, n.top),
                                                         max(old.tabs, n.tabs))
    scored.sort(key=lambda s: (-s.score, -s.tabs, -s.artist_tabs, s.artist_key, s.base))
    parts = _parts(conn, query, tabs, listed_forms) if reading is None else {}
    return scored, named, parts


def _parts(conn: sqlite3.Connection, query: str, read: Iterable[str],
           listed: Mapping[str, Iterable[str]]) -> dict[str, float]:
    """The artists the query names in part: those whose name holds every word of the query as a word of its own,
    among others ("skynyrd" and "lynyrd" are Lynyrd Skynyrd's, "horse" Horse the Band's; never "beatle" in
    "beatles"), accents folded as the keys fold them, a Chinese word as its pinyin, a whole run of the name's words
    (伍佰 is ``wu-bai`` of ``wu-bai-china-blue``), as the rest of the search reads pinyin. Each with how much of the
    name the query is (its letters over the name's). A query in Latin letters finds them by the words of every
    artist key (``ug_artists_fts``, db.py), a Chinese one among the artists the prefilter read (``read``); both
    among the artist pages caracole read (``listed``: each artist's forms).

    Bounded, so that a word in many names fills no screen with them: a query needs a word of ``WORD_LETTERS``
    letters or more (or a Chinese word of four letters of pinyin), and the artists that hold its words must be
    ``WORD_ARTISTS`` or fewer. In the full index (148,705 artists) about seventy words are in more names than that,
    "the" (3,037), "band" (1,476), "of", "los", "john", "worship", "david", "black" among them: such a word alone
    names no one in part, while "young" (238 names), "horse" (44) or "skynyrd" (1) do."""
    words = name_words(query)
    latin = [w for w in words if not has_han(w)]
    runs = ["".join(fold(s) for s in romanize(t).split()) for t in words if has_han(t)]
    if not any(len(w) >= WORD_LETTERS for w in latin) and not any(len(r) >= 4 for r in runs):
        return {}
    if runs:
        keys = list(dict.fromkeys(read))
    else:
        keys = _artists_with_words(conn, latin)
        if keys is None:
            return {}
    names: dict[str, list[list[str]]] = {k: [k.split("-")] for k in keys}
    for k, forms in listed.items():
        names.setdefault(k, []).extend(f.split("-") for f in forms if f.isascii())
    letters = sum(len(w) for w in latin) + sum(len(r) for r in runs)
    found: dict[str, float] = {}
    for key, forms in names.items():
        if no_ones(key):
            continue
        shares = [letters / len("".join(name)) for name in forms
                  if all(w in name for w in latin) and all(holds_run(name, r) for r in runs)]
        if shares:  # every word of the name, in another order, too: a name the query isn't as it is written
            found[key] = max(shares)
    return found if len(found) <= WORD_ARTISTS else {}


def _artists_with_words(conn: sqlite3.Connection, words: Sequence[str]) -> list[str] | None:
    """The artist keys of the index that hold every one of ``words`` as a word, from the index of their words; None
    when more than ``WORD_ARTISTS`` do."""
    match = " AND ".join('"' + w.replace('"', '""') + '"' for w in words)
    keys = [r[0] for r in conn.execute(
        "SELECT artist_key FROM ug_artists WHERE id IN (SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?) "
        "LIMIT ?", (match, WORD_ARTISTS + 1))]
    return keys if len(keys) <= WORD_ARTISTS else None


def _listed_rows(conn: sqlite3.Connection, queries: list[_Query], patterns: list[str],
                 reading: str | None) -> tuple[list[_Row], dict[str, _Named], dict[str, set[str]]]:
    """The songs of the artist pages caracole read (ug/artist_tabs.py) whose names hold a pattern, scored as
    the index's are but on every form of UG's names (``normalize.name_forms``: "Song Dongye (宋冬野)" is
    宋冬野 and Song Dongye), their artists the query names (none with ``reading``), and each artist's forms."""
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
    forms: dict[str, set[str]] = {}
    for (artist_key, _), group in songs.items():
        forms.setdefault(artist_key, set()).update(f for t in group.values() for f in t.artist_forms)
    if reading is None:
        for artist_key, names_ in forms.items():
            if no_ones(artist_key):
                continue
            score = max((q.name(f.replace("-", " ")) for q in queries for f in _same_script(q, names_)), default=0.0)
            if score >= STRONG:
                named[artist_key] = _Named(score, top[artist_key], tabs[artist_key])
    return scored, named, forms


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
    """Each song of an artist with its tabs (a song's variants counted with it), most tabbed first: the index's,
    with the tabs only an artist page caracole read lists (ug/artist_tabs.py)."""
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
                yours: _Yours | None = None, *, part: bool = False) -> ArtistHit | None:
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
                     artist_page(conn, artist_key) or "", part)


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
