"""A YouTube video's address: its id, as a browser shows it, and the plain address yt-dlp is given.

The standard library alone: overrides.py reads every ``[youtube]`` entry with it, which
the web page writes, so a command that runs no yt-dlp never loads youtube.py or an HTTP
client for it. youtube.py runs yt-dlp, and gives these names too.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

# The shape of a video's id, and the hosts its address may be on, as a browser shows them.
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_HOSTS = re.compile(r"(?:(?:www|m|music)\.)?youtube\.com")
_SHORT_HOST = "youtu.be"
_PATH_ID = re.compile(r"/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})")
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def video_id_from_url(url: Any) -> str | None:
    """The id of a YouTube video's address, as a browser shows it (``watch?v=``, ``youtu.be/``,
    ``/shorts/``, ``/embed/``, ``/live/``, on www, m or music); None for anything else."""
    if not isinstance(url, str):
        return None
    text = url.strip()
    if not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = parts.netloc.lower()
    if parts.scheme not in ("http", "https"):
        return None
    if host == _SHORT_HOST:
        found = parts.path.strip("/")
    elif _HOSTS.fullmatch(host):
        m = _PATH_ID.fullmatch(parts.path.rstrip("/"))
        if m:
            found = m.group(1)
        elif parts.path.rstrip("/") == "/watch":
            found = (parse_qs(parts.query).get("v") or [""])[0]
        else:
            return None
    else:
        return None
    return found if _VIDEO_ID.fullmatch(found) else None


def watch_url(video_id: str) -> str:
    """The video's plain address, the one yt-dlp is given: never one with a playlist."""
    return f"https://www.youtube.com/watch?v={video_id}"
