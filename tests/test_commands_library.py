from pathlib import Path

import typer
from typer.testing import CliRunner

from tabarr import db
from tabarr.cli import build_app
from tabarr.songs import get_song, upsert_song, update_song

# Two [artist_url] tables, as pasting two of the to-do page's blocks one after the other makes them.
BROKEN_OVERRIDES = (
    '[artist_url]\n"Maná" = "https://www.ultimate-guitar.com/artist/mana_98"\n\n'
    '[artist_url]\n"宋冬野" = "https://www.ultimate-guitar.com/artist/song_dongye_99"\n'
)
CANDIDATE = {"artist_key": "song-dongye", "song_key": "ban-ma-ban-ma", "score": 80.0, "step": "fuzzy_title"}


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


def test_review_prompts_end_in_one_colon_and_enter_at_the_url_prompt_skips(tmp_path):
    conn, sid = seed(tmp_path)
    update_song(conn, sid, review=True, match_candidates=[CANDIDATE])
    result = run(tmp_path, "review", input="p\n\n")
    assert result.exit_code == 0, result.output
    assert "(q)uit: p" in result.output and ": :" not in result.output
    assert "not an Ultimate Guitar tab URL" not in result.output and "skipped 1" in result.output
    assert not (tmp_path / "lib" / "overrides.toml").exists()


def test_review_with_broken_overrides_stops_before_the_first_prompt(tmp_path):
    conn, sid = seed(tmp_path)
    update_song(conn, sid, review=True, match_candidates=[CANDIDATE])
    overrides = tmp_path / "lib" / "overrides.toml"
    overrides.parent.mkdir(parents=True)
    overrides.write_text(BROKEN_OVERRIDES, encoding="utf-8")
    result = run(tmp_path, "review", input="1\nq\n")
    assert result.exit_code == 2, result.output
    assert "overrides:" in result.output and "artist_url" in result.output
    assert "[1/1]" not in result.output  # no question asked that can't be saved
    assert overrides.read_text(encoding="utf-8") == BROKEN_OVERRIDES


def test_review_reports_overrides_broken_while_it_waits(tmp_path, monkeypatch):
    # The file is edited in another window while review waits for an answer.
    conn, sid = seed(tmp_path)
    update_song(conn, sid, review=True, match_candidates=[CANDIDATE])
    overrides = tmp_path / "lib" / "overrides.toml"

    def answer(prompt, **kwargs):
        overrides.parent.mkdir(parents=True, exist_ok=True)
        overrides.write_text(BROKEN_OVERRIDES, encoding="utf-8")
        return "1"

    monkeypatch.setattr(typer, "prompt", answer)
    result = run(tmp_path, "review")
    assert result.exit_code == 2, result.output
    assert "overrides:" in result.output and "artist_url" in result.output
    assert overrides.read_text(encoding="utf-8") == BROKEN_OVERRIDES
    assert get_song(conn, sid).review is True


def index_covers(conn, *, built=True):
    """The index has only a cover of 斑马斑马, by 李志; ``built`` marks the build finished."""
    from datetime import UTC, datetime

    from tabarr.ug.index import mark_built

    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'li-zhi', 'ban-ma-ban-ma', 'chords', '1', 'x', 'li-zhi/ban-ma-ban-ma-chords-1')")
    if built:
        mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))


COVER = {"artist_key": "li-zhi", "song_key": "ban-ma-ban-ma", "score": 100.0, "step": "title_only"}


def test_review_none_of_these_keeps_looking_for_the_song(tmp_path):
    conn, sid = seed(tmp_path)
    index_covers(conn)
    update_song(conn, sid, review=True, match_decision="review", match_step="title_only", match_candidates=[COVER])
    result = run(tmp_path, "review", input="n\n")
    assert result.exit_code == 0, result.output
    assert "(n)one of these" in result.output
    assert "accepted 0, pinned 0, ignored 0, rejected 1, skipped 0" in result.output
    overrides = (tmp_path / "lib" / "overrides.toml").read_text(encoding="utf-8")
    assert '[reject]\n"宋冬野 - 斑马斑马" = ["li-zhi/ban-ma-ban-ma"]' in overrides
    song = get_song(conn, sid)
    assert (song.match_decision, song.review, song.status) == ("not_found", False, "wanted")


def test_review_on_a_partial_index_saves_no_song_as_not_found(tmp_path):
    # A build stopped part-way: the rematch after your answers mustn't take the songs in the sitemaps
    # not read yet for misses.
    conn, sid = seed(tmp_path)
    update_song(conn, sid, review=True, match_decision="review", match_step="fuzzy_title",
                match_candidates=[CANDIDATE])
    other, _ = upsert_song(conn, artists=["Soda Stereo"], title="Signos", album=None, duration_ms=None,
                           isrc=None, source="wanted", source_id="y", added_at="2026-10-18T00:00:00Z")
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'song-dongye', 'ban-ma-ban-ma', 'chords', '1', 'x', 'song-dongye/ban-ma-ban-ma-chords-1')")
    result = run(tmp_path, "review", input="1\n")  # the index was never marked built: it is partial
    assert result.exit_code == 0, result.output
    assert get_song(conn, sid).match_decision == "accept"  # your answer is kept
    assert get_song(conn, other).match_decision is None


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


def test_scan_counts_the_links_it_refused(tmp_path):
    seed(tmp_path)
    inbox = tmp_path / "lib" / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "宋冬野 - 斑马斑马.gp5").symlink_to(tmp_path / "state" / "tabarr.sqlite")
    result = run(tmp_path, "scan")
    assert result.exit_code == 0, result.output
    assert "Inbox: 0 filed, 0 duplicates, 0 left, 1 symbolic link refused" in result.output


def test_bad_config_is_a_clean_error(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("libary_dir = 1\n", encoding="utf-8")
    result = CliRunner().invoke(build_app(), ["--config", str(p), "todo"])
    assert result.exit_code == 2
    assert "libary_dir" in result.output
