import json
import os
import re

import pytest

from tabarr.library import drop_file, keep_file, kept_files, safe_name, song_dir, write_atomic, write_info
from tabarr.versions import (
    SHEET_KINDS,
    mark_gone,
    mark_stale,
    picks,
    replaces_sheet,
    set_coverage,
    set_picks,
    song_versions,
    upsert_version,
)

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


def test_write_atomic_syncs_the_file_before_the_rename_and_the_folder_after(tmp_path, monkeypatch):
    # A power cut during the 03:30 run must not leave an empty sheet that the database says is kept.
    calls = []
    fsync, replace = os.fsync, os.replace

    def spy_fsync(fd):
        calls.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        fsync(fd)

    def spy_replace(src, dst):
        calls.append(("replace", os.fspath(dst)))
        replace(src, dst)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)
    folder = tmp_path / "lib" / "Soda Stereo" / "Signos"
    write_atomic(folder / "sheet.txt", b"x")

    assert [what for what, _ in calls] == ["fsync", "replace", "fsync"]
    real = os.path.realpath(folder)
    assert re.fullmatch(re.escape(real) + r"/\.sheet\.txt\.[0-9a-f]{8}\.tmp", calls[0][1])
    assert calls[1][1] == str(folder / "sheet.txt") and calls[2][1] == real


def test_holds_only_the_regular_file_with_those_bytes(tmp_path):
    from tabarr.library import holds

    path = tmp_path / "sheet.txt"
    sha = write_atomic(path, b"sheet")
    assert holds(path, sha) and holds(path, sha, size=5)
    assert not holds(path, sha, size=4)  # another length: not even read
    path.write_bytes(b"shoot")  # the same length, other bytes
    assert not holds(path, sha, size=5)
    path.unlink()
    assert not holds(path, sha)  # deleted, on a synced device say
    (tmp_path / "elsewhere.txt").write_bytes(b"sheet")
    path.symlink_to(tmp_path / "elsewhere.txt")
    assert not holds(path, sha)  # never read through a link
    path.unlink()
    path.mkdir()
    assert not holds(path, sha)


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


def test_stale_versions_are_out_of_the_running_until_recorded_again(conn):
    # A corrected match: what UG listed under the old one is another song's, until the new one lists it.
    s = add_song(conn)
    sheet, gone = _version(conn, s, 1), _version(conn, s, 3)
    gp = _version(conn, s, 2, slot="guitar", kind="guitar-pro")
    lacuerda = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/signos-1", song_id=s.id, slot="sheet",
                              kind="acordes", rating=0, votes=0, version=1, label=None,
                              url="https://acordes.lacuerda.net/soda_stereo/signos.shtml", raw={},
                              now="2026-10-18T03:30:00Z")
    set_picks(conn, s.id, ["guitar-pro"], [gp])
    mark_gone(conn, gone)

    assert mark_stale(conn, s.id, "ug") == 2

    assert [v.id for v in song_versions(conn, s.id)] == [lacuerda]
    rows = {v.id: (v.stale, v.gone, v.pick_rank) for v in song_versions(conn, s.id, include_gone=True)}
    assert rows == {sheet: (True, False, None), gp: (True, False, None), gone: (False, True, None),
                    lacuerda: (False, False, None)}
    assert _version(conn, s, 1) == sheet  # listed again under the new match
    assert [v.id for v in song_versions(conn, s.id)] == [sheet, lacuerda]


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


def test_sheet_kinds_are_every_kind_the_sheet_slot_holds():
    # UG's chords, LaCuerda's acordes and the auto-chords sheet: keeping one makes it the only pick.
    assert SHEET_KINDS == ("chords", "acordes", "auto")


def test_set_picks_over_every_sheet_kind_leaves_one_pick(conn):
    s = add_song(conn)
    ug = _version(conn, s, 1)
    lacuerda = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/signos-1", song_id=s.id,
                              slot="sheet", kind="acordes", rating=0, votes=0, version=1, label=None,
                              url="https://acordes.lacuerda.net/soda_stereo/signos.shtml", raw={},
                              now="2026-10-18T03:30:00Z")
    auto = upsert_version(conn, provider="auto", tab_id=str(s.id), song_id=s.id, slot="sheet", kind="auto",
                          rating=0, votes=0, version=1, label=None, url="file:///music/signos.flac", raw={},
                          now="2026-10-18T03:30:00Z")
    set_picks(conn, s.id, ("acordes",), [lacuerda])
    set_picks(conn, s.id, ("auto",), [auto])
    set_picks(conn, s.id, SHEET_KINDS, [ug])
    assert [v.id for v in picks(conn, s.id, SHEET_KINDS)] == [ug]


THRESHOLD = 0.8


@pytest.mark.parametrize("new,kept,replaces", [
    (0.9, 0.5, True),  # complete beats incomplete
    (0.8, 0.79, True),  # the threshold itself is complete
    (0.8, None, True),  # unknown coverage is incomplete
    (1.0, 0.85, False),  # two complete sheets tie: the kept one stays
    (0.85, 1.0, False),
    (0.5, 0.9, False),  # a partial sheet never beats a complete one
    (0.6, 0.4, True),  # of two incomplete sheets the one covering more wins
    (0.4, 0.6, False),
    (0.5, 0.5, False),  # a tie keeps the kept sheet
    (None, 0.3, False),  # unknown coverage never displaces a known partial sheet
    (None, 0.9, False),  # nor a complete one
    (None, 0.0, False),
    (0.5, None, False),  # a sheet of unknown coverage may be complete: a partial one doesn't displace it
    (0.0, None, False),
    (None, None, False),  # a tie
])
def test_replaces_sheet(new, kept, replaces):
    assert replaces_sheet(new, kept, THRESHOLD) is replaces


def test_replaces_sheet_follows_the_threshold():
    assert replaces_sheet(0.6, 0.4, 0.5) is True and replaces_sheet(0.6, 0.55, 0.5) is False


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
