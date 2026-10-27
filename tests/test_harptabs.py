"""harptabs.py: the sitemap's pages as index rows, and a tab page read, from what the site answered caracole."""

from __future__ import annotations

import re

import pytest
from helpers.harptabs_site import BASE, artist_page, fixture, tab_page

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


def test_a_tabs_key_joins_a_contractions_end_to_its_word_whichever_way_the_slug_wrote_it():
    # "can-t-help-falling-in-love" and "cant-help-falling-in-love" are one title's slugs: the key is the second,
    # which the title's own key ("Can't Help Falling in Love") and a query typed either way meet.
    for slug in ("can-t-help-falling-in-love", "cant-help-falling-in-love"):
        assert parse_page_url(f"{BASE}/tab/1/{slug}").key == "cant-help-falling-in-love"
    assert parse_page_url(f"{BASE}/tab/2/knockin-on-heaven-s-door").key == "knockin-on-heavens-door"
    assert parse_page_url(f"{BASE}/tab/3/i-m-confessin").key == title_key("I'm Confessin'") == "im-confessin"
    assert parse_page_url(f"{BASE}/tab/4/you-ain-t-goin-nowhere").key == title_key("You Ain't Goin' Nowhere")
    assert parse_page_url(f"{BASE}/artist/5/guns-n-roses").key == "guns-n-roses"  # an artist's: compared hyphens aside


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


def test_a_tab_page_by_unknown_parses_and_names_no_artist():
    # Some tabs are of no known artist: no composer in the JSON-LD, "by Unknown" in the header, linking nowhere.
    tab = parse_tab_page(fixture("tab_29910_knockin-on-heavens-door.html"))
    assert (tab.title, tab.artist, tab.key, tab.views) == ("KNOCKIN ON HEAVENS DOOR...", None, "C", 2_000)
    assert tab.body.startswith("ARMONICA C\n") and "(3)la (3)lo" in tab.body
    assert tab.raw()["artist"] is None


def test_a_line_the_page_breaks_with_a_tag_is_a_line_of_the_tab():
    # The site's editor writes a line as a <p> and breaks one with <br> (Love Me Do's, tab 53: "go to:<br><a>…"), which
    # its <pre> shows as lines apart: a row of holes so broken from its words is two lines, never one.
    page = tab_page("Love Me Do", "Beatles",
                    body="<p>Tabbed by someone<br>-4 -4 5<br/>Love, love me</p><p>4 5</p><p>do</p>\n<p>4</p>")
    assert parse_tab_page(page).body == "Tabbed by someone\n-4 -4 5\nLove, love me\n4 5\ndo\n4\n"


@pytest.mark.parametrize("artist, path", [
    ("Unknown", "artist/1/unknown"), ("?", "artist/4"), ("unknown", "artist/9/x"),
])
def test_the_sites_catch_all_artist_is_no_artist(artist, path):
    assert parse_tab_page(tab_page("Yesterday", artist, artist_path=path)).artist is None


def test_an_artist_the_header_names_with_no_link_is_the_artist():
    page = tab_page("Yesterday", "").replace('<a class="font-medium text-fg transition-colors hover:text-accent-text" '
                                             'href="/artist/1/someone"></a>',
                                             '<span class="font-medium text-fg">The Beatles</span>')
    assert parse_tab_page(page).artist == "The Beatles"


@pytest.mark.parametrize("views, count", [("57k", 57_000), ("974", 974), ("2.5M", 2_500_000), ("", 0), ("lots", 0)])
def test_views_are_counted_as_the_chip_writes_them(views, count):
    assert parse_tab_page(tab_page("Yesterday", "The Beatles", views=views)).views == count


_BY_LINE = re.compile(r"<p[^>]*>by<!-- --> .*?</p>")


@pytest.mark.parametrize("html", [
    "<html><body><h1>Not here</h1></body></html>",  # no tab
    tab_page("Yesterday", "The Beatles", body="   \n"),  # an empty one
    _BY_LINE.sub("", tab_page("Yesterday", "")),  # no artist anywhere, nor a header saying it is unknown
    tab_page("Yesterday", "").replace('href="/artist/1/someone"></a>', 'href="/artist/1/someone"> </a>'),  # "by" no one
    _BY_LINE.sub("", fixture("tab_29910_knockin-on-heavens-door.html")),
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


# --- an artist page ---------------------------------------------------------------------------------------------------


def test_an_artist_page_gives_its_name_how_many_tabs_it_says_and_the_tabs_it_lists():
    from caracole.harptabs import ListedTab, parse_artist_page

    page = parse_artist_page(fixture("artist_1178_billy-joel.html"))
    assert (page.name, page.tabs) == ("billy joel", 98)  # the page's own spelling, and the count its header says
    assert page.listed[:2] == (
        ListedTab(25, "tab/25/piano-man", "piano man", key="C", difficulty="Beginner", views=1_100_000, rating=4.0),
        ListedTab(23862, "tab/23862/piano-man-c-harmonica", "Piano Man (C Harmonica)", key="C", views=574_000),
    )
    # Beside the artist, a card shows the harp's key, a genre ("Rock", "Pop"), both or neither.
    assert [(t.tab_id, t.title, t.key, t.rating) for t in page.listed[2:]] == [
        (9925, "((((Piano Man (Harmonica Intro)", None, 2.9),
        (1256, "Piano Man (Harp Intro)", "C", 2.2),
        (8767, "Vienna!", "Bb", None),
        (2008, "She's Always a Woman", None, None),
        (5751, "New York State Of Mind", "C", None),
    ]
    assert [t.views for t in page.listed] == [1_100_000, 574_000, 177_000, 75_000, 59_000, 32_000, 15_000]


def test_the_sites_catch_all_artist_is_a_page_like_any_other():
    from caracole.harptabs import parse_artist_page

    page = parse_artist_page(fixture("artist_4.html"))
    assert (page.name, page.tabs) == ("?", 41)
    assert [(t.path, t.key, t.difficulty) for t in page.listed] == [
        ("tab/125/dixie", "C", "Beginner"), ("tab/165/oh-danny-boy", None, "Beginner"),
        ("tab/4907/lord-of-the-rings-theme", None, "Beginner")]


@pytest.mark.parametrize("html", [
    "<html><body><h1>Not here</h1></body></html>",  # no header of an artist's page
    "<html><body><main><p>98 tabs</p></main></body></html>",  # no name
])
def test_an_artist_page_without_its_header_is_an_error_never_no_tabs(html):
    from caracole.harptabs import parse_artist_page

    with pytest.raises(HarpTabsParseError):
        parse_artist_page(html, f"{BASE}/artist/1/x")


def test_an_artist_with_no_tab_is_a_page_with_none():
    from caracole.harptabs import parse_artist_page

    html = fixture("artist_4.html")
    head, _, rest = html.partition('<div class="grid')
    empty = head.replace("41 tabs", "0 tabs") + "</div></main></body></html>"
    page = parse_artist_page(empty)
    assert (page.name, page.tabs, page.listed) == ("?", 0, ())


def test_an_artist_page_that_says_they_have_tabs_and_lists_none_it_can_read_is_an_error_never_no_tabs():
    # Its cards changed, say: read as no tab, each page read again would empty the artist's tabs from the index.
    from caracole.harptabs import parse_artist_page

    with pytest.raises(HarpTabsParseError):
        parse_artist_page(artist_page("billy joel", [], count=98), f"{BASE}/artist/1178/billy-joel")
    unreadable = fixture("artist_1178_billy-joel.html").replace('href="/tab/', 'href="/tabs/')
    with pytest.raises(HarpTabsParseError):
        parse_artist_page(unreadable, f"{BASE}/artist/1178/billy-joel")


def test_a_card_that_links_to_no_tab_page_is_left_out():
    from caracole.harptabs import parse_artist_page

    html = fixture("artist_4.html").replace('href="/tab/165/oh-danny-boy"', 'href="/tab/165/Oh Danny"')
    assert [t.tab_id for t in parse_artist_page(html).listed] == [125, 4907]


@pytest.mark.parametrize("title, song", [
    ("piano man", "piano man"),
    ("Piano Man (C Harmonica)", "Piano Man"),
    ("((((Piano Man (Harmonica Intro)", "Piano Man"),
    ("Piano man(THE ACTUAL WAY THE GUY PLAYS )", "Piano man"),
    ("(harmonica riff) piano man", "piano man"),
    ("Piano Man [intro]", "Piano Man"),
    ("Pianoman (Complete)", "Pianoman"),
    ("(Intro)", "(Intro)"),  # nothing left: the title as it is
])
def test_a_tabs_song_is_its_title_less_what_it_says_in_brackets(title, song):
    from caracole.harptabs import song_title

    assert song_title(title) == song


def test_tabs_of_one_song_share_its_key():
    from caracole.harptabs import song_key

    assert {song_key(t) for t in ("piano man", "Piano Man (C Harmonica)", "((((Piano Man (Harmonica Intro)")} == {
        "piano-man"}
    assert song_key("She's Always a Woman") == "shes-always-a-woman"
