"""``caracole index merge --delete --progress -- FILE``: the merge caracole serve queues for the index pages a phone
posted (``POST /peer/index``, web/jobs.py ``index_merge_job``), its one stage as get.py's JSON lines, the file deleted
once it is merged or refused, and kept for Try again when no backup could be made first."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_index_transfer as tt
from typer.testing import CliRunner

from caracole import backup, db
from caracole import index_transfer as transfer
from caracole.get import read_progress_line
from caracole.web import jobs


def invoke(tmp_path: Path, *args: str):
    from caracole.cli import build_app

    config = tmp_path / "caracole.toml"
    config.write_text(f'data_dir = "{tmp_path / "data"}"\n', encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(config), "index", *args])


@pytest.fixture
def state(tmp_path, monkeypatch) -> Path:
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    folder = tmp_path / "data" / "state"
    folder.mkdir(parents=True)
    db.connect(folder / "caracole.sqlite").close()
    return folder


def phone_reads(tmp_path: Path, name: str = "index-0123456789abcdef.sqlite") -> Path:
    """An export of a phone's reads, as POST /peer/index stages one."""
    phone = tt.database(tmp_path, "phone")
    try:
        tt.harp_page(phone, "artist/1178/billy-joel", ["Piano Man", "Honesty"], tt.LATE)
        path = tmp_path / "staged" / name
        path.parent.mkdir()
        transfer.export(phone, path, now=tt.NOW, pages={"harptabs": ["artist/1178/billy-joel"]})
    finally:
        phone.close()
    return path


def events(output: str) -> list[dict]:
    return [e for e in map(read_progress_line, output.splitlines()) if e is not None]


def test_the_queued_merge_reports_its_stage_and_deletes_the_file_once_merged(tmp_path, state):
    path = phone_reads(tmp_path)
    args = jobs.index_merge_job(path)["steps"][0][1]
    assert args == ("index", "merge", "--delete", "--progress", "--", str(path))  # serve's spelling, as it queues it

    result = invoke(tmp_path, *args[1:])

    assert result.exit_code == 0, result.output
    assert events(result.stdout) == [
        {"stage": "merge", "state": "running", "detail": ""},
        {"stage": "merge", "state": "done", "detail": "harptabs.com: 1 artist page"},
    ]
    assert f"Merged {path} into {state / 'caracole.sqlite'}:" in result.stdout
    assert not path.exists()
    conn = db.connect(state / "caracole.sqlite")
    try:
        assert conn.execute("SELECT count(*) FROM harptabs_artist_tabs").fetchone()[0] == 2
    finally:
        conn.close()


def test_a_merge_that_takes_nothing_says_so_and_still_deletes_the_file(tmp_path, state):
    path = phone_reads(tmp_path)
    copy = tmp_path / "again.sqlite"
    copy.write_bytes(path.read_bytes())
    assert invoke(tmp_path, "merge", "--", str(path)).exit_code == 0
    assert path.exists()  # no --delete: kept

    result = invoke(tmp_path, "merge", "--delete", "--progress", "--", str(copy))

    assert result.exit_code == 0, result.output
    assert events(result.stdout)[-1] == {"stage": "merge", "state": "done", "detail": "Nothing read more recently"}
    assert not copy.exists()


def test_a_refused_file_fails_its_stage_in_its_words_and_is_deleted(tmp_path, state):
    path = tmp_path / "index-0123456789abcdef.sqlite"
    sqlite3.connect(path).close()

    result = invoke(tmp_path, "merge", "--delete", "--progress", "--", str(path))

    assert result.exit_code == 2
    [running, failed] = events(result.stdout)
    assert running["state"] == "running" and failed["state"] == "failed"
    assert failed["detail"].startswith(f"{path} is no index export of caracole's")
    assert "no index export" in result.stderr
    assert not path.exists()  # it can never be merged here


def test_no_room_for_the_backup_keeps_the_file_for_try_again(tmp_path, state, monkeypatch):
    path = phone_reads(tmp_path)
    monkeypatch.setattr(backup, "disk_usage", lambda p: SimpleNamespace(total=1, used=1, free=1))

    result = invoke(tmp_path, "merge", "--delete", "--progress", "--", str(path))

    assert result.exit_code == 2
    assert events(result.stdout)[-1]["state"] == "failed"
    assert "no room" in events(result.stdout)[-1]["detail"]
    assert path.exists()  # the next try merges it


def test_without_progress_it_says_what_it_always_said(tmp_path, state):
    path = phone_reads(tmp_path)

    result = invoke(tmp_path, "merge", "--delete", str(path))

    assert result.exit_code == 0, result.output
    assert events(result.stdout) == []
    assert result.stdout.splitlines()[1] == f"Merged {path} into {state / 'caracole.sqlite'}:"
    assert not path.exists()


def test_a_file_missing_is_a_failed_stage(tmp_path, state):
    path = tmp_path / "gone.sqlite"

    result = invoke(tmp_path, "merge", "--delete", "--progress", "--", str(path))

    assert result.exit_code == 2
    assert json.dumps(events(result.stdout)[-1]).count("no such file") == 1
