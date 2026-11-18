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
from helpers.viewer_pages import back, harmony_tab, key, viewer as open_viewer
from test_viewer_harmony_tab import FAKE_SOUND, PLAY, SAID as PLAYING, SONG as PROG_SONG
from test_viewer_instruments_page import IN_E, SETTINGS, SONG, THREE, choose
from test_viewer_necks import reload, served, to_song

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

DESKTOP = {"width": 1280, "height": 800, "mobile": False}
READY = "document.documentElement.dataset.ready === '1'"
SAID = "[location.hash.split('=')[0], document.querySelector('#shift .d').textContent]"  # the settings' word


def _songbook(tmp_path, songs) -> str:
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    return path.as_uri()


@pytest.mark.parametrize("panel", ["settings", "harmony"])
def test_the_arrows_stay_in_the_song_while_a_panel_is_open(tmp_path, panel):
    """With the settings open, or the overlay's sheet on its Harmony tab, ← and → stay with it (a progression playing
    there goes on), as with a card open."""
    book = _songbook(tmp_path, [BookSong("One", "Synthetic", cho=PROG_SONG, id="aaaa"),
                                BookSong("Two", "Synthetic", cho=IN_E, id="bbbb")])
    size = DESKTOP if panel == "settings" else {"width": 1100, "height": 800, "mobile": False}  # the sheet, not the rail
    with open_viewer(tmp_path, book + "#song-1", **size) as b:
        if panel == "harmony":
            b.js(FAKE_SOUND)
            harmony_tab(b)
            b.js(PLAY)
            b.js("document.querySelector('#harmony .prog-play').focus()")  # on ■, as a tap on ▶ leaves it
        else:
            b.click("#more")
        b.js("window.before = true")
        key(b, "ArrowRight", 39)
        time.sleep(0.5)
        seen = b.js("[location.hash.split('=')[0], window.before === true]")
        playing = b.js(PLAYING) if panel == "harmony" else None
    assert seen == ["#song-1", True], seen
    assert playing == ("Stop" if panel == "harmony" else None)  # the progression goes on




def test_from_1200_px_a_progression_playing_from_the_rail_keeps_the_arrows_and_stopped_lets_them_go(tmp_path):
    """The rail is no layer: with its Harmony tab shown, ← and → go from song to song, but not while a progression
    plays from it (book.js busy(): #harmony[data-playing])."""
    book = _songbook(tmp_path, [BookSong("One", "Synthetic", cho=PROG_SONG, id="aaaa"),
                                BookSong("Two", "Synthetic", cho=IN_E, id="bbbb")])
    with open_viewer(tmp_path, book + "#song-1", **DESKTOP) as b:
        b.js(FAKE_SOUND)
        harmony_tab(b)
        b.js(PLAY)
        b.js("document.querySelector('#harmony .prog-play').focus()")  # on ■, as a tap on ▶ leaves it
        b.js("window.before = true")
        key(b, "ArrowRight", 39)
        time.sleep(0.5)
        held = b.js(f"[location.hash.split('=')[0], window.before === true, {PLAYING},"
                    " document.getElementById('harmony').hasAttribute('data-playing')]")
        b.js(PLAY)  # ■
        stopped = b.js("document.getElementById('harmony').hasAttribute('data-playing')")
        key(b, "ArrowRight", 39)
        assert b.wait("!window.before && document.documentElement?.dataset.ready === '1'")
        moved = b.js("location.hash.split('=')[0]")
    assert held == ["#song-1", True, "Stop", True]
    assert stopped is False and moved == "#song-2"


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


@pytest.mark.parametrize("where", ["file", "served"])
def test_a_reload_on_a_song_on_its_own_instrument_keeps_the_players_for_the_songs_after(tmp_path, where):
    """A set list's song on its own instrument (the ukulele), the player on the piano: reloaded there (F5, a tab the
    browser restores), the song is on its own still, and the songs after it on the player's, never the song's own."""
    songs = [BookSong("One", "Synthetic", cho=SONG, id="aaaa"),
             BookSong("Two", "Synthetic", cho=IN_E, id="bbbb", start="t=0&inst=ukulele"),
             BookSong("Three", "Synthetic", cho=THREE, id="cccc")]
    html = build_songbook("Campfire", songs)
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(html, encoding="utf-8")
    with served({"/_songbooks/Campfire/songbook.html": (html, songbook_csp)}) if where == "served" \
            else nullcontext() as site:
        page = site + "/_songbooks/Campfire/songbook.html" if site else path.as_uri()
        with open_viewer(tmp_path, page + "#song-1") as b:
            choose(b, "Piano")  # the player's instrument
            to_song(b, 2)  # its own: the ukulele
            two = b.js(SETTINGS)
            reload(b)
            again = b.js(SETTINGS)
            to_song(b, 3)
            three = b.js(SETTINGS)
    assert two["chips"][1][1] == "true" and again["chips"][1][1] == "true"  # the ukulele, its own
    assert three["chips"][4][1] == "true", three["hash"]  # the piano: the player's


@pytest.mark.parametrize("where", ["file", "sandbox"])
def test_back_closes_a_songs_layer_and_stays_on_the_song(tmp_path, where):
    """Back closes the settings a song opened and the songbook stays on that song, unreloaded, with the change made
    there (in the sandbox the address alone keeps it)."""
    songs = [BookSong("One", "Synthetic", cho=IN_E, id="aaaa"), BookSong("Two", "Synthetic", cho=THREE, id="bbbb")]
    html = build_songbook("Campfire", songs)
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(html, encoding="utf-8")
    with served({"/_songbooks/Campfire/songbook.html": (html, songbook_csp)}) if where == "sandbox" \
            else nullcontext() as site:
        page = site + "/_songbooks/Campfire/songbook.html" if site else path.as_uri()
        with open_viewer(tmp_path, page + "#song-1", **DESKTOP) as b:
            b.js("window.marker = 1")
            b.click("#more")
            assert b.wait("!document.getElementById('panel').hidden")
            b.click("#up")
            assert b.wait("location.hash.includes('t=1')")
            back(b)
            assert b.wait("document.getElementById('panel').hidden")
            time.sleep(0.5)
            seen = b.js("[window.marker, document.querySelector('#shift .d').textContent, location.hash]")
    assert seen[0] == 1, seen
    assert seen[1] == "+1" and "t=1" in seen[2], seen


def test_a_step_to_the_next_song_with_a_layer_open_then_back_returns_to_it(tmp_path):
    book = _songbook(tmp_path, [BookSong("One", "Synthetic", cho=IN_E, id="aaaa"),
                                BookSong("Two", "Synthetic", cho=THREE, id="bbbb")])
    with open_viewer(tmp_path, book + "#song-1", **DESKTOP) as b:
        b.click("#more")
        assert b.wait("!document.getElementById('panel').hidden")
        b.js("window.marker = 1")
        b.click("a[rel=next]")
        assert b.wait("window.marker === undefined && " + READY)
        assert b.js("location.hash.startsWith('#song-2')")
        back(b)
        assert b.wait("location.hash.startsWith('#song-1') && " + READY)
        time.sleep(0.5)
        seen = b.js("[document.getElementById('panel').hidden, (history.state || {}).caracoleLayer || 0]")
    assert seen == [True, 0], seen
