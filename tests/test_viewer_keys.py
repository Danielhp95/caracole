"""No viewer page takes a key from the browser: the owner's choice of 2026-11-22, for Vimium ("I can't use vimium keys
when I am on Caracole ... Remove the keybindings that caracole takes entirely", a page turner's pedal among them, which
now scrolls the page as the browser does). Space, Enter, the page keys, the arrows and Vimium's letters reach the
browser untouched on a sheet, a songbook and a harmonica tab's page: no autoscroll started, no song changed, no version.
The keys of caracole's own controls stay theirs: a chord's Space opens its card, a focused button presses itself, the
rail's tabs take their arrows, Escape closes what is open. A pointer's press on a button that steers autoscroll takes no
focus (screen.js ``steer``), so that no button the bar hides holds the next key. These tests drive the pages on real
time in Chromium (helpers/browser.py's ``Browser``).
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import CHROMIUM_MARKS, Browser
from helpers.version_pages import WONDERWALL, folder
from helpers.viewer_pages import tap_at, written
from test_viewer_harptab_browser import tab, written as harmonica_written

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

# A long sheet of short lines, so that the page has somewhere to scroll.
LONG = "{title: Long Song}\n{artist: Synthetic}\n" + "".join(
    f"{{comment: Verse {n}}}\n" + "".join(f"[G]Line [D]{n}.{m}\n" for m in range(4)) for n in range(40))

PHONE = {"width": 390, "height": 844, "mobile": True}
LAPTOP = {"width": 1280, "height": 900, "mobile": False}
READY = "document.documentElement.dataset.ready === '1'"
STATE = "document.getElementById('pill').dataset.state"

# Each key as Chromium's input sends it: its code, its key code, and the text it types.
KEYS = {" ": ("Space", 32, " "), "Enter": ("Enter", 13, "\r"), "PageDown": ("PageDown", 34, None),
        "PageUp": ("PageUp", 33, None), "ArrowDown": ("ArrowDown", 40, None), "ArrowUp": ("ArrowUp", 38, None),
        "ArrowLeft": ("ArrowLeft", 37, None), "ArrowRight": ("ArrowRight", 39, None), "/": ("Slash", 191, "/"),
        "j": ("KeyJ", 74, "j"), "k": ("KeyK", 75, "k"), "f": ("KeyF", 70, "f")}
# The keys a reader, a page turner and Vimium send: none of them the page's.
EVERY = [" ", "Enter", "PageDown", "PageUp", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "/", "j", "k", "f"]

# Whether each key the page heard had its default prevented once every handler of the page ran (window's listeners
# in the bubbling phase are the last).
HEARD = """window.heard = [];
addEventListener('keydown', (e) => { heard.push([e.key, e.defaultPrevented]); });"""


@contextmanager
def opened(tmp_path: Path, url: str, *, width: int = 390, height: int = 844, mobile: bool = True):
    """The page at ``url`` in Chromium, ``width`` × ``height``, once its script ran."""
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), width=width, height=height,
                 mobile=mobile) as b:
        b.open(url)
        assert b.wait(READY)
        yield b


def press(b: Browser, name: str) -> None:
    """``name`` pressed and let go where the focus is, with the text it types."""
    code, number, text = KEYS[name]
    b.send("Input.dispatchKeyEvent", type="keyDown", key=name, code=code, windowsVirtualKeyCode=number,
           **({"text": text} if text else {}))
    b.send("Input.dispatchKeyEvent", type="keyUp", key=name, code=code, windowsVirtualKeyCode=number)


def blur(b: Browser) -> None:
    """The focus on the page itself, as a reader who tapped beside the song has it."""
    b.js("document.activeElement && document.activeElement.blur()")


def untaken(b: Browser, names: list[str]) -> list:
    """Each of ``names`` pressed with the focus on the page: what the page did with them."""
    b.js("heard.length = 0")
    for name in names:
        blur(b)
        press(b, name)
    return b.js("heard")


@pytest.mark.parametrize("size", [PHONE, LAPTOP], ids=["phone", "laptop"])
def test_a_sheet_takes_no_key(tmp_path, size):
    with opened(tmp_path, written(tmp_path, LONG), **size) as b:
        b.js(HEARD)
        path = b.js("location.pathname + location.hash")
        heard = untaken(b, EVERY)
        state = [b.js(STATE), b.js("document.getElementById('version-list').hidden"),
                 b.js("location.pathname + location.hash") == path]
    assert heard == [[name, False] for name in EVERY], heard  # every key the browser's (and Vimium's)
    assert state == ["off", True, True], state  # no autoscroll, no version list, the same page


def test_a_songbook_takes_no_key_its_songs_changed_by_its_links(tmp_path):
    short = "{title: One}\n{artist: Synthetic}\n" + "".join(f"[G]Line [D]{n}\n" for n in range(30))
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", [BookSong("One", "Synthetic", cho=short, id="aaaa"),
                                                BookSong("Two", "Synthetic", cho=short, id="bbbb")]), "utf-8")
    with opened(tmp_path, path.as_uri() + "#song-1") as b:
        b.js(HEARD)
        b.js("window.before = true")
        heard = untaken(b, EVERY)
        stayed = b.wait("window.before !== true || !location.hash.startsWith('#song-1')", 0.5)
        state = b.js(STATE)
    assert heard == [[name, False] for name in EVERY], heard
    assert not stayed and state == "off"  # ← → change no song: the pagers' links do, and a swipe


def test_the_harmonica_page_takes_no_key(tmp_path):
    with opened(tmp_path, harmonica_written(tmp_path, tab("588_hotel-california"))) as b:
        b.js(HEARD)
        heard = untaken(b, EVERY)
        state = b.js(STATE)
    assert heard == [[name, False] for name in EVERY] and state == "off", (heard, state)


def test_its_own_controls_keep_their_keys(tmp_path):
    # Space on a chord with the focus opens its card; Enter on the bar's Scroll presses it: their own, as in any page.
    with opened(tmp_path, written(tmp_path, LONG)) as b:
        b.js(HEARD)
        b.js("document.querySelector('#sheet .c').focus()")
        b.js("heard.length = 0")
        b.press(" ")
        chord = [b.js("heard"), b.wait("!document.getElementById('card').hidden")]
        b.press("Escape")  # what is open closes
        closed = b.wait("document.getElementById('card').hidden")
        b.js("document.getElementById('scroll').focus(); heard.length = 0")
        b.press("Enter")
        scroll = [b.js("heard"), b.js(STATE)]
    assert chord == [[[" ", True]], True] and closed
    assert scroll == [[["Enter", False]], "counting"]  # the button's own press


def test_the_rails_tabs_keep_their_arrows_on_a_laptop(tmp_path):
    with opened(tmp_path, written(tmp_path, LONG), **LAPTOP) as b:
        b.js(HEARD)
        assert b.wait("document.querySelector('#necks [role=tab]') !== null")
        b.js("document.querySelector('#necks [role=tab]').focus()")
        for name in ("PageDown", "ArrowDown"):
            press(b, name)
        heard, state = b.js("heard"), b.js(STATE)
    # The tabs' own arrows go from tab to tab, and no further; PageDown is the browser's.
    assert heard == [["PageDown", False]] and state == "off", (heard, state)


@pytest.mark.parametrize("size", [PHONE, LAPTOP], ids=["finger", "mouse"])
def test_a_button_that_steers_autoscroll_pressed_by_hand_takes_no_focus(tmp_path, size):
    # A browser focuses a button tapped or clicked: one the bar then hides would take the next Space as its own press.
    with opened(tmp_path, written(tmp_path, LONG), **size) as b:
        b.click("#scroll")
        assert b.wait(f"{STATE} === 'counting'")
        b.click("#go")  # at once
        assert b.wait(f"{STATE} === 'running'")
        started = b.js("document.activeElement === document.body")
        if size["mobile"]:
            tap_at(b, *b.js("(() => { const r = document.getElementById('pill-faster').getBoundingClientRect();"
                            " return [r.left + r.width / 2, r.top + r.height / 2]; })()"))
        else:
            b.click("#pill-faster")
        faster = [b.js("document.getElementById('pill-speed').textContent"), b.js("document.activeElement.id"),
                  b.js(STATE)]
    assert started and faster == ["7", "", "running"]  # a step faster, and the focus where it was: on the page


def test_no_key_changes_the_version(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with opened(tmp_path, pages["sheet.html"].as_uri()) as b:
        b.js("window.stayed = true")
        path = b.js("location.pathname")
        for name in ("ArrowLeft", "ArrowRight", "PageDown", " "):
            blur(b)
            press(b, name)
        left = b.wait(f"window.stayed !== true || location.pathname !== {path!r}", 0.5)
        listed = b.js("document.getElementById('version-list').hidden")
    assert not left and listed
