"""How caracole stores and shows a time: ISO 8601 UTC to the second ("2026-10-18T03:30:00Z"), shown in UTC,
or in the server's local time zone on the library page's Requests tab.

A naive time is UTC. The standard library alone, so any module may import it.
"""

from __future__ import annotations

from datetime import UTC, datetime

FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc(dt: datetime) -> datetime:
    """``dt`` in UTC; a naive time is UTC already."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def stamp(dt: datetime) -> str:
    """``dt`` as stored: "2026-10-18T03:30:00Z"."""
    return utc(dt).strftime(FORMAT)


def parse(value: str | None) -> datetime | None:
    """A stored time in UTC; None when it is missing or unreadable."""
    try:
        return utc(datetime.fromisoformat(value)) if value else None
    except ValueError:
        return None


def before(value: str | None, cutoff: datetime) -> bool:
    """Whether a stored time is older than ``cutoff``; a missing or unreadable one is."""
    when = parse(value)
    return when is None or when < cutoff


def shown(dt: datetime | None, none: str = "?", *, local: bool = False) -> str:
    """A time as the to-do page shows it, in UTC; ``none`` for no time. ``local``: in the server's local time
    zone, named, as the library page's Requests tab shows it ("2026-10-17 23:30 EDT")."""
    if dt is None:
        return none
    return utc(dt).astimezone().strftime("%Y-%m-%d %H:%M %Z") if local else utc(dt).strftime("%Y-%m-%d %H:%M UTC")
