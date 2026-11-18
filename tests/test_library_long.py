"""A long list on index.html (stage 1e of the library page's redesign), in Chromium: what is off the screen isn't laid
out. Each artist's band of 50 lines or fewer, and each run of lines or of folded artists (``div.run``: 40 a run, the
last of a sequence 8 or more, else none), has ``content-visibility: auto`` (``.cv``, library.css), with an estimate of
its height from what it holds (``--bands``, ``--lines``, ``--folds``: library.js ``render``) and library.css's heights
(``--band-h``, ``--line-h``, ``--fold-h``); the dividers, find in page, a card's menu and the laptop's placing of a
line's buttons are as they were. Most tests read tests/helpers/big_library.py's library of 600 songs."""

from __future__ import annotations

import base64
import json
import re
import struct
import zlib

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_library_page import page, put

from caracole.library_page import write_library_page
from caracole.songs import update_song

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium

RUN, RUN_MIN, BIG_GROUP = 40, 8, 50  # library.js's
PHONE = {"width": 390, "height": 844, "mobile": True}
LAPTOP = {"width": 1280, "height": 900}
SIZES = pytest.mark.parametrize("size", [PHONE, LAPTOP], ids=["390", "1280"])
FRAMES = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    """big_library's library of 600 songs, built once for the module: its index.html's address."""
    from helpers.big_library import build

    return build(tmp_path_factory.mktemp("long") / "lib", 600).resolve().as_uri()


def _open(tmp_path, url, size, *, before=None):
    try:
        b = Browser(tmp_path / "chrome", **size)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    try:
        if before:
            b.send("Page.addScriptToEvaluateOnNewDocument", source=before)
        b.open(url)
        assert b.wait("!document.body.classList.contains('drawing')", 60)
        b.js(FRAMES)
    except BaseException:
        b.close()
        raise
    return b


def _sort(b, by):
    b.js(f"(() => {{ const s = document.getElementById('sort'); s.value = {json.dumps(by)}; "
         "s.dispatchEvent(new Event('change')); })()")
    b.js(FRAMES)


def _library(conn, cfg, names):
    """Songs (artist, title), each found with its sheet: the page's address."""
    for artist, title in names:
        song = add_song(conn, artist, title)
        put(cfg, song, "sheet.html", "sheet.pdf")
        update_song(conn, song.id, status="found")
    return write_library_page(cfg.library_dir, page(conn, cfg)).as_uri()


# What the list is cut into: each band group (its lines, whether it is .cv and content-visibility: auto), each run
# (its lines, whether it is the last of its sequence of runs, .cv, auto, what it holds and its counts), the elements
# with content-visibility: auto holding fewer than two lines, and for each line in no .cv, how long its sequence is
# (its folded artist's and those beside it, or its flat list's lines).
SHAPE = r"""(() => {
  const list = document.getElementById("list");
  const auto = (e) => getComputedStyle(e).contentVisibility === "auto";
  const lines = (e) => e.querySelectorAll(".line").length;
  const out = { bands: [], runs: [], singles: [], loose: [] };
  for (const s of list.querySelectorAll("section.artist:not(.folded)")) {
    out.bands.push({ n: lines(s), cv: s.classList.contains("cv"), auto: auto(s) });
  }
  for (const r of list.querySelectorAll("div.run")) {
    const next = r.nextElementSibling;
    out.runs.push({ n: lines(r), last: !(next && next.matches("div.run")), cv: r.classList.contains("cv"), auto: auto(r),
      holds: [...new Set(Array.from(r.children, (c) => c.matches("section.artist.folded") ? "folds"
        : c.matches("article.line") ? "lines" : c.tagName))],
      counts: ["--bands", "--lines", "--folds"].map((p) => r.style.getPropertyValue(p)) });
  }
  for (const e of list.querySelectorAll("*")) if (auto(e) && lines(e) < 2) out.singles.push(e.tagName + "." + e.className);
  const folded = (s) => Boolean(s && s.matches("section.artist.folded"));
  for (const line of list.querySelectorAll(".line")) {
    if (line.closest(".cv")) continue;
    const section = line.closest("section");
    let n = lines(section);
    if (folded(section)) {
      // the folded artists in a row around it, in the groups' box (a run's are its own: none is loose)
      n = 1;
      for (let s = section.previousElementSibling; folded(s); s = s.previousElementSibling) n += 1;
      for (let s = section.nextElementSibling; folded(s); s = s.nextElementSibling) n += 1;
    }
    out.loose.push(n);
  }
  return out;
})()"""


def _check_shape(shape):
    for band in shape["bands"]:
        if band["n"] <= BIG_GROUP:
            assert band["cv"] and band["auto"], band
        else:
            assert not band["cv"] and not band["auto"], band
    for run in shape["runs"]:
        assert run["cv"] and run["auto"], run
        assert (RUN_MIN if run["last"] else 30) <= run["n"] <= 50, run
    assert shape["singles"] == [], shape["singles"]
    assert all(n < RUN_MIN for n in shape["loose"]), shape["loose"]


@SIZES
def test_groups_and_runs_skip_what_is_off_the_screen(big, tmp_path, size):
    # By artist, every band group is .cv (the big library's largest has 45 lines); by title, the lines are in runs of
    # 40. Nothing is .cv that holds one line, and no line is outside one but in a sequence too short for a run.
    b = _open(tmp_path, big, size)
    try:
        shape = b.js(SHAPE)
        assert len(shape["bands"]) > 20, shape["bands"]
        _check_shape(shape)
        _sort(b, "title")
        shape = b.js(SHAPE)
        assert len(shape["runs"]) == 600 // RUN and shape["loose"] == [], shape
        _check_shape(shape)
        assert {tuple(r["holds"]) for r in shape["runs"]} == {("lines",)}
        # A line far down is skipped (no layout), one at the top isn't.
        assert b.js("(() => { const l = [...document.querySelectorAll('#list .line')]; "
                    "return [l[0].checkVisibility({ contentVisibilityAuto: true }), "
                    "l[l.length - 1].checkVisibility({ contentVisibilityAuto: true })]; })()") == [True, False]
    finally:
        b.close()


# Each .cv's estimate (its contain-intrinsic-height's length) and its height once laid out: each made visible, then
# measured two frames on (the laptop's buttons placed again meanwhile).
ESTIMATES = r"""(async () => {
  const cvs = [...document.querySelectorAll("#list .cv")];
  const said = cvs.map((e) => getComputedStyle(e).containIntrinsicHeight);
  for (const e of cvs) e.style.contentVisibility = "visible";
  await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
  return cvs.map((e, i) => ({ said: said[i], est: parseFloat(said[i].split(" ").pop()),
    height: e.getBoundingClientRect().height, what: e.className, lines: e.querySelectorAll(".line").length }));
})()"""


@SIZES
@pytest.mark.parametrize("by", ["artist", "title"])
def test_each_estimate_is_within_a_quarter_of_its_height(big, tmp_path, size, by):
    b = _open(tmp_path, big, size)
    try:
        if by != "artist":
            _sort(b, by)
        found = b.js(ESTIMATES)
        assert len(found) > 10, found
        for cv in found:
            assert cv["said"].startswith("auto "), cv
            assert cv["est"] > 0 and abs(cv["height"] - cv["est"]) <= 0.25 * cv["height"], cv
    finally:
        b.close()


@pytest.mark.parametrize("by", ["artist", "title"])
def test_a_library_of_one_song_artists_is_runs_alone(conn, cfg, tmp_path, by):
    url = _library(conn, cfg, [(f"Artist {n:03d}", f"Song {n:03d}") for n in range(300)])
    b = _open(tmp_path, url, PHONE)
    try:
        if by != "artist":
            _sort(b, by)
        shape = b.js(SHAPE)
        assert shape["bands"] == [] and shape["loose"] == [], shape
        assert [r["n"] for r in shape["runs"]] == [40] * 7 + [20], shape["runs"]
        _check_shape(shape)
        holds = "folds" if by == "artist" else "lines"
        assert {tuple(r["holds"]) for r in shape["runs"]} == {(holds,)}, shape["runs"]
        # A run counts what it holds, as folded lines either way (1b draws a flat line as a folded one).
        assert {tuple(r["counts"]) for r in shape["runs"][:-1]} == {("", "", "40")}, shape["runs"]
        assert b.js("document.querySelectorAll('#list .run.cv .line').length") == 300
    finally:
        b.close()


def test_one_artist_of_300_songs_is_cut_into_runs_inside_its_group(conn, cfg, tmp_path):
    url = _library(conn, cfg, [("Radiohead", f"Song {n:03d}") for n in range(300)])
    b = _open(tmp_path, url, PHONE)
    try:
        shape = b.js(SHAPE)
        assert shape["bands"] == [{"n": 300, "cv": False, "auto": False}], shape["bands"]
        assert [r["n"] for r in shape["runs"]] == [40] * 7 + [20], shape["runs"]
        _check_shape(shape)
        assert {tuple(r["holds"]) for r in shape["runs"]} == {("lines",)}
        assert {tuple(r["counts"]) for r in shape["runs"][:-1]} == {("", "40", "")}, shape["runs"]
        # The runs are in the group's box of lines, under its band, which is always laid out.
        assert b.js("[...document.querySelectorAll('#list .run')].every((r) => r.parentElement.matches("
                    "'section.artist > .lines'))")
        assert b.js("document.querySelector('#list .artist-title').checkVisibility({ contentVisibilityAuto: true })")
    finally:
        b.close()


# Every line's top border and every group's: none on a line first in its group's box (under a band, or the list's
# first), none on the list's first group, a divider on every other, wherever runs cut them.
BORDERS = r"""(() => {
  const top = (e) => getComputedStyle(e).borderTopWidth;
  const lines = [...document.querySelectorAll("#list .line")].map((l) => {
    const box = l.closest(".lines");
    return [l.querySelector("h3").textContent, top(l), box.querySelector(".line") === l];
  });
  const groups = [...document.querySelectorAll("#list section.artist")].map((s, i) => [s.dataset.artist, top(s), i === 0]);
  return { lines, groups, runs: document.querySelectorAll("#list .run").length };
})()"""


@pytest.mark.parametrize("by", ["artist", "title"])
@SIZES
def test_dividers_stay_between_runs_and_groups(conn, cfg, tmp_path, by, size):
    names = [("Aa Duo", "One"), ("Aa Duo", "Two")]
    names += [(f"B {n:02d}", f"B song {n:02d}") for n in range(20)]  # folded: a run of 20
    names += [("C Big", f"C song {n:03d}") for n in range(100)]  # runs of 40, 40 and 20 in its group
    names += [(f"D {n:02d}", f"D song {n:02d}") for n in range(10)]  # folded: a run of 10
    names += [("E Duo", "Three"), ("E Duo", "Four")]
    url = _library(conn, cfg, names)
    b = _open(tmp_path, url, size)
    try:
        if by != "artist":
            _sort(b, by)
        found = b.js(BORDERS)
        assert found["runs"] == (5 if by == "artist" else 4), found["runs"]
        for title, width, first in found["lines"]:
            assert width == ("0px" if first else "1px"), (title, width, first)
        for artist, width, first in found["groups"]:
            assert width == ("0px" if first else "1px"), (artist, width, first)
        if by == "artist":
            # An open card moves none either, across two of C Big's runs: from 1200 px the line whose card is in the
            # pane keeps the divider over it; under 1200 px the line after a card open in place has none, as within a
            # run (card.css).
            runs = "document.querySelectorAll('#list .lines > .run')"
            first, last = f"{runs}[1].querySelector('.line')", f"{runs}[0].querySelector('.line:last-child')"
            opened = first if size is LAPTOP else last
            b.js(f"{opened}.querySelector('.line-more').click()")
            assert b.wait(f"{opened}.querySelector('.line-more').getAttribute('aria-expanded') === 'true'")
            if size is LAPTOP:
                assert b.wait(f"{first}.classList.contains('selected')")
            assert b.js(f"getComputedStyle({first}).borderTopWidth") == ("1px" if size is LAPTOP else "0px")
            # A removed song's line that keeps its open card's box (card-gone) has its run laid out whole, as an open
            # card's, so that its shadow isn't cut at the run's sides.
            seen = f"getComputedStyle({runs}[2]).contentVisibility"
            assert b.js(seen) == "auto"
            b.js(f"{runs}[2].querySelector('.line').classList.add('card-gone')")
            assert b.js(seen) == "visible"
    finally:
        b.close()


def test_find_in_page_finds_a_song_off_the_screen(big, tmp_path):
    b = _open(tmp_path, big, PHONE)
    try:
        last = b.js("(() => { const l = [...document.querySelectorAll('#list .cv .line')].pop(); "
                    "return [l.querySelector('h3').textContent, l.checkVisibility({ contentVisibilityAuto: true })]; })()")
        assert last[1] is False, last  # skipped: not laid out
        assert b.js(f"window.find({json.dumps(last[0])})") is True
        assert b.wait("[...document.querySelectorAll('#list .cv .line')].pop().checkVisibility({ contentVisibilityAuto: true })")
    finally:
        b.close()


# The page's scroll once it has stood still for 20 frames: a smooth scroll over, and anything after it.
SETTLED = """new Promise((done) => { let last = -1, still = 0;
  const step = () => { if (scrollY === last) still += 1; else { still = 0; last = scrollY; }
    if (still > 20) done(scrollY); else requestAnimationFrame(step); };
  requestAnimationFrame(step); })"""
# The page's scroll each frame from now on (window.__trace), and how many frames there were at the first scrollend
# (window.__ended); window.__tracing = false stops it.
TRACE = """(() => { window.__trace = []; window.__ended = -1; window.__tracing = true;
  const tick = () => { window.__trace.push(Math.round(scrollY)); if (window.__tracing) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  addEventListener("scrollend", () => { if (window.__ended < 0) window.__ended = window.__trace.length; }, { once: true });
})()"""
JUMP_TO = "[...document.querySelectorAll('#jump button')].find((x) => x.textContent === {}).click()"


@SIZES
@pytest.mark.parametrize("by", ["artist", "title"])
def test_the_a_to_z_strip_lands_where_it_aims_however_far(big, tmp_path, size, by):
    # A smooth scroll's end is set as it starts, while the runs it passes are as tall as their estimates: laid out on
    # the way, they would make a long jump land off its group or line (under the bar, or short of it). It lands where an
    # instant jump does, the rest of the way a smooth scroll too, never a snap.
    b = _open(tmp_path, big, size)
    try:
        if by != "artist":
            _sort(b, by)
        letters = b.js("[...document.querySelectorAll('#jump button')].map((x) => x.textContent)")
        assert len(letters) > 10, letters
        for letter in (letters[len(letters) * 2 // 3], letters[2], letters[-4]):  # far down, back up, down again
            b.js(TRACE)
            b.js(JUMP_TO.format(json.dumps(letter)))
            landed = b.js(SETTLED)
            b.js("window.__tracing = false")
            trace, ended = b.js("window.__trace"), b.js("window.__ended")
            assert ended > 0, (letter, trace)
            at_end, rest = trace[ended - 1], trace[ended:]
            if abs(landed - at_end) > 2:  # set right after the scroll's end: through frames between, not at once
                between = [y for y in rest if min(at_end, landed) + 1 < y < max(at_end, landed) - 1]
                assert between, (letter, at_end, landed, rest[:12])
            assert b.js("document.activeElement.matches('#list section.artist, #list .line')"), letter
            b.js("document.activeElement.scrollIntoView({ block: 'start' })")  # where an instant jump puts it
            assert abs(b.js(SETTLED) - landed) <= 1, (letter, landed, b.js("scrollY"))
    finally:
        b.close()


def test_a_jump_that_doesnt_move_leaves_no_landing_behind(big, tmp_path):
    # The same letter twice: the second jump has nowhere to go and no scroll ends, so nothing waits for one; the page's
    # next scroll, a script's with no key, press or wheel, ends where it was going.
    b = _open(tmp_path, big, PHONE)
    try:
        _sort(b, "title")
        letters = b.js("[...document.querySelectorAll('#jump button')].map((x) => x.textContent)")
        letter = json.dumps(letters[len(letters) // 2])
        b.js(JUMP_TO.format(letter))
        first = b.js(SETTLED)
        b.js(JUMP_TO.format(letter))
        assert b.js(SETTLED) == first
        b.js("scrollTo({ top: 200, behavior: 'smooth' })")
        assert b.js(SETTLED) == 200
    finally:
        b.close()


# --- a focused line's ring ------------------------------------------------------------------------------------------


def _png_rgb(data: bytes) -> list[list[tuple[int, int, int]]]:
    """A screenshot's pixels, row by row: an 8-bit RGB or RGBA PNG, not interlaced, any filter."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    at, idat, width, height, step = 8, b"", 0, 0, 3
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        body = data[at + 8:at + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and colour in (2, 6), (depth, colour)
            step = 4 if colour == 6 else 3
        elif kind == b"IDAT":
            idat += body
        at += 12 + length
    raw, stride, rows, above, i = zlib.decompress(idat), width * step, [], bytearray(width * step), 0
    for _ in range(height):
        kind, line, i = raw[i], bytearray(raw[i + 1:i + 1 + stride]), i + 1 + stride
        for x in range(stride):
            a, b, c = line[x - step] if x >= step else 0, above[x], above[x - step] if x >= step else 0
            if kind == 1:
                line[x] = (line[x] + a) & 255
            elif kind == 2:
                line[x] = (line[x] + b) & 255
            elif kind == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x:x + 3]) for x in range(0, stride, step)])
        above = line
    return rows


def test_a_focused_lines_ring_shows_on_all_four_sides(big, tmp_path):
    # A run's containment clips what is painted outside it, and a focused line's ring is drawn 2 to 5 px outside the
    # line, which fills the run's width: the last line of a run and the first of the next, each focused from the
    # keyboard, show the whole ring, its sides and its top and bottom at the runs' edges.
    b = _open(tmp_path, big, PHONE)
    try:
        _sort(b, "title")
        b.press("Tab")  # the keyboard's: a focus the page gives a line is :focus-visible
        for index in (RUN - 1, RUN):
            line = f"document.querySelectorAll('#list .line')[{index}]"
            b.js(f"{line}.focus(); {line}.scrollIntoView({{ block: 'center' }})")
            b.js(FRAMES)
            box = b.js(f"""(() => {{ const l = {line}, r = l.getBoundingClientRect(), c = getComputedStyle(l);
              return {{ visible: l.matches(':focus-visible'), ring: c.outlineColor, width: c.outlineWidth,
                left: r.left, right: r.right, top: r.top, bottom: r.bottom }}; }})()""")
            assert box["visible"] and box["width"] == "3px", box
            ring = tuple(int(n) for n in re.findall(r"\d+", box["ring"])[:3])
            shot = _png_rgb(base64.b64decode(b.send("Page.captureScreenshot", format="png")["data"]))
            middle_x, middle_y = int((box["left"] + box["right"]) / 2), int((box["top"] + box["bottom"]) / 2)
            sides = {"left": shot[middle_y][int(box["left"]) - 4], "right": shot[middle_y][int(box["right"]) + 3],
                     "top": shot[int(box["top"]) - 4][middle_x], "bottom": shot[int(box["bottom"]) + 3][middle_x]}
            for side, pixel in sides.items():
                assert all(abs(p - q) <= 12 for p, q in zip(pixel, ring)), (index, side, pixel, ring, box)
    finally:
        b.close()


# --- the laptop's buttons placed before the frame is painted ------------------------------------------------------

# Before the page's scripts: the list beside the pane narrowed to 520 px (a stylesheet the document adopts, which the
# page's policy doesn't govern), so that a line's two or three icon tiles don't fit beside its title and its artist and
# go under its title, as six beside a long name do in the list's own 760 px (test_library_card_place.py): the long
# list then holds lines placePlays puts under their title, on the screen and far down.
NARROW = r"""(() => {
  const sheet = new CSSStyleSheet();
  sheet.replaceSync("@media (min-width: 1200px) { "
    + ".lib-cols { grid-template-columns: minmax(0, 520px) minmax(400px, 1fr); } }");
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
})();"""

# Before the page's scripts: each draw of the list (``drawn``, the frame it came in), and each line its buttons were
# put under its title for (``under``: the frame, and whether the line was on the screen then).
PLACED_LATE = r"""(() => {
  window.__placed = []; let frame = 0;
  const tick = () => { frame += 1; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  new MutationObserver((changes) => { for (const m of changes) {
    if (m.type === "childList" && m.target.id === "list" && m.addedNodes.length) window.__placed.push(["drawn", frame]);
    if (m.type === "attributes" && m.target.classList.contains("plays-under") && !(m.oldValue || "").includes("plays-under")) {
      const r = m.target.getBoundingClientRect();
      window.__placed.push(["under", frame, r.top < innerHeight && r.bottom > 0]);
    } } }).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"],
                               attributeOldValue: true });
})();"""


def _placed_late(log):
    """The lines on the screen placed in a frame after the one the list was last drawn in."""
    late, drawn = [], None
    for event in log:
        if event[0] == "drawn":
            drawn = event[1]
        elif event[2] and drawn is not None and event[1] > drawn:
            late.append(event)
    return late


def test_lines_on_the_screen_are_placed_before_their_first_frame(big, tmp_path):
    # From 1200 px, the lines a draw of the list puts on the screen have their buttons where they go in the frame that
    # first shows them, at the page's load and after a search alike; their runs, on the screen, are laid out for it.
    # The list narrowed (NARROW), so that some of them go under their title.
    b = _open(tmp_path, big.replace("index.html", "index.html#sort=title"), LAPTOP, before=NARROW + PLACED_LATE)
    try:
        b.js(FRAMES)
        log = b.js("window.__placed")
        assert any(e[0] == "under" and e[2] for e in log), log  # some of them go under their title
        assert _placed_late(log) == [], log
        b.js("document.getElementById('q').focus(); window.__placed = []")
        b.type("e")
        b.js(SETTLED)
        log = b.js("window.__placed")
        assert any(e[0] == "drawn" for e in log), log
        assert _placed_late(log) == [], log
    finally:
        b.close()


# --- a card's menu, at a run's top (served) ------------------------------------------------------------------------

from test_web_page import FakeCaracole, serve  # noqa: E402,F401  (serve: a fixture)


def test_a_cards_menu_at_a_runs_top_is_not_cut(serve, cfg, conn, tmp_path):  # noqa: F811
    # On a phone a card opens in place, inside its line's run; the "⋯" menu of a card with no tiles (info.json, then
    # Remove) rises above the card and its line, past the run's top, where the run's containment would cut it. A run
    # that holds an open card is laid out whole: each of the menu's items, and its top edge, is where it shows.
    for n in range(50):  # one-song artists, folded into runs of 40 and 10, none with a file to play
        put(cfg, add_song(conn, f"Artist {n:03d}", f"Song {n:03d}"), "info.json")
    url = serve(FakeCaracole(cfg), "(() => {})();\n")
    try:
        b = Browser(tmp_path / "chrome", **PHONE)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    run = "document.querySelectorAll('#list .run')[1]"
    line = f"{run}.querySelector('.line')"
    card = f"document.getElementById({line}.querySelector('.line-more').getAttribute('aria-controls'))"
    seen = f"getComputedStyle({run}).contentVisibility"
    try:
        b.open(url)
        assert b.wait("document.querySelectorAll('#list .run').length === 2")
        assert b.js(seen) == "auto"
        b.js(f"{line}.scrollIntoView({{ block: 'center' }})")
        b.js(f"{line}.querySelector('.line-more').click()")
        assert b.wait(f"Boolean({card} && !{card}.hidden && {card}.querySelector('.foot-more'))")
        assert b.js(f"{card}.querySelector('.tile') === null")
        b.js(f"{card}.querySelector('.foot-more').open = true")
        b.js(FRAMES)
        where = b.js(f"""(() => {{ const menu = {card}.querySelector('.foot-menu'), box = menu.getBoundingClientRect();
          const at = (item, x, y) => {{ const hit = document.elementFromPoint(x, y);
            return [y > 0 && y < innerHeight, Boolean(hit && item.contains(hit)), hit ? hit.tagName + '.' + hit.className : null]; }};
          return {{ above: box.top < {run}.getBoundingClientRect().top, edge: at(menu, box.left + box.width / 2, box.top + 1),
            items: [...menu.querySelectorAll('a, button')].map((item) => {{ const r = item.getBoundingClientRect();
              return [item.textContent.trim(), ...at(item, r.left + r.width / 2, r.top + r.height / 2)]; }}) }}; }})()""")
        assert b.js(seen) == "visible"
        assert where["above"], where  # past the run's top: its containment would cut it
        assert where["edge"][:2] == [True, True], where
        assert [item[0] for item in where["items"]] == ["info.json", "Remove"], where
        for item in where["items"]:
            assert item[1:3] == [True, True], where
        b.js(f"{line}.querySelector('.line-more').click()")  # closed: the run is skipped off the screen again
        assert b.wait(f"{seen} === 'auto'")
    finally:
        b.close()


# --- the laptop's buttons placed where a run shows --------------------------------------------------------------

# Before the page's scripts: each read of a layout inside a run the browser skips (getBoundingClientRect,
# getClientRects) that is off the screen counted, as it lays the run out for that read. (A run on the screen that a
# draw of the list has just made is skipped until the next frame lays it out: its lines are read, as they would be.)
FORCED = r"""(() => {
  window.__forced = [];
  const box = Element.prototype.getBoundingClientRect;
  for (const name of ["getBoundingClientRect", "getClientRects"]) {
    const real = Element.prototype[name];
    Element.prototype[name] = function () {
      const cv = this.closest && this.closest(".cv");
      if (cv && cv !== this && this.checkVisibility() && !this.checkVisibility({ contentVisibilityAuto: true })) {
        const at = box.call(cv);
        if (at.bottom <= 0 || at.top >= innerHeight) window.__forced.push(this.tagName + "." + this.className);
      }
      return real.call(this);
    };
  }
})();"""

# The last run's lines: whether each is laid out, whether its buttons are under its title, and whether they would wrap
# on one row (library.js placePlays's rule), read with its class taken off and put back.
LAST_RUN = r"""(() => {
  const runs = document.querySelectorAll("#list .run");
  return [...runs[runs.length - 1].querySelectorAll(".line")].map((line) => {
    const shown = line.checkVisibility({ contentVisibilityAuto: true });
    const under = line.classList.contains("plays-under");
    let wraps = null;
    if (shown) {
      line.classList.remove("plays-under");
      const chips = line.querySelectorAll(":scope > .line-title > .line-plays > .play");
      wraps = chips.length > 1 && chips[chips.length - 1].getBoundingClientRect().top
        > chips[0].getBoundingClientRect().top + 1;
      if (under) line.classList.add("plays-under");
    }
    return { title: line.querySelector("h3").textContent, shown, under, wraps };
  });
})()"""


def test_a_line_far_down_is_placed_once_its_run_shows_and_no_skipped_run_is_laid_out(big, tmp_path):
    # From 1200 px a folded or flat line's buttons go under its title where they don't fit beside it (placePlays):
    # measured for the lines on the screen alone, never by laying out a run the browser skips; a line far down is
    # placed as its run comes on the screen. The list narrowed (NARROW), so that some of them go under their title.
    b = _open(tmp_path, big, LAPTOP, before=NARROW + FORCED)
    try:
        _sort(b, "title")  # flat lines, in runs
        assert b.js("window.__forced") == []
        before = b.js(LAST_RUN)
        assert not any(line["shown"] or line["under"] for line in before), before  # skipped, never placed
        b.js("scrollTo(0, document.scrollingElement.scrollHeight)")
        assert b.wait("(() => { const runs = document.querySelectorAll('#list .run'); const l = runs[runs.length - 1]"
                      ".querySelector('.line'); return l.checkVisibility({ contentVisibilityAuto: true }); })()")
        forced = b.js("window.__forced")
        assert b.wait(f"{LAST_RUN}.every((l) => !l.shown || l.under === l.wraps)", 10), b.js(LAST_RUN)
        after = b.js(LAST_RUN)
        assert any(line["under"] for line in after), after  # some of them under their title
        assert forced == [] and b.js("window.__forced") == [], forced
    finally:
        b.close()


# --- no action reads the layout of more lines when the library grows ---------------------------------------------

# Before the page's scripts: each layout read of an element inside #list (getBoundingClientRect, getClientRects,
# checkVisibility, getComputedStyle, the offset*, client* and scroll* getters) counted, by the action in hand.
READS = r"""(() => {
  window.__reads = 0;
  const inList = (e) => e && e.nodeType === 1 && e.closest && e.closest("#list") !== null;
  for (const name of ["getBoundingClientRect", "getClientRects", "checkVisibility"]) {
    const real = Element.prototype[name];
    Element.prototype[name] = function () { if (inList(this)) window.__reads += 1; return real.apply(this, arguments); };
  }
  const style = window.getComputedStyle;
  window.getComputedStyle = function (e) { if (inList(e)) window.__reads += 1; return style.apply(this, arguments); };
  const getters = [];
  for (const proto of [Element.prototype, HTMLElement.prototype]) {
    for (const name of Object.getOwnPropertyNames(proto)) {
      if (!/^(offset|client|scroll)(Width|Height|Top|Left)$/.test(name)) continue;
      const d = Object.getOwnPropertyDescriptor(proto, name);
      if (!d || !d.get) continue;
      Object.defineProperty(proto, name, { ...d, get() { if (inList(this)) window.__reads += 1; return d.get.call(this); } });
    }
  }
})();"""


def _reads_per_action(tmp_path, url):
    b = _open(tmp_path, url, PHONE, before=READS)
    counts = {}
    try:
        counts["load"] = b.js("window.__reads")

        def action(name, run):
            b.js("window.__reads = 0")
            run()
            b.js(FRAMES)
            b.js(FRAMES)
            counts[name] = b.js("window.__reads")

        def type_ra():
            b.js("document.querySelector('#q').focus()")
            b.type("ra")
            assert b.wait("document.querySelector('#q').value === 'ra'")

        def open_card():
            b.js("document.querySelector('#q').blur()")
            b.js("scrollTo(0, 0)")
            assert b.wait("document.querySelector('#list article.line > .line-more') !== null")
            b.js("document.querySelector('#list article.line > .line-more').click()")

        def clear():
            b.js("(() => { const q = document.querySelector('#q'); q.value = ''; "
                 "q.dispatchEvent(new Event('input', { bubbles: true })); })()")

        action("type ra", type_ra)
        action("open a card", open_card)
        action("clear the box", clear)
        action("scroll to the end", lambda: b.js("scrollTo(0, document.scrollingElement.scrollHeight)"))
    finally:
        b.close()
    return counts


def test_no_action_reads_the_layout_of_more_lines_with_more_songs(tmp_path_factory):
    from helpers.big_library import build

    counts = {}
    for songs in (200, 2000):
        url = build(tmp_path_factory.mktemp(f"reads{songs}") / "lib", songs).resolve().as_uri()
        counts[songs] = _reads_per_action(tmp_path_factory.mktemp(f"chrome{songs}"), url)
    print(counts)
    for action, few in counts[200].items():
        many = counts[2000][action]
        assert few <= 12 and many <= 12, (action, counts)
        assert abs(many - few) <= 2, (action, counts)
