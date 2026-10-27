"""``caracole songbook``: songbooks of your songs, kept in songbooks.toml, made into Library/_songbooks/.

    caracole songbook make NAME SONG...          a songbook of these songs, in this order
    caracole songbook list                       every songbook, and what it holds
    caracole songbook show NAME                  its songs, in order, the missing ones marked
    caracole songbook add NAME SONG...           songs at its end
    caracole songbook remove NAME SONG...        songs out of it
    caracole songbook move NAME SONG POSITION    a song to a place, 1 the first
    caracole songbook set NAME SONG [--key K] [--mode M] [--capo N] [--instrument I] | --clear
                                                 where it plays a song: its key, mode, capo and instrument
    caracole songbook rename NAME NEW            another name, and its files to its new folder
    caracole songbook delete NAME                the songbook, and the files caracole made of it
    caracole songbook render [NAME] [--force]    its files (every songbook's), when they need it

A SONG is "Artist - Title", found the way other commands find songs (accents, case,
Traditional or Simplified characters), or by a search of your library that one song
answers well ("ban ma ban ma"); a song the library hasn't got is refused, with what you
may have meant; ``remove`` and ``move`` look among the songbook's own songs first, by
"Artist - Title" alone. A song of songbooks.toml is found by its "Artist - Title" alone,
never by a search: one gone from the library is missing. A change writes songbooks.toml,
makes the songbook's files again and rewrites the library pages, holding caracole's lock;
``list`` and ``show`` only read. A change (``render`` too) is asked for now, so it takes the lock
as a lookup does (``exclusive(..., interactive=True)``): a nightly run holding it hands it over at
its next pause, or between two songs, rather than making the songbook wait for the whole run. A
songbooks.toml that can't be read exits 2, naming it and the line. Every command module is
imported on every start, so the songbook code is imported inside the commands.
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
from caracole.logs import plural

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
        with exclusive(cfg, "songbook make", interactive=True), closing(open_db(cfg)) as conn:
            found = _songs(conn, songs)
            made = _do(lambda: make_songbook(_file(cfg), name, [f.song.display for f in found]))
            typer.echo(f'Made the songbook "{made.name}": {plural(len(made.songs), "song")}.')
            seen: set[int] = set()
            for f in found:  # a song named twice is in it once
                if f.song.id in seen:
                    typer.echo(f"{f.song.display} is in it already")
                seen.add(f.song.id)
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
                typer.echo(f"{b.name}: {plural(len(b.songs), "song")}{without} · {', '.join(files) or 'not made yet'}")

    @book.command("show")
    def show_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name.")) -> None:
        """A songbook's songs, in order, where it plays those with a setting or a version of their own, and where
        its files are."""
        from caracole.songbook import FOLDER, plays_in, songbook_entries
        from caracole.viewer.version import Version

        cfg = load_cfg(ctx)
        b = _book(_books(cfg), name)
        overrides = load_ovr(cfg)
        with closing(open_db(cfg)) as conn:
            entries = songbook_entries(conn, cfg.library_dir, overrides, b)
        typer.echo(f"{b.name}: {plural(len(entries), "song")}")
        for n, e in enumerate(entries, start=1):
            shown = e.song.display if e.song is not None else e.text
            where = plays_in(e) if e.setting or e.keeps_key or e.version != Version() else None
            typer.echo(f"  {n}. {shown}" + (f" ({where})" if where else "")
                       + (f" (missing: {e.missing})" if e.missing else ""))
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
        with exclusive(cfg, "songbook add", interactive=True), closing(open_db(cfg)) as conn:
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
        with exclusive(cfg, "songbook remove", interactive=True), closing(open_db(cfg)) as conn:
            b = _book(_books(cfg), name)
            removed = _do(lambda: remove_from_songbook(_file(cfg), b.name, _names(conn, b, songs)))
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
        with exclusive(cfg, "songbook move", interactive=True), closing(open_db(cfg)) as conn:
            b = _book(_books(cfg), name)
            entry = _entry_for(conn, b, song)
            to = _do(lambda: move_in_songbook(_file(cfg), b.name, entry, position))
            shown = next((e.song.display for e in songbook_entries(conn, cfg.library_dir, overrides, b)
                          if e.text == entry and e.song is not None), entry)
            typer.echo(f"Moved {shown} to {to}")
            _render(cfg, conn, b.name)

    @book.command("set")
    def set_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name."),
                song: str = typer.Argument(..., metavar='"ARTIST - TITLE"', help="A song of the songbook."),
                key: str | None = typer.Option(None, "--key", help='The key it is played in here: "G", "F#", "Bb".'),
                mode: str | None = typer.Option(None, "--mode", help="Its mode: ionian, dorian, ..., aeolian, locrian."),
                capo: int | None = typer.Option(None, "--capo", min=0, max=11, help="The fret of its capo."),
                instrument: str | None = typer.Option(
                    None, "--instrument",
                    help="The instrument it is played on: guitar, ukulele, ukulele-low-g, baritone, piano, harmonica, "
                         "flute or recorder. Its PDF draws that instrument's chords, and its phone page opens there."),
                clear: bool = typer.Option(False, "--clear", help="Take its setting off: the sheet's own.")) -> None:
        """Set the key, mode, capo or instrument a song is played in within a songbook (the parts you give change;
        the others stay), or --clear its setting. A key or a mode with no capo keeps the capo it plays at now; on an
        instrument with no capo (the piano, the harmonica, the winds) the key is the key it sounds in, and another
        instrument with no --key keeps the pitch it plays at."""
        from caracole.songbook import Setting, check_setting, on_instrument, plays_in, set_song_setting, with_capo

        given = key is not None or mode is not None or capo is not None or instrument is not None
        if clear == given:
            fail("Give --key, --mode, --capo or --instrument to set, or --clear to take the setting off.", 2)
        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook set", interactive=True), closing(open_db(cfg)) as conn:
            overrides = load_ovr(cfg)
            b = _book(_books(cfg), name)
            entry = _entry_for(conn, b, song)
            old = next((s.setting for s in b.songs if s.text == entry), None) or Setting()
            new = None
            if not clear:
                given_setting = _do(lambda: check_setting(key[:1].upper() + key[1:] if key else old.key,
                                                          mode.lower() if mode else old.mode,
                                                          old.capo if capo is None else capo,
                                                          instrument.lower() if instrument else old.instrument))
                if instrument is not None:  # at the pitch it plays at now, as the Songbooks tab's menus keep it
                    given_setting = on_instrument(_played(conn, cfg, overrides, b, entry, old or None), given_setting,
                                                  key_given=key is not None, capo_given=capo is not None)
                new = with_capo(_played(conn, cfg, overrides, b, entry, None), given_setting, overrides)
            _do(lambda: set_song_setting(_file(cfg), b.name, entry, new))
            played = _played(conn, cfg, overrides, b, entry, new)
            shown = played.song.display if played.song is not None else entry
            typer.echo(f"{shown}: " + (_setting_line(new) if new else "the sheet's own setting"))
            if (where := plays_in(played)) is not None:
                typer.echo(f"In the songbook: {where}")
            _render(cfg, conn, b.name)

    @book.command("rename")
    def rename_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name."),
                   new: str = typer.Argument(..., help="Its new name.")) -> None:
        """Give a songbook another name; its files move to the folder of that name."""
        from caracole.songbook import rename_songbook

        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook rename", interactive=True), closing(open_db(cfg)) as conn:
            b = _book(_books(cfg), name)
            renamed = _do(lambda: rename_songbook(_file(cfg), b.name, new))
            typer.echo(f'Renamed the songbook "{b.name}" to "{renamed.name}".')
            _render(cfg, conn, renamed.name)

    @book.command("delete")
    def delete_cmd(ctx: typer.Context, name: str = typer.Argument(..., help="The songbook's name.")) -> None:
        """Delete a songbook, and the files caracole made of it (a file of yours there stays)."""
        from caracole.songbook import delete_songbook

        cfg = load_cfg(ctx)
        with exclusive(cfg, "songbook delete", interactive=True), closing(open_db(cfg)) as conn:
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
        with exclusive(cfg, "songbook render", interactive=True), closing(open_db(cfg)) as conn:
            only = _book(_books(cfg), name).name if name is not None else None
            stats = _render(cfg, conn, only, force=force, quiet=True, exit_on_failure=False)
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


def _names(conn: sqlite3.Connection, book, texts: list[str]) -> list[str]:
    """What to look for in the songbook, one for each text: the songbook's own entry when the text
    names one by its "Artist - Title" (``same_entry``), as the page's buttons send it; only when it
    names none, the library's name for the song a search of the library finds (``find_library_song``),
    else the text. A song gone from the library is never taken for one whose title its own holds."""
    return [_entry_for(conn, book, text) for text in texts]


def _entry_for(conn: sqlite3.Connection, book, text: str) -> str:
    """The songbook's entry ``text`` stands for (see ``_names``), or ``text`` when there is none."""
    from caracole.songbook import find_library_song, same_entry

    entry = next((e for e in book.texts if same_entry(e, text)), None)
    if entry is not None:
        return entry
    found = find_library_song(conn, text)
    if found is not None:
        return next((e for e in book.texts if same_entry(e, found.song.display)), found.song.display)
    return text


def _played(conn: sqlite3.Connection, cfg: Config, overrides, book, entry: str, setting):
    """The songbook's song ``entry`` as its files play it with ``setting`` (``songbook.Entry``)."""
    from dataclasses import replace

    from caracole.songbook import SongbookSong, songbook_entries

    (played,) = songbook_entries(conn, cfg.library_dir, overrides, replace(book, songs=(SongbookSong(entry, setting),)))
    return played


def _say_found(texts: list[str], found: list[Found]) -> None:
    for text, f in zip(texts, found):
        if not f.exact:
            typer.echo(f'Took {f.song.display} for "{text}"')


def _setting_line(setting) -> str:
    """The setting as songbooks.toml holds it, in words: "key G, dorian, capo 2", "on the ukulele"; "no capo" for a
    capo of 0, a setting's choice, as its menu names it (where it plays then says nothing of a capo:
    ``songbook.plays_in``)."""
    from caracole.viewer.version import instrument_of, instrument_words

    capo = "" if setting.capo is None else "no capo" if setting.capo == 0 else f"capo {setting.capo}"
    played = instrument_of(setting.instrument)
    on = f"on the {instrument_words(played)}" if played is not None else ""
    parts = [p for p in (f"key {setting.key}" if setting.key else "", setting.mode or "", capo, on) if p]
    return ", ".join(parts) or "the sheet's own setting"


def _files(cfg: Config, folder: str) -> list[str]:
    from caracole.songbook import FOLDER, OUTPUTS

    where = cfg.library_dir / FOLDER / folder
    order = ("songbook.pdf", "songbook.html", "songbook.cho")
    return [name for name in order if name in OUTPUTS and (where / name).is_file() and not (where / name).is_symlink()]


def _render(cfg: Config, conn: sqlite3.Connection, only: str | None, *, force: bool = False,
            quiet: bool = False, exit_on_failure: bool = True) -> SongbookStats:
    """Make the songbook's files (``only``: that one, else every one; the files of songbooks gone go
    too), then rewrite the library pages, which list the songbooks. A file that couldn't be made exits
    1 once the pages are written (``exit_on_failure``), as caracole render does: a change to
    songbooks.toml stays made, and caracole serve's request shows it failed."""
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
    if stats.failed and exit_on_failure:
        raise typer.Exit(1)
    return stats
