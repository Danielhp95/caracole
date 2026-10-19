"""The nightly timer in nix/module.nix, as its option text and tabarr's cooldowns assume it."""

import re
from datetime import timedelta
from pathlib import Path

import pytest

from tabarr.health import COOLDOWN_BASE, COOLDOWN_MARGIN

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "nix" / "module.nix"

# The package's own build runs these tests on a source tree without nix/.
pytestmark = pytest.mark.skipif(not MODULE.is_file(), reason="the Nix files are not in this tree")


def timer_delay() -> timedelta:
    """The timer's RandomizedDelaySec: how late, at most, it starts a run."""
    (minutes,) = re.findall(r'RandomizedDelaySec = "(\d+)m";', MODULE.read_text(encoding="utf-8"))
    return timedelta(minutes=int(minutes))


def option_description(name: str) -> str:
    """An option's description in module.nix, on one line."""
    text = MODULE.read_text(encoding="utf-8")
    option = re.search(rf"^    {name} = lib\.mkOption \{{$.*?^    \}};$", text,
                       re.MULTILINE | re.DOTALL)
    assert option, name
    description = re.search(r"description = (\"(?:[^\"\\]|\\.)*\"|''.*?'');", option.group(0),
                            re.DOTALL)
    assert description, name
    return " ".join(description.group(1).split())


def test_the_schedule_option_says_runs_start_only_late():
    # RandomizedDelaySec puts a start 0-45 minutes late; it never starts a run early.
    description = option_description("schedule")
    assert f"up to {timer_delay() // timedelta(minutes=1)} minutes late" in description
    assert "give or take" not in description


def test_a_cooldown_outlasts_the_timer_delay_and_a_clock_change_but_not_a_night():
    # A cooldown counts from the blocked run's start. The runs it must skip can start later
    # in the day than that by the timer's delay, and an hour more if the clocks went back;
    # the run after them, as much earlier. The margin covers the first and not the second.
    clock_change = timedelta(hours=1)
    assert COOLDOWN_MARGIN > timer_delay() + clock_change
    assert COOLDOWN_MARGIN + timer_delay() + clock_change < COOLDOWN_BASE
