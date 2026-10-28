"""harmonica-N.html in Chromium (viewer/harptab_page.py, harptab.js): each hole drawn over its syllable, wrapping
between words on a phone and never parting a hole from its syllable; a hole tapped heard at its note on the harp
chosen, a line's ▶ playing it hole by hole, lighting each, and stopping; the harp's −/+ and Notes; dark mode; a tab
caracole can't read, as its text. The sound is recorded as test_viewer_sound.py records it (``SCHEDULE``)."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser

from caracole.viewer.harptab_page import build_harmonica_viewer
from caracole.viewer.page import HERE

from test_viewer_sound import FADE, SCHEDULE, silent_after, strum_timers, strums, tapped

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium

TABS = Path(__file__).parent / "fixtures" / "harptabs" / "tabs"
PHONE = {"width": 390, "height": 844, "mobile": True}
# A D harp's hole 8 blown (F#6), drawn (E6), its 7 blown (D6), its -6 (B5); an Eb harp's 8 blown (G6).
F_SHARP_6, E_6, D_6, G_6 = "1479.98", "1318.51", "1174.66", "1567.98"


def tab(stem: str) -> str:
    return (TABS / f"{stem}.txt").read_text(encoding="utf-8")


def written(tmp_path: Path, text: str, **given) -> str:
    """The page of the tab ``text``, written where render.py writes it; its address."""
    html = build_harmonica_viewer(text, **({"title": "Synthetic Song", "artist": "Placeholder Band",
                                            "tab_file": "harmonica-1.txt", "page_key": "D"} | given))
    path = tmp_path / "Placeholder Band" / "Synthetic Song" / "harmonica-1.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    (path.parent / "harmonica-1.txt").write_text(text, encoding="utf-8")
    return path.as_uri()


@contextmanager
def opened(tmp_path: Path, address: str, *, schedule: bool = False, **size):
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), **(PHONE | size)) as b:
        if schedule:
            b.send("Page.addScriptToEvaluateOnNewDocument", source=SCHEDULE)
        b.open(address)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        html = Path(address.removeprefix("file://").split("#")[0].replace("%20", " ")).read_text("utf-8")
        strum = (HERE / "strum.js").read_text(encoding="utf-8")
        first = html[:html.index(strum)].count("\n") + 1
        b.strum_lines = range(first, first + strum.count("\n") + 1)
        yield b


# Each hole's group (.hg) and the syllable under it (.y) of each column (.s), as laid out.
COLUMNS = """[...document.querySelectorAll('#sheet .s')].map((s) => {
  const h = s.querySelector('.hg').getBoundingClientRect(), y = s.querySelector('.y').getBoundingClientRect();
  return [h.left, h.bottom, y.left, y.top, y.bottom];
})"""
WIDE = "[document.documentElement.scrollWidth, window.innerWidth]"
HOLES = "[...document.querySelectorAll('#sheet .h[data-i]')].slice(0, %d).map((h) => h.textContent)"


@pytest.mark.parametrize("size", [PHONE, {"width": 1280, "height": 900, "mobile": False}], ids=["390", "1280"])
def test_each_hole_is_drawn_over_its_syllable_and_a_phone_wraps_between_words(tmp_path, size):
    with opened(tmp_path, written(tmp_path, tab("588_hotel-california")), **size) as b:
        columns = b.js(COLUMNS)
        lines = b.js("[...document.querySelectorAll('#sheet p.hl')].map((p) => new Set([...p.querySelectorAll('.y')]"
                     ".map((y) => Math.round(y.getBoundingClientRect().top))).size)")
        wide = b.js(WIDE)
    assert len(columns) > 150
    for hole_left, hole_bottom, word_left, word_top, word_bottom in columns:
        assert abs(hole_left - word_left) < 0.5  # the same column
        assert word_top - 0.5 <= hole_bottom <= word_top + 2  # right over it, never on another line
    if size["width"] == 390:
        assert max(lines) >= 2  # a sung line wrapped, between its words
    else:
        assert max(lines) == 1
    assert wide[0] <= wide[1]  # no sideways scroll


@pytest.mark.parametrize("stem", ["3489_wonderwall", "1882_juke", "10228_whammer-jammer", "1786_simple-man",
                                  "29910_knockin-on-heavens-door"])
def test_no_sideways_scroll_on_a_phone(tmp_path, stem):
    with opened(tmp_path, written(tmp_path, tab(stem))) as b:
        assert b.js(WIDE)[0] <= 390


def test_a_hole_tapped_sounds_its_note_on_the_harp_chosen_and_the_harps_plus_moves_it(tmp_path):
    with opened(tmp_path, written(tmp_path, tab("588_hotel-california"))) as b:
        assert b.js("document.getElementById('harp-name').textContent") == "D harp"
        assert b.js("document.getElementById('harp-why').textContent") == "harptabs.com's key"
        b.click('#sheet .h[data-i="0"]')  # 8 blown
        assert b.wait("document.documentElement.dataset.heard === '%s'" % F_SHARP_6)
        lit = b.js("document.querySelector('#sheet .h[data-i=\"0\"]').classList.contains('on')")
        b.click("#h-up")
        assert b.js("document.getElementById('harp-name').textContent") == "Eb harp"
        assert b.js("location.hash") == "#harp=Eb"
        b.click('#sheet .h[data-i="0"]')
        assert b.wait("document.documentElement.dataset.heard === '%s'" % G_6)
        b.click('#sheet .h[data-i="3"]')  # 8 drawn, on the Eb harp: F6
        assert b.wait("document.documentElement.dataset.heard === '1396.91'")
    assert lit is True


def test_notes_shows_each_holes_note_on_the_harp_chosen(tmp_path):
    with opened(tmp_path, written(tmp_path, tab("588_hotel-california"))) as b:
        assert b.js(HOLES % 4) == ["8", "8", "8", "−8"]
        b.click("#notes")
        on_d = b.js(HOLES % 4)
        pressed = b.js("document.getElementById('notes').getAttribute('aria-pressed')")
        said = b.js("document.querySelector('#sheet .h[data-i=\"3\"]').getAttribute('aria-label')")
        b.click("#h-down")
        on_db = b.js(HOLES % 4)
        address = b.js("Object.fromEntries(new URLSearchParams(location.hash.slice(1)))")
        b.click("#notes")
        back = b.js(HOLES % 4)
    assert on_d == ["F#6", "F#6", "F#6", "E6"] and pressed == "true"
    assert said == "draw 8, E6"
    assert on_db == ["F6", "F6", "F6", "Eb6"]
    assert address == {"harp": "Db", "notes": "1"}
    assert back == ["8", "8", "8", "−8"]


def test_the_address_keeps_the_harp_notes_and_text_size(tmp_path):
    with opened(tmp_path, written(tmp_path, tab("588_hotel-california")) + "#harp=A&notes=1&fs=22") as b:
        found = b.js("[document.getElementById('harp-name').textContent, document.querySelector('#sheet .h').textContent,"
                     " getComputedStyle(document.documentElement).getPropertyValue('--fs')]")
        b.click("#size")
        b.click("#bigger")
        address = b.js("location.hash")
    assert found == ["A harp", "C#6", "22px"]
    assert address == "#harp=A&notes=1&fs=24"


# Each hole lit, in the order it lights (a MutationObserver on the holes' class).
LIGHTS = """window.lit = [];
new MutationObserver((changes) => changes.forEach((c) => {
  if (c.target.classList.contains('on')) window.lit.push(Number(c.target.dataset.i));
})).observe(document.getElementById('sheet'), { subtree: true, attributes: true, attributeFilter: ['class'] });"""


def test_a_lines_play_sounds_it_hole_by_hole_lighting_each_then_ends(tmp_path):
    text = "8 -8 7 -6\nla la la la\n"
    with opened(tmp_path, written(tmp_path, text), schedule=True) as b:
        b.js(LIGHTS)
        b.click('#sheet .rp[data-row="0"]')
        assert b.js("document.querySelector('.rp').getAttribute('aria-pressed')") == "true"
        assert b.wait("document.querySelector('.rp').getAttribute('aria-pressed') === 'false'", 10)
        found = strums(b)
        lit, on = b.js("window.lit"), b.js("document.querySelectorAll('#sheet .h.on').length")
        assert b.wait("log.context.state === 'suspended'", 8)  # silent, it lets the device's audio sleep
        timers = strum_timers(b)
    assert [s["heard"] for s in found] == [F_SHARP_6, E_6, D_6, "987.77"]
    beat = 60 / 132
    assert all(abs((b2["when"] - a["when"]) - beat) < 1e-6 or b2["when"] - a["when"] > beat
               for a, b2 in zip(found, found[1:]))
    assert lit == [0, 1, 2, 3] and on == 0 and timers == []


def test_a_line_playing_stops_when_its_play_is_pressed_again_and_nothing_of_it_sounds_after(tmp_path):
    with opened(tmp_path, written(tmp_path, tab("588_hotel-california")), schedule=True) as b:
        b.js(LIGHTS)
        b.click('#sheet .rp[data-row="0"]')
        assert b.wait("window.lit.length >= 3", 10)
        at = tapped(b, "(() => { const t = log.context.currentTime; document.querySelector('.rp').click(); return t; })()")
        state = b.js("[document.querySelector('.rp').getAttribute('aria-pressed'), "
                     "document.querySelectorAll('#sheet .h.on').length]")
        assert b.wait("log.context.currentTime > %f" % (at + FADE + 0.1), 5)
        lit = b.js("window.lit")
        silent_after(b, at)
        assert b.wait("log.context.state === 'suspended'", 8)
        timers = strum_timers(b)
    assert state == ["false", 0]
    assert lit == list(range(len(lit))) and 3 <= len(lit) < 12  # in its order, and no further once stopped
    assert timers == []


def test_a_hole_tapped_stops_the_line_playing(tmp_path):
    with opened(tmp_path, written(tmp_path, tab("588_hotel-california")), schedule=True) as b:
        b.click('#sheet .rp[data-row="1"]')
        assert b.wait("document.querySelector('.rp[data-row=\"1\"]').getAttribute('aria-pressed') === 'true'")
        b.click('#sheet .h[data-i="0"]')
        assert b.wait("document.documentElement.dataset.heard === '%s'" % F_SHARP_6)
        assert b.js("document.querySelector('.rp[data-row=\"1\"]').getAttribute('aria-pressed')") == "false"


@pytest.mark.parametrize(("scheme", "blow", "draw", "background"), [
    ("light", "rgb(180, 68, 30)", "rgb(27, 95, 193)", "rgb(247, 246, 243)"),
    ("dark", "rgb(240, 137, 92)", "rgb(138, 184, 255)", "rgb(19, 19, 18)"),
])
def test_blow_and_draw_in_the_viewers_colours_light_and_dark(tmp_path, scheme, blow, draw, background):
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), **PHONE) as b:
        b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
        b.open(written(tmp_path, tab("588_hotel-california")))
        assert b.wait("document.documentElement.dataset.ready === '1'")
        found = b.js("[getComputedStyle(document.querySelector('#sheet .h .b')).color,"
                     " getComputedStyle(document.querySelector('#sheet .h .d')).color,"
                     " getComputedStyle(document.body).backgroundColor]")
    assert found == [blow, draw, background]


def test_a_tab_caracole_cant_read_is_its_text_with_aa_and_scrolling_alone(tmp_path):
    with opened(tmp_path, written(tmp_path, tab("29910_knockin-on-heavens-door"))) as b:
        found = b.js("""[document.querySelector('#sheet pre.tab').textContent.split('\\n')[0],
          document.querySelectorAll('#sheet .h').length, document.getElementById('bar').hidden,
          Boolean(document.getElementById('h-up')), Boolean(document.getElementById('notes')),
          getComputedStyle(document.getElementById('scroll')).display !== 'none',
          document.documentElement.scrollWidth]""")
        b.click("#size")
        b.click("#bigger")
        size = b.js("getComputedStyle(document.documentElement).getPropertyValue('--fs')")
    assert found == ["ARMONICA C", 0, False, False, False, True, 390]
    assert size == "20px"


def test_scrolling_by_itself_counts_down_then_scrolls_and_stops(tmp_path):
    with opened(tmp_path, written(tmp_path, tab("3489_wonderwall"))) as b:
        b.click("#scroll")
        assert b.js("document.getElementById('pill').dataset.state") == "counting"
        b.click("#go")  # pressed again: at once
        assert b.wait("window.scrollY > 20", 10)
        b.click("#pill-end")
        assert b.js("[document.getElementById('pill').hidden, document.getElementById('bar').classList.contains('away')]") \
            == [True, False]


# --- the overlay, from 1200 px: Harmonica first, its harp the page's, then Guitar (overlay.js) ------------------

WIDE_SCREEN = {"width": 1400, "height": 1000, "mobile": False}


def with_sheet(tmp_path, **given) -> str:
    """The page of a tab whose words name a D harp, beside a sheet in Am shapes with the capo on 2 (it sounds Bm)."""
    from test_viewer_harptab_page import TAB_D, a_song

    return written(tmp_path, TAB_D, **({"cho": a_song(), "key": "Am", "key_source": "tab"} | given))


def bar_harp(b) -> str:
    return b.js("document.getElementById('harp-name').textContent")


def test_on_a_wide_screen_the_overlay_opens_on_harmonica_on_the_pages_harp(tmp_path):
    from test_viewer_overlay import SHAPES, seen

    with opened(tmp_path, with_sheet(tmp_path), **WIDE_SCREEN) as b:
        first = seen(b)
        bar = bar_harp(b)
        named = b.js("document.getElementById('necks').getAttribute('aria-label')")
        rail = b.js("[document.getElementById('necks').getBoundingClientRect().width, "
                    "document.getElementById('sheet').getBoundingClientRect().left, "
                    "document.getElementById('bar').getBoundingClientRect().left]")
        b.click("#necks [role=tab][data-tab=guitar]")
        assert b.wait("document.querySelector('#necks .ov-pane').dataset.tab === 'guitar'")
        guitar = seen(b)
        keyneck = b.js("document.querySelector('#necks .kn-name').textContent")
    assert first["tabs"] == [["Harmonica", "true"], ["Guitar", "false"]] and first["pane"] == "harmonica"
    assert first["centre"] == "Bm" and first["chosen"] == ["D harp, 4th position, aeolian"]
    assert (first["name"], first["tag"]) == ("D harp", "the tab's") and bar == "D harp"
    assert first["plays"] == "Plays A, D and Em; E as Em." and first["card"] == "Bm on a D harp4th position, aeolian"
    assert named == "Chord necks" and rail[0] == 345 and rail[1] >= 345 + 16 and rail[2] == 345
    assert guitar["necks"] == SHAPES and keyneck == "Am scale"  # the sheet's chords as written, on the guitar


def test_a_harp_tapped_on_the_circle_is_the_one_the_page_plays_and_its_bar_moves_the_circle(tmp_path):
    from test_viewer_overlay import harp, seen

    with opened(tmp_path, with_sheet(tmp_path), **WIDE_SCREEN) as b:
        b.click("#notes")
        before = b.js(HOLES % 3)
        harp(b, "A")
        tapped_on = [bar_harp(b), b.js(HOLES % 3), b.js("location.hash"), seen(b)]
        b.click("#h-up")
        assert b.wait("document.querySelector('#necks .hw-name').textContent === 'Bb harp'")
        stepped = [seen(b), bar_harp(b)]
        b.click('#sheet .h[data-i="0"]')  # a hole tapped: the page's harp is the circle's
        heard = b.wait("document.documentElement.dataset.heard !== undefined")
    assert before == ["D5", "F#5", "A5"]  # the tab's 4 5 6 blown, named on the D harp
    assert tapped_on[0] == "A harp" and tapped_on[1] != before and "harp=A" in tapped_on[2]
    assert tapped_on[3]["chosen"] == ["A harp, 3rd position, dorian"] and tapped_on[3]["tag"] is None
    assert stepped[0]["chosen"] == ["Bb harp, 8th position"] and stepped[1] == "Bb harp" and heard


def test_a_song_with_no_sheet_has_no_guitar_tab_and_shows_the_pages_harp(tmp_path):
    from test_viewer_harptab_page import TAB_D
    from test_viewer_overlay import seen

    with opened(tmp_path, written(tmp_path, TAB_D), **WIDE_SCREEN) as b:
        first = seen(b)
        title = b.js("document.querySelector('#necks .nk-title').textContent")
        b.click("#h-up")
        assert b.wait("document.querySelector('#necks .hk-name').textContent === 'Eb harp'")
        up = seen(b)
    assert first["tabs"] == [] and title == "Harmonica" and first["pane"] == "harmonica"
    assert first["none"].startswith("With no chord sheet") and first["centre"] is None and first["chords"] == []
    assert first["card"] == "D harp" and [n for n, _ in first["blow"]] == "D F# A D F# A D F# A D".split()
    assert {role for _, role in first["blow"] + first["draw"]} == {"plain"}
    assert [n for n, _ in up["blow"]][:3] == ["Eb", "G", "Bb"]


def test_the_rail_hidden_is_the_screens_choice_here_too(tmp_path):
    from test_viewer_overlay import seen

    with opened(tmp_path, with_sheet(tmp_path) + "#necks=0", **WIDE_SCREEN) as b:
        hidden = [b.js("document.getElementById('necks').hidden"), b.js("document.body.style.paddingLeft"),
                  b.js("document.getElementById('necks-toggle').getAttribute('aria-pressed')")]
        b.click("#necks-toggle")
        shown = [seen(b), b.js("location.hash")]
        b.click("#necks .nk-hide")
        again = [b.js("document.getElementById('necks').hidden"), b.js("location.hash"),
                 b.js("document.activeElement.id")]
    assert hidden == [True, "", "false"]
    assert shown[0]["shown"] and shown[0]["pane"] == "harmonica" and shown[1] == ""
    assert again == [True, "#necks=0", "necks-toggle"]


def test_on_a_phone_the_overlay_waits_for_the_bars_neck(tmp_path):
    with opened(tmp_path, with_sheet(tmp_path)) as b:
        found = b.js("[document.getElementById('necks').hidden, document.getElementById('necks-toggle').hidden, "
                     "document.getElementById('necks-open').hidden, document.documentElement.scrollWidth]")
    assert found == [True, True, False, 390]  # its sheet's tests are test_viewer_overlay_sheet.py's


def test_served_with_no_storage_the_screens_choices_go_to_the_tabs_page_and_back(tmp_path):
    # In caracole serve's sandbox the address alone keeps them: the Harmonica row's link to the tab's page takes on the
    # rail hidden, the pinyin, the Chinese characters and the instrument, as a version's ‹ › do, and ‹ Chord sheet
    # brings them back.
    from caracole.viewer import build_viewer, viewer_csp
    from test_viewer_harptab_page import TAB_D, a_song
    from test_viewer_necks import served

    sheet = build_viewer(a_song(), key="Am", key_source="tab", harmonica=[
        {"name": "harmonica-1.txt", "href": "harmonica-1.txt", "page": "harmonica-1.html", "harp": 2}])
    harp = build_harmonica_viewer(TAB_D, title="Synthetic Song", artist="Placeholder Band",
                                  tab_file="harmonica-1.txt", cho=a_song(), key="Am", key_source="tab",
                                  back="sheet.html")
    folder = "/Placeholder%20Band/Synthetic%20Song/"
    ready = "!window.before && document.documentElement.dataset.ready === '1'"
    with served({folder + "sheet.html": (sheet, viewer_csp), folder + "harmonica-1.html": (harp, viewer_csp)}) as site, \
            Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), **WIDE_SCREEN) as b:
        b.open(site + folder + "sheet.html#py=1&trad=1")
        assert b.wait("document.documentElement.dataset.ready === '1'")
        b.click("#necks .nk-hide")
        b.js("(() => { document.getElementById('more').click(); const m = document.getElementById('insts');"
             " m.value = 'harmonica'; m.dispatchEvent(new Event('change')); })()")
        link = b.js("document.querySelector('.wd-tabs a.link').getAttribute('href')")
        b.js("window.before = true; document.querySelector('.wd-tabs a.link').click()")
        assert b.wait(ready)
        there = [b.js("location.pathname.endsWith('harmonica-1.html')"), b.js("document.getElementById('necks').hidden")]
        back = b.js("document.querySelector('a.back').getAttribute('href')")
        b.js("window.before = true; document.querySelector('a.back').click()")
        assert b.wait(ready)
        home = [b.js("location.pathname.endsWith('sheet.html')"), b.js("document.getElementById('necks').hidden"),
                b.js("document.getElementById('insts').value"), b.js("location.hash")]
    assert link == "harmonica-1.html#necks=0&py=1&trad=1&inst=harmonica"
    assert there == [True, True]
    assert back == "sheet.html#necks=0&py=1&trad=1&inst=harmonica"
    assert home[:3] == [True, True, "harmonica"]
    assert all(part in home[3] for part in ("necks=0", "py=1", "trad=1", "inst=harmonica"))


def test_the_window_narrowed_with_the_focus_in_the_rail_puts_it_on_the_bar(tmp_path):
    with opened(tmp_path, with_sheet(tmp_path), **WIDE_SCREEN) as b:
        b.js("document.querySelector('#necks .hw-harp[aria-checked=true]').focus()")
        b.send("Emulation.setDeviceMetricsOverride", width=1100, height=1000, deviceScaleFactor=1, mobile=False)
        assert b.wait("document.getElementById('necks').hidden")
        focus = b.js("document.activeElement.id")
    assert focus == "h-down"  # the bar's first control, where the rail's button was


def test_the_pages_harp_diagrams_have_draw_above_the_holes_and_blow_below(tmp_path):
    from test_viewer_harptab_page import TAB_D
    from test_viewer_overlay import ROWS, draw_above_blow

    with opened(tmp_path, with_sheet(tmp_path), **WIDE_SCREEN) as b:
        charts = b.js(ROWS)
    with opened(tmp_path, written(tmp_path, TAB_D), **WIDE_SCREEN) as b:  # no sheet: the page's harp's notes alone
        plain = b.js(ROWS)
    draw_above_blow(charts)
    assert len(plain) == 1
    draw_above_blow(plain)
