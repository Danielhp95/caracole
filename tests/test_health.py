from datetime import UTC, datetime, timedelta

from tabarr.health import EventLog, get_state, is_cooling, record_block, record_error, record_ok
from tabarr.http import Event

T0 = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)


def test_fresh_provider_is_not_cooling(conn):
    s = get_state(conn, "ug")
    assert s.strikes == 0 and s.cooldown_until is None
    assert not is_cooling(conn, "ug", T0)


def test_cooldown_doubles_and_resets(conn):
    s1 = record_block(conn, "ug", T0, "403 on /tab/1")
    assert s1.strikes == 1 and s1.cooldown_until == T0 + timedelta(hours=24)
    assert is_cooling(conn, "ug", T0 + timedelta(hours=23))
    assert not is_cooling(conn, "ug", T0 + timedelta(hours=24, seconds=1))
    s2 = record_block(conn, "ug", T0 + timedelta(hours=25), "429")
    assert s2.strikes == 2 and s2.cooldown_until == T0 + timedelta(hours=25 + 48)
    s3 = record_block(conn, "ug", T0 + timedelta(hours=80), "403")
    assert s3.cooldown_until == T0 + timedelta(hours=80 + 96)
    record_ok(conn, "ug", T0 + timedelta(days=10))
    s4 = get_state(conn, "ug")
    assert s4.strikes == 0 and s4.cooldown_until is None and s4.last_ok == T0 + timedelta(days=10)
    assert s4.last_error == "403"


def test_record_error_keeps_strikes(conn):
    record_block(conn, "ug", T0, "403")
    record_error(conn, "ug", T0 + timedelta(hours=30), "502 on sitemap")
    s = get_state(conn, "ug")
    assert s.strikes == 1 and s.last_error == "502 on sitemap"


def test_providers_are_independent(conn):
    record_block(conn, "ug", T0, "403")
    assert not is_cooling(conn, "lrclib", T0)


def test_event_log_writes_rows(conn):
    log = EventLog(conn, "2026-10-18T03:30:00Z", clock=lambda: T0)
    log(Event(provider="ug", url="https://x.test/1", status=200, decision="ok", message=None))
    log(Event(provider="ug", url="https://x.test/2", status=403, decision="blocked", message="forbidden"))
    rows = conn.execute("SELECT run, at, provider, url, status, decision, message FROM events ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        ("2026-10-18T03:30:00Z", "2026-10-18T03:30:00Z", "ug", "https://x.test/1", 200, "ok", None),
        ("2026-10-18T03:30:00Z", "2026-10-18T03:30:00Z", "ug", "https://x.test/2", 403, "blocked", "forbidden"),
    ]
