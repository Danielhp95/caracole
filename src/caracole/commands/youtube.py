"""``caracole youtube``: the nightly run's YouTube step, by hand, or for one song.

Without ``--song`` it makes the same pass as the step (youtube_fetch.py): the songs with
no human sheet that are due for their audio from YouTube, newest first, within the
budget. With ``--song "Artist - Title"`` it takes that song's audio, even when its search
found nothing lately, unless it has a human sheet, is ignored or has a purchase linked;
``--url`` first writes the video to use under ``[youtube]`` in overrides.toml, and
``--none`` writes "none" there, lets go of any audio the song has from YouTube, and asks
YouTube nothing.

As the other steps' commands do, it leaves YouTube alone while it cools down after a
block; a block starts (or extends) the cooldown and sends one ntfy alert, and like a
spent budget it exits 0. It holds caracole's lock throughout. It exits 1, asking
nothing, when this caracole can't make chords of the audio (no auto-chords, no model
files) or has no yt-dlp: the download would be of no use. The chords themselves come
from ``caracole autochords``, which the caracole-autochords unit runs after each night.

Every command module is imported on every start, so the pass is imported inside the command.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from caracole.commands import _common
from caracole.commands._common import (
    exclusive,
    fail,
    load_cfg,
    load_ovr,
    make_youtube,
    open_db,
    run_id_for,
    utcnow,
    write_pages,
)

if TYPE_CHECKING:
    import sqlite3

    from caracole.config import Config
    from caracole.overrides import Overrides
    from caracole.songs import Song
    from caracole.youtube_fetch import Record, YouTubeStats

PROVIDER = "youtube"
NOT_BUILT = "use the flake's packages.autochords, which has auto-chords and yt-dlp"


def register(app: typer.Typer) -> None:
    @app.command("youtube")
    def youtube_cmd(
        ctx: typer.Context,
        song: str | None = typer.Option(
            None, "--song", metavar='"ARTIST - TITLE"',
            help="Take only this song's audio, even when its search found nothing lately.",
        ),
        url: str | None = typer.Option(
            None, "--url", metavar="URL",
            # Rich reads [...] as markup: the backslash keeps the table's name.
            help="With --song: the YouTube video to take its audio from, written under \\[youtube] in "
                 "overrides.toml.",
        ),
        none: bool = typer.Option(
            False, "--none",
            help="With --song: never take its audio from YouTube (\"none\" under \\[youtube]), and let go of any.",
        ),
    ) -> None:
        """Take the audio of songs no one has charted from YouTube (yt-dlp), for auto-chords."""
        if (url is not None or none) and song is None:
            raise typer.BadParameter("--url and --none need --song", param_hint="--url/--none")
        if url is not None and none:
            raise typer.BadParameter("either --url or --none, not both", param_hint="--url/--none")
        _youtube(load_cfg(ctx), song, url, none)


def _youtube(cfg: Config, display: str | None, url: str | None, none: bool) -> None:
    from caracole.health import get_state, is_cooling, record_block, record_ok
    from caracole.http import ProviderBlocked
    from caracole.overrides import OverridesError, add_youtube
    from caracole.youtube_fetch import route_problem, songs_for_youtube, tidy, youtube_pass

    if not cfg.provider(PROVIDER).enabled:
        typer.echo(f"YouTube is off ([providers.{PROVIDER}] enabled = false); nothing was asked.")
        return
    problem = route_problem(cfg)
    if problem is not None:
        hint = f"; {NOT_BUILT}" if "auto-chords" in problem and "built without" in problem else ""
        fail(f"caracole takes no audio from YouTube here: {problem}{hint}")
    # Under caracole's lock from the start: overrides.toml is in the library, and a run this waited
    # for may have been blocked meanwhile.
    with exclusive(cfg, "youtube"), closing(open_db(cfg)) as conn:
        if display is not None and (url is not None or none):
            try:
                add_youtube(cfg.overrides_file, display, "none" if none else url or "")
            except OverridesError as e:
                fail(f"--url: {e}", 2)
        overrides = load_ovr(cfg)
        now = utcnow()
        tidy(conn, cfg, overrides)  # lets go of audio no song needs, and of files gone from the cache
        song = _one_song(conn, cfg, display, overrides) if display else None
        if none and song is not None:
            typer.echo(f"caracole won't take {song.display}'s audio from YouTube (\"none\" under [youtube]).")
            write_pages(conn, cfg, overrides, utcnow())
            return
        if song is not None and _has_it(conn, song, overrides):
            return
        songs = [song] if song is not None else songs_for_youtube(conn, cfg, overrides, now)
        if not songs:
            typer.echo("No song is waiting for audio from YouTube.")
            return
        if is_cooling(conn, PROVIDER, now):
            until = get_state(conn, PROVIDER).cooldown_until
            typer.echo(f"YouTube is cooling down after a block until {_when(until)}; caracole won't ask it before "
                       "then.")
            return
        runner = make_youtube(cfg, conn, run_id_for(now))
        try:
            stats = youtube_pass(conn, runner, cfg, now, overrides=overrides, songs=songs,
                                 on_song=lambda s, outcome, record: typer.echo(_line(s, outcome, record)))
        except ProviderBlocked as e:
            state = record_block(conn, PROVIDER, now, str(e))
            message = (f"{e}\nNo more yt-dlp runs until {_when(state.cooldown_until)} (block #{state.strikes}). "
                       "Nothing was marked missing.")
            _alert(cfg, f"caracole: {PROVIDER} blocked", message)
            typer.echo(f"YouTube blocked caracole: {message}")
            write_pages(conn, cfg, overrides, utcnow())
            return
        finally:
            runner.close()
        if runner.requests_made:
            record_ok(conn, PROVIDER, now)
        write_pages(conn, cfg, overrides, utcnow())
    typer.echo(_totals(stats, runner.requests_made, cfg.provider(PROVIDER).budget))
    if stats.budget_exhausted:
        budget = cfg.provider(PROVIDER).budget
        typer.echo(f"YouTube's budget of {_count(budget, 'yt-dlp run')} is spent; the songs left wait for the next run.")
    if stats.downloaded:
        typer.echo("Next, `caracole autochords` works out the chords from the audio (the caracole-autochords unit "
                   "runs it after each nightly run).")


def _one_song(conn: sqlite3.Connection, cfg: Config, display: str, overrides: Overrides) -> Song:
    """The song ``--song`` names, if YouTube may be asked for its audio; otherwise say why not."""
    from caracole.overrides import OverridesError, override_key
    from caracole.songs import find_song
    from caracole.youtube_fetch import youtube_audio

    try:
        key = override_key(display)
    except OverridesError as e:
        fail(str(e), 2)
    song = find_song(conn, key)
    if song is None:
        fail(f'No song "{display}" in the library. Add it with `caracole add` first.')
    if song.status == "ignored" or key in overrides.ignore:
        fail(f'"{song.display}" is ignored in overrides.toml.')
    if conn.execute("SELECT 1 FROM files WHERE song_id = ? AND name = 'sheet.txt'", (song.id,)).fetchone():
        fail(f'"{song.display}" has a human sheet: caracole takes no audio from YouTube for it.')
    if song.audio_path and youtube_audio(conn, song) is None:  # a purchase, linked from Music/
        audio = Path(song.audio_path)
        shown = f"{audio.relative_to(cfg.music_dir)} in Music/" if audio.is_relative_to(cfg.music_dir) else audio
        fail(f'"{song.display}" has its audio already ({shown}): caracole takes none from YouTube for it.')
    return song


def _has_it(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> bool:
    """Whether the song has the audio of the video it would be given already; says so if it has."""
    from caracole.youtube_fetch import youtube_audio

    video = youtube_audio(conn, song)
    pasted = overrides.youtube.get(song.key)
    if video is None or (pasted and pasted != video.id):
        return False
    typer.echo(f"{song.display} already has the audio of {video.url}; paste another video under [youtube] "
               "(caracole youtube --song ... --url ...) to take another.")
    return True


def _line(song: Song, outcome: str, record: Record) -> str:
    from caracole.youtube_fetch import DOWNLOADED_NOW, MISSED, PASSED_OVER

    video = record.video
    if outcome == DOWNLOADED_NOW and video is not None:
        named = f"{video.title} ({video.channel})" if video.channel else video.title
        return f"{song.display}: downloaded {named}, {video.url}"
    if outcome == MISSED:
        return (f"{song.display}: no video on YouTube fits; asked again after 30 days, or paste one with "
                "--url")
    if outcome == PASSED_OVER:
        if record.unusable:
            return (f"{song.display}: the video under [youtube] can't be downloaded ({record.unusable_reason}); "
                    "paste another with --url")
        return f"{song.display}: its video can't be downloaded; the next run picks another"
    return f"{song.display}: failed ({record.error}); tried again on the next run"


def _totals(stats: YouTubeStats, runs: int, budget: int) -> str:
    return (f"YouTube: {stats.downloaded} downloaded, {stats.missing} not there, {stats.unavailable} unavailable, "
            f"{_count(stats.errors, 'error')} ({_count(runs, 'yt-dlp run')} of {budget}).")


def _alert(cfg: Config, title: str, message: str) -> None:
    """One ntfy message, as the nightly run sends on a block; nothing without an ntfy URL."""
    from caracole.notify import Notifier

    notifier = Notifier(cfg.ntfy.url, cfg.ntfy.token, transport=_common.transport_for("ntfy"))
    notifier.send(title, message, priority="high", tags=["warning"])


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _when(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "?"
