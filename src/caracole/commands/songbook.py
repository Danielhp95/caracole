"""``caracole songbook``: songbooks of your songs, kept in songbooks.toml, made into Library/_songbooks/.

    caracole songbook make NAME SONG...          a songbook of these songs, in this order
    caracole songbook list                       every songbook, and what it holds
    caracole songbook show NAME                  its songs, in order, the missing ones marked
    caracole songbook add NAME SONG...           songs at its end
    caracole songbook remove NAME SONG...        songs out of it
    caracole songbook move NAME SONG POSITION    a song to a place, 1 the first
    caracole songbook rename NAME NEW            another name, and its files to its new folder
    caracole songbook delete NAME                the songbook, and the files caracole made of it
    caracole songbook render [NAME] [--force]    its files (every songbook's), when they need it

A SONG is "Artist - Title", found the way other commands find songs (accents, case,
Traditional or Simplified characters), or by a search of your library that one song
answers well ("ban ma ban ma"); a song the library hasn't got is refused, with what you
may have meant. A change writes songbooks.toml, makes the songbook's files again and
rewrites the library pages, holding caracole's lock; ``list`` and ``show`` only read. A
songbooks.toml that can't be read exits 2, naming it and the line. Every command module
is imported on every start, so the songbook code is imported inside the commands.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, NoReturn

import typer

from caracole.commands._common import (
    exclusive,
    fail,
    load_cfg,
    load_ovr,
    open_db,
    utcnow,
    write_pages,
)

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.songbook import Found, SongbookError, SongbookStats

SONGS = typer.Argument(..., metavar='"ARTIST - TITLE"...', help='Songs of your library, each "Artist - Title".')


def register(app: typer.Typer) -> None:
    book = typer.Typer(help="Songbooks: songs of yours, in order, as a PDF, a phone page and a ChordPro file.",
                       no_args_is_help=True)
    app.add_typer(book, name="songbook")

    @book.command("make")
    def make_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name."),
                 songs: list[str] = SONGS) -> None:
        """Make a songbook of these songs, in this order, and its files."""
        from caracole.songbook import make_songbook

        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook make"), closing(open_db(cfg)) as conn:
            found = _songs(conn, songs)
            made = _do(lambda: make_songbook(_file(cfg), name, [f.song.display for f in found]))
            typer.echo(f'Made the songbook "{made.name}": {_count(len(made.songs))}.')
            _say_found(songs, found)
            _render(cfg, conn, made.name)

    @book.command("list")
    def list_cmd(ctx: typer.Context) -> None:
        """Every songbook: its songs counted, and its files."""
        from caracole.songbook import songbook_entries

        cfg = load_cfg(ctx)
        books = _books(cfg)
        if not books:
            typer.echo('No songbooks yet: make one with caracole songbook make NAME "ARTIST - TITLE"...')
            return
        overrides = load_ovr(cfg)
        with closing(open_db(cfg)) as conn:
            for b in books:
                missing = sum(1 for e in songbook_entries(conn, cfg.library_dir, overrides, b) if e.cho is None)
                without = f", {missing} without a sheet" if missing else ""
                files = _files(cfg, b.folder)
                typer.echo(f"{b.name}: {_count(len(b.songs))}{without} · {', '.join(files) or 'not made yet'}")

    @book.command("show")
    def show_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name.")) -> None:
        """A songbook's songs, in order, and where its files are."""
        from caracole.songbook import FOLDER, songbook_entries

        cfg = load_cfg(ctx)
        b = _book(_books(cfg), name)
        overrides = load_ovr(cfg)
        with closing(open_db(cfg)) as conn:
            entries = songbook_entries(conn, cfg.library_dir, overrides, b)
        typer.echo(f"{b.name}: {_count(len(entries))}")
        for n, e in enumerate(entries, start=1):
            shown = e.song.display if e.song is not None else e.text
            shift = f" (transposed {e.transpose:+d})" if e.transpose else ""
            typer.echo(f"  {n}. {shown}{shift}" + (f" (missing: {e.missing})" if e.missing else ""))
        folder = cfg.library_dir / FOLDER / b.folder
        files = _files(cfg, b.folder)
        if files:
            typer.echo("Files:\n" + "\n".join(f"  {folder / f}" for f in files))
        else:
            typer.echo("Not made yet: caracole songbook render makes its files.")

    @book.command("add")
    def add_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name."),
                songs: list[str] = SONGS) -> None:
        """Add songs at the end of a songbook."""
        from caracole.songbook import add_to_songbook, same_entry

        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook add"), closing(open_db(cfg)) as conn:
            b = _book(_books(cfg), name)
            found = _songs(conn, songs)
            added = _do(lambda: add_to_songbook(_file(cfg), b.name, [f.song.display for f in found]))
            for f in found:
                if any(same_entry(f.song.display, a) for a in added):
                    typer.echo(f"Added {f.song.display}")
                else:
                    typer.echo(f"{f.song.display} is in it already")
            _say_found(songs, found)
            _render(cfg, conn, b.name)

    @book.command("remove")
    def remove_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name."),
                   songs: list[str] = SONGS) -> None:
        """Take songs out of a songbook; a song no longer in the library goes by its name."""
        from caracole.songbook import remove_from_songbook

        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook remove"), closing(open_db(cfg)) as conn:
            b = _book(_books(cfg), name)
            removed = _do(lambda: remove_from_songbook(_file(cfg), b.name, _names(conn, songs)))
            for entry in removed:
                typer.echo(f"Removed {entry}")
            if not removed:
                fail(f'None of these is in the songbook "{b.name}": caracole songbook show lists its songs.')
            _render(cfg, conn, b.name)

    @book.command("move")
    def move_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name."),
                 song: str = typer.Argument(..., metavar='"ARTIST - TITLE"', help="A song of the songbook."),
                 position: int = typer.Argument(..., min=1, help="Where it goes: 1 is the first song.")) -> None:
        """Move a song of a songbook to a place in it."""
        from caracole.songbook import move_in_songbook, songbook_entries

        cfg = load_cfg(ctx)
        overrides = load_ovr(cfg)
        with exclusive(cfg, "songbook move"), closing(open_db(cfg)) as conn:
            b = _book(_books(cfg), name)
            names = _names(conn, [song])
            entry = next((e for e in b.songs if any(_same(e, n) for n in names)), names[0])
            to = _do(lambda: move_in_songbook(_file(cfg), b.name, entry, position))
            shown = next((e.song.display for e in songbook_entries(conn, cfg.library_dir, overrides, b)
                          if e.text == entry and e.song is not None), entry)
            typer.echo(f"Moved {shown} to {to}")
            _render(cfg, conn, b.name)

    @book.command("rename")
    def rename_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name."),
                   new: str = typer.Argument(..., help="Its new name.")) -> None:
        """Give a songbook another name; its files move to the folder of that name."""
        from caracole.songbook import rename_songbook

        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook rename"), closing(open_db(cfg)) as conn:
            b = _book(_books(cfg), name)
            renamed = _do(lambda: rename_songbook(_file(cfg), b.name, new))
            typer.echo(f'Renamed the songbook "{b.name}" to "{renamed.name}".')
            _render(cfg, conn, renamed.name)

    @book.command("delete")
    def delete_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name.")) -> None:
        """Delete a songbook, and the files caracole made of it (a file of yours there stays)."""
        from caracole.songbook import delete_songbook

        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook delete"), closing(open_db(cfg)) as conn:
            b = _book(_books(cfg), name)
            _do(lambda: delete_songbook(_file(cfg), b.name))
            typer.echo(f'Deleted the songbook "{b.name}".')
            _render(cfg, conn, b.name)

    @book.command("render")
    def render_cmd(ctx: typer.Context,
                   name: str | None = typer.Argument(None, help="One songbook; every one without it."),
                   force: bool = typer.Option(False, "--force", help="Make every file again, up to date or not.")
                   ) -> None:
        """Make the songbooks' files, those that need it: songbook.pdf, songbook.html and songbook.cho.

        Exits 1 when a songbook's file couldn't be made; a warning says which and why.
        """
        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook render"), closing(open_db(cfg)) as conn:
            only = _book(_books(cfg), name).name if name is not None else None
            stats = _render(cfg, conn, only, force=force, quiet=True)
        typer.echo(songbooks_line(stats))
        if stats.failed:
            raise typer.Exit(1)


# --- shared by the commands --------------------------------------------------------------------


def songbooks_line(stats: SongbookStats) -> str:
    """How a pass over the songbooks went, in one line."""
    return f"{stats.rendered} rendered, {stats.skipped} up to date, {len(stats.failed)} failed"


def _file(cfg: Config):
    from caracole.songbook import songbooks_file

    return songbooks_file(cfg.library_dir)


def _fail(e: SongbookError) -> NoReturn:
    from caracole.songbook import SongbookFileError

    fail(str(e), 2 if isinstance(e, SongbookFileError) else 1)


def _do(change):
    """``change()``, a write to songbooks.toml; its SongbookError ends the command."""
    from caracole.songbook import SongbookError

    try:
        return change()
    except SongbookError as e:
        _fail(e)


def _books(cfg: Config):
    from caracole.songbook import load_songbooks

    return _do(lambda: load_songbooks(_file(cfg)))


def _book(books, name: str):
    from caracole.songbook import find_songbook

    found = find_songbook(books, name)
    if found is None:
        listed = ", ".join(f'"{b.name}"' for b in books)
        fail(f'No songbook named "{" ".join(name.split())}"' + (f": there are {listed}." if listed else "."))
    return found


def _songs(conn: sqlite3.Connection, texts: list[str]) -> list[Found]:
    """The songs the texts name; a song the library lacks ends the command, with a hint."""
    from caracole.songbook import library_songs

    return _do(lambda: library_songs(conn, texts))


def _names(conn: sqlite3.Connection, texts: list[str]) -> list[str]:
    """What to look for in a songbook: each text, and the library's name for the song it names."""
    from caracole.songbook import find_library_song

    names: list[str] = []
    for text in texts:
        names.append(text)
        found = find_library_song(conn, text)
        if found is not None:
            names.append(found.song.display)
    return names


def _same(a: str, b: str) -> bool:
    from caracole.songbook import same_entry

    return same_entry(a, b)


def _say_found(texts: list[str], found: list[Found]) -> None:
    for text, f in zip(texts, found):
        if not f.exact:
            typer.echo(f'Took {f.song.display} for "{text}"')


def _count(n: int) -> str:
    return f"{n} song" if n == 1 else f"{n} songs"


def _files(cfg: Config, folder: str) -> list[str]:
    from caracole.songbook import FOLDER, OUTPUTS

    where = cfg.library_dir / FOLDER / folder
    order = ("songbook.pdf", "songbook.html", "songbook.cho")
    return [name for name in order if name in OUTPUTS and (where / name).is_file() and not (where / name).is_symlink()]


def _render(cfg: Config, conn: sqlite3.Connection, only: str | None, *, force: bool = False,
            quiet: bool = False) -> SongbookStats:
    """Make the songbook's files (``only``: that one, else every one; the files of songbooks gone go
    too), then rewrite the library pages, which list the songbooks."""
    from caracole import songbook

    overrides = load_ovr(cfg)
    stats = songbook.render_songbooks(conn, cfg, overrides, force=force, only=only)
    if stats.error:
        write_pages(conn, cfg, overrides, utcnow())
        fail(stats.error, 2)
    if not quiet and only is not None:
        b = songbook.find_songbook(songbook.load_songbooks(_file(cfg)), only)
        if b is not None:
            for e in songbook.songbook_entries(conn, cfg.library_dir, overrides, b):
                if e.missing == songbook.MISSING_SHEET:
                    typer.echo(f"{e.song.display if e.song else e.text} has no sheet yet: it is named missing "
                               "until it has one")
            files = _files(cfg, b.folder)
            where = cfg.library_dir / songbook.FOLDER / b.folder
            typer.echo(f"Wrote {where}: {', '.join(files)}" if files else f"Nothing written in {where}")
        if stats.failed:
            typer.echo("Some of its files couldn't be made: the warning above says why.")
    write_pages(conn, cfg, overrides, utcnow())
    return stats
