"""The sheet viewer's instrument (viewer.js ``state.inst``, instruments.js): the settings' Instrument row, the
ukuleles' four-string boxes and the piano's keyboard drawn as Python shapes them (viewer/instruments.py), the capo
folded in on the piano, the easy keys, the rail of necks, the setting kept as the rail of necks' is, and an
instrument another script registers.

The tests open a viewer in a Chromium of their own (helpers/viewer_pages.py) and read what it draws back: a box's
marks carry their string and fret (data-string, data-fret), a keyboard's keys their note (data-note, data-role).
"""

from __future__ import annotations

import json
from contextlib import nullcontext

import pytest

from caracole.viewer import build_viewer, instruments, viewer_csp
from caracole.viewer.book import BookSong, build_songbook, songbook_csp
from caracole.viewer.instruments import BARITONE, PIANO, UKULELE, UKULELE_LOW_G, chord_shapes
from caracole.viewer.theory import parse_chord

from helpers.browser import CHROMIUM_MARKS, Browser
from helpers.viewer_pages import viewer as open_viewer, written
from test_viewer_necks import STORAGE, follow, reload, reopen, served, to_song

pytestmark = CHROMIUM_MARKS

DESKTOP = {"width": 1280, "height": 800, "mobile": False}
SONG = ("{title: Instruments}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n"
        "[C]made [Am]up [F]words [G7]here\n[Dm7]and [Bb]some [C/E]more [E]there\n")
SONG_CHORDS = ["C", "Am", "F", "G7", "Dm7", "Bb", "C/E", "E"]
# Em shapes with capo 2: the song sounds in F#m.
CAPO_2 = ("{title: Capo}\n{artist: Synthetic}\n{key: Em}\n{capo: 2}\n{comment: Verse}\n"
          "[Em]la la [C]la la [G]la la [D]la\n")
IN_E = "{title: In E}\n{artist: Synthetic}\n{key: E}\n{comment: Verse}\n[E]la la [A]la la [B7]la la [E]la\n"
NAMES = ["Guitar", "Ukulele", "Ukulele, low G", "Baritone ukulele", "Piano", "Harmonica", "Flute", "Recorder"]

# Each box of ``boxes``, read back: [frets as the position writes them, base fret].
BOXES = """((boxes) => [...boxes].map((svg) => {
  const marks = [...svg.querySelectorAll('[data-string]')].sort((a, b) => a.dataset.string - b.dataset.string);
  return [marks.map((m) => m.dataset.fret).join(''), Number(svg.dataset.base)];
}))"""
# Each keyboard of ``boards``, read back: [bass, ...the right hand's notes], and its keys' count.
BOARDS = """((boards) => [...boards].map((svg) => {
  const lit = [...svg.querySelectorAll('[data-role]')];
  return { bass: lit.filter((k) => k.dataset.role === 'bass').map((k) => Number(k.dataset.note)),
           on: lit.filter((k) => k.dataset.role === 'on').map((k) => Number(k.dataset.note)).sort((a, b) => a - b),
           keys: svg.querySelectorAll('rect').length };
}))"""
# The Instrument menu's options, each with whether it is the one chosen, and its title: what it says of that one.
SETTINGS = """(() => ({
  chips: [...document.querySelectorAll('#insts option')].map((o) => [o.textContent, o.selected ? 'true' : 'false']),
  row: !document.getElementById('inst-row').hidden, hint: document.getElementById('insts').title,
  capo: !document.getElementById('capo-row').hidden, easy: !document.getElementById('easy-row').hidden,
  facts: document.getElementById('facts').textContent, hash: location.hash,
}))()"""


def choose(b: Browser, name: str) -> None:
    """The instrument ``name`` chosen in the settings' Instrument menu, as a hand picks it."""
    b.js(f"""(() => {{ if (document.getElementById('panel').hidden) document.getElementById('more').click();
      const menu = document.getElementById('insts');
      menu.value = [...menu.options].find((o) => o.textContent === {json.dumps(name)}).value;
      menu.dispatchEvent(new Event('change', {{bubbles: true}})); }})()""")


def strip(b: Browser) -> list:
    if b.js("document.getElementById('strip').hidden"):
        b.js("document.getElementById('strip-toggle').click()")  # All chord shapes, the strip's switch in ⋯
    return b.js("[...document.querySelectorAll('#strip button')].map((x) => x.lastChild.textContent)")


def chords(b: Browser) -> list[str]:
    return b.js("[...document.querySelectorAll('#sheet .c')].map((c) => c.textContent)")


def first_shapes(inst, names, shift=0):
    return [chord_shapes(inst, parse_chord(name), shift)[0] for name in names]


# --- the setting -------------------------------------------------------------------------------------------


def test_the_settings_offer_each_instrument_the_viewer_draws_the_guitar_first(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.click("#more")
        seen = b.js(SETTINGS)
        choose(b, "Ukulele")
        uke = b.js(SETTINGS)
    assert seen["row"] and seen["chips"] == [[n, "true" if n == "Guitar" else "false"] for n in NAMES]
    assert seen["hint"] == "Standard tuning, E A D G B E." and seen["hash"] == ""
    assert [c[1] for c in uke["chips"]] == ["false", "true"] + ["false"] * 6
    assert uke["hint"] == "G C E A, the G string high." and uke["hash"] == "#inst=ukulele"


@pytest.mark.parametrize("inst", [UKULELE, UKULELE_LOW_G, BARITONE], ids=lambda i: i.id)
def test_a_ukulele_draws_each_chord_as_a_four_string_box_as_python_shapes_it(tmp_path, inst):
    with open_viewer(tmp_path, written(tmp_path, SONG) + "#t=3") as b:
        choose(b, inst.name)
        names = strip(b)
        drawn = b.js(BOXES + "(document.querySelectorAll('#strip svg'))")
        strings = b.js("[...document.querySelectorAll('#strip svg')].map((s) => s.querySelectorAll('[data-string]').length)")
        b.click('#sheet .c[data-c="1"]')
        assert b.wait("!document.getElementById('card').hidden")
        card = [b.js(BOXES + "(document.querySelectorAll('#diagram svg'))")[0], b.js("document.querySelector('#diagram .count').textContent")]
        b.click("#next")
        second = b.js(BOXES + "(document.querySelectorAll('#diagram svg'))")[0]
    assert names == ["Eb", "Cm", "Ab", "Bb7", "Fm7", "Db", "Eb/G", "G"]
    expected = first_shapes(inst, SONG_CHORDS, 3)
    assert drawn == [[p[0], p[2]] for p in expected] and set(strings) == {4}
    cm = chord_shapes(inst, parse_chord("Am"), 3)
    assert card == [[cm[0][0], cm[0][2]], f"1 of {len(cm)}"] and second == [cm[1][0], cm[1][2]]


def test_a_chord_the_ukulele_has_no_shape_for_says_what_it_shows(tmp_path):
    cho = "{title: T}\n{artist: A}\n{key: C}\n{comment: Verse}\n[C5]la [C/E]la [G9]la\n"
    with open_viewer(tmp_path, written(tmp_path, cho)) as b:
        choose(b, "Ukulele")
        notes = []
        for i in range(3):
            b.click(f'#sheet .c[data-c="{i}"]')
            assert b.wait(f"document.getElementById('card-name').textContent === {json.dumps(['C5', 'C/E', 'G9'][i])}")
            notes.append(b.js("document.getElementById('shape-note').textContent"))
    assert notes == ["No shape for this chord here: C is the closest.", "Shown without its bass, E.",
                     "No shape for this chord here: G7 is the closest."]


def test_the_piano_draws_each_chord_as_a_keyboard_its_notes_lit_and_its_bass_marked(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        choose(b, "Piano")
        strip(b)
        drawn = b.js(BOARDS + "(document.querySelectorAll('#strip svg'))")
        b.click('#sheet .c[data-c="6"]')  # C/E
        assert b.wait("document.getElementById('card-name').textContent === 'C/E'")
        card = [b.js(BOARDS + "(document.querySelectorAll('#diagram svg'))")[0],
                b.js("document.querySelector('#diagram .count').textContent"),
                b.js("document.getElementById('shape-note').textContent")]
        b.click("#next")
        second = [b.js(BOARDS + "(document.querySelectorAll('#diagram svg'))")[0],
                  b.js("document.getElementById('shape-note').textContent")]
        wide = b.js("[document.getElementById('diagram').getBoundingClientRect().width, document.documentElement.scrollWidth]")
    for board, position in zip(drawn, first_shapes(PIANO, SONG_CHORDS), strict=True):
        assert board["bass"] == [position[0]] and board["on"] == position[1:]
    c_e = chord_shapes(PIANO, parse_chord("C/E"))
    assert card[0]["bass"] == [52] and card[0]["on"] == c_e[0][1:] and card[1] == "1 of 3"
    assert card[2] == "Root position; E in the bass, left hand."
    assert second[0]["on"] == c_e[1][1:] and second[1] == "1st inversion; E in the bass, left hand."
    assert card[0]["keys"] == second[0]["keys"]  # one keyboard for all three: the card keeps its width
    assert wide[0] >= 170 and wide[1] == 390


# --- the capo, folded in on the piano -------------------------------------------------------------------------


def test_on_the_piano_the_capo_is_folded_in_and_the_guitar_gets_it_back(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, CAPO_2)) as b:
        guitar = [b.js(SETTINGS)["facts"], chords(b), b.js("document.querySelector('#key-now').textContent")]
        b.click("#more")
        b.click("#capo-up")  # capo 3, by hand: D#m shapes
        moved = [b.js(SETTINGS)["facts"], chords(b)]
        choose(b, "Piano")
        piano = [b.js(SETTINGS), chords(b), b.js("document.querySelector('#key-now').textContent")]
        b.click('#sheet .c[data-c="0"]')
        assert b.wait("!document.getElementById('card').hidden")
        card = [b.js("document.getElementById('card-name').textContent"), b.js("document.getElementById('shape-note').textContent")]
        choose(b, "Guitar")
        back = [b.js(SETTINGS)["facts"], chords(b)]
    assert guitar[0] == "Em shapes · capo 2 · sounds F#m · key from the sheet" and guitar[1] == ["Em", "C", "G", "D"]
    assert moved[0].startswith("D#m shapes · capo 3 · sounds F#m") and moved[1] == ["D#m", "B", "F#", "C#"]
    # As it sounds: the key it sounds in, no capo said, the chords named as they sound, no Capo row.
    assert piano[0]["facts"] == "Key F#m from the sheet" and not piano[0]["capo"]
    assert piano[1] == ["F#m", "D", "A", "E"] and piano[2].startswith("F#m") and "capo" not in piano[2]
    assert card == ["F#m", "Root position; F# in the bass, left hand."]
    assert back[0].startswith("D#m shapes · capo 3 · sounds F#m") and back[1] == ["D#m", "B", "F#", "C#"]


def test_a_ukulele_keeps_the_capo(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, CAPO_2)) as b:
        choose(b, "Ukulele")
        seen = [b.js(SETTINGS), chords(b)]
    assert seen[0]["capo"] and seen[0]["facts"].startswith("Em shapes · capo 2 · sounds F#m")
    assert seen[1] == ["Em", "C", "G", "D"]


# --- easy keys -----------------------------------------------------------------------------------------------

EASY = """(() => ({ shown: !document.getElementById('easy-row').hidden,
  chips: [...document.querySelectorAll('#easy .chip')].map((c) => [c.firstChild.textContent, c.querySelector('small').textContent,
    c.getAttribute('aria-pressed')]) }))()"""


def test_easy_keys_move_the_song_to_a_key_the_ukulele_plays_well(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_E)) as b:
        b.click("#more")
        guitar = b.js(EASY)
        choose(b, "Ukulele")
        uke = b.js(EASY)
        b.js("[...document.querySelectorAll('#easy .chip')][0].click()")  # F, a semitone up
        moved = [b.js(EASY), chords(b), b.js("location.hash")]
        choose(b, "Baritone ukulele")
        baritone = b.js(EASY)
        choose(b, "Piano")
        piano = b.js(EASY)
    assert not guitar["shown"] and not piano["shown"]  # the guitar's capo suggests its shapes
    # Nearest E first: F a semitone up, G three up, C four down, Bb six down.
    assert uke["shown"] and uke["chips"] == [["F", "+1", "false"], ["G", "+3", "false"], ["C", "−4", "false"],
                                             ["Bb", "−6", "false"]]
    assert moved[0]["chips"][0] == ["F", "now", "true"] and moved[1] == ["F", "Bb", "C7", "F"]
    assert "t=1" in moved[2]
    assert baritone["chips"][0] == ["F", "now", "true"]  # F is easy on the baritone too


def test_the_guitars_capo_hints_are_the_guitars_alone(tmp_path):
    in_bb = "{title: In Bb}\n{artist: Synthetic}\n{key: Bb}\n{comment: Verse}\n[Bb]la la [Eb]la la [F]la\n"
    hints = "[...document.querySelectorAll('#capo .chip')].map((c) => c.textContent)"
    with open_viewer(tmp_path, written(tmp_path, in_bb)) as b:
        b.click("#more")
        guitar = b.js(hints)
        choose(b, "Ukulele")
        uke = [b.js(hints), b.js(EASY)]
    assert guitar == ["Capo 1A shapes", "Capo 3G shapes"]
    assert uke[0] == [] and uke[1]["chips"][0] == ["Bb", "now", "true"]  # Bb is easy on a ukulele


@pytest.mark.parametrize("name", ["Harmonica", "Flute", "Recorder"])
def test_an_instrument_with_no_capo_is_offered_no_capo_hint(tmp_path, name):
    # None takes a capo: no Capo row, and no capo to press that would move the guitar's while you play it.
    in_bb = "{title: In Bb}\n{artist: Synthetic}\n{key: Bb}\n{comment: Verse}\n[Bb]la la [Eb]la la [F]la\n"
    with open_viewer(tmp_path, written(tmp_path, in_bb)) as b:
        choose(b, name)
        seen = [b.js(SETTINGS), b.js("!document.getElementById('capo-opts').hidden"),
                b.js("[...document.querySelectorAll('#capo .chip')].map((c) => c.textContent)")]
    assert not seen[0]["capo"] and seen[1] is False and seen[2] == []


# --- the rail of necks --------------------------------------------------------------------------------------

RAIL = """(() => ({ shown: !document.getElementById('necks').hidden,
  strings: [...document.querySelectorAll('#necks svg.neck')].map((s) => s.querySelectorAll('.nk-string').length),
  button: !document.getElementById('necks-toggle').hidden,
  tabs: [...document.querySelectorAll('#necks [role=tab]')].map((t) => t.textContent),
  names: [...document.querySelectorAll('#necks .nk-name')].map((n) => n.textContent) }))()"""


def test_the_rail_of_necks_has_four_strings_on_a_ukulele_and_the_guitars_on_the_piano(tmp_path):
    # Its Guitar tab is the instrument's necks, named for it; on one with no neck (the piano), the guitar's.
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        guitar = b.js(RAIL)
        choose(b, "Ukulele")
        uke = b.js(RAIL)
        dots = b.js("[...document.querySelectorAll('#necks .nk')][0].querySelectorAll('circle[data-p]').length")
        choose(b, "Piano")
        piano = b.js(RAIL)
        padding = b.js("getComputedStyle(document.body).paddingLeft")
    assert guitar["shown"] and set(guitar["strings"]) == {6} and guitar["button"]
    assert guitar["tabs"] == ["Guitar", "Harmonica"]
    assert uke["shown"] and set(uke["strings"]) == {4} and len(uke["strings"]) == 1 + 8  # the key's, then a chord's
    assert uke["tabs"] == ["Ukulele", "Harmonica"]
    shapes = chord_shapes(UKULELE, parse_chord("C"))
    assert dots == sum(sum(1 for f in p[0] if f != "x") for p in shapes)
    assert piano["shown"] and piano["button"] and padding != "0px"
    assert piano["tabs"] == ["Guitar", "Harmonica"] and piano["strings"] == guitar["strings"]
    assert piano["names"] == guitar["names"]  # the guitar's chords, as its capo names them



# Each of the rail's tabs, and whether it lies inside its segmented control, its edge and its track.
TABS_FIT = """(() => { const control = document.querySelector('#necks .ov-tabs'), box = control.getBoundingClientRect();
  return [...control.children].map((t) => { const r = t.getBoundingClientRect();
    return [t.textContent, r.left >= box.left + 1 && r.right <= box.right - 1]; }); })()"""


@pytest.mark.parametrize(("name", "tab"), [("Guitar", "Guitar"), ("Ukulele", "Ukulele"), ("Ukulele, low G", "Ukulele"),
                                         ("Baritone ukulele", "Baritone"), ("Piano", "Guitar")])
def test_the_rails_tabs_name_the_neck_in_short_and_fit_at_1200_px(tmp_path, name, tab):
    # At the narrowest the rail shows, a long name ("Baritone ukulele") would overflow the control: the tab names the
    # neck in short, as the instrument's own tab name (instruments.py ``tab``).
    with open_viewer(tmp_path, written(tmp_path, SONG), width=1200, height=800, mobile=False) as b:
        choose(b, name)
        found = b.js(TABS_FIT)
    assert found == [[tab, True], ["Harmonica", True]]


# --- kept, carried, in the address -----------------------------------------------------------------------------


def test_the_instrument_is_kept_for_every_sheet_and_in_the_address(tmp_path):
    url, other = written(tmp_path, SONG), written(tmp_path, IN_E, name="Other")
    with open_viewer(tmp_path, url) as b:
        choose(b, "Ukulele")
        reload(b)
        reloaded = b.js(SETTINGS)
        reopen(b, other)
        elsewhere = [b.js(SETTINGS), b.js("[...document.querySelectorAll('#strip svg')].length")]
        choose(b, "Guitar")
        reopen(b, url)
        guitar = b.js(SETTINGS)
        reopen(b, url + "#inst=piano")
        asked = b.js(SETTINGS)
        reopen(b, url + "#inst=kazoo")
        unknown = b.js(SETTINGS)
    assert reloaded["chips"][1][1] == "true" and reloaded["hash"] == "#inst=ukulele"
    assert elsewhere[0]["chips"][1][1] == "true" and elsewhere[0]["hash"] == "#inst=ukulele"
    assert guitar["chips"][0][1] == "true" and guitar["hash"] == ""
    assert asked["chips"][4][1] == "true" and asked["facts"] == "Key C from the sheet"
    assert unknown["chips"][0][1] == "true" and unknown["hash"] == ""  # one the viewer doesn't draw: the guitar


def test_reset_everything_keeps_the_players_instrument(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        choose(b, "Piano")
        b.click("#t-up")
        b.click("#reset-all")
        seen = [b.js(SETTINGS), chords(b)]
    assert seen[0]["chips"][4][1] == "true" and seen[0]["hash"] == "#inst=piano" and seen[1][0] == "C"


def test_served_in_its_sandbox_the_address_keeps_the_instrument(tmp_path):
    sheet = "/Artist/Title/sheet.html"
    with served({sheet: (build_viewer(SONG), viewer_csp)}) as site, open_viewer(tmp_path, site + sheet) as b:
        sandboxed = b.js(STORAGE)
        choose(b, "Baritone ukulele")
        reload(b)
        seen = b.js(SETTINGS)
    assert sandboxed is False
    assert seen["chips"][3][1] == "true" and seen["hash"] == "#inst=baritone"


def songbook(songs: list[BookSong]) -> str:
    return build_songbook("Campfire", songs)


def test_a_served_songbook_carries_the_instrument_from_song_to_song(tmp_path):
    songs = [BookSong("One", "Synthetic", cho=SONG, id="aaaa"), BookSong("Two", "Synthetic", cho=IN_E, id="bbbb")]
    page = "/_songbooks/Campfire/songbook.html"
    with served({page: (songbook(songs), songbook_csp)}) as site, \
            open_viewer(tmp_path, site + page + "#song-1") as b:
        choose(b, "Piano")
        follow(b, "document.querySelector('#song-1 a[rel=next]').click()")
        two = [b.js(SETTINGS), b.js(BOARDS + "(document.querySelectorAll('#strip svg'))")]
    assert two[0]["chips"][4][1] == "true" and two[0]["hash"] == "#song-2=&inst=piano"
    assert two[0]["facts"].startswith("Key E")


def test_a_songbook_song_on_its_own_instrument_opens_on_it(tmp_path):
    # A set list played on another instrument than the player's: the song starts there, as it starts in its version.
    songs = [BookSong("One", "Synthetic", cho=SONG, id="aaaa"),
             BookSong("Two", "Synthetic", cho=IN_E, id="bbbb", start="t=0&inst=ukulele")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(songbook(songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-1") as b:
        choose(b, "Piano")
        to_song(b, 2)
        two = b.js(SETTINGS)
        easy = b.js(EASY)  # the songbook's one block of easy keys, for a song with a key
        choose(b, "Guitar")  # on this song, by hand
        reload(b)
        again = b.js(SETTINGS)
        to_song(b, 1)
        one = b.js(SETTINGS)
    assert two["chips"][1][1] == "true" and "inst=ukulele" in two["hash"]
    assert easy["shown"] and easy["chips"][0] == ["F", "+1", "false"]
    assert again["chips"][0][1] == "true" and "inst=guitar" in again["hash"]
    assert one["chips"][0][1] == "true"  # the player's own, now the guitar


def test_a_songbook_song_set_on_the_guitar_opens_on_it_whatever_the_players_instrument(tmp_path):
    # songbook.py names the guitar in the start of a song set on it (instrument = "guitar")
    songs = [BookSong("One", "Synthetic", cho=SONG, id="aaaa"),
             BookSong("Two", "Synthetic", cho=IN_E, id="bbbb", start="t=0&inst=guitar"),
             BookSong("Three", "Synthetic", cho=SONG, id="cccc")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(songbook(songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-1") as b:
        choose(b, "Piano")
        to_song(b, 2)
        two = b.js(SETTINGS)
        to_song(b, 3)
        three = b.js(SETTINGS)
    assert two["chips"][0][1] == "true"
    assert three["chips"][4][1] == "true"  # the player's own again


THREE = "{title: Three}\n{artist: Synthetic}\n{key: G}\n{comment: Verse}\n[G]la la [C]la la [D]la\n"


@pytest.mark.parametrize("where", ["file", "served"])
def test_the_song_after_one_on_its_own_instrument_is_on_the_players_again(tmp_path, where):
    # A set list's song on the ukulele, the player on the piano: the songs after it, and back before it, are the
    # player's, from a file (the browser keeps the piano) and in caracole serve's sandbox (the address alone does).
    songs = [BookSong("One", "Synthetic", cho=SONG, id="aaaa"),
             BookSong("Two", "Synthetic", cho=IN_E, id="bbbb", start="t=0&inst=ukulele"),
             BookSong("Three", "Synthetic", cho=THREE, id="cccc")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(songbook(songs), encoding="utf-8")
    pages = {"/_songbooks/Campfire/songbook.html": (songbook(songs), songbook_csp)}
    with served(pages) if where == "served" else nullcontext() as site:
        page = site + "/_songbooks/Campfire/songbook.html" if site else path.as_uri()
        with open_viewer(tmp_path, page + "#song-1") as b:
            choose(b, "Piano")
            to_song(b, 2)
            two = b.js(SETTINGS)
            to_song(b, 3)
            three = b.js(SETTINGS)
            to_song(b, 1)
            one = b.js(SETTINGS)
            to_song(b, 2)
            choose(b, "Baritone ukulele")  # the player's now, chosen on the song by hand
            b.click("#reset-all")  # the song's own again
            reset = b.js(SETTINGS)
            to_song(b, 3)
            after = b.js(SETTINGS)
    assert two["chips"][1][1] == "true"  # its own: the ukulele
    assert three["chips"][4][1] == "true" and "inst=piano" in three["hash"]
    assert one["chips"][4][1] == "true" and "inst=piano" in one["hash"]
    assert reset["chips"][1][1] == "true" and after["chips"][3][1] == "true" and "inst=baritone" in after["hash"]


# --- a phone's width ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_no_sideways_scroll_at_390_px_with_the_strip_and_a_card_open(tmp_path, name):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        choose(b, name)
        b.js("document.querySelector('#panel [data-close]').click()")
        strip(b)
        b.click('#sheet .c[data-c="3"]')
        assert b.wait("!document.getElementById('card').hidden")
        seen = b.js("""[document.documentElement.scrollWidth, innerWidth,
          document.querySelector('#diagram svg').getBoundingClientRect().right,
          document.getElementById('alts').getBoundingClientRect().left,
          document.getElementById('card').getBoundingClientRect().right]""")
    assert seen[0] == seen[1] == 390
    assert seen[2] < seen[3] < seen[4]  # the shape whole, beside the chords to play instead


# --- an instrument another script draws --------------------------------------------------------------------------

KAZOO = instruments.Instrument("kazoo", "Kazoo", "kazoo", capo=False, voice="guitar", about="Hum along.")
REGISTER = """window.caracoleInstruments.register('kazoo', {
  header: (view) => 'Kazoo in ' + view.key + ', ' + view.chords.length + ' chords',
  diagram: (view, chord, bare) => { const p = document.createElement('p'); p.className = 'kz' + (bare ? ' bare' : '');
    p.textContent = 'hum ' + view.names[chord.root]; return p; },
  panel: (view, box) => { const p = box.appendChild(document.createElement('p')); p.className = 'kz-panel';
    p.textContent = view.instrument.name + ' at ' + view.shift; },
  notes: (view, chord) => [60 + chord.root],
})"""


def test_an_instrument_a_script_registers_is_offered_then_drawn_by_it(tmp_path, monkeypatch):
    monkeypatch.setattr(instruments, "INSTRUMENTS", (*instruments.INSTRUMENTS, KAZOO))
    with open_viewer(tmp_path, written(tmp_path, CAPO_2) + "#inst=kazoo") as b:
        before = b.js(SETTINGS)
        b.js(REGISTER)
        after = b.js(SETTINGS)
        choose(b, "Kazoo")
        on = [b.js(SETTINGS), b.js("[...document.querySelectorAll('#strip .kz')].map((p) => p.textContent)"),
              b.js("document.querySelector('#inst-panel .kz-panel').textContent")]
        strip(b)
        bare = b.js("[...document.querySelectorAll('#strip .kz.bare')].map((p) => p.textContent)")
        b.click('#sheet .c[data-c="0"]')
        assert b.wait("!document.getElementById('card').hidden")
        card = b.js("document.querySelector('#diagram .kz').textContent")
        heard = b.wait("document.documentElement.dataset.heard === '369.99'")  # F#4: its notes, as it says
    assert [c[0] for c in before["chips"]] == NAMES and before["chips"][0][1] == "true"  # not drawn yet: the guitar
    assert [c[0] for c in after["chips"]] == [*NAMES, "Kazoo"]
    assert on[0]["facts"] == "Key F#m from the sheetKazoo in F#m, 4 chords"  # its line, under the key line
    assert on[0]["hint"] == "Hum along." and not on[0]["capo"] and on[2] == "Kazoo at 2"
    assert bare == ["hum F#", "hum D", "hum A", "hum E"] and card == "hum F#" and heard
