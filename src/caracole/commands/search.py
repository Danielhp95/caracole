"""``caracole search``: find a song in your library and in the offline UG and LaCuerda indexes.

Nothing here touches the network: the library is the SQLite file, the UG
index is the table ``caracole index build`` filled from UG's sitemaps, and
LaCuerda's the one the nightly run fills from its listings of every artist and
the artist pages caracole read (lacuerda_index.py). Each UG hit comes with the
``caracole add`` line to paste, and ``--add N`` adds hit N through ``caracole
add``'s own path (``sources.add_song``): appended to wanted.txt, which is then
synced. A hit under a catch-all artist (``misc-musicals``…) has no such line,
and ``--add`` refuses it: under UG's names, the song's artist would be "Misc
Musicals". LaCuerda's group comes after UG's, numbered on: its artists (each
with their most popular songs with chords, or, when caracole never read their
page, the ``caracole lacuerda --artist`` line that reads it) and its songs, whose
line, and ``--add``, record the song as your pick there (``--lacuerda``).
harptabs.com's group comes last, unnumbered: its artists (with their most viewed songs, or,
when caracole never read their page, the ``caracole harptabs --artist`` line that reads it),
its songs by an artist whose page caracole read, each with the ``caracole get --harptabs``
line that looks the song up keeping that tab, and its tabs by title alone, whose artist no
page read names (search.py ``search_harptabs``); then how far its artist index has got.

A query may be an artist alone or a title alone (``search.find_index``): when
an artist leads, its most tabbed songs come first, then the songs titled like
it; when a song does, the artists of that name are a line each, for
``--artist``; a word of an artist's name ("skynyrd") names them too, and a
query nothing matches well, spelled close to an artist's name ("lynrd"),
ends with "Did you mean" that artist (``search.suggestions``) and the line
that lists their songs. ``--artist NAME`` lists an artist's songs, ``--title
TITLE`` a title's by any artist, and ``--add N`` numbers exactly what was printed
(``_listing``). ``offer_songs`` is what ``caracole add`` and ``caracole get``
say to one name, which names no song: the same listing, each hit with its line
to run.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import textwrap
from collections.abc import Callable, Sequence
from contextlib import closing, nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

import typer

from caracole.commands import sources
from caracole.commands._common import exclusive, fail, load_cfg, open_db

LACUERDA = "On LaCuerda (offline index)"
HARPTABS = "On harptabs.com (offline index)"

if TYPE_CHECKING:
    from collections.abc import Mapping

    from caracole.config import Config
    from caracole.keys import SongKey
    from caracole.overrides import Overrides
    from caracole.search import ArtistHit, IndexHit, LibraryHit, SiteArtist, SiteHit
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
            None, "--add", metavar="N", min=1,
            help="Add hit N to wanted.txt, numbered as listed: Ultimate Guitar's, then LaCuerda's (as your "
                 "pick there).",
        ),
        key: str | None = typer.Option(
            None, "--key", metavar="KEY",
            help='Only your songs in this key, in either case: "A minor", am, F#, "La menor". The offline '
                 "indexes have no keys, so they aren't searched.",
        ),
        artist: str | None = typer.Option(
            None, "--artist", metavar="NAME",
            help="Only this artist's songs: yours, then the offline indexes', most tabbed (on LaCuerda, most "
                 "popular) first. QUERY words then search their titles.",
        ),
        title: str | None = typer.Option(
            None, "--title", metavar="TITLE", help="Only songs of this title, by any artist."
        ),
        progression: str | None = typer.Option(
            None, "--progression", metavar="NUMERALS",
            help='Only your songs that play this progression, in any key: its numerals ("vi IV I V") or its '
                 'name ("andalusian"). The offline indexes have no chords, so they aren\'t searched.',
        ),
    ) -> None:
        """Search your library and the offline Ultimate Guitar and LaCuerda indexes (no network)."""
        if progression is not None:
            _by_progression(ctx, progression, limit, others={"QUERY": bool(query), "--add": add is not None,
                                                             "--key": key is not None, "--artist": artist is not None,
                                                             "--title": title is not None})
            return
        ask = _ask(" ".join(" ".join(query or []).split()), artist, title, key)
        in_key = None if key is None else _wanted_key(key, add)
        cfg = load_cfg(ctx)
        # Only --add writes (wanted.txt, then the library), so only it waits for another caracole.
        lock = nullcontext() if add is None else exclusive(cfg, "search --add")
        with lock, closing(open_db(cfg)) as conn:
            if add is None:
                _search(cfg, conn, ask, limit, in_key)
            else:
                _add(cfg, conn, ask, add, limit)


@dataclass(frozen=True)
class _Ask:
    """What a search asks for: ``text`` (QUERY's words), or an artist's songs (``artist``, ``text``
    then words of their titles), or a title's (``title``)."""

    text: str
    artist: str | None = None
    title: str | None = None

    def __str__(self) -> str:
        if self.artist is not None:
            return f"--artist {self.artist!r}" + (f" {self.text!r}" if self.text else "")
        return f"--title {self.title!r}" if self.title is not None else repr(self.text)


def _ask(text: str, artist: str | None, title: str | None, key: str | None) -> _Ask:
    """The search asked for; a usage error for one that asks nothing, or two things at once."""
    named = {}
    for option, value in (("--artist", artist), ("--title", title)):
        if value is not None:
            named[option] = " ".join(value.split())
            if not re.search(r"\w", named[option]):
                fail(f"{option}: nothing to search for in {value!r}", 2)
    if named and key is not None:
        fail(f"--key searches your songs by their key, and the offline indexes have none: it can't go with "
             f"{' or '.join(named)}", 2)
    if "--artist" in named:  # words of their titles: --title's, or QUERY's
        return _Ask(" ".join(w for w in (text, named.get("--title", "")) if w), artist=named["--artist"])
    if "--title" in named:
        if text:
            fail(f"--title takes the whole title: search for {text!r} without it, or put it in the title", 2)
        return _Ask("", title=named["--title"])
    if (text or key is None) and not re.search(r"\w", text):
        fail(f"nothing to search for in {text!r}", 2)
    return _Ask(text)


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
        fail("--add adds a hit of the offline indexes, and they have no keys: "
             "search without --key to add one", 2)
    return found


def _by_progression(ctx: typer.Context, text: str, limit: int, *, others: Mapping[str, bool]) -> None:
    """``--progression``: your songs that play it (``progressions.songs_with``), by name, each with its
    status, the sections that play it, the key its sheet was read in and its folder. It reads, and never
    waits for another caracole."""
    from caracole.icons import kept_sources
    from caracole.library import song_dir
    from caracole.progressions import any_recorded, read_progression, songs_with

    named = [name for name, given in others.items() if given]
    if named:
        fail(f"--progression searches your songs by what they play: it can't go with {' or '.join(named)}", 2)
    wanted = read_progression(text)
    if wanted is None:
        fail(f'--progression: {text!r} is no progression: write its numerals ("vi IV I V", "i bVII bVI V"), '
             'two chords or more, or its name ("andalusian", "the pop progression")', 2)
    cfg = load_cfg(ctx)
    with closing(open_db(cfg)) as conn:
        said = wanted.label if wanted.name in (None, wanted.label) else f"{wanted.label}, {wanted.name}"
        typer.echo(f"Your songs with {said}")
        playing = songs_with(conn, wanted)
        kept = kept_sources(conn)
        for p in playing[:limit]:
            folder = song_dir(cfg.library_dir, p.song)
            where = str(folder) if folder.is_dir() else "no folder yet"
            key = f" · in {p.key}" if p.key else ""
            typer.echo(f"  {_tag(_sheet_source(kept.get(p.song.id, {})))}{p.song.display} · {_status(p.song)} · "
                       f"{', '.join(p.sections)}{key} · {where}")
        if not playing:
            typer.echo("  none" if any_recorded(conn) else
                       "  none yet: caracole reads a sheet's progressions as it renders it, so the next "
                       "`caracole run` (or `caracole render`) reads every sheet's")
        elif len(playing) > limit:
            typer.echo(f"  … and {len(playing) - limit} more: see them with --limit {len(playing)}")


def _sheet_source(kept: Mapping[str, str]) -> str | None:
    from caracole.icons import sheet_source

    return sheet_source(kept)


def _search(cfg: Config, conn: sqlite3.Connection, ask: _Ask, limit: int, key: str | None = None) -> None:
    from caracole.icons import kept_sources
    from caracole.keys import key_name, song_key

    kept = kept_sources(conn)  # where each song's sheet came from, for its tag
    if key is not None:
        typer.echo(f"In your library, in {key_name(key)}")
        in_key = _in_key(cfg, conn, ask.text, key)
        library, more = in_key[:limit], max(len(in_key) - limit, 0)
    else:
        typer.echo("In your library" + (f", by {ask.artist}" if ask.artist is not None else ""))
        hits = _library_hits(conn, ask, limit)
        library = [(hit, song_key(conn, cfg.library_dir, hit.song)) for hit in hits[:limit]]
        more = max(len(hits) - limit, 0) if ask.artist is not None else 0  # songs by the artist left out
    for hit, found in library:
        typer.echo(_library_line(cfg, hit, found, kept.get(hit.song.id, {})))
    if not library:
        typer.echo("  nothing matches")
    elif more:
        typer.echo(f"  … and {more} more: see them with --limit {limit + more}")
    if key is not None:
        typer.echo("\nThe offline Ultimate Guitar and LaCuerda indexes have no keys: search them without --key.")
        return

    _print_removed(conn, ask, limit)
    typer.echo("\nOn Ultimate Guitar (offline index)")
    known = _library_keys(conn)
    shown, hint, ug = 0, None, None
    if not _index_built(conn):
        typer.echo(f"  Nothing yet: {_EMPTY_INDEX}.")
    else:
        listing = ug = _listing(conn, ask, limit)
        _print_listing(listing, known)
        shown = len(listing.hits)
        hint = _hint(ask, listing, library[0][0] if library else None, _overrides(cfg))
    typer.echo(f"\n{LACUERDA}")
    lacuerda = _lacuerda_listing(conn, ask, limit, ug)
    _print_listing(lacuerda, known, start=shown)
    typer.echo(f"\n{HARPTABS}")
    for line in _harptabs_listing(cfg, conn, ask, limit):
        typer.echo(line)
    if ug is not None and ask.artist is None and ask.title is None:
        _print_suggestions(conn, ask, ug, lacuerda, [hit for hit, _ in library])
    if hint:  # Ultimate Guitar's bare ids: after every place's hits
        typer.echo("\n" + _wrap(hint))


def _print_suggestions(conn: sqlite3.Connection, ask: _Ask, ug: _Listing, lacuerda: _Listing,
                       mine: Sequence[LibraryHit]) -> None:
    """The artists spelled close to a query nothing matches well (``search.suggestions``), each with the line that
    lists their songs; nothing when a song of yours is the query's by its title."""
    from caracole.search import STRONG, IndexFound, suggestions

    if any(h.score >= STRONG and h.via != "artist" for h in mine):
        return
    close = suggestions(conn, ask.text, IndexFound(ug.artists, ug.songs, ug.lead), lacuerda.sites)
    if not close:
        return
    names = [s.artist for s in close]
    said = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
    typer.echo(f"\nDid you mean {said}?")
    for s in close:
        where = "LaCuerda" if s.source == "lacuerda" else "Ultimate Guitar"
        typer.echo(f"  {s.artist} · {where} · {_count(s.songs, 'song')}: caracole search --artist {_quote(s.artist)}")


def _print_removed(conn: sqlite3.Connection, ask: _Ask, limit: int) -> None:
    """The group of removed songs the words match, after your library's: each with the date it was
    removed and the line that asks for it again (a wanted.txt line is such a request). Nothing is
    printed when none matches, or for an artist's or a title's listing."""
    from caracole.search import search_removed

    if ask.artist is not None or ask.title is not None:
        return
    hits = search_removed(conn, ask.text, limit)
    if not hits:
        return
    typer.echo("\nRemoved from your library")
    for hit in hits:
        typer.echo(f"  {hit.artist} - {hit.title} · removed {hit.removed_at[:10]}")
        typer.echo(f"     bring it back: caracole add {_quote(hit.artist)} {_quote(hit.title)}")


def _library_hits(conn: sqlite3.Connection, ask: _Ask, limit: int) -> list[LibraryHit]:
    """Your songs the search asks for, best first: those matching the words, or of the title (up to
    ``limit``), or every one by the artist (``search.library_by_artist``; with ``text``, those whose
    titles it matches)."""
    from caracole.search import LibraryHit, library_by_artist, search_library
    from caracole.songs import list_songs

    if ask.title is not None:
        return search_library(conn, ask.title, limit, reading="title")
    if ask.artist is None:
        return search_library(conn, ask.text, limit)
    named = _named_artist(conn, ask.artist)
    theirs = library_by_artist(list_songs(conn), ask.artist, named.artist_key if named else None)
    if not ask.text:
        return [LibraryHit(s, 100.0, "artist") for s in theirs]
    ids = {s.id for s in theirs}
    return [h for h in search_library(conn, ask.text, sys.maxsize, reading="title") if h.song.id in ids]


def _named_artist(conn: sqlite3.Connection, name: str) -> ArtistHit | None:
    """The offline index's artist ``name`` names: the first artist row a search for it gives, never one it names only
    in part ("lynyrd" is no name of Lynyrd Skynyrd's for ``--artist``)."""
    from caracole.search import find_index

    artists = [a for a in find_index(conn, name, songs=0).artists if not a.part]
    return artists[0] if artists else None


@dataclass(frozen=True)
class _Listing:
    """What the search prints of the offline index: lines, with the hits between them, numbered in
    order. ``songs`` and ``artists`` are what its hint weighs; ``missing`` says the index has no
    artist ``--artist`` names."""

    parts: tuple[str | IndexHit | SiteHit, ...]
    songs: tuple[IndexHit, ...] = ()
    artists: tuple[ArtistHit, ...] = ()
    missing: bool = False
    lead: str | None = None  # a search's: "artist" when an artist leads
    sites: tuple[SiteArtist | SiteHit, ...] = ()  # LaCuerda's artists and songs, for the suggestions

    @property
    def hits(self) -> list[IndexHit | SiteHit]:
        return [p for p in self.parts if not isinstance(p, str)]


def _listing(conn: sqlite3.Connection, ask: _Ask, limit: int) -> _Listing:
    """The offline index's answer as the search prints it, at most ``limit`` hits, numbered as
    ``--add`` takes them. An artist that leads comes first, with its most tabbed songs; any other
    artist the query names is a line, to list with ``--artist``."""
    from caracole.search import artist_songs, find_index

    if ask.artist is not None:
        named = _named_artist(conn, ask.artist)
        if named is None:
            return _Listing((f"  No artist named {ask.artist} in the offline index",), missing=True)
        hits, total = artist_songs(conn, named.artist_key, limit=limit, title=ask.text or None)
        head = (f"  {named.artist}'s songs titled like {ask.text}:" if ask.text else
                f"  {named.artist}: {_count(named.songs, 'song')} ({_count(named.tabs, 'tab')}), the most tabbed "
                "first:")
        parts: list[str | IndexHit] = [head, *hits] if hits else [head, "  nothing matches"]
        if total > len(hits):
            parts.append(f"  … and {total - len(hits)} more: see them with --limit {total}")
        return _Listing(tuple(parts), tuple(hits), (named,))
    if ask.title is not None:
        songs = find_index(conn, ask.title, songs=limit, artists=0, reading="title").songs
        return _Listing(tuple(songs) or ("  nothing matches",), songs)
    found = find_index(conn, ask.text, songs=limit)
    parts = []
    others = found.artists
    if found.lead == "artist":
        lead, *others = found.artists
        top = lead.top[:limit]
        parts += [f"  {lead.artist}, an artist: {_count(lead.songs, 'song')} ({_count(lead.tabs, 'tab')}). "
                  "The most tabbed:", *top]
        if lead.songs > len(top):
            parts.append(f"     All {lead.songs:,}: caracole search --artist {_quote(lead.artist)}")
        rest = found.songs[:max(limit - len(top), 0)]
        if rest:
            heading = f"Songs titled like {ask.text}" if all(h.via == "title" for h in rest) else "Other songs"
            parts += ["", f"  {heading}:", *rest]
    else:
        parts += found.songs[:limit] or ["  nothing matches"]
    for a in others:
        parts += ["", f"  Also an artist: {a.artist}, {_count(a.songs, 'song')} ({_count(a.tabs, 'tab')})",
                  f"     caracole search --artist {_quote(a.artist)}"]
    return _Listing(tuple(parts), found.songs, found.artists, lead=found.lead)


def _print_listing(listing: _Listing, known: set[tuple[str, str]],
                   paste: Callable[[IndexHit], str | None] | None = None, *, start: int = 0) -> None:
    """Its lines, and its hits numbered from ``start`` + 1, each with its line to run (``paste``, by default
    the ``caracole add`` line; None for none). A LaCuerda song's line records it as your pick there."""
    from caracole.search import SiteHit

    n = start
    for part in listing.parts:
        if isinstance(part, str):
            typer.echo(part)
        elif isinstance(part, SiteHit):
            n += 1
            typer.echo(_lacuerda_lines(n, part, known))
        else:
            n += 1
            typer.echo(_index_lines(n, part, known, paste or _add_line))


def _lacuerda_listing(conn: sqlite3.Connection, ask: _Ask, limit: int, ug: _Listing | None = None) -> _Listing:
    """LaCuerda's index's answer as the search prints it, at most ``limit`` songs, numbered on after Ultimate
    Guitar's. An artist that leads comes first, with their most popular songs with chords; any other artist
    the query names is a line. Then what the index lacks: all of it while it is empty, or the letters not
    read yet (``search.lacuerda_left_out``); and, for a name it has no artist by under a letter not read
    yet, the line that reads the page of that name (``search.lacuerda_unlisted``, which weighs the Ultimate
    Guitar index's answer, ``ug``)."""
    from caracole.search import STRONG, lacuerda_left_out, search_lacuerda

    left = lacuerda_left_out(conn)
    if left is not None and left[0] == "empty":
        return _Listing((f"  Nothing yet: LaCuerda's {left[1]} (`caracole lacuerda --index` reads them now, "
                         "a run's budget at a time).", *_lacuerda_offer(conn, ask, ug)))
    artists: list[SiteArtist] = []
    songs: list[SiteHit] = []
    if ask.artist is not None:
        parts, found = _lacuerda_artist_parts(conn, ask, limit)
        artists = [found] if found is not None else []
    elif ask.title is not None:
        songs = [h for h in search_lacuerda(conn, ask.title, songs=limit, artists=0)[1] if h.via == "title"]
        parts = list(songs) or ["  nothing matches"]
    else:
        artists, songs = search_lacuerda(conn, ask.text, songs=limit)
        parts = []
        if artists and (not songs or artists[0].score >= songs[0].score):
            lead, *others = artists
            top = [t for t in lead.top][:limit]
            parts += _lacuerda_artist_head(lead, bool(top))
            parts += top
            if lead.known > len(top):
                parts.append(f"     All {lead.known:,} the index holds: caracole search --artist {_quote(lead.artist)}")
            shown = {t.url for t in top}
            rest = [h for h in songs if h.url not in shown][:max(limit - len(top), 0)]
            if rest:
                parts += ["", "  Other songs:", *rest]
        else:
            others = artists
            parts += songs or ["  nothing matches"]
        for a in others:
            parts += ["", *_lacuerda_artist_head(a, False, also=True)]
    if left is not None:
        parts += ["", _fill(f"LaCuerda's {left[1]}.")]
    if not any(a.score >= STRONG for a in artists):  # none of theirs it found is the name ("Bomba Estereo")
        parts += _lacuerda_offer(conn, ask, ug, [*artists, *songs])
    return _Listing(tuple(parts), sites=(*artists, *songs))


def _lacuerda_offer(conn: sqlite3.Connection, ask: _Ask, ug: _Listing | None,
                    lacuerda: Sequence[SiteHit | SiteArtist] = ()) -> list[str]:
    """For a name LaCuerda's index has no artist by, while its listing of their letter isn't read
    (``search.lacuerda_unlisted``), the line that reads the page of that name now: ``--artist``'s, or the one
    the query names; none when the index can tell (LaCuerda's own answer, ``lacuerda``, among it), and for a
    title (``--title``, or a query Ultimate Guitar's or LaCuerda's index reads as one)."""
    from caracole.search import lacuerda_unlisted

    if ask.title is not None:
        return []
    found = (lacuerda_unlisted(conn, ask.artist, artist=True) if ask.artist is not None else
             lacuerda_unlisted(conn, ask.text, *((ug.artists, ug.songs, ug.lead) if ug is not None else ()),
                               lacuerda=lacuerda))
    if found is None:
        return []
    name, letter = found
    return ["", _fill(f"LaCuerda hasn't listed {letter} yet: caracole lacuerda --artist {_quote(name)} reads "
                      f"the page of “{name}” now (a request for each spelling of the name tried, usually one).")]


def _fill(text: str) -> str:
    """A note of LaCuerda's group, wrapped and indented, its words and commands whole."""
    return textwrap.fill(text, 88, initial_indent="  ", subsequent_indent="  ", break_long_words=False,
                         break_on_hyphens=False)


def _lacuerda_artist_head(a: SiteArtist, top: bool, *, also: bool = False) -> list[str]:
    """An artist's line in LaCuerda's group, and the line that lists their songs, or reads their page."""
    head = f"  {'Also an artist: ' if also else ''}{a.artist} · LaCuerda · {_count(a.songs, 'song')}"
    if top:
        return [head + ". The most popular with chords:"]
    if a.known:
        return [head, f"     caracole search --artist {_quote(a.artist)}"]
    return [head, f"     caracole hasn't read their page: caracole lacuerda --artist {a.slug} reads it (one request)"]


def _lacuerda_artist_parts(conn: sqlite3.Connection, ask: _Ask,
                           limit: int) -> tuple[list[str | SiteHit], SiteArtist | None]:
    """``--artist NAME``'s part of LaCuerda: the songs the index holds of the artist the name is, most popular
    first (with QUERY words, those whose titles they match), or how to read their page; and that artist, None
    for a name the index has no artist by."""
    from caracole.search import STRONG, lacuerda_songs, search_lacuerda

    named = [a for a in search_lacuerda(conn, ask.artist or "", songs=0, artists=1)[0] if a.score >= STRONG]
    if not named:
        return [f"  No artist named {ask.artist} in LaCuerda's index"], None
    a = named[0]
    if not a.known:
        return list(_lacuerda_artist_head(a, False)), a
    songs = lacuerda_songs(conn, a.slug, title=ask.text or None)
    head = (f"  {a.artist} · LaCuerda · their songs titled like {ask.text}:" if ask.text else
            f"  {a.artist} · LaCuerda · {a.known:,} of their {_count(a.songs, 'song')} in the index, the most "
            "popular first:")
    parts: list[str | SiteHit] = [head, *songs[:limit]] if songs else [head, "  nothing matches"]
    if len(songs) > limit:
        parts.append(f"  … and {len(songs) - limit} more: see them with --limit {len(songs)}")
    return parts, a


def _lacuerda_lines(n: int, hit: SiteHit, known: set[tuple[str, str]]) -> str:
    """A numbered LaCuerda song: its names and versions, its page, and the line that adds it as your pick
    there (by its names alone for a song without chords there: no sheet to keep)."""
    from caracole.normalize import identity_key

    versions = f"{_count(hit.uploads, 'version')}, {'with chords' if hit.sheet else 'no chords'}"
    head = f"  {n}. {_tag('lacuerda')}{hit.artist} - {hit.title} · {versions}\n     {hit.url}"
    if tuple(identity_key(hit.artist, hit.title).split("/", 1)) in known:
        return f"{head}\n     in your library"
    pick = f"--lacuerda {hit.url} " if hit.sheet else ""
    return f"{head}\n     caracole add {pick}{_quote(hit.artist)} {_quote(hit.title)}"


def _harptabs_listing(cfg: Config, conn: sqlite3.Connection, ask: _Ask, limit: int) -> list[str]:
    """harptabs.com's index's answer as the search prints it, unnumbered: the artists the query names, each with their
    most viewed songs, then its songs, at most ``limit``, and its tabs by title alone; with ``--artist``, that
    artist's songs; with ``--title``, the songs of that title. Then how far its artist index has got, while it isn't
    whole. Nothing but why, while harptabs.com is turned off or its index is empty."""
    from caracole.harptabs_index import index_state
    from caracole.search import STRONG, harptabs_songs, search_harptabs

    if not cfg.provider("harptabs").enabled:
        return ["  harptabs.com is turned off in caracole.toml."]
    if conn.execute("SELECT 1 FROM harptabs_index LIMIT 1").fetchone() is None:
        return ["  Nothing yet: harptabs.com's index is empty: the nightly run reads its sitemap (caracole harptabs "
                "--index reads it now, then its artist pages)."]
    lines: list[str] = []
    if ask.artist is not None:
        named = [a for a in search_harptabs(conn, ask.artist, songs=0, artists=1)[0] if a.score >= STRONG]
        if not named:
            lines.append(f"  No artist named {ask.artist} in harptabs.com's index")
        elif not named[0].read:
            lines += _harptabs_artist_head(named[0], False)
        else:
            a = named[0]
            songs = harptabs_songs(conn, a.slug, title=ask.text or None)
            whole = len(harptabs_songs(conn, a.slug))
            lines.append(f"  {a.artist} · harptabs.com · their songs titled like {ask.text}:" if ask.text else
                         f"  {a.artist} · harptabs.com · {whole:,} of their songs in the index ({a.known:,} of their "
                         f"{_count(a.songs, 'tab')}), the most viewed first:")
            lines += [_harptabs_lines(h) for h in songs[:limit]] or ["  nothing matches"]
            if len(songs) > limit:
                lines.append(f"  … and {len(songs) - limit} more: see them with --limit {len(songs)}")
    elif ask.title is not None:
        songs = [h for h in search_harptabs(conn, ask.title, songs=limit, artists=0)[1] if h.via == "title"]
        lines += [_harptabs_lines(h) for h in songs] or ["  nothing matches"]
    else:
        artists, songs = search_harptabs(conn, ask.text, songs=limit)
        for a in artists:
            lines += _harptabs_artist_head(a, bool(a.top))
            lines += [_harptabs_lines(t) for t in a.top]
            whole = len(harptabs_songs(conn, a.slug)) if a.known else 0
            if whole > len(a.top):
                lines.append(f"     All {_count(whole, 'song')} the index holds: caracole search --artist "
                             f"{_quote(a.artist)}")
        if artists and songs:
            lines += ["", "  Other songs:"]
        lines += [_harptabs_lines(h) for h in songs]
        if not lines:
            lines.append("  nothing matches")
    state = index_state(conn)
    if state.read < state.artists:
        lines += ["", _fill(f"harptabs.com's artist pages are still being read: {state.read:,} of "
                            f"{state.artists:,} artists so far; caracole harptabs --index reads the rest.")]
    return lines


def _harptabs_artist_head(a: SiteArtist, top: bool) -> list[str]:
    """An artist's line in harptabs.com's group: the tabs their page says they have, and their most viewed songs, or,
    while caracole hasn't read their page, the line that reads it."""
    if not a.read:
        return [f"  {a.artist} · harptabs.com",
                f"     caracole hasn't read their page: caracole harptabs --artist {a.slug} reads it (one request)"]
    head = f"  {a.artist} · harptabs.com · {_count(a.songs, 'tab')}, {a.known:,} in the index"
    return [head + (". The most viewed:" if top else "")]


def _harptabs_lines(hit: SiteHit) -> str:
    """A harptabs.com song: its names, its tabs and the key of the most viewed, its page, and the line that
    looks it up keeping that tab; a tab by its title alone, its page."""
    if not hit.artist:
        return f"  {_tag('harptabs')}{hit.title} · same title, maybe another song\n     {hit.url}"
    key = hit.tabs[0].key if hit.tabs else None
    said = _count(hit.uploads, "tab") + (f", key {key}" if key else "")
    return (f"  {_tag('harptabs')}{hit.artist} - {hit.title} · {said}\n     {hit.url}\n"
            f"     caracole get --harptabs {hit.url} {_quote(hit.artist)} {_quote(hit.title)}")


def _count(n: int, thing: str) -> str:
    return f"{n:,} {thing}" + ("" if n == 1 else "s")


def _hint(ask: _Ask, listing: _Listing, mine: LibraryHit | None, overrides: Overrides | None) -> str | None:
    """The bare-id hint (``search.bare_id_hint``) for the name the search asked about: with
    ``--artist``, that artist's, when the index has no such artist; with ``--title``, that caracole
    needs the song's artist, when no song of that title matches well."""
    from caracole.normalize import placeholder_artist
    from caracole.search import STRONG, bare_id_hint

    if ask.artist is not None:
        return bare_id_hint(ask.artist, [], artist=ask.artist, overrides=overrides) if listing.missing else None
    if ask.title is not None:
        if any(h.score >= STRONG for h in listing.songs):
            return None
        return (f"No song titled {ask.title} in the offline Ultimate Guitar index matches well (UG's sitemaps "
                f"list some artists only by bare ids, and their songs aren't in it). caracole needs the song's artist to look it "
                f"up: `caracole add ARTIST {_quote(ask.title)}`.")
    # A song of yours the query found names the artist; "misc", which the owner writes for one they
    # don't know, names no one.
    artist = mine.song.artist if mine is not None and mine.score >= STRONG else None
    if artist is not None and placeholder_artist(artist):
        artist = None
    return bare_id_hint(ask.text, [*listing.songs, *listing.artists], artist=artist, overrides=overrides)


def _overrides(cfg: Config) -> Overrides | None:
    """overrides.toml, for the hint's line to paste into it; None when it can't be read, which
    leaves the search itself as it is: it needs no overrides."""
    from caracole.overrides import load_overrides_or_none

    return load_overrides_or_none(cfg.overrides_file)


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


def _library_line(cfg: Config, hit: LibraryHit, key: SongKey | None = None,
                  kept: Mapping[str, str] | None = None) -> str:
    """The song, tagged with where its sheet came from (``kept``: its files' sources) when it has
    one, its status, its key when one is asked for, and its folder; for a song in review, its
    first candidates too."""
    from caracole.icons import sheet_source
    from caracole.library import song_dir
    from caracole.search import did_you_mean

    song = hit.song
    folder = song_dir(cfg.library_dir, song)
    where = str(folder) if folder.is_dir() else "no folder yet"
    known = f"Key {key.describe()} · " if key is not None else ""
    lines = [f"  {_tag(sheet_source(kept or {}))}{song.display} · {_status(song)} · {known}{where}"]
    candidates = did_you_mean(song)
    if candidates:
        lines.append("     Did you mean (`caracole review` settles it):")
        lines += [
            f"       {float(c.get('score') or 0):.0f}  {c['artist_key']}/{c['song_key']} ({c.get('step', '')})"
            for c in candidates
        ]
    return "\n".join(lines)


def _tag(source: str | None) -> str:
    """Where a hit came from, as the command line marks it: "[UG] ", "[LaCuerda] "; nothing for no source."""
    from caracole.icons import tag

    return f"[{tag(source)}] " if source else ""


def _status(song: Song) -> str:
    if song.status == "wanted":
        return "wanted, needs review" if song.review else "wanted, no sheet yet"
    return song.status


@dataclass(frozen=True)
class _Offer:
    """What ``caracole add`` or ``caracole get`` says to one name: the line to run for a hit and for a
    song of yours (None: none), the line after the hits (None: none), what the command takes, and its
    line for a song of that name with the missing half, the artist or the title."""

    hit: Callable[[IndexHit], str]
    mine: Callable[[Song], str | None]
    after: Callable[[str], str] | None
    takes: str
    whole: Callable[[str, str], str]


_OFFERS = {
    "add": _Offer(lambda hit: _add_line(hit), lambda song: None,
                  lambda text: f"Or add one by its number: caracole search {_quote(text)} --add N",
                  'caracole add takes the artist and the title: caracole add ARTIST TITLE, or "ARTIST - TITLE"',
                  lambda artist, title: f"caracole add {artist} {title}"),
    "get": _Offer(lambda hit: f"caracole get --ug {hit.artist_key}/{hit.song_key} "
                              f"{_quote(f'{hit.artist} - {hit.title}')}",
                  lambda song: _get_yours(song),
                  None,
                  'caracole get takes a song as "Artist - Title", or as ARTIST TITLE',
                  lambda artist, title: f"caracole get {_quote(f'{artist} - {title}')}"),
}
OFFERED = 5  # the songs offered for one name


def _get_yours(song: Song) -> str | None:
    """The line that gets a song of yours, none for one whose artist is a placeholder ("misc"):
    nothing can be found by it."""
    from caracole.normalize import placeholder_artist

    return None if placeholder_artist(song.artist) else f"caracole get {_quote(song.display)}"


def offer_songs(cfg: Config, text: str, command: str) -> NoReturn:
    """``caracole add TEXT`` or ``caracole get TEXT`` for one name with no " - ": a song needs its
    artist, and the name may be its title or an artist's, so nothing is written or looked up. It
    prints your songs of that title and what ``caracole search TEXT`` lists first (its numbers), each
    scoring ``STRONG`` or more with the line that adds or gets it, and exits 2. It only reads, so it takes no lock."""
    from caracole.search import STRONG, search_library

    offer = _OFFERS[command]
    lines, artist = 0, False  # lines to run printed; the name is an artist's
    with closing(open_db(cfg)) as conn:
        yours = [h.song for h in search_library(conn, text, OFFERED) if h.via != "artist" and h.score >= STRONG]
        if yours:
            typer.echo("In your library")
        for song in yours:
            line = offer.mine(song)
            lines += line is not None
            typer.echo(f"  {song.display} · {_status(song)}" + (f"\n     {line}" if line else ""))
        if _index_built(conn):
            listing = _listing(conn, _Ask(text), OFFERED)
            artist = listing.lead == "artist"
            typer.echo("On Ultimate Guitar (offline index)")
            # A weak hit is listed, numbered as caracole search numbers it, with no line to run: it may well be
            # another song.
            _print_listing(listing, _library_keys(conn) if command == "add" else set(),
                           lambda hit: offer.hit(hit) if hit.score >= STRONG else None)
            lines += sum(h.score >= STRONG for h in listing.hits)
            if listing.hits and offer.after is not None:
                typer.echo(offer.after(text))
    whole = (f"give its title too: {offer.whole(_quote(text) if command == 'add' else text, 'TITLE')}" if artist
             else f"name its artist too: {offer.whole('ARTIST', _quote(text) if command == 'add' else text)}")
    then = f"Run one of the lines above, or {whole}" if lines else whole[:1].upper() + whole[1:]
    what = "added" if command == "add" else "looked up"
    fail(f'{offer.takes}. "{text}" is one name, so nothing was {what}. {then}.', 2)


def _add_line(hit: IndexHit) -> str:
    """The line that adds a hit: ``caracole add "Artist" "Title"``."""
    return f"caracole add {_quote(hit.artist)} {_quote(hit.title)}"


def _index_lines(n: int, hit: IndexHit, known: set[tuple[str, str]],
                 paste: Callable[[IndexHit], str | None] = _add_line) -> str:
    """A numbered hit: the name and its tabs per type, a sample page, and how to add it (``paste``)."""
    from caracole.normalize import identity_key

    counts = " ".join(f"{kind}×{count}" for kind, count in hit.counts.items())
    if hit.labels:
        counts += f" (incl. {', '.join(hit.labels)})"
    if hit.rating is not None:  # an artist page caracole read rates its tabs: the page's best one
        counts += f" · rated {hit.rating:.1f} ({_count(hit.votes, 'vote')})"
    in_library = (hit.artist_key, hit.song_key) in known or tuple(
        identity_key(hit.artist, hit.title).split("/", 1)
    ) in known
    head = f"  {n}. {_tag('ug')}{hit.artist} - {hit.title} · {counts}\n     {hit.url}"
    if in_library:
        return f"{head}\n     in your library"
    if hit.catch_all:  # added under UG's names, the song's artist would be "Misc Musicals"
        return f"{head}\n{_catch_all_note(hit, 'this hit')}"
    line = paste(hit)
    return head if line is None else f"{head}\n     {line}"


_ADD_AS_YOU_KNOW_IT = 'caracole add "<the show or singer>" "<the song>"'


def _catch_all_note(hit: IndexHit, which: str, *, head: str = "", indent: int = 5) -> str:
    """How to add the song of a catch-all hit: as you know it, never under UG's names."""
    return textwrap.fill(
        f"{head}{hit.artist_key} is UG's catch-all artist, no one's name: add the song as you know it, then "
        f"pick {which} in `caracole review`:", 88, initial_indent=" " * indent, subsequent_indent=" " * indent,
        break_long_words=False, break_on_hyphens=False) + f"\n{' ' * (indent + 2)}{_ADD_AS_YOU_KNOW_IT}"


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


def _add(cfg: Config, conn: sqlite3.Connection, ask: _Ask, n: int, limit: int) -> None:
    """Add hit ``n`` of the search the way ``caracole add`` adds a song, and say what happened: Ultimate
    Guitar's, or LaCuerda's after them, as your pick there.

    Only a hit the same search shows can be added: numbered as it printed them, each place's up to ``limit``.
    """
    from caracole.search import SiteHit

    ug = _listing(conn, ask, limit).hits if _index_built(conn) else []
    lacuerda = _lacuerda_listing(conn, ask, limit).hits
    hits = [*ug, *lacuerda]
    if not hits and not _index_built(conn):
        fail(f"--add {n}: {_EMPTY_INDEX}", 2)
    if n > len(hits) and (len(ug) >= limit or len(lacuerda) >= limit):  # a hit you never saw: --add 12 for --add 2
        shown = "the first hit is" if len(hits) == 1 else f"the first {len(hits)} hits are"
        fail(f"--add {n}: only {shown} shown; see hit {n} with --limit {n} first, then add it with "
             f"--limit {n} --add {n}", 2)
    if not 1 <= n <= len(hits):
        found = f"only {len(hits)} hit{'s' if len(hits) != 1 else ''}" if hits else "nothing"
        fail(f"--add {n}: {'Ultimate Guitar and LaCuerda have' if lacuerda else 'Ultimate Guitar has'} {found} "
             f"for {ask}", 2)
    hit = hits[n - 1]
    if isinstance(hit, SiteHit):  # LaCuerda's, as your pick there when it has chords to keep
        sources.say_added(cfg, sources.add_song(cfg, hit.artist, hit.title, conn=conn,
                                                lacuerda=hit.url if hit.sheet else None))
        return
    if hit.catch_all:  # under UG's names, the song's artist would be the catch-all, as "Misc Musicals"
        fail(_catch_all_note(hit, f"{hit.artist_key}/{hit.song_key}", head=f"--add {n} adds nothing: ",
                             indent=0), 2)
    # The hit's own song first: add_song says where it is already. Then another spelling of it.
    other = None if _listed(cfg, conn, hit) else _matched_elsewhere(conn, hit)
    if other is not None:  # adding it would make a second record of the same song
        typer.echo(f"Already in your library as {other.display} ({_status(other)}); wanted.txt is unchanged.")
        return
    sources.say_added(cfg, sources.add_song(cfg, hit.artist, hit.title, conn=conn))  # as `caracole add` says it
