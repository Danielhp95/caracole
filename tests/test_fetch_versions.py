"""The fetch keeps the runners-up of a song's sheet beside it: ``version-<tab>.txt`` and ``.json``.

They are the versions it scores for lyric coverage anyway (``RankPolicy.scored_sheets``), so keeping
them costs no request; a fake Ultimate Guitar behind a real ``PoliteClient`` counts them (test_fetch.py's).
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest

from test_fetch import BROKEN, LINES, LYRICS, NOW, FakeUG, accepted, context, index, read, sheet, slugged, v

from caracole.config import RankPolicy
from caracole.library import kept_files, song_dir
from caracole.overrides import Overrides
from caracole.sheet_versions import in_library, kept_by_you
from caracole.songs import get_song, update_song
from caracole.ug.fetch import fetch_songs, keep_version, process_song, rescore_kept_sheets, songs_to_fetch
from caracole.ug.page import PageParseError, strip_markup
from caracole.versions import get_version, mark_gone, song_versions

PERSIANA = ("soda-stereo", "persiana-americana")


def four_chords(conn, ug, *, same=None):
    """Four complete chords versions, best rated first: 101 (4.9), 102 (4.7), 103 (4.5), 104 (4.0).

    ``same`` gives two tabs one text: (101, 102) serves 102 with 101's very sheet."""
    index(conn, *[(t, *PERSIANA, "chords") for t in (101, 102, 103, 104)])
    tabs = {t: v(t, version=t - 100, rating=r, votes=100) for t, r in ((101, 4.9), (102, 4.7), (103, 4.5), (104, 4.0))}
    for t, tab in tabs.items():
        tag = same[0] if same and t == same[1] else t
        ug.tab(tab, [o for o in tabs.values() if o is not tab], content=sheet(f"sheet {tag}", LINES))


def version_files(conn, song):
    """The song's kept version files, by name: their kept_rank and the tab their version is."""
    return {f.name: (f.kept_rank, get_version(conn, f.version_id).tab_id)
            for f in kept_files(conn, song.id) if f.name.startswith("version-")}


def fetch(conn, ug, tmp_path, song, overrides=None, *, now=NOW):
    ug.requests.clear()
    client = ug.client(tmp_path / "cache", now=now)
    return process_song(context(conn, client, tmp_path, overrides, now=now), get_song(conn, song.id))


def test_the_runners_up_are_kept_beside_the_sheet_with_no_request_more(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)

    out = fetch(conn, ug, tmp_path, song)

    assert ug.requests == [slugged(101), slugged(102), slugged(103)]  # as before: one rates them, three are scored
    assert out.sheet == 101 and out.kept_versions == ("102", "103")
    assert version_files(conn, song) == {
        "version-102.txt": (2, "102"), "version-102.json": (2, "102"),
        "version-103.txt": (3, "103"), "version-103.json": (3, "103"),
    }
    text = read(tmp_path, song, "version-102.txt")
    assert text == strip_markup(sheet("sheet 102", LINES))
    doc = json.loads(read(tmp_path, song, "version-102.json"))
    assert doc["url"] == slugged(102) and doc["version"]["id"] == 102 and doc["content"].startswith("[Intro]")
    assert not (song_dir(tmp_path / "lib", song) / "version-104.txt").exists()  # the 4th is listed, not kept
    listed = in_library(conn, song.id, RankPolicy())
    assert [(x.tab_id, x.kept, x.page) for x in listed] == [
        ("101", True, "sheet.html"), ("102", True, "version-102.html"), ("103", True, "version-103.html"),
        ("104", False, None)]


def test_a_fetch_again_rewrites_nothing(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)
    folder = song_dir(tmp_path / "lib", song)
    before = {p.name: p.stat().st_ino for p in folder.iterdir()}
    update_song(conn, song.id, ug_dirty=True)

    out = fetch(conn, ug, tmp_path, song)

    assert ug.requests == [] and out.kept_versions == ("102", "103")
    assert {p.name: p.stat().st_ino for p in folder.iterdir() if p.name != "info.json"} == {
        k: i for k, i in before.items() if k != "info.json"}


def test_new_votes_reorder_the_kept_set_from_the_pages_scored_that_run(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)

    # The index finds 105, whose page carries fresh ratings: 104 climbs, 103 falls.
    index(conn, (105, *PERSIANA, "chords"))
    ug.tab(v(105, version=5, rating=4.95, votes=100),
           [v(104, version=4, rating=4.8, votes=100), v(103, version=3, rating=3.0, votes=100)],
           content=sheet("sheet 105", LINES))
    update_song(conn, song.id, ug_dirty=True)

    out = fetch(conn, ug, tmp_path, song)

    assert ug.requests == [slugged(105), slugged(104)]  # the new page, and 104 scored as it would be anyway
    assert out.sheet == 105 and out.kept_versions == ("101", "104")
    assert "sheet 105" in read(tmp_path, song, "sheet.txt")
    assert version_files(conn, song) == {
        "version-101.txt": (2, "101"), "version-101.json": (2, "101"),
        "version-104.txt": (3, "104"), "version-104.json": (3, "104"),
    }
    folder = song_dir(tmp_path / "lib", song)
    assert sorted(p.name for p in folder.glob("version-*")) == [
        "version-101.json", "version-101.txt", "version-104.json", "version-104.txt"]
    assert "sheet 101" in read(tmp_path, song, "version-101.txt")


def test_a_runner_up_that_becomes_the_sheet_leaves_its_version_files(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)

    out = fetch(conn, ug, tmp_path, song, Overrides(pin={song.key: (102,)}))  # your choice: 102

    assert out.sheet == 102 and "sheet 102" in read(tmp_path, song, "sheet.txt")
    assert ug.requests == []  # the pin's page and the runners-up's from the cache
    assert out.kept_versions == ("101", "103")
    assert set(version_files(conn, song)) == {
        "version-101.txt", "version-101.json", "version-103.txt", "version-103.json"}


def test_a_pin_outside_the_top_three_keeps_them_beside_it_from_the_cache_alone(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)

    out = fetch(conn, ug, tmp_path, song, Overrides(pin={song.key: (104,)}))

    assert ug.requests == [slugged(104)]  # the pin's page alone
    assert out.sheet == 104 and out.kept_versions == ("101", "102", "103")
    assert {n: r for n, (r, _) in version_files(conn, song).items() if n.endswith(".txt")} == {
        "version-101.txt": 2, "version-102.txt": 3, "version-103.txt": 4}

    out = fetch(conn, ug, tmp_path, song)  # the pin cleared: caracole's pick again

    assert ug.requests == [] and out.sheet == 101 and out.kept_versions == ("102", "103")
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")
    assert set(version_files(conn, song)) == {
        "version-102.txt", "version-102.json", "version-103.txt", "version-103.json"}


def test_a_version_whose_text_is_the_sheets_is_listed_as_the_sheet(conn, tmp_path):
    # Review Focus 1: two UG tabs with one text. keep_file refuses one sha256 under two names.
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug, same=(101, 102))

    out = fetch(conn, ug, tmp_path, song)

    assert out.sheet == 101 and out.kept_versions == ("103",)
    assert set(version_files(conn, song)) == {"version-103.txt", "version-103.json"}
    assert not list(song_dir(tmp_path / "lib", song).glob("version-102*"))
    listed = {x.tab_id: (x.kept, x.chosen, x.page) for x in in_library(conn, song.id, RankPolicy())}
    assert listed["102"] == (True, False, "sheet.html")
    assert listed["101"] == (True, True, "sheet.html")


def test_a_version_listed_as_the_same_as_one_leaving_the_set_is_kept_in_its_place(conn, tmp_path):
    # Two UG tabs with one text: 102 holds it, 103 is listed as 102's. When 102 leaves the top
    # three and 103 stays, 103 takes the text: 102's files go before 103 is kept, not after.
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug, same=(102, 103))
    out = fetch(conn, ug, tmp_path, song)
    assert out.kept_versions == ("102",)

    # The index finds 105, whose page carries fresh ratings: 102 falls out of the top three.
    index(conn, (105, *PERSIANA, "chords"))
    ug.tab(v(105, version=5, rating=4.95, votes=100), [v(102, version=2, rating=3.0, votes=100)],
           content=sheet("sheet 105", LINES))
    update_song(conn, song.id, ug_dirty=True)

    out = fetch(conn, ug, tmp_path, song)

    assert ug.requests == [slugged(105)]
    assert out.sheet == 105 and out.kept_versions == ("101", "103")
    assert set(version_files(conn, song)) == {
        "version-101.txt", "version-101.json", "version-103.txt", "version-103.json"}
    assert "sheet 102" in read(tmp_path, song, "version-103.txt")
    assert not list(song_dir(tmp_path / "lib", song).glob("version-102*"))
    listed = {x.tab_id: (x.kept, x.page) for x in in_library(conn, song.id, RankPolicy())}
    assert listed["103"] == (True, "version-103.html")
    assert listed["102"] == (False, None)


def test_a_gone_version_keeps_its_files_until_the_next_fetch_drops_it(conn, tmp_path):
    # Review Focus 5.
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)
    [row] = [r for r in song_versions(conn, song.id) if r.tab_id == "103"]
    mark_gone(conn, row.id)

    listed = {x.tab_id: (x.gone, x.kept, x.page) for x in in_library(conn, song.id, RankPolicy())}
    assert listed["103"] == (True, True, "version-103.html")
    assert (song_dir(tmp_path / "lib", song) / "version-103.txt").exists()

    update_song(conn, song.id, ug_dirty=True)
    ug.tab(v(104, version=4, rating=4.0, votes=100),  # UG lists it no more
           [v(101, version=1, rating=4.9, votes=100), v(102, version=2, rating=4.7, votes=100)],
           content=sheet("sheet 104", LINES))
    out = fetch(conn, ug, tmp_path, song)

    assert ug.requests == [slugged(104)]  # scored in 103's place
    assert out.kept_versions == ("102", "104")
    assert not list(song_dir(tmp_path / "lib", song).glob("version-103*"))
    listed = {x.tab_id: (x.gone, x.kept, x.page) for x in in_library(conn, song.id, RankPolicy())}
    assert listed["103"] == (True, False, None)


def test_a_version_page_that_wont_parse_is_not_kept_and_is_no_miss(conn, tmp_path):
    song = accepted(conn)
    index(conn, *[(t, *PERSIANA, "chords") for t in (101, 102, 103)])
    ug = FakeUG()
    tabs = {t: v(t, version=t - 100, rating=r, votes=100) for t, r in ((101, 4.9), (102, 4.7), (103, 4.5))}
    for t in (101, 102):
        ug.tab(tabs[t], [o for o in tabs.values() if o is not tabs[t]], content=sheet(f"sheet {t}", LINES))
    ug.add(slugged(103), BROKEN)

    for day in (0, 1):  # the first bad answer may be a passing fault; the second time it is unreadable
        when = NOW + timedelta(days=day)
        fetch_songs(context(conn, ug.client(tmp_path / "cache", now=when), tmp_path, now=when),
                    songs_to_fetch(conn, Overrides(), when))

    assert "sheet 101" in read(tmp_path, song, "sheet.txt")
    assert set(version_files(conn, song)) == {"version-102.txt", "version-102.json"}
    done = get_song(conn, song.id)
    assert (done.ug_dirty, done.ug_checked_at) == (True, None)  # waits to read 103: never a miss
    assert [r.tab_id for r in song_versions(conn, song.id)] == ["101", "102", "103"]


def test_a_kept_version_whose_page_cant_be_read_now_keeps_its_files(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)
    key = hashlib.sha256(slugged(103).encode()).hexdigest()
    (tmp_path / "cache" / "http" / "ug" / key[:2] / f"{key}.body").unlink()  # its cached page lost
    ug.add(slugged(103), BROKEN)  # and UG serves no sheet there now
    with pytest.raises(PageParseError):  # the first bad answer may be a passing fault
        fetch(conn, ug, tmp_path, song)

    out = fetch(conn, ug, tmp_path, song)  # unreadable again: 104 is scored in its place

    assert ug.requests == [slugged(103), slugged(104)]
    assert out.kept_versions == ("102", "104")
    assert set(version_files(conn, song)) == {
        "version-102.txt", "version-102.json", "version-103.txt", "version-103.json",
        "version-104.txt", "version-104.json"}  # 103's stay: an error is never a miss


def test_a_blocked_version_leaves_its_files(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)
    update_song(conn, song.id, ug_dirty=False, ug_checked_at=NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    block = Overrides(block=frozenset({103}))
    assert [s.id for s in songs_to_fetch(conn, block, NOW)] == [song.id]  # a kept version blocked: sent back

    out = fetch(conn, ug, tmp_path, song, block)

    assert out.kept_versions == ("102", "104")
    assert set(version_files(conn, song)) == {
        "version-102.txt", "version-102.json", "version-104.txt", "version-104.json"}


def test_a_lost_version_file_sends_its_song_back_and_is_written_again(conn, tmp_path, cfg):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)
    update_song(conn, song.id, ug_dirty=False)
    lost = song_dir(tmp_path / "lib", song) / "version-103.txt"
    kept = lost.read_bytes()
    lost.unlink()

    rescore_kept_sheets(conn, tmp_path / "lib", RankPolicy())
    assert get_song(conn, song.id).ug_dirty is True
    fetch(conn, ug, tmp_path, song)

    assert ug.requests == [] and lost.read_bytes() == kept


def test_a_song_whose_sheet_is_another_sites_keeps_its_ug_versions_beside_it(conn, tmp_path):
    from caracole.library import keep_file
    from caracole.versions import set_coverage, set_picks, upsert_version

    song = accepted(conn)
    theirs = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/persiana_americana", song_id=song.id,
                            slot="sheet", kind="acordes", rating=0, votes=0, version=1, label=None,
                            url="https://acordes.lacuerda.net/soda_stereo/persiana_americana.shtml", raw={},
                            now="2026-10-17T00:00:00Z")
    set_coverage(conn, theirs, 1.0)
    keep_file(conn, tmp_path / "lib", song=song, version_id=theirs, name="sheet.txt", data=b"lacuerda's", rank=1)
    set_picks(conn, song.id, ("acordes",), [theirs])
    ug = FakeUG()
    four_chords(conn, ug)

    out = fetch(conn, ug, tmp_path, song)

    assert out.sheet is None and read(tmp_path, song, "sheet.txt") == "lacuerda's"
    assert out.kept_versions == ("101", "102", "103")
    listed = in_library(conn, song.id, RankPolicy())
    assert [(x.tab_id, x.chosen, x.page) for x in listed][:3] == [
        ("101", False, "version-101.html"), ("102", False, "version-102.html"), ("103", False, "version-103.html")]


def test_versions_kept_before_the_song_had_lyrics_are_scored_without_a_request(conn, tmp_path):
    song = accepted(conn, plain=None)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)
    assert {r.tab_id: r.coverage for r in song_versions(conn, song.id)}["102"] is None
    from test_fetch import lyrics_json

    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics_json(LYRICS))

    rescore_kept_sheets(conn, tmp_path / "lib", RankPolicy())

    coverage = {r.tab_id: r.coverage for r in song_versions(conn, song.id)}
    assert coverage["101"] == 1.0 and coverage["102"] == 1.0 and coverage["103"] == 1.0
    assert coverage["104"] is None


def keep(conn, ug, tmp_path, song, tab):
    """``caracole versions --keep``'s fetch: one version kept now."""
    ug.requests.clear()
    return keep_version(context(conn, ug.client(tmp_path / "cache"), tmp_path), get_song(conn, song.id), tab)


def test_keeping_the_sheets_own_tab_notes_nothing_as_yours(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)

    assert keep(conn, ug, tmp_path, song, 101) == "sheet"
    assert kept_by_you(conn, song.id) == ()  # a later pick of another sheet doesn't keep it beside that one


def test_a_version_whose_text_is_the_tabs_is_not_kept_and_leaves_no_file(conn, tmp_path):
    # The library keeps one text under one name: tab.txt holds it, and no viewer page shows a tab.
    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    index(conn, (401, *PERSIANA, "tabs"))
    ug.tab(v(401, "tabs", rating=4.8, votes=40), content=sheet("sheet 104", LINES))
    out = fetch(conn, ug, tmp_path, song)
    assert out.tab == 401 and "sheet 104" in read(tmp_path, song, "tab.txt")

    assert keep(conn, ug, tmp_path, song, 104) == "held"

    assert ug.requests == [slugged(104)]
    assert not list(song_dir(tmp_path / "lib", song).glob("version-104*"))
    assert "version-104.json" not in version_files(conn, song)
    assert kept_by_you(conn, song.id) == ()
    listed = {x.tab_id: (x.kept, x.page) for x in in_library(conn, song.id, RankPolicy())}
    assert listed["104"] == (False, None)


def test_a_version_whose_page_redirects_where_robots_txt_closes_is_closed_never_textless(conn, tmp_path):
    # RobotsClosed is no failure and no miss: the keep says so, and nothing notes the version as one it can't keep.
    from test_fetch import CLOSED

    song = accepted(conn)
    ug = FakeUG()
    four_chords(conn, ug)
    fetch(conn, ug, tmp_path, song)
    ug.redirect(slugged(104), CLOSED)

    assert keep(conn, ug, tmp_path, song, 104) == "closed"
    assert CLOSED not in ug.requests
    assert not list(song_dir(tmp_path / "lib", song).glob("version-104*"))
