"""Index commands: ``tabarr index build``, ``tabarr index refresh`` and ``tabarr index stats``.

The local UG index is built once from Ultimate Guitar's sitemaps, or from
sitemap files you already have, and the nightly run refreshes it. A block or
a spent budget is not a failure: the sitemaps read so far are kept, and the
command says what happens next. Every command module is imported on every
start, so the index module is imported inside the commands.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import typer

from tabarr.commands import _common
from tabarr.commands._common import fail, load_cfg, open_db, run_id_for, utcnow

if TYPE_CHECKING:
    from tabarr.config import Config, ProviderPolicy
    from tabarr.http import Client
    from tabarr.ug.index import IndexStats


# A full build is about 42 requests (the sitemap index and 41 tab sitemaps), more than one night's budget.
BUILD_BUDGET = 100
_KEPT = "the sitemaps read so far are kept"


def register(app: typer.Typer) -> None:
    index = typer.Typer(help="The local index of Ultimate Guitar's tabs, built from its sitemaps.",
                        no_args_is_help=True)
    app.add_typer(index, name="index")

    @index.command("build")
    def build_cmd(
        ctx: typer.Context,
        from_dir: Path | None = typer.Option(
            None, "--from", metavar="DIR", exists=True, file_okay=False, dir_okay=True,
            help="Read sitemapN.xml[.gz] and sitemap_last.xml[.gz] from DIR instead (no requests).",
        ),
    ) -> None:
        """Index every UG tab sitemap: about 42 requests, 10-20 s apart (about 10 minutes)."""
        _build(load_cfg(ctx), from_dir)

    @index.command("refresh")
    def refresh_cmd(ctx: typer.Context) -> None:
        """Re-read the sitemaps where new tabs appear, as the nightly run does."""
        _refresh(load_cfg(ctx))

    @index.command("stats")
    def stats_cmd(ctx: typer.Context) -> None:
        """How many tabs, of which types, and how many artists the index holds."""
        _stats(load_cfg(ctx))


# --- tabarr index build ------------------------------------------------------------------------


def _build(cfg: Config, from_dir: Path | None) -> None:
    from tabarr.config import ProviderPolicy
    from tabarr.ug.index import build_index, index_count

    now = utcnow()
    with closing(open_db(cfg)) as conn:
        if from_dir is not None:
            typer.echo(f"Reading the sitemap files in {from_dir} (no requests).")
            try:
                stats = build_index(conn, None, now, from_dir=from_dir, progress=_progress)
            except (OSError, ValueError) as e:
                fail(f"index build: {e}")
        else:
            ug = cfg.provider("ug")
            policy = ProviderPolicy(budget=max(BUILD_BUDGET, ug.budget), delay=ug.delay)
            typer.echo("Reading Ultimate Guitar's sitemap index, then each tab sitemap, one request at a time, "
                       f"{ug.delay[0]:g}-{ug.delay[1]:g} s apart.")
            stats = _with_ug(conn, cfg, now, policy,
                             lambda client: build_index(conn, client, now, progress=_progress))
        if stats is None:
            return
        typer.echo(f"Index built: {_read(stats)}; {_count(len(stats.new_tab_ids), 'new tab')}. "
                   f"The index holds {_count(index_count(conn), 'tab')}.")


# --- tabarr index refresh ----------------------------------------------------------------------


def _refresh(cfg: Config) -> None:
    from tabarr.ug.index import index_count, mark_dirty_for_new, refresh_index

    now = utcnow()
    with closing(open_db(cfg)) as conn:
        if index_count(conn) == 0:
            fail("The index is empty: run `tabarr index build` first.")
        stats = _with_ug(conn, cfg, now, cfg.provider("ug"),
                         lambda client: refresh_index(conn, client, now, progress=_progress))
        if stats is None:
            return
        dirty = mark_dirty_for_new(conn, stats.new_tab_ids)
        typer.echo(f"Index refreshed: {_read(stats)}; {_count(len(stats.new_tab_ids), 'new tab')}; "
                   f"{_count(dirty, 'song')} to refetch.")


# --- tabarr index stats ------------------------------------------------------------------------


def _stats(cfg: Config) -> None:
    from tabarr.ug.index import index_stats

    with closing(open_db(cfg)) as conn:
        s = index_stats(conn)
    if not s["rows"]:
        typer.echo("The index is empty: run `tabarr index build`.")
        return
    types = ", ".join(f"{kind} {n:,}" for kind, n in s["types"].items())
    typer.echo(f"Tabs: {s['rows']:,} ({types})")
    typer.echo(f"Artists: {s['artists']:,}")
    typer.echo(f"Sitemaps indexed: {s['sitemaps']}")
    typer.echo(f"Newest tab id: {s['newest_tab_id']}")
    typer.echo(f"Built: {s['built_at'] or 'never'}; refreshed: {s['refreshed_at'] or 'never'}")


# --- shared ------------------------------------------------------------------------------------


def _with_ug(conn: sqlite3.Connection, cfg: Config, now: datetime, policy: ProviderPolicy,
             action: Callable[[Client], IndexStats]) -> IndexStats | None:
    """Run ``action`` with a polite UG client, the way the nightly run treats UG.

    A cooldown means no request is sent; a block starts (or doubles) the
    cooldown; neither, nor a spent budget, is a failure, so they print a message
    and return None. Any other provider error is recorded and exits 1.
    """
    from tabarr.health import EventLog, get_state, is_cooling, record_block, record_error, record_ok
    from tabarr.http import BudgetExhausted, Event, PoliteClient, ProviderBlocked, ProviderError

    if is_cooling(conn, "ug", now):
        until = get_state(conn, "ug").cooldown_until
        typer.echo(f"Ultimate Guitar is cooling down after a block until {_when(until)}; no request was sent.")
        return None
    log = EventLog(conn, run_id_for(now))
    answered = 0

    def on_event(event: Event) -> None:
        nonlocal answered
        log(event)
        if event.decision in ("ok", "not_modified"):  # an error or a block is no answer
            answered += 1

    client = PoliteClient("ug", policy, cfg.cache_dir, user_agent=cfg.user_agent,
                          transport=_common.transport_for("ug"), on_event=on_event)
    result: IndexStats | None = None
    note = failure = None
    try:
        result = action(client)
    except ProviderBlocked as e:
        state = record_block(conn, "ug", now, str(e))
        typer.echo(f"Ultimate Guitar blocked tabarr ({e}). No more requests to it until {_when(state.cooldown_until)} "
                   f"(block #{state.strikes}); {_KEPT}.")
        return None
    except BudgetExhausted:
        note = (f"The Ultimate Guitar budget of {policy.budget} requests is spent; {_KEPT}, "
                "and the next refresh reads the sitemaps not read yet.")
    except ProviderError as e:
        record_error(conn, "ug", now, str(e))
        failure = f"Ultimate Guitar failed: {e}. The sitemaps read so far are kept."
    finally:
        client.close()
    if answered:
        record_ok(conn, "ug", now)  # UG answered without a block, as the nightly run records it
    if failure is not None:
        fail(failure)
    if note is not None:
        typer.echo(note)
        return None
    return result


def _progress(name: str, stats: IndexStats) -> None:
    label = "sitemap_last" if name == "last" else f"sitemap{name}"
    if stats.sitemaps_unchanged:
        typer.echo(f"{label}: unchanged")
    else:
        typer.echo(f"{label}: {stats.rows:,} tabs, {len(stats.new_tab_ids):,} new")


def _read(stats: IndexStats) -> str:
    return f"{_count(stats.sitemaps_fetched, 'sitemap')} read, {stats.sitemaps_unchanged} unchanged"


def _count(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _when(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "?"
