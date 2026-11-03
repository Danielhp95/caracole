"""caracole serve's Sync tab (library_assets/sync.js): this library and another caracole's, compared unit by unit
(peer_sync.py), and synced as the owner chose.

    GET  /api/sync        this caracole's id and its library's name, the address it synced with last, and each
                          caracole it synced with before (kv ``sync:peer:<id>``, which ``caracole peer sync`` keeps)
    POST /sync/compare    this library and the one at ``address`` compared, as ``caracole peer diff`` compares them:
                          every unit the two hold differently, with what the sync proposes for it, kept 10 minutes
                          under an id of its own (``comparison``)
    POST /sync/apply      a comparison kept (``comparison``), synced with the owner's choices (``choices``: a line a
                          unit, ``<here|there|skip>\\t<unit id>``; ``prefer``: here, there, or "" for none):
                          ``caracole peer sync --push --compared HASH --choose=…`` queued, its view the answer

The comparison asks the other caracole for its state, one request (``GET /api/peer/state``), on the request's thread,
as ``caracole peer diff`` does from a terminal: no lock, nothing written. Only the differences and the choices travel
between the page and the server, never a unit's document: the sync's command asks the other side for each unit it
takes (``GET /api/peer/unit``) and pushes there each it gives (``POST /peer/push``), as the phone does, so the other
side needn't reach this one. Sync compares afresh first and refuses (409) a comparison the two no longer agree with,
as the command does again (``--compared``, ``peer_sync.compared_hash``) once it runs; a conflict that has neither a
choice nor ``prefer`` is refused too. The job is no song's (kind ``sync``, under ``sync:<address>``): the Sync tab
follows it, its stages, and once over what it took, gave and left (jobs_routes.py ``peer_outcome``). caracole serve
writes no file for it; ``caracole peer sync`` keeps what the two agree on and the peer's address and name.

The phone answers the same three routes with the same shapes (docs/superpowers/plans/2026-11-03-android-port-m1-m3.md
§5.3; tests/conformance/vectors/web/sync_routes.jsonl).
"""

from __future__ import annotations

import secrets
import threading
import time
import weakref
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from caracole.web.app import Response, Route, WebApp, json_response
from caracole.web.pages import Refused

SYNCING = "sync:"  # a sync's job key: the address it syncs with after it
KEPT_FOR = 600.0  # seconds a comparison is kept for its Sync
KEPT = 20  # comparisons kept at most, the newest
SIDES = ("here", "there", "skip")
PREFER = ("", "here", "there")
STALE = ("The two changed since that comparison: compare them again, and choose again.")
GONE = ("That comparison is more than 10 minutes old, or caracole serve has restarted since: compare the two "
        "again.")

ROUTES = (
    Route("GET", "/api/sync", lambda app, asked: sync_state(app)),
    Route("POST", "/sync/compare", lambda app, asked, form: compare(app, form)),
    Route("POST", "/sync/apply", lambda app, asked, form: apply(app, form), limit=1024 * 1024),
)


def transport():
    """The HTTP transport a comparison asks the other caracole with: httpx's own (None). Tests replace it."""
    return None


@dataclass(frozen=True)
class Compared:
    """A comparison kept for its Sync: the other side's address and name, what was found (``hash``,
    ``peer_sync.compared_hash``), each difference's proposal by its unit, and when (``time.monotonic``)."""

    address: str
    name: str
    hash: str
    proposals: dict[str, str]
    at: float


# Each server's comparisons, by their ids, oldest first.
_kept: weakref.WeakKeyDictionary[WebApp, OrderedDict[str, Compared]] = weakref.WeakKeyDictionary()
_kept_lock = threading.Lock()


def _keep(app: WebApp, compared: Compared) -> str:
    made = secrets.token_hex(8)
    with _kept_lock:
        kept = _kept.setdefault(app, OrderedDict())
        _sweep(kept)
        kept[made] = compared
        while len(kept) > KEPT:
            kept.popitem(last=False)
    return made


def _sweep(kept: OrderedDict[str, Compared]) -> None:
    now = time.monotonic()
    for made in [k for k, c in kept.items() if now - c.at > KEPT_FOR]:
        del kept[made]


def _kept_one(app: WebApp, made: str) -> Compared | None:
    with _kept_lock:
        kept = _kept.get(app)
        if kept is None:
            return None
        _sweep(kept)
        return kept.get(made)


def _forget(app: WebApp, made: str) -> None:
    with _kept_lock:
        kept = _kept.get(app)
        if kept is not None:
            kept.pop(made, None)


def sync_state(app: WebApp) -> Response:
    """``GET /api/sync``: this caracole's id (``server``, None before it has one) and its library's name, and each
    caracole it synced with, newest first (``peers``: its address, id, name and when, from kv ``sync:peer:<id>``),
    the newest's address as ``address``, for the tab's field."""
    from caracole import peer_sync as sync

    with app.db() as conn:
        server = sync.own_id(conn)
        peers = peers_of(conn)
    return json_response(200, {"server": server, "name": app.cfg.library_name,
                               "address": peers[0]["address"] if peers else None, "peers": peers})


def peers_of(conn) -> list[dict[str, Any]]:
    """Each caracole this one synced with (kv ``sync:peer:<id>``: its address, name and when), newest first, then by
    id; a record that can't be read left out."""
    from caracole.db import kv_get_json
    from caracole.peer_push import PEER_KEY

    found = []
    for (key,) in conn.execute("SELECT key FROM kv WHERE substr(key, 1, ?) = ? ORDER BY key",
                               (len(PEER_KEY), PEER_KEY)):
        try:
            record = kv_get_json(conn, key)
        except ValueError:
            continue
        if not (isinstance(record, dict) and isinstance(record.get("address"), str) and record["address"]):
            continue
        name, at = record.get("name"), record.get("synced_at")
        found.append({"address": record["address"], "server": key[len(PEER_KEY):],
                      "name": name if isinstance(name, str) else "", "synced_at": at if isinstance(at, str) else None})
    found.sort(key=lambda p: p["server"])
    found.sort(key=lambda p: p["synced_at"] or "", reverse=True)
    return found


def _compared(app: WebApp, address: str):
    """The other caracole's state and the comparison, as ``caracole peer diff`` makes it: (its state, the differences,
    when the two last agreed, None if never). Refused when it can't be asked, is this very caracole, or this library
    can't be read."""
    from caracole import peer_sync as sync
    from caracole.web.peer_routes import _library

    overrides, books = _library(app)
    with app.db() as conn:
        me = sync.own_id(conn)
    try:
        with sync.Peer(address, transport=transport()) as peer:
            state = peer.state(me)
    except sync.PeerError as e:
        raise Refused(502, "Not reached", str(e)) from None
    if me is not None and me == state.server:
        raise Refused(409, "The same caracole", f"The caracole at {address} is this one (the same id, {me}): its "
                                                "database is a copy of this one's. Give one of them another: "
                                                "caracole peer new-id.")
    with app.db() as conn:
        mine = sync.library_state(conn, overrides, books)
        ours = sync.base_of(conn, state.server) if state.server else None
    found = sync.compare(mine, state.units, sync.merged_base(ours, state.base))
    agreed = [at for base in (ours, state.base) if base for _, at in base.values()]
    return state, found, max(agreed) if agreed else None


def compare(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /sync/compare``: this library and the one at ``address`` compared, the comparison kept for its Sync:
    ``{comparison, peer: {address, server, caracole, name}, synced_before, differences: [{id, label, kind, proposal,
    why, here, there}]}``, ``synced_before`` when the two last agreed (None: never), ``here`` and ``there`` each side's
    digest (None where it has none)."""
    from caracole import peer_sync as sync

    try:
        address = sync.peer_address(form.get("address", ""))
    except sync.PeerError as e:
        raise Refused(400, "Not an address", str(e)) from None
    state, found, synced = _compared(app, address)
    made = _keep(app, Compared(address, state.name, sync.compared_hash(found), {d.id: d.proposal for d in found},
                               time.monotonic()))
    return json_response(200, {
        "comparison": made,
        "peer": {"address": address, "server": state.server, "caracole": state.version, "name": state.name},
        "synced_before": synced,
        "differences": [{"id": d.id, "label": d.label, "kind": d.id.partition("/")[0], "proposal": d.proposal,
                         "why": d.why, "here": d.mine.digest if d.mine else None,
                         "there": d.theirs.digest if d.theirs else None} for d in found],
    })


def choices_of(text: str, proposals: dict[str, str]) -> dict[str, str]:
    """The owner's choices, a line each (``<here|there|skip>\\t<unit id>``, a blank line left out), each unit's side;
    Refused (400) for a line that isn't one, a unit the comparison didn't find, or one chosen two ways."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        side, tab, unit_id = line.partition("\t")
        if not tab or side not in SIDES or unit_id not in proposals:
            raise Refused(400, "Not a choice", f"{line[:200]!r} isn't a choice of this comparison's: here, there "
                                               "or skip, a tab, then one of its units.")
        if found.get(unit_id, side) != side:
            raise Refused(400, "Not a choice", f"{unit_id[:200]} is chosen two ways.")
        found[unit_id] = side
    return found


def apply(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /sync/apply``: the comparison's sync queued, as the owner chose (see the module's docstring); the
    answer is the job, as /jobs.json gives it. A sync with the same caracole that waits or runs is refused (409): its
    choices were made on another comparison."""
    made = form.get("comparison", "").strip()
    kept = _kept_one(app, made) if made else None
    if kept is None:
        raise Refused(409, "Compare again", GONE)
    prefer = form.get("prefer", "").strip()
    if prefer not in PREFER:
        raise Refused(400, "Not a side", "prefer is here, there, or nothing.")
    choices = choices_of(form.get("choices", ""), kept.proposals)
    open_ = [u for u, proposal in kept.proposals.items() if proposal == "conflict" and u not in choices]
    if open_ and not prefer:
        raise Refused(409, "Choose first", f"Choose a side for every conflict first: {len(open_)} "
                                           f"{'has' if len(open_) == 1 else 'have'} none.")
    from caracole import peer_sync as sync

    _, found, _ = _compared(app, kept.address)  # afresh: refused now, before anything is queued, once it is past
    if sync.compared_hash(found) != kept.hash:
        _forget(app, made)
        raise Refused(409, "Compare again", STALE)
    shown = f"Sync with {(kept.name.strip() or kept.address)[:120]}"
    args = ("peer", "sync", "--push", "--yes", "--progress", f"--compared={kept.hash}",
            *(f"--choose={side}:{unit_id}" for unit_id, side in choices.items()),
            *((f"--prefer={prefer}",) if prefer else ()), "--", kept.address)
    job, new = app.submit(shown, SYNCING + kept.address, [(shown, args)], display=shown, join=False)
    if not new:
        raise Refused(409, "Syncing already", f"A sync with {kept.address} is on its way already (request "
                                              f"{job.id}): compare again once it is over.")
    _forget(app, made)
    return app.queued(job, "/#tab=sync")
