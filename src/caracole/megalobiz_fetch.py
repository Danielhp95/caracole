"""The Megalobiz step: timed lyrics for the songs LRCLIB left without them (megalobiz.py reads its API).

It follows LRCLIB's pass (lyrics.py), in the nightly run, in ``caracole lyrics`` and in a lookup, and asks about
the songs LRCLIB left (``songs_to_ask``), those with no lyrics first, newest first, none that Megalobiz answered
about in the last 30 days (kv ``megalobiz:checked:<song id>``, the time of a miss):

- a song LRCLIB answered a miss for (``lyrics_status`` "missing");
- a song still pending whose last LRCLIB lookup failed (kv ``lyrics:failed:<song id>``, which lyrics.py's pass
  keeps);
- a song whose lyrics LRCLIB has without timing (found, plain only): timed ones put each chord over its word.

A song takes the search's result that is it (``megalobiz.pick_result``), then that record's timed lyrics: two
requests at most, one when nothing fits. What each answer does:

- **Found**: the song's lyrics are Megalobiz's, ``lyrics.txt`` and ``lyrics.lrc`` written as LRCLIB's are
  (``lyrics.write_lyrics``) and stored with their provider and their page (``Lyrics.provider``, ``Lyrics.url``),
  which caracole links to wherever it credits them (the library page's Lyrics tile, info.json's ``lyrics_from``);
  the song is found.
- **A miss** (no result fits, or the record is gone, 404, or has no timed line): ``megalobiz:checked:`` now, and the
  song as it was: one LRCLIB missed stays missing (every site asked answered a miss), a pending one pending, one
  with plain lyrics keeps them. A miss is asked again after 30 days, past the cache.
- **An error** (provider_pass.py's ladder; a block propagates, a spent budget ends the pass): never a miss. A song
  LRCLIB missed goes back to pending, so that the next run asks both again (LRCLIB from its cache, sending
  nothing); any other is left as it was.

``[lyrics]`` (``picks``, lyrics.py): a song is searched under its ``as``. A record you picked is final: a song whose
record is another site's is never asked, nor timed lyrics for one with plain ones; a song whose record is Megalobiz's
is asked for that record alone, ``/lrc/{id}`` (``fetch_record``), one request, while it has no lyrics
(``lyrics.picked_due``), and that record gone (or with no timed line) is a miss that makes its lyrics missing, as the
one site asked answered one (logged), asked again after 30 days, past the cache, as is every ask after that miss, an
error between them aside (kv ``megalobiz:checked:``, which an error leaves). A pick, a clear or a search the client's
pauses let in is kept to at once (lyrics.py ``Turns``): ``picks`` read again, before each song's turn and after it.
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
from caracole.db import kv_delete, kv_get, kv_set
from caracole.http import Client, read_once_more
from caracole.library import song_dir, write_info
from caracole.lyrics import (
    FAILED,
    Lyrics,
    Turns,
    asked_as,
    picked_due,
    picked_record,
    plain_from_synced,
    song_lyrics,
    write_lyrics,
)
from caracole.megalobiz import (
    PROVIDER,
    SEARCH,
    MegalobizParseError,
    lrc_url,
    parse_lrc,
    parse_search,
    pick_result,
    record_json,
    search_params,
)
from caracole.provider_pass import PassStats, as_now, each_song
from caracole.songs import Song, get_song, list_songs, update_song

if TYPE_CHECKING:
    from collections.abc import Callable

    from caracole.overrides import LyricsPick, Overrides

log = logging.getLogger(__name__)

CHECKED = "megalobiz:checked:"  # + song id: when Megalobiz last answered a miss about the song
RECHECK_AFTER = timedelta(days=30)
_LRC_ACCEPT = (200, 404)  # a record gone is a 404: a miss


@dataclass
class MegalobizStats(PassStats):
    """What one pass did: ``tried``, ``errors`` and ``failures`` as every pass counts them (provider_pass.py);
    ``found``, songs that had no lyrics and now have Megalobiz's; ``timed``, songs whose plain lyrics are now
    Megalobiz's timed ones; ``missing``, songs it has nothing that fits for."""

    found: int = 0
    timed: int = 0
    missing: int = 0


def _lyrics(song: Song) -> Lyrics | None:
    try:
        return song_lyrics(song)
    except (TypeError, ValueError):  # lyrics stored that can't be read: as none
        return None


def _wants(conn: sqlite3.Connection, song: Song, picks: Mapping[str, LyricsPick] | None = None) -> bool:
    """Whether LRCLIB left the song for Megalobiz: missing, failed on and pending, or plain lyrics of its own; for a
    song with a picked record (``[lyrics]``), only when it is Megalobiz's and the song has no lyrics."""
    record = picked_record(song, picks)
    if record is not None:
        return record.site == PROVIDER and song.lyrics_status in ("pending", "missing")
    if song.lyrics_status == "missing":
        return True
    if song.lyrics_status == "pending":
        return kv_get(conn, f"{FAILED}{song.id}") is not None
    if song.lyrics_status == "found":
        lyrics = _lyrics(song)
        return lyrics is not None and lyrics.provider != PROVIDER and lyrics.has_lyrics and not lyrics.synced
    return False


def songs_to_ask(conn: sqlite3.Connection, now: datetime, *, recheck_after: timedelta = RECHECK_AFTER,
                 only: Collection[int] | None = None, picks: Mapping[str, LyricsPick] | None = None) -> list[Song]:
    """The songs LRCLIB left for Megalobiz that it hasn't answered a miss about since ``recheck_after``: those with
    no lyrics first, then those with plain ones, newest first within each; and those whose picked record
    (``picks``, ``Overrides.lyrics``) is Megalobiz's, by ``lyrics.picked_due``."""
    none: list[Song] = []
    plain: list[Song] = []
    for song in list_songs(conn):
        if _due(conn, song, now, recheck_after=recheck_after, only=only, picks=picks):
            (plain if song.lyrics_status == "found" else none).append(song)
    return none + plain


def _due(conn: sqlite3.Connection, song: Song, now: datetime, *, recheck_after: timedelta,
         only: Collection[int] | None, picks: Mapping[str, LyricsPick] | None = None) -> bool:
    """Whether ``songs_to_ask`` lists the song."""
    if song.status == "ignored" or (only is not None and song.id not in only) or not _wants(conn, song, picks):
        return False
    if picked_record(song, picks) is not None:
        return picked_due(song, now, recheck_after)
    checked = kv_get(conn, f"{CHECKED}{song.id}")
    return checked is None or stamps.before(checked, stamps.utc(now) - recheck_after)


def fetch_megalobiz(client: Client, *, artist: str, title: str, duration_s: float | None,
                    cache: bool = True) -> Lyrics | None:
    """A song's timed lyrics from Megalobiz, or None when it has none that fit: the search, then the record of the
    result that is the song. Errors propagate (``MegalobizParseError`` for an answer that isn't as documented, a
    cached one asked for once more first, past the cache); ``cache`` goes to each first request."""
    params = search_params(artist, title, duration_s)
    resp = client.get(SEARCH, params=params, cache=cache)
    results = read_once_more(client, resp, SEARCH, parse_search, MegalobizParseError, params=params)
    found = pick_result(results, artist=artist, title=title, duration_s=duration_s)
    if found is None:
        return None
    return fetch_record(client, found.id, cache=cache)


def fetch_record(client: Client, lrc_id: int, *, cache: bool = True) -> Lyrics | None:
    """A record's timed lyrics, ``/lrc/{id}``: the search's result that is the song, or the record you picked
    (``[lyrics]``); None for one gone (its 404) or with no timed line. Errors propagate as ``fetch_megalobiz``'s do;
    ``cache`` goes to the first request."""
    url = lrc_url(lrc_id)
    resp = client.get(url, accept=_LRC_ACCEPT, cache=cache)
    if resp.status == 404:
        return None
    lrc = read_once_more(client, resp, url, parse_lrc, MegalobizParseError, accept=_LRC_ACCEPT)
    if not lrc.lrc:
        return None
    return Lyrics(plain=plain_from_synced(lrc.lrc), synced=lrc.lrc, instrumental=False, duration=lrc.duration,
                  lrclib_id=None, raw=record_json(lrc), provider=PROVIDER, url=lrc.url)


def megalobiz_lyrics(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    now: datetime,
    *,
    only: Collection[int] | None = None,
    durations: Mapping[int, float] | None = None,
    recheck_after: timedelta = RECHECK_AFTER,
    picks: Mapping[str, LyricsPick] | None = None,
    reload_overrides: Callable[[], Overrides] | None = None,
) -> MegalobizStats:
    """Ask Megalobiz about the songs LRCLIB left (``songs_to_ask``; of ``only``'s ids when given, a lookup's one
    song); see the module docstring. ``durations``: a length by song id for a song whose line gives none (a sheet
    from a YouTube video's audio), else LRCLIB's plain lyrics' length. ``picks``: ``Overrides.lyrics``, the name a
    song is asked under and the record picked; without it, every request is what it was. ``reload_overrides``: after
    the client handed caracole's lock over, ``picks`` read again, as lyrics.py's ``Turns`` says."""
    stats = MegalobizStats()
    stamp = stamps.stamp(now)
    turns = Turns(conn, client, picks, reload_overrides,
                  lambda song, held: _due(conn, song, now, recheck_after=recheck_after, only=only, picks=held))

    def length(song: Song) -> float | None:
        if song.duration_s is not None:
            return song.duration_s
        given = (durations or {}).get(song.id)
        if given is not None:
            return given
        lyrics = _lyrics(song)
        return lyrics.duration if lyrics is not None and lyrics.duration else None

    def turn(song: Song) -> Lyrics | None:  # a miss asked again goes past the cache
        held = turns.asking(song)
        record = picked_record(song, held)
        if record is not None:
            # past the cache once Megalobiz answered it a miss: an error since never makes its cached 404 a new one
            return fetch_record(client, int(record.id), cache=kv_get(conn, f"{CHECKED}{song.id}") is None)
        cache = kv_get(conn, f"{CHECKED}{song.id}") is None
        artist, title, _ = asked_as(song, held)
        return fetch_megalobiz(client, artist=artist, title=title, duration_s=length(song), cache=cache)

    def back_to_pending(song: Song, error: Exception) -> None:
        # a song is missing only once every site asked answered a miss; as it is now, since a pick or a clear in the
        # turn's pauses asked its question anew
        if turns.still_asked(song) and get_song(conn, song.id).lyrics_status == "missing":
            update_song(conn, song.id, lyrics_status="pending", lyrics_at=None)

    songs = songs_to_ask(conn, now, recheck_after=recheck_after, only=only, picks=picks)
    for song, lyrics in each_song(as_now(conn, songs, turns.due), stats, turn, site="Megalobiz",
                                  on_error=back_to_pending, on_cut=back_to_pending):
        song = turns.answered(song)
        if song is None:  # a pick, a clear or a name came in this very turn: its answer isn't the song's now
            continue
        if lyrics is None:
            kv_set(conn, f"{CHECKED}{song.id}", stamp)
            record = picked_record(song, turns.picks)
            if record is not None:  # the one site asked missed: the song's lyrics are missing
                log.info("%s: the record you picked is gone: %s", song.display, record.text.replace(":", " ", 1))
                update_song(conn, song.id, lyrics_status="missing", lyrics_at=stamp)
            stats.missing += 1
            continue
        write_lyrics(song_dir(library_dir, song), lyrics)
        update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics.to_json(), lyrics_at=stamp)
        kv_delete(conn, f"{CHECKED}{song.id}")
        kv_delete(conn, f"{FAILED}{song.id}")
        write_info(conn, library_dir, get_song(conn, song.id))  # its "lyrics_from": the link back to their page
        if song.lyrics_status == "found":
            stats.timed += 1
        else:
            stats.found += 1
    return stats
