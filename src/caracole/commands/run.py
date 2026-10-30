"""``caracole run``: the nightly pipeline (what the systemd timer starts).

It holds caracole's lock from start to end, so it waits for a ``caracole-admin``
command already running, and one started meanwhile waits for it.

Its summary goes to stdout (report.py), and only there: the log, on stderr,
is the root callback's. It exits 0 when the run did what it could, a block or
a spent budget included, and 1 for a bug, after every step has run.
"""

from __future__ import annotations

import sys
from contextlib import closing

import typer

from caracole import logs
from caracole.commands._common import exclusive, load_cfg, open_db


def register(app: typer.Typer) -> None:
    @app.command("run")
    def run_cmd(ctx: typer.Context) -> None:
        """Sync, refresh the index, match, fetch within budget, render, and write _todo.md."""
        from caracole import pipeline
        from caracole.report import style_for, summary_text

        cfg = load_cfg(ctx, builds_index="run")
        with exclusive(cfg, "run"), closing(open_db(cfg)) as conn:
            report = pipeline.run_pipeline(cfg, conn=conn)
        quiet = ctx.obj is not None and ctx.obj.verbosity == logs.QUIET
        typer.echo(summary_text(report, quiet=quiet, style=style_for(sys.stdout)), nl=False)
        if not report.ok:
            raise typer.Exit(1)
