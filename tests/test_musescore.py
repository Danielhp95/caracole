"""musescore.com's song pages: their addresses, and which ones a song's title meets."""

from __future__ import annotations

import pytest
from conftest import add_song

from caracole.musescore import (
    MAX_PAGES,
    SITEMAP_INDEX_URL,
    SongPage,
    parse_song_url,
    sitemap_name,
    song_pages,
    title_key,
)

BASE = "https://musescore.com"


def index(conn, *paths: str, sitemap: str = "1") -> None:
    rows = [parse_song_url(f"{BASE}/{p}") for p in paths]
    conn.executemany("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES (?, ?, ?, ?)",
                     [(*row, sitemap) for row in rows])


def test_a_song_page_is_its_id_its_path_and_its_titles_key():
    assert parse_song_url(f"{BASE}/song/dont_look_back_in_anger-680901") == SongPage(
        680901, "song/dont_look_back_in_anger-680901", "dont-look-back-in-anger")
    assert parse_song_url(f"{BASE}/song/dont_look_back_in_anger-680901").url == (
        f"{BASE}/song/dont_look_back_in_anger-680901")


def test_the_titles_key_is_caracoles():
    # A leading "the" goes, as in every key; MuseScore's slugs have no accents or apostrophes
    # ("lideal" is L'idéal), and neither has the key.
    assert parse_song_url(f"{BASE}/song/the_scientist-680304").title_key == "scientist"
    assert parse_song_url(f"{BASE}/song/lideal-364").title_key == "lideal"
    assert title_key("L'idéal") == "lideal"
    assert title_key("The Scientist - 2002 Remaster") == "scientist"


@pytest.mark.parametrize("url", [
    f"{BASE}/song/wonderwall",  # no id
    f"{BASE}/song/wonderwall-680101/",
    f"{BASE}/song/wonderwall-680101?ref=x",
    f"{BASE}/song/Wonderwall-680101",  # the sitemaps write slugs in lowercase
    f"{BASE}/song/won%22der-680101",
    "http://musescore.com/song/wonderwall-680101",
    "https://example.com/song/wonderwall-680101",
    f"{BASE}/user/27/scores/6159957",  # a score, not a song page
    f"{BASE}/artist/oasis-1234",
    f"{BASE}/song/_-680101",  # a slug with no letter or digit has no key
])
def test_other_urls_are_no_song_pages(url):
    assert parse_song_url(url) is None


def test_sitemap_names():
    assert SITEMAP_INDEX_URL == f"{BASE}/sitemaps/song-index.xml"
    assert sitemap_name(f"{BASE}/sitemaps/song-index/sitemap_songs18.xml") == "18"
    assert sitemap_name(f"{BASE}/sitemaps/scores-index/sitemap_scores1.xml") is None
    assert sitemap_name(f"{BASE}/sitemaps/song-index/sitemap_songs18.xml.gz") is None


def test_a_songs_title_meets_the_pages_titles_as_caracoles_keys_do(conn):
    index(conn, "song/dont_look_back_in_anger-680901", "song/wonderwall-680101")
    song = add_song(conn, "Oasis", "Don't Look Back in Anger - Remastered")
    assert [p.url for p in song_pages(conn, song)] == [f"{BASE}/song/dont_look_back_in_anger-680901"]


def test_at_most_three_pages_a_song_oldest_first(conn):
    # Sitemap 1 has nine "Ave Maria" pages: Schubert's, Bach and Gounod's, Caccini's...
    index(conn, "song/ave_maria-18459", "song/ave_maria-1365", "song/ave_maria-9066", "song/ave_maria-4862")
    song = add_song(conn, "Franz Schubert", "Ave Maria")
    assert MAX_PAGES == 3
    assert [p.page_id for p in song_pages(conn, song)] == [1365, 4862, 9066]


def test_a_title_the_index_lacks_has_no_pages(conn):
    index(conn, "song/wonderwall-680101")
    assert song_pages(conn, add_song(conn, "Radiohead", "Creep")) == []
    assert song_pages(conn, add_song(conn, "Nobody", "???")) == []
