"""The library is writable by the Syncthing group and every synced device, so tabarr
never writes or reads through a symbolic link planted there."""

import os
import stat

import pytest

from tabarr.library import write_atomic


@pytest.fixture
def state(tmp_path):
    """tabarr's private state directory, with a Spotify token in it."""
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
    # Syncthing reads the library through the group (UMask 0007), so a 0600 file would be hidden from it.
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
