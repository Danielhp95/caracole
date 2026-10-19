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
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence

from tabarr.db import kv_delete, kv_get, kv_set
from tabarr.normalize import KEY_VERSION, display_key, identity_key, title_variant

_JSON_COLUMNS = {"artists", "source_ids", "match_candidates", "lyrics_json"}
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
# What other modules keep in kv under a song's id (render.py, ug/fetch.py, autochords/run.py).
# It goes with a song merged into another: SQLite may give that id to the next new song.
_PER_SONG_KV = ("render:", "ug:artist_page_checked:", "autochords:failed:")


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
    lyrics_json: Any = None
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
        if name == "lyrics_json":
            values[name] = value  # kept as the raw JSON text; lyrics.lyrics_from_json decodes it
        elif name in _JSON_COLUMNS and value is not None:
            values[name] = json.loads(value)
        elif name in _BOOL_COLUMNS:
            values[name] = bool(value)
        else:
            values[name] = value
    return Song(**values)


def get_song(conn: sqlite3.Connection, song_id: int) -> Song:
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
    are kept, and so is its key.

    The album, duration, ISRC and variant (read from the title) given here are
    this source id's word now, kept in kv (``SOURCE_FIELDS_KV``); the song
    then takes each field from the first of its sources that gives it
    (:func:`_resolve`). So a wanted.txt line you correct corrects the song at
    the next sync, and a value you take off the line gives way to Spotify's.
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
        row = conn.execute("SELECT * FROM songs WHERE key = ?", (key,)).fetchone()
    if row is None:
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
    ids = {k: list(v) for k, v in existing.source_ids.items()}
    bucket = ids.setdefault(source, [])
    if source_id not in bucket:
        bucket.append(source_id)
    _remember(conn, source, source_id, said)
    fields = _resolve(conn, ids, existing)
    conn.execute(
        "UPDATE songs SET source_ids = ?, added_at = ?, album = ?, duration_ms = ?, isrc = ?, "
        "variant = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(ids, ensure_ascii=False), max(existing.added_at, added_at), fields["album"],
            fields["duration_ms"], fields["isrc"], fields["variant"], now, existing.id,
        ),
    )
    return existing.id, False


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

    A source id with no word kept was last heard by a tabarr that kept none
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
        if name in _JSON_COLUMNS and name != "lyrics_json" and value is not None:
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
    key, and so does the line's first-seen time. All in one savepoint; returns
    how many songs were re-keyed or merged into another.
    """
    conn.execute("SAVEPOINT rekey_songs")
    try:
        changed = _rekey(conn)
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


def _merge(conn: sqlite3.Connection, keep: Song, other: Song) -> None:
    """Fold ``other`` into ``keep`` and delete it.

    ``keep`` gains its source ids, the newer ``added_at`` and the fields it
    lacked, as ``upsert_song`` merges a source. Versions ``keep`` hasn't seen
    move over unpicked, so ``keep``'s picks stand; kept files under names
    ``keep`` hasn't used move with them and stay where they are on disk. The
    rest goes with ``other``. The fetch step then picks again from all of it.
    """
    for source, ids in other.source_ids.items():
        bucket = keep.source_ids.setdefault(source, [])
        bucket.extend(i for i in ids if i not in bucket)
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
    for prefix in _PER_SONG_KV:
        kv_delete(conn, f"{prefix}{other.id}")
    refresh_status(conn, keep.id, ignored=keep.status == "ignored")


def _follow_wanted(conn: sqlite3.Connection, song_id: int, old_keys: set[str], key: str) -> None:
    """A wanted.txt line's source id is its key, and so are the kv keys of its first-seen time
    (``wanted.sync_wanted``) and of its word on the song's fields (``_remember``): all move
    from the song's old keys to its new one. Of several lines' words, one is kept, until the
    next sync says it again."""
    from tabarr.wanted import FIRST_SEEN_KEY, SOURCE  # a source of songs: imported on use

    ids = get_song(conn, song_id).source_ids
    if ids.get(SOURCE):
        ids[SOURCE] = list(dict.fromkeys(key if i in old_keys else i for i in ids[SOURCE]))
        update_song(conn, song_id, source_ids=ids)
    for old in old_keys:
        seen = kv_get(conn, FIRST_SEEN_KEY + old)
        if seen is not None:
            current = kv_get(conn, FIRST_SEEN_KEY + key)
            kv_set(conn, FIRST_SEEN_KEY + key, min(seen, current) if current else seen)
            kv_delete(conn, FIRST_SEEN_KEY + old)
    said = kv_get(conn, _fields_key(SOURCE, key))
    for old in sorted(old_keys):
        old_said = kv_get(conn, _fields_key(SOURCE, old))
        if old_said is not None:
            if said is None:
                said = old_said
                kv_set(conn, _fields_key(SOURCE, key), said)
            kv_delete(conn, _fields_key(SOURCE, old))
