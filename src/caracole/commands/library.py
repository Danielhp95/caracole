"""Library commands: ``caracole todo``, ``caracole review`` and ``caracole scan``.

Each rewrites _todo.md and index.html for what it changed (``review`` only when
an answer changed something), holding caracole's lock while it writes; ``review``
takes it only after the questions, never while it waits for you. An
overrides.toml that can't be read still gets the to-do page rewritten, leading
with why, and the command exits 2, as the nightly run does. The pages are built
by modules that import the matcher and the index, so those are imported inside
the commands: every command module is imported on every start.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from caracole.commands._common import (
    exclusive,
    fail,
    load_cfg,
    load_ovr,
    open_db,
    utcnow,
    write_pages,
)
from caracole.overrides import Overrides, OverridesError, load_overrides

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.music import ScanStats


def _overrides_for_pages(conn: sqlite3.Connection, cfg: Config, now: datetime) -> Overrides:
    """overrides.toml, to build the pages with.

    One that can't be read still gets the to-do page rewritten, leading with why, and then exits 2.
    index.html is left as it was: built without your overrides it would lose your transpositions and
    ignored songs.
    """
    from caracole.todo import build_todo, write_todo

    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError as e:
        try:
            path = write_todo(cfg.library_dir, build_todo(conn, cfg, Overrides(), now, overrides_error=str(e)))
            typer.echo(f"Wrote {path}, which leads with this error; index.html was left as it was")
        except OSError as w:
            typer.secho(f"can't write {cfg.library_dir / '_todo.md'}: {w.strerror or w}", err=True,
                        fg=typer.colors.RED)
        fail(f"overrides: {e}", 2)


def _rewrite_pages(conn: sqlite3.Connection, cfg: Config, what: str, *,
                   rematch: bool = False) -> tuple[Path, Path]:
    """Rewrite _todo.md and index.html (matching every song first, with ``rematch``), holding caracole's
    lock as ``what``; a library caracole can't write exits 1."""
    with exclusive(cfg, what):
        now = utcnow()
        overrides = _overrides_for_pages(conn, cfg, now)
        if rematch:
            from caracole.match import match_all

            match_all(conn, overrides, cfg.match)
        return write_pages(conn, cfg, overrides, now)


def _music_line(cfg: Config, music: ScanStats) -> str:
    if not music.seen:  # scan_music unlinks nothing then: a disk that isn't mounted tonight, say
        why = "has no audio files" if cfg.music_dir.is_dir() else "is missing"
        return f"Music: {cfg.music_dir} {why}, so nothing was unlinked"
    files = "file" if music.seen == 1 else "files"
    return f"Music: {music.seen} {files}, {music.matched} linked, {len(music.unmatched)} unmatched"


def register(app: typer.Typer) -> None:
    @app.command("todo")
    def todo_cmd(ctx: typer.Context) -> None:
        """Rewrite Library/_todo.md and Library/index.html from the database."""
        cfg = load_cfg(ctx)
        path, page = _rewrite_pages(open_db(cfg), cfg, "todo")
        typer.echo(f"Wrote {path} and {page}")

    @app.command("review")
    def review_cmd(ctx: typer.Context) -> None:
        """Settle uncertain matches; each answer is written to overrides.toml."""
        from caracole.review import ReviewIO, review_songs

        cfg = load_cfg(ctx)
        load_ovr(cfg)  # a broken file stops here, before a question whose answer it couldn't keep
        conn = open_db(cfg)
        written: list[Path] = []

        def read(prompt: str) -> str:  # the prompts end in ": "; Enter answers ""
            return typer.prompt(prompt, default="", show_default=False, prompt_suffix="")

        def settle() -> None:  # after the questions, when an answer changed something
            written.extend(_rewrite_pages(conn, cfg, "review", rematch=True))

        try:
            stats = review_songs(conn, cfg, ReviewIO(read=read, write=typer.echo), rematch=settle)
        except OverridesError as e:  # the file broke while review waited for an answer
            fail(f"overrides: {e}", 2)
        typer.echo(f"accepted {stats.accepted}, pinned {stats.pinned}, ignored {stats.ignored}, "
                   f"rejected {stats.rejected}, skipped {stats.skipped}")
        if written:
            typer.echo(f"Wrote {written[0]} and {written[1]}")

    @app.command("scan")
    def scan_cmd(ctx: typer.Context) -> None:
        """Link purchased audio in Music/ to songs, and file Guitar Pro downloads from _inbox/."""
        from caracole.inbox import file_inbox
        from caracole.music import scan_music

        cfg = load_cfg(ctx)
        conn = open_db(cfg)
        with exclusive(cfg, "scan"):
            music = scan_music(conn, cfg.music_dir)
            inbox = file_inbox(conn, cfg.library_dir)
            typer.echo(_music_line(cfg, music))
            refused = len(inbox.refused)  # links, never read: the to-do page names them
            links = f", {refused} symbolic link{'s' if refused != 1 else ''} refused" if refused else ""
            typer.echo(f"Inbox: {len(inbox.filed)} filed, {len(inbox.duplicates)} duplicates, "
                       f"{len(inbox.unmatched)} left{links}")
            path, page = _rewrite_pages(conn, cfg, "scan")
        typer.echo(f"Wrote {path} and {page}")
