"""render_songbooks: each songbook as songbook.pdf, songbook.html and songbook.cho, in Library/_songbooks/."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import zlib
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import add_song
from helpers.songbooks import ZH_SHEET, FakeChordPro, keep_sheet, output_of, render_sheets

from caracole.db import kv_get_json, kv_set_json
from caracole.overrides import load_overrides
from caracole.render import STYLE_FILE
from caracole.songbook import (
    SongbookStats,
    delete_songbook,
    make_songbook,
    move_in_songbook,
    pages_written,
    rename_songbook,
    render_songbooks,
    songbooks_file,
    written_page,
)

CHORDPRO = os.environ.get("CARACOLE_CHORDPRO_BIN") or shutil.which("chordpro")
CJK_FONT = os.environ.get("CARACOLE_CJK_FONT")


def make(cfg, name, *songs):
    return make_songbook(songbooks_file(cfg.library_dir), name, list(songs))


def folder(cfg, name="Campfire") -> Path:
    return cfg.library_dir / "_songbooks" / name


def overrides(cfg, text: str):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(text, encoding="utf-8")
    return load_overrides(cfg.overrides_file)


def render(conn, cfg, ovr=None, runner=None, **kwargs) -> SongbookStats:
    return render_songbooks(conn, cfg, ovr or overrides(cfg, ""), runner=runner or FakeChordPro(), **kwargs)


def pdf_call(fake: FakeChordPro) -> list[str]:
    calls = [c for c in fake.calls if output_of(c).suffix == ".pdf"]
    assert len(calls) == 1, fake.calls
    return calls[0]


def inputs(fake: FakeChordPro, call) -> list[str]:
    """The songs a chordpro run read, in order."""
    return [fake.text(p) for p in fake.inputs(call)]


@pytest.fixture
def two(conn, cfg):
    """Two songs with sheets, rendered, in a songbook named Campfire: Creep, then De Música Ligera."""
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet(conn, cfg, soda, tab_id=1)
    creep = add_song(conn, "Radiohead", "Creep")
    keep_sheet(conn, cfg, creep, tab_id=2, tonality="G")
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "Radiohead - Creep", "Soda Stereo - De Música Ligera")
    return creep, soda


# --- what it makes ---------------------------------------------------------------------------


def test_a_songbook_becomes_a_pdf_a_phone_page_and_a_chordpro_file(conn, cfg, two):
    stats = render(conn, cfg)
    assert stats == SongbookStats(rendered=1, skipped=0, failed=[], font_error=None, error=None)
    out = folder(cfg)
    assert (out / "songbook.pdf").read_bytes().startswith(b"%PDF")
    assert (out / "songbook.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    cho = (out / "songbook.cho").read_text(encoding="utf-8")
    assert cho.index("{title: Creep}") < cho.index("{new_song}") < cho.index("{title: De Música Ligera}")


def test_the_pdf_is_one_chordpro_run_of_every_sheet_in_order_with_caracoles_look(conn, cfg, two):
    fake = FakeChordPro()
    render(conn, cfg, runner=fake)
    call = pdf_call(fake)
    assert call[:3] == [cfg.chordpro_bin, "--nodefaultconfigs", f"--config={STYLE_FILE}"]
    songs = inputs(fake, call)
    assert len(songs) == 2
    assert songs[0].startswith("{title: Creep}\n{artist: Radiohead}")
    assert songs[1].startswith("{title: De Música Ligera}")


def test_chordpro_reads_copies_in_a_private_folder(conn, cfg, two):
    fake = FakeChordPro()
    render(conn, cfg, runner=fake)
    for call in fake.calls:
        for path in [*fake.inputs(call), output_of(call)]:
            assert cfg.cache_dir in path.parents and cfg.library_dir not in path.parents


def test_the_pdf_opens_on_a_title_page_then_the_contents(conn, cfg, two):
    fake = FakeChordPro()
    render(conn, cfg, runner=fake)
    call = pdf_call(fake)
    book = next(Path(a.split("=", 1)[1]) for a in call if a.startswith("--config=") and a != f"--config={STYLE_FILE}")
    config = json.loads(fake.text(book))
    contents = config["contents"]
    assert len(contents) == 1 and contents[0]["fields"] == ["songindex"]  # in the songbook's order
    template = fake.text(book.parent / contents[0]["template"])  # beside the songs: where chordpro looks
    assert template.startswith("{title: Campfire}\n{artist: 2 songs}")
    assert "{new_page}" in template and "{comment: Contents}" in template
    assert config["pdf"]["pagealign-songs"] == 0  # no blank page before a song
    assert config["pdf"]["info"]["title"] == "Campfire"  # the document's name, not its first song's


def test_the_pdfs_document_title_is_the_songbooks_name_never_a_substitution(conn, cfg, two):
    make(cfg, "Camp %{title} {fire}", "Radiohead - Creep")
    fake = FakeChordPro()
    render(conn, cfg, runner=fake, only="Camp %{title} {fire}")
    call = pdf_call(fake)
    book = next(Path(a.split("=", 1)[1]) for a in call if a.startswith("--config=") and a != f"--config={STYLE_FILE}")
    assert json.loads(fake.text(book))["pdf"]["info"]["title"] == "Camp %(title) (fire)"  # as its title page has it


def test_each_song_is_in_its_transposition(conn, cfg, two):
    fake = FakeChordPro()
    render(conn, cfg, overrides(cfg, '[transpose]\n"Radiohead - Creep" = 2\n'), runner=fake)
    creep, soda = inputs(fake, pdf_call(fake))
    assert creep.startswith("{transpose: 2}\n{title: Creep}")  # before {key}, so the key moves too
    assert soda.startswith("{title: De Música Ligera}")
    cho_call = next(c for c in fake.calls if output_of(c).suffix == ".cho")
    assert inputs(fake, cho_call)[0].startswith("{transpose: 2}\n")
    assert "--diagrams=none" in cho_call  # no chord definitions in the file for an app to choke on


def test_songs_without_a_sheet_are_named_missing(conn, cfg, two):
    add_song(conn, "Muse", "Hysteria")  # in the library, no sheet yet
    path = songbooks_file(cfg.library_dir)
    path.write_text('["Campfire"]\nsongs = ["Radiohead - Creep", "Muse - Hysteria", "Gone Band - Removed Song"]\n',
                    encoding="utf-8")
    fake = FakeChordPro()
    stats = render(conn, cfg, runner=fake)
    assert stats.failed == [] and stats.rendered == 1
    creep, hysteria, gone = inputs(fake, pdf_call(fake))
    assert creep.startswith("{title: Creep}")
    assert hysteria.startswith("{title: Hysteria}\n{artist: Muse · missing: no sheet yet}")
    assert gone.startswith("{title: Removed Song}\n{artist: Gone Band · missing: not in the library}")
    cho = (folder(cfg) / "songbook.cho").read_text(encoding="utf-8")
    assert "Hysteria" not in cho and "Removed Song" not in cho  # an app gets the songs it can play
    page = (folder(cfg) / "songbook.html").read_text(encoding="utf-8")
    assert "Hysteria" in page and "no sheet yet" in page and "not in the library" in page


@pytest.fixture
def gig(conn, cfg):
    """The songbook Gig: Karma Police (a sheet), Wonderwall (none), then Karma Police Live, a song
    removed from the library since, whose title holds Karma Police's: a search would take one for the
    other."""
    police = add_song(conn, "Radiohead", "Karma Police")
    keep_sheet(conn, cfg, police, tab_id=3)
    add_song(conn, "Oasis", "Wonderwall")
    live = add_song(conn, "Radiohead", "Karma Police Live")
    render_sheets(conn, cfg)
    make(cfg, "Gig", "Radiohead - Karma Police", "Oasis - Wonderwall", "Radiohead - Karma Police Live")
    conn.execute("DELETE FROM songs WHERE id = ?", (live.id,))
    return police


def test_a_song_gone_from_the_library_is_missing_never_a_song_whose_title_its_own_holds(conn, cfg, gig):
    from caracole.songbook import load_songbooks, songbook_entries

    (book,) = load_songbooks(songbooks_file(cfg.library_dir))
    entries = songbook_entries(conn, cfg.library_dir, overrides(cfg, ""), book)
    assert [(e.song.id if e.song else None, e.missing) for e in entries] == [
        (gig.id, None), (entries[1].song.id, "no sheet yet"), (None, "not in the library")]
    fake = FakeChordPro()
    render(conn, cfg, runner=fake)
    police, wonderwall, live = inputs(fake, pdf_call(fake))
    assert police.startswith("{title: Karma Police}\n")
    assert live.startswith("{title: Karma Police Live}\n{artist: Radiohead · missing: not in the library}")
    page = (folder(cfg, "Gig") / "songbook.html").read_text(encoding="utf-8")
    assert page.count('<section class="song"') == 1  # Karma Police, once
    assert re.search(r'<li class="missing">.*?Karma Police Live.*?Missing: not in the library', page)
    assert (folder(cfg, "Gig") / "songbook.cho").read_text(encoding="utf-8").count("{title: Karma Police}") == 1


def test_a_songbook_with_no_sheet_gets_its_page_alone(conn, cfg):
    add_song(conn, "Muse", "Hysteria")
    make(cfg, "Campfire", "Muse - Hysteria")
    fake = FakeChordPro()
    assert render(conn, cfg, runner=fake).failed == []
    assert fake.calls == []
    assert sorted(p.name for p in folder(cfg).iterdir()) == ["songbook.html"]


def test_an_auto_sheet_stands_in_for_a_missing_human_one(conn, cfg):
    from caracole.autochords import ChordSegment, build_sheet
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    text = build_sheet([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G")], title=song.title,
                       artist=song.artist, synced="[00:00.00]made up words to sing\n")
    vid = upsert_version(conn, provider="auto", tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet",
                         kind="auto", rating=0, votes=0, version=1, label=None, url="", raw={},
                         now="2026-10-18T03:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt",
              data=text.encode("utf-8"), rank=1)
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "Placeholder Band - Synthetic Song")
    fake = FakeChordPro()
    render(conn, cfg, runner=fake)
    (sheet,) = inputs(fake, pdf_call(fake))
    assert "auto-generated, unverified" in sheet


# --- only when something changed ------------------------------------------------------------------


def test_an_unchanged_songbook_is_not_rendered_again(conn, cfg, two):
    render(conn, cfg)
    fake = FakeChordPro()
    stats = render(conn, cfg, runner=fake)
    assert fake.calls == [] and stats.skipped == 1 and stats.rendered == 0


def test_force_renders_it_again(conn, cfg, two):
    render(conn, cfg)
    fake = FakeChordPro()
    assert render(conn, cfg, runner=fake, force=True).rendered == 1
    assert len(fake.calls) == 2


@pytest.mark.parametrize("change", ["order", "sheet", "transpose", "style", "removed", "pdf gone", "pdf changed"])
def test_a_change_renders_it_again(conn, cfg, two, change):
    creep, _ = two
    render(conn, cfg)
    ovr = overrides(cfg, "")
    if change == "order":
        move_in_songbook(songbooks_file(cfg.library_dir), "Campfire", "Soda Stereo - De Música Ligera", 1)
    elif change == "sheet":
        keep_sheet(conn, cfg, creep, "[ch]D[/ch]\nnew words\n", tab_id=2, tonality="D")
        render_sheets(conn, cfg)
    elif change == "transpose":
        ovr = overrides(cfg, '[transpose]\n"Radiohead - Creep" = -3\n')
    elif change == "style":
        key = "songbook:Campfire"
        record = kv_get_json(conn, key)
        record["inputs"]["songbook.pdf"] = "made with an older look"
        kv_set_json(conn, key, record)
    elif change == "removed":
        from caracole.library import drop_file

        drop_file(conn, cfg.library_dir, song=creep, name="sheet.txt")
        render_sheets(conn, cfg)
    elif change == "pdf gone":
        (folder(cfg) / "songbook.pdf").unlink()
    elif change == "pdf changed":
        (folder(cfg) / "songbook.pdf").write_bytes(b"%PDF-1.4 changed on a phone")
    fake = FakeChordPro()
    stats = render(conn, cfg, ovr, runner=fake)
    assert stats.rendered == 1
    assert pdf_call(fake)


def fake_font(path: Path) -> Path:
    directory = struct.pack(">HHHH", 1, 0, 0, 0) + struct.pack(">4sIII", b"CFF ", 0, 28, 4)
    path.write_bytes(b"OTTO" + directory + bytes(4))
    return path


def test_a_chinese_songbook_waits_for_a_font_and_takes_one_when_set(conn, cfg, tmp_path):
    zh = add_song(conn, "宋冬野", "斑马斑马")
    keep_sheet(conn, cfg, zh, ZH_SHEET, tonality="")
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "宋冬野 - 斑马斑马")
    fake = FakeChordPro()
    stats = render(conn, cfg, runner=fake)
    assert stats.font_error and "Campfire" in stats.font_error and "CARACOLE_CJK_FONT" in stats.font_error
    assert not (folder(cfg) / "songbook.pdf").exists()
    assert (folder(cfg) / "songbook.html").exists() and (folder(cfg) / "songbook.cho").exists()

    font = fake_font(tmp_path / "Kai.otf")
    fake = FakeChordPro()
    stats = render(conn, replace(cfg, cjk_font=font), runner=fake)
    assert stats.font_error is None
    call = pdf_call(fake)
    assert f"--define=pdf.fonts.text.file={font}" in call and f"--define=pdf.fonts.toc.file={font}" in call
    assert (folder(cfg) / "songbook.pdf").exists()


def test_a_latin_songbook_keeps_the_built_in_fonts(conn, cfg, two, tmp_path):
    fake = FakeChordPro()
    render(conn, replace(cfg, cjk_font=fake_font(tmp_path / "Kai.otf")), runner=fake)
    assert not any(a.startswith("--define=pdf.fonts") for a in pdf_call(fake))


def test_a_failed_run_is_reported_and_the_rest_goes_on(conn, cfg, two, caplog):
    make(cfg, "Picnic", "Soda Stereo - De Música Ligera")
    stats = render(conn, cfg, runner=FakeChordPro(fail=("Creep",)))
    assert stats.failed == ["Campfire"] and stats.rendered == 1
    assert (folder(cfg, "Picnic") / "songbook.pdf").exists()
    assert "songbook Campfire" in caplog.text and "Unhandled fonts" in caplog.text
    assert (folder(cfg) / "songbook.html").exists()  # the page needs no chordpro


def test_a_file_that_cant_be_written_fails_its_songbook_alone(conn, cfg, two, caplog):
    make(cfg, "Trip", "Radiohead - Creep")
    make(cfg, "Weekend", "Soda Stereo - De Música Ligera")
    (folder(cfg, "Trip") / "songbook.pdf").mkdir(parents=True)  # a synced device put a folder in its place
    stats = render(conn, cfg)
    assert stats.failed == ["Trip"] and stats.rendered == 2
    assert "songbook Trip: no songbook.pdf" in caplog.text
    assert (folder(cfg, "Weekend") / "songbook.pdf").is_file()  # the songbooks after it are made
    trip = kv_get_json(conn, "songbook:Trip")
    assert set(trip["files"]) == {"songbook.cho", "songbook.html"}  # what it wrote, recorded
    assert written_page(conn, "Trip") is not None
    assert "songbook.pdf" not in (folder(cfg, "Trip") / "songbook.html").read_text(encoding="utf-8")


def test_a_songbook_folder_that_cant_be_made_fails_that_songbook_alone(conn, cfg, two, caplog, monkeypatch):
    make(cfg, "Trip", "Radiohead - Creep")
    real = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if self.name == "Trip":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    stats = render(conn, cfg)
    assert stats.failed == ["Trip"] and stats.rendered == 1
    assert "songbook Trip" in caplog.text and "Permission denied" in caplog.text


def test_a_file_of_a_songbook_gone_that_cant_be_removed_is_tried_again_next_time(conn, cfg, two, caplog,
                                                                                  monkeypatch):
    render(conn, cfg)
    delete_songbook(songbooks_file(cfg.library_dir), "Campfire")
    real = Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == "songbook.pdf":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    stats = render(conn, cfg)
    assert stats.removed == 0 and "Permission denied" in caplog.text
    assert kv_get_json(conn, "songbook:Campfire") is not None  # kept, to try again
    monkeypatch.undo()
    assert render(conn, cfg).removed == 1
    assert not folder(cfg).exists()


def test_the_files_written_stay_recorded_when_a_songbook_breaks_off(conn, cfg, two, monkeypatch):
    from caracole.viewer import book

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt  # Ctrl-C while the page is made: the PDF and the .cho are written

    monkeypatch.setattr(book, "build_songbook", interrupted)
    with pytest.raises(KeyboardInterrupt):
        render(conn, cfg)
    record = kv_get_json(conn, "songbook:Campfire")
    assert set(record["files"]) == {"songbook.cho", "songbook.pdf"}


# --- what it records -------------------------------------------------------------------------


def test_the_bytes_written_are_recorded(conn, cfg, two):
    render(conn, cfg)
    page = (folder(cfg) / "songbook.html").read_bytes()
    assert written_page(conn, "Campfire") == (hashlib.sha256(page).hexdigest(), len(page))
    record = kv_get_json(conn, "songbook:Campfire")
    assert record["name"] == "Campfire"
    assert set(record["files"]) == {"songbook.pdf", "songbook.html", "songbook.cho"}


def test_a_server_finds_the_pages_record_by_its_path(conn, cfg, two):
    render(conn, cfg)
    page = (folder(cfg) / "songbook.html").read_bytes()
    record = (hashlib.sha256(page).hexdigest(), len(page))
    assert pages_written(conn, cfg.library_dir, ("_songbooks", "Campfire", "songbook.html")) == [record]
    for parts in (("_songbooks", "Campfire", "songbook.pdf"), ("_songbooks", "..", "index.html"),
                  ("Campfire", "songbook.html"), ("_songbooks", "Picnic", "songbook.html"),
                  ("_songbooks", ".x", "songbook.html"), ("x", "_songbooks", "Campfire", "songbook.html")):
        assert pages_written(conn, cfg.library_dir, parts) == [], parts
    kv_set_json(conn, "songbook:Campfire", {"files": {"songbook.html": {"sha256": record[0], "size": "big"}}})
    assert pages_written(conn, cfg.library_dir, ("_songbooks", "Campfire", "songbook.html")) == []


# --- songbooks that go, and files that aren't caracole's ------------------------------------------------


def test_a_deleted_songbook_takes_its_files_along_but_not_yours(conn, cfg, two):
    make(cfg, "Picnic", "Radiohead - Creep")
    render(conn, cfg)
    (folder(cfg) / "my notes.txt").write_text("mine", encoding="utf-8")
    delete_songbook(songbooks_file(cfg.library_dir), "Campfire")
    delete_songbook(songbooks_file(cfg.library_dir), "Picnic")
    stats = render(conn, cfg)
    assert stats.removed == 2
    assert [p.name for p in folder(cfg).iterdir()] == ["my notes.txt"]
    assert not folder(cfg, "Picnic").exists()
    assert kv_get_json(conn, "songbook:Campfire") is None


def test_a_renamed_songbook_moves_to_its_new_folder(conn, cfg, two):
    render(conn, cfg)
    rename_songbook(songbooks_file(cfg.library_dir), "Campfire", "Beach nights")
    render(conn, cfg)
    assert not folder(cfg).exists()
    assert sorted(p.name for p in folder(cfg, "Beach nights").iterdir()) == [
        "songbook.cho", "songbook.html", "songbook.pdf"]


def test_a_file_changed_on_a_device_stays_when_its_songbook_goes(conn, cfg, two):
    render(conn, cfg)
    (folder(cfg) / "songbook.cho").write_text("{title: mine now}\n", encoding="utf-8")
    delete_songbook(songbooks_file(cfg.library_dir), "Campfire")
    render(conn, cfg)
    assert [p.name for p in folder(cfg).iterdir()] == ["songbook.cho"]


def test_a_broken_songbooks_file_is_an_error_that_stops_nothing_else(conn, cfg, two):
    render(conn, cfg)
    songbooks_file(cfg.library_dir).write_text("[Campfire\n", encoding="utf-8")
    fake = FakeChordPro()
    stats = render(conn, cfg, runner=fake)
    assert stats.error and "songbooks.toml" in stats.error and "line 1" in stats.error
    assert fake.calls == [] and stats.removed == 0
    assert (folder(cfg) / "songbook.pdf").exists()  # your songbooks stay until the file reads again


def test_a_link_in_place_of_the_songbooks_folder_is_never_written_through(conn, cfg, two, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    (cfg.library_dir / "_songbooks").symlink_to(elsewhere)
    stats = render(conn, cfg)
    assert stats.failed == ["Campfire"]
    assert list(elsewhere.iterdir()) == []


def test_a_link_in_place_of_the_songbooks_folder_is_never_removed_through(conn, cfg, two, tmp_path):
    render(conn, cfg)
    books_dir, elsewhere = cfg.library_dir / "_songbooks", tmp_path / "elsewhere"
    shutil.move(books_dir, elsewhere)  # caracole's very files, its record matching them, behind a link
    books_dir.symlink_to(elsewhere, target_is_directory=True)
    delete_songbook(songbooks_file(cfg.library_dir), "Campfire")
    stats = render(conn, cfg)
    assert stats.removed == 0
    assert sorted(p.name for p in (elsewhere / "Campfire").iterdir()) == [
        "songbook.cho", "songbook.html", "songbook.pdf"]
    assert kv_get_json(conn, "songbook:Campfire") is not None  # kept, for when a folder is back
    books_dir.unlink()
    shutil.move(elsewhere, books_dir)
    assert render(conn, cfg).removed == 1 and not folder(cfg).exists()


def test_only_one_songbook_is_rendered_when_asked(conn, cfg, two):
    make(cfg, "Picnic", "Radiohead - Creep")
    stats = render(conn, cfg, only="picnic")
    assert stats.rendered == 1
    assert folder(cfg, "Picnic").exists() and not folder(cfg).exists()


# --- the real chordpro ----------------------------------------------------------------------------

real_chordpro = pytest.mark.skipif(CHORDPRO is None, reason="chordpro not found on PATH or in CARACOLE_CHORDPRO_BIN")


_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _unescape(literal: bytes) -> str:
    """A PDF string literal's text: its escapes undone, its bytes read as the built-in fonts' WinAnsi."""
    def one(m: re.Match[bytes]) -> bytes:
        code = m.group(1)
        return bytes([int(code, 8) & 0xFF]) if code[:1].isdigit() else _ESCAPES.get(code, code)

    return re.sub(rb"\\([0-7]{1,3}|.)", one, literal, flags=re.DOTALL).decode("cp1252", "replace")


def drawn(pdf: Path) -> list[str]:
    """The strings the PDF's pages draw, in order: the built-in fonts write them as literals."""
    strings: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf.read_bytes(), re.DOTALL):
        try:
            stream = zlib.decompressobj().decompress(m.group(1))
        except zlib.error:
            continue
        if b" Tf" in stream:
            strings += [_unescape(s).strip() for s in re.findall(rb"\(((?:\\.|[^\\)])*)\)", stream)]
    return strings


@real_chordpro
def test_the_real_pdf_has_a_title_page_contents_and_every_song_in_its_key(conn, cfg, two):
    cfg = replace(cfg, chordpro_bin=CHORDPRO, cjk_font=None)
    add_song(conn, "Muse", "Hysteria")
    make(cfg, "Picnic", "Radiohead - Creep", "Muse - Hysteria", "Soda Stereo - De Música Ligera")
    stats = render_songbooks(conn, cfg, overrides(cfg, '[transpose]\n"Soda Stereo - De Música Ligera" = 2\n'),
                             only="Picnic")
    assert stats.failed == [], stats
    pdf = folder(cfg, "Picnic") / "songbook.pdf"
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page\b", data)) == 5  # title, contents, 3 songs
    info = re.search(rb"\b%s 0 obj(.*?)endobj" % re.search(rb"/Info (\d+) 0 R", data).group(1), data, re.DOTALL)
    assert re.search(rb"/Title\s*\(Picnic\)", info.group(1))  # the name a viewer or a phone shows
    strings = drawn(pdf)
    assert "Picnic" in strings and "Contents" in strings
    for text in ("Creep", "Hysteria", "Muse · missing: no sheet yet", "De Música Ligera · Soda Stereo"):
        assert text in strings, strings
    assert "Bm" in strings  # De Música Ligera's Am, up 2 (an object's place in the PDF varies, so no order)


@real_chordpro
def test_the_real_chordpro_file_holds_every_song_in_its_key(conn, cfg, two):
    cfg = replace(cfg, chordpro_bin=CHORDPRO, cjk_font=None)
    render_songbooks(conn, cfg, overrides(cfg, '[transpose]\n"Soda Stereo - De Música Ligera" = 2\n'))
    cho = (folder(cfg) / "songbook.cho").read_text(encoding="utf-8")
    first, second = cho.split("{new_song}\n")
    assert "{title: Creep}" in first and "{title: De Música Ligera}" in second
    assert "{key: Bm}" in second and "[Bm]" in second and "[Am]" not in second
    assert "{transpose" not in cho and "#{chord" not in cho


@real_chordpro
@pytest.mark.skipif(not (CJK_FONT and Path(CJK_FONT).is_file()), reason="set CARACOLE_CJK_FONT")
def test_the_real_pdf_of_a_chinese_songbook_embeds_the_font(conn, cfg):
    cfg = replace(cfg, chordpro_bin=CHORDPRO, cjk_font=Path(CJK_FONT))
    zh = add_song(conn, "宋冬野", "斑马斑马")
    keep_sheet(conn, cfg, zh, ZH_SHEET, tonality="")
    render_sheets(conn, cfg)
    make(cfg, "宋冬野的歌", "宋冬野 - 斑马斑马")
    stats = render_songbooks(conn, cfg, overrides(cfg, ""))
    assert stats.failed == [] and stats.font_error is None
    data = (folder(cfg, "宋冬野的歌") / "songbook.pdf").read_bytes()
    assert Path(CJK_FONT).stem.split("-")[0].encode() in data
