"""harptabs_index.py: harptabs.com's artist pages read into a local index, a batch at a time or one now.

The site is ``FakeHarpTabs`` (helpers/harptabs_site.py) behind a real ``PoliteClient``: the sitemap and
Billy Joel's artist page caracole's own user agent got, trimmed, and artist pages made from it. The
cache, the budget and robots.txt are the client's real behaviour.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from conftest import add_song
from helpers.harptabs_site import BASE, NOW, SITEMAP, FakeHarpTabs, artist_page

from caracole import normalize
from caracole.harptabs import ArtistPage, ListedTab
from caracole.harptabs_index import (
    ArtistPassStats,
    IndexState,
    artist_pass,
    artist_paths,
    ensure_current_keys,
    index_state,
    read_artist,
    store_artist_page,
)
from caracole.http import BudgetExhausted, ProviderBlocked
from caracole.overrides import Overrides

BEATLES, BILLY, VALENS = (f"{BASE}/artist/50/the-beatles", f"{BASE}/artist/1178/billy-joel",
                          f"{BASE}/artist/7829/ritchie-valens")


def site_of_three() -> FakeHarpTabs:
    """The sitemap's three artists with a page each: Billy Joel's the captured one (7 tabs), the others made."""
    site = FakeHarpTabs()
    site.page("artist/50/the-beatles", artist_page("the beatles", [(172, "yesterday", "Yesterday")], count=40))
    site.page("artist/7829/ritchie-valens", artist_page("Ritchie Valens", [(89, "la-bamba", "La Bamba", "57k")]))
    return site


def run(site: FakeHarpTabs, conn, tmp_path: Path, now=NOW, *, budget=20, **kw) -> ArtistPassStats:
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        return artist_pass(conn, client, now, **kw)
    finally:
        client.close()


def tabs_of(conn, path: str) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT tab_id, title, song_key, harp_key, views, place FROM harptabs_artist_tabs WHERE artist = ? "
        "ORDER BY place", (path,))]


def test_a_pass_reads_the_sitemap_then_each_artists_page_in_the_sitemaps_order(conn, tmp_path):
    site = site_of_three()

    stats = run(site, conn, tmp_path)

    assert site.requests == [SITEMAP, BEATLES, BILLY, VALENS]  # by the site's ids, as the sitemap lists them
    assert stats == ArtistPassStats(sitemaps=1, read=3)
    assert index_state(conn) == IndexState(artists=3, read=3, tabs=9)
    assert [tuple(r) for r in conn.execute(
        "SELECT path, page_id, key, name, tabs, read_at FROM harptabs_artists ORDER BY page_id")] == [
        ("artist/50/the-beatles", 50, "beatles", "the beatles", 40, "2026-10-27T03:30:00Z"),
        ("artist/1178/billy-joel", 1178, "billy-joel", "billy joel", 98, "2026-10-27T03:30:00Z"),
        ("artist/7829/ritchie-valens", 7829, "ritchie-valens", "Ritchie Valens", 1, "2026-10-27T03:30:00Z"),
    ]
    # Each tab with the song its title names, the harp's key, its views and its place on the page.
    assert tabs_of(conn, "artist/1178/billy-joel")[:3] == [
        (25, "piano man", "piano-man", "C", 1_100_000, 0),
        (23862, "Piano Man (C Harmonica)", "piano-man", "C", 574_000, 1),
        (9925, "((((Piano Man (Harmonica Intro)", "piano-man", None, 177_000, 2),
    ]


def test_the_artists_of_your_songs_are_read_first(conn, tmp_path):
    add_song(conn, "Ritchie Valens", "La Bamba")
    add_song(conn, "Billy Joel", "Vienna")
    site = site_of_three()

    run(site, conn, tmp_path)

    assert site.requests == [SITEMAP, BILLY, VALENS, BEATLES]


def test_an_ignored_songs_artist_waits_its_turn(conn, tmp_path):
    song = add_song(conn, "Ritchie Valens", "La Bamba")
    site = site_of_three()

    run(site, conn, tmp_path, overrides=Overrides(ignore=frozenset({song.key})))

    assert site.requests == [SITEMAP, BEATLES, BILLY, VALENS]


def test_a_pass_the_budget_cuts_short_goes_on_where_it_stopped_the_next_time(conn, tmp_path):
    site = site_of_three()

    first = run(site, conn, tmp_path, budget=2)
    assert first == ArtistPassStats(sitemaps=1, read=1, budget_exhausted=True)
    assert site.requests == [SITEMAP, BEATLES]
    assert index_state(conn) == IndexState(artists=3, read=1, tabs=1)

    second = run(site, conn, tmp_path, NOW + timedelta(hours=1), budget=2)
    assert second == ArtistPassStats(read=2)
    assert site.requests[2:] == [BILLY, VALENS]  # the sitemap is fresh, and the Beatles were read
    assert index_state(conn).complete


def test_a_page_is_read_again_after_30_days_and_not_before(conn, tmp_path):
    site = site_of_three()
    run(site, conn, tmp_path)
    site.requests.clear()

    assert run(site, conn, tmp_path, NOW + timedelta(days=10)) == ArtistPassStats()
    assert site.requests == []

    site.page("artist/7829/ritchie-valens", artist_page("Ritchie Valens", [(89, "la-bamba", "La Bamba"),
                                                                           (90, "donna", "Donna")]))
    later = NOW + timedelta(days=31)
    assert run(site, conn, tmp_path, later) == ArtistPassStats(sitemaps=1, read=3)
    assert site.requests == [SITEMAP, BEATLES, BILLY, VALENS]  # asked again past the cache
    assert [t[1] for t in tabs_of(conn, "artist/7829/ritchie-valens")] == ["La Bamba", "Donna"]


def test_an_artist_page_gone_keeps_no_tab_and_is_not_asked_again_for_30_days(conn, tmp_path):
    site = site_of_three()
    run(site, conn, tmp_path)
    site.page("artist/1178/billy-joel", "<html><body>Not found</body></html>", status=404)

    stats = run(site, conn, tmp_path, NOW + timedelta(days=31))

    assert stats == ArtistPassStats(sitemaps=1, read=3, gone=1)
    assert tabs_of(conn, "artist/1178/billy-joel") == []
    assert tuple(conn.execute("SELECT name, tabs FROM harptabs_artists WHERE path = 'artist/1178/billy-joel'"
                              ).fetchone()) == ("", 0)
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=32)) == ArtistPassStats()
    assert site.requests == []


def test_a_page_that_wont_parse_is_an_error_its_tabs_stay_and_it_is_asked_for_next_time(conn, tmp_path):
    site = site_of_three()
    run(site, conn, tmp_path)
    site.page("artist/1178/billy-joel", "<html><body><p>Down for maintenance</p></body></html>")
    later = NOW + timedelta(days=31)

    stats = run(site, conn, tmp_path, later)

    assert stats == ArtistPassStats(sitemaps=1, read=2, errors=1)
    assert len(tabs_of(conn, "artist/1178/billy-joel")) == 7  # an error is never an artist without tabs
    site.requests.clear()
    run(site, conn, tmp_path, later + timedelta(hours=1))
    assert site.requests == [BILLY]  # its cached copy won't parse: asked once more, past the cache


def test_a_block_stops_the_pass_and_propagates(conn, tmp_path):
    site = site_of_three()
    site.page("artist/1178/billy-joel", "Forbidden", status=403)

    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)

    assert site.requests == [SITEMAP, BEATLES, BILLY]
    assert index_state(conn) == IndexState(artists=3, read=1, tabs=1)


def test_a_sitemap_that_errs_leaves_the_artists_it_listed_to_be_read(conn, tmp_path):
    site = site_of_three()
    run(site, conn, tmp_path, budget=1)  # the sitemap alone
    site.pages[SITEMAP] = (500, "oops", {})
    later = NOW + timedelta(days=31)

    stats = run(site, conn, tmp_path, later)

    assert stats == ArtistPassStats(read=3, errors=1, sitemap_error=True)
    assert site.requests[1:] == [SITEMAP, BEATLES, BILLY, VALENS]


def test_an_empty_index_and_a_spent_budget_ask_for_nothing_more(conn, tmp_path):
    site = site_of_three()
    assert run(site, conn, tmp_path, budget=0) == ArtistPassStats(budget_exhausted=True)
    assert site.requests == []


def test_one_artists_page_now_and_once_in_30_days(conn, tmp_path):
    site = site_of_three()
    run(site, conn, tmp_path, budget=1)  # the sitemap
    client = site.client(tmp_path / "cache", budget=6)
    try:
        page = read_artist(conn, client, "artist/1178/billy-joel", NOW)
        again = read_artist(conn, client, "artist/1178/billy-joel", NOW + timedelta(days=29))
    finally:
        client.close()
    assert page is not None and (page.name, page.tabs, len(page.listed)) == ("billy joel", 98, 7)
    assert again == page
    assert site.requests[1:] == [BILLY]  # read within 30 days: the cache's copy
    assert index_state(conn) == IndexState(artists=3, read=1, tabs=7)


def test_one_artists_page_gone_is_none(conn, tmp_path):
    site = site_of_three()
    site.page("artist/50/the-beatles", "<html>gone</html>", status=404)
    client = site.client(tmp_path / "cache")
    try:
        assert read_artist(conn, client, "artist/50/the-beatles", NOW) is None
    finally:
        client.close()


def test_one_artists_page_with_the_budget_spent_is_no_answer(conn, tmp_path):
    client = site_of_three().client(tmp_path / "cache", budget=0)
    try:
        with pytest.raises(BudgetExhausted):
            read_artist(conn, client, "artist/1178/billy-joel", NOW)
    finally:
        client.close()


def test_an_artists_pages_by_name_by_path_or_by_address(conn, tmp_path):
    run(site_of_three(), conn, tmp_path, budget=1)  # the sitemap
    assert artist_paths(conn, "Billy Joel") == ["artist/1178/billy-joel"]
    assert artist_paths(conn, "The Beatles") == artist_paths(conn, "beatles") == ["artist/50/the-beatles"]
    assert artist_paths(conn, "artist/7829/ritchie-valens") == ["artist/7829/ritchie-valens"]
    assert artist_paths(conn, f"{BASE}/artist/7829/ritchie-valens") == ["artist/7829/ritchie-valens"]
    assert artist_paths(conn, "harptabs.com/artist/7829/ritchie-valens") == ["artist/7829/ritchie-valens"]
    assert artist_paths(conn, "Nobody") == artist_paths(conn, "artist/9/nobody") == []


def test_a_change_of_caracoles_keys_makes_the_songs_keys_again_from_the_titles(conn, monkeypatch):
    store_artist_page(conn, "artist/1178/billy-joel", ArtistPage("billy joel", 1, (
        ListedTab(25, "tab/25/piano-man", "Piano Man (Intro)"),)), NOW)
    conn.execute("UPDATE harptabs_artist_tabs SET song_key = 'old'")
    assert ensure_current_keys(conn) == 0  # made with the keys of now: nothing to do
    monkeypatch.setattr(normalize, "KEY_VERSION", normalize.KEY_VERSION + 1)
    assert ensure_current_keys(conn) == 1
    assert conn.execute("SELECT song_key FROM harptabs_artist_tabs").fetchone()[0] == "piano-man"
    assert ensure_current_keys(conn) == 0
