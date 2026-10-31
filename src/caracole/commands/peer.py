"""``caracole peer``: this library and another caracole's compared, unit by unit (peer_sync.py).

``caracole peer diff ADDRESS`` asks the ``caracole serve`` at ADDRESS (the phone's, the computer's) for its library's
units, one request, and lists every one the two hold differently: a song, a removal, a songbook, an artist's alias or
UG page, a blocked tab, each with the side the sync would take it from ("here", "there") or a conflict for you to
settle. It changes nothing on either side and takes no lock, as ``caracole search`` takes none. ``--json`` prints the
comparison as data. Applying it comes next (docs/superpowers/specs/2026-10-31-phone-server-sync-design.md).
``caracole sync`` is another command: wanted.txt read into the library.
"""

from __future__ import annotations

import json
from contextlib import closing

import typer

from caracole.commands._common import fail, load_cfg, open_db

# How a difference's proposal reads, in the list.
WORDS = {"mine": "keep here's", "theirs": "take there's", "conflict": "CONFLICT"}
KINDS = {"song": "Songs", "removed": "Removals", "songbook": "Songbooks", "alias": "Artists' aliases",
         "artist_url": "Artists' UG pages", "block": "Blocked tabs"}


def register(app: typer.Typer) -> None:
    peer_app = typer.Typer(help="Another caracole (the phone's, the computer's) and this one: what each library holds.",
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
        from caracole.overrides import OverridesError, load_overrides
        from caracole.songbook import SongbookError, load_songbooks, songbooks_file

        cfg = load_cfg(ctx)
        try:
            address = sync.peer_address(address)
            peer, version, name, theirs = sync.read_peer(address, transport=transport_for_peer())
        except sync.PeerError as e:
            fail(str(e))
        try:
            overrides = load_overrides(cfg.overrides_file)
            books = load_songbooks(songbooks_file(cfg.library_dir))
        except (OverridesError, SongbookError) as e:
            fail(f"This library can't be read: {e}")
        with closing(open_db(cfg)) as conn:
            mine = sync.library_state(conn, overrides, books)
            me = sync.own_id(conn)
            if me is not None and me == peer:
                fail(f"The caracole at {address} is this one (the same id, {me}): its database is a copy of this "
                     "one's. Nothing to compare.")
            base = sync.base_of(conn, peer) if peer else None
        found = sync.compare(mine, theirs, base)
        if as_json:
            typer.echo(json.dumps({
                "peer": {"address": address, "server": peer, "caracole": version, "name": name},
                "synced_before": base is not None,
                "differences": [{"id": d.id, "label": d.label, "proposal": d.proposal, "why": d.why,
                                 "here": d.mine.digest if d.mine else None,
                                 "there": d.theirs.digest if d.theirs else None} for d in found],
            }, ensure_ascii=False, indent=2))
            return
        typer.echo(_report(address, name, version, base is not None, len(mine), len(theirs), found))


def transport_for_peer():
    """The HTTP transport ``caracole peer`` asks the other caracole with: httpx's own (None). Tests replace it."""
    return None


def _report(address: str, name: str, version: str, synced_before: bool, here: int, there: int,
            found: list) -> str:
    from caracole import __version__

    lines = [f"Here: {here} units. There, {name or 'a library'} at {address} (caracole {version}): {there} units."]
    if version != __version__:
        lines.append(f"Its caracole is {version}, this one {__version__}: the two may read a song differently.")
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
