"""The sync corpus, for the phone: what peer_sync.py answers (a library's units, their values, digests, labels and
documents; the three-way comparison and what it keeps; a take, rule by rule), the settings the computer gives the
phone (politeness.py), and how the library adds, removes and re-keys a song, over fixture libraries, written for the
Kotlin sync lanes (core/sync, core/library, core/config) to agree with.

**Fixtures** (``vectors/sync/fixtures/<name>.jsonl`` and ``vectors/library/fixtures/<name>.jsonl``,
helpers.corpus's format): each a library built with caracole's own writers (helpers/peer_libraries.py's ``Library``:
wanted.txt lines synced into songs, ``versions.upsert_version``, ``library.keep_file``, overrides.py's and
songbook.py's writers, ``removal.remove_song``), every stamp caracole writes as now made ``NOW``, then dumped
(``dump_fixture``) with its kept files. What the phone holds in place of overrides.toml and songbooks.toml is in the
fixture as the rows of its own tables (phone.sql): a ``phone_overrides`` row for each entry, ``{tbl, key, written,
value}`` (a song's table and its identity key, or ``alias`` and ``artist_url`` with the artist's key, or ``block``
with the tab id; ``written`` the name overrides.toml writes it under; ``value`` the canonical JSON of the value as
``overrides.song_entries`` gives it, the alias's slugs, the artist's page, ``true`` for a blocked tab or an
``[ignore]``d song), and a ``phone_songbooks`` row for each songbook, ``{key: songbook.name_key(name), name, songs:
the canonical JSON of songbook_value's "songs", position: its place in songbooks.toml, from 0}``. An artist's page is
its unit's value ``{name, page}`` split in two: ``written`` its name, ``value`` C(page) (OverridesStore.artistUrl puts
them together, putArtistUrl writes ``written`` from ``name``). Every answer below is
computed over the fixture replayed into a fresh database (``replay_fixture``), with the built library's
overrides.toml, songbooks.toml and wanted.txt beside it, never over the database it was built in:

- ``sync/fixtures/rich``: a unit of every kind and an entry of every overrides table (helpers/peer_libraries.py's
  ``rich``): two songs of one artist, a Chinese name and names beyond the BMP, tab ``101`` beside ``99``, kept files,
  lyrics, carried kv (``sheet_versions:yours:``, ``sheet_versions:same:``), a tombstone, a songbook with a setting, an
  alias, an artist's UG page, a blocked tab;
- ``sync/fixtures/dense``: every field of a song's value and document, and of a songbook's setting, that ``rich``
  leaves at its default, set (helpers/peer_libraries.py's ``dense``): an album, a duration, a variant, two artists, a
  match decided with a REAL score, a song in review, lyrics missing and instrumental, a version gone with a pick, a
  REAL coverage and a label, carried kv of every prefix, settings with a mode and an instrument; and raw records
  whose ratings and votes are no part of their hash (UG's own members) and are (within one, and LaCuerda's);
- ``sync/fixtures/plain``: a song with nothing kept and a song removed; ``sync/fixtures/empty``: nothing;
- ``sync/fixtures/take_<case>``: this side's library before each case of take.jsonl;
- ``library/fixtures/remove`` and ``library/fixtures/rekey``: the libraries remove.jsonl and ensure_current_keys.jsonl
  start from.

**Vectors**: a header, then a record a line, ``{fn, fixture, args, kw, out}`` (or ``err``, the exception's class),
``fixture`` the one whose replayed database the function reads (null for none):

- sync/values.jsonl: ``caracole.peer_sync.unit_value`` of each unit ``library_state`` lists, ``out`` ``{id, label,
  value, digest}``;
- sync/documents.jsonl: ``caracole.peer_sync.unit_document`` of each unit (and of ids no unit has: a song or a
  tombstone the library hasn't got, a blocked tab's id written otherwise than ASCII digits with no leading zero,
  ``peer_sync.tab_of``), and ``caracole.peer_sync.value_of_document`` of each document's ``unit`` (and of documents
  it refuses);
- sync/compare.jsonl: ``caracole.peer_sync.compare``, ``args`` ``[mine, theirs, base]`` (``{id: {id, label, digest}}``,
  and ``{id: digest or null}`` or null), ``out`` each difference ``{id, label, mine, theirs, proposal, why}`` in order;
  ``case`` names each row of the design's three-way table, first syncs, a unit appearing and going, the order;
- sync/merged_base.jsonl: ``caracole.peer_sync.merged_base`` (``{id: [digest or null, at]}`` or null, both sides);
- sync/record_agreement.jsonl: ``caracole.peer_sync.record_agreement`` with ``args`` ``[peer, mine, theirs, at]``
  over a database whose kv ``sync:base:<peer>`` holds ``before`` (a text, or null for none), ``out``
  ``{agreed, after}``, ``after`` that kv's text byte for byte;
- sync/decide.jsonl: ``caracole.peer_sync.decide``, ``args`` ``[found, prefer]``, ``kw.choose`` the side each conflict
  is chosen (``{id: side}``; a conflict it doesn't name: None), ``out`` ``{here: [id], there: [id]}``;
- sync/name_key.jsonl: ``caracole.songbook.name_key``;
- sync/compared_hash.jsonl: ``caracole.peer_sync.compared_hash`` of a list of differences (``args[0]``, as
  compare.jsonl writes them);
- sync/take.jsonl: ``caracole.peer_sync.apply_units`` for each case of the take (``case``), each showing one of
  §5.6's rules (``rule``, one of ``TAKE_RULES``), over ``fixture`` (this side before), ``args`` ``[wanted]`` (``[[id,
  the digest compared there or null]]``), ``kw`` ``{expected_here, now}``, ``source`` what the other side gives
  (``units``: each unit's document or null; ``files``: ``[{song, name, sha256, base64}]``, which a source answers by
  all three: one it lacks it can't give, and one whose bytes aren't its SHA-256's is refused by the take), ``out``
  ``{taken, left: [[id, why]], respelled, songbooks, songs, after, documents, ids, kv, paths, files}``: ``after`` this
  side's units then (``{id: {label, digest, value}}``), ``documents`` each song's ``unit_document`` then (the record's
  columns and the versions' beyond the value, the kept files' ranks, the carried kv), ``ids`` each song's id by its
  key, ``kv`` the ``render:`` and ``sheet_versions:`` rows (by those ids), ``paths`` its ``files.path`` rows,
  ``files`` every file of its song folders ``[[path, sha256]]``. A why is Python's words: those of the
  compare-and-swap (``peer_sync.CHANGED_HERE``, ``CHANGED_THERE``) are the phone's too, the others (SQLite's own
  message among them) say what a unit was left for;
- sync/checked_name.jsonl: ``caracole.peer_sync.checked_name``, a name kept or ``err`` ``UnitError``;
- sync/settings.jsonl: ``caracole.politeness.settings_document`` of a config, ``args`` ``[caracole.toml's text]``
  (read by ``config.load_config``), ``case`` its name (``SETTINGS``), ``out`` the document ``GET /api/peer/state``
  gives as ``settings``, and ``phone`` the phone's settings once it takes that document (``phone_settings``,
  made from the config, never the document: data/caracole/config/config.json's shape, its ``switchable`` aside, with
  ``name``), which ``PhoneConfig.read`` answers after ``PhoneConfig.take``;
- sync/settings_take.jsonl: the phone's take rule by rule (``SETTINGS_TAKES``, ``case``), what no caracole.toml can
  show: ``args`` ``[kept, settings]``, the kv ``phone:settings`` before (a document or null) and the state's
  ``settings`` (null: the state has none), ``out`` ``{kept, read}``, the kv after and what ``PhoneConfig.read``
  answers then (settings.jsonl's ``phone`` shape), of ``phone_takes``, the spec's rule as a model, which a test holds
  to settings.jsonl's ``phone`` on every document there;
- library/add.jsonl: ``caracole.songs.upsert_song`` as wanted.txt's sync calls it (``kw``), over a library ``before``
  (``songs``: ``[artist, title]`` added in order; ``removed``: tombstones), ``out`` ``{created, song, songs, removed}``;
- library/remove.jsonl: ``caracole.removal.remove_song`` of the song of ``args[0]``'s key over ``fixture``, ``out``
  the database after (the tombstone, the songs, versions, files and kv left) and the files deleted;
- library/lyrics_files.jsonl: ``caracole.peer_sync.lyrics_files``, each file's text or null;
- library/stamps.jsonl: ``caracole.stamps.parse``, ``out`` ``{iso, stamp}`` (``datetime.isoformat`` in UTC, and
  ``stamps.stamp``) or null;
- library/ensure_current_keys.jsonl: ``caracole.songs.ensure_current_keys`` over ``fixture``, whose keys record is
  older, ``out`` ``{count, songs, versions, files, removed, kv}`` after.

The generator's answers are the same under any hash seed (``test_the_corpus_is_the_same_whatever_the_hash_seed``).
Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from helpers.corpus import VECTORS, check, dump_fixture, jsonl, phone_schema, plain, read_fixture, replay_fixture
from helpers.peer_libraries import EVERY_ENTRY, NOW, Library, dense, rich

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
MADE_BY = "tests/test_conformance_sync.py"
SYNC = VECTORS / "sync"
LIBRARY = VECTORS / "library"
TOP_FILES = ("wanted.txt", "overrides.toml", "songbooks.toml")  # the computer's: the phone holds them as rows
SYNC_FILES = ("values", "documents", "compare", "merged_base", "record_agreement", "decide", "name_key",
              "compared_hash", "take", "checked_name", "settings", "settings_take")
LIBRARY_FILES = ("add", "remove", "lyrics_files", "stamps", "ensure_current_keys")


def canonical(value: Any) -> str:
    """C(v), as peer_sync hashes a unit's value."""
    from caracole import canonical

    return canonical.dumps(value)


# --- the fixtures ---------------------------------------------------------------------------------------------------


def _settled(conn) -> None:
    """Every stamp caracole writes as now, made ``NOW``: a fixture is the same on every run."""
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (NOW, NOW))
    conn.execute("UPDATE files SET created_at = ?", (NOW,))


def _written(path: Path) -> dict[str, dict[str, str]]:
    """The name each entry of overrides.toml is written under, by table and the key overrides.py reads it by."""
    from caracole.normalize import slug_key
    from caracole.overrides import override_key

    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    names: dict[str, dict[str, str]] = {}
    for table, entries in data.items():
        if not isinstance(entries, dict):
            continue
        if table == "ignore":
            songs = entries.get("songs", [])
            for song in [songs] if isinstance(songs, str) else songs:
                names.setdefault(table, {})[override_key(song)] = song
        elif table in ("alias", "artist_url"):
            for name in entries:
                names.setdefault(table, {})[slug_key(name)] = name
        elif table != "block":
            for name in entries:
                names.setdefault(table, {})[override_key(name)] = name
    return names


def phone_rows(lib: Library) -> list[tuple[str, dict[str, Any]]]:
    """overrides.toml's and songbooks.toml's entries as the phone's tables hold them (see the module's docstring)."""
    from caracole.overrides import SONG_TABLES, song_entries
    from caracole.songbook import name_key, songbooks_file

    overrides, written = lib.overrides(), _written(lib.cfg.overrides_file)
    rows: list[tuple[str, dict[str, Any]]] = []
    for (key,) in lib.conn.execute("SELECT key FROM songs ORDER BY id"):
        entries = song_entries(overrides, key)
        for table in (*SONG_TABLES, "ignore"):
            if table in entries:
                rows.append(("phone_overrides", {"tbl": table, "key": key, "written": written[table][key],
                                                 "value": canonical(entries[table])}))
    for artist, slugs in overrides.alias.items():
        rows.append(("phone_overrides", {"tbl": "alias", "key": artist, "written": written["alias"][artist],
                                         "value": canonical(list(slugs))}))
    for artist, page in overrides.artist_url.items():
        rows.append(("phone_overrides", {"tbl": "artist_url", "key": artist,
                                         "written": overrides.artist_url_names.get(artist, artist),
                                         "value": canonical(page)}))
    for tab in sorted(overrides.block):
        rows.append(("phone_overrides", {"tbl": "block", "key": str(tab), "written": str(tab),
                                         "value": canonical(True)}))
    if songbooks_file(lib.cfg.library_dir).exists():
        from caracole import peer_sync

        for position, book in enumerate(lib.books()):
            rows.append(("phone_songbooks", {"key": name_key(book.name), "name": book.name,
                                             "songs": canonical(peer_sync.songbook_value(book)["songs"]),
                                             "position": position}))
    return rows


def fixture_records(lib: Library) -> list[dict[str, Any]]:
    """The library as a fixture: its rows, the phone's rows of its overrides and songbooks, its kv, its kept files
    (not the computer's own files at the top of the library)."""
    _settled(lib.conn)
    phone_schema(lib.conn)
    for table, row in phone_rows(lib):
        lib.conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                         list(row.values()))
    records = dump_fixture(lib.conn, lib.cfg.library_dir)
    return [r for r in records if r.get("file") not in TOP_FILES]


def build_rich(lib: Library) -> None:
    from caracole.lyrics import Lyrics

    rich(lib)
    # Stored JSON as other writers write it, which the stored-JSON hash reads by its value: a non-integral number
    # (4.50, 1E2, -0.0), spaces and key order of its own; lyrics with a duration of 238.0.
    raw = '{ "votes":1E2, "rating" : 4.50, "b":[-0.0, 1e-7], "é":"\\u00e9"}'
    lib.conn.execute("UPDATE versions SET raw = ? WHERE tab_id = '99' AND song_id = (SELECT id FROM songs WHERE "
                     "key = 'radiohead/karma-police')", (raw,))
    lib.conn.execute("UPDATE songs SET lyrics_json = ? WHERE key = '宋冬野/斑马斑马'", (Lyrics(
        plain="斑马，斑马", synced=None, instrumental=False, duration=238.0, lrclib_id=7).to_json(),))


def build_dense(lib: Library) -> None:
    from caracole.versions import upsert_version

    dense(lib)
    # A version's raw is hashed without what VOLATILE_RAW names for its provider alone (FORMAT 3): UG's ratings and
    # votes, its own members, never one within them; another site's whole.
    live = lib.conn.execute("SELECT id FROM songs WHERE title LIKE 'De Música Ligera%'").fetchone()[0]
    upsert_version(lib.conn, provider="lacuerda", tab_id="soda_stereo/de_musica_ligera", song_id=live, slot="sheet",
                   kind="acordes", rating=0, votes=0, version=1, label=None, url="https://acordes.lacuerda.net/x",
                   raw={"lcd": "soda_stereo", "rating": 4.5, "votes": 3}, now=NOW)
    upsert_version(lib.conn, provider="ug", tab_id="303", song_id=live, slot="sheet", kind="chords", rating=4.0,
                   votes=2, version=1, label=None, url="https://u/303",
                   raw={"votes": 2, "meta": {"rating": 4.0, "votes": 2}, "rating": 4.0}, now=NOW)


def build_plain(lib: Library) -> None:
    lib.song("Soda Stereo", "De Música Ligera", sheet=None, lyrics=None)
    lib.removed("Oasis", "Wonderwall")


def build_empty(lib: Library) -> None:
    pass


# --- the take's cases: this side before, the other side, the units taken ----------------------------------------------


CREEP, KARMA = "song/radiohead/creep", "song/radiohead/karma-police"
SURPRISES = "song/radiohead/no-surprises"
WONDERWALL = "removed/oasis/wonderwall"


def _no_sheet_name(doc: dict) -> dict:
    doc["versions"][0]["files"][0]["name"] = "../sheet.txt"
    return doc


def _bad_slot(doc: dict) -> dict:
    doc["versions"][0]["slot"] = "nonsense"  # the schema's CHECK refuses it: sqlite3.IntegrityError
    return doc


def _no_kept_rank(doc: dict) -> dict:
    del doc["versions"][0]["files"][0]["kept_rank"]  # beyond the value: its digest checks out
    return doc


def _no_removed_at(doc: dict) -> dict:
    del doc["removed_at"]
    return doc


def _unknown_table(doc: dict) -> dict:
    doc["overrides"]["nonsense"] = 1  # no table overrides.toml has: put_song_entries refuses it
    return doc


def _without(name: str) -> Callable[[list[dict]], list[dict]]:
    """The source's files, ``name`` not among them: the other side can't give it."""
    return lambda files: [f for f in files if f["name"] != name]


def _other_bytes(name: str) -> Callable[[list[dict]], list[dict]]:
    """The source's files, ``name`` given with other bytes than its SHA-256 says."""
    return lambda files: [{**f, "base64": base64.b64encode(b"changed in transit").decode("ascii")}
                          if f["name"] == name else f for f in files]


def _rendered(lib: Library, artist: str, title: str, **kw) -> None:
    """A song, with what render.py records of it: its sheet's record, its Traditional PDF's and its pages' (which a
    take that moves its folder drops), its export's and its progressions' (which stay)."""
    from caracole.db import kv_set

    song = lib.song(artist, title, **kw)
    for key in (f"render:{song.id}", f"render:{song.id}:trad", f"render:files:{song.id}",
                f"render:export:{song.id}", f"render:progressions:{song.id}"):
        kv_set(lib.conn, key, '{"made": true}')


def _new_there(lib: Library) -> None:
    """A song with an entry of every table, a file beyond its sheet and carried kv of every prefix, after another
    song, so that its id there is not the one it gets here: its kv taken under its id here."""
    from caracole.db import kv_set

    lib.song("Oasis", "Wonderwall")
    creep = lib.song("Radiohead", "Creep", entries=EVERY_ENTRY, files={"tab.txt": b"e|--0--|"})
    kv_set(lib.conn, f"sheet_versions:yours:{creep.id}", "[101]")
    kv_set(lib.conn, f"sheet_versions:unkeepable:{creep.id}", "[7]")
    kv_set(lib.conn, f"sheet_versions:same:{creep.id}:101", "99")


def _co_artists(lib: Library) -> None:
    """Two songs of one artist, each with a second artist: first, and second."""
    from caracole.songs import update_song

    karma = lib.song("radiohead", "Karma Police", sheet=b"[Em]Karma")
    update_song(lib.conn, karma.id, artists=["radiohead", "Thom Yorke"])
    surprises = lib.song("radiohead", "No Surprises", sheet=b"[F]No alarms")
    update_song(lib.conn, surprises.id, artists=["Thom Yorke", "radiohead"])


class Take(NamedTuple):
    """A take's case: the §5.6 rule it shows (``TAKE_RULES``) and how; this side's library before and the other's;
    the units taken; the documents changed on their way; the units whose digest here, or there, the comparison had
    otherwise (a compare-and-swap); what the other side gives of its files."""

    rule: str
    shows: str
    here: Callable[[Library], Any]
    there: Callable[[Library], Any]
    ids: Sequence[str]
    changed: Mapping[str, Callable[[dict], dict]] = {}
    stale_here: Sequence[str] = ()
    stale_there: Sequence[str] = ()
    files: Callable[[list[dict]], list[dict]] | None = None


# §5.6's rules, each shown by one take or more (``test_every_rule_of_the_take_is_in_the_vectors``).
TAKE_RULES = (
    "names: the peer's written verbatim",
    "respelling: artist, and artists[0] where it was the artist, one folder renamed once",
    "folders: files and files.path move, the old folder's render records dropped",
    "file names: one no song's folder holds refused",
    "tombstones: a song taken forgets this side's",
    "a song new here: through the one way songs are added, then the peer's",
    "a song absent there: removed by remove_song's rules",
    "a removed unit: a tombstone made only where neither the song nor one is",
    "an absent removed unit: the tombstone forgotten",
    "whole or nothing: files fetched and checked before any change",
    "whole or nothing: the rows, the carried kv and the overrides entries together",
    "whole or nothing: IntegrityError per unit",
    "whole or nothing: a document the take can't read left",
    "files no longer kept: deleted",
    "compare and swap: changed here",
    "compare and swap: changed there",
    "songbooks, aliases, artists' pages and blocked tabs: put and dropped",
)
R = dict(enumerate(TAKE_RULES))

TAKES: dict[str, Take] = {
    "names_as_written": Take(
        R[0], "the peer's names written as it writes them, its folder with them",
        lambda h: h.song("radiohead", "creep"), lambda t: t.song("Radiohead", "Creep"), [CREEP]),
    "respelling": Take(
        R[1], "an artist written in another case alone: every song of theirs respelled, one folder renamed once",
        lambda h: (_rendered(h, "radiohead", "Karma Police", sheet=b"[Em]Karma"),
                   h.song("radiohead", "No Surprises", sheet=b"[F]No alarms")),
        lambda t: t.song("Radiohead", "Creep"), [CREEP]),
    "co_artists": Take(
        R[1], "a respelled song's artists: the first takes the spelling where it was the artist, never another",
        _co_artists, lambda t: t.song("Radiohead", "Creep"), [CREEP]),
    "folder_moved": Take(
        R[2], "a song whose folder changes: its files moved, files.path with them, its render records dropped",
        lambda h: _rendered(h, "Soda Stereo", "De Musica Ligera", files={"tab.txt": b"e|--3--|"}),
        lambda t: t.song("Soda Stereo", "De Música Ligera", files={"tab.txt": b"e|--3--|"}),
        ["song/soda-stereo/de-musica-ligera"]),
    "refused_name": Take(
        R[3], "a kept file named what no song's folder holds: the song left",
        lambda h: None, lambda t: t.song("Radiohead", "Creep"), [CREEP], {CREEP: _no_sheet_name}),
    "tombstone_forgotten": Take(
        R[4], "removed here, changed there, resolved there: the song taken forgets this side's tombstone",
        lambda h: h.removed("Radiohead", "Creep"), lambda t: t.song("Radiohead", "Creep", sheet=b"[G]changed"),
        [CREEP]),
    "new_here": Take(
        R[5], "a song new here, made through the one way songs are added, then the peer's",
        lambda h: None, _new_there, [CREEP]),
    "absent_there": Take(
        R[6], "a song the peer has no longer: removed here, its tombstone left",
        lambda h: h.song("Radiohead", "Creep"), lambda t: None, [CREEP]),
    "tombstone_made": Take(
        R[7], "a removed unit taken where neither the song nor a tombstone is: a tombstone made",
        lambda h: None, lambda t: t.removed("Oasis", "Wonderwall"), [WONDERWALL]),
    "tombstone_beside_a_song": Take(
        R[7], "a removed unit taken where the song is: no tombstone made",
        lambda h: h.song("Oasis", "Wonderwall"), lambda t: t.removed("Oasis", "Wonderwall"), [WONDERWALL]),
    "tombstone_dropped": Take(
        R[8], "a removed unit the peer has no longer: the tombstone forgotten",
        lambda h: h.tombstone("Oasis", "Wonderwall"), lambda t: None, [WONDERWALL]),
    "file_not_given": Take(
        R[9], "a kept file the other side can't give: the song left as it was here, the sheet it gave unwritten",
        lambda h: h.song("Radiohead", "Creep", sheet=b"[Am]mine"),
        lambda t: t.song("Radiohead", "Creep", sheet=b"[G]theirs", files={"tab.txt": b"e|--0--|"}), [CREEP],
        files=_without("tab.txt")),
    "file_other_sha": Take(
        R[9], "a kept file given other than its SHA-256 says: the song left as it was here",
        lambda h: h.song("Radiohead", "Creep", sheet=b"[Am]mine"),
        lambda t: t.song("Radiohead", "Creep", sheet=b"[G]theirs", files={"tab.txt": b"e|--0--|"}), [CREEP],
        files=_other_bytes("tab.txt")),
    "overrides_refused": Take(
        R[10], "overrides entries the library refuses: the song's rows, kv and files as they were here",
        lambda h: h.song("Radiohead", "Creep", sheet=b"[Am]mine"),
        lambda t: t.song("Radiohead", "Creep", sheet=b"[G]theirs"), [CREEP], {CREEP: _unknown_table}),
    "whole_or_nothing": Take(
        R[11], "a song the database refuses (IntegrityError) left whole, the other taken",
        lambda h: None, lambda t: (t.song("Radiohead", "Creep"), t.song("Radiohead", "Karma Police")),
        [CREEP, KARMA], {CREEP: _bad_slot}),
    "document_unreadable": Take(
        R[12], "a document that lacks what the take reads beyond its value (a file's kept_rank, a tombstone's "
        "removed_at): left, the others taken",
        lambda h: None,
        lambda t: (t.song("Radiohead", "Creep"), t.song("Radiohead", "Karma Police"), t.removed("Oasis", "Wonderwall")),
        [CREEP, KARMA, WONDERWALL], {CREEP: _no_kept_rank, WONDERWALL: _no_removed_at}),
    "file_dropped": Take(
        R[13], "a file kept here that the peer's song keeps no longer: deleted, its row with it",
        lambda h: h.song("Radiohead", "Creep", files={"guitar-1.gp5": b"FICHIER GUITAR PRO v5.00"}),
        lambda t: t.song("Radiohead", "Creep"), [CREEP]),
    "changed_here": Take(
        R[14], "the compare-and-swap: a unit changed here since the comparison left",
        lambda h: h.song("Radiohead", "Creep", sheet=b"[Am]mine"), lambda t: t.song("Radiohead", "Creep"), [CREEP],
        stale_here=(CREEP,)),
    "changed_there": Take(
        R[15], "the compare-and-swap: a unit changed there since the comparison left",
        lambda h: h.song("Radiohead", "Creep", sheet=b"[Am]mine"), lambda t: t.song("Radiohead", "Creep"), [CREEP],
        stale_there=(CREEP,)),
    "entries": Take(
        R[16], "a songbook, an alias, an artist's page and a blocked tab put, and those the peer hasn't got dropped",
        lambda h: (h.songbook("Old", ["A - B"]), _entries(h, "Oasis", 77)),
        lambda t: (t.songbook("Campfire", ["Radiohead - Creep"]), _entries(t, "Soda", 4242)),
        ["songbook/campfire", "songbook/old", "alias/soda", "alias/oasis", "artist_url/soda", "artist_url/oasis",
         "block/4242", "block/77"]),
}


def _entries(lib: Library, artist: str, tab: int) -> None:
    from caracole.overrides import add_alias, add_artist_url, add_block

    add_alias(lib.cfg.overrides_file, artist, f"{artist.lower()}-ug")
    add_artist_url(lib.cfg.overrides_file, artist, f"https://www.ultimate-guitar.com/artist/{artist.lower()}_{tab}")
    add_block(lib.cfg.overrides_file, tab)


FIXTURES: dict[str, Callable[[Library], None]] = {
    "rich": build_rich, "dense": build_dense, "plain": build_plain, "empty": build_empty,
    **{f"take_{name}": case.here for name, case in TAKES.items()},
}


# --- the library's own: remove and re-key --------------------------------------------------------------------------


def build_remove(lib: Library) -> None:
    from caracole.db import kv_set
    from caracole.songs import _PER_SONG_KV

    creep = lib.song("Radiohead", "Creep", files={"tab.txt": b"e|--0--|"})
    karma = lib.song("Radiohead", "Karma Police")
    for prefix in _PER_SONG_KV:  # every prefix of the song's kv, and the next song's, which stays
        for song in (creep, karma):
            kv_set(lib.conn, f"{prefix}{song.id}", "{}")
            kv_set(lib.conn, f"{prefix}{song.id}:more", "{}")
    kv_set(lib.conn, f"render:{creep.id}0", "{}")  # another song's id that starts with this one's
    lib.tombstone("Oasis", "Wonderwall", at="2026-10-01T00:00:00Z")
    lib.song("Oasis", "Wonderwall", sheet=None, lyrics=None)  # asked for again since: its tombstone gone
    # Left by a re-keying: a second removal of the key adds its source ids to it, at the later time.
    lib.tombstone("Radiohead", "Creep", at="2026-10-01T00:00:00Z", source_ids={"wanted": ["radiohead/creep-old"]})


REMOVALS = (("song/radiohead/creep", "a song with its files, kv of every prefix, an older tombstone of its key"),
            ("song/radiohead/karma-police", "a song beside another of its artist"),
            ("song/oasis/wonderwall", "a song asked for again after its removal"))


def build_rekey(lib: Library) -> None:
    from caracole.db import kv_set
    from caracole.songs import KEY_VERSION_KV

    soda = lib.song("Soda Stereo", "De Música Ligera")
    live = lib.song("Soda Stereo", "Persiana Americana", sheet=b"[E]live", tab="7")
    lib.song("Radiohead", "Creep", sheet=None)
    # As an older normalizer keyed them: the first two as two songs that are one now, the third alone.
    lib.conn.execute("UPDATE songs SET key = 'soda stereo/de musica ligera' WHERE id = ?", (soda.id,))
    lib.conn.execute("UPDATE songs SET key = 'soda stereo/de música ligera', title = 'De Música Ligera' "
                     "WHERE id = ?", (live.id,))
    lib.conn.execute("UPDATE songs SET key = 'Radiohead/Creep' WHERE key = 'radiohead/creep'")
    # Two tombstones an older normalizer keyed apart, one now: their source ids together, the later time.
    for old, at in (("Oasis/Wonderwall", "2026-10-03T00:00:00Z"), ("oasis/wonder wall", "2026-10-05T00:00:00Z")):
        lib.conn.execute("INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?)",
                         (old, "Oasis", "Wonderwall", json.dumps({"wanted": [old], "other": ["x"]}), at))
    lib.conn.execute("INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?)",
                     ("blur/song 2", "Blur", "Song 2", "{}", "2026-10-04T00:00:00Z"))
    kv_set(lib.conn, "wanted:first_seen:soda stereo/de musica ligera", "2026-10-02T00:00:00Z")
    kv_set(lib.conn, KEY_VERSION_KV, "0")


LIBRARY_FIXTURES: dict[str, Callable[[Library], None]] = {"remove": build_remove, "rekey": build_rekey}


# --- building and replaying ----------------------------------------------------------------------------------------


class Corpus:
    """The fixtures, built and replayed in ``workdir``, and the vectors' records made over them."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self._built: dict[tuple[str, str], Library] = {}
        self._texts: dict[tuple[str, str], str] = {}
        self._replayed: dict[tuple[str, str, str], Library] = {}
        self._records: dict[str, list[dict]] = {}
        self.libraries: list[Library] = []

    def close(self) -> None:
        for lib in self.libraries:
            lib.close()

    def library(self, where: str) -> Library:
        lib = Library(self.workdir / where)
        self.libraries.append(lib)
        return lib

    def built(self, area: str, name: str) -> Library:
        if (area, name) not in self._built:
            lib = self.library(f"built/{area}/{name}")
            (FIXTURES if area == "sync" else LIBRARY_FIXTURES)[name](lib)
            records = fixture_records(lib)
            self._built[area, name] = lib
            self._texts[area, name] = jsonl(records, corpus=f"{area}/fixtures/{name}", made_by=MADE_BY)
        return self._built[area, name]

    def records(self, name: str) -> list[dict]:
        """The records of the vector ``name`` (``MAKERS``), made once."""
        if name not in self._records:
            self._records[name] = MAKERS[name](self)
        return self._records[name]

    def fixture_text(self, area: str, name: str) -> str:
        self.built(area, name)
        return self._texts[area, name]

    def replayed(self, area: str, name: str, tag: str = "") -> Library:
        """A fresh library holding the fixture replayed, with the built one's overrides.toml, songbooks.toml and
        wanted.txt beside it; once for each ``tag``."""
        if (area, name, tag) in self._replayed:
            return self._replayed[area, name, tag]
        built = self.built(area, name)
        lib = self.library(f"replayed/{area}/{name}{tag}")
        self._replayed[area, name, tag] = lib
        replay_fixture(lib.conn, read_fixture(self.fixture_text(area, name)), lib.cfg.library_dir)
        for top in TOP_FILES:
            if (built.cfg.library_dir / top).exists():
                lib.cfg.library_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(built.cfg.library_dir / top, lib.cfg.library_dir / top)
        return lib


def record(fn: str, fixture: str | None, args: Sequence[Any], kw: dict[str, Any], call: Callable[[], Any],
           **extra: Any) -> dict:
    try:
        return {"fn": fn, "fixture": fixture, "args": list(args), "kw": kw, "out": plain(call()), **extra}
    except Exception as e:  # noqa: BLE001 (an exception is an answer too)
        return {"fn": fn, "fixture": fixture, "args": list(args), "kw": kw, "err": type(e).__name__, **extra}


SYNC_FIXTURES = ("rich", "dense", "plain", "empty")


def value_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync

    out = []
    for name in SYNC_FIXTURES:
        lib = corpus.replayed("sync", name)
        overrides, books = lib.overrides(), lib.books()
        for unit_id, unit in sorted(lib.units().items()):
            value = sync.unit_value(lib.conn, overrides, books, unit_id)
            out.append(record("caracole.peer_sync.unit_value", name, [unit_id], {}, lambda: {
                "id": unit_id, "label": unit.label, "value": value, "digest": unit.digest}))
    return out


def document_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync

    out = []
    for name in SYNC_FIXTURES:
        lib = corpus.replayed("sync", name)
        # and ids no unit has: a block's tab written otherwise than library_state writes it (4242 is rich's)
        for unit_id in [*sorted(lib.units()), "song/nobody/here", "removed/nobody/here", "block/1", "block/04242",
                        "block/٤٢٤٢", "block/+4242", "block/4242 ", "block/", "nonsense/x"]:
            doc = lib.document(unit_id)
            out.append(record("caracole.peer_sync.unit_document", name, [unit_id], {}, lambda: doc))
            if doc is not None:
                out.append(record("caracole.peer_sync.value_of_document", None, [unit_id, doc["unit"]], {},
                                  lambda: sync.value_of_document(unit_id, doc["unit"])))
    for unit_id, doc in (("song/a/b", None), ("song/a/b", {"names": {}}), ("song/a/b", []), ("removed/a/b", {}),
                         ("removed/a/b", {"artist": 1, "title": "b"}), ("songbook/x", {"name": "x", "songs": [1]}),
                         ("alias/x", {"slugs": "x"}), ("block/1", {"tab": "1"}), ("block/1", {"tab": True}),
                         ("artist_url/x", {"name": "x"}), ("nonsense/x", {})):
        out.append(record("caracole.peer_sync.value_of_document", None, [unit_id, doc], {},
                          lambda: sync.value_of_document(unit_id, doc)))
    return out


def _u(unit_id: str, digest: str, label: str | None = None):
    from caracole import peer_sync as sync

    return sync.Unit(unit_id, label if label is not None else unit_id.partition("/")[2], digest)


def _units(*units) -> dict:
    return {u.id: u for u in units}


def compare_cases() -> list[tuple[str, dict, dict, dict | None]]:
    """(case, mine, theirs, base): every row of the design's three-way table, first syncs, a unit appearing and
    going, both sides making one change, 'removed here, changed there', and the order."""
    k = "radiohead/creep"
    return [
        ("same on both, as agreed: nothing", _units(_u("song/a", "0")), _units(_u("song/a", "0")), {"song/a": "0"}),
        ("changed here alone: mine", _units(_u("song/a", "1")), _units(_u("song/a", "0")), {"song/a": "0"}),
        ("changed there alone: theirs", _units(_u("song/a", "0")), _units(_u("song/a", "2")), {"song/a": "0"}),
        ("both changed, the same way: nothing", _units(_u("song/a", "1")), _units(_u("song/a", "1")),
         {"song/a": "0"}),
        ("both changed, differently: a conflict", _units(_u("song/a", "1")), _units(_u("song/a", "2")),
         {"song/a": "0"}),
        ("new here since", _units(_u("song/a", "1")), {}, {}),
        ("new there since", {}, _units(_u("song/a", "1")), {}),
        ("new here since, agreed absent", _units(_u("song/a", "1")), {}, {"song/a": None}),
        ("gone here since", {}, _units(_u("song/a", "0")), {"song/a": "0"}),
        ("gone there since", _units(_u("song/a", "0")), {}, {"song/a": "0"}),
        ("gone on both: nothing", {}, {}, {"song/a": "0"}),
        ("gone here, changed there: a conflict", {}, _units(_u("song/a", "2")), {"song/a": "0"}),
        ("new on both, differently, since: a conflict", _units(_u("song/a", "1")), _units(_u("song/a", "2")), {}),
        ("never synced: only here, only there, on both and different, on both the same",
         _units(_u("song/a", "1"), _u("song/b", "2"), _u("song/same", "3")),
         _units(_u("song/c", "4"), _u("song/b", "5"), _u("song/same", "3")), None),
        ("never synced: nothing on either side", {}, {}, None),
        ("removed here, changed there: the song a conflict, its tombstone mine",
         _units(_u(f"removed/{k}", "t", "Radiohead - Creep (removed)")),
         _units(_u(f"song/{k}", "2", "Radiohead - Creep")), {f"song/{k}": "1"}),
        ("one change on each side, of different units", _units(_u("song/a", "1"), _u("song/b", "0")),
         _units(_u("song/a", "0"), _u("song/b", "2")), {"song/a": "0", "song/b": "0"}),
        ("the order: songs by label, any case, then removals, songbooks, aliases, pages, blocks, unknown kinds",
         _units(_u("block/2", "1", "the blocked tab 2"), _u("artist_url/x", "1", "the UG page of x"),
                _u("alias/x", "1", "the alias of x"), _u("songbook/x", "1", "the songbook X"),
                _u("removed/z/z", "1", "Zed - Zed (removed)"), _u("song/b/b", "1", "beta - B"),
                _u("song/a/a", "1", "Alpha - A"), _u("song/c/c", "1", "alpha - a"), _u("other/x", "1", "x"),
                _u("song/é/é", "1", "Émile - É"), _u("song/z/z", "1", "zeta - Z")),
         {}, None),
        ("the label is this side's when both have the unit",
         _units(_u("song/a", "1", "here's name")), _units(_u("song/a", "2", "there's name")), None),
    ]


def compare_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync

    return [record("caracole.peer_sync.compare", None, [mine, theirs, base], {},
                   lambda: sync.compare(mine, theirs, base), case=case)
            for case, mine, theirs, base in compare_cases()]


def merged_base_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync

    early, late = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"
    cases = [
        ("neither side has one", None, None),
        ("only theirs", None, {"song/a": ("1", early)}),
        ("only mine", {"song/a": ("1", early)}, None),
        ("an empty one", None, {}),
        ("the later agreement wins", {"song/a": ("1", early), "song/b": ("1", late)},
         {"song/a": ("2", late), "song/b": ("3", early), "song/c": (None, early)}),
        ("a tie is mine", {"song/a": ("1", early)}, {"song/a": ("2", early)}),
        ("stamps compared as text", {"song/a": ("1", "2026-10-01T00:00:00+00:00")}, {"song/a": ("2", early)}),
    ]
    return [record("caracole.peer_sync.merged_base", None, [mine, theirs], {},
                   lambda: sync.merged_base(mine, theirs), case=case) for case, mine, theirs in cases]


def record_agreement_records(corpus: Corpus) -> list[dict]:
    from caracole import db
    from caracole import peer_sync as sync

    at = "2026-10-31T00:00:00Z"
    tagged = json.dumps({"format": sync.FORMAT, "units": {"song/gone": ["x", "2026-10-01T00:00:00Z"],
                                                          "song/differs": ["y", "2026-10-01T00:00:00Z"],
                                                          "song/ü": ["z", "2026-10-01T00:00:00Z"]}}, ensure_ascii=False)
    cases = [
        ("no base before", None, _units(_u("song/a", "1"), _u("song/b", "2")), _units(_u("song/a", "1"))),
        ("a base before: what both hold the same and what both lack agreed, the rest kept", tagged,
         _units(_u("song/same", "1"), _u("song/differs", "2"), _u("song/ü", "z")),
         _units(_u("song/same", "1"), _u("song/differs", "3"), _u("song/ü", "z"))),
        ("an untagged base before is none", json.dumps({"song/old": ["x", "2026-10-01T00:00:00Z"]}),
         _units(_u("song/a", "1")), _units(_u("song/a", "1"))),
        ("a base of FORMAT 2, whose digests hashed UG's ratings, is none",
         json.dumps({"format": 2, "units": {"song/old": ["x", "2026-10-01T00:00:00Z"]}}),
         _units(_u("song/a", "1")), _units(_u("song/a", "1"))),
        ("a base that isn't JSON is none", "{nonsense", {}, {}),
        ("keys in code-point order: a supplementary letter after U+FF61",
         None, _units(_u("song/\U0001f600", "1"), _u("song/｡", "2"), _u("song/a", "3")),
         _units(_u("song/\U0001f600", "1"), _u("song/｡", "2"), _u("song/a", "3"))),
    ]
    out = []
    lib = corpus.library("record_agreement")
    for case, before, mine, theirs in cases:
        key = sync.BASE_KEY + "peer"
        lib.conn.execute("DELETE FROM kv WHERE key = ?", (key,))
        if before is not None:
            db.kv_set(lib.conn, key, before)
        agreed = sync.record_agreement(lib.conn, "peer", mine, theirs, at)
        out.append({"fn": "caracole.peer_sync.record_agreement", "fixture": None, "args": ["peer", plain(mine),
                    plain(theirs), at], "kw": {}, "before": before, "case": case,
                    "out": {"agreed": agreed, "after": db.kv_get(lib.conn, key)}})
    return out


def _diff(unit_id: str, proposal: str, mine: str | None = None, theirs: str | None = None, label: str | None = None):
    from caracole import peer_sync as sync

    label = label if label is not None else unit_id
    return sync.Difference(unit_id, label, _u(unit_id, mine, label) if mine else None,
                           _u(unit_id, theirs, label) if theirs else None, proposal, "")


def decide_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync

    found = [_diff("song/a", "mine", "1"), _diff("song/b", "theirs", None, "2"), _diff("song/c", "conflict", "1", "2"),
             _diff("song/d", "conflict", "1", "2"), _diff("song/e", "conflict", None, "2")]
    cases = [("each as proposed, a conflict left", None, {}),
             ("a conflict as chosen, the others as preferred", "theirs", {"song/c": "mine"}),
             ("every conflict as preferred", "mine", {}),
             ("a conflict chosen with none preferred", None, {"song/d": "theirs", "song/e": "mine"}),
             ("a proposal isn't turned by a choice", None, {"song/a": "theirs"})]
    out = []
    for case, prefer, chosen in cases:
        here, there = sync.decide(found, prefer, lambda d, chosen=chosen: chosen.get(d.id))
        out.append({"fn": "caracole.peer_sync.decide", "fixture": None, "args": [plain(found), prefer],
                    "kw": {"choose": chosen}, "case": case,
                    "out": {"here": [d.id for d in here], "there": [d.id for d in there]}})
    return out


def name_key_records(corpus: Corpus) -> list[dict]:
    from caracole.songbook import name_key

    names = ["Campfire", "campfire", "  Camp   fire  ", "Camp\tfire\n", "Camp fire", "Camp fire",
             "Camp　fire", "Camp\x1cfire", "Camp\x85fire", "Camp​fire", "Straße", "STRASSE", "İstanbul",
             "istanbul", "ı", "Café", "Café", "é", "é", "ﬁre", "Ǆ", "ǅ", "Σίσυφος", "ΣΊΣΥΦΟΣ",
             "篝火", "𝔉ire", "\U0001f525 Fire", "", "   ", "KK", "Ⅻ"]
    return [record("caracole.songbook.name_key", None, [name], {}, lambda: name_key(name)) for name in names]


def compared_hash_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync

    lists = [[], [_diff("song/b", "mine", "1"), _diff("song/a", "conflict", "2", "3")],
             [_diff("removed/a/b", "mine", "1", None, "A - B (removed)"),
              _diff("song/a/b", "conflict", None, "2", "A - B")],
             [_diff("song/\U0001f600", "theirs", None, "9", "😀"), _diff("song/｡", "theirs", None, "8", "｡")],
             [_diff("block/1", "mine", "1", None, "the blocked tab 1"), _diff("song/x", "mine", "1", None, "X")]]
    return [record("caracole.peer_sync.compared_hash", None, [plain(found)], {},
                   lambda: sync.compared_hash(found)) for found in lists]


class InlineSource:
    """A UnitSource of a record's documents and files, as the phone's test reads them."""

    def __init__(self, units: dict[str, Any], files: list[dict[str, str]]):
        self.units, self.files = units, files

    def unit(self, unit_id: str):
        doc = self.units.get(unit_id)
        return None if doc is None else json.loads(json.dumps(doc))

    def file(self, key: str, name: str, sha256: str) -> bytes:
        from caracole.peer_sync import UnitError

        for f in self.files:
            if (f["song"], f["name"], f["sha256"]) == (key, name, sha256):
                return base64.b64decode(f["base64"])
        raise UnitError(f"{name}: there, no such file is kept")


def _song_files(lib: Library) -> list[list[str]]:
    """Every file of the library's song folders, by path, with its SHA-256."""
    root = lib.cfg.library_dir
    if not root.exists():
        return []
    return [[p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()]
            for p in sorted(root.rglob("*")) if p.is_file() and p.parent != root]


def take_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync

    out = []
    for name, case in TAKES.items():
        there = corpus.library(f"there/{name}")
        case.there(there)
        here = corpus.replayed("sync", f"take_{name}")
        units = {}
        files = []
        for unit_id in case.ids:
            doc = there.document(unit_id)
            unit = None if doc is None else doc["unit"]
            if unit is not None and unit_id in case.changed:
                unit = case.changed[unit_id](unit)
            units[unit_id] = unit
            if unit is not None and unit_id.startswith("song/"):
                for version in unit["versions"]:
                    for f in version["files"]:
                        data = sync.song_file(there.conn, there.cfg.library_dir, unit["key"], f["name"]) \
                            if not f["name"].startswith(".") else None
                        if data is not None:
                            files.append({"song": unit["key"], "name": f["name"], "sha256": f["sha256"],
                                          "base64": base64.b64encode(data).decode("ascii")})
        if case.files is not None:
            files = case.files(files)
        before = here.digests()
        wanted = [[u, None if units[u] is None else sync.digest_of(sync.value_of_document(u, units[u]))]
                  for u in case.ids]
        wanted = [[u, "stale" if u in case.stale_there else d] for u, d in wanted]
        expected = {u: "stale" if u in case.stale_here else before.get(u) for u in case.ids}
        done = sync.apply_units(here.conn, here.cfg, InlineSource(units, files), [tuple(w) for w in wanted], NOW,
                                expected_here=expected)
        overrides, books = here.overrides(), here.books()
        after = {u: {"label": unit.label, "digest": unit.digest,
                     "value": sync.unit_value(here.conn, overrides, books, u)}
                 for u, unit in sorted(here.units().items())}
        out.append({"fn": "caracole.peer_sync.apply_units", "fixture": f"take_{name}", "case": name,
                    "rule": case.rule, "note": case.shows,
                    "args": [wanted], "kw": {"expected_here": expected, "now": NOW},
                    "source": {"units": units, "files": files},
                    "out": plain({"taken": done.taken, "left": [list(x) for x in done.left],
                                  "respelled": done.respelled, "songbooks": done.songbooks,
                                  "songs": sorted(done.songs), "after": after,
                                  "documents": {u: here.document(u)["unit"] for u in after if u.startswith("song/")},
                                  "ids": {key: song_id for song_id, key in here.conn.execute(
                                      "SELECT id, key FROM songs ORDER BY id")},
                                  "kv": [list(r) for r in here.conn.execute(
                                      "SELECT key, value FROM kv WHERE substr(key, 1, 7) = 'render:' "
                                      "OR substr(key, 1, 15) = 'sheet_versions:' ORDER BY key")],
                                  "paths": [p for (p,) in here.conn.execute("SELECT path FROM files ORDER BY path")],
                                  "files": _song_files(here)})})
    return out


CHECKED_NAMES = ["sheet.txt", "sheet (auto).txt", "guitar-1.gp5", "斑马.txt", "𝄞.txt", "trailing.", " spaced ",
                 "a..b", "...x", "../x", "a/b", "a\\b", ".hidden", ".", "..", "", "x\0y", "CON", 5, None, ["a"]]


def checked_name_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync

    return [record("caracole.peer_sync.checked_name", None, [name], {}, lambda name=name: sync.checked_name(name))
            for name in CHECKED_NAMES]


# --- the library's vectors ------------------------------------------------------------------------------------------


ADDS: list[tuple[str, list, list[dict], dict]] = [
    ("a new song", [], [], {"artists": ["Radiohead"], "title": "Creep"}),
    ("names stripped", [], [], {"artists": ["  Radiohead "], "title": "  Creep\t"}),
    ("an empty artist left out of its artists", [], [], {"artists": ["", "  ", "Radiohead"], "title": "Creep"}),
    ("its artists, the first the primary", [], [], {"artists": ["Shakira", "Wyclef Jean"], "title": "Hips Don't Lie"}),
    ("a title's variant", [], [], {"artists": ["Soda Stereo"], "title": "De Música Ligera (Live)"}),
    ("an album and a duration", [], [], {"artists": ["Radiohead"], "title": "Creep", "album": "Pablo Honey",
                                         "duration_ms": 238000}),
    ("an artist the library writes in another case: its spelling", [["radiohead", "Karma Police"]], [],
     {"artists": ["Radiohead"], "title": "Creep"}),
    ("an artist the library writes as given: as given", [["Radiohead", "Karma Police"]], [],
     {"artists": ["Radiohead"], "title": "Creep"}),
    ("another artist's songs: as given", [["radiohead fans", "Creep"]], [],
     {"artists": ["Radiohead"], "title": "Creep"}),
    ("the oldest song's spelling of the artist", [["RADIOHEAD", "Karma Police"], ["radiohead", "No Surprises"]], [],
     {"artists": ["Radiohead"], "title": "Creep"}),
    ("a song of that key found, its names kept", [["Radiohead", "Creep"]], [],
     {"artists": ["radiohead"], "title": "creep"}),
    ("a song found takes its line's album and duration", [["Radiohead", "Creep"]], [],
     {"artists": ["Radiohead"], "title": "Creep", "album": "Pablo Honey", "duration_ms": 238000}),
    ("a tombstone of its key dropped",
     [], [{"key": "radiohead/creep", "artist": "Radiohead", "title": "Creep", "source_ids": {"wanted": [
         "radiohead/creep"]}, "removed_at": "2026-10-01T00:00:00Z"}], {"artists": ["Radiohead"], "title": "Creep"}),
    ("a tombstone of its source id dropped",
     [], [{"key": "radiohead/creep-old", "artist": "Radiohead", "title": "Creep (old)", "source_ids": {"wanted": [
         "radiohead/creep"]}, "removed_at": "2026-10-01T00:00:00Z"}], {"artists": ["Radiohead"], "title": "Creep"}),
    ("another song's tombstone kept",
     [], [{"key": "oasis/wonderwall", "artist": "Oasis", "title": "Wonderwall", "source_ids": {},
           "removed_at": "2026-10-01T00:00:00Z"}], {"artists": ["Radiohead"], "title": "Creep"}),
    ("Chinese, found as one with its punctuation", [["宋冬野", "斑马，斑马"]], [], {"artists": ["宋冬野"], "title": "斑马斑马"}),
    ("Traditional characters, keyed as Simplified", [], [], {"artists": ["宋冬野"], "title": "斑馬，斑馬"}),
    ("beyond the BMP", [], [], {"artists": ["Bad 🎸 Band"], "title": "Riff 𝄞"}),
    ("no artist", [], [], {"artists": ["  "], "title": "Creep"}),
]


def add_records(corpus: Corpus) -> list[dict]:
    from caracole.normalize import identity_key
    from caracole.songs import get_song, list_removed, upsert_song

    out = []
    for n, (case, songs, removed, call) in enumerate(ADDS):
        lib = corpus.library(f"add/{n}")
        for artist, title in songs:
            upsert_song(lib.conn, artists=[artist], title=title, album=None, duration_ms=None, isrc=None,
                        source="wanted", source_id=identity_key(artist, title), added_at="2026-10-01T00:00:00Z")
        for stone in removed:
            lib.conn.execute("INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?)",
                             (stone["key"], stone["artist"], stone["title"], json.dumps(stone["source_ids"]),
                              stone["removed_at"]))
        names = [a.strip() for a in call["artists"] if a.strip()]
        kw = {"album": None, "duration_ms": None, "isrc": None, "source": "wanted", "added_at": NOW, **call,
              "source_id": identity_key(names[0], call["title"].strip()) if names else ""}

        def add(kw=kw, lib=lib):
            song_id, created = upsert_song(lib.conn, **kw)
            song = get_song(lib.conn, song_id)
            return {"created": created,
                    "song": {f: getattr(song, f) for f in ("key", "artist", "title", "artists", "album", "duration_ms",
                                                          "isrc", "variant", "source_ids", "added_at", "status",
                                                          "match_candidates", "review", "ug_dirty", "lyrics_status")},
                    "songs": [[r[0], r[1], r[2]] for r in lib.conn.execute(
                        "SELECT key, artist, title FROM songs ORDER BY id")],
                    "removed": [s.key for s in list_removed(lib.conn)]}

        before = {"songs": songs, "removed": removed}
        out.append(record("caracole.songs.upsert_song", None, [], kw, add, case=case, before=before))
    return out


def remove_records(corpus: Corpus) -> list[dict]:
    from caracole.removal import plan_removal, remove_song
    from caracole.songs import find_song
    from helpers.peer_libraries import WHEN

    out = []
    for unit_id, case in REMOVALS:
        key = unit_id.partition("/")[2]
        lib = corpus.replayed("library", "remove", tag=f"-{key.replace('/', '-')}")

        def remove(lib=lib, key=key):
            song = find_song(lib.conn, key)
            result = remove_song(lib.conn, lib.cfg, plan_removal(lib.conn, lib.cfg, song), now=WHEN)
            stone = lib.conn.execute("SELECT key, artist, title, source_ids, removed_at FROM removed WHERE key = ?",
                                     (key,)).fetchone()
            return {"removed": dict(zip(("key", "artist", "title", "source_ids", "removed_at"), stone)),
                    "tombstones": [r[0] for r in lib.conn.execute("SELECT key FROM removed ORDER BY key")],
                    "songs": [r[0] for r in lib.conn.execute("SELECT key FROM songs ORDER BY id")],
                    "versions": [list(r) for r in lib.conn.execute(
                        "SELECT song_id, provider, tab_id FROM versions ORDER BY id")],
                    "files": [r[0] for r in lib.conn.execute("SELECT path FROM files ORDER BY id")],
                    "kv": [r[0] for r in lib.conn.execute("SELECT key FROM kv WHERE key != 'sync:id' ORDER BY key")],
                    "deleted": sorted(result.deleted), "folder_gone": result.folder_gone}

        out.append(record("caracole.removal.remove_song", "remove", [key], {"now": NOW}, remove, case=case))
    return out


def lyrics_records(corpus: Corpus) -> list[dict]:
    from caracole import peer_sync as sync
    from caracole.lyrics import Lyrics

    def stored(**kw) -> str:
        made = {"plain": "", "synced": None, "instrumental": False, "duration": None, "lrclib_id": None, **kw}
        return Lyrics(**made).to_json()

    texts = [None, stored(plain="I'm a creep"), stored(plain="I'm a creep\n\n\n"),
             stored(plain="line one\nline two", synced="[00:01.00] line one\n[00:02.00] line two\n"),
             stored(plain="", instrumental=True), stored(plain="   \n", synced="[00:01.00] la"),
             stored(plain="crlf\r\nline\r\n"), stored(plain="斑马，斑马 𝄞"),
             json.dumps({"plainLyrics": "a bare LRCLIB record", "syncedLyrics": None, "instrumental": False}),
             json.dumps({"plain": 5, "raw": {}}), "", "   ", "not json", "[1, 2]", "null"]
    out = []
    for text in texts:
        out.append(record("caracole.peer_sync.lyrics_files", None, [text], {}, lambda text=text: {
            name: None if data is None else data.decode("utf-8") for name, data in sync.lyrics_files(text).items()}))
    return out


STAMPS = ["2026-10-31T00:00:00Z", "2026-10-31T00:00:00+00:00", "2026-10-31T02:00:00+02:00", "2026-10-31T00:00:00",
          "2026-10-31", "2026-10-31 00:00", "2026-10-31T00", "20261031T000000Z", "2026-W44-1", "2026-W44",
          "2026-304", "2026-10-31t00:00:00z", "2026-10-31T00:00:00.5Z", "2026-10-31T00:00:00.123456Z",
          "2026-10-31T00:00:00.123456789Z", "2026-10-31T00:00:00,5", "2026-10-31T23:59:60Z", "2026-02-30",
          "2026-10-31T00:00:00+0530", "2026-10-31T00:00:00-00:00", "2026-10-31T00:00:00+05:30:15",
          "2026-10-31T00:00:00+05", "2026-10-31T24:00:00", "２０２６-10-31", "  2026-10-31", "2026-10-31 ", "", None,
          "x", "2026-1-3", "0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z", "2026-10-31T00:00:00Z[UTC]",
          "2026-10-31T00:00:00.Z", "2026-10-31T00:00Z", "2026-10-31T0000Z"]


def stamp_records(corpus: Corpus) -> list[dict]:
    from caracole import stamps

    def parsed(value):
        when = stamps.parse(value)
        return None if when is None else {"iso": when.isoformat(), "stamp": stamps.stamp(when)}

    return [record("caracole.stamps.parse", None, [value], {}, lambda value=value: parsed(value)) for value in STAMPS]


def rekey_records(corpus: Corpus) -> list[dict]:
    from caracole.songs import ensure_current_keys

    lib = corpus.replayed("library", "rekey")

    def rekey():
        count = ensure_current_keys(lib.conn)
        return {"count": count, "songs": [list(r) for r in lib.conn.execute(
                    "SELECT id, key, artist, title, artists, album, duration_ms, variant, source_ids, added_at, "
                    "status, ug_dirty FROM songs ORDER BY id")],
                "versions": [list(r) for r in lib.conn.execute(
                    "SELECT id, song_id, provider, tab_id, pick_rank FROM versions ORDER BY id")],
                "files": [list(r) for r in lib.conn.execute(
                    "SELECT id, song_id, version_id, name, path FROM files ORDER BY id")],
                "removed": [list(r) for r in lib.conn.execute(
                    "SELECT key, artist, title, source_ids, removed_at FROM removed ORDER BY key")],
                "kv": [list(r) for r in lib.conn.execute(
                    "SELECT key, value FROM kv WHERE key LIKE 'wanted:first_seen:%' OR key = 'songs:key_version' "
                    "ORDER BY key")]}

    return [record("caracole.songs.ensure_current_keys", "rekey", [], {}, rekey)]


# caracole.toml as the computer's owner may write it, each case a settings document the phone takes.
SETTINGS = {
    "defaults": "",
    "named": 'name = "Canciones de Dani · 歌 🎸"\nuser_agent = "caracole/0.1 (Dani\'s tabs; +https://example.org)"\n',
    "switches": "[providers.megalobiz]\nenabled = false\n[providers.youtube]\nenabled = false\n"
                "[providers.ytimg]\nenabled = false\n[providers.gametabs]\nenabled = true\n",
    "lookup": "[providers.ug]\nlookup_delay = [0, 0]\nlookup_requests = 3\nlookup_per_hour = 30\nbudget = 7\n"
              "delay = [9, 10]\n[providers.lacuerda]\nlookup_delay = [0.5, 1.5]\n[providers.azlyrics]\n"
              "lookup_requests = 0\nlookup_per_hour = 1000\n",
    "thresholds": "[match]\naccept = 85.5\nmargin = 5\nreview = 70\nartist_gate = 95\n[rank]\n"
                  "coverage_threshold = 0.7\nline_match = 80\nprior_votes = 0\nscored_sheets = 5\n"
                  "label_penalty = 1\nvariant_bonus = 0.125\n",
    # caracole.toml may give any of them but scored_sheets a fraction, line_match and prior_votes too (config.py
    # keeps what it reads), and a whole number where the default is a float
    "fractions": "[match]\naccept = 100\nmargin = 0.5\nreview = 0\n[rank]\nline_match = 82.5\nprior_votes = 2.5\n"
                 "coverage_threshold = 1\nlabel_penalty = 0\n",
}


def phone_settings(cfg) -> dict[str, Any]:
    """The phone's settings once it takes ``cfg``'s document, in data/caracole/config/config.json's shape
    (``switchable`` aside) with ``name``: config.py's defaults, each provider's switch and a lookup's settings the
    computer's, bulk work's ``budget`` and ``delay`` the defaults' (the phone does none); the user agent, ``[match]``,
    ``[rank]`` and caracole.toml's name the computer's. Made from the config itself, never from the document."""
    import dataclasses

    from caracole import config

    def fields(obj) -> dict:
        return {f.name: list(v) if isinstance(v := getattr(obj, f.name), tuple) else v
                for f in dataclasses.fields(obj)}

    providers = {}
    for name, default in config.DEFAULT_PROVIDERS.items():
        mine = cfg.provider(name)
        providers[name] = fields(dataclasses.replace(
            default, enabled=mine.enabled, lookup_delay=mine.lookup_delay, lookup_requests=mine.lookup_requests,
            lookup_per_hour=mine.lookup_per_hour, per_day=mine.per_day))
    return {"providers": providers, "user_agent": cfg.user_agent, "match": fields(cfg.match),
            "rank": fields(cfg.rank), "name": cfg.name}


def settings_config(corpus: Corpus, case: str):
    """The config of ``SETTINGS[case]``'s caracole.toml, in a folder of its own."""
    from caracole.config import load_config

    folder = corpus.workdir / "settings" / case
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "caracole.toml").write_text(SETTINGS[case], encoding="utf-8")
    return load_config(folder / "caracole.toml", env={"HOME": str(folder / "home")})


def settings_records(corpus: Corpus) -> list[dict]:
    from caracole.politeness import settings_document

    out = []
    for case, text in SETTINGS.items():
        cfg = settings_config(corpus, case)
        out.append(record("caracole.politeness.settings_document", None, [text], {},
                          lambda cfg=cfg: settings_document(cfg), case=case, phone=phone_settings(cfg)))
    return out


# The phone's take, rule by rule (settings_take.jsonl): what no caracole.toml can show, since a computer's document
# always names every provider of its own config, and the phone takes a document after another.
SETTINGS_TAKES = (
    "nothing taken yet",
    "a state with no settings keeps the last take",
    "a second take replaces the first",
    "a newer computer's provider is passed over",
    "an older computer's document leaves a provider it doesn't name at the defaults",
    "a provider the second take doesn't name is the defaults', never the first take's",
)


def phone_takes(kept: dict | None, settings: dict | None) -> dict[str, Any]:
    """The phone's rule for the computer's settings, as the spec states it (PhoneConfig.take, then
    PhoneConfig.read): ``kept`` the kv ``phone:settings`` before (a document, or None), ``settings`` the state's
    member (None: the state has none). ``{"kept", "read"}``: the kv after (the document as given, or ``kept`` as it
    was when the state gives none), and what ``PhoneConfig.read`` answers then, in config.json's shape (its
    ``switchable`` aside) with ``name``: config.json's defaults, each provider the document names that the phone
    knows taking its five fields (``politeness.LOOKUP_FIELDS``) over them, its ``budget`` and ``delay`` the defaults',
    a provider the document doesn't name the defaults' whole (never an earlier take's), one the phone doesn't know
    passed over; the user agent, ``[match]``, ``[rank]`` and the name the document's. A model for the corpus: the
    test below holds it to ``phone_settings``, made from the config, on every document of ``SETTINGS``."""
    from caracole.politeness import LOOKUP_FIELDS
    from test_conformance_config import config_json

    defaults = json.loads(config_json())
    del defaults["switchable"]
    taken = settings if settings is not None else kept
    if taken is None:
        return {"kept": None, "read": {**defaults, "name": None}}
    given = taken["providers"]
    providers = {name: policy | ({field: given[name][field] for field in LOOKUP_FIELDS} if name in given else {})
                 for name, policy in defaults["providers"].items()}
    return {"kept": taken, "read": {"providers": providers, "user_agent": taken["user_agent"],
                                    "match": taken["match"], "rank": taken["rank"], "name": taken["name"]}}


def settings_take_records(corpus: Corpus) -> list[dict]:
    import copy

    from caracole.politeness import settings_document

    lookup = settings_document(settings_config(corpus, "lookup"))
    thresholds = settings_document(settings_config(corpus, "thresholds"))
    newer = copy.deepcopy(lookup)
    newer["providers"]["songsterr"] = {"enabled": False, "lookup_delay": [9.0, 9.5], "lookup_requests": 1,
                                       "lookup_per_hour": 2, "per_day": 3}
    older = copy.deepcopy(lookup)
    del older["providers"]["lacuerda"]
    without_ug = copy.deepcopy(lookup)
    del without_ug["providers"]["ug"]
    takes = dict(zip(SETTINGS_TAKES, (
        (None, None), (lookup, None), (lookup, thresholds), (None, newer), (None, older), (lookup, without_ug))))
    return [record("test_conformance_sync.phone_takes", None, [kept, given], {},
                   lambda kept=kept, given=given: phone_takes(kept, given), case=case)
            for case, (kept, given) in takes.items()]


MAKERS: dict[str, Callable[[Corpus], list[dict]]] = {
    "values": value_records, "documents": document_records, "compare": compare_records,
    "merged_base": merged_base_records, "record_agreement": record_agreement_records, "decide": decide_records,
    "name_key": name_key_records, "compared_hash": compared_hash_records, "take": take_records,
    "checked_name": checked_name_records, "settings": settings_records, "settings_take": settings_take_records,
    "add": add_records, "remove": remove_records, "lyrics_files": lyrics_records, "stamps": stamp_records,
    "ensure_current_keys": rekey_records,
}


def vector_path(name: str) -> Path:
    return (SYNC if name in SYNC_FILES else LIBRARY) / f"{name}.jsonl"


def vector_text(corpus: Corpus, name: str) -> str:
    area = "sync" if name in SYNC_FILES else "library"
    return jsonl(corpus.records(name), corpus=f"{area}/{name}", made_by=MADE_BY)


def every_file(workdir: Path) -> dict[Path, str]:
    """Every file of this corpus, by its path, made in ``workdir``."""
    corpus = Corpus(workdir)
    try:
        files = {SYNC / "fixtures" / f"{name}.jsonl": corpus.fixture_text("sync", name) for name in FIXTURES}
        files.update({LIBRARY / "fixtures" / f"{name}.jsonl": corpus.fixture_text("library", name)
                      for name in LIBRARY_FIXTURES})
        files.update({vector_path(name): vector_text(corpus, name) for name in MAKERS})
    finally:
        corpus.close()
    return files


# --- the tests -----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    made = Corpus(tmp_path_factory.mktemp("sync-corpus"))
    yield made
    made.close()


@pytest.mark.parametrize("name", list(FIXTURES))
def test_a_sync_fixture_is_its_library_dumped(corpus, name):
    check(SYNC / "fixtures" / f"{name}.jsonl", corpus.fixture_text("sync", name))


@pytest.mark.parametrize("name", list(LIBRARY_FIXTURES))
def test_a_library_fixture_is_its_library_dumped(corpus, name):
    check(LIBRARY / "fixtures" / f"{name}.jsonl", corpus.fixture_text("library", name))


def test_a_fixture_replayed_dumps_as_it_was_built(corpus):
    for area, names in (("sync", FIXTURES), ("library", LIBRARY_FIXTURES)):
        for name in names:
            lib = corpus.replayed(area, name, tag="-again")
            again = [r for r in dump_fixture(lib.conn, lib.cfg.library_dir) if r.get("file") not in TOP_FILES]
            assert again == read_fixture(corpus.fixture_text(area, name)), (area, name)


def test_the_phones_rows_hold_every_entry_of_overrides_and_songbooks(corpus):
    """What the phone reads of its rows is what overrides.py reads of overrides.toml, entry by entry."""
    from caracole.overrides import song_entries

    for name in SYNC_FIXTURES:
        lib = corpus.replayed("sync", name)
        overrides = lib.overrides()
        rows = lib.conn.execute("SELECT tbl, key, value FROM phone_overrides").fetchall()
        for (key,) in lib.conn.execute("SELECT key FROM songs"):
            assert {t: json.loads(v) for t, k, v in rows if k == key and t not in ("alias", "artist_url", "block")} \
                == song_entries(overrides, key), (name, key)
        assert {k: tuple(json.loads(v)) for t, k, v in rows if t == "alias"} == dict(overrides.alias)
        assert {k: json.loads(v) for t, k, v in rows if t == "artist_url"} == dict(overrides.artist_url)
        assert {int(k) for t, k, _ in rows if t == "block"} == set(overrides.block)
        books = [(n, json.loads(s)) for n, s in lib.conn.execute(
            "SELECT name, songs FROM phone_songbooks ORDER BY position")]
        from caracole import peer_sync as sync

        assert books == [(b.name, sync.songbook_value(b)["songs"]) for b in lib.books()]


def test_every_unit_kind_compare_case_and_take_rule_is_in_the_vectors(corpus):
    kinds = {record["out"]["id"].partition("/")[0] for record in corpus.records("values")}
    assert kinds == {"song", "removed", "songbook", "alias", "artist_url", "block"}
    proposals = {d["proposal"] for r in corpus.records("compare") for d in r["out"]}
    assert proposals == {"mine", "theirs", "conflict"}
    whys = {d["why"].split(" since")[0].split(" ")[0] for r in corpus.records("compare") for d in r["out"]}
    assert {"only", "on", "changed", "new", "gone"} <= whys
    # the design's three-way table, row by row (docs/superpowers/specs/2026-10-31-phone-server-sync-design.md)
    rows = {(r["case"], tuple((d["proposal"], d["why"]) for d in r["out"])) for r in corpus.records("compare")}
    for row in [("changed here alone: mine", (("mine", "changed here since the last sync"),)),
                ("changed there alone: theirs", (("theirs", "changed there since the last sync"),)),
                ("both changed, differently: a conflict", (("conflict", "changed on both sides since the last sync"),)),
                ("new here since", (("mine", "new here since the last sync"),)),
                ("new there since", (("theirs", "new there since the last sync"),)),
                ("gone here since", (("mine", "gone here since the last sync"),)),
                ("gone there since", (("theirs", "gone there since the last sync"),)),
                ("gone here, changed there: a conflict", (("conflict", "changed on both sides since the last sync"),)),
                ("same on both, as agreed: nothing", ()), ("both changed, the same way: nothing", ()),
                ("gone on both: nothing", ())]:
        assert row in rows, row


def test_the_phone_takes_the_settings_over_config_jsons_defaults(corpus):
    """settings.jsonl's ``phone`` is config.json (PhoneConfig.DEFAULTS) with the computer's settings laid over it: the
    defaults case is config.json itself, no case moves a run's budget or pause, and each case changes what its
    caracole.toml says and nothing else."""
    from test_conformance_config import config_json

    defaults = json.loads(config_json())
    del defaults["switchable"]
    records = {r["case"]: r for r in corpus.records("settings")}
    assert list(records) == list(SETTINGS) and all("err" not in r for r in records.values())
    assert records["defaults"]["phone"] == {**defaults, "name": None}
    for case, r in records.items():
        doc, phone = r["out"], r["phone"]
        assert list(doc) == ["name", "user_agent", "providers", "match", "rank"], case
        for name, policy in phone["providers"].items():
            assert (policy["budget"], policy["delay"]) == (defaults["providers"][name]["budget"],
                                                           defaults["providers"][name]["delay"]), (case, name)
            assert {k: policy[k] for k in doc["providers"][name]} == doc["providers"][name], (case, name)
        assert (phone["name"], phone["user_agent"], phone["match"], phone["rank"]) == (
            doc["name"], doc["user_agent"], doc["match"], doc["rank"]), case
    assert records["lookup"]["phone"]["providers"]["ug"]["lookup_delay"] == [0.0, 0.0]
    assert records["switches"]["out"]["providers"]["megalobiz"]["enabled"] is False
    assert records["thresholds"]["out"]["match"]["accept"] == 85.5 and records["named"]["out"]["name"]
    assert records["fractions"]["out"]["rank"]["line_match"] == 82.5 and records["fractions"]["out"]["rank"][
        "coverage_threshold"] == 1


def test_the_phones_take_rule_is_the_settings_phone_on_every_document(corpus):
    """phone_takes, settings_take.jsonl's model, answers settings.jsonl's ``phone`` (made from the config, never the
    document) for every document there, taken first or after another."""
    lookup = next(r["out"] for r in corpus.records("settings") if r["case"] == "lookup")
    for r in corpus.records("settings"):
        for kept in (None, lookup):
            assert phone_takes(kept, r["out"]) == {"kept": r["out"], "read": r["phone"]}, r["case"]


def test_every_rule_of_the_phones_take_is_in_the_vectors(corpus):
    """Each of SETTINGS_TAKES once, and each shows what its name says."""
    records = {r["case"]: r for r in corpus.records("settings_take")}
    assert list(records) == list(SETTINGS_TAKES) and all("err" not in r for r in records.values())
    phone = {r["case"]: r["phone"] for r in corpus.records("settings")}
    nothing, kept, replaced, newer, older, dropped = (records[case] for case in SETTINGS_TAKES)
    assert nothing["out"] == {"kept": None, "read": phone["defaults"]}
    assert kept["out"]["kept"] == kept["args"][0] and kept["out"]["read"] == phone["lookup"]
    assert replaced["out"]["kept"] == replaced["args"][1] and replaced["out"]["read"] == phone["thresholds"]
    assert replaced["out"]["read"]["providers"]["ug"]["lookup_requests"] == 6  # the first take's 3 gone
    assert "songsterr" in newer["out"]["kept"]["providers"] and newer["out"]["read"] == phone["lookup"]
    ug, lacuerda = (older["out"]["read"]["providers"][name] for name in ("ug", "lacuerda"))
    assert ug["lookup_requests"] == 3 and lacuerda == phone["defaults"]["providers"]["lacuerda"]
    ug, lacuerda = (dropped["out"]["read"]["providers"][name] for name in ("ug", "lacuerda"))
    assert ug == phone["defaults"]["providers"]["ug"] and lacuerda["lookup_delay"] == [0.5, 1.5]


def test_every_rule_of_the_take_is_in_the_vectors(corpus):
    """Each of §5.6's rules (``TAKE_RULES``) is shown by a take of take.jsonl, and every take shows one of them."""
    shown = [r["rule"] for r in corpus.records("take")]
    assert set(shown) == set(TAKE_RULES) and len(TAKE_RULES) == len(set(TAKE_RULES))
    assert len({r["case"] for r in corpus.records("take")}) == len(shown)


@pytest.mark.parametrize("name", list(MAKERS))
def test_a_vector_is_what_peer_sync_and_the_library_answer(corpus, name):
    check(vector_path(name), vector_text(corpus, name))


def test_each_take_does_what_its_rule_says(corpus):
    from caracole import peer_sync as sync

    takes = {r["case"]: r for r in corpus.records("take")}
    for case in ("names_as_written", "respelling", "co_artists", "new_here", "tombstone_forgotten", "folder_moved",
                 "file_dropped", "entries"):
        assert takes[case]["out"]["left"] == [], case
    for case in ("refused_name", "file_not_given", "file_other_sha", "overrides_refused", "changed_here",
                 "changed_there"):  # left, and this side as it was
        record, before = takes[case], corpus.replayed("sync", f"take_{case}", tag="-before")
        assert [u for u, _ in record["out"]["left"]] == [CREEP] and record["out"]["taken"] == [], case
        assert {u: a["digest"] for u, a in record["out"]["after"].items()} == before.digests(), case
        assert record["out"]["files"] == _song_files(before), case
    assert takes["names_as_written"]["out"]["after"][CREEP]["value"]["names"]["artist"] == "Radiohead"
    assert {p.split("/")[0] for p, _ in takes["respelling"]["out"]["files"]} == {"Radiohead"}
    assert takes["respelling"]["out"]["respelled"] == [KARMA, SURPRISES]
    karma_id = takes["respelling"]["out"]["ids"]["radiohead/karma-police"]
    assert [k for k, _ in takes["respelling"]["out"]["kv"]] == [f"render:export:{karma_id}",
                                                                 f"render:progressions:{karma_id}"]
    artists = {u: takes["co_artists"]["out"]["after"][u]["value"]["names"]["artists"] for u in (KARMA, SURPRISES)}
    assert artists == {KARMA: ["Radiohead", "Thom Yorke"], SURPRISES: ["Thom Yorke", "radiohead"]}
    assert {takes["co_artists"]["out"]["after"][u]["value"]["names"]["artist"] for u in (KARMA, SURPRISES)} \
        == {"Radiohead"}
    assert "removed/radiohead/creep" not in takes["tombstone_forgotten"]["out"]["after"]
    assert list(takes["absent_there"]["out"]["after"]) == ["removed/radiohead/creep"]
    assert list(takes["tombstone_made"]["out"]["after"]) == ["removed/oasis/wonderwall"]
    assert "removed/oasis/wonderwall" not in takes["tombstone_beside_a_song"]["out"]["after"]
    assert takes["tombstone_dropped"]["out"]["after"] == {}
    assert takes["folder_moved"]["out"]["paths"] == ["Soda Stereo/De Música Ligera/sheet.txt",
                                                     "Soda Stereo/De Música Ligera/tab.txt"]
    assert [k.split(":")[1] for k, _ in takes["folder_moved"]["out"]["kv"]] == ["export", "progressions"]
    assert "Radiohead/Creep/guitar-1.gp5" not in [p for p, _ in takes["file_dropped"]["out"]["files"]]
    assert takes["file_dropped"]["out"]["paths"] == ["Radiohead/Creep/sheet.txt"]
    assert "unknown table" in takes["overrides_refused"]["out"]["left"][0][1]
    assert takes["document_unreadable"]["out"]["taken"] == [KARMA]
    assert [u for u, _ in takes["document_unreadable"]["out"]["left"]] == [CREEP, WONDERWALL]
    assert list(takes["document_unreadable"]["out"]["after"]) == [KARMA]
    new = takes["new_here"]["out"]["documents"][CREEP]
    assert new["song"]["status"] == "found" and new["versions"][0]["rating"] == 4.5
    assert takes["new_here"]["out"]["ids"] == {"radiohead/creep": 1}
    assert takes["new_here"]["source"]["units"][CREEP]["kv"] == new["kv"] != {}
    assert takes["new_here"]["out"]["kv"] == [["sheet_versions:same:1:101", "99"],
                                              ["sheet_versions:unkeepable:1", "[7]"], ["sheet_versions:yours:1", "[101]"]]
    assert [u for u, _ in takes["refused_name"]["out"]["left"]] == [CREEP]
    assert takes["whole_or_nothing"]["out"]["taken"] == [KARMA]
    assert takes["changed_here"]["out"]["left"] == [[CREEP, sync.CHANGED_HERE]]
    assert takes["changed_there"]["out"]["left"] == [[CREEP, sync.CHANGED_THERE]]
    assert takes["entries"]["out"]["left"] == [] and takes["entries"]["out"]["songbooks"]


@pytest.mark.slow  # the whole corpus made twice, in two processes
def test_the_corpus_is_the_same_whatever_the_hash_seed(tmp_path):
    from conftest import subprocess_pythonpath

    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(f"{SRC}{os.pathsep}{TESTS}"),
           "CARACOLE_YTDLP_BIN": str(tmp_path / "no-yt-dlp"), "CARACOLE_SERVICE_FILE": str(tmp_path / "no-service")}
    script = "import sys, test_conformance_sync as m; m.write_all(sys.argv[1], sys.argv[2])"
    running = {seed: subprocess.Popen([sys.executable, "-c", script, str(tmp_path / f"seed-{seed}"),
                                       str(tmp_path / f"work-{seed}")], env={**env, "PYTHONHASHSEED": seed}, cwd=TESTS)
               for seed in ("1", "2")}
    made = {}
    for seed, process in running.items():
        assert process.wait(timeout=300) == 0, seed
        out = tmp_path / f"seed-{seed}"
        made[seed] = {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}
    assert made["1"].keys() == made["2"].keys() and made["1"]
    for path in made["1"]:
        assert made["1"][path] == made["2"][path], path


def write_all(out: str, workdir: str) -> None:
    """Every file of the corpus written under ``out`` (by its path under tests/conformance/vectors), made in
    ``workdir``: what the hash seed test compares."""
    for path, text in every_file(Path(workdir)).items():
        target = Path(out) / path.relative_to(VECTORS)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
