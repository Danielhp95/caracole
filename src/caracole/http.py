"""HTTP for every provider: errors, responses and the polite client.

Rules this module enforces (plan §6, "Politeness"):

- every raw response worth keeping (a 200 or 404 the caller accepts) is cached
  forever, and a cached URL never costs a request again;
- a request budget, with a random pause before every network request, redirect
  hops included. The policy sets the pace: bulk work's (2.5-5 s
  between requests to UG, a run's budget) or an interactive lookup's (a quarter
  of a second, a few requests for one song), which commands/_common.py picks;
- one request at a time;
- a URL its host's robots.txt disallows (``ROBOTS_DISALLOW``) is never requested,
  nor followed to: ``RobotsClosed``, a ``ProviderError`` that is no failure of the
  provider, so a caller may pass that URL over as one it may not read;
- a 403, a 429 or a challenge page raises ``ProviderBlocked``. Errors are never
  misses: callers must not turn any ``ProviderError`` into "not found";
- a 503 from a host that documents it as "busy, ask again after Retry-After"
  (``RETRY_AFTER_503``: LRCLIB) is asked once more after that wait, within the
  budget and the pace; a 503 is never cached.
"""

from __future__ import annotations

import email.utils
import gzip
import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Callable, Collection, Mapping, Protocol, runtime_checkable

from caracole.config import ProviderPolicy
from caracole.logs import provider_name, request_line

# httpx, with the rich and pygments it imports, is a third of a caracole's start: each function
# that uses it imports it, so a command that sends no request never does.
if TYPE_CHECKING:
    import httpx

log = logging.getLogger(__name__)  # a line per request, at information (-v)


class ProviderError(Exception):
    """A provider failed: an HTTP error, a timeout or an unparseable page. Never a miss."""

    def __init__(
        self,
        provider: str,
        url: str | None = None,
        status: int | None = None,
        message: str | None = None,
    ):
        self.provider = provider
        self.url = url
        self.status = status
        self.message = message
        parts = [provider]
        if status is not None:
            parts.append(str(status))
        if url:
            parts.append(url)
        if message:
            parts.append(message)
        super().__init__(": ".join(parts))


class ProviderBlocked(ProviderError):
    """A 403, a 429 or a challenge page: stop using the provider and back off."""


class ProviderUnavailable(ProviderError):
    """Too many consecutive errors this run; the provider is skipped until the next run."""


class RobotsClosed(ProviderError):
    """A URL robots.txt disallows (``robots_disallows``), asked for or redirected to: nothing is
    requested there. No failure of the provider, and no miss: a caller can pass the URL over as
    one caracole may not read."""


class BudgetExhausted(Exception):
    """This run's request budget for the provider is spent. Not an error and not a miss."""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"{provider}: request budget for this run is spent")


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content: bytes
    headers: Mapping[str, str] = field(default_factory=dict)
    from_cache: bool = False
    fetched_at: str | None = None

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)


@dataclass(frozen=True)
class Event:
    """One network request, for the ``events`` table."""

    provider: str
    url: str
    status: int | None
    decision: str  # ok | not_modified | redirect | blocked | error | budget | unavailable
    message: str | None = None


@runtime_checkable
class Client(Protocol):
    """What provider code needs from an HTTP client; tests pass fakes with this shape."""

    requests_made: int

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        cache: bool = True,
        conditional: bool = False,
        accept: Collection[int] = (200,),
        max_age: timedelta | None = None,
    ) -> Response: ...


# --- reading a provider's answers ---------------------------------------------


_STAMP = "%Y-%m-%dT%H:%M:%SZ"  # a cached copy's ``fetched_at``, in UTC


def stale(resp: Response, now: datetime, max_age: timedelta) -> bool:
    """Whether ``resp`` is a cached copy older than ``max_age`` at ``now`` (a naive time is UTC),
    or of unknown age. A fresh answer never is, nor one a 304 just revalidated. ``PoliteClient``
    serves such a copy only once the run's budget is spent: no answer for today, so its caller
    stops as the next request would have.
    """
    if not resp.from_cache:
        return False
    if not resp.fetched_at:
        return True
    fetched = datetime.strptime(resp.fetched_at, _STAMP).replace(tzinfo=UTC)
    return (now.replace(tzinfo=UTC) if now.tzinfo is None else now) - fetched > max_age


def read_once_more[T](
    client: Client, resp: Response, url: str, read: Callable[[Response], T],
    unreadable: type[ProviderError], *, fetched: set[str] | None = None, **get: Any,
) -> T:
    """``read(resp)``, where ``resp`` answered ``url``; a cached answer ``read`` can't read
    (it raises ``unreadable``) is asked for once more, past the cache, and read again.

    A 200 is cached, so a maintenance notice or a cut-short page would otherwise fail the
    song, from the cache, on every run. A fresh answer that fails is an error, and so is one
    for a URL this pass fetched already (``fetched``, which gains each URL fetched). ``get``
    goes to the second ``client.get``: what the first was given (``params``, ``accept``).
    """
    if fetched is not None and not resp.from_cache:
        fetched.add(url)
    try:
        return read(resp)
    except unreadable:
        if not resp.from_cache or (fetched is not None and url in fetched):
            raise
    if fetched is not None:
        fetched.add(url)
    return read(client.get(url, cache=False, **get))


# --- the polite client --------------------------------------------------------

_CACHED_STATUSES = (200, 404)
# The waits before each new try of a connection that failed before any byte was sent, while a client's patience lasts.
_CONNECT_WAITS = (2.0, 4.0, 8.0, 16.0, 30.0)
_KEPT_HEADERS = ("etag", "last-modified", "content-type", "location")
_FAILED = ("error", "blocked")  # a request's events that are no answer, as health.answered_any counts them
# Markers of a real challenge page. Normal UG pages also load Cloudflare's
# "/cdn-cgi/challenge-platform/" bot-management script, so that string alone
# is NOT evidence of a challenge.
_CHALLENGE_MARKERS = (
    b"_cf_chl_opt",
    b"<title>Just a moment...</title>",
    b"Attention Required! | Cloudflare",
    b"Enable JavaScript and cookies to continue",
    # AZLyrics' own, a 200 with a box to tick, as those it stopped quote it: a page like any other to the status.
    b"unusual activity from your IP address",
)


def is_challenge(headers: Mapping[str, str], body: bytes) -> bool:
    """Whether a response is a bot challenge (which counts as a block)."""
    if str(_header(headers, "cf-mitigated")).lower() == "challenge":
        return True
    head = body[:32768]
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name:
            return v
    return None


# The Disallow lines of the "User-agent: *" group of each host's robots.txt, as fetched
# on 2026-10-18 (docs/spike-2026-10-18.md), gtptabs.com's and musescore.com's on 2026-10-19
# (tests/fixtures/gtptabs/robots.txt, tests/fixtures/musescore/robots.txt), harptabs.com's on 2026-10-27
# (tests/fixtures/harptabs/robots.txt, which allows "/" first: its Disallow lines are longer, so they win), gametabs.net's
# on 2026-10-28 (tests/fixtures/gametabs/robots.txt, whose "$" ends a rule: "/*.php$" closes a path that ends in
# ".php"). LaCuerda's robots.txt is empty (tests/fixtures/lacuerda/robots.txt, 2026-10-20) and LRCLIB is an API,
# so their hosts have none.
_HARPTABS = (
    "/login", "/signup", "/recover", "/settings", "/submit", "/admin/", "/messages/", "/favorites", "/following",
    "/tab/*/edit", "/tab/*/upload", "/api/", "/search", "/*?*_rsc=",
)
_AZLYRICS = ("/lyricsdb/", "/song/", "/search/", "/suggest/")
_GAMETABS = (
    "/api/", "/admin/", "/*.log$", "/*.php$", "/create-report", "/tab-submissions", "/reputation", "/reports",
    "/settings", "/change-username", "/notifications", "/my-tabs", "/preparing-tab-file-download", "/global-stats",
    "/account-deactivation", "/tabs?*", "/login?*", "/create-account?*", "/administrator/", "/all-tabs/",
    "/article/", "/articles/", "/backend/", "/comment/", "/comments/", "/composer/", "/composers/", "/dashboard/",
    "/file/", "/files/", "/forum/topic/", "/game/", "/member/", "/members/", "/message/", "/messages/", "/module/",
    "/modules/", "/node/", "/nodes/", "/panel/", "/platform/", "/platforms/", "/recording/", "/recordings/",
    "/request/", "/requests/", "/series/", "/stat/", "/stats/", "/style/", "/styles/", "/template/", "/templates/",
    "/user/", "/users/",
)
ROBOTS_DISALLOW: Mapping[str, tuple[str, ...]] = {
    # /storage/ holds each artist's "Download all" archive; /ru/ is half of every sitemap.
    "gtptabs.com": (
        "/ru/", "/profile/", "/search/", "/storage/", "/index.php", "/tabs/upload.html",
        "/advertisement.html", "/message/",
    ),
    # /api/jmuse serves a score's pages, audio and MIDI; /sheetmusic? is the site's search.
    "musescore.com": (
        "/core/", "/profiles/", "/comment/reply/", "/filter/tips/", "/node/add/", "/search/",
        "/score/*/download/*", "/sheetmusic?", "/api/jmuse", "/pay-pal/*", "/pro/payment/*",
        "/pro/tools/*", "/pro/gift/*", "/user/login?", "/cas/login?", "/components/analytics/",
        "/components/data", "/gift/", "/community/", "/community?", "/redirect*", "/*/s/*",
        "/courses?", "/courses/favorites", "/books?", "/books/purchased", "/oembed/*", "/hymnal?",
    ),
    "www.ultimate-guitar.com": (
        "/search.php", "/forum/showthread.php?p=", "/forum/showpost.php", "/guitar/", "/tabmanager/",
        "/follow_me.php", "/goto.php", "/show.php", "/show", "/analytics/tracker/", "/updates/?filter=",
        "/contribution/", "/tabs/*.htm?sort=date", "/vote0.php", "/*?no_takeover",
        "/forum/showthread.php?t=*&goto=*", "/forum/archive/index.php?t-*.html",
        "/contribution/contest/index?", "/edu", "/components/", "/send?", "/profile/messages",
        "/profile/manage/", "/user/auth/", "/user/activity", "/tp/", "/pro/", "/redirect/away",
        "/courses/section", "/tab/applicature/transpose", "/tab-pro/download", "/books?*",
        "/user/tab/view?*", "/explore*song_id[]=*",
    ),
    # /api/ is its API (keys on request); /search its search; /*?*_rsc= a page's React data.
    "www.harptabs.com": _HARPTABS,
    "harptabs.com": _HARPTABS,
    # /preparing-tab-file-download is every attachment's download (a login's); /tabs?* its filters; /api/ its API.
    "gametabs.net": _GAMETABS,
    "www.gametabs.net": _GAMETABS,
    # Megalobiz's site, whose favicon caracole asks (icons.py): its robots.txt allows all but its accounts and editors
    # (tests/fixtures/megalobiz/robots.txt, 2026-10-30). Its API host, api.megalobiz.com, has no robots.txt (404).
    "megalobiz.com": (
        "/auth/", "/history", "/seo/", "/song/details", "/song/new", "/song/edit", "/album/details", "/album/new",
        "/album/edit", "/artist/details", "/artist/new", "/artist/edit", "/genre/details", "/genre/new",
        "/genre/edit", "/lrc/details", "/lrc/new", "/lrc/edit", "/playlist/details", "/playlist/new",
        "/playlist/edit",
    ),
    # AZLyrics' robots.txt (tests/fixtures/azlyrics/robots.txt, 2026-10-30): /search/ and /suggest/ are its search,
    # which is why a song is reached from its artist's page (azlyrics.py).
    "www.azlyrics.com": _AZLYRICS,
    "azlyrics.com": _AZLYRICS,
    # YouTube's image host, of which caracole asks a suggested video's thumbnail alone (youtube_search.py); /sb/ is
    # a video's storyboard frames.
    "i.ytimg.com": ("/sb/",),
    # The services a link shared to the phone is read from, each asked once a share (config.SHARE_PROVIDERS, the
    # phone's core.share.ShareLinks), each host's `User-agent: *` group as its live robots.txt had it on 2026-11-10
    # (tests/fixtures/itunes/, spotify/, tidal/ and youtube/www-robots.txt). Apple's catalogue: /lookup? is open,
    # /{cc}/lookup? closed. Spotify's track pages are open, its embeds closed (its oEmbed is open, and unasked). Its
    # short links' hosts close Branch's /_r/. tidal.com's and tidal.link's close nothing. YouTube's /oembed is open;
    # its /results and /youtubei/, which yt-dlp asks against them (the one exception), no PoliteClient ever asks.
    "itunes.apple.com": (
        "/WebObjects/MZFastFinance.woa", "/WebObjects/MZFinance.woa", "/WebObjects/MZPersonalizer.woa",
        "/WebObjects/MZStoreElements.woa", "/station/idst.", "/WebObjects/*", "/search*", "/*/rss/*", "/*/lookup?",
    ),
    "open.spotify.com": ("/local/", "/download/", "/embed/"),
    "spotify.link": ("/_r/",),
    "spotify.app.link": ("/_r/",),
    "www.youtube.com": (
        "/api/", "/channel_picker", "/comment", "/feeds/videos.xml", "/file_download", "/get_video", "/get_video_info",
        "/get_midroll_info", "/live_chat", "/login", "/qr", "/results", "/signup", "/t/terms", "/timedtext_video",
        "/verify_age", "/watch_ajax", "/watch_fragments_ajax", "/watch_popup", "/watch_queue_ajax", "/youtubei/",
    ),
    "tabs.ultimate-guitar.com": (
        "/forum/", "/tab/print?", "/components/", "/contribution/", "/user/tab/", "/download/public/",
        "/tab/download", "/tab/track/", "/tab/applicature/transpose", "/user/tab/view?*",
    ),
}


# The hosts whose 503 means "busy: ask again after Retry-After", as each documents it, with the longest Retry-After
# caracole waits for. LRCLIB's docs define its 503 as ServerOverloaded, "temporarily busy; retry after the
# Retry-After header (usually 1 second)", and its llms.txt asks clients to honour Retry-After on 429 and 503; asked
# by hand on 2026-10-29, an /api/search answered 503 with Retry-After: 1, and the next request, 7 s later, 200. Its
# 429 stays a block (the cooldown waits far longer than any Retry-After). Another site's 503 is an error at once.
RETRY_AFTER_503: Mapping[str, float] = {"lrclib.net": 30.0}
_RETRY_JITTER = 1.0  # seconds at most, added at random to a Retry-After's wait


def retry_after(headers: Mapping[str, str], now: datetime) -> float | None:
    """The seconds an answer's ``Retry-After`` asks to wait from ``now`` (an aware time): whole seconds, or an HTTP
    date (one already past is 0); None for none, or one that is neither (RFC 9110 §10.2.3)."""
    value = (_header(headers, "retry-after") or "").strip()
    if value.isascii() and value.isdigit():
        return float(value)
    now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)  # a naive time is UTC, as everywhere here
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:  # an HTTP date is always GMT
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


def _robots_pattern(rule: str) -> re.Pattern[str]:
    """A Disallow rule as a pattern matched at the start of a path and query: ``*`` any run of characters, and a
    ``$`` at its end the end of the path (RFC 9309)."""
    anchored = rule.endswith("$")
    body = ".*".join(map(re.escape, rule.removesuffix("$").split("*")))
    return re.compile(body + (r"\Z" if anchored else ""))


_ROBOTS = {host: [(rule, _robots_pattern(rule)) for rule in rules] for host, rules in ROBOTS_DISALLOW.items()}

# What robots_disallows answers for a string httpx can't parse as a URL.
NOT_A_URL = "not a valid URL"


def robots_disallows(url: str) -> str | None:
    """The robots.txt rule (``ROBOTS_DISALLOW``) that closes ``url``, or None when it is open.

    A rule matches the start of the URL's path and query, and ``*`` stands for any
    run of characters (RFC 9309). ``PoliteClient`` never requests a closed URL;
    other modules can use this to skip one before asking for it.

    A string httpx can't parse as a URL (a control character, more than 64 KiB, a
    broken host) can't be asked for either, so it is closed too, by ``NOT_A_URL``:
    one such link in UG's JSON or a sitemap is skipped, and never ends the run.
    """
    import httpx

    try:
        u = httpx.URL(url)
        host, target = u.host, u.raw_path.decode("ascii")
    except (httpx.InvalidURL, ValueError):  # ValueError: a lone surrogate, a broken IDNA label
        return NOT_A_URL
    for rule, pattern in _ROBOTS.get(host, ()):
        if pattern.match(target):
            return rule
    return None


def _not_a_url(provider: str, url: str) -> ProviderError:
    """The error for a string httpx can't parse as a URL, which shows its start, escaped, for the log."""
    shown = url if len(url) <= 120 else url[:120] + "..."
    return ProviderError(provider, None, None, f"{NOT_A_URL}: {shown!r}")


_MAX_REDIRECTS = 3  # hops followed for one request; httpx alone would follow 20


def _redirect_problem(origin: str, target: str, hops: int) -> str | None:
    """Why the ``hops``-th redirect of a request for ``origin``, to ``target``, is an error, if it is.

    A target robots.txt closes is no error (``RobotsClosed``), and is checked after these.
    """
    if hops > _MAX_REDIRECTS:
        return f"more than {_MAX_REDIRECTS} redirects"
    if _site(target) != _site(origin):
        return f"redirect to another site: {target}"
    return None


def _status_line(status: int) -> str:
    """"503 Service Unavailable"."""
    import httpx

    reason = httpx.codes.get_reason_phrase(status)
    return f"{status} {reason}" if reason else str(status)


def _site(url: str) -> str:
    """A URL's site: the last two labels of its host (each provider is on a plain .com or .net domain)."""
    import httpx

    return ".".join(httpx.URL(url).host.split(".")[-2:])


class PoliteClient:
    """One provider's HTTP client for one run: cache-first, budgeted, paced, never escalating.

    - A cached 200 or 404 is served without a request (``cache=True``) when the
      caller accepts its status; otherwise the URL is asked again. Only accepted
      answers are cached.
    - ``conditional=True`` revalidates a cached copy with If-None-Match /
      If-Modified-Since; a 304 returns the cached body, and the copy counts as
      fetched then.
    - Before every network request except the first, it pauses for a random
      time in ``policy.delay``, minus the time already elapsed. A subclass may spend the pause otherwise
      (``_wait``): commands/_common.py's hands caracole's lock to a waiting lookup.
    - ``policy.budget`` network requests per run; after that ``BudgetExhausted``, with one ``budget`` event
      (``_check_budget``, which a subclass that cuts the budget between two requests asks again).
    - A URL robots.txt disallows (``robots_disallows``) is never requested: when
      no cached answer is served, ``RobotsClosed``. Nor is a string httpx can't
      parse as a URL, which is a ``ProviderError`` at once.
    - Redirects are followed one hop at a time, at most three. Each hop is a
      request like any other (budget, pause, event) and must stay on the site
      asked for, or ``ProviderError``. A hop robots.txt closes isn't followed:
      ``RobotsClosed``, which the error breaker doesn't count (the site
      answered). The final answer is cached under the URL asked for. A redirect whose
      status the caller accepts is its answer, never followed (a short link's one hop:
      its ``location`` kept with it), and, as any status but 200 and 404, not cached.
    - 403, 429 or a challenge page raise ``ProviderBlocked``, and no further
      requests are made this run.
    - A 503 the caller rejects, from a host of ``RETRY_AFTER_503`` (LRCLIB), with a
      ``Retry-After`` it can read and no longer than the host's most, is asked once
      more: after that wait and a jitter under a second (``_wait``, so bulk work
      hands the lock over in it as in any pause), then the pause before any request,
      when that is longer. It is an ``error`` event, a request sent and unanswered,
      but not one of the breaker's: the retry's answer is what the request came to.
      A second 503, a 503 without such a ``Retry-After``, or one the budget can't pay
      the retry of is the 503's error, at once. A 503 is never cached.
    - After ``max_consecutive_errors`` other errors, ``ProviderUnavailable``. Only a
      healthy answer resets the count: an accepted 5xx is returned but doesn't.
    - A connection that fails before any byte of the request is sent (``httpx.ConnectError``:
      no address for the host, no route, refused) is tried again after a wait (``_CONNECT_WAITS``,
      spent through ``_wait``, then the usual pause), while the client's ``connect_patience`` (in
      seconds, none by default) lasts: a laptop that has just woken has no network for a few seconds.
      The patience is the client's for its whole life, so a network that stays down costs it once.
      Nothing else is tried again: a request that may have reached the site (an error reading its
      answer, a timeout) is the request's error at once. A retry is the same request: no event, and
      no more of the budget.
    - ``answered_any``: whether the site answered any request it sent, from its own count of those that failed
      (an ``error`` or a ``blocked`` event), as ``health.answered_any`` reads a run's from ``events``.
    """

    def __init__(
        self,
        provider: str,
        policy: ProviderPolicy,
        cache_dir: Path,
        *,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        on_event: Callable[[Event], None] | None = None,
        max_consecutive_errors: int = 3,
        timeout: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        connect_patience: float = 0.0,
    ):
        import httpx

        self.provider = provider
        self.policy = policy
        self.cache_root = cache_dir / "http" / provider
        self.requests_made = 0
        self._failed = 0  # requests sent and answered with an error or a block (``_event``)
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._on_event = on_event
        self._max_errors = max_consecutive_errors
        self._clock = clock
        self._wall_clock = wall_clock
        self._last_request: float | None = None
        self._errors_in_a_row = 0
        self._blocked: ProviderBlocked | None = None
        self._unavailable = False
        self._budget_reported = False
        self._connect_patience = connect_patience
        self._connect_waited = 0.0
        self._connect_tries = 0
        self._http = httpx.Client(
            transport=transport,
            headers={"User-Agent": user_agent},
            follow_redirects=False,  # get() follows them, one counted, paced and checked hop at a time
            timeout=timeout,
        )

    # -- public ------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        cache: bool = True,
        conditional: bool = False,
        accept: Collection[int] = (200,),
        max_age: timedelta | None = None,
    ) -> Response:
        """GET ``url``; see the class docstring. ``max_age`` refetches cached copies older than it,
        but serves the stale copy when this run's budget is spent."""
        import httpx

        try:
            full = str(httpx.URL(url, params=params)) if params else url
        except (httpx.InvalidURL, ValueError):
            raise _not_a_url(self.provider, url) from None
        rule = robots_disallows(full)
        if rule == NOT_A_URL:  # nothing is sent, so the error breaker doesn't count it either
            raise _not_a_url(self.provider, full)
        key = hashlib.sha256(full.encode("utf-8")).hexdigest()
        cached = self._read_cache(key) if (cache or conditional) else None
        if cached is not None and cached.status not in accept:
            cached = None  # an answer the caller rejects is no answer: ask again
        expired = cached is not None and max_age is not None and stale(cached, self._wall_clock(), max_age)
        if (cache and cached is not None and not conditional and not expired) or (
            expired and self.requests_made >= self.policy.budget
        ):
            self._log_request("GET", full, _status_line(cached.status), cached=True)
            return cached

        if rule is not None:  # nothing is sent, so the error breaker doesn't count it either
            raise RobotsClosed(self.provider, full, None, f"robots.txt disallows it ({rule})")
        headers: dict[str, str] = {}
        if conditional and cached is not None:
            etag = _header(cached.headers, "etag")
            modified = _header(cached.headers, "last-modified")
            if etag:
                headers["If-None-Match"] = etag
            if modified:
                headers["If-Modified-Since"] = modified

        at, resp = self._answer(full, headers, accept)
        wait = self._retry_wait(at, resp, accept)
        if wait is not None:  # the host is busy, and said when to ask again: once
            said = _header(resp.headers, "retry-after")
            log.info("%s answered %s, Retry-After: %s; asking once more in %.1f s", provider_name(self.provider),
                     _status_line(resp.status_code), said, wait)
            self._event(at, resp.status_code, "error",
                        f"HTTP {resp.status_code}, asked again in {wait:.1f} s (Retry-After: {said})")
            self._wait(wait)
            at, resp = self._answer(full, headers, accept)

        status, body = resp.status_code, resp.content
        if status == 304 and cached is not None:  # the copy is current: it is as old as this answer
            self._errors_in_a_row = 0
            self._event(at, status, "not_modified", None)
            stamp = self._write_meta(key, cached.url, cached.status, cached.headers)
            return Response(
                url=full, status=304, content=cached.content, headers=cached.headers, from_cache=True,
                fetched_at=stamp,
            )

        if status in accept:
            kept = {h: resp.headers[h] for h in _KEPT_HEADERS if h in resp.headers}
            if status in _CACHED_STATUSES:  # only what the caller accepts: a rejected 404 is asked again
                self._write_cache(key, full, status, kept, body)
            if status < 500:  # an accepted 5xx is no sign of health
                self._errors_in_a_row = 0
            self._event(at, status, "ok", None)
            return Response(url=full, status=status, content=body, headers=kept, from_cache=False)

        self._fail(at, status, f"HTTP {status}")
        raise AssertionError("unreachable")  # pragma: no cover

    def has_cached(self, url: str, *, accept: Collection[int] = (200,)) -> bool:
        """Whether the cache holds an answer for ``url`` with a status in ``accept``: one a
        conditional ``get`` would revalidate, and a plain one serve. Nothing is sent, and the
        body isn't read: that it is there is enough."""
        body_path, meta_path = self._paths(hashlib.sha256(url.encode("utf-8")).hexdigest())
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))["status"] in accept and body_path.is_file()
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def cached(self, url: str, *, accept: Collection[int] = (200,)) -> Response | None:
        """The cache's answer for ``url`` (``url`` as ``get`` would key it, no ``params``) when its
        status is in ``accept``, however old; None for none, or a copy that can't be read. Nothing is
        sent, nothing is counted, and it works whatever the budget, a block or a cooldown."""
        return cached_answer(self.cache_root, url, accept=accept)

    def answered_any(self) -> bool:
        """Whether the site answered at least one of the requests this client sent it: more were sent than
        failed with an error or a block, as ``health.answered_any`` counts a run's in ``events``. Only then did
        its work go well (``record_ok``): one whose every request failed (UG answering 502, say) is no success,
        and one that sent nothing has nothing to say. Its own count, so two lookups whose run ids are alike (two
        started in one second) never read each other's errors."""
        return self.requests_made > self._failed

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals ---------------------------------------------------------

    def _answer(self, full: str, headers: Mapping[str, str], accept: Collection[int]) -> tuple[str, httpx.Response]:
        """GET ``full`` with ``headers``, its redirects followed one checked hop at a time, but one whose status the
        caller accepts (``accept``), which is the answer; the URL that answered (the one asked for, or the last hop)
        and its answer."""
        at = full
        resp = self._send(at, self._http.build_request("GET", full, headers=headers))
        hops = 0
        while resp.next_request is not None and resp.status_code not in accept:  # a hop is a request like any other
            hops += 1
            target = str(resp.next_request.url)
            problem = _redirect_problem(full, target, hops)
            if problem is not None:
                self._fail(at, resp.status_code, problem)
                raise AssertionError("unreachable")  # pragma: no cover
            closed = robots_disallows(target)
            if closed is not None:  # the site answered, so the breaker neither counts this nor resets
                message = f"redirect to {target}, which robots.txt disallows ({closed})"
                self._event(at, resp.status_code, "redirect", f"not followed: {message}")
                raise RobotsClosed(self.provider, at, resp.status_code, message)
            self._event(at, resp.status_code, "redirect", target)
            at, resp = target, self._send(target, resp.next_request)
        return at, resp

    def _retry_wait(self, at: str, resp: httpx.Response, accept: Collection[int]) -> float | None:
        """How long to wait before asking once more for what answered ``resp`` at ``at``: a 503 the caller rejects,
        from a host of ``RETRY_AFTER_503``, whose ``Retry-After`` is no longer than the host's most, when the budget
        can pay for the retry; its Retry-After and a jitter. None: no retry."""
        import httpx

        if resp.status_code != 503 or 503 in accept or self.requests_made >= self.policy.budget:
            return None
        most = RETRY_AFTER_503.get(httpx.URL(at).host)
        said = retry_after(resp.headers, self._wall_clock()) if most is not None else None
        if said is None or said > most:
            return None
        return said + self._rng.uniform(0.0, _RETRY_JITTER)

    def _send(self, url: str, request: httpx.Request) -> httpx.Response:
        """One network request, a redirect hop included: within the budget, after the pause."""
        self._claim(url, request)
        return self._transmit(url, request)

    def _claim(self, url: str, request: httpx.Request) -> None:
        """What a request must clear before it is sent: no block this run, the breaker closed, the budget, then the
        pause; the request counted. ``ParallelClient`` clears one at a time, under its lock."""
        if self._blocked is not None:
            raise ProviderBlocked(self.provider, url, self._blocked.status, "blocked earlier this run")
        if self._unavailable:
            raise ProviderUnavailable(self.provider, url, None, "too many errors this run")
        self._check_budget(url)

        self._pause(str(request.url))
        self.requests_made += 1
        self._last_request = self._clock()

    def _check_budget(self, url: str) -> None:
        """The budget a request to ``url`` must keep: spent, ``BudgetExhausted``, said once in a ``budget`` event
        (the first time). ``_claim`` asks before the pause, and a subclass that cuts ``policy.budget`` in the pause
        (commands/_common.py's lane client, after another lookup's turn) asks again."""
        if self.requests_made >= self.policy.budget:
            if not self._budget_reported:
                self._budget_reported = True
                self._event(url, None, "budget", f"budget of {self.policy.budget} requests spent")
            raise BudgetExhausted(self.provider)

    def _transmit(self, url: str, request: httpx.Request) -> httpx.Response:
        """A request ``_claim`` cleared, sent: a connection that fails before any byte is sent tried again while the
        client's patience lasts, the answer logged, a block raised."""
        import httpx

        while True:
            sent = perf_counter()
            try:
                resp = self._http.send(request)
                break
            except httpx.HTTPError as e:
                self._log_request(request.method, str(request.url), type(e).__name__, seconds=perf_counter() - sent)
                wait = self._connect_wait() if isinstance(e, httpx.ConnectError) else None
                if wait is None:
                    self._fail(url, None, f"{type(e).__name__}: {e}")
                    raise AssertionError("unreachable")  # pragma: no cover
                said = f"{type(e).__name__}: {e}"
            log.info("%s couldn't be reached (%s); trying again in %.0f s", provider_name(self.provider), said, wait)
            self._wait(wait)
            self._pause(str(request.url))
            self._last_request = self._clock()
        self._log_request(request.method, str(request.url), _status_line(resp.status_code),
                          seconds=perf_counter() - sent)

        status, body = resp.status_code, resp.content
        challenge = is_challenge(resp.headers, body)
        if status in (403, 429) or challenge:
            reason = "challenge page" if challenge else f"HTTP {status}"
            self._blocked = ProviderBlocked(self.provider, url, status, reason)
            self._event(url, status, "blocked", reason)
            raise self._blocked
        return resp

    def _connect_wait(self) -> float | None:
        """How long to wait before trying again a connection that failed before any byte was sent: the next of
        ``_CONNECT_WAITS``, no longer than what is left of the client's patience; None once it is spent."""
        left = self._connect_patience - self._connect_waited
        if left <= 0:
            return None
        wait = min(_CONNECT_WAITS[min(self._connect_tries, len(_CONNECT_WAITS) - 1)], left)
        self._connect_tries += 1
        self._connect_waited += wait
        return wait

    def _pause(self, url: str) -> None:
        if self._last_request is None:
            return
        target = self._rng.uniform(*self.policy.delay)
        remaining = target - (self._clock() - self._last_request)
        if remaining > 0:
            self._wait(remaining)

    def _wait(self, seconds: float) -> None:
        """Spend the pause before the next request."""
        self._sleep(seconds)

    def _fail(self, url: str, status: int | None, message: str) -> None:
        self._errors_in_a_row += 1
        if self._errors_in_a_row >= self._max_errors:
            self._unavailable = True
        self._event(url, status, "error", message)
        raise ProviderError(self.provider, url, status, message)

    def _log_request(self, method: str, url: str, answer: str, *, cached: bool = False,
                     seconds: float | None = None) -> None:
        if log.isEnabledFor(logging.INFO):
            log.info("%s", request_line(self.provider, method, url, answer, cached=cached, seconds=seconds,
                                        used=self.requests_made, budget=self.policy.budget))

    def _event(self, url: str, status: int | None, decision: str, message: str | None) -> None:
        if decision in _FAILED:  # a request sent that the site answered with no answer: ``answered_any``
            self._failed += 1
        if self._on_event is not None:
            self._on_event(Event(provider=self.provider, url=url, status=status, decision=decision, message=message))

    def _paths(self, key: str) -> tuple[Path, Path]:
        return _cache_paths(self.cache_root, key)

    def _read_cache(self, key: str) -> Response | None:
        return _read_cached(self.cache_root, key)

    def _stamp(self) -> str:
        """Now, as a ``fetched_at``."""
        return self._wall_clock().astimezone(UTC).strftime(_STAMP)

    def _write_cache(self, key: str, url: str, status: int, headers: Mapping[str, str], body: bytes) -> None:
        body_path, _ = self._paths(key)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        _replace(body_path, gzip.compress(body, compresslevel=6))
        self._write_meta(key, url, status, headers)

    def _write_meta(self, key: str, url: str, status: int, headers: Mapping[str, str]) -> str:
        """Write a cached copy's meta, fetched now; return its ``fetched_at``."""
        stamp = self._stamp()
        meta = {"url": url, "status": status, "headers": dict(headers), "fetched_at": stamp}
        _replace(self._paths(key)[1], json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        return stamp


class ParallelClient(PoliteClient):
    """``PoliteClient``'s rules with several requests in flight at once: one provider's client for a pass the owner
    chose to read quicker than one request at a time (UG's artist directory, ug/directory.py: "Ignore the politeness
    for this", 2026-11-17).

    Every rule is ``PoliteClient``'s own, none copied: the cache first, robots.txt, the budget, the pause, a block
    (after one, nothing more is sent), the breaker, redirects one checked hop at a time, every request an event. Its
    workers (``workers`` threads, ``get_many``) clear each request one at a time (``_claim``, under a lock: the budget
    counted and the pause kept between two requests begun, so a ``policy.delay`` of [0, 0] sends them as quickly as
    the site answers), then send it each alone. The events a worker makes are held (``on_event`` is never called in a
    worker's thread, as it writes the database) and handed to ``on_event`` in the caller's thread by ``drain``, which
    ``get_many`` calls before each answer it yields. A plain ``get`` works as a ``PoliteClient``'s, in the caller's
    thread, its events drained the same way."""

    def __init__(self, *args: Any, workers: int = 1, on_event: Callable[[Event], None] | None = None,
                 **kwargs: Any):
        self._held: list[Event] = []
        self._held_lock = threading.Lock()
        self._deliver = on_event
        super().__init__(*args, on_event=self._hold, **kwargs)
        self.workers = max(1, int(workers))
        self._lock = threading.RLock()
        self._owner = threading.get_ident()  # the thread events are drained in: the one that made the client

    def _hold(self, event: Event) -> None:
        with self._held_lock:
            self._held.append(event)

    def drain(self) -> None:
        """Hand the events held since the last drain to ``on_event``, in this thread (the one that made the client), in
        the order they came."""
        with self._held_lock:
            events, self._held = self._held, []
        if self._deliver is not None:
            for event in events:
                self._deliver(event)

    def get(self, url: str, **kwargs: Any) -> Response:
        try:
            return super().get(url, **kwargs)
        finally:
            if threading.get_ident() == self._owner:
                self.drain()

    def _claim(self, url: str, request: httpx.Request) -> None:
        with self._lock:
            super()._claim(url, request)

    def _fail(self, url: str, status: int | None, message: str) -> None:
        with self._lock:
            super()._fail(url, status, message)

    def _event(self, url: str, status: int | None, decision: str, message: str | None) -> None:
        with self._lock:  # its workers make events: the count of failed requests is kept under its lock
            super()._event(url, status, decision, message)

    def get_many(self, urls: Sequence[str | tuple[str, Mapping[str, Any]]],
                 **get: Any) -> Iterator[tuple[str, Response | BaseException]]:
        """Each of ``urls`` (each once) asked as ``get`` asks it (``get``'s keywords: ``accept``, ``max_age``…, and a
        URL's own, given as a pair of it and them), up to ``workers`` in flight at once, each answer yielded in the order
        asked with what ``get`` returned or raised (a ``ProviderError``, ``BudgetExhausted``), the events drained
        before each.

        After a block, no more is begun: those in flight end as the block left them (asked before it, or refused
        after it with no request). Once the generator ends, however it ends (the caller stops at a block or a spent
        budget, an exception, Ctrl-C), nothing not begun is sent, and the requests in flight are waited for, so that
        no worker outlives it."""
        from concurrent.futures import ThreadPoolExecutor

        if self._blocked is not None:  # nothing is sent after a block
            raise ProviderBlocked(self.provider, None, self._blocked.status,
                                  f"blocked earlier this run ({self._blocked.message or self._blocked})")
        asked: dict[str, Mapping[str, Any]] = {}
        for item in urls:
            url, own = (item, {}) if isinstance(item, str) else item
            asked.setdefault(url, {**get, **own})
        todo = iter(list(asked.items()))
        pending: deque[tuple[str, Any]] = deque()
        blocked = False

        def one(url: str, kwargs: Mapping[str, Any]) -> Response | BaseException:
            try:
                return super(ParallelClient, self).get(url, **kwargs)
            except (ProviderError, BudgetExhausted) as e:
                return e

        pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix=f"{self.provider}-get")

        def begin() -> bool:
            if blocked or self._blocked is not None:
                return False
            item = next(todo, None)
            if item is None:
                return False
            pending.append((item[0], pool.submit(one, *item)))
            return True

        try:
            while len(pending) < self.workers and begin():
                pass
            while pending:
                url, future = pending.popleft()
                answer = future.result()
                self.drain()
                blocked = blocked or isinstance(answer, ProviderBlocked)
                begin()
                yield url, answer
        finally:
            for _, future in pending:
                future.cancel()
            pool.shutdown(wait=True, cancel_futures=True)
            self.drain()


class CachedAnswers:
    """One provider's answers in caracole's HTTP cache (``cache_dir/http/<provider>/``), read alone:
    ``cached`` as ``PoliteClient.cached`` reads them. It has no way to send a request, so it needs no
    client, no budget and no lock of its own, and reads while the provider cools down too."""

    def __init__(self, provider: str, cache_dir: Path):
        self.provider = provider
        self.cache_root = cache_dir / "http" / provider

    def cached(self, url: str, *, accept: Collection[int] = (200,)) -> Response | None:
        return cached_answer(self.cache_root, url, accept=accept)


def cached_answer(cache_root: Path, url: str, *, accept: Collection[int] = (200,)) -> Response | None:
    """The answer for ``url`` in the cache under ``cache_root`` when its status is in ``accept``, else None."""
    answer = _read_cached(cache_root, hashlib.sha256(url.encode("utf-8")).hexdigest())
    return answer if answer is not None and answer.status in accept else None


def _cache_paths(cache_root: Path, key: str) -> tuple[Path, Path]:
    d = cache_root / key[:2]
    return d / f"{key}.body", d / f"{key}.json"


def _read_cached(cache_root: Path, key: str) -> Response | None:
    body_path, meta_path = _cache_paths(cache_root, key)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        content = gzip.decompress(body_path.read_bytes())
        return Response(
            url=meta["url"], status=meta["status"], content=content,
            headers=meta.get("headers", {}), from_cache=True, fetched_at=meta.get("fetched_at"),
        )
    except (OSError, ValueError, EOFError, KeyError, TypeError):  # gzip's BadGzipFile is an OSError
        return None


def _replace(path: Path, data: bytes) -> None:
    """Write ``path`` whole: a temporary file beside it, then a rename."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
