from pathlib import Path

import pytest
from helpers.ug_pages import make_tab_page_html, store_page_html, version_dict

from tabarr.http import ProviderError
from tabarr.ug.page import (
    PageParseError,
    UGVersion,
    kind_of,
    page_url,
    parse_tab_page,
    strip_markup,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ug"
CHORDS_URL = "https://tabs.ultimate-guitar.com/tab/85053"


def chords_page():
    return parse_tab_page(
        (FIXTURES / "tab_chords.html").read_text(encoding="utf-8"), url=CHORDS_URL
    )


def pro_page():
    return parse_tab_page((FIXTURES / "tab_pro.html").read_text(encoding="utf-8"))


def test_chords_page_tab_and_versions():
    page = chords_page()
    assert (page.tab.tab_id, page.tab.version, page.tab.kind) == (85053, 2, "chords")
    assert (page.tab.rating, page.tab.votes) == (4.54038, 7)
    assert [(v.tab_id, v.type, v.version, v.rating, v.votes) for v in page.versions] == [
        (2528571, "Official", 1, 4.84768, 270),
        (85042, "Chords", 1, 4.83354, 277),
        (1601635, "Chords", 3, 4.85005, 81),
        (1601636, "Chords", 4, 4.64041, 7),
    ]
    assert [v.kind for v in page.versions] == [None, "chords", "chords", "chords"]


def test_chords_page_content_is_the_raw_markup():
    content = chords_page().content
    assert content.startswith("[Intro]\r\n[ch]Bm[/ch]  [ch]G[/ch]")
    assert (
        "[tab][ch]Bm[/ch]                    [ch]G[/ch]\r\nPaper lanterns on the water,[/tab]"
        in content
    )


def test_chords_page_empty_meta_list_is_empty_dict():
    assert chords_page().meta == {}


def test_meta_that_is_not_an_object_is_empty():
    view = {"versions": [], "wiki_tab": {}, "meta": ["unexpected"]}
    assert (
        parse_tab_page(store_page_html({"tab": version_dict(1, type="Pro"), "tab_view": view})).meta
        == {}
    )


def test_raw_is_the_page_data():
    page = chords_page()
    assert page.raw["tab"]["id"] == 85053
    assert len(page.raw["tab_view"]["versions"]) == 4


def test_version_fields():
    v = chords_page().versions[1]
    assert v == UGVersion(
        tab_id=85042,
        song_id=67588,
        song_name="De Música Ligera",
        artist_name="Soda Stereo",
        type="Chords",
        part="",
        version=1,
        rating=4.83354,
        votes=277,
        access="public",
        url="https://tabs.ultimate-guitar.com/tab/85042",
        description=None,
        is_acoustic=False,
        raw=v.raw,
    )
    assert v.raw["type_name"] == "Chords"
    assert v.label is None


def test_pro_page_meta():
    page = pro_page()
    assert (page.tab.tab_id, page.tab.kind, page.tab.label) == (555890, "guitar-pro", "solo")
    assert page.meta["fileExtension"] == ".gp5"
    assert page.meta["duration"] == 14
    assert page.content is None
    assert [v.tab_id for v in page.versions] == [2528571]


def test_artist_url_from_page_tab():
    assert chords_page().artist_url == "https://www.ultimate-guitar.com/artist/soda_stereo_2946"


def test_artist_url_missing_is_none():
    page = parse_tab_page(make_tab_page_html(version_dict(1), [], content="x"))
    assert page.artist_url is None


@pytest.mark.parametrize(
    "ug_type,kind",
    [
        ("Chords", "chords"),
        ("Tabs", "tabs"),
        ("Pro", "guitar-pro"),
        ("Power", "power"),
        ("Official", None),
        ("Bass Tabs", None),
        ("Ukulele Chords", None),
        ("Video", None),
        ("Drum Tabs", None),
        ("Lyrics", None),
        (None, None),
    ],
)
def test_kind_of(ug_type, kind):
    assert kind_of(ug_type) == kind


@pytest.mark.parametrize(
    "part,acoustic,label",
    [("Solo", False, "solo"), ("", True, "acoustic"), ("intro", True, "intro"), ("", False, None)],
)
def test_label_is_part_else_acoustic(part, acoustic, label):
    page = parse_tab_page(
        make_tab_page_html(version_dict(1, part=part, is_acoustic=acoustic), [], content="x")
    )
    assert page.tab.label == label


def test_strip_markup():
    sheet = "[Verse 1]\r\n[tab][ch]G[/ch]   [ch]D/F#[/ch]\r\nla la la[/tab]\r\n[ch]Em[/ch]"
    assert strip_markup(sheet) == "[Verse 1]\r\nG   D/F#\r\nla la la\r\nEm"


def test_page_url():
    assert page_url(85053) == "https://tabs.ultimate-guitar.com/tab/85053"


def test_missing_store_is_parse_error():
    with pytest.raises(PageParseError) as info:
        parse_tab_page(
            "<html><body><h1>Oops! We couldn't find that page.</h1></body></html>", url=CHORDS_URL
        )
    assert isinstance(info.value, ProviderError)
    assert (info.value.provider, info.value.url) == ("ug", CHORDS_URL)


def test_invalid_json_is_parse_error():
    with pytest.raises(PageParseError):
        parse_tab_page('<div class="js-store" data-content="{&quot;store&quot;:"></div>')


@pytest.mark.parametrize(
    "payload", ["[]", "{&quot;store&quot;:[]}", "{&quot;store&quot;:{&quot;page&quot;:{}}}"]
)
def test_store_without_page_data_is_parse_error(payload):
    with pytest.raises(PageParseError):
        parse_tab_page(f'<div class="js-store" data-content="{payload}"></div>')


def test_missing_tab_is_parse_error():
    with pytest.raises(PageParseError):
        parse_tab_page(
            store_page_html(
                {"tab_view": {"versions": [], "wiki_tab": {"content": "x"}, "meta": []}}
            )
        )


def test_missing_tab_view_is_parse_error():
    with pytest.raises(PageParseError):
        parse_tab_page(store_page_html({"tab": version_dict(1, type="Pro")}))


def test_missing_versions_key_is_parse_error():
    with pytest.raises(PageParseError):
        parse_tab_page(
            store_page_html({"tab": version_dict(1), "tab_view": {"wiki_tab": {"content": "x"}}})
        )


def test_null_versions_is_no_versions():
    page = parse_tab_page(
        store_page_html(
            {"tab": version_dict(1), "tab_view": {"versions": None, "wiki_tab": {"content": "x"}}}
        )
    )
    assert page.versions == ()


def test_sheet_without_content_is_parse_error():
    with pytest.raises(PageParseError):
        parse_tab_page(make_tab_page_html(version_dict(1, type="Tabs"), []))


@pytest.mark.parametrize("bad", [None, "n/a"])
def test_null_rating_and_votes_are_zero(bad):
    tab = version_dict(1, rating=bad, votes=bad)
    page = parse_tab_page(
        make_tab_page_html(tab, [version_dict(2, rating=bad, votes=bad)], content="x")
    )
    assert (page.tab.rating, page.tab.votes) == (0.0, 0)
    assert (page.versions[0].rating, page.versions[0].votes) == (0.0, 0)


def test_whole_number_rating_is_a_float():
    page = parse_tab_page(make_tab_page_html(version_dict(1, rating=5), [], content="x"))
    assert page.tab.rating == 5.0 and isinstance(page.tab.rating, float)


def test_versions_without_type_or_id_are_skipped():
    versions = [{"id": 2, "song_name": "No type"}, version_dict(3, id="three"), version_dict(4)]
    page = parse_tab_page(make_tab_page_html(version_dict(1), versions, content="x"))
    assert [v.tab_id for v in page.versions] == [4]


def test_entities_in_attribute_are_decoded():
    raw = (FIXTURES / "tab_chords.html").read_text(encoding="utf-8")
    assert "De M&uacute;sica Ligera" in raw
    assert chords_page().tab.song_name == "De Música Ligera"


def test_apostrophes_and_ampersands_are_decoded():
    html = make_tab_page_html(
        version_dict(1, song="Don't Stop", artist="Simon & Garfunkel"), [], content="x"
    )
    assert "Don&#039;t Stop" in html and "Simon &amp; Garfunkel" in html
    page = parse_tab_page(html)
    assert (page.tab.song_name, page.tab.artist_name) == ("Don't Stop", "Simon & Garfunkel")


def test_chinese_names_survive():
    html = make_tab_page_html(
        version_dict(7, song="斑马斑马", artist="宋冬野"), [], content="[ch]C[/ch] 斑马"
    )
    assert "斑马斑马" in html
    page = parse_tab_page(html)
    assert (page.tab.song_name, page.tab.artist_name, page.content) == (
        "斑马斑马",
        "宋冬野",
        "[ch]C[/ch] 斑马",
    )


def test_bytes_are_read_as_utf8():
    html = make_tab_page_html(version_dict(7, song="斑马斑马", artist="宋冬野"), [], content="x")
    assert parse_tab_page(html.encode("utf-8")).tab.song_name == "斑马斑马"


def test_helper_page_round_trip():
    tab = version_dict(
        10,
        type="Pro",
        version=2,
        rating=4.2,
        votes=9,
        part="intro",
        song="S",
        artist="A",
        song_id=5,
    )
    page = parse_tab_page(
        make_tab_page_html(
            tab,
            [version_dict(11, type="Pro")],
            meta={"fileExtension": ".gpx"},
            artist_url="https://u/a_1",
        )
    )
    t = page.tab
    assert (t.tab_id, t.song_id, t.kind, t.version, t.rating, t.votes, t.label) == (
        10,
        5,
        "guitar-pro",
        2,
        4.2,
        9,
        "intro",
    )
    assert (t.url, t.access, t.song_name, t.artist_name) == (
        "https://tabs.ultimate-guitar.com/tab/10",
        "public",
        "S",
        "A",
    )
    assert (page.meta, page.artist_url, page.content) == (
        {"fileExtension": ".gpx"},
        "https://u/a_1",
        None,
    )
    assert [v.tab_id for v in page.versions] == [11]
