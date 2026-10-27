"""The instruments the sheet viewer draws a sheet's chords for: guitar, ukulele (high G, low G, baritone) and piano.

The instrument is one setting of the viewer, the player's rather than a song's (viewer.js ``state.inst``, kept once
for every page as the rail of necks is, and in the address as ``inst=``). Switching it never moves the song: a
sheet's chord names play as they stand on every instrument, each drawing its own shapes for them. An instrument
with no capo (``capo`` False: the piano) plays the chords as they sound, the capo folded in (version.py
``for_instrument``), and the guitar's capo comes back with the guitar.

``INSTRUMENTS`` lists them in the menu's order, each an ``Instrument``:

- ``id``: its name in the address (``inst=ukulele``) and in the page's data; ``name``, the menu's;
- ``kind``: "strings", a fretted instrument drawn as a chord box (instruments.js ``box``) and a neck, whose
  ``tuning`` is each string's open note as MIDI, in the order a box draws them left to right (a guitar's low E
  first, a ukulele's 4th string first: G4, an octave above its C4 string, re-entrant); "keys", a keyboard strip
  (instruments.js ``keyboard``); any other kind is drawn by a script that registers it (instruments.js
  ``register``), and the viewer offers it only then;
- ``capo``: whether it takes a capo;
- ``shapes``: where the page's ``voicings`` file its chord shapes: "" for the guitar's own keys (voicings.py),
  else the prefix of its table's keys ("ukulele:", "piano:"); ``offset``: its shapes for a root are its table's
  for the root this many semitones up (the baritone's, the ukulele's a fourth lower: 5);
- ``easy``: the name of its table of easy keys (``EASY``), whose chords sit well under the fingers, which the
  viewer's Easy keys row offers before the capo; None for none;
- ``voice``: the sound strum.js makes for it ("guitar", "ukulele", "piano");
- ``sounds``: how many semitones its notes sound above where its music is written (0: at concert pitch);
- ``about``: a line on it, under the settings' Instrument row.

Their shapes, all from the chord's name alone:

- the ukuleles' are chords-db's (``voicings-ukulele.json``, voicings.py), filed by the guitar's keys
  (``voicings.voicing_keys``), so a page needs no other: a quality the ukulele file has is its own, one it has
  not (a power chord; a chord of five notes or more, whose four-string shapes leave the root out) its nearest
  (``ukulele_quality``), and a slash chord the plain chord, its bass left to the bass player. High G and low G
  share them: only the 4th string's octave differs. The baritone (DGBE) plays the same shapes a fourth lower
  (``offset``): a ukulele's C shape is its G, as the guitar's top four strings are tuned;
- the piano's are computed from the chord's notes (``piano_positions``): root position, then two inversions to
  step through as a guitar's shapes are, the right hand around middle C, and a left-hand bass, the root or a
  slash chord's bass, lowest.

``chord_shapes`` gives the shapes the viewer shows a chord on an instrument (viewer.js ``shapesOf``), for what
shows the same beside the page; ``page_voicings`` and ``entries`` are what a page's data carries (page.py).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from caracole.viewer.theory import MODES, QUALITIES, SCALES, Chord, Key, key_name
from caracole.viewer.voicings import TUNING, Position, _nearest, load_voicings, voicing_keys


@dataclass(frozen=True)
class Instrument:
    """An instrument the viewer draws chords for (the module's docstring)."""

    id: str
    name: str
    kind: str
    tuning: tuple[int, ...] = ()
    capo: bool = True
    shapes: str = ""
    easy: str | None = None
    voice: str = "guitar"
    sounds: int = 0
    offset: int = 0
    about: str = ""


GUITAR = Instrument("guitar", "Guitar", "strings", TUNING, about="Standard tuning, E A D G B E.")
UKULELE = Instrument("ukulele", "Ukulele", "strings", (67, 60, 64, 69), shapes="ukulele:", easy="ukulele",
                     voice="ukulele", about="G C E A, the G string high.")  # G4 C4 E4 A4: re-entrant
UKULELE_LOW_G = Instrument("ukulele-low-g", "Ukulele, low G", "strings", (55, 60, 64, 69), shapes="ukulele:",
                           easy="ukulele", voice="ukulele", about="G C E A, the G string low.")  # G3 C4 E4 A4
BARITONE = Instrument("baritone", "Baritone ukulele", "strings", (50, 55, 59, 64), shapes="ukulele:",
                      easy="baritone", voice="ukulele", offset=5,
                      about="D G B E, as a guitar's top four strings: a ukulele's shapes, named a fourth lower.")
PIANO = Instrument("piano", "Piano", "keys", capo=False, shapes="piano:", voice="piano",
                   about="The chords as they sound, any capo folded in: root position and two inversions, "
                         "with a bass for the left hand.")

INSTRUMENTS: tuple[Instrument, ...] = (GUITAR, UKULELE, UKULELE_LOW_G, BARITONE, PIANO)
_BY_ID = {i.id: i for i in INSTRUMENTS}


def instrument(name: str | None) -> Instrument:
    """The instrument an address names (``inst=ukulele``), the guitar for none or one caracole has not."""
    return _BY_ID.get(name or "", GUITAR)


# The keys whose chords sit well on each table's instrument: the tonics of its easy major keys, then of its easy
# minor ones. The ukulele's C, F, G, Bb, Am, Dm; the baritone's, the same shapes a fourth lower: G, C, D, F, Em, Am.
EASY: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "ukulele": ((0, 5, 7, 10), (9, 2)),
    "baritone": ((7, 0, 2, 5), (4, 9)),
}


def is_easy(table: str, key: Key) -> bool:
    """Whether ``key`` is easy on the instruments of ``table`` (``EASY``): a major or minor key by its tonic, another
    mode by its notes, those of an easy major key (D dorian's are C major's)."""
    majors, minors = EASY[table]
    if key.mode == "ionian":
        return key.tonic in majors
    if key.mode == "aeolian":
        return key.tonic in minors
    return (key.tonic - SCALES["ionian"][MODES.index(key.mode)]) % 12 in majors


def easy_keys(table: str) -> dict[str, list[list[Any]]]:
    """The easy keys of ``table`` in every mode, as the page's data gives them (``easy[table][mode]``): each
    ``[tonic, name]``, its pitch class and its name (``theory.key_name``), in the order of the pitch classes. The
    viewer offers them nearest the key played first. A copy of the answer kept."""
    return {mode: [list(entry) for entry in keys] for mode, keys in _easy_keys(table)}


@lru_cache(maxsize=None)
def _easy_keys(table: str) -> tuple[tuple[str, tuple[tuple[int, str], ...]], ...]:
    return tuple((mode, tuple((tonic, key_name(Key(tonic, mode))) for tonic in range(12)
                              if is_easy(table, Key(tonic, mode)))) for mode in MODES)


# --- the ukuleles' shapes ---------------------------------------------------------------------------------


def ukulele_quality(fingering: str) -> str:
    """The quality the ukulele shows for a chord the guitar files under ``fingering`` (a quality,
    ``voicings.voicing_keys``): the same where the ukulele file has it, else its nearest (``voicings._nearest``):
    C5 is C, C9 C7."""
    data = load_voicings("ukulele")
    if fingering in data:
        return fingering
    return _nearest(Chord(0, fingering) if fingering in QUALITIES else Chord(0, ""), data)


def ukulele_shapes(fingering: str) -> list[list[Position]]:
    """The ukulele's shapes for a chord the guitar files under ``fingering``, on every root (pitch class 0, C,
    first), as high G and low G play them; the baritone's for a root are those of the root five semitones up."""
    return load_voicings("ukulele")[ukulele_quality(fingering)]


# --- the piano's -------------------------------------------------------------------------------------------

LOW, HIGH = 53, 64  # the right hand's lowest note, F3 to E4: a chord around middle C
BASS = 41  # the left hand's bass, F2 to E3, below every right-hand note


def stacked(chord: Chord) -> list[int]:
    """The chord's intervals as a pianist stacks them up from the root: the third (or a sus chord's second or
    fourth), the fifth, the seventh or sixth, then what is left above the octave, a ninth, an eleventh, a
    thirteenth (C13: C E G Bb D A; Cadd9: C E G D; C6: C E G A)."""
    intervals = chord.intervals
    third = 4 if 4 in intervals else 3 if 3 in intervals else None
    if third is None:
        third = 5 if 5 in intervals else 2 if 2 in intervals else None  # sus4, sus2
    fifth = 7 if 7 in intervals else 6 if 6 in intervals else 8 if 8 in intervals else None
    seventh = 10 if 10 in intervals else 11 if 11 in intervals else 9 if 9 in intervals else None
    ranks = {0: 0, third: 1, fifth: 2, seventh: 3}
    return sorted(intervals, key=lambda i: (ranks[i], i) if i in ranks else (4, i + 12))


def piano_positions(chord: Chord) -> list[list[int]]:
    """The piano's positions of a chord, each ``[bass, *right hand]`` as MIDI notes, low to high: root position,
    then its first and second inversions (fewer for a chord of two notes), each moved by octaves so that its lowest
    note is from F3 to E4 (``LOW``, ``HIGH``); the bass, the root or a slash chord's bass, from F2 to E3 (``BASS``),
    below them all. A slash chord's right hand plays the chord's own notes, its bass the left hand's."""
    root_position = []
    for interval in stacked(chord):
        pc = (chord.root + interval) % 12
        if not root_position:
            root_position.append(LOW + (pc - LOW) % 12)
        else:
            last = root_position[-1]
            root_position.append(last + ((pc - last) % 12 or 12))
    positions = [root_position]
    for _ in range(min(3, len(root_position)) - 1):
        before = positions[-1]
        moved = sorted(before[1:] + [before[0] + 12])
        octaves = -12 * ((moved[0] - LOW) // 12)
        positions.append([note + octaves for note in moved])
    low = chord.root if chord.bass is None else chord.bass
    bass = BASS + (low - BASS) % 12
    return [[bass, *notes] for notes in positions]


def piano_key(chord: Chord) -> str:
    """Where the page's ``voicings`` file a chord's piano positions on every root: "piano:" and its suffix as shown,
    then "|" and its bass's interval above the root, if any ("piano:m7|", "piano:|4" for C/E). viewer.js builds the
    same from the chord's data."""
    bass = "" if chord.bass is None else str((chord.bass - chord.root) % 12)
    return f"piano:{chord.suffix}|{bass}"


def on_root(chord: Chord, root: int) -> Chord:
    """``chord`` with ``root`` as its root, its bass moved with it."""
    if chord.bass is None:
        return replace(chord, root=root)
    return replace(chord, root=root, bass=(chord.bass - chord.root + root) % 12)


def piano_table(chord: Chord) -> list[list[list[int]]]:
    """The piano's positions of ``chord``'s kind on every root (pitch class 0, C, first): a copy of the answer
    kept."""
    return [[list(p) for p in positions] for positions in _piano_table(chord)]


@lru_cache(maxsize=4096)
def _piano_table(chord: Chord) -> tuple[tuple[tuple[int, ...], ...], ...]:
    return tuple(tuple(map(tuple, piano_positions(on_root(chord, root)))) for root in range(12))


# --- what a chord shows, and what a page carries ------------------------------------------------------------


def chord_shapes(inst: Instrument, chord: Chord, shift: int = 0,
                 given: dict[str, dict[str, Any]] | None = None) -> list[Any]:
    """The shapes the viewer shows ``chord`` moved ``shift`` semitones on ``inst`` (viewer.js ``shapesOf``), in its
    order: on the guitar the shapes the sheet gives that very chord first (``given``: ``voicings.sheet_shapes``),
    else chords-db's for its slash chord, else for its quality; on a ukulele the ukulele's for its quality
    (``ukulele_shapes``, at the instrument's ``offset``); on the piano its positions (``piano_positions``)."""
    root = (chord.root + shift) % 12
    if inst.kind == "keys":
        return piano_positions(on_root(chord, root))
    fingering, _, slash = voicing_keys(chord)
    if inst.shapes == "ukulele:":
        return list(ukulele_shapes(fingering)[(root + inst.offset) % 12])
    shown = f"{root},{chord.suffix},{'' if chord.bass is None else (chord.bass + shift) % 12}"
    if given and shown in given:
        return list(given[shown]["list"])
    data = load_voicings()
    if slash is not None and slash in data and data[slash][root]:
        return list(data[slash][root])
    return list(data[fingering][root]) if fingering in data else []


def page_voicings(fingerings: set[str], chords: list[Chord]) -> dict[str, Any]:
    """What the instruments add to a page's ``voicings``, beside the guitar's (``voicings.page_voicings``): the
    ukulele's shapes of each quality it shows for a guitar key the page's chords use (``fingerings``,
    ``voicings.voicing_keys``; ``ukulele_quality``; a slash key has none, as the plain chord is shown), under
    "ukulele:" ("ukulele:m7"), and for each chord's kind (``chords``) the piano's positions (``piano_key``), each on
    every root."""
    out: dict[str, Any] = {}
    uke = load_voicings("ukulele")
    for fingering in sorted(fingerings):
        if "/" not in fingering:
            quality = ukulele_quality(fingering)
            out["ukulele:" + quality] = uke[quality]
    for chord in chords:
        out.setdefault(piano_key(chord), piano_table(on_root(chord, 0)))
    return out


def entries(fingerings: set[str]) -> list[dict[str, Any]]:
    """The instruments as the page's data lists them (``instruments``), in the menu's order: each one's fields (the
    module's docstring), a fretted one's ``tuning``, and, for a ukulele, ``near``: each guitar key of the page's
    (``fingerings``) whose chords it shows as another quality, with that quality (``ukulele_quality``), where its
    shapes are filed ("ukulele:" and it) and what the card's note names ("No shape for this chord here: C is the
    closest")."""
    out = []
    for inst in INSTRUMENTS:
        entry: dict[str, Any] = {"id": inst.id, "name": inst.name, "kind": inst.kind, "capo": inst.capo,
                                 "shapes": inst.shapes, "offset": inst.offset, "easy": inst.easy, "voice": inst.voice,
                                 "sounds": inst.sounds, "about": inst.about}
        if inst.tuning:
            entry["tuning"] = list(inst.tuning)
        if inst.shapes == "ukulele:":
            entry["near"] = {f: q for f in sorted(fingerings) if "/" not in f and (q := ukulele_quality(f)) != f}
        out.append(entry)
    return out

