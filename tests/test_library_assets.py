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
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))  # every template
    for name in TEMPLATES:
        text = text_of(name)
        pieces = re.split(r"__[A-Z]+__", text)
        assert len(pieces) > 1 or name == "requested.html", name  # each but one has a blank to fill
        assert all(piece in html for piece in pieces), name
        assert not re.search(r"__[A-Z]+__", html)  # and none is left


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

    # A request's steps: the requests page's running card and the library page's song lines draw the same chips.
    assert pages.PAGE_STYLE.startswith(text_of("base.css") + text_of("picker.css") + text_of("steps.css"))
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
