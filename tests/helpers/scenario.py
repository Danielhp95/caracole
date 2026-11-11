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

**Whole lookups** (``record_lookup``, lane lookup-scenarios'): a pass that makes its own clients, as get.py's
``_Lookup`` does through ``_common.make_client``, is recorded over a caracole's ``Config`` rather than given clients.
``record_lookup(cfg, *, fn, call, answers, now, case="", kw=None, cache=None, settle=None, leaves_out=LEAVES_OUT)``
runs ``call()`` with:

- the transport hook, ``_common.transport_for``, answering every provider from ``answers`` (a mapping as above, or a
  function of ``"GET <url>"`` that gives an answer or None): a request it doesn't answer fails the recording, and the
  record carries the answers asked for alone;
- ``_common.sleep`` recorded and skipped (each client's pauses and the pause after a provider's last request alike),
  and every clock a lookup reads fixed at ``now``: ``_common``'s ``time.time()`` (kv ``http:last_request:``) and
  ``datetime.now`` (the hour's and the day's requests), its ``EventLog``'s, each client's (monotonic at 0, its wall
  clock at ``now``), and songs.py's and match.py's ``utc_now_iso``;
- what a caracole with no ChordPro, no PDF, no index.html and no songbook makes stood still (render.py's
  ``render_all``, todo.py's ``write_pages`` and songbook.py's ``render_songbooks`` answer an empty pass), so that the
  pass writes no PDF, page or ``render:*`` record, as the phone's ``SongPages.NONE`` and ``SongbookPages.NONE``
  make none;
- ``cache`` seeded into ``cfg.cache_dir`` first, as above.

What the phone writes and Python doesn't is recorded as ``noted``: each index page a lookup's store wrote, which the
phone notes for its next push to the computer (core.index.Reads, kv ``phone:read:<site>:<page>`` = the store's stamp):
an Ultimate Guitar artist page a store kept tabs of (``ug.artist_tabs.store``, at the store's time or the read's where
that is later, never moved back), a LaCuerda page its index stored (``lacuerda_index._replace``: an artist's
``"<slug>/"``, at the store's time) and its search's answer with rows (``busca.php``), a harptabs.com artist page
stored (``harptabs_index.store_artist_page``, at its ``now``).

``settle(conn)``, when given, runs once the pass is over, before what it did is read (a generator's own bookkeeping,
such as a stamp SQLite's clock wrote). ``leaves_out`` is what the phone never writes, left out of the fixture and of
what the pass did alike: ``{"kv": [prefix, ...], "files": [file name, ...]}`` (``LEAVES_OUT``: wanted.txt's
``wanted:first_seen:``, as the phone adds a song through ``LibraryStore.add`` with no wanted.txt, and every
``info.json``, milestone 5's viewer's). The record::

    {"fn": fn, "case": case, "fixture": [...], "kw": kw, "now": "<stamp>", "cache": {...}, "answers": {...},
     "leaves_out": leaves_out,
     "out": {"result": <plain(result)>, "requests": [...], "rows": {...}, "kv": {...}, "library": {...},
             "events": [[run, provider, url, status, decision], ...], "pauses": N, "noted": {kv key: stamp}}}

its ``events`` naming each request's run too (a lookup's own, ``lookup:<now>``).
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


# --- whole lookups ----------------------------------------------------------------------------------------------

# What the phone never writes: wanted.txt's first-seen times (the phone adds a song through LibraryStore.add, with no
# wanted.txt) and info.json (milestone 5's viewer's).
LEAVES_OUT: dict[str, list[str]] = {"kv": ["wanted:first_seen:"], "files": ["info.json"]}


class _Clock:
    """The ``time`` module, its ``time()`` at a fixed instant."""

    def __init__(self, epoch: float):
        self._epoch = epoch

    def time(self) -> float:
        return self._epoch

    def __getattr__(self, name: str) -> Any:
        import time

        return getattr(time, name)


def _left(records: list[dict[str, Any]], leaves_out: Mapping[str, Any]) -> list[dict[str, Any]]:
    prefixes = tuple(leaves_out.get("kv", ()))
    names = set(leaves_out.get("files", ()))
    return [r for r in records
            if not ("kv" in r and prefixes and r["kv"].startswith(prefixes))
            and not ("file" in r and r["file"].rsplit("/", 1)[-1] in names)]


READ = "phone:read:"  # core.index.Reads.READ


def _noting(noted: dict[str, str], stamp: str) -> list[tuple[Any, str, Any]]:
    """The stores a lookup's index pages go through, each wrapped to note its page as the phone does (the module's
    docstring, ``noted``): ``(module, name, wrapper)`` for ``mock.patch.object``."""
    from caracole import harptabs_index, lacuerda_index
    from caracole.ug import artist_tabs

    real_ug, real_replace = artist_tabs.store, lacuerda_index._replace
    real_search, real_harp = lacuerda_index.store_search, harptabs_index.store_artist_page

    def ug_store(conn, page, name, tabs, *, read_at):
        kept = real_ug(conn, page, name, tabs, read_at=read_at)
        at, key = max(read_at, stamp), f"{READ}ug:{page}"
        if kept and at > noted.get(key, ""):
            noted[key] = at
        return kept

    def replace(conn, page, rows):
        real_replace(conn, page, rows)
        noted[f"{READ}lacuerda:{page}"] = stamp

    def store_search(conn, answer):
        stored = real_search(conn, answer)
        if answer.songs or answer.artists:
            noted[f"{READ}lacuerda:{lacuerda_index.SEARCH_PAGE}"] = stamp
        return stored

    def harp_store(conn, path, page, now):
        real_harp(conn, path, page, now)
        noted[f"{READ}harptabs:{path}"] = now.astimezone(UTC).strftime(STAMP)

    return [(artist_tabs, "store", ug_store), (lacuerda_index, "_replace", replace),
            (lacuerda_index, "store_search", store_search), (harptabs_index, "store_artist_page", harp_store)]


def _empty_pass(kind: str) -> Callable[..., Any]:
    """render_all's, write_pages' or render_songbooks' stand-in: a pass that made nothing."""
    from caracole.render import RenderStats
    from caracole.songbook import SongbookStats

    made = {"render": RenderStats, "songbooks": SongbookStats}.get(kind)
    return lambda *_a, **_k: made() if made is not None else None


def record_lookup(cfg, *, fn: str, call: Callable[[], Any],
                  answers: Mapping[str, Mapping[str, Any]] | Callable[[str], Mapping[str, Any] | None],
                  now: datetime, case: str = "", kw: Mapping[str, Any] | None = None,
                  cache: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
                  settle: Callable[[Any], None] | None = None,
                  leaves_out: Mapping[str, list[str]] = LEAVES_OUT) -> dict[str, Any]:
    """One whole-lookup record (the module's docstring): ``call()`` run over ``cfg`` answering ``answers``."""
    from contextlib import ExitStack, closing
    from functools import partial
    from unittest import mock

    from caracole import db
    from caracole.commands import _common

    now = now.astimezone(UTC)
    stamp = now.strftime(STAMP)
    asked = answers if callable(answers) else (lambda said: answers.get(said))
    carried_answers: dict[str, dict[str, Any]] = {}
    requests: list[str] = []
    unanswered: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        said = f"{request.method} {request.url}"
        requests.append(said)
        answer = asked(said)
        if answer is None:
            unanswered.append(said)
            return httpx.Response(599, content=b"unanswered by the scenario")
        response, carried = _answer(answer)
        carried_answers[said] = carried
        return response

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    real_client = _common._locked_client()

    class FrozenClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any):
            kwargs.setdefault("clock", lambda: 0.0)
            kwargs.setdefault("wall_clock", lambda: now)
            super().__init__(*args, **kwargs)

    pauses: list[float] = []
    noted: dict[str, str] = {}
    with closing(db.connect(cfg.db_path)) as conn:
        before = _left(dump_fixture(conn, cfg.library_dir), leaves_out)
        carried_cache = {p: _seed_cache(cfg.cache_dir, p, entries) for p, entries in (cache or {}).items()}
        events_before = conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
        files_before = _files(cfg.library_dir)
        result: Any = None
        raised: BaseException | None = None
        with ExitStack() as stack:
            for target, value in (
                ("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(handler)),
                ("caracole.commands._common.sleep", pauses.append),
                ("caracole.commands._common.time", _Clock(now.timestamp())),
                ("caracole.commands._common.datetime", Frozen),
                ("caracole.commands._common.EventLog", partial(EventLog, clock=lambda: now)),
                ("caracole.commands._common._locked_client", lambda: FrozenClient),
                ("caracole.songs.utc_now_iso", lambda: stamp),
                ("caracole.match.utc_now_iso", lambda: stamp),
                ("caracole.render.render_all", _empty_pass("render")),
                ("caracole.todo.write_pages", _empty_pass("pages")),
                ("caracole.songbook.render_songbooks", _empty_pass("songbooks")),
            ):
                stack.enter_context(mock.patch(target, value))
            for module, name, wrapper in _noting(noted, stamp):
                stack.enter_context(mock.patch.object(module, name, wrapper))
            try:
                result = call()
            except Exception as e:  # recorded: a pass that raises is a scenario too
                raised = e
        if unanswered:
            raise AssertionError(f"the scenario answers none of: {', '.join(unanswered)}")
        if settle is not None:
            settle(conn)
        after = _left(dump_fixture(conn, cfg.library_dir), leaves_out)
        events = [list(r) for r in conn.execute(
            "SELECT run, provider, url, status, decision FROM events WHERE id > ? ORDER BY id", (events_before,))]
    old_rows, new_rows = _tables(before), _tables(after)
    rows = {t: new_rows.get(t, []) for t in sorted(set(old_rows) | set(new_rows))
            if t != "events" and old_rows.get(t, []) != new_rows.get(t, [])}
    old_kv, new_kv = _kv(before), _kv(after)
    kv = {k: new_kv.get(k) for k in sorted(set(old_kv) | set(new_kv)) if old_kv.get(k) != new_kv.get(k)}
    names = set(leaves_out.get("files", ()))
    files_after = _files(cfg.library_dir)
    library = {p: files_after.get(p) for p in sorted(set(files_before) | set(files_after))
               if files_before.get(p) != files_after.get(p) and p.rsplit("/", 1)[-1] not in names}
    assert not any(k.startswith(READ) for k in kv), "Python notes no page for a push"
    done = {"requests": requests, "rows": rows, "kv": kv, "library": library, "events": events,
            "pauses": len(pauses), "noted": dict(sorted(noted.items()))}
    out: dict[str, Any] = {
        "fn": fn, "case": case, "fixture": before, "kw": plain(dict(kw or {})), "now": stamp,
        "cache": carried_cache, "answers": carried_answers, "leaves_out": {k: list(v) for k, v in leaves_out.items()},
    }
    if raised is not None:
        out["raises"] = {"type": type(raised).__name__, "message": str(raised)}
        out["after"] = done
    else:
        out["out"] = {"result": plain(result), **done}
    return out
