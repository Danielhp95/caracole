"""A site's sitemaps, read into a table of the database: gtptabs.com's and MuseScore's.

A ``Site`` names its sitemap index, the table its pages go in and how a ``<loc>`` becomes
a child sitemap's name or a page's row. :func:`refresh` reads the sitemaps into the table
when they never were all read, again after ``Site.max_age``, and at once after a change to
caracole's keys (``normalize.KEY_VERSION``), always with conditional requests:

- A sitemap unchanged since it was indexed costs one request and isn't parsed, unless its
  rows were made with older keys: then the cache's copy, which the 304 brings, is parsed.
- A refresh the budget cuts short goes on where it stopped: a sitemap read or found
  unchanged in this round isn't asked for again until ``max_age`` has passed.
- Each sitemap is stored in one transaction, its rows in place of the ones it gave
  before, and a sitemap the index no longer lists leaves the table.

Every request is the client's, with its budget, its pauses and its robots.txt rules. A
block, a spent budget or any other ``ProviderError`` propagates, and what was stored
before it stays. The kv records are ``<provider>:sitemaps`` (each sitemap's validators,
rows, keys and when it was last checked) and ``<provider>:index:complete_at``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from caracole import normalize, stamps
from caracole.db import kv_get, kv_get_json, kv_set, kv_set_json, savepoint
from caracole.http import Client, ProviderError, Response
from caracole.ug.sitemap import iter_locs


def _as_is(url: str) -> str:
    return url


@dataclass(frozen=True)
class Site:
    """A site's sitemaps and the table they fill.

    ``columns`` are the table's columns a row fills, in the row's order; the table also has
    a ``sitemap`` column, the name of the sitemap a row came from. ``child`` names a child
    sitemap from its ``<loc>`` in the index (None for any other URL), and ``row`` makes a
    page's row from its ``<loc>`` (None leaves it out: a page robots.txt closes, say).
    ``fetch_url`` is the address a child is asked for at.
    """

    provider: str
    index_url: str
    table: str
    columns: Sequence[str]
    child: Callable[[str], str | None]
    row: Callable[[str], Sequence[Any] | None]
    max_age: timedelta = timedelta(days=30)
    fetch_url: Callable[[str], str] = field(default=_as_is)

    @property
    def sitemaps_key(self) -> str:
        return f"{self.provider}:sitemaps"

    @property
    def complete_key(self) -> str:
        return f"{self.provider}:index:complete_at"


def refresh(
    conn: sqlite3.Connection,
    client: Client,
    site: Site,
    now: datetime,
    on_read: Callable[[], None] = lambda: None,
) -> None:
    """Read the site's sitemaps into its table when due (see the module docstring).

    ``on_read`` is called for each sitemap stored (one found unchanged isn't), as it is
    stored, so a count survives a refresh the budget cuts short.
    """
    now = stamps.utc(now)
    complete = complete_at(conn, site)
    old_keys = any(not _current(entry) for entry in sitemaps(conn, site).values())
    if complete is not None and now - complete < site.max_age and not old_keys:
        return
    resp = client.get(site.index_url, cache=False, conditional=True)
    listed = _children(site, resp)
    for name in [n for n in sitemaps(conn, site) if n not in listed]:
        _forget(conn, site, name)
    for name, url in listed.items():
        entry = sitemaps(conn, site).get(name)
        current = entry is not None and _current(entry)
        if current and not stamps.before(entry.get("checked_at"), now - site.max_age):
            continue  # read or found unchanged in this round already
        r = client.get(url, cache=False, conditional=True)
        validators = _validators(r.headers)
        if r.status == 304 and current and _validators_of(entry) == validators:
            _record(conn, site, name, {**entry, "checked_at": stamps.stamp(now)})
            continue
        _store(conn, site, name, _rows(site, r.content, url, r.status), validators, now)
        on_read()
    kv_set(conn, site.complete_key, stamps.stamp(now))


def sitemaps(conn: sqlite3.Connection, site: Site) -> dict[str, dict[str, Any]]:
    """Each sitemap in the table, by name: its validators, its rows, its keys and when it was checked."""
    return kv_get_json(conn, site.sitemaps_key, default={}) or {}


def complete_at(conn: sqlite3.Connection, site: Site) -> datetime | None:
    """When every sitemap the index listed was last read or found unchanged; None before that."""
    return stamps.parse(kv_get(conn, site.complete_key))


def _children(site: Site, resp: Response) -> dict[str, str]:
    """The child sitemaps the sitemap index lists, by name, at the address each is asked for at."""
    children = {
        name: site.fetch_url(loc)
        for loc in _locs(site, resp.content, site.index_url, resp.status)
        if (name := site.child(loc)) is not None
    }
    if not children:
        raise ProviderError(site.provider, site.index_url, resp.status, "the sitemap index lists no sitemaps")
    return children


def _locs(site: Site, data: bytes, url: str, status: int) -> list[str]:
    try:
        locs = list(iter_locs(data))
    except (OSError, EOFError, ValueError) as e:  # a truncated or corrupt gzip body
        raise ProviderError(site.provider, url, status, f"unreadable sitemap: {e}") from e
    if not locs:
        raise ProviderError(site.provider, url, status, "not a sitemap (no <loc> entries)")
    return locs


def _rows(site: Site, data: bytes, url: str, status: int) -> list[Sequence[Any]]:
    return [row for row in map(site.row, _locs(site, data, url, status)) if row is not None]


def _record(conn: sqlite3.Connection, site: Site, name: str, entry: Mapping[str, Any]) -> None:
    indexed = sitemaps(conn, site)
    indexed[name] = dict(entry)
    kv_set_json(conn, site.sitemaps_key, indexed)


def _store(conn: sqlite3.Connection, site: Site, name: str, rows: list[Sequence[Any]],
           validators: Mapping[str, str | None], now: datetime) -> None:
    """Put one sitemap's rows in place of those it gave before, and record it, in one transaction."""
    columns = ", ".join((*site.columns, "sitemap"))
    marks = ", ".join("?" for _ in range(len(site.columns) + 1))
    with savepoint(conn, "site_index_store"):
        conn.execute(f"DELETE FROM {site.table} WHERE sitemap = ?", (name,))
        conn.executemany(f"INSERT OR REPLACE INTO {site.table} ({columns}) VALUES ({marks})",
                         [(*row, name) for row in rows])
        _record(conn, site, name, {**validators, "checked_at": stamps.stamp(now), "rows": len(rows),
                                   "keys": normalize.KEY_VERSION})


def _forget(conn: sqlite3.Connection, site: Site, name: str) -> None:
    """A sitemap the index no longer lists: its rows go, and its record."""
    with savepoint(conn, "site_index_forget"):
        conn.execute(f"DELETE FROM {site.table} WHERE sitemap = ?", (name,))
        indexed = sitemaps(conn, site)
        indexed.pop(name, None)
        kv_set_json(conn, site.sitemaps_key, indexed)


def _current(entry: Mapping[str, Any]) -> bool:
    """Whether a sitemap's rows were made with caracole's keys as they are now."""
    return entry.get("keys") == normalize.KEY_VERSION


def _validators(headers: Mapping[str, str]) -> dict[str, str | None]:
    lower = {k.lower(): v for k, v in headers.items()}
    return {"etag": lower.get("etag"), "last_modified": lower.get("last-modified")}


def _validators_of(entry: Mapping[str, Any]) -> dict[str, str | None]:
    return {"etag": entry.get("etag"), "last_modified": entry.get("last_modified")}
