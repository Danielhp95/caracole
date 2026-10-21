"""caracole.viewer: a sheet's versions (viewer.js, viewer.css, page.py's switcher and list).

Each viewer of a song with versions (its data's ``versions``, sheet_versions.as_data: the sheet's own
viewer and each kept version's) says under its key line which of UG's versions it is ("Ver 3 of 13 ·
4.86★ (408) · the one"), between ‹ and ›, which open the version kept before or after it in rank order,
in the same tab. The line opens the list of every version UG has: a kept one opens, one not kept is
kept (caracole serve's /versions page) or shows the command that keeps it (a file), a gone one is
neither. The data here is helpers/version_pages.py's, in the shape render.py writes.
"""

from __future__ import annotations

import http.server
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from helpers.browser import Browser, in_chromium
from helpers.targets import small_targets
from helpers.version_pages import CHO, UG, WONDERWALL, entry, folder
from helpers.viewer_pages import viewer

from caracole.sheet_versions import SheetVersion, as_data
from caracole.viewer import build_viewer, viewer_csp
from caracole.viewer.book import BookSong, build_songbook

PHONE = {"width": 390, "height": 844, "mobile": True}
DESKTOP = {"width": 1280, "height": 800, "mobile": False}
DISPLAY = "'The Placeholders - Synthetic Test Song'"

# What the switcher and the list show.
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
  return {nav: shown(q('#versions')), line: q('#ver-line').textContent,
          prev: q('#ver-prev').getAttribute('href'), next: q('#ver-next').getAttribute('href'),
          prevOff: q('#ver-prev').getAttribute('aria-disabled'), nextOff: q('#ver-next').getAttribute('aria-disabled'),
          list: shown(q('#version-list')), title: q('#version-list-title').textContent, rows,
          acts: [...document.querySelectorAll('#ver-acts a, #ver-acts button')].map((a) =>
            [a.textContent, a.getAttribute('href')]),
          sideways: document.documentElement.scrollWidth > innerWidth};
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


# --- the line, and ‹ › ---------------------------------------------------------------------------


@in_chromium
def test_the_line_names_the_version_its_rating_and_the_one(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        one = seen(b)
        b.open(pages["version-39144.html"].as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        kept = seen(b)
        b.open(pages["version-2161290.html"].as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        third = seen(b)
    assert one["nav"] and one["line"] == "Ver 3 of 13 · 4.86★ (408) · the one"
    assert kept["line"] == "Ver 1 of 13 · 4.85★ (12,629)"
    assert third["line"] == "Ver 7 of 13 · acoustic · 4.80★ (1,204)"


@in_chromium
def test_back_and_forth_open_the_kept_versions_in_rank_order_in_the_same_tab(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        first = seen(b)
        b.click("#ver-next")
        assert b.wait("location.pathname.endsWith('/version-39144.html')"
                      " && document.documentElement.dataset.ready === '1'")
        second = seen(b)
        b.click("#ver-next")
        assert b.wait("location.pathname.endsWith('/version-2161290.html')"
                      " && document.documentElement.dataset.ready === '1'")
        last = seen(b)
        b.click("#ver-prev")
        assert b.wait("location.pathname.endsWith('/version-39144.html')"
                      " && document.documentElement.dataset.ready === '1'")
    assert (first["prev"], first["prevOff"], first["next"]) == (None, "true", "version-39144.html")
    assert (second["prev"], second["next"]) == ("sheet.html", "version-2161290.html")
    assert second["prevOff"] is None and second["nextOff"] is None
    assert (last["prev"], last["next"], last["nextOff"]) == ("version-39144.html", None, "true")


@in_chromium
def test_the_text_size_goes_along_to_the_next_version(tmp_path):
    # Served, a viewer keeps its text size in its address alone: the next version opens at the same size.
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["sheet.html"].as_uri() + "#t=2&fs=24") as b:
        shown = seen(b)
    assert shown["next"] == "version-39144.html#fs=24"  # the size, not the key: its chords are other ones


@in_chromium
def test_a_lacuerda_sheet_is_the_one_and_ug_versions_still_switch(tmp_path):
    # Review Focus 3: the song's sheet is LaCuerda's: no UG version is chosen, and the line says so.
    versions = deepcopy(WONDERWALL)
    versions["list"][0].update(chosen=False, page="version-1064463.html")
    versions["sheet"] = "lacuerda"
    pages = folder(tmp_path, versions)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        sheet = seen(b)
        open_list(b)
        listed = seen(b)
        b.open(pages["version-1064463.html"].as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        version = seen(b)
    assert sheet["line"] == "13 versions on UG · the one: LaCuerda's sheet"
    assert (sheet["prev"], sheet["next"]) == (None, "version-1064463.html")
    assert listed["rows"][0]["text"].startswith("LaCuerda's sheet") and "the one" in listed["rows"][0]["text"]
    assert listed["rows"][0]["current"] == "page"
    assert version["line"] == "Ver 3 of 13 · 4.86★ (408)" and version["prev"] == "sheet.html"


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
    assert listed["prev"] == "sheet%20(auto).html"
    assert listed["rows"][0]["link"] == "sheet%20(auto).html" and "the auto sheet" in listed["rows"][0]["text"]
    assert auto["line"] == "13 versions on UG · the one: the auto sheet" and auto["next"] == "version-1064463.html"


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
    assert shown["line"] == "Ver 3 of 13 · 4.86★ (408) · the one"
    assert shown["rows"][0]["current"] == "page" and shown["rows"][1]["link"] == "sheet.html"
    assert "kept" in shown["rows"][1]["text"]
    assert shown["next"] == "version-2161290.html"  # sheet.html once


@in_chromium
def test_without_versions_there_is_no_switcher(tmp_path):
    for versions in (None, {"total": 0, "list": []}):
        pages = folder(tmp_path, versions)
        with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
            shown = seen(b)
            b.click("#more")  # the settings work as ever
            assert b.wait("!document.querySelector('#panel').hidden")
        assert not shown["nav"] and not shown["list"], versions


def test_the_songbook_has_no_switcher():
    page = build_songbook("Set", [BookSong("Synthetic Test Song", "The Placeholders", CHO)])
    assert 'id="versions"' not in page and 'id="version-list"' not in page
    assert 'id="versions"' in build_viewer(CHO) and 'id="version-list"' in build_viewer(CHO)


# --- the list of every version -------------------------------------------------------------------


@in_chromium
def test_the_list_shows_every_version_and_opens_the_kept_ones(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["version-39144.html"].as_uri()) as b:
        open_list(b)
        shown = seen(b)
        focus = b.js("document.activeElement.id")
        b.click("#ver-items > li:first-child .ver-main")
        assert b.wait("location.pathname.endsWith('/sheet.html') && document.documentElement.dataset.ready === '1'")
    rows = shown["rows"]
    assert shown["title"] == "13 versions on Ultimate Guitar" and len(rows) == 13 and focus == "version-list-title"
    assert rows[0]["link"] == "sheet.html" and "Ver 3" in rows[0]["text"] and "4.86★ (408)" in rows[0]["text"]
    assert "the one" in rows[0]["text"] and "the version that oasis play on Wembley 2008" in rows[0]["text"]
    assert rows[1]["link"] is None and rows[1]["current"] == "page" and "this page" in rows[1]["text"]
    assert rows[2]["link"] == "version-2161290.html" and "kept" in rows[2]["text"] and "acoustic" in rows[2]["text"]
    assert rows[3]["link"] is None and "kept" not in rows[3]["text"] and "Ver 4" in rows[3]["text"]
    assert "capo 2, easy chords" in rows[4]["text"]


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
    assert actions == [["On UG", WONDERWALL["list"][3]["url"]], ["Keep it", None]]
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
    assert shown["next"] == "version-39144.html"
    with viewer(tmp_path, pages["version-39144.html"].as_uri()) as b:
        assert seen(b)["next"] is None  # nothing kept after it but the gone one


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
    assert shown["line"] == "Ver 6 of 13 · 4.58★ (180) · the one"
    assert shown["prev"] == "version-2161290.html" and shown["next"] is None  # by rank, the 6th after the 3rd
    assert shown["acts"] == [["Back to caracole's pick", None]]
    assert cmd == f"caracole versions {DISPLAY} --clear"


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
    assert back[0] == "Back to caracole's pick" and query(back[1]) == (
        "/versions", {"sheet": "Artist/Title/version-39144.html", "do": "clear"})
    keep = shown["rows"][3]["actions"]
    assert len(keep) == 1 and keep[0][0] == "Keep it" and query(keep[0][1]) == (
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
