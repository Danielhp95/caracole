"""CLI command modules.

Every public module in this package defines ``register(app: typer.Typer) -> None``
and is picked up by ``tabarr.cli`` automatically, so adding a command never
touches a shared file.
"""
