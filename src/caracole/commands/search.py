"""``caracole search``: find a song in your library and in the offline UG index.

Nothing here touches the network: the library is the SQLite file, and the UG
index is the table ``caracole index build`` filled from UG's sitemaps. Each UG
hit comes with the ``caracole add`` line to paste, and ``--add N`` adds hit N
through ``caracole add``'s own path (``sources.add_song``): appended to
wanted.txt, which is then synced.
"""

from __future__ import annotations

import re
import sqlite3
import textwrap
from contextlib import closing, nullcontext
from typing import TYPE_CHECKING

import typer

from caracole.commands import sources
from caracole.commands._common import exclusive, fail, load_cfg, open_db

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.overrides import Overrides
    from caracole.search import IndexHit, LibraryHit
    from caracole.songs import Song

_SHELL_SPECIAL = re.compile(r'(["\\$`])')
_EMPTY_INDEX = "the offline index is empty: run `caracole index build` once (about 10 minutes)"


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
        # Only --add writes (wanted.txt, then the library), so only it waits for another caracole.
        lock = nullcontext() if add is None else exclusive(cfg, "search --add")
        with lock, closing(open_db(cfg)) as conn:
            if add is None:
                _search(cfg, conn, text, limit)
            else:
                _add(cfg, conn, text, add, limit)


def _search(cfg: Config, conn: sqlite3.Connection, text: str, limit: int) -> None:
    from caracole.search import STRONG, bare_id_hint, search_index, search_library

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
    hint = bare_id_hint(text, hits, artist=artist, overrides=_overrides(cfg))
    if hint:
        typer.echo("\n" + _wrap(hint))


def _overrides(cfg: Config) -> Overrides | None:
    """overrides.toml, for the hint's line to paste into it; None when it can't be read, which
    leaves the search itself as it is: it needs no overrides."""
    from caracole.overrides import OverridesError, load_overrides

    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError:
        return None


def _library_line(cfg: Config, hit: LibraryHit) -> str:
    from caracole.library import song_dir

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
    from caracole.normalize import identity_key

    counts = " ".join(f"{kind}×{count}" for kind, count in hit.counts.items())
    if hit.labels:
        counts += f" (incl. {', '.join(hit.labels)})"
    in_library = (hit.artist_key, hit.song_key) in known or tuple(
        identity_key(hit.artist, hit.title).split("/", 1)
    ) in known
    action = "in your library" if in_library else f"caracole add {_quote(hit.artist)} {_quote(hit.title)}"
    return f"  {n}. {hit.artist} - {hit.title} · {counts}\n     {hit.url}\n     {action}"


# Only these decisions make a song's matched UG song its own; a review's keys are a candidate's,
# often a cover by another artist. A [match] override is an accept.
_MATCHED = "match_decision IN ('accept', 'pinned')"


def _library_keys(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """Each library song as (artist key, song key): its identity, and the UG song it matched."""
    keys: set[tuple[str, str]] = set()
    for key, artist_key, song_key, matched in conn.execute(
        f"SELECT key, match_artist_key, match_song_key, {_MATCHED} FROM songs"
    ):
        artist, _, title = key.partition("/")
        keys.add((artist, title))
        if matched and artist_key and song_key:
            keys.add((artist_key, song_key))
    return keys


def _matched_elsewhere(conn: sqlite3.Connection, hit: IndexHit) -> Song | None:
    """A library song matched to this UG song under another identity (another spelling, say)."""
    from caracole.normalize import identity_key
    from caracole.songs import get_song

    row = conn.execute(
        f"SELECT id FROM songs WHERE {_MATCHED} AND match_artist_key = ? AND match_song_key = ? AND key != ? "
        "ORDER BY id LIMIT 1",
        (hit.artist_key, hit.song_key, identity_key(hit.artist, hit.title)),
    ).fetchone()
    return get_song(conn, row[0]) if row else None


def _listed(cfg: Config, conn: sqlite3.Connection, hit: IndexHit) -> bool:
    """Whether the hit's own song is in the library or in wanted.txt already."""
    from caracole.normalize import identity_key
    from caracole.songs import find_song
    from caracole.wanted import find_wanted

    if find_song(conn, identity_key(hit.artist, hit.title)) is not None:
        return True
    try:
        return find_wanted(cfg.wanted_file, hit.artist, hit.title) is not None
    except OSError:  # add_song reports a file it can't read
        return False


def _wrap(text: str, width: int = 88) -> str:
    """Prose paragraphs wrapped for a terminal; indented lines (the TOML to paste) left as they are."""
    return "\n\n".join(
        p if p.startswith(" ")
        else textwrap.fill(p, width, break_long_words=False, break_on_hyphens=False)
        for p in text.split("\n\n")
    )


def _quote(s: str) -> str:
    """Double-quoted for a POSIX shell, as the `caracole add` lines are printed."""
    return '"' + _SHELL_SPECIAL.sub(r"\\\1", s) + '"'


def _index_built(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM ug_index LIMIT 1").fetchone() is not None


def _add(cfg: Config, conn: sqlite3.Connection, text: str, n: int, limit: int) -> None:
    """Add UG hit ``n`` of the search the way ``caracole add`` adds a song, and say what happened.

    Only a hit the same search shows can be added: ``n`` up to ``limit``.
    """
    from caracole.search import search_index
    from caracole.wanted import format_line

    if not _index_built(conn):
        fail(f"--add {n}: {_EMPTY_INDEX}", 2)
    if n > limit:  # a hit you never saw, such as --add 12 typed for --add 2
        shown = "the first hit is" if limit == 1 else f"the first {limit} hits are"
        fail(f"--add {n}: only {shown} shown; see hit {n} with --limit {n} first, then add it with "
             f"--limit {n} --add {n}", 2)
    hits = search_index(conn, text, limit)
    if not 1 <= n <= len(hits):
        found = f"only {len(hits)} hit{'s' if len(hits) != 1 else ''}" if hits else "nothing"
        fail(f"--add {n}: Ultimate Guitar has {found} for {text!r}", 2)
    hit = hits[n - 1]
    # The hit's own song first: add_song says where it is already. Then another spelling of it.
    other = None if _listed(cfg, conn, hit) else _matched_elsewhere(conn, hit)
    if other is not None:  # adding it would make a second record of the same song
        typer.echo(f"Already in your library as {other.display} ({_status(other)}); wanted.txt is unchanged.")
        return
    added = sources.add_song(cfg, hit.artist, hit.title, conn=conn)
    line, path = added.line, cfg.wanted_file
    written = format_line(line.artist, line.title, line.album, line.duration_ms)
    if added.listed:
        typer.echo(f"{written} is already in {path}, line {line.line_no}.")
    else:
        typer.echo(f"Added to {path}, line {line.line_no}:\n  {written}")
    if added.db_error is not None:  # the line is in the file, which is the source of truth
        typer.secho(
            f"The database couldn't be updated ({added.db_error}); "
            "the next `caracole sync` or `caracole run` adds it.",
            err=True, fg=typer.colors.YELLOW,
        )
        return
    if added.known is None:
        typer.echo(f"Song {line.identity}: new; the next `caracole run` looks for it.")
    else:
        typer.echo(f"Song {line.identity}: already in your library ({_status(added.known)}).")
    for text in sources.match_lines(added.match):
        typer.echo(text)
    for problem in added.problems:
        typer.secho(problem, err=True, fg=typer.colors.YELLOW)
