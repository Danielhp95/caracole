"""The PDFs of a sheet whose words are Chinese (render.py, songbook.py): its own in Simplified characters, as its
viewer starts, and one in Traditional ones beside it, ``sheet (Traditional).pdf``, each recorded as the sheet's PDF
is; an export in the characters its viewer showed; a songbook's PDF and its Traditional one. A sheet in no Chinese
gets no second file. The conversion is the viewer's (viewer/hanzi.py), tested in test_viewer_hanzi.py."""

from __future__ import annotations

from dataclasses import replace

import pytest

from caracole.db import kv_get_json, kv_set_json
from caracole.library import song_dir
from caracole.overrides import Overrides
from caracole.songs import TRADITIONAL_PDFS, is_export

from conftest import add_song
from test_render_all import FakeChordPro, UG_SHEET, fake_font, human_sheet, render, viewer_of

# 宋冬野's 斑马斑马 as UG has it in Traditional characters (two lines of it), and in Simplified ones.
TRADITIONAL = (
    "[Verse]\n"
    "[tab][ch]C[/ch]       [ch]D[/ch]\n"
    "斑馬斑馬 你不要睡著啦[/tab]\n"
    "[tab][ch]Bm[/ch]          [ch]Em[/ch]\n"
    "我只想掀起你的頭髮[/tab]\n"
)
SIMPLIFIED = TRADITIONAL.replace("斑馬斑馬 你不要睡著啦", "斑马斑马 你不要睡着啦").replace("頭髮", "头发")


@pytest.fixture
def zh_cfg(cfg, tmp_path):
    return replace(cfg, cjk_font=fake_font(tmp_path / "Kai.otf"))


def printed(pdf) -> str:
    """The text FakeChordPro printed into a PDF (after its options)."""
    return pdf.read_bytes().decode("utf-8")


def lyric_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if "[" in line and not line.startswith("{")]


def in_simplified(lines: list[str]) -> list[str]:
    """These tests' lines in Simplified characters, by hand."""
    return [line.translate(str.maketrans("馬著頭髮", "马着头发")) for line in lines]


def in_traditional(lines: list[str]) -> list[str]:
    return [line.translate(str.maketrans("马着头发", "馬著頭髮")) for line in lines]


def folder(cfg, song):
    return song_dir(cfg.library_dir, song)


# --- the sheet's PDFs ------------------------------------------------------------------------------------------


def test_a_traditional_sheets_pdf_is_in_simplified_and_its_traditional_one_as_written(conn, zh_cfg):
    song = add_song(conn, "宋冬野", "斑馬斑馬")
    human_sheet(conn, zh_cfg, song, TRADITIONAL, tonality="")
    fake = FakeChordPro()
    render(conn, zh_cfg, runner=fake)
    own, twin = folder(zh_cfg, song) / "sheet.pdf", folder(zh_cfg, song) / "sheet (Traditional).pdf"
    written = lyric_lines((folder(zh_cfg, song) / "sheet.cho").read_text(encoding="utf-8"))
    assert "".join(written).count("馬") == 2  # the sheet's .cho as written: its viewer converts what it shows
    assert lyric_lines(printed(own)) == in_simplified(written)  # each chord where it was
    assert "{title: 斑马斑马}" in printed(own)
    assert lyric_lines(printed(twin)) == written
    assert "{title: 斑馬斑馬}" in printed(twin)
    assert len(fake.calls) == 2
    # Each recorded as the sheet's PDF is, in the characters it is in
    own_record, twin_record = kv_get_json(conn, f"render:{song.id}"), kv_get_json(conn, f"render:{song.id}:trad")
    assert own_record["pdf"] == "sheet.pdf" and own_record["script"] == "simplified"
    assert twin_record["pdf"] == "sheet (Traditional).pdf" and twin_record["script"] == "traditional"
    # Up to date, neither is rendered again
    again = FakeChordPro()
    render(conn, zh_cfg, runner=again)
    assert again.calls == []


def test_a_simplified_sheets_traditional_pdf_is_in_taiwans_characters(conn, zh_cfg):
    song = add_song(conn, "宋冬野", "斑马斑马")
    human_sheet(conn, zh_cfg, song, SIMPLIFIED, tonality="")
    render(conn, zh_cfg)
    own, twin = folder(zh_cfg, song) / "sheet.pdf", folder(zh_cfg, song) / "sheet (Traditional).pdf"
    written = lyric_lines((folder(zh_cfg, song) / "sheet.cho").read_text(encoding="utf-8"))
    assert lyric_lines(printed(own)) == written
    assert lyric_lines(printed(twin)) == in_traditional(written)  # Taiwan's 著 for 着


def test_a_sheet_in_no_chinese_gets_no_second_pdf(conn, zh_cfg):
    song = add_song(conn, "宋冬野", "斑馬")  # Chinese names, Spanish words: as written, one PDF
    human_sheet(conn, zh_cfg, song, UG_SHEET)
    fake = FakeChordPro()
    render(conn, zh_cfg, runner=fake)
    assert len(fake.calls) == 1 and not (folder(zh_cfg, song) / "sheet (Traditional).pdf").exists()
    assert "{title: 斑馬}" in printed(folder(zh_cfg, song) / "sheet.pdf")
    assert "script" not in kv_get_json(conn, f"render:{song.id}")  # its record as before: nothing to make again


def test_the_viewer_links_the_pdf_in_the_characters_it_shows(conn, zh_cfg):
    song = add_song(conn, "宋冬野", "斑馬斑馬")
    human_sheet(conn, zh_cfg, song, TRADITIONAL, tonality="")
    render(conn, zh_cfg)
    html = viewer_of(zh_cfg, song)
    assert '<a class="pdf" href="sheet.pdf" data-trad="sheet%20%28Traditional%29.pdf">PDF</a>' in html


def test_a_pdf_made_before_the_characters_were_chosen_is_made_again_in_simplified(conn, zh_cfg):
    # A Traditional sheet's sheet.pdf, as an older caracole printed it, as written: its record names no script,
    # and its text printed was another, so the next render makes it again, in Simplified.
    song = add_song(conn, "宋冬野", "斑馬斑馬")
    human_sheet(conn, zh_cfg, song, TRADITIONAL, tonality="")
    render(conn, zh_cfg)
    record = kv_get_json(conn, f"render:{song.id}")
    kv_set_json(conn, f"render:{song.id}", {k: v for k, v in record.items() if k != "script"})
    fake = FakeChordPro()
    render(conn, zh_cfg, runner=fake)
    assert [c[-1].rsplit("/", 1)[-1] for c in fake.calls] == ["sheet.cho"]  # the PDF's text, by the PDF's name
    assert kv_get_json(conn, f"render:{song.id}")["script"] == "simplified"


def test_a_sheet_no_longer_chinese_takes_its_traditional_pdf_along_but_one_of_yours_stays(conn, zh_cfg):
    song = add_song(conn, "宋冬野", "斑馬斑馬")
    human_sheet(conn, zh_cfg, song, TRADITIONAL, tonality="")
    render(conn, zh_cfg)
    twin = folder(zh_cfg, song) / "sheet (Traditional).pdf"
    human_sheet(conn, zh_cfg, song, UG_SHEET)  # another sheet in its place, in Spanish
    render(conn, zh_cfg)
    assert not twin.exists() and kv_get_json(conn, f"render:{song.id}:trad") is None
    # Changed on a synced device, it is yours
    human_sheet(conn, zh_cfg, song, TRADITIONAL, tonality="")
    render(conn, zh_cfg)
    twin.write_bytes(b"%PDF-1.4 yours")
    human_sheet(conn, zh_cfg, song, UG_SHEET)
    render(conn, zh_cfg)
    assert twin.read_bytes() == b"%PDF-1.4 yours"


def test_an_auto_sheets_traditional_pdf_is_named_for_it_and_goes_with_it(conn, zh_cfg):
    from caracole.autochords import ChordSegment, build_sheet
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    song = add_song(conn, "宋冬野", "斑馬斑馬")
    text = build_sheet([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G")], title=song.title,
                       artist=song.artist, synced="[00:00.00]斑馬斑馬 你不要睡著啦\n[00:04.00]我只想掀起你的頭髮\n")
    vid = upsert_version(conn, provider="auto", tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet", kind="auto",
                         rating=0, votes=0, version=1, label=None, url="", raw={}, now="2026-10-18T03:00:00Z")
    keep_file(conn, zh_cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt", data=text.encode(), rank=1)
    render(conn, zh_cfg)
    twin = folder(zh_cfg, song) / "sheet (auto, Traditional).pdf"
    assert twin.is_file() and "斑馬斑馬" in printed(twin)
    assert "斑马斑马" in printed(folder(zh_cfg, song) / "sheet (auto).pdf")
    # A complete human sheet in its place: the auto sheet's files go, its Traditional PDF with them
    from test_render_all import complete_human_sheet

    complete_human_sheet(conn, zh_cfg, song)
    render(conn, zh_cfg)
    assert not twin.exists()


def test_the_names_kept_beside_a_sheet_are_no_exports():
    assert set(TRADITIONAL_PDFS.values()) == {"sheet (Traditional).pdf", "sheet (auto, Traditional).pdf"}
    assert not any(is_export(name) for name in TRADITIONAL_PDFS.values())
    assert is_export("sheet (E Minor, Traditional).pdf")


# --- an export -------------------------------------------------------------------------------------------------


def export(conn, cfg, song, query):
    from caracole.render import export_sheet, export_traditional, export_version, render_version

    v = export_version(query, export_sheet(conn, cfg, song).own(Overrides()))
    run = FakeChordPro()
    return render_version(conn, cfg, Overrides(), song, v, runner=run, traditional=export_traditional(query)), run


def test_an_export_is_in_the_characters_its_viewer_showed(conn, zh_cfg):
    from caracole.render import EXPORT_KV

    song = add_song(conn, "宋冬野", "斑馬斑馬")
    human_sheet(conn, zh_cfg, song, TRADITIONAL, tonality="")
    render(conn, zh_cfg)
    simplified, _ = export(conn, zh_cfg, song, "t=2")
    traditional, _ = export(conn, zh_cfg, song, "t=2&trad=1")
    assert traditional.name == simplified.name.removesuffix(").pdf") + ", Traditional).pdf"
    assert "斑马斑马" in printed(simplified) and "斑馬斑馬" in printed(traditional)
    record = kv_get_json(conn, f"{EXPORT_KV}{song.id}")
    queries = sorted(entry["query"] for entry in record.values())
    assert queries == ["t=2", "t=2&trad=1"]
    # A render pass remakes it in its characters, its query saying which
    (traditional).unlink()
    render(conn, zh_cfg)
    assert "斑馬斑馬" in printed(traditional)


def test_an_export_of_a_sheet_in_no_chinese_is_one_file_whichever_the_viewer_showed(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, cfg, song, UG_SHEET)
    render(conn, cfg)
    one, _ = export(conn, cfg, song, "t=2")
    other, _ = export(conn, cfg, song, "t=2&trad=1")
    assert one == other and "Traditional" not in one.name


# --- removal ---------------------------------------------------------------------------------------------------


def test_caracole_remove_takes_the_traditional_pdfs_along(conn, zh_cfg):
    from caracole.removal import plan_removal, remove_song

    song = add_song(conn, "宋冬野", "斑馬斑馬")
    human_sheet(conn, zh_cfg, song, TRADITIONAL, tonality="")
    render(conn, zh_cfg)
    export(conn, zh_cfg, song, "t=2&trad=1")
    names = {p.name for p in folder(zh_cfg, song).iterdir()}
    assert {"sheet (Traditional).pdf"} <= names and any(n.endswith(", Traditional).pdf") for n in names)
    plan = plan_removal(conn, zh_cfg, song)
    remove_song(conn, zh_cfg, plan)
    left = {p.name for p in folder(zh_cfg, song).iterdir()} if folder(zh_cfg, song).exists() else set()
    assert not {name for name in left if name.endswith(".pdf")}, left  # sheet.json stays: the test wrote it unkept


def test_a_traditional_pdf_comes_from_where_its_sheet_came_from():
    from caracole.icons import source_of

    kept = {"sheet.txt": "ug", "sheet (auto).txt": "auto"}
    assert source_of("sheet (Traditional).pdf", kept) == "ug"
    assert source_of("sheet (auto, Traditional).pdf", kept) == "auto"


# --- a songbook ------------------------------------------------------------------------------------------------


def test_a_songbook_with_chinese_gets_its_pdf_in_simplified_and_one_in_traditional(conn, zh_cfg):
    from helpers.songbooks import FakeChordPro as BookChordPro

    from caracole.songbook import make_songbook, remove_from_songbook, render_songbooks, songbooks_file

    zh = add_song(conn, "宋冬野", "斑馬斑馬")
    human_sheet(conn, zh_cfg, zh, TRADITIONAL, tonality="", tab_id=1)
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    human_sheet(conn, zh_cfg, soda, UG_SHEET, tab_id=2)
    render(conn, zh_cfg)
    books = songbooks_file(zh_cfg.library_dir)
    make_songbook(books, "Campfire", ["宋冬野 - 斑馬斑馬", "Soda Stereo - De Música Ligera"])
    render_songbooks(conn, zh_cfg, Overrides(), runner=BookChordPro())
    out = zh_cfg.library_dir / "_songbooks" / "Campfire"
    own, twin = printed(out / "songbook.pdf"), printed(out / "songbook (Traditional).pdf")
    assert "{title: 斑马斑马}" in own and "你不要睡着啦" in own and "斑馬" not in own
    assert "{title: 斑馬斑馬}" in twin and "你不要睡著啦" in twin and "solo para el anali" in twin  # every song
    html = (out / "songbook.html").read_text(encoding="utf-8")
    assert '<a class="pdf" href="songbook.pdf" data-trad="songbook%20%28Traditional%29.pdf">PDF</a>' in html
    assert "songbook (Traditional).pdf" in kv_get_json(conn, "songbook:Campfire")["files"]
    # Without its Chinese song, the songbook has no Traditional PDF
    remove_from_songbook(books, "Campfire", ["宋冬野 - 斑馬斑馬"])
    render_songbooks(conn, zh_cfg, Overrides(), runner=BookChordPro())
    assert not (out / "songbook (Traditional).pdf").exists() and ' data-trad="' not in (out / "songbook.html").read_text()
