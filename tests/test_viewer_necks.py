"""The sheet viewer's rail of necks: from 1200 px wide, a guitar neck per chord of the song on the left,
every position of the chord drawn on it in its own colour, with a legend; picking one makes it the shape
the strip and the chord's card show (viewer.js ``drawNecks``, ``neck``; viewer.css).

The tests open a viewer in a Chromium of their own (helpers/viewer_pages.py) and read the rail back.
"""

from __future__ import annotations

import http.server
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from caracole.viewer import build_viewer, viewer_csp
from caracole.viewer.book import BookSong, build_songbook, songbook_csp
from caracole.viewer.voicings import load_voicings

from helpers.browser import CHROMIUM_MARKS, Browser
from helpers.targets import small_targets
from helpers.viewer_pages import click_at, key, viewer as open_viewer, written

pytestmark = CHROMIUM_MARKS

LEGEND = (Path(__file__).parent / "fixtures" / "chordpro" / "legend_sheet.cho").read_text(encoding="utf-8")
LEGEND_CHORDS = ["Em7", "G", "A7sus4", "Cadd9", "Dsus4", "Dsus4/F#"]  # in the order they first come
DB = load_voicings()
G_POSITIONS = [["320033", "000000", 1, []], *DB[""][7]]  # the tab's own G, then chords-db's
# A# and Bb are one chord by two names: as written, two; transposed, both are B. N.C. is no chord to play.
TWINS = "{title: Twins}\n{artist: Synthetic}\n{key: Bb}\n{comment: Verse}\n[A#]Made up [Bb]words [F]here [N.C.]now\n"
MANY = ["G", "D", "Em", "C", "Am", "F", "Bm", "E", "A", "Dm", "B7", "G7", "Cmaj7", "Fmaj7"]
MANY_CHO = "{title: Many Chords}\n{artist: Synthetic}\n{key: G}\n" + "".join(
    f"{{comment: Verse {n}}}\n" + "".join(f"[{c}]made up " for c in MANY[:7]) + "\n"
    + "".join(f"[{c}]words " for c in MANY[7:]) + "\n\n" for n in range(1, 13))
# Chords whose shapes sit where another of theirs does: F's two at fret 1, Em7's three open ones.
SAME_PLACES = "{title: Same Places}\n{artist: Synthetic}\n{comment: Verse}\n[F]made [Em7]up [Am7]words [A7]here\n"
DESKTOP = {"width": 1280, "height": 800, "mobile": False}

# What the page shows: the rail, the sheet, the bar, the settings and the card (None: not shown), each
# of the rail's chords (its name, its neck's label, its legend, the position checked, its dots as
# [position, fret, kind]), and the sheet's chords as it names them, each once, in order.
RAIL = """(() => {
  const box = (el) => {
    if (!el || !el.getClientRects().length) return null;
    const r = el.getBoundingClientRect();
    return {top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), right: Math.round(r.right),
            width: Math.round(r.width), height: Math.round(r.height)};
  };
  const q = (s) => document.querySelector(s);
  const rail = q('#necks');
  return {
    rail: box(rail), sheet: box(q('#sheet')), bar: box(q('#bar')), panel: box(q('#panel')), card: box(q('#card')),
    chords: rail ? [...rail.querySelectorAll('.nk')].map((g) => {
      const svg = g.querySelector('svg.neck');
      const radios = [...g.querySelectorAll('[role=radio]')];
      return {name: g.querySelector('.nk-name').textContent, label: svg ? svg.getAttribute('aria-label') : null,
              legend: radios.map((r) => r.textContent),
              checked: radios.findIndex((r) => r.getAttribute('aria-checked') === 'true'),
              dots: svg ? [...svg.querySelectorAll('circle[data-p]')].map((c) => [Number(c.dataset.p),
                Number(c.dataset.fret), c.classList.contains('nk-open') ? 'open' : 'dot']) : []};
    }) : [],
    sheetChords: [...new Set([...document.querySelectorAll('#sheet .c')].map((c) => c.textContent))],
    at: new URLSearchParams(location.hash.slice(1)).get('at'),
    sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    client: document.documentElement.clientWidth, padding: getComputedStyle(document.body).paddingLeft,
  };
})()"""
# A diagram as the strip or the card draws it: its dots as [string, fret], its open strings, its first fret.
DIAGRAM = """((svg) => svg && {
  dots: [...svg.querySelectorAll('.dg-dot')].map((c) => [Math.round((c.getAttribute('cx') - 16) / 10),
    Math.round((c.getAttribute('cy') - 16) / 13 + 0.5)]),
  open: [...svg.querySelectorAll('.dg-open')].map((c) => Math.round((c.getAttribute('cx') - 16) / 10)),
  fret: svg.querySelector('.dg-fret') ? svg.querySelector('.dg-fret').textContent : null,
})(document.querySelector(%r))"""
# The middle of a dot of chord group ``g``'s position ``p`` at a note (a string and a fret) no other position plays.
LONE_DOT = """(() => {
  const svg = document.querySelectorAll('#necks .nk')[%d].querySelector('svg.neck');
  const all = [...svg.querySelectorAll('circle.nk-dot')];
  const at = (c) => c.getAttribute('cy') + ',' + c.dataset.fret;
  const lone = all.find((c) => Number(c.dataset.p) === %d && all.filter((o) => at(o) === at(c)).length === 1);
  const r = lone.getBoundingClientRect();
  return [r.left + r.width / 2, r.top + r.height / 2];
})()"""


# Chords whose positions share notes: G's five (with the tab's own) three at a time on its low and high 3rd
# frets, two on its open D and G strings; F's two at fret 1, by the nut; Am/E's four on its open low E and on
# the D string's 2nd fret; Em7's three open ones on its open strings.
SHARED = ("{title: Shared Notes}\n{artist: Synthetic}\n{comment: Verse}\n{define: G base-fret 1 frets 3 2 0 0 3 3}\n"
          "[G]made [F]up [Am/E]words [Em7]here\n")
# Every dot of every neck, as drawn: its position, string (0 the low E), fret, centre, radius, outline's
# width and classes; each neck's frets' x (0 the nut's right edge), the nut's left edge and the viewBox's left.
# Each neck scrolled into the rail's view first (below the key's neck, the last ones are past its foot), and
# the rail scrolled back after.
NECK_DOTS = """(() => { const rail = document.getElementById('necks'), was = rail.scrollTop;
const seen = [...rail.querySelectorAll('.nk')].map((g) => {
  g.scrollIntoView({block: 'center', behavior: 'instant'});
  const svg = g.querySelector('svg.neck'), n = (el, a) => Number(el.getAttribute(a));
  const nut = svg.querySelector('.nk-nut');
  return {name: g.querySelector('.nk-name').textContent,
    box: svg.getAttribute('viewBox').split(' ').map(Number),
    nut: [n(nut, 'x'), n(nut, 'x') + n(nut, 'width')],
    frets: [...svg.querySelectorAll('.nk-fret')].map((l) => n(l, 'x1')),
    fretWidth: parseFloat(getComputedStyle(svg.querySelector('.nk-fret')).strokeWidth),
    dots: [...svg.querySelectorAll('circle[data-p]')].map((c) => {
      const r = c.getBoundingClientRect();
      return {p: Number(c.dataset.p), fret: Number(c.dataset.fret), string: 5 - Math.round((n(c, 'cy') - 9) / 9),
        cx: n(c, 'cx'), cy: n(c, 'cy'), r: n(c, 'r'), stroke: parseFloat(getComputedStyle(c).strokeWidth),
        open: c.classList.contains('nk-open'), chosen: c.classList.contains('chosen'), tabs: c.classList.contains('tabs'),
        // the element at the dot's middle on the screen: none other covers it
        top: c.classList.contains('nk-dot') && document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === c};
    })};
});
rail.scrollTop = was;
return seen; })()"""


def notes(position) -> list[tuple[int, int]]:
    """The notes a position plays, (string, absolute fret), the low E first: 0 for an open string."""
    frets, base = position[0], position[2]
    return [(s, 0 if f == "0" else int(f) + base - 1) for s, f in enumerate(frets) if f != "x"]


def absolute(position) -> set[tuple[int, str]]:
    """The (fret, kind) a position draws: absolute frets of its fingered strings, 0 for an open one."""
    frets, base = position[0], position[2]
    out = set()
    for f in frets:
        if f == "x":
            continue
        n = int(f)
        out.add((0, "open") if n == 0 else (n + base - 1, "dot"))
    return out


def diagram(position) -> dict:
    """What a diagram of ``position`` draws (``DIAGRAM``)."""
    frets, base = position[0], position[2]
    return {"dots": [[s, int(f)] for s, f in enumerate(frets) if f not in "x0"],
            "open": [s for s, f in enumerate(frets) if f == "0"], "fret": f"{base}fr" if base > 1 else None}


def positions_label(name: str, n: int) -> str:
    return f"{name}: {n} position{'' if n == 1 else 's'}"


def reload(b: Browser) -> None:
    b.js("window.before = true")
    b.send("Page.reload")
    assert b.wait("!window.before && document.documentElement.dataset.ready === '1'")


def reopen(b: Browser, url: str) -> None:
    """The page opened again at ``url``, as from the library: a new load, in the same browser."""
    b.send("Page.navigate", url="about:blank")
    assert b.wait("location.href === 'about:blank'")
    b.open(url)
    assert b.wait("document.documentElement.dataset.ready === '1'")


@contextmanager
def served(pages: dict[str, tuple[str, object]]) -> Iterator[str]:
    """Each of ``pages`` (its path: its HTML and the function that makes its policy) served with its own policy
    in its sandbox, as caracole serve serves it: an origin of its own, and no storage. The server's address."""
    bodies = {path: (html.encode("utf-8"), csp) for path, (html, csp) in pages.items()}

    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body, csp = bodies[self.path.split("#")[0]]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", csp(body))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


# Whether the page has storage: in its sandbox, localStorage throws.
STORAGE = "(() => { try { localStorage.getItem('x'); return true; } catch (err) { return false; } })()"


def to_song(b: Browser, n: int) -> None:
    """A songbook's next song, as its arrows and swipes go there: its address, which loads the page again."""
    b.js(f"window.before = true; location.hash = 'song-{n}'")
    assert b.wait("!window.before && document.documentElement?.dataset.ready === '1'")


def radio_names(b: Browser) -> list[list[str]]:
    """Each legend's radio buttons by the names Chromium gives them (its accessibility tree), legend by legend."""
    b.send("Accessibility.enable")
    names = []
    for k in range(b.js("document.querySelectorAll('#necks .nk-legend').length")):
        group = b.send("Runtime.evaluate", expression=f"document.querySelectorAll('#necks .nk-legend')[{k}]")
        nodes = b.send("Accessibility.queryAXTree", objectId=group["result"]["objectId"], role="radio")["nodes"]
        names.append([node["name"]["value"] for node in nodes])
    return names


# --- the rail ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("width", [1200, 1280])
def test_from_1200_px_a_rail_on_the_left_shows_a_neck_per_chord(tmp_path, width):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), width=width, height=800, mobile=False) as b:
        seen = b.js(RAIL)
    rail = seen["rail"]
    assert rail == {"top": 0, "bottom": 800, "left": 0, "right": 345, "width": 345, "height": 800}
    assert seen["sheet"]["left"] >= rail["right"] + 16  # the song beside it, never under it
    assert seen["bar"]["left"] == rail["right"] and seen["bar"]["right"] == seen["client"]
    assert [c["name"] for c in seen["chords"]] == LEGEND_CHORDS == seen["sheetChords"]
    g = seen["chords"][1]
    assert g["label"] == "G: 5 positions"
    assert g["legend"] == ["1 · the tab's", "2 · open", "3 · fret 3", "4 · fret 5", "5 · fret 7"]
    assert seen["chords"][0]["legend"] == ["1 · the tab's", "2 · open", "3 · fret 12", "4 · open", "5 · open"]  # Em7
    for chord in seen["chords"]:
        assert chord["label"] == positions_label(chord["name"], len(chord["legend"])), chord
        assert {p for p, *_ in chord["dots"]} == set(range(len(chord["legend"]))), chord  # each drawn
        assert chord["checked"] == 0, chord  # the shape the strip and the card start on
    assert not seen["sideways"]


@pytest.mark.parametrize("size", [{"width": 1100, "height": 800, "mobile": False},
                                  {"width": 390, "height": 844, "mobile": True}], ids=["1100", "390"])
def test_below_1200_px_there_is_no_rail(tmp_path, size):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **size) as b:
        seen = b.js(RAIL)
    assert seen["rail"] is None and seen["padding"] == "0px" and seen["bar"]["left"] == 0
    assert not seen["sideways"]


def test_the_rail_comes_and_goes_as_the_window_widens_and_narrows(tmp_path):
    shown = "!document.getElementById('necks').hidden"
    with open_viewer(tmp_path, written(tmp_path, LEGEND), width=1199, height=800, mobile=False) as b:
        narrow = b.js(RAIL)
        b.send("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=1, mobile=False)
        assert b.wait(shown)
        wide = b.js(RAIL)
        b.send("Emulation.setDeviceMetricsOverride", width=1199, height=800, deviceScaleFactor=1, mobile=False)
        assert b.wait("!(" + shown + ")")
        again = b.js(RAIL)
    assert narrow["rail"] is None and again["rail"] is None and again["padding"] == "0px"
    assert wide["rail"]["right"] == 345 and [c["name"] for c in wide["chords"]] == LEGEND_CHORDS
    assert wide["sheet"]["left"] >= 345 and again["sheet"]["left"] < 345


def test_the_rail_and_everything_in_it_is_fifteen_percent_larger_than_it_was(tmp_path):
    # The owner's ask: 15 % larger than the 300 px rail, its necks (drawn at its width), their names, the legends
    # and their buttons, and the key's neck with its switch, all of it.
    sizes = """(() => { const rail = document.getElementById('necks'), q = (s) => rail.querySelector(s);
      const px = (el, p) => parseFloat(getComputedStyle(el)[p]), w = (el) => el.getBoundingClientRect().width;
      const radio = q('.nk [role=radio]');
      return {neck: w(q('.nk svg.neck')), key: w(q('.kn svg.neck')), name: px(q('.nk-name'), 'fontSize'),
              keyName: px(q('.kn-name'), 'fontSize'), legend: px(radio, 'fontSize'),
              button: radio.getBoundingClientRect().height, swatch: w(q('.sw')),
              chip: px(q('.kn-switch .chip'), 'fontSize'), chipHeight: q('.kn-switch .chip').getBoundingClientRect().height,
              title: px(q('.nk-title'), 'fontSize')}; })()"""
    # Tall enough for the whole rail: no scroll bar takes its width from the necks.
    with open_viewer(tmp_path, written(tmp_path, IN_C), width=1280, height=1600, mobile=False) as b:
        seen = b.js(sizes)
        rail = b.js(RAIL)
        whole = b.js("(() => { const r = document.getElementById('necks'); return r.scrollHeight <= r.clientHeight; })()")
    assert whole and rail["rail"]["width"] == 345 and rail["sheet"]["left"] >= 345 + 16 and rail["bar"]["left"] == 345
    was = {"neck": 267, "key": 267, "name": 16, "keyName": 16, "legend": 12.8, "button": 44, "swatch": 10,
           "chip": 15.2, "chipHeight": 44}
    for what, size in was.items():
        assert seen[what] == pytest.approx(size * 1.15, abs=1), (what, seen)
    assert seen["title"] == pytest.approx(0.72 * 16 * 1.15, abs=0.5), seen  # the rail's own heading too


# --- showing and hiding the rail -----------------------------------------------------------------------

# The rail's toggles: the bar's (shown from 1200 px), the rail's own Hide at its top and the settings' row.
TOGGLES = """(() => { const q = (s) => document.querySelector(s), shown = (el) => Boolean(el && el.getClientRects().length);
  const button = q('#necks-toggle'), chip = q('#necks-chip');
  return {button: shown(button), pressed: button.getAttribute('aria-pressed'), named: button.getAttribute('aria-label'),
          row: !q('#necks-row').hidden, chip: chip.getAttribute('aria-pressed'), said: chip.textContent,
          hide: shown(q('#necks .nk-hide')), harmonyNeck: Boolean(q('#harmony-neck .kn')),
          necks: new URLSearchParams(location.hash.slice(1)).get('necks'), focus: document.activeElement.id,
          railNamed: q('#necks') && q('#necks').getAttribute('aria-label')}; })()"""


def toggles(b: Browser) -> dict:
    return b.js(TOGGLES)


@pytest.mark.parametrize("width", [1200, 1280])
def test_the_bars_button_hides_the_rail_and_the_song_takes_the_whole_width(tmp_path, width):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), width=width, height=800, mobile=False) as b:
        shown = [b.js(RAIL), toggles(b)]
        b.click("#necks-toggle")
        hidden = [b.js(RAIL), toggles(b)]
        b.click("#necks-toggle")
        again = [b.js(RAIL), toggles(b)]
    assert shown[0]["rail"]["width"] == 345 and shown[0]["padding"] == "345px"
    assert shown[1]["button"] and shown[1]["pressed"] == "true" and shown[1]["named"] == "Chord necks"
    assert shown[1]["hide"] and shown[1]["necks"] is None
    assert shown[1]["railNamed"] == "Chord necks"  # the rail by the name its heading and its toggles give it
    rail, said = hidden
    assert rail["rail"] is None and rail["padding"] == "0px"  # the song has the whole width
    assert rail["bar"]["left"] == 0 and rail["bar"]["right"] == rail["client"]
    assert rail["sheet"]["left"] < 345 and not rail["sideways"]
    assert said["button"] and said["pressed"] == "false" and said["necks"] == "0"  # the address keeps it
    assert again[0]["rail"]["width"] == 345 and again[1]["pressed"] == "true" and again[1]["necks"] is None
    assert [c["name"] for c in again[0]["chords"]] == LEGEND_CHORDS


def test_the_rails_own_hide_button_at_its_top_hides_it_and_the_bars_button_brings_it_back(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, MANY_CHO), **DESKTOP) as b:
        b.js("document.getElementById('necks').scrollTop = 1e6")  # far down the rail, its top stays in reach
        top = b.js("""(() => { const r = document.querySelector('#necks .nk-hide').getBoundingClientRect();
          return [Math.round(r.top), Math.round(r.left), Math.round(r.right), r.width, r.height,
                  document.querySelector('#necks .nk-hide').getAttribute('aria-label')]; })()""")
        b.click("#necks .nk-hide")
        hidden = [b.js(RAIL), toggles(b)]
        b.press("Enter")  # the focus is on the bar's button now: Enter brings the rail back
        back = [b.js(RAIL), toggles(b)]
    assert 0 <= top[0] <= 8 and top[2] <= 345 and top[3] >= 44 * 1.15 - 1 and top[4] >= 44 * 1.15 - 1
    assert top[5] == "Hide chord necks"
    assert hidden[0]["rail"] is None and hidden[1]["pressed"] == "false" and hidden[1]["focus"] == "necks-toggle"
    assert back[0]["rail"]["width"] == 345 and back[1]["pressed"] == "true"


def test_the_hide_buttons_focus_ring_is_whole_inside_the_rail(tmp_path):
    # The keyboard's ring round Hide (3 px, 2 px away from it) is clipped by nothing, the rail's top or side, at
    # the rail's top or scrolled far down it.
    ring = """(() => { const rail = document.getElementById('necks'), hide = rail.querySelector('.nk-hide');
      hide.focus();
      const s = getComputedStyle(hide), out = parseFloat(s.outlineWidth) + parseFloat(s.outlineOffset);
      const r = hide.getBoundingClientRect(), box = rail.getBoundingClientRect();
      return {visible: hide.matches(':focus-visible'), out,
              top: r.top - out - box.top, right: box.left + rail.clientLeft + rail.clientWidth - (r.right + out)}; })()"""
    with open_viewer(tmp_path, written(tmp_path, MANY_CHO), **DESKTOP) as b:
        top = b.js(ring)
        b.js("document.getElementById('necks').scrollTop = 1e6")
        down = b.js(ring)
    for seen in (top, down):
        assert seen["visible"] and seen["out"] == 5, seen
        assert seen["top"] >= 0 and seen["right"] >= 0, seen


def test_the_settings_row_and_the_bars_button_say_the_same_both_ways(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **DESKTOP) as b:
        b.click("#more")
        before = toggles(b)
        b.click("#necks-chip")
        from_row = [b.js(RAIL), toggles(b)]
        b.click("#necks-toggle")  # with the settings open: the row says so
        from_bar = [b.js(RAIL), toggles(b)]
    assert before["row"] and before["chip"] == before["pressed"] == "true" and before["said"] == "Hide"
    assert from_row[0]["rail"] is None and from_row[1]["chip"] == from_row[1]["pressed"] == "false"
    assert from_row[1]["said"] == "Show" and from_row[0]["panel"] is not None  # the settings stay open
    assert from_bar[0]["rail"]["width"] == 345 and from_bar[1]["chip"] == from_bar[1]["pressed"] == "true"
    assert from_bar[1]["said"] == "Hide"
    # The song between the two rails, or beside the settings' alone.
    assert from_row[0]["sheet"]["left"] < 345 <= from_bar[0]["sheet"]["left"]
    assert from_bar[0]["sheet"]["right"] <= from_bar[0]["panel"]["left"]


def test_the_choice_is_kept_across_a_reload_and_for_every_other_sheet(tmp_path):
    # One choice for the screen, not a song's: hidden here, it is hidden on the next sheet opened too.
    url, other = written(tmp_path, LEGEND), written(tmp_path, IN_C, name="Other")
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        b.click("#necks-toggle")
        reload(b)
        reloaded = [b.js(RAIL), toggles(b)]
        reopen(b, other)
        elsewhere = [b.js(RAIL), toggles(b)]
        b.click("#necks-toggle")
        reopen(b, url)
        shown = [b.js(RAIL), toggles(b)]
    assert reloaded[0]["rail"] is None and reloaded[1]["pressed"] == "false" and reloaded[0]["padding"] == "0px"
    assert elsewhere[0]["rail"] is None and elsewhere[1]["pressed"] == "false"
    assert shown[0]["rail"]["width"] == 345 and shown[1]["pressed"] == "true"


def test_necks_0_in_the_address_opens_the_sheet_with_the_rail_hidden(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND) + "#necks=0", **DESKTOP) as b:
        seen = [b.js(RAIL), toggles(b)]
    assert seen[0]["rail"] is None and seen[1]["pressed"] == "false" and seen[1]["necks"] == "0"


def test_served_in_its_sandbox_with_no_storage_a_reload_keeps_the_rail_hidden_by_its_address(tmp_path):
    # Served, in its sandbox, the page keeps nothing: necks=0 in the address hides the rail, as fs= keeps the size.
    sheet = "/Artist/Title/sheet.html"
    with served({sheet: (build_viewer(LEGEND), viewer_csp)}) as site, \
            open_viewer(tmp_path, site + sheet, **DESKTOP) as b:
        sandboxed = [b.js("origin"), b.js(STORAGE)]
        b.click("#necks-toggle")
        hidden = toggles(b)
        reload(b)
        reloaded = [b.js(RAIL), toggles(b)]
        b.click("#necks-toggle")
        reload(b)
        shown = [b.js(RAIL), toggles(b)]
    assert sandboxed == ["null", False]  # an origin of its own, with no storage
    assert hidden["pressed"] == "false" and hidden["necks"] == "0"
    assert reloaded[0]["rail"] is None and reloaded[1]["pressed"] == "false" and reloaded[0]["padding"] == "0px"
    assert shown[0]["rail"]["width"] == 345 and shown[1]["pressed"] == "true" and shown[1]["necks"] is None


def test_reset_everything_brings_the_rail_back(tmp_path):
    url = written(tmp_path, LEGEND)
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        b.click("#necks-toggle")
        b.click("#more")
        b.click("#reset-all")
        reset = [b.js(RAIL), toggles(b)]
        reopen(b, url)
        kept = b.js(RAIL)
    assert reset[0]["rail"]["width"] == 345 and reset[1]["pressed"] == reset[1]["chip"] == "true"
    assert reset[1]["necks"] is None and kept["rail"]["width"] == 345


def test_with_the_rail_hidden_the_harmony_panel_shows_the_keys_neck(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_C), **DESKTOP) as b:
        b.click("#more")
        b.click("#harmony-open")
        with_rail = toggles(b)
        b.click("#necks-toggle")
        without = toggles(b)
    assert not with_rail["harmonyNeck"] and without["harmonyNeck"]  # the key's neck in one place or the other


@pytest.mark.parametrize("width", [1200, 1280, 1440])
def test_no_sideways_scroll_with_the_rail_shown_or_hidden_and_the_settings_open(tmp_path, width):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), width=width, height=800, mobile=False) as b:
        shown = b.js(RAIL)
        b.click("#more")
        both = b.js(RAIL)
        b.click("#necks-toggle")
        hidden = b.js(RAIL)
    for seen in (shown, both, hidden):
        assert not seen["sideways"], seen
        assert seen["sheet"]["right"] <= (seen["panel"]["left"] if seen["panel"] else seen["client"]), seen
    assert shown["sheet"]["left"] >= 345 + 16 and both["sheet"]["width"] >= 440, both  # room for the song still


@pytest.mark.parametrize("size", [{"width": 1100, "height": 800, "mobile": False},
                                  {"width": 390, "height": 844, "mobile": True}], ids=["1100", "390"])
def test_below_1200_px_there_is_no_toggle(tmp_path, size):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **size) as b:
        b.click("#more")
        seen = toggles(b)
    assert not seen["button"] and not seen["row"] and not seen["hide"]


def test_a_sheet_without_chords_has_no_rail_and_no_toggle(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, "{title: T}\n{artist: A}\nwords alone\n"), **DESKTOP) as b:
        seen = [b.js(RAIL), toggles(b)]
    assert seen[0]["rail"] is None and not seen[1]["button"] and not seen[1]["row"]


# --- the necks ---------------------------------------------------------------------------------------


def test_a_neck_draws_every_position_at_its_frets(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **DESKTOP) as b:
        circles = b.js("""Array.from(document.querySelectorAll('#necks svg[aria-label^="G:"] circle'),
          (c) => [Number(c.dataset.p), Number(c.dataset.fret), c.getAttribute('class')])""")
    for p, position in enumerate(G_POSITIONS):
        drawn = {(fret, "open" if "open" in cls else "dot") for q, fret, cls in circles if q == p}
        assert drawn == absolute(position), position
    # the tab's own 320033 is the open D and G strings, a 2 and three 3s
    assert {f for q, f, c in circles if q == 0} == {0, 2, 3}
    assert not any(cls is None for *_, cls in circles)


def test_the_chosen_position_is_drawn_bolder(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND) + "#at=1.2", **DESKTOP) as b:
        dots = b.js("""Array.from(document.querySelectorAll('#necks svg[aria-label^="G:"] circle.nk-dot'),
          (c) => [Number(c.dataset.p), c.classList.contains('chosen')])""")
        tabs = set(b.js("""Array.from(document.querySelectorAll('#necks svg[aria-label^="G:"] circle.tabs'),
          (c) => Number(c.dataset.p))"""))
        checked = b.js(RAIL)["chords"][1]["checked"]
    assert {p for p, chosen in dots if chosen} == {2} and checked == 2
    assert tabs == {0}


def test_the_necks_follow_transposition_and_mode(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **DESKTOP) as b:
        b.click('#necks .nk:nth-of-type(2) [role=radio][data-p="2"]')  # a shape of G's...
        picked = b.js(RAIL)["at"]
        b.click("#t-up")
        up = b.js(RAIL)
        b.click("#more")
        b.js("[...document.querySelectorAll('#modes .chip')].find((c) => c.getAttribute('aria-pressed') === 'false')"
             ".click()")
        moded = b.js(RAIL)
    names = [c["name"] for c in up["chords"]]
    assert names == up["sheetChords"] and names[1] == "Ab"  # G, a semitone up
    ab = up["chords"][1]
    assert ab["label"] == positions_label("Ab", len(DB[""][8]))
    assert ab["legend"] == ["1 · fret 1", "2 · fret 4", "3 · fret 6", "4 · fret 8"]
    for p, position in enumerate(DB[""][8]):  # chords-db's Ab: the tab's own G is G's alone
        assert {(fret, kind) for q, fret, kind in ab["dots"] if q == p} == absolute(position), position
    assert picked == "1.2" and up["at"] is None and ab["checked"] == 0  # ...is G's: Ab starts at its first
    assert [c["name"] for c in moded["chords"]] == moded["sheetChords"] != names


def test_chords_shown_by_one_name_share_one_neck(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, TWINS), **DESKTOP) as b:
        as_written = b.js(RAIL)
        b.click("#t-up")
        up = b.js(RAIL)
        b.click('#necks .nk [role=radio][data-p="1"]')
        picked = b.js(RAIL)
    assert [c["name"] for c in as_written["chords"]] == ["A#", "Bb", "F"]  # and no neck for N.C.
    assert [c["name"] for c in up["chords"]] == ["B", "F#"] and up["sheetChords"] == ["B", "F#", "N.C."]
    assert picked["at"] == "0.1,1.1" and picked["chords"][0]["checked"] == 1  # both of its places


def test_every_legend_names_its_shapes_apart(tmp_path):
    # Numbered as the card counts them ("2 of 4"), so two shapes at one fret, or three open ones, are told
    # apart in words, by sight and by a screen reader, and never by their colour alone.
    with open_viewer(tmp_path, written(tmp_path, SAME_PLACES), **DESKTOP) as b:
        seen = b.js(RAIL)
        heard = radio_names(b)
    legends = [c["legend"] for c in seen["chords"]]
    assert [c["name"] for c in seen["chords"]] == ["F", "Em7", "Am7", "A7"]
    assert legends == [["1 · fret 1", "2 · fret 1", "3 · fret 3", "4 · fret 5"],
                       ["1 · open", "2 · fret 12", "3 · open", "4 · open"],
                       ["1 · open", "2 · open", "3 · fret 5", "4 · fret 5"],
                       ["1 · open", "2 · open", "3 · fret 5", "4 · fret 7"]]
    assert heard == legends  # the names a screen reader gives them: the words shown
    assert all(len(set(names)) == len(names) for names in heard)


# --- notes several positions share ------------------------------------------------------------------------


@pytest.mark.parametrize("at", ["", "#at=0.2"], ids=["first-chosen", "third-chosen"])
def test_a_note_several_positions_share_is_a_dot_for_each_side_by_side_inside_its_fret(tmp_path, at):
    with open_viewer(tmp_path, written(tmp_path, SHARED) + at, **DESKTOP) as b:
        necks = b.js(NECK_DOTS)
    assert [n["name"] for n in necks] == ["G", "F", "Am/E", "Em7"]
    expected = {"G": G_POSITIONS, "F": DB[""][5], "Am/E": DB["m/7"][9]}
    shared_seen = {}
    for neck in necks:
        dots, nut, frets = neck["dots"], neck["nut"], neck["frets"]
        half_line = neck["fretWidth"] / 2
        if neck["name"] in expected:  # every position's every note, a dot of its own
            for p, position in enumerate(expected[neck["name"]]):
                assert sorted((d["string"], d["fret"]) for d in dots if d["p"] == p) == sorted(notes(position)), (
                    neck["name"], p)
        assert all(d["tabs"] == (neck["name"] == "G" and d["p"] == 0) for d in dots)  # the tab's own, ringed
        for i, d in enumerate(dots):  # no dot's middle under another's
            for e in dots[i + 1:]:
                assert ((d["cx"] - e["cx"]) ** 2 + (d["cy"] - e["cy"]) ** 2) ** 0.5 >= max(d["r"], e["r"]), (d, e)
        assert all(d["top"] for d in dots if not d["open"]), neck["name"]
        by_note = {}
        for d in dots:
            by_note.setdefault((d["string"], d["fret"]), []).append(d)
        for (string, fret), here in by_note.items():
            here.sort(key=lambda d: d["p"])
            assert [d["cx"] for d in here] == sorted(d["cx"] for d in here)  # position 1 leftmost
            assert len({d["cy"] for d in here}) == 1  # along the string
            reach = [(d["cx"] - d["r"] - d["stroke"] / 2, d["cx"] + d["r"] + d["stroke"] / 2) for d in here]
            if fret == 0:  # left of the nut, inside the neck's picture
                assert min(lo for lo, _ in reach) >= neck["box"][0] and max(hi for _, hi in reach) <= nut[0]
            else:  # inside the fret's cell: past the nut or the fret line before, short of the one after
                lo = nut[1] if fret == 1 else frets[fret - 2] + half_line
                assert min(a for a, _ in reach) >= lo and max(z for _, z in reach) <= frets[fret - 1] - half_line
            if len(here) == 1:  # a note one position plays: as it always was
                d = here[0]
                assert d["cx"] == (7 if fret == 0 else 14 + (fret - 0.5) * 19) and d["r"] == (4.2 if d["chosen"] else 3.2)
            else:
                shared_seen.setdefault(neck["name"], set()).add((len(here), fret == 0))
                assert len({d["r"] for d in here if not d["chosen"]}) == 1
                if len(here) == 2:  # the size the owner picked: 6.4 apart, 2.9 or 3.6 for the chosen
                    assert here[1]["cx"] - here[0]["cx"] == pytest.approx(6.4)
                    assert all(d["r"] == pytest.approx(3.6 if d["chosen"] else 2.9) for d in here)
    assert shared_seen["G"] == {(2, False), (3, False), (2, True)}
    assert (2, False) in shared_seen["F"]
    assert {(4, False), (4, True)} <= shared_seen["Am/E"]
    assert (3, True) in shared_seen["Em7"]
    widened = {n["name"]: n["box"][0] < 0 for n in necks}
    assert widened == {"G": True, "F": False, "Am/E": True, "Em7": True}  # only for open strings shared


def test_a_neck_widened_for_shared_open_strings_keeps_its_frets_under_the_others(tmp_path):
    lines = """[...document.querySelectorAll('#necks .nk svg.neck')].map((svg) => {  // the key's neck aside
      const x = (el) => el.getBoundingClientRect();
      return [svg.getAttribute('viewBox').startsWith('-'), x(svg.querySelector('.nk-nut')).left,
              x([...svg.querySelectorAll('.nk-fret')].pop()).right, x(svg).left - x(svg.closest('#necks')).left];
    })"""
    with open_viewer(tmp_path, written(tmp_path, SHARED), **DESKTOP) as b:
        necks = b.js(lines)
        seen = b.js(RAIL)
    assert [wide for wide, *_ in necks] == [True, False, True, True]  # G, F, Am/E, Em7
    plain = necks[1]
    for wide, nut, last, at in necks:
        assert nut == pytest.approx(plain[1], abs=0.5) and last == pytest.approx(plain[2], abs=0.5)
        assert at >= 0  # inside the rail, in its padding at most
    assert not seen["sideways"] and seen["rail"]["width"] == 345


def test_each_dot_of_a_shared_note_plays_its_own_position(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SHARED), **DESKTOP) as b:
        for g, note in ((0, (5, 3)), (2, (3, 2))):  # G's high e at fret 3 (three shapes), Am/E's D string at fret 2 (four)
            dots = [d for d in b.js(NECK_DOTS)[g]["dots"] if (d["string"], d["fret"]) == note]
            assert len(dots) >= 3
            for d in sorted(dots, key=lambda d: -d["p"]):
                middle = b.js(f"""(() => {{ const c = [...document.querySelectorAll('#necks .nk')[{g}]
                  .querySelectorAll('circle[data-p="{d["p"]}"][data-fret="{note[1]}"]')]
                  .find((c) => Number(c.getAttribute('cy')) === {d["cy"]});
                  c.scrollIntoView({{block: 'center', behavior: 'instant'}});  // a neck past the rail's foot
                  const r = c.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")
                click_at(b, *middle)
                assert b.wait(f"document.querySelectorAll('#necks .nk')[{g}].querySelector('[aria-checked=true]')"
                              f".dataset.p === '{d['p']}'"), (g, d)


# --- picking a position --------------------------------------------------------------------------------


def test_picking_a_position_on_the_neck_makes_it_the_chords_shape_in_the_strip_and_card(tmp_path):
    strip_g = "#strip button:nth-of-type(2) svg"  # the strip has a button per chord, G the second
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **DESKTOP) as b:
        b.click("#more")
        b.click("#strip-toggle")  # every chord's shape at a glance
        b.press("Escape")
        click_at(b, *b.js(LONE_DOT % (1, 2)))  # a dot of G's third shape
        on_neck = b.js(RAIL)
        strip = b.js(DIAGRAM % strip_g)
        b.click("#strip button:nth-of-type(2)")  # its card
        card = [b.js("document.querySelector('#diagram .count').textContent"), b.js(DIAGRAM % "#diagram svg")]
        b.click('#necks .nk:nth-of-type(2) [role=radio][data-p="3"]')  # its fourth, in the legend
        in_legend = [b.js(RAIL), b.js("document.querySelector('#diagram .count').textContent"),
                     b.js(DIAGRAM % "#diagram svg"), b.js(DIAGRAM % strip_g)]
        b.click("#prev")  # the card's ‹: the rail follows it
        back = b.js(RAIL)
        reload(b)
        reloaded = [b.js(RAIL), b.js(DIAGRAM % strip_g)]
    assert on_neck["at"] == "1.2" and on_neck["chords"][1]["checked"] == 2
    assert strip == diagram(G_POSITIONS[2])
    assert card == ["3 of 5", diagram(G_POSITIONS[2])]
    rail, count, shown, strip = in_legend
    assert rail["at"] == "1.3" and rail["chords"][1]["checked"] == 3 and count == "4 of 5"
    assert shown == strip == diagram(G_POSITIONS[3])
    assert back["at"] == "1.2" and back["chords"][1]["checked"] == 2
    assert reloaded[0]["at"] == "1.2" and reloaded[0]["chords"][1]["checked"] == 2  # kept in the address
    assert reloaded[1] == diagram(G_POSITIONS[2])


def test_opened_again_the_page_keeps_the_shapes_chosen_for_the_chords_they_were_chosen_for(tmp_path):
    # From the folder the browser keeps them, as it keeps the key: opened again with no address, each
    # chord plays the shape chosen for it. An address naming another key renames the chords: theirs start
    # at their first shape, never one chosen for another chord.
    url = written(tmp_path, LEGEND)
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        b.click("#t-up")  # Em7 and G are Fm7 and Ab
        b.click('#necks .nk:nth-of-type(1) [role=radio][data-p="1"]')  # Fm7's second shape
        b.click('#necks .nk:nth-of-type(2) [role=radio][data-p="2"]')  # Ab's third
        picked = b.js(RAIL)
        reopen(b, url)
        again = [b.js(RAIL), b.js("location.hash")]
        b.click("#more")
        b.click("#strip-toggle")
        b.press("Escape")
        strip = b.js(DIAGRAM % "#strip button:nth-of-type(2) svg")
        reopen(b, url + "#t=2")
        other = b.js(RAIL)
    assert picked["at"] == "0.1,1.2" and [c["name"] for c in picked["chords"]][:2] == ["Fm7", "Ab"]
    rail, hash_ = again
    assert [c["name"] for c in rail["chords"]] == [c["name"] for c in picked["chords"]]
    assert hash_ == "#t=1&at=0.1%2C1.2" and [c["checked"] for c in rail["chords"]][:3] == [1, 2, 0]
    assert strip == diagram(DB[""][8][2])  # the strip plays it too
    assert [c["name"] for c in other["chords"]][:2] == ["F#m7", "A"]
    assert other["at"] is None and all(c["checked"] == 0 for c in other["chords"])


def test_the_keyboard_picks_a_position_with_the_arrows(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **DESKTOP) as b:
        stops = b.js("[...document.querySelectorAll('#necks .nk')].map((g) => "
                     "[...g.querySelectorAll('[role=radio]')].filter((r) => r.tabIndex === 0).length)")
        b.js("document.querySelectorAll('#necks .nk')[1].querySelector('[aria-checked=true]').focus()")
        key(b, "ArrowRight", 39)
        right = [b.js(RAIL), b.js("document.activeElement.dataset.p")]
        key(b, "ArrowLeft", 37)
        key(b, "ArrowLeft", 37)  # round to the last
        left = [b.js(RAIL), b.js("document.activeElement.dataset.p")]
    assert stops == [1] * len(LEGEND_CHORDS)  # one Tab stop a chord, on the shape it plays
    assert right[0]["at"] == "1.1" and right[0]["chords"][1]["checked"] == 1 and right[1] == "1"
    assert left[0]["at"] == "1.4" and left[0]["chords"][1]["checked"] == 4 and left[1] == "4"


# --- beside the song ------------------------------------------------------------------------------------


def test_the_rail_and_the_settings_rail_fit_together(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), width=1440, height=900, mobile=False) as b:
        b.click("#more")
        b.click('#sheet .sec .c[data-c="1"]')  # a chord's card, too
        both = b.js(RAIL)
    rail, sheet, panel, bar, card = (both[k] for k in ("rail", "sheet", "panel", "bar", "card"))
    assert rail["left"] == 0 and panel["right"] == both["client"]
    assert rail["right"] <= sheet["left"] and sheet["right"] <= panel["left"]  # the song between them
    assert rail["right"] <= bar["left"] and bar["right"] <= panel["left"]
    assert rail["right"] <= card["left"] and card["right"] <= panel["left"]
    assert not both["sideways"]


def test_a_song_with_many_chords_scrolls_the_rail_alone(tmp_path):
    scrolls = """(() => { const r = document.getElementById('necks');
      return {top: r.scrollTop, height: r.scrollHeight, client: r.clientHeight, wide: r.scrollWidth > r.clientWidth,
              at: Math.round(r.getBoundingClientRect().top), y: scrollY}; })()"""
    with open_viewer(tmp_path, written(tmp_path, MANY_CHO), **DESKTOP) as b:
        names = [c["name"] for c in b.js(RAIL)["chords"]]
        before = b.js(scrolls)
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=150, y=400, deltaX=0, deltaY=300)
        assert b.wait("document.getElementById('necks').scrollTop > 0")
        wheeled = b.js(scrolls)
        b.js("document.getElementById('necks').scrollTop = 1e6")  # at its end, the wheel moves the song no more
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=150, y=400, deltaX=0, deltaY=300)
        time.sleep(0.4)
        at_end = b.js(scrolls)
        b.js("window.scrollTo(0, 600)")  # the song scrolls under its own bar, the rail stays
        song = b.js(scrolls)
        sheet = b.js("document.getElementById('sheet').getBoundingClientRect().top")
        click_at(b, *b.js("""(() => { const r = [...document.querySelectorAll('#necks .nk')].pop()
          .querySelector('[role=radio][data-p="1"]').getBoundingClientRect();
          return [r.left + r.width / 2, r.top + r.height / 2]; })()"""))  # the last chord's second shape
        picked = b.js(scrolls)
        moved = [b.js("document.getElementById('sheet').getBoundingClientRect().top"), b.js(RAIL)]
    assert names == MANY
    assert before["height"] > before["client"] and not before["wide"]
    assert wheeled["top"] > 0 and wheeled["y"] == 0  # the rail scrolled, the song didn't
    assert at_end["y"] == 0
    assert song["y"] == 600 and song["at"] == 0 and song["top"] == at_end["top"]
    # Drawn anew for the shape picked, the rail stays where it was scrolled to, and the song holds still.
    assert moved[1]["at"] == "13.1" and moved[1]["chords"][-1]["checked"] == 1
    assert picked["top"] == song["top"] and picked["y"] == 600 and moved[0] == sheet
    assert not moved[1]["sideways"]


def luminance(colour: str) -> float:
    r, g, b = (int(round(float(v))) for v in re.findall(r"[\d.]+", colour)[:3])

    def channel(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def blend(colour: str, opacity: float, under: str) -> str:
    top = [float(v) for v in re.findall(r"[\d.]+", colour)[:3]]
    bottom = [float(v) for v in re.findall(r"[\d.]+", under)[:3]]
    return "rgb({}, {}, {})".format(*(t * opacity + u * (1 - opacity) for t, u in zip(top, bottom)))


def test_the_rail_in_dark_mode_keeps_its_contrast(tmp_path):
    colours = """(() => { const rail = document.getElementById('necks'), all = (s) => [...rail.querySelectorAll(s)];
      const css = (el) => getComputedStyle(el);
      return {background: css(rail).backgroundColor,
              text: all('.nk-name, [role=radio]').map((el) => css(el).color),
              dots: all('circle.nk-dot').map((c) => css(c).fill).concat(all('circle.nk-open').map((c) => css(c).stroke)),
              swatches: all('.sw').map((s) => css(s).backgroundColor),
              lines: all('.nk-string, .nk-fret').map((l) => [css(l).stroke, Number(css(l).opacity)]),
              checked: all('[aria-checked=true]').map((r) => css(r).borderTopColor)}; })()"""
    schemes = {}
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **DESKTOP) as b:
        for scheme in ("light", "dark"):
            b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
            assert b.wait(f"matchMedia('(prefers-color-scheme: {scheme})').matches")
            schemes[scheme] = b.js(colours)
    assert luminance(schemes["light"]["background"]) > 0.9 and luminance(schemes["dark"]["background"]) < 0.02
    for scheme, seen in schemes.items():  # dark as the page is, and as clear as in light
        background = seen["background"]
        assert seen["text"] and min(contrast(c, background) for c in seen["text"]) >= 4.5, scheme
        for kind in ("dots", "swatches", "checked"):  # each position told apart from the rail, and the one played
            assert seen[kind] and min(contrast(c, background) for c in seen[kind]) >= 3, (scheme, kind)
        lines = [contrast(blend(c, a, background), background) for c, a in seen["lines"]]
        assert lines and min(lines) >= 3, scheme  # the strings and the frets


def test_on_a_touch_screen_the_rails_legend_is_easy_to_tap(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), **DESKTOP) as b:
        b.send("Emulation.setTouchEmulationEnabled", enabled=True)
        short = b.js(small_targets(":not(.necks *)"))  # the rail's controls alone
        radios = b.js("document.querySelectorAll('#necks [role=radio]').length")
    assert radios > len(LEGEND_CHORDS) and short == []


# --- the key's neck ------------------------------------------------------------------------------------

IN_C = ("{title: In C}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n"
        "[C]Made up [G]words to [Am]sing a[F]long\n")
OPEN_STRINGS = [4, 9, 2, 7, 11, 4]  # E A D G B E, low E first
MAJOR, DORIAN, MAJOR_BOX = (0, 2, 4, 5, 7, 9, 11), (0, 2, 3, 5, 7, 9, 10), (0, 2, 4, 7, 9)
# The rail's key neck: where it is, its name, its switch, and its dots as [string (0: low E), fret, tonic].
KEY_NECK = """(() => { const g = document.querySelector('#necks .kn'); if (!g) return null;
  return {first: document.querySelector('#necks :is(.kn, .nk)') === g, name: g.querySelector('.kn-name').textContent,
    switch: [...g.querySelectorAll('.chip')].map((c) => [c.textContent, c.getAttribute('aria-pressed')]),
    label: g.querySelector('svg').getAttribute('aria-label'),
    dots: [...g.querySelectorAll('circle[data-fret]')].map((c) => [Number(c.dataset.string), Number(c.dataset.fret),
      c.classList.contains('tonic')]).sort((a, b) => a[0] - b[0] || a[1] - b[1])}; })()"""


def scale_dots(tonic: int, steps: tuple[int, ...], frets: int = 15) -> list[list]:
    """Where a scale's notes are on the neck, as ``KEY_NECK`` reads them, frets 0 to ``frets``."""
    return [[s, f, (OPEN_STRINGS[s] + f - tonic) % 12 == 0] for s in range(6) for f in range(frets + 1)
            if (OPEN_STRINGS[s] + f - tonic) % 12 in steps]


def test_the_rails_first_neck_is_the_keys_scale_with_its_tonic_marked(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_C), **DESKTOP) as b:
        scale = b.js(KEY_NECK)
        b.click("#necks .kn .chip:nth-of-type(2)")
        box = b.js(KEY_NECK)
        focus = b.js("document.activeElement.textContent")
        chords = b.js(RAIL)["chords"]
    assert scale["first"] and scale["name"] == "C scale"
    assert scale["switch"] == [["Scale", "true"], ["Major pentatonic", "false"]]
    assert scale["dots"] == scale_dots(0, MAJOR) and scale["label"] == "C scale: the tonic, C, marked"
    assert box["name"] == "C major pentatonic" and box["dots"] == scale_dots(0, MAJOR_BOX)
    assert box["switch"] == [["Scale", "false"], ["Major pentatonic", "true"]] and focus == "Major pentatonic"
    assert [c["name"] for c in chords] == ["C", "G", "Am", "F"]  # the chords' necks after it


def test_the_keys_neck_follows_the_key_the_mode_and_the_capo(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_C), **DESKTOP) as b:
        b.click("#t-up")
        b.click("#t-up")
        up = b.js(KEY_NECK)
        b.click("#more")
        b.js("[...document.querySelectorAll('#modes .chip')].find((c) => c.textContent.startsWith('Dorian')).click()")
        dorian = b.js(KEY_NECK)
        b.click("#capo-up")
        b.click("#capo-up")
        capo = b.js(KEY_NECK)
        b.js("document.querySelector('#necks .kn .chip:nth-of-type(2)').click()")
        box = b.js(KEY_NECK)
    assert up["name"] == "D scale" and up["dots"] == scale_dots(2, MAJOR)
    assert dorian["name"] == "D dorian scale" and dorian["dots"] == scale_dots(2, DORIAN)
    # Capo 2: the shapes are C's, and so are the frets, counted from the capo.
    assert capo["name"] == "C dorian scale" and capo["dots"] == scale_dots(0, DORIAN)
    assert box["name"] == "C dorian minor pentatonic" and box["dots"] == scale_dots(0, (0, 3, 5, 7, 10))


def test_a_song_with_no_key_has_no_keys_neck(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, "{title: T}\n{comment: V}\n[N.C.]made [Xq]up\n"), **DESKTOP) as b:
        seen = b.js(KEY_NECK)
    assert seen is None


# --- in a songbook --------------------------------------------------------------------------------------


def test_a_songbook_song_has_its_own_rail(tmp_path):
    songs = [BookSong("Legend Song", "The Placeholders", cho=LEGEND, id="aaaa"),
             BookSong("Twins", "Synthetic", cho=TWINS, id="bbbb")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-2", **DESKTOP) as b:
        seen = b.js(RAIL)
        other = b.js("[document.getElementById('necks-1').getClientRects().length, document.getElementById('necks-2')]")
        b.click('#necks .nk [role=radio][data-p="1"]')
        picked = b.js("[location.hash, document.querySelector('#necks [aria-checked=true]').dataset.p]")
    assert seen["rail"]["left"] == 0 and seen["rail"]["width"] == 345
    assert [c["name"] for c in seen["chords"]] == ["A#", "Bb", "F"]  # its own chords
    assert other == [0, None]  # the other song's rail is in its hidden section; this one's is the viewer's
    assert picked[0] == "#song-2=&at=0.1" and picked[1] == "1"


def test_in_a_songbook_each_song_keeps_its_shapes_from_song_to_song(tmp_path):
    # A set list played song to song: each song comes back in the key and with the shapes you left it in.
    songs = [BookSong("Legend Song", "The Placeholders", cho=LEGEND, id="aaaa"),
             BookSong("Twins", "Synthetic", cho=TWINS, id="bbbb")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-1", **DESKTOP) as b:
        b.click("#t-up")
        b.click('#necks .nk:nth-of-type(2) [role=radio][data-p="2"]')  # song 1's G, now Ab: its third shape
        one = [b.js(RAIL), b.js("location.hash")]
        to_song(b, 2)
        two = [b.js(RAIL), b.js("location.hash")]
        to_song(b, 1)
        back = [b.js(RAIL), b.js("location.hash")]
    assert one[1] == "#song-1=&t=1&at=1.2" and one[0]["chords"][1]["name"] == "Ab"
    assert [c["name"] for c in two[0]["chords"]] == ["A#", "Bb", "F"] and two[1] == "#song-2="  # its own, as left
    assert back[1] == "#song-1=&t=1&at=1.2"
    assert back[0]["chords"][1]["name"] == "Ab" and back[0]["chords"][1]["checked"] == 2


def test_in_a_songbook_the_rail_hidden_stays_hidden_from_song_to_song(tmp_path):
    songs = [BookSong("Legend Song", "The Placeholders", cho=LEGEND, id="aaaa"),
             BookSong("Twins", "Synthetic", cho=TWINS, id="bbbb")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-1", **DESKTOP) as b:
        shown = [b.js(RAIL), toggles(b)]
        b.click("#necks-toggle")
        to_song(b, 2)
        two = [b.js(RAIL), toggles(b)]
        b.click("#necks-toggle")
        to_song(b, 1)
        one = [b.js(RAIL), toggles(b)]
    assert shown[0]["rail"]["width"] == 345 and shown[1]["button"] and shown[1]["pressed"] == "true"
    assert two[0]["rail"] is None and two[1]["pressed"] == "false" and two[0]["padding"] == "0px"
    assert one[0]["rail"]["width"] == 345 and one[1]["pressed"] == "true"


def follow(b: Browser, script: str, ready: str = "document.documentElement?.dataset.ready === '1'") -> None:
    """``script`` run in the page, which takes it to another address of the songbook: the page loaded again."""
    b.js(f"window.before = true; {script}")
    assert b.wait(f"!window.before && {ready}")


def test_a_served_songbook_keeps_the_rail_hidden_from_song_to_song_and_through_its_contents(tmp_path):
    # In caracole serve's sandbox there is no storage: the address keeps the choice, and every step to another
    # song (the arrows, a swipe, the ‹ › links, the contents) carries it into the next song's address.
    songs = [BookSong("Legend Song", "The Placeholders", cho=LEGEND, id="aaaa"),
             BookSong("Twins", "Synthetic", cho=TWINS, id="bbbb"),
             BookSong("In C", "Synthetic", cho=IN_C, id="cccc")]
    page = "/_songbooks/Campfire/songbook.html"
    contents = "document.documentElement?.dataset.view === 'contents'"
    with served({page: (build_songbook("Campfire", songs), songbook_csp)}) as site, \
            open_viewer(tmp_path, site + page + "#song-1", **DESKTOP) as b:
        sandboxed = [b.js("origin"), b.js(STORAGE)]
        b.click("#necks-toggle")
        one = toggles(b)
        b.js("document.activeElement.blur(); window.before = true")
        key(b, "ArrowRight", 39)  # the next song, from the keyboard
        assert b.wait("!window.before && document.documentElement?.dataset.ready === '1'")
        two = [b.js(RAIL), toggles(b), b.js("location.hash")]
        follow(b, "document.querySelector('#song-2 a[rel=next]').click()")
        three = [b.js(RAIL), toggles(b), b.js("location.hash")]
        follow(b, "document.querySelector('#song-3 a[href=\"#contents\"]').click()", contents)
        listed = b.js("location.hash")
        follow(b, "document.querySelector('#contents a[href=\"#song-1\"]').click()")
        back = [b.js(RAIL), toggles(b), b.js("location.hash")]
        b.click("#necks-toggle")  # shown again: so on the next song
        follow(b, "document.querySelector('#song-1 a[rel=next]').click()")
        shown = [b.js(RAIL), toggles(b), b.js("location.hash")]
    assert sandboxed == ["null", False]
    assert one["pressed"] == "false" and one["necks"] == "0"
    for seen, at in ((two, "#song-2=&necks=0"), (three, "#song-3=&necks=0"), (back, "#song-1=&necks=0")):
        assert seen[0]["rail"] is None and seen[1]["pressed"] == "false" and seen[0]["padding"] == "0px", seen
        assert seen[2] == at
    assert listed == "#contents=&necks=0"  # as the viewer writes a song's: "#song-1=&necks=0"
    assert shown[0]["rail"]["width"] == 345 and shown[1]["pressed"] == "true" and shown[2] == "#song-2="
