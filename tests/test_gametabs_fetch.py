"""gametabs.net in the nightly run: which songs get a text tab of game music, and how it is kept.

The site is ``FakeGameTabs`` (helpers/gametabs_site.py) behind a real ``PoliteClient``: the sitemaps, game pages
and tab pages caracole's own user agent got, trimmed. The cache, the budget and robots.txt are the client's real
behaviour.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from conftest import add_song
from helpers.gametabs_site import (
    BASE,
    CHILDREN,
    FILLMORE,
    NOW,
    RESTING,
    SITEMAP,
    FakeGameTabs,
    fixture,
    game_page,
    tab_page,
)

from caracole.db import kv_get
from caracole.gametabs_fetch import CANDIDATES, GameTabsStats, game_forms, gametabs_tabs
from caracole.gametabs_index import read_game
from caracole.http import ProviderBlocked
from caracole.library import keep_file, kept_files, song_dir
from caracole.overrides import GameTabsPick, Overrides
from caracole.versions import get_version, upsert_version

SITEMAPS = [SITEMAP, *CHILDREN]
FIRST = f"{BASE}/tabs/hollow-knight/resting-grounds"


def run(site: FakeGameTabs, conn, tmp_path: Path, now=NOW, *, budget=20, **kw) -> GameTabsStats:
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        return gametabs_tabs(conn, client, tmp_path / "library", now, **kw)
    finally:
        client.close()


def read_games(site: FakeGameTabs, conn, tmp_path: Path, *paths: str) -> None:
    """The game pages caracole read (gametabs_index.py), as a pass before would have."""
    client = site.client(tmp_path / "cache", budget=50)
    try:
        for path in paths:
            read_game(conn, client, path, NOW)
    finally:
        client.close()


def folder(tmp_path: Path, song) -> Path:
    return song_dir(tmp_path / "library", song)


def checked(conn, song) -> str | None:
    return kv_get(conn, f"gametabs:checked:{song.id}")


def test_a_song_named_by_its_game_gets_the_tab_kept_as_gametab_1(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()

    stats = run(site, conn, tmp_path)

    assert stats == GameTabsStats(sitemaps=6, tried=1, kept=1)
    # The sitemaps, then the title's two tabs of the game: the first gone (404 here), the second read and kept.
    assert site.requests == [*SITEMAPS, FIRST, RESTING]
    text = (folder(tmp_path, song) / "gametab-1.txt").read_text(encoding="utf-8")
    assert text.startswith("Title: Resting Grounds\nSubTitle: Hollow Knight\nArtist: Christopher Larkin\n")
    [kept] = kept_files(conn, song.id)
    version = get_version(conn, kept.version_id)
    assert (kept.name, version.provider, version.tab_id, version.slot, version.kind, version.url, version.votes) == (
        "gametab-1.txt", "gametabs", "tabs/hollow-knight/resting-grounds-2", "guitar", "gametab", RESTING, 431)
    assert version.raw["composers"] == ["Christopher Larkin"] and version.raw["tuning"] == "D#ADGBE"
    assert checked(conn, song) == "2026-10-28T03:30:00Z"
    assert "gametab-1.txt" in (folder(tmp_path, song) / "info.json").read_text(encoding="utf-8")


def test_a_song_named_by_its_composer_is_found_once_its_games_page_is_read(conn, tmp_path):
    song = add_song(conn, "Yuzo Koshiro", "Fillmore")
    site = FakeGameTabs()
    # Before any game page is read, no tab is the composer's: nothing is asked but the sitemaps.
    assert run(site, conn, tmp_path).tried == 0 and site.requests == SITEMAPS
    read_games(site, conn, tmp_path, "tabs/actraiser")
    site.requests.clear()

    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1))

    assert stats.kept == 1 and site.requests == [FILLMORE]
    text = (folder(tmp_path, song) / "gametab-1.txt").read_text(encoding="utf-8")
    assert text.startswith("Fillmore\nActraiser\nComposer: Yuzo Koshiro\n")


def test_a_game_named_with_ost_after_it_is_the_game():
    assert "hollow-knight" in game_forms("Hollow Knight OST")
    assert "celeste" in game_forms("Celeste (Original Soundtrack)")
    assert "chrono-trigger" in game_forms("Chrono Trigger Original Game Soundtrack")
    assert game_forms("Ghost") == ["ghost"]


def test_the_most_viewed_of_the_songs_tabs_is_kept(conn, tmp_path):
    song = add_song(conn, "Hollow Knight OST", "Resting Grounds")
    site = FakeGameTabs()
    site.page("tabs/hollow-knight/resting-grounds", tab_page("Hollow Knight", "Resting Grounds", tab_id=8000,
                                                             views=5000, body="E|--7--|\nmine\n"))

    stats = run(site, conn, tmp_path)

    assert stats.kept == 1 and site.requests == [*SITEMAPS, FIRST, RESTING]
    assert (folder(tmp_path, song) / "gametab-1.txt").read_text(encoding="utf-8") == "E|--7--|\nmine\n"


def test_a_page_of_another_title_or_another_game_is_a_miss_asked_again_after_30_days(conn, tmp_path):
    # The slug's number never stands for a title's: a page that says it is another title is not the song's.
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    site.page("tabs/hollow-knight/resting-grounds", tab_page("Hollow Knight", "Resting Grounds Remix"))
    site.page("tabs/hollow-knight/resting-grounds-2", tab_page("Silksong", "Resting Grounds", composers=()))

    stats = run(site, conn, tmp_path)

    assert (stats.tried, stats.kept, stats.missing, stats.errors) == (1, 0, 1, 0)
    assert kept_files(conn, song.id) == [] and checked(conn, song) == "2026-10-28T03:30:00Z"
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)).tried == 0 and site.requests == []
    assert run(site, conn, tmp_path, NOW + timedelta(days=31)).missing == 1


def test_a_song_with_no_candidate_costs_no_page(conn, tmp_path):
    add_song(conn, "Billy Joel", "Piano Man")
    add_song(conn, "Someone", "Resting Grounds")  # the title, by no game or composer of it
    site = FakeGameTabs()

    stats = run(site, conn, tmp_path)

    assert stats.tried == 0 and site.requests == SITEMAPS


def test_with_no_song_wanting_a_tab_nothing_is_asked_not_even_the_sitemaps(conn, tmp_path):
    site = FakeGameTabs()
    assert run(site, conn, tmp_path) == GameTabsStats() and site.requests == []


def test_a_song_with_a_tab_from_there_gets_no_other_and_a_number_held_is_never_reused(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    # A file of yours by that name, put in the folder by hand: never replaced.
    folder(tmp_path, song).mkdir(parents=True)
    (folder(tmp_path, song) / "gametab-1.txt").write_text("my own\n", encoding="utf-8")

    assert run(site, conn, tmp_path).kept == 1
    assert (folder(tmp_path, song) / "gametab-1.txt").read_text(encoding="utf-8") == "my own\n"
    assert [f.name for f in kept_files(conn, song.id)] == ["gametab-2.txt"]
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=40)).tried == 0 and site.requests == []


def test_a_page_that_wont_parse_is_an_error_never_a_miss(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    site.page("tabs/hollow-knight/resting-grounds-2", "<html><body>Something went wrong</body></html>")

    stats = run(site, conn, tmp_path)

    assert (stats.tried, stats.errors, stats.kept, stats.missing) == (1, 1, 0, 0)
    [(failed, error)] = stats.failures
    assert failed.id == song.id and error.provider == "gametabs"
    assert checked(conn, song) is None  # it waits for the next run
    # Cached, it is asked for once more before it is an error again; fixed, it is read.
    site.page("tabs/hollow-knight/resting-grounds-2", fixture("tab_hollow-knight_resting-grounds-2.html"))
    assert run(site, conn, tmp_path).kept == 1


def test_a_server_error_leaves_the_song_for_the_next_run(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    site.pages[RESTING] = (502, "<html><body>Bad Gateway</body></html>", {"Content-Type": "text/html"})

    stats = run(site, conn, tmp_path)

    assert stats.errors == 1 and stats.kept == 0 and stats.missing == 0 and checked(conn, song) is None


def test_a_sitemap_error_leaves_the_index_as_it_was(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    site.pages[SITEMAP] = (503, "<html><body>Down</body></html>", {"Content-Type": "text/html"})

    stats = run(site, conn, tmp_path)

    assert stats.errors == 1 and stats.sitemap_errors == 1 and stats.tried == 0
    assert site.requests == [SITEMAP] and checked(conn, song) is None


def test_a_sitemap_cut_short_is_an_error_and_the_index_stays_whole(conn, tmp_path):
    from caracole import site_index
    from caracole.gametabs_fetch import SITE
    from caracole.http import ProviderError

    add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    assert run(site, conn, tmp_path).kept == 1
    rows = conn.execute("SELECT COUNT(*) FROM gametabs_index").fetchone()[0]
    cut = fixture("sitemap_1.xml")
    site.pages[CHILDREN[0]] = (200, cut[: cut.index("</urlset>") - 200], {"Content-Type": "application/xml"})

    later = NOW + timedelta(days=31)
    client = site.client(tmp_path / "cache", now=later)
    try:
        with pytest.raises(ProviderError, match="cut short"):
            site_index.refresh(conn, client, SITE, later)
    finally:
        client.close()
    assert conn.execute("SELECT COUNT(*) FROM gametabs_index").fetchone()[0] == rows


def test_a_gzipped_sitemap_reads_as_one_sent_plain(conn, tmp_path):
    add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    site.gzipped(CHILDREN[1])
    assert run(site, conn, tmp_path).kept == 1


def test_a_block_propagates_and_keeps_nothing(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    site.pages[FIRST] = (429, "Too Many Requests", {"Content-Type": "text/plain"})

    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    assert kept_files(conn, song.id) == [] and checked(conn, song) is None
    assert site.requests[-1] == FIRST  # nothing more was asked


def test_a_spent_budget_ends_the_pass_and_the_song_resumes_from_the_cache(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()

    stats = run(site, conn, tmp_path, budget=8)  # the sitemaps and the first candidate

    assert stats.budget_exhausted and stats.kept == 0 and checked(conn, song) is None
    assert site.requests == [*SITEMAPS, FIRST]
    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1))
    assert stats.kept == 1 and site.requests[-1] == RESTING


def test_an_ignored_song_is_left_alone(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    assert run(site, conn, tmp_path, overrides=Overrides(ignore=frozenset({song.key}))) == GameTabsStats()
    assert site.requests == []


def test_a_lookup_reads_no_sitemap_and_its_song_alone(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    other = add_song(conn, "Yuzo Koshiro", "Fillmore")
    site = FakeGameTabs()
    run(site, conn, tmp_path, only=(), refresh_index=True)  # nothing wanted: nothing asked
    assert site.requests == []
    run(site, conn, tmp_path, only={other.id})  # the nightly run's sitemaps, for the index
    site.requests.clear()

    stats = run(site, conn, tmp_path, only={song.id}, refresh_index=False)

    assert stats.kept == 1 and site.requests == [FIRST, RESTING]


def test_at_most_a_handful_of_candidates_are_read_for_one_title(conn, tmp_path):
    add_song(conn, "Hollow Knight", "Resting Grounds")
    many = [f"tabs/hollow-knight/resting-grounds-{n}" for n in range(3, 12)]
    from helpers.gametabs_site import urlset

    site = FakeGameTabs()
    site.pages[CHILDREN[2]] = (200, urlset(*many), {"Content-Type": "application/xml"})
    for path in [*many, "tabs/hollow-knight/resting-grounds-2"]:
        site.page(path, tab_page("Hollow Knight", "Another Title"))

    stats = run(site, conn, tmp_path)

    assert stats.missing == 1 and len(site.requests) == len(SITEMAPS) + CANDIDATES


def test_caracole_asks_with_its_own_user_agent(conn, tmp_path):
    from caracole.config import DEFAULT_USER_AGENT

    add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    client = site.client(tmp_path / "cache", user_agent=DEFAULT_USER_AGENT)
    try:
        gametabs_tabs(conn, client, tmp_path / "library", NOW)
    finally:
        client.close()
    assert set(site.agents) == {"caracole/0.1 (personal tab library)"}


def test_the_sitemaps_are_read_again_after_30_days_and_not_before(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    run(site, conn, tmp_path)
    conn.execute("DELETE FROM files WHERE song_id = ?", (song.id,))
    conn.execute("DELETE FROM kv WHERE key LIKE 'gametabs:checked:%'")
    site.requests.clear()
    run(site, conn, tmp_path, NOW + timedelta(days=29))
    assert not set(site.requests) & set(SITEMAPS)
    site.requests.clear()
    conn.execute("DELETE FROM files WHERE song_id = ?", (song.id,))
    conn.execute("DELETE FROM kv WHERE key LIKE 'gametabs:checked:%'")
    run(site, conn, tmp_path, NOW + timedelta(days=31))
    assert site.requests[:len(SITEMAPS)] == SITEMAPS


def test_the_tab_you_picked_is_kept_whatever_its_page_names(conn, tmp_path):
    song = add_song(conn, "Someone", "Something")
    site = FakeGameTabs()
    pick = GameTabsPick("actraiser", "fillmore")
    overrides = Overrides(gametabs={song.key: pick})

    stats = run(site, conn, tmp_path, overrides=overrides, refresh_index=False)

    assert stats.kept == 1 and site.requests == [FILLMORE]
    [kept] = kept_files(conn, song.id)
    assert get_version(conn, kept.version_id).tab_id == "tabs/actraiser/fillmore"
    assert kv_get(conn, f"gametabs:checked:{song.id}:pick") == "tabs/actraiser/fillmore"
    site.requests.clear()
    assert run(site, conn, tmp_path, overrides=overrides).tried == 0 and site.requests == []


def test_a_pick_is_kept_beside_the_tab_the_song_has(conn, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    site = FakeGameTabs()
    assert run(site, conn, tmp_path).kept == 1
    overrides = Overrides(gametabs={song.key: GameTabsPick("actraiser", "fillmore")})

    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1), overrides=overrides)

    assert stats.kept == 1
    assert [f.name for f in kept_files(conn, song.id)] == ["gametab-1.txt", "gametab-2.txt"]


def test_a_pick_gone_is_a_miss_asked_about_again_after_30_days(conn, tmp_path):
    song = add_song(conn, "Someone", "Something")
    site = FakeGameTabs()
    overrides = Overrides(gametabs={song.key: GameTabsPick("actraiser", "gone")})

    assert run(site, conn, tmp_path, overrides=overrides).missing == 1
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=1), overrides=overrides).tried == 0
    assert site.requests == []
    # Another pick is asked for at once.
    overrides = Overrides(gametabs={song.key: GameTabsPick("actraiser", "fillmore")})
    assert run(site, conn, tmp_path, NOW + timedelta(days=1), overrides=overrides).kept == 1


def test_a_kept_tab_from_another_site_is_no_tab_from_here(conn, tmp_path):
    # A UG text tab (tab.txt) is another file: the song still gets one from gametabs.net, beside it.
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    version = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="guitar", kind="tabs", rating=0,
                             votes=0, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x", raw={},
                             now="2026-10-01T00:00:00Z")
    keep_file(conn, tmp_path / "library", song=song, version_id=version, name="tab.txt", data=b"e|--|\n", rank=1)
    assert run(FakeGameTabs(), conn, tmp_path).kept == 1


def test_a_games_name_from_its_page_meets_an_artist_its_slug_doesnt(conn, tmp_path):
    # "Army Men: Sarge's Heroes" is slugged "army-men-sarge039s-heroes": its page's name is what meets the line.
    song = add_song(conn, "Army Men: Sarge's Heroes", "Main Theme")
    site = FakeGameTabs()
    site.page("tabs/army-men-sarge039s-heroes", game_page(
        "Army Men: Sarge's Heroes", [("main-theme-60", "Main Theme")], game_slug="army-men-sarge039s-heroes"))
    site.page("tabs/army-men-sarge039s-heroes/main-theme-60", tab_page(
        "Army Men: Sarge's Heroes", "Main Theme", game_slug="army-men-sarge039s-heroes", slug="main-theme-60"))
    assert run(site, conn, tmp_path).tried == 0  # its slug names it alone, before its page is read
    read_games(site, conn, tmp_path, "tabs/army-men-sarge039s-heroes")

    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1))

    assert stats.kept == 1 and [f.name for f in kept_files(conn, song.id)] == ["gametab-1.txt"]
