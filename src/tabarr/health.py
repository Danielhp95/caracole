"""Provider health: cooldowns after blocks, and the per-request event log.

On a block a provider cools down for 24 hours, doubling on each repeated
block (24 h, 48 h, 96 h, …), until a successful run resets it (plan §6).
State lives in the ``kv`` table under ``provider:<name>``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from tabarr.db import kv_get_json, kv_set_json
from tabarr.http import Event

COOLDOWN_BASE = timedelta(hours=24)


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
    """Start (or extend) a cooldown: 24 h × 2^(strikes − 1)."""
    s = get_state(conn, provider)
    strikes = s.strikes + 1
    return _save(conn, ProviderState(
        provider=provider, strikes=strikes,
        cooldown_until=now + COOLDOWN_BASE * (2 ** (strikes - 1)),
        last_ok=s.last_ok, last_error=message, last_error_at=now,
    ))


def record_ok(conn: sqlite3.Connection, provider: str, now: datetime) -> ProviderState:
    """A run used the provider without a block: clear the cooldown and the strikes."""
    s = get_state(conn, provider)
    return _save(conn, ProviderState(
        provider=provider, strikes=0, cooldown_until=None, last_ok=now,
        last_error=s.last_error, last_error_at=s.last_error_at,
    ))


def record_error(conn: sqlite3.Connection, provider: str, now: datetime, message: str) -> ProviderState:
    """Remember a non-block error for the to-do page; it doesn't start a cooldown."""
    s = get_state(conn, provider)
    return _save(conn, ProviderState(
        provider=provider, strikes=s.strikes, cooldown_until=s.cooldown_until,
        last_ok=s.last_ok, last_error=message, last_error_at=now,
    ))


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
