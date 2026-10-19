"""``tabarr search``: find a song in your library and in the offline UG index.

Nothing here touches the network: the library is the SQLite file, and the UG
index is the table ``tabarr index build`` filled from UG's sitemaps. Each UG
hit comes with the ``tabarr add`` line to paste, and ``--add N`` appends hit N
to wanted.txt and syncs it, as ``tabarr add`` does.
"""

from __future__ import annotations

import re
import sqlite3
import textwrap
from contextlib import closing
from typing import TYPE_CHECKING

import typer

from tabarr.commands._common import fail, load_cfg, open_db, utcnow

if TYPE_CHECKING:
    from tabarr.config import Config
    from tabarr.search import IndexHit, LibraryHit
    from tabarr.songs import Song

_SHELL_SPECIAL = re.compile(r'(["\\$`])')
_EMPTY_INDEX = "the offline index is empty: run `tabarr index build` once (about 10 minutes)"


def register(app: typer.Typer) -> None:
    @app.command("search")
    def search_cmd(
        ctx: typer.Context,
        query: list[str] = typer.Argument(
            ..., metavar="QUERY", help="Words of the artist, the title, or both."
        ),
        limit: int = typer.Option(10, "--limit", "-n", min=1, help="Hits to show from each place."),
        add: int | None = typer.Option(
            None, "--add", metavar="N", min=1, help="Add Ultimate Guitar hit N to wanted.txt."
        ),
    ) -> None:
        """Search your library and the offline Ultimate Guitar index (no network)."""
        text = " ".join(" ".join(query).split())
        if not re.search(r"\w", text):
            fail(f"nothing to search for in {text!r}", 2)
        cfg = load_cfg(ctx)
        with closing(open_db(cfg)) as conn:
            if add is None:
                _search(cfg, conn, text, limit)
            else:
                _add(cfg, conn, text, add, max(limit, add))


def _search(cfg: Config, conn: sqlite3.Connection, text: str, limit: int) -> None:
    from tabarr.search import STRONG, bare_id_hint, search_index, search_library

    library = search_library(conn, text, limit)
    typer.echo("In your library")
    for hit in library:
        typer.echo(_library_line(cfg, hit))
    if not library:
        typer.echo("  nothing matches")

    typer.echo("\nOn Ultimate Guitar (offline index)")
    if not _index_built(conn):
        typer.echo(f"  Nothing yet: {_EMPTY_INDEX}.")
        return
    hits = search_index(conn, text, limit)
    known = _library_keys(conn)
    for n, hit in enumerate(hits, start=1):
        typer.echo(_index_lines(n, hit, known))
    if not hits:
        typer.echo("  nothing matches")
    artist = library[0].song.artist if library and library[0].score >= STRONG else None
    hint = bare_id_hint(text, hits, artist=artist)
    if hint:
        typer.echo("\n" + _wrap(hint))


def _library_line(cfg: Config, hit: LibraryHit) -> str:
    from tabarr.library import song_dir

    song = hit.song
    folder = song_dir(cfg.library_dir, song)
    where = str(folder) if folder.is_dir() else "no folder yet"
    return f"  {song.display} · {_status(song)} · {where}"


def _status(song: Song) -> str:
    if song.status == "wanted":
        return "wanted, needs review" if song.review else "wanted, no sheet yet"
    return song.status


def _index_lines(n: int, hit: IndexHit, known: set[tuple[str, str]]) -> str:
    """A numbered hit: the name and its tabs per type, a sample page, and how to add it."""
    from tabarr.normalize import identity_key

    counts = " ".join(f"{kind}×{count}" for kind, count in hit.counts.items())
    if hit.labels:
        counts += f" (incl. {', '.join(hit.labels)})"
    in_library = (hit.artist_key, hit.song_key) in known or tuple(
        identity_key(hit.artist, hit.title).split("/", 1)
    ) in known
    action = "in your library" if in_library else f"tabarr add {_quote(hit.artist)} {_quote(hit.title)}"
    return f"  {n}. {hit.artist} - {hit.title} · {counts}\n     {hit.url}\n     {action}"


def _library_keys(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """Each library song as (artist key, song key): its identity, and the UG song it matched."""
    keys: set[tuple[str, str]] = set()
    for key, artist_key, song_key in conn.execute(
        "SELECT key, match_artist_key, match_song_key FROM songs"
    ):
        artist, _, title = key.partition("/")
        keys.add((artist, title))
        if artist_key and song_key:
            keys.add((artist_key, song_key))
    return keys


def _wrap(text: str, width: int = 88) -> str:
    """Prose paragraphs wrapped for a terminal; indented lines (the TOML to paste) left as they are."""
    return "\n\n".join(
        p if p.startswith(" ")
        else textwrap.fill(p, width, break_long_words=False, break_on_hyphens=False)
        for p in text.split("\n\n")
    )


def _quote(s: str) -> str:
    """Double-quoted for a POSIX shell, as the `tabarr add` lines are printed."""
    return '"' + _SHELL_SPECIAL.sub(r"\\\1", s) + '"'


def _index_built(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM ug_index LIMIT 1").fetchone() is not None


def _add(cfg: Config, conn: sqlite3.Connection, text: str, n: int, limit: int) -> None:
    """Append UG hit ``n`` of the search to wanted.txt, then sync wanted.txt into the library."""
    from tabarr.search import search_index
    from tabarr.songs import find_song
    from tabarr.wanted import append_wanted, find_wanted, format_line, sync_wanted

    if not _index_built(conn):
        fail(f"--add {n}: {_EMPTY_INDEX}", 2)
    hits = search_index(conn, text, limit)
    if not 1 <= n <= len(hits):
        found = f"only {len(hits)} hit{'s' if len(hits) != 1 else ''}" if hits else "nothing"
        fail(f"--add {n}: Ultimate Guitar has {found} for {text!r}", 2)
    hit = hits[n - 1]
    path = cfg.wanted_file
    try:
        listed = find_wanted(path, hit.artist, hit.title)
        line = append_wanted(path, hit.artist, hit.title)
    except ValueError as e:  # a name wanted.txt can't hold
        fail(f"can't add this song: {e}", 2)
    except OSError as e:
        fail(f"can't update {path}: {e.strerror or e}")
    written = format_line(line.artist, line.title, line.album, line.duration_ms)
    if listed:
        typer.echo(f"{written} is already in {path}, line {line.line_no}.")
    else:
        typer.echo(f"Added to {path}, line {line.line_no}:\n  {written}")
    try:
        known = find_song(conn, line.identity)
        stats = sync_wanted(conn, path, utcnow())
    except sqlite3.Error as e:  # the line is in the file, which is the source of truth
        typer.secho(
            f"The database couldn't be updated ({e}); the next `tabarr sync` or `tabarr run` adds it.",
            err=True, fg=typer.colors.YELLOW,
        )
        return
    if known is None:
        typer.echo(f"Song {line.identity}: new; the next `tabarr run` looks for it.")
    else:
        typer.echo(f"Song {line.identity}: already in your library ({_status(known)}).")
    for problem in stats.errors:
        typer.secho(problem, err=True, fg=typer.colors.YELLOW)
