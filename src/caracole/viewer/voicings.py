"""Guitar fingerings for the sheet viewer, from chords-db (MIT; see LICENSE-chords-db).

``voicings.json`` is a subset of chords-db's ``lib/guitar.json`` (commit df06fa7b,
https://github.com/tombatossals/chords-db), made by ``subset_chords_db``: the qualities
the viewer names (``theory.QUALITIES``), and the major and minor slash chords, each
position checked against the notes it sounds (``notes_of``) and dropped when it plays a
note outside its chord. To make it again::

    python -m caracole.viewer.voicings guitar.json src/caracole/viewer/voicings.json

A position is ``[frets, fingers, base fret, barres]``: ``frets`` has one character per
string, low E first, "x" for a muted one, "0" for an open one, else the fret counted
from the base fret (1 is the base fret itself); ``fingers`` likewise, 0 for none; and
``barres`` lists the frets (counted the same way) a finger lays across.

The data is filed by quality and root: ``data[quality][root]`` is the root's positions
(pitch class 0, C, first). A slash chord's quality is "<quality>/<bass interval>", so
C/E is ``data["/4"][0]`` and Am/G ``data["m/10"][9]``.
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from caracole.viewer.theory import QUALITIES, Chord, note_pc

DATA_FILE = Path(__file__).with_name("voicings.json")
LICENSE_FILE = Path(__file__).with_name("LICENSE-chords-db")
SOURCE = "chords-db by David Rubert (MIT): https://github.com/tombatossals/chords-db"

TUNING = (40, 45, 50, 55, 59, 64)  # E2 A2 D3 G3 B3 E4, as MIDI notes
MAX_POSITIONS = 4

# chords-db's suffixes, by the quality caracole calls them.
_SUFFIXES = {
    "major": "", "minor": "m", "dim": "dim", "dim7": "dim7", "aug": "aug", "5": "5",
    "sus2": "sus2", "sus4": "sus4", "7sus4": "7sus4", "6": "6", "69": "69", "m6": "m6",
    "m69": "m69", "7": "7", "7b5": "7b5", "aug7": "aug7", "7b9": "7b9", "7#9": "7#9",
    "9": "9", "11": "11", "13": "13", "maj7": "maj7", "maj9": "maj9", "m7": "m7",
    "m7b5": "m7b5", "m9": "m9", "m11": "m11", "mmaj7": "mmaj7", "add9": "add9",
    "madd9": "madd9", "add11": "add11",
}
_SLASH = re.compile(r"(m?)/([A-G])(#|b)?")
_ROOTS = {"C": 0, "Csharp": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "Fsharp": 6, "G": 7, "Ab": 8,
          "A": 9, "Bb": 10, "B": 11}

Position = list[Any]  # [frets, fingers, base fret, barres]


def notes_of(position: Position) -> list[int]:
    """The MIDI notes a position sounds, low string first."""
    frets, _, base, _ = position
    notes = []
    for string, fret in zip(TUNING, frets, strict=True):
        if fret == "x":
            continue
        n = int(fret)
        notes.append(string + (n + base - 1 if n else 0))
    return notes


def subset_chords_db(doc: dict[str, Any]) -> dict[str, list[list[Position]]]:
    """chords-db's guitar data as the viewer files it (see the module's docstring)."""
    data: dict[str, list[list[Position]]] = {}
    for db_root, entries in doc["chords"].items():
        root = _ROOTS[db_root]
        for entry in entries:
            key = _key(entry["suffix"], root)
            if key is None:
                continue
            quality, _, interval = key.partition("/")
            bass = None if not interval else (root + int(interval)) % 12
            chord = Chord(root, quality, bass)
            positions: list[Position] = []
            for p in map(_compact, entry["positions"]):
                if p and _plays(p, chord) and all(p[0] != q[0] for q in positions):
                    positions.append(p)  # the first fingering of the same frets
            if positions:
                data.setdefault(key, [[] for _ in range(12)])[root] = positions[:MAX_POSITIONS]
    return data


def _key(suffix: str, root: int) -> str | None:
    if suffix in _SUFFIXES:
        return _SUFFIXES[suffix]
    if m := _SLASH.fullmatch(suffix):
        minor, letter, accidental = m.groups()
        return f"{minor}/{(note_pc(letter, accidental or '') - root) % 12}"
    return None


def _compact(position: dict[str, Any]) -> Position | None:
    frets, fingers = position.get("frets"), position.get("fingers")
    if not (isinstance(frets, list) and isinstance(fingers, list) and len(frets) == len(TUNING)):
        return None
    if any(not isinstance(f, int) or f > 9 for f in frets + fingers):
        return None
    return [
        "".join("x" if f < 0 else str(f) for f in frets),
        "".join(str(max(f, 0)) for f in fingers),
        int(position.get("baseFret", 1)),
        [int(b) for b in position.get("barres", [])],
    ]


def _plays(position: Position, chord: Chord) -> bool:
    """Whether the position sounds its chord: no other note, the root, and a slash chord's bass lowest."""
    notes = notes_of(position)
    pcs = {n % 12 for n in notes}
    if not notes or not pcs <= chord.pitch_classes or chord.root not in pcs:
        return False
    return chord.bass is None or min(notes) % 12 == chord.bass


@lru_cache(maxsize=1)
def load_voicings() -> dict[str, list[list[Position]]]:
    """The vendored fingerings (``voicings.json``)."""
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def voicing_keys(chord: Chord) -> tuple[str, bool, str | None]:
    """Where a chord's fingerings are filed: (quality, whether it is only the nearest one, slash key).

    A quality without fingerings shows the largest one with them whose notes are all the
    chord's, keeping its third (Cmaj7#11 shows Cmaj7, Cm9b5 Cm7b5); failing that, the
    plain major or minor triad. A major or minor slash chord looks for its own
    fingerings first (the slash key, which may still have none on a given root).
    """
    data = load_voicings()
    quality, nearest = chord.quality, False
    if chord.tones is not None or quality not in data:
        quality, nearest = _nearest(chord, data), True
    slash = None
    if chord.bass is not None and not nearest and quality in ("", "m"):
        candidate = f"{quality}/{(chord.bass - chord.root) % 12}"
        slash = candidate if candidate in data else None
    return quality, nearest, slash


def _nearest(chord: Chord, data: dict[str, Any]) -> str:
    third = next((t for t in (3, 4) if t in chord.intervals), None)
    fitting = [
        q for q in QUALITIES
        if q in data and QUALITIES[q] <= chord.intervals and (third is None or third in QUALITIES[q])
    ]
    if fitting:
        return max(fitting, key=lambda q: len(QUALITIES[q]))  # the first of the largest
    return "m" if third == 3 else ""


def page_voicings(keys: set[str]) -> dict[str, list[list[Position]]]:
    """The fingerings a page needs: those filed under ``keys``, on every root."""
    data = load_voicings()
    return {key: data[key] for key in sorted(keys) if key in data}


def main(argv: list[str]) -> None:
    source, target = Path(argv[0]), Path(argv[1])
    data = subset_chords_db(json.loads(source.read_text(encoding="utf-8")))
    text = json.dumps(data, separators=(",", ":"), sort_keys=True)
    target.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
