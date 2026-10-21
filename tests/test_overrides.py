import os
from pathlib import Path

import pytest

from caracole.normalize import name_forms, slug_key
from caracole.overrides import (
    Overrides,
    OverridesError,
    add_alias,
    add_artist_url,
    add_block,
    add_ignore,
    add_lacuerda,
    add_match,
    add_pin,
    add_reject,
    add_version,
    add_youtube,
    LaCuerdaPick,
    artist_url_entry,
    lacuerda_pick_from_url,
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


def test_a_reader_that_can_go_without_gets_none_for_a_file_that_cant_be_read(tmp_path):
    from caracole.overrides import load_overrides_or_none

    assert load_overrides_or_none(tmp_path / "nope.toml") == Overrides()  # no file: no overrides
    assert load_overrides_or_none(write(tmp_path, '[ignore]\nsongs = ["Nickelback - Photograph"]\n')).ignore
    assert load_overrides_or_none(write(tmp_path, "[[[ not toml\n")) is None


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


@pytest.mark.parametrize("pasted", [
    "https://www.ultimate-guitar.com/artist/soda_stereo_2946?filter=chords",
    "https://www.ultimate-guitar.com/artist/soda_stereo_2946?filter=chords&page=2",
    "https://www.ultimate-guitar.com/artist/soda_stereo_2946?page=6",
    "https://www.ultimate-guitar.com/artist/soda_stereo_2946?sort=date",
    "https://www.ultimate-guitar.com/artist/soda_stereo_2946/#tabs",
])
def test_artist_url_takes_the_artist_pages_own_links(tmp_path, pasted):
    # The artist page links to filtered, paged and sorted copies of itself: any of them is the page.
    o = load_overrides(write(tmp_path, f'[artist_url]\n"Soda Stereo" = "{pasted}"\n'))
    assert o.artist_url["soda-stereo"] == "https://www.ultimate-guitar.com/artist/soda_stereo_2946"


@pytest.mark.parametrize("pasted", [
    "https://www.ultimate-guitar.com/artist/634073",
    "https://www.ultimate-guitar.com/artist/634073/",
    "https://www.ultimate-guitar.com/artist/634073?filter=chords",
    "https://www.ultimate-guitar.com/artist/634073?filter=chords&page=2",
    "https://www.ultimate-guitar.com/artist/634073#tabs",
])
def test_artist_url_takes_an_artist_page_addressed_by_its_number_alone(tmp_path, pasted):
    # UG writes some artist pages without the name: 宋冬野's is /artist/634073 (checked live).
    o = load_overrides(write(tmp_path, f'[artist_url]\n"宋冬野" = "{pasted}"\n'))
    assert o.artist_url["宋冬野"] == "https://www.ultimate-guitar.com/artist/634073"


def test_add_artist_url_writes_the_page_without_its_query(tmp_path):
    p = tmp_path / "overrides.toml"
    add_artist_url(p, "Soda Stereo", "https://www.ultimate-guitar.com/artist/soda_stereo_2946?filter=chords")
    add_artist_url(p, "宋冬野", "https://www.ultimate-guitar.com/artist/634073?filter=chords")
    assert "?filter" not in p.read_text(encoding="utf-8")
    o = load_overrides(p)
    assert o.artist_url["soda-stereo"] == "https://www.ultimate-guitar.com/artist/soda_stereo_2946"
    assert o.artist_url["宋冬野"] == "https://www.ultimate-guitar.com/artist/634073"


def test_a_bad_artist_url_shows_what_was_pasted(tmp_path):
    # UG answers /artist/joaquin_sabina with 404: the page's address needs its number.
    p = write(tmp_path, '[artist_url]\n"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/joaquin_sabina"\n')
    with pytest.raises(OverridesError) as e:
        load_overrides(p)
    assert str(e.value) == (
        f"{p}: [artist_url] 'Joaquín Sabina': expected the artist's page "
        "(https://www.ultimate-guitar.com/artist/…) or one of their tab pages "
        "(https://tabs.ultimate-guitar.com/tab/…), as your browser shows it, "
        "got 'https://www.ultimate-guitar.com/artist/joaquin_sabina'"
    )
    assert "<name>" not in str(e.value)


@pytest.mark.parametrize("pasted,page", [
    # The page the user found for 宋冬野 (2026-10-19), and the shapes a browser shows tab pages in.
    ("https://tabs.ultimate-guitar.com/tab/4180894", "https://tabs.ultimate-guitar.com/tab/4180894"),
    ("https://tabs.ultimate-guitar.com/tab/4180894/?ref=artist#comments",
     "https://tabs.ultimate-guitar.com/tab/4180894"),
    ("https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-1081460?app=1",
     "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-1081460"),
])
def test_artist_url_takes_a_tab_page_of_the_artist(tmp_path, pasted, page):
    o = load_overrides(write(tmp_path, f'[artist_url]\n"宋冬野" = "{pasted}"\n'))
    assert o.artist_url["宋冬野"] == page


@pytest.mark.parametrize("pasted", [
    "4180894",  # a number could be the artist's or a tab's
    "https://tabs.ultimate-guitar.com/tab/download?id=4180894",  # pages caracole never asks for
    "https://tabs.ultimate-guitar.com/tab/print?id=4180894",
    "https://www.ultimate-guitar.com/search.php?value=宋冬野",
])
def test_artist_url_refuses_what_is_no_artist_or_tab_page(tmp_path, pasted):
    with pytest.raises(OverridesError, match=r"\[artist_url\] '宋冬野': expected the artist's page"):
        load_overrides(write(tmp_path, f'[artist_url]\n"宋冬野" = "{pasted}"\n'))


def test_add_artist_url_takes_a_tab_page(tmp_path):
    p = tmp_path / "overrides.toml"
    add_artist_url(p, "宋冬野", "https://tabs.ultimate-guitar.com/tab/4180894?ref=search")
    assert load_overrides(p).artist_url["宋冬野"] == "https://tabs.ultimate-guitar.com/tab/4180894"
    with pytest.raises(OverridesError):
        add_artist_url(p, "宋冬野", "https://tabs.ultimate-guitar.com/tab/download?id=4180894")


@pytest.mark.parametrize("entry,artist", [
    ("宋冬野", "宋冬野"),
    ("Song Dongye (宋冬野)", "宋冬野"),  # the entry written as UG names the artist
    ("宋冬野", "Song Dongye (宋冬野)"),
    ("Song Dongye", "宋冬野"),
])
def test_an_artist_url_entry_is_found_by_any_form_of_the_artists_name(tmp_path, entry, artist):
    o = load_overrides(write(tmp_path, f'[artist_url]\n"{entry}" = "https://www.ultimate-guitar.com/artist/634073"\n'))
    assert artist_url_entry(o, name_forms(artist)) == (slug_key(entry), "https://www.ultimate-guitar.com/artist/634073")


def test_an_artist_url_entry_is_compared_by_the_name_as_written(tmp_path):
    # Its key loses the brackets: "Song Dongye (宋冬野)" and "DJ 李志" are both Latin, then the original.
    o = load_overrides(write(tmp_path, '[artist_url]\n"Song Dongye (宋冬野)" = "https://www.ultimate-guitar.com/artist/634073"\n'
                                       '"DJ 李志" = "https://www.ultimate-guitar.com/artist/1"\n'))
    assert artist_url_entry(o, name_forms("宋冬野")) == ("song-dongye-宋冬野", "https://www.ultimate-guitar.com/artist/634073")
    assert artist_url_entry(o, name_forms("李志")) is None  # another artist's name holds his


def test_an_artist_url_entry_under_the_artists_own_key_comes_first():
    o = Overrides(artist_url={"song-dongye": "https://www.ultimate-guitar.com/artist/1",
                              "宋冬野": "https://www.ultimate-guitar.com/artist/634073"})
    assert artist_url_entry(o, name_forms("宋冬野")) == ("宋冬野", "https://www.ultimate-guitar.com/artist/634073")
    assert artist_url_entry(o, name_forms("Li Zhi (李志)")) is None


def test_pins_take_addresses_with_a_query_or_fragment(tmp_path):
    o = load_overrides(write(tmp_path, '''
[pin]
"Soda Stereo - Persiana Americana" = [
  "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-1081460?ref=artist",
  "https://tabs.ultimate-guitar.com/tab/85053/#comments",
]
'''))
    assert o.pin["soda-stereo/persiana-americana"] == (1081460, 85053)
    assert o.pin_urls["soda-stereo/persiana-americana"] == (  # fetched without the query
        "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-1081460",
        "https://tabs.ultimate-guitar.com/tab/85053",
    )


@pytest.mark.parametrize("url", [
    "https://tabs.ultimate-guitar.com/tab/print?id=85053",
    "https://tabs.ultimate-guitar.com/tab/download?id=85053",
    "https://www.ultimate-guitar.com/search.php?value=85053",
])
def test_pages_caracole_never_requests_are_not_tab_urls(url):
    with pytest.raises(OverridesError, match="not an Ultimate Guitar tab URL"):
        tab_id_from_url(url)


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


@pytest.mark.parametrize("text, table, named, shape", [
    ('[ignore]\nsong = ["Maná - Rayando el Sol"]\n', "[ignore]", "'song'", "songs = ["),
    # The shape every other table uses:
    ('[ignore]\n"Maná - Rayando el Sol" = true\n', "[ignore]", "'Maná - Rayando el Sol'", "songs = ["),
    ('[ignore]\nsongs = ["A - B"]\nsong = ["C - D"]\n', "[ignore]", "'song'", "songs = ["),
    ("[block]\ntab_id = [1601668]\n", "[block]", "'tab_id'", "tab_ids = ["),
])
def test_unknown_keys_in_ignore_and_block_are_errors(tmp_path, text, table, named, shape):
    # Dropped, the typo would keep the song fetched, or the rejected tab in use.
    p = write(tmp_path, text)
    with pytest.raises(OverridesError) as e:
        load_overrides(p)
    message = str(e.value)
    assert message.startswith(f"{p}: ") and table in message and named in message and shape in message


@pytest.mark.parametrize("text, where", [
    ('[match]\n"Creep" = "radiohead/creep"\n', "[match] 'Creep'"),
    ('[transpose]\n"Creep" = 2\n', "[transpose] 'Creep'"),
    ('[ignore]\nsongs = ["Creep"]\n', "[ignore] songs"),
    ('[pin]\n"Creep" = "85053"\n', "[pin] 'Creep'"),
])
def test_a_malformed_song_key_names_its_table_and_file(tmp_path, text, where):
    p = write(tmp_path, text)
    with pytest.raises(OverridesError) as e:
        load_overrides(p)
    assert str(e.value) == f"{p}: {where}: expected \"Artist - Title\", got 'Creep'"


def test_a_malformed_pin_value_names_the_pin_once(tmp_path):
    p = write(tmp_path, '[pin]\n"A - B" = 85053\n')
    with pytest.raises(OverridesError) as e:
        load_overrides(p)
    assert str(e.value) == f"{p}: [pin] 'A - B': expected a string or a list of strings"


def test_invalid_toml_is_error(tmp_path):
    with pytest.raises(OverridesError):
        load_overrides(write(tmp_path, "[alias\n"))


def test_a_table_declared_twice_says_to_merge_the_two(tmp_path):
    # As pasting two blocks that each start with the table's header makes it.
    p = write(tmp_path, (
        '[artist_url]\n"Maná" = "https://www.ultimate-guitar.com/artist/mana_98"\n\n'
        '[artist_url]\n"宋冬野" = "https://www.ultimate-guitar.com/artist/song_dongye_99"\n'
    ))
    with pytest.raises(OverridesError) as e:
        load_overrides(p)
    assert str(e.value) == (f"{p}: Cannot declare ('artist_url',) twice (at line 4, column 12); "
                            "merge the two [artist_url] sections into one")
    other = write(tmp_path, '[match]\n"A - B" = "a/b"\n"A - B" = "a/c"\n')  # a key twice: no such hint
    with pytest.raises(OverridesError) as e:
        load_overrides(other)
    assert "merge" not in str(e.value)


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


@pytest.mark.parametrize("pasted", [
    # Taken as an address bar shows it, but only on UG's own hosts.
    "example.com/tab/85053",
    "https://ultimate-guitar.com.example.com/tab/85053",
    "https://notultimate-guitar.com/tab/85053",
    "https://tabs.ultimate-guitar.com.example.com/tab/85053",
    "https://user@tabs.ultimate-guitar.com/tab/85053",
    "https://tabs.ultimate-guitar.com:8080/tab/85053",
    "ftp://tabs.ultimate-guitar.com/tab/85053",
])
def test_a_lookalike_of_ugs_hosts_is_no_tab_page(pasted):
    with pytest.raises(OverridesError, match="not an Ultimate Guitar tab URL"):
        tab_id_from_url(pasted)


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


def test_reject_lists_the_ug_songs_that_are_not_the_song(tmp_path):
    o = load_overrides(write(tmp_path, '''
[reject]   # "none of these" in caracole review
"Soda - Persiana Americana" = ["Soda-Stereo/Persiana-Americana", "soda-stereo/persiana"]
"soda - persiana americana" = "soda-stereo-ar/persiana-americana"  # the same song, written another way
"宋冬野 - 斑马，斑马" = ["li-zhi/ban-ma-ban-ma"]
'''))
    assert o.reject == {
        "soda/persiana-americana": frozenset({("soda-stereo", "persiana-americana"), ("soda-stereo", "persiana"),
                                              ("soda-stereo-ar", "persiana-americana")}),
        "宋冬野/斑马斑马": frozenset({("li-zhi", "ban-ma-ban-ma")}),
    }
    assert Overrides().reject == {}


@pytest.mark.parametrize("text, where, expected", [
    ('[reject]\n"Creep" = ["radiohead/creep"]\n', "[reject] 'Creep'", "expected \"Artist - Title\", got 'Creep'"),
    ('[reject]\n"A - B" = ["no-slash"]\n', "[reject] 'A - B'", "expected \"ug-artist/ug-song\", got 'no-slash'"),
    ('[reject]\n"A - B" = 5\n', "[reject] 'A - B'", "expected a string or a list of strings"),
])
def test_a_malformed_reject_names_its_entry(tmp_path, text, where, expected):
    p = write(tmp_path, text)
    with pytest.raises(OverridesError) as e:
        load_overrides(p)
    assert str(e.value) == f"{p}: {where}: {expected}"


def test_add_reject_adds_to_the_songs_list_and_keeps_your_comments(tmp_path):
    p = write(tmp_path, '# mine\n[reject]\n"Soda - Persiana Americana" = "soda-stereo/persiana"  # a cover\n')
    add_reject(p, "soda - persiana americana", ["soda-stereo/persiana", "soda-stereo/persiana-americana"])
    add_reject(p, "Maná - Rayando el Sol", ["ana-gabriel/rayando-el-sol"])
    before, inode = p.read_text(encoding="utf-8"), p.stat().st_ino
    add_reject(p, "Soda - Persiana Americana", ["Soda-Stereo/Persiana"])  # rejected already: nothing is written
    add_reject(p, "Maná - Rayando el Sol", [])
    text = p.read_text(encoding="utf-8")
    assert text == before and p.stat().st_ino == inode
    assert "# mine" in text and "# a cover" in text and "soda - persiana americana" not in text
    o = load_overrides(p)
    assert o.reject["soda/persiana-americana"] == frozenset({("soda-stereo", "persiana"),
                                                             ("soda-stereo", "persiana-americana")})
    assert o.reject["mana/rayando-el-sol"] == frozenset({("ana-gabriel", "rayando-el-sol")})


def test_add_reject_checks_what_it_writes(tmp_path):
    p = tmp_path / "overrides.toml"
    with pytest.raises(OverridesError, match="Artist - Title"):
        add_reject(p, "Creep", ["radiohead/creep"])
    with pytest.raises(OverridesError, match=r"\[reject\] 'Radiohead - Creep': expected \"ug-artist/ug-song\""):
        add_reject(p, "Radiohead - Creep", ["radiohead"])
    assert not p.exists()


def test_youtube_names_a_songs_video_or_none(tmp_path):
    o = load_overrides(write(tmp_path, '''
[youtube]   # the video caracole takes a song's audio from, or "none"
"Radiohead - Creep" = "https://youtu.be/XFkzRNyygfk?si=abc"
"Soda Stereo - De Música Ligera" = "music.youtube.com/watch?v=Dgv4fE0Xjbg&list=OLAK5uy"
"Some Artist - Some Interlude" = "None"
'''))
    assert o.youtube == {
        "radiohead/creep": "XFkzRNyygfk",
        "soda-stereo/de-musica-ligera": "Dgv4fE0Xjbg",
        "some-artist/some-interlude": None,
    }
    assert Overrides().youtube == {}


@pytest.mark.parametrize("value", ['"https://www.youtube.com/playlist?list=PL1"', '"XFkzRNyygfk"', "5",
                                   '"https://vimeo.com/123"', '["https://youtu.be/XFkzRNyygfk"]'])
def test_a_youtube_entry_that_is_no_video_names_its_entry_and_what_it_takes(tmp_path, value):
    p = write(tmp_path, f'[youtube]\n"Radiohead - Creep" = {value}\n')
    with pytest.raises(OverridesError, match=r"\[youtube\] 'Radiohead - Creep': expected a YouTube video's address "
                                             r"\(https://www.youtube.com/watch\?v=…\) or \"none\""):
        load_overrides(p)


def test_add_youtube_writes_the_plain_address_or_none_in_the_songs_one_entry(tmp_path):
    p = write(tmp_path, '# mine\n[youtube]\n"radiohead - creep" = "none"  # no good upload\n')
    add_youtube(p, "Radiohead - Creep", "https://www.youtube.com/watch?v=XFkzRNyygfk&list=PL1&t=3")
    add_youtube(p, "宋冬野 - 斑马，斑马", "none")
    before, inode = p.read_text(encoding="utf-8"), p.stat().st_ino
    add_youtube(p, "Radiohead - Creep", "https://youtu.be/XFkzRNyygfk")  # the same video: nothing is written
    text = p.read_text(encoding="utf-8")
    assert text == before and p.stat().st_ino == inode
    assert "# mine" in text and text.count("reep") == 1
    assert '"radiohead - creep" = "https://www.youtube.com/watch?v=XFkzRNyygfk"' in text
    o = load_overrides(p)
    assert o.youtube == {"radiohead/creep": "XFkzRNyygfk", "宋冬野/斑马斑马": None}
    with pytest.raises(OverridesError, match="YouTube video's address"):
        add_youtube(p, "Radiohead - Creep", "https://www.youtube.com/@radiohead")
    with pytest.raises(OverridesError, match="Artist - Title"):
        add_youtube(p, "Creep", "none")
    assert p.read_text(encoding="utf-8") == before


def test_version_names_where_a_song_is_played_as_its_viewers_address(tmp_path):
    o = load_overrides(write(tmp_path, '''
[version]   # where you play a song: its PDF, its viewer and its songbooks follow it
"Soda Stereo - De Música Ligera" = "t=2&mode=dorian&capo=0&at=3.1"
"Radiohead - Creep" = "#t=-1"
'''))
    assert o.version == {"soda-stereo/de-musica-ligera": "t=2&mode=dorian&capo=0&at=3.1", "radiohead/creep": "t=-1"}
    assert Overrides().version == {}


@pytest.mark.parametrize("value", ["3", "true", '"t=2\\u0000"', '"t=%ff"', '"' + "t=2&" + "x" * 3000 + '"'])
def test_a_version_that_is_no_viewers_address_names_its_entry(tmp_path, value):
    with pytest.raises(OverridesError, match=r"\[version\] 'Radiohead - Creep': expected .*t=2&mode=dorian"):
        load_overrides(write(tmp_path, f'[version]\n"Radiohead - Creep" = {value}\n'))


def test_add_version_writes_and_clears_the_table_keeping_comments(tmp_path):
    p = write(tmp_path, '# mine\n[transpose]\n"Soda Stereo - De Música Ligera" = -2  # for my voice\n\n'
                        '[version]  # where I play them\n"radiohead - creep" = "t=1"  # half a step up\n')
    add_version(p, "Soda Stereo - De Música Ligera", "t=2&mode=dorian&capo=0&at=3.1")
    add_version(p, "Radiohead - Creep", "#t=3")  # the song's one entry, as it is written; no "#"
    text = p.read_text(encoding="utf-8")
    assert "# mine" in text and "# for my voice" in text and "# where I play them" in text
    assert text.count("reep") == 1 and '"radiohead - creep" = "t=3"' in text
    o = load_overrides(p)
    assert o.version == {"soda-stereo/de-musica-ligera": "t=2&mode=dorian&capo=0&at=3.1", "radiohead/creep": "t=3"}
    assert o.transpose == {"soda-stereo/de-musica-ligera": -2}  # [transpose] stays; [version] wins over it
    before, inode = text, p.stat().st_ino
    add_version(p, "Radiohead - Creep", "t=3")  # the same again: nothing is written
    add_version(p, "Nobody - Nothing", None)  # no entry to clear: nothing either
    assert p.read_text(encoding="utf-8") == before and p.stat().st_ino == inode

    add_version(p, "RADIOHEAD - CREEP", None)  # cleared, by the song's key
    text = p.read_text(encoding="utf-8")
    assert "reep" not in text and "# mine" in text and "# where I play them" in text
    assert load_overrides(p).version == {"soda-stereo/de-musica-ligera": "t=2&mode=dorian&capo=0&at=3.1"}
    with pytest.raises(OverridesError, match="Artist - Title"):
        add_version(p, "Creep", "t=1")
    with pytest.raises(OverridesError, match="expected"):
        add_version(p, "Radiohead - Creep", "t=1\x00&mode=dorian")
    assert p.read_text(encoding="utf-8") == text


def test_lacuerda_names_the_song_or_the_version_you_picked_there(tmp_path):
    o = load_overrides(write(tmp_path, '''
[lacuerda]   # the LaCuerda song or version a song's sheet comes from
"Estopa - Como Camarón" = "https://acordes.lacuerda.net/estopa/como_camaron-2.shtml"
"Soda Stereo - De Música Ligera" = "acordes.lacuerda.net/soda_stereo/de_musica_ligera/"
"Fito y Fitipaldis - Soldadito Marinero" = "http://lacuerda.net/fito__fitipaldis/soldadito_marinero.shtml?x=1"
'''))
    assert o.lacuerda == {
        "estopa/como-camaron": LaCuerdaPick("estopa", "como_camaron", 2),
        "soda-stereo/de-musica-ligera": LaCuerdaPick("soda_stereo", "de_musica_ligera"),
        "fito-fitipaldis/soldadito-marinero": LaCuerdaPick("fito__fitipaldis", "soldadito_marinero", 1),
    }
    assert o.lacuerda["estopa/como-camaron"].url == "https://acordes.lacuerda.net/estopa/como_camaron-2.shtml"
    assert o.lacuerda["soda-stereo/de-musica-ligera"].url == "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera"
    assert LaCuerdaPick("a", "b", 1).url == "https://acordes.lacuerda.net/a/b.shtml"
    assert Overrides().lacuerda == {}


def test_a_lacuerda_pick_holds_its_version_or_any_version_of_its_song():
    song, version = LaCuerdaPick("estopa", "como_camaron"), LaCuerdaPick("estopa", "como_camaron", 2)
    assert song.holds("estopa/como_camaron-2") and song.holds("estopa/como_camaron-1")
    assert version.holds("estopa/como_camaron-2") and not version.holds("estopa/como_camaron-1")
    assert not song.holds("estopa/como_camaron_2-1") and not song.holds("ecos/como_camaron-2")


@pytest.mark.parametrize("value", [
    "https://acordes.lacuerda.net/estopa/", "https://acordes.lacuerda.net/estopa/como_camaron/x",
    "https://tabs.ultimate-guitar.com/tab/85053", "https://acordes.lacuerda.net/tabs/e/index0.html",
    "https://acordes.lacuerda.net/Estopa/Como Camaron", "https://acordes.lacuerda.net/estopa/como_camaron-0.shtml",
    "ftp://acordes.lacuerda.net/estopa/como_camaron", "estopa", ""])
def test_a_lacuerda_entry_that_is_no_song_page_says_what_it_takes(tmp_path, value):
    with pytest.raises(OverridesError, match="LaCuerda song"):
        lacuerda_pick_from_url(value)
    p = write(tmp_path, f'[lacuerda]\n"Estopa - Como Camarón" = "{value}"\n')
    with pytest.raises(OverridesError, match=r"\[lacuerda\] 'Estopa - Como Camarón': expected a LaCuerda song"):
        load_overrides(p)
    with pytest.raises(OverridesError, match="a string"):
        load_overrides(write(tmp_path, '[lacuerda]\n"Estopa - Como Camarón" = 5\n'))


def test_add_lacuerda_writes_the_picks_address_in_the_songs_one_entry(tmp_path):
    p = write(tmp_path, '# mine\n[lacuerda]\n"estopa - como camarón" = "https://acordes.lacuerda.net/estopa/x"  # old\n')
    add_lacuerda(p, "Estopa - Como Camarón", "acordes.lacuerda.net/estopa/como_camaron-2.shtml?ref=1")
    add_lacuerda(p, "Soda Stereo - De Música Ligera", "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera")
    before, inode = p.read_text(encoding="utf-8"), p.stat().st_ino
    add_lacuerda(p, "Estopa - Como Camarón", "https://acordes.lacuerda.net/estopa/como_camaron-2.shtml")  # the same
    text = p.read_text(encoding="utf-8")
    assert text == before and p.stat().st_ino == inode
    assert "# mine" in text and text.lower().count("como camar") == 1 and "# old" in text
    assert '"estopa - como camarón" = "https://acordes.lacuerda.net/estopa/como_camaron-2.shtml"' in text
    assert load_overrides(p).lacuerda == {"estopa/como-camaron": LaCuerdaPick("estopa", "como_camaron", 2),
                                          "soda-stereo/de-musica-ligera": LaCuerdaPick("soda_stereo", "de_musica_ligera")}
    with pytest.raises(OverridesError, match="LaCuerda song"):
        add_lacuerda(p, "Estopa - Como Camarón", "https://acordes.lacuerda.net/estopa/")
    with pytest.raises(OverridesError, match="Artist - Title"):
        add_lacuerda(p, "Como Camarón", "https://acordes.lacuerda.net/estopa/como_camaron")
    assert p.read_text(encoding="utf-8") == before


def test_add_alias_keeps_the_artists_other_aliases(tmp_path):
    p = write(tmp_path, (
        "[alias]\n"
        '"Soda" = "soda-stereo"  # mine\n'
        '"Bob Marley and the Wailers" = [\n  "bob-marley",  # UG files them under two names\n'
        '  "bob-marley-the-wailers",\n]\n'
    ))
    add_alias(p, "Soda", "soda-stereo-ar")  # a single slug becomes a list
    add_alias(p, "Bob Marley & The Wailers", "wailers")  # the same artist, written another way
    before, inode = p.read_text(encoding="utf-8"), p.stat().st_ino
    add_alias(p, "Bob Marley & The Wailers", "bob-marley")  # already one of them: nothing is written
    add_alias(p, "Soda", "Soda-Stereo")
    text = p.read_text(encoding="utf-8")
    assert text == before and p.stat().st_ino == inode
    assert "# mine" in text and "# UG files them under two names" in text
    assert "Bob Marley & The Wailers" not in text
    o = load_overrides(p)
    assert o.alias["soda"] == ("soda-stereo", "soda-stereo-ar")
    assert o.alias["bob-marley-the-wailers"] == ("bob-marley", "bob-marley-the-wailers", "wailers")


def test_writer_creates_missing_file(tmp_path):
    p = tmp_path / "sub" / "overrides.toml"
    add_ignore(p, "A - B")
    assert load_overrides(p).ignore == frozenset({"a/b"})


SECRET = '[ignore]\nsongs = ["Private - Token"]\n'  # a private file that happens to parse as overrides


def all_writers(p: Path):
    return [
        lambda: add_alias(p, "Maná", "mana"),
        lambda: add_match(p, "Maná - Rayando el Sol", "mana/rayando-el-sol"),
        lambda: add_artist_url(p, "宋冬野", "https://www.ultimate-guitar.com/artist/song_dongye_99"),
        lambda: add_pin(p, "Maná - Rayando el Sol", ["https://tabs.ultimate-guitar.com/tab/85053"]),
        lambda: add_ignore(p, "Maná - Rayando el Sol"),
        lambda: add_block(p, 1601668),
        lambda: add_reject(p, "Maná - Rayando el Sol", ["ana-gabriel/rayando-el-sol"]),
    ]


def planted(tmp_path: Path, kind: str) -> tuple[Path, Path]:
    """overrides.toml in the library as something other than a file: a link (to a private file, or
    to nothing) or a folder. Returns it and the private file."""
    secret = tmp_path / "private" / "secret.toml"
    secret.parent.mkdir()
    secret.write_text(SECRET, encoding="utf-8")
    p = tmp_path / "lib" / "overrides.toml"
    p.parent.mkdir()
    if kind == "link":
        p.symlink_to(secret)
    elif kind == "dangling link":
        p.symlink_to(tmp_path / "private" / "gone.toml")
    else:
        p.mkdir()
    return p, secret


LINK = "a symbolic link, which caracole doesn't follow"


@pytest.mark.parametrize("kind, said", [
    ("link", LINK), ("dangling link", LINK), ("folder", "not a regular file"),
])
def test_overrides_that_arent_a_file_are_refused_unread(tmp_path, kind, said):
    # The library is writable by every synced device: a link planted as overrides.toml could point at
    # caracole's private files, which would then be read, or copied into the library by a writer.
    p, secret = planted(tmp_path, kind)
    with pytest.raises(OverridesError) as e:
        load_overrides(p)
    assert str(e.value) == f"{p}: {said}; put the file itself there"
    for add in all_writers(p):
        with pytest.raises(OverridesError) as e:
            add()
        assert str(e.value) == f"{p}: {said}; put the file itself there"
    assert p.is_symlink() == ("link" in kind) and secret.read_text(encoding="utf-8") == SECRET
    copied = [f for f in (tmp_path / "lib").rglob("*") if f.is_file() and not f.is_symlink()]
    assert copied == []  # nothing of the private file reached the library


def test_writers_never_write_through_a_link_at_a_temporary_name(tmp_path):
    p = write(tmp_path, "[ignore]\nsongs = []\n")
    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    for name in ("overrides.toml.tmp", ".overrides.toml.tmp"):
        (tmp_path / name).symlink_to(victim)
    add_ignore(p, "A - B")
    assert victim.read_text(encoding="utf-8") == "precious"
    assert not p.is_symlink() and load_overrides(p).ignore == frozenset({"a/b"})


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files it has no permission for")
def test_a_file_caracole_may_not_read_is_an_overrides_error(tmp_path):
    # Every command, and the nightly run, reports an OverridesError cleanly; anything else is a traceback.
    p = write(tmp_path, '[ignore]\nsongs = ["A - B"]\n')
    p.chmod(0o200)
    try:
        with pytest.raises(OverridesError) as e:
            load_overrides(p)
        assert str(e.value) == f"{p}: can't read it: Permission denied"
        for add in all_writers(p):
            with pytest.raises(OverridesError, match="can't read it: Permission denied"):
                add()
    finally:
        p.chmod(0o600)
    assert p.read_text(encoding="utf-8") == '[ignore]\nsongs = ["A - B"]\n'


def test_a_file_that_isnt_utf8_is_an_overrides_error_naming_the_line(tmp_path):
    # Saved as Latin-1 by an editor, say: "Maná" is the byte 0xE1 then.
    p = tmp_path / "overrides.toml"
    latin1 = '# mine\n[ignore]\nsongs = ["Maná - Rayando el Sol"]\n'.encode("latin-1")
    p.write_bytes(latin1)
    with pytest.raises(OverridesError) as e:
        load_overrides(p)
    assert str(e.value) == f"{p}: line 3 is not valid UTF-8 (save the file as UTF-8)"
    for add in all_writers(p):
        with pytest.raises(OverridesError, match="line 3 is not valid UTF-8"):
            add()
    assert p.read_bytes() == latin1


def test_writers_report_a_broken_file_as_an_overrides_error(tmp_path):
    broken = '[artist_url]\n"Maná" = "https://www.ultimate-guitar.com/artist/mana_98"\n[artist_url]\n'
    p = write(tmp_path, broken)
    for add in all_writers(p):
        with pytest.raises(OverridesError, match=r"overrides\.toml: .*artist_url"):
            add()
    assert p.read_text(encoding="utf-8") == broken


def test_a_file_nested_too_deep_is_an_overrides_error_and_is_left_alone(tmp_path):
    deep = "x = " + "[" * 1000 + "]" * 1000 + "\n"  # tomllib and tomlkit raise RecursionError on it
    p = write(tmp_path, deep)
    with pytest.raises(OverridesError, match=r"overrides\.toml: "):
        load_overrides(p)
    for add in all_writers(p):
        with pytest.raises(OverridesError, match=r"overrides\.toml: "):
            add()
    assert p.read_text(encoding="utf-8") == deep
