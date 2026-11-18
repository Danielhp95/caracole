"""Caracoles in processes of their own, taking caracole's lock in the lane or waiting for it, each writing what it
did, timed, to a log: for tests/test_commands_lane.py.

    config = config_file(cfg, tmp_path)                      # a caracole.toml of cfg's folders: the same lock
    a = start(TURNS, config, log, "a", 6, go=tmp_path / "go-a")
    wait_for(log, "ready", "a")                              # imported, and waiting for its go file
    (tmp_path / "go-a").touch()                              # now it asks for the lock
    turns = [r for r in records(log) if r.word == "turn"]    # each line a Record: word, name, t, rest

Every script opens the one log they share with "a", line-buffered, so each line is one write of its own; writes
``ready <name> <t>`` (``t`` its ``time.time()``) once it has imported caracole; then waits for its own ``go`` file,
when it has one, before it asks for the lock, so a test starts every process up front and lets each go at the state
it waits for (a line seen in the log, a waiter seen waiting), never against a time window. A script never told to go
within ``GO_WITHIN`` seconds exits, its test gone. What a script says on stderr goes to ``<log>.err``.

- ``TURNS`` (name, turns): in the lane, each turn writes ``turn <name> <t> <i>``, sleeps 0.1 s and calls
  ``pass_turn(cfg)``; then ``end <name> <t>``, still holding the lock.
- ``HOLD`` (name): in the lane, writes ``holding <name> <t>``, then sleeps 60 s holding the lock.
- ``WAITER`` (name, kind): ``exclusive(cfg, f"remove {name}", interactive=kind == "asked")``, then ``got <name>
  <t>``, holding it: "asked" waits as what the owner asked for now does, anything else as bulk work.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

from conftest import subprocess_pythonpath

SRC = Path(__file__).resolve().parents[2] / "src"
GO_WITHIN = 120  # seconds a script waits for its go file before it gives up

_PRELUDE = f"""
import os, sys, time
from pathlib import Path
from caracole.commands import _common
from caracole.config import load_config

cfg = load_config(Path(sys.argv[1]))
log = open(sys.argv[2], "a", encoding="utf-8", buffering=1)
go, args = sys.argv[3], sys.argv[4:]
name = args[0]


def say(word, *rest):
    log.write(" ".join([word, name, f"{{time.time():.6f}}", *map(str, rest)]) + "\\n")


say("ready")
deadline = time.monotonic() + {GO_WITHIN}
while go and not os.path.exists(go):
    if time.monotonic() > deadline:
        sys.exit("never told to go")
    time.sleep(0.005)
"""

TURNS = _PRELUDE + """
with _common.exclusive(cfg, f"get {name}", lane=True):
    for i in range(int(args[1])):
        say("turn", i)
        time.sleep(0.1)
        _common.pass_turn(cfg)
    say("end")
"""

HOLD = _PRELUDE + """
with _common.exclusive(cfg, f"get {name}", lane=True):
    say("holding")
    time.sleep(60)
"""

WAITER = _PRELUDE + """
with _common.exclusive(cfg, f"remove {name}", interactive=args[1] == "asked"):
    say("got")
"""


class Record(NamedTuple):
    """A line of the log: what a script did (``word``), which one (``name``), when (``t``, its ``time.time()``),
    and the rest of the line's words."""

    word: str
    name: str
    t: float
    rest: list[str]


def config_file(cfg, tmp_path: Path, ug: str = "") -> Path:
    """A caracole.toml naming ``cfg``'s library, state and cache folders, so that a process of its own takes the
    same lock and lane, with ``ug``'s lines under ``[providers.ug]`` when given."""
    lines = [f"{key} = {json.dumps(str(getattr(cfg, key)))}" for key in ("library_dir", "state_dir", "cache_dir")]
    if ug:
        lines += ["[providers.ug]", ug]
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def start(script: str, config: Path, log: Path, *args: object, go: Path | None = None) -> subprocess.Popen:
    """``script`` in a Python of its own, given ``config``, ``log``, ``go`` and ``args`` (its name first)."""
    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(SRC)}
    with open(log.with_name(log.name + ".err"), "a", encoding="utf-8") as err:
        return subprocess.Popen(
            [sys.executable, "-c", script, str(config), str(log), str(go) if go is not None else "", *map(str, args)],
            env=env, cwd=log.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
        )


def records(log: Path) -> list[Record]:
    """Each line of ``log`` written whole, in the order written."""
    try:
        text = log.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    out = []
    for line in text.splitlines(keepends=True):
        if not line.endswith("\n"):
            break  # still being written
        word, name, t, *rest = line.split()
        out.append(Record(word, name, float(t), rest))
    return out


def wait_for(log: Path, word: str, name: str, timeout: float = 30) -> float:
    """When ``name`` first wrote ``word``, waiting up to ``timeout`` seconds for it to: an AssertionError naming
    what the scripts wrote and said otherwise."""
    deadline = time.monotonic() + timeout
    while True:
        for record in records(log):
            if record.word == word and record.name == name:
                return record.t
        if time.monotonic() > deadline:
            break
        time.sleep(0.01)
    said = log.with_name(log.name + ".err")
    raise AssertionError(f"{name} never wrote {word!r} within {timeout} s.\n"
                         f"{log.name}:\n{log.read_text(encoding='utf-8') if log.exists() else ''}\n"
                         f"{said.name}:\n{said.read_text(encoding='utf-8') if said.exists() else ''}")
