"""harptabs.com in the nightly run: which songs get a harmonica tab, and how it is kept.

The site is ``FakeHarpTabs`` (helpers/harptabs_site.py) behind a real ``PoliteClient``: the sitemap and
the tab pages caracole's own user agent got, trimmed. The cache, the budget and robots.txt are the
client's real behaviour.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from conftest import add_song
from helpers.harptabs_site import BASE, NOW, SITEMAP, FakeHarpTabs, fixture, tab_page

from caracole.db import kv_get
from caracole.harptabs_fetch import CANDIDATES, HarpTabsStats, harptabs_tabs
from caracole.http import ProviderBlocked
from caracole.inbox import harmonica_files
from caracole.library import keep_file, kept_files, song_dir
from caracole.overrides import Overrides
from caracole.versions import get_version, upsert_version

PIANO_MAN = f"{BASE}/tab/25/piano-man"
LA_BAMBA = f"{BASE}/tab/89/la-bamba"


def run(site: FakeHarpTabs, conn, tmp_path: Path, now=NOW, *, budget=20, **kw) -> HarpTabsStats:
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        return harptabs_tabs(conn, client, tmp_path / "library", now, **kw)
    finally:
        client.close()


def folder(tmp_path: Path, song) -> Path:
    return song_dir(tmp_path / "library", song)


def checked(conn, song) -> str | None:
    return kv_get(conn, f"harptabs:checked:{song.id}")


def test_a_song_gets_the_tab_by_its_artist_kept_as_harmonica_1(conn, tmp_path):
    song = add_song(conn, "Ritchie Valens", "La Bamba")
    site = FakeHarpTabs()

    stats = run(site, conn, tmp_path)

    assert stats == HarpTabsStats(sitemaps=1, tried=1, kept=1)
    assert site.requests == [SITEMAP, LA_BAMBA]  # the sitemap, then the one candidate
    text = (folder(tmp_path, song) / "harmonica-1.txt").read_text(encoding="utf-8")
    assert text.startswith("-9 -9 -9  -9  -9  8  7\nPa-ra bai-lar la bam-ba\n")
    [kept] = kept_files(conn, song.id)
    version = get_version(conn, kept.version_id)
    assert (kept.name, version.provider, version.tab_id, version.slot, version.kind, version.url) == (
        "harmonica-1.txt", "harptabs", "89", "guitar", "harmonica", LA_BAMBA)
    assert version.raw == {"title": "La Bamba", "artist": "Ritchie Valens", "key": "C", "harp": "Diatonic",
                           "difficulty": "Beginner", "views": 57000, "rating": None}
    assert checked(conn, song) == "2026-10-27T03:30:00Z"
    assert [(f.name, f.key) for f in harmonica_files(conn, song.id)] == [("harmonica-1.txt", "C")]
    assert "harmonica-1.txt" in (folder(tmp_path, song) / "info.json").read_text(encoding="utf-8")


def test_the_most_viewed_of_the_artists_tabs_is_kept_and_another_artists_never(conn, tmp_path):
    song = add_song(conn, "Billy Joel", "Piano Man")
    site = FakeHarpTabs()
    site.page("tab/29525/piano-man", tab_page("Piano Man", "Billy Joel", views="2.5M", body="6 6 6\nmine\n"))

    stats = run(site, conn, tmp_path)

    assert stats.kept == 1 and site.requests == [SITEMAP, PIANO_MAN, f"{BASE}/tab/29525/piano-man"]
    assert (folder(tmp_path, song) / "harmonica-1.txt").read_text(encoding="utf-8") == "6 6 6\nmine\n"


def test_a_title_by_other_artists_alone_is_a_miss_asked_again_after_30_days(conn, tmp_path):
    song = add_song(conn, "Billy Joel", "Piano Man")
    site = FakeHarpTabs()
    site.page("tab/25/piano-man", tab_page("piano man", "Someone Else"))
    site.page("tab/29525/piano-man", tab_page("piano man", "Another One"))

    stats = run(site, conn, tmp_path)

    assert (stats.tried, stats.kept, stats.missing) == (1, 0, 1)
    assert not folder(tmp_path, song).exists() and checked(conn, song) is not None
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)) == HarpTabsStats()
    assert site.requests == []  # not asked again within 30 days, and nothing else wants a tab: no sitemap either
    assert run(site, conn, tmp_path, NOW + timedelta(days=31)).missing == 1


def test_a_song_whose_artist_the_sitemap_doesnt_list_costs_no_page(conn, tmp_path):
    # "Silent Night" is a tab there, but by no artist named as the song's: no page is read for it.
    add_song(conn, "Mariah Carey", "Silent Night")
    site = FakeHarpTabs()

    stats = run(site, conn, tmp_path)

    assert stats == HarpTabsStats(sitemaps=1) and site.requests == [SITEMAP]


def test_with_no_song_wanting_a_tab_nothing_is_asked_not_even_the_sitemap(conn, tmp_path):
    site = FakeHarpTabs()
    assert run(site, conn, tmp_path) == HarpTabsStats() and site.requests == []


def test_a_song_with_a_harmonica_tab_gets_no_other_and_a_number_held_is_never_reused(conn, tmp_path):
    song = add_song(conn, "Ritchie Valens", "La Bamba")
    other = add_song(conn, "Billy Joel", "Piano Man")
    held = upsert_version(conn, provider="harptabs", tab_id="1", song_id=song.id, slot="guitar", kind="harmonica",
                          rating=0, votes=0, version=1, label=None, url=f"{BASE}/tab/1/x", raw={},
                          now="2026-10-01T00:00:00Z")
    keep_file(conn, tmp_path / "library", song=song, version_id=held, name="harmonica-1.txt", data=b"mine", rank=1)
    folder(tmp_path, other).mkdir(parents=True)
    (folder(tmp_path, other) / "harmonica-1.txt").write_text("put there by hand")

    stats = run(FakeHarpTabs(), conn, tmp_path)

    assert stats.kept == 1
    assert (folder(tmp_path, song) / "harmonica-1.txt").read_bytes() == b"mine"
    assert (folder(tmp_path, other) / "harmonica-1.txt").read_text() == "put there by hand"
    assert (folder(tmp_path, other) / "harmonica-2.txt").exists()


def test_a_page_that_wont_parse_is_an_error_never_a_miss(conn, tmp_path):
    song = add_song(conn, "Ritchie Valens", "La Bamba")
    site = FakeHarpTabs()
    site.page("tab/89/la-bamba", "<html><body>Something went wrong</body></html>")

    stats = run(site, conn, tmp_path)

    assert (stats.tried, stats.errors, stats.kept, stats.missing) == (1, 1, 0, 0)
    [(failed, error)] = stats.failures
    assert failed.id == song.id and error.provider == "harptabs"
    assert checked(conn, song) is None  # it waits for the next run
    # Cached, it is asked for once more before it is an error again; fixed, it is read.
    site.page("tab/89/la-bamba", fixture("tab_89_la-bamba.html"))
    assert run(site, conn, tmp_path).kept == 1


def test_a_server_error_leaves_the_song_for_the_next_run(conn, tmp_path):
    # The sitemap answered 530 once (Cloudflare couldn't reach the site): an error, never a block.
    song = add_song(conn, "Ritchie Valens", "La Bamba")
    site = FakeHarpTabs()
    site.pages[SITEMAP] = (530, "<title>Connection Error - Harptabs.com</title>", {"Content-Type": "text/html"})

    stats = run(site, conn, tmp_path)

    assert stats.errors == 1 and stats.kept == 0 and checked(conn, song) is None
    assert site.requests == [SITEMAP]  # with no index there is no candidate yet


def test_a_tab_gone_since_the_sitemap_listed_it_is_passed_over(conn, tmp_path):
    song = add_song(conn, "Billy Joel", "Piano Man")
    site = FakeHarpTabs()
    site.page("tab/25/piano-man", "<html><body>Not found</body></html>", status=404)
    site.page("tab/29525/piano-man", tab_page("Piano Man", "Billy Joel"))

    assert run(site, conn, tmp_path).kept == 1
    assert get_version(conn, kept_files(conn, song.id)[0].version_id).tab_id == "29525"


def test_a_block_propagates_and_keeps_nothing(conn, tmp_path):
    add_song(conn, "Ritchie Valens", "La Bamba")
    site = FakeHarpTabs()
    site.page("tab/89/la-bamba", "Forbidden", status=403)

    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)


def test_a_spent_budget_ends_the_pass_and_the_song_resumes_from_the_cache(conn, tmp_path):
    song = add_song(conn, "Billy Joel", "Piano Man")
    site = FakeHarpTabs()
    site.page("tab/29525/piano-man", tab_page("Piano Man", "Billy Joel", views="2.5M"))

    stats = run(site, conn, tmp_path, budget=2)  # the sitemap and one candidate

    assert stats.budget_exhausted and stats.kept == 0 and checked(conn, song) is None
    site.requests.clear()
    assert run(site, conn, tmp_path).kept == 1
    assert site.requests == [f"{BASE}/tab/29525/piano-man"]  # the first candidate came from the cache


def test_an_ignored_song_is_left_alone(conn, tmp_path):
    bamba = add_song(conn, "Ritchie Valens", "La Bamba")
    piano = add_song(conn, "Billy Joel", "Piano Man")

    stats = run(FakeHarpTabs(), conn, tmp_path, overrides=Overrides(ignore=frozenset({bamba.key})))

    assert stats.kept == 1 and not kept_files(conn, bamba.id) and kept_files(conn, piano.id)


def test_a_lookup_reads_no_sitemap_and_its_song_alone(conn, tmp_path):
    bamba = add_song(conn, "Ritchie Valens", "La Bamba")
    site = FakeHarpTabs()
    assert run(site, conn, tmp_path, only={bamba.id}, refresh_index=False) == HarpTabsStats()
    assert site.requests == []  # the sitemap is the nightly run's to read
    piano = add_song(conn, "Billy Joel", "Piano Man")
    run(site, conn, tmp_path, only={piano.id})  # the index read, and Piano Man's candidates alone
    assert LA_BAMBA not in site.requests
    site.requests.clear()

    stats = run(site, conn, tmp_path, only={bamba.id}, refresh_index=False)

    assert stats.kept == 1 and site.requests == [LA_BAMBA]


def test_at_most_a_handful_of_candidates_are_read_for_one_title(conn, tmp_path):
    add_song(conn, "Billy Joel", "Piano Man")
    urls = "".join(f"<url><loc>{BASE}/tab/{n}/piano-man</loc></url>" for n in range(100, 120))
    site = FakeHarpTabs()
    site.pages[SITEMAP] = (200, fixture("sitemap.xml").replace("</urlset>", urls + "</urlset>"),
                           {"Content-Type": "application/xml"})

    stats = run(site, conn, tmp_path, budget=40)

    assert len(site.requests) == 1 + CANDIDATES and stats.kept == 1  # the rest, 404s, are passed over
    assert site.requests[1:3] == [PIANO_MAN, f"{BASE}/tab/100/piano-man"]  # lowest id first


def test_caracole_asks_with_its_own_user_agent(conn, tmp_path):
    add_song(conn, "Ritchie Valens", "La Bamba")
    site = FakeHarpTabs()
    client = site.client(tmp_path / "cache", user_agent="caracole/0.1 (personal tab library)")
    try:
        harptabs_tabs(conn, client, tmp_path / "library", NOW)
    finally:
        client.close()
    assert set(site.agents) == {"caracole/0.1 (personal tab library)"}


def test_the_sitemap_is_read_again_after_30_days_and_not_before(conn, tmp_path):
    add_song(conn, "Mariah Carey", "Silent Night")  # wants a tab, and has no candidate: the sitemap alone
    site = FakeHarpTabs()
    run(site, conn, tmp_path)
    run(site, conn, tmp_path, NOW + timedelta(days=29))
    assert site.requests == [SITEMAP]
    assert run(site, conn, tmp_path, NOW + timedelta(days=31)).sitemaps == 1
    assert site.requests == [SITEMAP, SITEMAP]


# --- a tab you picked ([harptabs]) -----------------------------------------------------------------------------


def picked(song, url: str) -> Overrides:
    from caracole.overrides import harptabs_pick_from_url

    return Overrides(harptabs={song.key: harptabs_pick_from_url(url)})


def test_the_tab_you_picked_is_kept_whoever_its_page_names(conn, tmp_path):
    song = add_song(conn, "Billy Joel", "Piano Man")
    site = FakeHarpTabs()
    site.page("tab/23862/piano-man-c-harmonica", tab_page("Piano Man (C Harmonica)", "Pharm Gal", body="6 6 6\npick\n"))

    stats = run(site, conn, tmp_path, overrides=picked(song, f"{BASE}/tab/23862/piano-man-c-harmonica"))

    assert stats == HarpTabsStats(sitemaps=1, tried=1, kept=1)
    assert site.requests == [SITEMAP, f"{BASE}/tab/23862/piano-man-c-harmonica"]  # the pick alone: no candidate
    assert (folder(tmp_path, song) / "harmonica-1.txt").read_text(encoding="utf-8") == "6 6 6\npick\n"
    [kept] = kept_files(conn, song.id)
    assert get_version(conn, kept.version_id).tab_id == "23862"


def test_a_pick_is_kept_beside_the_tab_the_song_has_and_asked_for_no_more(conn, tmp_path):
    song = add_song(conn, "Billy Joel", "Piano Man")
    site = FakeHarpTabs()
    run(site, conn, tmp_path)  # the most viewed by its artist: Piano Man, tab 25
    site.page("tab/23862/piano-man-c-harmonica", tab_page("Piano Man (C Harmonica)", "billy joel", body="pick\n"))
    overrides = picked(song, f"{BASE}/tab/23862/piano-man-c-harmonica")

    stats = run(site, conn, tmp_path, NOW + timedelta(hours=1), overrides=overrides)

    assert stats.kept == 1
    assert [f.name for f in harmonica_files(conn, song.id)] == ["harmonica-1.txt", "harmonica-2.txt"]
    assert (folder(tmp_path, song) / "harmonica-2.txt").read_text(encoding="utf-8") == "pick\n"
    site.requests.clear()
    assert run(site, conn, tmp_path, NOW + timedelta(days=40), overrides=overrides).tried == 0
    assert site.requests == []


def test_a_pick_gone_is_a_miss_asked_about_again_after_30_days(conn, tmp_path):
    song = add_song(conn, "Billy Joel", "Piano Man")
    site = FakeHarpTabs()
    overrides = picked(song, f"{BASE}/tab/404/gone")

    assert run(site, conn, tmp_path, overrides=overrides) == HarpTabsStats(sitemaps=1, tried=1, missing=1)
    assert checked(conn, song) == "2026-10-27T03:30:00Z" and kept_files(conn, song.id) == []
    assert run(site, conn, tmp_path, NOW + timedelta(days=10), overrides=overrides).tried == 0
