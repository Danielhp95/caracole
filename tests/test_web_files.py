"""caracole/web/files.py: the library's files over HTTP, never through a link, never a private one."""

import os

import pytest

from caracole.web.files import NotServed, read_library_file


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "lib"
    song = lib / "Soda Stereo" / "De Música Ligera"
    song.mkdir(parents=True)
    (song / "sheet.pdf").write_bytes(b"%PDF-1.7 sheet")
    (song / "lyrics.txt").write_text("letra\n", encoding="utf-8")
    (song / "guitar-1.gp5").write_bytes(b"gp5")
    (song / "info.json").write_text("{}", encoding="utf-8")
    (lib / "_todo.md").write_text("# To do\n", encoding="utf-8")
    return lib


def test_a_kept_file_comes_with_its_type(library):
    data, kind, attachment = read_library_file(library, "Soda Stereo/De Música Ligera/sheet.pdf")
    assert (data, kind, attachment) == (b"%PDF-1.7 sheet", "application/pdf", False)
    assert read_library_file(library, "Soda Stereo/De Música Ligera/lyrics.txt")[1] == "text/plain; charset=utf-8"
    assert read_library_file(library, "_todo.md")[1] == "text/plain; charset=utf-8"
    assert read_library_file(library, "Soda Stereo/De Música Ligera/info.json")[1].startswith("application/json")


def test_guitar_pro_files_are_downloads(library):
    data, kind, attachment = read_library_file(library, "Soda Stereo/De Música Ligera/guitar-1.gp5")
    assert (data, kind, attachment) == (b"gp5", "application/octet-stream", True)


@pytest.mark.parametrize("path", [
    "", "/", "Soda Stereo", "Soda Stereo/De Música Ligera", "../lib/_todo.md", "Soda Stereo/../_todo.md",
    "./_todo.md", "Soda Stereo//De Música Ligera/sheet.pdf", ".stfolder/x.txt", "Soda Stereo/.sheet.pdf.1a2b.tmp",
    "missing.pdf", "index.html", "page.htm", "image.svg", "overrides.toml", "caracole.sqlite", "notes.txt\x00.pdf",
])
def test_anything_else_is_not_served(library, path):
    (library / "index.html").write_text("<script></script>", encoding="utf-8")
    (library / "page.htm").write_text("<script></script>", encoding="utf-8")
    (library / "image.svg").write_text("<svg/>", encoding="utf-8")
    (library / "overrides.toml").write_text("[ignore]\n", encoding="utf-8")
    (library / "caracole.sqlite").write_bytes(b"SQLite format 3")
    with pytest.raises(NotServed):
        read_library_file(library, path)


def test_no_link_is_followed_to_a_file_or_through_a_folder(library, tmp_path):
    private = tmp_path / "state"
    private.mkdir()
    (private / "spotify_token.json").write_text('{"refresh_token": "secret"}', encoding="utf-8")
    (library / "Evil").symlink_to(private, target_is_directory=True)
    (library / "token.json").symlink_to(private / "spotify_token.json")
    for path in ("Evil/spotify_token.json", "token.json"):
        with pytest.raises(NotServed):
            read_library_file(library, path)


def test_a_fifo_is_never_waited_on(library):
    os.mkfifo(library / "trap.txt")
    with pytest.raises(NotServed):
        read_library_file(library, "trap.txt")


def test_caracoles_private_folders_inside_the_library_stay_private(library):
    (library / "state").mkdir()
    (library / "state" / "spotify_token.json").write_text("{}", encoding="utf-8")
    (library / "cache" / "http").mkdir(parents=True)
    (library / "cache" / "http" / "page.txt").write_text("cached", encoding="utf-8")
    hidden = [library / "state", library / "cache"]
    for path in ("state/spotify_token.json", "cache/http/page.txt"):
        with pytest.raises(NotServed):
            read_library_file(library, path, hidden=hidden)
    assert read_library_file(library, "_todo.md", hidden=hidden)[0] == b"# To do\n"
