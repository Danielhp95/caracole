"""overrides.py's writers of a whole unit, which a sync between two caracoles takes from the other side
(peer_sync.py): a song's entries in every table about it, an artist's alias or UG page, a blocked tab. Each writes
what it is given, as the reader reads it back, and leaves the rest of the file, comments included, as it was."""

import pytest

from caracole.overrides import (
    OverridesError,
    add_harmonica,
    add_ignore,
    add_match,
    add_pin,
    add_version,
    add_youtube,
    load_overrides,
    override_key,
    put_alias,
    put_artist_url,
    put_block,
    put_song_entries,
    song_entries,
)

SONG = "Radiohead - Creep"
KEY = override_key(SONG)
PIN = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"


def entries_of(path, key=KEY):
    return song_entries(load_overrides(path), key)


def a_full_song(path):
    add_version(path, SONG, "key=Gm&capo=0")
    add_pin(path, SONG, [PIN])
    add_match(path, SONG, "radiohead/creep")
    add_youtube(path, SONG, "https://www.youtube.com/watch?v=XFkzRNyygfk")
    add_harmonica(path, SONG, "harmonica-1.txt", {"as": "signs", "*": "bend"})
    add_ignore(path, SONG)


def test_a_songs_entries_written_elsewhere_read_back_the_same_here(tmp_path):
    there, here = tmp_path / "there.toml", tmp_path / "here.toml"
    a_full_song(there)
    wanted = entries_of(there)
    assert set(wanted) == {"version", "pin", "match", "youtube", "harmonica", "ignore"}
    here.write_text("# mine\n[transpose]\n\"Radiohead - Creep\" = 2  # a note\n\"Oasis - Wonderwall\" = 1\n",
                    encoding="utf-8")
    put_song_entries(here, SONG, wanted)
    assert entries_of(here) == wanted  # the transpose here is gone: the other side has none
    text = here.read_text(encoding="utf-8")
    assert text.startswith("# mine\n") and '"Oasis - Wonderwall" = 1' in text
    assert load_overrides(here).transpose == {override_key("Oasis - Wonderwall"): 1}


def test_no_entries_takes_every_entry_about_the_song_out_and_none_about_another(tmp_path):
    path = tmp_path / "overrides.toml"
    a_full_song(path)
    add_version(path, "Oasis - Wonderwall", "key=Em&capo=2")
    add_ignore(path, "Oasis - Wonderwall")
    put_song_entries(path, SONG, {})
    assert entries_of(path) == {}
    assert set(entries_of(path, override_key("Oasis - Wonderwall"))) == {"version", "ignore"}


def test_the_same_entries_again_write_nothing(tmp_path):
    path = tmp_path / "overrides.toml"
    a_full_song(path)
    before = path.read_bytes()
    put_song_entries(path, SONG, entries_of(path))
    assert path.read_bytes() == before


def test_entries_the_reader_would_refuse_are_refused_and_nothing_is_written(tmp_path):
    path = tmp_path / "overrides.toml"
    add_version(path, SONG, "key=Gm&capo=0")
    before = path.read_bytes()
    with pytest.raises(OverridesError):
        put_song_entries(path, SONG, {"transpose": 40})
    with pytest.raises(OverridesError):
        put_song_entries(path, SONG, {"nonsense": 1})
    assert path.read_bytes() == before


def test_an_alias_an_artists_page_and_a_blocked_tab_are_put_and_taken_out(tmp_path):
    path = tmp_path / "overrides.toml"
    put_alias(path, "soda stereo", ["soda-stereo", "soda-stereo-2"])
    put_artist_url(path, "Banma", "Banma", "https://www.ultimate-guitar.com/artist/banma_123")
    put_block(path, 4242, True)
    o = load_overrides(path)
    assert [len(slugs) for slugs in o.alias.values()] == [2]
    assert list(o.artist_url.values()) == ["https://www.ultimate-guitar.com/artist/banma_123"]
    assert o.block == {4242}
    artist = next(iter(o.alias))
    put_alias(path, artist, None)
    put_artist_url(path, next(iter(o.artist_url)), "Banma", None)
    put_block(path, 4242, False)
    o = load_overrides(path)
    assert not o.alias and not o.artist_url and not o.block
