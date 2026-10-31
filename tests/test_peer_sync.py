"""sync.py: a library cut into units, each unit's digest, and two libraries compared, three ways once they synced."""

import httpx
import pytest
from conftest import add_song

from caracole import peer_sync as sync
from caracole.db import kv_get, kv_set, kv_set_json
from caracole.library import keep_file
from caracole.overrides import add_block, add_version, load_overrides
from caracole.songbook import Songbook, SongbookSong
from caracole.songs import mark_removed
from caracole.versions import upsert_version
from caracole.viewer.version import Setting

NOW = "2026-10-31T00:00:00Z"


def units(conn, overrides=None, books=()):
    from caracole.overrides import Overrides

    return sync.library_state(conn, overrides or Overrides(), books)


def a_kept_song(conn, lib, artist="Radiohead", title="Creep", sheet=b"[Am]Creep"):
    song = add_song(conn, artist, title)
    vid = upsert_version(conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url="https://u/101", raw={}, now=NOW)
    keep_file(conn, lib, song=song, version_id=vid, name="sheet.txt", data=sheet, rank=1)
    return song


def test_a_library_is_its_songs_removals_songbooks_and_the_entries_about_artists_and_tabs(tmp_path, conn):
    song = add_song(conn, "Radiohead", "Creep")
    gone = add_song(conn, "Oasis", "Wonderwall")
    mark_removed(conn, gone, NOW)
    conn.execute("DELETE FROM songs WHERE id = ?", (gone.id,))
    path = tmp_path / "overrides.toml"
    add_block(path, 4242)
    books = [Songbook("Campfire", ("Radiohead - Creep",))]
    found = units(conn, load_overrides(path), books)
    assert sorted(found) == sorted([f"song/{song.key}", f"removed/{gone.key}", "songbook/campfire", "block/4242"])
    assert found[f"song/{song.key}"].label == "Radiohead - Creep"
    assert found["songbook/campfire"].label == "the songbook Campfire"
    assert found[f"removed/{gone.key}"].label == "Oasis - Wonderwall (removed)"


def test_a_songs_digest_moves_with_its_chords_its_kept_files_and_its_own_version_and_nothing_else(tmp_path, conn):
    lib = tmp_path / "lib"
    song = a_kept_song(conn, lib)
    unit = f"song/{song.key}"
    before = units(conn)[unit].digest
    assert units(conn)[unit].digest == before  # the same library, the same digest

    # What caracole makes of it, and what a lookup would find again, are no part of it.
    kv_set(conn, f"render:files:{song.id}", '{"sheet.html": {"sha256": "x", "size": 1}}')
    conn.execute("UPDATE songs SET ug_checked_at = ?, lacuerda_checked_at = ? WHERE id = ?", (NOW, NOW, song.id))
    assert units(conn)[unit].digest == before

    # Make this my version: an overrides.toml entry about the song.
    path = tmp_path / "overrides.toml"
    add_version(path, "Radiohead - Creep", "key=Gm&capo=0")
    mine = units(conn, load_overrides(path))[unit].digest
    assert mine != before

    # Another sheet kept: its file's hash.
    keep_file(conn, lib, song=song, version_id=conn.execute("SELECT id FROM versions").fetchone()[0],
              name="sheet.txt", data=b"[G]Creep", rank=1)
    assert units(conn, load_overrides(path))[unit].digest != mine


def test_a_songbooks_digest_is_its_songs_in_order_with_their_settings():
    one = sync.songbook_value(Songbook("Campfire", ("A - B", "C - D")))
    assert sync.digest_of(one) != sync.digest_of(sync.songbook_value(Songbook("Campfire", ("C - D", "A - B"))))
    set_ = Songbook("Campfire", (SongbookSong("A - B", Setting(key="G", capo=2)), "C - D"))
    assert sync.songbook_value(set_)["songs"][0] == ["A - B", {"key": "G", "capo": 2}]


def u(unit_id, digest):
    return sync.Unit(unit_id, unit_id.partition("/")[2], digest)


def by_id(found):
    return {d.id: d.proposal for d in found}


def test_never_synced_a_unit_on_one_side_alone_is_that_sides_and_one_on_both_that_differs_a_conflict():
    mine = {"song/a": u("song/a", "1"), "song/b": u("song/b", "2"), "song/same": u("song/same", "3")}
    theirs = {"song/c": u("song/c", "4"), "song/b": u("song/b", "5"), "song/same": u("song/same", "3")}
    assert by_id(sync.compare(mine, theirs, None)) == {"song/a": sync.MINE, "song/b": sync.CONFLICT,
                                                       "song/c": sync.THEIRS}


def test_once_synced_a_unit_one_side_changed_is_that_sides_and_one_both_changed_differently_a_conflict():
    base = {"song/kept": "0", "song/here": "0", "song/there": "0", "song/both": "0", "song/same": "0",
            "song/gone-here": "0"}
    mine = {"song/kept": u("song/kept", "0"), "song/here": u("song/here", "1"), "song/there": u("song/there", "0"),
            "song/both": u("song/both", "1"), "song/same": u("song/same", "9"), "song/new-here": u("song/new-here", "1")}
    theirs = {"song/kept": u("song/kept", "0"), "song/here": u("song/here", "0"),
              "song/there": u("song/there", "2"), "song/both": u("song/both", "2"), "song/same": u("song/same", "9"),
              "song/gone-here": u("song/gone-here", "0"), "song/new-there": u("song/new-there", "2")}
    found = sync.compare(mine, theirs, base)
    assert by_id(found) == {"song/here": sync.MINE, "song/there": sync.THEIRS, "song/both": sync.CONFLICT,
                            "song/new-here": sync.MINE, "song/new-there": sync.THEIRS, "song/gone-here": sync.MINE}
    why = {d.id: d.why for d in found}
    assert why["song/gone-here"] == "gone here since the last sync"
    assert why["song/new-there"] == "new there since the last sync"
    assert why["song/there"] == "changed there since the last sync"


def test_the_differences_come_songs_first_by_their_label():
    mine = {"songbook/x": sync.Unit("songbook/x", "the songbook X", "1"),
            "song/b": sync.Unit("song/b", "Beta - Song", "1"), "song/a": sync.Unit("song/a", "alpha - Song", "1")}
    assert [d.id for d in sync.compare(mine, {}, None)] == ["song/a", "song/b", "songbook/x"]


def test_the_id_is_made_once_and_only_when_asked(conn):
    assert sync.own_id(conn) is None
    made = sync.make_id(conn)
    assert sync.own_id(conn) == made == sync.make_id(conn) == kv_get(conn, sync.ID_KEY)
    assert sync.base_of(conn, "peer") is None
    kv_set_json(conn, sync.BASE_KEY + "peer", {"song/a": "1"})
    assert sync.base_of(conn, "peer") == {"song/a": "1"}


def test_the_state_document_reads_back_as_it_was_written():
    found = {"song/a": sync.Unit("song/a", "A - B", "d1")}
    doc = sync.state_document(None, "0.1.0", "Tabs", found)
    assert sync.read_state_document(doc) == (None, "0.1.0", "Tabs", found)
    for broken in ({}, {"format": 2, "units": {}}, {"format": 1, "server": "", "units": {}},
                   {"format": 1, "units": {"no-slash": {"label": "x", "digest": "y"}}},
                   {"format": 1, "units": {"song/a": {"label": "x"}}}):
        with pytest.raises(sync.StateError):
            sync.read_state_document(broken)


@pytest.mark.parametrize(("typed", "address"), [
    ("192.168.1.20:8737", "http://192.168.1.20:8737"),
    ("http://phone.lan:8737/", "http://phone.lan:8737"),
    ("https://[fd7a:115c::1]:8737", "https://[fd7a:115c::1]:8737"),
])
def test_an_address_typed_is_asked_as_http_with_no_trailing_slash(typed, address):
    assert sync.peer_address(typed) == address


@pytest.mark.parametrize("typed", ["ftp://phone", "http://", "phone:port", "http://phone/?q=1"])
def test_an_address_that_isnt_a_caracole_serves_is_refused(typed):
    with pytest.raises(sync.PeerError):
        sync.peer_address(typed)


def test_the_peer_is_asked_once_and_what_it_answers_otherwise_is_said():
    asked = []

    def answer(status, body):
        def handler(request):
            asked.append(str(request.url))
            return httpx.Response(status, **body)
        return httpx.MockTransport(handler)

    doc = sync.state_document("abc", "0.1.0", "Phone", {"song/a": sync.Unit("song/a", "A - B", "d")})
    assert sync.read_peer("http://phone:8737", transport=answer(200, {"json": doc}))[0] == "abc"
    assert asked == ["http://phone:8737/api/peer/state"]
    with pytest.raises(sync.PeerError, match="not as a caracole that syncs"):
        sync.read_peer("http://phone:8737", transport=answer(404, {"text": "nope"}))
    with pytest.raises(sync.PeerError, match="answered 503: overrides.toml can't be read"):
        sync.read_peer("http://phone:8737", transport=answer(503, {"json": {"error": "overrides.toml can't be read"}}))
    with pytest.raises(sync.PeerError, match="not a caracole sync state"):
        sync.read_peer("http://phone:8737", transport=answer(200, {"json": {"format": 99}}))

    def refused(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(sync.PeerError, match="Nothing answered at http://phone:8737"):
        sync.read_peer("http://phone:8737", transport=httpx.MockTransport(refused))
