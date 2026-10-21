"""render.py's page for each version a song keeps beside its sheet (sheet_versions.py): a viewer
each, ``version-<tab>.html``, and no PDF; and the list of the song's versions in every viewer."""

from __future__ import annotations

import hashlib
import json
import os
import re

from caracole.config import RankPolicy
from caracole.library import drop_file, keep_file, song_dir
from caracole.overrides import Overrides
from caracole.removal import plan_removal, remove_song
from caracole.render import render_all, written_file
from caracole.sheet_versions import as_data, song_sheet_versions, version_names
from caracole.ug.page import strip_markup
from caracole.versions import mark_gone, set_coverage, upsert_version

from conftest import add_song
from helpers.rendered import fake_chordpro
from helpers.ug_pages import version_dict

FETCHED = "2026-10-21T03:00:00Z"
SHEET_TAB, B, C, D = 1064463, 39144, 2205118, 700001


def sheet(word: str, chords: tuple[str, str] = ("G", "D")) -> str:
    """A UG chords sheet as wiki_tab.content holds it (synthetic lyrics); ``word`` makes it its own."""
    first, second = chords
    return (
        "[Verse]\r\n"
        f"[tab][ch]{first}[/ch]           [ch]{second}[/ch]\r\n"
        f"Palabras de prueba {word}[/tab]\r\n"
        "[tab][ch]Em[/ch]          [ch]C[/ch]\r\n"
        "solo para el visor[/tab]\r\n"
    )


def ug_version(conn, song, tab: int, *, rating: float, votes: int, number: int, coverage: float | None = None,
               tonality: str = "G", **extra) -> tuple[int, dict]:
    raw = version_dict(tab, song=song.title, artist=song.artist, version=number, rating=rating, votes=votes,
                       tonality_name=tonality, **extra)
    vid = upsert_version(conn, provider="ug", tab_id=str(tab), song_id=song.id, slot="sheet", kind="chords",
                         rating=rating, votes=votes, version=number, label=None, url=raw["tab_url"], raw=raw,
                         now=FETCHED)
    if coverage is not None:
        set_coverage(conn, vid, coverage)
    return vid, raw


def keep_text(conn, cfg, song, vid: int, raw: dict, content: str, names: tuple[str, str], rank: int) -> None:
    """Keep a sheet's text and its JSON, as the fetch step keeps them (``ug/fetch.py`` ``_keep_text``)."""
    txt, doc = names
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=txt,
              data=strip_markup(content).encode("utf-8"), rank=rank)
    body = {"version": raw, "content": content, "url": raw["tab_url"], "meta": []}
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=doc,
              data=(json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), rank=rank)


def song_with_versions(conn, cfg, *, kept: tuple[int, ...] = (B, C)):
    """Wonderwall-like: the sheet (tab 1064463, Ver 3), two versions kept beside it and a fourth listed."""
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    vid, raw = ug_version(conn, song, SHEET_TAB, rating=4.86, votes=408, number=3, coverage=0.95,
                          version_description="the version that\n  they play live")
    keep_text(conn, cfg, song, vid, raw, sheet("uno"), ("sheet.txt", "sheet.json"), 1)
    others = {B: (4.85, 12629, 1, 0.9, ("A", "E")), C: (4.7, 300, 2, 0.85, ("C", "G")), D: (4.2, 50, 4, None, None)}
    for rank, (tab, (rating, votes, number, coverage, chords)) in enumerate(others.items(), start=2):
        vid, raw = ug_version(conn, song, tab, rating=rating, votes=votes, number=number, coverage=coverage,
                              tonality="A" if tab == B else "")
        if tab in kept:
            keep_text(conn, cfg, song, vid, raw, sheet(str(tab), chords), version_names(str(tab))[:2], rank)
    return song


def render(conn, cfg, calls: list | None = None):
    def runner(cmd, **kwargs):
        if calls is not None:
            calls.append(list(cmd))
        return fake_chordpro(cmd, **kwargs)

    stats = render_all(conn, cfg, Overrides(), runner=runner)
    assert stats.failed == 0, stats
    return stats


def page_data(path) -> dict:
    found = re.search(r'<script type="application/json" id="song">(.*?)</script>', path.read_text("utf-8"), re.S)
    assert found, path
    return json.loads(found.group(1))


def folder_of(cfg, song):
    return song_dir(cfg.library_dir, song)


# --- a viewer each, no PDF --------------------------------------------------------------------------------


def test_each_kept_version_gets_a_viewer_page_and_no_pdf(conn, cfg):
    song = song_with_versions(conn, cfg)
    calls: list = []
    render(conn, cfg, calls)
    folder = folder_of(cfg, song)
    for tab in (B, C):
        page = folder / version_names(str(tab))[2]
        assert page.is_file()
        data = page.read_bytes()
        assert written_file(conn, song.id, page.name) == (hashlib.sha256(data).hexdigest(), len(data))
        assert f'<span class="w">{tab}</span>' in page.read_text("utf-8")  # its own lyrics
    assert not (folder / version_names(str(D))[2]).exists()  # listed, not kept
    names = {p.name for p in folder.iterdir()}
    assert not {n for n in names if n.startswith("version-") and not n.endswith((".txt", ".json", ".html"))}
    assert len(calls) == 1  # sheet.pdf alone: no PDF per version
    assert "sheet.pdf" in names


def test_a_version_page_takes_its_own_key_and_links_no_pdf(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    b = page_data(folder / version_names(str(B))[2])
    c = page_data(folder / version_names(str(C))[2])
    assert b["key"] == {"tonic": 9, "mode": "ionian", "from": "from the tab"}  # its tonality_name
    assert c["key"]["tonic"] == 0  # no tonality_name: from its chords, as the sheet's would be
    assert c["key"]["from"] == "estimated from the chords"
    assert page_data(folder / "sheet.html")["key"]["tonic"] == 7
    assert "sheet.pdf" not in (folder / version_names(str(B))[2]).read_text("utf-8")


def test_a_version_page_offers_no_export_the_sheets_does(conn, cfg):
    # an export is made from the sheet export_viewer names: from a version's page, Export PDF would give
    # the one's PDF, not this version's, served or copied as a command
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    assert 'id="export"' in (folder / "sheet.html").read_text("utf-8")
    for tab in (B, C):
        assert 'id="export' not in (folder / version_names(str(tab))[2]).read_text("utf-8")


def test_a_version_page_is_written_again_only_when_its_bytes_change(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    page = folder_of(cfg, song) / version_names(str(B))[2]
    os.utime(page, ns=(1_000_000_000, 1_000_000_000))
    render(conn, cfg)
    assert page.stat().st_mtime_ns == 1_000_000_000
    ug_version(conn, song, D, rating=4.3, votes=60, number=4)  # new votes for a version listed
    render(conn, cfg)
    assert page.stat().st_mtime_ns != 1_000_000_000
    assert next(v for v in page_data(page)["versions"]["list"] if v["tab"] == str(D))["votes"] == 60


def test_a_version_page_that_cant_be_made_fails_the_song_and_nothing_else(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    before = (folder / version_names(str(B))[2]).read_bytes()
    (folder / version_names(str(B))[1]).write_text("{not json", encoding="utf-8")  # on a synced device
    ug_version(conn, song, D, rating=4.3, votes=60, number=4)  # every page changes
    stats = render_all(conn, cfg, Overrides(), runner=fake_chordpro)
    assert stats.failed == 1
    assert (folder / version_names(str(B))[2]).read_bytes() == before  # the last one written stays
    assert written_file(conn, song.id, version_names(str(B))[2]) == (hashlib.sha256(before).hexdigest(), len(before))
    assert (folder / "sheet.pdf").is_file()
    listed = page_data(folder / version_names(str(C))[2])["versions"]["list"]
    assert next(v for v in listed if v["tab"] == str(D))["votes"] == 60


# --- the list in every viewer -----------------------------------------------------------------------------


def test_every_page_carries_the_songs_versions_marking_its_own(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    versions = song_sheet_versions(conn, song.id, RankPolicy(), chosen_tab=str(SHEET_TAB), kept_tabs={str(B), str(C)})
    expected = as_data(versions, len(versions))
    for name, own in (("sheet.html", SHEET_TAB), (version_names(str(B))[2], B), (version_names(str(C))[2], C)):
        data = page_data(folder / name)["versions"]
        assert data["total"] == 4
        assert data["sheet"] == "ug"
        assert [v["tab"] for v in data["list"]] == [v["tab"] for v in expected["list"]]
        assert [v["tab"] for v in data["list"] if v["this"]] == [str(own)]
        assert [{k: v[k] for k in v if k != "this"} for v in data["list"]] == expected["list"]
    listed = {v["tab"]: v for v in page_data(folder / "sheet.html")["versions"]["list"]}
    assert listed[str(SHEET_TAB)]["page"] == "sheet.html" and listed[str(SHEET_TAB)]["chosen"]
    assert listed[str(B)]["page"] == version_names(str(B))[2] and listed[str(B)]["kept"]
    assert listed[str(D)]["page"] is None


def test_a_gone_version_is_listed_as_gone(conn, cfg):
    song = song_with_versions(conn, cfg)
    gone = next(v.version_id for v in song_sheet_versions(conn, song.id, RankPolicy(), chosen_tab=None, kept_tabs=())
                if v.tab_id == str(D))
    mark_gone(conn, gone)
    render(conn, cfg)
    listed = {v["tab"]: v for v in page_data(folder_of(cfg, song) / "sheet.html")["versions"]["list"]}
    assert listed[str(D)]["gone"] is True


def test_a_lacuerda_sheet_lists_the_songs_ug_versions_and_is_none_of_them(conn, cfg):
    song = add_song(conn, "Placeholder Banda", "Canción Sintética")
    tab_id = "placeholder_banda/cancion_sintetica-3"
    url = f"https://acordes.lacuerda.net/{tab_id}.shtml"
    vid = upsert_version(conn, provider="lacuerda", tab_id=tab_id, song_id=song.id, slot="sheet", kind="acordes",
                         rating=0, votes=0, version=3, label=None, url=url, raw={"lcd": "RRT-312"}, now=FETCHED)
    content = sheet("lacuerda")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.json",
              data=json.dumps({"provider": "lacuerda", "url": url, "version": 3, "content": content}).encode(), rank=1)
    vid_b, raw_b = ug_version(conn, song, B, rating=4.8, votes=100, number=1, coverage=0.9)
    keep_text(conn, cfg, song, vid_b, raw_b, sheet("ug"), version_names(str(B))[:2], 2)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    one = page_data(folder / "sheet.html")["versions"]
    assert one["sheet"] == "lacuerda"
    assert [v["tab"] for v in one["list"]] == [str(B)]
    assert not any(v["this"] or v["chosen"] for v in one["list"])
    mine = page_data(folder / version_names(str(B))[2])["versions"]
    assert [v["this"] for v in mine["list"]] == [True]


def test_an_auto_sheet_standing_alone_lists_the_songs_ug_versions(conn, cfg):
    from caracole.autochords import ChordSegment, build_sheet
    from caracole.autochords.run import PROVIDER

    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    text = build_sheet([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G")], title=song.title,
                       artist=song.artist, synced="[00:00.00]made up words\n[00:04.00]for the test\n")
    vid = upsert_version(conn, provider=PROVIDER, tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet",
                         kind="auto", rating=0, votes=0, version=1, label=None, url="", raw={}, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt", data=text.encode(), rank=1)
    ug_version(conn, song, B, rating=4.8, votes=100, number=1)
    render(conn, cfg)
    data = page_data(folder_of(cfg, song) / "sheet (auto).html")["versions"]
    assert data["sheet"] == PROVIDER
    assert [v["tab"] for v in data["list"]] == [str(B)]


def test_a_song_with_no_ug_chords_versions_carries_no_list(conn, cfg):
    song = add_song(conn, "Placeholder Banda", "Canción Sintética")
    tab_id = "placeholder_banda/cancion_sintetica-3"
    url = f"https://acordes.lacuerda.net/{tab_id}.shtml"
    vid = upsert_version(conn, provider="lacuerda", tab_id=tab_id, song_id=song.id, slot="sheet", kind="acordes",
                         rating=0, votes=0, version=3, label=None, url=url, raw={}, now=FETCHED)
    content = sheet("lacuerda")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.json",
              data=json.dumps({"provider": "lacuerda", "url": url, "version": 3, "content": content}).encode(), rank=1)
    render(conn, cfg)
    assert "versions" not in page_data(folder_of(cfg, song) / "sheet.html")


# --- a version leaving the set ----------------------------------------------------------------------------


def test_a_version_leaving_the_set_takes_its_page_along(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    for name in version_names(str(C))[:2]:  # the fetch dropped it (ug/fetch.py)
        drop_file(conn, cfg.library_dir, song=song, name=name)
    render(conn, cfg)
    assert not (folder / version_names(str(C))[2]).exists()
    assert written_file(conn, song.id, version_names(str(C))[2]) is None
    assert (folder / version_names(str(B))[2]).is_file()
    listed = {v["tab"]: v for v in page_data(folder / "sheet.html")["versions"]["list"]}
    assert listed[str(C)]["kept"] is False and listed[str(C)]["page"] is None


def test_a_version_page_changed_since_stays_when_its_version_leaves(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    page = folder_of(cfg, song) / version_names(str(C))[2]
    page.write_text("my own notes", encoding="utf-8")  # on a synced device
    for name in version_names(str(C))[:2]:
        drop_file(conn, cfg.library_dir, song=song, name=name)
    render(conn, cfg)
    assert page.read_text("utf-8") == "my own notes"
    assert written_file(conn, song.id, page.name) is None


def test_a_song_that_keeps_no_sheet_any_more_drops_its_version_pages_too(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    for name in ("sheet.txt", "sheet.json", *version_names(str(B))[:2], *version_names(str(C))[:2]):
        drop_file(conn, cfg.library_dir, song=song, name=name)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    assert not [p.name for p in folder.iterdir() if p.name.startswith("version-")]


# --- caracole remove --------------------------------------------------------------------------------------


def test_removing_a_song_deletes_every_version_file_and_nothing_else(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    (folder / "my notes.txt").write_text("mine", encoding="utf-8")
    (folder / "version-mine.pdf").write_bytes(b"%PDF-1.4 mine")  # a name like caracole's, not its own
    versions = {n for tab in (B, C) for n in version_names(str(tab))}
    plan = plan_removal(conn, cfg, song)
    assert versions <= set(plan.delete)
    assert {"my notes.txt", "version-mine.pdf"} <= {name for name, _ in plan.keep}
    remove_song(conn, cfg, plan)
    assert sorted(p.name for p in folder.iterdir()) == ["my notes.txt", "version-mine.pdf"]


def test_removing_a_song_takes_a_version_page_whose_version_has_left_the_set(conn, cfg):
    song = song_with_versions(conn, cfg)
    render(conn, cfg)
    for name in version_names(str(C))[:2]:  # dropped by the fetch; the next render hasn't run
        drop_file(conn, cfg.library_dir, song=song, name=name)
    plan = plan_removal(conn, cfg, song)
    assert version_names(str(C))[2] in plan.delete


def test_a_version_page_no_render_wrote_is_not_caracoles_to_remove(conn, cfg):
    # the version's text and JSON are kept, but no render has written its page: one by that name is yours
    song = song_with_versions(conn, cfg)
    folder = folder_of(cfg, song)
    page = folder / version_names(str(B))[2]
    page.write_text("<p>mine</p>", encoding="utf-8")
    plan = plan_removal(conn, cfg, song)
    assert page.name not in plan.delete
    assert page.name in {name for name, _ in plan.keep}
    remove_song(conn, cfg, plan)
    assert [p.name for p in folder.iterdir()] == [page.name]


# --- what the fetch keeps (ug/fetch.py), rendered --------------------------------------------------------


def fetched(conn, cfg, tmp_path, *, same=None):
    """A song fetched from a fake UG (test_fetch_versions.py's four versions): 101 the sheet, the next two
    kept beside it, as ug/fetch.py writes them; ``cfg`` with the library the fetch wrote."""
    import dataclasses

    from test_fetch import FakeUG, accepted, context
    from test_fetch_versions import four_chords

    from caracole.songs import get_song
    from caracole.ug.fetch import process_song

    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug, same=same)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), get_song(conn, song.id))
    return song, dataclasses.replace(cfg, library_dir=tmp_path / "lib")


def test_the_versions_the_fetch_keeps_get_their_pages(conn, cfg, tmp_path):
    song, cfg = fetched(conn, cfg, tmp_path)
    render(conn, cfg)
    folder = folder_of(cfg, song)
    assert sorted(p.name for p in folder.glob("version-*.html")) == ["version-102.html", "version-103.html"]
    data = page_data(folder / "version-102.html")["versions"]
    assert [(v["tab"], v["page"], v["this"]) for v in data["list"]] == [
        ("101", "sheet.html", False), ("102", "version-102.html", True), ("103", "version-103.html", False),
        ("104", None, False)]
    assert data["sheet"] == "ug"
    assert '<p class="l">sheet 102</p>' in (folder / "version-102.html").read_text("utf-8")  # its own text


def test_a_version_whose_text_is_the_sheets_gets_no_page_and_opens_the_sheets(conn, cfg, tmp_path):
    # Review Focus 1: tab 102 is 101's very text. It's kept as sheet.html, and no page of its own is made
    song, cfg = fetched(conn, cfg, tmp_path, same=(101, 102))
    render(conn, cfg)
    folder = folder_of(cfg, song)
    assert [p.name for p in folder.glob("version-*.html")] == ["version-103.html"]
    for page in ("sheet.html", "version-103.html"):
        listed = {v["tab"]: (v["kept"], v["page"]) for v in page_data(folder / page)["versions"]["list"]}
        assert listed["102"] == (True, "sheet.html")
    mine = [v["tab"] for v in page_data(folder / "sheet.html")["versions"]["list"] if v["this"]]
    assert mine == ["101"]
