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
    assert 150 <= card["height"] <= 250  # about 200 px: most of the song stays in view
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
def test_while_the_song_scrolls_by_itself_a_card_docks_at_the_foot_under_the_pill(tmp_path):
    with viewer(tmp_path) as b:
        b.click("#scroll")
        b.click("#go")  # at once
        time.sleep(0.4)
        tap_at(b, *chord(b, "C", above=600)[:2])  # pauses it, and opens the card
        docked = look(b)
        paused = b.js("document.querySelector('#go').getAttribute('aria-label')")
        b.click("#go")  # ▶, beside the card
        again = b.js("document.querySelector('#go').getAttribute('aria-label')")
    card, pill = docked["card"], docked["pill"]
    assert docked["name"] == "C" and docked["bar"] is None and paused == "Resume"
    assert card["bottom"] == 844 and pill["bottom"] <= card["top"]  # the card at the foot, the pill above it
    assert again == "Start now" and not docked["inert"]


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
