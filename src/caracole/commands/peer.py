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
- ``caracole peer sync ADDRESS`` compares, asks you to settle each conflict (``--prefer here`` or ``there`` settles
  them all), takes here what comes from there, and, with ``--here`` (this side's address, as the other reaches it),
  asks the other to take what goes there; without it, says what to run there.
- ``caracole peer take DIR`` takes a push another caracole sent (peer_push.py), staged by caracole serve in DIR
  (``state_dir/peer/push-<id>``, ``POST /peer/push`` queues it): its stages check (the push read, each document what
  its digest says), take (a backup first, then each unit as a pull takes one, left when it changed on this side
  since the pusher compared: ``peer_sync.apply_units`` with ``expected_here``), render and agree, a line (with
  ``--progress``, get.py's JSON lines and a unit's event) for each; then DIR is deleted. It exits 0 unless a bug.
- ``caracole peer new-id`` gives this caracole another id, for a database copied from another's.

``caracole sync`` is another command: wanted.txt read into the library.
"""

from __future__ import annotations

import json
from contextlib import closing

import typer

from caracole.commands._common import exclusive, fail, load_cfg, load_ovr, open_db, utcnow, write_pages

# How a difference's proposal reads, in the list.
WORDS = {"mine": "keep here's", "theirs": "take there's", "conflict": "CONFLICT"}
KINDS = {"song": "Songs", "removed": "Removals", "songbook": "Songbooks", "alias": "Artists' aliases",
         "artist_url": "Artists' UG pages", "block": "Blocked tabs"}
PREFER = {"here": "mine", "there": "theirs"}
DONE = {"taken": "Took", "given": "Gave", "left": "Left"}


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
        cfg = load_cfg(ctx)
        address, found, state, synced, here_count = _compare(cfg, address)
        if as_json:
            typer.echo(json.dumps({
                "peer": {"address": address, "server": state.server, "caracole": state.version, "name": state.name},
                "synced_before": synced,
                "differences": [{"id": d.id, "label": d.label, "proposal": d.proposal, "why": d.why,
                                 "here": d.mine.digest if d.mine else None,
                                 "there": d.theirs.digest if d.theirs else None} for d in found],
            }, ensure_ascii=False, indent=2))
            return
        typer.echo(_report(address, state, synced, here_count, found))

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
        prefer: str | None = typer.Option(None, "--prefer", help="Settle every conflict so: here or there."),
        yes: bool = typer.Option(False, "--yes", help="Don't ask before taking the changes."),
    ) -> None:
        """Compare, settle each conflict, take here what comes from there, and have there take what goes there."""
        from caracole import peer_sync as sync

        if prefer is not None and prefer not in PREFER:
            fail("--prefer is here or there", 2)
        cfg = load_cfg(ctx)
        if here is not None:
            try:
                here = sync.peer_address(here)
            except sync.PeerError as e:
                fail(str(e), 2)
        address, found, state, synced, here_count = _compare(cfg, address)
        typer.echo(_report(address, state, synced, here_count, found))
        if not found:
            return

        def choose(d) -> str | None:
            if prefer is not None or not _interactive():
                return None
            answer = typer.prompt(f"{d.label}: keep here's or take there's? (here/there/skip)", default="skip")
            return PREFER.get(answer.strip().lower())

        take, give = sync.decide(found, PREFER.get(prefer or ""), choose)
        left = len(found) - len(take) - len(give)
        typer.echo(f"Here takes {len(take)}, there takes {len(give)}" + (f", {left} left as they are." if left
                                                                         else "."))
        if not take and not give:
            return
        if not yes and _interactive() and not typer.confirm("Go on?", default=True):
            raise typer.Exit(1)
        failed = False
        if take:
            done = _pull(cfg, address, [d.id for d in take],
                         {d.id: d.theirs.digest if d.theirs else None for d in take})
            typer.echo(_pulled(done))
            failed = bool(done.left)
        if give:
            ids = [d.id for d in give]
            if here is None:
                typer.echo(f"There takes {len(ids)}: give --here (this caracole serve's address, as the other reaches "
                           f"it), or run there: caracole peer pull ADDRESS-OF-THIS-ONE "
                           + " ".join(f"--unit={i}" for i in ids))
            else:
                with sync.Peer(address, transport=transport_for_peer()) as peer:
                    try:
                        job = peer.ask_to_pull(here, ids, peer.state().token or "")
                    except sync.PeerError as e:
                        fail(f"There couldn't be asked to take its {len(ids)}: {e}")
                typer.echo(f"Asked {address} to take {len(ids)} from {here}"
                           + (f": its request {job}, in its Requests tab." if job else "."))
        if failed:
            raise typer.Exit(1)

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

    def unit(self, unit_id: str, outcome: str, why: str = "") -> None:
        if self.progress:
            from caracole.get import progress_line

            typer.echo(progress_line({"event": "unit", "id": unit_id, "outcome": outcome, "why": why}))
        else:
            typer.echo(f"  {DONE[outcome]} {unit_id}" + (f": {why}" if why else ""))


def _count(n: int) -> str:
    return f"{n} {'change' if n == 1 else 'changes'}"


def _compare(cfg, address: str):
    """The other caracole's state and the comparison: (address, differences, its state, whether the two synced
    before, how many units here)."""
    from caracole import peer_sync as sync
    from caracole.overrides import OverridesError, load_overrides
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    try:
        address = sync.peer_address(address)
    except sync.PeerError as e:
        fail(str(e), 2)
    try:
        overrides = load_overrides(cfg.overrides_file)
        books = load_songbooks(songbooks_file(cfg.library_dir))
    except (OverridesError, SongbookError) as e:
        fail(f"This library can't be read: {e}")
    with closing(open_db(cfg)) as conn:
        me = sync.own_id(conn)
        try:
            with sync.Peer(address, transport=transport_for_peer()) as peer:
                state = peer.state(me)
        except sync.PeerError as e:
            fail(str(e))
        if me is not None and me == state.server:
            fail(f"The caracole at {address} is this one (the same id, {me}): its database is a copy of this "
                 "one's. Give one of them another: caracole peer new-id.")
        mine = sync.library_state(conn, overrides, books)
        base = sync.merged_base(sync.base_of(conn, state.server) if state.server else None, state.base)
    return address, sync.compare(mine, state.units, base), state, base is not None, len(mine)


def _pull(cfg, address: str, unit_ids: list[str], compared: dict[str, str | None] | None = None):
    """``caracole peer pull``'s work: see the module's docstring. ``compared``: each unit's digest there as compared
    (None: it had none), so that one changed there since is left; else as it is there now. Returns peer_sync's
    ``Applied``."""
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
                    fail(f"The caracole at {address} is this one: nothing to take. caracole peer new-id gives one "
                         "of them another id.")
                wanted = [(u, compared[u] if compared is not None and u in compared
                           else state.units[u].digest if u in state.units else None) for u in unit_ids]
                now = utcnow()
                made = backup.make(conn, cfg.state_dir, now, label=BACKUP_LABEL)
                if isinstance(made, backup.Skipped):
                    fail(f"Nothing taken: no backup of the database first, {made.reason}.")
                done = sync.apply_units(conn, cfg, peer, wanted, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
                overrides = load_ovr(cfg)
                if done.songs:
                    render_all(conn, cfg, overrides, song_ids=done.songs)
                render_songbooks(conn, cfg, overrides)
                write_pages(conn, cfg, overrides, utcnow())
                if state.server is not None:
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
            fail(f"Nothing taken: the database couldn't be backed up first: {e}")
    return done


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
            raise peer_push.PushError("That push comes from this caracole itself (the same id): its database is a "
                                      "copy of this one's. Give one of them another: caracole peer new-id.")
        said.stage("check", "done", f"{_count(len(push.take))} from {shown}")
        now = utcnow()
        try:
            made = backup.make(conn, cfg.state_dir, now, label=BACKUP_LABEL)
            nothing = (f"Nothing taken: no backup of the database first, {made.reason}."
                       if isinstance(made, backup.Skipped) else None)
        except backup.BackupError as e:
            nothing = f"Nothing taken: the database couldn't be backed up first: {e}"
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
            said.stage("agree", "done", f"{agreed} {'unit' if agreed == 1 else 'units'} the two agree on")
    typer.echo(f"From {shown}: " + _pulled(done, units=False))
    if done.respelled:
        typer.echo("Respelled as it writes their artist: " + ", ".join(done.respelled))


BACKUP_LABEL = "before-sync"  # the database's copy a pull or a take makes first (backup.py)


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
        lines.append(f"    {WORDS[d.proposal]:<13} {d.label}  ({d.why})")
    return "\n".join(lines)
