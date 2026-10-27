"""``caracole harptabs``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, with no pause between requests. harptabs.com is
``FakeHarpTabs`` (helpers/harptabs_site.py) and ntfy a fake too, handed to the clients through
``caracole.commands._common.transport_for``, so no request can reach the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import add_song
from helpers.harptabs_site import BASE, SITEMAP, FakeHarpTabs, artist_page
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.health import is_cooling

NTFY = "https://ntfy.example/caracole-test"


class Sites:
    def __init__(self):
        self.harptabs = FakeHarpTabs()
        self.posts: list[httpx.Request] = []

    def ntfy(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})

    def transport(self, provider: str) -> httpx.BaseTransport:
        if provider == "ntfy":
            return httpx.MockTransport(self.ntfy)
        if provider != "harptabs":
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(self.harptabs.handler)


@pytest.fixture
def sites(monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    return s


def run(tmp_path: Path, *args: str, enabled: bool = True, ntfy: bool = False):
    lines = [
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
        "[providers.harptabs]",
        "delay = [0, 0]",
        f"enabled = {'true' if enabled else 'false'}",
    ]
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(path), "harptabs", *args])


def seed(tmp_path, artist="Ritchie Valens", title="La Bamba") -> int:
    (tmp_path / "state").mkdir(exist_ok=True)
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        return add_song(conn, artist, title).id
    finally:
        conn.close()


def test_harptabs_keeps_a_tab_and_says_what_it_did(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Index: 1 sitemap read." in result.stdout
    assert "harptabs.com: 1 tried, 1 harmonica tab kept, 0 not on harptabs.com, 0 errors" in result.stdout
    assert (tmp_path / "lib" / "Ritchie Valens" / "La Bamba" / "harmonica-1.txt").is_file()
    assert (tmp_path / "lib" / "index.html").is_file()


def test_harptabs_with_no_song_asks_nothing(tmp_path, sites):
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "No song to look up on harptabs.com." in result.stdout and sites.harptabs.requests == []


def test_harptabs_turned_off_asks_nothing(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path, enabled=False)
    assert result.exit_code == 0, result.output
    assert "harptabs.com is off ([providers.harptabs] enabled = false)" in result.stdout
    assert sites.harptabs.requests == []


def test_harptabs_block_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    sites.harptabs.pages[SITEMAP] = (403, "Forbidden", {"Content-Type": "text/html"})
    seed(tmp_path)
    result = run(tmp_path, ntfy=True)
    assert result.exit_code == 0, result.output
    assert "harptabs.com blocked caracole" in result.stdout
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        assert is_cooling(conn, "harptabs", datetime.now(UTC))
    finally:
        conn.close()
    (alert,) = sites.posts
    assert alert.headers["Title"] == "caracole: harptabs.com blocked"


# --- caracole harptabs --index -------------------------------------------------------------------------------

BEATLES, BILLY, VALENS = (f"{BASE}/artist/50/the-beatles", f"{BASE}/artist/1178/billy-joel",
                          f"{BASE}/artist/7829/ritchie-valens")


def three_artists(sites) -> None:
    sites.harptabs.page("artist/50/the-beatles", artist_page("the beatles", [(172, "yesterday", "Yesterday")]))
    sites.harptabs.page("artist/7829/ritchie-valens", artist_page("Ritchie Valens", [(89, "la-bamba", "La Bamba")]))


def state(tmp_path):
    from caracole.harptabs_index import index_state

    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        return index_state(conn)
    finally:
        conn.close()


def test_index_reads_artist_pages_a_budget_at_a_time_even_for_an_empty_library(tmp_path, sites):
    three_artists(sites)

    result = run(tmp_path, "--index", "--budget", "2")

    assert result.exit_code == 0, result.output
    assert sites.harptabs.requests == [SITEMAP, BEATLES]
    assert result.stdout.splitlines() == [
        "Index: harptabs.com's sitemap read.",
        "harptabs.com: 1 artist page read; 1 of 3 artists read, 1 tab in the index.",
        "The budget of 2 requests is spent: caracole harptabs --index reads the next 2 artists, under a second "
        "of requests at this pace.",
    ]
    again = run(tmp_path, "--index")
    assert again.exit_code == 0, again.output
    assert sites.harptabs.requests[2:] == [BILLY, VALENS]
    assert again.stdout.splitlines() == ["harptabs.com: 2 artist pages read; 3 of 3 artists read, 9 tabs in the index."]
    assert state(tmp_path).complete
    done = run(tmp_path, "--index")
    assert done.stdout == "harptabs.com's artist index is up to date: 3 of 3 artists read, 9 tabs.\n"
    assert sites.harptabs.requests[4:] == []


def test_index_says_its_errors_and_its_gone_pages(tmp_path, sites):
    sites.harptabs.page("artist/50/the-beatles", "<html><body><p>Down</p></body></html>")

    result = run(tmp_path, "--index")

    assert result.exit_code == 0, result.output
    assert ("harptabs.com: 2 artist pages read, 1 gone, 1 error (asked for again next time); 2 of 3 artists read, "
            "7 tabs in the index.") in result.stdout


def test_index_with_a_budget_that_isnt_a_number_is_a_usage_error(tmp_path, sites):
    for args in (("--index", "--budget", "0"), ("--budget", "5"), ("--index", "--artist", "x")):
        result = run(tmp_path, *args)
        assert result.exit_code == 2, (args, result.output)
    assert sites.harptabs.requests == []


def test_index_turned_off_asks_nothing(tmp_path, sites):
    result = run(tmp_path, "--index", enabled=False)
    assert result.exit_code == 0 and "harptabs.com is off" in result.stdout and sites.harptabs.requests == []


def test_index_block_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    sites.harptabs.page("artist/50/the-beatles", "Forbidden", status=403)
    result = run(tmp_path, "--index", ntfy=True)
    assert result.exit_code == 0, result.output
    assert "harptabs.com blocked caracole" in result.stdout
    assert sites.harptabs.requests == [SITEMAP, BEATLES]
    assert len(sites.posts) == 1


# --- caracole harptabs --artist ------------------------------------------------------------------------------


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)  # the lookup pace's second, between two runs


def indexed(tmp_path, sites) -> None:
    """The sitemap read, as the nightly run reads it: the artists it lists."""
    result = run(tmp_path, "--index", "--budget", "1")
    assert result.exit_code == 0, result.output
    sites.harptabs.requests.clear()


def test_artist_reads_one_page_now_at_the_lookup_pace_and_once_in_30_days(tmp_path, sites, quick):
    indexed(tmp_path, sites)

    result = run(tmp_path, "--artist", "Billy Joel")

    assert result.exit_code == 0, result.output
    assert result.stdout == "Read: harptabs.com's page of billy joel lists 7 of their 98 tabs, in the index now.\n"
    assert sites.harptabs.requests == [BILLY]
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        # A lookup's request: it counts in the hour's lookup requests.
        assert [r[0] for r in conn.execute("SELECT run FROM events WHERE provider = 'harptabs' AND url = ?",
                                           (BILLY,))] [0].startswith("lookup:")
    finally:
        conn.close()
    again = run(tmp_path, "--artist", "artist/1178/billy-joel")  # by its page too; read within 30 days: no request
    assert again.stdout == result.stdout and sites.harptabs.requests == [BILLY]


def test_artist_the_sitemap_lists_no_page_of_is_not_found_and_asks_nothing(tmp_path, sites, quick):
    indexed(tmp_path, sites)
    result = run(tmp_path, "--artist", "Nobody Known")
    assert result.exit_code == 0, result.output
    assert result.stdout == "Not found: harptabs.com's sitemap lists no artist named Nobody Known.\n"
    assert sites.harptabs.requests == []


def test_artist_with_the_index_empty_says_so_and_asks_nothing(tmp_path, sites, quick):
    result = run(tmp_path, "--artist", "Billy Joel")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("Not read: harptabs.com's index is empty")
    assert sites.harptabs.requests == []


def test_artist_gone_block_and_error_exit_0(tmp_path, sites, quick):
    indexed(tmp_path, sites)
    sites.harptabs.page("artist/50/the-beatles", "<html>gone</html>", status=404)
    result = run(tmp_path, "--artist", "The Beatles")
    assert result.exit_code == 0 and result.stdout == "Not found: harptabs.com no longer has the page of The Beatles.\n"
    sites.harptabs.page("artist/7829/ritchie-valens", "oops", status=500)
    result = run(tmp_path, "--artist", "Ritchie Valens")
    assert result.exit_code == 0 and result.stdout.startswith("Not read: harptabs.com failed (")
    sites.harptabs.page("artist/7829/ritchie-valens", "Forbidden", status=403)
    result = run(tmp_path, "--artist", "Ritchie Valens")
    assert result.exit_code == 0 and result.stdout.startswith("Not read: harptabs.com blocked caracole (")
    asked = len(sites.harptabs.requests)
    result = run(tmp_path, "--artist", "Billy Joel")
    assert result.stdout.startswith("Not read: harptabs.com is cooling down after a block until ")
    assert len(sites.harptabs.requests) == asked


def test_artist_turned_off_asks_nothing(tmp_path, sites, quick):
    result = run(tmp_path, "--artist", "Billy Joel", enabled=False)
    assert result.exit_code == 0
    assert result.stdout.startswith("Not read: harptabs.com is off") and sites.harptabs.requests == []
