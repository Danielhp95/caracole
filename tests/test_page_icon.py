"""page_icon.py: the mark in the tab of every page caracole writes and serves, an inverted question mark."""

from __future__ import annotations

import base64
import re
import threading
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest
from helpers.browser import in_chromium
from helpers.chromium import Chromium

from caracole.overrides import Overrides
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

SVG_NS = "{http://www.w3.org/2000/svg}"
LINK = re.compile(r'<link rel="icon" type="image/svg\+xml" href="(data:image/svg\+xml;base64,[A-Za-z0-9+/=]+)">')
META_POLICY = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">')
HOST = "localhost:8737"
CHO = "{title: Synthetic Test Song}\n{artist: The Placeholders}\n[C]One line [G]of it\n"


def svg_of(uri: str) -> bytes:
    return base64.b64decode(uri.split(",", 1)[1], validate=True)


def allows_data_images(policy: str) -> bool:
    """Whether a Content-Security-Policy lets an image come from a data: URI: its img-src, else its
    default-src, names ``data:``."""
    directives = {d.split()[0]: d.split()[1:] for d in (p.strip() for p in policy.split(";")) if d}
    sources = directives.get("img-src", directives.get("default-src", ["*"]))
    return "data:" in sources


def library_html(conn, cfg) -> str:
    from caracole.library_page import build_library_page

    return build_library_page(conn, cfg, Overrides(), datetime(2026, 10, 21, tzinfo=UTC))


def the_pages(conn, cfg) -> dict[str, tuple[str, list[str]]]:
    """Every kind of page caracole writes or serves: its HTML, and the policies it is shown under (its own
    ``<meta>`` one, and the header a server sends with it)."""
    from caracole.viewer import build_viewer, viewer_csp
    from caracole.viewer.book import BookSong, build_songbook, songbook_csp
    from caracole.web import lookup_page, pages

    library = library_html(conn, cfg)
    viewer = build_viewer(CHO)
    book = build_songbook("Campfire", [BookSong("Synthetic Test Song", "The Placeholders", cho=CHO, id="aaaa")])
    meta = lambda html: META_POLICY.search(html).group(1)  # noqa: E731
    return {
        "index.html": (library, [meta(library)]),
        "sheet.html": (viewer, [meta(viewer), viewer_csp(viewer.encode("utf-8"))]),
        "songbook.html": (book, [meta(book), songbook_csp(book.encode("utf-8"))]),
        "message page": (pages.message_page("Not here", "Nothing here."), [pages.PAGE_CSP]),
        "lookup page": (lookup_page.lookup_page("tok"), [lookup_page.LOOKUP_CSP]),
    }


def test_the_icon_is_an_svg_of_shapes_alone_never_a_glyph():
    from caracole import page_icon

    svg = ET.fromstring(page_icon.SVG)
    assert svg.tag == f"{SVG_NS}svg" and svg.get("viewBox") == "0 0 32 32"
    tags = {e.tag.removeprefix(SVG_NS) for e in svg.iter()}
    assert "path" in tags and not tags & {"text", "tspan", "textPath", "image", "use", "foreignObject", "style",
                                          "script"}
    assert "href" not in page_icon.SVG  # it refers to nothing, not even within itself
    assert svg_of(LINK.fullmatch(page_icon.LINK.strip()).group(1)) == page_icon.SVG.encode("utf-8")


def test_the_mark_for_a_bar_is_the_icons_question_mark_alone_in_the_colour_of_its_text():
    # The icon without its square: the same dot and hook, so the two never drift apart, drawn in currentColor so the
    # page's accent (and its dark one) colours it, and hidden from a screen reader: the wordmark beside it says it.
    from caracole import page_icon

    def shapes(svg):  # the shapes and where they are, whatever their colours and namespace
        named = [(e.tag.rsplit("}", 1)[-1], {k: v for k, v in e.attrib.items() if k not in ("fill", "stroke")}) for e in svg]
        return [shape for shape in named if shape[0] != "rect"]

    mark, icon = ET.fromstring(page_icon.mark()), ET.fromstring(page_icon.SVG)
    assert shapes(mark) == shapes(icon) and len(shapes(mark)) == 2  # a dot and a hooked stroke
    assert mark.get("aria-hidden") == "true" and mark.get("focusable") == "false" and mark.get("class") == "mark"
    colours = {e.get("fill") for e in mark if e.get("fill") != "none"} | {e.get("stroke") for e in mark if e.get("stroke")}
    assert colours == {"currentColor"}
    assert "style" not in page_icon.mark() and "href" not in page_icon.mark()  # a policy needs nothing for it


def test_every_page_carries_the_icon_in_its_head_and_its_policies_allow_it(conn, cfg):
    from caracole import page_icon

    for name, (html, policies) in the_pages(conn, cfg).items():
        head = html.split("</head>", 1)[0]
        assert page_icon.LINK in head, name
        assert LINK.search(head).group(1) == page_icon.DATA_URI, name
        for policy in policies:
            assert allows_data_images(policy), (name, policy)


def test_the_viewers_policy_allows_the_icon_and_keeps_its_sandbox():
    from caracole.viewer import build_viewer, viewer_csp

    page = build_viewer(CHO)
    policy = META_POLICY.search(page).group(1)
    assert "img-src data:;" in policy and "default-src 'none'" in policy and "form-action 'none'" in policy
    assert viewer_csp(page.encode("utf-8")).startswith("sandbox allow-scripts allow-downloads; ")


def test_caracole_serve_answers_favicon_ico_with_the_mark(cfg):
    from caracole import page_icon

    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=frozenset({"localhost"}), csrf="tok")
    response = app.handle(Request("GET", "/favicon.ico", {"host": HOST}))
    headers = dict(response.headers)
    assert response.status == 200 and response.body == page_icon.SVG.encode("utf-8")
    assert headers["Content-Type"] == "image/svg+xml"
    assert headers["Content-Security-Policy"].startswith("default-src 'none'")  # opened alone, it runs nothing
    assert headers["X-Content-Type-Options"] == "nosniff"


# The icon, as Chromium loads it under the page's own policy: "loaded", or what refused it.
LOAD_ICON = """new Promise(done => {
  const refused = [];
  document.addEventListener("securitypolicyviolation", e => refused.push(e.violatedDirective));
  const image = new Image();
  image.onload = () => done(image.naturalWidth > 0 && !refused.length ? "loaded" : "refused: " + refused);
  image.onerror = () => setTimeout(() => done("refused: " + (refused.join(", ") || "not an image")), 50);
  image.src = document.querySelector('link[rel="icon"]').href;
})"""


@pytest.fixture
def served(cfg):
    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # stops within 10 ms
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@in_chromium
def test_chromium_shows_the_icon_of_a_written_and_a_served_page_with_no_violation(tmp_path, conn, cfg, served):
    from caracole.viewer import build_viewer

    sheet = tmp_path / "Artist" / "Title" / "sheet.html"
    sheet.parent.mkdir(parents=True)
    sheet.write_text(build_viewer(CHO), encoding="utf-8")
    index = tmp_path / "index.html"
    index.write_text(library_html(conn, cfg), encoding="utf-8")
    seen = {}
    with Chromium(tmp_path / "profile") as browser:
        for url in (sheet.as_uri(), index.as_uri(), f"{served}/", f"{served}/lookup", f"{served}/nothing-here"):
            tab = browser.open(url)
            tab.wait_for("document.readyState === 'complete'")
            seen[url] = tab.eval(LOAD_ICON)
    assert set(seen.values()) == {"loaded"}, seen
