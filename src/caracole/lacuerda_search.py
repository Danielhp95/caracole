"""LaCuerda's own search, one query at a time, at the lookup pace: ``caracole lacuerda --search QUERY``.

LaCuerda's local index (lacuerda_index.py) holds every artist of its listings, but the songs only of
the artist pages caracole has read, so a song by anyone else is no hit there. LaCuerda's search
(lacuerda.py: ``search_url``, ``parse_search``) answers it: what a page of results lists goes into the
index (``lacuerda_index.store_search``), and every search after finds it locally. caracole serve's
search bar sends it by itself (``--auto``) once a query has settled, when ``gate`` says so; its
button, and a terminal, send it by hand.

**One request.** A search of the songs (``canc=1``): the artists a query names are the listings'
(and Ask LaCuerda's, for a letter they don't reach yet), so a general search, whose answer is the
artists whose names match in place of the songs, would cost the songs; a page that lists artists
all the same is stored too. A query is the words LaCuerda reads of it (``lacuerda.search_words``:
four letters or more, accents folded), which make its key: "la flaca" and "flaca" are one search.

**When.** At most once in ``ASKED_FOR`` (30 days) a query: kv ``lacuerda:search:<key>`` keeps when
and what it answered, and the HTTP cache the page, asked again only once it is that old (a cached
page that won't parse is asked for once more, past the cache, as every LaCuerda page is). Within a
lookup's budgets (commands/_common.py: ``lookup_per_hour`` for every lookup to LaCuerda together, in
``events`` under runs named ``lookup:…``), and those the page sends by itself within a share of
them, ``SEARCHES_PER_HOUR`` in the last hour, counted in ``events`` under runs named
``lookup:lacuerda-search:…`` (``RUN``). ``gate`` says, with no request and no lock, what a search
of a query would be: ``auto`` (the page sends it), ``button`` (only the share is spent: the page
offers it), ``asked`` (within 30 days) or ``spent`` (a cooldown, or the hour's lookups); None for a
query it reads no word of, or one LaCuerda's index answers well already (a strong song, or the
artist the query names whose page caracole has read: web/search_routes.py says which).

Errors are never misses: a block, a spent budget, an error or a page cut short (``LaCuerdaParseError``)
records nothing asked, and the query may be searched again.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from caracole import stamps
from caracole.db import kv_get_json, kv_set_json, savepoint

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.http import Client
    from caracole.lacuerda import SearchAnswer

PROVIDER = "lacuerda"
SEARCHES_PER_HOUR = 20  # LACUERDA_SEARCHES_PER_HOUR: the searches the page sends by itself, within lookup_per_hour
ASKED_FOR = timedelta(days=30)  # a query asked once in this long
RUN = "lacuerda-search:"  # after "lookup:", how a search's run is named in events
KV_PREFIX = "lacuerda:search:"  # + the query's key: when it was asked, and what it answered
STATES = ("auto", "button", "asked", "spent")


def query_key(query: str) -> str:
    """The query as LaCuerda's search reads it, its words hyphenated ("corazon-tiza"); "" for none."""
    from caracole.lacuerda import search_words

    return "-".join(search_words(query))


def asked(conn: sqlite3.Connection, key: str, now: datetime) -> dict[str, Any] | None:
    """What LaCuerda answered the query of ``key`` when it was asked within ``ASKED_FOR`` (``at``, ``songs``,
    ``artists``, ``stated``); None when it wasn't."""
    said = kv_get_json(conn, KV_PREFIX + key) if key else None
    if not isinstance(said, dict) or stamps.before(said.get("at"), stamps.utc(now) - ASKED_FOR):
        return None
    return said


def searches_used(conn: sqlite3.Connection, now: datetime) -> int:
    """The requests LaCuerda's searches sent in the last hour: their share of the hour's lookups."""
    from caracole.commands._common import LOOKUP_RUN, lookup_requests_used

    return lookup_requests_used(conn, PROVIDER, now, run=LOOKUP_RUN + RUN)


@dataclass(frozen=True)
class Gate:
    """What a search of a query would be (``gate``): its ``state`` (``STATES``), its ``key``, and what LaCuerda
    answered it (``asked``) when it was asked within 30 days."""

    state: str
    key: str
    asked: dict[str, Any] | None = None


def gate(cfg: Config, conn: sqlite3.Connection, query: str, *, strong: bool, now: datetime) -> Gate | None:
    """What a search of ``query`` would be, with no request (module docstring); None when there is none to send:
    no word LaCuerda reads, LaCuerda's index answering it well already (``strong``: a strong song of
    lacuerda_index.find's, which never scores letters inside a word so, or an artist the query names whose page
    caracole read), or LaCuerda turned off."""
    from caracole.commands._common import lookup_requests_used
    from caracole.health import is_cooling

    key = query_key(query)
    p = cfg.provider(PROVIDER)
    if not key or strong or not p.enabled:
        return None
    was = asked(conn, key, now)
    if was is not None:
        return Gate("asked", key, was)
    if is_cooling(conn, PROVIDER, now) or p.lookup_requests < 1 or \
            lookup_requests_used(conn, PROVIDER, now) >= p.lookup_per_hour:
        return Gate("spent", key)
    if searches_used(conn, now) >= SEARCHES_PER_HOUR:
        return Gate("button", key)
    return Gate("auto", key)


def search(conn: sqlite3.Connection, client: Client, query: str, now: datetime) -> SearchAnswer:
    """Ask LaCuerda's search for the songs of ``query`` (one request, none while the cache holds an answer younger
    than ``ASKED_FOR``), store what it answers in the index and record it asked, in one transaction. A cached page
    that won't parse is asked for once more, past the cache. Provider errors propagate, a page cut short among
    them, and record nothing; a stale copy served because the budget is spent is ``BudgetExhausted``."""
    from caracole.http import BudgetExhausted, read_once_more, stale
    from caracole.lacuerda import LaCuerdaParseError, parse_search, search_url
    from caracole.lacuerda_index import store_search

    url = search_url(query)
    resp = client.get(url, accept=(200,), max_age=ASKED_FOR)
    if stale(resp, now, ASKED_FOR):
        raise BudgetExhausted(PROVIDER)
    answer = read_once_more(client, resp, url, lambda r: parse_search(r.text, url=r.url), LaCuerdaParseError,
                            accept=(200,))
    with savepoint(conn, "lacuerda_search"):
        store_search(conn, answer)
        kv_set_json(conn, KV_PREFIX + query_key(query), {
            "at": stamps.stamp(now), "songs": len(answer.songs), "artists": len(answer.artists),
            "stated": answer.stated})
    return answer
