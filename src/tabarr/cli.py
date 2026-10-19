"""The ``tabarr`` command line.

Commands live in ``tabarr.commands.<area>`` modules, each exposing
``register(app)``. ``build_app`` discovers them, so areas of the program can be
added without editing this file.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import typer

from tabarr import __version__


@dataclass
class AppState:
    """Options from the root callback, available to commands as ``ctx.obj``."""

    config_path: Path | None = None


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tabarr {__version__}")
        raise typer.Exit()


def _command_modules() -> list[str]:
    import tabarr.commands as pkg

    names = sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.name.startswith("_"))
    return [f"tabarr.commands.{name}" for name in names]


def build_app(extra_modules: Iterable[str] = ()) -> typer.Typer:
    app = typer.Typer(
        name="tabarr",
        help="Build a private library of chord sheets, lyrics and guitar parts.",
        no_args_is_help=True,
        add_completion=False,
    )

    @app.callback()
    def root(
        ctx: typer.Context,
        config: Path | None = typer.Option(
            None, "--config", "-c", envvar="TABARR_CONFIG", help="Path to tabarr.toml."
        ),
        version: bool = typer.Option(
            False, "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ) -> None:
        ctx.obj = AppState(config_path=config)

    for name in [*_command_modules(), *extra_modules]:
        importlib.import_module(name).register(app)
    return app


app = build_app()


def main() -> None:
    app()
