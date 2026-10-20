"""songbook.py: songbooks.toml, the songs a songbook names, and what it is rendered to."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import add_song

from caracole.songbook import (
    FILE_NAME,
    Songbook,
    SongbookError,
    add_to_songbook,
    check_name,
    delete_songbook,
    find_songbook,
    load_songbooks,
    make_songbook,
    move_in_songbook,
    remove_from_songbook,
    rename_songbook,
    same_entry,
)

HAND_WRITTEN = '''# My songbooks, kept by hand and by caracole.

["Campfire"]   # for the beach
songs = [
  "Soda Stereo - De Música Ligera",   # the opener
  "宋冬野 - 斑马，斑马",
]

# For the wedding in June
[Weddings]
songs = ["Radiohead - Creep"]
'''


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / FILE_NAME
    path.write_text(text, encoding="utf-8")
    return path


# --- reading ---------------------------------------------------------------------------------


def test_no_file_means_no_songbooks(tmp_path):
    assert load_songbooks(tmp_path / FILE_NAME) == []


def test_each_table_is_a_songbook_its_songs_in_order(tmp_path):
    books = load_songbooks(write(tmp_path, HAND_WRITTEN))
    assert books == [
        Songbook("Campfire", ("Soda Stereo - De Música Ligera", "宋冬野 - 斑马，斑马")),
        Songbook("Weddings", ("Radiohead - Creep",)),
    ]
    assert books[0].folder == "Campfire"


@pytest.mark.parametrize("text,words", [
    ('[Campfire\nsongs = []\n', "line 1"),  # not TOML
    ('[Campfire]\nsongs = "Radiohead - Creep"\n', "a list of"),
    ('[Campfire]\nsongs = [1, 2]\n', "a list of"),
    ('[Campfire]\nsong = ["Radiohead - Creep"]\n', "unknown key"),
    ('title = "Campfire"\n', "a table"),
    ('[Campfire]\nsongs = ["Radiohead"]\n', '"Artist - Title"'),
    ('["  "]\nsongs = []\n', "name"),
    ('[Campfire]\nsongs = []\n["campfire "]\nsongs = []\n', "twice"),
])
def test_a_bad_file_is_an_error_naming_it(tmp_path, text, words):
    path = write(tmp_path, text)
    with pytest.raises(SongbookError) as e:
        load_songbooks(path)
    assert str(path) in str(e.value) and words in str(e.value)


def test_a_file_that_isnt_utf8_is_an_error(tmp_path):
    path = tmp_path / FILE_NAME
    path.write_bytes(b'["Caf\xe9"]\nsongs = []\n')
    with pytest.raises(SongbookError, match="UTF-8"):
        load_songbooks(path)


def test_the_file_is_never_read_through_a_link(tmp_path):
    private = tmp_path / "private.toml"
    private.write_text('["Secret"]\nsongs = ["A - B"]\n', encoding="utf-8")
    (tmp_path / FILE_NAME).symlink_to(private)
    with pytest.raises(SongbookError, match="symbolic link"):
        load_songbooks(tmp_path / FILE_NAME)


def test_two_names_for_one_folder_are_refused(tmp_path):
    # Two names a phone's file system would put in one folder.
    path = write(tmp_path, '["Camp/fire"]\nsongs = []\n["Camp-fire"]\nsongs = []\n')
    with pytest.raises(SongbookError, match="folder"):
        load_songbooks(path)


# --- names -----------------------------------------------------------------------------------


def test_a_name_is_trimmed_and_its_spaces_collapsed():
    assert check_name("  Camp \t fire  ") == "Camp fire"


@pytest.mark.parametrize("name", ["", "   ", ".hidden", "a" * 81, "tab\x00name", "new\nline"])
def test_a_name_that_cant_be_a_folder_is_refused(name):
    with pytest.raises(SongbookError):
        check_name(name)


def test_a_songbook_is_found_by_its_name_in_any_case(tmp_path):
    books = load_songbooks(write(tmp_path, HAND_WRITTEN))
    assert find_songbook(books, "campfire").name == "Campfire"
    assert find_songbook(books, " WEDDINGS ").name == "Weddings"
    assert find_songbook(books, "Picnic") is None


def test_entries_are_the_same_song_by_identity():
    assert same_entry("Soda Stereo - De Musica Ligera", "soda stereo - De Música Ligera (Remastered 2007)")
    assert same_entry("宋冬野 - 斑馬，斑馬", "宋冬野 - 斑马，斑马")  # Traditional and Simplified
    assert not same_entry("Radiohead - Creep", "Stone Temple Pilots - Creep")
    assert same_entry("Earth - Wind - Fire", "Earth - Wind - Fire")


# --- writing ---------------------------------------------------------------------------------


def test_make_writes_a_new_songbook(tmp_path):
    path = tmp_path / FILE_NAME
    make_songbook(path, "Campfire", ["Radiohead - Creep", "宋冬野 - 斑马，斑马"])
    assert load_songbooks(path) == [Songbook("Campfire", ("Radiohead - Creep", "宋冬野 - 斑马，斑马"))]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#")  # a word on what the file is, for whoever opens it
    assert '"Radiohead - Creep",\n' in text  # one song a line, to edit by hand


def test_make_keeps_a_song_named_twice_once_where_it_first_is(tmp_path):
    path = tmp_path / FILE_NAME
    made = make_songbook(path, "Gig", ["Oasis - Wonderwall", "Radiohead - Creep", "oasis - wonderwall"])
    assert made.songs == ("Oasis - Wonderwall", "Radiohead - Creep")
    assert load_songbooks(path) == [made]


def test_make_refuses_a_name_taken_in_any_case(tmp_path):
    path = write(tmp_path, HAND_WRITTEN)
    with pytest.raises(SongbookError, match="already"):
        make_songbook(path, "CAMPFIRE", ["Radiohead - Creep"])
    with pytest.raises(SongbookError, match="folder"):
        make_songbook(path, "Weddings.", ["Radiohead - Creep"])  # the same folder name


def test_writers_keep_comments_and_layout(tmp_path):
    path = write(tmp_path, HAND_WRITTEN)
    make_songbook(path, "Picnic", ["Radiohead - Creep"])
    add_to_songbook(path, "campfire", ["Radiohead - Creep"])
    move_in_songbook(path, "Campfire", "Radiohead - Creep", 1)
    remove_from_songbook(path, "Weddings", ["radiohead - creep"])
    text = path.read_text(encoding="utf-8")
    for comment in ("# My songbooks", "# for the beach", "# the opener", "# For the wedding in June"):
        assert comment in text
    assert [(b.name, b.songs) for b in load_songbooks(path)] == [
        ("Campfire", ("Radiohead - Creep", "Soda Stereo - De Música Ligera", "宋冬野 - 斑马，斑马")),
        ("Weddings", ()),
        ("Picnic", ("Radiohead - Creep",)),
    ]


def test_add_appends_only_songs_not_there(tmp_path):
    path = write(tmp_path, HAND_WRITTEN)
    added = add_to_songbook(path, "Campfire", ["soda stereo - de musica ligera", "Radiohead - Creep"])
    assert added == ["Radiohead - Creep"]
    assert find_songbook(load_songbooks(path), "Campfire").songs[-1] == "Radiohead - Creep"


def test_remove_says_what_it_removed(tmp_path):
    path = write(tmp_path, HAND_WRITTEN)
    assert remove_from_songbook(path, "Campfire", ["宋冬野 - 斑馬，斑馬", "Muse - Hysteria"]) == ["宋冬野 - 斑马，斑马"]
    assert find_songbook(load_songbooks(path), "Campfire").songs == ("Soda Stereo - De Música Ligera",)


@pytest.mark.parametrize("position,order", [
    (1, ["C", "A", "B"]),
    (2, ["A", "C", "B"]),
    (3, ["A", "B", "C"]),
    (9, ["A", "B", "C"]),  # past the end: last
])
def test_move_puts_a_song_at_a_position_counted_from_one(tmp_path, position, order):
    path = tmp_path / FILE_NAME
    make_songbook(path, "Book", ["X - A", "X - B", "X - C"])
    move_in_songbook(path, "Book", "x - c", position)
    assert [s.removeprefix("X - ") for s in find_songbook(load_songbooks(path), "Book").songs] == order


def test_move_refuses_a_song_the_songbook_lacks_and_a_position_below_one(tmp_path):
    path = write(tmp_path, HAND_WRITTEN)
    with pytest.raises(SongbookError, match="isn't in"):
        move_in_songbook(path, "Campfire", "Muse - Hysteria", 1)
    with pytest.raises(SongbookError, match="1"):
        move_in_songbook(path, "Campfire", "Radiohead - Creep", 0)


def test_rename_keeps_the_songbooks_place_and_comments(tmp_path):
    path = write(tmp_path, HAND_WRITTEN)
    rename_songbook(path, "campfire", "Beach nights")
    text = path.read_text(encoding="utf-8")
    assert '["Campfire"]' not in text and "# for the beach" in text
    assert [b.name for b in load_songbooks(path)] == ["Beach nights", "Weddings"]
    with pytest.raises(SongbookError, match="already"):
        rename_songbook(path, "Beach nights", "weddings")
    rename_songbook(path, "Beach nights", "beach Nights")  # a new spelling of its own name
    assert [b.name for b in load_songbooks(path)] == ["beach Nights", "Weddings"]


def test_delete_takes_the_songbook_out(tmp_path):
    path = write(tmp_path, HAND_WRITTEN)
    delete_songbook(path, "WEDDINGS")
    assert [b.name for b in load_songbooks(path)] == ["Campfire"]
    assert "# for the beach" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("change", [
    lambda p: add_to_songbook(p, "Picnic", ["Radiohead - Creep"]),
    lambda p: remove_from_songbook(p, "Picnic", ["Radiohead - Creep"]),
    lambda p: move_in_songbook(p, "Picnic", "Radiohead - Creep", 1),
    lambda p: rename_songbook(p, "Picnic", "Beach"),
    lambda p: delete_songbook(p, "Picnic"),
])
def test_a_songbook_that_isnt_there_is_an_error(tmp_path, change):
    path = write(tmp_path, HAND_WRITTEN)
    with pytest.raises(SongbookError, match="No songbook"):
        change(path)


def test_writers_replace_the_file_in_one_rename_and_never_write_through_a_link(tmp_path):
    private = tmp_path / "private.toml"
    private.write_text("secret = true\n", encoding="utf-8")
    path = tmp_path / FILE_NAME
    path.symlink_to(private)
    with pytest.raises(SongbookError, match="symbolic link"):
        make_songbook(path, "Campfire", ["Radiohead - Creep"])
    assert private.read_text(encoding="utf-8") == "secret = true\n"


def test_writers_refuse_a_broken_file_and_leave_it_alone(tmp_path):
    path = write(tmp_path, "[Campfire\n")
    with pytest.raises(SongbookError):
        make_songbook(path, "Picnic", ["Radiohead - Creep"])
    assert path.read_text(encoding="utf-8") == "[Campfire\n"


def test_an_unchanged_file_is_not_written_again(tmp_path):
    path = write(tmp_path, HAND_WRITTEN)
    before = os.stat(path).st_ino
    assert add_to_songbook(path, "Campfire", ["Soda Stereo - De Música Ligera"]) == []
    assert os.stat(path).st_ino == before


# --- the songs a songbook names ----------------------------------------------------------------


def test_a_song_is_found_by_its_artist_and_title_written_any_way(conn):
    from caracole.songbook import find_library_song

    soda = add_song(conn, "Soda Stereo", "De Música Ligera - Remasterizado 2007")
    found = find_library_song(conn, "soda stereo - de musica ligera")
    assert found.song.id == soda.id and found.exact
    zh = add_song(conn, "宋冬野", "斑马，斑马")
    assert find_library_song(conn, "宋冬野 - 斑馬，斑馬").song.id == zh.id


def test_a_song_is_found_by_its_pinyin_or_a_unique_search(conn):
    from caracole.songbook import find_library_song

    zh = add_song(conn, "宋冬野", "斑马，斑马")
    add_song(conn, "Radiohead", "Creep")
    found = find_library_song(conn, "Song Dongye - Ban Ma Ban Ma")
    assert found.song.id == zh.id and not found.exact
    assert find_library_song(conn, "ban ma ban ma").song.id == zh.id


def test_a_search_two_songs_answer_as_well_finds_neither(conn):
    from caracole.songbook import find_library_song

    add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Stone Temple Pilots", "Creep")
    assert find_library_song(conn, "creep") is None
    assert find_library_song(conn, "Radiohead - Creep").song.artist == "Radiohead"


def test_songs_the_library_lacks_are_refused_with_a_hint(conn):
    from caracole.songbook import NotInLibrary, library_songs

    add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Radiohead", "Karma Police")
    with pytest.raises(NotInLibrary) as e:
        library_songs(conn, ["Radiohead - Creep", "Radiohed - Karma", "Muse - Hysteria"])
    message = str(e.value)
    assert 'No song "Radiohed - Karma" in the library: did you mean "Radiohead - Karma Police"' in message
    assert 'No song "Muse - Hysteria" in the library.' in message and "caracole add" in message
    assert e.value.texts == ["Radiohed - Karma", "Muse - Hysteria"]
    found = library_songs(conn, ["Radiohead - Karma Polise", "radiohead - creep"])  # a typo, then a case
    assert [f.song.title for f in found] == ["Karma Police", "Creep"]


def test_an_entry_of_the_file_is_its_song_by_artist_and_title_alone_never_by_a_search(conn):
    from caracole.songbook import find_entry_song, find_library_song

    police = add_song(conn, "Radiohead", "Karma Police")
    zh = add_song(conn, "宋冬野", "斑马，斑马")
    assert find_entry_song(conn, "radiohead - karma police").id == police.id
    assert find_entry_song(conn, "宋冬野 - 斑馬，斑馬").id == zh.id  # Traditional and Simplified
    # A song gone from the library, whose title holds another's: what you typed may find it, an entry never.
    assert find_library_song(conn, "Radiohead - Karma Police Live").song.id == police.id
    assert find_entry_song(conn, "Radiohead - Karma Police Live") is None
    assert find_entry_song(conn, "ban ma ban ma") is None
