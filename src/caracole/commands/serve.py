"""``caracole serve``: the library page over HTTP, with a form to request songs (caracole/web/).

It listens on 127.0.0.1 unless ``--address`` says otherwise: a LAN or tailnet
address, or 0.0.0.0. It answers only to the names it knows (localhost, the
address, the machine's name, and ``--allow-host``), and with ``--token-file``,
or a ``web_token`` credential from systemd, asks for that access token once
per browser. A request runs the caracole command line, one command at a time,
under caracole's lock. The server code is imported inside the command, as every
command module is imported on every start.
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from caracole.commands._common import fail, load_cfg

if TYPE_CHECKING:
    from caracole.config import Config

DEFAULT_PORT = 8737
MIN_TOKEN = 16  # characters
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


def register(app: typer.Typer) -> None:
    @app.command("serve")
    def serve_cmd(
        ctx: typer.Context,
        address: str = typer.Option(
            "127.0.0.1", "--address", metavar="ADDRESS",
            help="Where to listen: 127.0.0.1 (this machine alone), a LAN or tailnet address, or 0.0.0.0.",
        ),
        port: int = typer.Option(DEFAULT_PORT, "--port", min=1, max=65535, help="The port to listen on."),
        allow_host: list[str] = typer.Option(
            [], "--allow-host", metavar="NAME",
            help="Another name the server answers to, such as its tailnet name; repeat for more.",
        ),
        token_file: Path | None = typer.Option(
            None, "--token-file", metavar="FILE",
            help="A file holding an access token that each browser gives once. "
                 "Default: $CREDENTIALS_DIRECTORY/web_token, when it exists.",
        ),
    ) -> None:
        """Serve the library page, with a form to request songs and fetch them now."""
        config_path = ctx.obj.config_path if ctx.obj is not None else None
        _serve(load_cfg(ctx), config_path, address, port, allow_host, token_file)


def _access_token(token_file: Path | None) -> str | None:
    """The access token from ``--token-file``, else from systemd's credentials; None without either."""
    if token_file is None:
        creds = os.environ.get("CREDENTIALS_DIRECTORY")
        if not creds or not (Path(creds) / "web_token").is_file():
            return None
        token_file = Path(creds) / "web_token"
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        fail(f"can't read the access token in {token_file}: {getattr(e, 'strerror', None) or e}", 2)
    if len(token) < MIN_TOKEN:
        fail(f"the access token in {token_file} is too short: use {MIN_TOKEN} characters or more, "
             "such as the output of `openssl rand -base64 24`", 2)
    return token


def _serve(cfg: Config, config_path: Path | None, address: str, port: int, allow_host: list[str],
           token_file: Path | None) -> None:
    from caracole.web import server
    from caracole.web.app import WebApp
    from caracole.web.jobs import CaracoleRunner, JobQueue
    from caracole.web.security import allowed_hosts

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    token = _access_token(token_file)
    try:
        hosts = allowed_hosts(address, hostname=socket.gethostname(), extra=allow_host)
    except ValueError as e:
        fail(f"--allow-host: {e}", 2)
    app = WebApp(cfg, JobQueue(CaracoleRunner(config_path)), allowed=hosts, access_token=token)
    if address.strip("[]") not in _LOOPBACK and token is None:
        typer.secho(f"Listening on {address}: anyone who can reach it can read the library and request "
                    "songs. On a LAN, give an access token with --token-file.", err=True,
                    fg=typer.colors.YELLOW)
    typer.echo("It answers to " + ", ".join(sorted(hosts)) + "; --allow-host adds a name.")
    try:
        server.serve(app, address, port, announce=typer.echo)
    except OSError as e:
        fail(f"can't listen on {address}:{port}: {e.strerror or e}")
