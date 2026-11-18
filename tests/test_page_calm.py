"""Stage 1f, a calmer page (library_assets/), in Chromium: four corner radii, one set of tokens in base.css."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from helpers.browser import in_chromium
from helpers.targets import noted, noting, odd_radii
from test_library_page import dump_dom, put, with_script

from caracole.library_page import WebControls, build_library_page, write_library_page
from caracole.overrides import Overrides
from caracole.songs import update_song

from conftest import add_song

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)

# The elements of a lane not merged yet (the card's, lane 3b's, whose own radii come to the tokens with its merge).
OTHER_LANES = (".line-panel", ".play")

# Each state of the page, in a script that leaves it as the owner would see it.
STATES = {
    "library": "",
    "songbooks": "location.hash = '#tab=songbooks';",
    "sites": "location.hash = '#tab=sites';",
    "requests": "location.hash = '#tab=requests';",
    "sync": "location.hash = '#tab=sync';",
    "filter": "document.getElementById('filter').click();",
    "search": "const q = document.getElementById('q'); q.focus(); q.value = 'wonder'; "
              "q.dispatchEvent(new Event('input', { bubbles: true }));",
    "sheet": "location.hash = '#sheet=sync';",
    "tray": "const t = document.getElementById('tray'); t.hidden = false; "
            "document.getElementById('tray-toggle').click();",
}


@in_chromium
@pytest.mark.parametrize("size,touch", [("390,844", True), ("1280,900", False)])
@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("state", STATES)
def test_the_library_page_has_four_corner_radii(conn, cfg, tmp_path, size, touch, scheme, state):
    for artist, title in (("Oasis", "Wonderwall"), ("Oasis", "Live Forever"), ("Eagles", "Desperado")):
        song = add_song(conn, artist, title)
        put(cfg, song, "sheet.html", "sheet.pdf")
        update_song(conn, song.id, status="found")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", sync="tab"))
    script = "setTimeout(() => {" + STATES[state] + "setTimeout(() => {" + noting(
        "data-odd", odd_radii(OTHER_LANES)) + "}, 300);}, 100);"
    path = write_library_page(cfg.library_dir, with_script(html, script))
    dom = dump_dom(path, tmp_path, size=size, touch=touch, media={"prefers-color-scheme": scheme})
    assert noted(dom, "data-odd") == []
