import pytest

from tabarr.inbox import GP_EXTENSIONS, file_inbox, parse_download_name
from tabarr.library import keep_file, kept_files, song_dir
from tabarr.versions import set_picks, upsert_version

from conftest import add_song


@pytest.mark.parametrize("name,parsed", [
    ("Soda Stereo - De Musica Ligera (ver 2).gp5", ("Soda Stereo", "De Musica Ligera", 2)),
    ("Soda Stereo - De Musica Ligera (ver 2 by Pelusteriano).gp5", ("Soda Stereo", "De Musica Ligera", 2)),
    ("Metallica - One.gpx", ("Metallica", "One", None)),
    ("Artist - Title (solo).gp5", ("Artist", "Title", None)),
    ("random.gp5", (None, "random", None)),
    ("宋冬野 - 斑马斑马.gp", ("宋冬野", "斑马斑马", None)),
])
def test_parse_download_name(name, parsed):
    assert parse_download_name(name) == parsed


def pick(conn, song, tab_id, *, kind="guitar-pro", version=1):
    return upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="guitar", kind=kind,
                          rating=4.5, votes=10, version=version, label=None,
                          url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}", raw={}, now="x")


def drop(cfg, name, data=b"GP-DATA"):
    inbox = cfg.library_dir / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / name).write_bytes(data)
    return inbox / name


def test_files_into_song_by_name(conn, cfg):
    s = add_song(conn)
    v = pick(conn, s, 555890)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v])
    src = drop(cfg, "Soda Stereo - De Musica Ligera.gp5")
    stats = file_inbox(conn, cfg.library_dir)
    dest = song_dir(cfg.library_dir, s) / "guitar-1.gp5"
    assert stats.filed == [dest] and not src.exists()
    assert dest.read_bytes() == b"GP-DATA"
    assert [(f.name, f.version_id) for f in kept_files(conn, s.id)] == [("guitar-1.gp5", v)]


def test_version_number_selects_pick(conn, cfg):
    s = add_song(conn)
    a = pick(conn, s, 1, version=3)
    b = pick(conn, s, 2, version=1)
    set_picks(conn, s.id, ["guitar-pro", "power"], [a, b])
    drop(cfg, "Soda Stereo - De Musica Ligera (ver 1).gp5")
    file_inbox(conn, cfg.library_dir)
    assert [(f.name, f.version_id) for f in kept_files(conn, s.id)] == [("guitar-2.gp5", b)]


@pytest.mark.parametrize("ext,kind", [(".gp5", "guitar-pro"), (".ptb", "power")])
def test_version_number_selects_a_pick_of_the_files_kind(conn, cfg, ext, kind):
    # UG numbers versions within each type, so a Power Tab and a Guitar Pro file are both "ver 1".
    s = add_song(conn)
    other = "power" if kind == "guitar-pro" else "guitar-pro"
    first = pick(conn, s, 1, kind=other, version=1)
    second = pick(conn, s, 2, kind=kind, version=1)
    set_picks(conn, s.id, ["guitar-pro", "power"], [first, second])
    drop(cfg, f"Soda Stereo - De Musica Ligera (ver 1){ext}")
    file_inbox(conn, cfg.library_dir)
    assert [(f.name, f.version_id) for f in kept_files(conn, s.id)] == [(f"guitar-2{ext}", second)]


def test_version_number_of_another_kind_falls_back_to_the_kind(conn, cfg):
    s = add_song(conn)
    gp = pick(conn, s, 1, kind="guitar-pro", version=3)
    pt = pick(conn, s, 2, kind="power", version=1)
    set_picks(conn, s.id, ["guitar-pro", "power"], [gp, pt])
    drop(cfg, "Soda Stereo - De Musica Ligera (ver 1).gp5")
    file_inbox(conn, cfg.library_dir)
    assert [(f.name, f.version_id) for f in kept_files(conn, s.id)] == [("guitar-1.gp5", gp)]


def test_second_file_takes_next_open_pick(conn, cfg):
    s = add_song(conn)
    a, b = pick(conn, s, 1), pick(conn, s, 2, version=2)
    set_picks(conn, s.id, ["guitar-pro", "power"], [a, b])
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"one")
    file_inbox(conn, cfg.library_dir)
    drop(cfg, "Soda Stereo - De Musica Ligera.gpx", b"two")
    file_inbox(conn, cfg.library_dir)
    assert [f.name for f in kept_files(conn, s.id)] == ["guitar-1.gp5", "guitar-2.gpx"]


def test_a_new_top_pick_never_overwrites_the_file_of_the_old_one(conn, cfg):
    s = add_song(conn)
    a = pick(conn, s, 1, version=1)
    set_picks(conn, s.id, ["guitar-pro", "power"], [a])
    drop(cfg, "Soda Stereo - De Musica Ligera (ver 1).gp5", b"A's file")
    file_inbox(conn, cfg.library_dir)
    # A better-rated version appears: the next fetch ranks it first and A second.
    b = pick(conn, s, 2, version=2)
    set_picks(conn, s.id, ["guitar-pro", "power"], [b, a])
    drop(cfg, "Soda Stereo - De Musica Ligera (ver 2).gp5", b"B's file")
    stats = file_inbox(conn, cfg.library_dir)
    folder = song_dir(cfg.library_dir, s)
    assert (folder / "guitar-1.gp5").read_bytes() == b"A's file"
    assert stats.filed == [folder / "guitar-2.gp5"]
    assert (folder / "guitar-2.gp5").read_bytes() == b"B's file"
    kept = kept_files(conn, s.id)
    assert [(f.name, f.version_id) for f in kept] == [("guitar-1.gp5", a), ("guitar-2.gp5", b)]
    assert [f.kept_rank for f in kept] == [1, 1]  # each version's rank when it was filed


def test_a_guitar_file_put_in_the_folder_by_hand_is_never_overwritten(conn, cfg):
    s = add_song(conn)
    v = pick(conn, s, 1)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v])
    folder = song_dir(cfg.library_dir, s)
    folder.mkdir(parents=True)
    (folder / "guitar-1.gp5").write_bytes(b"mine")
    (folder / "guitar-2.gpx").write_bytes(b"also mine")  # a number is taken whatever the extension
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5", b"download")
    file_inbox(conn, cfg.library_dir)
    assert (folder / "guitar-1.gp5").read_bytes() == b"mine"
    assert (folder / "guitar-2.gpx").read_bytes() == b"also mine"
    assert [(f.name, f.version_id) for f in kept_files(conn, s.id)] == [("guitar-3.gp5", v)]
    assert (folder / "guitar-3.gp5").read_bytes() == b"download"


def test_ptb_prefers_power_pick(conn, cfg):
    s = add_song(conn)
    gp, pt = pick(conn, s, 1), pick(conn, s, 2, kind="power")
    set_picks(conn, s.id, ["guitar-pro", "power"], [gp, pt])
    drop(cfg, "Soda Stereo - De Musica Ligera.ptb")
    file_inbox(conn, cfg.library_dir)
    assert [(f.name, f.version_id) for f in kept_files(conn, s.id)] == [("guitar-2.ptb", pt)]


def test_duplicate_removed(conn, cfg):
    s = add_song(conn)
    a, b = pick(conn, s, 1), pick(conn, s, 2)
    set_picks(conn, s.id, ["guitar-pro", "power"], [a, b])
    drop(cfg, "Soda Stereo - De Musica Ligera.gp5")
    file_inbox(conn, cfg.library_dir)
    again = drop(cfg, "Soda Stereo - De Musica Ligera (1).gp5")
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.duplicates == [again] and not again.exists()
    assert [f.name for f in kept_files(conn, s.id)] == ["guitar-1.gp5"]


def test_cjk_name_files_into_cjk_song(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马，斑马")
    v = pick(conn, s, 7)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v])
    drop(cfg, "宋冬野 - 斑马斑马.gp")
    file_inbox(conn, cfg.library_dir)
    assert (cfg.library_dir / "宋冬野" / "斑马，斑马" / "guitar-1.gp").exists()


def test_title_only_name_matches_a_unique_open_pick(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    v = pick(conn, s, 9)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v])
    drop(cfg, "creep.gp5")
    file_inbox(conn, cfg.library_dir)
    assert [f.name for f in kept_files(conn, s.id)] == ["guitar-1.gp5"]


def test_unmatched_stays(conn, cfg):
    s = add_song(conn)
    v = pick(conn, s, 1)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v])
    a = drop(cfg, "Somebody Else - Unknown Song.gp5")
    b = drop(cfg, "notes.pdf")
    stats = file_inbox(conn, cfg.library_dir)
    assert sorted(stats.unmatched) == sorted([a, b]) and a.exists() and b.exists()


def test_a_symlink_in_the_inbox_is_refused_and_left_alone(conn, cfg, tmp_path):
    # Anyone who can write to the library could point a link at tabarr's credentials,
    # under a name the to-do page lists ("Guitar Pro pages to click").
    s = add_song(conn)
    v = pick(conn, s, 555890)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v])
    secret = tmp_path / "credentials" / "spotify_client_secret"
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
    """A song with an open pick, and a link in place of _inbox/ to a folder outside the library that
    holds a download for it and a copy of a file tabarr keeps. Returns the song, the inbox and the files."""
    s = add_song(conn)
    a, b = pick(conn, s, 555890), pick(conn, s, 555891, version=2)
    set_picks(conn, s.id, ["guitar-pro", "power"], [a, b])
    keep_file(conn, cfg.library_dir, song=s, version_id=a, name="guitar-1.gp5", data=b"KEPT", rank=1)
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
    # tabarr file the .gp* files of the folder it points at, and delete them there.
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
    import tabarr.inbox as inbox_module

    s = add_song(conn)
    set_picks(conn, s.id, ["guitar-pro", "power"], [pick(conn, s, 555890)])
    name = "Soda Stereo - De Musica Ligera.gp5"
    drop(cfg, name, b"DOWNLOAD")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / name).write_bytes(b"NOT THE INBOX'S")
    inbox, moved = cfg.library_dir / "_inbox", cfg.library_dir / "_inbox.moved"
    real = inbox_module._songs_with_open_picks

    def swapped(conn_):  # between reading the download and deleting it from the inbox
        inbox.rename(moved)
        inbox.symlink_to(elsewhere)
        return real(conn_)

    monkeypatch.setattr(inbox_module, "_songs_with_open_picks", swapped)
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

    from tabarr.cli import build_app

    _, _, new, kept = linked_inbox(conn, cfg, tmp_path)
    config = tmp_path / "tabarr.toml"
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
