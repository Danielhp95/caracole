"""Libraries side by side, for the sync's tests (test_peer_sync.py) and its corpus (test_conformance_sync.py): each its
own config, database, wanted.txt and folders under one root, its songs added as wanted.txt lines and filled as the
steps leave them, and a ``Source`` that reads another library's units and kept files as ``GET /api/peer/unit`` and
``/api/peer/file`` give them (JSON through and back), with no HTTP::

    from helpers.peer_libraries import Library

    here, there = Library(tmp_path / "here"), Library(tmp_path / "there")
    creep = there.song("Radiohead", "Creep")
    done = here.take(there, [f"song/{creep.key}"])
    assert here.units() == there.units()

``Library.song`` keeps a sheet (``sheet.txt``, of a UG version), lyrics and, given them, overrides.toml's entries
about the song (``entries``, as ``overrides.song_entries`` gives them); ``rich(library)`` fills one with a unit of
every kind and an entry of every table. Each library gets a database id of its own (``sync:id``).
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from caracole import db
from caracole import peer_sync as sync
from caracole.config import load_config
from caracole.library import keep_file
from caracole.lyrics import Lyrics
from caracole.normalize import identity_key
from caracole.overrides import (
    Overrides,
    add_alias,
    add_artist_url,
    add_block,
    load_overrides,
    put_song_entries,
)
from caracole.songbook import load_songbooks, make_songbook, set_song_setting, songbooks_file
from caracole.songs import find_song, mark_removed, update_song
from caracole.versions import upsert_version
from caracole.viewer.version import Setting
from caracole.wanted import append_wanted, sync_wanted

NOW = "2026-10-31T00:00:00Z"
WHEN = datetime.fromisoformat("2026-10-31T00:00:00+00:00")

# Every overrides.toml table about a song, as song_entries gives each back.
EVERY_ENTRY = {
    "match": "radiohead/creep",
    "pin": ["https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"],
    "transpose": -2,
    "reject": ["radiohead/creep-acoustic"],
    "youtube": "https://www.youtube.com/watch?v=XFkzRNyygfk",
    "lacuerda": "https://acordes.lacuerda.net/radiohead/creep",
    "harptabs": "https://www.harptabs.com/tab/1234/creep",
    "gametabs": "https://gametabs.net/tabs/zelda/main-theme",
    "azlyrics": "https://www.azlyrics.com/lyrics/radiohead/creep.html",
    "version": "key=Gm&capo=0",
    "harmonica": {"harmonica-1.txt": "signs"},
    "ignore": True,
}


def write_config(root: Path) -> Path:
    path = root / "caracole.toml"
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(f'library_dir = "{root / "lib"}"\nmusic_dir = "{root / "music"}"\n'
                    f'state_dir = "{root / "state"}"\ncache_dir = "{root / "cache"}"\n', encoding="utf-8")
    return path


class Library:
    """A library of its own under ``root``: its config (``cfg``), its database (``conn``), its folders."""

    def __init__(self, root: Path, *, sync_id: str | None = None):
        from conftest import migrated_database

        self.root = Path(root)
        self.cfg = load_config(write_config(self.root), env={"HOME": str(self.root / "home")})
        self.cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.db_path.write_bytes(migrated_database())
        self.conn = db.connect(self.cfg.db_path)
        db.kv_set(self.conn, sync.ID_KEY, sync_id or secrets.token_hex(8))  # a copy's id would be every copy's

    def close(self) -> None:
        self.conn.close()

    # --- filling it ------------------------------------------------------------------------------------------

    def song(self, artist: str, title: str, *, sheet: bytes | None = b"[Am]Creep", tab: str = "101",
             lyrics: str | None = "I'm a creep", entries: Mapping[str, Any] | None = None,
             album: str | None = None, duration_ms: int | None = None, raw: Mapping[str, Any] | None = None,
             files: Mapping[str, bytes] | None = None):
        """A song of wanted.txt, added as the sync step adds one, with a UG sheet kept (``sheet``, of tab ``tab``),
        more files of that version (``files``), lyrics, and overrides.toml's ``entries`` about it."""
        append_wanted(self.cfg.wanted_file, artist, title, album, duration_ms)
        sync_wanted(self.conn, self.cfg.wanted_file, WHEN)
        song = find_song(self.conn, identity_key(artist, title))
        assert song is not None, f"{artist} - {title} wasn't added"
        if sheet is not None or files:
            vid = upsert_version(self.conn, provider="ug", tab_id=tab, song_id=song.id, slot="sheet", kind="chords",
                                 rating=4.5, votes=10, version=1, label=None, url=f"https://u/{tab}",
                                 raw=raw if raw is not None else {"x": 1}, now=NOW)
            kept = ({"sheet.txt": sheet} if sheet is not None else {}) | dict(files or {})
            for name, data in kept.items():
                keep_file(self.conn, self.cfg.library_dir, song=song, version_id=vid, name=name, data=data, rank=1)
        if lyrics is not None:
            found = Lyrics(plain=lyrics, synced=None, instrumental=False, duration=None, lrclib_id=1)
            update_song(self.conn, song.id, status="found" if sheet is not None else "wanted", lyrics_status="found",
                        lyrics_json=found.to_json())
        if entries:
            put_song_entries(self.cfg.overrides_file, f"{artist} - {title}", entries)
        return find_song(self.conn, song.key)

    def removed(self, artist: str, title: str):
        """A song added, then removed as ``caracole remove --yes`` removes one: its tombstone left."""
        from caracole.removal import plan_removal, remove_song

        song = self.song(artist, title, sheet=None, lyrics=None)
        remove_song(self.conn, self.cfg, plan_removal(self.conn, self.cfg, song), now=WHEN)
        return song

    def tombstone(self, artist: str, title: str, at: str = NOW):
        """A tombstone alone, for a song this library never held."""
        from caracole.songs import Song

        key = identity_key(artist, title)
        stone = Song(id=0, key=key, artist=artist, title=title, artists=[artist], album=None, duration_ms=None,
                     isrc=None, source_ids={"wanted": [key]}, added_at=at, variant=None, status="wanted",
                     review=False, match_decision=None, match_step=None, match_score=None, match_artist_key=None,
                     match_song_key=None)
        return mark_removed(self.conn, stone, at)

    def songbook(self, name: str, entries: Sequence[str], settings: Mapping[str, Setting] | None = None) -> None:
        path = songbooks_file(self.cfg.library_dir)
        make_songbook(path, name, list(entries))
        for entry, setting in (settings or {}).items():
            set_song_setting(path, name, entry, setting)

    # --- reading it ------------------------------------------------------------------------------------------

    def overrides(self) -> Overrides:
        return load_overrides(self.cfg.overrides_file) if self.cfg.overrides_file.exists() else Overrides()

    def books(self) -> list:
        return load_songbooks(songbooks_file(self.cfg.library_dir))

    def units(self) -> dict[str, sync.Unit]:
        return sync.library_state(self.conn, self.overrides(), self.books())

    def digests(self) -> dict[str, str]:
        return {unit_id: unit.digest for unit_id, unit in self.units().items()}

    def document(self, unit_id: str) -> dict[str, Any] | None:
        """``GET /api/peer/unit``'s answer, as it comes over the wire (JSON there and back)."""
        doc = sync.unit_document(self.conn, self.cfg, self.overrides(), self.books(), unit_id)
        return None if doc is None else json.loads(json.dumps(doc, ensure_ascii=False))

    def source(self) -> Source:
        return Source(self)

    def take(self, other: Library, unit_ids: Sequence[str], *, expected_here: Mapping[str, str | None] | None = None,
             now: str = NOW) -> sync.Applied:
        """This library takes ``unit_ids`` from ``other``, each as ``other`` holds it now."""
        theirs = other.digests()
        return sync.apply_units(self.conn, self.cfg, other.source(), [(u, theirs.get(u)) for u in unit_ids], now,
                                expected_here=expected_here)


class Source:
    """A ``peer_sync.UnitSource`` reading another library as its caracole serve would answer: a unit's document,
    and a kept file while it is as kept. ``asked`` lists the files asked for."""

    def __init__(self, library: Library):
        self.library = library
        self.asked: list[tuple[str, str]] = []

    def unit(self, unit_id: str) -> dict[str, Any] | None:
        doc = self.library.document(unit_id)
        return None if doc is None else doc["unit"]

    def file(self, key: str, name: str, sha256: str) -> bytes:
        self.asked.append((key, name))
        data = sync.song_file(self.library.conn, self.library.cfg.library_dir, key, name)
        if data is None:
            raise sync.UnitError(f"{name}: there, no such file is kept")
        return data


def rich(library: Library) -> None:
    """A unit of every kind, and an entry of every overrides.toml table: Radiohead - Creep with every table about a
    song, two songs of one artist, a Chinese name and one beyond the BMP, versions 99 and 101 (BINARY order), a
    song's carried kv, a tombstone, a songbook with a setting, an alias, an artist's UG page and a blocked tab."""
    creep = library.song("Radiohead", "Creep", entries=EVERY_ENTRY, files={"tab.txt": b"e|--0--|"})
    library.song("Radiohead", "Karma Police", sheet=b"[Em]Karma", tab="99", entries={"version": "key=Am&capo=2"})
    vid = upsert_version(library.conn, provider="ug", tab_id="101", song_id=library.song(
        "宋冬野", "斑马，斑马", sheet=b"[C]\xe6\x96\x91\xe9\xa9\xac", tab="99", lyrics="斑马，斑马").id,
        slot="sheet", kind="chords", rating=4.0, votes=3, version=2, label="Ver 2", url="https://u/101b", raw={},
        now=NOW)
    assert vid
    library.song("Bad 🎸 Band", "Riff 𝄞", sheet=b"[E]riff", lyrics=None)
    db.kv_set(library.conn, f"sheet_versions:yours:{creep.id}", "[101]")
    db.kv_set(library.conn, f"sheet_versions:same:{creep.id}:101", "99")
    library.tombstone("Oasis", "Wonderwall")
    library.songbook("Campfire", ["Radiohead - Creep", "Radiohead - Karma Police"],
                     {"Radiohead - Creep": Setting(key="G", capo=2)})
    add_alias(library.cfg.overrides_file, "Soda", "soda-stereo")
    add_artist_url(library.cfg.overrides_file, "宋冬野", "https://www.ultimate-guitar.com/artist/song_dongye_12345")
    add_block(library.cfg.overrides_file, 4242)
