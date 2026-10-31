"""songbook.py ``put_songbook``: a songbook made whole as another caracole holds it (peer_sync.py)."""

from caracole.songbook import Songbook, SongbookSong, load_songbooks, make_songbook, put_songbook
from caracole.viewer.version import Setting


def test_a_songbook_is_put_in_its_place_with_its_settings_then_taken_out(tmp_path):
    path = tmp_path / "songbooks.toml"
    make_songbook(path, "Campfire", ["A - B"])
    make_songbook(path, "Road", ["C - D"])
    text = path.read_text(encoding="utf-8")
    path.write_text(text + "# a note of mine\n", encoding="utf-8")
    songs = (SongbookSong("C - D", Setting(key="G", capo=2)), SongbookSong("A - B"))
    put_songbook(path, "campfire", songs)  # found in any case, written under the name given
    books = load_songbooks(path)
    assert [b.name for b in books] == ["campfire", "Road"]
    assert books[0].songs == songs
    assert "# a note of mine" in path.read_text(encoding="utf-8")
    before = path.read_bytes()
    put_songbook(path, "campfire", songs)
    assert path.read_bytes() == before
    put_songbook(path, "New", (SongbookSong("E - F"),))
    put_songbook(path, "Road", None)
    assert [b.name for b in load_songbooks(path)] == ["campfire", "New"]
    assert load_songbooks(path)[1] == Songbook("New", ("E - F",))
