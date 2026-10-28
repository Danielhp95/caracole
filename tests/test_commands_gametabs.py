"""``caracole gametabs``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, with no pause between requests beyond robots.txt's 5 s, which
``_common.sleep`` takes (replaced here, as it records each). gametabs.net is ``FakeGameTabs``
(helpers/gametabs_site.py) and ntfy a fake too, handed to the clients through
``caracole.commands._common.transport_for``, so no request can reach the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import add_song
from helpers.gametabs_site import BASE, CHILDREN, RESTING, SITEMAP, FakeGameTabs
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.health import is_cooling

NTFY = "https://ntfy.example/caracole-test"
SITEMAPS = [SITEMAP, *CHILDREN]


class Sites:
    def __init__(self):
        self.gametabs = FakeGameTabs()
        self.posts: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def ntfy(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})

    def transport(self, provider: str) -> httpx.BaseTransport:
        if provider == "ntfy":
            return httpx.MockTransport(self.ntfy)
        if provider != "gametabs":
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(self.gametabs.handler)


@pytest.fixture
def sites(monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    monkeypatch.setattr(_common, "sleep", s.sleeps.append)
    return s


def run(tmp_path: Path, *args: str, enabled: bool = True, ntfy: bool = False):
    lines = [
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
        "[providers.gametabs]",
        "delay = [0, 0]",
        f"enabled = {'true' if enabled else 'false'}",
    ]
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(path), "gametabs", *args])


def seed(tmp_path, artist="Hollow Knight", title="Resting Grounds") -> int:
    (tmp_path / "state").mkdir(exist_ok=True)
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        return add_song(conn, artist, title).id
    finally:
        conn.close()


def test_gametabs_keeps_a_tab_and_says_what_it_did(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Index: 6 sitemaps read." in result.stdout
    assert "gametabs.net: 1 tried, 1 tab kept, 0 not on gametabs.net, 0 errors" in result.stdout
    assert (tmp_path / "lib" / "Hollow Knight" / "Resting Grounds" / "gametab-1.txt").is_file()
    assert (tmp_path / "lib" / "index.html").is_file()
    assert sites.gametabs.requests[-1] == RESTING
    # robots.txt's Crawl-delay: 5 s between two of its requests, though the pace says none (slept in slices, each a
    # look for a lookup waiting for the lock).
    gaps = len(sites.gametabs.requests) - 1
    assert 5.0 * gaps - 0.5 <= sum(sites.sleeps) <= 5.0 * gaps + 0.5


def test_gametabs_with_no_song_asks_nothing(tmp_path, sites):
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "No song to look up on gametabs.net." in result.stdout and sites.gametabs.requests == []


def test_gametabs_turned_off_asks_nothing(tmp_path, sites):
    seed(tmp_path)
    for args in ((), ("--index",)):
        result = run(tmp_path, *args, enabled=False)
        assert result.exit_code == 0, result.output
        assert "gametabs.net is off ([providers.gametabs] enabled = false)" in result.stdout
    assert sites.gametabs.requests == []


def test_gametabs_block_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    sites.gametabs.pages[SITEMAP] = (403, "Forbidden", {"Content-Type": "text/html"})
    seed(tmp_path)
    result = run(tmp_path, ntfy=True)
    assert result.exit_code == 0, result.output
    assert "gametabs.net blocked caracole" in result.stdout
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        assert is_cooling(conn, "gametabs", datetime.now(UTC))
    finally:
        conn.close()
    (alert,) = sites.posts
    assert alert.headers["Title"] == "caracole: gametabs.net blocked"
    assert sites.gametabs.requests == [SITEMAP]


# --- caracole gametabs --index ---------------------------------------------------------------------------------------


def state(tmp_path):
    from caracole.gametabs_index import index_state

    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        return index_state(conn)
    finally:
        conn.close()


def test_index_reads_game_pages_a_budget_at_a_time_even_for_an_empty_library(tmp_path, sites):
    result = run(tmp_path, "--index", "--budget", "8")

    assert result.exit_code == 0, result.output
    assert sites.gametabs.requests == [*SITEMAPS, f"{BASE}/tabs/actraiser"]
    assert result.stdout.splitlines() == [
        "Index: gametabs.net's 6 sitemaps read.",
        "gametabs.net: 1 game page read; 1 of 7 game pages read, 5 tabs in the index.",
        "The budget of 8 requests is spent: caracole gametabs --index reads the next 6 game pages, about 30 s of "
        "requests at this pace.",
    ]
    again = run(tmp_path, "--index")
    assert again.exit_code == 0, again.output
    assert len(sites.gametabs.requests) == 8 + 6
    assert again.stdout.splitlines() == [
        "gametabs.net: 6 game pages read, 4 gone; 7 of 7 game pages read, 16 tabs in the index."]
    assert state(tmp_path).complete
    done = run(tmp_path, "--index")
    assert done.stdout == "gametabs.net's game index is up to date: 7 of 7 game pages read, 16 tabs.\n"
    assert len(sites.gametabs.requests) == 14


def test_index_says_its_errors(tmp_path, sites):
    sites.gametabs.page("tabs/actraiser", "<html><body><p>Down</p></body></html>")

    result = run(tmp_path, "--index")

    assert result.exit_code == 0, result.output
    assert ("gametabs.net: 6 game pages read, 4 gone, 1 error (asked for again next time); 6 of 7 game pages read, "
            "11 tabs in the index.") in result.stdout


def test_index_with_a_budget_that_isnt_one_is_a_usage_error(tmp_path, sites):
    for args in (("--index", "--budget", "0"), ("--budget", "5")):
        result = run(tmp_path, *args)
        assert result.exit_code == 2, (args, result.output)
    assert sites.gametabs.requests == []


def test_index_block_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    sites.gametabs.page("tabs/actraiser", "Forbidden", status=403)
    result = run(tmp_path, "--index", ntfy=True)
    assert result.exit_code == 0, result.output
    assert "gametabs.net blocked caracole" in result.stdout
    assert sites.gametabs.requests == [*SITEMAPS, f"{BASE}/tabs/actraiser"]
    assert len(sites.posts) == 1


def test_the_command_imports_no_pass_when_it_registers():
    import subprocess
    import sys

    from conftest import subprocess_pythonpath

    code = ("import sys; import caracole.cli as c; c.build_app(); "
            "print(sorted(m for m in sys.modules if m.startswith('caracole.gametabs')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(Path(__file__).resolve().parent.parent / "src")})
    assert out.stdout.strip() == "[]"
