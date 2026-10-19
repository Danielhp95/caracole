"""``caracole lyrics`` and ``caracole lacuerda``: one step of the nightly run, by hand.

Each makes the same pass as its ``caracole run`` step, with a client of its own:
this run's budget, and the HTTP cache the nightly run uses too. As in the run,
a provider cooling down after a block is left alone, and a block starts (or
extends) its cooldown and sends one ntfy alert. Neither is a failure, and
neither is a spent budget: each prints what happened and exits 0, as
``caracole fetch`` and ``caracole index`` do, and the songs left wait for the
next run. Then each rewrites _todo.md and index.html, which read
overrides.toml, unless it did nothing (a cooldown, or no song to ask about).

Every command module is imported on every start, so the passes are imported
inside the commands.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from typing import TYPE_CHECKING

import typer

from caracole.commands import _common
from caracole.commands._common import (
    exclusive,
    load_cfg,
    load_ovr,
    make_client,
    open_db,
    run_id_for,
    utcnow,
    write_pages,
)
from caracole.health import get_state, is_cooling, record_block, record_ok
from caracole.http import ProviderBlocked

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.http import Client
    from caracole.lacuerda_fetch import LaCuerdaStats
    from caracole.lyrics import LyricsStats
    from caracole.overrides import Overrides

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
    from caracole.lyrics import fetch_pending_lyrics

    overrides = load_ovr(cfg)  # for the pages

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        return fetch_pending_lyrics(conn, client, cfg.library_dir, now)

    def ran(s: LyricsStats) -> bool:
        return bool(s.found or s.missing or s.instrumental or s.errors or s.budget_exhausted)

    s = _provider_pass(cfg, "lrclib", run, overrides, ran)
    if s is None:
        return
    if not ran(s):
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
    from caracole.lacuerda_fetch import lacuerda_sheets
    from caracole.ug.fetch import rescore_kept_sheets

    overrides = load_ovr(cfg)
    rescored = 0

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        nonlocal rescored
        # As the run does before its fetch: a sheet kept before its lyrics is scored first (no
        # request), or no partial LaCuerda sheet could replace it, and a complete one is left be.
        rescored = rescore_kept_sheets(conn, cfg.library_dir, cfg.rank)
        return lacuerda_sheets(conn, client, cfg.library_dir, cfg.rank, now, overrides=overrides)

    def ran(s: LaCuerdaStats) -> bool:
        return bool(rescored or s.tried or s.budget_exhausted)

    s = _provider_pass(cfg, "lacuerda", run, overrides, ran)
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
    cfg: Config,
    provider: str,
    run: Callable[[sqlite3.Connection, Client, datetime], T],
    overrides: Overrides,
    ran: Callable[[T], bool],
) -> T | None:
    """Run one provider's pass as the nightly run does; None after a cooldown or a block.

    Either way it says so first; neither is a failure, so the command exits 0.
    Requests are logged to ``events`` under a run id of their own. A pass that
    made requests without a block clears the provider's strikes, as a run does.
    It holds caracole's lock throughout, so the cooldown it reads is the one a
    caracole it waited for left. After a block, or a pass that did something
    (``ran``), it rewrites _todo.md and index.html.
    """
    name = _NAMES[provider]
    with exclusive(cfg, _COMMANDS[provider]), closing(open_db(cfg)) as conn:
        now = utcnow()
        if is_cooling(conn, provider, now):
            until = get_state(conn, provider).cooldown_until
            typer.echo(f"{name} is cooling down after a block until {_when(until)}; "
                       "caracole won't ask it before then.")
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
            _alert(cfg, f"caracole: {provider} blocked", message)
            typer.echo(f"{name} blocked caracole: {message}")
            write_pages(conn, cfg, overrides, utcnow())  # with the cooldown
            return None
        finally:
            client.close()
        if client.requests_made:
            record_ok(conn, provider, now)
        if ran(result):
            write_pages(conn, cfg, overrides, utcnow())
    return result


def _alert(cfg: Config, title: str, message: str) -> None:
    """One ntfy message, as the nightly run sends on a block; nothing without an ntfy URL."""
    from caracole.notify import Notifier

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
