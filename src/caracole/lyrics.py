"""Lyrics from LRCLIB, for every song: the singer's text and the yardstick for sheets.

A lookup asks ``/api/get`` for the song's exact signature first. On a miss it
asks ``/api/search`` once and chooses among the records locally
(``pick_candidate``). Lyrics are saved as ``lyrics.txt`` and, when LRCLIB has
them timed, ``lyrics.lrc``, and stored as JSON in the ``songs`` table.

The nightly pass (``fetch_pending_lyrics``) looks up every song once, through
the forever cache, and asks again about a miss after 30 days, past the cache.

Errors are never misses: whatever the client raises, and any body that is not
the JSON LRCLIB documents, propagates and leaves the song pending. A cached
answer that is not (a maintenance notice served with HTTP 200, say) is asked
for once more before it counts as an error, so one bad night isn't replayed
from the cache every night after.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from rapidfuzz import fuzz

from caracole.http import Client, ProviderError, Response, read_once_more
from caracole.library import song_dir, write_atomic
from caracole.normalize import clean_title, fold, slug_key
from caracole.provider_pass import PassStats, each_song
from caracole.songs import Song, list_songs, update_song

log = logging.getLogger(__name__)

LRCLIB_API = "https://lrclib.net/api"
PROVIDER = "lrclib"

# /api/get answers a miss with 404, or lately with 503 ServerOverloaded (spike).
_GET_ACCEPT = (200, 404, 503)

_TEXT_MATCH = 85  # rapidfuzz ratio, for titles and for artists
_CLOSE_S = 2.0  # the tolerance LRCLIB itself applies on /api/get
_TEXT_MATCH_S = 10.0  # a text match is accepted this far off; beyond it, keys must be equal

_HAN = "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ebef]"
_HAN_GAP = re.compile(rf"(?<={_HAN})[\W_]+(?={_HAN})")

_APOSTROPHES = re.compile(r"['’‘`´ʼ]")
_NON_WORD = re.compile(r"[\W_]+")
_SECTION_HEADER = re.compile(r"\[[^\]]*\]")

# LRC timestamps: [mm:ss.xx] at the start of a line, <mm:ss.xx> before a word.
_LINE_STAMP = re.compile(r"\[(\d+):(\d{2}(?:\.\d+)?)\]")
_LEADING_STAMPS = re.compile(r"(?:\s*\[\d+:\d{2}(?:\.\d+)?\])+")
_WORD_STAMP = re.compile(r"<\d+:\d{2}(?:\.\d+)?>")
# LRC ID tags. Some records carry them in their plain lyrics too (seen live).
_ID_TAG = re.compile(
    r"\[(?:ar|al|ti|au|by|re|ve|la|id|length|offset|tool|#):[^\]]*\]", re.IGNORECASE
)


def _text(value: Any) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else ""


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def synced_lines(synced: str) -> list[tuple[float, str]]:
    """The timed lines of LRC text as ``(seconds, text)``, in time order.

    A line stamped with several times appears once per time. Word timings and
    untimed lines, such as ``[ar:…]`` tags, are dropped.
    """
    timed: list[tuple[float, str]] = []
    for line in _text(synced).split("\n"):
        stamps = _LEADING_STAMPS.match(line)
        if not stamps:
            continue
        text = " ".join(_WORD_STAMP.sub("", line[stamps.end() :]).split())
        for minutes, seconds in _LINE_STAMP.findall(stamps.group()):
            timed.append((int(minutes) * 60 + float(seconds), text))
    timed.sort(key=lambda t: t[0])
    return timed


def _without_id_tags(plain: str) -> str:
    kept = [line for line in plain.split("\n") if not _ID_TAG.fullmatch(line.strip())]
    return "\n".join(kept).strip("\n")


def plain_from_synced(synced: str) -> str:
    """Plain lyrics from LRC text; an empty timed line becomes a break between stanzas."""
    out: list[str] = []
    for _, text in synced_lines(synced):
        if text or (out and out[-1]):
            out.append(text)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


@dataclass(frozen=True)
class Lyrics:
    """A song's lyrics, from one LRCLIB record.

    ``plain`` is "" when there are none (an instrumental, say), ``synced`` is
    LRC text or None, ``duration`` is LRCLIB's in seconds, and ``raw`` is the
    record as LRCLIB sent it.
    """

    plain: str
    synced: str | None
    instrumental: bool
    duration: float | None
    lrclib_id: int | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, hash=False)

    @classmethod
    def from_record(cls, raw: Mapping[str, Any]) -> Lyrics:
        """Read an LRCLIB record.

        Plain lyrics lose any LRC ID tags (``[ti:…]``) and are derived from the
        synced ones when missing.
        """
        synced = _text(raw.get("syncedLyrics"))
        from_synced = plain_from_synced(synced)
        plain = _without_id_tags(_text(raw.get("plainLyrics")))
        return cls(
            plain=plain if plain.strip() else from_synced,
            synced=synced if from_synced else None,
            instrumental=raw.get("instrumental") is True,
            duration=_float(raw.get("duration")),
            lrclib_id=_int(raw.get("id")),
            raw=dict(raw),
        )

    @property
    def has_lyrics(self) -> bool:
        """Whether there is any lyric text at all."""
        return bool(self.plain.strip())

    def to_json(self) -> str:
        """JSON for the ``songs.lyrics_json`` column; ``lyrics_from_json`` reads it back."""
        return json.dumps(
            {
                "plain": self.plain,
                "synced": self.synced,
                "instrumental": self.instrumental,
                "duration": self.duration,
                "lrclib_id": self.lrclib_id,
                "raw": dict(self.raw),
            },
            ensure_ascii=False,
        )


def lyrics_from_json(value: str | Mapping[str, Any] | None) -> Lyrics | None:
    """Read lyrics stored with ``Lyrics.to_json``; None when nothing is stored.

    The value may also be already decoded (a JSON column read as a dict), or a
    bare LRCLIB record, which is read with ``Lyrics.from_record``.
    """
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else None
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"stored lyrics must be a JSON object, not {type(value).__name__}")
    if "raw" not in value or "plain" not in value:
        return Lyrics.from_record(value)
    plain, synced, raw = value["plain"], value.get("synced"), value["raw"]
    return Lyrics(
        plain=plain if isinstance(plain, str) else "",
        synced=synced if isinstance(synced, str) else None,
        instrumental=value.get("instrumental") is True,
        duration=_float(value.get("duration")),
        lrclib_id=_int(value.get("lrclib_id")),
        raw=dict(raw) if isinstance(raw, Mapping) else {},
    )


class HasLyricsJson(Protocol):
    """Anything with a stored ``lyrics_json`` value, such as ``songs.Song``."""

    lyrics_json: str | Mapping[str, Any] | None


def song_lyrics(song: HasLyricsJson) -> Lyrics | None:
    """A song's stored lyrics, read from its ``lyrics_json``; None when there are none."""
    return lyrics_from_json(song.lyrics_json)


def expected_seconds(song: Song) -> float | None:
    """How long the song is: its own duration, else LRCLIB's (a wanted.txt line rarely gives
    one); None when neither is known, or the stored lyrics can't be read."""
    if song.duration_s is not None:
        return song.duration_s
    try:
        lyrics = song_lyrics(song)
    except (TypeError, ValueError):  # stored lyrics that can't be read: no duration
        return None
    return lyrics.duration if lyrics is not None and lyrics.duration else None


def _normalize_line(line: str) -> str:
    return " ".join(_NON_WORD.split(fold(_APOSTROPHES.sub("", line)))).strip()


def lyric_lines(plain: str, *, normalize: Callable[[str], str] | None = None) -> list[str]:
    """The distinct lines of plain lyrics, normalized, in order of first appearance.

    Blank lines and section headers such as ``[Chorus]`` are skipped. The default
    normalization folds accents and case and drops punctuation; pass the coverage
    normalizer instead to compare lines exactly the way sheets are compared.
    """
    norm = normalize or _normalize_line
    seen: set[str] = set()
    lines: list[str] = []
    for line in _text(plain).split("\n"):
        if _SECTION_HEADER.fullmatch(line.strip()):
            continue
        key = norm(line)
        if key and key not in seen:
            seen.add(key)
            lines.append(key)
    return lines


LyricsStatus = Literal["found", "missing", "instrumental"]


@dataclass(frozen=True)
class LyricsResult:
    """The outcome of a lookup. ``lyrics`` is set for found and instrumental songs."""

    status: LyricsStatus
    lyrics: Lyrics | None


class LrclibParseError(ProviderError):
    """An answer from LRCLIB that isn't the JSON it documents: an error, never a miss."""


def _json(resp: Response, shape: type[Mapping] | type[list]) -> Any:
    """The JSON an answer holds, which must be a ``shape``: an object (``Mapping``) or a list."""
    try:
        found = resp.json()
    except (ValueError, RecursionError) as e:  # UnicodeDecodeError too; or nested too deep
        raise LrclibParseError(PROVIDER, resp.url, resp.status, f"unreadable response: {e}") from e
    if not isinstance(found, shape):
        what = "object" if shape is Mapping else "list"
        raise LrclibParseError(PROVIDER, resp.url, resp.status, f"expected a JSON {what}")
    return found


def _get_record(resp: Response) -> Mapping[str, Any] | None:
    """The record ``/api/get`` answered; None for its miss, a 404 or a 503 (whatever its body)."""
    return _json(resp, Mapping) if resp.status == 200 else None


def _outcome(lyrics: Lyrics) -> LyricsResult | None:
    if lyrics.has_lyrics:
        return LyricsResult("found", lyrics)
    if lyrics.instrumental:
        return LyricsResult("instrumental", lyrics)
    return None


def _kind(lyrics: Lyrics) -> int | None:
    """How useful a record is: 0 synced, 1 plain only, 2 instrumental, None empty."""
    if lyrics.synced:
        return 0
    if lyrics.has_lyrics:
        return 1
    return 2 if lyrics.instrumental else None


def _key(name: str) -> str:
    # slug_key drops punctuation, which leaves nothing of names like "!!!" or "?".
    return slug_key(name) or fold(name).strip()


def _artist_matches(want: str, got: str) -> bool:
    return bool(want and got) and (
        fuzz.ratio(want, got) >= _TEXT_MATCH or want in got or got in want
    )


def pick_candidate(
    cands: Iterable[Any], *, artist: str, title: str, duration_s: float | None
) -> Mapping[str, Any] | None:
    """Choose the ``/api/search`` record for a song, or None when none fits.

    A record must match the title (rapidfuzz ``ratio`` ≥ 85 between the
    ``slug_key`` of both cleaned titles), match the artist (``ratio`` ≥ 85
    between the keys, or one key containing the other), and have lyrics or be
    marked instrumental. A name that is only punctuation, such as "!!!", has no
    slug key and is compared as written. When the song's duration is known:

    - records within ±2 s come first, then records within ±10 s;
    - a record more than 10 s off is accepted only when its title and artist
      keys equal the song's (the same song in another cut), and it comes last;
    - inside each of those bands, synced lyrics beat plain ones, plain ones beat
      an instrumental flag, and then the smallest difference wins.

    Without a duration, synced lyrics win. Remaining ties keep LRCLIB's order.
    """
    want_title = _key(clean_title(title))
    want_artist = _key(artist)
    best: Mapping[str, Any] | None = None
    best_rank: tuple[float, ...] | None = None
    for order, cand in enumerate(cands):
        if not isinstance(cand, Mapping):
            continue
        lyrics = Lyrics.from_record(cand)
        kind = _kind(lyrics)
        if kind is None:
            continue
        got_title = _key(clean_title(_text(cand.get("trackName") or cand.get("name"))))
        got_artist = _key(_text(cand.get("artistName")))
        if fuzz.ratio(want_title, got_title) < _TEXT_MATCH:
            continue
        if not _artist_matches(want_artist, got_artist):
            continue
        if duration_s is None:
            rank: tuple[float, ...] = (kind, order)
        else:
            delta = abs(lyrics.duration - duration_s) if lyrics.duration is not None else math.inf
            band = 0 if delta <= _CLOSE_S else 1 if delta <= _TEXT_MATCH_S else 2
            if band == 2 and (got_title, got_artist) != (want_title, want_artist):
                continue
            rank = (band, kind, delta, order)
        if best_rank is None or rank < best_rank:
            best, best_rank = cand, rank
    return best


def _search_title(track: str) -> str:
    # Spotify writes 斑马，斑马 where LRCLIB lists 斑马斑马, the query the spike found
    # it with. /api/search gets the joined form; /api/get keeps the title as written.
    return _HAN_GAP.sub("", track)


def fetch_lyrics(
    client: Client,
    *,
    artist: str,
    title: str,
    album: str | None,
    duration_s: float | None,
    cache: bool = True,
) -> LyricsResult:
    """Look a song up on LRCLIB: ``/api/get`` first, then ``/api/search``.

    ``/api/get`` takes the cleaned title, the artist as written and, when known,
    the album and the duration in whole seconds. A 404 or 503 from it, or a
    record without lyrics, falls back to ``/api/search`` and ``pick_candidate``;
    only an empty or non-matching search result is "missing". Errors raised by
    the client (``ProviderError``, ``BudgetExhausted``) and unreadable bodies
    (``LrclibParseError``) propagate, so the song stays pending: an error is
    never a miss. A cached answer that can't be read is asked for once more,
    past the cache, before it is an error (``http.read_once_more``).

    ``cache`` goes to the first ``client.get`` of each endpoint; the one more ask
    (``read_once_more``) goes past the cache. By default a cached answer is used
    forever; ``cache=False`` asks LRCLIB again.
    """
    track = clean_title(title)
    params: dict[str, str | int] = {"artist_name": artist, "track_name": track}
    if album:
        params["album_name"] = album
    if duration_s is not None:
        params["duration"] = round(duration_s)
    url = f"{LRCLIB_API}/get"
    resp = client.get(url, params=params, accept=_GET_ACCEPT, cache=cache)
    found = read_once_more(client, resp, url, _get_record, LrclibParseError, params=params, accept=_GET_ACCEPT)
    if found is not None:
        outcome = _outcome(Lyrics.from_record(found))
        if outcome is not None:
            return outcome

    url = f"{LRCLIB_API}/search"
    query = {"track_name": _search_title(track), "artist_name": artist}
    resp = client.get(url, params=query, accept=(200,), cache=cache)
    cands = read_once_more(client, resp, url, lambda r: _json(r, list), LrclibParseError, params=query,
                           accept=(200,))
    best = pick_candidate(cands, artist=artist, title=title, duration_s=duration_s)
    outcome = _outcome(Lyrics.from_record(best)) if best is not None else None
    return outcome or LyricsResult("missing", None)


def write_lyrics(song_dir: Path, lyrics: Lyrics) -> list[Path]:
    """Write ``lyrics.txt`` and, when there are synced lyrics, ``lyrics.lrc``.

    Each file ends in a newline and is replaced atomically (``library.write_atomic``,
    which makes the folder). A file these lyrics have no text for is removed, so a
    stale ``lyrics.lrc`` never outlives a re-fetch. Returns the paths written; an
    instrumental writes nothing.
    """
    contents = {
        "lyrics.txt": lyrics.plain if lyrics.has_lyrics else None,
        "lyrics.lrc": lyrics.synced,
    }
    written: list[Path] = []
    for name, text in contents.items():
        path = song_dir / name
        if text:
            write_atomic(path, (text.rstrip("\n") + "\n").encode("utf-8"))
            written.append(path)
        else:
            path.unlink(missing_ok=True)
    return written


# --- the nightly pass ----------------------------------------------------------


@dataclass
class LyricsStats(PassStats):
    """What one ``fetch_pending_lyrics`` pass did: ``tried``, ``errors`` and ``failures`` as
    every pass counts them (provider_pass.py), and what LRCLIB answered."""

    found: int = 0
    missing: int = 0
    instrumental: int = 0


RECHECK_MISSING_AFTER = timedelta(days=30)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _stamp(now: datetime) -> str:
    """``now`` as stored in ``songs.lyrics_at``; naive times are UTC."""
    return _utc(now).strftime("%Y-%m-%dT%H:%M:%SZ")


def _before(stamp: str | None, cutoff: datetime) -> bool:
    """Whether a stored time is older than ``cutoff``; a missing or unreadable one is."""
    try:
        return stamp is None or _utc(datetime.fromisoformat(stamp)) < cutoff
    except ValueError:
        return True


def _songs_to_look_up(conn: sqlite3.Connection, now: datetime, recheck_after: timedelta) -> list[Song]:
    """Songs never looked up, newest first, then misses older than ``recheck_after``: re-checks,
    whose cached answer is the old miss itself."""
    cutoff = _utc(now) - recheck_after
    pending: list[Song] = []
    due: list[Song] = []
    for song in list_songs(conn):
        if song.status == "ignored":
            continue
        if song.lyrics_status == "pending":
            pending.append(song)
        elif song.lyrics_status == "missing" and _before(song.lyrics_at, cutoff):
            due.append(song)
    return pending + due


def fetch_pending_lyrics(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    now: datetime,
    *,
    recheck_missing_after: timedelta = RECHECK_MISSING_AFTER,
    only: Collection[int] | None = None,
) -> LyricsStats:
    """Look up the lyrics of every song that has none yet, newest first (of ``only``'s ids, when given:
    a lookup's one song).

    Ignored songs are skipped. Songs LRCLIB had no lyrics for are asked again
    once their ``lyrics_at`` is older than ``recheck_missing_after``, after the
    songs never looked up. A re-check bypasses the cache (``cache=False``):
    the cached answer is the old miss, and a client that has spent its budget
    may still serve it, so only a real request counts as a re-check.

    Found lyrics are written to the song's folder (``write_lyrics``) and stored
    in ``songs.lyrics_json``; every outcome stores ``lyrics_at``.

    Errors are never misses (provider_pass.py): ``ProviderBlocked`` propagates;
    ``BudgetExhausted`` ends the pass (``budget_exhausted``); any other
    ``ProviderError`` counts in ``errors`` and leaves the song as it was, for the
    next run. Once the client gives up on the provider for this run
    (``ProviderUnavailable``), the pass ends.
    """
    stats = LyricsStats()
    stamp = _stamp(now)

    def turn(song: Song) -> LyricsResult:  # a re-check of a miss goes past the cache
        return fetch_lyrics(client, artist=song.artists[0], title=song.title, album=song.album,
                            duration_s=song.duration_s, cache=song.lyrics_status != "missing")

    songs = (s for s in _songs_to_look_up(conn, now, recheck_missing_after) if only is None or s.id in only)
    for song, result in each_song(songs, stats, turn, site="LRCLIB"):
        _record(conn, library_dir, song, result, stamp)
        if result.status == "found":
            stats.found += 1
        elif result.status == "instrumental":
            stats.instrumental += 1
        else:
            stats.missing += 1
    return stats


def _record(
    conn: sqlite3.Connection, library_dir: Path, song: Song, result: LyricsResult, stamp: str
) -> None:
    """Store one lookup's outcome: the lyric files first, so a failed write leaves it pending."""
    if result.lyrics is None:
        update_song(conn, song.id, lyrics_status=result.status, lyrics_at=stamp)
        return
    write_lyrics(song_dir(library_dir, song), result.lyrics)
    update_song(
        conn, song.id,
        lyrics_status=result.status, lyrics_json=result.lyrics.to_json(), lyrics_at=stamp,
    )
