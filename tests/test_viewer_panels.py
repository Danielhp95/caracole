"""caracole.viewer: the settings (⋯) and a chord's card leave the song in view (viewer.js, viewer.css).

Neither is modal: no scrim, and nothing behind it out of reach. On a phone each docks at the foot,
above the bar, the settings in at most 45 % of the screen and the card in about 200 px, and the song
scrolls under them; from 900 px wide the settings are a rail beside the song and the card a popover
by its chord. Another chord tapped fills the card that is open; Escape closes the one on top, and the
focus goes back to what opened it. The tests tap, drag and press keys in a Chromium of their own on
real time (helpers/browser.py's ``Browser``).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from helpers import viewer_pages as pages
from helpers.browser import Browser, in_chromium
from helpers.targets import small_targets
from helpers.viewer_pages import click_at, drag, rest, tab, tap_at

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # G shapes, capo 2
# Long enough to scroll on any screen: G, D, Em, C, G/B, Am and F (data-c 0 to 6), with a capo.
LONG = "{title: Long Song}\n{artist: Synthetic}\n{key: G}\n{capo: 2}\n" + "".join(
    f"{{comment: Verse {n}}}\n[G]Synthetic line [D]number {n} [Em]made up to [C]scroll by\n[G/B]and [Am]on it [F]goes\n\n"
    for n in range(40))
PHONE = {"width": 390, "height": 844, "mobile": True}
DESKTOP = {"width": 1280, "height": 800, "mobile": False}

# Where the settings, the card, the bar, the sheet and the pill are on the screen (None: not shown),
# and what the page says about them.
LOOK = """(() => {
  const q = (s) => document.querySelector(s);
  const box = (el) => {
    if (!el || el.hidden || !el.getClientRects().length) return null;
    const r = el.getBoundingClientRect();
    return {top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), right: Math.round(r.right),
            width: Math.round(r.width), height: Math.round(r.height)};
  };
  const seen = (el) => Boolean(box(el)) && getComputedStyle(el).visibility === "visible";
  const active = document.activeElement;
  return {panel: box(q("#panel")), card: box(q("#card")), bar: box(q("#bar")), sheet: box(q("#sheet")),
          pill: box(q("#pill")), panelSeen: seen(q("#panel")), cardSeen: seen(q("#card")),
          name: q("#card-name").textContent, more: q("#more").getAttribute("aria-expanded"),
          focus: active ? active.id || active.className : "", chord: active ? active.closest("#sheet .c") !== null : false,
          inert: q(".page").inert || q("#bar").inert || q("#pill").inert, scrim: q("#scrim") !== null,
          y: Math.round(scrollY), page: document.documentElement.scrollWidth, width: innerWidth,
          client: document.documentElement.clientWidth};  // innerWidth less a desktop's scroll bar
})()"""


def written(tmp_path: Path, cho: str = LONG, name: str = "Title") -> str:
    return pages.written(tmp_path, cho, name)


def viewer(tmp_path: Path, url: str | None = None, **options):
    """The viewer at ``url`` (the long sheet's, by default) in a Chromium of its own, once its script ran."""
    return pages.viewer(tmp_path, url or written(tmp_path), **options)


def look(b: Browser) -> dict:
    return b.js(LOOK)


def chord(b: Browser, name: str, *, below: int = 0, above: int | None = None) -> list[float]:
    """The middle of a chord ``name`` that a finger or the mouse reaches (on top, nothing over it), between
    ``below`` and ``above`` px down the screen; it is ``window.picked`` for the test to ask about."""
    found = b.js(f"""(() => {{
      const limit = {above if above is not None else "innerHeight"};
      const el = [...document.querySelectorAll('#sheet .c')].find((c) => {{
        const r = c.getBoundingClientRect();
        if (c.textContent !== {name!r} || r.top < {below} || r.bottom > limit) return false;
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return hit === c || c.contains(hit);
      }});
      if (!el) return null;
      window.picked = el;
      const r = el.getBoundingClientRect();
      return [r.left + r.width / 2, r.top + r.height / 2, r.top, r.bottom, r.left, r.right];
    }})()""")
    assert found, f"no {name} in reach"
    return found


# --- the page as written ---------------------------------------------------------------------------


def test_the_settings_and_the_card_are_dialogs_that_leave_the_page_alone():
    html = build_viewer(UG_CHO)
    assert 'id="scrim"' not in html and 'class="scrim"' not in html  # nothing dims the song
    for name, label in (("panel", "panel-title"), ("card", "card-name")):
        tag = re.search(rf'<section class="sheet-ui[^"]*" id="{name}"[^>]*>', html)
        assert tag, name
        assert 'role="dialog"' in tag.group(0) and f'aria-labelledby="{label}"' in tag.group(0)
        assert "aria-modal" not in tag.group(0)  # the page behind it stays within reach


# --- the settings ------------------------------------------------------------------------------------


@in_chromium
def test_on_a_phone_the_settings_dock_above_the_bar_and_the_song_stays_in_view(tmp_path):
    with viewer(tmp_path) as b:
        b.click("#more")
        opened = look(b)
        # A chord above the settings is in view and within reach, and changes as you transpose.
        chord(b, "G", above=opened["panel"]["top"])
        b.click("#up")
        moved = b.js("window.picked.textContent")
        drag(b, 260, start=360)  # the song, not the settings, under the finger
        rest(b)
        scrolled = look(b)
        # Its end comes up above them, the footer too.
        clear = b.js("""(() => { scrollTo(0, document.documentElement.scrollHeight);
          const last = [...document.querySelectorAll('.foot > *')].pop().getBoundingClientRect();
          return last.bottom <= document.querySelector('#panel').getBoundingClientRect().top + 1; })()""")
    panel, bar = opened["panel"], opened["bar"]
    assert opened["more"] == "true" and opened["focus"] == "panel-title"
    assert not opened["scrim"] and not opened["inert"]
    assert panel["bottom"] == bar["top"] and panel["left"] == 0 and panel["right"] == 390  # docked on the bar
    assert panel["height"] <= round(0.45 * 844)
    assert moved == "Ab"
    assert scrolled["y"] >= opened["y"] + 150 and scrolled["panel"] == panel  # the song moved, not the settings
    assert clear and scrolled["page"] <= 390


@in_chromium
def test_just_below_900_px_the_settings_still_dock(tmp_path):
    with viewer(tmp_path, width=899, height=800, mobile=False) as b:
        b.click("#more")
        opened = look(b)
    assert opened["panel"]["bottom"] == opened["bar"]["top"] and opened["panel"]["top"] > 0


@in_chromium
@pytest.mark.parametrize("width", [1280, 900])
def test_from_900_px_wide_the_settings_are_a_rail_beside_the_song(tmp_path, width):
    with viewer(tmp_path, width=width, height=800, mobile=False) as b:
        before = look(b)
        b.click("#more")
        opened = look(b)
        b.click("#up")
        moved = b.js("document.querySelector('#sheet .c').textContent")
        b.press("Escape")  # from +, in the rail
        closed = look(b)
    rail = opened["panel"]
    assert rail["top"] == 0 and rail["bottom"] == 800 and rail["right"] == opened["client"]
    assert 300 <= rail["width"] <= 400
    assert opened["sheet"]["right"] <= rail["left"] and opened["bar"]["right"] <= rail["left"]  # beside it
    assert opened["page"] <= width and not opened["inert"] and not opened["scrim"]
    assert moved == "Ab"
    assert closed["panel"] is None and closed["focus"] == "more"
    assert [closed["sheet"][k] for k in ("left", "right")] == [before["sheet"][k] for k in ("left", "right")]


@in_chromium
@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_the_head_clears_the_line_under_it(tmp_path, size):
    # Its title on one line, and what is set under it, however long that runs, above Transpose and Capo.
    measure = """(() => { const lines = (el) => { const range = document.createRange(); range.selectNodeContents(el);
        return [new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size, range.getBoundingClientRect().bottom]; };
      return [lines(document.querySelector('#panel-title'))[0], lines(document.querySelector('#panel-sum'))[1],
              document.querySelector('#t-row').getBoundingClientRect().top]; })()"""
    with viewer(tmp_path, written(tmp_path) + "#t=1&mode=mixolydian&capo=11&inst=baritone", **size) as b:
        b.click("#more")
        lines, text, row = b.js(measure)
    assert lines == 1 and text <= row - 4


# --- what the settings hold, top to bottom ------------------------------------------------------------

IN_E = "{title: In E}\n{artist: Synthetic}\n{key: E}\n{comment: Verse}\n[E]la la [A]la la [B7]la la [E]la\n"
NO_KEY = "{title: Riffs}\n{artist: Synthetic}\n{capo: 1}\n{comment: Verse}\n[N.C.]Made up [Xq]words\n"
# The settings' head: its title, the line of what is set, and the part of it in bold.
HEAD = """[document.getElementById('panel-title').textContent, document.getElementById('panel-sum').textContent,
  (document.querySelector('#panel-sum b') || {}).textContent || '']"""
# Whether each Reset shows, and whether its stepper's edge says the value differs.
RESETS = """(() => { const q = (s) => document.querySelector(s);
  const shown = (el) => !el.hidden && el.getClientRects().length > 0;
  return {t: shown(q('#reset-t')), capo: shown(q('#reset-capo')),
          tMarked: q('#up').closest('.stepper').classList.contains('changed'),
          capoMarked: q('#capo-up').closest('.stepper').classList.contains('changed')}; })()"""
SHIFT = "document.getElementById('shift').textContent"


def mode(b: Browser, name: str) -> None:
    """The settings' mode ``name``, pressed."""
    b.js(f"[...document.querySelectorAll('#modes .chip')].find((c) => c.firstChild.textContent === {name!r}).click()")


@in_chromium
def test_the_settings_head_says_key_mode_capo_and_instrument(tmp_path):
    with viewer(tmp_path, written(tmp_path, IN_E)) as b:
        b.click("#more")
        first = b.js(HEAD)
        mode(b, "Dorian")
        b.click("#capo-up")
        b.click("#capo-up")
        chosen = b.js(HEAD)
    with viewer(tmp_path, written(tmp_path, name="Long") + "#inst=piano") as b:
        b.click("#more")
        piano = b.js(HEAD)
    with viewer(tmp_path, written(tmp_path, NO_KEY, name="Riffs") + "#t=2") as b:
        b.click("#more")
        moved = b.js(HEAD)
        b.click("#reset-t")
        unknown = b.js(HEAD)
    assert first == ["Settings", "E Major · Guitar", "E Major"]
    assert chosen == ["Settings", "D Dorian · capo 2 · Guitar", "D Dorian"]  # the shapes played, and the capo
    assert piano == ["Settings", "A Major · Piano", "A Major"]  # G shapes, capo 2: no capo, the key it sounds in
    assert moved == ["Settings", "Transposed +2 · capo 1 · Guitar", "Transposed +2"]
    assert unknown == ["Settings", "As written · capo 1 · Guitar", "As written"]


@in_chromium
def test_a_reset_shows_only_while_a_value_differs(tmp_path):
    with viewer(tmp_path) as b:  # G shapes, capo 2
        b.click("#more")
        sheet = b.js(RESETS)
        b.click("#capo-up")
        capo = b.js(RESETS)
        b.js("document.getElementById('reset-capo').focus()")
        b.press("Enter")
        back = [b.js(RESETS), b.js("document.getElementById('capo-at').textContent"),
                b.js("document.activeElement.closest('.stepper') === document.getElementById('capo-up').parentElement")]
        b.click("#up")
        up = b.js(RESETS)
    assert sheet == {"t": False, "capo": False, "tMarked": False, "capoMarked": False}
    assert capo == {"t": False, "capo": True, "tMarked": False, "capoMarked": True}
    assert back == [sheet, "2", True]  # the focus on the stepper it put back, not lost with the Reset
    assert up == {"t": True, "capo": False, "tMarked": True, "capoMarked": False}


@in_chromium
def test_transpose_reset_goes_back_to_the_pdfs_transposition(tmp_path):
    page = tmp_path / "Artist" / "Moved" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer(LONG, transpose=2), encoding="utf-8")
    with viewer(tmp_path, page.as_uri()) as b:
        b.click("#more")
        pdf = [b.js(SHIFT), b.js(RESETS)["t"]]
        b.click("#down")
        b.click("#down")
        zero = [b.js(SHIFT), b.js(RESETS)["t"]]  # the sheet as written, which the PDF isn't
        b.click("#reset-t")
        back = [b.js(SHIFT), b.js(RESETS)["t"]]
    assert pdf == ["+2", False] and zero == ["0", True] and back == ["+2", False]


@in_chromium
def test_transpose_and_capo_share_a_line_at_390px(tmp_path):
    seen = """(() => { const r = (s) => document.querySelector(s).getBoundingClientRect();
      return {rows: [r('#t-row').top, r('#capo-row').top], steppers: [r('#down').top, r('#capo-down').top],
              between: r('#up').right <= r('#capo-down').left, page: document.documentElement.scrollWidth}; })()"""
    with viewer(tmp_path) as b:
        b.click("#more")
        b.click("#capo-up")  # its Reset shown: nothing moves
        shown = b.js(seen)
        b.click("#reset-capo")
        hidden = b.js(seen)
    assert shown["rows"][0] == shown["rows"][1] and shown["steppers"][0] == shown["steppers"][1]
    assert shown["between"] and shown["page"] <= 390
    assert hidden == shown


@in_chromium
def test_an_instrument_without_a_capo_shows_transpose_alone(tmp_path):
    with viewer(tmp_path, written(tmp_path) + "#inst=piano") as b:
        b.click("#more")
        seen = b.js("""(() => { const q = (s) => document.querySelector(s), panel = q('#panel');
          const style = getComputedStyle(panel);
          return {capo: q('#capo-row').getClientRects().length > 0, width: q('#t-row').getBoundingClientRect().width,
                  room: panel.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)}; })()""")
    assert not seen["capo"] and seen["width"] >= seen["room"] - 1  # the whole width


# --- a chord's card ------------------------------------------------------------------------------------


@in_chromium
def test_on_a_phone_a_chords_card_docks_and_the_next_chord_tapped_fills_it(tmp_path):
    with viewer(tmp_path) as b:
        tap_at(b, *chord(b, "G")[:2])
        first = look(b)
        sizes = b.js("""[...document.querySelectorAll('#card button')].filter((e) => e.getClientRects().length)
          .map((e) => { const r = e.getBoundingClientRect(); return Math.min(r.width, r.height); })""")
        tap_at(b, *chord(b, "D", above=first["card"]["top"])[:2])  # one in view above the card
        second = look(b)
        drag(b, 300, start=420)
        rest(b)
        scrolled = look(b)
        b.click("#card .x")
        closed = look(b)
    card, bar = first["card"], first["bar"]
    assert first["name"] == "G" and not first["inert"] and not first["scrim"]
    assert card["bottom"] == bar["top"] and card["left"] == 0 and card["right"] == 390  # docked on the bar
    assert 150 <= card["height"] <= 290  # about a third of the screen: most of the song stays in view
    assert min(sizes) >= 44
    assert second["name"] == "D" and second["card"] == card  # filled in place, holding still
    assert scrolled["y"] >= second["y"] + 150 and scrolled["card"] == card  # the song scrolls under it
    assert closed["card"] is None and scrolled["page"] <= 390


@in_chromium
@pytest.mark.parametrize("reduced", [False, True], ids=["motion", "reduced-motion"])
def test_on_a_phone_a_chord_tapped_low_on_the_screen_comes_up_above_its_card(tmp_path, reduced):
    with viewer(tmp_path) as b:
        b.send("Emulation.setEmulatedMedia", features=[
            {"name": "prefers-reduced-motion", "value": "reduce" if reduced else "no-preference"}])
        b.js("scrollTo(0, 900)")
        time.sleep(0.2)
        low = chord(b, "C", below=844 - 53 - 200, above=844 - 53)  # where the card will be
        tap_at(b, *low[:2])
        assert b.wait("(() => { const y = scrollY; return new Promise((r) => setTimeout(() => r(scrollY === y), 150)); })()")
        shown = look(b)
        where = b.js("window.picked.closest('.l').getBoundingClientRect().bottom")  # its line, words and all
        high = chord(b, "G", below=100, above=shown["card"]["top"] - 60)  # one in view already...
        y = look(b)["y"]
        tap_at(b, *high[:2])
        time.sleep(0.4)
        still = look(b)["y"]
    assert shown["name"] == "C" and shown["y"] > 900
    assert where <= shown["card"]["top"]  # in sight, lit, with its words, and its card under it
    assert still == y  # ...and the page stays where it is


@in_chromium
def test_on_a_desktop_a_chords_card_is_a_popover_by_the_chord(tmp_path):
    with viewer(tmp_path, **DESKTOP) as b:
        g = chord(b, "G", below=150, above=400)
        click_at(b, *g[:2])
        first = look(b)
        d = chord(b, "Em", below=g[2] - 4, above=g[3] + 4)  # further along the same line
        click_at(b, *d[:2])
        second = look(b)
        b.js("window.scrollBy(0, 120)")
        scrolled = look(b)
        b.press("Escape")
        closed = look(b)
        back = b.js("document.activeElement === window.picked")
        low = chord(b, "Am", below=800 - 53 - 200, above=800 - 53)  # near the bar: no room below it
        click_at(b, *low[:2])
        above = look(b)
    for found, at in ((first, g), (second, d)):
        card = found["card"]
        assert card["top"] >= at[3] and card["top"] <= at[3] + 16  # just under its chord...
        assert card["left"] <= at[4] and card["right"] >= at[5]  # ...and across it
        assert card["width"] <= 380 and card["bottom"] <= found["bar"]["top"]
    assert first["name"] == "G" and second["name"] == "Em" and not first["inert"] and not first["scrim"]
    assert second["card"]["left"] > first["card"]["left"]  # over to the chord tapped
    assert scrolled["card"]["top"] == second["card"]["top"] - 120  # it goes with its chord as the page scrolls
    assert closed["card"] is None and back  # the focus back on the chord that opened it
    assert above["card"]["bottom"] <= low[2] and above["card"]["bottom"] >= low[2] - 16 and above["card"]["top"] >= 0


@in_chromium
def test_an_open_card_follows_the_key_and_the_mode(tmp_path):
    with viewer(tmp_path, **DESKTOP) as b:
        click_at(b, *chord(b, "G", below=150)[:2])
        b.click("#t-up")
        up = b.js("[document.querySelector('#card-name').textContent,"
                  " document.querySelector('#diagram svg').getAttribute('aria-label')]")
        b.click("#more")
        b.js("[...document.querySelectorAll('#modes .chip')].find((c) => c.firstChild.textContent === 'Minor').click()")
        minor = look(b)
        sheet = b.js("window.picked.textContent")
    assert up == ["Ab", "Ab"]
    assert minor["name"] == sheet and sheet.endswith("m")  # its minor chord, as the sheet now names it
    assert minor["card"] and minor["panel"]  # both open, side by side


@in_chromium
def test_while_the_song_scrolls_by_itself_a_card_docks_on_the_bar_under_the_pill(tmp_path):
    with viewer(tmp_path) as b:
        b.click("#scroll")
        b.click("#go")  # at once
        time.sleep(0.4)
        alone = look(b)
        tap_at(b, *chord(b, "C", above=600)[:2])  # pauses it, and opens the card
        docked = look(b)
        paused = b.js("document.querySelector('#go').getAttribute('aria-label')")
        b.click("#go")  # ▶, beside the card
        again = b.js("document.querySelector('#go').getAttribute('aria-label')")
        resumed = look(b)
        b.click("#card .x")
        closed = look(b)
    card, pill = docked["card"], docked["pill"]
    assert alone["bar"] is None and alone["pill"]["bottom"] == 844 - 53 - 12  # above where the bar was
    assert docked["name"] == "C" and paused == "Resume" and not docked["inert"]
    assert card["bottom"] == docked["bar"]["top"] and pill["bottom"] <= card["top"]  # on the bar, the pill above
    # Counting down again with the card open, nothing moves under the thumb: the bar stays under the card.
    assert again == "Start now"
    assert [resumed[k] for k in ("card", "pill", "bar")] == [docked[k] for k in ("card", "pill", "bar")]
    assert closed["card"] is None and closed["bar"] is None and closed["pill"] == alone["pill"]


# The card's notes, each with its interval, and its scale for a solo: its name and its notes.
NOTES = """({notes: [...document.querySelectorAll('#card-tones .tn')].map((t) => [t.firstChild.textContent,
    t.querySelector('small').textContent]),
  scale: document.querySelector('#card-scale .sn') ? [document.querySelector('#card-scale .sn').textContent,
    document.querySelector('#card-scale .sx').textContent] : null,
  name: document.getElementById('card-name').textContent,
  box: (() => { const r = document.getElementById('card').getBoundingClientRect(); return [Math.round(r.top), Math.round(r.height)]; })()})"""
IN_C = "{title: Notes}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n[C]made [Dm7]up [G7]words [C]here\n"


@in_chromium
def test_a_chords_card_lists_its_notes_and_the_scale_for_a_solo_over_it(tmp_path):
    with viewer(tmp_path, written(tmp_path, IN_C)) as b:
        tap_at(b, *chord(b, "Dm7")[:2])
        assert b.wait("!document.getElementById('card').hidden")
        dm7 = b.js(NOTES)
        b.click("#t-up")
        b.click("#t-up")
        em7 = b.js(NOTES)
        b.js("document.querySelectorAll('#alts .chip')[1].click()")  # an alternative, tried
        tried = b.js(NOTES)
        targets = b.js(small_targets(".foot *"))
    assert dm7["notes"] == [["D", "R"], ["F", "♭3"], ["A", "5"], ["C", "♭7"]]
    assert dm7["scale"] == ["D Dorian", "D E F G A B C"]
    assert em7["name"] == "Em7" and em7["notes"] == [["E", "R"], ["G", "♭3"], ["B", "5"], ["D", "♭7"]]
    assert em7["scale"] == ["E Dorian", "E F# G A B C# D"]
    assert tried["name"] != "Em7" and tried["notes"] and tried["notes"] != em7["notes"] and tried["scale"]
    assert dm7["box"] == em7["box"] == tried["box"]  # the card holds still from chord to chord
    assert targets == []


@in_chromium
def test_a_card_for_a_chord_caracole_cant_read_lists_no_notes(tmp_path):
    with viewer(tmp_path, written(tmp_path, "{title: T}\n{comment: V}\n[N.C.]made [Xq]up\n"), **DESKTOP) as b:
        b.js("document.querySelector('#sheet .c').click()")
        assert b.wait("!document.getElementById('card').hidden")
        seen = b.js(NOTES)
    assert seen["notes"] == [] and seen["scale"] is None and seen["name"] == "N.C."


# --- the Harmony panel --------------------------------------------------------------------------------

SONG = ("{title: Progressions}\n{artist: Synthetic}\n{key: C}\n"
        "{comment: Verse}\n" + "[C]made [G]up [Am]words [F]here\n" * 4 + "\n"
        "{comment: Chorus}\n[F]and [G]the [C]cho[Am]rus\n[F]ends [G]at [C]home\n\n"
        "{comment: Riff}\n[N.C.]no chords here\n\n"
        "{comment: Bridge}\n[Am]down [G]the [F]stairs [E7]again\n")
UNNAMED = "{title: Unnamed}\n{artist: Synthetic}\n[Am]down [G]the [F]stairs [E7]again\n[Am]down [G]the [F]stairs [E7]again\n"
# What the Harmony panel lists, section by section, and where it is.
HARMONY = """(() => { const h = document.getElementById('harmony');
  const r = h.getBoundingClientRect();
  return {open: !h.hidden, box: h.hidden ? null : {top: Math.round(r.top), bottom: Math.round(r.bottom),
            left: Math.round(r.left), right: Math.round(r.right)},
    key: document.getElementById('harmony-key').textContent,
    neck: h.querySelector('.kn') !== null,
    tempo: !document.getElementById('tempo-row').hidden,
    rows: [...h.querySelectorAll('.prog')].map((li) => ({
      section: li.querySelector('.prog-sec').textContent,
      numerals: [...li.querySelectorAll('.prog-nums .pn')].map((n) => n.textContent),
      repeats: li.querySelector('.prog-x') ? li.querySelector('.prog-x').textContent : '',
      about: li.querySelector('.prog-about').textContent,
      play: !li.querySelector('.prog-play').hidden,
      songs: li.querySelector('.prog-songs').getAttribute('href'),
      named: [...li.querySelectorAll('.prog-named')].map((a) => [a.textContent, a.getAttribute('href')])})),
    focus: document.activeElement ? document.activeElement.id : '', panel: !document.getElementById('panel').hidden,
    page: document.documentElement.scrollWidth}; })()"""
# A stand-in for HV3's synthesis (strum.js: window.caracoleSound), noting what it is asked to play.
FAKE_SOUND = """window.caracoleSound = {available: true, stop() {},
  play(chords, options) { window.asked = {chords, bpm: options.bpm}; window.playing = options;
    options.onChord(0);
    return {playing: true, stop() { window.stopped = true; options.onEnd(false); }}; }};"""


def open_harmony(b: Browser) -> None:
    b.click("#more")
    b.click("#harmony-open")
    assert b.wait("!document.getElementById('harmony').hidden")


@in_chromium
def test_on_a_phone_the_harmony_panel_docks_in_place_of_the_settings_and_lists_each_sections_progression(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        open_harmony(b)
        seen = b.js(HARMONY)
        bar = look(b)["bar"]
        targets = b.js(small_targets(".foot *"))
    assert seen["open"] and not seen["panel"] and seen["focus"] == "harmony-title"
    assert seen["box"]["bottom"] == bar["top"] and seen["box"]["left"] == 0 and seen["box"]["right"] == 390
    assert seen["key"] == "Read in the key of C (from the sheet)."
    assert seen["neck"]  # the key's neck, on a phone, is here
    verse, chorus, bridge = seen["rows"]  # the riff has no chord to read
    assert verse == {"section": "Verse", "numerals": ["I", "V", "vi", "IV"], "repeats": "×4",
                     "about": "the pop progression", "play": True,  # strum.js plays it
                     "songs": "../../index.html#prog=I%20V%20vi%20IV", "named": []}
    assert chorus["numerals"] == ["IV", "V", "I", "vi", "IV", "V", "I"] and chorus["repeats"] == ""
    # Its C Am F G, I–vi–IV–V, is the '50s progression from its own first chord, inside the longer chorus.
    assert chorus["about"] == "contains the '50s progression · ends on an authentic cadence (V–I)"
    assert chorus["named"] == [["Songs with the '50s progression", "../../index.html#prog=I%20vi%20IV%20V"]]
    assert verse["named"] == []  # the verse is the pop progression whole: its own link says so
    assert bridge["section"] == "Bridge" and bridge["numerals"][0] == "vi"
    assert seen["tempo"] and seen["page"] <= 390 and targets == []


@in_chromium
def test_a_page_that_cant_play_a_chord_offers_no_play_and_no_tempo(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.js("window.caracoleSound = undefined")  # as in a browser with no Web Audio
        open_harmony(b)
        seen = b.js(HARMONY)
    assert seen["rows"] and not any(r["play"] for r in seen["rows"]) and not seen["tempo"]


@in_chromium
def test_with_the_sound_off_the_panel_offers_no_play_until_it_is_on_again(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG) + "#vol=0") as b:
        open_harmony(b)
        off = b.js(HARMONY)
        b.js("document.querySelector('#harmony [data-close]').click()")
        b.click("#more")
        b.js("[...document.querySelectorAll('#volumes .chip')].find((c) => c.textContent === 'Soft').click()")
        b.click("#harmony-open")
        assert b.wait("!document.getElementById('harmony').hidden")
        on = b.js(HARMONY)
    assert off["rows"] and not any(r["play"] for r in off["rows"]) and not off["tempo"]
    assert all(r["play"] for r in on["rows"]) and on["tempo"]


@in_chromium
def test_on_a_laptop_the_harmony_panel_is_a_rail_and_the_keys_neck_stays_in_the_rail_of_necks(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        open_harmony(b)
        seen = b.js(HARMONY)
        client = look(b)["client"]
        b.click("#more")  # the settings in its place
        swapped = b.js("[document.getElementById('harmony').hidden, document.getElementById('panel').hidden]")
    assert seen["box"]["right"] == client and seen["box"]["top"] == 0 and seen["box"]["left"] == client - 360
    assert not seen["neck"] and seen["page"] <= 1280
    assert swapped == [True, False]


@in_chromium
def test_a_section_tapped_in_the_panel_comes_into_view(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG + "".join(f"{{comment: Outro {n}}}\n[C]la [G]la\n" for n in range(30)))) as b:
        open_harmony(b)
        b.js("document.querySelectorAll('#harmony .prog-go')[2].click()")  # the bridge
        assert b.wait("Math.abs(document.querySelectorAll('#sheet section.sec')[3].getBoundingClientRect().top) < 40")
        still = b.js("!document.getElementById('harmony').hidden")
    assert still


@in_chromium
def test_with_numerals_on_a_sections_heading_names_its_progression(tmp_path):
    heads = "[...document.querySelectorAll('#sheet h2.lbl')].map((h) => h.textContent)"
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        plain = b.js(heads)
    with viewer(tmp_path, written(tmp_path, SONG, name="Numbered") + "#nm=both") as b:
        named = b.js(heads)
    assert plain == ["Verse", "Chorus", "Riff", "Bridge"]
    # The bridge, vi V IV V7/vi, is the Andalusian cadence read in the relative major; the chorus plays the
    # '50s progression within it.
    assert named == ["Verse · the pop progression", "Chorus · contains the '50s progression", "Riff",
                     "Bridge · the Andalusian cadence"]


@in_chromium
def test_a_sheet_with_no_headings_has_one_section_to_list(tmp_path):
    with viewer(tmp_path, written(tmp_path, UNNAMED)) as b:
        open_harmony(b)
        seen = b.js(HARMONY)
    assert [(r["section"], r["numerals"], r["repeats"], r["about"]) for r in seen["rows"]] == [
        ("Section 1", ["i", "♭VII", "♭VI", "V7"], "×2", "the Andalusian cadence · ends on a half cadence (on V)")]


# A verse that plays the pop progression twice within it, and folds round one pass that varies it; a chorus on
# the Andalusian cadence, its last pass with a chord more.
NAMED = ("{title: Named}\n{artist: Synthetic}\n{key: Am}\n"
         "{comment: Verse}\n[Dm]made [C]up [G]words [Am]to [F]sing\n[Bb]and [C]more [G]of [Am]them [F]here\n\n"
         "{comment: Chorus}\n" + "[Am]la [G]la [F]la [E7]la\n" * 3 + "[Am]la [G]la [F]la [Dm]la [E7]la\n")


@in_chromium
def test_the_panel_names_a_progression_a_section_plays_within_it_and_a_cycle_that_varies(tmp_path):
    with viewer(tmp_path, written(tmp_path, NAMED) + "#nm=numerals") as b:
        open_harmony(b)
        seen = b.js(HARMONY)
        heads = b.js("[...document.querySelectorAll('#sheet h2.lbl')].map((h) => h.textContent)")
    verse, chorus = seen["rows"]
    assert verse["numerals"] == ["iv", "♭III", "♭VII", "i", "♭VI", "♭II", "♭III", "♭VII", "i", "♭VI"]
    assert verse["about"] == "contains the pop progression ×2"
    assert verse["named"] == [["Songs with the pop progression", "../../index.html#prog=I%20V%20vi%20IV"]]
    assert chorus["numerals"] == ["i", "♭VII", "♭VI", "V7"] and chorus["repeats"] == "×4, one variation"
    assert chorus["about"] == "the Andalusian cadence · ends on a half cadence (on V)" and chorus["named"] == []
    assert heads == ["Verse · contains the pop progression ×2", "Chorus · the Andalusian cadence"]


# A verse that plays ii–V–I, then the Andalusian cadence read in C major: a link to the songs with each.
TWO = "{title: Two}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n[Dm7]a [G7]b [Cmaj7]c [Am]d [G]e [F]f [E7]g\n"


@in_chromium
def test_a_link_focused_in_the_panel_keeps_the_focus_though_the_panel_is_drawn_anew(tmp_path):
    with viewer(tmp_path, written(tmp_path, TWO)) as b:
        open_harmony(b)
        links = b.js("[...document.querySelectorAll('#harmony .prog-named')].map((a) => a.textContent)")
        b.js("document.querySelectorAll('#harmony .prog-named')[1].focus()")
        b.js("document.querySelectorAll('#volumes .chip')[1].click()")  # the panel is drawn anew
        after = b.js("[document.activeElement.textContent, document.activeElement.isConnected]")
    assert links == ["Songs with ii–V–I", "Songs with the Andalusian cadence"]
    assert after == ["Songs with the Andalusian cadence", True]  # the second link, as before, not the first


@in_chromium
def test_play_asks_the_synthesis_for_the_progression_and_marks_the_chord_playing(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.js(FAKE_SOUND)
        open_harmony(b)
        shown = b.js(HARMONY)
        b.js("document.querySelectorAll('#harmony .prog-play')[0].click()")
        asked = b.js("window.asked")
        marked = b.js("[...document.querySelectorAll('#harmony .prog')[0].querySelectorAll('.pn.on')].map((n) => n.textContent)")
        label = b.js("document.querySelectorAll('#harmony .prog-play')[0].getAttribute('aria-label')")
        b.js("window.playing.onChord(5)")
        later = b.js("[...document.querySelectorAll('#harmony .prog')[0].querySelectorAll('.pn.on')].map((n) => n.textContent)")
        shapes = b.js("""(() => { const d = JSON.parse(document.getElementById('song').textContent);
          const rep = d.chords[0]; return d.voicings[rep[3]][rep[0]][0]; })()""")
        b.click("#bpm-up")
        b.js("document.querySelectorAll('#harmony .prog-play')[0].click()")  # ■
        stopped = b.js("[window.stopped, document.querySelectorAll('#harmony .prog-play')[0].getAttribute('aria-label')]")
    assert shown["tempo"] and all(r["play"] for r in shown["rows"])
    assert asked["bpm"] == 80 and len(asked["chords"]) == 4 * 4  # a chord a bar, the cycle four times
    # with the guitar's strings and its sound (strum.js: the default tuning and voice)
    assert asked["chords"][0] == {"position": shapes, "capo": 0, "tuning": [40, 45, 50, 55, 59, 64], "voice": "guitar"}
    assert marked == ["I"] and later == ["V"] and label == "Stop"
    assert stopped == [True, "Play Verse"]


@in_chromium
@pytest.mark.skipif(not (Path(__file__).parents[1] / "src" / "caracole" / "viewer" / "strum.js").exists(),
                    reason="waits for HV3's synthesis (strum.js, window.caracoleSound)")
def test_play_strums_the_progression_with_hv3s_synthesis(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        open_harmony(b)
        b.click("#harmony .prog-play")
        assert b.wait("document.documentElement.dataset.heard !== undefined", timeout=5)
        heard = b.js("document.documentElement.dataset.heard")
        b.click("#harmony .prog-play")
    assert heard


# --- both open: Escape, and the focus ---------------------------------------------------------------------


@in_chromium
@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_escape_closes_the_one_on_top_and_the_focus_goes_back_to_its_opener(tmp_path, size):
    with viewer(tmp_path, **size) as b:
        b.js("document.querySelector('#more').focus()")
        b.press("Enter")
        settings = look(b)
        b.js("window.picked = document.querySelectorAll('#sheet .c')[2]; picked.focus()")
        b.press("Enter")  # a chord's card, over the settings
        both = look(b)
        b.press("Escape")
        card_closed = look(b)
        on_chord = b.js("document.activeElement === window.picked")
        b.press("Escape")  # the settings, from the chord: the focus stays where you are
        all_closed = look(b)
        stayed = b.js("document.activeElement === window.picked")
    assert settings["panel"] and settings["focus"] == "panel-title"
    assert both["card"] and both["panel"] and both["focus"] == "card-name" and both["cardSeen"]
    # On a phone the card covers the settings, out of sight and of the focus's way; side by side on a desktop.
    assert both["panelSeen"] is (size is DESKTOP)
    assert card_closed["card"] is None and card_closed["panelSeen"] and on_chord
    assert all_closed["panel"] is None and stayed


@in_chromium
def test_the_card_comes_after_its_chord_in_the_focus_order(tmp_path):
    with viewer(tmp_path, **DESKTOP) as b:
        b.js("window.chords = [...document.querySelectorAll('#sheet .c')]; chords[1].focus()")
        b.press("Enter")
        inside, landed = [], -1
        for _ in range(15):
            tab(b)
            landed = b.js("chords.indexOf(document.activeElement)")
            if landed >= 0 or not b.js("document.querySelector('#card').contains(document.activeElement)"):
                break
            inside.append(b.js("document.activeElement.id || document.activeElement.className"))
        b.press("Enter")  # on the next chord: the card fills with it, the focus in it again
        refilled = look(b)
        tab(b, back=True)
        back = b.js("chords.indexOf(document.activeElement)")
    assert "next" in inside and len(inside) >= 3  # its own buttons first...
    assert landed == 2  # ...then the chord after the one that opened it, not the end of the page
    assert refilled["focus"] == "card-name" and refilled["name"] == "Em"
    assert back == 2  # and back out to its chord


@in_chromium
@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_a_chip_pressed_keeps_the_focus_though_its_row_is_drawn_anew(tmp_path, size):
    # The capo's frets, the modes and the card's chords are drawn anew as one is pressed: the focus stays
    # on the one pressed, in the settings or the card, not on the page behind them.
    focused = """(() => { const a = document.activeElement, row = a && a.closest('.chips');
      return row ? [row.id, a.firstChild.textContent, a.getAttribute('aria-pressed')] : [a ? a.tagName : null]; })()"""
    with viewer(tmp_path, written(tmp_path) + "#t=1", **size) as b:  # in Ab: frets to suggest
        b.js("document.querySelector('#more').focus()")
        b.press("Enter")
        b.js("document.querySelector('#capo .chip').focus()")
        b.press("Enter")
        capo = b.js(focused)
        b.js("[...document.querySelectorAll('#modes .chip')].find((c) => c.firstChild.textContent === 'Dorian').focus()")
        b.press("Enter")
        mode = b.js(focused)
        b.js("document.querySelectorAll('#sheet .c')[0].focus()")
        b.press("Enter")  # its card
        name = b.js("document.querySelectorAll('#alts .chip')[1].firstChild.textContent")
        b.js("document.querySelectorAll('#alts .chip')[1].focus()")
        b.press("Enter")
        alt = b.js(focused)
        b.js("document.querySelector('#use').focus()")  # Play it for every one
        b.press("Enter")
        used = b.js(focused)
    assert capo == ["capo", "Capo 1", "true"]
    assert mode == ["modes", "Dorian", "true"]
    assert alt == ["alts", name, "true"]
    assert used == ["alts", name, "true"]  # Play … hides once played: the focus on the chord played


# --- in a songbook ---------------------------------------------------------------------------------------


@in_chromium
def test_a_songbook_song_has_the_rail_and_the_docked_card_too(tmp_path):
    songs = [BookSong("Long Song", "Synthetic", cho=LONG, id="aaaa"),
             BookSong("Other", "Synthetic", cho=UG_CHO, id="bbbb")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    with viewer(tmp_path, path.as_uri() + "#song-1", **DESKTOP) as b:
        b.click("#more")
        rail = look(b)
        pager = b.js("[...document.querySelectorAll('#song-1 .pager')][0].getBoundingClientRect().right")
    with viewer(tmp_path, path.as_uri() + "#song-1") as b:
        tap_at(b, *chord(b, "G")[:2])
        docked = look(b)
        b.press("Escape")
        stayed = b.js("location.hash")
    assert rail["panel"]["right"] == rail["client"] and rail["sheet"]["right"] <= rail["panel"]["left"]
    assert pager <= rail["panel"]["left"]  # Next, beside the rail too
    assert docked["card"]["bottom"] == docked["bar"]["top"] and docked["name"] == "G"
    assert stayed.startswith("#song-1")  # Escape changed no song


# --- exporting the version -------------------------------------------------------------------------


@in_chromium
def test_the_file_viewer_shows_the_command_to_export(tmp_path):
    # A page opened from the disk has no server to ask: the settings say what to run, with Copy.
    with viewer(tmp_path, written(tmp_path) + "#t=2&capo=1&fs=20") as b:
        b.js("document.querySelector('#more').click()")
        shown = b.js("""(() => {
          const q = (s) => document.querySelector(s);
          const box = (el) => { const r = el.getBoundingClientRect(); return [r.width, r.height]; };
          return {cmd: q('#export-cmd').textContent, link: q('#export').hidden, copy: box(q('#export-copy')),
                  hint: q('#export-hint').textContent,
                  cmdSeen: !q('#export-cmd').closest('[hidden]'), sideways: document.documentElement.scrollWidth > innerWidth};
        })()""")
        b.js("document.querySelector('#t-up').click()")
        moved = b.js("document.querySelector('#export-cmd').textContent")
    assert shown["cmd"] == "caracole render --song 'Synthetic - Long Song' --version 't=2&capo=1'"
    assert shown["link"] is True and shown["cmdSeen"] and not shown["sideways"]
    assert "--mine" in shown["hint"]  # and how to make it the song's own version
    assert min(shown["copy"]) >= 44
    assert moved.endswith("--version 't=3&capo=1'")  # it follows the song
