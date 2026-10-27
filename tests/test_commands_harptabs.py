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
from helpers.harptabs_site import SITEMAP, FakeHarpTabs
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


def run(tmp_path: Path, *, enabled: bool = True, ntfy: bool = False):
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
    return CliRunner().invoke(build_app(), ["--config", str(path), "harptabs"])


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
