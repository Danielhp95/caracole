"""The nightly ``caracole run`` (plan §6).

Steps, in order: sync → icons → index → match → lyrics → fetch → lacuerda →
scan → gtptabs → harptabs → gametabs → musescore → youtube → render → todo. Each step runs even
if an earlier one failed, so the to-do page is always rewritten.

- A step's provider is skipped while it is cooling down, and for the rest of
  the run once it blocks. So are gtptabs, harptabs, gametabs, musescore and youtube when caracole.toml
  turns one off: it gets no client then. A block records a cooldown (24 h, doubling)
  and sends one ntfy message; it is expected behaviour, not a failed run.
- The youtube step runs yt-dlp (youtube.py, youtube_fetch.py) only in a caracole
  with auto-chords, which makes the chords of what it downloads: without, the run
  makes no yt-dlp runner and the step is skipped, and the to-do page says why.
- An exhausted budget or a provider error ends that step for this run; neither
  is a failure, and neither ever marks a song "not found".
- Anything else is a bug: it's recorded, the remaining steps still run, and
  the run exits non-zero so systemd's OnFailure fires.
- An overrides.toml that can't be read stops the run before its first step
  (every step reads it); the to-do page is still rewritten, leading with why.
  Once the run has let a lookup go first (``_common.hand_over``), which may have
  pinned a tab, the steps after read it again (``StepContext.read_overrides_again``).
- A provider counts as working (``record_ok``) only when it answered at least
  one of the run's requests: a run of nothing but errors is no success.

Each step hands back a ``report.StepResult``: what it did, counted, the songs a
provider's error left for the next run, and what only you can do. The run's
summary (``RunReport.summary``, report.py) is made of them, and every ntfy
message the run sends uses the summary's words. A new step plugs in by
returning one; a step that returns a line of text, or nothing, still works.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from caracole.config import DEFAULT_PROVIDERS, Config
from caracole.db import kv_set_json
from caracole.health import answered_any, get_state, is_cooling, record_block, record_error, record_ok
from caracole.http import BudgetExhausted, Client, ProviderBlocked, ProviderError
from caracole.notify import Notifier
from caracole.overrides import Overrides, OverridesError, load_overrides
from caracole.report import (
    BUILD_INDEX,
    FINISH_INDEX,
    Action,
    Failure,
    NeedsYou,
    Problem,
    StepResult,
    blocked,
    bug,
    cooling,
    fix_overrides,
    plural,
    provider_name,
    shared_folder,
    step_error,
    summary_text,
    todo_count,
    unreadable_wanted,
    when,
)
from caracole.songs import ensure_current_keys, list_songs

log = logging.getLogger(__name__)
PROVIDERS = tuple(p for p in DEFAULT_PROVIDERS if p != "youtube")  # each gets a polite client; YouTube, yt-dlp
clock = time.monotonic  # what the run's duration is measured with; tests replace it


@dataclass
class Services:
    clients: Mapping[str, Any]
    notifier: Notifier

    def client(self, provider: str) -> Client:
        return self.clients[provider]

    def close(self) -> None:
        """Close every client that can be closed; a polite client holds caracole's lock until then."""
        for client in self.clients.values():
            close = getattr(client, "close", None)
            if close is not None:
                close()


@dataclass
class RunReport:
    """What a run did. ``steps`` holds each step's status line (kv ``run:last``, the log at -v),
    ``results`` what the steps handed back for the summary, ``requests`` and ``budgets`` each
    provider's requests and their limit, and ``seconds`` how long the run took."""

    run_id: str
    started: str
    finished: str | None = None
    steps: dict[str, str] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requests: dict[str, int] = field(default_factory=dict)
    results: dict[str, StepResult] = field(default_factory=dict)
    budgets: dict[str, int] = field(default_factory=dict)
    seconds: float | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self, *, quiet: bool = False) -> str:
        """The run's summary as plain text, the way ntfy gets it (report.py)."""
        return summary_text(self, quiet=quiet)

    def record(self, step: str, result: StepResult | str | None) -> None:
        """What a step handed back; a line of text, or nothing ("ok"), is its status alone."""
        if isinstance(result, StepResult):
            self.results[step] = result
            self.steps[step] = result.status
        else:
            self.steps[step] = result or "ok"


def _handoffs() -> int:
    """How many times this process has let a lookup have caracole's lock (``_common.handoffs``)."""
    from caracole.commands._common import handoffs

    return handoffs()


@dataclass
class StepContext:
    cfg: Config
    conn: sqlite3.Connection
    overrides: Overrides
    now: datetime
    run_id: str
    services: Services
    report: RunReport
    handoffs: int = field(default_factory=_handoffs)  # how many there had been when ``overrides`` was read

    def read_overrides_again(self) -> None:
        """overrides.toml read again once the run has let a lookup have caracole's lock since it was read
        (``_common.hand_over``: in a pause of a step's client, or between two songs), as the lookup may have
        pinned a tab or picked a LaCuerda sheet, which the steps after keep to; the copy read before stays
        when the file can't be read now (``_common.overrides_since``)."""
        from caracole.commands._common import overrides_since

        handed, self.handoffs = self.handoffs, _handoffs()
        self.overrides = overrides_since(self.cfg, self.overrides, handed)


@dataclass(frozen=True)
class Step:
    """One step of the run. ``run`` hands back a ``StepResult``, or a line of text, or nothing."""

    name: str
    run: Callable[[StepContext], StepResult | str | None]
    provider: str | None = None


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the default steps ----------------------------------------------------------


def _counted(*counts: tuple[int, str]) -> list[str]:
    """The counts that aren't zero, the way a step's line shows them: "3 found"."""
    return [f"{n} {words}" for n, words in counts if n]


def _n(n: int, noun: str, what: str = "") -> tuple[int, str]:
    """A count that reads well alone, for ``_counted``: (3, "songs matched"), (1, "new tab")."""
    return n, f"{noun if n == 1 else noun + 's'} {what}".rstrip()


def _provider_result(ctx: StepContext, provider: str, *, errors: int, error: str, spent: bool, status: str,
                     failures: Iterable[tuple[Any, BaseException]] = (), **fields: Any) -> StepResult:
    """A provider step's result: its errors recorded in the provider's health (``error`` says how
    many), the songs an error left (``failures``), a spent budget on the line and in the status."""
    if errors:
        record_error(ctx.conn, provider, ctx.now, error)
    return StepResult(failures=[Failure.of(song, e) for song, e in failures], spent=[provider] if spent else [],
                      status=status + (" (budget spent)" if spent else ""), **fields)


def _sync(ctx: StepContext) -> StepResult:
    from caracole.sources import sync_sources

    r = sync_sources(ctx.conn, ctx.cfg, ctx.now)
    result = StepResult(title="Songs", status=r.summary())
    w = r.wanted
    if w.new:  # a night with no new song needs no line
        result.done = [f"{w.seen} in wanted.txt", f"{w.new} new"]
    if w.errors and not w.line_errors:  # the file itself couldn't be read
        result.actions.append(unreadable_wanted(w.errors))
    elif w.line_errors:
        result.actions.append(Action(f"fix the {plural(len(w.line_errors), 'line')} of wanted.txt caracole "
                                     "couldn't read", "The to-do page says what is wrong with each.", rank=40))
    return result


def _icons(ctx: StepContext) -> StepResult:
    """The icons index.html lacks of the sites the library has something from (icons.py), with the
    run's own clients: never a provider's that cools down or blocked this run. Early, so that a
    site's budget is never spent before it: an icon costs a request or two, once. A block raises,
    and ends the step as any block does."""
    from caracole.icons import fetch_icons, sources_in_use

    clients = {p: c for p, c in ctx.services.clients.items()
               if p not in ctx.report.blocked and not is_cooling(ctx.conn, p, ctx.now)}
    run = fetch_icons(ctx.conn, ctx.cfg.cache_dir, clients, ctx.now, only=sources_in_use(ctx.conn))
    return StepResult(title="Site icons", done=_counted((len(run.fetched), "fetched")),
                      status=f"{len(run.fetched)} fetched, {len(run.missing)} not there, "
                             f"{plural(len(run.errors), 'error')}, {len(run.waiting)} waiting")


def _index(ctx: StepContext) -> StepResult:
    from caracole.ug.index import index_count, refresh_index

    if index_count(ctx.conn) == 0:
        return StepResult(title="Index refresh", actions=[BUILD_INDEX],
                          status="skipped: the index is empty; run `caracole index build` once")
    stats = refresh_index(ctx.conn, ctx.services.client("ug"), ctx.now)
    dirty = len(stats.songs_marked)
    new = len(stats.new_tab_ids)
    return StepResult(title="Index refresh",
                      done=_counted(_n(new, "new tab"), _n(dirty, "song", "to fetch again")),
                      status=f"{new} new tabs, {dirty} songs to refetch")


def _match(ctx: StepContext) -> StepResult:
    from caracole.match import match_all
    from caracole.ug.artist_tabs import backfill
    from caracole.ug.index import index_state

    # Once, the artist pages caracole read before it kept their tabs for searches, from its HTTP cache: no
    # request, so here, where nothing waits for Ultimate Guitar's cooldown (ug/artist_tabs.py).
    if (ug := ctx.services.clients.get("ug")) is not None:
        backfill(ctx.conn, ug, ctx.overrides)
    state = index_state(ctx.conn)
    if state == "empty":
        # Matching against an empty index would mark every song not found (and put it on the
        # buy list); errors are not misses, and a missing index is not evidence of absence.
        return StepResult(title="Matching", actions=[BUILD_INDEX],
                          status="skipped: the index is empty; run `caracole index build` once")
    if state == "partial":
        # Nor is an index a build left half-done: the songs in the sitemaps it didn't read would
        # be marked not found. Stored decisions stay; the index step's refresh reads the rest.
        return StepResult(title="Matching", actions=[FINISH_INDEX],
                          status="skipped: the index is incomplete; the next refresh, or `caracole index build`, "
                                 "reads the rest")
    changes = match_all(ctx.conn, ctx.overrides, ctx.cfg.match)
    changed = [c.new.decision for c in changes if c.old != c.new.decision]
    matched = sum(1 for d in changed if d in ("accept", "pinned"))
    return StepResult(
        title="Matching",
        done=_counted(_n(matched, "song", "matched"), _n(changed.count("review"), "song", "to review"),
                      _n(changed.count("not_found"), "song", "not on Ultimate Guitar")),
        status=f"{len(changed)} decisions changed",
    )


def _lyrics(ctx: StepContext) -> StepResult:
    from caracole.lyrics import fetch_pending_lyrics

    s = fetch_pending_lyrics(ctx.conn, ctx.services.client("lrclib"), ctx.cfg.library_dir, ctx.now)
    return _provider_result(
        ctx, "lrclib", errors=s.errors, error=f"{plural(s.errors, 'song')} failed this run", spent=s.budget_exhausted,
        status=f"{s.found} found, {s.missing} missing, {s.instrumental} instrumental, {plural(s.errors, 'error')}",
        failures=s.failures, title="Lyrics",
        done=_counted((s.found, "found"), (s.missing, "missing"), (s.instrumental, "instrumental")),
        retry="the lyrics of {songs} will be tried again on the next run",
    )


def _fetch(ctx: StepContext) -> StepResult:
    from caracole.ug.fetch import FetchContext, fetch_songs, rescore_kept_sheets, songs_to_fetch

    # Sheets kept before their lyrics arrived are scored first (no requests), so a partial one
    # shows on the to-do page and the fetch and LaCuerda can tell it from a complete one.
    rescored = rescore_kept_sheets(ctx.conn, ctx.cfg.library_dir, ctx.cfg.rank)
    fctx = FetchContext(
        conn=ctx.conn, client=ctx.services.client("ug"), overrides=ctx.overrides, rank=ctx.cfg.rank,
        library_dir=ctx.cfg.library_dir, now=ctx.now,
        # A lookup the run lets go first, in a pause, may pin a song: read again after one (_Handoffs).
        reload_overrides=lambda: load_overrides(ctx.cfg.overrides_file),
    )
    s = fetch_songs(fctx, songs_to_fetch(ctx.conn, ctx.overrides, ctx.now))
    scored = f", {plural(rescored, 'kept sheet')} rescored" if rescored else ""
    sheets = f"{plural(s.sheets_done, 'sheet')} settled, " if s.sheets_done else ""
    result = _provider_result(
        ctx, "ug", errors=s.songs_failed, error=f"{plural(s.songs_failed, 'song')} failed this run",
        spent=s.budget_exhausted,
        status=f"{sheets}{plural(s.songs_done, 'song')} done, {s.songs_failed} failed{scored}",
        failures=s.failures, title="Ultimate Guitar",
        done=_counted(_n(s.sheets_done, "sheet", "settled"), _n(s.songs_done, "song", "done"),
                      _n(rescored, "kept sheet", "rescored")),
        retry="{songs} will be looked for on Ultimate Guitar again on the next run",
    )
    result.problems += [shared_folder(e) for e in s.shared]
    return result


def _lacuerda(ctx: StepContext) -> StepResult:
    from caracole import lacuerda_fetch, lacuerda_index

    client = ctx.services.client("lacuerda")
    # A lookup the run lets go first, in a pause, may pin a tab: read again after one, as the fetch does.
    s = lacuerda_fetch.lacuerda_sheets(ctx.conn, client, ctx.cfg.library_dir, ctx.cfg.rank, ctx.now,
                                       overrides=ctx.overrides,
                                       reload_overrides=lambda: load_overrides(ctx.cfg.overrides_file))
    # The artist listings, for searches to suggest LaCuerda's artists, get what the sheets left of the budget;
    # as MuseScore's sitemaps, only once the library has a song, so that an empty one asks no site. Then, once
    # they are read whole, the most popular artists' pages get what is left (lacuerda_fetch.popular_pages).
    wanted = any(song.status != "ignored" and song.key not in ctx.overrides.ignore for song in list_songs(ctx.conn))
    ix = (lacuerda_index.index_pass(ctx.conn, client, ctx.now) if wanted and not s.budget_exhausted
          else lacuerda_index.IndexStats())
    pop = (lacuerda_fetch.popular_pages(ctx.conn, client, ctx.now)
           if wanted and not s.budget_exhausted and not ix.budget_exhausted else lacuerda_fetch.PopularStats())
    popular = f"; {plural(pop.read, 'popular artist page')} read, {plural(pop.errors, 'error')}" if pop.read else ""
    artists, songs = lacuerda_index.index_size(ctx.conn)
    result = _provider_result(
        ctx, "lacuerda", errors=s.errors, error=f"{plural(s.errors, 'song')} failed this run",
        spent=s.budget_exhausted or ix.budget_exhausted,
        status=(f"{s.tried} tried, {plural(s.kept, 'sheet')} kept, {s.missing} not on LaCuerda, "
                f"{plural(s.errors, 'error')}; artist index: {plural(ix.pages, 'page')} read, "
                f"{plural(artists, 'artist')}, {plural(songs, 'song')}{popular}"),
        failures=s.failures, title="LaCuerda",
        done=_counted(_n(s.kept, "sheet", "kept"), _n(s.missing, "song", "not there"),
                      _n(ix.pages, "page", "of artists read"),
                      _n(pop.read, "popular artist page", "read")),
        retry="{songs} will be looked for on LaCuerda again on the next run",
    )
    result.problems += [shared_folder(e) for e in s.shared]
    if ix.errors:
        record_error(ctx.conn, "lacuerda", ctx.now, "its artist listings couldn't be read this run")
        result.problems.append(Problem("LaCuerda's artist listings couldn't be read this run; they are asked for "
                                       "again on the next run, and the log says why."))
    return result


def _gtptabs(ctx: StepContext) -> StepResult:
    from caracole.gtptabs_fetch import gtptabs_files

    s = gtptabs_files(ctx.conn, ctx.services.client("gtptabs"), ctx.cfg.library_dir, ctx.now,
                      overrides=ctx.overrides)
    index = f"{plural(s.sitemaps, 'sitemap')} indexed, " if s.sitemaps else ""
    result = _provider_result(
        ctx, "gtptabs", errors=s.errors, error=f"{plural(s.errors, 'error')} this run", spent=s.budget_exhausted,
        status=(f"{index}{s.tried} tried, {plural(s.kept, 'Guitar Pro file')} kept, {s.missing} not on gtptabs.com, "
                f"{plural(s.errors, 'error')}"),
        failures=s.failures, title="gtptabs.com",
        done=_counted(_n(s.kept, "Guitar Pro file", "downloaded"), _n(s.missing, "song", "not there")),
        retry="{songs} will be looked for on gtptabs.com again on the next run",
    )
    if s.sitemap_errors:  # a song's error is on its failure's line
        result.problems.append(Problem("gtptabs.com's sitemaps couldn't be read this run; they are asked for again "
                                       "on the next run, and the log says why."))
    return result


def _harptabs(ctx: StepContext) -> StepResult:
    from caracole.harptabs_fetch import harptabs_tabs
    from caracole.harptabs_index import ArtistPassStats, artist_pass, index_state

    client = ctx.services.client("harptabs")
    s = harptabs_tabs(ctx.conn, client, ctx.cfg.library_dir, ctx.now, overrides=ctx.overrides)
    # The artist pages, for searches to find harptabs.com's tabs by artist, get what the tabs left of the budget
    # (harptabs_index.py: your songs' artists first); as LaCuerda's listings, only once the library has a song, so
    # that an empty one asks no site. The sitemap is asked for again only when the tabs' pass didn't fail on it.
    wanted = any(song.status != "ignored" and song.key not in ctx.overrides.ignore for song in list_songs(ctx.conn))
    ax = (artist_pass(ctx.conn, client, ctx.now, overrides=ctx.overrides, refresh_index=not s.sitemap_errors)
          if wanted and not s.budget_exhausted else ArtistPassStats())
    state = index_state(ctx.conn)
    sitemaps = s.sitemaps + ax.sitemaps
    index = f"{plural(sitemaps, 'sitemap')} indexed, " if sitemaps else ""
    artists = (f"; artist index: {plural(ax.read, 'page')} read, {state.read:,} of {plural(state.artists, 'artist')}"
               if ax.read or ax.errors else "")
    result = _provider_result(
        ctx, "harptabs", errors=s.errors, error=f"{plural(s.errors, 'error')} this run",
        spent=s.budget_exhausted or ax.budget_exhausted,
        status=(f"{index}{s.tried} tried, {plural(s.kept, 'harmonica tab')} kept, {s.missing} not on harptabs.com, "
                f"{plural(s.errors, 'error')}{artists}"),
        failures=s.failures, title="harptabs.com",
        done=_counted(_n(s.kept, "harmonica tab", "kept"), _n(s.missing, "song", "not there"),
                      _n(ax.read, "artist page", "read")),
        retry="{songs} will be looked for on harptabs.com again on the next run",
    )
    if s.sitemap_errors or ax.sitemap_error:  # a song's error is on its failure's line
        result.problems.append(Problem("harptabs.com's sitemap couldn't be read this run; it is asked for again "
                                       "on the next run, and the log says why."))
    pages = ax.errors - ax.sitemap_error
    if pages:
        record_error(ctx.conn, "harptabs", ctx.now, f"{plural(pages, 'artist page')} couldn't be read this run")
        result.problems.append(Problem(f"{plural(pages, 'artist page')} of harptabs.com couldn't be read this run; "
                                       "they are asked for again on the next run, and the log says why."))
    return result


def _gametabs(ctx: StepContext) -> StepResult:
    from caracole.gametabs_fetch import gametabs_tabs
    from caracole.gametabs_index import GamePassStats, game_pass, index_state

    client = ctx.services.client("gametabs")
    s = gametabs_tabs(ctx.conn, client, ctx.cfg.library_dir, ctx.now, overrides=ctx.overrides)
    # The game pages, for a song to be found by its composer and searches by composer, get what the tabs left of the
    # budget (gametabs_index.py: your songs' games first); only once the library has a song, so that an empty one asks
    # no site. The sitemaps are asked for again only when the tabs' pass didn't fail on them.
    wanted = any(song.status != "ignored" and song.key not in ctx.overrides.ignore for song in list_songs(ctx.conn))
    gx = (game_pass(ctx.conn, client, ctx.now, overrides=ctx.overrides, refresh_index=not s.sitemap_errors)
          if wanted and not s.budget_exhausted else GamePassStats())
    state = index_state(ctx.conn)
    sitemaps = s.sitemaps + gx.sitemaps
    index = f"{plural(sitemaps, 'sitemap')} indexed, " if sitemaps else ""
    games = (f"; game index: {plural(gx.read, 'page')} read, {state.read:,} of {plural(state.pages, 'game page')}"
             if gx.read or gx.errors else "")
    result = _provider_result(
        ctx, "gametabs", errors=s.errors, error=f"{plural(s.errors, 'error')} this run",
        spent=s.budget_exhausted or gx.budget_exhausted,
        status=(f"{index}{s.tried} tried, {plural(s.kept, 'tab')} kept, {s.missing} not on gametabs.net, "
                f"{plural(s.errors, 'error')}{games}"),
        failures=s.failures, title="gametabs.net",
        done=_counted(_n(s.kept, "game music tab", "kept"), _n(s.missing, "song", "not there"),
                      _n(gx.read, "game page", "read")),
        retry="{songs} will be looked for on gametabs.net again on the next run",
    )
    if s.sitemap_errors or gx.sitemap_error:  # a song's error is on its failure's line
        result.problems.append(Problem("gametabs.net's sitemaps couldn't be read this run; they are asked for again "
                                       "on the next run, and the log says why."))
    pages = gx.errors - gx.sitemap_error
    if pages:
        record_error(ctx.conn, "gametabs", ctx.now, f"{plural(pages, 'game page')} couldn't be read this run")
        result.problems.append(Problem(f"{plural(pages, 'game page')} of gametabs.net couldn't be read this run; "
                                       "they are asked for again on the next run, and the log says why."))
    return result


def _musescore(ctx: StepContext) -> StepResult:
    from caracole.musescore_fetch import index_size, musescore_index

    s = musescore_index(ctx.conn, ctx.services.client("musescore"), ctx.now, overrides=ctx.overrides)
    read = f"{plural(s.sitemaps, 'sitemap')} indexed, " if s.sitemaps else ""
    errors = f", {plural(s.errors, 'error')}" if s.errors else ""
    result = _provider_result(
        ctx, "musescore", errors=s.errors, error=f"{plural(s.errors, 'error')} this run", spent=s.budget_exhausted,
        status=f"{read}{plural(index_size(ctx.conn), 'song page')} in the index{errors}", title="MuseScore",
        done=_counted(_n(s.sitemaps, "song sitemap", "read")),
    )
    if s.errors:
        result.problems.append(Problem("MuseScore's song sitemaps couldn't be read this run; they are asked for "
                                       "again on the next run, and the log says why."))
    return result


def _youtube(ctx: StepContext) -> StepResult:
    from caracole.youtube_fetch import route_problem, youtube_pass

    problem = route_problem(ctx.cfg)
    runner = ctx.services.clients.get("youtube")
    if problem is not None or runner is None:
        return StepResult(status=f"skipped: {problem or 'no yt-dlp runner this run'}")
    s = youtube_pass(ctx.conn, runner, ctx.cfg, ctx.now, overrides=ctx.overrides)
    return _provider_result(
        ctx, "youtube", errors=s.errors, error=f"{plural(s.errors, 'song')} failed this run", spent=s.budget_exhausted,
        status=(f"{s.tried} tried, {s.downloaded} downloaded, {s.missing} not on YouTube, {s.unavailable} unavailable, "
                f"{plural(s.errors, 'error')}"),
        failures=s.failures, title="YouTube",
        done=_counted(_n(s.downloaded, "song", "downloaded"), _n(s.missing, "song", "not there")),
        retry="{songs} will be looked for on YouTube again on the next run",
    )


def _scan(ctx: StepContext) -> StepResult:
    from caracole.inbox import file_inbox
    from caracole.music import scan_music

    music = scan_music(ctx.conn, ctx.cfg.music_dir)
    inbox = file_inbox(ctx.conn, ctx.cfg.library_dir)
    refused = len(inbox.refused)  # links in the inbox, or in its place, never read: the to-do page names them
    links = f", {plural(refused, 'symbolic link')} refused" if refused else ""
    filed = len(inbox.filed)
    result = StepResult(
        title="Music and inbox",
        done=_counted(_n(music.matched, "purchase", "linked"), _n(filed, "Guitar Pro file", "filed")),
        status=f"{music.matched} purchases linked, {filed} Guitar Pro files filed{links}",
    )
    if refused:
        result.problems.append(Problem(f"{plural(refused, 'symbolic link')} in _inbox, or in its place, "
                                       f"{'was' if refused == 1 else 'were'} left unread; the to-do page names "
                                       f"{'it' if refused == 1 else 'them'}."))
    return result


def _render(ctx: StepContext) -> StepResult:
    from caracole.commands._common import hand_over
    from caracole.render import render_all

    # Many PDFs to make (a new font, say) take minutes: a waiting lookup goes between two songs.
    s = render_all(ctx.conn, ctx.cfg, ctx.overrides, now=ctx.now, between=lambda: hand_over(ctx.cfg, ctx.conn))
    ctx.read_overrides_again()  # and what such a lookup changed, for the songbooks
    tail = f"; {s.font_error}" if s.font_error else ""
    result = StepResult(title="PDFs", done=_counted((s.rendered, "rendered")),
                        status=f"{s.rendered} rendered, {s.failed} failed{tail}")
    if s.failed:
        them = "it" if s.failed == 1 else "them"
        result.problems.append(Problem(f"{plural(s.failed, 'song')} got no PDF: the to-do page names {them}, "
                                       "and the log says why."))
    if s.font_error:
        result.problems.append(Problem(s.font_error))
    _render_songbooks(ctx, result)
    return result


def _render_songbooks(ctx: StepContext, result: StepResult) -> None:
    """The songbooks' files, after the sheets they hold (songbook.py), on the render step's line."""
    from caracole.songbook import render_songbooks

    b = render_songbooks(ctx.conn, ctx.cfg, ctx.overrides)
    result.done += _counted(_n(b.rendered, "songbook", "made"))
    if b.rendered or b.skipped or b.failed:
        result.status += f"; songbooks: {b.rendered} rendered, {len(b.failed)} failed"
    if b.error:
        result.problems.append(Problem(f"No songbook was made: {b.error}. Fix songbooks.toml, then run caracole "
                                       "songbook render."))
    if b.failed:
        result.problems.append(Problem(f"{plural(len(b.failed), 'songbook')} couldn't be made in full "
                                       f"({', '.join(b.failed)}): the log says why."))
    if b.font_error:
        result.problems.append(Problem(b.font_error))


def _todo(ctx: StepContext) -> StepResult:
    from caracole.todo import write_pages

    _settle(ctx.conn, ctx.report, ctx.services, ctx.now)  # before the page, so its provider health shows this run
    page, _ = write_pages(ctx.conn, ctx.cfg, ctx.overrides, ctx.now)
    return StepResult(todo=_needs_you(page))


def _needs_you(page: Path) -> NeedsYou:
    """How many things the to-do page just written lists for you."""
    from caracole.library import read_regular

    return NeedsYou(todo_count(read_regular(page).decode("utf-8", "replace")), page)


def _todo_for_broken_overrides(cfg: Config, conn: sqlite3.Connection, now: datetime, error: str,
                               report: RunReport) -> None:
    """No step can run, but the page you read still says why: it leads with the error.

    index.html is left as it was: built without your overrides it would lose your
    transpositions and ignored songs.
    """
    from caracole.todo import build_todo, write_todo

    try:
        page = write_todo(cfg.library_dir, build_todo(conn, cfg, Overrides(), now, overrides_error=error))
        report.results["todo"] = StepResult(todo=_needs_you(page))  # for the summary: no step ran
    except Exception as e:  # a bug, or a library folder that can't be written; the run fails anyway
        log.error("The to-do page couldn't be written: %s: %s.", type(e).__name__, e, exc_info=True)
        report.errors.append(f"todo: {type(e).__name__}: {e}")


def default_steps() -> list[Step]:
    return [
        Step("sync", _sync),
        Step("icons", _icons),
        Step("index", _index, provider="ug"),
        Step("match", _match),
        Step("lyrics", _lyrics, provider="lrclib"),
        Step("fetch", _fetch, provider="ug"),
        Step("lacuerda", _lacuerda, provider="lacuerda"),
        Step("scan", _scan),
        # After the scan: a file you dropped into _inbox/ is filed first, so its song gets no other.
        Step("gtptabs", _gtptabs, provider="gtptabs"),
        Step("harptabs", _harptabs, provider="harptabs"),
        Step("gametabs", _gametabs, provider="gametabs"),
        Step("musescore", _musescore, provider="musescore"),
        # After the scan, so a purchase dropped into Music/ is linked first and nothing is downloaded for it.
        Step("youtube", _youtube, provider="youtube"),
        Step("render", _render),
        Step("todo", _todo),
    ]


# --- orchestration ---------------------------------------------------------------


def make_services(cfg: Config, conn: sqlite3.Connection, run_id: str) -> Services:
    """Real clients for a run: one polite client per provider turned on, and yt-dlp when the YouTube
    route is on (``youtube_fetch.route_problem``).

    The clients are the commands' own (``commands._common.make_client`` and
    ``make_youtube``): each holds caracole's lock until it is closed, and its first
    request keeps the pause after the provider's last one, whichever caracole sent it.
    """
    from caracole.commands._common import make_client, make_youtube, transport_for
    from caracole.youtube_fetch import route_problem

    clients: dict[str, Any] = {}
    try:
        for p in PROVIDERS:
            if cfg.provider(p).enabled:
                clients[p] = make_client(cfg, conn, p, run_id)
        if route_problem(cfg) is None:
            clients["youtube"] = make_youtube(cfg, conn, run_id)
    except BaseException:  # Ctrl-C during a pause, say: the clients made let go of the lock
        for client in clients.values():
            client.close()
        raise
    notifier = Notifier(cfg.ntfy.url, transport=transport_for("ntfy"))
    return Services(clients=clients, notifier=notifier)


def _requests(services: Services) -> dict[str, int]:
    return {p: int(getattr(c, "requests_made", 0)) for p, c in services.clients.items()}


def _budgets(services: Services) -> dict[str, int]:
    """Each client's request budget for the run, when it has one (a ``PoliteClient``'s policy)."""
    budgets = {}
    for p, c in services.clients.items():
        budget = getattr(getattr(c, "policy", None), "budget", None)
        if isinstance(budget, int):
            budgets[p] = budget
    return budgets


def _record_ok(conn: sqlite3.Connection, report: RunReport, now: datetime) -> None:
    """A provider that answered this run without a block had a good run: clear its cooldown, note the time.

    A run whose every request failed (UG answering 502, say) is no success.
    """
    for p, n in report.requests.items():
        if n and p not in report.blocked and answered_any(conn, report.run_id, p, n):
            record_ok(conn, p, now)


def _settle(conn: sqlite3.Connection, report: RunReport, services: Services, now: datetime, *,
            started: float | None = None) -> None:
    """The run so far into kv ``run:last``: each provider's requests and budget, and its health
    (``_record_ok``); at the run's end (``started``), how long it took, timed after the health."""
    report.requests = _requests(services)
    report.budgets = _budgets(services)
    _record_ok(conn, report, now)
    if started is not None:
        report.seconds = clock() - started
    kv_set_json(conn, "run:last", _report_json(report))


def _report_json(report: RunReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id, "started": report.started, "finished": report.finished,
        "steps": report.steps, "blocked": report.blocked, "errors": report.errors, "requests": report.requests,
        "budgets": report.budgets, "seconds": report.seconds,
    }


def run_pipeline(
    cfg: Config,
    *,
    conn: sqlite3.Connection,
    services: Services | None = None,
    steps: list[Step] | None = None,
    now: datetime | None = None,
) -> RunReport:
    """Run the steps (by default ``default_steps``) and report; see the module docstring.

    Services the run makes itself (``make_services``) are closed when it ends,
    and with their clients goes the hold they had on caracole's lock.
    """
    started = clock()
    clock_given = now is not None
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    run_id = _iso(now)
    # Before any step reads songs by key, as the sync reads wanted.txt's first-seen times.
    ensure_current_keys(conn)
    own = services is None
    if own:
        services = make_services(cfg, conn, run_id)
    try:
        return _run(cfg, conn, services, steps, now, run_id, clock_given, started)
    finally:
        if own:
            services.close()


def _skipped(cfg: Config, conn: sqlite3.Connection, report: RunReport, step: Step,
             now: datetime) -> StepResult | None:
    """Why a step doesn't run, if it doesn't: its provider is turned off, blocked this run, or cooling down."""
    p = step.provider
    if p and not cfg.provider(p).enabled:
        return StepResult(status=f"skipped: {p} is off ([providers.{p}] enabled = false)")
    if p and p in report.blocked:  # the block's own line says it
        return StepResult(status=f"skipped: {p} blocked this run")
    if p and is_cooling(conn, p, now):
        until = get_state(conn, p).cooldown_until
        return StepResult(problems=[cooling(p, until)], status=f"skipped: {p} cooling down until {when(until)}")
    return None


def _run_step(ctx: StepContext, step: Step) -> StepResult | str | None:
    """Run one step; a provider's block, a spent budget, a provider's error or a bug becomes its result."""
    conn, now, report = ctx.conn, ctx.now, ctx.report
    try:
        return step.run(ctx)
    except ProviderBlocked as e:
        state = record_block(conn, e.provider, now, str(e))
        report.blocked.append(e.provider)
        problem = blocked(e, step.name, state.cooldown_until, strikes=state.strikes)
        ctx.services.notifier.send(f"caracole: {provider_name(e.provider)} blocked", problem.text,
                                   priority="high", tags=["warning"])
        return StepResult(problems=[problem], status=f"blocked: {e}")
    except BudgetExhausted as e:
        return StepResult(spent=[e.provider], status=f"budget spent ({e.provider})")
    except ProviderError as e:
        record_error(conn, e.provider, now, str(e))
        return StepResult(problems=[step_error(e, step.name)], status=f"error: {e}")
    except Exception as e:  # a bug: record it, keep going, fail the run at the end
        what = f"{type(e).__name__}: {e}"
        log.error("The %s step failed: %s. That's a bug in caracole; its traceback follows.", step.name, what,
                  exc_info=True)
        report.errors.append(f"{step.name}: {what}")
        return StepResult(problems=[bug(e, step.name)], status=f"failed: {what}")


def _run(cfg: Config, conn: sqlite3.Connection, services: Services, steps: list[Step] | None,
         now: datetime, run_id: str, clock_given: bool, started: float) -> RunReport:
    report = RunReport(run_id=run_id, started=run_id)
    try:
        overrides = load_overrides(cfg.overrides_file)
    except OverridesError as e:
        report.errors.append(f"overrides.toml: {e}")
        report.record("overrides", StepResult(actions=[fix_overrides(e)], status=f"failed: {e}"))
        _todo_for_broken_overrides(cfg, conn, now, str(e), report)
        report.seconds = clock() - started
        services.notifier.send("caracole run failed", report.summary(), priority="high", tags=["rotating_light"])
        return report
    ctx = StepContext(cfg=cfg, conn=conn, overrides=overrides, now=now, run_id=run_id, services=services,
                      report=report)

    for step in steps if steps is not None else default_steps():
        ctx.read_overrides_again()  # what a lookup the step before let go first changed
        result = _skipped(cfg, conn, report, step, now)
        report.record(step.name, result if result is not None else _run_step(ctx, step))
        log.info("%s: %s", step.name, report.steps[step.name])

    report.finished = run_id if clock_given else _iso(datetime.now(UTC))
    _settle(conn, report, services, now, started=started)
    title = "caracole run" if report.ok else "caracole run failed"
    services.notifier.send(title, report.summary(), priority=None if report.ok else "high",
                           tags=() if report.ok else ("rotating_light",))
    return report
