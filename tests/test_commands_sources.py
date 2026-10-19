"""``tabarr add``, ``tabarr sync`` and ``tabarr auth spotify``, run through the CLI.

Each test writes a tabarr.toml rooted in tmp_path. Spotify is faked by replacing
``tabarr.spotify.client_from_config`` (or the token session of a real OAuth
manager), and no request can reach the network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests
from spotipy.exceptions import SpotifyException
from typer.testing import CliRunner

from tabarr import db
from tabarr.cli import build_app
from tabarr.songs import list_songs
from tabarr.wanted import HEADER
from conftest import subprocess_pythonpath

# Environment that load_config or spotipy would read; none of it may leak into a test.
OUTSIDE_SETTINGS = (
    "CREDENTIALS_DIRECTORY",
    "TABARR_CONFIG",
    "TABARR_SPOTIFY_CLIENT_SECRET",
    "TABARR_NTFY_TOKEN",
    "SPOTIPY_CLIENT_ID",
    "SPOTIPY_CLIENT_SECRET",
    "SPOTIPY_REDIRECT_URI",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)

    def refuse(*args, **kwargs):
        pytest.fail("tried to reach the network")

    monkeypatch.setattr(requests.Session, "request", refuse)


def write_config(tmp_path, extra=""):
    path = tmp_path / "tabarr.toml"
    path.write_text(
        f'library_dir = "{tmp_path / "lib"}"\n'
        f'music_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        f'cache_dir = "{tmp_path / "cache"}"\n' + extra,
        encoding="utf-8",
    )
    return path


def run(tmp_path, *args, config="", input=None):
    path = write_config(tmp_path, config)
    return CliRunner().invoke(build_app(), ["--config", str(path), *args], input=input)


def wanted_file(tmp_path, text=None):
    path = tmp_path / "lib" / "wanted.txt"
    if text is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return path


def songs(tmp_path):
    conn = db.connect(tmp_path / "state" / "tabarr.sqlite")
    try:
        return list_songs(conn)
    finally:
        conn.close()


def spotify_config(tmp_path, *, secret=True):
    """A [spotify] table for tabarr.toml; the client secret sits in a file next to it."""
    if not secret:
        return '[spotify]\nclient_id = "cid"\n'
    (tmp_path / "spotify_secret").write_text("secret\n", encoding="utf-8")
    return '[spotify]\nclient_id = "cid"\nclient_secret_file = "spotify_secret"\n'


class OneTrackSpotify:
    """A Spotify account with one liked track, no playlists and no top tracks."""

    def __init__(self, error=None):
        self.error = error

    def current_user_saved_tracks(self, limit=20, offset=0, market=None):
        if self.error:
            raise self.error
        creep = {
            "type": "track",
            "id": "tCreep",
            "name": "Creep",
            "artists": [{"name": "Radiohead"}],
            "album": {"name": "Pablo Honey"},
            "duration_ms": 238000,
        }
        return {"items": [{"added_at": "2026-10-01T12:00:00Z", "track": creep}], "next": None}

    def current_user_playlists(self, limit=50, offset=0):
        return {"items": [], "next": None}

    def playlist_items(self, playlist_id, **kwargs):
        raise SpotifyException(404, -1, "x:\n Not found")

    def current_user_top_tracks(self, limit=20, offset=0, time_range="medium_term"):
        return {"items": [], "next": None}

    def next(self, result):
        return None


def fake_spotify(monkeypatch, client):
    """Make ``client_from_config`` return ``client`` (or raise it); returns a list of its calls."""
    calls = []

    def client_from_config(cfg):
        calls.append(cfg)
        if isinstance(client, BaseException):
            raise client
        return client

    monkeypatch.setattr("tabarr.spotify.client_from_config", client_from_config)
    return calls


# --- tabarr add -----------------------------------------------------------------------------


def test_add_creates_wanted_txt_and_the_song(tmp_path):
    result = run(tmp_path, "add", "Soda Stereo", "De Música Ligera", "--duration", "213")
    assert result.exit_code == 0, result.output
    path = wanted_file(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(HEADER)
    assert text.endswith("\nSoda Stereo - De Música Ligera | 3:33\n")
    assert f"Added to {path}, line {text.count(chr(10))}:" in result.output
    assert "\n  Soda Stereo - De Música Ligera | 3:33\n" in result.output
    assert "Song soda-stereo/de-musica-ligera: new" in result.output
    [song] = songs(tmp_path)
    assert (song.key, song.duration_ms, song.source_ids) == (
        "soda-stereo/de-musica-ligera",
        213000,
        {"wanted": ["soda-stereo/de-musica-ligera"]},
    )


def test_add_a_chinese_song_with_album_and_duration(tmp_path):
    result = run(tmp_path, "add", "宋冬野", "斑马斑马", "--album", "安和桥北", "--duration", "4:13")
    assert result.exit_code == 0, result.output
    text = wanted_file(tmp_path).read_text(encoding="utf-8")
    assert text.endswith("\n宋冬野 - 斑马斑马 | 安和桥北 | 4:13\n")
    assert "\n  宋冬野 - 斑马斑马 | 安和桥北 | 4:13\n" in result.output
    assert "Song 宋冬野/斑马斑马: new" in result.output
    [song] = songs(tmp_path)
    assert (song.artist, song.title, song.album, song.duration_ms) == (
        "宋冬野",
        "斑马斑马",
        "安和桥北",
        253000,
    )


def test_add_appends_to_the_file_and_syncs_all_of_it(tmp_path):
    path = wanted_file(tmp_path, "# mine\nSoda Stereo - De Música Ligera\n")
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert path.read_text(encoding="utf-8") == (
        "# mine\nSoda Stereo - De Música Ligera\nRadiohead - Creep\n"
    )
    assert f"Added to {path}, line 3:" in result.output
    assert {s.key for s in songs(tmp_path)} == {"soda-stereo/de-musica-ligera", "radiohead/creep"}


def test_add_a_song_already_listed_leaves_the_file_alone(tmp_path):
    path = wanted_file(tmp_path, "Oasis - Wonderwall\n宋冬野 - 斑马，斑马 | 安和桥北\n")
    before = path.read_bytes()
    result = run(tmp_path, "add", "宋冬野", "斑马斑马", "--duration", "4:13")
    assert result.exit_code == 0, result.output
    assert path.read_bytes() == before
    assert f"Already in {path}, line 2:" in result.output
    assert "\n  宋冬野 - 斑马，斑马 | 安和桥北\n" in result.output
    # The duration given isn't on that line, and wasn't written: say how to change it.
    assert "edit" in result.output
    assert "Song 宋冬野/斑马斑马: new" in result.output  # listed, but never synced until now
    assert {s.key: s.album for s in songs(tmp_path)}["宋冬野/斑马斑马"] == "安和桥北"


def test_add_twice_says_the_song_is_listed_and_known(tmp_path):
    first = run(tmp_path, "add", "Radiohead", "Creep", "--album", "Pablo Honey")
    assert first.exit_code == 0, first.output
    again = run(tmp_path, "add", "radiohead", "CREEP")
    assert again.exit_code == 0, again.output
    assert "Already in" in again.output
    assert "Song radiohead/creep: already known, no sheet yet" in again.output
    assert "edit" not in again.output  # nothing was given that the line lacks
    assert wanted_file(tmp_path).read_text(encoding="utf-8").count("Creep") == 1


def test_add_mentions_lines_of_wanted_txt_it_cannot_read(tmp_path):
    wanted_file(tmp_path, "not a song line\n")
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert "wanted.txt line 1: expected 'Artist - Title'" in result.output


@pytest.mark.parametrize("duration", ["4:75", "0:00", "4.13", "four minutes"])
def test_add_with_a_bad_duration_is_a_clean_error(tmp_path, duration):
    result = run(tmp_path, "add", "Radiohead", "Creep", "--duration", duration)
    assert result.exit_code == 2, result.output
    assert "--duration: " in result.output and repr(duration) in result.output
    assert not wanted_file(tmp_path).exists()


def test_add_refuses_a_song_wanted_txt_cannot_hold(tmp_path):
    result = run(tmp_path, "add", "Sergio Mendes - Brasil '66", "Mas Que Nada")
    assert result.exit_code == 2, result.output
    assert "Sergio Mendes" in result.output
    assert not wanted_file(tmp_path).exists()


def test_add_says_when_wanted_txt_cannot_be_written(tmp_path):
    wanted_file(tmp_path).mkdir(parents=True)  # a folder where the file should be
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 1, result.output
    assert f"can't update {wanted_file(tmp_path)}" in result.output


def test_add_keeps_the_line_when_the_database_is_out_of_reach(tmp_path):
    (tmp_path / "state").write_text("a file where the state folder should be", encoding="utf-8")
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert wanted_file(tmp_path).read_text(encoding="utf-8").endswith("\nRadiohead - Creep\n")
    assert "Added to" in result.output
    assert "`tabarr sync`" in result.output  # the next sync adds it to the database


# --- tabarr sync ----------------------------------------------------------------------------

TWO_SONGS_AND_A_TYPO = (
    "宋冬野 - 斑马斑马 | 安和桥北 | 4:13\nnot a song line\nSoda Stereo - De Música Ligera\n"
)


def test_sync_without_spotify_reads_wanted_txt(tmp_path, monkeypatch):
    clients_made = fake_spotify(monkeypatch, OneTrackSpotify())
    wanted_file(tmp_path, TWO_SONGS_AND_A_TYPO)
    result = run(tmp_path, "sync")
    assert result.exit_code == 0, result.output
    assert "wanted.txt 2 songs, 2 new, 1 problem; Spotify off\n" in result.output
    assert "wanted.txt line 2: expected 'Artist - Title'" in result.output
    assert {s.key for s in songs(tmp_path)} == {"宋冬野/斑马斑马", "soda-stereo/de-musica-ligera"}
    assert clients_made == []  # Spotify is off: no client is even made


def test_sync_with_nothing_to_read_says_how_to_start(tmp_path):
    result = run(tmp_path, "sync")
    assert result.exit_code == 0, result.output
    assert "wanted.txt 0 songs, 0 new; Spotify off" in result.output
    assert str(wanted_file(tmp_path)) in result.output and "`tabarr add" in result.output


def test_sync_with_spotify(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, OneTrackSpotify())
    wanted_file(tmp_path, "宋冬野 - 斑马斑马 | 安和桥北 | 4:13\n")
    result = run(tmp_path, "sync", config=spotify_config(tmp_path))
    assert result.exit_code == 0, result.output
    assert "wanted.txt 1 song, 1 new; Spotify 1 song, 1 new\n" in result.output
    by_key = {s.key: s for s in songs(tmp_path)}
    assert set(by_key) == {"宋冬野/斑马斑马", "radiohead/creep"}
    assert by_key["radiohead/creep"].source_ids == {"spotify": ["tCreep"]}


def test_sync_when_spotify_needs_authorization(tmp_path):
    # Spotify is set up but never authorized: the real client_from_config finds no token.
    wanted_file(tmp_path, TWO_SONGS_AND_A_TYPO)
    result = run(tmp_path, "sync", config=spotify_config(tmp_path))
    assert result.exit_code == 0, result.output
    assert "Spotify needs authorization (run `tabarr auth spotify`)" in result.output
    token = tmp_path / "state" / "spotify_token.json"
    assert f"Spotify: No Spotify authorization is saved yet (no token in {token})." in result.output
    assert len(songs(tmp_path)) == 2  # wanted.txt synced all the same


def test_sync_says_once_that_the_client_secret_is_missing(tmp_path):
    token = tmp_path / "state" / "spotify_token.json"
    token.parent.mkdir(parents=True)
    token.write_text('{"access_token": "AT", "refresh_token": "RT", "expires_at": 4102444800}')
    result = run(tmp_path, "sync", config=spotify_config(tmp_path, secret=False))
    assert result.exit_code == 0, result.output
    assert result.output.count("client secret is missing") == 1


def test_sync_when_spotify_fails(tmp_path, monkeypatch):
    outage = SpotifyException(502, -1, "https://api.spotify.com/v1/me/tracks:\n Bad gateway")
    fake_spotify(monkeypatch, OneTrackSpotify(error=outage))
    wanted_file(tmp_path, TWO_SONGS_AND_A_TYPO)
    result = run(tmp_path, "sync", config=spotify_config(tmp_path))
    assert result.exit_code == 0, result.output
    assert "Spotify 0 songs, 0 new (Spotify Liked Songs: HTTP 502: Bad gateway)" in result.output
    assert len(songs(tmp_path)) == 2


def test_sync_when_the_spotify_client_cannot_be_made(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, RuntimeError("the token cache is unreadable"))
    wanted_file(tmp_path, TWO_SONGS_AND_A_TYPO)
    result = run(tmp_path, "sync", config=spotify_config(tmp_path))
    assert result.exit_code == 0, result.output
    assert "Spotify unavailable: RuntimeError: the token cache is unreadable" in result.output
    assert len(songs(tmp_path)) == 2


# --- tabarr auth spotify --------------------------------------------------------------------

REDIRECT = "http://127.0.0.1:8888/callback"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeTokenSession:
    """Stands in for the session a real SpotifyOAuth posts the code exchange with."""

    def __init__(self, error=None):
        self.error = error
        self.posts = []

    def post(self, url, data=None, headers=None, **kwargs):
        self.posts.append((url, data))
        if self.error:
            raise self.error
        token = {
            "access_token": "AT",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "RT",
            "scope": "user-library-read playlist-read-private",
        }
        return FakeResponse(token)


def token_session(monkeypatch, session):
    """Have the real OAuth manager that ``make_auth`` builds post through ``session``."""
    import tabarr.spotify

    real = tabarr.spotify.make_auth

    def make_auth(cfg, state_dir):
        auth = real(cfg, state_dir)
        auth._session = session
        return auth

    monkeypatch.setattr(tabarr.spotify, "make_auth", make_auth)


def test_auth_spotify_without_a_client_id_says_how_to_set_it_up(tmp_path, monkeypatch):
    monkeypatch.setattr("tabarr.spotify.make_auth", lambda *a: pytest.fail("Spotify is off"))
    result = run(tmp_path, "auth", "spotify")
    assert result.exit_code == 1, result.output
    out = result.output
    assert "optional" in out and "wanted.txt" in out
    assert "developer.spotify.com" in out and REDIRECT in out
    assert str(tmp_path / "tabarr.toml") in out
    assert "[spotify]" in out and 'client_id = "' in out
    assert "spotify_client_secret" in out


def test_auth_spotify_saves_the_token_and_says_where(tmp_path, monkeypatch):
    session = FakeTokenSession()
    token_session(monkeypatch, session)
    result = run(
        tmp_path,
        "auth",
        "spotify",
        config=spotify_config(tmp_path),
        input=f"{REDIRECT}?code=AQDcode-123\n",
    )
    assert result.exit_code == 0, result.output
    assert "https://accounts.spotify.com/authorize?" in result.output
    assert "Address: " in result.output and "Address: :" not in result.output
    [(url, data)] = session.posts
    assert url == "https://accounts.spotify.com/api/token" and data["code"] == "AQDcode-123"
    token = tmp_path / "state" / "spotify_token.json"
    assert '"refresh_token": "RT"' in token.read_text(encoding="utf-8")
    assert f"the token is in {token}" in result.output
    assert "`tabarr sync`" in result.output


def test_auth_spotify_refused_in_the_browser_exits_1(tmp_path, monkeypatch):
    session = FakeTokenSession()
    token_session(monkeypatch, session)
    result = run(
        tmp_path,
        "auth",
        "spotify",
        config=spotify_config(tmp_path),
        input=f"{REDIRECT}?error=access_denied\n",
    )
    assert result.exit_code == 1, result.output
    assert "access was refused in the browser (access_denied)" in result.output
    assert "Run `tabarr auth spotify`" not in result.output  # that's what was just run
    assert session.posts == []
    assert not (tmp_path / "state" / "spotify_token.json").exists()


def test_auth_spotify_without_the_client_secret_exits_1(tmp_path):
    result = run(tmp_path, "auth", "spotify", config=spotify_config(tmp_path, secret=False))
    assert result.exit_code == 1, result.output
    assert "client secret is missing" in result.output


def test_auth_spotify_when_spotify_cannot_be_reached_exits_1(tmp_path, monkeypatch):
    token_session(monkeypatch, FakeTokenSession(error=requests.ConnectionError("no route")))
    result = run(
        tmp_path,
        "auth",
        "spotify",
        config=spotify_config(tmp_path),
        input=f"{REDIRECT}?code=AQDcode\n",
    )
    assert result.exit_code == 1, result.output
    assert "couldn't reach accounts.spotify.com" in result.output


# --- the module -----------------------------------------------------------------------------


def test_registering_the_commands_imports_no_spotipy(tmp_path):
    # Every command module is imported on every start, so spotipy waits for a command.
    src = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys, typer\n"
        "from tabarr.commands import sources\n"
        "sources.register(typer.Typer())\n"
        "print([m for m in ('spotipy', 'tabarr.spotify') if m in sys.modules])\n"
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]"
