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
  (server.py, the phone's LocalServer). A message page's style, ``pages.PAGE_STYLE`` (13 KB), is written once, in
  message.json: a body holds the first record's ``style_mark`` in its place, which the Kotlin test puts it back for
  (its policy's hash, in the headers, is compared as it is). No request names a page caracole writes into the
  library (sheet.html, index.html…): the computer serves those as written (``WebApp._written_page``), the phone the
  mirror's copies.
  After the requests, what every page's data and every JSON answer are written by: ``json_response``'s body and
  inline.py's ``json_block`` and ``sha256_source``, each record's data given as the JSON text Python reads it from
  (``args`` ``[text]`` or ``[id, text]``), so its members keep their order (a corpus line sorts its own), floats
  among them.
- ``vectors/web/downloads.jsonl``: web/files.py's ``TYPES`` (its pairs, in order), ``DOWNLOADS`` and ``MAX_BYTES``, and
  download_names.py's ``download_name`` and ``content_disposition``.
- ``data/caracole/page/message.json``: ``{"style": pages.PAGE_STYLE, "csp": pages.PAGE_CSP}``, the message page's
  style and policy, which the phone's MessagePage writes its pages with.
- ``vectors/web/job_views_kinds.jsonl`` and ``vectors/web/outcome.jsonl``: every job's view, line, chips and outcome
  (jobs_routes.view, status.job_line with no to-do page, outcome.py), lane job-views': the section below says their
  shape. vectors/web/job_views.jsonl, the phone's own jobs' views, is test_conformance_sync_routes.py's.
- ``data/caracole/page/icon.json``: ``{"link": page_icon.LINK, "svg": page_icon.SVG, "mark": page_icon.mark(),
  "scratch_link": library_name.SCRATCH_LINK}``: the tab's icon, the browser's /favicon.ico, the bar's "¿", and the
  icon of a library with a badge.
"""

from __future__ import annotations

import base64
import copy
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from urllib.parse import urlencode

import pytest

from caracole import download_names, inline, page_icon
from caracole.get import GTPTABS_KEPT, MATCH_NOT_FOUND, SHEET_FROM
from caracole.library_name import SCRATCH_LINK, LibraryName
from caracole.web import app as app_module
from caracole.web import files, pages, security
from caracole.web.app import Request, Response, Route, WebApp, html_response, json_response
from caracole.web import jobs as _jobs
from caracole.web import jobs_routes as _jobs_routes
from caracole.web import outcome as _outcome
from caracole.web import songbooks as _songbooks
from caracole.web import status as _status
from caracole.web.jobs import Job as _Job
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
STYLE_MARK = "\x00message.json's style\x00"

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


def _body(data: bytes, into: dict, style: bool = False) -> dict:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        into["body_b64"] = base64.b64encode(data).decode("ascii")
    else:
        into["body"] = text.replace(f"<style>{pages.PAGE_STYLE}</style>", f"<style>{STYLE_MARK}</style>") if style \
            else text
    return into


def routing_records(app: WebApp) -> list[dict]:
    assert STYLE_MARK not in pages.PAGE_STYLE
    out: list[dict] = [{"fn": "routes", "out": {
        "allowed": ALLOWED, "csrf": CSRF, "library_name": NAME, "badge": BADGE, "style_mark": STYLE_MARK,
        "routes": [{"under": False, "script_only": False, "page": "the library", **spec} for spec in ROUTES]}}]
    for note, method, target, headers, body in REQUESTS:
        response = app.handle(Request(method, target, headers, body))
        out.append({"fn": "caracole.web.app.WebApp.handle", "note": note,
                    "args": [_body(body, {"method": method, "target": target, "headers": headers})],
                    "out": _body(response.body, {"status": response.status,
                                                 "headers": [list(h) for h in response.headers]}, style=True)})
    return out


@pytest.fixture
def routing_app(cfg, monkeypatch):
    table = {(spec["method"], spec["path"]): _route(spec) for spec in ROUTES}
    monkeypatch.setattr(app_module, "routes", lambda: table)
    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=frozenset(ALLOWED), csrf=CSRF, badge=BADGE)
    app.library_name = LibraryName(NAME, BADGE)
    return app


# What a page's data block and a JSON answer hold: its text as json.loads reads it, members in the text's order.
JSON_DATA = [
    {"t": "</script><!--é", "z": 1, "a": [None, True, False]},
    {"songs": [{"id": 3, "title": "斑马，斑马", "artist": "宋冬野"}], "fold": {"á": "a", "ß": "ss"}},
    ["\x00\x01\x08\t\n\x0b\x0c\r\x1b\x1f", "\x7f\x80\x85\xa0\xad", "\u2028\u2029\ufeff\uffff", "\U0001f3b8\U0010ffff",
     '"quoted" \\ back/slash', "<<>>&", ""],
    [0, -1, 2**53 + 1, 2**70, -(2**64)],
    [0.0, -0.0, 0.1, 1.5, 238.0, 1e-4, 1e-5, 2.5e-10, 1e7, 1e15, 9999999999999998.0, 1e16, 1.7976931348623157e308,
     5e-324, 2.2250738585072014e-308, 1 / 3, 2e23, 123456789.123],
    {"score": 87.5, "ratio": 0.6666666666666666, "when": "2026-11-03T12:00:00Z", "nested": {"x": [1.0, {"y": 1e-7}]}},
    {"z": 1, "a": 2, "m": {"b": 1, "a": 2}},
    {}, [], "plain", 7, None,
]
BLOCK_IDS = ["songs", 'a"b&<c>\'', "data-é"]
HASHED = ["", "body{}", "é", "\U0001f3b8", "a\nb\r\n", "x" * 1000]


def _text(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_records() -> list[dict]:
    out: list[dict] = [{"fn": "caracole.web.app.json_response", "args": [_text(value)],
                        "out": json_response(200, json.loads(_text(value))).body.decode("utf-8")}
                       for value in JSON_DATA]
    out += [{"fn": "caracole.inline.json_block", "args": [element_id, _text(value)],
             "out": inline.json_block(element_id, json.loads(_text(value)))}
            for element_id in BLOCK_IDS for value in JSON_DATA]
    out += [{"fn": "caracole.inline.sha256_source", "args": [text], "out": inline.sha256_source(text)}
            for text in HASHED]
    return out


def test_routing_vectors_are_webapp_handles_answers(routing_app):
    assert all(spec["answer"] in ANSWERS for spec in ROUTES)
    check(WEB / "routing.jsonl",
          jsonl(routing_records(routing_app) + json_records(), corpus="web/routing", made_by=MADE_BY))


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


# --- the jobs' views, lines, chips and outcomes (lane job-views) -------------------------------------------------
#
# ``vectors/web/job_views_kinds.jsonl``: ``caracole.web.jobs_routes.view`` over a job of every kind caracole serve
# queues, each made by its own builder through a real ``JobQueue.submit`` and set in its states as the queue and its
# command's progress lines would leave it: a lookup (``caracole get``), a sheet's versions (``caracole versions``), a
# LaCuerda artist's read and a query of its search, a harptabs.com artist's read, a songbook's change, a review's
# answer, a harmonica tab's reading, Make this my version, an add and a removal as commands, a pull another caracole
# asked for, a sheet from YouTube and a video searched for. Each record: ``job`` as the phone holds a job of commands
# (``commands``: its steps, ``{label, args, state, code, output}``; ``stages`` its stages as it heard them; ``kind`` its
# JobSpec's, ``JobCommands.kindOf``'s; ``song_id`` the view's song, ``job_song_id`` the job's own, ``started_at``,
# ``fetching``, ``note``, ``units``, ``ahead``), ``facts`` (status.SongFacts as data, or null: no such song),
# ``songbook_page`` (a songbook's change's page, or null), ``kw`` ``{"todo": null}`` (the phone has no to-do page:
# status.job_line's ``todo``), and ``out`` the view. Every kind passes through every state (queued, running, done,
# failed, cancelled, interrupted), every stage status.STAGE_LINES words runs in a job of the first kind that has it,
# and a sync's, a take's and a merge's commands (test_web_sync.peer_job) are there too.
# vectors/web/job_views.jsonl, test_conformance_sync_routes.py's, holds the phone's own jobs (a sync, an index
# import, an add and a removal it runs itself, with no command).
#
# ``vectors/web/outcome.jsonl``: first the words status.py and outcome.py look up by a name, whole (``{"fn":
# "tables", "out": {table: its words}}``), then outcome.py over the same jobs and a done lookup for each way each site
# ``_WHAT`` names waits or fails: ``out`` ``{line, steps, progress, outcome}``, status.job_line's line (todo None),
# ``outcome.steps``' chips, ``outcome.progress`` and, for a job over, ``outcome.outcome`` (``{tone, word, reason,
# action, also}``, each action ``{label, href, post, fields}``).

V_WHEN = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)
V_SONG = ("Radiohead", "Creep")
V_DISPLAY = "Radiohead - Creep"
V_KEY = "radiohead/creep"
V_ID = 12
SHEET = "Radiohead/Creep/sheet.html"
NO_PDF = "no PDF on this caracole"  # a pdf stage skipped, whatever its words: get.py's own are lane lookup's
_STEP_STATES = {"queued": "waiting", "running": "running", "done": "done", "failed": "failed",
                "cancelled": "skipped", "interrupted": "interrupted"}


def phone_kind(job: _Job) -> str:
    """The kind the phone's JobSpec gives a job of commands (JobCommands.kindOf, by its key, else its first command)."""
    key, first = job.song_key, (job.steps[0].args[0] if job.steps and job.steps[0].args else "")
    for prefix, kind in ((_jobs.REMOVING, "remove"), (_jobs.EXPORTING, "export"), (_jobs.READING, "harmonica"),
                         (_songbooks.KEY, "songbook"), (_jobs.LACUERDA_SEARCH, "lacuerda-search"),
                         (_jobs.LACUERDA_ARTIST, "lacuerda-artist"), (_jobs.HARPTABS_ARTIST, "harptabs-artist"),
                         (_jobs.YOUTUBE_SEARCH, "youtube-search"), (_jobs.YOUTUBE_SHEET, "youtube"),
                         (_jobs.INDEX_MERGE, "index-merge"), ("sync:", "sync"), ("import:", "sync")):
        if key.startswith(prefix):
            return kind
    return {"versions": "versions", "review": "review"}.get(first, "song")


def _stamp(at: datetime | None) -> str | None:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if at else None


def phone_job(job: _Job, song_id: int | None, ahead: int) -> dict:
    """A job of commands as the phone holds it (the section's comment)."""
    return {"kind": phone_kind(job), "id": job.id, "title": job.title, "display": job.display, "key": job.song_key,
            "state": job.state, "fetching": job.fetching, "note": job.note,
            "commands": [{"label": s.label, "args": list(s.args), "state": s.state, "code": s.code,
                          "output": list(s.output)} for s in job.steps],
            "stages": [{"name": s.name, "label": s.label, "state": s.state, "detail": s.detail,
                        "running_detail": s.running_detail} for s in job.stages],
            "output": [line for s in job.steps for line in s.output], "song_id": song_id,
            "job_song_id": job.song_id, "started_at": _stamp(job.started_at), "units": [list(u) for u in job.units],
            "ahead": ahead, "outcome": None}


def facts_json(facts: _status.SongFacts | None) -> dict | None:
    if facts is None:
        return None
    shown = asdict(facts)
    shown["elsewhere"] = list(facts.elsewhere) if facts.elsewhere else None
    return shown


def queued_job(title: str, key: str, steps, *, job_id: int = 7, fetching: bool = False, display: str = "",
               song_id: int | None = None, join: bool = True, note: str = "") -> _Job:
    """A job as caracole serve's queue makes it (its stages from its commands), queued."""
    made, _ = _jobs.JobQueue(lambda args, emit: 0).submit(title, key, steps, fetching=fetching, display=display,
                                                         song_id=song_id, join=join, note=note)
    job = copy.deepcopy(made)
    job.id, job.queued_at = job_id, V_WHEN
    return job


def in_state(job: _Job, state: str, stages: dict[str, tuple[str, str]] | None = None, *, output=(),
             code: int | None = None, running: dict[str, str] | None = None) -> _Job:
    """``job`` in ``state``: its one or more steps so (the last one ended so, those before it done), each stage
    ``stages`` names (name: (state, detail); a running stage's detail is its running detail, as heard; one it doesn't
    name skipped once the job is over), ``running`` the running detail a stage ended with, and ``output`` its last
    step's lines."""
    job = copy.deepcopy(job)
    job.state = state
    job.started_at = None if state in ("queued", "cancelled") else V_WHEN
    job.finished_at = V_WHEN if state not in ("queued", "running") else None
    for n, step in enumerate(job.steps):
        last = n == len(job.steps) - 1
        step.state = _STEP_STATES[state] if last else ("done" if state not in ("queued", "cancelled") else
                                                        _STEP_STATES[state])
        step.code = (0 if step.state == "done" else code if step.state == "failed" else None)
    if job.steps:
        job.steps[-1].output = list(output)
    for stage in job.stages:
        said, detail = (stages or {}).get(stage.name, (None, None))
        if said is not None:
            stage.state, stage.detail = said, detail
            if said == "running":
                stage.running_detail = detail
        if running and stage.name in running:
            stage.running_detail = running[stage.name]
        if said is None and state in ("cancelled", "done", "failed"):  # get.py says each, else the queue skips it
            stage.state = "skipped"
    return job


def lookup_job(*options, **kw) -> _Job:
    artist, title = V_SONG
    return queued_job(f"Fetch {V_DISPLAY}", V_KEY, _jobs.lookup_steps(artist, title, **dict(options)),
                      fetching=True, display=V_DISPLAY, **kw)


def ended(job: _Job, name: str, state: str = "failed") -> _Job:
    """``job`` with its running stage ``name`` ended by the queue, its waiting ones skipped."""
    for stage in job.stages:
        if stage.name == name:
            stage.state = state
        elif stage.state == "waiting":
            stage.state = "skipped"
    return job


UG_BLOCKED = ("Ultimate Guitar blocked caracole (ug: 403: https://www.ultimate-guitar.com/: blocked): no more "
              "requests to it until 2026-11-04 11:30 UTC. Nothing was marked not found.")
UG_COOLING = "Ultimate Guitar is cooling down after a block, until 2026-11-04 11:30 UTC"
UG_SPENT = "the lookup's 6 requests to Ultimate Guitar are spent; the nightly run does the rest"
HOUR_SPENT = "this hour's 60 lookup requests to LRCLIB are spent; the nightly run does the rest"
LRCLIB_503 = ("LRCLIB failed (lrclib: 503: https://lrclib.net/api/get: Service Unavailable); the nightly run tries "
              "again")
LRCLIB_DOWN = "LRCLIB failed (lrclib: network error: timed out); the nightly run tries again"
LACUERDA_BLOCKED = "LaCuerda blocked caracole (lacuerda: 429: https://acordes.lacuerda.net/: slow down)"
DONE_ALL = {"song": ("done", ""), "match": ("done", "accepted"), "sheet": ("done", "kept tab 85053"),
            "pdf": ("skipped", NO_PDF), "lyrics": ("done", "timed"), "ug": ("done", "2 more versions"),
            "lacuerda": ("skipped", "not Spanish"), "gtptabs": ("done", "no file there"),
            "harptabs": ("skipped", ""), "gametabs": ("skipped", ""), "pages": ("done", ""),
            "songbooks": ("done", "")}


def _with(base: dict, **changed: tuple[str, str]) -> dict:
    return {**base, **changed}


def kinds_jobs() -> list[tuple[str, _Job, int | None, int, _status.SongFacts | None, str | None]]:
    """Every kind of job in its states: (note, job, the view's song id, ahead, facts, songbook page)."""
    out: list[tuple[str, _Job, int | None, int, _status.SongFacts | None, str | None]] = []
    ready = _status.SongFacts(sheet=SHEET, sheet_from="UG")

    def add(note, job, song_id=V_ID, ahead=0, facts=None, page=None):
        out.append((note, job, song_id, ahead, facts, page))

    # A lookup, caracole get, in every state its stages pass through.
    look = lookup_job()
    add("a lookup queued", look, None)
    add("a lookup queued behind two", look, None, 2)
    add("its song stage, a song new to the library", in_state(look, "running", {"song": ("running", "")}), None)
    add("its song stage, a song of the library", in_state(look, "running", {"song": ("running", "")}),
        facts=_status.SongFacts())
    add("waiting for another caracole", in_state(look, "running", {"song": (
        "running", "waiting for another caracole (pid 4242), which lets a lookup go first at its next pause")}),
        facts=_status.SongFacts())
    add("its match stage", in_state(look, "running", {"song": ("done", ""), "match": ("running", "")}),
        facts=_status.SongFacts())
    add("between two stages", in_state(look, "running", {"song": ("done", ""), "match": ("done", "accepted")}),
        facts=_status.SongFacts())
    for provider, said in SHEET_FROM.items():
        add(f"its sheet asked {said}", in_state(look, "running", {"song": ("done", ""), "match": ("done", ""),
                                                                   "sheet": ("running", said)}),
            facts=_status.SongFacts())
    add("its sheet stage, said nothing yet", in_state(look, "running", {
        "song": ("done", ""), "match": ("done", MATCH_NOT_FOUND), "sheet": ("running", "")}), facts=_status.SongFacts())
    add("its lyrics, after its sheet", in_state(look, "running", _with(
        {k: v for k, v in DONE_ALL.items() if k in ("song", "match", "sheet", "pdf")}, lyrics=("running", ""))),
        facts=ready)
    add("remaking a songbook", in_state(look, "running", _with(
        {k: v for k, v in DONE_ALL.items() if k != "songbooks"}, songbooks=("running", "Campfire"))), facts=ready)
    add("writing the library page", in_state(look, "running", _with(
        {k: v for k, v in DONE_ALL.items() if k not in ("pages", "songbooks")}, pages=("running", ""))), facts=ready)
    add("done, ready", in_state(look, "done", DONE_ALL), facts=ready)
    add("done, ready from LaCuerda", in_state(look, "done", _with(DONE_ALL, sheet=("done", "kept LaCuerda's"))),
        facts=_status.SongFacts(sheet=SHEET, sheet_from="LaCuerda"), )
    add("done, ready, its lyrics wait", in_state(look, "done", _with(DONE_ALL, lyrics=("failed", LRCLIB_503))),
        facts=ready)
    add("done, ready, its lyrics' hour spent", in_state(look, "done", _with(DONE_ALL, lyrics=("skipped", HOUR_SPENT))),
        facts=ready)
    add("done, ready, LaCuerda blocked", in_state(look, "done", _with(DONE_ALL, lacuerda=("skipped", LACUERDA_BLOCKED))),
        facts=ready)
    nothing = _with(DONE_ALL, sheet=("done", "no chords on Ultimate Guitar"), pdf=("skipped", ""), ug=("skipped", ""),
                    pages=("done", ""))
    add("done, not found, UG asked", in_state(look, "done", nothing),
        facts=_status.SongFacts(checked_now=True, asked_ug=True))
    add("done, not found, LaCuerda has a sheet", in_state(look, "done", nothing), facts=_status.SongFacts(
        checked_now=True, asked_ug=True, elsewhere=("lacuerda", "https://acordes.lacuerda.net/radiohead/creep.shtml")))
    add("done, not found, gtptabs.com lists a page", in_state(look, "done", nothing), facts=_status.SongFacts(
        checked_now=True, asked_ug=True, elsewhere=("gtptabs", "https://gtptabs.com/tabs/1/radiohead-creep.html")))
    add("done, not found, a Guitar Pro file kept", in_state(look, "done", _with(nothing, gtptabs=("done", GTPTABS_KEPT))),
        facts=_status.SongFacts(checked_now=True, asked_ug=True))
    unmatched = _with(nothing, match=("done", MATCH_NOT_FOUND), sheet=("skipped", "not in the index"))
    add("done, not in the offline index", in_state(look, "done", unmatched),
        facts=_status.SongFacts(not_found=True, checked_now=True))
    add("done, not in the index, LaCuerda has it", in_state(look, "done", unmatched), facts=_status.SongFacts(
        not_found=True, checked_now=True, elsewhere=("lacuerda", "https://acordes.lacuerda.net/radiohead/creep.shtml")))
    add("done, not found, nothing known of it", in_state(look, "done", unmatched), None,
        facts=_status.SongFacts(not_found=True, checked_now=True))
    for note, detail in (("blocked", UG_BLOCKED), ("cooling down", UG_COOLING), ("its budget spent", UG_SPENT)):
        add(f"done, not fetched yet: UG {note}", in_state(look, "done", _with(
            nothing, sheet=("skipped", detail)), running={"sheet": SHEET_FROM["ug"]}), facts=_status.SongFacts())
    add("done, not fetched yet: UG failed", in_state(look, "done", _with(nothing, sheet=(
        "failed", "Ultimate Guitar failed (ug: 500: https://tabs.ultimate-guitar.com/tab/85053: oops); the nightly "
                  "run tries again")), running={"sheet": SHEET_FROM["ug"]}), facts=_status.SongFacts())
    add("done, not fetched yet, no stage said why", in_state(look, "done", _with(nothing, sheet=("skipped", ""))),
        facts=_status.SongFacts())
    add("done, needs review, its picker", in_state(look, "done", _with(nothing, match=("done", "review"))),
        facts=_status.SongFacts(review=True, picker=f"review?song={V_ID}"))
    add("done, needs review, nothing to pick", in_state(look, "done", _with(nothing, match=("done", "review"))),
        facts=_status.SongFacts(review=True))
    add("done, ignored", in_state(look, "done", {"song": ("done", ""), "match": ("skipped", "ignored")}),
        facts=_status.SongFacts(ignored=True))
    add("failed in its song stage's words", in_state(look, "failed", {"song": (
        "failed", "Ultimate Guitar's page for that tab is another song's. Pick it again.")},
        output=["error: Ultimate Guitar's page for that tab is another song's."], code=2), None)
    add("failed, a bug, its stage ended by the queue", ended(in_state(look, "failed", {
        "song": ("done", ""), "match": ("running", "")}, output=["Traceback (most recent call last):",
                                                                "error: database is locked"], code=1), "match"),
        facts=_status.SongFacts())
    add("failed, needs review", ended(in_state(look, "failed", {"song": ("done", ""), "match": ("running", "")},
                                               output=["error: no"], code=1), "match"),
        facts=_status.SongFacts(review=True, picker=f"review?song={V_ID}"))
    add("failed, not found", ended(in_state(look, "failed", {"song": ("done", ""), "match": ("running", "")},
                                            output=["error: no"], code=1), "match"),
        facts=_status.SongFacts(not_found=True))
    add("cancelled", in_state(look, "cancelled"), None)
    add("interrupted while it ran", _interrupted(in_state(look, "running", {"song": ("done", ""),
                                                                           "match": ("running", "")})),
        facts=_status.SongFacts())
    add("interrupted before it ran", _interrupted(look), None)
    no_books = lookup_job(("songbooks", False))
    add("a lookup that leaves its songbooks to a later job, running", in_state(no_books, "running", {
        "song": ("done", ""), "match": ("done", ""), "sheet": ("running", SHEET_FROM["ug"])}), facts=_status.SongFacts())
    add("a lookup that leaves its songbooks, not fetched", in_state(no_books, "done", _with(
        nothing, sheet=("skipped", UG_SPENT), songbooks=("waiting", ""))), facts=_status.SongFacts())
    picked = lookup_job(("tab", "85053"))
    add("a tab picked, done", in_state(picked, "done", DONE_ALL), facts=ready)

    # A sheet's versions: Keep it, Fetch them, Make this the one, back to caracole's pick.
    artist, title = V_SONG
    for do, options in (("keep", {"keep": "85053"}), ("keep-more", {"keep_more": True}),
                        ("choose", {"choose": "85053"}), ("clear", {})):
        job = queued_job(f"{do} {V_DISPLAY}", V_KEY, _jobs.version_steps(artist, title, **options), fetching=True,
                         display=V_DISPLAY)
        first = job.stages[1].name if len(job.stages) > 1 else job.stages[0].name
        add(f"versions --{do}, queued", job)
        add(f"versions --{do}, running", in_state(job, "running", {"song": ("done", ""), first: ("running", "")}),
            facts=ready)
        add(f"versions --{do}, done", in_state(job, "done", {s.name: ("done", "") for s in job.stages}), facts=ready)
        add(f"versions --{do}, failed", in_state(job, "failed", {"song": ("failed", "That tab isn't one of the "
                                                                                   "song's versions.")},
                                                 output=["error: That tab isn't one of the song's versions."], code=2),
            facts=ready)

    # A site's index read: a LaCuerda artist's page, a query of its search, a harptabs.com artist's page.
    reads = [
        (queued_job("Read the page of Soda Stereo on LaCuerda", _jobs.LACUERDA_ARTIST + "soda_stereo",
                    _jobs.lacuerda_artist_steps("soda_stereo", "Soda Stereo")),
         ["Read: LaCuerda's page of Soda Stereo lists 42 songs, in the index now (1 request).",
          "Not found: LaCuerda has no artist page for Soda Stereo.",
          "Not read: LaCuerda blocked caracole (lacuerda: 403: x); no more requests to it until 2026-11-04 11:30 UTC.",
          "Done, somehow"]),
        (queued_job("Search LaCuerda for “de musica ligera”", _jobs.LACUERDA_SEARCH + "de-ligera-musica",
                    _jobs.lacuerda_search_steps("de musica ligera", auto=True)),
         ["Searched: LaCuerda's search for “de musica ligera” found 3 songs (1 request).",
          "Found already: your library has “de musica ligera”; no request.",
          "Nothing found: LaCuerda has no song for “de musica ligera”.",
          "Not searched: this hour's 20 searches of LaCuerda the page sends by itself are spent; ask again later."]),
        (queued_job("Read the page of Bob Dylan on harptabs.com", _jobs.HARPTABS_ARTIST + "/artist/bob-dylan",
                    _jobs.harptabs_artist_steps("/artist/bob-dylan", "Bob Dylan")),
         ["Read: harptabs.com's page of Bob Dylan lists 30 tabs (1 request).",
          "Not read: harptabs.com failed (harptabs: 500: x); nothing changed: try again later."]),
    ]
    for job, endings in reads:
        kind = phone_kind(job)
        add(f"{kind}, queued", job, None)
        add(f"{kind}, running", in_state(job, "running", {s.name: ("running", "") for s in job.stages}), None)
        for said in endings:
            add(f"{kind}, done: {said[:24]}", in_state(job, "done", {s.name: ("done", "") for s in job.stages},
                                                       output=["GET https://… → 200", said]), None)
        add(f"{kind}, failed", in_state(job, "failed", output=["error: The index can't be written."], code=1), None)

    # A songbook's change, each action.
    form = {"make": ("make", "Campfire", V_DISPLAY), "add": ("add", "Campfire", V_DISPLAY),
            "move": ("move", "Campfire", V_DISPLAY, "2"), "remove": ("remove", "Campfire", V_DISPLAY),
            "rename": ("rename", "Campfire", "Fireside"), "delete": ("delete", "Campfire")}
    labels = {"make": "Making the songbook", "add": "Adding to the songbook", "move": "Moving the song",
              "remove": "Taking the song out", "rename": "Renaming the songbook", "delete": "Deleting the songbook"}
    books = [(action, _songbooks._job(f"{action} Campfire", labels[action], *words)) for action, words in form.items()]
    books.append(("render", _songbooks.render_job("Campfire", 6)))
    books.append(("set", _songbooks._setting_job("Campfire", V_DISPLAY, {"key": "G", "capo": "0"})))
    for action, book in books:
        job = queued_job(book.title, book.key, book.steps)
        page = "_songbooks/Campfire/songbook.html" if action in ("make", "add", "render") else None
        add(f"songbook {action}, running", in_state(job, "running"), None)
        add(f"songbook {action}, done", in_state(job, "done"), None, page=page)
        if action == "make":
            add("songbook make, done, no page written", in_state(job, "done"), None)
            add("songbook make, failed", in_state(job, "failed", output=['error: A songbook named "Campfire" is '
                                                                         "there already."], code=2), None)

    # A review's answer, with a fetch after it.
    review = queued_job(f"Pick radiohead/creep for {V_DISPLAY}, and fetch it", V_KEY,
                        _jobs.review_steps(V_DISPLAY, pick="radiohead/creep") + [
                            s for s in _jobs.fetch_steps(V_DISPLAY) if s[1][0] != "match"],
                        fetching=True, join=False, display=V_DISPLAY)
    add("a review's pick and its fetch, running", in_state(review, "running"), facts=_status.SongFacts(review=True))
    add("a review's pick and its fetch, done", in_state(review, "done"), facts=ready)
    add("a review's pick, its fetch failed", in_state(review, "failed", output=["error: no"], code=1),
        facts=_status.SongFacts(review=True, picker=f"review?song={V_ID}"))
    none = queued_job(f"None of these for {V_DISPLAY}", V_KEY, _jobs.review_steps(V_DISPLAY, seen=["a/b", "c/d"]),
                      join=False, display=V_DISPLAY)
    add("none of these, done", in_state(none, "done"), facts=_status.SongFacts(not_found=True))

    # A harmonica tab's reading, pinned and cleared; Make this my version.
    for options, said in ((("--as=letters",), '"letters"'), (("--clear",), "clear")):
        steps = [("Reading the harmonica tab as you set it", ("harmonica", "--tab=harmonica-1.txt", *options, "--",
                                                              *V_SONG))]
        job = queued_job(f"Read harmonica-1.txt of {V_DISPLAY}", f"{_jobs.READING}{V_KEY}:harmonica-1.txt:{said}"
                         f"{_jobs.MINE}", steps, display=V_DISPLAY, song_id=V_ID)
        add(f"a harmonica reading {said}, running", in_state(job, "running"), None, facts=ready)
        add(f"a harmonica reading {said}, done", in_state(job, "done"), None, facts=ready)
    mine = queued_job(f"Make {V_DISPLAY} your version", f"{_jobs.EXPORTING}{V_KEY}:key=G{_jobs.MINE}",
                      [("Making it your version", ("render", f"--song={V_DISPLAY}", "--version=key=G", "--mine"))],
                      display=V_DISPLAY, song_id=V_ID)
    add("make it mine, running", in_state(mine, "running"), None, facts=ready)
    add("make it mine, done", in_state(mine, "done"), None, facts=ready)
    add("make it mine, done, no sheet", in_state(mine, "done"), None, facts=_status.SongFacts())
    add("make it mine, failed", in_state(mine, "failed", output=["error: That version can't be made."], code=2),
        None, facts=ready)

    # An add and a removal as caracole serve queues them: commands.
    plain = queued_job(f"Add {V_DISPLAY}", V_KEY, _jobs.add_steps(*V_SONG), display=V_DISPLAY)
    add("an add, done, the nightly run looks", in_state(plain, "done"), facts=_status.SongFacts())
    add("an add, done, its sheet there", in_state(plain, "done"), facts=ready)
    add("an add, done, a LaCuerda sheet picked", in_state(plain, "done"), facts=_status.SongFacts(lacuerda=True))
    add("an add, done, needs review", in_state(plain, "done"), facts=_status.SongFacts(review=True))
    add("an add, done, ignored", in_state(plain, "done"), facts=_status.SongFacts(ignored=True))
    fetch = queued_job(f"Fetch {V_DISPLAY}", V_KEY, _jobs.add_steps(*V_SONG) + _jobs.fetch_steps(V_DISPLAY),
                       fetching=True, display=V_DISPLAY)
    add("a fetch of commands, running its second", in_state(fetch, "running"), facts=_status.SongFacts())
    add("a fetch of commands, done, not found", in_state(fetch, "done"), facts=_status.SongFacts(checked_now=True))
    add("a fetch of commands, done, not fetched", in_state(fetch, "done"), facts=_status.SongFacts())
    removal = queued_job(f"Remove {V_DISPLAY}", _jobs.REMOVING + V_KEY, _jobs.remove_steps(V_DISPLAY),
                         display=V_DISPLAY, song_id=V_ID, join=False)
    add("a removal of commands, done", in_state(removal, "done"))
    add("a removal of commands, failed", in_state(removal, "failed", output=["error: wanted.txt can't be read."],
                                                  code=1))
    add("a removal of commands, interrupted while it ran", _interrupted(in_state(removal, "running")))
    add("a removal of commands, interrupted before it ran", _interrupted(removal))

    # A pull another caracole asked for; a sheet from a YouTube video; a video searched for.
    pull = queued_job("Sync with http://192.168.1.20:8737", "peer-pull:http://192.168.1.20:8737",
                      [("Taking 2 changes from http://192.168.1.20:8737",
                        ("peer", "pull", "--unit=song/a/b", "--unit=song/c/d", "--", "http://192.168.1.20:8737"))],
                      display="http://192.168.1.20:8737", join=False)
    add("a pull, queued", pull, None)
    done_pull = in_state(pull, "done")
    done_pull.units = [("song/a/b", "taken", ""), ("song/c/d", "left", "changed here")]
    add("a pull, done, one left", done_pull, None)
    youtube = queued_job(f"YouTube sheet {V_DISPLAY}", _jobs.YOUTUBE_SHEET + V_KEY,
                         _jobs.youtube_sheet_steps(V_DISPLAY, "https://www.youtube.com/watch?v=XFkzRNyygfk"),
                         display=V_DISPLAY)
    add("a sheet from YouTube, its audio", in_state(youtube, "running", {"song": ("done", ""),
                                                                        "audio": ("running", "")}), facts=ready)
    add("a sheet from YouTube, ready", in_state(youtube, "done", {
        "song": ("done", ""), "audio": ("done", ""), "lyrics": ("done", ""),
        "chords": ("done", "chords over the timed lyrics"), "pdf": ("done", ""), "pages": ("done", "")}), facts=ready)
    add("a sheet from YouTube, not made", in_state(youtube, "done", {
        "song": ("done", ""), "audio": ("skipped", "YouTube is cooling down after a block, until 2026-11-04 11:30 UTC")}),
        facts=_status.SongFacts())
    video = queued_job("Search YouTube for “creep”", _jobs.YOUTUBE_SEARCH + "creep",
                       _jobs.youtube_search_steps("creep"))
    add("a video searched for, done", in_state(video, "done", {"video": ("done", ""), "thumbnail": ("done", "")},
                                               output=["Searched: YouTube's first video for “creep” is Creep "
                                                       "(Radiohead), https://www.youtube.com/watch?v=XFkzRNyygfk."]),
        None)

    # Each kind in every state a request passes through, beside the kind's own records above.
    keep = queued_job(f"keep {V_DISPLAY}", V_KEY, _jobs.version_steps(artist, title, keep="85053"), fetching=True,
                      display=V_DISPLAY)
    make = next(book for action, book in books if action == "make")
    harp = queued_job(f"Read harmonica-1.txt of {V_DISPLAY}", f"{_jobs.READING}{V_KEY}:harmonica-1.txt:clear"
                      f"{_jobs.MINE}", [("Reading the harmonica tab as you set it", (
                          "harmonica", "--tab=harmonica-1.txt", "--clear", "--", *V_SONG))],
                      display=V_DISPLAY, song_id=V_ID)
    for note, job, song_id, facts in (
            ("versions --keep", keep, V_ID, ready), *((phone_kind(job), job, None, None) for job, _ in reads),
            ("songbook make", queued_job(make.title, make.key, make.steps), None, None),
            ("a review's pick and its fetch", review, V_ID, _status.SongFacts(review=True)),
            ("a harmonica reading", harp, None, ready), ("make it mine", mine, None, ready),
            ("an add", plain, V_ID, _status.SongFacts()), ("a fetch of commands", fetch, V_ID, _status.SongFacts()),
            ("a removal of commands", removal, V_ID, None), ("a pull", pull, None, None),
            ("a sheet from YouTube", youtube, V_ID, ready), ("a video searched for", video, None, None)):
        first = {job.stages[0].name: ("running", "")} if job.stages else None
        add(f"{note}, every state: queued", job, song_id, facts=facts)
        add(f"{note}, every state: queued behind one", job, song_id, 1, facts=facts)
        add(f"{note}, every state: running", in_state(job, "running", first), song_id, facts=facts)
        add(f"{note}, every state: done", in_state(job, "done", {s.name: ("done", "") for s in job.stages}),
            song_id, facts=facts)
        add(f"{note}, every state: failed", in_state(job, "failed", output=["<3>error: It broke. Try again."],
                                                     code=1), song_id, facts=facts)
        add(f"{note}, every state: cancelled", in_state(job, "cancelled"), song_id, facts=facts)
        add(f"{note}, every state: interrupted while it ran", _interrupted(in_state(job, "running", first)),
            song_id, facts=facts)
        add(f"{note}, every state: interrupted before it ran", _interrupted(job), song_id, facts=facts)

    # Each stage status.STAGE_LINES words, running, in the first kind of job that has it (the phone's own sync's
    # mirror and index stages are job_views.jsonl's), every stage before it done.
    staged = [lookup_job(), keep, reads[1][0], youtube, video] + [peer_job(kind, "queued") for kind in PEER_KINDS]
    for name in _status.STAGE_LINES:
        job = next((j for j in staged if name in [s.name for s in j.stages]), None)
        if job is None:
            continue
        names = [s.name for s in job.stages]
        said = {n: ("done", "") for n in names[:names.index(name)]} | {name: ("running", "")}
        songless = job.song_key.startswith(_jobs.INDEX_READS) or _status.peer_kind(job) is not None
        add(f"its {name} stage running ({phone_kind(job)})", in_state(job, "running", said),
            None if songless else V_ID, facts=None if songless else _status.SongFacts())
    # The commands of a sync, a take and a merge (test_web_sync.peer_job), in every state.
    out += peer_jobs()
    return out


PEER_KINDS = ("sync", "peer-push", "index-merge")


def peer_jobs() -> list[tuple[str, _Job, int | None, int, _status.SongFacts | None, str | None]]:
    """The syncs, imports of a file, takes and merges caracole serve runs (test_web_sync.peer_job), each in its
    states."""
    from test_web_sync import peer_job

    took = [("song/oasis/wonderwall", "taken", ""), ("song/muse/hysteria", "given", "")]
    left = took + [("song/radiohead/creep", "left", "skipped, as chosen")]
    jobs = []
    for kind, done in (("sync", {"compare": ("done", "4 differences"), "take": ("done", "took 1"),
                                 "give": ("done", "gave 1"), "agree": ("done", "12 units the two agree on")}),
                       ("peer-push", {"check": ("done", "1 change"), "take": ("done", "took 1"),
                                      "render": ("skipped", ""), "agree": ("done", "12 units the two agree on")}),
                       ("index-merge", {"merge": ("done", "merged 12 pages: ug, lacuerda")}),
                       ("import", {"check": ("done", "2 differences with Desk's file"), "take": ("done", "took 1"),
                                   "render": ("done", ""), "agree": ("done", "12 units the two agree on, 1 kept here"),
                                   "index": ("done", "1 index merged")})):
        first = next(iter(done))
        jobs += [
            (f"{kind}, queued", peer_job(kind, "queued"), None, 0, None, None),
            (f"{kind}, running", peer_job(kind, "running", {first: ("running", "")}), None, 0, None, None),
            (f"{kind}, done", peer_job(kind, "done", done, units=took), None, 0, None, None),
            (f"{kind}, done, one left", peer_job(kind, "done", done, units=left), None, 0, None, None),
            (f"{kind}, done, nothing", peer_job(kind, "done", {first: ("done", "")}), None, 0, None, None),
            (f"{kind}, failed", peer_job(kind, "failed", {first: ("failed", "The other caracole answered 500.")},
                                         output=["error: The other caracole answered 500."]), None, 0, None, None),
            (f"{kind}, cancelled", peer_job(kind, "cancelled"), None, 0, None, None),
            (f"{kind}, interrupted", _interrupted(peer_job(kind, "running", {first: ("running", "")})), None, 0,
             None, None),
            (f"{kind}, interrupted before it ran", _interrupted(peer_job(kind, "queued")), None, 0, None, None),
        ]
    # A sync's agree stage counted in another script's digits, as Python's \d and int() read them.
    jobs.append(("sync, done, its count in Arabic-Indic digits", peer_job("sync", "done", {
        "compare": ("done", ""), "agree": ("done", " ١٢ units the two agree on\n")}, units=took),
        None, 0, None, None))
    return jobs


def peer_job(kind: str, state: str, stages: dict[str, tuple[str, str]] | None = None, **kw) -> _Job:
    from test_web_sync import peer_job as made

    return made(kind, state, stages, **kw)


def _interrupted(job: _Job) -> _Job:
    """``job`` as the server's stop or a restart leaves it (history.interrupt): its running step and stage
    interrupted, those waiting skipped."""
    from caracole.web.history import interrupt

    job = copy.deepcopy(job)
    interrupt(job, at=V_WHEN)
    return job


def _todo_none(monkeypatch) -> None:
    """jobs_routes.view's line as the phone says it: status.job_line with no to-do page (``todo=None``)."""
    monkeypatch.setattr(_jobs_routes, "job_line", partial(_status.job_line, todo=None))


def view_kind_records(monkeypatch) -> list[dict]:
    _todo_none(monkeypatch)
    records = []
    for note, job, song_id, ahead, facts, page in kinds_jobs():
        queue = [_Job(job.id - 1 - n, "Add Other", f"other/{n}", [_jobs.Step("Adding to the library", ("add",))])
                 for n in range(ahead)] + [job]
        out = _jobs_routes.view(job, queue[::-1], song_id, facts, songbook_page=page)
        records.append({"fn": "caracole.web.jobs_routes.view", "note": note, "job": phone_job(job, song_id, ahead),
                        "facts": facts_json(facts), "songbook_page": page, "args": [], "kw": {"todo": None},
                        "out": out})
    return records


def _action(action: _outcome.Action | None) -> dict | None:
    if action is None:
        return None
    return {"label": action.label, "href": action.href, "post": action.post, "fields": [list(f) for f in action.fields]}


SITE_NAMES = {"sheet": ("Ultimate Guitar", "ug"), "lyrics": ("LRCLIB", "lrclib"), "ug": ("Ultimate Guitar", "ug"),
              "lacuerda": ("LaCuerda", "lacuerda"), "gtptabs": ("gtptabs.com", "gtptabs"),
              "harptabs": ("harptabs.com", "harptabs"), "gametabs": ("gametabs.net", "gametabs")}


def reason_jobs() -> list[tuple[str, _Job, int | None, int, _status.SongFacts | None, str | None]]:
    """A done lookup each of whose stages outcome.py's ``_WHAT`` names failed or was skipped in each of get.py's ways
    of saying why (an answer, an error, a block, a cooldown, a spent budget), the others done: the sheet's leaves the
    song without one."""
    out = []
    look = lookup_job()
    for name, (site, provider) in SITE_NAMES.items():
        facts = _status.SongFacts() if name == "sheet" else _status.SongFacts(sheet=SHEET, sheet_from="UG")
        for said, detail in (
                ("failed", f"{site} failed ({provider}: 503: https://{provider}.example/: busy); the nightly run tries "
                           "again"),
                ("failed", f"{site} failed ({provider}: network error: timed out); the nightly run tries again"),
                ("skipped", f"{site} blocked caracole ({provider}: 429: https://{provider}.example/: slow down): no "
                            "more requests to it until 2026-11-04 11:30 UTC. Nothing was marked not found."),
                ("skipped", f"{site} blocked caracole ({provider}: 403: x)"),
                ("skipped", f"{site} is cooling down after a block, until 2026-11-04 11:30 UTC"),
                ("skipped", f"the lookup's 6 requests to {site} are spent; the nightly run does the rest")):
            stages = _with(DONE_ALL, **{name: (said, detail)})
            if name == "sheet":
                stages = _with(stages, pdf=("skipped", ""), ug=("skipped", ""))
            out.append((f"done, its {name} stage {said}: {detail[:40]}",
                        in_state(look, "done", stages, running={name: SHEET_FROM["ug"]} if name == "sheet" else None),
                        V_ID, 0, facts, None))
    return out


def tables_record() -> dict:
    """The words status.py and outcome.py look up by a stage's, a step's or a command's name, whole: what the
    records above don't draw (the phone's own sync's mirror and index stages among them)."""
    from caracole.web import songbooks

    return {"fn": "tables", "args": [], "kw": {}, "out": {
        "STAGE_LINES": _status.STAGE_LINES, "PEER_KINDS": _status.PEER_KINDS, "PEER_DONE": _status._PEER_DONE,
        "SHEET_LINES": _status._SHEET_LINES, "READ_TONES": _status._READ_TONES,
        "SONGBOOK_DONE": songbooks.DONE, "SONGBOOK_OPENS": sorted(songbooks.OPENS),
        "LOOKUP_STEPS": [[name, list(names)] for name, names in _outcome.LOOKUP_STEPS],
        "YOUTUBE_STEPS": [[name, list(names)] for name, names in _outcome.YOUTUBE_STEPS],
        "COMMAND_STEPS": _outcome.COMMAND_STEPS, "PEER_STEPS": _outcome.PEER_STEPS, "ASKS": _outcome._ASKS,
        "WHAT": {name: list(said) for name, said in _outcome._WHAT.items()}, "ELSEWHERE": _outcome._ELSEWHERE}}


def outcome_records() -> list[dict]:
    """outcome.py's chips, progress and outcome of every job of ``kinds_jobs`` (the syncs, takes and merges caracole
    serve runs among them) and of ``reason_jobs``, each line status.job_line's with ``todo=None``; after the tables."""
    jobs = kinds_jobs() + reason_jobs()
    records = []
    for note, job, song_id, ahead, facts, page in jobs:
        line = _status.job_line(job, facts, ahead=ahead, songbook_page=page, todo=None)
        over = None if job.active else _outcome.outcome(job, line, facts, song_id=song_id)
        shown = None if over is None else {"tone": over.tone, "word": over.word, "reason": over.reason,
                                           "action": _action(over.action), "also": _action(over.also)}
        records.append({"fn": "caracole.web.outcome", "note": note, "job": phone_job(job, song_id, ahead),
                        "facts": facts_json(facts),
                        "songbook_page": page, "args": [], "kw": {"todo": None},
                        "out": {"line": line.as_json(),
                                "steps": [chip.as_json() for chip in _outcome.steps(job, facts)],
                                "progress": _outcome.progress(job, line, facts), "outcome": shown}})
    return [tables_record()] + records


def test_job_views_kinds_jsonl_is_what_the_views_say_of_every_kind_caracole_serve_queues(monkeypatch):
    records = view_kind_records(monkeypatch)
    kinds = {r["job"]["kind"] for r in records}
    assert {"song", "versions", "lacuerda-artist", "lacuerda-search", "harptabs-artist", "songbook", "review",
            "harmonica", "export", "remove", "youtube", "youtube-search"} <= kinds
    assert {r["out"]["kind"] for r in records} >= {"song", "remove", "export", "songbook", "peer-pull"}
    every = {"queued", "running", "done", "failed", "cancelled", "interrupted"}
    for kind in kinds | {"sync", "peer-push", "index-merge"}:  # every kind in every state
        assert {r["job"]["state"] for r in records if kind in (r["job"]["kind"], r["out"]["kind"])} == every, kind
    running = {s["name"] for r in records if r["job"]["state"] == "running" for s in r["job"]["stages"]
               if s["state"] == "running"}
    assert set(_status.STAGE_LINES) - running == {"mirror"}  # the phone's own sync's: job_views.jsonl's
    check(WEB / "job_views_kinds.jsonl", jsonl(records, corpus="web/job_views", made_by=MADE_BY))


def test_outcome_jsonl_is_what_the_requests_tab_says_of_each_job():
    tables, *records = outcome_records()
    assert tables["fn"] == "tables"
    words = {r["out"]["outcome"]["word"] for r in records if r["out"]["outcome"]}
    reasons = {r["out"]["outcome"]["reason"] for r in records if r["out"]["outcome"]}
    for name, (what, verb) in _outcome._WHAT.items():  # each site's wait and error said
        assert {f"{what} {verb} for tonight's run.", f"{what} {verb} until 2026-11-04 11:30 UTC."} <= {
            reason.partition(": ")[2] for reason in reasons}, name
    assert {"Ready", "Not found", "Not fetched yet", "Needs review", "Failed", "Cancelled", "Interrupted",
            "Removed", "Synced", "Taken", "Merged"} <= words
    assert any(r["out"]["outcome"] and r["out"]["outcome"]["also"] for r in records)
    check(WEB / "outcome.jsonl", jsonl([tables, *records], corpus="web/outcome", made_by=MADE_BY))


def test_a_skipped_pdf_stage_is_no_chip_and_says_nothing():
    # A caracole that makes no PDF skips its pdf stage, whatever its words: no step drawn, no reason read.
    job = in_state(lookup_job(), "done", DONE_ALL)
    assert "PDF" not in [chip.name for chip in _outcome.steps(job)]
    line = _status.job_line(job, _status.SongFacts(sheet=SHEET), todo=None)
    assert _outcome.outcome(job, line, _status.SongFacts(sheet=SHEET)).reason == ""


# --- what the library knows of a job's song: jobs_routes.song_of (lane job-views) ---------------------------------
#
# ``vectors/web/job_views_song_of.jsonl``: ``caracole.web.jobs_routes.song_of`` over a small library a record, built
# with caracole's own writers for that case (helpers/peer_libraries.py's ``Library``: wanted.txt lines synced into
# songs, ``versions.upsert_version``, ``library.keep_file``, overrides.py's writers), then dumped before it is asked
# (``fixture``: helpers.corpus.dump_fixture's records, its kept files left out, then the phone's rows of its
# overrides.toml as test_conformance_sync.phone_rows writes them, and, where the case turns gtptabs.com off, the
# phone's settings saying so, kv ``phone:settings``). Each record: ``job`` as job_views_kinds.jsonl holds one;
# ``sheets`` each song's sheet link, ``[[id, href]]`` (library_page.sheet_href, read from the kept files the fixture
# leaves out: the phone's SongCards give it); ``now`` the time ``outcome.elsewhere`` is asked at; and ``out``
# ``[the song's id, its facts]`` (facts as job_views_kinds.jsonl writes them, null for no such song), or ``err`` the
# class of what Python raised.

SONG_OF_NOW = datetime(2026, 11, 3, 9, 45, tzinfo=UTC)
LACUERDA_ROW = {"path": "radiohead/creep", "artist_slug": "radiohead", "artist": "Radiohead",
                "artist_key": "radiohead", "title": "Creep", "title_key": "creep", "songs": 0, "versions": "1 2",
                "acordes": 2, "popular": 3, "page": "r"}
GTPTABS_ROW = {"path": "tabs/7/radiohead-creep.html", "artist_path": "tabs/7.html", "artist_key": "radiohead",
               "title_key": "creep", "base_key": "creep", "sitemap": "s1"}
TAB_PASTED = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"


class _SongOfClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return SONG_OF_NOW if tz is None else SONG_OF_NOW.astimezone(tz)


def _insert(lib, table: str, row: dict) -> None:
    lib.conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                     list(row.values()))


def _kept(lib, song, name: str, provider: str, kind: str = "chords"):
    """A file of ``song`` kept under ``name``, of a version of ``provider``'s."""
    from caracole.library import keep_file
    from caracole.versions import upsert_version
    from helpers.peer_libraries import NOW

    slot = "sheet" if kind == "chords" else "guitar"
    vid = upsert_version(lib.conn, provider=provider, tab_id=f"{provider}-{name}", song_id=song.id, slot=slot,
                         kind=kind, rating=4.5, votes=10, version=1, label=None, url=f"https://u/{provider}", raw={},
                         now=NOW)
    keep_file(lib.conn, lib.cfg.library_dir, song=song, version_id=vid, name=name, data=b"[Am]Creep", rank=1)


def song_of_cases() -> list[tuple]:
    """(note, build, job, gtptabs on): ``build(lib)`` fills a library and gives the job's song id where the job
    names its song by it, ``job(song_id)`` makes the job."""
    from caracole.overrides import add_alias, add_artist_url, put_song_entries
    from caracole.songs import update_song

    def song(lib, *, sheet=False, entries=None, **cols):
        made = lib.song(*V_SONG, sheet=b"[Am]Creep" if sheet else None, lyrics=None)
        if cols:
            update_song(lib.conn, made.id, **cols)
        if entries:
            put_song_entries(lib.cfg.overrides_file, V_DISPLAY, entries)
        return made.id

    look = lookup_job()
    nothing = _with(DONE_ALL, sheet=("done", "no chords on Ultimate Guitar"), pdf=("skipped", ""),
                    ug=("skipped", ""), gtptabs=("skipped", ""))  # gtptabs.com not asked: a page there may be
    unmatched = _with(nothing, match=("done", MATCH_NOT_FOUND), sheet=("skipped", "not in the index"))
    done, running = in_state(look, "done", nothing), in_state(look, "running", {"song": ("done", "")})
    missed = in_state(look, "done", unmatched)
    accepted = {"match_decision": "accept", "match_artist_key": "radiohead", "match_song_key": "creep"}
    not_found = {"match_decision": "not_found"}
    before, at, after = "2026-11-03T09:29:59Z", "2026-11-03T09:30:00Z", "2026-11-03T09:31:00Z"
    candidates = [{"artist_key": "radiohead", "song_key": "creep", "score": 88.0}]

    def lookup(job):
        return lambda _id: job

    def by_id(make):
        return make

    def with_kv(**kv):
        def build(lib):
            sid = song(lib, **not_found)
            for key, value in kv.items():
                lib.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (key.format(id=sid), value))
            return sid
        return build

    plain = queued_job(f"Add {V_DISPLAY}", V_KEY, _jobs.add_steps(*V_SONG), display=V_DISPLAY)

    def removal(state):
        def make(song_id):
            job = queued_job(f"Remove {V_DISPLAY}", _jobs.REMOVING + V_KEY, _jobs.remove_steps(V_DISPLAY),
                             display=V_DISPLAY, song_id=song_id, join=False)
            return in_state(job, state)
        return make

    def export(key, steps):
        def make(song_id):
            return in_state(queued_job(f"Make {V_DISPLAY} yours", key, steps, display=V_DISPLAY, song_id=song_id),
                            "done")
        return make

    mine = export(f"{_jobs.EXPORTING}{V_KEY}:key=G{_jobs.MINE}",
                  [("Making it your version", ("render", f"--song={V_DISPLAY}", "--version=key=G", "--mine"))])
    reading = export(f"{_jobs.READING}{V_KEY}:harmonica-1.txt:clear{_jobs.MINE}",
                     [("Reading the harmonica tab", ("harmonica", "--tab=harmonica-1.txt", "--clear", "--",
                                                     *V_SONG))])

    def gone(lib):
        sid = song(lib)
        lib.conn.execute("DELETE FROM songs WHERE id = ?", (sid,))
        return sid

    def other_sheet(provider, name):
        def build(lib):
            sid = song(lib)
            _kept(lib, lib.conn and _song(lib, sid), name, provider)
            return sid
        return build

    def lacuerda_row(**cols):
        def build(lib):
            sid = song(lib, **accepted, ug_checked_at=after, **cols)
            _insert(lib, "lacuerda_index", LACUERDA_ROW)
            return sid
        return build

    def gtptabs_row(*, kv=None, guitar=False, **row):
        def build(lib):
            sid = song(lib, **accepted, ug_checked_at=after)
            _insert(lib, "gtptabs_index", GTPTABS_ROW | row)
            if kv is not None:
                lib.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (f"gtptabs:checked:{sid}", kv))
            if guitar:
                _kept(lib, _song(lib, sid), "guitar-1.gp5", "gtptabs", "guitar-pro")
            return sid
        return build

    def both(*, cooling=None, **cols):
        def build(lib):
            sid = lacuerda_row(**cols)(lib)
            _insert(lib, "gtptabs_index", GTPTABS_ROW)
            for provider, until in (cooling or {}).items():
                lib.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (f"provider:{provider}", json.dumps(
                    {"strikes": 1, "cooldown_until": until, "last_ok": None, "last_error": "403",
                     "last_error_at": "2026-11-03T08:00:00Z"})))
            return sid
        return build

    def stage(name, said, detail):
        return lookup(in_state(look, "done", _with(nothing, **{name: (said, detail)})))

    def artist(how):
        def build(lib):
            sid = song(lib, **not_found)
            if how == "index":
                _insert(lib, "ug_index", {"tab_id": 85053, "artist_key": "radiohead", "song_key": "karma-police",
                                          "type": "chords", "sitemap": "s", "first_seen": "2026-10-01T00:00:00Z",
                                          "path": "radiohead/karma-police-chords-85053"})
            elif how == "learned":
                lib.conn.execute("INSERT INTO kv (key, value) VALUES ('ug:artist_url:radiohead', ?)",
                                 ("https://www.ultimate-guitar.com/artist/radiohead_1",))
            elif how == "alias":
                add_alias(lib.cfg.overrides_file, "Radiohead", "Radio-Head")
                _insert(lib, "ug_index", {"tab_id": 85053, "artist_key": "radio-head", "song_key": "creep",
                                          "type": "chords", "sitemap": "s", "first_seen": "2026-10-01T00:00:00Z",
                                          "path": "radio-head/creep-chords-85053"})
            elif how == "page":
                add_artist_url(lib.cfg.overrides_file, "Radiohead", "https://www.ultimate-guitar.com/artist/radiohead_1")
            elif how == "page by a form":
                add_artist_url(lib.cfg.overrides_file, "Radiohead (レディオヘッド)",
                               "https://www.ultimate-guitar.com/artist/radiohead_1")
            elif how.startswith("tab"):
                add_artist_url(lib.cfg.overrides_file, "Radiohead", TAB_PASTED)
                record = {"tab problem": {"problem": "it leads to no artist page"},
                          "tab read": {"artist_url": "https://www.ultimate-guitar.com/artist/radiohead_1"},
                          "tab empty problem": {"problem": ""}, "tab not read": None}[how]
                if record is not None:
                    lib.conn.execute("INSERT INTO kv (key, value) VALUES ('ug:pasted_tab:4169', ?)",
                                     (json.dumps(record),))
            return sid
        return build

    lacuerda_page = "https://acordes.lacuerda.net/radiohead/creep.shtml"
    return [
        # No such song; a job of no song's.
        ("no such song", lambda lib: None, lookup(done), True),
        ("a pull's: no song's", lambda lib: song(lib), lambda _id: in_state(queued_job(
            "Sync", "peer-pull:http://192.168.1.20:8737", [("Taking", ("peer", "pull", "--", "http://x"))]), "done"),
         True),
        # Its sheet, and where it came from.
        ("a sheet kept, a lookup done", lambda lib: song(lib, sheet=True), lookup(in_state(look, "done", DONE_ALL)),
         True),
        ("a sheet kept, a lookup running", lambda lib: song(lib, sheet=True), lookup(running), True),
        ("a sheet kept, an add of commands", lambda lib: song(lib, sheet=True), lookup(in_state(plain, "done")),
         True),
        ("LaCuerda's sheet kept", other_sheet("lacuerda", "sheet.txt"), lookup(in_state(look, "done", DONE_ALL)),
         True),
        ("an auto sheet kept", other_sheet("auto", "sheet (auto).txt"), lookup(in_state(look, "done", DONE_ALL)),
         True),
        # A fetch that left no sheet: did it look the song up during the job (ug.fetch.checked_since)?
        ("no sheet, a lookup running", lambda lib: song(lib, **accepted, ug_checked_at=after), lookup(running), True),
        ("UG checked before it started", lambda lib: song(lib, **accepted, ug_checked_at=before), lookup(done), True),
        ("UG checked as it started", lambda lib: song(lib, **accepted, ug_checked_at=at), lookup(done), True),
        ("UG checked after it started", lambda lib: song(lib, **accepted, ug_checked_at=after), lookup(done), True),
        ("UG checked, a stamp in strptime's other shapes",
         lambda lib: song(lib, **accepted, ug_checked_at="2026-11-3t9:31:0z"), lookup(done), True),
        ("UG checked, a stamp in other digits",
         lambda lib: song(lib, **accepted, ug_checked_at="٢٠٢٦-11-03T09:31:00Z"), lookup(done),
         True),
        ("UG checked, a stamp strptime refuses",
         lambda lib: song(lib, **accepted, ug_checked_at="2026-11-03 09:31:00"), lookup(done), True),
        ("UG checked, never", lambda lib: song(lib, **accepted), lookup(done), True),
        ("UG checked, a fetch not looking it up", lambda lib: song(lib, **accepted, ug_checked_at=after),
         lookup(in_state(plain, "done")), True),
        ("pinned, checked before", lambda lib: song(lib, match_decision="pinned", ug_checked_at=before), lookup(done),
         True),
        ("unmatched, its artist page read after it started", with_kv(**{"ug:artist_page_checked:{id}": after}),
         lookup(missed), True),
        ("unmatched, its artist page read before", with_kv(**{"ug:artist_page_checked:{id}": before}),
         lookup(missed), True),
        ("unmatched, its artist page's stamp unreadable", with_kv(**{"ug:artist_page_checked:{id}": "soon"}),
         lookup(missed), True),
        ("no match yet, its artist page read after", lambda lib: (
            sid := song(lib), lib.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)",
                                               (f"ug:artist_page_checked:{sid}", after)))[0], lookup(done), True),
        # Not in the offline index: can UG be asked at all (jobs_routes._nothing_to_ask, ug.fetch.artist_is_known)?
        ("not in the index, its artist unknown", lambda lib: song(lib, **not_found), lookup(missed), True),
        ("not in the index, of commands, no stage", lambda lib: song(lib, **not_found),
         lookup(in_state(queued_job(f"Fetch {V_DISPLAY}", V_KEY, _jobs.add_steps(*V_SONG) +
                                    _jobs.fetch_steps(V_DISPLAY), fetching=True, display=V_DISPLAY), "done")), True),
        ("not in the index, its artist in it", artist("index"), lookup(missed), True),
        ("not in the index, its artist's page learned", artist("learned"), lookup(missed), True),
        ("not in the index, its artist by an alias", artist("alias"), lookup(missed), True),
        ("not in the index, its artist's page pasted", artist("page"), lookup(missed), True),
        ("not in the index, its artist's page pasted under a form", artist("page by a form"), lookup(missed), True),
        ("not in the index, a tab page pasted, not read", artist("tab not read"), lookup(missed), True),
        ("not in the index, a tab page pasted, read", artist("tab read"), lookup(missed), True),
        ("not in the index, a tab page pasted that leads nowhere", artist("tab problem"), lookup(missed), True),
        ("not in the index, a tab page pasted, an empty problem", artist("tab empty problem"), lookup(missed), True),
        # Review, ignored, a LaCuerda pick.
        ("in review, its candidates", lambda lib: song(lib, review=True, match_candidates=candidates),
         lookup(done), True),
        ("in review, no candidate", lambda lib: song(lib, review=True, match_candidates=[]), lookup(done), True),
        ("in review, a candidate naming no song", lambda lib: song(lib, review=True, match_candidates=[
            {"artist_key": "radiohead", "song_key": ""}, {"score": 3}]), lookup(done), True),
        ("in review and ignored", lambda lib: song(lib, review=True, match_candidates=candidates,
                                                   entries={"ignore": True}), lookup(done), True),
        ("ignored in overrides.toml", lambda lib: song(lib, entries={"ignore": True}), lookup(done), True),
        ("ignored by its status", lambda lib: song(lib, status="ignored"), lookup(done), True),
        ("a LaCuerda sheet picked, not asked yet", lambda lib: song(lib, entries={"lacuerda": lacuerda_page}),
         lookup(in_state(plain, "done")), True),
        ("a LaCuerda sheet picked, asked", lambda lib: song(lib, entries={"lacuerda": lacuerda_page},
                                                            lacuerda_checked_at=before),
         lookup(in_state(plain, "done")), True),
        # What the local indexes have elsewhere (outcome.elsewhere).
        ("LaCuerda's index has it", lacuerda_row(), lookup(done), True),
        ("LaCuerda's index has it, asked this month", lacuerda_row(lacuerda_checked_at="2026-10-20T00:00:00Z"),
         lookup(done), True),
        ("LaCuerda's index has it, asked last month", lacuerda_row(lacuerda_checked_at="2026-10-01T00:00:00Z"),
         lookup(done), True),
        ("LaCuerda's index has it, the song in review", lacuerda_row(review=True), lookup(done), True),
        ("LaCuerda's index has it, a lookup running", lacuerda_row(), lookup(running), True),
        ("LaCuerda's index has a page with no chords", lambda lib: (
            song(lib, **accepted, ug_checked_at=after),
            _insert(lib, "lacuerda_index", LACUERDA_ROW | {"acordes": 0}))[0], lookup(done), True),
        ("LaCuerda's index has its third version", lambda lib: (
            song(lib, **accepted, ug_checked_at=after),
            _insert(lib, "lacuerda_index", LACUERDA_ROW | {"acordes": 3}))[0], lookup(done), True),
        ("gtptabs.com's index lists it", gtptabs_row(), lookup(done), True),
        ("gtptabs.com's index lists it by its base key", gtptabs_row(title_key="creep-live"), lookup(done), True),
        ("gtptabs.com's index lists it under another artist", gtptabs_row(artist_key="radiohead-the"),
         lookup(done), True),
        ("gtptabs.com's index lists it, asked this month", gtptabs_row(kv="2026-10-20T00:00:00Z"), lookup(done),
         True),
        ("gtptabs.com's index lists it, asked last month", gtptabs_row(kv="2026-10-01T00:00:00Z"), lookup(done),
         True),
        ("gtptabs.com's index lists it, a Guitar Pro file kept", gtptabs_row(guitar=True), lookup(done), True),
        ("gtptabs.com's index lists it, turned off", gtptabs_row(), lookup(done), False),
        ("both: LaCuerda first", both(), lookup(done), True),
        ("both, LaCuerda cooling down", both(cooling={"lacuerda": "2026-11-04T11:30:00Z"}), lookup(done), True),
        ("both, LaCuerda's cooldown over", both(cooling={"lacuerda": "2026-11-03T09:00:00Z"}), lookup(done), True),
        ("both, each cooling down", both(cooling={"lacuerda": "2026-11-04T11:30:00Z",
                                                  "gtptabs": "2026-11-04T11:30:00Z"}), lookup(done), True),
        ("both, LaCuerda's cooldown unreadable", both(cooling={"lacuerda": "tomorrow"}), lookup(done), True),
        ("both, its LaCuerda stage done", both(), stage("lacuerda", "done", "kept LaCuerda's"), True),
        ("both, its LaCuerda stage asked already", both(), stage("lacuerda", "skipped", "asked already this month"),
         True),
        ("both, its LaCuerda stage blocked", both(), stage("lacuerda", "skipped", LACUERDA_BLOCKED), True),
        ("both, its LaCuerda stage's budget spent", both(), stage("lacuerda", "skipped", UG_SPENT), True),
        ("both, its LaCuerda stage skipped otherwise", both(), stage("lacuerda", "skipped", "not Spanish"), True),
        ("both, its gtptabs.com stage done, LaCuerda asked lately", both(lacuerda_checked_at="2026-10-20T00:00:00Z"),
         stage("gtptabs", "done", "no file there"), True),
        ("both, the song ignored", both(status="ignored"), lookup(done), True),
        # A removal, Make this my version, a harmonica tab's reading: by the job's song id.
        ("a removal done, the song gone", gone, removal("done"), True),
        ("a removal failed, the song there", lambda lib: song(lib), removal("failed"), True),
        ("make it mine, by its id", lambda lib: song(lib, sheet=True), by_id(mine), True),
        ("make it mine, its song gone", gone, by_id(mine), True),
        ("a harmonica reading, by its id", lambda lib: song(lib, sheet=True), by_id(reading), True),
    ]


def _song(lib, song_id: int):
    from caracole.songs import get_song

    return get_song(lib.conn, song_id)


def song_of_records(root, monkeypatch) -> list[dict]:
    from caracole.library_page import sheet_href
    from caracole.songs import list_songs
    from helpers.corpus import dump_fixture
    from helpers.peer_libraries import NOW, Library
    from test_conformance_sync import phone_rows

    monkeypatch.setattr(_jobs_routes, "datetime", _SongOfClock)
    records = []
    for n, (note, build, make, gtptabs) in enumerate(song_of_cases()):
        lib = Library(root / f"case-{n}", sync_id="0123456789abcdef")
        try:
            song_id = build(lib)
            job = make(song_id)
            cfg = lib.cfg
            if not gtptabs:
                import dataclasses

                cfg = dataclasses.replace(cfg, providers={**cfg.providers, "gtptabs": dataclasses.replace(
                    cfg.providers["gtptabs"], enabled=False)})
            lib.conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (NOW, NOW))  # the same every run
            lib.conn.execute("UPDATE files SET created_at = ?", (NOW,))
            fixture = dump_fixture(lib.conn)
            fixture += [{"table": table, "row": row} for table, row in phone_rows(lib)]
            if not gtptabs:
                fixture.append({"kv": "phone:settings", "value": json.dumps({"providers": {"gtptabs": {
                    "enabled": False}}})})
            sheets = [[s.id, sheet_href(lib.cfg.library_dir, s)] for s in list_songs(lib.conn)]
            app = type("App", (), {"cfg": cfg, "_ended": {}, "_ended_lock": __import__("threading").Lock()})()
            record = {"fn": "caracole.web.jobs_routes.song_of", "note": note, "fixture": fixture,
                      "sheets": sorted(sheets), "now": _stamp(SONG_OF_NOW), "job": phone_job(job, None, 0),
                      "args": [], "kw": {}}
            try:
                found, facts = _jobs_routes.song_of(app, lib.conn, lib.overrides(), job)
                record["out"] = [found, facts_json(facts)]
            except ValueError as e:
                record["err"] = type(e).__name__
            records.append(record)
        finally:
            lib.close()
    return records


def test_job_views_song_of_jsonl_is_what_jobs_routes_song_of_knows_of_each_jobs_song(tmp_path, monkeypatch):
    records = song_of_records(tmp_path, monkeypatch)
    facts = [r["out"][1] for r in records if "out" in r and r["out"][1]]
    for name in ("review", "not_found", "checked_now", "ignored", "lacuerda", "asked_ug"):  # each fact, both ways
        assert {f[name] for f in facts} == {True, False}, name
    assert {f["elsewhere"][0] for f in facts if f["elsewhere"]} == {"lacuerda", "gtptabs"}
    assert {f["sheet_from"] for f in facts} == {"", "UG", "LaCuerda", "auto"}
    assert any(f["picker"] for f in facts) and any(r.get("err") for r in records)
    check(WEB / "job_views_song_of.jsonl", jsonl(records, corpus="web/job_views", made_by=MADE_BY))
