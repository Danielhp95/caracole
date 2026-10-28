"""The overlay on a phone (overlay.js): below 1200 px, where there is no rail, the bar's neck button slides it up from
the bar as a sheet over about half the screen, the song readable and scrollable above it; the sheet's handle takes it
to the whole screen and back, and ✕ or Escape closes it, the focus back on the button. It holds what the rail holds
(test_viewer_overlay.py): the Guitar and Harmonica tabs in the page's order, the circle, the key on the harp chosen,
each chord's card and the slim bar, and on a harmonica tab's page the page's harp both ways. A dialog that is not
modal: the song stays within reach. Each page opens with it closed. From 1200 px nothing of it shows."""

from __future__ import annotations

import json

import pytest
from helpers.browser import CHROMIUM_MARKS
from helpers.targets import small_targets
from helpers.viewer_pages import drag, key, rest, tap_at, viewer as open_viewer, written

from caracole.viewer.book import BookSong, build_songbook

from test_viewer_harptab_browser import bar_harp, opened, with_sheet
from test_viewer_necks import contrast, to_song
from test_viewer_overlay import IN_C, SHAPES, SLID_IN, SONG, seen

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

LONG = SONG + "".join(f"{{comment: Verse {n}}}\n[Am]Made up [E7]words to [G]sing a[D]long\n"
                      f"[F]more made [C]up words [Dm]here and [E]there\n" for n in range(2, 9))

# The sheet as it shows: open or not, at half the screen or the whole, its box, what it says to assistive tech, the
# bar's neck button, the sheet's own controls, and where the focus is.
SHEET = """(() => {
  const q = (s) => document.querySelector(s), aside = q('#necks'), button = q('#necks-open');
  const box = aside.getBoundingClientRect(), bar = q('#bar').getBoundingClientRect(), handle = q('#necks .ov-handle');
  const active = document.activeElement;
  return {open: !aside.hidden, at: aside.dataset.sheet || null, role: aside.getAttribute('role'),
          named: aside.getAttribute('aria-label'), modal: aside.getAttribute('aria-modal'),
          visible: !aside.hidden && getComputedStyle(aside).visibility === 'visible',
          top: Math.round(box.top), bottom: Math.round(box.bottom), height: Math.round(box.height),
          left: Math.round(box.left), right: Math.round(box.right), barTop: Math.round(bar.top), barShown: !q('#bar').hidden,
          screen: innerHeight, client: document.documentElement.clientWidth,
          sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          inside: aside.scrollWidth <= aside.clientWidth,
          button: Boolean(button && button.getClientRects().length), expanded: button && button.getAttribute('aria-expanded'),
          buttonNamed: button && button.getAttribute('aria-label'), controls: button && button.getAttribute('aria-controls'),
          handle: handle && handle.getAttribute('aria-pressed'), handleNamed: handle && handle.getAttribute('aria-label'),
          close: q('#necks .ov-close') && q('#necks .ov-close').getAttribute('aria-label'),
          hide: Boolean(q('#necks .nk-hide')), rail: Boolean(q('#necks-toggle') && q('#necks-toggle').getClientRects().length),
          focus: active && (active.id === 'necks-open' ? active.id : active.getAttribute('aria-label') || active.textContent)};
})()"""
# Open at half the screen, or the whole, and there: neither sliding up nor growing (viewer.css) any more.
SETTLED = "document.getElementById('necks').getAnimations().length === 0"
HALF = "document.getElementById('necks').dataset.sheet === 'half' && " + SETTLED
FULL = "document.getElementById('necks').dataset.sheet === 'full' && " + SETTLED
CLOSED = "document.getElementById('necks').hidden && !document.getElementById('necks').dataset.sheet"


def sheet(b) -> dict:
    return b.js(SHEET)


def middle(b, selector: str) -> tuple[float, float]:
    box = b.js(f"""(() => {{ const e = document.querySelector({json.dumps(selector)});
      if (!e || !e.getClientRects().length) return null;
      const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")
    assert box, f"nothing shown is {selector}"
    return box[0], box[1]


def touch(b, selector: str) -> None:
    """A finger on the middle of the element ``selector`` finds, lifted at once."""
    tap_at(b, *middle(b, selector))


def open_sheet(b) -> None:
    touch(b, "#necks-open")
    assert b.wait(HALF)


def to_harmonica(b) -> None:
    touch(b, "#necks [role=tab][data-tab=harmonica]")
    assert b.wait("document.querySelector('#necks .ov-pane').dataset.tab === 'harmonica'")


def harp(b, name: str) -> None:
    """The harp ``name`` ("D") tapped on the circle, with a finger."""
    touch(b, f"#necks .hw-harp[aria-label^='{name} harp,'] .hw-dot")
    assert b.wait(f"document.querySelector('#necks .hw-name').textContent === '{name} harp'")


# --- opening it, its handle, closing it --------------------------------------------------------------------------


def test_the_bars_neck_opens_the_overlay_as_a_sheet_over_half_the_screen(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG)) as b:
        closed = sheet(b)
        open_sheet(b)
        half = sheet(b)
        shown = seen(b)
        drag(b, 300, start=300)  # a finger on the song above it: the song scrolls, the sheet stays
        rest(b)
        scrolled = [b.js("scrollY"), sheet(b)]
    assert not closed["open"] and closed["button"] and closed["expanded"] == "false" and closed["controls"] == "necks"
    assert closed["buttonNamed"] == "Necks and harps" and not closed["rail"]
    assert half["open"] and half["visible"] and half["at"] == "half" and half["expanded"] == "true"
    # A dialog, not a modal one: the song stays within reach
    assert half["role"] == "dialog" and half["named"] == "Necks and harps" and half["modal"] is None
    assert half["barShown"] and half["bottom"] == half["barTop"]  # on the bar, which stays
    assert 0.45 * half["screen"] <= half["height"] <= 0.6 * half["screen"]  # about half the screen
    assert (half["left"], half["right"]) == (0, half["client"]) and not half["sideways"] and half["inside"]
    assert half["close"] == "Close" and not half["hide"]  # ✕, not the rail's Hide
    assert half["handle"] == "false" and half["handleNamed"] == "Whole screen"
    assert shown["tabs"] == [["Guitar", "true"], ["Harmonica", "false"]] and shown["necks"] == SHAPES
    assert half["focus"] == "Guitar"  # into it, on the tab shown
    assert scrolled[0] > 100 and scrolled[1]["at"] == "half"


def test_its_handle_takes_it_to_the_whole_screen_and_back(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG)) as b:
        open_sheet(b)
        touch(b, "#necks .ov-grip")
        assert b.wait(FULL)
        full = sheet(b)
        # The handle reaches across the sheet's head, between its tabs and ✕
        x, y = b.js("""(() => { const tabs = document.querySelector('#necks .ov-tabs').getBoundingClientRect();
          const close = document.querySelector('#necks .ov-close').getBoundingClientRect();
          return [(tabs.right + close.left) / 2, tabs.top + tabs.height / 2]; })()""")
        gap = b.js(f"document.elementFromPoint({x}, {y}).closest('.ov-handle') !== null")
        tap_at(b, x, y)
        assert b.wait(HALF)
        half = sheet(b)
        b.js("document.querySelector('#necks .ov-handle').focus()")
        b.press("Enter")  # a toggle button, from the keyboard too
        assert b.wait(FULL)
        keyed = sheet(b)
    assert full["open"] and full["handle"] == "true" and full["top"] <= 40 and full["bottom"] == full["barTop"]
    assert full["focus"] != "necks-open"  # the focus stays in the sheet
    assert gap and half["handle"] == "false" and half["top"] > 0.35 * half["screen"]
    assert keyed["handle"] == "true" and keyed["focus"] == "Whole screen"


def test_close_and_escape_close_it_and_the_focus_goes_back_to_the_button(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.js("document.getElementById('necks-open').focus()")
        b.press("Enter")
        assert b.wait(HALF)
        opened_by_key = sheet(b)
        b.click("#necks .ov-close")
        assert b.wait(CLOSED)
        closed = sheet(b)
        open_sheet(b)
        b.press("Escape")
        assert b.wait(CLOSED)
        escaped = sheet(b)
        open_sheet(b)
        touch(b, "#necks-open")  # the button again: closed
        assert b.wait(CLOSED)
        again = sheet(b)
    assert opened_by_key["focus"] == "Guitar" and opened_by_key["expanded"] == "true"
    assert closed["focus"] == "necks-open" and closed["expanded"] == "false" and closed["role"] is None
    assert escaped["focus"] == "necks-open" and escaped["expanded"] == "false"
    assert again["focus"] == "necks-open"


def test_each_page_opens_with_the_sheet_closed_and_it_opens_at_half(tmp_path):
    url = written(tmp_path, SONG)
    with open_viewer(tmp_path, url) as b:
        open_sheet(b)
        touch(b, "#necks .ov-grip")
        assert b.wait(FULL)
        touch(b, "#necks .ov-close")
        assert b.wait(CLOSED)
        open_sheet(b)  # half again
        reopened = sheet(b)
        b.js("window.before = true")
        b.send("Page.reload")
        assert b.wait("!window.before && document.documentElement.dataset.ready === '1'")
        reloaded = sheet(b)
    assert reopened["at"] == "half" and not reloaded["open"] and reloaded["expanded"] == "false"


# --- what it holds -----------------------------------------------------------------------------------------------


def test_on_a_sheet_guitar_comes_first_and_a_harp_tapped_on_the_circle_is_the_one_the_cards_are_on(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        open_sheet(b)
        to_harmonica(b)
        first = seen(b)
        harp(b, "D")
        d = seen(b)
        b.js("document.getElementById('necks').scrollTop = 600")
        assert b.wait("document.querySelector('#necks .ov-slim').classList.contains('on')")
        assert b.wait(SLID_IN)
        slim = seen(b)
        touch(b, "#necks .ov-change")
        assert b.wait("document.getElementById('necks').scrollTop === 0")
        top = seen(b)
    assert first["tabs"] == [["Guitar", "false"], ["Harmonica", "true"]] and first["centre"] == "Bm"
    assert first["chosen"] == ["A harp, 3rd position, dorian"] and first["plays"] == "Plays Bm, A and E."
    assert d["name"] == "D harp" and d["card"] == "Bm on a D harp4th position, aeolian"
    assert [c["name"] for c in d["chords"]] == ["Bm", "F#7", "A", "E", "G", "D", "Em", "F#"]
    assert slim["slim"]["on"] and slim["slim"]["text"] == "D harp · 4th, aeolian" and -1 <= slim["slim"]["below"] <= 1
    assert not top["slim"]["on"]


def test_on_a_harmonica_tabs_page_harmonica_comes_first_and_the_bars_harp_is_the_circles_both_ways(tmp_path):
    with opened(tmp_path, with_sheet(tmp_path)) as b:
        closed = sheet(b)
        open_sheet(b)
        first = [seen(b), sheet(b)]
        harp(b, "A")
        tapped = [bar_harp(b), seen(b)]
        touch(b, "#h-up")
        assert b.wait("document.querySelector('#necks .hw-name').textContent === 'Bb harp'")
        stepped = [bar_harp(b), seen(b)]
        touch(b, "#necks [role=tab][data-tab=guitar]")
        assert b.wait("document.querySelector('#necks .ov-pane').dataset.tab === 'guitar'")
        guitar = seen(b)
        b.press("Escape")
        assert b.wait(CLOSED)
        escaped = sheet(b)
    assert closed["button"] and not closed["open"] and not closed["rail"]
    assert first[0]["tabs"] == [["Harmonica", "true"], ["Guitar", "false"]] and first[0]["name"] == "D harp"
    assert first[0]["tag"] == "the tab's" and first[1]["focus"] == "Harmonica" and first[1]["role"] == "dialog"
    assert tapped[0] == "A harp" and tapped[1]["chosen"] == ["A harp, 3rd position, dorian"]
    assert stepped[0] == "Bb harp" and stepped[1]["chosen"] == ["Bb harp, 8th position"]
    assert guitar["necks"] == SHAPES
    assert escaped["focus"] == "necks-open" and escaped["expanded"] == "false"


def test_a_songbook_song_has_the_sheet_and_the_next_song_opens_with_it_closed(tmp_path):
    page = tmp_path / "_songbooks" / "Book" / "songbook.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_songbook("Book", [BookSong("Synthetic Song", "Placeholder Band", cho=SONG, key="Am",
                                                     key_source="tab"),
                                            BookSong("In C", "Placeholder Band", cho=IN_C, key="C")]), encoding="utf-8")
    with open_viewer(tmp_path, page.as_uri() + "#song-1") as b:
        open_sheet(b)
        first = seen(b)
        to_harmonica(b)
        harmonicas = seen(b)
        b.js("document.querySelector('#necks .ov-close').focus()")
        key(b, "ArrowRight", 39)  # the songbook's arrows go nowhere from the sheet
        stayed = b.js("location.hash")
        to_song(b, 2)
        second = sheet(b)
        open_sheet(b)
        next_one = seen(b)
    assert first["tabs"][0] == ["Guitar", "true"] and first["necks"] == SHAPES
    assert harmonicas["centre"] == "Bm" and harmonicas["name"] == "A harp"
    assert stayed.startswith("#song-1")
    assert second["button"] and not second["open"]
    assert next_one["pane"] == "guitar" and next_one["necks"] == ["C", "G", "Am", "F"]


# --- beside the song -----------------------------------------------------------------------------------------------


def test_with_the_half_sheet_open_the_song_scrolls_by_itself_above_it_and_ends_above_it(tmp_path):
    ends = """(() => { const lines = [...document.querySelectorAll('#sheet .l')], last = lines[lines.length - 1];
      return last.getBoundingClientRect().bottom <= document.getElementById('necks').getBoundingClientRect().top; })()"""
    with open_viewer(tmp_path, written(tmp_path, LONG)) as b:
        open_sheet(b)
        touch(b, "#necks .ov-grip")
        assert b.wait(FULL)
        touch(b, "#scroll")  # ▶ keeps the sheet, at half, for the song to show above it
        assert b.wait("!document.getElementById('pill').hidden")
        running = [sheet(b), b.js("""(() => { const p = document.getElementById('pill').getBoundingClientRect();
          return p.bottom <= document.getElementById('necks').getBoundingClientRect().top && p.top >= 0; })()""")]
        b.js("document.getElementById('pill-end').click()")
        b.js("scrollTo(0, document.documentElement.scrollHeight)")
        assert b.wait(ends)
    assert running[0]["at"] == "half" and running[0]["barShown"] and running[0]["bottom"] == running[0]["barTop"]
    assert running[1]  # the pill rides above the sheet


def test_the_settings_open_over_the_sheet_and_it_comes_back_once_they_close(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        open_sheet(b)
        touch(b, "#more")
        assert b.wait("!document.getElementById('panel').hidden")
        under = sheet(b)
        b.press("Escape")
        assert b.wait("document.getElementById('panel').hidden")
        back = sheet(b)
    assert under["open"] and not under["visible"]  # the one opened last shows, as the settings and the card do
    assert back["visible"] and back["at"] == "half"


# --- the bar and the sheet at a phone's widths --------------------------------------------------------------------

BAR = """(() => {
  const bar = document.getElementById('bar').getBoundingClientRect();
  const shown = [...document.querySelectorAll('#bar button')].filter((e) => e.getClientRects().length);
  const boxes = shown.map((e) => e.getBoundingClientRect());
  return {ids: shown.map((e) => e.id), smallest: Math.min(...boxes.map((r) => Math.min(r.width, r.height))),
          row: boxes.every((r, i) => r.left >= bar.left && r.right <= bar.right && r.top >= bar.top
            && r.bottom <= bar.bottom && (i === 0 || r.left >= boxes[i - 1].right - 0.5))};
})()"""
SMALL = small_targets(":not(#necks *):not(#bar *)")  # the sheet's controls and the bar's


@pytest.mark.parametrize("width", [320, 360, 390])
def test_nothing_overflows_and_every_target_is_a_thumbs_on_a_sheet(tmp_path, width):
    with open_viewer(tmp_path, written(tmp_path, SONG), width=width, height=740) as b:
        bar = b.js(BAR)
        open_sheet(b)
        guitar = [sheet(b), b.js(SMALL)]
        to_harmonica(b)
        harmonica = [sheet(b), b.js(SMALL)]
        touch(b, "#necks .ov-grip")
        assert b.wait(FULL)
        full = sheet(b)
    # On a phone the neck after the key, in the guitar's place: the strip is ⋯'s All chord shapes
    assert bar["ids"] == ["t-down", "t-up", "necks-open", "size", "scroll", "more"], (width, bar)
    assert bar["smallest"] >= 44 and bar["row"], (width, bar)
    for now, small in (guitar, harmonica):
        assert not now["sideways"] and now["inside"] and small == [], (width, now, small)
    assert not full["sideways"] and full["inside"]


@pytest.mark.parametrize("width", [320, 360, 390])
def test_nothing_overflows_on_a_harmonica_tabs_page(tmp_path, width):
    with opened(tmp_path, with_sheet(tmp_path), width=width, height=740) as b:
        bar = b.js(BAR)
        name = b.js("""(() => { const k = document.getElementById('harp-name'), text = document.createRange();
          text.selectNodeContents(k); return text.getBoundingClientRect().width <= k.getBoundingClientRect().width; })()""")
        for _ in range(6):  # from the D harp up to the Ab, the longest name
            touch(b, "#h-up")
        assert b.wait("document.getElementById('harp-name').textContent === 'Ab harp'")
        longest = b.js("""(() => { const k = document.getElementById('harp-name'), text = document.createRange();
          text.selectNodeContents(k); return [k.textContent,
            text.getBoundingClientRect().width <= k.getBoundingClientRect().width]; })()""")
        open_sheet(b)
        harmonica = [sheet(b), b.js(SMALL)]
        touch(b, "#necks [role=tab][data-tab=guitar]")
        assert b.wait("document.querySelector('#necks .ov-pane').dataset.tab === 'guitar'")
        guitar = [sheet(b), b.js(SMALL)]
    assert bar["ids"] == ["h-down", "h-up", "necks-open", "notes", "size", "scroll"], (width, bar)
    assert bar["smallest"] >= 44 and bar["row"], (width, bar)
    assert name and longest == ["Ab harp", True], width  # the harp's name whole, a little smaller where it must be
    for now, small in (harmonica, guitar):
        assert not now["sideways"] and now["inside"] and small == [], (width, now, small)


def test_the_sheet_in_dark_mode_keeps_its_contrast(tmp_path):
    colours = """(() => { const aside = document.getElementById('necks'), css = (el) => getComputedStyle(el);
      return {background: css(aside).backgroundColor, grip: css(aside.querySelector('.ov-grip')).backgroundColor,
              close: css(aside.querySelector('.ov-close')).color,
              text: [...aside.querySelectorAll('.hw-name, .hw-pos, .hw-plays, .hk-name, .hc-run')].map((el) => css(el).color)};
    })()"""
    schemes = {}
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        open_sheet(b)
        to_harmonica(b)
        for scheme in ("light", "dark"):
            b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
            assert b.wait(f"matchMedia('(prefers-color-scheme: {scheme})').matches")
            schemes[scheme] = b.js(colours)
    for scheme, now in schemes.items():
        assert contrast(now["grip"], now["background"]) >= 3, scheme  # the handle, told apart from the sheet
        assert contrast(now["close"], now["background"]) >= 4.5, scheme
        assert now["text"] and min(contrast(c, now["background"]) for c in now["text"]) >= 4.5, scheme


# --- from 1200 px: the rail, as it was -----------------------------------------------------------------------------


def test_from_1200_px_there_is_no_sheet_and_no_neck_button(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), width=1400, height=1000, mobile=False) as b:
        wide = sheet(b)
    assert not wide["button"] and wide["rail"] and wide["open"] and wide["at"] is None
    assert wide["role"] is None and wide["named"] == "Chord necks" and wide["hide"] and wide["close"] is None


def test_the_window_widened_past_1200_px_with_the_sheet_open_gives_its_place_to_the_rail(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), width=1100, height=900, mobile=False) as b:
        b.click("#necks-open")
        assert b.wait(HALF)
        b.click("#necks [role=tab][data-tab=harmonica]")
        assert b.wait("document.querySelector('#necks .ov-pane').dataset.tab === 'harmonica'")
        narrow = sheet(b)
        b.send("Emulation.setDeviceMetricsOverride", width=1400, height=900, deviceScaleFactor=1, mobile=False)
        assert b.wait("!document.getElementById('necks').dataset.sheet && !document.getElementById('necks').hidden")
        wide = [sheet(b), seen(b)]
        b.send("Emulation.setDeviceMetricsOverride", width=1100, height=900, deviceScaleFactor=1, mobile=False)
        assert b.wait("document.getElementById('necks').hidden")
        back = sheet(b)
    assert narrow["at"] == "half" and narrow["focus"] == "Harmonica"
    # The rail, on the tab the sheet was on, the focus still on it
    assert wide[0]["role"] is None and wide[0]["named"] == "Chord necks" and wide[0]["hide"]
    assert wide[1]["pane"] == "harmonica" and wide[0]["focus"] == "Harmonica"
    assert not back["open"] and back["expanded"] == "false" and back["button"]  # it never opens by itself
