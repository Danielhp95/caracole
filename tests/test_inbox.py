import pytest

from tabarr.inbox import GP_EXTENSIONS, file_inbox, parse_download_name
from tabarr.library import kept_files, song_dir
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


def test_no_inbox_is_fine(conn, cfg):
    stats = file_inbox(conn, cfg.library_dir)
    assert stats.filed == [] and stats.unmatched == []


def test_extensions():
    assert {".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb"} == set(GP_EXTENSIONS)
