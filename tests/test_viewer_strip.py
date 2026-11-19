"""The strip of every chord's shape (viewer.js ``stripShown``): shown by default below 1200 px, where no rail holds the
shapes, above the song's first section; from 1200 px the rail holds them and the strip waits for its switch; hidden by
hand it stays hidden for that song alone."""

from __future__ import annotations

import pytest

from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import CHROMIUM_MARKS, Browser
from helpers.viewer_pages import drag, viewer as open_viewer, written
from test_viewer_necks import reload, reopen, served, to_song
from caracole.viewer.book import songbook_csp

pytestmark = CHROMIUM_MARKS

SONG = ("{title: Strip}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n"
        "[C]made [Am]up [F]words [G7]here\n[C]and [Am]some [F]more [G7]there\n")
LONG = SONG + "".join(f"{{comment: Part {n}}}\n[C]la [Am]la [F]la [G7]la\n" * 1 for n in range(40))
OTHER = "{title: Other}\n{artist: Synthetic}\n{key: E}\n{comment: Verse}\n[E]la [A]la [B7]la [E]la\n"
DESKTOP = {"width": 1280, "height": 900, "mobile": False}
STRIP = """(() => { const s = document.querySelector('#strip');
  const first = document.querySelector('section.sec');
  return {shown: !s.hidden && s.getClientRects().length > 0, buttons: s.querySelectorAll('button').length,
          names: [...s.querySelectorAll('button')].map((x) => x.lastChild.textContent),
          bottom: s.getBoundingClientRect().bottom, above: first.getBoundingClientRect().top,
          pressed: document.querySelector('#strip-toggle').getAttribute('aria-pressed'),
          wide: document.documentElement.scrollWidth <= window.innerWidth}; })()"""


def strip(b: Browser) -> dict:
    return b.js(STRIP)


def switch(b: Browser) -> None:
    b.js("(() => { if (document.getElementById('panel').hidden) document.getElementById('more').click();"
         " document.getElementById('strip-toggle').click(); })()")


def test_on_a_phone_the_strip_shows_the_songs_shapes_above_the_first_section(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG)) as b:
        seen = strip(b)
        assert seen["shown"] and seen["names"] == ["C", "Am", "F", "G7"] and seen["pressed"] == "true"
        assert seen["bottom"] <= seen["above"]
        drag(b, 800)
        assert b.js("document.querySelector('#strip').getBoundingClientRect().bottom") < 0
        b.js("window.scrollTo(0, 0)")
        b.click("#strip button:nth-child(2)")
        assert b.wait("document.querySelector('#card-name').textContent === 'Am'")


def test_from_1200_px_the_rail_holds_the_shapes_and_the_strip_waits_for_its_switch(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        seen = strip(b)
        assert not seen["shown"] and seen["pressed"] == "false"
        switch(b)
        seen = strip(b)
        assert seen["shown"] and seen["pressed"] == "true"


def test_hidden_by_hand_it_stays_hidden_for_that_song_alone(tmp_path):
    url = written(tmp_path, SONG)
    other = written(tmp_path, OTHER, "Other")
    with open_viewer(tmp_path, url) as b:
        switch(b)
        assert not strip(b)["shown"]
        reload(b)
        assert not strip(b)["shown"]
        reopen(b, other)
        assert strip(b)["shown"]


def test_a_song_opened_before_keeps_the_default(tmp_path):
    url = written(tmp_path, SONG)
    with open_viewer(tmp_path, url) as b:
        key = b.js("Object.keys(localStorage).find((k) => k.startsWith('caracole-viewer:'))")
        if key is None:
            switch(b)
            switch(b)
            key = b.js("Object.keys(localStorage).find((k) => k.startsWith('caracole-viewer:'))")
        assert key
        b.js(f"localStorage.setItem({key!r}, JSON.stringify({{base: 0, strip: false}}))")
        reload(b)
        assert strip(b)["shown"]


@pytest.mark.parametrize("inst, drawn", [("ukulele", "svg"), ("piano", "svg.kb"), ("harmonica", "svg.hp")])
def test_the_strip_draws_the_instrument_shown(tmp_path, inst, drawn):
    with open_viewer(tmp_path, written(tmp_path, SONG) + f"#inst={inst}") as b:
        assert strip(b)["shown"]
        assert b.js(f"document.querySelectorAll('#strip button {drawn}').length") == 4
        if inst == "ukulele":  # a box of four strings
            assert b.js("""[...document.querySelectorAll('#strip button svg')].every((svg) =>
              new Set([...svg.querySelectorAll('[data-string]')].map((m) => m.dataset.string)).size === 4)""")


NO_SHAPE = ("{title: Riffs}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n"
            "[N.C.]made up [Xq]words [C]here\n")


def test_a_chord_with_no_shape_is_still_a_fingers_width_in_the_strip(tmp_path):
    # N.C. and a chord no instrument has a shape of are their names alone: shown by default on every phone, each is
    # still a target a finger finds, as the bar's are (48 px).
    with open_viewer(tmp_path, written(tmp_path, NO_SHAPE)) as b:
        seen = strip(b)
        widths = b.js("[...document.querySelectorAll('#strip button')].map((x) => x.getBoundingClientRect().width)")
    assert seen["shown"] and seen["names"] == ["N.C.", "Xq", "C"]
    assert all(w >= 48 for w in widths), widths


@pytest.mark.parametrize("size", [{"width": 320, "height": 640}, {"width": 844, "height": 390}])
def test_the_strip_fits_a_320_px_phone_and_one_on_its_side(tmp_path, size):
    with open_viewer(tmp_path, written(tmp_path, SONG), **size) as b:
        seen = strip(b)
        assert seen["shown"] and seen["wide"]


def test_a_songbook_song_shows_its_strip_and_the_harmonica_page_has_none(tmp_path):
    from caracole.viewer.harptab_page import build_harmonica_viewer

    book = tmp_path / "book.html"
    book.write_text(build_songbook("Book", [BookSong("Strip", "Synthetic", cho=SONG, id="aaaa")]), encoding="utf-8")
    with open_viewer(tmp_path, book.as_uri() + "#song-1") as b:
        assert b.js("""[...document.querySelectorAll('.strip')].some((s) => !s.hidden && s.querySelectorAll('button').length === 4)""")
    harp = tmp_path / "harp.html"
    harp.write_text(build_harmonica_viewer("Verse\n 4  -4  5\nla la la\n", title="T", tab_file="harmonica-1.txt"),
                    encoding="utf-8")
    with open_viewer(tmp_path, harp.as_uri()) as b:
        assert b.js("document.querySelector('.strip') === null")


def resize(b: Browser, width: int) -> None:
    b.send("Emulation.setDeviceMetricsOverride", width=width, height=900, deviceScaleFactor=1, mobile=False)
    assert b.wait(f"window.innerWidth === {width}")


def test_crossing_1200_px_follows_the_default_and_never_a_choice_made_by_hand(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), width=390, height=900, mobile=False) as b:
        assert strip(b)["shown"]
        resize(b, 1280)
        assert b.wait("document.querySelector('#strip').hidden")
        assert strip(b)["pressed"] == "false"
        resize(b, 390)
        assert b.wait("!document.querySelector('#strip').hidden")
        switch(b)  # hidden by hand at 390 px
        assert not strip(b)["shown"]
        resize(b, 1280)
        assert b.wait("window.innerWidth === 1280") and not strip(b)["shown"]
        resize(b, 390)
        assert b.wait("window.innerWidth === 390") and not strip(b)["shown"]


def test_the_strip_shown_by_default_leaves_the_columns_a_short_song_had(tmp_path):
    # The strip is above the sheet, outside the columns' room: layout() measures the sheet alone.
    with open_viewer(tmp_path, written(tmp_path, SONG), width=1100, height=900, mobile=False) as b:
        assert strip(b)["shown"]
        shown = b.js("document.documentElement.dataset.columns")
        switch(b)
        assert not strip(b)["shown"]
        assert b.js("document.documentElement.dataset.columns") == shown


def test_a_songbook_without_storage_shows_the_next_songs_strip_by_default(tmp_path):
    songs = [BookSong("Strip", "Synthetic", cho=SONG, id="aaaa"), BookSong("Other", "Synthetic", cho=OTHER, id="bbbb")]
    page = "/_songbooks/Book/songbook.html"
    with served({page: (build_songbook("Book", songs), songbook_csp)}) as site, \
            open_viewer(tmp_path, site + page + "#song-1") as b:
        assert strip(b)["shown"]
        switch(b)
        assert not strip(b)["shown"]
        to_song(b, 2)
        assert strip(b)["shown"]
