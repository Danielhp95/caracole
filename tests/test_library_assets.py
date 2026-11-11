"""caracole/library_assets/: index.html's stylesheets and scripts, as files, inlined as they are."""

import re
from datetime import UTC, datetime

from caracole.inline import sha256_source
from caracole.overrides import Overrides

from conftest import add_song

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)
POLICY = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">')


def text_of(name):
    from caracole.library_assets import HERE

    return (HERE / name).read_bytes().decode("utf-8")


def test_index_html_holds_its_stylesheets_and_scripts_as_their_files_have_them(conn, cfg):
    from caracole.library_page import SCRIPTS, STYLESHEETS, WebControls, build_library_page

    add_song(conn, "Radiohead", "Creep")
    for controls in (None, WebControls(csrf="tok")):
        html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
        (style,) = re.findall(r"<style>(.*?)</style>", html, re.S)
        (script,) = re.findall(r"<script>(.*?)</script>", html, re.S)
        assert style == "".join(text_of(name) for name in STYLESHEETS)
        assert script == "".join(text_of(name) for name in SCRIPTS)
        csp = POLICY.search(html).group(1)
        assert f"script-src {sha256_source(script)};" in csp and f"style-src {sha256_source(style)};" in csp


def test_index_html_is_its_templates_filled_in(conn, cfg):
    from caracole.library_page import TEMPLATES, WebControls, build_library_page

    add_song(conn, "Radiohead", "Creep")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", sync="tab"))  # every one
    whole = ("requested.html", "sync-tab.html", "sync-panel.html", "sync-sheet.html")  # put in as they are
    for name in TEMPLATES:
        text = text_of(name)
        pieces = re.split(r"__[A-Z]+__", text)
        assert len(pieces) > 1 or name in whole, name  # the others have a blank to fill
        assert all(piece in html for piece in pieces), name
        assert not re.search(r"__[A-Z]+__", html)  # and none is left


def test_the_sync_tab_is_its_templates_after_requests_and_only_where_the_server_syncs(conn, cfg):
    from caracole.library_page import WebControls, build_library_page

    tab, panel, sheet = text_of("sync-tab.html"), text_of("sync-panel.html"), text_of("sync-sheet.html")
    synced = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", sync="tab"))
    assert tab in synced and panel in synced and synced.count(sheet) == 1
    assert synced.index('id="tab-requests"') < synced.index('id="tab-sync"')  # Sync last
    assert synced.index('id="requests"') < synced.index('id="sync"') < synced.index('id="sync-sheet"')
    # The phone's page: the sheet alone, which its app's sync button opens.
    phone = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", sync="sheet"))
    assert tab not in phone and panel not in phone and phone.count(sheet) == 1
    for page in (build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok")),
                 build_library_page(conn, cfg, Overrides(), NOW)):
        assert 'id="tab-sync"' not in page and 'id="sync"' not in page and 'id="sync-sheet"' not in page


def test_the_page_is_assembled_from_its_data_alone(conn, cfg):
    import json

    from caracole.library_page import WebControls, assemble_page, build_library_page

    add_song(conn, "Radiohead", "Creep")
    for controls in (None, WebControls(csrf="tok", sync="tab"), WebControls(csrf="tok", sync="sheet")):
        notes = []
        html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls, note=notes.append)
        (data,) = notes
        assert assemble_page(json.loads(json.dumps(data)), controls, problem=None if controls is None else
                             _problem(cfg), library_name=cfg.library_name) == html


def _problem(cfg):
    from caracole.youtube_fetch import route_reason

    return route_reason(cfg)


def test_every_file_of_the_folder_is_text_index_html_inlines():
    from caracole.library_assets import HERE
    from caracole.library_page import SCRIPTS, STYLESHEETS, TEMPLATES

    names = sorted(p.name for p in HERE.iterdir() if p.suffix in (".css", ".js", ".html"))
    assert names == sorted(STYLESHEETS + SCRIPTS + TEMPLATES)
    for name in names:
        data = (HERE / name).read_bytes()
        # Read as bytes, so nothing turns a line's end into another; a page's hash is of exactly these.
        assert data.strip() and b"\r" not in data and not data.startswith(b"\xef\xbb\xbf"), name
        data.decode("utf-8")


def test_caracole_serves_own_pages_inline_the_shared_files_too():
    from caracole.web import lookup_page, pages

    # A song in review's picker: its page and the library page's song lines draw the same one.
    assert pages.PAGE_STYLE.startswith(text_of("base.css") + text_of("picker.css"))
    assert f"style-src {sha256_source(pages.PAGE_STYLE)};" in pages.PAGE_CSP
    assert lookup_page.STYLE.startswith(text_of("base.css") + text_of("rows.css"))
    html = lookup_page.lookup_page("tok")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts[0] == text_of("rows.js")
    assert all(sha256_source(s) in lookup_page.LOOKUP_CSP for s in scripts)


def test_the_caracole_mark_that_leads_home_reads_at_body_size_at_least():
    # The masthead's "caracole", a link to the library on caracole serve's pages: once a small label, now
    # big enough to find and to tap.
    from caracole.library_assets import BASE_STYLE

    rule = re.search(r"\.app \{([^}]*)\}", BASE_STYLE).group(1)
    size = re.search(r"font-size: ([\d.]+)rem", rule)
    assert size and float(size.group(1)) >= 1.05
