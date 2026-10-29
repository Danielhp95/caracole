"""caracole/page_log.py: a line in the log for each build of the library page, served or written."""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime

import pytest

from caracole import logs
from caracole.db import SCHEMA_VERSION
from caracole.overrides import Overrides, add_ignore
from caracole.songbook import make_songbook, songbooks_file
from caracole.songs import update_song
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from conftest import add_song

HOST = "localhost:8737"
NOW = datetime(2026, 10, 29, 3, 30, tzinfo=UTC)
LOGGER = "caracole.page_log"


@pytest.fixture
def app(cfg):
    return WebApp(cfg, JobQueue(lambda args, emit: 0, limit=3), allowed=frozenset({"localhost"}), csrf="tok")


@pytest.fixture
def lines(caplog):
    """The page log's records, at information level and above."""
    caplog.set_level(logging.INFO, logger=LOGGER)
    return lambda: [r for r in caplog.records if r.name == LOGGER]


def get(app, path, **headers):
    return app.handle(Request("GET", path, {"host": HOST, **headers}))


def stamp_of(path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def a_library(conn, cfg):
    """Four songs: one found, one wanted and in review, one wanted, one ignored; and a songbook."""
    found = add_song(conn, "Radiohead", "Creep")
    update_song(conn, found.id, status="found")
    review = add_song(conn, "Pixies", "Debaser")
    update_song(conn, review.id, match_decision="review", review=True)
    add_song(conn, "Soda Stereo", "Persiana Americana")
    add_song(conn, "Eagles", "Hotel California")
    add_ignore(cfg.overrides_file, "Eagles - Hotel California")
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Radiohead - Creep"])


def test_serving_the_library_page_logs_what_it_put_on_the_page(app, conn, cfg, lines):
    a_library(conn, cfg)
    assert get(app, "/").status == 200
    [line] = lines()
    assert line.levelno == logging.INFO
    db = cfg.db_path
    assert re.fullmatch(
        rf"library page served to {HOST}: 4 songs \(1 found, 2 wanted, 1 ignored; 1 in review\), 1 songbook; "
        rf"database {re.escape(str(db))}, {db.stat().st_size:,} bytes, modified {stamp_of(db)}; \d+\.\d\d s",
        line.getMessage()), line.getMessage()
    assert get(app, "/index.html").status == 200
    assert len(lines()) == 2


def test_the_served_line_reaches_the_journal_by_default(app, conn, cfg, tmp_path):
    # As caracole-web runs: `caracole serve` at the default verbosity, its stderr the journal (logs.py).
    add_song(conn, "Radiohead", "Creep")
    journal = open(tmp_path / "journal", "w+", encoding="utf-8")  # noqa: SIM115 - closed below
    st = os.fstat(journal.fileno())
    try:
        logs.setup(logs.NORMAL, stream=journal, env={"JOURNAL_STREAM": f"{st.st_dev}:{st.st_ino}"})
        assert get(app, "/").status == 200
        journal.seek(0)
        [line] = journal.read().splitlines()
    finally:
        logs.teardown()
        journal.close()
    assert line.startswith(f"<6>library page served to {HOST}: 1 song (0 found, 1 wanted, 0 ignored; 0 in review), "
                           f"0 songbooks; database {cfg.db_path}, ")


def test_an_empty_library_is_a_warning_with_what_tells_why_and_the_page_is_served_as_ever(app, conn, cfg, lines):
    response = get(app, "/")
    assert response.status == 200 and b'id="songs"' in response.body
    [line] = lines()
    assert line.levelno == logging.WARNING
    text = line.getMessage()
    db = cfg.db_path
    assert text.startswith(f"library page served to {HOST} with no songs: database {db}, "
                           f"{db.stat().st_size:,} bytes, modified {stamp_of(db)}, owner ")
    assert f"({db.stat().st_uid}:{db.stat().st_gid})" in text
    assert f"schema version {SCHEMA_VERSION}" in text
    assert "songs table 0 rows" in text
    assert f"state_dir {cfg.state_dir}" in text and f"library_dir {cfg.library_dir}" in text
    assert f"process uid {os.getuid()} gid {os.getgid()}" in text
    assert "\n" not in text and not line.exc_info


def test_a_database_that_wasnt_there_before_the_page_opened_it_says_so(app, cfg, lines):
    # Opening a missing database makes a new, empty one: a state directory not yet mounted, say.
    assert not cfg.db_path.exists()
    assert get(app, "/").status == 200
    [line] = lines()
    assert line.levelno == logging.WARNING
    assert f"database {cfg.db_path} missing before this build opened it, now " in line.getMessage()
    assert "songs table 0 rows" in line.getMessage()


def test_a_database_that_cant_be_read_is_a_warning_and_the_page_refuses_as_ever(app, cfg, lines):
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.db_path.write_bytes(b"not a database, not at all: a file a device synced here")
    response = get(app, "/")
    assert response.status == 503
    [line] = lines()
    assert line.levelno == logging.WARNING
    text = line.getMessage()
    assert text.startswith(f"library page served to {HOST} failed: the database can't be read "
                           "(DatabaseError: file is not a database): ")
    assert f"database {cfg.db_path}, 55 bytes, modified " in text
    assert "schema version unreadable (file is not a database)" in text
    assert f"process uid {os.getuid()} gid {os.getgid()}" in text
    assert "\n" not in text and not line.exc_info


def test_writing_the_pages_logs_a_written_line(conn, cfg, lines):
    from caracole.todo import write_pages

    add_song(conn, "Radiohead", "Creep")
    _, page = write_pages(conn, cfg, Overrides(), NOW)
    [line] = lines()
    assert line.levelno == logging.INFO
    assert re.fullmatch(
        rf"library page written to {re.escape(str(page))}: 1 song \(0 found, 1 wanted, 0 ignored; 0 in review\), "
        rf"0 songbooks; database {re.escape(str(cfg.db_path))}, [\d,]+ bytes, modified \S+Z; \d+\.\d\d s",
        line.getMessage()), line.getMessage()


def test_writing_an_empty_library_is_a_warning_too(conn, cfg, lines):
    from caracole.todo import write_pages

    write_pages(conn, cfg, Overrides(), NOW)
    [line] = lines()
    assert line.levelno == logging.WARNING
    assert line.getMessage().startswith(f"library page written to {cfg.library_dir / 'index.html'} with no songs: ")
    assert "songs table 0 rows" in line.getMessage()


def test_a_songbooks_file_that_cant_be_read_is_said_in_place_of_the_count(app, conn, cfg, lines):
    add_song(conn, "Radiohead", "Creep")
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    songbooks_file(cfg.library_dir).write_text("[broken\n", encoding="utf-8")
    assert get(app, "/").status == 200
    [line] = lines()
    assert "1 song (0 found, 1 wanted, 0 ignored; 0 in review), songbooks.toml unreadable; " in line.getMessage()


def test_the_pages_polls_log_no_line(app, conn, lines):
    add_song(conn, "Radiohead", "Creep")
    script = {"accept": "application/json", "sec-fetch-site": "same-origin", "x-caracole-form-token": "tok"}
    for path in ("/jobs.json", "/requests.json", "/api/search?q=creep", "/lookup", "/favicon.ico"):
        assert get(app, path, **script).status == 200, path
    assert lines() == []
