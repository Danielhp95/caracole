"""A songbook's songs in the viewer (book.js): each song's own settings, the player's instrument and the arrows.

book.js shows one song of songbook.html at a time and keeps each song's settings apart; the screen's choices (the
instrument among them) are the player's, kept from song to song. These tests open a songbook from a file (the
browser keeps its settings) and in caracole serve's sandbox (only the address does), in Chromium.
"""

from __future__ import annotations

import time
from contextlib import nullcontext

import pytest

from caracole.viewer.book import BookSong, build_songbook, songbook_csp

from helpers.browser import CHROMIUM_MARKS, Browser
from helpers.viewer_pages import key, viewer as open_viewer
from test_viewer_instruments_page import IN_E, SETTINGS, SONG, THREE, choose
from test_viewer_necks import reload, served, to_song
from test_viewer_panels import SONG as PROG_SONG

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

DESKTOP = {"width": 1280, "height": 800, "mobile": False}
READY = "document.documentElement.dataset.ready === '1'"
SAID = "[location.hash.split('=')[0], document.getElementById('shift').textContent]"


def _songbook(tmp_path, songs) -> str:
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    return path.as_uri()


@pytest.mark.parametrize("panel", ["settings", "harmony"])
def test_the_arrows_stay_in_the_song_while_a_panel_is_open(tmp_path, panel):
    """With the settings or the Harmony panel open, ← and → stay with it (a progression playing there goes on), as
    with a card or the overlay's sheet open."""
    book = _songbook(tmp_path, [BookSong("One", "Synthetic", cho=PROG_SONG, id="aaaa"),
                                BookSong("Two", "Synthetic", cho=IN_E, id="bbbb")])
    with open_viewer(tmp_path, book + "#song-1", **DESKTOP) as b:
        b.click("#more")
        if panel == "harmony":
            b.click("#harmony-open")
            assert b.wait("!document.getElementById('harmony').hidden")
        b.js("window.before = true")
        key(b, "ArrowRight", 39)
        time.sleep(0.5)
        seen = b.js("[location.hash.split('=')[0], window.before === true]")
    assert seen == ["#song-1", True], seen



class _Tab:
    """Another tab of ``b``'s browser, in its browser context: the same storage."""

    def __init__(self, b: Browser, url: str):
        self.b = b
        self.target = b._send("Target.createTarget", url=url)["targetId"]
        self.session = b._send("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]

    def js(self, expression: str):
        result = self.b._chromium.send("Runtime.evaluate", {"expression": expression, "returnByValue": True},
                                       session=self.session, timeout=30)
        assert "exceptionDetails" not in result, result
        return result.get("result", {}).get("value")

    def wait(self, expression: str, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.js(f"(() => {{ try {{ return Boolean({expression}); }} catch (e) {{ return false; }} }})()"):
                    return True
            except Exception:  # noqa: BLE001 - a page between two documents
                pass
            time.sleep(0.03)
        return False


def test_two_tabs_of_one_songbook_keep_each_songs_own_settings(tmp_path):
    """Two tabs of a songbook from a file, each on another song: each song comes back as it was left in its tab, never
    with what the other tab's song wrote."""
    book = _songbook(tmp_path, [BookSong("One", "Synthetic", cho=PROG_SONG, id="aaaa"),
                                BookSong("Two", "Synthetic", cho=IN_E, id="bbbb"),
                                BookSong("Three", "Synthetic", cho=THREE, id="cccc")])
    with open_viewer(tmp_path, book + "#song-1", **DESKTOP) as b:
        b.js("document.getElementById('t-up').click(); document.getElementById('t-up').click()")  # song 1: two up
        one = b.js(SAID)
        other = _Tab(b, book + "#song-2")  # song 2, in another tab (this one goes out of sight)
        assert other.wait(READY)
        other.js("document.getElementById('t-down').click()")  # song 2: one down
        two = other.js(SAID)
        targets = [t["targetId"] for t in b._send("Target.getTargets")["targetInfos"]
                   if t["type"] == "page" and t["targetId"] != other.target and "songbook.html" in t["url"]]
        b._send("Target.activateTarget", targetId=targets[0])
        assert b.wait("document.visibilityState === 'visible'")
        assert other.wait("document.visibilityState === 'hidden'")
        to_song(b, 3)
        to_song(b, 1)
        back = b.js(SAID)
        b._send("Target.activateTarget", targetId=other.target)
        assert other.wait("document.visibilityState === 'visible'")
        other.js("window.before = true; location.hash = 'song-3'")
        assert other.wait("!window.before && " + READY)
        other.js("window.before = true; location.hash = 'song-2'")
        assert other.wait("!window.before && " + READY)
        again = other.js(SAID)
    assert one == ["#song-1", "+2"] and two == ["#song-2", "−1"]
    assert back == ["#song-1", "+2"], back  # song 1 as it was left
    assert again == ["#song-2", "−1"], again  # and song 2
