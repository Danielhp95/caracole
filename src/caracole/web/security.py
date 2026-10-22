"""What keeps ``caracole serve`` to its owner: host names, cross-origin writes, tokens.

- **Host names.** A page on another site can make a browser send requests to
  127.0.0.1 under a name of its own that it points there (DNS rebinding), and
  then read the answers. Every request must name the server by one of the names
  it answers to: localhost, the machine's name and its ``.local`` name, those
  ``--allow-host`` adds, or an IP address. An address can't be rebound: a page
  that names one has that address for its origin, the server's own.
- **Writes** must come from the server's own pages: Filippo Valsorda's check,
  the one Go's ``net/http.CrossOriginProtection`` makes, with ``Sec-Fetch-Site``
  and, where a browser sends no such header (plain HTTP to a LAN address),
  ``Origin`` against ``Host``. Every form also carries a token the server made
  when it started, which another site can't read.
- **An access token**, optional, for a server on the LAN: a sign-in page sets a
  cookie holding a digest of it, never the token itself.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

SESSION_COOKIE = "caracole_session"
LOOPBACK = ("localhost", "127.0.0.1", "::1")
WILDCARDS = ("", "0.0.0.0", "::")
_NAME = re.compile(r"[a-z0-9._-]+|[0-9a-f:.]+")
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def host_name(header: str | None) -> str | None:
    """The name a ``Host`` header gives, lowercase, without its port or a final dot; None if it isn't one."""
    if not header:
        return None
    text = header.strip().lower()
    if text.startswith("["):
        name, sep, rest = text[1:].partition("]")
        if not sep or (rest and not (rest[:1] == ":" and rest[1:].isdigit())):
            return None
    else:
        name, sep, port = text.partition(":")
        if sep and not port.isdigit():
            return None
    name = name.rstrip(".")
    return name if name and _NAME.fullmatch(name) else None


def allowed_hosts(address: str, *, hostname: str = "", extra: Iterable[str] = ()) -> frozenset[str]:
    """The names the server answers to: loopback, ``address`` unless it's a wildcard, ``hostname`` and
    its mDNS name (``hostname.local``), ``extra``. ``answers_to`` also takes any IP address.

    A name in ``extra`` may come with a port, which goes; ValueError for one that isn't a host name.
    """
    names = set(LOOPBACK)
    bound = address.strip().strip("[]").lower()
    if bound not in WILDCARDS:
        names.add(bound)
    own = hostname.strip().lower().rstrip(".")
    if own:
        names.update((own, own.split(".")[0] + ".local"))
    for given in extra:
        name = host_name(given)
        if name is None:
            raise ValueError(f"{given.strip()!r} isn't a host name")
        names.add(name)
    return frozenset(names)


def answers_to(name: str | None, allowed: frozenset[str]) -> bool:
    """Whether the server answers to the name a ``Host`` header gives (``host_name``): one it knows, or an
    IP address, which no other site can point at it."""
    if name is None:
        return False
    if name in allowed:
        return True
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def cross_origin_ok(method: str, headers: Mapping[str, str], host: str | None) -> bool:
    """Whether a request may change something: not a cross-origin write from a browser.

    ``headers`` has lowercase names. Reads always may. A browser that sends
    ``Sec-Fetch-Site`` says where the request comes from; one that sends only
    ``Origin`` has it compared with ``Host``. A client that sends neither is no
    browser, so no other site can be making it.
    """
    if method in _SAFE_METHODS:
        return True
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site in ("same-origin", "none")
    origin = headers.get("origin")
    if origin is None:
        return True
    try:
        netloc = urlsplit(origin).netloc
    except ValueError:
        return False
    return bool(netloc) and bool(host) and netloc.lower() == host.strip().lower()


def own_page_read(headers: Mapping[str, str]) -> bool:
    """Whether a read of the JSON API comes from the server's own pages (or from no browser at all).

    Another site can't read the answers, but its page could still make the
    server search, again and again: a browser that says it is fetching for
    another site (``Sec-Fetch-Site`` cross-site or same-site) is refused. One
    that sends no such header (curl, an older browser) is let through.
    """
    site = headers.get("sec-fetch-site")
    return site is None or site in ("same-origin", "none")


def same_token(given: str | None, expected: str) -> bool:
    """Whether a token is the expected one, compared in constant time; nothing never matches."""
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def session_value(access_token: str) -> str:
    """What the sign-in cookie holds: a digest of the access token, the same after a restart."""
    return hmac.new(access_token.encode("utf-8"), b"caracole serve session", hashlib.sha256).hexdigest()


def session_cookie(header: str | None) -> str | None:
    """The sign-in cookie's value in a ``Cookie`` header, if it has one.

    Read pair by pair, never with ``http.cookies``: cookies ignore ports, so another app on the same
    host can set one that parser stops at (JSON, a space, no value at all), and it would take
    caracole's with it. Of two sign-in cookies, the first, which the browser sends for the longer path.
    """
    for pair in (header or "").split(";"):
        name, sep, value = pair.partition("=")
        if not sep or name.strip() != SESSION_COOKIE:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        return value or None
    return None
