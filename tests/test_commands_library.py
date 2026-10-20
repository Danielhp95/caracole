import fcntl
import os
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.songs import get_song, upsert_song, update_song

needs_permissions = pytest.mark.skipif(os.geteuid() == 0, reason="root writes into read-only folders")

# Two [artist_url] tables, as pasting two of the to-do page's blocks one after the other makes them.
BROKEN_OVERRIDES = (
    '[artist_url]\n"Maná" = "https://www.ultimate-guitar.com/artist/mana_98"\n\n'
    '[artist_url]\n"宋冬野" = "https://www.ultimate-guitar.com/artist/song_dongye_99"\n'
)
CANDIDATE = {"artist_key": "song-dongye", "song_key": "ban-ma-ban-ma", "score": 80.0, "step": "fuzzy_title"}


def config(tmp_path: Path) -> Path:
    p = tmp_path / "caracole.toml"
    p.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n',
        encoding="utf-8",
    )
    return p


def run(tmp_path, *args, input=None):
    return CliRunner().invoke(build_app(), ["--config", str(config(tmp_path)), *args], input=input)


def seed(tmp_path):
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    sid, _ = upsert_song(conn, artists=["宋冬野"], title="斑马斑马", album=None, duration_ms=253000, isrc=None,
                         source="wanted", source_id="x", added_at="2026-10-18T00:00:00Z")
    return conn, sid


def free(tmp_path) -> bool:
    """Whether another process could take caracole's lock now (an open file of its own)."""
    path = tmp_path / "state" / "caracole.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


def spy(monkeypatch, module, name: str, tmp_path) -> list[bool]:
    """Whether caracole's lock was held each time ``module.name`` was called."""
    held, real = [], getattr(module, name)

    def wrapper(*args, **kwargs):
        held.append(not free(tmp_path))
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    return held


def pages(tmp_path) -> tuple[Path, Path]:
    return tmp_path / "lib" / "_todo.md", tmp_path / "lib" / "index.html"


def test_todo_writes_page(tmp_path):
    conn, sid = seed(tmp_path)
    update_song(conn, sid, match_decision="not_found")
    result = run(tmp_path, "todo")
    assert result.exit_code == 0, result.output
    page = (tmp_path / "lib" / "_todo.md").read_text(encoding="utf-8")
    assert "宋冬野 - 斑马斑马" in page and "## Buy list (1)" in page
    assert "_todo.md" in result.output


def test_todo_holds_caracoles_lock_while_it_writes(tmp_path, monkeypatch):
    import caracole.todo

    seed(tmp_path)
    held = spy(monkeypatch, caracole.todo, "build_todo", tmp_path)
    result = run(tmp_path, "todo")
    assert result.exit_code == 0, result.output
    assert held == [True] and free(tmp_path)  # and let go of it after


def test_todo_with_broken_overrides_writes_the_page_leading_with_why(tmp_path):
    # As the nightly run does: index.html is left as it was, since without your overrides it would lose
    # your transpositions and ignored songs.
    seed(tmp_path)
    overrides = tmp_path / "lib" / "overrides.toml"
    overrides.parent.mkdir(parents=True)
    overrides.write_text(BROKEN_OVERRIDES, encoding="utf-8")
    result = run(tmp_path, "todo")
    assert result.exit_code == 2, result.output
    assert "overrides:" in result.output and "merge the two [artist_url] sections into one" in result.output
    todo, page = pages(tmp_path)
    first = todo.read_text(encoding="utf-8").split("\n## ", 2)[1]
    assert first.startswith("Setup problems") and "overrides.toml can't be read" in first
    assert not page.exists() and overrides.read_text(encoding="utf-8") == BROKEN_OVERRIDES


@needs_permissions
@pytest.mark.parametrize("broken, code", [(False, 1), (True, 2)])
def test_todo_in_a_library_caracole_cant_write_says_so(tmp_path, broken, code):
    seed(tmp_path)
    lib = tmp_path / "lib"
    lib.mkdir()
    if broken:
        (lib / "overrides.toml").write_text(BROKEN_OVERRIDES, encoding="utf-8")
    lib.chmod(0o555)
    try:
        result = run(tmp_path, "todo")
    finally:
        lib.chmod(0o755)
    assert result.exit_code == code, result.output
    assert not isinstance(result.exception, OSError)
    assert f"can't write {lib / '_todo.md'}: Permission denied" in result.output
    assert ("overrides:" in result.output) == broken


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


def index_covers(conn):
    """A finished index whose only 斑马斑马 is a cover, by 李志."""
    from datetime import UTC, datetime

    from caracole.ug.index import mark_built

    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'li-zhi', 'ban-ma-ban-ma', 'chords', '1', 'x', 'li-zhi/ban-ma-ban-ma-chords-1')")
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


def test_review_rewrites_the_pages_holding_the_lock_only_after_the_questions(tmp_path, monkeypatch):
    # Never while it waits for you: the nightly run may start meanwhile.
    import caracole.match

    conn, sid = seed(tmp_path)
    update_song(conn, sid, review=True, match_decision="review", match_step="fuzzy_title",
                match_candidates=[CANDIDATE])
    asked = []

    def answer(prompt, **kwargs):
        asked.append(not free(tmp_path))
        return "1"

    monkeypatch.setattr(typer, "prompt", answer)
    matched = spy(monkeypatch, caracole.match, "match_all", tmp_path)
    result = run(tmp_path, "review")
    assert result.exit_code == 0, result.output
    assert asked == [False] and matched == [True] and free(tmp_path)
    todo, page = pages(tmp_path)
    assert f"Wrote {todo} and {page}" in result.output
    assert "宋冬野 - 斑马斑马" not in todo.read_text(encoding="utf-8").split("\n## Review", 1)[-1].split("\n## ")[0]


def test_review_that_changes_nothing_leaves_the_pages_alone(tmp_path):
    conn, sid = seed(tmp_path)
    update_song(conn, sid, review=True, match_candidates=[CANDIDATE])
    result = run(tmp_path, "review", input="s\n")
    assert result.exit_code == 0, result.output
    assert "Wrote" not in result.output and not any(p.exists() for p in pages(tmp_path))


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


# --- one song, one answer: caracole review --song (what caracole serve's picker runs) -------------

SONG = "宋冬野 - 斑马斑马"


def index_both(conn):
    """A finished index with 宋冬野's 斑马斑马 and 李志's cover of it."""
    from datetime import UTC, datetime

    from caracole.ug.index import mark_built

    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'li-zhi', 'ban-ma-ban-ma', 'chords', '1', 'x', 'li-zhi/ban-ma-ban-ma-chords-1'), "
                 "(2, 'song-dongye', 'ban-ma-ban-ma', 'chords', '1', 'x', 'song-dongye/ban-ma-ban-ma-chords-2')")
    mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))


def in_review(tmp_path):
    conn, sid = seed(tmp_path)
    index_both(conn)
    update_song(conn, sid, review=True, match_decision="review", match_step="fuzzy_title",
                match_candidates=[CANDIDATE, COVER])
    return conn, sid


def overrides_text(tmp_path) -> str:
    path = tmp_path / "lib" / "overrides.toml"
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.mark.parametrize("pick", ["song-dongye/ban-ma-ban-ma", "1"])
def test_review_song_pick_answers_as_its_number_does_without_a_question(tmp_path, monkeypatch, pick):
    import caracole.review

    conn, sid = in_review(tmp_path)
    held = spy(monkeypatch, caracole.review, "add_match", tmp_path)
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: pytest.fail("asked a question"))
    result = run(tmp_path, "review", "--song", SONG, "--pick", pick)
    assert result.exit_code == 0, result.output
    text = overrides_text(tmp_path)
    assert f'[match]\n"{SONG}" = "song-dongye/ban-ma-ban-ma"' in text
    assert '[alias]\n"宋冬野" = "song-dongye"' in text
    assert held == [True] and free(tmp_path)  # the answer is written under caracole's lock
    assert "accepted 1, pinned 0, ignored 0, rejected 0, skipped 0" in result.output
    song = get_song(conn, sid)
    assert (song.match_decision, song.review) == ("accept", False)
    assert "Now matched to song-dongye/ban-ma-ban-ma" in result.output
    todo, page = pages(tmp_path)
    assert f"Wrote {todo} and {page}" in result.output


def test_review_song_pick_of_a_cover_writes_no_alias(tmp_path):
    in_review(tmp_path)
    result = run(tmp_path, "review", "--song", SONG, "--pick", "2")
    assert result.exit_code == 0, result.output
    text = overrides_text(tmp_path)
    assert f'"{SONG}" = "li-zhi/ban-ma-ban-ma"' in text and "[alias]" not in text


def test_review_song_none_rejects_every_candidate_listed(tmp_path):
    conn, sid = in_review(tmp_path)
    result = run(tmp_path, "review", "--song", SONG, "--none")
    assert result.exit_code == 0, result.output
    assert (f'[reject]\n"{SONG}" = ["song-dongye/ban-ma-ban-ma", "li-zhi/ban-ma-ban-ma"]'
            in overrides_text(tmp_path))
    assert "rejected 1" in result.output
    song = get_song(conn, sid)
    assert (song.match_decision, song.review, song.status) == ("not_found", False, "wanted")
    assert "caracole goes on looking for it" in result.output


def test_review_song_none_with_seen_rejects_only_the_candidates_seen(tmp_path):
    # The page showed one candidate; the nightly run found another since. Only the one seen goes.
    conn, sid = in_review(tmp_path)
    result = run(tmp_path, "review", "--song", SONG, "--none", "--seen", "li-zhi/ban-ma-ban-ma")
    assert result.exit_code == 0, result.output
    assert f'[reject]\n"{SONG}" = ["li-zhi/ban-ma-ban-ma"]' in overrides_text(tmp_path)
    # The one not seen is still a candidate, which the rematch accepts: the index has it exactly.
    assert get_song(conn, sid).match_decision == "accept"
    assert "Now matched to song-dongye/ban-ma-ban-ma" in result.output


def test_review_song_alone_asks_about_that_song_only(tmp_path):
    conn, sid = in_review(tmp_path)
    other, _ = upsert_song(conn, artists=["Soda Stereo"], title="Signos", album=None, duration_ms=None,
                           isrc=None, source="wanted", source_id="y", added_at="2026-10-18T00:00:00Z")
    update_song(conn, other, review=True, match_candidates=[CANDIDATE])
    result = run(tmp_path, "review", "--song", SONG, input="1\n")
    assert result.exit_code == 0, result.output
    assert "[1/1] 宋冬野 - 斑马斑马" in result.output and "Signos" not in result.output
    assert "accepted 1" in result.output and "Signos" not in overrides_text(tmp_path)


@pytest.mark.parametrize("args,code,message", [
    (["--pick", "1"], 2, "--pick and --none answer for one song: name it with --song"),
    (["--none"], 2, "--pick and --none answer for one song: name it with --song"),
    (["--song", SONG, "--pick", "1", "--none"], 2, "--pick or --none, not both"),
    (["--song", SONG, "--seen", "li-zhi/ban-ma-ban-ma"], 2, "--seen goes with --none"),
    (["--song", SONG, "--none", "--seen", "li-zhi"], 2, "--seen: 'li-zhi' isn't a UG song"),
    (["--song", "no dash", "--pick", "1"], 2, "expected \"Artist - Title\""),
    (["--song", "Radiohead - Creep", "--pick", "1"], 1, 'No song "Radiohead - Creep" in the library'),
    (["--song", SONG, "--pick", "3"], 1, "has no candidate 3 now"),
    (["--song", SONG, "--pick", "radiohead/creep"], 1, "has no candidate radiohead/creep now"),
])
def test_review_song_refuses_what_it_cant_answer_and_writes_nothing(tmp_path, args, code, message):
    in_review(tmp_path)
    result = run(tmp_path, "review", *args)
    assert result.exit_code == code, result.output
    assert message in result.output
    assert overrides_text(tmp_path) == "" and not any(p.exists() for p in pages(tmp_path))


def test_review_song_of_a_song_that_needs_no_review_says_so(tmp_path):
    conn, sid = in_review(tmp_path)
    update_song(conn, sid, review=False, match_decision="accept")
    result = run(tmp_path, "review", "--song", SONG, "--none")
    assert result.exit_code == 1, result.output
    assert "doesn't need review" in result.output and overrides_text(tmp_path) == ""


def test_review_song_with_broken_overrides_stops_before_writing(tmp_path):
    in_review(tmp_path)
    overrides = tmp_path / "lib" / "overrides.toml"
    overrides.parent.mkdir(parents=True)
    overrides.write_text(BROKEN_OVERRIDES, encoding="utf-8")
    result = run(tmp_path, "review", "--song", SONG, "--pick", "1")
    assert result.exit_code == 2, result.output
    assert "overrides:" in result.output and overrides.read_text(encoding="utf-8") == BROKEN_OVERRIDES


CREP = "Radio Head - Crep"


def not_found(tmp_path):
    """Radio Head's "Crep", not found under that name, and an index that has Radiohead's "Creep"."""
    from datetime import UTC, datetime

    from caracole.ug.index import mark_built

    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    sid, _ = upsert_song(conn, artists=["Radio Head"], title="Crep", album=None, duration_ms=None, isrc=None,
                         source="wanted", source_id="x", added_at="2026-10-18T00:00:00Z")
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'radiohead', 'creep', 'chords', '1', 'x', 'radiohead/creep-chords-1')")
    mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))
    update_song(conn, sid, match_decision="not_found")
    return conn, sid


@pytest.mark.parametrize("pick", ["radiohead/creep", "1"])
def test_review_song_pick_of_a_song_not_found_takes_a_search_hit_and_writes_match_alone(tmp_path, pick):
    conn, sid = not_found(tmp_path)
    result = run(tmp_path, "review", "--song", CREP, "--pick", pick)
    assert result.exit_code == 0, result.output
    text = overrides_text(tmp_path)
    assert f'[match]\n"{CREP}" = "radiohead/creep"' in text and "[alias]" not in text
    assert get_song(conn, sid).match_decision == "accept"
    assert "Now matched to radiohead/creep" in result.output


@pytest.mark.parametrize("args,message", [
    (["--pick", "oasis/wonderwall"], "has no candidate oasis/wonderwall now"),
    (["--pick", "2"], "has no candidate 2 now"),
    (["--none"], "doesn't need review"),
])
def test_review_song_of_a_song_not_found_takes_only_a_search_hit(tmp_path, args, message):
    not_found(tmp_path)
    result = run(tmp_path, "review", "--song", CREP, *args)
    assert result.exit_code == 1, result.output
    assert message in result.output and overrides_text(tmp_path) == ""


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


def test_scan_rewrites_the_pages_holding_the_lock(tmp_path, monkeypatch):
    import caracole.music

    conn, sid = seed(tmp_path)
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "宋冬野 - 斑马斑马.mp3").write_bytes(b"not audio")
    held = spy(monkeypatch, caracole.music, "scan_music", tmp_path)
    result = run(tmp_path, "scan")
    assert result.exit_code == 0, result.output
    assert held == [True] and free(tmp_path)
    todo, page = pages(tmp_path)
    assert f"Wrote {todo} and {page}" in result.output
    assert get_song(conn, sid).audio_path is not None and "斑马斑马" in page.read_text(encoding="utf-8")


@pytest.mark.parametrize("folder, said", [(None, "is missing"), ("empty", "has no audio files")])
def test_scan_says_why_it_unlinked_nothing(tmp_path, folder, said):
    # A Music/ folder missing or without audio is taken for a disk that isn't mounted tonight.
    conn, sid = seed(tmp_path)
    music = tmp_path / "music"
    update_song(conn, sid, audio_path=str(music / "宋冬野 - 斑马斑马.flac"))
    if folder:
        music.mkdir()
    result = run(tmp_path, "scan")
    assert result.exit_code == 0, result.output
    assert f"Music: {music} {said}, so nothing was unlinked" in result.output
    assert get_song(conn, sid).audio_path is not None


def test_scan_with_broken_overrides_scans_then_writes_the_page_leading_with_why(tmp_path):
    seed(tmp_path)
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "overrides.toml").write_text(BROKEN_OVERRIDES, encoding="utf-8")
    result = run(tmp_path, "scan")
    assert result.exit_code == 2, result.output
    assert "Inbox: 0 filed" in result.output and "overrides:" in result.output
    todo, page = pages(tmp_path)
    assert "overrides.toml can't be read" in todo.read_text(encoding="utf-8") and not page.exists()


def test_scan_counts_the_links_it_refused(tmp_path):
    seed(tmp_path)
    inbox = tmp_path / "lib" / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "宋冬野 - 斑马斑马.gp5").symlink_to(tmp_path / "state" / "caracole.sqlite")
    result = run(tmp_path, "scan")
    assert result.exit_code == 0, result.output
    assert "Inbox: 0 filed, 0 duplicates, 0 left, 1 symbolic link refused" in result.output


def test_bad_config_is_a_clean_error(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("libary_dir = 1\n", encoding="utf-8")
    result = CliRunner().invoke(build_app(), ["--config", str(p), "todo"])
    assert result.exit_code == 2
    assert "libary_dir" in result.output
