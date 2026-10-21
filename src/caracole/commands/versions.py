"""``caracole versions``: a song's Ultimate Guitar chords versions, kept, chosen or cleared (versions_cmd.py).

    caracole versions "Oasis - Wonderwall"                  # every version, in rank order
    caracole versions "Oasis - Wonderwall" --keep 39144     # keep one beside the sheet, fetched now
    caracole versions "Oasis - Wonderwall" --choose 39144   # make it the sheet: caracole get --tab
    caracole versions "Oasis - Wonderwall" --clear          # back to caracole's pick

The list only reads, and never waits for caracole's lock; ``--keep``, ``--choose`` and ``--clear``
are lookups (one song, now, at the interactive pace). ``--progress`` adds a JSON line per event, as
``caracole get --progress`` does, for caracole serve. The logic is imported inside the command, as
every command module is imported on every start.
"""

from __future__ import annotations

import typer

from caracole.commands._common import fail, load_cfg


def register(app: typer.Typer) -> None:
    @app.command("versions")
    def versions_cmd(
        ctx: typer.Context,
        song: list[str] = typer.Argument(..., metavar='"ARTIST - TITLE"', help='"Artist - Title", or ARTIST TITLE.'),
        keep: str | None = typer.Option(None, "--keep", metavar="TAB",
                                        help="Keep this version beside the sheet, fetched now (its id or address)."),
        choose: str | None = typer.Option(None, "--choose", metavar="TAB",
                                          help="Make this version the sheet: recorded under \\[pin] in overrides.toml."),
        clear: bool = typer.Option(False, "--clear",
                                   help="Take the song's chords pin out of \\[pin]: caracole's pick is the sheet again."),
        progress: bool = typer.Option(False, "--progress", help="A JSON line per event too, for caracole serve."),
    ) -> None:
        """List a song's Ultimate Guitar chords versions; keep one beside the sheet, choose one, or clear your choice."""
        if sum(x is not None for x in (keep, choose)) + clear > 1:
            fail("caracole versions takes one of --keep, --choose and --clear", 2)
        artist, title = _artist_title(song)
        display = f"{artist} - {title}"
        cfg = load_cfg(ctx)
        from caracole import versions_cmd

        if keep is not None:
            versions_cmd.keep(cfg, display, _tab(keep, "--keep"), progress=progress)
        elif choose is not None:
            versions_cmd.choose(cfg, display, _tab(choose, "--choose"), progress=progress)
        elif clear:
            versions_cmd.clear(cfg, display, progress=progress)
        else:
            versions_cmd.show(cfg, display)


def _artist_title(words: list[str]) -> tuple[str, str]:
    if len(words) == 1:
        artist, sep, title = words[0].partition(" - ")
    elif len(words) == 2:
        (artist, title), sep = words, " - "
    else:
        artist, sep, title = "", "", ""
    if not sep or not artist.strip() or not title.strip():
        fail(f'caracole versions takes a song as "Artist - Title", or as ARTIST TITLE, not {" ".join(words)!r}', 2)
    return artist.strip(), title.strip()


def _tab(text: str, option: str) -> int:
    from caracole.overrides import OverridesError, tab_id_from_url

    try:
        return tab_id_from_url(text)
    except OverridesError as e:
        fail(f"{option}: {e}", 2)
