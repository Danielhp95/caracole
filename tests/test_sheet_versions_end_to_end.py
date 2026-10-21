"""A song's sheet versions end to end: Ultimate Guitar lists four chords versions of it, ``caracole get`` keeps
the sheet and the two runners-up it scores beside it (ug/fetch.py), render writes a viewer page for each
(render.py), whose switcher lists them and steps between them (viewer.js), the library page's "⋯" lists them
(library_page.py), and caracole serve serves each version's page and makes one the sheet (versions_routes.py:
``caracole versions --choose``, queued).

The sites are test_get.py's ``Sites`` behind ``caracole.commands._common.transport_for`` (test_commands_versions.py's
fixtures); chordpro is test_commands_get.py's fake script; caracole serve's queue runs each command in this
process, through the CLI, against the same fake sites.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.parse import quote

import pytest
from helpers.browser import Browser, BrowserError, dump_dom, in_chromium
from helpers.ug_pages import make_tab_page_html, version_dict
import test_commands_versions
from test_get import LINES, NOW, TAB, Sites, sheet
from test_library_page import line_of, link_texts, listing, panel_of, songs_of
from typer.testing import CliRunner

from caracole.cli import build_app
from caracole.config import load_config
from caracole.library import keep_file, song_dir
from caracole.overrides import load_overrides
from caracole.sheet_versions import version_names
from caracole.ug.page import strip_markup
from caracole.versions import upsert_version
from conftest import add_song
from caracole.ug.index import mark_built, upsert_rows
from caracole.web.app import Request

config, conn, sites = test_commands_versions.config, test_commands_versions.conn, test_commands_versions.sites
CREEP = "Radiohead - Creep"
FOLDER = "Radiohead/Creep"


def creep(tab_id: int, number: int, rating: float, votes: int, note: str | None = None) -> dict:
    extra = {"version_description": note} if note else {}
    return version_dict(tab_id, song="Creep", artist="Radiohead", version=number, rating=rating, votes=votes,
                        tab_url=f"{TAB}radiohead/creep-chords-{tab_id}", **extra)


# Four chords versions: 101, the best rated, charts a verse alone (it never opens first); 102, 103 and 104 the song.
FOUR = [creep(101, 1, 4.9, 100), creep(102, 2, 4.6, 50, "the album version"), creep(103, 3, 4.2, 50),
        creep(104, 4, 3.5, 20)]


def serve(sites: Sites, conn) -> None:
    texts = {101: LINES[:2], 102: LINES, 103: LINES, 104: LINES}
    for tab in FOUR:
        others = [t for t in FOUR if t is not tab]
        sites.pages[tab["tab_url"]] = (200, make_tab_page_html(tab, others, content=sheet(f"sheet {tab['id']}",
                                                                                            texts[tab["id"]])))
    upsert_rows(conn, [(t["id"], "radiohead", "creep", "chords", t["tab_url"].removeprefix(TAB)) for t in FOUR],
                "1", NOW)
    mark_built(conn, NOW)
    sites.lyrics[("Radiohead", "Creep")] = "\n".join(LINES)


def caracole(config_path: Path, *args: str):
    return CliRunner().invoke(build_app(), ["--config", str(config_path), *args])


def looked_up(config_path: Path, sites: Sites, conn, tmp_path: Path) -> Path:
    """Creep looked up (``caracole get``): its folder."""
    serve(sites, conn)
    result = caracole(config_path, "get", CREEP)
    assert result.exit_code == 0, result.output
    return tmp_path / "library" / "Radiohead" / "Creep"


def data_of(page: Path) -> dict:
    found = re.search(r'<script type="application/json" id="song">(.*?)</script>', page.read_text("utf-8"), re.S)
    assert found, page
    return json.loads(found.group(1))


def listed(page: Path) -> list[tuple]:
    return [(v["tab"], v["page"], v["chosen"], v["this"]) for v in data_of(page)["versions"]["list"]]


@pytest.mark.slow
def test_four_versions_on_ug_three_kept_each_with_its_viewer_page(config, sites, conn, tmp_path):
    folder = looked_up(config, sites, conn, tmp_path)

    assert "sheet 102" in (folder / "sheet.txt").read_text("utf-8")  # complete first, then the rating
    assert sorted(p.name for p in folder.glob("version-*")) == [
        "version-101.html", "version-101.json", "version-101.txt",
        "version-103.html", "version-103.json", "version-103.txt"]  # the 4th is listed, not kept
    # Every page lists every version in rank order, its own marked
    assert listed(folder / "sheet.html") == [
        ("102", "sheet.html", True, True), ("103", "version-103.html", False, False),
        ("101", "version-101.html", False, False), ("104", None, False, False)]
    assert listed(folder / "version-103.html") == [
        ("102", "sheet.html", True, False), ("103", "version-103.html", False, True),
        ("101", "version-101.html", False, False), ("104", None, False, False)]
    versions = data_of(folder / "version-101.html")["versions"]
    assert (versions["total"], versions["sheet"], versions["pinned"]) == (4, "ug", False)
    # A version's page is its own text, and offers no export: an export is the one's
    page = (folder / "version-103.html").read_text("utf-8")
    assert '<p class="l">sheet 103</p>' in page and 'id="export"' not in page
    assert 'id="export"' in (folder / "sheet.html").read_text("utf-8")
    # The library page's data lists the kept ones, each with its page
    library = songs_of((tmp_path / "library" / "index.html").read_text("utf-8"))[CREEP]
    kept = [(v["tab"], v["href"], v["chosen"]) for v in library["versions"]["list"]]
    assert kept == [("102", "Radiohead/Creep/sheet.html", True),
                    ("103", "Radiohead/Creep/version-103.html", False),
                    ("101", "Radiohead/Creep/version-101.html", False)]


@pytest.fixture
def browser(tmp_path):
    try:
        page = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    yield page
    page.close()


SWITCHER = """(() => {
  const q = (s) => document.querySelector(s);
  return {page: decodeURIComponent(location.pathname.split('/').pop()), line: q('#ver-line').textContent,
          prev: q('#ver-prev').getAttribute('href'), next: q('#ver-next').getAttribute('href'),
          rows: [...document.querySelectorAll('#ver-items > li')].map((li) => li.querySelector('.ver-main').textContent),
          acts: [...document.querySelectorAll('#ver-acts a, #ver-acts button')].map((a) =>
            [a.textContent, a.getAttribute('href')]),
          keep: [...document.querySelectorAll('#ver-items .ver-acts a, #ver-items .ver-acts button')].map((a) =>
            [a.textContent, a.getAttribute('href')])};
})()"""


def step(b: Browser, which: str, page: str) -> dict:
    """Click ‹ or › (``which``) and wait for ``page``, the new document."""
    b.js("window.before = true")
    b.click(which)
    assert b.wait(f"!window.before && location.pathname.endsWith({json.dumps('/' + quote(page))})"
                  " && document.querySelector('#ver-line').textContent !== ''")
    return b.js(SWITCHER)


@in_chromium
def test_the_switcher_steps_through_the_kept_versions_pages_and_lists_them_all(
        config, sites, conn, tmp_path, browser):
    folder = looked_up(config, sites, conn, tmp_path)

    browser.open((folder / "version-103.html").as_uri())
    assert browser.wait("document.querySelector('#ver-line').textContent !== ''")
    seen = browser.js(SWITCHER)
    assert seen["line"] == "Ver 3 of 4 · 4.20★ (50)"
    assert (seen["prev"], seen["next"]) == ("sheet.html", "version-101.html")
    assert [r.split(" · ")[0] for r in seen["rows"]] == ["Ver 2", "Ver 3", "Ver 1", "Ver 4"]
    assert "the album version" in seen["rows"][0]
    assert seen["acts"] == [["Make this the one", None]]  # from a file, a button showing the command
    assert seen["keep"] == [["On UG", f"{TAB}radiohead/creep-chords-104"], ["Keep it", None]]

    seen = step(browser, "#ver-next", "version-101.html")
    assert seen["line"] == "Ver 1 of 4 · 4.90★ (100)" and seen["next"] is None

    step(browser, "#ver-prev", "version-103.html")
    seen = step(browser, "#ver-prev", "sheet.html")
    assert seen["line"] == "Ver 2 of 4 · 4.60★ (50) · the one" and seen["prev"] is None
    assert seen["next"] == "version-103.html"


@in_chromium
def test_the_library_pages_menu_lists_the_kept_versions(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path)

    shown = listing(dump_dom((tmp_path / "library" / "index.html").as_uri(), (1280, 800)))
    groups = dict(re.findall(r'<p class="subhead">([^<]*)</p><div class="actions">(.*?)</div>',
                             panel_of(line_of(shown, "Creep")), re.S))
    kept = groups["Sheet versions"]
    assert link_texts(kept) == ["Ver 2 · 4.60★ (50) · the one", "Ver 3 · 4.20★ (50)", "Ver 1 · 4.90★ (100)"]
    assert re.findall(r'href="([^"]*)"', kept) == [
        "Radiohead/Creep/sheet.html", "Radiohead/Creep/version-103.html", "Radiohead/Creep/version-101.html"]


@in_chromium
def test_a_lacuerda_sheet_rendered_is_named_the_one_and_ug_versions_still_switch(conn, cfg, browser):
    # Review Focus 3, as render.py writes it and the viewer reads it: the title opens LaCuerda's sheet, none of UG's
    import test_render_versions as r

    song = add_song(conn, "Placeholder Banda", "Canción Sintética")
    tab_id = "placeholder_banda/cancion_sintetica-3"
    url = f"https://acordes.lacuerda.net/{tab_id}.shtml"
    vid = upsert_version(conn, provider="lacuerda", tab_id=tab_id, song_id=song.id, slot="sheet", kind="acordes",
                         rating=0, votes=0, version=3, label=None, url=url, raw={}, now=r.FETCHED)
    content = r.sheet("lacuerda")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.json",
              data=json.dumps({"provider": "lacuerda", "url": url, "version": 3, "content": content}).encode(), rank=1)
    vid_b, raw_b = r.ug_version(conn, song, r.B, rating=4.8, votes=100, number=1, coverage=0.9)
    r.keep_text(conn, cfg, song, vid_b, raw_b, r.sheet("ug"), version_names(str(r.B))[:2], 2)
    r.ug_version(conn, song, r.C, rating=4.5, votes=20, number=2)
    r.render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)

    browser.open((folder / "sheet.html").as_uri())
    assert browser.wait("document.querySelector('#ver-line').textContent !== ''")
    one = browser.js(SWITCHER)
    browser.open((folder / version_names(str(r.B))[2]).as_uri())
    assert browser.wait("document.querySelector('#ver-line').textContent !== ''")
    other = browser.js(SWITCHER)

    assert one["line"] == "2 versions on UG · the one: LaCuerda's sheet"
    assert (one["prev"], one["next"]) == (None, version_names(str(r.B))[2])
    assert [row.split(" · ")[0] for row in one["rows"]] == ["LaCuerda's sheet", "Ver 1", "Ver 2"]
    assert other["line"] == "Ver 1 of 2 · 4.80★ (100)" and other["prev"] == "sheet.html"
    assert other["acts"] == [["Make this the one", None]]


# --- caracole serve ----------------------------------------------------------------------------------


class InProcess:
    """caracole serve's runner, running each command through the CLI in this process (the fake sites stay in
    place), its output said line by line."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.ran: list[tuple[str, ...]] = []

    def __call__(self, args, emit):
        self.ran.append(tuple(args))
        result = caracole(self.config_path, *args)
        for line in result.output.splitlines():
            emit(line)
        return result.exit_code


@pytest.fixture
def live(config, tmp_path):
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue
    from caracole.web.security import allowed_hosts
    from caracole.web.server import make_server

    runner = InProcess(config)
    queue = JobQueue(runner)  # run here, by the test: run_pending
    app = WebApp(load_config(config, env={}), queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", app, queue, runner
    server.shutdown()
    server.server_close()


@in_chromium
def test_make_this_the_one_from_a_versions_served_page(config, sites, conn, tmp_path, browser, live):
    folder = looked_up(config, sites, conn, tmp_path)
    base, app, queue, runner = live

    # The version's page, served as a viewer, links caracole serve's versions page
    browser.open(base + quote(f"{FOLDER}/version-103.html"))
    assert browser.wait("document.querySelector('#ver-line').textContent !== ''")
    seen = browser.js(SWITCHER)
    assert seen["acts"] == [["Make this the one", f"/versions?sheet={quote(FOLDER + '/version-103.html', safe='')}"
                                                  "&tab=103&do=choose"]]
    assert seen["keep"] == [["Keep it", f"/versions?sheet={quote(FOLDER + '/version-103.html', safe='')}"
                                        "&tab=104&do=keep"]]
    browser.click("#ver-now")  # the list, where it is offered
    assert browser.wait("!document.querySelector('#version-list').hidden")
    browser.js("window.before = true")
    browser.click("#ver-acts a")
    assert browser.wait("!window.before && location.pathname === '/versions' && document.forms.length === 1")
    browser.js("window.before = true")
    browser.click("form.confirm button[type=submit]")
    assert browser.wait("!window.before && location.search.includes('job=')")

    queue.run_pending()
    assert runner.ran == [("versions", "--choose=103", "--progress", "--", "Radiohead", "Creep")]
    # Its progress lines are the job's stages, a lookup's
    stages = {stage.name: stage.state for stage in queue.job(1).stages}
    assert (stages["song"], stages["sheet"], stages["pdf"]) == ("done", "done", "done"), stages
    browser.js("window.before = true")
    browser.js("location.reload()")
    assert browser.wait("!window.before && document.readyState === 'complete'")
    assert "Done: it is the one now." in browser.js("document.body.textContent")
    # The page it was asked from went (the version is sheet.html now): back to the sheet is the song's sheet
    assert browser.js("[...document.querySelectorAll('a.btn')].map((a) => [a.textContent, a.getAttribute('href')])") == [
        ["Open the sheet", f"/{FOLDER}/sheet.html"], ["Back to the sheet", f"/{FOLDER}/sheet.html"]]

    assert "sheet 103" in (folder / "sheet.txt").read_text("utf-8")
    assert load_overrides(tmp_path / "library" / "overrides.toml").pin["radiohead/creep"] == (103,)
    assert listed(folder / "sheet.html")[:3] == [
        ("102", "version-102.html", False, False), ("103", "sheet.html", True, True),
        ("101", "version-101.html", False, False)]
    assert sorted(p.name for p in folder.glob("version-*.html")) == ["version-101.html", "version-102.html"]
    assert data_of(folder / "sheet.html")["versions"]["pinned"] is True  # Back to caracole's pick, offered

    # Its page was the version's, and is gone now that it's the sheet; an export from a version's page is refused
    def get(path):
        return app.handle(Request("GET", path, {"host": base.split("/")[2]}))

    assert get("/" + quote(f"{FOLDER}/version-103.html")).status == 404
    assert get("/" + quote(f"{FOLDER}/version-102.html")).status == 200
    assert get(f"/export?sheet={quote(FOLDER + '/version-102.html')}&t=2").status == 409

    # Keep it, from the sheet's served page: the 4th version, fetched now and kept beside the sheet
    browser.open(base + quote(f"{FOLDER}/sheet.html"))
    assert browser.wait("document.querySelector('#ver-line').textContent !== ''")
    browser.click("#ver-now")
    assert browser.wait("!document.querySelector('#version-list').hidden")
    assert browser.js(SWITCHER)["acts"] == [["Back to caracole's pick", f"/versions?sheet={quote(FOLDER + '/sheet.html', safe='')}"
                                                                        "&do=clear"]]
    browser.js("window.before = true")
    browser.click("#ver-items > li:nth-child(4) .ver-acts a")
    assert browser.wait("!window.before && location.pathname === '/versions' && document.forms.length === 1")
    browser.js("window.before = true")
    browser.click("form.confirm button[type=submit]")
    assert browser.wait("!window.before && location.search.includes('job=')")
    queue.run_pending()
    assert runner.ran[-1] == ("versions", "--keep=104", "--progress", "--", "Radiohead", "Creep")
    stages = {stage.name: stage.state for stage in queue.job(2).stages}
    assert (stages["version"], stages["pdf"]) == ("done", "done"), stages
    browser.js("window.before = true")
    browser.js("location.reload()")
    assert browser.wait("!window.before && document.readyState === 'complete'")
    assert "Done: it is kept beside the sheet." in browser.js("document.body.textContent")
    browser.js("window.before = true")
    browser.click("a.btn.primary")  # Open it
    assert browser.wait("!window.before && location.pathname.endsWith('/version-104.html')"
                        " && document.querySelector('#ver-line').textContent !== ''")
    assert browser.js(SWITCHER)["line"] == "Ver 4 of 4 · 3.50★ (20)"
