"""``tabarr review``: settle uncertain matches, one prompt per song.

Each decision is written to overrides.toml, so it survives a lost database and
can live in git:

- choosing a candidate writes ``[match]``, plus an ``[alias]`` when the artist
  differs, so every other song by that artist is fixed too (but never for a
  title-only match: that's usually a cover by someone else);
- ``p`` pins a UG tab page you paste;
- ``i`` ignores the song.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from tabarr.config import Config
from tabarr.normalize import slug_key
from tabarr.overrides import OverridesError, add_alias, add_ignore, add_match, add_pin, tab_id_from_url
from tabarr.songs import list_songs, update_song
from tabarr.ug.lookup import song_tabs


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

    @property
    def changed(self) -> bool:
        return bool(self.accepted or self.ignored or self.pinned)


def review_songs(
    conn: sqlite3.Connection,
    cfg: Config,
    io: ReviewIO,
    *,
    rematch: Callable[[], None] | None = None,
) -> ReviewStats:
    """Walk the songs flagged for review; re-run matching afterwards if anything changed."""
    stats = ReviewStats()
    songs = [s for s in list_songs(conn) if s.review and s.status != "ignored"]
    if not songs:
        io.write("Nothing to review.")
        return stats
    for i, s in enumerate(songs, start=1):
        cands = [c for c in (s.match_candidates or []) if c.get("artist_key") and c.get("song_key")][:9]
        io.write(f"\n[{i}/{len(songs)}] {s.display}")
        for n, c in enumerate(cands, start=1):
            tabs = song_tabs(conn, c["artist_key"], c["song_key"])
            url = f"  {tabs[0].url}" if tabs else ""
            io.write(f"  {n}) {float(c.get('score') or 0):.0f}  {c['artist_key']}/{c['song_key']} ({c.get('step', '')}){url}")
        choices = f"1-{len(cands)}, " if cands else ""
        answer = io.read(f"Pick {choices}(p)in a URL, (i)gnore, (s)kip, (q)uit: ").strip().lower()
        if answer == "q":
            break
        if answer.isdigit() and 1 <= int(answer) <= len(cands):
            c = cands[int(answer) - 1]
            add_match(cfg.overrides_file, s.display, f"{c['artist_key']}/{c['song_key']}")
            if c.get("step") != "title_only" and slug_key(s.artist) != c["artist_key"]:
                add_alias(cfg.overrides_file, s.artist, c["artist_key"])
            update_song(conn, s.id, review=False)
            stats.accepted += 1
        elif answer == "i":
            add_ignore(cfg.overrides_file, s.display)
            update_song(conn, s.id, review=False, status="ignored")
            stats.ignored += 1
        elif answer == "p":
            url = io.read("UG tab URL: ").strip()
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
