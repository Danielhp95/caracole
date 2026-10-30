"""song_sites.py: which sites have each song, as its line's marks say it (library_page.py's ``sites``)."""

from datetime import UTC, datetime

import pytest

from caracole.db import kv_set
from caracole.library import keep_file
from caracole.library_page import build_library_page
from caracole.overrides import Overrides
from caracole.songs import update_song
from caracole.versions import upsert_version

from conftest import add_song
from test_library_page import songs_of

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)


def sites_of(conn, cfg, song, overrides=None):
    card = songs_of(build_library_page(conn, cfg, overrides or Overrides(), NOW))[song.display]
    return {s["source"]: (s["state"], s["said"]) for s in card["sites"]}


def kept(conn, cfg, song, provider, name, *, tab="1"):
    vid = upsert_version(conn, provider=provider, tab_id=tab, song_id=song.id, slot="sheet", kind="chords",
                         rating=None, votes=None, version=None, label=None, url=f"https://example.org/{tab}", raw={},
                         now="2026-10-17T03:30:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=name, data=b"x", rank=1)


def test_a_song_never_asked_has_every_site_grey_and_unasked_in_their_order(conn, cfg):
    s = add_song(conn, "Eagles", "Desperado")
    sites = sites_of(conn, cfg, s)
    # The sites on by default; YouTube only where its route runs, which needs auto-chords.
    assert list(sites) == ["ug", "lacuerda", "lrclib", "gtptabs", "harptabs", "gametabs", "musescore"]
    assert {state for state, _ in sites.values()} == {"unasked"}
    assert sites["harptabs"][1] == "harptabs.com: not asked yet"


def test_the_digging_my_potato_case_ug_has_none_and_harptabs_has_it(conn, cfg):
    # The line said "Not found" though a harmonica tab was there: UG had nothing, harptabs.com had the tab.
    s = add_song(conn, "Cowboy Bebop", "Digging my potato")
    update_song(conn, s.id, match_decision="not_found", matched_at="2026-10-16T03:31:00Z", lyrics_status="missing",
                lyrics_at="2026-10-15T03:00:00Z", lacuerda_checked_at="2026-10-14T03:00:00Z")
    kept(conn, cfg, s, "harptabs", "harmonica-1.txt")
    kv_set(conn, f"gtptabs:checked:{s.id}", "2026-10-13T03:00:00Z")
    kv_set(conn, f"gametabs:checked:{s.id}", "2026-10-12T03:00:00Z")
    kv_set(conn, f"gametabs:checked:{s.id}:pick", "some-pick")  # the tab picked then: no stamp, never read as one
    sites = sites_of(conn, cfg, s)
    assert sites["harptabs"] == ("have", "harptabs.com: has it")
    assert sites["ug"] == ("none", "Ultimate Guitar: nothing for it (looked 2026-10-16)")
    assert sites["lacuerda"] == ("none", "LaCuerda: nothing for it (looked 2026-10-14)")
    assert sites["lrclib"] == ("none", "LRCLIB: nothing for it (looked 2026-10-15)")
    assert sites["gtptabs"] == ("none", "gtptabs.com: nothing for it (looked 2026-10-13)")
    assert sites["gametabs"] == ("none", "gametabs.net: nothing for it (looked 2026-10-12)")


def test_ug_has_a_song_its_index_matched_even_when_its_sheet_came_from_elsewhere(conn, cfg):
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, s.id, match_decision="accept", status="found", lyrics_status="found")
    kept(conn, cfg, s, "lacuerda", "sheet.txt")
    sites = sites_of(conn, cfg, s)
    assert sites["ug"][0] == sites["lacuerda"][0] == sites["lrclib"][0] == "have"
    update_song(conn, s.id, match_decision="review")  # caracole isn't sure yet: UG is still to say
    assert sites_of(conn, cfg, s)["ug"] == ("unasked", "Ultimate Guitar: not sure which song yet")


def test_lacuerda_has_a_song_whose_sheets_caracole_met_though_none_was_kept(conn, cfg):
    s = add_song(conn, "Andrés Calamaro", "Flaca")
    upsert_version(conn, provider="lacuerda", tab_id="flaca", song_id=s.id, slot="sheet", kind="chords", rating=None,
                   votes=None, version=None, label=None, url="https://acordes.lacuerda.net/andres_calamaro/flaca",
                   raw={}, now="2026-10-17T03:30:00Z")
    update_song(conn, s.id, lacuerda_checked_at="2026-10-17T03:30:00Z")
    assert sites_of(conn, cfg, s)["lacuerda"][0] == "have"


def test_lrclib_says_an_instrumental_has_no_words(conn, cfg):
    s = add_song(conn, "Cowboy Bebop", "Tank!")
    update_song(conn, s.id, lyrics_status="instrumental")
    assert sites_of(conn, cfg, s)["lrclib"] == ("have", "LRCLIB: an instrumental, no words")


def test_musescore_has_a_possible_match_and_none_once_its_index_is_read(conn, cfg):
    s = add_song(conn, "Eagles", "Desperado")
    other = add_song(conn, "Eagles", "Take It Easy")
    conn.execute("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES (1, 'song/desperado-1', 'desperado', 's')")
    assert sites_of(conn, cfg, s)["musescore"] == ("have", "MuseScore: a possible match, by its title")
    assert sites_of(conn, cfg, other)["musescore"] == ("none", "MuseScore: nothing for it")


def test_a_site_turned_off_is_left_out(conn, cfg):
    from dataclasses import replace

    s = add_song(conn, "Eagles", "Desperado")
    off = replace(cfg, providers={**cfg.providers, "gametabs": replace(cfg.provider("gametabs"), enabled=False),
                                  "musescore": replace(cfg.provider("musescore"), enabled=False)})
    assert list(sites_of(conn, off, s)) == ["ug", "lacuerda", "lrclib", "gtptabs", "harptabs"]


@pytest.mark.parametrize("module", ["gtptabs_fetch", "harptabs_fetch", "gametabs_fetch"])
def test_the_misses_are_read_under_each_steps_own_prefix(module):
    import importlib

    from caracole import song_sites

    prefix = importlib.import_module(f"caracole.{module}").CHECKED_PREFIX
    assert prefix in song_sites.CHECKED.values()


def test_lyrics_from_megalobiz_leave_lrclib_with_nothing_timed(conn, cfg):
    # Megalobiz's lyrics show on the song's card (its Lyrics tile links to their page), not as a mark of the line;
    # LRCLIB's mark never claims lyrics it didn't give.
    from caracole.lyrics import Lyrics

    s = add_song(conn, "Eagles", "Hotel California")
    update_song(conn, s.id, lyrics_status="found", lyrics_json=Lyrics(
        plain="x", synced="[00:01.00]x", instrumental=False, duration=None, lrclib_id=None, provider="megalobiz",
        url="https://megalobiz.com/lrc/1/x").to_json(), lyrics_at="2026-10-15T03:30:00Z")
    sites = sites_of(conn, cfg, s)
    assert "megalobiz" not in sites
    assert sites["lrclib"] == ("none", "LRCLIB: nothing timed for it (looked 2026-10-15)")
