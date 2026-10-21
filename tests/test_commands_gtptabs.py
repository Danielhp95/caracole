"""``caracole gtptabs``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, with no pause between requests.
gtptabs.com is ``FakeGtpTabs`` (helpers/gtptabs_site.py) and ntfy a fake too, handed
to the clients through ``caracole.commands._common.transport_for``, so no request can
reach the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import add_song
from helpers.gtptabs_site import HTML, FakeGtpTabs, gp_file
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.health import is_cooling, record_block

NTFY = "https://ntfy.example/caracole-test"
INDEX = "https://gtptabs.com/sitemapGoogle.xml"
OUTSIDE_SETTINGS = (
    "CREDENTIALS_DIRECTORY", "CARACOLE_CONFIG", "CARACOLE_NTFY_TOKEN", "CARACOLE_SPOTIFY_CLIENT_SECRET",
)


class FakeNtfy:
    def __init__(self):
        self.posts: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})


class Sites:
    def __init__(self):
        self.gtptabs = FakeGtpTabs(files={26: gp_file(b"v3.00")})
        self.ntfy = FakeNtfy()

    def transport(self, provider: str) -> httpx.BaseTransport:
        fakes = {"gtptabs": self.gtptabs, "ntfy": self.ntfy}
        if provider not in fakes:
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(fakes[provider].handler)


@pytest.fixture
def sites(monkeypatch):
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    return s


def run(tmp_path: Path, *, budget: int | None = None, enabled: bool = True, ntfy: bool = False):
    lines = [
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
        "[providers.gtptabs]",
        "delay = [0, 0]",
        f"enabled = {'true' if enabled else 'false'}",
    ]
    if budget is not None:
        lines.append(f"budget = {budget}")
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(path), "gtptabs"])


def open_db(tmp_path):
    return db.connect(tmp_path / "state" / "caracole.sqlite")


def seed(tmp_path, artist="Blur", title="Beetlebum") -> int:
    conn = open_db(tmp_path)
    try:
        return add_song(conn, artist, title).id
    finally:
        conn.close()


def stamp(tmp_path, song_id):
    conn = open_db(tmp_path)
    try:
        return db.kv_get(conn, f"gtptabs:checked:{song_id}")
    finally:
        conn.close()


STALE = "as an earlier run left it\n"


def stale_pages(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    for name in ("_todo.md", "index.html"):
        (lib / name).write_text(STALE, encoding="utf-8")


def pages(tmp_path):
    return [(tmp_path / "lib" / name).read_text(encoding="utf-8") for name in ("_todo.md", "index.html")]


def test_gtptabs_downloads_a_file_and_says_so(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Index: 2 sitemaps read." in result.stdout
    assert "gtptabs.com: 1 tried, 1 Guitar Pro file kept, 0 not on gtptabs.com, 0 errors" in result.stdout
    assert (tmp_path / "lib" / "Blur" / "Beetlebum" / "guitar-1.gp3").read_bytes() == gp_file(b"v3.00")
    conn = open_db(tmp_path)
    try:  # every request is in the event log, as in the nightly run
        logged = conn.execute("SELECT COUNT(*) FROM events WHERE provider = 'gtptabs'").fetchone()[0]
    finally:
        conn.close()
    assert logged == len(sites.gtptabs.requests) == 5


def test_gtptabs_rewrites_the_pages_with_the_file(tmp_path, sites):
    seed(tmp_path)
    stale_pages(tmp_path)
    assert run(tmp_path).exit_code == 0
    todo, index = pages(tmp_path)
    assert "| gtptabs | OK |" in todo
    assert "guitar-1.gp3" in index


def test_gtptabs_with_nothing_to_do_asks_nothing(tmp_path, sites):
    stale_pages(tmp_path)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "No song to look up on gtptabs.com." in result.stdout
    assert sites.gtptabs.requests == [] and pages(tmp_path) == [STALE, STALE]


def test_gtptabs_turned_off_asks_nothing(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path, enabled=False)
    assert result.exit_code == 0, result.output
    assert "gtptabs.com is off ([providers.gtptabs] enabled = false)" in result.stdout
    assert sites.gtptabs.requests == []


def test_gtptabs_block_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    sites.gtptabs.pages[INDEX] = (403, "Forbidden", HTML)
    song_id = seed(tmp_path)
    result = run(tmp_path, ntfy=True)
    assert result.exit_code == 0, result.output
    assert "gtptabs.com blocked caracole" in result.stdout and "Nothing was marked missing" in result.stdout
    assert stamp(tmp_path, song_id) is None
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "gtptabs", datetime.now(UTC))
    finally:
        conn.close()
    (alert,) = sites.ntfy.posts
    assert alert.headers["Title"] == "caracole: gtptabs.com blocked"


def test_gtptabs_asks_nothing_while_it_cools_down(tmp_path, sites):
    seed(tmp_path)
    conn = open_db(tmp_path)
    try:
        record_block(conn, "gtptabs", datetime.now(UTC), "gtptabs: 403: HTTP 403")
    finally:
        conn.close()
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "gtptabs.com is cooling down" in result.stdout
    assert sites.gtptabs.requests == []


def test_gtptabs_spent_budget_is_no_failure(tmp_path, sites):
    song_id = seed(tmp_path)
    result = run(tmp_path, budget=4)  # the index and the artist page; no request left for the file
    assert result.exit_code == 0, result.output
    assert "budget of 4 requests per run is spent" in result.stdout
    assert stamp(tmp_path, song_id) is None
    assert not (tmp_path / "lib" / "Blur" / "Beetlebum").exists()
