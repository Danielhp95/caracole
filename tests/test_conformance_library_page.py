"""The library page, for the phone: what android/server's ``page`` package reads and checks its page against.

- ``data/caracole/page/library_assets.json``, the runtime order the phone's ``LibraryAssets`` reads library_assets/
  in: ``{"SCRIPTS": [name, …], "STYLESHEETS": [name, …], "TEMPLATES": [name, …]}``, library_page.py's three tuples
  as they are. The scripts and the stylesheets are inlined in this order, each file's text whole (its UTF-8 bytes,
  ``library_assets.read``), and the templates are filled in by name.
- ``vectors/web/library_page.json``: the hashes the page's policy allows its script and its style by
  (``script_hash``, ``style_hash``: ``inline.sha256_source`` of the concatenated files), the served page's policy
  (``csp``), the reason the request form gives for no sheet from YouTube on the phone (``youtube_problem``), the
  library's name (``library_name``), and ``cases``: for fixed data objects (``data``: one with Chinese and the
  characters a JSON block must escape, one with no songs; each object's keys sorted, as the vector keeps them, so
  that its JSON block is the one a reader of the vector writes) and the server's controls (``controls``: the form
  token, the badge, the Sync tab or not), the SHA-256 of the page (``sha256``, of its UTF-8), and the page itself
  (``page``) for the smallest case. The page is ``library_page.assemble_page``'s served page with no Requests tab,
  as the phone serves it until M4 brings the tab: ``__TABREQUESTS__`` and ``__REQUESTS__`` filled with nothing.
- ``vectors/web/cards.jsonl``: library_page.py's ``_sort_key``, ``_letter``, ``_initials`` and ``_haystack``, which
  the phone's minimal cards of its own songs port, over names in many scripts (``NAMES``).

A change to library_assets/ (a file, or the order) makes these stale: regenerate them with this generator (§3 of
docs/superpowers/plans/2026-11-03-android-port-m1-m3.md), and the phone's tests read them again.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest import mock

from caracole import library_page
from caracole.inline import sha256_source
from caracole.library_page import (
    _TRANSLITERATED,
    SCRIPTS,
    STYLESHEETS,
    TEMPLATES,
    WebControls,
    _haystack,
    _initials,
    _letter,
    _sort_key,
    assemble_page,
)
from caracole.normalize import fold
from helpers.corpus import DATA, VECTORS, check, json_document, jsonl

MADE_BY = "tests/test_conformance_library_page.py"
ASSETS = DATA / "page" / "library_assets.json"
PAGE = VECTORS / "web" / "library_page.json"
CARDS = VECTORS / "web" / "cards.jsonl"

# What the phone's page says where caracole serve's says why this caracole makes no sheet from a YouTube video
# (youtube_fetch.route_reason): the request form's line, "No sheets from YouTube here: YouTube isn't on the phone."
YOUTUBE_PROBLEM = "YouTube isn't on the phone"
LIBRARY_NAME = "Phone"
# A form token with every character html.escape writes otherwise, so the request form's escape is checked too.
CSRF = "tok-&\"<'>-0123456789"


def library_assets_json() -> str:
    data = {"SCRIPTS": list(SCRIPTS), "STYLESHEETS": list(STYLESHEETS), "TEMPLATES": list(TEMPLATES)}
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def sorted_deep(value: Any) -> Any:
    """``value`` with every object's keys in sorted order, as a ``.json`` vector keeps them."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


# The characters a page's JSON block writes otherwise than as they are, or that a reader might: "<" (\\u003c), the
# quote and the backslash, control characters, the line and paragraph separators, a character beyond the BMP.
TRICKY = "</script><!-- \"quoted\" back\\slash tab\there\nline\u0001\u001f\u007f\u2028\u2029 😀 é"


def card(n: int, artist: str, title: str, **more: Any) -> dict[str, Any]:
    """A song's card, as the page's data carries one: its fields' shapes, made up."""
    sort_artist, sort_title = _sort_key(artist), _sort_key(title)
    return {
        "id": n, "artist": artist, "artists": [artist], "title": title, "display": f"{artist} - {title}",
        "status": "found", "review": False, "added": "2026-10-01T00:00:00Z", "key": "G", "key_source": "ug",
        "transpose": 0, "lyrics": "found", "lyricsFrom": None, "auto": False,
        "files": [{"name": "sheet.html", "label": "Sheet viewer", "href": f"{artist}/{title}/sheet.html",
                   "primary": True, "source": "ug"}],
        "instruments": [], "versions": None, "autoSheet": None, "source": "ug", "museScore": [], "links": [],
        "buy": [], "youtube": None, "youtubeSheet": False, "lacuerda": None, "lacuerdaVersions": [],
        "lacuerdaSheet": None, "identity": f"{sort_artist}/{sort_title}", "sortArtist": sort_artist,
        "sortTitle": sort_title, "artistLetter": _letter(sort_artist), "titleLetter": _letter(sort_title),
        "search": _haystack([artist, title]), "progressions": [], "fetchable": True, **more,
    }


def server(active: int) -> dict[str, Any]:
    return {"csrf": CSRF, "busy": [1] if active else [], "active": active, "removing": [], "jobs": [], "guitar": False,
            "youtube": {"ok": False, "why": "YouTube isn't on the phone.", "off": True}}


def data_objects() -> dict[str, dict[str, Any]]:
    """The fixed data objects of the cases: their names, and each object as the vector keeps it."""
    shared = {
        "generated": "2026-11-03T12:00:00Z",
        "fold": {c: fold(c) for c in _TRANSLITERATED},
        "icons": {"ug": {"name": "Ultimate Guitar", "badge": "UG", "src": "data:image/png;base64,iVBORw0KGgo="}},
        "catalogue": {"I-V-vi-IV": {"name": "the pop progression", "source": "Wikipedia"}},
        "songbooks": {"books": [], "error": None, "keys": ["C", "C♯", "D"], "modes": [["major", "major"]],
                      "capoMax": 11, "instruments": [["guitar", "Guitar", True]], "fileLabels": ["PDF"]},
    }
    chinese = shared | {
        "songs": [
            card(1, "宋冬野", "斑马斑马", initials="bmbm",
                 hanzi={"simplified": {"斑马斑马": "斑马斑马", "宋冬野": "宋冬野"},
                        "traditional": {"斑马斑马": "斑馬斑馬", "宋冬野": "宋冬野"}}),
            card(2, "Sigur Rós", TRICKY, rating=4.5, score=1e-07, votes=123456789012345678, gone=-0.0,
                 nested={"empty": {}, "list": [], "none": None, "yes": True}),
        ],
        "server": server(1),
        "sites": [{"id": "ug", "name": "Ultimate Guitar", "role": TRICKY, "rows": 1234567}],
    }
    empty = shared | {"songs": [], "server": server(0), "sites": []}
    return {"chinese": sorted_deep(chinese), "empty": sorted_deep(empty)}


# The cases: a data object, and the controls the page is served with.
CASES = (
    ("empty", {"csrf": CSRF, "badge": "Phone", "sync": False}),  # the smallest: its page is in the vector whole
    ("empty", {"csrf": CSRF, "badge": "Phone", "sync": True}),
    ("chinese", {"csrf": CSRF, "badge": "Phone", "sync": False}),
    ("chinese", {"csrf": CSRF, "badge": "Phone", "sync": True}),
    ("chinese", {"csrf": CSRF, "badge": None, "sync": True}),
)


def phone_page(data: dict[str, Any], controls: dict[str, Any]) -> str:
    """The page the phone serves for ``data`` and ``controls``: caracole serve's (``assemble_page``, served), with no
    Requests tab."""
    served = WebControls(controls["csrf"], badge=controls["badge"], sync=controls["sync"])
    with (mock.patch.object(library_page, "_requests_tab", lambda controls: ""),
          mock.patch.object(library_page, "_requests_panel", lambda controls: "")):
        return assemble_page(data, served, problem=YOUTUBE_PROBLEM, library_name=LIBRARY_NAME)


def library_page_json() -> str:
    objects = data_objects()
    cases = []
    for n, (name, controls) in enumerate(CASES):
        page = phone_page(objects[name], controls)
        cases.append({"name": f"{name}, sync {'on' if controls['sync'] else 'off'}, badge {controls['badge']}",
                      "data": objects[name], "controls": controls,
                      "sha256": hashlib.sha256(page.encode("utf-8")).hexdigest(),
                      **({"page": page} if n == 0 else {})})
    served_csp = phone_page(objects["empty"], CASES[0][1]).split('<meta http-equiv="Content-Security-Policy" content="',
                                                                 1)[1].split('"', 1)[0]
    return json_document({
        "script_hash": sha256_source(library_page._PAGE_SCRIPT),
        "style_hash": sha256_source(library_page._PAGE_STYLE),
        "csp": served_csp,
        "youtube_problem": YOUTUBE_PROBLEM,
        "library_name": LIBRARY_NAME,
        "cases": cases,
    }, corpus="web/library_page", made_by=MADE_BY)


# Names in many scripts and spellings: Latin with accents and letters fold transliterates, Chinese (Simplified,
# Traditional, mixed with Latin), other scripts, apostrophes, punctuation, digits, spaces, and nothing at all.
NAMES = (
    "The Beatles", "Wish You Were Here", "Guns N' Roses", "Don’t Stop Me Now", "Rock ’n’ Roll", "'Til Tuesday",
    "100% #1 Hit", "9 to 5", "#1", "1999", "AC/DC", "a-b-c", "under_score", "Mr. Brightside", "!!!", "¿Quién será?",
    "¡Ay!", "Sigur Rós", "Mötley Crüe", "Ñandú", "Él", "Señor", "Ça plane pour moi", "Café Tacvba", "Björk",
    "Los Enanitos Verdes", "Ægir", "Œuvre", "Øystein", "Straße", "ẞ", "Łódź", "Đorđe", "ÞÓR", "Ðóra", "İstanbul",
    "ıi", "Ħamrun", "Ｆｕｌｌｗｉｄｔｈ", "ﬁne", "Ⅻ", "Cafe\u0301", "Москва", "Ελλάδα", "日本語の歌", "한국어 노래",
    "ไทย", "עברית", "عربي", "宋冬野", "斑马斑马", "斑馬斑馬", "周杰伦", "稻香", "Hello 世界", "G.E.M. 邓紫棋",
    "邓紫棋 - 光年之外", "Tab\there", "line\nbreak", "😀 emoji", "Zebra", "zz", "ABC", "a", "Z", "é", "", " ",
)


def card_records() -> list[dict[str, Any]]:
    fn = "caracole.library_page."
    records: list[dict[str, Any]] = []
    for name in NAMES:
        key = _sort_key(name)
        records.append({"fn": fn + "_sort_key", "args": [name], "kw": {}, "out": key})
        records.append({"fn": fn + "_letter", "args": [key], "kw": {}, "out": _letter(key)})
        records.append({"fn": fn + "_initials", "args": [name], "kw": {}, "out": _initials(name)})
        records.append({"fn": fn + "_haystack", "args": [[name]], "kw": {}, "out": _haystack([name])})
    for texts in (["宋冬野", "宋冬野", "斑马斑马", "宋冬野 - 斑马斑马", "minor"], ["Sigur Rós", "Jónsi", "Hoppípolla"],
                  ["AC/DC", "AC/DC", "T.N.T.", "AC/DC - T.N.T."], ["a", "a", "A"], [], ["", " "]):
        records.append({"fn": fn + "_haystack", "args": [texts], "kw": {}, "out": _haystack(texts)})
    return records


def test_library_assets_json_is_the_pages_order_of_its_files():
    check(ASSETS, library_assets_json())


def test_library_page_json_is_the_phones_page_for_each_case():
    check(PAGE, library_page_json())


def test_cards_jsonl_is_library_pages_sort_keys_letters_initials_and_haystacks():
    check(CARDS, jsonl(card_records(), corpus="web/cards", made_by=MADE_BY))


def test_the_phones_page_is_caracole_serves_without_its_requests_tab():
    # The one difference: the Requests tab and its panel (requests.js asks /requests.json, which the phone has not
    # in M3). With them, the page is assemble_page's as caracole serve fills it in.
    objects = data_objects()
    for name, controls in CASES:
        served = WebControls(controls["csrf"], badge=controls["badge"], sync=controls["sync"])
        computer = assemble_page(objects[name], served, problem=YOUTUBE_PROBLEM, library_name=LIBRARY_NAME)
        phone = phone_page(objects[name], controls)
        tab, panel = library_page._requests_tab(served), library_page._requests_panel(served)
        assert tab and panel and tab not in phone and panel not in phone
        assert computer.count(tab) == computer.count(panel) == 1
        assert computer.replace(tab, "", 1).replace(panel, "", 1) == phone


def test_the_vectors_data_reads_back_in_the_order_its_page_was_made_with():
    # A reader of the vector keeps its objects' keys in the file's order, sorted: the page's JSON block is then the
    # block its data makes, whoever reads it.
    document = json.loads(library_page_json())
    for case in document["cases"]:
        page = phone_page(case["data"], case["controls"])
        assert hashlib.sha256(page.encode("utf-8")).hexdigest() == case["sha256"], case["name"]
    assert document["cases"][0]["page"] == phone_page(document["cases"][0]["data"], document["cases"][0]["controls"])
    assert "page" not in document["cases"][1]


def test_the_cases_cover_what_the_page_writes_otherwise():
    document = json.loads(library_page_json())
    chinese = next(case for case in document["cases"] if case["data"]["songs"])
    page = phone_page(chinese["data"], chinese["controls"])
    assert "\\u003c/script>" in page and "斑马斑马" in page and "😀" in page and "\\u0001" in page
    assert "&amp;&quot;&lt;&#x27;&gt;" in page  # the form token, escaped in the request form
    assert "No sheets from YouTube here: YouTube isn&#x27;t on the phone." in page
    assert {case["controls"]["sync"] for case in document["cases"]} == {False, True}
    assert {case["controls"]["badge"] for case in document["cases"]} == {"Phone", None}
