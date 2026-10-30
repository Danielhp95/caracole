"""Which library a page shows (library_name.py): its name in every page caracole writes or serves, in its header and
its tab's title, and the badge of a library that isn't the owner's usual one on every page caracole serve serves."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from helpers import browser
from helpers.browser import in_chromium
from typer.testing import CliRunner

from caracole.cli import build_app
from caracole.library_name import SCRATCH, SCRATCH_LINK
from caracole.library_page import WebControls, build_library_page
from caracole.overrides import Overrides
from caracole.page_icon import LINK
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue

from conftest import add_song
from test_web_app import ALLOWED, Recorder, get, text

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
TITLE = re.compile(r"<title>([^<]*)</title>")
MASTHEAD = re.compile(r'<header class="masthead lib">(.*?)</header>', re.S)
TOP = re.compile(r'<header class="top">(.*?)</header>', re.S)


def title_of(html: str) -> str:
    import html as html_text

    return html_text.unescape(TITLE.search(html).group(1))


def named(cfg, name="Tabs"):
    from dataclasses import replace

    return replace(cfg, name=name)


# --- the library page -----------------------------------------------------------------------------------------------


def test_the_written_library_page_carries_the_name_and_never_a_badge(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    html = build_library_page(conn, named(cfg), Overrides(), NOW)
    assert title_of(html) == "caracole · Tabs"
    masthead = MASTHEAD.search(html).group(1)
    assert '<p class="libname"><span class="name">Tabs</span></p>' in masthead
    assert "scratch" not in masthead and LINK in html and SCRATCH_LINK not in html


def test_by_default_the_library_is_named_by_its_folder(conn, cfg):
    html = build_library_page(conn, cfg, Overrides(), NOW)
    assert title_of(html) == f"caracole · {cfg.library_dir.name}"


def test_the_served_library_page_carries_the_name_and_its_servers_badge(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    plain = build_library_page(conn, named(cfg), Overrides(), NOW, controls=WebControls(csrf="tok"))
    assert title_of(plain) == "caracole · Tabs" and "scratch" not in MASTHEAD.search(plain).group(1)
    badged = build_library_page(conn, named(cfg), Overrides(), NOW, controls=WebControls(csrf="tok", badge=SCRATCH))
    assert title_of(badged) == "Scratch library · caracole · Tabs"
    masthead = MASTHEAD.search(badged).group(1)
    assert ('<p class="libname"><span class="name">Tabs</span> '
            '<span class="scratch" title="Not your usual library">Scratch library</span></p>') in masthead
    assert SCRATCH_LINK in badged and LINK not in badged  # its icon in the badge's colour


def test_a_name_is_escaped_on_the_page(conn, cfg):
    html = build_library_page(conn, named(cfg, "<Dani & co>"), Overrides(), NOW)
    assert "<Dani" not in html and title_of(html) == "caracole · <Dani & co>"
    assert '<span class="name">&lt;Dani &amp; co&gt;</span>' in html


# --- caracole serve's pages -------------------------------------------------------------------------------------------


@pytest.fixture
def badged(cfg):
    return WebApp(named(cfg), JobQueue(Recorder()), allowed=ALLOWED, csrf="tok", badge="Demo")


@pytest.fixture
def usual(cfg):
    return WebApp(named(cfg), JobQueue(Recorder()), allowed=ALLOWED, csrf="tok")


SERVED = ("/", "/lookup", "/review?song=999", "/nothing.pdf")


def test_every_page_caracole_serve_writes_names_the_library_and_says_its_badge(badged, usual, conn):
    add_song(conn, "Radiohead", "Creep")
    for path in SERVED:
        page = text(get(badged, path))
        header = (MASTHEAD.search(page) or TOP.search(page)).group(1)
        assert '<span class="name">Tabs</span>' in header, path
        assert '<span class="scratch" title="Not your usual library">Demo</span>' in header, path
        assert title_of(page).startswith("Demo · ") and title_of(page).endswith(" · caracole · Tabs"), path
        assert SCRATCH_LINK in page and LINK not in page, path
        page = text(get(usual, path))
        header = (MASTHEAD.search(page) or TOP.search(page)).group(1)
        assert '<span class="name">Tabs</span>' in header and "scratch" not in header, path
        assert title_of(page).endswith("caracole · Tabs") and not title_of(page).startswith("Demo"), path
    assert title_of(text(get(usual, "/lookup"))) == "Look up · caracole · Tabs"
    assert title_of(text(get(usual, "/nothing.pdf"))) == "Not found · caracole · Tabs"


def test_a_page_written_without_a_server_names_no_library():
    # pages.py's pages and the header (top.py) say a library's name only when given one.
    from caracole.web.pages import message_page

    html = message_page("Not found", "There's nothing here.")
    assert 'class="libname"' not in html and title_of(html) == "Not found · caracole"


# --- caracole serve: how it knows -------------------------------------------------------------------------------------


def config(tmp_path, folder):
    root = tmp_path / folder
    path = tmp_path / f"{folder}.toml"
    path.write_text(f'library_dir = "{root / "lib"}"\nstate_dir = "{root / "state"}"\n'
                    f'cache_dir = "{root / "cache"}"\nmusic_dir = "{root / "music"}"\n', encoding="utf-8")
    return path


@pytest.fixture
def started(monkeypatch):
    seen = {}

    def serve(app, address, port, *, announce):
        seen.update(app=app)

    monkeypatch.setattr("caracole.web.server.serve", serve)
    return seen


def test_serve_badges_a_library_in_a_temporary_folder_and_says_so(tmp_path, started, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))  # wherever pytest's folders are
    result = CliRunner().invoke(build_app(), ["--config", str(config(tmp_path, "scratch")), "serve"])
    assert result.exit_code == 0, result.output
    assert started["app"].library_name.badge == SCRATCH
    assert ("Its pages say Scratch library beside the library's name, lib: it serves a library in a temporary "
            "folder; --label sets another badge") in result.output


def test_serve_label_names_the_badge_or_takes_it_away(tmp_path, started, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    path = config(tmp_path, "demo")
    result = CliRunner().invoke(build_app(), ["--config", str(path), "serve", "--label", "Demo"])
    assert result.exit_code == 0, result.output
    assert started["app"].library_name.badge == "Demo" and "Its pages say Demo" in result.output
    result = CliRunner().invoke(build_app(), ["--config", str(path), "serve", "--label", ""])
    assert result.exit_code == 0, result.output
    assert started["app"].library_name.badge is None and "Its pages say" not in result.output
    result = CliRunner().invoke(build_app(), ["--config", str(path), "serve", "--label", "x" * 41])
    assert result.exit_code == 2 and "--label: 40 characters at most" in result.output


def test_serve_badges_nothing_for_a_library_outside_temporary_folders(tmp_path, started, monkeypatch):
    # The owner's libraries (tests/test_library_name.py): here, a folder no temporary folder holds.
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("caracole.library_name.TEMPORARY", ())  # pytest's tmp_path may be in /tmp or /dev/shm
    result = CliRunner().invoke(build_app(), ["--config", str(config(tmp_path, "home")), "serve"])
    assert result.exit_code == 0, result.output
    assert started["app"].library_name.badge is None and "Its pages say" not in result.output
    assert started["app"].library_name.name == "lib"


# --- in a browser -----------------------------------------------------------------------------------------------------

LOOK = """
(() => {
  const box = (s) => { const e = document.querySelector(s); if (!e || !e.checkVisibility()) return null;
    const r = e.getBoundingClientRect();  // one visually hidden, there for a screen reader alone: none
    return r.width <= 1 ? null : [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]; };
  const badge = document.querySelector(".libname .scratch");
  document.body.setAttribute("data-look", JSON.stringify({
    name: box(".libname .name"), badge: box(".libname .scratch"), tabs: box(".masthead .tabs") || box("header.top h1"),
    app: box(".masthead .app") || box("header.top .app"),
    colour: badge ? getComputedStyle(badge).color : null, background: badge ? getComputedStyle(badge).backgroundColor : null,
    fits: document.documentElement.scrollWidth <= innerWidth,
    first: (() => { const a = document.querySelector("#list article"); return a ? Math.round(a.getBoundingClientRect().top) : null; })(),
  }));
})();
"""


def look(html: str, tmp_path, size, scheme="light") -> dict:
    """What LOOK notes of a page opened as a file: the library page with LOOK allowed by its hash, a page of caracole
    serve's own (whose policy is a header, not sent to a file) with LOOK after it."""
    from test_library_page import attribute_of, with_script

    path = tmp_path / f"look-{size[0]}-{scheme}.html"
    shown = (with_script(html, LOOK) if 'http-equiv="Content-Security-Policy"' in html
             else html.replace("</body>", f"<script>{LOOK}</script>\n</body>"))
    path.write_text(shown, encoding="utf-8")
    dom = browser.dump_dom(path.as_uri(), size, hide_scrollbars=True, mobile=size[0] < 500,
                           media={"prefers-color-scheme": scheme})
    return attribute_of(dom, "data-look")


def library_page(conn, cfg, badge=None) -> str:
    for n, (artist, title) in enumerate((("Radiohead", "Creep"), ("Oasis", "Wonderwall"), ("Muse", "Hysteria"))):
        add_song(conn, artist, title)
    return build_library_page(conn, named(cfg, "Tabs"), Overrides(), NOW,
                              controls=WebControls(csrf="tok", active=1, badge=badge))


@in_chromium
def test_on_a_desktop_the_name_follows_caracole_on_the_bar_and_the_badge_after_it(conn, cfg, tmp_path):
    html = library_page(conn, cfg, SCRATCH)
    seen = look(html, tmp_path, (1280, 900))
    assert seen["fits"] and seen["name"] and seen["badge"], seen
    app, name, badge, tabs = seen["app"], seen["name"], seen["badge"], seen["tabs"]
    assert app[0] + app[2] <= name[0] < badge[0] < tabs[0], seen  # caracole, the name, the badge, the tabs
    middle = lambda box: box[1] + box[3] / 2  # noqa: E731
    assert abs(middle(name) - middle(tabs)) < 12 and abs(middle(badge) - middle(tabs)) < 12, seen  # one bar
    assert seen["first"] < 215, seen  # the songs start where they did


@in_chromium
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_on_a_phone_the_badge_shows_under_the_bar_and_the_usual_library_keeps_one_bar(conn, cfg, tmp_path, scheme):
    usual = look(library_page(conn, cfg), tmp_path, (390, 844), scheme)
    assert usual["fits"] and usual["badge"] is None and usual["name"] is None, usual  # the name is in the title
    assert usual["first"] < 240, usual
    badged = look(build_library_page(conn, named(cfg, "Tabs"), Overrides(), NOW,
                                     controls=WebControls(csrf="tok", active=1, badge=SCRATCH)), tmp_path, (390, 844),
                  scheme)
    assert badged["fits"] and badged["badge"] and badged["name"], badged
    assert badged["badge"][1] >= badged["tabs"][1] + badged["tabs"][3] - 4, badged  # a line of its own, under the tabs
    assert badged["badge"][0] + badged["badge"][2] <= 390 - 16, badged
    assert badged["colour"] != badged["background"], badged
    assert badged["first"] < 280, badged  # a line more, and no more


@in_chromium
@pytest.mark.parametrize("size", [(1280, 800), (390, 844)])
def test_a_page_of_caracole_serves_own_shows_the_badge_at_any_width(badged, tmp_path, size):
    page = text(get(badged, "/review?song=999"))
    seen = look(page, tmp_path, size)
    assert seen["fits"] and seen["badge"], seen
    if size[0] > 500:
        assert seen["name"], seen
