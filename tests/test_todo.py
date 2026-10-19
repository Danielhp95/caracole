from datetime import UTC, datetime
from urllib.parse import quote

from tabarr.db import kv_set, kv_set_json
from tabarr.health import record_block
from tabarr.library import keep_file
from tabarr.normalize import slug_key
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


def test_review_links_use_the_slugged_url(conn, cfg):
    conn.execute(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (1081462, 'soda-stereo', 'persiana-americana', 'tabs', '1', 'x', "
        "'soda-stereo/persiana-americana-tabs-1081462')"
    )
    s = add_song(conn, "Soda", "Persiana Americana")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "soda-stereo", "song_key": "persiana-americana", "score": 82.0, "step": "fuzzy_artist"},
    ])
    assert "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-tabs-1081462" in todo(conn, cfg)


def test_title_only_candidate_gets_no_alias_line(conn, cfg):
    index(conn, [(5, "jeff-buckley", "hallelujah", "chords")])
    s = add_song(conn, "Someone", "Hallelujah")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "jeff-buckley", "song_key": "hallelujah", "score": 100.0, "step": "title_only"},
    ])
    text = todo(conn, cfg)
    assert '"Someone - Hallelujah" = "jeff-buckley/hallelujah"' in text
    assert "[alias]" not in text


def covers_only(conn, artist, title, *covers):
    """A song reviewed on its title alone: its only candidates are other artists' songs (covers)."""
    s = add_song(conn, artist, title)
    song_key = slug_key(title)
    index(conn, [(500 + i, a, song_key, "chords") for i, a in enumerate(covers)])
    update_song(conn, s.id, review=True, match_decision="review", match_step="title_only", match_score=100.0,
                match_artist_key=covers[0], match_song_key=song_key, match_candidates=[
                    {"artist_key": a, "song_key": song_key, "score": 100.0, "step": "title_only"} for a in covers])
    return s


def review_item(text, display):
    return text.split(f"### {display}\n", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


def test_title_only_review_of_an_artist_ug_lists_by_bare_ids_asks_for_its_artist_page(conn, cfg):
    # UG lists Maná only by bare ids: the index has covers of the title, and nothing of Maná's.
    from tabarr.ug.fetch import songs_to_fetch

    s = covers_only(conn, "Maná", "Rayando el Sol", "ana-gabriel", "pablo-alboran")
    text = todo(conn, cfg)
    assert "## Artists to find on Ultimate Guitar (1)" in text
    assert "**Maná** (1 song)" in text
    item = review_item(text, "Maná - Rayando el Sol")
    assert "other artists' songs with this title (probably covers)" in item
    assert "[artist_url]" in item and "Artists to find" in item
    # Once the page is pasted, the next fetch looks for the song there.
    o = Overrides(artist_url={"mana": "https://www.ultimate-guitar.com/artist/mana_1234"})
    assert [x.id for x in songs_to_fetch(conn, o, NOW)] == [s.id]
    text = todo(conn, cfg, o)
    assert "## Artists to find" not in text
    assert "tabarr looks for it on Maná's UG page in the next run" in review_item(text, "Maná - Rayando el Sol")


def test_title_only_review_of_an_indexed_artist_says_its_page_is_checked_first(conn, cfg):
    index(conn, [(1, "soda-stereo", "persiana-americana", "chords")])
    s = covers_only(conn, "Soda Stereo", "De Música Ligera", "os-paralamas-do-sucesso", "ana-mena", "pereza")
    text = todo(conn, cfg)
    assert "## Artists to find" not in text
    item = review_item(text, "Soda Stereo - De Música Ligera")
    assert "other artists' songs with this title (probably covers)" in item
    assert "tabarr looks for it on Soda Stereo's UG page in the next run" in item
    # The page was read and doesn't list it: say so, and that it is read again.
    kv_set(conn, f"ug:artist_page_checked:{s.id}", "2026-10-18T03:35:00Z")
    item = review_item(todo(conn, cfg), "Soda Stereo - De Música Ligera")
    assert "tabarr didn't find it on Soda Stereo's UG page either" in item and "after 30 days" in item


def test_a_review_with_a_candidate_by_the_songs_own_artist_gets_no_covers_note(conn, cfg):
    index(conn, [(1, "radiohead", "creep", "chords")])
    s = add_song(conn, "Radio Head", "Crep")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89.0, "step": "fuzzy_title"},
        {"artist_key": "stone-temple-pilots", "song_key": "creep", "score": 80.0, "step": "title_only"},
    ])
    assert "probably covers" not in todo(conn, cfg)


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


def test_buy_list_waits_while_the_index_is_incomplete(conn, cfg):
    # A build stopped part-way: UG may have sheets for a song marked not found against it.
    from tabarr.ug.index import mark_built

    index(conn, [(1001, "oasis", "wonderwall", "chords")])
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert "## Buy list" not in text
    assert "The Ultimate Guitar index is incomplete" in text.split("\n## Review", 1)[0]
    mark_built(conn, NOW)
    text = todo(conn, cfg)
    assert "## Buy list (1)" in text and "index is incomplete" not in text


def test_buy_list_waits_for_a_due_artist_page_check(conn, cfg):
    # You just pasted the artist page: the next fetch looks for the song there before anything is bought.
    s = add_song(conn, "宋冬野", "斑马斑马")
    update_song(conn, s.id, match_decision="not_found")
    o = Overrides(artist_url={"宋冬野": "https://www.ultimate-guitar.com/artist/song_dongye_1234567"})
    text = todo(conn, cfg, o)
    assert "## Buy list" not in text
    assert "1 song waiting for the nightly fetch" in text
    # Once the page has been read for the song (and didn't list it), buying is the next step.
    kv_set(conn, f"ug:artist_page_checked:{s.id}", "2026-10-18T03:35:00Z")
    assert "## Buy list (1)" in todo(conn, cfg, o)


def test_buy_list_waits_for_lacuerda_to_be_asked(conn, cfg):
    s = add_song(conn, "Joaquín Sabina", "Y Nos Dieron las Diez")
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert "## Buy list" not in text and "1 song waiting for the nightly fetch" in text
    update_song(conn, s.id, lacuerda_checked_at="2026-10-18T03:36:00Z")  # LaCuerda had none
    text = todo(conn, cfg)
    assert "## Buy list (1)" in text and "No human sheet found yet" in text
    assert "No human sheet exists" not in text


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


def test_header_links_to_the_library_page(conn, cfg):
    head = todo(conn, cfg).split("\n## ", 1)[0]
    assert "[index.html](index.html)" in head


def test_render_status_line(conn, cfg):
    kv_set_json(conn, "render:status",
                {"at": "2026-10-18T03:40:00Z", "rendered": 12, "failed": [], "font_error": None})
    text = todo(conn, cfg)
    assert "## PDFs" in text
    assert "2026-10-18 03:40 UTC: 12 rendered, 0 failed" in text
    assert "Couldn't render" not in text and "Font" not in text


def test_render_failures_and_font_error_are_shown(conn, cfg):
    kv_set_json(conn, "render:status", {
        "at": "2026-10-18T03:40:00Z", "rendered": 3, "failed": ["Soda Stereo - Persiana Americana", "A_B - [C]"],
        "font_error": "set cjk_font or TABARR_CJK_FONT to render 宋冬野 - 斑马斑马",
    })
    text = todo(conn, cfg)
    assert "## PDFs" in text
    pdfs = text.split("## PDFs", 1)[1].split("\n## ", 1)[0]
    assert "3 rendered, 2 failed" in pdfs
    assert r"set cjk\_font or TABARR\_CJK\_FONT to render 宋冬野 - 斑马斑马" in pdfs
    assert "Soda Stereo - Persiana Americana" in pdfs and r"A\_B - \[C\]" in pdfs


def test_render_status_with_a_count_instead_of_names_still_renders(conn, cfg):
    kv_set_json(conn, "render:status", {"at": "2026-10-18T03:40:00Z", "rendered": 4, "failed": 2, "font_error": None})
    assert "4 rendered, 2 failed" in todo(conn, cfg)
    kv_set_json(conn, "render:status", {"at": "nonsense", "rendered": 4, "failed": "abc"})
    text = todo(conn, cfg)
    assert "4 rendered, 0 failed" in text and "  - a" not in text


def test_no_pdf_section_before_the_first_render_or_for_a_bad_record(conn, cfg):
    assert "## PDFs" not in todo(conn, cfg)
    kv_set_json(conn, "render:status", ["not", "a", "record"])
    assert "## PDFs" not in todo(conn, cfg)


def test_spotify_auth_line_keeps_reason_and_advice(conn, cfg):
    import dataclasses

    from tabarr.config import SpotifyConfig

    cfg = dataclasses.replace(cfg, spotify=SpotifyConfig(client_id="abc"))
    kv_set_json(conn, "source:spotify", {"state": "auth_needed", "at": "2026-10-18T03:30:00Z",
                                         "message": "the refresh token was revoked"})
    text = todo(conn, cfg)
    assert "the refresh token was revoked" in text and "Run `tabarr auth spotify`." in text


AUTOCHORDS = "## Auto-chords couldn't read these purchases"


def test_autochords_failures_listed_with_their_file_and_error(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="not_found")
    kv_set_json(conn, "autochords:status", {"at": "2026-10-18T04:12:00Z", "generated": 1, "skipped": 3, "failed": [
        {"song": "宋冬野 - 斑马斑马", "error": "RuntimeError: Error opening '…': Format not recognised.",
         "audio": str(cfg.music_dir / "宋冬野" / "斑马斑马.m4a")},
        {"song": "A_B - [C]", "error": "ValueError: too short_to [read]", "audio": "/elsewhere/a `b`.wav"},
    ]})
    text = todo(conn, cfg)
    assert f"{AUTOCHORDS} (2)\n" in text
    assert text.index("## Buy list") < text.index(AUTOCHORDS) < text.index("## Provider health")
    section = text.split(f"{AUTOCHORDS} (2)\n", 1)[1].split("\n## ", 1)[0]
    assert "Re-download" in section and "convert it" in section and "replace the original" in section
    assert "tries a changed file again" in section and "2026-10-18 04:12 UTC" in section
    # Files in Music/ are shown from there, as you'd find them on the laptop.
    assert "- **宋冬野 - 斑马斑马**: `宋冬野/斑马斑马.m4a` · RuntimeError: Error opening '…': Format not recognised." in section
    assert r"- **A\_B - \[C\]**: /elsewhere/a \`b\`.wav · ValueError: too short\_to \[read\]" in section


def test_autochords_section_only_with_failures(conn, cfg):
    assert AUTOCHORDS not in todo(conn, cfg)
    for record in ({"at": "2026-10-18T04:12:00Z", "generated": 2, "skipped": 0, "failed": []},
                   ["not", "a", "record"], {"failed": "A - T"}, {"failed": [None, "x", {"song": "A - T"}]}):
        kv_set_json(conn, "autochords:status", record)
        assert AUTOCHORDS not in todo(conn, cfg), record


def test_autochords_section_copes_with_a_bad_timestamp(conn, cfg):
    kv_set_json(conn, "autochords:status", {"at": "nonsense", "failed": [
        {"song": "A - T", "error": "EOFError", "audio": "/music/x.wav"}, {"song": "B - U"}]})
    text = todo(conn, cfg)
    assert f"{AUTOCHORDS} (1)" in text and "- **A - T**: `/music/x.wav` · EOFError" in text
    assert "nonsense" not in text and "B - U" not in text
