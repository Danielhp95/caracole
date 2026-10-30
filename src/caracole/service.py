"""Whether this machine runs caracole as a service, and whether a caracole started by hand would use other folders.

A caracole started with no ``--config`` and no ``CARACOLE_CONFIG`` runs on its home defaults (config.py:
``~/.local/state/caracole``, ``~/Tabs``), while the service's units and ``caracole-admin`` name its config, in
/var/lib/caracole by default. On a machine with both, an index built from a shell lands in the home database,
days of polite requests the service never sees. So the service leaves a marker, ``MARKER``, readable by everyone:
nix/module.nix writes it (``environment.etc``), and so do docs/deploy.md's Ubuntu steps. It is a few lines of TOML
naming the service's folders, ``state_dir`` and ``library_dir``; one that won't read, or names no absolute path,
still says a service is here. ``CARACOLE_SERVICE_FILE`` names another file (the tests' own; conftest.py points it
at none). ``elsewhere`` is the service when a caracole on its home defaults would use another database than its;
commands/_common.py's ``load_cfg`` then refuses an index build, unless ``--home``, and warns once before the first
write (``warn_elsewhere``). The standard library alone, as every command reads it.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from caracole.config import Config

MARKER = Path("/etc/caracole/service")
MARKER_ENV = "CARACOLE_SERVICE_FILE"
ADMIN = "sudo caracole-admin"


@dataclass(frozen=True)
class Service:
    """caracole's service on this machine: its marker, and the folders it names (None when it names none)."""

    marker: Path
    state_dir: Path | None
    library_dir: Path | None


def marker_path(env: Mapping[str, str]) -> Path:
    return Path(env.get(MARKER_ENV) or MARKER)


def find(env: Mapping[str, str]) -> Service | None:
    """The service its marker tells of; None without one."""
    path = marker_path(env)
    if not os.path.lexists(path):
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        data = {}

    def folder(key: str) -> Path | None:
        value = data.get(key)
        return Path(value) if isinstance(value, str) and value.startswith("/") else None

    return Service(path, folder("state_dir"), folder("library_dir"))


def elsewhere(cfg: Config, env: Mapping[str, str], *, explicit: bool) -> Service | None:
    """The service, when ``cfg`` is caracole's home defaults (no config named, ``explicit`` False) on a machine
    with one, and its database another than the service's; None else."""
    if explicit:
        return None
    found = find(env)
    if found is None or (found.state_dir is not None and _same(found.state_dir, cfg.state_dir)):
        return None
    return found


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def _places(cfg: Config, found: Service) -> tuple[str, str]:
    """Where the home defaults are, and where the service is, in words."""
    home = f"its database in {cfg.state_dir} and its library in {cfg.library_dir}"
    if found.state_dir is None and found.library_dir is None:
        there = f"(its marker, {found.marker}, names no folder)"
    else:
        parts = [f"its database in {found.state_dir}" if found.state_dir else "",
                 f"its library in {found.library_dir}" if found.library_dir else ""]
        there = " and ".join(p for p in parts if p)
    return home, there


def warning(cfg: Config, found: Service, command: str) -> str:
    """What a command that writes or sends requests says first, on the home defaults beside the service."""
    home, there = _places(cfg, found)
    return (f"caracole runs on its home defaults here (no --config, no CARACOLE_CONFIG), {home}; but this machine "
            f"runs caracole as a service, {there}. For the service's library, run `{ADMIN} {command}`; "
            "`caracole --home …` says nothing of it.")


def refusal(cfg: Config, found: Service, command: str) -> str:
    """Why an index build on the home defaults beside the service builds nothing."""
    home, there = _places(cfg, found)
    return (f"`caracole {command}` would build an index into caracole's home defaults, {home}, and this machine "
            f"runs caracole as a service, {there}: an index takes days of requests, so nothing was done. To build "
            f"the service's, run `{ADMIN} {command}`; to build the home one all the same, `caracole --home "
            f"{command}`.")
