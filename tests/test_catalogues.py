"""catalogues.py: the public catalogue file's name, its gzip and sidecar, the Keep rule and the manifest."""

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
                                  "indexes-sx-20261124T0312Z.sqlite.gz"])
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


def test_a_manifest_lists_the_new_file_first_and_the_kept_ones():
    old = [catalogues.Published(catalogues.name_for(s, at), s, "m", 1, 2, "h", {"ug": 1}).as_json()
           for s, at in [(17, d(2026, 11, 17)), (17, d(2026, 11, 10)), (15, d(2026, 4, 1))]]
    new = catalogues.Published(catalogues.name_for(17, d(2026, 11, 24)), 17, "m", 3, 4, "n", {"ug": 2})
    out = catalogues.manifest_with({"format": 1, "files": old}, new, now=d(2026, 11, 24))
    assert out["format"] == 1
    assert [e["file"] for e in out["files"]] == [new.name, old[0]["file"]]
    assert out["files"][0] == new.as_json()
    assert catalogues.manifest_with(None, new, now=d(2026, 11, 24))["files"] == [new.as_json()]
