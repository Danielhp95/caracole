"""Source commands: ``caracole add``, ``caracole sync`` and ``caracole auth spotify``.

wanted.txt is the source that always works. Spotify is optional, and no Spotify
failure makes ``caracole sync`` fail. ``add_song`` is the one way a command adds
a song: ``caracole add`` and ``caracole search --add`` both call it, and each says
in its own words what it did. With ``--lacuerda`` (a LaCuerda song you picked, as
``caracole search --add`` and caracole serve's Add for tonight's run pick one), the
pick goes under ``[lacuerda]`` in overrides.toml too, for the nightly run to keep. It also matches the song against the offline
index at once, as the nightly match step would, so a name that isn't quite
UG's is a review you can settle now ("Did you mean", ``match_lines``). A sync,
an add's too, then rewrites _todo.md and index.html. Every command module is
imported on every start, so spotipy, the matcher and the source modules are
imported inside the commands.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing, nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer

from caracole import db
from caracole.commands._common import LOCK_NAME, exclusive, fail, load_cfg, open_db, utcnow, warn, write_pages

if TYPE_CHECKING:
    from pathlib import Path

    from caracole.config import Config
    from caracole.match import MatchResult
    from caracole.overrides import Overrides
    from caracole.songs import RemovedSong, Song
    from caracole.spotify import SpotifyAPI
    from caracole.wanted import WantedLine

# What `caracole auth spotify` says when there's no client id (docs/usage.md, "Spotify (optional)").
_SPOTIFY_SETUP = """\
Spotify isn't set up. It's optional: wanted.txt works without it.
To add your Liked Songs and playlists:
1. Create an app at https://developer.spotify.com/dashboard, with the redirect URI
   {redirect}
2. Add its client id to {config}:
     [spotify]
     client_id = "your-app-client-id"
     playlists = ["Learn"]   # names, ids or links of playlists you own
3. Give caracole the app's client secret: $CREDENTIALS_DIRECTORY/spotify_client_secret,
   a file named by [spotify] client_secret_file, or $CARACOLE_SPOTIFY_CLIENT_SECRET.
4. Run `caracole auth spotify` again.
On NixOS, set services.caracole.settings.spotify and credentials.spotify_client_secret
instead (docs/deploy.md, section 5)."""
_DEFAULT_CONFIG = "caracole.toml (~/.config/caracole/caracole.toml, unless --config names another)"

log = logging.getLogger(__name__)

# How `caracole add` describes a song the library already had, by its status.
_KNOWN = {"wanted": "with no sheet yet", "found": "with a sheet", "ignored": "ignored by overrides.toml"}


def register(app: typer.Typer) -> None:
    auth = typer.Typer(help="Authorize caracole to read an account of yours.", no_args_is_help=True)
    app.add_typer(auth, name="auth")

    @auth.command("spotify")
    def auth_spotify_cmd(ctx: typer.Context) -> None:
        """Let caracole read your Spotify Liked Songs and playlists (optional)."""
        config_path = ctx.obj.config_path if ctx.obj is not None else None
        _auth_spotify(load_cfg(ctx), config_path)

    @app.command("add")
    def add_cmd(
        ctx: typer.Context,
        artist: str = typer.Argument(
            ..., help='The artist, as you\'d write it; or the whole song, as "ARTIST - TITLE".'
        ),
        title: str | None = typer.Argument(None, help="The song's title."),
        album: str | None = typer.Option(
            None, "--album", help="The album; it makes the lyrics lookup exact."
        ),
        duration: str | None = typer.Option(
            None,
            "--duration",
            metavar="M:SS",
            help="The length, as m:ss or whole seconds; it also makes the lookup exact.",
        ),
        lacuerda: str | None = typer.Option(
            None, "--lacuerda", metavar="URL",
            help="The LaCuerda song (its page's address) or version (its sheet's) whose sheet the nightly run "
                 "keeps; recorded under \\[lacuerda] in overrides.toml.",
        ),
    ) -> None:
        """Add a song to wanted.txt, then sync wanted.txt into the library."""
        duration_ms = _duration_ms(duration)
        _lacuerda_pick(lacuerda)
        cfg = load_cfg(ctx)
        if title is None:  # one text: "Artist - Title", else one name, which names no song
            artist, sep, title = artist.partition(" - ")
            if not sep and not any(c.isalnum() for c in artist):
                fail("can't add this song: a song needs an artist and a title", 2)
            if not sep:
                from caracole.commands.search import offer_songs

                offer_songs(cfg, " ".join(artist.split()), "add")
        _add(cfg, artist, title, album, duration_ms, lacuerda)

    @app.command("sync")
    def sync_cmd(ctx: typer.Context) -> None:
        """Add new songs from wanted.txt and, when it's set up, from Spotify."""
        _sync(load_cfg(ctx))


# --- caracole auth spotify --------------------------------------------------------------------


def _auth_spotify(cfg: Config, config_path: Path | None) -> None:
    """Authorize by pasting back the redirect, or say how to set Spotify up; exit 1 on failure."""
    if not cfg.spotify.enabled:
        setup = _SPOTIFY_SETUP.format(
            redirect=cfg.spotify.redirect_uri, config=config_path or _DEFAULT_CONFIG
        )
        typer.echo(setup, err=True)
        raise typer.Exit(1)
    from caracole.spotify import SpotifyAuthError, SpotifyError, authorize, make_auth

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
    typer.echo("Run `caracole sync` to read your Spotify songs now, or leave it to the nightly run.")


# --- caracole sync ----------------------------------------------------------------------------


def _sync(cfg: Config) -> None:
    """Sync every source, print the summary and each problem; Spotify never fails it."""
    from caracole.sources import sync_sources

    with exclusive(cfg, "sync"), closing(open_db(cfg)) as conn:
        spotify = _spotify_client(cfg)  # it may refresh the token in the state folder
        report = sync_sources(conn, cfg, utcnow(), spotify=spotify)
        _write_pages(conn, cfg, _page_overrides(cfg))
    typer.echo(report.summary())
    for problem in report.wanted.errors:
        warn(problem)
    if report.spotify_state == "auth_needed" and report.spotify_message:
        warn(f"Spotify: {report.spotify_message}")
    if report.spotify_state == "off" and not cfg.wanted_file.exists():
        typer.echo(f"No {cfg.wanted_file} yet: `caracole add ARTIST TITLE` creates it.")


def _spotify_client(cfg: Config) -> SpotifyAPI | None:
    """The Spotify client, or None; as in the nightly run, no failure here stops the sync.

    A SpotifyError is left for ``sync_sources`` to explain, so it's said once.
    """
    if not cfg.spotify.enabled:
        return None
    from caracole.spotify import SpotifyError, client_from_config

    try:
        return client_from_config(cfg)
    except SpotifyError:
        return None
    except Exception as e:  # noqa: BLE001 (Spotify is optional: nothing it raises stops the sync)
        warn(f"Spotify unavailable: {type(e).__name__}: {e}")
        return None


# --- caracole add -----------------------------------------------------------------------------


def _lacuerda_pick(url: str | None) -> None:
    """``--lacuerda``'s address, checked before anything is written: a usage error for any other."""
    if url is None:
        return
    from caracole.overrides import OverridesError, lacuerda_pick_from_url

    try:
        lacuerda_pick_from_url(url)
    except OverridesError as e:
        fail(f"--lacuerda: {e}", 2)


def _duration_ms(text: str | None) -> int | None:
    """``--duration`` in milliseconds; a value that isn't a duration exits with status 2."""
    if text is None:
        return None
    from caracole.wanted import parse_duration

    try:
        ms = parse_duration(text)
    except ValueError as e:
        fail(f"--duration: {e}", 2)
    if ms is None:
        fail(f"--duration: {text.strip()!r} isn't a duration: write m:ss, h:mm:ss or seconds", 2)
    return ms


@dataclass(frozen=True)
class AddedMatch:
    """What ``add_song`` found for the song in the offline UG index.

    ``index`` is the index's state (``ug.index.index_state``); ``result`` the
    match, None when the index is empty. ``pages`` has the page of each
    candidate's oldest tab, as ``caracole review`` shows it (None for one the
    index has no tab of).
    """

    index: str
    result: MatchResult | None = None
    pages: tuple[str | None, ...] = ()


@dataclass(frozen=True)
class AddedSong:
    """What ``add_song`` did, for the command to put in its own words.

    ``line`` is the song's line as wanted.txt now holds it, and ``listed`` says
    the file had it already and was left as it was. ``known`` is the library's
    record of the song before the sync (None for a song new to the library) and
    ``song`` the record after it. ``problems`` are the lines of wanted.txt the
    sync couldn't read. ``db_error`` says why the database couldn't be updated;
    the line is in the file all the same, and the next sync adds the song.
    ``match`` is what the offline index says of the song (None when
    overrides.toml can't be read: the match waits for it, as the pages do).
    ``removed`` is the tombstone of a song ``caracole remove`` took out, which
    the line brought back.
    """

    line: WantedLine
    listed: bool
    known: Song | None = None
    song: Song | None = None
    problems: tuple[str, ...] = ()
    db_error: Exception | None = None
    match: AddedMatch | None = None
    removed: RemovedSong | None = None
    lacuerda: str | None = None  # the LaCuerda pick recorded for it


def add_song(
    cfg: Config,
    artist: str,
    title: str,
    album: str | None = None,
    duration_ms: int | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    lacuerda: str | None = None,
) -> AddedSong:
    """Append a song to wanted.txt unless it's listed, then sync wanted.txt into the library.

    ``lacuerda`` is the LaCuerda song or version picked for it, recorded under ``[lacuerda]`` once the
    line is written (overrides.toml that can't be written exits with status 1), and asked for at the
    next LaCuerda pass, however lately LaCuerda answered for the song.

    A song the file can't hold exits with status 2, and a file that can't be
    written with status 1. The file is the source of truth, so a database that
    can't be opened or updated is no failure: it's reported in ``db_error``.
    ``conn`` is the caller's open database; without one, it's opened here. The
    line is written at once; the database, and the pick, wait for caracole's lock (a lock file that
    can't be opened exits with status 1 when there is a pick to write). After the
    sync, the song is matched against the offline index (``_match_added``), and
    _todo.md and index.html are rewritten (``_write_pages``).
    """
    from caracole.songs import find_song, removed_song
    from caracole.wanted import append_wanted, find_wanted, sync_wanted

    path = cfg.wanted_file
    try:
        listed = find_wanted(path, artist, title) is not None
        line = append_wanted(path, artist, title, album, duration_ms)
    except ValueError as e:  # a song the file can't hold, such as an artist with " - " in it
        fail(f"can't add this song: {e}", 2)
    except OSError as e:
        fail(f"can't update {path}: {e.strerror or e}")
    pick = None
    try:
        with exclusive(cfg, "add", fatal=False):
            # overrides.toml is in the library: the pick is written under the lock, as its other writers do.
            pick = _record_lacuerda(cfg, line, lacuerda) if lacuerda is not None else None
            with nullcontext(conn) if conn is not None else closing(db.connect(cfg.db_path)) as conn:
                known = find_song(conn, line.identity)
                removed = removed_song(conn, line.identity)
                stats = sync_wanted(conn, path, utcnow())
                song = find_song(conn, line.identity)
                if pick is not None and song is not None and song.lacuerda_checked_at is not None:
                    from caracole.songs import update_song

                    update_song(conn, song.id, lacuerda_checked_at=None)  # a new pick is asked for at once
                overrides = _page_overrides(cfg)
                match = _match_added(conn, cfg, song, overrides) if song is not None else None
                if match is not None and match.result is not None:
                    song = find_song(conn, line.identity)
                _write_pages(conn, cfg, overrides)
    except (sqlite3.Error, OSError) as e:
        if lacuerda is not None and pick is None:  # no lock: the pick is never written without it
            fail(f"the song is in wanted.txt, but its LaCuerda pick can't be recorded in overrides.toml without "
                 f"caracole's lock: can't open {cfg.state_dir / LOCK_NAME}: {e.strerror or e}")
        return AddedSong(line, listed, db_error=e, lacuerda=pick)
    return AddedSong(line, listed, known, song, tuple(stats.errors), match=match, removed=removed, lacuerda=pick)


def _record_lacuerda(cfg: Config, line: WantedLine, url: str) -> str:
    """The LaCuerda pick under ``[lacuerda]``, by the song's line; its address as written."""
    from caracole.overrides import OverridesError, add_lacuerda, lacuerda_pick_from_url

    try:
        add_lacuerda(cfg.overrides_file, f"{line.artist} - {line.title}", url)
    except (OverridesError, OSError) as e:
        fail(f"the song is in wanted.txt, but its LaCuerda pick can't be recorded in overrides.toml: {e}")
    return lacuerda_pick_from_url(url).url


def _match_added(
    conn: sqlite3.Connection, cfg: Config, song: Song, overrides: Overrides | None
) -> AddedMatch | None:
    """Match the song just added against the offline index, and save it, as the nightly match step would.

    Nothing is matched without overrides.toml (None), nor against an empty index. A partial
    one records no miss (``match.match_all``): a song in the sitemaps not read yet isn't missing.
    """
    from caracole.match import match_all
    from caracole.ug.index import index_state
    from caracole.review import candidate_page

    if overrides is None:
        return None
    state = index_state(conn)
    if state == "empty":
        return AddedMatch(state)
    [change] = match_all(conn, overrides, cfg.match, song_ids={song.id})
    pages = [candidate_page(conn, c.artist_key, c.song_key) for c in change.new.candidates]
    return AddedMatch(state, change.new, tuple(pages))


def match_lines(match: AddedMatch | None, *, lacuerda: str | None = None) -> list[str]:
    """What the offline index says of a song just added: the UG song it matched, the candidates of a
    review ("Did you mean"), or that it has nothing under that name, which for a song picked on LaCuerda
    (``lacuerda``) is no matter."""
    if match is None:
        return []
    if lacuerda is not None and match.result is not None and match.result.decision == "not_found":
        index = ("The part of Ultimate Guitar's offline index read so far has" if match.index == "partial"
                 else "Ultimate Guitar's offline index has")
        return [f"{index} no song of theirs by this name; the sheet is the one you picked on LaCuerda."]
    if match.result is None:
        return ["The offline index is empty: run `caracole index build` once (about 10 minutes), and the "
                "song can be matched."]
    r = match.result
    if r.decision in ("accept", "pinned"):
        target = f"{r.artist_key}/{r.song_key}" if r.artist_key and r.song_key else "tabs " + ", ".join(
            str(t) for t in r.pinned)
        return [f"On Ultimate Guitar: {target} ({r.step})"]
    if r.decision == "review":
        lines = ["Not sure which Ultimate Guitar song it is. Did you mean:"]
        for n, (c, page) in enumerate(zip(r.candidates, match.pages, strict=True), start=1):
            lines.append(f"  {n}) {float(c.score or 0):.0f}  {c.artist_key}/{c.song_key} ({c.step})"
                         + (f"  {page}" if page else ""))
        return [*lines, "Pick one with `caracole review`, or on _todo.md."]
    if r.decision == "not_found" and match.index == "partial":
        return ["The offline index is incomplete (a build stopped before it read every sitemap), and the "
                "part read so far hasn't the song: the nightly refresh reads the rest."]
    if r.decision == "not_found":
        return ["Not in the offline Ultimate Guitar index under this name: `caracole search` with a few of its "
                "words looks wider."]
    return []


def _page_overrides(cfg: Config) -> Overrides | None:
    """overrides.toml, which the pages need (ignored songs, transpositions), and so does an add's
    match; a sync doesn't. None, with a warning, when it can't be read."""
    from caracole.overrides import OverridesError, load_overrides

    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError as e:
        warn(f"overrides: {e}\n_todo.md and index.html are left as they were until it's fixed.")
        return None


def _write_pages(conn: sqlite3.Connection, cfg: Config, overrides: Overrides | None) -> None:
    """Rewrite _todo.md and index.html for the songs just synced.

    The pages need overrides.toml and a library folder caracole can write.
    wanted.txt always works, so without either (``overrides`` None) the pages
    are left as they are, with a warning, and the sync fails nothing.
    """
    if overrides is not None:
        write_pages(conn, cfg, overrides, utcnow(), fatal=False)


def _add(cfg: Config, artist: str, title: str, album: str | None, duration_ms: int | None,
         lacuerda: str | None = None) -> None:
    """Add the song with ``add_song``, then say what was done (``say_added``), and when its artist is
    a placeholder such as "misc", that nothing can be found by it."""
    from caracole.normalize import placeholder_artist

    say_added(cfg, add_song(cfg, artist, title, album, duration_ms, lacuerda=lacuerda), album, duration_ms)
    if placeholder_artist(artist):
        name = " ".join(title.split())
        warn(f'"{" ".join(artist.split())}" is no one\'s name, and caracole looks a song up by its artist: '
              f'it may never find this one. If you don\'t know the artist, caracole search "{name}" lists the '
              "songs of that title with theirs; then write the artist into its line in wanted.txt.")


def say_added(cfg: Config, added: AddedSong, album: str | None = None, duration_ms: int | None = None) -> None:
    """Say in a line what ``add_song`` did and what the library has of the song: ``caracole add``'s
    words, and ``caracole search --add``'s.

    -v adds its line in wanted.txt, where the file is, and the song's key. ``album``
    and ``duration_ms`` are what was asked for, which a listed line may lack.
    """
    from caracole.wanted import format_line

    line, path = added.line, cfg.wanted_file
    name = f"{line.artist} - {line.title}"
    done = f"{name} is in wanted.txt already" if added.listed else f"Added {name} to wanted.txt"
    log.info("wanted.txt line %d (%s): %s", line.line_no, path,
             format_line(line.artist, line.title, line.album, line.duration_ms))
    if added.db_error is not None:
        typer.echo(f"{done}.")
        log.info("Song %s", line.identity)
        warn(
            f"The song is in wanted.txt, but the database couldn't be updated ({added.db_error}); "
            "the next `caracole sync` or `caracole run` adds it."
        )
        return
    if added.known is None and added.removed is not None and added.song is not None:
        when = added.removed.removed_at[:10]
        state = f"back from its removal on {when}, as new; the next `caracole run` looks for it"
        known = f"new, back from its removal on {when}"
    elif added.known is None:
        state, known = "the next `caracole run` looks for it", "new"
    else:
        status = (added.song or added.known).status
        state, known = f"the library has it, {_KNOWN.get(status, status)}", f"already known, {status}"
    typer.echo(f"{done}; {state}.")
    if added.listed and _would_change(line, album, duration_ms):
        typer.echo("Its line stays as it is: edit it to change the album or the duration.")
    log.info("Song %s: %s", line.identity, known)
    if added.lacuerda is not None:
        typer.echo(f"LaCuerda: the nightly run keeps the sheet you picked there ({added.lacuerda}), recorded "
                   "under [lacuerda] in overrides.toml.")
    for text in match_lines(added.match, lacuerda=added.lacuerda):
        typer.echo(text)
    for problem in added.problems:
        warn(problem)


def _would_change(line: WantedLine, album: str | None, duration_ms: int | None) -> bool:
    """Whether the album or duration given differs from what the listed line says."""
    from caracole.wanted import format_line

    asked = format_line(
        line.artist,
        line.title,
        album if album and album.strip() else line.album,
        line.duration_ms if duration_ms is None else duration_ms,
    )
    return asked != format_line(line.artist, line.title, line.album, line.duration_ms)
