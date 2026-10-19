"""``tabarr run``: the nightly pipeline (what the systemd timer starts).

It holds tabarr's lock from start to end, so it waits for a ``tabarr-admin``
command already running, and one started meanwhile waits for it.
"""

from __future__ import annotations

import logging
from contextlib import closing

import typer

from tabarr.commands._common import exclusive, load_cfg, open_db


def register(app: typer.Typer) -> None:
    @app.command("run")
    def run_cmd(ctx: typer.Context) -> None:
        """Sync, refresh the index, match, fetch within budget, render, and write _todo.md."""
        from tabarr import pipeline

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        cfg = load_cfg(ctx)
        with exclusive(cfg, "run"), closing(open_db(cfg)) as conn:
            report = pipeline.run_pipeline(cfg, conn=conn)
        typer.echo(report.summary())
        if not report.ok:
            raise typer.Exit(1)
