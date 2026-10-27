"""harptabs.py: the sitemap's pages as index rows, and a tab page read, from what the site answered caracole."""

from __future__ import annotations

import pytest
from helpers.harptabs_site import BASE, fixture, tab_page

from caracole.harptabs import (
    HarpTab,
    HarpTabsParseError,
    IndexRow,
    page_url,
    parse_page_url,
    parse_tab_page,
    title_key,
)
from caracole.http import robots_disallows
from caracole.ug.sitemap import iter_locs


def test_the_sitemap_gives_its_tabs_by_title_and_its_artists_by_name():
    rows = [r for r in map(parse_page_url, iter_locs(fixture("sitemap.xml").encode())) if r is not None]
    assert rows[:4] == [
        IndexRow("artist/50/the-beatles", "artist", 50, "beatles"),
        IndexRow("artist/1178/billy-joel", "artist", 1178, "billy-joel"),
        IndexRow("artist/7829/ritchie-valens", "artist", 7829, "ritchie-valens"),
        IndexRow("tab/6/silent-night", "tab", 6, "silent-night"),
    ]
    # The site's own pages, its genres, and an artist with no slug (a name in another script) are no rows.
    assert len(rows) == 11
    assert [r.page_id for r in rows if r.key == "piano-man"] == [25, 29525]


@pytest.mark.parametrize("url", [
    f"{BASE}/", f"{BASE}/browse", f"{BASE}/genre/blues", f"{BASE}/artist/4", f"{BASE}/tab/25/piano-man/edit",
    f"{BASE}/tab/25/Piano-Man", "https://example.com/tab/25/piano-man", f"{BASE}/tab/25/piano-man?_rsc=1",
])
def test_any_other_url_is_no_row(url):
    assert parse_page_url(url) is None


def test_a_page_of_the_bare_host_is_one_of_the_sites():
    assert parse_page_url("https://harptabs.com/tab/89/la-bamba") == IndexRow("tab/89/la-bamba", "tab", 89, "la-bamba")
    assert page_url("tab/89/la-bamba") == f"{BASE}/tab/89/la-bamba"


def test_a_songs_title_meets_the_slugs_once_its_version_words_are_gone():
    assert title_key("Piano Man (Live)") == "piano-man"
    assert title_key("Don't Stop") == "dont-stop"


def test_a_tab_page_gives_its_title_artist_tab_and_chips():
    tab = parse_tab_page(fixture("tab_89_la-bamba.html"))
    assert (tab.title, tab.artist, tab.key, tab.harp, tab.difficulty, tab.views, tab.rating) == (
        "La Bamba", "Ritchie Valens", "C", "Diatonic", "Beginner", 57_000, None)
    assert tab.body.startswith("-9 -9 -9  -9  -9  8  7\nPa-ra bai-lar la bam-ba\n")
    assert tab.body.endswith("bam-ba, bam-ba, bam-ba\n")


def test_a_tab_page_with_a_rating_and_no_harp_chip():
    tab = parse_tab_page(fixture("tab_25_piano-man.html"))
    assert (tab.title, tab.artist, tab.key, tab.harp, tab.views, tab.rating) == (
        "piano man", "billy joel", "C", None, 1_100_000, 4.0)
    assert tab.raw() == {"title": "piano man", "artist": "billy joel", "key": "C", "harp": None,
                         "difficulty": "Beginner", "views": 1_100_000, "rating": 4.0}


def test_the_header_names_the_artist_where_the_json_ld_doesnt():
    page = tab_page("Yesterday", "The Beatles").replace('"@type":"MusicComposition"', '"@type":"Thing"')
    assert parse_tab_page(page).artist == "The Beatles" and parse_tab_page(page).title == "Yesterday"


@pytest.mark.parametrize("views, count", [("57k", 57_000), ("974", 974), ("2.5M", 2_500_000), ("", 0), ("lots", 0)])
def test_views_are_counted_as_the_chip_writes_them(views, count):
    assert parse_tab_page(tab_page("Yesterday", "The Beatles", views=views)).views == count


@pytest.mark.parametrize("html", [
    "<html><body><h1>Not here</h1></body></html>",  # no tab
    tab_page("Yesterday", "The Beatles", body="   \n"),  # an empty one
    tab_page("Yesterday", "").replace('href="/artist/1/someone"></a>', ""),  # no artist anywhere
])
def test_a_page_without_a_tab_or_an_artist_is_an_error_never_no_tab(html):
    with pytest.raises(HarpTabsParseError):
        parse_tab_page(html, f"{BASE}/tab/1/x")


def test_robots_txt_closes_its_search_its_api_and_a_pages_react_data():
    for path in ("/search?key=5", "/search", "/api/v1/tabs/25", "/tab/25/piano-man?_rsc=abc", "/tab/25/edit",
                 "/login"):
        assert robots_disallows(f"{BASE}{path}") is not None, path
        assert robots_disallows(f"https://harptabs.com{path}") is not None, path
    for path in ("/sitemap.xml", "/tab/25/piano-man", "/artist/1178/billy-joel", "/robots.txt"):
        assert robots_disallows(f"{BASE}{path}") is None, path


def test_robots_rules_are_the_live_files_disallow_lines():
    lines = [line.split(":", 1)[1].strip() for line in fixture("robots.txt").splitlines()
             if line.startswith("Disallow:")]
    from caracole.http import ROBOTS_DISALLOW

    assert list(ROBOTS_DISALLOW["www.harptabs.com"]) == lines == list(ROBOTS_DISALLOW["harptabs.com"])


def test_a_harp_tab_is_frozen():
    tab = parse_tab_page(fixture("tab_89_la-bamba.html"))
    assert isinstance(tab, HarpTab)
    with pytest.raises(AttributeError):
        tab.title = "x"  # type: ignore[misc]
