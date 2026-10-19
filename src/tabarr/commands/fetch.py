"""``tabarr fetch``: fetch, rank and keep UG sheets and guitar parts, within the request budget.

The nightly ``tabarr run`` does this as one of its steps; the command runs it
on its own, or for one song with ``--song``. A block or a spent budget is
expected behaviour, not a failure, so both exit 0. Every command module is
imported on every start, so the fetch code is imported inside the command.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from typing import TYPE_CHECKING

import typer

from tabarr.commands._common import (
    fail,
    load_cfg,
    load_ovr,
    make_client,
    open_db,
    run_id_for,
    utcnow,
)

if TYPE_CHECKING:
    from tabarr.config import Config
    from tabarr.overrides import Overrides
    from tabarr.songs import Song
    from tabarr.ug.fetch import FetchStats, SongFetchOutcome

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
    from tabarr.health import get_state, is_cooling, record_block, record_ok
    from tabarr.http import ProviderBlocked
    from tabarr.ug.fetch import FetchContext, fetch_songs, songs_to_fetch

    now = utcnow()
    overrides = load_ovr(cfg)
    with closing(open_db(cfg)) as conn:
        if is_cooling(conn, PROVIDER, now):
            until = _when(get_state(conn, PROVIDER).cooldown_until)
            typer.echo(f"Ultimate Guitar is cooling down after a block until {until}; nothing fetched.")
            return
        songs = [_one_song(conn, display, overrides)] if display else songs_to_fetch(conn, overrides, now)
        if not songs:
            typer.echo("Nothing to fetch.")
            return
        client = make_client(cfg, conn, PROVIDER, run_id_for(now))
        ctx = FetchContext(conn=conn, client=client, overrides=overrides, rank=cfg.rank,
                           library_dir=cfg.library_dir, now=now)
        try:
            stats = fetch_songs(ctx, songs, on_song=lambda song, outcome: typer.echo(_line(song, outcome)))
        except ProviderBlocked as e:
            state = record_block(conn, e.provider, now, str(e))
            typer.echo(
                f"Ultimate Guitar blocked tabarr ({e}). No more UG requests until "
                f"{_when(state.cooldown_until)} (block #{state.strikes}). Nothing was marked not found."
            )
            return
        finally:
            client.close()
        if client.requests_made:
            record_ok(conn, PROVIDER, now)
    typer.echo(_totals(stats, client.requests_made))
    if stats.budget_exhausted:
        budget = cfg.provider(PROVIDER).budget
        typer.echo(f"The UG budget of {_count(budget, 'request')} is spent; the rest waits for the next run.")


def _one_song(conn: sqlite3.Connection, display: str, overrides: Overrides) -> Song:
    """The song ``--song`` names, if it is one UG can be asked about; otherwise say what's missing."""
    from tabarr.overrides import OverridesError, override_key
    from tabarr.songs import find_song
    from tabarr.ug.fetch import artist_is_known

    try:
        key = override_key(display)
    except OverridesError as e:
        fail(str(e), 2)
    song = find_song(conn, key)
    if song is None:
        fail(f'No song "{display}" in the library. Add it with `tabarr add` first.')
    if song.status == "ignored" or song.match_decision == "ignored" or key in overrides.ignore:
        fail(f'"{song.display}" is ignored in overrides.toml.')
    if song.match_decision == "review":
        fail(f'"{song.display}" needs review first: run `tabarr review`.')
    if song.match_decision == "not_found" and not artist_is_known(conn, song, overrides):
        fail(
            f"Ultimate Guitar lists {song.artist} only by bare tab ids, which tabarr can't see. "
            "Find the artist's page on UG and paste it under [artist_url] in overrides.toml."
        )
    if song.match_decision not in ("accept", "pinned", "not_found"):
        fail(f'"{song.display}" isn\'t matched yet: run `tabarr match` first.')
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
