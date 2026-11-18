"""What a viewer opens on again (a reload, a tab the browser restores, Back or Forward to it), in Chromium.

A page writes into its address what the player chose there, so that where the browser keeps nothing (caracole serve's
sandbox) a reload keeps it. What nobody chose there (the song's own version, where the page opens) is no choice: once
that version changes, the page made again opens in the new one. And a choice the browser keeps once for every page
(the instrument, the rail of necks, the pinyin, the Chinese characters) is the one a page comes back on, whatever an
address written before it says.
"""

from __future__ import annotations

import json

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import CHROMIUM_MARKS
from helpers.viewer_pages import viewer as open_viewer, written
from test_viewer_harmony_tab import SONG
from test_viewer_necks import reload
from test_viewer_panels import LONG

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

IN_E = "{title: In E}\n{artist: Synthetic}\n{key: E}\n{comment: Verse}\n[E]la la [A]la la [B7]la la [E]la\n"
SAID = "[location.hash, document.querySelector('#shift .d').textContent]"  # the settings' word, the bar's
DESKTOP = {"width": 1280, "height": 800, "mobile": False}


def test_a_sheet_made_again_in_a_new_own_version_opens_in_it_after_a_reload(tmp_path):
    path = tmp_path / "Library" / "Artist" / "Title" / "sheet.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_viewer(IN_E, transpose=2, start="t=2"), encoding="utf-8")  # the song's own: two up
    with open_viewer(tmp_path, path.as_uri(), **DESKTOP) as b:  # as from the library: no address
        first = b.js(SAID)
        path.write_text(build_viewer(IN_E, transpose=4, start="t=4"), encoding="utf-8")  # made yours elsewhere
        reload(b)
        again = b.js(SAID)
        b.js("document.getElementById('t-up').click()")  # chosen here: five up
        chosen = b.js(SAID)
        reload(b)
        kept = b.js(SAID)
    assert first == ["", "+2"]  # nobody chose it: nothing in the address
    assert again == ["", "+4"]  # the song's own version now
    assert chosen == ["#t=5", "+5"] and kept == ["#t=5", "+5"]  # a choice made here stays


def test_a_songbook_song_whose_setting_changed_opens_in_it_after_a_reload(tmp_path):
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)

    def book(start: str) -> str:
        return build_songbook("Campfire", [BookSong("One", "Synthetic", cho=IN_E, id="aaaa", start=start)])

    path.write_text(book("t=2"), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-1", **DESKTOP) as b:
        first = b.js(SAID)
        path.write_text(book("t=-2"), encoding="utf-8")  # its chip on the Songbooks tab: another key
        reload(b)
        again = b.js(SAID)
    assert first[1] == "+2"
    assert again[1] == "−2", again


PICK = """(() => { const s = document.getElementById('insts'); s.value = %s;
  s.dispatchEvent(new Event('change', {bubbles: true})); })()"""
READY = "!window.before && document.documentElement?.dataset.ready === '1'"


def test_the_instrument_kept_for_every_page_is_the_one_a_sheet_comes_back_on(tmp_path):
    a, other = written(tmp_path, SONG, "A"), written(tmp_path, LONG, "B")
    with open_viewer(tmp_path, a, **DESKTOP) as b:
        b.click("#more")
        b.js(PICK % json.dumps("ukulele"))  # on sheet A: the ukulele, for every page
        b.js(f"window.before = true; location.href = {json.dumps(other)}")  # on to sheet B
        assert b.wait(READY)
        on_b = b.js("document.getElementById('insts').value")
        b.js(PICK % json.dumps("guitar"))  # on sheet B: the guitar, for every page
        b.js("window.before = true; history.back()")  # back to sheet A, its address saying the ukulele
        assert b.wait(READY)
        back = b.js("document.getElementById('insts').value")
    assert on_b == "ukulele"
    assert back == "guitar"  # the one kept for every page


def test_the_rail_kept_for_every_page_wins_over_an_address_written_before(tmp_path):
    a, other = written(tmp_path, SONG, "A"), written(tmp_path, LONG, "B")
    with open_viewer(tmp_path, a, **DESKTOP) as b:
        b.click("#necks-toggle")  # hidden, for every page: necks=0 in A's address
        b.js(f"window.before = true; location.href = {json.dumps(other)}")
        assert b.wait(READY)
        b.click("#necks-toggle")  # shown again, on B
        b.js("window.before = true; history.back()")
        assert b.wait(READY)
        back = b.js("[location.hash, getComputedStyle(document.getElementById('necks')).display !== 'none']")
    assert back == ["", True], back
