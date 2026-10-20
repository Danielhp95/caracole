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
import sys
import textwrap
from contextlib import closing, nullcontext
from typing import TYPE_CHECKING

import typer

from caracole.commands import sources
from caracole.commands._common import exclusive, fail, load_cfg, open_db

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.keys import SongKey
    from caracole.overrides import Overrides
    from caracole.search import IndexHit, LibraryHit
    from caracole.songs import Song

_SHELL_SPECIAL = re.compile(r'(["\\$`])')
_EMPTY_INDEX = "the offline index is empty: run `caracole index build` once (about 10 minutes)"


def register(app: typer.Typer) -> None:
    @app.command("search")
    def search_cmd(
        ctx: typer.Context,
        query: list[str] | None = typer.Argument(
            None, metavar="[QUERY]...", help="Words of the artist, the title, or both."
        ),
        limit: int = typer.Option(10, "--limit", "-n", min=1, help="Hits to show from each place."),
        add: int | None = typer.Option(
            None, "--add", metavar="N", min=1, help="Add Ultimate Guitar hit N to wanted.txt."
        ),
        key: str | None = typer.Option(
            None, "--key", metavar="KEY",
            help='Only your songs in this key, in either case: "A minor", am, F#, "La menor". The offline index '
                 "has no keys, so it isn't searched.",
        ),
    ) -> None:
        """Search your library and the offline Ultimate Guitar index (no network)."""
        text = " ".join(" ".join(query or []).split())
        if (text or key is None) and not re.search(r"\w", text):
            fail(f"nothing to search for in {text!r}", 2)
        in_key = None if key is None else _wanted_key(key, add)
        cfg = load_cfg(ctx)
        # Only --add writes (wanted.txt, then the library), so only it waits for another caracole.
        lock = nullcontext() if add is None else exclusive(cfg, "search --add")
        with lock, closing(open_db(cfg)) as conn:
            if add is None:
                _search(cfg, conn, text, limit, in_key)
            else:
                _add(cfg, conn, text, add, limit)


def _wanted_key(key: str, add: int | None) -> str:
    """The key ``--key`` names, as caracole writes keys; a usage error if it names none.

    The value is known to be a key, so its tonic may be lowercase ("am", "bbm", "f#"), which
    ``parse_key`` refuses in tab text so that the word "am" is no key; a b after the letter is
    still a flat.
    """
    from caracole.keys import parse_key

    k = key.strip()
    found = parse_key(k[:1].upper() + k[1:])
    if found is None:
        fail(f"--key: {key!r} is not a key; write one as A minor, Am, F#, Bb or La menor", 2)
    if add is not None:
        fail("--add adds an Ultimate Guitar hit, and the offline index has no keys: "
             "search without --key to add one", 2)
    return found


def _search(cfg: Config, conn: sqlite3.Connection, text: str, limit: int, key: str | None = None) -> None:
    from caracole.keys import key_name, song_key
    from caracole.search import STRONG, bare_id_hint, search_index, search_library

    more = 0  # songs in the key that --limit leaves out
    if key is None:
        typer.echo("In your library")
        hits = search_library(conn, text, limit)
        library = [(hit, song_key(conn, cfg.library_dir, hit.song)) for hit in hits]
    else:
        typer.echo(f"In your library, in {key_name(key)}")
        in_key = _in_key(cfg, conn, text, key)
        library, more = in_key[:limit], max(len(in_key) - limit, 0)
    for hit, found in library:
        typer.echo(_library_line(cfg, hit, found))
    if not library:
        typer.echo("  nothing matches")
    elif more:
        typer.echo(f"  … and {more} more: see them with --limit {limit + more}")
    if key is not None:
        typer.echo("\nThe offline Ultimate Guitar index has no keys: search it without --key.")
        return

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
    best = library[0][0] if library else None
    artist = best.song.artist if best is not None and best.score >= STRONG else None
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


def _in_key(
    cfg: Config, conn: sqlite3.Connection, text: str, key: str
) -> list[tuple[LibraryHit, SongKey]]:
    """Your songs in ``key``, however it is spelled (``keys.same_key``): those that match ``text``,
    best first, or with no text every one, by name. All of them, so the listing can say how many
    ``--limit`` leaves out."""
    from caracole.keys import same_key, song_key
    from caracole.search import LibraryHit, search_library
    from caracole.songs import list_songs

    if text:
        hits = search_library(conn, text, sys.maxsize)
    else:
        songs = sorted(list_songs(conn), key=lambda s: (s.display.casefold(), s.id))
        hits = [LibraryHit(s, 100.0) for s in songs]
    found = []
    for hit in hits:
        known = song_key(conn, cfg.library_dir, hit.song)
        if known is not None and same_key(known.key, key):
            found.append((hit, known))
    return found


def _library_line(cfg: Config, hit: LibraryHit, key: SongKey | None = None) -> str:
    from caracole.library import song_dir

    song = hit.song
    folder = song_dir(cfg.library_dir, song)
    where = str(folder) if folder.is_dir() else "no folder yet"
    known = f"Key {key.describe()} · " if key is not None else ""
    return f"  {song.display} · {_status(song)} · {known}{where}"


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
    sources.say_added(cfg, sources.add_song(cfg, hit.artist, hit.title, conn=conn))  # as `caracole add` says it
