from datetime import UTC, datetime
from urllib.parse import quote

from tabarr.db import kv_set_json
from tabarr.health import record_block
from tabarr.library import keep_file
from tabarr.overrides import Overrides
from tabarr.songs import update_song
from tabarr.todo import build_todo, search_links, write_todo
from tabarr.versions import set_coverage, set_picks, upsert_version

from conftest import add_song

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)


def index(conn, rows):
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen) VALUES (?, ?, ?, ?, '1', 'x')",
        rows,
    )


def version(conn, song, tab_id, *, slot="sheet", kind="chords", rating=4.6, votes=35, ver=2):
    return upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot=slot, kind=kind,
                          rating=rating, votes=votes, version=ver, label=None,
                          url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}", raw={}, now="x")


def todo(conn, cfg, overrides=None):
    return build_todo(conn, cfg, overrides or Overrides(), NOW)


def test_summary_counts(conn, cfg):
    add_song(conn, "A", "One")
    s2 = add_song(conn, "B", "Two")
    s3 = add_song(conn, "C", "Three")
    update_song(conn, s2.id, status="found")
    update_song(conn, s3.id, status="ignored")
    text = todo(conn, cfg)
    assert text.startswith("# tabarr to-do")
    assert "3 songs: 1 found, 1 wanted, 1 ignored" in text
    assert "2026-10-18 03:41 UTC" in text


def test_review_item_has_links_and_paste_line(conn, cfg):
    index(conn, [(1081460, "soda-stereo", "persiana-americana", "chords"),
                 (1081462, "soda-stereo", "persiana-americana", "tabs")])
    s = add_song(conn, "Soda", "Persiana Americana - Remasterizado 2007")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "soda-stereo", "song_key": "persiana-americana", "score": 82.0, "step": "fuzzy_artist"},
    ])
    text = todo(conn, cfg)
    assert "## Review (1)" in text
    assert "Soda - Persiana Americana" in text
    assert "82" in text
    assert "https://tabs.ultimate-guitar.com/tab/1081460" in text
    assert "https://tabs.ultimate-guitar.com/tab/1081462" in text
    assert '[match]\n"Soda - Persiana Americana" = "soda-stereo/persiana-americana"' in text
    assert '[alias]\n"Soda" = "soda-stereo"' in text


def test_title_only_candidate_gets_no_alias_line(conn, cfg):
    index(conn, [(5, "jeff-buckley", "hallelujah", "chords")])
    s = add_song(conn, "Someone", "Hallelujah")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "jeff-buckley", "song_key": "hallelujah", "score": 100.0, "step": "title_only"},
    ])
    text = todo(conn, cfg)
    assert '"Someone - Hallelujah" = "jeff-buckley/hallelujah"' in text
    assert "[alias]" not in text


def test_partial_sheet_listed_with_percent(conn, cfg):
    s = add_song(conn)
    v = version(conn, s, 85053)
    set_coverage(conn, v, 0.45)
    keep_file(conn, cfg.library_dir, song=s, version_id=v, name="sheet.txt", data=b"x", rank=1)
    text = todo(conn, cfg)
    assert "## Partial sheets (1)" in text
    assert "Soda Stereo - De Música Ligera" in text and "45%" in text
    assert "https://tabs.ultimate-guitar.com/tab/85053" in text


def test_buy_list_links(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马，斑马", album="安和桥北", duration_ms=253000)
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert "## Buy list (1)" in text
    assert "宋冬野 - 斑马，斑马" in text
    links = search_links("宋冬野", "斑马，斑马")
    for name in ("bandcamp", "qobuz", "itunes", "chordify", "songsterr", "youtube"):
        assert links[name] in text
    assert quote("宋冬野 斑马，斑马 吉他教学") in links["youtube"]
    assert "guitar+lesson" in search_links("Radiohead", "Creep")["youtube"] or "guitar%20lesson" in search_links("Radiohead", "Creep")["youtube"]


def test_buy_list_excludes_found_and_songs_with_audio(conn, cfg):
    s1 = add_song(conn, "A", "Has Audio")
    update_song(conn, s1.id, audio_path="/music/a.flac", match_decision="not_found")
    s2 = add_song(conn, "B", "Found")
    update_song(conn, s2.id, status="found", match_decision="accept")
    assert "## Buy list" not in todo(conn, cfg)


def test_buy_list_waits_for_pending_fetches(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="accept")
    text = todo(conn, cfg)
    assert "## Buy list" not in text
    assert "1 song waiting for the nightly fetch" in text


def test_guitar_pro_pages_to_click(conn, cfg):
    s = add_song(conn)
    v1 = version(conn, s, 555890, slot="guitar", kind="guitar-pro", rating=4.2, votes=5, ver=1)
    v2 = version(conn, s, 555891, slot="guitar", kind="power", rating=4.0, votes=2, ver=1)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v1, v2])
    text = todo(conn, cfg)
    assert "## Guitar Pro pages to click (2)" in text
    assert "https://tabs.ultimate-guitar.com/tab/555890" in text
    assert "_inbox" in text
    # Once a file exists for a pick it's no longer listed.
    keep_file(conn, cfg.library_dir, song=s, version_id=v1, name="guitar-1.gp5", data=b"gp", rank=1)
    keep_file(conn, cfg.library_dir, song=s, version_id=v2, name="guitar-2.ptb", data=b"pt", rank=2)
    assert "## Guitar Pro pages to click" not in todo(conn, cfg)


def test_guitar_parts_not_found(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="accept", ug_checked_at="2026-10-18T03:35:00Z")
    text = todo(conn, cfg)
    assert "## Guitar parts not found (1)" in text
    assert search_links("Radiohead", "Creep")["songsterr"] in text


def test_inbox_unmatched_files_listed(conn, cfg):
    inbox = cfg.library_dir / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "mystery.gp5").write_bytes(b"x")
    (inbox / ".hidden").write_bytes(b"x")
    text = todo(conn, cfg)
    assert "## Inbox: files tabarr couldn't place (1)" in text
    assert "mystery.gp5" in text and ".hidden" not in text


def test_missing_lyrics(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马斑马")
    update_song(conn, s.id, lyrics_status="missing")
    assert "## Missing lyrics (1)" in todo(conn, cfg)


def test_find_artist_on_ug(conn, cfg):
    s = add_song(conn, "Joaquín Sabina", "19 Días y 500 Noches")
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert "## Artists to find on Ultimate Guitar (1)" in text
    assert '[artist_url]\n"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/' in text
    assert "search.php" in text  # a link for you to click; tabarr itself never requests search.php
    # Known artist page (override): no longer asked for.
    o = Overrides(artist_url={"joaquin-sabina": "https://www.ultimate-guitar.com/artist/joaquin_sabina_1"})
    assert "## Artists to find" not in todo(conn, cfg, o)


def test_find_artist_skips_artists_in_index(conn, cfg):
    index(conn, [(1, "soda-stereo", "signos", "chords")])
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, s.id, match_decision="not_found")
    assert "## Artists to find" not in todo(conn, cfg)


def test_provider_health_shows_cooldown(conn, cfg):
    record_block(conn, "ug", NOW, "HTTP 403 on https://tabs.ultimate-guitar.com/tab/1")
    text = todo(conn, cfg)
    assert "## Provider health" in text
    assert "cooling down until 2026-10-19 03:41 UTC" in text
    assert "HTTP 403" in text


def test_suggestions_exclude_songs_already_wanted(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    kv_set_json(conn, "spotify:top_tracks", [
        {"id": "1", "title": "Creep", "artists": ["Radiohead"]},
        {"id": "2", "title": "Karma Police", "artists": ["Radiohead"]},
    ])
    text = todo(conn, cfg)
    assert "## Suggestions from your Spotify top tracks (1)" in text
    assert "Radiohead - Karma Police" in text


def test_sources_status(conn, cfg):
    import dataclasses

    from tabarr.config import SpotifyConfig

    text = todo(conn, cfg)
    assert "Spotify: not configured" in text
    cfg = dataclasses.replace(cfg, spotify=SpotifyConfig(client_id="abc"))
    assert "Spotify: not synced yet" in todo(conn, cfg)
    kv_set_json(conn, "source:spotify", {"state": "auth_needed", "at": "2026-10-18T03:30:00Z",
                                         "message": "run `tabarr auth spotify`"})
    kv_set_json(conn, "source:wanted", {"at": "2026-10-18T03:30:00Z", "lines": 12, "new": 2,
                                        "errors": [[3, "expected \"Artist - Title\""]]})
    text = todo(conn, cfg)
    assert "tabarr auth spotify" in text
    assert "wanted.txt: 12 songs" in text and "line 3" in text


def test_markdown_special_characters_are_escaped(conn, cfg):
    s = add_song(conn, "Artist_with_[brackets]*", "Title")
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert r"Artist\_with\_\[brackets\]\*" in text


def test_write_todo(cfg):
    path = write_todo(cfg.library_dir, "# tabarr to-do\n")
    assert path == cfg.library_dir / "_todo.md"
    assert path.read_text(encoding="utf-8") == "# tabarr to-do\n"
