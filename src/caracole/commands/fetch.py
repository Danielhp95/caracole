"""``caracole fetch``: fetch, rank and keep UG sheets and guitar parts, within the request budget.

The nightly ``caracole run`` does this as one of its steps; the command runs it
on its own, or for one song with ``--song``, and like the run it first scores
the sheets kept before their lyrics arrived. A block or a spent budget is
expected behaviour, not a failure, so both exit 0; a block sends the one ntfy
alert the run sends (``_common.alert_block``). Then it rewrites _todo.md
and index.html, unless it did nothing (a cooldown, or nothing to fetch or
score). Every command module is imported on every start, so the fetch code is
imported inside the command.

It prints a line per song and the totals; for one song (``--song``), that
song's line alone, which says why when nothing came, and -v adds the rest.
A ``--song`` cut short (a cooldown, a block, a spent budget, an error) marks
a matched song to fetch, so the next run fetches it even if it was clean.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import TYPE_CHECKING

import typer

from caracole.commands._common import (
    alert_block,
    exclusive,
    fail,
    load_cfg,
    load_ovr,
    make_client,
    open_db,
    run_id_for,
    song_named,
    utcnow,
    write_pages,
)
from caracole.logs import plural
from caracole.stamps import shown

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.overrides import Overrides
    from caracole.songs import Song
    from caracole.ug.fetch import FetchStats, SongFetchOutcome

PROVIDER = "ug"
log = logging.getLogger(__name__)


def register(app: typer.Typer) -> None:
    @app.command("fetch")
    def fetch_cmd(
        ctx: typer.Context,
        song: str | None = typer.Option(
            None, "--song", metavar='"ARTIST - TITLE"',
            help="Fetch only this song, even when nothing about it changed.",
        ),
    ) -> None:
        """Fetch and rank Ultimate Guitar versions for the songs that need it, within the budget."""
        _fetch(load_cfg(ctx), song)


def _fetch(cfg: Config, display: str | None) -> None:
    from caracole.health import get_state, is_cooling, record_block, record_ok
    from caracole.http import ProviderBlocked
    from caracole.overrides import load_overrides
    from caracole.report import shared_folder
    from caracole.ug.fetch import FetchContext, fetch_songs, rescore_kept_sheets, songs_to_fetch

    overrides = load_ovr(cfg)
    # Under caracole's lock from the start: a run this waited for may have been blocked meanwhile.
    with exclusive(cfg, "fetch"), closing(open_db(cfg)) as conn:
        now = utcnow()
        asked = _one_song(conn, display, overrides) if display else None  # what's missing comes first
        if is_cooling(conn, PROVIDER, now):
            until = shown(get_state(conn, PROVIDER).cooldown_until)
            if asked is not None and _send_back(conn, asked, overrides, now):
                typer.echo(f"Ultimate Guitar is cooling down after a block until {until}; "
                           f"{asked.display} waits for the first run after that.")
            else:
                typer.echo(f"Ultimate Guitar is cooling down after a block until {until}; nothing fetched.")
            return
        # As in the nightly run: sheets kept before their lyrics are scored first, with no request,
        # and a partial one sends its song back to have its sheets ranked again.
        rescored = rescore_kept_sheets(conn, cfg.library_dir, cfg.rank)
        if rescored:
            scored = f"Scored {plural(rescored, 'kept sheet')} against lyrics that came later."
            if display:  # not about the song asked for
                log.info(scored)
            else:
                typer.echo(scored)
        songs = [asked] if asked is not None else songs_to_fetch(conn, overrides, now)
        if not songs:
            typer.echo("Nothing to fetch.")
            if rescored:  # a partial sheet it found shows at once
                write_pages(conn, cfg, overrides, utcnow())
            return
        client = make_client(cfg, conn, PROVIDER, run_id_for(now))
        ctx = FetchContext(conn=conn, client=client, overrides=overrides, rank=cfg.rank,
                           library_dir=cfg.library_dir, now=now,
                           reload_overrides=lambda: load_overrides(cfg.overrides_file))
        one = asked is not None

        def said(song: Song, outcome: SongFetchOutcome) -> None:
            typer.echo(_line(song, outcome, requests=not one))

        try:
            stats = fetch_songs(ctx, songs, on_song=said)
        except ProviderBlocked as e:
            state = record_block(conn, e.provider, now, str(e))
            if asked is not None:
                _send_back(conn, asked, overrides, now)
            message = (f"Ultimate Guitar blocked caracole ({e}). No more UG requests until "
                       f"{shown(state.cooldown_until)} (block #{state.strikes}). Nothing was marked not found.")
            alert_block(cfg, e.provider, message)
            typer.echo(message)
            write_pages(conn, cfg, overrides, utcnow())  # with what it kept, and the cooldown
            return
        finally:
            client.close()
        if client.requests_made:
            record_ok(conn, PROVIDER, now)
        unfinished = asked is not None and not stats.songs_done
        due = _send_back(conn, asked, overrides, now) if unfinished else True
        write_pages(conn, cfg, overrides, utcnow())
    budget = cfg.provider(PROVIDER).budget
    if one:
        log.info(_totals(stats, client.requests_made))
        if unfinished:
            typer.echo(_not_done(songs[0], stats, budget, due=due))
        return
    typer.echo(_totals(stats, client.requests_made))
    for shared in stats.shared:
        typer.echo(shared_folder(shared).text)
    if stats.budget_exhausted:
        typer.echo(f"The UG budget of {plural(budget, 'request')} is spent; the rest waits for the next run.")


def _send_back(conn: sqlite3.Connection, song: Song, overrides: Overrides, now: datetime) -> bool:
    """``--song``'s song, cut short before it was done (a cooldown, a block, a spent budget, an error).

    A matched song is marked to fetch, so the nightly run fetches it again even
    if it was clean (fetched before, nothing new): asked for, it is owed a
    fetch. True when the next run will fetch it; a song looked up on its
    artist's UG page lately waits for that page's next reading.
    """
    from caracole.songs import get_song, update_song
    from caracole.ug.fetch import fetch_due

    song = get_song(conn, song.id)  # the fetch may have matched it on its artist's page
    if song.match_decision in ("accept", "pinned") and not song.ug_dirty:
        update_song(conn, song.id, ug_dirty=True)
        song = get_song(conn, song.id)
    return fetch_due(conn, song, overrides, now)


def _one_song(conn: sqlite3.Connection, display: str, overrides: Overrides) -> Song:
    """The song ``--song`` names, if it is one UG can be asked about; otherwise say what's missing.

    As in the nightly run, a song the index can't settle (not found, or a
    review of other artists' songs of its title or of names that aren't quite
    UG's, ``match.REVIEW_ONLY_STEPS``) is looked up on its artist's UG page.
    """
    from caracole.ug.fetch import artist_is_known, needs_artist_page, pasted_page_problem

    song = song_named(conn, display, overrides)
    if song.match_decision == "ignored":
        fail(f'"{song.display}" is ignored in overrides.toml.')
    artist_page = needs_artist_page(song)
    if song.match_decision == "review" and not artist_page:
        fail(f'"{song.display}" needs review first: run `caracole review`.')
    if artist_page and not artist_is_known(conn, song, overrides):
        pasted = pasted_page_problem(conn, song, overrides)
        if pasted is not None:
            fail(f"The page under [artist_url] for {song.artist}, {pasted[0]}: {pasted[1]}. Put the artist's "
                 "page, or another of their tab pages, in its place in overrides.toml.")
        fail(
            f"Ultimate Guitar lists {song.artist} only by bare tab ids, which caracole can't see. "
            "Find the artist's page on UG, or one of their tab pages, and paste its address under "
            "[artist_url] in overrides.toml."
        )
    if song.match_decision not in ("accept", "pinned") and not artist_page:
        fail(f'"{song.display}" isn\'t matched yet: run `caracole match` first.')
    return song


def _line(song: Song, outcome: SongFetchOutcome, *, requests: bool = True) -> str:
    """One song's result, as ``Artist - Title: sheet 101 · Guitar Pro 301, 303 · tab 402 (3 requests)``;
    without ``requests``, the count is left to -v."""
    parts = []
    if outcome.sheet is not None:
        parts.append(f"sheet {outcome.sheet}")
    if outcome.guitar_pro:
        parts.append("Guitar Pro " + ", ".join(str(t) for t in outcome.guitar_pro))
    if outcome.tab is not None:
        parts.append(f"tab {outcome.tab}")
    line = f"{song.display}: {' · '.join(parts) or 'nothing kept'}"
    if not requests:
        log.info("%s: %s", song.display, plural(outcome.requests, "UG request"))
        return line
    return f"{line} ({plural(outcome.requests, 'request')})"


def _not_done(song: Song, stats: FetchStats, budget: int, *, due: bool = True) -> str:
    """Why ``--song``'s song got no line of its own: an error, the budget, or a file of its that would go
    where another song keeps one (``library.SharedFolder``), before it was done. None is a miss, so it
    waits for the next run (``due``, as ``_send_back`` makes a matched song), or for you to ask again; a
    sheet the first pass kept stays."""
    from caracole.report import shared_folder

    if stats.shared:
        return shared_folder(stats.shared[0]).text
    spent = f"the UG budget of {plural(budget, 'request')} is spent"
    if stats.sheets_done:
        if stats.failures:
            return f"{song.display}: sheet kept; its guitar parts wait for the next run ({stats.failures[0][1]})."
        return f"{song.display}: sheet kept; {spent}, so its guitar parts wait for the next run."
    then = "it waits for the next run" if due else "ask for it again later"
    if stats.failures:
        return f"{song.display}: not fetched ({stats.failures[0][1]}); {then}."
    return f"{song.display}: not fetched; {spent}, so {then}."


def _totals(stats: FetchStats, requests: int) -> str:
    done = plural(stats.songs_done, "song")
    return f"{done} done, {stats.songs_failed} failed, {plural(requests, 'UG request')}."
