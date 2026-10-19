from pathlib import Path

import pytest
from helpers.ug_pages import make_artist_page_html, store_page_html, version_dict

from caracole.ug.artist import artist_page_url, parse_artist_page
from caracole.ug.page import PageParseError

FIXTURES = Path(__file__).parent / "fixtures" / "ug"
SODA = "https://www.ultimate-guitar.com/artist/soda_stereo_2946"


def soda_page():
    return parse_artist_page((FIXTURES / "artist.html").read_text(encoding="utf-8"), url=SODA)


def test_artist_identity():
    page = soda_page()
    assert (page.artist_id, page.name, page.url) == (2946, "Soda Stereo", SODA)


def test_typed_tabs_in_order_and_pro_links_skipped():
    assert [t.tab_id for t in soda_page().tabs] == [
        2213253,
        1271959,
        3505940,
        4909726,
        824731,
        578349,
        311923,
        2528571,
        85042,
        85053,
        1601635,
        1601636,
        35952,
        210848,
        4905640,
        37649,
        420174,
        453174,
        527120,
        557599,
        615463,
        743772,
        1601637,
        1601638,
        1601640,
        2730615,
        555890,
    ]


def test_bare_id_tabs_are_listed_with_names_and_ratings():
    chords = [t for t in soda_page().tabs if t.kind == "chords"]
    assert [(t.tab_id, t.version, t.rating, t.votes) for t in chords] == [
        (85042, 1, 4.83354, 277),
        (85053, 2, 4.54038, 7),
        (1601635, 3, 4.85005, 81),
        (1601636, 4, 4.64041, 7),
    ]
    assert {t.song_name for t in chords} == {"De Música Ligera"}


def test_kinds_and_labels():
    tabs = {t.tab_id: t for t in soda_page().tabs}
    assert [tabs[i].kind for i in (2213253, 1271959, 3505940, 578349, 311923)] == [
        None,
        None,
        None,
        "guitar-pro",
        "power",
    ]
    assert [tabs[i].label for i in (4909726, 824731, 555890, 85042)] == [
        "intro",
        "acoustic",
        "solo",
        None,
    ]


def test_pagination():
    page = soda_page()
    assert (page.page, page.pages) == (1, 6)


def test_filters_map_kinds_to_absolute_urls():
    assert soda_page().filters == {
        "chords": SODA + "?filter=chords",
        "tabs": SODA + "?filter=tabs",
        "guitar-pro": SODA + "?filter=guitar_pro",
        "power": SODA + "?filter=power",
    }


def test_relative_links_resolve_against_the_page_url():
    html = (FIXTURES / "artist.html").read_text(encoding="utf-8")
    page = parse_artist_page(
        html, url="https://www.ultimate-guitar.test/artist/soda_stereo_2946?page=2"
    )
    assert (
        page.filters["chords"]
        == "https://www.ultimate-guitar.test/artist/soda_stereo_2946?filter=chords"
    )


def test_url_follows_the_path_of_ugs_own_links():
    data = {
        "artist": {"id": 3, "name": "X", "name_stripped": "x"},
        "other_tabs": [],
        "pagination": {"pages": [{"page": 1, "url": "/artist/renamed_3"}], "current": 1},
    }
    page = parse_artist_page(
        store_page_html(data), url="https://www.ultimate-guitar.com/artist/x_3?filter=tabs"
    )
    assert page.url == "https://www.ultimate-guitar.com/artist/renamed_3"


def test_url_from_page_url_when_page_has_no_links():
    data = {"artist": {"id": 3, "name": "X"}, "other_tabs": []}
    page = parse_artist_page(
        store_page_html(data), url="https://www.ultimate-guitar.com/artist/x_3?filter=tabs"
    )
    assert page.url == "https://www.ultimate-guitar.com/artist/x_3"


def test_url_from_name_and_id_without_links_or_page_url():
    data = {"artist": {"id": 3, "name": "X", "name_stripped": "x"}, "other_tabs": []}
    assert (
        parse_artist_page(store_page_html(data)).url == "https://www.ultimate-guitar.com/artist/x_3"
    )


def test_single_page_without_pagination():
    data = {"artist": {"id": 3, "name": "X", "name_stripped": "x"}, "other_tabs": [version_dict(1)]}
    page = parse_artist_page(store_page_html(data))
    assert (page.page, page.pages, page.filters, [t.tab_id for t in page.tabs]) == (1, 1, {}, [1])


def test_helper_artist_page_round_trip():
    tabs = [
        version_dict(1, song="斑马斑马", artist="宋冬野"),
        {"id": 9, "song_name": "斑马斑马", "marketing_type": "TabPro", "rating": 4.8, "votes": 21},
        version_dict(2, type="Pro", part="intro", song="安和桥", artist="宋冬野"),
    ]
    page = parse_artist_page(make_artist_page_html(5, "宋冬野", tabs, page=2, pages=3))
    base = "https://www.ultimate-guitar.com/artist/宋冬野_5"
    assert (page.artist_id, page.name, page.url, page.page, page.pages) == (5, "宋冬野", base, 2, 3)
    assert [(t.tab_id, t.song_name, t.kind, t.label) for t in page.tabs] == [
        (1, "斑马斑马", "chords", None),
        (2, "安和桥", "guitar-pro", "intro"),
    ]
    assert page.filters == {
        "chords": base + "?filter=chords",
        "guitar-pro": base + "?filter=guitar_pro",
    }


def test_missing_store_is_parse_error():
    with pytest.raises(PageParseError) as info:
        parse_artist_page("<html><title>Oops! We couldn't find that page.</title></html>", url=SODA)
    assert (info.value.provider, info.value.url) == ("ug", SODA)


@pytest.mark.parametrize("artist", [None, {"name": "No id"}])
def test_missing_artist_is_parse_error(artist):
    data = {"other_tabs": []} if artist is None else {"artist": artist, "other_tabs": []}
    with pytest.raises(PageParseError):
        parse_artist_page(store_page_html(data))


def test_missing_other_tabs_is_parse_error():
    with pytest.raises(PageParseError):
        parse_artist_page(store_page_html({"artist": {"id": 3, "name": "X", "name_stripped": "x"}}))


@pytest.mark.parametrize(
    "kind,page,expected",
    [
        (None, 1, SODA),
        ("chords", 1, SODA + "?filter=chords"),
        ("chords", 2, SODA + "?filter=chords&page=2"),
        ("tabs", 1, SODA + "?filter=tabs"),
        ("guitar-pro", 3, SODA + "?filter=guitar_pro&page=3"),
        ("power", 1, SODA + "?filter=power"),
        (None, 4, SODA + "?page=4"),
    ],
)
def test_artist_page_url(kind, page, expected):
    assert artist_page_url(SODA, kind=kind, page=page) == expected


def test_artist_page_url_replaces_query_and_trailing_slash():
    assert artist_page_url(SODA + "/?filter=tabs&page=4", kind="chords") == SODA + "?filter=chords"


@pytest.mark.parametrize("kind,page", [("bass", 1), ("chords", 0)])
def test_artist_page_url_rejects_unknown_kind_and_page(kind, page):
    with pytest.raises(ValueError):
        artist_page_url(SODA, kind=kind, page=page)
