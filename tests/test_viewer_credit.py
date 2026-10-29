"""An auto sheet's credit on its viewer: the YouTube video its audio came from, which render.py gives the page as its
data's ``video`` (test_render_all.py) and viewer.js draws under the notice: YouTube's mark, the video's title a link
to it, and its channel, muted. No address and no "Audio from YouTube" on the page; served in its sandbox, the link
opens YouTube in the same tab, as the page's other links do, with no flag added to the sandbox."""

from __future__ import annotations

import base64
import http.server
import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from helpers.browser import in_chromium
from helpers.icon_files import png
from helpers.viewer_pages import viewer

from caracole.chordpro import to_chordpro
from caracole.icons import sanitize
from caracole.viewer import build_viewer, viewer_csp

URL = "https://www.youtube.com/watch?v=lzN7Thn3FV4"
ICON = "data:image/png;base64," + base64.b64encode(sanitize(png(32))).decode("ascii")
VIDEO = {"title": "Somos vikingos veganos - Hyperfanes", "href": URL, "channel": "kintanedu",
         "mark": {"name": "YouTube", "letters": "YT", "src": ICON}}
# An auto sheet from YouTube as render.py hands it to its viewer: without the line naming the video, which is
# the page's data instead.
AUTO = to_chordpro("[ch]Em[/ch]       [ch]C[/ch]\nSomos vikingos de prueba\n[ch]G[/ch]        [ch]D[/ch]\n"
                   "comemos lechuga de prueba\n", title="Vikingos veganos", artist="Nick Cani", auto=True)
FOLDER = Path("Nick Cani") / "Vikingos veganos"


def data_of(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S).group(1))


def test_the_page_carries_the_video_in_its_data_and_its_place_under_the_notice():
    html = build_viewer(AUTO, video=VIDEO)
    assert data_of(html)["video"] == VIDEO
    assert re.search(r'<p class="notice">[^<]*</p>\n<p class="credit" id="credit" hidden></p>\n', html)


def test_a_page_given_no_video_has_neither():
    html = build_viewer(AUTO)
    assert "video" not in data_of(html) and 'id="credit"' not in html


# --- drawn, in Chromium ------------------------------------------------------------------------------------------


# What the credit shows: its mark (what it is, its icon, its name for a screen reader, its letters), its link (its
# text, where it goes, whether it opens another window), its channel, and the page's text as a reader sees it.
CREDIT = """(() => {
  const box = document.getElementById("credit");
  const mark = box.querySelector(".source");
  const links = [...box.querySelectorAll("a")];
  const r = box.getBoundingClientRect();
  return {shown: !box.hidden && r.height > 0, afterNotice: document.querySelector(".notice").nextElementSibling === box,
          mark: mark && [mark.tagName, mark.getAttribute("src"), mark.getAttribute("alt") || mark.getAttribute("aria-label"),
                         mark.textContent],
          links: links.map((a) => [a.textContent, a.getAttribute("href"), a.getAttribute("target")]),
          channel: [...box.querySelectorAll(".channel")].map((c) => c.textContent),
          text: document.body.innerText, sideways: document.documentElement.scrollWidth > innerWidth};
})()"""


def written(tmp_path: Path, html: str) -> Path:
    page = tmp_path / FOLDER / "sheet (auto).html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")
    return page


def assert_drawn(seen: dict, mark: list) -> None:
    assert seen["shown"] and seen["afterNotice"]
    assert seen["mark"] == mark
    assert seen["links"] == [["Somos vikingos veganos - Hyperfanes", URL, None]]  # in this tab: the sandbox's rule
    assert seen["channel"] == ["kintanedu"]
    assert "Audio from YouTube" not in seen["text"] and "youtube.com" not in seen["text"]
    assert "Auto-generated, unverified" in seen["text"]  # the notice, as it was
    assert not seen["sideways"]


@in_chromium
def test_from_the_file_the_credit_is_youtubes_icon_then_the_videos_title_a_link_to_it_and_its_channel(tmp_path):
    with viewer(tmp_path, written(tmp_path, build_viewer(AUTO, video=VIDEO)).as_uri()) as b:
        assert_drawn(b.js(CREDIT), ["IMG", ICON, "from YouTube", ""])


@in_chromium
def test_with_no_icon_kept_the_mark_is_youtubes_lettered_badge(tmp_path):
    lettered = {**VIDEO, "mark": {"name": "YouTube", "letters": "YT"}}
    with viewer(tmp_path, written(tmp_path, build_viewer(AUTO, video=lettered)).as_uri()) as b:
        assert_drawn(b.js(CREDIT), ["SPAN", None, "from YouTube", "YT"])


@in_chromium
def test_an_address_that_isnt_a_youtube_videos_is_drawn_as_no_link(tmp_path):
    # render.py writes a watch address from the video's id alone; anything else in its place is no link at all.
    for href in ("javascript:alert(1)", "https://example.com/watch?v=lzN7Thn3FV4"):
        page = written(tmp_path, build_viewer(AUTO, video={**VIDEO, "href": href}))
        with viewer(tmp_path, page.as_uri()) as b:
            assert b.js("document.getElementById('credit').hidden && !document.querySelector('#credit a')")


@contextmanager
def served(root: Path) -> Iterator[str]:
    """``root``'s files over HTTP on 127.0.0.1, each viewer with the policy and the sandbox caracole serve gives it."""
    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            from urllib.parse import unquote, urlsplit

            path = root / unquote(urlsplit(self.path).path).lstrip("/")
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


@in_chromium
def test_served_in_its_sandbox_the_link_opens_the_video_on_youtube_in_this_tab(tmp_path):
    written(tmp_path, build_viewer(AUTO, video=VIDEO))
    with served(tmp_path) as root, viewer(tmp_path, f"{root}/{quote(FOLDER.as_posix())}/sheet%20(auto).html") as b:
        assert b.js("origin") == "null"  # the sandbox: an origin of its own
        assert_drawn(b.js(CREDIT), ["IMG", ICON, "from YouTube", ""])
        # No name resolves in the tests' Chromium: YouTube's answer is the test's, given to the navigation held.
        b.send("Fetch.enable", patterns=[{"urlPattern": "https://www.youtube.com/*"}])
        b.events.clear()
        b.click("#credit a")
        held = b.event("Fetch.requestPaused")
        assert held is not None, "the sandbox let the link go nowhere"
        assert held["request"]["url"] == URL
        b.send("Fetch.fulfillRequest", requestId=held["requestId"], responseCode=200,
               responseHeaders=[{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
               body=base64.b64encode(b"<!doctype html><title>YouTube</title><p>a video</p>").decode("ascii"))
        assert b.wait(f"location.href === {json.dumps(URL)} && document.readyState === 'complete'")
        assert b.js("origin") == "https://www.youtube.com"  # YouTube's own page, out of the viewer's sandbox
