import gzip
from pathlib import Path

import pytest

from caracole.ug.sitemap import (
    IndexRow,
    classify_tab_url,
    iter_locs,
    parse_sitemap_index,
    parse_tab_url,
    sitemap_label,
    sitemap_name,
    tab_sitemaps,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ug"
TAB = "https://tabs.ultimate-guitar.com/tab/"
WWW = "https://www.ultimate-guitar.com/"


def test_chords_url():
    assert parse_tab_url(TAB + "soda-stereo/de-musica-ligera-chords-85053") == IndexRow(
        85053, "soda-stereo", "de-musica-ligera", "chords", "soda-stereo/de-musica-ligera-chords-85053"
    )


def test_http_scheme_accepted():
    assert parse_tab_url(
        "http://tabs.ultimate-guitar.com/tab/queen/bohemian-rhapsody-tabs-1"
    ) == IndexRow(1, "queen", "bohemian-rhapsody", "tabs", "queen/bohemian-rhapsody-tabs-1")


def test_guitar_pro_and_power_tab_files_are_left_out_by_their_whole_type():
    # "guitar-pro" is peeled whole, before a single-word type could take its last part.
    assert parse_tab_url(TAB + "royal-blood/triggers-guitar-pro-6571406") is None
    assert classify_tab_url(TAB + "royal-blood/triggers-guitar-pro-6571406") == "guitar-pro"
    assert classify_tab_url(TAB + "queen/the-miracle-power-1041631") == "power"


@pytest.mark.parametrize(
    "path",
    [
        "china-crisis/arizona-sky-bass-6228233",
        "green-day/21-guns-official-1910535",
        "nirvana/about-a-girl-video-1041731",
        "nat-adderley/work-song-musescore-5955137",
        "green-day/wake-me-up-when-september-ends-drums-1045015",
    ],
)
def test_other_kinds_dropped(path):
    assert parse_tab_url(TAB + path) is None


@pytest.mark.parametrize("path", ["some-artist/some-song-123", "some-artist/hardtabs-123"])
def test_url_without_type_token_is_none(path):
    assert parse_tab_url(TAB + path) is None


def test_type_word_inside_song_is_not_the_type():
    assert parse_tab_url(TAB + "nicki-minaj/super-bass-chords-1055050") == IndexRow(
        1055050, "nicki-minaj", "super-bass", "chords", "nicki-minaj/super-bass-chords-1055050"
    )
    assert parse_tab_url(TAB + "some-band/power-chords-tabs-77") == IndexRow(
        77, "some-band", "power-chords", "tabs", "some-band/power-chords-tabs-77"
    )


def test_bare_id_skipped():
    assert parse_tab_url(TAB + "6571181") is None


def test_empty_artist_skipped():
    assert parse_tab_url(TAB + "/autosmile-chords-65163") is None


def test_empty_key_after_canonicalization_skipped():
    assert parse_tab_url(TAB + "some-artist/chords-123") is None


def test_names_made_only_of_and_are_kept():
    # "And And And" (a real band) and songs titled "&" keep their "and" tokens.
    assert parse_tab_url(TAB + "some-artist/and-chords-123")[1:3] == ("some-artist", "and")
    assert parse_tab_url(TAB + "and/song-chords-123")[1:3] == ("and", "song")
    assert parse_tab_url(TAB + "and-and-and/song-chords-124")[1] == "and-and-and"


@pytest.mark.parametrize(
    "url",
    [
        "https://es.ultimate-guitar.com/tab/queen/the-miracle-chords-1041631",
        "https://www.ultimate-guitar.com/tab/queen/the-miracle-chords-1041631",
        "https://example.com/tab/queen/the-miracle-chords-1041631",
    ],
)
def test_other_hosts_are_none(url):
    assert parse_tab_url(url) is None


def test_leading_the_and_trailing_hyphen():
    assert parse_tab_url(TAB + "the-rifles/the-general-chords-6228251")[1:3] == (
        "rifles",
        "general",
    )
    assert parse_tab_url(TAB + "misc-originals/armokto--chords-6573314")[1:3] == (
        "misc-originals",
        "armokto",
    )
    assert parse_tab_url(TAB + "fontaines-d-c-/big-tabs-2626344")[1:3] == ("fontaines-d-c", "big")
    assert parse_tab_url(TAB + "-feast/jerusalem-chords-2766562")[1:3] == ("feast", "jerusalem")


def test_variant_label_stays_in_song_key():
    row = parse_tab_url(TAB + "ella-langley/froggy-went-a-courtin-intro-chords-6236009")
    assert row == IndexRow(
        6236009, "ella-langley", "froggy-went-a-courtin-intro", "chords",
        "ella-langley/froggy-went-a-courtin-intro-chords-6236009",
    )


def test_iter_locs_reads_only_loc_elements():
    locs = list(iter_locs((FIXTURES / "sitemap_tabs.xml").read_bytes()))
    assert len(locs) == 23
    assert locs[0] == TAB + "amy-shark/ill-be-yours-chords-6228227"
    assert locs[-1] == TAB + "fontaines-d-c-/big-tabs-2626344"
    assert not [u for u in locs if "es.ultimate-guitar.com" in u]


def test_iter_locs_gunzips():
    data = (FIXTURES / "sitemap_tabs.xml").read_bytes()
    assert list(iter_locs(gzip.compress(data))) == list(iter_locs(data))


def test_iter_locs_unescapes_xml_entities():
    assert list(iter_locs(b"<url><loc>https://x.test/a?b=1&amp;c=2</loc></url>")) == [
        "https://x.test/a?b=1&c=2"
    ]


def test_iter_locs_strips_whitespace():
    assert list(iter_locs(b"<loc>\n   https://x.test/a\n</loc>")) == ["https://x.test/a"]


def test_fixture_sitemap_rows():
    rows = [
        r for r in map(parse_tab_url, iter_locs((FIXTURES / "sitemap_tabs.xml").read_bytes())) if r
    ]
    assert [tuple(r[:4]) for r in rows] == [
        (6228227, "amy-shark", "ill-be-yours", "chords"),
        (6236009, "ella-langley", "froggy-went-a-courtin-intro", "chords"),
        (1506192, "soda-stereo", "persiana-americana", "chords"),
        (52384, "soda-stereo", "persiana-americana", "tabs"),
        (6573122, "rainbow", "man-on-the-silver-mountain", "ukulele"),
        (1042515, "r-e-m", "pale-blue-eyes", "tabs"),
        (2766562, "feast", "jerusalem", "chords"),
        (1041823, "noah-the-whale", "give-it-all-back", "tabs"),
        (1055050, "nicki-minaj", "super-bass", "chords"),
        (2626344, "fontaines-d-c", "big", "tabs"),
    ]
    assert all(parse_tab_url(TAB + r.path) == r for r in rows)


def test_parse_sitemap_index_lists_children_in_order():
    children = parse_sitemap_index((FIXTURES / "sitemap_index.xml").read_bytes())
    assert len(children) == 15
    assert children[:3] == [
        WWW + "sitemap_news.xml",
        WWW + "sitemap40.xml",
        WWW + "sitemap_ukulele1.xml",
    ]


def test_tab_sitemaps_numeric_order_then_ukulele_then_last():
    children = parse_sitemap_index((FIXTURES / "sitemap_index.xml").read_bytes())
    assert tab_sitemaps(children) == [
        WWW + "sitemap1.xml",
        WWW + "sitemap2.xml",
        WWW + "sitemap10.xml",
        WWW + "sitemap40.xml",
        WWW + "sitemap_ukulele1.xml",
        WWW + "sitemap_ukulele4.xml",
        WWW + "sitemap_last.xml",
    ]


def test_a_ukulele_chords_url_is_a_row_of_its_own_type():
    # UG's "Ukulele Chords" (2026-10-27: 151,769 URLs in sitemap_ukulele1–4, and the newest in sitemap_last).
    assert parse_tab_url(TAB + "vance-joy/riptide-ukulele-1391193") == IndexRow(
        1391193, "vance-joy", "riptide", "ukulele", "vance-joy/riptide-ukulele-1391193")


def test_tab_sitemaps_lists_each_once():
    assert tab_sitemaps([WWW + "sitemap3.xml", WWW + "sitemap3.xml", WWW + "sitemap_last.xml"]) == [
        WWW + "sitemap3.xml",
        WWW + "sitemap_last.xml",
    ]


def test_sitemap_name():
    assert sitemap_name(WWW + "sitemap40.xml") == "40"
    assert sitemap_name(WWW + "sitemap_ukulele3.xml") == "ukulele3"
    assert sitemap_name(WWW + "sitemap_last.xml") == "last"


def test_sitemap_name_rejects_non_tab_sitemaps():
    for name in ("sitemap_news.xml", "sitemap_wiki_1.xml", "sitemap_forum_threads_3.xml"):
        with pytest.raises(ValueError):
            sitemap_name(WWW + name)


def test_parse_tab_url_keeps_the_raw_path():
    # UG answers 404 for a slugged tab requested at its bare /tab/{id} URL (checked live,
    # 2026-10-18: /tab/1081462 → 404, /tab/soda-stereo/persiana-americana-tabs-1081462 → 200),
    # and canonical keys drop information ("the-rifles" → "rifles"), so the raw path is kept.
    row = parse_tab_url("https://tabs.ultimate-guitar.com/tab/the-rifles/the-general-chords-6228251")
    assert (row.artist_key, row.song_key) == ("rifles", "general")
    assert row.path == "the-rifles/the-general-chords-6228251"


def test_sitemap_label_is_the_file_name_in_the_url():
    for url in (WWW + "sitemap40.xml", WWW + "sitemap_ukulele2.xml", WWW + "sitemap_last.xml"):
        assert sitemap_label(sitemap_name(url)) == url.rsplit("/", 1)[1]


# --- why a tab URL has no index row ---------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        (TAB + "6571181", "bare"),
        ("http://tabs.ultimate-guitar.com/tab/85053", "bare"),
        (TAB + "china-crisis/arizona-sky-bass-6228233", "bass"),
        (TAB + "the-rifles/the-general-guitar-pro-6228251", "guitar-pro"),
        (TAB + "queen/the-miracle-power-1041631", "power"),
        (TAB + "green-day/wake-me-up-when-september-ends-drums-1045015", "drums"),
        (TAB + "nat-adderley/work-song-musescore-5955137", "musescore"),
        (TAB + "some-artist/some-song-123", "unrecognized"),  # no type
        (TAB + "/autosmile-chords-65163", "unrecognized"),  # no artist
        (TAB + "some-artist/chords-123", "unrecognized"),  # no song once canonicalized
        ("https://www.ultimate-guitar.com/tab/queen/the-miracle-power-1041631", "unrecognized"),
        ("https://www.ultimate-guitar.com/tab/1041631", "unrecognized"),  # bare, but not on the tabs host
    ],
)
def test_classify_tab_url_says_why_a_url_has_no_row(url, kind):
    # Bare ids matter apart from the rest: they are tabs, reachable only through artist pages.
    assert classify_tab_url(url) == kind


def test_classify_tab_url_gives_the_row_parse_tab_url_gives():
    url = TAB + "soda-stereo/de-musica-ligera-chords-85053"
    assert classify_tab_url(url) == parse_tab_url(url) == IndexRow(
        85053, "soda-stereo", "de-musica-ligera", "chords", "soda-stereo/de-musica-ligera-chords-85053"
    )
