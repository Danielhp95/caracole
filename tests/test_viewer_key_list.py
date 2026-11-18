"""caracole.viewer: the key list, the twelve keys a tap away (page.py ``_KEY_LIST``, viewer.js ``drawKeyList``).

The key between − and + is a button: a tap opens the twelve keys in the song's mode, the key as written first (on an
instrument with no capo, the key the song sounds in), the one played pressed; choosing one transposes the song there,
the nearest way, as Easy keys does (the capo stays), and closes the list. It is a layer, as the settings are: docked on
the bar on a phone, a right-hand rail in the settings' place from 900 px, one step of the history while it is open;
Back, Escape and its × close it. A sheet with no key has none; nor has a harmonica tab's page, whose −/+ move its harp.
"""

from __future__ import annotations

import re
import time

from caracole.viewer import build_viewer, page, viewer_csp
from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import in_chromium
from helpers.viewer_pages import back, entries, key, viewer, written
from test_viewer import data_of
from test_viewer_bar import MINOR, NO_KEY, UG_CHO
from test_viewer_harptab_page import TAB_D, a_song
from test_viewer_harptab_page import page as harmonica_page
from test_viewer_necks import reload, served

DESKTOP = {"width": 1280, "height": 800, "mobile": False}
OPEN = "!document.querySelector('#key-list').hidden"
SHUT = "document.querySelector('#key-list').hidden"

# Each key in the list: what it says and whether it is pressed.
KEYS = "[...document.querySelectorAll('#key-items button')].map((b) => [b.textContent, b.getAttribute('aria-pressed')])"

# The list as you see it: where it is, where the focus is, what the key's button says of it, the history's depth.
LOOK = """(() => {
  const list = document.querySelector('#key-list'), r = list.getBoundingClientRect();
  const bar = document.querySelector('#bar').getBoundingClientRect();
  return {open: !list.hidden, seen: getComputedStyle(list).visibility,
          dock: document.documentElement.dataset.dock || null, docked: Math.abs(r.bottom - bar.top) <= 1,
          top: r.top, right: r.right, width: r.width,
          client: document.documentElement.clientWidth, panel: document.documentElement.dataset.panel || null,
          settings: !document.querySelector('#panel').hidden, focus: document.activeElement.id,
          expanded: document.querySelector('#key-now').getAttribute('aria-expanded'),
          depth: (history.state || {}).caracoleLayer || 0, hash: location.hash};
})()"""

# Each key's box in the list: as written across its row, the others four to a row, each a thumb's.
CELLS = """(() => {
  const grid = document.querySelector('#key-items').getBoundingClientRect();
  return [...document.querySelectorAll('#key-items button')].map((b) => {
    const r = b.getBoundingClientRect(), text = document.createRange(), s = getComputedStyle(b);
    text.selectNodeContents(b);
    const t = text.getBoundingClientRect();  // to the fraction of a pixel, within its padding
    const room = b.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
    return {cls: b.className, k: b.dataset.k, width: r.width, height: r.height, top: r.top, left: r.left - grid.left,
            span: Math.abs(r.width - grid.width) < 1, whole: t.width <= room && t.height <= b.clientHeight,
            size: parseFloat(s.fontSize),
            edge: getComputedStyle(b).borderTopColor, fill: getComputedStyle(b).backgroundColor};
  });
})()"""

# The bar's key, in short, and what it says changed under it.
SAID = ("[document.querySelector('#key-now .k').textContent, document.querySelector('#key-now .d').textContent,"
        " location.hash, document.activeElement.id]")


def chosen(b, k: int) -> None:
    """The key list opened from the bar's key, and key ``k`` (0, as written, to 11) chosen there: the list closed."""
    b.click("#key-now")
    assert b.wait(OPEN)
    b.click(f'#key-items button[data-k="{k}"]')
    assert b.wait(SHUT)


def settled(b) -> None:
    """Once the list's step of the history is off again (the page's own entry, the address carried down)."""
    assert b.wait("!(history.state && history.state.caracoleLayer)")


# --- the page as written ---------------------------------------------------------------------------


def test_the_key_is_a_button_that_opens_the_key_list():
    for html in (build_viewer(UG_CHO), build_viewer(UG_CHO, export=False)):  # sheet.html and a kept version's page
        assert re.search(r'<button type="button" class="now" id="key-now" aria-haspopup="dialog" '
                         r'aria-controls="key-list" aria-expanded="false"><span class="k" aria-hidden="true"></span>'
                         r'<span class="d" aria-hidden="true"></span><span class="vh" id="key-full"></span></button>',
                         html)
        assert '<section class="sheet-ui panel keylist" id="key-list" hidden role="dialog"' in html
        assert page._KEY_LIST in html
        # right after the settings, before a chord's card
        assert html.index('id="panel"') < html.index('id="key-list"') < html.index('id="card"')
        assert html.index(page._KEY_LIST) == html.index("</section>\n", html.index('id="panel"')) + len("</section>\n")
    # A songbook's songs have it too: they share the bar.
    assert page._KEY_LIST in build_songbook("Campfire", [BookSong("One", "Synthetic", cho=MINOR, id="aaaa")])
    # The harmonica page keeps its harp −/+ and no list.
    assert 'id="key-list"' not in harmonica_page(TAB_D, cho=a_song(), key="Am", key_source="tab")


# --- what it shows -----------------------------------------------------------------------------------


@in_chromium
def test_tapping_the_key_opens_the_twelve_keys_as_written_first(tmp_path):
    names = data_of(build_viewer(MINOR))["keyNames"]["aeolian"]  # Cm: tonic 0
    with viewer(tmp_path, written(tmp_path, MINOR)) as b:
        before = b.js(LOOK)
        b.click("#key-now")
        assert b.wait(OPEN)
        shown = b.js(KEYS)
        where = b.js(LOOK)
        cells = b.js(CELLS)
        b.click("#t-up")  # the bar's +, with the list open: it follows
        followed = [b.js(KEYS), b.js(LOOK)["open"], b.js(CELLS)]
    assert before["expanded"] == "false" and before["depth"] == 0
    assert [t for t, _ in shown] == [names[0] + " · as written"] + names[1:]
    assert [p for _, p in shown] == ["true"] + ["false"] * 11
    # Docked on the bar, as the settings are; the focus on its heading; one step of the history.
    assert where["dock"] == "key-list" and where["docked"] and where["seen"] == "visible", where
    assert where["focus"] == "key-list-title" and where["expanded"] == "true" and where["depth"] == 1, where
    # As written across the first row, in the song's own mode's look; the others four to a row, each 48 px tall on a
    # touch screen, whole.
    assert [c["k"] for c in cells] == [str(k) for k in range(12)]
    assert cells[0]["cls"] == "key-as" and cells[0]["span"] and not any(c["span"] for c in cells[1:])
    assert all(c["cls"] == "" for c in cells[1:])
    assert [round(c["left"]) for c in cells[1:5]] == [round(c["left"]) for c in cells[5:9]]
    assert len({round(c["width"]) for c in cells[1:]}) == 1 and len({round(c["top"]) for c in cells[1:5]}) == 1
    assert all(c["height"] == 48 and c["whole"] and c["size"] == 14.4 for c in cells), cells  # none made smaller
    assert [p for _, p in followed[0]] == ["false", "true"] + ["false"] * 10 and followed[1]
    # The key played in the accent's edge, wherever it is; as written in the song's own mode's fill, pressed or not.
    after = followed[2]
    assert after[1]["edge"] == cells[0]["edge"] != cells[1]["edge"] == after[2]["edge"]
    assert after[0]["edge"] not in (cells[0]["edge"], cells[1]["edge"])  # the own mode's edge, unpressed
    assert after[0]["fill"] == cells[0]["fill"] != cells[1]["fill"] == after[1]["fill"]


@in_chromium
def test_a_mode_with_long_names_keeps_every_key_whole_on_a_phone_and_in_the_rail(tmp_path):
    # "Ab mixolydian" four a row: its two words on two lines, and a little smaller where even "mixolydian" is too long,
    # the eleven alike, as the bar's key is; as written has its row.
    for width, height, mobile, smaller in ((390, 844, True, False), (320, 640, True, True), (1280, 800, False, True)):
        with viewer(tmp_path, written(tmp_path, UG_CHO, name=f"W{width}") + "#mode=mixolydian", width=width,
                    height=height, mobile=mobile) as b:
            b.click("#key-now")
            assert b.wait(OPEN)
            shown = b.js(KEYS)
            cells = b.js(CELLS)
            wide = b.js("document.documentElement.scrollWidth > innerWidth")
        assert shown[0][0] == "G mixolydian · as written" and shown[1][0] == "Ab mixolydian", width
        assert all(c["whole"] and c["height"] == (48 if mobile else 44) for c in cells) and not wide, (width, cells)
        sizes = {c["size"] for c in cells[1:]}
        assert len(sizes) == 1 and cells[0]["size"] == 14.4, (width, cells)
        size = sizes.pop()  # whole at 390 px; smaller in a cell of the 360 px rail or of a 320 px phone, as measured
        assert (14.4 * 0.75 <= size < 14.4) if smaller else size == 14.4, (width, size)


# --- what it does ------------------------------------------------------------------------------------


@in_chromium
def test_a_key_chosen_moves_the_song_there_the_nearest_way_and_the_list_closes(tmp_path):
    with viewer(tmp_path, written(tmp_path, MINOR)) as b:
        chosen(b, 4)
        four = b.js(SAID)
        settled(b)
        b.click("#key-now")
        assert b.wait(OPEN)
        again = b.js(KEYS)
        b.click('#key-items button[data-k="0"]')  # as written again
        assert b.wait(SHUT)
        written_again = b.js(SAID)
        settled(b)
        chosen(b, 11)  # a semitone down, the nearest way, never eleven up
        eleven = b.js(SAID)
    assert four == ["Em", "+4", "#t=4", "key-now"]
    assert [p for _, p in again] == ["false"] * 4 + ["true"] + ["false"] * 7
    assert written_again[:3] == ["Cm", "key", ""]
    assert eleven == ["Bm", "−1", "#t=-1", "key-now"]
    with viewer(tmp_path, written(tmp_path, UG_CHO, name="Capo")) as b:  # G shapes, capo 2
        chosen(b, 2)
        capo = b.js(SAID) + [b.js("document.querySelector('#capo-at').textContent")]
    assert capo == ["A", "capo 2 · +2", "#t=2", "key-now", "2"]  # the capo stays where it was


@in_chromium
def test_on_the_piano_the_list_starts_at_the_key_the_song_sounds_in(tmp_path):
    names = data_of(build_viewer(UG_CHO))["keyNames"]["ionian"]
    with viewer(tmp_path, written(tmp_path, UG_CHO) + "#inst=piano") as b:  # G shapes, capo 2: it sounds in A
        b.click("#key-now")
        assert b.wait(OPEN)
        shown = b.js(KEYS)
        b.click('#key-items button[data-k="1"]')
        assert b.wait(SHUT)
        up = b.js(SAID)
    assert shown[0] == [names[(7 + 2) % 12] + " · as written", "true"]
    assert [t for t, _ in shown[1:]] == [names[(7 + 2 + k) % 12] for k in range(1, 12)]
    assert up[:3] == [names[(7 + 3) % 12], "+1", "#inst=piano&t=1"]


@in_chromium
def test_escape_back_and_close_close_it(tmp_path):
    with viewer(tmp_path, written(tmp_path, MINOR)) as b:
        start = entries(b)
        closed = {}
        for how in ("Escape", "×", "Back", "the key"):
            b.click("#key-now")
            assert b.wait(OPEN)
            opened = [b.js(LOOK)["depth"], entries(b)]
            if how == "Escape":
                b.press("Escape")
            elif how == "×":
                b.click("#key-list [data-close]")
            elif how == "Back":
                back(b)  # the browser's own Back: the list's step of the history
            else:
                b.click("#key-now")  # the key again, as ⋯ closes the settings
            assert b.wait(SHUT)
            settled(b)
            look = b.js(LOOK)
            closed[how] = [opened, look["focus"], look["expanded"], look["dock"]]
    for how, (opened, focus, expanded, dock) in closed.items():
        assert opened == [1, (start[0] + 1, start[1] + 1)], how
        assert focus == "key-now" and expanded == "false" and dock is None, how


@in_chromium
def test_from_900_px_it_is_a_rail_in_the_settings_place(tmp_path):
    with viewer(tmp_path, written(tmp_path, MINOR), **DESKTOP) as b:
        b.click("#key-now")
        assert b.wait(OPEN)
        rail = b.js(LOOK)
        cells = b.js(CELLS)
        b.click("#t-up")
        followed = b.js(KEYS)
        b.click("#more")  # the settings in its place: one rail at a time
        assert b.wait(SHUT)
        settings = b.js(LOOK)
        b.click("#key-now")  # and the list in theirs
        assert b.wait(OPEN)
        back_in = b.js(LOOK)
    assert rail["right"] == rail["client"] and rail["top"] == 0 and rail["width"] == 360, rail
    assert rail["panel"] == "open" and rail["dock"] is None and rail["focus"] == "key-list-title", rail
    assert all(c["height"] == 44 and c["whole"] for c in cells), cells  # a mouse's 44 px
    assert [p for _, p in followed] == ["false", "true"] + ["false"] * 10
    assert settings["settings"] and not settings["open"] and settings["expanded"] == "false" and settings["depth"] == 1
    assert back_in["open"] and not back_in["settings"] and back_in["depth"] == 1 and back_in["panel"] == "open"


@in_chromium
def test_a_sheet_with_no_key_has_no_list(tmp_path):
    with viewer(tmp_path, written(tmp_path, NO_KEY)) as b:
        start = entries(b)
        disabled = b.js("document.querySelector('#key-now').disabled")
        popup = b.js("document.querySelector('#key-now').getAttribute('aria-haspopup')")  # none: it opens nothing
        b.click("#key-now")
        time.sleep(0.3)
        look = [b.js(LOOK), b.js(KEYS), entries(b)]
    assert disabled and popup is None
    assert not look[0]["open"] and look[0]["expanded"] == "false" and look[0]["depth"] == 0
    assert look[1] == [] and look[2] == start


@in_chromium
def test_served_in_its_sandbox_with_no_storage_a_key_chosen_is_kept_by_the_address(tmp_path):
    sheet = "/Artist/Title/sheet.html"
    with served({sheet: (build_viewer(MINOR), viewer_csp)}) as site, viewer(tmp_path, site + sheet) as b:
        storage = b.js("(() => { try { localStorage.getItem('x'); return true; } catch (err) { return false; } })()")
        chosen(b, 2)
        settled(b)
        reload(b)
        kept = b.js(SAID)
    assert storage is False
    assert kept[:3] == ["Dm", "+2", "#t=2"]


@in_chromium
def test_in_a_songbook_the_arrows_stay_with_the_open_list(tmp_path):
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", [BookSong("One", "Synthetic", cho=MINOR, id="aaaa"),
                                                BookSong("Two", "Synthetic", cho=UG_CHO, id="bbbb")]), encoding="utf-8")
    with viewer(tmp_path, path.as_uri() + "#song-1", **DESKTOP) as b:
        b.click("#key-now")
        assert b.wait(OPEN)
        b.js("window.before = true")
        key(b, "ArrowRight", 39)
        time.sleep(0.5)
        seen = b.js("[location.hash.split('=')[0], window.before === true, "
                    "!document.querySelector('#key-list').hidden]")
    assert seen == ["#song-1", True, True], seen
