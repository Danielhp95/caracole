"""``caracole harmonica``: how a song's harmonica tabs are read, and a reading pinned (harmonica_cmd.py).

    caracole harmonica "Cowboy Bebop - Spokey Dokey"                          # how each tab is read, and the readings
    caracole harmonica "Cowboy Bebop - Spokey Dokey" --as letters             # read its one tab as letters
    caracole harmonica "A - B" --tab harmonica-2.txt --as signs --symbol "*=bend"   # signs, "*" a bend
    caracole harmonica "Cowboy Bebop - Spokey Dokey" --clear                  # back to caracole's guess

The list only reads, and never waits for caracole's lock; ``--as`` and ``--clear`` write overrides.toml's
``[harmonica]`` and render the song again, under the lock, waiting for it as a lookup does (it is asked for now:
caracole serve's page of readings queues it). The logic is imported inside the command, as every command module
is imported on every start.
"""

from __future__ import annotations

import typer

from caracole.commands._common import fail, load_cfg


def register(app: typer.Typer) -> None:
    @app.command("harmonica")
    def harmonica_cmd(
        ctx: typer.Context,
        song: list[str] = typer.Argument(..., metavar='"ARTIST - TITLE"', help='"Artist - Title", or ARTIST TITLE.'),
        tab: str | None = typer.Option(None, "--tab", metavar="NAME",
                                       help="The song's harmonica tab (harmonica-1.txt); its only one by default."),
        as_: str | None = typer.Option(
            None, "--as", metavar="NOTATION",
            help="Read the tab so, whatever caracole guesses: signs, brackets, letters, signs after, barrett, or "
                 "legend (its own); recorded under \\[harmonica] in overrides.toml."),
        symbol: list[str] = typer.Option(
            [], "--symbol", metavar="SYMBOL=MEANING",
            help="With --as: a symbol of that notation read another way (\"*=bend\", \"(w)=wah\"); repeatable."),
        clear: bool = typer.Option(False, "--clear", help="Take the tab's \\[harmonica] entry out: caracole guesses."),
    ) -> None:
        """Say how a song's harmonica tabs are read, and the readings caracole weighs; or read one as you say, or
        as caracole guesses again."""
        if as_ is not None and clear:
            fail("caracole harmonica takes one of --as and --clear", 2)
        if symbol and as_ is None:
            fail("--symbol needs --as: the notation whose symbol it changes", 2)
        spec = _spec(as_, symbol) if as_ is not None else None
        artist, title = _artist_title(song)
        cfg = load_cfg(ctx)
        from caracole import harmonica_cmd

        display = f"{artist} - {title}"
        if spec is not None:
            harmonica_cmd.pin(cfg, display, tab, spec)
        elif clear:
            harmonica_cmd.clear(cfg, display, tab)
        else:
            harmonica_cmd.show(cfg, display)


def _spec(name: str, symbols: list[str]) -> str | dict[str, str]:
    """The pin ``--as`` and its ``--symbol``s say, checked (viewer/harptab.py ``check_spec``): a usage error else."""
    from caracole.viewer.harptab import check_spec

    spec: str | dict[str, str] = name
    if symbols:
        spec = {"as": name}
        for given in symbols:
            sym, sep, word = given.rpartition("=")
            if not sep or not sym:
                fail(f"--symbol: expected SYMBOL=MEANING (\"*=bend\"), got {given!r}", 2)
            spec[sym] = word
    try:
        check_spec(spec)
    except ValueError as e:
        fail(f"--as: {e}" if not symbols else f"--symbol: {e}", 2)
    return spec


def _artist_title(words: list[str]) -> tuple[str, str]:
    if len(words) == 1:
        artist, sep, title = words[0].partition(" - ")
    elif len(words) == 2:
        (artist, title), sep = words, " - "
    else:
        artist, sep, title = "", "", ""
    if not sep or not artist.strip() or not title.strip():
        fail(f'caracole harmonica takes a song as "Artist - Title", or as ARTIST TITLE, not {" ".join(words)!r}', 2)
    return artist.strip(), title.strip()
