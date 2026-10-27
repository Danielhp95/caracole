"""sheet_versions.py: a song's chords versions in rank order, which are kept and which is the one."""

from caracole.config import RankPolicy
from caracole.library import keep_file
from caracole.sheet_versions import (
    as_data,
    in_library,
    library_state,
    sheet_kind,
    song_sheet_versions,
    tab_of,
    version_names,
)
from caracole.versions import mark_gone, mark_stale, set_coverage, upsert_version

from conftest import add_song

POLICY = RankPolicy()


def chords(conn, song_id, tab_id, *, rating=4.5, votes=100, version=1, coverage=None, raw=None,
           provider="ug", kind="chords"):
    vid = upsert_version(conn, provider=provider, tab_id=tab_id, song_id=song_id, slot="sheet", kind=kind,
                         rating=rating, votes=votes, version=version, label=None,
                         url=f"https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-chords-{tab_id}",
                         raw=raw or {}, now="2026-10-20T00:00:00Z")
    if coverage is not None:
        set_coverage(conn, vid, coverage)
    return vid


def tabs(versions):
    return [v.tab_id for v in versions]


def test_versions_list_in_rank_order_complete_first(conn):
    song = add_song(conn, "Oasis", "Wonderwall")
    chords(conn, song.id, "1", rating=5.0, votes=900, version=1, coverage=0.4)  # the best rating, half the lyrics
    chords(conn, song.id, "2", rating=4.6, votes=200, version=2, coverage=0.9)
    chords(conn, song.id, "3", rating=4.8, votes=300, version=3, coverage=0.95)
    chords(conn, song.id, "4", rating=4.9, votes=500, version=4)  # not scored
    chords(conn, song.id, "5", rating=4.2, votes=50, version=5)  # not scored
    chords(conn, song.id, "6", rating=4.95, votes=800, version=6, provider="lacuerda", kind="acordes")

    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=())

    assert tabs(versions) == ["3", "2", "1", "4", "5"]  # complete, then scored, then the rest by rating
    assert [v.rank for v in versions] == [1, 2, 3, 4, 5]
    assert [v.complete for v in versions] == [True, True, False, None, None]
    assert versions[0].coverage == 0.95 and versions[3].coverage is None
    assert versions[0].number == 3 and versions[0].rating == 4.8 and versions[0].votes == 300


def test_with_no_lyrics_the_rating_weighed_by_votes_decides(conn):
    song = add_song(conn, "Oasis", "Wonderwall")
    chords(conn, song.id, "1064463", rating=4.86, votes=408, version=3)
    chords(conn, song.id, "39144", rating=4.85, votes=12629, version=1)

    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=())

    assert tabs(versions) == ["1064463", "39144"]


def test_the_chosen_and_kept_pages_are_named(conn):
    song = add_song(conn, "Oasis", "Wonderwall")
    for n, tab in enumerate(("10", "20", "30", "40")):
        chords(conn, song.id, tab, rating=4.9 - n / 10, votes=100)

    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab="20", kept_tabs=["10", "30"])

    pages = {v.tab_id: v.page for v in versions}
    assert pages == {"10": "version-10.html", "20": "sheet.html", "30": "version-30.html", "40": None}
    assert [v.tab_id for v in versions if v.chosen] == ["20"]
    assert [v.tab_id for v in versions if v.kept] == ["10", "20", "30"]  # the one is kept too


def test_a_song_whose_sheet_is_another_sites_still_lists_its_ug_versions(conn):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    chords(conn, song.id, "1", rating=4.9)
    chords(conn, song.id, "2", rating=4.5)

    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=["1", "2"])

    assert not any(v.chosen for v in versions)
    assert [v.page for v in versions] == ["version-1.html", "version-2.html"]


def test_the_tabbers_note_is_folded_and_cut(conn):
    song = add_song(conn, "Oasis", "Wonderwall")
    chords(conn, song.id, "1", raw={"version_description": "the version that oasis play\n on   Wembley 2008"})
    chords(conn, song.id, "2", raw={"version_description": "x" * 300}, rating=4.0)
    chords(conn, song.id, "3", raw={"version_description": "  \n "}, rating=3.0)
    chords(conn, song.id, "4", raw={"version_description": None}, rating=2.0)

    notes = [v.note for v in song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=())]

    assert notes == ["the version that oasis play on Wembley 2008", "x" * 200, None, None]


def test_a_gone_version_lists_as_gone(conn):
    song = add_song(conn, "Oasis", "Wonderwall")
    chords(conn, song.id, "1", rating=5.0, votes=900)
    chords(conn, song.id, "2", rating=4.0, votes=100)
    mark_gone(conn, chords(conn, song.id, "3", rating=4.9, votes=900))

    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab="1", kept_tabs=["3"])

    assert tabs(versions) == ["1", "2", "3"]  # gone, after every live one
    assert [v.gone for v in versions] == [False, False, True]
    assert versions[2].kept and versions[2].page == "version-3.html"  # kept until the next fetch drops it


def test_a_version_an_earlier_match_found_is_not_listed(conn):
    song = add_song(conn, "Oasis", "Wonderwall")
    chords(conn, song.id, "1")
    mark_stale(conn, song.id, "ug")
    chords(conn, song.id, "2")

    assert tabs(song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=())) == ["2"]


def test_names_round_trip():
    assert version_names("39144") == ("version-39144.txt", "version-39144.json", "version-39144.html")
    assert tab_of(version_names("39144")[1]) == "39144"
    assert all(tab_of(name) == "7" for name in version_names("7"))
    assert tab_of("sheet.txt") is None
    assert tab_of("version-.txt") is None
    assert tab_of("version-12.pdf") is None
    assert tab_of("version-1a.txt") is None
    assert tab_of("version-12.txt.bak") is None


def test_as_data_is_the_json_the_pages_read(conn):
    song = add_song(conn, "Oasis", "Wonderwall")
    chords(conn, song.id, "1064463", rating=4.86, votes=408, version=3,
           raw={"version_description": "the version that oasis play on Wembley 2008"})
    chords(conn, song.id, "39144", rating=4.85, votes=12629, version=1)
    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab="1064463", kept_tabs=["39144"])

    data = as_data(versions, 13)

    assert data["total"] == 13
    assert data["list"][0] == {
        "tab": "1064463", "number": 3, "rating": 4.86, "votes": 408, "label": None,
        "note": "the version that oasis play on Wembley 2008", "rank": 1, "kept": True, "chosen": True,
        "gone": False, "page": "sheet.html",
        "url": "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-chords-1064463",
    }
    assert data["list"][1]["page"] == "version-39144.html"


def test_the_library_state_is_read_from_the_files_caracole_kept(conn, cfg):
    song = add_song(conn, "Oasis", "Wonderwall")
    one = chords(conn, song.id, "1", rating=5.0)
    two = chords(conn, song.id, "2", rating=4.0)
    three = chords(conn, song.id, "3", rating=4.5)
    lib = cfg.library_dir
    keep_file(conn, lib, song=song, version_id=one, name="sheet.txt", data=b"one", rank=1)
    keep_file(conn, lib, song=song, version_id=two, name="version-2.txt", data=b"two", rank=3)
    keep_file(conn, lib, song=song, version_id=two, name="version-2.json", data=b"{2}", rank=3)
    keep_file(conn, lib, song=song, version_id=three, name="version-3.txt", data=b"three", rank=2)

    assert library_state(conn, song.id) == ("1", ("3", "2"))
    versions = in_library(conn, song.id, POLICY)
    assert [(v.tab_id, v.page) for v in versions] == [("1", "sheet.html"), ("3", "version-3.html"),
                                                      ("2", "version-2.html")]


def test_a_sheet_from_another_site_is_no_chosen_ug_version(conn, cfg):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    theirs = chords(conn, song.id, "lc-1", provider="lacuerda", kind="acordes")
    chords(conn, song.id, "1")
    keep_file(conn, cfg.library_dir, song=song, version_id=theirs, name="sheet.txt", data=b"lc", rank=1)

    assert library_state(conn, song.id) == (None, ())
    assert [v.chosen for v in in_library(conn, song.id, POLICY)] == [False]


def test_a_ukulele_sheet_lists_the_ukulele_versions_alone(conn, cfg):
    # A song with no chords on UG takes its sheet from its Ukulele Chords versions (ug/fetch.py); one that had
    # once and has chords now lists those.
    song = add_song(conn, "Vance Joy", "Riptide")
    uke = chords(conn, song.id, "301", kind="ukulele", rating=4.9)
    chords(conn, song.id, "302", kind="ukulele", rating=4.5)
    chords(conn, song.id, "101", rating=4.0)
    keep_file(conn, cfg.library_dir, song=song, version_id=uke, name="sheet.txt", data=b"uke", rank=1)

    assert sheet_kind(conn, song.id) == "ukulele"
    assert library_state(conn, song.id) == ("301", ())
    assert tabs(in_library(conn, song.id, POLICY)) == ["301", "302"]
    assert tabs(song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=())) == ["101"]


def test_with_no_chords_the_ukulele_versions_are_listed(conn):
    song = add_song(conn, "Vance Joy", "Riptide")
    chords(conn, song.id, "301", kind="ukulele")

    assert tabs(song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=())) == ["301"]
    assert sheet_kind(conn, song.id) == "chords"  # no sheet kept yet


def test_may_keep_is_every_version_a_keep_may_still_keep_in_rank_order(conn):
    from caracole.sheet_versions import may_keep, note_unkeepable

    song = add_song(conn, "Oasis", "Wonderwall")
    ids = {tab: chords(conn, song.id, tab, rating=4.9 - n / 10, votes=100)
           for n, tab in enumerate(("10", "20", "30", "40", "50", "60", "70"))}
    gone = ids["50"]
    mark_gone(conn, gone)
    note_unkeepable(conn, song.id, "60")  # a keep found it had no text, or another kept file's very text
    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab="20", kept_tabs=["10"])

    left = may_keep(conn, song.id, versions, block={40})

    assert tabs(left) == ["30", "70"]  # not kept, not the one, not under [block], not gone, not unkeepable


def test_may_keep_leaves_out_a_version_robots_txt_closes(conn):
    from caracole.sheet_versions import may_keep

    song = add_song(conn, "Oasis", "Wonderwall")
    chords(conn, song.id, "10")
    vid = chords(conn, song.id, "20")
    conn.execute("UPDATE versions SET url = ? WHERE id = ?",
                 ("https://www.ultimate-guitar.com/tab-pro/download?id=20", vid))
    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=())

    assert tabs(may_keep(conn, song.id, versions, block=())) == ["10"]


def test_unkeepable_versions_are_noted_once_and_go_with_the_song(conn):
    from caracole.sheet_versions import UNKEEPABLE_KV, note_unkeepable, unkeepable
    from caracole.songs import _PER_SONG_KV

    song = add_song(conn, "Oasis", "Wonderwall")
    note_unkeepable(conn, song.id, "60")
    note_unkeepable(conn, song.id, 60)

    assert unkeepable(conn, song.id) == ("60",)
    assert UNKEEPABLE_KV in _PER_SONG_KV  # a merge or a removal deletes it


def test_in_library_of_lists_each_song_as_in_library_does(conn, cfg):
    # The library page reads every song's versions at once (in_library_of): the same lists in_library gives each,
    # the one, the kept ones, those a kept one's text, gone ones, notes and a variant's ranking among them.
    from caracole.db import kv_set_json
    from caracole.sheet_versions import in_library_of, same_key
    from caracole.songs import update_song

    lib = cfg.library_dir
    kept = add_song(conn, "Oasis", "Wonderwall")
    one = chords(conn, kept.id, "1", rating=4.9, coverage=0.9, raw={"version_description": " Capo 2\n  slowly "})
    two = chords(conn, kept.id, "2", rating=4.8, raw={"version_description": {"not": "a note"}})
    chords(conn, kept.id, "3", rating=4.7)
    mark_gone(conn, chords(conn, kept.id, "4", rating=4.95))
    keep_file(conn, lib, song=kept, version_id=one, name="sheet.txt", data=b"one", rank=1)
    keep_file(conn, lib, song=kept, version_id=two, name="version-2.txt", data=b"two", rank=2)
    kv_set_json(conn, same_key(kept.id), {"3": "version-2.html", "9": "version-9.html"})
    elsewhere = add_song(conn, "Soda Stereo", "De Música Ligera")
    theirs = chords(conn, elsewhere.id, "lc-1", provider="lacuerda", kind="acordes")
    chords(conn, elsewhere.id, "5", rating=4.1, votes=10)
    chords(conn, elsewhere.id, "6", rating=4.0, votes=900, raw={"version_description": "live"})
    keep_file(conn, lib, song=elsewhere, version_id=theirs, name="sheet.txt", data=b"lc", rank=1)
    uke = add_song(conn, "Vance Joy", "Riptide")
    chords(conn, uke.id, "301", kind="ukulele")
    stale = add_song(conn, "Radiohead", "Creep")
    chords(conn, stale.id, "7")
    mark_stale(conn, stale.id, "ug")
    acoustic = add_song(conn, "Radiohead", "Nude")
    update_song(conn, acoustic.id, variant="acoustic")
    chords(conn, acoustic.id, "8", rating=4.9, votes=500)
    chords(conn, acoustic.id, "81", rating=4.2, votes=50)
    conn.execute("UPDATE versions SET label = 'Acoustic' WHERE tab_id = '81'")
    none = add_song(conn, "Nobody", "Nothing")
    ids = [kept.id, elsewhere.id, uke.id, stale.id, acoustic.id, none.id]

    each = {song_id: listed for song_id in ids if (listed := in_library(conn, song_id, POLICY))}

    assert in_library_of(conn, ids, POLICY) == each
    assert set(each) == {kept.id, elsewhere.id, uke.id, acoustic.id}
    assert [(v.tab_id, v.kept, v.page, v.note) for v in each[kept.id]] == [
        ("1", True, "sheet.html", "Capo 2 slowly"), ("2", True, "version-2.html", None),
        ("3", True, "version-2.html", None), ("4", False, None, None)]
    assert in_library_of(conn, [], POLICY) == {}


def test_may_keep_is_nothing_when_a_keep_keeps_another_group_than_the_list_shows(conn):
    # No sheet of UG's and no live chords version: the list shows the Ukulele Chords versions, but a keep keeps
    # chords beside a sheet that isn't UG's ukulele one (ug.fetch.sheet_group), so none of them is to fetch.
    from caracole.sheet_versions import may_keep

    song = add_song(conn, "Oasis", "Wonderwall")
    chords(conn, song.id, "201", kind="ukulele")
    chords(conn, song.id, "202", kind="ukulele")
    versions = song_sheet_versions(conn, song.id, POLICY, chosen_tab=None, kept_tabs=())

    assert tabs(versions) == ["201", "202"]
    assert may_keep(conn, song.id, versions, block=()) == []
