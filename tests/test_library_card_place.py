"""Where a song's card is on the library page (stage 1d), in a real browser: the tests find it by its line's chevron."""

from __future__ import annotations

from conftest import add_song
from helpers import cards
from helpers.browser import CHROMIUM_MARKS
from test_library_card import run
from test_library_page import attribute_of, put

from caracole.songs import update_song

pytestmark = CHROMIUM_MARKS


def test_the_tests_find_a_card_by_its_chevron(conn, cfg, tmp_path):
    for title in ("Creep", "Karma Police"):
        song = add_song(conn, "Radiohead", title)
        put(cfg, song, "sheet.pdf")
        update_song(conn, song.id, status="found")
    script = r"""
const line = lineOf("Creep");
openCardOf(line);
note("card", { id: cardOf(line).id, named: line.querySelector(".line-more").getAttribute("aria-controls"),
  other: cardOf(lineOf("Karma Police")).hidden });
"""
    dom = run(conn, cfg, tmp_path, script)
    noted = attribute_of(dom, "data-card")
    assert noted["id"] == noted["named"]
    assert noted["other"] is True
    card = cards.card_of(dom, "Creep")
    assert card.startswith('<div class="line-panel') and "Add to a songbook…" in card
