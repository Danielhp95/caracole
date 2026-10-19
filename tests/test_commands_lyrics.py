"""``tabarr lyrics`` and ``tabarr lacuerda``, run through the CLI.

Each test writes a tabarr.toml rooted in tmp_path, with no pause between
requests. LRCLIB, LaCuerda and ntfy are fakes behind ``httpx.MockTransport``,
handed to the clients through ``tabarr.commands._common.transport_for``, so no
request can reach the network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from conftest import add_song
from typer.testing import CliRunner

from tabarr import db
from tabarr.cli import build_app
from tabarr.commands import _common
from tabarr.health import get_state, is_cooling, record_block
from tabarr.lyrics import Lyrics
from tabarr.songs import get_song, update_song

LRCLIB_FIXTURES = Path(__file__).parent / "fixtures" / "lrclib"
LACUERDA_FIXTURES = Path(__file__).parent / "fixtures" / "lacuerda"
SODA = "https://acordes.lacuerda.net/soda_stereo/"
DML_3 = "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera-3.shtml"
NTFY = "https://ntfy.example/tabarr-test"

# Every line is in the LaCuerda version fixture's sheet (all invented).
SHEET_LYRICS = """\
Cruzo la plaza con el café frío
y cuento las luces del tren de las seis
nadie me espera en el andén vacío
guardo tu nombre y no sé qué hacer
"""

# Environment load_config would read; none of it may leak into a test.
OUTSIDE_SETTINGS = ("CREDENTIALS_DIRECTORY", "TABARR_CONFIG", "TABARR_NTFY_TOKEN", "TABARR_SPOTIFY_CLIENT_SECRET")


class FakeLrclib:
    """``/api/get`` answers its records (by artist and track) and 503 otherwise, as live;
    ``/api/search`` lists nothing. ``status`` answers every request with that status."""

    def __init__(self, records=(), status: int | None = None):
        self.records = list(records)
        self.status = status
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.status is not None:
            return httpx.Response(self.status, text="nope")
        params = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        if request.url.path == "/api/get":
            for r in self.records:
                if (r["artistName"], r["trackName"]) == (params["artist_name"], params["track_name"]):
                    return httpx.Response(200, json=r)
            return httpx.Response(503, json={"name": "ServerOverloaded"})
        if request.url.path == "/api/search":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.url}")


class FakeLaCuerda:
    """Pages by URL; an unknown artist gets LaCuerda's HTTP 200 "aqui llega" body."""

    def __init__(self, pages=None, status: int | None = None):
        self.pages = dict(pages or {})
        self.status = status
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if self.status is not None:
            return httpx.Response(self.status, text="nope")
        if url in self.pages:
            return httpx.Response(200, text=self.pages[url])
        slug = request.url.path.strip("/")
        if request.url.path.endswith("/") and "/" not in slug:
            return httpx.Response(200, text=f"aqui llega:../tabs/{slug[0]}/{slug}/index.html")
        raise AssertionError(f"unexpected request: {url}")


class FakeNtfy:
    def __init__(self):
        self.posts: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})


class Sites:
    def __init__(self):
        self.lrclib = FakeLrclib()
        self.lacuerda = FakeLaCuerda()
        self.ntfy = FakeNtfy()

    def transport(self, provider: str) -> httpx.BaseTransport:
        fakes = {"lrclib": self.lrclib, "lacuerda": self.lacuerda, "ntfy": self.ntfy}
        if provider not in fakes:
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(lambda request: fakes[provider].handler(request))


@pytest.fixture
def sites(monkeypatch):
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    return s


def write_config(tmp_path: Path, *, budgets=None, ntfy=False) -> Path:
    budgets = budgets or {}
    lines = [
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
    ]
    for provider in ("lrclib", "lacuerda"):
        lines += [f"[providers.{provider}]", "delay = [0, 0]"]
        if provider in budgets:
            lines.append(f"budget = {budgets[provider]}")
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "tabarr.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(tmp_path, *args, **config):
    return CliRunner().invoke(build_app(), ["--config", str(write_config(tmp_path, **config)), *args])


def open_db(tmp_path):
    return db.connect(tmp_path / "state" / "tabarr.sqlite")


def hit_record() -> dict:
    return json.loads((LRCLIB_FIXTURES / "get_hit.json").read_text(encoding="utf-8"))


def seed(tmp_path, *songs: tuple[str, str]) -> list[int]:
    conn = open_db(tmp_path)
    try:
        return [
            add_song(conn, artist, title, added_at=f"2026-10-{i + 1:02}T00:00:00Z").id
            for i, (artist, title) in enumerate(songs)
        ]
    finally:
        conn.close()


def song(tmp_path, song_id):
    conn = open_db(tmp_path)
    try:
        return get_song(conn, song_id)
    finally:
        conn.close()


# --- tabarr lyrics ---------------------------------------------------------------------


def test_lyrics_looks_up_pending_songs_and_reports_the_counts(tmp_path, sites):
    sites.lrclib.records.append(hit_record())
    found, missing = seed(tmp_path, ("Soda Stereo", "De Música Ligera"), ("Soda Stereo", "Canción Inexistente"))
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "Lyrics: 1 found, 1 missing, 0 instrumental, 0 errors" in result.stdout
    assert song(tmp_path, found).lyrics_status == "found"
    assert song(tmp_path, missing).lyrics_status == "missing"
    assert (tmp_path / "lib" / "Soda Stereo" / "De Música Ligera" / "lyrics.txt").is_file()
    conn = open_db(tmp_path)
    try:  # every request is in the event log, as in the nightly run
        logged = conn.execute("SELECT COUNT(*) FROM events WHERE provider = 'lrclib'").fetchone()[0]
    finally:
        conn.close()
    assert logged == len(sites.lrclib.requests) == 3


def test_lyrics_with_nothing_to_look_up(tmp_path, sites):
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "No song is waiting for lyrics." in result.stdout
    assert sites.lrclib.requests == []


def test_lyrics_errors_leave_songs_pending_and_say_so(tmp_path, sites):
    sites.lrclib.status = 500
    (song_id,) = seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "0 found, 0 missing, 0 instrumental, 1 error" in result.stdout
    assert "pending" in result.stdout
    assert song(tmp_path, song_id).lyrics_status == "pending"


def test_lyrics_spent_budget_is_no_failure(tmp_path, sites):
    sites.lrclib.records.append(hit_record())
    older, newer = seed(tmp_path, ("Soda Stereo", "Persiana Americana"), ("Soda Stereo", "De Música Ligera"))
    result = run(tmp_path, "lyrics", budgets={"lrclib": 1})
    assert result.exit_code == 0, result.output
    assert "Lyrics: 1 found, 0 missing, 0 instrumental, 0 errors" in result.stdout
    assert "budget of 1 request" in result.stdout and "next run" in result.stdout
    assert (song(tmp_path, newer).lyrics_status, song(tmp_path, older).lyrics_status) == ("found", "pending")


def test_lyrics_block_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    sites.lrclib.status = 429
    (song_id,) = seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    result = run(tmp_path, "lyrics", ntfy=True)
    assert result.exit_code == 1
    assert "LRCLIB blocked tabarr" in result.stderr
    assert "Nothing was marked missing" in result.stderr
    assert song(tmp_path, song_id).lyrics_status == "pending"
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "lrclib", datetime.now(UTC))
        assert get_state(conn, "lrclib").strikes == 1
    finally:
        conn.close()
    (alert,) = sites.ntfy.posts
    assert alert.headers["Title"] == "tabarr: lrclib blocked"
    assert alert.headers["Priority"] == "high"


def test_lyrics_asks_nothing_while_lrclib_cools_down(tmp_path, sites):
    seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    conn = open_db(tmp_path)
    try:
        record_block(conn, "lrclib", datetime.now(UTC), "lrclib: 429: HTTP 429")
    finally:
        conn.close()
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 1
    assert "LRCLIB is cooling down" in result.stderr
    assert sites.lrclib.requests == []


def test_a_pass_that_went_well_clears_old_strikes(tmp_path, sites):
    # As after a nightly run: the cooldown is over and LRCLIB answered.
    sites.lrclib.records.append(hit_record())
    seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    conn = open_db(tmp_path)
    try:
        record_block(conn, "lrclib", datetime.now(UTC) - timedelta(days=2), "lrclib: 429: HTTP 429")
    finally:
        conn.close()
    assert run(tmp_path, "lyrics").exit_code == 0
    conn = open_db(tmp_path)
    try:
        assert get_state(conn, "lrclib").strikes == 0
    finally:
        conn.close()


# --- tabarr lacuerda -------------------------------------------------------------------


def spanish_song(tmp_path, title="De Música Ligera") -> int:
    (song_id,) = seed(tmp_path, ("Soda Stereo", title))
    lyrics = Lyrics(plain=SHEET_LYRICS, synced=None, instrumental=False, duration=None, lrclib_id=None)
    conn = open_db(tmp_path)
    try:
        update_song(conn, song_id, lyrics_status="found", lyrics_json=lyrics.to_json())
    finally:
        conn.close()
    return song_id


def soda_pages() -> dict[str, str]:
    return {
        SODA: (LACUERDA_FIXTURES / "artist.html").read_text(encoding="utf-8"),
        DML_3: (LACUERDA_FIXTURES / "version.html").read_text(encoding="utf-8"),
    }


def test_lacuerda_keeps_a_sheet_and_reports_the_counts(tmp_path, sites):
    sites.lacuerda.pages.update(soda_pages())
    kept = spanish_song(tmp_path)
    spanish_song(tmp_path, "Canción Inexistente")
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert "LaCuerda: 2 tried, 1 sheet kept, 1 missing, 0 errors" in result.stdout
    assert song(tmp_path, kept).status == "found"
    assert (tmp_path / "lib" / "Soda Stereo" / "De Música Ligera" / "sheet.txt").is_file()


def test_lacuerda_follows_overrides(tmp_path, sites):
    # Ignored in overrides.toml, though no match has run since.
    sites.lacuerda.pages.update(soda_pages())
    spanish_song(tmp_path)
    overrides = tmp_path / "lib" / "overrides.toml"
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text('[ignore]\nsongs = ["Soda Stereo - De Música Ligera"]\n', encoding="utf-8")
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert "No song to try on LaCuerda." in result.stdout
    assert sites.lacuerda.requests == []


def test_lacuerda_with_nothing_to_try(tmp_path, sites):
    seed(tmp_path, ("Radiohead", "Creep"))
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert "No song to try on LaCuerda." in result.stdout
    assert sites.lacuerda.requests == []


def test_lacuerda_block_starts_a_cooldown(tmp_path, sites):
    sites.lacuerda.status = 403
    song_id = spanish_song(tmp_path)
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 1
    assert "LaCuerda blocked tabarr" in result.stderr
    assert song(tmp_path, song_id).lacuerda_checked_at is None
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "lacuerda", datetime.now(UTC))
    finally:
        conn.close()


def test_lacuerda_spent_budget_is_no_failure(tmp_path, sites):
    sites.lacuerda.pages.update(soda_pages())
    song_id = spanish_song(tmp_path)
    result = run(tmp_path, "lacuerda", budgets={"lacuerda": 1})
    assert result.exit_code == 0, result.output
    assert "budget of 1 request" in result.stdout and "next run" in result.stdout
    assert song(tmp_path, song_id).lacuerda_checked_at is None


# --- start-up ------------------------------------------------------------------------------


def test_registering_the_commands_imports_neither_pass(tmp_path):
    # Every command module is imported on every start; the passes wait for their command.
    src = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys, typer\n"
        "from tabarr.commands import lyrics\n"
        "lyrics.register(typer.Typer())\n"
        "print([m for m in ('tabarr.lyrics', 'tabarr.lacuerda', 'tabarr.lacuerda_fetch') if m in sys.modules])\n"
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(src)}
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]"
