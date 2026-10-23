"""``caracole musescore``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, with no pause between requests.
MuseScore is ``FakeMuseScore`` (helpers/musescore_site.py) and ntfy a fake too, handed to
the clients through ``caracole.commands._common.transport_for``, so no request can reach
the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import add_song
from helpers.musescore_site import INDEX, FakeMuseScore, challenge
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.health import is_cooling, record_block

NTFY = "https://ntfy.example/caracole-test"
OUTSIDE_SETTINGS = (
    "CARACOLE_CONFIG",
)


class FakeNtfy:
    def __init__(self):
        self.posts: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})


class Sites:
    def __init__(self):
        self.musescore = FakeMuseScore()
        self.ntfy = FakeNtfy()

    def transport(self, provider: str) -> httpx.BaseTransport:
        fakes = {"musescore": self.musescore, "ntfy": self.ntfy}
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
        "[providers.musescore]",
        "delay = [0, 0]",
        f"enabled = {'true' if enabled else 'false'}",
    ]
    if budget is not None:
        lines.append(f"budget = {budget}")
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(path), "musescore"])


def open_db(tmp_path):
    return db.connect(tmp_path / "state" / "caracole.sqlite")


def seed(tmp_path, artist="Oasis", title="Wonderwall") -> int:
    conn = open_db(tmp_path)
    try:
        return add_song(conn, artist, title).id
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


def test_musescore_reads_the_song_sitemaps_and_says_so(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Index: 2 sitemaps read." in result.stdout
    assert "MuseScore: 19 song pages in the index." in result.stdout
    conn = open_db(tmp_path)
    try:  # every request is in the event log, as in the nightly run
        logged = conn.execute("SELECT COUNT(*) FROM events WHERE provider = 'musescore'").fetchone()[0]
    finally:
        conn.close()
    assert logged == len(sites.musescore.requests) == 3


def test_musescore_rewrites_the_pages_once_it_read_something(tmp_path, sites):
    seed(tmp_path)
    stale_pages(tmp_path)
    assert run(tmp_path).exit_code == 0
    assert STALE not in pages(tmp_path)


def test_musescore_with_its_index_up_to_date_asks_nothing(tmp_path, sites):
    seed(tmp_path)
    run(tmp_path)
    sites.musescore.requests.clear()
    stale_pages(tmp_path)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "MuseScore's index is up to date: 19 song pages." in result.stdout
    assert sites.musescore.requests == [] and pages(tmp_path) == [STALE, STALE]


def test_musescore_with_no_song_asks_nothing(tmp_path, sites):
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "No song to look up on MuseScore." in result.stdout
    assert sites.musescore.requests == []


def test_musescore_turned_off_asks_nothing(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path, enabled=False)
    assert result.exit_code == 0, result.output
    assert "MuseScore is off ([providers.musescore] enabled = false)" in result.stdout
    assert sites.musescore.requests == []


def test_a_musescore_challenge_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    sites.musescore.pages[INDEX] = challenge()
    seed(tmp_path)
    stale_pages(tmp_path)
    result = run(tmp_path, ntfy=True)
    assert result.exit_code == 0, result.output
    assert "MuseScore blocked caracole" in result.stdout and "challenge page" in result.stdout
    assert sites.musescore.requests == [INDEX]
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "musescore", datetime.now(UTC))
    finally:
        conn.close()
    (alert,) = sites.ntfy.posts
    assert alert.headers["Title"] == "caracole: MuseScore blocked"
    assert STALE not in pages(tmp_path)  # the to-do page shows the cooldown


def test_musescore_asks_nothing_while_it_cools_down(tmp_path, sites):
    seed(tmp_path)
    conn = open_db(tmp_path)
    try:
        record_block(conn, "musescore", datetime.now(UTC), "musescore: 403: challenge page")
    finally:
        conn.close()
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "MuseScore is cooling down" in result.stdout
    assert sites.musescore.requests == []


def test_a_spent_musescore_budget_is_no_failure(tmp_path, sites):
    seed(tmp_path)
    result = run(tmp_path, budget=2)
    assert result.exit_code == 0, result.output
    assert "MuseScore: 12 song pages in the index." in result.stdout
    assert "MuseScore's budget of 2 requests per run is spent; the next run reads the rest of its sitemaps." in (
        result.stdout)


def test_a_musescore_error_is_no_failure(tmp_path, sites):
    sites.musescore.pages[INDEX] = (502, "Bad gateway", {"Content-Type": "text/html"})
    seed(tmp_path)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "MuseScore: 0 song pages in the index, 1 error; the next run asks again." in result.stdout
