"""``caracole index build | refresh | stats`` and ``caracole match``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, with no pause between UG
requests. UG is a fake behind ``caracole.commands._common.transport_for``, so no
request can reach the network.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from helpers.ntfy import CONFIG as NTFY_CONFIG
from helpers.ntfy import FakeNtfy
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.health import get_state
from caracole.songs import get_song, update_song

from conftest import add_song, subprocess_pythonpath

WWW = "https://www.ultimate-guitar.com/"
TAB = "https://tabs.ultimate-guitar.com/tab/"


def urlset(*paths: str) -> bytes:
    urls = "".join(f"<url><loc>{TAB}{p}</loc><lastmod>2026-10-01</lastmod></url>" for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset>{urls}</urlset>'.encode()


def sitemap_index(*names: str) -> bytes:
    items = "".join(f"<sitemap><loc>{WWW}{n}</loc></sitemap>" for n in names)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex>{items}</sitemapindex>'.encode()


S1 = urlset("oasis/wonderwall-chords-1001", "oasis/wonderwall-bass-1003", "1004",
            "the-rifles/the-general-guitar-pro-1005")
S2 = urlset("radiohead/creep-chords-2002", "radiohead/creep-tabs-2003")
LAST = urlset("radiohead/creep-chords-2002", "eagles/hotel-california-power-3001")


class FakeUG:
    """UG's sitemaps with ETags; ``status`` makes a file answer with another status instead."""

    def __init__(self, files: dict[str, bytes]):
        self.files = dict(files)
        self.status: dict[str, int] = {}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.lstrip("/")
        self.requests.append(name)
        if name in self.status:
            return httpx.Response(self.status[name], content=b"no")
        body = self.files.get(name)
        if body is None:
            return httpx.Response(404, content=b"not found")
        etag = '"' + hashlib.sha256(body).hexdigest()[:16] + '"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"etag": etag})
        return httpx.Response(200, content=body, headers={"etag": etag})


def site() -> FakeUG:
    return FakeUG({
        "sitemap.xml": sitemap_index("sitemap2.xml", "sitemap_news.xml", "sitemap1.xml", "sitemap_last.xml"),
        "sitemap1.xml": S1, "sitemap2.xml": S2, "sitemap_last.xml": LAST,
    })


@pytest.fixture
def ug(monkeypatch) -> FakeUG:
    fake = site()
    monkeypatch.setattr("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(fake.handler))
    return fake


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """The index commands' clock stands still: every duration is 0.0 s, so their output is exact."""
    monkeypatch.setattr("caracole.commands.index.clock", lambda: 0.0)


def run(tmp_path: Path, *args: str, budget: int = 60, ntfy: bool = False):
    path = tmp_path / "caracole.toml"
    path.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n'
        f"[providers.ug]\nbudget = {budget}\ndelay = [0, 0]\n" + (NTFY_CONFIG if ntfy else ""),
        encoding="utf-8",
    )
    return CliRunner().invoke(build_app(), ["--config", str(path), *args])


def connect(tmp_path: Path):
    return db.connect(tmp_path / "state" / "caracole.sqlite")


def sitemap_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sitemaps"
    d.mkdir()
    (d / "sitemap1.xml.gz").write_bytes(gzip.compress(S1))
    (d / "sitemap2.xml").write_bytes(S2)
    (d / "sitemap_last.xml.gz").write_bytes(gzip.compress(LAST))
    return d


def tab_ids(tmp_path: Path) -> list[int]:
    conn = connect(tmp_path)
    try:
        return [r[0] for r in conn.execute("SELECT tab_id FROM ug_index ORDER BY tab_id")]
    finally:
        conn.close()


# --- caracole index build ---------------------------------------------------------------------------

INTRO = [
    "Indexing Ultimate Guitar's tab pages as rows of artist, title and type, to match your songs offline.",
    "Only the sitemaps UG publishes for search engines are read: no tab itself is downloaded.",
]
PLAN = [
    "Reading the sitemap index...",
    "The sitemap index lists 3 tab sitemaps (sitemap1.xml, sitemap2.xml and sitemap_last.xml): 3 to download.",
    "About 150,000 tab URLs (up to 50,000 a sitemap). 3 requests, 0 s apart: under a second.",
]
SITEMAP1 = "[1/3] sitemap1.xml  4 tabs: 2 indexed, 1 bare id, 1 of another type  2 left, under a second"
INDEX = [  # what the index holds after a build, whatever the build read
    "  Indexed     5 tabs: chords 2, guitar-pro 1, power 1, tabs 1",
    "  Artists     4",
    "  Bare ids    1 of 8 tab URLs (12.5%): with no artist or title in the URL, only artist pages lead to them",
    "  Left out    1 of another type (bass 1)",
    "  robots.txt  no tab left out",
]
COMPLETE = ("The index is complete: `caracole match` can now match your songs against it, "
            "and the nightly run keeps it up to date.")
PARTIAL = "The index is partial: 1 of 3 tab sitemaps indexed, so no song is matched against it yet."


def resume_line(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith(("To resume", "To finish")))


def test_cli_index_build_says_what_it_indexes_how_each_sitemap_went_and_what_the_index_holds(tmp_path, ug):
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        *INTRO,
        *PLAN,
        SITEMAP1,
        "[2/3] sitemap2.xml  2 tabs: 2 indexed  1 left, under a second",
        "[3/3] sitemap_last.xml  2 tabs: 2 indexed (1 new)",  # 2002 is in sitemap2 too
        "Index built: 3 sitemaps read; 5 new tabs.",
        *INDEX,
        "  Requests    4 of a budget of 100",
        "  Duration    0.0 s",
        COMPLETE,
    ]
    assert "\r" not in result.output and "\x1b" not in result.output  # no live line, no color, but on a terminal


def test_cli_index_build_from_dir_sends_no_requests(tmp_path, ug):
    d = sitemap_dir(tmp_path)
    result = run(tmp_path, "index", "build", "--from", str(d))
    assert result.exit_code == 0, result.output
    assert ug.requests == []
    assert tab_ids(tmp_path) == [1001, 1005, 2002, 2003, 3001]
    assert result.output.splitlines() == [
        INTRO[0],
        f"Only the sitemap files in {d} are read: no request is sent.",
        "Found 3 sitemap files (sitemap1.xml, sitemap2.xml and sitemap_last.xml).",
        "About 150,000 tab URLs (up to 50,000 a sitemap): about 2 s.",
        "[1/3] sitemap1.xml.gz  4 tabs: 2 indexed, 1 bare id, 1 of another type  2 left, under a second",
        "[2/3] sitemap2.xml  2 tabs: 2 indexed  1 left, under a second",
        "[3/3] sitemap_last.xml.gz  2 tabs: 2 indexed (1 new)",
        "Index built from 3 sitemap files; 5 new tabs.",
        *INDEX,
        "  Requests    none: read from files",
        "  Duration    0.0 s",
        COMPLETE,
    ]


def test_cli_index_build_from_a_dir_with_a_broken_file_keeps_the_files_before_it_and_exits_1(tmp_path, ug):
    d = sitemap_dir(tmp_path)
    (d / "sitemap2.xml").write_bytes(b"<html>not a sitemap</html>")
    result = run(tmp_path, "index", "build", "--from", str(d))
    assert result.exit_code == 1
    assert ug.requests == [] and tab_ids(tmp_path) == [1001, 1005]
    lines = result.output.splitlines()
    assert "Index build stopped after 1 of 3 sitemaps; 2 new tabs." in lines
    assert lines[-3:] == [
        "The index is partial: 1 tab sitemap indexed, so no song is matched against it yet.",
        f"To finish, run `caracole index build --from {d}` again: it reads every file again, with no request.",
        f"error: index build: {d / 'sitemap2.xml'}: not a sitemap (no <loc> entries)",
    ]


def test_cli_index_build_from_a_dir_without_sitemaps_fails(tmp_path):
    (tmp_path / "empty").mkdir()
    result = run(tmp_path, "index", "build", "--from", str(tmp_path / "empty"))
    assert result.exit_code == 1
    assert "no sitemap files" in result.output


def test_cli_index_build_over_the_network_has_a_budget_of_its_own(tmp_path, ug):
    # The nightly budget is 2 here; a build needs 4 requests and still finishes.
    result = run(tmp_path, "index", "build", budget=2)
    assert result.exit_code == 0, result.output
    assert ug.requests == ["sitemap.xml", "sitemap1.xml", "sitemap2.xml", "sitemap_last.xml"]
    assert tab_ids(tmp_path) == [1001, 1005, 2002, 2003, 3001]
    conn = connect(tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM events WHERE provider = 'ug' AND decision = 'ok'").fetchone()[0] == 4
    assert get_state(conn, "ug").last_ok is not None


def test_cli_index_build_again_finds_the_sitemaps_unchanged(tmp_path, ug):
    run(tmp_path, "index", "build")
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[3:5] == [
        "The sitemap index lists 3 tab sitemaps (sitemap1.xml, sitemap2.xml and sitemap_last.xml): "
        "3 indexed already, asked for again and skipped if unchanged.",
        "3 requests, 0 s apart: under a second.",
    ]
    assert "[2/3] sitemap2.xml  unchanged  1 left, under a second" in lines
    assert "Index built: 0 sitemaps read, 3 unchanged; 0 new tabs." in lines
    assert lines[-1] == COMPLETE


def test_cli_index_block_cools_ug_down_and_exits_0(tmp_path, ug):
    ug.status["sitemap2.xml"] = 403
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 0, result.output
    assert "blocked" in result.output and "sitemaps read so far are kept" in result.output
    assert tab_ids(tmp_path) == [1001, 1005]  # sitemap1 was stored before the block
    state = get_state(connect(tmp_path), "ug")
    assert state.strikes == 1 and state.cooldown_until is not None
    lines = result.output.splitlines()
    assert lines[len(INTRO) + len(PLAN)] == SITEMAP1
    assert "Index build stopped after 1 of 3 sitemaps; 2 new tabs." in lines
    assert "  Requests    3 of a budget of 100" in lines
    until = state.cooldown_until.strftime("%Y-%m-%d %H:%M UTC")
    assert lines[-2:] == [
        PARTIAL,
        f"To resume, run `caracole index refresh` after {until}: it reads the 2 sitemaps left, "
        "sitemap2.xml and sitemap_last.xml (3 requests, under a second). The nightly run does the same.",
    ]
    # During the cooldown no request is sent at all.
    ug.requests.clear()
    again = run(tmp_path, "index", "refresh")
    assert again.exit_code == 0, again.output
    assert ug.requests == [] and "cooling down" in again.output


def test_cli_index_block_sends_one_alert_as_the_nightly_run_does(tmp_path, ug, monkeypatch):
    ug.status["sitemap2.xml"] = 403
    ntfy = FakeNtfy()
    monkeypatch.setattr("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(
        ntfy.handler if provider == "ntfy" else ug.handler))
    result = run(tmp_path, "index", "build", ntfy=True)
    assert result.exit_code == 0, result.output
    assert ntfy.titles == ["caracole: ug blocked"]
    (alert,) = ntfy.posts
    assert alert.headers["priority"] == "high" and alert.headers["tags"] == "warning"
    assert "Ultimate Guitar blocked caracole" in alert.content.decode()
    assert run(tmp_path, "index", "refresh", ntfy=True).exit_code == 0  # cooling down: no request, no alert
    assert len(ntfy.posts) == 1


def test_cli_index_build_in_a_cooldown_sends_nothing_and_still_says_how_to_resume(tmp_path, ug):
    ug.status["sitemap2.xml"] = 403
    run(tmp_path, "index", "build")
    ug.requests.clear()
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 0, result.output
    assert ug.requests == []
    until = get_state(connect(tmp_path), "ug").cooldown_until.strftime("%Y-%m-%d %H:%M UTC")
    assert result.output.splitlines() == [
        *INTRO,
        f"Ultimate Guitar is cooling down after a block until {until}; no request was sent.",
        PARTIAL,
        f"To resume, run `caracole index refresh` after {until}: it reads the 2 sitemaps left, "
        "sitemap2.xml and sitemap_last.xml (3 requests, under a second). The nightly run does the same.",
    ]


def test_cli_index_build_with_its_budget_spent_exits_0_and_says_how_to_resume(tmp_path, ug, monkeypatch):
    monkeypatch.setattr("caracole.commands.index.BUILD_BUDGET", 2)
    result = run(tmp_path, "index", "build", budget=2)  # the sitemap index and sitemap1
    assert result.exit_code == 0, result.output
    assert ug.requests == ["sitemap.xml", "sitemap1.xml"]
    lines = result.output.splitlines()
    assert "The Ultimate Guitar budget of 2 requests is spent; the sitemaps read so far are kept." in lines
    assert "  Requests    2 of a budget of 2" in lines
    assert lines[-2] == PARTIAL
    assert resume_line(result.output).startswith(
        "To resume, run `caracole index refresh`: it reads the 2 sitemaps left, sitemap2.xml and sitemap_last.xml")


def test_cli_index_build_stopped_by_ctrl_c_keeps_what_it_read_and_says_how_to_resume(tmp_path, ug, monkeypatch):
    def interrupted(request):
        if request.url.path == "/sitemap2.xml":
            raise KeyboardInterrupt
        return ug.handler(request)

    monkeypatch.setattr("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(interrupted))
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 130  # as Ctrl-C always ends a caracole command
    assert tab_ids(tmp_path) == [1001, 1005]
    lines = result.output.splitlines()
    assert "Stopped by Ctrl-C; the sitemaps read so far are kept." in lines
    assert "Index build stopped after 1 of 3 sitemaps; 2 new tabs." in lines
    assert lines[-2] == PARTIAL
    assert resume_line(result.output) == (
        "To resume, run `caracole index refresh`: it reads the 2 sitemaps left, sitemap2.xml and sitemap_last.xml "
        "(3 requests, under a second). The nightly run does the same.")


def test_cli_index_other_errors_exit_1_and_are_recorded(tmp_path, ug):
    ug.status["sitemap_last.xml"] = 500
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 1
    assert "500" in result.output and "sitemaps read so far are kept" in result.output
    state = get_state(connect(tmp_path), "ug")
    assert "500" in (state.last_error or "") and state.cooldown_until is None
    # sitemap1 and sitemap2 are in; a refresh reads sitemap_last and, as always, checks the highest-numbered one
    assert resume_line(result.output) == (
        "To resume, run `caracole index refresh`: it reads the sitemap left, sitemap_last.xml, and checks "
        "sitemap2.xml (3 requests, under a second). The nightly run does the same.")


def test_cli_index_build_whose_every_request_failed_is_no_success(tmp_path, ug):
    ug.status["sitemap.xml"] = 502
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 1
    state = get_state(connect(tmp_path), "ug")
    assert "502" in (state.last_error or "") and state.last_ok is None


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_cli_index_build_on_a_terminal_keeps_one_live_line(tmp_path, ug, monkeypatch):
    from caracole.progress import Console

    screen = Terminal()
    monkeypatch.setattr("caracole.commands.index.console",
                        lambda: Console(screen, environ={"TERM": "xterm", "NO_COLOR": "1"}, width=lambda: 200))
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 0, result.output
    out = screen.getvalue()
    assert "\r" + SITEMAP1 in out and SITEMAP1 + "\n" not in out  # rewritten in place, never a line of its own
    lines = [line.rsplit("\r", 1)[-1] for line in out.split("\n")]  # what stays on screen
    assert lines[:2] == INTRO and "Index built: 3 sitemaps read; 5 new tabs." in lines and COMPLETE in lines
    assert "\x1b" not in out  # NO_COLOR


# --- caracole index refresh -------------------------------------------------------------------------


def test_cli_index_refresh_reports_new_tabs_and_songs_to_refetch(tmp_path, ug):
    run(tmp_path, "index", "build")
    conn = connect(tmp_path)
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep",
                ug_dirty=False)
    ug.files["sitemap_last.xml"] = urlset("radiohead/creep-chords-2002", "radiohead/creep-intro-tabs-3002")
    ug.requests.clear()
    result = run(tmp_path, "index", "refresh")
    assert result.exit_code == 0, result.output
    assert ug.requests == ["sitemap.xml", "sitemap2.xml", "sitemap_last.xml"]
    # compact: the unchanged sitemap2 gets no line of its own
    assert result.output.splitlines() == [
        "Checking the sitemap index for new tabs...",
        "[2/2] sitemap_last.xml  2 tabs: 2 indexed (1 new)",
        "Index refreshed: 1 of 2 sitemaps changed (sitemap_last.xml): +1 tab, 1 song to refetch. 3 requests, 0.0 s.",
    ]
    assert get_song(conn, creep.id).ug_dirty is True


def test_cli_index_refresh_reads_what_a_stopped_build_left_and_completes_the_index(tmp_path, ug, monkeypatch):
    monkeypatch.setattr("caracole.commands.index.BUILD_BUDGET", 2)
    run(tmp_path, "index", "build", budget=2)
    ug.requests.clear()
    result = run(tmp_path, "index", "refresh")
    assert result.exit_code == 0, result.output
    assert ug.requests == ["sitemap.xml", "sitemap2.xml", "sitemap_last.xml"]
    assert result.output.splitlines() == [
        "Checking the sitemap index for new tabs...",
        "Reading sitemap2.xml and sitemap_last.xml, not indexed yet: 2 requests, 0 s apart, under a second.",
        "[1/2] sitemap2.xml  2 tabs: 2 indexed  1 left, under a second",
        "[2/2] sitemap_last.xml  2 tabs: 2 indexed (1 new)",
        "Index refreshed: 2 of 2 sitemaps changed (sitemap2.xml and sitemap_last.xml): +3 tabs, no song to refetch; "
        "the index is now complete. 3 requests, 0.0 s.",
    ]


def test_cli_index_refresh_stopped_by_ctrl_c_sums_up_what_it_read_and_says_how_to_resume(tmp_path, ug, monkeypatch):
    monkeypatch.setattr("caracole.commands.index.BUILD_BUDGET", 2)
    run(tmp_path, "index", "build", budget=2)  # sitemap1 only

    def interrupted(request):
        if request.url.path == "/sitemap_last.xml":
            raise KeyboardInterrupt
        return ug.handler(request)

    monkeypatch.setattr("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(interrupted))
    result = run(tmp_path, "index", "refresh")
    assert result.exit_code == 130
    assert tab_ids(tmp_path) == [1001, 1005, 2002, 2003]  # sitemap2 is kept
    assert result.output.splitlines()[-4:] == [
        "Stopped by Ctrl-C; the sitemaps read so far are kept.",
        "Index refresh stopped: 1 of 1 sitemap changed (sitemap2.xml): +2 tabs. 3 requests, 0.0 s.",  # the cut one too
        "The index is partial: 2 of 3 tab sitemaps indexed, so no song is matched against it yet.",
        "To resume, run `caracole index refresh`: it reads the sitemap left, sitemap_last.xml, and checks "
        "sitemap2.xml (3 requests, under a second). The nightly run does the same.",
    ]


def test_cli_index_refresh_with_the_budget_spent_exits_0(tmp_path, ug):
    run(tmp_path, "index", "build")
    ug.requests.clear()
    result = run(tmp_path, "index", "refresh", budget=2)
    assert result.exit_code == 0, result.output
    assert ug.requests == ["sitemap.xml", "sitemap2.xml"]
    assert "budget of 2 requests is spent" in result.output
    assert result.output.splitlines()[-1] == "Index refresh stopped: 1 sitemap checked, none changed. 2 requests, 0.0 s."


def test_cli_index_refresh_needs_a_built_index(tmp_path, ug):
    result = run(tmp_path, "index", "refresh")
    assert result.exit_code == 1
    assert "caracole index build" in result.output and ug.requests == []


# --- caracole index stats ---------------------------------------------------------------------------


def test_cli_index_stats(tmp_path):
    empty = run(tmp_path, "index", "stats")
    assert empty.exit_code == 0 and "The index is empty" in empty.output
    run(tmp_path, "index", "build", "--from", str(sitemap_dir(tmp_path)))
    result = run(tmp_path, "index", "stats")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "Tabs: 5 (chords 2, guitar-pro 1, power 1, tabs 1)"  # most first, ties by name
    assert "Artists: 4" in lines and "Sitemaps indexed: 3" in lines and "Newest tab id: 3001" in lines
    assert any(line.startswith("Built: 20") and line.endswith("refreshed: never") for line in lines)


# --- caracole match ---------------------------------------------------------------------------------


def seed(tmp_path: Path, *, built: bool = True):
    """An index and three songs: one exact, one with a close rival title, one not on UG.

    ``built=False`` leaves the index as a build stopped part-way would.
    """
    from datetime import UTC, datetime

    from caracole.ug.index import mark_built

    conn = connect(tmp_path)
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, ?, '1', 'x', ?)",
        [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in (
            (1, "radiohead", "creep", "chords"), (2, "radiohead", "creep-acoustic", "chords"),
            (3, "oasis", "wonderwall", "chords"), (4, "oasis", "wonderwalls", "chords"))],
    )
    if built:
        mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))
    songs = [add_song(conn, "Radiohead", "Creep", added_at="2026-10-03T00:00:00Z"),
             add_song(conn, "Oasis", "Wonderwal", added_at="2026-10-02T00:00:00Z"),
             add_song(conn, "Joaquín Sabina", "19 Días y 500 Noches", added_at="2026-10-01T00:00:00Z")]
    return conn, songs


def song_rows(conn):
    return [tuple(r) for r in conn.execute("SELECT * FROM songs ORDER BY id")]


def test_cli_match_dry_run_prints_changes(tmp_path):
    conn, (creep, typo, sabina) = seed(tmp_path)
    before = song_rows(conn)
    result = run(tmp_path, "match", "--dry-run")
    assert result.exit_code == 0, result.output
    assert song_rows(conn) == before
    lines = result.output.splitlines()
    assert lines[0].split() == ["accept", "100.0", "exact", "Radiohead", "-", "Creep", "→", "radiohead/creep",
                                "CHANGED", "unmatched", "→", "accept"]
    assert lines[1].split()[:3] == ["review", "94.7", "fuzzy_title"]
    assert "Oasis - Wonderwal → oasis/wonderwall" in lines[1]
    assert lines[2].split()[:3] == ["not_found", "-", "-"]
    assert "Joaquín Sabina - 19 Días y 500 Noches → -" in lines[2]
    assert "3 songs: 1 accept, 1 review, 1 not_found; 3 changed. Dry run: nothing was saved." in lines


def test_cli_match_saves_then_marks_only_what_changed(tmp_path):
    conn, (creep, typo, sabina) = seed(tmp_path)
    first = run(tmp_path, "match")
    assert first.exit_code == 0, first.output
    assert get_song(conn, creep.id).match_decision == "accept" and get_song(conn, typo.id).review is True
    assert "caracole review" in first.output
    again = run(tmp_path, "match")
    assert "CHANGED" not in again.output and "; 0 changed." in again.output
    # A [match] override moves Creep to another UG song: same decision, other keys.
    (tmp_path / "lib").mkdir(exist_ok=True)
    (tmp_path / "lib" / "overrides.toml").write_text(
        '[match]\n"Radiohead - Creep" = "radiohead/creep-acoustic"\n', encoding="utf-8")
    moved = run(tmp_path, "match", "--dry-run")
    line = next(x for x in moved.output.splitlines() if "Radiohead - Creep" in x)
    assert line.split()[:3] == ["accept", "100.0", "override"]
    assert line.endswith("CHANGED radiohead/creep → radiohead/creep-acoustic")


def test_cli_match_needs_a_built_index(tmp_path):
    conn = connect(tmp_path)
    add_song(conn, "Radiohead", "Creep")
    result = run(tmp_path, "match")
    assert result.exit_code == 1
    assert "caracole index build" in result.output
    assert get_song(conn, 1).match_decision is None


def test_cli_match_rewrites_the_pages_it_points_to(tmp_path):
    seed(tmp_path)
    todo, page = tmp_path / "lib" / "_todo.md", tmp_path / "lib" / "index.html"
    dry = run(tmp_path, "match", "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert not todo.exists() and not page.exists()  # a dry run saves nothing, pages included
    result = run(tmp_path, "match")
    assert result.exit_code == 0, result.output
    assert "on _todo.md" in result.output
    assert todo.is_file(), result.output
    assert "### Oasis - Wonderwal" in todo.read_text(encoding="utf-8")  # the review it points to
    assert "Oasis - Wonderwal" in page.read_text(encoding="utf-8")
    assert f"Wrote {todo} and {page}" in result.output


def test_cli_match_names_a_page_it_cant_write(tmp_path):
    # As every command that writes the pages: the decisions are saved, and the page is named.
    conn, (creep, _, _) = seed(tmp_path)
    (tmp_path / "lib" / "_todo.md").mkdir(parents=True)  # a folder where the page goes (root too)
    result = run(tmp_path, "match")
    assert result.exit_code == 1, result.output
    assert f"can't write {tmp_path / 'lib' / '_todo.md'}: Is a directory" in result.output
    assert get_song(conn, creep.id).match_decision == "accept"


def test_cli_match_refuses_to_save_against_an_incomplete_index(tmp_path):
    # A build stopped part-way: the songs in the sitemaps it didn't read would be saved as not found.
    conn, songs = seed(tmp_path, built=False)
    result = run(tmp_path, "match")
    assert all(get_song(conn, s.id).match_decision is None for s in songs), result.output
    assert result.exit_code == 1
    assert "incomplete" in result.output and "caracole index build" in result.output
    dry = run(tmp_path, "match", "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "Dry run: nothing was saved." in dry.output
    assert "incomplete" in dry.output.splitlines()[-1]


def test_cli_match_without_songs(tmp_path):
    seed(tmp_path)[0].execute("DELETE FROM songs")
    result = run(tmp_path, "match")
    assert result.exit_code == 0 and "No songs" in result.output


# --- start-up cost --------------------------------------------------------------------------------


@pytest.mark.slow
def test_registering_the_commands_imports_neither_the_matcher_nor_the_index():
    code = ("import sys; import caracole.cli; "
            "print(sorted(m for m in sys.modules if m.startswith(('rapidfuzz', 'caracole.match', 'caracole.ug'))))")
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.strip() == "[]"


@pytest.mark.slow
def test_a_command_that_sends_no_request_imports_no_http_client(tmp_path):
    # httpx imports its own command line, and with it rich and pygments: a third of a start.
    # A [youtube] entry, which the web page writes, is read without the yt-dlp runner either.
    overrides = tmp_path / "overrides.toml"
    overrides.write_text('[youtube]\n"Radiohead - Creep" = "youtu.be/XFkzRNyygfk"\n', encoding="utf-8")
    code = (
        "import sys; from pathlib import Path; import caracole.cli\n"
        "from caracole.overrides import load_overrides\n"
        f"print(dict(load_overrides(Path({str(overrides)!r})).youtube))\n"
        "print(sorted(m for m in sys.modules if m.startswith(('httpx', 'rich', 'caracole.http'))"
        " or m == 'caracole.youtube'))\n"
    )
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.splitlines() == ["{'radiohead/creep': 'XFkzRNyygfk'}", "[]"]
