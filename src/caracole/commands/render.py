"""``caracole render``: a ChordPro file and a PDF, in your key, for every kept sheet.

Then it rewrites _todo.md, which says when the PDFs were last made and which
failed, and index.html, which links them.
"""

from __future__ import annotations

from contextlib import closing

import typer

from caracole.commands import _common
from caracole.commands._common import exclusive, load_cfg, load_ovr, open_db, utcnow, write_pages
from caracole.commands.songbook import songbooks_line


def register(app: typer.Typer) -> None:
    @app.command("render")
    def render_cmd(
        ctx: typer.Context,
        force: bool = typer.Option(
            False, "--force", help="Render every PDF again, even those that are up to date."
        ),
    ) -> None:
        """Write sheet.cho and sheet.pdf, transposed as overrides.toml says, for every sheet; then the
        files of every songbook that needs them (caracole songbook).

        Exits 1 when a sheet or a songbook could not be rendered, or songbooks.toml can't be read; a
        warning says which and why.
        """
        from caracole.render import render_all
        from caracole.songbook import render_songbooks

        cfg = load_cfg(ctx)
        overrides = load_ovr(cfg)
        with exclusive(cfg, "render"), closing(open_db(cfg)) as conn:
            # A waiting lookup goes between two songs: --force renders every PDF, minutes of work.
            stats = render_all(conn, cfg, overrides, force=force, between=lambda: _common.hand_over(cfg, conn))
            books = render_songbooks(conn, cfg, overrides, force=force)  # after the sheets: they hold them
            write_pages(conn, cfg, overrides, utcnow())
        typer.echo(f"{stats.rendered} rendered, {stats.skipped} up to date, {stats.failed} failed")
        if books.error:
            typer.echo(f"Songbooks: songbooks.toml can't be read: {books.error}")
        elif books.rendered or books.skipped or books.failed:
            typer.echo(f"Songbooks: {songbooks_line(books)}")
        if stats.failed or books.failed or books.error:
            raise typer.Exit(1)
