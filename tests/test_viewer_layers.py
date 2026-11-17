"""A viewer page's layers in the browser's history (viewer/layers.js, ``window.caracoleLayers``).

Each layer a page opens over its sheet is one entry of the tab's history while it is open, so that the browser's Back
(a phone's, the app's) closes the one on top rather than leaving the page; a layer the page closes itself takes its
entry off again. ``caracoleLayers.history(back)`` is that history's side: the page says how many layers are open
(``sync(count)``), and hears how many a Back took off (``back(k)``).

"The history" drives it on a bare page of two buttons, one that opens a layer and one that shuts one, opened from
about:blank, so that the page is the history's entry 1; Back and Forward are the browser's own (helpers/viewer_pages.py
``back``, ``forward``, ``entries``).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from caracole.viewer import build_viewer, page
from caracole.viewer.book import BookSong, build_songbook
from caracole.viewer.harptab_page import build_harmonica_viewer

from helpers.browser import Browser, in_chromium
from helpers.viewer_pages import back, entries, forward, viewer as open_viewer

FIXTURES = Path(__file__).parent / "fixtures"
UG_CHO = (FIXTURES / "chordpro" / "ug_sheet.cho").read_text(encoding="utf-8")


# --- the history ---------------------------------------------------------------------------------------------------

BARE = """
window.n = 0; window.backs = []; window.pops = 0;
addEventListener("popstate", () => pops++);
const h = caracoleLayers.history((k) => { backs.push(k); n -= k; h.sync(n); });
document.getElementById("open").onclick = () => h.sync(++n);
document.getElementById("shut").onclick = () => h.sync(--n);
document.documentElement.dataset.ready = "1";
"""


def bare(tmp_path: Path, name: str = "bare.html") -> str:
    """A page of two buttons, #open and #shut, each a layer opened or shut, with layers.js's history; its address."""
    layers = (page.HERE / "layers.js").read_text(encoding="utf-8")
    path = tmp_path / name
    path.write_text('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>Bare</title></head><body>\n'
                    '<button id="open">Open</button> <button id="shut">Shut</button>\n'
                    f"<script>{layers}</script>\n<script>{BARE}</script>\n</body></html>\n", encoding="utf-8")
    return path.as_uri()


def until(b: Browser, want: tuple[int, int], timeout: float = 10.0) -> tuple[int, int]:
    """The tab's history (``entries``) once it is ``want``, or as it is ``timeout`` seconds on: the browser hears of
    an entry a page pushed, or of a step it took, a moment after the page made it."""
    deadline = time.monotonic() + timeout
    found = entries(b)
    while found != want and time.monotonic() < deadline:
        time.sleep(0.03)
        found = entries(b)
    return found


@in_chromium
def test_each_layer_opened_is_one_entry_and_back_takes_one_off_saying_so(tmp_path):
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.js("window.marker = 1")
        assert entries(b) == (1, 2)  # about:blank, then the page
        b.click("#open")
        b.click("#open")
        assert until(b, (3, 4)) == (3, 4)  # a layer, then one over it
        assert b.js("history.state.caracoleLayer") == 2
        back(b)
        assert b.wait("backs.length === 1")
        assert b.js("[backs, n]") == [[1], 1]  # Back took one off, and said so
        assert entries(b)[0] == 2
        back(b)
        assert b.wait("backs.length === 2")
        assert b.js("backs") == [1, 1]
        assert entries(b)[0] == 1
        assert b.js("window.marker") == 1  # the same document: no page left, none loaded


@in_chromium
def test_a_layer_the_page_closes_takes_its_entry_off_and_says_nothing(tmp_path):
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.click("#open")
        assert until(b, (2, 3)) == (2, 3)
        b.click("#shut")
        assert until(b, (1, 3)) == (1, 3)  # its entry off: the page's own again
        assert b.js("backs") == []
        back(b)
        assert b.wait("location.href === 'about:blank'")  # Back leaves the page, as it would with no layer opened


@in_chromium
def test_opened_and_shut_in_one_task_is_no_entry(tmp_path):
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.js("for (const id of ['open', 'shut', 'open']) document.getElementById(id).click()")
        assert until(b, (2, 3)) == (2, 3)  # one layer open at the task's end: one entry
        assert b.js("[history.state.caracoleLayer, pops]") == [1, 0]  # pushed once, never taken back


@in_chromium
def test_fewer_than_no_layer_is_none_and_never_leaves_the_page(tmp_path):
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.js("window.marker = 1")
        b.click("#shut")  # a count below 0
        b.js("typeof h === 'undefined' || h.sync(NaN)")  # or none at all
        b.js("typeof h === 'undefined' || h.sync(n = 1)")  # then a layer: the page still listens
        assert b.wait("location.href === 'about:blank' || (history.state && history.state.caracoleLayer === 1)")
        assert b.js("[location.pathname.endsWith('/bare.html'), window.marker]") == [True, 1]  # neither left nor loaded
        assert until(b, (2, 3)) == (2, 3)


@in_chromium
def test_forward_onto_a_layers_entry_with_none_open_comes_back(tmp_path):
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.click("#open")
        assert until(b, (2, 3)) == (2, 3)
        back(b)
        assert b.wait("backs.length === 1")
        assert entries(b)[0] == 1
        forward(b)  # onto the layer's entry, with no layer open
        assert until(b, (1, 3)) == (1, 3)  # back on the entry of what is open
        assert b.js("[backs, n, history.state]") == [[1], 0, None]


@in_chromium
def test_a_page_come_back_to_at_a_layers_entry_goes_back_to_its_own(tmp_path):
    other = bare(tmp_path, "other.html")
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.click("#open")
        assert until(b, (2, 3)) == (2, 3)
        b.js(f"location.href = {json.dumps(other)}")  # a layer's link, say: another page, from the layer's entry
        assert b.wait("location.pathname.endsWith('/other.html') && document.documentElement.dataset.ready === '1'")
        assert entries(b) == (3, 4)
        back(b)  # the page loads again at its layer's entry, with no layer open
        assert b.wait("location.pathname.endsWith('/bare.html') && document.documentElement.dataset.ready === '1'"
                      " && (!history.state || !history.state.caracoleLayer)")
        assert until(b, (1, 4)) == (1, 4)
        assert b.js("backs") == []  # nothing open to close


@in_chromium
def test_a_history_that_refuses_entries_leaves_back_to_the_browser(tmp_path):
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.js("""history.pushState = () => { throw new DOMException("denied", "SecurityError"); };
                window.errors = []; addEventListener("error", (e) => errors.push(String(e.message)));""")
        for button in ("#open", "#shut", "#open"):
            b.click(button)
        assert b.wait("n === 1")
        assert b.js("errors") == []  # the layers still open and shut, with no error
        assert until(b, (1, 2)) == (1, 2)  # and no entry: Back leaves the page, as before
        assert b.js("backs") == []


# --- every viewer page ---------------------------------------------------------------------------------------------

def inlined(name: str) -> str:
    """viewer/'s script ``name`` as a page inlines it."""
    return f"<script>{(page.HERE / name).read_text(encoding='utf-8')}</script>"


def test_every_viewer_page_inlines_layers_js_before_its_own_script():
    layers = f"<script>{page._layers()}</script>"
    pages = [
        (build_viewer(UG_CHO), "winds.js", "viewer.js"),
        (build_songbook("Book", [BookSong("Title", "Artist", cho=UG_CHO, id="aaaa")]), "winds.js", "viewer.js"),
        (build_harmonica_viewer("4 -4 5", title="T", tab_file="harmonica-1.txt"), "overlay.js", "harptab.js"),
    ]
    for html, after, before in pages:
        assert html.count(layers) == 1
        # before the page's own script, never right before: kinds.js and screen.js come between them
        assert html.index(inlined(after)) < html.index(layers) < html.index(inlined(before)), (after, before)
    assert page.HERE / "layers.js" in page.BUILD_FILES
    # It makes no element of its own and loads nothing.
    for word in ("innerHTML", "createElement", "fetch(", "XMLHttpRequest", "import(", "eval(", "new Function"):
        assert word not in page._layers(), word
