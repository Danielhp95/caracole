import pytest

from caracole.inbox import GP_EXTENSIONS, SCORE_EXTENSIONS, file_inbox, parse_download_name
from caracole.library import keep_file, kept_files, song_dir
from caracole.versions import upsert_version

from conftest import add_song


@pytest.mark.parametrize("name,parsed", [
    ("Soda Stereo - De Musica Ligera (ver 2).gp5", ("Soda Stereo", "De Musica Ligera", 2)),
    ("Soda Stereo - De Musica Ligera (ver 2 by Pelusteriano).gp5", ("Soda Stereo", "De Musica Ligera", 2)),
    ("Metallica - One.gpx", ("Metallica", "One", None)),
    ("Artist - Title (solo).gp5", ("Artist", "Title", None)),
    ("random.gp5", (None, "random", None)),
    ("宋冬野 - 斑马斑马.gp", ("宋冬野", "斑马斑马", None)),
    # UG names a download after its artist and song, which it writes in two scripts for some: a
    # bracketed original is a part of the name, the version (and its tabber's name) is not.
    ("Jay Chou (周杰倫) - 晴天 (ver 1).gp5", ("Jay Chou (周杰倫)", "晴天", 1)),
    ("米津玄師 - Lemon (レモン) (ver 3).gp5", ("米津玄師", "Lemon (レモン)", 3)),
    ("宋冬野 - 斑马斑马 (ver 2 by 小明).gp5", ("宋冬野", "斑马斑马", 2)),
    ("宋冬野 - 斑马斑马 (Banma Banma) (ver 2).gp5", ("宋冬野", "斑马斑马", 2)),
])
def test_parse_download_name(name, parsed):
    assert parse_download_name(name) == parsed


def test_the_cutoff_is_one_music_names_scores_exactly():
    # Names.score compares no artists for a title below music's cutoff less its margin, so a
    # download's score is exact only from there up: inbox's own cutoff must stay at or above it.
    from caracole import inbox, music

    assert inbox.MATCH_CUTOFF >= music.MATCH_CUTOFF - music.MATCH_MARGIN


def guitar_version(conn, song, kind="guitar-pro"):
    """The song's one inbox version of a Guitar Pro kind, as file_inbox records one."""
    return upsert_version(conn, provider="inbox", tab_id=kind, song_id=song.id, slot="guitar", kind=kind, rating=0,
                          votes=0, version=1, label=None, url="", raw={}, now="x")


def drop(cfg, name, data=b"GP-DATA"):
    inbox = cfg.library_dir / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / name).write_bytes(data)
    return inbox / name


def guitar_kept(conn, song):
    from caracole.versions import get_version

    return [(f.name, get_version(conn, f.version_id).provider, get_version(conn, f.version_id).kind)
            for f in kept_files(conn, song.id)]


def test_files_into_song_by_name(conn, cfg):
    # Any song, as for a score: caracole picks no Guitar Pro version anywhere for you to download.
    s = add_song(conn)
    src = drop(cfg, "Soda Stereo - De Musica Ligera.gp5")
    stats = file_inbox(conn, cfg.library_dir)
    dest = song_dir(cfg.library_dir, s) / "guitar-1.gp5"
    assert stats.filed == [dest] and not src.exists()
    assert dest.read_bytes() == b"GP-DATA"
    assert guitar_kept(conn, s) == [("guitar-1.gp5", "inbox", "guitar-pro")]
    assert [f.kept_rank for f in kept_files(conn, s.id)] == [1]


def test_a_power_tab_file_is_kept_for_the_songs_power_tab_version(conn, cfg):
    s = add_song(conn)
    drop(cfg, "Soda Stereo - De Musica Ligera.ptb")
    file_inbox(conn, cfg.library_dir)
    assert guitar_kept(conn, s) == [("guitar-1.ptb", "inbox", "power")]


def test_a_version_number_in_the_name_still_names_the_song(conn, cfg):
    s = add_song(conn)
    drop(cfg, "Soda Stereo - De Musica Ligera (ver 2 by Pelusteriano).gp5")
    file_inbox(conn, cfg.library_dir)
    assert guitar_kept(conn, s) == [("guitar-1.gp5", "inbox", "guitar-pro")]


def test_a_second_file_takes_the_next_free_number(conn, cfg):
    s = add_song(conn)
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"one")
    file_inbox(conn, cfg.library_dir)
    drop(cfg, "Soda Stereo - De Musica Ligera.gpx", b"two")
    drop(cfg, "Soda Stereo - De Musica Ligera.ptb", b"three")
    file_inbox(conn, cfg.library_dir)
    assert guitar_kept(conn, s) == [("guitar-1.gp5", "inbox", "guitar-pro"), ("guitar-2.gpx", "inbox", "guitar-pro"),
                                    ("guitar-3.ptb", "inbox", "power")]


def test_a_file_beside_one_from_gtptabs_takes_the_next_number(conn, cfg):
    s = add_song(conn)
    gtp = upsert_version(conn, provider="gtptabs", tab_id="9", song_id=s.id, slot="guitar", kind="guitar-pro",
                         rating=4, votes=0, version=1, label=None, url="https://gtptabs.com/tabs/9.html", raw={},
                         now="x")
    keep_file(conn, cfg.library_dir, song=s, version_id=gtp, name="guitar-1.gp5", data=b"FROM GTPTABS", rank=1)
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"MINE")
    file_inbox(conn, cfg.library_dir)
    folder = song_dir(cfg.library_dir, s)
    assert (folder / "guitar-1.gp5").read_bytes() == b"FROM GTPTABS"
    assert (folder / "guitar-2.gp5").read_bytes() == b"MINE"
    assert guitar_kept(conn, s) == [("guitar-1.gp5", "gtptabs", "guitar-pro"), ("guitar-2.gp5", "inbox", "guitar-pro")]


def test_a_guitar_file_put_in_the_folder_by_hand_is_never_overwritten(conn, cfg):
    s = add_song(conn)
    folder = song_dir(cfg.library_dir, s)
    folder.mkdir(parents=True)
    (folder / "guitar-1.gp5").write_bytes(b"mine")
    (folder / "guitar-2.gpx").write_bytes(b"also mine")  # a number is taken whatever the extension
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"download")
    file_inbox(conn, cfg.library_dir)
    assert (folder / "guitar-1.gp5").read_bytes() == b"mine"
    assert (folder / "guitar-2.gpx").read_bytes() == b"also mine"
    assert guitar_kept(conn, s) == [("guitar-3.gp5", "inbox", "guitar-pro")]
    assert (folder / "guitar-3.gp5").read_bytes() == b"download"


def test_a_number_another_song_keeps_in_the_folder_their_names_make_is_not_taken(conn, cfg):
    # Two parts whose titles agree for longer than a folder's name keeps: one folder, two songs.
    long = ("Concierto de Aranjuez para guitarra y orquesta, segundo movimiento, arreglo para guitarra sola de Narciso "
            "Yepes, grabado en Madrid, part")
    one, two = add_song(conn, "Joaquín Rodrigo", f"{long} one"), add_song(conn, "Joaquín Rodrigo", f"{long} two")
    folder = song_dir(cfg.library_dir, one)
    assert one.key != two.key and song_dir(cfg.library_dir, two) == folder
    keep_file(conn, cfg.library_dir, song=one, version_id=guitar_version(conn, one), name="guitar-1.gp5", data=b"ONE",
              rank=1)
    (folder / "guitar-1.gp5").unlink()  # lost on a synced device: the first song keeps its number all the same
    src = drop(cfg, f"Joaquín Rodrigo - {long} two.gp5", b"TWO")
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [folder / "guitar-2.gp5"] and not src.exists()
    assert guitar_kept(conn, two) == [("guitar-2.gp5", "inbox", "guitar-pro")]


def test_duplicate_removed(conn, cfg):
    s = add_song(conn)
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5")
    file_inbox(conn, cfg.library_dir)
    again = drop(cfg, "Soda Stereo - De Musica Ligera (1).gp5")
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.duplicates == [again] and not again.exists()
    assert [f.name for f in kept_files(conn, s.id)] == ["guitar-1.gp5"]


def test_a_file_the_library_lost_dropped_again_is_put_back(conn, cfg):
    s = add_song(conn)
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"GP-DATA")
    file_inbox(conn, cfg.library_dir)
    kept = song_dir(cfg.library_dir, s) / "guitar-1.gp5"
    kept.unlink()  # deleted on a synced device
    again = drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"GP-DATA")  # downloaded again
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [kept] and stats.duplicates == [] and not again.exists()
    assert kept.read_bytes() == b"GP-DATA"
    assert guitar_kept(conn, s) == [("guitar-1.gp5", "inbox", "guitar-pro")]


def test_a_file_filed_for_an_ultimate_guitar_pick_before_stays_and_is_put_back_on_its_version(conn, cfg):
    # A file caracole filed when it still picked Guitar Pro versions on Ultimate Guitar keeps that version
    # (schema 9 leaves a version that has a file): dropped again once the library lost it, it is put back there.
    s = add_song(conn)
    old = upsert_version(conn, provider="ug", tab_id="555890", song_id=s.id, slot="guitar", kind="guitar-pro",
                         rating=4.5, votes=10, version=1, label=None,
                         url="https://tabs.ultimate-guitar.com/tab/555890", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=s, version_id=old, name="guitar-1.gp5", data=b"FROM UG", rank=1)
    (song_dir(cfg.library_dir, s) / "guitar-1.gp5").unlink()
    drop(cfg, "Soda Stereo - De Musica Ligera (ver 1).gp5", b"FROM UG")
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [song_dir(cfg.library_dir, s) / "guitar-1.gp5"]
    assert guitar_kept(conn, s) == [("guitar-1.gp5", "ug", "guitar-pro")]


def test_a_lost_score_dropped_again_under_another_name_is_put_back(conn, cfg):
    s = add_song(conn, "Oasis", "Wonderwall")
    drop(cfg, "Oasis - Wonderwall.pdf", b"%PDF-score")
    file_inbox(conn, cfg.library_dir)
    kept = song_dir(cfg.library_dir, s) / "score-1.pdf"
    kept.unlink()
    again = drop(cfg, "download (3).pdf", b"%PDF-score")  # a name no song has: the bytes say which file it is
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [kept] and not again.exists() and kept.read_bytes() == b"%PDF-score"
    assert score_kept(conn, s) == [("score-1.pdf", "inbox", "score")]


def test_a_download_with_the_bytes_of_a_file_you_changed_replaces_nothing_and_stays(conn, cfg):
    s = add_song(conn)
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"GP-DATA")
    file_inbox(conn, cfg.library_dir)
    kept = song_dir(cfg.library_dir, s) / "guitar-1.gp5"
    kept.write_bytes(b"edited on the laptop")
    again = drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"GP-DATA")
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [] and stats.duplicates == [] and stats.unmatched == [again] and again.exists()
    assert kept.read_bytes() == b"edited on the laptop"


def test_a_download_with_another_songs_bytes_is_filed_for_its_own_song(conn, cfg):
    live = add_song(conn, "Soda Stereo", "Persiana Americana")
    s = add_song(conn)
    drop(cfg, "Soda Stereo - Persiana Americana.gp5", b"SAME BYTES")
    file_inbox(conn, cfg.library_dir)
    src = drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"SAME BYTES")
    stats = file_inbox(conn, cfg.library_dir)
    dest = song_dir(cfg.library_dir, s) / "guitar-1.gp5"
    assert stats.filed == [dest] and stats.duplicates == [] and not src.exists()
    assert dest.read_bytes() == b"SAME BYTES"
    assert guitar_kept(conn, s) == [("guitar-1.gp5", "inbox", "guitar-pro")]
    assert guitar_kept(conn, live) == [("guitar-1.gp5", "inbox", "guitar-pro")]


def test_cjk_name_files_into_cjk_song(conn, cfg):
    add_song(conn, "宋冬野", "斑马，斑马")
    drop(cfg, "宋冬野 - 斑马斑马.gp")
    file_inbox(conn, cfg.library_dir)
    assert (cfg.library_dir / "宋冬野" / "斑马，斑马" / "guitar-1.gp").exists()


def test_a_download_named_in_two_scripts_files_into_its_song(conn, cfg):
    # Ultimate Guitar and others name a download after the artist and song, in two scripts for 宋冬野.
    s = add_song(conn, "宋冬野", "斑马斑马")
    other = add_song(conn, "宋冬野", "董小姐")
    drop(cfg, "Song Dongye (宋冬野) - 斑马 斑马 Banma Banma Zebra Zebra (ver 1 by someone).gp5")
    file_inbox(conn, cfg.library_dir)
    assert [f.name for f in kept_files(conn, s.id)] == ["guitar-1.gp5"]
    assert kept_files(conn, other.id) == []


def test_a_name_of_the_title_alone_needs_the_only_song_of_that_title(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    drop(cfg, "creep.gp5", b"one")
    file_inbox(conn, cfg.library_dir)
    assert [f.name for f in kept_files(conn, s.id)] == ["guitar-1.gp5"]
    add_song(conn, "TLC", "Creep")
    left = drop(cfg, "creep.gpx", b"two")
    assert file_inbox(conn, cfg.library_dir).unmatched == [left] and left.exists()


def test_an_ignored_song_gets_no_guitar_file(conn, cfg):
    from caracole.songs import update_song

    s = add_song(conn)
    update_song(conn, s.id, status="ignored")
    left = drop(cfg, "Soda Stereo - De Musica Ligera.gp5")
    assert file_inbox(conn, cfg.library_dir).unmatched == [left] and left.exists()


def test_unmatched_stays(conn, cfg):
    add_song(conn)
    a = drop(cfg, "Somebody Else - Unknown Song.gp5")
    b = drop(cfg, "notes.pdf")
    stats = file_inbox(conn, cfg.library_dir)
    assert sorted(stats.unmatched) == sorted([a, b]) and a.exists() and b.exists()


def test_a_symlink_in_the_inbox_is_refused_and_left_alone(conn, cfg, tmp_path):
    # Anyone who can write to the library could point a link at caracole's credentials, under a name the
    # to-do page would list (its inbox section).
    s = add_song(conn)
    secret = tmp_path / "credentials" / "ntfy_token"
    secret.parent.mkdir()
    secret.write_text("f00dfeedcafe0123456789abcdef0123\n")
    inbox = cfg.library_dir / "_inbox"
    inbox.mkdir(parents=True)
    gp, other = inbox / "Soda Stereo - De Musica Ligera.gp5", inbox / "notes.txt"
    gp.symlink_to(secret)
    other.symlink_to(secret)
    stats = file_inbox(conn, cfg.library_dir)
    assert kept_files(conn, s.id) == []
    assert not song_dir(cfg.library_dir, s).exists()
    assert gp.is_symlink() and other.is_symlink()
    assert stats.refused == [gp, other] and stats.filed == [] and stats.unmatched == []


def linked_inbox(conn, cfg, tmp_path):
    """A song with a Guitar Pro file kept, and a link in place of _inbox/ to a folder outside the library that
    holds a download for it and a copy of the file caracole keeps. Returns the song, the inbox and the files."""
    s = add_song(conn)
    keep_file(conn, cfg.library_dir, song=s, version_id=guitar_version(conn, s), name="guitar-1.gp5", data=b"KEPT",
              rank=1)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    new, kept = elsewhere / "Soda Stereo - De Musica Ligera (ver 2).gp5", elsewhere / "copy.gp5"
    new.write_bytes(b"GP-DATA")
    kept.write_bytes(b"KEPT")
    inbox = cfg.library_dir / "_inbox"
    inbox.symlink_to(elsewhere)
    return s, inbox, new, kept


def test_a_linked_inbox_is_refused_and_nothing_is_read_filed_or_deleted_through_it(conn, cfg, tmp_path):
    # Anyone who can write to the library can put a link in place of _inbox/: followed, it would have
    # caracole file the .gp* files of the folder it points at, and delete them there.
    s, inbox, new, kept = linked_inbox(conn, cfg, tmp_path)
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.refused == [inbox]
    assert stats.filed == [] and stats.duplicates == [] and stats.unmatched == []
    assert new.read_bytes() == b"GP-DATA" and kept.read_bytes() == b"KEPT"
    assert [f.name for f in kept_files(conn, s.id)] == ["guitar-1.gp5"]
    assert inbox.is_symlink()


def test_an_inbox_swapped_for_a_link_while_it_is_filed_is_emptied_only_where_it_was(conn, cfg, tmp_path,
                                                                                    monkeypatch):
    # A synced device can put a link in place of _inbox/ at any time: the folder is listed, read and
    # emptied through the descriptor it was opened as, so a link swapped in meanwhile leads nowhere.
    import caracole.inbox as inbox_module

    s = add_song(conn)
    name = "Soda Stereo - De Musica Ligera.gp5"
    drop(cfg, name, b"DOWNLOAD")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / name).write_bytes(b"NOT THE INBOX'S")
    inbox, moved = cfg.library_dir / "_inbox", cfg.library_dir / "_inbox.moved"
    real = inbox_module._download_song

    def swapped(*args):  # between reading the download and deleting it from the inbox
        inbox.rename(moved)
        inbox.symlink_to(elsewhere)
        return real(*args)

    monkeypatch.setattr(inbox_module, "_download_song", swapped)
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [song_dir(cfg.library_dir, s) / "guitar-1.gp5"]
    assert stats.filed[0].read_bytes() == b"DOWNLOAD"
    assert (elsewhere / name).read_bytes() == b"NOT THE INBOX'S"
    assert not (moved / name).exists()


def test_a_dangling_inbox_link_is_refused(conn, cfg):
    cfg.library_dir.mkdir(parents=True)
    inbox = cfg.library_dir / "_inbox"
    inbox.symlink_to(cfg.library_dir / "gone")
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.refused == [inbox] and stats.filed == [] and stats.unmatched == []


def test_scan_says_it_refused_a_linked_inbox(conn, cfg, tmp_path):
    from typer.testing import CliRunner

    from caracole.cli import build_app

    _, _, new, kept = linked_inbox(conn, cfg, tmp_path)
    config = tmp_path / "caracole.toml"
    dirs = ("library_dir", "music_dir", "state_dir", "cache_dir")
    config.write_text("".join(f'{d} = "{getattr(cfg, d)}"\n' for d in dirs), encoding="utf-8")
    result = CliRunner().invoke(build_app(), ["--config", str(config), "scan"])
    assert result.exit_code == 0, result.output
    assert "Inbox: 0 filed, 0 duplicates, 0 left, 1 symbolic link refused" in result.output
    assert new.exists() and kept.exists()
    todo = (cfg.library_dir / "_todo.md").read_text(encoding="utf-8")
    assert "`_inbox` is a symbolic link" in todo and "Soda Stereo - De Musica Ligera (ver 2)" not in todo


def test_no_inbox_is_fine(conn, cfg):
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [] and stats.unmatched == [] and stats.refused == []


def test_an_inbox_that_is_a_file_is_no_inbox(conn, cfg):
    cfg.library_dir.mkdir(parents=True)
    (cfg.library_dir / "_inbox").write_bytes(b"not a folder")
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [] and stats.unmatched == [] and stats.refused == []


def test_extensions():
    assert {".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb"} == set(GP_EXTENSIONS)


# --- scores: MuseScore downloads --------------------------------------------------------------


def score_kept(conn, song):
    from caracole.versions import get_version

    return [(f.name, get_version(conn, f.version_id).provider, get_version(conn, f.version_id).kind)
            for f in kept_files(conn, song.id)]


def test_a_score_named_as_the_song_is_filed_as_its_score(conn, cfg):
    # Any song, with or without picks: MuseScore's pages are listed for every song.
    s = add_song(conn, "Oasis", "Wonderwall")
    src = drop(cfg, "Oasis - Wonderwall.mscz", b"PK-MSCZ")
    stats = file_inbox(conn, cfg.library_dir)
    dest = song_dir(cfg.library_dir, s) / "score-1.mscz"
    assert stats.filed == [dest] and not src.exists() and dest.read_bytes() == b"PK-MSCZ"
    assert score_kept(conn, s) == [("score-1.mscz", "inbox", "score")]


def test_every_format_musescore_downloads_is_a_score(conn, cfg):
    s = add_song(conn, "Oasis", "Wonderwall")
    for ext in SCORE_EXTENSIONS:
        drop(cfg, f"Oasis - Wonderwall{ext}", f"data{ext}".encode())
    file_inbox(conn, cfg.library_dir)
    assert sorted(name for name, _, _ in score_kept(conn, s)) == sorted(f"score-1{ext}" for ext in SCORE_EXTENSIONS)


def test_a_score_pdf_never_takes_the_place_of_the_sheet_pdf(conn, cfg):
    # caracole renders sheet.pdf itself: a PDF from MuseScore is a score beside it.
    s = add_song(conn, "Oasis", "Wonderwall")
    folder = song_dir(cfg.library_dir, s)
    folder.mkdir(parents=True)
    (folder / "sheet.pdf").write_bytes(b"rendered")
    drop(cfg, "Oasis - Wonderwall.pdf", b"%PDF-score")
    file_inbox(conn, cfg.library_dir)
    assert (folder / "sheet.pdf").read_bytes() == b"rendered"
    assert (folder / "score-1.pdf").read_bytes() == b"%PDF-score"


def test_another_score_of_a_format_takes_the_next_free_number(conn, cfg):
    s = add_song(conn, "Oasis", "Wonderwall")
    drop(cfg, "Oasis - Wonderwall.pdf", b"%PDF-one")
    file_inbox(conn, cfg.library_dir)
    (song_dir(cfg.library_dir, s) / "score-2.pdf").write_bytes(b"yours")
    drop(cfg, "Oasis - Wonderwall.pdf", b"%PDF-two")
    file_inbox(conn, cfg.library_dir)
    assert (song_dir(cfg.library_dir, s) / "score-2.pdf").read_bytes() == b"yours"
    assert [name for name, _, _ in score_kept(conn, s)] == ["score-1.pdf", "score-3.pdf"]


def test_a_score_kept_already_is_a_duplicate(conn, cfg):
    add_song(conn, "Oasis", "Wonderwall")
    drop(cfg, "Oasis - Wonderwall.mid", b"MThd-same")
    file_inbox(conn, cfg.library_dir)
    again = drop(cfg, "Oasis - Wonderwall (1).mid", b"MThd-same")
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.duplicates == [again] and not again.exists()


def test_a_score_named_by_its_title_alone_needs_the_only_song_of_that_title(conn, cfg):
    oasis = add_song(conn, "Oasis", "Wonderwall")
    drop(cfg, "Wonderwall.pdf", b"%PDF-one")
    file_inbox(conn, cfg.library_dir)
    assert [name for name, _, _ in score_kept(conn, oasis)] == ["score-1.pdf"]
    add_song(conn, "Ryan Adams", "Wonderwall")
    left = drop(cfg, "Wonderwall.mid", b"MThd")
    assert file_inbox(conn, cfg.library_dir).unmatched == [left]


def test_a_musicxml_file_is_filed_by_the_title_and_creator_inside(conn, cfg):
    from helpers.scores import musicxml, mxl

    oasis = add_song(conn, "Oasis", "Wonderwall")
    ryan = add_song(conn, "Ryan Adams", "Wonderwall")
    drop(cfg, "score.musicxml", musicxml("Wonderwall", "Oasis"))
    drop(cfg, "export.mxl", mxl(musicxml("Wonderwall (Live)", "Ryan Adams")))
    stats = file_inbox(conn, cfg.library_dir)
    assert len(stats.filed) == 2 and stats.unmatched == []
    assert score_kept(conn, oasis) == [("score-1.musicxml", "inbox", "score")]
    assert score_kept(conn, ryan) == [("score-1.mxl", "inbox", "score")]


def test_a_musicxml_file_whose_creator_is_no_artist_of_the_song_stays(conn, cfg):
    from helpers.scores import musicxml

    add_song(conn, "Oasis", "Wonderwall")
    left = drop(cfg, "score.musicxml", musicxml("Wonderwall", "Noel Gallagher"))
    assert file_inbox(conn, cfg.library_dir).unmatched == [left] and left.exists()


def test_a_musicxml_file_that_wont_read_stays(conn, cfg):
    add_song(conn, "Oasis", "Wonderwall")
    left = drop(cfg, "export.mxl", b"not a zip")
    assert file_inbox(conn, cfg.library_dir).unmatched == [left] and left.exists()


def test_an_ignored_song_gets_no_score(conn, cfg):
    from caracole.songs import update_song

    s = add_song(conn, "Oasis", "Wonderwall")
    update_song(conn, s.id, status="ignored")
    left = drop(cfg, "Oasis - Wonderwall.pdf", b"%PDF")
    assert file_inbox(conn, cfg.library_dir).unmatched == [left]


def test_score_extensions():
    assert set(SCORE_EXTENSIONS) == {".mscz", ".mxl", ".musicxml", ".pdf", ".mid", ".midi"}
