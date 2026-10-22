from datetime import UTC, datetime, timedelta

import httpx
import pytest

from caracole.health import EventLog, get_state, is_cooling, record_block, record_error, record_ok
from caracole.http import Event, ProviderBlocked
from caracole.notify import Notifier
from caracole.pipeline import Services, Step, run_pipeline

T0 = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)

# The nightly timer (nix/module.nix) starts each run at 03:30 plus a fresh delay of up to
# 45 minutes (RandomizedDelaySec). A night the clocks change is 23 or 25 hours long.
LATE = timedelta(minutes=45)
CLOCK_CHANGE = timedelta(hours=1)


def night(n: int, late: timedelta = timedelta(0), clocks: timedelta = timedelta(0)) -> datetime:
    """When the run n nights after T0's starts: ``late`` past 03:30, ``clocks`` after a change."""
    return T0 + timedelta(days=n) + late + clocks


def test_fresh_provider_is_not_cooling(conn):
    s = get_state(conn, "ug")
    assert s.strikes == 0 and s.cooldown_until is None
    assert not is_cooling(conn, "ug", T0)


def test_cooldown_doubles_and_resets(conn):
    # 24 h, 48 h, 96 h, each 2 h longer: blocked on nights 0, 2 and 5, each time on the
    # first night it could ask again.
    s1 = record_block(conn, "ug", T0, "403 on /tab/1")
    assert s1.strikes == 1 and s1.cooldown_until == T0 + timedelta(hours=24 + 2)
    assert is_cooling(conn, "ug", T0 + timedelta(hours=25, minutes=59))
    assert not is_cooling(conn, "ug", T0 + timedelta(hours=26, seconds=1))
    s2 = record_block(conn, "ug", night(2), "429")
    assert s2.strikes == 2 and s2.cooldown_until == night(2) + timedelta(hours=48 + 2)
    s3 = record_block(conn, "ug", night(5), "403")
    assert s3.cooldown_until == night(5) + timedelta(hours=96 + 2)
    record_ok(conn, "ug", T0 + timedelta(days=10))
    s4 = get_state(conn, "ug")
    assert s4.strikes == 0 and s4.cooldown_until is None and s4.last_ok == T0 + timedelta(days=10)
    assert s4.last_error == "403"


def test_a_first_block_skips_the_next_nightly_run_however_late_it_starts(conn):
    # The blocked run started on time, and a run's cooldown counts from its start (pipeline.py
    # passes the run's now); the next run starts as late as the timer lets it.
    record_block(conn, "ug", T0, "403 on /tab/1")
    assert is_cooling(conn, "ug", night(1, LATE))
    assert is_cooling(conn, "ug", night(1, LATE, CLOCK_CHANGE))  # the night the clocks go back


@pytest.mark.parametrize("blocks", [1, 2, 3, 4])
def test_a_block_skips_its_nights_and_not_one_more(conn, blocks):
    nights = 2 ** (blocks - 1)  # 24 h, 48 h, 96 h, 192 h
    for before in range(blocks - 1, 0, -1):  # the blocks before it in a row, each once the one before had ended
        record_block(conn, "ug", T0 - timedelta(days=30 * before), "403")
        record_block(conn, "lrclib", T0 - timedelta(days=30 * before), "429")
    record_block(conn, "ug", T0, "403")  # blocked in a run that started on time...
    record_block(conn, "lrclib", T0 + LATE, "429")  # ...and in one as late as the timer allows
    # Each of its nights is skipped, even when that run starts as late as it can...
    for n in range(1, nights + 1):
        assert is_cooling(conn, "ug", night(n, LATE, CLOCK_CHANGE)), n
    # ...and the night after is not, even at its earliest start, after the clocks went forward.
    assert not is_cooling(conn, "lrclib", night(nights + 1, clocks=-CLOCK_CHANGE))


def test_a_cooldown_ends_at_the_time_the_state_gives(conn):
    # Commands, the run's messages and the to-do page all print cooldown_until.
    s = record_block(conn, "ug", T0, "403")
    assert is_cooling(conn, "ug", s.cooldown_until - timedelta(seconds=1))
    assert not is_cooling(conn, "ug", s.cooldown_until)


class _Client:
    """A provider's client as the run reads it."""

    requests_made = 0

    def close(self) -> None:
        pass


def _nightly_run(conn, cfg, start: datetime, ug: str | Exception = "ok"):
    """A nightly run of one UG step: the report, whether the step ran, and what ntfy got."""
    clients = {p: _Client() for p in ("ug", "lrclib", "lacuerda")}
    sent: list[str] = []

    def fetch(ctx) -> str:
        clients["ug"].requests_made += 1
        if isinstance(ug, Exception):
            raise ug
        return ug

    def ntfy(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200)

    notifier = Notifier("https://ntfy.sh/t", None, transport=httpx.MockTransport(ntfy))
    report = run_pipeline(cfg, conn=conn, services=Services(clients, None, notifier),
                          steps=[Step("fetch", fetch, provider="ug")], now=start)
    return report, clients["ug"].requests_made > 0, sent


def test_the_run_after_a_block_leaves_the_provider_alone_however_late_it_starts(conn, cfg):
    blocked = ProviderBlocked("ug", "https://tabs.ultimate-guitar.com/tab/1", 403, "HTTP 403")
    first, _, sent = _nightly_run(conn, cfg, T0, ug=blocked)  # on time
    second, asked, _ = _nightly_run(conn, cfg, night(1, LATE))  # the next night, 45 minutes late
    assert first.blocked == ["ug"] and not asked
    # The block's message and the skipped step print the time the run went by.
    assert "so caracole leaves it alone until 2026-10-19 05:30 UTC." in sent[0]
    assert second.steps["fetch"] == "skipped: ug cooling down until 2026-10-19 05:30 UTC"
    _, asked, _ = _nightly_run(conn, cfg, night(2))  # the night after that, on time, asks again
    assert asked and get_state(conn, "ug").strikes == 0


def test_a_good_run_leaves_a_cooldown_that_began_after_it_did(conn):
    # A block another caracole met while this one had let it go first (a lookup in the nightly run's
    # pause) is newer than this run's answers: the run's end clears no part of it.
    met = T0 + timedelta(minutes=12)
    record_block(conn, "ug", met, "403")
    record_ok(conn, "ug", T0)
    s = get_state(conn, "ug")
    assert s.strikes == 1 and s.cooldown_until == met + timedelta(hours=26) and s.last_ok is None
    assert is_cooling(conn, "ug", night(1))


def test_a_block_met_after_a_block_another_caracole_met_meanwhile_is_that_block(conn):
    # The run (started at T0) let a lookup go first, which UG blocked; the run then met that block too: one block,
    # one strike and its cooldown, not two in a row.
    met = T0 + timedelta(minutes=12)
    lookups = record_block(conn, "ug", met, "ug: 403: https://tabs.ultimate-guitar.com/tab/9: HTTP 403")
    assert record_block(conn, "ug", T0, "ug: 403: https://tabs.ultimate-guitar.com/tab/2: HTTP 403") == lookups
    assert get_state(conn, "ug") == lookups and lookups.strikes == 1


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
