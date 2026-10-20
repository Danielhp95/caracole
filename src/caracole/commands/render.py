"""``caracole render``: a ChordPro file and a PDF, in your key, for every kept sheet.

``--song`` renders one song's sheets alone, as the step after a web pick's
fetch does (web/jobs.py), so another song's failure is not its own, and
neither is a songbook's. Then it rewrites _todo.md, which says when the PDFs
were last made and which failed, and index.html, which links them.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import typer

from caracole.commands import _common
from caracole.commands._common import exclusive, fail, load_cfg, load_ovr, open_db, utcnow, write_pages
from caracole.commands.songbook import songbooks_line

if TYPE_CHECKING:
    from caracole.overrides import Overrides
    from caracole.songs import Song


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
    ) -> None:
        """Write sheet.cho and sheet.pdf, transposed as overrides.toml says, for every sheet (or one
        song's, with --song); then the files of every songbook that needs them (caracole songbook).

        Exits 1 when a sheet or a songbook could not be rendered, or songbooks.toml can't be read; a
        warning says which and why. With --song, only when that song's sheets could not be.
        """
        from caracole.render import render_all
        from caracole.songbook import render_songbooks

        cfg = load_cfg(ctx)
        overrides = load_ovr(cfg)
        with exclusive(cfg, "render"), closing(open_db(cfg)) as conn:
            song_ids = {_one_song(conn, song, overrides).id} if song else None
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


def _one_song(conn: sqlite3.Connection, display: str, overrides: Overrides) -> Song:
    """The song ``--song`` names; otherwise say why there is none to render."""
    from caracole.overrides import OverridesError, override_key
    from caracole.songs import find_song

    try:
        key = override_key(display)
    except OverridesError as e:
        fail(str(e), 2)
    found = find_song(conn, key)
    if found is None:
        fail(f'No song "{display}" in the library. Add it with `caracole add` first.')
    if found.status == "ignored" or key in overrides.ignore:
        fail(f'"{found.display}" is ignored in overrides.toml.')
    return found
