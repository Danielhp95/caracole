import unicodedata

import pytest

from tabarr.lacuerda import (
    BASE_URL,
    artist_slug,
    artist_slug_candidates,
    artist_url,
    version_url,
)

# --- slugs and URLs -------------------------------------------------------


@pytest.mark.parametrize(
    "name,slug",
    [
        ("Joaquín Sabina", "joaquin_sabina"),
        ("Niño", "ninio"),
        ("Soda Stereo", "soda_stereo"),
    ],
)
def test_artist_slug(name, slug):
    assert artist_slug(name) == slug


@pytest.mark.parametrize(
    "name,slug",
    [
        # Seen on the real pages: "&" is removed but both spaces stay.
        ("Fito & Fitipaldis", "fito__fitipaldis"),
        # A leading article is dropped from artist slugs.
        ("Las Pastillas del Abuelo", "pastillas_del_abuelo"),
        ("Los Huayra", "huayra"),
        ("Las Pelotas", "pelotas"),
        # Articles inside the name stay.
        ("Ciro y los Persas", "ciro_y_los_persas"),
        ("Manuel García", "manuel_garcia"),
        ("Attaque 77", "attaque_77"),
    ],
)
def test_artist_slug_follows_the_real_pages(name, slug):
    assert artist_slug(name) == slug


def test_artist_slug_handles_capital_and_decomposed_enie():
    assert artist_slug("PEÑA") == "penia"
    assert artist_slug(unicodedata.normalize("NFD", "Niño")) == "ninio"


@pytest.mark.parametrize(
    "name,slug",
    [
        ("Guns N' Roses", "guns_n_roses"),
        ("AC/DC", "acdc"),
        ("Ska-P", "skap"),
        ("Fontaines D.C.", "fontaines_dc"),
        ("  Soda   Stereo ", "soda_stereo"),
    ],
)
def test_artist_slug_removes_punctuation(name, slug):
    assert artist_slug(name) == slug


def test_artist_slug_keeps_an_article_that_is_the_whole_name():
    assert artist_slug("The The") == "the"
    assert artist_slug("La") == "la"


def test_artist_slug_of_a_non_latin_name_is_empty():
    assert artist_slug("宋冬野") == ""


def test_artist_slug_candidates_try_the_article_and_the_ampersand():
    assert artist_slug_candidates("Soda Stereo") == ("soda_stereo",)
    assert artist_slug_candidates("La Oreja de Van Gogh") == (
        "oreja_de_van_gogh",
        "la_oreja_de_van_gogh",
    )
    assert artist_slug_candidates("Fito y Fitipaldis") == ("fito_y_fitipaldis", "fito__fitipaldis")
    assert artist_slug_candidates("Fito & Fitipaldis") == ("fito__fitipaldis", "fito_y_fitipaldis")
    assert artist_slug_candidates("宋冬野") == ()


def test_artist_url():
    assert BASE_URL == "https://acordes.lacuerda.net"
    assert artist_url("soda_stereo") == "https://acordes.lacuerda.net/soda_stereo/"


def test_artist_url_refuses_an_empty_slug():
    with pytest.raises(ValueError):
        artist_url("")


def test_version_url():
    assert version_url("soda_stereo", "de_musica_ligera", 1) == (
        "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera.shtml"
    )
    assert version_url("soda_stereo", "de_musica_ligera", 3) == (
        "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera-3.shtml"
    )
    assert version_url("soda_stereo", "de_musica_ligera", 12).endswith("/de_musica_ligera-12.shtml")


@pytest.mark.parametrize("artist,song,n", [("soda_stereo", "x", 0), ("", "x", 1), ("soda_stereo", "", 2)])
def test_version_url_refuses_bad_arguments(artist, song, n):
    with pytest.raises(ValueError):
        version_url(artist, song, n)
