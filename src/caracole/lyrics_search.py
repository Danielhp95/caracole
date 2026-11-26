"""What the three lyrics sites list under a name you type, for a song whose own name finds nothing there (a video's
decorated title, a transliterated artist): ``caracole lyrics --song X --as "A - T"``.

The name is noted first, ``[lyrics]``' ``as`` (taken out when it is the song's own), so the nights after ask under it
too, and a new name resets the question (``ask_anew``: for a song pending or missing alone, the sites' misses
forgotten and the song pending again; found lyrics or an instrumental verdict stay as they are); then each site is
asked once, at a lookup's pace, by one interactive client of its own (``_common.make_client``, run ``lookup:…``), in
the lookups' lane, where another lookup goes first in the clients' pauses:

- LRCLIB's ``/api/search`` for the typed name, then ``/api/get`` with it and the audio's length only when no record of
  the search fits it: each record with lyrics a row, an instrumental or empty one counted, never listed;
- Megalobiz's search (``search_params``): each result a row, its lyrics never asked;
- AZLyrics' page of the typed artist, only where one can be named (``azlyrics.artist_url``): the songs on it whose
  title fits the typed one. Its search, which robots.txt closes, is never asked.

So 2 to 4 requests. Each answer is read through the HTTP cache while it is younger than ``PICKABLE_FOR``, the life of
a kept search (the same name typed again costs nothing, and a pick reads LRCLIB's answer with no request), and asked
again, past the cache, once older (``max_age``: a cached 404 alike), so a record a site adds later is listed. The
nightly passes read the same addresses through the cache with no age (AZLyrics' artist page; LRCLIB's search and
get, for a song asked under ``as``): a search's fresher copy is theirs too, and theirs one younger than a week is the
search's. A site turned off, cooling down, out of its asks or failing is passed over and said (``Search.said``, with
its ``Search.state``), never a miss; a block cools it down, with no alert, as a lookup's does. It changes no stored
lyrics.

The rows are kept in kv ``lyrics-search:<song id>`` (``KV``), replaced by the song's next search, for a pick within
``PICKABLE_FOR`` (``kept_search``, ``row_of``; ``last_search`` reads it however old, ``pickable`` says whether it
still is). The name typed is read by ``typed_name``, the command's and caracole serve's route's alike. A row names
its record only by an id the site answered, of the shape ``[lyrics]`` takes (``overrides.LYRICS_RECORD_IDS``): one of
any other shape is dropped as it is read, from the site or from kv.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from caracole import stamps
from caracole.config import Config
from caracole.db import kv_get_json, kv_set_json
from caracole.logs import plural, provider_name
from caracole.overrides import LYRICS_RECORD_IDS
from caracole.songs import Song

log = logging.getLogger(__name__)

KV = "lyrics-search:"  # + song id: the song's last search (songs._PER_SONG_KV)
PICKABLE_FOR = timedelta(days=7)  # a search may be picked from this long after it was made
MOST_ROWS = 40  # rows a search keeps
FAR = 10.0  # seconds off the audio's length past which a row is listed with its gap (lyrics.fits' second band)
SITES = ("lrclib", "megalobiz", "azlyrics")  # in the order they are asked and listed
# Each site's state in a search, beside its words: it answered with rows or none; or it wasn't asked (turned off,
# cooling down, its hour's, day's or search's asks spent); or it blocked caracole or failed.
ROWS, NONE, OFF, COOLING, SPENT, BLOCKED, FAILED = "rows", "none", "off", "cooling", "spent", "blocked", "failed"
STATES = (ROWS, NONE, OFF, COOLING, SPENT, BLOCKED, FAILED)
ANSWERED = (ROWS, NONE)
NOT_MADE = "; its ask by the exact name not made: "  # LRCLIB's words, between what it listed and why its get wasn't
_AZLYRICS_PAGE = re.compile(r"https://www\.azlyrics\.com/lyrics/([a-z0-9-]+/[a-z0-9-]+)\.html")


@dataclass(frozen=True)
class Row:
    """A record a site listed: ``record`` as ``[lyrics]`` writes it (``lrclib:<id>``, ``megalobiz:<id>``,
    ``azlyrics:<a>/<s>``), its names, album ("" for none) and length (None), whether it is timed, the best fit, and
    whether it fits the typed name."""

    record: str
    site: str
    artist: str
    title: str
    album: str
    duration: float | None
    timed: bool
    best: bool = False
    fits: bool = False

    def as_json(self) -> dict[str, Any]:
        return {"record": self.record, "site": self.site, "artist": self.artist, "title": self.title,
                "album": self.album, "duration": self.duration, "timed": self.timed, "best": self.best,
                "fits": self.fits}


@dataclass(frozen=True)
class Search:
    """A song's search: when, the name asked (``asked``) and the audio's length, LRCLIB's exact query (a pick reads
    its answer from the HTTP cache), the rows, each site's words and its state (``STATES``), and how many records
    marked instrumental weren't listed."""

    at: str
    asked: tuple[str, str]
    length: float | None
    lrclib: dict[str, str]
    rows: tuple[Row, ...]
    said: dict[str, str]
    state: dict[str, str]
    instrumental: int = 0

    @property
    def name(self) -> str:
        return f"{self.asked[0]} - {self.asked[1]}"

    def as_json(self) -> dict[str, Any]:
        return {"at": self.at, "as": list(self.asked), "length": self.length, "lrclib": dict(self.lrclib),
                "rows": [row.as_json() for row in self.rows], "said": dict(self.said), "state": dict(self.state),
                "instrumental": self.instrumental}


def _record(site: str, record_id: Any) -> str | None:
    """``site:id`` for an id of the shape ``[lyrics]`` takes, else None: an id a site gives as a number, a number
    (a ``bool`` is none), AZLyrics' as written."""
    if isinstance(record_id, bool) or not isinstance(record_id, (int, str)):
        return None
    if site != "azlyrics" and not isinstance(record_id, int):
        return None
    text = str(record_id)
    return f"{site}:{text}" if LYRICS_RECORD_IDS[site].fullmatch(text) else None


def typed_name(conn: sqlite3.Connection | None, text: str) -> tuple[str, str] | None:
    """The artist and the title a name typed ("Artist - Title") says, as a search asks the sites under it: read by
    song_names.py's one parser of free text (``conn``, the library's known artists, or None), each part then cleaned
    and capped as ``[lyrics]``' ``as`` is (``lyrics._asked_part``); None for a text that doesn't say who its artist
    is, or a part that cleans to nothing. ``caracole lyrics --as`` reads its name so, and caracole serve's route says
    the name it queues so."""
    import unicodedata

    from caracole.lyrics import _asked_part
    from caracole.song_names import read_names

    kept = "".join(c for c in text if c.isspace() or unicodedata.category(c) != "Cc")
    named = read_names(conn, kept)
    artist, title = (_asked_part(part) for part in named) if named is not None else ("", "")
    return (artist, title) if artist and title else None


def is_own_name(song: Song, name: tuple[str, str]) -> bool:
    """Whether ``name`` is the song's own, by its identity key: then ``[lyrics]`` keeps no ``as``."""
    from caracole.normalize import identity_key

    return identity_key(name[0], name[1]) == song.key


def audio_length(conn: sqlite3.Connection, song: Song) -> float | None:
    """The song's length: its line's, else its YouTube video's, else its audio file's, else None (a hint only)."""
    if song.duration_s is not None:
        return song.duration_s
    from caracole.youtube_fetch import youtube_audio

    video = youtube_audio(conn, song)
    if video is not None and video.duration:
        return float(video.duration)
    if song.audio_path and Path(song.audio_path).is_file():
        from caracole.music import read_audio

        try:
            return read_audio(Path(song.audio_path)).duration_s
        except Exception as e:  # noqa: BLE001 - a length is a hint: the sites are asked without one
            log.info("The length of %s can't be read: %s", song.audio_path, e)
    return None


# --- each site ----------------------------------------------------------------------------------------------------


@dataclass
class _Found:
    rows: list[Row] = field(default_factory=list)
    best: str | None = None  # the record today's rules keep, of this site
    said: str = ""
    instrumental: int = 0
    state: str | None = None  # a state of STATES; None until the asking sets it (ROWS or NONE for an answer)
    after: Exception | None = None  # what stopped a second ask of the site (LRCLIB's get) after its first answered


def _lrclib(client: Any, name: tuple[str, str], length: float | None, query: dict[str, str]) -> _Found:
    from caracole.http import BudgetExhausted, ProviderError
    from caracole.lyrics import Lyrics, fits, get_match, get_params, pick_candidate, search_records

    artist, title = name
    answered = search_records(client, query, max_age=PICKABLE_FOR)
    found = _Found()
    listed: dict[str, Mapping[str, Any]] = {}
    seen: set[Any] = set()

    def take(cand: Any) -> None:
        if not isinstance(cand, Mapping) or repr(cand.get("id")) in seen:
            return
        seen.add(repr(cand.get("id")))
        if not Lyrics.from_record(cand).has_lyrics:
            found.instrumental += 1  # an instrumental record, or one with nothing: counted, never listed
            return
        record = _record("lrclib", cand.get("id"))
        if record is not None:
            listed[record] = cand

    for cand in answered:
        take(cand)
    best = pick_candidate(listed.values(), artist=artist, title=title, duration_s=length)
    if best is None:  # no record of the search fits: LRCLIB's own match of the name, with the audio's length
        try:
            got = get_match(client, get_params(artist, title, album=None, duration_s=length), max_age=PICKABLE_FOR)
        except (ProviderError, BudgetExhausted) as e:  # the search's rows stay; the asking says what stopped it
            got, found.after = None, e
        if got is not None:
            take(got)
            record = _record("lrclib", got.get("id"))
            if record in listed:
                best = listed[record]
    for record, cand in listed.items():
        lyrics = Lyrics.from_record(cand)
        got_artist, got_title = str(cand.get("artistName") or ""), str(cand.get("trackName") or cand.get("name") or "")
        fit = fits(artist=artist, title=title, duration_s=length, got_artist=got_artist, got_title=got_title,
                   got_duration=lyrics.duration)
        album = cand.get("albumName")
        found.rows.append(Row(record, "lrclib", got_artist, got_title, album if isinstance(album, str) else "",
                              lyrics.duration, bool(lyrics.synced), fits=fit is not None))
        if cand is best:
            found.best = record
    return found


def _megalobiz(client: Any, name: tuple[str, str], length: float | None) -> _Found:
    from caracole.http import read_once_more
    from caracole.lyrics import another_version, fits
    from caracole.megalobiz import SEARCH, MegalobizParseError, parse_search, pick_result, search_params

    artist, title = name
    params = search_params(artist, title, length)
    resp = client.get(SEARCH, params=params, max_age=PICKABLE_FOR)
    results = read_once_more(client, resp, SEARCH, parse_search, MegalobizParseError, params=params)
    best = pick_result(results, artist=artist, title=title, duration_s=length)
    found = _Found()
    for result in results:
        record = _record("megalobiz", result.id)
        if record is None or any(row.record == record for row in found.rows):
            continue
        fit = (bool(result.artist.strip()) and not another_version(title, result.title)
               and fits(artist=artist, title=title, duration_s=length, got_artist=result.artist,
                        got_title=result.title, got_duration=result.duration) is not None)
        found.rows.append(Row(record, "megalobiz", result.artist, result.title, "", result.duration, True, fits=fit))
        if result is best:
            found.best = record
    return found


def _azlyrics(client: Any, name: tuple[str, str]) -> _Found:
    from caracole.azlyrics import AzLyricsParseError, artist_url, parse_artist, pick_song
    from caracole.http import read_once_more
    from caracole.lyrics import another_version, fits

    artist, title = name
    url = artist_url(artist)
    found = _Found()
    if url is None:
        found.said = f"no artist page for {artist}"
        return found
    resp = client.get(url, accept=(200, 404), max_age=PICKABLE_FOR)
    if resp.status == 404:
        found.said = f"no artist page for {artist}"
        return found
    page = read_once_more(client, resp, url, parse_artist, AzLyricsParseError, accept=(200, 404))
    best = pick_song(page, artist=artist, title=title)
    for song in page.songs:
        if another_version(title, song.title) or fits(artist=artist, title=title, duration_s=None,
                                                      got_artist=page.name, got_title=song.title,
                                                      got_duration=None) is None:
            continue
        address = _AZLYRICS_PAGE.fullmatch(song.url)
        record = _record("azlyrics", address.group(1)) if address else None
        if record is None or any(row.record == record for row in found.rows):
            continue
        found.rows.append(Row(record, "azlyrics", page.name, song.title, "", None, False, fits=True))
        if song is best:
            found.best = record
    if not found.rows:
        found.said = f"no song titled {title} on {page.name}'s page"
    return found


# --- the search ---------------------------------------------------------------------------------------------------


def search_lyrics(cfg: Config, conn: sqlite3.Connection, song: Song, name: tuple[str, str], *,
                  now: datetime) -> Search:
    """Note ``name`` (artist, title) under the song's ``[lyrics]`` (its ``as``; taken out for the song's own name),
    then ask each lyrics site what it lists under it, and keep the rows (module docstring). The caller holds the
    lock in the lane."""
    from caracole.lyrics import search_query
    from caracole.overrides import set_lyrics_name

    if set_lyrics_name(cfg.overrides_file, song.display, None if is_own_name(song, name) else f"{name[0]} - {name[1]}"):
        ask_anew(conn, song, renamed=True)  # another name holds now: every site is asked under it first
    length = audio_length(conn, song)
    query = search_query(name[0], name[1])
    ask = _Asking(cfg, conn, now)
    finds: dict[str, _Found] = {}
    works: dict[str, Callable[[Any], _Found]] = {
        "lrclib": lambda client: _lrclib(client, name, length, query),
        "megalobiz": lambda client: _megalobiz(client, name, length),
        "azlyrics": lambda client: _azlyrics(client, name),
    }
    for site in SITES:
        if site == "azlyrics":
            from caracole.azlyrics import artist_url

            if artist_url(name[0]) is None:  # a name with no Latin letter or digit: nothing to ask
                finds[site] = _Found(said=f"no artist page for {name[0]}", state=NONE)
                continue
        finds[site] = ask(site, works[site])
    search = Search(at=stamps.stamp(now), asked=(name[0], name[1]), length=length, lrclib=query,
                    rows=_ordered(finds), said={site: _said(finds[site]) for site in SITES},
                    state={site: finds[site].state or NONE for site in SITES},
                    instrumental=sum(f.instrumental for f in finds.values()))
    if conn.execute("SELECT 1 FROM songs WHERE id = ? AND key = ?", (song.id, song.key)).fetchone() is not None:
        kv_set_json(conn, f"{KV}{song.id}", search.as_json())  # never under an id another lookup gave a new song
    return search


def ask_anew(conn: sqlite3.Connection, song: Song, *, renamed: bool = False) -> None:
    """A ``[lyrics]`` entry changed (another name, a record picked or cleared) is a new question, written with the
    entry: the records of LRCLIB's failure and of Megalobiz's and AZLyrics' misses go, so each site is asked under
    what holds now, and a song with no lyrics is pending again with no ``lyrics_at`` (its misses were of the question
    before), so no transcription is offered (transcript.py ``why_not_offered``) until every site answered it. Found
    lyrics are kept (a pick replaces them). ``renamed``, a name changed by a search, which only lists: only a song
    with no answer, pending or missing, is asked anew; found lyrics or an instrumental verdict keep their state and
    their stamps."""
    from caracole.azlyrics_fetch import CHECKED as AZLYRICS_CHECKED
    from caracole.db import kv_delete, savepoint
    from caracole.lyrics import FAILED
    from caracole.megalobiz_fetch import CHECKED as MEGALOBIZ_CHECKED
    from caracole.songs import update_song

    if renamed and song.lyrics_status not in ("pending", "missing"):
        return
    with savepoint(conn, "ask_anew"):
        for prefix in (FAILED, MEGALOBIZ_CHECKED, AZLYRICS_CHECKED):
            kv_delete(conn, f"{prefix}{song.id}")
        if song.lyrics_status != "found":
            update_song(conn, song.id, lyrics_status="pending", lyrics_at=None)


def _said(found: _Found) -> str:
    if found.said:
        return found.said
    return f"listed {len(found.rows)}" if found.rows else "nothing listed"


def _ordered(finds: Mapping[str, _Found]) -> tuple[Row, ...]:
    """The best fit first (LRCLIB's, else Megalobiz's, else AZLyrics'), then the rows that fit, site by site, then
    the rest, each in its site's order; at most ``MOST_ROWS``."""
    best = next((f.best for site in SITES if (f := finds.get(site)) and f.best), None)
    rows = [row for site in SITES for row in finds[site].rows]
    first = [Row(**{**row.as_json(), "best": True}) for row in rows if row.record == best]
    fitting = [row for row in rows if row.fits and row.record != best]
    rest = [row for row in rows if not row.fits and row.record != best]
    return tuple((first + fitting + rest)[:MOST_ROWS])


class _Asking:
    """One site asked, as a lookup asks it: off, cooling down or out of its asks passed over and said; a block cooled
    down (no alert), an error recorded, a good run after its own client's answers; each in its words and state."""

    def __init__(self, cfg: Config, conn: sqlite3.Connection, now: datetime):
        self.cfg, self.conn, self.now = cfg, conn, now

    def __call__(self, site: str, work: Callable[[Any], _Found]) -> _Found:
        from caracole.commands._common import lookup_run_id, make_client
        from caracole.health import get_state, is_cooling, record_ok
        from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError

        name, p = provider_name(site), self.cfg.provider(site)
        if not p.enabled:
            return _Found(said=f"{name} is off (caracole.toml)", state=OFF)
        if is_cooling(self.conn, site, self.now):
            until = stamps.shown(get_state(self.conn, site).cooldown_until)
            return _Found(said=f"waiting out {name} until {until}", state=COOLING)
        client = make_client(self.cfg, self.conn, site, lookup_run_id(self.now), interactive=True)
        try:
            found = work(client)
        except (ProviderError, BudgetExhausted) as e:
            state, said = self._stopped(site, client, e)
            return _Found(said=said, state=state)
        finally:
            client.close()
        # A good run is its own client's answers, never another lookup's of the same second, and never a run that
        # met a block, at any of its requests (a block after an answer is the streak's next strike); an error after
        # an answer is recorded and the run is good all the same, as get.py's envelope records them.
        if client.answered_any() and not isinstance(found.after, ProviderBlocked):
            record_ok(self.conn, site, self.now)
        if found.after is not None:  # a second ask stopped after the first answered: its rows stay, said
            state, said = self._stopped(site, client, found.after)
            listed = f"listed {len(found.rows)}" if found.rows else "nothing listed"
            found.said = f"{listed}{NOT_MADE}{said}"
            found.state = ROWS if found.rows else state
            return found
        found.state = ROWS if found.rows else NONE
        return found

    def _stopped(self, site: str, client: Any, e: Exception) -> tuple[str, str]:
        return stopped(self.cfg, self.conn, self.now, site, client, e)


def stopped(cfg: Config, conn: sqlite3.Connection, now: datetime, site: str, client: Any, e: Exception, *,
            whose: str = "this search's", why: bool = False) -> tuple[str, str]:
    """What stopped a lookup's ask of a site (a block, a spent budget, an error), recorded as a lookup records it, as a
    state of ``STATES`` and words: ``whose`` asks a lookup's budget was ("this pick's"), ``why`` the block's reason
    said too ("LRCLIB turned us back (…); no asks until …")."""
    from caracole.commands._common import requests_today
    from caracole.health import record_block, record_error
    from caracole.http import BudgetExhausted, ProviderBlocked

    name, p = provider_name(site), cfg.provider(site)
    if isinstance(e, ProviderBlocked):
        state = record_block(conn, site, now, str(e))
        reason = f" ({e})" if why else ""
        return BLOCKED, f"{name} turned us back{reason}; no asks until {stamps.shown(state.cooldown_until)}"
    if isinstance(e, BudgetExhausted):
        if p.per_day is not None and requests_today(conn, site, now) >= p.per_day:
            return SPENT, f"no more asks of {name} today ({p.per_day} spent)"
        if client.policy.budget < p.lookup_requests:
            return SPENT, f"no more asks of {name} this hour ({p.lookup_per_hour} spent)"
        return SPENT, f"{whose} {p.lookup_requests} asks of {name} are spent"
    record_error(conn, site, now, str(e))
    return FAILED, f"{name} failed ({e})"


def last_line(search: Search) -> str:
    """The command's last line, which caracole serve's request line reads by its first words: "Searched: " (rows),
    "Nothing found: " (every site asked answered, none with any) or "Not searched: " (no rows, and a site failed,
    waited or couldn't be asked)."""
    quoted = f"“{search.name}”"
    listing = [site for site in SITES if any(row.site == site for row in search.rows)]
    if listing:
        return (f"Searched: {_joined(listing)} {'lists' if len(listing) == 1 else 'list'} "
                f"{plural(len(search.rows), 'record')} for {quoted}.")
    answered = [site for site in SITES if search.state.get(site) in ANSWERED]
    left = [site for site in SITES if site not in answered and search.state.get(site) != OFF]  # a site off isn't asked
    if left:
        why = [search.said.get(site, "").partition(NOT_MADE)[2] or search.said.get(site, "") for site in left]
        return f"Not searched: {'; '.join(why)}; try again later."
    if answered:
        return f"Nothing found: {_joined(answered)} {'lists' if len(answered) == 1 else 'list'} nothing for {quoted}."
    # A guard: no caracole.toml reaches it today, LRCLIB being no switchable provider (config.SWITCHABLE).
    return "Not searched: every lyrics site is off (caracole.toml); nothing asked."


@dataclass(frozen=True)
class Note:
    """A line a search says beside its rows: of a site that listed none (``site``, its ``state``), or the count of the
    records marked instrumental (``site`` "", ``state`` "instrumental")."""

    site: str
    state: str
    line: str


def notes(search: Search) -> tuple[Note, ...]:
    """What the search says of each site that listed no row, in its words (its name kept where they hold it, the first
    letter capitalized, else the name before them; one full stop), then how many instrumental records weren't
    listed: ``caracole lyrics --as``'s lines, and the card's (web/lyrics_routes.py), which composes none."""
    said: list[Note] = []
    for site in SITES:
        if any(row.site == site for row in search.rows):
            continue
        words, who = search.said.get(site, ""), provider_name(site)
        line = f"{words[:1].upper()}{words[1:]}" if who in words else f"{who}: {words}"
        said.append(Note(site, search.state.get(site, NONE), line if line.endswith(".") else f"{line}."))
    if search.instrumental:
        said.append(Note("", "instrumental", f"{plural(search.instrumental, 'record')} marked instrumental "
                                             f"{'isn\'t' if search.instrumental == 1 else 'aren\'t'} listed."))
    return tuple(said)


def far(row: Row, length: float | None) -> bool:
    """Whether a row's record is more than ``FAR`` seconds off the audio's ``length``, so its gap is said."""
    return row.duration is not None and length is not None and abs(row.duration - length) > FAR


def _joined(sites: Any) -> str:
    names = [provider_name(site) for site in sites]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


# --- what is kept -------------------------------------------------------------------------------------------------


def _row(value: Any) -> Row | None:
    """A kept row, read back as strictly as a site's answer: its record of its own site and of ``[lyrics]``' shape."""
    if not isinstance(value, Mapping):
        return None
    site, record = value.get("site"), value.get("record")
    if site not in SITES or not isinstance(record, str) or not record.startswith(f"{site}:"):
        return None
    if not LYRICS_RECORD_IDS[site].fullmatch(record.removeprefix(f"{site}:")):
        return None
    duration = value.get("duration")
    text = {k: value.get(k) if isinstance(value.get(k), str) else "" for k in ("artist", "title", "album")}
    return Row(record, site, text["artist"], text["title"], text["album"],
               float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
               value.get("timed") is True, value.get("best") is True, value.get("fits") is True)


def kept_search(conn: sqlite3.Connection, song_id: int, now: datetime) -> Search | None:
    """The song's last search, while it may be picked from (``PICKABLE_FOR`` after it was made); else None."""
    search = last_search(conn, song_id)
    return search if search is not None and pickable(search, now) else None


def pickable(search: Search, now: datetime) -> bool:
    """Whether ``search`` may still be picked from: made ``PICKABLE_FOR`` ago at most."""
    when = stamps.parse(search.at)
    return when is not None and stamps.utc(now) - when <= PICKABLE_FOR


def last_search(conn: sqlite3.Connection, song_id: int) -> Search | None:
    """The song's last search as kept, however old (caracole serve's card says when, and that an old one is past
    picking from); None for none, or one that won't read."""
    kept = kv_get_json(conn, f"{KV}{song_id}")
    if not isinstance(kept, Mapping):
        return None
    at, asked = kept.get("at"), kept.get("as")
    if not isinstance(at, str) or stamps.parse(at) is None:
        return None
    if not (isinstance(asked, list) and len(asked) == 2 and all(isinstance(part, str) for part in asked)):
        return None
    length, query, said, state = kept.get("length"), kept.get("lrclib"), kept.get("said"), kept.get("state")
    if not isinstance(state, Mapping) or any(state.get(site) not in STATES for site in SITES):
        return None  # a search kept before each site's state was: none to pick from
    rows = tuple(row for row in map(_row, kept.get("rows") if isinstance(kept.get("rows"), list) else []) if row)
    count = kept.get("instrumental")
    return Search(
        at=at, asked=(asked[0], asked[1]),
        length=float(length) if isinstance(length, (int, float)) and not isinstance(length, bool) else None,
        lrclib={k: v for k, v in query.items() if isinstance(v, str)} if isinstance(query, Mapping) else {},
        rows=rows, said={k: v for k, v in said.items() if isinstance(v, str)} if isinstance(said, Mapping) else {},
        state={site: state[site] for site in SITES},
        instrumental=count if isinstance(count, int) and not isinstance(count, bool) else 0)


def row_of(search: Search, record: str) -> Row | None:
    """The row of ``search`` that names ``record``; None for a record it didn't list."""
    return next((row for row in search.rows if row.record == record), None)
