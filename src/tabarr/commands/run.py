"""``tabarr run``: the nightly pipeline (what the systemd timer starts)."""

from __future__ import annotations

import logging

import typer

from tabarr.commands._common import load_cfg


def register(app: typer.Typer) -> None:
    @app.command("run")
    def run_cmd(ctx: typer.Context) -> None:
        """Sync, refresh the index, match, fetch within budget, render, and write _todo.md."""
        from tabarr import pipeline

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        cfg = load_cfg(ctx)
        report = pipeline.run_pipeline(cfg)
        typer.echo(report.summary())
        if not report.ok:
            raise typer.Exit(1)
