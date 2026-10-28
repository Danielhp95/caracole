"""gametabs_index.py: gametabs.net's game pages read into a local index, a budget at a time.

The site is ``FakeGameTabs`` (helpers/gametabs_site.py) behind a real ``PoliteClient``: the sitemaps and the game
pages caracole's own user agent got, trimmed, and game pages made from Actraiser's. The cache, the budget and
robots.txt are the client's real behaviour.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from conftest import add_song
from helpers.gametabs_site import BASE, CHILDREN, NOW, SITEMAP, FakeGameTabs, game_page

from caracole import normalize
from caracole.gametabs_index import (
    GamePassStats,
    IndexState,
    ensure_current_keys,
    game_pass,
    index_state,
    read_game,
)
from caracole.http import ProviderBlocked
from caracole.overrides import Overrides

SITEMAPS = [SITEMAP, *CHILDREN]
PAGES = ["tabs/actraiser", "tabs/age-of-empires-ii", "tabs/army-men-sarge039s-heroes", "tabs/final-fantasy-vii",
         "tabs/final-fantasy-vii?page=2", "tabs/game-of-thrones", "tabs/hollow-knight"]


def site_of_seven() -> FakeGameTabs:
    """The fixture's seven game pages: three captured, the rest made."""
    site = FakeGameTabs()
    site.page("tabs/age-of-empires-ii", game_page("Age of Empires II", [("main-theme-55", "Main Theme", "")]))
    site.page("tabs/army-men-sarge039s-heroes", game_page("Army Men: Sarge's Heroes", [("main-theme-60", "Main Theme")],
                                                          game_slug="army-men-sarge039s-heroes"))
    site.page("tabs/final-fantasy-vii?page=2", game_page(
        "Final Fantasy VII", [("one-winged-angel", "One-Winged Angel", "Nobuo Uematsu")], count=240,
        game_slug="final-fantasy-vii"))
    site.page("tabs/game-of-thrones", game_page("Game of Thrones", [("main-theme-108", "Main Theme", "Ramin Djawadi")]))
    return site


def run(site: FakeGameTabs, conn, tmp_path: Path, now=NOW, *, budget=20, **kw) -> GamePassStats:
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        return game_pass(conn, client, now, **kw)
    finally:
        client.close()


def tabs_of(conn, page: str) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT path, game, title, title_key, instruments, composers, views, rating, place FROM gametabs_game_tabs "
        "WHERE page = ? ORDER BY place", (page,))]


def test_a_pass_reads_the_sitemaps_then_each_game_page_in_the_sitemaps_order(conn, tmp_path):
    site = site_of_seven()

    stats = run(site, conn, tmp_path)

    assert site.requests == [*SITEMAPS, *(f"{BASE}/{p}" for p in PAGES)]
    assert stats == GamePassStats(sitemaps=6, read=7)
    assert index_state(conn) == IndexState(pages=7, read=7, tabs=5 + 1 + 1 + 5 + 1 + 1 + 6)
    assert [tuple(r) for r in conn.execute("SELECT path, game, name, tabs, read_at FROM gametabs_games "
                                           "WHERE game = 'final-fantasy-vii' ORDER BY path")] == [
        ("tabs/final-fantasy-vii", "final-fantasy-vii", "Final Fantasy VII", 240, "2026-10-28T03:30:00Z"),
        ("tabs/final-fantasy-vii?page=2", "final-fantasy-vii", "Final Fantasy VII", 240, "2026-10-28T03:30:00Z"),
    ]
    # Each tab with its title and its key, its instruments and composers, its views, its fun rating and its place.
    assert tabs_of(conn, "tabs/actraiser")[3] == (
        "tabs/actraiser/fillmore", "actraiser", "Fillmore", "fillmore", '["Guitar"]', '["Yuzo Koshiro"]', 16400, 5.0,
        3)
    assert tabs_of(conn, "tabs/hollow-knight")[5][2:6] == ("Title Theme", "title-theme", '["Guitar"]', "[]")
    assert tabs_of(conn, "tabs/final-fantasy-vii?page=2") == [
        ("tabs/final-fantasy-vii/one-winged-angel", "final-fantasy-vii", "One-Winged Angel", "one-winged-angel",
         '["Guitar"]', '["Nobuo Uematsu"]', 1200, 5.0, 0)]


def test_the_games_of_your_songs_are_read_first(conn, tmp_path):
    add_song(conn, "Hollow Knight", "Resting Grounds")  # by its game
    add_song(conn, "Ramin Djawadi", "Main Theme")  # by a title three games have a tab of
    site = site_of_seven()

    run(site, conn, tmp_path)

    order = [r.removeprefix(f"{BASE}/") for r in site.requests[len(SITEMAPS):]]
    assert order == ["tabs/age-of-empires-ii", "tabs/army-men-sarge039s-heroes", "tabs/game-of-thrones",
                     "tabs/hollow-knight", "tabs/actraiser", "tabs/final-fantasy-vii", "tabs/final-fantasy-vii?page=2"]


def test_an_ignored_songs_game_waits_its_turn(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = site_of_seven()

    run(site, conn, tmp_path, overrides=Overrides(ignore=frozenset({song.key})))

    assert site.requests == [*SITEMAPS, *(f"{BASE}/{p}" for p in PAGES)]


def test_a_pass_the_budget_cuts_short_goes_on_where_it_stopped_the_next_time(conn, tmp_path):
    site = site_of_seven()

    first = run(site, conn, tmp_path, budget=9)
    assert first == GamePassStats(sitemaps=6, read=2, budget_exhausted=True)
    assert index_state(conn) == IndexState(pages=7, read=2, tabs=6)

    second = run(site, conn, tmp_path, NOW + timedelta(hours=1), budget=9)
    assert second == GamePassStats(read=5)
    assert site.requests[9:] == [f"{BASE}/{p}" for p in PAGES[2:]]  # the sitemaps are fresh, two pages read
    assert index_state(conn).complete


def test_a_page_is_read_again_after_30_days_and_not_before(conn, tmp_path):
    site = site_of_seven()
    run(site, conn, tmp_path)
    site.requests.clear()

    assert run(site, conn, tmp_path, NOW + timedelta(days=10)) == GamePassStats()
    assert site.requests == []

    site.page("tabs/game-of-thrones", game_page("Game of Thrones", [("main-theme-108", "Main Theme", "Ramin Djawadi"),
                                                                    ("rains-of-castamere", "Rains of Castamere")]))
    later = NOW + timedelta(days=31)
    assert run(site, conn, tmp_path, later, budget=30) == GamePassStats(sitemaps=6, read=7)
    assert [t[2] for t in tabs_of(conn, "tabs/game-of-thrones")] == ["Main Theme", "Rains of Castamere"]


def test_a_game_page_gone_keeps_no_tab_and_is_not_asked_again_for_30_days(conn, tmp_path):
    site = site_of_seven()
    run(site, conn, tmp_path)
    site.page("tabs/game-of-thrones", "<html><body>Not found</body></html>", status=404)
    later = NOW + timedelta(days=31)

    stats = run(site, conn, tmp_path, later, budget=30)

    assert stats.gone == 1 and tabs_of(conn, "tabs/game-of-thrones") == []
    assert conn.execute("SELECT name FROM gametabs_games WHERE path = 'tabs/game-of-thrones'").fetchone()[0] == ""
    site.requests.clear()
    run(site, conn, tmp_path, later + timedelta(days=1))
    assert site.requests == []


def test_a_page_that_wont_parse_is_an_error_its_tabs_stay_and_it_is_asked_for_next_time(conn, tmp_path):
    site = site_of_seven()
    run(site, conn, tmp_path)
    site.page("tabs/game-of-thrones", "<html><body><p>Tabs: 3</p></body></html>")
    later = NOW + timedelta(days=31)

    stats = run(site, conn, tmp_path, later, budget=40)

    assert stats.errors == 1 and stats.read == 6
    assert [t[2] for t in tabs_of(conn, "tabs/game-of-thrones")] == ["Main Theme"]  # as the index had it
    assert conn.execute("SELECT read_at FROM gametabs_games WHERE path = 'tabs/game-of-thrones'").fetchone()[0] == (
        "2026-10-28T03:30:00Z")


def test_a_block_stops_the_pass_and_propagates(conn, tmp_path):
    site = site_of_seven()
    site.pages[f"{BASE}/tabs/age-of-empires-ii"] = (403, "Forbidden", {"Content-Type": "text/plain"})

    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    assert site.requests[-1] == f"{BASE}/tabs/age-of-empires-ii"
    assert index_state(conn).read == 1


def test_a_sitemap_that_errs_leaves_the_pages_it_listed_to_be_read(conn, tmp_path):
    site = site_of_seven()
    run(site, conn, tmp_path, budget=7)  # the sitemaps alone
    site.pages[SITEMAP] = (502, "Bad Gateway", {"Content-Type": "text/plain"})
    later = NOW + timedelta(days=31)

    stats = run(site, conn, tmp_path, later)

    assert stats.sitemap_error and stats.errors == 1 and stats.read == 7


def test_an_empty_index_and_a_spent_budget_ask_for_nothing_more(conn, tmp_path):
    site = site_of_seven()
    assert run(site, conn, tmp_path, budget=1) == GamePassStats(budget_exhausted=True)
    assert site.requests == [SITEMAP]


def test_one_game_page_now_and_once_in_30_days(conn, tmp_path):
    site = site_of_seven()
    client = site.client(tmp_path / "cache")
    try:
        page = read_game(conn, client, "tabs/actraiser", NOW)
        assert page.name == "Actraiser" and len(page.listed) == 5
        read_game(conn, client, "tabs/actraiser", NOW + timedelta(days=3))
    finally:
        client.close()
    assert site.requests == [f"{BASE}/tabs/actraiser"]


def test_a_change_of_caracoles_keys_makes_the_title_keys_again_from_the_titles(conn, tmp_path, monkeypatch):
    site = site_of_seven()
    run(site, conn, tmp_path)
    conn.execute("UPDATE gametabs_game_tabs SET title_key = 'old'")
    assert ensure_current_keys(conn) == 0  # made with these keys already
    monkeypatch.setattr(normalize, "KEY_VERSION", normalize.KEY_VERSION + 1)

    assert ensure_current_keys(conn) == 20
    assert tabs_of(conn, "tabs/actraiser")[3][3] == "fillmore"
    assert ensure_current_keys(conn) == 0
