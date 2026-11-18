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
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from helpers.browser import Browser, in_chromium
from helpers.targets import small_targets
from helpers.version_pages import CHO, EVERY_KIND, KINDS, UG, WONDERWALL, entry, folder
from helpers.viewer_pages import viewer

from caracole import render
from caracole.sheet_versions import SheetVersion, as_data
from caracole.viewer import build_viewer, page, viewer_csp
from caracole.viewer.book import BookSong, build_songbook

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


@in_chromium
def test_on_a_phone_the_list_docks_at_the_foot_with_thumb_sized_targets_and_no_sideways_scroll(tmp_path):
    versions = deepcopy(WONDERWALL)
    versions["list"][1]["note"] = "a tabber's note that runs on " * 12
    pages = folder(tmp_path, versions)
    with viewer(tmp_path, pages["version-39144.html"].as_uri(), **PHONE) as b:
        closed = seen(b)
        small_switcher = b.js(small_targets("#version-list *, .bar *, .foot *, .head .back, .sheet *"))
        open_list(b)
        shown = seen(b)
        box = b.js("(() => { const r = document.querySelector('#version-list').getBoundingClientRect();"
                   " const bar = document.querySelector('#bar').getBoundingClientRect();"
                   " return {bottom: r.bottom, barTop: bar.top, height: r.height}; })()")
        small = b.js(small_targets(":not(#version-list):not(#version-list *)"))
        b.press("Escape")
        assert b.wait("document.querySelector('#version-list').hidden")
        back = b.js("document.activeElement.id")
    assert not closed["sideways"] and not shown["sideways"]
    assert small_switcher == [] and small == []
    assert abs(box["bottom"] - box["barTop"]) <= 1 and box["height"] <= 844 * 0.45 + 1
    assert back == "ver-now"


@in_chromium
def test_on_a_laptop_the_list_is_a_rail_and_one_rail_at_a_time(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["sheet.html"].as_uri(), **DESKTOP) as b:
        open_list(b)
        rail = b.js("(() => { const r = document.querySelector('#version-list').getBoundingClientRect();"
                    " return {right: r.right - document.documentElement.clientWidth, width: r.width, top: r.top,"
                    " rail: document.documentElement.dataset.panel}; })()")
        b.click("#more")
        assert b.wait("!document.querySelector('#panel').hidden")
        after = b.js("[document.querySelector('#version-list').hidden, document.documentElement.dataset.panel,"
                     " document.querySelector('#ver-now').getAttribute('aria-expanded')]")
    assert rail == {"right": 0, "width": 360, "top": 0, "rail": "open"}
    assert after == [True, "open", "false"]


def test_the_fixture_has_the_shape_render_writes():
    # The fixture's keys are as_data's (sheet_versions.py): a change there changes them here too.
    one = SheetVersion(version_id=1, tab_id="1", number=1, rating=4.5, votes=10, label=None, note=None, coverage=None,
                       complete=None, rank=1, kept=False, chosen=False, gone=False, page=None, url=UG + "1")
    data = as_data([one], 1)
    assert set(data) == {"total", "list"} and data["list"] == [entry("1", 1, 4.5, 10, 1)]
