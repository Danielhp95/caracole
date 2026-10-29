"""sites.py: the Sites tab's data, each site's words and figures, read with no request."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from caracole import health, icons
from caracole.config import ProviderPolicy
from caracole.db import kv_set_json
from caracole.http import ROBOTS_DISALLOW
from caracole.lacuerda import LETTERS
from caracole.lacuerda_index import letters_read
from caracole.sites import (SITES, Indexed, Progress, Status, index_figures, more_paths, refresh_counts, sites_data,
                            status_of)
from caracole.stamps import shown
from caracole.youtube_fetch import route_problem


def site(key):
    return next(s for s in SITES if s.key == key)


def test_the_sites_are_icons_sources_less_the_two_that_are_no_site():
    assert [s.key for s in SITES] == [k for k in icons.SOURCES if k not in ("auto", "inbox")]


def test_every_path_named_is_one_caracole_keeps_out_of():
    for s in SITES:
        if s.key == "youtube":
            continue
        for path, words in s.paths:
            assert words
            assert any(path in ROBOTS_DISALLOW.get(host, ()) for host in s.hosts), (s.key, path)


def test_youtubes_paths_are_named_from_its_robots_txt_and_said_to_be_gone_against():
    youtube = site("youtube")
    assert [path for path, _ in youtube.paths] == ["/results", "/youtubei/"]
    assert not any(path in rules for path, _ in youtube.paths for rules in ROBOTS_DISALLOW.values())
    assert "caracole goes against" in youtube.robots


def test_the_three_sites_of_the_owners_exceptions_carry_their_terms():
    assert {s.key for s in SITES if s.terms} == {"harptabs", "gametabs", "youtube"}


def test_gametabs_says_it_asks_five_seconds_and_caracole_asks_once_a_second():
    assert "5 s" in site("gametabs").robots
    assert "once a second" in site("gametabs").robots


def test_lacuerda_closes_nothing():
    assert site("lacuerda").paths == ()
    assert more_paths(site("lacuerda")) == 0


def test_the_rest_of_a_sites_closed_paths_are_counted():
    ug = site("ug")
    every = set(ROBOTS_DISALLOW["www.ultimate-guitar.com"]) | set(ROBOTS_DISALLOW["tabs.ultimate-guitar.com"])
    assert more_paths(ug) == len(every) - len(ug.paths)
    assert more_paths(site("youtube")) == 0


def test_only_the_sites_with_no_index_say_how_they_are_asked():
    assert {s.key: s.asked for s in SITES if s.asked} == {
        "lrclib": "Asked song by song", "youtube": "Searched song by song"}


# --- what each index holds ---------------------------------------------------------------------------------------


def ug_rows(conn, *rows):
    conn.executemany("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, ?, ?, 'Chords', 'tabs1.xml', '2026-10-01T00:00:00Z', '')", rows)


def test_ug_counts_songs_by_artist_and_song_key_and_its_tabs_in_the_detail(conn):
    ug_rows(conn, (1, "eagles", "hotel california"), (2, "eagles", "hotel california"), (3, "eagles", "desperado"))
    indexed, _ = index_figures(conn)["ug"]
    assert indexed == Indexed(2, "songs", "3 tabs, from its sitemap")


def test_ug_has_progress_only_while_its_sitemaps_are_partly_read(conn):
    kv_set_json(conn, "ug:index:listed", ["tabs1.xml", "tabs2.xml", "tabs3.xml"])
    kv_set_json(conn, "ug:sitemaps", {"tabs1.xml": {}})
    assert index_figures(conn)["ug"][1] == Progress(1, 3, "sitemaps read")
    kv_set_json(conn, "ug:sitemaps", {"tabs1.xml": {}, "tabs2.xml": {}, "tabs3.xml": {}})
    assert index_figures(conn)["ug"][1] is None


def lacuerda_rows(conn, *rows):
    conn.executemany("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, songs, page) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, 'tabs/e/index0.html')", rows)


def test_lacuerda_leads_with_the_songs_caracole_knows_and_gives_the_listings_total(conn):
    lacuerda_rows(conn, ("estopa/", "estopa", "Estopa", "estopa", "", "", 30),
                  ("extremoduro/", "extremoduro", "Extremoduro", "extremoduro", "", "", 12),
                  ("estopa/tu_calorro", "estopa", "Estopa", "estopa", "Tu Calorro", "tu calorro", 0),
                  ("estopa/como_camaron", "estopa", "Estopa", "estopa", "Como Camarón", "como camaron", 0),
                  ("extremoduro/so_payaso", "extremoduro", "Extremoduro", "extremoduro", "So Payaso", "so payaso", 0))
    indexed, _ = index_figures(conn)["lacuerda"]
    assert indexed == Indexed(3, "songs", "of 42 its listings count, 2 artists")


def test_lacuerda_progress_is_letters_read(conn):
    assert index_figures(conn)["lacuerda"][1] == Progress(len(letters_read(conn)), len(LETTERS), "letters read")


def test_gtptabs_counts_songs_by_artist_and_title_key(conn):
    conn.executemany("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) "
                     "VALUES (?, 'e/eagles', 'eagles', ?, ?, 'sitemap1.xml')",
                     [("tabs/1", "hotel california", "hotel california"),
                      ("tabs/2", "hotel california", "hotel california"), ("tabs/3", "desperado", "desperado")])
    assert index_figures(conn)["gtptabs"][0] == Indexed(2, "songs", "3 tabs, from its sitemaps")


def test_musescore_counts_titles(conn):
    conn.executemany("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES (?, ?, ?, 's1.xml')",
                     [(1, "song/a-1", "hotel california"), (2, "song/a-2", "hotel california"),
                      (3, "song/b-3", "desperado")])
    assert index_figures(conn)["musescore"][0] == Indexed(2, "songs", "titles of 3 scores, from its sitemaps")


def test_harptabs_counts_tab_rows_by_key_and_artist_pages_read(conn):
    conn.executemany("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) VALUES (?, ?, ?, ?, 'sitemap.xml')",
                     [("tab/1/piano-man", "tab", 1, "piano man"), ("tab/2/piano-man", "tab", 2, "piano man"),
                      ("tab/3/heart-of-gold", "tab", 3, "heart of gold"),
                      ("artist/1/billy-joel", "artist", 1, "billy joel"), ("artist/2/neil-young", "artist", 2, "neil young")])
    conn.execute("INSERT INTO harptabs_artists (path, page_id, key, name, tabs, read_at) "
                 "VALUES ('artist/1/billy-joel', 1, 'billy joel', 'Billy Joel', 2, '2026-10-28T03:00:00Z')")
    indexed, progress = index_figures(conn)["harptabs"]
    assert indexed == Indexed(2, "songs", "3 tabs, from its sitemap")
    assert progress == Progress(1, 2, "artist pages read")


def test_gametabs_counts_tracks_of_games_and_game_pages_read(conn):
    conn.executemany("INSERT INTO gametabs_index (path, kind, game, slug, page, key, slug_key, sitemap) "
                     "VALUES (?, ?, ?, ?, 1, ?, ?, 'tabs.xml')",
                     [("tabs/hollow-knight/main-theme", "tab", "hollow-knight", "main-theme", "main theme", "main theme"),
                      ("tabs/hollow-knight/main-theme-108", "tab", "hollow-knight", "main-theme-108", "main theme",
                       "main theme 108"),
                      ("tabs/celeste/resurrections", "tab", "celeste", "resurrections", "resurrections", "resurrections"),
                      ("games/hollow-knight", "game", "hollow-knight", "", "", ""),
                      ("games/celeste", "game", "celeste", "", "", "")])
    conn.execute("INSERT INTO gametabs_games (path, game, name, tabs, read_at) "
                 "VALUES ('games/celeste', 'celeste', 'Celeste', 1, '2026-10-28T03:00:00Z')")
    indexed, progress = index_figures(conn)["gametabs"]
    assert indexed == Indexed(2, "tracks", "3 tabs of 2 games")
    assert progress == Progress(1, 2, "game pages read")


def test_an_empty_database_indexes_nothing(conn):
    figures = index_figures(conn)
    assert list(figures) == [s.key for s in SITES]
    for key in ("ug", "lacuerda", "gtptabs", "musescore", "harptabs", "gametabs"):
        assert figures[key][0].songs == 0
    assert figures["lrclib"] == (None, None)
    assert figures["youtube"] == (None, None)
    assert figures["harptabs"][1] is None  # nothing listed yet: no meter of 0 of 0
    assert figures["gametabs"][1] is None


# --- counts kept, so that building the page doesn't count a million rows -----------------------------------------


def test_a_stored_count_is_read_without_counting(conn):
    ug_rows(conn, (1, "eagles", "hotel california"))
    kv_set_json(conn, "ug:sitemaps", {"tabs1.xml": {"rows": 1}})
    refresh_counts(conn)
    ug_rows(conn, (2, "eagles", "desperado"))  # a row no index record speaks of: the stored count stands
    assert index_figures(conn)["ug"][0].songs == 1


def test_a_change_to_an_indexs_record_counts_again(conn):
    ug_rows(conn, (1, "eagles", "hotel california"))
    kv_set_json(conn, "ug:sitemaps", {"tabs1.xml": {"rows": 1}})
    refresh_counts(conn)
    ug_rows(conn, (2, "eagles", "desperado"))
    kv_set_json(conn, "ug:sitemaps", {"tabs1.xml": {"rows": 2}})  # as ug/index.py records a sitemap stored
    assert index_figures(conn)["ug"][0].songs == 2
    refresh_counts(conn)
    ug_rows(conn, (3, "eagles", "take it easy"))
    assert index_figures(conn)["ug"][0].songs == 2


def test_harptabs_keyed_again_counts_again(conn):
    conn.execute("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) "
                 "VALUES ('tab/1/cant-help', 'tab', 1, 'can t help', 'sitemap.xml')")
    refresh_counts(conn)
    conn.execute("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) "
                 "VALUES ('tab/2/piano-man', 'tab', 2, 'piano man', 'sitemap.xml')")
    conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('harptabs:index:keys', '1')")
    assert index_figures(conn)["harptabs"][0].songs == 2


def test_reading_the_figures_writes_nothing(conn):
    ug_rows(conn, (1, "eagles", "hotel california"))
    before = conn.total_changes
    index_figures(conn)
    assert conn.total_changes == before


def test_writing_the_pages_keeps_the_counts(conn, cfg):
    from caracole.overrides import Overrides
    from caracole.todo import write_pages

    ug_rows(conn, (1, "eagles", "hotel california"))
    write_pages(conn, cfg, Overrides(), datetime(2026, 10, 29, 3, 41, tzinfo=UTC))
    ug_rows(conn, (2, "eagles", "desperado"))
    assert index_figures(conn)["ug"][0].songs == 1


# --- a site's status ---------------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 29, 3, 41, tzinfo=UTC)


def test_a_site_turned_off_is_off_with_the_setting_that_turned_it_off(conn, cfg):
    off = dataclasses.replace(cfg, providers={**cfg.providers, "gtptabs": ProviderPolicy(20, (10.0, 20.0), False)})
    assert status_of(conn, off, "gtptabs", NOW) == Status("off", "Off", "[providers.gtptabs] enabled = false")


def test_youtube_without_auto_chords_is_off_with_why(conn, cfg):
    assert route_problem(cfg) is not None  # the tests' caracole has no models and no yt-dlp
    assert status_of(conn, cfg, "youtube", NOW) == Status("off", "Off", route_problem(cfg))


def test_a_cooldown_reads_until_when_and_why(conn, cfg):
    state = health.record_block(conn, "musescore", NOW - timedelta(hours=1), "challenge page")
    status = status_of(conn, cfg, "musescore", NOW)
    assert (status.state, status.label) == ("cooling", "Cooling down")
    assert shown(state.cooldown_until, local=True) in status.detail
    assert "challenge page" in status.detail


def test_errors_since_the_last_good_run(conn, cfg):
    health.record_ok(conn, "ug", NOW - timedelta(days=1))
    health.record_error(conn, "ug", NOW - timedelta(hours=2), "HTTP 502")
    assert status_of(conn, cfg, "ug", NOW) == Status("errors", "Errors", "HTTP 502")


def test_a_partial_index_reads_indexing_unless_something_is_wrong(conn, cfg):
    assert status_of(conn, cfg, "harptabs", NOW) == Status("ok", "OK", None)
    assert status_of(conn, cfg, "harptabs", NOW, partial=True) == Status("indexing", "Indexing", None)
    health.record_block(conn, "harptabs", NOW - timedelta(hours=1), "HTTP 429")
    assert status_of(conn, cfg, "harptabs", NOW, partial=True).state == "cooling"


# --- what your library keeps, the last run, the tab's data ------------------------------------------------------


def card(source=None, files=(), muse=(), versions=None):
    """A song's card as library_page.song_cards gives it, with what sites_data reads of it."""
    return {"source": source, "files": [{"name": n, "source": s} for n, s in files],
            "museScore": [{"href": h} for h in muse], "versions": versions}


def line(data, key):
    return next(s for s in data["list"] if s["key"] == key)


def test_a_song_counts_once_per_site(conn, cfg):
    cards = [card("ug", [("sheet.txt", "ug"), ("guitar-1.gp5", "gtptabs"), ("guitar-2.gp", "gtptabs")]),
             card("lacuerda", [("sheet.txt", "lacuerda")])]
    data = sites_data(conn, cfg, cards, NOW)
    assert line(data, "gtptabs")["kept"] == {"count": 2, "unit": "Guitar Pro files", "songs": 1, "detail": None}
    assert line(data, "ug")["kept"]["count"] == 1
    assert line(data, "lacuerda")["kept"] == {"count": 1, "unit": "sheet", "songs": 1, "detail": None}
    assert data["songs"] == 2


def test_lyrics_count_songs_and_the_synced_ones(conn, cfg):
    cards = [card(files=[("lyrics.txt", "lrclib"), ("lyrics.lrc", "lrclib")]), card(files=[("lyrics.txt", "lrclib")]),
             card()]
    assert line(sites_data(conn, cfg, cards, NOW), "lrclib")["kept"] == {
        "count": 2, "unit": "lyrics", "songs": 2, "detail": "1 of them synced"}


def test_musescore_counts_its_links_and_the_songs_they_are_for(conn, cfg):
    cards = [card(muse=["https://musescore.com/song/a-1", "https://musescore.com/song/a-2"]), card()]
    assert line(sites_data(conn, cfg, cards, NOW), "musescore")["kept"] == {
        "count": 2, "unit": "links", "songs": 1, "detail": None}


def test_ug_counts_the_versions_kept_beside_the_sheet(conn, cfg):
    cards = [card("ug", versions={"list": [{}, {}, {}]}), card("ug", versions={"list": [{}]}), card("ug")]
    assert line(sites_data(conn, cfg, cards, NOW), "ug")["kept"] == {
        "count": 3, "unit": "sheets", "songs": 3, "detail": "+ 2 other versions kept beside them"}


def test_harmonica_and_game_tabs_and_auto_sheets_from_youtube(conn, cfg):
    cards = [card(files=[("harmonica-1.txt", "harptabs"), ("harmonica-1.html", "harptabs")]),
             card(files=[("gametab-1.txt", "gametabs")]), card("youtube", [("sheet (auto).txt", "youtube")])]
    data = sites_data(conn, cfg, cards, NOW)
    assert line(data, "harptabs")["kept"]["count"] == 1
    assert line(data, "gametabs")["kept"]["count"] == 1
    assert line(data, "youtube")["kept"] == {"count": 1, "unit": "auto sheet", "songs": 1, "detail": None}


RUN = {"run_id": "2026-10-29T07:00:00Z", "started": "2026-10-29T07:00:00Z", "finished": "2026-10-29T07:41:00Z",
       "requests": {"ug": 58, "lrclib": 37, "lacuerda": 30}, "budgets": {"ug": 60, "lrclib": 200, "lacuerda": 30}}


def test_the_last_run_is_the_nightly_runs_record_alone(conn, cfg):
    kv_set_json(conn, "run:last", RUN)
    conn.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES "
                 "('2026-10-29T15:02:00Z', '2026-10-29T15:02:00Z', 'ug', 'https://x', 200, 'ok')")
    data = sites_data(conn, cfg, [], NOW)
    assert data["run"] == {"started": shown(datetime(2026, 10, 29, 7, 0, tzinfo=UTC), local=True),
                           "finished": shown(datetime(2026, 10, 29, 7, 41, tzinfo=UTC), local=True), "requests": 125}
    assert line(data, "ug")["night"] == {"used": 58, "budget": 60, "unit": "requests"}
    assert line(data, "gtptabs")["night"] == {"used": 0, "budget": 20, "unit": "requests"}
    assert line(data, "ug")["last"] == shown(datetime(2026, 10, 29, 15, 2, tzinfo=UTC), local=True)


def test_a_run_with_no_end_yet_gives_its_start_alone(conn, cfg):
    kv_set_json(conn, "run:last", {**RUN, "finished": None})
    run = sites_data(conn, cfg, [], NOW)["run"]
    assert run["finished"] is None
    assert run["started"] == shown(datetime(2026, 10, 29, 7, 0, tzinfo=UTC), local=True)


def test_no_nightly_run_yet(conn, cfg):
    data = sites_data(conn, cfg, [], NOW)
    assert data["run"] is None
    assert all(s["night"] is None for s in data["list"])
    assert all(s["last"] is None for s in data["list"])


def test_an_off_site_has_no_night(conn, cfg):
    kv_set_json(conn, "run:last", RUN)
    off = dataclasses.replace(cfg, providers={**cfg.providers, "gtptabs": ProviderPolicy(20, (10.0, 20.0), False)})
    data = sites_data(conn, off, [], NOW)
    assert line(data, "gtptabs")["night"] is None
    assert line(data, "gtptabs")["status"]["state"] == "off"


def test_each_line_says_its_pace_its_robots_and_its_terms(conn, cfg):
    data = sites_data(conn, cfg, [], NOW)
    assert [s["key"] for s in data["list"]] == [s.key for s in SITES]
    assert line(data, "ug")["pace"] == "10–20 s between requests"
    assert line(data, "gametabs")["pace"] == "1 s between requests"
    assert line(data, "youtube")["pace"] == "15–30 s between runs"
    assert line(data, "ug")["robots"]["paths"][0] == ["/search.php", "its search"]
    assert line(data, "ug")["robots"]["more"] == more_paths(site("ug"))
    assert line(data, "harptabs")["terms"] == site("harptabs").terms
    assert line(data, "ug")["name"] == "Ultimate Guitar"
    assert line(data, "lrclib")["indexed"] is None and line(data, "lrclib")["asked"] == "Asked song by song"
    assert data["totals"] == {"sites": 8, "indexed": 0, "kept": 0}


def test_a_partial_index_reads_indexing(conn, cfg):
    conn.execute("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) "
                 "VALUES ('artist/1/billy-joel', 'artist', 1, 'billy joel', 'sitemap.xml')")
    assert line(sites_data(conn, cfg, [], NOW), "harptabs")["status"]["state"] == "indexing"
    assert line(sites_data(conn, cfg, [], NOW), "lacuerda")["status"]["state"] == "indexing"  # no listing read yet
