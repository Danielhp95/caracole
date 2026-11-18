"""caracole.viewer: a sheet's versions and the song's other kinds (kinds.js, viewer.css, page.py's line and list).

Each viewer of a song with versions (its data's ``versions``, sheet_versions.as_data: the sheet's own
viewer and each kept version's) says under its artist which of UG's versions it is, its kind first and its rating
last ("Chords · Ver 3 of 13 · ★ 4.86 (408)"), then an icon for each kind of thing the song keeps to play from (its
data's ``kinds``, render.py ``_kinds_data``), the library card's glyphs, with how many of each. The line opens the
list of every version UG has: a kept one opens, in the same tab, with the text size and the screen's choices; one not
kept is kept (caracole serve's /versions page) or shows the command that keeps it (a file), a gone one is neither.
The data here is helpers/version_pages.py's, in the shape render.py writes.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from helpers.browser import Browser, in_chromium
from helpers.targets import small_targets
from helpers.version_pages import CHO, EVERY_KIND, KINDS, UG, WONDERWALL, entry, folder, with_versions
from helpers.viewer_pages import back, entries, viewer

from caracole import render
from caracole.sheet_versions import SheetVersion, as_data
from caracole.viewer import build_viewer, page, viewer_csp
from caracole.viewer.book import BookSong, build_songbook
from caracole.viewer.harptab_page import build_harmonica_viewer

PHONE = {"width": 390, "height": 844, "mobile": True}
DESKTOP = {"width": 1280, "height": 800, "mobile": False}
DISPLAY = "'The Placeholders - Synthetic Test Song'"

# What the line and the list show: the line's words, its icons (each a glyph and its count) and what names them for a
# screen reader, the list's rows and each kept version's link.
SEEN = """(() => {
  const q = (s) => document.querySelector(s);
  const shown = (el) => Boolean(el) && !el.closest('[hidden]') && el.getClientRects().length > 0;
  const rows = [...document.querySelectorAll('#ver-items > li')].map((li) => {
    const main = li.querySelector('.ver-main');
    return {text: main.textContent, link: main.tagName === 'A' ? main.getAttribute('href') : null,
            current: main.getAttribute('aria-current'),
            actions: [...li.querySelectorAll('.ver-acts a, .ver-acts button')].map((a) =>
              [a.textContent, a.getAttribute('href')])};
  });
  const glyph = (kind) => (kind.querySelector('svg').getAttribute('class').match(/glyph-(\\w+)/) || [])[1];
  return {nav: shown(q('#versions')), line: q('#ver-line').textContent,
          icons: [...document.querySelectorAll('#kinds .kind')].map((k) => [glyph(k), k.querySelector('.n').textContent]),
          said: [...document.querySelectorAll('#kinds .vh')].map((s) => s.textContent),
          steppers: document.querySelectorAll('#ver-prev, #ver-next, .vstep').length,
          links: Object.fromEntries([...document.querySelectorAll('#version-list a[data-page]')].map((a) =>
            [a.dataset.page, a.getAttribute('href')])),
          list: shown(q('#version-list')), title: q('#version-list-title').textContent, rows,
          acts: [...document.querySelectorAll('#ver-acts a, #ver-acts button')].map((a) =>
            [a.textContent, a.getAttribute('href')]),
          sideways: document.documentElement.scrollWidth > innerWidth};
})()"""

# How each of the line's icons is drawn: the icon's own attributes, its glyph's, its glyph's painted fill and its size.
DRAWN = """[...document.querySelectorAll('#kinds .kind')].map((k) => {
  const svg = k.querySelector('svg');
  const r = svg.getBoundingClientRect();
  return {hidden: k.getAttribute('aria-hidden'),
          svg: Object.fromEntries(['viewBox', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
                                   'aria-hidden'].map((a) => [a, svg.getAttribute(a)])),
          painted: getComputedStyle(svg).fill, size: [r.width, r.height]};
})"""


# The list's groups, a kind each: its kind, its heading's words (its name and its count) and each row's name, address,
# the name it downloads under and whether it is this page.
GROUPS = """[...document.querySelectorAll('#kind-groups .kind-group')].map((g) =>
  [g.dataset.kind, g.querySelector('.kind-head').textContent, [...g.querySelectorAll('.ver-main')].map((m) =>
    [m.textContent, m.getAttribute('href'), m.getAttribute('download'), m.getAttribute('aria-current')])])"""
# How the list's own parts are drawn: each heading's glyph, the tick before this page's row, where the actions sit.
PARTS = """(() => {
  const glyph = (svg) => svg && (svg.getAttribute('class').match(/glyph-(\\w+)/) || [])[1];
  const mine = document.querySelector('#version-list [aria-current]');
  return {heads: [...document.querySelectorAll('#kind-groups .kind-head')].map((h) => glyph(h.querySelector('svg'))),
          tick: mine && mine.firstElementChild.tagName === 'svg' ? glyph(mine.firstElementChild) : null,
          acts: Boolean(document.querySelector('#kind-groups > .kind-group:first-child > #ver-acts + ol#ver-items')),
          title: document.querySelector('#version-list-title').textContent};
})()"""


def seen(b: Browser) -> dict:
    return b.js(SEEN)


def open_list(b: Browser) -> None:
    b.click("#ver-now")
    assert b.wait("!document.querySelector('#version-list').hidden")


@contextmanager
def served(root: Path):
    """``root``'s files over HTTP on 127.0.0.1, each viewer with the policy and sandbox caracole serve gives it."""
    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = root / urlsplit(self.path).path.lstrip("/")
            if not path.is_file():
                self.send_error(404)
                return
            page = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", viewer_csp(page))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


# --- the line ----------------------------------------------------------------------------------------------


@in_chromium
def test_the_line_names_the_kind_the_version_and_its_rating(tmp_path):
    pages = folder(tmp_path, WONDERWALL, kinds=KINDS)
    others = {}
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        one = seen(b)
        drawn = b.js(DRAWN)
        for name in ("version-39144.html", "version-2161290.html"):
            b.open(pages[name].as_uri())
            assert b.wait("document.documentElement.dataset.ready === '1'")
            others[name] = seen(b)
    assert one["nav"] and one["line"] == "Chords · Ver 3 of 13 · ★ 4.86 (408)"  # no "the one" on the line
    assert others["version-39144.html"]["line"] == "Chords · Ver 1 of 13 · ★ 4.85 (12,629)"
    assert others["version-2161290.html"]["line"] == "Chords · Ver 7 of 13 · acoustic · ★ 4.80 (1,204)"
    for shown in (one, *others.values()):
        assert shown["icons"] == [["sheet", "13"], ["guitar", "2"], ["harmonica", "1"]]
        assert shown["said"] == ["13 chord versions, 2 Guitar Pro files, 1 harmonica tab"]
        assert shown["steppers"] == 0  # no ‹ › any more: the list opens each kept version
    # Each icon drawn as the library's glyphs are, a stroke in the text's colour on a 24-unit grid, unheard: the
    # words beside them name them.
    assert drawn == [{"hidden": "true", "svg": {"viewBox": "0 0 24 24", "fill": "none", "stroke": "currentColor",
                                                "stroke-width": "1.8", "stroke-linecap": "round",
                                                "stroke-linejoin": "round", "aria-hidden": "true"},
                      "painted": "none", "size": [16, 16]}] * 3


@in_chromium
def test_a_tap_on_the_line_the_back_arrow_or_a_version_leaves_no_highlight(tmp_path):
    # A phone's browser paints a tapped link or button blue until the next tap: the version line, the header's ‹ and
    # a kept version's row take none, as the bar's buttons, the chords and the rail don't.
    pages = folder(tmp_path, WONDERWALL, kinds=KINDS)
    with viewer(tmp_path, pages["version-39144.html"].as_uri(), **PHONE) as b:
        open_list(b)
        painted = b.js("['#ver-now', '.head .back', 'a.ver-main'].map((s) =>"
                       " [s, getComputedStyle(document.querySelector(s)).webkitTapHighlightColor])")
    assert painted == [["#ver-now", "rgba(0, 0, 0, 0)"], [".head .back", "rgba(0, 0, 0, 0)"],
                       ["a.ver-main", "rgba(0, 0, 0, 0)"]]


@in_chromium
def test_one_version_and_one_kind_is_no_ver_1_of_1_and_one_icon(tmp_path):
    one = {"total": 1, "sheet": "ug",
           "list": [entry("1064463", 3, 4.86, 408, 1, kept=True, chosen=True, page="sheet.html")]}
    unrated = deepcopy(one)
    unrated["list"][0].update(rating=None, votes=None)
    alone = {"sheet": "sheet", "page": "sheet.html", "groups": []}
    shown = {}
    for name, versions in (("rated", one), ("unrated", unrated)):
        pages = folder(tmp_path / name, versions, kinds=alone)
        with viewer(tmp_path / name, pages["sheet.html"].as_uri()) as b:
            shown[name] = seen(b)
    assert shown["rated"]["nav"] and shown["rated"]["line"] == "Chords · ★ 4.86 (408)"
    assert shown["unrated"]["line"] == "Chords · New"
    assert shown["rated"]["icons"] == shown["unrated"]["icons"] == [["sheet", "1"]]
    assert shown["rated"]["said"] == ["1 chord version"]


@in_chromium
def test_a_lacuerda_sheet_says_so(tmp_path):
    # Review Focus 3: the song's sheet is LaCuerda's: no UG version is chosen, and the line says so.
    versions = deepcopy(WONDERWALL)
    versions["list"][0].update(chosen=False, page="version-1064463.html")
    versions["sheet"] = "lacuerda"
    pages = folder(tmp_path, versions, kinds=KINDS)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        sheet = seen(b)
        open_list(b)
        listed = seen(b)
        b.open(pages["version-1064463.html"].as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        version = seen(b)
    assert sheet["line"] == "Chords · LaCuerda's sheet"
    assert sheet["icons"] == [["sheet", "13"], ["guitar", "2"], ["harmonica", "1"]]
    assert sheet["links"]["version-1064463.html"] == "version-1064463.html"
    assert listed["rows"][0]["text"].startswith("LaCuerda's sheet") and "the one" in listed["rows"][0]["text"]
    assert listed["rows"][0]["current"] == "page"
    assert version["line"] == "Chords · Ver 3 of 13 · ★ 4.86 (408)" and version["links"]["sheet.html"] == "sheet.html"


@in_chromium
def test_a_ukulele_sheet_is_ukulele_chords(tmp_path):
    # UG's Ukulele Chords, the song's sheet where UG has no chords for it (render.py's kinds' "ukulele").
    pages = folder(tmp_path, WONDERWALL, kinds={**KINDS, "sheet": "ukulele"})
    with viewer(tmp_path, pages["version-39144.html"].as_uri()) as b:
        shown = seen(b)
    assert shown["line"] == "Ukulele chords · Ver 1 of 13 · ★ 4.85 (12,629)"
    assert shown["icons"] == [["ukulele", "13"], ["guitar", "2"], ["harmonica", "1"]]
    assert shown["said"] == ["13 ukulele chord versions, 2 Guitar Pro files, 1 harmonica tab"]


@in_chromium
def test_the_text_size_goes_along_to_the_next_version(tmp_path):
    # Served, a viewer keeps its text size in its address alone: the next version opens at the same size.
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["sheet.html"].as_uri() + "#t=2&fs=24") as b:
        shown = seen(b)
    assert shown["links"]["version-39144.html"] == "version-39144.html#fs=24"  # the size, not the key: other chords


@in_chromium
def test_the_rail_of_necks_hidden_stays_hidden_on_the_next_version(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["sheet.html"].as_uri() + "#fs=24&necks=0") as b:
        shown = seen(b)
    assert shown["links"]["version-39144.html"] == "version-39144.html#fs=24&necks=0"


@in_chromium
def test_an_auto_sheet_standing_alone_is_the_one(tmp_path):
    # UG's versions kept beside an auto sheet the title opens (render.py's ``sheet``: "auto").
    versions = deepcopy(WONDERWALL)
    versions["list"][0].update(chosen=False, page="version-1064463.html")
    versions["sheet"] = "auto"
    pages = folder(tmp_path, versions, pages=("sheet (auto).html", "version-1064463.html"))
    with viewer(tmp_path, pages["version-1064463.html"].as_uri()) as b:
        open_list(b)
        listed = seen(b)
        b.open(pages["sheet (auto).html"].as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        auto = seen(b)
    assert listed["links"]["sheet (auto).html"] == "sheet%20(auto).html"
    assert listed["rows"][0]["link"] == "sheet%20(auto).html" and "the auto sheet" in listed["rows"][0]["text"]
    assert auto["line"] == "Chords · the auto sheet"
    assert auto["links"]["version-1064463.html"] == "version-1064463.html"


@in_chromium
def test_a_version_whose_text_is_the_sheets_opens_the_sheet(tmp_path):
    # Review Focus 1: a version with the sheet's very text is kept, and opens sheet.html; on sheet.html the
    # page is the one's, not the copy's.
    versions = deepcopy(WONDERWALL)
    versions["list"][1].update(page="sheet.html")
    pages = folder(tmp_path, versions)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        open_list(b)
        shown = seen(b)
    assert shown["line"] == "Chords · Ver 3 of 13 · ★ 4.86 (408)"
    assert shown["rows"][0]["current"] == "page" and shown["rows"][1]["link"] == "sheet.html"
    assert "kept" in shown["rows"][1]["text"]


@in_chromium
def test_without_versions_or_other_kinds_there_is_no_line(tmp_path):
    nothing = {"sheet": "sheet", "page": "sheet.html", "groups": []}
    cases = ((None, None), ({"total": 0, "list": []}, None), (None, nothing), ({"total": 0, "list": []}, nothing))
    for n, (versions, kinds) in enumerate(cases):
        pages = folder(tmp_path / str(n), versions, kinds=kinds)
        with viewer(tmp_path / str(n), pages["sheet.html"].as_uri()) as b:
            shown = seen(b)
            b.click("#more")  # the settings work as ever
            assert b.wait("!document.querySelector('#panel').hidden")
        assert not shown["nav"] and not shown["list"], (versions, kinds)
    # A song with no versions that keeps more than this page: the line, its kind alone, and its icons.
    pages = folder(tmp_path / "more", None, kinds=KINDS)
    with viewer(tmp_path / "more", pages["sheet.html"].as_uri()) as b:
        more = seen(b)
    assert more["nav"] and more["line"] == "Chords"
    assert more["icons"] == [["sheet", "1"], ["guitar", "2"], ["harmonica", "1"]]
    assert more["said"] == ["1 chord version, 2 Guitar Pro files, 1 harmonica tab"]


def test_the_songbook_has_no_line():
    book = build_songbook("Set", [BookSong("Synthetic Test Song", "The Placeholders", CHO)])
    assert 'id="versions"' not in book and 'id="version-list"' not in book
    assert 'id="versions"' in build_viewer(CHO) and 'id="version-list"' in build_viewer(CHO)
    kinds = f"<script>{page._kinds()}</script>"
    assert kinds in build_viewer(CHO) and kinds not in book  # kinds.js is a sheet page's, never a songbook's


# --- the icons are the library's ------------------------------------------------------------------------------

LIBRARY = page.HERE.parent / "library_assets"
# The page that holds kinds.js's copies to the library's: rows.js's glyphs (an <svg> of paths, or a <use> of the
# sprite's #glyph-NAME symbol where rows.js comes to draw one) against kinds.js's GLYPHS, and the line's icons as
# kinds.js draws them (each kind of render.py's _kinds_data once) against rows.js's drawing of the same glyph.
COMPARE = """(() => {
  const rows = caracoleRows({});
  const paths = (svg) => {
    const use = svg.querySelector("use");
    const from = use ? document.querySelector(use.getAttribute("href") || use.getAttribute("xlink:href")) : svg;
    return from ? [...from.querySelectorAll("path")].map((p) => p.getAttribute("d")) : null;
  };
  const drawing = (svg) => Object.fromEntries(svg.getAttributeNames().filter((a) => a !== "class").sort()
    .map((a) => [a, svg.getAttribute(a)]));
  const names = Object.keys(caracoleKinds.GLYPHS);
  const groups = KINDS.map((kind) => ({kind, items: [{name: kind + "-1.txt", label: kind}]}));
  caracoleKinds.attach({data: {kinds: {sheet: "sheet", page: "sheet.html", groups}}, here: "sheet.html",
    served: false, sheetPath: "Artist/Title/sheet.html", carry: (p) => p, open() {}, close() {}, inSight: () => false});
  document.documentElement.dataset.result = JSON.stringify({
    glyphs: names.map((n) => [n, caracoleKinds.GLYPHS[n], paths(rows.glyph(n))]),
    drawn: [...document.querySelectorAll("#kinds .kind")].map((k) => {
      const svg = k.querySelector("svg");
      const theirs = rows.glyph(caracoleKinds.GLYPH_OF[k.dataset.kind]);
      return [k.dataset.kind, paths(svg), paths(theirs), drawing(svg), drawing(theirs)];
    }),
    glyphOf: caracoleKinds.GLYPH_OF,
    frozen: Object.isFrozen(caracoleKinds) && Object.isFrozen(caracoleKinds.GLYPHS)
      && Object.isFrozen(caracoleKinds.GLYPH_OF) && names.every((n) => Object.isFrozen(caracoleKinds.GLYPHS[n])),
  });
})();"""


def card_glyphs() -> dict[str, str]:
    """Each kind's glyph as library_assets/card.js's ``things`` name it (``kind: "guitar", glyph: "guitar"``), the
    chord sheet's ``ukulele ? "ukulele" : "sheet"`` as both kinds of sheet."""
    source = (LIBRARY / "card.js").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for kind, glyph, either in re.findall(r'kind: "(\w+)", glyph: (?:"(\w+)"|(ukulele \? "ukulele" : "sheet"))',
                                          source):
        found.update({"sheet": "sheet", "ukulele": "ukulele"} if either else {kind: glyph})
    assert {"sheet", "ukulele", "guitar"} <= set(found), "card.js's things no longer read as kind and glyph pairs"
    return found


@in_chromium
def test_the_kind_icons_are_the_library_cards_drawings(tmp_path):
    # kinds.js holds a copy of the library's glyphs (rows.js's, which the sheet pages don't inline) and of the glyph
    # card.js's things draw each kind with: a glyph the library redraws, or a kind it draws otherwise, fails here, and
    # kinds.js follows it.
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"></head><body>\n" + page._VERSIONS + page._VERSION_LIST
            + f"<script>{(LIBRARY / 'rows.js').read_text(encoding='utf-8')}</script>\n"
            + f"<script>{page._kinds()}</script>\n"
            + f"<script>const KINDS = {json.dumps(list(render._KINDS))};\n{COMPARE}</script>\n</body></html>\n")
    path = tmp_path / "glyphs.html"
    path.write_text(html, encoding="utf-8")
    with Browser(tmp_path / "profile") as b:
        b.open(path.as_uri())
        assert b.wait("document.documentElement.dataset.result !== undefined")
        result = json.loads(b.js("document.documentElement.dataset.result"))
    # the card's five, and the tick before this page's row in the list
    assert sorted(name for name, *_ in result["glyphs"]) == ["check", "guitar", "harmonica", "score", "sheet", "ukulele"]
    for name, mine, theirs in result["glyphs"]:
        assert mine == theirs, f"kinds.js's {name} glyph is not rows.js's: copy rows.js's into kinds.js's GLYPHS"
    assert [kind for kind, *_ in result["drawn"]] == ["sheet", *render._KINDS]
    for kind, mine, theirs, drawn, drawing in result["drawn"]:
        assert mine == theirs and drawn == drawing, kind  # rows.js's paths, drawn as rows.js draws them
    card = card_glyphs()
    for kind in ("sheet", "ukulele", *render._KINDS):
        assert result["glyphOf"][kind] == card[kind], kind  # tab and gametab the guitar's, as on the card
    assert set(result["glyphOf"].values()) == {name for name, *_ in result["glyphs"]} - {"check"}
    assert result["frozen"]
    for word in ("innerHTML", "fetch(", "XMLHttpRequest", "import(", "eval(", "new Function"):
        assert word not in page._kinds(), word


# --- the list of every version -------------------------------------------------------------------


@in_chromium
def test_the_list_shows_every_version_and_opens_the_kept_ones(tmp_path):
    versions = deepcopy(WONDERWALL)
    versions["list"][3].update(rating=None, votes=None)  # UG hasn't rated it yet
    pages = folder(tmp_path, versions)
    with viewer(tmp_path, pages["version-39144.html"].as_uri()) as b:
        open_list(b)
        shown = seen(b)
        focus = b.js("document.activeElement.id")
        b.click("#ver-items > li:first-child .ver-main")
        assert b.wait("location.pathname.endsWith('/sheet.html') && document.documentElement.dataset.ready === '1'")
    rows = shown["rows"]
    assert shown["title"] == "Versions" and len(rows) == 13 and focus == "version-list-title"
    assert rows[0]["link"] == "sheet.html" and "Ver 3" in rows[0]["text"] and "★ 4.86 (408)" in rows[0]["text"]
    assert "the one" in rows[0]["text"] and "the version that oasis play on Wembley 2008" in rows[0]["text"]
    assert rows[1]["link"] is None and rows[1]["current"] == "page" and "this page" in rows[1]["text"]
    assert "★ 4.85 (12,629)" in rows[1]["text"]
    assert rows[2]["link"] == "version-2161290.html" and "kept" in rows[2]["text"] and "acoustic" in rows[2]["text"]
    assert rows[3]["link"] is None and "kept" not in rows[3]["text"] and rows[3]["text"].startswith("Ver 4 · New")
    assert "capo 2, easy chords" in rows[4]["text"]


@in_chromium
def test_a_version_with_no_votes_is_new_as_the_library_card_says_it(tmp_path):
    versions = deepcopy(WONDERWALL)
    rows = versions["list"]
    rows[3].update(rating=0, votes=0)  # UG's unrated tab
    rows[4].update(rating=4.5, votes=0)  # a rating with no votes
    rows[5].update(rating=4.85, votes="81")  # votes as a string
    rows[6].pop("rating")  # no rating at all
    pages = folder(tmp_path, versions)
    with viewer(tmp_path, pages["version-39144.html"].as_uri()) as b:
        open_list(b)
        shown = seen(b)["rows"]
    assert shown[3]["text"].startswith("Ver 4 · New") and "0.00" not in shown[3]["text"]
    assert shown[4]["text"].startswith("Ver 5 · New")
    assert shown[5]["text"].startswith("Ver 6 · ★ 4.85 (81)")
    assert shown[6]["text"].startswith("Ver 7 · New")


@in_chromium
def test_the_list_groups_every_kind_in_the_cards_order(tmp_path):
    # Chords, today's versions, then a group for each other kind the song keeps, the library card's, in its order: each
    # row named as the card names it, a tap from the list. From a file, a Guitar Pro file is the file itself, saved
    # under the song's name; a harmonica tab opens its page, with the reader's choices for the screen.
    pages = folder(tmp_path, WONDERWALL, kinds=EVERY_KIND)
    with viewer(tmp_path, pages["version-39144.html"].as_uri(), **DESKTOP) as b:
        groups = b.js(GROUPS)
        parts = b.js(PARTS)
        rows = seen(b)["rows"]
        b.click("#necks-toggle")  # the rail of necks hidden: the harmonica tab's page opens without it too
        assert b.wait("location.hash.includes('necks=0')")
        later = b.js(GROUPS)
    assert [kind for kind, *_ in groups] == ["sheet", "guitar", "tab", "harmonica", "gametab", "score"]
    assert [head for _, head, _ in groups] == ["Chords13", "Guitar Pro2", "Guitar tab1", "Harmonica1", "Game music1",
                                               "Score2"]
    assert parts == {"heads": ["sheet", "guitar", "guitar", "harmonica", "guitar", "score"], "tick": "check",
                     "acts": True, "title": "Versions"}
    chords = groups[0][2]
    assert len(chords) == len(rows) == 13  # today's rows, #ver-items' own
    assert chords[1][1:] == [None, None, "page"] and chords[1][0].startswith("Ver 1 · ★ 4.85 (12,629)")
    assert chords[0][1] == "sheet.html" and chords[2][1] == "version-2161290.html"
    assert {kind: items for kind, _, items in groups[1:]} == {
        "guitar": [["Guitar Pro 1 · gtptabs", "guitar-1.gp5", "Artist - Title.gp5", None],
                   ["Power Tab 2", "guitar-2.ptb", "Artist - Title (2).ptb", None]],
        "tab": [["Guitar tab · UG", "tab.txt", None, None]],
        "harmonica": [["Harmonica tab 1 · harptabs", "harmonica-1.html", None, None]],
        "gametab": [["Game music tab 1 · gametabs", "gametab-1.txt", None, None]],
        "score": [["Score 1 (MuseScore)", "score-1.mscz", "Artist - Title.mscz", None],
                  ["Score 1 (PDF)", "score-1.pdf", None, None]]}
    assert later[3][2] == [["Harmonica tab 1 · harptabs", "harmonica-1.html#necks=0", None, None]]
    assert later[1][2] == groups[1][2]  # a file is the file, whatever the screen


@in_chromium
def test_served_guitar_pro_opens_in_the_browser_and_versions_keep_through_caracole_serve(tmp_path):
    # Served, a Guitar Pro file caracole serve draws opens its Guitar Pro page (/guitar?file=…, "in the browser"), as
    # the settings' row does; a Power Tab file is still a download; Keep is caracole serve's /versions page, as ever.
    folder(tmp_path, WONDERWALL, kinds=EVERY_KIND)
    with served(tmp_path) as root, viewer(tmp_path, root + "/Artist/Title/sheet.html") as b:
        groups = {kind: items for kind, _, items in b.js(GROUPS)}
        keep = seen(b)["rows"][3]["actions"]
    assert groups["guitar"] == [
        ["Guitar Pro 1 · gtptabs · in the browser", "/guitar?file=Artist%2FTitle%2Fguitar-1.gp5", None, None],
        ["Power Tab 2", "guitar-2.ptb", "Artist - Title (2).ptb", None]]
    assert groups["harmonica"] == [["Harmonica tab 1 · harptabs", "harmonica-1.html", None, None]]
    assert groups["score"][0][1:3] == ["score-1.mscz", "Artist - Title.mscz"]
    assert keep == [["Keep", "/versions?sheet=Artist%2FTitle%2Fsheet.html&tab=504&do=keep"]]


@in_chromium
def test_a_song_with_no_versions_lists_its_sheet_and_its_other_kinds(tmp_path):
    # UG lists no chords version of the song: its Chords group is its chord sheet alone, a row, then its other kinds.
    # On the sheet's page that row is this page's; on another page of the song (a harmonica tab's, say) it opens the
    # sheet, and that page's own row is ticked in its group.
    pages = folder(tmp_path, None, kinds=EVERY_KIND, pages=("sheet.html", "harmonica-1.html"))
    shown = {}
    for name in pages:
        with viewer(tmp_path, pages[name].as_uri() + "#fs=24") as b:
            open_list(b)
            shown[name] = [b.js(GROUPS), b.js(PARTS)]
    ukulele = folder(tmp_path / "ukulele", None, kinds={**EVERY_KIND, "sheet": "ukulele"})
    with viewer(tmp_path / "ukulele", ukulele["sheet.html"].as_uri()) as b:
        uke = b.js(GROUPS)
    sheet, parts = shown["sheet.html"]
    assert [head for _, head, _ in sheet] == ["Chords1", "Guitar Pro2", "Guitar tab1", "Harmonica1", "Game music1",
                                              "Score2"]
    assert sheet[0] == ["sheet", "Chords1", [["Chord sheet · this page", None, None, "page"]]]
    assert parts["tick"] == "check" and parts["acts"] and parts["title"] == "Versions"
    assert sheet[3][2] == [["Harmonica tab 1 · harptabs", "harmonica-1.html#fs=24", None, None]]
    harp, parts = shown["harmonica-1.html"]
    assert harp[0][2] == [["Chord sheet", "sheet.html#fs=24", None, None]]
    assert harp[3][2] == [["Harmonica tab 1 · harptabs · this page", None, None, "page"]] and parts["tick"] == "check"
    assert uke[0] == ["ukulele", "Ukulele chords1", [["Ukulele chords · this page", None, None, "page"]]]


@in_chromium
def test_from_a_file_a_version_not_kept_links_to_ug_and_shows_the_command_that_keeps_it(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        open_list(b)
        actions = seen(b)["rows"][3]["actions"]
        b.click("#ver-items > li:nth-child(4) .ver-acts button")
        assert b.wait("document.querySelector('#ver-items > li:nth-child(4) .cmd') !== null")
        cmd = b.js("document.querySelector('#ver-items > li:nth-child(4) .cmd').textContent")
        copy = b.js("(() => { const r = document.querySelector('#ver-items > li:nth-child(4) .vcmd button')"
                    ".getBoundingClientRect(); return [r.width, r.height]; })()")
    assert actions == [["On UG", WONDERWALL["list"][3]["url"]], ["Keep", None]]
    assert cmd == f"caracole versions {DISPLAY} --keep 504"
    assert min(copy) >= 44


@in_chromium
def test_a_gone_version_is_listed_but_opens_nothing(tmp_path):
    # Review Focus 5: gone from UG, kept or not, it is no link and offers nothing to do.
    versions = deepcopy(WONDERWALL)
    versions["list"][2]["gone"] = True  # a kept one gone too: its page stays until the next fetch drops it
    pages = folder(tmp_path, versions)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        open_list(b)
        shown = seen(b)
    for row in (shown["rows"][2], shown["rows"][8]):
        assert row["link"] is None and row["actions"] == [] and "gone from UG" in row["text"]
    assert list(shown["links"]) == ["version-39144.html"]  # the gone one opens nothing, kept or not
    with viewer(tmp_path, pages["version-39144.html"].as_uri()) as b:
        assert list(seen(b)["links"]) == ["sheet.html"]


@in_chromium
def test_from_a_file_a_version_shows_the_command_that_makes_it_the_one(tmp_path):
    versions = deepcopy(WONDERWALL)
    pages = folder(tmp_path, versions)
    with viewer(tmp_path, pages["version-39144.html"].as_uri()) as b:
        open_list(b)
        acts = seen(b)["acts"]
        b.click("#ver-acts button")
        assert b.wait("document.querySelector('#ver-acts .cmd') !== null")
        cmd = b.js("document.querySelector('#ver-acts .cmd').textContent")
        hint = b.js("document.querySelector('#ver-acts .hint').textContent")
    assert acts == [["Make this the one", None]]
    assert cmd == f"caracole versions {DISPLAY} --choose 39144"
    assert "caracole is installed" in hint
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        open_list(b)
        assert seen(b)["acts"] == []  # the one already, and caracole's pick: nothing to do


@in_chromium
def test_a_version_you_chose_offers_caracoles_pick_back(tmp_path):
    # Your choice (a pin) is the one but not the first in rank order: the way back to caracole's pick.
    versions = deepcopy(WONDERWALL)
    versions["list"][0].update(chosen=False, page="version-1064463.html")
    versions["list"][5].update(chosen=True, kept=True, page="sheet.html")
    pages = folder(tmp_path, versions)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        shown = seen(b)
        b.click("#ver-now")
        assert b.wait("!document.querySelector('#version-list').hidden")
        b.click("#ver-acts button")
        assert b.wait("document.querySelector('#ver-acts .cmd') !== null")
        cmd = b.js("document.querySelector('#ver-acts .cmd').textContent")
    assert shown["line"] == "Chords · Ver 6 of 13 · ★ 4.58 (180)"
    assert shown["acts"] == [["Back to our pick", None]]
    assert cmd == f"caracole versions {DISPLAY} --clear"


@in_chromium
def test_the_way_back_to_caracoles_pick_is_offered_while_a_pin_chooses_the_sheet(tmp_path):
    # The data says whether a [pin] of yours chooses the sheet (render.py: the pin caracole versions --clear takes
    # out): offered then, wherever your version ranks, and never without one, wherever the one ranks.
    pinned = deepcopy(WONDERWALL)  # your pin, which ranks first
    pinned["pinned"] = True
    loose = deepcopy(WONDERWALL)  # no pin, the one not first: the first's page failed to parse, say
    loose["pinned"] = False
    loose["list"][0].update(chosen=False, page=None, kept=False)
    loose["list"][1].update(chosen=True, page="sheet.html")
    seen_acts = {}
    for name, versions in (("pinned", pinned), ("loose", loose)):
        pages = folder(tmp_path / name, versions)
        with viewer(tmp_path / name, pages["sheet.html"].as_uri()) as b:
            open_list(b)
            seen_acts[name] = seen(b)["acts"]
    assert seen_acts == {"pinned": [["Back to our pick", None]], "loose": []}


@in_chromium
def test_served_the_list_links_to_caracole_serves_versions_page(tmp_path):
    versions = deepcopy(WONDERWALL)
    versions["list"][0].update(chosen=False, page="version-1064463.html")
    versions["list"][5].update(chosen=True, kept=True, page="sheet.html")
    folder(tmp_path, versions)
    with served(tmp_path) as root, viewer(tmp_path, root + "/Artist/Title/version-39144.html") as b:
        open_list(b)
        shown = seen(b)
        sandboxed = b.js("(() => { try { localStorage.length; return false; } catch (e) { return true; } })()")
        b.click("#ver-items > li:nth-child(3) .ver-main")
        assert b.wait("location.pathname === '/Artist/Title/version-2161290.html'"
                      " && document.documentElement.dataset.ready === '1'")

    def query(href):
        parts = urlsplit(href)
        return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}

    assert sandboxed  # the policy's sandbox: no storage
    make, back = shown["acts"]
    assert make[0] == "Make this the one" and query(make[1]) == (
        "/versions", {"sheet": "Artist/Title/version-39144.html", "tab": "39144", "do": "choose"})
    assert back[0] == "Back to our pick" and query(back[1]) == (
        "/versions", {"sheet": "Artist/Title/version-39144.html", "do": "clear"})
    keep = shown["rows"][3]["actions"]
    assert len(keep) == 1 and keep[0][0] == "Keep" and query(keep[0][1]) == (
        "/versions", {"sheet": "Artist/Title/version-39144.html", "tab": "504", "do": "keep"})
    assert shown["rows"][8]["actions"] == []  # gone


# --- the list's place, on a phone and a laptop -----------------------------------------------------


# Where the list is, and how it is drawn: its box and the version line's, the bar's top, its position and its edges,
# the song's column and whether a rail is open beside the song (html's data-panel).
PLACED = """(() => {
  const list = document.querySelector('#version-list'), s = getComputedStyle(list);
  const r = list.getBoundingClientRect(), now = document.querySelector('#ver-now').getBoundingClientRect();
  const bar = document.querySelector('#bar').getBoundingClientRect();
  const sheet = document.querySelector('#sheet').getBoundingClientRect();
  return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height,
          under: r.top - now.bottom, from: r.left - now.left, barTop: bar.top, position: s.position,
          edges: [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth],
          radius: s.borderBottomLeftRadius, column: [sheet.left, sheet.width],
          panel: document.documentElement.dataset.panel || null, depth: (history.state || {}).caracoleLayer || 0};
})()"""


def history_at(b: Browser, want: tuple[int, int]) -> tuple[int, int]:
    """The tab's history (``entries``) once it is ``want``, or as it is 10 s on: the browser hears of an entry the page
    pushed, or of a step it took, a moment after."""
    deadline = time.monotonic() + 10
    found = entries(b)
    while found != want and time.monotonic() < deadline:
        time.sleep(0.03)
        found = entries(b)
    return found


@in_chromium
@pytest.mark.parametrize("width", [390, 320])
def test_on_a_phone_the_list_is_a_sheet_from_the_bottom_and_back_closes_it(tmp_path, width):
    versions = deepcopy(WONDERWALL)
    versions["list"][1]["note"] = "a tabber's note that runs on " * 12
    pages = folder(tmp_path, versions, kinds=EVERY_KIND)
    with viewer(tmp_path, pages["version-39144.html"].as_uri(), **{**PHONE, "width": width}) as b:
        closed = seen(b)
        small_switcher = b.js(small_targets("#version-list *, .bar *, .foot *, .head .back, .sheet *"))
        open_list(b)
        assert b.wait("(history.state || {}).caracoleLayer === 1")
        shown = seen(b)
        box = b.js(PLACED)
        small = b.js(small_targets(":not(#version-list):not(#version-list *)"))
        opened = history_at(b, (2, 3))
        back(b)
        assert b.wait("document.querySelector('#version-list').hidden")
        after = history_at(b, (1, 3))
        assert b.wait("document.activeElement === document.querySelector('#ver-now')")
    assert not closed["sideways"] and not shown["sideways"]
    assert small_switcher == [] and small == []
    # Fixed at the foot, docked on the bar, the screen's width and at most 45 % of its height.
    assert box["position"] == "fixed" and abs(box["bottom"] - box["barTop"]) <= 1
    assert box["left"] >= 0 and box["right"] <= width and box["height"] <= 844 * 0.45 + 1
    assert opened == (2, 3) and after == (1, 3)  # one entry, and Back takes it off


@in_chromium
def test_on_a_laptop_the_list_is_a_popover_under_the_line(tmp_path):
    pages = folder(tmp_path, WONDERWALL, kinds=EVERY_KIND)
    with viewer(tmp_path, pages["sheet.html"].as_uri(), **{**DESKTOP, "height": 600}) as b:
        before = b.js(PLACED)
        open_list(b)
        alone = b.js(PLACED)
        b.js("scrollTo(0, 120)")
        assert b.wait("scrollY === 120")
        scrolled = b.js(PLACED)
        b.press("Escape")
        assert b.wait("document.querySelector('#version-list').hidden")
        b.js("scrollTo(0, 0)")
        b.click("#more")
        assert b.wait("!document.querySelector('#panel').hidden")
        open_list(b)
        assert b.wait("(history.state || {}).caracoleLayer === 2")
        beside = b.js(PLACED)
        at = history_at(b, (3, 4))
        back(b)
        assert b.wait("document.querySelector('#version-list').hidden")
        after = b.js("[document.querySelector('#panel').hidden, document.documentElement.dataset.panel,"
                     " document.querySelector('#ver-now').getAttribute('aria-expanded')]")
    # Under the line, 6 px below it, at its left, in the page: it scrolls with the page.
    assert alone["position"] == "absolute" and 6 <= alone["under"] <= 8 and abs(alone["from"]) <= 1
    assert alone["width"] == 380 and alone["height"] <= 600 * 0.6 + 1
    assert alone["edges"] == ["1px"] * 4 and alone["radius"] == "14px"
    assert alone["panel"] is None and alone["column"] == before["column"]  # no rail: the song's column unchanged
    assert 6 <= scrolled["under"] <= 8 and abs(scrolled["from"]) <= 1 and scrolled["top"] == alone["top"] - 120
    # Beside the settings' rail, which stays open: the list over it in the history, Back closing the list first.
    assert 6 <= beside["under"] <= 8 and abs(beside["from"]) <= 1 and beside["panel"] == "open"
    assert beside["right"] <= 1280 - 360 and at == (3, 4)  # the page, the settings, the list
    assert after == [False, "open", "false"]


# A song of a few lines, so that a window 500 px tall shows it whole and the page doesn't scroll: the popover's own
# scroll is the one way to its last row.
SHORT_CHO = "{title: Synthetic Test Song}\n{artist: The Placeholders}\n{key: G}\n[G]Tiny test [D]words\n"
# The list's last row and its head's close button, where they are and what is hit at the close button's middle.
ENDS = """(() => {
  const list = document.querySelector('#version-list'), rows = list.querySelectorAll('.ver');
  const last = rows[rows.length - 1].getBoundingClientRect(), x = list.querySelector('[data-close]');
  const r = x.getBoundingClientRect(), hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {last: last.bottom, x: r.top, hit: Boolean(hit) && x.contains(hit), scrolled: list.scrollTop,
          end: list.scrollHeight - list.clientHeight};
})()"""


def short_song(tmp_path: Path) -> Path:
    """sheet.html of SHORT_CHO under Artist/Title/, with every version and every kind."""
    where = tmp_path / "Artist" / "Title"
    where.mkdir(parents=True, exist_ok=True)
    path = where / "sheet.html"
    path.write_text(with_versions(build_viewer(SHORT_CHO), WONDERWALL, "sheet.html", EVERY_KIND), encoding="utf-8")
    return path


@in_chromium
def test_on_a_short_laptop_window_the_popover_ends_above_the_bar_and_its_head_stays_in_sight(tmp_path):
    # 1280 × 500: the bar (over the popover) would hide the list's last rows, and a short song gives the page no
    # scroll to bring them up: the popover ends above the bar, its own scroll reaching its last row, and its head, with
    # its ×, stays at its top as it scrolls.
    with viewer(tmp_path, short_song(tmp_path).as_uri(), **{**DESKTOP, "height": 500}) as b:
        open_list(b)
        box = b.js(PLACED)
        b.js("document.querySelector('#version-list').scrollTop = 1e6")
        assert b.wait("document.querySelector('#version-list').scrollTop > 0")
        end = b.js(ENDS)
        b.js("document.querySelector('#version-list [data-close]').click()")
        assert b.wait("document.querySelector('#version-list').hidden")
    # At the line's left: the line measured as it is once the popover is placed (unplaced, at the document's end, it
    # would give the page a scrollbar for a moment and shift the page's column under it)
    assert box["position"] == "absolute" and 6 <= box["under"] <= 8 and abs(box["from"]) <= 1, box
    assert box["bottom"] <= box["barTop"], box  # above the bar
    assert end["scrolled"] == end["end"] > 0  # the list scrolled to its end
    assert end["last"] <= box["bottom"] and end["last"] <= box["barTop"]  # its last row in sight, above the bar
    assert end["hit"] and box["top"] <= end["x"] <= box["top"] + 8  # the head kept at its top, its × pressable


@in_chromium
def test_the_popover_keeps_within_the_window_less_the_rails(tmp_path):
    # From 900 px wide the popover is under its line, at its left, and within the window less the rails beside the
    # song (the rail of necks on the left, the settings' on the right): 8 px from either, as wide as fits there.
    pages = folder(tmp_path, WONDERWALL, kinds=EVERY_KIND)
    found = {}
    with viewer(tmp_path, pages["sheet.html"].as_uri(), **DESKTOP) as b:
        # The line at the right of a page the whole window wide, the rail of necks on the left
        b.js("document.querySelector('.page').style.maxWidth = 'none'")
        b.js("document.querySelector('#versions').style.justifyContent = 'flex-end'")
        b.js("document.querySelector('#ver-now').style.maxWidth = '120px'")
        open_list(b)
        found["right"] = b.js(PLACED) | {"rail": b.js("document.querySelector('#necks').getBoundingClientRect().right")}
        b.press("Escape")
        assert b.wait("document.querySelector('#version-list').hidden")
        # A page narrower than the popover, at the right, beside the settings' rail at 960 px: never over the rail
        b.send("Emulation.setDeviceMetricsOverride", width=960, height=800, deviceScaleFactor=1, mobile=False)
        assert b.wait("innerWidth === 960")
        b.js("Object.assign(document.querySelector('.page').style, {maxWidth: '300px', marginRight: '0'})")
        b.click("#more")
        assert b.wait("!document.querySelector('#panel').hidden")
        open_list(b)
        found["rail"] = b.js(PLACED)
        # A rail that leaves less room than the popover's 380 px: the popover as wide as the room
        b.js("document.documentElement.style.setProperty('--rail', '600px')")
        b.click("#more")  # the settings closed and opened again: the list placed again beside the wider rail
        assert b.wait("document.querySelector('#panel').hidden")
        b.click("#more")
        assert b.wait("!document.querySelector('#panel').hidden")
        found["room"] = b.js(PLACED) | {"window": b.js("document.documentElement.clientWidth")}  # less its scrollbar
    right = found["right"]
    assert right["left"] >= right["rail"] + 8 and right["right"] <= 1280 - 8 and right["width"] == 380
    assert right["from"] < 0  # pulled in from the line's left, which would run it off the window
    rail = found["rail"]
    assert rail["panel"] == "open" and rail["left"] >= 8 and rail["right"] <= 960 - 360 - 8 and rail["width"] == 380
    room = found["room"]
    assert room["left"] >= 8 and room["right"] <= room["window"] - 600 - 8 and room["width"] == room["window"] - 600 - 16


@in_chromium
def test_on_a_laptop_escape_closes_the_list_and_the_focus_goes_back_to_its_line(tmp_path):
    pages = folder(tmp_path, WONDERWALL, kinds=EVERY_KIND)
    with viewer(tmp_path, pages["sheet.html"].as_uri(), **DESKTOP) as b:
        b.js("document.querySelector('#ver-now').focus()")
        b.press("Enter")
        assert b.wait("!document.querySelector('#version-list').hidden")
        opened = b.js("document.activeElement.id")
        b.press("Escape")
        assert b.wait("document.querySelector('#version-list').hidden")
        focus = b.js("document.activeElement.id")
        expanded = b.js("document.querySelector('#ver-now').getAttribute('aria-expanded')")
        depth = history_at(b, (1, 3))
    assert opened == "version-list-title" and focus == "ver-now" and expanded == "false"
    assert depth == (1, 3)  # its entry stepped off


@in_chromium
def test_the_list_open_across_900_px_docks_and_floats_again_with_one_entry(tmp_path):
    # Narrowed below 900 px with the list open, it docks on the bar, a sheet from the bottom; widened again, the
    # popover under its line: the same one layer, its one entry, all along; Back closes it.
    pages = folder(tmp_path, WONDERWALL, kinds=EVERY_KIND)
    with viewer(tmp_path, pages["sheet.html"].as_uri(), **DESKTOP) as b:
        open_list(b)
        wide = b.js(PLACED)
        at_wide = history_at(b, (2, 3))
        b.send("Emulation.setDeviceMetricsOverride", width=800, height=800, deviceScaleFactor=1, mobile=False)
        assert b.wait("innerWidth === 800 && document.documentElement.dataset.dock === 'version-list'")
        narrow = b.js(PLACED)
        at_narrow = history_at(b, (2, 3))
        b.send("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=1, mobile=False)
        assert b.wait("innerWidth === 1280 && !document.documentElement.dataset.dock")
        again = b.js(PLACED)
        at_again = history_at(b, (2, 3))
        back(b)
        assert b.wait("document.querySelector('#version-list').hidden")
        after = history_at(b, (1, 3))
    assert wide["position"] == "absolute" and 6 <= wide["under"] <= 8
    assert narrow["position"] == "fixed" and abs(narrow["bottom"] - narrow["barTop"]) <= 1 and narrow["depth"] == 1
    assert again["position"] == "absolute" and 6 <= again["under"] <= 8 and abs(again["from"]) <= 1
    assert again["depth"] == 1 and at_wide == at_narrow == at_again == (2, 3) and after == (1, 3)


# --- a harmonica tab's page ---------------------------------------------------------------------------------------

HARP_TAB = "4 -4 5 -5 6\nla la la la la\n"
# KINDS with two harmonica tabs, each with its page.
TWO_TABS: dict = {**KINDS, "groups": [KINDS["groups"][0], {"kind": "harmonica", "items": [
    {"name": "harmonica-1.txt", "label": "Harmonica tab 1 · harptabs", "page": "harmonica-1.html"},
    {"name": "harmonica-2.txt", "label": "Harmonica tab 2 · harptabs", "page": "harmonica-2.html"}]}]}
# A song with no sheet: a Guitar Pro file and two harmonica tabs.
NO_SHEET: dict = {"sheet": None, "page": None, "groups": [
    {"kind": "guitar", "items": [{"name": "guitar-1.gp5", "label": "Guitar Pro 1 · gtptabs", "browser": True,
                                  "download": "Artist - Title.gp5"}]},
    TWO_TABS["groups"][1]]}
# Every address and command the line and the list hold.
SAID = """[...document.querySelectorAll('#versions a, #version-list a')].map((a) => a.getAttribute('href'))
  .concat([...document.querySelectorAll('#version-list .cmd')].map((c) => c.textContent))"""


def harmonica_pages(tmp_path: Path, versions: dict | None, kinds: dict | None) -> dict[str, Path]:
    """Each harmonica tab's page of ``kinds`` under Artist/Title/, as render.py writes them: ``versions`` none of its
    own (every ``this`` false), and its ‹ the sheet's page, or the library's for a song with none."""
    where = tmp_path / "Artist" / "Title"
    where.mkdir(parents=True, exist_ok=True)
    listed = None if versions is None else {**versions, "list": [{**v, "this": False} for v in versions["list"]]}
    tabs = next((g["items"] for g in (kinds or {}).get("groups", []) if g["kind"] == "harmonica"), [])
    out = {}
    for item in tabs or [{"name": "harmonica-1.txt", "page": "harmonica-1.html"}]:
        html = build_harmonica_viewer(HARP_TAB, title="Synthetic Test Song", artist="The Placeholders",
                                      tab_file=item["name"], back=(kinds or {}).get("page"), versions=listed,
                                      kinds=kinds)
        (where / item["page"]).write_text(html, encoding="utf-8")
        out[item["page"]] = where / item["page"]
    return out


def thrown(b: Browser) -> list:
    return [e for e in b.events if e.get("method") == "Runtime.exceptionThrown"]


@in_chromium
def test_a_harmonica_page_has_the_line_and_the_list(tmp_path):
    # The song's line under the artist: its kind, Harmonica, and which of its tabs this is, then the icons the sheet's
    # line shows; its list as the sheet's, none of UG's versions this page, and this tab ticked in its group.
    folder(tmp_path, WONDERWALL, kinds=TWO_TABS)
    pages = harmonica_pages(tmp_path, WONDERWALL, TWO_TABS)
    with viewer(tmp_path, pages["harmonica-1.html"].as_uri() + "#necks=0&py=1") as b:
        line = seen(b)
        open_list(b)
        assert b.wait("(history.state || {}).caracoleLayer === 1")
        shown = seen(b)
        groups = b.js(GROUPS)
        focus = b.js("document.activeElement.id")
        opened = history_at(b, (2, 3))
        back(b)
        assert b.wait("document.querySelector('#version-list').hidden")
        after = history_at(b, (1, 3))
        refocused = b.js("document.activeElement.id")
        b.open(pages["harmonica-2.html"].as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        second = seen(b)
        errors = thrown(b)
    assert line["nav"] and line["line"] == "Harmonica · Tab 1 of 2" and second["line"] == "Harmonica · Tab 2 of 2"
    assert line["icons"] == [["sheet", "13"], ["guitar", "2"], ["harmonica", "2"]]
    assert line["said"] == ["13 chord versions, 2 Guitar Pro files, 2 harmonica tabs"]
    rows = shown["rows"]
    assert len(rows) == 13 and all(row["current"] is None for row in rows)  # none of UG's versions is this page
    assert [row["link"] for row in rows[:3]] == ["sheet.html#necks=0&py=1", "version-39144.html#necks=0&py=1",
                                                 "version-2161290.html#necks=0&py=1"]
    assert shown["acts"] == [] and focus == "version-list-title"
    assert groups[0][0] == "sheet" and groups[-1] == ["harmonica", "Harmonica2", [
        ["Harmonica tab 1 · harptabs · this page", None, None, "page"],
        ["Harmonica tab 2 · harptabs", "harmonica-2.html#necks=0&py=1", None, None]]]
    assert opened == (2, 3) and after == (1, 3) and refocused == "ver-now"
    assert errors == []


@in_chromium
def test_served_a_harmonica_page_keeps_a_version_through_caracole_serve_on_the_songs_sheet(tmp_path):
    folder(tmp_path, WONDERWALL, kinds=TWO_TABS)
    harmonica_pages(tmp_path, WONDERWALL, TWO_TABS)
    with served(tmp_path) as root, viewer(tmp_path, root + "/Artist/Title/harmonica-1.html") as b:
        open_list(b)
        keep = seen(b)["rows"][3]["actions"]
        guitar = {kind: items for kind, _, items in b.js(GROUPS)}["guitar"]
        b.click("#ver-items > li:first-child .ver-main")
        assert b.wait("location.pathname === '/Artist/Title/sheet.html'"
                      " && document.documentElement.dataset.ready === '1'")
    assert keep == [["Keep", "/versions?sheet=Artist%2FTitle%2Fsheet.html&tab=504&do=keep"]]
    assert guitar[0][1] == "/guitar?file=Artist%2FTitle%2Fguitar-1.gp5"  # the song's folder, from its sheet's


@in_chromium
def test_a_tab_with_no_sheet_and_nothing_else_has_no_line(tmp_path):
    alone = {"sheet": None, "page": None, "groups": [{"kind": "harmonica", "items": [
        {"name": "harmonica-1.txt", "label": "Harmonica tab 1 · harptabs", "page": "harmonica-1.html"}]}]}
    for n, kinds in enumerate((alone, None)):
        pages = harmonica_pages(tmp_path / str(n), None, kinds)
        with viewer(tmp_path / str(n), pages["harmonica-1.html"].as_uri()) as b:
            shown = seen(b)
            b.click("#size")  # the page works as ever
            assert b.wait("!document.querySelector('#sizes').hidden")
            errors = thrown(b)
        assert not shown["nav"] and not shown["list"] and errors == [], kinds


@in_chromium
def test_a_tab_of_a_song_with_no_sheet_lists_its_kinds_with_no_sheet_path(tmp_path):
    # No sheet (kinds' page null): the line and the list show the song's other kinds, and nothing they hold names a
    # sheet that isn't there, from a file or served; served, its Guitar Pro file still opens on caracole serve's
    # Guitar Pro page, the song's folder read from this page's own address.
    pages = harmonica_pages(tmp_path, None, NO_SHEET)
    found = {}
    with viewer(tmp_path, pages["harmonica-2.html"].as_uri()) as b:
        open_list(b)
        found["file"] = [seen(b), b.js(GROUPS), b.js(SAID), thrown(b)]
    with served(tmp_path) as root, viewer(tmp_path, root + "/Artist/Title/harmonica-2.html") as b:
        open_list(b)
        found["served"] = [seen(b), b.js(GROUPS), b.js(SAID), thrown(b)]
    for where, (shown, groups, said, errors) in found.items():
        assert shown["nav"] and shown["line"] == "Harmonica · Tab 2 of 2", where
        assert shown["icons"] == [["guitar", "1"], ["harmonica", "2"]] and shown["rows"] == [], where
        assert [kind for kind, *_ in groups] == ["guitar", "harmonica"], where  # no Chords: no sheet
        assert groups[0][2] == {
            "file": [["Guitar Pro 1 · gtptabs", "guitar-1.gp5", "Artist - Title.gp5", None]],
            "served": [["Guitar Pro 1 · gtptabs · in the browser", "/guitar?file=Artist%2FTitle%2Fguitar-1.gp5", None,
                        None]]}[where], where
        assert groups[1][2] == [["Harmonica tab 1 · harptabs", "harmonica-1.html", None, None],
                                ["Harmonica tab 2 · harptabs · this page", None, None, "page"]], where
        assert said and not any("null" in text or "undefined" in text for text in said), (where, said)
        assert errors == [], where


@in_chromium
def test_on_a_harmonica_page_the_list_docks_on_a_phone_and_floats_under_its_line_on_a_laptop(tmp_path):
    folder(tmp_path, WONDERWALL, kinds=TWO_TABS)
    pages = harmonica_pages(tmp_path, WONDERWALL, TWO_TABS)
    with viewer(tmp_path, pages["harmonica-1.html"].as_uri()) as b:
        open_list(b)
        phone = b.js(PLACED) | b.js("({dock: document.documentElement.dataset.dock || null, seen: getComputedStyle("
                                    "document.querySelector('#version-list')).visibility,"
                                    " wide: document.documentElement.scrollWidth > innerWidth})")
        b.click("#necks-open")  # the necks' sheet in its place: one at a time on a phone
        assert b.wait("document.querySelector('#version-list').hidden")
        swapped = [b.js("document.documentElement.dataset.dock"), history_at(b, (2, 3))]
        open_list(b)
        assert b.wait("document.querySelector('#necks-open').getAttribute('aria-expanded') === 'false'")
        again = [b.js("document.documentElement.dataset.dock"), history_at(b, (2, 3))]
    assert phone["position"] == "fixed" and abs(phone["bottom"] - phone["barTop"]) <= 1 and phone["depth"] == 1
    assert phone["dock"] == "version-list" and phone["seen"] == "visible" and not phone["wide"]
    assert swapped == ["necks", (2, 3)] and again == ["version-list", (2, 3)]
    with viewer(tmp_path, pages["harmonica-1.html"].as_uri(), **{**DESKTOP, "height": 500}) as b:
        open_list(b)
        laptop = b.js(PLACED) | {"rail": b.js("document.querySelector('#necks').getBoundingClientRect().right")}
        b.press("Escape")
        assert b.wait("document.querySelector('#version-list').hidden")
        focus = b.js("document.activeElement.id")
    assert laptop["position"] == "absolute" and 6 <= laptop["under"] <= 8 and abs(laptop["from"]) <= 1
    assert laptop["left"] >= laptop["rail"] + 8 and laptop["bottom"] <= laptop["barTop"] and focus == "ver-now"


def test_the_fixture_has_the_shape_render_writes():
    # The fixture's keys are as_data's (sheet_versions.py): a change there changes them here too.
    one = SheetVersion(version_id=1, tab_id="1", number=1, rating=4.5, votes=10, label=None, note=None, coverage=None,
                       complete=None, rank=1, kept=False, chosen=False, gone=False, page=None, url=UG + "1")
    data = as_data([one], 1)
    assert set(data) == {"total", "list"} and data["list"] == [entry("1", 1, 4.5, 10, 1)]
