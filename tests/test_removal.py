"""removal.py: what ``caracole remove`` takes out of the library, and what it leaves."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from conftest import add_song

from caracole import db
from caracole.library import keep_file, song_dir, write_info
from caracole.songs import get_song, list_songs, removed_song, update_song
from caracole.versions import upsert_version

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
CREEP = "radiohead/creep"


def creep(conn, cfg, *, wanted="Radiohead - Creep\nOasis - Wonderwall\n"):
    """Radiohead's Creep, from wanted.txt, with what caracole keeps of a found song."""
    song = add_song(conn, "Radiohead", "Creep", source="wanted", source_id=CREEP)
    if wanted is not None:
        cfg.wanted_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.wanted_file.write_text(wanted, encoding="utf-8")
    sheet = version(conn, song, "101", "chords")
    gp = version(conn, song, "301", "guitar-pro", provider="gtptabs")
    song = get_song(conn, song.id)
    for vid, name in ((sheet, "sheet.txt"), (sheet, "sheet.json"), (gp, "guitar-1.gp5")):
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=name, data=name.encode(), rank=1)
    folder = song_dir(cfg.library_dir, song)
    for name in ("sheet.cho", "sheet.pdf", "lyrics.txt", "lyrics.lrc"):
        (folder / name).write_text(name, encoding="utf-8")
    db.kv_set_json(conn, f"render:{song.id}", {"pdf": "sheet.pdf", "transpose": 0})
    update_song(conn, song.id, status="found", lyrics_status="found", lyrics_json='{"plain": "x"}')
    write_info(conn, cfg.library_dir, get_song(conn, song.id))
    return get_song(conn, song.id)


def version(conn, song, tab_id, kind, provider="ug"):
    return upsert_version(conn, provider=provider, tab_id=tab_id, song_id=song.id,
                          slot="sheet" if kind == "chords" else "guitar", kind=kind, rating=4.5, votes=10,
                          version=1, label=None, url=f"https://u/{tab_id}", raw={}, now="2026-10-01T00:00:00Z")


def plan_and_remove(conn, cfg, song):
    from caracole.removal import plan_removal, remove_song

    plan = plan_removal(conn, cfg, song)
    return plan, remove_song(conn, cfg, plan, now=NOW)


CARACOLES = ["guitar-1.gp5", "info.json", "lyrics.lrc", "lyrics.txt", "sheet.cho", "sheet.json", "sheet.pdf",
             "sheet.txt"]


def test_a_song_goes_with_its_files_its_wanted_line_and_its_record(conn, cfg):
    song = creep(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / ".sheet.pdf.1a2b3c4d.tmp").write_bytes(b"what a power cut left")
    db.kv_set(conn, f"render:{song.id}:auto", "{}")
    db.kv_set(conn, f"ug:blocked:{song.id}", "[]")
    db.kv_set(conn, f"wanted:first_seen:{CREEP}", "2026-10-01T00:00:00Z")

    plan, result = plan_and_remove(conn, cfg, song)

    assert sorted(plan.delete) == sorted([*CARACOLES, ".sheet.pdf.1a2b3c4d.tmp"])
    assert plan.keep == () and plan.wanted_lines == (1,) and plan.versions == 2
    assert sorted(result.deleted) == sorted(plan.delete) and result.folder_gone and result.errors == []
    assert not folder.exists() and not folder.parent.exists()  # Radiohead/ held only Creep
    assert cfg.wanted_file.read_text(encoding="utf-8") == "Oasis - Wonderwall\n"
    assert list_songs(conn) == []
    for table in ("versions", "files"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    for key in (f"render:{song.id}", f"render:{song.id}:auto", f"ug:blocked:{song.id}", f"wanted:first_seen:{CREEP}"):
        assert db.kv_get(conn, key) is None, key
    stone = removed_song(conn, CREEP)
    assert (stone.display, stone.removed_at) == ("Radiohead - Creep", "2026-10-19T12:00:00Z")
    assert stone.source_ids == {"wanted": [CREEP]}


def test_your_own_files_stay_in_the_folder_and_the_removal_says_so(conn, cfg, tmp_path):
    song = creep(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / "notes.md").write_text("capo 2", encoding="utf-8")
    (folder / ".notes.md.swp").write_bytes(b"vim")
    (folder / "photos").mkdir()
    (folder / "photos" / "fretboard.jpg").write_bytes(b"jpg")
    secret = tmp_path / "state" / "secret.json"
    secret.write_text("token", encoding="utf-8")
    (folder / "sheet.pdf").unlink()
    (folder / "sheet.pdf").symlink_to(secret)  # planted under a name of caracole's
    add_song(conn, "Radiohead", "Karma Police")  # the artist folder has another song too
    (cfg.library_dir / "Radiohead" / "Karma Police").mkdir()

    plan, result = plan_and_remove(conn, cfg, song)

    assert sorted(plan.delete) == [name for name in CARACOLES if name != "sheet.pdf"]
    assert plan.keep == ((".notes.md.swp", "caracole didn't write it"), ("notes.md", "caracole didn't write it"),
                         ("photos", "a folder"), ("sheet.pdf", "a symbolic link, which caracole doesn't follow"))
    assert sorted(os.listdir(folder)) == [".notes.md.swp", "notes.md", "photos", "sheet.pdf"]
    assert not result.folder_gone and secret.read_text(encoding="utf-8") == "token"
    assert (folder / "photos" / "fretboard.jpg").read_bytes() == b"jpg"
    assert (cfg.library_dir / "Radiohead" / "Karma Police").is_dir()


def test_files_of_caracoles_names_it_didnt_write_stay(conn, cfg):
    # No human sheet kept, no render record, no lyrics found: a sheet.pdf and a lyrics.txt are yours.
    song = add_song(conn, "Radiohead", "Creep")
    folder = song_dir(cfg.library_dir, song)
    folder.mkdir(parents=True)
    for name in ("sheet.pdf", "sheet.cho", "lyrics.txt", "guitar-1.gp5"):
        (folder / name).write_text("mine", encoding="utf-8")
    plan, _ = plan_and_remove(conn, cfg, song)
    assert plan.delete == ()
    assert [name for name, _ in plan.keep] == ["guitar-1.gp5", "lyrics.txt", "sheet.cho", "sheet.pdf"]
    assert sorted(os.listdir(folder)) == ["guitar-1.gp5", "lyrics.txt", "sheet.cho", "sheet.pdf"]
    assert removed_song(conn, "radiohead/creep") is not None


def test_in_a_folder_another_song_shares_only_the_songs_kept_files_go(conn, cfg):
    # Two songs whose names make the same folder: what isn't this song's own may be the other's.
    song = creep(conn, cfg)
    conn.execute(
        "INSERT INTO songs (key, artist, title, artists, source_ids, added_at, created_at, updated_at) "
        "VALUES ('radiohead/creep-2', 'Radiohead', 'Creep', '[\"Radiohead\"]', '{}', 'x', 'x', 'x')")
    plan, _ = plan_and_remove(conn, cfg, song)
    assert sorted(plan.delete) == ["guitar-1.gp5", "sheet.json", "sheet.txt"]
    assert dict(plan.keep)["lyrics.txt"] == "the folder is Radiohead - Creep's too"
    assert sorted(os.listdir(song_dir(cfg.library_dir, song))) == [
        "info.json", "lyrics.lrc", "lyrics.txt", "sheet.cho", "sheet.pdf"]


def test_an_auto_sheets_pdf_goes_with_it(conn, cfg):
    song = add_song(conn, "Radiohead", "Creep")
    vid = upsert_version(conn, provider="autochords", tab_id="audio", song_id=song.id, slot="sheet", kind="auto",
                         rating=0, votes=0, version=1, label=None, url="file:", raw={}, now="2026-10-01T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt", data=b"[Am]", rank=1)
    folder = song_dir(cfg.library_dir, song)
    for name in ("sheet (auto).cho", "sheet (auto).pdf", "sheet (auto).html"):
        (folder / name).write_text(name, encoding="utf-8")
    plan, _ = plan_and_remove(conn, cfg, song)
    assert sorted(plan.delete) == ["sheet (auto).cho", "sheet (auto).html", "sheet (auto).pdf", "sheet (auto).txt"]


def test_nothing_is_deleted_through_a_link_in_place_of_the_folder(conn, cfg, tmp_path):
    song = creep(conn, cfg)
    elsewhere = tmp_path / "elsewhere"
    (cfg.library_dir / "Radiohead").rename(elsewhere)
    (cfg.library_dir / "Radiohead").symlink_to(elsewhere)  # planted by a synced device, say

    plan, result = plan_and_remove(conn, cfg, song)

    assert plan.delete == () and "symbolic link" in plan.folder_problem
    assert sorted(os.listdir(elsewhere / "Creep")) == CARACOLES
    assert result.deleted == [] and (cfg.library_dir / "Radiohead").is_symlink()
    assert removed_song(conn, CREEP) is not None  # the rest of the song goes all the same


def test_a_file_the_database_keeps_outside_the_songs_folder_stays(conn, cfg):
    # Two songs merged after a re-keying: the other's files stay where they were on disk.
    song = creep(conn, cfg)
    conn.execute("UPDATE files SET path = 'Radiohead/Creep (old)/guitar-1.gp5' WHERE name = 'guitar-1.gp5'")
    old = cfg.library_dir / "Radiohead" / "Creep (old)"
    old.mkdir()
    (old / "guitar-1.gp5").write_bytes(b"gp5")
    (song_dir(cfg.library_dir, song) / "guitar-1.gp5").unlink()
    plan, _ = plan_and_remove(conn, cfg, song)
    assert plan.elsewhere == ("Radiohead/Creep (old)/guitar-1.gp5",)
    assert (old / "guitar-1.gp5").read_bytes() == b"gp5"


def test_the_audio_you_bought_is_never_deleted(conn, cfg):
    song = creep(conn, cfg)
    audio = cfg.music_dir / "Radiohead" / "Creep.flac"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"fLaC")
    update_song(conn, song.id, audio_path=str(audio))
    plan, _ = plan_and_remove(conn, cfg, get_song(conn, song.id))
    assert plan.audio == str(audio)
    assert audio.read_bytes() == b"fLaC"


def youtube_audio(conn, cfg, song, video_id="XFkzRNyygfk"):
    """The audio youtube_fetch.py took for the song, in caracole's cache, linked as a purchase is."""
    audio = cfg.cache_dir / "youtube" / f"{song.id}-{video_id}.m4a"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"aac")
    db.kv_set_json(conn, f"youtube:{song.id}", {
        "video": {"id": video_id, "title": "Creep", "channel": "Radiohead - Topic"}, "source": "search",
        "audio": str(audio)})
    return audio


def test_the_audio_caracole_took_from_youtube_goes_with_the_song(conn, cfg):
    from caracole.removal import describe

    song = creep(conn, cfg)
    audio = youtube_audio(conn, cfg, song)
    other = add_song(conn, "Oasis", "Wonderwall")
    theirs = youtube_audio(conn, cfg, other, "6hzrDeceEKc")
    update_song(conn, song.id, audio_path=str(audio), audio_mtime=audio.stat().st_mtime)
    update_song(conn, other.id, audio_path=str(theirs), audio_mtime=theirs.stat().st_mtime)
    plan, result = plan_and_remove(conn, cfg, get_song(conn, song.id))
    assert plan.audio is None and plan.youtube_audio == (str(audio),)  # caracole's, not a purchase of yours
    goes, stays, _ = describe(plan, cfg)
    assert any("audio caracole took from YouTube" in line for line in goes), goes
    assert not any("you bought" in line for line in stays), stays
    assert not audio.exists() and result.errors == []
    assert db.kv_get(conn, f"youtube:{song.id}") is None
    assert theirs.read_bytes() == b"aac"  # another song's stays


def test_a_purchase_stays_and_the_youtube_audio_it_replaced_goes(conn, cfg):
    # A purchase linked later took the YouTube audio's place; the next youtube step would have tidied it.
    song = creep(conn, cfg)
    left = youtube_audio(conn, cfg, song)
    bought = cfg.music_dir / "Radiohead" / "Creep.flac"
    bought.parent.mkdir(parents=True)
    bought.write_bytes(b"fLaC")
    update_song(conn, song.id, audio_path=str(bought))
    plan, _ = plan_and_remove(conn, cfg, get_song(conn, song.id))
    assert plan.audio == str(bought) and plan.youtube_audio == (str(left),)
    assert bought.read_bytes() == b"fLaC" and not left.exists()


def test_a_youtube_record_naming_a_file_outside_caracoles_cache_deletes_nothing(conn, cfg):
    song = creep(conn, cfg)
    mine = cfg.music_dir / "Creep.m4a"
    mine.parent.mkdir(parents=True)
    mine.write_bytes(b"mine")
    db.kv_set_json(conn, f"youtube:{song.id}", {"video": {"id": "XFkzRNyygfk"}, "audio": str(mine)})
    plan, _ = plan_and_remove(conn, cfg, song)
    assert plan.youtube_audio == () and mine.read_bytes() == b"mine"


def test_a_wanted_txt_caracole_cant_read_stops_the_removal_before_anything_goes(conn, cfg, tmp_path):
    from caracole.removal import RemovalError, plan_removal, remove_song

    song = creep(conn, cfg, wanted=None)
    real = tmp_path / "real-wanted.txt"
    real.write_text("Radiohead - Creep\n", encoding="utf-8")
    cfg.wanted_file.symlink_to(real)
    plan = plan_removal(conn, cfg, song)
    assert "symbolic link" in plan.wanted_problem
    with pytest.raises(RemovalError, match="wanted.txt"):
        remove_song(conn, cfg, plan, now=NOW)
    assert [s.id for s in list_songs(conn)] == [song.id] and removed_song(conn, CREEP) is None
    assert sorted(os.listdir(song_dir(cfg.library_dir, song))) == CARACOLES


def test_the_next_sync_brings_nothing_back_until_you_ask_for_the_song_again(conn, cfg):
    from caracole.sources import sync_sources
    from caracole.wanted import append_wanted

    song = creep(conn, cfg)
    plan_and_remove(conn, cfg, song)
    report = sync_sources(conn, cfg, NOW)
    assert report.wanted.seen == 1 and [s.title for s in list_songs(conn)] == ["Wonderwall"]
    append_wanted(cfg.wanted_file, "Radiohead", "Creep")  # caracole add, or the web page's request
    assert sync_sources(conn, cfg, NOW).wanted.new == 1
    back = next(s for s in list_songs(conn) if s.title == "Creep")
    assert (back.status, back.lyrics_status, back.match_decision) == ("wanted", "pending", None)
    assert removed_song(conn, CREEP) is None


def test_a_removal_deletes_the_songs_exports(conn, cfg):
    from caracole.render import EXPORT_KV

    song = creep(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / "sheet (G Dorian, capo 0).pdf").write_text("x", encoding="utf-8")
    (folder / "sheet (mine).pdf").write_text("y", encoding="utf-8")  # not recorded: yours
    db.kv_set_json(conn, f"{EXPORT_KV}{song.id}", {"G Dorian, capo 0": {"pdf": "sheet (G Dorian, capo 0).pdf",
                                                                        "query": "t=2&mode=dorian"}})
    plan, result = plan_and_remove(conn, cfg, song)
    assert "sheet (G Dorian, capo 0).pdf" in plan.delete and "sheet (mine).pdf" not in plan.delete
    assert not (folder / "sheet (G Dorian, capo 0).pdf").exists() and (folder / "sheet (mine).pdf").exists()
    assert db.kv_get_json(conn, f"{EXPORT_KV}{song.id}") is None


def test_a_removal_deletes_the_songs_tabs_from_gametabs_and_their_record_but_a_file_of_yours_stays(conn, cfg):
    song = creep(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    tab = version(conn, song, "tabs/actraiser/fillmore", "gametab", provider="gametabs")
    keep_file(conn, cfg.library_dir, song=song, version_id=tab, name="gametab-1.txt", data=b"e|--12--|\n", rank=1)
    (folder / "gametab-2.txt").write_text("my own", encoding="utf-8")  # put there by hand: yours
    db.kv_set(conn, f"gametabs:checked:{song.id}", "2026-10-28T03:30:00Z")
    db.kv_set(conn, f"gametabs:checked:{song.id}:pick", "tabs/actraiser/fillmore")

    plan, result = plan_and_remove(conn, cfg, song)

    assert "gametab-1.txt" in plan.delete and "gametab-2.txt" not in plan.delete
    assert not (folder / "gametab-1.txt").exists() and (folder / "gametab-2.txt").read_text(encoding="utf-8") == "my own"
    for key in (f"gametabs:checked:{song.id}", f"gametabs:checked:{song.id}:pick"):
        assert db.kv_get(conn, key) is None, key
