"""``caracole backup``: a whole copy of the database now, as the nightly run makes one at its end (backup.py).

It takes caracole's lock, so it waits for a run or a command that holds it, and the copies beyond the newest
three go once it is made. ``--list`` reads the folder alone: no lock, no database. A disk without room for a
copy, or a copy that fails its check, exits 1 and leaves the copies there were.
"""

from __future__ import annotations

from contextlib import closing

import typer

from caracole.commands._common import exclusive, fail, load_cfg, open_db, utcnow


def register(app: typer.Typer) -> None:
    @app.command("backup")
    def backup_cmd(
        ctx: typer.Context,
        list_: bool = typer.Option(False, "--list", help="List the copies there are instead, the newest last."),
    ) -> None:
        """Copy the database whole into the state folder's backups/, keeping the newest three."""
        from caracole import backup

        cfg = load_cfg(ctx)
        where = backup.folder(cfg.state_dir)
        if list_:
            copies = backup.backups(cfg.state_dir)
            if not copies:
                typer.echo(f"No copy of the database in {where} yet.")
                return
            typer.echo(f"{len(copies)} {'copy' if len(copies) == 1 else 'copies'} of the database in {where}, "
                       "the newest last:")
            width = max(len(b.path.name) for b in copies)
            for b in copies:
                typer.echo(f"  {b.path.name:<{width}}  {b.at.strftime('%Y-%m-%d %H:%M UTC')}  "
                           f"{backup.size_text(b.size)}")
            return
        with exclusive(cfg, "backup"), closing(open_db(cfg)) as conn:
            try:
                made = backup.make(conn, cfg.state_dir, utcnow())
            except backup.BackupError as e:
                fail(f"No backup: {e}. The copies in {where} stay as they are.")
        if isinstance(made, backup.Skipped):
            fail(f"No backup: {made.reason}.")
        gone = "".join(f", {p.name} deleted" for p in made.deleted)
        typer.echo(f"Backed up the database to {made.backup.path} ({backup.size_text(made.backup.size)}) in "
                   f"{made.seconds:.1f} s; {made.kept} kept{gone}.")
