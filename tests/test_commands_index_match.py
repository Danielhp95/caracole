"""``tabarr index build | refresh | stats`` and ``tabarr match``, run through the CLI.

Each test writes a tabarr.toml rooted in tmp_path, with no pause between UG
requests. UG is a fake behind ``tabarr.commands._common.transport_for``, so no
request can reach the network.
"""

from __future__ import annotations

import gzip
import hashlib
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from tabarr import db
from tabarr.cli import build_app
from tabarr.health import get_state
from tabarr.songs import get_song, update_song

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
    monkeypatch.setattr("tabarr.commands._common.transport_for", lambda provider: httpx.MockTransport(fake.handler))
    return fake


def run(tmp_path: Path, *args: str, budget: int = 60):
    path = tmp_path / "tabarr.toml"
    path.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n'
        f"[providers.ug]\nbudget = {budget}\ndelay = [0, 0]\n",
        encoding="utf-8",
    )
    return CliRunner().invoke(build_app(), ["--config", str(path), *args])


def connect(tmp_path: Path):
    return db.connect(tmp_path / "state" / "tabarr.sqlite")


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


# --- tabarr index build ---------------------------------------------------------------------------


def test_cli_index_build_from_dir_sends_no_requests(tmp_path, ug):
    result = run(tmp_path, "index", "build", "--from", str(sitemap_dir(tmp_path)))
    assert result.exit_code == 0, result.output
    assert ug.requests == []
    assert tab_ids(tmp_path) == [1001, 1005, 2002, 2003, 3001]
    lines = result.output.splitlines()
    assert "sitemap1: 2 tabs, 2 new" in lines and "sitemap2: 2 tabs, 2 new" in lines
    assert "sitemap_last: 2 tabs, 1 new" in lines
    assert lines[-1] == "Index built: 3 sitemaps read, 0 unchanged; 5 new tabs. The index holds 5 tabs."


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
    assert "sitemap2: unchanged" in result.output.splitlines()
    assert result.output.splitlines()[-1] == (
        "Index built: 0 sitemaps read, 3 unchanged; 0 new tabs. The index holds 5 tabs.")


def test_cli_index_block_cools_ug_down_and_exits_0(tmp_path, ug):
    ug.status["sitemap2.xml"] = 403
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 0, result.output
    assert "blocked" in result.output and "sitemaps read so far are kept" in result.output
    assert tab_ids(tmp_path) == [1001, 1005]  # sitemap1 was stored before the block
    state = get_state(connect(tmp_path), "ug")
    assert state.strikes == 1 and state.cooldown_until is not None
    # During the cooldown no request is sent at all.
    ug.requests.clear()
    again = run(tmp_path, "index", "refresh")
    assert again.exit_code == 0, again.output
    assert ug.requests == [] and "cooling down" in again.output


def test_cli_index_other_errors_exit_1_and_are_recorded(tmp_path, ug):
    ug.status["sitemap_last.xml"] = 500
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 1
    assert "500" in result.output and "sitemaps read so far are kept" in result.output
    state = get_state(connect(tmp_path), "ug")
    assert "500" in (state.last_error or "") and state.cooldown_until is None


def test_cli_index_build_whose_every_request_failed_is_no_success(tmp_path, ug):
    ug.status["sitemap.xml"] = 502
    result = run(tmp_path, "index", "build")
    assert result.exit_code == 1
    state = get_state(connect(tmp_path), "ug")
    assert "502" in (state.last_error or "") and state.last_ok is None


# --- tabarr index refresh -------------------------------------------------------------------------


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
    lines = result.output.splitlines()
    assert "sitemap2: unchanged" in lines and "sitemap_last: 2 tabs, 1 new" in lines
    assert lines[-1] == "Index refreshed: 1 sitemap read, 1 unchanged; 1 new tab; 1 song to refetch."
    assert get_song(conn, creep.id).ug_dirty is True


def test_cli_index_refresh_with_the_budget_spent_exits_0(tmp_path, ug):
    run(tmp_path, "index", "build")
    ug.requests.clear()
    result = run(tmp_path, "index", "refresh", budget=2)
    assert result.exit_code == 0, result.output
    assert ug.requests == ["sitemap.xml", "sitemap2.xml"]
    assert "budget of 2 requests is spent" in result.output


def test_cli_index_refresh_needs_a_built_index(tmp_path, ug):
    result = run(tmp_path, "index", "refresh")
    assert result.exit_code == 1
    assert "tabarr index build" in result.output and ug.requests == []


# --- tabarr index stats ---------------------------------------------------------------------------


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


# --- tabarr match ---------------------------------------------------------------------------------


def seed(tmp_path: Path, *, built: bool = True):
    """An index and three songs: one exact, one with a close rival title, one not on UG.

    ``built=False`` leaves the index as a build stopped part-way would.
    """
    from datetime import UTC, datetime

    from tabarr.ug.index import mark_built

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
    assert "tabarr review" in first.output
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
    assert "tabarr index build" in result.output
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
    assert "incomplete" in result.output and "tabarr index build" in result.output
    dry = run(tmp_path, "match", "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "Dry run: nothing was saved." in dry.output
    assert "incomplete" in dry.output.splitlines()[-1]


def test_cli_match_without_songs(tmp_path):
    seed(tmp_path)[0].execute("DELETE FROM songs")
    result = run(tmp_path, "match")
    assert result.exit_code == 0 and "No songs" in result.output


# --- start-up cost --------------------------------------------------------------------------------


def test_registering_the_commands_imports_neither_the_matcher_nor_the_index():
    code = ("import sys; import tabarr.cli; "
            "print(sorted(m for m in sys.modules if m.startswith(('rapidfuzz', 'tabarr.match', 'tabarr.ug'))))")
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.strip() == "[]"
