"""``caracole youtube``: the nightly run's YouTube step, by hand, or for one song.

Without ``--song`` it makes the same pass as the step (youtube_fetch.py): the songs with
no human sheet that are due for their audio from YouTube, newest first, within the
budget. With ``--song "Artist - Title"`` it takes that song's audio, even when its search
found nothing lately, unless it has a human sheet, is ignored or has a purchase linked;
``--url`` first writes the video to use under ``[youtube]`` in overrides.toml, and
``--none`` writes "none" there, lets go of any audio the song has from YouTube, and asks
YouTube nothing: it does so with YouTube off too, and for a song not in the library yet.
Audio let go of with nothing to download (a human sheet came, a file is gone) rewrites
the pages all the same.

As the other steps' commands do, it leaves YouTube alone while it cools down after a
block; a block starts (or extends) the cooldown and sends one ntfy alert, and like a
spent budget it exits 0. It holds caracole's lock throughout. It exits 1, asking
nothing, when this caracole can't make chords of the audio (no auto-chords, no model
files) or has no yt-dlp: the download would be of no use. The chords themselves come
from ``caracole autochords``, which the caracole-autochords unit runs after each night.

``--song "Artist - Title" --sheet`` makes that song's auto sheet now, as caracole serve's sheet from a
YouTube video does (youtube_sheet.py): the song added to wanted.txt if it isn't in the library, the video
(``--url``, else the one under ``[youtube]``, else its search's pick) written there and its audio taken,
its lyrics from LRCLIB, the chords from the audio, its PDF and viewer, then the pages; ``--progress`` adds a
JSON line per stage, which caracole serve reads, as ``caracole get --progress`` does. It exits 0 once the
sheet is made, and for a block, a cooldown, a spent budget or a site's error, which wait; 1 for a song it
won't make a sheet of, a video YouTube won't give, audio auto-chords can't read, or a caracole that can't
make chords of the audio, which it says before it asks anything.

Every command module is imported on every start, so the pass is imported inside the command.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from caracole.commands import _common
from caracole.commands._common import (
    exclusive,
    fail,
    load_cfg,
    load_ovr,
    make_client,
    make_youtube,
    open_db,
    run_id_for,
    song_named,
    utcnow,
    write_pages,
)
from caracole.logs import plural
from caracole.stamps import shown

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from datetime import datetime

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
        sheet: bool = typer.Option(
            False, "--sheet",
            help="With --song: make its auto sheet now, the song added to the library if it isn't there: the "
                 "audio, the lyrics from LRCLIB, the chords from the audio, the PDF and the viewer.",
        ),
        progress: bool = typer.Option(False, "--progress", help="With --sheet or --search: a JSON line per stage "
                                                                "too, for caracole serve."),
        search: str | None = typer.Option(
            None, "--search", metavar="QUERY",
            help="YouTube's first video for the query (one yt-dlp run, no download) and its thumbnail, kept for "
                 "caracole serve to suggest.",
        ),
        video: str | None = typer.Option(
            None, "--video", metavar="URL|ID",
            help="A YouTube video's title, channel and length (one yt-dlp run, no download) and its thumbnail, kept "
                 "for caracole serve to name a pasted link's song.",
        ),
    ) -> None:
        """Take the audio of songs no one has charted from YouTube (yt-dlp), for auto-chords."""
        if search is not None or video is not None:
            if song is not None or url is not None or none or sheet or (search is not None and video is not None):
                raise typer.BadParameter("--search and --video go alone", param_hint="--search/--video")
            if search is not None:
                _search(load_cfg(ctx), " ".join(search.split()), progress=progress)
            else:
                _video(load_cfg(ctx), video or "", progress=progress)
            return
        if (url is not None or none or sheet) and song is None:
            raise typer.BadParameter("--url, --none and --sheet need --song", param_hint="--song")
        if url is not None and none:
            raise typer.BadParameter("either --url or --none, not both", param_hint="--url/--none")
        if sheet and none:
            raise typer.BadParameter("either --sheet or --none, not both", param_hint="--sheet/--none")
        if progress and not sheet:
            raise typer.BadParameter("--progress goes with --sheet, --search or --video", param_hint="--progress")
        if sheet:
            _sheet(load_cfg(ctx), song or "", url, progress=progress)
            return
        _youtube(load_cfg(ctx), song, url, none)


def _youtube(cfg: Config, display: str | None, url: str | None, none: bool) -> None:
    from caracole.health import answered_any, get_state, is_cooling, record_block, record_ok
    from caracole.http import ProviderBlocked
    from caracole.overrides import OverridesError, add_youtube
    from caracole.youtube_fetch import route_problem, songs_for_youtube, tidy, youtube_pass

    if none and display is not None:  # asks YouTube nothing: written even with YouTube off
        _decline(cfg, display)
        return
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
        if display is not None and url is not None:
            try:
                add_youtube(cfg.overrides_file, display, url)
            except OverridesError as e:
                fail(f"--url: {e}", 2)
        overrides = load_ovr(cfg)
        now = utcnow()
        tidied = tidy(conn, cfg, overrides)  # lets go of audio no song needs, and of files gone from the cache
        song = _one_song(conn, cfg, display, overrides) if display else None
        songs = [song] if song is not None else songs_for_youtube(conn, overrides, now)
        if song is not None and _has_it(conn, song, overrides):
            songs = []
        elif not songs:
            typer.echo("No song is waiting for audio from YouTube.")
        elif is_cooling(conn, PROVIDER, now):
            until = get_state(conn, PROVIDER).cooldown_until
            typer.echo(f"YouTube is cooling down after a block until {shown(until)}; caracole won't ask it before "
                       "then.")
            songs = []
        if not songs:
            if tidied:  # audio let go of: the pages say so
                write_pages(conn, cfg, overrides, utcnow())
            return
        run_id = run_id_for(now)
        handed = _common.handoffs()  # the runner's first pause may let a lookup go first too
        runner = make_youtube(cfg, conn, run_id)
        try:
            stats = youtube_pass(conn, runner, cfg, now, overrides=overrides, songs=songs,
                                 on_song=lambda s, outcome, record: typer.echo(_line(s, outcome, record)))
        except ProviderBlocked as e:
            state = record_block(conn, PROVIDER, now, str(e))
            message = (f"{e}\nNo more yt-dlp runs until {shown(state.cooldown_until)} (block #{state.strikes}). "
                       "Nothing was marked missing.")
            _common.alert_block(cfg, PROVIDER, message)
            typer.echo(f"YouTube blocked caracole: {message}")
            write_pages(conn, cfg, _common.overrides_since(cfg, overrides, handed), utcnow())
            return
        finally:
            runner.close()
        if answered_any(conn, run_id, PROVIDER, runner.requests_made):  # runs that all failed are no good run
            record_ok(conn, PROVIDER, now)
        write_pages(conn, cfg, _common.overrides_since(cfg, overrides, handed), utcnow())
    typer.echo(_totals(stats, runner.requests_made, cfg.provider(PROVIDER).budget))
    if stats.budget_exhausted:
        budget = cfg.provider(PROVIDER).budget
        typer.echo(f"YouTube's budget of {plural(budget, 'yt-dlp run')} is spent; the songs left wait for the next run.")
    if stats.downloaded:
        typer.echo("Next, `caracole autochords` works out the chords from the audio (the caracole-autochords unit "
                   "runs it after each nightly run).")


def _sheet(cfg: Config, display: str, url: str | None, *, progress: bool) -> None:
    """``--sheet``: the song's auto sheet now (youtube_sheet.py), said a stage a line, as ``caracole get`` says
    its own; nothing is asked when this caracole can't make chords of the audio."""
    from caracole.commands.get import _Lines
    from caracole.overrides import OverridesError, override_key
    from caracole.youtube_fetch import route_problem
    from caracole.youtube_sheet import SheetRequest, make_sheet

    try:
        override_key(display)
    except OverridesError as e:
        fail(str(e), 2)
    problem = route_problem(cfg)
    if problem is not None:
        hint = f"; {NOT_BUILT}" if "auto-chords" in problem and "built without" in problem else ""
        fail(f"caracole makes no sheet from YouTube here: {problem}{hint}")
    artist, _, title = display.partition(" - ")
    reporter = _Lines(cfg.library_dir, show=False, json_lines=progress)
    result = make_sheet(cfg, SheetRequest(artist.strip(), title.strip(), url), reporter)
    reporter.flush()
    sent = ", ".join(f"{plural(n, 'yt-dlp run') if p == PROVIDER else plural(n, 'LRCLIB request')}"
                     for p, n in result.requests.items() if n)
    if result.refused:
        typer.echo(f"No sheet made: {result.refused}.")
    else:
        typer.echo(f"Done in {result.seconds:.1f} s" + (f": {sent}." if sent else ", asking nothing."))
    if progress:
        typer.echo(reporter.event({"done": {"seconds": round(result.seconds, 3), "requests": result.requests,
                                            "ok": result.ok, "refused": result.refused}}))
    if not result.ok:
        raise typer.Exit(1)


NOT_SEARCHED = "Not searched: "


def _search(cfg: Config, query: str, *, progress: bool) -> None:
    """``--search``: YouTube's first video for ``query`` and its thumbnail (youtube_search.py), as caracole serve's
    library page asks for them. Its last line starts with what came of it, which the request's line shows
    (web/status.py): "Searched: " (the video, found now or within 30 days), "Nothing found: " or "Not searched: "
    (no word, no sheet from YouTube here, a cooldown, the hour's searches spent, a search that failed lately, a
    block, a spent budget, or an error, which is remembered for an hour). It exits 0 but for a bug."""
    from contextlib import closing
    from dataclasses import replace

    from caracole.get import progress_line
    from caracole.health import answered_any, record_block, record_error, record_ok
    from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
    from caracole.youtube_fetch import route_problem
    from caracole.youtube_search import (
        RUN,
        query_key,
        record_failure,
        search,
    )
    from caracole.youtube_search import gate as search_gate

    shown_query = f"“{query}”"

    def say(stage: str, state: str, detail: str = "") -> None:
        if progress:
            typer.echo(progress_line({"stage": stage, "state": state, "detail": detail}))

    def end(line: str, state: str = "skipped") -> None:
        say("video", state, line)
        typer.echo(line)

    if not query_key(query):
        end(f"{NOT_SEARCHED}{shown_query} has no word to search for.")
        return
    problem = route_problem(cfg)
    if problem is not None:
        end(f"{NOT_SEARCHED}no sheet from YouTube here ({problem}).")
        return
    say("video", "running", "asking YouTube")
    with exclusive(cfg, f"youtube --search {query}"), closing(open_db(cfg)) as conn:
        now = utcnow()
        said = search_gate(cfg, conn, query, on_screen=False, now=now)
        if said is not None and said.asked is not None:
            video = said.asked.get("video")
            if isinstance(video, dict):
                end(f"Searched: YouTube's first video for {shown_query} is {video.get('title')} "
                    f"({video.get('channel')}), {video.get('url')}.", "done")
            else:
                end(f"Nothing found: YouTube had no video for {shown_query} lately.", "done")
            return
        if said is None or said.state in ("spent", "failed"):
            end(f"{NOT_SEARCHED}{said.why if said else 'nothing to search for'}; try again later.")
            return
        run_id = RUN + run_id_for(now)
        runner = make_youtube(cfg, conn, run_id)
        runner.policy = replace(runner.policy, budget=1)  # one run: the search
        try:
            found = search(conn, runner, query, now)
        except ProviderBlocked as e:
            state = record_block(conn, PROVIDER, now, str(e))
            message = f"{e}\nNo more yt-dlp runs until {shown(state.cooldown_until)} (block #{state.strikes})."
            _common.alert_block(cfg, PROVIDER, message)
            end(f"{NOT_SEARCHED}YouTube blocked caracole ({e}); no more yt-dlp runs until "
                f"{shown(state.cooldown_until)}.")
            return
        except BudgetExhausted:
            end(f"{NOT_SEARCHED}YouTube's budget is spent; try again later.")
            return
        except ProviderError as e:
            record_error(conn, PROVIDER, now, str(e))
            record_failure(conn, query_key(query), now, str(e.message or e))
            end(f"{NOT_SEARCHED}yt-dlp failed ({e.message or e}); try again later.")
            return
        finally:
            runner.close()
        if answered_any(conn, run_id, PROVIDER, runner.requests_made):
            record_ok(conn, PROVIDER, now)
        if found is None:
            end(f"Nothing found: YouTube has no video for {shown_query}.", "done")
            return
        say("video", "done", f"{found.title} ({found.channel})")
        _thumbnail(cfg, conn, found.id, query_key(query), run_id, now, say)
    typer.echo(f"Searched: YouTube's first video for {shown_query} is {found.title} ({found.channel}), {found.url}.")


def _video(cfg: Config, link: str, *, progress: bool) -> None:
    """``--video``: a pasted YouTube video's title, channel and length (one yt-dlp run, no download) and its
    thumbnail (youtube_search.read_video), as caracole serve's library page asks for them to name the song of a link
    pasted into its search box. Its last line starts as ``--search``'s does: "Searched: " (now, or within 30 days),
    "Nothing found: " (a video YouTube won't give) or "Not searched: " (no sheet from YouTube here, a cooldown, the
    hour's lookups spent, a failure lately, a block, a spent budget, or an error). It exits 0 but for a bug, or 2 for
    a link that is no YouTube video's."""
    from contextlib import closing
    from dataclasses import replace

    from caracole.get import progress_line
    from caracole.health import answered_any, record_block, record_error, record_ok
    from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
    from caracole.youtube_search import RUN, read_video, record_failure, video_gate, video_key
    from caracole.youtube_urls import VIDEO_ID, video_id_from_url

    video_id = link.strip() if VIDEO_ID.fullmatch(link.strip()) else video_id_from_url(link)  # an id, as jobs pass it
    if video_id is None:
        fail(f"--video: not a YouTube video's link: {link!r}", 2)
    key = video_key(video_id)

    def say(stage: str, state: str, detail: str = "") -> None:
        if progress:
            typer.echo(progress_line({"stage": stage, "state": state, "detail": detail}))

    def end(line: str, state: str = "skipped") -> None:
        say("video", state, line)
        typer.echo(line)

    say("video", "running", "asking YouTube")
    with exclusive(cfg, f"youtube --video {video_id}"), closing(open_db(cfg)) as conn:
        now = utcnow()
        said = video_gate(cfg, conn, video_id, now)
        if said.asked is not None:
            found = said.asked.get("video")
            if isinstance(found, dict):
                end(f"Searched: YouTube's video {video_id} is {found.get('title')} ({found.get('channel')}).", "done")
            else:
                end(f"Nothing found: YouTube won't give video {video_id} ({said.asked.get('unavailable')}).", "done")
            return
        if said.state != "auto":
            end(f"{NOT_SEARCHED}{said.why}; try again later.")
            return
        run_id = RUN + key + ":" + run_id_for(now)
        runner = make_youtube(cfg, conn, run_id)
        runner.policy = replace(runner.policy, budget=1)  # one run: the video's metadata
        try:
            found_video = read_video(conn, runner, video_id, now)
        except ProviderBlocked as e:
            state = record_block(conn, PROVIDER, now, str(e))
            message = f"{e}\nNo more yt-dlp runs until {shown(state.cooldown_until)} (block #{state.strikes})."
            _common.alert_block(cfg, PROVIDER, message)
            end(f"{NOT_SEARCHED}YouTube blocked caracole ({e}); no more yt-dlp runs until "
                f"{shown(state.cooldown_until)}.")
            return
        except BudgetExhausted:
            end(f"{NOT_SEARCHED}YouTube's budget is spent; try again later.")
            return
        except ProviderError as e:
            record_error(conn, PROVIDER, now, str(e))
            record_failure(conn, key, now, str(e.message or e))
            end(f"{NOT_SEARCHED}yt-dlp failed ({e.message or e}); try again later.")
            return
        finally:
            runner.close()
        if answered_any(conn, run_id, PROVIDER, runner.requests_made):
            record_ok(conn, PROVIDER, now)
        if found_video is None:
            reason = video_gate(cfg, conn, video_id, now).asked or {}
            end(f"Nothing found: YouTube won't give video {video_id} ({reason.get('unavailable')}).", "done")
            return
        say("video", "done", f"{found_video.title} ({found_video.channel})")
        _thumbnail(cfg, conn, video_id, key, run_id, now, say)
    typer.echo(f"Searched: YouTube's video {video_id} is {found_video.title} ({found_video.channel}).")


def _thumbnail(cfg: Config, conn: sqlite3.Connection, video_id: str, key: str, run_id: str, now: datetime,
               say: Callable[[str, str, str], None]) -> None:
    """A suggested video's thumbnail, right after the search, from YouTube's image host (provider ``ytimg``: no pause,
    its own cooldown and alert); none while it cools down or is turned off, and none is no failure."""
    from caracole.health import answered_any, get_state, is_cooling, record_block, record_error, record_ok
    from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
    from caracole.youtube_search import THUMBS_PROVIDER, fetch_thumbnail

    if not cfg.provider(THUMBS_PROVIDER).enabled:
        say("thumbnail", "skipped", "turned off")
        return
    if is_cooling(conn, THUMBS_PROVIDER, now):
        say("thumbnail", "skipped", f"paused after a block, until {shown(get_state(conn, THUMBS_PROVIDER).cooldown_until)}")
        return
    say("thumbnail", "running", "")
    client = make_client(cfg, conn, THUMBS_PROVIDER, run_id)
    try:
        kept = fetch_thumbnail(cfg, conn, client, video_id, key, now)
        say("thumbnail", "done" if kept else "skipped", "kept" if kept else "none")
    except ProviderBlocked as e:
        state = record_block(conn, THUMBS_PROVIDER, now, str(e))
        _common.alert_block(cfg, THUMBS_PROVIDER, f"{e}\nNo more thumbnails until {shown(state.cooldown_until)} "
                                                  f"(block #{state.strikes}).")
        say("thumbnail", "skipped", f"YouTube's images blocked caracole; paused until {shown(state.cooldown_until)}")
        return
    except BudgetExhausted:
        say("thumbnail", "skipped", "budget spent")
        return
    except ProviderError as e:
        record_error(conn, THUMBS_PROVIDER, now, str(e))
        say("thumbnail", "skipped", "no thumbnail")
        return
    finally:
        client.close()
    if answered_any(conn, run_id, THUMBS_PROVIDER, client.requests_made):
        record_ok(conn, THUMBS_PROVIDER, now)


def _decline(cfg: Config, display: str) -> None:
    """``--none``: "none" under ``[youtube]`` for the song, any audio it has from YouTube let go
    of, and the pages rewritten. It asks YouTube nothing, so it is written with YouTube off, or
    for a song not in the library yet."""
    from caracole.overrides import OverridesError, add_youtube, override_key
    from caracole.songs import find_song
    from caracole.youtube_fetch import tidy

    with exclusive(cfg, "youtube"), closing(open_db(cfg)) as conn:
        try:
            add_youtube(cfg.overrides_file, display, "none")
        except OverridesError as e:
            fail(f"--song: {e}", 2)
        overrides = load_ovr(cfg)
        tidy(conn, cfg, overrides)
        song = find_song(conn, override_key(display))
        if song is not None:
            typer.echo(f"caracole won't take {song.display}'s audio from YouTube (\"none\" under [youtube]).")
        else:
            typer.echo(f'"none" is under [youtube]: caracole won\'t take the audio from YouTube once "{display}" '
                       "is in the library.")
        write_pages(conn, cfg, overrides, utcnow())


def _one_song(conn: sqlite3.Connection, cfg: Config, display: str, overrides: Overrides) -> Song:
    """The song ``--song`` names, if YouTube may be asked for its audio; otherwise say why not."""
    from caracole.youtube_fetch import youtube_audio

    song = song_named(conn, display, overrides)
    if conn.execute("SELECT 1 FROM files WHERE song_id = ? AND name = 'sheet.txt'", (song.id,)).fetchone():
        fail(f'"{song.display}" has a human sheet: caracole takes no audio from YouTube for it.')
    if song.audio_path and youtube_audio(conn, song) is None:  # a purchase, linked from Music/
        audio = Path(song.audio_path)
        where = f"{audio.relative_to(cfg.music_dir)} in Music/" if audio.is_relative_to(cfg.music_dir) else audio
        fail(f'"{song.display}" has its audio already ({where}): caracole takes none from YouTube for it.')
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
    from caracole.youtube_fetch import DOWNLOADED_NOW, GAVE_UP, MISSED, PASSED_OVER

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
    if outcome == GAVE_UP:  # the error says what comes next
        return f"{song.display}: failed ({record.error})"
    return f"{song.display}: failed ({record.error}); tried again on the next run"


def _totals(stats: YouTubeStats, runs: int, budget: int) -> str:
    return (f"YouTube: {stats.downloaded} downloaded, {stats.missing} not there, {stats.unavailable} unavailable, "
            f"{plural(stats.errors, 'error')} ({plural(runs, 'yt-dlp run')} of {budget}).")
