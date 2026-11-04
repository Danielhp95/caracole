"""A file to import, staged part by part in ``state_dir/peer/import-<id>/`` (peer_import.py), as caracole serve's
import routes send it (``POST /sync/import/open`` and ``/sync/import/part``), then taken by ``caracole peer import``."""

from __future__ import annotations

import os
import stat
import time

import pytest

from caracole import peer_file, peer_import


def opened(tmp_path, size=8, name="desk-03-11-26.caracole", now=None):
    return peer_import.open_import(tmp_path / "state", size=size, name=name, now=now)


def folder_of(tmp_path, import_id):
    return tmp_path / "state" / "peer" / f"import-{import_id}"


def test_an_upload_is_staged_part_by_part_in_order_and_whole_once_its_size_is_reached(tmp_path):
    state = tmp_path / "state"
    import_id = opened(tmp_path)
    assert len(import_id) == 16 and int(import_id, 16) >= 0
    with pytest.raises(peer_import.StagingError, match="isn't whole yet") as e:
        peer_import.whole(state, import_id)
    assert e.value.status == 400
    assert [peer_import.add_part(state, import_id, at, data) for at, data in ((0, b"abc"), (3, b"def"), (6, b"gh"))] \
        == [3, 6, 8]
    path = peer_import.whole(state, import_id)
    assert path == folder_of(tmp_path, import_id) / peer_import.FILE and path.read_bytes() == b"abcdefgh"
    assert peer_import.opened_name(folder_of(tmp_path, import_id)) == "desk-03-11-26.caracole"


def test_a_part_out_of_order_or_past_the_size_is_refused(tmp_path):
    state = tmp_path / "state"
    import_id = opened(tmp_path)
    peer_import.add_part(state, import_id, 0, b"abc")
    for at, data in ((0, b"abc"), (2, b"x"), (4, b"x"), (3, b"defghi")):
        with pytest.raises(peer_import.StagingError, match="isn't the next one") as e:
            peer_import.add_part(state, import_id, at, data)
        assert e.value.status == 400
    with pytest.raises(peer_import.StagingError):
        peer_import.add_part(state, import_id, 3, b"x" * (peer_import.PART_MAX + 1))
    assert peer_import.add_part(state, import_id, 3, b"defgh") == 8  # what it had is as it was


def test_an_import_no_one_opened_is_said(tmp_path):
    state = tmp_path / "state"
    for unknown in ("0123456789abcdef", "../../etc/passwd", "ABCDEF0123456789"):
        with pytest.raises(peer_import.StagingError, match="No such import is open here|Which import") as e:
            peer_import.add_part(state, unknown, 0, b"x")
        assert e.value.status in (400, 404)
        with pytest.raises(peer_import.StagingError):
            peer_import.whole(state, unknown)


def test_one_import_at_a_time_and_an_hour_untouched_is_swept_unless_held(tmp_path):
    state = tmp_path / "state"
    first = opened(tmp_path)
    with pytest.raises(peer_import.StagingError, match="being sent here already") as e:
        opened(tmp_path)
    assert e.value.status == 409
    later = time.time() + peer_import.EXPIRES + 60
    with peer_import.held(folder_of(tmp_path, first)):
        assert peer_import.sweep(state, later) == []
        with pytest.raises(peer_import.StagingError, match="being sent here already"):
            opened(tmp_path, now=later)
    assert peer_import.sweep(state, later) == [first]
    assert not folder_of(tmp_path, first).exists()
    second = opened(tmp_path)
    assert second != first and peer_import.sweep(state) == []  # touched just now


def test_a_part_touches_the_import_so_it_is_not_swept_while_it_is_sent(tmp_path):
    state = tmp_path / "state"
    import_id = opened(tmp_path)
    folder = folder_of(tmp_path, import_id)
    old = time.time() - peer_import.EXPIRES - 60
    for path in (folder, folder / peer_import.FILE, folder / peer_import.OPENED):
        os.utime(path, (old, old))
    peer_import.add_part(state, import_id, 0, b"abc")
    assert peer_import.sweep(state) == []


def test_opening_one_sweeps_one_left_an_hour(tmp_path):
    first = opened(tmp_path)
    folder = folder_of(tmp_path, first)
    old = time.time() - peer_import.EXPIRES - 60
    for path in (folder, folder / peer_import.FILE, folder / peer_import.OPENED):
        os.utime(path, (old, old))
    assert opened(tmp_path) != first and not folder.exists()


def test_staged_folder_refuses_any_other_path(tmp_path):
    state = tmp_path / "state"
    import_id = opened(tmp_path)
    folder = folder_of(tmp_path, import_id)
    assert peer_import.staged_folder(state, folder) == folder
    assert peer_import.staged_folder(state, str(folder)) == folder
    link = tmp_path / "link"
    link.symlink_to(folder)
    elsewhere = tmp_path / "elsewhere" / f"import-{import_id}"
    elsewhere.mkdir(parents=True)
    push = state / "peer" / f"push-{import_id}"
    push.mkdir()
    linked_in = state / "peer" / "import-ffffffffffffffff"
    linked_in.symlink_to(folder)
    for given in (link, elsewhere, push, linked_in, state / "peer" / "import-xyz", tmp_path / "state" / "peer"):
        with pytest.raises(peer_import.StagingError):
            peer_import.staged_folder(state, given)


def test_the_staged_file_is_0600_in_a_0700_folder(tmp_path):
    import_id = opened(tmp_path)
    folder = folder_of(tmp_path, import_id)
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "state" / "peer").stat().st_mode) == 0o700
    for name in (peer_import.FILE, peer_import.OPENED):
        assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600


def test_a_file_bigger_than_eight_gib_is_refused_before_anything_is_made(tmp_path):
    with pytest.raises(peer_import.StagingError, match="too big") as e:
        opened(tmp_path, size=peer_file.IMPORT_MAX + 1)
    assert e.value.status == 413 and not (tmp_path / "state").exists()
    for size in (0, -1, "12", True):
        with pytest.raises(peer_import.StagingError) as e:
            opened(tmp_path, size=size)
        assert e.value.status == 400
    assert opened(tmp_path, size=peer_file.IMPORT_MAX)


def test_a_staged_file_planted_as_a_link_is_never_written_through(tmp_path):
    state = tmp_path / "state"
    import_id = opened(tmp_path)
    target = tmp_path / "victim"
    target.write_bytes(b"precious")
    staged = folder_of(tmp_path, import_id) / peer_import.FILE
    staged.unlink()
    staged.symlink_to(target)
    with pytest.raises((peer_import.StagingError, OSError)):
        peer_import.add_part(state, import_id, 0, b"abc")
    assert target.read_bytes() == b"precious"


def test_removing_an_import_deletes_its_folder_whole(tmp_path):
    import_id = opened(tmp_path)
    folder = folder_of(tmp_path, import_id)
    peer_import.remove(folder)
    assert not folder.exists()
