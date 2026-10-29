"""LaCuerda's own search, one query at a time, at the lookup pace: ``caracole lacuerda --search QUERY``.

LaCuerda's local index (lacuerda_index.py) holds every artist of its listings, but the songs only of
the artist pages caracole has read, so a song by anyone else is no hit there. LaCuerda's search
(lacuerda.py: ``search_url``, ``parse_search``) answers it: what a page of results lists goes into the
index (``lacuerda_index.store_search``), and every search after finds it locally. caracole serve's
search bar sends it by itself (``--auto``) once a query has settled, when ``gate`` says so; its
button, Enter in the bar, and a terminal, send it by hand.

**One request.** A search of the songs (``canc=1``): the artists a query names are the listings'
(and Ask LaCuerda's, for a letter they don't reach yet), so a general search, whose answer is the
artists whose names match in place of the songs, would cost the songs; a page that lists artists
all the same is stored too. A query is the words LaCuerda reads of it (``lacuerda.search_words``:
four letters or more, accents folded), which make its key, in alphabetical order: "la flaca" and
"flaca" are one search, and so are "corazon tiza" and "tiza corazon". None is sent for a query
caracole answers well already (``answered``): a strong song of LaCuerda's index, the artist the query
names whose page caracole has read, or a strong song of your library (you are looking through your
songs); the command asks again once it has put the artist pages the HTTP cache holds into the index.

**When.** At most once in ``ASKED_FOR`` (30 days) a query: kv ``lacuerda:search:<key>`` keeps when
and what it answered, and the HTTP cache the page, asked again only once it is that old (a cached
page that won't parse is asked for once more, past the cache, as every LaCuerda page is). Within a
lookup's budgets (commands/_common.py: ``lookup_per_hour`` for every lookup to LaCuerda together, in
``events`` under runs named ``lookup:…``), and those the page sends by itself within a share of
them, ``SEARCHES_PER_HOUR`` in the last hour, counted in ``events`` under runs named
``lookup:lacuerda-search:…`` (``RUN``). ``gate`` says, with no request and no lock, what a search
of a query would be: ``auto`` (the page sends it), ``button`` (only the share is spent: the page
offers it), ``failed`` (it failed lately: below), ``asked`` (within 30 days) or ``spent`` (a cooldown,
or the hour's lookups); None for a query it reads no word of, or one caracole answers well already.

Errors are never misses: a block, a spent budget, an error or a page cut short (``LaCuerdaParseError``)
records nothing asked, and the query may be searched again. A search that failed (an error, or a page
caracole can't read: the answer of the songs, ``canc=1``, was never captured live, so a page shaped
otherwise would fail every time) isn't sent by the page by itself again for ``FAILED_FOR`` (an hour; kv
``lacuerda:search-failed``, each query's key with when and what it said), and after ``FAILURES_PAUSE``
(3) failed in the last hour the page sends none by itself: ``gate`` says ``failed``, and the page
offers it by hand, as the Requests tab's Try again and a terminal ask it. A search that answers drops
its query's failure.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from caracole import stamps
from caracole.db import kv_get_json, kv_set_json, savepoint

if TYPE_CHECKING:
    from collections.abc import Sequence

    from caracole.config import Config
    from caracole.http import Client
    from caracole.lacuerda import SearchAnswer
    from caracole.search import LibraryHit, SiteArtist, SiteHit

PROVIDER = "lacuerda"
SEARCHES_PER_HOUR = 20  # LACUERDA_SEARCHES_PER_HOUR: the searches the page sends by itself, within lookup_per_hour
ASKED_FOR = timedelta(days=30)  # a query asked once in this long
RUN = "lacuerda-search:"  # after "lookup:", how a search's run is named in events
KV_PREFIX = "lacuerda:search:"  # + the query's key: when it was asked, and what it answered
STATES = ("auto", "button", "failed", "asked", "spent")
FAILED_FOR = timedelta(hours=1)  # a search that failed: the page doesn't send it by itself again for this long
FAILURES_PAUSE = 3  # searches failed within FAILED_FOR that stop the page sending any by itself
FAILED_KEY = "lacuerda:search-failed"  # {query's key: {"at", "error"}}, those of the last FAILED_FOR
ERROR_CHARS = 200  # of what a failure said, kept
ANSWER_HITS = 5  # the hits ``answered`` reads of each search: the best are first


def query_key(query: str) -> str:
    """The query as LaCuerda's search reads it, its words in alphabetical order, hyphenated ("corazon-tiza" for
    "tiza corazón" too); "" for none."""
    from caracole.lacuerda import search_words

    return "-".join(sorted(search_words(query)))


def asked(conn: sqlite3.Connection, key: str, now: datetime) -> dict[str, Any] | None:
    """What LaCuerda answered the query of ``key`` when it was asked within ``ASKED_FOR`` (``at``, ``songs``,
    ``artists``, ``stated``); None when it wasn't."""
    said = kv_get_json(conn, KV_PREFIX + key) if key else None
    if not isinstance(said, dict) or stamps.before(said.get("at"), stamps.utc(now) - ASKED_FOR):
        return None
    return said


def answers_well(lc_artists: Sequence[SiteArtist], lc_songs: Sequence[SiteHit],
                 mine: Sequence[LibraryHit] = ()) -> bool:
    """Whether caracole answers a query well already, so that LaCuerda's search would bring nothing the query wants:
    a strong song of LaCuerda's index (``lc_songs``, search.search_lacuerda's: lacuerda_index.find never scores
    letters inside a word so), the artist the query names, whole, whose page caracole has read (``known``: their
    songs, all of them), or a strong song of your library (``mine``, search.search_library's: by its title or its
    artist, you are looking through your songs)."""
    from caracole.search import STRONG

    return (any(h.score >= STRONG for h in lc_songs)
            or any(a.score >= STRONG and not a.part and a.known > 0 for a in lc_artists)
            or any(h.score >= STRONG for h in mine))


def answered(conn: sqlite3.Connection, query: str) -> bool:
    """``answers_well`` for ``query``, its searches made now: LaCuerda's index and your library, read alone."""
    from caracole.search import search_lacuerda, search_library

    artists, songs = search_lacuerda(conn, query, songs=ANSWER_HITS)
    return answers_well(artists, songs, search_library(conn, query, ANSWER_HITS))


@dataclass(frozen=True)
class Failure:
    """Why the page doesn't send a search by itself for now (``failed``): the query's own search failed within
    ``FAILED_FOR`` (``own``), or ``count`` searches did (``FAILURES_PAUSE`` or more); ``error``, what the latest of
    them said, and ``until``, when the page may send it by itself again."""

    own: bool
    count: int
    error: str
    until: datetime

    def said(self, query: str) -> str:
        """Why, in a sentence without its full stop, ``query`` as it is shown ("“corazon tiza”")."""
        from caracole.stamps import shown

        if self.own:
            return (f"LaCuerda's search for {query} failed less than an hour ago ({self.error}), so the page won't "
                    f"send it by itself before {shown(self.until)}")
        return (f"{self.count} searches of LaCuerda failed in the last hour (the last: {self.error}), so the page "
                f"sends none by itself before {shown(self.until)}")


def _failures(conn: sqlite3.Connection, now: datetime) -> dict[str, dict[str, str]]:
    """The searches that failed within ``FAILED_FOR``, by their query's key: when (``at``) and what they said."""
    said = kv_get_json(conn, FAILED_KEY)
    since = stamps.utc(now) - FAILED_FOR
    return {k: {"at": str(v.get("at")), "error": str(v.get("error") or "")} for k, v in said.items()
            if isinstance(k, str) and isinstance(v, dict) and not stamps.before(v.get("at"), since)
            } if isinstance(said, dict) else {}


def failed(conn: sqlite3.Connection, key: str, now: datetime) -> Failure | None:
    """Why the page doesn't send the search of ``key`` by itself now (``Failure``): its own failed within
    ``FAILED_FOR``, or ``FAILURES_PAUSE`` searches did; None when neither."""
    failures = _failures(conn, now)
    own = failures.get(key)
    if own is not None:
        return Failure(True, 1, own["error"], stamps.parse(own["at"]) + FAILED_FOR)
    if len(failures) < FAILURES_PAUSE:
        return None
    times = sorted(failures.values(), key=lambda v: stamps.parse(v["at"]))
    # The pause ends once fewer than FAILURES_PAUSE are within the hour: when the one that leaves that many is older.
    until = stamps.parse(times[len(times) - FAILURES_PAUSE]["at"]) + FAILED_FOR
    return Failure(False, len(times), times[-1]["error"], until)


def record_failure(conn: sqlite3.Connection, key: str, now: datetime, error: str) -> None:
    """Remember that the search of ``key`` failed now, saying ``error``, for ``FAILED_FOR``; older failures go."""
    failures = _failures(conn, now)
    failures[key] = {"at": stamps.stamp(now), "error": " ".join(error.split())[:ERROR_CHARS]}
    kv_set_json(conn, FAILED_KEY, failures)


def _forget_failure(conn: sqlite3.Connection, key: str, now: datetime) -> None:
    failures = _failures(conn, now)
    failures.pop(key, None)
    kv_set_json(conn, FAILED_KEY, failures)


def searches_used(conn: sqlite3.Connection, now: datetime) -> int:
    """The requests LaCuerda's searches sent in the last hour: their share of the hour's lookups."""
    from caracole.commands._common import LOOKUP_RUN, lookup_requests_used

    return lookup_requests_used(conn, PROVIDER, now, run=LOOKUP_RUN + RUN)


@dataclass(frozen=True)
class Gate:
    """What a search of a query would be (``gate``): its ``state`` (``STATES``), its ``key``, what LaCuerda
    answered it (``asked``) when it was asked within 30 days, and why the page doesn't send it by itself
    (``failure``) when it failed lately."""

    state: str
    key: str
    asked: dict[str, Any] | None = None
    failure: Failure | None = None


def gate(cfg: Config, conn: sqlite3.Connection, query: str, *, strong: bool, now: datetime) -> Gate | None:
    """What a search of ``query`` would be, with no request (module docstring); None when there is none to send:
    no word LaCuerda reads, caracole answering it well already (``strong``: ``answers_well``), or LaCuerda turned
    off."""
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
    failure = failed(conn, key, now)
    if failure is not None:
        return Gate("failed", key, failure=failure)
    if searches_used(conn, now) >= SEARCHES_PER_HOUR:
        return Gate("button", key)
    return Gate("auto", key)


def search(conn: sqlite3.Connection, client: Client, query: str, now: datetime) -> SearchAnswer:
    """Ask LaCuerda's search for the songs of ``query`` (one request, none while the cache holds an answer younger
    than ``ASKED_FOR``), store what it answers in the index and record it asked, its failure gone, in one
    transaction. A cached page that won't parse is asked for once more, past the cache. Provider errors propagate,
    a page cut short among them, and record nothing (the command records the failure: ``record_failure``); a stale
    copy served because the budget is spent is ``BudgetExhausted``."""
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
        key = query_key(query)
        kv_set_json(conn, KV_PREFIX + key, {
            "at": stamps.stamp(now), "songs": len(answer.songs), "artists": len(answer.artists),
            "stated": answer.stated})
        _forget_failure(conn, key, now)
    return answer
