"""``caracole render``: a ChordPro file and a PDF, in your key, for every kept sheet.

``--song`` renders one song's sheets alone, as the step after a web pick's
fetch does (web/jobs.py), so another song's failure is not its own, and
neither is a songbook's. Then it rewrites _todo.md, which says when the PDFs
were last made and which failed, and index.html, which links them.
"""

from __future__ import annotations

from contextlib import closing

import typer

from caracole.commands import _common
from caracole.commands._common import exclusive, load_cfg, load_ovr, open_db, song_named, utcnow, write_pages
from caracole.commands.songbook import songbooks_line


def register(app: typer.Typer) -> None:
    @app.command("render")
    def render_cmd(
        ctx: typer.Context,
        force: bool = typer.Option(
            False, "--force", help="Render every PDF again, even those that are up to date."
        ),
        song: str | None = typer.Option(
            None, "--song", metavar='"ARTIST - TITLE"', help="Render only this song's sheets.",
        ),
        version: str | None = typer.Option(
            None, "--version", metavar="QUERY",
            help="With --song: export the sheet's PDF in this version (the viewer's address: "
                 "'t=2&mode=dorian&capo=0'), as 'sheet (G Dorian, capo 0).pdf'.",
        ),
    ) -> None:
        """Write sheet.cho and sheet.pdf, transposed as overrides.toml says, for every sheet (or one
        song's, with --song); then the files of every songbook that needs them (caracole songbook).

        With --song and --version, only that song's export in that version: another key, capo, mode, chosen
        shapes or swaps, written to a PDF beside the sheet's own. A later render remakes it when the sheet
        or the style changes; caracole remove deletes it.

        Exits 1 when a sheet or a songbook could not be rendered, or songbooks.toml can't be read; a
        warning says which and why. With --song, only when that song's sheets could not be.
        """
        from caracole.render import render_all
        from caracole.songbook import render_songbooks

        if version is not None and not song:
            _common.fail("--version needs --song: the version is one song's.", code=2)
        cfg = load_cfg(ctx)
        overrides = load_ovr(cfg)
        if version is not None:
            _export(cfg, overrides, song, version)
            return
        with exclusive(cfg, "render"), closing(open_db(cfg)) as conn:
            song_ids = {song_named(conn, song, overrides).id} if song else None
            # A waiting lookup goes between two songs: --force renders every PDF, minutes of work.
            stats = render_all(conn, cfg, overrides, force=force, between=lambda: _common.hand_over(cfg, conn),
                               song_ids=song_ids)
            # After the sheets, which they hold; --force --song forces that song's PDFs alone.
            books = render_songbooks(conn, cfg, overrides, force=force and not song)
            write_pages(conn, cfg, overrides, utcnow())
        typer.echo(f"{stats.rendered} rendered, {stats.skipped} up to date, {stats.failed} failed")
        if books.error:
            typer.echo(f"Songbooks: songbooks.toml can't be read: {books.error}")
        elif books.rendered or books.skipped or books.failed:
            typer.echo(f"Songbooks: {songbooks_line(books)}")
        if stats.failed or (not song and (books.failed or books.error)):
            raise typer.Exit(1)


def _export(cfg, overrides, song_name: str, query: str) -> None:
    """``--version``: the one export, then the pages, which list it."""
    from caracole.render import RenderError, export_version, render_version

    with exclusive(cfg, "render"), closing(open_db(cfg)) as conn:
        song = song_named(conn, song_name, overrides)
        try:
            path = render_version(conn, cfg, overrides, song, export_version(query, overrides, song))
        except (RenderError, OSError) as e:
            _common.fail(f"no export for {song.display}: {e}")
        write_pages(conn, cfg, overrides, utcnow())
    typer.echo(f"Exported {path}")
