"""``caracole serve``: the library page over HTTP, with a form to request songs (caracole/web/).

It listens on 127.0.0.1 unless ``--address`` says otherwise: a LAN or tailnet
address, or 0.0.0.0. It answers only to an IP address and the names it knows
(localhost, the machine's name, and ``--allow-host``). There is no sign-in:
whoever can reach it can read the library and request songs, so it belongs on a
network you trust. A request runs the caracole command line, one command at a
time, under caracole's lock. Its pages name the library, and a library that isn't
the usual one (in a temporary folder, or ``--label``) carries a badge on them
(library_name.py). Its requests' history is kept in the state folder, its
own file, and read back when it starts again (web/history.py). The server code is imported inside the command, as every
command module is imported on every start.
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
        label: str | None = typer.Option(
            None, "--label", metavar="TEXT",
            help="A badge beside the library's name on every page, for a library that isn't your usual one "
                 '("Demo", "Test"); --label "" for none. Without it, a library in a temporary folder is badged '
                 '"Scratch library".',
        ),
    ) -> None:
        """Serve the library page, with a form to request songs and fetch them now."""
        config_path = ctx.obj.config_path if ctx.obj is not None else None
        _serve(load_cfg(ctx), config_path, address, port, allow_host, label)


def _serve(cfg: Config, config_path: Path | None, address: str, port: int, allow_host: list[str],
           label: str | None = None) -> None:
    from caracole.library_name import LABEL_LIMIT, SCRATCH, scratch_badge
    from caracole.web import server
    from caracole.web.app import WebApp
    from caracole.web.history import FILE_NAME, History
    from caracole.web.jobs import CaracoleRunner, JobQueue
    from caracole.web.security import allowed_hosts

    try:
        hosts = allowed_hosts(address, hostname=socket.gethostname(), extra=allow_host)
    except ValueError as e:
        fail(f"--allow-host: {e}", 2)
    warn_elsewhere()  # once, here: its commands, run on the same home defaults, then say nothing of it (--home)
    if label is not None and len(label.strip()) > LABEL_LIMIT:
        fail(f"--label: {LABEL_LIMIT} characters at most", 2)
    badge = scratch_badge(cfg, label=label, config_path=config_path)
    # Its requests' history, its own file in the state folder, read back from the last server's (history.py)
    queue = JobQueue(CaracoleRunner(config_path, home=config_path is None),
                     history=History(cfg.state_dir / FILE_NAME))
    app = WebApp(cfg, queue, allowed=hosts, badge=badge)
    typer.echo("It answers to " + ", ".join(sorted(hosts)) + " and any IP address; --allow-host adds a name.")
    if badge is not None:
        why = (": it serves a library in a temporary folder; --label sets another badge, --label \"\" none"
               if label is None and badge == SCRATCH else "")
        typer.echo(f"Its pages say {badge} beside the library's name, {app.library_name.name}{why}.")
    try:
        server.serve(app, address, port, announce=typer.echo)
    except OSError as e:
        fail(f"can't listen on {address}:{port}: {e.strerror or e}")
