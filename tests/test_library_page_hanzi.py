"""The library page and Chinese: a Chinese song's title and its artist's name in the characters the sheet viewer shows
its Chinese in (the choice it keeps in the browser, ``caracole-viewer-hanzi``; Simplified at first), from each song's
card (``hanzi``: library_page.py, for a song whose sheet's PDF is a Chinese sheet's, render.py ``chinese_songs``); and
the PDFs in Traditional characters beside a sheet's and a songbook's, linked from the page, so the offline copy takes
them too (``linked_files``)."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from caracole.library_page import build_library_page, linked_files, song_cards, write_library_page
from caracole.overrides import Overrides

from conftest import add_song
from helpers.browser import Browser, in_chromium
from test_render_all import UG_SHEET, human_sheet, render
from test_render_hanzi import TRADITIONAL, zh_cfg  # noqa: F401 (a fixture)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def songs(conn, cfg):
    """A Chinese song with Traditional names, and one with Chinese names over Spanish words; rendered."""
    zh = add_song(conn, "張學友", "斑馬斑馬")
    human_sheet(conn, cfg, zh, TRADITIONAL, tonality="", tab_id=1)
    latin = add_song(conn, "宋冬野", "斑馬")
    human_sheet(conn, cfg, latin, UG_SHEET, tab_id=2)
    render(conn, cfg)
    return zh, latin


def test_a_chinese_songs_card_carries_its_names_in_either_script(conn, zh_cfg):  # noqa: F811
    zh, latin = songs(conn, zh_cfg)
    cards = {c["id"]: c for c in song_cards(conn, zh_cfg, Overrides(), NOW)}
    assert cards[zh.id]["hanzi"] == {"simplified": {"斑馬斑馬": "斑马斑马", "張學友": "张学友"}, "traditional": {}}
    assert "hanzi" not in cards[latin.id]  # its words aren't Chinese: its names as written, as on its viewer


def test_the_traditional_pdfs_are_listed_and_so_copied_offline(conn, zh_cfg):  # noqa: F811
    from caracole.songbook import make_songbook, render_songbooks, songbooks_file
    from helpers.songbooks import FakeChordPro

    zh, _ = songs(conn, zh_cfg)
    make_songbook(songbooks_file(zh_cfg.library_dir), "Campfire", ["張學友 - 斑馬斑馬"])
    render_songbooks(conn, zh_cfg, Overrides(), runner=FakeChordPro())
    html = build_library_page(conn, zh_cfg, Overrides(), NOW)
    card = next(c for c in song_cards(conn, zh_cfg, Overrides(), NOW) if c["id"] == zh.id)
    assert [f["label"] for f in card["files"]][:3] == ["Sheet viewer", "Sheet PDF", "Sheet PDF, Traditional"]
    linked = linked_files(html.encode("utf-8"))
    assert "張學友/斑馬斑馬/sheet (Traditional).pdf" in linked
    assert "_songbooks/Campfire/songbook (Traditional).pdf" in linked


NAMES = """(() => ({titles: [...document.querySelectorAll('#list .line h3')].map((h) => h.textContent),
  artists: [...document.querySelectorAll('#list .artist-title .artist-name, #list .artist-title button')]
    .map((b) => b.textContent.trim()).filter(Boolean)}))()"""


@in_chromium
def test_the_page_shows_chinese_names_in_the_characters_the_viewer_keeps(conn, zh_cfg, tmp_path):  # noqa: F811
    songs(conn, zh_cfg)
    path = write_library_page(zh_cfg.library_dir, build_library_page(conn, zh_cfg, Overrides(), NOW))
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), width=1280, height=800) as b:
        b.open(path.as_uri())
        assert b.wait("document.querySelectorAll('#list .line h3').length === 2")
        first = b.js(NAMES)
        b.js("localStorage.setItem('caracole-viewer-hanzi', 'traditional'); window.before = true; location.reload()")
        assert b.wait("!window.before && document.querySelectorAll('#list .line h3').length === 2")
        chosen = b.js(NAMES)
    assert set(first["titles"]) == {"斑马斑马", "斑馬"}  # the Spanish song's, as written
    assert "张学友" in first["artists"] and "宋冬野" in first["artists"]
    assert set(chosen["titles"]) == {"斑馬", "斑馬斑馬"} and "張學友" in chosen["artists"]
