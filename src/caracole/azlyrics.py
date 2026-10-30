"""AZLyrics' pages: plain lyrics for a song LRCLIB and Megalobiz have none of (azlyrics_fetch.py).

Asked by hand on 2026-10-30 with caracole's user agent, it answered with its pages, no script needed. Its robots.txt
(tests/fixtures/azlyrics/robots.txt, ``http.ROBOTS_DISALLOW``) closes its search (``/search/``, ``/suggest/``) and
``/song/`` and ``/lyricsdb/``, and it has no sitemap, so a song is reached from its artist's page and nothing else;
caracole reads no letter page (``/p.html``) and keeps no index. Each lyrics page says, in a comment above the text,
"Usage of azlyrics.com content by any third-party lyrics provider is prohibited by our licensing agreement": the
owner chose the site knowing it (AGENTS.md, Invariants), for their own songs alone, and caracole links back to the page
wherever it credits the lyrics (``Lyrics.url``).

- ``/<letter>/<slug>.html`` is an artist's page: a ``listAlbum`` of rows, a song's a ``listalbum-item`` link to
  ``/lyrics/<artist>/<song>.html`` (another artist's for a song they sang together, an absolute address then), an
  instrumental's a row with no link, then a script that lists them again. Its ``<h1>`` names the artist.
- The slug is the name in lower-case letters and digits, without a leading "The" (``artist_url``), under a name's first
  letter, or ``19/`` for a digit: 667 of the 696 artists of ``/p.html``. The others (12 filed by their surname, "Paul,
  Sean", 17 by a slug of their own, ``planb3751``) answer 404, a miss, unless ``[azlyrics]`` names the song's page.
- ``/lyrics/<artist>/<song>.html`` has the lyrics in the ``<div>`` that begins with that comment, a line a ``<br>``.
- It answers a block with a 200 and a box to tick, which ``http.is_challenge`` knows by its words: a block, never a page.

Pure: no client, no database. A page that doesn't read as one of these is an ``AzLyricsParseError``: an error, never a
miss.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from caracole.http import ProviderError, Response
from caracole.lyrics import another_version, fits
from caracole.normalize import fold, slug_key

PROVIDER = "azlyrics"
SITE = "https://www.azlyrics.com/"  # where every page is, which caracole links back to

_HEADING = re.compile(r"<h1>\s*<strong>(.+?) Lyrics</strong>\s*</h1>", re.S)
_ROW = re.compile(
    r'<div class="listalbum-item"><a href="(?:https://www\.azlyrics\.com)?(/lyrics/[a-z0-9-]+/[a-z0-9-]+\.html)"'
    r"[^>]*>(.*?)</a>", re.S)
_LYRICS = re.compile(r"<!-- Usage of azlyrics\.com content.*?-->(.*?)</div>", re.S)
_TAG = re.compile(r"<[^>]+>")


class AzLyricsParseError(ProviderError):
    """A page from AZLyrics that isn't the artist's or the lyrics page it should be: an error, never a miss."""


@dataclass(frozen=True)
class SongLink:
    """A song an artist's page links to: its title as written, and its lyrics page."""

    title: str
    url: str


@dataclass(frozen=True)
class ArtistPage:
    """An artist's page: their name as the site writes it, and the songs it links to."""

    name: str
    songs: tuple[SongLink, ...]


def artist_url(name: str) -> str | None:
    """The address of an artist's page, or None for a name with no letter or digit to write in one (a name in
    another script, which the site files under a slug of its own)."""
    slug = re.sub(r"[^a-z0-9]", "", re.sub(r"^the\s+", "", fold(name).lower()))
    if not slug:
        return None
    return f"{SITE}{slug[0] if slug[0].isalpha() else '19'}/{slug}.html"


def _text(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).strip()


def parse_artist(resp: Response) -> ArtistPage:
    """An artist's name and the songs their page links to, the page's script read for none."""
    page = resp.text
    heading = _HEADING.search(page)
    if heading is None or 'id="listAlbum"' not in page:
        raise AzLyricsParseError(PROVIDER, resp.url, resp.status, "not an artist's page")
    songs = tuple(SongLink(_text(title), SITE + path.removeprefix("/")) for path, title in _ROW.findall(page))
    return ArtistPage(_text(heading.group(1)), songs)


def parse_lyrics(resp: Response) -> str:
    """A lyrics page's text, a line a ``<br>``, its tags (an italic section's name) gone and their words kept."""
    found = _LYRICS.search(resp.text)
    if found is None:
        raise AzLyricsParseError(PROVIDER, resp.url, resp.status, "not a lyrics page")
    joined = re.sub(r"<br\s*/?>", "\n", re.sub(r"[\r\n]+", "", found.group(1)))
    text = "\n".join(line.strip() for line in html.unescape(_TAG.sub("", joined)).split("\n")).strip()
    if not text:
        raise AzLyricsParseError(PROVIDER, resp.url, resp.status, "a lyrics page with no lyrics")
    return text


def pick_song(page: ArtistPage, *, artist: str, title: str) -> SongLink | None:
    """The song on an artist's page, or None when it isn't there: their name and its title fit as
    ``lyrics.pick_candidate``'s do (``lyrics.fits``), no other kind of version than the song
    (``lyrics.another_version``), the title closest to the song's as written first, so that its own line goes before
    its "(Live)" one, which ``clean_title`` makes the same."""
    close = [song for song in page.songs if not another_version(title, song.title)
             and fits(artist=artist, title=title, duration_s=None, got_artist=page.name, got_title=song.title,
                      got_duration=None) is not None]
    return max(close, key=lambda song: fuzz.ratio(slug_key(title), slug_key(song.title)), default=None)
