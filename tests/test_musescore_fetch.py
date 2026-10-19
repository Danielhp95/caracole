"""MuseScore in the nightly run: its song sitemaps into the local index, and nothing else.

The site is ``FakeMuseScore`` (helpers/musescore_site.py) behind a real ``PoliteClient``,
so the budget, the cache, conditional requests and Cloudflare's challenge are the client's
real behaviour.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from conftest import add_song
from helpers.musescore_site import BASE, CHILD, INDEX, NOW, FakeMuseScore, challenge

from caracole.http import ProviderBlocked, robots_disallows
from caracole.musescore import song_pages
from caracole.musescore_fetch import MuseScoreStats, musescore_index
from caracole.overrides import Overrides
from caracole.songs import update_song

SITEMAPS = [INDEX, CHILD.format(1), CHILD.format(18)]


def run(site: FakeMuseScore, conn, tmp_path: Path, now=NOW, *, budget=10, overrides=None) -> MuseScoreStats:
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        return musescore_index(conn, client, now, overrides=overrides)
    finally:
        client.close()


def rows(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM musescore_index").fetchone()[0]


def test_the_song_sitemaps_are_read_into_the_index(conn, tmp_path):
    song = add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore()
    assert run(site, conn, tmp_path) == MuseScoreStats(sitemaps=2)
    assert site.requests == SITEMAPS
    assert rows(conn) == 19  # twelve pages in sitemap 1, seven in sitemap 18
    assert [p.url for p in song_pages(conn, song)] == [f"{BASE}/song/wonderwall-680101"]


def test_caracole_asks_for_the_sitemaps_alone(conn, tmp_path):
    # No song page, no score, no search and nothing robots.txt closes: the pages are for you to open.
    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore()
    run(site, conn, tmp_path)
    assert all(u.startswith(f"{BASE}/sitemaps/") and robots_disallows(u) is None for u in site.requests)


def test_a_library_without_a_song_asks_nothing(conn, tmp_path):
    site = FakeMuseScore()
    assert run(site, conn, tmp_path) == MuseScoreStats()
    assert site.requests == []


def test_ignored_songs_want_no_pages(conn, tmp_path):
    ignored = add_song(conn, "Oasis", "Wonderwall")
    update_song(conn, ignored.id, status="ignored")
    in_overrides = add_song(conn, "Radiohead", "Creep")
    site = FakeMuseScore()
    run(site, conn, tmp_path, overrides=Overrides(ignore=frozenset({in_overrides.key})))
    assert site.requests == []


def test_a_challenge_is_a_block_and_the_first_night_indexes_nothing(conn, tmp_path):
    # Cloudflare's answer to caracole on 19 October 2026: the pass sends nothing more.
    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore(pages={INDEX: challenge()})
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    assert site.requests == [INDEX] and rows(conn) == 0


def test_a_challenge_later_leaves_the_index_as_it_was(conn, tmp_path):
    song = add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore()
    run(site, conn, tmp_path)
    site.pages[INDEX] = challenge()
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path, NOW + timedelta(days=31))
    assert rows(conn) == 19
    assert [p.page_id for p in song_pages(conn, song)] == [680101]


def test_a_challenged_sitemap_keeps_those_read_before_it_and_the_next_night_goes_on(conn, tmp_path):
    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore(pages={CHILD.format(18): challenge()})
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    assert rows(conn) == 12
    site.pages.update(FakeMuseScore().pages)  # Cloudflare lets caracole in again
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=3)).sitemaps == 1
    assert site.requests == [INDEX, CHILD.format(18)] and rows(conn) == 19


def test_the_budget_spreads_a_first_read_over_nights(conn, tmp_path):
    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore()
    first = run(site, conn, tmp_path, budget=2)
    assert first == MuseScoreStats(sitemaps=1, budget_exhausted=True)
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=1), budget=2).sitemaps == 1
    assert site.requests == [INDEX, CHILD.format(18)]


def test_the_index_is_read_again_after_30_days_with_conditional_requests(conn, tmp_path):
    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore()
    run(site, conn, tmp_path)
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)) == MuseScoreStats()
    assert site.requests == []
    assert run(site, conn, tmp_path, NOW + timedelta(days=31)) == MuseScoreStats()  # every one answers 304
    assert site.requests == SITEMAPS and rows(conn) == 19


def test_a_server_error_is_an_error_not_a_block(conn, tmp_path):
    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore(pages={INDEX: (502, "Bad gateway", {"Content-Type": "text/html"})})
    assert run(site, conn, tmp_path) == MuseScoreStats(errors=1)
