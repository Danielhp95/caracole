"""Helpers shared by command modules: config, database, clients, clock."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import NoReturn

import httpx
import typer

from tabarr import db
from tabarr.config import Config, ConfigError, load_config
from tabarr.health import EventLog
from tabarr.http import PoliteClient
from tabarr.overrides import Overrides, OverridesError, load_overrides


def fail(message: str, code: int = 1) -> NoReturn:
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(code)


def load_cfg(ctx: typer.Context) -> Config:
    path = ctx.obj.config_path if ctx.obj is not None else None
    try:
        return load_config(path)
    except ConfigError as e:
        fail(f"config: {e}", 2)


def open_db(cfg: Config) -> sqlite3.Connection:
    return db.connect(cfg.db_path)


def load_ovr(cfg: Config) -> Overrides:
    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError as e:
        fail(f"overrides: {e}", 2)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def run_id_for(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def transport_for(provider: str) -> httpx.BaseTransport | None:
    """The transport for a provider's client; tests monkeypatch this to inject fakes."""
    return None


def make_client(cfg: Config, conn: sqlite3.Connection, provider: str, run_id: str) -> PoliteClient:
    """A polite client for one provider and one run, logging every request to ``events``."""
    return PoliteClient(
        provider,
        cfg.provider(provider),
        cfg.cache_dir,
        user_agent=cfg.user_agent,
        transport=transport_for(provider),
        on_event=EventLog(conn, run_id),
    )
