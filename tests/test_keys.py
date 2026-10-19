"""keys.py: a song's musical key, read from its tab or estimated from its chords."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from caracole.keys import (
    SongKey,
    chords_in_sheet,
    estimate_key,
    key_in_text,
    key_name,
    parse_key,
    refresh_info_keys,
    same_key,
    song_key,
)
from caracole.library import keep_file, song_dir
from caracole.versions import upsert_version

from conftest import add_song


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Am", "A minor"),
        ("A minor", "A minor"),
        ("A min", "A minor"),
        ("Amin", "A minor"),
        ("A Minor", "A minor"),
        ("F#m", "F# minor"),
        ("Bbm", "Bb minor"),
        ("Eb", "Eb"),
        ("E♭", "Eb"),
        ("C♯m", "C# minor"),
        ("C", "C"),
        ("C major", "C"),
        ("Cmaj", "C"),
        ("  G ", "G"),
        ("Do", "C"),
        ("do mayor", "C"),
        ("La menor", "A minor"),
        ("Lam", "A minor"),
        ("Sib", "Bb"),
        ("Fa#m", "F# minor"),
        ("Sol", "G"),
        ("Re menor", "D minor"),
    ],
)
def test_parse_key_reads_the_ways_tabs_write_a_key(text, key):
    assert parse_key(text) == key


@pytest.mark.parametrize("text", ["", "   ", "H", "Am7", "C/G", "Hello", "am", "A minor blues", "x2"])
def test_parse_key_refuses_what_is_not_a_key(text):
    assert parse_key(text) is None


def test_key_name_spells_out_the_mode():
    assert key_name("C") == "C major"
    assert key_name("F#") == "F# major"
    assert key_name("A minor") == "A minor"


def test_same_key_compares_enharmonic_spellings():
    assert same_key("F# minor", "Gb minor")
    assert same_key("C", "C")
    assert not same_key("A minor", "C")
    assert not same_key("A minor", "A")


# --- the tab's own word ------------------------------------------------------------------


def test_a_chordpro_key_directive_is_the_tabs_key():
    assert key_in_text("{title: Song}\n{key: Am}\n[Verse]\n[ch]Am[/ch] [ch]F[/ch]\nWords") == "A minor"


def test_a_key_line_before_the_first_chords_is_the_tabs_key():
    sheet = "Capo 2\nKey: G\n\n[Intro]\n[ch]G[/ch] [ch]C[/ch]\nWords here\n"
    assert key_in_text(sheet) == "G"


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("Tono: La menor", "A minor"),
        ("TONO: Re", "D"),
        ("Tonalidad: Mi menor", "E minor"),
        ("Tono original: Do", "C"),
        ("Key: [ch]F#m[/ch]", "F# minor"),
        ("Key of Bb", "Bb"),
        ("Key - Em (capo 3)", "E minor"),
        ("Tuning: E A D G B E, Key: Em", "E minor"),
        ("Key: Am  Capo: 2", "A minor"),
    ],
)
def test_key_lines_in_english_and_spanish(line, key):
    assert key_in_text(f"{line}\n\n[ch]Am[/ch] [ch]G[/ch]\nWords\n") == key


def test_a_key_line_after_the_chords_start_is_not_read():
    sheet = "[Verse]\n[ch]G[/ch]        [ch]C[/ch]\nKey: D is where it goes after\n"
    assert key_in_text(sheet) is None


@pytest.mark.parametrize(
    "line",
    ["The key: I lost it", "Key change: up a tone", "Monkey: G", "Keys: Am", "no key here"],
)
def test_lines_that_only_look_like_a_key_line(line):
    assert key_in_text(f"{line}\n[ch]G[/ch]\nWords\n") is None


# --- the chords --------------------------------------------------------------------------


def test_chords_in_sheet_reads_the_chord_tags_in_order_with_letter_names():
    sheet = "[Intro]\n[ch]Am[/ch]-[ch]F[/ch]\n[ch]Do[/ch]  [ch]Sol7[/ch]\nWords\n[ch]N.C.[/ch]"
    assert chords_in_sheet(sheet) == ["Am", "F", "C", "G7", "N.C."]


@pytest.mark.parametrize(
    ("progression", "key"),
    [
        ("G D Em C G D Em C", "G"),
        ("Am F C G Am F C G", "A minor"),
        ("C G Am F C G Am F", "C"),
        ("Em C G D Em C G D", "E minor"),
        ("D A Bm G D A Bm G", "D"),
        ("Am Dm E7 Am Am Dm E7 Am", "A minor"),
        ("A7 A7 A7 A7 D7 D7 A7 A7 E7 D7 A7 E7", "A"),
        ("F C Dm Bb F C Dm Bb", "F"),
        ("D A Bm F#m G D G A", "D"),
        ("Am G F E Am G F E", "A minor"),
        ("Dm Bb F C Dm Bb F C", "D minor"),
        ("Bm G D A Bm G D A", "B minor"),
        ("Am C D F Am C E Am", "A minor"),
        ("Cm Ab Eb Bb Cm Ab Eb Bb", "C minor"),
        ("F#m D A E F#m D A E", "F# minor"),
        ("Em D C B7 Em D C B7 Em", "E minor"),
        ("Gm F Eb D7 Gm", "G minor"),
        ("E A E B7 E A B7 E", "E"),
        ("Bm F# A E G D Em F#", "B minor"),
        ("G D Am G D C G D Am", "G"),
        ("Am G#+ C/G D/F# Fmaj7 G Am", "A minor"),
        ("F G C Am F G C", "C"),
        ("G G7 C Cm G D7 G", "G"),
        ("Am Am7 D7 Am Em Am", "A minor"),
        ("F5 Bb5 Ab5 Db5 F5 Bb5 Ab5 Db5", "F minor"),
        ("Lam Fa Do Sol", "A minor"),
    ],
)
def test_estimate_key_from_well_known_progressions(progression, key):
    assert estimate_key(progression.split()) == key


@pytest.mark.parametrize(
    ("chords", "key"),
    [
        (["Cmaj7", "Am7", "Dm7", "G7", "Cmaj7"], "C"),
        (["Bm7b5", "E7", "Am", "Am/G", "F", "E7", "Am"], "A minor"),
        (["C(add9)", "Fadd9", "G6", "Gsus4", "G", "C"], "C"),
        (["Em", "Am", "B7#9", "Em"], "E minor"),
        (["D", "Dsus2", "G/D", "A7sus4", "D"], "D"),
        (["AmMaj7", "Am", "Dm", "E7", "Am"], "A minor"),
    ],
)
def test_estimate_key_reads_extended_slash_and_suspended_chords(chords, key):
    assert estimate_key(chords) == key


def test_the_estimate_spells_the_tonic_as_the_chords_do():
    assert estimate_key("C#m A E B C#m A E B".split()) == "C# minor"
    assert estimate_key("Gb Db Ebm Cb Gb Db Ebm Cb".split()) == "Gb"
    assert estimate_key("F# C# D#m B F# C# D#m B".split()) == "F#"


def test_the_estimate_weighs_each_chord_by_its_duration():
    # The same four chords: the one that rings longest is home.
    assert estimate_key([("Am", 1.0), ("C", 20.0), ("G", 4.0), ("F", 4.0), ("C", 20.0)]) == "C"
    assert estimate_key([("C", 1.0), ("Am", 20.0), ("G", 4.0), ("F", 4.0), ("Am", 20.0)]) == "A minor"


@pytest.mark.parametrize(
    "chords",
    [[], ["N.C.", "x2", "N"], ["C7", "F#7", "C7", "F#7"], ["C", "C#m", "D", "D#m", "E", "Fm", "F#"]],
)
def test_no_estimate_without_chords_or_from_chords_that_fit_no_key(chords):
    assert estimate_key(chords) is None


# --- a song's key ------------------------------------------------------------------------

AM_F_C_G = "[Verse]\n[ch]Am[/ch]  [ch]F[/ch]  [ch]C[/ch]  [ch]G[/ch]\nWords go here\n" * 4
AUTO_SHEET = (
    "auto-generated, unverified\nA - T\n\n[Chords]\n| [ch]Em[/ch] | [ch]C[/ch] | [ch]G[/ch] | [ch]D[/ch] |\n"
)


def keep_sheet(conn, cfg, song, *, content=AM_F_C_G, raw=None, provider="ug", tab_id="85053"):
    """A human sheet as the fetch steps keep it: sheet.json with the markup, then sheet.txt."""
    url = f"https://example.invalid/{tab_id}"
    vid = upsert_version(conn, provider=provider, tab_id=tab_id, song_id=song.id, slot="sheet",
                         kind="chords" if provider == "ug" else "acordes", rating=4.5, votes=10,
                         version=1, label=None, url=url, raw=raw or {}, now="2026-10-18T00:00:00Z")
    doc = {"version": raw or {}, "content": content, "url": url}
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.json",
              data=json.dumps(doc).encode(), rank=1)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=content.replace("[ch]", "").replace("[/ch]", "").encode(), rank=1)
    return vid


def keep_auto_sheet(conn, cfg, song, *, raw=None):
    vid = upsert_version(conn, provider="auto", tab_id=str(song.id), song_id=song.id, slot="sheet",
                         kind="auto", rating=0, votes=0, version=1, label=None, url="file:///x.flac",
                         raw=raw if raw is not None else {"model": "btc_large_voca"},
                         now="2026-10-18T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt",
              data=AUTO_SHEET.encode(), rank=1)
    return vid


def test_ugs_key_for_the_kept_version_is_the_tabs(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s, raw={"tonality_name": "Bm"})
    assert song_key(conn, cfg.library_dir, s) == SongKey("B minor", "tab")


def test_a_key_the_sheet_states_is_the_tabs(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s, content="Key: G\n\n" + AM_F_C_G)
    assert song_key(conn, cfg.library_dir, s) == SongKey("G", "tab")


def test_a_lacuerda_sheets_tono_is_the_tabs(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s, provider="lacuerda", content="Tono: Re\n\n" + AM_F_C_G)
    assert song_key(conn, cfg.library_dir, s) == SongKey("D", "tab")


def test_without_the_tabs_word_the_key_is_estimated_from_the_chords(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s, raw={"tonality_name": ""})
    assert song_key(conn, cfg.library_dir, s) == SongKey("A minor", "chords")


def test_a_key_ug_gives_that_is_no_key_is_passed_over(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s, raw={"tonality_name": "Standard"})
    assert song_key(conn, cfg.library_dir, s) == SongKey("A minor", "chords")


def test_an_auto_sheet_has_the_key_the_audio_model_heard(conn, cfg):
    s = add_song(conn)
    keep_auto_sheet(conn, cfg, s, raw={"model": "btc_large_voca", "key": "B minor"})
    assert song_key(conn, cfg.library_dir, s) == SongKey("B minor", "audio")


def test_an_older_auto_sheet_has_the_key_of_its_chords_which_came_from_the_audio(conn, cfg):
    s = add_song(conn)
    keep_auto_sheet(conn, cfg, s)
    assert song_key(conn, cfg.library_dir, s) == SongKey("E minor", "audio")


def test_a_human_sheet_with_no_chords_leaves_the_key_to_the_audio(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s, content="Just the words\nand no chords\n")
    keep_auto_sheet(conn, cfg, s, raw={"key": "C"})
    assert song_key(conn, cfg.library_dir, s) == SongKey("C", "audio")


def test_the_human_sheet_wins_over_the_audio(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s)
    keep_auto_sheet(conn, cfg, s, raw={"key": "C"})
    assert song_key(conn, cfg.library_dir, s) == SongKey("A minor", "chords")


def test_a_song_without_a_sheet_has_no_key(conn, cfg):
    assert song_key(conn, cfg.library_dir, add_song(conn)) is None


def test_a_link_in_place_of_sheet_json_is_never_read(conn, cfg, tmp_path):
    s = add_song(conn)
    keep_sheet(conn, cfg, s)
    elsewhere = tmp_path / "private.json"
    elsewhere.write_text(json.dumps({"content": "Key: G\n\n[ch]G[/ch]\n"}))
    sheet_json = song_dir(cfg.library_dir, s) / "sheet.json"
    sheet_json.unlink()
    sheet_json.symlink_to(elsewhere)
    assert song_key(conn, cfg.library_dir, s) is None


def test_a_sheet_json_that_is_no_json_gives_no_estimate_but_ugs_key_still_counts(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s, raw={"tonality_name": "F"})
    (song_dir(cfg.library_dir, s) / "sheet.json").write_text("{not json")
    assert song_key(conn, cfg.library_dir, s) == SongKey("F", "tab")
    other = add_song(conn, "Radiohead", "Creep")
    keep_sheet(conn, cfg, other, tab_id="1")
    (song_dir(cfg.library_dir, other) / "sheet.json").write_text("[1, 2]")
    assert song_key(conn, cfg.library_dir, other) is None


def test_a_sheet_json_nested_too_deep_to_decode_is_no_json_either(conn, cfg):
    # Any synced device can write one; json.loads raises RecursionError, not ValueError, on it.
    s = add_song(conn)
    keep_sheet(conn, cfg, s, raw={"tonality_name": "F"})
    keep = add_song(conn, "Radiohead", "Creep")
    keep_sheet(conn, cfg, keep, tab_id="1")
    for song in (s, keep):
        (song_dir(cfg.library_dir, song) / "sheet.json").write_text("[" * 100_000 + "]" * 100_000)
    assert song_key(conn, cfg.library_dir, s) == SongKey("F", "tab")
    assert song_key(conn, cfg.library_dir, keep) is None


def test_info_json_written_before_keys_gets_them_once(conn, cfg):
    s = add_song(conn)
    keep_sheet(conn, cfg, s, raw={"tonality_name": "Bm"})
    info = song_dir(cfg.library_dir, s) / "info.json"
    info.write_text(json.dumps({"key": s.key}))  # as an older caracole wrote it: the song's identity
    assert refresh_info_keys(conn, cfg.library_dir) == 1
    assert json.loads(info.read_text())["key"] == "B minor"
    info.write_text("{}")
    assert refresh_info_keys(conn, cfg.library_dir) == 0
    assert info.read_text() == "{}"


def test_refreshing_makes_no_folder_for_a_song_without_files(conn, cfg):
    s = add_song(conn)
    assert refresh_info_keys(conn, cfg.library_dir) == 0
    assert not song_dir(cfg.library_dir, s).exists()


def test_an_info_json_that_cant_be_written_is_tried_again_next_time(conn, cfg, monkeypatch, caplog):
    s = add_song(conn)
    keep_sheet(conn, cfg, s)

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("caracole.keys.write_info", refuse)
    assert refresh_info_keys(conn, cfg.library_dir) == 0
    assert "Permission denied" in caplog.text
    monkeypatch.undo()
    assert refresh_info_keys(conn, cfg.library_dir) == 1
    info = json.loads((song_dir(cfg.library_dir, s) / "info.json").read_text())
    assert (info["key"], info["key_source"]) == ("A minor", "chords")


def test_the_pages_bring_info_json_up_to_date(conn, cfg):
    from caracole.overrides import Overrides
    from caracole.todo import write_pages

    s = add_song(conn)
    keep_sheet(conn, cfg, s, raw={"tonality_name": "G"})
    write_pages(conn, cfg, Overrides(), datetime(2026, 10, 19, tzinfo=UTC))
    assert json.loads((song_dir(cfg.library_dir, s) / "info.json").read_text())["key"] == "G"


def test_a_song_key_reads_as_its_source_says():
    assert SongKey("A minor", "tab").describe() == "A minor (from the tab)"
    assert SongKey("C", "chords").describe() == "C major (estimated from the chords)"
    assert SongKey("F#", "audio").describe() == "F# major (from the audio)"
