"""``caracole icons``: fetch the sites' icons that index.html lacks, now, then rewrite the pages.

The nightly run does this as its icons step, with its own clients; this command
asks each site that has no icon kept, even one asked less than a week ago, with
a client of its own (``make_client``: caracole's lock, the provider's budget and
pauses, its cooldown). A site with no provider of its own yet (YouTube) gets
``ICON_POLICY``. A block cools that provider down as any block does, and the
other sites are still asked; a block or an error exits 0.
"""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING

import typer

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
from caracole.config import ProviderPolicy

if TYPE_CHECKING:
    from caracole.icons import IconRun

# For a site caracole.toml has no provider for: a request or two, ever, at the usual pace.
ICON_POLICY = ProviderPolicy(budget=4, delay=(10.0, 20.0))


def register(app: typer.Typer) -> None:
    @app.command("icons")
    def icons_cmd(ctx: typer.Context) -> None:
        """Fetch the sites' icons that index.html shows where files came from, then rewrite the pages."""
        from caracole.health import get_state, is_cooling, record_block, record_ok
        from caracole.http import ProviderBlocked
        from caracole.icons import SOURCES, fetch_icons, has_icon

        cfg = load_cfg(ctx)
        overrides = load_ovr(cfg)
        with exclusive(cfg, "icons"), closing(open_db(cfg)) as conn:
            now = utcnow()
            for key, source in SOURCES.items():
                if source.glyph:
                    continue
                policy = cfg.providers.get(key)
                if has_icon(cfg.cache_dir, key):
                    typer.echo(f"{source.name}: kept already")
                elif policy is not None and not policy.enabled:
                    typer.echo(f"{source.name}: turned off ([providers.{key}] enabled = false)")
                elif is_cooling(conn, key, now):
                    until = get_state(conn, key).cooldown_until
                    typer.echo(f"{source.name}: cooling down until {until:%Y-%m-%d %H:%M UTC}; asked after that")
                else:
                    client = make_client(cfg, conn, key, run_id_for(now), policy=policy or ICON_POLICY)
                    try:
                        run = fetch_icons(conn, cfg.cache_dir, {key: client}, now, wait=None)
                    except ProviderBlocked as e:
                        state = record_block(conn, key, now, str(e))
                        typer.echo(f"{source.name} blocked caracole ({e.message}); no more requests to it until "
                                   f"{state.cooldown_until:%Y-%m-%d %H:%M UTC}, and its badge stands in")
                        continue
                    finally:
                        client.close()
                    if run.fetched or run.missing:
                        record_ok(conn, key, now)
                    typer.echo(f"{source.name}: {_outcome(key, run)}")
            todo, page = write_pages(conn, cfg, overrides, utcnow())
        typer.echo(f"Wrote {todo} and {page}")


def _outcome(key: str, run: IconRun) -> str:
    if key in run.fetched:
        return "icon fetched"
    if key in run.missing:
        return "no icon there; its badge stands in"
    if key in run.errors:
        return "couldn't be asked (the log says why, at -v); its badge stands in until the next try"
    return "its request budget is spent; asked on the next run"
