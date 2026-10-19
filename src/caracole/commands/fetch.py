"""``caracole fetch``: fetch, rank and keep UG sheets and guitar parts, within the request budget.

The nightly ``caracole run`` does this as one of its steps; the command runs it
on its own, or for one song with ``--song``, and like the run it first scores
the sheets kept before their lyrics arrived. A block or a spent budget is
expected behaviour, not a failure, so both exit 0. Then it rewrites _todo.md
and index.html, unless it did nothing (a cooldown, or nothing to fetch or
score). Every command module is imported on every start, so the fetch code is
imported inside the command.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from typing import TYPE_CHECKING

import typer

from caracole.commands._common import (
    exclusive,
    fail,
    load_cfg,
    load_ovr,
    make_client,
    open_db,
    run_id_for,
    utcnow,
    write_pages,
)

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.overrides import Overrides
    from caracole.songs import Song
    from caracole.ug.fetch import FetchStats, SongFetchOutcome

PROVIDER = "ug"


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
    from caracole.ug.fetch import FetchContext, fetch_songs, rescore_kept_sheets, songs_to_fetch

    overrides = load_ovr(cfg)
    # Under caracole's lock from the start: a run this waited for may have been blocked meanwhile.
    with exclusive(cfg, "fetch"), closing(open_db(cfg)) as conn:
        now = utcnow()
        if is_cooling(conn, PROVIDER, now):
            until = _when(get_state(conn, PROVIDER).cooldown_until)
            typer.echo(f"Ultimate Guitar is cooling down after a block until {until}; nothing fetched.")
            return
        # As in the nightly run: sheets kept before their lyrics are scored first, with no request,
        # and a partial one sends its song back to have its sheets ranked again.
        rescored = rescore_kept_sheets(conn, cfg.library_dir, cfg.rank)
        if rescored:
            typer.echo(f"Scored {_count(rescored, 'kept sheet')} against lyrics that came later.")
        songs = [_one_song(conn, display, overrides)] if display else songs_to_fetch(conn, overrides, now)
        if not songs:
            typer.echo("Nothing to fetch.")
            if rescored:  # a partial sheet it found shows at once
                write_pages(conn, cfg, overrides, utcnow())
            return
        client = make_client(cfg, conn, PROVIDER, run_id_for(now))
        ctx = FetchContext(conn=conn, client=client, overrides=overrides, rank=cfg.rank,
                           library_dir=cfg.library_dir, now=now,
                           reload_overrides=lambda: load_overrides(cfg.overrides_file))
        try:
            stats = fetch_songs(ctx, songs, on_song=lambda song, outcome: typer.echo(_line(song, outcome)))
        except ProviderBlocked as e:
            state = record_block(conn, e.provider, now, str(e))
            typer.echo(
                f"Ultimate Guitar blocked caracole ({e}). No more UG requests until "
                f"{_when(state.cooldown_until)} (block #{state.strikes}). Nothing was marked not found."
            )
            write_pages(conn, cfg, overrides, utcnow())  # with what it kept, and the cooldown
            return
        finally:
            client.close()
        if client.requests_made:
            record_ok(conn, PROVIDER, now)
        write_pages(conn, cfg, overrides, utcnow())
    typer.echo(_totals(stats, client.requests_made))
    if stats.budget_exhausted:
        budget = cfg.provider(PROVIDER).budget
        typer.echo(f"The UG budget of {_count(budget, 'request')} is spent; the rest waits for the next run.")


def _one_song(conn: sqlite3.Connection, display: str, overrides: Overrides) -> Song:
    """The song ``--song`` names, if it is one UG can be asked about; otherwise say what's missing.

    As in the nightly run, a song the index can't settle (not found, or a
    review of other artists' songs of its title) is looked up on its artist's
    UG page.
    """
    from caracole.overrides import OverridesError, override_key
    from caracole.songs import find_song
    from caracole.ug.fetch import artist_is_known, needs_artist_page, pasted_page_problem

    try:
        key = override_key(display)
    except OverridesError as e:
        fail(str(e), 2)
    song = find_song(conn, key)
    if song is None:
        fail(f'No song "{display}" in the library. Add it with `caracole add` first.')
    if song.status == "ignored" or song.match_decision == "ignored" or key in overrides.ignore:
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


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _line(song: Song, outcome: SongFetchOutcome) -> str:
    """One song's result, as ``Artist - Title: sheet 101 · Guitar Pro 301, 303 · tab 402 (3 requests)``."""
    parts = []
    if outcome.sheet is not None:
        parts.append(f"sheet {outcome.sheet}")
    if outcome.guitar_pro:
        parts.append("Guitar Pro " + ", ".join(str(t) for t in outcome.guitar_pro))
    if outcome.tab is not None:
        parts.append(f"tab {outcome.tab}")
    return f"{song.display}: {' · '.join(parts) or 'nothing kept'} ({_count(outcome.requests, 'request')})"


def _totals(stats: FetchStats, requests: int) -> str:
    done = _count(stats.songs_done, "song")
    return f"{done} done, {stats.songs_failed} failed, {_count(requests, 'UG request')}."


def _when(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "?"
