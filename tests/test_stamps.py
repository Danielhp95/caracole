import time
from datetime import UTC, datetime, timedelta, timezone

import pytest

from caracole import stamps

NAIVE = datetime(2026, 10, 18, 3, 30)  # noqa: DTZ001 (deliberately naive)
PLUS_TWO = timezone(timedelta(hours=2))


def test_utc_reads_a_naive_time_as_utc_and_converts_an_aware_one():
    assert stamps.utc(NAIVE) == datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
    assert stamps.utc(datetime(2026, 10, 18, 5, 30, tzinfo=PLUS_TWO)) == datetime(2026, 10, 18, 3, 30, tzinfo=UTC)


def test_stamp_is_iso_utc_with_z():
    assert stamps.stamp(datetime(2026, 10, 18, 3, 30, 5, 999999, tzinfo=UTC)) == "2026-10-18T03:30:05Z"
    assert stamps.stamp(datetime(2026, 10, 18, 5, 30, tzinfo=PLUS_TWO)) == "2026-10-18T03:30:00Z"


def test_stamp_reads_naive_time_as_utc():
    assert stamps.stamp(NAIVE) == "2026-10-18T03:30:00Z"


def test_parse_gives_utc_and_none_for_a_missing_or_unreadable_value():
    assert stamps.parse("2026-10-18T03:30:00Z") == datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
    assert stamps.parse("2026-10-18T05:30:00+02:00") == datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
    assert stamps.parse("2026-10-18T03:30:00") == datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
    assert stamps.parse(None) is None
    assert stamps.parse("") is None
    assert stamps.parse("garbage") is None


def test_before_counts_a_missing_or_unreadable_stamp_as_older():
    cutoff = datetime(2026, 10, 18, tzinfo=UTC)
    assert stamps.before(None, cutoff)
    assert stamps.before("garbage", cutoff)
    assert stamps.before("2026-10-17T23:59:59Z", cutoff)
    assert not stamps.before("2026-10-18T00:00:00Z", cutoff)
    assert not stamps.before("2026-10-19T00:00:00Z", cutoff)


def test_stamps_round_trip():
    assert stamps.parse(stamps.stamp(NAIVE)) == stamps.utc(NAIVE)


def test_shown_is_the_to_do_pages_time_in_utc():
    assert stamps.shown(NAIVE) == "2026-10-18 03:30 UTC"
    assert stamps.shown(datetime(2026, 10, 18, 5, 30, tzinfo=PLUS_TWO)) == "2026-10-18 03:30 UTC"
    assert stamps.shown(None) == "?"
    assert stamps.shown(None, "never") == "never"


@pytest.fixture
def five_hours_west(monkeypatch):
    """The server's local time zone, five hours behind UTC and named EST (a POSIX rule: no zone files)."""
    monkeypatch.setenv("TZ", "EST+05")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_shown_local_is_the_requests_pages_time_in_the_servers_zone_named(five_hours_west):
    assert stamps.shown(NAIVE, local=True) == "2026-10-17 22:30 EST"
    assert stamps.shown(datetime(2026, 10, 18, 5, 30, tzinfo=PLUS_TWO), local=True) == "2026-10-17 22:30 EST"
    assert stamps.shown(None, "", local=True) == ""


def test_sources_stamp_is_this_one():
    from caracole import sources

    assert sources.utc_stamp is stamps.stamp
