"""``caracole peer``: this library and another caracole's (the phone's, the computer's), compared and synced unit by
unit (peer_sync.py; the design: docs/superpowers/specs/2026-10-31-phone-server-sync-design.md).

- ``caracole peer diff ADDRESS`` asks the ``caracole serve`` at ADDRESS for its library's units, one request, and lists
  every one the two hold differently (a song, a removal, a songbook, an artist's alias or UG page, a blocked tab),
  each with the side it would come from, "here" or "there", or a conflict for you to settle. It changes nothing on
  either side and takes no lock, as ``caracole search`` takes none. ``--json`` prints the comparison as data.
- ``caracole peer pull ADDRESS --unit ID…`` takes those units from the caracole at ADDRESS: under caracole's lock,
  waiting for the nightly run as a lookup does, after a backup of the database; then renders the songs it took,
  makes the songbooks and writes the pages, and keeps what the two now agree on. caracole serve's ``POST /peer/pull``
  queues it.
- ``caracole peer sync ADDRESS`` compares, settles each conflict (``--choose=<here|there|skip>:<unit id>`` for one,
  ``--prefer here`` or ``there`` for the rest, else asked), takes here what comes from there, and gives there what
  goes there: pushed (``--push``, peer_push.py, as the phone pushes), or asked of the other to pull (``--here``, this
  side's address as the other reaches it), or, with neither, the line to run there. ``--compared HASH`` refuses,
  before any change, a comparison that isn't the one the choices were made on (``peer_sync.compared_hash``: the
  Sync tab's), and applies the one it names: with the answers an import remembered, as ``peer diff`` shows it, or,
  once one was, without them, as caracole serve's Sync tab compares (web/sync_routes.py ``_compared``), so that a
  Sync from the tab does what the tab showed. Then it keeps what the two agree on, and the peer's address and name
  (kv ``sync:peer:<id>``,
  ``peer_push.PEER_KEY``), which caracole serve's Sync tab lists. ``--progress``: get.py's JSON lines, its stages
  compare, take, give and agree (web/jobs.py ``PEER_SYNC_STAGES``), and ``{"event": "unit", "id", "outcome",
  "why"}`` for each unit taken, given or left.
- ``caracole peer take DIR`` takes a push another caracole sent (peer_push.py), staged by caracole serve in DIR
  (``state_dir/peer/push-<id>``, ``POST /peer/push`` queues it): its stages check (the push read, each document what
  its digest says), take (a backup first, then each unit as a pull takes one, left when it changed on this side
  since the pusher compared: ``peer_sync.apply_units`` with ``expected_here``), render and agree, a line (with
  ``--progress``, get.py's JSON lines and a unit's event) for each; then DIR is deleted. It exits 0 unless a bug.
- ``caracole peer export FILE`` writes this library to a ``.caracole`` file (peer_file.py): its songs with their
  kept files and pages, its songbooks with the songs they list, and with ``--parts`` its site indexes too
  (``--parts library,songbooks``, the default; ``indexes`` adds them), its units in one read transaction, taking no
  lock as ``caracole index export`` takes none. FILE is a new file, or a folder to write
  ``<library>-dd-mm-yy.caracole`` in. It says what it wrote and each song it left out, and why (a kept file that
  changed since caracole kept it, or one bigger than a file carries).
- ``caracole peer import SOURCE`` syncs this library with a file another caracole exported, as if that caracole
  were here (SOURCE a ``.caracole`` file, an index export, or the folder caracole serve staged one in,
  ``state_dir/peer/import-<id>``, deleted once it is over): its stages check (the file read whole, then refused, in
  your words, when it is this library's own export or no newer than the last sync with its caracole:
  ``peer_file.check_importable``), take (a backup first, then each unit the file gives, as a pull takes one),
  render, agree (what the two now agree on, stamped with the file's ``made``, and each answer "keep mine" to what
  the file would give remembered: a file takes nothing back; none for an import of the indexes alone) and index (its
  indexes merged, ``index_transfer.merge``), ``PEER_IMPORT_STAGES``. A staged folder is taken only once its file is
  whole (``peer_import.whole``: else refused and left, to be sent on). ``--parts``, ``--choose``, ``--prefer``,
  ``--compared``, ``--progress`` and ``--yes`` as ``peer sync``'s; at the end, with ``--progress``, ``{"event":
  "report", "report": …}``, what it did for the Sync tab's summary, also when it took nothing. It exits 2 for a file
  refused, 1 for a unit left or its indexes not merged, else 0.
- ``caracole peer new-id`` gives this caracole another id, for a database copied from another's.

``peer sync`` and ``peer import`` take ``--parts``, the parts of the sync (``peer_sync.PARTS``: library, songbooks,
indexes, by commas; all three by default): a difference outside them is neither taken nor given nor said, but a song
a songbook lists comes along with the songbooks (``peer_sync.in_scope``). A sync compares with the answers an
import remembered (``peer_sync.merged_kept``): a unit kept here then is given there now.

``caracole sync`` is another command: wanted.txt read into the library.
"""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass, replace

import typer

from caracole.commands._common import exclusive, fail, load_cfg, load_ovr, open_db, utcnow, write_pages

# How a difference's proposal reads, in the list.
WORDS = {"mine": "ours goes there", "theirs": "theirs comes here", "conflict": "CONFLICT"}
FILE_WORDS = {"mine": "keep here's", "theirs": "take the file's", "conflict": "CONFLICT"}
KINDS = {"song": "Songs", "removed": "Removed", "songbook": "Songbooks", "alias": "Artists' aliases",
         "artist_url": "Artists' UG pages", "block": "Blocked tabs"}
PREFER = {"here": "mine", "there": "theirs"}
SIDES = ("here", "there", "skip")  # what --choose says of a unit
DONE = {"taken": "Took", "given": "Gave", "left": "Left"}
STALE = "Both books changed since that comparison. Compare again, then choose again."
UNSETTLED = "both books changed it: choose one"
SKIPPED = "skipped, as you chose"
NOT_A_PART = "parts are library, songbooks or indexes, by commas."
# ``caracole peer import --progress``'s stages, which caracole serve's jobs name (§3.5 of the sync redesign's plan).
PEER_IMPORT_STAGES = (("check", "Reading the file"), ("take", "Taking what they wrote"),
                      ("render", "Rendering what was taken"), ("agree", "Noting where the books agree"),
                      ("index", "Merging the indexes"))


def register(app: typer.Typer) -> None:
    peer_app = typer.Typer(help="Another caracole (the phone's, the computer's) and this one: compare and sync.",
                           no_args_is_help=True)
    app.add_typer(peer_app, name="peer")

    @peer_app.command("diff")
    def diff_cmd(
        ctx: typer.Context,
        address: str = typer.Argument(..., help="The other caracole serve's address: http://192.168.1.20:8737"),
        as_json: bool = typer.Option(False, "--json", help="Print the comparison as JSON."),
    ) -> None:
        """List what this library and the one at ADDRESS hold differently, and which side each would come from.
        Changes nothing."""
        from caracole import peer_sync as sync

        cfg = load_cfg(ctx)
        c = _compare(cfg, address)
        state = c.state
        if as_json:
            typer.echo(json.dumps({
                "peer": {"address": c.address, "server": state.server, "caracole": state.version,
                         "name": state.name},
                "synced_before": c.synced_before,
                "compared": sync.compared_hash(c.found),
                "differences": [{"id": d.id, "label": d.label, "proposal": d.proposal, "why": d.why,
                                 "here": d.mine.digest if d.mine else None,
                                 "there": d.theirs.digest if d.theirs else None} for d in c.found],
            }, ensure_ascii=False, indent=2))
            return
        typer.echo(_report(c.address, state, c.synced_before, len(c.mine), c.found))

    @peer_app.command("pull")
    def pull_cmd(
        ctx: typer.Context,
        address: str = typer.Argument(..., help="The other caracole serve's address."),
        units: list[str] = typer.Option(..., "--unit", help="A unit to take from there (song/<key>, …); again for "
                                                           "more."),
    ) -> None:
        """Take these units from the caracole at ADDRESS, then render what changed and write the pages."""
        from caracole import peer_sync as sync

        cfg = load_cfg(ctx)
        try:
            address = sync.peer_address(address)
        except sync.PeerError as e:
            fail(str(e), 2)
        done = _pull(cfg, address, list(dict.fromkeys(units)))
        typer.echo(_pulled(done))
        if done.left:
            raise typer.Exit(1)

    @peer_app.command("sync")
    def sync_cmd(
        ctx: typer.Context,
        address: str = typer.Argument(..., help="The other caracole serve's address."),
        here: str | None = typer.Option(None, "--here", help="This caracole serve's address, as the other reaches "
                                                            "it: it then takes what goes there itself."),
        push: bool = typer.Option(False, "--push", help="Give there what goes there by pushing it, as the phone "
                                                       "does: only this side needs to reach the other."),
        prefer: str | None = typer.Option(None, "--prefer", help="Settle every conflict so: here or there."),
        choose: list[str] = typer.Option([], "--choose", metavar="SIDE:UNIT",
                                         help="here, there or skip, then a unit's id (song/<key>, …): that unit "
                                              "so, whatever is proposed for it; again for more."),
        compared: str | None = typer.Option(None, "--compared", metavar="HASH",
                                            help="The comparison the choices were made on (diff --json's "
                                                 "\"compared\"): refused, before any change, when the two differ "
                                                 "from it now."),
        progress: bool = typer.Option(False, "--progress", help="Report each stage and unit as a JSON line, for "
                                                               "caracole serve."),
        yes: bool = typer.Option(False, "--yes", help="Don't ask before taking the changes."),
        parts: str | None = typer.Option(None, "--parts", metavar="PARTS",
                                         help="What to sync, by commas: library, songbooks, indexes (all three by "
                                              "default)."),
    ) -> None:
        """Compare, settle each conflict, take here what comes from there, and give there what goes there."""
        from caracole import peer_sync as sync

        if prefer is not None and prefer not in PREFER:
            fail("--prefer is here or there", 2)
        if push and here is not None:
            fail("--push or --here: one way to give there what goes there", 2)
        choices = _choices(choose)
        wanted_parts = _parts(parts) if parts is not None else sync.PARTS
        cfg = load_cfg(ctx)
        if here is not None:
            try:
                here = sync.peer_address(here)
            except sync.PeerError as e:
                fail(str(e), 2)
        said = _Said(progress)
        said.stage("compare", "running")
        c = _compare(cfg, address, wanted_parts)
        address, state, every = c.address, c.state, c.found
        if compared is not None:
            every = c.named(compared.strip().lower())
            if every is None:
                said.stage("compare", "failed", STALE)
                fail(STALE)
        unknown = sorted(set(choices) - {d.id for d in every})
        if unknown:
            said.stage("compare", "failed", f"--choose names {unknown[0]}, no longer a difference")
            fail(f"--choose names {', '.join(unknown[:3])}, which the two don't hold differently now: compare "
                 "them again.", 2)
        # The differences of the parts asked for alone are taken, given or said (the hash is of every one).
        found = sync.in_scope(every, wanted_parts, listed=c.listed)
        said.stage("compare", "done", f"{len(found)} {'difference' if len(found) == 1 else 'differences'}")
        typer.echo(_report(address, state, c.synced_before, len(c.mine), found))

        def asked(d) -> str | None:
            if prefer is not None or not _interactive():
                return None
            answer = typer.prompt(f"{d.label}: keep here's or take there's? (here/there/skip)", default="skip")
            return PREFER.get(answer.strip().lower())

        take, give = sync.decide(_as_chosen(found, choices), PREFER.get(prefer or ""), asked)
        settled = {d.id for d in (*take, *give)}
        left = [(d.id, SKIPPED if choices.get(d.id) == "skip" else UNSETTLED) for d in found if d.id not in settled]
        if found:
            typer.echo(f"Here takes {len(take)}, there takes {len(give)}"
                       + (f", {len(left)} left as they are." if left else "."))
        if (take or give) and not yes and _interactive() and not typer.confirm("Go on?", default=True):
            raise typer.Exit(1)
        for unit_id, why in left:
            said.unit(unit_id, "left", why)
        if take:
            said.stage("take", "running", _count(len(take)))
            done = _pull(cfg, address, [d.id for d in take],
                         {d.id: d.theirs.digest if d.theirs else None for d in take},
                         expected_here={d.id: d.mine.digest if d.mine else None for d in take},
                         on_unit=said.unit, agree=False)
            said.stage("take", "done", _taken_detail(done))
            typer.echo(_pulled(done, units=False))
        else:
            said.stage("take", "skipped")
        if not give:
            said.stage("give", "skipped")
        elif push:
            said.stage("give", "running", _count(len(give)))
            given, left_there = _push(cfg, address, state, give)
            for unit_id in given:
                said.unit(unit_id, "given")
            for unit_id, why in left_there:
                said.unit(unit_id, "left", why)
            said.stage("give", "done", f"gave {len(given)}" + (f", left {len(left_there)}" if left_there else ""))
            typer.echo(f"Gave {_count(len(given))} to {address}.")
        else:
            ids = [d.id for d in give]
            if here is None:
                said.stage("give", "skipped", "they don't know our address")
                typer.echo(f"There takes {len(ids)}: give --here (this caracole serve's address, as the other reaches "
                           f"it) or --push, or run there: caracole peer pull ADDRESS-OF-THIS-ONE "
                           + " ".join(f"--unit={i}" for i in ids))
            else:
                said.stage("give", "running", _count(len(ids)))
                with sync.Peer(address, transport=transport_for_peer()) as peer:
                    try:
                        job = peer.ask_to_pull(here, ids, peer.state().token or "")
                    except sync.PeerError as e:
                        said.stage("give", "failed", str(e))
                        fail(f"There couldn't be asked to take its {len(ids)}: {e}")
                said.stage("give", "done", f"asked them to take {len(ids)}")
                typer.echo(f"Asked {address} to take {len(ids)} from {here}"
                           + (f": its Journal entry {job}." if job else "."))
        said.stage("agree", "running")
        agreed = _agree(cfg, address)
        said.stage("agree", "done", f"{agreed} {'unit' if agreed == 1 else 'units'} the books agree on")

    @peer_app.command("take")
    def take_cmd(
        ctx: typer.Context,
        folder: str = typer.Argument(..., help="The push's folder, state_dir/peer/push-<id>, as caracole serve "
                                               "staged it (POST /peer/push queues this command)."),
        progress: bool = typer.Option(False, "--progress", help="Report each stage and unit as a JSON line, for "
                                                               "caracole serve."),
    ) -> None:
        """Take the units another caracole pushed here, then render what changed, write the pages, and keep what
        the two now agree on; the push's folder is deleted after."""
        from caracole import peer_push

        cfg = load_cfg(ctx)
        try:
            where = peer_push.sent_folder(cfg.state_dir, folder)
        except peer_push.PushError as e:
            fail(str(e), 2)
        said = _Said(progress)
        try:
            with peer_push.held(where):
                try:
                    _take(cfg, where, said)
                finally:
                    peer_push.remove(where)
        except peer_push.PushError as e:
            said.stage("check", "failed", str(e))
            fail(str(e))
        finally:
            peer_push.sweep(cfg.state_dir)

    @peer_app.command("export")
    def export_cmd(
        ctx: typer.Context,
        file: str = typer.Argument(..., help="The file to write, a new one, or a folder to write "
                                             "<library>-dd-mm-yy.caracole in."),
        parts: str = typer.Option("library,songbooks", "--parts", metavar="PARTS",
                                  help="What it holds, by commas: library, songbooks, indexes."),
    ) -> None:
        """Write this library to a .caracole file, for another caracole to import (or to keep). Changes nothing."""
        cfg = load_cfg(ctx)
        _export(cfg, file, _parts(parts))

    @peer_app.command("import")
    def import_cmd(
        ctx: typer.Context,
        source: str = typer.Argument(..., help="A .caracole file, an index export, or the folder caracole serve "
                                               "staged one in (state_dir/peer/import-<id>)."),
        parts: str | None = typer.Option(None, "--parts", metavar="PARTS",
                                         help="What to sync, by commas: library, songbooks, indexes (all three by "
                                              "default, of those the file holds)."),
        prefer: str | None = typer.Option(None, "--prefer", help="Settle every conflict so: here or there (the "
                                                                "file's)."),
        choose: list[str] = typer.Option([], "--choose", metavar="SIDE:UNIT",
                                         help="here, there or skip, then a unit's id: that unit so; again for more."),
        compared: str | None = typer.Option(None, "--compared", metavar="HASH",
                                            help="The comparison the choices were made on: refused, before any "
                                                 "change, when this library and the file differ from it now."),
        progress: bool = typer.Option(False, "--progress", help="Report each stage and unit as a JSON line, for "
                                                               "caracole serve."),
        yes: bool = typer.Option(False, "--yes", help="Don't ask before taking the changes."),
    ) -> None:
        """Sync this library with a file another caracole exported, as if that caracole were here: take what
        changed there, then keep what the two agree on. A file takes nothing back."""
        from pathlib import Path

        from caracole import peer_import
        from caracole import peer_sync as sync

        if prefer is not None and prefer not in PREFER:
            fail("--prefer is here or there", 2)
        choices = _choices(choose)
        wanted_parts = _parts(parts) if parts is not None else sync.PARTS
        cfg = load_cfg(ctx)
        said = _Said(progress)
        given = Path(source)
        options = {"said": said, "parts": wanted_parts, "choices": choices, "prefer": prefer, "compared": compared,
                   "yes": yes}
        if not given.exists():
            said.stage("check", "failed", f"no file at {source}")
            fail(f"No file at {source}: name a .caracole file, or an index export.", 2)
        if not given.is_dir():
            _import(cfg, given, name=None, **options)
            return
        try:
            folder = peer_import.staged_folder(cfg.state_dir, given)
            try:
                with peer_import.held(folder):
                    # Not whole yet: refused, and left for the rest to come (a sweep deletes it after an hour).
                    path = peer_import.whole(cfg.state_dir, folder.name[len(peer_import.PREFIX):])
                    try:
                        _import(cfg, path, name=peer_import.opened_name(folder), **options)
                    finally:
                        peer_import.remove(folder)
            finally:
                peer_import.sweep(cfg.state_dir)
        except peer_import.StagingError as e:
            said.stage("check", "failed", str(e))
            fail(str(e), 2)

    @peer_app.command("new-id")
    def new_id_cmd(ctx: typer.Context) -> None:
        """Give this caracole another id, for a database copied whole from another caracole's."""
        from caracole import peer_sync as sync

        cfg = load_cfg(ctx)
        with exclusive(cfg, "peer new-id", interactive=True), closing(open_db(cfg)) as conn:
            made = sync.new_id(conn)
        typer.echo(f"This caracole's id is now {made}: it starts over with every caracole it syncs with.")


def transport_for_peer():
    """The HTTP transport ``caracole peer`` asks the other caracole with: httpx's own (None). Tests replace it."""
    return None


def _interactive() -> bool:
    import sys

    return sys.stdin.isatty()


class _Said:
    """What a sync or a take says as it goes: with ``progress``, get.py's JSON lines (a stage's, a unit's event),
    which caracole serve reads (web/jobs.py); else a plain line a unit."""

    def __init__(self, progress: bool):
        self.progress = progress

    def stage(self, name: str, state: str, detail: str = "") -> None:
        if self.progress:
            from caracole.get import progress_line

            typer.echo(progress_line({"stage": name, "state": state, "detail": detail}))

    def report(self, report: dict) -> None:
        """What a sync or an import did, for caracole serve's summary (with ``progress`` alone)."""
        if self.progress:
            from caracole.get import progress_line

            typer.echo(progress_line({"event": "report", "report": report}))

    def unit(self, unit_id: str, outcome: str, why: str = "") -> None:
        if self.progress:
            from caracole.get import progress_line

            typer.echo(progress_line({"event": "unit", "id": unit_id, "outcome": outcome, "why": why}))
        else:
            typer.echo(f"  {DONE[outcome]} {unit_id}" + (f": {why}" if why else ""))


def _count(n: int) -> str:
    return f"{n} {'change' if n == 1 else 'changes'}"


def _choices(given: list[str]) -> dict[str, str]:
    """``--choose``'s, ``<here|there|skip>:<unit id>`` each (the side first: an id holds ``/`` and ``:``): each
    unit's side."""
    found: dict[str, str] = {}
    for text in given:
        side, _, unit_id = text.partition(":")
        if side not in SIDES or "/" not in unit_id:
            fail(f"--choose {text!r}: here, there or skip, a colon, then a unit's id (song/<key>, …)", 2)
        if found.get(unit_id, side) != side:
            fail(f"--choose names {unit_id} twice, two ways", 2)
        found[unit_id] = side
    return found


def _as_chosen(found: list, choices: dict[str, str]) -> list:
    """The differences, each chosen one as chosen: here's (kept here, so there takes it), there's (taken here), or
    left out (skip), whatever was proposed for it."""
    chosen = []
    for d in found:
        side = choices.get(d.id)
        if side == "skip":
            continue
        chosen.append(d if side is None else replace(d, proposal=PREFER[side]))
    return chosen


@dataclass(frozen=True)
class _Compared:
    """This library and the other caracole compared (``_compare``): its address and state; the differences, with
    the answers an import remembered (``peer_sync.merged_kept``, ``kept``), so that a unit kept here at an import is
    this side's to give; this side's units and the base compared against; and the songs the two sides' songbooks
    list (``peer_sync.listed_songs``)."""

    address: str
    state: object
    found: list
    mine: dict
    base: dict | None
    kept: dict
    listed: dict

    @property
    def synced_before(self) -> bool:
        return self.base is not None

    def named(self, hash_: str) -> list | None:
        """The comparison ``hash_`` names (``peer_sync.compared_hash``): this one, or, once an import remembered an
        answer, the same made without the answers, as caracole serve's Sync tab compares (web/sync_routes.py
        ``_compared``); None for neither, a comparison the two no longer agree with."""
        from caracole import peer_sync as sync

        if sync.compared_hash(self.found) == hash_:
            return self.found
        if self.kept:
            plain = sync.compare(self.mine, self.state.units, self.base)
            if sync.compared_hash(plain) == hash_:
                return plain
        return None


def _compare(cfg, address: str, parts: tuple[str, ...] | None = None) -> _Compared:
    """The other caracole's state and the comparison (``_Compared``). The songs songbooks list are read only for a
    sync of the songbooks without the library (``parts``), which needs them: the other side's songbooks asked for,
    one request each."""
    from caracole import peer_sync as sync
    from caracole.songbook import name_key

    try:
        address = sync.peer_address(address)
    except sync.PeerError as e:
        fail(str(e), 2)
    overrides, books = _library(cfg)
    listing = parts is not None and "songbooks" in parts and "library" not in parts
    with closing(open_db(cfg)) as conn:
        me = sync.own_id(conn)
        theirs_books: dict[str, object] = {}
        try:
            with sync.Peer(address, transport=transport_for_peer()) as peer:
                state = peer.state(me)
                if listing and state.server != me:
                    for unit_id in state.units:
                        if unit_id.startswith("songbook/"):
                            theirs_books[unit_id] = peer.unit(unit_id)
        except sync.PeerError as e:
            fail(str(e))
        if me is not None and me == state.server:
            fail(f"The scribe at {address} is this one (same id, {me}): its database is a copy of ours. Give one a "
                 "new id: caracole peer new-id.")
        mine = sync.library_state(conn, overrides, books)
        here_base = sync.base_of(conn, state.server) if state.server else None
        base = sync.merged_base(here_base, state.base)
        kept = sync.merged_kept(here_base, sync.kept_of(conn, state.server) if state.server else {}, state.base,
                                state.kept)
    listed: dict[str, list[str]] = {}
    if listing:
        units = set(mine) | set(state.units)
        found_by: dict[str, set[str]] = {}
        here_books = {f"songbook/{name_key(b.name)}": sync.songbook_value(b) for b in books}
        for books_of in (here_books, {u: doc for u, doc in theirs_books.items() if doc is not None}):
            for song, by in sync.listed_songs(books_of, units).items():
                found_by.setdefault(song, set()).update(by)
        listed = {song: sorted(by) for song, by in sorted(found_by.items())}
    return _Compared(address, state, sync.compare(mine, state.units, base, kept), mine, base, kept, listed)


def _pull(cfg, address: str, unit_ids: list[str], compared: dict[str, str | None] | None = None, *,
          expected_here: dict[str, str | None] | None = None, on_unit=None, agree: bool = True):
    """``caracole peer pull``'s work: see the module's docstring. ``compared``: each unit's digest there as compared
    (None: it had none), so that one changed there since is left; else as it is there now. ``expected_here``: each
    one's digest here as compared, so that one changed here since is left too. ``agree``: keep what the two agree on
    after (a sync does once it gave there what goes there). Returns peer_sync's ``Applied``."""
    from caracole import backup
    from caracole import peer_sync as sync
    from caracole.render import render_all
    from caracole.songbook import SongbookError, load_songbooks, render_songbooks, songbooks_file

    with exclusive(cfg, "peer pull", interactive=True), closing(open_db(cfg)) as conn:
        me = sync.make_id(conn)
        try:
            with sync.Peer(address, transport=transport_for_peer()) as peer:
                state = peer.state(me)
                if state.server == me:
                    fail(f"The scribe at {address} is this one: nothing to take. caracole peer new-id gives one a new "
                         "id.")
                wanted = [(u, compared[u] if compared is not None and u in compared
                           else state.units[u].digest if u in state.units else None) for u in unit_ids]
                now = utcnow()
                made = backup.make(conn, cfg.state_dir, now, label=BACKUP_LABEL)
                if isinstance(made, backup.Skipped):
                    fail(f"Nothing taken: no backup first ({made.reason}).")
                done = sync.apply_units(conn, cfg, peer, wanted, now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        expected_here=expected_here, on_unit=on_unit)
                overrides = load_ovr(cfg)
                if done.songs:
                    render_all(conn, cfg, overrides, song_ids=done.songs)
                render_songbooks(conn, cfg, overrides)
                write_pages(conn, cfg, overrides, utcnow())
                if agree and state.server is not None:
                    try:
                        books = load_songbooks(songbooks_file(cfg.library_dir))
                    except SongbookError:
                        books = None
                    if books is not None:
                        after = peer.state(me)
                        sync.record_agreement(conn, state.server, sync.library_state(conn, overrides, books),
                                              after.units, utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
        except sync.PeerError as e:
            fail(str(e))
        except backup.BackupError as e:
            fail(f"Nothing taken: couldn't back up the database first: {e}")
    return done


def _push(cfg, address: str, state, give: list) -> tuple[list[str], list[tuple[str, str]]]:
    """Give the caracole at ``address`` the differences of ``give`` by pushing them (``peer_push.push_units``: what
    it compared there, ``state``, and here), under caracole's lock, then wait for it to take them, the lock let go:
    (the units it took, those left with why)."""
    from caracole import __version__, peer_push
    from caracole import peer_sync as sync
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    try:
        with peer_push.Pusher(address, transport=transport_for_peer()) as pusher:
            with exclusive(cfg, "peer sync", interactive=True), closing(open_db(cfg)) as conn:
                me = sync.make_id(conn)
                pusher.state(me)  # its form token, as it is now
                overrides = load_ovr(cfg)
                try:
                    books = load_songbooks(songbooks_file(cfg.library_dir))
                except SongbookError as e:
                    fail(f"Nothing given: our songbooks.toml can't be read: {e}")
                pushed = peer_push.push_units(
                    pusher, conn, cfg, overrides, books, {d.id: d.theirs.digest if d.theirs else None for d in give},
                    own=me, at=state.now or utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), name=cfg.library_name,
                    version=__version__, compared_here={d.id: d.mine.digest if d.mine else None for d in give})
            left = list(pushed.left)
            if not pushed.job:
                return [], left
            job = peer_push.wait_for(pusher, pushed.job, sleep=_sleep)
    except sync.PeerError as e:
        fail(f"Couldn't give them {len(give)}: {e}")
    said = {unit_id: (outcome, why) for unit_id, outcome, why in job.get("units") or ()}
    given = []
    for unit_id in pushed.given:
        outcome, why = said.get(unit_id, (None, ""))
        if outcome == "taken":
            given.append(unit_id)
        else:
            left.append((unit_id, why or (f"their Journal entry {pushed.job}: {job['state']}" if job["state"] != "done"
                                          else "not taken there")))
    return given, left


def _sleep(seconds: float) -> None:
    """The pause between two asks of how a push's take goes there. Tests replace it."""
    import time

    time.sleep(seconds)


def _agree(cfg, address: str) -> int:
    """Keep what this side and the caracole at ``address`` agree on now, stamped by its clock, and its address and
    name (kv ``sync:peer:<id>``, which caracole serve's Sync tab lists); how many units were agreed."""
    from caracole import peer_push
    from caracole import peer_sync as sync
    from caracole.db import kv_set_json
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    with exclusive(cfg, "peer sync", interactive=True), closing(open_db(cfg)) as conn:
        me = sync.make_id(conn)
        try:
            with sync.Peer(address, transport=transport_for_peer()) as peer:
                after = peer.state(me)
        except sync.PeerError as e:
            fail(str(e))
        if after.server is None or after.server == me:
            return 0
        overrides = load_ovr(cfg)
        try:
            books = load_songbooks(songbooks_file(cfg.library_dir))
        except SongbookError as e:
            fail(f"This library's songbooks.toml can't be read: {e}")
        at = after.now or utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        agreed = sync.record_agreement(conn, after.server, sync.library_state(conn, overrides, books), after.units,
                                       at)
        kv_set_json(conn, peer_push.PEER_KEY + after.server, {"address": address, "name": after.name,
                                                              "synced_at": at})
    return agreed


def _take(cfg, folder, said: _Said) -> None:
    """``caracole peer take``'s work, the push in ``folder`` held: see the module's docstring."""
    from caracole import backup, peer_push, stamps
    from caracole import peer_sync as sync
    from caracole.render import render_all
    from caracole.songbook import SongbookError, load_songbooks, render_songbooks, songbooks_file

    said.stage("check", "running")
    push = peer_push.read_sent(folder)
    shown = push.name.strip() or "another caracole"
    with exclusive(cfg, "peer take", interactive=True), closing(open_db(cfg)) as conn:
        if push.sender == sync.make_id(conn):
            raise peer_push.PushError("That push comes from this same scribe (same id): its database is a "
                                      "copy of ours. Give one a new id: caracole peer new-id.")
        said.stage("check", "done", f"{_count(len(push.take))} from {shown}")
        now = utcnow()
        try:
            made = backup.make(conn, cfg.state_dir, now, label=BACKUP_LABEL)
            nothing = (f"Nothing taken: no backup first ({made.reason})."
                       if isinstance(made, backup.Skipped) else None)
        except backup.BackupError as e:
            nothing = f"Nothing taken: couldn't back up the database first: {e}"
        if nothing is not None:
            said.stage("take", "failed", nothing)
            for taken in push.take:
                said.unit(taken.id, "left", nothing)
            for stage in ("render", "agree"):
                said.stage(stage, "skipped")
            typer.echo(nothing)
            return
        said.stage("take", "running", _count(len(push.take)))
        done = sync.apply_units(conn, cfg, peer_push.StagedSource(folder, push, conn, cfg.library_dir),
                                [(t.id, t.digest) for t in push.take], stamps.stamp(now),
                                expected_here={t.id: t.expected for t in push.take}, on_unit=said.unit)
        said.stage("take", "done", _taken_detail(done))
        said.stage("render", "running")
        overrides = load_ovr(cfg)
        if done.songs:
            render_all(conn, cfg, overrides, song_ids=done.songs)
        render_songbooks(conn, cfg, overrides)
        write_pages(conn, cfg, overrides, utcnow())
        said.stage("render", "done")
        said.stage("agree", "running")
        try:
            books = load_songbooks(songbooks_file(cfg.library_dir))
        except SongbookError as e:
            said.stage("agree", "failed", f"songbooks.toml can't be read: {e}")
        else:
            agreed = sync.record_agreement(conn, push.sender, sync.library_state(conn, overrides, books),
                                           push.units, push.at)
            said.stage("agree", "done", f"{agreed} {'unit' if agreed == 1 else 'units'} the books agree on")
    typer.echo(f"From {shown}: " + _pulled(done, units=False))
    if done.respelled:
        typer.echo("Respelled as it writes their artist: " + ", ".join(done.respelled))


BACKUP_LABEL = "before-sync"  # the database's copy a pull or a take makes first (backup.py)


def _parts(text: str) -> tuple[str, ...]:
    """``--parts``': the parts named by commas, in ``peer_sync.PARTS``' order; exit 2 for one that isn't a part."""
    from caracole import peer_sync as sync

    named = [p.strip() for p in text.split(",") if p.strip()]
    if not named or any(p not in sync.PARTS for p in named):
        fail(f"--parts {text!r}: {NOT_A_PART}", 2)
    return tuple(p for p in sync.PARTS if p in named)


def _library(cfg):
    """This library's overrides.toml and songbooks, as a sync reads them; exit 1 when either can't be read."""
    from caracole.overrides import OverridesError, load_overrides
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    try:
        overrides = load_overrides(cfg.overrides_file)
        books = load_songbooks(songbooks_file(cfg.library_dir))
    except (OverridesError, SongbookError) as e:
        fail(f"This library can't be read: {e}")
    return overrides, books


def _export(cfg, file: str, parts: tuple[str, ...]) -> None:
    """``caracole peer export``'s work: see the module's docstring."""
    from pathlib import Path

    from caracole import __version__, peer_file
    from caracole.web.offline_routes import library_pages

    now = utcnow()
    path = Path(file)
    if path.is_dir():
        path = path / peer_file.file_name(cfg.library_name, now.astimezone())
    overrides, books = _library(cfg)
    pages = library_pages(cfg) if "library" in parts else None
    with closing(open_db(cfg)) as conn:
        try:
            made = peer_file.export_file(conn, cfg, overrides, books, path, parts, now=now, version=__version__,
                                         name=cfg.library_name, pages=pages)
        except peer_file.FileError as e:
            fail(f"peer export: {e}", 2)
    typer.echo(f"Exported {cfg.library_name}: {_counted(made.songs, 'song')}, {_counted(made.songbooks, 'songbook')}"
               f", {made.size / 1_000_000:.1f} MB to {made.path}.")
    if "library" in parts and pages is None:
        typer.echo("  No pages in it: the library page isn't as caracole last wrote it (caracole todo writes it "
                   "again), so a phone that takes its songs opens them as their sheets' text.")
    for unit_id, why in made.left:
        typer.echo(f"  Left out {unit_id}: {why}.")


def _counted(n: int, noun: str) -> str:
    return f"{n} {noun if n == 1 else noun + 's'}"


def _import(cfg, path, *, name: str | None, said: _Said, parts: tuple[str, ...], choices: dict[str, str],
            prefer: str | None, compared: str | None, yes: bool) -> None:
    """``caracole peer import``'s work, the file at ``path``: see the module's docstring."""
    from caracole import peer_file
    from caracole import peer_sync as sync

    said.stage("check", "running")
    try:
        file = peer_file.read_file(path, name=name)
    except peer_file.FileError as e:
        said.stage("check", "failed", str(e))
        fail(str(e), 2)
    overrides, books = _library(cfg)
    with closing(open_db(cfg)) as conn, peer_file.FileSource(file, conn, cfg.library_dir) as source:
        try:
            peer_file.check_importable(file, conn, own=sync.own_id(conn))
            peer_file.check_whole(file)
            found = peer_file.compare_file(conn, overrides, books, file, source)
        except (peer_file.FileError, sync.PeerError) as e:
            said.stage("check", "failed", str(e))
            fail(str(e), 2)
        if compared is not None and sync.compared_hash(found.found) != compared.strip().lower():
            said.stage("check", "failed", STALE)
            fail(STALE)
        unknown = sorted(set(choices) - {d.id for d in found.found})
        if unknown:
            said.stage("check", "failed", f"--choose names {unknown[0]}, no longer a difference")
            fail(f"--choose names {', '.join(unknown[:3])}, which this library and the file don't hold differently "
                 "now: compare them again.", 2)
        scoped = peer_file.in_parts(found, parts)
        shown = file.name.strip() or "a file"
        said.stage("check", "done", f"{len(scoped)} {'difference' if len(scoped) == 1 else 'differences'} with "
                                    f"{shown}'s file")
        typer.echo(_file_report(file, len(found.mine), found.synced_before, scoped))

        def asked(d) -> str | None:
            if prefer is not None or not _interactive():
                return None
            answer = typer.prompt(f"{d.label}: keep here's or take the file's? (here/there/skip)", default="skip")
            return PREFER.get(answer.strip().lower())

        take, keep = sync.decide(_as_chosen(scoped, choices), PREFER.get(prefer or ""), asked)
        # A "keep mine" answered for what the file would give: remembered, as the file can't take this side's.
        kept_here = peer_file.kept_answers(scoped, keep)
        settled = {d.id for d in (*take, *keep)}
        left = [(d.id, SKIPPED if choices.get(d.id) == "skip" else UNSETTLED) for d in scoped if d.id not in settled]
        if scoped:
            typer.echo(f"Here takes {len(take)}" + (f", keeps {len(kept_here)} as chosen" if kept_here else "")
                       + (f", {len(left)} left as they are." if left else "."))
        if (take or kept_here) and not yes and _interactive() and not typer.confirm("Go on?", default=True):
            raise typer.Exit(1)
        for unit_id, why in left:
            said.unit(unit_id, "left", why)
        done, indexed = _import_under_lock(cfg, conn, file, source, said, parts, take, kept_here)
    typer.echo(f"From {shown}'s file: " + _pulled(done, units=False))
    if done.respelled:
        typer.echo("Respelled as it writes their artist: " + ", ".join(done.respelled))
    if done.left or not indexed:
        raise typer.Exit(1)


def _import_under_lock(cfg, conn, file, source, said: _Said, parts: tuple[str, ...], take: list,
                       kept_here: dict) -> tuple[object, bool]:
    """An import's take, render, agree and index, under caracole's lock, waiting for the nightly run as a lookup
    does; then its report, also when nothing could be taken. Returns peer_sync's ``Applied``, and whether its
    indexes were merged as asked (False: the index stage failed, or was never reached)."""
    from caracole import backup, stamps
    from caracole import peer_file
    from caracole import peer_sync as sync
    from caracole.render import render_all
    from caracole.songbook import SongbookError, load_songbooks, render_songbooks, songbooks_file

    done = sync.Applied()
    held = [p for p in sync.PARTS if p in parts and p in file.holds]
    with exclusive(cfg, "peer import", interactive=True):
        now = utcnow()
        if take:
            try:
                made = backup.make(conn, cfg.state_dir, now, label=BACKUP_LABEL)
                nothing = (f"Nothing taken: no backup first ({made.reason})."
                           if isinstance(made, backup.Skipped) else None)
            except backup.BackupError as e:
                nothing = f"Nothing taken: couldn't back up the database first: {e}"
            if nothing is not None:
                said.stage("take", "failed", nothing)
                for d in take:
                    said.unit(d.id, "left", nothing)
                    done.left.append((d.id, nothing))
                for stage in ("render", "agree", "index"):
                    said.stage(stage, "skipped")
                typer.echo(nothing)
                said.report({"with": {"name": file.name, "kind": "file", "address": None}, "at": stamps.stamp(now),
                             "parts": held, "indexes": []})
                return done, "indexes" not in held
            said.stage("take", "running", _count(len(take)))
            done = sync.apply_units(conn, cfg, source, [(d.id, d.theirs.digest if d.theirs else None) for d in take],
                                    stamps.stamp(now), expected_here={d.id: d.mine.digest if d.mine else None
                                                                      for d in take}, on_unit=said.unit)
            said.stage("take", "done", _taken_detail(done))
            said.stage("render", "running")
            overrides = load_ovr(cfg)
            if done.songs:
                render_all(conn, cfg, overrides, song_ids=done.songs)
            render_songbooks(conn, cfg, overrides)
            write_pages(conn, cfg, overrides, utcnow())
            said.stage("render", "done")
        else:
            said.stage("take", "skipped")
            said.stage("render", "skipped")
        if file.index_only or not ({"library", "songbooks"} & set(held)):
            said.stage("agree", "skipped")  # no unit asked of it: nothing agreed, nor this file made older
        else:
            said.stage("agree", "running")
            try:
                books = load_songbooks(songbooks_file(cfg.library_dir))
            except SongbookError as e:
                said.stage("agree", "failed", f"songbooks.toml can't be read: {e}")
            else:
                mine = sync.library_state(conn, load_ovr(cfg), books)
                agreed = peer_file.record_import(conn, file, mine, kept_here)
                said.stage("agree", "done", f"{agreed} {'unit' if agreed == 1 else 'units'} the books agree on"
                                            + (f", {len(kept_here)} kept here" if kept_here else ""))
        indexes = _merge_indexes(cfg, conn, file, source, said, parts, now)
    said.report({"with": {"name": file.name, "kind": "file", "address": None}, "at": stamps.stamp(now),
                 "parts": held, "indexes": indexes or []})
    return done, indexes is not None


def _merge_indexes(cfg, conn, file, source, said: _Said, parts: tuple[str, ...], now) -> list[dict] | None:
    """The file's indexes merged into this database (``index_transfer.merge``), when it holds them and they are
    asked for: the report's ``indexes``, each site that took something, its first table's rows before and after
    and its newest read; None when the merge failed. An index export is merged where it is; a ``.caracole`` file's
    indexes.sqlite is copied out into ``cache_dir/peer`` (0700), merged, and deleted."""
    import os
    import secrets

    from caracole import backup, index_transfer
    from caracole import peer_sync as sync

    if "indexes" not in parts or "indexes" not in file.holds:
        said.stage("index", "skipped")
        return []
    said.stage("index", "running")
    copy = None
    try:
        if file.index_only:
            merged_from = file.path
        else:
            folder = cfg.cache_dir / "peer"
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(folder, 0o700)
            copy = merged_from = folder / f"import-indexes-{secrets.token_hex(6)}.sqlite"
            source.indexes(copy)
        merged = index_transfer.merge(conn, merged_from, state_dir=cfg.state_dir, now=now)
    except (index_transfer.TransferError, backup.BackupError, sync.PeerError, OSError) as e:
        said.stage("index", "failed", str(e))
        typer.echo(f"The file's indexes weren't merged: {e}")
        return None
    finally:
        if copy is not None:
            copy.unlink(missing_ok=True)
    newest = index_transfer.newest(conn)
    taken = []
    for site in merged.sites:
        if not site.changed:
            continue
        first = index_transfer.SITES[site.site].tables[0]
        before, after = site.rows.get(first, (0, 0))
        taken.append({"site": site.site, "title": index_transfer.SITES[site.site].title, "direction": "taken",
                      "before": before, "after": after, "read": newest.get(site.site)})
    said.stage("index", "done", f"{len(taken)} {'index' if len(taken) == 1 else 'indexes'} merged" if taken
               else "nothing read more recently")
    return taken


def _file_report(file, here: int, synced_before: bool, found: list) -> str:
    """What an import compared, as ``_report`` says a peer's: what the file differs in, a "keep here's" counted
    alone (a file takes nothing back)."""
    from caracole import __version__

    made = file.made or "?"
    lines = [f"Here: {here} units. The file, of {file.name or 'a library'} (caracole "
             f"{file.manifest.get('caracole') or '?'}, made {made}): "
             + (f"{len(file.state.units)} units." if file.state is not None else "its site indexes alone.")]
    if file.manifest.get("caracole") not in (None, __version__):
        lines.append(f"Its caracole is {file.manifest.get('caracole')}, this one {__version__}: the two may read a "
                     "song differently.")
    if file.state is not None and not synced_before:
        lines.append("The two never synced: a unit in the file alone is the file's, and one both hold, "
                     "differently, a conflict.")
    shown = [d for d in found if d.proposal != "mine"]
    mine = len(found) - len(shown)
    if not shown:
        lines.append("Nothing to take." + (f" {mine} kept as they are here: a file takes nothing back." if mine
                                           else ""))
        return "\n".join(lines)
    conflicts = sum(1 for d in shown if d.proposal == "conflict")
    lines.append(f"{len(shown)} {'difference' if len(shown) == 1 else 'differences'}"
                 + (f", {conflicts} {'conflict' if conflicts == 1 else 'conflicts'}" if conflicts else "") + ":")
    kind = None
    for d in shown:
        unit_kind = d.id.partition("/")[0]
        if unit_kind != kind:
            kind = unit_kind
            lines.append(f"  {KINDS.get(kind, kind)}:")
        lines.append(f"    {FILE_WORDS[d.proposal]:<15} {d.label}  ({d.why})")
    if mine:
        lines.append(f"{mine} kept as they are here: a file takes nothing back.")
    return "\n".join(lines)


def _taken_detail(done) -> str:
    return f"took {len(done.taken)}" + (f", left {len(done.left)}" if done.left else "")


def _pulled(done, *, units: bool = True) -> str:
    """What a take did: how many units it took and songs it rendered, then (``units``) each unit it left."""
    lines = [f"Took {len(done.taken)} {'change' if len(done.taken) == 1 else 'changes'}"
             + (f"; {len(done.songs)} {'song' if len(done.songs) == 1 else 'songs'} rendered again." if done.songs
                else ".")]
    lines += [f"  Left {unit_id}: {why}" for unit_id, why in done.left] if units else []
    return "\n".join(lines)


def _report(address: str, state, synced_before: bool, here: int, found: list) -> str:
    from caracole import __version__

    lines = [f"Here: {here} units. There, {state.name or 'a library'} at {address} (caracole {state.version}): "
             f"{len(state.units)} units."]
    if state.version != __version__:
        lines.append(f"Its caracole is {state.version}, this one {__version__}: the two may read a song differently.")
    if not synced_before:
        lines.append("The two never synced: a unit on one side alone is that side's, and one both hold, "
                     "differently, a conflict.")
    if not found:
        lines.append("Nothing differs.")
        return "\n".join(lines)
    conflicts = sum(1 for d in found if d.proposal == "conflict")
    lines.append(f"{len(found)} {'difference' if len(found) == 1 else 'differences'}"
                 + (f", {conflicts} {'conflict' if conflicts == 1 else 'conflicts'}" if conflicts else "") + ":")
    kind = None
    for d in found:
        unit_kind = d.id.partition("/")[0]
        if unit_kind != kind:
            kind = unit_kind
            lines.append(f"  {KINDS.get(kind, kind)}:")
        lines.append(f"    {WORDS[d.proposal]:<17} {d.label}  ({d.why})")
    return "\n".join(lines)
