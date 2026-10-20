"""``caracole review``: settle uncertain matches, one prompt per song.

Each decision is written to overrides.toml, so it survives a lost database and
can live in git:

- choosing a candidate writes ``[match]``, plus an ``[alias]`` when the artist
  differs, so every other song by that artist is fixed too (but never for a
  title-only match, usually a cover by someone else, nor for one under a
  catch-all artist such as ``misc-musicals``: ``match.NO_ALIAS_STEPS``);
- ``n`` (none of these) writes every candidate shown under ``[reject]``: they
  never come back, and the song is still looked for, on its artist's UG page
  too, without being ignored;
- ``p`` pins a UG tab page you paste;
- ``i`` ignores the song.

The first two are also functions of their own, ``accept`` and ``reject``, for
one answer given without the questions: ``caracole review --song`` and the
picker of ``caracole serve`` (web/app.py) answer through them. ``candidates_of``
gives the candidates a review lists, in its order and numbering, and
``step_words`` says in plain words why the matcher thought of each one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from caracole.config import Config
from caracole.match import NO_ALIAS_STEPS, PERFORMER_CATCH_ALLS
from caracole.normalize import clean_title, slug_key
from caracole.overrides import (
    OverridesError,
    add_alias,
    add_ignore,
    add_match,
    add_pin,
    add_reject,
    tab_id_from_url,
)
from caracole.songs import Song, list_songs, update_song
from caracole.ug.lookup import song_tabs

SHOWN = 9  # candidates a review lists, numbered 1 to 9
SEARCH = "search"  # the step of a candidate caracole search found, for a song not found
SEARCHED = 5  # search hits offered as a song not found's candidates

# Why the matcher thought of a candidate, by the step that found it (match.STEPS).
_STEP_WORDS = {
    SEARCH: "a caracole search hit for its artist and title",
    "exact": "same artist and title",
    "alias": "under the artist's [alias]",
    "fuzzy_title": "title spelled differently",
    "fuzzy_artist": "artist spelled differently",
    "word_title": "a title of the artist's with words more or fewer",
    "typo_artist": "artist a letter or two off",
    "title_only": "title only: another artist's song, probably a cover",
    "override": "your [match] in overrides.toml",
    "pin": "pinned in overrides.toml",
    "artist_page": "on the artist's UG page",
}


def candidates_of(song: Song) -> list[dict[str, Any]]:
    """The candidates ``caracole review`` lists for a song, best first, numbered from 1 as it numbers
    them: its stored candidates (``songs.match_candidates``) that name a UG song, nine at most."""
    return [c for c in (song.match_candidates or []) if c.get("artist_key") and c.get("song_key")][:SHOWN]


def search_candidates(conn: sqlite3.Connection, song: Song, *, rejected: Collection[tuple[str, str]] = (),
                      limit: int = SEARCHED) -> list[dict[str, Any]]:
    """For a song not found (and not ignored), what ``caracole search`` finds for its artist and title in
    the offline index, best first, as candidates of step ``SEARCH``; the UG songs ``rejected`` for it
    (its ``[reject]`` entry) left out. None for any other song."""
    from caracole.search import search_index

    if song.match_decision != "not_found" or song.status == "ignored":
        return []
    hits = search_index(conn, f"{song.artist} {clean_title(song.title)}", limit + len(rejected))
    found = [{"artist_key": h.artist_key, "song_key": h.song_key, "score": h.score, "step": SEARCH}
             for h in hits if (h.artist_key, h.song_key) not in rejected]
    return found[:limit]


def ref(cand: Mapping[str, Any]) -> str:
    """A candidate as overrides.toml names a UG song: ``"artist-key/song-key"``."""
    return f"{cand['artist_key']}/{cand['song_key']}"


def writes_alias(song: Song, cand: Mapping[str, Any]) -> bool:
    """Whether accepting the candidate adds an ``[alias]`` too: when the artist's name differs, but
    never for a title-only match (a cover, mostly) nor under a catch-all artist (``NO_ALIAS_STEPS``),
    nor for a search hit, which may be a cover as well as another spelling."""
    return cand.get("step") not in (*NO_ALIAS_STEPS, SEARCH) and slug_key(song.artist) != cand["artist_key"]


def accept(conn: sqlite3.Connection, cfg: Config, song: Song, cand: Mapping[str, Any]) -> None:
    """The answer "this one": ``[match]``, and ``[alias]`` when ``writes_alias``; the review is settled."""
    add_match(cfg.overrides_file, song.display, ref(cand))
    if writes_alias(song, cand):
        add_alias(cfg.overrides_file, song.artist, cand["artist_key"])
    update_song(conn, song.id, review=False)


def reject(conn: sqlite3.Connection, cfg: Config, song: Song, cands: Sequence[Mapping[str, Any]]) -> None:
    """The answer "none of these": every candidate shown under ``[reject]``. The song is still looked
    for: the rematch makes it not found, or a review of the rest."""
    add_reject(cfg.overrides_file, song.display, [ref(c) for c in cands])
    update_song(conn, song.id, review=False)


def step_words(cand: Mapping[str, Any]) -> str:
    """Why the matcher thought of a candidate, in plain words: "artist spelled differently", "under UG's
    catch-all misc-musicals". An unknown step is given as it is; none, as nothing."""
    step = cand.get("step") or ""
    if step == "catch_all":
        artist = cand.get("artist_key") or ""
        performer = ", the performer's name first" if artist in PERFORMER_CATCH_ALLS else ""
        return f"under UG's catch-all {artist}{performer}"
    return _STEP_WORDS.get(step, step)


@dataclass
class ReviewIO:
    read: Callable[[str], str]
    write: Callable[[str], None]


@dataclass
class ReviewStats:
    accepted: int = 0
    ignored: int = 0
    pinned: int = 0
    skipped: int = 0
    rejected: int = 0  # songs answered "none of these"

    @property
    def changed(self) -> bool:
        return bool(self.accepted or self.ignored or self.pinned or self.rejected)


def review_songs(
    conn: sqlite3.Connection,
    cfg: Config,
    io: ReviewIO,
    *,
    rematch: Callable[[], None] | None = None,
    only: Collection[int] | None = None,
) -> ReviewStats:
    """Walk the songs flagged for review (with ``only``, those of these ids); re-run matching afterwards
    if anything changed."""
    stats = ReviewStats()
    songs = [s for s in list_songs(conn) if s.review and s.status != "ignored" and (only is None or s.id in only)]
    if not songs:
        io.write("Nothing to review.")
        return stats
    for i, s in enumerate(songs, start=1):
        cands = candidates_of(s)
        io.write(f"\n[{i}/{len(songs)}] {s.display}")
        for n, c in enumerate(cands, start=1):
            tabs = song_tabs(conn, c["artist_key"], c["song_key"])
            url = f"  {tabs[0].url}" if tabs else ""
            io.write(f"  {n}) {float(c.get('score') or 0):.0f}  {c['artist_key']}/{c['song_key']} ({c.get('step', '')}){url}")
        choices = f"1-{len(cands)}, (n)one of these, " if cands else ""
        answer = io.read(f"Pick {choices}(p)in a URL, (i)gnore, (s)kip, (q)uit: ").strip().lower()
        if answer == "q":
            break
        if answer.isdigit() and 1 <= int(answer) <= len(cands):
            accept(conn, cfg, s, cands[int(answer) - 1])
            stats.accepted += 1
        elif answer == "n" and cands:
            reject(conn, cfg, s, cands)
            stats.rejected += 1
        elif answer == "i":
            add_ignore(cfg.overrides_file, s.display)
            update_song(conn, s.id, review=False, status="ignored")
            stats.ignored += 1
        elif answer == "p":
            url = io.read("UG tab URL: ").strip()
            if not url:  # Enter: skip after all
                stats.skipped += 1
                continue
            try:
                tab_id_from_url(url)
            except OverridesError as e:
                io.write(f"  {e}; skipped")
                stats.skipped += 1
                continue
            add_pin(cfg.overrides_file, s.display, [url])
            update_song(conn, s.id, review=False)
            stats.pinned += 1
        else:
            stats.skipped += 1
    if stats.changed and rematch is not None:
        rematch()
    return stats
