import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from caracole import db
from caracole.library import keep_file, kept_files
from caracole.normalize import KEY_VERSION
from caracole.songs import (
    KEY_VERSION_KV,
    ensure_current_keys,
    find_song,
    get_song,
    list_songs,
    refresh_status,
    update_song,
    upsert_song,
)
from caracole.versions import get_version, set_picks, song_versions, upsert_version

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
    key = "soda-stereo/de-musica-ligera"
    a = upsert_song(conn, artists=["Soda Stereo"], title="De Música Ligera", album=None, duration_ms=213000,
                    isrc=None, source="wanted", source_id=key, added_at="2026-01-01T00:00:00Z")
    b = upsert_song(conn, artists=["Soda Stereo"], title="De Música Ligera", album="Canción Animal",
                    duration_ms=213000, isrc=None, source="wanted", source_id=key,
                    added_at="2026-02-01T00:00:00Z")
    assert a == (1, True)
    assert b == (1, False)
    s = get_song(conn, 1)
    assert s.album == "Canción Animal"
    assert s.duration_ms == 213000
    assert s.isrc is None
    assert s.source_ids == {"wanted": [key]}
    assert s.added_at.startswith("2026-02")
    assert s.key == "soda-stereo/de-musica-ligera"
    assert s.status == "wanted" and s.ug_dirty and s.lyrics_status == "pending"


def test_remaster_merges_with_original(conn):
    # A line for the remaster, then one for the original: one song, as its first line wrote it.
    key = "the-beatles/let-it-be"
    upsert_song(conn, artists=["The Beatles"], title="Let It Be - Remastered 2009", album=None,
                duration_ms=243000, isrc=None, source="wanted", source_id=key, added_at="2026-01-01T00:00:00Z")
    _, created = upsert_song(conn, artists=["The Beatles"], title="Let It Be", album=None, duration_ms=None,
                             isrc=None, source="wanted", source_id=key, added_at="2026-01-03T00:00:00Z")
    assert not created
    rows = list_songs(conn)
    assert len(rows) == 1
    assert rows[0].source_ids == {"wanted": [key]}
    assert rows[0].title == "Let It Be - Remastered 2009"
    assert rows[0].display == "The Beatles - Let It Be"


def test_a_title_written_with_or_without_its_comma_is_one_song(conn):
    upsert_song(conn, artists=["宋冬野"], title="斑马，斑马", album=None, duration_ms=253000, isrc=None,
                source="wanted", source_id="宋冬野/斑马斑马", added_at="2026-01-01T00:00:00Z")
    _, created = upsert_song(conn, artists=["宋冬野"], title="斑马斑马", album="安和桥北", duration_ms=253000,
                             isrc=None, source="wanted", source_id="宋冬野/斑马斑马",
                             added_at="2026-01-03T00:00:00Z")
    assert not created
    s = list_songs(conn)[0]
    assert s.source_ids == {"wanted": ["宋冬野/斑马斑马"]}
    assert s.album == "安和桥北"


def test_variant_kept_from_source_title(conn):
    s = add_song(conn, "Radiohead", "Creep - Acoustic")
    assert s.variant == "acoustic"
    assert s.key == "radiohead/creep"


def test_a_new_song_takes_the_spelling_of_an_artist_the_library_writes_in_another_case(conn, tmp_path):
    from caracole.library import song_dir
    from caracole.normalize import identity_key

    oasis = add_song(conn, "Oasis", "Wonderwall")
    typed = add_song(conn, "oasis", "champagne supernova", artists=["oasis", "Noel Gallagher"])  # typed on a phone
    assert (typed.artist, typed.artists, typed.title) == ("Oasis", ["Oasis", "Noel Gallagher"], "champagne supernova")
    assert typed.key == identity_key("oasis", "champagne supernova")
    # One folder for the artist, which a phone's file system, blind to case, can hold.
    assert song_dir(tmp_path, typed).parent == song_dir(tmp_path, oasis).parent == tmp_path / "Oasis"
    # A name that differs in more than case is the artist as written; so is one a folder of its own has already.
    assert add_song(conn, "Oasis Tribute", "Wonderwall").artist == "Oasis Tribute"
    conn.execute("UPDATE songs SET artist = 'OASIS' WHERE id = ?", (typed.id,))  # a library from before
    assert add_song(conn, "OASIS", "Live Forever").artist == "OASIS"
    assert add_song(conn, "oAsis", "Slide Away").artist == "Oasis"  # the oldest song's spelling


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


@pytest.mark.parametrize("song_id", [2**63, -2**63 - 1, 2**70, -2**70])
def test_an_id_no_sqlite_integer_can_hold_is_no_song(conn, song_id):
    add_song(conn)
    with pytest.raises(KeyError, match="no song with id"):
        get_song(conn, song_id)


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

def older_song(conn, artist, title, key, *, source, source_id, added_at="2026-09-01T00:00:00Z"):
    """A song as an older caracole stored it: keyed by that day's normalizer, with no key version."""
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
    from caracole.wanted import sync_wanted

    song_id = older_song(conn, "Soda Stereo", "Persiana Americana - En Vivo", OLD_LIVE_KEY,
                         source="wanted", source_id=OLD_LIVE_KEY)
    sync_wanted(conn, wanted_file(tmp_path), NIGHT)
    (song,) = list_songs(conn)
    assert (song.id, song.key) == (song_id, "soda-stereo/persiana-americana")
    assert song.source_ids == {"wanted": ["soda-stereo/persiana-americana"]}
    assert db.kv_get(conn, KEY_VERSION_KV) == str(KEY_VERSION)


def test_re_keying_carries_a_wanted_lines_first_seen_time(conn, tmp_path):
    # Re-keyed before the sync reads it (on opening the database), the line keeps its place.
    from caracole.wanted import FIRST_SEEN_KEY, sync_wanted

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


def test_todays_overrides_meet_a_song_an_older_normalizer_keyed(conn):
    from caracole.overrides import override_key

    song_id = older_song(conn, "Los Enanitos Verdes", "Lamento Boliviano",
                         "los-enanitos-verdes/lamento-boliviano", source="wanted",
                         source_id="los-enanitos-verdes/lamento-boliviano")
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
    # "Los Enanitos Verdes" and "Enanitos Verdes", two lines an older normalizer kept apart: two songs until now.
    lib = tmp_path / "lib"
    older = older_song(conn, "Los Enanitos Verdes", "Lamento Boliviano",
                       "los-enanitos-verdes/lamento-boliviano", source="wanted",
                       source_id="los-enanitos-verdes/lamento-boliviano")
    key = "enanitos-verdes/lamento-boliviano"
    newer = older_song(conn, "Enanitos Verdes", "Lamento Boliviano", key, source="wanted",
                       source_id=key, added_at="2026-09-05T00:00:00Z")
    update_song(conn, newer, album="Igual Que Ayer", duration_ms=223000)
    # Both were fetched to the same sheet; the newer one also has a text tab.
    sheet = keep(conn, lib, older, "101", "chords", "sheet.txt", b"older's sheet", pick=True)
    keep(conn, lib, newer, "101", "chords", "sheet.txt", b"newer's sheet", pick=True)
    keep(conn, lib, newer, "401", "tabs", "tab.txt", b"tab", pick=True)
    update_song(conn, older, ug_dirty=False)
    refresh_status(conn, older, ignored=False)

    assert ensure_current_keys(conn) == 2

    (song,) = list_songs(conn)
    # The older record stays, with the first source's display artist.
    assert (song.id, song.key, song.artist) == (older, key, "Los Enanitos Verdes")
    assert song.source_ids == {"wanted": [key]}
    assert (song.added_at, song.album, song.duration_ms) == (
        "2026-09-05T00:00:00Z", "Igual Que Ayer", 223000)
    assert song.ug_dirty and song.status == "found"  # the next fetch weighs what it gained
    kept = {f.name: f for f in kept_files(conn, older)}
    assert set(kept) == {"sheet.txt", "tab.txt"} and kept["sheet.txt"].version_id == sheet
    tab = get_version(conn, kept["tab.txt"].version_id)
    assert (tab.tab_id, tab.song_id, tab.pick_rank) == ("401", older, None)  # its picks stand
    assert sorted(v.tab_id for v in song_versions(conn, older)) == ["101", "401"]
    assert all((lib / f.path).is_file() for f in kept.values())


def test_a_merged_songs_own_state_goes_with_it(conn):
    # SQLite hands the next new song the id of the newest row once that row is gone.
    older_song(conn, "Los Enanitos Verdes", "Lamento Boliviano",
               "los-enanitos-verdes/lamento-boliviano", source="wanted",
               source_id="los-enanitos-verdes/lamento-boliviano")
    newer = older_song(conn, "Enanitos Verdes", "Lamento Boliviano",
                       "enanitos-verdes/lamento-boliviano", source="wanted",
                       source_id="enanitos-verdes/lamento-boliviano")
    own = [f"render:{newer}", f"render:{newer}:auto", f"render:files:{newer}", f"ug:artist_page_checked:{newer}",
           f"autochords:failed:{newer}", f"gtptabs:checked:{newer}", f"ug:blocked:{newer}", f"youtube:{newer}"]
    for key in own + [f"render:{newer}0", f"youtube:{newer}0", "render:status"]:
        db.kv_set(conn, key, '"2026-10-18T03:30:00Z"')
    ensure_current_keys(conn)
    fresh = add_song(conn, "Soda Stereo", "Signos")
    assert fresh.id == newer
    assert [db.kv_get(conn, key) for key in own] == [None] * len(own)
    # Another song's, and no song's, stay.
    assert db.kv_get(conn, f"render:{newer}0") and db.kv_get(conn, f"youtube:{newer}0")
    assert db.kv_get(conn, "render:status")


def test_keys_that_change_hands_are_re_keyed_without_a_clash(conn):
    # One song's new key is another's old one: keys are unique, so neither may wait for the other.
    moving = older_song(conn, "Soda Stereo", "Persiana Americana - En Vivo", OLD_LIVE_KEY,
                        source="wanted", source_id=OLD_LIVE_KEY)
    holder = older_song(conn, "Soda Stereo", "Signos", "soda-stereo/persiana-americana",
                        source="wanted", source_id="soda-stereo/persiana-americana")
    ensure_current_keys(conn)
    assert get_song(conn, moving).key == "soda-stereo/persiana-americana"
    assert get_song(conn, holder).key == "soda-stereo/signos"


def test_keys_are_re_keyed_once_per_normalizer_version(conn):
    add_song(conn, "Soda Stereo", "Signos")
    assert db.kv_get(conn, KEY_VERSION_KV) == str(KEY_VERSION)
    conn.execute("UPDATE songs SET key = 'stale/key'")  # keys of this version aren't read again
    assert ensure_current_keys(conn) == 0
    assert [s.key for s in list_songs(conn)] == ["stale/key"]


# --- album, duration, ISRC and variant: what the line says now -----------------------------

LINE = "radiohead/creep"  # a wanted.txt line's source id is its identity key


def line(conn, title="Creep", *, album=None, duration_ms=None):
    """Radiohead's Creep as its wanted.txt line hands it over (sync_wanted)."""
    return upsert_song(conn, artists=["Radiohead"], title=title, album=album,
                       duration_ms=duration_ms, isrc=None, source="wanted", source_id=LINE,
                       added_at="2026-10-01T00:00:00Z")


def fields(conn):
    (song,) = list_songs(conn)
    return song.album, song.duration_ms, song.isrc, song.variant


def test_a_corrected_wanted_line_replaces_what_it_said(conn):
    # "| 3:13" written for a song of 3:58: the sync after the fix stores the line's new values.
    line(conn, album="Pablo Honey (Deluxe)", duration_ms=193000)
    line(conn, album="Pablo Honey", duration_ms=238000)
    assert fields(conn) == ("Pablo Honey", 238000, None, None)


def test_what_comes_off_a_wanted_line_comes_off_the_song(conn):
    line(conn, "Creep - Acoustic", album="Pablo Honey", duration_ms=193000)
    line(conn)
    assert fields(conn) == (None, None, None, None)


def test_a_value_stored_before_goes_when_the_only_source_no_longer_gives_it(conn):
    only = older_song(conn, "Radiohead", "Creep", LINE, source="wanted", source_id=LINE)
    update_song(conn, only, album="Pablo Honey", duration_ms=193000)
    line(conn)
    assert (get_song(conn, only).album, get_song(conn, only).duration_ms) == (None, None)


def test_a_line_saying_the_same_again_writes_nothing(conn):
    # Every sync hands every song over again; one nothing changed for is left as it is.
    song_id, _ = line(conn, album="Pablo Honey", duration_ms=238000)
    before = conn.total_changes
    assert line(conn, album="Pablo Honey", duration_ms=238000) == (song_id, False)
    assert conn.total_changes == before
    line(conn, album="Pablo Honey (Deluxe)", duration_ms=238000)  # the line's album edited
    assert conn.total_changes > before
    assert fields(conn) == ("Pablo Honey (Deluxe)", 238000, None, None)


def test_a_song_keeps_what_its_line_says_in_its_own_record_alone(conn):
    # The record is the line's word: nothing beside it in kv to read back or to tidy up after a removal.
    line(conn, "Creep - Acoustic", album="Pablo Honey", duration_ms=193000)
    assert fields(conn) == ("Pablo Honey", 193000, None, "acoustic")
    assert conn.execute("SELECT key FROM kv WHERE key LIKE 'songs:fields:%'").fetchall() == []


def test_a_second_sync_of_an_unchanged_wanted_txt_writes_nothing(conn, tmp_path):
    from caracole.wanted import sync_wanted

    path = tmp_path / "wanted.txt"
    path.write_text("Radiohead - Creep | Pablo Honey | 3:58\nSoda Stereo - Signos\n", encoding="utf-8")
    sync_wanted(conn, path, datetime(2026, 10, 18, tzinfo=UTC))
    before = conn.total_changes
    stats = sync_wanted(conn, path, datetime(2026, 10, 19, tzinfo=UTC))
    assert (stats.seen, stats.new) == (2, 0)
    assert conn.total_changes == before


# --- removed songs (caracole remove) ------------------------------------------------------------

REMOVED_AT = "2026-10-10T00:00:00Z"


def removed(conn, song):
    """The song as removal.py leaves it: a tombstone, and no record."""
    from caracole.songs import mark_removed

    mark_removed(conn, song, REMOVED_AT)
    conn.execute("DELETE FROM songs WHERE id = ?", (song.id,))


def test_a_wanted_line_brings_a_removed_song_back_as_new(conn):
    from caracole.songs import removed_song

    line(conn, album="Pablo Honey")
    (song,) = list_songs(conn)
    removed(conn, song)
    song_id, created = line(conn)
    assert created and removed_song(conn, "radiohead/creep") is None
    assert get_song(conn, song_id).album is None  # new: what it had went with it


def test_a_song_of_the_same_key_in_the_library_outranks_a_tombstone(conn):
    # After a re-keying, a removed song may share its key with one you have.
    from caracole.songs import mark_removed, removed_song

    kept_id, _ = line(conn)
    mark_removed(conn, get_song(conn, kept_id), REMOVED_AT)
    assert line(conn) == (kept_id, False)
    assert removed_song(conn, LINE) is not None  # the line found its song: no tombstone was asked about


def test_removed_songs_are_listed_newest_first_and_merge_their_sources(conn):
    from caracole.songs import list_removed, mark_removed

    creep = add_song(conn, "Radiohead", "Creep", source_id="radiohead/creep-live")
    mark_removed(conn, creep, "2026-10-01T00:00:00Z")
    signos = add_song(conn, "Soda Stereo", "Signos")
    mark_removed(conn, signos, "2026-10-05T00:00:00Z")
    # A song removed under a key that has a tombstone already (two songs re-keyed into one, say).
    mark_removed(conn, replace(creep, source_ids={"wanted": ["radiohead/creep"]}), "2026-10-03T00:00:00Z")
    assert [(r.display, r.removed_at) for r in list_removed(conn)] == [
        ("Soda Stereo - Signos", "2026-10-05T00:00:00Z"), ("Radiohead - Creep", "2026-10-03T00:00:00Z")]
    assert list_removed(conn)[1].source_ids == {"wanted": ["radiohead/creep-live", "radiohead/creep"]}


def test_removed_songs_are_re_keyed_with_the_songs(conn):
    from caracole.songs import removed_song

    conn.execute(
        "INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?)",
        (OLD_LIVE_KEY, "Soda Stereo", "Persiana Americana - En Vivo", json.dumps({"wanted": [OLD_LIVE_KEY]}),
         REMOVED_AT),
    )
    db.kv_delete(conn, KEY_VERSION_KV)
    ensure_current_keys(conn)
    assert removed_song(conn, OLD_LIVE_KEY) is None
    stone = removed_song(conn, "soda-stereo/persiana-americana")
    assert stone.source_ids == {"wanted": ["soda-stereo/persiana-americana"]}
    # A line for it, under today's normalizer, asks for it again: it comes back new.
    _, created = upsert_song(conn, artists=["Soda Stereo"], title="Persiana Americana", album=None, duration_ms=None,
                             isrc=None, source="wanted", source_id="soda-stereo/persiana-americana",
                             added_at="2026-10-11T00:00:00Z")
    assert created and removed_song(conn, "soda-stereo/persiana-americana") is None
