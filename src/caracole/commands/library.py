"""Library commands: ``caracole todo``, ``caracole review`` and ``caracole scan``.

Each rewrites _todo.md and index.html for what it changed (``review`` only when
an answer changed something), holding caracole's lock while it writes; ``review``
takes it only after the questions, never while it waits for you. ``review
--song S --pick N`` (or ``--none``) answers for one song with no question, so
it holds the lock from reading the song to rewriting the pages: it is what
caracole serve's picker runs. An
overrides.toml that can't be read still gets the to-do page rewritten, leading
with why, and the command exits 2, as the nightly run does. The pages are built
by modules that import the matcher and the index, so those are imported inside
the commands: every command module is imported on every start.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

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
from caracole.overrides import Overrides, OverridesError, load_overrides

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.music import ScanStats
    from caracole.review import ReviewStats
    from caracole.songs import Song


def _overrides_for_pages(conn: sqlite3.Connection, cfg: Config, now: datetime) -> Overrides:
    """overrides.toml, to build the pages with.

    One that can't be read still gets the to-do page rewritten, leading with why, and then exits 2.
    index.html is left as it was: built without your overrides it would lose your transpositions and
    ignored songs.
    """
    from caracole.todo import build_todo, write_todo

    try:
        return load_overrides(cfg.overrides_file)
    except OverridesError as e:
        try:
            path = write_todo(cfg.library_dir, build_todo(conn, cfg, Overrides(), now, overrides_error=str(e)))
            typer.echo(f"Wrote {path}, which leads with this error; index.html was left as it was")
        except OSError as w:
            typer.secho(f"can't write {cfg.library_dir / '_todo.md'}: {w.strerror or w}", err=True,
                        fg=typer.colors.RED)
        fail(f"overrides: {e}", 2)


def _rewrite_pages(conn: sqlite3.Connection, cfg: Config, what: str, *,
                   rematch: bool = False) -> tuple[Path, Path]:
    """Rewrite _todo.md and index.html (matching every song first, with ``rematch``), holding caracole's
    lock as ``what``; a library caracole can't write exits 1."""
    with exclusive(cfg, what):
        now = utcnow()
        overrides = _overrides_for_pages(conn, cfg, now)
        if rematch:
            from caracole.match import match_all

            match_all(conn, overrides, cfg.match)
        return write_pages(conn, cfg, overrides, now)


def _counts(stats: ReviewStats) -> str:
    return (f"accepted {stats.accepted}, pinned {stats.pinned}, ignored {stats.ignored}, "
            f"rejected {stats.rejected}, skipped {stats.skipped}")


def _song_named(conn: sqlite3.Connection, display: str) -> Song:
    """The song ``--song`` names; a name that isn't "Artist - Title" exits 2, one not in the library 1."""
    from caracole.overrides import override_key
    from caracole.songs import find_song

    try:
        key = override_key(display)
    except OverridesError as e:
        fail(f"--song: {e}", 2)
    found = find_song(conn, key)
    if found is None:
        fail(f'No song "{display}" in the library.')
    return found


def _seen_candidate(text: str) -> dict[str, str]:
    """A ``--seen`` UG song, as a candidate; one that isn't ARTIST/SONG exits 2."""
    artist_key, sep, song_key = text.strip().partition("/")
    if not sep or not artist_key or not song_key or "/" in song_key:
        fail(f"--seen: {text!r} isn't a UG song: write it as ARTIST/SONG, as caracole review lists it", 2)
    return {"artist_key": artist_key, "song_key": song_key}


def _answer(cfg: Config, display: str, pick: str | None, seen: list[dict[str, str]]) -> None:
    """One song's answer, as ``caracole review`` takes it, with no question: ``pick`` (a number or
    ARTIST/SONG), or none of the candidates (those ``seen``, else every one it lists).

    It holds caracole's lock from reading the song to rewriting the pages, as nothing waits for
    you here: what caracole serve's picker runs (web/app.py).
    """
    from caracole.review import ReviewStats, accept, candidates_of, ref, reject, writes_alias
    from caracole.songs import get_song

    with exclusive(cfg, "review"):
        load_ovr(cfg)
        conn = open_db(cfg)
        song = _song_named(conn, display)
        if not song.review or song.status == "ignored":
            fail(f'"{song.display}" doesn\'t need review, so nothing was written.')
        cands = candidates_of(song)
        again = f'caracole review --song "{song.display}"'
        stats = ReviewStats()
        try:
            if pick is not None:
                chosen = _picked(cands, pick.strip())
                if chosen is None:
                    fail(f'"{song.display}" has no candidate {pick.strip()} now: {again} lists them.')
                accept(conn, cfg, song, chosen)
                stats.accepted += 1
                alias = (f', and [alias] "{song.artist}" = "{chosen["artist_key"]}"'
                         if writes_alias(song, chosen) else "")
                typer.echo(f'{song.display}: "{ref(chosen)}" under [match]{alias}')
            else:
                rejected = seen or cands
                if not rejected:
                    fail(f'"{song.display}" has no candidates to reject: {again} offers the rest.')
                reject(conn, cfg, song, rejected)
                stats.rejected += 1
                typer.echo(f"{song.display}: {', '.join(ref(c) for c in rejected)} under [reject]")
        except OverridesError as e:  # the file broke since it was read
            fail(f"overrides: {e}", 2)
        path, page = _rewrite_pages(conn, cfg, "review", rematch=True)
        typer.echo(_counts(stats))
        typer.echo(f"Wrote {path} and {page}")
        typer.echo(_now(get_song(conn, song.id)))


def _picked(cands: list[dict], pick: str) -> dict | None:
    """The candidate ``--pick`` names: its number in the list, or its ARTIST/SONG."""
    from caracole.review import ref

    if pick.isdigit():
        n = int(pick)
        return cands[n - 1] if 1 <= n <= len(cands) else None
    return next((c for c in cands if ref(c) == pick), None)


def _now(song: Song) -> str:
    """Where the song stands after the rematch."""
    if song.match_decision in ("accept", "pinned") and song.match_artist_key and song.match_song_key:
        return (f"Now matched to {song.match_artist_key}/{song.match_song_key}: "
                f'caracole fetch --song "{song.display}" fetches it now, or the nightly run does.')
    if song.match_decision == "review":
        return f'Still in review, with other candidates: caracole review --song "{song.display}" lists them.'
    if song.match_decision == "not_found":
        return "Not found now: caracole goes on looking for it, on its artist's UG page too."
    return f"Now {song.match_decision or 'not matched yet'}."


def _music_line(cfg: Config, music: ScanStats) -> str:
    if not music.seen:  # scan_music unlinks nothing then: a disk that isn't mounted tonight, say
        why = "has no audio files" if cfg.music_dir.is_dir() else "is missing"
        return f"Music: {cfg.music_dir} {why}, so nothing was unlinked"
    files = "file" if music.seen == 1 else "files"
    return f"Music: {music.seen} {files}, {music.matched} linked, {len(music.unmatched)} unmatched"


def register(app: typer.Typer) -> None:
    @app.command("todo")
    def todo_cmd(ctx: typer.Context) -> None:
        """Rewrite Library/_todo.md and Library/index.html from the database."""
        cfg = load_cfg(ctx)
        path, page = _rewrite_pages(open_db(cfg), cfg, "todo")
        typer.echo(f"Wrote {path} and {page}")

    @app.command("review")
    def review_cmd(
        ctx: typer.Context,
        song: str | None = typer.Option(
            None, "--song", metavar='"ARTIST - TITLE"',
            help="Only this song: ask about it alone, or answer for it with --pick or --none.",
        ),
        pick: str | None = typer.Option(
            None, "--pick", metavar="N|ARTIST/SONG",
            help="With --song: this candidate is the song, by its number or as ARTIST/SONG. Writes \\[match], "
                 "and \\[alias] as answering its number does.",
        ),
        none: bool = typer.Option(
            False, "--none", help="With --song: none of its candidates is the song. Writes them under \\[reject].",
        ),
        seen: list[str] = typer.Option(
            [], "--seen", metavar="ARTIST/SONG",
            help="With --none: a candidate you were shown; only those are rejected. Repeat for each.",
        ),
    ) -> None:
        """Settle uncertain matches; each answer is written to overrides.toml."""
        from caracole.review import ReviewIO, review_songs

        if (pick is not None or none) and song is None:
            fail("--pick and --none answer for one song: name it with --song", 2)
        if pick is not None and none:
            fail("--pick or --none, not both", 2)
        if seen and not none:
            fail("--seen goes with --none", 2)
        shown = [_seen_candidate(text) for text in seen]
        cfg = load_cfg(ctx)
        if song is not None and (pick is not None or none):
            _answer(cfg, song, pick, shown)
            return
        load_ovr(cfg)  # a broken file stops here, before a question whose answer it couldn't keep
        conn = open_db(cfg)
        only = None if song is None else {_song_named(conn, song).id}
        written: list[Path] = []

        def read(prompt: str) -> str:  # the prompts end in ": "; Enter answers ""
            return typer.prompt(prompt, default="", show_default=False, prompt_suffix="")

        def settle() -> None:  # after the questions, when an answer changed something
            written.extend(_rewrite_pages(conn, cfg, "review", rematch=True))

        try:
            stats = review_songs(conn, cfg, ReviewIO(read=read, write=typer.echo), rematch=settle, only=only)
        except OverridesError as e:  # the file broke while review waited for an answer
            fail(f"overrides: {e}", 2)
        typer.echo(_counts(stats))
        if written:
            typer.echo(f"Wrote {written[0]} and {written[1]}")

    @app.command("scan")
    def scan_cmd(ctx: typer.Context) -> None:
        """Link purchased audio in Music/ to songs, and file Guitar Pro downloads from _inbox/."""
        from caracole.inbox import file_inbox
        from caracole.music import scan_music

        cfg = load_cfg(ctx)
        conn = open_db(cfg)
        with exclusive(cfg, "scan"):
            music = scan_music(conn, cfg.music_dir)
            inbox = file_inbox(conn, cfg.library_dir)
            typer.echo(_music_line(cfg, music))
            refused = len(inbox.refused)  # links, never read: the to-do page names them
            links = f", {refused} symbolic link{'s' if refused != 1 else ''} refused" if refused else ""
            typer.echo(f"Inbox: {len(inbox.filed)} filed, {len(inbox.duplicates)} duplicates, "
                       f"{len(inbox.unmatched)} left{links}")
            path, page = _rewrite_pages(conn, cfg, "scan")
        typer.echo(f"Wrote {path} and {page}")
