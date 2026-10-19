"""``tabarr lyrics`` and ``tabarr lacuerda``: one step of the nightly run, by hand.

Each makes the same pass as its ``tabarr run`` step, with a client of its own:
this run's budget, and the HTTP cache the nightly run uses too. As in the run,
a provider cooling down after a block is left alone, and a block starts (or
extends) its cooldown and sends one ntfy alert. Neither is a failure, and
neither is a spent budget: each prints what happened and exits 0, as
``tabarr fetch`` and ``tabarr index`` do, and the songs left wait for the
next run.

Every command module is imported on every start, so the passes are imported
inside the commands.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from typing import TYPE_CHECKING

import typer

from tabarr.commands import _common
from tabarr.commands._common import (
    exclusive,
    load_cfg,
    load_ovr,
    make_client,
    open_db,
    run_id_for,
    utcnow,
)
from tabarr.health import get_state, is_cooling, record_block, record_ok
from tabarr.http import ProviderBlocked

if TYPE_CHECKING:
    from tabarr.config import Config
    from tabarr.http import Client

_NAMES = {"lrclib": "LRCLIB", "lacuerda": "LaCuerda"}
_COMMANDS = {"lrclib": "lyrics", "lacuerda": "lacuerda"}  # each provider's command, for the lock


def register(app: typer.Typer) -> None:
    @app.command("lyrics")
    def lyrics_cmd(ctx: typer.Context) -> None:
        """Fetch lyrics from LRCLIB for songs that have none yet."""
        _lyrics(load_cfg(ctx))

    @app.command("lacuerda")
    def lacuerda_cmd(ctx: typer.Context) -> None:
        """Look for LaCuerda chord sheets for Spanish songs without a complete one."""
        _lacuerda(load_cfg(ctx))


def _lyrics(cfg: Config) -> None:
    """Look up every song still waiting for lyrics, and old misses, then print the counts."""
    from tabarr.lyrics import fetch_pending_lyrics

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        return fetch_pending_lyrics(conn, client, cfg.library_dir, now)

    s = _provider_pass(cfg, "lrclib", run)
    if s is None:
        return
    if not (s.found or s.missing or s.instrumental or s.errors or s.budget_exhausted):
        typer.echo("No song is waiting for lyrics.")
        return
    counts = f"{s.found} found, {s.missing} missing, {s.instrumental} instrumental"
    typer.echo(f"Lyrics: {counts}, {_count(s.errors, 'error')}")
    if s.errors:
        typer.echo("Songs with an error stay pending; the next run asks LRCLIB again.")
    if s.budget_exhausted:
        _budget_spent(cfg, "lrclib")


def _lacuerda(cfg: Config) -> None:
    """Try LaCuerda for the Spanish songs that need a sheet, then print the counts."""
    from tabarr.lacuerda_fetch import lacuerda_sheets

    overrides = load_ovr(cfg)

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        return lacuerda_sheets(conn, client, cfg.library_dir, cfg.rank, now, overrides=overrides)

    s = _provider_pass(cfg, "lacuerda", run)
    if s is None:
        return
    if not (s.tried or s.budget_exhausted):
        typer.echo("No song to try on LaCuerda.")
        return
    counts = f"{s.tried} tried, {_count(s.kept, 'sheet')} kept, {s.missing} missing"
    typer.echo(f"LaCuerda: {counts}, {_count(s.errors, 'error')}")
    if s.errors:
        typer.echo("Songs with an error are tried again next run.")
    if s.budget_exhausted:
        _budget_spent(cfg, "lacuerda")


def _provider_pass[T](
    cfg: Config, provider: str, run: Callable[[sqlite3.Connection, Client, datetime], T]
) -> T | None:
    """Run one provider's pass as the nightly run does; None after a cooldown or a block.

    Either way it says so first; neither is a failure, so the command exits 0.
    Requests are logged to ``events`` under a run id of their own. A pass that
    made requests without a block clears the provider's strikes, as a run does.
    It holds tabarr's lock throughout, so the cooldown it reads is the one a
    tabarr it waited for left.
    """
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    name = _NAMES[provider]
    with exclusive(cfg, _COMMANDS[provider]), closing(open_db(cfg)) as conn:
        now = utcnow()
        if is_cooling(conn, provider, now):
            until = get_state(conn, provider).cooldown_until
            typer.echo(f"{name} is cooling down after a block until {_when(until)}; "
                       "tabarr won't ask it before then.")
            return None
        client = make_client(cfg, conn, provider, run_id_for(now))
        try:
            result = run(conn, client, now)
        except ProviderBlocked as e:
            state = record_block(conn, provider, now, str(e))
            message = (
                f"{e}\nNo more requests to {name} until {_when(state.cooldown_until)} "
                f"(block #{state.strikes}). Nothing was marked missing."
            )
            _alert(cfg, f"tabarr: {provider} blocked", message)
            typer.echo(f"{name} blocked tabarr: {message}")
            return None
        finally:
            client.close()
        if client.requests_made:
            record_ok(conn, provider, now)
    return result


def _alert(cfg: Config, title: str, message: str) -> None:
    """One ntfy message, as the nightly run sends on a block; nothing without an ntfy URL."""
    from tabarr.notify import Notifier

    notifier = Notifier(cfg.ntfy.url, cfg.ntfy.token, transport=_common.transport_for("ntfy"))
    notifier.send(title, message, priority="high", tags=["warning"])


def _budget_spent(cfg: Config, provider: str) -> None:
    budget = cfg.provider(provider).budget
    typer.echo(
        f"{_NAMES[provider]}'s budget of {_count(budget, 'request')} per run is spent; "
        "the songs left wait for the next run."
    )


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _when(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "?"
