"""``caracole render``: a ChordPro file and a PDF, in your key, for every kept sheet.

``--song`` renders one song's sheets alone, as the step after a web pick's
fetch does (web/jobs.py), so another song's failure is not its own, and
neither is a songbook's. Then it rewrites _todo.md, which says when the PDFs
were last made and which failed, and index.html, which links them.

``--song --version QUERY`` exports the sheet's PDF in that version; with
``--mine`` it makes that version the song's own instead (overrides.toml's
``[version]``, written once caracole's lock is held, as caracole serve's "Make
this my version" asks), then renders the song in it.
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
        mine: bool = typer.Option(
            False, "--mine",
            help="With --version: make it the song's own version (overrides.toml [version]) instead of "
                 "exporting it; its PDF, its viewer and its songbooks then start there.",
        ),
    ) -> None:
        """Write sheet.cho and sheet.pdf, in the song's own version as overrides.toml says ([version], else
        [transpose]), for every sheet (or one song's, with --song); then the files of every songbook that
        needs them (caracole songbook).

        With --song and --version, only that song's export in that version: another key, capo, mode, chosen
        shapes or swaps, written to a PDF beside the sheet's own. A later render remakes it when the sheet
        or the style changes; caracole remove deletes it. With --mine too, that version becomes the song's
        own in overrides.toml (or leaves it, when it is where the song plays without one), and the song is
        rendered in it.

        Exits 1 when a sheet or a songbook could not be rendered, or songbooks.toml can't be read; a
        warning says which and why. With --song, only when that song's sheets could not be.
        """
        from caracole.render import render_all
        from caracole.songbook import render_songbooks

        if version is not None and not song:
            _common.fail("--version needs --song: the version is one song's.", code=2)
        if mine and version is None:
            _common.fail("--mine needs --version: the version to make the song's own.", code=2)
        cfg = load_cfg(ctx)
        overrides = load_ovr(cfg)
        if version is not None and not mine:
            _export(cfg, overrides, song, version)
            return
        with exclusive(cfg, "render"), closing(open_db(cfg)) as conn:
            if mine:
                _make_mine(conn, cfg, overrides, song, version)
                overrides = load_ovr(cfg)
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


def _make_mine(conn, cfg, overrides, song_name: str, query: str) -> None:
    """``--mine``: the version ``query`` holds becomes the song's own in overrides.toml, under caracole's lock;
    one that is where the song plays without one (its ``[transpose]``, else as written) takes the song's
    ``[version]`` out instead."""
    from caracole.overrides import OverridesError, add_version
    from caracole.render import RenderError, export_label, export_query, export_version
    from caracole.viewer.version import Version

    song = song_named(conn, song_name, overrides)
    v = export_version(query, overrides, song)
    try:
        label = export_label(conn, cfg, song, v)
    except RenderError as e:
        _common.fail(f"no version of {song.display}: {e}")
    plain = export_query(Version(t=overrides.transpose.get(song.key, 0)))
    try:
        add_version(cfg.overrides_file, song.display, None if export_query(v) == plain else export_query(v))
    except OverridesError as e:
        _common.fail(f"overrides: {e}", 2)
    typer.echo(f"Your version of {song.display}: {label}")


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
