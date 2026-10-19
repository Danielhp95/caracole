from pathlib import Path

import pytest

from tabarr.overrides import (
    Overrides,
    OverridesError,
    add_alias,
    add_artist_url,
    add_block,
    add_ignore,
    add_match,
    add_pin,
    load_overrides,
    override_key,
    tab_id_from_url,
)

PLAN_EXAMPLE = '''[alias]                       # source artist -> UG artist slug
"Bob Marley & The Wailers" = "bob-marley"

[pin]                         # always use these pages for a song
"Soda Stereo - De Música Ligera" = ["https://tabs.ultimate-guitar.com/tab/85053"]

[transpose]                   # semitones, applied when sheets are rendered (step 3)
"Soda Stereo - De Música Ligera" = -2

[ignore]
songs = ["Some Artist - Some Interlude"]

[block]
tab_ids = [1601668]
'''


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "overrides.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_plan_example(tmp_path):
    o = load_overrides(write(tmp_path, PLAN_EXAMPLE))
    assert o.alias["bob-marley-the-wailers"] == ("bob-marley",)
    assert o.pin["soda-stereo/de-musica-ligera"] == (85053,)
    assert o.transpose["soda-stereo/de-musica-ligera"] == -2
    assert "some-artist/some-interlude" in o.ignore
    assert 1601668 in o.block


def test_plan_example_keeps_the_pinned_url(tmp_path):
    o = load_overrides(write(tmp_path, PLAN_EXAMPLE))
    assert o.pin_urls["soda-stereo/de-musica-ligera"] == ("https://tabs.ultimate-guitar.com/tab/85053",)


def test_pin_urls_keep_the_pasted_addresses_in_pin_order(tmp_path):
    # UG serves a slugged tab only at its slugged URL, so the address you pasted is kept.
    o = load_overrides(write(tmp_path, '''
[pin]
"Soda Stereo - Persiana Americana" = [
  "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-1081460",
  " http://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-guitar-pro-6571406/ ",
  "85053",
]
"宋冬野 - 斑马，斑马" = "https://tabs.ultimate-guitar.com/tab/2001234"
'''))
    assert o.pin["soda-stereo/persiana-americana"] == (1081460, 6571406, 85053)
    assert o.pin_urls["soda-stereo/persiana-americana"] == (
        "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-1081460",
        "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-guitar-pro-6571406",
        "https://tabs.ultimate-guitar.com/tab/85053",  # a bare id is the bare page
    )
    assert o.pin["宋冬野/斑马斑马"] == (2001234,)
    assert o.pin_urls["宋冬野/斑马斑马"] == ("https://tabs.ultimate-guitar.com/tab/2001234",)


def test_overrides_without_pin_urls_still_work():
    # Built by hand (as tests and callers do), the pins carry no URLs.
    o = Overrides(pin={"soda-stereo/de-musica-ligera": (85053,)})
    assert o.pin_urls == {} and o.pin["soda-stereo/de-musica-ligera"] == (85053,)


def test_missing_file_is_empty(tmp_path):
    o = load_overrides(tmp_path / "nope.toml")
    assert not o.alias and not o.pin and not o.ignore and not o.block and not o.match and not o.artist_url
    assert not o.pin_urls


def test_alias_accepts_list_and_canonicalizes(tmp_path):
    o = load_overrides(write(tmp_path, '[alias]\n"The Wailers" = ["the-wailers", "bob-marley-and-the-wailers"]\n'))
    assert o.alias["wailers"] == ("wailers", "bob-marley-the-wailers")


def test_match_and_artist_url_tables(tmp_path):
    o = load_overrides(write(tmp_path, '''
[match]
"Soda Stereo - Persiana Americana - Remasterizado 2007" = "soda-stereo/persiana-americana"
[artist_url]
"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/joaquin_sabina_1234"
"宋冬野" = "https://www.ultimate-guitar.com/artist/song_dongye_99"
'''))
    assert o.match["soda-stereo/persiana-americana"] == ("soda-stereo", "persiana-americana")
    assert o.artist_url["joaquin-sabina"] == "https://www.ultimate-guitar.com/artist/joaquin_sabina_1234"
    assert o.artist_url["宋冬野"] == "https://www.ultimate-guitar.com/artist/song_dongye_99"


def test_bad_values_are_errors(tmp_path):
    with pytest.raises(OverridesError, match="pin"):
        load_overrides(write(tmp_path, '[pin]\n"A - B" = ["https://example.com/x"]\n'))
    with pytest.raises(OverridesError, match="artist_url"):
        load_overrides(write(tmp_path, '[artist_url]\n"A" = "https://example.com/artist/a_1"\n'))
    with pytest.raises(OverridesError, match="transpose"):
        load_overrides(write(tmp_path, '[transpose]\n"A - B" = 15\n'))
    with pytest.raises(OverridesError, match="match"):
        load_overrides(write(tmp_path, '[match]\n"A - B" = "no-slash"\n'))


def test_unknown_table_is_error(tmp_path):
    with pytest.raises(OverridesError, match="pins"):
        load_overrides(write(tmp_path, '[pins]\n"A - B" = []\n'))


def test_invalid_toml_is_error(tmp_path):
    with pytest.raises(OverridesError):
        load_overrides(write(tmp_path, "[alias\n"))


def test_override_key():
    assert override_key("Soda Stereo - De Música Ligera") == "soda-stereo/de-musica-ligera"
    assert override_key("宋冬野 - 斑马，斑马") == "宋冬野/斑马斑马"
    with pytest.raises(OverridesError):
        override_key("No dash here")


def test_tab_id_from_url():
    assert tab_id_from_url("https://tabs.ultimate-guitar.com/tab/85053") == 85053
    assert tab_id_from_url("https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053") == 85053
    assert tab_id_from_url("85053") == 85053
    with pytest.raises(OverridesError):
        tab_id_from_url("https://example.com/tab/1")


def test_writers_preserve_comments_and_roundtrip(tmp_path):
    p = write(tmp_path, "# my decisions\n[alias]  # artists\n\"X\" = \"y\"\n")
    add_alias(p, "Bob Marley & The Wailers", "bob-marley")
    add_match(p, "Soda Stereo - Persiana Americana", "soda-stereo/persiana-americana")
    add_artist_url(p, "宋冬野", "https://www.ultimate-guitar.com/artist/song_dongye_99")
    add_pin(p, "Soda Stereo - De Música Ligera", ["https://tabs.ultimate-guitar.com/tab/85053"])
    add_ignore(p, "Some Artist - Some Interlude")
    add_ignore(p, "Some Artist - Some Interlude")
    add_block(p, 1601668)
    add_block(p, 1601668)
    text = p.read_text(encoding="utf-8")
    assert "# my decisions" in text and "# artists" in text
    o = load_overrides(p)
    assert o.alias["x"] == ("y",) and o.alias["bob-marley-the-wailers"] == ("bob-marley",)
    assert o.match["soda-stereo/persiana-americana"] == ("soda-stereo", "persiana-americana")
    assert o.artist_url["宋冬野"].endswith("song_dongye_99")
    assert o.pin["soda-stereo/de-musica-ligera"] == (85053,)
    assert o.pin_urls["soda-stereo/de-musica-ligera"] == ("https://tabs.ultimate-guitar.com/tab/85053",)
    assert text.count("Some Artist - Some Interlude") == 1
    assert sorted(o.block) == [1601668]


def test_writer_creates_missing_file(tmp_path):
    p = tmp_path / "sub" / "overrides.toml"
    add_ignore(p, "A - B")
    assert load_overrides(p).ignore == frozenset({"a/b"})


def test_writers_report_a_broken_file_as_an_overrides_error(tmp_path):
    broken = '[artist_url]\n"Maná" = "https://www.ultimate-guitar.com/artist/mana_98"\n[artist_url]\n'
    p = write(tmp_path, broken)
    writers = [
        lambda: add_alias(p, "Maná", "mana"),
        lambda: add_match(p, "Maná - Rayando el Sol", "mana/rayando-el-sol"),
        lambda: add_artist_url(p, "宋冬野", "https://www.ultimate-guitar.com/artist/song_dongye_99"),
        lambda: add_pin(p, "Maná - Rayando el Sol", ["https://tabs.ultimate-guitar.com/tab/85053"]),
        lambda: add_ignore(p, "Maná - Rayando el Sol"),
        lambda: add_block(p, 1601668),
    ]
    for add in writers:
        with pytest.raises(OverridesError, match=r"overrides\.toml: .*artist_url"):
            add()
    assert p.read_text(encoding="utf-8") == broken
