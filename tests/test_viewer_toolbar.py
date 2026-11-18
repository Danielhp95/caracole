"""From 1200 px wide, the bar is a toolbar under the song's title (viewer.css, layers.js ``toolbar``, viewer.js,
harptab.js): its pills in the phone's order (the key between − and +, Shapes, Text, Scroll, More), in the page's flow
right after ``header.head``, so that it sticks to the window's top once the title scrolls away and never slides away;
what is brought into view comes up below it (``scroll-padding-top``); while autoscroll counts down and runs it is
asleep (``bar[data-asleep]``: out of sight, its room kept, so the song doesn't jump), the pill under it
(``--toolbar-bottom``); Aa's box and a chord's card open below it. Below 1200 px the bar is at the foot again, back
where the page wrote it, the focus kept on the control that had it. A songbook's song and a harmonica tab's page have
it too. The full-screen handle stays at the window's foot (test_viewer_full_screen.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from caracole.viewer import page
from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import CHROMIUM_MARKS
from helpers.viewer_pages import click_at, rest, viewer, written
from test_viewer_bar import LONG
from test_viewer_harptab_browser import tab, written as harmonica_written

pytestmark = CHROMIUM_MARKS  # every test opens a page in Chromium, but the last, which reads the scripts

DESKTOP = {"width": 1280, "height": 800, "mobile": False}
HERE = Path(page.HERE)
# A long title, over two lines of the header, and a Chinese one: the toolbar under either alike.
LONG_TITLE = LONG.replace("{title: Long Song}", "{title: The Long Song Whose Title Runs On and On Across Two Lines of"
                          " the Header at a Laptop's Width}")
CHINESE = "{title: 合成的歌}\n{artist: 占位乐队}\n{key: G}\n" + "".join(
    f"[G]合成的 [D]歌词只为 [Em]测试而写 [C]第{n}行\n" for n in range(120))
# Eight sections of twelve lines: a section brought into view as Harmony's go brings one.
SECTIONS = "{title: Sections}\n{artist: Synthetic}\n{key: G}\n" + "".join(
    f"{{comment: Part {s}}}\n" + "[G]Synthetic line [D]made up [Em]to fill [C]the part\n" * 12 + "\n" for s in range(8))

# The toolbar as laid out: its box, the header's over it, the page's column, the sheet under it, its buttons shown (in
# the order a keyboard reaches them), their left edges and tops, whether it is in sight, and whether it is right after
# the header (``head``: the header's selector).
TOOLBAR = """(() => { const r = (e) => e.getBoundingClientRect(), bar = document.getElementById('bar');
  const shown = [...bar.querySelectorAll('button')].filter((e) => e.getClientRects().length);
  const head = document.querySelector(HEAD);
  return {bar: r(bar).toJSON(), head: r(head).toJSON(), page: r(document.querySelector('.page')).toJSON(),
    sheet: r(document.getElementById('sheet')).toJSON(), ids: shown.map((e) => e.id),
    lefts: shown.map((e) => r(e).left), rights: shown.map((e) => r(e).right),
    tops: shown.map((e) => Math.round(r(e).top)), visible: getComputedStyle(bar).visibility,
    away: bar.classList.contains('away'), asleep: bar.hasAttribute('data-asleep'),
    after: bar.previousElementSibling === head, next: bar.nextElementSibling ? bar.nextElementSibling.id : null,
    y: scrollY, inner: innerHeight, focus: document.activeElement ? document.activeElement.id : ''}; })()"""
PAGE_HEAD = ".page > header.head"
TOOLS = ["t-down", "key-now", "t-up", "necks-toggle", "size", "scroll", "more"]


def seen(b, head: str = PAGE_HEAD) -> dict:
    return b.js(TOOLBAR.replace("HEAD", json.dumps(head)))


def frames(b, n: int = 2) -> None:
    """Until the page has drawn ``n`` frames: its scroll handlers have run."""
    b.js("new Promise((done) => { let k = %d; const f = () => (--k ? requestAnimationFrame(f) : done());"
         " requestAnimationFrame(f); })" % n)


def under_the_title(m: dict) -> None:
    """The toolbar right under the header, before the sheet, one row of its tools in order within the song's
    column."""
    bar, head = m["bar"], m["head"]
    assert m["after"], m
    assert head["bottom"] <= bar["top"] < head["bottom"] + 24, m
    assert bar["bottom"] <= m["sheet"]["top"], m
    assert m["lefts"] == sorted(m["lefts"]) and max(m["tops"]) - min(m["tops"]) <= 4, m  # one row, in order
    assert all(b >= a - 0.5 for a, b in zip(m["rights"], m["lefts"][1:])), m  # none over another
    assert m["page"]["left"] <= bar["left"] and bar["right"] <= m["page"]["right"], m  # in the song's column
    assert m["lefts"][0] >= bar["left"] and m["rights"][-1] <= bar["right"], m
    assert m["visible"] == "visible" and not m["asleep"], m


def test_from_1200_px_the_bar_is_a_toolbar_under_the_title(tmp_path):
    for name, cho in (("Long", LONG), ("Title", LONG_TITLE), ("Chinese", CHINESE)):
        with viewer(tmp_path, written(tmp_path, cho, name=name), **DESKTOP) as b:
            m = seen(b)
            lines = b.js("Math.round(document.querySelector('.head h1').getBoundingClientRect().height"
                         " / parseFloat(getComputedStyle(document.querySelector('.head h1')).lineHeight))")
        under_the_title(m)
        assert m["ids"] == TOOLS, (name, m)
        assert m["bar"]["height"] <= 56 + 0.5, (name, m)  # --toolbar's room
        if name == "Title":
            assert lines >= 2, lines  # the long title wraps, and the toolbar is under its last line


def test_once_the_title_scrolls_away_the_toolbar_sticks_to_the_top_and_never_slides(tmp_path):
    with viewer(tmp_path, written(tmp_path, LONG), **DESKTOP) as b:
        b.js("window.scrollTo(0, 1500)")
        frames(b)
        stuck = seen(b)
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=640, y=400, deltaX=0, deltaY=600)
        assert b.wait("scrollY > 1500")
        rest(b)
        frames(b)
        wheeled = seen(b)
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=640, y=400, deltaX=0, deltaY=-300)
        assert b.wait("scrollY < %d" % wheeled["y"])
        rest(b)
        frames(b)
        up = seen(b)
        b.js("window.scrollTo(0, 0)")
        frames(b)
        top = seen(b)
    for m in (stuck, wheeled, up):
        assert m["bar"]["top"] == 0 and m["visible"] == "visible" and not m["away"], m
        assert m["after"], m  # in the page's flow still
    assert wheeled["y"] > 1500
    under_the_title(top)


def test_what_is_brought_into_view_is_never_under_the_toolbar(tmp_path):
    with viewer(tmp_path, written(tmp_path, SECTIONS), **DESKTOP) as b:
        b.js("window.scrollTo(0, 1500)")
        frames(b)
        tops = []
        for n in (3, 6, 1):
            b.js(f"document.querySelectorAll('#sheet .sec')[{n}].scrollIntoView({{block: 'start'}})")
            frames(b)
            tops.append([b.js(f"document.querySelectorAll('#sheet .sec')[{n}].getBoundingClientRect().top"),
                         seen(b)["bar"]["bottom"]])
    for top, bottom in tops:
        assert bottom <= top <= bottom + 16, tops  # below the toolbar, and right below it


def test_while_autoscroll_runs_the_toolbar_keeps_its_room_and_the_pill_sits_under_it(tmp_path):
    pill = "document.getElementById('pill').getBoundingClientRect().toJSON()"
    with viewer(tmp_path, written(tmp_path, LONG), **DESKTOP) as b:
        before = seen(b)
        b.click("#scroll")
        assert b.wait("document.getElementById('pill').dataset.state === 'counting'")
        frames(b)
        counting, counting_pill = seen(b), b.js(pill)
        assert b.wait("document.getElementById('pill').dataset.state === 'running'", 10)
        b.js("window.scrollTo(0, 1500)")  # by hand: it pauses, the toolbar back
        assert b.wait("document.getElementById('pill').dataset.state === 'paused'")
        frames(b)
        paused = seen(b)
        b.click("#go")  # ▶: counting down again, the toolbar asleep at the top
        assert b.wait("document.getElementById('pill').dataset.state === 'counting'")
        frames(b)
        stuck, stuck_pill = seen(b), b.js(pill)
        b.click("#pill-end")  # ×
        frames(b)
        ended = seen(b)
    assert counting["visible"] == "hidden" and counting["asleep"], counting
    assert counting["bar"]["height"] == before["bar"]["height"] and counting["sheet"]["top"] == before["sheet"]["top"]
    assert counting["bar"]["top"] == before["bar"]["top"] and counting["after"]  # its room kept: nothing moved
    assert counting_pill["top"] >= counting["bar"]["bottom"], (counting_pill, counting)  # under it
    assert paused["visible"] == "visible" and not paused["asleep"], paused
    assert stuck["visible"] == "hidden" and stuck["bar"]["top"] == 0, stuck
    assert stuck["bar"]["bottom"] <= stuck_pill["top"] <= stuck["bar"]["bottom"] + 16, (stuck_pill, stuck)
    assert stuck_pill["right"] <= 1280 and stuck_pill["bottom"] < 200, stuck_pill  # at the top, never at the foot
    assert ended["visible"] == "visible" and not ended["asleep"], ended


def test_below_1200_px_the_bar_is_at_the_foot_again(tmp_path):
    resize = "Emulation.setDeviceMetricsOverride"
    with viewer(tmp_path, written(tmp_path, LONG), **DESKTOP) as b:
        b.js("document.getElementById('t-up').focus()")
        wide = seen(b)
        b.send(resize, width=1100, height=800, deviceScaleFactor=1, mobile=False)
        assert b.wait("innerWidth === 1100")
        frames(b)
        narrow = seen(b)
        b.send(resize, width=1280, height=800, deviceScaleFactor=1, mobile=False)
        assert b.wait("innerWidth === 1280")
        frames(b)
        again = seen(b)
    under_the_title(wide)
    assert wide["focus"] == "t-up"
    assert not narrow["after"] and narrow["next"] == "pill", narrow  # back where the page wrote it
    assert round(narrow["bar"]["bottom"]) == narrow["inner"] and narrow["focus"] == "t-up", narrow
    assert "necks-open" in narrow["ids"] and "necks-toggle" not in narrow["ids"], narrow
    under_the_title(again)
    assert again["focus"] == "t-up" and again["ids"] == TOOLS, again


def test_the_aa_box_and_a_chords_card_open_below_the_toolbar(tmp_path):
    box = "(id) => document.getElementById(id).getBoundingClientRect().toJSON()"
    with viewer(tmp_path, written(tmp_path, LONG), width=1280, height=640, mobile=False) as b:
        b.click("#size")
        assert b.wait("!document.getElementById('sizes').hidden")
        sizes = b.js(f"({box})('sizes')")
        size = b.js(f"({box})('size')")
        b.press("Escape")
        assert b.wait("document.getElementById('sizes').hidden")
        b.js("window.scrollTo(0, 1500)")
        frames(b)
        # A chord's card, its height first: open on a chord in the middle of the window and closed again.
        middle = b.js("""(() => { const all = [...document.querySelectorAll('#sheet .c')];
          const e = all.find((c) => c.getBoundingClientRect().top > innerHeight / 2);
          const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
        click_at(b, *middle)
        assert b.wait("!document.getElementById('card').hidden")
        height = b.js("document.getElementById('card').offsetHeight")
        b.press("Escape")
        assert b.wait("document.getElementById('card').hidden")
        # A chord whose card has no room under it in the window, and room above it only over the toolbar: under it,
        # never above it into the toolbar.
        bottom = seen(b)["bar"]["bottom"]
        target = bottom + height - 16  # its top in the window
        chord = b.js(f"""(() => {{ const want = {target};
          const all = [...document.querySelectorAll('#sheet .c')];
          const best = all.reduce((a, e) => Math.abs(e.getBoundingClientRect().top - want)
            < Math.abs(a.getBoundingClientRect().top - want) ? e : a);
          window.scrollBy(0, best.getBoundingClientRect().top - want);
          best.id = 'probe';
          const r = best.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2, r.top, r.bottom]; }})()""")
        frames(b)
        click_at(b, chord[0], chord[1])
        assert b.wait("!document.getElementById('card').hidden")
        frames(b)
        card = b.js(f"({box})('card')")
        stuck = seen(b)
    assert sizes["top"] >= size["bottom"], (sizes, size)  # Aa's box under Aa, not over the title
    assert stuck["bar"]["top"] == 0
    assert card["top"] >= stuck["bar"]["bottom"], (card, stuck["bar"], chord, height)  # never over the toolbar
    # No room under it, room above it in the window but only over the toolbar: the window's top alone would have put
    # it above, over the toolbar.
    assert chord[3] + 8 + height > 640 - 8 and chord[2] - 8 - height >= 8, (chord, height)


def songbook(tmp_path: Path) -> str:
    songs = [BookSong("Long Song", "Synthetic", cho=LONG, id="aaaa"),
             BookSong("Sections", "Synthetic", cho=SECTIONS, id="bbbb")]
    path = tmp_path / "Library" / "_songbooks" / "campfire" / "songbook.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    return path.as_uri()


def test_a_songbook_song_has_the_toolbar_under_its_own_title(tmp_path):
    with viewer(tmp_path, songbook(tmp_path) + "#song-1", **DESKTOP) as b:
        m = seen(b, "#song-1 > header.head")
        b.js("window.scrollTo(0, document.documentElement.scrollHeight)")
        frames(b)
        end = seen(b, "#song-1 > header.head")
    under_the_title(m)
    assert m["ids"] == TOOLS, m
    assert end["bar"]["top"] == 0 and end["visible"] == "visible", end  # stuck to the song's end


def test_a_harmonica_tabs_page_has_the_toolbar_too(tmp_path):
    with viewer(tmp_path, harmonica_written(tmp_path, tab("588_hotel-california")), **DESKTOP) as b:
        m = seen(b)
        b.js("window.scrollTo(0, 1200)")
        frames(b)
        stuck = seen(b)
        b.click("#scroll")
        assert b.wait("document.getElementById('pill').dataset.state === 'counting'")
        frames(b)
        moving = seen(b)
        pill = b.js("document.getElementById('pill').getBoundingClientRect().top")
    under_the_title(m)
    assert m["ids"] == ["h-down", "h-up", "necks-toggle", "notes", "size", "scroll"], m
    assert stuck["bar"]["top"] == 0 and stuck["visible"] == "visible" and not stuck["away"], stuck
    assert moving["visible"] == "hidden" and moving["asleep"] and moving["bar"]["top"] == 0, moving
    assert pill >= moving["bar"]["bottom"], (pill, moving)


def test_both_pages_place_the_toolbar_through_layers_js():
    layers = (HERE / "layers.js").read_text(encoding="utf-8")
    assert re.search(r"\btoolbar\b", layers.split("window.caracoleLayers = Object.freeze(")[1])
    for name in ("viewer.js", "harptab.js"):
        script = (HERE / name).read_text(encoding="utf-8")
        assert "caracoleLayers.toolbar(bar," in script, name
        for copy in ("placeBar", "toolbarEdge", "--toolbar-bottom"):
            assert copy not in script, (name, copy)
