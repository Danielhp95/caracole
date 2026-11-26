"""The AZLyrics step: plain lyrics for the songs LRCLIB and Megalobiz left without any (azlyrics.py reads its pages).

It follows Megalobiz's pass, in the nightly run, in ``caracole lyrics``, in a lookup and in a sheet from a YouTube video,
and asks about the songs with no lyrics (``songs_to_ask``), newest first, none that it answered a miss about in the last
30 days (kv ``azlyrics:checked:<song id>``): a song LRCLIB answered a miss for (``lyrics_status`` "missing"), or still
pending because its last LRCLIB lookup failed (kv ``lyrics:failed:<song id>``). A song with plain lyrics isn't asked:
AZLyrics has no timing to add.

A song takes two requests, one right after the other: its artist's page (``azlyrics.artist_url``), then the lyrics page
of the line that is the song (``azlyrics.pick_song``). Never a letter page, a search or an index. A song ``[azlyrics]``
names a page for takes that page alone, whoever it credits, and is asked about whatever its last miss or LRCLIB's
failure. What each answer does:

- **Found**: the song's lyrics are AZLyrics', ``lyrics.txt`` written as LRCLIB's plain lyrics are
  (``lyrics.write_lyrics``) and stored with their provider and their page (``Lyrics.provider``, ``Lyrics.url``), which
  caracole links to wherever it credits them; the song is found, and Megalobiz is asked about it again as about any
  song with plain lyrics, every 30 days.
- **A miss** (no such artist, or song, or page, 404): ``azlyrics:checked:`` now, and the song as it was. A miss is asked
  again after 30 days, past the cache.
- **An error** (provider_pass.py's ladder; a block propagates): never a miss. A song LRCLIB missed goes back to pending,
  so that the next run asks every site again (LRCLIB and Megalobiz from their cache or their 30 days); any other is
  left as it was.

``[lyrics]`` (``lyrics``, lyrics.py): the artist's page is that of its ``as``, and the song looked for on it its title;
an ``[azlyrics]`` page wins over it. A record you picked is final, and wins over an ``[azlyrics]`` page: a song whose
record is another site's is never asked; one whose record is AZLyrics' is asked for that page alone
(``LyricsRecord.page``), one request, while it has no lyrics (``lyrics.picked_due``), and that page gone is a miss that
makes its lyrics missing, as the one site asked answered one (logged), asked again after 30 days, past the cache, as
is every ask after that miss, an error between them aside (kv ``azlyrics:checked:``, which an error leaves).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from caracole import stamps
from caracole.azlyrics import PROVIDER, AzLyricsParseError, artist_url, parse_artist, parse_lyrics, pick_song
from caracole.db import kv_delete, kv_get, kv_set
from caracole.http import Client, read_once_more
from caracole.library import song_dir, write_info
from caracole.lyrics import FAILED, Lyrics, asked_as, picked_due, picked_record, write_lyrics
from caracole.overrides import override_key
from caracole.provider_pass import PassStats, as_now, each_song
from caracole.songs import Song, get_song, list_songs, update_song

if TYPE_CHECKING:
    from caracole.overrides import LyricsPick

log = logging.getLogger(__name__)

CHECKED = "azlyrics:checked:"  # + song id: when AZLyrics last answered a miss about the song
RECHECK_AFTER = timedelta(days=30)
_ACCEPT = (200, 404)  # no such page: a miss


@dataclass
class AzLyricsStats(PassStats):
    """What one pass did: ``tried``, ``errors`` and ``failures`` as every pass counts them (provider_pass.py);
    ``found``, songs that had no lyrics and now have AZLyrics'; ``missing``, songs it has nothing for."""

    found: int = 0
    missing: int = 0


def _wants(conn: sqlite3.Connection, song: Song) -> bool:
    """Whether the sites before it left the song without lyrics: missing, or failed on and pending."""
    if song.lyrics_status == "pending":
        return kv_get(conn, f"{FAILED}{song.id}") is not None
    return song.lyrics_status == "missing"


def songs_to_ask(conn: sqlite3.Connection, now: datetime, *, picks: Mapping[str, str] | None = None,
                 recheck_after: timedelta = RECHECK_AFTER, only: Collection[int] | None = None,
                 lyrics: Mapping[str, LyricsPick] | None = None) -> list[Song]:
    """The songs with no lyrics that AZLyrics hasn't answered a miss about since ``recheck_after``, or that ``picks``
    (``Overrides.azlyrics``) names a page for, newest first; of those with a picked record (``lyrics``,
    ``Overrides.lyrics``), only those whose record is AZLyrics', by ``lyrics.picked_due``."""
    return [song for song in list_songs(conn)
            if _due(conn, song, now, picks=picks, recheck_after=recheck_after, only=only, lyrics=lyrics)]


def _due(conn: sqlite3.Connection, song: Song, now: datetime, *, picks: Mapping[str, str] | None,
         recheck_after: timedelta, only: Collection[int] | None,
         lyrics: Mapping[str, LyricsPick] | None = None) -> bool:
    """Whether ``songs_to_ask`` lists the song."""
    if song.status == "ignored" or (only is not None and song.id not in only):
        return False
    record = picked_record(song, lyrics)
    if record is not None:
        return record.site == PROVIDER and picked_due(song, now, recheck_after)
    if override_key(song.display) in (picks or {}):
        return song.lyrics_status in ("pending", "missing")
    checked = kv_get(conn, f"{CHECKED}{song.id}")
    return _wants(conn, song) and (checked is None or stamps.before(checked, stamps.utc(now) - recheck_after))


def fetch_azlyrics(client: Client, *, artist: str, title: str, page: str | None = None,
                   cache: bool = True) -> Lyrics | None:
    """A song's plain lyrics from AZLyrics, or None when it has none: its artist's page, then the song's lyrics page, or
    ``page`` alone when it is given. Errors propagate (``AzLyricsParseError`` for a page that doesn't read, a cached
    one asked for once more first, past the cache); ``cache`` goes to each first request."""
    if page is None:
        url = artist_url(artist)
        if url is None:
            return None
        resp = client.get(url, accept=_ACCEPT, cache=cache)
        if resp.status == 404:
            return None
        listed = read_once_more(client, resp, url, parse_artist, AzLyricsParseError, accept=_ACCEPT)
        song = pick_song(listed, artist=artist, title=title)
        if song is None:
            return None
        page = song.url
    resp = client.get(page, accept=_ACCEPT, cache=cache)
    if resp.status == 404:
        return None
    plain = read_once_more(client, resp, page, parse_lyrics, AzLyricsParseError, accept=_ACCEPT)
    return Lyrics(plain=plain, synced=None, instrumental=False, duration=None, lrclib_id=None, raw={"url": page},
                  provider=PROVIDER, url=page)


def azlyrics_lyrics(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    now: datetime,
    *,
    picks: Mapping[str, str] | None = None,
    only: Collection[int] | None = None,
    recheck_after: timedelta = RECHECK_AFTER,
    lyrics: Mapping[str, LyricsPick] | None = None,
) -> AzLyricsStats:
    """Ask AZLyrics about the songs left with no lyrics (``songs_to_ask``; of ``only``'s ids when given, a lookup's one
    song); see the module docstring. ``picks``: ``Overrides.azlyrics``; ``lyrics``: ``Overrides.lyrics``, the name a
    song is asked under and the record picked; without them, every request is what it was."""
    stats = AzLyricsStats()
    stamp = stamps.stamp(now)

    def turn(song: Song) -> Lyrics | None:  # a miss asked again goes past the cache
        record = picked_record(song, lyrics)
        if record is not None:
            # past the cache once AZLyrics answered it a miss: an error since never makes its cached 404 a new one
            return fetch_azlyrics(client, artist="", title="", page=record.page,
                                  cache=kv_get(conn, f"{CHECKED}{song.id}") is None)
        page = (picks or {}).get(override_key(song.display))
        cache = page is not None or kv_get(conn, f"{CHECKED}{song.id}") is None
        artist, title, _ = asked_as(song, lyrics)
        return fetch_azlyrics(client, artist=artist, title=title, page=page, cache=cache)

    def back_to_pending(song: Song, error: Exception) -> None:
        if song.lyrics_status == "missing":  # a song is missing only once every site asked answered a miss
            update_song(conn, song.id, lyrics_status="pending", lyrics_at=None)

    songs = as_now(conn, songs_to_ask(conn, now, picks=picks, recheck_after=recheck_after, only=only, lyrics=lyrics),
                   lambda song: _due(conn, song, now, picks=picks, recheck_after=recheck_after, only=only,
                                     lyrics=lyrics))
    for song, found in each_song(songs, stats, turn, site="AZLyrics", on_error=back_to_pending,
                                 on_cut=back_to_pending):
        if found is None:
            kv_set(conn, f"{CHECKED}{song.id}", stamp)
            record = picked_record(song, lyrics)
            if record is not None:  # the one site asked missed: the song's lyrics are missing
                log.info("%s: the record you picked is gone: %s", song.display, record.text.replace(":", " ", 1))
                update_song(conn, song.id, lyrics_status="missing", lyrics_at=stamp)
            stats.missing += 1
            continue
        write_lyrics(song_dir(library_dir, song), found)
        update_song(conn, song.id, lyrics_status="found", lyrics_json=found.to_json(), lyrics_at=stamp)
        kv_delete(conn, f"{CHECKED}{song.id}")
        kv_delete(conn, f"{FAILED}{song.id}")
        write_info(conn, library_dir, get_song(conn, song.id))  # its "lyrics_from": the link back to their page
        stats.found += 1
    return stats
