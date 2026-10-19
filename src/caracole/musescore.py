"""musescore.com: song pages caracole lists for you, and never downloads from.

MuseScore has no public API, a download needs a login (most scores a Pro account), and
its formats are MuseScore, MusicXML, PDF and MIDI, never Guitar Pro. So caracole only
finds each song's pages, in a local index of MuseScore's song sitemaps
(musescore_fetch.py), and lists them on the to-do page and index.html; you open one,
download a score yourself, and drop the file into ``_inbox/``, which inbox.py files.
What the site looked like on 19 October 2026:

- **robots.txt** closes ``/api/jmuse`` (a score's pages, audio and MIDI), the downloads
  (``/score/*/download/*``), the search (``/sheetmusic?``, ``/search/``), ``/oembed/*``
  and more (``http.ROBOTS_DISALLOW``), and lists the sitemaps, ``song-index.xml`` among
  them.
- **The song sitemaps**, ``SITEMAP_INDEX_URL`` and its 18 children of about 40,000 song
  pages each, give a page's title and nothing of its artist:
  ``/song/{title}-{id}``, the title in lowercase ASCII, its words joined by
  underscores, its accents and apostrophes gone ("lideal" is L'idéal). Titles repeat:
  nine pages are "Ave Maria". So every match is on the title alone, a possible match.
- **Cloudflare** answers caracole's request for the song sitemap index with a challenge
  (HTTP 403, ``cf-mitigated: challenge``), as it did every client the research tried;
  only robots.txt answers. A challenge is a block (``http.is_challenge``): caracole
  cools down and never works around it, and the pages list what the index holds.
"""

from __future__ import annotations

import re
import sqlite3
from typing import NamedTuple

from caracole.normalize import clean_title, slug_key
from caracole.songs import Song

PROVIDER = "musescore"
HOST = "musescore.com"
BASE_URL = f"https://{HOST}"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemaps/song-index.xml"
MAX_PAGES = 3  # a song's pages on the to-do page and index.html, oldest first

_CHILD = re.compile(r"https://musescore\.com/sitemaps/song-index/sitemap_songs(\d{1,4})\.xml")
# The slugs the sitemaps list are lowercase ASCII letters, digits and underscores (a hyphen is
# let through too); a URL with anything else in it is no page caracole lists, and never lands
# in a link it writes.
_SONG = re.compile(r"https://musescore\.com/(song/([a-z0-9_-]{1,300})-(\d{1,12}))")


class SongPage(NamedTuple):
    """A song page, as ``musescore_index`` keeps it: MuseScore's id, its path, its title's key."""

    page_id: int
    path: str
    title_key: str

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.path}"


def sitemap_name(url: str) -> str | None:
    """``"18"`` for the song sitemap ``sitemap_songs18.xml``; None for any other URL."""
    m = _CHILD.fullmatch(url)
    return m.group(1) if m else None


def parse_song_url(url: str) -> SongPage | None:
    """The song page a sitemap URL is, or None for any other URL, or a title without a key."""
    m = _SONG.fullmatch(url)
    if m is None:
        return None
    path, slug, page_id = m.groups()
    key = slug_key(slug)
    return SongPage(int(page_id), path, key) if key else None


def title_key(title: str) -> str:
    """The key a song's title meets the pages' titles with: Spotify's suffixes go first."""
    return slug_key(clean_title(title))


def song_pages(conn: sqlite3.Connection, song: Song, limit: int = MAX_PAGES) -> list[SongPage]:
    """The index's pages with the song's title, oldest first: possible matches, on the title alone."""
    key = title_key(song.title)
    if not key:
        return []
    rows = conn.execute(
        "SELECT page_id, path, title_key FROM musescore_index WHERE title_key = ? ORDER BY page_id LIMIT ?",
        (key, limit),
    )
    return [SongPage(*row) for row in rows]
