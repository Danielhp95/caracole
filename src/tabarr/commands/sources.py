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
    from pathlib import Path

    from tabarr.config import Config
    from tabarr.spotify import SpotifyAPI
    from tabarr.wanted import WantedLine

# What `tabarr auth spotify` says when there's no client id (docs/usage.md, section 2).
_SPOTIFY_SETUP = """\
Spotify isn't set up. It's optional: wanted.txt works without it.
To add your Liked Songs and playlists:
1. Create an app at https://developer.spotify.com/dashboard, with the redirect URI
   {redirect}
2. Add its client id to {config}:
     [spotify]
     client_id = "your-app-client-id"
     playlists = ["Learn"]   # names, ids or links of playlists you own
3. Give tabarr the app's client secret: $CREDENTIALS_DIRECTORY/spotify_client_secret,
   a file named by [spotify] client_secret_file, or $TABARR_SPOTIFY_CLIENT_SECRET.
4. Run `tabarr auth spotify` again.
On NixOS, set services.tabarr.settings.spotify and credentials.spotify_client_secret
instead (docs/deploy.md, section 5)."""
_DEFAULT_CONFIG = "tabarr.toml (~/.config/tabarr/tabarr.toml, unless --config names another)"

# How `tabarr add` describes a song the library already had, by its status.
_KNOWN = {"wanted": "no sheet yet", "found": "has a sheet", "ignored": "ignored"}


def register(app: typer.Typer) -> None:
    auth = typer.Typer(help="Authorize tabarr to read an account of yours.", no_args_is_help=True)
    app.add_typer(auth, name="auth")

    @auth.command("spotify")
    def auth_spotify_cmd(ctx: typer.Context) -> None:
        """Let tabarr read your Spotify Liked Songs and playlists (optional)."""
        config_path = ctx.obj.config_path if ctx.obj is not None else None
        _auth_spotify(load_cfg(ctx), config_path)

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

    @app.command("sync")
    def sync_cmd(ctx: typer.Context) -> None:
        """Add new songs from wanted.txt and, when it's set up, from Spotify."""
        _sync(load_cfg(ctx))


# --- tabarr auth spotify --------------------------------------------------------------------


def _auth_spotify(cfg: Config, config_path: Path | None) -> None:
    """Authorize by pasting back the redirect, or say how to set Spotify up; exit 1 on failure."""
    if not cfg.spotify.enabled:
        setup = _SPOTIFY_SETUP.format(
            redirect=cfg.spotify.redirect_uri, config=config_path or _DEFAULT_CONFIG
        )
        typer.echo(setup, err=True)
        raise typer.Exit(1)
    from tabarr.spotify import SpotifyAuthError, SpotifyError, authorize, make_auth

    try:
        authorize(
            make_auth(cfg.spotify, cfg.state_dir),
            read=lambda prompt: typer.prompt(prompt, prompt_suffix=""),
            write=typer.echo,
        )
    except SpotifyAuthError as e:  # its message says to run this very command: leave that out
        fail(f"Spotify authorization failed: {e.problem.rstrip('.')}.")
    except SpotifyError as e:
        fail(str(e))
    typer.echo("Run `tabarr sync` to read your Spotify songs now, or leave it to the nightly run.")


# --- tabarr sync ----------------------------------------------------------------------------


def _sync(cfg: Config) -> None:
    """Sync every source, print the summary and each problem; Spotify never fails it."""
    from tabarr.sources import sync_sources

    spotify = _spotify_client(cfg)
    with closing(open_db(cfg)) as conn:
        report = sync_sources(conn, cfg, utcnow(), spotify=spotify)
    typer.echo(report.summary())
    for problem in report.wanted.errors:
        _warn(problem)
    if report.spotify_state == "auth_needed" and report.spotify_message:
        _warn(f"Spotify: {report.spotify_message}")
    if report.spotify_state == "off" and not cfg.wanted_file.exists():
        typer.echo(f"No {cfg.wanted_file} yet: `tabarr add ARTIST TITLE` creates it.")


def _spotify_client(cfg: Config) -> SpotifyAPI | None:
    """The Spotify client, or None; as in the nightly run, no failure here stops the sync.

    A SpotifyError is left for ``sync_sources`` to explain, so it's said once.
    """
    if not cfg.spotify.enabled:
        return None
    from tabarr.spotify import SpotifyError, client_from_config

    try:
        return client_from_config(cfg)
    except SpotifyError:
        return None
    except Exception as e:  # noqa: BLE001 (Spotify is optional: nothing it raises stops the sync)
        _warn(f"Spotify unavailable: {type(e).__name__}: {e}")
        return None


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
