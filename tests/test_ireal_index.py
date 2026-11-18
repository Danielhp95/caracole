"""ireal_index.py: the thread pages read into the index, and the pass over the playlists of the jazz forum.

The site is ``FakeIReal`` (helpers/ireal_site.py) behind a real ``PoliteClient``: the cache, the budget and robots.txt
are the client's real behaviour.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from helpers.ireal_site import (
    BASE,
    CHILDREN,
    JAZZ_1460,
    JAZZ_FORUM,
    NOW,
    SITEMAP,
    THAD_JONES,
    FakeIReal,
    link,
    thread_page,
)

from caracole import normalize
from caracole.db import kv_get, kv_set
from caracole.http import ProviderBlocked
from caracole.ireal_index import (
    IndexState,
    PlaylistStats,
    ensure_current_keys,
    index_state,
    playlist_pass,
    playlists,
    read_thread,
)

SITEMAPS = [SITEMAP, *CHILDREN]
STICKY = ["threads/fusion-and-smooth-jazz.210/", "threads/jazz-practice-exercises.992/", "threads/gypsy-jazz.215/",
          "threads/contemporary-jazz.204/", "threads/dixieland-trad-playlists.10591/",
          "threads/jazz-1460-standards-individual-songs.27435/"]


def run(site: FakeIReal, conn, tmp_path: Path, now=NOW, *, budget=40, **kw) -> PlaylistStats:
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        return playlist_pass(conn, client, now, **kw)
    finally:
        client.close()


def charts(conn, page: str) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT post, place, title, title_key, composer, style, key, playlist FROM ireal_charts WHERE page = ? "
        "ORDER BY post, place", (page,))]


def test_a_pass_reads_the_sitemaps_the_forums_page_then_its_playlists_the_curated_one_first(conn, tmp_path):
    site = FakeIReal()
    site.page(STICKY[2], thread_page("Gypsy Jazz", [(5, [link([("Minor Swing", "Reinhardt Django", "Gypsy Jazz",
                                                                 "A-", "[T44A-6   |E7   Z ")], playlist="Gypsy")])],
                                     path=STICKY[2]))

    stats = run(site, conn, tmp_path)

    assert stats == PlaylistStats(sitemaps=6, forums=1, read=7, gone=5)
    assert site.requests == [*SITEMAPS, f"{BASE}/{JAZZ_1460}", f"{BASE}/{JAZZ_FORUM}", *(f"{BASE}/{p}" for p in STICKY)]
    assert playlists(conn) == [JAZZ_1460, *STICKY]
    assert charts(conn, JAZZ_1460)[:2] == [
        (31492, 1, "500 Miles High", "500-miles-high", "Corea Chick", "Bossa Nova", "E-", "Jazz 1460"),
        (31492, 2, "A Night In Tunisia", "night-in-tunisia", "Gillespie Dizzy", "Latin", "D-", "Jazz 1460")]
    assert len(charts(conn, JAZZ_1460)) == 14
    assert charts(conn, STICKY[2]) == [(5, 1, "Minor Swing", "minor-swing", "Reinhardt Django", "Gypsy Jazz", "A-",
                                        "Gypsy")]
    row = conn.execute("SELECT thread, title, forum, charts, read_at FROM ireal_threads WHERE path = ?",
                       (JAZZ_1460,)).fetchone()
    assert tuple(row) == (12753, "Jazz 1460 Standards", "forums/jazz.6/", 14, "2026-11-18T03:30:00Z")
    # The other sticky threads answered 404 here: gone, with no charts and no title.
    assert conn.execute("SELECT COUNT(*) FROM ireal_threads WHERE title = ''").fetchone()[0] == 5
    assert index_state(conn) == IndexState(threads=17, read=7, charts=15, forums=1, playlists=7, playlists_read=7)
    assert index_state(conn).complete


def test_a_pass_reads_nothing_again_within_30_days_and_everything_after(conn, tmp_path):
    site = FakeIReal()
    run(site, conn, tmp_path)
    site.requests.clear()

    assert run(site, conn, tmp_path, NOW + timedelta(days=29)) == PlaylistStats()
    assert site.requests == []

    later = NOW + timedelta(days=31)
    stats = run(site, conn, tmp_path, later)
    assert stats.read == 7 and stats.forums == 1
    assert f"{BASE}/{JAZZ_1460}" in site.requests and f"{BASE}/{JAZZ_FORUM}" in site.requests


def test_the_first_playlist_alone_is_the_curated_one(conn, tmp_path):
    site = FakeIReal()
    stats = run(site, conn, tmp_path, first=1)
    assert stats == PlaylistStats(sitemaps=6, read=1)
    assert site.requests == [*SITEMAPS, f"{BASE}/{JAZZ_1460}"]
    assert index_state(conn).playlists == 1 and not index_state(conn).complete  # the forum's page not read yet


def test_a_spent_budget_ends_a_pass_and_the_next_goes_on_where_it_stopped(conn, tmp_path):
    site = FakeIReal()
    stats = run(site, conn, tmp_path, budget=9)
    assert stats.budget_exhausted and stats.read == 1 and stats.forums == 1
    site.requests.clear()
    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1), refresh_index=False)
    assert stats.read == 6 and site.requests == [f"{BASE}/{p}" for p in STICKY]


def test_a_page_that_wont_parse_is_an_error_and_its_charts_stay(conn, tmp_path):
    site = FakeIReal()
    run(site, conn, tmp_path)
    site.page(JAZZ_1460, "<html><body><h1>Oops! We ran into some problems.</h1></body></html>")
    stats = run(site, conn, tmp_path, NOW + timedelta(days=31), refresh_index=False)
    assert stats.errors == 1
    assert len(charts(conn, JAZZ_1460)) == 14  # an error is never a playlist without charts


def test_a_block_propagates(conn, tmp_path):
    site = FakeIReal()
    site.page(JAZZ_1460, "<html>Forbidden</html>", status=403)
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)


def test_a_thread_read_stores_its_charts_in_place_of_those_it_gave_before(conn, tmp_path):
    site = FakeIReal()

    def read(now):
        client = site.client(tmp_path / "cache", now=now)
        try:
            return read_thread(conn, client, THAD_JONES, now)
        finally:
            client.close()

    page = read(NOW)
    assert [p.post for p in page.posts] == [23346, 23470, 38106]
    assert charts(conn, THAD_JONES) == [
        (23346, 1, "Groove Merchant", "groove-merchant", "Jones Thad", "Medium Swing", "Bb", ""),
        (38106, 1, "Groove Merchant", "groove-merchant", "Jones Thad", "Medium Swing", "Bb", "")]
    site.page(THAD_JONES, thread_page("Groove Merchant - Thad Jones", [(9, [])]))
    assert read(NOW + timedelta(days=31)) is not None
    assert charts(conn, THAD_JONES) == []
    site.page(THAD_JONES, "<html>Not found</html>", status=404)
    assert read(NOW + timedelta(days=62)) is None
    row = conn.execute("SELECT title, charts FROM ireal_threads WHERE path = ?", (THAD_JONES,)).fetchone()
    assert tuple(row) == ("", 0)


def test_new_keys_make_the_charts_title_keys_again_with_no_request(conn, tmp_path):
    site = FakeIReal()
    run(site, conn, tmp_path, first=1)
    conn.execute("UPDATE ireal_charts SET title_key = 'old' WHERE title = 'Misty'")
    kv_set(conn, "ireal:charts:keys", "0")
    assert ensure_current_keys(conn) == 1
    assert conn.execute("SELECT title_key FROM ireal_charts WHERE title = 'Misty'").fetchone()[0] == "misty"
    assert kv_get(conn, "ireal:charts:keys") == str(normalize.KEY_VERSION)
    assert ensure_current_keys(conn) == 0
