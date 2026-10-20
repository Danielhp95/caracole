"""render_all and ``caracole render``: every kept sheet as ChordPro and as a PDF in your key."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import unicodedata
import zlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from caracole import render as render_module
from caracole.autochords import ChordSegment, build_sheet
from caracole.cli import build_app
from caracole.db import kv_get_json, kv_set_json
from caracole.lacuerda import parse_version_page
from caracole.library import drop_file, keep_file, song_dir, write_atomic, write_info
from caracole.overrides import Overrides, load_overrides
from caracole.render import STYLE_FILE, RenderStats, render_all, written_file
from caracole.songs import get_song, update_song
from caracole.ug.page import strip_markup
from caracole.versions import set_coverage, upsert_version

from conftest import add_song
from helpers.ug_pages import version_dict

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
FETCHED = "2026-10-18T03:00:00Z"

# A UG chords sheet, as wiki_tab.content holds it (synthetic Spanish lyrics).
UG_SHEET = (
    "[Intro]\r\n"
    "[ch]Bm[/ch]  [ch]G[/ch]  [ch]D[/ch]  [ch]A[/ch]\r\n"
    "\r\n"
    "[Verse 1]\r\n"
    "[tab][ch]Bm[/ch]             [ch]G[/ch]\r\n"
    "Una canción de prueba[/tab]\r\n"
    "[tab][ch]D[/ch]                 [ch]A[/ch]\r\n"
    "solo para el analizador[/tab]\r\n"
)

ZH_SHEET = (
    "[Verse]\n"
    "[tab][ch]C[/ch]       [ch]G[/ch]\n"
    "这是一个合成的例子[/tab]\n"
    "[tab][ch]Am[/ch]          [ch]F[/ch]\n"
    "测试歌词第二行[/tab]\n"
)

# A LaCuerda version page as acordes.lacuerda.net writes it (synthetic lyrics): solfège
# chords in <A> tags, each chord line after an empty <div></div>.
LC_PAGE = (
    "<html><body><div id=t_body><PRE>Intro:\n"
    "\n"
    "<div></div><A>Lam</A>-<A>Fa</A>-<A>Do</A>-<A>Sol</A>\n"
    "\n"
    "<div></div><A>Lam</A>             <A>Fa</A>          <A>Do</A>        <A>Sol7</A>\n"
    "Cruzo la plaza,    con el café frío\n"
    "<div></div><A>Rem</A>              <A>Mim</A>       <A>Fa</A>    <A>Sol</A>\n"
    "guardo tu nombre,    y no sé qué hacer\n"
    "</PRE></div></body></html>"
)

# Built with chr() so no editor or tool turns them into invisible literals.
ZWSP, BOM, NOTE = chr(0x200B), chr(0xFEFF), chr(0x266A)


def output_of(cmd) -> Path:
    """The PDF a chordpro command line writes: its --output= option."""
    return Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("--output=")))


class FakeChordPro:
    """Stands in for subprocess.run: records each command and writes a PDF holding its options,
    then the sheet it prints. Like chordpro, it opens both files by name.

    The options in the PDF let a test tell one rendering from another by the file alone.
    """

    def __init__(self, fail: tuple[str, ...] = ()):
        self.calls: list[list[str]] = []
        self.fail = fail  # a .cho whose name or text holds one of these fails, after half a PDF

    def __call__(self, cmd, **kwargs):
        cmd = list(cmd)
        self.calls.append(cmd)
        cho, out = Path(cmd[-1]), output_of(cmd)
        sheet = cho.read_text(encoding="utf-8")
        if any(part in cho.name or part in sheet for part in self.fail):
            out.write_bytes(b"%PDF-1.4 half")
            stderr = "Unhandled fonts detected -- aborted\n"
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr=stderr)
        out.write_bytes(b"%PDF-1.4 fake\n" + "\n".join([*cmd[1:-1], sheet]).encode("utf-8"))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def human_sheet(conn, cfg, song, content=UG_SHEET, *, tab_id=85053, tonality="Bm", meta=None):
    """Keep a UG sheet the way the fetch step does: sheet.txt, plus sheet.json beside it
    holding the raw version JSON, the content and the page's tab_view.meta (UG writes an
    empty one as []). render_all reads only "content" and "meta"."""
    raw = version_dict(tab_id, song=song.title, artist=song.artist, tonality_name=tonality)
    vid = upsert_version(
        conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="sheet", kind="chords",
        rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw, now=FETCHED,
    )
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    doc = {"version": raw, "content": content, "url": raw["tab_url"],
           "meta": meta if meta is not None else []}
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json",
                 json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    return vid


def auto_sheet(conn, cfg, song, *, key=None):
    """Keep an auto-chords sheet the way the autochords step does: 'sheet (auto).txt',
    from a versions row with provider "auto", whose raw data holds the ``key`` heard, if any."""
    text = build_sheet(
        [ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G")],
        title=song.title,
        artist=song.artist,
        synced="[00:00.00]made up words to sing\n[00:04.00]only for the test\n",
    )
    vid = upsert_version(
        conn, provider="auto", tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet",
        kind="auto", rating=0, votes=0, version=1, label=None, url="", raw={"key": key} if key else {},
        now=FETCHED,
    )
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt",
              data=text.encode("utf-8"), rank=1)


def lacuerda_sheet(conn, cfg, song, content, *, n=3):
    """Keep a LaCuerda sheet the way the LaCuerda step does: an "acordes" version whose raw
    JSON (the artist page's lcd code) names no key, and sheet.json holding the markup."""
    tab_id = f"placeholder_banda/cancion_sintetica-{n}"
    url = f"https://acordes.lacuerda.net/{tab_id}.shtml"
    vid = upsert_version(
        conn, provider="lacuerda", tab_id=tab_id, song_id=song.id, slot="sheet",
        kind="acordes", rating=0, votes=0, version=n, label=None, url=url,
        raw={"lcd": "RRT-312", "title": song.title}, now=FETCHED,
    )
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    doc = {"provider": "lacuerda", "url": url, "version": n, "content": content}
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json",
                 json.dumps(doc, ensure_ascii=False).encode("utf-8"))


def overrides(cfg, toml: str) -> Overrides:
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(toml, encoding="utf-8")
    return load_overrides(cfg.overrides_file)


def fake_font(path: Path) -> Path:
    """Just enough of an OpenType (CFF) font to pass render.py's font check."""
    directory = struct.pack(">HHHH", 1, 0, 0, 0) + struct.pack(">4sIII", b"CFF ", 0, 28, 4)
    path.write_bytes(b"OTTO" + directory + bytes(4))
    return path


def pdf_of(cfg, song, name="sheet.pdf") -> Path:
    return song_dir(cfg.library_dir, song) / name


def info_json(cfg, song) -> dict:
    path = song_dir(cfg.library_dir, song) / "info.json"
    assert path.is_file()
    return json.loads(path.read_text(encoding="utf-8"))


def render(conn, cfg, ovr=None, **kwargs) -> RenderStats:
    kwargs.setdefault("runner", FakeChordPro())
    kwargs.setdefault("now", NOW)
    return render_all(conn, cfg, ovr or Overrides(), **kwargs)


# --- what gets written ------------------------------------------------------------------


def test_human_sheet_becomes_chordpro_and_pdf(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera - Remasterizado 2007")
    human_sheet(conn, cfg, song, meta={"capo": 2})
    stats = render(conn, cfg)
    folder = cfg.library_dir / "Soda Stereo" / "De Música Ligera"
    cho = (folder / "sheet.cho").read_text(encoding="utf-8").splitlines()
    assert cho[:4] == [
        "{title: De Música Ligera}", "{artist: Soda Stereo}", "{key: Bm}", "{capo: 2}",
    ]
    assert "[Bm]Una canción de [G]prueba" in cho
    assert (folder / "sheet.pdf").read_bytes().startswith(b"%PDF")
    assert stats == RenderStats(rendered=1, skipped=0, failed=0, font_error=None)


@pytest.mark.parametrize(
    "tonality,capo,head",
    [
        ("Bm", "3", ["{key: Bm}", "{capo: 3}"]),  # UG writes some numbers as digit strings
        ("", 0, []),
        (None, None, []),
        (7, {"fret": 2}, []),
        ("Bm", True, ["{key: Bm}"]),
    ],
)
def test_key_and_capo_read_defensively(conn, cfg, tonality, capo, head):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song, tonality=tonality, meta={"capo": capo})
    assert render(conn, cfg).rendered == 1
    cho = (song_dir(cfg.library_dir, song) / "sheet.cho").read_text(encoding="utf-8").splitlines()
    assert cho[2 : 2 + len(head) + 1] == [*head, "{comment: Intro}"]


def test_auto_sheet_rendered_under_its_own_name(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    stats = render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    assert (folder / "sheet (auto).cho").is_file()
    assert (folder / "sheet (auto).cho").read_text(encoding="utf-8") == (
        "{title: Synthetic Song}\n"
        "{artist: Placeholder Band}\n"
        "{comment: auto-generated, unverified}\n"
        "[C]made up words to sing\n"
        "[G]only for the test\n"
    )
    assert (folder / "sheet (auto).pdf").read_bytes().startswith(b"%PDF")
    assert not (folder / "sheet.cho").exists() and not (folder / "sheet.pdf").exists()
    assert stats.rendered == 1


def complete_human_sheet(conn, cfg, song):
    """A complete human sheet arrives: the fetch step keeps it and retires the auto sheet."""
    vid = human_sheet(conn, cfg, song)
    set_coverage(conn, vid, 1.0)
    drop_file(conn, cfg.library_dir, song=song, name="sheet (auto).txt")


def test_a_complete_human_sheet_replaces_auto_outputs(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    complete_human_sheet(conn, cfg, song)
    stats = render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    assert stats.rendered == 1
    assert "[Bm]Una canción" in (folder / "sheet.cho").read_text(encoding="utf-8")
    assert (folder / "sheet.pdf").is_file() and (folder / "sheet.html").is_file()
    assert not (folder / "sheet (auto).cho").exists()
    assert not (folder / "sheet (auto).pdf").exists()
    assert not (folder / "sheet (auto).html").exists()


def test_auto_outputs_stay_until_the_human_pdf_replaces_them(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    complete_human_sheet(conn, cfg, song)
    folder = song_dir(cfg.library_dir, song)
    assert render(conn, cfg, runner=FakeChordPro(fail=("sheet.cho",))).failed == 1
    assert (folder / "sheet (auto).pdf").is_file()  # still the song's only PDF
    assert (folder / "sheet (auto).cho").is_file()
    assert render(conn, cfg).rendered == 1
    assert not (folder / "sheet (auto).pdf").exists()


def test_auto_outputs_stay_while_the_human_sheet_waits_for_a_font(conn, cfg):
    assert cfg.cjk_font is None
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    vid = human_sheet(conn, cfg, song, f"[ch]G[/ch]\nUna can{chr(0x434)}ión de prueba\n")  # д
    set_coverage(conn, vid, 1.0)
    drop_file(conn, cfg.library_dir, song=song, name="sheet (auto).txt")
    stats = render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    assert stats.font_error is not None and not (folder / "sheet.pdf").exists()
    assert (folder / "sheet (auto).pdf").is_file()  # still the song's only PDF


def test_a_partial_human_sheet_keeps_the_auto_pdf_beside_it(conn, cfg):
    # The fetch step keeps 'sheet (auto).txt' until a complete human sheet arrives, so
    # both are rendered: the auto sheet still has every verse.
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    set_coverage(conn, human_sheet(conn, cfg, song), 0.3)
    stats = render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    assert stats.failed == 0 and stats.rendered >= 1
    for name in ("sheet.cho", "sheet.pdf", "sheet (auto).cho", "sheet (auto).pdf"):
        assert (folder / name).is_file(), name
    assert info_json(cfg, song)["render"] == {"transpose": 0, "pdf": "sheet.pdf"}
    run = FakeChordPro()
    assert render(conn, cfg, runner=run).skipped == 2 and run.calls == []
    down = overrides(cfg, '[transpose]\n"Placeholder Band - Synthetic Song" = -2\n')
    assert render(conn, cfg, down).rendered == 2  # both PDFs are in your key
    assert b"--transpose=-2" in pdf_of(cfg, song, "sheet (auto).pdf").read_bytes()


def test_the_auto_pdf_goes_once_the_human_sheet_proves_complete(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    vid = human_sheet(conn, cfg, song)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    assert (folder / "sheet (auto).pdf").is_file()  # coverage unknown: no lyrics yet
    set_coverage(conn, vid, 0.95)
    drop_file(conn, cfg.library_dir, song=song, name="sheet (auto).txt")  # as rescoring does
    render(conn, cfg)
    assert not (folder / "sheet (auto).pdf").exists() and not (folder / "sheet (auto).cho").exists()
    assert (folder / "sheet.pdf").is_file()
    assert kv_get_json(conn, f"render:{song.id}:auto") is None


def drop_human_sheet(conn, cfg, song):
    """The fetch drops the song's UG sheet: its match was undone ([reject], a corrected [match])."""
    for name in ("sheet.txt", "sheet.json"):
        drop_file(conn, cfg.library_dir, song=song, name=name)


@pytest.mark.parametrize("auto", [False, True])
def test_the_cho_and_pdf_of_a_sheet_no_longer_kept_go(conn, cfg, auto):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    if auto:
        auto_sheet(conn, cfg, song)
    set_coverage(conn, human_sheet(conn, cfg, song), 0.3)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / "notes.txt").write_text("yours", encoding="utf-8")  # untracked: never caracole's to delete
    drop_human_sheet(conn, cfg, song)

    render(conn, cfg)

    assert not (folder / "sheet.cho").exists() and not (folder / "sheet.pdf").exists()
    assert not (folder / "sheet.html").exists()
    assert (folder / "sheet (auto).html").is_file() is auto
    record = kv_get_json(conn, f"render:{song.id}")  # the auto sheet's now, if there is one
    assert (record or {}).get("pdf") == ("sheet (auto).pdf" if auto else None)
    assert (folder / "sheet (auto).pdf").is_file() is auto
    assert (folder / "notes.txt").read_text(encoding="utf-8") == "yours"
    assert info_json(cfg, song)["render"] == ({"transpose": 0, "pdf": "sheet (auto).pdf"} if auto else None)


@pytest.mark.parametrize("why", ["no font", "chordpro failed"])
@pytest.mark.parametrize("yours", [False, True], ids=["as-written", "yours"])
def test_the_cho_and_viewer_of_a_sheet_that_never_got_a_pdf_go_with_it(conn, cfg, why, yours):
    assert cfg.cjk_font is None
    if why == "no font":
        song = add_song(conn, "宋冬野", "斑马斑马")
        human_sheet(conn, cfg, song, ZH_SHEET, tonality="")
        assert render(conn, cfg).font_error is not None
    else:
        song = add_song(conn, "Soda Stereo", "De Música Ligera")
        human_sheet(conn, cfg, song)
        assert render(conn, cfg, runner=FakeChordPro(fail=("Música",))).failed == 1
    folder = song_dir(cfg.library_dir, song)
    assert (folder / "sheet.cho").is_file() and (folder / "sheet.html").is_file()
    assert not (folder / "sheet.pdf").exists() and kv_get_json(conn, f"render:{song.id}") is None
    if yours:  # a page of your own, under that name
        (folder / "sheet.html").write_bytes(b"yours")
    drop_human_sheet(conn, cfg, song)

    render(conn, cfg)

    assert not (folder / "sheet.cho").exists()
    assert (folder / "sheet.html").exists() is yours
    if yours:
        assert (folder / "sheet.html").read_bytes() == b"yours"
    assert written_file(conn, song.id, "sheet.html") is None
    assert written_file(conn, song.id, "sheet.cho") is None


def test_a_sheet_pdf_caracole_never_rendered_stays(conn, cfg):
    # No render record names it, so it is yours: a song caracole found no sheet for, say.
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    folder = song_dir(cfg.library_dir, song)
    folder.mkdir(parents=True)
    for name in ("sheet.cho", "sheet.pdf", "sheet.html"):
        (folder / name).write_bytes(b"yours")
    render(conn, cfg)
    assert [(folder / name).read_bytes() for name in ("sheet.cho", "sheet.pdf", "sheet.html")] == [b"yours"] * 3


def test_lacuerda_sheet_gets_letter_chords(conn, cfg):
    song = add_song(conn, "Placeholder Banda", "Canción Sintética")
    lacuerda_sheet(conn, cfg, song, parse_version_page(LC_PAGE))
    assert render(conn, cfg).rendered == 1
    cho = (song_dir(cfg.library_dir, song) / "sheet.cho").read_text(encoding="utf-8")
    assert cho.splitlines() == [
        "{title: Canción Sintética}",
        "{artist: Placeholder Banda}",  # and no key: LaCuerda names none
        "Intro:",
        "",
        "[Am] [F] [C] [G]",
        "",
        "[Am]Cruzo la plaza, [F]   con el ca[C]fé frío   [G7]",
        "[Dm]guardo tu nombre,[Em]    y no s[F]é qué [G]hacer",
    ]


def test_ignored_songs_are_not_rendered(conn, cfg):
    listed = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, listed, tab_id=1)
    marked = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, marked, tab_id=2)
    update_song(conn, marked.id, status="ignored")
    ignore = overrides(cfg, '[ignore]\nsongs = ["Soda Stereo - De Musica Ligera"]\n')
    run = FakeChordPro()
    stats = render(conn, cfg, ignore, runner=run)
    assert run.calls == [] and stats == RenderStats()
    for song in (listed, marked):
        assert not (song_dir(cfg.library_dir, song) / "sheet.cho").exists()


# --- the sheet viewer -----------------------------------------------------------------------


def viewer_of(cfg, song, name="sheet.html") -> str:
    return (song_dir(cfg.library_dir, song) / name).read_text(encoding="utf-8")


def viewer_data(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S).group(1))


def test_every_sheet_gets_a_viewer_beside_its_pdf(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song, meta={"capo": 2})
    render(conn, cfg)
    html = viewer_of(cfg, song)
    assert "<h1>De Música Ligera</h1>" in html and 'href="sheet.pdf"' in html
    assert "Una canción de prueba" not in html  # each word is a column of its own...
    assert ">Una </span>" in html and ">canción </span>" in html  # ...in the song's own folder only
    data = viewer_data(html)
    assert data["key"] == {"tonic": 11, "mode": "aeolian", "from": "from the tab"}
    assert data["capoSheet"] == 2 and data["transpose"] == 0


def test_an_auto_sheet_gets_a_viewer_of_its_own(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    html = viewer_of(cfg, song, "sheet (auto).html")
    assert 'href="sheet%20%28auto%29.pdf"' in html and "unverified" in html
    assert not (song_dir(cfg.library_dir, song) / "sheet.html").exists()


def test_a_viewer_needs_no_cjk_font(conn, cfg, tmp_path):
    assert cfg.cjk_font is None
    song = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, song, ZH_SHEET, tonality="")
    assert render(conn, cfg).font_error is not None
    html = viewer_of(cfg, song)
    assert ">这</span>" in html and not re.search(r'href="[^"]*\.pdf"', html)  # no PDF to link yet
    cfg = replace(cfg, cjk_font=fake_font(tmp_path / "Kai.otf"))
    assert render(conn, cfg).rendered == 1
    assert 'href="sheet.pdf"' in viewer_of(cfg, song)  # and now there is


def test_the_viewer_starts_in_the_key_of_the_pdf(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg, overrides(cfg, '[transpose]\n"Soda Stereo - De Musica Ligera" = 3\n'))
    assert viewer_data(viewer_of(cfg, song))["transpose"] == 3


def test_the_viewer_and_info_json_agree_on_the_key_from_the_first_render(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)  # UG gives Bm
    render(conn, cfg)
    info = info_json(cfg, song)
    assert (info["key"], info["key_source"]) == ("B minor", "tab")
    assert viewer_data(viewer_of(cfg, song))["key"] == {"tonic": 11, "mode": "aeolian", "from": "from the tab"}


def test_the_viewer_takes_the_songs_key(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song, tonality="D")  # UG's key, not the sheet's own Bm
    render(conn, cfg)
    assert viewer_data(viewer_of(cfg, song))["key"] == {"tonic": 2, "mode": "ionian", "from": "from the tab"}


def test_an_auto_sheet_takes_the_key_heard_in_the_audio(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song, key="D")  # C, then G
    render(conn, cfg)
    assert viewer_data(viewer_of(cfg, song, "sheet (auto).html"))["key"] == {
        "tonic": 2, "mode": "ionian", "from": "from the audio",
    }


@pytest.mark.parametrize("tonality", ["Bm", ""])
def test_beside_a_human_sheet_each_viewer_takes_its_own_sheets_key(conn, cfg, tonality):
    # The song's key is the human sheet's, which the auto sheet's chords, as the model heard
    # them, may not be in: another transposition, or the capo.
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)  # C, then G
    set_coverage(conn, human_sheet(conn, cfg, song, tonality=tonality), 0.3)  # in Bm
    render(conn, cfg)
    human = viewer_data(viewer_of(cfg, song))["key"]
    auto = viewer_data(viewer_of(cfg, song, "sheet (auto).html"))["key"]
    assert (human["tonic"], human["mode"]) == (11, "aeolian")
    assert (auto["tonic"], auto["mode"]) in [(0, "ionian"), (7, "ionian")]


def test_a_human_sheet_never_takes_a_key_heard_in_the_audio(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song, key="D")
    set_coverage(conn, human_sheet(conn, cfg, song), 0.3)  # the tab says Bm
    render(conn, cfg)
    assert viewer_data(viewer_of(cfg, song))["key"] == {"tonic": 11, "mode": "aeolian", "from": "from the tab"}
    assert viewer_data(viewer_of(cfg, song, "sheet (auto).html"))["key"]["tonic"] == 2


def test_info_json_is_never_read_through_a_link(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    elsewhere = cfg.state_dir / "elsewhere.json"
    elsewhere.parent.mkdir(parents=True, exist_ok=True)
    elsewhere.write_text(json.dumps({"key": "F#", "key_source": "not yours"}), encoding="utf-8")
    info = song_dir(cfg.library_dir, song) / "info.json"
    info.unlink(missing_ok=True)
    info.symlink_to(elsewhere)
    assert render(conn, cfg).rendered == 1
    html = viewer_of(cfg, song)
    assert viewer_data(html)["key"]["from"] == "from the tab" and "not yours" not in html


def test_odd_chord_names_on_a_sheet_get_their_viewer(conn, cfg):
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    odd = add_song(conn, "Soda Stereo", "Persiana Americana")  # newer: rendered first
    human_sheet(conn, cfg, odd, "[ch]E7+13[/ch]  [ch]Am7b11[/ch]  [ch]C7(#13)[/ch]\nuna prueba\n", tab_id=1)
    stats = render(conn, cfg)
    assert (stats.rendered, stats.failed) == (2, 0)
    assert ">E7+13</b>" in viewer_of(cfg, odd) and ">Am7b11</b>" in viewer_of(cfg, odd)
    assert "<h1>De Música Ligera</h1>" in viewer_of(cfg, good)


def test_a_viewer_that_cant_be_built_never_costs_the_pdfs(conn, cfg, caplog, monkeypatch):
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")  # newer: rendered first
    human_sheet(conn, cfg, bad, tab_id=1)
    real = render_module.build_viewer

    def build_viewer(cho, **kwargs):
        if "Persiana" in cho:
            raise ValueError("a bug in the viewer")
        return real(cho, **kwargs)

    monkeypatch.setattr(render_module, "build_viewer", build_viewer)
    stats = render(conn, cfg)
    assert (stats.rendered, stats.failed) == (2, 1)  # both PDFs; one song without its viewer
    assert pdf_of(cfg, bad).is_file() and pdf_of(cfg, good).is_file()
    assert not (song_dir(cfg.library_dir, bad) / "sheet.html").exists()
    assert "<h1>De Música Ligera</h1>" in viewer_of(cfg, good)
    assert "no viewer for Soda Stereo - Persiana Americana" in caplog.text
    assert "Traceback" in caplog.text and "a bug in the viewer" in caplog.text
    assert "no PDF for" not in caplog.text
    assert kv_get_json(conn, "render:status")["failed"] == ["Soda Stereo - Persiana Americana"]


def test_a_sheet_chordpro_fails_on_still_gets_its_viewer(conn, cfg, caplog):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    stats = render(conn, cfg, runner=FakeChordPro(fail=("Música",)))
    assert stats.failed == 1 and not pdf_of(cfg, song).exists()
    html = viewer_of(cfg, song)
    assert "<h1>De Música Ligera</h1>" in html and not re.search(r'href="[^"]*\.pdf"', html)
    assert "no PDF for Soda Stereo - De Música Ligera" in caplog.text


def recorded(data: bytes) -> tuple[str, int]:
    return hashlib.sha256(data).hexdigest(), len(data)


def test_each_cho_and_viewer_written_is_recorded(conn, cfg):
    # A server serves a viewer only while it is the page caracole wrote: anyone with a synced
    # device could put a sheet.html of their own there, whose script would run as the server's.
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    set_coverage(conn, human_sheet(conn, cfg, song), 0.3)
    render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    for name in ("sheet.cho", "sheet.html", "sheet (auto).cho", "sheet (auto).html"):
        assert written_file(conn, song.id, name) == recorded((folder / name).read_bytes()), name
    assert written_file(conn, song.id, "sheet.pdf") is None  # the PDF has a record of its own
    auto_sheet(conn, cfg, song, key="D")  # the key the model heard arrives
    render(conn, cfg)  # a new key: the auto sheet's viewer changes, and its record with it
    page = (folder / "sheet (auto).html").read_bytes()
    assert b"from the audio" in page
    assert written_file(conn, song.id, "sheet (auto).html") == recorded(page)


def test_a_viewer_that_cant_be_written_is_not_recorded(conn, cfg, private_file):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    page = song_dir(cfg.library_dir, song) / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.symlink_to(private_file)
    assert render(conn, cfg).failed == 1
    assert written_file(conn, song.id, "sheet.html") is None
    assert written_file(conn, song.id, "sheet.cho") is not None


def test_the_records_of_retired_auto_outputs_go_with_them(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    assert written_file(conn, song.id, "sheet (auto).html") is not None
    complete_human_sheet(conn, cfg, song)
    render(conn, cfg)
    assert written_file(conn, song.id, "sheet (auto).html") is None
    assert written_file(conn, song.id, "sheet (auto).cho") is None
    assert written_file(conn, song.id, "sheet.html") is not None


def test_an_unchanged_viewer_is_not_written_again(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    page = song_dir(cfg.library_dir, song) / "sheet.html"
    os.utime(page, ns=(1_000_000_000, 1_000_000_000))
    render(conn, cfg)
    assert page.stat().st_mtime_ns == 1_000_000_000  # one sync fewer on every device
    human_sheet(conn, cfg, song, UG_SHEET.replace("[ch]G[/ch]", "[ch]Em[/ch]"))
    render(conn, cfg)
    assert '<b class="c" data-c="1" tabindex="0" role="button">Em</b>' in page.read_text(encoding="utf-8")


def test_a_lookup_goes_between_two_songs_and_what_it_changed_is_read_again(conn, cfg):
    # A long pass (every PDF again, a new font) holds the lock: a waiting lookup gets it between two songs.
    first = add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-02T00:00:00Z")
    human_sheet(conn, cfg, first, tab_id=1)
    second = add_song(conn, "Soda Stereo", "Persiana Americana", added_at="2026-10-01T00:00:00Z")
    human_sheet(conn, cfg, second, tab_id=2)
    run, turns = FakeChordPro(), []

    def between() -> bool:  # the lock went to a lookup, and you ignored the second song meanwhile
        turns.append(len(run.calls))
        overrides(cfg, '[ignore]\nsongs = ["Soda Stereo - Persiana Americana"]\n')
        return True

    stats = render(conn, cfg, runner=run, between=between)
    assert turns == [1]  # once, between the two songs
    assert stats.rendered == 1 and not pdf_of(cfg, second).exists()


def test_the_nightly_render_and_caracole_render_hand_the_lock_over_between_songs(cfg, monkeypatch, tmp_path):
    import caracole.render
    from caracole.commands import _common
    from caracole.pipeline import _render

    handed, passes = [], []
    monkeypatch.setattr(_common, "hand_over", lambda cfg, conn=None: handed.append(conn is not None) or False)

    def render_all(conn, cfg, overrides, **kwargs):
        passes.append(kwargs["between"]())
        return RenderStats()

    monkeypatch.setattr(caracole.render, "render_all", render_all)
    from caracole import db
    from caracole.pipeline import StepContext

    conn = db.connect(cfg.db_path)
    _render(StepContext(cfg=cfg, conn=conn, overrides=Overrides(), now=NOW, run_id="r", services=None,
                        report=None))
    conn.close()
    config = tmp_path / "caracole.toml"
    config.write_text(f'state_dir = "{cfg.state_dir}"\ncache_dir = "{cfg.cache_dir}"\n'
                      f'library_dir = "{cfg.library_dir}"\n', encoding="utf-8")
    result = CliRunner().invoke(build_app(), ["--config", str(config), "render"])
    assert result.exit_code == 0, result.output
    assert handed == [True, True] and passes == [False, False]


# --- when a PDF is rendered again ------------------------------------------------------------


def test_unchanged_sheet_is_skipped(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    run = FakeChordPro()
    stats = render(conn, cfg, runner=run)
    assert run.calls == []
    assert stats == RenderStats(rendered=0, skipped=1, failed=0, font_error=None)


def test_transposition_from_overrides_rerenders(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    assert b"--transpose" not in pdf_of(cfg, song).read_bytes()
    down = overrides(cfg, '[transpose]\n"Soda Stereo - De Musica Ligera" = -2\n')
    assert render(conn, cfg, down).rendered == 1
    assert b"--transpose=-2" in pdf_of(cfg, song).read_bytes()
    run = FakeChordPro()
    assert render(conn, cfg, down, runner=run).skipped == 1 and run.calls == []


def test_changed_sheet_rerenders(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    human_sheet(conn, cfg, song, UG_SHEET.replace("[ch]A[/ch]", "[ch]E[/ch]"))
    assert render(conn, cfg).rendered == 1
    cho = (song_dir(cfg.library_dir, song) / "sheet.cho").read_text(encoding="utf-8")
    assert "[E]zador" in cho


def test_missing_pdf_rerenders(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    pdf_of(cfg, song).unlink()
    assert render(conn, cfg).rendered == 1
    assert pdf_of(cfg, song).is_file()


@pytest.mark.parametrize("how", ["emptied", "same-size", "linked"])
def test_a_pdf_that_is_no_longer_the_one_rendered_rerenders(conn, cfg, how):
    # "emptied": the rename of a write a power cut caught, with no data behind it.
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    pdf = pdf_of(cfg, song)
    good = pdf.read_bytes()
    twin = pdf.with_name("elsewhere.pdf")
    if how == "emptied":
        pdf.write_bytes(b"")
    elif how == "same-size":
        pdf.write_bytes(bytes(len(good)))
    else:  # a link to a file with the very bytes rendered, which is no reason to trust it
        twin.write_bytes(good)
        pdf.unlink()
        pdf.symlink_to(twin)
    assert render(conn, cfg).rendered == 1
    data, record = pdf.read_bytes(), kv_get_json(conn, f"render:{song.id}")
    assert not pdf.is_symlink() and data.startswith(b"%PDF-1.4 fake") and b"[Bm]Una" in data
    assert (record["pdf_size"], record["pdf_sha256"]) == (len(data), hashlib.sha256(data).hexdigest())
    assert how != "linked" or twin.read_bytes() == good  # the link's target is left as it was
    run = FakeChordPro()
    assert render(conn, cfg, runner=run).skipped == 1 and run.calls == []  # in place again: left alone


def test_a_pdf_whose_record_predates_its_size_and_sha256_rerenders_once(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    key = f"render:{song.id}"
    old = {k: kv_get_json(conn, key)[k] for k in ("source_sha", "transpose", "font", "pdf")}
    kv_set_json(conn, key, old)  # as a caracole that didn't record what it wrote left it
    assert render(conn, cfg).rendered == 1
    assert render(conn, cfg).skipped == 1


def test_force_rerenders_unchanged_sheets(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    run = FakeChordPro()
    stats = render(conn, cfg, runner=run, force=True)
    assert stats.rendered == 1 and len(run.calls) == 1


# --- fonts -----------------------------------------------------------------------------------


def test_cjk_sheet_without_a_font_keeps_its_cho_and_reports_once(conn, cfg):
    assert cfg.cjk_font is None
    songs = [add_song(conn, "宋冬野", "斑马斑马"), add_song(conn, "宋冬野", "安和桥")]
    for tab_id, song in enumerate(songs, start=1):
        human_sheet(conn, cfg, song, ZH_SHEET, tab_id=tab_id, tonality="")
    run = FakeChordPro()
    stats = render(conn, cfg, runner=run)
    for song in songs:
        folder = song_dir(cfg.library_dir, song)
        assert "这是一个" in (folder / "sheet.cho").read_text(encoding="utf-8")
        assert not (folder / "sheet.pdf").exists()
    assert run.calls == []
    assert stats.rendered == 0 and stats.failed == 0
    assert "cjk_font" in stats.font_error and "CARACOLE_CJK_FONT" in stats.font_error
    assert "宋冬野 - 斑马斑马" in stats.font_error


def test_cjk_font_used_only_where_needed(conn, cfg, tmp_path):
    font = fake_font(tmp_path / "Kai.otf")
    cfg = replace(cfg, cjk_font=font)
    zh = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, zh, ZH_SHEET, tab_id=1, tonality="")
    latin = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, latin, tab_id=2)
    stats = render(conn, cfg)
    assert stats.rendered == 2 and stats.font_error is None
    assert f"--define=pdf.fonts.text.file={font}".encode() in pdf_of(cfg, zh).read_bytes()
    assert b"pdf.fonts" not in pdf_of(cfg, latin).read_bytes()


def test_new_cjk_font_rerenders_only_sheets_that_use_it(conn, cfg, tmp_path):
    zh = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, zh, ZH_SHEET, tab_id=1, tonality="")
    latin = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, latin, tab_id=2)
    render(conn, replace(cfg, cjk_font=fake_font(tmp_path / "A.otf")))
    other = fake_font(tmp_path / "B.otf")
    stats = render(conn, replace(cfg, cjk_font=other))
    assert (stats.rendered, stats.skipped) == (1, 1)
    assert f"--define=pdf.fonts.text.file={other}".encode() in pdf_of(cfg, zh).read_bytes()


def test_invisible_characters_need_no_font(conn, cfg, tmp_path):
    cfg = replace(cfg, cjk_font=fake_font(tmp_path / "Kai.otf"))
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song, f"[ch]G[/ch]\n{BOM}Una canción{ZWSP} de prueba\n")
    render(conn, cfg)
    assert b"pdf.fonts" not in pdf_of(cfg, song).read_bytes()


def test_a_stray_symbol_does_not_hold_back_the_pdf(conn, cfg):
    assert cfg.cjk_font is None
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song, f"[ch]G[/ch]\nUna canción de prueba {NOTE}\n")
    stats = render(conn, cfg)
    assert stats.rendered == 1 and stats.font_error is None
    assert pdf_of(cfg, song).is_file()


def test_a_stray_symbol_uses_the_font_when_there_is_one(conn, cfg, tmp_path):
    font = fake_font(tmp_path / "Kai.otf")
    cfg = replace(cfg, cjk_font=font)
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song, f"[ch]G[/ch]\nUna canción de prueba {NOTE}\n")
    render(conn, cfg)
    assert f"--define=pdf.fonts.text.file={font}".encode() in pdf_of(cfg, song).read_bytes()


# UG's Hotel California sheet writes its repeat as "(х2)", with a Cyrillic х (U+0445).
HOTEL = (
    f"[Intro] ({chr(0x445)}2)\n"
    "[ch]Bm[/ch]    [ch]F#[/ch]\n"
    "\n"
    "[Verse 1]\n"
    "[tab][ch]Bm[/ch]               [ch]F#[/ch]\n"
    "On a dark desert highway[/tab]\n"
)


def test_a_stray_letter_that_looks_latin_needs_no_font(conn, cfg):
    assert cfg.cjk_font is None
    song = add_song(conn, "Eagles", "Hotel California")
    human_sheet(conn, cfg, song, HOTEL, tonality="Bm")
    stats = render(conn, cfg)
    assert stats.rendered == 1 and stats.font_error is None
    cho = (song_dir(cfg.library_dir, song) / "sheet.cho").read_text(encoding="utf-8")
    assert "(Intro) (x2)" in cho and chr(0x445) not in cho


def test_a_stray_letter_that_looks_latin_keeps_the_built_in_fonts(conn, cfg, tmp_path):
    # With a CJK font set, the whole English sheet would be set in the Kai brush face.
    cfg = replace(cfg, cjk_font=fake_font(tmp_path / "Kai.otf"))
    song = add_song(conn, "Eagles", "Hotel California")
    human_sheet(conn, cfg, song, HOTEL, tonality="Bm")
    render(conn, cfg)
    assert b"pdf.fonts" not in pdf_of(cfg, song).read_bytes()


def test_letters_that_look_latin_stay_beside_letters_that_dont(conn, cfg, tmp_path):
    # Only a sheet whose every such letter has a Latin twin is rewritten.
    cfg = replace(cfg, cjk_font=fake_font(tmp_path / "Kai.otf"))
    song = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, song, ZH_SHEET + f"({chr(0x445)}2)\n", tonality="")
    render(conn, cfg)
    cho = (song_dir(cfg.library_dir, song) / "sheet.cho").read_text(encoding="utf-8")
    assert f"({chr(0x445)}2)" in cho


def test_the_font_error_names_the_letter_each_sheet_needs(conn, cfg):
    assert cfg.cjk_font is None
    hotel = add_song(conn, "Eagles", "Hotel California")
    human_sheet(conn, cfg, hotel, HOTEL.replace("desert", f"{chr(0x434)}esert"), tab_id=1)  # д
    zh = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, zh, ZH_SHEET, tab_id=2, tonality="")
    stats = render(conn, cfg)
    assert f"Eagles - Hotel California ({chr(0x434)} U+0434)" in stats.font_error
    assert "宋冬野 - 斑马斑马 (斑 U+6591)" in stats.font_error


@pytest.mark.parametrize(
    "data,problem",
    [(b"ttcf" + bytes(60), "font collection"), (None, "font file not found")],
    ids=["collection", "missing"],
)
def test_an_unusable_cjk_font_is_reported_once_like_a_missing_one(
    conn, cfg, tmp_path, data, problem
):
    # Noto CJK, the CJK font NixOS users have at hand, comes only as .ttc collections.
    font = tmp_path / "NotoSansCJK-Regular.ttc"
    if data is not None:
        font.write_bytes(data)
    cfg = replace(cfg, cjk_font=font)
    songs = [add_song(conn, "宋冬野", "斑马斑马"), add_song(conn, "宋冬野", "安和桥")]
    for tab_id, song in enumerate(songs, start=1):
        human_sheet(conn, cfg, song, ZH_SHEET, tab_id=tab_id, tonality="")
    latin = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, latin, f"[ch]G[/ch]\nUna canción de prueba {NOTE}\n", tab_id=3)
    run = FakeChordPro()
    stats = render(conn, cfg, runner=run)
    assert (stats.rendered, stats.failed) == (1, 0)
    assert problem in stats.font_error and "CARACOLE_CJK_FONT" in stats.font_error
    assert "宋冬野 - 斑马斑马" in stats.font_error and "宋冬野 - 安和桥" in stats.font_error
    for song in songs:
        assert (song_dir(cfg.library_dir, song) / "sheet.cho").is_file()
        assert not pdf_of(cfg, song).exists()
    # A stray symbol needs no font, so the Spanish sheet renders without the broken one.
    assert len(run.calls) == 1 and b"pdf.fonts" not in pdf_of(cfg, latin).read_bytes()


# --- failures --------------------------------------------------------------------------------


def test_a_failed_render_is_counted_and_logged_and_the_rest_go_on(conn, cfg, caplog):
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, bad, tab_id=1)
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    stats = render(conn, cfg, runner=FakeChordPro(fail=("Persiana",)))
    assert (stats.rendered, stats.failed) == (1, 1)
    assert pdf_of(cfg, good).is_file() and not pdf_of(cfg, bad).exists()
    assert "Soda Stereo - Persiana Americana" in caplog.text
    assert "Unhandled fonts detected" in caplog.text
    stats = render(conn, cfg)
    assert (stats.rendered, stats.skipped, stats.failed) == (1, 1, 0)


def test_a_failed_rerender_keeps_the_previous_pdf(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    before = pdf_of(cfg, song).read_bytes()
    stats = render(conn, cfg, runner=FakeChordPro(fail=("Música",)), force=True)
    assert stats.failed == 1
    assert pdf_of(cfg, song).read_bytes() == before
    folder = song_dir(cfg.library_dir, song)
    assert [p.name for p in folder.iterdir() if p.name.startswith(".")] == []


def test_another_writers_temporary_files_are_not_in_the_way(conn, cfg):
    # Two caracole processes rendering at once (the nightly run and `caracole render`) shared one
    # temporary name per file, so one's rename found the other's file gone, or in the way.
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    folder = song_dir(cfg.library_dir, song)
    for name in (".sheet.cho.tmp", ".sheet.tmp.pdf"):
        (folder / name).mkdir()  # another writer's, mid-write
    assert render(conn, cfg) == RenderStats(rendered=1)
    assert pdf_of(cfg, song).read_bytes().startswith(b"%PDF")
    assert sorted(p.name for p in folder.iterdir() if p.name.startswith(".")) == [
        ".sheet.cho.tmp", ".sheet.tmp.pdf",
    ]


@pytest.mark.parametrize(
    "doc", [None, b"{not json", b'["a list"]', b'{"meta": []}', b'{"content": "  "}'],
    ids=["missing", "not-json", "not-an-object", "no-content", "blank-content"],
)
def test_unreadable_sheet_json_fails_that_song_only(conn, cfg, caplog, doc):
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, bad, tab_id=1)
    path = song_dir(cfg.library_dir, bad) / "sheet.json"
    if doc is None:
        path.unlink()
    else:
        path.write_bytes(doc)
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    stats = render(conn, cfg)
    assert (stats.rendered, stats.failed) == (1, 1)
    assert "sheet.json" in caplog.text


def test_a_sheet_json_nested_too_deep_fails_that_song_only(conn, cfg, caplog):
    # Any synced device can write one, and the decoder raises RecursionError on it, not ValueError:
    # the song it stops comes first (the newest is rendered first), and the pass goes on after it.
    good = add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-01T00:00:00Z")
    human_sheet(conn, cfg, good, tab_id=2)
    bad = add_song(conn, "Soda Stereo", "Persiana Americana", added_at="2026-10-02T00:00:00Z")
    human_sheet(conn, cfg, bad, tab_id=1)
    (song_dir(cfg.library_dir, bad) / "sheet.json").write_bytes(b"[" * 100_000 + b"]" * 100_000)
    stats = render(conn, cfg)
    assert (stats.rendered, stats.failed) == (1, 1)
    assert pdf_of(cfg, good).is_file() and not pdf_of(cfg, bad).exists()
    assert "nested too deep" in caplog.text


@pytest.mark.parametrize("data", [None, b"\xff\xfe not UTF-8"], ids=["missing", "not-utf8"])
def test_unreadable_auto_sheet_fails_that_song_only(conn, cfg, caplog, data):
    bad = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, bad)
    path = song_dir(cfg.library_dir, bad) / "sheet (auto).txt"
    if data is None:
        path.unlink()
    else:
        path.write_bytes(data)
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good)
    stats = render(conn, cfg)
    assert (stats.rendered, stats.failed) == (1, 1)
    assert "sheet (auto).txt" in caplog.text


# --- others writing to the library -----------------------------------------------------------
#
# The library is writable by the Syncthing group and every synced device. A symbolic link
# planted there must not copy caracole's private files into a .cho or a PDF, nor have one
# written over; a FIFO must not hold up the pass.

SECRET = "refresh-token-s3cr3t"


@pytest.fixture
def private_file(cfg) -> Path:
    """A file only caracole may read, in its state directory. It is shaped like sheet.json, so a
    sheet read through a link to it would carry the secret into the .cho and the PDF."""
    path = cfg.state_dir / "credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"content": SECRET}), encoding="utf-8")
    return path


def library_bytes(cfg) -> bytes:
    """The bytes of every regular file in the library, links not followed."""
    return b"".join(
        p.read_bytes() for p in cfg.library_dir.rglob("*") if not p.is_symlink() and p.is_file()
    )


@pytest.mark.parametrize("planted", ["link", "fifo"])
@pytest.mark.parametrize("name", ["sheet (auto).txt", "sheet.json", "sheet.cho", "sheet.html"])
def test_a_link_or_fifo_in_place_of_a_sheet_fails_that_song_only(
    conn, cfg, caplog, private_file, name, planted
):
    bad = add_song(conn, "Placeholder Band", "Synthetic Song")
    if name == "sheet (auto).txt":
        auto_sheet(conn, cfg, bad)
    else:
        human_sheet(conn, cfg, bad, tab_id=1)
    path = song_dir(cfg.library_dir, bad) / name
    path.unlink(missing_ok=True)
    if planted == "link":
        path.symlink_to(private_file)
    else:
        os.mkfifo(path)  # opened to read, it waits for a writer
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    stats = render(conn, cfg)
    assert SECRET.encode() not in library_bytes(cfg)
    viewer = name == "sheet.html"  # then only the viewer can't be written: the PDF is
    assert (stats.rendered, stats.failed) == ((2, 1) if viewer else (1, 1))
    assert name in caplog.text
    assert ("symbolic link" if planted == "link" else "not a regular file") in caplog.text
    said = "no viewer for" if viewer else "no PDF for"
    assert f"{said} Placeholder Band - Synthetic Song" in caplog.text
    assert pdf_of(cfg, bad).is_file() is viewer
    assert private_file.read_text(encoding="utf-8") == json.dumps({"content": SECRET})


class Watcher(FakeChordPro):
    """Also notes the mode of the directory chordpro opens its files in, while it runs."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.modes: list[int] = []

    def __call__(self, cmd, **kwargs):
        self.modes.append(stat.S_IMODE(Path(cmd[-1]).parent.stat().st_mode))
        return super().__call__(cmd, **kwargs)


def test_chordpro_opens_files_only_in_a_private_directory(conn, cfg):
    # chordpro opens its input and its output by name and follows links: in the song's
    # folder, either could be swapped for a link while it runs.
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=1)
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, bad, tab_id=2)
    run = Watcher(fail=("Persiana",))
    assert render(conn, cfg, runner=run) == RenderStats(rendered=1, failed=1)
    assert len(run.calls) == 2
    for cmd in run.calls:
        cho, out = Path(cmd[-1]), output_of(cmd)
        assert cho.parent == out.parent and cho.parent.parent == cfg.cache_dir
        assert (cho.name, out.name) == ("sheet.cho", "sheet.pdf")
    assert run.modes == [0o700, 0o700]  # only caracole can enter it
    assert list(cfg.cache_dir.iterdir()) == []  # and it is gone, after a failure too
    assert pdf_of(cfg, good).read_bytes().startswith(b"%PDF-1.4 fake")


class Intruder(FakeChordPro):
    """chordpro, raced by someone else who can write to the song's folder: each file it is to
    open there is a link to ``target`` by the time it opens it."""

    def __init__(self, library: Path, target: Path):
        super().__init__()
        self.library, self.target = library, target

    def __call__(self, cmd, **kwargs):
        for path in (Path(cmd[-1]), output_of(cmd)):
            if path.is_relative_to(self.library):
                path.unlink(missing_ok=True)
                path.symlink_to(self.target)
        return super().__call__(cmd, **kwargs)


def test_files_swapped_for_links_while_chordpro_runs_are_not_followed(conn, cfg, private_file):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    assert render(conn, cfg, runner=Intruder(cfg.library_dir, private_file)).rendered == 1
    assert private_file.read_text(encoding="utf-8") == json.dumps({"content": SECRET})
    pdf = pdf_of(cfg, song)
    assert not pdf.is_symlink()
    assert "{title: De Música Ligera}" in pdf.read_bytes().decode("utf-8")  # caracole's own sheet
    assert SECRET.encode() not in library_bytes(cfg)


# --- what the pass records -------------------------------------------------------------------


def test_status_recorded_for_the_todo_page(conn, cfg):
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, bad, tab_id=1)
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    zh = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, zh, ZH_SHEET, tab_id=3, tonality="")
    stats = render(conn, cfg, runner=FakeChordPro(fail=("Persiana",)))
    assert stats.font_error is not None
    assert kv_get_json(conn, "render:status") == {
        "at": "2026-10-18T03:30:00Z",
        "rendered": 1,
        "failed": ["Soda Stereo - Persiana Americana"],
        "font_error": stats.font_error,
        "no_font": {"宋冬野 - 斑马斑马": "斑"},  # its first letter the built-in fonts lack
    }


def test_status_time_defaults_to_now(conn, cfg):
    before = datetime.now(UTC).replace(microsecond=0)
    render_all(conn, cfg, Overrides(), runner=FakeChordPro())
    at = datetime.fromisoformat(kv_get_json(conn, "render:status")["at"])
    assert before <= at <= datetime.now(UTC)


def test_render_record_says_what_the_pdf_was_made_from(conn, cfg, tmp_path):
    font = fake_font(tmp_path / "Kai.otf")
    cfg = replace(cfg, cjk_font=font)
    song = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, song, ZH_SHEET, tonality="")
    render(conn, cfg, overrides(cfg, '[transpose]\n"宋冬野 - 斑马斑马" = 3\n'))
    cho = (song_dir(cfg.library_dir, song) / "sheet.cho").read_bytes()
    pdf = pdf_of(cfg, song).read_bytes()
    assert kv_get_json(conn, f"render:{song.id}") == {
        "source_sha": hashlib.sha256(cho).hexdigest(),
        "transpose": 3,
        "font": str(font),
        "style": hashlib.sha256(STYLE_FILE.read_bytes()).hexdigest(),  # the look of the PDF
        "pdf": "sheet.pdf",
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),  # what was written, to tell it is still there
        "pdf_size": len(pdf),
    }


def test_a_new_pdf_style_rerenders_every_pdf_once(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg)
    key = f"render:{song.id}"
    record = kv_get_json(conn, key)
    kv_set_json(conn, key, {**record, "style": "the look of an older caracole"})
    assert render(conn, cfg).rendered == 1
    record = kv_get_json(conn, key)
    del record["style"]  # a caracole that didn't record it
    kv_set_json(conn, key, record)
    assert render(conn, cfg).rendered == 1
    assert render(conn, cfg).skipped == 1


def test_info_json_records_the_rendered_transposition(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    render(conn, cfg, overrides(cfg, '[transpose]\n"Soda Stereo - De Música Ligera" = -2\n'))
    assert info_json(cfg, song).get("render") == {"transpose": -2, "pdf": "sheet.pdf"}


def test_info_json_keeps_the_render_entry_when_another_step_rewrites_it(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    write_info(conn, cfg.library_dir, get_song(conn, song.id))  # as the fetch step does
    assert info_json(cfg, song).get("render") == {"transpose": 0, "pdf": "sheet (auto).pdf"}


# --- a pass over some songs (a lookup's one song) --------------------------------------------

LATER = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def test_a_pass_over_some_songs_renders_those_alone(conn, cfg):
    mine = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, mine, tab_id=1)
    other = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, other, tab_id=2)
    run = FakeChordPro()

    stats = render(conn, cfg, runner=run, song_ids={mine.id, 9999})  # 9999: no such song (merged, removed)

    assert stats == RenderStats(rendered=1) and len(run.calls) == 1
    assert pdf_of(cfg, mine).is_file()
    assert not any((song_dir(cfg.library_dir, other) / name).exists()
                   for name in ("sheet.cho", "sheet.pdf", "sheet.html"))


def test_a_pass_over_some_songs_leaves_the_last_full_pass_on_the_todo_page(conn, cfg):
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, bad, tab_id=1)
    zh = add_song(conn, "宋冬野", "斑马斑马")  # no CJK font: no PDF, and the pass's font error
    human_sheet(conn, cfg, zh, ZH_SHEET, tab_id=2, tonality="")
    run = FakeChordPro(fail=("Persiana",))
    render(conn, cfg, runner=run)
    nightly = kv_get_json(conn, "render:status")
    assert nightly["failed"] == ["Soda Stereo - Persiana Americana"] and nightly["font_error"]
    new = add_song(conn, "Soda Stereo", "Signos")
    human_sheet(conn, cfg, new, tab_id=3)

    stats = render(conn, cfg, runner=run, now=LATER, song_ids={new.id})

    assert stats == RenderStats(rendered=1)
    assert kv_get_json(conn, "render:status") == nightly  # its time, its counts, the others' failures


def test_a_pass_over_some_songs_brings_their_own_failures_up_to_date(conn, cfg):
    first = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, first, tab_id=1)
    second = add_song(conn, "Soda Stereo", "Signos")
    human_sheet(conn, cfg, second, tab_id=2)
    render(conn, cfg, runner=FakeChordPro(fail=("Persiana", "Signos")))
    assert kv_get_json(conn, "render:status")["failed"] == ["Soda Stereo - Signos", "Soda Stereo - Persiana Americana"]

    render(conn, cfg, runner=FakeChordPro(fail=("Signos",)), now=LATER, song_ids={first.id})  # renders now
    status = kv_get_json(conn, "render:status")
    assert status["failed"] == ["Soda Stereo - Signos"]
    assert (status["at"], status["rendered"]) == ("2026-10-18T03:30:00Z", 0)

    render(conn, cfg, runner=FakeChordPro(fail=("Persiana",)), force=True, song_ids={first.id})  # fails again
    assert kv_get_json(conn, "render:status")["failed"] == ["Soda Stereo - Signos", "Soda Stereo - Persiana Americana"]


def test_a_font_error_of_a_pass_over_some_songs_is_the_one_shown(conn, cfg):
    render(conn, cfg)  # an empty library: a record, no font error
    zh = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, zh, ZH_SHEET, tonality="")

    stats = render(conn, cfg, now=LATER, song_ids={zh.id})

    assert stats.font_error is not None and "宋冬野 - 斑马斑马" in stats.font_error
    assert kv_get_json(conn, "render:status") == {
        "at": "2026-10-18T03:30:00Z", "rendered": 0, "failed": [], "font_error": stats.font_error,
        "no_font": {"宋冬野 - 斑马斑马": "斑"},
    }


def test_a_pass_over_some_songs_keeps_the_others_that_wait_for_a_font(conn, cfg, tmp_path):
    first = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, first, ZH_SHEET, tab_id=1, tonality="")
    second = add_song(conn, "宋冬野", "安和桥")
    human_sheet(conn, cfg, second, ZH_SHEET, tab_id=2, tonality="")
    render(conn, cfg)  # no CJK font: neither gets a PDF

    def waiting() -> list[str]:
        shown = kv_get_json(conn, "render:status")["font_error"] or ""
        return [s.display for s in (first, second) if s.display in shown]

    assert waiting() == [first.display, second.display]
    render(conn, cfg, now=LATER, song_ids={first.id})  # still no font: both still wait
    assert waiting() == [first.display, second.display]
    cfg = replace(cfg, cjk_font=fake_font(tmp_path / "Kai.otf"))
    render(conn, cfg, now=LATER, song_ids={first.id})  # its PDF made: the other one alone waits
    assert waiting() == [second.display]
    render(conn, cfg, now=LATER, song_ids={second.id})
    assert kv_get_json(conn, "render:status")["font_error"] is None


def test_a_record_kept_before_no_font_keeps_its_font_error_until_a_pass_hits_one(conn, cfg):
    old = {"at": "2026-10-18T03:30:00Z", "rendered": 0, "failed": [], "font_error": "set cjk_font to render X"}
    kv_set_json(conn, "render:status", old)  # by a caracole that kept no "no_font"
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song, tab_id=1)
    render(conn, cfg, now=LATER, song_ids={song.id})
    assert kv_get_json(conn, "render:status") == old
    zh = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, zh, ZH_SHEET, tab_id=2, tonality="")
    stats = render(conn, cfg, now=LATER, song_ids={zh.id})
    assert kv_get_json(conn, "render:status") == {**old, "font_error": stats.font_error}


def test_a_pass_over_some_songs_before_any_full_pass_records_itself(conn, cfg):
    song = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, song)

    render(conn, cfg, runner=FakeChordPro(fail=("Persiana",)), song_ids={song.id})

    assert kv_get_json(conn, "render:status") == {
        "at": "2026-10-18T03:30:00Z", "rendered": 0, "failed": ["Soda Stereo - Persiana Americana"],
        "font_error": None, "no_font": {},
    }


# --- caracole render ---------------------------------------------------------------------------

# A stand-in for the chordpro program, run as one: it writes a PDF naming its options,
# and fails on a sheet whose text holds "Persiana".
FAKE_CHORDPRO = """\
#!{python}
import sys

out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
with open(sys.argv[-1], encoding="utf-8") as f:
    sheet = f.read()
if "Persiana" in sheet:
    sys.exit("Unhandled fonts detected -- aborted")
with open(out, "w", encoding="utf-8") as f:
    f.write("%PDF-1.4 fake " + " ".join(sys.argv[1:-1]))
"""


@pytest.fixture
def fake_chordpro(tmp_path) -> Path:
    path = tmp_path / "bin" / "chordpro"
    path.parent.mkdir()
    path.write_text(FAKE_CHORDPRO.format(python=sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


def caracole_render(cfg, chordpro: Path, *args: str):
    """Run ``caracole render`` on the library and database of ``cfg``, with ``chordpro``."""
    toml = cfg.state_dir.parent / "caracole.toml"
    toml.write_text(
        f'library_dir = "{cfg.library_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        f'cache_dir = "{cfg.cache_dir}"\nchordpro_bin = "{chordpro}"\n',
        encoding="utf-8",
    )
    return CliRunner().invoke(
        build_app(), ["--config", str(toml), "render", *args], env={"CARACOLE_CJK_FONT": None}
    )


@pytest.mark.slow
def test_render_command_renders_skips_and_forces(conn, cfg, fake_chordpro):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    first = caracole_render(cfg, fake_chordpro)
    assert first.exit_code == 0, first.output
    assert "1 rendered, 0 up to date, 0 failed" in first.output
    assert pdf_of(cfg, song).read_bytes().startswith(b"%PDF")
    again = caracole_render(cfg, fake_chordpro)
    assert "0 rendered, 1 up to date, 0 failed" in again.output
    forced = caracole_render(cfg, fake_chordpro, "--force")
    assert forced.exit_code == 0, forced.output
    assert "1 rendered, 0 up to date, 0 failed" in forced.output


@pytest.mark.slow
def test_render_command_exits_1_when_a_sheet_fails(conn, cfg, fake_chordpro, caplog):
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, bad, tab_id=1)
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    result = caracole_render(cfg, fake_chordpro)
    assert result.exit_code == 1
    assert "1 rendered, 0 up to date, 1 failed" in result.output
    # The warning says which song and why; the command then needs to add nothing.
    assert "no PDF for Soda Stereo - Persiana Americana" in caplog.text
    assert "Unhandled fonts detected" in caplog.text


@pytest.mark.slow
def test_render_command_renders_one_song_with_song(conn, cfg, fake_chordpro):
    # The step after a web pick's fetch: another song's sheet that fails is not its failure.
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, bad, tab_id=1)
    assert caracole_render(cfg, fake_chordpro).exit_code == 1  # the night's render
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)

    result = caracole_render(cfg, fake_chordpro, "--song", "Soda Stereo - De Música Ligera")

    assert result.exit_code == 0, result.output
    assert "1 rendered, 0 up to date, 0 failed" in result.output
    assert pdf_of(cfg, good).is_file()
    assert kv_get_json(conn, "render:status")["failed"] == ["Soda Stereo - Persiana Americana"]
    unknown = caracole_render(cfg, fake_chordpro, "--song", "Soda Stereo - Zoom")
    assert unknown.exit_code == 1 and 'No song "Soda Stereo - Zoom" in the library' in unknown.output


def test_render_command_with_song_refuses_a_name_that_is_none_and_an_ignored_song(conn, cfg, fake_chordpro):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    bad = caracole_render(cfg, fake_chordpro, "--song", "no dash here")
    assert bad.exit_code == 2, bad.output
    cfg.overrides_file.write_text(f'[ignore]\nsongs = ["{song.display}"]\n', encoding="utf-8")
    ignored = caracole_render(cfg, fake_chordpro, "--song", song.display)
    assert ignored.exit_code == 1 and f'"{song.display}" is ignored in overrides.toml.' in ignored.output
    assert not pdf_of(cfg, song).exists()


@pytest.mark.slow
def test_render_command_with_song_counts_no_songbook_that_fails(conn, cfg, fake_chordpro):
    # A synced device's folder where a songbook's PDF goes: that songbook fails at every render.
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    other = add_song(conn, "Soda Stereo", "Signos")
    human_sheet(conn, cfg, other, tab_id=3)
    (cfg.library_dir / "songbooks.toml").write_text('["Rock"]\nsongs = ["Soda Stereo - Signos"]\n',
                                                     encoding="utf-8")
    (cfg.library_dir / "_songbooks" / "Rock" / "songbook.pdf").mkdir(parents=True)
    night = caracole_render(cfg, fake_chordpro)
    assert night.exit_code == 1 and "Songbooks: 0 rendered, 0 up to date, 1 failed" in night.output

    result = caracole_render(cfg, fake_chordpro, "--song", good.display)

    assert result.exit_code == 0, result.output
    assert "0 rendered, 1 up to date, 0 failed" in result.output
    assert "Songbooks: 0 rendered, 0 up to date, 1 failed" in result.output  # said, but not the song's
    assert pdf_of(cfg, good).is_file()


@pytest.mark.slow
def test_render_command_with_song_counts_no_songbooks_file_that_cant_be_read(conn, cfg, fake_chordpro):
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    (cfg.library_dir / "songbooks.toml").write_text("[[[not toml\n", encoding="utf-8")

    result = caracole_render(cfg, fake_chordpro, "--song", good.display)

    assert result.exit_code == 0, result.output
    assert "1 rendered, 0 up to date, 0 failed" in result.output
    assert "Songbooks: songbooks.toml can't be read" in result.output
    assert pdf_of(cfg, good).is_file()
    assert caracole_render(cfg, fake_chordpro).exit_code == 1  # the library's render counts it


def test_render_command_forces_one_songs_pdfs_alone(conn, cfg, fake_chordpro, monkeypatch):
    import caracole.render
    import caracole.songbook
    from caracole.songbook import SongbookStats

    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    calls = []
    monkeypatch.setattr(caracole.render, "render_all", lambda conn, cfg, overrides, **kwargs: calls.append(
        ("sheets", kwargs["force"], kwargs["song_ids"])) or RenderStats())
    monkeypatch.setattr(caracole.songbook, "render_songbooks", lambda conn, cfg, overrides, *, force: calls.append(
        ("songbooks", force)) or SongbookStats())

    assert caracole_render(cfg, fake_chordpro, "--force", "--song", song.display).exit_code == 0
    assert caracole_render(cfg, fake_chordpro, "--force").exit_code == 0

    assert calls == [("sheets", True, {song.id}), ("songbooks", False), ("sheets", True, None), ("songbooks", True)]


def test_render_command_a_missing_font_is_no_failure(conn, cfg, fake_chordpro, caplog):
    song = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, song, ZH_SHEET, tonality="")
    result = caracole_render(cfg, fake_chordpro)
    assert result.exit_code == 0, result.output
    assert "0 rendered, 0 up to date, 0 failed" in result.output
    assert "set cjk_font or CARACOLE_CJK_FONT to render 宋冬野 - 斑马斑马" in caplog.text


# --- the real chordpro -----------------------------------------------------------------------
#
# These run with chordpro 6.050.7 on PATH (or CARACOLE_CHORDPRO_BIN) and CARACOLE_CJK_FONT set to
# FusionKaiJ-Regular.ttf from nixpkgs lxgw-fusionkai. With poppler's pdftotext on PATH (or
# CARACOLE_PDFTOTEXT) they also read each PDF's text: nix shell nixpkgs#poppler-utils.

CHORDPRO = os.environ.get("CARACOLE_CHORDPRO_BIN") or shutil.which("chordpro")
CJK_FONT = os.environ.get("CARACOLE_CJK_FONT")
PDFTOTEXT = os.environ.get("CARACOLE_PDFTOTEXT") or shutil.which("pdftotext")

real_chordpro = pytest.mark.skipif(
    CHORDPRO is None, reason="chordpro not found on PATH or in CARACOLE_CHORDPRO_BIN"
)
real_cjk_font = pytest.mark.skipif(
    not (CJK_FONT and Path(CJK_FONT).is_file()),
    reason="set CARACOLE_CJK_FONT to a single-font CJK .ttf/.otf, such as FusionKaiJ-Regular.ttf",
)

# A chord name standing alone, as pdftotext lays out chord lines and chord diagrams.
CHORD = re.compile(r"(?<!\S)[A-G][#b]?(?:m|maj|dim|aug|sus)?\d*(?!\S)")
SOLFEGE = re.compile(r"(?<!\S)(?:Do|Re|Mi|Fa|Sol|La|Si)[#b]?m?\d*(?!\S)")


@pytest.fixture
def real(cfg):
    """The config with the real chordpro, and the CJK font when CARACOLE_CJK_FONT names one."""
    font = Path(CJK_FONT) if CJK_FONT and Path(CJK_FONT).is_file() else None
    return replace(cfg, chordpro_bin=CHORDPRO, cjk_font=font)


def pdf_text(pdf: Path) -> str | None:
    """What the PDF shows, as poppler's pdftotext lays it out; None without pdftotext.

    PDF::API2 maps a glyph that the font shares between a Kangxi radical and an
    ideograph to the radical (一 comes out as U+2F00); NFKC maps it back.
    """
    if PDFTOTEXT is None:
        return None
    out = subprocess.run(
        [PDFTOTEXT, "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, check=True
    )
    return unicodedata.normalize("NFKC", out.stdout.decode("utf-8"))


def drawn_strings(pdf: Path) -> set[bytes]:
    """The literal strings that the PDF's pages draw, such as b"Bm" for a chord, unpadded.

    ChordPro sets chord names in a built-in font, as plain strings, so this reads
    them without pdftotext. (The object order of its PDFs varies from run to run,
    so comparing whole files says nothing.)
    """
    strings: set[bytes] = set()
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf.read_bytes(), re.DOTALL):
        try:
            stream = zlib.decompressobj().decompress(m.group(1))
        except zlib.error:
            continue
        if b" Tf" in stream:
            strings |= {s.strip() for s in re.findall(rb"\(((?:\\.|[^\\)])*)\)", stream)}
    return strings


def font_name(font: Path) -> bytes:
    """How a PDF names an embedded font: FusionKaiJ-Regular.ttf is /FusionKaiJ."""
    return font.stem.split("-")[0].encode()


def assert_built_in_fonts(cfg, pdf: Path) -> None:
    """A Latin sheet keeps ChordPro's built-in fonts, even when a CJK font is set."""
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF") and b"/Helvetica" in data
    if cfg.cjk_font is not None:
        assert font_name(cfg.cjk_font) not in data


@pytest.mark.chordpro
@real_chordpro
def test_real_spanish_ug_sheet_transposed_then_skipped(conn, real):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, real, song, meta={"capo": 2})
    assert render_all(conn, real, Overrides()) == RenderStats(rendered=1)
    pdf = pdf_of(real, song)
    assert_built_in_fonts(real, pdf)
    assert {b"Bm", b"G", b"D", b"A"} <= drawn_strings(pdf)
    if (text := pdf_text(pdf)) is not None:
        for shown in ("De Música Ligera", "Soda Stereo · Key Bm · Capo 2",
                      "Una canción de prueba", "solo para el analizador"):
            assert shown in text
        assert set(CHORD.findall(text)) == {"Bm", "G", "D", "A"}

    down = overrides(real, '[transpose]\n"Soda Stereo - De Musica Ligera" = -2\n')
    assert render_all(conn, real, down) == RenderStats(rendered=1)
    drawn = drawn_strings(pdf)
    assert {b"Am", b"F", b"C", b"G"} <= drawn and not {b"Bm", b"D", b"A"} & drawn
    if (text := pdf_text(pdf)) is not None:
        assert "Key Am · Capo 2" in text
        assert set(CHORD.findall(text)) == {"Am", "F", "C", "G"}
    assert info_json(real, song)["render"] == {"transpose": -2, "pdf": "sheet.pdf"}

    stamp = pdf.stat().st_mtime_ns
    assert render_all(conn, real, down) == RenderStats(skipped=1)
    assert pdf.stat().st_mtime_ns == stamp


@pytest.mark.chordpro
@real_chordpro
def test_real_lacuerda_sheet_with_solfege(conn, real):
    song = add_song(conn, "Placeholder Banda", "Canción Sintética")
    lacuerda_sheet(conn, real, song, parse_version_page(LC_PAGE))
    assert render_all(conn, real, Overrides()) == RenderStats(rendered=1)
    pdf = pdf_of(real, song)
    assert_built_in_fonts(real, pdf)
    drawn = drawn_strings(pdf)
    assert {b"Am", b"F", b"C", b"G7", b"Dm", b"Em"} <= drawn
    assert not {b"Lam", b"Fa", b"Do", b"Sol7", b"Rem", b"Mim"} & drawn
    if (text := pdf_text(pdf)) is not None:
        for shown in ("Canción Sintética", "Placeholder Banda", "Cruzo la plaza", "café frío",
                      "guardo tu nombre", "qué hacer"):
            assert shown in text
        assert set(CHORD.findall(text)) == {"Am", "F", "C", "G", "G7", "Dm", "Em"}
        assert SOLFEGE.findall(text) == []


@pytest.mark.chordpro
@real_chordpro
def test_real_english_sheet_with_a_cyrillic_x_keeps_the_built_in_fonts(conn, real):
    song = add_song(conn, "Eagles", "Hotel California")
    human_sheet(conn, real, song, HOTEL, tonality="Bm")
    assert render_all(conn, real, Overrides()) == RenderStats(rendered=1)
    pdf = pdf_of(real, song)
    assert_built_in_fonts(real, pdf)  # not the CJK font, even when one is set
    if (text := pdf_text(pdf)) is not None:
        assert "(x2)" in text and "On a dark desert highway" in text


@pytest.mark.chordpro
@real_chordpro
def test_real_auto_sheet(conn, real):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, real, song)
    assert render_all(conn, real, Overrides()) == RenderStats(rendered=1)
    pdf = pdf_of(real, song, "sheet (auto).pdf")
    assert_built_in_fonts(real, pdf)
    assert {b"C", b"G"} <= drawn_strings(pdf)
    if (text := pdf_text(pdf)) is not None:
        for shown in ("Synthetic Song", "Placeholder Band", "auto-generated, unverified",
                      "made up words to sing", "only for the test"):
            assert shown in text
        assert set(CHORD.findall(text)) == {"C", "G"}


@pytest.mark.chordpro
@real_chordpro
@real_cjk_font
def test_real_chinese_sheet_with_the_cjk_font(conn, real):
    song = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, real, song, ZH_SHEET, tonality="")
    assert render_all(conn, real, Overrides()) == RenderStats(rendered=1)
    pdf = pdf_of(real, song)
    assert font_name(real.cjk_font) in pdf.read_bytes()
    assert {b"C", b"G", b"Am", b"F"} <= drawn_strings(pdf)
    if (text := pdf_text(pdf)) is not None:
        for shown in ("斑马斑马", "宋冬野", "这是一个合成的例子", "测试歌词第二行"):
            assert shown in text
        assert set(CHORD.findall(text)) == {"C", "G", "Am", "F"}
