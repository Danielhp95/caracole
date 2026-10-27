"""caracole serve's offline copy of the library, for caracole's Android app (web/offline_routes.py):
``GET /api/offline``, the manifest of every file the app mirrors, and ``GET /offline/index.html``, the
library page caracole wrote, while it is still as written."""

import dataclasses
import hashlib
import json
import re
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

import pytest

from caracole import todo
from caracole.db import kv_set_json
from caracole.library import song_dir
from caracole.library_page import write_library_page
from caracole.overrides import Overrides
from caracole.songbook import RECORD_KEY, make_songbook, songbooks_file
from caracole.viewer import build_viewer
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from helpers import browser
from helpers.browser import in_chromium
from helpers.guitar import keep_guitar
from helpers.rendered import rendered_song
from test_web_app import ALLOWED, HOST, META_POLICY, Recorder, get, header, text
from test_web_versions import KEPT, versioned_song

NOW = datetime(2026, 10, 27, tzinfo=UTC)
FOLDER = "Soda Stereo/De Música Ligera"
AUTO = "Placeholder Band/Synthetic Song"
BOOK = "_songbooks/Campfire"
JSON_TYPE = "application/json; charset=utf-8"
HTML = "text/html; charset=utf-8"
# The headers the manifest may name (the Android app ignores any other).
NAMES = ("Content-Security-Policy", "Referrer-Policy", "X-Content-Type-Options")
GP5 = b"FICHIER GUITAR PRO v5.00" + bytes(40)  # a Guitar Pro 5 header, then nothing: no one's tab

# What the library of the fixture mirrors: the library page first, then each file it links to that serve sends, by
# path. Not listed: sheet.json and the kept version's .txt and .json (no page links them), _todo.md, songbooks.toml.
LISTED = [
    "index.html",
    f"{AUTO}/info.json",
    f"{AUTO}/sheet (auto).cho",
    f"{AUTO}/sheet (auto).html",
    f"{AUTO}/sheet (auto).pdf",
    f"{AUTO}/sheet (auto).txt",
    f"{FOLDER}/guitar-1.gp5",
    f"{FOLDER}/info.json",
    f"{FOLDER}/sheet.cho",
    f"{FOLDER}/sheet.html",
    f"{FOLDER}/sheet.pdf",
    f"{FOLDER}/sheet.txt",
    f"{FOLDER}/version-{KEPT}.html",
    f"{BOOK}/songbook.html",
    f"{BOOK}/songbook.pdf",
]


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=3)


@pytest.fixture
def app(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def songbook(conn, cfg):
    """Campfire, with its page as caracole songbook render writes and records it, and its PDF."""
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Soda Stereo - De Música Ligera"])
    folder = cfg.library_dir / BOOK
    folder.mkdir(parents=True)
    page = build_viewer("{title: Campfire}\n[G]La la la\n").encode("utf-8")
    (folder / "songbook.html").write_bytes(page)
    (folder / "songbook.pdf").write_bytes(b"%PDF-1.4 fake\n")
    kv_set_json(conn, f"{RECORD_KEY}Campfire", {"inputs": {}, "files": {
        "songbook.html": {"sha256": hashlib.sha256(page).hexdigest(), "size": len(page)}}})


def write_pages(conn, cfg):
    todo.write_pages(conn, cfg, Overrides(), NOW)


@pytest.fixture
def library(conn, cfg):
    """An auto sheet; De Música Ligera's sheet, a version kept beside it with its page, and a Guitar Pro file; a
    songbook; and the pages written, as any command leaves them."""
    rendered_song(conn, cfg, "Placeholder Band", "Synthetic Song", auto=True)
    song = versioned_song(conn, cfg)
    keep_guitar(conn, cfg, song, GP5, name="guitar-1.gp5")
    songbook(conn, cfg)
    write_pages(conn, cfg)
    return cfg.library_dir


def manifest(app, **headers):
    response = get(app, "/api/offline", **headers)
    assert response.status == 200, response.body[:300]
    assert header(response, "content-type") == JSON_TYPE
    return json.loads(response.body)


def paths(listed):
    return [entry["path"] for entry in listed["files"]]


def served(response):
    """The headers of an answer the manifest may name, as it names them."""
    found = {}
    for name, value in response.headers:
        if name in NAMES:
            assert name not in found, name
            found[name] = value
    return found


# --- what it lists ---------------------------------------------------------------------------------------


def test_the_manifest_lists_the_library_page_first_then_each_file_it_links_to(app, library):
    listed = manifest(app)
    assert listed["format"] == 1 and listed["start"] == "index.html"
    assert paths(listed) == LISTED
    assert paths(listed)[1:] == sorted(paths(listed)[1:])  # by path, after the page the app opens first
    assert listed["files"][0]["url"] == "/offline/index.html"
    assert all(sorted(entry) == ["headers", "path", "sha256", "size", "type", "url"] for entry in listed["files"])


def test_each_address_answers_exactly_the_bytes_type_and_headers_listed(app, library):
    for entry in manifest(app)["files"]:
        assert entry["url"].startswith("/") and not entry["url"].startswith("//")
        response = get(app, entry["url"])
        assert response.status == 200, entry["path"]
        assert len(response.body) == entry["size"]
        assert hashlib.sha256(response.body).hexdigest() == entry["sha256"]
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        assert header(response, "content-type") == entry["type"]
        assert served(response) == entry["headers"], entry["path"]
        if entry["path"] != "index.html":  # the file in the library, as the pages link it
            assert response.body == (library / entry["path"]).read_bytes()


def test_the_addresses_are_the_paths_percent_encoded(app, conn, cfg):
    rendered_song(conn, cfg, "Placeholder Band", "Synthetic Song", auto=True)
    rendered_song(conn, cfg)
    rendered_song(conn, cfg, "Guns N' Roses", "100% #1 Hit")
    write_pages(conn, cfg)
    urls = {entry["path"]: entry["url"] for entry in manifest(app)["files"]}
    assert urls[f"{FOLDER}/sheet.pdf"] == "/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.pdf"
    assert urls[f"{AUTO}/sheet (auto).html"] == "/Placeholder%20Band/Synthetic%20Song/sheet%20%28auto%29.html"
    assert urls["Guns N' Roses/100% #1 Hit/sheet.html"] == "/Guns%20N%27%20Roses/100%25%20%231%20Hit/sheet.html"
    for path, url in urls.items():
        assert path and not path.startswith("/") and "\\" not in path and "\x00" not in path
        assert not {".", "..", ""} & set(path.split("/"))
        assert get(app, url).status == 200, path


def test_a_written_page_goes_with_its_own_policy_in_a_sandbox_and_the_library_page_with_its_own(app, library):
    listed = {entry["path"]: entry for entry in manifest(app)["files"]}
    for path in (f"{FOLDER}/sheet.html", f"{AUTO}/sheet (auto).html", f"{FOLDER}/version-{KEPT}.html",
                 f"{BOOK}/songbook.html"):
        own = META_POLICY.search((library / path).read_text(encoding="utf-8")).group(1)
        assert listed[path]["type"] == HTML
        assert listed[path]["headers"] == {"Content-Security-Policy": f"sandbox allow-scripts; {own}; "
                                                                      "frame-ancestors 'none'",
                                           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin"}
    # The library page is the file on disk (no form, no request: form-action 'none' and nothing to connect to),
    # with the policy its <meta> tag holds, as caracole serve sends its own library page: no sandbox, so its
    # links to the sites and its downloads work.
    page = (library / "index.html").read_text(encoding="utf-8")
    own = META_POLICY.search(page).group(1)
    assert "form-action 'none'" in own and "connect-src" not in own and 'name="csrf"' not in page
    assert listed["index.html"]["type"] == HTML
    assert listed["index.html"]["headers"]["Content-Security-Policy"] == f"{own}; frame-ancestors 'none'"
    assert listed[f"{FOLDER}/sheet.pdf"]["type"] == "application/pdf"
    assert listed[f"{FOLDER}/guitar-1.gp5"]["type"] == "application/octet-stream"
    assert listed[f"{FOLDER}/sheet.txt"]["type"] == "text/plain; charset=utf-8"


def test_the_same_library_gives_the_same_answer(app, library):
    first = get(app, "/api/offline").body
    assert get(app, "/api/offline").body == first


# --- only what serve sends now ------------------------------------------------------------------------------


def test_a_page_no_longer_as_caracole_wrote_it_is_left_out(app, library):
    sheet = library / FOLDER / "sheet.html"
    sheet.write_bytes(sheet.read_bytes() + b"<script>fetch('/caracole.sqlite')</script>")
    listed = paths(manifest(app))
    assert f"{FOLDER}/sheet.html" not in listed
    assert listed == [p for p in LISTED if p != f"{FOLDER}/sheet.html"]


def test_a_link_in_a_files_place_and_a_file_gone_are_left_out(app, library, tmp_path):
    pdf = library / FOLDER / "sheet.pdf"
    elsewhere = tmp_path / "elsewhere.pdf"
    elsewhere.write_bytes(pdf.read_bytes())
    pdf.unlink()
    pdf.symlink_to(elsewhere)
    (library / AUTO / "sheet (auto).txt").unlink()
    listed = paths(manifest(app))
    assert f"{FOLDER}/sheet.pdf" not in listed and f"{AUTO}/sheet (auto).txt" not in listed
    assert len(listed) == len(LISTED) - 2


def test_a_file_no_page_links_is_left_out(app, library):
    folder = library / FOLDER
    (folder / "notes.txt").write_text("my own notes\n", encoding="utf-8")  # a kind serve sends, linked nowhere
    (folder / "notes.html").write_bytes((folder / "sheet.html").read_bytes())  # caracole's bytes, its name never
    (folder / ".hidden.pdf").write_bytes(b"%PDF-1.4\n")
    (library / ".stfolder").mkdir()
    (library / ".stfolder" / "x.pdf").write_bytes(b"%PDF-1.4\n")
    assert paths(manifest(app)) == LISTED


def test_nothing_in_music_the_inbox_or_at_an_address_another_route_answers(conn, cfg, queue):
    # Folders of songs whose names are those of Music/ (when it is inside the library), of _inbox/, and of an
    # address caracole serve answers itself (/api/jobs/…): the library page links them, the copy leaves them out.
    inside = dataclasses.replace(cfg, music_dir=cfg.library_dir / "Music")
    app = WebApp(inside, queue, allowed=ALLOWED, csrf="tok")
    rendered_song(conn, inside, "Soda Stereo", "De Música Ligera")
    for artist, title in (("Music", "Album"), ("_inbox", "Dropped"), ("api", "jobs")):
        song = rendered_song(conn, inside, artist, title)
        assert (song_dir(inside.library_dir, song) / "sheet.html").is_file()
    todo.write_pages(conn, inside, Overrides(), NOW)
    page = (inside.library_dir / "index.html").read_text(encoding="utf-8")
    assert "Music/Album/sheet.html" in page and "_inbox/Dropped/sheet.html" in page  # linked
    listed = paths(manifest(app))
    assert listed[0] == "index.html" and f"{FOLDER}/sheet.html" in listed
    assert not [p for p in listed if p.split("/")[0] in ("Music", "_inbox", "api")]


def test_without_the_library_page_as_written_there_is_no_copy(app, library):
    # The app opens the library page first: without it, its last copy stays whole rather than one with no start.
    index = library / "index.html"
    index.write_bytes(index.read_bytes().replace(b"<body", b"<BODY", 1))  # the same length
    response = get(app, "/api/offline")
    assert response.status == 503 and header(response, "content-type") == JSON_TYPE
    assert "caracole todo" in json.loads(response.body)["error"]
    refused = get(app, "/offline/index.html")
    assert refused.status == 404 and b"<script" not in refused.body
    assert "caracole todo writes it again" in text(refused)


def test_a_library_page_caracole_kept_no_record_of_is_not_sent(app, conn, cfg):
    # As one written before caracole kept the record: the next command that writes the pages records it.
    rendered_song(conn, cfg)
    write_library_page(cfg.library_dir, "<!doctype html>\n<title>an older page</title>\n")
    assert get(app, "/api/offline").status == 503
    assert get(app, "/offline/index.html").status == 404
    write_pages(conn, cfg)
    assert get(app, "/offline/index.html").body == (cfg.library_dir / "index.html").read_bytes()
    assert paths(manifest(app))[0] == "index.html"


def test_the_library_page_is_one_of_the_pages_caracole_writes():
    # Served as the sheet viewers are (files.read_written_page), by its own record and policy.
    from caracole import library_page
    from caracole.web.app import written_pages

    page = written_pages()[library_page.PAGE_NAME]
    assert page.written is library_page.pages_written and page.csp is library_page.page_csp
    assert page.refused == library_page.PAGE_REFUSED


def test_the_library_page_is_served_as_written(app, library):
    response = get(app, "/offline/index.html")
    assert response.status == 200
    assert response.body == (library / "index.html").read_bytes()
    assert header(response, "content-type") == HTML
    assert header(response, "x-frame-options") == "DENY" and header(response, "cache-control") == "no-store"
    assert app.handle(Request("HEAD", "/offline/index.html", {"host": HOST})).status == 200
    assert get(app, "/" + quote(f"{FOLDER}/index.html")).status == 404  # the library page's record is for its own


# --- a read, from the app ------------------------------------------------------------------------------------


@pytest.mark.parametrize("site,allowed", [
    (None, True),  # the app, or any client that is no browser
    ("same-origin", True),
    ("none", True),
    ("same-site", False),
    ("cross-site", False),
])
def test_another_sites_page_cant_read_it_and_the_app_can(app, library, site, allowed):
    response = get(app, "/api/offline", **({"sec-fetch-site": site} if site else {}))
    if allowed:
        assert response.status == 200 and json.loads(response.body)["format"] == 1
    else:
        assert response.status == 403 and "another site" in json.loads(response.body)["error"]


def test_the_manifest_asks_no_site_takes_no_lock_and_writes_nothing(app, library, conn, queue, monkeypatch):
    from caracole.commands import _common

    def never(*args, **kwargs):
        raise AssertionError("the manifest asked a site, or took the lock")

    monkeypatch.setattr(_common, "make_client", never)
    monkeypatch.setattr(_common, "exclusive", never)

    def tree():
        return {p.relative_to(library).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in sorted(library.rglob("*")) if p.is_file()}

    before = tree(), conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall()
    manifest(app)
    get(app, "/offline/index.html")
    assert (tree(), conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall()) == before
    assert queue.snapshot() == []


def test_a_host_name_the_server_doesnt_answer_to_gets_nothing(app, library):
    response = app.handle(Request("GET", "/api/offline", {"host": "evil.example"}))
    assert response.status == 421 and b"index.html" not in response.body


# --- in a browser ----------------------------------------------------------------------------------------------


@in_chromium
def test_the_library_page_runs_under_the_policy_it_is_sent_with(app, library):
    # The headers the app hands the WebView with the page are serve's: under them the page's script still runs.
    from caracole.web.server import make_server

    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        dom = browser.dump_dom(f"http://127.0.0.1:{server.server_address[1]}/offline/index.html", (390, 844))
    finally:
        server.shutdown()
        server.server_close()
    shown = re.search(r'<main[^>]*id="list"[^>]*>(.*?)</main>', dom, re.S).group(1)
    assert re.search(r"<h3[^>]*>De Música Ligera</h3>", shown) and re.search(r"<h3[^>]*>Synthetic Song</h3>", shown)


# --- in the app's copy -----------------------------------------------------------------------------------------

APP_HOST = "appassets.androidplatform.net"  # androidx.webkit's WebViewAssetLoader: where the app's WebView reads it
# What a page offers that only caracole serve answers, as the page shows it: a viewer's Export PDF, its versions'
# actions, its Guitar Pro links, any link to an address of the server's; the library page's lines, forms and
# command lines; and what the page asked for besides itself.
VIEWER_CONTROLS = """JSON.stringify({
  export: [...document.querySelectorAll('#export, #export-cmd, #export-copy')].map((e) =>
    [e.id, e.hidden, e.getAttribute('href'), e.id === 'export-cmd' ? e.textContent : null]),
  guitar: [...document.querySelectorAll('#guitar-links a')].map((a) =>
    [a.textContent, a.getAttribute('href'), a.getAttribute('download')]),
  hint: (document.getElementById('guitar-hint') || {}).textContent,
  versions: [...document.querySelectorAll('#ver-acts > *, #ver-items .ver-acts > *')].map((e) =>
    [e.tagName, e.textContent, e.getAttribute('href')]),
  server: [...document.querySelectorAll('a[href^="/"]')].map((a) => a.getAttribute('href')),
  fetched: performance.getEntriesByType('resource').map((r) => r.name),
})"""
LIBRARY_CONTROLS = """JSON.stringify({
  lines: document.querySelectorAll('main#list article.line').length,
  commands: [...document.querySelectorAll('code')].map((c) => c.textContent).filter((t) => t.startsWith('caracole ')),
  forms: document.forms.length,
  server: [...document.querySelectorAll('a[href^="/"]')].map((a) => a.getAttribute('href')),
  fetched: performance.getEntriesByType('resource').map((r) => r.name),
})"""


@contextmanager
def app_copy(app):
    """The Android app's copy of the library as its WebView reads it, the app's PathHandler in small: each file of
    the manifest at ``/library/<path>`` on APP_HOST (over plain HTTP here: the pages go by the host's name), with
    its type and its headers, 404 for anything else. Yields the copy's address and every path asked for."""
    files = {}
    for entry in manifest(app)["files"]:
        files[entry["path"]] = (get(app, entry["url"]).body, entry["type"], entry["headers"])
    asked: list[str] = []

    class Copy(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            asked.append(path)
            found = files.get(path.removeprefix("/library/")) if path.startswith("/library/") else None
            if found is None:
                self.send_error(404)
                return
            body, kind, headers = found
            self.send_response(200)
            self.send_header("Content-Type", kind)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Copy)
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        yield f"http://{APP_HOST}:{server.server_address[1]}/library/", asked
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def versioned(conn, cfg):
    """A sheet with two versions kept beside it and a third UG lists, and a Guitar Pro file, rendered as the
    nightly run leaves them; the pages written."""
    from test_render_versions import render, song_with_versions

    song = song_with_versions(conn, cfg)
    keep_guitar(conn, cfg, song, GP5, name="guitar-1.gp5")
    render(conn, cfg)
    write_pages(conn, cfg)
    return cfg.library_dir


@in_chromium
def test_in_the_apps_copy_a_viewer_offers_what_it_offers_from_a_file(app, versioned, tmp_path):
    # The copy is read like the folder: no caracole serve answers there, so the viewer shows the commands, and the
    # Guitar Pro files themselves, never a link to the server's Export, versions or Guitar Pro pages.
    from helpers.chromium import Chromium

    pages = (f"{AUTO}/sheet.html", f"{AUTO}/version-39144.html")
    with app_copy(app) as (copy, asked), Chromium(tmp_path / "profile", local=[APP_HOST]) as browser:
        for path in pages:
            seen = {}
            for where, url in (("copy", copy + quote(path)), ("file", (versioned / path).as_uri())):
                tab = browser.open(url)
                tab.wait_for("document.documentElement.dataset.ready === '1'")
                tab.eval("document.getElementById('t-up').click()")  # a semitone up: Export names that version
                seen[where] = json.loads(tab.eval(VIEWER_CONTROLS))
            assert seen["copy"] == seen["file"], path
            controls = seen["copy"]
            if path.endswith("/sheet.html"):  # a version's page exports nothing: the sheet's PDF is the one's
                assert [(name, hidden) for name, hidden, _, _ in controls["export"]] == [
                    ("export", True), ("export-cmd", False), ("export-copy", False)]
                assert controls["export"][1][3].startswith("caracole render --song 'Placeholder Band - Synthetic Song'")
            assert controls["guitar"] == [["guitar-1.gp5", "guitar-1.gp5", "Placeholder Band - Synthetic Song.gp5"]]
            assert controls["versions"] and all(tag == "BUTTON" or href.startswith("https://tabs.ultimate-guitar.com/")
                                                for tag, _, href in controls["versions"])
            assert controls["server"] in ([], ["/export"]) and controls["fetched"] == []  # /export: its link, hidden
    assert asked == ["/library/" + path for path in pages]


@in_chromium
def test_in_the_apps_copy_the_library_page_asks_nothing_as_from_a_file(app, versioned, tmp_path):
    # Its served script's forms, its search of the sites and its requests' lines come with caracole serve's own
    # page alone: the copy's, as the file, names the command to run and asks nothing of anyone.
    from helpers.chromium import Chromium

    with app_copy(app) as (copy, asked), Chromium(tmp_path / "profile", local=[APP_HOST]) as browser:
        seen = {}
        for where, url in (("copy", copy + "index.html"), ("file", (versioned / "index.html").as_uri())):
            tab = browser.open(url + "#q=" + quote("wonderwall"))
            tab.wait_for("[...document.querySelectorAll('code')].some((c) => c.textContent.startsWith('caracole search'))")
            seen[where] = json.loads(tab.eval(LIBRARY_CONTROLS))
    assert seen["copy"] == seen["file"]
    assert "caracole search 'wonderwall'" in seen["copy"]["commands"]
    assert seen["copy"]["server"] == [] and seen["copy"]["fetched"] == []
    assert asked == ["/library/index.html"]
