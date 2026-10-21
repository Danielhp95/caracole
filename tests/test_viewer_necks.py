"""The sheet viewer's neck drawing: a chord's positions along a guitar neck, each in its own colour.

``neck(positions, opts)`` is viewer.js's; the page hands it to ``window.caracole`` for the rail of
necks (and for this test, which draws one beside the song).
"""

from __future__ import annotations

from pathlib import Path

from caracole.viewer.voicings import load_voicings

from helpers.browser import CHROMIUM_MARKS
from helpers.viewer_pages import viewer as open_viewer, written

pytestmark = CHROMIUM_MARKS

LEGEND = (Path(__file__).parent / "fixtures" / "chordpro" / "legend_sheet.cho").read_text(encoding="utf-8")
DB = load_voicings()

DRAW = """(() => {
  const s = JSON.parse(document.getElementById('song').textContent);
  const g = s.shapes['7,,'];
  const host = document.createElement('div');
  host.id = 'necks';
  document.body.appendChild(host);
  host.appendChild(window.caracole.neck(g.list, {name: 'G', chosen: %d, mine: g.mine, frets: 15}));
  return true;
})()"""
READ = """Array.from(document.querySelectorAll('#necks svg[aria-label^="G"] circle'),
  (c) => [Number(c.dataset.p), Number(c.dataset.fret), c.getAttribute('class')])"""


def absolute(position) -> set[tuple[int, str]]:
    """The (fret, kind) a position draws: absolute frets of its fingered strings, 0 for an open one."""
    frets, _, base = position[0], position[1], position[2]
    out = set()
    for f in frets:
        if f == "x":
            continue
        n = int(f)
        out.add((0, "open") if n == 0 else (n + base - 1, "dot"))
    return out


def test_a_neck_draws_every_position_at_its_frets(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), width=1280, height=800, mobile=False) as b:
        b.js(DRAW % 0)
        circles = b.js(READ)
        label = b.js("document.querySelector('#necks svg').getAttribute('aria-label')")
    positions = [["320033", "000000", 1, []], *DB[""][7]]
    assert label == "G: 5 positions"
    for p, position in enumerate(positions):
        drawn = {(fret, "open" if "open" in cls else "dot") for q, fret, cls in circles if q == p}
        assert drawn == absolute(position), position
    # the tab's own 320033 is the open D and G strings, a 2 and three 3s
    assert {f for q, f, c in circles if q == 0} == {0, 2, 3}
    assert not any(cls is None for *_, cls in circles)


def test_the_chosen_position_is_drawn_bolder(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), width=1280, height=800, mobile=False) as b:
        b.js(DRAW % 2)
        sizes = b.js("""Array.from(document.querySelectorAll('#necks circle.nk-dot'),
          (c) => [Number(c.dataset.p), c.classList.contains('chosen')])""")
        b_tabs = set(b.js("""Array.from(document.querySelectorAll('#necks circle.tabs'), (c) => Number(c.dataset.p))"""))
    assert {p for p, chosen in sizes if chosen} == {2}
    assert b_tabs == {0}


def test_the_legend_names_the_tabs_own_shapes_and_the_others_by_where_they_sit(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LEGEND), width=1280, height=800, mobile=False) as b:
        names = b.js("""(() => {
          const g = JSON.parse(document.getElementById('song').textContent).shapes['7,,'];
          return window.caracole.neckLabels(g.list, g.mine);
        })()""")
    assert names[0] == "the tab's"
    lows = [min([f for f, kind in absolute(pos) if kind == "dot"] or [0]) for pos in DB[""][7]]
    assert names[1:] == ["open" if pos[0].count("0") and pos[2] == 1 else f"fret {low}"
                         for pos, low in zip(DB[""][7], lows)]
