"""The library is writable by the Syncthing group and every synced device, so caracole
never writes or reads through a symbolic link planted there."""

import os
import stat
from pathlib import Path

import pytest

from caracole.library import NotRegularFile, read_json, read_regular, write_atomic


@pytest.fixture
def state(tmp_path):
    """caracole's private state directory, with a Spotify token in it."""
    d = tmp_path / "state"
    d.mkdir(mode=0o700)
    (d / "spotify_token.json").write_text('{"refresh_token": "secret"}', encoding="utf-8")
    return d


def test_write_atomic_never_writes_through_a_planted_temporary_name(tmp_path, state):
    lib = tmp_path / "Library"
    lib.mkdir()
    token = state / "spotify_token.json"
    (lib / ".index.html.tmp").symlink_to(token)  # the temporary name write_atomic used to pick
    write_atomic(lib / "index.html", b"<!doctype html>the library page")
    assert token.read_text(encoding="utf-8") == '{"refresh_token": "secret"}'
    page = lib / "index.html"
    assert not page.is_symlink() and page.read_bytes() == b"<!doctype html>the library page"


def test_write_atomic_replaces_a_link_at_the_name_itself(tmp_path, state):
    lib = tmp_path / "Library"
    lib.mkdir()
    token = state / "spotify_token.json"
    (lib / "_todo.md").symlink_to(token)
    write_atomic(lib / "_todo.md", b"# To do")
    assert token.read_text(encoding="utf-8") == '{"refresh_token": "secret"}'
    assert not (lib / "_todo.md").is_symlink() and (lib / "_todo.md").read_bytes() == b"# To do"


def test_write_atomic_keeps_the_group_bits_of_the_umask(tmp_path):
    # Syncthing reads the library through the group (UMask 0007): a 0600 file is hidden from it.
    old = os.umask(0o007)
    try:
        write_atomic(tmp_path / "sheet.txt", b"x")
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "sheet.txt").stat().st_mode) == 0o660


def test_a_failed_write_atomic_leaves_no_temporary_file(tmp_path):
    (tmp_path / "sheet.txt").mkdir()  # a directory can't be replaced by a file
    with pytest.raises(OSError):
        write_atomic(tmp_path / "sheet.txt", b"x")
    assert [p.name for p in tmp_path.iterdir()] == ["sheet.txt"]


# --- reading -------------------------------------------------------------------------


def test_read_regular_reads_a_regular_file(tmp_path):
    (tmp_path / "wanted.txt").write_bytes(b"Oasis - Wonderwall\n")
    assert read_regular(tmp_path / "wanted.txt") == b"Oasis - Wonderwall\n"


def test_read_regular_refuses_a_symbolic_link(tmp_path, state):
    link = tmp_path / "wanted.txt"
    link.symlink_to(state / "spotify_token.json")
    with pytest.raises(NotRegularFile, match="symbolic link") as e:
        read_regular(link)
    assert isinstance(e.value, OSError) and e.value.filename == str(link)


def test_read_regular_refuses_a_dangling_link(tmp_path):
    link = tmp_path / "wanted.txt"
    link.symlink_to(tmp_path / "nowhere")
    with pytest.raises(NotRegularFile, match="symbolic link"):
        read_regular(link)


def test_read_regular_refuses_a_directory(tmp_path):
    (tmp_path / "wanted.txt").mkdir()
    with pytest.raises(NotRegularFile, match="not a regular file"):
        read_regular(tmp_path / "wanted.txt")


def test_read_regular_refuses_a_fifo_without_waiting_for_a_writer(tmp_path):
    os.mkfifo(tmp_path / "wanted.txt")
    with pytest.raises(NotRegularFile, match="not a regular file"):
        read_regular(tmp_path / "wanted.txt")


def test_read_regular_of_nothing_is_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_regular(tmp_path / "wanted.txt")


@pytest.fixture
def inbox_fd(tmp_path):
    """A folder opened as the inbox is (no link followed), whose files are reached through it."""
    (tmp_path / "_inbox").mkdir()
    fd = os.open(tmp_path / "_inbox", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    yield fd
    os.close(fd)


def test_read_regular_reads_a_name_in_a_folder_open_at_a_descriptor(tmp_path, inbox_fd):
    (tmp_path / "_inbox" / "a.gp5").write_bytes(b"GP5")
    (tmp_path / "a.gp5").write_bytes(b"NOT THE INBOX'S")
    assert read_regular(Path("a.gp5"), dir_fd=inbox_fd) == b"GP5"


@pytest.mark.parametrize("planted", ["link", "folder", "fifo"])
def test_read_regular_in_a_folder_refuses_what_it_refuses_elsewhere(tmp_path, state, inbox_fd, planted):
    entry = tmp_path / "_inbox" / "a.gp5"
    if planted == "link":
        entry.symlink_to(state / "spotify_token.json")
    elif planted == "folder":
        entry.mkdir()
    else:
        os.mkfifo(entry)
    with pytest.raises(NotRegularFile) as e:
        read_regular(Path("a.gp5"), dir_fd=inbox_fd)
    assert e.value.filename == "a.gp5"


def test_read_json_reads_a_regular_file(tmp_path):
    (tmp_path / "sheet.json").write_bytes('{"content": "[ch]Am[/ch] canción"}'.encode())
    assert read_json(tmp_path / "sheet.json") == {"content": "[ch]Am[/ch] canción"}


@pytest.mark.parametrize(
    "data", [b"{not json", b"\xff\xfe not UTF-8", b"[" * 100_000 + b"]" * 100_000],
    ids=["not-json", "not-utf8", "nested-too-deep"],
)
def test_read_json_of_anything_else_is_a_value_error(tmp_path, data):
    # Any synced device can write the file: whatever it holds raises ValueError, never
    # RecursionError, which would stop a pass over every song.
    (tmp_path / "sheet.json").write_bytes(data)
    with pytest.raises(ValueError):
        read_json(tmp_path / "sheet.json")


def test_read_json_refuses_a_symbolic_link(tmp_path, state):
    link = tmp_path / "sheet.json"
    link.symlink_to(state / "spotify_token.json")
    with pytest.raises(NotRegularFile, match="symbolic link"):
        read_json(link)
