import unicodedata
from pathlib import Path

import pytest

from tabarr.http import ProviderError
from tabarr.lacuerda import (
    BASE_URL,
    LaCuerdaParseError,
    LCSong,
    artist_slug,
    artist_slug_candidates,
    artist_url,
    best_acordes_version,
    parse_artist_page,
    parse_lcd,
    version_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "lacuerda"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")

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


# --- lcd codes and the best acordes version --------------------------------


def _song(lcd: str, slug: str = "cancion", title: str = "Canción") -> LCSong:
    types, ranking = parse_lcd(lcd)
    return LCSong(slug=slug, title=title, types=types, ranking=ranking)


def test_parse_lcd():
    assert parse_lcd("RHRTTTDTB-314865972") == ("RHRTTTDTB", (3, 1, 4, 8, 6, 5, 9, 7, 2))


def test_parse_lcd_reads_more_than_nine_versions_as_base36():
    # No real page listed more than nine versions, so base 36 is an assumption.
    assert parse_lcd("RTRTRTRTRTR-a1b23456789") == (
        "RTRTRTRTRTR",
        (10, 1, 11, 2, 3, 4, 5, 6, 7, 8, 9),
    )
    assert parse_lcd("RTRTRTRTRTR-A1B23456789")[1][:3] == (10, 1, 11)


@pytest.mark.parametrize(
    "lcd,expected",
    [
        ("RTRTRTRTRTR-1011123456789", ("RTRTRTRTRTR", tuple(range(1, 12)))),  # lengths disagree
        ("RT-1", ("RT", (1, 2))),
        ("RRR-113", ("RRR", (1, 2, 3))),  # not one rank per version
        ("RR-01", ("RR", (1, 2))),  # there is no version 0
        ("RR-1?", ("RR", (1, 2))),  # not a digit
        ("RT", ("RT", (1, 2))),  # no ranking at all
        ("", ("", ())),
    ],
)
def test_parse_lcd_falls_back_to_version_order(lcd, expected):
    assert parse_lcd(lcd) == expected


def test_parse_lcd_tolerates_case_and_spaces():
    assert parse_lcd(" rht-312 ") == ("RHT", (3, 1, 2))


def test_best_acordes_version():
    assert best_acordes_version(_song("RHRTTTDTB-314865972")) == 3


def test_best_acordes_version_reads_letters_by_version_number():
    # Letter n is the type of version n (the real version page lists them as
    # trcal.push(['R',0,0,1]), (['H',0,0,2]), ...), and the ranking holds version
    # numbers. Reading the letters in rank order instead would pick version 1 here.
    assert best_acordes_version(_song("BR-21")) == 2
    assert best_acordes_version(_song("TBTRTRRT-46783512")) == 4


def test_best_acordes_version_is_none_without_acordes():
    assert best_acordes_version(_song("T-1")) is None
    assert best_acordes_version(_song("TT-21")) is None
    assert best_acordes_version(_song("")) is None


def test_best_acordes_version_skips_ranks_with_no_version():
    assert best_acordes_version(LCSong("cancion", "Canción", "TR", (5, 2, 1))) == 2


# --- the artist page -------------------------------------------------------


@pytest.fixture(scope="module")
def artist_songs() -> list[LCSong]:
    return parse_artist_page(_fixture("artist.html"))


def _by_slug(songs: list[LCSong], slug: str) -> LCSong:
    return next(s for s in songs if s.slug == slug)


def test_parse_artist_page_lists_every_song_in_page_order(artist_songs):
    assert len(artist_songs) == 14
    assert [s.slug for s in artist_songs[:3]] == ["1990", "algun_diasomeday", "angel_electrico"]
    assert artist_songs[-1].slug == "un_millon_de_anios_luz"


def test_parse_artist_page_ignores_the_other_lists(artist_songs):
    # The sidebar, the filter bar, the extras and the suggested artists are lists too.
    slugs = {s.slug for s in artist_songs}
    assert "tratame_suavemente" not in slugs
    assert "huayra" not in slugs


def test_parse_artist_page_titles_drop_the_acordes_label(artist_songs):
    assert _by_slug(artist_songs, "de_musica_ligera").title == "De Música Ligera"
    assert _by_slug(artist_songs, "algun_diasomeday").title == "Algun día"
    assert _by_slug(artist_songs, "picnic_en_el_4o_b").title == "Pic-Nic en el 4o. B"
    assert _by_slug(artist_songs, "1990").title == "1990"
    assert (
        _by_slug(artist_songs, "cuando_pase_el_temblor_unplugged").title
        == "Cuando pase el temblor (unplugged)"
    )


def test_parse_artist_page_lcd(artist_songs):
    song = _by_slug(artist_songs, "de_musica_ligera")
    assert song == LCSong(
        "de_musica_ligera", "De Música Ligera", "RHRTTTDTB", (3, 1, 4, 8, 6, 5, 9, 7, 2)
    )
    assert best_acordes_version(song) == 3


def test_parse_artist_page_finds_songs_without_acordes(artist_songs):
    no_acordes = [s.slug for s in artist_songs if best_acordes_version(s) is None]
    assert no_acordes == ["disco_eterno_unplugged", "telaranias"]


def test_parse_artist_page_keeps_every_type_letter(artist_songs):
    assert set("".join(s.types for s in artist_songs)) == set("RTBKDH")


def test_parse_artist_page_decodes_entities_and_skips_items_without_lcd_or_link():
    html = """<ul id=b_main>
    <li lcd='R-1'><a href="cancion_y_co">Canci&oacute;n &amp; Co <em>acordes</em></a></li>
    <li><a href="sin_lcd">Sin lcd <em>acordes</em></a></li>
    <li lcd='T-1'>sin enlace</li>
    <li lcd='RT-21'><a href="/otra_banda/otra">Otra <em>acordes</em></a></li>
    </ul>"""
    songs = parse_artist_page(html)
    assert [(s.slug, s.title) for s in songs] == [("cancion_y_co", "Canción & Co"), ("otra", "Otra")]


def test_parse_artist_page_with_an_empty_list():
    assert parse_artist_page("<ul id=b_main class=b_main></ul>") == []


def test_a_page_without_the_song_list_is_a_parse_error():
    url = "https://acordes.lacuerda.net/soda_stereo/"
    with pytest.raises(LaCuerdaParseError) as err:
        parse_artist_page(_fixture("song.html"), url=url)
    # A provider error, never "the artist has no songs".
    assert isinstance(err.value, ProviderError)
    assert err.value.provider == "lacuerda"
    assert err.value.url == url
