import sqlite3

import pytest

from tabarr import db
from tabarr.songs import get_song, find_song, list_songs, refresh_status, update_song, upsert_song

from conftest import add_song


def test_connect_creates_schema_and_version(tmp_path):
    c = db.connect(tmp_path / "a" / "t.sqlite")
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"songs", "ug_index", "versions", "files", "events", "kv"} <= tables
    assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c.close()
    # Reopening is idempotent.
    db.connect(tmp_path / "a" / "t.sqlite").close()


def test_kv_roundtrip(conn):
    assert db.kv_get(conn, "x") is None
    db.kv_set(conn, "x", "1")
    db.kv_set(conn, "x", "2")
    assert db.kv_get(conn, "x") == "2"
    db.kv_set_json(conn, "j", {"a": [1, "é"]})
    assert db.kv_get_json(conn, "j") == {"a": [1, "é"]}
    assert db.kv_get_json(conn, "missing", default=[]) == []


def test_upsert_creates_then_merges(conn):
    a = upsert_song(conn, artists=["Soda Stereo"], title="De Música Ligera", album=None, duration_ms=213000,
                    isrc=None, source="spotify", source_id="t1", added_at="2026-01-01T00:00:00Z")
    b = upsert_song(conn, artists=["Soda Stereo"], title="De Música Ligera", album="Canción Animal",
                    duration_ms=None, isrc="ARX1", source="spotify", source_id="t1",
                    added_at="2026-02-01T00:00:00Z")
    assert a == (1, True)
    assert b == (1, False)
    s = get_song(conn, 1)
    assert s.album == "Canción Animal"
    assert s.duration_ms == 213000
    assert s.isrc == "ARX1"
    assert s.source_ids == {"spotify": ["t1"]}
    assert s.added_at.startswith("2026-02")
    assert s.key == "soda-stereo/de-musica-ligera"
    assert s.status == "wanted" and s.ug_dirty and s.lyrics_status == "pending"


def test_remaster_merges_with_original(conn):
    upsert_song(conn, artists=["The Beatles"], title="Let It Be - Remastered 2009", album=None,
                duration_ms=243000, isrc=None, source="spotify", source_id="t2", added_at="2026-01-01T00:00:00Z")
    upsert_song(conn, artists=["The Beatles"], title="Let It Be", album=None, duration_ms=243000,
                isrc=None, source="spotify", source_id="t3", added_at="2026-01-02T00:00:00Z")
    rows = list_songs(conn)
    assert len(rows) == 1
    assert rows[0].source_ids == {"spotify": ["t2", "t3"]}
    assert rows[0].title == "Let It Be - Remastered 2009"
    assert rows[0].display == "The Beatles - Let It Be"


def test_same_song_from_two_sources(conn):
    upsert_song(conn, artists=["宋冬野"], title="斑马，斑马", album=None, duration_ms=253000, isrc=None,
                source="spotify", source_id="sp1", added_at="2026-01-01T00:00:00Z")
    _, created = upsert_song(conn, artists=["宋冬野"], title="斑马斑马", album="安和桥北", duration_ms=253000,
                             isrc=None, source="wanted", source_id="宋冬野/斑马斑马",
                             added_at="2026-01-03T00:00:00Z")
    assert not created
    s = list_songs(conn)[0]
    assert s.source_ids == {"spotify": ["sp1"], "wanted": ["宋冬野/斑马斑马"]}
    assert s.album == "安和桥北"


def test_variant_kept_from_source_title(conn):
    s = add_song(conn, "Radiohead", "Creep - Acoustic")
    assert s.variant == "acoustic"
    assert s.key == "radiohead/creep"


def test_list_songs_newest_first_and_status_filter(conn):
    add_song(conn, "A", "One", added_at="2026-01-01T00:00:00Z")
    add_song(conn, "B", "Two", added_at="2026-03-01T00:00:00Z")
    add_song(conn, "C", "Three", added_at="2026-02-01T00:00:00Z")
    assert [s.title for s in list_songs(conn)] == ["Two", "Three", "One"]
    update_song(conn, list_songs(conn)[0].id, status="ignored")
    assert [s.title for s in list_songs(conn, statuses=["wanted"])] == ["Three", "One"]


def test_update_song_encodes_json_and_rejects_unknown_fields(conn):
    s = add_song(conn)
    update_song(conn, s.id, match_candidates=[{"artist_key": "x", "score": 80.0}], review=True)
    s2 = get_song(conn, s.id)
    assert s2.match_candidates == [{"artist_key": "x", "score": 80.0}]
    assert s2.review is True
    with pytest.raises(ValueError, match="nope"):
        update_song(conn, s.id, nope=1)


def test_status_check_constraint(conn):
    s = add_song(conn)
    with pytest.raises(sqlite3.IntegrityError):
        update_song(conn, s.id, status="maybe")


def test_find_song_by_key(conn):
    s = add_song(conn)
    assert find_song(conn, "soda-stereo/de-musica-ligera").id == s.id
    assert find_song(conn, "nobody/nothing") is None


def test_refresh_status_found_requires_kept_sheet(conn):
    s = add_song(conn)
    assert refresh_status(conn, s.id, ignored=False) == "wanted"
    vid = conn.execute(
        "INSERT INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) "
        "VALUES ('ug', '1', ?, 'guitar', 'tabs', 'u', 'now')", (s.id,)
    ).lastrowid
    conn.execute(
        "INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) "
        "VALUES (?, ?, 'tab.txt', 'a/b/tab.txt', 'x', 1, 'now')", (vid, s.id)
    )
    assert refresh_status(conn, s.id, ignored=False) == "wanted"
    conn.execute(
        "INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) "
        "VALUES (?, ?, 'sheet (auto).txt', 'a/b/sheet (auto).txt', 'y', 1, 'now')", (vid, s.id)
    )
    assert refresh_status(conn, s.id, ignored=False) == "found"
    assert get_song(conn, s.id).status == "found"
    assert refresh_status(conn, s.id, ignored=True) == "ignored"
