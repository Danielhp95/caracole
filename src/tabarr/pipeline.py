"""The nightly ``tabarr run`` (plan §6).

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
"""

from __future__ import annotations

import logging
import sqlite3
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from tabarr import db
from tabarr.config import Config
from tabarr.db import kv_get_json, kv_set_json
from tabarr.health import get_state, is_cooling, record_block, record_error, record_ok
from tabarr.http import BudgetExhausted, Client, ProviderBlocked, ProviderError
from tabarr.notify import Notifier
from tabarr.overrides import Overrides, OverridesError, load_overrides

log = logging.getLogger(__name__)
PROVIDERS = ("ug", "lrclib", "lacuerda")


@dataclass
class Services:
    clients: Mapping[str, Any]
    spotify: Any | None
    notifier: Notifier

    def client(self, provider: str) -> Client:
        return self.clients[provider]


@dataclass
class RunReport:
    run_id: str
    started: str
    finished: str | None = None
    steps: dict[str, str] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requests: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [f"{name}: {result}" for name, result in self.steps.items()]
        if self.requests:
            lines.append("requests: " + ", ".join(f"{p} {n}" for p, n in self.requests.items()))
        return "\n".join(lines)


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
    name: str
    run: Callable[[StepContext], str | None]
    provider: str | None = None


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "?"


# --- the default steps ----------------------------------------------------------


def _sync(ctx: StepContext) -> str:
    from tabarr.sources import sync_sources

    before = (kv_get_json(ctx.conn, "source:spotify", default={}) or {}).get("state")
    r = sync_sources(ctx.conn, ctx.cfg, ctx.now, spotify=ctx.services.spotify)
    if r.spotify_state == "auth_needed" and before != "auth_needed":
        ctx.services.notifier.send(
            "tabarr: Spotify needs you",
            f"{r.spotify_message or 'Spotify authorization failed.'} Run `tabarr auth spotify` "
            "(wanted.txt keeps working meanwhile).",
            priority="high", tags=["warning"],
        )
    return r.summary()


def _index(ctx: StepContext) -> str:
    from tabarr.ug.index import index_count, mark_dirty_for_new, refresh_index

    if index_count(ctx.conn) == 0:
        return "skipped: the index is empty; run `tabarr index build` once"
    stats = refresh_index(ctx.conn, ctx.services.client("ug"), ctx.now)
    dirty = mark_dirty_for_new(ctx.conn, stats.new_tab_ids)
    return f"{len(stats.new_tab_ids)} new tabs, {dirty} songs to refetch"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _match(ctx: StepContext) -> str:
    from tabarr.match import match_all
    from tabarr.ug.index import index_state

    state = index_state(ctx.conn)
    if state == "empty":
        # Matching against an empty index would mark every song not found (and put it on the
        # buy list); errors are not misses, and a missing index is not evidence of absence.
        return "skipped: the index is empty; run `tabarr index build` once"
    if state == "partial":
        # Nor is an index a build left half-done: the songs in the sitemaps it didn't read would
        # be marked not found. Stored decisions stay; the index step's refresh reads the rest.
        return "skipped: the index is incomplete; the next refresh, or `tabarr index build`, reads the rest"
    changes = match_all(ctx.conn, ctx.overrides, ctx.cfg.match)
    changed = [c for c in changes if c.old != c.new.decision]
    return f"{len(changed)} decisions changed"


def _lyrics(ctx: StepContext) -> str:
    from tabarr.lyrics import fetch_pending_lyrics

    s = fetch_pending_lyrics(ctx.conn, ctx.services.client("lrclib"), ctx.cfg.library_dir, ctx.now)
    if s.errors:
        record_error(ctx.conn, "lrclib", ctx.now, f"{_plural(s.errors, 'song')} failed this run")
    tail = " (budget spent)" if s.budget_exhausted else ""
    return f"{s.found} found, {s.missing} missing, {s.instrumental} instrumental, {_plural(s.errors, 'error')}{tail}"


def _fetch(ctx: StepContext) -> str:
    from tabarr.ug.fetch import FetchContext, fetch_songs, rescore_kept_sheets, songs_to_fetch

    # Sheets kept before their lyrics arrived are scored first (no requests), so a partial one
    # shows on the to-do page and the fetch and LaCuerda can tell it from a complete one.
    rescored = rescore_kept_sheets(ctx.conn, ctx.cfg.library_dir, ctx.cfg.rank)
    fctx = FetchContext(
        conn=ctx.conn, client=ctx.services.client("ug"), overrides=ctx.overrides, rank=ctx.cfg.rank,
        library_dir=ctx.cfg.library_dir, now=ctx.now,
    )
    s = fetch_songs(fctx, songs_to_fetch(ctx.conn, ctx.overrides, ctx.now))
    if s.songs_failed:
        record_error(ctx.conn, "ug", ctx.now, f"{_plural(s.songs_failed, 'song')} failed this run")
    scored = f", {_plural(rescored, 'kept sheet')} rescored" if rescored else ""
    tail = " (budget spent)" if s.budget_exhausted else ""
    sheets = f"{_plural(s.sheets_done, 'sheet')} settled, " if s.sheets_done else ""
    return f"{sheets}{_plural(s.songs_done, 'song')} done, {s.songs_failed} failed{scored}{tail}"


def _lacuerda(ctx: StepContext) -> str:
    from tabarr.lacuerda_fetch import lacuerda_sheets

    s = lacuerda_sheets(ctx.conn, ctx.services.client("lacuerda"), ctx.cfg.library_dir, ctx.cfg.rank, ctx.now,
                        overrides=ctx.overrides)
    if s.errors:
        record_error(ctx.conn, "lacuerda", ctx.now, f"{_plural(s.errors, 'song')} failed this run")
    tail = " (budget spent)" if s.budget_exhausted else ""
    return (f"{s.tried} tried, {_plural(s.kept, 'sheet')} kept, {s.missing} not on LaCuerda, "
            f"{_plural(s.errors, 'error')}{tail}")


def _scan(ctx: StepContext) -> str:
    from tabarr.inbox import file_inbox
    from tabarr.music import scan_music

    music = scan_music(ctx.conn, ctx.cfg.music_dir)
    inbox = file_inbox(ctx.conn, ctx.cfg.library_dir)
    return f"{music.matched} purchases linked, {len(inbox.filed)} Guitar Pro files filed"


def _render(ctx: StepContext) -> str:
    from tabarr.render import render_all

    s = render_all(ctx.conn, ctx.cfg, ctx.overrides, now=ctx.now)
    tail = f"; {s.font_error}" if s.font_error else ""
    return f"{s.rendered} rendered, {s.failed} failed{tail}"


def _todo(ctx: StepContext) -> str:
    from tabarr.todo import write_pages

    ctx.report.requests = _requests(ctx.services)
    _record_ok(ctx.conn, ctx.report, ctx.now)  # before the page, so its provider health shows this run
    kv_set_json(ctx.conn, "run:last", _report_json(ctx.report))
    write_pages(ctx.conn, ctx.cfg, ctx.overrides, ctx.now)
    return "ok"


def _todo_for_broken_overrides(cfg: Config, conn: sqlite3.Connection, now: datetime, error: str,
                               report: RunReport) -> None:
    """No step can run, but the page you read still says why: it leads with the error.

    index.html is left as it was: built without your overrides it would lose your
    transpositions and ignored songs.
    """
    from tabarr.todo import build_todo, write_todo

    try:
        write_todo(cfg.library_dir, build_todo(conn, cfg, Overrides(), now, overrides_error=error))
    except Exception as e:  # a bug, or a library folder that can't be written; the run fails anyway
        log.error("the to-do page could not be written:\n%s", traceback.format_exc())
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
    """Real clients for a run: one polite client per provider, Spotify if configured."""
    from tabarr.health import EventLog
    from tabarr.http import PoliteClient

    clients = {
        p: PoliteClient(p, cfg.provider(p), cfg.cache_dir, user_agent=cfg.user_agent, on_event=EventLog(conn, run_id))
        for p in PROVIDERS
    }
    spotify = None
    if cfg.spotify.enabled:
        try:
            from tabarr.spotify import client_from_config

            spotify = client_from_config(cfg)
        except Exception as e:  # Spotify is optional; never let it stop the run
            log.warning("Spotify unavailable: %s", e)
    return Services(clients=clients, spotify=spotify, notifier=Notifier(cfg.ntfy.url, cfg.ntfy.token))


def _requests(services: Services) -> dict[str, int]:
    return {p: int(getattr(c, "requests_made", 0)) for p, c in services.clients.items()}


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
    }


def run_pipeline(
    cfg: Config,
    *,
    conn: sqlite3.Connection | None = None,
    services: Services | None = None,
    steps: list[Step] | None = None,
    now: datetime | None = None,
) -> RunReport:
    clock_given = now is not None
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    run_id = _iso(now)
    conn = conn or db.connect(cfg.db_path)
    services = services or make_services(cfg, conn, run_id)
    report = RunReport(run_id=run_id, started=run_id)
    try:
        overrides = load_overrides(cfg.overrides_file)
    except OverridesError as e:
        report.errors.append(f"overrides.toml: {e}")
        report.steps["overrides"] = f"failed: {e}"
        _todo_for_broken_overrides(cfg, conn, now, str(e), report)
        services.notifier.send("tabarr run failed", f"overrides.toml could not be read: {e}", priority="high",
                               tags=["rotating_light"])
        return report
    ctx = StepContext(cfg=cfg, conn=conn, overrides=overrides, now=now, run_id=run_id, services=services,
                      report=report)

    for step in steps if steps is not None else default_steps():
        p = step.provider
        if p and p in report.blocked:
            report.steps[step.name] = f"skipped: {p} blocked this run"
            continue
        if p and is_cooling(conn, p, now):
            report.steps[step.name] = f"skipped: {p} cooling down until {_fmt(get_state(conn, p).cooldown_until)}"
            continue
        try:
            report.steps[step.name] = step.run(ctx) or "ok"
        except ProviderBlocked as e:
            state = record_block(conn, e.provider, now, str(e))
            report.blocked.append(e.provider)
            report.steps[step.name] = f"blocked: {e}"
            services.notifier.send(
                f"tabarr: {e.provider} blocked",
                f"{e}\nNo more requests to {e.provider} until {_fmt(state.cooldown_until)} "
                f"(block #{state.strikes}). Nothing was marked not found.",
                priority="high", tags=["warning"],
            )
        except BudgetExhausted as e:
            report.steps[step.name] = f"budget spent ({e.provider})"
        except ProviderError as e:
            record_error(conn, e.provider, now, str(e))
            report.steps[step.name] = f"error: {e}"
        except Exception as e:  # a bug: record it, keep going, fail the run at the end
            log.error("step %s failed:\n%s", step.name, traceback.format_exc())
            report.errors.append(f"{step.name}: {type(e).__name__}: {e}")
            report.steps[step.name] = f"failed: {type(e).__name__}: {e}"

    report.requests = _requests(services)
    _record_ok(conn, report, now)
    report.finished = run_id if clock_given else _iso(datetime.now(UTC))
    kv_set_json(conn, "run:last", _report_json(report))
    title = "tabarr run" if report.ok else "tabarr run failed"
    services.notifier.send(title, report.summary(), priority=None if report.ok else "high",
                           tags=() if report.ok else ("rotating_light",))
    return report
