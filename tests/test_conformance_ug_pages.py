"""UG's tab and artist pages, the sitemap index's reads and the artist pages' tabs kept, for the phone: what
``ug/page.py``, ``ug/artist.py``, ``ug/lookup.py`` and ``ug/artist_tabs.py``'s writers answer, written for the Kotlin
port's core.ug (UgPage, UgArtist, UgLookup, ArtistTabs) to agree with (docs/superpowers/plans/
2026-11-03-android-port-m4-m6.md, lane ug-pages).

Vectors, tests/conformance/vectors/sites/ (a body is ``{"fixture": …}``, a file of tests/fixtures/, ``{"text": …}``
or ``{"base64": …}``, the bytes the parser is handed; a float is the text ``repr`` writes, ``"4.54038"``):

- ``ug_pages.jsonl``:
  - ``parse_tab_page`` records over each UG fixture, each page helpers/ug_pages.py builds as test_page.py does, and
    an edge set (every field's odd values, the js-store found or not, entities, a page cut short, lone surrogates):
    ``args`` the body, ``kw.url``, ``out`` the page (``tab`` and ``versions`` each a version, ``content``, ``meta``
    and ``raw`` as ``json.dumps(…, ensure_ascii=False, indent=2)`` writes them, as a kept sheet.json holds them,
    ``artist_url``), or ``err`` its ``PageParseError``'s words; ``recursion`` where they end in Python's
    RecursionError's, whose words (the stack it used) are left out: the phone's are its own (PyJson.MAX_DEPTH).
    A ``raw`` past ``RAW_WHOLE`` bytes is ``{"sha256", "size"}`` of that text. A body ``{"before", "repeat",
    "times", "after"}`` is ``repeat`` that many times between the two.
  - A version: its fields, ``rating`` as its repr, its ``kind`` and ``label``, ``raw_sha256`` the SHA-256 of
    ``json.dumps(raw, ensure_ascii=False, indent=2)``.
  - ``parse_version`` records batch tab dicts, each the JSON text json.loads reads (``out`` a version or null);
    ``_number`` and ``json_int`` batch JSON texts of one value each (``out`` a repr, an int, or null).
  - ``kind_of``, ``page_url`` (``[tab_id, path]`` pairs), ``strip_markup`` and ``decode_twice`` batch their inputs.
- ``ug_artist.jsonl``: ``parse_artist_page`` records as the tab pages' (``out`` its ``artist_id``, ``name``, ``tabs``,
  ``page``, ``pages`` and ``filters`` sorted), a ValueError of urllib's as ``err`` ``"ValueError: …"``; and
  ``artist_page_url`` batches of ``[base, kind, page]``, each a URL or ``{"err": "ValueError: …"}``.
- ``ug_artist_tabs.jsonl``:
  - ``caracole.ug.artist_tabs.ops``: a database (``fixture``, dump_fixture's) and ``ops`` run in turn on it:
    ``store`` (``tabs`` UG's tab dicts, each made a version by ``parse_version``, those it refuses left out),
    ``store_page`` (``body`` an artist page parsed, its tabs of ``kind``, all of them for null, stored under its
    name), ``keep_only`` and ``forget``; ``out`` after each op its result, ``ug_artist_tabs``' rows (dump_fixture's;
    null where the op changed none) and the kv it changed.
  - ``caracole.ug.artist_tabs.backfill``: scenario records (tests/helpers/scenario.py) of a backfill from a cache
    of artist pages, ``kw.artist_url`` the ``[artist_url]`` entries; no client, so no request.
- ``ug_pages_lookup.jsonl``: ``caracole.ug.lookup``, a database of index rows and ``calls`` in turn: ``song_tabs``,
  ``artist_known``, ``index_tab``, ``tab_url_for``, ``artist_tabs``, and ``learned_artist_url`` between
  ``remember_artist_url`` and ``forget_artist_url``; an IndexTab as its fields and ``url``.

The phone notes each page a store keeps tabs of for the next push to the computer (core.index.Reads, kv
``phone:read:ug:<page>``), which Python doesn't: the replay checks the notes and leaves them out of the kv compared.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from conftest import migrated_database
from helpers.corpus import VECTORS, check, dump_fixture, fixture_bytes, fixture_ref, jsonl
from helpers.scenario import record as scenario
from helpers.ug_pages import (
    BANMA_UG,
    SONG_DONGYE,
    SONG_DONGYE_URL,
    make_artist_page_html,
    make_tab_page_html,
    song_dongye_chords,
    song_dongye_page_html,
    song_dongye_tab,
    store_page_html,
    version_dict,
)

from caracole import db
from caracole.http import CachedAnswers
from caracole.overrides import Overrides
from caracole.ug import artist_tabs, lookup
from caracole.ug.artist import artist_page_url, parse_artist_page
from caracole.ug.index import upsert_rows
from caracole.ug.page import (
    PageParseError,
    UGTabPage,
    UGVersion,
    _number,
    decode_twice,
    json_int,
    kind_of,
    page_url,
    parse_tab_page,
    parse_version,
    strip_markup,
)
from caracole.ug.sitemap import classify_tab_url

OUT = VECTORS / "sites"
MADE_BY = "tests/test_conformance_ug_pages.py"
TAB = "https://tabs.ultimate-guitar.com/tab/"
SODA = "https://www.ultimate-guitar.com/artist/soda_stereo_2946"
CHORDS_URL = f"{TAB}85053"
EARLY, LATE = "2026-10-18T00:00:00Z", "2026-10-19T03:30:00Z"


# --- what a record holds -----------------------------------------------------------------------------------


def _indented(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def version(v: UGVersion) -> dict[str, Any]:
    return {"tab_id": v.tab_id, "song_id": v.song_id, "song_name": v.song_name, "artist_name": v.artist_name,
            "type": v.type, "part": v.part, "version": v.version, "rating": repr(v.rating), "votes": v.votes,
            "access": v.access, "url": v.url, "description": v.description, "is_acoustic": v.is_acoustic,
            "kind": v.kind, "label": v.label,
            "raw_sha256": hashlib.sha256(_indented(v.raw).encode("utf-8")).hexdigest()}


RAW_WHOLE = 2000  # a page's raw text is in its record up to this many bytes, else its digest and size


def _text_or_digest(text: str) -> str | dict[str, Any]:
    data = text.encode("utf-8")
    return text if len(data) <= RAW_WHOLE else {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def tab_page(p: UGTabPage) -> dict[str, Any]:
    return {"tab": version(p.tab), "versions": [version(v) for v in p.versions], "content": p.content,
            "meta": _indented(p.meta), "raw": _text_or_digest(_indented(p.raw)), "artist_url": p.artist_url}


def body(html: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(html, dict):
        return html
    if isinstance(html, bytes):
        return {"base64": base64.b64encode(html).decode("ascii")}
    return {"text": html}


def _bytes(b: dict[str, Any]) -> bytes:
    if "repeat" in b:  # a long page of one text repeated, ``before`` and ``after`` it
        return (b["before"] + b["repeat"] * b["times"] + b["after"]).encode("utf-8")
    if "fixture" in b:
        return fixture_bytes(b)
    if "base64" in b:
        return base64.b64decode(b["base64"])
    return b["text"].encode("utf-8")


def parsed(fn: str, parse, out, case: str, html: str | bytes | dict[str, str], url: str | None) -> dict[str, Any]:
    """A parser's record: what it made of the page, or its error's words."""
    given = body(html)
    record: dict[str, Any] = {"fn": fn, "case": case, "args": [given], "kw": {"url": url}}
    try:
        record["out"] = out(parse(_bytes(given), url=url))
    except PageParseError as e:
        record["err"] = f"PageParseError: {e}"
        if isinstance(e.__cause__, RecursionError):  # its words name the stack Python used: the words before them
            record["err"] = record["err"].removesuffix(str(e.__cause__))
            record["recursion"] = True
    except ValueError as e:  # urllib's, from a filter link: no PageParseError
        record["err"] = f"ValueError: {e}"
    return record


# --- tab pages -----------------------------------------------------------------------------------------------


def _page(tab: dict[str, Any], **view: Any) -> str:
    """A tab page whose tab_view is ``view`` exactly (versions, wiki_tab, meta as given)."""
    return store_page_html({"tab": tab, "tab_view": view})


def _lone(html: str) -> str:
    """The page with each LONE a lone low surrogate's escape, HIGH a lone high one's and PAIR a whole pair's."""
    return html.replace("LONE", "\\udc00").replace("HIGH", "\\ud83d").replace("PAIR", "\\ud83d\\ude00")


def _js_store(payload: str, *, doctype: str = "<!doctype html>", attrs: str = "class=\"js-store\"") -> str:
    return f'{doctype}<html><body><div {attrs} data-content="{payload}"></div></body></html>'


def _q(text: str) -> str:
    """JSON text as an attribute holds it: its quotes as &quot;, its ampersands as &amp;."""
    return text.replace("&", "&amp;").replace('"', "&quot;")


def _odd(tab_id: int, **fields: Any) -> dict[str, Any]:
    """A chords tab of UG's, its id ``tab_id`` and ``fields`` in place of its own."""
    return {"id": tab_id, "type": "Chords", **fields}


# Each field's odd values: what parse_version makes of a number, a text, a boolean, a list or an object in it.
ODD = [
    _odd(20, id="21"), _odd(22, id=23.0), _odd(24, id="2.5e1"), _odd(26, id=" 27 "), _odd(28, id="2_9"),
    _odd(30, id="٣١"), _odd(32, id=True), _odd(33, id=33.5), _odd(34, id=None), _odd(35, id=[35]),
    _odd(36, id="nan"), _odd(37, id="inf"),
    _odd(40, rating="4.5"), _odd(41, rating=" 4.5\n"), _odd(42, rating="nan"), _odd(43, rating="inf"),
    _odd(44, rating=-0.0), _odd(45, rating=True), _odd(46, rating=[1]), _odd(47, rating={"a": 1}),
    _odd(48, rating="1e400"), _odd(49, rating="1_0.5"),
    _odd(50, votes="7"), _odd(51, votes=7.0), _odd(52, votes=7.5), _odd(53, votes="7.0"), _odd(54, votes=-3),
    _odd(55, votes=False),
    _odd(60, version=0), _odd(61, version=None), _odd(62, version="2"), _odd(63, version=2.0), _odd(64, version="x"),
    _odd(70, song_id=None), _odd(71, song_id="12"), _odd(72, song_id=12.5),
    _odd(80, recording=None), _odd(81, recording={"is_acoustic": "1"}), _odd(82, recording={"is_acoustic": 0.5}),
    _odd(83, recording={"is_acoustic": "nan"}), _odd(84, recording={"is_acoustic": "0"}),
    _odd(85, recording={"is_acoustic": True}), _odd(86, recording=[1]), _odd(87, recording={}),
    _odd(90, type=" chords "), _odd(91, type="CHORDS"), _odd(92, type="Ukulele  Chords"),
    _odd(93, type="ukulele chords\xa0"), _odd(94, type="ＣＨＯＲＤＳ"), _odd(95, type=5), _odd(96, type=True),
    _odd(97, type=[1]), _odd(98, type={"a": "b"}), _odd(99, type=0), _odd(100, type=""), _odd(101, type=[]),
    _odd(102, type=False), _odd(103, type=None), _odd(104, type=0.0), _odd(105, type="Tabs\t"),
    _odd(110, song_name=None), _odd(111, song_name=12), _odd(112, song_name=1.5), _odd(113, song_name=1e16),
    _odd(114, song_name=True), _odd(115, song_name=["a", 1, None, 2.5, {"k": "v"}, "it's", "\u200b"]),
    _odd(116, song_name=12345678901234567890), _odd(117, song_name={"x": [True, False]}),
    _odd(118, song_name=0.1 + 0.2), _odd(119, song_name=-0.0),
    _odd(120, artist_name=None, tab_url=""), _odd(121, tab_url=0), _odd(122, tab_url=None),
    _odd(123, version_description=""), _odd(124, version_description=0), _odd(125, tab_access_type=None),
    _odd(126, part=None), _odd(127, part=7), _odd(130, part="ÉCLAT"), _odd(131, part="İntro"),
    _odd(132, part="ΣOLO Σ"), _odd(133, part=" ", recording={"is_acoustic": 1}), _odd(134, part="\x1cSolo\x85"),
    _odd(135, tab_url="https://tabs.ultimate-guitar.com/tab/a/b-chords-135", version_description="Capo 2"),
]


def tab_page_cases() -> list[tuple[str, str | bytes | dict[str, str], str | None]]:
    v = version_dict
    cases: list[tuple[str, str | bytes | dict[str, str], str | None]] = [
        ("the chords fixture", fixture_ref("ug/tab_chords.html"), CHORDS_URL),
        ("the Guitar Pro fixture", fixture_ref("ug/tab_pro.html"), None),
        ("the ukulele chords fixture", fixture_ref("ug/tab_ukulele.html"), None),
        ("an artist page read as a tab page", fixture_ref("ug/artist.html"), SODA),
        ("a sitemap: no js-store", fixture_ref("ug/sitemap_tabs.xml"), None),
        ("a missing page", "<html><body><h1>Oops! We couldn't find that page.</h1></body></html>", CHORDS_URL),
        ("invalid JSON", '<div class="js-store" data-content="{&quot;store&quot;:"></div>', None),
        ("nested too deep", {"before": '<div class="js-store" data-content="', "repeat": "[", "times": 100_000,
                             "after": '"></div>'}, None),
    ]
    for payload in ["[]", "{&quot;store&quot;:[]}", "{&quot;store&quot;:{&quot;page&quot;:{}}}"]:
        cases.append((f"no store.page.data: {payload}", f'<div class="js-store" data-content="{payload}"></div>',
                      None))
    cases += [
        ("no data.tab", store_page_html({"tab_view": {"versions": [], "wiki_tab": {"content": "x"}, "meta": []}}),
         None),
        ("no tab_view", store_page_html({"tab": v(1, type="Pro")}), None),
        ("no versions key", store_page_html({"tab": v(1), "tab_view": {"wiki_tab": {"content": "x"}}}), None),
        ("null versions", store_page_html({"tab": v(1), "tab_view": {"versions": None, "wiki_tab": {"content": "x"}}}),
         None),
        ("a sheet without content", make_tab_page_html(v(1, type="Tabs"), []), None),
        ("null rating and votes", make_tab_page_html(v(1, rating=None, votes=None), [v(2, rating=None, votes=None)],
                                                     content="x"), None),
        ("n/a rating and votes", make_tab_page_html(v(1, rating="n/a", votes="n/a"), [v(2, rating="n/a", votes="n/a")],
                                                    content="x"), None),
        ("a whole number rating", make_tab_page_html(v(1, rating=5), [], content="x"), None),
        ("versions without a type or an id", make_tab_page_html(
            v(1), [{"id": 2, "song_name": "No type"}, v(3, id="three"), v(4)], content="x"), None),
        ("apostrophes and ampersands", make_tab_page_html(v(1, song="Don't Stop", artist="Simon & Garfunkel"), [],
                                                          content="x"), None),
        ("Chinese names", make_tab_page_html(v(7, song="斑马斑马", artist="宋冬野"), [], content="[ch]C[/ch] 斑马"),
         None),
        ("UTF-8 bytes", make_tab_page_html(v(7, song="斑马斑马", artist="宋冬野"), [], content="x").encode("utf-8"),
         None),
        ("a helper Guitar Pro page", make_tab_page_html(
            v(10, type="Pro", version=2, rating=4.2, votes=9, part="intro", song="S", artist="A", song_id=5),
            [v(11, type="Pro")], meta={"fileExtension": ".gpx"}, artist_url="https://u/a_1"), None),
        ("entities in the sheet", make_tab_page_html(v(1), [], content="Tom &amp; Jerry&#039;s [ch]G[/ch] &lt;3"),
         None),
        ("an entity escaped twice", make_tab_page_html(
            v(1), [], content="watch?v=x&amp;amp;feature=related [ch]G[/ch]"), None),
        ("meta not an object", _page(v(1, type="Pro"), versions=[], wiki_tab={}, meta=["unexpected"]), None),
        ("meta an object", make_tab_page_html(v(1), [], content="x", meta={"capo": 2, "tonality": "Am"}), None),
        ("a Pro page with content", _page(v(1, type="Pro"), versions=[], wiki_tab={"content": "a &amp; b"}, meta=[]),
         None),
        ("content a number on a chords page", _page(v(1), versions=[], wiki_tab={"content": 5}, meta=[]), None),
        ("content a number on a Pro page", _page(v(1, type="Pro"), versions=[], wiki_tab={"content": 5}, meta={}),
         None),
        ("wiki_tab a list", _page(v(1, type="Video"), versions=[], wiki_tab=["x"], meta=[]), None),
        ("tab_view a list", store_page_html({"tab": v(1), "tab_view": []}), None),
        ("versions an object", _page(v(1), versions={"a": 1}, wiki_tab={"content": "x"}), None),
        ("versions a string", _page(v(1), versions="x", wiki_tab={"content": "x"}), None),
        ("artist_url a number", make_tab_page_html(v(1, artist_url=5), [], content="x"), None),
        ("artist_url empty", make_tab_page_html(v(1, artist_url=""), [], content="x"), None),
        ("a slugged tab_url", make_tab_page_html(v(1, tab_url=f"{TAB}a/b-chords-1"), [], content="x"), None),
        ("a part and a description", make_tab_page_html(
            v(1, part="  Solo　", version_description="Capo 2", is_acoustic=True), [], content="x"), None),
        ("acoustic without a part", make_tab_page_html(v(1, is_acoustic=True), [], content="x"), None),
        ("ukulele chords", make_tab_page_html(v(1, type="Ukulele Chords"), [], content="[ch]C[/ch]"), None),
    ]
    # A few of the odd values (parse_version's records have them all), in the page's own tab and its versions.
    some = [odd for n, odd in enumerate(ODD) if n % 9 == 0]
    cases.append(("odd values in the versions", make_tab_page_html(v(1), some, content="x"), None))
    cases += [(f"an odd tab #{n}", make_tab_page_html(d, [], content="x"), None)
              for n, d in enumerate(ODD) if n % 11 == 3]
    # Lone surrogates: in the content, the names, a key, a versions' entry; a whole pair stays its character.
    cases += [
        ("a lone low surrogate", _lone(make_tab_page_html(v(1, song="Zebra LONE"), [v(2, song="LONE")],
                                                          content="[ch]C[/ch] la LONE la PAIR",
                                                          meta={"LONE": "x", "y": "HIGH"})), None),
        ("lone surrogates in a row", _lone(make_tab_page_html(v(1, song="HIGHHIGHLONE LONEHIGH"), [],
                                                              content="HIGHPAIR LONELONE")), None),
        ("a lone surrogate's escape in capitals", make_tab_page_html(v(1, song="Q"), [], content="R")
         .replace("Q", "\\uD83D").replace("R", "\\uDE00x\\uDBFF"), None),
        ("an escaped backslash before u", make_tab_page_html(v(1, song="a\\ud800"), [], content="x"), None),
        ("a pair alone", _lone(make_tab_page_html(v(1, song="PAIR"), [], content="PAIR")), None),
    ]
    # Where the js-store is found, and how its attribute is read.
    store = '{"store":{"page":{"data":{"tab":{"id":1,"type":"Pro"},"tab_view":{"versions":[],"meta":{}}}}}}'
    cases += [
        ("a quirks page's class in capitals", _js_store(_q(store), doctype="", attrs='class="JS-STORE"'), None),
        ("a no-quirks page's class in capitals", _js_store(_q(store), attrs='class="JS-STORE"'), None),
        ("another class beside it", _js_store(_q(store), attrs='class="x js-store y"'), None),
        ("a span, no div", _js_store(_q(store)).replace("<div", "<span").replace("</div>", "</span>"), None),
        ("the first of two js-stores", _js_store(_q(store)) + _js_store("[]"), None),
        ("the first js-store has no data", '<div class="js-store"></div>' + _js_store(_q(store)), None),
        ("an empty data-content", '<div class="js-store" data-content=""></div>', None),
        ("data-content twice", f'<div class="js-store" data-content="[]" data-content="{_q(store)}"></div>', None),
        ("single quotes", f"<div class='js-store' data-content='{store}'></div>", None),
        ("unquoted", "<div class=js-store data-content=" + store.replace('"', "&quot;") + "></div>", None),
        ("named references without their semicolon", _js_store(_q(store).replace(
            "&quot;Pro&quot;", "&quot;P&ampro &amp=x &ampx &notit; &copy2&quot;")), None),
        ("numeric references", _js_store(_q(store).replace(
            "&quot;Pro&quot;", "&quot;&#x50;&#114;&#x6F;&#0; &#x80;&#xD800;&#1114112;&quot;")), None),
        ("a NUL and a CR", _js_store(_q(store).replace("&quot;Pro&quot;", "&quot;P\x00r\ro\r\n&quot;")), None),
        ("the page cut short in the attribute", _js_store(_q(store))[:120], None),
        ("NaN and Infinity in the JSON", _js_store(_q(store).replace(
            "&quot;meta&quot;:{}", "&quot;meta&quot;:{&quot;a&quot;:NaN,&quot;b&quot;:-Infinity,&quot;c&quot;:1E2}")),
         None),
        ("duplicate keys", _js_store(_q(store).replace(
            "&quot;meta&quot;:{}", "&quot;meta&quot;:{&quot;a&quot;:1,&quot;b&quot;:2,&quot;a&quot;:3}")), None),
        ("a trailing comma", _js_store(_q(store).replace("{}", "{&quot;a&quot;:1,}")), None),
        ("JSON after the value", _js_store(_q(store) + " x"), None),
        ("big numbers", _js_store(_q(store).replace(
            "&quot;meta&quot;:{}", "&quot;meta&quot;:{&quot;n&quot;:123456789012345678901234567890,"
            "&quot;f&quot;:1.0000000000000002,&quot;e&quot;:1e-7,&quot;z&quot;:-0}")), None),
        ("invalid UTF-8", make_tab_page_html(v(1, song="AB"), [], content="CD").encode("utf-8")
         .replace(b"AB", b"A\xffB\xc3").replace(b"CD", b"C\xed\xa0\x80D"), None),
        ("a BOM before the page", b"\xef\xbb\xbf" + make_tab_page_html(v(1), [], content="x").encode("utf-8"), None),
    ]
    return cases


def tab_page_records() -> list[dict[str, Any]]:
    return [parsed("caracole.ug.page.parse_tab_page", parse_tab_page, tab_page, case, html, url)
            for case, html, url in tab_page_cases()]


VERSION_TEXTS = [json.dumps(d, ensure_ascii=False) for d in ODD] + [
    '{"id": 1, "type": "Chords"}',
    '{"id": "7", "type": "Tabs", "rating": "4.5", "votes": "12", "version": "3", "part": "Intro"}',
    '{"id": 1, "type": "x", "recording": {"is_acoustic": 1}}',
    '{"id": 1, "type": "x", "recording": {"is_acoustic": 2.0}, "part": ""}',
    '{"id": 1, "type": " "}',
    '{"id": 1}',
    '{"type": "Chords"}',
    '{"id": 1.5, "type": "Chords"}',
    '{"id": 1e3, "type": "Chords"}',
    '{"id": 9007199254740993, "type": "Chords"}',
    '{"id": "9007199254740993", "type": "Chords"}',
    '{"id": -4, "type": "Chords", "version": -1, "votes": -2}',
    '{"id": 1, "type": "Chords", "rating": NaN, "votes": Infinity}',
    '{"id": 1, "type": "Chords", "rating": 1e400, "version": -Infinity}',
    '{"id": 1, "type": "Chords", "rating": -1e-400, "song_id": 0}',
    '{"id": 1, "type": "Chords", "tab_url": "x", "artist_name": "\\u00e9", "song_name": "a\\u0000b"}',
    '{"id": 1, "type": "Chords", "song_name": [1.0, 1e16, 1e-5, 123456789.0, -0.0, 1e22, 0.0001]}',
    '{"id": 1, "type": "Chords", "song_name": {"\'": "\\"", "a\\nb": "\\t\\u0007\\u007f\\u0085\\u00ad\\u2028"}}',
    '{"id": 1, "type": "Chords", "song_name": ["\\ud83d\\ude00", "\\u00a0", "\\ue000", "\\u0378", "\\\\"]}',
    '{"id": 1, "type": "Chords", "song_name": [NaN, Infinity, -Infinity, 1E2, 2.50]}',
    '{"id": 1, "type": "Chords", "id": 2}',
    '[1]',
    '"x"',
    'null',
    '{"id": "\\u0661\\u0662", "type": "Chords", "votes": "\\uff17", "rating": "\\u0664.\\u0665"}',
    '{"id": "1\\u2003", "type": "Chords", "votes": "\\u20077", "rating": "\\u00854"}',
    '{"id": "0x10", "type": "Chords", "votes": "1__0", "rating": "_1"}',
    '{"id": "+5", "type": "Chords", "votes": "-0", "rating": "+inf"}',
    '{"id": "Infinity", "type": "Chords", "rating": "iNfInItY", "votes": "1e2"}',
    '{"id": 5, "type": "Chords", "rating": "1.7976931348623157e308", "votes": "1.7976931348623159e308"}',
    '{"id": 5, "type": "Chords", "rating": "4.9406564584124654e-324", "votes": "2.4703282292062327e-324"}',
]

NUMBER_TEXTS = [
    "1", "1.5", "-0.0", "0", "true", "false", "null", '"1"', '" 2.5 "', '"1_000"', '"1__0"', '"nan"', '"-inf"',
    '"infinity"', '"Infinityx"', '"1e5"', '"1E-5"', '"."', '"1."', '".5"', '"5e"', '"\\u0663.\\u0661"', '"\\u00a01"',
    '"1\\u200b"', '[]', "{}", '"0x1"', "NaN", "-Infinity", "1e308", "1e309", "123456789012345678901234567890",
    "9007199254740993", '"9007199254740993"', "4.5e15", "4503599627370497.5", '"12.0"', '"-12.000"', '"1e-400"',
    '"\\u0031\\u0662"', '"\\uff11"', '"𝟙"', '"२"', '"1 2"', '"+-1"', '"--1"', '""', '"1e3"', '" -7 "',
]


def number_records() -> list[dict[str, Any]]:
    values = [json.loads(t) for t in NUMBER_TEXTS]
    numbers = [None if (n := _number(x)) is None else repr(n) for x in values]
    return [
        {"fn": "caracole.ug.page._number", "args": [NUMBER_TEXTS], "out": numbers},
        {"fn": "caracole.ug.page.json_int", "args": [NUMBER_TEXTS], "out": [json_int(x) for x in values]},
    ]


def version_records() -> list[dict[str, Any]]:
    out = []
    for text in VERSION_TEXTS:
        v = parse_version(json.loads(text))
        out.append(None if v is None else version(v))
    return [{"fn": "caracole.ug.page.parse_version", "args": [VERSION_TEXTS], "out": out}]


KIND_INPUTS = [None, "Chords", "chords", " chords ", "CHORDS", "Tabs", "tabs\n", "Ukulele Chords", "ukulele chords",
               "Ukulele  Chords", "Ukulele Chords\xa0", "　Tabs　", "Pro", "Power", "Official", "Bass Tabs",
               "Drum Tabs", "Video", "Lyrics", "", " ", "ＣＨＯＲＤＳ", "tab", "chord", "CHORDſ", "TABS​",
               "\x1cchords\x1f", "\x85tabs "]
PAGE_URLS = [(85053, None), (85053, ""), (1081462, "soda-stereo/persiana-americana-tabs-1081462"),
             (1, "/a/b-chords-1"), (1, "//a/b"), (1, "/"), (1, "a b/ç-1"), (-5, None), (0, None),
             (9007199254740993, None)]
MARKUPS = ["[Verse 1]\r\n[tab][ch]G[/ch]   [ch]D/F#[/ch]\r\nla la la[/tab]\r\n[ch]Em[/ch]", "", "[CH]G[/CH] [ch ]",
           "[[ch]]G[[/ch]] [/tab][tab]", "[ch][/ch][tab][/tab]", "[/ch][//ch][ch/]", "x[chord]y[tabs]z"]
DECODES = ["", "plain", "Tom &amp; Jerry&#039;s &lt;3", "&amp;amp;feature", "&amp;amp;amp;", "&#38;lt;", "&#x26;gt;",
           "&ampx", "&amp;ampx &#١٢;", "&amp;ampx &K;", "&amp;ampx &ſ;", "&amp;ampx &İ;", "&amp;ampx &ı;",
           "&amp;ampx &#X1f;", "&amp;notit;", "&notit;", "&amp;notin;", "&amp", "&#0;", "&#xd800;", "&amp;#xd800;",
           "&#128512;&amp;#128512;", "&AMP;amp;", "&amp;AMP;", "&#;", "&#x;", "&amp;#;", "&amp;#x41", "&amp;#65",
           "&amp;nbsp", "&amp;nbsp;", "&amp;lt;b&amp;gt;", "&&amp;;", "&;", "&amp;eacute&amp;eacute;",
           "&amp;copy2", "&amp;Ascr;", "&amp;fjlig;", "&amp;#x110000;", "&amp;#9999999999;"]


def small_records() -> list[dict[str, Any]]:
    return [
        {"fn": "caracole.ug.page.kind_of", "args": [KIND_INPUTS], "out": [kind_of(x) for x in KIND_INPUTS]},
        {"fn": "caracole.ug.page.page_url", "args": [[list(p) for p in PAGE_URLS]],
         "out": [page_url(t, p) for t, p in PAGE_URLS]},
        {"fn": "caracole.ug.page.strip_markup", "args": [MARKUPS], "out": [strip_markup(x) for x in MARKUPS]},
        {"fn": "caracole.ug.page.decode_twice", "args": [DECODES], "out": [decode_twice(x) for x in DECODES]},
    ]


def test_ug_pages_jsonl():
    records = [*tab_page_records(), *version_records(), *number_records(), *small_records()]
    check(OUT / "ug_pages.jsonl", jsonl(records, corpus="sites/ug_pages", made_by=MADE_BY))


def test_the_tab_pages_cover_each_outcome():
    records = tab_page_records()
    errors = [r for r in records if "err" in r]
    assert len(errors) >= 20 and any(r.get("recursion") for r in errors)
    assert len(records) - len(errors) >= 45
    lone = [r for r in records if r["case"] == "a lone low surrogate"][0]["out"]
    assert lone["content"] == "[ch]C[/ch] la � la \U0001f600" and "�" in lone["meta"]


# --- artist pages ----------------------------------------------------------------------------------------------


def artist_page(p) -> dict[str, Any]:
    return {"artist_id": p.artist_id, "name": p.name, "tabs": [version(t) for t in p.tabs], "page": p.page,
            "pages": p.pages, "filters": sorted(p.filters)}


def _artist(data: dict[str, Any]) -> str:
    return store_page_html(data)


def artist_cases() -> list[tuple[str, str | bytes | dict[str, str], str | None]]:
    v = version_dict
    base = {"artist": {"id": 2946, "name": "Soda Stereo"}, "other_tabs": []}

    def with_(**more: Any) -> str:
        return _artist({**base, **more})

    def filters(*urls: Any) -> str:
        return with_(filters={"types": [{"name": "x", "url": u} if not isinstance(u, dict) else u for u in urls]})

    return [
        ("the Soda Stereo fixture", fixture_ref("ug/artist.html"), SODA),
        ("a tab page read as an artist page", fixture_ref("ug/tab_chords.html"), CHORDS_URL),
        ("a missing page", "<html><title>Oops! We couldn't find that page.</title></html>", SODA),
        ("no artist", _artist({"other_tabs": []}), None),
        ("an artist without an id", _artist({"artist": {"name": "No id"}, "other_tabs": []}), None),
        ("no other_tabs", _artist({"artist": {"id": 3, "name": "X", "name_stripped": "x"}}), None),
        ("other_tabs null", with_(other_tabs=None), None),
        ("other_tabs an object", with_(other_tabs={"a": 1}), None),
        ("absolute filter links", filters(SODA + "?filter=chords", "/artist/soda_stereo_2946?filter=tabs&page=2",
                                          SODA + "?filter=bass", SODA), None),
        ("bare number links, no stripped name", make_artist_page_html(
            634073, "Song Dongye (宋冬野)", [v(4180894, song="斑马 斑马 Banma Banma Zebra Zebra",
                                              artist="Song Dongye (宋冬野)")], path="/artist/634073", stripped=""),
         "https://www.ultimate-guitar.com/artist/634073?filter=chords"),
        ("one page, no pagination", _artist({"artist": {"id": 3, "name": "X", "name_stripped": "x"},
                                             "other_tabs": [v(1)]}), None),
        ("a helper page", make_artist_page_html(5, "宋冬野", [
            v(1, song="斑马斑马", artist="宋冬野"),
            {"id": 9, "song_name": "斑马斑马", "marketing_type": "TabPro", "rating": 4.8, "votes": 21},
            v(2, type="Pro", part="intro", song="安和桥", artist="宋冬野")], page=2, pages=3), None),
        ("宋冬野's chords", song_dongye_page_html(song_dongye_chords(t4180894=(4.8, 120))), SONG_DONGYE_URL),
        ("odd filter links", filters("?filter=%63hords", "?filter=tabs&filter=chords", "?filter=+chords",
                                     "?fil%74er=tabs", "?x=1;filter=chords", "\t?filter=tabs", "?filter=",
                                     "?filter", "?filter=Chords", "#?filter=chords", "?a=b#filter=tabs",
                                     {"name": "no url"}, {"url": 5}, {"url": ""}, "?filter=chords%", "x", 7), None),
        ("a filter link urllib refuses", filters("http://[::1?filter=chords"), None),
        ("a filter link with a bad bracketed host", filters("http://[x]/?filter=tabs"), None),
        ("filters not a list", with_(filters={"types": {"url": "?filter=chords"}}), None),
        ("filters a list", with_(filters=[{"url": "?filter=chords"}]), None),
        ("the page from pagination", with_(pagination={"current": 3, "pages": [{"page": 1}, {"page": 5}]}), None),
        ("the page from current_page", with_(current_page="4", pagination={"pages": []}), None),
        ("current zero", with_(current_page=2, pagination={"current": 0}), None),
        ("pages of odd numbers", with_(pagination={"current": "2", "pages": [
            {"page": "7"}, {"page": 3.0}, {"page": 9.5}, {"page": None}, {"page": 0}, {"page": -4}, "x", 5]}), None),
        ("a negative current page", with_(pagination={"current": -3, "pages": [{"page": -1}]}), None),
        ("pages not a list", with_(pagination={"current": 2, "pages": {"page": 9}}), None),
        ("pagination a list", with_(pagination=[1, 2], current_page=6), None),
        ("names of every kind", _artist({"artist": {"id": "12", "name": 0}, "other_tabs": []}), None),
        ("a name a number", _artist({"artist": {"id": 12.0, "name": 5}, "other_tabs": []}), None),
        ("a name a list", _artist({"artist": {"id": 12, "name": ["a", "b"]}, "other_tabs": []}), None),
        ("a name true", _artist({"artist": {"id": 12, "name": True}, "other_tabs": []}), None),
        ("artist a list", _artist({"artist": [1], "other_tabs": []}), None),
        ("an odd id", _artist({"artist": {"id": "1e3", "name": "X"}, "other_tabs": []}), None),
        ("a lone surrogate", _lone(make_artist_page_html(7, "Ban LONE", [v(3, song="LONE")])), None),
        ("tabs of every type", make_artist_page_html(8, "A", [
            v(1), v(2, type="Tabs"), v(3, type="Ukulele Chords"), v(4, type="Pro"), v(5, type="Official"),
            v(6, access="pro"), v(7, tab_url="https://www.ultimate-guitar.com/pro/x"), {"id": 8}, {"type": "Chords"}]),
         None),
    ]


def artist_records() -> list[dict[str, Any]]:
    records = [parsed("caracole.ug.artist.parse_artist_page", parse_artist_page, artist_page, case, html, url)
               for case, html, url in artist_cases()]
    urls = [[SODA, None, 1], [SODA, "chords", 1], [SODA, "chords", 2], [SODA, "tabs", 1], [SODA, None, 4],
            [SODA + "/?filter=tabs&page=4", "chords", 1], [SODA, "bass", 1], [SODA, "guitar-pro", 1],
            [SODA, "power", 1], [SODA, "chords", 0], [SODA, None, -1], [SODA, "ukulele", 1], [SODA + "//", None, 2],
            [SODA + "#top", "tabs", 3], ["HTTPS://WWW.Ultimate-Guitar.com/artist/x_1", None, 1],
            ["/artist/634073", "chords", 1], ["https://www.ultimate-guitar.com/artist/634073?filter=chords", None, 1],
            ["https://www.ultimate-guitar.com", None, 2], ["https://u.example/a b/ç", "tabs", 2],
            ["http://[::1/x", None, 1], ["", None, 1], ["//host", "chords", 1], [SODA, "", 1]]
    answers = []
    for base, kind, page in urls:
        try:
            answers.append(artist_page_url(base, kind=kind, page=page))
        except ValueError as e:
            answers.append({"err": f"ValueError: {e}"})
    return records + [{"fn": "caracole.ug.artist.artist_page_url", "args": [urls], "out": answers}]


def test_ug_artist_jsonl():
    check(OUT / "ug_artist.jsonl", jsonl(artist_records(), corpus="sites/ug_artist", made_by=MADE_BY))


def test_the_artist_pages_cover_each_outcome():
    records = artist_records()
    pages = [r for r in records if r["fn"].endswith("parse_artist_page")]
    assert sum("err" in r for r in pages) >= 8 and any(r.get("err", "").startswith("ValueError") for r in pages)
    soda = pages[0]["out"]
    assert (soda["artist_id"], soda["pages"], soda["filters"]) == (2946, 6, ["chords", "tabs"])


# --- the artist pages' tabs kept ---------------------------------------------------------------------------


def fresh(directory: Path, name: str) -> sqlite3.Connection:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.sqlite"
    path.write_bytes(migrated_database())
    return db.connect(path)


def _rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [r["row"] for r in dump_fixture(conn) if r.get("table") == "ug_artist_tabs"]


def _kv(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM kv").fetchall())


def index_rows(conn: sqlite3.Connection, urls: list[str], when: str = "2026-10-01T00:00:00Z") -> None:
    rows = [classify_tab_url(u) for u in urls]
    assert all(not isinstance(r, str) for r in rows), rows
    upsert_rows(conn, rows, "1", datetime.fromisoformat(when.replace("Z", "+00:00")))


def run_ops(conn: sqlite3.Connection, case: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    """The ``ops`` record: each op run on ``conn`` in turn, and what came of each."""
    before = dump_fixture(conn)
    outs: list[dict[str, Any]] = []
    last: list[dict[str, Any]] = []
    for op in ops:
        kv_before = _kv(conn)
        if op["op"] == "store":
            tabs = [t for t in map(parse_version, op["tabs"]) if t is not None]
            result: Any = artist_tabs.store(conn, op["page"], op["name"], tabs, read_at=op["read_at"])
        elif op["op"] == "store_page":
            listed = parse_artist_page(_bytes(op["body"]), url=op["page"])
            tabs = [t for t in listed.tabs if op["kind"] is None or t.kind == op["kind"]]
            result = artist_tabs.store(conn, op["page"], listed.name, tabs, read_at=op["read_at"])
        elif op["op"] == "keep_only":
            result = artist_tabs.keep_only(conn, op["page"], op["kind"], op["ids"], read_at=op["read_at"])
        elif op["op"] == "forget":
            result = artist_tabs.forget(conn, op["page"])
        else:
            raise AssertionError(op)
        kv_after = _kv(conn)
        changed = {k: kv_after.get(k) for k in sorted(set(kv_before) | set(kv_after)) if kv_before.get(k) != kv_after.get(k)}
        rows = _rows(conn)
        outs.append({"result": result, "rows": None if outs and rows == last else rows, "kv": changed})
        last = rows
    return {"fn": "caracole.ug.artist_tabs.ops", "case": case, "fixture": before, "ops": ops, "out": outs}


def _dict(**kw: Any) -> dict[str, Any]:
    """A tab dict as UG lists it, ready for a record (its recording dropped: nothing a store reads)."""
    d = version_dict(**kw)
    d.pop("recording")
    return d


def ops_records(directory: Path) -> list[dict[str, Any]]:
    v = _dict
    records = []

    conn = fresh(directory, "banma")
    index_rows(conn, [f"{TAB}anju-panta/banma-phulyo-fullai-ful-chords-9001"])
    chords = song_dongye_chords(t4180894=(4.8, 120), t4689017=(4.6, 40), t3016223=(4.7, 90))
    records.append(run_ops(conn, "宋冬野's lists read, read again without a tab, then answering 404", [
        {"op": "store", "page": SONG_DONGYE_URL, "name": SONG_DONGYE, "tabs": chords, "read_at": EARLY},
        {"op": "store", "page": SONG_DONGYE_URL, "name": SONG_DONGYE,
         "tabs": [song_dongye_tab(5000001, "安和桥 Anhe Bridge", type="Tabs")], "read_at": EARLY},
        {"op": "keep_only", "page": SONG_DONGYE_URL, "kind": "chords",
         "ids": [t["id"] for t in chords if t["id"] != 3392735], "read_at": LATE},
        {"op": "keep_only", "page": SONG_DONGYE_URL, "kind": "tabs", "ids": [5000001], "read_at": LATE},
        {"op": "keep_only", "page": SONG_DONGYE_URL, "kind": "chords", "ids": [], "read_at": EARLY},
        {"op": "store", "page": SONG_DONGYE_URL, "name": SONG_DONGYE,
         "tabs": [song_dongye_tab(4180894, BANMA_UG, rating=1.0, votes=1)], "read_at": EARLY},
        {"op": "store", "page": SONG_DONGYE_URL, "name": "",
         "tabs": [song_dongye_tab(4180894, BANMA_UG, rating=4.9, votes=200)], "read_at": "2026-10-20T00:00:00Z"},
        {"op": "forget", "page": SONG_DONGYE_URL},
        {"op": "forget", "page": SONG_DONGYE_URL},
    ]))
    conn.close()

    conn = fresh(directory, "index")
    index_rows(conn, [f"{TAB}soda-stereo/persiana-americana-chords-1081460",
                      f"{TAB}soda-stereo/persiana-americana-tabs-1081462", f"{TAB}acdc/highway-to-hell-chords-9001",
                      f"{TAB}soda-stereo/de-musica-ligera-acoustic-chords-85060"])
    acdc = "https://www.ultimate-guitar.com/artist/ac_dc_1234"
    records.append(run_ops(conn, "tabs filed under the index's keys", [
        {"op": "store", "page": SODA, "name": "Soda Stereo", "tabs": [
            v(tab_id=1081460, song="Persiana Americana", artist="Soda Stereo", rating=4.9, votes=300,
              tab_url=f"{TAB}soda-stereo/persiana-americana-chords-1081460"),
            v(tab_id=2001, song="Persiana Americana", artist="Soda Stereo", rating=4.1, votes=8),
            v(tab_id=85060, song="De Música Ligera (acoustic)", artist="Soda Stereo",
              tab_url=f"{TAB}soda-stereo/de-musica-ligera-acoustic-chords-85060"),
            v(tab_id=85061, song="De Musica Ligera", artist="Soda Stereo", part="Intro", type="Tabs")],
         "read_at": EARLY},
        {"op": "store", "page": acdc, "name": "AC/DC", "tabs": [
            v(tab_id=9001, song="Highway To Hell", artist="AC/DC", tab_url=f"{TAB}acdc/highway-to-hell-chords-9001"),
            v(tab_id=9002, song="Highway to Hell", artist="AC/DC", type="Tabs"),
            v(tab_id=9003, song="Thunderstruck", artist="AC/DC")], "read_at": EARLY},
    ]))
    conn.close()

    conn = fresh(directory, "kept")
    page = "https://www.ultimate-guitar.com/artist/a_8"
    records.append(run_ops(conn, "what a store keeps, and what it leaves out", [
        {"op": "store", "page": page, "name": "A", "tabs": [
            v(tab_id=1), v(tab_id=2, type="Tabs", part=" SOLO "), v(tab_id=3, type="Ukulele Chords"),
            v(tab_id=4, type="Pro"), v(tab_id=5, type="Official"), v(tab_id=6, access="pro"),
            v(tab_id=7, tab_url="https://www.ultimate-guitar.com/pro/x"), v(tab_id=8, tab_url="http://[::1/tab/8"),
            v(tab_id=9, tab_url="ftp://tabs.ultimate-guitar.com/tab/9"),
            v(tab_id=10, tab_url="https://tabs.ultimate-guitar.com/tabs/10"),
            v(tab_id=11, tab_url="https://TABS.ultimate-guitar.com/tab/11"),
            v(tab_id=12, tab_url="HTTP://tabs.ultimate-guitar.com/tab/12"),
            v(tab_id=13, rating=None, votes=None, is_acoustic=True), v(tab_id=14, song="Song (acoustic)"),
            v(tab_id=15, song="斑马 斑马 Banma Banma Zebra Zebra", artist="Song Dongye (宋冬野)"),
            v(tab_id=16, tab_url=" https://tabs.ultimate-guitar.com/tab/16"),
            v(tab_id=17, tab_url="https://tabs.ultimate-guitar.com:443/tab/17"),
            {"id": 18, "song_name": "X", "marketing_type": "TabPro"}],
         "read_at": EARLY},
        {"op": "store", "page": page, "name": "A", "tabs": [v(tab_id=4, type="Pro")], "read_at": LATE},
        {"op": "store", "page": page, "name": "A", "tabs": [], "read_at": LATE},
        {"op": "keep_only", "page": page, "kind": "tabs", "ids": [2, 2, 99], "read_at": LATE},
        {"op": "keep_only", "page": "https://www.ultimate-guitar.com/artist/none_1", "kind": "chords", "ids": [],
         "read_at": LATE},
    ]))
    conn.close()

    conn = fresh(directory, "page")
    records.append(run_ops(conn, "artist pages parsed and stored as a fetch stores them", [
        {"op": "store_page", "page": SODA, "body": fixture_ref("ug/artist.html"), "kind": "chords", "read_at": EARLY},
        {"op": "store_page", "page": SODA, "body": fixture_ref("ug/artist.html"), "kind": None, "read_at": LATE},
        {"op": "store_page", "page": SONG_DONGYE_URL, "kind": "chords", "read_at": LATE,
         "body": body(song_dongye_page_html(song_dongye_chords(t4180894=(4.8, 120))))},
    ]))
    conn.close()
    return records


def backfill_records(directory: Path) -> list[dict[str, Any]]:
    now = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
    records = []
    chords = artist_page_url(SONG_DONGYE_URL, kind="chords")
    tabs = artist_page_url(SONG_DONGYE_URL, kind="tabs")
    soda_chords = artist_page_url(SODA, kind="chords")
    soda_2 = artist_page_url(SODA, kind="chords", page=2)
    page_one = make_artist_page_html(2946, "Soda Stereo", [version_dict(1, song="Uno", artist="Soda Stereo")],
                                     page=1, pages=3)
    page_two = make_artist_page_html(2946, "Soda Stereo", [version_dict(2, song="Dos", artist="Soda Stereo"),
                                                           version_dict(3, song="Tres", type="Tabs")], page=2, pages=3)
    cases = [
        ("every known page's lists the cache holds", {"宋冬野": SONG_DONGYE_URL}, [], {
            f"GET {chords}": {"status": 200, "fetched_at": EARLY,
                              "body": song_dongye_page_html(song_dongye_chords(t4180894=(4.8, 120)))},
            f"GET {tabs}": {"status": 200, "fetched_at": LATE, "body": song_dongye_page_html(
                [song_dongye_tab(5000001, "安和桥 Anhe Bridge", type="Tabs")])},
            f"GET {SONG_DONGYE_URL}": {"status": 404, "fetched_at": LATE, "body": "Not found"}}),
        ("a learned page, its list pages in a row until one is missing", {},
         [("ug:artist_url:soda-stereo", SODA + "/"), ("ug:artist_url:x", "not a page"),
          ("ug:artist_url:y", "https://tabs.ultimate-guitar.com/tab/1")], {
             f"GET {soda_chords}": {"status": 200, "fetched_at": EARLY, "body": page_one},
             f"GET {soda_2}": {"status": 200, "fetched_at": "", "body": page_two},
             f"GET {SODA}": {"status": 200, "fetched_at": EARLY, "body": "<html>no store</html>"}}),
        ("a pasted tab page is no artist page", {"a": "https://tabs.ultimate-guitar.com/tab/a/b-chords-5",
                                                 "b": "https://www.ultimate-guitar.com/artist/b_9"}, [], {}),
        ("the backfill once", {}, [("ug:artist_url:soda-stereo", SODA), (artist_tabs.BACKFILL_KEY, '{"pages": 0}')],
         {f"GET {soda_chords}": {"status": 200, "fetched_at": EARLY, "body": page_one}}),
    ]
    for n, (case, pasted, kv, cache) in enumerate(cases):
        conn = fresh(directory, f"backfill-{n}")
        for key, value in kv:
            db.kv_set(conn, key, value)
        cache_dir = directory / f"backfill-cache-{n}"
        overrides = Overrides(artist_url=pasted)
        records.append(scenario(
            conn, None, fn="caracole.ug.artist_tabs.backfill", case=case, now=now, clients={}, answers={},
            cache={"ug": cache}, kw={"artist_url": pasted}, cache_dir=cache_dir,
            call=lambda made, c=conn, d=cache_dir, o=overrides: artist_tabs.backfill(c, CachedAnswers("ug", d), o)))
        conn.close()
    return records


def test_ug_artist_tabs_jsonl(tmp_path):
    records = [*ops_records(tmp_path), *backfill_records(tmp_path)]
    check(OUT / "ug_artist_tabs.jsonl", jsonl(records, corpus="sites/ug_artist_tabs", made_by=MADE_BY))


def test_the_ops_keep_drop_and_forget_rows(tmp_path):
    first = ops_records(tmp_path)[0]["out"]
    rows = [o["rows"] for o in first]
    assert [len(r) for r in rows[:3]] == [7, 8, 7] and rows[-2] == [] and rows[-1] is None
    backfilled = backfill_records(tmp_path / "b")
    assert [r["out"]["result"] for r in backfilled] == [8, 2, 0, 0]
    assert all(r["out"]["requests"] == [] for r in backfilled)


# --- the index's reads -------------------------------------------------------------------------------------------


def index_tab(t: lookup.IndexTab | None) -> dict[str, Any] | None:
    return None if t is None else {"tab_id": t.tab_id, "type": t.type, "song_key": t.song_key, "label": t.label,
                                   "path": t.path, "url": t.url}


def lookup_records(directory: Path) -> list[dict[str, Any]]:
    conn = fresh(directory, "lookup")
    index_rows(conn, [
        f"{TAB}radiohead/creep-chords-4169", f"{TAB}radiohead/creep-acoustic-chords-4170",
        f"{TAB}radiohead/creep-tabs-4171", f"{TAB}radiohead/creep-live-chords-4172",
        f"{TAB}radiohead/creeping-chords-4173", f"{TAB}radiohead/creep-chords-4174",
        f"{TAB}radiohead/karma-police-chords-50", f"{TAB}radiohead/no-surprises-ukulele-chords-60",
        f"{TAB}soda-stereo/de-musica-ligera-chords-85042", f"{TAB}the-rifles/local-boy-chords-77",
        f"{TAB}radiohead/creep_x-chords-4175", f"{TAB}radiohead/creep%-chords-4176",
    ])
    before = dump_fixture(conn)
    plan = [
        ("song_tabs", ["radiohead", "creep"]), ("song_tabs", ["radiohead", "creep-acoustic"]),
        ("song_tabs", ["radiohead", "creeping"]), ("song_tabs", ["radiohead", "karma-police"]),
        ("song_tabs", ["radiohead", "no-surprises"]), ("song_tabs", ["rifles", "local-boy"]),
        ("song_tabs", ["radiohead", "cree"]), ("song_tabs", ["nobody", "creep"]), ("song_tabs", ["radiohead", "_"]),
        ("song_tabs", ["radiohead", "creep_x"]), ("song_tabs", ["radiohead", "%"]),
        ("song_tabs", ["radiohead", "CREEP"]), ("song_tabs", ["Radiohead", "creep"]),
        ("artist_known", ["radiohead"]), ("artist_known", ["the-rifles"]), ("artist_known", ["rifles"]),
        ("artist_known", ["Radiohead"]),
        ("index_tab", [4170]), ("index_tab", [999]), ("tab_url_for", [4169]), ("tab_url_for", [999]),
        ("artist_tabs", ["radiohead"]), ("artist_tabs", ["radiohead", 2]), ("artist_tabs", ["radiohead", 0]),
        ("artist_tabs", ["radiohead", -1]), ("artist_tabs", ["nobody"]),
        ("learned_artist_url", ["radiohead"]), ("remember_artist_url", ["radiohead", f"{SODA}x"]),
        ("learned_artist_url", ["radiohead"]), ("remember_artist_url", ["radiohead", SODA]),
        ("learned_artist_url", ["radiohead"]), ("forget_artist_url", ["radiohead"]),
        ("learned_artist_url", ["radiohead"]), ("forget_artist_url", ["radiohead"]),
    ]
    calls = []
    for fn, args in plan:
        answer = getattr(lookup, fn)(conn, *args)
        if fn in ("song_tabs", "artist_tabs"):
            answer = [index_tab(t) for t in answer]
        elif fn == "index_tab":
            answer = index_tab(answer)
        calls.append({"fn": fn, "args": args, "out": answer})
    conn.close()
    return [{"fn": "caracole.ug.lookup", "case": "the index's reads and the artist pages learned",
             "fixture": before, "calls": calls}]


def test_ug_pages_lookup_jsonl(tmp_path):
    check(OUT / "ug_pages_lookup.jsonl", jsonl(lookup_records(tmp_path), corpus="sites/ug_pages_lookup",
                                               made_by=MADE_BY))
