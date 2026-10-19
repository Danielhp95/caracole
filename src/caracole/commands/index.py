"""Index commands: ``caracole index build``, ``caracole index refresh`` and ``caracole index stats``.

The local UG index is built once from Ultimate Guitar's sitemaps, or from
sitemap files you already have, and the nightly run refreshes it. A block or
a spent budget is not a failure: the sitemaps read so far are kept, and the
command says what happens next. Every command module is imported on every
start, so the index module is imported inside the commands.

What build and refresh print comes from ``ug.index``'s progress events, put
into words by ``_Report``: what is indexed and what the sitemap index lists,
how much is to download and how long it should take, a line per sitemap with
the time left, then what the index holds and, for a partial index, how to
resume and where. On a terminal the sitemap lines share one live line; in a
journal or a pipe each is a plain line (``caracole.progress.Console``). A
refresh says less: a line per changed sitemap, then one line for it all.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeVar

import typer

from caracole.commands import _common
from caracole.commands._common import exclusive, fail, load_cfg, open_db, run_id_for, utcnow
from caracole.progress import Console, Pace, about, duration

if TYPE_CHECKING:
    from caracole.config import Config, ProviderPolicy
    from caracole.http import Client
    from caracole.ug.index import Coverage, IndexPlan, IndexStats, SitemapRead

    T = TypeVar("T")


# A full build is about 42 requests (the sitemap index and 41 tab sitemaps), more than one night's budget.
BUILD_BUDGET = 100
_KEPT = "the sitemaps read so far are kept"
_FILE_PACE = 0.5  # seconds to read one 25 MB sitemap file, about: the 41 take about 22 s
clock = time.monotonic  # tests replace it


def console() -> Console:
    """Where the index commands report: stdout, with a live line on a terminal. Tests replace it."""
    return Console()


def register(app: typer.Typer) -> None:
    index = typer.Typer(help="The local index of Ultimate Guitar's tabs, built from its sitemaps.",
                        no_args_is_help=True)
    app.add_typer(index, name="index")

    @index.command("build")
    def build_cmd(
        ctx: typer.Context,
        from_dir: Path | None = typer.Option(
            None, "--from", metavar="DIR", exists=True, file_okay=False, dir_okay=True,
            help="Read sitemapN.xml[.gz] and sitemap_last.xml[.gz] from DIR instead (no requests).",
        ),
    ) -> None:
        """Index every UG tab sitemap: about 42 requests, 10-20 s apart (about 10 minutes)."""
        _build(load_cfg(ctx), from_dir)

    @index.command("refresh")
    def refresh_cmd(ctx: typer.Context) -> None:
        """Re-read the sitemaps where new tabs appear, as the nightly run does."""
        _refresh(load_cfg(ctx))

    @index.command("stats")
    def stats_cmd(ctx: typer.Context) -> None:
        """How many tabs, of which types, and how many artists the index holds."""
        _stats(load_cfg(ctx))


# --- caracole index build ------------------------------------------------------------------------


def _build(cfg: Config, from_dir: Path | None) -> None:
    from caracole.config import ProviderPolicy
    from caracole.ug.index import build_index

    with exclusive(cfg, "index build"), closing(open_db(cfg)) as conn:
        now = utcnow()
        out = console()
        try:
            if from_dir is not None:
                report = _Report(out, files=from_dir)
                report.intro()
                try:
                    stats = _interruptible(conn, report, lambda: build_index(conn, None, now, from_dir=from_dir,
                                                                              progress=report))
                except (OSError, ValueError) as e:
                    report.finish(conn)
                    fail(f"index build: {e}")
                report.finish(conn, stats=stats)
                return
            ug = cfg.provider("ug")
            policy = ProviderPolicy(budget=max(BUILD_BUDGET, ug.budget), delay=ug.delay)
            report = _Report(out, delay=policy.delay, budget=policy.budget)
            report.intro()
            outcome = _interruptible(conn, report, lambda: _with_ug(
                conn, cfg, now, policy, report, lambda client: build_index(conn, client, now, progress=report)))
            report.finish(conn, stats=outcome.stats)
            if outcome.failure is not None:
                fail(outcome.failure)
        finally:
            out.close()


# --- caracole index refresh ----------------------------------------------------------------------


def _refresh(cfg: Config) -> None:
    from caracole.ug.index import index_count, mark_dirty_for_new, refresh_index

    with exclusive(cfg, "index refresh"), closing(open_db(cfg)) as conn:
        now = utcnow()
        if index_count(conn) == 0:
            fail("The index is empty: run `caracole index build` first.")
        policy = cfg.provider("ug")
        out = console()
        try:
            report = _Report(out, refresh=True, delay=policy.delay, budget=policy.budget)
            outcome = _interruptible(conn, report, lambda: _with_ug(
                conn, cfg, now, policy, report, lambda client: refresh_index(conn, client, now, progress=report)))
            dirty = mark_dirty_for_new(conn, outcome.stats.new_tab_ids) if outcome.stats is not None else None
            report.finish(conn, stats=outcome.stats, refetch=dirty)
            if outcome.failure is not None:
                fail(outcome.failure)
        finally:
            out.close()


# --- caracole index stats ------------------------------------------------------------------------


def _stats(cfg: Config) -> None:
    from caracole.ug.index import index_stats

    with closing(open_db(cfg)) as conn:
        s = index_stats(conn)
    if not s["rows"]:
        typer.echo("The index is empty: run `caracole index build`.")
        return
    types = ", ".join(f"{kind} {n:,}" for kind, n in s["types"].items())
    typer.echo(f"Tabs: {s['rows']:,} ({types})")
    typer.echo(f"Artists: {s['artists']:,}")
    typer.echo(f"Sitemaps indexed: {s['sitemaps']}")
    typer.echo(f"Newest tab id: {s['newest_tab_id']}")
    typer.echo(f"Built: {s['built_at'] or 'never'}; refreshed: {s['refreshed_at'] or 'never'}")


# --- shared ------------------------------------------------------------------------------------


@dataclass
class _Outcome:
    """What ``_with_ug`` came to: the action's stats, unless it stopped; a failure to exit 1 with."""

    stats: IndexStats | None = None
    failure: str | None = None


def _with_ug(conn: sqlite3.Connection, cfg: Config, now: datetime, policy: ProviderPolicy, report: _Report,
             action: Callable[[Client], IndexStats]) -> _Outcome:
    """Run ``action`` with a polite UG client, the way the nightly run treats UG.

    A cooldown means no request is sent; a block starts (or doubles) the
    cooldown; neither, nor a spent budget, is a failure: the report says so, and
    the outcome has no stats. Any other provider error is recorded and comes
    back as the outcome's failure, which exits 1 once the report is out. The
    client is the commands' own (``make_client``), with ``policy`` for UG's.
    """
    from caracole.health import get_state, is_cooling, record_block, record_error, record_ok
    from caracole.http import BudgetExhausted, Event, ProviderBlocked, ProviderError

    if is_cooling(conn, "ug", now):
        until = get_state(conn, "ug").cooldown_until
        report.stopped(f"Ultimate Guitar is cooling down after a block until {_when(until)}; no request was sent.",
                       until=until)
        return _Outcome()
    answered = 0

    def on_event(event: Event) -> None:
        nonlocal answered
        if event.decision in ("ok", "not_modified"):  # an error or a block is no answer
            answered += 1

    report.asking()
    client = _common.make_client(cfg, conn, "ug", run_id_for(now), policy=policy, on_event=on_event)
    report.requests = lambda: client.requests_made
    outcome = _Outcome()
    try:
        outcome.stats = action(client)
    except ProviderBlocked as e:
        state = record_block(conn, "ug", now, str(e))
        report.stopped(f"Ultimate Guitar blocked caracole ({e}). No more requests to it until "
                       f"{_when(state.cooldown_until)} (block #{state.strikes}); {_KEPT}.", until=state.cooldown_until)
        return outcome
    except BudgetExhausted:
        report.stopped(f"The Ultimate Guitar budget of {policy.budget} requests is spent; {_KEPT}.")
    except ProviderError as e:
        record_error(conn, "ug", now, str(e))
        outcome.failure = f"Ultimate Guitar failed: {e}. The sitemaps read so far are kept."
    finally:
        client.close()
    if answered:
        record_ok(conn, "ug", now)  # UG answered without a block, as the nightly run records it
    return outcome


def _interruptible(conn: sqlite3.Connection, report: _Report, action: Callable[[], T]) -> T:
    """``action()``; on Ctrl-C, the report of what was done and how to resume, then Ctrl-C goes on
    (to exit 130, as it ends any command)."""
    try:
        return action()
    except KeyboardInterrupt:
        report.stopped(f"Stopped by Ctrl-C; {_KEPT}.")
        report.finish(conn)
        raise


class _Report:
    """What ``caracole index build`` and ``refresh`` print, from ``ug.index``'s progress events.

    ``intro`` and ``asking`` come before the first request, the events
    (``__call__``, the ``progress`` callback) as the sitemaps are read, and
    ``stopped`` with ``finish`` at the end. The time left starts from the
    pacing, ``delay``, and moves to the pace measured (``Pace``).
    """

    def __init__(self, console: Console, *, refresh: bool = False, files: Path | None = None,
                 delay: tuple[float, float] = (0.0, 0.0), budget: int | None = None):
        self.console = console
        self.refresh = refresh
        self.files = files
        self.delay = delay
        self.budget = budget
        self.requests: Callable[[], int] = lambda: 0  # how many this run sent, once the client is made
        self.started = clock()
        self.plan: IndexPlan | None = None
        self.reads: list[SitemapRead] = []
        self.until: datetime | None = None  # when UG's cooldown ends, after a block
        self._stopped = False
        self._pace: Pace | None = None

    # -- before the first request --------------------------------------------------------------

    def intro(self) -> None:
        """What a build indexes, and from what."""
        self.console.note("Indexing Ultimate Guitar's tab pages as rows of artist, title and type, "
                          "to match your songs offline.")
        if self.files is not None:
            self.console.note(f"Only the sitemap files in {self.files} are read: no request is sent.")
        else:
            self.console.note("Only the sitemaps UG publishes for search engines are read: no tab itself is downloaded.")

    def asking(self) -> None:
        """The first request, for the sitemap index, is about to go."""
        self.console.step("Checking the sitemap index for new tabs..." if self.refresh else "Reading the sitemap index...")

    # -- the progress events -------------------------------------------------------------------

    def __call__(self, event: IndexPlan | SitemapRead) -> None:
        from caracole.ug.index import IndexPlan

        if isinstance(event, IndexPlan):
            self._planned(event)
        else:
            self._read(event)

    def _planned(self, plan: IndexPlan) -> None:
        from caracole.ug.index import SITEMAP_MAX_URLS, describe_sitemaps

        self.plan = plan
        self._pace = Pace(_FILE_PACE if self.files is not None else sum(self.delay) / 2, clock=clock)
        reads = len(plan.reads)
        eta = about(self._pace.left(reads))
        urls = f"About {_roughly(plan.expected_urls)} tab URLs (up to {SITEMAP_MAX_URLS:,} a sitemap)"
        if self.files is not None:
            self.console.note(f"Found {_count(reads, 'sitemap file')} ({describe_sitemaps(plan.reads)}).")
            self.console.note(f"{urls}: {eta}.")
        elif self.refresh:
            new = [n for n in plan.reads if n not in plan.indexed]
            checks = [n for n in plan.reads if n in plan.indexed]
            if new:  # more than the nightly look at the newest sitemaps: say what and how long
                also = f", and checking {describe_sitemaps(checks)}" if checks else ""
                self.console.note(f"Reading {describe_sitemaps(new)}, not indexed yet{also}: "
                                  f"{_count(reads, 'request')}, {self._pacing()}, {eta}.")
        else:
            parts = [f"{len(plan.downloads):,} to download"] if plan.downloads else []
            if plan.cached:
                parts.append(f"{len(plan.cached):,} in the HTTP cache")
            if plan.indexed:
                parts.append(f"{len(plan.indexed):,} indexed already, asked for again and skipped if unchanged")
            self.console.note(f"The sitemap index lists {_count(len(plan.listed), 'tab sitemap')} "
                              f"({describe_sitemaps(plan.listed)}): {', '.join(parts)}.")
            work = f"{_count(reads, 'request')}, {self._pacing()}: {eta}."
            self.console.note(f"{urls}. {work}" if plan.expected_urls else work)
        if plan.reads:
            first = plan.reads[0]
            self.console.status(f"[{1:>{len(str(reads))}}/{reads}] {_label(first)}...", f"{reads:,} left, {eta}")

    def _read(self, event: SitemapRead) -> None:
        self.reads.append(event)
        if self._pace is not None:
            self._pace.step()
        left = event.total - event.position
        tail = f"{left:,} left, {about(self._pace.left(left))}" if left and self._pace is not None else ""
        if self.refresh and event.unchanged:
            self.console.status(_sitemap_line(event), tail)  # on a terminal only: a refresh stays compact
        else:
            self.console.step(_sitemap_line(event), tail)

    # -- the end -------------------------------------------------------------------------------

    def stopped(self, message: str, *, until: datetime | None = None) -> None:
        """Why the run stopped short: a block, a cooldown, the budget or Ctrl-C."""
        self._stopped = True
        self.until = until
        self.console.say(message, fg="yellow")

    def finish(self, conn: sqlite3.Connection, *, stats: IndexStats | None = None, refetch: int | None = None) -> None:
        """What the run did and what the index holds, then its state: complete, or how to resume.

        ``stats`` is None when the run stopped short; the events so far say what it did.
        """
        from caracole.ug.index import index_coverage, index_state

        if self.plan is None and not self._stopped:
            return  # it failed before it knew what to read: the error says it all
        if self.refresh:
            self._refresh_summary(stats, refetch)
        elif self.plan is not None:
            self._build_summary(conn, finished=stats is not None)
        self._state(index_state(conn), index_coverage(conn), finished=stats is not None)

    def _build_summary(self, conn: sqlite3.Connection, *, finished: bool) -> None:
        from caracole.ug.index import index_coverage, index_stats

        parsed = sum(1 for e in self.reads if not e.unchanged)
        unchanged = len(self.reads) - parsed
        new = _count(sum(len(e.new_tab_ids) for e in self.reads), "new tab")
        if not finished:
            some = f" ({parsed:,} read, {unchanged:,} unchanged)" if unchanged else ""
            self.console.say(f"Index build stopped after {len(self.reads):,} of {len(self.plan.reads):,} "
                             f"sitemaps{some}; {new}.")
        elif self.files is not None:
            self.console.say(f"Index built from {_count(parsed, 'sitemap file')}; {new}.")
        else:
            some = f", {unchanged:,} unchanged" if unchanged else ""
            self.console.say(f"Index built: {_count(parsed, 'sitemap')} read{some}; {new}.")
        s = index_stats(conn)
        if s["rows"]:
            self._row("Indexed", f"{_count(s['rows'], 'tab')}: " + ", ".join(f"{k} {n:,}" for k, n in s["types"].items()))
            self._row("Artists", f"{s['artists']:,}")
        tabs = index_coverage(conn).tabs
        if tabs.urls:
            self._row("Bare ids", f"{tabs.bare:,} of {tabs.urls:,} tab URLs ({100 * tabs.bare / tabs.urls:.1f}%): "
                      "with no artist or title in the URL, only artist pages lead to them")
            left_out = []
            if tabs.other_total:
                kinds = ", ".join(f"{k} {n:,}" for k, n in sorted(tabs.other.items(), key=lambda kn: (-kn[1], kn[0])))
                left_out.append(f"{tabs.other_total:,} of {'another type' if tabs.other_total == 1 else 'other types'}"
                                f" ({kinds})")
            if tabs.unrecognized:
                left_out.append(f"{tabs.unrecognized:,} unrecognized")
            if left_out:
                self._row("Left out", "; ".join(left_out))
            closed = tabs.closed + self.plan.dropped
            self._row("robots.txt", f"{_count(closed, 'tab')} left out: robots.txt closes their pages"
                      if closed else "no tab left out")
        self._row("Requests", "none: read from files" if self.files is not None
                  else f"{self.requests():,} of a budget of {self.budget:,}")
        self._row("Duration", duration(clock() - self.started))

    def _refresh_summary(self, stats: IndexStats | None, refetch: int | None) -> None:
        cost = f"{_count(self.requests(), 'request')}, {duration(clock() - self.started)}"
        if stats is not None:
            self.console.say(f"Index refreshed: {stats.summary(refetch)}. {cost}.")
        elif self.reads:
            self.console.say(f"Index refresh stopped: {_stats_of(self.reads).summary()}. {cost}.")

    def _state(self, state: str, cov: Coverage, *, finished: bool) -> None:
        after = f" after {_when(self.until)}" if self.until is not None else ""
        if state == "complete":
            if self.refresh:
                return  # the summary says it: "the index is now complete" when this refresh made it so
            if finished:
                self.console.say("The index is complete: `caracole match` can now match your songs against it, "
                                 "and the nightly run keeps it up to date.", fg="green")
            else:
                self.console.say("The index is still complete: the sitemaps this build didn't get to keep "
                                 "what they held.", fg="green")
            return
        if state == "empty":
            self.console.say(f"The index is empty: run `caracole index build` again{after}.", fg="yellow")
            return
        of = (f"{len(cov.indexed):,} of {_count(len(cov.listed), 'tab sitemap')}" if cov.listed is not None
              else _count(len(cov.indexed), "tab sitemap"))
        self.console.say(f"The index is partial: {of} indexed, so no song is matched against it yet.", fg="yellow")
        self.console.say(self._resume(cov, after))

    def _resume(self, cov: Coverage, after: str) -> str:
        from caracole.ug.index import describe_sitemaps

        if self.files is not None:
            return (f"To finish, run `caracole index build --from {self.files}` again: it reads every file again, "
                    "with no request.")
        if cov.listed is None:
            return (f"To resume, run `caracole index refresh`{after}: it reads the sitemaps not indexed yet. "
                    "The nightly run does the same.")
        checks = [n for n in cov.refresh if n not in cov.left]
        cost = f"{_count(len(cov.refresh) + 1, 'request')}, {about(len(cov.refresh) * sum(self.delay) / 2)}"
        if not cov.left:
            return (f"To finish, run `caracole index refresh`{after}: every sitemap is indexed, and checking "
                    f"{describe_sitemaps(checks)} marks the index complete ({cost}).")
        what = "the sitemap left" if len(cov.left) == 1 else f"the {len(cov.left):,} sitemaps left"
        also = f", and checks {describe_sitemaps(checks)}" if checks else ""
        return (f"To resume, run `caracole index refresh`{after}: it reads {what}, {describe_sitemaps(cov.left)}"
                f"{also} ({cost}). The nightly run does the same.")

    def _row(self, label: str, value: str) -> None:
        self.console.note(f"  {label:<11} {value}")

    def _pacing(self) -> str:
        low, high = self.delay
        return f"{low:g} s apart" if low == high else f"{low:g}-{high:g} s apart"


def _sitemap_line(event: SitemapRead) -> str:
    """``[ 7/41] sitemap7.xml  50,000 tabs: 44,120 indexed, 1,409 bare ids, 4,471 of other types``."""
    head = f"[{event.position:>{len(str(event.total))}}/{event.total}] {event.label}"
    if event.unchanged:
        return f"{head}  unchanged"
    tabs, new = event.tabs, len(event.new_tab_ids)
    parts = [f"{tabs.indexed:,} indexed" + ("" if new == tabs.indexed else f" ({new:,} new)" if new else " (none new)")]
    if tabs.bare:
        parts.append(_count(tabs.bare, "bare id"))
    if tabs.other_total:
        parts.append(f"{tabs.other_total:,} of {'another type' if tabs.other_total == 1 else 'other types'}")
    if tabs.closed:
        parts.append(f"{tabs.closed:,} closed by robots.txt")
    if tabs.unrecognized:
        parts.append(f"{tabs.unrecognized:,} unrecognized")
    source = " (from the HTTP cache)" if event.from_cache else ""
    return f"{head}  {_count(tabs.urls, 'tab')}{source}: {', '.join(parts)}"


def _stats_of(reads: list[SitemapRead]) -> IndexStats:
    """What the sitemaps read so far did, as ``refresh_index`` would have returned it."""
    from caracole.ug.index import IndexStats

    parsed = [e for e in reads if not e.unchanged]
    return IndexStats(sitemaps_fetched=len(parsed), sitemaps_unchanged=len(reads) - len(parsed),
                      rows=sum(e.tabs.indexed for e in parsed),
                      new_tab_ids=tuple(chain.from_iterable(e.new_tab_ids for e in parsed)),
                      parsed=tuple(e.name for e in parsed))


def _label(name: str) -> str:
    from caracole.ug.sitemap import sitemap_label

    return sitemap_label(name)


def _roughly(n: int) -> str:
    return f"{n / 1_000_000:.1f}".removesuffix(".0") + " million" if n >= 1_000_000 else f"{n:,}"


def _count(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _when(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "?"
