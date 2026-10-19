"""Library commands: ``tabarr todo``, ``tabarr review`` and ``tabarr scan``."""

from __future__ import annotations

import typer

from tabarr.commands._common import load_cfg, load_ovr, open_db, utcnow


def _rematch(conn, cfg) -> None:
    from tabarr.match import match_all

    match_all(conn, load_ovr(cfg), cfg.match)


def register(app: typer.Typer) -> None:
    @app.command("todo")
    def todo_cmd(ctx: typer.Context) -> None:
        """Rewrite Library/_todo.md from the database."""
        from tabarr.todo import build_todo, write_todo

        cfg = load_cfg(ctx)
        conn = open_db(cfg)
        path = write_todo(cfg.library_dir, build_todo(conn, cfg, load_ovr(cfg), utcnow()))
        typer.echo(f"Wrote {path}")

    @app.command("review")
    def review_cmd(ctx: typer.Context) -> None:
        """Settle uncertain matches; each answer is written to overrides.toml."""
        from tabarr.review import ReviewIO, review_songs

        cfg = load_cfg(ctx)
        conn = open_db(cfg)
        stats = review_songs(
            conn, cfg, ReviewIO(read=lambda prompt: typer.prompt(prompt, default="s", show_default=False),
                                write=typer.echo),
            rematch=lambda: _rematch(conn, cfg),
        )
        typer.echo(
            f"accepted {stats.accepted}, pinned {stats.pinned}, ignored {stats.ignored}, skipped {stats.skipped}"
        )

    @app.command("scan")
    def scan_cmd(ctx: typer.Context) -> None:
        """Link purchased audio in Music/ to songs, and file Guitar Pro downloads from _inbox/."""
        from tabarr.inbox import file_inbox
        from tabarr.music import scan_music

        cfg = load_cfg(ctx)
        conn = open_db(cfg)
        music = scan_music(conn, cfg.music_dir)
        inbox = file_inbox(conn, cfg.library_dir)
        files = "file" if music.seen == 1 else "files"
        typer.echo(f"Music: {music.seen} {files}, {music.matched} linked, {len(music.unmatched)} unmatched")
        typer.echo(f"Inbox: {len(inbox.filed)} filed, {len(inbox.duplicates)} duplicates, {len(inbox.unmatched)} left")
