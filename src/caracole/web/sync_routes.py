"""caracole serve's Sync tab (library_assets/sync.js): this library and another caracole's, compared unit by unit
(peer_sync.py), and synced as the owner chose.

    GET  /api/sync        this caracole's id, its library's name, its device (``"computer"``: the phone's says
                          ``"phone"``), its songs and songbooks counted (``songbooks`` null while songbooks.toml
                          can't be read), the address it synced with last, and each caracole it synced with before
                          (kv ``sync:peer:<id>``, which ``caracole peer sync`` keeps)
    POST /sync/test       the caracole at ``address`` asked what it holds, changing nothing: its songs, songbooks,
                          the newest read of its indexes, when this one last synced with it, and that in words
                          (``said``, ``tested_words``); refused as a comparison is
    POST /sync/compare    this library and the one at ``address`` compared, as ``caracole peer diff`` compares them:
                          every unit the two hold differently, with what the sync proposes for it, each song's names,
                          each side's change since the two last agreed, its part and the songbooks that list it; each
                          songbook difference's two documents; the indexes newer on either side; kept 10 minutes
                          under an id of its own (``comparison``)
    GET  /api/sync/unit?comparison=&id=   a unit of a comparison kept, its two documents: this side's and the other's,
                          asked of it now, or an import's read from its file (``here``, ``there``: null where a side
                          hasn't got it); the page's script alone asks it
    GET  /api/sync/indexes   each site's index here: its newest read and the tabs it tracks
                          (``index_transfer.newest``, ``tab_counts``), which the phone asks after it gives one
    POST /sync/apply      a comparison kept (``comparison``), synced with the owner's choices (``choices``: a line a
                          unit, ``<here|there|skip>\\t<unit id>``; ``prefer``: here, there, or "" for none) and its
                          parts (``parts``: library, songbooks, indexes by commas; none sent, all three):
                          ``caracole peer sync --push --parts=… --compared HASH --choose=…`` queued, its view the
                          answer; on a file's comparison (``POST /sync/import/compare``, web/sync_file_routes.py),
                          ``caracole peer import`` of the folder it is staged in, under ``import:<id>``

Test and the comparison ask the other caracole for its state, one request (``GET /api/peer/state``), and a comparison
asks for each songbook the two hold differently that the other has (``GET /api/peer/unit``), so that the songs either
side's songbooks list are read from both sides' documents (``peer_sync.listed_songs``), on the request's thread, as
``caracole peer diff`` does from a terminal: no lock, nothing written. A comparison is made as ``caracole peer sync``
makes it, with the answers an import remembered (``peer_sync.merged_kept``), so that a unit kept here at an import is
given there; its hash (``peer_sync.compared_hash``) is of every difference, whatever parts are synced. Only the
differences, the songbooks' documents and the choices travel between the page and the server, and a unit's two
documents when the page asks for them: the sync's command asks the other side for each unit it takes (``GET
/api/peer/unit``) and pushes there each it gives (``POST /peer/push``), as the phone does, so the other side needn't
reach this one. Sync compares afresh first and refuses (409) a comparison the two no longer agree with, as the command
does again (``--compared``) once it runs; a conflict of the parts synced (``peer_sync.in_scope``) that has neither a
choice nor ``prefer`` is refused too, and so is a part it doesn't know (400). The job is no song's (kind ``sync``,
under ``sync:<address>``): the Sync tab follows it, its stages, and once over what it took, gave and left
(jobs_routes.py ``peer_outcome``). caracole serve writes no file for it; ``caracole peer sync`` keeps what the two
agree on and the peer's address and name.

The phone answers the same routes with the same shapes (docs/superpowers/plans/2026-11-03-sync-redesign.md §3.4.1;
tests/conformance/vectors/web/sync_routes.jsonl).
"""

from __future__ import annotations

import secrets
import threading
import time
import weakref
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from caracole.peer_sync import PARTS
from caracole.web.app import Response, Route, WebApp, json_response, query
from caracole.web.pages import Refused

SYNCING = "sync:"  # a sync's job key: the address it syncs with after it
IMPORTING = "import:"  # an import's comparison's source, and its job's key: the staged file's id after it
KEPT_FOR = 600.0  # seconds a comparison is kept for its Sync
KEPT = 20  # comparisons kept at most, the newest
SIDES = ("here", "there", "skip")
PREFER = ("", "here", "there")
DEVICE = "computer"  # what this caracole is, as GET /api/sync says it: the phone's says "phone"
STALE = "Both books changed since that comparison. Compare again, then choose again."
GONE = "That comparison is over 10 minutes old, or caracole serve restarted. Compare again."
NOT_A_PART = "parts are library, songbooks or indexes, by commas."  # caracole peer sync --parts' words

ROUTES = (
    Route("GET", "/api/sync", lambda app, asked: sync_state(app)),
    Route("POST", "/sync/test", lambda app, asked, form: test(app, form)),
    Route("POST", "/sync/compare", lambda app, asked, form: compare(app, form)),
    Route("GET", "/api/sync/unit", lambda app, asked: unit_documents(app, _params(asked)), script_only=True),
    Route("GET", "/api/sync/indexes", lambda app, asked: indexes(app)),
    Route("POST", "/sync/apply", lambda app, asked, form: apply(app, form), limit=1024 * 1024),
)


def transport():
    """The HTTP transport a comparison asks the other caracole with: httpx's own (None). Tests replace it."""
    return None


def _params(asked) -> dict[str, str]:
    """The fields of the request's address, each its first value."""
    return {k: v[0] for k, v in query(asked).items() if v}


@dataclass(frozen=True)
class Compared:
    """A comparison kept for its Sync: the other side's address and name, what was found (``hash``,
    ``peer_sync.compared_hash``), each difference's proposal by its unit, and when (``time.monotonic``); with whom
    (``source``: ``"peer"``, a caracole serve asked; ``kind``, as the page says it), the parts the other side holds
    (``holds``), the songs either side's songbooks list (``listed``, ``peer_sync.listed_songs``') and the differences
    themselves (``found``), whose scope a Sync of some parts reads: a comparison kept without them (``found`` empty
    while ``proposals`` isn't) has every conflict it proposes chosen first, whatever the parts. ``GET /api/sync/unit``
    asks the other side of a comparison of ``source`` ``"peer"`` alone: another source's units are its own to read."""

    address: str
    name: str
    hash: str
    proposals: dict[str, str]
    at: float
    source: str = "peer"
    holds: tuple[str, ...] = PARTS
    listed: dict[str, list[str]] = field(default_factory=dict)
    kind: str = "server"
    found: tuple = ()


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


# --- what the tab reads first ------------------------------------------------------------------------------------


def sync_state(app: WebApp) -> Response:
    """``GET /api/sync``: this caracole's id (``server``, None before it has one), its library's name, its device
    (``DEVICE``), its songs and songbooks counted (``songbooks`` None while songbooks.toml can't be read: that stops
    the songbooks and nothing else), and each caracole it synced with, newest first (``peers``: its address, id,
    name and when, from kv ``sync:peer:<id>``), the newest's address as ``address``, for the tab's field."""
    from caracole import peer_sync as sync
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    with app.db() as conn:
        server = sync.own_id(conn)
        peers = peers_of(conn)
        songs = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    try:
        songbooks: int | None = len(load_songbooks(songbooks_file(app.cfg.library_dir)))
    except SongbookError:
        songbooks = None
    return json_response(200, {"server": server, "name": app.cfg.library_name, "device": DEVICE,
                               "address": peers[0]["address"] if peers else None, "peers": peers, "songs": songs,
                               "songbooks": songbooks})


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


def _synced_at(conn, server: str | None) -> str | None:
    """When this caracole last synced with ``server``, as kv ``sync:peer:<id>`` records it; None for never, or a
    record that can't be read."""
    from caracole.db import kv_get_json
    from caracole.peer_push import PEER_KEY

    if server is None:
        return None
    try:
        record = kv_get_json(conn, PEER_KEY + server)
    except ValueError:
        return None
    at = record.get("synced_at") if isinstance(record, dict) else None
    return at if isinstance(at, str) else None


# --- Test --------------------------------------------------------------------------------------------------------


def _address(form: Mapping[str, str]) -> str:
    """The other caracole's address the form names, as ``peer_sync.peer_address`` reads it; Refused (400) else."""
    from caracole import peer_sync as sync

    try:
        return sync.peer_address(form.get("address", ""))
    except sync.PeerError as e:
        raise Refused(400, "Not an address", str(e)) from None


def _not_this_one(address: str, me: str | None, state) -> None:
    """Refused (409) when the caracole at ``address`` is this very one: its database a copy of this one's."""
    if me is not None and me == state.server:
        raise Refused(409, "The same scribe", f"The scribe at {address} is this one (same id, {me}): its database is "
                                              "a copy of ours. Give one a new id: caracole peer new-id.")


def test(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /sync/test``: the caracole at ``address`` asked for its state, one request, and nothing written:
    ``{peer: {address, server, caracole, name}, songs, songbooks, indexes, synced_at, said}``, its song and songbook
    units counted, ``indexes`` the newest read of its indexes (``newest_read``; None: none), ``synced_at`` when
    this one last synced with it (None: never), and ``said`` all that in words (``tested_words``). Refused as a
    comparison is: 400 for no address, 502 for nothing answering, 409 for this very caracole."""
    from caracole import peer_sync as sync

    address = _address(form)
    with app.db() as conn:
        me = sync.own_id(conn)
    try:
        with sync.Peer(address, transport=transport()) as peer:
            state = peer.state(me)
    except sync.PeerError as e:
        raise Refused(502, "Not reached", str(e)) from None
    _not_this_one(address, me, state)
    with app.db() as conn:
        synced_at = _synced_at(conn, state.server)
    songs = sum(1 for unit_id in state.units if unit_id.startswith("song/"))
    songbooks = sum(1 for unit_id in state.units if unit_id.startswith("songbook/"))
    newest = newest_read(state.indexes)
    return json_response(200, {
        "peer": {"address": address, "server": state.server, "caracole": state.version, "name": state.name},
        "songs": songs, "songbooks": songbooks, "indexes": newest, "synced_at": synced_at,
        "said": tested_words(state.name.strip() or address, songs, songbooks, newest),
    })


def newest_read(indexes: Mapping[str, str]) -> str | None:
    """The newest of a state's index reads (``PeerState.indexes``), as it gives it; one that isn't a time left out,
    None for none."""
    from caracole import stamps

    read = [(when, text) for text in indexes.values() if (when := stamps.parse(text)) is not None]
    return max(read)[1] if read else None


def _counted(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def tested_words(name: str, songs: int, songbooks: int, indexes_at: str | None) -> str:
    """What Test says of the other caracole: "Studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26"
    (the day in the server's zone), or ", no indexes" for a caracole that read none."""
    from caracole import stamps

    when = stamps.parse(indexes_at) if indexes_at else None
    read = f", its indexes read {when.astimezone().strftime('%d/%m/%y')}" if when is not None else ", no indexes"
    return f"{name} answered: {_counted(songs, 'song')}, {_counted(songbooks, 'songbook')}{read}"


# --- the comparison ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Found:
    """A comparison made (``_compared``): the other side's state, the differences, when the two last agreed (None:
    never), the base and the kept answers they were compared against, the songs either side's songbooks list, each
    songbook difference's two documents, and this side's newest index reads."""

    state: Any
    found: list
    synced: str | None
    base: dict | None
    kept: dict
    listed: dict[str, list[str]]
    songbooks: dict[str, tuple[Any, Any]]
    newest: dict[str, str]


def _compared(app: WebApp, address: str, *, documents: bool = True) -> _Found:
    """The other caracole's state and the comparison, as ``caracole peer sync`` makes it (``_Found``), with, when
    ``documents``, each songbook difference's two documents and the songs both sides' songbooks list (the other's
    songbooks asked for, one request each: none when Sync compares afresh, which needs the hash alone). Refused when
    it can't be asked, is this very caracole, or this library can't be read."""
    from caracole import index_transfer
    from caracole import peer_sync as sync
    from caracole.songbook import name_key
    from caracole.web.peer_routes import _library

    overrides, books = _library(app)
    with app.db() as conn:
        me = sync.own_id(conn)
    try:
        with sync.Peer(address, transport=transport()) as peer:
            state = peer.state(me)
            _not_this_one(address, me, state)
            with app.db() as conn:
                mine = sync.library_state(conn, overrides, books)
                ours = sync.base_of(conn, state.server) if state.server else None
                kept_here = sync.kept_of(conn, state.server) if state.server else {}
                newest = index_transfer.newest(conn) if documents else {}
                base = sync.merged_base(ours, state.base)
                kept = sync.merged_kept(ours, kept_here, state.base, state.kept)
                found = sync.compare(mine, state.units, base, kept)
                differing = [d for d in found if documents and d.id.startswith("songbook/")]
                here_docs = {d.id: sync.unit_document(conn, app.cfg, overrides, books, d.id) for d in differing}
            songbooks: dict[str, tuple[Any, Any]] = {
                d.id: (here_docs[d.id]["unit"] if here_docs[d.id] else None, peer.unit(d.id) if d.theirs else None)
                for d in differing}
    except sync.PeerError as e:
        raise Refused(502, "Not reached", str(e)) from None
    listed: dict[str, list[str]] = {}
    if documents:
        units = set(mine) | set(state.units)
        by: dict[str, set[str]] = {}
        here_books = {f"songbook/{name_key(b.name)}": sync.songbook_value(b) for b in books}
        there_books = {u: there for u, (_, there) in songbooks.items() if there is not None}
        for side in (here_books, there_books):
            for song, listing in sync.listed_songs(side, units).items():
                by.setdefault(song, set()).update(listing)
        listed = {song: sorted(listing) for song, listing in sorted(by.items())}
    agreed = [at for b in (ours, state.base) if b for _, at in b.values()]
    return _Found(state, found, max(agreed) if agreed else None, base, kept, listed, songbooks, newest)


def _waiting(here: Mapping[str, str], there: Mapping[str, str]) -> list[dict[str, Any]]:
    """Each site whose newest read differs on the two sides, in ``index_transfer.SITES``' order, with which side's is
    newer: the side that has one when the other hasn't, else the later."""
    from caracole import index_transfer, stamps

    found = []
    for name, site in index_transfer.SITES.items():
        a, b = here.get(name), there.get(name)
        if a == b:
            continue
        if a is None:
            newer = "there"
        elif b is None:
            newer = "here"
        else:
            t, m = stamps.parse(b), stamps.parse(a)
            newer = "there" if t is not None and (m is None or t > m) else "here"
        found.append({"site": name, "title": site.title, "here": a, "there": b, "newer": newer})
    return found


def compare(app: WebApp, form: dict[str, str]) -> Response:
    """``POST /sync/compare``: this library and the one at ``address`` compared, the comparison kept for its Sync:
    ``{comparison, peer: {address, server, caracole, name, kind, made}, synced_before, holds, differences: [{id,
    label, kind, proposal, why, here, there, names, change, part, with}], songbooks, indexes}``: ``synced_before``
    when the two last agreed (None: never); ``holds``, the parts the other side holds (all three: a caracole serve's
    library); each difference's ``here`` and ``there``, each side's digest (None where it has none), ``names`` a
    song's ``{artist, title}`` (``peer_sync.names_of``; None for another kind), ``change`` what each side did since
    the two last agreed (``peer_sync.change_of``), ``part`` its part (``peer_sync.part_of``) and ``with`` the
    songbooks either side has that list it (``peer_sync.listed_songs``); ``songbooks``, ``{unit: {here, there}}``
    each songbook difference's two documents (None for a side that hasn't got it); ``indexes``, each site whose newest
    read differs (``{site, title, here, there, newer}``)."""
    from caracole import peer_sync as sync

    address = _address(form)
    made = _compared(app, address)
    state, found = made.state, made.found
    kept = Compared(address, state.name, sync.compared_hash(found), {d.id: d.proposal for d in found},
                    time.monotonic(), listed=made.listed, found=tuple(found))
    comparison = _keep(app, kept)
    peer = {"address": address, "server": state.server, "caracole": state.version, "name": state.name,
            "kind": kept.kind, "made": None}
    return json_response(200, comparison_answer(comparison, peer, made.synced, kept.holds, found, made.base,
                                                made.kept, made.listed, made.songbooks,
                                                _waiting(made.newest, state.indexes)))


def comparison_answer(comparison: str, peer: Mapping[str, Any], synced_before: str | None, holds, found: list,
                      base, kept, listed: Mapping[str, list[str]], songbooks: Mapping[str, tuple[Any, Any]],
                      indexes: list[dict[str, Any]]) -> dict[str, Any]:
    """A comparison as the page reads it (``POST /sync/compare``'s answer, and ``POST /sync/import/compare``'s of a
    file: web/sync_file_routes.py): its id, the other side (``peer``), when the two last agreed, the parts the other
    holds, each difference with its names, each side's change against ``base`` and ``kept``, its part and the
    songbooks that list it (``listed``), each songbook difference's two documents, and the indexes newer there."""
    from caracole import peer_sync as sync

    def names(d) -> dict[str, str] | None:
        cut = sync.names_of(d.id, d.label)
        return None if cut is None else {"artist": cut[0], "title": cut[1]}

    return {
        "comparison": comparison,
        "peer": dict(peer),
        "synced_before": synced_before,
        "holds": list(holds),
        "differences": [{"id": d.id, "label": d.label, "kind": d.id.partition("/")[0], "proposal": d.proposal,
                         "why": d.why, "here": d.mine.digest if d.mine else None,
                         "there": d.theirs.digest if d.theirs else None, "names": names(d),
                         "change": list(sync.change_of(d, base, kept)), "part": sync.part_of(d.id),
                         "with": listed.get(d.id, [])} for d in found],
        "songbooks": {unit_id: {"here": here, "there": there} for unit_id, (here, there) in songbooks.items()},
        "indexes": indexes,
    }


def unit_documents(app: WebApp, params: dict[str, str]) -> Response:
    """``GET /api/sync/unit``: a unit of a comparison kept (``comparison``, ``id``), its two documents, ``{id, here,
    there}``: this side's now (``peer_sync.unit_document``'s ``"unit"``) and the other side's, asked of the other
    caracole now (``GET /api/peer/unit``), or, for an import's comparison, read from its staged file
    (``sync_file_routes.file_unit``, sending no request), None for a side that hasn't got it. Refused 409 for a
    comparison past, of another source, or of a file gone, 404 for a unit it didn't find, 502 for the other caracole
    not answering."""
    from caracole import peer_sync as sync
    from caracole.web.peer_routes import _library

    made = params.get("comparison", "").strip()
    kept = _kept_one(app, made) if made else None
    if kept is None:
        raise Refused(409, "Compare again", GONE)
    unit_id = params.get("id", "")
    if unit_id not in kept.proposals:
        raise Refused(404, "Not compared", f"{unit_id[:200]!r} isn't one that comparison found: it is no unit the "
                                           "two hold differently.")
    importing = kept.source.startswith(IMPORTING)
    if kept.source != "peer" and not importing:  # its units are its source's own to read
        raise Refused(409, "Not a network sync", "That comparison is of a file, not of another caracole: its units "
                                                 "are read from the file.")
    overrides, books = _library(app)
    with app.db() as conn:
        here = sync.unit_document(conn, app.cfg, overrides, books, unit_id)
    if importing:
        from caracole.web.sync_file_routes import file_unit

        there = file_unit(app, kept.source[len(IMPORTING):], unit_id)
    else:
        try:
            with sync.Peer(kept.address, transport=transport()) as peer:
                there = peer.unit(unit_id)
        except sync.PeerError as e:
            raise Refused(502, "Not reached", str(e)) from None
    return json_response(200, {"id": unit_id, "here": here["unit"] if here else None, "there": there})


def indexes(app: WebApp) -> Response:
    """``GET /api/sync/indexes``: ``{indexes: {site: {read, tabs}}}``, every site of ``index_transfer.SITES``, its
    newest read (``index_transfer.newest``; None: never read) and the tabs it tracks (``index_transfer.tab_counts``),
    read here alone."""
    from caracole import index_transfer

    with app.db() as conn:
        newest = index_transfer.newest(conn)
        counts = index_transfer.tab_counts(conn)
    return json_response(200, {"indexes": {name: {"read": newest.get(name), "tabs": counts[name]}
                                           for name in index_transfer.SITES}})


# --- the sync ----------------------------------------------------------------------------------------------------


def choices_of(text: str, proposals: dict[str, str]) -> dict[str, str]:
    """The owner's choices, a line each (``<here|there|skip>\\t<unit id>``, a blank line left out), each unit's side;
    Refused (400) for a line that isn't one, a unit the comparison didn't find, or one chosen two ways."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        side, tab, unit_id = line.partition("\t")
        if not tab or side not in SIDES or unit_id not in proposals:
            raise Refused(400, "Not a choice", f"{line[:200]!r} isn't a choice of this compare: here, there "
                                               "or skip, a tab, then a unit.")
        if found.get(unit_id, side) != side:
            raise Refused(400, "Not a choice", f"{unit_id[:200]} is chosen two ways.")
        found[unit_id] = side
    return found


def parts_of(form: Mapping[str, str]) -> tuple[str, ...] | None:
    """The parts a Sync is of (``parts``: library, songbooks, indexes by commas), in ``PARTS``' order; None when the
    form sends none (all three). Refused (400) for none named, or one that isn't a part."""
    if "parts" not in form:
        return None
    named = [p.strip() for p in form["parts"].split(",") if p.strip()]
    if not named or any(p not in PARTS for p in named):
        raise Refused(400, "Not a part", NOT_A_PART)
    return tuple(p for p in PARTS if p in named)


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
    parts = parts_of(form)
    choices = choices_of(form.get("choices", ""), kept.proposals)
    from caracole import peer_sync as sync

    if kept.found or not kept.proposals:
        scoped = [(d.id, d.proposal) for d in sync.in_scope(kept.found, parts or PARTS, listed=kept.listed)]
    else:  # a comparison kept with no differences of its own (``found``): every conflict it proposes, whatever part
        scoped = list(kept.proposals.items())
    open_ = [unit_id for unit_id, proposal in scoped if proposal == sync.CONFLICT and unit_id not in choices]
    if open_ and not prefer:
        raise Refused(409, "Choose first", f"Choose a book for every conflict: {len(open_)} "
                                           f"{'has' if len(open_) == 1 else 'have'} none.")
    if kept.source.startswith(IMPORTING):
        return _apply_import(app, made, kept, parts, choices, prefer)
    fresh = _compared(app, kept.address, documents=False)  # afresh: refused now, before anything is queued
    if sync.compared_hash(fresh.found) != kept.hash:
        _forget(app, made)
        raise Refused(409, "Compare again", STALE)
    shown = f"Share with {(kept.name.strip() or kept.address)[:120]}"
    args = ("peer", "sync", "--push", "--yes", "--progress",
            *((f"--parts={','.join(parts)}",) if parts is not None else ()), f"--compared={kept.hash}",
            *(f"--choose={side}:{unit_id}" for unit_id, side in choices.items()),
            *((f"--prefer={prefer}",) if prefer else ()), "--", kept.address)
    job, new = app.submit(shown, SYNCING + kept.address, [(shown, args)], display=shown, join=False)
    if not new:
        raise Refused(409, "Sharing already", f"Already sharing with {kept.address} (request {job.id}). Compare "
                                              "again once it's done.")
    _forget(app, made)
    return app.queued(job, "/#tab=sync")


def _apply_import(app: WebApp, made: str, kept: Compared, parts: tuple[str, ...] | None, choices: dict[str, str],
                  prefer: str) -> Response:
    """Sync on an import's comparison (``kept.source`` ``import:<id>``, web/sync_file_routes.py): the staged file
    compared again, sending no request (409 ``STALE`` once this library moved since, 409 ``GONE`` once the file is
    gone), then ``caracole peer import --yes --progress [--parts=…] --compared HASH --choose=… -- FOLDER`` queued under
    ``import:<id>``, its view the answer; one of that file waiting or running already is refused (409)."""
    from caracole.web.sync_file_routes import compared_again

    import_id = kept.source[len(IMPORTING):]
    if compared_again(app, import_id) != kept.hash:
        _forget(app, made)
        raise Refused(409, "Compare again", STALE)
    shown = f"Sync with a file from {(kept.name.strip() or 'a library')[:120]}"
    args = ("peer", "import", "--yes", "--progress",
            *((f"--parts={','.join(parts)}",) if parts is not None else ()), f"--compared={kept.hash}",
            *(f"--choose={side}:{unit_id}" for unit_id, side in choices.items()),
            *((f"--prefer={prefer}",) if prefer else ()), "--", kept.address)
    job, new = app.submit(shown, IMPORTING + import_id, [(shown, args)], display=shown, join=False)
    if not new:
        raise Refused(409, "Importing already", f"That file is being imported already (request {job.id}): choose it "
                                                "again once that is over.")
    _forget(app, made)
    return app.queued(job, "/#tab=sync")
