"""Each song's progressions, for finding songs by them: the library page's ``#prog=``, the served
search and ``caracole search --progression``.

**Read as the sheet is rendered.** render.py hands this module each song's sheet as it writes its
.cho (the human sheet, else the auto one), and ``record`` keeps what ``sheet_progressions`` reads
of it in kv ``render:progressions:<song id>``: the key the viewer reads the sheet in
(``page.viewer_key``, the song's own key first), and each section's progression
(``viewer.harmony.progressions``): its numerals, one cycle, its repeats, its name from
``harmony.CATALOGUE``, how it ends, and ``harmony.progression_key``, the same in every key and
rotation. A song with no sheet, or one whose sheet has no chord caracole can read, has no record.
So the library page reads one kv row a song, never a sheet; a library rendered by an older caracole
has its records after the next render, which a new viewer (``page.BUILD_FILES``) brings anyway.

**For searching**, a progression is a section's cycle of two chords or more (a section held on one
chord is none). ``read_progression`` reads what you type: numerals ("vi IV I V", "vi–IV–I–V",
"bVII" for ♭VII, the chord's quality and extensions ignored, as the key ignores them), or a
catalogue name or a word of one ("andalusian", "the pop progression", "blues"; a short word alone,
"pop", is too common a word to be a name). A progression the catalogue names stands for every
progression of that name: the pop progression is I–V–vi–IV and, read in the relative minor,
i–♭VI–♭III–♭VII, so a song whose key caracole read as A minor rather than C major is found either
way. ``songs_with`` gives the songs that play it, with the sections that do.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from caracole.db import kv_delete, kv_get_json, kv_set_json
from caracole.normalize import fold

if TYPE_CHECKING:
    from caracole.songs import Song

KV = "render:progressions:"  # kv, then the song's id: its sheet's progressions (``record``)

# What a section with no heading is called where its name is said.
UNNAMED = "untitled section"

_ROMAN = r"(?:VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)"
# A numeral as you type it: an accidental, the Roman numeral, its quality and extensions, a slash's.
_TYPED = re.compile(rf"[♭♯b#]?{_ROMAN}(?:maj|add|sus|dim|aug|[°ø+o0-9♭♯#b])*(?:/[♭♯b#]?(?:{_ROMAN}|[0-9]+))*")
_SEPARATORS = re.compile(r"[\s,–—-]+")
_WORD = re.compile(r"[^\W_]+")
_APOSTROPHES = re.compile(r"['’‘`´ʼ]")
# Words every name has, which name none alone; and what a name's other words must come to, letters alone.
_GENERIC = frozenset({"the", "a", "of", "progression", "cadence", "chords"})
_NAME_LETTERS = 5


@dataclass(frozen=True)
class Wanted:
    """A progression asked for: ``key``, its own (``harmony.progression_key``), the first of ``keys``,
    every key a song may play it as (each of its name's); ``name``, the catalogue's; ``label``, how
    it is said: "I–V–vi–IV" typed, "the Andalusian cadence" named."""

    key: str
    keys: frozenset[str]
    name: str | None
    label: str


def label(key: str) -> str:
    """A progression's key as it is written: "I V vi IV" -> "I–V–vi–IV"."""
    return "–".join(key.split())


def catalogue() -> dict[str, str]:
    """Each progression of ``harmony.CATALOGUE`` by its key: {"I V vi IV": "the pop progression", ...}."""
    from caracole.viewer.harmony import CATALOGUE, progression_key

    names: dict[str, str] = {}
    for name, numerals in CATALOGUE:
        names.setdefault(progression_key(numerals), name)
    return names


def key_words(key: Any) -> str:
    """"C major", "A minor", "D Dorian"."""
    from caracole.viewer.theory import spelling

    mode = {"ionian": "major", "aeolian": "minor"}.get(key.mode, key.mode.capitalize())
    return f"{spelling(key)[key.tonic]} {mode}"


def sheet_progressions(cho: str, key: str | None) -> dict[str, Any] | None:
    """What a ChordPro sheet plays, as ``record`` keeps it: ``{"key": "C major", "sections": [{"section",
    "numerals", "repeats", "name", "ending", "key"}]}``, each section's ``section`` its heading (None for
    none), in the key its viewer reads it in (``key``, the song's, else the sheet's own, else estimated).
    The chords of a chord legend's line (its fingerings) are no chords played; one caracole can't read
    (N.C.) is left out. None for a sheet with no chord it can read."""
    from caracole.viewer.harmony import progression_key, progressions
    from caracole.viewer.page import viewer_key
    from caracole.viewer.sheet import ChordRow, Lyrics, parse_sheet, written
    from caracole.viewer.theory import parse_chord
    from caracole.viewer.voicings import chord_legend

    shapes = viewer_key(cho, key)
    if shapes is None:
        return None
    sheet = parse_sheet(cho)
    sections = []
    for section in sheet.sections:
        played = []
        for line in section.lines:
            if not isinstance(line, (Lyrics, ChordRow)) or chord_legend(written(line, sheet.chords)):
                continue
            items = [c for c, _ in line.parts] if isinstance(line, Lyrics) else line.items
            played += [parse_chord(sheet.chords[i], strict=False) for i in items if isinstance(i, int)]
        sections.append((section.label or "", played))
    found = progressions(sections, shapes)
    if not found:
        return None
    return {"key": key_words(shapes), "sections": [
        {"section": name or None, "numerals": list(p.numerals), "repeats": p.repeats, "name": p.name,
         "ending": p.ending, "key": progression_key(p.numerals)}
        for name, p in found
    ]}


def record(conn: sqlite3.Connection, song_id: int, cho: str, key: str | None) -> None:
    """Keep what the song's sheet ``cho`` plays (``sheet_progressions``), in the key ``key``, in kv
    ``render:progressions:<song id>``, written only when it changed; a sheet that plays nothing leaves
    no record."""
    found = sheet_progressions(cho, key)
    if found is None:
        forget(conn, song_id)
    elif kv_get_json(conn, f"{KV}{song_id}") != found:
        kv_set_json(conn, f"{KV}{song_id}", found)


def forget(conn: sqlite3.Connection, song_id: int) -> None:
    """The song keeps no sheet: no progressions."""
    kv_delete(conn, f"{KV}{song_id}")


def _searchable(record: Any) -> list[dict[str, Any]]:
    """A record's sections that are progressions to search: a cycle of two chords or more, its key
    and numerals well formed (a record is the database's, but read as data all the same)."""
    sections = record.get("sections") if isinstance(record, dict) else None
    found = []
    for s in sections if isinstance(sections, list) else []:
        if not isinstance(s, dict) or not isinstance(s.get("key"), str) or " " not in s["key"]:
            continue
        numerals = s.get("numerals")
        if not isinstance(numerals, list) or not all(isinstance(n, str) for n in numerals):
            continue
        found.append(s)
    return found


def _records(conn: sqlite3.Connection, *, whole: bool = False) -> dict[int, Any]:
    """Every song's searchable sections, by song id, those of a song with some; with ``whole``, each
    song's record as it is kept."""
    import json

    found: dict[int, Any] = {}
    rows = conn.execute("SELECT key, value FROM kv WHERE substr(key, 1, ?) = ?", (len(KV), KV))
    for key, value in rows:
        number = key[len(KV):]
        if not (number.isascii() and number.isdigit()):
            continue
        try:
            record = json.loads(value)
        except ValueError:
            continue
        if sections := _searchable(record):
            found[int(number)] = record if whole else sections
    return found


def any_recorded(conn: sqlite3.Connection) -> bool:
    """Whether any song's progressions were read: a library rendered by an older caracole has none
    until its next render."""
    return conn.execute("SELECT 1 FROM kv WHERE substr(key, 1, ?) = ? LIMIT 1", (len(KV), KV)).fetchone() is not None


def library_progressions(conn: sqlite3.Connection) -> dict[int, list[dict[str, str]]]:
    """What the library page's data gives each song: its progressions, each once, in the order its
    sheet plays them, ``{"key": "I V vi IV", "plays": "vi–IV–I–V"}`` (as its first section that plays
    it does)."""
    found: dict[int, list[dict[str, str]]] = {}
    for song_id, sections in _records(conn).items():
        seen: dict[str, str] = {}
        for s in sections:
            seen.setdefault(s["key"], "–".join(s["numerals"]))
        found[song_id] = [{"key": k, "plays": plays} for k, plays in seen.items()]
    return found


def read_progression(text: str) -> Wanted | None:
    """The progression ``text`` asks for: numerals, two chords or more ("vi IV I V"), or a catalogue
    name or words of one ("andalusian"); None for anything else."""
    from caracole.viewer.harmony import progression_key

    names = catalogue()
    tokens = [t for t in _SEPARATORS.split(text.strip()) if t]
    if tokens and all(_TYPED.fullmatch(t) for t in tokens):
        key = progression_key(tokens)
        if " " not in key:
            return None
        name = names.get(key)
        return Wanted(key, frozenset({key, *_named(names, {name})}), name, label(key))
    words = _words(text)
    rest = [w for w in words if w not in _GENERIC]
    if not rest or (len(rest) == len(words) and sum(map(len, rest)) < _NAME_LETTERS):
        return None
    found = [name for name in dict.fromkeys(names.values()) if set(words) <= set(_words(name))]
    if not found:
        return None
    keys = [k for k, name in names.items() if name in found]
    return Wanted(keys[0], frozenset(keys), found[0], " or ".join(found))


def _named(names: dict[str, str], wanted: set[str | None]) -> list[str]:
    return [k for k, name in names.items() if name in wanted]


def _words(text: str) -> list[str]:
    return _WORD.findall(_APOSTROPHES.sub("", fold(text)))


@dataclass(frozen=True)
class Playing:
    """A song of yours that plays a progression: the sections that do (``UNNAMED`` for one with no
    heading), and the key its sheet was read in ("C major")."""

    song: Song
    sections: list[str]
    key: str


def songs_with(conn: sqlite3.Connection, wanted: Wanted) -> list[Playing]:
    """Your songs that play ``wanted`` (any of its keys), by name."""
    from caracole.songs import list_songs

    records = _records(conn, whole=True)
    found = []
    for song in sorted(list_songs(conn), key=lambda s: (s.display.casefold(), s.id)):
        record = records.get(song.id)
        sections = [s.get("section") or UNNAMED for s in _searchable(record) if s["key"] in wanted.keys]
        if sections:
            key = record.get("key")
            found.append(Playing(song, list(dict.fromkeys(str(s) for s in sections)),
                                 key if isinstance(key, str) else ""))
    return found
