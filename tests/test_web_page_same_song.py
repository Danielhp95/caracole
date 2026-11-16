"""The served library page names a song by its id and its identity key (library.js ``songForm``, ``startRemoval``):
Remove on a line of a song removed elsewhere, whose id the next song added got, removes nothing, and its line says
why (web/app.py ``same_song``)."""

from __future__ import annotations

from helpers import browser
from helpers.browser import CHROMIUM_MARKS
from test_web_page import QUICK, FakeCaracole, press_remove, serve  # noqa: F401  (serve: a fixture)

from caracole.overrides import override_key
from caracole.songs import find_song

from conftest import add_song

pytestmark = CHROMIUM_MARKS


def test_remove_on_a_line_whose_id_another_song_has_now_removes_nothing_and_says_why(serve, cfg, conn,  # noqa: F811
                                                                                     tmp_path):
    add_song(conn, "Band", "Song")
    creep = add_song(conn, "Radiohead", "Creep")  # the newest
    runner = FakeCaracole(cfg)
    url = serve(runner, "(() => {})();\n", timers=QUICK)
    item = f'#list [data-id="{creep.id}"]'
    with browser.Browser(tmp_path / "chrome", width=1280, height=800) as page:
        page.open(url)
        # Elsewhere: Creep removed, then Uprising added, which gets Creep's id.
        conn.execute("DELETE FROM songs WHERE id = ?", (creep.id,))
        uprising = add_song(conn, "Muse", "Uprising")
        conn.commit()
        assert uprising.id == creep.id
        assert page.js(f"document.querySelector('{item} h3').textContent") == "Creep"
        page.click(f"{item} .line-more")
        page.js(f"window.song = document.querySelector('{item}')")
        press_remove(page, item)
        assert page.wait("/another has its place/.test(window.song.querySelector('.progress')?.textContent || '')",
                         timeout=20)
    assert not [call for call in runner.calls if call[0] == "remove"]
    assert find_song(conn, override_key("Muse - Uprising")) is not None
