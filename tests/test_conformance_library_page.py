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
  The vector also holds ``server``, the server's member of the page's data (``build_library_page``'s, for the phone's
  controls ``SERVER_CONTROLS``: no Guitar Pro page, no sheet from YouTube and YouTube off) that the phone's
  ``LibraryPage.withServer`` writes; and ``minimal_cards``: songs only the phone has (``song``: their rows, ``files``:
  their ``files`` rows' name and path, ``ignored``: whether the phone's overrides ignore them), each with the card the
  phone gives it (``card``, ``minimal_card``: library_page.py's ``_song`` of a song with no key, no site, no
  file's origin, of its kept files alone); and ``routes``, caracole serve's status and headers for ``GET /``,
  ``/index.html`` and ``/favicon.ico`` (``WebApp.finish``'s among them), and the icon (``svg``).
- ``data/caracole/page/empty_library.json``: what the page's data holds of a library with no song that is no
  song's (``fold``, ``icons`` with no icon kept, ``catalogue``, ``songbooks`` with no songbooks.toml), as
  ``build_library_page`` writes them, in its key order (not sorted: the catalogue's order is each name's first key):
  the phone's page before its first sync.
- ``vectors/web/cards.jsonl``: library_page.py's ``_sort_key``, ``_letter``, ``_initials`` and ``_haystack``, which
  the phone's minimal cards of its own songs port, over names in many scripts (``NAMES``, and the keys corpus's
  ``names()`` and ``EDGES``); and of a kept file, ``_label``, ``_in_line_order`` (with no export), ``_primary``,
  ``icons.source_of`` with no origin and ``urllib.parse.quote(part, safe="")``, over the names a song's folder holds.

A change to library_assets/ (a file, or the order), to what library_page.py writes of a card or of the page's data, or
to the keys corpus's names makes these stale: regenerate them with this generator (§3 of
docs/superpowers/plans/2026-11-03-android-port-m1-m3.md), and the phone's tests read them again.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from unittest import mock
from urllib.parse import quote

import pytest

from caracole import library_page
from caracole.icons import page_icons, source_of
from caracole.inline import sha256_source
from caracole.library import keep_file
from caracole.library_page import (
    _TRANSLITERATED,
    SCRIPTS,
    STYLESHEETS,
    TEMPLATES,
    WebControls,
    _haystack,
    _in_line_order,
    _initials,
    _label,
    _letter,
    _primary,
    _sort_key,
    assemble_page,
    build_library_page,
    song_cards,
)
from caracole.normalize import clean_title, fold
from caracole.overrides import Overrides
from caracole.progressions import catalogue
from caracole.songbook_section import songbooks_data
from caracole.songs import get_song
from caracole.versions import upsert_version
from conftest import add_song
from helpers import browser
from helpers.browser import in_chromium
from helpers.corpus import DATA, VECTORS, check, json_document, jsonl
from test_conformance_keys import EDGES
from test_conformance_keys import names as keys_names

MADE_BY = "tests/test_conformance_library_page.py"
ASSETS = DATA / "page" / "library_assets.json"
EMPTY = DATA / "page" / "empty_library.json"
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
# quote and the backslash, control characters (those json.dumps writes short, \\b \\f \\n \\r \\t, and the others),
# the line and paragraph separators, a character beyond the BMP.
TRICKY = ("</script><!-- \"quoted\" back\\slash tab\there\nline\rreturn\bback\fform"
          "\u0001\u001f\u007f\u2028\u2029 😀 é")


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
    """The server's member of the page's data, as the phone writes it (``server_member``): with requests on their
    way (SERVER_CONTROLS'), or none."""
    controls = SERVER_CONTROLS if active else WebControls(CSRF)
    return server_member(controls)


# The phone's controls of the vector's ``server``: a song a request runs for, one a removal waits for, a request.
SERVER_CONTROLS = WebControls(CSRF, busy=frozenset({3, 1}), active=2, held=frozenset({3}), removing=frozenset({5}),
                              jobs=({"id": 7, "kind": "lookup", "song": 1, "state": "running"},))


def server_member(controls: WebControls) -> dict[str, Any]:
    """``build_library_page``'s ``server`` for ``controls`` on the phone: no Guitar Pro page, no sheet from YouTube
    (``YOUTUBE_PROBLEM``), YouTube off (checked against build_library_page itself:
    ``test_the_server_member_is_build_library_pages``)."""
    return {"csrf": controls.csrf, "busy": sorted(controls.busy), "active": controls.active,
            "removing": sorted(controls.removing), "jobs": list(controls.jobs), "guitar": False,
            "youtube": {"ok": False, "why": YOUTUBE_PROBLEM, "off": True}}


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


# Songs only the phone has (taken in a sync before the mirror came again, or added on the phone): their artist,
# title and artists, status, review, whether the phone's overrides ignore them, and the files they keep (the phone's
# ``files`` table), in the order kept: numbers past 9 and in another script's digits, Power Tab, scores of each kind
# and of none, an auto sheet's, a name no group of the line holds, a folder name safe_name changes, none.
MINIMAL_SONGS = (
    ("Sigur Rós", "Hoppípolla (Live)", ["Sigur Rós", "Jónsi"], "wanted", False, False,
     ("tab.txt", "sheet.txt", "guitar-10.gp5", "guitar-2.gp5", "guitar-٣.ptb", "score-1.pdf", "score-1.mxl",
      "score-2.mid", "score-3.doc", "harmonica-1.txt", "gametab-1.txt", "lyrics.lrc", "info.json", "notes.md")),
    ("宋冬野", "斑马斑马", None, "found", True, False, ("sheet (auto).pdf", "sheet (auto).txt", "sheet (auto).html")),
    ("Guns N' Roses", "Sweet Child O' Mine", None, "found", True, True, ("sheet.txt",)),
    ("AC/DC", "T.N.T.", [], "wanted", False, False, ()),  # its row's artists empty, as an older row's may be
)
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def keep_minimal_songs(conn, cfg) -> list[tuple[Any, dict[str, str], bool]]:
    """MINIMAL_SONGS in a fresh database, as a sync leaves them: each song, its kept files' paths by name, and
    whether it is ignored."""
    kept = []
    for artist, title, artists, status, review, ignored, names in MINIMAL_SONGS:
        song = add_song(conn, artist, title, artists=artists or None, added_at=f"2026-10-0{len(kept) + 1}T00:00:00Z")
        conn.execute("UPDATE songs SET status = ?, review = ? WHERE id = ?", (status, int(review), song.id))
        if artists == []:
            conn.execute("UPDATE songs SET artists = '[]' WHERE id = ?", (song.id,))
        version = upsert_version(conn, provider="ug", tab_id=str(100 + song.id), song_id=song.id, slot="sheet",
                                 kind="chords", rating=4, votes=1, version=1, label=None, url="u", raw={},
                                 now="2026-10-01T00:00:00Z")
        for rank, name in enumerate(names, start=1):
            keep_file(conn, cfg.library_dir, song=song, version_id=version, name=name, data=name.encode(), rank=rank)
        paths = dict(conn.execute("SELECT name, path FROM files WHERE song_id = ?", (song.id,)).fetchall())
        kept.append((get_song(conn, song.id), paths, ignored))
    return kept


def minimal_card(song: Any, files: dict[str, str], ignored: bool) -> dict[str, Any]:
    """The card the phone gives a song only it has: ``_song``'s fields of a song with no key, no file's origin and no
    site, of its kept files alone (``files``: their paths by name), each file's link its path percent-encoded."""
    title = clean_title(song.title)
    ordered = _in_line_order(set(files), [])
    primary = _primary(ordered)
    entries = []
    for name in ordered:
        entry = {"name": name, "label": _label(name), "href": "/".join(quote(part, safe="") for part in
                                                                       files[name].split("/")),
                 "primary": name == primary, "source": source_of(name, {})}
        if library_page._GUITAR.fullmatch(name) or (library_page._SCORE.fullmatch(name) and not name.endswith(".pdf")):
            entry["download"] = library_page.download_name(song.artist, title, name)
        entries.append(entry)
    sort_artist, sort_title = _sort_key(song.artist), _sort_key(title)
    initials = _initials(title)
    return {
        "id": song.id, "artist": song.artist, "artists": song.artists or [song.artist], "title": title,
        "display": song.display, "status": "ignored" if ignored else song.status,
        "review": bool(song.review) and not ignored, "added": song.added_at, "key": None, "files": entries,
        "source": next((f["source"] for f in entries if f["primary"]), None), "identity": song.key,
        "sortArtist": sort_artist, "sortTitle": sort_title, "artistLetter": _letter(sort_artist),
        "titleLetter": _letter(sort_title), "search": _haystack([song.artist, *song.artists, title, song.display]),
        **({"initials": initials} if initials else {}), "sites": [],
    }


def minimal_cards(conn, cfg) -> list[dict[str, Any]]:
    return [{"song": {"key": song.key, "artist": song.artist, "title": song.title, "artists": song.artists,
                      "added_at": song.added_at, "status": song.status, "review": bool(song.review)},
             "files": sorted([name, path] for name, path in files.items()),
             "ignored": ignored, "card": minimal_card(song, files, ignored)}
            for song, files, ignored in keep_minimal_songs(conn, cfg)]


def library_page_json(conn, cfg) -> str:
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
        "server": {"controls": {"csrf": SERVER_CONTROLS.csrf, "busy": sorted(SERVER_CONTROLS.busy),
                                "active": SERVER_CONTROLS.active, "held": sorted(SERVER_CONTROLS.held),
                                "removing": sorted(SERVER_CONTROLS.removing), "jobs": list(SERVER_CONTROLS.jobs)},
                   "member": server_member(SERVER_CONTROLS)},
        "minimal_cards": minimal_cards(conn, cfg),
        "routes": served_routes(cfg),
    }, corpus="web/library_page", made_by=MADE_BY)


# The page's routes, as caracole serve answers them: their status and headers (the page's own in its meta tag).
ROUTE_PATHS = ("/", "/index.html", "/favicon.ico")


def served_routes(cfg) -> dict[str, Any]:
    """caracole serve's answer to a GET of each of ROUTE_PATHS, every header WebApp.finish gives it, in its order:
    ``{path: {"status", "headers": [[name, value], ...]}}``, and the icon's body (``svg``)."""
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue
    from test_web_app import ALLOWED, Recorder, get

    app = WebApp(cfg, JobQueue(Recorder(), limit=3), allowed=ALLOWED, csrf=CSRF)
    answers = {path: get(app, path, **{"sec-fetch-site": "same-origin"}) for path in ROUTE_PATHS}
    return {path: {"status": answer.status, "headers": [[name, value] for name, value in answer.headers]}
            for path, answer in answers.items()} | {"svg": answers["/favicon.ico"].body.decode("utf-8")}


def empty_library_json(cfg) -> str:
    """What a library with no song holds that is no song's, as build_library_page writes it (its order kept)."""
    data = {
        "fold": {c: fold(c) for c in _TRANSLITERATED},
        "icons": page_icons(cfg.cache_dir),
        "catalogue": catalogue(),
        "songbooks": songbooks_data(None, cfg, Overrides()),
    }
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


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


def all_names() -> list[str]:
    """NAMES, then the keys corpus's names and edges, each once, none with a lone surrogate."""
    seen = dict.fromkeys((*NAMES, *keys_names(), *EDGES))
    return [name for name in seen if not any(0xD800 <= ord(c) <= 0xDFFF for c in name)]


# What a song's folder may hold, for a kept file's label, its place in the line, its link: every name the line lists,
# numbers in any script's digits and of many places, every score extension, and names of no group.
FILE_NAMES = (
    *library_page._SHEET_PAGES, "sheet.txt", "sheet.cho", "lyrics.txt", "lyrics.lrc", "tab.txt", "sheet (auto).txt",
    "sheet (auto).cho", "info.json", "guitar-1.gp5", "guitar-2.gp", "guitar-10.gpx", "guitar-9.gp3", "guitar-1.PTB",
    "guitar-3.ptb", "guitar-007.gp5", "guitar-٣.gp5", "guitar-３.gp4", "guitar-𝟗.gp5", "guitar-12345678901234567890.gp5",
    "score-1.mscz", "score-1.mxl", "score-1.musicxml", "score-1.pdf", "score-1.mid", "score-1.midi", "score-2.pdf",
    "score-10.mxl", "score-٢.mid", "harmonica-1.txt", "harmonica-12.txt", "harmonica-2.txt", "gametab-3.txt",
    "gametab-1.txt",
)
# Names of no group: the line leaves them out (_label would refuse them).
UNLISTED = ("notes.md", "sheet.json", "version-12.txt", "version-12.html", "score-1.doc", "score-1.MXL", "guitar-.gp5",
            "guitar-1", "guitar-1.g p5", "harmonica-1.html", "harmonica-x.txt", "Sheet.txt",
            "sheet (G Dorian, capo 0).pdf")
# Sets of names a folder holds, for the line's order and the file it opens.
FOLDERS = (
    FILE_NAMES, FILE_NAMES + UNLISTED, UNLISTED, (), ("sheet.txt",), ("sheet (auto).txt", "tab.txt"),
    ("sheet (auto).pdf", "sheet.txt"), ("sheet.pdf", "sheet (auto).html"), ("tab.txt", "lyrics.txt", "info.json"),
    ("guitar-10.gp5", "guitar-2.gp5", "guitar-2.ptb", "guitar-٣.gp5", "guitar-3.gp5", "guitar-𝟗.gp5", "guitar-９.gp5"),
    ("score-1.pdf", "score-1.mxl", "score-0.midi", "score-1.mscz", "score-٢.mid", "score-1.doc"),
)
# Parts of a path (no "/" in one), for urllib's quote(part, safe=""): what it leaves as it is, what it writes %XX, in
# UTF-8.
PARTS = ("Guns N' Roses", "100% #1 Hit", "sheet (auto).html", "a_b.c-d~e", "Ñandú", "斑马", "😀", "AC_DC", "a\\b",
         "?&=+;,:@$!*'()[]", "tab\there", "", " ", "~", "Ｆｕｌｌ")


def card_records() -> list[dict[str, Any]]:
    fn = "caracole.library_page."
    records: list[dict[str, Any]] = []
    for name in all_names():
        key = _sort_key(name)
        records.append({"fn": fn + "_sort_key", "args": [name], "kw": {}, "out": key})
        records.append({"fn": fn + "_letter", "args": [key], "kw": {}, "out": _letter(key)})
        records.append({"fn": fn + "_initials", "args": [name], "kw": {}, "out": _initials(name)})
        records.append({"fn": fn + "_haystack", "args": [[name]], "kw": {}, "out": _haystack([name])})
    for texts in (["宋冬野", "宋冬野", "斑马斑马", "宋冬野 - 斑马斑马", "minor"], ["Sigur Rós", "Jónsi", "Hoppípolla"],
                  ["AC/DC", "AC/DC", "T.N.T.", "AC/DC - T.N.T."], ["a", "a", "A"], [], ["", " "]):
        records.append({"fn": fn + "_haystack", "args": [texts], "kw": {}, "out": _haystack(texts)})
    for name in FILE_NAMES:
        records.append({"fn": fn + "_label", "args": [name], "kw": {}, "out": _label(name)})
    for name in FILE_NAMES + UNLISTED:
        records.append({"fn": "caracole.icons.source_of", "args": [name, {}], "kw": {}, "out": source_of(name, {})})
    for names in FOLDERS:
        ordered = _in_line_order(set(names), [])
        records.append({"fn": fn + "_in_line_order", "args": [sorted(names), []], "kw": {}, "out": ordered})
        records.append({"fn": fn + "_primary", "args": [ordered], "kw": {}, "out": _primary(ordered)})
    for part in PARTS:
        records.append({"fn": "urllib.parse.quote", "args": [part], "kw": {"safe": ""}, "out": quote(part, safe="")})
    return records


def test_library_assets_json_is_the_pages_order_of_its_files():
    check(ASSETS, library_assets_json())


def test_library_page_json_is_the_phones_page_for_each_case(conn, cfg):
    check(PAGE, library_page_json(conn, cfg))


def test_empty_library_json_is_what_a_library_with_no_song_holds(cfg):
    check(EMPTY, empty_library_json(cfg))


def test_cards_jsonl_is_library_pages_sort_keys_letters_initials_haystacks_and_files():
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


def test_the_vectors_data_reads_back_in_the_order_its_page_was_made_with(conn, cfg):
    # A reader of the vector keeps its objects' keys in the file's order, sorted: the page's JSON block is then the
    # block its data makes, whoever reads it.
    document = json.loads(library_page_json(conn, cfg))
    for case in document["cases"]:
        page = phone_page(case["data"], case["controls"])
        assert hashlib.sha256(page.encode("utf-8")).hexdigest() == case["sha256"], case["name"]
    assert document["cases"][0]["page"] == phone_page(document["cases"][0]["data"], document["cases"][0]["controls"])
    assert "page" not in document["cases"][1]


def test_the_cases_cover_what_the_page_writes_otherwise():
    objects = data_objects()
    chinese = next(controls for name, controls in CASES if name == "chinese")
    page = phone_page(objects["chinese"], chinese)
    assert "\\u003c/script>" in page and "斑马斑马" in page and "😀" in page and "\\u0001" in page
    assert all(escaped in page for escaped in ("\\b", "\\f", "\\r", "\\t", "\\n"))
    assert "&amp;&quot;&lt;&#x27;&gt;" in page  # the form token, escaped in the request form
    assert "No sheets from YouTube here: YouTube isn&#x27;t on the phone." in page
    assert {controls["sync"] for _, controls in CASES} == {False, True}
    assert {controls["badge"] for _, controls in CASES} == {"Phone", None}


def test_the_server_member_is_build_library_pages(conn, cfg):
    # The phone's server member is the one build_library_page writes for the same controls, with no Guitar Pro page,
    # no sheet from YouTube (the phone's reason) and YouTube off.
    youtube = cfg.provider("youtube")
    off = mock.patch.object(type(cfg), "provider", lambda self, name: (
        type(youtube)(**{**youtube.__dict__, "enabled": False}) if name == "youtube" else youtube))
    with off, mock.patch.object(library_page, "route_reason", lambda cfg: YOUTUBE_PROBLEM):
        html = build_library_page(conn, cfg, Overrides(), NOW, controls=SERVER_CONTROLS)
    data = json.loads(re.search(r'<script type="application/json" id="songs">(.*?)</script>', html, re.S).group(1))
    assert data["server"] == server_member(SERVER_CONTROLS)
    assert list(data["server"]) == list(server_member(SERVER_CONTROLS))
    assert list(data).index("server") == list(data).index("songbooks") - 1


def test_a_minimal_card_is_the_card_build_library_page_writes_of_the_song_but_what_the_phone_lacks(conn, cfg):
    # The phone knows a song of its own by its row and its kept files alone: its card is the computer's for that
    # song, its fields in their order, less what the phone has no record of (its musical key, where each file came
    # from, its sites, its versions, lyrics and the rest), and each Guitar Pro file's Guitar Pro page.
    kept = keep_minimal_songs(conn, cfg)
    ignored = frozenset(song.key for song, _, ignore in kept if ignore)
    cards = {card["id"]: card for card in song_cards(conn, cfg, Overrides(ignore=ignored), NOW)}
    for song, files, ignore in kept:
        mine, computers = minimal_card(song, files, ignore), cards[song.id]
        assert [k for k in computers if k in mine] == list(mine), song.display
        for field, value in mine.items():
            if field not in ("source", "files", "sites"):
                assert computers[field] == value, (song.display, field)
        assert [f["name"] for f in computers["files"]] == [f["name"] for f in mine["files"]]
        for theirs, ours in zip(computers["files"], mine["files"], strict=True):
            assert list(ours) == [k for k in theirs if k in ours and k != "guitarPage"], ours["name"]
            assert {k: v for k, v in theirs.items() if k in ours and k != "source"} == {
                k: v for k, v in ours.items() if k != "source"}, ours["name"]


def test_the_empty_librarys_songbooks_are_the_tabs_with_no_songbooks_toml(cfg, conn):
    empty = json.loads(empty_library_json(cfg))
    assert list(empty) == ["fold", "icons", "catalogue", "songbooks"]
    assert empty["songbooks"]["books"] == [] and empty["songbooks"]["error"] is None
    assert {"keys", "modes", "capoMax", "instruments", "fileLabels"} <= set(empty["songbooks"])
    html = build_library_page(conn, cfg, Overrides(), NOW)
    data = json.loads(re.search(r'<script type="application/json" id="songs">(.*?)</script>', html, re.S).group(1))
    assert {name: data[name] for name in empty} == empty


# --- the phone's data shapes, in a real browser ---------------------------------------------------------------


def phone_shaped_data(conn, cfg) -> dict[str, Any]:
    """A page's data as only the phone makes it: an empty library's (no sync yet: no sites), a card of the
    computer's for a song the phone hasn't got (a negative id, not fetchable), and minimal cards of its own songs."""
    empty = json.loads(empty_library_json(cfg))
    computers = data_objects()["chinese"]["songs"][1] | {"id": -1, "fetchable": False}
    mine = [entry["card"] | {"fetchable": entry["card"]["id"] > 0} for entry in minimal_cards(conn, cfg)]
    return {"generated": "2026-11-03T12:00:00Z", "fold": empty["fold"], "songs": [computers, *mine],
            "icons": empty["icons"], "catalogue": empty["catalogue"], "server": server(0),
            "songbooks": empty["songbooks"], "sites": []}


# Run after the page's scripts: what the list drew, and every error the page's scripts threw.
PROBE = """window.addEventListener("load", () => { setTimeout(() => {
  const titles = Array.from(document.querySelectorAll("#list article h3")).map((h) => h.textContent);
  document.body.dataset.result = JSON.stringify({titles, errors: window.__errors || []});
}, 50); });"""
# Before them: an error's message, kept.
CATCH = ("window.__errors = []; window.addEventListener(\"error\", (e) => window.__errors.push(String(e.message)));"
         " window.addEventListener(\"unhandledrejection\", (e) => window.__errors.push(String(e.reason)));")


def _sha(text: str) -> str:
    import base64

    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


@in_chromium
@pytest.mark.parametrize("sync", [False, True])
def test_the_phones_own_data_shapes_draw_with_no_script_error(conn, cfg, tmp_path, sync):
    # library.js, card.js and songbooks.js read every field through listOf() and defaults; this shows it, on the
    # shapes no computer's page has.
    data = phone_shaped_data(conn, cfg)
    html = phone_page(data, {"csrf": CSRF, "badge": "Phone", "sync": sync})
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    html = html.replace(csp, csp.replace("script-src ", f"script-src {_sha(CATCH)} {_sha(PROBE)} "))
    html = html.replace("<head>", f"<head>\n<script>{CATCH}</script>", 1)
    html = html.replace("</body>", f"<script>{PROBE}</script>\n</body>")
    page = tmp_path / "phone.html"
    page.write_text(html, encoding="utf-8")
    dom = browser.dump_dom(page.as_uri(), (1280, 900))
    found = re.search(r'data-result="([^"]*)"', dom)
    assert found, dom[-3000:]
    import html as html_module

    out = json.loads(html_module.unescape(found.group(1)))
    assert out["errors"] == []
    assert sorted(out["titles"]) == sorted(song["title"] for song in data["songs"]), out["titles"]
