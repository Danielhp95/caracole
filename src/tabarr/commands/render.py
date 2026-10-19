"""``tabarr render``: a ChordPro file and a PDF, in your key, for every kept sheet."""

from __future__ import annotations

import logging

import typer

from tabarr.commands._common import load_cfg, load_ovr, open_db


def register(app: typer.Typer) -> None:
    @app.command("render")
    def render_cmd(
        ctx: typer.Context,
        force: bool = typer.Option(
            False, "--force", help="Render every PDF again, even those that are up to date."
        ),
    ) -> None:
        """Write sheet.cho and sheet.pdf, transposed as overrides.toml says, for every sheet.

        Exits 1 when a sheet could not be rendered; a warning says which and why.
        """
        from tabarr.render import render_all

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        cfg = load_cfg(ctx)
        stats = render_all(open_db(cfg), cfg, load_ovr(cfg), force=force)
        typer.echo(f"{stats.rendered} rendered, {stats.skipped} up to date, {stats.failed} failed")
        if stats.failed:
            raise typer.Exit(1)
