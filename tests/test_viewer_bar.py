"""caracole.viewer: the bar at the foot of the sheet viewer (page.py ``_CONTROLS``, viewer.js).

[− key +] [guitar] [Aa] [▶] [⋯]: the song a semitone down or up, with its key in short; the strip of
the song's chord shapes, shown or hidden; the text size; scrolling by itself; and the rest of the settings. It slides away as you scroll down, and comes
back when you scroll up, tap the page or reach the end. The tests that scroll and tap run in a
Chromium of their own on real time (helpers/browser.py's ``Browser``).
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
from caracole.viewer import build_viewer
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
    # In the order a keyboard reaches them, each named for a screen reader.
    assert re.findall(r'<button type="button"[^>]*id="([^"]+)"[^>]*aria-label="([^"]*)"', controls) == [
        ("t-down", "Transpose down a semitone"), ("t-up", "Transpose up a semitone"), ("shapes", "Chord shapes"),
        ("size", "Text size"),
        ("smaller", "Smaller text"), ("bigger", "Bigger text"), ("scroll", "Scroll by itself"),
        ("more", "More settings")]
    # The key between − and +, in short for the eye and in full for a screen reader.
    assert re.search(r'<output class="now" id="key-now" for="t-down t-up">.*id="key-full"', controls)
    # Aa opens the size, there with the size it shows; ⋯ the settings.
    assert re.search(r'id="size"[^>]*aria-expanded="false" aria-controls="sizes"', controls)
    assert re.search(r'<span class="sizes" id="sizes" role="group" aria-label="Text size" hidden>', controls)
    assert '<output id="fs-now">18 px</output>' in controls
    assert re.search(r'id="more"[^>]*aria-haspopup="dialog" aria-controls="panel" aria-expanded="false"', controls)
    # The guitar shows the strip of chord shapes, or hides it: a toggle, a tool like Aa and ⋯, its icon drawn.
    shapes = re.search(r'<button type="button" class="tool shapes" id="shapes"[^>]*>(.*?)</button>', controls)
    assert shapes and 'aria-pressed="false" aria-controls="strip"' in shapes.group(0)
    assert re.fullmatch(r'<svg viewBox="0 0 16 16" aria-hidden="true">(<path d="[^"]+"/>)+</svg>', shapes.group(1))
    # The settings keep the rest: the transposition and its reset, the capo, the mode, the shapes, and
    # Reset everything; the text size and the scrolling are the bar's.
    panel = html[html.index('id="panel"'):html.index('id="card"')]
    for wanted in ('id="up"', 'id="reset-t"', 'id="capo-row"', 'id="mode-row"', 'id="strip-toggle"', 'id="reset-all"'):
        assert wanted in panel, wanted
    for gone in ('id="smaller"', 'id="scroll"', 'id="scroll-row"', 'id="speed"'):
        assert gone not in panel, gone


# --- what it says ------------------------------------------------------------------------------------


@in_chromium
@pytest.mark.parametrize(
    ("cho", "fragment", "main", "sub", "full"),
    [(UG_CHO, "", "G", "shapes · capo 2", "G shapes · capo 2 · sounds A"),
     (WALL, "", "Em", "shapes · capo 2", "Em shapes · capo 2 · sounds F#m"),
     (MINOR, "", "Cm", "key", "Key Cm"),
     (MINOR, "#t=3", "D#m", "key · +3", "Key D#m · +3"),
     (UG_CHO, "#capo=0", "A", "key · no capo", "Key A · no capo"),
     (UG_CHO, "#mode=mixolydian&t=1", "Ab mixolydian", "shapes · capo 2 · +1",
      "Ab mixolydian shapes · capo 2 · sounds Bb mixolydian · +1"),
     (NO_KEY, "", "Transpose", "capo 1", "Transpose · capo 1")],
    ids=["capo", "capo-on-open-shapes", "no-capo", "transposed", "capo-off", "mode", "no-key"],
)
def test_the_bar_says_the_key_in_short_and_a_screen_reader_hears_it_whole(tmp_path, cho, fragment, main, sub, full):
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer(cho), encoding="utf-8")
    dom = browser.dump_dom(page.as_uri() + fragment, (390, 844), hide_scrollbars=True)  # a phone's, over the page
    assert re.search(r'<div class="bar" id="bar"(?![^>]*hidden)', dom)  # there once the script ran
    found = re.search(r'<output class="now" id="key-now"[^>]*><span class="k" aria-hidden="true">([^<]*)</span>'
                      r'<span class="d" aria-hidden="true">([^<]*)</span><span class="vh" id="key-full">([^<]*)</span>',
                      dom)
    assert found, "no key in the bar"
    assert found.groups() == (main, sub, full)


@in_chromium
def test_a_sheet_without_chords_keeps_the_text_size_and_the_scrolling(tmp_path):
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer("{title: T}\n{artist: A}\nOnly words\n"), encoding="utf-8")
    dom = browser.dump_dom(page.as_uri(), (390, 844))
    assert 'data-ready="1"' in dom and re.search(r'<div class="bar" id="bar"(?![^>]*hidden)', dom)
    # Nothing to transpose, no shapes and no other setting: no key, no guitar and no ⋯, but Aa and ▶.
    assert re.search(r'id="keys"[^>]*hidden', dom) and re.search(r'id="more"[^>]*hidden', dom)
    assert re.search(r'id="shapes"[^>]*hidden', dom)
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
    assert (up["main"], up["sub"], up["chord"], up["hash"]) == ("Ab", "shapes · capo 2 · +1", "Ab", "#t=1")
    assert up["full"] == "Ab shapes · capo 2 · sounds Bb · +1"
    assert down["hash"] == "#t=-1" and down["main"] == down["chord"] == "F#" and down["sub"] == "shapes · capo 2 · −1"
    assert not up["panel"] and not down["panel"] and up["where"] == down["where"] == "shown"  # nothing opened


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
    assert status == "Scrolling in 3 seconds"
    assert not ended["pill"] and ended["where"] == "shown" and ended["focus"] == "scroll"


@in_chromium
def test_more_opens_the_rest_of_the_settings(tmp_path):
    with viewer(tmp_path, written(tmp_path, UG_CHO)) as b:
        b.click("#more")
        opened = bar(b)
        shown = b.js("""['capo-row', 'mode-row', 'strip-toggle', 'reset-t', 'reset-all']
          .map((id) => document.getElementById(id).getClientRects().length > 0)""")
        b.press("Escape")
        closed = bar(b)
    assert opened["panel"] and opened["more"] == "true" and all(shown)
    assert not closed["panel"] and closed["more"] == "false" and closed["focus"] == "more"


# The strip of chord shapes, the guitar in the bar and the settings' chip, which say the same.
SHAPES = """(() => {
  const q = (s) => document.querySelector(s);
  const strip = q("#strip"), r = strip.getBoundingClientRect();
  return {strip: !strip.hidden && strip.querySelectorAll("button").length > 0,
          pressed: q("#shapes").getAttribute("aria-pressed"), chip: q("#strip-toggle").getAttribute("aria-pressed"),
          said: q("#strip-toggle").textContent, top: Math.round(r.top), bottom: Math.round(r.bottom),
          bar: Math.round(q("#bar").getBoundingClientRect().top), y: Math.round(scrollY),
          focus: document.activeElement ? document.activeElement.id : ""};
})()"""


def shapes(b: Browser) -> dict:
    return b.js(SHAPES)


@in_chromium
def test_the_guitar_shows_the_chord_shapes_and_hides_them_again(tmp_path):
    with viewer(tmp_path, written(tmp_path, UG_CHO)) as b:
        before = shapes(b)
        b.click("#shapes")
        shown, opened = shapes(b), bar(b)["panel"]
        b.click("#shapes")
        hidden = shapes(b)
    assert not opened  # the strip alone: the settings stay closed
    assert not before["strip"] and before["pressed"] == before["chip"] == "false" and before["said"] == "Show all"
    assert shown["strip"] and shown["pressed"] == shown["chip"] == "true" and shown["said"] == "Hide"
    assert not hidden["strip"] and hidden["pressed"] == hidden["chip"] == "false" and hidden["said"] == "Show all"


@in_chromium
def test_the_guitar_and_the_settings_chip_stay_in_step_both_ways(tmp_path):
    with viewer(tmp_path, written(tmp_path, UG_CHO)) as b:
        b.click("#more")
        b.click("#strip-toggle")  # the chip shows them: the guitar is pressed
        from_chip = shapes(b)
        b.click("#shapes")  # the guitar hides them, with the settings open: the chip says so
        from_bar = shapes(b)
        panel = bar(b)["panel"]
    assert from_chip["strip"] and from_chip["pressed"] == from_chip["chip"] == "true"
    assert not from_bar["strip"] and from_bar["pressed"] == from_bar["chip"] == "false"
    assert from_bar["said"] == "Show all" and panel  # the settings stay open


@in_chromium
def test_the_guitar_brings_the_shapes_into_view_from_anywhere_in_the_song(tmp_path):
    # The strip is above the song: read from halfway down, the guitar takes you up to it, where the
    # shapes are whole above the bar, and the bar stays.
    with viewer(tmp_path) as b:
        b.js("window.scrollTo(0, 2000)")
        assert b.wait("scrollY === 2000")
        b.click("#shapes")
        assert b.wait(f"(({SHAPES}).top >= 0) && ({SHAPES}).bottom <= ({SHAPES}).bar", 3), shapes(b)
        rest(b)
        there = shapes(b)
        shown = bar(b)["where"]
        b.click("#shapes")  # hidden again: nowhere to go
        y = shapes(b)["y"]
    assert there["strip"] and 0 <= there["top"] and there["bottom"] <= there["bar"] and shown == "shown"
    assert y <= there["y"] + 1, (y, there)


@in_chromium
def test_the_guitars_choice_is_kept_across_a_reload(tmp_path):
    url = written(tmp_path, UG_CHO)
    with viewer(tmp_path, url) as b:
        b.click("#shapes")
        b.open(url)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        again = shapes(b)
        b.click("#shapes")
        b.open(url)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        off = shapes(b)
    assert again["strip"] and again["pressed"] == again["chip"] == "true"
    assert not off["strip"] and off["pressed"] == off["chip"] == "false"


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
    with viewer(tmp_path, width=1280, height=800, mobile=False) as b:
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=640, y=400, deltaX=0, deltaY=600)
        assert settled(b, "away")
        # The last thing on the page, without scrolling there (the end of the song brings the bar back).
        b.js("document.querySelector('.licence summary').focus({preventScroll: true})")
        assert bar(b)["where"] == "away"
        order = []
        for _ in range(6):
            b.press("Tab")
            order.append(bar(b)["focus"])
        back = settled(b, "shown")
        # A control with the keyboard's focus is never slid out of sight, whatever scrolls the page.
        watch_slides(b)
        key(b, "PageDown", 34)
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=640, y=400, deltaX=0, deltaY=600)
        down = b.wait(f"({BAR}).y > 600", 2)
        kept = down and not slid(b) and bar(b)["where"] == "shown"
        b.press("Enter")  # ⋯
        opened = bar(b)
    assert order == ["t-down", "t-up", "shapes", "size", "scroll", "more"]
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
      const fits = (s) => { const e = document.querySelector(s), text = document.createRange();
        text.selectNodeContents(e);  // to the fraction of a pixel, which scrollWidth rounds away
        return text.getBoundingClientRect().width <= e.getBoundingClientRect().width; };
      return {height: Math.round(bar.height), bottom: Math.round(bar.bottom), left: bar.left, right: bar.right,
              width: innerWidth, client: document.documentElement.clientWidth,
              page: document.documentElement.scrollWidth, smallest: Math.min(...buttons), row,
              ids: shown.map((e) => e.id),
              main: fits('#key-now .k'), sub: fits('#key-now .d'), said: document.querySelector('#key-now .d').textContent};
    })()"""
    end = """(() => { scrollTo(0, document.documentElement.scrollHeight);
      const last = [...document.querySelectorAll('.foot > *')].pop().getBoundingClientRect();
      return last.bottom <= document.querySelector('#bar').getBoundingClientRect().top; })()"""
    for width, height, mobile in ((390, 844, True), (1280, 800, False), (360, 740, True), (320, 640, True)):
        with viewer(tmp_path, written(tmp_path, UG_CHO, name=f"W{width}") + "#mode=mixolydian&t=1", width=width,
                    height=height, mobile=mobile) as b:
            m = b.js(measure)
            clear = b.js(end)
        assert 50 <= m["height"] <= 54 and m["bottom"] == height, (width, m)
        rail = 300 if width >= 1200 else 0  # from 1200 px the rail of necks is on its left
        assert m["left"] == rail and m["right"] == m["client"] and m["page"] <= width, (width, m)
        assert m["smallest"] >= 44 and m["row"], (width, m)  # one row, each a thumb's target, none over another
        assert m["ids"] == ["t-down", "t-up", "shapes", "size", "scroll", "more"], (width, m)
        if width >= 390:  # the longest key in short, whole ("Ab mixolydian" over "shapes · capo 2 · +1")
            assert m["main"] and m["sub"] and m["said"] == "shapes · capo 2 · +1", (width, m)
        elif width >= 360:  # with no room for "shapes", the capo and the transposition, whole
            assert m["sub"] and m["said"] == "capo 2 · +1", (width, m)
        assert clear, width


@in_chromium
def test_the_key_under_it_is_never_cut_short_by_a_fraction_of_a_pixel(tmp_path):
    # At 360 px "shapes · capo 2" is a fraction of a pixel wider than its room, which scrollWidth rounds away:
    # without "shapes", whole, rather than "shapes · capo…".
    with viewer(tmp_path, written(tmp_path, UG_CHO), width=360, height=740) as b:
        seen = b.js("""(() => { const d = document.querySelector('#key-now .d'), text = document.createRange();
          text.selectNodeContents(d);
          return [d.textContent, text.getBoundingClientRect().width <= d.getBoundingClientRect().width]; })()""")
    assert seen == ["capo 2", True]


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
def test_a_songbook_songs_guitar_shows_its_shapes(tmp_path):
    with viewer(tmp_path, songbook(tmp_path) + "#song-2") as b:
        b.click("#shapes")
        shown = shapes(b)
        names = b.js("[...document.querySelectorAll('#strip button')].map((e) => e.lastChild.textContent)")
    assert shown["strip"] and shown["pressed"] == shown["chip"] == "true"
    assert names == ["Cm", "Ab", "Bb", "G7"]


@in_chromium
def test_the_songbooks_contents_have_no_bar(tmp_path):
    dom = browser.dump_dom(songbook(tmp_path), (390, 844))
    assert 'data-view="contents"' in dom and re.search(r'<div class="bar" id="bar"[^>]*hidden', dom)
