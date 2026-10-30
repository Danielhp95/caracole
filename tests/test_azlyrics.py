"""azlyrics.py: its addresses and its two kinds of page, from the live markup with invented lyrics."""

import re
from dataclasses import replace

import pytest
from helpers.azlyrics_site import artist_page, fixture, lyrics_page

from caracole.azlyrics import (
    ArtistPage,
    AzLyricsParseError,
    SongLink,
    artist_url,
    parse_artist,
    parse_lyrics,
    pick_song,
)
from caracole.http import Response

ARTIST_URL = "https://www.azlyrics.com/p/pomme.html"
SONG_URL = "https://www.azlyrics.com/lyrics/pomme/mononoke.html"


def page(text: str, url: str = ARTIST_URL) -> Response:
    return Response(url, 200, text.encode("utf-8"))


@pytest.mark.parametrize(("name", "address"), [
    ("pomme", "https://www.azlyrics.com/p/pomme.html"),
    ("Pablo Alborán", "https://www.azlyrics.com/p/pabloalboran.html"),
    ("The Police", "https://www.azlyrics.com/p/police.html"),
    ("Panic! At The Disco", "https://www.azlyrics.com/p/panicatthedisco.html"),
    ("Paddy And The Rats", "https://www.azlyrics.com/p/paddyandtherats.html"),
    ("P1Harmony", "https://www.azlyrics.com/p/p1harmony.html"),
    ("Przyłu", "https://www.azlyrics.com/p/przylu.html"),
    ("Theory", "https://www.azlyrics.com/t/theory.html"),
    ("50 Cent", "https://www.azlyrics.com/19/50cent.html"),
])
def test_an_artists_page_is_their_name_in_letters_and_digits_under_its_first(name, address):
    assert artist_url(name) == address


def test_a_name_with_nothing_to_write_in_an_address_has_no_page():
    assert artist_url("!!!") is None
    assert artist_url("") is None


def test_an_artist_page_gives_its_name_and_the_songs_it_links():
    found = parse_artist(page(artist_page()))
    assert found.name == "Pomme"
    assert SongLink("mononoke", SONG_URL) in found.songs
    assert SongLink("J'suis Pas Dupe", "https://www.azlyrics.com/lyrics/pomme/jsuispasdupe.html") in found.songs


def test_a_song_on_another_artists_page_is_linked_there():
    found = parse_artist(page(artist_page()))
    assert SongLink("Ma Meilleure Ennemie", "https://www.azlyrics.com/lyrics/stromae/mameilleureennemie.html") in found.songs


def test_an_instrumental_row_with_no_link_and_the_scripts_list_are_no_songs():
    found = parse_artist(page(artist_page()))
    assert "Chapelle" not in [s.title for s in found.songs]
    assert [s.title for s in found.songs].count("mononoke") == 1
    assert not any("songlist" in s.url for s in found.songs)
    assert len(found.songs) == 6


@pytest.mark.parametrize("broken", [
    "<html><body>a maintenance notice</body></html>",
    artist_page().replace("<strong>Pomme Lyrics</strong>", "<strong>Pomme</strong>"),
    artist_page().replace('id="listAlbum"', 'id="another"'),
])
def test_an_artist_page_that_isnt_one_is_a_parse_error_never_a_page_with_no_songs(broken):
    with pytest.raises(AzLyricsParseError):
        parse_artist(page(broken))


def test_the_lyrics_are_the_text_after_the_sites_notice_a_line_a_break():
    assert parse_lyrics(page(lyrics_page(), SONG_URL)) == (
        "[Couplet 1]\n"
        "Des mots inventés pour ce test\n"
        "Rien & personne n'a chanté ça\n"
        "\n"
        "L'été n'existe qu'ici\n"
        "Et s'arrête là"
    )


def test_windows_line_ends_read_the_same():
    assert parse_lyrics(page(lyrics_page().replace("\n", "\r\n"), SONG_URL)) == parse_lyrics(page(lyrics_page(), SONG_URL))


@pytest.mark.parametrize("broken", [
    "<html><body>a maintenance notice</body></html>",
    re.sub(r"<!-- Usage of.*?-->.*?</div>", "<!-- Usage of azlyrics.com content is prohibited -->\n<br>\n</div>",
           lyrics_page(), flags=re.S),
    lyrics_page().replace("<!-- Usage of", "<!-- A notice of"),
])
def test_a_lyrics_page_with_none_is_a_parse_error_never_empty_lyrics(broken):
    with pytest.raises(AzLyricsParseError):
        parse_lyrics(page(broken, SONG_URL))


POMME = ArtistPage("Pomme", (
    SongLink("Mono", "https://www.azlyrics.com/lyrics/pomme/mono.html"),
    SongLink("Mononoke (Live)", "https://www.azlyrics.com/lyrics/pomme/mononokelive.html"),
    SongLink("mononoke", SONG_URL),
))


def test_the_song_is_the_line_of_its_title():
    assert pick_song(POMME, artist="pomme", title="Mononoke").url == SONG_URL


def test_a_title_spelled_a_little_differently_still_fits():
    assert pick_song(POMME, artist="pomme", title="Monoke").title == "mononoke"


def test_no_line_of_the_title_is_no_song():
    assert pick_song(POMME, artist="pomme", title="Grandiose") is None


def test_another_artists_page_is_no_song_whatever_its_titles():
    assert pick_song(replace(POMME, name="Mononoke Band"), artist="pomme", title="mononoke") is None


def test_a_remix_is_only_a_song_that_says_it_is_one():
    both = ArtistPage("Pomme", (
        SongLink("Ma Meilleure Ennemie (Coldplay Remix)", "https://www.azlyrics.com/lyrics/stromae/remix.html"),
        SongLink("Ma Meilleure Ennemie", "https://www.azlyrics.com/lyrics/stromae/song.html"),
    ))
    assert pick_song(both, artist="Pomme", title="Ma Meilleure Ennemie").url.endswith("/song.html")
    assert pick_song(both, artist="Pomme", title="Ma Meilleure Ennemie (Coldplay Remix)").url.endswith("/remix.html")


def test_the_block_page_is_kept_as_the_site_words_it():
    assert "unusual activity from your IP address" in fixture("block.html")
