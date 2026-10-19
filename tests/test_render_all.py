"""render_all and ``tabarr render``: every kept sheet as ChordPro and as a PDF in your key."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tabarr.autochords import ChordSegment, build_sheet
from tabarr.cli import build_app
from tabarr.db import kv_get_json
from tabarr.lacuerda import parse_version_page
from tabarr.library import keep_file, song_dir, write_atomic, write_info
from tabarr.overrides import Overrides, load_overrides
from tabarr.render import RenderStats, render_all
from tabarr.songs import get_song, update_song
from tabarr.ug.page import strip_markup
from tabarr.versions import upsert_version

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


class FakeChordPro:
    """Stands in for subprocess.run: records each command and writes a PDF holding its options.

    The options in the PDF let a test tell one rendering from another by the file alone.
    """

    def __init__(self, fail: tuple[str, ...] = ()):
        self.calls: list[list[str]] = []
        self.fail = fail  # a .cho path containing one of these fails, after writing half a PDF

    def __call__(self, cmd, **kwargs):
        cmd = list(cmd)
        self.calls.append(cmd)
        out = Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("--output=")))
        if any(part in cmd[-1] for part in self.fail):
            out.write_bytes(b"%PDF-1.4 half")
            stderr = "Unhandled fonts detected -- aborted\n"
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr=stderr)
        out.write_bytes(b"%PDF-1.4 fake\n" + "\n".join(cmd[1:-1]).encode("utf-8"))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def human_sheet(conn, cfg, song, content=UG_SHEET, *, tab_id=85053, tonality="Bm", meta=None):
    """Keep a UG sheet the way the fetch step does: sheet.txt, plus sheet.json beside it
    holding the raw version JSON and the content."""
    raw = version_dict(tab_id, song=song.title, artist=song.artist, tonality_name=tonality)
    vid = upsert_version(
        conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="sheet", kind="chords",
        rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw, now=FETCHED,
    )
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    doc = {**raw, "content": content, "meta": meta if meta is not None else []}
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json",
                 json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    return vid


def auto_sheet(conn, cfg, song):
    """Keep an auto-chords sheet the way the autochords step does: 'sheet (auto).txt',
    from a versions row with provider "auto"."""
    text = build_sheet(
        [ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G")],
        title=song.title,
        artist=song.artist,
        synced="[00:00.00]made up words to sing\n[00:04.00]only for the test\n",
    )
    vid = upsert_version(
        conn, provider="auto", tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet",
        kind="auto", rating=0, votes=0, version=1, label=None, url="", raw={}, now=FETCHED,
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
    return render_all(conn, cfg, ovr or Overrides(), now=NOW, **kwargs)


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


def test_human_sheet_replaces_auto_outputs(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    human_sheet(conn, cfg, song)
    stats = render(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    assert stats.rendered == 1
    assert "[Bm]Una canción" in (folder / "sheet.cho").read_text(encoding="utf-8")
    assert (folder / "sheet.pdf").is_file()
    assert not (folder / "sheet (auto).cho").exists()
    assert not (folder / "sheet (auto).pdf").exists()
    assert (folder / "sheet (auto).txt").is_file()  # the kept auto sheet is the fetch step's


def test_auto_outputs_stay_until_the_human_pdf_replaces_them(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song)
    render(conn, cfg)
    human_sheet(conn, cfg, song)
    folder = song_dir(cfg.library_dir, song)
    assert render(conn, cfg, runner=FakeChordPro(fail=("sheet.cho",))).failed == 1
    assert (folder / "sheet (auto).pdf").is_file()  # still the song's only PDF
    assert (folder / "sheet (auto).cho").is_file()
    assert render(conn, cfg).rendered == 1
    assert not (folder / "sheet (auto).pdf").exists()


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
    assert "cjk_font" in stats.font_error and "TABARR_CJK_FONT" in stats.font_error
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
    assert problem in stats.font_error and "TABARR_CJK_FONT" in stats.font_error
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
    }


def test_status_time_defaults_to_now(conn, cfg):
    before = datetime.now(UTC).replace(microsecond=0)
    render_all(conn, cfg, Overrides(), runner=FakeChordPro())
    at = datetime.fromisoformat(kv_get_json(conn, "render:status")["at"])
    assert before <= at <= datetime.now(UTC)


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


# --- tabarr render ---------------------------------------------------------------------------

# A stand-in for the chordpro program, run as one: it writes a PDF naming its options,
# and fails on a sheet whose path holds "Persiana".
FAKE_CHORDPRO = """\
#!{python}
import sys

out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
if "Persiana" in sys.argv[-1]:
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


def tabarr_render(cfg, chordpro: Path, *args: str):
    """Run ``tabarr render`` on the library and database of ``cfg``, with ``chordpro``."""
    toml = cfg.state_dir.parent / "tabarr.toml"
    toml.write_text(
        f'library_dir = "{cfg.library_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        f'cache_dir = "{cfg.cache_dir}"\nchordpro_bin = "{chordpro}"\n',
        encoding="utf-8",
    )
    return CliRunner().invoke(
        build_app(), ["--config", str(toml), "render", *args], env={"TABARR_CJK_FONT": None}
    )


def test_render_command_renders_skips_and_forces(conn, cfg, fake_chordpro):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song)
    first = tabarr_render(cfg, fake_chordpro)
    assert first.exit_code == 0, first.output
    assert "1 rendered, 0 up to date, 0 failed" in first.output
    assert pdf_of(cfg, song).read_bytes().startswith(b"%PDF")
    again = tabarr_render(cfg, fake_chordpro)
    assert "0 rendered, 1 up to date, 0 failed" in again.output
    forced = tabarr_render(cfg, fake_chordpro, "--force")
    assert forced.exit_code == 0, forced.output
    assert "1 rendered, 0 up to date, 0 failed" in forced.output


def test_render_command_exits_1_when_a_sheet_fails(conn, cfg, fake_chordpro, caplog):
    bad = add_song(conn, "Soda Stereo", "Persiana Americana")
    human_sheet(conn, cfg, bad, tab_id=1)
    good = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, good, tab_id=2)
    result = tabarr_render(cfg, fake_chordpro)
    assert result.exit_code == 1
    assert "1 rendered, 0 up to date, 1 failed" in result.output
    # The warning says which song and why; the command then needs to add nothing.
    assert "no PDF for Soda Stereo - Persiana Americana" in caplog.text
    assert "Unhandled fonts detected" in caplog.text


def test_render_command_a_missing_font_is_no_failure(conn, cfg, fake_chordpro, caplog):
    song = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, cfg, song, ZH_SHEET, tonality="")
    result = tabarr_render(cfg, fake_chordpro)
    assert result.exit_code == 0, result.output
    assert "0 rendered, 0 up to date, 0 failed" in result.output
    assert "set cjk_font or TABARR_CJK_FONT to render 宋冬野 - 斑马斑马" in caplog.text
