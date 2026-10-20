import html as htmllib
import re
import unicodedata
from pathlib import Path

import pytest

from caracole.http import ProviderError
from caracole.lacuerda import (
    BASE_URL,
    LETTERS,
    LaCuerdaParseError,
    LCArtist,
    LCSong,
    Listing,
    artist_slug,
    artist_slug_candidates,
    artist_url,
    best_acordes_version,
    is_missing_artist_page,
    is_spanish,
    listing_path,
    listing_url,
    looks_spanish,
    match_title,
    parse_artist_name,
    parse_artist_page,
    parse_lcd,
    parse_listing_page,
    parse_popularity,
    parse_version_page,
    song_url,
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


@pytest.mark.parametrize(
    "artist,song,n", [("soda_stereo", "x", 0), ("", "x", 1), ("soda_stereo", "", 2)]
)
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
    assert [(s.slug, s.title) for s in songs] == [
        ("cancion_y_co", "Canción & Co"),
        ("otra", "Otra"),
    ]


def test_parse_artist_page_keeps_each_lcd_code_as_written(artist_songs):
    assert _by_slug(artist_songs, "de_musica_ligera").lcd == "RHRTTTDTB-314865972"
    # The raw code is kept even where its ranking is unreadable.
    page = "<ul id=b_main><li lcd='RT-1'><a href='x'>X <em>acordes</em></a></li></ul>"
    (song,) = parse_artist_page(page)
    assert (song.lcd, song.ranking) == ("RT-1", (1, 2))


def test_parse_artist_page_with_an_empty_list():
    assert parse_artist_page("<ul id=b_main class=b_main></ul>") == []


# --- "no such artist" --------------------------------------------------------


# LaCuerda's answer to /zzq_no_such_artist_qqz/, byte for byte: HTTP 200, 54 bytes.
SOFT_404 = "aqui llega:../tabs/z/zzq_no_such_artist_qqz/index.html"


def test_the_soft_404_body_is_a_missing_artist():
    assert len(SOFT_404.encode()) == 54
    assert is_missing_artist_page(SOFT_404)
    assert is_missing_artist_page(SOFT_404 + "\n")


def test_a_small_page_without_a_song_list_is_not_a_soft_404():
    # A PHP or database error page is a server error, which must never read as "no such
    # artist": parse_artist_page reports it, and the next run asks again.
    assert not is_missing_artist_page("")
    assert not is_missing_artist_page("<html><body>No encontrado</body></html>")
    assert not is_missing_artist_page(
        "<html><body><b>Warning</b>: mysqli_connect(): Too many connections</body></html>"
    )


def test_a_full_page_that_starts_like_the_soft_404_is_not_one():
    assert not is_missing_artist_page(SOFT_404 + "\n" + _fixture("song.html"))


def test_a_page_with_a_song_list_is_not_missing(artist_songs):
    assert not is_missing_artist_page(_fixture("artist.html"))
    # However small: an artist with one song is still an artist.
    assert not is_missing_artist_page(
        "<ul id=b_main><li lcd='R-1'><a href='rosas'>Rosas <em>acordes</em></a></li></ul>"
    )
    assert not is_missing_artist_page("<ul id=b_main class=b_main></ul>")


def test_a_full_page_without_a_song_list_is_not_a_soft_404():
    # A real page that lost its list is shape drift, which parse_artist_page reports
    # as an error; it must not read as "LaCuerda doesn't have this artist".
    assert not is_missing_artist_page(_fixture("song.html"))


def test_a_song_list_with_no_readable_item_is_a_parse_error():
    # Shape drift (the lcd attribute renamed, say) must not read as "no songs".
    with pytest.raises(LaCuerdaParseError):
        parse_artist_page(
            "<ul id=b_main><li data-lcd='R-1'><a href='x'>X <em>acordes</em></a></li></ul>"
        )


def test_a_page_without_the_song_list_is_a_parse_error():
    url = "https://acordes.lacuerda.net/soda_stereo/"
    with pytest.raises(LaCuerdaParseError) as err:
        parse_artist_page(_fixture("song.html"), url=url)
    # A provider error, never "the artist has no songs".
    assert isinstance(err.value, ProviderError)
    assert err.value.provider == "lacuerda"
    assert err.value.url == url


# --- matching a title against the artist page ------------------------------


def test_match_title_exact(artist_songs):
    assert match_title(artist_songs, "De Música Ligera").slug == "de_musica_ligera"


def test_match_title_cleans_spotify_suffixes(artist_songs):
    assert (
        match_title(artist_songs, "De Música Ligera - Remasterizado 2007").slug
        == "de_musica_ligera"
    )
    assert match_title(artist_songs, "Cuando Pase El Temblor - MTV Unplugged").slug == (
        "cuando_pase_el_temblor"
    )


def test_match_title_ignores_accents_and_case(artist_songs):
    assert match_title(artist_songs, "de musica ligera").slug == "de_musica_ligera"
    assert match_title(artist_songs, "ÁNGEL ELÉCTRICO").slug == "angel_electrico"


def test_match_title_uses_the_slug_as_a_second_form(artist_songs):
    # The page titles this one "Algun día"; its slug kept the "(Someday)".
    assert match_title(artist_songs, "Algún Día (Someday)").slug == "algun_diasomeday"
    assert match_title(artist_songs, "Picnic en el 4º B").slug == "picnic_en_el_4o_b"


def test_match_title_fuzzy_above_the_cutoff(artist_songs):
    assert match_title(artist_songs, "Persiana Americanna").slug == "persiana_americana"


def test_match_title_below_the_cutoff_is_none(artist_songs):
    assert match_title(artist_songs, "Hotel California") is None
    assert match_title(artist_songs, "Persiana") is None
    assert match_title(artist_songs, "斑马斑马") is None


def test_match_title_cutoff_is_adjustable(artist_songs):
    assert match_title(artist_songs, "Persiana", cutoff=60).slug == "persiana_americana"


def test_match_title_prefers_a_song_with_acordes_on_a_tie():
    songs = [
        LCSong("la_flaca_tab", "La Flaca", "T", (1,)),
        LCSong("la_flaca", "La Flaca", "TR", (2, 1)),
    ]
    assert match_title(songs, "La Flaca").slug == "la_flaca"


def test_match_title_first_on_the_page_wins_a_full_tie():
    songs = [LCSong("la_flaca", "La Flaca", "R", (1,)), LCSong("la_flaca_2", "La flaca", "R", (1,))]
    assert match_title(songs, "La Flaca").slug == "la_flaca"


def test_match_title_with_nothing_to_match():
    assert match_title([], "De Música Ligera") is None
    assert match_title([LCSong("ecos", "Ecos", "R", (1,))], "!!!") is None


# --- the version page ------------------------------------------------------


def _sheet_page(pre: str) -> str:
    return f"<html><body><div id=t_body><PRE>{pre}</PRE></div></body></html>"


def test_parse_version_page_marks_chords():
    lines = parse_version_page(_fixture("version.html")).splitlines()
    assert lines[0] == "Intro:"
    assert lines[2] == "[ch]Am[/ch]-[ch]F[/ch]-[ch]C[/ch]-[ch]G[/ch]"
    assert lines[3] == "[ch]Am[/ch]-[ch]F[/ch]-[ch]C[/ch]-[ch]G[/ch](2)"
    assert lines[5] == "[ch]Am[/ch]             [ch]F[/ch]          [ch]C[/ch]        [ch]G[/ch]"
    assert lines[6] == "Cruzo la plaza,    con el café frío"
    assert "CORO:" in lines


def test_parse_version_page_keeps_the_line_structure_exactly():
    page = _fixture("version.html")
    raw = re.search(r"<PRE>(.*?)</PRE>", page, re.DOTALL).group(1)
    shown = re.sub(r"\[/?ch\]", "", parse_version_page(page))
    assert shown == htmllib.unescape(re.sub(r"<[^>]+>", "", raw))


def test_parse_version_page_converts_a_small_sheet_exactly():
    page = _sheet_page("Intro:\n\n<div></div><A>Am</A>   <A>Do</A>\nla luz del bar\n")
    assert parse_version_page(page) == "Intro:\n\n[ch]Am[/ch]   [ch]Do[/ch]\nla luz del bar\n"


def test_parse_version_page_keeps_solfege_chords():
    page = _sheet_page("<A>Do</A> <A>Rem</A> <A>Sol7</A> <A>La#m</A>\n")
    assert parse_version_page(page) == "[ch]Do[/ch] [ch]Rem[/ch] [ch]Sol7[/ch] [ch]La#m[/ch]\n"


def test_parse_version_page_decodes_entities():
    page = _sheet_page("Canci&oacute;n &amp; co&nbsp;<A>Fa&#35;m</A> &lt;x2&gt;\n")
    assert parse_version_page(page) == "Canción & co [ch]Fa#m[/ch] <x2>\n"


def test_parse_version_page_drops_other_tags_but_keeps_their_text():
    page = _sheet_page(
        "<b>CORO:</b>\n<em>e|--0--2--|</em>\n<span class=x><A>Em</A></span> fin<br>otra<!-- nota --> linea\n"
    )
    assert parse_version_page(page) == "CORO:\ne|--0--2--|\n[ch]Em[/ch] fin\notra linea\n"


def test_parse_version_page_moves_spaces_out_of_a_chord():
    page = _sheet_page("<A> Am </A>|<A></A>|<A>  </A>|\n")
    assert parse_version_page(page) == " [ch]Am[/ch] ||  |\n"


def test_a_page_without_a_sheet_is_a_parse_error():
    # The song page has <pre> previews but no div#t_body: never take a preview for the sheet.
    with pytest.raises(LaCuerdaParseError):
        parse_version_page(_fixture("song.html"))
    url = "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera-3.shtml"
    with pytest.raises(LaCuerdaParseError) as err:
        parse_version_page(_fixture("artist.html"), url=url)
    assert err.value.url == url


def test_an_empty_sheet_is_a_parse_error():
    with pytest.raises(LaCuerdaParseError):
        parse_version_page(_sheet_page("  \n<div></div>\n"))


# --- is it Spanish? ----------------------------------------------------------
# Invented lyrics, written for these tests.

SPANISH_LYRICS = """\
Cruzo la plaza con el café frío
y cuento las luces del tren de las seis
nadie me espera en el andén vacío
guardo tu nombre y no sé qué hacer
Baila la lluvia sobre los tejados
suena la radio de la vecindad
llevo en el bolso tu carta doblada
mañana el puerto se va a despertar
"""

ENGLISH_LYRICS = """\
I walk the long road when the city is asleep
and the lights on the river are the only thing I keep
you said that tomorrow would be easy on the heart
but the morning came early and we fell apart
oh the radio is playing all the songs we used to know
and I'm counting every window on the way back home
"""

# In the manner of 斑马斑马: a Chinese folk ballad.
CHINESE_LYRICS = """\
我走过安静的长街
风吹着旧城的屋檐
你说远方没有尽头
我把歌留在桥边
斑马在梦里慢慢地走
南方的雨下个不停
"""


def test_is_spanish_on_spanish_lyrics():
    assert is_spanish(SPANISH_LYRICS)


def test_is_spanish_on_english_lyrics():
    assert not is_spanish(ENGLISH_LYRICS)


def test_is_spanish_on_chinese_lyrics():
    assert not is_spanish(CHINESE_LYRICS)
    assert not is_spanish("斑马，斑马")


@pytest.mark.parametrize(
    "title,spanish",
    [
        ("De Música Ligera", True),
        ("La Flaca", True),
        ("19 Días y 500 Noches", True),
        ("Te Para Tres", True),
        ("Let It Be", False),
        ("Wonderwall", False),
        ("Hotel California", False),
        ("Persiana Americana", False),  # nothing to go on in two words
        ("", False),
    ],
)
def test_is_spanish_on_short_titles(title, spanish):
    assert is_spanish(title) is spanish


def test_is_spanish_on_mixed_text():
    assert is_spanish(SPANISH_LYRICS + "oh baby you know that I love you\n")
    assert not is_spanish(ENGLISH_LYRICS + "te quiero mi amor\n")
    # Each Chinese character counts as a word, so a Spanish phrase can't tip Chinese lyrics.
    assert not is_spanish(CHINESE_LYRICS + "te quiero mi amor\n")


def test_is_spanish_is_not_fooled_by_a_la_la_chorus():
    assert not is_spanish(ENGLISH_LYRICS + "la la la la la la\nla la la la\n")


def test_looks_spanish_lets_the_lyrics_decide():
    assert not looks_spanish("Señorita", ENGLISH_LYRICS)
    assert looks_spanish("Persiana Americana", SPANISH_LYRICS)
    assert not looks_spanish("斑马，斑马", CHINESE_LYRICS)


def test_looks_spanish_without_lyrics_reads_the_title():
    assert looks_spanish("Señorita")
    assert looks_spanish("Señorita", None)
    assert looks_spanish("Señorita", "  \n")


@pytest.mark.parametrize(
    "title,spanish",
    [
        ("Señorita", True),
        ("¿Dónde Estás?", True),
        ("¡Ay!", True),
        ("Corazón Espinado", True),
        ("Pingüino", True),
        ("La Bamba", True),  # no marks, but a Spanish article
        ("Persiana Americana", False),
        ("Déjà Vu", False),  # à is not Spanish
        ("Für Elise", False),  # ü only follows g in Spanish
        ("Ça Ira", False),
        ("Café in the Rain", False),  # an accent, but English words
        ("Wonderwall", False),
        ("斑马，斑马", False),
    ],
)
def test_looks_spanish_title_marks(title, spanish):
    assert looks_spanish(title) is spanish


def test_looks_spanish_reads_decomposed_and_capital_marks():
    assert looks_spanish(unicodedata.normalize("NFD", "Señorita"))
    assert looks_spanish("CORAZÓN ESPINADO")


# --- the artist listings ------------------------------------------------------------------


def test_the_letters_are_the_initials_the_artist_index_links():
    # tests/fixtures/lacuerda/tabs.html is /tabs/ as captured: its menu links every initial,
    # "#" as _num and "ñ" as nn, and every page of each letter's listing follows from its first.
    menu = re.findall(r"<a href=/tabs/([a-z_]+)/>", _fixture("tabs.html"))
    assert LETTERS == tuple(menu)
    assert len(LETTERS) == 28 and LETTERS[0] == "_num" and LETTERS[15] == "nn"


def test_listing_paths_and_urls():
    assert listing_path("e") == "tabs/e/index0.html"
    assert listing_path("nn", "index100.html") == "tabs/nn/index100.html"
    assert listing_url("tabs/e/index0.html") == f"{BASE_URL}/tabs/e/index0.html"
    assert song_url("soda_stereo", "de_musica_ligera") == f"{BASE_URL}/soda_stereo/de_musica_ligera"


@pytest.fixture
def letter_e():
    return parse_listing_page(_fixture("letter_e.html"), url=f"{BASE_URL}/tabs/e/index0.html")


def test_parse_listing_page_lists_each_artist_with_its_slug_name_and_songs(letter_e):
    # As captured: "Los Ecos" is filed under E with the slug ecos, and E.G.O. as ego.
    assert letter_e.artists[:5] == (
        LCArtist("ec_inchausti", "E.C. Inchausti", 1),
        LCArtist("ego", "E.G.O.", 3),
        LCArtist("ea", "Ea!", 2),
        LCArtist("ebenezer", "Ebenezer", 268),
        LCArtist("ecos", "Los Ecos", 5),
    )
    assert len(letter_e.artists) == 12
    assert LCArtist("eduardo_rios", "Eduardo Ríos", 16) in letter_e.artists


def test_parse_listing_page_reads_every_page_of_the_letter_and_how_many_artists_it_has(letter_e):
    assert letter_e.pages == tuple(f"index{n}.html" for n in range(0, 700, 100))
    assert letter_e.total == 639


def test_a_listing_page_without_its_own_url_lists_the_pages_it_links():
    listing = parse_listing_page(_fixture("letter_e.html"))
    assert listing.pages == tuple(f"index{n}.html" for n in range(100, 700, 100))


def listing_html(items: str, multipag: str = "") -> str:
    return f"<html><body>{multipag}<div id=a_cont><ul id=i_main>{items}</ul></div></body></html>"


def test_a_letter_with_one_page_lists_that_page():
    one = listing_html(
        "<li onclick='w.location=\"/nnaque/\"'><a HREF=\"/nnaque/\"><em>Acordes de &nbsp;</em>Ñaque</a>"
        "<span>4<em>&nbsp; canciones</em></span></li>",
        "<div class='multipag'><ul><li class='sel'>1</li><li class=last><font>1</font> Artistas</li></ul></div>",
    )
    listing = parse_listing_page(one, url=f"{BASE_URL}/tabs/nn/index0.html")
    assert listing == Listing((LCArtist("nnaque", "Ñaque", 4),), ("index0.html",), 1)


def test_a_listing_skips_items_without_a_slug_and_reads_a_missing_count_as_zero():
    items = (
        "<li><a HREF=\"/\"><em>Acordes de</em>Nobody</a></li>"
        "<li><a HREF=\"/a/b/\">Two segments</a></li>"
        "<li><span>3 canciones</span></li>"
        "<li><a HREF=\"https://acordes.lacuerda.net/estopa/\"><em>Acordes de &nbsp;</em>Estopa</a></li>"
    )
    listing = parse_listing_page(listing_html(items))
    assert listing.artists == (LCArtist("estopa", "Estopa", 0),)
    assert (listing.pages, listing.total) == ((), None)


def test_an_empty_listing_is_a_listing():
    assert parse_listing_page(listing_html("")) == Listing((), (), None)


def test_a_page_without_the_artist_list_is_a_parse_error():
    with pytest.raises(LaCuerdaParseError, match=r"i_main"):
        parse_listing_page(_fixture("not_found.html"), url=f"{BASE_URL}/tabs/e/index0.html")


def test_an_artist_list_with_no_readable_item_is_a_parse_error():
    with pytest.raises(LaCuerdaParseError):
        parse_listing_page(listing_html("<li>nothing here</li><li><span>2</span></li>"))


def test_parse_artist_name_reads_the_artist_page_heading():
    assert parse_artist_name(_fixture("artist.html")) == "Soda Stereo"
    assert parse_artist_name("<html><body><h1>no artist block</h1></body></html>") is None


def test_parse_popularity_reads_the_artist_pages_order_of_its_songs():
    # The page's script orders its list by popularity: item 5 (De Música Ligera) first.
    places = parse_popularity(_fixture("artist.html"))
    assert sorted(places, key=places.get)[:3] == ["de_musica_ligera", "persiana_americana", "te_para_3"]
    assert len(places) == 14 and sorted(places.values()) == list(range(14))


def test_parse_popularity_without_an_order_or_with_a_broken_one():
    page = "<ul id=b_main><li lcd='R-1'><a href='a'>A</a></li><li lcd='R-1'><a href='b'>B</a></li></ul>"
    assert parse_popularity(page) == {}
    assert parse_popularity(page + "<script>var popOrder = [1,7,0];</script>") == {"b": 0, "a": 2}
    assert parse_popularity(page + "<script>var popOrder = [x];</script>") == {}
