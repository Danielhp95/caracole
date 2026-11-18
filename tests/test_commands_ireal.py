"""``caracole ireal``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, with no pause between requests, which ``_common.sleep`` takes
(replaced here, as it records each). iReal Pro's forum is ``FakeIReal`` (helpers/ireal_site.py) and ntfy a fake too,
handed to the clients through ``caracole.commands._common.transport_for``, so no request can reach the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import add_song
from helpers.ireal_site import BASE, CHILDREN, JAZZ_1460, JAZZ_FORUM, SITEMAP, THAD_JONES, FakeIReal
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.health import is_cooling

NTFY = "https://ntfy.example/caracole-test"
SITEMAPS = [SITEMAP, *CHILDREN]


class Sites:
    def __init__(self):
        self.ireal = FakeIReal()
        self.posts: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def ntfy(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})

    def transport(self, provider: str) -> httpx.BaseTransport:
        if provider == "ntfy":
            return httpx.MockTransport(self.ntfy)
        if provider != "ireal":
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(self.ireal.handler)


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
        "[providers.ireal]",
        "delay = [0, 0]",
        f"enabled = {'true' if enabled else 'false'}",
    ]
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(path), "ireal", *args])


def seed(tmp_path, artist="Thad Jones", title="Groove Merchant") -> int:
    (tmp_path / "state").mkdir(exist_ok=True)
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        return add_song(conn, artist, title).id
    finally:
        conn.close()


def test_ireal_keeps_a_chart_as_the_sheet_and_says_what_it_did(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Index: 6 sitemaps read." in result.stdout and "Index: the Jazz 1460 Standards read." in result.stdout
    assert "iReal Pro's forum: 1 tried, 1 chart kept, 0 not on iReal Pro's forum, 0 errors" in result.stdout
    here = tmp_path / "lib" / "Thad Jones" / "Groove Merchant"
    assert (here / "sheet.txt").is_file() and (here / "sheet.json").is_file()
    assert (tmp_path / "lib" / "index.html").is_file()
    assert sites.ireal.requests == [*SITEMAPS, f"{BASE}/{JAZZ_1460}", f"{BASE}/{THAD_JONES}"]


def test_ireal_reads_a_pick_a_lookup_made_while_it_read_the_playlist(tmp_path, sites, monkeypatch):
    seed(tmp_path, "Count Basie")  # no candidate of its own: only a pick reads a chart
    asked = sites.ireal.handler

    def handler(request):
        if str(request.url) == f"{BASE}/{JAZZ_1460}":  # a lookup goes first in this pause, and picks a chart
            (tmp_path / "lib").mkdir(exist_ok=True)
            (tmp_path / "lib" / "overrides.toml").write_text(
                '[ireal]\n"Count Basie - Groove Merchant" = '
                '"https://forums.irealpro.com/threads/groove-merchant-thad-jones.9518/"\n', encoding="utf-8")
            monkeypatch.setattr(_common, "_handoffs", _common.handoffs() + 1)
        return asked(request)

    sites.ireal.handler = handler
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "lib" / "Count Basie" / "Groove Merchant" / "sheet.txt").is_file()


def test_ireal_with_no_song_asks_nothing(tmp_path, sites):
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "No song to look up on iReal Pro's forum." in result.stdout and sites.ireal.requests == []


def test_ireal_turned_off_asks_nothing(tmp_path, sites):
    seed(tmp_path)
    for args in ((), ("--index",)):
        result = run(tmp_path, *args, enabled=False)
        assert result.exit_code == 0, result.output
        assert "iReal Pro's forum is off ([providers.ireal] enabled = false)" in result.stdout
    assert sites.ireal.requests == []


def test_ireal_block_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    sites.ireal.pages[SITEMAP] = (403, "Forbidden", {"Content-Type": "text/html"})
    seed(tmp_path)
    result = run(tmp_path, ntfy=True)
    assert result.exit_code == 0, result.output
    assert "iReal Pro's forum blocked caracole" in result.stdout
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        assert is_cooling(conn, "ireal", datetime.now(UTC))
    finally:
        conn.close()
    (alert,) = sites.posts
    assert alert.headers["Title"] == "caracole: iReal Pro's forum blocked"
    assert sites.ireal.requests == [SITEMAP]


def test_index_reads_the_playlists_a_budget_at_a_time_even_for_an_empty_library(tmp_path, sites):
    result = run(tmp_path, "--index", "--budget", "9")

    assert result.exit_code == 0, result.output
    assert sites.ireal.requests == [*SITEMAPS, f"{BASE}/{JAZZ_1460}", f"{BASE}/{JAZZ_FORUM}"]
    assert result.stdout.splitlines() == [
        "Index: iReal Pro's forum's 6 sitemaps read.",
        "iReal Pro's forum: 1 playlist page read; 1 of 7 playlists read, 14 charts in the index.",
        "The budget of 9 requests is spent: caracole ireal --index reads the rest the next time.",
    ]
    again = run(tmp_path, "--index")
    assert again.exit_code == 0, again.output
    assert again.stdout.splitlines() == [
        "iReal Pro's forum: 6 playlist pages read, 6 gone; 7 of 7 playlists read, 14 charts in the index."]
    done = run(tmp_path, "--index")
    assert done.stdout == ("iReal Pro's forum's index is up to date: 7 of 7 playlists read, 14 charts in the "
                           "index.\n")


def test_index_with_a_budget_that_isnt_one_is_a_usage_error(tmp_path, sites):
    for args in (("--index", "--budget", "0"), ("--budget", "5")):
        result = run(tmp_path, *args)
        assert result.exit_code == 2, (args, result.output)
    assert sites.ireal.requests == []


def test_the_command_imports_no_pass_when_it_registers():
    import subprocess
    import sys

    from conftest import subprocess_pythonpath

    code = ("import sys; import caracole.cli as c; c.build_app(); "
            "print(sorted(m for m in sys.modules if m.startswith('caracole.ireal')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(Path(__file__).resolve().parent.parent / "src")})
    assert out.stdout.strip() == "[]"
