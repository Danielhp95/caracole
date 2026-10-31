"""Two caracoles compared (``caracole peer``), unit by unit: what each library holds, and which side each
difference comes from.

The owner keeps a caracole on the computer and another on the phone, each with its own database and library, and
uses either alone (docs/superpowers/specs/2026-10-31-phone-server-sync-design.md). A sync shows what differs
between them and lets the owner choose, for each difference, which side keeps it. This module is the comparison;
it reads alone, and writes nothing.

**Units.** A library's state is cut into units, each compared alone and, once applying comes, taken whole from one
side (``library_state``):

- ``song/<identity key>``: a song, by ``songs.key``: its names as its wanted.txt line gives them (artist, title,
  album, duration, variant), its record's decisions (status, review, the match, its lyrics: their status and a
  hash of their text), its versions (provider, tab, slot, kind, label, pick, gone, the URL, a hash of the raw
  record), its kept files (each name with its SHA-256: ``files``), and every overrides.toml entry about it
  (``SONG_TABLES``, ``[ignore]`` among them);
- ``removed/<identity key>``: a tombstone of ``caracole remove``, and when;
- ``songbook/<name key>``: a songbook, its name and its songs in order, each with its setting;
- ``alias/<artist key>``, ``artist_url/<artist key>``, ``block/<tab id>``: overrides.toml's entries that are about
  an artist or a tab, not a song.

What caracole makes of a unit (PDFs, viewers, ``.cho``, info.json, the pages) is no part of it, nor what a lookup
would find again (cooldowns, a miss's date, the HTTP cache, the site indexes, which ``caracole index merge``
merges): a side that takes a song renders it again, so two caracoles of different versions agree on what a song is.

A unit's ``digest`` is the SHA-256 of its canonical JSON (``digest_of``); its ``label`` what the owner reads
("Eagles - Hotel California", "the songbook Campfire").

**Comparing** (``compare``) is three-way when the two have synced before: each side kept the digest every unit had
then, its ``base`` (kv ``sync:base:<peer id>``, written once a sync applies, which comes in phase 2). A unit only one
side changed since is that side's; a unit both changed, differently, is a ``CONFLICT`` for the owner to settle; one
both changed the same way, or neither, no difference at all. With no base (the first sync), a unit on one side alone
is that side's, and one both hold, differently, a conflict.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from caracole.db import kv_get, kv_get_json, kv_set

FORMAT = 1  # of ``state_document``: changes only with its shape
ID_KEY = "sync:id"
BASE_KEY = "sync:base:"  # kv, then a peer's id: {unit: digest} as of the last sync with it

# The overrides.toml tables an entry of which is about one song, keyed by its identity key.
SONG_TABLES = ("match", "pin", "transpose", "reject", "youtube", "lacuerda", "harptabs", "gametabs", "azlyrics",
               "version", "harmonica")

# What a comparison proposes for a unit.
MINE = "mine"  # this side's: the peer takes it
THEIRS = "theirs"  # the peer's: this side takes it
CONFLICT = "conflict"  # both changed it, differently: the owner chooses


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


def own_id(conn: sqlite3.Connection) -> str | None:
    """This caracole's id among the ones it syncs with (kv ``sync:id``), or None before its first sync: read alone,
    as caracole serve reads the database (``make_id`` is a sync's, under caracole's lock)."""
    return kv_get(conn, ID_KEY) or None


def make_id(conn: sqlite3.Connection) -> str:
    """This caracole's id, made now if it has none."""
    found = own_id(conn)
    if found:
        return found
    made = secrets.token_hex(8)
    kv_set(conn, ID_KEY, made)
    return made


def base_of(conn: sqlite3.Connection, peer: str) -> dict[str, str] | None:
    """Each unit's digest as of the last sync with ``peer``, or None if the two never synced."""
    found = kv_get_json(conn, BASE_KEY + peer)
    if not isinstance(found, dict):
        return None
    return {str(k): str(v) for k, v in found.items() if isinstance(v, str)}


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
    for key, artist, title, removed_at in conn.execute("SELECT key, artist, title, removed_at FROM removed"):
        add(f"removed/{key}", f"{artist} - {title} (removed)", {"artist": artist, "title": title, "at": removed_at})
    for book in books:
        add(f"songbook/{name_key(book.name)}", f"the songbook {book.name}", songbook_value(book))
    for artist, slugs in overrides.alias.items():
        add(f"alias/{artist}", f"the alias of {artist}", list(slugs))
    for artist, page in overrides.artist_url.items():
        name = overrides.artist_url_names.get(artist, artist)
        add(f"artist_url/{artist}", f"the UG page of {name}", {"name": name, "page": page})
    for tab in sorted(overrides.block):
        add(f"block/{tab}", f"the blocked tab {tab}", True)
    return units


def song_value(conn: sqlite3.Connection, song, overrides) -> dict[str, Any]:
    """What a song unit is, as JSON: see the module's docstring. Nothing of it depends on the song's id here."""
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
        "names": {"artist": song.artist, "artists": list(song.artists), "title": song.title, "album": song.album,
                  "duration_ms": song.duration_ms, "variant": song.variant},
        "status": status,
        "review": bool(review),
        "match": [decision, match_artist, match_song],
        "lyrics": [lyrics_status, _hash_text(lyrics_json)],
        "versions": versions,
        "files": files,
        "overrides": song_overrides(overrides, song.key),
    }


def song_overrides(overrides, key: str) -> dict[str, Any]:
    """Every overrides.toml entry about the song of ``key``, as JSON, by table: only the tables that have one."""
    found: dict[str, Any] = {}
    for table in SONG_TABLES:
        entries: Mapping[str, Any] = getattr(overrides, table)
        if key not in entries:
            continue
        value = entries[key]
        if table == "pin":
            value = list(overrides.pin_urls.get(key, ()))
        elif table == "reject":
            value = sorted(list(pair) for pair in value)
        elif table in ("lacuerda", "harptabs", "gametabs"):
            value = value.url
        elif table == "match":
            value = list(value)
        elif table == "harmonica":
            value = {tab: dict(spec) if isinstance(spec, Mapping) else spec for tab, spec in value.items()}
        found[table] = value
    if key in overrides.ignore:
        found["ignore"] = True
    return found


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


# --- the document a side answers, and the comparison -------------------------------------------------------------


def state_document(server: str | None, version: str, name: str, units: Mapping[str, Unit]) -> dict[str, Any]:
    """``GET /api/peer/state``'s answer: who this side is (``server`` None before its first sync), and its units by
    id."""
    return {"format": FORMAT, "server": server, "caracole": version, "name": name,
            "units": {u.id: {"label": u.label, "digest": u.digest} for u in sorted(units.values(), key=_order)}}


class StateError(ValueError):
    """A peer's answer that isn't a sync state this caracole reads."""


def read_state_document(data: Any) -> tuple[str | None, str, str, dict[str, Unit]]:
    """A peer's ``state_document`` read back: its server id (None before its first sync), caracole version, library
    name and units. StateError for anything else."""
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
    return server, str(version or "?"), str(name or ""), read


def compare(mine: Mapping[str, Unit], theirs: Mapping[str, Unit],
            base: Mapping[str, str] | None) -> list[Difference]:
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


# --- the peer ----------------------------------------------------------------------------------------------------

STATE_PATH = "/api/peer/state"
PEER_TIMEOUT = 60.0  # seconds: a phone's caracole reads every song of its library to answer


class PeerError(Exception):
    """The other caracole couldn't be asked, or answered with no sync state: what to tell the owner."""


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
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise PeerError(f"{text!r} isn't the address of a caracole serve (http://HOST:PORT)")
    return typed.rstrip("/")


def read_peer(address: str, *, transport=None) -> tuple[str | None, str, str, dict[str, Unit]]:
    """The other caracole's sync state, ``read_state_document``'s parts, asked at ``address`` (``peer_address``'s):
    one request. PeerError when it can't be asked or answers with something else."""
    import httpx

    url = address + STATE_PATH
    try:
        with httpx.Client(transport=transport, timeout=PEER_TIMEOUT, follow_redirects=False) as client:
            response = client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise PeerError(f"Nothing answered at {address}: {e}. Is caracole serve running there, on an address this "
                        "machine can reach (caracole serve --address 0.0.0.0)?") from None
    if response.status_code == 404:
        raise PeerError(f"{address} answered, but not as a caracole that syncs: is it an older caracole, or "
                        "something else?")
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code != 200:
        said = data.get("error") if isinstance(data, dict) else None
        raise PeerError(f"The caracole at {address} answered {response.status_code}" + (f": {said}" if said else "."))
    try:
        return read_state_document(data)
    except StateError as e:
        raise PeerError(f"The caracole at {address} answered {e}.") from None
