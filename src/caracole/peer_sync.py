"""Two caracoles synced (``caracole peer``), unit by unit: what each library holds, which side each difference
comes from, and each side taking from the other what the owner chose.

The owner keeps a caracole on the computer and another on the phone, each with its own database and library, and
uses either alone (docs/superpowers/specs/2026-10-31-phone-server-sync-design.md). A sync shows what differs
between them, lets the owner choose, for each difference, which side keeps it, and then each side takes what it was
chosen to take: a pull, the side that takes a unit asking the other for it, or a push the other side takes.

**Units.** A library's state is cut into units, each compared and taken whole (``library_state``):

- ``song/<identity key>``: a song, by ``songs.key``: its names as its wanted.txt line gives them (artist, title,
  album, duration, variant), its record's decisions (status, review, the match, its lyrics: their status and a
  hash of their JSON), its versions (provider, tab, slot, kind, label, pick, gone, the URL, a hash of the raw
  record's JSON), its kept files (each name with its SHA-256: ``files``), and every overrides.toml entry about it
  (``overrides.SONG_TABLES``, ``[ignore]`` among them: ``overrides.song_entries``);
- ``removed/<identity key>``: a tombstone of ``caracole remove``;
- ``songbook/<name key>``: a songbook, its name and its songs in order, each with its setting;
- ``alias/<artist key>``, ``artist_url/<artist key>``, ``block/<tab id>``: overrides.toml's entries that are about
  an artist or a tab, not a song.

What caracole makes of a unit (PDFs, viewers, ``.cho``, info.json, the pages) is no part of it, nor what a lookup
would find again (cooldowns, a miss's date, the HTTP cache, the site indexes, which ``caracole index merge``
merges): a side that takes a song renders it again, so two caracoles of different versions agree on what a song is.
A unit's ``digest`` is the SHA-256 of its canonical JSON (``digest_of``: canonical.py, which the phone's caracole
writes byte for byte alike), and a stored JSON text in it is hashed by the JSON it holds (``canonical.stored_hash``),
so that two caracoles that wrote one record in two texts agree; its ``label`` what the owner reads
("Eagles - Hotel California", "the songbook Campfire"). A unit's document (``unit_document``, what ``GET
/api/peer/unit`` answers) holds everything another side needs to take it, and its value, the digest's, is read back
from it alone (``value_of_document``), so a side checks what it is given before it takes it.

**FORMAT 2** (``FORMAT``) is of every document a side answers (the state, a unit, a push), and of the base each
side keeps. A side refuses a document of another format; a base kept by another format is no base (``base_of``),
so the first sync after an upgrade compares as a first sync, with no translation. The state document says when it
was made by its side's clock (``now``), which both sides stamp their agreement with, and the newest read of each of
its site indexes (``indexes``: ``index_transfer.newest``); a reader ignores what it doesn't know.

**Comparing** (``compare``) is three-way once the two have synced: for each unit, its digest when the two last held
it the same, the **base**. Each side keeps its own (kv ``sync:base:<peer id>``, ``{"format": 2, "units": {unit:
[digest or None, when]}}``: None for a unit both lacked, ``record_agreement``), written at the end of every sync it
makes; the other's comes with its state (``GET /api/peer/state?peer=<id>``), and the later of the two counts
(``merged_base``), so a unit one side pushed to the other is known as synced on both, whichever side took it. A
unit only one side changed since is that side's; a unit both changed, differently, a ``CONFLICT`` for the owner to
settle; one both changed the same way, or neither, no difference at all. With no base (the first sync), a unit on
one side alone is that side's, and one both hold, differently, a conflict. ``compared_hash`` names a comparison, so
that a change made on what was compared is refused once either side moved on.

**The remembered answer.** A file of the other's imported can't take this side's version back, so a conflict the
owner answers "keep mine" in an import is remembered beside the base (``record_kept``: its ``"kept"`` member,
``{unit: [digest here, digest there, when]}``, the two versions chosen between and the file's ``made``). The state
document gives the asker the entries kept for it (``"kept"``, read into ``PeerState.kept``), and for each unit the
latest of the four records (each side's agreement and kept answer) counts, an agreement on a tie (``merged_kept``,
the other side's read with its two digests swapped): a kept answer that counts makes the unit, while neither side has
changed it since, the chooser's, ``KEPT_HERE`` or ``KEPT_THERE``, never a conflict asked again; a change on either
side after it is compared as usual (``compare``'s ``kept``). An agreement drops the kept answer of every unit it
agrees on (``record_agreement``), and a base with no kept answer is written as before, with no ``"kept"``.

**Parts.** A sync, or a file, is of some of three parts (``PARTS``): the library (songs, tombstones and the entries
about an artist or a tab), the songbooks, and the site indexes, which no unit is of (``part_of``). A difference is in
a sync's scope when its unit is of a part asked for, or is a song a songbook lists (``listed_songs``, by any cut of
an entry's "Artist - Title", ``songbook.entry_keys``) while the songbooks are; and a unit a file lacks of a part the
file doesn't hold is never read as removed there (``in_scope``'s ``holds``). ``change_of`` says what each side did to
a unit since the base, and ``names_of`` reads a song's names from its label, for the pages.

**Taking** (``apply_units``) reads each chosen unit's document from a ``UnitSource`` (the peer, ``Peer``, or a push
staged here) and leaves it when it is no longer what was compared, on either side (a compare-and-swap of both
digests), then makes it this side's (``_take_song``): a song through its wanted.txt line (``songs.upsert_song``, by
``wanted.sync_wanted``, the one way a song is added, which drops a tombstone of it), then the peer's names written
as the peer writes them, its record's decisions, its versions and their kept files (each file asked for by name and
checked by its SHA-256 before anything changes), its lyrics' files and its overrides.toml entries
(``overrides.put_song_entries``), whole or not at all: the rows in one savepoint that overrides.toml failing rolls
back, the folders' changes and wanted.txt undone with it. When the peer writes the song's artist in another case
alone than this library writes them, every song of theirs here takes the peer's spelling, and their folder is renamed
once, through a temporary name, so that an artist has one folder (``_artist_as_written``'s reason); a song whose
folder changes takes its files along, through descriptors opened from the library down with no link followed. A unit
that can't be taken (its document lacking what the take reads, the database or overrides.toml refusing it, a file
that won't come) is left, saying why, and the others are taken all the same. A song the peer has no
longer is removed here as ``caracole remove`` removes one; a tombstone, a songbook (``songbook.put_songbook``), an
alias, an artist's page or a blocked tab is written or taken out. The caller holds caracole's lock, then renders the
songs taken and writes the pages (commands/peer.py).

Each caracole's id is kv ``sync:id``, which db.py's schema 15 makes for every database (``own_id``); two databases
that are copies of each other share it, and ``caracole peer new-id`` gives one another.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from caracole import canonical
from caracole.db import kv_get, kv_get_json, kv_set, kv_set_json, savepoint

FORMAT = 2  # of every document a side answers, and of the base it keeps: changes only with their shapes
ID_KEY = "sync:id"
# kv, then a peer's id: {"format": FORMAT, "units": {unit: [digest or None, when]}} as of the last time the two agreed,
# and "kept": {unit: [digest here, digest there, when]}, the answers an import remembered (none: no member)
BASE_KEY = "sync:base:"

# What a comparison proposes for a unit.
MINE = "mine"  # this side's: the peer takes it
THEIRS = "theirs"  # the peer's: this side takes it
CONFLICT = "conflict"  # both changed it, differently: the owner chooses

# A song record's columns a song unit carries, beyond its names: what the song is, as its side decided or found it.
# Not its id, key, names or source ids (the line's), when it was added (wanted.txt's first sighting, each side's),
# nor its audio (Music/, each side's own).
SONG_COLUMNS = ("status", "review", "match_decision", "match_step", "match_score", "match_artist_key",
                "match_song_key", "match_candidates", "matched_at", "ug_dirty", "ug_checked_at", "lyrics_status",
                "lyrics_json", "lyrics_at", "lacuerda_checked_at")
VERSION_COLUMNS = ("provider", "tab_id", "slot", "kind", "rating", "votes", "version", "label", "coverage", "url",
                   "raw", "fetched_at", "pick_rank", "gone")
# The per-song kv a song unit carries (songs._PER_SONG_KV's): which kept versions are yours, and which can't be.
CARRIED_KV = ("sheet_versions:yours:", "sheet_versions:unkeepable:", "sheet_versions:same:")
LYRICS_FILES = ("lyrics.txt", "lyrics.lrc")
# Why a unit is left: either side holds it otherwise than when the two were compared.
CHANGED_HERE = "changed here since the comparison"
CHANGED_THERE = "changed there since the comparison"
# Why a unit is one side's though both hold it otherwise than the base: an import's "keep mine", remembered.
KEPT_HERE = "kept here, as you chose when a file of the other's was imported"
KEPT_THERE = "kept there, as you chose when a file of this one's was imported"


@dataclass(frozen=True)
class Unit:
    """One unit of a library's state: its id (``song/…``), what the owner reads of it, and its digest."""

    id: str
    label: str
    digest: str

    @property
    def kind(self) -> str:
        return self.id.partition("/")[0]


@dataclass(frozen=True)
class Difference:
    """A unit the two sides hold differently: each side's (None where it has none) and what the sync proposes,
    ``MINE``, ``THEIRS`` or ``CONFLICT``. ``why`` says it in words."""

    id: str
    label: str
    mine: Unit | None
    theirs: Unit | None
    proposal: str
    why: str


def digest_of(value: Any) -> str:
    """The SHA-256 of ``value``'s canonical JSON (``canonical.digest``)."""
    return canonical.digest(value)


def _stored_hash(text: str | None) -> str | None:
    """The hash of a stored JSON text (a version's raw record, a song's lyrics) as a unit's value holds it: of the
    JSON it holds, so that two texts of one record (its keys in another order, other spaces, ``4.50`` for ``4.5``)
    hash alike, else of its bytes (``canonical.stored_hash``)."""
    return canonical.stored_hash(text)


# --- who this side is, and when it last agreed with a peer -------------------------------------------------------


def own_id(conn: sqlite3.Connection) -> str | None:
    """This caracole's id among the ones it syncs with (kv ``sync:id``, made by schema 15), read alone."""
    return kv_get(conn, ID_KEY) or None


def make_id(conn: sqlite3.Connection) -> str:
    """This caracole's id, made now if it has none."""
    found = own_id(conn)
    if found:
        return found
    made = secrets.token_hex(8)
    kv_set(conn, ID_KEY, made)
    return made


def new_id(conn: sqlite3.Connection) -> str:
    """Another id for this caracole, for a database copied from another's: it starts over with every peer."""
    made = secrets.token_hex(8)
    with savepoint(conn, "peer_new_id"):
        kv_set(conn, ID_KEY, made)
        conn.execute("DELETE FROM kv WHERE substr(key, 1, ?) = ?", (len(BASE_KEY), BASE_KEY))
    return made


Base = dict[str, tuple[str | None, str]]  # a unit's digest (None: both lacked it) and when the two agreed on it
# An answer an import remembered, by unit: this side's digest kept, the other's not taken (None: lacking it), when.
Kept = dict[str, tuple[str | None, str | None, str]]
# A kept answer as a comparison reads it: the digest here and there when it was kept, and whose it was, MINE or THEIRS.
KeptPair = tuple[str | None, str | None, str]


def _read_units(value: Any) -> Base | None:
    """A base's units, ``{unit: [digest or None, when]}``, its odd entries left out; None for no mapping."""
    if not isinstance(value, Mapping):
        return None
    read: Base = {}
    for unit_id, entry in value.items():
        if (isinstance(entry, (list, tuple)) and len(entry) == 2 and (entry[0] is None or isinstance(entry[0], str))
                and isinstance(entry[1], str)):
            read[str(unit_id)] = (entry[0], entry[1])
    return read


def _read_base(value: Any) -> Base | None:
    """A stored base: ``{"format": FORMAT, "units": …}``. Anything else (a base an earlier format kept, untagged)
    is no base, never translated: the next sync compares as a first one."""
    if not isinstance(value, Mapping) or value.get("format") != FORMAT:
        return None
    return _read_units(value.get("units"))


def base_of(conn: sqlite3.Connection, peer: str) -> Base | None:
    """What this side last agreed on with ``peer``, unit by unit, or None if the two never synced (or synced in
    another format)."""
    try:
        return _read_base(kv_get_json(conn, BASE_KEY + peer))
    except ValueError:
        return None


def _read_kept(value: Any) -> Kept:
    """Kept answers, ``{unit: [here, there, when]}``, their odd entries left out; none for no mapping."""
    if not isinstance(value, Mapping):
        return {}
    read: Kept = {}
    for unit_id, entry in value.items():
        if (isinstance(entry, (list, tuple)) and len(entry) == 3
                and all(side is None or isinstance(side, str) for side in entry[:2]) and isinstance(entry[2], str)):
            read[str(unit_id)] = (entry[0], entry[1], entry[2])
    return read


def kept_of(conn: sqlite3.Connection, peer: str) -> Kept:
    """The answers this side's imports of ``peer``'s files remembered, unit by unit (the base's ``"kept"``): none if
    there are none, or the base is of another format or can't be read."""
    try:
        value = kv_get_json(conn, BASE_KEY + peer)
    except ValueError:
        return {}
    if not isinstance(value, Mapping) or value.get("format") != FORMAT:
        return {}
    return _read_kept(value.get("kept"))


def _write_base(conn: sqlite3.Connection, peer: str, base: Base, kept: Kept) -> None:
    """The base kept for ``peer``, its units and, when there are any, its kept answers, each by unit id."""
    stored: dict[str, Any] = {"format": FORMAT, "units": {k: list(v) for k, v in sorted(base.items())}}
    if kept:
        stored["kept"] = {k: list(v) for k, v in sorted(kept.items())}
    kv_set_json(conn, BASE_KEY + peer, stored)


def record_kept(conn: sqlite3.Connection, peer: str, chosen: Mapping[str, tuple[str | None, str | None]],
                at: str) -> int:
    """Remember, beside the base kept for ``peer``, each conflict an import of its file answered "keep mine":
    ``chosen`` ``{unit: (this side's digest, the file's)}``, at ``at``, the file's ``made``; a unit kept before
    takes the new answer. The base's units stay as they are, and none answered writes nothing. Return how many were
    recorded."""
    if not chosen:
        return 0
    base, kept = base_of(conn, peer) or {}, kept_of(conn, peer)
    for unit_id, (here, there) in chosen.items():
        kept[unit_id] = (here, there, at)
    _write_base(conn, peer, base, kept)
    return len(chosen)


def merged_kept(mine: Base | None, mine_kept: Mapping[str, tuple], theirs: Base | None,
                theirs_kept: Mapping[str, tuple]) -> dict[str, KeptPair]:
    """The kept answers a comparison reads: for each unit, the latest of the four records (this side's agreement,
    the other's, this side's kept answer, the other's) by when (ISO 8601 UTC, so the latest sorts last), an
    agreement on a tie, then this side's. A unit whose latest record is a kept answer comes back as a ``KeptPair``:
    this side's as stored, ``MINE``'s; the other's with its two digests swapped, ``THEIRS``'s."""
    merged: dict[str, KeptPair] = {}
    for unit_id in sorted(set(mine_kept) | set(theirs_kept)):
        records: list[tuple[str, KeptPair | None]] = []
        for agreed in (mine, theirs):
            if agreed is not None and unit_id in agreed:
                records.append((agreed[unit_id][1], None))
        if unit_id in mine_kept:
            here, there, when = mine_kept[unit_id]
            records.append((when, (here, there, MINE)))
        if unit_id in theirs_kept:
            there, here, when = theirs_kept[unit_id]
            records.append((when, (here, there, THEIRS)))
        latest = records[0]
        for record in records[1:]:
            if record[0] > latest[0]:
                latest = record
        if latest[1] is not None:
            merged[unit_id] = latest[1]
    return merged


def merged_base(mine: Base | None, theirs: Base | None) -> dict[str, str | None] | None:
    """The base a comparison reads: for each unit, the later of the two sides' agreements on it (``at`` is ISO 8601
    UTC, so the later sorts last); None when neither side has one."""
    if mine is None and theirs is None:
        return None
    merged: dict[str, tuple[str | None, str]] = dict(mine or {})
    for unit_id, entry in (theirs or {}).items():
        if unit_id not in merged or entry[1] > merged[unit_id][1]:
            merged[unit_id] = entry
    return {unit_id: digest for unit_id, (digest, _) in merged.items()}


def record_agreement(conn: sqlite3.Connection, peer: str, mine: Mapping[str, Unit], theirs: Mapping[str, Unit],
                     at: str) -> int:
    """Keep, as agreed with ``peer`` at ``at``, every unit the two hold the same now (and those both lack that the
    base names), dropping the kept answer of each (``record_kept``); the others keep what they had. Return how many
    were agreed."""
    base, kept = base_of(conn, peer) or {}, kept_of(conn, peer)
    agreed = 0
    for unit_id in set(mine) | set(theirs) | set(base):
        a, b = mine.get(unit_id), theirs.get(unit_id)
        if a is not None and b is not None and a.digest == b.digest:
            base[unit_id] = (a.digest, at)
            kept.pop(unit_id, None)
            agreed += 1
        elif a is None and b is None:
            base[unit_id] = (None, at)
            kept.pop(unit_id, None)
    _write_base(conn, peer, base, kept)
    return agreed


# --- a library's units -------------------------------------------------------------------------------------------


def library_state(conn: sqlite3.Connection, overrides, books: Iterable) -> dict[str, Unit]:
    """Every unit of this library, by id: its songs, its tombstones, its songbooks (``books``, songbook.py's), and
    the entries of ``overrides`` (overrides.py's ``Overrides``) about an artist or a tab."""
    from caracole.songbook import name_key
    from caracole.songs import list_songs

    units: dict[str, Unit] = {}

    def add(unit_id: str, label: str, value: Any) -> None:
        units[unit_id] = Unit(unit_id, label, digest_of(value))

    for song in list_songs(conn):
        add(f"song/{song.key}", f"{song.artist} - {song.title}", song_value(conn, song, overrides))
    for key, artist, title in conn.execute("SELECT key, artist, title FROM removed"):
        add(f"removed/{key}", f"{artist} - {title} (removed)", removed_value(artist, title))
    for book in books:
        add(f"songbook/{name_key(book.name)}", f"the songbook {book.name}", songbook_value(book))
    for artist, slugs in overrides.alias.items():
        add(f"alias/{artist}", f"the alias of {artist}", list(slugs))
    for artist, page in overrides.artist_url.items():
        name = overrides.artist_url_names.get(artist, artist)
        add(f"artist_url/{artist}", f"the UG page of {name}", artist_url_value(name, page))
    for tab in sorted(overrides.block):
        add(f"block/{tab}", f"the blocked tab {tab}", True)
    return units


def song_value(conn: sqlite3.Connection, song, overrides) -> dict[str, Any]:
    """What a song unit is, as JSON: see the module's docstring. Nothing of it depends on the song's id here."""
    from caracole.overrides import song_entries

    row = conn.execute(
        "SELECT status, review, match_decision, match_artist_key, match_song_key, lyrics_status, lyrics_json "
        "FROM songs WHERE id = ?", (song.id,)).fetchone()
    status, review, decision, match_artist, match_song, lyrics_status, lyrics_json = row
    versions = [
        {"provider": provider, "tab": tab_id, "slot": slot, "kind": kind, "label": label, "pick": pick_rank,
         "gone": bool(gone), "url": url, "raw": _stored_hash(raw)}
        for provider, tab_id, slot, kind, label, pick_rank, gone, url, raw in conn.execute(
            "SELECT provider, tab_id, slot, kind, label, pick_rank, gone, url, raw FROM versions WHERE song_id = ? "
            "ORDER BY provider, tab_id", (song.id,))
    ]
    files = {name: sha for name, sha in conn.execute(
        "SELECT name, sha256 FROM files WHERE song_id = ? ORDER BY name", (song.id,))}
    return {
        "names": _names(song),
        "status": status,
        "review": bool(review),
        "match": [decision, match_artist, match_song],
        "lyrics": [lyrics_status, _stored_hash(lyrics_json)],
        "versions": versions,
        "files": files,
        "overrides": song_entries(overrides, song.key),
    }


def _names(song) -> dict[str, Any]:
    return {"artist": song.artist, "artists": list(song.artists), "title": song.title, "album": song.album,
            "duration_ms": song.duration_ms, "variant": song.variant}


def removed_value(artist: str, title: str) -> dict[str, Any]:
    """What a tombstone unit is: the song's names alone, so two sides that removed it, whenever, agree."""
    return {"artist": artist, "title": title}


def songbook_value(book) -> dict[str, Any]:
    """What a songbook unit is: its name, and its songs in order, each with its setting's parts it gives."""
    songs = []
    for entry in book.songs:
        setting = entry.setting
        parts = {} if not setting else {
            name: getattr(setting, name) for name in ("key", "mode", "capo", "instrument")
            if getattr(setting, name) is not None}
        songs.append([entry.text, parts])
    return {"name": book.name, "songs": songs}


def artist_url_value(name: str, page: str) -> dict[str, str]:
    return {"name": name, "page": page}


# --- the documents a side answers --------------------------------------------------------------------------------


def state_document(server: str | None, version: str, name: str, units: Mapping[str, Unit],
                   base: Base | None = None, *, now: str | None = None,
                   indexes: Mapping[str, str] | None = None,
                   kept: Mapping[str, tuple] | None = None) -> dict[str, Any]:
    """``GET /api/peer/state``'s answer: who this side is, its units by id, and, for the peer that asked, what this
    side last agreed on with it (``base``, null if never) and the answers its imports of that peer's files remembered
    (``kept``, ``kept_of``'s, as stored: ``here`` this side's; no member unless given); ``now``, this side's clock (a
    stamp; the time it answers, unless given), which a sync stamps its agreement with on both sides, and ``indexes``,
    the newest read of each of its site indexes (``index_transfer.newest``), so the other side asks only for what is
    newer."""
    from caracole import stamps

    doc = {"format": FORMAT, "server": server, "caracole": version, "name": name,
           "now": now if now is not None else stamps.stamp(datetime.now(UTC)),
           "indexes": dict(indexes or {}),
           "units": {u.id: {"label": u.label, "digest": u.digest} for u in sorted(units.values(), key=_order)},
           "base": None if base is None else {k: list(v) for k, v in sorted(base.items())}}
    if kept is not None:
        doc["kept"] = {k: list(v) for k, v in sorted(kept.items())}
    return doc


@dataclass(frozen=True)
class PeerState:
    """A peer's ``state_document`` read back."""

    server: str | None
    version: str
    name: str
    units: dict[str, Unit]
    base: Base | None = None
    token: str | None = None  # its form token, which a pull's form posts (``Peer.ask_to_pull``)
    now: str | None = None  # its clock when it answered
    indexes: dict[str, str] = field(default_factory=dict)  # the newest read of each of its site indexes
    kept: Kept = field(default_factory=dict)  # the answers its imports of the asker's files remembered, as it keeps them


class StateError(ValueError):
    """A peer's answer that isn't a document this caracole reads."""


def read_state_document(data: Any) -> PeerState:
    """A peer's ``state_document`` read back; StateError for anything else."""
    if not isinstance(data, Mapping) or data.get("format") != FORMAT:
        raise StateError("not a caracole sync state of format "
                         f"{FORMAT} (the other caracole may be of another version)")
    server, version, name, units = data.get("server"), data.get("caracole"), data.get("name"), data.get("units")
    if not (server is None or isinstance(server, str) and server) or not isinstance(units, Mapping):
        raise StateError("a sync state with no units, or a server id that can't be read")
    read: dict[str, Unit] = {}
    for unit_id, unit in units.items():
        if not (isinstance(unit_id, str) and "/" in unit_id and isinstance(unit, Mapping)
                and isinstance(unit.get("digest"), str) and isinstance(unit.get("label"), str)):
            raise StateError(f"a unit that can't be read: {str(unit_id)[:80]!r}")
        read[unit_id] = Unit(unit_id, unit["label"], unit["digest"])
    token, now, indexes = data.get("token"), data.get("now"), data.get("indexes")
    stamps = {site: stamp for site, stamp in (indexes.items() if isinstance(indexes, Mapping) else ())
              if isinstance(site, str) and isinstance(stamp, str)}
    return PeerState(server, str(version or "?"), str(name or ""), read, _read_units(data.get("base")),
                     token if isinstance(token, str) and token else None, now if isinstance(now, str) else None, stamps,
                     _read_kept(data.get("kept")))


def unit_document(conn: sqlite3.Connection, cfg, overrides, books: Iterable, unit_id: str) -> dict[str, Any] | None:
    """``GET /api/peer/unit``'s answer: everything another side needs to take the unit, with its digest as
    ``library_state`` gives it; None for a unit this side hasn't got."""
    found = _unit(conn, overrides, books, unit_id, document=True)
    if found is None:
        return None
    value, doc = found
    return {"format": FORMAT, "id": unit_id, "digest": digest_of(value), "unit": doc}


def unit_value(conn: sqlite3.Connection, overrides, books: Iterable, unit_id: str) -> Any:
    """The value of one unit of this library, what its digest is of (as ``library_state`` makes it); None for a
    unit this side hasn't got."""
    found = _unit(conn, overrides, books, unit_id, document=False)
    return None if found is None else found[0]


def _unit(conn: sqlite3.Connection, overrides, books: Iterable, unit_id: str, *, document: bool
          ) -> tuple[Any, dict[str, Any] | None] | None:
    """A unit's value and, with ``document``, its document; None for a unit this side hasn't got."""
    from caracole.songbook import name_key
    from caracole.songs import find_song, removed_song

    kind, _, rest = unit_id.partition("/")
    value: Any
    doc: dict[str, Any] | None
    if kind == "song":
        song = find_song(conn, rest)
        if song is None:
            return None
        value = song_value(conn, song, overrides)
        doc = song_document(conn, song, value) if document else None
    elif kind == "removed":
        stone = removed_song(conn, rest)
        if stone is None:
            return None
        value = removed_value(stone.artist, stone.title)
        doc = {**value, "source_ids": stone.source_ids, "removed_at": stone.removed_at}
    elif kind == "songbook":
        book = next((b for b in books if name_key(b.name) == rest), None)
        if book is None:
            return None
        value = doc = songbook_value(book)
    elif kind == "alias":
        if rest not in overrides.alias:
            return None
        value = list(overrides.alias[rest])
        doc = {"slugs": value}
    elif kind == "artist_url":
        if rest not in overrides.artist_url:
            return None
        value = doc = artist_url_value(overrides.artist_url_names.get(rest, rest), overrides.artist_url[rest])
    elif kind == "block":
        tab = tab_of(rest)
        if tab is None or tab not in overrides.block:
            return None
        value, doc = True, {"tab": tab}
    else:
        return None
    return value, doc


def tab_of(text: str) -> int | None:
    """The tab a ``block/<tab>`` unit names: its id as ``library_state`` writes it, ASCII digits with no leading
    zero (``block/4242``); None for anything else (``block/007``, ``block/٣``, ``block/+7``), which no unit is."""
    if not (text.isascii() and text.isdigit()) or str(int(text)) != text:
        return None
    return int(text)


def value_of_document(unit_id: str, doc: Mapping[str, Any] | None) -> Any:
    """The unit's value, what its digest is of, read from its document alone (``unit_document``'s ``"unit"``): the
    inverse of the documents, so that what another side sends is checked against the digest compared before it is
    taken. None for no document (a unit the other side hasn't got); UnitError for one that isn't a document of its
    kind."""
    if doc is None:
        return None
    kind = unit_id.partition("/")[0]
    try:
        if not isinstance(doc, Mapping):
            raise TypeError("not an object")
        if kind == "song":
            return _song_value_of(doc)
        if kind == "removed":
            return removed_value(_text(doc["artist"]), _text(doc["title"]))
        if kind == "songbook":
            songs = doc["songs"]
            if not isinstance(songs, list) or not all(isinstance(e, list) and len(e) == 2 for e in songs):
                raise TypeError("songs that aren't pairs")
            return {"name": _text(doc["name"]), "songs": songs}
        if kind == "alias":
            slugs = doc["slugs"]
            if not isinstance(slugs, list):
                raise TypeError("slugs that aren't a list")
            return list(slugs)
        if kind == "artist_url":
            return artist_url_value(_text(doc["name"]), _text(doc["page"]))
        if kind == "block":
            if type(doc["tab"]) is not int:
                raise TypeError("a tab that isn't a number")
            return True
    except (KeyError, TypeError, ValueError) as e:
        raise UnitError(f"its document can't be read ({type(e).__name__}: {e})") from None
    raise UnitError(f"this caracole doesn't know units of kind {kind!r}")


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{value!r} isn't text")
    return value


def _song_value_of(doc: Mapping[str, Any]) -> dict[str, Any]:
    """``song_value`` from a ``song_document``: its versions and files in the document's order, which is the
    database's (``ORDER BY provider, tab_id``; files by name)."""
    record, names, overrides = doc["song"], doc["names"], doc["overrides"]
    if not isinstance(record, Mapping) or not isinstance(names, Mapping) or not isinstance(overrides, Mapping):
        raise TypeError("a song, names or overrides that aren't objects")
    versions, files = [], {}
    for version in doc["versions"]:
        raw = version["raw"]
        if raw is not None and not isinstance(raw, str):
            raise TypeError("a raw record that isn't text")
        versions.append({"provider": version["provider"], "tab": version["tab_id"], "slot": version["slot"],
                         "kind": version["kind"], "label": version["label"], "pick": version["pick_rank"],
                         "gone": bool(version["gone"]), "url": version["url"], "raw": _stored_hash(raw)})
        for f in version["files"]:
            files[_text(f["name"])] = f["sha256"]
    lyrics_json = record["lyrics_json"]
    if lyrics_json is not None and not isinstance(lyrics_json, str):
        raise TypeError("lyrics that aren't text")
    return {
        "names": dict(names),
        "status": record["status"],
        "review": bool(record["review"]),
        "match": [record["match_decision"], record["match_artist_key"], record["match_song_key"]],
        "lyrics": [record["lyrics_status"], _stored_hash(lyrics_json)],
        "versions": versions,
        "files": dict(sorted(files.items())),
        "overrides": dict(overrides),
    }


def song_document(conn: sqlite3.Connection, song, value: Mapping[str, Any]) -> dict[str, Any]:
    """A song unit whole: its names, record, versions with their kept files (name, SHA-256, size, rank), carried kv
    and overrides.toml entries."""
    row = conn.execute(f"SELECT {', '.join(SONG_COLUMNS)} FROM songs WHERE id = ?", (song.id,)).fetchone()
    versions = []
    for version in conn.execute(f"SELECT id, {', '.join(VERSION_COLUMNS)} FROM versions WHERE song_id = ? "
                                "ORDER BY provider, tab_id", (song.id,)).fetchall():
        files = [{"name": name, "sha256": sha, "kept_rank": rank}
                 for name, sha, rank in conn.execute(
                     "SELECT name, sha256, kept_rank FROM files WHERE version_id = ? ORDER BY name", (version[0],))]
        versions.append({**{c: version[c] for c in VERSION_COLUMNS}, "files": files})
    carried = {}
    for prefix in CARRIED_KV:
        own = f"{prefix}{song.id}"
        for key, kv_value in conn.execute("SELECT key, value FROM kv WHERE key = ? OR substr(key, 1, ?) = ?",
                                          (own, len(own) + 1, own + ":")):
            carried[prefix + "|" + key[len(own):]] = kv_value
    return {"key": song.key, "names": value["names"], "song": {c: row[c] for c in SONG_COLUMNS},
            "versions": versions, "kv": carried, "overrides": value["overrides"]}


def song_file(conn: sqlite3.Connection, library_dir: Path, key: str, name: str) -> bytes | None:
    """A kept file of the song of ``key`` (``files``), as the folder holds it, while it is what was recorded: its
    bytes, or None (no such song or file, a file changed or gone since, or no regular file)."""
    from caracole.library import read_regular

    row = conn.execute("SELECT files.path, files.sha256 FROM files JOIN songs ON songs.id = files.song_id "
                       "WHERE songs.key = ? AND files.name = ?", (key, name)).fetchone()
    if row is None:
        return None
    try:
        data = read_regular(library_dir / row[0])
    except (OSError, ValueError):
        return None
    return data if hashlib.sha256(data).hexdigest() == row[1] else None


# --- the comparison ----------------------------------------------------------------------------------------------


def compare(mine: Mapping[str, Unit], theirs: Mapping[str, Unit],
            base: Mapping[str, str | None] | None,
            kept: Mapping[str, KeptPair] | None = None) -> list[Difference]:
    """Every unit the two sides hold differently, with what the sync proposes for it (see the module's docstring),
    in ``_order``: songs first, by their label. A unit ``kept`` names (``merged_kept``) is compared with the two
    versions kept, whatever the base says: changed on neither side since, the chooser's (``KEPT_HERE``,
    ``KEPT_THERE``); else as usual."""
    found = []
    for unit_id in set(mine) | set(theirs):
        a, b = mine.get(unit_id), theirs.get(unit_id)
        if (a and a.digest) == (b and b.digest):
            continue
        label = (a or b).label
        was = None if base is None else base.get(unit_id)
        pair = None if kept is None else kept.get(unit_id)
        if pair is not None:
            proposal, why = _since_kept(a, b, pair)
        elif base is None:
            proposal, why = _first_time(a, b)
        else:
            a_changed = (a.digest if a else None) != was
            b_changed = (b.digest if b else None) != was
            if a_changed and not b_changed:
                proposal, why = MINE, _changed("here", a, was)
            elif b_changed and not a_changed:
                proposal, why = THEIRS, _changed("there", b, was)
            else:
                proposal, why = CONFLICT, "changed on both sides since the last sync"
        found.append(Difference(unit_id, label, a, b, proposal, why))
    return sorted(found, key=_order)


def _since_kept(a: Unit | None, b: Unit | None, pair: KeptPair) -> tuple[str, str]:
    was_here, was_there, chooser = pair
    a_changed = (a.digest if a else None) != was_here
    b_changed = (b.digest if b else None) != was_there
    if not a_changed and not b_changed:
        return (MINE, KEPT_HERE) if chooser == MINE else (THEIRS, KEPT_THERE)
    if a_changed and not b_changed:
        return MINE, _changed("here", a, was_here)
    if b_changed and not a_changed:
        return THEIRS, _changed("there", b, was_there)
    return CONFLICT, "changed on both sides since the last sync"


def _first_time(a: Unit | None, b: Unit | None) -> tuple[str, str]:
    if b is None:
        return MINE, "only here"
    if a is None:
        return THEIRS, "only there"
    return CONFLICT, "on both sides, different, and never synced"


def _changed(where: str, unit: Unit | None, was: str | None) -> str:
    if unit is None:
        return f"gone {where} since the last sync"
    if was is None:
        return f"new {where} since the last sync"
    return f"changed {where} since the last sync"


_KINDS = ("song", "removed", "songbook", "alias", "artist_url", "block")


def _order(item) -> tuple[int, str, str]:
    kind = item.id.partition("/")[0]
    return (_KINDS.index(kind) if kind in _KINDS else len(_KINDS), item.label.casefold(), item.id)


def decide(found: Sequence[Difference], prefer: str | None = None,
           choose: Callable[[Difference], str | None] | None = None) -> tuple[list[Difference], list[Difference]]:
    """Which differences this side takes (``THEIRS``) and which the peer takes (``MINE``): each as proposed, and each
    conflict as ``choose`` answers it (``MINE``, ``THEIRS``, or None to leave it), else as ``prefer`` says, else
    left. Return (taken here, taken there)."""
    here, there = [], []
    for d in found:
        side = d.proposal
        if side == CONFLICT:
            side = (choose(d) if choose is not None else None) or prefer
        if side == THEIRS:
            here.append(d)
        elif side == MINE:
            there.append(d)
    return here, there


def compared_hash(found: Iterable[Difference]) -> str:
    """What a comparison found, named: the SHA-256 of the canonical JSON of ``[[id, proposal, here, there], …]`` in
    ``_order`` (``here`` and ``there``, each side's digest, or None), so that the owner's choices, made on one
    comparison, are refused once a fresh one differs."""
    rows = [[d.id, d.proposal, d.mine.digest if d.mine else None, d.theirs.digest if d.theirs else None]
            for d in sorted(found, key=_order)]
    return hashlib.sha256(canonical.dumps(rows).encode("utf-8")).hexdigest()


# --- a sync's parts ---------------------------------------------------------------------------------------------

PARTS = ("library", "songbooks", "indexes")  # what a sync, or a file, may be of; no unit is of the indexes
_PART_OF = {"song": "library", "removed": "library", "alias": "library", "artist_url": "library",
            "block": "library", "songbook": "songbooks"}


def part_of(unit_id: str) -> str | None:
    """The part a unit is of, by its kind: ``"library"`` or ``"songbooks"``; None for a kind caracole doesn't know."""
    return _PART_OF.get(unit_id.partition("/")[0]) if "/" in unit_id else None


def listed_songs(books: Mapping[str, Any], units: Iterable[str]) -> dict[str, list[str]]:
    """The songs songbooks list: for each song unit of ``units`` an entry of a songbook of ``books`` (``{songbook
    unit: its value, {"name", "songs": [[text, parts], …]}}``, of either side) names by any cut of its "Artist -
    Title" (``songbook.entry_keys``), the songbook units listing it, sorted, each once. A songbook or an entry that
    isn't of that shape lists nothing."""
    from caracole.songbook import entry_keys

    held = set(units)
    listed: dict[str, set[str]] = {}
    for book_id, book in books.items():
        songs = book.get("songs") if isinstance(book, Mapping) else None
        if not isinstance(songs, list):
            continue
        for entry in songs:
            if not (isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[0], str)):
                continue
            for key in entry_keys(entry[0]):
                if f"song/{key}" in held:
                    listed.setdefault(f"song/{key}", set()).add(book_id)
    return {song: sorted(found) for song, found in sorted(listed.items())}


def in_scope(found: Sequence[Difference], parts: Iterable[str], *, listed: Mapping[str, Sequence[str]] | None = None,
             holds: Iterable[str] | None = None) -> list[Difference]:
    """The differences of ``found`` (in its order) a sync of ``parts`` is about: a unit of a part asked for, or a song
    a songbook lists (``listed``, ``listed_songs``'s) while the songbooks are. With ``holds``, the parts a file
    holds, a unit of a part it doesn't hold that the file lacks is left out: a file of the songbooks alone removes no
    song."""
    asked, listed = set(parts), listed or {}
    held = None if holds is None else set(holds)
    kept = []
    for d in found:
        part = part_of(d.id)
        if not (part in asked or d.id.startswith("song/") and "songbooks" in asked and d.id in listed):
            continue
        if held is not None and part not in held and d.theirs is None:
            continue
        kept.append(d)
    return kept


def change_of(d: Difference, base: Mapping[str, str | None] | None,
              kept: Mapping[str, KeptPair] | None = None) -> tuple[str | None, str | None]:
    """What each side did to ``d``'s unit since the base (or since the answer ``kept`` remembers for it), this
    side's then the other's: ``"new"``, ``"changed"``, ``"gone"``, or None for a side that didn't change it. With no
    base, a unit on one side alone is new there, and one on both changed on both."""
    here, there = (d.mine.digest if d.mine else None), (d.theirs.digest if d.theirs else None)
    pair = None if kept is None else kept.get(d.id)
    if pair is not None:
        return _change(here, pair[0]), _change(there, pair[1])
    if base is not None:
        was = base.get(d.id)
        return _change(here, was), _change(there, was)
    if here is not None and there is not None:
        return "changed", "changed"
    return ("new" if here is not None else None), ("new" if there is not None else None)


def _change(now: str | None, was: str | None) -> str | None:
    if now == was:
        return None
    if was is None:
        return "new"
    return "gone" if now is None else "changed"


def names_of(unit_id: str, label: str) -> tuple[str, str] | None:
    """A song unit's artist and title, read from its label ("Artist - Title"): the cut at a " - " whose
    ``normalize.identity_key`` is the unit's key (an artist's name may hold one: "Earth - Wind - Fire"), else the
    first; None for a label with no cut and for a unit of another kind."""
    from caracole.normalize import identity_key

    kind, _, key = unit_id.partition("/")
    parts = label.split(" - ")
    if kind != "song" or len(parts) < 2:
        return None
    cuts = [(" - ".join(parts[:i]), " - ".join(parts[i:])) for i in range(1, len(parts))]
    return next((cut for cut in cuts if identity_key(*cut) == key), cuts[0])


# --- the peer ----------------------------------------------------------------------------------------------------

STATE_PATH = "/api/peer/state"
UNIT_PATH = "/api/peer/unit"
FILE_PATH = "/api/peer/file"
PULL_PATH = "/peer/pull"
PEER_TIMEOUT = 60.0  # seconds: a phone's caracole reads every song of its library to answer


class PeerError(Exception):
    """The other caracole couldn't be asked, or answered with something else: what to tell the owner."""


class UnitSource(Protocol):
    """Where a take reads the units it takes and their songs' kept files: another caracole (``Peer``), or a push it
    sent, staged here."""

    def unit(self, unit_id: str) -> Mapping[str, Any] | None:
        """The unit's document, as ``unit_document``'s ``"unit"``; None when the source holds none."""

    def file(self, key: str, name: str, sha256: str) -> bytes:
        """A kept file of the song of ``key``, which the take checks against ``sha256``; an error (UnitError,
        PeerError, OSError) when the source can't give it."""


def peer_address(text: str) -> str:
    """The address of another ``caracole serve`` as typed (``192.168.1.20:8737``, ``http://phone.lan:8737/``), as
    caracole asks it: ``http://`` when no scheme is given, no trailing ``/``. PeerError for one that isn't."""
    from urllib.parse import urlsplit

    typed = text.strip()
    if "://" not in typed:
        typed = "http://" + typed
    try:
        parts = urlsplit(typed)
        parts.port  # noqa: B018 - a port that isn't a number raises ValueError
    except ValueError as e:
        raise PeerError(f"{text!r} isn't an address caracole can ask: {e}") from None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment or (
            parts.path not in ("", "/")):
        raise PeerError(f"{text!r} isn't the address of a caracole serve (http://HOST:PORT)")
    return typed.rstrip("/")


class Peer:
    """Another ``caracole serve``, asked over HTTP, one request at a time: its state, a unit, a file (a
    ``UnitSource``), and a pull of this side's units (``ask_to_pull``, a form posted as its pages post one).
    ``transport`` is httpx's, for tests."""

    def __init__(self, address: str, *, transport=None):
        import httpx

        self.address = address
        self._client = httpx.Client(transport=transport, timeout=PEER_TIMEOUT, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Peer:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: Mapping[str, str] | None = None):
        import httpx

        try:
            return self._client.get(self.address + path, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise PeerError(f"Nothing answered at {self.address}: {e}. Is caracole serve running there, on an "
                            "address this machine can reach (caracole serve --address 0.0.0.0)?") from None

    def _refused(self, response) -> PeerError:
        try:
            data = response.json()
        except ValueError:
            data = None
        said = data.get("error") if isinstance(data, dict) else None
        return PeerError(f"The caracole at {self.address} answered {response.status_code}"
                         + (f": {said}" if said else "."))

    def state(self, asking: str | None = None) -> PeerState:
        """Its ``state_document``, with its base for ``asking`` (this side's id)."""
        response = self._get(STATE_PATH, {"peer": asking} if asking else None)
        if response.status_code == 404:
            raise PeerError(f"{self.address} answered, but not as a caracole that syncs: is it an older caracole, "
                            "or something else?")
        if response.status_code != 200:
            raise self._refused(response)
        try:
            return read_state_document(response.json())
        except (ValueError, StateError) as e:
            raise PeerError(f"The caracole at {self.address} answered {e}.") from None

    def unit(self, unit_id: str) -> dict[str, Any] | None:
        """The unit's document (its ``unit_document``'s ``"unit"``), or None for a unit it hasn't got."""
        response = self._get(UNIT_PATH, {"id": unit_id})
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise self._refused(response)
        try:
            doc = response.json()
        except ValueError:
            doc = None
        if not (isinstance(doc, Mapping) and doc.get("format") == FORMAT and doc.get("id") == unit_id
                and isinstance(doc.get("digest"), str) and isinstance(doc.get("unit"), Mapping)):
            raise PeerError(f"The caracole at {self.address} answered {unit_id} with something it can't read.")
        return dict(doc["unit"])

    def file(self, key: str, name: str, sha256: str) -> bytes:
        """A kept file of its song of ``key``, checked against ``sha256``."""
        response = self._get(FILE_PATH, {"song": key, "name": name})
        if response.status_code != 200:
            raise self._refused(response)
        if hashlib.sha256(response.content).hexdigest() != sha256:
            raise PeerError(f"The caracole at {self.address} sent {name} other than it said it is: it changed "
                            "there since, so the song is left as it was here.")
        return response.content

    def ask_to_pull(self, here: str, units: Sequence[str], token: str) -> int:
        """Ask it to take ``units`` from this side, at ``here`` (an address it can reach): its form posted with its
        form token (``PeerState.token``), as its own page posts one; return the number of its job (0 unknown)."""
        import httpx

        try:
            response = self._client.post(
                self.address + PULL_PATH, data={"csrf": token, "from": here, "units": "\n".join(units)},
                headers={"Origin": self.address, "Sec-Fetch-Site": "same-origin", "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise PeerError(f"The caracole at {self.address} stopped answering: {e}") from None
        if response.status_code not in (200, 202):
            raise self._refused(response)
        try:
            job = response.json().get("job")
            return int(job.get("id") if isinstance(job, dict) else job)
        except (ValueError, TypeError, AttributeError):
            return 0


# --- taking units from the peer ----------------------------------------------------------------------------------


@dataclass
class Applied:
    """What ``apply_units`` did: the units taken, those left (with why), the songs whose files or names changed (to
    render again), by id; the songs respelled to the artist's spelling a song taken writes (their unit ids); whether
    songbooks.toml changed."""

    taken: list[str] = field(default_factory=list)
    left: list[tuple[str, str]] = field(default_factory=list)
    songs: set[int] = field(default_factory=set)
    songbooks: bool = False
    respelled: list[str] = field(default_factory=list)


class UnitError(Exception):
    """A unit that can't be taken: why, said to the owner; the rest go on."""


def apply_units(conn: sqlite3.Connection, cfg, source: UnitSource, wanted: Sequence[tuple[str, str | None]],
                now: str, *, expected_here: Mapping[str, str | None] | None = None,
                on_unit: Callable[[str, str, str], None] | None = None) -> Applied:
    """Take each of ``wanted`` (a unit's id and the source's digest of it when compared, None for a unit it hadn't
    got) from ``source``, under caracole's lock, which the caller holds; songs go first, then tombstones, songbooks
    and the rest. A unit is left, saying why, when its document no longer has the digest compared
    (``CHANGED_THERE``), when this side's digest of it differs from ``expected_here``'s (``CHANGED_HERE``: the
    digests this side had when compared, None for a unit it hadn't; a unit it doesn't name isn't checked), or when
    it can't be taken. ``on_unit(unit id, "taken" or "left", why)`` is told of each, as it is done."""
    from caracole.overrides import OverridesError
    from caracole.songbook import SongbookError

    done = Applied()
    here, unreadable = _digests_here(conn, cfg) if expected_here else ({}, None)
    for unit_id, digest in sorted(wanted, key=lambda w: (_KINDS.index(w[0].partition("/")[0])
                                                        if w[0].partition("/")[0] in _KINDS else 99, w[0])):
        try:
            if expected_here is not None and unit_id in expected_here:
                if unreadable is not None:
                    raise UnitError(unreadable)
                if here.get(unit_id) != expected_here[unit_id]:
                    raise UnitError(CHANGED_HERE)
            doc = source.unit(unit_id)
            if (None if doc is None else digest_of(value_of_document(unit_id, doc))) != digest:
                raise UnitError(CHANGED_THERE)
            try:
                _apply(conn, cfg, source, unit_id, doc, now, done)
            except (KeyError, TypeError, AttributeError) as e:
                # A document whose digest checks out may still lack what the take reads beyond its value (a file's
                # kept_rank, a tombstone's removed_at, a setting's parts): left, whole, as any unit that can't be.
                raise UnitError(f"its document can't be read ({type(e).__name__}: {e})") from e
        except (UnitError, PeerError, OverridesError, SongbookError, OSError, ValueError, sqlite3.IntegrityError) as e:
            done.left.append((unit_id, str(e)))
            if on_unit is not None:
                on_unit(unit_id, "left", str(e))
            continue
        done.taken.append(unit_id)
        if on_unit is not None:
            on_unit(unit_id, "taken", "")
    return done


def _digests_here(conn: sqlite3.Connection, cfg) -> tuple[dict[str, str], str | None]:
    """Each unit's digest on this side now, before the take changes any; or why this library can't be read."""
    from caracole.overrides import Overrides, OverridesError, load_overrides
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    try:
        overrides = load_overrides(cfg.overrides_file) if cfg.overrides_file.exists() else Overrides()
        books = load_songbooks(songbooks_file(cfg.library_dir))
    except (OverridesError, SongbookError) as e:
        return {}, f"this library can't be read: {e}"
    return {unit_id: unit.digest for unit_id, unit in library_state(conn, overrides, books).items()}, None


def _apply(conn, cfg, source: UnitSource, unit_id: str, doc: Mapping[str, Any] | None, now: str,
           done: Applied) -> None:
    from caracole import overrides as ov
    from caracole.songbook import SongbookSong, check_setting, put_songbook, songbooks_file
    from caracole.songs import find_song, forget_removed, removed_song

    kind, _, rest = unit_id.partition("/")
    if kind == "song":
        if doc is None:
            _remove_song(conn, cfg, rest, now)
        else:
            done.songs.add(_take_song(conn, cfg, source, rest, doc, now, done))
    elif kind == "removed":
        if doc is None:
            forget_removed(conn, rest)
        elif find_song(conn, rest) is None and removed_song(conn, rest) is None:
            conn.execute("INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?)",
                         (rest, str(doc["artist"]), str(doc["title"]),
                          json.dumps(doc.get("source_ids") or {}, ensure_ascii=False), str(doc["removed_at"])))
    elif kind == "songbook":
        songs = None
        if doc is not None:
            songs = [SongbookSong(str(text), check_setting(**dict(parts)) or None) for text, parts in doc["songs"]]
        name = str(doc["name"]) if doc is not None else _songbook_name(cfg, rest)
        if name is not None:
            put_songbook(songbooks_file(cfg.library_dir), name, songs)
            done.songbooks = True
    elif kind == "alias":
        ov.put_alias(cfg.overrides_file, rest, None if doc is None else [str(s) for s in doc["slugs"]])
    elif kind == "artist_url":
        ov.put_artist_url(cfg.overrides_file, rest, str(doc["name"]) if doc else rest,
                          None if doc is None else str(doc["page"]))
    elif kind == "block":
        tab = tab_of(rest)
        if tab is None:
            raise UnitError(f"{rest!r} isn't a tab's id")
        ov.put_block(cfg.overrides_file, tab, doc is not None)
    else:
        raise UnitError(f"this caracole doesn't know units of kind {kind!r}")


def _songbook_name(cfg, key: str) -> str | None:
    from caracole.songbook import load_songbooks, name_key, songbooks_file

    return next((b.name for b in load_songbooks(songbooks_file(cfg.library_dir)) if name_key(b.name) == key), None)


def _remove_song(conn, cfg, key: str, now: str) -> None:
    """The song the peer has no longer, removed here as ``caracole remove --yes`` removes it."""
    from caracole.removal import RemovalError, plan_removal, remove_song
    from caracole.songs import find_song

    song = find_song(conn, key)
    if song is None:
        return
    try:
        remove_song(conn, cfg, plan_removal(conn, cfg, song), now=_when(now))
    except RemovalError as e:
        raise UnitError(str(e)) from e


def _when(now: str) -> datetime:
    from caracole import stamps

    when = stamps.parse(now)
    if when is None:
        raise ValueError(f"not a time: {now!r}")
    return when


def checked_name(name: Any) -> str:
    """A kept file's name as a song's document gives it, when a song's folder can hold it: no ``/``, ``\\`` or NUL,
    nothing that starts with ``.``, not empty; else UnitError."""
    if (not isinstance(name, str) or "/" in name or "\\" in name or "\0" in name or name.startswith(".")
            or name in ("", "..")):
        raise UnitError(f"a kept file named {name!r}, which no song's folder holds")
    return name


def lyrics_files(lyrics_json: str | None) -> dict[str, bytes | None]:
    """The lyrics' files a song's folder holds for its ``lyrics_json``, as ``lyrics.write_lyrics`` writes them:
    ``lyrics.txt`` (the plain text) and ``lyrics.lrc`` (the timed one), each ending in a newline, or None for a file
    the lyrics have no text for, which goes; both None for no lyrics, or lyrics that can't be read."""
    from caracole.lyrics import lyrics_from_json

    try:
        lyrics = lyrics_from_json(lyrics_json)
    except (TypeError, ValueError):
        lyrics = None
    texts = {"lyrics.txt": lyrics.plain if lyrics is not None and lyrics.has_lyrics else None,
             "lyrics.lrc": lyrics.synced if lyrics is not None else None}
    return {name: (text.rstrip("\n") + "\n").encode("utf-8") if text else None for name, text in texts.items()}


def _names_of(doc: Mapping[str, Any], key: str) -> dict[str, Any]:
    """A song document's names, checked: they are the song of ``key``, as this caracole keys it."""
    from caracole.normalize import identity_key

    names = doc["names"]
    artist, title, artists = names.get("artist"), names.get("title"), names.get("artists")
    if not (isinstance(artist, str) and artist.strip() and isinstance(title, str) and isinstance(artists, list)
            and all(isinstance(a, str) for a in artists)):
        raise UnitError("its names can't be read")
    if identity_key(artist, title) != key:
        raise UnitError(f"its names, {artist} - {title}, are another song's here (caracole's versions differ?)")
    album, duration, variant = names.get("album"), names.get("duration_ms"), names.get("variant")
    if not ((album is None or isinstance(album, str)) and (duration is None or type(duration) is int)
            and (variant is None or isinstance(variant, str))):
        raise UnitError("its album, duration or variant can't be read")
    return {"artist": artist, "title": title, "artists": list(artists), "album": album, "duration_ms": duration,
            "variant": variant}


def _take_song(conn, cfg, source: UnitSource, key: str, doc: Mapping[str, Any], now: str, done: Applied) -> int:
    """The peer's song made this side's (see the module's docstring), whole or not at all; its id here."""
    from caracole.library import song_folder
    from caracole.overrides import put_song_entries
    from caracole.songs import find_song, forget_removed
    from caracole.wanted import sync_wanted

    names = _names_of(doc, key)
    here = find_song(conn, key)
    folder_here = cfg.library_dir.joinpath(*song_folder(here.artist, here.title)) if here is not None else None

    # Every file first, from the source, checked, before anything here changes: one it can't give leaves the song.
    files: dict[str, tuple[bytes | None, Mapping[str, Any]]] = {}
    for version in doc["versions"]:
        for f in version["files"]:
            name, sha = checked_name(f["name"]), str(f["sha256"])
            same = folder_here is not None and _same_file(folder_here / name, sha)
            files[name] = (None if same else _fetched(source, key, name, sha), f)
    lyrics = lyrics_files(doc["song"].get("lyrics_json"))
    before = set() if here is None else {
        name for (name,) in conn.execute("SELECT name FROM files WHERE song_id = ?", (here.id,))}
    respelled_here = here is not None and _respells(_to_respell(conn, names["artist"], key), here)
    new_parts = song_folder(names["artist"], names["title"])
    # Where the song's files are once its artist's folder is respelled, and those that go to its new folder if that
    # differs: caracole's, as they are now.
    current = None if here is None else song_folder(names["artist"] if respelled_here else here.artist, here.title)
    moving = _caracoles_files(conn, cfg, here) if here is not None and current != new_parts else ()
    for name, (data, f) in list(files.items()):
        if data is None and current != new_parts and name not in moving:  # the same bytes here, but staying behind
            files[name] = (_fetched(source, key, name, str(f["sha256"])), f)

    folders = _Folders(cfg.library_dir)
    undo_line: Callable[[], None] | None = None
    try:
        with savepoint(conn, "peer_take"):
            undo_line = _wanted_line(cfg, names, key)
            sync_wanted(conn, cfg.wanted_file, _when(now))
            song = find_song(conn, key)
            if song is None:
                raise UnitError("wanted.txt's line for it brought no song (an [ignore]d line?)")
            # Read once wanted.txt is synced, so that a song of the artist whose line was waiting is respelled too.
            respell = _to_respell(conn, names["artist"], key)
            if here is not None and _respells(respell, here) != respelled_here:
                raise UnitError("its artist's songs here changed while it was taken: compare again")
            respelled = _respell(conn, folders, respell, names["artist"], now)
            if current is not None and current != new_parts:
                folders.move_files(current, new_parts, moving)
                _drop_render_records(conn, song.id)
            folder = cfg.library_dir.joinpath(*new_parts)
            record = doc["song"]
            conn.execute(
                "UPDATE songs SET artist = ?, title = ?, artists = ?, album = ?, duration_ms = ?, variant = ?, "
                f"{', '.join(f'{c} = ?' for c in SONG_COLUMNS)}, updated_at = ? WHERE id = ?",
                (names["artist"], names["title"], json.dumps(names["artists"], ensure_ascii=False), names["album"],
                 names["duration_ms"], names["variant"], *[record.get(c) for c in SONG_COLUMNS], now, song.id))
            conn.execute("DELETE FROM versions WHERE song_id = ?", (song.id,))  # and their files' rows
            for version in doc["versions"]:
                cursor = conn.execute(
                    f"INSERT INTO versions (song_id, {', '.join(VERSION_COLUMNS)}) "
                    f"VALUES (?, {', '.join('?' for _ in VERSION_COLUMNS)})",
                    (song.id, *[version.get(c) for c in VERSION_COLUMNS]))
                for f in version["files"]:
                    conn.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) "
                                 "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 (cursor.lastrowid, song.id, f["name"],
                                  (folder / str(f["name"])).relative_to(cfg.library_dir).as_posix(), f["sha256"],
                                  f["kept_rank"], now))
            for prefix in CARRIED_KV:
                own = f"{prefix}{song.id}"
                conn.execute("DELETE FROM kv WHERE key = ? OR substr(key, 1, ?) = ?", (own, len(own) + 1, own + ":"))
            for carried, value in doc.get("kv", {}).items():
                prefix, _, more = str(carried).partition("|")
                if prefix in CARRIED_KV:
                    kv_set(conn, f"{prefix}{song.id}{more}", str(value))
            forget_removed(conn, key)
            # The files, as the rows now say: the peer's written, its lyrics', those it keeps no longer gone.
            for name, (data, _) in files.items():
                if data is not None:
                    folders.write(new_parts, name, data)
            for name, data in lyrics.items():
                if data is not None:
                    folders.write(new_parts, name, data)
                else:
                    folders.remove(new_parts, name)
            for name in sorted(before - set(files) - set(lyrics)):
                folders.remove(new_parts, name)
            put_song_entries(cfg.overrides_file, f"{names['artist']} - {names['title']}", doc["overrides"])
    except BaseException:
        folders.undo()
        if undo_line is not None:
            undo_line()
        raise
    folders.done()
    done.respelled += [f"song/{s.key}" for s in respelled if s.key != key]
    done.songs.update(s.id for s in respelled)
    return song.id


def _fetched(source: UnitSource, key: str, name: str, sha256: str) -> bytes:
    """A kept file of the song from ``source``, checked against ``sha256``."""
    data = source.file(key, name, sha256)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise UnitError(f"{name} came other than it is there: it changed there since, so the song is left as it was "
                        "here")
    return data


def _caracoles_files(conn, cfg, song) -> tuple[str, ...]:
    """The files caracole wrote in the song's folder (removal.py's reading of them: its kept files, what it made of
    them, its lyrics, info.json), which go with the song when its folder changes; UnitError for a folder caracole
    won't follow."""
    from caracole.removal import plan_removal

    plan = plan_removal(conn, cfg, song)
    if plan.folder_problem:
        raise UnitError(f"its folder can't be moved: {plan.folder_problem}")
    return plan.delete


def _to_respell(conn, artist: str, key: str) -> list:
    """The songs of the artist of ``key`` whose folder (``library.safe_name``) differs from ``artist``'s in case
    alone, when no song has ``artist``'s folder: each takes ``artist``'s spelling, so that the artist keeps one folder
    (as ``songs._artist_as_written`` gives a new song the library's spelling). Oldest first."""
    from caracole.library import safe_name
    from caracole.songs import get_song

    folder = safe_name(artist)
    side = key.split("/", 1)[0]
    rows = conn.execute("SELECT id, artist FROM songs WHERE key >= ? AND key < ? ORDER BY id",
                        (f"{side}/", f"{side}0")).fetchall()
    theirs = [(song_id, safe_name(other)) for song_id, other in rows]
    if any(name == folder for _, name in theirs):
        return []
    return [get_song(conn, song_id) for song_id, name in theirs if name.casefold() == folder.casefold()]


def _respells(songs: Sequence, song) -> bool:
    return any(s.id == song.id for s in songs)


def _respell(conn, folders: _Folders, songs: Sequence, artist: str, now: str) -> list:
    """``songs`` (``_to_respell``'s) written as ``artist``: their artist, and the first of their artists where it was
    the same; their artist's folder renamed to ``artist``'s once, their kept files' paths with it, and what caracole
    made of them to make again. Returns ``songs``."""
    from caracole.library import safe_name

    new = safe_name(artist)
    for old in sorted({safe_name(s.artist) for s in songs}):
        folders.move_folder(old, new)
    for song in songs:
        old = safe_name(song.artist)
        artists = list(song.artists)
        if artists and artists[0] == song.artist:
            artists[0] = artist
        conn.execute("UPDATE songs SET artist = ?, artists = ?, updated_at = ? WHERE id = ?",
                     (artist, json.dumps(artists, ensure_ascii=False), now, song.id))
        for file_id, path in conn.execute("SELECT id, path FROM files WHERE song_id = ? ORDER BY id",
                                          (song.id,)).fetchall():
            parts = PurePosixPath(path).parts
            if parts and parts[0] == old:
                conn.execute("UPDATE files SET path = ? WHERE id = ?", (PurePosixPath(new, *parts[1:]).as_posix(),
                                                                       file_id))
        _drop_render_records(conn, song.id)
    return list(songs)


def _drop_render_records(conn, song_id: int) -> None:
    """What render.py recorded of the song's PDFs and pages, which its next render makes again where the song is now
    (its exports' and progressions' records stay: their files moved with it, and their sheet is the same)."""
    own = f"render:{song_id}"
    conn.execute("DELETE FROM kv WHERE key = ? OR substr(key, 1, ?) = ? OR key = ?",
                 (own, len(own) + 1, own + ":", f"render:files:{song_id}"))


def _wanted_line(cfg, names: Mapping[str, Any], key: str) -> Callable[[], None] | None:
    """The song's line in wanted.txt as the peer's names say it (its lines taken out, one appended); what puts the
    file back as it was, or None when its line said so already. The file goes back byte for byte (none, if the take
    made it) while it reads as the take wrote it; else, written to since (``caracole serve`` appends without the
    lock), what was written since stays and the song's first line comes back at the end."""
    from caracole.library import read_regular, write_atomic
    from caracole.wanted import append_wanted, find_wanted, remove_wanted

    path = cfg.wanted_file
    artist, title, album, duration = names["artist"], names["title"], names["album"], names["duration_ms"]
    line = find_wanted(path, artist, title)
    if line is not None and (line.artist, line.title, line.album, line.duration_ms) == (artist, title, album, duration):
        return None
    try:
        before: bytes | None = read_regular(path)
    except FileNotFoundError:
        before = None
    if line is not None:
        remove_wanted(path, key)
    append_wanted(path, artist, title, album, duration)
    written = read_regular(path)

    def undo() -> None:
        try:
            if read_regular(path) == written:
                if before is None:
                    os.unlink(path)
                else:
                    write_atomic(path, before)
                return
            remove_wanted(path, key)
            if line is not None:
                append_wanted(path, line.artist, line.title, line.album, line.duration_ms)
        except (OSError, ValueError):
            pass

    return undo


def _same_file(path: Path, sha256: str) -> bool:
    from caracole.library import read_regular

    try:
        return hashlib.sha256(read_regular(path)).hexdigest() == sha256
    except (OSError, ValueError):
        return False


class _Folders:
    """The changes a take makes to the library's folders, each through descriptors opened from the library down with
    no link followed, and each undone, latest first, when the take fails (``undo``); ``done`` lets go of what they
    kept for that (a file a write replaced, a folder left empty). A file is written under a temporary name of its own
    first (``.<name>.<8 hex>.tmp``, which removal.py knows), then renamed into place."""

    def __init__(self, library_dir: Path):
        self.root = library_dir
        self._fds: dict[tuple[str, ...], int] = {}  # by the names the folders had when opened
        self._open: list[int] = []  # every descriptor, closed at the end alone: an undo step may need any
        self._undo: list[Callable[[], None]] = []
        self._done: list[Callable[[], None]] = []
        self._synced: set[int] = set()

    def _folder(self, parts: Sequence[str], *, make: bool = False) -> int | None:
        """The folder ``parts`` under the library, open; None when it isn't there (and isn't to be made)."""
        parts = tuple(parts)
        if parts in self._fds:
            return self._fds[parts]
        if not parts:
            if make:
                self.root.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            except FileNotFoundError:
                return None
        else:
            parent = self._folder(parts[:-1], make=make)
            if parent is None:
                return None
            name = parts[-1]
            try:
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                if not make:
                    return None
                os.mkdir(name, dir_fd=parent)
                self._undo.append(lambda: os.rmdir(name, dir_fd=parent))
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except OSError as e:
                raise UnitError(f"{'/'.join(parts)}/ is a symbolic link or no folder, which caracole doesn't "
                                "follow") from e
        self._open.append(fd)
        self._fds[parts] = fd
        return fd

    def _forget(self, prefix: tuple[str, ...]) -> None:
        """The folders under one renamed: found again by their new names (their descriptors stay open, for undo)."""
        for parts in [p for p in self._fds if p[:len(prefix)] == prefix]:
            del self._fds[parts]

    def _rename(self, src: int, src_name: str, dst: int, dst_name: str) -> None:
        os.rename(src_name, dst_name, src_dir_fd=src, dst_dir_fd=dst)
        self._undo.append(lambda: os.rename(dst_name, src_name, src_dir_fd=dst, dst_dir_fd=src))
        self._synced.update((src, dst))

    @staticmethod
    def _entry(folder: int, name: str) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=folder, follow_symlinks=False)
        except FileNotFoundError:
            return None

    @staticmethod
    def _temporary(name: str) -> str:
        return f".{name}.{secrets.token_hex(4)}.tmp"

    def move_folder(self, old: str, new: str) -> None:
        """The artist's folder ``old`` renamed ``new``, through a temporary name, so that a file system blind to case
        renames it too; into a folder ``new`` there is already, each folder of ``old``'s moved in."""
        root = self._folder(())
        if root is None or old == new:
            return
        held = self._entry(root, old)
        if held is None:
            return
        if not stat.S_ISDIR(held.st_mode):
            raise UnitError(f"{old}/ is a symbolic link or no folder, which caracole doesn't follow")
        there = self._entry(root, new)
        self._forget((old,))
        if there is None or os.path.samestat(held, there):
            temporary = self._temporary(new)
            self._rename(root, old, root, temporary)
            self._rename(root, temporary, root, new)
            return
        src, dst = self._folder((old,)), self._folder((new,))
        assert src is not None and dst is not None
        for name in sorted(os.listdir(src)):
            if self._entry(dst, name) is not None:
                raise UnitError(f"{new}/{name} is there already, so {old}/ can't be moved into it")
            self._rename(src, name, dst, name)
        self._done.append(lambda: self._prune(root, old))

    def move_files(self, old: Sequence[str], new: Sequence[str], names: Iterable[str]) -> None:
        """The files ``names`` of the song's folder ``old`` moved to its folder ``new``, one at a time, each a
        regular file (another is left where it is)."""
        src = self._folder(old)
        if src is None:
            return
        dst = self._folder(new, make=True)
        assert dst is not None
        for name in names:
            held = self._entry(src, name)
            if held is None or not stat.S_ISREG(held.st_mode):
                continue
            there = self._entry(dst, name)
            if there is not None:
                if os.path.samestat(held, there):
                    continue  # one folder by both names, on a file system blind to case
                raise UnitError(f"{'/'.join(new)}/{name} is there already")
            self._rename(src, name, dst, name)
        parent = self._folder(tuple(old)[:-1])
        if parent is not None:
            self._done.append(lambda: self._prune(parent, tuple(old)[-1], up=tuple(old)[:-1]))

    def write(self, parts: Sequence[str], name: str, data: bytes) -> None:
        """``data`` as the file ``name`` of the folder ``parts``, in place of a regular file there."""
        folder = self._folder(parts, make=True)
        assert folder is not None
        temporary = self._temporary(name)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666, dir_fd=folder)
        self._undo.append(lambda: self._unlink(folder, temporary))
        with open(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        self._aside(folder, name)
        self._rename(folder, temporary, folder, name)

    def remove(self, parts: Sequence[str], name: str) -> None:
        """The regular file ``name`` of the folder ``parts`` gone, if it is there."""
        folder = self._folder(parts)
        if folder is not None:
            self._aside(folder, name)

    def _aside(self, folder: int, name: str) -> None:
        """A regular file ``name`` renamed out of the way, deleted once the take is done; anything else there
        refused."""
        held = self._entry(folder, name)
        if held is None:
            return
        if not stat.S_ISREG(held.st_mode):
            raise UnitError(f"{name} there is no regular file, which caracole doesn't replace")
        aside = self._temporary(name)
        self._rename(folder, name, folder, aside)
        self._done.append(lambda: self._unlink(folder, aside))

    @staticmethod
    def _unlink(folder: int, name: str) -> None:
        try:
            if stat.S_ISREG(os.stat(name, dir_fd=folder, follow_symlinks=False).st_mode):
                os.unlink(name, dir_fd=folder)
        except FileNotFoundError:
            pass

    def _prune(self, parent: int, name: str, *, up: tuple[str, ...] = ()) -> None:
        """The folder ``name`` gone once empty, then its own folder (``up``) the same way."""
        try:
            os.rmdir(name, dir_fd=parent)
        except OSError:
            return
        if up:
            grand = self._folder(up[:-1])
            if grand is not None:
                self._prune(grand, up[-1])

    def undo(self) -> None:
        for step in reversed(self._undo):
            try:
                step()
            except OSError:
                pass
        self._close()

    def done(self) -> None:
        for fd in self._synced:
            try:
                os.fsync(fd)
            except OSError:
                pass
        for step in self._done:
            try:
                step()
            except OSError:
                pass
        self._close()

    def _close(self) -> None:
        for fd in self._open:
            os.close(fd)
        self._open.clear()
        self._fds.clear()
        self._undo.clear()
        self._done.clear()
        self._synced.clear()
