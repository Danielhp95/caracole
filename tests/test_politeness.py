"""politeness.py: each caracole's politeness is its own, and what the computer gives the phone at a sync is its
settings (docs/superpowers/specs/2026-11-03-politeness-crossing.md)."""

import dataclasses
import json

from caracole import config, politeness
from caracole.config import load_config


def a_config(tmp_path, text: str = ""):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "caracole.toml"
    path.write_text(text, encoding="utf-8")
    return load_config(path, env={"HOME": str(tmp_path / "home"), "STATE_DIRECTORY": str(tmp_path / "state"),
                                  "CACHE_DIRECTORY": str(tmp_path / "cache")})


def test_the_settings_hold_the_name_the_user_agent_each_providers_lookup_settings_match_and_rank(tmp_path):
    doc = politeness.settings_document(a_config(tmp_path))
    assert list(doc) == ["name", "user_agent", "providers", "match", "rank"]
    assert doc["name"] is None and doc["user_agent"] == config.DEFAULT_USER_AGENT
    assert list(doc["providers"]) == list(config.DEFAULT_PROVIDERS)
    for name, policy in config.DEFAULT_PROVIDERS.items():
        assert doc["providers"][name] == {
            "enabled": True, "lookup_delay": list(policy.lookup_delay), "lookup_requests": policy.lookup_requests,
            "lookup_per_hour": policy.lookup_per_hour, "per_day": policy.per_day}, name
    assert doc["providers"]["megalobiz"]["per_day"] == 900 and doc["providers"]["ug"]["lookup_delay"] == [0.125, 0.375]
    assert doc["match"] == {"accept": 90, "margin": 8, "review": 75, "artist_gate": 90}
    assert doc["rank"] == {"coverage_threshold": 0.8, "line_match": 85, "prior_votes": 10, "scored_sheets": 3,
                           "label_penalty": 0.5, "variant_bonus": 0.25}
    assert json.loads(json.dumps(doc)) == doc


def test_caracole_tomls_switches_lookup_settings_match_rank_name_and_user_agent_are_given(tmp_path):
    cfg = a_config(tmp_path, """
name = "Canciones de Dani"
user_agent = "caracole/0.1 (Dani's tabs)"
[providers.ug]
lookup_delay = [0, 1]
lookup_requests = 3
lookup_per_hour = 30
[providers.megalobiz]
enabled = false
[match]
accept = 85.5
review = 70
[rank]
scored_sheets = 5
""")
    doc = politeness.settings_document(cfg)
    assert doc["name"] == "Canciones de Dani" and doc["user_agent"] == "caracole/0.1 (Dani's tabs)"
    assert doc["providers"]["ug"] == {"enabled": True, "lookup_delay": [0.0, 1.0], "lookup_requests": 3,
                                      "lookup_per_hour": 30, "per_day": None}
    assert doc["providers"]["megalobiz"]["enabled"] is False
    assert doc["match"]["accept"] == 85.5 and doc["match"]["review"] == 70 and doc["rank"]["scored_sheets"] == 5


def test_bulk_works_budget_and_pause_never_go_to_the_phone(tmp_path):
    """The phone never does bulk work: a run's budget and pause are no setting of its, whatever the computer's."""
    cfg = a_config(tmp_path, "[providers.ug]\nbudget = 7\ndelay = [9, 10]\n")
    doc = politeness.settings_document(cfg)
    assert all(set(p) == {"enabled", "lookup_delay", "lookup_requests", "lookup_per_hour", "per_day"}
               for p in doc["providers"].values())
    assert doc["providers"]["ug"] == politeness.settings_document(a_config(tmp_path / "other"))["providers"]["ug"]


def test_the_library_name_is_caracole_tomls_alone_never_the_folders(tmp_path):
    """A library its caracole.toml doesn't name is called after its folder ("Tabs"): the phone's folder is its own, so
    the phone is given no name then, and keeps its own."""
    cfg = a_config(tmp_path)
    assert cfg.library_name == "Tabs" and politeness.settings_document(cfg)["name"] is None


def test_no_folder_command_alert_or_politeness_record_is_given(tmp_path):
    """Nothing but the settings: no folder, no program, ntfy's topic (a URL anyone who has it can post to) never, and
    nothing of this side's own politeness, which isn't in the document's source at all (it reads the config alone)."""
    cfg = dataclasses.replace(a_config(tmp_path, '[ntfy]\nurl = "https://ntfy.sh/caracole-secret-topic"\n'),
                              chordpro_bin="/opt/chordpro")
    text = json.dumps(politeness.settings_document(cfg))
    for left_out in (str(tmp_path), "ntfy", "secret-topic", "chordpro", "yt-dlp", "budget", '"delay"'):
        assert left_out not in text, left_out
