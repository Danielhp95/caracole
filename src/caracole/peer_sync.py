"""Two caracoles synced (``caracole peer``), unit by unit: what each library holds, which side each difference
comes from, and each side taking from the other what the owner chose.

The owner keeps a caracole on the computer and another on the phone, each with its own database and library, and
uses either alone (docs/superpowers/specs/2026-10-31-phone-server-sync-design.md). A sync shows what differs
between them, lets the owner choose, for each difference, which side keeps it, and then each side takes what it was
chosen to take: always a pull, the side that takes a unit asking the other for it.

**Units.** A library's state is cut into units, each compared and taken whole (``library_state``):

- ``song/<identity key>``: a song, by ``songs.key``: its names as its wanted.txt line gives them (artist, title,
  album, duration, variant), its record's decisions (status, review, the match, its lyrics: their status and a
  hash of their text), its versions (provider, tab, slot, kind, label, pick, gone, the URL, a hash of the raw
  record), its kept files (each name with its SHA-256: ``files``), and every overrides.toml entry about it
  (``overrides.SONG_TABLES``, ``[ignore]`` among them: ``overrides.song_entries``);
- ``removed/<identity key>``: a tombstone of ``caracole remove``;
- ``songbook/<name key>``: a songbook, its name and its songs in order, each with its setting;
- ``alias/<artist key>``, ``artist_url/<artist key>``, ``block/<tab id>``: overrides.toml's entries that are about
  an artist or a tab, not a song.

What caracole makes of a unit (PDFs, viewers, ``.cho``, info.json, the pages) is no part of it, nor what a lookup
would find again (cooldowns, a miss's date, the HTTP cache, the site indexes, which ``caracole index merge``
merges): a side that takes a song renders it again, so two caracoles of different versions agree on what a song is.
A unit's ``digest`` is the SHA-256 of its canonical JSON (``digest_of``); its ``label`` what the owner reads
("Eagles - Hotel California", "the songbook Campfire").

**Comparing** (``compare``) is three-way once the two have synced: for each unit, its digest when the two last held
it the same, the **base**. Each side keeps its own (kv ``sync:base:<peer id>``: each unit's digest, or None for a
unit both lacked, and when, ``record_agreement``), written at the end of every pull it makes; the other's comes
with its state (``GET /api/peer/state?peer=<id>``), and the later of the two counts (``merged_base``), so a unit
one side pushed to the other is known as synced on both, whichever side pulled. A unit only one side changed since
is that side's; a unit both changed, differently, a ``CONFLICT`` for the owner to settle; one both changed the same
way, or neither, no difference at all. With no base (the first sync), a unit on one side alone is that side's, and
one both hold, differently, a conflict.

**Taking** (``apply_units``) reads each chosen unit's document from the peer (``GET /api/peer/unit``) and refuses it
when it is no longer what was compared (its digest), then makes it this side's: a song through its wanted.txt line
(``songs.upsert_song``, by ``wanted.sync_wanted``, the one way a song is added), its record's decisions, its
versions and their kept files (each file asked for by name, ``GET /api/peer/file``, and checked by its SHA-256),
its lyrics' files, and its overrides.toml entries (``overrides.put_song_entries``); a song the peer has no longer,
removed here as ``caracole remove`` removes one; a tombstone, a songbook (``songbook.put_songbook``), an alias, an
artist's page or a blocked tab written or taken out. The caller holds caracole's lock, then renders the songs taken
and writes the pages (commands/peer.py).

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
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from caracole.db import kv_get, kv_get_json, kv_set, kv_set_json, savepoint

FORMAT = 1  # of every document a side answers: changes only with their shapes
ID_KEY = "sync:id"
BASE_KEY = "sync:base:"  # kv, then a peer's id: {unit: [digest or None, when]} as of the last time the two agreed

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
    """The SHA-256 of ``value``'s canonical JSON: keys sorted, no spaces, every character as it is."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_text(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _read_base(value: Any) -> Base | None:
    if not isinstance(value, Mapping):
        return None
    read: Base = {}
    for unit_id, entry in value.items():
        if (isinstance(entry, (list, tuple)) and len(entry) == 2 and (entry[0] is None or isinstance(entry[0], str))
                and isinstance(entry[1], str)):
            read[str(unit_id)] = (entry[0], entry[1])
    return read


def base_of(conn: sqlite3.Connection, peer: str) -> Base | None:
    """What this side last agreed on with ``peer``, unit by unit, or None if the two never synced."""
    return _read_base(kv_get_json(conn, BASE_KEY + peer))


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
    base names); the others keep what they had. Return how many were agreed."""
    base = base_of(conn, peer) or {}
    agreed = 0
    for unit_id in set(mine) | set(theirs) | set(base):
        a, b = mine.get(unit_id), theirs.get(unit_id)
        if a is not None and b is not None and a.digest == b.digest:
            base[unit_id] = (a.digest, at)
            agreed += 1
        elif a is None and b is None:
            base[unit_id] = (None, at)
    kv_set_json(conn, BASE_KEY + peer, {k: list(v) for k, v in sorted(base.items())})
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
         "gone": bool(gone), "url": url, "raw": _hash_text(raw)}
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
        "lyrics": [lyrics_status, _hash_text(lyrics_json)],
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
                   base: Base | None = None) -> dict[str, Any]:
    """``GET /api/peer/state``'s answer: who this side is, its units by id, and, for the peer that asked, what this
    side last agreed on with it (``base``, null if never)."""
    return {"format": FORMAT, "server": server, "caracole": version, "name": name,
            "units": {u.id: {"label": u.label, "digest": u.digest} for u in sorted(units.values(), key=_order)},
            "base": None if base is None else {k: list(v) for k, v in sorted(base.items())}}


@dataclass(frozen=True)
class PeerState:
    """A peer's ``state_document`` read back."""

    server: str | None
    version: str
    name: str
    units: dict[str, Unit]
    base: Base | None = None
    token: str | None = None  # its form token, which a pull's form posts (``Peer.ask_to_pull``)


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
    token = data.get("token")
    return PeerState(server, str(version or "?"), str(name or ""), read, _read_base(data.get("base")),
                     token if isinstance(token, str) and token else None)


def unit_document(conn: sqlite3.Connection, cfg, overrides, books: Iterable, unit_id: str) -> dict[str, Any] | None:
    """``GET /api/peer/unit``'s answer: everything another side needs to take the unit, with its digest as
    ``library_state`` gives it; None for a unit this side hasn't got."""
    from caracole.songbook import name_key
    from caracole.songs import find_song, removed_song

    kind, _, rest = unit_id.partition("/")
    value: Any
    doc: dict[str, Any]
    if kind == "song":
        song = find_song(conn, rest)
        if song is None:
            return None
        value = song_value(conn, song, overrides)
        doc = song_document(conn, song, value)
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
        if not rest.isdigit() or int(rest) not in overrides.block:
            return None
        value, doc = True, {"tab": int(rest)}
    else:
        return None
    return {"format": FORMAT, "id": unit_id, "digest": digest_of(value), "unit": doc}


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
            base: Mapping[str, str | None] | None) -> list[Difference]:
    """Every unit the two sides hold differently, with what the sync proposes for it (see the module's docstring),
    in ``_order``: songs first, by their label."""
    found = []
    for unit_id in set(mine) | set(theirs):
        a, b = mine.get(unit_id), theirs.get(unit_id)
        if (a and a.digest) == (b and b.digest):
            continue
        label = (a or b).label
        was = None if base is None else base.get(unit_id)
        if base is None:
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


# --- the peer ----------------------------------------------------------------------------------------------------

STATE_PATH = "/api/peer/state"
UNIT_PATH = "/api/peer/unit"
FILE_PATH = "/api/peer/file"
PULL_PATH = "/peer/pull"
PEER_TIMEOUT = 60.0  # seconds: a phone's caracole reads every song of its library to answer


class PeerError(Exception):
    """The other caracole couldn't be asked, or answered with something else: what to tell the owner."""


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
    """Another ``caracole serve``, asked over HTTP, one request at a time: its state, a unit, a file, and a pull of
    this side's units (``ask_to_pull``, a form posted as its pages post one). ``transport`` is httpx's, for tests."""

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
        """Its ``unit_document`` of ``unit_id``, or None for a unit it hasn't got."""
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
        return dict(doc)

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
    """What ``apply_units`` did: the units taken, those left (with why), and the songs whose files changed (to render
    again), by id; whether songbooks.toml changed."""

    taken: list[str] = field(default_factory=list)
    left: list[tuple[str, str]] = field(default_factory=list)
    songs: set[int] = field(default_factory=set)
    songbooks: bool = False


class UnitError(Exception):
    """A unit that can't be taken: why, said to the owner; the rest go on."""


def apply_units(conn: sqlite3.Connection, cfg, peer: Peer, wanted: Sequence[tuple[str, str | None]], now: str,
                *, on_unit: Callable[[str], None] | None = None) -> Applied:
    """Take each of ``wanted`` (a unit's id and the peer's digest of it when compared, None for a unit it hasn't got)
    from ``peer``, under caracole's lock, which the caller holds. A unit no longer as compared there, or one that
    can't be taken, is left, saying why; songs go first, then tombstones, songbooks and the rest."""
    from caracole.overrides import OverridesError
    from caracole.songbook import SongbookError

    done = Applied()
    for unit_id, digest in sorted(wanted, key=lambda w: (_KINDS.index(w[0].partition("/")[0])
                                                        if w[0].partition("/")[0] in _KINDS else 99, w[0])):
        if on_unit is not None:
            on_unit(unit_id)
        try:
            doc = peer.unit(unit_id) if digest is not None else None
            if digest is not None and (doc is None or doc["digest"] != digest):
                raise UnitError("it changed there since the comparison: compare again")
            if digest is None and peer.unit(unit_id) is not None:
                raise UnitError("it is there again since the comparison: compare again")
            _apply(conn, cfg, peer, unit_id, None if doc is None else doc["unit"], now, done)
        except (UnitError, PeerError, OverridesError, SongbookError, OSError, ValueError) as e:
            done.left.append((unit_id, str(e)))
            continue
        done.taken.append(unit_id)
    return done


def _apply(conn, cfg, peer: Peer, unit_id: str, doc: Mapping[str, Any] | None, now: str, done: Applied) -> None:
    from caracole import overrides as ov
    from caracole.songbook import SongbookSong, check_setting, put_songbook, songbooks_file
    from caracole.songs import find_song, forget_removed, removed_song

    kind, _, rest = unit_id.partition("/")
    if kind == "song":
        if doc is None:
            _remove_song(conn, cfg, rest, now)
        else:
            done.songs.add(_take_song(conn, cfg, peer, rest, doc, now))
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
        ov.put_block(cfg.overrides_file, int(rest), doc is not None)
    else:
        raise UnitError(f"this caracole doesn't know units of kind {kind!r}")


def _songbook_name(cfg, key: str) -> str | None:
    from caracole.songbook import load_songbooks, name_key, songbooks_file

    return next((b.name for b in load_songbooks(songbooks_file(cfg.library_dir)) if name_key(b.name) == key), None)


def _remove_song(conn, cfg, key: str, now: str) -> None:
    """The song the peer has no longer, removed here as ``caracole remove --yes`` removes it."""
    from datetime import datetime

    from caracole.removal import RemovalError, plan_removal, remove_song
    from caracole.songs import find_song

    song = find_song(conn, key)
    if song is None:
        return
    try:
        remove_song(conn, cfg, plan_removal(conn, cfg, song), now=datetime.fromisoformat(now.replace("Z", "+00:00")))
    except RemovalError as e:
        raise UnitError(str(e)) from e


def _take_song(conn, cfg, peer: Peer, key: str, doc: Mapping[str, Any], now: str) -> int:
    """The peer's song made this side's (see the module's docstring); its id here."""
    from datetime import datetime

    from caracole.library import song_dir, write_atomic
    from caracole.lyrics import lyrics_from_json, write_lyrics
    from caracole.normalize import identity_key
    from caracole.overrides import put_song_entries
    from caracole.songs import find_song
    from caracole.wanted import append_wanted, find_wanted, remove_wanted, sync_wanted

    names = doc["names"]
    artist, title = str(names["artist"]), str(names["title"])
    if identity_key(artist, title) != key:
        raise UnitError(f"its names, {artist} - {title}, are another song's here (caracole's versions differ?)")
    album = names.get("album")
    duration = names.get("duration_ms")

    # Every file first, from the peer, before anything here changes: a file it can't send leaves the song as it was.
    files: dict[str, tuple[bytes | None, Mapping[str, Any]]] = {}
    here = find_song(conn, key)
    folder = song_dir(cfg.library_dir, here) if here is not None else None
    for version in doc["versions"]:
        for f in version["files"]:
            name = str(f["name"])
            if "/" in name or "\\" in name or name.startswith(".") or name in ("", ".."):
                raise UnitError(f"a kept file named {name!r}, which no song's folder holds")
            same = folder is not None and _same_file(folder / name, str(f["sha256"]))
            files[name] = (None if same else peer.file(key, name, str(f["sha256"])), f)

    # Its line in wanted.txt, as the peer's says it: the song is added, or its line put right, by wanted.txt's sync.
    line = find_wanted(cfg.wanted_file, artist, title)
    if line is not None and (line.artist, line.title, line.album, line.duration_ms) != (artist, title, album, duration):
        remove_wanted(cfg.wanted_file, key)
    append_wanted(cfg.wanted_file, artist, title, album, duration)
    sync_wanted(conn, cfg.wanted_file, datetime.fromisoformat(now.replace("Z", "+00:00")))
    song = find_song(conn, key)
    if song is None:
        raise UnitError("wanted.txt's line for it brought no song (an [ignore]d line?)")
    folder = song_dir(cfg.library_dir, song)

    before = {name for (name,) in conn.execute("SELECT name FROM files WHERE song_id = ?", (song.id,))}
    for name, (data, _) in files.items():
        if data is not None:
            write_atomic(folder / name, data)
    with savepoint(conn, "peer_song"):
        record = doc["song"]
        conn.execute(f"UPDATE songs SET {', '.join(f'{c} = ?' for c in SONG_COLUMNS)}, updated_at = ? WHERE id = ?",
                     (*[record.get(c) for c in SONG_COLUMNS], now, song.id))
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
    for name in before - set(files):  # a file caracole kept here that the peer's song has no longer
        _unlink_regular(folder / name)

    lyrics = lyrics_from_json(doc["song"].get("lyrics_json"))
    if lyrics is not None:
        write_lyrics(folder, lyrics)
    else:
        for name in LYRICS_FILES:
            _unlink_regular(folder / name)
    put_song_entries(cfg.overrides_file, f"{artist} - {title}", doc["overrides"])
    return song.id


def _same_file(path: Path, sha256: str) -> bool:
    from caracole.library import read_regular

    try:
        return hashlib.sha256(read_regular(path)).hexdigest() == sha256
    except (OSError, ValueError):
        return False


def _unlink_regular(path: Path) -> None:
    """Delete ``path`` when it is a regular file: never a link followed, never a folder."""
    try:
        if stat.S_ISREG(os.lstat(path).st_mode):
            os.unlink(path)
    except FileNotFoundError:
        pass
