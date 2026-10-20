"""The local matching ladder: your songs against the UG index, offline (plan §2).

For each song, in order:

1. ``overrides.toml``: ``[ignore]``, then ``[pin]``, then ``[match]``.
2. For each of the song's artists, the UG artist keys it may go by: its
   ``[alias]`` first, then its own key, then any UG key that is the same once
   hyphens are removed (``ac-dc`` → ``acdc``). A Chinese name also tries its
   pinyin (宋冬野 → ``song-dong-ye``, which meets ``song-dongye`` the same way),
   and a name written in two scripts each of its parts (``normalize.name_forms``):
   UG's sitemaps write names in Latin letters only, so "打上花火 (Uchiage
   Hanabi)" meets ``uchiage-hanabi``. Under those artists an exact title
   accepts at once. Otherwise every title is scored with rapidfuzz ``ratio``,
   the best of UG's full key and its base key, so ``creep-acoustic`` and
   ``creep-intro`` count as ``creep``.
3. The nearest other artist key at or above ``artist_gate``, then step 2 under
   it, scored as the lower of the artist and title scores. A Chinese name's
   pinyin is compared with and without hyphens.
4. Names that aren't quite UG's, when steps 2 and 3 accept nothing. These are
   always reviews, never accepts, and join the candidates of a review:

   - ``word_title``: under the song's artists (steps 2 and 3), a title that
     holds yours word for word, or that yours holds ("Canción del Mariachi"
     in ``cancion-del-mariachi-morena-de-mi-corazon``). It scores 80 to 90,
     by how much of the longer title the shorter covers.
   - ``typo_artist``: for an artist none of whose names the index has, the
     artist keys an edit or so away (one for a name of four to seven letters,
     two from eight; two letters swapped count as one), so "Coldplya" meets
     ``coldplay``. Its titles are scored as in step 2, or as a ``word_title``.
   - ``catch_all``: UG's catch-all artists for shows (``SHOW_CATCH_ALLS``:
     ``misc-musicals``, ``misc-soundtrack``, ``misc-cartoons``,
     ``misc-television``, ``misc-computer-games``) file a song under a title
     that holds its show's name: "epic" - "I'm Not Sorry for Loving You" is
     ``misc-musicals/epic-the-musical-not-sorry-for-loving-you``. A catch-all
     title that holds one of the artist's names as whole words is scored by
     what is left of it (less the words such as "the musical" next to the
     name), as in step 2 or as a ``word_title``. A show's title that doesn't,
     but ends in your title of two words or more, scores 90: Spotify credits
     EPIC's songs to their composer, whose name UG's title doesn't hold.
     ``misc-originals`` and ``misc-unsigned-bands`` (``PERFORMER_CATCH_ALLS``)
     file "performer-title": there the name must start the title, and no
     ending counts. The other ``misc-…`` keys file the bare title, which
     step 5 finds; ``misc-mashups`` titles hold two songs, neither the one
     you want.

5. The title alone, across every artist (covers and misfiled tabs), for a song
   still not found: always reviews, ranked with step 4's. Here a Chinese
   title's pinyin must match exactly, hyphens aside: across every artist,
   short syllables fuzz-match unrelated titles. So must the parts of a title
   written in two scripts.

At every step, the UG songs you rejected for the song (``[reject]``, "none of
these" in ``caracole review``) are dropped, so they never come back; the others
still can. Decision: accept at ``accept`` or more with a lead of ``margin`` over
the next different title; review from ``review``; otherwise not found. A review
keeps five candidates, the best ``catch_all`` and the best ``typo_artist`` hit
among them (``KEPT_STEPS``) however many others score more: a show's song
credited to its singer ends a catch-all title at 90, behind the covers of its
title at 100. A review made only of steps 4 and 5 (``REVIEW_ONLY_STEPS``)
leaves the song to its artist's UG page as well (``ug.fetch.needs_artist_page``).

``match_all`` never replaces a match the fetch step made on a UG artist page
(step ``artist_page``, amendment A6): the index can't see those bare-id tabs,
so only your overrides can. Nor does an index that isn't complete (empty:
never built, or emptied; partial: a build stopped part-way) undo what the
ladder found before, or record a miss: it is no evidence that UG lacks a song.
"""

from __future__ import annotations

import bisect
import itertools
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz, process
from rapidfuzz.distance import OSA

from caracole.config import MatchPolicy
from caracole.db import savepoint
from caracole.normalize import (
    GENERIC_WORDS,
    clean_title,
    compact,
    has_han,
    name_forms,
    romanize,
    slug_key,
    split_variant,
)
from caracole.overrides import Overrides
from caracole.songs import Song, list_songs, refresh_status, update_song, utc_now_iso
from caracole.ug.index import index_state
from caracole.ug.lookup import artist_known
from caracole.versions import mark_stale

DECISIONS = ("accept", "review", "not_found", "pinned", "ignored")
TOLERANT_STEPS = ("word_title", "typo_artist", "catch_all")  # names that aren't quite UG's (step 4)
STEPS = ("override", "pin", "exact", "alias", "fuzzy_title", "fuzzy_artist", *TOLERANT_STEPS, "title_only")
LADDER_STEPS = ("exact", "alias", "fuzzy_title", "fuzzy_artist", *TOLERANT_STEPS, "title_only")  # the index's
# Steps that never accept: a review made only of these leaves the song to its artist's UG page too.
REVIEW_ONLY_STEPS = (*TOLERANT_STEPS, "title_only")
# Steps whose candidate is filed under another artist than the song's: choosing one makes no [alias].
NO_ALIAS_STEPS = ("catch_all", "title_only")
ARTIST_PAGE = "artist_page"  # the fetch step's matches on UG artist pages (A6)
CATCH_ALL_PREFIX = "misc-"  # misc-musicals, misc-soundtrack, misc-cartoons, misc-television…
NOT_CATCH_ALL = frozenset({"misc-mashups"})  # two songs in one title: neither is the one you want
# The catch-alls step 4 reads, by how they file a song. A show's holds the show's name, anywhere in
# the title: misc-musicals/epic-the-musical-not-sorry-for-loving-you, misc-cartoons/frozen-let-it-go.
SHOW_CATCH_ALLS = frozenset({"misc-musicals", "misc-soundtrack", "misc-cartoons", "misc-television",
                             "misc-computer-games"})
# A performer's starts with the performer's name: misc-originals/ray-porter-red-sarah.
PERFORMER_CATCH_ALLS = frozenset({"misc-originals", "misc-unsigned-bands"})
# The other misc-… keys (misc-praise-songs, misc-traditional, misc-christmas, misc-children) file the
# bare title, which step 5 finds.
CATCH_ALL_ENDING = 90.0  # a show's catch-all title that ends in yours: "hamilton-my-shot" for "My Shot"
MAX_CANDIDATES = 5
# A review keeps the best hit of each among its MAX_CANDIDATES, however many others score more.
KEPT_STEPS = ("catch_all", "typo_artist")
_TITLE_ONLY_TITLES = 10  # nearest titles expanded into candidates, per title form
_TYPO_ARTISTS = 5  # nearest artist keys within the typo distance, per name
# Words a catch-all title may put next to a show's name: "epic-the-musical-not-sorry-for-loving-you".
SHOW_WORDS = frozenset({
    "the", "musical", "soundtrack", "ost", "movie", "film", "show", "series", "tv", "theme", "from",
    "original", "cast", "broadway", "game", "anime", "opening", "ending",
})


def is_catch_all(artist_key: str) -> bool:
    """Whether UG files songs of many artists under this key, which is no one's name: every ``misc-…``
    key but ``misc-mashups``. Step 4 reads only ``SHOW_CATCH_ALLS`` and ``PERFORMER_CATCH_ALLS``."""
    return artist_key.startswith(CATCH_ALL_PREFIX) and artist_key not in NOT_CATCH_ALL


@dataclass(frozen=True)
class IndexTitle:
    """One title of an artist in the index: its base key, the song keys filed under it (``creep``,
    ``creep-acoustic``), and how many tabs they list."""

    base_key: str
    song_keys: tuple[str, ...]
    tabs: int


def _titles_of(rows: Iterable[tuple[str, int]]) -> list[IndexTitle]:
    """Group (song key, tabs) rows, sorted by song key, by base key, in the order each base first comes."""
    keys: dict[str, list[str]] = {}
    tabs: dict[str, int] = {}
    for song_key, n in rows:
        base = split_variant(song_key)[0]
        keys.setdefault(base, []).append(song_key)
        tabs[base] = tabs.get(base, 0) + n
    return [IndexTitle(base, tuple(k), tabs[base]) for base, k in keys.items()]


class IndexView:
    """``ug_index`` as the matcher reads it during one run.

    The artist keys (about 150,000) are loaded once, when a step first needs them
    all: steps 3 and 4 compare names with every one. Until then the index itself
    answers whether it has an artist and which artists read the same without
    hyphens, so matching a song whose artist UG has (``caracole add``, a lookup)
    never loads them. The title keys (about 720,000), which only title-only
    matching needs, are loaded once too, on first use. An artist's titles are read
    when a song first asks for that artist.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._artists: list[str] | None = None
        self._artist_set: frozenset[str] = frozenset()
        self._by_compact: dict[str, tuple[str, ...]] = {}
        self._compact_artists: list[str] | None = None
        self._titles_by_artist: dict[str, list[IndexTitle]] = {}
        self._tabs: dict[str, int] = {}
        self._titles: list[str] | None = None
        self._compact_titles: list[str] | None = None
        self._catch_all: list[tuple[str, str, int]] | None = None
        self._catch_all_text = ""  # each base key of catch_all_songs() as a line "-base-"
        self._catch_all_starts: list[int] = []  # where each line starts

    def artist_keys(self) -> list[str]:
        """Every artist key in the index, sorted."""
        if self._artists is None:
            self._artists = [r[0] for r in self.conn.execute(
                "SELECT DISTINCT artist_key FROM ug_index ORDER BY artist_key")]
            self._artist_set = frozenset(self._artists)
            by_compact: dict[str, list[str]] = {}
            for a in self._artists:
                by_compact.setdefault(compact(a), []).append(a)
            self._by_compact = {k: tuple(v) for k, v in by_compact.items()}
        return self._artists

    def has_artist(self, artist_key: str) -> bool:
        if self._artists is None:
            return artist_known(self.conn, artist_key)
        return artist_key in self._artist_set

    def compact_artists(self, compact_key: str) -> tuple[str, ...]:
        """The artist keys that read ``compact_key`` once hyphens are removed, sorted."""
        if not compact_key:
            return ()
        if self._artists is None:
            # A key never starts or ends with a hyphen, nor holds two in a row: one that reads
            # ``acdc`` starts with acd, ac-d, a-cd or a-c-d, a range of keys each. UNION, as SQLite
            # reads an OR of ranges as a full scan.
            head = compact_key[:3]
            starts = ["".join(c + sep for c, sep in zip(head, (*seps, ""), strict=True))
                      for seps in itertools.product(("", "-"), repeat=len(head) - 1)]
            sql = " UNION ".join(["SELECT DISTINCT artist_key FROM ug_index WHERE artist_key >= ? AND artist_key < ?"]
                                 * len(starts))
            rows = self.conn.execute(f"{sql} ORDER BY 1", [k for s in starts for k in (s, s + "\U0010ffff")])
            return tuple(r[0] for r in rows if compact(r[0]) == compact_key)
        return self._by_compact.get(compact_key, ())

    def compact_artist_keys(self) -> list[str]:
        """``artist_keys()`` with hyphens removed, in the same order."""
        if self._compact_artists is None:
            self._compact_artists = [compact(a) for a in self.artist_keys()]
        return self._compact_artists

    def artist_tabs(self, artist_key: str) -> int:
        """How many tabs the index lists under the artist."""
        n = self._tabs.get(artist_key)
        if n is None:
            row = self.conn.execute("SELECT COUNT(*) FROM ug_index WHERE artist_key = ?", (artist_key,)).fetchone()
            n = self._tabs[artist_key] = row[0]
        return n

    def titles_for_artist(self, artist_key: str) -> list[IndexTitle]:
        """The artist's titles, variant keys such as ``x-acoustic`` with their ``x``."""
        titles = self._titles_by_artist.get(artist_key)
        if titles is None:
            rows = self.conn.execute(
                "SELECT song_key, COUNT(*) FROM ug_index WHERE artist_key = ? GROUP BY song_key ORDER BY song_key",
                (artist_key,),
            )
            titles = self._titles_by_artist[artist_key] = _titles_of((r[0], r[1]) for r in rows)
        return titles

    def title_keys(self) -> list[str]:
        """Every title in the index as a base key (``creep-acoustic`` is ``creep``), sorted."""
        if self._titles is None:
            keys = self.conn.execute("SELECT DISTINCT song_key FROM ug_index")
            self._titles = sorted({split_variant(r[0])[0] for r in keys})
        return self._titles

    def compact_title_keys(self) -> list[str]:
        """``title_keys()`` with hyphens removed, in the same order."""
        if self._compact_titles is None:
            self._compact_titles = [compact(t) for t in self.title_keys()]
        return self._compact_titles

    def titles_reading(self, compact_key: str) -> list[str]:
        """The title keys that read ``compact_key`` once hyphens are removed."""
        return [t for t, c in zip(self.title_keys(), self.compact_title_keys(), strict=True) if c == compact_key]

    def artists_for_title(self, title_key: str) -> dict[str, int]:
        """Every artist key with a title whose base key is ``title_key``, with its tabs, by artist key."""
        # A range instead of LIKE, so the song_key index serves the variant keys too.
        rows = self.conn.execute(
            "SELECT artist_key, song_key, COUNT(*) FROM ug_index "
            "WHERE song_key = ? OR (song_key > ? AND song_key < ?) GROUP BY artist_key, song_key "
            "ORDER BY artist_key, song_key",
            (title_key, title_key + "-", title_key + "."),
        )
        tabs: dict[str, int] = {}
        for artist_key, song_key, n in rows:
            if split_variant(song_key)[0] == title_key:
                tabs[artist_key] = tabs.get(artist_key, 0) + n
        return tabs

    def catch_all_songs(self) -> list[tuple[str, str, int]]:
        """(artist key, base key, tabs) of every song of the catch-all artists step 4 reads
        (``SHOW_CATCH_ALLS``, ``PERFORMER_CATCH_ALLS``): about 90,000, variant keys such as
        ``x-acoustic`` counted with their song."""
        if self._catch_all is None:
            keys = sorted(SHOW_CATCH_ALLS | PERFORMER_CATCH_ALLS)
            marks = ", ".join("?" * len(keys))
            rows = self.conn.execute(
                f"SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE artist_key IN ({marks}) "
                "GROUP BY artist_key, song_key",
                keys,
            )
            tabs: dict[tuple[str, str], int] = {}
            for artist_key, song_key, n in rows:
                key = (artist_key, split_variant(song_key)[0])
                tabs[key] = tabs.get(key, 0) + n
            self._catch_all = sorted((a, s, n) for (a, s), n in tabs.items())
            lines = [f"-{s}-\n" for _, s, _ in self._catch_all]
            self._catch_all_text = "".join(lines)
            self._catch_all_starts = [0, *itertools.accumulate(map(len, lines))][:-1]
        return self._catch_all

    def catch_all_holding(self, needles: Iterable[str]) -> list[tuple[str, str, int]]:
        """The ``catch_all_songs()`` whose line ``-base-`` holds any of ``needles``, in the same order.
        A needle that ends in a newline holds the line's end: ``-my-shot-\\n`` is a title that ends in
        ``my-shot``. A search of one text per needle, instead of a test of each of 90,000 titles."""
        songs = self.catch_all_songs()
        text, starts = self._catch_all_text, self._catch_all_starts
        found: set[int] = set()
        for needle in needles:
            i = text.find(needle)
            while i != -1:
                found.add(bisect.bisect_right(starts, i) - 1)
                i = text.find(needle, i + 1)
        return [songs[i] for i in sorted(found)]

    def tab_keys(self, tab_id: int) -> tuple[str, str] | None:
        """The (artist key, song key) a tab is indexed under, if it is indexed."""
        row = self.conn.execute("SELECT artist_key, song_key FROM ug_index WHERE tab_id = ?", (tab_id,)).fetchone()
        return (row[0], row[1]) if row else None


@dataclass(frozen=True)
class MatchCandidate:
    artist_key: str
    song_key: str
    score: float | None
    step: str


@dataclass(frozen=True)
class MatchResult:
    """A song's match: ``decision`` is one of DECISIONS and ``step`` one of STEPS (None when not found).

    ``artist_key``/``song_key`` are the UG song (for a review, the best
    candidate). ``pinned`` holds the tab ids of a ``[pin]``.
    """

    decision: str
    step: str | None
    score: float | None
    artist_key: str | None
    song_key: str | None
    candidates: tuple[MatchCandidate, ...] = ()
    pinned: tuple[int, ...] = ()


@dataclass(frozen=True)
class MatchChange:
    """One song in a ``match_all`` run: the song as it was, its previous decision, and its match now."""

    song: Song
    old: str | None
    new: MatchResult


# --- the ladder -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Hit:
    cand: MatchCandidate
    rank: int  # the order its artist key was tried in
    tabs: int


@dataclass(frozen=True)
class _Forms:
    """A name or title as keys: its own key, its pinyin key when it has Chinese characters, and its
    other forms (``normalize.name_forms``), such as each part of a name written in two scripts."""

    own: tuple[str, ...]
    pinyin: tuple[str, ...] = ()
    parts: tuple[str, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        return self.own + self.pinyin + self.parts


def _forms(text: str) -> _Forms:
    own = slug_key(text)
    pinyin = slug_key(romanize(text)) if has_han(text) else ""
    parts = tuple(f for f in name_forms(text) if f not in (own, pinyin))
    return _Forms(tuple(k for k in (own,) if k), tuple(k for k in (pinyin,) if k and k != own), parts)


# Spanish leading articles are part of some UG artist slugs and not of the source's name, or the
# other way round: UG files Enanitos Verdes as los-enanitos-verdes.
_ARTICLES = ("los", "las", "el", "la")


def _article_forms(key: str) -> list[str]:
    """The same artist key with a leading Spanish article removed, or with each one added."""
    head, sep, rest = key.partition("-")
    if sep and rest and head in _ARTICLES:
        return [rest]
    return [f"{a}-{key}" for a in _ARTICLES]


def _own_artists(song: Song, index: IndexView, overrides: Overrides) -> list[tuple[str, bool]]:
    """(UG artist key, came from [alias]) for each of the song's artists, in the order they're tried."""
    keys: dict[str, bool] = {}

    def add(key: str, alias: bool = False) -> None:
        if key and key not in keys and index.has_artist(key):
            keys[key] = alias

    for name in song.artists or [song.artist]:
        for a in overrides.alias.get(slug_key(name), ()):
            add(a, alias=True)
        forms = _forms(name).keys
        for form in forms:
            add(form)
            for a in index.compact_artists(compact(form)):
                add(a)
        for form in forms:
            for alt in _article_forms(form):
                add(alt)
    return list(keys.items())


def _title_hits(index: IndexView, artist_key: str, title: _Forms, rank: int, *, exact_step: str,
                fuzzy_step: str = "fuzzy_title", cap: float | None = None) -> list[_Hit]:
    """Score every title of one artist, grouped by base key."""
    compact_pinyin = [compact(p) for p in title.pinyin]
    hits = []
    for t in index.titles_for_artist(artist_key):
        base, keys = t.base_key, {t.base_key, *t.song_keys}
        if any(k in keys or compact(k) == compact(base) for k in title.keys):
            score, step = 100.0, exact_step
        else:
            score = max(fuzz.ratio(k, u) for k in title.keys for u in keys)
            score = max([score, *(fuzz.ratio(c, compact(base)) for c in compact_pinyin)])
            step = fuzzy_step
        if cap is not None:
            score = min(score, cap)
        hits.append(_Hit(MatchCandidate(artist_key, base, round(score, 1), step), rank, t.tabs))
    return hits


def _ranked(hits: Iterable[_Hit]) -> list[_Hit]:
    """Best first (score, then the artist tried first, then the most tabs), one hit per UG song."""
    best: dict[tuple[str, str], _Hit] = {}
    for h in sorted(hits, key=lambda h: (-h.cand.score, h.rank, -h.tabs)):
        best.setdefault((h.cand.artist_key, h.cand.song_key), h)
    return list(best.values())


def _decide(hits: list[_Hit], policy: MatchPolicy) -> str:
    if not hits:
        return "not_found"
    best = hits[0].cand
    rival = next((h.cand.score for h in hits[1:] if h.cand.song_key != best.song_key), 0.0)
    if best.score >= policy.accept and best.score - rival >= policy.margin:
        return "accept"
    return "review" if best.score >= policy.review else "not_found"


def _nearest_artists(song: Song, index: IndexView, tried: set[str], gate: float) -> list[tuple[str, float]]:
    """For each of the song's artists, the closest artist key not tried yet, if it scores ``gate`` or more.

    A Chinese name's pinyin is also compared without hyphens (``songdongye``
    against every artist key read that way).
    """
    artists = index.artist_keys()
    found: dict[str, float] = {}
    for name in song.artists or [song.artist]:
        forms = _forms(name)
        queries = [(f, artists) for f in forms.keys]
        queries += [(compact(p), index.compact_artist_keys()) for p in forms.pinyin]
        best: tuple[str, float] | None = None
        for query, choices in queries:
            skip = tried | found.keys()
            # At most len(skip) of these are skipped, so one is left whenever any artist passes the gate.
            near = process.extract(query, choices, scorer=fuzz.ratio, score_cutoff=gate, limit=len(skip) + 1)
            key, score = next(((artists[i], s) for _, s, i in near if artists[i] not in skip), (None, 0.0))
            if key is not None and (best is None or score > best[1]):
                best = (key, score)
        if best is not None:
            found[best[0]] = round(best[1], 1)
    return list(found.items())


def _title_only(index: IndexView, title: _Forms, policy: MatchPolicy, rank: int = 0) -> list[_Hit]:
    """Step 5; ``rank`` puts its hits behind every other step's of the same score."""
    titles = index.title_keys()
    scores: dict[str, float] = {}
    for query in title.own:
        for _, score, i in process.extract(query, titles, scorer=fuzz.ratio, score_cutoff=policy.review,
                                           limit=_TITLE_ONLY_TITLES):
            scores[titles[i]] = max(scores.get(titles[i], 0.0), score)
    # Across every artist, pinyin counts only when it matches exactly (hyphens aside): short
    # syllables fuzz-match unrelated titles ("banmabanma" scores 80 against "banaobanao"). So do the
    # parts of a title written in two scripts, whose romanizations are just as short.
    for query in title.pinyin + title.parts:
        for key in index.titles_reading(compact(query)):
            scores[key] = 100.0
    hits = []
    for key, score in scores.items():
        hits += [_Hit(MatchCandidate(a, key, round(score, 1), "title_only"), rank, n)
                 for a, n in index.artists_for_title(key).items()]
    return _ranked(hits)


# --- names that aren't quite UG's (step 4) --------------------------------------------------


def _find(words: list[str], part: list[str]) -> int | None:
    """Where ``part`` first runs, whole words in order, inside ``words``."""
    n = len(part)
    return next((i for i in range(len(words) - n + 1) if words[i:i + n] == part), None)


def _names_something(words: list[str]) -> bool:
    """Whether words could name a song or an artist on their own (as ``normalize.name_forms`` judges a
    part): three letters or more besides ``GENERIC_WORDS`` and numbers, or any Chinese."""
    kept = [w for w in words if w not in GENERIC_WORDS and not w.isdigit()]
    return any(has_han(w) for w in kept) or sum(len(w) for w in kept) >= 3


def _coverage(short: list[str], long: list[str]) -> float:
    return len("".join(short)) / len("".join(long))


def _word_score(a: str, b: str) -> float:
    """80 to 90 when one key's words run inside the other's, by how much of the longer the shorter
    covers; else 0. The shorter must name something on its own: "live" in ``live-forever`` doesn't."""
    short, long = sorted((a.split("-"), b.split("-")), key=len)
    if len(short) == len(long) or not _names_something(short) or _find(long, short) is None:
        return 0.0
    return 80 + 10 * _coverage(short, long)


def _title_score(title: _Forms, key: str) -> float:
    """A title against one UG title key, as step 2 scores it, or as a ``word_title``."""
    if any(k == key or compact(k) == compact(key) for k in title.keys):
        return 100.0
    return max(max(fuzz.ratio(k, key), _word_score(k, key)) for k in title.keys)


def _word_hits(index: IndexView, artist_key: str, title: _Forms, rank: int, *, step: str,
               cap: float | None = None) -> list[_Hit]:
    """The artist's titles that hold yours word for word, or that yours holds."""
    hits = []
    for t in index.titles_for_artist(artist_key):
        score = max(_word_score(k, u) for k in title.keys for u in {t.base_key, *t.song_keys})
        if score:
            score = score if cap is None else min(score, cap)
            hits.append(_Hit(MatchCandidate(artist_key, t.base_key, round(score, 1), step), rank, t.tabs))
    return hits


def _typo_artists(song: Song, index: IndexView, tried: set[str]) -> list[str]:
    """The artist keys an edit or so from one of the song's names; two letters swapped count as one.

    One edit for a name of four to seven letters, two from eight; names are compared without hyphens.
    Only Latin names: a romanization's syllables are too short to tell a typo from another name.
    Nearest first, then the most tabs: "Tolo" has five neighbours an edit away, and the one it
    misspells is ``tool``, last of them in the alphabet and first by its tabs.
    """
    artists, compacts = index.artist_keys(), index.compact_artist_keys()
    found: dict[str, None] = {}
    for name in song.artists or [song.artist]:
        forms = _forms(name)
        for form in dict.fromkeys(f for f in forms.own + forms.parts if f.isascii()):
            query = compact(form)
            if len(query) < 4:
                continue
            edits = 1 if len(query) < 8 else 2
            # Every neighbour (few, an edit or two away), not the first in the alphabet.
            near = process.extract(query, compacts, scorer=OSA.distance, score_cutoff=edits, limit=None)
            keys = [(d, artists[i]) for _, d, i in near if artists[i] not in tried and artists[i] not in found]
            keys.sort(key=lambda dk: (dk[0], -index.artist_tabs(dk[1]), dk[1]))
            found.update((key, None) for _, key in keys[:_TYPO_ARTISTS])
    return list(found)


def _rests(words: list[str], name: list[str]) -> list[list[str]]:
    """What a catch-all title holds besides the name, wherever the name runs in it: the words after it,
    before it, or both, each also without the words next to the name that only say what the name is
    (``SHOW_WORDS``: "the musical", "from", "soundtrack")."""
    i = _find(words, name)
    if i is None:
        return []
    before, after = words[:i], words[i + len(name):]
    bare_before = list(before)
    while bare_before and bare_before[-1] in SHOW_WORDS:
        bare_before.pop()
    bare_after = list(after)
    while bare_after and bare_after[0] in SHOW_WORDS:
        bare_after.pop(0)
    parts = [after, bare_after, before, bare_before]
    if before and after:
        parts += [before + after, bare_before + bare_after]
    return [p for p in parts if p]


def _catch_all_hits(song: Song, index: IndexView, title: _Forms, rank: int) -> list[_Hit]:
    """The songs of UG's catch-all artists whose titles name the song's artist and hold its title.

    A title that holds one of the artist's names as whole words scores what is left of it as step 2
    does, or as a ``word_title``; under a performer's catch-all (``PERFORMER_CATCH_ALLS``) the name
    must start the title. A show's title (``SHOW_CATCH_ALLS``) that doesn't hold it, but ends in a
    title of two words or more that names something, scores ``CATCH_ALL_ENDING``: what comes before
    is the show's name, which tells nothing against you, so it leads near titles of other artists,
    and stays behind exact ones.
    """
    names = [n for a in (song.artists or [song.artist]) for n in _forms(a).keys if _names_something(n.split("-"))]
    endings = [k for k in title.own if k.count("-") >= 1 and _names_something(k.split("-"))]
    hits = []
    # Only a title that holds a name, or ends in an ending, can score.
    for artist_key, base, tabs in index.catch_all_holding([*(f"-{n}-" for n in names),
                                                           *(f"-{e}-\n" for e in endings)]):
        padded = f"-{base}-"
        if artist_key in PERFORMER_CATCH_ALLS:  # "performer-title": a name elsewhere is a word of the title
            held = [n for n in names if padded.startswith(f"-{n}-")]
        else:
            held = [n for n in names if f"-{n}-" in padded]
        if held:
            words = base.split("-")
            rests = [r for n in held for r in _rests(words, n.split("-"))]
            score = max((_title_score(title, "-".join(r)) for r in rests), default=0.0)
        elif artist_key in SHOW_CATCH_ALLS:
            score = CATCH_ALL_ENDING if any(padded.endswith(f"-{e}-") and e != base for e in endings) else 0.0
        else:
            score = 0.0
        if score:
            hits.append(_Hit(MatchCandidate(artist_key, base, round(score, 1), "catch_all"), rank, tabs))
    return hits


def _tolerant_hits(song: Song, index: IndexView, title: _Forms, routes: list[tuple[str, float | None]],
                   own: bool, policy: MatchPolicy) -> list[_Hit]:
    """Step 4: the ``word_title``, ``typo_artist`` and ``catch_all`` hits that reach ``review``.

    ``routes`` are the artist keys steps 2 and 3 tried, in order, each with the score its titles are
    capped at (None for the song's own); ``own`` says whether any of them is the song's own.
    """
    hits = []
    for rank, (artist_key, cap) in enumerate(routes):
        hits += _word_hits(index, artist_key, title, rank, step="word_title", cap=cap)
    rank = len(routes)
    if not own:
        for artist_key in _typo_artists(song, index, {a for a, _ in routes}):
            hits += _title_hits(index, artist_key, title, rank, exact_step="typo_artist", fuzzy_step="typo_artist")
            hits += _word_hits(index, artist_key, title, rank, step="typo_artist")
            rank += 1
    hits += _catch_all_hits(song, index, title, rank)
    return [h for h in hits if h.cand.score >= policy.review]


def _allowed(hits: Iterable[_Hit], rejected: frozenset[tuple[str, str]]) -> list[_Hit]:
    """The hits that aren't UG songs you rejected for the song."""
    return [h for h in hits if (h.cand.artist_key, h.cand.song_key) not in rejected]


def _keeping_near_names(hits: list[_Hit]) -> list[_Hit]:
    """``hits`` with the best of each of ``KEPT_STEPS`` (score, then tabs) among the first
    ``MAX_CANDIDATES``, in place of the last of the others there; the rest keep their order.

    A show's song credited to its singer ends a catch-all title (``CATCH_ALL_ENDING``), behind the
    covers of its title (100): cut off with them, it would never be offered, and rejecting five
    covers would only bring five more.
    """
    top = hits[:MAX_CANDIDATES]
    kept = [best for step in KEPT_STEPS if (best := min(
        (h for h in hits if h.cand.step == step), key=lambda h: (-h.cand.score, -h.tabs, h.rank), default=None))]
    missing = [h for h in kept if h not in top]
    if not missing:
        return hits
    dropped = [h for h in top if h not in kept][-len(missing):]
    top = [h for h in top if h not in dropped] + missing
    return top + [h for h in hits if h not in top]


def _review(hits: list[_Hit]) -> MatchResult:
    return _result("review", _keeping_near_names(_ranked(hits)))


def _result(decision: str, hits: list[_Hit]) -> MatchResult:
    best = hits[0].cand
    return MatchResult(decision, best.step, best.score, best.artist_key, best.song_key,
                       candidates=tuple(h.cand for h in hits[:MAX_CANDIDATES]))


def _pinned_keys(index: IndexView, pins: tuple[int, ...]) -> tuple[str | None, str | None]:
    for tab_id in pins:
        keys = index.tab_keys(tab_id)
        if keys is not None:
            return keys[0], split_variant(keys[1])[0]
    return None, None


def match_song(song: Song, index: IndexView, overrides: Overrides, policy: MatchPolicy) -> MatchResult:
    """Run the ladder for one song."""
    ident = song.key
    if ident in overrides.ignore:
        return MatchResult("ignored", "override", None, None, None)
    if ident in overrides.pin:
        pins = tuple(overrides.pin[ident])
        artist_key, song_key = overrides.match.get(ident) or _pinned_keys(index, pins)
        return MatchResult("pinned", "pin", None, artist_key, song_key, pinned=pins)
    if ident in overrides.match:
        artist_key, song_key = overrides.match[ident]
        return MatchResult("accept", "override", 100.0, artist_key, song_key,
                           candidates=(MatchCandidate(artist_key, song_key, 100.0, "override"),))

    title = _forms(clean_title(song.title))
    if not title.keys:
        return MatchResult("not_found", None, None, None, None)
    rejected = overrides.reject.get(ident, frozenset())
    own = _own_artists(song, index, overrides)
    hits: list[_Hit] = []
    for rank, (artist_key, via_alias) in enumerate(own):
        step = "alias" if via_alias else "exact"
        hits += _allowed(_title_hits(index, artist_key, title, rank, exact_step=step), rejected)
    ranked = _ranked(hits)
    exact = next((h for h in ranked if h.cand.step in ("exact", "alias")), None)
    if exact is not None:
        return _result("accept", [exact, *(h for h in ranked if h is not exact)])

    decision = _decide(ranked, policy)
    if decision == "accept":
        return _result(decision, ranked)
    routes: list[tuple[str, float | None]] = [(a, None) for a, _ in own]
    for i, (artist_key, score) in enumerate(_nearest_artists(song, index, set(dict(routes)), policy.artist_gate)):
        hits += _allowed(_title_hits(index, artist_key, title, len(own) + i, exact_step="fuzzy_artist",
                                     fuzzy_step="fuzzy_artist", cap=score), rejected)
        routes.append((artist_key, score))
    ranked = _ranked(hits)
    decision = _decide(ranked, policy)
    if decision == "accept":
        return _result(decision, ranked)

    # Names that aren't quite UG's: never an accept.
    tolerant = _allowed(_tolerant_hits(song, index, title, routes, bool(own), policy), rejected)
    if decision == "review":
        return _review(hits + tolerant)
    behind = max((h.rank for h in tolerant), default=len(routes)) + 1
    found = tolerant + _allowed(_title_only(index, title, policy, behind), rejected)
    if found:
        return _review(found)
    return MatchResult("not_found", None, ranked[0].cand.score if ranked else None, None, None,
                       candidates=tuple(h.cand for h in ranked[:MAX_CANDIDATES]))


# --- match_all ------------------------------------------------------------------------------


def _candidate_rows(result: MatchResult) -> list[dict[str, Any]]:
    """``songs.match_candidates``. A pin is one row that also lists its tabs, so a changed pin is noticed."""
    if result.decision == "pinned":
        return [{"artist_key": result.artist_key, "song_key": result.song_key, "score": None, "step": "pin",
                 "tab_ids": list(result.pinned)}]
    return [{"artist_key": c.artist_key, "song_key": c.song_key, "score": c.score, "step": c.step}
            for c in result.candidates[:MAX_CANDIDATES]]


def _pins_of(song: Song) -> list[int]:
    pin = next((c for c in song.match_candidates or [] if c.get("step") == "pin"), {})
    return [int(t) for t in pin.get("tab_ids", [])]


def _needs_fetch(song: Song, new: MatchResult) -> bool:
    """Whether the song's UG versions must be fetched again: a new accept or pin, other keys, other pins."""
    if new.decision in ("accept", "pinned") and song.match_decision != new.decision:
        return True
    if (song.match_artist_key, song.match_song_key) != (new.artist_key, new.song_key):
        return True
    return new.decision == "pinned" and _pins_of(song) != list(new.pinned)


def _keeps_stored(song: Song, new: MatchResult, rejected: frozenset[tuple[str, str]], *,
                  complete: bool) -> bool:
    """Whether a song keeps its stored match instead of ``new``.

    Your overrides always win. Otherwise a match the fetch step made on a UG
    artist page stays (A6), unless you rejected that UG song for it. While the
    index isn't complete, so does what the ladder found before, and a song it
    misses now keeps what it had (a song never matched stays unmatched); only an
    override you took out still comes off.
    """
    if new.step in ("override", "pin"):
        return False
    if song.match_step == ARTIST_PAGE:
        return (song.match_artist_key, song.match_song_key) not in rejected
    if complete:
        return False
    return song.match_step in LADDER_STEPS or (song.match_step is None and new.decision == "not_found")


def _stored(song: Song) -> MatchResult:
    cands = tuple(
        MatchCandidate(c["artist_key"], c["song_key"], c.get("score"), c.get("step"))
        for c in song.match_candidates or [] if c.get("artist_key") and c.get("song_key")
    )
    return MatchResult(song.match_decision or "not_found", song.match_step, song.match_score,
                       song.match_artist_key, song.match_song_key, candidates=cands)


def _save(conn: sqlite3.Connection, song: Song, new: MatchResult, now: str) -> None:
    values: dict[str, Any] = {
        "match_decision": new.decision,
        "match_step": new.step,
        "match_score": new.score,
        "match_artist_key": new.artist_key,
        "match_song_key": new.song_key,
        "match_candidates": _candidate_rows(new),
        "review": new.decision == "review",
    }
    if any(getattr(song, name) != value for name, value in values.items()):
        if _needs_fetch(song, new):
            values["ug_dirty"] = True
            # The UG versions found so far are the old match's: none competes, or stays a pick,
            # until the new match's pages (from the cache, mostly) list it again.
            mark_stale(conn, song.id, "ug")
        update_song(conn, song.id, **values, matched_at=now)
    if new.decision == "ignored" and song.status != "ignored":
        update_song(conn, song.id, status="ignored")
    elif new.decision != "ignored" and song.status == "ignored":
        refresh_status(conn, song.id, ignored=False)


def match_all(conn: sqlite3.Connection, overrides: Overrides, policy: MatchPolicy, *,
              dry_run: bool = False, song_ids: Collection[int] | None = None,
              songs: Iterable[Song] | None = None) -> list[MatchChange]:
    """Match every song, newest first, and store the results (unless ``dry_run``). With
    ``song_ids``, only those songs: ``caracole add`` matches the song it adds.

    Stores the decision, step, score, matched keys, up to five candidates
    (dicts with ``artist_key``, ``song_key``, ``score`` and ``step``, best
    first; a pin's one row also lists its ``tab_ids``), ``matched_at`` and the
    review flag, for songs whose match changed. Sets ``ug_dirty`` when a song
    becomes accepted or pinned, or its keys or pins change, and then marks the
    UG versions found under the old match stale (``versions.mark_stale``), so
    they leave every slot until the new match lists them. Ignored songs get
    status ``ignored``; songs no longer ignored get their status back.

    A song matched on a UG artist page (A6) keeps that match unless an
    override applies or ``[reject]`` names it. While the index is empty or
    partial (``index_state``) so does any song the ladder matched before, and a
    miss is never saved: a song never matched stays unmatched (only an override
    you took out comes off). Returns one change per song; a kept song's ``new``
    is its stored match (not found, for one never matched). ``songs``: these
    alone, as a lookup (``caracole get``) matches its one song.
    """
    index = IndexView(conn)
    complete = index_state(conn) == "complete"
    changes, kept = [], set()
    for song in list_songs(conn) if songs is None else songs:
        if song_ids is not None and song.id not in song_ids:
            continue
        new = match_song(song, index, overrides, policy)
        if _keeps_stored(song, new, overrides.reject.get(song.key, frozenset()), complete=complete):
            new = _stored(song)
            kept.add(song.id)
        changes.append(MatchChange(song, song.match_decision, new))
    if not dry_run:
        now = utc_now_iso()
        with savepoint(conn, "match_all"):
            for c in changes:
                if c.song.id not in kept:
                    _save(conn, c.song, c.new, now)
    return changes
