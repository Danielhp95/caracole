"""Provider health: cooldowns after blocks, and the per-request event log.

On a block a provider cools down for 24 hours, doubling on each repeated
block (24 h, 48 h, 96 h, …), until a successful run resets it (plan §6). Each
cooldown is 2 hours longer than that, so however late the timer starts a run,
the nightly run's k-th block in a row skips the next 2^(k−1) runs, not one
fewer and not one more. State lives in the ``kv`` table under
``provider:<name>``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Callable

from caracole.db import kv_get_json, kv_set_json

if TYPE_CHECKING:
    from caracole.http import Event

COOLDOWN_BASE = timedelta(hours=24)
# A cooldown counts from the blocked run's start, and the timer (nix/module.nix)
# starts each run at 03:30 plus a fresh delay of up to 45 minutes; the night the
# clocks go back is 25 hours long. Without a margin, 24 h would end before the
# next run about half the time. 2 h covers both and stays well short of the
# night after.
COOLDOWN_MARGIN = timedelta(hours=2)


@dataclass(frozen=True)
class ProviderState:
    provider: str
    strikes: int = 0
    cooldown_until: datetime | None = None
    last_ok: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _parse(value: str | None) -> datetime | None:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) if value else None


def _key(provider: str) -> str:
    return f"provider:{provider}"


def get_state(conn: sqlite3.Connection, provider: str) -> ProviderState:
    raw = kv_get_json(conn, _key(provider), default={}) or {}
    return ProviderState(
        provider=provider,
        strikes=int(raw.get("strikes", 0)),
        cooldown_until=_parse(raw.get("cooldown_until")),
        last_ok=_parse(raw.get("last_ok")),
        last_error=raw.get("last_error"),
        last_error_at=_parse(raw.get("last_error_at")),
    )


def _save(conn: sqlite3.Connection, s: ProviderState) -> ProviderState:
    kv_set_json(conn, _key(s.provider), {
        "strikes": s.strikes,
        "cooldown_until": _iso(s.cooldown_until),
        "last_ok": _iso(s.last_ok),
        "last_error": s.last_error,
        "last_error_at": _iso(s.last_error_at),
    })
    return s


def record_block(conn: sqlite3.Connection, provider: str, now: datetime, message: str) -> ProviderState:
    """Start (or extend) a cooldown, for a run (or a command, or a lookup) that began at ``now``:
    24 h × 2^(strikes − 1), plus the margin.

    A cooldown still running at ``now`` stays as it is, with its strikes. A run only asks a provider
    that isn't cooling down, so that block came while the run went on: another caracole met it while
    this one let it go first (``_common.hand_over``), and the run met the same block, or its client
    refused to send for it. One block is one strike."""
    s = get_state(conn, provider)
    if s.cooldown_until is not None and now < s.cooldown_until:
        return s
    strikes = s.strikes + 1
    return _save(conn, replace(
        s, strikes=strikes, cooldown_until=now + COOLDOWN_BASE * (2 ** (strikes - 1)) + COOLDOWN_MARGIN,
        last_error=message, last_error_at=now,
    ))


def record_ok(conn: sqlite3.Connection, provider: str, now: datetime) -> ProviderState:
    """A run that began at ``now`` used the provider without a block: clear the cooldown and the strikes.

    A cooldown still running at ``now`` is left as it is. A run only asks a provider that isn't
    cooling down, so that block came while the run went on: another caracole met it while this
    one let it go first (a lookup in a pause of the nightly run, ``_common.hand_over``). It is
    newer than the run's answers."""
    s = get_state(conn, provider)
    if s.cooldown_until is not None and now < s.cooldown_until:
        return s
    return _save(conn, replace(s, strikes=0, cooldown_until=None, last_ok=now))


def answered_any(conn: sqlite3.Connection, run_id: str, provider: str, requests: int) -> bool:
    """Whether the provider answered at least one of the ``requests`` a run sent it: a nightly run's,
    a command's or a lookup's, by its run id in ``events``. Only then did the run go well
    (``record_ok``): one whose every request failed (UG answering 502, say) is no success.

    Every request a client sends is logged to ``events`` as answered (``ok``,
    ``not_modified``), an ``error`` or a ``blocked``; a client that logs nothing counts
    as answered.
    """
    failed = conn.execute(
        "SELECT COUNT(*) FROM events WHERE run = ? AND provider = ? AND decision IN ('error', 'blocked')",
        (run_id, provider),
    ).fetchone()[0]
    return requests > failed


def record_error(conn: sqlite3.Connection, provider: str, now: datetime, message: str) -> ProviderState:
    """Remember a non-block error for the to-do page; it doesn't start a cooldown."""
    return _save(conn, replace(get_state(conn, provider), last_error=message, last_error_at=now))


def is_cooling(conn: sqlite3.Connection, provider: str, now: datetime) -> bool:
    until = get_state(conn, provider).cooldown_until
    return until is not None and now < until


class EventLog:
    """Writes each network request to the ``events`` table; pass it as ``on_event``."""

    def __init__(self, conn: sqlite3.Connection, run_id: str, *, clock: Callable[[], datetime] | None = None):
        self.conn = conn
        self.run_id = run_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def __call__(self, event: Event) -> None:
        self.conn.execute(
            "INSERT INTO events (run, at, provider, url, status, decision, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.run_id, _iso(self._clock()), event.provider, event.url, event.status, event.decision, event.message),
        )
