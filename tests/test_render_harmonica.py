"""render.py's page for each harmonica tab a song keeps (harptabs_fetch.py: ``harmonica-N.txt``): ``harmonica-N.html``
beside it (viewer/harptab_page.py), recorded as a viewer is, linked from the song's viewers, gone with its tab, and
caracole's to remove."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

from caracole.library import drop_file, keep_file, song_dir, write_atomic
from caracole.overrides import Overrides
from caracole.removal import plan_removal, remove_song
from caracole.render import render_all, written_file
from caracole.ug.page import strip_markup
from caracole.versions import upsert_version

from conftest import add_song
from helpers.rendered import fake_chordpro
from helpers.ug_pages import version_dict
from test_viewer_harpfit import LINES, a_tab

FETCHED = "2026-10-27T03:30:00Z"
TAB_URL = "https://www.harptabs.com/tab/588/synthetic-song"


def keep_sheet(conn, cfg, song, chord: str = "D", tonality: str = "Bm") -> None:
    """A UG chords sheet playing ``chord`` under each of the tab's lines (synthetic), kept as the fetch keeps one."""
    content = "".join(f"[tab][ch]{chord}[/ch]\r\n{line}[/tab]\r\n" for line in LINES)
    raw = version_dict(91000 + song.id, song=song.title, artist=song.artist, tonality_name=tonality)
    vid = upsert_version(conn, provider="ug", tab_id=str(raw["id"]), song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    doc = {"version": raw, "content": content, "url": raw["tab_url"], "meta": []}
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json", json.dumps(doc, ensure_ascii=False).encode())


def keep_tab(conn, cfg, song, text: str = a_tab(), number: int = 1, key: str | None = "C") -> None:
    """A harmonica tab kept as harptabs_fetch.py keeps one."""
    vid = upsert_version(conn, provider="harptabs", tab_id=str(588 + number), song_id=song.id, slot="guitar",
                         kind="harmonica", rating=3.3, votes=224000, version=1, label=None, url=TAB_URL,
                         raw={"title": song.title, "artist": song.artist, "key": key, "harp": None,
                              "difficulty": "Beginner", "views": 224000, "rating": 3.3}, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=f"harmonica-{number}.txt",
              data=text.encode("utf-8"), rank=number)


def render(conn, cfg, runner=fake_chordpro, failed: int = 0):
    stats = render_all(conn, cfg, Overrides(), runner=runner)
    assert stats.failed == failed, stats
    return stats


def song_with_a_tab(conn, cfg, *, sheet: bool = True):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    if sheet:
        keep_sheet(conn, cfg, song)
    keep_tab(conn, cfg, song)
    return song


def data_of(path, block: str) -> dict:
    found = re.search(rf'<script type="application/json" id="{block}">(.*?)</script>', path.read_text("utf-8"), re.S)
    assert found, path
    return json.loads(found.group(1))


def facts(path) -> str:
    found = re.search(r'<p class="facts" id="facts">(.*?)</p>', path.read_text("utf-8"), re.S)
    return re.sub(r"<[^>]+>", "", found.group(1))


def test_a_kept_tab_gets_its_page_beside_it_recorded_and_linked_from_the_songs_viewer(conn, cfg):
    song = song_with_a_tab(conn, cfg)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    page = folder / "harmonica-1.html"
    data = page.read_bytes()
    assert written_file(conn, song.id, page.name) == (hashlib.sha256(data).hexdigest(), len(data))
    # the sheet plays D under every line the tab blows C E G on: a D harp with the record, in B minor the 4th position
    assert facts(page) == "Harmonica tab · D harp with the record (4th position, aeolian)"
    assert '<a class="back" href="sheet.html">‹ Chord sheet</a>' in page.read_text("utf-8")
    assert f'<a href="{TAB_URL}">harptabs.com</a>' in page.read_text("utf-8")
    assert data_of(page, "harp-data")["why"] == {"2": "with the record", "0": "harptabs.com's key"}
    assert data_of(folder / "sheet.html", "song")["harmonicaTabs"] == [
        {"name": "harmonica-1.txt", "href": "harmonica-1.txt", "page": "harmonica-1.html", "key": "C"}]


def test_the_songs_viewer_starts_its_overlay_on_the_harp_its_tab_plays_on(conn, cfg):
    song = song_with_a_tab(conn, cfg)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    # the D harp, with the record: three semitones above B, the key the sheet sounds in, on the viewer and the tab's page
    assert data_of(folder / "sheet.html", "song")["harpTabs"] == [3]
    assert data_of(folder / "harmonica-1.html", "harp-data")["overlay"]["harp"]["tabs"] == [3]


def test_a_tab_whose_harp_the_page_only_guesses_marks_no_harp_on_the_songs_viewer(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    keep_sheet(conn, cfg, song)
    keep_tab(conn, cfg, song, "4 5 6\nwords no line of the sheet has\n")  # harptabs.com's key, C: a guess
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    assert "harpTabs" not in data_of(folder / "sheet.html", "song")
    assert data_of(folder / "harmonica-1.html", "harp-data")["start"] == 0


def test_a_song_with_a_tab_and_no_sheet_gets_its_page_and_goes_back_to_the_library(conn, cfg):
    song = song_with_a_tab(conn, cfg, sheet=False)
    render(conn, cfg)
    page = song_dir(cfg.library_dir, song) / "harmonica-1.html"
    assert facts(page) == "Harmonica tab · C harp, as harptabs.com's key says"
    assert '<a class="back" href="../../index.html">‹ Library</a>' in page.read_text("utf-8")
    assert not (song_dir(cfg.library_dir, song) / "sheet.html").exists()


def test_each_tab_its_own_page(conn, cfg):
    song = song_with_a_tab(conn, cfg)
    keep_tab(conn, cfg, song, "-4 -4 5\nla la la\n", number=2, key=None)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    assert {p.name for p in folder.iterdir() if p.name.startswith("harmonica-")} == {
        "harmonica-1.txt", "harmonica-1.html", "harmonica-2.txt", "harmonica-2.html"}
    assert '<a class="pdf" href="harmonica-2.txt">' in (folder / "harmonica-2.html").read_text("utf-8")
    assert [t["page"] for t in data_of(folder / "sheet.html", "song")["harmonicaTabs"]] == [
        "harmonica-1.html", "harmonica-2.html"]


def test_a_page_is_written_again_only_when_its_bytes_change(conn, cfg):
    song = song_with_a_tab(conn, cfg)
    render(conn, cfg)
    page = song_dir(cfg.library_dir, song) / "harmonica-1.html"
    os.utime(page, ns=(1_000_000_000, 1_000_000_000))
    render(conn, cfg)
    assert page.stat().st_mtime_ns == 1_000_000_000
    (song_dir(cfg.library_dir, song) / "harmonica-1.txt").write_text("4 5\nla la\n", encoding="utf-8")  # edited
    render(conn, cfg)
    assert page.stat().st_mtime_ns != 1_000_000_000 and data_of(page, "harp-data")["groups"] == [
        ["note", [[4, "b", 0, 0]]], ["note", [[5, "b", 0, 0]]]]


def test_the_page_goes_with_its_tabs_text_deleted_from_the_folder(conn, cfg):
    song = song_with_a_tab(conn, cfg)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / "harmonica-1.txt").unlink()  # on a synced device
    render(conn, cfg)
    assert not (folder / "harmonica-1.html").exists()
    assert written_file(conn, song.id, "harmonica-1.html") is None


def test_the_page_goes_once_its_tab_is_no_longer_kept_but_one_changed_since_stays(conn, cfg):
    song = song_with_a_tab(conn, cfg)
    keep_tab(conn, cfg, song, "-4 -4 5\nla la la\n", number=2)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / "harmonica-2.html").write_text("my own notes", encoding="utf-8")
    for name in ("harmonica-1.txt", "harmonica-2.txt"):
        drop_file(conn, cfg.library_dir, song=song, name=name)
    render(conn, cfg)
    assert not (folder / "harmonica-1.html").exists()
    assert (folder / "harmonica-2.html").read_text("utf-8") == "my own notes"
    assert written_file(conn, song.id, "harmonica-1.html") is None
    assert written_file(conn, song.id, "harmonica-2.html") is None


def test_a_tab_read_through_a_link_fails_the_song_and_the_last_page_stays(conn, cfg, tmp_path):
    song = song_with_a_tab(conn, cfg)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    before = (folder / "harmonica-1.html").read_bytes()
    secret = tmp_path / "secret.txt"
    secret.write_text("4 5 6\nnot the library's\n", encoding="utf-8")
    (folder / "harmonica-1.txt").unlink()
    (folder / "harmonica-1.txt").symlink_to(secret)
    render(conn, cfg, failed=1)
    assert (folder / "harmonica-1.html").read_bytes() == before
    assert written_file(conn, song.id, "harmonica-1.html") == (hashlib.sha256(before).hexdigest(), len(before))
    assert b"not the library" not in (folder / "harmonica-1.html").read_bytes()


def test_a_sheet_whose_pdf_fails_still_gets_its_tabs_page(conn, cfg):
    song = song_with_a_tab(conn, cfg)

    def failing(cmd, **kwargs):
        return subprocess.CompletedProcess(list(cmd), 1, stdout="", stderr="chordpro: it broke")

    render(conn, cfg, runner=failing, failed=1)
    page = song_dir(cfg.library_dir, song) / "harmonica-1.html"
    assert facts(page) == "Harmonica tab · D harp with the record (4th position, aeolian)"
    assert written_file(conn, song.id, page.name) is not None


def test_a_tab_it_cant_read_gets_a_page_of_its_text(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    keep_tab(conn, cfg, song, "ARMONICA C\n(3)mua (3)do (3)be (3)pi\n")
    render(conn, cfg)
    text = (song_dir(cfg.library_dir, song) / "harmonica-1.html").read_text("utf-8")
    assert '<pre class="tab">ARMONICA C\n(3)mua (3)do (3)be (3)pi</pre>' in text


def test_removing_the_song_deletes_the_page_a_render_wrote_and_not_one_of_yours(conn, cfg):
    song = song_with_a_tab(conn, cfg)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / "harmonica-7.html").write_text("<p>mine</p>", encoding="utf-8")  # a name like caracole's
    plan = plan_removal(conn, cfg, song)
    assert {"harmonica-1.txt", "harmonica-1.html"} <= set(plan.delete)
    assert "harmonica-7.html" in {name for name, _ in plan.keep}
    remove_song(conn, cfg, plan)
    assert sorted(p.name for p in folder.iterdir() if p.name.startswith("harmonica-")) == ["harmonica-7.html"]
