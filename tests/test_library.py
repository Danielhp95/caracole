import json

import pytest

from tabarr.library import drop_file, keep_file, kept_files, safe_name, song_dir, write_atomic, write_info
from tabarr.versions import picks, set_coverage, set_picks, song_versions, upsert_version

from conftest import add_song


@pytest.mark.parametrize(
    "raw,safe",
    [
        ("AC/DC", "AC-DC"),
        ("What's Up?", "What's Up"),
        ("Live: Here", "Live - Here"),
        ("..", "_"),
        (".", "_"),
        ("", "_"),
        ("  Trailing dots...  ", "Trailing dots"),
        ('a<b>c"d|e*f', "abcdef"),
        ("back\\slash", "back-slash"),
        ("宋冬野", "宋冬野"),
        ("斑马，斑马", "斑马，斑马"),
        ("tab\tand\nnewline", "tab and newline"),
    ],
)
def test_safe_name(raw, safe):
    assert safe_name(raw) == safe


def test_safe_name_truncates_utf8():
    name = safe_name("é" * 200)
    assert len(name.encode("utf-8")) <= 120
    assert name == "é" * 60


def test_song_dir_stays_inside_library(conn, tmp_path):
    lib = tmp_path / "Library"
    for artist, title in [("../../etc", "passwd"), ("AC/DC", "Back In Black - Remastered"), ("..", "..")]:
        s = add_song(conn, artist, title)
        d = song_dir(lib, s)
        assert d.resolve().is_relative_to(lib.resolve())
        assert d.parent.parent == lib
    s = add_song(conn, "AC/DC", "Back In Black - 2003 Remaster")
    assert song_dir(lib, s) == lib / "AC-DC" / "Back In Black"


def test_write_atomic_returns_sha256(tmp_path):
    sha = write_atomic(tmp_path / "a" / "f.txt", b"hello")
    assert sha == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert (tmp_path / "a" / "f.txt").read_bytes() == b"hello"
    assert not list((tmp_path / "a").glob("*.tmp"))


def _version(conn, song, tab_id, *, slot="sheet", kind="chords", rating=4.5, votes=10):
    return upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot=slot, kind=kind,
                          rating=rating, votes=votes, version=1, label=None,
                          url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}", raw={"id": tab_id},
                          now="2026-10-18T03:30:00Z")


def test_upsert_version_is_unique_per_song_and_updates(conn):
    s = add_song(conn)
    v1 = _version(conn, s, 85053, rating=4.5, votes=7)
    v2 = _version(conn, s, 85053, rating=4.6, votes=8)
    assert v1 == v2
    rows = song_versions(conn, s.id)
    assert len(rows) == 1 and rows[0].rating == 4.6 and rows[0].votes == 8 and rows[0].raw == {"id": 85053}
    other = add_song(conn, "Other", "Song")
    assert _version(conn, other, 85053) != v1


def test_song_versions_filters(conn):
    s = add_song(conn)
    _version(conn, s, 1)
    _version(conn, s, 2, slot="guitar", kind="guitar-pro")
    _version(conn, s, 3, slot="guitar", kind="tabs")
    assert [v.tab_id for v in song_versions(conn, s.id, slot="guitar")] == ["2", "3"]
    assert [v.tab_id for v in song_versions(conn, s.id, kinds=["tabs"])] == ["3"]


def test_set_coverage(conn):
    s = add_song(conn)
    v = _version(conn, s, 1)
    set_coverage(conn, v, 0.85)
    assert song_versions(conn, s.id)[0].coverage == 0.85


def test_set_picks_ranks_and_clears(conn):
    s = add_song(conn)
    a = _version(conn, s, 1, slot="guitar", kind="guitar-pro")
    b = _version(conn, s, 2, slot="guitar", kind="power")
    t = _version(conn, s, 3, slot="guitar", kind="tabs")
    set_picks(conn, s.id, ["guitar-pro", "power"], [b, a])
    set_picks(conn, s.id, ["tabs"], [t])
    assert [v.id for v in picks(conn, s.id, ["guitar-pro", "power"])] == [b, a]
    set_picks(conn, s.id, ["guitar-pro", "power"], [a])
    assert [v.id for v in picks(conn, s.id, ["guitar-pro", "power"])] == [a]
    assert [v.id for v in picks(conn, s.id, ["tabs"])] == [t]


def test_keep_file_replaces_and_dedupes(conn, tmp_path):
    lib = tmp_path / "Library"
    s = add_song(conn)
    v1 = _version(conn, s, 1)
    v2 = _version(conn, s, 2)
    assert keep_file(conn, lib, song=s, version_id=v1, name="sheet.txt", data=b"one", rank=1)
    path = song_dir(lib, s) / "sheet.txt"
    assert path.read_bytes() == b"one"
    # Same name, new version: replaced in place.
    assert keep_file(conn, lib, song=s, version_id=v2, name="sheet.txt", data=b"two", rank=1)
    assert path.read_bytes() == b"two"
    rows = kept_files(conn, s.id)
    assert [(r.name, r.version_id) for r in rows] == [("sheet.txt", v2)]
    # Identical bytes under another name in the same song: not written twice.
    assert not keep_file(conn, lib, song=s, version_id=v1, name="tab.txt", data=b"two", rank=1)
    assert not (song_dir(lib, s) / "tab.txt").exists()
    drop_file(conn, lib, song=s, name="sheet.txt")
    assert not path.exists() and kept_files(conn, s.id) == []


def test_write_info_lists_kept_versions(conn, tmp_path):
    lib = tmp_path / "Library"
    s = add_song(conn, "宋冬野", "斑马，斑马")
    v = _version(conn, s, 99)
    keep_file(conn, lib, song=s, version_id=v, name="sheet.txt", data=b"x", rank=1)
    p = write_info(conn, lib, s)
    info = json.loads(p.read_text(encoding="utf-8"))
    assert p == lib / "宋冬野" / "斑马，斑马" / "info.json"
    assert info["artist"] == "宋冬野" and info["title"] == "斑马，斑马"
    assert info["files"][0]["name"] == "sheet.txt"
    assert info["files"][0]["url"] == "https://tabs.ultimate-guitar.com/tab/99"
