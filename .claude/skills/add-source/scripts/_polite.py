"""Polite HTTP for the add-source scripts: caracole's own user agent, robots.txt honoured (its Allow, Disallow with
`*` and `$`, and Crawl-delay), one request at a time with a pause between, and a 403, a 429 or a challenge page as a
block that stops everything. The standard library alone, so it runs anywhere caracole's checkout does.

This is what caracole's own http.py does for a source once it is built; the scripts here are for the research and
the fixtures before that, and keep to the same rules (AGENTS.md, Invariants, Politeness).
"""

from __future__ import annotations

import gzip
import http.client
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# caracole's own user agent (src/caracole/config.py DEFAULT_USER_AGENT). Never another.
USER_AGENT = "caracole/0.1 (personal tab library)"
MIN_DELAY = 6.0  # seconds between two requests to a host, at least; a robots.txt Crawl-delay above it wins

CHALLENGE = re.compile(
    r"cf-chl|challenge-platform|Just a moment\.\.\.|Attention Required!|captcha|"
    r"Checking your browser|DDoS protection by|px-captcha|_Incapsula_Resource", re.I)


class _FinalResponse(http.client.HTTPResponse):
    """An answer read past every interim 1xx. http.client skips 100 Continue alone, so a 103 Early Hints (nginx sends
    them; songsterr.com did) would be taken for the answer, with no body."""

    def _read_status(self):
        while True:
            version, status, reason = super()._read_status()
            if not 102 <= status < 200:
                return version, status, reason
            http.client.parse_headers(self.fp)  # the hints' headers, dropped


class _Connection(http.client.HTTPConnection):
    response_class = _FinalResponse


class _SecureConnection(http.client.HTTPSConnection):
    response_class = _FinalResponse


class _Plain(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_Connection, req)


class _Secure(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_SecureConnection, req, context=self._context)


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect comes back as the answer: `Polite.get` follows it, one paced, counted, robots-checked hop at a
    time, as caracole's PoliteClient does."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_Plain, _Secure, _NoRedirects)
REDIRECTS = (301, 302, 303, 307, 308)


class Blocked(RuntimeError):
    """The site answered a 403, a 429 or a challenge: stop asking it."""


@dataclass
class Answer:
    url: str
    status: int
    headers: http.client.HTTPMessage  # case-insensitive: headers["etag"] is headers["ETag"]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


@dataclass
class Robots:
    """The `User-agent: *` group of a robots.txt (or caracole's own, if it has one), and its sitemaps."""

    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    sitemaps: list[str] = field(default_factory=list)
    named_agents: dict[str, list[str]] = field(default_factory=dict)  # other groups: agent → their Disallow lines

    @classmethod
    def parse(cls, text: str) -> Robots:
        robots = cls()
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[str, str]] = []
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "sitemap":
                robots.sitemaps.append(value)
                continue
            if key == "user-agent":
                if in_rules:
                    groups.append((agents, rules))
                    agents, rules, in_rules = [], [], False
                agents.append(value.lower())
            elif key in ("allow", "disallow", "crawl-delay"):
                in_rules = True
                rules.append((key, value))
        if agents:
            groups.append((agents, rules))
        mine = [g for g in groups if any(a.startswith("caracole") for a in g[0])]
        chosen = mine or [g for g in groups if "*" in g[0]]
        for _, group_rules in chosen:
            for key, value in group_rules:
                if key == "allow" and value:
                    robots.allow.append(value)
                elif key == "disallow" and value:
                    robots.disallow.append(value)
                elif key == "crawl-delay":
                    try:
                        robots.crawl_delay = float(value)
                    except ValueError:
                        pass
        for group_agents, group_rules in groups:
            if "*" in group_agents:
                continue
            for agent in group_agents:
                robots.named_agents[agent] = [v for k, v in group_rules if k == "disallow"]
        return robots

    @staticmethod
    def _matches(rule: str, path: str) -> bool:
        pattern = re.escape(rule).replace(r"\*", ".*")
        if pattern.endswith(r"\$"):
            pattern = pattern[:-2] + "$"
        return re.match(pattern, path) is not None

    def allowed(self, path_and_query: str) -> bool:
        """Google's rule: the longest matching rule wins, Allow on a tie; no rule, allowed."""
        best: tuple[int, bool] = (-1, True)
        for rule, verdict in [(r, True) for r in self.allow] + [(r, False) for r in self.disallow]:
            if self._matches(rule, path_and_query):
                length = len(rule)
                if length > best[0] or (length == best[0] and verdict):
                    best = (length, verdict)
        return best[1]


class Polite:
    """One host, one request at a time, its robots.txt read first."""

    def __init__(self, base: str, *, delay: float = MIN_DELAY, max_requests: int = 12, log=sys.stderr):
        parts = urllib.parse.urlsplit(base if "://" in base else "https://" + base)
        self.root = f"{parts.scheme}://{parts.netloc}"
        self.host = parts.netloc
        self.delay = max(delay, MIN_DELAY)
        self.max_requests = max_requests
        self.made = 0
        self.last = 0.0
        self.log = log
        self.robots = Robots()
        robots = self._get("/robots.txt", check=False)
        self.robots_answer = robots
        if robots.status == 200:
            self.robots = Robots.parse(robots.text)
            if self.robots.crawl_delay:
                self.delay = max(self.delay, self.robots.crawl_delay)

    def path_of(self, url: str) -> str:
        parts = urllib.parse.urlsplit(urllib.parse.urljoin(self.root + "/", url))
        if parts.netloc != self.host:
            raise ValueError(f"{url} is not on {self.host}")
        return parts.path + (f"?{parts.query}" if parts.query else "")

    def get(self, url: str) -> Answer:
        """Ask for a page robots.txt allows, following redirects on this host, each hop checked and paced; a
        redirect to another host, or to a path robots.txt closes, is not followed."""
        path = self.path_of(url)
        for _ in range(5):
            if not self.robots.allowed(path):
                raise PermissionError(f"robots.txt closes {path}: not asked")
            answer = self._get(path, check=True)
            location = answer.headers.get("Location")
            if answer.status not in REDIRECTS or not location:
                return answer
            try:
                path = self.path_of(location)
            except ValueError:
                raise RuntimeError(f"{answer.url} redirects to {location}, another host: probe that one") from None
        raise RuntimeError(f"{url}: more than 5 redirects")

    def _get(self, path: str, *, check: bool) -> Answer:
        if self.made >= self.max_requests:
            raise RuntimeError(f"the budget of {self.max_requests} requests is spent")
        wait = self.last + self.delay - time.monotonic()
        if self.made and wait > 0:
            time.sleep(wait)
        url = self.root + path
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
        self.made += 1
        try:
            with _OPENER.open(request, timeout=30) as response:  # noqa: S310 - the host is the user's choice
                status, headers, body = response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            status, headers, body = error.code, error.headers or http.client.HTTPMessage(), error.read() or b""
        self.last = time.monotonic()
        if headers.get("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        answer = Answer(url, status, headers, body)
        moved = f" to {headers.get('Location')}" if status in REDIRECTS else ""
        print(f"  GET {path} → {status}{moved} ({len(body):,} bytes)", file=self.log)
        if check and (status in (403, 429) or (status in (200, 503) and CHALLENGE.search(answer.text[:20000]))):
            raise Blocked(f"{url} answered {status}{' with a challenge page' if status != 403 else ''}: stop asking")
        return answer


def gunzip_if_needed(body: bytes) -> bytes:
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
