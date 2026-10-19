import sys
import types
from datetime import UTC, datetime, timedelta, timezone

from tabarr.sources import SyncStats, default_kv_get, default_kv_set, default_upsert, utc_stamp


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
