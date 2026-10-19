"""HTTP for every provider: errors, responses and the polite client.

Rules this module enforces (plan §6, "Politeness"):

- every raw response worth keeping (a 200 or 404 the caller accepts) is cached
  forever, and a cached URL never costs a request again;
- a per-run request budget, with a random pause before every network request,
  redirect hops included;
- one request at a time;
- a URL its host's robots.txt disallows (``ROBOTS_DISALLOW``) is never requested,
  nor followed to: ``RobotsClosed``, a ``ProviderError`` that is no failure of the
  provider, so a caller may pass that URL over as one it may not read;
- a 403, a 429 or a challenge page raises ``ProviderBlocked``. Errors are never
  misses: callers must not turn any ``ProviderError`` into "not found".
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, Protocol, runtime_checkable

import httpx

from caracole.config import ProviderPolicy


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


# --- the polite client --------------------------------------------------------

_CACHED_STATUSES = (200, 404)
_KEPT_HEADERS = ("etag", "last-modified", "content-type", "location")
# Markers of a real challenge page. Normal UG pages also load Cloudflare's
# "/cdn-cgi/challenge-platform/" bot-management script, so that string alone
# is NOT evidence of a challenge.
_CHALLENGE_MARKERS = (
    b"_cf_chl_opt",
    b"<title>Just a moment...</title>",
    b"Attention Required! | Cloudflare",
    b"Enable JavaScript and cookies to continue",
)


def is_challenge(status: int, headers: Mapping[str, str], body: bytes) -> bool:
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
# on 2026-10-18 (docs/spike-2026-10-18.md). LaCuerda's robots.txt is empty and LRCLIB is
# an API, so their hosts have none.
ROBOTS_DISALLOW: Mapping[str, tuple[str, ...]] = {
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
    "tabs.ultimate-guitar.com": (
        "/forum/", "/tab/print?", "/components/", "/contribution/", "/user/tab/", "/download/public/",
        "/tab/download", "/tab/track/", "/tab/applicature/transpose", "/user/tab/view?*",
    ),
}
_ROBOTS = {
    host: [(rule, re.compile(".*".join(map(re.escape, rule.split("*"))))) for rule in rules]
    for host, rules in ROBOTS_DISALLOW.items()
}


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


def _site(url: str) -> str:
    """A URL's site: the last two labels of its host (each provider is on a plain .com or .net domain)."""
    return ".".join(httpx.URL(url).host.split(".")[-2:])


class PoliteClient:
    """One provider's HTTP client for one run: cache-first, budgeted, paced, never escalating.

    - A cached 200 or 404 is served without a request (``cache=True``) when the
      caller accepts its status; otherwise the URL is asked again. Only accepted
      answers are cached.
    - ``conditional=True`` revalidates a cached copy with If-None-Match /
      If-Modified-Since; a 304 returns the cached body.
    - Before every network request except the first, it pauses for a random
      time in ``policy.delay``, minus the time already elapsed.
    - ``policy.budget`` network requests per run; after that ``BudgetExhausted``.
    - A URL robots.txt disallows (``robots_disallows``) is never requested: when
      no cached answer is served, ``RobotsClosed``. Nor is a string httpx can't
      parse as a URL, which is a ``ProviderError`` at once.
    - Redirects are followed one hop at a time, at most three. Each hop is a
      request like any other (budget, pause, event) and must stay on the site
      asked for, or ``ProviderError``. A hop robots.txt closes isn't followed:
      ``RobotsClosed``, which the error breaker doesn't count (the site
      answered). The final answer is cached under the URL asked for.
    - 403, 429 or a challenge page raise ``ProviderBlocked``, and no further
      requests are made this run.
    - After ``max_consecutive_errors`` other errors, ``ProviderUnavailable``. Only a
      healthy answer resets the count: an accepted 5xx is returned but doesn't.
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
    ):
        self.provider = provider
        self.policy = policy
        self.cache_root = cache_dir / "http" / provider
        self.requests_made = 0
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
        stale = cached is not None and max_age is not None and self._older_than(cached, max_age)
        if cache and cached is not None and not conditional and not stale:
            return cached
        if stale and self.requests_made >= self.policy.budget:
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

        at = full  # the URL that answered: the one asked for, or the last redirect hop
        resp = self._send(at, self._http.build_request("GET", full, headers=headers))
        hops = 0
        while resp.next_request is not None:  # a redirect; its hop is a request like any other
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

        status, body = resp.status_code, resp.content
        if status == 304 and cached is not None:
            self._errors_in_a_row = 0
            self._event(at, status, "not_modified", None)
            return Response(url=full, status=304, content=cached.content, headers=cached.headers, from_cache=True)

        if status in accept:
            kept = {h: resp.headers[h] for h in _KEPT_HEADERS if h in resp.headers}
            if status in _CACHED_STATUSES:  # only what the caller accepts: a rejected 404 is asked again
                self._write_cache(key, full, status, kept, body)
            if status < 500:  # an accepted 5xx (LRCLIB's 503 for a miss) is no sign of health
                self._errors_in_a_row = 0
            self._event(at, status, "ok", None)
            return Response(url=full, status=status, content=body, headers=kept, from_cache=False)

        self._fail(at, status, f"HTTP {status}")
        raise AssertionError("unreachable")  # pragma: no cover

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals ---------------------------------------------------------

    def _older_than(self, cached: Response, max_age: timedelta) -> bool:
        if not cached.fetched_at:
            return True
        fetched = datetime.strptime(cached.fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        return self._wall_clock() - fetched > max_age

    def _send(self, url: str, request: httpx.Request) -> httpx.Response:
        """One network request, a redirect hop included: within the budget, after the pause."""
        if self._blocked is not None:
            raise ProviderBlocked(self.provider, url, self._blocked.status, "blocked earlier this run")
        if self._unavailable:
            raise ProviderUnavailable(self.provider, url, None, "too many errors this run")
        if self.requests_made >= self.policy.budget:
            if not self._budget_reported:
                self._budget_reported = True
                self._event(url, None, "budget", f"budget of {self.policy.budget} requests spent")
            raise BudgetExhausted(self.provider)

        self._pause()
        self.requests_made += 1
        self._last_request = self._clock()
        try:
            resp = self._http.send(request)
        except httpx.HTTPError as e:
            self._fail(url, None, f"{type(e).__name__}: {e}")
            raise AssertionError("unreachable")  # pragma: no cover

        status, body = resp.status_code, resp.content
        if status in (403, 429) or is_challenge(status, resp.headers, body):
            reason = "challenge page" if is_challenge(status, resp.headers, body) else f"HTTP {status}"
            self._blocked = ProviderBlocked(self.provider, url, status, reason)
            self._event(url, status, "blocked", reason)
            raise self._blocked
        return resp

    def _pause(self) -> None:
        if self._last_request is None:
            return
        target = self._rng.uniform(*self.policy.delay)
        remaining = target - (self._clock() - self._last_request)
        if remaining > 0:
            self._sleep(remaining)

    def _fail(self, url: str, status: int | None, message: str) -> None:
        self._errors_in_a_row += 1
        if self._errors_in_a_row >= self._max_errors:
            self._unavailable = True
        self._event(url, status, "error", message)
        raise ProviderError(self.provider, url, status, message)

    def _event(self, url: str, status: int | None, decision: str, message: str | None) -> None:
        if self._on_event is not None:
            self._on_event(Event(provider=self.provider, url=url, status=status, decision=decision, message=message))

    def _paths(self, key: str) -> tuple[Path, Path]:
        d = self.cache_root / key[:2]
        return d / f"{key}.body", d / f"{key}.json"

    def _read_cache(self, key: str) -> Response | None:
        body_path, meta_path = self._paths(key)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            content = gzip.decompress(body_path.read_bytes())
        except (OSError, ValueError, EOFError):
            return None
        return Response(
            url=meta["url"], status=meta["status"], content=content,
            headers=meta.get("headers", {}), from_cache=True, fetched_at=meta.get("fetched_at"),
        )

    def _write_cache(self, key: str, url: str, status: int, headers: Mapping[str, str], body: bytes) -> None:
        body_path, meta_path = self._paths(key)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "url": url, "status": status, "headers": dict(headers),
            "fetched_at": self._wall_clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for path, data in (
            (body_path, gzip.compress(body, compresslevel=6)),
            (meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8")),
        ):
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
