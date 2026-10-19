"""Offline search: your library, and the local Ultimate Guitar index (amendment A7).

``tabarr search`` never touches the network. It looks in two places:

- **Your library** (``search_library``): every song, whatever its status,
  scored against its artists and its title.
- **The UG index** (``search_index``): the ``ug_index`` table built from UG's
  sitemaps, about 1.6 million rows. A SQL ``LIKE`` prefilter keeps the
  candidates to a few thousand, and rapidfuzz ranks them. One pattern costs
  about 0.1 s per column over 1.6M rows, so the prefilter uses at most two:
  the query's two longest words (a typo in one of them still finds the song),
  or, for names made of initials, the hyphenated and the compact key
  (UG writes R.E.M. as ``r-e-m`` but AC/DC as ``acdc``). Variant slugs such as
  ``creep-acoustic`` are grouped under their song.

Both sides are compared as words made the way slug keys are made (accents
folded, apostrophes, "and" and a leading "the" dropped), and Chinese is also
compared as pinyin: "宋冬野" meets UG's ``song-dongye``, and "ban ma" finds
斑马，斑马. A Chinese word's syllables are matched in order with ``%``
between them, so ``song-dongye``, ``songdongye`` and ``song-dong-ye`` all match.

UG's sitemaps list artists with accented or non-Latin names only by bare ids,
so the index can't see their tabs; ``bare_id_hint`` says what to do then.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from rapidfuzz import fuzz

from tabarr.normalize import clean_title, fold, has_han, romanize, split_variant
from tabarr.songs import Song, list_songs
from tabarr.ug.lookup import IndexTab, song_tabs

MIN_SCORE = 70  # below this a hit is noise
STRONG = 90  # a hit this good is the song you meant
PARTIAL_SCALE = 0.9  # a query that is only part of a name tops out at 90
TYPE_ORDER = ("chords", "tabs", "guitar-pro", "power")
MAX_PATTERNS = 2

_WORD_SPLIT = re.compile(r"[\W_]+")
_APOSTROPHES = re.compile(r"['’‘`´ʼ]")


@dataclass(frozen=True)
class LibraryHit:
    """A song of yours that matches the query; ``score`` is 0–100."""

    song: Song
    score: float


@dataclass(frozen=True)
class IndexHit:
    """A song in the offline UG index.

    ``song_key`` is the song's base key: its variant slugs (``-acoustic``,
    ``-intro``…) are counted with it, and their labels are in ``labels``.
    ``counts`` gives the tabs per type, best type first. ``url`` is a sample
    tab page. ``artist`` and ``title`` are made from UG's own slugs, which keep
    a leading "the" and an "and" that the keys drop, to show and to paste into
    ``tabarr add``.
    """

    artist_key: str
    song_key: str
    counts: Mapping[str, int]
    score: float
    url: str
    labels: tuple[str, ...] = ()
    artist: str = ""
    title: str = ""


def display_from_keys(artist_key: str, song_key: str) -> tuple[str, str]:
    """An artist and a title made from UG keys or slugs: each word capitalized.

    ``("soda-stereo", "de-musica-ligera")`` gives ``("Soda Stereo", "De Musica Ligera")``.
    Only a word's first letter changes, so "3am" stays "3am".
    """
    return _title_words(artist_key), _title_words(song_key)


def search_library(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[LibraryHit]:
    """Your songs that match ``query``, best first, whatever their status."""
    queries = [_Query(form) for form in _forms(query)]
    if not queries:
        return []
    hits = []
    for song in list_songs(conn):
        score = _song_score(queries, song)
        if score >= MIN_SCORE:
            hits.append(LibraryHit(song, round(score, 1)))
    hits.sort(key=lambda h: (-h.score, h.song.display.casefold(), h.song.id))
    return hits[:limit]


def search_index(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[IndexHit]:
    """Songs in the offline UG index that match ``query``, best first.

    Ties go to the song with more tabs, which is usually the one you mean
    ("creep" is Radiohead's before Stone Temple Pilots').
    """
    tokens = _tokens(query)
    patterns = _patterns(tokens)
    if not patterns:
        return []
    queries = [_Query(form) for form in _forms(query)]
    where = " OR ".join(
        f"artist_key LIKE ?{i} OR song_key LIKE ?{i}" for i in range(1, len(patterns) + 1)
    )
    rows = conn.execute(
        f"SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE {where} GROUP BY artist_key, song_key",
        patterns,
    )
    groups: dict[tuple[str, str], int] = {}
    for artist_key, song_key, n in rows:
        key = (artist_key, split_variant(song_key)[0])
        groups[key] = groups.get(key, 0) + n

    scored = []
    for (artist_key, base), n in groups.items():
        artist, title = artist_key.replace("-", " "), base.replace("-", " ")
        score = max(q.score(artist, title) for q in queries)
        if score >= MIN_SCORE:
            scored.append((score, n, artist_key, base))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2], s[3]))

    hits = []
    for score, _, artist_key, base in scored[:limit]:
        hit = _index_hit(conn, artist_key, base, score)
        if hit is not None:
            hits.append(hit)
    return hits


def bare_id_hint(query: str, hits: Sequence[IndexHit], *, artist: str | None = None) -> str | None:
    """What to do when the index can't see an artist, or None when the search went fine.

    Artists with accents or non-Latin letters in their names (Joaquín Sabina,
    Maná, 宋冬野) have no slugged rows in UG's sitemaps. The hint names the
    ``[artist_url]`` override, with a line to paste for ``artist`` (by default
    the query itself). It's given when nothing matches well, and, more briefly,
    for a query with such letters even when something does.
    """
    strong = any(h.score >= STRONG for h in hits)
    if strong and not any(c.isalpha() and not c.isascii() for c in query):
        return None
    name = (artist or " ".join(query.split())).replace("\\", "\\\\").replace('"', '\\"')
    line = f'"{name}" = "https://www.ultimate-guitar.com/artist/<name>_<id>"'
    if strong:
        return (
            "UG's sitemaps list artists with accented or non-Latin names only by bare ids. If the "
            "one you want isn't above, find their page on ultimate-guitar.com and paste its address "
            f"into overrides.toml:\n\n    [artist_url]\n    {line}"
        )
    return (
        "Nothing in the offline index matches well. UG's sitemaps list some artists only by bare "
        "ids, usually because of accents or non-Latin letters (Joaquín Sabina, Maná, 宋冬野), so "
        "tabarr can't see their tabs. Find the artist's page on ultimate-guitar.com once and paste "
        f"its address into overrides.toml:\n\n    [artist_url]\n    {line}\n\n"
        "Then add the song with `tabarr add`; the nightly run looks for its tabs on that page."
    )


# --- words, pinyin and scores -----------------------------------------------------------


def _tokens(text: str) -> list[str]:
    """The words of a name, as ``normalize.slug_key`` makes them, but with CJK runs kept apart.

    Accents are folded, apostrophes dropped, "and" removed and a leading "the"
    dropped, so the words meet UG's canonical keys one for one. Unlike
    ``slug_key``, "宋冬野 斑马" stays two words, so each can be looked up alone.
    """
    words = [w for w in _WORD_SPLIT.split(_APOSTROPHES.sub("", fold(text))) if w]
    kept = [w for w in words if w != "and"] or words
    if len(kept) > 1 and kept[0] == "the":
        kept = kept[1:]
    return kept


def _forms(text: str) -> list[str]:
    """The text as space-separated words; Chinese gets a second form, in pinyin."""
    tokens = _tokens(text)
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


class _Query:
    """One form of a query, ready to be scored against many songs."""

    def __init__(self, text: str):
        self.text = text
        self.compact = text.replace(" ", "")

    def score(self, artist: str, title: str) -> float:
        """How well this query matches a song, 0–100 (artist and title are space-separated words).

        100 for the exact title, the exact artist, or both in either order; a
        typo costs a few points; a query that is only part of a name ("creep"
        in "creeping death", "musica" in "de musica ligera") gets at most 90.
        Everything is compared once more without spaces, so "ac dc" meets
        "acdc" and "banma" meets "ban ma".
        """
        q = self.text
        full = f"{artist} {title}"
        best = max(fuzz.ratio(q, title), fuzz.ratio(q, artist), fuzz.token_sort_ratio(q, full))
        if len(q) < len(full):
            best = max(best, PARTIAL_SCALE * fuzz.partial_ratio(q, full))
        qc = self.compact
        a, t = artist.replace(" ", ""), title.replace(" ", "")
        best = max(best, fuzz.ratio(qc, t), fuzz.ratio(qc, a), fuzz.ratio(qc, a + t))
        if len(qc) < len(a) + len(t):
            best = max(best, PARTIAL_SCALE * fuzz.partial_ratio(qc, a + t))
        return best


def _song_score(queries: list[_Query], song: Song) -> float:
    """The best score over a song's artists, each paired with its title, plain and in pinyin."""
    titles = _forms(clean_title(song.title)) or [""]
    best = 0.0
    for artist in dict.fromkeys(song.artists or [song.artist]):
        artists = _forms(artist) or [""]
        # Plain words with plain words, pinyin with pinyin (a form missing on one side is its plain one).
        for a, t in {(artists[0], titles[0]), (artists[-1], titles[-1])}:
            for q in queries:
                best = max(best, q.score(a, t))
    return best


# --- index hits ---------------------------------------------------------------------------


def _type_rank(kind: str) -> tuple[int, str]:
    return (TYPE_ORDER.index(kind) if kind in TYPE_ORDER else len(TYPE_ORDER), kind)


def _index_hit(conn: sqlite3.Connection, artist_key: str, song_key: str, score: float) -> IndexHit | None:
    """Every tab of the song, counted per type, with a sample page and names to show."""
    tabs = song_tabs(conn, artist_key, song_key)
    if not tabs:
        return None
    counts = Counter(t.type for t in tabs)
    ordered = {kind: counts[kind] for kind in sorted(counts, key=_type_rank)}
    labels = tuple(sorted({t.label for t in tabs if t.label}))
    sample = min(tabs, key=lambda t: (t.label is not None, _type_rank(t.type), t.tab_id))
    artist, title = _names_from_path(sample) or display_from_keys(artist_key, song_key)
    return IndexHit(artist_key, song_key, ordered, round(score, 1), sample.url, labels, artist, title)


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


def _title_words(key: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in key.split("-") if w)
