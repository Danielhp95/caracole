"""The local matching ladder: your songs against the UG index, offline (plan §2).

For each song, in order:

1. ``overrides.toml``: ``[ignore]``, then ``[pin]``, then ``[match]``.
2. For each of the song's artists, the UG artist keys it may go by: its
   ``[alias]`` first, then its own key, then any UG key that is the same once
   hyphens are removed (``ac-dc`` → ``acdc``). A Chinese name also tries its
   pinyin (宋冬野 → ``song-dong-ye``, which meets ``song-dongye`` the same way),
   and a name written in two scripts each of its parts (``normalize.name_forms``):
   UG's sitemaps write names in Latin letters only, so "打上花火 (Uchiage Hanabi)"
   meets ``uchiage-hanabi``. Under those artists an exact title accepts at once. Otherwise every title
   is scored with rapidfuzz ``ratio``, the best of UG's full key and its base
   key, so ``creep-acoustic`` and ``creep-intro`` count as ``creep``.
3. The nearest other artist key at or above ``artist_gate``, then step 2 under
   it, scored as the lower of the artist and title scores. A Chinese name's
   pinyin is compared with and without hyphens.
4. The title alone, across every artist (covers and misfiled tabs). These are
   always reviews. Here a Chinese title's pinyin must match exactly, hyphens
   aside: across every artist, short syllables fuzz-match unrelated titles. So
   must the parts of a title written in two scripts.

At every step, the UG songs you rejected for the song (``[reject]``, "none of
these" in ``caracole review``) are dropped, so they never come back; the others
still can. Decision: accept at ``accept`` or more with a lead of ``margin`` over
the next different title; review from ``review``; otherwise not found.

``match_all`` never replaces a match the fetch step made on a UG artist page
(step ``artist_page``, amendment A6): the index can't see those bare-id tabs,
so only your overrides can. Nor does an index that isn't complete (empty:
never built, or emptied; partial: a build stopped part-way) undo what the
ladder found before, or record a miss: it is no evidence that UG lacks a song.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz, process

from caracole.config import MatchPolicy
from caracole.normalize import clean_title, compact, has_han, name_forms, romanize, slug_key, split_variant
from caracole.overrides import Overrides
from caracole.songs import Song, list_songs, refresh_status, update_song, utc_now_iso
from caracole.ug.index import index_state
from caracole.versions import mark_stale

DECISIONS = ("accept", "review", "not_found", "pinned", "ignored")
STEPS = ("override", "pin", "exact", "alias", "fuzzy_title", "fuzzy_artist", "title_only")
LADDER_STEPS = ("exact", "alias", "fuzzy_title", "fuzzy_artist", "title_only")  # what the index decided
ARTIST_PAGE = "artist_page"  # the fetch step's matches on UG artist pages (A6)
MAX_CANDIDATES = 5
_TITLE_ONLY_TITLES = 10  # nearest titles expanded into candidates, per title form


@dataclass(frozen=True)
class IndexSong:
    """One song key of an artist in the index, with every tab (id, type) listed under it."""

    song_key: str
    base_key: str
    label: str | None
    tabs: tuple[tuple[int, str], ...]


def _songs_of(rows: Iterable[tuple[str, int, str]]) -> list[IndexSong]:
    """Group rows of (song_key, tab_id, type), sorted by song key, into songs."""
    songs = []
    for song_key, group in itertools.groupby(rows, key=lambda r: r[0]):
        base, label = split_variant(song_key)
        songs.append(IndexSong(song_key, base, label, tuple((r[1], r[2]) for r in group)))
    return songs


class IndexView:
    """``ug_index`` as the matcher reads it during one run.

    The artist keys (about 150,000) are loaded once, on first use, and so are
    the title keys (about 720,000), which only title-only matching needs. An
    artist's songs are read when a song first asks for that artist.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._artists: list[str] | None = None
        self._artist_set: frozenset[str] = frozenset()
        self._by_compact: dict[str, tuple[str, ...]] = {}
        self._compact_artists: list[str] | None = None
        self._songs: dict[str, list[IndexSong]] = {}
        self._titles: list[str] | None = None
        self._compact_titles: list[str] | None = None

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
        self.artist_keys()
        return artist_key in self._artist_set

    def compact_artists(self, compact_key: str) -> tuple[str, ...]:
        """The artist keys that read ``compact_key`` once hyphens are removed."""
        self.artist_keys()
        return self._by_compact.get(compact_key, ())

    def compact_artist_keys(self) -> list[str]:
        """``artist_keys()`` with hyphens removed, in the same order."""
        if self._compact_artists is None:
            self._compact_artists = [compact(a) for a in self.artist_keys()]
        return self._compact_artists

    def songs_for_artist(self, artist_key: str) -> list[IndexSong]:
        """The artist's songs, one per song key (variant keys such as ``x-acoustic`` are their own)."""
        songs = self._songs.get(artist_key)
        if songs is None:
            rows = self.conn.execute(
                "SELECT song_key, tab_id, type FROM ug_index WHERE artist_key = ? ORDER BY song_key, tab_id",
                (artist_key,),
            )
            songs = self._songs[artist_key] = _songs_of(tuple(r) for r in rows)
        return songs

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

    def songs_for_title(self, title_key: str) -> list[tuple[str, IndexSong]]:
        """Every (artist key, song) whose base key is ``title_key``."""
        # A range instead of LIKE, so the song_key index serves the variant keys too.
        rows = self.conn.execute(
            "SELECT artist_key, song_key, tab_id, type FROM ug_index "
            "WHERE song_key = ? OR (song_key > ? AND song_key < ?) ORDER BY artist_key, song_key, tab_id",
            (title_key, title_key + "-", title_key + "."),
        ).fetchall()
        out = []
        for artist_key, group in itertools.groupby(rows, key=lambda r: r[0]):
            out += [(artist_key, s) for s in _songs_of((r[1], r[2], r[3]) for r in group) if s.base_key == title_key]
        return out

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
        for form in _forms(name).keys:
            add(form)
            for a in index.compact_artists(compact(form)):
                add(a)
        for form in _forms(name).keys:
            for alt in _article_forms(form):
                add(alt)
    return list(keys.items())


def _title_hits(index: IndexView, artist_key: str, title: _Forms, rank: int, *, exact_step: str,
                fuzzy_step: str = "fuzzy_title", cap: float | None = None) -> list[_Hit]:
    """Score every title of one artist, grouped by base key."""
    groups: dict[str, list[IndexSong]] = {}
    for s in index.songs_for_artist(artist_key):
        groups.setdefault(s.base_key, []).append(s)
    compact_pinyin = [compact(p) for p in title.pinyin]
    hits = []
    for base, members in groups.items():
        keys = {base, *(m.song_key for m in members)}
        if any(k in keys or compact(k) == compact(base) for k in title.keys):
            score, step = 100.0, exact_step
        else:
            score = max(fuzz.ratio(k, u) for k in title.keys for u in keys)
            score = max([score, *(fuzz.ratio(c, compact(base)) for c in compact_pinyin)])
            step = fuzzy_step
        if cap is not None:
            score = min(score, cap)
        tabs = sum(len(m.tabs) for m in members)
        hits.append(_Hit(MatchCandidate(artist_key, base, round(score, 1), step), rank, tabs))
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


def _title_only(index: IndexView, title: _Forms, policy: MatchPolicy) -> list[_Hit]:
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
        tabs: dict[str, int] = {}
        for artist_key, s in index.songs_for_title(key):
            tabs[artist_key] = tabs.get(artist_key, 0) + len(s.tabs)
        hits += [_Hit(MatchCandidate(a, key, round(score, 1), "title_only"), 0, n) for a, n in tabs.items()]
    return _ranked(hits)


def _allowed(hits: Iterable[_Hit], rejected: frozenset[tuple[str, str]]) -> list[_Hit]:
    """The hits that aren't UG songs you rejected for the song."""
    return [h for h in hits if (h.cand.artist_key, h.cand.song_key) not in rejected]


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
    if decision != "accept":
        tried = {a for a, _ in own}
        for i, (artist_key, score) in enumerate(_nearest_artists(song, index, tried, policy.artist_gate)):
            hits += _allowed(_title_hits(index, artist_key, title, len(own) + i, exact_step="fuzzy_artist",
                                         fuzzy_step="fuzzy_artist", cap=score), rejected)
        ranked = _ranked(hits)
        decision = _decide(ranked, policy)
    if decision != "not_found":
        return _result(decision, ranked)

    by_title = _allowed(_title_only(index, title, policy), rejected)
    if by_title:
        return _result("review", by_title)
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


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("SAVEPOINT match_all")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK TO match_all")
        conn.execute("RELEASE match_all")
        raise
    conn.execute("RELEASE match_all")


def match_all(conn: sqlite3.Connection, overrides: Overrides, policy: MatchPolicy, *,
              dry_run: bool = False) -> list[MatchChange]:
    """Match every song, newest first, and store the results (unless ``dry_run``).

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
    is its stored match (not found, for one never matched).
    """
    index = IndexView(conn)
    complete = index_state(conn) == "complete"
    changes, kept = [], set()
    for song in list_songs(conn):
        new = match_song(song, index, overrides, policy)
        if _keeps_stored(song, new, overrides.reject.get(song.key, frozenset()), complete=complete):
            new = _stored(song)
            kept.add(song.id)
        changes.append(MatchChange(song, song.match_decision, new))
    if not dry_run:
        now = utc_now_iso()
        with _transaction(conn):
            for c in changes:
                if c.song.id not in kept:
                    _save(conn, c.song, c.new, now)
    return changes
