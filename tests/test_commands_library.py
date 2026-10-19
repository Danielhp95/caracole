from pathlib import Path

from typer.testing import CliRunner

from tabarr import db
from tabarr.cli import build_app
from tabarr.songs import upsert_song, update_song


def config(tmp_path: Path) -> Path:
    p = tmp_path / "tabarr.toml"
    p.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n',
        encoding="utf-8",
    )
    return p


def run(tmp_path, *args, input=None):
    return CliRunner().invoke(build_app(), ["--config", str(config(tmp_path)), *args], input=input)


def seed(tmp_path):
    conn = db.connect(tmp_path / "state" / "tabarr.sqlite")
    sid, _ = upsert_song(conn, artists=["宋冬野"], title="斑马斑马", album=None, duration_ms=253000, isrc=None,
                         source="wanted", source_id="x", added_at="2026-10-18T00:00:00Z")
    return conn, sid


def test_todo_writes_page(tmp_path):
    conn, sid = seed(tmp_path)
    update_song(conn, sid, match_decision="not_found")
    result = run(tmp_path, "todo")
    assert result.exit_code == 0, result.output
    page = (tmp_path / "lib" / "_todo.md").read_text(encoding="utf-8")
    assert "宋冬野 - 斑马斑马" in page and "## Buy list (1)" in page
    assert "_todo.md" in result.output


def test_review_with_nothing_to_review(tmp_path):
    seed(tmp_path)
    result = run(tmp_path, "review")
    assert result.exit_code == 0, result.output
    assert "Nothing to review" in result.output


def test_review_skip_and_quit(tmp_path):
    conn, sid = seed(tmp_path)
    update_song(conn, sid, review=True, match_candidates=[
        {"artist_key": "song-dongye", "song_key": "ban-ma-ban-ma", "score": 80.0, "step": "fuzzy_title"}])
    result = run(tmp_path, "review", input="s\n")
    assert result.exit_code == 0, result.output
    assert "song-dongye/ban-ma-ban-ma" in result.output and "skipped 1" in result.output


def test_scan_reports_music_and_inbox(tmp_path):
    seed(tmp_path)
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "宋冬野 - 斑马斑马.mp3").write_bytes(b"not audio")
    (tmp_path / "lib" / "_inbox").mkdir(parents=True)
    (tmp_path / "lib" / "_inbox" / "stray.gp5").write_bytes(b"gp")
    result = run(tmp_path, "scan")
    assert result.exit_code == 0, result.output
    assert "Music: 1 file, 1 linked" in result.output
    assert "Inbox: 0 filed, 0 duplicates, 1 left" in result.output


def test_bad_config_is_a_clean_error(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("libary_dir = 1\n", encoding="utf-8")
    result = CliRunner().invoke(build_app(), ["--config", str(p), "todo"])
    assert result.exit_code == 2
    assert "libary_dir" in result.output
