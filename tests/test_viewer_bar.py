"""caracole.viewer: the bar at the foot of the sheet viewer (page.py ``_CONTROLS``, viewer.js).

[− key +] [necks] [neck] [Aa] [⇣] [⋯]: the song a semitone down or up, with its key in short; from 1200 px, the rail
of chord necks shown or hidden (its tests are test_viewer_necks.py's); below 1200 px, in its place, the overlay's sheet
up or down (test_viewer_overlay_sheet.py's); the text size; scrolling by itself, an arrow lit while it is on; and the
rest of the settings, where All chord shapes is the strip's one switch. Each after the key says its word under its icon
(Shapes, Text, Scroll, More). It slides away as you scroll down, and comes back when you scroll up, tap
the page or reach the end. From 1200 px it is a toolbar under the song's title instead (test_viewer_toolbar.py). The
tests that scroll and tap run in a Chromium of their own on real time (helpers/browser.py's ``Browser``).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from helpers import browser
from helpers import viewer_pages as pages
from helpers.browser import Browser, in_chromium
from helpers.viewer_pages import drag, key, rest, tap

from caracole.chordpro import to_chordpro
from caracole.viewer import build_viewer, page
from caracole.viewer.book import BookSong, build_songbook

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # G shapes, capo 2
MINOR = to_chordpro("[ch]Cm[/ch]      [ch]Ab[/ch]\nTiny minor words\n[ch]Bb[/ch]     [ch]G7[/ch]\nand back home",
                    title="Minor", artist="Placeholders", key="Cm")
WALL = to_chordpro("[ch]Em7[/ch]      [ch]G[/ch]\nSynthetic words go here\n[ch]Dsus4[/ch]     [ch]A7sus4[/ch]\nmade up",
                   title="Wall", artist="Synthetic", capo=2)
NO_KEY = "{title: T}\n{artist: A}\n{capo: 1}\n[(G)]la [H7]lo\n"
LONG = "{title: Long Song}\n{artist: Synthetic}\n{key: G}\n" + "".join(
    f"[G]Synthetic line [D]number {n} [Em]made up to [C]scroll by\n" for n in range(120))

# The word under each bar button that has one (the key's line is its own).
WORDS = [("necks-toggle", "Shapes"), ("necks-open", "Shapes"), ("size", "Text"), ("scroll", "Scroll"), ("more", "More")]

# The bar as you see it: there or not, slid away or not, and what it says.
BAR = """(() => {
  const q = (s) => document.querySelector(s);
  const bar = q("#bar"), r = bar.getBoundingClientRect(), now = q("#key-now");
  const where = r.height === 0 ? "hidden" : r.top >= innerHeight - 1 ? "away"
    : Math.abs(r.bottom - innerHeight) < 1 ? "shown" : "moving";
  return {where, main: now.querySelector(".k").textContent, sub: now.querySelector(".d").textContent,
          full: q("#key-full").textContent, chord: q('#sheet .c[data-c="0"]') ? q('#sheet .c[data-c="0"]').textContent : "",
          hash: location.hash, focus: document.activeElement ? document.activeElement.id : "",
          sizes: !q("#sizes").hidden && q("#sizes").getClientRects().length > 0,
          sizeOpen: q("#size").getAttribute("aria-expanded"), fs: q("#fs-now").textContent,
          font: getComputedStyle(q("#sheet")).fontSize, panel: !q("#panel").hidden,
          more: q("#more").getAttribute("aria-expanded"), scrim: q("#scrim") !== null, inert: q(".page").inert,
          pill: !q("#pill").hidden, y: Math.round(scrollY)};
})()"""


def written(tmp_path: Path, cho: str = LONG, name: str = "Title") -> str:
    return pages.written(tmp_path, cho, name)


def viewer(tmp_path: Path, url: str | None = None, **options):
    """The viewer at ``url`` (a long sheet's, by default) in a Chromium of its own, once its script ran."""
    return pages.viewer(tmp_path, url or written(tmp_path), **options)


def bar(b: Browser) -> dict:
    return b.js(BAR)


def settled(b: Browser, where: str) -> bool:
    """Whether the bar comes to be ``where`` ("shown", "away", "hidden") within two seconds."""
    return b.wait(f"({BAR}).where === {where!r}", 2)


def watch_slides(b: Browser) -> None:
    """From now on, note whether the bar is ever told to slide away (``slid``): the page decides it in its
    scroll handler, at once, so this sees a slide the moment it starts, however short."""
    b.js("""(() => { window.slides = 0; const bar = document.querySelector('#bar');
      new MutationObserver(() => { if (bar.classList.contains('away')) window.slides += 1; })
        .observe(bar, { attributes: true, attributeFilter: ['class'] }); })()""")


def slid(b: Browser) -> bool:
    """Whether the bar was told to slide away since ``watch_slides``, once the scrolls sent so far have
    come to rest and the page has drawn two frames since (in which their scroll events fire)."""
    rest(b)
    b.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
    return b.js("window.slides") > 0


# --- the page as written ---------------------------------------------------------------------------


def test_the_bar_is_on_the_page_hidden_until_the_script_runs():
    html = build_viewer(UG_CHO)
    assert 'id="fab"' not in html  # the bar takes the one key button's place
    start = html.index('<div class="bar" id="bar"')
    tag = html[start:html.index(">", start)]
    assert " hidden" in tag and 'role="region"' in tag and 'aria-label="Controls"' in tag
    controls = html[start:html.index('<div class="pill"')]
    # In the order a keyboard reaches them, each named for a screen reader: these by an aria-label, the rest by the
    # word each shows under its icon, which its name holds (WCAG 2.5.3), what it does in its title.
    assert re.findall(r'<button type="button"[^>]*id="([^"]+)"[^>]*aria-label="([^"]*)"', controls) == [
        ("t-down", "Down a semitone"), ("t-up", "Up a semitone"), ("size", "Text size"),
        ("smaller", "Smaller text"), ("bigger", "Bigger text"), ("scroll", "Auto-scroll")]
    for id_, word in WORDS:
        assert re.search(rf'id="{id_}"[^>]*>(?:(?!</button>).)*<span class="bw">{word}</span></button>', controls), id_
    assert re.search(r'id="necks-toggle" hidden title="Chord necks" aria-pressed="true"', controls)
    assert re.search(r'id="more" title="Settings" aria-haspopup', controls)
    # Scrolling by itself, an arrow down to a line in a disc, never ▶, pressed while it is on.
    assert page._SCROLL_ICON in controls and "M4.5 2.4v11.2" not in controls
    assert re.search(r'id="scroll" aria-label="Auto-scroll" aria-pressed="false"><span class="disc">'
                     + re.escape(page._SCROLL_ICON) + '</span>', controls)
    assert 'id="shapes"' not in html  # the strip's one switch is the settings' All chord shapes
    # The key between − and +, in short for the eye and in full for a screen reader: a button, which opens the key
    # list (test_viewer_key_list.py).
    assert re.search(r'<button type="button" class="now" id="key-now" aria-haspopup="dialog" aria-controls="key-list"'
                     r' aria-expanded="false">.*id="key-full"', controls)
    # A button is no live region, as the <output> it was: the key's line is said as it moves by a status line of its
    # own, beside the scroll's, outside the bar (hidden while it is away, and in full screen) and outside the key.
    assert ('<p class="vh" id="scroll-status" role="status"></p>\n'
            '<p class="vh" id="key-status" role="status"></p>') in html
    assert 'id="key-status"' not in controls and html.index('id="key-status"') > html.index('<div class="pill"')
    # Aa opens the size, there with the size it shows; ⋯ the settings.
    assert re.search(r'id="size"[^>]*aria-expanded="false" aria-controls="sizes"', controls)
    assert re.search(r'<span class="sizes" id="sizes" role="group" aria-label="Text size" hidden>', controls)
    assert '<output id="fs-now">18 px</output>' in controls
    assert re.search(r'id="more"[^>]*aria-haspopup="dialog" aria-controls="panel" aria-expanded="false"', controls)
    # The neck opens the overlay's sheet, a dialog, below 1200 px (the script shows it there)
    assert re.search(r'id="necks-open" hidden title="Necks and harps" aria-haspopup="dialog" aria-controls="necks"'
                     r' aria-expanded="false"', controls)
    # The settings keep the rest: the transposition and its reset, the capo, the mode, the shapes, and
    # Reset everything; the text size and the scrolling are the bar's.
    panel = html[html.index('id="panel"'):html.index('id="card"')]
    for wanted in ('id="up"', 'id="reset-t"', 'id="capo-row"', 'id="mode-row"', 'id="strip-toggle"', 'id="reset-all"'):
        assert wanted in panel, wanted
    for gone in ('id="smaller"', 'id="scroll"', 'id="scroll-row"', 'id="speed"'):
        assert gone not in panel, gone
    # One control each: the strip's in the settings, the rail's the bar's button (and its own Hide).
    assert 'id="strip-toggle"' in panel and 'id="necks-chip"' not in html and 'id="necks-row"' not in html


# --- what it says ------------------------------------------------------------------------------------


# Under the key, what changed the chords you see from the sheet as written: the capo that plays them ("capo 2", or
# "no capo" for a sheet's capo taken off), then how far they moved ("+2"), else "key". The word is in the accent
# (``changed``) once you moved them or the capo; a screen reader hears the key line whole.
@in_chromium
@pytest.mark.parametrize(
    ("cho", "fragment", "main", "sub", "changed", "full"),
    [(UG_CHO, "", "G", "capo 2", False, "G shapes · capo 2 · sounds A"),
     (WALL, "", "Em", "capo 2", False, "Em shapes · capo 2 · sounds F#m"),
     (MINOR, "", "Cm", "key", False, "Key Cm"),
     (MINOR, "#t=3", "D#m", "+3", True, "Key D#m · +3"),
     (MINOR, "#t=2&capo=2", "Cm", "capo 2", True, "Cm shapes · capo 2 · sounds Dm"),  # the capo plays it: no move
     (UG_CHO, "#capo=0", "A", "no capo · +2", True, "Key A · no capo · +2"),  # the chords two frets up
     (UG_CHO, "#mode=mixolydian&t=1", "Ab mixolydian", "capo 2 · +1", True,  # the move the shapes', not the sound's
      "Ab mixolydian shapes (+1) · capo 2 · sounds Bb mixolydian"),
     (UG_CHO, "#inst=piano", "A", "key", False, "Key A"),  # the capo folded in: no move of yours
     (NO_KEY, "", "Transpose", "capo 1", False, "Transpose · capo 1")],
    ids=["capo", "capo-on-open-shapes", "no-capo", "transposed", "capo-plays-it", "capo-off", "mode", "piano",
         "no-key"],
)
def test_the_bar_says_the_key_in_short_and_a_screen_reader_hears_it_whole(tmp_path, cho, fragment, main, sub,
                                                                             changed, full):
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer(cho), encoding="utf-8")
    dom = browser.dump_dom(page.as_uri() + fragment, (390, 844), hide_scrollbars=True)  # a phone's, over the page
    assert re.search(r'<div class="bar" id="bar"(?![^>]*hidden)', dom)  # there once the script ran
    found = re.search(r'<button[^>]*id="key-now"[^>]*><span class="k" aria-hidden="true">([^<]*)</span>'
                      r'<span class="d( changed)?" aria-hidden="true">([^<]*)</span>'
                      r'<span class="vh" id="key-full">([^<]*)</span>', dom)
    assert found, "no key in the bar"
    assert (found.group(1), found.group(3), bool(found.group(2)), found.group(4)) == (main, sub, changed, full)


@in_chromium
def test_a_sheet_without_chords_keeps_the_text_size_and_the_scrolling(tmp_path):
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer("{title: T}\n{artist: A}\nOnly words\n"), encoding="utf-8")
    dom = browser.dump_dom(page.as_uri(), (390, 844))
    assert 'data-ready="1"' in dom and re.search(r'<div class="bar" id="bar"(?![^>]*hidden)', dom)
    # Nothing to transpose, no shapes and no other setting: no key and no ⋯, but Aa and Scroll.
    assert re.search(r'id="keys"[^>]*hidden', dom) and re.search(r'id="more"[^>]*hidden', dom)
    assert re.search(r'id="necks-open"[^>]*hidden', dom)  # no overlay
    assert not re.search(r'id="size"[^>]*hidden', dom) and not re.search(r'id="scroll"[^>]*hidden', dom)


# --- what it does ------------------------------------------------------------------------------------


@in_chromium
def test_minus_and_plus_transpose_a_semitone_at_a_time(tmp_path):
    with viewer(tmp_path, written(tmp_path, UG_CHO)) as b:
        before = bar(b)
        b.click("#t-up")
        up = bar(b)
        b.click("#t-down")
        b.click("#t-down")
        down = bar(b)
    assert (before["main"], before["chord"], before["hash"]) == ("G", "G", "")
    assert (up["main"], up["sub"], up["chord"], up["hash"]) == ("Ab", "capo 2 · +1", "Ab", "#t=1")
    assert up["full"] == "Ab shapes (+1) · capo 2 · sounds Bb"
    assert down["hash"] == "#t=-1" and down["main"] == down["chord"] == "F#" and down["sub"] == "capo 2 · −1"
    assert not up["panel"] and not down["panel"] and up["where"] == down["where"] == "shown"  # nothing opened


STATUS = "document.querySelector('#key-status').textContent"


@in_chromium
def test_minus_and_plus_are_said_to_a_screen_reader_and_nothing_else_is(tmp_path):
    # #key-status says the key's whole line as − and + move it; nothing as the page opens, nothing for a change of text
    # size, and nothing where something else says it: the settings' Transpose (an output) while they are open, the key's
    # own name as a key chosen from the list gives it the focus back. Then it is cleared, so the next line said is a
    # change, even to the one said last.
    with viewer(tmp_path, written(tmp_path, UG_CHO)) as b:
        loaded = b.js(STATUS)
        b.click("#size")
        b.click("#bigger")
        sized = b.js(STATUS)
        b.click("#t-up")
        up = [b.js(STATUS), bar(b)["full"]]
        b.click("#t-down")
        down = [b.js(STATUS), bar(b)["full"]]
        b.click("#key-now")
        assert b.wait("!document.querySelector('#key-list').hidden")
        b.click('#key-items button[data-k="1"]')
        assert b.wait("document.querySelector('#key-list').hidden")
        chosen = [b.js(STATUS), bar(b)["full"], bar(b)["focus"]]
        b.click("#t-down")  # back to the line said last: said again
        again = [b.js(STATUS), bar(b)["full"]]
        b.click("#more")
        assert b.wait("!document.querySelector('#panel').hidden")
        b.click("#up")
        settings = [b.js(STATUS), b.js("document.querySelector('#shift').textContent")]
    assert loaded == "" and sized == ""
    assert up == ["Ab shapes (+1) · capo 2 · sounds Bb"] * 2
    assert down == ["G shapes · capo 2 · sounds A"] * 2
    assert chosen == ["", "Ab shapes (+1) · capo 2 · sounds Bb", "key-now"]  # its name says it as it takes the focus
    assert again == ["G shapes · capo 2 · sounds A"] * 2
    assert settings == ["", "Abcapo 2 · +1"]  # the settings' Transpose says it


@in_chromium
def test_aa_shows_the_size_beside_the_song_and_changes_it(tmp_path):
    with viewer(tmp_path) as b:
        b.click("#size")
        opened = bar(b)
        b.click("#bigger")
        b.click("#bigger")
        bigger = bar(b)
        b.press("Escape")  # from A+, which has the focus
        closed = bar(b)
        b.click("#size")
        tap(b, "#sheet .w")  # anywhere else
        elsewhere = bar(b)
        b.js("document.querySelector('#size').focus()")
        b.press("Enter")
        b.press("Tab")
        keyboard = bar(b)
        b.press("Enter")
        smaller = bar(b)
    # Non-modal: no scrim, the page within reach, the song in view beside it.
    assert opened["sizes"] and opened["sizeOpen"] == "true" and opened["fs"] == "18 px"
    assert not opened["scrim"] and not opened["inert"] and not opened["panel"]
    assert bigger["sizes"] and bigger["fs"] == "22 px" and bigger["font"] == "22px" and bigger["hash"] == "#fs=22"
    assert not closed["sizes"] and closed["sizeOpen"] == "false" and closed["focus"] == "size"
    assert not elsewhere["sizes"] and elsewhere["where"] == "shown"
    assert keyboard["sizes"] and keyboard["focus"] == "smaller"
    assert smaller["fs"] == "20 px" and smaller["hash"] == "#fs=20"


@in_chromium
def test_the_size_says_when_it_can_grow_no_more(tmp_path):
    with viewer(tmp_path, written(tmp_path, UG_CHO) + "#fs=30") as b:
        b.click("#size")
        top = b.js("[document.querySelector('#bigger').getAttribute('aria-disabled'),"
                   " document.querySelector('#smaller').getAttribute('aria-disabled'), document.querySelector('#fs-now').textContent]")
    assert top == ["true", "false", "30 px"]


@in_chromium
def test_play_starts_the_scroll_and_the_pill_takes_the_bars_place(tmp_path):
    with viewer(tmp_path) as b:
        b.click("#scroll")
        counting = bar(b)
        status = b.js("document.querySelector('#scroll-status').textContent")
        b.click("#pill-end")
        ended = bar(b)
    assert counting["pill"] and counting["where"] == "hidden" and counting["focus"] == "go"
    assert status == "Scrolling in 3 s"
    assert not ended["pill"] and ended["where"] == "shown" and ended["focus"] == "scroll"


# Each tool's word as drawn: whole, under its icon and centred on it.
WORD_UNDER = """(() => [...document.querySelectorAll('#bar .tool')].filter((t) => t.getClientRects().length).map((t) => {
  const word = t.querySelector('.bw'), icon = t.firstElementChild;
  if (!word || icon === word) return {id: t.id, word: null};
  const text = document.createRange();
  text.selectNodeContents(word);  // to the fraction of a pixel
  const r = text.getBoundingClientRect(), w = word.getBoundingClientRect(), i = icon.getBoundingClientRect();
  const b = t.getBoundingClientRect();
  return {id: t.id, word: word.textContent, whole: r.width <= w.width && r.left >= b.left && r.right <= b.right,
          under: w.top >= i.bottom - 0.5 && w.bottom <= b.bottom,
          centred: Math.abs((w.left + w.right) / 2 - (i.left + i.right) / 2) <= 1,
          top: Math.round(w.top * 10) / 10, middle: Math.round((i.top + i.bottom) * 5) / 10};
}))()"""


@in_chromium
def test_every_bar_button_says_its_word_under_its_icon(tmp_path):
    for width, height, mobile in ((390, 844, True), (320, 640, True), (768, 1024, True), (1100, 800, False)):
        with viewer(tmp_path, written(tmp_path, UG_CHO, name=f"W{width}"), width=width, height=height,
                    mobile=mobile) as b:
            seen = b.js(WORD_UNDER)
        assert [(t["id"], t["word"]) for t in seen] == [w for w in WORDS if w[0] != "necks-toggle"], (width, seen)
        for tool in seen:
            assert tool["whole"] and tool["under"] and tool["centred"], (width, tool)
        # One line of words, and the icons over them on one line too, whatever each icon is.
        assert len({t["top"] for t in seen}) == 1 and len({t["middle"] for t in seen}) == 1, (width, seen)


@in_chromium
def test_the_scroll_button_is_lit_while_autoscroll_is_on(tmp_path):
    pressed = "document.getElementById('scroll').getAttribute('aria-pressed')"
    with viewer(tmp_path) as b:
        before = b.js(pressed)
        b.click("#scroll")
        counting = b.js(pressed)
        b.click("#go")
        b.click("#go")  # started, paused: the bar is back
        paused = b.js(f"""[{pressed}, getComputedStyle(document.querySelector('#scroll .disc')).boxShadow !== 'none',
          getComputedStyle(document.querySelector('#scroll .bw')).color
            === getComputedStyle(document.querySelector('#scroll .disc')).backgroundColor]""")
        b.click("#pill-end")
        after = b.js(f"[{pressed}, getComputedStyle(document.querySelector('#scroll .disc')).boxShadow]")
    assert (before, counting, paused, after) == ("false", "true", ["true", True, True], ["false", "none"])


@in_chromium
def test_more_opens_the_rest_of_the_settings(tmp_path):
    with viewer(tmp_path, written(tmp_path, UG_CHO)) as b:
        b.click("#more")
        opened = bar(b)
        shown = b.js("""['capo-row', 'mode-row', 'strip-toggle', 'reset-all']  // a Reset only once a value differs
          .map((id) => document.getElementById(id).getClientRects().length > 0)""")
        b.press("Escape")
        closed = bar(b)
    assert opened["panel"] and opened["more"] == "true" and all(shown)
    assert not closed["panel"] and closed["more"] == "false" and closed["focus"] == "more"


# The strip of chord shapes and the settings' All chord shapes, its one switch.
SHAPES = """(() => {
  const strip = document.querySelector("#strip");
  return {strip: !strip.hidden && strip.querySelectorAll("button").length > 0,
          chip: document.querySelector("#strip-toggle").getAttribute("aria-pressed")};
})()"""


def shapes(b: Browser) -> dict:
    return b.js(SHAPES)


def all_chord_shapes(b: Browser) -> None:
    """The strip shown or hidden by its one switch, the settings' All chord shapes: ⋯, then the switch."""
    b.click("#more")
    b.click("#strip-toggle")


@in_chromium
def test_all_chord_shapes_is_kept_across_a_reload(tmp_path):
    url = written(tmp_path, UG_CHO)
    with viewer(tmp_path, url) as b:
        all_chord_shapes(b)
        b.open(url)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        again = shapes(b)
        all_chord_shapes(b)
        b.open(url)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        off = shapes(b)
    assert again["strip"] and again["chip"] == "true"
    assert not off["strip"] and off["chip"] == "false"


@in_chromium
def test_the_bar_slides_away_as_you_scroll_down_and_comes_back(tmp_path):
    with viewer(tmp_path) as b:
        first = bar(b)["where"]
        drag(b, 500)
        away = settled(b, "away")
        drag(b, -200)  # up
        back_up = settled(b, "shown")
        drag(b, 500)
        assert settled(b, "away")
        rest(b)
        tap(b, "#sheet .w")  # a tap on the song
        back_tap = settled(b, "shown")
        drag(b, 500)
        assert settled(b, "away")
        b.js("window.scrollTo(0, document.documentElement.scrollHeight - innerHeight - 300)")
        drag(b, 600)  # to the end
        at_end = settled(b, "shown")
        end = b.js("innerHeight + scrollY >= document.documentElement.scrollHeight - 2")
    assert first == "shown" and away and back_up and back_tap and at_end and end


@in_chromium
def test_the_keyboard_reaches_every_control_even_when_the_bar_is_away(tmp_path):
    # At 1100 px, the widest the bar is at the foot (from 1200 px it is a toolbar under the title, which never slides
    # away: test_viewer_toolbar.py).
    with viewer(tmp_path, width=1100, height=800, mobile=False) as b:
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=400, deltaX=0, deltaY=600)
        assert settled(b, "away")
        # The last thing on the page, without scrolling there (the end of the song brings the bar back).
        b.js("document.querySelector('.licence summary').focus({preventScroll: true})")
        assert bar(b)["where"] == "away"
        order = []
        for _ in range(7):
            b.press("Tab")
            order.append(bar(b)["focus"])
        back = settled(b, "shown")
        # A control with the keyboard's focus is never slid out of sight, whatever scrolls the page.
        watch_slides(b)
        key(b, "PageDown", 34)
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=400, deltaX=0, deltaY=600)
        down = b.wait(f"({BAR}).y > 600", 2)
        kept = down and not slid(b) and bar(b)["where"] == "shown"
        b.press("Enter")  # ⋯
        opened = bar(b)
    # the key a button between − and + (its list), the neck after it (the overlay's sheet, at 1100)
    assert order == ["t-down", "key-now", "t-up", "necks-open", "size", "scroll", "more"]
    assert back and kept and opened["panel"]


@in_chromium
def test_a_change_of_size_or_key_mid_song_leaves_the_bar_where_it_is(tmp_path):
    # A bigger text, or chords renamed, move the lines under the page's scroll position, and a
    # browser may keep the line you were reading in place by scrolling (Firefox's scroll
    # anchoring): no scroll of yours, so the bar stays.
    with viewer(tmp_path) as b:
        for _ in range(3):
            drag(b, 500)
        assert settled(b, "away")
        rest(b)
        drag(b, -100)
        assert settled(b, "shown")
        rest(b)
        watch_slides(b)
        b.click("#size")
        for _ in range(4):
            b.click("#bigger")
            b.js("window.scrollBy(0, 40)")  # as the browser keeps your line in place
        sized, sized_slid = bar(b), slid(b)
        b.click("#t-up")
        b.js("window.scrollBy(0, 40)")
        after, after_slid = bar(b), slid(b)
        drag(b, 300)  # and your own scrolling still takes it away
        later = settled(b, "away")
    assert sized["where"] == "shown" and sized["sizes"] and sized["fs"] == "26 px" and not sized_slid
    assert after["where"] == "shown" and after["main"] == "Ab" and not after_slid and later


@in_chromium
def test_a_page_that_opens_partway_down_keeps_its_bar(tmp_path):
    # The browser, or the songbook, puts you back where you were in the song: no scroll of yours.
    with viewer(tmp_path) as b:
        b.js("window.scrollTo(0, 1500)")
        time.sleep(0.5)
        kept = bar(b)
    assert kept["where"] == "shown" and kept["y"] == 1500


@in_chromium
def test_the_bar_fits_a_phone_and_a_desktop_and_the_song_ends_above_it(tmp_path):
    measure = """(() => {
      const bar = document.querySelector('#bar').getBoundingClientRect();
      const shown = [...document.querySelectorAll('#bar button')].filter((e) => e.getClientRects().length);
      const buttons = shown.map((e) => { const r = e.getBoundingClientRect(); return Math.min(r.width, r.height); });
      const boxes = shown.map((e) => e.getBoundingClientRect());
      const row = boxes.every((r, i) => r.left >= bar.left && r.right <= bar.right && r.top >= bar.top
        && r.bottom <= bar.bottom && (i === 0 || r.left >= boxes[i - 1].right - 0.5));
      const fits = (e) => { const text = document.createRange();
        text.selectNodeContents(e);  // to the fraction of a pixel, which scrollWidth rounds away
        return text.getBoundingClientRect().width <= e.getBoundingClientRect().width; };
      // The line under the key, or its lines, one above the other, where one line has no room for them.
      const k = document.querySelector('#key-now .k'), d = document.querySelector('#key-now .d');
      const lines = d.children.length ? [...d.children] : [d];
      const keys = document.querySelector('#keys').getBoundingClientRect();
      const now = document.querySelector('#key-now').getBoundingClientRect();
      return {height: Math.round(bar.height), bottom: Math.round(bar.bottom), left: bar.left, right: bar.right,
              width: innerWidth, client: document.documentElement.clientWidth,
              page: document.documentElement.scrollWidth, smallest: Math.min(...buttons), row,
              ids: shown.map((e) => e.id), main: fits(k), size: parseFloat(getComputedStyle(k).fontSize),
              sub: lines.every(fits), said: lines.map((e) => e.textContent),
              inside: Math.round(keys.height) === 54 && now.top >= keys.top && now.bottom <= keys.bottom};
    })()"""
    end = """(() => { scrollTo(0, document.documentElement.scrollHeight);
      const last = [...document.querySelectorAll('.foot > *')].pop().getBoundingClientRect();
      return last.bottom <= document.querySelector('#bar').getBoundingClientRect().top; })()"""
    # From 1200 px the bar is a toolbar under the title (test_viewer_toolbar.py): 1100 px is the widest at the foot.
    for width, height, mobile in ((390, 844, True), (1100, 800, False), (768, 1024, True), (440, 932, True),
                                  (430, 932, True), (360, 740, True), (320, 640, True)):
        with viewer(tmp_path, written(tmp_path, UG_CHO, name=f"W{width}") + "#mode=mixolydian&t=1", width=width,
                    height=height, mobile=mobile) as b:
            m = b.js(measure)
            clear = b.js(end)
        assert 60 <= m["height"] <= 66 and m["bottom"] == height, (width, m)  # 10 px taller, for the words
        assert m["left"] == 0 and m["right"] == m["client"] and m["page"] <= width, (width, m)
        assert m["smallest"] >= (48 if mobile and width >= 380 else 44) and m["row"], (width, m)  # one row, a finger's target
        # After the key the neck, the overlay's sheet up or down (from 1200 px, the rail's toggle in its place)
        assert m["ids"] == ["t-down", "key-now", "t-up", "necks-open", "size", "scroll", "more"], (width, m)
        assert m["inside"], (width, m)  # the key's lines in its box, as tall as the buttons with their words
        # The longest key in short, whole ("Ab mixolydian" over "capo 2 · +1"), with no guitar beside the neck to take
        # its room; narrower, as the buttons grow to 48 px, the key a little smaller (on the narrowest cut short); and where one line has no room
        # for what changed, the capo over the transposition, each whole (as measured at each width).
        assert m["sub"] and m["said"] == (["capo 2", "+1"] if width < 360 else ["capo 2 · +1"]), (width, m)
        if width >= 360:
            assert m["main"] and ((m["size"] == 16) if width >= 440 else (14 <= m["size"] <= 16) if width == 430
                       else (13 <= m["size"] <= 16) if width == 390 else (12 <= m["size"] < 16)), (width, m)
        assert clear, width


@in_chromium
@pytest.mark.parametrize(("width", "height", "wide"), [(390, 844, 48), (430, 932, 48), (768, 1024, 48),
                                                       (360, 740, 44), (320, 640, 44)])
def test_on_a_touch_screen_every_bar_and_pill_button_is_a_fingers_48_px(tmp_path, width, height, wide):
    # Tall 48 always; wide 48 from 380 px, where six of them leave the key room, else 44 (the owner was told).
    measure = """(() => {
      const shown = [...document.querySelectorAll('#bar button, #pill button')].filter((e) => e.getClientRects().length);
      return {coarse: matchMedia('(pointer: coarse)').matches, page: document.documentElement.scrollWidth,
              boxes: shown.map((e) => { const r = e.getBoundingClientRect(); return [e.id || e.className, r.width, r.height]; }),
              key: document.querySelector('#key-now').getBoundingClientRect().width,
              tools: [...document.querySelectorAll("#bar .tool")].filter((e) => e.getClientRects().length).map((e) => e.getBoundingClientRect().height)};
    })()"""
    with viewer(tmp_path, written(tmp_path, UG_CHO, name=f"F{width}"), width=width, height=height) as b:
        b.click("#scroll")
        b.click("#go")  # counting down, then paused: the bar and the pill both shown
        b.click("#go")
        assert b.wait("!document.querySelector('#pill').hidden && document.querySelector('#bar').getBoundingClientRect().height > 0", 2)
        m = b.js(measure)
    assert m["coarse"] and m["page"] <= width, m
    assert any(box[0] == "go" for box in m["boxes"]) and len(m["boxes"]) >= 9, m
    for name, w, h in m["boxes"]:
        assert h >= 48 and w >= wide, (name, w, h, m)
    assert m["key"] >= wide, m
    assert all(round(h) == 54 for h in m["tools"]), m


@in_chromium
def test_with_a_mouse_they_stay_44_px(tmp_path):
    with viewer(tmp_path, written(tmp_path, UG_CHO, name="Mouse"), width=1100, height=800, mobile=False) as b:
        coarse = b.js("matchMedia('(pointer: coarse)').matches")
        sizes = b.js("[...document.querySelectorAll('#bar button')].filter((e) => e.getClientRects().length)"
                     ".map((e) => e.getBoundingClientRect().width)")
    assert coarse is False and min(sizes) == 44, sizes


HIT = """((x, y) => { const e = document.elementFromPoint(x, y);
  return e && e.closest('button') ? e.closest('button').id : null; })"""


NEIGHBOURS = """(() => { const hit = (x, y) => { const e = document.elementFromPoint(x, y);
  return e && e.closest('button') ? e.closest('button').id : null; };
  const y = innerHeight - 30, left = document.querySelector(%r).getBoundingClientRect(),
    right = document.querySelector(%r).getBoundingClientRect();
  return [hit(left.right + 1, y), hit(right.left - 1, y)]; })()"""


@in_chromium
def test_the_corner_buttons_reach_the_screens_edge(tmp_path):
    with viewer(tmp_path) as b:  # 390 x 844, coarse
        corners = b.js(f"[{HIT}(0, innerHeight - 1), {HIT}(innerWidth - 1, innerHeight - 1)]")
        # 1 px inside the neighbours: the key just right of -, Scroll just left of More: the extra areas stop there
        beside = b.js(NEIGHBOURS % ("#t-down", "#more"))
    assert corners == ["t-down", "more"] and beside == ["key-now", "scroll"]


@in_chromium
@pytest.mark.parametrize(("width", "size"), [(390, 16), (430, 16)])
def test_a_plain_key_keeps_its_16_px_beside_the_48_px_buttons(tmp_path, width, size):
    with viewer(tmp_path, written(tmp_path, UG_CHO, name=f"P{width}"), width=width, height=844) as b:
        got = b.js("parseFloat(getComputedStyle(document.querySelector('#key-now .k')).fontSize)")
        whole = b.js("(() => { const k = document.querySelector('#key-now .k'); const r = document.createRange();"
                     " r.selectNodeContents(k); return r.getBoundingClientRect().width <= k.getBoundingClientRect().width; })()")
    assert got == size and whole


@in_chromium
@pytest.mark.parametrize("width", [320, 360, 390])
def test_the_text_size_box_fits_a_phone_with_its_48_px_buttons(tmp_path, width):
    with viewer(tmp_path, written(tmp_path, UG_CHO, name=f"A{width}"), width=width, height=740) as b:
        b.click("#size")
        box = b.js("(() => { const r = document.querySelector('#sizes').getBoundingClientRect();"
                   " return [r.left, r.right, document.documentElement.scrollWidth]; })()")
    assert box[0] >= 0 and box[1] <= width and box[2] <= width, box


@in_chromium
def test_the_key_under_it_is_never_cut_short_by_a_fraction_of_a_pixel(tmp_path):
    # At 344 px "no capo · +2" is a fraction of a pixel wider than its room, which scrollWidth rounds away (it says the
    # line fits): measured to the fraction, "no capo" over "+2", each whole, rather than "no capo · …".
    edge = """(() => { const d = document.querySelector('#key-now .d'), kept = [...d.childNodes];
      const cls = d.className, range = document.createRange();
      d.classList.remove('stack');
      d.textContent = 'no capo · +2';
      range.selectNodeContents(d);
      const over = range.getBoundingClientRect().width - d.getBoundingClientRect().width;
      const rounded = d.scrollWidth <= d.clientWidth;
      d.textContent = '';
      d.append(...kept);
      d.className = cls;
      return [over, rounded]; })()"""
    lines = """[...document.querySelectorAll('#key-now .d > span')].map((e) => { const text = document.createRange();
      text.selectNodeContents(e);
      return [e.textContent, text.getBoundingClientRect().width <= e.getBoundingClientRect().width]; })"""
    with viewer(tmp_path, written(tmp_path, UG_CHO) + "#capo=0", width=344, height=740) as b:
        over, rounded = b.js(edge)
        seen = b.js(lines)
    assert 0 < over < 1 and rounded, (over, rounded)  # the edge this guards: over by a fraction scrollWidth hides
    assert seen == [["no capo", True], ["+2", True]]


@in_chromium
def test_a_move_past_an_octave_is_said_within_one(tmp_path):
    # caracole's [transpose] is −11 to 11; a page made with more still says the move within an octave (26: "+2").
    page = tmp_path / "Artist" / "Far" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer(MINOR, transpose=26), encoding="utf-8")
    with viewer(tmp_path, page.as_uri()) as b:
        seen = [bar(b)[k] for k in ("main", "sub", "full")]
    assert seen == ["Dm", "+2", "Key Dm · +2"]


@in_chromium
def test_with_reduced_motion_the_bar_does_not_slide(tmp_path):
    durations = []
    for reduced in (False, True):
        with viewer(tmp_path, reduced=reduced) as b:
            durations.append(b.js("getComputedStyle(document.querySelector('#bar')).transitionDuration"))
    assert durations[0] != "0s" and durations[1] == "0s"


# --- in a songbook ------------------------------------------------------------------------------------


def songbook(tmp_path: Path) -> str:
    songs = [BookSong("Long Song", "Synthetic", cho=LONG, id="aaaa"),
             BookSong("Minor", "Placeholders", cho=MINOR, id="bbbb")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    return path.as_uri()


@in_chromium
def test_a_songbook_song_has_the_bar_and_its_next_and_previous_too(tmp_path):
    url = songbook(tmp_path)
    with viewer(tmp_path, url + "#song-1") as b:
        on_song = bar(b)
        b.click("#t-up")
        transposed = bar(b)
        # A finger that swipes across the bar moves it, never to another song.
        box = b.js("(() => { const r = document.querySelector('#key-now').getBoundingClientRect();"
                   " return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        b.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": box[0], "y": box[1]}])
        b.send("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": box[0] - 150, "y": box[1]}])
        b.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        swiped = b.wait("!location.hash.startsWith('#song-1')", 1)
        # The song ends with Next above the bar, not under it.
        clear = b.js("""(() => { scrollTo(0, document.documentElement.scrollHeight);
          const next = [...document.querySelectorAll('#song-1 a[rel="next"]')].pop().getBoundingClientRect();
          return next.bottom <= document.querySelector('#bar').getBoundingClientRect().top; })()""")
        b.js("window.before = true")  # gone once the page loads again for the next song
        b.click("#song-1 .sheet + .pager a[rel='next']")
        assert b.wait("window.before === undefined && location.hash.startsWith('#song-2')"
                      " && document.documentElement.dataset.ready === '1'", 5)
        assert settled(b, "shown")
        next_song = bar(b)
    assert on_song["where"] == "shown" and on_song["main"] == "G"
    assert transposed["main"] == "Ab" and transposed["hash"] == "#song-1=&t=1"
    assert not swiped and clear
    assert next_song["main"] == "Cm" and next_song["hash"].startswith("#song-2")


@in_chromium
def test_a_songbook_songs_all_chord_shapes_shows_them(tmp_path):
    with viewer(tmp_path, songbook(tmp_path) + "#song-2") as b:
        all_chord_shapes(b)
        shown = shapes(b)
        names = b.js("[...document.querySelectorAll('#strip button')].map((e) => e.lastChild.textContent)")
    assert shown["strip"] and shown["chip"] == "true"
    assert names == ["Cm", "Ab", "Bb", "G7"]


@in_chromium
def test_the_songbooks_contents_have_no_bar(tmp_path):
    dom = browser.dump_dom(songbook(tmp_path), (390, 844))
    assert 'data-view="contents"' in dom and re.search(r'<div class="bar" id="bar"[^>]*hidden', dom)


# --- the song's end ----------------------------------------------------------------------------------


@in_chromium
@pytest.mark.parametrize("kind", ("sheet", "songbook", "harmonica"))
def test_the_songs_end_comes_up_half_a_screen_clear_of_the_bar(tmp_path, kind):
    from test_viewer_print import _written as written_kind

    url, fragment = written_kind(tmp_path, kind)
    for width, height, mobile in ((390, 844, True), (844, 390, True), (1280, 800, False)):
        with pages.viewer(tmp_path, url + fragment, width=width, height=height, mobile=mobile) as b:
            m = b.js("""(() => { scrollTo(0, document.documentElement.scrollHeight);
              const last = [...document.querySelectorAll('.foot > *')].filter((e) => e.getClientRects().length).pop()
                .getBoundingClientRect();
              const bar = document.querySelector('#bar'), r = bar.getBoundingClientRect();
              // the window's foot where the bar isn't there: hidden, away, or from 1200 px the toolbar at the top
              const floor = bar.hidden || !r.height || bar.classList.contains('away') || r.top < innerHeight / 2
                ? innerHeight : r.top;
              return {room: floor - last.bottom, half: innerHeight / 2}; })()""")
        assert m["room"] >= m["half"] - 1, (kind, width, m)
