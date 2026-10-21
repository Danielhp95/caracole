"""``caracole add``, ``caracole sync`` and ``caracole auth spotify``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path. Spotify is faked by replacing
``caracole.spotify.client_from_config`` (or the token session of a real OAuth
manager), and no request can reach the network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests
from spotipy.exceptions import SpotifyException
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.songs import list_songs
from caracole.wanted import HEADER
from conftest import subprocess_pythonpath

# Environment that load_config or spotipy would read; none of it may leak into a test.
OUTSIDE_SETTINGS = (
    "CREDENTIALS_DIRECTORY",
    "CARACOLE_CONFIG",
    "CARACOLE_SPOTIFY_CLIENT_SECRET",
    "CARACOLE_NTFY_TOKEN",
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
    path = tmp_path / "caracole.toml"
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
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        return list_songs(conn)
    finally:
        conn.close()


def spotify_config(tmp_path, *, secret=True):
    """A [spotify] table for caracole.toml; the client secret sits in a file next to it."""
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

    monkeypatch.setattr("caracole.spotify.client_from_config", client_from_config)
    return calls


# --- caracole add -----------------------------------------------------------------------------

# What add says after its line while the offline index is empty (match_lines).
EMPTY_INDEX = ("The offline index is empty: run `caracole index build` once (about 10 minutes), and the song can "
               "be matched.\n")


def test_add_creates_wanted_txt_and_the_song(tmp_path):
    result = run(tmp_path, "add", "Soda Stereo", "De Música Ligera", "--duration", "213")
    assert result.exit_code == 0, result.output
    path = wanted_file(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(HEADER)
    assert text.endswith("\nSoda Stereo - De Música Ligera | 3:33\n")
    # One line says it all, then what the offline index says; -v says where, and the song's key.
    assert result.output == (
        "Added Soda Stereo - De Música Ligera to wanted.txt; the next `caracole run` looks for it.\n" + EMPTY_INDEX)
    (tmp_path / "v").mkdir()
    verbose = run(tmp_path / "v", "-v", "add", "Soda Stereo", "De Música Ligera", "--duration", "213")
    vpath = wanted_file(tmp_path / "v")
    assert f"wanted.txt line {text.count(chr(10))} ({vpath}): Soda Stereo - De Música Ligera | 3:33" in verbose.output
    assert "Song soda-stereo/de-musica-ligera: new" in verbose.output
    [song] = songs(tmp_path)
    assert (song.key, song.duration_ms, song.source_ids) == (
        "soda-stereo/de-musica-ligera",
        213000,
        {"wanted": ["soda-stereo/de-musica-ligera"]},
    )


def test_add_with_lacuerda_records_the_sheet_you_picked_there_for_tonights_run(tmp_path):
    from caracole.overrides import LaCuerdaPick, load_overrides

    url = "https://acordes.lacuerda.net/estopa/como_camaron-2.shtml"
    result = run(tmp_path, "add", "--lacuerda", url, "Estopa", "Como Camarón")
    assert result.exit_code == 0, result.output
    assert wanted_file(tmp_path).read_text(encoding="utf-8").endswith("\nEstopa - Como Camarón\n")
    assert load_overrides(tmp_path / "lib" / "overrides.toml").lacuerda == {
        "estopa/como-camaron": LaCuerdaPick("estopa", "como_camaron", 2)}
    assert "LaCuerda: the nightly run keeps the sheet you picked there" in result.output
    [song] = songs(tmp_path)
    assert song.lacuerda_checked_at is None
    bad = run(tmp_path, "add", "--lacuerda", "https://acordes.lacuerda.net/estopa/", "Estopa", "Tu Calorro")
    assert bad.exit_code == 2 and "--lacuerda" in bad.output
    assert "Tu Calorro" not in wanted_file(tmp_path).read_text(encoding="utf-8")


def test_add_with_lacuerda_writes_no_pick_without_caracoles_lock(tmp_path):
    # overrides.toml is in the library, which only a caracole holding the lock writes: with a lock file that
    # can't be opened (its folder is a file), the line is in wanted.txt, but the pick isn't written unlocked.
    (tmp_path / "state").write_text("not a folder", encoding="utf-8")
    url = "https://acordes.lacuerda.net/estopa/como_camaron"
    result = run(tmp_path, "add", "--lacuerda", url, "Estopa", "Como Camarón")
    assert result.exit_code == 1, result.output
    assert "Estopa - Como Camarón" in wanted_file(tmp_path).read_text(encoding="utf-8")
    assert "caracole's lock" in result.output and "caracole.lock" in result.output
    assert not (tmp_path / "lib" / "overrides.toml").exists()


def test_add_a_chinese_song_with_album_and_duration(tmp_path):
    result = run(tmp_path, "add", "宋冬野", "斑马斑马", "--album", "安和桥北", "--duration", "4:13")
    assert result.exit_code == 0, result.output
    text = wanted_file(tmp_path).read_text(encoding="utf-8")
    assert text.endswith("\n宋冬野 - 斑马斑马 | 安和桥北 | 4:13\n")
    assert result.output == (
        "Added 宋冬野 - 斑马斑马 to wanted.txt; the next `caracole run` looks for it.\n" + EMPTY_INDEX)
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
    assert result.output.startswith("Added Radiohead - Creep to wanted.txt")
    assert {s.key for s in songs(tmp_path)} == {"soda-stereo/de-musica-ligera", "radiohead/creep"}


def test_add_a_song_already_listed_leaves_the_file_alone(tmp_path):
    path = wanted_file(tmp_path, "Oasis - Wonderwall\n宋冬野 - 斑马，斑马 | 安和桥北\n")
    before = path.read_bytes()
    result = run(tmp_path, "-v", "add", "宋冬野", "斑马斑马", "--duration", "4:13")
    assert result.exit_code == 0, result.output
    assert path.read_bytes() == before
    # Listed, but never synced until now.
    assert "宋冬野 - 斑马，斑马 is in wanted.txt already; the next `caracole run` looks for it.\n" in result.output
    # The duration given isn't on that line, and wasn't written: say how to change it.
    assert "Its line stays as it is: edit it to change the album or the duration.\n" in result.output
    assert f"wanted.txt line 2 ({path}): 宋冬野 - 斑马，斑马 | 安和桥北" in result.output  # at -v
    assert {s.key: s.album for s in songs(tmp_path)}["宋冬野/斑马斑马"] == "安和桥北"


def test_add_twice_says_the_song_is_listed_and_known(tmp_path):
    first = run(tmp_path, "add", "Radiohead", "Creep", "--album", "Pablo Honey")
    assert first.exit_code == 0, first.output
    again = run(tmp_path, "add", "radiohead", "CREEP")
    assert again.exit_code == 0, again.output
    assert again.output == (
        "Radiohead - Creep is in wanted.txt already; the library has it, with no sheet yet.\n" + EMPTY_INDEX)
    assert "edit" not in again.output  # nothing was given that the line lacks
    assert wanted_file(tmp_path).read_text(encoding="utf-8").count("Creep") == 1


def test_add_says_what_the_library_has_of_a_song_it_knew(tmp_path):
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    from caracole.songs import update_song
    from conftest import add_song as insert

    creep = insert(conn, "Radiohead", "Creep", source="spotify")
    update_song(conn, creep.id, status="found")
    conn.close()
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert result.output == "Added Radiohead - Creep to wanted.txt; the library has it, with a sheet.\n" + EMPTY_INDEX


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
    assert "Added Radiohead - Creep to wanted.txt" in result.output
    assert "`caracole sync`" in result.output  # the next sync adds it to the database


def test_add_and_search_add_go_through_one_add_path(tmp_path, monkeypatch):
    from caracole.commands import sources

    real = sources.add_song
    calls = []

    def add_song(cfg, artist, title, album=None, duration_ms=None, **kwargs):
        calls.append((artist, title, album, duration_ms))
        return real(cfg, artist, title, album, duration_ms, **kwargs)

    monkeypatch.setattr(sources, "add_song", add_song)
    added = run(
        tmp_path, "add", "Radiohead", "Creep", "--album", "Pablo Honey", "--duration", "3:58"
    )
    assert added.exit_code == 0, added.output
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    conn.execute(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (5001, 'stone-temple-pilots', 'creep', 'chords', '1', 'x', ?)",
        ("stone-temple-pilots/creep-chords-5001",),
    )
    conn.close()
    found = run(tmp_path, "search", "stone temple pilots creep", "--add", "1")
    assert found.exit_code == 0, found.output
    assert calls == [
        ("Radiohead", "Creep", "Pablo Honey", 238000),
        ("Stone Temple Pilots", "Creep", None, None),
    ]
    assert wanted_file(tmp_path).read_text(encoding="utf-8").endswith(
        "\nRadiohead - Creep | Pablo Honey | 3:58\nStone Temple Pilots - Creep\n"
    )
    assert {s.key for s in songs(tmp_path)} == {"radiohead/creep", "stone-temple-pilots/creep"}


EPIC = (4742072, "misc-musicals", "epic-the-musical-not-sorry-for-loving-you", "chords")


def ug_index(tmp_path, *rows, built=True):
    """Index rows (tab_id, artist_key, song_key, type) in the state folder's database; ``built=False``
    leaves the index partial, as a build stopped part-way does."""
    from caracole.ug.index import mark_built

    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        conn.executemany(
            "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
            "VALUES (?, ?, ?, ?, '1', 'x', ?)",
            [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows],
        )
        if built:
            mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))
    finally:
        conn.close()


def test_add_says_at_once_which_ug_songs_a_name_not_quite_ugs_may_be(tmp_path):
    # The owner's example: UG files EPIC: The Musical under misc-musicals, the show's name in each title.
    ug_index(tmp_path, EPIC, (11, "bill-fox", "im-not-over-loving-you", "chords"))
    result = run(tmp_path, "add", "epic", "I'm not sorry for loving you")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Did you mean" in out
    lines = out[out.index("Did you mean"):].splitlines()
    assert lines[1] == ("  1) 94  misc-musicals/epic-the-musical-not-sorry-for-loving-you (catch_all)  "
                        "https://tabs.ultimate-guitar.com/tab/misc-musicals/"
                        "epic-the-musical-not-sorry-for-loving-you-chords-4742072")
    assert lines[2].startswith("  2) 82  bill-fox/im-not-over-loving-you (title_only)  https://")
    assert "`caracole review`" in out
    # Saved as the nightly match step would save it: a review, there for `caracole review` and the to-do page now.
    [song] = songs(tmp_path)
    assert (song.match_decision, song.review, song.match_artist_key) == ("review", True, "misc-musicals")
    todo = (tmp_path / "lib" / "_todo.md").read_text(encoding="utf-8")
    assert "### epic - I'm not sorry for loving you" in todo.split("## Review (1)", 1)[1]


def test_add_says_its_one_line_then_what_the_offline_index_says(tmp_path):
    ug_index(tmp_path, (4169, "radiohead", "creep", "chords"))
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert result.output == ("Added Radiohead - Creep to wanted.txt; the next `caracole run` looks for it.\n"
                             "On Ultimate Guitar: radiohead/creep (exact)\n")
    again = run(tmp_path, "-v", "add", "Radiohead", "Creep")
    lines = again.output.splitlines()
    said = lines.index("Radiohead - Creep is in wanted.txt already; the library has it, with no sheet yet.")
    assert "On Ultimate Guitar: radiohead/creep (exact)" in lines[said + 1:]  # after it, -v or not
    assert "Song radiohead/creep: already known, wanted" in again.output


def test_add_says_which_ug_song_it_matched(tmp_path):
    ug_index(tmp_path, (4169, "radiohead", "creep", "chords"), (4170, "radiohead", "karma-police", "chords"))
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert "On Ultimate Guitar: radiohead/creep (exact)" in result.output
    assert "Did you mean" not in result.output
    [song] = songs(tmp_path)
    assert (song.match_decision, song.match_song_key, song.ug_dirty) == ("accept", "creep", True)


def test_add_of_a_song_the_index_lacks_says_so_and_how_to_look_wider(tmp_path):
    ug_index(tmp_path, (4169, "radiohead", "creep", "chords"))
    result = run(tmp_path, "add", "Soda Stereo", "Persiana Americana")
    assert result.exit_code == 0, result.output
    assert "Not in the offline Ultimate Guitar index under this name" in result.output
    assert "`caracole search`" in result.output
    [song] = songs(tmp_path)
    assert song.match_decision == "not_found"


WONDERWALL = ((6125, "oasis", "wonderwall", "chords"), (6126, "oasis", "wonderwall", "tabs"),
              (7001, "oasis", "live-forever", "chords"), (2426561, "ryan-adams", "wonderwall", "chords"))


def test_add_with_one_name_writes_nothing_and_offers_the_songs_of_that_title(tmp_path):
    ug_index(tmp_path, *WONDERWALL)
    result = run(tmp_path, "add", "Wonderwall")
    assert result.exit_code == 2, result.output
    assert not wanted_file(tmp_path).exists() and songs(tmp_path) == []
    out = result.output
    assert "  1. [UG] Oasis - Wonderwall · chords×1 tabs×1\n" in out
    assert '     caracole add "Oasis" "Wonderwall"\n' in out and '     caracole add "Ryan Adams" "Wonderwall"\n' in out
    assert 'Or add one by its number: caracole search "Wonderwall" --add N' in out
    assert '"Wonderwall" is one name' in out and "nothing was added" in out
    assert 'name its artist too: caracole add ARTIST "Wonderwall".' in out
    assert run(tmp_path, "search", "Wonderwall", "--add", "2").exit_code == 0  # the same numbers
    assert wanted_file(tmp_path).read_text(encoding="utf-8").endswith("\nRyan Adams - Wonderwall\n")


def test_add_with_an_artists_name_alone_offers_their_most_tabbed_songs(tmp_path):
    ug_index(tmp_path, *WONDERWALL)
    result = run(tmp_path, "add", "oasis")
    assert result.exit_code == 2, result.output
    assert "Oasis, an artist: 2 songs (3 tabs). The most tabbed:" in result.output
    assert 'caracole add "Oasis" "Live Forever"' in result.output
    assert 'give its title too: caracole add "oasis" TITLE.' in result.output  # an artist, so the title is missing
    assert not wanted_file(tmp_path).exists()


def test_add_with_one_name_and_no_index_says_what_it_takes(tmp_path):
    result = run(tmp_path, "add", "斑马")
    assert result.exit_code == 2, result.output
    assert '"斑马" is one name' in result.output and "caracole add ARTIST TITLE" in result.output
    assert not wanted_file(tmp_path).exists()


def test_add_with_one_text_holding_a_dash_adds_the_song(tmp_path):
    result = run(tmp_path, "add", "Radiohead - Creep")
    assert result.exit_code == 0, result.output
    assert wanted_file(tmp_path).read_text(encoding="utf-8").endswith("\nRadiohead - Creep\n")
    assert run(tmp_path, "add", " - Creep").exit_code == 2  # no artist
    blank = run(tmp_path, "add", "  ")
    assert blank.exit_code == 2 and "a song needs an artist and a title" in blank.output


@pytest.mark.parametrize("artist", ["misc", "Unknown", "Various Artists"])
def test_add_warns_when_the_artist_is_a_placeholder(tmp_path, artist):
    # The owner's wanted.txt has "misc - 斑马": no one's name, so nothing can be found by it.
    result = run(tmp_path, "add", artist, "斑马")
    assert result.exit_code == 0, result.output
    assert wanted_file(tmp_path).read_text(encoding="utf-8").endswith(f"\n{artist} - 斑马\n")  # still added
    out = " ".join(result.output.split())
    assert f'"{artist}" is no one\'s name' in out and 'caracole search "斑马"' in out
    assert "no one's name" not in run(tmp_path, "add", "Oasis", "Wonderwall").output


def test_add_matches_nothing_against_an_index_that_isnt_built(tmp_path):
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert "The offline index is empty: run `caracole index build` once" in result.output
    [song] = songs(tmp_path)
    assert song.match_decision is None


def test_add_records_no_miss_against_a_partial_index(tmp_path):
    # Errors are never misses: a song in the sitemaps not read yet isn't missing from UG.
    ug_index(tmp_path, (4169, "radiohead", "creep", "chords"), built=False)
    result = run(tmp_path, "add", "Soda Stereo", "Persiana Americana")
    assert result.exit_code == 0, result.output
    assert "incomplete" in result.output and "Not in the offline" not in result.output
    [song] = songs(tmp_path)
    assert song.match_decision is None
    found = run(tmp_path, "add", "Radiohead", "Creep")
    assert "On Ultimate Guitar: radiohead/creep (exact)" in found.output


def test_add_with_a_broken_overrides_file_matches_nothing(tmp_path):
    ug_index(tmp_path, (4169, "radiohead", "creep", "chords"))
    (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
    (tmp_path / "lib" / "overrides.toml").write_text("[match\n", encoding="utf-8")
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert "On Ultimate Guitar" not in result.output and "overrides" in result.output
    [song] = songs(tmp_path)
    assert song.match_decision is None


def test_search_add_says_which_ug_song_it_matched_too(tmp_path):
    ug_index(tmp_path, (5001, "stone-temple-pilots", "creep", "chords"))
    result = run(tmp_path, "search", "stone temple pilots creep", "--add", "1")
    assert result.exit_code == 0, result.output
    assert "On Ultimate Guitar: stone-temple-pilots/creep (exact)" in result.output


# --- caracole sync ----------------------------------------------------------------------------

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


OLD_LIVE_KEY = "soda-stereo/persiana-americana-en-vivo"  # before " - En Vivo" was a version suffix
SEPTEMBER = "2026-09-01T00:00:00Z"


def listed_since_september_under_an_older_key(tmp_path):
    """Persiana Americana - En Vivo, in wanted.txt since September, as an older caracole keyed it."""
    import json

    from caracole.songs import KEY_VERSION_KV
    from caracole.wanted import FIRST_SEEN_KEY

    wanted_file(tmp_path, "Soda Stereo - Persiana Americana - En Vivo\n")
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        conn.execute(
            "INSERT INTO songs (key, artist, title, artists, source_ids, added_at, created_at, "
            "updated_at) VALUES (?, 'Soda Stereo', 'Persiana Americana - En Vivo', ?, ?, ?, ?, ?)",
            (OLD_LIVE_KEY, json.dumps(["Soda Stereo"]), json.dumps({"wanted": [OLD_LIVE_KEY]}),
             SEPTEMBER, SEPTEMBER, SEPTEMBER),
        )
        db.kv_set(conn, FIRST_SEEN_KEY + OLD_LIVE_KEY, SEPTEMBER)
        db.kv_delete(conn, KEY_VERSION_KV)
    finally:
        conn.close()


def test_sync_after_an_upgrade_keeps_a_re_keyed_lines_place_in_the_queue(tmp_path):
    # The songs are re-keyed as the database opens, before the sync reads a line's first-seen
    # time: read under the old key, it would be "now", and the song would jump the queue.
    from caracole.wanted import FIRST_SEEN_KEY

    listed_since_september_under_an_older_key(tmp_path)
    result = run(tmp_path, "sync")
    assert result.exit_code == 0, result.output
    [song] = songs(tmp_path)
    assert (song.key, song.added_at) == ("soda-stereo/persiana-americana", SEPTEMBER)
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        assert db.kv_get(conn, FIRST_SEEN_KEY + "soda-stereo/persiana-americana") == SEPTEMBER
    finally:
        conn.close()


def test_sync_with_nothing_to_read_says_how_to_start(tmp_path):
    result = run(tmp_path, "sync")
    assert result.exit_code == 0, result.output
    assert "wanted.txt 0 songs, 0 new; Spotify off" in result.output
    assert str(wanted_file(tmp_path)) in result.output and "`caracole add" in result.output


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
    assert "Spotify needs authorization (run `caracole auth spotify`)" in result.output
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


# --- the pages ------------------------------------------------------------------------------

STALE = "as an earlier run left it\n"
PAGES = ("_todo.md", "index.html")
BROKEN_OVERRIDES = '[artist_url]\n"Maná" = "x"\n\n[artist_url]\n"宋冬野" = "y"\n'  # pasted twice


def stale_pages(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    for name in PAGES:
        (lib / name).write_text(STALE, encoding="utf-8")


def pages(tmp_path):
    return [(tmp_path / "lib" / name).read_text(encoding="utf-8") for name in PAGES]


@pytest.mark.parametrize("args", [("add", "宋冬野", "斑马斑马"), ("sync",)], ids=["add", "sync"])
def test_add_and_sync_rewrite_the_pages(tmp_path, args):
    wanted_file(tmp_path, "宋冬野 - 斑马斑马 | 安和桥北 | 4:13\n")
    stale_pages(tmp_path)
    result = run(tmp_path, *args)
    assert result.exit_code == 0, result.output
    todo, index = pages(tmp_path)
    assert "1 song: 0 found, 1 wanted" in todo
    assert "斑马斑马" in index


def test_search_add_rewrites_the_pages_too(tmp_path):
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    conn.execute(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (5001, 'stone-temple-pilots', 'creep', 'chords', '1', 'x', ?)",
        ("stone-temple-pilots/creep-chords-5001",),
    )
    conn.close()
    stale_pages(tmp_path)
    result = run(tmp_path, "search", "stone temple pilots creep", "--add", "1")
    assert result.exit_code == 0, result.output
    assert "Stone Temple Pilots - Creep" in pages(tmp_path)[1]


@pytest.mark.parametrize("args", [("add", "Radiohead", "Creep"), ("sync",)], ids=["add", "sync"])
def test_a_broken_overrides_file_leaves_the_pages_but_not_the_songs(tmp_path, args):
    # wanted.txt always works: the songs are synced; only the pages, which need the file, wait.
    wanted_file(tmp_path, "Radiohead - Creep\n")
    (tmp_path / "lib" / "overrides.toml").write_text(BROKEN_OVERRIDES, encoding="utf-8")
    stale_pages(tmp_path)
    result = run(tmp_path, *args)
    assert result.exit_code == 0, result.output
    assert [s.key for s in songs(tmp_path)] == ["radiohead/creep"]
    assert "overrides: " in result.output and "artist_url" in result.output
    assert "_todo.md and index.html" in result.output
    assert pages(tmp_path) == [STALE, STALE]


@pytest.mark.parametrize("args", [("add", "Radiohead", "Creep"), ("sync",)], ids=["add", "sync"])
def test_a_page_it_cant_write_is_a_warning_and_the_songs_are_synced(tmp_path, args):
    wanted_file(tmp_path, "Radiohead - Creep\n")
    (tmp_path / "lib" / "_todo.md").mkdir()  # a folder where the page goes (root too)
    result = run(tmp_path, *args)
    assert result.exit_code == 0, result.output
    assert f"can't write {tmp_path / 'lib' / '_todo.md'}: Is a directory" in result.output
    assert [s.key for s in songs(tmp_path)] == ["radiohead/creep"]
    said = "Radiohead - Creep is in wanted.txt already" if args[0] == "add" else "wanted.txt 1 song, 1 new"
    assert said in result.output


# --- caracole auth spotify --------------------------------------------------------------------

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
    import caracole.spotify

    real = caracole.spotify.make_auth

    def make_auth(cfg, state_dir):
        auth = real(cfg, state_dir)
        auth._session = session
        return auth

    monkeypatch.setattr(caracole.spotify, "make_auth", make_auth)


def test_auth_spotify_without_a_client_id_says_how_to_set_it_up(tmp_path, monkeypatch):
    monkeypatch.setattr("caracole.spotify.make_auth", lambda *a: pytest.fail("Spotify is off"))
    result = run(tmp_path, "auth", "spotify")
    assert result.exit_code == 1, result.output
    out = result.output
    assert "optional" in out and "wanted.txt" in out
    assert "developer.spotify.com" in out and REDIRECT in out
    assert str(tmp_path / "caracole.toml") in out
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
    assert "`caracole sync`" in result.output


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
    assert "Run `caracole auth spotify`" not in result.output  # that's what was just run
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


@pytest.mark.slow
def test_registering_the_commands_imports_no_spotipy(tmp_path):
    # Every command module is imported on every start, so spotipy waits for a command.
    src = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys, typer\n"
        "from caracole.commands import sources\n"
        "sources.register(typer.Typer())\n"
        "print([m for m in ('spotipy', 'caracole.spotify') if m in sys.modules])\n"
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
