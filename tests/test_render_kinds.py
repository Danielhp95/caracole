"""render.py's ``kinds`` in every viewer of a song (``_kinds_data``): what else the song keeps to play from, as its
library card names it (library_assets/card.js ``things``), which the viewer's version line counts and its list opens
(viewer/kinds.js): its chord sheet's kind and page, then each other kind it keeps a file of, in the card's order."""

from __future__ import annotations

from caracole import library_page, render as render_module
from caracole.library import keep_file, song_dir
from caracole.sheet_versions import version_names
from caracole.versions import upsert_version

from conftest import add_song
from helpers.ug_pages import version_dict
from test_render_all import auto_sheet
from test_render_harmonica import FETCHED, data_of, keep_sheet, keep_tab, render
from test_render_versions import keep_text, sheet, ug_version

VERSION_TAB = 39144

KINDS = {"sheet": "sheet", "page": "sheet.html", "groups": [
    {"kind": "guitar", "items": [
        {"name": "guitar-1.gp5", "label": "Guitar Pro 1 · gtptabs", "browser": True, "download": "Artist - Title.gp5"},
        {"name": "guitar-2.ptb", "label": "Power Tab 2", "browser": False, "download": "Artist - Title (2).ptb"}]},
    {"kind": "tab", "items": [{"name": "tab.txt", "label": "Guitar tab · UG"}]},
    {"kind": "harmonica", "items": [{"name": "harmonica-1.txt", "label": "Harmonica tab 1 · harptabs",
                                     "page": "harmonica-1.html"}]},
    {"kind": "gametab", "items": [{"name": "gametab-1.txt", "label": "Game music tab 1 · gametabs"}]},
    # by N, then by name, as the card lists a score's formats
    {"kind": "score", "items": [{"name": "score-1.mscz", "label": "Score 1 (MuseScore)", "download": "Artist - Title.mscz"},
                                {"name": "score-1.pdf", "label": "Score 1 (PDF)"}]}]}


def keep(conn, cfg, song, name: str, data: bytes, *, provider: str, kind: str, tab_id: str, slot: str = "guitar",
         rank: int = 1) -> None:
    """A file kept for a version of ``provider``'s, as its step keeps one (synthetic)."""
    vid = upsert_version(conn, provider=provider, tab_id=tab_id, song_id=song.id, slot=slot, kind=kind, rating=0,
                         votes=0, version=1, label=None, url="", raw={}, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=name, data=data, rank=rank)


def keep_everything(conn, cfg, song) -> None:
    """Every other kind a song can keep: two Guitar Pro files (gtptabs.com's and a Power Tab file from the inbox),
    UG's text tab, a harmonica tab, a game music tab and a score in two formats from the inbox."""
    keep(conn, cfg, song, "guitar-1.gp5", b"FICHIER GUITAR PRO v5.00 synthetic", provider="gtptabs",
         kind="guitar-pro", tab_id="1201")
    keep(conn, cfg, song, "guitar-2.ptb", b"ptab synthetic", provider="inbox", kind="power", tab_id="power", rank=2)
    keep(conn, cfg, song, "tab.txt", b"e|--0--| synthetic", provider="ug", kind="tabs", tab_id="91500")
    keep_tab(conn, cfg, song)
    keep(conn, cfg, song, "gametab-1.txt", b"e|--3--| synthetic", provider="gametabs", kind="gametab",
         tab_id="synthetic-game/main-theme")
    keep(conn, cfg, song, "score-1.pdf", b"%PDF-1.4 synthetic", provider="inbox", kind="score", tab_id="score")
    keep(conn, cfg, song, "score-1.mscz", b"PK synthetic", provider="inbox", kind="score", tab_id="score")


def kinds_of(cfg, song, page: str = "sheet.html"):
    return data_of(song_dir(cfg.library_dir, song) / page, "song").get("kinds")


def test_every_viewer_of_the_song_names_its_other_kinds(conn, cfg):
    song = add_song(conn, "Artist", "Title")
    keep_sheet(conn, cfg, song)
    vid, raw = ug_version(conn, song, VERSION_TAB, rating=4.85, votes=12629, number=2)
    keep_text(conn, cfg, song, vid, raw, sheet("dos"), version_names(str(VERSION_TAB))[:2], 2)
    keep_everything(conn, cfg, song)
    render(conn, cfg)
    assert kinds_of(cfg, song) == KINDS
    assert kinds_of(cfg, song, version_names(str(VERSION_TAB))[2]) == KINDS
    data = data_of(song_dir(cfg.library_dir, song) / "sheet.html", "song")
    members = list(data)
    assert members.index("kinds") == members.index("versions") + 1  # right after the versions, on both sides


def ukulele_sheet(conn, cfg, song) -> None:
    """A sheet of UG's Ukulele Chords type, kept as the fetch keeps one for a song with no chords there."""
    content = "[tab][ch]C[/ch]\r\nmade up words[/tab]\r\n"
    raw = version_dict(92000 + song.id, song=song.title, artist=song.artist, tonality_name="C")
    vid = upsert_version(conn, provider="ug", tab_id=str(raw["id"]), song_id=song.id, slot="sheet", kind="ukulele",
                         rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw, now=FETCHED)
    keep_text(conn, cfg, song, vid, raw, content, ("sheet.txt", "sheet.json"), 1)


def test_a_ukulele_sheet_is_ukulele_chords(conn, cfg):
    song = add_song(conn, "Artist", "Title")
    ukulele_sheet(conn, cfg, song)
    render(conn, cfg)
    assert kinds_of(cfg, song) == {"sheet": "ukulele", "page": "sheet.html", "groups": []}


def test_an_auto_sheet_beside_a_human_one_names_none(conn, cfg):
    song = add_song(conn, "Artist", "Title")
    keep_sheet(conn, cfg, song)
    auto_sheet(conn, cfg, song)
    keep_tab(conn, cfg, song)
    render(conn, cfg)
    assert kinds_of(cfg, song, "sheet (auto).html") is None
    assert kinds_of(cfg, song) == {"sheet": "sheet", "page": "sheet.html", "groups": [
        {"kind": "harmonica", "items": [{"name": "harmonica-1.txt", "label": "Harmonica tab 1 · harptabs",
                                         "page": "harmonica-1.html"}]}]}


def test_an_auto_sheet_standing_alone_is_the_songs_sheet(conn, cfg):
    song = add_song(conn, "Artist", "Title")
    auto_sheet(conn, cfg, song)
    keep(conn, cfg, song, "guitar-1.gp5", b"FICHIER GUITAR PRO v5.00 synthetic", provider="inbox",
         kind="guitar-pro", tab_id="guitar-pro")
    render(conn, cfg)
    assert kinds_of(cfg, song, "sheet (auto).html") == {"sheet": "sheet", "page": "sheet (auto).html", "groups": [
        {"kind": "guitar", "items": [{"name": "guitar-1.gp5", "label": "Guitar Pro 1", "browser": True,
                                      "download": "Artist - Title.gp5"}]}]}


def test_a_song_with_nothing_else_has_its_sheet_alone(conn, cfg):
    song = add_song(conn, "Artist", "Title")
    keep_sheet(conn, cfg, song)
    render(conn, cfg)
    assert kinds_of(cfg, song) == {"sheet": "sheet", "page": "sheet.html", "groups": []}


def test_the_score_formats_are_the_library_cards():
    assert render_module._SCORE_FORMATS == library_page._SCORE_FORMATS
