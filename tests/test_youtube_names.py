"""youtube_names.py: "Artist - Title" guessed from a YouTube video's title and channel, for a pasted link's request.

The shapes are real-world ones: an artist's own upload, a VEVO or "- Topic" channel, Spanish words of the same noise,
a fan's upload whose title names the song first. A guess is only a start: the owner checks it before it is sent.
"""

import pytest

from caracole.youtube_names import clean_channel, guess


@pytest.mark.parametrize("title,channel,expected", [
    ("Radiohead - Creep", "Radiohead", ("Radiohead", "Creep")),
    ("Oasis - Wonderwall (Official Video)", "Oasis", ("Oasis", "Wonderwall")),
    ("Creep", "Radiohead - Topic", ("Radiohead", "Creep")),
    ("Hello", "AdeleVEVO", ("Adele", "Hello")),
    ("Queen – Bohemian Rhapsody (Official Video Remastered)", "Queen Official", ("Queen", "Bohemian Rhapsody")),
    ("Soda Stereo - De Música Ligera (Video Oficial)", "Soda Stereo", ("Soda Stereo", "De Música Ligera")),
    ("Estopa - Como Camarón [Videoclip Oficial] HD", "EstopaVEVO", ("Estopa", "Como Camarón")),
    ("Manu Chao | Clandestino (Letra)", "Manu Chao Official", ("Manu Chao", "Clandestino")),
    ("Rosalía - DESPECHÁ (Official Video)", "RosaliaVEVO", ("Rosalía", "DESPECHÁ")),
    ("Me Gustas Tú (Con Letra)", "Manu Chao", ("Manu Chao", "Me Gustas Tú")),
    ("Vegan Vikings", "Nick Cani", ("Nick Cani", "Vegan Vikings")),
    ("“Bohemian Rhapsody” (Official Lyric Video)", "Queen Official", ("Queen", "Bohemian Rhapsody")),
    ("宋冬野 - 斑马斑马", "宋冬野", ("宋冬野", "斑马斑马")),
    ("Los Prisioneros - El Baile de los que Sobran (En Vivo)", "Los Prisioneros",
     ("Los Prisioneros", "El Baile de los que Sobran (En Vivo)")),  # a version of the song: kept
    ("Daft Punk - Get Lucky (feat. Pharrell Williams) [Official Audio]", "Daft Punk",
     ("Daft Punk", "Get Lucky (feat. Pharrell Williams)")),
    # The owner's example, a fan's upload: the song first, the band after, the channel neither. The plain rule takes
    # the first part for the artist; the owner swaps them in the form.
    ("Somos vikingos veganos - Hyperfanes", "kintanedu", ("Somos vikingos veganos", "Hyperfanes")),
])
def test_a_videos_title_and_channel_give_artist_and_title(title, channel, expected):
    assert guess(title, channel) == expected


def test_a_title_that_names_the_song_first_is_turned_round_when_its_artist_is_known():
    # Known from the library or the offline indexes, read with no request: the band is Hyperfanes.
    def known(name):
        return name == "Hyperfanes"

    assert guess("Somos vikingos veganos - Hyperfanes", "kintanedu", known=known) == ("Hyperfanes",
                                                                                      "Somos vikingos veganos")
    # The channel's name on one side says the same.
    assert guess("Wonderwall - Oasis", "Oasis") == ("Oasis", "Wonderwall")
    # A first part that is a known artist stays first.
    assert guess("Hyperfanes - Vikingos", "x", known=known) == ("Hyperfanes", "Vikingos")


@pytest.mark.parametrize("channel,expected", [
    ("Radiohead - Topic", "Radiohead"), ("AdeleVEVO", "Adele"), ("Queen Official", "Queen"),
    ("Shakira Oficial", "Shakira"), ("Nick Cani", "Nick Cani"), ("VEVO", "VEVO"), ("", ""),
])
def test_a_channels_name_loses_its_label_words(channel, expected):
    assert clean_channel(channel) == expected


def test_no_title_gives_no_guess():
    assert guess("", "") == ("", "")
    assert guess("(Official Video)", "Oasis") == ("Oasis", "")
