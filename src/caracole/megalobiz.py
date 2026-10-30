"""Megalobiz's public API: timed lyrics for a song LRCLIB has none of, or none timed (megalobiz_fetch.py).

``https://api.megalobiz.com/api/public/v1``, official and documented, free, with no key and no cookie: 30 requests a
minute and 1,000 a day from one address (its ``X-RateLimit-*`` headers count both). Its fair use, which caracole
keeps: look up only the songs people play (your wanted.txt's and a lookup's, never a mirror), cache what it answers,
personal and non-commercial use, a link back to each record's page wherever its lyrics are shown (``Lrc.url``: the
library page's Lyrics tile, info.json), and a user agent naming the app (caracole's own, as every site). Asked by hand
on 2026-10-30 with caracole's user agent: its API host has no robots.txt (404), megalobiz.com's allows every page but
its accounts and editors (tests/fixtures/megalobiz/robots.txt, ``http.ROBOTS_DISALLOW``), and the site's old HTML
search, ``/search/all``, answers 410 and is never asked.

- ``/search?title=&artist=&duration=&limit=`` answers ``{query, count, results}``, each result a record's ``id``,
  ``title``, ``artist`` (sometimes empty: a fan's upload), ``duration`` in seconds, ``score`` and ``url`` (its page on
  megalobiz.com). A song it lacks is ``count`` 0, or no result that fits (``pick_result``): it ranks other songs of
  the artist, or other artists' songs of the title, among them.
- ``/lrc/{id}`` answers the record: its ``lines`` (``time_ms``, ``text``) and its ``lrc`` text (``[ar:]``, ``[ti:]``,
  ``[length:]``, ``[re:Megalobiz]`` tags, then a stamped line each), every record synced by hand (``sync``
  "manual"); 404 for one gone.
- A 429 (with ``Retry-After``) is a block, as every site's (http.py). It never says a record is instrumental.

Pure: no client, no database. Whatever doesn't read as documented is a ``MegalobizParseError``: an error, never a
miss.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from caracole.http import ProviderError, Response
from caracole.lyrics import another_version, fits
from caracole.normalize import clean_title

PROVIDER = "megalobiz"
API = "https://api.megalobiz.com/api/public/v1"
SEARCH = f"{API}/search"
SITE = "https://megalobiz.com/"  # where every record's page is, which caracole links back to
LIMIT = 10  # results a search asks for

_STAMPED = re.compile(r"^\s*\[\d+:\d{2}(?:\.\d+)?\]", re.MULTILINE)


class MegalobizParseError(ProviderError):
    """An answer from Megalobiz that isn't the JSON it documents: an error, never a miss."""


@dataclass(frozen=True)
class Result:
    """One result of a search: a record's id, its title and artist as written, its length in seconds (None when not
    given) and its page on megalobiz.com."""

    id: int
    title: str
    artist: str
    duration: float | None
    url: str


@dataclass(frozen=True)
class Lrc:
    """A record's timed lyrics: ``lrc`` its LRC text ("" for a record with no timed line), and the record's names,
    length and page."""

    id: int
    title: str
    artist: str
    duration: float | None
    url: str
    lrc: str


def search_params(artist: str, title: str, duration_s: float | None) -> dict[str, str | int]:
    """What a search for a song sends: its cleaned title, its artist as written and, when known, its length in whole
    seconds."""
    params: dict[str, str | int] = {"title": clean_title(title), "artist": artist}
    if duration_s is not None:
        params["duration"] = round(duration_s)
    params["limit"] = LIMIT
    return params


def lrc_url(lrc_id: int) -> str:
    """A record's address under the API."""
    return f"{API}/lrc/{lrc_id}"


def _object(resp: Response) -> Mapping[str, Any]:
    try:
        found = resp.json()
    except (ValueError, RecursionError) as e:  # UnicodeDecodeError too; or nested too deep
        raise MegalobizParseError(PROVIDER, resp.url, resp.status, f"unreadable response: {e}") from e
    if not isinstance(found, Mapping):
        raise MegalobizParseError(PROVIDER, resp.url, resp.status, "expected a JSON object")
    return found


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _record(resp: Response, data: Mapping[str, Any]) -> tuple[int, str, str, float | None, str]:
    """A record's id, title, artist, length and page, as a search's result or ``/lrc/`` gives them."""
    lrc_id, url = data.get("id"), data.get("url")
    if not isinstance(lrc_id, int) or isinstance(lrc_id, bool):
        raise MegalobizParseError(PROVIDER, resp.url, resp.status, f"a record without a numeric id: {lrc_id!r}")
    if not isinstance(url, str) or not url.startswith(SITE):
        raise MegalobizParseError(PROVIDER, resp.url, resp.status, f"record {lrc_id}'s page isn't on {SITE}: {url!r}")
    title, artist = data.get("title"), data.get("artist")
    return (lrc_id, title if isinstance(title, str) else "", artist if isinstance(artist, str) else "",
            _number(data.get("duration")), url)


def parse_search(resp: Response) -> list[Result]:
    """The results of a search, in its order."""
    data = _object(resp)
    found = data.get("results")
    if not isinstance(found, list):
        raise MegalobizParseError(PROVIDER, resp.url, resp.status, "a search without a list of results")
    out = []
    for item in found:
        if not isinstance(item, Mapping):
            raise MegalobizParseError(PROVIDER, resp.url, resp.status, "a result that isn't an object")
        out.append(Result(*_record(resp, item)))
    return out


def _from_lines(lines: list[Any]) -> str:
    """LRC text from a record's ``lines``, ``[mm:ss.xx]`` before each line's text."""
    out = []
    for line in lines:
        if not isinstance(line, Mapping) or not isinstance(line.get("time_ms"), int):
            continue
        ms, text = line["time_ms"], line.get("text")
        out.append(f"[{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}]{text if isinstance(text, str) else ''}")
    return "\n".join(out)


def parse_lrc(resp: Response) -> Lrc:
    """A record's timed lyrics: its ``lrc`` text, else made from its ``lines``; "" when it has no timed line."""
    data = _object(resp)
    text, lines = data.get("lrc"), data.get("lines")
    if not isinstance(text, str) and not isinstance(lines, list):
        raise MegalobizParseError(PROVIDER, resp.url, resp.status, "a record with neither lrc text nor lines")
    lrc = text.replace("\r\n", "\n") if isinstance(text, str) else ""
    if not _STAMPED.search(lrc):
        lrc = _from_lines(lines) if isinstance(lines, list) else ""
    return Lrc(*_record(resp, data), lrc=lrc if _STAMPED.search(lrc) else "")


def pick_result(results: Iterable[Result], *, artist: str, title: str, duration_s: float | None) -> Result | None:
    """The result that is the song, or None when none is: its title and artist fit as ``lyrics.pick_candidate``'s
    do (``lyrics.fits``: the keys' ratio at least 85, the closest length first within ±2 s, then ±10 s, beyond that
    only the same names), credited to someone, and no other kind of version than the song (a cover, a karaoke or an
    instrumental track, a vocal version, a remix: ``lyrics.another_version``). Without the song's length, the first that
    fits, in the search's order."""
    best: Result | None = None
    best_rank: tuple[float, ...] | None = None
    for order, result in enumerate(results):
        if not result.artist.strip() or another_version(title, result.title):
            continue
        fit = fits(artist=artist, title=title, duration_s=duration_s, got_artist=result.artist,
                   got_title=result.title, got_duration=result.duration)
        if fit is None:
            continue
        rank = (*fit, order)
        if best_rank is None or rank < best_rank:
            best, best_rank = result, rank
    return best


def record_json(lrc: Lrc) -> dict[str, Any]:
    """What caracole stores of a record, as ``Lyrics.raw``: its names, length and page, never its lyrics twice."""
    return {"id": lrc.id, "title": lrc.title, "artist": lrc.artist, "duration": lrc.duration, "url": lrc.url}
