"""The nightly ``caracole run`` (plan §6).

Steps, in order: sync → index → match → lyrics → fetch → lacuerda → scan →
render → todo. Each step runs even if an earlier one failed, so the to-do page
is always rewritten.

- A step's provider is skipped while it is cooling down, and for the rest of
  the run once it blocks. A block records a cooldown (24 h, doubling) and sends
  one ntfy message; it is expected behaviour, not a failed run.
- An exhausted budget or a provider error ends that step for this run; neither
  is a failure, and neither ever marks a song "not found".
- Anything else is a bug: it's recorded, the remaining steps still run, and
  the run exits non-zero so systemd's OnFailure fires.
- An overrides.toml that can't be read stops the run before its first step
  (every step reads it); the to-do page is still rewritten, leading with why.
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
from typing import Any, Callable, Mapping

from caracole import db
from caracole.config import Config
from caracole.db import kv_get_json, kv_set_json
from caracole.health import get_state, is_cooling, record_block, record_error, record_ok
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
    sentence,
    spotify_auth,
    spotify_setup,
    step_error,
    summary_text,
    todo_count,
    unreadable_wanted,
)
from caracole.songs import ensure_current_keys

log = logging.getLogger(__name__)
PROVIDERS = ("ug", "lrclib", "lacuerda")
clock = time.monotonic  # what the run's duration is measured with; tests replace it


@dataclass
class Services:
    clients: Mapping[str, Any]
    spotify: Any | None
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


@dataclass
class StepContext:
    cfg: Config
    conn: sqlite3.Connection
    overrides: Overrides
    now: datetime
    run_id: str
    services: Services
    report: RunReport


@dataclass(frozen=True)
class Step:
    """One step of the run. ``run`` hands back a ``StepResult``, or a line of text, or nothing."""

    name: str
    run: Callable[[StepContext], StepResult | str | None]
    provider: str | None = None


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "?"


# --- the default steps ----------------------------------------------------------


def _counted(*counts: tuple[int, str]) -> list[str]:
    """The counts that aren't zero, the way a step's line shows them: "3 found"."""
    return [f"{n} {words}" for n, words in counts if n]


def _songs(n: int, what: str) -> tuple[int, str]:
    """A count of songs that reads well alone: (3, "songs matched")."""
    return n, f"{'song' if n == 1 else 'songs'} {what}"


def _sync(ctx: StepContext) -> StepResult:
    from caracole.sources import sync_sources

    before = (kv_get_json(ctx.conn, "source:spotify", default={}) or {}).get("state")
    r = sync_sources(ctx.conn, ctx.cfg, ctx.now, spotify=ctx.services.spotify)
    result = StepResult(title="Songs", status=r.summary())
    w, s = r.wanted, r.spotify
    new = w.new + (s.new if s is not None else 0)
    if new:  # a night with no new song needs no line
        spotify = [f"{s.seen} on Spotify"] if s is not None and s.seen else []
        result.done = [f"{w.seen} in wanted.txt", *spotify, f"{new} new"]
    if w.errors and not w.line_errors:  # the file itself couldn't be read
        result.actions.append(unreadable_wanted(w.errors))
    elif w.line_errors:
        result.actions.append(Action(f"fix the {plural(len(w.line_errors), 'line')} of wanted.txt caracole "
                                     "couldn't read", "The to-do page says what is wrong with each.", rank=40))
    if r.spotify_state == "auth_needed":
        action = spotify_auth(r.spotify_message)
        result.actions.append(action)
        if before != "auth_needed":
            ctx.services.notifier.send("caracole: Spotify needs you", sentence(action), priority="high",
                                       tags=["warning"])
    elif r.spotify_state == "setup_needed":
        result.actions.append(spotify_setup(r.spotify_message))
    elif r.spotify_state == "error":
        why = (r.spotify_message or "it failed").strip().rstrip(".")
        result.problems.append(Problem(f"Spotify couldn't be synced ({why}), so it will be tried again on the "
                                       "next run; wanted.txt was synced."))
    return result


def _index(ctx: StepContext) -> StepResult:
    from caracole.ug.index import index_count, mark_dirty_for_new, refresh_index

    if index_count(ctx.conn) == 0:
        return StepResult(title="Index refresh", actions=[BUILD_INDEX],
                          status="skipped: the index is empty; run `caracole index build` once")
    stats = refresh_index(ctx.conn, ctx.services.client("ug"), ctx.now)
    dirty = mark_dirty_for_new(ctx.conn, stats.new_tab_ids)
    new = len(stats.new_tab_ids)
    return StepResult(title="Index refresh",
                      done=_counted((new, "new tab" if new == 1 else "new tabs"), _songs(dirty, "to fetch again")),
                      status=f"{new} new tabs, {dirty} songs to refetch")


def _match(ctx: StepContext) -> StepResult:
    from caracole.match import match_all
    from caracole.ug.index import index_state

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
        done=_counted(_songs(matched, "matched"), _songs(changed.count("review"), "to review"),
                      _songs(changed.count("not_found"), "not on Ultimate Guitar")),
        status=f"{len(changed)} decisions changed",
    )


def _lyrics(ctx: StepContext) -> StepResult:
    from caracole.lyrics import fetch_pending_lyrics

    s = fetch_pending_lyrics(ctx.conn, ctx.services.client("lrclib"), ctx.cfg.library_dir, ctx.now)
    if s.errors:
        record_error(ctx.conn, "lrclib", ctx.now, f"{plural(s.errors, 'song')} failed this run")
    tail = " (budget spent)" if s.budget_exhausted else ""
    return StepResult(
        title="Lyrics",
        done=_counted((s.found, "found"), (s.missing, "missing"), (s.instrumental, "instrumental")),
        failures=[Failure.of(song, e) for song, e in s.failures],
        retry="the lyrics of {songs} will be tried again on the next run",
        spent=["lrclib"] if s.budget_exhausted else [],
        status=(f"{s.found} found, {s.missing} missing, {s.instrumental} instrumental, "
                f"{plural(s.errors, 'error')}{tail}"),
    )


def _fetch(ctx: StepContext) -> StepResult:
    from caracole.ug.fetch import FetchContext, fetch_songs, rescore_kept_sheets, songs_to_fetch

    # Sheets kept before their lyrics arrived are scored first (no requests), so a partial one
    # shows on the to-do page and the fetch and LaCuerda can tell it from a complete one.
    rescored = rescore_kept_sheets(ctx.conn, ctx.cfg.library_dir, ctx.cfg.rank)
    fctx = FetchContext(
        conn=ctx.conn, client=ctx.services.client("ug"), overrides=ctx.overrides, rank=ctx.cfg.rank,
        library_dir=ctx.cfg.library_dir, now=ctx.now,
    )
    s = fetch_songs(fctx, songs_to_fetch(ctx.conn, ctx.overrides, ctx.now))
    if s.songs_failed:
        record_error(ctx.conn, "ug", ctx.now, f"{plural(s.songs_failed, 'song')} failed this run")
    scored = f", {plural(rescored, 'kept sheet')} rescored" if rescored else ""
    tail = " (budget spent)" if s.budget_exhausted else ""
    sheets = f"{plural(s.sheets_done, 'sheet')} settled, " if s.sheets_done else ""
    return StepResult(
        title="Ultimate Guitar",
        done=_counted((s.sheets_done, "sheet settled" if s.sheets_done == 1 else "sheets settled"),
                      _songs(s.songs_done, "done"),
                      (rescored, "kept sheet rescored" if rescored == 1 else "kept sheets rescored")),
        failures=[Failure.of(song, e) for song, e in s.failures],
        retry="{songs} will be looked for on Ultimate Guitar again on the next run",
        spent=["ug"] if s.budget_exhausted else [],
        status=f"{sheets}{plural(s.songs_done, 'song')} done, {s.songs_failed} failed{scored}{tail}",
    )


def _lacuerda(ctx: StepContext) -> StepResult:
    from caracole.lacuerda_fetch import lacuerda_sheets

    s = lacuerda_sheets(ctx.conn, ctx.services.client("lacuerda"), ctx.cfg.library_dir, ctx.cfg.rank, ctx.now,
                        overrides=ctx.overrides)
    if s.errors:
        record_error(ctx.conn, "lacuerda", ctx.now, f"{plural(s.errors, 'song')} failed this run")
    tail = " (budget spent)" if s.budget_exhausted else ""
    return StepResult(
        title="LaCuerda",
        done=_counted((s.kept, "sheet kept" if s.kept == 1 else "sheets kept"), _songs(s.missing, "not there")),
        failures=[Failure.of(song, e) for song, e in s.failures],
        retry="{songs} will be looked for on LaCuerda again on the next run",
        spent=["lacuerda"] if s.budget_exhausted else [],
        status=(f"{s.tried} tried, {plural(s.kept, 'sheet')} kept, {s.missing} not on LaCuerda, "
                f"{plural(s.errors, 'error')}{tail}"),
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
        done=_counted((music.matched, "purchase linked" if music.matched == 1 else "purchases linked"),
                      (filed, "Guitar Pro file filed" if filed == 1 else "Guitar Pro files filed")),
        status=f"{music.matched} purchases linked, {filed} Guitar Pro files filed{links}",
    )
    if refused:
        result.problems.append(Problem(f"{plural(refused, 'symbolic link')} in _inbox, or in its place, "
                                       f"{'was' if refused == 1 else 'were'} left unread; the to-do page names "
                                       f"{'it' if refused == 1 else 'them'}."))
    return result


def _render(ctx: StepContext) -> StepResult:
    from caracole.render import render_all

    s = render_all(ctx.conn, ctx.cfg, ctx.overrides, now=ctx.now)
    tail = f"; {s.font_error}" if s.font_error else ""
    result = StepResult(title="PDFs", done=_counted((s.rendered, "rendered")),
                        status=f"{s.rendered} rendered, {s.failed} failed{tail}")
    if s.failed:
        them = "it" if s.failed == 1 else "them"
        result.problems.append(Problem(f"{plural(s.failed, 'song')} got no PDF: the to-do page names {them}, "
                                       "and the log says why."))
    if s.font_error:
        result.problems.append(Problem(s.font_error))
    return result


def _todo(ctx: StepContext) -> StepResult:
    from caracole.todo import write_pages

    ctx.report.requests = _requests(ctx.services)
    ctx.report.budgets = _budgets(ctx.services)
    _record_ok(ctx.conn, ctx.report, ctx.now)  # before the page, so its provider health shows this run
    kv_set_json(ctx.conn, "run:last", _report_json(ctx.report))
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
        Step("index", _index, provider="ug"),
        Step("match", _match),
        Step("lyrics", _lyrics, provider="lrclib"),
        Step("fetch", _fetch, provider="ug"),
        Step("lacuerda", _lacuerda, provider="lacuerda"),
        Step("scan", _scan),
        Step("render", _render),
        Step("todo", _todo),
    ]


# --- orchestration ---------------------------------------------------------------


def make_services(cfg: Config, conn: sqlite3.Connection, run_id: str) -> Services:
    """Real clients for a run: one polite client per provider, Spotify if configured.

    The clients are the commands' own (``commands._common.make_client``): each
    holds caracole's lock until it is closed, and its first request keeps the
    pause after the provider's last one, whichever caracole sent it.
    """
    from caracole.commands._common import make_client, transport_for

    clients: dict[str, Any] = {}
    try:
        for p in PROVIDERS:
            clients[p] = make_client(cfg, conn, p, run_id)
    except BaseException:  # Ctrl-C during a pause, say: the clients made let go of the lock
        for client in clients.values():
            client.close()
        raise
    spotify = None
    if cfg.spotify.enabled:
        try:
            from caracole.spotify import client_from_config

            spotify = client_from_config(cfg)
        except Exception as e:  # Spotify is optional; never let it stop the run: the sync says what to do
            log.info("Spotify can't be used this run: %s", e)
    notifier = Notifier(cfg.ntfy.url, cfg.ntfy.token, transport=transport_for("ntfy"))
    return Services(clients=clients, spotify=spotify, notifier=notifier)


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


def _answered(conn: sqlite3.Connection, run_id: str, provider: str, requests: int) -> bool:
    """Whether the provider answered at least one of this run's requests.

    Every request a PoliteClient sends is logged to ``events`` as answered
    (``ok``, ``not_modified``), an ``error`` or a ``blocked``; a client that
    logs nothing counts as answered.
    """
    failed = conn.execute(
        "SELECT COUNT(*) FROM events WHERE run = ? AND provider = ? AND decision IN ('error', 'blocked')",
        (run_id, provider),
    ).fetchone()[0]
    return requests > failed


def _record_ok(conn: sqlite3.Connection, report: RunReport, now: datetime) -> None:
    """A provider that answered this run without a block had a good run: clear its cooldown, note the time.

    A run whose every request failed (UG answering 502, say) is no success.
    """
    for p, n in report.requests.items():
        if n and p not in report.blocked and _answered(conn, report.run_id, p, n):
            record_ok(conn, p, now)


def _report_json(report: RunReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id, "started": report.started, "finished": report.finished,
        "steps": report.steps, "blocked": report.blocked, "errors": report.errors, "requests": report.requests,
        "budgets": report.budgets, "seconds": report.seconds,
    }


def run_pipeline(
    cfg: Config,
    *,
    conn: sqlite3.Connection | None = None,
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
    conn = conn or db.connect(cfg.db_path)
    # Before any step reads songs by key, as the sync reads wanted.txt's first-seen times.
    ensure_current_keys(conn)
    if services is not None:
        return _run(cfg, conn, services, steps, now, run_id, clock_given, started)
    services = make_services(cfg, conn, run_id)
    try:
        return _run(cfg, conn, services, steps, now, run_id, clock_given, started)
    finally:
        services.close()


def _skipped(conn: sqlite3.Connection, report: RunReport, step: Step, now: datetime) -> StepResult | None:
    """Why a step of a provider that blocked this run, or is cooling down, doesn't run, if it doesn't."""
    p = step.provider
    if p and p in report.blocked:  # the block's own line says it
        return StepResult(status=f"skipped: {p} blocked this run")
    if p and is_cooling(conn, p, now):
        until = get_state(conn, p).cooldown_until
        return StepResult(problems=[cooling(p, until)], status=f"skipped: {p} cooling down until {_fmt(until)}")
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
        result = _skipped(conn, report, step, now)
        report.record(step.name, result if result is not None else _run_step(ctx, step))
        log.info("%s: %s", step.name, report.steps[step.name])

    report.requests = _requests(services)
    report.budgets = _budgets(services)
    _record_ok(conn, report, now)
    report.finished = run_id if clock_given else _iso(datetime.now(UTC))
    report.seconds = clock() - started
    kv_set_json(conn, "run:last", _report_json(report))
    title = "caracole run" if report.ok else "caracole run failed"
    services.notifier.send(title, report.summary(), priority=None if report.ok else "high",
                           tags=() if report.ok else ("rotating_light",))
    return report
