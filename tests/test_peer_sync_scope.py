"""peer_sync.py: a sync's three parts (library, songbooks, site indexes), the songs a songbook lists, which brings them
along, a part a file doesn't hold never read as a removal, each side's change since the base, and a song's names."""

from caracole import normalize
from caracole import peer_sync as sync


def D(i, mine="m", theirs="t", proposal=sync.CONFLICT):
    return sync.Difference(i, i, mine and sync.Unit(i, i, mine), theirs and sync.Unit(i, i, theirs), proposal, "")


SONG, OTHER, BOOK = "song/eagles/hotel california", "song/pomme/mononoke", "songbook/campfire"


def test_each_unit_kind_is_of_one_part_and_the_indexes_hold_none():
    assert sync.PARTS == ("library", "songbooks", "indexes")
    assert [sync.part_of(i) for i in (SONG, "removed/x/y", "alias/x", "artist_url/x", "block/7", BOOK)] == [
        "library"] * 5 + ["songbooks"]
    assert [sync.part_of(i) for i in ("other/x", "indexes/ug", "song", "")] == [None] * 4


def test_library_alone_keeps_songs_removals_and_overrides_and_no_songbook():
    found = [D(SONG), D("removed/x/y"), D("alias/x"), D("block/7"), D(BOOK)]
    assert [d.id for d in sync.in_scope(found, ["library"])] == [SONG, "removed/x/y", "alias/x", "block/7"]


def test_songbooks_alone_bring_the_songs_they_list_and_no_other():
    found = [D(SONG), D(OTHER), D(BOOK)]
    kept = sync.in_scope(found, ["songbooks"], listed={SONG: [BOOK]})
    assert [d.id for d in kept] == [SONG, BOOK]


def test_a_sync_of_the_songbooks_brings_a_listed_song_along_and_never_removes_one():
    a, b, c, d, e, f = (f"song/x/{n}" for n in "abcdef")
    found = [D(a, "m", None, sync.MINE),  # new here: given
             D(b, None, "t", sync.THEIRS),  # new there: taken
             D(c, "m", None, sync.THEIRS),  # gone there since: its removal not taken
             D(d, None, "t", sync.MINE),  # gone here since: its removal not given
             D(e, None, "t", sync.CONFLICT),  # gone here, changed there: left
             D(f, "m", "t", sync.CONFLICT)]  # changed on both: asked
    listed = {u: [BOOK] for u in (a, b, c, d, e, f)}
    assert [x.id for x in sync.in_scope(found, ["songbooks"], listed=listed)] == [a, b, f]
    assert [x.id for x in sync.in_scope(found, ["songbooks", "library"], listed=listed)] == [a, b, c, d, e, f]


def test_a_songbook_lists_no_removal_or_override_into_the_songbooks_part():
    found = [D("removed/x/y"), D("alias/x"), D(BOOK)]
    assert [d.id for d in sync.in_scope(found, ["songbooks"], listed={"removed/x/y": [BOOK]})] == [BOOK]


def test_every_part_keeps_every_known_unit_in_its_order_and_none_keeps_nothing():
    found = [D(BOOK), D(SONG), D("other/x"), D("artist_url/x")]
    assert [d.id for d in sync.in_scope(found, sync.PARTS)] == [BOOK, SONG, "artist_url/x"]
    assert sync.in_scope(found, []) == [] and sync.in_scope(found, ["indexes"]) == []


def test_a_file_that_holds_no_library_never_reads_a_song_it_lacks_as_removed():
    found = [D(SONG, theirs=None), D(OTHER), D(BOOK)]
    kept = sync.in_scope(found, ["songbooks"], listed={SONG: [BOOK], OTHER: [BOOK]}, holds=["songbooks"])
    assert [d.id for d in kept] == [OTHER, BOOK]


def test_a_file_that_holds_a_part_may_remove_what_it_lacks_of_it():
    found = [D(SONG, theirs=None), D(BOOK, theirs=None)]
    assert [d.id for d in sync.in_scope(found, sync.PARTS, holds=["library"])] == [SONG]
    assert [d.id for d in sync.in_scope(found, sync.PARTS, holds=["songbooks"])] == [BOOK]
    assert sync.in_scope(found, sync.PARTS, holds=["indexes"]) == []


def test_a_songbooks_entry_lists_a_song_by_any_cut_of_its_name():
    key = normalize.identity_key("Earth - Wind", "Fire")
    books = {BOOK: {"name": "Campfire", "songs": [["Earth - Wind - Fire", {}]]}}
    assert sync.listed_songs(books, [f"song/{key}", OTHER]) == {f"song/{key}": [BOOK]}


def test_a_song_two_songbooks_list_maps_to_both_once_each():
    key = normalize.identity_key("Eagles", "Hotel California")
    books = {"songbook/z": {"name": "Z", "songs": [["Eagles - Hotel California", {"capo": 2}],
                                                   ["eagles - hotel california", {}]]},
             BOOK: {"name": "Campfire", "songs": [["Eagles - Hotel California", {}], ["Nobody - Here", {}]]}}
    assert sync.listed_songs(books, {f"song/{key}"}) == {f"song/{key}": [BOOK, "songbook/z"]}


def test_a_songbook_that_cant_be_read_lists_nothing():
    key = normalize.identity_key("Eagles", "Hotel California")
    books = {BOOK: {"name": "x", "songs": "Eagles - Hotel California"}, "songbook/b": None,
             "songbook/c": {"songs": [["Eagles - Hotel California"], [7, {}], "Eagles - Hotel California"]}}
    assert sync.listed_songs(books, [f"song/{key}"]) == {}


def test_each_sides_change_is_new_changed_or_gone():
    assert sync.change_of(D(SONG, "m", None), {SONG: None}) == ("new", None)
    assert sync.change_of(D(SONG, None, "t"), {SONG: "m"}) == ("gone", "changed")
    assert sync.change_of(D(SONG, "m", "t"), None) == ("changed", "changed")
    assert sync.change_of(D(SONG, "m", None), None) == ("new", None)
    assert sync.change_of(D(SONG, "bh2", "bt"), {}, {SONG: ("bh", "bt", "mine")}) == ("changed", None)


def test_a_unit_the_base_doesnt_name_is_new_where_it_is():
    assert sync.change_of(D(SONG, "m", "t"), {}) == ("new", "new")
    assert sync.change_of(D(SONG, None, "t"), {OTHER: "x"}) == (None, "new")
    assert sync.change_of(D(SONG, "m", "t"), {SONG: "m"}) == (None, "changed")


def test_a_songs_names_come_from_the_cut_of_its_label_that_is_its_key():
    key = normalize.identity_key("Earth - Wind", "Fire")
    assert sync.names_of(f"song/{key}", "Earth - Wind - Fire") == ("Earth - Wind", "Fire")
    assert sync.names_of(SONG, "Eagles - Hotel California") == ("Eagles", "Hotel California")
    assert sync.names_of(BOOK, "the songbook Campfire") is None


def test_a_label_no_cut_of_which_is_the_key_gives_its_first_cut_and_one_with_none_no_names():
    assert sync.names_of("song/x/y", "A - B - C") == ("A", "B - C")
    assert sync.names_of("song/x/y", "Nameless") is None
    assert sync.names_of("removed/eagles/hotel california", "Eagles - Hotel California (removed)") is None
