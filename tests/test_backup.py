"""backup.py: a whole copy of the database in state_dir/backups/, the newest few kept, none made without room."""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from caracole import backup, db

NOW = datetime(2026, 10, 29, 3, 45, 12, tzinfo=UTC)


def old_copy(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"an older copy")
    return path


def test_a_copy_is_the_database_whole_named_by_its_time_and_private(conn, tmp_path):
    db.kv_set(conn, "harptabs:index:complete_at", "2026-10-28T00:01:50Z")
    state = tmp_path / "state"

    made = backup.make(conn, state, NOW)

    assert isinstance(made, backup.Made)
    assert made.backup.path == state / "backups" / "caracole-2026-10-29T034512Z.sqlite"
    assert made.backup.at == NOW and made.backup.label is None
    assert made.backup.size == made.backup.path.stat().st_size > 0
    copy = sqlite3.connect(made.backup.path)
    try:
        assert copy.execute("SELECT value FROM kv WHERE key = 'harptabs:index:complete_at'").fetchone() == (
            "2026-10-28T00:01:50Z",)
        assert copy.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    finally:
        copy.close()
    assert stat.S_IMODE(made.backup.path.stat().st_mode) == 0o600
    assert stat.S_IMODE((state / "backups").stat().st_mode) == 0o700
    assert not list((state / "backups").glob("*.part"))


def test_the_newest_three_are_kept_and_the_older_ones_deleted(conn, tmp_path):
    folder = tmp_path / "state" / "backups"
    oldest = old_copy(folder, "caracole-2026-10-25T034500Z.sqlite")
    older = old_copy(folder, "caracole-2026-10-26T034500Z.sqlite")
    merge = old_copy(folder, "caracole-2026-10-27T120000Z-before-merge.sqlite")
    last = old_copy(folder, "caracole-2026-10-28T034500Z.sqlite")
    theirs = old_copy(folder, "notes.txt")
    other = old_copy(folder, "caracole-latest.sqlite")
    stale = old_copy(folder, "caracole-2026-10-28T034500Z.sqlite.1f2e3d.part")

    made = backup.make(conn, tmp_path / "state", NOW)

    assert made.deleted == (oldest, older)
    assert [b.path.name for b in backup.backups(tmp_path / "state")] == [
        merge.name, last.name, "caracole-2026-10-29T034512Z.sqlite"]
    assert theirs.exists() and other.exists()  # not caracole's copies: never touched
    assert not stale.exists()  # what a copy cut short left
    assert made.kept == 3


def test_keep_says_how_many(conn, tmp_path):
    folder = tmp_path / "state" / "backups"
    for day in (25, 26, 27, 28):
        old_copy(folder, f"caracole-2026-10-{day}T034500Z.sqlite")

    backup.make(conn, tmp_path / "state", NOW, keep=1)

    assert [b.path.name for b in backup.backups(tmp_path / "state")] == ["caracole-2026-10-29T034512Z.sqlite"]


def test_a_merges_copy_says_so_in_its_name(conn, tmp_path):
    made = backup.make(conn, tmp_path / "state", NOW, label="before-merge")

    assert made.backup.path.name == "caracole-2026-10-29T034512Z-before-merge.sqlite"
    assert backup.backups(tmp_path / "state")[0].label == "before-merge"


def test_the_copy_is_the_database_as_it_stood_when_it_began_whatever_another_connection_writes(conn, tmp_path):
    """SQLite's VACUUM INTO reads one snapshot: a transaction another connection commits while the copy is
    being made is in the database, and not in the copy, and the copy is whole."""
    conn.execute("CREATE TABLE pairs (n INTEGER PRIMARY KEY, half TEXT NOT NULL)")
    with db.savepoint(conn, "fill"):
        conn.executemany("INSERT INTO pairs (half) VALUES (?)", [("x" * 500,) for _ in range(4000)])
    writer = db.connect(tmp_path / "state" / "caracole.sqlite")
    wrote: list[int] = []

    def meanwhile() -> int:
        if not wrote:  # once the copy is under way: a whole transaction of another connection, committed
            with db.savepoint(writer, "during"):
                writer.execute("INSERT INTO kv (key, value) VALUES ('during', 'a')")
                writer.execute("INSERT INTO pairs (half) VALUES ('during')")
            wrote.append(1)
        return 0

    conn.set_progress_handler(meanwhile, 1000)
    try:
        made = backup.make(conn, tmp_path / "state", NOW)
    finally:
        conn.set_progress_handler(None, 0)
        writer.close()

    assert wrote, "the other connection never wrote while the copy was made"
    assert conn.execute("SELECT COUNT(*) FROM pairs").fetchone()[0] == 4001
    copy = sqlite3.connect(made.backup.path)
    try:
        assert copy.execute("SELECT COUNT(*) FROM pairs").fetchone()[0] == 4000
        assert copy.execute("SELECT value FROM kv WHERE key = 'during'").fetchone() is None
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        copy.close()


def test_no_room_no_copy_and_nothing_deleted(conn, tmp_path, monkeypatch, caplog):
    folder = tmp_path / "state" / "backups"
    kept = [old_copy(folder, f"caracole-2026-10-{day}T034500Z.sqlite") for day in (25, 26, 27, 28)]
    monkeypatch.setattr(backup, "disk_usage", lambda path: SimpleNamespace(total=10**9, used=10**9 - 4096,
                                                                        free=4096))

    with caplog.at_level(logging.WARNING, logger="caracole.backup"):
        made = backup.make(conn, tmp_path / "state", NOW)

    assert isinstance(made, backup.Skipped)
    assert made.free == 4096 and made.needed > made.free
    assert "room" in made.reason and str(folder) in made.reason
    assert [p.exists() for p in kept] == [True] * 4
    assert sorted(p.name for p in folder.iterdir()) == sorted(p.name for p in kept)
    assert any("room" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_room_counts_the_pages_in_use_and_some_headroom(conn):
    pages, free_pages, size = (conn.execute(f"PRAGMA {p}").fetchone()[0]
                               for p in ("page_count", "freelist_count", "page_size"))
    assert backup.needed(conn) == (pages - free_pages) * size + backup.HEADROOM


def test_a_copy_that_fails_its_check_is_deleted_and_the_old_ones_stay(conn, tmp_path, monkeypatch):
    folder = tmp_path / "state" / "backups"
    kept = [old_copy(folder, f"caracole-2026-10-{day}T034500Z.sqlite") for day in (26, 27, 28)]
    monkeypatch.setattr(backup, "_check", lambda path: "*** in database main ***\nPage 7: btreeInitPage() error")

    with pytest.raises(backup.BackupError, match="btreeInitPage"):
        backup.make(conn, tmp_path / "state", NOW)

    assert sorted(folder.iterdir()) == kept


def test_listing_reads_the_names_alone(tmp_path):
    folder = tmp_path / "state" / "backups"
    old_copy(folder, "caracole-2026-10-28T034500Z.sqlite")
    old_copy(folder, "caracole-2026-10-27T120000Z-before-merge.sqlite")
    old_copy(folder, "readme")

    listed = backup.backups(tmp_path / "state")

    assert [(b.at, b.label) for b in listed] == [
        (datetime(2026, 10, 27, 12, 0, tzinfo=UTC), "before-merge"),
        (datetime(2026, 10, 28, 3, 45, tzinfo=UTC), None),
    ]
    assert backup.backups(tmp_path / "nowhere") == []


def test_the_folder_is_made_private_even_under_a_loose_umask(conn, tmp_path):
    old = os.umask(0o002)
    try:
        backup.make(conn, tmp_path / "state", NOW)
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "state" / "backups").stat().st_mode) == 0o700


# --- the nightly run's last step ---------------------------------------------------------------------------------


def run_steps(conn, cfg, *steps):
    from test_pipeline import Outbox, services

    from caracole.pipeline import run_pipeline

    out = Outbox()
    return run_pipeline(cfg, conn=conn, services=services(out), steps=list(steps), now=NOW), out


def test_the_backup_is_the_runs_last_step():
    from caracole.pipeline import default_steps

    names = [s.name for s in default_steps()]
    assert names[-2:] == ["todo", "backup"]
    assert next(s for s in default_steps() if s.name == "backup").provider is None


def test_a_run_ends_with_a_copy_which_the_log_names_and_the_summary_leaves_out(conn, cfg, caplog):
    from test_pipeline import step

    from caracole.pipeline import default_steps

    backup_step = next(s for s in default_steps() if s.name == "backup")
    with caplog.at_level(logging.INFO, logger="caracole"):
        report, out = run_steps(conn, cfg, step("sync"), backup_step)

    [made] = backup.backups(cfg.state_dir)
    assert made.path.name == "caracole-2026-10-29T034512Z.sqlite"
    assert report.ok
    assert report.steps["backup"].startswith("backed up to caracole-2026-10-29T034512Z.sqlite (")
    assert report.steps["backup"].endswith("), 1 kept")
    assert "backup" not in report.summary().lower()
    assert any(r.getMessage().startswith(f"Backed up the database to {made.path} (") for r in caplog.records)


def test_a_run_a_step_of_which_failed_makes_no_copy(conn, cfg):
    from test_pipeline import step

    from caracole.pipeline import default_steps

    backup_step = next(s for s in default_steps() if s.name == "backup")
    old_copy(cfg.state_dir / "backups", "caracole-2026-10-28T034500Z.sqlite")
    report, _ = run_steps(conn, cfg, step("render", result=RuntimeError("boom")), backup_step)

    assert [b.path.name for b in backup.backups(cfg.state_dir)] == ["caracole-2026-10-28T034500Z.sqlite"]
    assert report.steps["backup"] == "skipped: a step failed"
    assert ("No backup tonight: a step failed, so the copies of the nights before stay as they are."
            in report.summary().splitlines())


def test_a_run_with_no_room_for_a_copy_says_so_and_still_succeeds(conn, cfg, monkeypatch):
    from test_pipeline import step

    from caracole.pipeline import default_steps

    monkeypatch.setattr(backup, "disk_usage", lambda path: SimpleNamespace(total=1, used=1, free=1))
    backup_step = next(s for s in default_steps() if s.name == "backup")
    report, _ = run_steps(conn, cfg, step("sync"), backup_step)

    assert report.ok
    assert report.steps["backup"].startswith("skipped: no room")
    [line] = [line for line in report.summary().splitlines() if line.startswith("No backup tonight: no room")]
    assert str(cfg.state_dir / "backups") in line


def test_a_copy_that_fails_its_check_fails_the_run(conn, cfg, monkeypatch):
    from test_pipeline import step

    from caracole.pipeline import default_steps

    monkeypatch.setattr(backup, "_check", lambda path: "Page 7: btreeInitPage() error")
    backup_step = next(s for s in default_steps() if s.name == "backup")
    report, out = run_steps(conn, cfg, step("sync"), backup_step)

    assert not report.ok
    assert report.errors == ["backup: the copy failed its check: Page 7: btreeInitPage() error"]
    assert out.sent[-1][0] == "caracole run failed"


# --- caracole backup -----------------------------------------------------------------------------------------------


def invoke(tmp_path, *args):
    from typer.testing import CliRunner

    from caracole.cli import build_app

    path = tmp_path / "caracole.toml"
    path.write_text(f'data_dir = "{tmp_path / "data"}"\n', encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(path), "backup", *args])


def test_caracole_backup_makes_a_copy_now_and_lists_them(tmp_path, monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    state = tmp_path / "data" / "state"
    old_copy(state / "backups", "caracole-2026-10-28T034500Z.sqlite")

    made = invoke(tmp_path)

    assert made.exit_code == 0, made.output
    [old, new] = backup.backups(state)
    assert new.label is None and new.at > old.at
    assert f"Backed up the database to {new.path}" in made.output
    assert "2 kept" in made.output
    listed = invoke(tmp_path, "--list")
    assert listed.exit_code == 0, listed.output
    lines = listed.output.splitlines()
    assert lines[0] == f"2 copies of the database in {state / 'backups'}, the newest last:"
    assert lines[1].startswith("  caracole-2026-10-28T034500Z.sqlite  2026-10-28 03:45 UTC  ")
    assert lines[2].startswith(f"  {new.path.name}  ")


def test_caracole_backup_with_no_room_says_so_and_exits_1(tmp_path, monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    monkeypatch.setattr(backup, "disk_usage", lambda path: SimpleNamespace(total=1, used=1, free=1))

    made = invoke(tmp_path)

    assert made.exit_code == 1
    assert "no room for a copy of the database" in made.output
    assert backup.backups(tmp_path / "data" / "state") == []


def test_caracole_backup_lists_none_before_the_first(tmp_path, monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    listed = invoke(tmp_path, "--list")
    assert listed.exit_code == 0
    assert listed.output == f"No copy of the database in {tmp_path / 'data' / 'state' / 'backups'} yet.\n"
