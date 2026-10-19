"""MuseScore in the nightly run: its song sitemaps into a local index, and nothing else.

caracole never downloads from MuseScore, never logs in, and asks for no page robots.txt
closes (``/api/jmuse``, the downloads, the search): it reads the song sitemaps robots.txt
lists into ``musescore_index`` (db.py), through site_index.py, and the to-do page and
index.html list each song's pages from it (``musescore.song_pages``), with no request.

The sitemaps are read when they never were all read, again after 30 days with
conditional requests (an unchanged one costs a request and isn't parsed), and at once
after a change to caracole's keys. With a budget of 10 requests a run, a first read of the
19 files takes two nights, the second going on where the first stopped.

With no song that wants pages (none, or every one ignored), nothing is sent. Cloudflare's
challenge is a block: ``ProviderBlocked`` propagates, the run or the command cools MuseScore
down, and the pages go on listing what the index holds. A spent budget ends the pass, and
any other provider error counts in ``errors``: the index stays as it was.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from caracole import site_index
from caracole.http import BudgetExhausted, Client, ProviderBlocked, ProviderError, ProviderUnavailable
from caracole.musescore import PROVIDER, SITEMAP_INDEX_URL, parse_song_url, sitemap_name
from caracole.overrides import Overrides
from caracole.site_index import Site
from caracole.songs import Song, list_songs

log = logging.getLogger(__name__)

INDEX_MAX_AGE = timedelta(days=30)

# MuseScore's song sitemaps, as site_index.py reads them into musescore_index.
SITE = Site(
    provider=PROVIDER, index_url=SITEMAP_INDEX_URL, table="musescore_index",
    columns=("page_id", "path", "title_key"), child=sitemap_name, row=parse_song_url, max_age=INDEX_MAX_AGE,
)


@dataclass
class MuseScoreStats:
    """What one ``musescore_index`` pass did. ``sitemaps`` counts the sitemaps read into the
    index (one found unchanged isn't)."""

    sitemaps: int = 0
    errors: int = 0
    budget_exhausted: bool = False


def musescore_index(
    conn: sqlite3.Connection,
    client: Client,
    now: datetime,
    *,
    overrides: Overrides | None = None,
) -> MuseScoreStats:
    """Read MuseScore's song sitemaps into the index when due; see the module docstring."""
    stats = MuseScoreStats()
    if not songs_wanting_pages(conn, overrides):
        return stats

    def read() -> None:
        stats.sitemaps += 1

    try:
        site_index.refresh(conn, client, SITE, now, on_read=read)
    except ProviderBlocked:
        raise
    except BudgetExhausted:
        stats.budget_exhausted = True
    except ProviderUnavailable as e:
        log.warning("MuseScore is unavailable for the rest of this run: %s", e)
    except ProviderError as e:
        stats.errors += 1
        log.warning("MuseScore's song sitemaps: %s", e)
    return stats


def songs_wanting_pages(conn: sqlite3.Connection, overrides: Overrides | None) -> list[Song]:
    """The songs the to-do page and index.html may list MuseScore pages for: all but the ignored."""
    ignored = overrides.ignore if overrides is not None else frozenset()
    return [s for s in list_songs(conn) if s.status != "ignored" and s.key not in ignored]


def index_size(conn: sqlite3.Connection) -> int:
    """How many song pages the index holds."""
    return conn.execute("SELECT COUNT(*) FROM musescore_index").fetchone()[0]
