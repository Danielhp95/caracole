"""render_songbooks: each songbook as songbook.pdf, songbook.html and songbook.cho, in Library/_songbooks/."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import zlib
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import add_song
from helpers.fonts import PDF_FONTS, font_folder
from helpers.songbooks import SHEET, ZH_SHEET, FakeChordPro, keep_sheet, output_of, render_sheets

from caracole.db import kv_get_json, kv_set_json
from caracole.overrides import load_overrides
from caracole.render import STYLE_FILE
from caracole.songbook import (
    Setting,
    SongbookStats,
    delete_songbook,
    make_songbook,
    move_in_songbook,
    pages_written,
    plays_in,
    rename_songbook,
    render_songbooks,
    set_song_setting,
    songbooks_file,
    with_capo,
    written_page,
)
from caracole.viewer.version import Version

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


def cho_inputs(fake: FakeChordPro) -> list[str]:
    """The songs songbook.cho's chordpro run read, in order."""
    (call,) = [c for c in fake.calls if output_of(c).suffix == ".cho"]
    return inputs(fake, call)


def sung(text: str) -> list[str]:
    """The chords a song's ChordPro sings, in order: those over its words, not its directives."""
    return re.findall(r"\[([^\]]+)\]", "\n".join(line for line in text.splitlines() if not line.startswith("{")))


def page_data(cfg, n: int, name: str = "Campfire") -> dict:
    """The data block of song ``n`` of the songbook's phone page."""
    html = (folder(cfg, name) / "songbook.html").read_text(encoding="utf-8")
    found = re.search(rf'<script type="application/json" id="data-{n}">(.*?)</script>', html, re.DOTALL)
    assert found, f"no data for song {n}"
    return json.loads(found.group(1))


def entries_of(conn, cfg, ovr=None, name: str = "Campfire"):
    from caracole.songbook import find_songbook, load_songbooks, songbook_entries

    book = find_songbook(load_songbooks(songbooks_file(cfg.library_dir)), name)
    return songbook_entries(conn, cfg.library_dir, ovr or overrides(cfg, ""), book)


def set_setting(cfg, song: str, setting, name: str = "Campfire") -> None:
    set_song_setting(songbooks_file(cfg.library_dir), name, song, setting)


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
    cho_call = next(c for c in fake.calls if output_of(c).suffix == ".cho")
    creep_cho, soda_cho = inputs(fake, cho_call)
    for text in (creep, creep_cho):  # moved by caracole, as the viewer names the chords: chordpro moves nothing
        assert text.startswith("{title: Creep}") and "{transpose" not in text
        assert sung(text) == ["Bm", "G", "D", "A"]  # Am, F, C, G, up 2
    assert "{key: A}" in creep_cho  # G, up 2
    for text in (soda, soda_cho):
        assert text.startswith("{title: De Música Ligera}") and sung(text) == ["Am", "F", "C", "G"]
    assert "--diagrams=none" in cho_call  # no chord definitions in the file for an app to choke on
    assert "{define" not in creep_cho


def test_a_songs_own_version_is_its_default_in_a_songbook(conn, cfg, two):
    from caracole.songbook import find_songbook, load_songbooks, songbook_entries
    from caracole.viewer.version import Version, version_from_query

    ovr = overrides(cfg, '[transpose]\n"Radiohead - Creep" = 3\n\n[version]\n"Radiohead - Creep" = "t=2&mode=dorian"\n')
    book = find_songbook(load_songbooks(songbooks_file(cfg.library_dir)), "Campfire")
    creep, soda = songbook_entries(conn, cfg.library_dir, ovr, book)
    assert creep.version == version_from_query("t=2&mode=dorian") and creep.transpose == 2  # [version] wins
    assert soda.version == Version() and soda.transpose == 0


# --- each song in its setting ---------------------------------------------------------------------

SODA = "Soda Stereo - De Música Ligera"
IN_D_MINOR = (  # De Música Ligera's sheet replaced by one a fourth up: Dm, Bb, F, C
    "[Verse 1]\n"
    "[tab][ch]Dm[/ch]          [ch]Bb[/ch]\n"
    "Otra letra de prueba[/tab]\n"
    "[tab][ch]F[/ch]              [ch]C[/ch]\n"
    "solo para el analizador[/tab]\n"
)
NO_KEY = (  # no chord caracole can read, so no key, none estimated
    "[Verse]\n"
    "[tab][ch]N.C.[/ch]       [ch]Hm[/ch]\n"
    "Palabras sin acordes[/tab]\n"
)


def test_a_song_in_g_dorian_is_written_in_g_dorian(conn, cfg, two):
    set_setting(cfg, SODA, Setting("G", "dorian", 0))
    fake = FakeChordPro()
    assert render(conn, cfg, runner=fake).rendered == 1
    creep, soda = inputs(fake, pdf_call(fake))
    creep_cho, soda_cho = cho_inputs(fake)
    for text in (soda, soda_cho):  # the chords themselves, as the viewer names them: chordpro moves nothing
        assert "{transpose" not in text
        assert sung(text) == ["Gm", "Edim", "Bb", "F"]  # Am, F, C, G in A dorian, then down to G
    assert "{subtitle: Soda Stereo · Key G dorian}" in soda.splitlines()
    assert "{define: Edim base-fret 1 frets x x 2 3 x 3 fingers 0 0 1 2 0 3}" in soda  # the viewer's shape
    assert "{key: Gm}" in soda_cho and "{define" not in soda_cho  # for an app: its key, no chord definitions
    assert sung(creep) == sung(creep_cho) == ["Am", "F", "C", "G"]  # a song without a setting stays as it was
    assert page_data(cfg, 2)["start"] == "t=-2&mode=dorian&capo=0"  # the phone page opens it there too
    assert page_data(cfg, 1)["start"] is None
    creep_entry, soda_entry = entries_of(conn, cfg)
    assert plays_in(soda_entry) == "G Dorian"  # the set list's chip
    assert plays_in(creep_entry) == "G Major"  # Creep's key, from its tab
    assert render(conn, cfg).skipped == 1


def test_a_song_without_a_setting_follows_its_own_version(conn, cfg, two):
    ovr = overrides(cfg, f'[version]\n"{SODA}" = "t=2&mode=dorian"\n')
    fake = FakeChordPro()
    render(conn, cfg, ovr, runner=fake)
    _, soda = inputs(fake, pdf_call(fake))
    assert "{transpose" not in soda and sung(soda) == ["Bm", "G#dim", "D", "A"]  # in B dorian
    assert sung(cho_inputs(fake)[1]) == ["Bm", "G#dim", "D", "A"]
    assert page_data(cfg, 2)["start"] == "t=2&mode=dorian"
    # Its version changed: the songbook follows
    ovr = overrides(cfg, f'[version]\n"{SODA}" = "t=-2&mode=dorian"\n')
    fake = FakeChordPro()
    assert render(conn, cfg, ovr, runner=fake).rendered == 1
    assert sung(inputs(fake, pdf_call(fake))[1]) == ["Gm", "Edim", "Bb", "F"]
    assert plays_in(entries_of(conn, cfg, ovr)[1]) == "G Dorian"


def test_a_song_without_a_setting_keeps_its_own_versions_key_on_a_new_sheet(conn, cfg, two):
    # "Make this my version" keeps the key it plays in: a sheet in another key and capo in its place plays there
    _, soda = two
    ovr = overrides(cfg, f'[version]\n"{SODA}" = "key=Gm&mode=dorian&capo=0"\n')
    keep_sheet(conn, cfg, soda, IN_D_MINOR, tab_id=4, tonality="Dm", capo=3)
    render_sheets(conn, cfg, ovr)
    fake = FakeChordPro()
    assert render(conn, cfg, ovr, runner=fake).rendered == 1
    _, text = inputs(fake, pdf_call(fake))
    assert "Otra letra" in text and sung(text) == ["Gm", "Edim", "Bb", "F"]  # D minor shapes, capo 3, up to G
    assert sung(cho_inputs(fake)[1]) == ["Gm", "Edim", "Bb", "F"]
    (_, entry) = entries_of(conn, cfg, ovr)
    assert entry.version.t == 2 and plays_in(entry) == "G Dorian"
    assert page_data(cfg, 2)["start"] == "t=2&mode=dorian&capo=0"
    set_setting(cfg, SODA, Setting(capo=5))  # what a setting leaves out is its own version's: G dorian's sound
    assert plays_in(entries_of(conn, cfg, ovr)[1]) == "D Dorian, capo 5"


def test_a_setting_with_a_key_and_no_mode_takes_no_mode_from_an_own_version_that_chose_none(conn, cfg, two):
    # The song's own version is B minor, two up from its A minor sheet, no mode chosen. A sheet in its place names
    # C major for the same chords: the songbook plays them as its own version did, Bm G D A, never C major's
    # degrees put in B aeolian (G Em Bm F#m). A setting of a key alone is that tonic in the mode the sheet plays,
    # as on top of a move from the sheet (t=2)
    _, soda = two
    ovr = overrides(cfg, f'[version]\n"{SODA}" = "key=Bm&capo=0"\n')
    keep_sheet(conn, cfg, soda, tab_id=4, tonality="C")
    render_sheets(conn, cfg, ovr)
    fake = FakeChordPro()
    assert render(conn, cfg, ovr, runner=fake).rendered == 1
    assert sung(inputs(fake, pdf_call(fake))[1]) == ["Bm", "G", "D", "A"]
    assert plays_in(entries_of(conn, cfg, ovr)[1]) == "D Major"
    for own in ("key=Bm&capo=0", "t=2"):
        ovr = overrides(cfg, f'[version]\n"{SODA}" = "{own}"\n')
        set_setting(cfg, SODA, Setting(key="B"))
        fake = FakeChordPro()
        assert render(conn, cfg, ovr, runner=fake, force=True).rendered == 1, own
        assert sung(inputs(fake, pdf_call(fake))[1]) == ["G#m", "E", "B", "F#"], own
        assert plays_in(entries_of(conn, cfg, ovr)[1]) == "B Major", own
        set_setting(cfg, SODA, None)


def test_a_sheet_with_no_key_plays_a_songs_own_key_as_written_and_says_so(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Keyless Song")
    keep_sheet(conn, cfg, song, NO_KEY, tonality="")
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "Placeholder Band - Keyless Song")
    ovr = overrides(cfg, '[version]\n"Placeholder Band - Keyless Song" = "key=Gm&mode=dorian&capo=0"\n')
    fake = FakeChordPro()
    assert render(conn, cfg, ovr, runner=fake).failed == []
    (text,) = inputs(fake, pdf_call(fake))
    assert sung(text) == ["N.C.", "Hm"] and "{key" not in text
    (entry,) = entries_of(conn, cfg, ovr)
    assert entry.version == Version() and plays_in(entry) == "key unknown, as written"
    assert page_data(cfg, 1)["start"] is None


def test_what_a_setting_leaves_out_follows_the_songs_own_version(conn, cfg, two):
    ovr = overrides(cfg, f'[version]\n"{SODA}" = "t=2&mode=dorian&capo=3&at=0.1"\n')
    set_setting(cfg, SODA, Setting(key="C"))  # in C, in its own version's mode and capo
    fake = FakeChordPro()
    render(conn, cfg, ovr, runner=fake)
    _, soda = inputs(fake, pdf_call(fake))
    assert sung(soda) == ["Cm", "Adim", "Eb", "Bb"]  # C dorian shapes, capo 3
    (_, entry) = entries_of(conn, cfg, ovr)
    assert plays_in(entry) == "C Dorian, capo 3"
    assert entry.version.at == {}  # a shape chosen for its own version's chords, not for these
    set_setting(cfg, SODA, Setting(capo=5))  # the capo alone: the same sound, other shapes
    (_, entry) = entries_of(conn, cfg, ovr)
    assert plays_in(entry) == "F# Dorian, capo 5"  # B dorian sounds, as in its own version, from F# shapes


def test_replacing_a_songs_sheet_keeps_the_songbooks_key(conn, cfg, two):
    _, soda = two
    set_setting(cfg, SODA, Setting("G", "dorian", 0))
    render(conn, cfg)
    keep_sheet(conn, cfg, soda, IN_D_MINOR, tab_id=4, tonality="Dm")  # another sheet, in another key
    render_sheets(conn, cfg)
    fake = FakeChordPro()
    assert render(conn, cfg, runner=fake).rendered == 1
    _, text = inputs(fake, pdf_call(fake))
    assert "Otra letra" in text and sung(text) == ["Gm", "Edim", "Bb", "F"]  # still in G dorian
    (_, entry) = entries_of(conn, cfg)
    assert entry.version.t == 5 and plays_in(entry) == "G Dorian"  # D up to G, where A went down
    assert page_data(cfg, 2)["start"] == "t=5&mode=dorian&capo=0"


IN_E_MINOR = (  # Wonderwall in E minor shapes, as a sheet with capo 2 writes it
    "[Verse 1]\n"
    "[tab][ch]Em[/ch]          [ch]G[/ch]\n"
    "Una canción de prueba[/tab]\n"
    "[tab][ch]D[/ch]              [ch]A[/ch]\n"
    "solo para el analizador[/tab]\n"
)
IN_F_SHARP_MINOR = (  # the same song in another version, the shapes it sounds in, no capo
    "[Verse 1]\n"
    "[tab][ch]F#m[/ch]          [ch]A[/ch]\n"
    "Otra letra de prueba[/tab]\n"
    "[tab][ch]E[/ch]              [ch]B[/ch]\n"
    "solo para el analizador[/tab]\n"
)
WONDERWALL = "Oasis - Wonderwall"


def test_a_key_set_with_no_capo_takes_the_capo_the_song_plays_at_now(conn, cfg):
    # A setting's key is the key of the shapes played: without its capo, a sheet in place of this one with
    # another capo would play those shapes at that capo, in another key for the singer. caracole songbook set
    # gives it the capo it plays at now (with_capo), so the key it sounds in stays.
    song = add_song(conn, "Oasis", "Wonderwall")
    keep_sheet(conn, cfg, song, IN_E_MINOR, tab_id=5, tonality="Em", capo=2)
    render_sheets(conn, cfg)
    make(cfg, "Campfire", WONDERWALL)
    ovr = overrides(cfg, "")
    (entry,) = entries_of(conn, cfg, ovr)
    assert with_capo(entry, Setting("E"), ovr) == Setting("E", capo=2)  # Em shapes at capo 2: F#m sounds
    assert with_capo(entry, Setting(mode="dorian"), ovr) == Setting(mode="dorian", capo=2)
    assert with_capo(entry, Setting("E", capo=0), ovr) == Setting("E", capo=0)  # a capo of its own stays
    assert with_capo(entry, Setting(capo=4), ovr) == Setting(capo=4)
    own = overrides(cfg, f'[version]\n"{WONDERWALL}" = "capo=3"\n')
    assert with_capo(entry, Setting("E"), own) == Setting("E", capo=3)  # its own version's capo, where it plays

    set_setting(cfg, WONDERWALL, with_capo(entry, Setting("E"), ovr))
    keep_sheet(conn, cfg, song, IN_F_SHARP_MINOR, tab_id=6, tonality="F#m")  # the nightly run's better version
    render_sheets(conn, cfg)
    (entry,) = entries_of(conn, cfg, ovr)
    assert plays_in(entry) == "E Minor, capo 2"  # the same shapes at the same capo: F#m, as before
    fake = FakeChordPro()
    render(conn, cfg, ovr, runner=fake)
    (text,) = inputs(fake, pdf_call(fake))
    assert "Otra letra" in text and sung(text) == ["Em", "G", "D", "A"]
    set_setting(cfg, WONDERWALL, Setting("E"))  # a key alone, as one may write it by hand
    (entry,) = entries_of(conn, cfg, ovr)
    assert plays_in(entry) == "E Minor"  # the new sheet's capo: Em sounds, two semitones down


def test_a_key_estimated_from_the_chords_is_the_key_of_the_shapes_a_songbook_plays(conn, cfg):
    # No key named: A minor, estimated from the chords as the sheet writes them, the Am shapes at capo 5. Their
    # notes are E minor's too, A minor lowered by the capo, which a key a tab names may be taken for: never the
    # key the chords gave, or a setting in A would move the shapes it names.
    from caracole.library import keep_file, kept_files, song_dir

    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet(conn, cfg, song, "[Verse 1]\n" + "[ch]Am[/ch]  [ch]C[/ch]  [ch]G[/ch]  [ch]D[/ch]\nUna canción\n" * 3,
               tab_id=7, tonality="", capo=5)
    vid = next(f.version_id for f in kept_files(conn, song.id) if f.name == "sheet.txt")
    doc = song_dir(cfg.library_dir, song) / "sheet.json"  # kept, as the fetch step keeps it: keys.py reads it
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.json", data=doc.read_bytes(), rank=1)
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "Soda Stereo - De Música Ligera")
    (entry,) = entries_of(conn, cfg)
    assert (entry.key, entry.key_source, plays_in(entry)) == ("A minor", "chords", "A Minor, capo 5")
    set_setting(cfg, "Soda Stereo - De Música Ligera", Setting("A"))  # the shapes it writes, at its capo
    (entry,) = entries_of(conn, cfg)
    assert entry.version == Version() and plays_in(entry) == "A Minor, capo 5"
    fake = FakeChordPro()
    render(conn, cfg, runner=fake)
    (text,) = inputs(fake, pdf_call(fake))
    assert sung(text) == ["Am", "C", "G", "D"] * 3
    assert "{subtitle: Soda Stereo · Am shapes · capo 5 · sounds Dm}" in text.splitlines()
    assert "{capo: 5}" in cho_inputs(fake)[0].splitlines()  # for an app, the capo it plays at
    set_setting(cfg, "Soda Stereo - De Música Ligera", Setting(capo=0))
    (entry,) = entries_of(conn, cfg)
    assert plays_in(entry) == "D Minor"
    fake = FakeChordPro()
    render(conn, cfg, runner=fake)
    (text,) = inputs(fake, pdf_call(fake))
    (cho,) = cho_inputs(fake)
    assert sung(text) == sung(cho) == ["Dm", "F", "C", "G"] * 3
    assert "{subtitle: Soda Stereo · Key Dm}" in text.splitlines()  # no capo said: none is played
    assert "capo" not in text.lower() and "capo" not in cho.lower()


def test_a_song_without_a_sheet_keeps_a_setting_as_given(conn, cfg):
    add_song(conn, "Muse", "Hysteria")
    make(cfg, "Campfire", "Muse - Hysteria")
    ovr = overrides(cfg, "")
    (entry,) = entries_of(conn, cfg, ovr)
    assert with_capo(entry, Setting("G"), ovr) == Setting("G")  # no capo to keep: its first sheet's


def test_a_song_whose_key_is_unknown_stays_as_written(conn, cfg):
    song = add_song(conn, "Placeholder Band", "Keyless Song")
    keep_sheet(conn, cfg, song, NO_KEY, tonality="")
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "Placeholder Band - Keyless Song")
    set_setting(cfg, "Placeholder Band - Keyless Song", Setting("G", "dorian"))
    fake = FakeChordPro()
    stats = render(conn, cfg, runner=fake)
    assert stats.failed == [] and stats.rendered == 1
    (text,) = inputs(fake, pdf_call(fake))
    (cho,) = cho_inputs(fake)
    for written in (text, cho):
        assert sung(written) == ["N.C.", "Hm"] and "{key" not in written and "{transpose" not in written
    assert "{subtitle: Placeholder Band}" in text.splitlines()  # no key it isn't in
    (entry,) = entries_of(conn, cfg)
    assert entry.version == Version() and plays_in(entry) == "key unknown, as written"
    assert page_data(cfg, 1)["start"] is None  # the phone page opens it as written


def test_a_song_without_a_sheet_plays_nowhere(conn, cfg):
    add_song(conn, "Muse", "Hysteria")
    make(cfg, "Campfire", "Muse - Hysteria")
    set_setting(cfg, "Muse - Hysteria", Setting("G"))
    (entry,) = entries_of(conn, cfg)
    assert entry.missing == "no sheet yet" and plays_in(entry) is None


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


@pytest.mark.parametrize("change", ["order", "sheet", "transpose", "setting", "style", "removed", "pdf gone",
                                    "pdf changed"])
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
    elif change == "setting":
        set_setting(cfg, "Radiohead - Creep", Setting(capo=2))
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


def test_an_upgrade_of_the_viewer_makes_the_phone_page_again(conn, cfg, two, monkeypatch):
    # An upgrade that changes how the viewer draws a sheet (here, its chords' markup) changes the
    # viewer's build version: songbook.html, each song in the viewer, follows as sheet.html does.
    # Its PDF and ChordPro file are chordpro's, and stay as they are.
    from caracole.viewer import page

    render(conn, cfg)
    before = (folder(cfg) / "songbook.html").read_bytes()
    chord_html = page._chord_html

    def marked(*args):
        return chord_html(*args).replace(' role="button"', ' role="button" data-new')

    monkeypatch.setattr(page, "_chord_html", marked)
    monkeypatch.setattr(page, "build_version", lambda: "a newer viewer")
    fake = FakeChordPro()
    stats = render(conn, cfg, runner=fake)
    after = (folder(cfg) / "songbook.html").read_bytes()
    assert stats.rendered == 1 and after != before and b"data-new" in after
    assert fake.calls == []


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


def test_with_pdf_fonts_a_songbook_and_its_contents_are_set_in_them_never_in_the_cjk_font(conn, cfg, tmp_path):
    # The Epic songbook went brush entirely for one ʼ: with the PDF fonts, a Latin songbook never does.
    epic = add_song(conn, "Epic", "Hymn")
    keep_sheet(conn, cfg, epic, SHEET.replace("Una canción", "Weʼre “singing” don’t"), tab_id=1)
    render_sheets(conn, cfg)
    make(cfg, "Epic", "Epic - Hymn")
    fonts, kai = font_folder(tmp_path / "fonts"), fake_font(tmp_path / "Kai.otf")
    fake = FakeChordPro()
    stats = render(conn, replace(cfg, cjk_font=kai, pdf_fonts=fonts), runner=fake)
    call = pdf_call(fake)
    assert stats.font_error is None and stats.failed == []
    assert f"--define=pdf.fonts.toc.file={fonts / 'regular.ttf'}" in call
    assert f"--define=pdf.fonts.title.file={fonts / 'bold.ttf'}" in call
    assert not any(str(kai) in a for a in call)


def test_with_pdf_fonts_a_songbook_with_a_chinese_song_sets_its_words_in_the_cjk_font(conn, cfg, two, tmp_path):
    zh = add_song(conn, "宋冬野", "斑马斑马")
    keep_sheet(conn, cfg, zh, ZH_SHEET, tab_id=3, tonality="")
    render_sheets(conn, cfg)
    make(cfg, "Mixed", "Radiohead - Creep", "宋冬野 - 斑马斑马")
    fonts, kai = font_folder(tmp_path / "fonts"), fake_font(tmp_path / "Kai.otf")
    fake = FakeChordPro()
    render(conn, replace(cfg, cjk_font=kai, pdf_fonts=fonts), runner=fake, only="Mixed")
    call = pdf_call(fake)
    for element in ("text", "title", "toc"):
        assert f"--define=pdf.fonts.{element}.file={kai}" in call
    assert f"--define=pdf.fonts.chord.file={fonts / 'bold.ttf'}" in call


def test_pdf_fonts_set_or_taken_away_make_the_songbook_pdf_again(conn, cfg, two, tmp_path):
    render(conn, cfg)
    fonts = font_folder(tmp_path / "fonts")
    for setting, made in ((fonts, True), (fonts, False), (None, True), (None, False)):
        fake = FakeChordPro()
        render(conn, replace(cfg, pdf_fonts=setting), runner=fake)
        assert any(output_of(c).suffix == ".pdf" for c in fake.calls) == made, (setting, made)


def test_a_failed_run_is_reported_and_the_rest_goes_on(conn, cfg, two, caplog):
    make(cfg, "Picnic", "Soda Stereo - De Música Ligera")
    stats = render(conn, cfg, runner=FakeChordPro(fail=("Creep",)))
    assert stats.failed == ["Campfire"] and stats.rendered == 1
    assert (folder(cfg, "Picnic") / "songbook.pdf").exists()
    assert "songbook Campfire" in caplog.text and "Unhandled fonts" in caplog.text
    assert (folder(cfg) / "songbook.html").exists()  # the page needs no chordpro


def _raising(error):
    def run(cmd, **kwargs):
        raise error
    return run


def _ends(code: int, *, writes: bool):
    def run(cmd, **kwargs):
        if writes:
            output_of(cmd).write_bytes(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, code, stdout="", stderr="")
    return run


@pytest.mark.parametrize(("runner", "said"), [
    (_raising(FileNotFoundError(2, "No such file or directory")), "chordpro not found: {bin}"),
    (_raising(subprocess.TimeoutExpired("chordpro", 1)), "chordpro timed out after {timeout} s"),
    (_raising(PermissionError(13, "Permission denied")), "cannot run {bin}: [Errno 13] Permission denied"),
    (_ends(3, writes=True), "chordpro failed (exit 3)"),
    (_ends(0, writes=False), "chordpro wrote no songbook.pdf"),
], ids=["not found", "timed out", "cannot run", "failed", "nothing written"])
def test_a_chordpro_run_that_fails_says_why_and_fails_its_songbook(conn, cfg, two, caplog, runner, said):
    from caracole.render import TIMEOUT
    from caracole.songbook import PER_SONG_TIMEOUT

    stats = render(conn, cfg, runner=runner)
    assert stats.failed == ["Campfire"]
    timeout = TIMEOUT + PER_SONG_TIMEOUT * 2  # its two songs
    assert f"songbook Campfire: no songbook.pdf: {said.format(bin=cfg.chordpro_bin, timeout=timeout)}" in caplog.text
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


def test_a_songbooks_file_nested_too_deep_stops_neither_the_render_nor_the_page(conn, cfg, two):
    from datetime import UTC, datetime

    from caracole.library_page import build_library_page
    from caracole.overrides import Overrides

    render(conn, cfg)
    songbooks_file(cfg.library_dir).write_text("a = " + "[" * 1000 + "]" * 1000 + "\n", encoding="utf-8")
    fake = FakeChordPro()
    stats = render(conn, cfg, runner=fake)
    assert stats.error and "songbooks.toml" in stats.error
    assert fake.calls == [] and stats.removed == 0
    page = build_library_page(conn, cfg, Overrides(), datetime(2026, 10, 18, 3, 41, tzinfo=UTC))
    assert "songbooks.toml can't be read" in page


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
@pytest.mark.chordpro
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
@pytest.mark.chordpro
def test_the_real_chordpro_file_holds_every_song_in_its_key(conn, cfg, two):
    cfg = replace(cfg, chordpro_bin=CHORDPRO, cjk_font=None)
    render_songbooks(conn, cfg, overrides(cfg, '[transpose]\n"Soda Stereo - De Música Ligera" = 2\n'))
    cho = (folder(cfg) / "songbook.cho").read_text(encoding="utf-8")
    first, second = cho.split("{new_song}\n")
    assert "{title: Creep}" in first and "{title: De Música Ligera}" in second
    assert "{key: Bm}" in second and "[Bm]" in second and "[Am]" not in second
    assert "{transpose" not in cho and "#{chord" not in cho


@real_chordpro
@pytest.mark.chordpro
def test_the_real_files_play_a_song_in_its_setting(conn, cfg, two):
    cfg = replace(cfg, chordpro_bin=CHORDPRO, cjk_font=None)
    set_setting(cfg, SODA, Setting("G", "dorian", 0))
    stats = render_songbooks(conn, cfg, overrides(cfg, ""))
    assert stats.failed == [], stats
    strings = drawn(folder(cfg) / "songbook.pdf")
    for text in ("Gm", "Edim", "Bb", "Soda Stereo · Key G dorian"):
        assert text in strings, strings
    second = (folder(cfg) / "songbook.cho").read_text(encoding="utf-8").split("{new_song}\n")[1]
    assert "{key: Gm}" in second and "[Edim]" in second and "[Am]" not in second and "{define" not in second


@real_chordpro
@pytest.mark.chordpro
def test_a_songs_two_columns_end_level_in_the_songbook_too(conn, cfg):
    # A song a little longer than a column (宋冬野's 斑马斑马 in shape, synthetic words): alone, chordpro
    # would leave one line in the second column.
    from caracole.pdf_text import layout
    from helpers.pdf_pages import pdf_pages

    cfg = replace(cfg, chordpro_bin=CHORDPRO, cjk_font=None)
    sheet = "".join(
        f"[Part {n}]\r\n" + "".join(f"[tab][ch]C[/ch]               [ch]D[/ch]\r\nMade up words to sing {n}.{i} and"
                                     " more[/tab]\r\n" for i in range(count)) + "\r\n"
        for n, count in enumerate([4, 4, 4, 8, 5], 1))
    level = add_song(conn, "The Placeholders", "Level")
    keep_sheet(conn, cfg, level, sheet, tonality="C")
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "The Placeholders - Level")
    assert render_songbooks(conn, cfg, overrides(cfg, "")).failed == []
    pages = [[x for x, y, s in page if s.startswith("Made up words")] for page in pdf_pages(folder(cfg) / "songbook.pdf")]
    lines = pages[-1]  # the song's one page
    second = sum(1 for x in lines if x >= layout().second_column)
    assert len(lines) == 25 and min(second, 25 - second) >= 10, lines


@real_chordpro
@pytest.mark.skipif(not (CJK_FONT and Path(CJK_FONT).is_file()), reason="set CARACOLE_CJK_FONT")
@pytest.mark.chordpro
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


def base_fonts(pdf: Path) -> set[str]:
    """The fonts a PDF names (its font dictionaries' /BaseFont)."""
    return {m.decode() for m in re.findall(rb"/BaseFont /([^\s/]+)", pdf.read_bytes())}


@real_chordpro
@pytest.mark.skipif(not (CJK_FONT and Path(CJK_FONT).is_file()), reason="set CARACOLE_CJK_FONT")
@pytest.mark.skipif(PDF_FONTS is None, reason="set CARACOLE_PDF_FONTS to nix/pdf-fonts.nix's folder")
@pytest.mark.chordpro
def test_the_real_pdf_of_a_songbook_is_in_adwaita_sans_and_the_cjk_font_only_for_chinese(conn, cfg):
    cfg = replace(cfg, chordpro_bin=CHORDPRO, cjk_font=Path(CJK_FONT), pdf_fonts=PDF_FONTS)
    epic, zh = add_song(conn, "Epic", "Hymn"), add_song(conn, "宋冬野", "斑马斑马")
    keep_sheet(conn, cfg, epic, SHEET.replace("Una canción", "Weʼre “singing” don’t"), tab_id=1)
    keep_sheet(conn, cfg, zh, ZH_SHEET, tab_id=2, tonality="")
    render_sheets(conn, cfg)
    make(cfg, "Epic", "Epic - Hymn")
    make(cfg, "Mixed", "Epic - Hymn", "宋冬野 - 斑马斑马")
    stats = render_songbooks(conn, cfg, overrides(cfg, ""))
    assert stats.failed == [] and stats.font_error is None
    kai = Path(CJK_FONT).stem.split("-")[0]
    latin = base_fonts(folder(cfg, "Epic") / "songbook.pdf")
    assert {"AdwaitaSans", "AdwaitaSansBold"} <= latin and not any(f.startswith((kai, "Helvetica")) for f in latin)
    mixed = base_fonts(folder(cfg, "Mixed") / "songbook.pdf")
    assert any(f.startswith(kai) for f in mixed) and "AdwaitaSansBold" in mixed  # the words, and the chords
    assert not any(f.startswith("Helvetica") for f in mixed)


def test_each_song_goes_in_as_its_pdf_text(conn, cfg, two):
    fake = FakeChordPro()
    render(conn, cfg, overrides(cfg, '[transpose]\n"Radiohead - Creep" = 2\n'), runner=fake)
    creep, soda = inputs(fake, pdf_call(fake))
    assert creep.startswith("{title: Creep}") and "{transpose" not in creep
    for text in (creep, soda):
        assert "{columns: 2}" in text and "{subtitle:" in text
    assert "Radiohead · Key A" in creep  # the key G, two semitones up: the line says what the chords play
    cho_call = next(c for c in fake.calls if output_of(c).suffix == ".cho")
    assert "{columns:" not in inputs(fake, cho_call)[0]  # songbook.cho stays the sheets as the apps read them


def auto_sheet(conn, cfg, song, *, key=None):
    """Keep an auto-chords sheet as the autochords step does: "sheet (auto).txt", from a versions row
    with provider "auto", whose raw data holds the ``key`` heard, if any."""
    from caracole.autochords import ChordSegment, build_sheet
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    text = build_sheet([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G")], title=song.title,
                       artist=song.artist, synced="[00:00.00]made up words to sing\n")
    vid = upsert_version(conn, provider="auto", tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet",
                         kind="auto", rating=0, votes=0, version=1, label=None, url="",
                         raw={"key": key} if key else {}, now="2026-10-18T03:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt",
              data=text.encode("utf-8"), rank=1)


def test_a_song_whose_key_is_heard_again_makes_the_pdf_again(conn, cfg):
    # A song's PDF text is made from more than its .cho: an auto sheet's key is in its version's data.
    # Heard again, the song's own PDF and the phone page say the new key, and so must the songbook's PDF.
    song = add_song(conn, "Placeholder Band", "Synthetic Song")
    auto_sheet(conn, cfg, song, key="D")
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "Placeholder Band - Synthetic Song")
    render(conn, cfg)
    auto_sheet(conn, cfg, song, key="G")
    render_sheets(conn, cfg)
    fake = FakeChordPro()
    assert render(conn, cfg, runner=fake).rendered == 1
    (sheet,) = inputs(fake, pdf_call(fake))
    assert "{subtitle: Placeholder Band · Key G}" in sheet.splitlines()
    assert render(conn, cfg).skipped == 1


def test_a_newer_way_of_printing_a_song_makes_the_pdf_again(conn, cfg, two, monkeypatch):
    # A newer caracole whose theory, key line or shapes print the same sheets another way.
    from caracole import render as render_module

    render(conn, cfg)
    made = render_module.pdf_text
    monkeypatch.setattr(render_module, "pdf_text", lambda cho, **kw: made(cho, **kw) + "{comment: newer}\n")
    fake = FakeChordPro()
    assert render(conn, cfg, runner=fake).rendered == 1
    assert all(song.endswith("{comment: newer}\n") for song in inputs(fake, pdf_call(fake)))
    assert render(conn, cfg).skipped == 1


def test_letters_only_a_songs_notes_have_need_no_font(conn, cfg):
    # The notes stay out of a song's PDF text, and so do the letters they alone have, as in its own PDF.
    assert cfg.cjk_font is None
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet(conn, cfg, song, "Notas: 这是一个合成的例子\n\n" + SHEET)
    render_sheets(conn, cfg)
    make(cfg, "Campfire", "Soda Stereo - De Música Ligera")
    fake = FakeChordPro()
    stats = render(conn, cfg, runner=fake)
    assert stats.font_error is None and stats.failed == [] and stats.rendered == 1
    call = pdf_call(fake)
    assert not any(a.startswith("--define=pdf.fonts") for a in call)
    (sheet,) = inputs(fake, call)
    assert "这是一个" not in sheet
    assert "这是一个" in (folder(cfg) / "songbook.cho").read_text(encoding="utf-8")  # the apps' file keeps the notes


@pytest.mark.parametrize("part", ["viewer_key", "pdf_text"])
def test_a_song_whose_pdf_text_cant_be_made_fails_the_songbooks_pdf_alone(conn, cfg, two, caplog, monkeypatch,
                                                                          part):
    # A song's PDF text runs the viewer's code: a bug there costs the songbooks it is in their PDF,
    # and nothing else: their page, their ChordPro file and the other songbooks are still made.
    from caracole import render as render_module

    make(cfg, "Picnic", "Soda Stereo - De Música Ligera")
    real = getattr(render_module, part)

    def broken(cho, *args, **kwargs):
        if "Creep" in cho:
            raise ValueError("a bug in the viewer's theory")
        return real(cho, *args, **kwargs)

    monkeypatch.setattr(render_module, part, broken)
    stats = render(conn, cfg)
    assert stats.failed == ["Campfire"] and stats.rendered == 1
    assert not (folder(cfg) / "songbook.pdf").exists()
    assert (folder(cfg) / "songbook.html").exists() and (folder(cfg) / "songbook.cho").exists()
    assert (folder(cfg, "Picnic") / "songbook.pdf").exists()
    assert "songbook Campfire: no songbook.pdf" in caplog.text
    assert "Traceback" in caplog.text and "a bug in the viewer's theory" in caplog.text
