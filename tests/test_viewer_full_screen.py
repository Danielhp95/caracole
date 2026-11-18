"""Full screen on the sheet viewer (viewer.js, layers.js, viewer.css): the controls hidden for reading.

The settings' Hide controls (``#full-open``, the first of the places to go) or a double tap beside the song
(``caracoleLayers.doubleTap``, on what ``caracoleLayers.MARGIN_SKIP`` leaves: no word, chord, title or control) hides
every control marked ``data-controls`` (the bar), the header's facts and the rail of necks, ``html[data-full="on"]``;
a thin handle stays at the foot (``#handle``, "Show controls"), and a tap on it, Escape or Back brings them back. It is
a layer of viewer.js's stack, one entry of the history while it is on: on a phone a layer opened over it (a chord's
card) takes its place, the controls back; on a laptop a card opens over it.
"""

from __future__ import annotations

import time

import pytest

from caracole.viewer import build_viewer, page
from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import Browser, in_chromium
from helpers.targets import small_targets
from helpers.viewer_pages import back, click_at, double_tap, entries, key, spot, tap_at, viewer as open_viewer, written
from test_viewer_instruments_page import IN_E, THREE
from test_viewer_layers import until
from test_viewer_panels import DESKTOP, LONG, PHONE, UG_CHO, chord
from test_viewer_songbook_browser import READY, _songbook

FULL = "document.documentElement.dataset.full === 'on'"
NOT_FULL = "!document.documentElement.dataset.full"
# What full screen hides and shows: <html>'s mark, the bar's and the facts' display, the rail of necks, the song's
# width, the handle's box (None while hidden), the window, the settings, the card and where the focus is.
STATE = """(() => { const q = (id) => document.getElementById(id), doc = document.documentElement;
  const h = q('handle'), r = h.getBoundingClientRect();
  return {full: doc.dataset.full || null, bar: getComputedStyle(q('bar')).display,
    facts: getComputedStyle(q('facts')).display, necks: q('necks').hidden, railed: doc.dataset.necks || null,
    sheet: Math.round(q('sheet').getBoundingClientRect().width),
    handle: h.hidden ? null : {left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height},
    inner: innerHeight, client: doc.clientWidth, panel: q('panel').hidden, card: q('card').hidden,
    dock: doc.dataset.dock || null, focus: document.activeElement ? document.activeElement.id : ''}; })()"""


def hide_controls(b: Browser) -> None:
    """The settings' Hide controls, as a reader presses it: ⋯, then its row."""
    b.click("#more")
    assert b.wait("!document.getElementById('panel').hidden")
    b.click("#full-open")
    assert b.wait(FULL)


# --- the page as written --------------------------------------------------------------------------------------------


def test_the_page_has_a_handle_and_hide_controls():
    songbook = build_songbook("Campfire", [BookSong("One", "Synthetic", cho=UG_CHO, id="aaaa")])
    for html in (build_viewer(UG_CHO), songbook):
        assert html.count(page._HANDLE) == 1
        assert page._HANDLE == ('<button type="button" class="handle" id="handle" hidden aria-label="Show controls">'
                                '</button>\n')
        assert '<div class="bar" id="bar" data-controls hidden role="region" aria-label="Controls">' in html
        # Hide controls, the first of the places to go, before Harmony.
        assert '<div class="places ruled" id="places">\n' + page._FULL_ROW + page._HARMONY_ROW in html
        assert '<span class="goto-lab">Hide controls</span><span class="goto-v">full screen' in page._FULL_ROW
        assert 'id="full-open"' in page._FULL_ROW
        # The handle right after the pill, out of the bar.
        assert html.index(page._HANDLE) > html.index('<div class="pill" id="pill"')
        assert html.index(page._HANDLE) < html.index('<p class="vh" id="scroll-status"')


# --- full screen and back ---------------------------------------------------------------------------------------------


@in_chromium
def test_hide_controls_hides_the_bar_the_facts_and_the_rail_and_the_handle_brings_them_back(tmp_path):
    # A short song, in one column beside the rail of necks at 1280 px, in two once the rail goes.
    with open_viewer(tmp_path, written(tmp_path, UG_CHO), **DESKTOP) as b:
        before = b.js(STATE)
        hide_controls(b)
        full = b.js(STATE)
        assert until(b, (2, 3)) == (2, 3)  # one layer's entry: the settings' gave way to it
        b.click("#handle")
        assert b.wait(NOT_FULL)
        after = b.js(STATE)
        assert until(b, (1, 3)) == (1, 3)
    assert before["full"] is None and before["railed"] == "1" and not before["necks"], before  # the rail shows
    assert before["bar"] != "none" and before["facts"] != "none" and before["handle"] is None, before
    assert full["full"] == "on" and full["bar"] == "none" and full["facts"] == "none", full
    assert full["necks"] and full["railed"] is None and full["sheet"] > before["sheet"], (before, full)
    handle = full["handle"]
    assert handle and abs(handle["bottom"] - full["inner"]) <= 1, full  # at the window's foot
    assert abs((handle["left"] + handle["right"]) / 2 - full["client"] / 2) <= 1, full  # centred
    assert full["panel"] and full["focus"] == "handle", full
    assert after["full"] is None and after["bar"] != "none" and after["facts"] != "none", after
    assert after["railed"] == "1" and not after["necks"] and after["sheet"] == before["sheet"], after
    assert after["handle"] is None and after["focus"] == "more", after  # the focus back on ⋯


@in_chromium
@pytest.mark.parametrize("how", ["Escape", "back"])
def test_escape_or_back_brings_the_controls_back(tmp_path, how):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        b.js("window.marker = 1")
        hide_controls(b)
        assert until(b, (2, 3)) == (2, 3)
        if how == "Escape":
            b.press("Escape")
        else:
            back(b)
        assert b.wait(NOT_FULL)
        seen = b.js(STATE)
        assert until(b, (1, 3)) == (1, 3)
        assert b.js("window.marker") == 1  # the same page
    assert seen["bar"] != "none" and seen["facts"] != "none" and seen["handle"] is None, seen


@in_chromium
def test_a_double_tap_beside_the_song_hides_the_controls(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        double_tap(b, *spot(b, "#sheet .w"))  # on a word: the song's own
        double_tap(b, *spot(b, "h1"))  # on the title
        time.sleep(0.5)
        assert b.js(NOT_FULL) is True
        assert b.js("document.getElementById('card').hidden") is True  # on them: no chord's card
        double_tap(b, 4, 420)  # the page's left padding, beside the song
        assert b.wait(FULL)
        assert until(b, (2, 3)) == (2, 3)  # one entry
        assert b.js("getComputedStyle(document.getElementById('bar')).display") == "none"
    with open_viewer(tmp_path, written(tmp_path, LONG, "Laptop") + "#necks=0", **DESKTOP) as b:
        title = b.js("(() => { const r = document.querySelector('h1').getBoundingClientRect(); "
                     "return [r.left + 20, r.top + r.height / 2]; })()")
        click_at(b, *title)
        click_at(b, *title)
        time.sleep(0.5)
        assert b.js(NOT_FULL) is True
        click_at(b, 120, 400)  # the column's left margin
        click_at(b, 120, 400)
        assert b.wait(FULL)
        assert until(b, (2, 3)) == (2, 3)


@in_chromium
def test_two_clicks_far_apart_or_from_the_keyboard_are_no_double_tap(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG) + "#necks=0", **DESKTOP) as b:
        click_at(b, 120, 400)
        time.sleep(0.5)  # past DOUBLE_MS
        click_at(b, 120, 400)
        click_at(b, 120, 440)  # past DOUBLE_PX from the one before
        b.js("document.querySelector('.page').click(); document.querySelector('.page').click()")  # detail 0
        time.sleep(0.5)
        assert b.js(NOT_FULL) is True
        assert b.js("[caracoleLayers.DOUBLE_MS, caracoleLayers.DOUBLE_PX]") == [350, 30]
        assert b.js("caracoleLayers.MARGIN_SKIP") == (
            "a, button, input, select, textarea, summary, label, [role=button], [tabindex], .c, .s, .w, .y, .m, "
            "pre, h1, h2, h3, .artist, .facts, .versions, .sheet-ui, .bar, .pill, .handle, .necks, .strip, .tip, "
            "details, .notice, .credit, .foot, .pager")


@in_chromium
def test_two_clicks_on_a_dot_of_the_rail_are_no_double_tap(tmp_path):
    # A dot picked draws its neck anew: the click's target is out of the page by the time the double tap hears it.
    with open_viewer(tmp_path, written(tmp_path, LONG), **DESKTOP) as b:
        dot = b.js("(() => { const c = document.querySelector('#necks .nk circle[data-p]'); "
                   "const r = c.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        click_at(b, *dot)
        click_at(b, *dot)
        time.sleep(0.5)
        assert b.js(NOT_FULL) is True
        assert b.js("document.documentElement.dataset.necks") == "1"


@in_chromium
def test_a_double_tap_in_full_screen_does_nothing(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG) + "#necks=0", **DESKTOP) as b:
        click_at(b, 120, 400)
        click_at(b, 120, 400)
        assert b.wait(FULL)
        assert until(b, (2, 3)) == (2, 3)
        click_at(b, *chord(b, "G")[:2])  # a card over full screen
        assert b.wait("!document.getElementById('card').hidden")
        assert until(b, (3, 4)) == (3, 4)
        click_at(b, 120, 400)
        click_at(b, 120, 400)
        time.sleep(0.5)
        assert entries(b) == (3, 4)  # no other entry, and full screen still under the card
        back(b)
        assert b.wait("document.getElementById('card').hidden")
        assert until(b, (2, 4)) == (2, 4)
        assert b.js(FULL) is True


@in_chromium
def test_on_a_phone_a_layer_opened_in_full_screen_brings_the_controls_back(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        hide_controls(b)
        assert until(b, (2, 3)) == (2, 3)
        tap_at(b, *chord(b, "G")[:2])
        assert b.wait("!document.getElementById('card').hidden")
        phone = b.js(STATE)
        assert until(b, (2, 3)) == (2, 3)  # the card's entry in full screen's place
    assert phone["full"] is None and phone["bar"] != "none" and phone["dock"] == "card", phone  # docked on the bar
    assert phone["handle"] is None, phone
    with open_viewer(tmp_path, written(tmp_path, LONG, "Laptop"), **DESKTOP) as b:
        hide_controls(b)
        assert until(b, (2, 3)) == (2, 3)
        click_at(b, *chord(b, "G")[:2])
        assert b.wait("!document.getElementById('card').hidden")
        laptop = b.js(STATE)
        assert until(b, (3, 4)) == (3, 4)  # a card over full screen
        back(b)
        assert b.wait("document.getElementById('card').hidden")
        assert until(b, (2, 4)) == (2, 4)
        closed = b.js(STATE)
    assert laptop["full"] == "on" and laptop["bar"] == "none" and laptop["handle"], laptop
    assert closed["full"] == "on" and closed["handle"], closed  # Back closed the card alone


@in_chromium
def test_the_handle_is_a_thumbs_target_at_320_px(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), width=320, height=640, mobile=True) as b:
        hide_controls(b)
        seen = b.js(STATE)
        small = [t for t in b.js(small_targets()) if "handle" in t["what"]]
        wide = b.js("document.documentElement.scrollWidth")
    assert seen["handle"]["width"] >= 48 and seen["handle"]["height"] >= 48, seen
    assert small == [] and wide <= 320, (small, wide)


@in_chromium
def test_full_screen_does_not_move_under_reduced_motion(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), reduced=True, **PHONE) as b:
        hide_controls(b)
        seen = b.js("[getComputedStyle(document.getElementById('handle')).transitionDuration, "
                    "getComputedStyle(document.getElementById('bar')).transitionDuration]")
    assert seen == ["0s", "0s"], seen


@in_chromium
def test_a_songbook_song_goes_full_screen_and_its_arrows_still_change_songs(tmp_path):
    book = _songbook(tmp_path, [BookSong("One", "Synthetic", cho=IN_E, id="aaaa"),
                                BookSong("Two", "Synthetic", cho=THREE, id="bbbb")])
    with open_viewer(tmp_path, book + "#song-1", **DESKTOP) as b:
        hide_controls(b)
        b.js("window.before = true")
        key(b, "ArrowRight", 39)
        assert b.wait("!window.before && location.hash.startsWith('#song-2') && " + READY)
        assert b.js("document.querySelector('section.song:not([hidden]) h2.title').textContent") == "Two"

