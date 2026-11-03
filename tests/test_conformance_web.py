"""The phone's local server, as caracole serve answers: what the Kotlin port's :server replays (lane server-shell).

- ``vectors/web/security.jsonl``: web/security.py's ``host_name``, ``answers_to``, ``cross_origin_ok``,
  ``own_page_read`` and ``same_token`` over a matrix of hosts, headers and methods (tests/test_web_security.py's cases
  among them), each a record ``{"fn": "caracole.web.security.<name>", "args": […], "out": …}`` (``answers_to``'s
  allowed names a sorted list); and the code point ranges of ``str.isdigit`` and ``str.isspace`` (``{"fn":
  "str.isdigit", "out": [[first, last], …]}``), which the Kotlin port keeps as tables of its own.
- ``vectors/web/routing.jsonl``: ``WebApp.handle`` over an empty library, with only the routes its first record
  lists (``{"fn": "routes", "out": {"allowed", "csrf", "library_name", "badge", "routes": [{method, path, under,
  script_only, page, answer}]}}``; each ``answer`` one of ``ANSWERS``, the same on both sides), then a record a request:
  ``args`` ``[{"method", "target", "headers", "body" | "body_b64"}]``, ``out`` ``{"status", "headers": [[name,
  value], …], "body" | "body_b64"}``, and a ``note``. Each refusal's status, page and data, and the headers
  ``WebApp.finish`` sets, in order. The body is what ``handle`` answers, a HEAD's too: the socket drops it
  (server.py, the phone's LocalServer). No request names a page caracole writes into the library (sheet.html,
  index.html…): the computer serves those as written (``WebApp._written_page``), the phone the mirror's copies.
- ``vectors/web/downloads.jsonl``: web/files.py's ``TYPES`` (its pairs, in order), ``DOWNLOADS`` and ``MAX_BYTES``, and
  download_names.py's ``download_name`` and ``content_disposition``.
- ``data/caracole/page/message.json``: ``{"style": pages.PAGE_STYLE, "csp": pages.PAGE_CSP}``, the message page's
  style and policy, which the phone's MessagePage writes its pages with.
- ``data/caracole/page/icon.json``: ``{"link": page_icon.LINK, "svg": page_icon.SVG, "mark": page_icon.mark(),
  "scratch_link": library_name.SCRATCH_LINK}``: the tab's icon, the browser's /favicon.ico, the bar's "¿", and the
  icon of a library with a badge.
"""

from __future__ import annotations

import base64
import json
import sys
from urllib.parse import urlencode

import pytest

from caracole import download_names, page_icon
from caracole.library_name import SCRATCH_LINK, LibraryName
from caracole.web import app as app_module
from caracole.web import files, pages, security
from caracole.web.app import Request, Response, Route, WebApp, html_response, json_response
from caracole.web.jobs import JobQueue
from caracole.web.pages import Refused
from helpers.corpus import DATA, VECTORS, check, jsonl

MADE_BY = "tests/test_conformance_web.py"
WEB = VECTORS / "web"

# --- security.py -----------------------------------------------------------------------------------------------

HOST_HEADERS = [
    # tests/test_web_security.py's
    "localhost:8737", "LOCALHOST", "127.0.0.1:8737", "[::1]:8737", "[::1]", "nuc.example.ts.net.:8737", "nuc",
    None, "", "localhost:80a", "[::1", "[::1]x", "a b", "evil.example:8737/x",
    # and more
    "127.0.0.1:8738", "localhost:", "localhost:8737:1", ":8737", "[::1]:", "[::1]:x", "[]", "[]:80",
    "[fe80::1%eth0]", "[fd7a:115c:a1e0::7]:8737", "[::ffff:192.168.1.20]", " localhost ", "\tlocalhost\x85",
    "\xa0localhost:8737　", "localhost\x00", "localhost..", "..", ".", "a..b", "Ex-ample_1.Local", "ex ample",
    "localhost:²", "localhost:١٢", "localhost:①", "[::1]:³", "Key", "İ", "ÀB", "例え.jp", "xn--r8jz45g.jp",
    "localhost:+80", "localhost:-1", "localhost: 80", "0x7f.1", "192.168.1.20.nip.io", "::1", "fe80::1",
]

NAMES = [
    None, "", "localhost", "nuc", "nuc.local", "evil.example", "nuc.evil.example", "0x7f.1", "192.168.1.20.nip.io",
    "192.168.1.20", "100.64.0.7", "127.0.0.1", "0.0.0.0", "255.255.255.255", "256.1.1.1", "1.2.3", "1.2.3.4.5",
    "1.2.3.04", "01.2.3.4", "1.2.3.0", "1.2.3.", ".1.2.3", "1..2.3", "1.2.3.4 ", "١.٢.٣.٤", "1.2.3.4/32",
    "fd7a:115c:a1e0::7", "::ffff:192.168.1.20", "::1", "::", ":::", "1::2::3", "fe80::1%eth0", "fe80::1%",
    "fe80::1%a%b", "1:2:3:4:5:6:7:8", "1:2:3:4:5:6:7:8:9", "1:2:3:4:5:6:7", "::1:2:3:4:5:6:7", "1:2:3:4:5:6:7::",
    "1:2:3:4:5:6::7:8", "1:2:3:4:5:6:7::8", "12345::", "g::", "::1.2.3.4", "::1.2.3", "1.2.3.4::", "::ffff:1.2.3.256",
    ":1::2", "1::2:", "1:2", "::0:0:0:0:0:0:0", "0:0:0:0:0:0:0:0", "1:2:3:4:5:6:1.2.3.4", "1:2:3:4:5:6:7:1.2.3.4",
    "::FFFF:1.2.3.4", "1:2:3:4:5:6:7:8:", ":1:2:3:4:5:6:7:8", "a" * 46, "::" + "0:" * 20 + "1",
    "fe80::1%25eth0", "::1/128",
]
ALLOWED_SETS = [["localhost"], ["localhost", "nuc", "nuc.local"], ["127.0.0.1", "::1", "localhost"]]

ORIGINS = [
    None, "http://localhost:8737", "https://localhost:8737", "http://LOCALHOST:8737", "http://localhost:9999",
    "http://evil.example", "null", "", "http://localhost:8737/path", "http://localhost:8737?q", "//localhost:8737",
    "localhost:8737", "http://user@localhost:8737", "http://[::1]:8737", "http://[::1", "http://::1]", "http://[1.2.3.4]",
    "http://[v1.x]", "http://[vz.x]", "http://[V7.a]:1", "http://x[::1]", "http://[::1]x", "http://[fe80::1%25eth0]",
    "http://ｌocalhost:8737", "http://a／b", "http://a℀b", "\x00 http://localhost:8737",
    "http://local\thost:8737", "http://local\nhost:8737", "HTTP://localhost:8737", "1http://localhost:8737",
    "http:localhost:8737", "http://localhost:8737#frag", "http://ÀB", "http://àb",
]
HOSTS = ["localhost:8737", "[::1]:8737", " localhost:8737 ", "", None, "àb", "a/b", "LOCALHOST:8737"]
SITES = [None, "same-origin", "none", "cross-site", "same-site", "", "SAME-ORIGIN", "same-origin "]
METHODS = ["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "post", "get"]

TOKENS = [("abc", "abc"), ("abd", "abc"), (None, "abc"), ("", ""), ("abc", ""), ("", "abc"), ("é", "é"),
          ("tok", "tok "), ("ab", "abc"), ("ÀÉ", "àé"), ("\U0001f3b8", "\U0001f3b8")]


def _ranges(test) -> list[list[int]]:
    found: list[list[int]] = []
    for cp in range(sys.maxunicode + 1):
        if test(chr(cp)):
            if found and found[-1][1] == cp - 1:
                found[-1][1] = cp
            else:
                found.append([cp, cp])
    return found


def security_records() -> list[dict]:
    out: list[dict] = [{"fn": "str.isdigit", "args": [], "out": _ranges(str.isdigit)},
                       {"fn": "str.isspace", "args": [], "out": _ranges(str.isspace)}]
    fn = "caracole.web.security."
    out += [{"fn": fn + "host_name", "args": [h], "out": security.host_name(h)} for h in HOST_HEADERS]
    out += [{"fn": fn + "answers_to", "args": [name, allowed], "out": security.answers_to(name, frozenset(allowed))}
            for allowed in ALLOWED_SETS for name in NAMES + [security.host_name(h) for h in HOST_HEADERS]]
    for method in METHODS:
        for site in SITES:
            for origin in ORIGINS if site is None else [None, "http://evil.example"]:
                headers = {k: v for k, v in (("sec-fetch-site", site), ("origin", origin)) if v is not None}
                for host in HOSTS if site is None else ["localhost:8737"]:
                    out.append({"fn": fn + "cross_origin_ok", "args": [method, headers, host],
                                "out": security.cross_origin_ok(method, headers, host)})
    for site in SITES:
        headers = {} if site is None else {"sec-fetch-site": site}
        out.append({"fn": fn + "own_page_read", "args": [headers], "out": security.own_page_read(headers)})
    out += [{"fn": fn + "same_token", "args": [given, expected], "out": security.same_token(given, expected)}
            for given, expected in TOKENS]
    return out


def test_security_vectors_are_security_pys_answers():
    check(WEB / "security.jsonl", jsonl(security_records(), corpus="web/security", made_by=MADE_BY))


# --- WebApp.handle ----------------------------------------------------------------------------------------------

HOST = "localhost:8737"
CSRF = "tok"
ALLOWED = ["127.0.0.1", "::1", "localhost"]
NAME = BADGE = "Phone"

# The routes both sides build: each answers as its ``answer`` says (``ANSWERS``).
ROUTES = [
    {"method": "GET", "path": "/", "answer": "page"},
    {"method": "GET", "path": "/api/echo", "answer": "echo"},
    {"method": "GET", "path": "/api/jobs/", "under": True, "answer": "echo"},
    {"method": "GET", "path": "/jobs.json", "script_only": True, "answer": "echo"},
    {"method": "GET", "path": "/refused", "answer": "refuse"},
    {"method": "GET", "path": "/kept", "answer": "kept"},
    {"method": "POST", "path": "/form", "answer": "echo"},
    {"method": "POST", "path": "/form/page", "page": "the page", "answer": "echo"},
    {"method": "POST", "path": "/queued", "answer": "queued"},
    {"method": "POST", "path": "/refuse", "answer": "refuse"},
    {"method": "POST", "path": "/under/", "under": True, "answer": "echo"},
]

# What each answer is, on both sides:
# - echo: 200 JSON {"route": the route's path, "method": the request's, "form": the form (a POST's alone)};
# - page: 200 HTML "<!doctype html>\n<p>page</p>\n" with its own Content-Security-Policy, "default-src 'none'";
# - refuse: Refused(409, "Not here yet", "That isn't here yet.");
# - kept: 200 text/plain "kept\n" with its own Cache-Control "max-age=60" and x-frame-options "SAMEORIGIN";
# - queued: a job queued, as WebApp.queued answers one: 303 to "/#tab=requests&job=7", data {"job": {"id": 7,
#   "state": "queued"}}.
ANSWERS = ("echo", "page", "refuse", "kept", "queued")


def _answer(spec: dict):
    kind, path = spec["answer"], spec["path"]

    def answer(app, request, form=None):
        if kind == "echo":
            data = {"route": path, "method": request.method}
            if form is not None:
                data["form"] = form
            return json_response(200, data)
        if kind == "page":
            return html_response(200, "<!doctype html>\n<p>page</p>\n", csp="default-src 'none'")
        if kind == "refuse":
            raise Refused(409, "Not here yet", "That isn't here yet.")
        if kind == "kept":
            return Response(200, b"kept\n", [("Content-Type", "text/plain; charset=utf-8"),
                                             ("Cache-Control", "max-age=60"), ("x-frame-options", "SAMEORIGIN")])
        assert kind == "queued"
        response = app_module.redirect("/#tab=requests&job=7")
        response.data = {"job": {"id": 7, "state": "queued"}}
        return response

    return answer


def _route(spec: dict) -> Route:
    return Route(spec["method"], spec["path"], _answer(spec), page=spec.get("page", "the library"),
                 under=spec.get("under", False), script_only=spec.get("script_only", False))


def _form(*fields: tuple[str, str], csrf: str | None = CSRF) -> bytes:
    return urlencode(([("csrf", csrf)] if csrf is not None else []) + list(fields)).encode("utf-8")


BROWSER = {"host": HOST, "sec-fetch-site": "same-origin"}
SCRIPT = {**BROWSER, "accept": "application/json", "x-caracole-form-token": CSRF}
POSTED = {**BROWSER, "content-type": "application/x-www-form-urlencoded", "origin": f"http://{HOST}"}
JSON_POST = {**POSTED, "accept": "application/json"}
PAD = "x" * (16384 - len(_form(("pad", ""))))

# (note, method, target, headers, body)
REQUESTS: list[tuple[str, str, str, dict, bytes]] = [
    # the host check
    ("a read of the API", "GET", "/api/echo", BROWSER, b""),
    ("no Host", "GET", "/api/echo", {"sec-fetch-site": "same-origin"}, b""),
    ("a name it doesn't answer to", "GET", "/api/echo", {"host": "evil.example"}, b""),
    ("an IP address is always answered", "GET", "/api/echo", {"host": "192.168.1.20:8737"}, b""),
    ("IPv6 loopback", "GET", "/api/echo", {"host": "[::1]:8738"}, b""),
    ("a name in capitals with a final dot", "GET", "/api/echo", {"host": "LOCALHOST."}, b""),
    ("a port that isn't one", "GET", "/api/echo", {"host": "localhost:80a"}, b""),
    ("a POST to a host it doesn't answer to", "POST", "/form", {**POSTED, "host": "evil.example"}, _form()),
    ("another method to a host it doesn't answer to", "PUT", "/form", {"host": "evil.example"}, b""),
    # the path, unquoted strictly
    ("a byte that isn't UTF-8", "GET", "/%ff", BROWSER, b""),
    ("a surrogate's UTF-8", "GET", "/%ED%A0%80.pdf", BROWSER, b""),
    ("UTF-8 cut short", "GET", "/%C3", BROWSER, b""),
    ("an overlong UTF-8", "GET", "/%C0%AF.pdf", BROWSER, b""),
    ("UTF-8 escapes, decoded", "GET", "/%C3%A9t%C3%A9.pdf", BROWSER, b""),
    ("an escape that isn't one stays", "GET", "/%zz.pdf", BROWSER, b""),
    ("a lone %", "GET", "/100%.pdf", BROWSER, b""),
    ("%2F, a slash in a name", "GET", "/a%2Fb.pdf", BROWSER, b""),
    ("a route's path escaped", "GET", "/api/%65cho", BROWSER, b""),
    ("a non-ASCII character as sent", "GET", "/\xe9t\xe9.pdf", BROWSER, b""),
    ("non-ASCII then an escape", "GET", "/\xe9%C3%A9", BROWSER, b""),
    ("a target with a netloc", "GET", "//evil/api/echo", BROWSER, b""),
    ("an absolute target", "GET", "http://localhost:8737/api/echo?x=1", BROWSER, b""),
    ("a target with brackets left open", "GET", "//[::1/api/echo", BROWSER, b""),
    ("a target with an IPv4 address in brackets", "GET", "//[1.2.3.4]/api/echo", BROWSER, b""),
    ("a scheme-like target", "GET", "api:echo", BROWSER, b""),
    ("a target with no slash", "GET", "api/echo", BROWSER, b""),
    ("a query and a fragment", "GET", "/api/echo?q=caf%C3%A9#x", BROWSER, b""),
    ("a tab in the target goes", "GET", "/api/e\tcho", BROWSER, b""),
    ("leading spaces go", "GET", "  /api/echo", BROWSER, b""),
    ("an escaped %00", "GET", "/a%00.pdf", BROWSER, b""),
    # /api/ reads
    ("another site's fetch", "GET", "/api/echo", {"host": HOST, "sec-fetch-site": "cross-site"}, b""),
    ("a same-site fetch", "GET", "/api/echo", {"host": HOST, "sec-fetch-site": "same-site"}, b""),
    ("a typed address", "GET", "/api/echo", {"host": HOST, "sec-fetch-site": "none"}, b""),
    ("no browser", "GET", "/api/echo", {"host": HOST}, b""),
    ("another site's fetch of no route under /api/", "GET", "/api/nothing", {"host": HOST, "sec-fetch-site": "cross-site"},
     b""),
    ("/api without its slash, from another site", "GET", "/api", {"host": HOST, "sec-fetch-site": "cross-site"}, b""),
    ("a HEAD from another site", "HEAD", "/api/echo", {"host": HOST, "sec-fetch-site": "cross-site"}, b""),
    # script-only reads
    ("the page's script", "GET", "/jobs.json", SCRIPT, b""),
    ("no token", "GET", "/jobs.json", BROWSER, b""),
    ("no token, to the script", "GET", "/jobs.json", {**BROWSER, "accept": "application/json"}, b""),
    ("a wrong token", "GET", "/jobs.json", {**SCRIPT, "x-caracole-form-token": "old"}, b""),
    ("another site, with the token", "GET", "/jobs.json", {**SCRIPT, "sec-fetch-site": "cross-site"}, b""),
    ("another origin, with the token", "GET", "/jobs.json",
     {"host": HOST, "origin": "http://evil.example", "x-caracole-form-token": CSRF}, b""),
    ("its own origin, with the token", "GET", "/jobs.json",
     {"host": HOST, "origin": f"http://{HOST}", "x-caracole-form-token": CSRF}, b""),
    ("a HEAD of a script-only read, no token", "HEAD", "/jobs.json", BROWSER, b""),
    # routes and prefixes
    ("under a prefix", "GET", "/api/jobs/5", SCRIPT, b""),
    ("the prefix itself", "GET", "/api/jobs/", SCRIPT, b""),
    ("the prefix without its slash", "GET", "/api/jobs", SCRIPT, b""),
    ("a page with its own policy", "GET", "/", BROWSER, b""),
    ("an answer's own headers stay", "GET", "/kept", BROWSER, b""),
    ("a refusal", "GET", "/refused", BROWSER, b""),
    ("a refusal, to the script", "GET", "/refused", SCRIPT, b""),
    ("a refusal, to Accept: Application/JSON", "GET", "/refused", {**BROWSER, "accept": "text/html, Application/JSON"},
     b""),
    ("a HEAD of a route", "HEAD", "/api/echo", BROWSER, b""),
    ("a HEAD of a page", "HEAD", "/", BROWSER, b""),
    ("a file the empty library hasn't", "GET", "/Artist/Song/sheet.pdf", BROWSER, b""),
    ("a HEAD of a file it hasn't", "HEAD", "/nothing.pdf", BROWSER, b""),
    ("a file, to the script", "GET", "/nothing.pdf", SCRIPT, b""),
    ("a POST route's path read", "GET", "/form", BROWSER, b""),
    # other methods
    ("PUT", "PUT", "/form", POSTED, _form()),
    ("DELETE", "DELETE", "/api/echo", BROWSER, b""),
    ("OPTIONS", "OPTIONS", "/", BROWSER, b""),
    ("a method in lower case", "get", "/api/echo", BROWSER, b""),
    ("another method, a bad path", "PUT", "/%ff", BROWSER, b""),
    # forms
    ("a form", "POST", "/form", POSTED, _form(("song", "12"))),
    ("a form, to the script", "POST", "/form", JSON_POST, _form(("song", "12"))),
    ("nothing to send to", "POST", "/nowhere", POSTED, _form()),
    ("nothing to send to, to the script", "POST", "/nowhere", JSON_POST, _form()),
    ("a GET route posted to", "POST", "/api/echo", POSTED, _form()),
    ("a POST under a prefix", "POST", "/under/x/y", POSTED, _form()),
    ("a POST with a bad path", "POST", "/%ff", POSTED, _form()),
    ("from another site", "POST", "/form", {**POSTED, "sec-fetch-site": "cross-site"}, _form()),
    ("from another site, to the script", "POST", "/form", {**JSON_POST, "sec-fetch-site": "cross-site"}, _form()),
    ("same-site", "POST", "/form", {**POSTED, "sec-fetch-site": "same-site"}, _form()),
    ("typed", "POST", "/form", {**POSTED, "sec-fetch-site": "none"}, _form()),
    ("another origin, plain HTTP", "POST", "/form",
     {"host": HOST, "content-type": "application/x-www-form-urlencoded", "origin": "http://evil.example"}, _form()),
    ("its own origin, plain HTTP", "POST", "/form",
     {"host": HOST, "content-type": "application/x-www-form-urlencoded", "origin": f"http://{HOST}"}, _form()),
    ("no browser", "POST", "/form", {"host": HOST, "content-type": "application/x-www-form-urlencoded"}, _form()),
    ("not a form", "POST", "/form", {**POSTED, "content-type": "text/plain"}, _form()),
    ("no content type", "POST", "/form", {k: v for k, v in POSTED.items() if k != "content-type"}, _form()),
    ("a form with its charset", "POST", "/form",
     {**POSTED, "content-type": " Application/X-WWW-Form-Urlencoded ; charset=UTF-8"}, _form()),
    ("multipart", "POST", "/form", {**POSTED, "content-type": "multipart/form-data; boundary=x"}, _form()),
    ("JSON, to the script", "POST", "/form", {**JSON_POST, "content-type": "application/json"}, b'{"csrf":"tok"}'),
    ("16 KiB, the most", "POST", "/form", POSTED, _form(("pad", PAD))),
    ("a byte too long", "POST", "/form", POSTED, _form(("pad", PAD + "x"))),
    ("too long, to the script", "POST", "/form", JSON_POST, _form(("pad", PAD + "x"))),
    ("a body that isn't UTF-8", "POST", "/form", POSTED, b"csrf=tok&a=\xff"),
    ("twenty fields", "POST", "/form", POSTED, _form(*((f"f{n}", "1") for n in range(19)))),
    ("twenty-one fields", "POST", "/form", POSTED, _form(*((f"f{n}", "1") for n in range(20)))),
    ("separators count as fields", "POST", "/form", POSTED, b"csrf=tok" + b"&" * 20),
    ("nineteen empty fields", "POST", "/form", POSTED, b"csrf=tok" + b"&" * 19),
    ("no token", "POST", "/form", POSTED, _form(csrf=None)),
    ("no token, to the script", "POST", "/form", JSON_POST, _form(csrf=None)),
    ("an old token", "POST", "/form", POSTED, _form(csrf="old")),
    ("an old token, from another page", "POST", "/form/page", JSON_POST, _form(csrf="old")),
    ("an empty token", "POST", "/form", POSTED, _form(csrf="")),
    ("the token twice, the first kept", "POST", "/form", POSTED, b"csrf=tok&csrf=old"),
    ("the token twice, the first old", "POST", "/form", POSTED, b"csrf=old&csrf=tok"),
    ("the token escaped", "POST", "/form", POSTED, b"csrf=%74ok"),
    ("fields as a form writes them", "POST", "/form", JSON_POST,
     b"csrf=tok&a=1&b=&c&a=2&d=x+y&e=caf%C3%A9&f=%zz&g=%ff&h=%E2%82&i=%ED%A0%80&j=%F0%9F%8E%B8&k=%e2%82%ac%"
     b"&=v&+=%2B&l=a%3Db&m=%0A%09%22%5C%01%7F%E2%80%A8%3C"),
    ("a field with no name", "POST", "/form", JSON_POST, b"csrf=tok&=x"),
    ("UTF-8 as sent", "POST", "/form", JSON_POST, "csrf=tok&q=café".encode("utf-8")),
    ("a job queued", "POST", "/queued", POSTED, _form()),
    ("a job queued, to the script", "POST", "/queued", JSON_POST, _form()),
    ("a refusal of a form", "POST", "/refuse", POSTED, _form()),
    ("a refusal of a form, to the script", "POST", "/refuse", JSON_POST, _form()),
    ("a HEAD of a POST route", "HEAD", "/form", BROWSER, b""),
]


def _body(data: bytes, into: dict) -> dict:
    try:
        into["body"] = data.decode("utf-8")
    except UnicodeDecodeError:
        into["body_b64"] = base64.b64encode(data).decode("ascii")
    return into


def routing_records(app: WebApp) -> list[dict]:
    out: list[dict] = [{"fn": "routes", "out": {
        "allowed": ALLOWED, "csrf": CSRF, "library_name": NAME, "badge": BADGE,
        "routes": [{"under": False, "script_only": False, "page": "the library", **spec} for spec in ROUTES]}}]
    for note, method, target, headers, body in REQUESTS:
        response = app.handle(Request(method, target, headers, body))
        out.append({"fn": "caracole.web.app.WebApp.handle", "note": note,
                    "args": [_body(body, {"method": method, "target": target, "headers": headers})],
                    "out": _body(response.body, {"status": response.status,
                                                 "headers": [list(h) for h in response.headers]})})
    return out


@pytest.fixture
def routing_app(cfg, monkeypatch):
    table = {(spec["method"], spec["path"]): _route(spec) for spec in ROUTES}
    monkeypatch.setattr(app_module, "routes", lambda: table)
    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=frozenset(ALLOWED), csrf=CSRF, badge=BADGE)
    app.library_name = LibraryName(NAME, BADGE)
    return app


def test_routing_vectors_are_webapp_handles_answers(routing_app):
    assert all(spec["answer"] in ANSWERS for spec in ROUTES)
    check(WEB / "routing.jsonl", jsonl(routing_records(routing_app), corpus="web/routing", made_by=MADE_BY))


def test_the_routing_vectors_hold_every_refusal(routing_app):
    statuses = {record["out"]["status"] for record in routing_records(routing_app)[1:]}
    assert {200, 303, 400, 403, 404, 405, 409, 413, 415, 421} <= statuses


# --- the library's files ----------------------------------------------------------------------------------------

DOWNLOAD_NAMES = [
    ("Eagles", "Hotel California", "guitar-1.gp3"), ("Eagles", "Hotel California", "guitar-2.gp5"),
    ("Eagles", "Hotel California", "guitar-3.PTB"), ("Eagles", "Hotel California", "score-1.mscz"),
    ("Eagles", "Hotel California", "score-2.mid"), ("Eagles", "Hotel California", "score-10.musicxml"),
    ("Joaquín Sabina", "19 días y 500 noches", "guitar-1.gp5"), ("宋冬野", "斑马，斑马", "guitar-1.gp"),
    ("AC/DC", "What Do You Do for Money Honey?", "guitar-1.gp5"),
    ('a\\b:c*d"e<f>g|h', "x\ty\x00z\x7f‮.", "guitar-1.gp5"), ("", "Untitled", "guitar-1.gp5"),
    ("", "", "guitar-2.gp5"), ("...", "  ", "guitar-1.gp5"), (".hidden", "Song.", "guitar-1.gp5"),
    ("Muse", "Hysteria", "lyrics.lrc"), ("...", "...", "guitar-2.gp4"), ("...", "Song", "guitar-2.gp4"),
    ("Muse", ". .", "guitar-1.gp4"), ("宋" * 60, "斑马，斑马", "guitar-2.gp5"), ("Joaquín Sabina", "x" * 400, "guitar-1.gp5"),
    ("a" * 300, "b" * 300, "guitar-1.gp5"), ("é" * 100, "Song", "guitar-1.gp5"), ("Song", "é" * 100, "guitar-1.gp5"),
    ("Ángel", "Café", "guitar-1.gp5"), ("Zero​Width", "R‏L", "guitar-1.gp5"),
    ("Tab\tand\nline", "Spaces   many", "guitar-1.gp5"), ("Bell\x07", "Esc\x1b", "guitar-1.gp5"),
    ("Song", "Title", "guitar-٢.gp5"), ("Song", "Title", "guitar-02.gp5"), ("Song", "Title", "guitar-1"),
    ("Song", "Title", "sheet."), ("Song", "Title", "notes.tar.GZ"), ("Song", "Title", "guitar-1.gp5.bak"),
    ("Song", "Title", "Guitar-2.gp5"), ("Song", "Title", "guitar-2.g_5"), ("Song", "Title", "guitar-2.gp٥"),
    ("Song", "Title", ".gp5"), ("Song", "Title", "..gp5"), ("\U0001f3b8" * 40, "Title", "guitar-1.gp5"),
    ("Artist　Wide", "Title\xa0NB", "guitar-1.gp5"), ("Ünïcödé", "Ⅻ ﬁ", "score-3.mxl"),
]

DISPOSITIONS = [
    "Joaquín Sabina - 19 días y 500 noches (2).gp5", "宋冬野 - 斑马.gp", "100% - Song.gp5", 'say "hi".gp5',
    "back\\slash.gp5", "plain.gp5", "Ångström ﬁ Ⅻ.gp5", "tab\there.gp5", "\U0001f3b8 guitar.gp5", "a b+c&d=e/f?g#h.gp5",
    "Æsir ß Œ.gp5", "~tilde.gp5", "café (2).mid",
]


def download_records() -> list[dict]:
    out: list[dict] = [{"fn": "caracole.web.files.TYPES", "args": [], "out": list(files.TYPES.items())},
                       {"fn": "caracole.web.files.DOWNLOADS", "args": [], "out": sorted(files.DOWNLOADS)},
                       {"fn": "caracole.web.files.MAX_BYTES", "args": [], "out": files.MAX_BYTES}]
    out += [{"fn": "caracole.download_names.download_name", "args": list(args),
             "out": download_names.download_name(*args)} for args in DOWNLOAD_NAMES]
    out += [{"fn": "caracole.download_names.content_disposition", "args": [name],
             "out": download_names.content_disposition(name)}
            for name in DISPOSITIONS + [download_names.download_name(*args) for args in DOWNLOAD_NAMES]]
    return out


def test_download_vectors_are_files_pys_and_download_names_pys():
    check(WEB / "downloads.jsonl", jsonl(download_records(), corpus="web/downloads", made_by=MADE_BY))


# --- the pages' data --------------------------------------------------------------------------------------------


def _data(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def test_message_json_is_the_message_pages_style_and_policy():
    check(DATA / "page" / "message.json", _data({"style": pages.PAGE_STYLE, "csp": pages.PAGE_CSP}))


def test_icon_json_is_page_icons_marks():
    check(DATA / "page" / "icon.json", _data({"link": page_icon.LINK, "svg": page_icon.SVG, "mark": page_icon.mark(),
                                              "scratch_link": SCRATCH_LINK}))
