"""``caracole serve``: the library page over HTTP, with a form to request songs (caracole/web/).

It listens on 127.0.0.1 unless ``--address`` says otherwise: a LAN or tailnet
address, or 0.0.0.0. It answers only to an IP address and the names it knows
(localhost, the machine's name, and ``--allow-host``). There is no sign-in:
whoever can reach it can read the library and request songs, so it belongs on a
network you trust. A request runs the caracole command line, one command at a
time, under caracole's lock. The server code is imported inside the command, as
every command module is imported on every start.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from caracole.commands._common import fail, load_cfg, warn_elsewhere

if TYPE_CHECKING:
    from caracole.config import Config

DEFAULT_PORT = 8737


def register(app: typer.Typer) -> None:
    @app.command("serve")
    def serve_cmd(
        ctx: typer.Context,
        address: str = typer.Option(
            "127.0.0.1", "--address", metavar="ADDRESS",
            help="Where to listen: 127.0.0.1 (this machine alone), a LAN or tailnet address, or 0.0.0.0. "
                 "There is no sign-in: listen only on a network you trust.",
        ),
        port: int = typer.Option(DEFAULT_PORT, "--port", min=1, max=65535, help="The port to listen on."),
        allow_host: list[str] = typer.Option(
            [], "--allow-host", metavar="NAME",
            help="Another name the server answers to, such as its tailnet name; repeat for more.",
        ),
    ) -> None:
        """Serve the library page, with a form to request songs and fetch them now."""
        config_path = ctx.obj.config_path if ctx.obj is not None else None
        _serve(load_cfg(ctx), config_path, address, port, allow_host)


def _serve(cfg: Config, config_path: Path | None, address: str, port: int, allow_host: list[str]) -> None:
    from caracole.web import server
    from caracole.web.app import WebApp
    from caracole.web.jobs import CaracoleRunner, JobQueue
    from caracole.web.security import allowed_hosts

    try:
        hosts = allowed_hosts(address, hostname=socket.gethostname(), extra=allow_host)
    except ValueError as e:
        fail(f"--allow-host: {e}", 2)
    warn_elsewhere()  # once, here: its commands, run on the same home defaults, then say nothing of it (--home)
    app = WebApp(cfg, JobQueue(CaracoleRunner(config_path, home=config_path is None)), allowed=hosts)
    typer.echo("It answers to " + ", ".join(sorted(hosts)) + " and any IP address; --allow-host adds a name.")
    try:
        server.serve(app, address, port, announce=typer.echo)
    except OSError as e:
        fail(f"can't listen on {address}:{port}: {e.strerror or e}")
