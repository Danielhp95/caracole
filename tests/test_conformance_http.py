"""http.py for the phone (lane http-client): its rules as data and its answers as vectors, which the phone's
``core.http`` (``Urls``, ``Robots``, ``HttpRules``, ``PoliteClient``, ``CachedAnswers``) must give back exactly
(docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §5.1; the corpus spec).

Runtime data (tests/conformance/data/caracole/http/):

- ``robots.json``: ``http.ROBOTS_DISALLOW``, ``{"hosts": {host: [rule, …]}}``, each host's rules in order;
- ``http.json``: http.py's other constants (``_CACHED_STATUSES``, ``_KEPT_HEADERS``, ``_CHALLENGE_MARKERS``, the 32768
  bytes a challenge is looked for in, ``_MAX_REDIRECTS``, ``RETRY_AFTER_503``, ``_RETRY_JITTER``, ``NOT_A_URL``);
- ``idna.json``: what the ``idna`` package httpx encodes a host with reads (its codepoint classes, joining types and
  scripts, ``idnadata``'s, as ``[start, end)`` ranges) and what it asks ``unicodedata`` beyond the phone's tables
  (each code point's bidirectional class as runs, and the code points with no name).

Vectors (tests/conformance/vectors/http/):

- ``urls.jsonl``: httpx's URL as caracole asks for one: ``url`` (``str(httpx.URL(u))``, its ``raw_path``, ``host``,
  ``netloc`` and whether it is absolute), ``with_params`` (``httpx.URL(u, params=…)``: the params replace the query),
  ``site`` (``http._site``) and ``resolve`` (the next request a redirect makes, ``Client._redirect_url``); an error is
  ``{"err": "<type>: <message>"}``;
- ``robots.jsonl``: ``robots_disallows`` of every URL tests/test_http.py names, each rule matched and nearly matched;
- ``rules.jsonl``: ``stale``, ``retry_after``, ``is_challenge``, and ``decode``: what httpx's content decoders
  make of a body under its ``Content-Encoding`` headers (its bytes, or the DecodingError zlib names);
- ``client.jsonl``: one scripted session of a ``PoliteClient`` for each case of tests/test_http.py (and a few more):
  its steps and what each came to, every request sent with its headers, the site's answers in turn, the events, the
  sleeps for the draws given, and the cache it left.

A string the corpus can't carry as one (a lone surrogate, or one too long for a line to read) is
``{"parts": [text | {"repeat": text, "times": n} | {"utf16": [unit, …]}]}``; a body is ``{"text"}``, ``{"base64"}``,
``{"parts"}`` of such or ``{"repeat"}``, and one of more than 4 KiB in what a session left only its ``{"sha256",
"size"}``.

The pauses are compared for the draws a session gives (``draws``: each ``random()`` the client's rng returns, in turn,
so ``uniform(a, b)`` is ``a + (b - a) * u`` as Python's is), never against Python's random.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
import unicodedata
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx
import idna
import idna.idnadata

import test_http as T
from caracole import http
from caracole.config import ProviderPolicy
from helpers.azlyrics_site import artist_page, fixture as azlyrics_fixture, lyrics_page
from helpers.corpus import DATA, VECTORS, check, fixture_ref, jsonl

MADE_BY = "tests/test_conformance_http.py"
HTTP = VECTORS / "http"
DATA_HTTP = DATA / "http"


# --- carrying strings and bodies ------------------------------------------------------------------------------


def _surrogate(c: str) -> bool:
    return 0xD800 <= ord(c) <= 0xDFFF


def pystr(s: str) -> Any:
    """``s`` as the corpus carries it: itself, or its parts (a run of one character as a repeat, a lone surrogate as
    its UTF-16 unit) when it holds a surrogate or is longer than 4096 characters."""
    if len(s) <= 4096 and not any(_surrogate(c) for c in s):
        return s
    parts: list[Any] = []
    text = []
    i = 0
    while i < len(s):
        c = s[i]
        if _surrogate(c):
            if text:
                parts.append("".join(text))
                text = []
            parts.append({"utf16": [ord(c)]})
            i += 1
            continue
        j = i
        while j < len(s) and s[j] == c:
            j += 1
        if j - i >= 64:
            if text:
                parts.append("".join(text))
                text = []
            parts.append({"repeat": c, "times": j - i})
        else:
            text.append(s[i:j])
        i = j
    if text:
        parts.append("".join(text))
    return {"parts": parts}


def body_in(b: bytes) -> dict[str, Any]:
    """A body given to the phone: its text or its bytes; a long one as a repeat of its first bytes."""
    if len(b) > 65536:
        for unit in range(1, 513):
            if len(b) % unit == 0 and b[:unit] * (len(b) // unit) == b:
                return {"repeat": b[:unit].decode("utf-8"), "times": len(b) // unit}
        raise ValueError("a long body the corpus carries is a repeat")
    try:
        text = b.decode("utf-8")
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(b).decode("ascii")}
    return {"text": text}


def body_out(b: bytes) -> dict[str, Any]:
    """A body a session came to: itself up to 4 KiB, else its digest and size."""
    if len(b) > 4096:
        return {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
    return body_in(b)


def repeat(text: str, times: int) -> dict[str, Any]:
    return {"repeat": text, "times": times}


def body_bytes(spec: Any) -> bytes:
    """The bytes of a body the corpus carries (the inverse of body_in, and of the given forms)."""
    if isinstance(spec, bytes):
        return spec
    if isinstance(spec, str):
        return spec.encode("utf-8")
    if "text" in spec:
        return spec["text"].encode("utf-8")
    if "base64" in spec:
        return base64.b64decode(spec["base64"])
    if "repeat" in spec:
        return spec["repeat"].encode("utf-8") * spec["times"]
    if "parts" in spec:
        return b"".join(body_bytes(p) for p in spec["parts"])
    if "fixture" in spec:
        return (Path(__file__).parent / "fixtures" / spec["fixture"]).read_bytes()
    raise TypeError(spec)


def err(e: BaseException) -> dict[str, str]:
    return {"err": f"{type(e).__name__}: {e}"}


# --- runtime data -------------------------------------------------------------------------------------------


def robots_json() -> str:
    return json.dumps({"hosts": {host: list(rules) for host, rules in http.ROBOTS_DISALLOW.items()}},
                      ensure_ascii=False, indent=1) + "\n"


CHALLENGE_HEAD = 32768  # is_challenge's: the bytes of a body it looks for a marker in (test_the_head_is_32768_bytes)


def http_json() -> str:
    data = {
        "cached_statuses": list(http._CACHED_STATUSES),
        "kept_headers": list(http._KEPT_HEADERS),
        "challenge_markers": [m.decode("ascii") for m in http._CHALLENGE_MARKERS],
        "challenge_head": CHALLENGE_HEAD,
        "max_redirects": http._MAX_REDIRECTS,
        "retry_after_503": dict(http.RETRY_AFTER_503),
        "retry_jitter": http._RETRY_JITTER,
        "not_a_url": http.NOT_A_URL,
    }
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def _ranges(encoded) -> list[list[int]]:
    """idna's intranges (``start << 32 | end``, end exclusive) as ``[start, end]`` pairs."""
    return [[r >> 32, r & 0xFFFFFFFF] for r in encoded]


def _runs(value: Callable[[str], Any]) -> list[list[Any]]:
    runs: list[list[Any]] = []
    prev = object()
    for cp in range(0x110000):
        v = value(chr(cp))
        if v != prev:
            runs.append([cp, v])
            prev = v
    return runs


def _has_name(c: str) -> bool:
    try:
        unicodedata.name(c)
    except ValueError:
        return False
    return True


def idna_json() -> str:
    d = idna.idnadata
    unnamed = [[start, end] for start, end in _pairs(_runs(lambda c: not _has_name(c)))]
    data = {
        "idna": idna.__version__,
        "idnadata": d.__version__,
        "unicodedata": unicodedata.unidata_version,
        "classes": {name: _ranges(d.codepoint_classes[name]) for name in ("PVALID", "CONTEXTJ", "CONTEXTO")},
        "joining": {jt: _ranges(r) for jt, r in d.joining_types.items()},
        "scripts": {name: _ranges(d.scripts[name]) for name in ("Greek", "Han", "Hebrew", "Hiragana", "Katakana")},
        "bidi": _runs(unicodedata.bidirectional),
        "unnamed": unnamed,
    }
    lines = ['{']
    keys = list(data)
    for i, key in enumerate(keys):
        tail = "," if i < len(keys) - 1 else ""
        lines.append(f" {json.dumps(key)}: {json.dumps(data[key], ensure_ascii=False, separators=(',', ':'))}{tail}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _pairs(runs: list[list[Any]]) -> list[tuple[int, int]]:
    """The ``[start, end)`` ranges where a boolean run is true."""
    out = []
    for i, (start, value) in enumerate(runs):
        if value:
            end = runs[i + 1][0] if i + 1 < len(runs) else 0x110000
            out.append((start, end))
    return out


def test_robots_json_is_http_pys_rules():
    check(DATA_HTTP / "robots.json", robots_json())


def test_http_json_is_http_pys_constants():
    check(DATA_HTTP / "http.json", http_json())


def test_idna_json_is_what_idna_reads():
    check(DATA_HTTP / "idna.json", idna_json())


def test_the_head_is_32768_bytes():
    marker = http._CHALLENGE_MARKERS[0]
    assert http.is_challenge({}, b"x" * (CHALLENGE_HEAD - len(marker)) + marker)
    assert not http.is_challenge({}, b"x" * (CHALLENGE_HEAD - len(marker) + 1) + marker)


def test_a_code_point_with_no_name_is_one_of_few_kinds():
    # idna asks unicodedata.name of the code point before a joiner; the phone reads idna.json's "unnamed".
    kinds = {unicodedata.category(chr(cp)) for start, end in json.loads(idna_json())["unnamed"]
             for cp in range(start, end)}
    assert kinds <= {"Cc", "Cn", "Cs", "Co", "Lo"}


# --- urls.jsonl ---------------------------------------------------------------------------------------------

TABS, WWW = T.TABS, T.WWW

URLS = [
    *T.ROBOTS_CLOSED, *T.READ_BY_CARACOLE, *T.NOT_URLS.values(), T.OLD, T.NEW, T.SEARCH,
    "https://tabs.ultimate-guitar.com/tab/1", "https://x.test/1", "https://lrclib.net/api/get",
    "https://www.ultimate-guitar.com/sitemap40.xml", "https://acordes.lacuerda.net/artist_1/",
    "https://gametabs.net/tabs/actraiser/fillmore",
    # case, ports, the default ports
    "HTTPS://Tabs.Ultimate-Guitar.COM/Tab/1", "https://tabs.ultimate-guitar.com:443/tab/1",
    "http://tabs.ultimate-guitar.com:80/tab/1", "http://x.test:8080/a", "https://x.test:8443/", "http://x.test:/",
    "http://x.test:abc/", "http://x.test:99999/", "ws://x.test:80/", "wss://x.test:443/", "ftp://x.test:21/f",
    "http://x.test:0443/", "https://x.test:+443/",
    # paths, queries and fragments as httpx quotes them
    "https://x.test/a b", "https://x.test/caf\u00e9?q=ni\u00f1o#frag ment", "https://x.test/a/./b/../c",
    "https://x.test/a/b/..", "https://x.test/../a", "https://x.test/./", "https://x.test/a/%2e%2e/b",
    "https://x.test/%7euser/%zz/%E6%96%91/%e6", "https://x.test/a%2Fb", "https://x.test/?a=1&b=2#",
    "https://x.test/?", "https://x.test#", "https://x.test", "https://x.test?q", "https://x.test/p?q=\"<>`{}|\\^'",
    "https://x.test/p\"<>`{}|\\^'", "https://x.test/#a b\"<>`{}#", "https://x.test/p;params?q;r",
    "https://x.test/\U0001F600?\U0001F600#\U0001F600", "https://x.test/a\u2028b", "https://x.test/\u0085",
    "https://x.test/%", "https://x.test/%%41", "https://x.test/~-._!$&'()*+,;=:@",
    "https://lrclib.net/api/search?track_name=%E6%96%91%E9%A9%AC&artist_name=x y+z",
    # hosts
    "https://[::1]:8080/a", "https://[::ffff:192.168.0.1]/", "https://[::zz]/", "https://[::1/",
    "https://999.1.1.1/", "https://1.2.3.4/", "https://01.2.3.4/", "https://1.2.3/", "https://ex ample.com/",
    "https://a_b.com/", "https://a%41.com/", "https://x.test.", "https://Ä.example/", "https://m\u00fcller.de/",
    "https://\u4e2d\u56fd.icom.museum/", "https://xn--mller-kva.de/", "https://xn--zz.com/",
    "https://B\u00fccher.example/", "https://xn--fiqs8s.icom.museum/x", "https://-bad\u00e9.com/",
    "https://bad\u00e9-.com/", "https://ab--\u00e9.com/", "https://\u0301\u00e9.com/", "https://e\u0301.com/",
    "https://\u05d0\u05d1.com/", "https://\u05d0a.com/", "https://a\u200cb.com/", "https://\u0915\u094d\u200cb.com/",
    "https://xn--ab-m1t.com/", "https://xn--ab-j1t.com/", "https://xn--11b2ezcs70k.com/", "https://xn--11b2ezcw70k.com/",
    "https://l\u00b7l.com/", "https://a\u00b7.com/", "https://\u30fb\u30a2.jp/", "https://\u30fbx.jp/",
    "https://\u0661\u06f1.com/", "https://\u00e9" + "a" * 70 + ".com/", "https://\u00e9." + "a." * 130 + "com/",
    "https://\u00e9\u3002com/", "https://\u00e9\uff0ecom/", "https://\u00e9..com/", "https://.\u00e9.com/",
    "https://\u00c9.com/", "https://\u2163.com/", "https://\ufb01.com/", "https://user@\u00e9.com/",
    "https://u:p@x.test/", "https://us er:p\u00e4ss@x.test/", "https://@x.test/", "https://a@b@x.test/",
    # no scheme, relative, broken
    "//x.test/a", "/relative/path", "relative", "rel:ative", ":bad", "//", "", "mailto:x@y.test", "https:/x.test",
    "https:x.test", "https:///path", "https://x.test/\x7f", "https://x.test/\t", "https://x.test/\x00",
    "https://x.test/" + "a" * 65536, "https://x.test/" + "a" * 65520, "https://\x01x.test/", "1http://x.test/",
    "h-t+t.p://x.test/", "HTTP://X.TEST/A",
]

PARAMS = [
    ("https://lrclib.net/api/get", [("track_name", "斑马斑马"), ("duration", "253")]),
    ("https://lrclib.net/api/get", [("track_name", "Other")]),
    ("https://lrclib.net/api/search", [("track_name", "x y"), ("artist_name", "a+b&c=d")]),
    ("https://lrclib.net/api/search?old=1", [("q", "new")]),
    ("https://x.test/p?old=1#frag", [("q", "#?/%~-._*'()!")]),
    ("https://x.test/p", [("a", ""), ("", "b"), ("a", "2")]),
    ("https://x.test/p", [("k", "\U0001F600 \u00e9\u00a0")]),
    ("https://x.test/p", []),
    ("https://x.test/p?old=1", []),
    ("https://tabs.ultimate-guitar.com/tab/busy", [("q", "x y")]),
    ("https://x.test/p", [("k", "a\x00b")]),
    ("https://x.test/p", [("k", "a\ud800b")]),
    ("https://x.test/a\nb", [("k", "v")]),
    ("https://acordes.lacuerda.net/busca.php", [("exp", "soda stereo"), ("met", "1")]),
    ("https://api.megalobiz.com/search", [("qry", "Hotel California Eagles"), ("type", "lrc")]),
]

RESOLVE = [
    (T.OLD, "/tab/a/new-chords-1"), (T.OLD, "new-chords-1"), (T.OLD, "../x"), (T.OLD, "./"), (T.OLD, "."),
    (T.OLD, ".."), (T.OLD, "?q=1"), (T.OLD, "#f"), (T.OLD, ""), (T.OLD, "//www.ultimate-guitar.com/artist/a_1"),
    (T.OLD, WWW + "/artist/a_1"), (T.OLD, "https://accounts.example.com/login?next=/tab/a"), (T.OLD, "https:///path"),
    (T.OLD, "https:path"), (T.OLD, "http:/x"), (T.OLD, "HTTPS://TABS.ULTIMATE-GUITAR.COM/x"), (T.OLD, "/a b"),
    (T.OLD, "/caf\u00e9"), (T.OLD + "#top", "/x"), (T.OLD + "#top", "/x#here"), (T.OLD, "/a\nb"),
    (T.OLD, "https://[::zz]/"), (T.OLD, "  /x"), (T.OLD, "/tab/print?id=1"), (T.OLD, "http://tabs.ultimate-guitar.com/x"),
    (T.OLD, "/a/./b/../../c"), (T.OLD, "../../../../x"), (T.OLD, "a//b"), (T.OLD, "//"), (T.OLD, "///x"),
    ("https://acordes.lacuerda.net/artist_1/", "https://acordes.lacuerda.net/artist_1/"),
    ("https://x.test/a/b?q=1", "?"), ("https://x.test/a/b?q=1", "c;p?x"), ("https://x.test/a;p/b", "c"),
    ("https://x.test:8443/a/b", "/c"), ("https://x.test/a/b", "mailto:x@y.test"), ("https://x.test/a/b", "//y.test"),
    ("https://x.test/a/b", "//y.test:80/z"), ("http://x.test/a", "https://x.test/b"), ("https://x.test/", "\u00e9"),
    ("https://x.test/a/b", "c/./d/../e"), ("https://x.test/a/b", "c/.."), ("https://x.test/a/b/", "../.."),
    ("https://x.test", "c"), ("https://x.test?q=1", "#f"), ("https://x.test/a", "//m\u00fcller.de/x"),
    ("https://x.test/a", "https://user:pw@x.test/b"), ("https://x.test/a", "/%zz"),
]


def _url_out(u: str) -> Any:
    try:
        url = httpx.URL(u)
        out = {"str": pystr(str(url)), "raw_path": pystr(url.raw_path.decode("ascii")),
               "netloc": url.netloc.decode("ascii"),
               "absolute": url.is_absolute_url, "scheme": url.scheme, "port": url.port}
    except (httpx.InvalidURL, ValueError) as e:
        return err(e)
    try:
        out["host"] = url.host
    except ValueError as e:
        out["host"] = err(e)
    try:
        out["site"] = http._site(u)
    except ValueError as e:
        out["site"] = err(e)
    return out


def _with_params(u: str, params: list[tuple[str, str]]) -> Any:
    try:
        return pystr(str(httpx.URL(u, params=params)))
    except (httpx.InvalidURL, ValueError) as e:
        return err(e)


def _resolve(base: str, location: str) -> Any:
    client = httpx.Client()
    request = client.build_request("GET", base)
    # A site's header is bytes: httpx reads it as ASCII, else UTF-8, else Latin-1 (the phone's RealTransport too).
    response = httpx.Response(302, headers=[(b"Location", location.encode("utf-8", "surrogatepass"))], request=request)
    try:
        return str(client._redirect_url(request, response))
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as e:  # InvalidURL: no HTTPError, so a client lets it out
        return err(e)


def url_records() -> list[dict[str, Any]]:
    records = [{"fn": "url", "args": [pystr(u)], "out": _url_out(u)} for u in URLS]
    records += [{"fn": "with_params", "args": [pystr(u), [[k, pystr(v)] for k, v in p]], "out": _with_params(u, p)}
                for u, p in PARAMS]
    records += [{"fn": "resolve", "args": [pystr(b), pystr(loc)], "out": _resolve(b, loc)} for b, loc in RESOLVE]
    return records


def test_urls_jsonl_is_httpx_s_urls():
    check(HTTP / "urls.jsonl", jsonl(url_records(), corpus="http/urls", made_by=MADE_BY))


def test_the_urls_cover_what_caracole_asks_and_what_httpx_refuses():
    outs = [r["out"] for r in url_records() if r["fn"] == "url"]
    assert sum("err" in o for o in outs) >= 15 and sum("str" in o for o in outs) >= 60
    assert any("IDNAError" in str(o.get("host")) for o in outs if "str" in o)


# --- robots.jsonl -------------------------------------------------------------------------------------------


def _rule_cases() -> list[str]:
    """For each rule of each host, a URL it closes and one it nearly closes."""
    out = []
    for host, rules in http.ROBOTS_DISALLOW.items():
        for rule in rules:
            path = rule.removesuffix("$").replace("*", "x")
            out.append(f"https://{host}{path}")
            if rule.endswith("$"):
                out.append(f"https://{host}{path}x")
            else:
                out.append(f"https://{host}{path[:-1]}")
            out.append(f"https://{host.upper()}:8443{path}")
    return out


ROBOTS_URLS = [
    *T.ROBOTS_CLOSED, *T.READ_BY_CARACOLE, *T.NOT_URLS.values(), *_rule_cases(),
    TABS + "/tab/track/ave-fenix-guitar-pro-1149792", "https://acordes.lacuerda.net/tabs/e/index0.html",
    "https://www.azlyrics.com/search/?q=mononoke", "https://www.azlyrics.com/suggest/?q=mononoke",
    "https://www.azlyrics.com/p/pomme.html", "https://www.azlyrics.com/lyrics/pomme/mononoke.html",
    "https://gametabs.net/x.php", "https://gametabs.net/x.php?a=1", "https://gametabs.net/x.phpx",
    "https://gametabs.net/tabs?game=1", "https://gametabs.net/tabs", "https://www.harptabs.com/tab/12/edit",
    "https://www.harptabs.com/tab/12/view", "https://harptabs.com/song?_rsc=1", "https://harptabs.com/song?a=1&_rsc=x",
    "https://tabs.ultimate-guitar.com/tab/pr%69nt?id=1", "https://musescore.com/search/caf\u00e9",
    "https://tabs.ultimate-guitar.com/tab/print?id=1#frag", "http://tabs.ultimate-guitar.com/tab/print?id=1",
    "https://tabs.ultimate-guitar.com", "https://tabs.ultimate-guitar.com?x", "https://i.ytimg.com/sb/abc/x.jpg",
    "https://i.ytimg.com/vi/abc/hqdefault.jpg", "https://megalobiz.com/lrc/details/1", "https://megalobiz.com/favicon.ico",
    "https://xn--mller-kva.de/search/", "https://m\u00fcller.de/", "https://xn--zz.com/", "https://xn--ab-m1t.com/", "relative/path", "",
]


def robots_records() -> list[dict[str, Any]]:
    return [{"fn": "robots_disallows", "args": [pystr(u)], "out": http.robots_disallows(u)} for u in ROBOTS_URLS]


def test_robots_jsonl_is_robots_disallows():
    check(HTTP / "robots.jsonl", jsonl(robots_records(), corpus="http/robots", made_by=MADE_BY))


# --- rules.jsonl --------------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
AT = T.AT


def _stamp(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


STALE = [
    (False, None, NOW, 30), (True, "2026-09-19T03:30:00Z", NOW, 30), (True, "2026-09-17T03:30:00Z", NOW, 30),
    (True, None, NOW, 30), (True, "2026-09-18T03:30:00Z", NOW, 30), (True, "2026-09-18T03:29:59Z", NOW, 30),
    (True, "2026-10-18T03:30:00Z", NOW, 0), (True, "2026-10-18T03:30:01Z", NOW, 0), (True, "2026-10-18T03:29:59Z", NOW, 0),
    (False, "2020-01-01T00:00:00Z", NOW, 1), (True, "2026-11-27T00:00:00Z", datetime(2026, 11, 27, tzinfo=UTC), 30),
]

RETRY_AFTER = [
    {}, {"Retry-After": "1"}, {"retry-after": "0"}, {"RETRY-AFTER": " 5 "}, {"Retry-After": "1.5"},
    {"Retry-After": "-1"}, {"Retry-After": "soon"}, {"Retry-After": ""}, {"Retry-After": "120"},
    {"Retry-After": "99999999999999999999"}, {"Retry-After": "\u0663"}, {"Retry-After": "\uff11"},
    {"Retry-After": "+3"}, {"Retry-After": "1 2"},
    {"Retry-After": T.http_date(AT + timedelta(seconds=3))}, {"Retry-After": T.http_date(AT - timedelta(seconds=30))},
    {"Retry-After": T.http_date(AT)}, {"Retry-After": "Thu, 29 Oct 2026 15:00:03 +0000"},
    {"Retry-After": "Thu, 29 Oct 2026 16:00:03 +0100"}, {"Retry-After": "Thu, 29 Oct 2026 10:00:03 -0500"},
    {"Retry-After": "Thursday, 29-Oct-26 15:00:07 GMT"}, {"Retry-After": "Thu Oct 29 15:00:09 2026"},
    {"Retry-After": "29 Oct 2026 15:00:04 GMT"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:05"},
    {"Retry-After": "Thu, 29 Oct 2026 15:00 GMT"}, {"Retry-After": "Thu, 29 Oct 26 15:00:05 GMT"},
    {"Retry-After": "Thu, 29 Oct 2026 15:00:05 EST"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:05 PDT"},
    {"Retry-After": "Thu, 29 Oct 2026 15:00:05 UT"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:05 Z"},
    {"Retry-After": "Thu, 29 Oct 2026 15:00:05 XYZ"}, {"Retry-After": "Thu, 32 Oct 2026 15:00:05 GMT"},
    {"Retry-After": "Thu, 29 Foo 2026 15:00:05 GMT"}, {"Retry-After": "Thu, 29 October 2026 15:00:05 GMT"},
    {"Retry-After": "Thu, 29 Oct 2026 25:00:05 GMT"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:05.5 GMT"},
    {"Retry-After": "Oct 29 2026 15:00:06 GMT"}, {"Retry-After": "Thu, 2026 Oct 29 15:00:06 GMT"},
    {"Retry-After": "Thu,29 Oct 2026 15:00:06 GMT"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:06 +00"},
    {"Retry-After": "Thu, 29 Oct 70 15:00:06 GMT"}, {"Retry-After": "Thu, 29 Oct 69 15:00:06 GMT"},
    {"Retry-After": "Thu, 29 Oct 1 15:00:06 GMT"}, {"Retry-After": "Thu, 29 Oct 2026 15.00.06 GMT"},
    {"Retry-After": "Thu, 29 Oct 2026 15:00:06 gmt"}, {"Retry-After": "thu, 29 oct 2026 15:00:06 GMT"},
    {"Retry-After": "Thu, 29 Oct 2026"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:06 GMT extra"},
    {"Retry-After": "Thu, 29-Oct-2026 15:00:06 GMT"}, {"Retry-After": "Thu, 29 Oct 9999 23:59:59 GMT"},
    {"Retry-After": "Thu, 29 Oct 10000 00:00:00 GMT"}, {"Retry-After": "Thu, 29 Feb 2026 00:00:00 GMT"},
    {"Retry-After": "Thu, 29 Oct 2026 15:60:06 GMT"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:61 GMT"},
    {"Retry-After": "Thu, 29 Oct 2026 15:00:06 +9999"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:06 -0000"},
    {"Retry-After": "Thu, 29 Oct 2026 15:00:06 +0530"}, {"Retry-After": "29 Oct, 2026 15:00:06 GMT"},
    {"Retry-After": "Thu, 29 Oct 2026 3:00:06 GMT"}, {"Retry-After": "Thu, 29 Oct 2026 15:00:06 GMT+1"},
]

MARKERS = http._CHALLENGE_MARKERS
CHALLENGES = [
    ({}, T.NORMAL_PAGE), ({}, T.CHALLENGE), ({"cf-mitigated": "challenge"}, b"x"), ({"CF-Mitigated": "Challenge"}, b""),
    ({"cf-mitigated": " challenge"}, b"x"), ({"cf-mitigated": "managed"}, b"x"), ({"x": "challenge"}, b"x"),
    ({}, b"<title>Just a moment...</title>"), ({}, b"<TITLE>Just a moment...</TITLE>"), ({}, b""),
    ({}, {"parts": [repeat("x", CHALLENGE_HEAD - len(MARKERS[0])), {"text": MARKERS[0].decode()}]}),
    ({}, {"parts": [repeat("x", CHALLENGE_HEAD - len(MARKERS[0]) + 1), {"text": MARKERS[0].decode()}]}),
    ({}, {"parts": [repeat("x", CHALLENGE_HEAD - 3), {"text": MARKERS[4].decode()}]}),
    ({}, {"base64": base64.b64encode(b"\xff\xfe" + MARKERS[2] + b"\x00").decode()}),
    ({}, azlyrics_fixture("block.html").encode("utf-8")), ({}, lyrics_page().encode("utf-8")),
    ({}, artist_page().encode("utf-8")), ({}, fixture_ref("ug/tab_chords.html")),
]


# --- what httpx's content decoders make of a body (rules.jsonl's "decode") ----------------------------------

DECODED = ("<html>" + "Wonderwall, " * 60 + "</html>").encode()
BIG = DECODED * 12  # more than 4 KiB decoded: its digest


def _raw_deflate(data: bytes) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return co.compress(data) + co.flush()


def _gz(data: bytes = DECODED, *, flags: int = 0, method: int = 8, extra: bytes = b"", name: bytes = b"",
        comment: bytes = b"", hcrc: int | None = None, crc: int | None = None, size: int | None = None,
        deflated: bytes | None = None, trailer: int = 8) -> bytes:
    """A gzip member as RFC 1952 lays it out, each field given or right; ``trailer`` its last bytes kept."""
    head = bytes([0x1F, 0x8B, method, flags]) + (1_700_000_000).to_bytes(4, "little") + b"\x02\x03"
    if flags & 0x04:
        head += len(extra).to_bytes(2, "little") + extra
    if flags & 0x08:
        head += name + b"\x00"
    if flags & 0x10:
        head += comment + b"\x00"
    if flags & 0x02:
        head += ((zlib.crc32(head) & 0xFFFF) if hcrc is None else hcrc).to_bytes(2, "little")
    tail = ((zlib.crc32(data) if crc is None else crc).to_bytes(4, "little")
            + ((len(data) if size is None else size) & 0xFFFFFFFF).to_bytes(4, "little"))
    return head + (_raw_deflate(data) if deflated is None else deflated) + tail[:trailer]


def _zlib(data: bytes = DECODED, *, adler: int | None = None, zdict: bytes | None = None) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, 15, zdict=zdict) if zdict else zlib.compressobj(9)
    out = co.compress(data) + co.flush()
    return out if adler is None else out[:-4] + adler.to_bytes(4, "big")


GZ = _gz()
GZ_HEAD = len(_gz(deflated=b"", trailer=0))
GZIP = [("Content-Encoding", "gzip")]
DEFLATE = [("Content-Encoding", "deflate")]
DECODE = [
    # gzip, one member as zlib's gzip mode (windowBits 16 + 15) reads it: an error as soon as the bytes show it,
    # nothing while they don't
    (GZIP, GZ), (GZIP, gzip.compress(DECODED, mtime=0)), (GZIP, _gz(BIG)), (GZIP, b""), (GZIP, b"h"),
    (GZIP, b"\x1f"), (GZIP, b"he"), (GZIP, b"hello"), (GZIP, b"not gzip at all"), (GZIP, b"\x1f\x8b"),
    (GZIP, b"\x1f\x8b\x08"), (GZIP, b"\x1f\x8b\x07"), (GZIP, b"\x1f\x8b\x07\x00"), (GZIP, _gz(method=7)),
    *[(GZIP, _gz(flags=f)) for f in (0x01, 0x20, 0x40, 0x80, 0xE0, 0x21)],
    (GZIP, _gz(flags=0x04, extra=b"AP\x02\x00hi")), (GZIP, _gz(flags=0x08, name=b"wonderwall.html")),
    (GZIP, _gz(flags=0x10, comment=b"a comment")), (GZIP, _gz(flags=0x02)), (GZIP, _gz(flags=0x02, hcrc=0x1234)),
    (GZIP, _gz(flags=0x1E, extra=b"xy", name=b"n", comment=b"c")),
    (GZIP, _gz(flags=0x1E, extra=b"xy", name=b"n", comment=b"c", hcrc=0)),
    (GZIP, GZ[:5]), (GZIP, GZ[:9]), (GZIP, GZ[:10]), (GZIP, _gz(flags=0x02)[:11]),
    (GZIP, _gz(flags=0x04, extra=b"abcdef")[:14]), (GZIP, _gz(flags=0x08, name=b"no end")[:15]),
    (GZIP, GZ[:GZ_HEAD + 20]), (GZIP, GZ[:-8]), *[(GZIP, GZ[:-k]) for k in (7, 6, 4, 2, 1)],
    (GZIP, _gz(crc=0)), (GZIP, _gz(crc=0, trailer=4)), (GZIP, _gz(crc=0, trailer=3)), (GZIP, _gz(size=1)),
    (GZIP, _gz(size=1, trailer=7)), (GZIP, GZ + b"trailing bytes"), (GZIP, GZ + _gz(b"a second member")),
    (GZIP, _gz(deflated=b"\xff\xff\xff")), (GZIP, _gz(deflated=b"\x01\x05\x00\x00\x00hello")),
    (GZIP, _gz(deflated=b"\x01\x05\x00\xfa\xffhello")), (GZIP, _gz(deflated=b"\x03\x00")),
    (GZIP, _gz(b"")),
    # deflate: zlib's stream, else (its first attempt failed) a raw one
    (DEFLATE, _zlib()), (DEFLATE, _raw_deflate(DECODED)), (DEFLATE, _zlib(BIG)), (DEFLATE, b""), (DEFLATE, b"x"),
    (DEFLATE, b"hello world"), (DEFLATE, _zlib()[:30]), (DEFLATE, _raw_deflate(DECODED)[:30]),
    (DEFLATE, _zlib(adler=0)), (DEFLATE, _zlib(zdict=b"Wonderwall, ")), (DEFLATE, b"\x88\x1b" + _zlib()[2:]),
    (DEFLATE, b"\x78\x9c\xff\xff\xff"), (DEFLATE, _zlib() + b"after"), (DEFLATE, GZ),
    # the codings named, applied last first
    ([("Content-Encoding", "gzip, deflate")], _zlib(GZ)), ([("Content-Encoding", "deflate, gzip")], _gz(_zlib())),
    ([("Content-Encoding", "gzip, gzip")], _gz(GZ)), ([("Content-Encoding", "deflate"), ("Content-Encoding", "gzip")],
                                                      _gz(_zlib())),
    ([("Content-Encoding", "identity, gzip")], GZ), ([("Content-Encoding", "br, gzip")], GZ),
    ([("Content-Encoding", "gzip,,identity")], GZ), ([("content-encoding", " GZIP ")], GZ),
    ([("Content-Encoding", "Gzip\t")], GZ), ([("Content-Encoding", "x-gzip")], GZ),
    ([("Content-Encoding", "gzip, deflate")], _zlib(b"not gzip inside")), ([("Content-Encoding", "identity")], GZ),
    ([("Content-Encoding", "br")], DECODED), ([("Content-Encoding", "compress")], DECODED),
    ([("Content-Encoding", "")], DECODED), ([], GZ), ([("Content-Type", "text/html")], DECODED),
]


def _decoded(headers: list[tuple[str, str]], body: bytes) -> Any:
    """What httpx makes of ``body`` under ``headers``: its decoders' bytes, or their DecodingError."""
    try:
        return body_out(httpx.Response(200, headers=headers, content=body).content)
    except httpx.DecodingError as e:
        return err(e)


def test_the_decoder_cases_reach_every_error_zlib_names():
    said = {r["out"]["err"] for r in rules_records() if r["fn"] == "decode" and "err" in r["out"]}
    for words in ("incorrect header check", "unknown compression method", "unknown header flags set",
                  "header crc mismatch", "incorrect data check", "incorrect length check", "invalid block type",
                  "invalid stored block lengths"):
        assert any(words in e for e in said), words


def rules_records() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for from_cache, fetched_at, now, days in STALE:
        resp = http.Response(url="https://x.test/page", status=200, content=b"page", from_cache=from_cache,
                             fetched_at=fetched_at)
        out.append({"fn": "stale", "args": [from_cache, fetched_at, _stamp(now), days * 86400],
                    "out": http.stale(resp, now, timedelta(days=days))})
    for headers in RETRY_AFTER:
        out.append({"fn": "retry_after", "args": [[[k, v] for k, v in headers.items()], _stamp(AT)],
                    "out": http.retry_after(headers, AT)})
    for headers, body in CHALLENGES:
        carried = body if isinstance(body, dict) else body_in(body)
        out.append({"fn": "is_challenge", "args": [[[k, v] for k, v in headers.items()], carried],
                    "out": http.is_challenge(headers, body_bytes(carried))})
    for headers, body in DECODE:
        out.append({"fn": "decode", "args": [[[k, v] for k, v in headers], body_in(body)],
                    "out": _decoded(headers, body)})
    return out


def test_rules_jsonl_is_http_pys_rules():
    check(HTTP / "rules.jsonl", jsonl(rules_records(), corpus="http/rules", made_by=MADE_BY))


# --- client.jsonl: sessions ---------------------------------------------------------------------------------

# Each random() the session's rng returns, in turn: a pause between two requests is low + (high - low) * u.
DRAWS = [0.5, 0.25, 0.75, 0.125, 0.875, 0.0, 0.999, 0.375, 0.625, 0.0625]
WALL = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


class Drawn(random.Random):
    """A random.Random whose random() returns ``draws`` in turn, so uniform() is Python's own over them."""

    def __init__(self, draws: list[float]):
        super().__init__(0)
        self.draws = list(draws)
        self.taken = 0

    def random(self) -> float:  # noqa: A003
        u = self.draws[self.taken % len(self.draws)]
        self.taken += 1
        return u


@dataclass
class Session:
    case: str
    handler: Callable[[httpx.Request], httpx.Response]
    steps: list[tuple]
    provider: str = "ug"
    budget: int = 60
    delay: tuple[float, float] = (10.0, 20.0)
    max_errors: int = 3
    user_agent: str = "caracole/test"
    clock: str = "fixed"  # or "sleeps": the monotonic clock moves on by every pause slept
    wall: datetime = WALL
    draws: list[float] = field(default_factory=lambda: list(DRAWS))


def get(url: str, *, params=None, cache=True, conditional=False, accept=(200,), max_age=None) -> tuple:
    return ("get", url, {"params": params, "cache": cache, "conditional": conditional, "accept": accept,
                         "max_age": max_age})


def _get_kw(opts: dict[str, Any]) -> dict[str, Any]:
    kw = {"cache": opts["cache"], "conditional": opts["conditional"], "accept": tuple(opts["accept"])}
    if opts["params"] is not None:
        kw["params"] = opts["params"]
    if opts["max_age"] is not None:
        kw["max_age"] = timedelta(seconds=opts["max_age"])
    return kw


def _step_record(step: tuple) -> dict[str, Any]:
    op = step[0]
    if op == "get":
        o = step[2]
        return {"op": "get", "url": pystr(step[1]),
                "params": None if o["params"] is None else [[k, pystr(str(v))] for k, v in o["params"]],
                "cache": o["cache"], "conditional": o["conditional"], "accept": list(o["accept"]),
                "max_age": o["max_age"]}
    if op in ("has_cached", "cached"):
        return {"op": op, "url": step[1], "accept": list(step[2])}
    if op == "client":
        return {"op": "client", **{k: (list(v) if isinstance(v, tuple) else v) for k, v in step[1].items()
                                   if k in ("budget", "delay", "max_errors")}}
    if op == "wall":
        return {"op": "wall", "at": _stamp(step[1])}
    if op == "clock":
        return {"op": "clock", "at": step[1]}
    if op == "read_once_more":
        url, first, again, fetched, unreadable = step[1:]
        first_get = _step_record(get(url, **first))
        return {"op": op, "url": url, "get": {k: v for k, v in first_get.items() if k not in ("op", "url")},
                "again": {"params": None if again.get("params") is None else [[k, str(v)] for k, v in
                                                                             again["params"]],
                          "accept": list(again.get("accept", (200,)))},
                "fetched": None if fetched is None else sorted(fetched), "unreadable": unreadable}
    return {"op": op}


NOTICE = T.NOTICE


class Unreadable(http.ProviderError):
    pass


class PageGone(http.ProviderError):
    pass


def words(resp: http.Response) -> str | None:
    """tests/test_http.py's reader: a notice is unreadable, a 404 nothing, anything else its text."""
    if resp.content == NOTICE:
        raise Unreadable("ug", resp.url, resp.status, "a notice, not the page")
    return None if resp.status == 404 else resp.text


def _response(r: http.Response) -> dict[str, Any]:
    return {"url": pystr(r.url), "status": r.status, "content": body_out(r.content),
            "headers": [[k, v] for k, v in r.headers.items()], "from_cache": r.from_cache, "fetched_at": r.fetched_at}


def _raised(e: BaseException) -> dict[str, Any]:
    return {"raises": {"type": type(e).__name__, "message": str(e), "status": getattr(e, "status", None),
                       "url": None if getattr(e, "url", None) is None else pystr(e.url)}}


def _cache_left(cache: Path) -> list[dict[str, Any]]:
    out = []
    if not cache.is_dir():
        return out
    for p in sorted(cache.rglob("*")):
        if not p.is_file():
            continue
        name = p.relative_to(cache).as_posix()
        data = p.read_bytes()
        if name.endswith(".json"):
            out.append({"path": name, "meta": data.decode("utf-8")})
        elif name.endswith(".body"):
            try:
                out.append({"path": name, "body": body_out(gzip.decompress(data))})
            except (OSError, EOFError):
                out.append({"path": name, "raw": body_out(data)})
        else:
            out.append({"path": name, "raw": body_out(data)})
    return out


def run_session(tmp: Path, s: Session) -> dict[str, Any]:
    cache = tmp / "cache"
    rng = Drawn(s.draws)
    sleeps: list[float] = []
    events: list[http.Event] = []
    requests: list[list[Any]] = []
    answers: list[dict[str, Any]] = []
    clock = [0.0]
    wall = [s.wall]
    handler = [s.handler]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if s.clock == "sleeps":
            clock[0] += seconds

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append([request.method, pystr(str(request.url)),
                         [[k.decode("latin-1"), v.decode("latin-1")] for k, v in request.headers.raw]])
        try:
            resp = handler[0](request)
        except httpx.HTTPError as e:
            answers.append({"raise": type(e).__name__, "message": str(e)})
            raise
        answers.append({"status": resp.status_code,
                        "headers": [[k.decode("latin-1"), v.decode("latin-1")] for k, v in resp.headers.raw],
                        "body": body_in(resp.content)})
        return resp

    def make(policy_budget: int, policy_delay: tuple[float, float], max_errors: int) -> http.PoliteClient:
        return http.PoliteClient(
            s.provider, ProviderPolicy(budget=policy_budget, delay=policy_delay), cache, user_agent=s.user_agent,
            transport=httpx.MockTransport(transport), sleep=sleep, rng=rng, on_event=events.append,
            max_consecutive_errors=max_errors, clock=lambda: clock[0], wall_clock=lambda: wall[0])

    budget, delay, max_errors = s.budget, s.delay, s.max_errors
    client = make(budget, delay, max_errors)
    results: list[Any] = []
    for step in s.steps:
        op = step[0]
        try:
            if op == "get":
                results.append({"response": _response(client.get(step[1], **_get_kw(step[2])))})
            elif op == "has_cached":
                results.append({"value": client.has_cached(step[1], accept=step[2])})
            elif op == "cached":
                r = client.cached(step[1], accept=step[2])
                results.append({"value": None if r is None else _response(r)})
            elif op == "requests_made":
                results.append({"value": client.requests_made})
            elif op == "client":
                opts = step[1]
                budget = opts.get("budget", budget)
                delay = opts.get("delay", delay)
                max_errors = opts.get("max_errors", max_errors)
                if "handler" in opts:
                    handler[0] = opts["handler"]
                client.close()
                client = make(budget, delay, max_errors)
                results.append(None)
            elif op == "wall":
                wall[0] = step[1]
                results.append(None)
            elif op == "clock":
                clock[0] = step[1]
                results.append(None)
            elif op == "unlink_bodies":
                for b in cache.rglob("*.body"):
                    b.unlink()
                results.append(None)
            elif op == "corrupt_bodies":
                for b in cache.rglob("*.body"):
                    b.write_bytes(b"not gzip")
                results.append(None)
            elif op == "read_once_more":
                url, first, again, fetched, unreadable = step[1:]
                kept = None if fetched is None else set(fetched)
                kind = {"Unreadable": Unreadable, "PageGone": PageGone}[unreadable]
                resp = client.get(url, **_get_kw(get(url, **first)[2]))
                try:
                    value = http.read_once_more(client, resp, url, words, kind, fetched=kept, **again)
                    results.append({"value": value, "fetched": None if kept is None else sorted(kept)})
                except http.ProviderError as e:
                    results.append({**_raised(e), "fetched": None if kept is None else sorted(kept)})
            else:
                raise ValueError(op)
        except (http.ProviderError, http.BudgetExhausted) as e:
            results.append(_raised(e))
    client.close()
    return {
        "fn": "session", "case": s.case, "provider": s.provider,
        "policy": {"budget": s.budget, "delay": list(s.delay)}, "max_errors": s.max_errors,
        "user_agent": s.user_agent, "clock": s.clock, "wall": _stamp(s.wall), "draws": s.draws,
        "steps": [_step_record(st) for st in s.steps], "answers": answers,
        "out": {"steps": results, "requests": requests,
                "events": [[e.provider, pystr(e.url), e.status, e.decision, e.message] for e in events],
                "sleeps": sleeps, "draws_taken": rng.taken, "cache": _cache_left(cache)},
    }


def ok(body=b"hello", status=200, headers=None):
    return lambda request: httpx.Response(status, content=body, headers=headers or {})


def in_turn(*answers):
    """Each request the next of ``answers`` (``(status, headers, body)``, or an exception to raise), the last for
    ever after."""
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        a = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(a, Exception):
            raise type(a)(str(a), request=request)
        status, headers, body = a
        return httpx.Response(status, headers=headers, content=body)
    return handler


def busy(*queue):
    """tests/test_http.py's in_turn: each ``(status, headers)`` in turn, a 503's body LRCLIB's."""
    return T.in_turn(list(queue))


X1, X2, X3 = "https://x.test/1", "https://x.test/2", "https://x.test/3"
TAB1, TAB2 = TABS + "/tab/1", TABS + "/tab/2"
SITEMAP = WWW + "/sitemap40.xml"
LR = "lrclib"


def sessions() -> list[Session]:
    out = [
        Session("a cache hit makes no request", ok(b"page"), [get(TAB1), get(TAB1), ("requests_made",)]),
        Session("the cache survives a new client", ok(b"page"),
                [get(TAB1), ("client", {"handler": ok(b"other")}), get(TAB1), ("requests_made",)]),
        Session("params are part of the cache key", lambda r: httpx.Response(200, content=r.url.query),
                [get("https://lrclib.net/api/get", params=[("track_name", "斑马斑马"), ("duration", 253)]),
                 get("https://lrclib.net/api/get", params=[("track_name", "Other")]),
                 get("https://lrclib.net/api/get", params=[("track_name", "斑马斑马"), ("duration", 253)])]),
        Session("the user agent is sent", ok(), [get(TAB1)], user_agent="caracole/0.1 (+https://x.test/about)"),
        Session("a pause before every network request but the first", ok(), [get(TAB1), get(TAB1), get(TAB2)]),
        Session("a pause counts the time already elapsed", ok(),
                [get(X1), ("clock", 4.0), get(X2), ("clock", 30.0), get(X3)], budget=10, delay=(10.0, 10.0)),
        Session("a zero gap sends back to back", ok(), [get(TAB1), get(TAB2)], delay=(0.0, 0.0)),
        Session("gametabs.net is paced by its policy alone", ok(),
                [get("https://gametabs.net/tabs/actraiser/fillmore"), get("https://gametabs.net/tabs/actraiser/sacrifices")],
                provider="gametabs", delay=(1.0, 1.0)),
        Session("the budget is spent before a request", ok(),
                [get(X1), get(X2), get(X3), get("https://x.test/4"), get(X1)], budget=2),
        *[Session(f"a {status} is a block", ok(b"no", status=status), [get(X1), get(X2)]) for status in (403, 429)],
        Session("a challenge page with a 200 is a block", ok(T.CHALLENGE), [get(TAB1)]),
        Session("cf-mitigated is a block", ok(b"x", status=403, headers={"cf-mitigated": "challenge"}), [get(X1)]),
        Session("cf-mitigated on a 200 is a block", ok(b"x", headers={"CF-Mitigated": "Challenge"}), [get(X1)]),
        Session("a normal page with Cloudflare's script is no block", ok(T.NORMAL_PAGE), [get(TAB1)]),
        Session("after a block no more requests this run", ok(b"no", status=429), [get(X1), get(X2), get(X1)]),
        *[Session(f"robots.txt closes {u}", ok(), [get(u), ("requests_made",)]) for u in T.ROBOTS_CLOSED],
        *[Session(f"caracole reads {u}", ok(), [get(u)]) for u in T.READ_BY_CARACOLE],
        Session("robots.txt's refusals are no failures of the provider", ok(b"boom", status=502),
                [get(TAB1), *[get(f"{TABS}/tab/print?id={i}") for i in range(3)], get(TAB2), get(TABS + "/tab/3"),
                 get(TABS + "/tab/4")]),
        *[Session(f"a string that isn't a URL is an error never sent: {name}", ok(),
                  [get(u), ("requests_made",), get(TAB1)], max_errors=1) for name, u in T.NOT_URLS.items()],
        Session("each redirect hop is counted and paced", T.moved("/tab/a/new-chords-1"),
                [get(T.OLD), ("requests_made",)]),
        Session("each redirect hop is an event", T.moved(T.NEW, status=302), [get(T.OLD)]),
        Session("a redirected answer is cached under the URL asked", T.moved(T.NEW), [get(T.OLD), get(T.OLD)]),
        Session("a redirect hop needs budget", T.moved(T.NEW), [get(T.OLD)], budget=1),
        Session("a redirect loop stops after three hops", lambda r: httpx.Response(302, headers={"Location": str(r.url)}),
                [*[get(f"https://acordes.lacuerda.net/artist_{i}/") for i in range(3)],
                 get("https://acordes.lacuerda.net/artist_9/"), ("requests_made",)], provider="lacuerda"),
        Session("a redirect robots.txt closes is not followed", T.moved("/tab/print?id=1", status=302), [get(T.OLD)]),
        Session("a URL robots.txt closes is RobotsClosed asked for or redirected to",
                T.moved("/tab/print?id=1", status=302), [get(TABS + "/tab/print?id=1"), get(T.OLD)]),
        Session("a redirect robots.txt closes is no failure of the provider", T.moved("/tab/print?id=1", status=302),
                [get(T.OLD), get(T.NEW)], max_errors=1),
        Session("a redirect to another site is not followed", T.moved("https://accounts.example.com/login?next=/tab/a",
                                                                       status=302), [get(T.OLD)]),
        Session("a redirect between the hosts of one site is followed", T.moved(WWW + "/artist/a_1"), [get(T.OLD)]),
        Session("a redirect to plain http on the site gets its own Host", T.moved("http://www.ultimate-guitar.com/a_1",
                                                                                  status=307), [get(T.OLD)]),
        Session("a redirect's Location httpx can't read is an error",
                in_turn((301, {"Location": "https://[::zz]/x"}, b""), (200, {}, b"page")), [get(T.OLD), get(T.NEW)]),
        Session("a 300 or a 304 with a Location is no redirect",
                in_turn((300, {"Location": "/x"}, b""), (304, {"Location": "/x"}, b"")), [get(X1), get(X2)]),
        Session("a redirect with no Location is the caller's answer", in_turn((302, {}, b"moved")),
                [get(X1, accept=(200, 302)), get(X1, accept=(200, 302))]),
        Session("a conditional request's validators go with each hop",
                in_turn((200, {"etag": '"v1"', "last-modified": "Sun, 18 Oct 2026 13:09:36 GMT"}, b"<urlset/>"),
                        (301, {"Location": "/sitemap41.xml"}, b""), (304, {}, b"")),
                [get(SITEMAP, cache=False, conditional=True), get(SITEMAP, cache=False, conditional=True)]),
        Session("a redirect hop that answers a block is a block",
                in_turn((302, {"Location": "/tab/2"}, b""), (403, {}, b"no")), [get(TAB1), get(TAB2)]),
        Session("a 500 is an error and not cached", ok(b"boom", status=500), [get(X1), get(X1)]),
        Session("a network error is a provider error",
                in_turn(httpx.ConnectError("[Errno 111] Connection refused")), [get(X1), get(X2), get(X3)]),
        Session("a timeout is a provider error", in_turn(httpx.ReadTimeout("timed out")), [get(TAB1)]),
        Session("a 404 is cached when accepted", ok(b"gone", status=404),
                [get(X1, accept=(200, 404)), get(X1, accept=(200, 404))]),
        Session("an unaccepted 404 is a provider error", ok(b"gone", status=404), [get(X1)]),
        Session("a 404 the caller rejects is not cached", ok(b"<html>Not Found</html>", status=404),
                [get("https://lrclib.net/api/search?track_name=x"),
                 get("https://lrclib.net/api/search?track_name=x", accept=(200, 404))], provider=LR),
        Session("a cached answer the caller rejects is asked again",
                in_turn((404, {}, b"[]"), (200, {}, b"[]")),
                [get("https://lrclib.net/api/search?track_name=x", accept=(200, 404)),
                 get("https://lrclib.net/api/search?track_name=x"), ("requests_made",),
                 get("https://lrclib.net/api/search?track_name=x")], provider=LR),
        Session("an accepted 503 is returned, not cached", ok(b'{"name": "ServerOverloaded"}', status=503),
                [get("https://lrclib.net/api/get", accept=(200, 404, 503)),
                 get("https://lrclib.net/api/get", accept=(200, 404, 503))], provider=LR),
        Session("an accepted 3xx or 2xx other than 200 is not cached", in_turn((203, {}, b"a"), (203, {}, b"b")),
                [get(X1, accept=(200, 203)), get(X1, accept=(200, 203))]),
        Session("a conditional get sends validators and reuses the body on a 304",
                lambda r: httpx.Response(304) if r.headers.get("if-none-match") == '"v1"' else httpx.Response(
                    200, content=b"<urlset/>", headers={"etag": '"v1"', "last-modified": "Sun, 18 Oct 2026 13:09:36 GMT"}),
                [get(SITEMAP, cache=False, conditional=True), get(SITEMAP, cache=False, conditional=True),
                 ("requests_made",)]),
        Session("an answer just revalidated is as old as its 304",
                in_turn((200, {"etag": '"v1"'}, b"<urlset/>"), (304, {"etag": '"v1"'}, b"<urlset/>")),
                [get(SITEMAP, cache=False, conditional=True), ("wall", datetime(2026, 11, 27, tzinfo=UTC)),
                 get(SITEMAP, cache=False, conditional=True), get(SITEMAP, max_age=30 * 86400)],
                wall=datetime(2026, 10, 18, tzinfo=UTC)),
        Session("a 304 for a copy that isn't kept is an error", in_turn((304, {}, b"")),
                [get(SITEMAP, cache=False, conditional=True)]),
        Session("a conditional get with Last-Modified alone",
                in_turn((200, {"Last-Modified": "Sun, 18 Oct 2026 13:09:36 GMT", "Content-Type": "text/xml"},
                         b"<urlset/>"), (304, {}, b"")),
                [get(SITEMAP, conditional=True), get(SITEMAP, conditional=True), get(SITEMAP)]),
        Session("an uncached conditional get is plain", ok(b"x"), [get("https://x.test/s.xml", cache=False,
                                                                       conditional=True)]),
        Session("has_cached says whether a request would have a copy to revalidate, and sends nothing",
                lambda r: httpx.Response(404 if r.url.path == "/gone.xml" else 200, content=b"<urlset/>"),
                [("has_cached", SITEMAP, (200,)), get(SITEMAP, cache=False, conditional=True),
                 get(WWW + "/gone.xml", accept=(200, 404)), ("has_cached", SITEMAP, (200,)),
                 ("has_cached", WWW + "/sitemap41.xml", (200,)), ("has_cached", WWW + "/gone.xml", (200,)),
                 ("has_cached", WWW + "/gone.xml", (200, 404))]),
        Session("has_cached is false when the body is gone, as get would download it", ok(b"<urlset/>"),
                [get(SITEMAP, cache=False, conditional=True), ("unlink_bodies",), ("has_cached", SITEMAP, (200,)),
                 get(SITEMAP, cache=False, conditional=True)]),
        Session("cached reads a cached answer alone and sends nothing",
                lambda r: httpx.Response(404 if r.url.path == "/gone" else 200, content=b"<html>page</html>"),
                [("cached", WWW + "/artist/634073", (200,)), get(WWW + "/artist/634073"),
                 get(WWW + "/gone", accept=(200, 404)), ("cached", WWW + "/artist/634073", (200,)),
                 ("cached", WWW + "/gone", (200,)), ("cached", WWW + "/gone", (200, 404)),
                 ("cached", WWW + "/artist/1", (200,)), ("corrupt_bodies",), ("cached", WWW + "/artist/634073", (200,)),
                 get(WWW + "/artist/634073"), ("requests_made",)]),
        Session("consecutive errors make the provider unavailable", ok(b"boom", status=502),
                [*[get(f"https://x.test/{i}") for i in range(3)], get("https://x.test/9")]),
        Session("a success resets the error count",
                in_turn(*[(s, {}, b"x") for s in (502, 502, 200, 502, 502, 200)]),
                [get(f"https://x.test/{i}") for i in range(6)]),
        Session("an accepted 503 does not reset the error count", T.lrclib_outage(503),
                [x for i in range(3) for x in (get(f"https://lrclib.net/api/get?n={i}", accept=(200, 404, 503)),
                                               get(f"https://lrclib.net/api/search?n={i}"))]
                + [get("https://lrclib.net/api/get?n=3", accept=(200, 404, 503))], provider=LR),
        Session("an accepted 404 resets the error count", T.lrclib_outage(404),
                [x for i in range(3) for x in (get(f"https://lrclib.net/api/get?n={i}", accept=(200, 404, 503)),
                                               get(f"https://lrclib.net/api/search?n={i}"))]
                + [get("https://lrclib.net/api/get?n=3", accept=(200, 404, 503))], provider=LR),
        Session("a 503 with Retry-After is asked once more after it", busy(T.BUSY, (200, {})),
                [get(T.SEARCH), ("requests_made",), get(T.SEARCH)], **_busy()),
        Session("a 503 with an HTTP date waits until then",
                busy((503, {"Retry-After": T.http_date(AT + timedelta(seconds=3))}), (200, {})), [get(T.SEARCH)],
                **_busy()),
        Session("an HTTP date already past is asked again after the jitter alone",
                busy((503, {"Retry-After": T.http_date(AT - timedelta(seconds=30))}), (200, {})), [get(T.SEARCH)],
                **_busy()),
        Session("the retry keeps the provider's pace when its Retry-After is shorter",
                busy((503, {"Retry-After": "0"}), (200, {})), [get(T.SEARCH)], **_busy(delay=(5.0, 5.0))),
        *[Session(f"a 503 without a Retry-After it can read is an error at once: {name}", busy((503, h), (200, {})),
                  [get(T.SEARCH)], **_busy())
          for name, h in [("none", {}), ("unreadable", {"Retry-After": "soon"}), ("negative", {"Retry-After": "-1"}),
                          ("not whole seconds", {"Retry-After": "1.5"})]],
        Session("two 503s in a row are an error, never an endless retry", busy(T.BUSY, T.BUSY, (200, {})),
                [get(T.SEARCH), get(T.SEARCH)], **_busy()),
        Session("a Retry-After longer than caracole waits is an error, never an early ask",
                busy((503, {"Retry-After": "120"}), (200, {})), [get(T.SEARCH)], **_busy()),
        Session("a Retry-After of 30 s is waited", busy((503, {"Retry-After": "30"}), (200, {})), [get(T.SEARCH)],
                **_busy()),
        Session("a retry the budget can't pay for is the 503's error with no wait", busy(T.BUSY, (200, {})),
                [get(T.SEARCH), get(T.SEARCH)], **_busy(budget=1)),
        Session("a retried 503 counts once toward the breaker", busy(T.BUSY),
                [get(f"{T.SEARCH}{n}") for n in range(4)], **_busy()),
        Session("a 503 that its retry answers resets the breaker",
                busy((500, {}), (500, {}), T.BUSY, (200, {}), (500, {}), (500, {}), (200, {})),
                [get(f"{T.SEARCH}{n}") for n in range(5)], **_busy()),
        Session("a 429 with Retry-After is still a block", busy((429, {"Retry-After": "1"}), (200, {})),
                [get(T.SEARCH), get(T.SEARCH)], **_busy()),
        Session("another site's 503 is never retried", busy(T.BUSY, (200, {})),
                [get("https://tabs.ultimate-guitar.com/tab/x-1")], **_busy(provider="ug")),
        Session("a wait that ties is written half to even", busy(T.BUSY, (200, {})), [get(T.SEARCH)],
                draws=[0.25], **_busy()),
        Session("a retry's redirect is followed as any", busy(T.BUSY, (302, {"Location": "/api/search?track_name=y"}),
                                                              (200, {})), [get(T.SEARCH)], **_busy()),
        Session("events are reported", ok(), [get(X1), get(X1)]),
        Session("a large body round-trips through the compressed cache",
                ok(("<url><loc>https://tabs.ultimate-guitar.com/tab/a/b-chords-1</loc></url>" * 20000).encode()),
                [get("https://x.test/big"), get("https://x.test/big")]),
        Session("max_age refetches stale copies and falls back when the budget is spent",
                in_turn((200, {}, b"v1"), (200, {}, b"v2")),
                [get(WWW + "/artist/soda_stereo_2946?filter=chords", max_age=30 * 86400),
                 ("wall", datetime(2026, 10, 28, tzinfo=UTC)),
                 get(WWW + "/artist/soda_stereo_2946?filter=chords", max_age=30 * 86400),
                 ("wall", datetime(2026, 11, 22, tzinfo=UTC)),
                 get(WWW + "/artist/soda_stereo_2946?filter=chords", max_age=30 * 86400),
                 ("wall", datetime(2027, 1, 1, tzinfo=UTC)),
                 get(WWW + "/artist/soda_stereo_2946?filter=chords", max_age=30 * 86400)],
                budget=2, delay=(0.0, 0.0), wall=datetime(2026, 10, 18, tzinfo=UTC)),
        Session("a cached answer with no time is stale", in_turn((200, {}, b"v1"), (200, {}, b"v2")),
                [get(X1), ("client", {}), get(X1, max_age=86400)]),
        Session("a fresh answer that won't read is an error and is asked for no more", T.answers(NOTICE),
                [("read_once_more", "https://x.test/page", {}, {}, [], "Unreadable"), ("requests_made",)]),
        Session("a cached answer that won't read is asked for once more past the cache",
                T.answers(NOTICE, b"the page"),
                [get("https://x.test/page"), ("client", {}),
                 ("read_once_more", "https://x.test/page", {}, {}, [], "Unreadable"), ("requests_made",),
                 get("https://x.test/page")]),
        Session("a cached answer still unreadable when asked again is an error", T.answers(NOTICE, NOTICE),
                [get("https://x.test/page"), ("client", {}),
                 ("read_once_more", "https://x.test/page", {}, {}, [], "Unreadable"), ("requests_made",)]),
        Session("what the first request was given goes to the second", T.answers(NOTICE, 404),
                [get("https://x.test/api/get", params=[("q", "x")]), ("client", {}),
                 ("read_once_more", "https://x.test/api/get", {"params": [("q", "x")]},
                  {"params": [("q", "x")], "accept": (200, 404)}, None, "Unreadable")]),
        Session("a URL already fetched in the pass is not asked for again", T.answers(NOTICE, b"the page"),
                [get("https://x.test/page"), ("client", {}),
                 ("read_once_more", "https://x.test/page", {}, {}, ["https://x.test/page"], "Unreadable"),
                 ("requests_made",)]),
        Session("only the reader's own failure asks again", T.answers(NOTICE, b"the page"),
                [get("https://x.test/page"), ("client", {}),
                 ("read_once_more", "https://x.test/page", {}, {}, None, "PageGone"), ("requests_made",)]),
        Session("a readable answer is read once", T.answers(b"the page"),
                [("read_once_more", "https://x.test/page", {}, {}, [], "Unreadable")]),
        Session("headers kept in http.py's order, the last of a name joined",
                in_turn((200, [("Location", "/x"), ("Content-Type", "text/html"), ("ETag", '"a"'), ("etag", '"b"'),
                               ("Last-Modified", "Sun, 18 Oct 2026 13:09:36 GMT"), ("X-Other", "y")], b"page")),
                [get(X1), get(X1)]),
        Session("a non-ASCII URL is asked for as httpx quotes it", ok(b"page"),
                [get("https://x.test/caf\u00e9 au lait?q=ni\u00f1o#top"), get("https://x.test/caf%C3%A9 au lait?q=ni%C3%B1o"),
                 get("https://m\u00fcller.de/x"), get("HTTPS://X.TEST:443/a/./b/../c")]),
        Session("a provider of no policy is paced by its own", ok(), [get(X1), get(X2)], provider="ytimg",
                delay=(0.0, 0.0)),
        Session("a URL's user and password go as httpx's basic auth", ok(b"page"),
                [get("https://u:p@x.test/a"), get("https://u%20x:p%C3%A9@x.test/b"), get("https://u@x.test/c"),
                 get("https://:p@x.test/d"), get("https://u:%ff@x.test/e"), get("https://@x.test/f"),
                 get("https://u:p@x.test/g", conditional=True)], delay=(0.0, 0.0)),
        Session("basic auth goes with a redirect on its origin, never off it",
                in_turn((302, {"Location": "/tab/b"}, b""), (302, {"Location": WWW + "/artist/a_1"}, b""),
                        (200, {}, b"page")), [get("https://u:p@tabs.ultimate-guitar.com/tab/a")]),
        Session("basic auth goes with a redirect from http to https on its host",
                in_turn((301, {"Location": "https://x.test/b"}, b""), (301, {"Location": "http://x.test/c"}, b""),
                        (200, {}, b"page")), [get("http://u:p@x.test/a")]),
        Session("a redirect's own user and password are its basic auth",
                in_turn((302, {"Location": "https://v:q@www.ultimate-guitar.com/x"}, b""),
                        (302, {"Location": "https://w@www.ultimate-guitar.com/y"}, b""), (200, {}, b"page")),
                [get("https://u:p@tabs.ultimate-guitar.com/tab/a")]),
    ]
    return out


def _busy(*, provider: str = LR, budget: int = 200, delay: tuple[float, float] = (0.0, 0.0)) -> dict[str, Any]:
    """tests/test_http.py's busy_client: LRCLIB, its clock moving on by every pause slept, its wall clock at AT."""
    return {"provider": provider, "budget": budget, "delay": delay, "clock": "sleeps", "wall": AT}


def client_records(tmp_path: Path) -> list[dict[str, Any]]:
    return [run_session(tmp_path / f"s{i}", s) for i, s in enumerate(sessions())]


def test_client_jsonl_is_each_case_of_test_http_as_a_session(tmp_path):
    check(HTTP / "client.jsonl", jsonl(client_records(tmp_path), corpus="http/client", made_by=MADE_BY))


def test_the_sessions_say_what_test_http_asserts(tmp_path):
    by = {r["case"]: r for r in client_records(tmp_path)}
    hit = by["a cache hit makes no request"]["out"]
    assert [s["response"]["from_cache"] for s in hit["steps"][:2]] == [False, True] and len(hit["requests"]) == 1
    loop = by["a redirect loop stops after three hops"]["out"]
    assert len(loop["requests"]) == 12 and len(loop["sleeps"]) == 11
    assert loop["steps"][3]["raises"]["type"] == "ProviderUnavailable"
    retry = by["a 503 with Retry-After is asked once more after it"]["out"]
    assert [e[3] for e in retry["events"]] == ["error", "ok"] and len(retry["sleeps"]) == 1
    assert 1.0 <= retry["sleeps"][0] <= 2.0
    assert by["a 403 is a block"]["out"]["steps"][0]["raises"]["type"] == "ProviderBlocked"
    headers = by["the user agent is sent"]["out"]["requests"][0][2]
    assert [h[0] for h in headers] == ["Host", "Accept", "Accept-Encoding", "Connection", "User-Agent"]
    big = by["a large body round-trips through the compressed cache"]
    assert "repeat" in big["answers"][0]["body"] and "sha256" in big["out"]["steps"][1]["response"]["content"]
