"""gtptabs.com's pages, read: sitemap URLs into index rows, artist pages into tabs, files by their bytes.

The pages are the captured ones in tests/fixtures/gtptabs/; the files are synthetic
(helpers/gtptabs_site.py).
"""

from __future__ import annotations

import pytest
from helpers.gtptabs_site import fixture, gp7_file, gp_file, gpx_file, ptb_file

from caracole.gtptabs import (
    GtpTab,
    GtpTabsParseError,
    IndexRow,
    artist_keys,
    download_url,
    page_url,
    parse_artist_page,
    parse_page_url,
    sitemap_name,
    sniff,
    title_key,
)
from caracole.http import ProviderError
from caracole.ug.sitemap import iter_locs

BLUR = "https://gtptabs.com/tabs/2/blur.html"


# --- sitemaps ---------------------------------------------------------------------------------


def test_an_artist_page_and_a_song_page_are_index_rows():
    assert parse_page_url("http://gtptabs.com/tabs/2/blur.html") == IndexRow(
        path="tabs/2/blur.html", artist_path="tabs/2/blur.html", artist_key="blur", title_key="", base_key="")
    assert parse_page_url("http://gtptabs.com/tabs/2/blur/country-house.html") == IndexRow(
        path="tabs/2/blur/country-house.html", artist_path="tabs/2/blur.html", artist_key="blur",
        title_key="country-house", base_key="country-house")


def test_a_trailing_number_is_read_both_as_part_of_the_title_and_as_a_version():
    # "Song 2 (2)" is song-2-2.html, and "Song 2" itself song-2.html: the slug alone can't tell.
    row = parse_page_url("http://gtptabs.com/tabs/2/blur/song-2-2.html")
    assert (row.title_key, row.base_key) == ("song-2-2", "song-2")
    row = parse_page_url("http://gtptabs.com/tabs/2/blur/song-2.html")
    assert (row.title_key, row.base_key) == ("song-2", "song")


def test_the_site_writes_the_at_the_end_of_an_artist_slug():
    # "Beatles, The" is beatles-the; the key is the one caracole gives "The Beatles".
    assert parse_page_url("http://gtptabs.com/tabs/2/beatles-the/yesterday-13.html") == IndexRow(
        path="tabs/2/beatles-the/yesterday-13.html", artist_path="tabs/2/beatles-the.html",
        artist_key="beatles", title_key="yesterday-13", base_key="yesterday")
    assert parse_page_url("http://gtptabs.com/tabs/18/rolling-stones-the/tumbling-dice-3.html").artist_key == (
        "rolling-stones")
    assert parse_page_url("http://gtptabs.com/tabs/20/the-the.html").artist_key == "the"


@pytest.mark.parametrize("url", [
    "http://gtptabs.com/",
    "http://gtptabs.com/tabs/2/",  # a letter's list of artists
    "http://gtptabs.com/news/first.html",
    "http://gtptabs.com/advertisement.html",  # closed by robots.txt anyway
    "http://gtptabs.com/ru/tabs/2/blur/country-house.html",  # /ru/: closed by robots.txt
    "https://example.com/tabs/2/blur.html",
    "http://gtptabs.com/tabs/2/blur/a/b.html",
    # Every slug in the sitemaps is lowercase letters, digits and hyphens: anything else, which
    # could break a link on the to-do page, is no page caracole reads.
    "http://gtptabs.com/tabs/2/blur/song-2)[x](y.html",
    "http://gtptabs.com/tabs/2/Blur.html",
    "http://gtptabs.com/tabs/2/blur/song%202.html",
])
def test_other_urls_are_no_index_rows(url):
    assert parse_page_url(url) is None


def test_the_captured_sitemaps_hold_these_rows():
    rows = [r for r in map(parse_page_url, iter_locs(fixture("sitemap1.xml").encode())) if r is not None]
    assert [r.path for r in rows] == [
        "tabs/2/blur.html", "tabs/2/beatles-the.html", "tabs/10/john-elton.html",
        "tabs/2/blur/country-house.html", "tabs/2/blur/song-2.html", "tabs/2/blur/song-2-2.html",
        "tabs/2/blur/beetlebum.html", "tabs/2/blur/girls-and-boys-bassline.html",
        "tabs/2/beatles-the/yesterday.html", "tabs/10/john-elton/crocodile-rock.html",
    ]
    rows = [r for r in map(parse_page_url, iter_locs(fixture("sitemap6.xml").encode())) if r is not None]
    assert [(r.artist_key, r.base_key) for r in rows] == [
        ("beatles", "yesterday"), ("beatles", "here-comes-the-sun"), ("rolling-stones", "tumbling-dice"),
        ("dobson-ewan", "time-8-string"),
    ]


def test_sitemap_names_and_urls():
    assert sitemap_name("http://gtptabs.com/sitemapGoogle6.xml") == "6"
    assert sitemap_name("https://gtptabs.com/sitemapGoogle1.xml") == "1"
    assert sitemap_name("http://gtptabs.com/sitemapYandex.xml") is None
    assert sitemap_name("https://example.com/sitemapGoogle1.xml") is None
    assert page_url("tabs/2/blur.html") == BLUR
    assert download_url(58155) == "https://gtptabs.com/tabs/download/58155.html"


# --- songs' names --------------------------------------------------------------------------------


@pytest.mark.parametrize("name, key", [
    ("Blur", "blur"),
    ("The Beatles", "beatles"),
    ("Elton John", "john-elton"),  # the site files people as "John, Elton"
    ("Ewan Dobson", "dobson-ewan"),
    ("Stevie Ray Vaughan", "vaughan-stevie-ray"),
    ("Simon & Garfunkel", "simon-garfunkel"),
    ("Mötley Crüe", "motley-crue"),
])
def test_an_artist_name_has_the_key_the_sites_slug_has(name, key):
    assert key in artist_keys(name)


def test_a_name_without_letters_has_no_key():
    assert artist_keys("!!!") == ()


def test_title_keys_drop_version_suffixes():
    assert title_key("Song 2 - 2012 Remaster") == "song-2"
    assert title_key("Coffee & TV") == title_key("Coffee And Tv") == "coffee-tv"


# --- artist pages -----------------------------------------------------------------------------------


def test_an_artist_page_lists_every_tab_with_its_download_id():
    tabs = parse_artist_page(fixture("artist.html"), BLUR)
    assert [t.tab_id for t in tabs] == [26, 58155, 89061, 18, 79720, 2, 79723, 9, 79718, 12, 15, 79714, 36, 39]
    assert tabs[0] == GtpTab(tab_id=26, title="Beetlebum", version=1, path="tabs/2/blur/beetlebum.html",
                             format="gp3", stars=4, size_kb=30.71, instruments=())
    assert tabs[1] == GtpTab(tab_id=58155, title="Beetlebum", version=2, path="tabs/2/blur/beetlebum-2.html",
                             format="gpx", stars=2, size_kb=50.48,
                             instruments=("electric guitar", "acoustic guitar", "bass", "drums", "vocals"))


def test_a_version_number_in_brackets_is_no_part_of_the_title():
    tabs = parse_artist_page(fixture("artist.html"), BLUR)
    songs = [(t.title, t.version) for t in tabs if t.title.startswith("Song 2")]
    assert songs == [("Song 2", 1), ("Song 2", 2), ("Song 2", 8), ("Song 2 (Live)", 1)]


def test_a_tab_without_a_guitar_part_says_so():
    # Instruments are listed only for newer uploads: an old one, listing none, may have one.
    by_id = {t.tab_id: t for t in parse_artist_page(fixture("artist.html"), BLUR)}
    assert not by_id[79718].guitar  # Oily Water (2): bass, drums and vocals
    assert not by_id[79714].guitar  # Song 2 (8): bass and drums
    assert by_id[58155].guitar and by_id[26].guitar
    assert by_id[79723].size_kb == 3.27  # "Added by:" after the size


def test_a_page_without_the_artists_list_is_a_parse_error_never_a_miss():
    with pytest.raises(GtpTabsParseError) as e:
        parse_artist_page("<html><body><h1>Site maintenance</h1></body></html>", BLUR)
    assert isinstance(e.value, ProviderError) and e.value.url == BLUR


def test_an_artist_with_no_tabs_left_has_an_empty_list():
    page = ('<html><body><div class="autorInfo"><h1>Artist "Nobody"</h1></div>'
            '<div class="autorSongs">\n</div></body></html>')
    assert parse_artist_page(page, BLUR) == []


def test_an_entry_linking_outside_the_tabs_is_left_out():
    page = fixture("artist.html").replace('href="/tabs/2/blur/beetlebum.html"', 'href="/storage/x.gp3"')
    assert 26 not in {t.tab_id for t in parse_artist_page(page, BLUR)}


# --- files ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data, ext", [
    (gp_file(b"v3.00"), ".gp3"),
    (gp_file(b"v4.06"), ".gp4"),
    (gp_file(b"v5.10"), ".gp5"),
    (gpx_file(), ".gpx"),
    (gp7_file(), ".gp"),
    (ptb_file(), ".ptb"),
])
def test_a_file_is_known_by_its_first_bytes(data, ext):
    assert sniff(data) == ext


@pytest.mark.parametrize("data", [
    b"",
    fixture("download_404.html").encode(),
    b"<!DOCTYPE html><html><body>Too many downloads</body></html>",
    gp_file(b"v1.04", word=b"GUITARE"),  # Guitar Pro 1: no format the library files
    gp7_file(score=False),
    b"PK\x03\x04 not really a zip",
    b"\x18FICHIER GUITAR PRO",  # cut short
], ids=["empty", "404-page", "html", "gp1", "zip-without-score", "broken-zip", "cut-short"])
def test_anything_else_is_no_guitar_pro_file(data):
    assert sniff(data) is None
