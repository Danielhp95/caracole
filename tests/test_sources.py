import json
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

from caracole.config import Config
from caracole.sources import (
    SourcesReport,
    SyncStats,
    default_kv_get,
    default_kv_set,
    default_upsert,
    sync_sources,
)

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
CONN = object()


def test_sync_stats_defaults_are_independent():
    a, b = SyncStats(), SyncStats()
    a.errors.append("wanted.txt line 2: expected 'Artist - Title'")
    a.line_errors.append((2, "expected 'Artist - Title'"))
    assert (b.seen, b.new, b.errors, b.line_errors) == (0, 0, [], [])


def test_default_upsert_is_the_song_repository(monkeypatch):
    fake = types.ModuleType("caracole.songs")
    fake.upsert_song = lambda conn, **fields: (1, True)
    monkeypatch.setitem(sys.modules, "caracole.songs", fake)
    assert default_upsert() is fake.upsert_song


def test_default_kv_functions_are_the_database_ones(monkeypatch):
    fake = types.ModuleType("caracole.db")
    fake.kv_get = lambda conn, key: None
    fake.kv_set = lambda conn, key, value: None
    monkeypatch.setitem(sys.modules, "caracole.db", fake)
    assert default_kv_get() is fake.kv_get
    assert default_kv_set() is fake.kv_set


# --- sync_sources: wanted.txt, and how it went ---------------------------------------------------


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


def config(tmp_path):
    return Config(
        library_dir=tmp_path / "Tabs",
        music_dir=tmp_path / "Music",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        overrides_file=tmp_path / "Tabs" / "overrides.toml",
        wanted_file=tmp_path / "Tabs" / "wanted.txt",
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


def run(cfg, repo):
    return sync_sources(CONN, cfg, NOW, upsert=repo.upsert, kv_get=repo.kv_get, kv_set=repo.kv_set)


def test_sync_sources_reads_wanted_txt_and_records_how_it_went(tmp_path, wanted):
    repo = Repo()
    report = run(config(tmp_path), repo)
    assert (report.wanted.seen, report.wanted.new) == (2, 2)
    assert set(repo.songs) == {("wanted", "宋冬野/斑马斑马"), ("wanted", "soda-stereo/de-musica-ligera")}
    record = repo.record("source:wanted")
    assert record["at"] == "2026-10-18T03:30:00Z" and (record["lines"], record["new"]) == (2, 2)
    assert [n for n, _ in record["errors"]] == [2]
    assert set(repo.kv) == {"source:wanted", "wanted:first_seen:宋冬野/斑马斑马",
                            "wanted:first_seen:soda-stereo/de-musica-ligera"}
    assert report.summary() == "wanted.txt 2 songs, 2 new, 1 problem"


def test_sync_sources_leaves_no_wanted_record_before_the_file_exists(tmp_path):
    repo = Repo()
    report = run(config(tmp_path), repo)
    assert report.wanted.seen == 0
    assert repo.record("source:wanted") is None  # so the to-do page can say how to create it


def test_summary_counts_read_as_english():
    one = SourcesReport(wanted=SyncStats(seen=1, new=1, errors=["wanted.txt line 2: x"]))
    assert one.summary() == "wanted.txt 1 song, 1 new, 1 problem"
    two = SourcesReport(wanted=SyncStats(seen=2, new=0, errors=["a", "b"]))
    assert two.summary() == "wanted.txt 2 songs, 0 new, 2 problems"
    assert SourcesReport(wanted=SyncStats()).summary() == "wanted.txt 0 songs, 0 new"


# --- with the song repository: a wanted.txt line you fix, the sync, the music scan --------------


def wav(path, seconds):
    """A silent WAV file of that many seconds; its name says which song it is."""
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000 * seconds)
    return path


def write_wanted(cfg, text):
    cfg.wanted_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.wanted_file.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("fixed", ["Radiohead - Creep | 0:10", "Radiohead - Creep"])
def test_a_fixed_wanted_line_lets_the_purchase_it_kept_out_link(conn, tmp_path, fixed):
    # "| 0:30" for a song of 0:10. The scan wants the file of a song to last as long as the
    # song, give or take 3 s, so the purchase stays out until the line is fixed or its
    # duration goes; then the next sync and scan link it.
    from caracole.music import scan_music
    from caracole.songs import find_song

    cfg = config(tmp_path)
    bought = wav(cfg.music_dir / "Radiohead - Creep.wav", 10)
    write_wanted(cfg, "Radiohead - Creep | 0:30\n")
    sync_sources(conn, cfg, NOW)
    assert scan_music(conn, cfg.music_dir).unmatched == [bought]
    write_wanted(cfg, fixed + "\n")
    sync_sources(conn, cfg, NOW + timedelta(days=1))
    assert scan_music(conn, cfg.music_dir).unmatched == []
    assert find_song(conn, "radiohead/creep").audio_path == str(bought)
