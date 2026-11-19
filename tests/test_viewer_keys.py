"""The keys a pedal sends (screen.js's key map, ``caracoleScreen.keys``, which viewer.js and harptab.js bind).

A Bluetooth page turner is a keyboard: Space or Enter starts and stops autoscroll (the bar's Scroll while it is off,
else the pill's first button: at once while it counts in, a pause while it runs, a count-in again while paused);
PageDown or ↓ turns a screen keeping the last two lines wholly in view at the top, PageUp or ↑ back keeping the first
two at the foot; any of them pauses a scroll. The room a turn measures is the window less what the page's controls
cover (``room()``): below 1200 px the bar at the foot (slid away or not) and the pill above it; from 1200 px the
toolbar stuck at the top and the pill under it; in full screen, where the keys still work, nothing but the pill. A
modifier, a text field or a layer with the focus leaves the key to them; ← → are a songbook's, and no key changes
the version. These tests drive the pages on real time in Chromium (helpers/browser.py's ``Browser``).
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import CHROMIUM_MARKS, Browser
from helpers.version_pages import WONDERWALL, folder
from helpers.viewer_pages import key, tap_at, written
from test_viewer_harptab_browser import tab, written as harmonica_written
from test_viewer_scroll import LONG as WRAPPING

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

# A long sheet of short lines: on any screen the tests use, at any text size, three lines and more wholly in view (a
# row of chords and its words each, unwrapped at 40 px on a 320 px phone).
LONG = "{title: Long Song}\n{artist: Synthetic}\n" + "".join(
    f"{{comment: Verse {n}}}\n" + "".join(f"[G]Line [D]{n}.{m}\n" for m in range(4)) for n in range(40))

PHONE = {"width": 390, "height": 844, "mobile": True}
LAPTOP = {"width": 1280, "height": 900, "mobile": False}
READY = "document.documentElement.dataset.ready === '1'"
FULL = "document.documentElement.dataset.full === 'on'"
STATE = "document.getElementById('pill').dataset.state"
CODES = {"PageDown": 34, "PageUp": 33, "ArrowDown": 40, "ArrowUp": 38, "ArrowLeft": 37, "ArrowRight": 39}

# The lines wholly in view between the page's controls, by their index among the sheet's lines. From 1200 px the
# bar is the toolbar at the top and the pill sits under it: below both. Below 1200 px the bar sits at the foot:
# above its place (its height whether slid away or not), and above the pill while it shows. In full screen the bar
# isn't displayed and counts for nothing.
WHOLE = """(() => { const bar = document.getElementById('bar'), pill = document.getElementById('pill');
  const wide = matchMedia('(min-width: 1200px)').matches, shown = !bar.hidden && bar.offsetHeight > 0;
  let top = wide && shown ? Math.max(0, bar.getBoundingClientRect().bottom) : 0;
  let bottom = !wide && shown ? innerHeight - bar.offsetHeight : innerHeight;
  if (!pill.hidden) {
    const p = pill.getBoundingClientRect();
    if (wide) top = Math.max(top, p.bottom); else bottom = Math.min(bottom, p.top);
  }
  return [...document.querySelectorAll('#sheet p, #sheet pre')].map((el, n) => [n, el.getBoundingClientRect()])
    .filter(([, r]) => r.height && r.top >= top - 1 && r.bottom <= bottom + 1).map(([n]) => n); })()"""

# Whether each key the page heard since had its default prevented once every handler of the page ran (window's
# listeners in the bubbling phase are the last): a key the map takes is prevented, one it leaves alone isn't.
HEARD = """window.heard = [];
addEventListener('keydown', (e) => { heard.push([e.key, e.defaultPrevented]); });"""


@contextmanager
def opened(tmp_path: Path, url: str, *, scale: float = 1, reduced: bool = False, args: tuple[str, ...] = (),
           width: int = 390, height: int = 844, mobile: bool = True):
    """The page at ``url`` in Chromium, ``width`` × ``height`` at ``scale`` device pixels a CSS pixel, once its script
    ran; ``reduced``: with prefers-reduced-motion; ``args``: more of Chromium's switches."""
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), width=width, height=height, mobile=mobile,
                 args=args) as b:
        if scale != 1:
            b.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale,
                   mobile=mobile)
        b.send("Emulation.setEmulatedMedia", features=[
            {"name": "prefers-reduced-motion", "value": "reduce" if reduced else "no-preference"}])
        b.open(url)
        assert b.wait(READY)
        yield b


def press(b: Browser, name: str) -> None:
    """A key pressed and let go where the focus is: Space and Enter as Browser.press sends them, the others by name."""
    if name in (" ", "Enter"):
        b.press(name)
    else:
        key(b, name, CODES[name])


def settled(b: Browser) -> None:
    """Two frames on: what the page does as it hears of a scroll (the toolbar's edge, the bar slid) is done."""
    b.js("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")


def turned(b: Browser, name: str) -> tuple[list[int], list[int], float]:
    """``name`` pressed: the lines wholly in view where the page was as the key came (a scroll that ran paused by it,
    the bar back), and where it is after the turn, by ``WHOLE``; and the page's scroll position after it."""
    b.js("document.addEventListener('keydown', () => { window.keyedAt = scrollY; }, {capture: true, once: true})")
    press(b, name)
    settled(b)
    y = b.js("scrollY")
    after = b.js(WHOLE)
    b.js("scrollTo(0, keyedAt)")
    settled(b)
    before = b.js(WHOLE)
    b.js(f"scrollTo(0, {y})")
    settled(b)
    assert b.js("scrollY") == y
    return before, after, y


def kept_down(before: list[int], after: list[int]) -> None:
    assert len(before) >= 2, before
    assert after[:2] == before[-2:], (before, after)


def kept_up(before: list[int], after: list[int]) -> None:
    assert len(before) >= 2, before
    assert after[-2:] == before[:2], (before, after)


def blur(b: Browser) -> None:
    """The focus on the page itself, as a reader who tapped beside the song has it."""
    b.js("document.activeElement && document.activeElement.blur()")


# --- a turn ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", [
    PHONE,
    {"width": 844, "height": 390, "mobile": True},  # the title and the strip leave two lines whole at the top
    LAPTOP,  # from the top, the toolbar under the title: stuck once turned
    PHONE | {"scale": 1.75},
    PHONE | {"args": ("--blink-settings=minimumFontSize=40",)},
    {"width": 320, "height": 640, "mobile": True, "reduced": True},
], ids=["phone", "on-its-side", "laptop", "scale-1.75", "text-zoom", "320-reduced-motion"])
def test_pagedown_turns_a_screen_keeping_two_lines_and_pageup_turns_back(tmp_path, size):
    with opened(tmp_path, written(tmp_path, LONG), **size) as b:
        if "scale" in size:
            assert b.js("devicePixelRatio") == 1.75
        if "args" in size:
            assert b.js("getComputedStyle(document.getElementById('sheet')).fontSize") == "40px"
        if size["height"] < 500:
            assert b.js("document.documentElement.dataset.full") == "auto"  # a phone on its side: the controls slim
        for _ in range(4):  # the title alone in view, in text drawn at 40 px: a turn into the song first
            if len(b.js(WHOLE)) >= 2:
                break
            press(b, "PageDown")
        down, down_after, y1 = turned(b, "PageDown")
        again, again_after, y2 = turned(b, "ArrowDown")
        up, up_after, y3 = turned(b, "PageUp")
        status = b.js(STATE)
    kept_down(down, down_after)
    kept_down(again, again_after)
    kept_up(up, up_after)
    assert 0 < y1 < y2 and y3 < y2
    assert all(float(y).is_integer() for y in (y1, y2, y3)), (y1, y2, y3)
    assert status == "off"  # a turn starts nothing


def test_a_screen_of_too_few_whole_lines_turns_by_its_height_less_two_lines(tmp_path):
    # Text drawn at 40 px on a phone: each line of this sheet wraps to some 340 px, two at most whole in view, filling
    # it. A turn goes on by the room less two lines' worth of the text's size (a chord row and its words, 2.6 em
    # each), and at least half the room. (Two lines under the title, on a phone on its side, are a turn by the lines:
    # the test above.)
    with opened(tmp_path, written(tmp_path, WRAPPING), args=("--blink-settings=minimumFontSize=40",)) as b:
        assert len(b.js(WHOLE)) < 3
        room = b.js("innerHeight - document.getElementById('bar').offsetHeight")
        size = b.js("parseFloat(getComputedStyle(document.getElementById('sheet')).fontSize)")
        press(b, "PageDown")
        down = b.js("scrollY")
        press(b, "PageUp")
        up = b.js("scrollY")
    step = round(max(room / 2, room - 2 * 2.6 * size))
    assert down == step and up == 0


def test_a_song_in_columns_turns_whole_into_view_and_back_to_the_top(tmp_path):
    # From 1100 px a song the window shows whole is in columns (viewer.js layout), its lines running down one and up
    # the next: a turn by its last lines would hide the next column's first ones under the toolbar. PageDown brings
    # the sheet's top under the toolbar, every line in view, and no further; PageUp goes back to the page's top.
    short = "{title: Short Song}\n{artist: Synthetic}\n" + "".join(
        f"{{comment: Verse {n}}}\n" + "".join(f"[G]Line [D]{n}.{m}\n" for m in range(4)) for n in range(6))
    with opened(tmp_path, written(tmp_path, short), **LAPTOP) as b:
        assert b.js("document.documentElement.dataset.columns") == "2"
        lines = b.js("document.querySelectorAll('#sheet p, #sheet pre').length")
        blur(b)
        top = len(b.js(WHOLE))
        press(b, "PageDown")
        settled(b)
        down = [b.js(WHOLE), b.js("scrollY")]
        press(b, "PageDown")
        settled(b)
        again = [b.js(WHOLE), b.js("scrollY")]
        press(b, "PageUp")
        up = b.js("scrollY")
    assert top < lines  # the title over it: some of its lines below the window
    assert down[0] == list(range(lines)) and down[1] > 0
    assert again == down  # no further
    assert up == 0


# --- Space and Enter ------------------------------------------------------------------------------------------------


def test_space_and_enter_start_and_stop_autoscroll(tmp_path):
    with opened(tmp_path, written(tmp_path, LONG)) as b:
        b.js(HEARD)
        seen = []
        for name in (" ", " ", "Enter", "Enter"):
            blur(b)
            press(b, name)
            seen.append((b.js(STATE), b.js("Math.round(scrollY)")))
        heard = b.js("heard")
    assert [state for state, _ in seen] == ["counting", "running", "paused", "counting"]
    assert all(y < 60 for _, y in seen), seen  # never Space's own screen down: it ran a moment between two presses
    assert heard == [[" ", True], [" ", True], ["Enter", True], ["Enter", True]]


@pytest.mark.parametrize("size", [PHONE, LAPTOP], ids=["finger", "mouse"])
def test_a_pill_button_pressed_by_hand_leaves_the_next_space_to_the_map(tmp_path, size):
    # A browser focuses a button tapped or clicked: the pedal's next Space would press + again rather than pause.
    with opened(tmp_path, written(tmp_path, LONG), **size) as b:
        blur(b)
        press(b, " ")
        press(b, " ")  # the focus on the pill's ▶: its own press, at once
        assert b.js(STATE) == "running"
        blur(b)
        if size["mobile"]:
            tap_at(b, *b.js("(() => { const r = document.getElementById('pill-faster').getBoundingClientRect();"
                            " return [r.left + r.width / 2, r.top + r.height / 2]; })()"))
        else:
            b.click("#pill-faster")
        faster = [b.js("document.getElementById('pill-speed').textContent"), b.js("document.activeElement.id"),
                  b.js(STATE)]
        press(b, " ")
        paused = [b.js("document.getElementById('pill-speed').textContent"), b.js(STATE)]
    assert faster == ["7", "", "running"]  # a step faster, and the focus where it was: on the page
    assert paused == ["7", "paused"]


def test_a_page_key_while_it_scrolls_pauses_it_and_turns(tmp_path):
    with opened(tmp_path, written(tmp_path, LONG)) as b:
        blur(b)
        press(b, " ")
        press(b, " ")  # the focus on the pill's ▶ now: its own press, at once
        assert b.js(STATE) == "running"
        assert b.wait("scrollY > 40")
        before, after, _ = turned(b, "PageDown")
        label, status = b.js("document.getElementById('go').getAttribute('aria-label')"), b.js(STATE)
    assert label == "Resume" and status == "paused"
    kept_down(before, after)


def test_from_1200_px_a_turn_keeps_its_lines_below_the_pill_under_the_toolbar(tmp_path):
    with opened(tmp_path, written(tmp_path, LONG), **LAPTOP) as b:
        b.js("scrollTo(0, 1500)")
        settled(b)
        assert b.js("document.getElementById('bar').getBoundingClientRect().top") == 0  # stuck to the window's top
        for button in ("scroll", "go", "go"):  # counting, running, paused: the pill under the toolbar
            b.js(f"document.getElementById('{button}').click()")
        assert b.js(STATE) == "paused"
        settled(b)
        pill, bar = b.js("[document.getElementById('pill').getBoundingClientRect().top,"
                         " document.getElementById('bar').getBoundingClientRect().bottom]")
        assert bar < pill < bar + 20
        down, down_after, y1 = turned(b, "PageDown")
        up, up_after, y2 = turned(b, "PageUp")
    assert 1500 < y1 and y2 < y1
    kept_down(down, down_after)
    kept_up(up, up_after)


@pytest.mark.parametrize("size", [PHONE, LAPTOP], ids=["phone", "laptop"])
def test_in_full_screen_the_keys_still_turn_and_start(tmp_path, size):
    with opened(tmp_path, written(tmp_path, LONG), **size) as b:
        b.click("#more")
        assert b.wait("!document.getElementById('panel').hidden")
        b.click("#full-open")
        assert b.wait(FULL)
        assert b.js("document.activeElement.id") == "handle"
        before, after, _ = turned(b, "PageDown")
        full_turned = b.js(FULL)
        press(b, " ")  # on the handle: the map's, never the handle's own press (which brings the controls back)
        counting = [b.js(STATE), b.js(FULL)]
        press(b, " ")
        running = [b.js(STATE), b.js(FULL)]
        b.press("Escape")
        assert b.wait("!document.documentElement.dataset.full")
    kept_down(before, after)
    assert full_turned and counting == ["counting", True] and running == ["running", True]


# --- what the map leaves alone --------------------------------------------------------------------------------------


def test_keys_are_left_alone_in_a_text_field_or_a_layer(tmp_path):
    # The settings open, the focus in them, then a chord's card, the Aa box, the instrument menu, a text field, and the
    # rail's tabs on a laptop: neither Space nor a page key is the map's.
    def untaken(b: Browser, *names: str) -> list:
        b.js("heard.length = 0")
        for name in names:
            press(b, name)
        return [b.js("heard"), b.js(STATE)]

    with opened(tmp_path, written(tmp_path, LONG)) as b:
        b.js(HEARD)
        found = {}
        b.click("#more")
        assert b.wait("document.getElementById('panel').contains(document.activeElement)")
        found["settings"] = untaken(b, " ", "PageDown", "ArrowDown")
        b.js("document.getElementById('insts').focus()")
        assert b.js("document.activeElement.id") == "insts"
        found["menu"] = untaken(b, "PageDown")
        b.press("Escape")
        assert b.wait("document.getElementById('panel').hidden")
        b.click("#sheet .c")
        assert b.wait("!document.getElementById('card').hidden"
                      " && document.getElementById('card').contains(document.activeElement)")
        found["card"] = untaken(b, " ", "PageDown", "ArrowDown")
        b.press("Escape")
        assert b.wait("document.getElementById('card').hidden")
        b.click("#size")
        assert b.wait("!document.getElementById('sizes').hidden")
        b.js("document.getElementById('theme-auto').focus()")
        found["aa"] = untaken(b, " ", "PageDown", "ArrowDown")
        b.press("Escape")
        assert b.wait("document.getElementById('sizes').hidden")
        b.js("const field = document.body.appendChild(document.createElement('input')); field.focus()")
        found["field"] = untaken(b, " ", "PageDown", "ArrowDown")
        b.js("document.activeElement.remove()")

        # Space on a chord with the focus opens its card; Enter on the bar's Scroll presses it: their own.
        b.js("document.querySelector('#sheet .c').focus()")
        b.js("heard.length = 0")
        b.press(" ")
        chord = [b.js("heard"), b.wait("!document.getElementById('card').hidden")]
        b.press("Escape")
        assert b.wait("document.getElementById('card').hidden")
        b.js("document.getElementById('scroll').focus(); heard.length = 0")
        b.press("Enter")
        scroll = [b.js("heard"), b.js(STATE)]
    for where, (heard, state) in found.items():  # whatever they do with it (the menu picks an instrument)
        assert heard and all(not prevented for _, prevented in heard) and state == "off", (where, heard, state)
    assert chord == [[[" ", True]], True]  # the chord's own handler takes it
    assert scroll == [[["Enter", False]], "counting"]  # the button's own press


def test_the_rails_tabs_keep_their_keys_on_a_laptop(tmp_path):
    with opened(tmp_path, written(tmp_path, LONG), **LAPTOP) as b:
        b.js(HEARD)
        assert b.wait("document.querySelector('#necks [role=tab]') !== null")
        b.js("document.querySelector('#necks [role=tab]').focus()")
        for name in (" ", "PageDown", "ArrowDown"):
            press(b, name)
        heard, state = b.js("heard"), b.js(STATE)
    # The tabs' own arrows go from tab to tab, and no further (overlay.js: in a songbook, never to another song).
    assert heard == [[" ", False], ["PageDown", False]] and state == "off", (heard, state)


def test_a_modifier_leaves_the_key_to_the_browser(tmp_path):
    with opened(tmp_path, written(tmp_path, LONG)) as b:
        b.js(HEARD)
        blur(b)
        b.press(" ", modifiers=8)  # Shift+Space
        b.press("ArrowDown", modifiers=1)  # Alt+↓
        b.press("ArrowDown", modifiers=2)  # Ctrl+↓
        heard, state = b.js("heard"), b.js(STATE)
    assert [name for name, _ in heard] == [" ", "ArrowDown", "ArrowDown"]
    assert all(not prevented for _, prevented in heard) and state == "off", heard


def test_no_key_changes_the_version(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with opened(tmp_path, pages["sheet.html"].as_uri()) as b:
        b.js("window.stayed = true")
        path = b.js("location.pathname")
        blur(b)
        for name in ("ArrowLeft", "ArrowRight", "PageDown", " "):
            press(b, name)
        left = b.wait(f"window.stayed !== true || location.pathname !== {path!r}", 0.5)
        listed = b.js("document.getElementById('version-list').hidden")
    assert not left and listed


# --- a songbook, and the harmonica tab's page -----------------------------------------------------------------------


def test_a_songbook_turns_by_page_keys_and_changes_songs_by_arrows(tmp_path):
    short = "{title: One}\n{artist: Synthetic}\n" + "".join(f"[G]Line [D]{n}\n" for n in range(30))
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", [BookSong("One", "Synthetic", cho=short, id="aaaa"),
                                                BookSong("Two", "Synthetic", cho=short, id="bbbb")]), "utf-8")
    with opened(tmp_path, path.as_uri() + "#song-1") as b:
        b.js("window.before = true")
        blur(b)
        ys = []
        for _ in range(12):  # to the end of song 1, and on: it stays there
            press(b, "PageDown")
            ys.append(b.js("scrollY"))
        stayed = b.js("window.before === true && location.hash.startsWith('#song-1')")
        key(b, "ArrowRight", 39)
        assert b.wait("window.before !== true && location.hash.startsWith('#song-2') && " + READY)
        title = b.js("document.querySelector('section.song:not([hidden]) h2.title').textContent")
        blur(b)
        press(b, " ")  # counting in, the room for the pill under the song: near its end meanwhile
        b.js("scrollTo(0, document.documentElement.scrollHeight - innerHeight - 20)")
        settled(b)
        press(b, " ")  # the pill's ▶ has the focus: at once
        ended = b.wait("document.getElementById('scroll-status').textContent === 'Paused · end of song'", 5)
    assert stayed and ys[-1] == ys[-2] > 0 and title == "Two" and ended


def test_the_harmonica_page_answers_the_same_keys(tmp_path):
    with opened(tmp_path, harmonica_written(tmp_path, tab("588_hotel-california"))) as b:
        blur(b)
        press(b, " ")
        counting = b.js(STATE)
        before, after, y = turned(b, "PageDown")
        status = b.js(STATE)
    assert counting == "counting" and status == "paused" and y > 0
    kept_down(before, after)
