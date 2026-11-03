"""peer_sync.py: a library cut into units, each unit's digest, two libraries compared, three ways once they synced,
and each unit taken from the other (FORMAT 2: the peer's names as written, its folders, whole or not at all)."""

import json
import os
import sqlite3
from pathlib import PurePosixPath

import httpx
import pytest
from conftest import add_song
from helpers.peer_libraries import Library, rich

from caracole import index_transfer
from caracole import peer_sync as sync
from caracole.db import kv_get, kv_set, kv_set_json
from caracole.library import keep_file, song_dir
from caracole.overrides import add_block, add_version, load_overrides
from caracole.songbook import Songbook, SongbookSong
from caracole.songs import find_song, mark_removed, removed_song
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


def test_every_database_has_an_id_and_a_copy_can_be_given_another(conn):
    made = sync.own_id(conn)
    assert made and sync.make_id(conn) == made == kv_get(conn, sync.ID_KEY)  # schema 15 made it
    kv_set_json(conn, sync.BASE_KEY + "peer", {"format": sync.FORMAT, "units": {"song/a": ["1", NOW]}})
    assert sync.base_of(conn, "peer") == {"song/a": ("1", NOW)}
    other = sync.new_id(conn)
    assert other != made and sync.own_id(conn) == other and sync.base_of(conn, "peer") is None


def test_the_later_agreement_of_the_two_sides_is_the_base():
    mine = {"song/a": ("1", "2026-10-30T00:00:00Z"), "song/b": ("1", "2026-10-31T00:00:00Z")}
    theirs = {"song/a": ("2", "2026-10-31T00:00:00Z"), "song/b": ("3", "2026-10-29T00:00:00Z"),
              "song/c": (None, "2026-10-29T00:00:00Z")}
    assert sync.merged_base(mine, theirs) == {"song/a": "2", "song/b": "1", "song/c": None}
    assert sync.merged_base(None, None) is None and sync.merged_base(None, {}) == {}


def test_a_unit_one_side_pushed_to_the_other_is_synced_whichever_side_pulled():
    # Here changed a song and there took it: there's agreement is the later. Then there changes it again.
    base = sync.merged_base({"song/a": ("old", "2026-10-01T00:00:00Z")}, {"song/a": ("new", "2026-10-02T00:00:00Z")})
    found = sync.compare({"song/a": u("song/a", "new")}, {"song/a": u("song/a", "newer")}, base)
    assert by_id(found) == {"song/a": sync.THEIRS}


def test_an_agreement_keeps_what_the_two_hold_the_same_and_what_both_lack(conn):
    kv_set_json(conn, sync.BASE_KEY + "p", {"format": 2, "units": {"song/gone": ["x", "2026-10-01T00:00:00Z"],
                                                                   "song/differs": ["y", "2026-10-01T00:00:00Z"]}})
    mine = {"song/same": u("song/same", "1"), "song/differs": u("song/differs", "2")}
    theirs = {"song/same": u("song/same", "1"), "song/differs": u("song/differs", "3")}
    assert sync.record_agreement(conn, "p", mine, theirs, NOW) == 1
    assert sync.base_of(conn, "p") == {"song/same": ("1", NOW), "song/gone": (None, NOW),
                                       "song/differs": ("y", "2026-10-01T00:00:00Z")}


def test_a_conflict_is_settled_as_chosen_else_as_preferred_else_left():
    found = [sync.Difference("song/a", "A", None, None, sync.MINE, ""),
             sync.Difference("song/b", "B", None, None, sync.THEIRS, ""),
             sync.Difference("song/c", "C", None, None, sync.CONFLICT, ""),
             sync.Difference("song/d", "D", None, None, sync.CONFLICT, "")]
    here, there = sync.decide(found)
    assert [d.id for d in here] == ["song/b"] and [d.id for d in there] == ["song/a"]
    here, there = sync.decide(found, sync.THEIRS, lambda d: sync.MINE if d.id == "song/c" else None)
    assert [d.id for d in here] == ["song/b", "song/d"] and [d.id for d in there] == ["song/a", "song/c"]


def test_the_state_document_reads_back_as_it_was_written():
    found = {"song/a": sync.Unit("song/a", "A - B", "d1")}
    doc = sync.state_document(None, "0.1.0", "Tabs", found, {"song/a": ("d1", NOW)}, now=NOW,
                              indexes={"ug": "2026-10-30T03:30:00Z"})
    assert doc["format"] == 2 and doc["now"] == NOW and doc["indexes"] == {"ug": "2026-10-30T03:30:00Z"}
    state = sync.read_state_document(json.loads(json.dumps(doc)))
    assert (state.server, state.version, state.name, state.units, state.base, state.now, state.indexes) == (
        None, "0.1.0", "Tabs", found, {"song/a": ("d1", NOW)}, NOW, {"ug": "2026-10-30T03:30:00Z"})
    # What a reader doesn't know it ignores: a later caracole's cooldowns, an index it never heard of.
    later = {**doc, "cooldowns": {"ug": NOW}, "indexes": {"ug": "2026-10-30T03:30:00Z", "x": 5}}
    assert sync.read_state_document(later).indexes == {"ug": "2026-10-30T03:30:00Z"}  # a stamp, or not read
    assert sync.read_state_document(later).units == found
    for broken in ({}, {"format": 1, "units": {}}, {"format": 2, "server": "", "units": {}},
                   {"format": 2, "units": {"no-slash": {"label": "x", "digest": "y"}}},
                   {"format": 2, "units": {"song/a": {"label": "x"}}}):
        with pytest.raises(sync.StateError):
            sync.read_state_document(broken)


def test_the_state_says_when_it_was_made_by_this_sides_clock():
    doc = sync.state_document("abc", "0.1.0", "Tabs", {})
    assert sync.read_state_document(doc).now == doc["now"]
    assert len(doc["now"]) == 20 and doc["now"].endswith("Z") and doc["indexes"] == {}


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


def read(address, transport):
    with sync.Peer(address, transport=transport) as peer:
        return peer.state("me")


def test_the_peer_is_asked_once_and_what_it_answers_otherwise_is_said():
    asked = []

    def answer(status, body):
        def handler(request):
            asked.append(str(request.url))
            return httpx.Response(status, **body)
        return httpx.MockTransport(handler)

    doc = sync.state_document("abc", "0.1.0", "Phone", {"song/a": sync.Unit("song/a", "A - B", "d")})
    assert read("http://phone:8737", answer(200, {"json": doc})).server == "abc"
    assert asked == ["http://phone:8737/api/peer/state?peer=me"]
    with pytest.raises(sync.PeerError, match="not as a caracole that syncs"):
        read("http://phone:8737", answer(404, {"text": "nope"}))
    with pytest.raises(sync.PeerError, match="answered 503: overrides.toml can't be read"):
        read("http://phone:8737", answer(503, {"json": {"error": "overrides.toml can't be read"}}))
    with pytest.raises(sync.PeerError, match="not a caracole sync state"):
        read("http://phone:8737", answer(200, {"json": {"format": 99}}))

    def refused(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(sync.PeerError, match="Nothing answered at http://phone:8737"):
        read("http://phone:8737", httpx.MockTransport(refused))


# --- FORMAT 2 --------------------------------------------------------------------------------------------------


def test_a_stored_base_is_tagged_with_its_format_and_an_untagged_one_reads_as_none(conn):
    mine, theirs = {"song/a": u("song/a", "1")}, {"song/a": u("song/a", "1")}
    assert sync.record_agreement(conn, "p", mine, theirs, NOW) == 1
    assert kv_get(conn, sync.BASE_KEY + "p") == '{"format": 2, "units": {"song/a": ["1", "%s"]}}' % NOW
    assert sync.base_of(conn, "p") == {"song/a": ("1", NOW)}
    # A FORMAT 1 base, untagged, is no base: the next sync compares as a first one (no translation).
    for stored in ({"song/a": ["1", NOW]}, {"format": 1, "units": {"song/a": ["1", NOW]}}, ["song/a"], "x"):
        kv_set_json(conn, sync.BASE_KEY + "old", stored)
        assert sync.base_of(conn, "old") is None
    assert sync.record_agreement(conn, "old", {}, {"song/b": u("song/b", "2")}, NOW) == 0
    assert sync.base_of(conn, "old") == {}


def test_a_versions_raw_and_the_lyrics_are_hashed_as_canonical_json(tmp_path):
    from caracole import canonical

    one, two = Library(tmp_path / "one"), Library(tmp_path / "two")
    for lib, raw, lyrics in ((one, '{"rating": 4.50, "b": [1, 2]}', '{"plain": "la", "synced": null}'),
                             (two, '{"b":[1,2],"rating":4.5}', '{\n "synced": null,\n "plain": "la"\n}')):
        song = lib.song("Radiohead", "Creep", lyrics=None)
        lib.conn.execute("UPDATE versions SET raw = ?", (raw,))
        lib.conn.execute("UPDATE songs SET lyrics_json = ? WHERE id = ?", (lyrics, song.id))
    assert one.digests() == two.digests()
    value = sync.unit_value(one.conn, one.overrides(), one.books(), "song/radiohead/creep")
    assert value["versions"][0]["raw"] == canonical.stored_hash('{"rating": 4.50, "b": [1, 2]}')
    assert value["lyrics"][1] == canonical.stored_hash('{"plain": "la", "synced": null}')


# --- a unit's value, from the library and from its document alone ------------------------------------------------


@pytest.fixture
def libraries(tmp_path):
    made = []

    def make(name):
        lib = Library(tmp_path / name)
        made.append(lib)
        return lib

    yield make
    for lib in made:
        lib.close()


def test_a_units_value_read_from_its_document_alone_is_the_value_its_digest_is_of(libraries):
    full, plain = libraries("full"), libraries("plain")
    rich(full)
    plain.song("Soda Stereo", "De Música Ligera", sheet=None, lyrics=None)
    plain.removed("Oasis", "Wonderwall")
    kinds = set()
    for lib in (full, plain):
        units = lib.units()
        for unit_id, unit in units.items():
            kinds.add(unit.kind)
            value = sync.unit_value(lib.conn, lib.overrides(), lib.books(), unit_id)
            doc = lib.document(unit_id)
            assert doc["digest"] == unit.digest == sync.digest_of(value), unit_id
            assert sync.value_of_document(unit_id, doc["unit"]) == value, unit_id
    assert kinds == {"song", "removed", "songbook", "alias", "artist_url", "block"}
    assert sync.value_of_document("song/x/y", None) is None
    with pytest.raises(sync.UnitError):
        sync.value_of_document("song/x/y", {"names": {}})
    with pytest.raises(sync.UnitError):
        sync.value_of_document("nonsense/x", {})


# --- taking units ------------------------------------------------------------------------------------------------


def test_a_take_writes_the_peers_names_as_written_and_both_sides_then_agree(libraries):
    here, there = libraries("here"), libraries("there")
    mine = here.song("radiohead", "creep", sheet=b"[Am]Creep")
    theirs = there.song("Radiohead", "Creep", sheet=b"[Am]Creep")
    assert mine.key == theirs.key and here.digests() != there.digests()
    done = here.take(there, [f"song/{mine.key}"])
    assert done.taken == [f"song/{mine.key}"] and done.left == []
    song = find_song(here.conn, mine.key)
    assert (song.artist, song.title, song.artists) == ("Radiohead", "Creep", ["Radiohead"])
    assert here.digests() == there.digests()
    assert (here.cfg.library_dir / "Radiohead" / "Creep" / "sheet.txt").read_bytes() == b"[Am]Creep"
    assert {p.name for p in here.cfg.library_dir.iterdir() if p.is_dir()} == {"Radiohead"}
    assert "Radiohead - Creep" in here.cfg.wanted_file.read_text(encoding="utf-8")


def test_a_take_whose_artist_differs_in_case_alone_respells_every_song_of_theirs_in_one_folder(libraries):
    here, there = libraries("here"), libraries("there")
    karma = here.song("radiohead", "Karma Police", sheet=b"[Em]Karma")
    surprises = here.song("radiohead", "No Surprises", sheet=b"[F]No alarms")
    kv_set(here.conn, f"render:{karma.id}", '{"pdf": "sheet.pdf"}')
    creep = there.song("Radiohead", "Creep")
    done = here.take(there, [f"song/{creep.key}"])
    assert done.left == [] and done.respelled == [f"song/{karma.key}", f"song/{surprises.key}"]
    for key in (karma.key, surprises.key, creep.key):
        song = find_song(here.conn, key)
        assert song.artist == "Radiohead" and song.artists == ["Radiohead"]
        for (path,) in here.conn.execute("SELECT path FROM files WHERE song_id = ?", (song.id,)):
            assert PurePosixPath(path).parts[0] == "Radiohead" and (here.cfg.library_dir / path).is_file()
    folders = [p.name for p in here.cfg.library_dir.iterdir() if p.is_dir()]
    assert [f.casefold() for f in folders] == ["radiohead"] and folders == ["Radiohead"]
    assert kv_get(here.conn, f"render:{karma.id}") is None  # rendered again, under its name as now written
    assert {karma.id, surprises.id} <= done.songs
    assert not list(here.cfg.library_dir.glob(".*"))  # no temporary name left


def test_a_song_whose_folder_changes_moves_its_files_and_their_paths_with_it(libraries):
    here, there = libraries("here"), libraries("there")
    mine = here.song("Soda Stereo", "De Musica Ligera", files={"tab.txt": b"e|--3--|"})
    kv_set(here.conn, f"render:files:{mine.id}", '{"sheet.html": {"sha256": "x", "size": 1}}')
    old = song_dir(here.cfg.library_dir, mine)
    (old / "notes.txt").write_text("mine, not caracole's")
    theirs = there.song("Soda Stereo", "De Música Ligera", files={"tab.txt": b"e|--3--|"})
    assert mine.key == theirs.key
    done = here.take(there, [f"song/{mine.key}"])
    assert done.left == []
    new = here.cfg.library_dir / "Soda Stereo" / "De Música Ligera"
    assert sorted(p.name for p in new.iterdir()) == ["lyrics.txt", "sheet.txt", "tab.txt"]
    assert sorted(p.name for p in old.iterdir()) == ["notes.txt"]  # what caracole didn't write stays
    paths = [p for (p,) in here.conn.execute("SELECT path FROM files ORDER BY path")]
    assert paths == ["Soda Stereo/De Música Ligera/sheet.txt", "Soda Stereo/De Música Ligera/tab.txt"]
    assert kv_get(here.conn, f"render:files:{mine.id}") is None
    assert here.digests() == there.digests()


def test_a_move_that_fails_halfway_leaves_the_song_whole_in_its_folder(libraries, monkeypatch):
    here, there = libraries("here"), libraries("there")
    mine = here.song("Soda Stereo", "De Musica Ligera", files={"tab.txt": b"e|--3--|"})
    before = here.digests()
    old = song_dir(here.cfg.library_dir, mine)
    there.song("Soda Stereo", "De Música Ligera", sheet=b"[G]other", files={"tab.txt": b"e|--5--|"})
    real, calls = os.rename, []

    def rename(src, dst, *args, **kwargs):
        calls.append(src)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr("caracole.peer_sync.os.rename", rename)
    done = here.take(there, [f"song/{mine.key}"])
    monkeypatch.undo()
    assert done.taken == [] and [unit for unit, _ in done.left] == [f"song/{mine.key}"]
    assert "No space left" in done.left[0][1]
    assert here.digests() == before
    assert (old / "sheet.txt").read_bytes() == b"[Am]Creep" and (old / "tab.txt").read_bytes() == b"e|--3--|"
    assert not (here.cfg.library_dir / "Soda Stereo" / "De Música Ligera").exists()
    assert not [p for p in old.iterdir() if p.name.startswith(".")]


def test_overrides_that_cant_be_written_leave_the_song_and_its_artists_folder_as_they_were(libraries):
    here, there = libraries("here"), libraries("there")
    karma = here.song("radiohead", "Karma Police")
    before, wanted = here.digests(), here.cfg.wanted_file.read_bytes()
    creep = there.song("Radiohead", "Creep", entries={"version": "key=Gm&capo=0"})
    here.cfg.overrides_file.write_text("[version\n", encoding="utf-8")  # a device's edit that broke it
    done = here.take(there, [f"song/{creep.key}"])
    assert done.taken == [] and done.respelled == []
    here.cfg.overrides_file.unlink()
    assert here.digests() == before and find_song(here.conn, creep.key) is None
    assert find_song(here.conn, karma.key).artist == "radiohead"
    assert [p.name for p in here.cfg.library_dir.iterdir() if p.is_dir()] == ["radiohead"]
    assert here.cfg.wanted_file.read_bytes() == wanted


def test_a_unit_changed_on_either_side_since_the_comparison_is_left(libraries):
    here, there = libraries("here"), libraries("there")
    mine = here.song("Radiohead", "Creep", sheet=b"[Am]mine")
    theirs = there.song("Radiohead", "Creep", sheet=b"[G]theirs")
    unit = f"song/{mine.key}"
    compared_here, compared_there = here.digests()[unit], there.digests()[unit]
    here.conn.execute("UPDATE songs SET review = 1 WHERE id = ?", (mine.id,))  # changed here since
    done = sync.apply_units(here.conn, here.cfg, there.source(), [(unit, compared_there)], NOW,
                            expected_here={unit: compared_here})
    assert done.left == [(unit, sync.CHANGED_HERE)] and find_song(here.conn, mine.key).review
    there.conn.execute("UPDATE songs SET review = 1 WHERE id = ?", (theirs.id,))  # and there
    done = sync.apply_units(here.conn, here.cfg, there.source(), [(unit, compared_there)], NOW,
                            expected_here={unit: here.digests()[unit]})
    assert done.left == [(unit, sync.CHANGED_THERE)]
    done = sync.apply_units(here.conn, here.cfg, there.source(), [(unit, there.digests()[unit])], NOW,
                            expected_here={unit: here.digests()[unit]})
    assert done.taken == [unit] and here.digests() == there.digests()


def test_a_unit_the_database_refuses_is_left_and_the_others_taken(libraries):
    here, there = libraries("here"), libraries("there")
    creep, karma = there.song("Radiohead", "Creep"), there.song("Radiohead", "Karma Police")

    class Broken:
        def __init__(self, source):
            self.source = source

        def unit(self, unit_id):
            doc = self.source.unit(unit_id)
            if unit_id == f"song/{creep.key}":
                doc["versions"][0]["slot"] = "nonsense"  # the schema's CHECK refuses it
            return doc

        def file(self, *args):
            return self.source.file(*args)

    wanted = [(f"song/{creep.key}", None), (f"song/{karma.key}", there.digests()[f"song/{karma.key}"])]
    doc = Broken(there.source()).unit(f"song/{creep.key}")
    wanted[0] = (wanted[0][0], sync.digest_of(sync.value_of_document(wanted[0][0], doc)))
    done = sync.apply_units(here.conn, here.cfg, Broken(there.source()), wanted, NOW)
    assert done.taken == [f"song/{karma.key}"]
    assert [u for u, _ in done.left] == [f"song/{creep.key}"] and "CHECK" in done.left[0][1]
    assert find_song(here.conn, creep.key) is None
    assert isinstance(sqlite3.IntegrityError("x"), sqlite3.DatabaseError)


def test_a_song_taken_forgets_the_tombstone_this_side_had_of_it(libraries):
    here, there = libraries("here"), libraries("there")
    gone = here.removed("Radiohead", "Creep")
    assert removed_song(here.conn, gone.key) is not None
    there.song("Radiohead", "Creep")
    done = here.take(there, [f"song/{gone.key}", f"removed/{gone.key}"])
    assert done.left == [] and removed_song(here.conn, gone.key) is None
    assert find_song(here.conn, gone.key) is not None and here.digests() == there.digests()


def test_a_kept_file_whose_name_no_folder_holds_is_refused(libraries):
    here, there = libraries("here"), libraries("there")
    creep = there.song("Radiohead", "Creep")
    for name in ("../x", "a/b", "a\\b", ".hidden", "", ".."):
        doc = there.source().unit(f"song/{creep.key}")
        doc["versions"][0]["files"][0]["name"] = name

        class One:
            def unit(self, unit_id, doc=doc):
                return doc

            def file(self, *args):
                raise AssertionError("nothing is asked for")

        digest = sync.digest_of(sync.value_of_document(f"song/{creep.key}", doc))
        done = sync.apply_units(here.conn, here.cfg, One(), [(f"song/{creep.key}", digest)], NOW)
        assert done.taken == [] and "no song's folder holds" in done.left[0][1], name
        with pytest.raises(sync.UnitError):
            sync.checked_name(name)
    assert sync.checked_name("sheet (auto).txt") == "sheet (auto).txt"


def test_every_unit_of_a_full_library_taken_into_an_empty_one_gives_the_same_units(libraries):
    here, there = libraries("here"), libraries("there")
    rich(there)
    done = here.take(there, list(there.units()))
    assert done.left == []
    assert here.units() == there.units()
    assert load_overrides(here.cfg.overrides_file).version == load_overrides(there.cfg.overrides_file).version


def test_the_comparisons_hash_is_of_each_differences_id_proposal_and_two_digests_in_order():
    found = sync.compare({"song/b": u("song/b", "1"), "song/a": u("song/a", "2")}, {"song/a": u("song/a", "3")}, None)
    text = json.dumps([["song/a", "conflict", "2", "3"], ["song/b", "mine", "1", None]], separators=(",", ":"))
    import hashlib

    assert sync.compared_hash(found) == hashlib.sha256(text.encode()).hexdigest()
    assert sync.compared_hash(list(reversed(found))) == sync.compared_hash(found)
    assert sync.compared_hash([]) == hashlib.sha256(b"[]").hexdigest()


def test_the_state_document_names_the_newest_read_of_each_sites_index(conn):
    assert index_transfer.newest(conn) == {}
    kv_set(conn, "ug:index:refreshed_at", "2026-10-30T03:30:00Z")
    doc = sync.state_document("abc", "0.1.0", "Tabs", {}, indexes=index_transfer.newest(conn))
    assert doc["indexes"] == {"ug": "2026-10-30T03:30:00Z"}
