"""catalogues.py: the public catalogue file's name, its gzip and sidecar, the Keep rule."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime

import pytest
import test_index_transfer as tt

from caracole import catalogues, db

NOW = datetime(2026, 11, 24, 3, 12, 40, tzinfo=UTC)


def d(y, m, day):
    return datetime(y, m, day, 3, 0, tzinfo=UTC)


@pytest.fixture
def out(tmp_path):
    (tmp_path / "out").mkdir()
    return tmp_path / "out"


@pytest.fixture
def conn_with_index(conn):
    tt.ug_sitemap(conn, "sitemap1.xml", ["a/b-chords-1", "a/c-chords-2", "d/e-chords-3"], tt.LATE)
    tt.ug_listed(conn, ["sitemap1.xml"], tt.LATE)
    return conn


def test_a_name_holds_the_schema_and_the_minute():
    at = datetime(2026, 11, 24, 3, 12, 40, tzinfo=UTC)
    assert catalogues.name_for(17, at) == "indexes-s17-20261124T0312Z.sqlite.gz"
    assert catalogues.read_name("indexes-s17-20261124T0312Z.sqlite.gz") == catalogues.Named(17, at.replace(second=0))


@pytest.mark.parametrize("name", ["indexes.json", "indexes-s17-20261124T0312Z.sqlite.gz.next",
                                  "indexes2-s17-20261124T0312Z.sqlite.gz", "indexes-s17-20261340T0312Z.sqlite.gz",
                                  "indexes-sx-20261124T0312Z.sqlite.gz", "indexes-s017-20261124T0312Z.sqlite.gz",
                                  "indexes-s0-20261124T0312Z.sqlite.gz", "indexes-s17-2026112\u0664T0312Z.sqlite.gz",
                                  "indexes-s1\u0667-20261124T0312Z.sqlite.gz",
                                  "indexes-s1234567890-20261124T0312Z.sqlite.gz"])
def test_other_names_are_none(name):
    assert catalogues.read_name(name) is None


def test_publish_writes_a_gzip_that_unpacks_to_a_mergeable_export(conn_with_index, out):
    p = catalogues.publish(conn_with_index, out, now=NOW, last=None)
    data = (out / p.name).read_bytes()
    assert data[4:8] == b"\0\0\0\0"  # mtime 0
    assert hashlib.sha256(data).hexdigest() == p.sha256
    assert len(gzip.decompress(data)) == p.raw_bytes
    assert p.bytes == len(data) and p.rows["ug"] == 3
    assert json.loads((out / "published.json").read_text())["file"] == p.name
    assert catalogues.published(out) == p
    assert sorted(x.name for x in out.iterdir()) == sorted([p.name, "published.json"])


def test_publish_refuses_a_name_that_exists(conn_with_index, out):
    catalogues.publish(conn_with_index, out, now=NOW, last=None)
    with pytest.raises(catalogues.PublishError, match="exists"):
        catalogues.publish(conn_with_index, out, now=NOW, last=None)


def test_publish_refuses_an_index_not_built_whole(conn, out):
    with pytest.raises(catalogues.PublishError, match="built whole"):
        catalogues.publish(conn, out, now=NOW, last=None)
    assert list(out.iterdir()) == []


def test_publish_refuses_a_tenth_fewer_rows_unless_forced(conn_with_index, out):
    last = catalogues.Published("indexes-s17-20261117T0312Z.sqlite.gz", db.SCHEMA_VERSION, "x", 1, 1, "0",
                                {"ug": 4})
    with pytest.raises(catalogues.PublishError, match="3 rows, a tenth fewer than the last file's 4: --force"):
        catalogues.publish(conn_with_index, out, now=NOW, last=last)
    assert list(out.iterdir()) == []
    assert catalogues.publish(conn_with_index, out, now=NOW, last=None).rows["ug"] == 3


def test_publish_keeps_only_its_newest_file_in_the_folder(conn_with_index, out):
    old = out / "indexes-s16-20261101T0000Z.sqlite.gz"
    old.write_bytes(b"x")
    (out / "other.txt").write_text("y")
    p = catalogues.publish(conn_with_index, out, now=NOW, last=None)
    assert not old.exists() and (out / p.name).exists() and (out / "other.txt").exists()


def test_the_keep_rule():
    names = [catalogues.name_for(17, d(2026, 11, 24)), catalogues.name_for(17, d(2026, 11, 17)),
             catalogues.name_for(17, d(2026, 11, 10)), catalogues.name_for(16, d(2026, 11, 3)),
             catalogues.name_for(15, d(2026, 4, 1)), "indexes.json"]
    assert catalogues.kept(names, schema=17, now=d(2026, 11, 24)) == set(names[:2] + [names[3], "indexes.json"])


def test_the_publishing_schemas_two_newest_stay_whatever_their_age():
    names = [catalogues.name_for(17, d(2025, 1, 10)), catalogues.name_for(17, d(2025, 1, 3)),
             catalogues.name_for(17, d(2024, 12, 27)), catalogues.name_for(16, d(2025, 1, 1))]
    assert catalogues.kept(names, schema=17, now=d(2026, 11, 24)) == set(names[:2])


def test_a_missing_sidecar_is_none_and_a_corrupt_or_wrongly_typed_one_is_refused(out):
    assert catalogues.published(out) is None
    for text in ["{not json", "[]", '{"file": "x"}', '{"file": "x", "schema": "s", "made": "m", "bytes": 1, '
                 '"raw_bytes": 1, "sha256": "h", "sites": {}}', '{"file": "x", "schema": 1, "made": "m", "bytes": 1, '
                 '"raw_bytes": 1, "sha256": "h", "sites": []}']:
        (out / "published.json").write_text(text)
        with pytest.raises(catalogues.PublishError, match="sidecar"):
            catalogues.published(out)


def test_a_sidecar_that_cant_be_written_leaves_no_file_and_is_a_publish_error(conn_with_index, out, monkeypatch):
    import os

    real = os.replace

    def replace(src, dst):
        if str(dst).endswith("published.json"):
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(catalogues.PublishError, match="disk full"):
        catalogues.publish(conn_with_index, out, now=NOW, last=None)
    assert list(out.iterdir()) == []


def test_a_publish_whose_cleanup_fails_too_still_says_why_it_failed(conn_with_index, out, monkeypatch):
    from pathlib import Path


    def refuse(self, missing_ok=False):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(Path, "unlink", refuse)
    import os

    def replace(src, dst):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(catalogues.PublishError, match="can't write"):
        catalogues.publish(conn_with_index, out, now=NOW, last=None)


def test_a_value_holding_a_path_of_this_machine_refuses_the_file(conn_with_index, out, tmp_path):
    private = [str(tmp_path / "state")]
    db.kv_set(conn_with_index, "ug:index:refreshed_at", f"read from {private[0]}/x")
    with pytest.raises(catalogues.PublishError, match=r"kv\.value holds a path of this machine: 'read from"):
        catalogues.publish(conn_with_index, out, now=NOW, last=None, private=private)
    assert list(out.iterdir()) == []


def test_a_title_holding_the_home_folder_refuses_the_file(conn_with_index, out):
    from pathlib import Path

    tt.artist_songs(conn_with_index, "slug", "Artist", [f"Song {Path.home()}"])
    with pytest.raises(catalogues.PublishError, match="lacuerda_index"):
        catalogues.publish(conn_with_index, out, now=NOW, last=None, private=[str(Path.home())])
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("value", ["/home/someone/x", "/root/x", "/var/lib/caracole", "/nix/var", "/tmp/x",
                                   "/etc/caracole/service", "/run/user/1000", "/usr/share", "/opt/x", "/srv/x",
                                   "/mnt/x", "/media/x", "/Users/someone", "/data/user/0", "/sdcard/Music",
                                   "/storage/emulated/0", "file:///x", "x /nix/store/abc-foo y"])
def test_a_machine_root_or_the_nix_store_refuses_the_file(conn_with_index, out, value):
    db.kv_set(conn_with_index, "ug:index:refreshed_at", value)
    with pytest.raises(catalogues.PublishError, match="a path of this machine"):
        catalogues.publish(conn_with_index, out, now=NOW, last=None)
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("value", ["/Dead Kennedys", "/\\/", "/rif", "AC/DC", "/home", "a /home/x"])
def test_a_name_that_begins_with_a_slash_is_no_path(conn_with_index, out, value):
    """Sites' names may begin with "/" (an artist, a title): only a machine's roots and its own folders refuse."""
    tt.artist_songs(conn_with_index, "slug", value, [value])
    db.kv_set(conn_with_index, "ug:index:refreshed_at", value)
    catalogues.publish(conn_with_index, out, now=NOW, last=None, private=["/"])


def test_a_folder_of_this_config_anywhere_in_a_value_refuses_the_file(conn_with_index, out, tmp_path):
    db.kv_set(conn_with_index, "ug:index:refreshed_at", f"somewhere {tmp_path}/lib")
    with pytest.raises(catalogues.PublishError, match="a path of this machine"):
        catalogues.publish(conn_with_index, out, now=NOW, last=None, private=[str(tmp_path)])


def test_the_cleanup_of_older_files_never_fails_a_publish(conn_with_index, out, monkeypatch):
    from pathlib import Path

    (out / catalogues.name_for(db.SCHEMA_VERSION, d(2026, 11, 17))).write_bytes(b"old")
    real = Path.unlink

    def unlink(self, missing_ok=False):
        if self.name.startswith("indexes-") and self.parent == out:
            raise PermissionError(13, "Permission denied")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    p = catalogues.publish(conn_with_index, out, now=NOW, last=None)
    assert (out / p.name).exists()


def test_a_published_file_and_its_sidecar_hold_no_path(conn_with_index, out):
    p = catalogues.publish(conn_with_index, out, now=NOW, last=None, private=[str(out)])
    data = (out / p.name).read_bytes()
    assert data[3] & 0x08 == 0
    assert str(out) not in (out / "published.json").read_text()


class Told:
    """A ``catalogues.Progress`` that keeps what it is told."""

    def __init__(self) -> None:
        self.events: list = []

    def exporting(self) -> None:
        self.events.append("exporting")

    def copied(self, table: str, rows: int) -> None:
        self.events.append(("copied", table, rows))

    def omitting(self) -> None:
        self.events.append("omitting")

    def checking(self) -> None:
        self.events.append("checking")

    def compressing(self, done: int, total: int) -> None:
        self.events.append(("compressing", done, total))


def test_publish_tells_each_step_as_it_goes_and_the_gzip_by_the_bytes_it_read(conn_with_index, out, monkeypatch):
    monkeypatch.setattr(catalogues, "CHUNK", 4096)
    told = Told()

    p = catalogues.publish(conn_with_index, out, now=NOW, last=None, progress=told)

    from caracole import index_transfer as transfer
    tables = [t for site in transfer.SITES.values() for t in site.tables]
    kinds = [e if isinstance(e, str) else e[0] for e in told.events]
    assert kinds == ["exporting", *["copied"] * len(tables), "omitting", "checking",
                     *["compressing"] * (kinds.count("compressing"))]
    assert [e[1] for e in told.events if e[0] == "copied"] == tables
    assert ("copied", "ug_index", 3) in told.events
    gzipped = [e[1:] for e in told.events if e[0] == "compressing"]
    assert gzipped[0] == (0, p.raw_bytes) and gzipped[-1] == (p.raw_bytes, p.raw_bytes)
    assert len(gzipped) == 1 + -(-p.raw_bytes // 4096)  # the start, then a chunk at a time
    assert [done for done, _ in gzipped] == sorted(done for done, _ in gzipped)


def test_a_publish_told_nothing_writes_the_same_file(conn_with_index, out, tmp_path):
    (tmp_path / "other").mkdir()
    told = catalogues.publish(conn_with_index, out, now=NOW, last=None, progress=Told())
    quiet = catalogues.publish(conn_with_index, tmp_path / "other", now=NOW, last=None)
    assert told == quiet and (out / told.name).read_bytes() == (tmp_path / "other" / quiet.name).read_bytes()


def test_a_progress_that_cant_be_told_is_no_error_of_the_folder_and_leaves_nothing(conn_with_index, out):
    class Cut(Told):
        def checking(self) -> None:
            raise BrokenPipeError(32, "Broken pipe")

    with pytest.raises(BrokenPipeError):
        catalogues.publish(conn_with_index, out, now=NOW, last=None, progress=Cut())
    assert list(out.iterdir()) == []
