import json
import sys
import types
from datetime import UTC, datetime, timedelta, timezone

import pytest
from spotipy.exceptions import SpotifyException

from tabarr.config import Config, SpotifyConfig
from tabarr.sources import (
    SyncStats,
    default_kv_get,
    default_kv_set,
    default_upsert,
    sync_sources,
    utc_stamp,
)

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
CONN = object()
LEARN = "0LearnPlaylist00000000"


def test_sync_stats_defaults_are_independent():
    a, b = SyncStats(), SyncStats()
    a.errors.append("wanted.txt line 2: expected 'Artist - Title'")
    a.missing_playlists.append("Learn")
    a.line_errors.append((2, "expected 'Artist - Title'"))
    assert (b.seen, b.new, b.errors, b.missing_playlists, b.line_errors) == (0, 0, [], [], [])


def test_utc_stamp_is_iso_utc_with_z():
    assert utc_stamp(datetime(2026, 10, 18, 3, 30, 5, 999999, tzinfo=UTC)) == "2026-10-18T03:30:05Z"
    plus_two = timezone(timedelta(hours=2))
    assert utc_stamp(datetime(2026, 10, 18, 5, 30, tzinfo=plus_two)) == "2026-10-18T03:30:00Z"


def test_utc_stamp_reads_naive_time_as_utc():
    naive = datetime(2026, 10, 18, 3, 30)  # noqa: DTZ001 (deliberately naive)
    assert utc_stamp(naive) == "2026-10-18T03:30:00Z"


def test_default_upsert_is_the_song_repository(monkeypatch):
    fake = types.ModuleType("tabarr.songs")
    fake.upsert_song = lambda conn, **fields: (1, True)
    monkeypatch.setitem(sys.modules, "tabarr.songs", fake)
    assert default_upsert() is fake.upsert_song


def test_default_kv_functions_are_the_database_ones(monkeypatch):
    fake = types.ModuleType("tabarr.db")
    fake.kv_get = lambda conn, key: None
    fake.kv_set = lambda conn, key, value: None
    monkeypatch.setitem(sys.modules, "tabarr.db", fake)
    assert default_kv_get() is fake.kv_get
    assert default_kv_set() is fake.kv_set


# --- sync_sources: every source, and how each one went ------------------------------------------


class Repo:
    """Fake song repository and kv table: upserts are recorded, kv values kept."""

    def __init__(self):
        self.songs = {}
        self.kv = {}

    def upsert(
        self, conn, *, artists, title, album, duration_ms, isrc, source, source_id, added_at
    ):
        assert conn is CONN
        created = (source, source_id) not in self.songs
        self.songs[(source, source_id)] = title
        return len(self.songs), created

    def kv_get(self, conn, key):
        return self.kv.get(key)

    def kv_set(self, conn, key, value):
        self.kv[key] = value

    def record(self, key):
        return json.loads(self.kv[key]) if key in self.kv else None


class OneTrackSpotify:
    """Liked Songs holding one track; no playlists of yours; no top tracks."""

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


def config(tmp_path, **spotify):
    return Config(
        library_dir=tmp_path / "Tabs",
        music_dir=tmp_path / "Music",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        overrides_file=tmp_path / "Tabs" / "overrides.toml",
        wanted_file=tmp_path / "Tabs" / "wanted.txt",
        spotify=SpotifyConfig(**spotify),
    )


@pytest.fixture
def wanted(tmp_path):
    path = tmp_path / "Tabs" / "wanted.txt"
    path.parent.mkdir(parents=True)
    path.write_text(
        "宋冬野 - 斑马斑马 | 安和桥北 | 4:13\nnot a song line\nSoda Stereo - De Música Ligera\n",
        encoding="utf-8",
    )
    return path


def run(cfg, repo, spotify=None):
    return sync_sources(
        CONN, cfg, NOW, spotify=spotify, upsert=repo.upsert, kv_get=repo.kv_get, kv_set=repo.kv_set
    )


def test_sync_sources_without_spotify(tmp_path, wanted):
    repo = Repo()
    report = run(config(tmp_path), repo)
    assert (report.wanted.seen, report.wanted.new) == (2, 2)
    assert report.spotify_state == "off" and report.spotify is None
    record = repo.record("source:wanted")
    assert record["at"] == "2026-10-18T03:30:00Z" and (record["lines"], record["new"]) == (2, 2)
    assert [n for n, _ in record["errors"]] == [2]
    assert repo.record("source:spotify") is None
    assert "wanted.txt 2 songs, 2 new" in report.summary() and "Spotify off" in report.summary()


def test_sync_sources_leaves_no_wanted_record_before_the_file_exists(tmp_path):
    repo = Repo()
    report = run(config(tmp_path), repo)
    assert report.wanted.seen == 0
    assert repo.record("source:wanted") is None  # so the to-do page can say how to create it


def test_sync_sources_with_spotify(tmp_path, wanted):
    repo = Repo()
    report = run(config(tmp_path, client_id="cid", client_secret="secret"), repo, OneTrackSpotify())
    assert report.spotify_state == "ok" and report.spotify_message is None
    assert (report.spotify.seen, report.spotify.new) == (1, 1)
    assert ("spotify", "tCreep") in repo.songs and ("wanted", "宋冬野/斑马斑马") in repo.songs
    record = repo.record("source:spotify")
    assert (record["state"], record["at"], record["new"]) == ("ok", "2026-10-18T03:30:00Z", 1)
    assert "Spotify 1 songs, 1 new" in report.summary()


def test_sync_sources_needs_authorization_without_a_client(tmp_path, wanted):
    repo = Repo()
    report = run(config(tmp_path, client_id="cid", client_secret="secret"), repo, None)
    assert report.spotify_state == "auth_needed"
    assert "authoriz" in report.spotify_message
    assert repo.record("source:spotify")["state"] == "auth_needed"
    assert report.wanted.seen == 2  # wanted.txt keeps working


def test_sync_sources_says_when_the_client_secret_is_missing(tmp_path, wanted):
    report = run(config(tmp_path, client_id="cid"), Repo(), None)
    assert report.spotify_state == "auth_needed"
    assert "client secret" in report.spotify_message


def test_sync_sources_turns_a_refused_token_into_auth_needed(tmp_path, wanted):
    repo = Repo()
    spotify = OneTrackSpotify(error=SpotifyException(401, -1, "x:\n The access token expired"))
    report = run(config(tmp_path, client_id="cid", client_secret="secret"), repo, spotify)
    assert report.spotify_state == "auth_needed"
    assert "tabarr auth spotify" not in report.spotify_message  # the caller adds the advice
    assert repo.record("source:spotify")["state"] == "auth_needed"


def test_sync_sources_reports_spotify_problems_as_errors(tmp_path, wanted):
    repo = Repo()
    cfg = config(tmp_path, client_id="cid", client_secret="secret", playlists=("Learn", LEARN))
    report = run(cfg, repo, OneTrackSpotify())
    assert report.spotify_state == "error"
    assert "Learn" in report.spotify_message and LEARN in report.spotify_message
    record = repo.record("source:spotify")
    assert record["state"] == "error" and record["new"] == 1
    assert record["missing_playlists"] == ["Learn", LEARN]
