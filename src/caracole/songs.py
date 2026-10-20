"""Song records: one row per song you want to learn, whatever source it came from.

A song's identity is ``normalize.identity_key(primary artist, title)``, so the
same song liked on Spotify and listed in ``wanted.txt`` (or a remaster next to
the original) becomes one record that remembers every source id. A source id
it already has finds it first, so a track Spotify retitles stays one song.

Its album, duration, ISRC and variant are what its sources say now, not what
the first one said: the latest word of each source is kept, and each field
comes from the first source that gives it, your wanted.txt line before
Spotify's tracks (:func:`upsert_song`).

The stored keys follow the normalizer: when its rules change
(``normalize.KEY_VERSION``), every key is recomputed once, before the songs are
next read or added, and songs that now share a key become one
(:func:`ensure_current_keys`).

A song ``caracole remove`` took out leaves a tombstone in the ``removed`` table
(:func:`mark_removed`; removal.py does the rest). No source brings it back
(:class:`SongRemoved`) until you ask for it again: a wanted.txt line for it, the
one ``caracole add`` and the web page write too, or a Spotify track you added
after the removal. Then it comes back as a new song.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence

from caracole.db import kv_delete, kv_get, kv_set
from caracole.normalize import KEY_VERSION, display_key, identity_key, title_variant

_JSON_COLUMNS = {"artists", "source_ids", "match_candidates"}
_BOOL_COLUMNS = {"review", "ug_dirty"}
SHEET_FILE_NAMES = ("sheet.txt", "sheet (auto).txt")
KEY_VERSION_KV = "songs:key_version"  # the normalize.KEY_VERSION the stored keys were made with
# What each source id last said of its song's album, duration, ISRC and variant (_remember),
# as JSON under this prefix + "<source>:<source id>", e.g. "songs:fields:spotify:<track id>".
SOURCE_FIELDS_KV = "songs:fields:"
_SOURCE_FIELDS = ("album", "duration_ms", "isrc", "variant")
# Whose word a field takes first: wanted.txt is your own (plan, Amendment A2), then Spotify's
# tracks (wanted.SOURCE, spotify.SOURCE). A source not named here comes after them.
_WANTED = "wanted"
_PRECEDENCE = (_WANTED, "spotify")
# What other modules keep in kv under a song's id (render.py, ug/fetch.py, autochords/run.py,
# gtptabs_fetch.py, youtube_fetch.py), as "<prefix><song id>" or "<prefix><song id>:<more>"
# ("render:7:auto"). It goes with a song merged into another or removed (delete_song_kv): SQLite
# may give that id to the next new song.
_PER_SONG_KV = ("render:", "render:files:", "ug:artist_page_checked:", "autochords:failed:", "gtptabs:checked:",
                "ug:blocked:", "youtube:")


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Song:
    id: int
    key: str
    artist: str
    title: str
    artists: list[str]
    album: str | None
    duration_ms: int | None
    isrc: str | None
    source_ids: dict[str, list[str]]
    added_at: str
    variant: str | None
    status: str
    review: bool
    match_decision: str | None
    match_step: str | None
    match_score: float | None
    match_artist_key: str | None
    match_song_key: str | None
    match_candidates: list[Any] = field(default_factory=list)
    matched_at: str | None = None
    ug_dirty: bool = True
    ug_checked_at: str | None = None
    lyrics_status: str = "pending"
    lyrics_json: Any = None  # the raw JSON text; lyrics.lyrics_from_json decodes it
    lyrics_at: str | None = None
    lacuerda_checked_at: str | None = None
    audio_path: str | None = None
    audio_mtime: float | None = None
    autochords_mtime: float | None = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def display(self) -> str:
        """"Artist - Clean Title", as written in overrides.toml and on the to-do page."""
        return display_key(self.artist, self.title)

    @property
    def duration_s(self) -> float | None:
        return self.duration_ms / 1000 if self.duration_ms else None


_COLUMNS = tuple(Song.__dataclass_fields__)


def _from_row(row: sqlite3.Row) -> Song:
    values: dict[str, Any] = {}
    for name in _COLUMNS:
        value = row[name]
        if name in _JSON_COLUMNS and value is not None:
            values[name] = json.loads(value)
        elif name in _BOOL_COLUMNS:
            values[name] = bool(value)
        else:
            values[name] = value
    return Song(**values)


def get_song(conn: sqlite3.Connection, song_id: int) -> Song:
    """The song with this id; KeyError for none, an id no SQLite integer can hold among them."""
    if not -(2**63) <= song_id < 2**63:  # sqlite3 would raise OverflowError
        raise KeyError(f"no song with id {song_id}")
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if row is None:
        raise KeyError(f"no song with id {song_id}")
    return _from_row(row)


def find_song(conn: sqlite3.Connection, key: str) -> Song | None:
    ensure_current_keys(conn)
    row = conn.execute("SELECT * FROM songs WHERE key = ?", (key,)).fetchone()
    return _from_row(row) if row else None


def list_songs(conn: sqlite3.Connection, *, statuses: Iterable[str] | None = None) -> list[Song]:
    """Songs, newest ``added_at`` first (so a song you just added is handled first)."""
    ensure_current_keys(conn)
    if statuses is None:
        rows = conn.execute("SELECT * FROM songs ORDER BY added_at DESC, id DESC").fetchall()
    else:
        wanted = list(statuses)
        marks = ",".join("?" for _ in wanted)
        rows = conn.execute(
            f"SELECT * FROM songs WHERE status IN ({marks}) ORDER BY added_at DESC, id DESC", wanted
        ).fetchall()
    return [_from_row(r) for r in rows]


def upsert_song(
    conn: sqlite3.Connection,
    *,
    artists: Sequence[str],
    title: str,
    album: str | None,
    duration_ms: int | None,
    isrc: str | None,
    source: str,
    source_id: str,
    added_at: str,
) -> tuple[int, bool]:
    """Insert a song or merge it into the existing record; return ``(song_id, created)``.

    The existing record is the one that has this source id already, else the
    one with the song's identity key. Merging keeps the newest ``added_at``
    and adds the source id. The display artist and title of the first source
    are kept, and so is its key. A source saying nothing new (every sync hands
    every song over again) leaves the record as it is: nothing is written.

    The album, duration, ISRC and variant (read from the title) given here are
    this source id's word now, kept in kv (``SOURCE_FIELDS_KV``); the song
    then takes each field from the first of its sources that gives it
    (:func:`_resolve`). So a wanted.txt line you correct corrects the song at
    the next sync, and a value you take off the line gives way to Spotify's.

    A song ``caracole remove`` took out, found by the source id or, failing a
    record of yours, by the key, raises SongRemoved, unless this is a request
    for it again (:func:`_unless_removed`): then it comes back as a new song.
    """
    names = [a.strip() for a in artists if a and a.strip()]
    if not names:
        raise ValueError("a song needs at least one artist")
    title = title.strip()
    key = identity_key(names[0], title)
    said = {"album": album, "duration_ms": duration_ms, "isrc": isrc, "variant": title_variant(title)}
    now = utc_now_iso()
    ensure_current_keys(conn)
    row = _with_source_id(conn, source, source_id)
    if row is None:
        _unless_removed(conn, _removed_with_source_id(conn, source, source_id), source, added_at)
        row = conn.execute("SELECT * FROM songs WHERE key = ?", (key,)).fetchone()
    if row is None:
        _unless_removed(conn, removed_song(conn, key), source, added_at)
        cur = conn.execute(
            "INSERT INTO songs (key, artist, title, artists, album, duration_ms, isrc, source_ids, "
            "added_at, variant, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key, names[0], title, json.dumps(names, ensure_ascii=False), album, duration_ms, isrc,
                json.dumps({source: [source_id]}, ensure_ascii=False), added_at,
                said["variant"], now, now,
            ),
        )
        assert cur.lastrowid is not None
        _remember(conn, source, source_id, said)
        return cur.lastrowid, True

    existing = _from_row(row)
    ids = _add_ids({k: list(v) for k, v in existing.source_ids.items()}, {source: [source_id]})
    _remember(conn, source, source_id, said)
    fields = _resolve(conn, ids, existing)
    added = max(existing.added_at, added_at)
    if ids == existing.source_ids and added == existing.added_at and all(
        fields[name] == getattr(existing, name) for name in _SOURCE_FIELDS
    ):
        return existing.id, False
    conn.execute(
        "UPDATE songs SET source_ids = ?, added_at = ?, album = ?, duration_ms = ?, isrc = ?, "
        "variant = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(ids, ensure_ascii=False), added, fields["album"],
            fields["duration_ms"], fields["isrc"], fields["variant"], now, existing.id,
        ),
    )
    return existing.id, False


def _add_ids(ids: dict[str, list[str]], more: dict[str, list[str]]) -> dict[str, list[str]]:
    """Add each id of ``more`` that ``ids`` lacks, after its source's ids there; return ``ids``."""
    for source, values in more.items():
        bucket = ids.setdefault(source, [])
        bucket.extend(v for v in values if v not in bucket)
    return ids


def _fields_key(source: str, source_id: str) -> str:
    return f"{SOURCE_FIELDS_KV}{source}:{source_id}"


def _remember(conn: sqlite3.Connection, source: str, source_id: str, said: dict[str, Any]) -> None:
    """Keep what a source id says of its song's fields; unchanged, nothing is written.

    A wanted.txt line is your whole word: what you take off it, it no longer
    says. A field another source leaves out (a Spotify track without an ISRC
    tonight) is no news, so its earlier word on it stands.
    """
    key = _fields_key(source, source_id)
    before = kv_get(conn, key)
    if before is not None and source != _WANTED:
        old = json.loads(before)
        said = {name: old.get(name) if value is None else value for name, value in said.items()}
    value = json.dumps(said, ensure_ascii=False)
    if before != value:
        kv_set(conn, key, value)


def _resolve(conn: sqlite3.Connection, source_ids: dict[str, list[str]], song: Song) -> dict[str, Any]:
    """The album, duration, ISRC and variant a song's sources give it now.

    Each field comes from the first source that gives one: the wanted.txt
    line, then Spotify's tracks in the order the song gained them (so a
    remaster and the original don't take turns), then any other source.

    A source id with no word kept was last heard by a caracole that kept none
    and merged first come, first served, so whose value the song holds is
    unknown. Such an id is taken, once, to have said what the song holds and
    no source heard since says the same: a track you no longer like keeps its
    album, and a duration the line says now stays the line's to take back.
    """
    rank = {name: i for i, name in enumerate(_PRECEDENCE)}
    words: dict[str, dict[str, Any] | None] = {}
    for source in sorted(source_ids, key=lambda s: rank.get(s, len(rank))):
        for source_id in source_ids[source]:
            value = kv_get(conn, _fields_key(source, source_id))
            words[_fields_key(source, source_id)] = None if value is None else json.loads(value)
    heard = [w for w in words.values() if w is not None]
    held = {
        name: None if any(w.get(name) == getattr(song, name) for w in heard) else getattr(song, name)
        for name in _SOURCE_FIELDS
    }
    for key, word in words.items():
        if word is None:
            kv_set(conn, key, json.dumps(held, ensure_ascii=False))
            words[key] = held
    return {
        name: next((w[name] for w in words.values() if w and w.get(name) is not None), None)
        for name in _SOURCE_FIELDS
    }


def _with_source_id(conn: sqlite3.Connection, source: str, source_id: str) -> sqlite3.Row | None:
    """The song that has ``source_id`` among its ids from ``source``, if any."""
    return conn.execute(
        "SELECT songs.* FROM songs, json_each(songs.source_ids, ?) AS sid WHERE sid.value = ? "
        "ORDER BY songs.id LIMIT 1",
        (f'$."{source}"', source_id),
    ).fetchone()


def update_song(conn: sqlite3.Connection, song_id: int, **fields: Any) -> None:
    """Set columns on a song; lists and dicts are stored as JSON, booleans as 0/1."""
    unknown = sorted(set(fields) - set(_COLUMNS) - {"id"})
    if unknown or "id" in fields:
        raise ValueError(f"unknown or read-only song field(s): {', '.join(unknown or ['id'])}")
    if not fields:
        return
    values: list[Any] = []
    for name, value in fields.items():
        if name in _JSON_COLUMNS and value is not None:
            value = json.dumps(value, ensure_ascii=False)
        elif name in _BOOL_COLUMNS:
            value = int(bool(value))
        values.append(value)
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(
        f"UPDATE songs SET {assignments}, updated_at = ? WHERE id = ?",
        (*values, utc_now_iso(), song_id),
    )


def refresh_status(conn: sqlite3.Connection, song_id: int, *, ignored: bool) -> str:
    """Recompute and store a song's status: ignored, found (has a sheet) or wanted.

    A song is "found" only once it has a human or auto-generated sheet; a guitar
    part alone never makes it found.
    """
    if ignored:
        status = "ignored"
    else:
        marks = ",".join("?" for _ in SHEET_FILE_NAMES)
        has_sheet = conn.execute(
            f"SELECT 1 FROM files WHERE song_id = ? AND name IN ({marks}) LIMIT 1",
            (song_id, *SHEET_FILE_NAMES),
        ).fetchone()
        status = "found" if has_sheet else "wanted"
    update_song(conn, song_id, status=status)
    return status


# --- removed songs ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RemovedSong:
    """A song ``caracole remove`` took out: its key then, its name, the source ids it had."""

    key: str
    artist: str
    title: str
    source_ids: dict[str, list[str]]
    removed_at: str

    @property
    def display(self) -> str:
        return display_key(self.artist, self.title)


class SongRemoved(Exception):
    """A source handed over a song you removed, and that isn't asking for it again."""

    def __init__(self, removed: RemovedSong):
        super().__init__(f"{removed.display} was removed with caracole remove on {removed.removed_at}")
        self.removed = removed


def _removed_from_row(row: sqlite3.Row) -> RemovedSong:
    return RemovedSong(row["key"], row["artist"], row["title"], json.loads(row["source_ids"]), row["removed_at"])


def removed_song(conn: sqlite3.Connection, key: str) -> RemovedSong | None:
    """The tombstone of the song with this identity key, if it was removed."""
    row = conn.execute("SELECT * FROM removed WHERE key = ?", (key,)).fetchone()
    return _removed_from_row(row) if row else None


def list_removed(conn: sqlite3.Connection) -> list[RemovedSong]:
    """Every removed song, the latest removed first."""
    ensure_current_keys(conn)
    rows = conn.execute("SELECT * FROM removed ORDER BY removed_at DESC, key").fetchall()
    return [_removed_from_row(r) for r in rows]


def _removed_with_source_id(conn: sqlite3.Connection, source: str, source_id: str) -> RemovedSong | None:
    row = conn.execute(
        "SELECT removed.* FROM removed, json_each(removed.source_ids, ?) AS sid WHERE sid.value = ? "
        "ORDER BY removed.removed_at DESC LIMIT 1",
        (f'$."{source}"', source_id),
    ).fetchone()
    return _removed_from_row(row) if row else None


def mark_removed(conn: sqlite3.Connection, song: Song, removed_at: str) -> RemovedSong:
    """Leave the song's tombstone, so no source brings it back (``upsert_song``); return it.

    A tombstone under its key already (two songs re-keyed into one) gains its
    source ids and the later time. The song's record itself is removal.py's to delete.
    """
    before = removed_song(conn, song.key)
    ids = _add_ids({k: list(v) for k, v in (before.source_ids if before else {}).items()},
                   song.source_ids)
    stone = RemovedSong(song.key, song.artist, song.title, ids,
                        max(removed_at, before.removed_at) if before else removed_at)
    _write_removed(conn, stone)
    return stone


def _write_removed(conn: sqlite3.Connection, stone: RemovedSong) -> None:
    conn.execute(
        "INSERT INTO removed (key, artist, title, source_ids, removed_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET artist = excluded.artist, title = excluded.title, "
        "source_ids = excluded.source_ids, removed_at = excluded.removed_at",
        (stone.key, stone.artist, stone.title, json.dumps(stone.source_ids, ensure_ascii=False), stone.removed_at),
    )


def forget_removed(conn: sqlite3.Connection, key: str) -> bool:
    """Drop a song's tombstone; whether it had one."""
    return conn.execute("DELETE FROM removed WHERE key = ?", (key,)).rowcount > 0


def _unless_removed(conn: sqlite3.Connection, stone: RemovedSong | None, source: str, added_at: str) -> None:
    """Raise SongRemoved for a removed song, unless the source asks for it again.

    A wanted.txt line asks for it: ``caracole remove`` took the song's lines
    out, so a line there now is one you wrote since, or ``caracole add``, or
    the web page. Another source asks for it with a track added after the
    removal (Spotify's date it was liked or put on a playlist); one added
    before, which the playlist still lists, doesn't. A request drops the
    tombstone, and the song comes back new.
    """
    if stone is None:
        return
    if source != _WANTED and added_at <= stone.removed_at:
        raise SongRemoved(stone)
    forget_removed(conn, stone.key)


def delete_song_kv(conn: sqlite3.Connection, song_id: int) -> None:
    """Delete what other modules keep in kv under the song's id (``_PER_SONG_KV``)."""
    for prefix in _PER_SONG_KV:
        own = f"{prefix}{song_id}"
        conn.execute("DELETE FROM kv WHERE key = ? OR substr(key, 1, ?) = ?", (own, len(own) + 1, own + ":"))


# --- keys after a normalizer change ------------------------------------------------------


def ensure_current_keys(conn: sqlite3.Connection) -> int:
    """Re-key the songs if the normalizer changed since their keys were made; return how many did.

    One kv read when nothing changed, so the readers and ``upsert_song`` call it:
    whatever command runs first after an upgrade sees today's keys, as overrides
    (keyed by today's ``identity_key``) and new sources expect. Like a schema
    migration, it writes whichever command triggers it, a dry run included.
    """
    if kv_get(conn, KEY_VERSION_KV) == str(KEY_VERSION):
        return 0
    return rekey_songs(conn)


def rekey_songs(conn: sqlite3.Connection) -> int:
    """Give every song the key today's normalizer gives it; merge songs that now share one.

    Of the songs that share a key, the oldest record stays, with its display
    artist and title, as if the others had arrived as more sources of it
    (``_merge``). A wanted.txt source id is its line's key, so it follows the
    key, and so does the line's first-seen time. The tombstones of removed songs
    are re-keyed too (``_rekey_removed``). All in one savepoint; returns how many
    songs were re-keyed or merged into another.
    """
    conn.execute("SAVEPOINT rekey_songs")
    try:
        changed = _rekey(conn)
        _rekey_removed(conn)
        kv_set(conn, KEY_VERSION_KV, str(KEY_VERSION))
    except BaseException:
        conn.execute("ROLLBACK TO rekey_songs")
        conn.execute("RELEASE rekey_songs")
        raise
    conn.execute("RELEASE rekey_songs")
    return changed


def _rekey(conn: sqlite3.Connection) -> int:
    groups: dict[str, list[Song]] = {}
    for row in conn.execute("SELECT * FROM songs ORDER BY id").fetchall():
        song = _from_row(row)
        groups.setdefault(identity_key(song.artist, song.title), []).append(song)
    moves = {key: songs for key, songs in groups.items() if len(songs) > 1 or songs[0].key != key}
    # Keys are unique, and one song's new key can be another's old one: park them all first.
    for key, (keep, *others) in moves.items():
        for other in others:
            _merge(conn, keep, other)
        conn.execute("UPDATE songs SET key = ? WHERE id = ?", (f"#rekey:{keep.id}", keep.id))
    for key, (keep, *others) in moves.items():
        conn.execute("UPDATE songs SET key = ? WHERE id = ?", (key, keep.id))
        _follow_wanted(conn, keep.id, {s.key for s in (keep, *others)} - {key}, key)
    return sum(len(others) + (keep.key != key) for key, (keep, *others) in moves.items())


def _rekey_removed(conn: sqlite3.Connection) -> None:
    """Give every tombstone the key today's normalizer gives its song, as ``_rekey`` does the songs:
    tombstones that now share a key become one, with every source id and the latest time, and a
    wanted.txt source id, its line's key, follows the key."""
    groups: dict[str, list[RemovedSong]] = {}
    for row in conn.execute("SELECT * FROM removed ORDER BY removed_at, key").fetchall():
        stone = _removed_from_row(row)
        groups.setdefault(identity_key(stone.artist, stone.title), []).append(stone)
    for key, stones in groups.items():
        if len(stones) == 1 and stones[0].key == key:
            continue
        old_keys = {s.key for s in stones}
        ids: dict[str, list[str]] = {}
        for stone in stones:
            _add_ids(ids, {source: [key if source == _WANTED and v in old_keys else v for v in vs]
                           for source, vs in stone.source_ids.items()})
        latest = stones[-1]
        conn.executemany("DELETE FROM removed WHERE key = ?", [(k,) for k in old_keys])
        _write_removed(conn, RemovedSong(key, latest.artist, latest.title, ids, latest.removed_at))


def _merge(conn: sqlite3.Connection, keep: Song, other: Song) -> None:
    """Fold ``other`` into ``keep`` and delete it.

    ``keep`` gains its source ids, the newer ``added_at`` and the fields it
    lacked, as ``upsert_song`` merges a source. Versions ``keep`` hasn't seen
    move over unpicked, so ``keep``'s picks stand; kept files under names
    ``keep`` hasn't used move with them and stay where they are on disk. The
    rest goes with ``other``. The fetch step then picks again from all of it.
    """
    _add_ids(keep.source_ids, other.source_ids)
    conn.execute(
        "UPDATE songs SET source_ids = ?, added_at = MAX(added_at, ?), album = COALESCE(album, ?), "
        "duration_ms = COALESCE(duration_ms, ?), isrc = COALESCE(isrc, ?), "
        "variant = COALESCE(variant, ?), ug_dirty = 1, updated_at = ? WHERE id = ?",
        (
            json.dumps(keep.source_ids, ensure_ascii=False), other.added_at, other.album,
            other.duration_ms, other.isrc, other.variant, utc_now_iso(), keep.id,
        ),
    )
    conn.execute(
        "UPDATE versions SET song_id = ?, pick_rank = NULL WHERE song_id = ? AND NOT EXISTS ("
        "SELECT 1 FROM versions AS mine WHERE mine.song_id = ? "
        "AND mine.provider = versions.provider AND mine.tab_id = versions.tab_id)",
        (keep.id, other.id, keep.id),
    )
    conn.execute(
        "UPDATE files SET song_id = ?, version_id = ("
        "SELECT mine.id FROM versions AS mine, versions AS theirs "
        "WHERE theirs.id = files.version_id AND mine.song_id = ? "
        "AND mine.provider = theirs.provider AND mine.tab_id = theirs.tab_id) "
        "WHERE song_id = ? AND name NOT IN (SELECT name FROM files WHERE song_id = ?)",
        (keep.id, keep.id, other.id, keep.id),
    )
    conn.execute("DELETE FROM songs WHERE id = ?", (other.id,))
    delete_song_kv(conn, other.id)
    refresh_status(conn, keep.id, ignored=keep.status == "ignored")


def _follow_wanted(conn: sqlite3.Connection, song_id: int, old_keys: set[str], key: str) -> None:
    """A wanted.txt line's source id is its key, and so are the kv keys of its first-seen time
    (``wanted.sync_wanted``) and of its word on the song's fields (``_remember``): all move
    from the song's old keys to its new one. Of several lines' words, one is kept, until the
    next sync says it again."""
    from caracole.wanted import FIRST_SEEN_KEY  # a source of songs: imported on use

    ids = get_song(conn, song_id).source_ids
    if ids.get(_WANTED):
        ids[_WANTED] = list(dict.fromkeys(key if i in old_keys else i for i in ids[_WANTED]))
        update_song(conn, song_id, source_ids=ids)
    for old in old_keys:
        seen = kv_get(conn, FIRST_SEEN_KEY + old)
        if seen is not None:
            current = kv_get(conn, FIRST_SEEN_KEY + key)
            kv_set(conn, FIRST_SEEN_KEY + key, min(seen, current) if current else seen)
            kv_delete(conn, FIRST_SEEN_KEY + old)
    said = kv_get(conn, _fields_key(_WANTED, key))
    for old in sorted(old_keys):
        old_said = kv_get(conn, _fields_key(_WANTED, old))
        if old_said is not None:
            if said is None:
                said = old_said
                kv_set(conn, _fields_key(_WANTED, key), said)
            kv_delete(conn, _fields_key(_WANTED, old))
