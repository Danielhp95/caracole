"""``caracole index merge --delete --progress -- FILE``: the merge caracole serve queues for the index pages a phone
posted (``POST /peer/index``, web/jobs.py ``index_merge_job``), its one stage as get.py's JSON lines, the file deleted
once it is merged or refused, and kept for Try again when no backup could be made first."""

from __future__ import annotations

import json
import os
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
    assert events(result.stdout)[-1] == {"stage": "merge", "state": "done", "detail": "Nothing newer"}
    assert not copy.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores a folder's mode")
def test_an_export_into_a_folder_it_cant_write_is_a_plain_refusal(tmp_path, state):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        result = invoke(tmp_path, "export", str(locked / "indexes.sqlite"))
    finally:
        locked.chmod(0o755)

    assert result.exit_code == 2, result.output
    assert "can't write" in result.stderr
    assert "Traceback" not in result.stderr and "bug in caracole" not in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_a_refused_file_serve_staged_fails_its_stage_in_its_words_and_is_deleted(tmp_path, state):
    path = state / "peer" / "index-0123456789abcdef.sqlite"
    path.parent.mkdir()
    sqlite3.connect(path).close()

    result = invoke(tmp_path, "merge", "--delete", "--progress", "--", str(path))

    assert result.exit_code == 2
    [running, failed] = events(result.stdout)
    assert running["state"] == "running" and failed["state"] == "failed"
    assert failed["detail"].startswith(f"{path} is no index export of caracole's")
    assert "no index export" in result.stderr
    assert not path.exists()  # it can never be merged here


def test_delete_never_deletes_the_database_itself_refused(tmp_path, state):
    database = state / "caracole.sqlite"

    result = invoke(tmp_path, "merge", "--delete", "--progress", "--", str(database))

    assert result.exit_code == 2
    assert events(result.stdout)[-1] == {"stage": "merge", "state": "failed",
                                         "detail": f"{database} is the database itself"}
    assert database.exists()
    conn = db.connect(database)  # whole, and still caracole's
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


@pytest.mark.parametrize("name", ["wanted.txt", "backups/caracole-before-merge.sqlite", "index-0123456789abcdef.sqlite"])
def test_delete_keeps_a_refused_file_named_by_hand(tmp_path, state, name):
    """Only a file of serve's staging (state_dir/peer/index-<16 hex>.sqlite) is deleted refused: a typo, a backup,
    or an export's look-alike elsewhere stays as it was."""
    path = tmp_path / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if name.endswith(".sqlite"):
        sqlite3.connect(path).close()
    else:
        path.write_text("Radiohead - Creep\n", encoding="utf-8")
    before = path.read_bytes()

    result = invoke(tmp_path, "merge", "--delete", "--progress", "--", str(path))

    assert result.exit_code == 2
    assert events(result.stdout)[-1]["state"] == "failed"
    assert path.read_bytes() == before


def test_a_database_it_cant_open_fails_its_stage_and_keeps_the_file_for_try_again(tmp_path, state):
    path = phone_reads(tmp_path)
    conn = sqlite3.connect(state / "caracole.sqlite")
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")  # a newer caracole's
    conn.close()

    result = invoke(tmp_path, "merge", "--delete", "--progress", "--", str(path))

    assert result.exit_code == 2
    [running, failed] = events(result.stdout)
    assert running["state"] == "running"
    assert failed["state"] == "failed" and failed["detail"].startswith("Not merged: couldn't get the lock or the database")
    assert path.exists()


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


# --- caracole index publish ---------------------------------------------------------------------------------------


def built(state: Path) -> None:
    conn = db.connect(state / "caracole.sqlite")
    try:
        tt.ug_sitemap(conn, "sitemap1.xml", ["a/b-chords-1", "a/c-chords-2"], tt.LATE)
        tt.ug_listed(conn, ["sitemap1.xml"], tt.LATE)
    finally:
        conn.close()


def test_index_publish_prints_the_file_and_its_rows(tmp_path, state):
    built(state)
    out = tmp_path / "pub"
    out.mkdir()

    result = invoke(tmp_path, "publish", str(out))

    assert result.exit_code == 0, result.output
    (gz,) = out.glob("indexes-s*.sqlite.gz")
    assert f"Published {gz}" in result.stdout and "ug: 2 rows." in result.stdout


def test_index_publish_says_what_it_does_as_it_goes_a_line_a_step_where_no_terminal_is(tmp_path, state):
    import re

    built(state)
    out = tmp_path / "pub"
    out.mkdir()

    result = invoke(tmp_path, "publish", str(out))

    assert result.exit_code == 0, result.output
    (gz,) = out.glob("indexes-s*.sqlite.gz")
    lines = result.stdout.splitlines()
    assert lines[:9] == [
        f"Exporting every site's index into {out}...",
        "  Ultimate Guitar: ug_index 2 rows copied, ug_artist_tabs 0, ug_directory 0.",
        "  LaCuerda: lacuerda_index 0 rows copied.",
        "  gtptabs.com: gtptabs_index 0 rows copied.",
        "  MuseScore: musescore_index 0 rows copied.",
        "  harptabs.com: harptabs_index 0 rows copied, harptabs_artists 0, harptabs_artist_tabs 0.",
        "  gametabs.net: gametabs_index 0 rows copied, gametabs_games 0, gametabs_game_tabs 0.",
        "Leaving out what stays private, and compacting the export...",
        "Checking the export: no path of this machine in it, then SQLite's quick check...",
    ]
    assert re.fullmatch(r"Compressing \u00b7 (\d+) of \1 KB", lines[9]), lines[9]  # one chunk: one line, not four
    assert lines[10].startswith(f"Published {gz} (") and lines[11:] == [
        "  ug: 2 rows.", "  lacuerda: 0 rows.", "  gtptabs: 0 rows.", "  musescore: 0 rows.", "  harptabs: 0 rows.",
        "  gametabs: 0 rows."]
    assert "\r" not in result.stdout


def test_index_publish_whose_output_is_cut_off_still_publishes_and_says_no_disk_error(tmp_path, state, monkeypatch):
    """``caracole index publish DIR | head -1``: once the pipe is closed, nothing more is said, the file is
    published, and a broken stdout is never worded as the folder's error."""
    from caracole.commands import index
    from caracole.progress import Console

    class Closed:
        def write(self, text):
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            raise BrokenPipeError(32, "Broken pipe")

        def isatty(self):
            return False

    monkeypatch.setattr(index, "console", lambda: Console(Closed()))
    built(state)
    out = tmp_path / "pub"
    out.mkdir()

    result = invoke(tmp_path, "publish", str(out))

    assert result.exit_code == 0, (result.output, result.exception)
    assert "can't write" not in result.stderr
    (gz,) = out.glob("indexes-s*.sqlite.gz")
    assert json.loads((out / "published.json").read_text())["file"] == gz.name


def compressed(monkeypatch, console, *, chunks: int = 100, step: float = 0.05) -> None:
    """What ``index publish``'s report makes of a gzip of ``chunks`` MiB read a chunk every ``step`` seconds."""
    from caracole.commands import index

    now = [0.0]
    monkeypatch.setattr(index, "clock", lambda: now[0])
    report = index._Publishing(console, Path("/pub"))
    mib = 1 << 20
    report.compressing(0, chunks * mib)
    for n in range(1, chunks + 1):
        now[0] += step
        report.compressing(n * mib, chunks * mib)


def test_index_publish_writes_the_gzips_progress_a_line_a_quarter_where_no_terminal_is(monkeypatch):
    import io

    from caracole.progress import Console

    stream = io.StringIO()
    compressed(monkeypatch, Console(stream, live=False, color=False))
    assert stream.getvalue().splitlines() == [
        "Compressing \u00b7 25 of 100 MB", "Compressing \u00b7 50 of 100 MB", "Compressing \u00b7 75 of 100 MB",
        "Compressing \u00b7 100 of 100 MB"]


def test_index_publish_updates_the_gzips_live_line_a_few_times_a_second(monkeypatch):
    import io

    from caracole.progress import Console

    stream = io.StringIO()
    compressed(monkeypatch, Console(stream, live=True, color=False, width=lambda: 200))
    shown = [part.strip() for part in stream.getvalue().split("\r") if part.strip()]
    assert shown[0] == "Compressing \u00b7 0 of 100 MB" and shown[-1] == "Compressing \u00b7 100 of 100 MB"
    assert len(shown) <= 1 + 5 / 0.25 + 1  # 5 s of chunks: at most four a second, and the last
    assert len(shown) >= 5 / 0.25 - 1  # and it does move as it goes
    assert "\n" not in stream.getvalue()


def high_sidecar(out: Path) -> None:
    (out / "published.json").write_text(json.dumps({
        "file": "indexes-s17-20261117T0312Z.sqlite.gz", "schema": 17, "made": "2026-11-17T03:12:00Z", "bytes": 1,
        "raw_bytes": 1, "sha256": "0", "sites": {"ug": 1000}}))


def test_index_publish_refuses_a_site_with_far_fewer_rows_than_the_last_file_unless_forced(tmp_path, state):
    built(state)
    out = tmp_path / "pub"
    out.mkdir()
    high_sidecar(out)

    result = invoke(tmp_path, "publish", str(out))

    assert result.exit_code == 1 and "--force publishes it" in result.stderr
    assert [p.name for p in out.iterdir()] == ["published.json"]

    forced = invoke(tmp_path, "publish", str(out), "--force")

    assert forced.exit_code == 0, forced.output
    (gz,) = out.glob("indexes-s*.sqlite.gz")
    assert json.loads((out / "published.json").read_text())["file"] == gz.name


def test_index_publish_refuses_a_corrupt_sidecar(tmp_path, state):
    built(state)
    out = tmp_path / "pub"
    out.mkdir()
    (out / "published.json").write_text("{nope")

    result = invoke(tmp_path, "publish", str(out))

    assert result.exit_code == 1 and "sidecar" in result.stderr
    assert list(out.glob("indexes-*")) == []


def test_index_publish_kept_prints_a_repeated_name_once(tmp_path, state):
    from caracole import catalogues

    old = catalogues.name_for(db.SCHEMA_VERSION - 1, tt.NOW.replace(year=2020))

    result = invoke(tmp_path, "publish", str(tmp_path), "--kept", old, "--kept", old)

    assert result.stdout.split() == [old]


def test_index_publish_exits_1_and_leaves_no_file_when_refused(tmp_path, state):
    out = tmp_path / "pub"
    out.mkdir()

    result = invoke(tmp_path, "publish", str(out))

    assert result.exit_code == 1
    assert "built whole" in result.stderr
    assert list(out.iterdir()) == []


def test_index_publish_kept_prints_what_to_delete(tmp_path, state):
    from datetime import UTC, datetime, timedelta

    from caracole import catalogues

    now = datetime.now(UTC)
    names = [catalogues.name_for(db.SCHEMA_VERSION - 1, now - timedelta(days=400)),  # an old schema, long past
             catalogues.name_for(db.SCHEMA_VERSION, now - timedelta(days=14)),
             catalogues.name_for(db.SCHEMA_VERSION, now - timedelta(days=7)),
             catalogues.name_for(db.SCHEMA_VERSION, now - timedelta(days=1)),
             "indexes.json"]
    args = [x for n in names for x in ("--kept", n)]

    result = invoke(tmp_path, "publish", str(tmp_path), *args)

    assert result.exit_code == 0, result.output
    assert result.stdout.split() == [names[0], names[1]]


def test_index_publish_is_refused_beside_the_service(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from caracole.cli import build_app

    marker = tmp_path / "service"
    marker.write_text(f'state_dir = "{tmp_path / "svc-state"}"\nlibrary_dir = "{tmp_path / "svc-lib"}"\n')
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CARACOLE_SERVICE_FILE", str(marker))

    result = CliRunner().invoke(build_app(), ["index", "publish", str(tmp_path)])

    assert result.exit_code == 2
    assert "caracole --home index publish" in " ".join(result.stderr.split())


def test_index_publish_kept_needs_no_config_and_answers_beside_the_service(tmp_path, monkeypatch):
    """publish-indexes' prune runs as the owner's user on the service's machine: --kept reads nothing, so the
    service's guard never refuses it."""
    from datetime import UTC, datetime

    from typer.testing import CliRunner

    from caracole import catalogues
    from caracole.cli import build_app

    marker = tmp_path / "service"
    marker.write_text(f'state_dir = "{tmp_path / "svc-state"}"\nlibrary_dir = "{tmp_path / "svc-lib"}"\n')
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CARACOLE_SERVICE_FILE", str(marker))
    old = catalogues.name_for(db.SCHEMA_VERSION - 1, datetime(2020, 1, 1, tzinfo=UTC))

    result = CliRunner().invoke(build_app(), ["index", "publish", str(tmp_path / "pub"), "--kept", old])

    assert result.exit_code == 0, result.output
    assert result.stdout.split() == [old]
    assert not (tmp_path / "home").exists() and not (tmp_path / "svc-state").exists()
