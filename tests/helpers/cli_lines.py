"""A command line a page shows for you to run, parsed by caracole's own CLI without running anything.

``parsed(line)`` splits ``line`` as a shell does, hands it to the CLI ``cli.build_app`` makes, with every command's
function stood in for, and gives the command it reaches, as its words (``("songbook", "make")``), and the parameters
it would get. A line the CLI refuses raises the CLI's own error (click's ``NoSuchOption`` for a name it takes for an
option), as nix/module-check.nix parses the units' command lines.
"""

from __future__ import annotations

import shlex
from typing import Any


def parsed(line: str) -> tuple[tuple[str, ...], dict[str, Any]]:
    import typer.main

    from caracole.cli import build_app

    words = shlex.split(line)
    assert words[:1] == ["caracole"], line
    root = typer.main.get_command(build_app())
    ran: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def stand_in(group, path: tuple[str, ...]) -> None:
        for name, command in group.commands.items():
            if hasattr(command, "commands"):
                stand_in(command, (*path, name))
            else:
                command.callback = lambda _at=(*path, name), **params: ran.append((_at, params))

    stand_in(root, ())
    root.main(words[1:], prog_name="caracole", standalone_mode=False)
    (reached,) = ran
    return reached
