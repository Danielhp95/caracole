"""The ``caracole`` command line.

Commands live in ``caracole.commands.<area>`` modules, each exposing
``register(app)``. ``build_app`` discovers them, so areas of the program can be
added without editing this file.

The root callback sets the log up for every command (``caracole.logs``): what a
command reports goes to stdout, its log to stderr, at the verbosity of ``-v``,
``-vv`` or ``-q``. ``main`` turns a bug into one line that says so, then its
traceback, and exit status 1.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import typer

from caracole import __version__, logs


@dataclass
class AppState:
    """Options from the root callback, available to commands as ``ctx.obj``."""

    config_path: Path | None = None
    verbosity: int = logs.NORMAL  # logs.QUIET, NORMAL, VERBOSE or DEBUG


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"caracole {__version__}")
        raise typer.Exit()


def _command_modules() -> list[str]:
    import caracole.commands as pkg

    names = sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.name.startswith("_"))
    return [f"caracole.commands.{name}" for name in names]


def build_app(extra_modules: Iterable[str] = ()) -> typer.Typer:
    app = typer.Typer(
        name="caracole",
        help="Build a private library of chord sheets, lyrics and guitar parts.",
        no_args_is_help=True,
        add_completion=False,
        # A traceback goes to the log as plain text (``main``), never rich's, with its local variables.
        pretty_exceptions_enable=False,
    )

    @app.callback()
    def root(
        ctx: typer.Context,
        config: Path | None = typer.Option(
            None, "--config", "-c", envvar="CARACOLE_CONFIG", help="Path to caracole.toml."
        ),
        verbose: int = typer.Option(
            0, "--verbose", "-v", count=True,
            help="Say more on stderr: -v adds a line per request, -vv debugging and other libraries' logs.",
        ),
        quiet: bool = typer.Option(False, "--quiet", "-q", help="Say only what went wrong, or needs you."),
        version: bool = typer.Option(
            False, "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ) -> None:
        level = logs.verbosity(verbose, quiet)
        ctx.obj = AppState(config_path=config, verbosity=level)
        logs.setup(level)
        ctx.call_on_close(logs.teardown)

    for name in [*_command_modules(), *extra_modules]:
        importlib.import_module(name).register(app)
    return app


app = build_app()


def main() -> None:
    try:
        app()
    except Exception as e:  # a bug: one line for people, then the traceback, for whoever fixes it
        logs.say(logging.ERROR, f"caracole stopped on an unexpected error: {type(e).__name__}: {e}. That's a bug "
                 "in caracole; its traceback follows.", exc_info=e)
        sys.exit(1)
