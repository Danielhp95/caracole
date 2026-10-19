import json
import sqlite3
from datetime import UTC, datetime

import pytest

from tabarr import db
from tabarr.library import keep_file, kept_files
from tabarr.normalize import KEY_VERSION
from tabarr.songs import (
    KEY_VERSION_KV,
    ensure_current_keys,
    find_song,
    get_song,
    list_songs,
    refresh_status,
    update_song,
    upsert_song,
)
from tabarr.versions import get_version, set_picks, song_versions, upsert_version

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


# --- one record per song, whatever the normalizer ------------------------------------------

SPOTIFY = {"album": None, "duration_ms": None, "isrc": None, "source": "spotify",
           "added_at": "2026-10-01T00:00:00Z"}


def test_a_retitled_track_is_still_its_song(conn):
    # Spotify retitles a track: its id still names the song it was, under the key it had.
    first, _ = upsert_song(conn, artists=["Soda Stereo"], title="Persiana Americana",
                           source_id="3Zr1nVDLLMxKdDKfbmyhqa", **SPOTIFY)
    again = upsert_song(conn, artists=["Soda Stereo"], title="Persiana Americana (Ensayo)",
                        source_id="3Zr1nVDLLMxKdDKfbmyhqa", **SPOTIFY)
    assert again == (first, False)
    (song,) = list_songs(conn)
    assert (song.key, song.source_ids) == (
        "soda-stereo/persiana-americana", {"spotify": ["3Zr1nVDLLMxKdDKfbmyhqa"]})


def older_song(conn, artist, title, key, *, source, source_id, added_at="2026-09-01T00:00:00Z"):
    """A song as an older tabarr stored it: keyed by that day's normalizer, with no key version."""
    cur = conn.execute(
        "INSERT INTO songs (key, artist, title, artists, source_ids, added_at, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (key, artist, title, json.dumps([artist]), json.dumps({source: [source_id]}), added_at,
         added_at, added_at),
    )
    db.kv_delete(conn, KEY_VERSION_KV)
    return cur.lastrowid


OLD_LIVE_KEY = "soda-stereo/persiana-americana-en-vivo"  # before " - En Vivo" was a version suffix
NIGHT = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)


def wanted_file(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_text("Soda Stereo - Persiana Americana - En Vivo\n", encoding="utf-8")
    return path


def test_a_wanted_song_keyed_by_an_older_normalizer_is_re_keyed_not_split(conn, tmp_path):
    # Its source id is its key, so a new normalizer gives the same line a new source id too.
    from tabarr.wanted import sync_wanted

    song_id = older_song(conn, "Soda Stereo", "Persiana Americana - En Vivo", OLD_LIVE_KEY,
                         source="wanted", source_id=OLD_LIVE_KEY)
    sync_wanted(conn, wanted_file(tmp_path), NIGHT)
    (song,) = list_songs(conn)
    assert (song.id, song.key) == (song_id, "soda-stereo/persiana-americana")
    assert song.source_ids == {"wanted": ["soda-stereo/persiana-americana"]}
    assert db.kv_get(conn, KEY_VERSION_KV) == str(KEY_VERSION)


def test_re_keying_carries_a_wanted_lines_first_seen_time(conn, tmp_path):
    # Re-keyed before the sync reads it (on opening the database), the line keeps its place.
    from tabarr.wanted import FIRST_SEEN_KEY, sync_wanted

    older_song(conn, "Soda Stereo", "Persiana Americana - En Vivo", OLD_LIVE_KEY,
               source="wanted", source_id=OLD_LIVE_KEY)
    db.kv_set(conn, FIRST_SEEN_KEY + OLD_LIVE_KEY, "2026-09-01T00:00:00Z")
    assert ensure_current_keys(conn) == 1
    new_key = "soda-stereo/persiana-americana"
    assert db.kv_get(conn, FIRST_SEEN_KEY + new_key) == "2026-09-01T00:00:00Z"
    assert db.kv_get(conn, FIRST_SEEN_KEY + OLD_LIVE_KEY) is None
    sync_wanted(conn, wanted_file(tmp_path), NIGHT)
    (song,) = list_songs(conn)
    assert song.added_at == "2026-09-01T00:00:00Z"


def test_a_spotify_song_keyed_by_an_older_normalizer_is_re_keyed_not_split(conn):
    song_id = older_song(conn, "Soda Stereo", "Persiana Americana - En Vivo", OLD_LIVE_KEY,
                         source="spotify", source_id="sp1")
    again = upsert_song(conn, artists=["Soda Stereo"], title="Persiana Americana - En Vivo",
                        source_id="sp1", **SPOTIFY)
    assert again == (song_id, False)
    assert [s.key for s in list_songs(conn)] == ["soda-stereo/persiana-americana"]


def test_todays_overrides_meet_a_song_an_older_normalizer_keyed(conn):
    from tabarr.overrides import override_key

    song_id = older_song(conn, "Los Enanitos Verdes", "Lamento Boliviano",
                         "los-enanitos-verdes/lamento-boliviano", source="spotify", source_id="sp9")
    song = find_song(conn, override_key("Enanitos Verdes - Lamento Boliviano"))
    assert song is not None and song.id == song_id


def keep(conn, lib, song_id, tab_id, kind, name, data, *, pick):
    slot = "sheet" if kind == "chords" else "guitar"
    vid = upsert_version(conn, provider="ug", tab_id=tab_id, song_id=song_id, slot=slot, kind=kind,
                         rating=4.5, votes=10, version=1, label=None, url=f"https://u/{tab_id}",
                         raw={}, now="2026-09-02T00:00:00Z")
    keep_file(conn, lib, song=get_song(conn, song_id), version_id=vid, name=name, data=data, rank=1)
    if pick:
        set_picks(conn, song_id, (kind,), [vid])
    return vid


def test_songs_an_older_normalizer_kept_apart_are_merged(conn, tmp_path):
    # Spotify's "Los Enanitos Verdes" and wanted.txt's "Enanitos Verdes": two songs until now.
    lib = tmp_path / "lib"
    older = older_song(conn, "Los Enanitos Verdes", "Lamento Boliviano",
                       "los-enanitos-verdes/lamento-boliviano", source="spotify", source_id="sp9")
    key = "enanitos-verdes/lamento-boliviano"
    newer = older_song(conn, "Enanitos Verdes", "Lamento Boliviano", key, source="wanted",
                       source_id=key, added_at="2026-09-05T00:00:00Z")
    update_song(conn, newer, album="Igual Que Ayer", duration_ms=223000)
    # Both were fetched to the same sheet; the newer one also has a Guitar Pro file you filed.
    sheet = keep(conn, lib, older, "101", "chords", "sheet.txt", b"older's sheet", pick=True)
    keep(conn, lib, newer, "101", "chords", "sheet.txt", b"newer's sheet", pick=True)
    keep(conn, lib, newer, "301", "guitar-pro", "guitar-1.gp5", b"gp5", pick=True)
    update_song(conn, older, ug_dirty=False)
    refresh_status(conn, older, ignored=False)

    assert ensure_current_keys(conn) == 2

    (song,) = list_songs(conn)
    # The older record stays, with the first source's display artist.
    assert (song.id, song.key, song.artist) == (older, key, "Los Enanitos Verdes")
    assert song.source_ids == {"spotify": ["sp9"], "wanted": [key]}
    assert (song.added_at, song.album, song.duration_ms) == (
        "2026-09-05T00:00:00Z", "Igual Que Ayer", 223000)
    assert song.ug_dirty and song.status == "found"  # the next fetch weighs what it gained
    kept = {f.name: f for f in kept_files(conn, older)}
    assert set(kept) == {"sheet.txt", "guitar-1.gp5"} and kept["sheet.txt"].version_id == sheet
    gp = get_version(conn, kept["guitar-1.gp5"].version_id)
    assert (gp.tab_id, gp.song_id, gp.pick_rank) == ("301", older, None)  # its picks stand
    assert sorted(v.tab_id for v in song_versions(conn, older)) == ["101", "301"]
    assert all((lib / f.path).is_file() for f in kept.values())


def test_a_merged_songs_own_state_goes_with_it(conn):
    # SQLite hands the next new song the id of the newest row once that row is gone.
    older_song(conn, "Los Enanitos Verdes", "Lamento Boliviano",
               "los-enanitos-verdes/lamento-boliviano", source="spotify", source_id="sp9")
    newer = older_song(conn, "Enanitos Verdes", "Lamento Boliviano",
                       "enanitos-verdes/lamento-boliviano", source="wanted", source_id="x")
    own = [f"render:{newer}", f"ug:artist_page_checked:{newer}", f"autochords:failed:{newer}"]
    for key in own:
        db.kv_set(conn, key, '"2026-10-18T03:30:00Z"')
    ensure_current_keys(conn)
    fresh = add_song(conn, "Soda Stereo", "Signos")
    assert fresh.id == newer
    assert [db.kv_get(conn, key) for key in own] == [None, None, None]


def test_keys_that_change_hands_are_re_keyed_without_a_clash(conn):
    # One song's new key is another's old one: keys are unique, so neither may wait for the other.
    moving = older_song(conn, "Soda Stereo", "Persiana Americana - En Vivo", OLD_LIVE_KEY,
                        source="spotify", source_id="sp1")
    holder = older_song(conn, "Soda Stereo", "Signos", "soda-stereo/persiana-americana",
                        source="spotify", source_id="sp2")
    ensure_current_keys(conn)
    assert get_song(conn, moving).key == "soda-stereo/persiana-americana"
    assert get_song(conn, holder).key == "soda-stereo/signos"


def test_keys_are_re_keyed_once_per_normalizer_version(conn):
    add_song(conn, "Soda Stereo", "Signos")
    assert db.kv_get(conn, KEY_VERSION_KV) == str(KEY_VERSION)
    conn.execute("UPDATE songs SET key = 'stale/key'")  # keys of this version aren't read again
    assert ensure_current_keys(conn) == 0
    assert [s.key for s in list_songs(conn)] == ["stale/key"]
