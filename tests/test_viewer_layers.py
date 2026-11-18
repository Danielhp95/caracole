"""A viewer page's layers in the browser's history (viewer/layers.js, ``window.caracoleLayers``).

Each layer a page opens over its sheet is one entry of the tab's history while it is open, so that the browser's Back
(a phone's, the app's) closes the one on top rather than leaving the page; a layer the page closes itself takes its
entry off again. ``caracoleLayers.history(back)`` is that history's side: the page says how many layers are open
(``sync(count)``), and hears how many a Back took off (``back(k)``).

"The history" drives it on a bare page of two buttons, one that opens a layer and one that shuts one, opened from
about:blank, so that the page is the history's entry 1; Back and Forward are the browser's own (helpers/viewer_pages.py
``back``, ``forward``, ``entries``). "A sheet's layers" drives the sheet viewer's (viewer.js's stack): the settings, a
chord's card, the necks' sheet and the versions list, each opened by a click or a tap, one at a time on a phone.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from caracole.viewer import build_viewer, page, viewer_csp
from caracole.viewer.book import BookSong, build_songbook
from caracole.viewer.harptab_page import build_harmonica_viewer

from helpers.browser import Browser, in_chromium
from helpers.version_pages import WONDERWALL, folder
from helpers.viewer_pages import (back, click_at, drag, entries, forward, rest, tap, tap_at, viewer as open_viewer,
                                  written)
from test_viewer_necks import reload, served
from test_viewer_panels import DESKTOP, IN_E, LONG, PHONE, SHEET_PATH, STOP_LINKS, chord

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


def bare(tmp_path: Path, name: str = "bare.html", *, tall: bool = False) -> str:
    """A page of two buttons, #open and #shut, each a layer opened or shut, with layers.js's history; its address.
    ``tall``: a page to scroll, its buttons fixed at the top of the screen."""
    layers = (page.HERE / "layers.js").read_text(encoding="utf-8")
    buttons = '<button id="open">Open</button> <button id="shut">Shut</button>'
    if tall:
        buttons = f'<div style="position: fixed; top: 0">{buttons}</div><div style="height: 6000px"></div>'
    path = tmp_path / name
    path.write_text('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>Bare</title></head><body>\n'
                    f"{buttons}\n<script>{layers}</script>\n<script>{BARE}</script>\n</body></html>\n",
                    encoding="utf-8")
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
def test_a_layer_the_page_closes_takes_the_address_it_wrote_down_with_it(tmp_path):
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.click("#open")
        assert until(b, (2, 3)) == (2, 3)
        b.js("history.replaceState(history.state, '', '#t=1')")  # the page's address, written on the layer's entry
        b.click("#shut")
        assert b.wait("pops === 1")  # the step down, its listeners all run
        assert until(b, (1, 3)) == (1, 3)
        assert b.js("[location.hash, history.state]") == ["#t=1", None]  # on the page's own entry now


@in_chromium
def test_a_forward_onto_a_layers_entry_takes_none_of_its_address_back(tmp_path):
    with open_viewer(tmp_path, bare(tmp_path)) as b:
        b.click("#open")
        assert until(b, (2, 3)) == (2, 3)
        b.js("history.replaceState(history.state, '', '#then')")
        back(b)  # the bare page writes nothing of its own after a Back: its entry's address as it was
        assert b.wait("pops === 1")
        b.js("history.replaceState(history.state, '', '#now')")  # what the page wrote since
        forward(b)  # onto the layer's entry, '#then', with no layer open: back from it at once
        assert b.wait("pops === 3")
        assert until(b, (1, 3)) == (1, 3)
        assert b.js("location.hash") == "#now"  # the page's newer address stays


@in_chromium
@pytest.mark.parametrize("how", ["shut", "back"])
def test_a_step_down_from_a_layers_entry_leaves_the_page_scrolled_where_it_is(tmp_path, how):
    with open_viewer(tmp_path, bare(tmp_path, tall=True)) as b:
        b.click("#open")
        assert until(b, (2, 3)) == (2, 3)
        b.js("scrollTo(0, 1500)")  # scrolled on with the layer open
        assert b.wait("scrollY === 1500")
        if how == "shut":
            b.click("#shut")
        else:
            back(b)
        assert b.wait("pops === 1")
        assert until(b, (1, 3)) == (1, 3)
        # The browser's own restoring of the place is back once the step is over, for a reload, which restores it.
        assert b.wait("history.scrollRestoration === 'auto'")
        assert b.js("scrollY") == 1500  # not where the layer opened
        reload(b)
        assert b.wait("scrollY === 1500")


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


# --- a sheet's layers ----------------------------------------------------------------------------------------------

# Each layer of the sheet viewer, shown and hidden: the necks' sheet is open while it has its place (data-sheet).
SHOWN = {
    "settings": "!document.getElementById('panel').hidden",
    "card": "!document.getElementById('card').hidden",
    "necks sheet": "!document.getElementById('necks').hidden && Boolean(document.getElementById('necks').dataset.sheet)",
    "versions": "!document.getElementById('version-list').hidden",
}
HIDDEN = {
    "settings": "document.getElementById('panel').hidden",
    "card": "document.getElementById('card').hidden",
    "necks sheet": "document.getElementById('necks').hidden && !document.getElementById('necks').dataset.sheet",
    "versions": "document.getElementById('version-list').hidden",
}
# What opened it, where the focus goes back as it closes (the card's: the chord tapped, ``chord``'s window.picked).
OPENER = {
    "settings": "document.activeElement === document.getElementById('more')",
    "card": "document.activeElement === window.picked",
    "necks sheet": "document.activeElement === document.getElementById('necks-open')",
    "versions": "document.activeElement === document.getElementById('ver-now')",
}
SHIFT = "document.querySelector('#shift .d').textContent"  # the settings' word: "capo 2 · +1"
SHEET = "/Artist/Title/sheet.html"  # where caracole serve serves a song's sheet


def sheet_page(tmp_path: Path, which: str) -> str:
    """The address a test opens ``which`` on: a song with kept versions for the versions list, else a long song."""
    if which == "versions":
        return folder(tmp_path, WONDERWALL)["sheet.html"].as_uri()
    return written(tmp_path, LONG)


def open_layer(b: Browser, which: str, size: dict) -> None:
    """``which`` opened as a reader opens it, a tap on a phone, a click on a laptop: shown once this returns."""
    if which == "card":
        at = chord(b, "G")[:2]  # the first G in reach, ``window.picked``
        (tap_at if size is PHONE else click_at)(b, *at)
    else:
        b.click({"settings": "#more", "necks sheet": "#necks-open", "versions": "#ver-now"}[which])
    assert b.wait(SHOWN[which])


LAYERS = [("settings", PHONE), ("settings", DESKTOP), ("card", PHONE), ("card", DESKTOP), ("necks sheet", PHONE),
          ("versions", PHONE), ("versions", DESKTOP)]


@in_chromium
@pytest.mark.parametrize(("which", "size"), LAYERS,
                         ids=[f"{which.replace(' ', '-')}-{'phone' if size is PHONE else 'laptop'}"
                              for which, size in LAYERS])
def test_each_layer_is_one_entry_and_back_closes_it(tmp_path, which, size):
    with open_viewer(tmp_path, sheet_page(tmp_path, which), **size) as b:
        b.js("window.marker = 1")
        open_layer(b, which, size)
        assert until(b, (2, 3)) == (2, 3)  # about:blank, the page, and the layer's entry over it
        assert b.js("history.state.caracoleLayer") == 1
        back(b)
        assert b.wait(HIDDEN[which])
        assert until(b, (1, 3)) == (1, 3)
        assert b.js("window.marker") == 1  # the same document: the page never left
        assert b.wait(OPENER[which])  # the focus back on what opened it, as Escape leaves it


@in_chromium
@pytest.mark.parametrize("how", ["Escape", "x"])
def test_escape_or_its_close_button_takes_its_entry_off_too(tmp_path, how):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        open_layer(b, "settings", PHONE)
        assert until(b, (2, 3)) == (2, 3)
        if how == "Escape":
            b.press("Escape")
        else:
            b.click("#panel .x")
        assert b.wait(HIDDEN["settings"])
        assert until(b, (1, 3)) == (1, 3)
        back(b)
        assert b.wait("location.href === 'about:blank'")  # Back then leaves the page, as with no layer opened


@in_chromium
def test_on_a_phone_one_layer_at_a_time(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        open_layer(b, "settings", PHONE)
        assert until(b, (2, 3)) == (2, 3)
        top = b.js("document.getElementById('panel').getBoundingClientRect().top")
        tap_at(b, *chord(b, "G", above=top)[:2])  # a chord above the settings
        assert b.wait(SHOWN["card"])
        assert b.js(HIDDEN["settings"]) is True  # the card in the settings' place, not over them
        assert until(b, (2, 3)) == (2, 3)  # still one layer's entry
        assert b.js("history.state.caracoleLayer") == 1
        back(b)
        assert b.wait(f"{HIDDEN['card']} && {HIDDEN['settings']}")
        assert until(b, (1, 3)) == (1, 3)


@in_chromium
def test_on_a_laptop_back_closes_the_one_on_top_first(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **DESKTOP) as b:
        open_layer(b, "settings", DESKTOP)  # the rail
        assert until(b, (2, 3)) == (2, 3)
        open_layer(b, "card", DESKTOP)  # a card beside it
        assert until(b, (3, 4)) == (3, 4)
        assert b.js(SHOWN["settings"]) is True
        back(b)
        assert b.wait(HIDDEN["card"])
        assert until(b, (2, 4)) == (2, 4)
        assert b.js(SHOWN["settings"]) is True  # the rail stays
        back(b)
        assert b.wait(HIDDEN["settings"])
        assert until(b, (1, 4)) == (1, 4)


@in_chromium
def test_a_change_made_with_a_layer_open_stays_after_back(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        open_layer(b, "settings", PHONE)
        assert until(b, (2, 3)) == (2, 3)
        b.click("#up")
        assert b.js("[location.hash, history.state.caracoleLayer]") == ["#t=1", 1]  # the layer's entry keeps its mark
        back(b)
        assert b.wait(HIDDEN["settings"])
        assert until(b, (1, 3)) == (1, 3)
        assert b.wait("location.hash === '#t=1'")  # written into the page's own entry too
        assert b.js(SHIFT) == "capo 2 · +1"


@in_chromium
@pytest.mark.parametrize("how", ["Escape", "x"])
def test_a_change_made_with_a_layer_open_stays_once_it_closes_and_after_a_reload(tmp_path, how):
    # In caracole serve's sandbox, with no storage, the address alone keeps it: the entry the layer's closing goes back
    # to was written before the change, and the page writes it there again.
    with served({SHEET: (build_viewer(LONG), viewer_csp)}) as site, \
            open_viewer(tmp_path, site + SHEET, **PHONE) as b:
        open_layer(b, "settings", PHONE)
        assert until(b, (2, 3)) == (2, 3)
        b.click("#up")
        if how == "Escape":
            b.press("Escape")
        else:
            b.click("#panel .x")
        assert b.wait(HIDDEN["settings"])
        assert until(b, (1, 3)) == (1, 3)
        assert b.wait("location.hash === '#t=1'")
        reload(b)
        assert b.js(f"[location.hash, {SHIFT}]") == ["#t=1", "capo 2 · +1"]


@in_chromium
@pytest.mark.parametrize("how", ["Escape", "back"])
def test_the_song_scrolled_under_a_layer_stays_where_it_is_as_the_layer_closes(tmp_path, how):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        open_layer(b, "settings", PHONE)
        assert until(b, (2, 3)) == (2, 3)
        drag(b, 260, start=360)  # the song, under the finger above the settings
        rest(b)
        y = b.js("scrollY")
        if how == "Escape":
            b.press("Escape")
        else:
            back(b)
        assert b.wait(HIDDEN["settings"])
        assert until(b, (1, 3)) == (1, 3)
        assert b.wait("history.scrollRestoration === 'auto'")  # the step down over
        assert y > 0 and b.js("scrollY") == y  # not back where the settings opened


@in_chromium
def test_on_a_laptop_the_song_stays_where_it_is_as_back_closes_each_layer(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **DESKTOP) as b:
        open_layer(b, "settings", DESKTOP)
        open_layer(b, "card", DESKTOP)
        assert until(b, (3, 4)) == (3, 4)
        b.js("scrollTo(0, 600)")
        assert b.wait("scrollY === 600")
        back(b)  # the card, down to the settings' entry
        assert b.wait(HIDDEN["card"])
        assert until(b, (2, 4)) == (2, 4)
        assert b.js("scrollY") == 600
        back(b)  # the settings
        assert b.wait(HIDDEN["settings"])
        assert until(b, (1, 4)) == (1, 4)
        assert b.wait("history.scrollRestoration === 'auto'")
        assert b.js("scrollY") == 600


@in_chromium
def test_a_file_whose_history_refuses_entries_still_opens_and_closes_them(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        b.js("""history.pushState = () => { throw new DOMException("denied", "SecurityError"); };
                window.errors = []; addEventListener("error", (e) => errors.push(String(e.message)));""")
        open_layer(b, "settings", PHONE)
        b.press("Escape")
        assert b.wait(HIDDEN["settings"])
        open_layer(b, "card", PHONE)
        b.click("#card .x")
        assert b.wait(HIDDEN["card"])
        assert b.js("errors") == []  # the layers open and close, with no error
        assert until(b, (1, 2)) == (1, 2)  # and no entry: Back leaves the page, as before


@in_chromium
def test_in_caracole_serves_sandbox_back_closes_a_layer(tmp_path):
    with served({SHEET: (build_viewer(LONG), viewer_csp)}) as site, \
            open_viewer(tmp_path, site + SHEET, **PHONE) as b:
        b.js("window.marker = 1")
        open_layer(b, "settings", PHONE)
        assert until(b, (2, 3)) == (2, 3)
        back(b)
        assert b.wait(HIDDEN["settings"])
        assert until(b, (1, 3)) == (1, 3)
        assert b.js("[window.marker, String(window.origin)]") == [1, "null"]  # the same document, in its sandbox


# --- Aa and the question -------------------------------------------------------------------------------------------

SIZES_SHOWN = "!document.getElementById('sizes').hidden"
SIZES_HIDDEN = "document.getElementById('sizes').hidden"
AA_EXPANDED = "document.getElementById('size').getAttribute('aria-expanded')"


@in_chromium
def test_aa_is_a_layer(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        b.click("#size")
        assert b.wait(SIZES_SHOWN)
        assert until(b, (2, 3)) == (2, 3)
        back(b)
        assert b.wait(SIZES_HIDDEN)
        assert b.js(AA_EXPANDED) == "false"
        b.click("#size")
        assert b.wait(SIZES_SHOWN)
        assert b.js(AA_EXPANDED) == "true"
        tap(b, "#sheet .w")  # a tap on the song's words closes it, and its entry goes
        assert b.wait(SIZES_HIDDEN)
        assert until(b, (1, 3)) == (1, 3)
        open_layer(b, "settings", PHONE)
        b.click("#size")
        assert b.wait(f"{SIZES_SHOWN} && {HIDDEN['settings']}")  # Aa in the settings' place
        assert until(b, (2, 3)) == (2, 3)


@in_chromium
def test_aa_beside_the_settings_rail_and_back_closes_aa_first(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **DESKTOP) as b:
        open_layer(b, "settings", DESKTOP)
        b.click("#size")
        assert b.wait(SIZES_SHOWN)
        assert until(b, (3, 4)) == (3, 4)
        back(b)
        assert b.wait(SIZES_HIDDEN)
        assert b.js(SHOWN["settings"]) is True
        assert until(b, (2, 4)) == (2, 4)


@in_chromium
def test_back_closes_the_question_and_leaves_the_settings_under_it(tmp_path):
    with served({SHEET_PATH: (build_viewer(IN_E), viewer_csp)}) as site, \
            open_viewer(tmp_path, site + SHEET_PATH, **PHONE) as b:
        b.js(STOP_LINKS)
        b.click("#more")
        b.js("document.getElementById('capo-up').click(); document.getElementById('capo-up').click()")
        b.click("#export")
        assert b.wait("document.getElementById('export-ask').open")
        assert until(b, (3, 4)) == (3, 4)  # the settings and the question
        back(b)
        assert b.wait("!document.getElementById('export-ask').open")
        assert b.js(SHOWN["settings"]) is True
        assert until(b, (2, 4)) == (2, 4)
        b.click("#export")
        assert b.wait("document.getElementById('export-ask').open")
        assert until(b, (3, 4)) == (3, 4)
        b.press("Escape")
        assert b.wait("!document.getElementById('export-ask').open")
        assert until(b, (2, 4)) == (2, 4)
        assert b.js(SHOWN["settings"]) is True


# --- a harmonica tab's page ---------------------------------------------------------------------------------------

@in_chromium
def test_on_a_harmonica_page_aa_and_the_necks_sheet_are_one_entry_each(tmp_path):
    from test_viewer_harptab_browser import opened, with_sheet

    with opened(tmp_path, with_sheet(tmp_path), **PHONE) as b:
        base = entries(b)
        assert base[0] == base[1] - 1
        b.click("#size")
        assert b.wait(SIZES_SHOWN)
        assert until(b, (base[0] + 1, base[1] + 1)) == (base[0] + 1, base[1] + 1)
        back(b)
        assert b.wait(SIZES_HIDDEN)
        assert until(b, (base[0], base[1] + 1)) == (base[0], base[1] + 1)
        b.click("#necks-open")
        assert b.wait("!document.getElementById('necks').hidden && document.getElementById('necks').dataset.sheet")
        assert until(b, (base[0] + 1, base[1] + 1)) == (base[0] + 1, base[1] + 1)
        back(b)
        assert b.wait(HIDDEN["necks sheet"])
        assert b.js(OPENER["necks sheet"]) is True
        assert until(b, (base[0], base[1] + 1)) == (base[0], base[1] + 1)
        b.click("#necks-open")
        assert b.wait("!document.getElementById('necks').hidden")
        b.click("#size")  # Aa takes the sheet's place
        assert b.wait(f"{SIZES_SHOWN} && {HIDDEN['necks sheet']}")
        assert until(b, (base[0] + 1, base[1] + 1)) == (base[0] + 1, base[1] + 1)
        b.click("#size")
        assert b.wait(SIZES_HIDDEN)
        b.click("#necks-open")
        assert b.wait("!document.getElementById('necks').hidden")
        b.click("#h-up")
        assert b.js("history.state && history.state.caracoleLayer") == 1


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
        # before the page's own script, never right before: kinds.js comes between them
        assert html.index(inlined(after)) < html.index(layers) < html.index(inlined(before)), (after, before)
    # kinds.js, the version line's, after layers.js and before the page's own script on a sheet and a harmonica tab's
    # page; never in a songbook
    sheet, book, harmonica = pages[0][0], pages[1][0], pages[2][0]
    for html, own in ((sheet, "viewer.js"), (harmonica, "harptab.js")):
        assert html.count(inlined("kinds.js")) == 1
        assert html.index(layers) < html.index(inlined("kinds.js")) < html.index(inlined(own)), own
    assert inlined("kinds.js") not in book
    assert page.HERE / "layers.js" in page.BUILD_FILES and page.HERE / "kinds.js" in page.BUILD_FILES
    # It makes no element of its own and loads nothing.
    for word in ("innerHTML", "createElement", "fetch(", "XMLHttpRequest", "import(", "eval(", "new Function"):
        assert word not in page._layers(), word
