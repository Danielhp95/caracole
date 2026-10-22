"""``caracole autochords``: chord sheets from audio you bought, for songs nobody has charted.

torch, librosa and beat_this exist only in the flake's ``packages.autochords``.
Every command module is imported on every start, so this one never imports
them; it only asks whether they could be imported.

The command exits 1 only when auto-chords can't work here: those packages are
missing, the model files are missing or unusable, or a sheet can't be kept in
the library. A purchase it can't read fails the song alone, with exit 0: the
to-do page lists it, and it is tried again once its file changes, so a file
that will never decode doesn't fail the unit (and alert you) every night.

The unit runs after the nightly run has written _todo.md and index.html, so
the command writes both again, with its own sheets and failures. It holds
caracole's lock while it works, so it waits for another caracole writing the
library (a ``caracole-admin`` command, say), and hands it to a waiting lookup
between two songs (``_common.hand_over``), since a song takes minutes.
"""

from __future__ import annotations

from importlib.util import find_spec

import typer

from caracole import logs
from caracole.commands import _common
from caracole.commands._common import (
    exclusive,
    fail,
    load_cfg,
    load_ovr,
    open_db,
    utcnow,
    write_pages,
)

MODEL_PACKAGES = ("torch", "librosa", "beat_this")
NOT_BUILT = "this caracole was built without auto-chords; use the flake's packages.autochords"


def missing_packages() -> list[str]:
    """The model packages this Python cannot import. Nothing is imported to find out."""
    return [name for name in MODEL_PACKAGES if find_spec(name) is None]


def register(app: typer.Typer) -> None:
    @app.command("autochords")
    def autochords_cmd(ctx: typer.Context) -> None:
        """Write 'sheet (auto).txt' from purchased audio, for songs with no human sheet."""
        missing = missing_packages()
        if missing:
            fail(f"{NOT_BUILT} (missing: {', '.join(missing)})")
        from caracole.autochords.run import autochords_pending
        from caracole.music import scan_music

        logs.at_least(logs.VERBOSE)  # a line per song: its progress, minutes apart
        cfg = load_cfg(ctx)
        overrides = load_ovr(cfg)
        conn = open_db(cfg)
        with exclusive(cfg, "autochords"):
            # A track dropped in after the night's run, with the unit started by hand, is
            # linked here first.
            music = scan_music(conn, cfg.music_dir)
            files = "file" if music.seen == 1 else "files"
            typer.echo(f"Music: {music.seen} {files}, {music.matched} linked")
            # A song takes minutes: a lookup waiting for the lock goes between two of them.
            handed = _common.handoffs()
            stats = autochords_pending(conn, cfg, overrides=overrides,
                                       between=lambda: _common.hand_over(cfg, conn))
            typer.echo(f"auto-chords: {stats.summary()}")
            write_pages(conn, cfg, _common.overrides_since(cfg, overrides, handed), utcnow())
        if stats.errors:  # the setup's problems; stats.failures are listed on the to-do page
            raise typer.Exit(1)
