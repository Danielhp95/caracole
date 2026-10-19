"""``tabarr match``: match every song against the local UG index, offline.

It prints one line per song (decision, score, step, "Artist - Title" → the
UG song), marks each decision or UG song that changed since the last match,
and ends with totals, then rewrites _todo.md and index.html for the new
decisions (a page it can't write exits 1, the decisions saved). ``--dry-run``
prints the same and saves nothing, so a change to the normalizer or the
thresholds can be checked against the whole library in seconds. Nothing is
saved against an index a build left half-done. The matcher is imported inside
the command, because every command module is imported on every start.
"""

from __future__ import annotations

from collections import Counter
from contextlib import closing, nullcontext
from typing import TYPE_CHECKING

import typer

from tabarr.commands._common import (
    exclusive,
    fail,
    load_cfg,
    load_ovr,
    open_db,
    utcnow,
    write_pages,
)

if TYPE_CHECKING:
    from tabarr.config import Config
    from tabarr.match import MatchChange, MatchResult

_ORDER = ("accept", "pinned", "review", "not_found", "ignored")
_PARTIAL = "The UG index is incomplete (a build stopped before it read every sitemap)"


def register(app: typer.Typer) -> None:
    @app.command("match")
    def match_cmd(
        ctx: typer.Context,
        dry_run: bool = typer.Option(False, "--dry-run", help="Print every decision, and save nothing."),
    ) -> None:
        """Match your songs against the local UG index (no requests) and print every decision."""
        _match(load_cfg(ctx), dry_run)


def _match(cfg: Config, dry_run: bool) -> None:
    from tabarr.match import match_all
    from tabarr.ug.index import index_state

    overrides = load_ovr(cfg)
    # A dry run saves nothing, so it needn't wait for another tabarr.
    with nullcontext() if dry_run else exclusive(cfg, "match"), closing(open_db(cfg)) as conn:
        state = index_state(conn)
        if state == "empty":
            fail("The UG index is empty: run `tabarr index build` first.")
        if state == "partial" and not dry_run:
            # Errors are not misses: a song in the sitemaps not read yet isn't missing from UG.
            fail(f"{_PARTIAL}: matching now would mark the songs in the sitemaps not read yet as not found, "
                 "so nothing was saved. Finish it with `tabarr index build` (the nightly refresh reads the rest "
                 "too); `tabarr match --dry-run` shows what it matches so far.")
        changes = match_all(conn, overrides, cfg.match, dry_run=dry_run)
        pages = write_pages(conn, cfg, overrides, utcnow()) if changes and not dry_run else None
    if not changes:
        typer.echo("No songs yet: add some to wanted.txt, or run `tabarr sync`.")
        return
    for c in changes:
        typer.echo(_line(c))
    typer.echo(_totals(changes, dry_run=dry_run))
    if state == "partial":
        typer.echo(f"{_PARTIAL}: a song whose tabs are in the sitemaps not read yet shows as not_found.")
    reviews = sum(1 for c in changes if c.new.decision == "review")
    if reviews and not dry_run:
        typer.echo(f"Settle the {'review' if reviews == 1 else f'{reviews} reviews'} with `tabarr review`, "
                   "or on _todo.md.")
    if pages:
        typer.echo(f"Wrote {pages[0]} and {pages[1]}")


def _key(artist_key: str | None, song_key: str | None) -> str | None:
    return f"{artist_key}/{song_key}" if artist_key and song_key else None


def _target(r: MatchResult) -> str:
    """The UG song a result points at, and a pin's tabs."""
    key = _key(r.artist_key, r.song_key)
    if r.pinned:
        tabs = ("tab " if len(r.pinned) == 1 else "tabs ") + ", ".join(str(t) for t in r.pinned)
        return f"{key} ({tabs})" if key else tabs
    return key or "-"


def _change(c: MatchChange) -> str | None:
    """``CHANGED old → new`` when the decision, or else the UG song, differs from the stored match."""
    if c.old != c.new.decision:
        return f"CHANGED {c.old or 'unmatched'} → {c.new.decision}"
    old, new = _key(c.song.match_artist_key, c.song.match_song_key), _key(c.new.artist_key, c.new.song_key)
    if old != new:
        return f"CHANGED {old or '-'} → {new or '-'}"
    return None


def _line(c: MatchChange) -> str:
    r = c.new
    score = f"{r.score:5.1f}" if r.score is not None else "    -"
    line = f"{r.decision:<9}  {score}  {r.step or '-':<12}  {c.song.display} → {_target(r)}"
    change = _change(c)
    return f"{line}  {change}" if change else line


def _totals(changes: list[MatchChange], *, dry_run: bool) -> str:
    counts = Counter(c.new.decision for c in changes)
    parts = [f"{counts[d]} {d}" for d in _ORDER if counts[d]]
    parts += [f"{n} {d}" for d, n in counts.items() if d not in _ORDER]
    changed = sum(1 for c in changes if _change(c))
    songs = "song" if len(changes) == 1 else "songs"
    tail = " Dry run: nothing was saved." if dry_run else ""
    return f"{len(changes)} {songs}: {', '.join(parts)}; {changed} changed.{tail}"
