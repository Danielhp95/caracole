"""``caracole versions``: a song's Ultimate Guitar chords versions, and which of them the title opens.

- ``show``: every chords version UG lists for the song, in rank order (sheet_versions.py), one line
  each: ``Ver 3 of 13 · 4.86★ (408) · tab 1064463 · kept · the one · <the tabber's note>``. It only
  reads: no request, no lock.
- ``keep``: one version kept beside the sheet now (``ug.fetch.keep_version``), at the lookup pace:
  one tab page at most, within the lookup's budget and the hour's, under caracole's lock as a lookup
  takes it; then its page is rendered and the library page written again. It is noted as yours, so
  the nightly fetch keeps it whatever the ranking. A block, a spent budget or a site's error keeps
  nothing, says so and exits 0, as in every command.
- ``keep_more``: ``keep`` for each version a keep may still keep (``sheet_versions.may_keep``: neither kept
  nor the one nor gone, not under ``[block]``, none a keep found it can't keep), in rank order, through one
  client at the lookup pace, until the lookup's budget or the hour's is spent, Ultimate Guitar blocks caracole
  or fails: as many as one lookup may, what it kept before that kept, and the rest counted for the next press.
  A version whose page has no sheet, or the very text of another kept file, is noted so
  (``note_unkeepable``, as ``keep`` notes it) and never read again. Then the song is rendered and the library
  page written, once. With nothing left to keep it sends nothing.
- ``choose``: ``caracole get --tab`` for one of the song's versions: recorded under ``[pin]``, it
  becomes the sheet, and the title, the PDF, the viewer and the songbooks use it.
- ``clear``: the song's chords pins out of ``[pin]`` (``overrides.remove_pin``), then ``caracole get``
  again, so caracole's pick is the sheet.

``--progress`` writes ``caracole get --progress`` lines (get.py ``progress_line``): ``choose`` and
``clear`` are lookups, and ``keep`` and ``keep_more`` report the stages ``song``, ``version`` (``keep_more``'s
counting, "kept 3 of 10"), ``pdf`` and ``pages`` and their ``done`` the same way, for caracole serve.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from typing import TYPE_CHECKING, Any

import typer

from caracole.commands._common import (
    exclusive,
    fail,
    load_ovr,
    lookup_run_id,
    make_client,
    open_db,
    song_named,
    utcnow,
    write_pages,
)

if TYPE_CHECKING:
    from datetime import datetime

    from caracole.config import Config
    from caracole.overrides import Overrides
    from caracole.sheet_versions import SheetVersion
    from caracole.songs import Song

PROVIDER = "ug"
# What ``ug.fetch.keep_version`` came to, in words.
KEPT_WORDS = {
    "same": "its text is the very text of {page}, which shows it",
    "held": "its text is the very text of another file kept in the song's folder, so it isn't kept again",
    "sheet": "it is the sheet already",
    "gone": "Ultimate Guitar no longer has it",
    "unreadable": "its page can't be read now; it waits",
    "no text": "its page has no sheet caracole can keep",
    "unknown": "it isn't one of the song's chords versions caracole may use",
}


def line(v: SheetVersion, total: int) -> str:
    """One version: ``Ver 3 of 13 · 4.86★ (408) · tab 1064463 · kept · the one · <note>``."""
    parts = [f"Ver {v.number if v.number is not None else '?'} of {total}"]
    if v.rating and v.votes:
        parts.append(f"{v.rating:.2f}★ ({v.votes:,})")
    else:
        parts.append("no votes yet")
    parts.append(f"tab {v.tab_id}")
    if v.complete is False and v.coverage is not None:
        parts.append(f"{round(v.coverage * 100)}% of the lyrics")
    if v.gone:
        parts.append("gone from Ultimate Guitar")
    if v.chosen:
        parts += ["kept", "the one"]
    elif v.kept and v.page == "sheet.html":
        parts.append("kept: the sheet's very text")
    elif v.kept:
        parts.append("kept")
    if v.note:
        parts.append(v.note)
    return " · ".join(parts)


def _the_one(conn: sqlite3.Connection, song: Song, versions: Sequence[SheetVersion], overrides: Overrides) -> str:
    from caracole.get import kept_sheet
    from caracole.songs import AUTO_SHEET
    from caracole.versions import get_version

    chosen = next((v for v in versions if v.chosen), None)
    if chosen is not None:
        yours = int(chosen.tab_id) in overrides.pin.get(song.key, ())
        return f"the title opens tab {chosen.tab_id}" + (", your choice under [pin]" if yours else ", caracole's pick")
    kept = kept_sheet(conn, song)
    if kept is None:
        return "no sheet is kept yet"
    if kept.name == AUTO_SHEET:
        return "the sheet is auto-chords', made from audio"
    provider = get_version(conn, kept.version_id).provider
    return "the sheet is LaCuerda's" if provider == "lacuerda" else f"the sheet is {provider}'s"


def show(cfg: Config, display: str) -> None:
    from caracole.sheet_versions import in_library, sheet_kind

    overrides = load_ovr(cfg)
    with closing(open_db(cfg)) as conn:
        song = song_named(conn, display, overrides)
        versions = in_library(conn, song.id, cfg.rank)
        if not versions:
            typer.echo(f"{song.display}: no Ultimate Guitar chords versions yet. caracole reads them once the song "
                       "is matched: caracole get, or the nightly run.")
            return
        n = len(versions)
        # The versions of the group the sheet comes from: UG's Ukulele Chords for a song with no chords there.
        kind = "Ukulele Chords version" if sheet_kind(conn, song.id) == "ukulele" else "chords version"
        typer.echo(f"{song.display}: {n} {kind}{'' if n == 1 else 's'} on Ultimate Guitar; "
                   f"{_the_one(conn, song, versions, overrides)}.")
        for v in versions:
            typer.echo(f"  {line(v, n)}")
        quoted = f'"{song.display}"'
        typer.echo(f"Keep one beside the sheet: caracole versions {quoted} --keep TAB. "
                   f"Make one the sheet: caracole versions {quoted} --choose TAB.")
        if _chords_pins(conn, song, overrides):
            typer.echo(f"Back to caracole's pick: caracole versions {quoted} --clear.")


def _listed(conn: sqlite3.Connection, cfg: Config, song: Song, tab: int) -> SheetVersion:
    """The song's version ``tab``, one UG still has; otherwise say why there is none, and exit 1."""
    from caracole.sheet_versions import in_library

    v = next((v for v in in_library(conn, song.id, cfg.rank) if v.tab_id == str(tab)), None)
    if v is None:
        fail(f'Tab {tab} isn\'t one of the Ultimate Guitar chords versions of {song.display}: '
             f'caracole versions "{song.display}" lists them.')
    if v.gone:
        fail(f"Ultimate Guitar no longer has tab {tab} of {song.display}.")
    return v


def _chords_pins(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> list[int]:
    """The song's pins that choose its sheet (``sheet_versions.sheet_pins``). Any other stays: a text tab's."""
    from caracole.sheet_versions import sheet_pins

    return sheet_pins(conn, song.id, overrides.pin.get(song.key, ()))


class _Events:
    """``--progress``: ``caracole get --progress`` lines (get.py ``progress_line``)."""

    def __init__(self, on: bool):
        self.on = on

    def __call__(self, event: Mapping[str, Any]) -> None:
        if self.on:
            from caracole.get import progress_line

            typer.echo(progress_line(event))

    def stage(self, name: str, state: str, detail: str = "") -> None:
        self({"stage": name, "state": state, "detail": detail})


def _cooling(conn: sqlite3.Connection, now: datetime) -> str | None:
    """Why Ultimate Guitar may not be asked now, its cooldown after a block, in a keep's words; None when it may."""
    from caracole.health import get_state, is_cooling

    if not is_cooling(conn, PROVIDER, now):
        return None
    until = get_state(conn, PROVIDER).cooldown_until
    return (f"Ultimate Guitar is cooling down after a block, until "
            f"{until.strftime('%Y-%m-%d %H:%M UTC') if until else 'later'}; nothing kept.")


def _stopped(cfg: Config, conn: sqlite3.Connection, e: Exception, now: datetime) -> tuple[str, str, bool]:
    """A block, a spent budget or a site's error that stopped a keep, recorded as health.py keeps each (a block
    cools Ultimate Guitar down, an error is counted): the version stage's state, why in words, and whether to ask
    again later (not after a block: its cooldown says until when)."""
    from caracole.health import record_block, record_error
    from caracole.http import ProviderBlocked, ProviderError

    if isinstance(e, ProviderBlocked):
        state = record_block(conn, e.provider, now, str(e))
        until = state.cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if state.cooldown_until else "later"
        return "skipped", f"Ultimate Guitar blocked caracole ({e}): no more requests to it until {until}", False
    if isinstance(e, ProviderError):
        record_error(conn, e.provider, now, str(e))
        return "failed", f"Ultimate Guitar failed ({e})", True
    p = cfg.provider(PROVIDER)  # BudgetExhausted
    return ("skipped", f"The lookup requests to Ultimate Guitar are spent ({p.lookup_requests} a lookup, "
                       f"{p.lookup_per_hour} an hour)", True)


def _nothing_kept(why: str, again: bool) -> str:
    return f"{why}; nothing kept." + (" Ask again later." if again else "")


def _came_to(cfg: Config, conn: sqlite3.Connection, song: Song, tab: str, outcome: str) -> str:
    """What ``ug.fetch.keep_version`` came to for one version, in a sentence. A version it can't keep (``no text``,
    ``held``) is noted so (``sheet_versions.note_unkeepable``): ``--keep-more`` never reads its page again, and the
    library page counts it no more."""
    from caracole.library import song_dir
    from caracole.sheet_versions import note_unkeepable, same_pages, version_names

    if outcome in ("no text", "held"):
        note_unkeepable(conn, song.id, tab)
    if outcome == "kept":
        txt = song_dir(cfg.library_dir, song) / version_names(tab)[0]
        return f"Kept tab {tab} beside the sheet of {song.display}: {txt}"
    page = same_pages(conn, song.id).get(tab, "another kept version") if outcome == "same" else "another kept version"
    return f"Tab {tab} of {song.display}: " + KEPT_WORDS.get(outcome, outcome).format(page=page) + "."


def keep(cfg: Config, display: str, tab: int, *, progress: bool = False) -> None:
    import time

    from caracole.health import record_ok
    from caracole.http import BudgetExhausted, ProviderError
    from caracole.library import song_dir
    from caracole.overrides import load_overrides
    from caracole.render import render_all
    from caracole.sheet_versions import note_kept_by_you, version_names
    from caracole.ug.fetch import FetchContext, keep_version

    events = _Events(progress)
    started = time.monotonic()
    overrides = load_ovr(cfg)
    events.stage("song", "running")
    requests = 0

    def done(ok: bool = True) -> None:
        events({"done": {"seconds": round(time.monotonic() - started, 3), "requests": {PROVIDER: requests},
                         "ok": ok, "refused": None}})

    with exclusive(cfg, f"versions {display} --keep", interactive=True), closing(open_db(cfg)) as conn:
        song = song_named(conn, display, overrides)
        v = _listed(conn, cfg, song, tab)
        if tab in overrides.block:
            fail(f"Tab {tab} is under [block] in overrides.toml: caracole never uses it.")
        events({"song": {"id": song.id, "display": song.display}})
        events.stage("song", "done", "in the library")
        events.stage("version", "running")
        if v.chosen:
            said = f"Tab {tab} is the sheet of {song.display} already."
            events.stage("version", "skipped", said)
            typer.echo(said)
            return done()
        if v.kept and v.page != "sheet.html":
            note_kept_by_you(conn, song.id, v.tab_id)
            said = f"Tab {tab} is kept beside the sheet of {song.display} already; it stays kept now."
            events.stage("version", "done", said)
            typer.echo(said)
            return done()
        now = utcnow()
        cooling = _cooling(conn, now)
        if cooling is not None:
            events.stage("version", "skipped", cooling)
            typer.echo(cooling)
            return done()
        client = make_client(cfg, conn, PROVIDER, lookup_run_id(now), interactive=True)
        ctx = FetchContext(conn=conn, client=client, overrides=overrides, rank=cfg.rank, library_dir=cfg.library_dir,
                           now=now, reload_overrides=lambda: load_overrides(cfg.overrides_file))
        refused: tuple[str, str] | None = None  # the version stage's state and line, when nothing was kept
        try:
            outcome = keep_version(ctx, song, tab)
        except (BudgetExhausted, ProviderError) as e:
            state, why, again = _stopped(cfg, conn, e, now)
            refused = (state, _nothing_kept(why, again))
        finally:
            requests = client.requests_made
            client.close()
        if refused is not None:
            events.stage("version", *refused)
            typer.echo(refused[1])
            return done()  # the requests sent before it count
        if requests:
            record_ok(conn, PROVIDER, now)
        said = _came_to(cfg, conn, song, str(tab), outcome)
        events.stage("version", "done" if outcome in ("kept", "same", "sheet") else "skipped", said)
        typer.echo(said)
        if outcome == "kept":
            events.stage("pdf", "running")
            render_all(conn, cfg, overrides, now=now, song_ids={song.id})
            events.stage("pdf", "done", "the version's page made")
            viewer = song_dir(cfg.library_dir, song) / version_names(str(tab))[2]
            if viewer.is_file():
                typer.echo(f"Viewer: {viewer}")
        events.stage("pages", "running")
        write_pages(conn, cfg, overrides, utcnow())
        events.stage("pages", "done", "_todo.md and index.html rewritten")
    done()


def keep_more(cfg: Config, display: str, *, progress: bool = False) -> None:
    """The song's versions not kept yet, kept in rank order, as many as one lookup may (the module's docstring);
    exits 0 on a block, a spent budget or a site's error, as ``keep`` does."""
    import time

    from caracole.health import record_ok
    from caracole.http import BudgetExhausted, ProviderError
    from caracole.logs import plural
    from caracole.overrides import load_overrides
    from caracole.render import render_all
    from caracole.sheet_versions import in_library, may_keep
    from caracole.ug.fetch import FetchContext, keep_version

    events = _Events(progress)
    started = time.monotonic()
    overrides = load_ovr(cfg)
    events.stage("song", "running")
    requests = 0

    def done() -> None:
        events({"done": {"seconds": round(time.monotonic() - started, 3), "requests": {PROVIDER: requests},
                         "ok": True, "refused": None}})

    with exclusive(cfg, f"versions {display} --keep-more", interactive=True), closing(open_db(cfg)) as conn:
        song = song_named(conn, display, overrides)
        events({"song": {"id": song.id, "display": song.display}})
        events.stage("song", "done", "in the library")
        events.stage("version", "running")
        todo = may_keep(conn, song.id, in_library(conn, song.id, cfg.rank), overrides.block)
        if not todo:
            said = (f"Nothing more to keep of {song.display}: every Ultimate Guitar version caracole may keep is "
                    "kept already, or can't be.")
            events.stage("version", "skipped", said)
            typer.echo(said)
            return done()
        now = utcnow()
        cooling = _cooling(conn, now)
        if cooling is not None:
            events.stage("version", "skipped", cooling)
            typer.echo(cooling)
            return done()
        client = make_client(cfg, conn, PROVIDER, lookup_run_id(now), interactive=True)
        ctx = FetchContext(conn=conn, client=client, overrides=overrides, rank=cfg.rank, library_dir=cfg.library_dir,
                           now=now, reload_overrides=lambda: load_overrides(cfg.overrides_file))
        kept, files, changed = 0, False, False  # kept (a file, or a kept one's text); a file written; a count moved
        stopped: tuple[str, str, bool] | None = None  # what stopped it: _stopped's
        spent = False  # the budget: how a press ends while versions are left
        try:
            for v in todo:
                outcome = keep_version(ctx, song, int(v.tab_id))
                kept += outcome in ("kept", "same")
                files = files or outcome == "kept"
                changed = changed or outcome in ("kept", "same", "no text", "held", "gone")
                typer.echo(_came_to(cfg, conn, song, v.tab_id, outcome))
                events.stage("version", "running", f"kept {kept} of {len(todo)}")
        except (BudgetExhausted, ProviderError) as e:
            stopped, spent = _stopped(cfg, conn, e, now), isinstance(e, BudgetExhausted)
        finally:
            requests = client.requests_made
            client.close()
        if requests and (stopped is None or spent):
            record_ok(conn, PROVIDER, now)
        if stopped is not None and not kept:
            state, why, again = stopped
            said = _nothing_kept(why, again)
            events.stage("version", state, said)
            typer.echo(said)
        else:
            counted = f"kept {kept} of {len(todo)}"
            if stopped is not None and not spent:  # a block or an error after some were kept: say it
                counted += f"; {stopped[1]}"
                typer.echo(f"{stopped[1]}.")
            events.stage("version", "done" if kept else "skipped", counted)
            left = len(may_keep(conn, song.id, in_library(conn, song.id, cfg.rank), overrides.block))
            again = ": ask again" if stopped is None or stopped[2] else ""  # not after a block: it cools down
            typer.echo(f"Kept {plural(kept, 'version') if kept else 'no version'} of {song.display}; "
                       + (f"{left} more not kept{again}." if left else "none is left to keep."))
        if stopped is not None and not changed:
            return done()  # nothing to write, as keep's refusals
        if files:
            events.stage("pdf", "running")
            render_all(conn, cfg, overrides, now=now, song_ids={song.id})
            events.stage("pdf", "done", "the versions' pages made")
        events.stage("pages", "running")
        write_pages(conn, cfg, overrides, utcnow())
        events.stage("pages", "done", "_todo.md and index.html rewritten")
    done()


def choose(cfg: Config, display: str, tab: int, *, progress: bool = False) -> None:
    """``caracole get --tab`` for one of the song's versions, at its own address (UG serves a slugged tab there
    alone)."""
    from caracole.commands.get import _get

    overrides = load_ovr(cfg)
    with closing(open_db(cfg)) as conn:
        song = song_named(conn, display, overrides)
        v = _listed(conn, cfg, song, tab)
    if tab in overrides.block:
        fail(f"Tab {tab} is under [block] in overrides.toml: take it out first to make it the sheet.")
    _get(cfg, song.artist, song.title, None, None, None, v.url, show=False, progress=progress)


def clear(cfg: Config, display: str, *, progress: bool = False) -> None:
    """The song's chords pins out of ``[pin]``, then the song looked up again: caracole's pick is the sheet."""
    from caracole.commands.get import _get
    from caracole.overrides import OverridesError, remove_pin

    overrides = load_ovr(cfg)
    # overrides.toml is in the library: written under caracole's lock, as a lookup writes a pick.
    with exclusive(cfg, f"versions {display} --clear", interactive=True):
        with closing(open_db(cfg)) as conn:
            song = song_named(conn, display, overrides)
            pins = _chords_pins(conn, song, overrides)
        if not pins:
            typer.echo(f"No [pin] chooses the sheet of {song.display}: caracole's pick is the sheet already.")
            return
        try:
            remove_pin(cfg.overrides_file, song.display, pins)
        except OverridesError as e:
            fail(f"overrides.toml can't be written: {e}")
        tabs = ", ".join(f"tab {t}" for t in pins)
        typer.echo(f"Took {tabs} out of [pin] in overrides.toml; caracole's pick is the sheet again.")
        _get(cfg, song.artist, song.title, None, None, None, None, show=False, progress=progress)
