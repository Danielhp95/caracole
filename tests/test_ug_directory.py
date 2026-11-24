"""ug/directory.py: UG's artist directory, its listings and every bare artist's page, read through fakes alone."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from caracole import db, normalize
from caracole.config import ProviderPolicy
from caracole.http import ParallelClient, ProviderBlocked
from caracole.ug import directory
from caracole.ug.bands import LETTERS, listing_url
from caracole.ug.directory import directory_pass, index_state
from helpers.ug_bands import FakeDirectory, fillers, listed
from helpers.ug_pages import SONG_DONGYE, SONG_DONGYE_CHORDS_URL, SONG_DONGYE_ID, SONG_DONGYE_TABS_URL, SONG_DONGYE_URL

NOW = datetime(2026, 11, 17, 20, 0, tzinfo=UTC)
SONG_DONGYE_ROW = listed(SONG_DONGYE_ID, SONG_DONGYE, tabs=42, bare=True)


def _client(tmp_path, site: FakeDirectory, *, now=NOW, budget=10_000, workers=4) -> ParallelClient:
    return ParallelClient("ug", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), tmp_path / "cache",
                          user_agent="caracole-test", transport=httpx.MockTransport(site.handler), workers=workers,
                          sleep=lambda s: None, wall_clock=lambda: now)


def _pass(conn, tmp_path, site, *, now=NOW, budget=10_000, workers=4, **kw):
    with _client(tmp_path, site, now=now, budget=budget, workers=workers) as client:
        return directory_pass(conn, client, now, **kw), client.requests_made


def _letters_asked(site: FakeDirectory) -> list[str]:
    return [u for u in site.requests if "/bands/" in u]


def test_every_listing_is_read_whole_and_each_artist_filed(conn, tmp_path):
    site = FakeDirectory({"s": [SONG_DONGYE_ROW, *fillers("s", 60, start=50_000)]})
    stats, made = _pass(conn, tmp_path, site, bare=False)
    assert sorted(stats.letters_done) == sorted(LETTERS) and stats.pages == len(LETTERS) + 1
    state = index_state(conn)
    assert state.complete and state.artists == 61 + 26 and state.bare == 1 and state.read == 0
    row = conn.execute("SELECT name, slug, letter, place, tabs, artist_key, forms FROM ug_directory WHERE artist_id = ?",
                       (SONG_DONGYE_ID,)).fetchone()
    assert tuple(row[:6]) == (SONG_DONGYE, "", "s", 0, 42, "song-dongye-宋冬野")
    assert "宋冬野" in row[6].split() and "songdongye" in row[6].split()
    assert directory.letters(conn)["s"].pages == 2 and directory.letters(conn)["s"].done == "2026-11-17T20:00:00Z"
    assert made == len(_letters_asked(site)) == len(LETTERS) + 1


def test_every_letters_first_pages_come_before_any_letters_rest(conn, tmp_path):
    many = {letter: fillers(letter, 50 * 12, start=10_000 * (n + 1)) for n, letter in enumerate(("a", "b"))}
    site = FakeDirectory(many)
    _pass(conn, tmp_path, site, bare=False, workers=1)
    asked = _letters_asked(site)
    first = [u for u in asked if u.endswith(("/a.htm", "/b.htm"))]
    assert len(first) == 2
    tenth = max(asked.index(listing_url(letter, 10)) for letter in ("a", "b"))
    assert all(asked.index(listing_url(letter, 11)) > tenth for letter in ("a", "b"))


def test_its_requests_are_in_flight_at_once(conn, tmp_path):
    site = FakeDirectory(hold=2.0, workers=4)
    _pass(conn, tmp_path, site, bare=False, workers=4)
    assert site.most == 4


def test_a_spent_budget_goes_on_from_the_same_page_the_next_time(conn, tmp_path):
    site = FakeDirectory({"s": fillers("s", 50 * 12, start=50_000)})
    stats, made = _pass(conn, tmp_path, site, budget=len(LETTERS) + 4, workers=1, bare=False)
    assert made == len(LETTERS) + 4 and stats.budget_exhausted
    s = directory.letters(conn)["s"]
    assert s.reading and s.next == 9 and s.pages == 12
    before = len(site.requests)
    stats, _ = _pass(conn, tmp_path, site, workers=1, bare=False)
    assert "s" in stats.letters_done and index_state(conn).complete
    again = site.requests[before:]
    assert set(again) == {listing_url("s", page) for page in range(9, 13)} | {listing_url(x) for x in "xyz"}
    assert len(site.requests) == len(set(site.requests))  # nothing asked twice


def test_a_page_cut_short_is_an_error_and_its_letter_goes_on_from_it_next_time(conn, tmp_path):
    site = FakeDirectory({"s": fillers("s", 120)})
    site.cut.add(listing_url("s", 2))
    stats, _ = _pass(conn, tmp_path, site, bare=False, workers=1)
    assert stats.errors == 1 and "s" not in stats.letters_done
    s = directory.letters(conn)["s"]
    assert s.next == 2 and s.reading
    held = conn.execute("SELECT COUNT(*) FROM ug_directory WHERE letter = 's'").fetchone()[0]
    assert held == 50  # page 1's alone: nothing missed, nothing removed
    site.cut.clear()
    stats, _ = _pass(conn, tmp_path, site, bare=False, workers=1)
    assert "s" in stats.letters_done
    assert conn.execute("SELECT COUNT(*) FROM ug_directory WHERE letter = 's'").fetchone()[0] == 120


def test_a_listing_never_removes_an_artist(conn, tmp_path):
    site = FakeDirectory({"s": [SONG_DONGYE_ROW, *fillers("s", 3)]})
    _pass(conn, tmp_path, site, bare=False)
    site.listings["s"] = fillers("s", 3)
    site.build()
    _pass(conn, tmp_path, site, now=NOW + timedelta(days=31), bare=False)
    assert conn.execute("SELECT 1 FROM ug_directory WHERE artist_id = ?", (SONG_DONGYE_ID,)).fetchone()


def test_every_letter_is_read_again_30_days_after_its_last_whole_read(conn, tmp_path):
    site = FakeDirectory({"s": fillers("s", 70)})
    _pass(conn, tmp_path, site, bare=False)
    first = len(site.requests)
    _, made = _pass(conn, tmp_path, site, now=NOW + timedelta(days=29), bare=False)
    assert made == 0 and len(site.requests) == first
    site.listings["s"] = [listed(77, "Sa New", tabs=5), *fillers("s", 70)]
    site.build()
    later = NOW + timedelta(days=30, minutes=5)
    stats, made = _pass(conn, tmp_path, site, now=later, bare=False)
    assert made == len(LETTERS) + 1 and sorted(stats.letters_done) == sorted(LETTERS)
    assert stats.new == 1 and directory.letters(conn)["s"].done == "2026-12-17T20:05:00Z"


def test_the_lock_goes_to_a_waiting_lookup_between_two_batches(conn, tmp_path):
    site = FakeDirectory({"s": fillers("s", 50 * 30)})
    handed = []

    class Handing(ParallelClient):
        def between(self):
            handed.append(site.active)  # nothing in flight
            return True

    with Handing("ug", ProviderPolicy(budget=10_000, delay=(0.0, 0.0)), tmp_path / "cache", user_agent="t",
                 transport=httpx.MockTransport(site.handler), workers=2, sleep=lambda s: None,
                 wall_clock=lambda: NOW) as client:
        directory_pass(conn, client, NOW, bare=False)
    assert len(handed) >= 2 and set(handed) == {0}


def test_a_lookup_that_met_a_block_in_the_handoff_stops_the_pass(conn, tmp_path, cfg, monkeypatch):
    from caracole.commands import _common
    from caracole.health import record_block

    site = FakeDirectory({"s": fillers("s", 50 * 30)})
    monkeypatch.setattr(_common, "transport_for", lambda provider: httpx.MockTransport(site.handler))
    calls = []

    def a_lookup_was_blocked(cfg_, conn_=None):
        calls.append(1)
        record_block(conn, "ug", datetime.now(UTC), "a lookup's 429")
        return True

    monkeypatch.setattr(_common, "hand_over", a_lookup_was_blocked)
    client = _common.directory_client(cfg, conn, "run-1")
    try:
        with pytest.raises(ProviderBlocked, match="met by a lookup"):
            directory_pass(conn, client, datetime.now(UTC), bare=False)
    finally:
        client.close()
    assert len(calls) == 1
    asked = len(site.requests)
    assert asked <= 2 * client.workers * directory.BATCH
    assert conn.execute("SELECT COUNT(*) FROM events WHERE provider = 'ug' AND run = 'run-1'").fetchone()[0] == asked


def test_bare_artists_pages_are_read_most_tabs_first_and_kept_for_searches(conn, tmp_path):
    site = FakeDirectory({"s": [SONG_DONGYE_ROW, listed(13472, "Кино", tabs=411)]})
    _pass(conn, tmp_path, site, bare=False)
    assert [a.artist_id for a in directory.due_bare(conn, NOW)] == [13472, SONG_DONGYE_ID]
    stats, _ = _pass(conn, tmp_path, site, listings=False)
    assert (stats.read, stats.gone) == (1, 1)  # Кино's page answers 404 in the fake: gone, their row too
    asked = [u for u in site.requests if "/artist/" in u]
    assert {SONG_DONGYE_CHORDS_URL, SONG_DONGYE_TABS_URL} <= set(asked)
    tabs = conn.execute("SELECT COUNT(*) FROM ug_artist_tabs WHERE page = ?", (SONG_DONGYE_URL,)).fetchone()[0]
    assert tabs == 8
    read = conn.execute("SELECT read_at, read_tabs FROM ug_directory WHERE artist_id = ?",
                        (SONG_DONGYE_ID,)).fetchone()
    assert tuple(read) == ("2026-11-17T20:00:00Z", 42)


def test_a_bare_page_is_read_again_only_once_its_row_moved_and_never_within_30_days(conn, tmp_path):
    site = FakeDirectory({"s": [SONG_DONGYE_ROW]})
    _pass(conn, tmp_path, site)
    first = site.asked(SONG_DONGYE_CHORDS_URL)
    site.listings["s"] = [listed(SONG_DONGYE_ID, SONG_DONGYE, tabs=43, bare=True)]
    site.build()
    _pass(conn, tmp_path, site, now=NOW + timedelta(days=31), listings=False)
    assert site.asked(SONG_DONGYE_CHORDS_URL) == first  # its row hasn't moved yet: the listing isn't read again
    _pass(conn, tmp_path, site, now=NOW + timedelta(days=31), bare=False)  # now it has
    _pass(conn, tmp_path, site, now=NOW + timedelta(days=31), listings=False)
    assert site.asked(SONG_DONGYE_CHORDS_URL) == first + 1


def test_a_404_from_an_artists_own_page_removes_them(conn, tmp_path):
    gone = listed(5555, "Ŝomebody", tabs=2)
    site = FakeDirectory({"s": [gone]})
    stats, _ = _pass(conn, tmp_path, site)
    assert stats.gone == 1
    assert conn.execute("SELECT 1 FROM ug_directory WHERE artist_id = 5555").fetchone() is None


def test_the_directory_names_a_songs_artist_page_a_whole_name_before_a_part(conn, tmp_path):
    site = FakeDirectory({"s": [listed(9, "Song Dongye (宋冬野) & Friends", tabs=900), SONG_DONGYE_ROW,
                                listed(10, "Song Dongye", tabs=5, bare=False)]})
    _pass(conn, tmp_path, site, bare=False)
    keys = list(normalize.name_forms("宋冬野"))
    assert directory.artist_page_for(conn, keys) == SONG_DONGYE_URL
    assert directory.artist_page_for(conn, ["nobody-at-all"]) is None
    whole = directory.artist_page_for(conn, list(normalize.name_forms("Song Dongye")))
    assert whole == "https://www.ultimate-guitar.com/artist/song_dongye_10"


def test_keys_are_made_again_from_the_names_after_a_change_of_keys(conn, tmp_path):
    site = FakeDirectory({"s": [SONG_DONGYE_ROW]})
    _pass(conn, tmp_path, site, bare=False)
    conn.execute("UPDATE ug_directory SET artist_key = 'stale', forms = 'stale'")
    db.kv_set(conn, directory.KEYS_KEY, "0")
    assert directory.ensure_current_keys(conn) >= 1
    assert conn.execute("SELECT artist_key FROM ug_directory WHERE artist_id = ?",
                        (SONG_DONGYE_ID,)).fetchone()[0] == "song-dongye-宋冬野"
    assert directory.ensure_current_keys(conn) == 0


def test_a_directory_artists_words_join_the_artist_vocabulary(conn, tmp_path):
    site = FakeDirectory({"s": [SONG_DONGYE_ROW]})
    _pass(conn, tmp_path, site, bare=False)
    assert conn.execute("SELECT 1 FROM ug_artists WHERE artist_key = 'song-dongye-宋冬野'").fetchone()
    assert conn.execute("SELECT 1 FROM ug_artist_words WHERE term = 'dongye'").fetchone()
    conn.execute("DELETE FROM ug_directory WHERE artist_id = ?", (SONG_DONGYE_ID,))
    assert conn.execute("SELECT 1 FROM ug_artists WHERE artist_key = 'song-dongye-宋冬野'").fetchone() is None


def test_a_pass_says_how_far_it_is_after_each_batch_of_listings_then_of_bare_pages(conn, tmp_path):
    # What caracole ug --directory and the run's step show while the hour goes: pages of the listings due, then the
    # bare artists' pages due, each with the requests sent so far.
    site = FakeDirectory({"s": [SONG_DONGYE_ROW, listed(13472, "Кино", tabs=411), *fillers("s", 60, start=50_000)]})
    seen = []
    stats, made = _pass(conn, tmp_path, site, workers=1, progress=seen.append)
    listings = [p for p in seen if p.phase == "listings"]
    bare = [p for p in seen if p.phase == "bare"]
    assert [p.phase for p in seen] == ["listings"] * len(listings) + ["bare"] * len(bare)
    # 28 pages (s has two, which its first says), 8 a batch with one worker: its start, four batches; then the bare
    # pages' start and their one batch
    assert [(p.done, p.due) for p in listings] == [(0, 27), (8, 27), (16, 27), (24, 28), (28, 28)]
    assert [(p.done, p.due) for p in bare] == [(0, 2), (2, 2)]
    assert bare[-1].requests == made and listings[-1].requests == bare[0].requests == 28
    assert listings[0].words() == "UG's listings · 0 of about 27 pages · 0 requests"
    assert listings[1].words() == "UG's listings · 8 of about 27 pages · letter g · 8 requests"
    assert bare[0].words() == "UG's bare artists' pages · 0 of 2 · 28 requests"
    assert stats.read + stats.gone == 2
