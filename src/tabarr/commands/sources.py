"""Source commands: ``tabarr add``, ``tabarr sync`` and ``tabarr auth spotify``.

wanted.txt is the source that always works. Spotify is optional, and no Spotify
failure makes ``tabarr sync`` fail. Every command module is imported on every
start, so spotipy and the source modules are imported inside the commands.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import typer

from tabarr.commands._common import fail, load_cfg, open_db, utcnow

if TYPE_CHECKING:
    from tabarr.config import Config
    from tabarr.wanted import WantedLine

# How `tabarr add` describes a song the library already had, by its status.
_KNOWN = {"wanted": "no sheet yet", "found": "has a sheet", "ignored": "ignored"}


def register(app: typer.Typer) -> None:
    @app.command("add")
    def add_cmd(
        ctx: typer.Context,
        artist: str = typer.Argument(..., help="The artist, as you'd write it."),
        title: str = typer.Argument(..., help="The song's title."),
        album: str | None = typer.Option(
            None, "--album", help="The album; it makes the lyrics lookup exact."
        ),
        duration: str | None = typer.Option(
            None,
            "--duration",
            metavar="M:SS",
            help="The length, as m:ss or whole seconds; it also makes the lookup exact.",
        ),
    ) -> None:
        """Add a song to wanted.txt, then sync wanted.txt into the library."""
        duration_ms = _duration_ms(duration)
        _add(load_cfg(ctx), artist, title, album, duration_ms)


# --- tabarr add -----------------------------------------------------------------------------


def _duration_ms(text: str | None) -> int | None:
    """``--duration`` in milliseconds; a value that isn't a duration exits with status 2."""
    if text is None:
        return None
    from tabarr.wanted import parse_duration

    try:
        ms = parse_duration(text)
    except ValueError as e:
        fail(f"--duration: {e}", 2)
    if ms is None:
        fail(f"--duration: {text.strip()!r} is not a duration: write m:ss or whole seconds", 2)
    return ms


def _add(cfg: Config, artist: str, title: str, album: str | None, duration_ms: int | None) -> None:
    """Append the song to wanted.txt unless it's listed, print its line, and sync the file."""
    from tabarr.wanted import append_wanted, find_wanted, format_line

    path = cfg.wanted_file
    try:
        listed = find_wanted(path, artist, title)
        line = append_wanted(path, artist, title, album, duration_ms)
    except ValueError as e:  # a song the file can't hold, such as an artist with " - " in it
        fail(f"can't add this song: {e}", 2)
    except OSError as e:
        fail(f"can't update {path}: {e.strerror or e}")
    typer.echo(f"{'Already in' if listed else 'Added to'} {path}, line {line.line_no}:")
    typer.echo(f"  {format_line(line.artist, line.title, line.album, line.duration_ms)}")
    if listed and _would_change(line, album, duration_ms):
        typer.echo("That line stays as it is: edit it to change the album or the duration.")
    _sync_wanted_song(cfg, line)


def _would_change(line: WantedLine, album: str | None, duration_ms: int | None) -> bool:
    """Whether the album or duration given differs from what the listed line says."""
    from tabarr.wanted import format_line

    asked = format_line(
        line.artist,
        line.title,
        album if album and album.strip() else line.album,
        line.duration_ms if duration_ms is None else duration_ms,
    )
    return asked != format_line(line.artist, line.title, line.album, line.duration_ms)


def _sync_wanted_song(cfg: Config, line: WantedLine) -> None:
    """Sync wanted.txt into the database, then say what the library knows of the line's song.

    The line is already in the file, which is the source of truth, so a database
    that can't be opened is a warning: the next sync adds the song.
    """
    from tabarr.songs import find_song
    from tabarr.wanted import sync_wanted

    try:
        with closing(open_db(cfg)) as conn:
            known = find_song(conn, line.identity)
            stats = sync_wanted(conn, cfg.wanted_file, utcnow())
            song = find_song(conn, line.identity)
    except (sqlite3.Error, OSError) as e:
        typer.echo(f"Song {line.identity}")
        _warn(
            f"The song is in wanted.txt, but the database couldn't be updated ({e}); "
            "the next `tabarr sync` or `tabarr run` adds it."
        )
        return
    if known is None:
        state = "new; the next `tabarr run` looks for it"
    else:
        status = song.status if song is not None else known.status
        state = f"already known, {_KNOWN.get(status, status)}"
    typer.echo(f"Song {line.identity}: {state}")
    for problem in stats.errors:
        _warn(problem)


def _warn(message: str) -> None:
    typer.secho(message, err=True, fg=typer.colors.YELLOW)
