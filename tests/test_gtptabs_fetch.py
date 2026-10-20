"""gtptabs.com in the nightly run: which songs get a Guitar Pro file, and how it is kept.

The site is ``FakeGtpTabs`` (helpers/gtptabs_site.py) behind a real ``PoliteClient``:
the captured sitemaps and Blur's captured artist page, and synthetic files. The cache,
the budget and robots.txt are the client's real behaviour.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import add_song
from helpers.gtptabs_site import (
    BASE,
    HTML,
    NOW,
    FakeGtpTabs,
    artist_page,
    entry,
    fixture,
    gp_file,
    gpx_file,
)

from caracole.db import kv_get
from caracole.gtptabs_fetch import GtpTabsStats, gtptabs_files
from caracole.http import ProviderBlocked
from caracole.library import keep_file, kept_files, song_dir
from caracole.overrides import Overrides
from caracole.songs import update_song
from caracole.versions import get_version, upsert_version

INDEX = f"{BASE}/sitemapGoogle.xml"
SITEMAPS = [INDEX, f"{BASE}/sitemapGoogle1.xml", f"{BASE}/sitemapGoogle6.xml"]
BLUR = f"{BASE}/tabs/2/blur.html"
HTML_PAGE = b"<!DOCTYPE html><html><head><title>GtpTabs.com</title></head><body>Sorry</body></html>"


def download(tab_id: int) -> str:
    return f"{BASE}/tabs/download/{tab_id}.html"


def run(site: FakeGtpTabs, conn, tmp_path: Path, now=NOW, *, budget=20, overrides=None) -> GtpTabsStats:
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        return gtptabs_files(conn, client, tmp_path / "library", now, overrides=overrides)
    finally:
        client.close()


def folder(tmp_path: Path, song) -> Path:
    return song_dir(tmp_path / "library", song)


def checked(conn, song) -> str | None:
    return kv_get(conn, f"gtptabs:checked:{song.id}")


# --- a file for a song that has none ---------------------------------------------------------------


def test_a_song_without_a_guitar_pro_file_gets_one_from_its_artists_page(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(files={26: gp_file(b"v3.00")})

    stats = run(site, conn, tmp_path)

    assert stats == GtpTabsStats(sitemaps=2, tried=1, kept=1)
    # The index first (three requests), then one artist page and one download.
    assert site.requests == [*SITEMAPS, BLUR, download(26)]
    assert (folder(tmp_path, song) / "guitar-1.gp3").read_bytes() == gp_file(b"v3.00")
    [kept] = kept_files(conn, song.id)
    assert (kept.name, kept.kept_rank) == ("guitar-1.gp3", 1)
    version = get_version(conn, kept.version_id)
    assert (version.provider, version.tab_id, version.slot, version.kind, version.pick_rank) == (
        "gtptabs", "26", "guitar", "guitar-pro", None)
    assert version.url == f"{BASE}/tabs/2/blur/beetlebum.html"
    assert version.raw["download"] == download(26)


def test_info_json_says_where_the_file_came_from(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    run(FakeGtpTabs(files={26: gp_file(b"v3.00")}), conn, tmp_path)
    info = json.loads((folder(tmp_path, song) / "info.json").read_text(encoding="utf-8"))
    [entry_] = info["files"]
    assert (entry_["name"], entry_["provider"], entry_["url"]) == (
        "guitar-1.gp3", "gtptabs", f"{BASE}/tabs/2/blur/beetlebum.html")


def test_the_best_rated_upload_is_taken_and_its_bytes_name_its_format(conn, tmp_path):
    # Song 2: 4 stars (gp4), 3 stars, a bass-and-drums upload, and "Song 2 (Live)", another title.
    # The site says gp4; the file is a Guitar Pro 6 one, so it is kept as .gpx.
    song = add_song(conn, "Blur", "Song 2")
    site = FakeGtpTabs(files={12: gpx_file(), 15: gp_file()})
    run(site, conn, tmp_path)
    assert [u for u in site.requests if "/download/" in u] == [download(12)]
    assert [f.name for f in kept_files(conn, song.id)] == ["guitar-1.gpx"]


def test_a_power_tab_file_is_a_power_tab_version(conn, tmp_path):
    from helpers.gtptabs_site import ptb_file

    song = add_song(conn, "Blur", "Country House")
    run(FakeGtpTabs(files={2: ptb_file()}), conn, tmp_path)
    [kept] = kept_files(conn, song.id)
    assert kept.name == "guitar-1.ptb" and get_version(conn, kept.version_id).kind == "power"


def test_titles_meet_as_caracoles_keys_do(conn, tmp_path):
    # "Coffee & TV" is listed twice, as "Coffee & TV" (4 stars) and "Coffee And Tv" (5 stars);
    # Spotify's suffix goes before the titles are compared.
    song = add_song(conn, "Blur", "Coffee & TV - 2012 Remaster")
    site = FakeGtpTabs(files={79720: gp_file()})
    run(site, conn, tmp_path)
    assert [f.name for f in kept_files(conn, song.id)] == ["guitar-1.gp5"]
    assert [u for u in site.requests if "/download/" in u] == [download(79720)]


def test_people_and_bands_named_the_are_found_under_the_sites_names(conn, tmp_path):
    elton = add_song(conn, "Elton John", "Crocodile Rock")
    beatles = add_song(conn, "The Beatles", "Yesterday")
    site = FakeGtpTabs(
        pages={
            f"{BASE}/tabs/10/john-elton.html": (200, artist_page(
                "John, Elton", "tabs/10/john-elton.html",
                entry(6970, "tabs/10/john-elton/crocodile-rock.html", "Crocodile Rock", fmt="gp4")), HTML),
            f"{BASE}/tabs/2/beatles-the.html": (200, artist_page(
                "Beatles, The", "tabs/2/beatles-the.html",
                entry(500, "tabs/2/beatles-the/yesterday.html", "Yesterday", fmt="gp3", stars=4),
                entry(81000, "tabs/2/beatles-the/yesterday-13.html", "Yesterday (13)", stars=2)), HTML),
        },
        files={6970: gp_file(b"v4.06"), 500: gp_file(b"v3.00")},
    )
    stats = run(site, conn, tmp_path)
    assert stats.kept == 2
    assert [f.name for f in kept_files(conn, elton.id)] == ["guitar-1.gp4"]
    assert [f.name for f in kept_files(conn, beatles.id)] == ["guitar-1.gp3"]


def test_a_song_uploaded_after_the_sitemaps_is_found_on_its_artists_page(conn, tmp_path):
    # The sitemaps are from 2015: they know Blur, not "Coffee & TV". Blur's page lists it.
    song = add_song(conn, "Blur", "Coffee & TV")
    run(FakeGtpTabs(files={79720: gp_file()}), conn, tmp_path)
    assert [f.name for f in kept_files(conn, song.id)] == ["guitar-1.gp5"]


def test_a_number_a_file_in_the_folder_holds_is_never_reused(conn, tmp_path):
    # A guitar-1.gp5 caracole doesn't track, put there by you: the download takes guitar-2.
    song = add_song(conn, "Blur", "Beetlebum")
    folder(tmp_path, song).mkdir(parents=True)
    (folder(tmp_path, song) / "guitar-1.gp5").write_bytes(b"yours")
    run(FakeGtpTabs(files={26: gp_file(b"v3.00")}), conn, tmp_path)
    assert (folder(tmp_path, song) / "guitar-1.gp5").read_bytes() == b"yours"
    assert [f.name for f in kept_files(conn, song.id)] == ["guitar-2.gp3"]


# --- songs left alone ---------------------------------------------------------------------------------


def test_a_song_with_a_guitar_pro_file_gets_no_other(conn, tmp_path):
    # Filed from _inbox for one of UG's picks: nothing more is downloaded for it.
    song = add_song(conn, "Blur", "Beetlebum")
    ug = upsert_version(conn, provider="ug", tab_id="301", song_id=song.id, slot="guitar", kind="guitar-pro",
                        rating=4.5, votes=9, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/301",
                        raw={}, now="x")
    keep_file(conn, tmp_path / "library", song=song, version_id=ug, name="guitar-1.gp5", data=gp_file(), rank=1)
    site = FakeGtpTabs(files={26: gp_file(b"v3.00")})
    stats = run(site, conn, tmp_path)
    assert stats.tried == 0 and site.requests == []  # not even the sitemaps


def test_a_library_with_no_song_needing_a_file_asks_nothing(conn, tmp_path):
    site = FakeGtpTabs()
    assert run(site, conn, tmp_path) == GtpTabsStats()
    assert site.requests == []


def test_ignored_songs_get_nothing(conn, tmp_path):
    ignored = add_song(conn, "Blur", "Beetlebum")
    update_song(conn, ignored.id, status="ignored")
    in_overrides = add_song(conn, "Blur", "Song 2")
    site = FakeGtpTabs(files={26: gp_file(), 12: gp_file()})
    stats = run(site, conn, tmp_path, overrides=Overrides(ignore=frozenset({in_overrides.key})))
    assert stats.tried == 0 and BLUR not in site.requests


def test_a_song_whose_artist_the_site_doesnt_know_costs_nothing(conn, tmp_path):
    add_song(conn, "Soda Stereo", "De Música Ligera")
    site = FakeGtpTabs()
    stats = run(site, conn, tmp_path)
    assert stats.tried == 0 and site.requests == SITEMAPS


def test_songs_whose_title_the_sitemaps_list_go_first(conn, tmp_path):
    # Budget for one artist page and one download after the index: "Song 2", which the
    # sitemaps list, comes before the newer "Coffee & TV", which only Blur's page does.
    song2 = add_song(conn, "Blur", "Song 2", added_at="2026-10-01T00:00:00Z")
    coffee = add_song(conn, "Blur", "Coffee & TV", added_at="2026-10-10T00:00:00Z")
    stats = run(FakeGtpTabs(files={12: gp_file(), 79720: gp_file()}), conn, tmp_path, budget=5)
    assert stats.kept == 1 and stats.budget_exhausted
    assert [f.name for f in kept_files(conn, song2.id)] == ["guitar-1.gp5"]
    assert kept_files(conn, coffee.id) == [] and checked(conn, coffee) is None


# --- misses ----------------------------------------------------------------------------------------------


def test_a_title_its_artists_page_doesnt_list_is_asked_again_after_30_days(conn, tmp_path):
    song = add_song(conn, "Blur", "Tender")  # not among the captured page's 14 entries
    site = FakeGtpTabs()
    stats = run(site, conn, tmp_path)
    assert (stats.tried, stats.missing, stats.kept) == (1, 1, 0)
    assert checked(conn, song) == "2026-10-19T03:30:00Z"

    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)).tried == 0
    assert site.requests == []

    later = run(site, conn, tmp_path, NOW + timedelta(days=31))
    assert later.tried == 1 and later.missing == 1
    assert BLUR in site.requests  # its page, cached for 30 days, is read again


def test_uploads_without_a_guitar_part_are_passed_over(conn, tmp_path):
    # Oily Water (2) holds bass, drums and vocals: no file for a guitarist, so none is downloaded.
    song = add_song(conn, "Blur", "Oily Water")
    site = FakeGtpTabs(files={79718: gp_file()})
    stats = run(site, conn, tmp_path)
    assert stats.missing == 1 and not [u for u in site.requests if "/download/" in u]
    assert kept_files(conn, song.id) == []


# --- answers that aren't files ---------------------------------------------------------------------------


def test_a_download_that_isnt_a_guitar_pro_file_is_not_kept_and_the_next_upload_is_tried(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(files={26: HTML_PAGE, 58155: gpx_file()})
    stats = run(site, conn, tmp_path)
    assert stats.kept == 1 and stats.errors == 0
    assert [u for u in site.requests if "/download/" in u] == [download(26), download(58155)]
    assert [f.name for f in kept_files(conn, song.id)] == ["guitar-1.gpx"]
    assert not list(folder(tmp_path, song).glob("guitar-*.gp3"))


def test_uploads_the_site_no_longer_has_are_passed_over_for_30_days(conn, tmp_path):
    # Every Beetlebum upload answers 404: each is asked for again after 30 days, not before.
    # The page lists them, so the song is no miss; it just has nothing to download meanwhile.
    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs()
    stats = run(site, conn, tmp_path)
    assert (stats.tried, stats.kept, stats.missing, stats.errors) == (1, 0, 0, 0)
    assert [u for u in site.requests if "/download/" in u] == [download(26), download(58155), download(89061)]
    assert checked(conn, song) is None

    site.requests.clear()
    run(site, conn, tmp_path, NOW + timedelta(days=10))
    assert site.requests == []
    site.files[89061] = gpx_file()
    assert run(site, conn, tmp_path, NOW + timedelta(days=31)).kept == 1
    assert [f.name for f in kept_files(conn, song.id)] == ["guitar-1.gpx"]


def test_at_most_three_downloads_a_song_a_run(conn, tmp_path):
    # Four uploads, none there: three are tried this run, the fourth the next. Not a miss yet.
    song = add_song(conn, "Blur", "Tender")
    page = artist_page("Blur", "tabs/2/blur.html", *(
        entry(900 + n, f"tabs/2/blur/tender{'' if n == 1 else f'-{n}'}.html",
              "Tender" if n == 1 else f"Tender ({n})", stars=5 - n) for n in range(1, 5)))
    site = FakeGtpTabs(pages={BLUR: (200, page, HTML)})
    stats = run(site, conn, tmp_path)
    assert [u for u in site.requests if "/download/" in u] == [download(901), download(902), download(903)]
    assert stats.missing == 0 and checked(conn, song) is None

    site.requests.clear()
    site.files[904] = gp_file()
    assert run(site, conn, tmp_path).kept == 1
    assert [u for u in site.requests if "/download/" in u] == [download(904)]


def test_three_pages_in_a_row_where_files_should_be_end_the_pass_as_an_error(conn, tmp_path):
    # A site that answers every download with a page (a login wall, say) costs three requests,
    # and no song becomes a miss for it. Country House goes first (the newest), then Song 2.
    songs = [add_song(conn, "Blur", title) for title in ("Beetlebum", "Song 2", "Country House")]
    site = FakeGtpTabs(files={n: HTML_PAGE for n in (2, 12, 15, 26, 58155, 89061)})
    stats = run(site, conn, tmp_path)
    assert [u for u in site.requests if "/download/" in u] == [download(2), download(12), download(15)]
    assert stats.errors == 1 and stats.kept == 0 and stats.missing == 0
    assert all(checked(conn, s) is None for s in songs)


def test_a_download_redirected_where_robots_txt_closes_is_never_followed(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(
        pages={download(26): (302, b"", {"Location": f"{BASE}/storage/tabs/beetlebum.gp3"})},
        files={58155: gpx_file()},
    )
    stats = run(site, conn, tmp_path)
    assert stats.kept == 1 and stats.errors == 0
    assert not [u for u in site.requests if "/storage/" in u]
    assert [f.name for f in kept_files(conn, song.id)] == ["guitar-1.gpx"]


def test_no_url_robots_txt_closes_is_ever_asked_for(conn, tmp_path):
    # The artist page links its "Download all" archive (/storage/) and its upload form, and the
    # sitemaps list a /ru/ copy of every page: none is asked for.
    add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(files={26: gp_file(b"v3.00")})
    run(site, conn, tmp_path)
    closed = ("/ru/", "/storage/", "/tabs/upload.html", "/search/", "/advertisement.html")
    assert not [u for u in site.requests if any(c in u for c in closed)]


# --- errors are never misses ------------------------------------------------------------------------------


def test_a_block_is_raised_and_marks_nothing(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(pages={BLUR: (403, "Forbidden", HTML)}, files={26: gp_file()})
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    assert checked(conn, song) is None and kept_files(conn, song.id) == []


def test_a_spent_budget_is_no_miss(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    stats = run(FakeGtpTabs(files={26: gp_file()}), conn, tmp_path, budget=4)  # no request left for the file
    assert stats.budget_exhausted and (stats.kept, stats.missing) == (0, 0)
    assert checked(conn, song) is None and kept_files(conn, song.id) == []


def test_a_server_error_is_an_error_not_a_miss(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(pages={BLUR: (502, "Bad gateway", HTML)})
    stats = run(site, conn, tmp_path)
    assert (stats.tried, stats.errors, stats.missing) == (1, 1, 0)
    assert checked(conn, song) is None


def test_a_page_that_isnt_an_artist_page_is_fetched_once_more_then_an_error(conn, tmp_path):
    # A notice served with HTTP 200 is cached: the next run asks again before it counts as an error.
    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(pages={BLUR: (200, "<html><body>Back soon</body></html>", HTML)})
    assert run(site, conn, tmp_path).errors == 1
    site.pages[BLUR] = (200, fixture("artist.html"), HTML)  # the real page again
    site.files[26] = gp_file(b"v3.00")
    site.requests.clear()
    assert run(site, conn, tmp_path).kept == 1
    assert site.requests == [BLUR, download(26)]
    assert checked(conn, song) is not None


def test_a_sitemap_index_that_fails_leaves_the_index_as_it_was(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(files={26: gp_file(b"v3.00")})
    run(site, conn, tmp_path, budget=3)  # the index is read, then the budget is spent
    site.pages[INDEX] = (500, "oops", HTML)
    stats = run(site, conn, tmp_path, NOW + timedelta(days=31))
    assert stats.errors == 1 and stats.kept == 1
    assert [f.name for f in kept_files(conn, song.id)] == ["guitar-1.gp3"]


# --- the index -----------------------------------------------------------------------------------------------


def test_the_index_is_read_again_only_after_30_days_and_with_conditional_requests(conn, tmp_path):
    add_song(conn, "Soda Stereo", "Signos")  # wants a file; the site doesn't know the band
    site = FakeGtpTabs()
    assert run(site, conn, tmp_path).sitemaps == 2
    rows = conn.execute("SELECT COUNT(*) FROM gtptabs_index").fetchone()[0]
    assert rows == 14  # the captured sitemaps' artist and song pages, less /ru/ and others

    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)).sitemaps == 0
    assert site.requests == []

    later = run(site, conn, tmp_path, NOW + timedelta(days=31))  # every sitemap answers 304
    assert later.sitemaps == 0 and site.requests == SITEMAPS
    assert conn.execute("SELECT COUNT(*) FROM gtptabs_index").fetchone()[0] == rows


def test_new_keys_read_the_sitemaps_again_even_when_they_are_unchanged(conn, tmp_path, monkeypatch):
    # The sitemaps date from 2015 and answer 304: after a change to caracole's keys
    # (normalize.KEY_VERSION), the copies the cache holds are parsed again with the new ones.
    from caracole import normalize

    add_song(conn, "Soda Stereo", "Signos")
    site = FakeGtpTabs()
    run(site, conn, tmp_path)
    conn.execute("UPDATE gtptabs_index SET artist_key = 'old-' || artist_key")
    monkeypatch.setattr(normalize, "KEY_VERSION", normalize.KEY_VERSION + 1)
    site.requests.clear()

    again = run(site, conn, tmp_path, NOW + timedelta(days=1))
    assert again.sitemaps == 2 and site.requests == SITEMAPS  # each answered 304
    assert conn.execute("SELECT COUNT(*) FROM gtptabs_index WHERE artist_key LIKE 'old-%'").fetchone()[0] == 0
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=2)).sitemaps == 0
    assert site.requests == []


def test_a_build_the_budget_cut_short_goes_on_where_it_stopped(conn, tmp_path):
    add_song(conn, "Soda Stereo", "Signos")
    site = FakeGtpTabs()
    first = run(site, conn, tmp_path, budget=2)
    assert first.budget_exhausted and first.sitemaps == 1
    site.requests.clear()
    second = run(site, conn, tmp_path)
    assert second.sitemaps == 1
    assert site.requests == [INDEX, f"{BASE}/sitemapGoogle6.xml"]


def test_a_sitemap_the_index_no_longer_lists_leaves_the_index(conn, tmp_path):
    add_song(conn, "Soda Stereo", "Signos")
    site = FakeGtpTabs()
    run(site, conn, tmp_path)
    one_child = site.pages[INDEX][1].replace(
        "<sitemap><loc>http://gtptabs.com/sitemapGoogle6.xml</loc><lastmod>2015-06-02</lastmod></sitemap>", "")
    site.pages[INDEX] = (200, one_child, {"Content-Type": "text/xml", "ETag": '"new"'})
    run(site, conn, tmp_path, NOW + timedelta(days=31))
    assert [r[0] for r in conn.execute("SELECT DISTINCT sitemap FROM gtptabs_index")] == ["1"]


# --- one song, looked up now (caracole get) ------------------------------------------------------------


def look_up(site, conn, tmp_path, song, now=NOW):
    client = site.client(tmp_path / "cache", now=now)
    try:
        return gtptabs_files(conn, client, tmp_path / "library", now, only={song.id}, refresh_index=False)
    finally:
        client.close()


def test_a_lookup_asks_about_its_own_song_alone_and_leaves_the_sitemaps_to_the_nightly_run(conn, tmp_path):
    song = add_song(conn, "Blur", "Beetlebum")
    other = add_song(conn, "Blur", "Song 2")
    site = FakeGtpTabs(files={26: gp_file(b"v3.00"), 12: gp_file()})
    assert look_up(site, conn, tmp_path, song) == GtpTabsStats() and site.requests == []  # no index to look in

    run(site, conn, tmp_path, budget=3)  # the nightly run indexes the sitemaps, and spends its budget
    site.requests.clear()
    stats = look_up(site, conn, tmp_path, song, NOW + timedelta(days=40))  # the index is due: the night's work
    assert (stats.tried, stats.kept, stats.sitemaps) == (1, 1, 0)
    assert site.requests == [BLUR, download(26)]
    assert kept_files(conn, other.id) == []


def test_a_song_given_a_file_while_the_pass_ran_gets_no_other(conn, tmp_path, monkeypatch):
    # A lookup the nightly run let go first, in one of its pauses, downloaded the song a file.
    from caracole import gtptabs_fetch

    songs = [add_song(conn, "Blur", "Beetlebum", added_at="2026-10-02T00:00:00Z"), add_song(conn, "Blur", "Song 2")]
    real = gtptabs_fetch._look_up
    others = []

    def looked_up_meanwhile(run, song, index):
        if not others:  # while the pass waited before its first song, a lookup filed the other one a file
            other = next(s for s in songs if s.id != song.id)
            vid = upsert_version(conn, provider="gtptabs", tab_id="999", song_id=other.id, slot="guitar",
                                 kind="guitar-pro", rating=0, votes=0, version=1, label=None,
                                 url=f"{BASE}/tabs/2/blur/other.html", raw={}, now="x")
            keep_file(conn, tmp_path / "library", song=other, version_id=vid, name="guitar-1.gp5", data=gp_file(),
                      rank=1)
            others.append(other)
        return real(run, song, index)

    monkeypatch.setattr(gtptabs_fetch, "_look_up", looked_up_meanwhile)
    stats = run(FakeGtpTabs(files={26: gp_file(b"v3.00"), 12: gp_file()}), conn, tmp_path)
    assert stats.tried == 1
    assert [f.name for f in kept_files(conn, others[0].id)] == ["guitar-1.gp5"]  # and no second file
