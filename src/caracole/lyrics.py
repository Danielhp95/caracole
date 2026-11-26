"""Lyrics from LRCLIB, for every song: the singer's text and the yardstick for sheets.

A lookup asks ``/api/get`` for the song's exact signature first. On a miss it
asks ``/api/search`` once and chooses among the records locally
(``pick_candidate``). Lyrics are saved as ``lyrics.txt`` and, when LRCLIB has
them timed, ``lyrics.lrc``, and stored as JSON in the ``songs`` table.

The nightly pass (``fetch_pending_lyrics``) looks up every song once, through
the forever cache, and asks again about a miss after 30 days, past the cache.

``[lyrics]`` (overrides.toml, ``Overrides.lyrics``) changes what is asked, for
the three lyrics sites alike (megalobiz_fetch.py, azlyrics_fetch.py): its ``as``
is the name asked under, with no album (``asked_as``); its ``record`` the record
you picked, final: only its own site asks about the song, only that record, and
only while the song has no lyrics (``picked_record``, ``picked_due``); LRCLIB's
by its id, ``/api/get/{id}`` (``fetch_lrclib_record``). The record gone is that
site's miss, and the song's lyrics are then missing, asked again after 30 days.

Errors are never misses: whatever the client raises, and any body that is not
the JSON LRCLIB documents, propagates and leaves the song pending. A cached
answer that is not (a maintenance notice served with HTTP 200, say) is asked
for once more before it counts as an error, so one bad night isn't replayed
from the cache every night after. A 503 from either endpoint is LRCLIB's
ServerOverloaded, "temporarily busy" as its docs say: an error, never a miss.
The client asks once more after its ``Retry-After`` (``http.RETRY_AFTER_503``),
within the run's budget and pace, or a lookup's.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from rapidfuzz import fuzz

from caracole import stamps
from caracole.db import kv_delete, kv_set
from caracole.http import Client, ProviderError, Response, read_once_more
from caracole.library import song_dir, write_atomic
from caracole.normalize import clean_title, fold, slug_key
from caracole.overrides import override_key
from caracole.provider_pass import PassStats, as_now, each_song
from caracole.songs import Song, list_songs, update_song

if TYPE_CHECKING:
    from caracole.overrides import LyricsPick, LyricsRecord

log = logging.getLogger(__name__)

LRCLIB_API = "https://lrclib.net/api"
PROVIDER = "lrclib"

# /api/get answers a miss with 404 TrackNotFound. Its 503 is ServerOverloaded, busy, which the client asks once more
# after its Retry-After and is an error then: never a miss (the spike of 2026-10-18 took one for a miss, wrongly).
_GET_ACCEPT = (200, 404)

_TEXT_MATCH = 85  # rapidfuzz ratio, for titles and for artists
_CLOSE_S = 2.0  # the tolerance LRCLIB itself applies on /api/get
_TEXT_MATCH_S = 10.0  # a text match is accepted this far off; beyond it, keys must be equal

_HAN = "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ebef]"
_HAN_GAP = re.compile(rf"(?<={_HAN})[\W_]+(?={_HAN})")
_CJK_MARKS = re.compile("[「」『』【】《》〈〉〖〗〔〕]")

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
    """A song's lyrics, from one record of one provider.

    ``plain`` is "" when there are none (an instrumental, say), ``synced`` is
    LRC text or None, ``duration`` is the record's in seconds, and ``raw`` is the
    record as the provider sent it (Megalobiz's without its lyrics: they are in
    ``synced``). ``provider`` is who answered, LRCLIB's, Megalobiz's
    (megalobiz_fetch.py) or AZLyrics' (azlyrics_fetch.py), and ``url`` the record's
    page, which caracole links to wherever it credits them (Megalobiz's fair use
    asks it, and AZLyrics' is credited the same way; LRCLIB's have none).
    """

    plain: str
    synced: str | None
    instrumental: bool
    duration: float | None
    lrclib_id: int | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, hash=False)
    provider: str = PROVIDER
    url: str | None = None

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
                "provider": self.provider,
                "url": self.url,
            },
            ensure_ascii=False,
        )


def lyrics_from_json(value: str | Mapping[str, Any] | None) -> Lyrics | None:
    """Read lyrics stored with ``Lyrics.to_json``; None when nothing is stored.

    The value may also be already decoded (a JSON column read as a dict), or a
    bare LRCLIB record, which is read with ``Lyrics.from_record``. Lyrics stored
    before they named their provider are LRCLIB's.
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
    provider, url = value.get("provider"), value.get("url")
    return Lyrics(
        plain=plain if isinstance(plain, str) else "",
        synced=synced if isinstance(synced, str) else None,
        instrumental=value.get("instrumental") is True,
        duration=_float(value.get("duration")),
        lrclib_id=_int(value.get("lrclib_id")),
        raw=dict(raw) if isinstance(raw, Mapping) else {},
        provider=provider if isinstance(provider, str) and provider else PROVIDER,
        url=url if isinstance(url, str) and url else None,
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
    """The record ``/api/get`` answered; None for its miss, a 404 (whatever its body)."""
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


# Words of a title that make it another kind of version than the song's (a fan's cover, a karaoke track, a vocal
# version of an instrumental), unless the song's own title says them too.
_OTHER_VERSION = re.compile(
    r"\b(cover|karaoke|instrumental|acapella|a cappella|nightcore|sped up|slowed|8d|vocals?|remix)\b")


def another_version(want: str, got: str) -> bool:
    """Whether ``got``'s title names a kind of version (a cover, a karaoke track) the song's title ``want`` doesn't."""
    named = set(_OTHER_VERSION.findall(fold(want).lower()))
    return any(word not in named for word in _OTHER_VERSION.findall(fold(got).lower()))


def fits(*, artist: str, title: str, duration_s: float | None, got_artist: str, got_title: str,
         got_duration: float | None) -> tuple[int, float] | None:
    """Whether a record (``got_*``) is the song, by ``pick_candidate``'s rules, which another provider's picker
    keeps too (megalobiz.py, azlyrics.py): None when it isn't; else its band, 0 within ±2 s of the song's duration, 1 within
    ±10 s, 2 beyond (only for a record whose title and artist keys equal the song's), and how far off it is (0, 0.0
    when the song's duration isn't known)."""
    want_title, want_artist = _key(clean_title(title)), _key(artist)
    got_t, got_a = _key(clean_title(got_title)), _key(got_artist)
    if fuzz.ratio(want_title, got_t) < _TEXT_MATCH or not _artist_matches(want_artist, got_a):
        return None
    if duration_s is None:
        return 0, 0.0
    delta = abs(got_duration - duration_s) if got_duration is not None else math.inf
    band = 0 if delta <= _CLOSE_S else 1 if delta <= _TEXT_MATCH_S else 2
    if band == 2 and (got_t, got_a) != (want_title, want_artist):
        return None
    return band, delta


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
    best: Mapping[str, Any] | None = None
    best_rank: tuple[float, ...] | None = None
    for order, cand in enumerate(cands):
        if not isinstance(cand, Mapping):
            continue
        lyrics = Lyrics.from_record(cand)
        kind = _kind(lyrics)
        if kind is None:
            continue
        fit = fits(artist=artist, title=title, duration_s=duration_s, got_artist=_text(cand.get("artistName")),
                   got_title=_text(cand.get("trackName") or cand.get("name")), got_duration=lyrics.duration)
        if fit is None:
            continue
        band, delta = fit
        rank: tuple[float, ...] = (kind, order) if duration_s is None else (band, kind, delta, order)
        if best_rank is None or rank < best_rank:
            best, best_rank = cand, rank
    return best


def _search_title(track: str) -> str:
    # A wanted.txt line may write 斑马，斑马 where LRCLIB lists 斑马斑马, the query the spike found it
    # with. /api/search gets the joined form; /api/get keeps the title as written. A CJK bracket is
    # punctuation to LRCLIB's search: each becomes a gap first, so a gap never takes one mark and leaves its pair.
    if _CJK_MARKS.search(track):
        track = " ".join(_CJK_MARKS.sub(" ", track).split())
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
    the album and the duration in whole seconds. A 404 from it, or a record
    without lyrics, falls back to ``/api/search`` and ``pick_candidate``; only
    an empty or non-matching search result is "missing". Errors raised by the
    client (``ProviderError``, a 503 among them once its retry is spent;
    ``BudgetExhausted``) and unreadable bodies (``LrclibParseError``) propagate,
    so the song stays pending: an error is never a miss. A cached answer that
    can't be read is asked for once more, past the cache, before it is an error
    (``http.read_once_more``).

    ``cache`` goes to the first ``client.get`` of each endpoint; the one more ask
    (``read_once_more``) goes past the cache. By default a cached answer is used
    forever; ``cache=False`` asks LRCLIB again.
    """
    found = get_match(client, get_params(artist, title, album=album, duration_s=duration_s), cache=cache)
    if found is not None:
        outcome = _outcome(Lyrics.from_record(found))
        if outcome is not None:
            return outcome

    cands = search_records(client, search_query(artist, title), cache=cache)
    best = pick_candidate(cands, artist=artist, title=title, duration_s=duration_s)
    outcome = _outcome(Lyrics.from_record(best)) if best is not None else None
    return outcome or LyricsResult("missing", None)


def _aged(max_age: timedelta | None) -> dict[str, timedelta]:
    """``max_age`` for a client's ``get`` only when it is given: a client of the tests' that takes none still asks."""
    return {} if max_age is None else {"max_age": max_age}


def get_params(artist: str, title: str, *, album: str | None, duration_s: float | None) -> dict[str, str | int]:
    """What ``/api/get`` is sent for a song: its cleaned title, its artist as written and, when known, its album and
    its length in whole seconds."""
    params: dict[str, str | int] = {"artist_name": artist, "track_name": clean_title(title)}
    if album:
        params["album_name"] = album
    if duration_s is not None:
        params["duration"] = round(duration_s)
    return params


def search_query(artist: str, title: str) -> dict[str, str]:
    """What ``/api/search`` is sent for a song: its cleaned title as LRCLIB's search reads it (``_search_title``)
    and its artist as written."""
    return {"track_name": _search_title(clean_title(title)), "artist_name": artist}


def get_match(client: Client, params: Mapping[str, str | int], *, cache: bool = True,
              max_age: timedelta | None = None) -> Mapping[str, Any] | None:
    """``/api/get``'s record for ``params`` (``get_params``), or None for its miss; a cached answer that can't be
    read asked for once more, past the cache. ``cache`` and ``max_age`` go to the first request."""
    url = f"{LRCLIB_API}/get"
    resp = client.get(url, params=params, accept=_GET_ACCEPT, cache=cache, **_aged(max_age))
    return read_once_more(client, resp, url, _get_record, LrclibParseError, params=params, accept=_GET_ACCEPT)


def search_records(client: Client, query: Mapping[str, str], *, cache: bool = True,
                   max_age: timedelta | None = None) -> list[Any]:
    """``/api/search``'s records for ``query`` (``search_query``), in its order, as fetch_lyrics' fallback reads
    them; ``cache`` and ``max_age`` go to the first request."""
    url = f"{LRCLIB_API}/search"
    resp = client.get(url, params=query, accept=(200,), cache=cache, **_aged(max_age))
    return read_once_more(client, resp, url, lambda r: _json(r, list), LrclibParseError, params=query,
                          accept=(200,))


def fetch_lrclib_record(client: Client, lrclib_id: int, *, cache: bool = True) -> Lyrics | None:
    """A record of LRCLIB's by its id, ``/api/get/{id}``: the record you picked (``[lyrics]``), or None when it is
    gone (its 404). Its lyrics as ``Lyrics.from_record`` reads them, which may be none (``_outcome`` says what they
    come to). Errors propagate as ``fetch_lyrics``' do; ``cache`` goes to the first request."""
    url = f"{LRCLIB_API}/get/{lrclib_id}"
    resp = client.get(url, accept=_GET_ACCEPT, cache=cache)
    found = read_once_more(client, resp, url, _get_record, LrclibParseError, accept=_GET_ACCEPT)
    return Lyrics.from_record(found) if found is not None else None


# --- [lyrics]: the name asked under, the record picked ----------------------------------------------------------------

ASKED_MOST = 200  # characters of each part of [lyrics]' ``as`` the sites are asked, as many as its search takes
_INVISIBLE = "\u200b\u200e\u200f\ufeff"  # wanted.py's: stray zero-width characters at a name's ends


def _asked_part(text: str) -> str:
    """An artist's or a title's name from ``as`` as the sites are asked it, as a wanted.txt line's names are read
    (NFC, its spaces folded into one, no zero-width character at its ends) and more, since ``as`` is only split and
    stripped: a newline or a tab one space, any other control character dropped, at most ``ASKED_MOST`` characters;
    "" for one of none of these."""
    kept = "".join(c for c in unicodedata.normalize("NFC", text) if c.isspace() or unicodedata.category(c) != "Cc")
    name = " ".join(kept.split()).strip(_INVISIBLE).strip()
    return name[:ASKED_MOST].strip()


def _pick(song: Song, picks: Mapping[str, LyricsPick] | None) -> LyricsPick | None:
    return picks.get(override_key(song.display)) if picks else None


def asked_as(song: Song, picks: Mapping[str, LyricsPick] | None) -> tuple[str, str, str | None]:
    """The artist, title and album the lyrics sites are asked under: ``[lyrics]``' ``as`` of the song in ``picks``
    (``Overrides.lyrics``), cleaned (``_asked_part``), with no album; else, or for an ``as`` that cleans to nothing,
    the song's own first artist, title and album."""
    pick = _pick(song, picks)
    if pick is not None and pick.asked is not None:
        artist, title = (_asked_part(part) for part in pick.asked)
        if artist and title:
            return artist, title, None
    return song.artists[0], song.title, song.album


def picked_record(song: Song, picks: Mapping[str, LyricsPick] | None) -> LyricsRecord | None:
    """The record you picked for the song (``[lyrics]``' ``record``), or None."""
    pick = _pick(song, picks)
    return pick.record if pick is not None else None


def asked_name(song: Song, picks: Mapping[str, LyricsPick] | None) -> str | None:
    """"Artist - Title", the name ``asked_as`` gives when it isn't the song's own (``[lyrics]``' ``as``), else None."""
    artist, title, album = asked_as(song, picks)
    return None if (artist, title, album) == (song.artists[0], song.title, song.album) else f"{artist} - {title}"


def said_under(said: str, name: str | None) -> str:
    """A lookup's lyrics stage in its words, the name its sites were asked under said once, first, when it isn't the
    song's own (``asked_name``) and a site was asked under it: "under “A - T”: LRCLIB has none; …"."""
    return said if name is None else f"under “{name}”: {said}"


PAGE_NAMED = " (the page you named)"  # after AZLyrics' words, for a page [azlyrics] names while a [lyrics] name holds


def picked_said(record: LyricsRecord, *, kept: bool, gone: bool) -> str:
    """What a lookup says of the record you picked, its site's pass done: kept, gone (the pass's log line's words), or
    not asked now (within 30 days of its miss, or its site off)."""
    said = f"{record.site} {record.id}"
    if kept:
        return f"the record you picked: {said}"
    if gone:
        return f"the record you picked is gone: {said}"
    return f"the record you picked isn't asked now: {said}"


def picked_due(song: Song, now: datetime, recheck_after: timedelta = timedelta(days=30)) -> bool:
    """Whether a song with a picked record is asked for it, by its site alone: while it has no lyrics, pending (a
    rebuilt library, an entry written by hand, an error), or missing (the record gone) for ``recheck_after``."""
    if song.status == "ignored":
        return False
    return song.lyrics_status == "pending" or (
        song.lyrics_status == "missing" and stamps.before(song.lyrics_at, stamps.utc(now) - recheck_after))


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
# + song id: when LRCLIB's last lookup of the song failed, an error or the pass given up before it, kept until LRCLIB
# answers about it; Megalobiz and AZLyrics ask about such a song (megalobiz_fetch.py, azlyrics_fetch.py), never one
# LRCLIB hasn't been asked about.
FAILED = "lyrics:failed:"


def _songs_to_look_up(conn: sqlite3.Connection, now: datetime, recheck_after: timedelta,
                      picks: Mapping[str, LyricsPick] | None = None) -> list[Song]:
    """Songs never looked up, newest first, then misses older than ``recheck_after``: re-checks,
    whose cached answer is the old miss itself."""
    pending: list[Song] = []
    due: list[Song] = []
    for song in list_songs(conn):
        if _due(song, now, recheck_after, picks):
            (pending if song.lyrics_status == "pending" else due).append(song)
    return pending + due


def _due(song: Song, now: datetime, recheck_after: timedelta,
         picks: Mapping[str, LyricsPick] | None = None) -> bool:
    """Whether ``_songs_to_look_up`` lists the song: a song with a record picked on another site never."""
    if song.status == "ignored":
        return False
    record = picked_record(song, picks)
    if record is not None and record.site != PROVIDER:
        return False
    return song.lyrics_status == "pending" or (
        song.lyrics_status == "missing" and stamps.before(song.lyrics_at, stamps.utc(now) - recheck_after))


def fetch_pending_lyrics(
    conn: sqlite3.Connection,
    client: Client,
    library_dir: Path,
    now: datetime,
    *,
    recheck_missing_after: timedelta = RECHECK_MISSING_AFTER,
    only: Collection[int] | None = None,
    durations: Mapping[int, float] | None = None,
    picks: Mapping[str, LyricsPick] | None = None,
) -> LyricsStats:
    """Look up the lyrics of every song that has none yet, newest first (of ``only``'s ids, when given:
    a lookup's one song). ``durations``: a length in seconds by song id, for a song whose line gives
    none (a sheet from a YouTube video asks with its audio's, so the timed lyrics LRCLIB gives fit it).
    ``picks``, ``Overrides.lyrics``: a song is asked under its ``as`` (``asked_as``); one whose picked
    record is LRCLIB's is asked for that record alone (``fetch_lrclib_record``, its 404 a miss), and one
    whose record is another site's is passed over. Without it, every request is what it was.

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
    (``ProviderUnavailable``), the pass ends. Every song an error left
    (``failures``) is remembered for the sites after it (kv ``lyrics:failed:``, ``FAILED``)
    until LRCLIB answers about it.
    """
    stats = LyricsStats()
    stamp = stamps.stamp(now)

    def turn(song: Song) -> LyricsResult:  # a re-check of a miss goes past the cache
        cache = song.lyrics_status != "missing"
        record = picked_record(song, picks)
        if record is not None:
            found = fetch_lrclib_record(client, int(record.id), cache=cache)
            return (_outcome(found) if found is not None else None) or LyricsResult("missing", None)
        duration = song.duration_s if song.duration_s is not None else (durations or {}).get(song.id)
        artist, title, album = asked_as(song, picks)
        return fetch_lyrics(client, artist=artist, title=title, album=album, duration_s=duration, cache=cache)

    listed = (s for s in _songs_to_look_up(conn, now, recheck_missing_after, picks) if only is None or s.id in only)
    songs = as_now(conn, listed, lambda song: _due(song, now, recheck_missing_after, picks))
    for song, result in each_song(songs, stats, turn, site="LRCLIB"):
        record = picked_record(song, picks)
        if record is not None and result.status == "missing":
            log.info("%s: the record you picked is gone: lrclib %s", song.display, record.id)
        _record(conn, library_dir, song, result, stamp)
        kv_delete(conn, f"{FAILED}{song.id}")
        if result.status == "found":
            stats.found += 1
        elif result.status == "instrumental":
            stats.instrumental += 1
        else:
            stats.missing += 1
    for song, _ in stats.failures:
        kv_set(conn, f"{FAILED}{song.id}", stamp)
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
