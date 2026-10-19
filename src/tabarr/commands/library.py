"""Library commands: ``tabarr todo``, ``tabarr review`` and ``tabarr scan``."""

from __future__ import annotations

import typer

from tabarr.commands._common import fail, load_cfg, load_ovr, open_db, utcnow


def _rematch(conn, cfg) -> None:
    from tabarr.match import match_all

    match_all(conn, load_ovr(cfg), cfg.match)


def register(app: typer.Typer) -> None:
    @app.command("todo")
    def todo_cmd(ctx: typer.Context) -> None:
        """Rewrite Library/_todo.md and Library/index.html from the database."""
        from tabarr.library_page import build_library_page, write_library_page
        from tabarr.todo import build_todo, write_todo

        cfg = load_cfg(ctx)
        conn = open_db(cfg)
        overrides, now = load_ovr(cfg), utcnow()
        path = write_todo(cfg.library_dir, build_todo(conn, cfg, overrides, now))
        page = write_library_page(cfg.library_dir, build_library_page(conn, cfg, overrides, now))
        typer.echo(f"Wrote {path} and {page}")

    @app.command("review")
    def review_cmd(ctx: typer.Context) -> None:
        """Settle uncertain matches; each answer is written to overrides.toml."""
        from tabarr.overrides import OverridesError
        from tabarr.review import ReviewIO, review_songs

        cfg = load_cfg(ctx)
        load_ovr(cfg)  # a broken file stops here, before a question whose answer it couldn't keep
        conn = open_db(cfg)

        def read(prompt: str) -> str:  # the prompts end in ": "; Enter answers ""
            return typer.prompt(prompt, default="", show_default=False, prompt_suffix="")

        try:
            stats = review_songs(conn, cfg, ReviewIO(read=read, write=typer.echo),
                                 rematch=lambda: _rematch(conn, cfg))
        except OverridesError as e:  # the file broke while review waited for an answer
            fail(f"overrides: {e}", 2)
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
