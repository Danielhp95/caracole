"""``caracole remove``: take a song out of caracole, until you ask for it again.

It says what goes and what stays (removal.py), asks, then removes the song's
wanted.txt lines, its record and the files caracole wrote, and leaves a
tombstone so that no source brings it back; ``--yes`` doesn't ask, and
``--list`` lists the songs removed. As ``caracole review`` does, it asks before
it takes caracole's lock, so a nightly run never waits for the answer; under
the lock it looks at the song again, removes it and rewrites _todo.md and
index.html. The removal code is imported inside the command: every command
module is imported on every start.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import typer

from caracole.commands._common import exclusive, fail, load_cfg, open_db, utcnow, warn, write_pages
from caracole.logs import plural

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.songs import RemovedSong, Song


def register(app: typer.Typer) -> None:
    @app.command("remove")
    def remove_cmd(
        ctx: typer.Context,
        song: str | None = typer.Argument(None, metavar='"ARTIST - TITLE"', help="The song, as the to-do page names it."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask: remove it."),
        list_them: bool = typer.Option(False, "--list", help="List the songs removed, and stop."),
    ) -> None:
        """Remove a song: its files, its wanted.txt line, its record; no source brings it back until you ask."""
        cfg = load_cfg(ctx)
        if list_them:
            _list(cfg)
            return
        if song is None:
            fail('Which song? Name it as "ARTIST - TITLE", or give --list.', 2)
        _remove(cfg, song, yes=yes)


def _list(cfg: Config) -> None:
    from caracole.songs import list_removed

    with closing(open_db(cfg)) as conn:
        removed = list_removed(conn)
    if not removed:
        typer.echo("No removed songs.")
        return
    typer.echo(f"{len(removed)} removed song{'s' if len(removed) != 1 else ''}; `caracole add` brings one back:")
    for stone in removed:
        typer.echo(f"  {stone.display}  removed {_when(stone.removed_at)}")


def _remove(cfg: Config, text: str, *, yes: bool) -> None:
    from caracole.removal import describe, plan_removal

    with closing(open_db(cfg)) as conn:
        song = _song(conn, text)
        if not yes:
            goes, stays, notes = describe(plan_removal(conn, cfg, song), cfg)
            typer.echo(f"Remove {song.display} from caracole?")
            _items("It takes:", goes)
            _items("It leaves:", stays)
            for note in notes:
                typer.echo(note)
            if not typer.confirm("Remove it?", default=False):
                typer.echo("Nothing was removed.")
                return
        with exclusive(cfg, "remove"):
            _remove_now(conn, cfg, song.key)


def _remove_now(conn: sqlite3.Connection, cfg: Config, key: str) -> None:
    """Under caracole's lock: look at the song again, remove it, rewrite the pages."""
    from caracole.removal import RemovalError, describe, plan_removal, remove_song
    from caracole.songs import find_song

    song = find_song(conn, key)
    if song is None:  # removed, or merged into another, while you answered
        fail("The song left the library meanwhile; nothing was removed.")
    plan = plan_removal(conn, cfg, song)
    try:
        result = remove_song(conn, cfg, plan, now=utcnow())
    except RemovalError as e:
        fail(str(e))
    files = f"deleted {plural(len(result.deleted), 'file')}"
    lines = len(result.wanted_lines)
    wanted = f", took {plural(lines, 'line')} out of wanted.txt" if lines else ""
    typer.echo(f"Removed {song.display}: {files}{wanted}.")
    _, stays, notes = describe(plan, cfg)
    _items("It left:", stays + [f"{plan.folder}/{name}: {why}" for name, why in result.kept[len(plan.keep):]])
    for note in notes:
        typer.echo(note)
    _write_pages(conn, cfg)
    for error in result.errors:
        warn(error)
    if result.errors:
        raise typer.Exit(1)


def _song(conn: sqlite3.Connection, text: str) -> Song:
    """The song "Artist - Title" names; an artist may have " - " in its name, so every split is tried.

    A song removed already says so and exits 0; one caracole doesn't know exits 1.
    """
    from caracole.normalize import identity_key
    from caracole.songs import find_song, removed_song

    keys = []
    start = 0
    while (at := text.find(" - ", start)) >= 0:
        artist, title = text[:at].strip(), text[at + 3:].strip()
        if artist and title:
            keys.append(identity_key(artist, title))
        start = at + 1
    if not keys:
        fail(f'Name the song as "ARTIST - TITLE", as the to-do page does: {text!r} isn\'t.', 2)
    for key in keys:
        song = find_song(conn, key)
        if song is not None:
            return song
    stone: RemovedSong | None = next((s for k in keys if (s := removed_song(conn, k))), None)
    if stone is not None:
        typer.echo(f"{stone.display} was removed on {_when(stone.removed_at)}. To bring it back: "
                   f"caracole add \"{stone.artist}\" \"{stone.title}\"")
        raise typer.Exit(0)
    fail(f'No song "{text}" in the library. `caracole search` finds the name it has there.')


def _write_pages(conn: sqlite3.Connection, cfg: Config) -> None:
    """Rewrite _todo.md and index.html without the song; without overrides.toml, leave them, and say so."""
    from caracole.overrides import OverridesError, load_overrides

    try:
        overrides = load_overrides(cfg.overrides_file)
    except OverridesError as e:
        warn(f"overrides: {e}\n_todo.md and index.html still list the song until it's fixed.")
        return
    pages = write_pages(conn, cfg, overrides, utcnow(), fatal=False)
    if pages is not None:
        typer.echo(f"Wrote {pages[0]} and {pages[1]}")


def _items(heading: str, lines: list[str]) -> None:
    if lines:
        typer.echo(heading)
        for line in lines:
            typer.echo(f"  - {line}")


def _when(stamp: str) -> str:
    """"2026-10-19T12:00:00Z" as "2026-10-19 12:00 UTC"."""
    return f"{stamp[:10]} {stamp[11:16]} UTC" if len(stamp) >= 16 else stamp
