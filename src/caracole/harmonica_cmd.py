"""``caracole harmonica``: how a song's harmonica tabs are read (viewer/harptab.py), and how you have one read.

- ``show``: each tab the song keeps (``inbox.harmonica_files``), how it is read now (``Reading.said``, its source and
  its Q), and every reading caracole weighs for it, best first (``harptab.readings``), each by the pin that reads it
  so (``spec_of``). It only reads: no lock.
- ``pin``: the tab read as ``spec`` says, whatever caracole guesses: overrides.toml's ``[harmonica]``
  (``overrides.add_harmonica``), then the song rendered again (``render_all`` for it alone: its tab's page, and its
  sheet's viewers, whose overlay starts on the harp the tab plays on) and the library's pages written again. A pin by
  the tab's own legend needs a tab with one.
- ``clear``: the tab's ``[harmonica]`` entry out, then the same: caracole guesses how it is read again.

Both write the library, so under caracole's lock, which they wait for as a lookup does (``exclusive(...,
interactive=True)``): caracole serve's page of readings queues them, asked for now. A usage error (a tab the song
hasn't got, a legend the tab hasn't got) exits 2 and writes nothing.
"""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING, Any

import typer

from caracole.commands._common import exclusive, fail, load_ovr, open_db, song_named, utcnow, write_pages

if TYPE_CHECKING:
    import sqlite3

    from caracole.config import Config
    from caracole.inbox import HarmonicaFile
    from caracole.songs import Song

SOURCES = {"legend": "from the tab's own legend", "pinned": "as you set it", "guessed": "guessed"}


def spec_words(spec: Any) -> str:
    """A pin in a few words: "letters", "legend", "signs, *=bend"."""
    if isinstance(spec, str):
        return spec
    return ", ".join([spec.get("as", "signs"), *(f"{k}={v}" for k, v in spec.items() if k != "as")])


def tab_text(cfg: Config, conn: sqlite3.Connection, song: Song, tab: HarmonicaFile) -> str | None:
    """The tab's text, as the library holds it (read without following a link), or None when it can't be read."""
    from caracole.library import kept_files, read_regular

    kept = next((f for f in kept_files(conn, song.id) if f.name == tab.name), None)
    if kept is None:
        return None
    try:
        return read_regular(cfg.library_dir / kept.path).decode("utf-8", errors="replace")
    except OSError:
        return None


def show(cfg: Config, display: str) -> None:
    """Each of the song's harmonica tabs, how it is read, and the readings caracole weighs for it."""
    from caracole.inbox import harmonica_files
    from caracole.viewer.harptab import parse, pinned, readings, spec_of

    overrides = load_ovr(cfg)
    with closing(open_db(cfg)) as conn:
        song = song_named(conn, display, overrides)
        tabs = harmonica_files(conn, song.id)
        texts = [(tab, tab_text(cfg, conn, song, tab)) for tab in tabs]
    if not tabs:
        typer.echo(f"{song.display} keeps no harmonica tab.")
        return
    for tab, text in texts:
        if text is None:
            typer.echo(f"{tab.name}: can't be read")
            continue
        pin = overrides.harmonica.get(song.key, {}).get(tab.name)
        read = parse(text, harp=tab.harp, notation=pinned(pin, text) if pin is not None else None).reading
        said = read.said() or "no hole read"
        typer.echo(f"{tab.name}: read as {said}, {SOURCES[read.source]} (Q {read.q:.2f})")
        for other in readings(text, harp=tab.harp):
            typer.echo(f"  {spec_words(spec_of(other)):<12} Q {other.q:.2f}  {other.said()}")


def _tab(conn: sqlite3.Connection, song: Song, name: str | None) -> HarmonicaFile:
    """The song's harmonica tab ``name``, or its only one; a usage error else."""
    from caracole.inbox import harmonica_files

    tabs = harmonica_files(conn, song.id)
    if not tabs:
        fail(f"{song.display} keeps no harmonica tab", 2)
    if name is None:
        if len(tabs) > 1:
            fail(f"{song.display} keeps {len(tabs)} harmonica tabs: say which with --tab: "
                 + " or ".join(t.name for t in tabs), 2)
        return tabs[0]
    found = next((t for t in tabs if t.name == name), None)
    if found is None:
        fail(f"{song.display} has no harmonica tab {name}: it keeps " + ", ".join(t.name for t in tabs), 2)
    return found


def _render(conn: sqlite3.Connection, cfg: Config, song: Song) -> None:
    """The song rendered again, as overrides.toml now says, and the library's pages written again."""
    from caracole.render import render_all

    overrides = load_ovr(cfg)
    stats = render_all(conn, cfg, overrides, song_ids={song.id})
    write_pages(conn, cfg, overrides, utcnow())
    if stats.failed:
        fail(f"{song.display}: its pages could not all be rendered again; the log says why")


def pin(cfg: Config, display: str, tab_name: str | None, spec: str | dict[str, str]) -> None:
    """The tab read as ``spec`` says (``harptab.check_spec``'s), recorded under ``[harmonica]``; the song rendered
    again."""
    from caracole.overrides import OverridesError, add_harmonica
    from caracole.viewer.harptab import parse, pinned

    overrides = load_ovr(cfg)
    # overrides.toml is in the library: written under caracole's lock, as a lookup writes a pick.
    with exclusive(cfg, f"harmonica {display} --as", interactive=True):
        with closing(open_db(cfg)) as conn:
            song = song_named(conn, display, overrides)
            tab = _tab(conn, song, tab_name)
            text = tab_text(cfg, conn, song, tab)
            if text is None:
                fail(f"{tab.name} of {song.display} can't be read")
            if spec == "legend" and pinned(spec, text) is None:
                fail(f"{tab.name} has no legend of its own: name a notation instead", 2)
            try:
                add_harmonica(cfg.overrides_file, song.display, tab.name, spec)
            except OverridesError as e:
                fail(f"overrides.toml can't be written: {e}")
            _render(conn, cfg, song)
    read = parse(text, harp=tab.harp, notation=pinned(spec, text)).reading
    typer.echo(f"{tab.name} of {song.display} is read as {spec_words(spec)}, as you set it: {read.said()}")


def clear(cfg: Config, display: str, tab_name: str | None) -> None:
    """The tab's ``[harmonica]`` entry taken out; the song rendered again, its tab read as caracole guesses."""
    from caracole.overrides import OverridesError, add_harmonica

    overrides = load_ovr(cfg)
    with exclusive(cfg, f"harmonica {display} --clear", interactive=True):
        with closing(open_db(cfg)) as conn:
            song = song_named(conn, display, overrides)
            tab = _tab(conn, song, tab_name)
            if tab.name not in load_ovr(cfg).harmonica.get(song.key, {}):
                typer.echo(f"No [harmonica] entry pins how {tab.name} is read: caracole guesses it already.")
                return
            try:
                add_harmonica(cfg.overrides_file, song.display, tab.name, None)
            except OverridesError as e:
                fail(f"overrides.toml can't be written: {e}")
            _render(conn, cfg, song)
    typer.echo(f"Took {tab.name} of {song.display} out of [harmonica] in overrides.toml: caracole guesses how "
               f"{tab.name} is read again.")
