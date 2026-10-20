"""The versions table: a slot's picks change all at once."""

import sqlite3

import pytest

from caracole.versions import set_picks, upsert_version

from conftest import add_song


def chords(conn, song_id, tab_id):
    return upsert_version(conn, provider="ug", tab_id=tab_id, song_id=song_id, slot="sheet", kind="chords",
                          rating=4.5, votes=10, version=1, label=None, url=f"https://u/{tab_id}",
                          raw={}, now="2026-10-20T00:00:00Z")


def ranks(conn, song_id):
    return conn.execute("SELECT id, pick_rank FROM versions WHERE song_id = ? ORDER BY id", (song_id,)).fetchall()


def test_set_picks_is_all_or_nothing(conn):
    song = add_song(conn)
    first, second = chords(conn, song.id, "1"), chords(conn, song.id, "2")
    set_picks(conn, song.id, ("chords",), [first, second])
    conn.execute("CREATE TEMP TRIGGER no_first_pick BEFORE UPDATE OF pick_rank ON versions "
                 "WHEN NEW.pick_rank = 1 BEGIN SELECT RAISE(ABORT, 'no first pick'); END")

    with pytest.raises(sqlite3.IntegrityError, match="no first pick"):
        set_picks(conn, song.id, ("chords",), [second, first])  # fails after clearing the old picks

    assert [tuple(r) for r in ranks(conn, song.id)] == [(first, 1), (second, 2)]
    assert not conn.in_transaction


def test_set_picks_inside_a_callers_savepoint_is_undone_with_it(conn):
    song = add_song(conn)
    vid = chords(conn, song.id, "1")

    conn.execute("SAVEPOINT outer")
    set_picks(conn, song.id, ("chords",), [vid])
    assert conn.in_transaction  # set_picks commits nothing of its caller's
    conn.execute("ROLLBACK TO outer")
    conn.execute("RELEASE outer")

    assert [tuple(r) for r in ranks(conn, song.id)] == [(vid, None)]
