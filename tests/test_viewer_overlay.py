"""The overlay (overlay.js): from 1200 px, the rail on the left with two tabs, Guitar and Harmonica, on a chord sheet
(viewer.js) and a songbook's song. Guitar is the rail of necks (test_viewer_necks.py's tests); Harmonica, the circle
of fifths that picks the harp, the key on that harp, each chord's holes on it, and the slim bar once the circle has
scrolled out of the rail. A harmonica tab's page has it too (test_viewer_harptab_browser.py); narrower, the phone's
sheet holds it (test_viewer_overlay_sheet.py)."""

from __future__ import annotations

import json
import re

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import in_chromium
from helpers.targets import small_targets
from helpers.viewer_pages import click_at, key, viewer as open_viewer, written
from test_viewer_necks import contrast, reload, reopen, to_song

SHAPES = ["Am", "E7", "G", "D", "F", "C", "Dm", "E"]
SOUNDS = ["Bm", "F#7", "A", "E", "G", "D", "Em", "F#"]  # the capo on 2
SONG = ("{title: Synthetic Song}\n{artist: Placeholder Band}\n{key: Am}\n{capo: 2}\n{comment: Verse}\n"
        "[Am]Made up [E7]words to [G]sing a[D]long\n[F]more made [C]up words [Dm]here and [E]there\n")
IN_C = "{title: In C}\n{artist: Placeholder Band}\n{key: C}\n{comment: Verse}\n[C]Made up [G]words to [Am]sing a[F]long\n"
DESKTOP = {"width": 1400, "height": 1000, "mobile": False}

# What the overlay shows: its tabs, the tab shown, and on Harmonica, the circle, the harp beside it, the key card,
# each chord's card and the slim bar.
OVERLAY = """(() => {
  const rail = document.getElementById('necks'), q = (s) => rail.querySelector(s), all = (s) => [...rail.querySelectorAll(s)];
  const text = (s) => (q(s) ? q(s).textContent : null);
  const notes = (card, row) => [...card.querySelectorAll('.hx[data-row="' + row + '"]')].map((g) => [g.dataset.note, g.dataset.role]);
  const slim = q('.ov-slim'), head = q('.nk-head');
  return {
    shown: !rail.hidden,
    tabs: all('[role=tab]').map((t) => [t.textContent, t.getAttribute('aria-selected')]),
    pane: q('.ov-pane') && q('.ov-pane').dataset.tab,
    necks: all('.nk-name').map((n) => n.textContent),
    centre: text('.hw-key'),
    chosen: all('.hw-harp[aria-checked=true]').map((g) => g.getAttribute('aria-label')),
    shaded: all('.hw-harp.good .hw-kn').map((t) => t.textContent),
    ordinals: all('.hw-ord').map((t) => t.textContent),
    ring: all('.hw-harp .hw-kn').map((t) => t.textContent),
    name: text('.hw-name'), position: text('.hw-pos'), tag: text('.hw-tag'), plays: text('.hw-plays'),
    hint: text('.hw-hint'), none: text('.hw-none'),
    card: text('.hk-name'), chips: all('.hk-switch .chip').map((c) => [c.textContent, c.getAttribute('aria-pressed')]),
    blow: q('.hk') ? notes(q('.hk'), 'blow') : [], draw: q('.hk') ? notes(q('.hk'), 'draw') : [],
    bends: q('.hk') ? notes(q('.hk'), 'bend') : [],
    legend: text('.hk-legend'), outside: text('.hk-out'),
    chords: all('.hc').map((c) => ({name: c.querySelector('.hc-name').firstChild.textContent,
      shape: c.querySelector('.hc-name small') ? c.querySelector('.hc-name small').textContent : '',
      run: c.querySelector('.hc-run').textContent, blow: notes(c, 'blow'), draw: notes(c, 'draw')})),
    slim: slim ? {on: slim.classList.contains('on'), text: slim.querySelector('.ov-harp').textContent,
      below: Math.round(slim.getBoundingClientRect().top - head.getBoundingClientRect().bottom)} : null,
    top: rail.scrollTop, focus: document.activeElement && (document.activeElement.getAttribute('aria-label')
      || document.activeElement.textContent),
  };
})()"""


# The slim bar slid all the way in, under the head (its slide takes a moment).
SLID_IN = """Math.abs(document.querySelector('#necks .ov-slim').getBoundingClientRect().top
  - document.querySelector('#necks .nk-head').getBoundingClientRect().bottom) < 1"""


def seen(b) -> dict:
    return b.js(OVERLAY)


def harmonica(b) -> None:
    b.click("#necks [role=tab][data-tab=harmonica]")
    assert b.wait("document.querySelector('#necks .ov-pane').dataset.tab === 'harmonica'")


def harp(b, name: str) -> None:
    """The harp ``name`` ("D") tapped on the circle."""
    b.click(f"#necks .hw-harp[aria-label^='{name} harp,']")
    assert b.wait(f"document.querySelector('#necks .hw-name').textContent === '{name} harp'")


# --- the tabs -----------------------------------------------------------------------------------------------------


@in_chromium
def test_a_sheet_opens_on_guitar_and_harmonica_is_a_tab_away_and_not_kept(tmp_path):
    url = written(tmp_path, SONG)
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        first = seen(b)
        harmonica(b)
        shown = seen(b)
        b.click("#necks [role=tab][data-tab=guitar]")
        assert b.wait("document.querySelector('#necks .ov-pane').dataset.tab === 'guitar'")
        back = seen(b)
        harmonica(b)
        reload(b)
        reloaded = seen(b)
        harmonica(b)
        reopen(b, written(tmp_path, IN_C, name="Other"))
        other = seen(b)
    assert first["shown"] and first["tabs"] == [["Guitar", "true"], ["Harmonica", "false"]]
    assert first["pane"] == "guitar" and first["necks"] == SHAPES and first["name"] is None
    assert shown["tabs"] == [["Guitar", "false"], ["Harmonica", "true"]] and shown["pane"] == "harmonica"
    assert shown["necks"] == [] and shown["centre"] == "Bm" and shown["focus"] == "Harmonica"
    assert back["pane"] == "guitar" and back["necks"] == SHAPES
    # Each page opens on its own tab: neither a reload nor another sheet keeps Harmonica.
    assert reloaded["pane"] == "guitar" and other["pane"] == "guitar" and other["necks"] == ["C", "G", "Am", "F"]


@in_chromium
def test_the_arrows_go_from_tab_to_tab_and_round_the_circle(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        b.js("document.querySelector('#necks [role=tab][data-tab=guitar]').focus()")
        key(b, "ArrowRight", 39)
        assert b.wait("document.querySelector('#necks .ov-pane').dataset.tab === 'harmonica'")
        on_tab = seen(b)
        b.js("document.querySelector('#necks .hw-harp[aria-checked=true]').focus()")
        key(b, "ArrowRight", 39)  # the next position round the circle: the 4th
        assert b.wait("document.querySelector('#necks .hw-name').textContent === 'D harp'")
        next_one = seen(b)
        key(b, "ArrowLeft", 37)
        key(b, "ArrowLeft", 37)
        assert b.wait("document.querySelector('#necks .hw-name').textContent === 'E harp'")
        b.press("Enter")
        again = seen(b)
    assert on_tab["focus"] == "Harmonica" and on_tab["tabs"][1] == ["Harmonica", "true"]
    assert next_one["focus"] == "D harp, 4th position, aeolian" and next_one["chosen"] == [next_one["focus"]]
    assert again["chosen"] == ["E harp, 2nd position, mixolydian"] and again["focus"] == again["chosen"][0]


# --- the circle, and the harp chosen --------------------------------------------------------------------------


@in_chromium
def test_the_harmonica_tab_starts_on_the_first_harp_for_the_song_as_it_sounds(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        harmonica(b)
        now = seen(b)
    # The 12 harps round Bm, the 1st (B) at the top, a fifth down at each step (counted ↺)
    assert now["centre"] == "Bm" and now["ring"] == ["B", "E", "A", "D", "G", "C", "F", "Bb", "Eb", "Ab", "Db", "F#"]
    # harp.py's choices for B minor and these chords: the A harp (3rd), then the D (4th) and the G (5th)
    assert now["chosen"] == ["A harp, 3rd position, dorian"] and sorted(now["shaded"]) == ["D", "G"]
    assert sorted(now["ordinals"]) == ["3rd", "4th", "5th"]
    assert (now["name"], now["position"], now["tag"]) == ("A harp", "3rd position, dorian", None)
    assert now["plays"] == "Plays Bm, A and E."
    assert now["hint"] == "Tap a harp. Shaded: the ones that play the song's chords."
    assert now["card"] == "Bm on an A harp3rd position, dorian"
    assert now["chips"] == [["Scale", "true"], ["Minor pentatonic", "false"], ["Blues", "false"]]
    assert now["outside"] == "Outside B minor: G#."
    assert [c["name"] for c in now["chords"]] == SOUNDS
    assert [c["shape"] for c in now["chords"]] == [s + " shape" for s in SHAPES]
    assert now["chords"][0]["run"] == "draw 4–6" and now["chords"][2]["run"] == "blow 1–3"


@in_chromium
def test_a_harp_tapped_on_the_circle_is_the_one_the_key_and_the_chords_are_on(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        harmonica(b)
        harp(b, "D")
        d = seen(b)
        b.click("#necks .hk-switch .chip:nth-of-type(2)")
        assert b.wait("document.querySelector('#necks .hk-switch [aria-pressed=true]').textContent === 'Minor pentatonic'")
        box = seen(b)
        harp(b, "G")
        g = seen(b)
    assert d["chosen"] == ["D harp, 4th position, aeolian"] and (d["name"], d["position"]) == ("D harp", "4th position, aeolian")
    assert d["plays"] == "Plays A, D and Em; E as Em."
    assert d["card"] == "Bm on a D harp4th position, aeolian"
    assert d["outside"] == "Every note it blows or draws is in B minor."
    # The key on the D harp: B the tonic, the rest of B minor dark; its bends outward, B minor's or a faint dot
    assert d["blow"] == [[n, "in"] for n in "D F# A D F# A D F# A D".split()]
    assert d["draw"] == [["E", "in"], ["A", "in"], ["C#", "in"], ["E", "in"], ["G", "in"], ["B", "tonic"],
                         ["C#", "in"], ["E", "in"], ["G", "in"], ["B", "tonic"]]
    assert ["G", "bent-in"] in d["bends"] and ["B", "bent-tonic"] in d["bends"] and ["G#", "bent-out"] in d["bends"]
    assert d["legend"] == "B, the tonicin the scalebent"
    chords = {c["name"]: c for c in d["chords"]}
    assert chords["E"]["run"] == "draw 4–6 · as Em, the minor stand-in" and chords["E"]["shape"] == "D shape"
    assert [n for n, role in chords["E"]["draw"] if role == "run"] == ["E", "G", "B"]  # Em's holes, draw 4 to 6
    assert chords["Bm"]["run"] == "no chord here: its notes, one hole at a time"
    assert {n for n, role in chords["Bm"]["blow"] + chords["Bm"]["draw"] if role == "tone"} == {"D", "F#", "B"}
    assert chords["A"]["run"] == "draw 2–4" and chords["F#7"]["run"].startswith("no chord here")
    # The pentatonic: B D E F# A, its notes on the harp alone dark
    assert box["chips"][1] == ["Minor pentatonic", "true"] and box["legend"] == "B, the tonicin the pentatonicbent"
    assert [n for n, role in box["draw"] if role == "out"] == ["C#", "G", "C#", "G"]
    assert g["outside"] == "Outside B minor: C." and g["position"] == "5th position, phrygian"
    assert g["chips"][1] == ["Minor pentatonic", "true"]  # the chip stays chosen from harp to harp


@in_chromium
def test_a_transposition_moves_every_harp_and_a_capo_none(tmp_path):
    url = written(tmp_path, SONG)
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        harmonica(b)
        harp(b, "D")
        b.click("#t-up")
        b.click("#t-up")
        assert b.wait("document.querySelector('#necks .hw-key').textContent === 'C#m'")
        up = seen(b)
    with open_viewer(tmp_path, url + "#capo=0", **DESKTOP) as b:  # Bm shapes, no capo: the song sounds the same
        harmonica(b)
        capo = seen(b)
    # The harp chosen goes with the song: D is the 4th position in B minor, E in C# minor
    assert up["name"] == "E harp" and up["position"] == "4th position, aeolian"
    assert up["plays"] == "Plays B, E and F#m; F# as F#m." and up["chords"][0]["name"] == "C#m"
    assert up["chords"][0]["shape"] == "Bm shape"  # +2 on Am shapes: Bm shapes, capo 2
    assert capo["centre"] == "Bm" and capo["name"] == "A harp" and capo["chords"][0]["name"] == "Bm"
    assert capo["chords"][0]["shape"] == ""  # Bm shapes sound Bm: no other shape to name


# --- the slim bar -----------------------------------------------------------------------------------------------


@in_chromium
def test_the_slim_bar_names_the_harp_once_the_circle_scrolls_away_and_change_harp_goes_back(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), width=1400, height=700, mobile=False) as b:
        harmonica(b)
        harp(b, "D")
        before = seen(b)
        b.js("document.getElementById('necks').scrollTop = 500")
        assert b.wait("document.querySelector('#necks .ov-slim').classList.contains('on')")
        assert b.wait(SLID_IN)
        scrolled = seen(b)
        click_at(b, *b.js("""(() => { const r = document.querySelector('#necks .ov-change').getBoundingClientRect();
          return [r.left + r.width / 2, r.top + r.height / 2]; })()"""))  # where it is: in the head, kept at the top
        assert b.wait("document.getElementById('necks').scrollTop === 0")
        assert b.wait("!document.querySelector('#necks .ov-slim').classList.contains('on')")
        back = seen(b)
    assert before["slim"]["on"] is False and before["top"] == 0
    assert scrolled["slim"]["on"] and scrolled["slim"]["text"] == "D harp · 4th, aeolian"
    assert -1 <= scrolled["slim"]["below"] <= 1  # under the rail's head, which stays at the top
    assert back["slim"]["on"] is False and back["focus"] == "D harp, 4th position, aeolian"  # on the circle again


@in_chromium
def test_the_slim_bar_is_none_of_a_keyboards_stops_until_it_shows(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), width=1400, height=700, mobile=False) as b:
        harmonica(b)
        inert = b.js("document.querySelector('#necks .ov-slim').inert")
        b.js("document.getElementById('necks').scrollTop = 500")
        assert b.wait("document.querySelector('#necks .ov-slim').classList.contains('on')")
        live = b.js("document.querySelector('#necks .ov-slim').inert")
    assert inert is True and live is False


# --- the rail's look --------------------------------------------------------------------------------------------


@in_chromium
def test_on_a_touch_screen_the_harmonica_tab_is_easy_to_tap(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        b.send("Emulation.setTouchEmulationEnabled", enabled=True)
        harmonica(b)
        short = b.js(small_targets(":not(.necks *)"))  # the rail's controls alone, the slim bar's too
        sideways = b.js("document.getElementById('necks').scrollWidth > document.getElementById('necks').clientWidth")
    assert short == [] and not sideways


@in_chromium
def test_the_harmonica_tab_in_dark_mode_keeps_its_contrast(tmp_path):
    colours = """(() => { const rail = document.getElementById('necks'), all = (s) => [...rail.querySelectorAll(s)];
      const css = (el) => getComputedStyle(el);
      return {background: css(rail).backgroundColor,
              text: all('.hw-name, .hw-pos, .hw-plays, .hk-name, .hc-name, .hk-out, .hc-run, .hw-hint')
                .map((el) => css(el).color),
              harps: all('.hw-harp.sel .hw-dot, .hw-harp.good .hw-dot').map((c) => css(c).fill),
              notes: all('.hx.tonic .hx-note, .hx.in .hx-note, .hx.run .hx-note').map((c) => css(c).fill),
              names: all('.hx.tonic, .hx.in, .hx.run').map((g) => [css(g.querySelector('.hx-name')).fill,
                css(g.querySelector('.hx-note')).fill])}; })()"""
    schemes = {}
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        harmonica(b)
        harp(b, "D")
        for scheme in ("light", "dark"):
            b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
            assert b.wait(f"matchMedia('(prefers-color-scheme: {scheme})').matches")
            schemes[scheme] = b.js(colours)
    for scheme, now in schemes.items():
        background = now["background"]
        assert now["text"] and min(contrast(c, background) for c in now["text"]) >= 4.5, scheme
        for kind in ("harps", "notes"):  # each harp and each note told apart from the rail
            assert now[kind] and min(contrast(c, background) for c in now[kind]) >= 3, (scheme, kind)
        assert min(contrast(name, fill) for name, fill in now["names"]) >= 4.5, scheme  # a note's name on its circle


# --- a songbook's song, and a sheet with a harmonica tab --------------------------------------------------------


@in_chromium
def test_a_songbook_song_has_the_overlay_too(tmp_path):
    page = tmp_path / "_songbooks" / "Book" / "songbook.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_songbook("Book", [BookSong("Synthetic Song", "Placeholder Band", cho=IN_C, key="C"),
                                            BookSong("Synthetic Song", "Placeholder Band", cho=SONG, key="Am",
                                                     key_source="tab")]), encoding="utf-8")
    with open_viewer(tmp_path, page.as_uri() + "#song-1", **DESKTOP) as b:
        first = seen(b)
        harmonica(b)
        to_song(b, 2)
        second = seen(b)
        harmonica(b)
        harmonicas = seen(b)
    assert first["tabs"] == [["Guitar", "true"], ["Harmonica", "false"]] and first["necks"] == ["C", "G", "Am", "F"]
    assert second["pane"] == "guitar" and second["necks"] == SHAPES  # each song opens on its own
    assert harmonicas["centre"] == "Bm" and harmonicas["name"] == "A harp"


def song_data(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S).group(1))


def test_the_harps_a_songs_tabs_play_on_are_its_overlays_by_the_key_it_sounds_in():
    tabs = [{"name": "harmonica-1.txt", "href": "harmonica-1.txt", "page": "harmonica-1.html", "harp": 2},
            {"name": "harmonica-2.txt", "href": "harmonica-2.txt", "page": "harmonica-2.html"}]
    data = song_data(build_viewer(SONG, key="Am", key_source="tab", harmonica=tabs))
    assert data["harpTabs"] == [3]  # a D harp, three above B, the key Am shapes sound in with the capo on 2
    assert [t for t in data["harmonicaTabs"] if "harp" in t] == []  # the links' list keeps its own fields
    assert "harpTabs" not in song_data(build_viewer(SONG, key="Am", key_source="tab", harmonica=tabs[1:]))


@in_chromium
def test_a_sheet_with_a_harmonica_tab_starts_on_its_harp_marked_the_tabs(tmp_path):
    tabs = [{"name": "harmonica-1.txt", "href": "harmonica-1.txt", "page": "harmonica-1.html", "harp": 2}]
    page = tmp_path / "Placeholder Band" / "Synthetic Song" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer(SONG, key="Am", key_source="tab", harmonica=tabs), encoding="utf-8")
    with open_viewer(tmp_path, page.as_uri(), **DESKTOP) as b:
        harmonica(b)
        start = seen(b)
        harp(b, "A")
        other = seen(b)
    assert (start["name"], start["tag"]) == ("D harp", "the tab's") and "4th" in start["ordinals"]
    assert (other["name"], other["tag"]) == ("A harp", None)


@in_chromium
def test_below_1200_px_the_overlay_waits_for_the_bars_neck(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), width=1100, height=800, mobile=False) as b:
        assert b.js("document.getElementById('necks').hidden && !document.querySelector('#necks *')")
        assert b.js("document.getElementById('necks-open').getClientRects().length === 1")


@in_chromium
def test_the_window_narrowed_with_the_focus_in_the_rail_puts_it_on_the_bar(tmp_path):
    # The rail goes below 1200 px, and the keyboard's focus with it: it goes to the bar's first control, where the rail's
    # button was, rather than to nothing.
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        harmonica(b)
        b.js("document.querySelector('#necks .hw-harp[aria-checked=true]').focus()")
        b.send("Emulation.setDeviceMetricsOverride", width=1100, height=1000, deviceScaleFactor=1, mobile=False)
        assert b.wait("document.getElementById('necks').hidden")
        narrow = b.js("document.activeElement.id")
        b.send("Emulation.setDeviceMetricsOverride", width=1400, height=1000, deviceScaleFactor=1, mobile=False)
        assert b.wait("!document.getElementById('necks').hidden")
        wide = b.js("document.activeElement.id")
    assert narrow == "t-down" and wide == "t-down"  # the rail back does not take it
