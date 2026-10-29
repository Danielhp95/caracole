"""A YouTube video suggested for a search: ``caracole youtube --search QUERY``, which caracole serve's library page
sends by itself once a query has settled with no sheet for it on the sites.

YouTube's first result for the query (yt-dlp's ``ytsearch1:``, metadata alone, no download) is offered beside the
results as a sheet to make from it: its thumbnail, title, channel and length, and "Make the sheet from it", which
fills the request form in with the query and the video for you to send (web/youtube_routes.py, youtube_sheet.py).
It is the owner's explicit choice, on 2026-10-29, and a second exception to "a search reads the local indexes
alone" (LaCuerda's own search is the first), on the YouTube exception's terms (AGENTS.md, youtube.py):

- **One yt-dlp run** a search, through ``make_youtube``: the lock, the pause from the youtube provider's ``delay``
  after the last run any caracole made, ``--retries 0``, an environment of its own, no cookies, login, config,
  plugins or remote code, ``--flat-playlist --dump-single-json`` of ``ytsearch1:`` with the query after ``--``
  (``YtDlp.search``): one result's metadata, never a download, never a playlist's page. A bot check, a 429 or
  a 403 is ``ProviderBlocked``: the cooldown, and one ntfy alert.
- **Its thumbnail**, once a video, right after the search: ``https://i.ytimg.com/vi/<id>/hqdefault.jpg``, one
  request through a ``PoliteClient`` of provider ``ytimg`` (``THUMBS_PROVIDER``), YouTube's image host, with no pause
  by the owner's choice (config.py), never while it cools down after a block of its own, nor when turned off; its
  robots.txt honoured (i.ytimg.com closes ``/sb/`` alone, http.py ``ROBOTS_DISALLOW``), its answer cached forever,
  so a video's thumbnail is never asked twice; kept only when its bytes are a JPEG (``checked_jpeg``: its
  segments walked to the image, a size of 1 to ``MAX_SIDE`` pixels a side, ``MAX_BYTES`` at most), in
  ``cache_dir/youtube-thumbs/<id>.jpg``, never in the library; caracole serve sends it (``GET /youtube/thumb/``).
- **When** (``gate``, read with no request and no lock): only where this caracole can make a sheet from the video
  (``youtube_fetch.route_problem``), and only for a query the search's answer has no sheet for
  (``sheet_on_screen``); a query (its words' key) at most once in ``ASKED_FOR`` (30 days, kv
  ``youtube-search:<key>``, which keeps what it found, so the suggestion comes back with no request); at most
  ``SEARCHES_PER_HOUR`` searches in the last hour (their runs in ``events``, named ``youtube-search:…``); none
  while YouTube cools down after a block; none of a query whose search failed within ``FAILED_FOR`` (an hour),
  and none at all for that hour once ``FAILURES_PAUSE`` (3) did (kv ``youtube-search:failed``).

Errors are never misses: a block, a spent budget or an error records nothing found, and the query may be searched
again; an error is remembered for the hour above. A thumbnail that can't be had leaves the video suggested without
one. caracole get never runs it: it is a command of its own, queued by the page (web/jobs.py).
"""

from __future__ import annotations

import os
import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from caracole import stamps
from caracole.db import kv_get_json, kv_set_json

if TYPE_CHECKING:
    from collections.abc import Sequence

    from caracole.config import Config
    from caracole.http import Client
    from caracole.search import IndexFound, LibraryHit, SiteArtist, SiteHit
    from caracole.youtube import Video, YtDlp

PROVIDER = "youtube"
THUMBS_PROVIDER = "ytimg"  # YouTube's image host: a provider of its own, with no pause (config.py)
SEARCHES_PER_HOUR = 10  # the page's searches of YouTube in the last hour, at most
ASKED_FOR = timedelta(days=30)  # a query searched once in this long
FAILED_FOR = timedelta(hours=1)  # a search that failed: not sent again for this long
FAILURES_PAUSE = 3  # searches failed within FAILED_FOR that stop every search for that long
RUN = "youtube-search:"  # how a search's run is named in events
KV_PREFIX = "youtube-search:"  # + the query's key: when it was searched, and the video it found
FAILED_KEY = "youtube-search:failed"  # {query's key: {"at", "error"}}, those of the last FAILED_FOR
ERROR_CHARS = 200
STATES = ("found", "none", "auto", "failed", "spent")
THUMB_URL = "https://i.ytimg.com/vi/{id}/hqdefault.jpg"  # 480 × 360
THUMBS = "youtube-thumbs"  # in cache_dir: never cache_dir/youtube/, whose files tidy() lets go of
MAX_BYTES = 256 * 1024
MAX_SIDE = 2048


def query_key(query: str) -> str:
    """The query's words, in alphabetical order, hyphenated ("cani-nick-veganos-vikingos"); "" for none."""
    from caracole.normalize import name_words

    return "-".join(sorted(name_words(query)))


def sheet_on_screen(mine: Sequence[LibraryHit], index: IndexFound, lc_artists: Sequence[SiteArtist],
                    lc_songs: Sequence[SiteHit]) -> bool:
    """Whether a search's answer has a sheet for the query already, or names an artist rather than a song, so that
    no video is suggested: a strong song of your library by its title, a strong song of Ultimate Guitar's index or a
    strong song of LaCuerda's with chords, or an artist either names whole."""
    from caracole.search import STRONG

    return (any(h.score >= STRONG and h.via != "artist" for h in mine)
            or any(h.score >= STRONG for h in index.songs)
            or any(a.score >= STRONG and not a.part for a in index.artists)
            or any(h.score >= STRONG and h.sheet for h in lc_songs)
            or any(a.score >= STRONG and not a.part for a in lc_artists))


def searched(conn: sqlite3.Connection, key: str, now: datetime) -> dict[str, Any] | None:
    """What the search of ``key`` found when it was made within ``ASKED_FOR`` (``at``, ``video``: its fields, or
    None for none, and ``thumb``: whether its thumbnail is kept); None when it wasn't."""
    said = kv_get_json(conn, KV_PREFIX + key) if key else None
    if not isinstance(said, dict) or stamps.before(said.get("at"), stamps.utc(now) - ASKED_FOR):
        return None
    return said


def _failures(conn: sqlite3.Connection, now: datetime) -> dict[str, dict[str, str]]:
    said = kv_get_json(conn, FAILED_KEY)
    since = stamps.utc(now) - FAILED_FOR
    return {k: {"at": str(v.get("at")), "error": str(v.get("error") or "")} for k, v in said.items()
            if isinstance(k, str) and isinstance(v, dict) and not stamps.before(v.get("at"), since)
            } if isinstance(said, dict) else {}


def failed(conn: sqlite3.Connection, key: str, now: datetime) -> str | None:
    """Why no search of ``key`` goes now, its own or ``FAILURES_PAUSE`` failing within the hour; None when neither."""
    failures = _failures(conn, now)
    if key in failures:
        return f"its search failed less than an hour ago ({failures[key]['error']})"
    if len(failures) >= FAILURES_PAUSE:
        return f"{len(failures)} searches failed in the last hour"
    return None


def record_failure(conn: sqlite3.Connection, key: str, now: datetime, error: str) -> None:
    failures = _failures(conn, now)
    failures[key] = {"at": stamps.stamp(now), "error": " ".join(error.split())[:ERROR_CHARS]}
    kv_set_json(conn, FAILED_KEY, failures)


def searches_used(conn: sqlite3.Connection, now: datetime) -> int:
    """The searches of YouTube made in the last hour: each run of them, named ``RUN``…, in ``events``."""
    since = stamps.stamp(stamps.utc(now) - timedelta(hours=1))
    return conn.execute("SELECT COUNT(DISTINCT run) FROM events WHERE provider = ? AND run LIKE ? AND at >= ?",
                        (PROVIDER, RUN + "%", since)).fetchone()[0]


@dataclass(frozen=True)
class Gate:
    """What a search of a query is now (``gate``): its ``state`` (``STATES``), its ``key``, what it found
    (``asked``) when it was made within 30 days, and why none goes (``why``) when it can't."""

    state: str
    key: str
    asked: dict[str, Any] | None = None
    why: str = ""


def gate(cfg: Config, conn: sqlite3.Connection, query: str, *, on_screen: bool, now: datetime) -> Gate | None:
    """What a search of ``query`` is now, with no request (module docstring); None when none is for it: no word,
    a sheet on the screen already (``on_screen``: ``sheet_on_screen``), or a caracole that makes no sheet from a
    video (``youtube_fetch.route_problem``)."""
    from caracole.health import is_cooling
    from caracole.youtube_fetch import route_problem

    key = query_key(query)
    if not key or on_screen or route_problem(cfg) is not None:
        return None
    was = searched(conn, key, now)
    if was is not None:
        return Gate("found" if isinstance(was.get("video"), dict) else "none", key, was)
    if is_cooling(conn, PROVIDER, now):
        return Gate("spent", key, why="YouTube is cooling down after a block")
    if searches_used(conn, now) >= SEARCHES_PER_HOUR:
        return Gate("spent", key, why=f"this hour's {SEARCHES_PER_HOUR} searches of YouTube are spent")
    why = failed(conn, key, now)
    if why is not None:
        return Gate("failed", key, why=why)
    return Gate("auto", key)


def search(conn: sqlite3.Connection, runner: YtDlp, query: str, now: datetime) -> Video | None:
    """YouTube's first result for ``query`` (one yt-dlp run), recorded searched with it (or with none). A block, a
    spent budget or an error propagates and records nothing."""
    videos = runner.search(query, 1)
    video = next((v for v in videos if not v.live), None)
    kv_set_json(conn, KV_PREFIX + query_key(query), {"at": stamps.stamp(now), "query": query,
                                                     "video": video.as_json() if video else None, "thumb": False})
    failures = _failures(conn, now)
    if failures.pop(query_key(query), None) is not None:
        kv_set_json(conn, FAILED_KEY, failures)
    return video


# --- the thumbnail -----------------------------------------------------------------------------------------


def thumb_path(cfg: Config, video_id: str) -> Path:
    return cfg.cache_dir / THUMBS / f"{video_id}.jpg"


def checked_jpeg(data: bytes) -> bytes | None:
    """``data`` when it is a JPEG image and nothing else: at most ``MAX_BYTES``, its start-of-image marker, its
    segments walked to a frame of 1 to ``MAX_SIDE`` pixels a side and on to the scan; None otherwise."""
    if not 4 <= len(data) <= MAX_BYTES or data[:2] != b"\xff\xd8":
        return None
    i, size = 2, None
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill bytes before a marker
            i += 1
            continue
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            return None  # an image starts once, ends after its scan; restart markers live inside the scan
        (length,) = struct.unpack(">H", data[i + 2:i + 4])
        if length < 2 or i + 2 + length > len(data):
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if length < 7:
                return None
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
                return None
            size = (width, height)
        if marker == 0xDA:  # the scan: the image data follows, to its end-of-image marker
            return data if size is not None and data.rstrip(b"\x00").endswith(b"\xff\xd9") else None
        i += 2 + length
    return None


def fetch_thumbnail(cfg: Config, conn: sqlite3.Connection, client: Client, video_id: str, query: str,
                    now: datetime) -> bool:
    """The video's thumbnail, once (one request; none once it is kept), kept in ``cache_dir/youtube-thumbs/`` when
    its bytes are a JPEG (``checked_jpeg``), and the query's search record says so; whether it is kept now. A
    thumbnail YouTube hasn't (404) or that isn't a JPEG is none; a block or an error propagates."""
    from caracole.youtube_urls import VIDEO_ID

    if not VIDEO_ID.fullmatch(video_id):
        return False
    path = thumb_path(cfg, video_id)
    if not path.is_file():
        resp = client.get(THUMB_URL.format(id=video_id), accept=(200, 404))
        image = checked_jpeg(resp.content) if resp.status == 200 else None
        if image is None:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".part-{os.getpid()}-{path.name}")  # caracole's cache, never the synced library
        try:
            tmp.write_bytes(image)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    said = searched(conn, query_key(query), now)
    if said is not None and isinstance(said.get("video"), dict) and said["video"].get("id") == video_id:
        kv_set_json(conn, KV_PREFIX + query_key(query), {**said, "thumb": True})
    return True


def read_thumbnail(cfg: Config, video_id: str) -> bytes | None:
    """A kept thumbnail's bytes, checked again (the cache is caracole's, but a file there may be anyone's); None for
    no such video, file, or JPEG."""
    from caracole.youtube_urls import VIDEO_ID

    if not VIDEO_ID.fullmatch(video_id):
        return None
    try:
        data = thumb_path(cfg, video_id).read_bytes()
    except OSError:
        return None
    return checked_jpeg(data)


def suggestion(gate_said: Gate | None, query: str) -> dict[str, Any] | None:
    """The gate as ``/api/search``'s ``youtube`` gives it to the page: None, or its ``state``, the ``query`` and its
    ``key``, and, ``found``, the ``video`` (``id``, ``title``, ``channel``, ``duration``, ``url``, and ``thumb``: the
    address caracole serve sends its thumbnail at, or None)."""
    if gate_said is None:
        return None
    said: dict[str, Any] = {"state": gate_said.state, "query": query, "key": gate_said.key}
    if gate_said.state == "found" and gate_said.asked is not None:
        v = gate_said.asked["video"]
        said["video"] = {"id": v.get("id"), "title": v.get("title") or "", "channel": v.get("channel") or "",
                         "duration": v.get("duration"), "url": v.get("url"),
                         "thumb": f"/youtube/thumb/{v.get('id')}.jpg" if gate_said.asked.get("thumb") else None}
    if gate_said.why:
        said["why"] = gate_said.why
    return said
