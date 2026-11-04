"""config.py's defaults, for the phone: tests/conformance/data/caracole/config/config.json, what the phone's
``core.config.PhoneConfig.DEFAULTS`` is made of until a sync brings the computer's settings (kv ``phone:settings``,
docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §4.3).

Its format: ``{"providers": {name: {"budget", "delay", "enabled", "lookup_delay", "lookup_requests",
"lookup_per_hour", "per_day"}}, "switchable": [name, …], "user_agent": …, "match": {…}, "rank": {…}}``:

- ``providers``: ``config.DEFAULT_PROVIDERS`` in its order, each ``ProviderPolicy``'s fields in theirs, a pair a list,
  ``config.NO_BUDGET`` (``sys.maxsize``) the number it is, 9223372036854775807 (Kotlin's ``Long.MAX_VALUE``);
- ``switchable``: ``config.SWITCHABLE``, sorted;
- ``user_agent``: ``config.DEFAULT_USER_AGENT``;
- ``match`` and ``rank``: ``MatchPolicy()``'s and ``RankPolicy()``'s fields in their order, each value as Python holds
  it (``accept`` 90, an int, though the field is a float).
"""

import dataclasses
import json
import sys

from caracole import config
from helpers.corpus import DATA, check

CONFIG = DATA / "config" / "config.json"


def fields(obj) -> dict:
    return {f.name: list(v) if isinstance(v := getattr(obj, f.name), tuple) else v for f in dataclasses.fields(obj)}


def config_json() -> str:
    data = {
        "providers": {name: fields(policy) for name, policy in config.DEFAULT_PROVIDERS.items()},
        "switchable": sorted(config.SWITCHABLE),
        "user_agent": config.DEFAULT_USER_AGENT,
        "match": fields(config.MatchPolicy()),
        "rank": fields(config.RankPolicy()),
    }
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def test_config_json_is_config_pys_defaults():
    check(CONFIG, config_json())


def test_no_budget_is_the_phones_long_max_value():
    assert config.NO_BUDGET == sys.maxsize == 2**63 - 1
    data = json.loads(config_json())
    assert data["providers"]["azlyrics"]["budget"] == 9223372036854775807
    assert list(data["providers"]["ug"]) == ["budget", "delay", "enabled", "lookup_delay", "lookup_requests",
                                             "lookup_per_hour", "per_day"]
