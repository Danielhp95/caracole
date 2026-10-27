"""caracole serve and a harmonica tab's page (render.py's ``harmonica-N.html``): served as a page caracole wrote, in a
sandbox with its own policy, only while it is as written; in the library page's links and the Android app's copy."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from helpers.browser import Browser, in_chromium

from caracole import todo
from caracole.library import song_dir
from caracole.library_page import linked_files
from caracole.overrides import Overrides
from caracole.web.app import WebApp, written_page
from caracole.web.jobs import JobQueue

from test_render_harmonica import render, song_with_a_tab
from test_web_app import ALLOWED, META_POLICY, Recorder, get, header

NOW = datetime(2026, 10, 27, tzinfo=UTC)
FOLDER = "Placeholder Band/Synthetic Song"


@pytest.fixture
def app(cfg):
    return WebApp(cfg, JobQueue(Recorder(), limit=3), allowed=ALLOWED, csrf="tok")


@pytest.fixture
def library(conn, cfg):
    song = song_with_a_tab(conn, cfg)
    render(conn, cfg)
    todo.write_pages(conn, cfg, Overrides(), NOW)
    return song_dir(cfg.library_dir, song)


def test_a_harmonica_tabs_page_is_a_kind_of_page_caracole_writes():
    assert written_page("harmonica-1.html") is not None and written_page("harmonica-12.html") is not None
    for name in ("harmonica-1.txt", "harmonica-x.html", "harmonica-.html", "my-harmonica-1.html"):
        assert written_page(name) is None


def test_it_is_served_as_written_in_a_sandbox_with_its_own_policy(app, library):
    response = get(app, f"/{FOLDER}/harmonica-1.html")
    assert response.status == 200
    page = (library / "harmonica-1.html").read_bytes()
    assert response.body == page
    own = META_POLICY.search(page.decode("utf-8")).group(1)
    assert header(response, "content-security-policy") == f"sandbox allow-scripts allow-downloads; {own}; frame-ancestors 'none'"
    assert header(response, "content-type") == "text/html; charset=utf-8"


def test_it_is_not_sent_once_changed_on_a_synced_device_nor_one_no_render_wrote(app, library):
    page = library / "harmonica-1.html"
    page.write_bytes(page.read_bytes() + b"<script>fetch('/caracole.sqlite')</script>")
    response = get(app, f"/{FOLDER}/harmonica-1.html")
    assert response.status == 404
    assert b"harmonica tab&#x27;s page isn&#x27;t the page caracole last wrote here" in response.body
    (library / "harmonica-2.html").write_text("<p>mine</p>", encoding="utf-8")
    assert get(app, f"/{FOLDER}/harmonica-2.html").status == 404


def test_the_library_page_links_it_and_the_apps_copy_takes_it(app, library, cfg):
    written = (cfg.library_dir / "index.html").read_bytes()
    assert f"{FOLDER}/harmonica-1.html" in linked_files(written)
    response = get(app, "/api/offline")
    assert response.status == 200
    listed = {entry["path"]: entry for entry in json.loads(response.body)["files"]}
    assert {f"{FOLDER}/harmonica-1.html", f"{FOLDER}/harmonica-1.txt"} <= set(listed)
    entry = listed[f"{FOLDER}/harmonica-1.html"]
    assert entry["headers"]["Content-Security-Policy"].startswith("sandbox allow-scripts allow-downloads; default-src 'none'")
    assert entry["url"] == "/Placeholder%20Band/Synthetic%20Song/harmonica-1.html"


def test_the_songs_card_groups_the_tab_with_its_page(library, cfg):
    found = re.search(rb'<script type="application/json" id="songs">(.*?)</script>',
                      (cfg.library_dir / "index.html").read_bytes(), re.S)
    songs = json.loads(found.group(1))["songs"]
    files = {f["name"]: f for f in next(s for s in songs if s["title"] == "Synthetic Song")["files"]}
    assert files["harmonica-1.txt"]["harmonicaPage"] == {"href": f"{FOLDER.replace(' ', '%20')}/harmonica-1.html"}
    assert "harmonica-1.html" not in files  # the page is no file of the list: the tab's group opens it


@in_chromium
def test_the_songs_line_opens_the_page_and_downloads_the_tabs_text(library, cfg, tmp_path):
    # From a file (the library folder, the Android app's copy): the card's Harmonica tab tile, under the line's chevron
    tile = "document.querySelector('.tile-harmonica')"
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), width=390, height=844, mobile=True) as b:
        b.open((cfg.library_dir / "index.html").as_uri())
        assert b.wait("!!document.querySelector('.line-more')", 15)
        b.click(".line-more")
        assert b.wait(f"!!{tile}")
        found = b.js(f"[...{tile}.querySelectorAll('a')].map((a) => [a.classList.contains('tile-open') ? 'Open' : "
                     "'Download', a.getAttribute('href'), a.getAttribute('download')])")
        b.js(f"{tile}.querySelector('a.tile-open').click()")
        assert b.wait("location.pathname.endsWith('harmonica-1.html') && document.documentElement.dataset.ready === '1'",
                      15)
    folder = FOLDER.replace(" ", "%20")
    # The tile opens the page; its download is the tab's text, under its own name (an empty download attribute)
    assert [(kind, href) for kind, href, _ in found] == [("Open", f"{folder}/harmonica-1.html"),
                                                         ("Download", f"{folder}/harmonica-1.txt")]
    assert found[0][2] is None and found[1][2] is not None
