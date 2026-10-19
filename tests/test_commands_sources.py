"""``tabarr add``, ``tabarr sync`` and ``tabarr auth spotify``, run through the CLI.

Each test writes a tabarr.toml rooted in tmp_path. Spotify is faked by replacing
``tabarr.spotify.client_from_config`` (or the token session of a real OAuth
manager), and no request can reach the network.
"""

from __future__ import annotations

import pytest
import requests
from typer.testing import CliRunner

from tabarr import db
from tabarr.cli import build_app
from tabarr.songs import list_songs
from tabarr.wanted import HEADER

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
