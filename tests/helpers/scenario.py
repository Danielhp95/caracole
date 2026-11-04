"""Scenario records: one pass over a fixture library and a set of answers, recorded for the phone to replay
(docs/superpowers/specs/2026-11-03-conformance-corpus.md, "Scenario records"; Kotlin's ``core.testing.Scenarios``).

``record(conn, library_dir, *, fn, call, clients, answers, cache=None, now, case="", kw=None, run=None)`` runs
``call(made)``, where ``made`` maps each provider of ``clients`` to a real ``PoliteClient``:

- its policy the provider's default (``config.DEFAULT_PROVIDERS``) with the record's ``budget`` and ``delay``;
- its cache under a folder of its own, filled first from ``cache`` (``{provider: {"GET <url>": {"status",
  "fetched_at", "headers"?, "body"}}}``), as http.py writes one;
- its transport an ``httpx.MockTransport`` answering ``answers`` (``{"GET <url>": {"status", "headers"?, "body"}}``,
  keyed by the method and the full URL as httpx renders it): a request it doesn't answer fails the recording;
- its pauses recorded and skipped (``time.sleep`` never runs), its clocks fixed at ``now``, its events logged by
  ``EventLog`` under ``run`` (``lookup:<now>`` by default).

A body is bytes, a text, or a ``corpus.fixture_ref``: the record carries the reference, never the fixture's bytes, and
any other bytes as ``{"base64": …}``, a text as ``{"text": …}``.

The record (a dict, ready for ``corpus.jsonl``)::

    {"fn": fn, "case": case, "fixture": [dump_fixture records before], "kw": kw, "now": "<stamp>",
     "clients": {provider: {"budget": N, "delay": [low, high]}}, "cache": {...}, "answers": {...},
     "out": {"result": <plain(result)>, "requests": ["GET <url>", ...], "rows": {table: [row, ...]},
             "kv": {key: value text or null}, "library": {path: sha256 or null},
             "events": [[provider, url, status, decision], ...], "pauses": N}}

``rows`` holds only the tables the pass changed, each whole as ``dump_fixture`` reads it after; ``kv`` only the keys it
changed (null: deleted); ``library`` only the files it wrote or deleted; ``pauses`` how many pauses the clients took
(their lengths are random, and never compared). A pass that raises records ``raises`` (``{"type", "message"}``) and
what it did up to then under ``after``, in place of ``out``.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from caracole import config
from caracole.health import EventLog
from caracole.http import PoliteClient
from helpers.corpus import dump_fixture, fixture_bytes, plain

STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _body(body: Any) -> tuple[bytes, Any]:
    """A body's bytes, and how the record carries it."""
    if isinstance(body, Mapping) and "fixture" in body:
        return fixture_bytes(body), dict(body)
    if isinstance(body, Mapping) and "text" in body:
        return body["text"].encode("utf-8"), dict(body)
    if isinstance(body, Mapping) and "base64" in body:
        return base64.b64decode(body["base64"]), dict(body)
    if isinstance(body, str):
        return body.encode("utf-8"), {"text": body}
    if isinstance(body, bytes):
        return body, {"base64": base64.b64encode(body).decode("ascii")}
    raise TypeError(f"a body is bytes, a text or a fixture reference, not {type(body).__name__}")


def _answer(answer: Mapping[str, Any]) -> tuple[httpx.Response, dict[str, Any]]:
    data, carried = _body(answer.get("body", b""))
    headers = [list(h) for h in answer.get("headers", [])]
    return httpx.Response(answer["status"], headers=[tuple(h) for h in headers], content=data), {
        "status": answer["status"], "headers": headers, "body": carried}


def _seed_cache(cache_dir: Path, provider: str, entries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """``entries`` written into the provider's cache as http.py writes one (gzip'd body, JSON meta, by the URL's
    SHA-256); what the record carries of them."""
    carried = {}
    for request, entry in entries.items():
        method, url = request.split(" ", 1)
        if method != "GET":
            raise ValueError(f"only GET answers are cached: {request}")
        data, body = _body(entry.get("body", b""))
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        folder = cache_dir / "http" / provider / key[:2]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{key}.body").write_bytes(gzip.compress(data, mtime=0))
        headers = dict(entry.get("headers", {}))
        meta = {"url": url, "status": entry["status"], "headers": headers, "fetched_at": entry["fetched_at"]}
        (folder / f"{key}.json").write_bytes(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        carried[request] = {"status": entry["status"], "fetched_at": entry["fetched_at"], "headers": headers,
                            "body": body}
    return carried


def _tables(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if "table" in r:
            out.setdefault(r["table"], []).append(r["row"])
    return out


def _kv(records: list[dict[str, Any]]) -> dict[str, str]:
    return {r["kv"]: r["value"] for r in records if "kv" in r}


def _files(library_dir: Path | None) -> dict[str, str]:
    if library_dir is None or not Path(library_dir).is_dir():
        return {}
    return {p.relative_to(library_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(library_dir).rglob("*")) if p.is_file() and not p.is_symlink()}


def record(conn, library_dir: Path | None, *, fn: str, call: Callable[[dict[str, PoliteClient]], Any],
           clients: Mapping[str, Mapping[str, Any]], answers: Mapping[str, Mapping[str, Any]],
           cache: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None, now: datetime,
           case: str = "", kw: Mapping[str, Any] | None = None, run: str | None = None,
           cache_dir: Path | None = None) -> dict[str, Any]:
    """One scenario record (the module's docstring): ``call`` run over ``clients`` answering ``answers``."""
    now = now.astimezone(UTC)
    stamp = now.strftime(STAMP)
    cache_dir = Path(cache_dir) if cache_dir is not None else Path(library_dir or ".").parent / "scenario-cache"
    before = dump_fixture(conn, library_dir)
    carried_cache = {provider: _seed_cache(cache_dir, provider, entries) for provider, entries in (cache or {}).items()}

    responses: dict[str, tuple[httpx.Response, dict[str, Any]]] = {r: _answer(a) for r, a in answers.items()}
    requests: list[str] = []
    unanswered: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        said = f"{request.method} {request.url}"
        requests.append(said)
        if said not in responses:
            unanswered.append(said)
            return httpx.Response(599, content=b"unanswered by the scenario")
        return responses[said][0]

    pauses: list[float] = []
    log = EventLog(conn, run or f"lookup:{stamp}", clock=lambda: now)
    made: dict[str, PoliteClient] = {}
    for provider, policy in clients.items():
        base = config.DEFAULT_PROVIDERS.get(provider) or config.ProviderPolicy(budget=0, delay=(0.0, 0.0))
        made[provider] = PoliteClient(
            provider, replace(base, budget=policy["budget"], delay=tuple(policy["delay"])), cache_dir,
            user_agent=config.DEFAULT_USER_AGENT, transport=httpx.MockTransport(handler),
            sleep=pauses.append, on_event=log, clock=lambda: 0.0, wall_clock=lambda: now)
    events_before = conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
    files_before = _files(library_dir)
    result: Any = None
    raised: BaseException | None = None
    try:
        result = call(made)
    except Exception as e:  # recorded: a pass that raises is a scenario too
        raised = e
    finally:
        for client in made.values():
            client.close()
    if unanswered:
        raise AssertionError(f"the scenario answers none of: {', '.join(unanswered)}")

    after = dump_fixture(conn, library_dir)
    old_rows, new_rows = _tables(before), _tables(after)
    rows = {t: new_rows.get(t, []) for t in sorted(set(old_rows) | set(new_rows))
            if t != "events" and old_rows.get(t, []) != new_rows.get(t, [])}
    old_kv, new_kv = _kv(before), _kv(after)
    kv = {k: new_kv.get(k) for k in sorted(set(old_kv) | set(new_kv)) if old_kv.get(k) != new_kv.get(k)}
    files_after = _files(library_dir)
    library = {p: files_after.get(p) for p in sorted(set(files_before) | set(files_after))
               if files_before.get(p) != files_after.get(p)}
    events = [list(r) for r in conn.execute(
        "SELECT provider, url, status, decision FROM events WHERE id > ? ORDER BY id", (events_before,))]
    done = {"requests": requests, "rows": rows, "kv": kv, "library": library, "events": events,
            "pauses": len(pauses)}
    out: dict[str, Any] = {
        "fn": fn, "case": case, "fixture": before, "kw": plain(dict(kw or {})), "now": stamp,
        "clients": {p: {"budget": c["budget"], "delay": list(c["delay"])} for p, c in clients.items()},
        "cache": carried_cache, "answers": {r: carried for r, (_, carried) in responses.items()},
    }
    if raised is not None:
        out["raises"] = {"type": type(raised).__name__, "message": str(raised)}
        out["after"] = done
    else:
        out["out"] = {"result": plain(result), **done}
    return out
