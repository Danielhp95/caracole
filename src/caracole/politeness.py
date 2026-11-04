"""Two caracoles' politeness, and what crosses between them (docs/superpowers/specs/2026-11-03-politeness-crossing.md).

Each caracole's politeness is its own, the owner's choice of 2026-11-03 ("Don't do the polite request across 2
devices"): a phone and a computer each keep their own limits, request counts (``events``), cooldowns, pace and the kv
records that gate a request, and nothing of them crosses at a sync, either way. So two caracoles at one address may
together send a site more than either one's limits.

What crosses is the computer's settings, to the phone: ``settings_document``, ``GET /api/peer/state``'s ``settings``
(web/peer_routes.py), which the phone keeps as kv ``phone:settings`` and lays over config.py's defaults, so that it
looks songs up with the switches, lookup limits, user agent, match and rank thresholds and library name the computer's
caracole.toml gives. A lookup's settings alone: the phone never does bulk work, so a run's ``budget`` and ``delay``
stay the phone's defaults, and no folder, program or alert (ntfy's topic) is given. The phone never sends settings
back.

The standard library alone.
"""

from __future__ import annotations

import dataclasses
from typing import Any

# What a provider's settings are for the phone: a lookup's, and its switch.
LOOKUP_FIELDS = ("enabled", "lookup_delay", "lookup_requests", "lookup_per_hour", "per_day")


def _plain(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _fields(policy: Any, names: tuple[str, ...] | None = None) -> dict[str, Any]:
    """A policy's fields in their order (``names`` alone, in theirs), each as Python holds it, a pair a list."""
    names = names or tuple(f.name for f in dataclasses.fields(policy))
    return {name: _plain(getattr(policy, name)) for name in names}


def settings_document(cfg) -> dict[str, Any]:
    """The settings this caracole gives a phone at a sync, of its config (``config.Config``):

    ``{"name", "user_agent", "providers": {name: {"enabled", "lookup_delay", "lookup_requests", "lookup_per_hour",
    "per_day"}}, "match": {…}, "rank": {…}}``: caracole.toml's ``name`` (None when it names none: the phone's
    library folder is its own, so it keeps its own name), the user agent every site sees, each provider of the config
    in its order with its switch and a lookup's settings, and ``[match]``'s and ``[rank]``'s fields in their order,
    each value as config.py holds it (``accept`` 90, an int, until caracole.toml gives a float)."""
    return {
        "name": cfg.name,
        "user_agent": cfg.user_agent,
        "providers": {name: _fields(policy, LOOKUP_FIELDS) for name, policy in cfg.providers.items()},
        "match": _fields(cfg.match),
        "rank": _fields(cfg.rank),
    }
