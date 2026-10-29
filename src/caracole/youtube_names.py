"""A song's "Artist - Title" guessed from a YouTube video's title and channel: what the library page fills a pasted
link's request in with, for the owner to check before it is sent (web/youtube_routes.py).

The rules, in order:

- **The title's noise goes:** a bracket ("(…)", "[…]", "【…】") made only of such words as Official, Video, Audio,
  Lyrics, Letra, Con Letra, Video Oficial, Videoclip, Visualizer, HD, 4K, MV or Remastered (a year beside them too),
  then such words at its end ("… HD", "… | Official Video"), and quotes around it. "(feat. …)" or "(En Vivo)" stay:
  they are the song's.
- **A title of two parts** ("A - B", "A – B", "A — B", "A | B", "A ~ B", "A // B", at the first such mark) is the
  artist and the song, in that order, unless the second part is a known artist and the first isn't (``known``: the
  library's or an offline index's, read with no request), or the second part is the channel's name: then the other
  way round, as a fan's "Song - Band".
- **Otherwise** the channel is the artist, its label words gone (``clean_channel``: "Radiohead - Topic",
  "AdeleVEVO", "Queen Official"), and the cleaned title the song.

The standard library alone: the pages import it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

_NOISE = frozenset({
    "official", "oficial", "officiel", "ufficiale", "music", "musical", "video", "vídeo", "videoclip", "clip",
    "audio", "lyric", "lyrics", "letra", "letras", "con", "with", "hd", "hq", "4k", "1080p", "720p", "mv", "m/v",
    "visualizer", "visualiser", "remastered", "remaster", "remasterizado", "remasterizada", "version", "versión",
})
_STRONG = _NOISE - {"music", "musical", "con", "with", "version", "versión", "clip"}
_YEAR = re.compile(r"(?:19|20)\d\d")
_BRACKETS = re.compile(r"\s*[(\[【「]([^()\[\]【】「」]*)[)\]】」]")
_SEPARATORS = re.compile(r"\s+(?:-|–|—|\||~|//)\s+")
_QUOTES = "\"'“”‘’«»「」『』"
_TOPIC = re.compile(r"^(.*\S)\s+-\s+topic$", re.IGNORECASE)
_LABEL = re.compile(r"\s*(?:vevo|official|oficial|officiel)(?:\s+channel)?$", re.IGNORECASE)


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return [w for w in re.split(r"[\s,.:!¡¿?\-–—]+", folded) if w]


def _noise(text: str) -> bool:
    """Whether a bracket's or a part's words are noise alone: one strong word at least, a year beside them too."""
    words = _words(text)
    return bool(words) and any(w in _STRONG for w in words) and all(w in _NOISE or _YEAR.fullmatch(w)
                                                                     for w in words)


def _clean(title: str) -> str:
    """A title without its noise (module docstring)."""
    text = _BRACKETS.sub(lambda m: "" if _noise(m.group(1)) else m.group(0), title)
    words = text.split()
    while words and _noise(words[-1]) and len(words) > 1:
        words.pop()
    text = " ".join(words)
    parts = _SEPARATORS.split(text)
    while len(parts) > 1 and _noise(parts[-1]):
        parts.pop()
    text = " - ".join(p for p in parts if p).strip()
    while len(text) > 1 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    return "" if _noise(text) else text


def clean_channel(channel: str) -> str:
    """A channel's name as an artist's: no " - Topic", no VEVO, Official or Oficial at its end."""
    name = channel.strip()
    topic = _TOPIC.match(name)
    if topic:
        return topic.group(1).strip()
    bare = _LABEL.sub("", name).strip()
    return bare or name


def _same(a: str, b: str) -> bool:
    return bool(a) and _words(a) == _words(b)


def guess(title: str, channel: str, *, known: Callable[[str], bool] = lambda name: False) -> tuple[str, str]:
    """``(artist, title)`` guessed from a video's title and channel (module docstring); "" for what can't be told."""
    artist = clean_channel(channel)
    cleaned = _clean(title)
    parts = _SEPARATORS.split(cleaned, maxsplit=1)
    if len(parts) == 2 and all(p.strip() for p in parts):
        first, second = (p.strip() for p in parts)
        if not known(first) and (known(second) or _same(second, artist)):
            first, second = second, first
        return first, _unquoted(second)
    return artist, _unquoted(cleaned)


def _unquoted(text: str) -> str:
    while len(text) > 1 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    return text
