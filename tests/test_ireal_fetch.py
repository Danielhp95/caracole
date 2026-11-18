"""iReal Pro's forum in the nightly run: which songs get a chart as their sheet, which chart, and how it is kept.

The site is ``FakeIReal`` (helpers/ireal_site.py) behind a real ``PoliteClient``: the sitemaps, thread pages and the
jazz forum's page caracole's own user agent got, trimmed. The cache, the budget and robots.txt are the client's real
behaviour.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import add_song
from helpers.ireal_site import (
    BASE,
    CHILDREN,
    JAZZ_1460,
    NOW,
    RICHARDSON,
    SITEMAP,
    THAD_JONES,
    FakeIReal,
    link,
    thread_page,
)

from caracole.config import RankPolicy
from caracole.db import kv_get
from caracole.http import ProviderBlocked
from caracole.ireal_fetch import (
    SITE,
    IRealStats,
    candidates,
    composer_fits,
    ireal_sheets,
)
from caracole.ireal_index import playlist_pass
from caracole.library import keep_file, kept_files, song_dir
from caracole.overrides import IRealPick, Overrides
from caracole.site_index import refresh
from caracole.songs import get_song
from caracole.versions import get_version, song_versions, upsert_version

SITEMAPS = [SITEMAP, *CHILDREN]


def run(site: FakeIReal, conn, tmp_path: Path, now=NOW, *, budget=20, **kw) -> IRealStats:
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        return ireal_sheets(conn, client, tmp_path / "library", RankPolicy(), now, **kw)
    finally:
        client.close()


def read_playlist(site: FakeIReal, conn, tmp_path: Path) -> None:
    """The curated playlist read into the index, as the nightly run's step reads it before its songs."""
    client = site.client(tmp_path / "cache", budget=20)
    try:
        playlist_pass(conn, client, NOW, first=1)
    finally:
        client.close()


def folder(tmp_path: Path, song) -> Path:
    return song_dir(tmp_path / "library", song)


def kept(conn, song):
    return {f.name: get_version(conn, f.version_id) for f in kept_files(conn, song.id)}


def test_a_song_by_its_composer_gets_its_thread_s_chart_as_its_sheet(conn, tmp_path):
    song = add_song(conn, "Thad Jones", "Groove Merchant")
    site = FakeIReal()

    stats = run(site, conn, tmp_path)

    assert stats == IRealStats(sitemaps=6, tried=1, kept=1)
    # The sitemaps, then the thread whose slug names the song's artist: a chart of his in hand, nothing more asked.
    assert site.requests == [*SITEMAPS, f"{BASE}/{THAD_JONES}"]
    files = kept(conn, song)
    assert set(files) == {"sheet.json", "sheet.txt"}
    version = files["sheet.txt"]
    # The thread's two charts are versions; its latest post's, the repost with the coda, is the sheet.
    assert (version.provider, version.tab_id, version.slot, version.kind) == ("ireal", "9518/38106/1", "sheet", "chords")
    assert version.url == f"{BASE}/{THAD_JONES}#post-38106"
    assert version.raw == {"title": "Groove Merchant", "composer": "Jones Thad", "style": "Medium Swing", "key": "Bb",
                           "tonality_name": "Bb", "playlist": "", "tempo": 155, "thread": THAD_JONES, "post": 38106,
                           "place": 1}
    assert sorted(v.tab_id for v in song_versions(conn, song.id)) == ["9518/23346/1", "9518/38106/1"]
    doc = json.loads((folder(tmp_path, song) / "sheet.json").read_text(encoding="utf-8"))
    assert doc["provider"] == "ireal" and doc["url"] == version.url
    assert doc["content"].startswith("Thad Jones · Medium Swing · 4/4\n\n| [ch]Bb7[/ch] | [ch]Eb7[/ch]")
    assert "[Coda]" in doc["content"]
    assert doc["tune"]["music"].startswith("1r34LbKcu7") and doc["tune"]["scheme"] == "irealb"
    text = (folder(tmp_path, song) / "sheet.txt").read_text(encoding="utf-8")
    assert "[ch]" not in text and "| Bb7 | Eb7 |" in text
    assert get_song(conn, song.id).status == "found"
    assert kv_get(conn, f"ireal:checked:{song.id}") == "2026-11-18T03:30:00Z"
    assert "sheet.txt" in (folder(tmp_path, song) / "info.json").read_text(encoding="utf-8")


def test_a_song_meets_the_curated_playlist_from_the_cache_with_no_request(conn, tmp_path):
    song = add_song(conn, "Erroll Garner", "Misty")
    site = FakeIReal()
    read_playlist(site, conn, tmp_path)
    site.requests.clear()

    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1), refresh_index=False)

    assert stats.kept == 1 and site.requests == []  # the playlist's Misty is Garner's: no thread more is asked for
    assert kept(conn, song)["sheet.txt"].tab_id == "12753/31492/8"
    assert json.loads((folder(tmp_path, song) / "sheet.json").read_text())["tune"]["playlist"] == "Jazz 1460"


def test_a_performers_standard_is_the_curated_playlists_by_its_title_alone(conn, tmp_path):
    # Standards are filed by composer: the owner's line may name a singer. A curated playlist's chart is the song's by
    # its title alone; a thread named for another (Misty's composer) is never read for her.
    song = add_song(conn, "Ella Fitzgerald", "Misty")
    site = FakeIReal()
    read_playlist(site, conn, tmp_path)
    site.requests.clear()

    assert candidates(conn, song) == [JAZZ_1460]
    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1), refresh_index=False)

    assert stats.kept == 1 and site.requests == []
    assert kept(conn, song)["sheet.txt"].tab_id == "12753/31492/8"
    assert [v.tab_id for v in song_versions(conn, song.id)] == ["12753/31492/8"]


def test_bill_evans_autumn_leaves_is_the_jazz_1460s(conn, tmp_path):
    song = add_song(conn, "Bill Evans", "Autumn Leaves")
    site = FakeIReal()
    read_playlist(site, conn, tmp_path)
    site.requests.clear()
    run(site, conn, tmp_path, NOW + timedelta(hours=1), refresh_index=False)
    assert kept(conn, song)["sheet.txt"].raw["composer"] == "Kosma Joseph" and site.requests == []


# The owner's songs a title alone gave another song's chart (the sitemaps of 2026-11-18): the ruling's cases.
NAMESAKES = [
    ("Jorge Rivera-Herrans", "Open Arms", "threads/open-arms-journey.6168/", "Cain Jonathan"),
    ("Ren", "Patience", "threads/patience-guns-roses.14097/", "Guns N' Roses"),
    ("Jorge Rivera-Herrans", "The Challenge", "threads/the-challenge-stephen-scott.26339/", "Scott Stephen"),
    ("Ren", "Troubles", "threads/troubles-larrie-cook.1416/", "Cook Larrie"),
]


@pytest.mark.parametrize("artist, title, path, composer", NAMESAKES)
def test_a_thread_named_for_someone_else_is_another_song_of_that_name(conn, tmp_path, artist, title, path, composer):
    song = add_song(conn, artist, title)
    site = FakeIReal()
    site.threads(path)
    site.page(path, thread_page(f"{title} - someone", [(9, [link([(title, composer, "Rock", "C", "[T44C   |G   Z ")])])],
                                path=path))

    stats = run(site, conn, tmp_path)

    assert stats.kept == 0 and kept(conn, song) == {}
    assert f"{BASE}/{path}" not in site.requests  # never read for the song: its slug names another
    # Read all the same (for another song, a search), its chart is still none of the song's.
    client = site.client(tmp_path / "cache")
    try:
        from caracole.ireal_index import read_thread

        read_thread(conn, client, path, NOW)
    finally:
        client.close()
    assert candidates(conn, song) == []


def test_a_composer_none_of_whose_threads_names_the_artist_gets_no_chart_but_a_pick(conn, tmp_path):
    song = add_song(conn, "Count Basie", "Groove Merchant")
    site = FakeIReal()
    assert run(site, conn, tmp_path).kept == 0 and kept(conn, song) == {}
    assert not any("groove-merchant" in url for url in site.requests)
    picked = Overrides(ireal={song.key: IRealPick("groove-merchant-thad-jones", 9518)})
    assert run(site, conn, tmp_path, NOW + timedelta(hours=1), overrides=picked).kept == 1
    assert kept(conn, song)["sheet.txt"].tab_id == "9518/38106/1"


def test_a_thread_named_for_the_title_alone_may_hold_the_artists_chart(conn, tmp_path):
    song = add_song(conn, "Erroll Garner", "Misty")
    site = FakeIReal()
    site.threads("threads/misty.40000/", "threads/misty-roses-tim-hardin.16246/")
    site.page("threads/misty.40000/", thread_page("Misty", [
        (41, [link([("Misty", "Garner Erroll", "Ballad", "Eb", "[*AT44Eb^7   |Bb-7 Eb7 Z ")])])], path="threads/misty.40000/"))

    assert run(site, conn, tmp_path).kept == 1
    assert kept(conn, song)["sheet.txt"].tab_id == "40000/41/1"
    assert f"{BASE}/threads/misty-roses-tim-hardin.16246/" not in site.requests


def test_a_title_irealpro_writes_with_its_article_last_is_the_songs(conn, tmp_path):
    song = add_song(conn, "Stan Getz", "The Girl from Ipanema")
    site = FakeIReal()
    read_playlist(site, conn, tmp_path)
    run(site, conn, tmp_path, NOW + timedelta(hours=1), refresh_index=False)
    assert kept(conn, song)["sheet.txt"].raw["title"] == "Girl From Ipanema, The"


def test_a_jerome_richardson_line_keeps_his_threads_latest_chart(conn, tmp_path):
    song = add_song(conn, "Jerome Richardson", "Groove Merchant")
    site = FakeIReal()
    run(site, conn, tmp_path)
    assert site.requests[-1] == f"{BASE}/{RICHARDSON}"
    assert kept(conn, song)["sheet.txt"].tab_id == "14294/48070/1"
    assert {v.tab_id for v in song_versions(conn, song.id)} == {"14294/6952/1", "14294/48070/1"}


def test_a_composer_is_one_of_the_songs_artists_whichever_order_their_names_come_in(conn):
    song = add_song(conn, "Antonio Carlos Jobim", "Wave")
    assert composer_fits(song, "Jobim Antonio-Carlos") and composer_fits(add_song(conn, "Jobim", "Wave"), "Jobim A")
    assert not composer_fits(song, "Gimbel Norman") and not composer_fits(song, "")


def test_a_song_with_a_human_sheet_is_never_asked_and_one_with_an_auto_sheet_alone_is(conn, tmp_path):
    ug = add_song(conn, "Thad Jones", "Groove Merchant")
    vid = upsert_version(conn, provider="ug", tab_id="1", song_id=ug.id, slot="sheet", kind="chords", rating=5,
                         votes=1, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/1", raw={},
                         now="2026-11-01T00:00:00Z")
    keep_file(conn, tmp_path / "library", song=ug, version_id=vid, name="sheet.txt", data=b"[ch]C[/ch]\n", rank=1)
    auto = add_song(conn, "Jerome Richardson", "Groove Merchant")
    avid = upsert_version(conn, provider="auto", tab_id="auto", song_id=auto.id, slot="sheet", kind="auto", rating=0,
                          votes=0, version=1, label=None, url="", raw={}, now="2026-11-01T00:00:00Z")
    keep_file(conn, tmp_path / "library", song=auto, version_id=avid, name="sheet (auto).txt", data=b"C\n", rank=1)
    site = FakeIReal()

    stats = run(site, conn, tmp_path)

    assert stats.kept == 1 and f"{BASE}/{THAD_JONES}" not in site.requests
    assert set(kept(conn, auto)) == {"sheet.txt", "sheet.json", "sheet (auto).txt"}  # a chart is no complete sheet


def test_a_title_no_thread_names_sends_nothing_but_the_sitemaps(conn, tmp_path):
    song = add_song(conn, "Somebody", "A Tune Nobody Charted")
    site = FakeIReal()
    assert run(site, conn, tmp_path) == IRealStats(sitemaps=6)
    assert site.requests == SITEMAPS
    assert kv_get(conn, f"ireal:checked:{song.id}") is None


def test_threads_that_hold_no_chart_of_the_title_are_a_miss_asked_again_after_30_days(conn, tmp_path):
    song = add_song(conn, "Tim Hardin", "Misty")
    site = FakeIReal()
    site.page("threads/misty-roses-tim-hardin.16246/", thread_page("Misty Roses - Tim Hardin", [
        (7, [link([("Misty Roses", "Hardin Tim", "Folk", "C", "[T44C^7   |F^7   Z ")])])],
        path="threads/misty-roses-tim-hardin.16246/"))

    stats = run(site, conn, tmp_path)

    assert stats == IRealStats(sitemaps=6, tried=1, missing=1)
    # The slug that names him alone: Misty Roses, no Misty there. The others name other people.
    assert site.requests[len(SITEMAPS):] == [f"{BASE}/threads/misty-roses-tim-hardin.16246/"]
    assert kept(conn, song) == {} and kv_get(conn, f"ireal:checked:{song.id}") == "2026-11-18T03:30:00Z"
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)).tried == 0 and site.requests == []
    # After 30 days it is due again, and a thread read before is no candidate any more: its page said no Misty there.
    assert run(site, conn, tmp_path, NOW + timedelta(days=31)).tried == 0
    assert set(site.requests) <= set(SITEMAPS)


def test_a_page_that_wont_parse_is_an_error_never_a_miss(conn, tmp_path):
    song = add_song(conn, "Thad Jones", "Groove Merchant")
    site = FakeIReal()
    site.page(THAD_JONES, "<html><body><h1>Oops! We ran into some problems.</h1></body></html>")

    stats = run(site, conn, tmp_path)

    assert stats.errors == 1 and stats.kept == stats.missing == 0
    assert [s.key for s, _ in stats.failures] == [song.key]
    assert kv_get(conn, f"ireal:checked:{song.id}") is None
    # The next night the cache's copy, which won't parse, is asked for once more past the cache.
    site.page(THAD_JONES, thread_page("Groove Merchant - Thad Jones", [
        (1, [link([("Groove Merchant", "Jones Thad", "Medium Swing", "Bb", "[T44Bb7   |Eb7   Z ")])])]))
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=1)).kept == 1
    assert site.requests == [f"{BASE}/{THAD_JONES}"]


def test_a_block_propagates_and_marks_no_song(conn, tmp_path):
    song = add_song(conn, "Thad Jones", "Groove Merchant")
    site = FakeIReal()
    site.page(THAD_JONES, "<html>Forbidden</html>", status=403)
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    assert kv_get(conn, f"ireal:checked:{song.id}") is None


def test_a_spent_budget_ends_the_pass(conn, tmp_path):
    add_song(conn, "Thad Jones", "Groove Merchant")
    site = FakeIReal()
    stats = run(site, conn, tmp_path, budget=7)
    assert stats.budget_exhausted and stats.kept == 0


def test_a_chart_you_picked_is_kept_in_place_of_another_sites_sheet_and_the_best(conn, tmp_path):
    song = add_song(conn, "Thad Jones", "Groove Merchant")
    vid = upsert_version(conn, provider="lacuerda", tab_id="x/groove-merchant-1", song_id=song.id, slot="sheet",
                         kind="acordes", rating=0, votes=0, version=1, label=None, url="https://acordes.lacuerda.net/x",
                         raw={}, now="2026-11-01T00:00:00Z")
    keep_file(conn, tmp_path / "library", song=song, version_id=vid, name="sheet.txt", data=b"[ch]C[/ch]\n", rank=1)
    overrides = Overrides(ireal={song.key: IRealPick("groove-merchant-thad-jones", 9518, 23346)})
    site = FakeIReal()

    assert run(site, conn, tmp_path, overrides=overrides).kept == 1
    assert kept(conn, song)["sheet.txt"].tab_id == "9518/23346/1"
    assert kv_get(conn, f"ireal:checked:{song.id}:pick") == f"{BASE}/{THAD_JONES}#post-23346"
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(hours=1), overrides=overrides).tried == 0  # kept: asked no more
    # Another pick is asked for at once, whatever the date.
    other = Overrides(ireal={song.key: IRealPick("groove-merchant-thad-jones", 9518, 38106)})
    assert run(site, conn, tmp_path, NOW + timedelta(hours=2), overrides=other).kept == 1
    assert kept(conn, song)["sheet.txt"].tab_id == "9518/38106/1"


def test_a_pick_never_replaces_a_ug_tab_you_pinned(conn, tmp_path):
    song = add_song(conn, "Thad Jones", "Groove Merchant")
    vid = upsert_version(conn, provider="ug", tab_id="77", song_id=song.id, slot="sheet", kind="chords", rating=5,
                         votes=1, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/77", raw={},
                         now="2026-11-01T00:00:00Z")
    keep_file(conn, tmp_path / "library", song=song, version_id=vid, name="sheet.txt", data=b"[ch]C[/ch]\n", rank=1)
    overrides = Overrides(ireal={song.key: IRealPick("groove-merchant-thad-jones", 9518)}, pin={song.key: (77,)})
    site = FakeIReal()
    assert run(site, conn, tmp_path, overrides=overrides) == IRealStats()
    assert site.requests == []


def test_a_kept_chart_the_library_lost_is_written_again(conn, tmp_path):
    song = add_song(conn, "Thad Jones", "Groove Merchant")
    site = FakeIReal()
    run(site, conn, tmp_path)
    (folder(tmp_path, song) / "sheet.txt").unlink()
    site.requests.clear()

    assert run(site, conn, tmp_path, NOW + timedelta(hours=1)).kept == 1
    assert (folder(tmp_path, song) / "sheet.txt").exists() and site.requests == []  # the cache's page


def test_a_lookup_asks_about_its_song_alone_and_reads_no_sitemap(conn, tmp_path):
    song = add_song(conn, "Thad Jones", "Groove Merchant")
    other = add_song(conn, "Jerome Richardson", "Groove Merchant")
    site = FakeIReal()
    run(site, conn, tmp_path, only={-1})  # nobody's: nothing sent
    assert site.requests == []
    client = site.client(tmp_path / "cache")
    try:
        refresh(conn, client, SITE, NOW)
    finally:
        client.close()
    site.requests.clear()
    stats = run(site, conn, tmp_path, only={song.id}, refresh_index=False)
    assert stats.kept == 1 and site.requests == [f"{BASE}/{THAD_JONES}"]
    assert kept(conn, other) == {}


def test_caracole_asks_with_its_own_user_agent(conn, tmp_path):
    add_song(conn, "Thad Jones", "Groove Merchant")
    site = FakeIReal()
    client = site.client(tmp_path / "cache", user_agent="caracole/0.1 (personal tab library)")
    try:
        ireal_sheets(conn, client, tmp_path / "library", RankPolicy(), NOW)
    finally:
        client.close()
    assert set(site.agents) == {"caracole/0.1 (personal tab library)"}


# --- the review of 2026-11-18 ----------------------------------------------------------------------------------------


def test_a_tune_that_wont_read_beside_good_ones_is_passed_over_and_the_songs_own_is_an_error_never_a_miss(conn,
                                                                                                         tmp_path):
    # "T4", a time of one digit at the music's end, once failed the whole step for every song the page was a
    # candidate of; now a tune that won't read is passed over, and is an error only for the song it would be.
    site = FakeIReal()
    site.page(JAZZ_1460, thread_page("Jazz 1460 Standards", [(31492, [link([
        ("Misty", "Garner Erroll", "Ballad", "Eb", "T4"),
        ("Autumn Leaves", "Kosma Joseph", "Medium Swing", "G-", "[T44C-7 F7 |Bb^7   Z "),
    ], playlist="Jazz 1460")])], path=JAZZ_1460))
    read_playlist(site, conn, tmp_path)
    leaves = add_song(conn, "Bill Evans", "Autumn Leaves")
    misty = add_song(conn, "Ella Fitzgerald", "Misty")

    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1), refresh_index=False)

    assert (stats.kept, stats.missing, stats.errors) == (1, 0, 1)
    assert kept(conn, leaves)["sheet.txt"].raw["composer"] == "Kosma Joseph"
    assert kept(conn, misty) == {} and [s.id for s, _ in stats.failures] == [misty.id]
    assert "no chord" in str(stats.failures[0][1])
    assert kv_get(conn, f"ireal:checked:{misty.id}") is None  # an error: asked about again at the next run


def test_a_playlist_a_song_reads_from_the_cache_is_still_read_again_after_30_days(conn, tmp_path):
    # The reviewer's sequence: the pass on day 0, Misty from the cache on day 20, the pass on day 35.
    site = FakeIReal()
    read_playlist(site, conn, tmp_path)
    read_at = conn.execute("SELECT read_at FROM ireal_threads WHERE path = ?", (JAZZ_1460,)).fetchone()[0]
    add_song(conn, "Ella Fitzgerald", "Misty")
    assert run(site, conn, tmp_path, NOW + timedelta(days=20), refresh_index=False).kept == 1
    assert conn.execute("SELECT read_at FROM ireal_threads WHERE path = ?", (JAZZ_1460,)).fetchone()[0] == read_at
    site.requests.clear()
    client = site.client(tmp_path / "cache", now=NOW + timedelta(days=35))
    try:
        stats = playlist_pass(conn, client, NOW + timedelta(days=35), first=1, refresh_index=False)
    finally:
        client.close()
    assert stats.read == 1 and site.requests == [f"{BASE}/{JAZZ_1460}"]


@pytest.mark.parametrize("artist", ["Thad Jones / Count Basie", "Thad Jones & Mel Lewis", "Count Basie and Thad Jones",
                                    "Count Basie, Thad Jones", "Count Basie feat. Thad Jones",
                                    "COUNT BASIE WITH THAD JONES"])
def test_a_line_naming_several_artists_is_each_of_them(conn, tmp_path, artist):
    song = add_song(conn, artist, "Groove Merchant")
    site = FakeIReal()
    assert run(site, conn, tmp_path).kept == 1
    assert kept(conn, song)["sheet.txt"].tab_id.startswith("9518/")
    assert site.requests[len(SITEMAPS)] == f"{BASE}/{THAD_JONES}"


def test_the_jazz_forums_other_playlists_need_the_composer_as_any_thread_does(conn, tmp_path):
    # Only the Jazz 1460 is the moderators' list of standards: a gypsy jazz playlist's Misty is no one's by its title.
    gypsy = "threads/gypsy-jazz.215/"
    site = FakeIReal()
    site.page(gypsy, thread_page("Gypsy Jazz", [(5, [link([
        ("Minor Swing", "Reinhardt Django", "Gypsy Jazz", "A-", "[T44A-6   |E7   Z "),
        ("Misty", "Someone Else", "Ballad", "Eb", "[T44Eb^7   |Ab7   Z "),
    ], playlist="Gypsy Jazz")])], path=gypsy))
    client = site.client(tmp_path / "cache", budget=20)
    try:
        playlist_pass(conn, client, NOW)
    finally:
        client.close()
    django = add_song(conn, "Django Reinhardt", "Minor Swing")
    ella = add_song(conn, "Ella Fitzgerald", "Minor Swing")
    misty = add_song(conn, "Sarah Vaughan", "Misty")

    assert candidates(conn, django) == [gypsy] and candidates(conn, ella) == []
    assert candidates(conn, misty) == [JAZZ_1460]  # the 1460's Misty, by its title alone; never the gypsy one
    run(site, conn, tmp_path, NOW + timedelta(hours=1), refresh_index=False)
    assert kept(conn, django)["sheet.txt"].tab_id == "215/5/1" and kept(conn, ella) == {}
    assert kept(conn, misty)["sheet.txt"].tab_id.startswith("12753/")


def test_a_pick_of_a_post_on_a_later_page_asks_the_posts_address_and_reads_its_page(conn, tmp_path):
    later = "threads/groove-merchant-thad-jones.9518/page-2"
    site = FakeIReal()
    site.redirect("threads/groove-merchant-thad-jones.9518/post-99001", later)
    site.page(later, thread_page("Groove Merchant - Thad Jones", [(99001, [link([
        ("Groove Merchant", "Jones Thad", "Medium Swing", "Bb", "[T44Bb7   |Eb7   |Bb7   Z ")])])], path=later))
    song = add_song(conn, "Count Basie", "Groove Merchant")
    picked = Overrides(ireal={song.key: IRealPick("groove-merchant-thad-jones", 9518, 99001)})

    stats = run(site, conn, tmp_path, overrides=picked)

    assert stats.kept == 1 and kept(conn, song)["sheet.txt"].tab_id == "9518/99001/1"
    assert site.requests[len(SITEMAPS):] == [
        f"{BASE}/{THAD_JONES}", f"{BASE}/threads/groove-merchant-thad-jones.9518/post-99001", f"{BASE}/{later}"]
    # The index keeps first pages alone.
    assert conn.execute("SELECT COUNT(*) FROM ireal_charts WHERE post = 99001").fetchone()[0] == 0
    assert kv_get(conn, f"ireal:checked:{song.id}:pick") == picked.ireal[song.key].url


def test_a_pick_of_a_post_gone_is_a_miss_once_its_address_answered(conn, tmp_path):
    song = add_song(conn, "Count Basie", "Groove Merchant")
    site = FakeIReal()  # its post's address answers 404
    picked = Overrides(ireal={song.key: IRealPick("groove-merchant-thad-jones", 9518, 99002)})
    stats = run(site, conn, tmp_path, overrides=picked)
    assert (stats.kept, stats.missing, stats.errors) == (0, 1, 0)
    assert site.requests[-1] == f"{BASE}/threads/groove-merchant-thad-jones.9518/post-99002"


class Handing:
    """A client whose process lets a lookup go first after the requests ``after`` names (commands/_common.py's
    clients count their handoffs in ``handoffs``)."""

    def __init__(self, inner, after):
        self.inner, self.after, self.handoffs = inner, after, 0

    def get(self, url, **kw):
        resp = self.inner.get(url, **kw)
        self.handoffs += self.after(url)
        return resp

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_a_pick_a_lookup_made_while_the_pass_paused_is_read_before_the_next_song(conn, tmp_path):
    song = add_song(conn, "Count Basie", "Groove Merchant")  # no candidate of its own: only a pick reads a chart
    site = FakeIReal()
    picked = Overrides(ireal={song.key: IRealPick("groove-merchant-thad-jones", 9518)})
    client = Handing(site.client(tmp_path / "cache"), lambda url: url == SITEMAP)
    try:
        stats = ireal_sheets(conn, client, tmp_path / "library", RankPolicy(), NOW, overrides=Overrides(),
                             reload_overrides=lambda: picked)
    finally:
        client.close()
    assert stats.kept == 1 and kept(conn, song)["sheet.txt"].tab_id.startswith("9518/")


def test_a_song_a_lookup_changed_in_its_own_turn_is_left_as_the_lookup_left_it(conn, tmp_path):
    song = add_song(conn, "Thad Jones", "Groove Merchant")
    site = FakeIReal()
    ignored = Overrides(ignore=frozenset({song.key}))
    client = Handing(site.client(tmp_path / "cache"), lambda url: url == f"{BASE}/{THAD_JONES}")
    try:
        stats = ireal_sheets(conn, client, tmp_path / "library", RankPolicy(), NOW, overrides=Overrides(),
                             reload_overrides=lambda: ignored)
    finally:
        client.close()
    assert (stats.kept, stats.missing) == (0, 0) and kept(conn, song) == {}
    assert kv_get(conn, f"ireal:checked:{song.id}") is None
