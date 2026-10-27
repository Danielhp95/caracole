"""The concert flute and the soprano recorder: their fingerings, the octave a melody is played in, and the notes a
wind player reads off a chord sheet (the key's scale, each chord's tones); with the tables a viewer's data carries.
On top of theory.py and harmony.py.

Notes are MIDI numbers (60 is C4, middle C) as the player **reads** them: the flute reads at concert pitch, C4 to
C7; the soprano recorder reads C4 to D6 and sounds an octave higher (``Wind.sounds``), C5 to D7. Each has a range
it plays at ease (``Wind.easy``): the flute up to D6, above which its third octave grows hard; the recorder up to
G5 (from E5 up its thumb is pinched, and the notes above G5 are hard).

**Fingerings** are facts about the instruments, written by hand in the notation of the Woodwind Fingering Guide's
basic charts (wfg.woodwind.org, checked 2026-10-27), each read into the state of each of the instrument's keys
(``Wind.keys``): "x" pressed or covered, "o" not, "h" half (the recorder's thumb pinched, or one of its double
holes covered). The standard fingering comes first; a note may have others after it.

- The **flute** (Boehm system, closed holes, a C foot): ``thumb`` (the B key) and ``thumb-Bb`` (the Briccialdi
  lever); ``L1`` ``L2`` ``L3``, the left hand's fingers, and ``G#`` its little finger's key; ``R1`` ``R2`` ``R3``, the
  right hand's, ``Eb`` its little finger's key, which stays down on all but C4, C#4, D4, D5, A#6, B6 and C7, and the
  foot's ``C#`` and ``C`` rollers; ``trill-D`` and ``trill-D#``, the two trill keys, which B♭6 and B6 take. The second
  octave is the first overblown (D5 and E♭5 lift the first finger to vent); C6 and C#6 are C5's and C#5's. B♭ is
  "one and one" (``T 1--|1-- Eb``), then the thumb lever (``Bb 1--|--- Eb``). The chart's notation: the thumb
  (``T``, ``Bb`` or ``-``), the left hand's fingers (a digit for each pressed, ``-`` not) and ``G#``, a bar, the right
  hand's, then its other keys (``Eb``, ``C#``, ``C``, ``TrD``, ``TrD#``).
- The **soprano recorder**: ``thumb``, ``L1`` to ``L3``, ``R1`` to ``R4`` (``R3`` and ``R4`` double holes on most) and
  ``bell``, closed on the knee for C#6 alone. Two systems (``Wind.systems``): **baroque** (English) fingering,
  caracole's, and **German**, which differs only on F4, F#4, G#4, F5 and F#5 (German F4 is ``T 123|4---``, the
  baroque one forked, ``T 123|4-67``). The chart's notation: the thumb (``T`` covered, ``t`` pinched, ``-`` open),
  the left hand's three holes, a bar, the right hand's four (a digit covered, ``h`` half, ``-`` open), then ``X`` for
  the bell closed.

**The octave a melody is played in** (``fit``): the melody as it sounds, moved by whole octaves, with as few of the
notes the instrument then reads as can be outside its range, then outside its easy range, then moved as little as
can be (up rather than down). A melody sung G4 to E5 stays there on a flute; a recorder reads it as written and so
sounds it an octave up. A low voice's C3 to E4 comes up an octave on a flute, and two on a recorder (read C4 to E5).
A melody high in the flute's third octave comes down one.

**Off a chord sheet**, with no melody: the key's scale and each chord's tones, in the notes both instruments read
alike: the tonic or the root in the octave C4 to B4, the lowest of each. ``scale_notes``: the scale up to the
tonic's octave. ``chord_notes``: the chord's tones in harmony.py's order (``harmony.chord_tones``: the root, the
third, the fifth, the seventh, the ninth...), each above the one before, but an 11th or a 13th an octave lower, as
a 4th or a 6th, so that no tone is more than 15 semitones above the root (``chord_steps``) and the highest, on a
B, is D6, the recorder's highest note: the same shape in every key. ``solfege`` names a note Do, Re, Mi... as
Spanish-speaking players read it.

**The tables** a viewer's data carries, for viewer.js to look up: it computes no theory of its own. A chord's notes
and a key's scale are the same steps above the root or the tonic in every key, so nothing in them changes with the
transposition: the page finds a note as ``low`` + the pitch class of the root (or the tonic) as shown + a step, as
it finds a note of the key's scale on the neck (harmony_tables.py's ``keyScale``, whose steps, then 12, are the
scale ``scale_notes`` gives).

- ``fingering_data()``, the same for every page: ``{"low": 60, "flute": {"keys": [...], "notes": [...]},
  "recorder": {"holes": [...], "baroque": [...], "german": [...]}, "solfege": {"C": "Do", ...}}``: each note's
  fingering from C4 up (index: the note read − ``low``), the flute's as a list of its fingerings, the standard one
  first, the recorder's the one of each system, each a string of a state a key ("x", "o", "h"), in the order of
  ``keys`` (``holes``); ``solfege``, the syllable for each letter, which keeps its sharps or flats ("Sib");
- ``tables(chords, key, mapped, alts)``, for a sheet: ``windForms``, each chord's steps above its root
  (``chord_steps``), each list once, shared by the chords that have it; ``windChords[mode][i]``, chord ``i``'s (by
  its index in ``windForms``) as ``data.mapped[mode]`` has it, or null for a chord caracole can't read, and
  ``windAlts[mode][i][j]``, those of the chords ``data.alts[mode][i]`` offers instead. With no key, the sheet's
  own chords alone, under the mode ``""`` (as ``data.names`` has them). The notes are in the order of
  harmony_tables.py's ``tones``, one for each name it lists for the chord.

The answers are kept (``functools`` caches), as theory.py's are: these dataclasses are frozen, and a list handed out
is a copy.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from caracole.viewer import harmony
from caracole.viewer.theory import _NATURAL, MODES, SCALES, Chord, Key

_LETTERS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
SOLFEGE = {"C": "Do", "D": "Re", "E": "Mi", "F": "Fa", "G": "Sol", "A": "La", "B": "Si"}
FLUTE_KEYS = ("thumb-Bb", "thumb", "L1", "L2", "L3", "G#", "R1", "R2", "R3", "Eb", "C#", "C", "trill-D", "trill-D#")
RECORDER_HOLES = ("thumb", "L1", "L2", "L3", "R1", "R2", "R3", "R4", "bell")
_HIGHEST_STEP = 15  # above a root in C4 to B4: B4 + 15 is D6, the recorder's highest note


@dataclass(frozen=True)
class Wind:
    """A wind instrument: the lowest and highest notes it reads, how far above them it sounds, the notes it reads
    at ease (lowest, highest), its keys (or holes) as a fingering's states name them, and its fingering systems,
    the first its usual one."""

    name: str
    low: int
    high: int
    sounds: int
    easy: tuple[int, int]
    keys: tuple[str, ...]
    systems: tuple[str, ...]


FLUTE = Wind("flute", 60, 96, 0, (60, 86), FLUTE_KEYS, ("boehm",))
RECORDER = Wind("recorder", 60, 86, 12, (60, 79), RECORDER_HOLES, ("baroque", "german"))
WINDS = {"flute": FLUTE, "recorder": RECORDER}


@dataclass(frozen=True)
class Fingering:
    """A note's fingering: as a chart writes it, and the state of each of the instrument's keys ("x", "o", "h")."""

    chart: str
    states: tuple[str, ...]

    @property
    def text(self) -> str:
        """The states in one string, as the page's data carries them: "xxxxxxxxo"."""
        return "".join(self.states)


# The flute's standard fingerings, C4 to C7 (the Woodwind Fingering Guide's basic chart; then other fingerings).
_FLUTE_CHART: dict[str, tuple[str, ...]] = {
    "C4": ("T 123|123 C",),
    "C#4": ("T 123|123 C#",),
    "D4": ("T 123|123",),
    "D#4": ("T 123|123 Eb",),
    "E4": ("T 123|12- Eb",),
    "F4": ("T 123|1-- Eb",),
    "F#4": ("T 123|--3 Eb",),
    "G4": ("T 123|--- Eb",),
    "G#4": ("T 123 G#|--- Eb",),
    "A4": ("T 12-|--- Eb",),
    "A#4": ("T 1--|1-- Eb", "Bb 1--|--- Eb"),
    "B4": ("T 1--|--- Eb",),
    "C5": ("- 1--|--- Eb",),
    "C#5": ("- ---|--- Eb",),
    "D5": ("T -23|123",),
    "D#5": ("T -23|123 Eb",),
    "E5": ("T 123|12- Eb",),
    "F5": ("T 123|1-- Eb",),
    "F#5": ("T 123|--3 Eb",),
    "G5": ("T 123|--- Eb",),
    "G#5": ("T 123 G#|--- Eb",),
    "A5": ("T 12-|--- Eb",),
    "A#5": ("T 1--|1-- Eb", "Bb 1--|--- Eb"),
    "B5": ("T 1--|--- Eb",),
    "C6": ("- 1--|--- Eb",),
    "C#6": ("- ---|--- Eb",),
    "D6": ("T -23|--- Eb",),
    "D#6": ("T 123 G#|123 Eb",),
    "E6": ("T 12-|12- Eb",),
    "F6": ("T 1-3|1-- Eb",),
    "F#6": ("T 1-3|--3 Eb",),
    "G6": ("- 123|--- Eb",),
    "G#6": ("- -23 G#|--- Eb",),
    "A6": ("T -2-|1-- Eb",),
    "A#6": ("T ---|1-- TrD",),
    "B6": ("T 1-3|--- TrD#",),
    "C7": ("- 123 G#|1--",),
}
# The soprano recorder's baroque fingerings, as written, C4 to D6 (sounding C5 to D7); German ones where they differ.
_RECORDER_CHART: dict[str, str] = {
    "C4": "T 123|4567",
    "C#4": "T 123|456h",
    "D4": "T 123|456-",
    "D#4": "T 123|45h-",
    "E4": "T 123|45--",
    "F4": "T 123|4-67",
    "F#4": "T 123|-56-",
    "G4": "T 123|----",
    "G#4": "T 12-|45h-",
    "A4": "T 12-|----",
    "A#4": "T 1-3|4---",
    "B4": "T 1--|----",
    "C5": "T -2-|----",
    "C#5": "- 12-|----",
    "D5": "- -2-|----",
    "D#5": "- -23|456-",
    "E5": "t 123|45--",
    "F5": "t 123|4-6-",
    "F#5": "t 123|-5--",
    "G5": "t 123|----",
    "G#5": "t 12-|4---",
    "A5": "t 12-|----",
    "A#5": "t 12-|456-",
    "B5": "t 12-|45--",
    "C6": "t 1--|45--",
    "C#6": "t 1-3|4-6- X",
    "D6": "t 1-3|4-6-",
}
_GERMAN = {
    "F4": "T 123|4---",
    "F#4": "T 123|-567",
    "G#4": "T 12-|45--",
    "F5": "t 123|4---",
    "F#5": "t 123|-5-7",
}
_FLUTE_EXTRAS = {"G#": "G#", "Eb": "Eb", "C#": "C#", "C": "C", "TrD": "trill-D", "TrD#": "trill-D#"}
_FLUTE_THUMB = {"T": "thumb", "Bb": "thumb-Bb", "-": None}


def _midi(name: str) -> int:
    """"C#4" -> 61."""
    return _LETTERS.index(name[:-1]) + 12 * (int(name[-1]) + 1)


def _flute(chart: str) -> Fingering:
    left, right = chart.split("|")
    thumb, fingers, *more = left.split()
    digits, *extras = right.split()
    pressed = {_FLUTE_THUMB[thumb]} | {f"L{d}" for d in fingers if d != "-"} | {f"R{d}" for d in digits if d != "-"}
    pressed |= {_FLUTE_EXTRAS[k] for k in (*more, *extras)}
    return Fingering(chart, tuple("x" if k in pressed else "o" for k in FLUTE_KEYS))


def _recorder(chart: str) -> Fingering:
    left, right = chart.split("|")
    thumb, fingers = left.split()
    holes, *bell = right.split()
    states = ({"T": "x", "t": "h", "-": "o"}[thumb],
              *("o" if c == "-" else "h" if c == "h" else "x" for c in fingers + holes), "x" if bell else "o")
    return Fingering(chart, states)


_FINGERINGS: dict[tuple[str, str], dict[int, tuple[Fingering, ...]]] = {
    ("flute", "boehm"): {_midi(n): tuple(_flute(c) for c in charts) for n, charts in _FLUTE_CHART.items()},
    ("recorder", "baroque"): {_midi(n): (_recorder(c),) for n, c in _RECORDER_CHART.items()},
    ("recorder", "german"): {_midi(n): (_recorder(_GERMAN.get(n, c)),) for n, c in _RECORDER_CHART.items()},
}


def fingerings(wind: Wind, note: int, *, system: str | None = None) -> list[Fingering]:
    """The fingerings of ``note`` (as the instrument reads it) on ``wind`` in ``system`` (its first by default), the
    standard one first; none for a note outside its range. An unknown system is a ValueError."""
    system = system or wind.systems[0]
    if system not in wind.systems:
        raise ValueError(f"the {wind.name} has no {system} fingering")
    return list(_FINGERINGS[(wind.name, system)].get(note, ()))


# --- the octave a melody is played in -------------------------------------------------------------


@dataclass(frozen=True)
class Fit:
    """Where a melody goes on an instrument: ``shift``, the whole octaves (in semitones) the instrument sounds it
    above the notes given; ``written``, the notes it reads; ``outside``, those of them outside its range."""

    shift: int
    written: tuple[int, ...]
    outside: tuple[int, ...]


def fit(notes: Iterable[int], wind: Wind) -> Fit:
    """The octave a melody (its notes as they sound, or its lowest and highest) is played in on ``wind`` (the
    module's docstring)."""
    return _fit(tuple(notes), wind)


@functools.lru_cache(maxsize=1024)
def _fit(notes: tuple[int, ...], wind: Wind) -> Fit:
    def cost(shift: int) -> tuple[int, int, int, int]:
        read = [n + shift - wind.sounds for n in notes]
        return (sum(not wind.low <= n <= wind.high for n in read),
                sum(not wind.easy[0] <= n <= wind.easy[1] for n in read), abs(shift), -shift)

    shift = min(range(-48, 49, 12), key=cost)
    written = tuple(n + shift - wind.sounds for n in notes)
    return Fit(shift, written, tuple(n for n in written if not wind.low <= n <= wind.high))


# --- off a chord sheet ----------------------------------------------------------------------------


def scale_notes(key: Key) -> list[int]:
    """The key's scale as a flute and a recorder read it: from its tonic in C4 to B4 up to the tonic's octave."""
    return list(_scale_notes(key))


@functools.cache
def _scale_notes(key: Key) -> tuple[int, ...]:
    tonic = 60 + key.tonic % 12
    return (*(tonic + step for step in SCALES[key.mode]), tonic + 12)


def _pc(name: str) -> int:
    """The pitch class of a note's name, with any sharps or flats: "B#" 0, "Ebb" 2."""
    return (_NATURAL[name[0]] + name.count("#") - name.count("b")) % 12


def chord_steps(chord: Chord) -> list[int]:
    """The chord's tones as semitones above its root, in ``harmony.chord_tones``' order, each above the one before,
    an 11th or a 13th an octave lower: C9 is [0, 4, 7, 10, 14], C11 [0, 4, 7, 10, 14, 5]."""
    return list(_chord_steps(chord.intervals, None if chord.bass is None else (chord.bass - chord.root) % 12))


@functools.lru_cache(maxsize=1024)
def _chord_steps(intervals: frozenset[int], bass: int | None) -> tuple[int, ...]:
    chord = Chord(0, "", bass, None, intervals)
    steps: list[int] = []
    for name, _ in harmony.chord_tones(chord, None):
        pc = _pc(name)
        steps.append(pc if not steps else steps[-1] + ((pc - steps[-1]) % 12 or 12))
    return tuple(s - 12 if s > _HIGHEST_STEP else s for s in steps)


def chord_notes(chord: Chord) -> list[int]:
    """The chord's tones as a flute and a recorder read them: the root in C4 to B4, then ``chord_steps`` above it."""
    return [60 + chord.root + step for step in _chord_steps(
        chord.intervals, None if chord.bass is None else (chord.bass - chord.root) % 12)]


def solfege(name: str) -> str:
    """A note's name in solfège, its sharps or flats kept: "C" Do, "Bb" Sib, "F#" Fa#."""
    return SOLFEGE[name[0]] + name[1:]


# --- the tables a viewer's data carries -----------------------------------------------------------


@functools.cache
def _fingering_data() -> dict[str, Any]:
    low = min(FLUTE.low, RECORDER.low)
    return {
        "low": low,
        "flute": {"keys": list(FLUTE.keys),
                  "notes": [[f.text for f in fingerings(FLUTE, n)] for n in range(low, FLUTE.high + 1)]},
        "recorder": {"holes": list(RECORDER.keys), **{
            system: [fingerings(RECORDER, n, system=system)[0].text for n in range(low, RECORDER.high + 1)]
            for system in RECORDER.systems}},
        "solfege": dict(SOLFEGE),
    }


def fingering_data() -> dict[str, Any]:
    """The fingerings the page carries, the same for every page (the module's docstring)."""
    import copy

    return copy.deepcopy(_fingering_data())


def tables(chords: Sequence[Chord | None], key: Key | None, mapped: dict[str, Sequence[Chord | None]],
           alts: dict[str, Sequence[Sequence[Chord]]]) -> dict[str, Any]:
    """The tables for a sheet whose chords are ``chords``, in ``key``, with each mode's chords and their
    alternatives ``mapped`` and ``alts`` as the page's data has them (harmony_tables.py's ``tables`` takes the same):
    ``windForms``, ``windChords`` and ``windAlts`` (the module's docstring)."""
    forms: list[list[int]] = []
    known: dict[tuple[int, ...], int] = {}

    def form(chord: Chord | None) -> int | None:
        if chord is None:
            return None
        steps = chord_steps(chord)
        index = known.setdefault(tuple(steps), len(forms))
        if index == len(forms):
            forms.append(steps)
        return index

    out: dict[str, Any] = {"windForms": forms, "windChords": {}, "windAlts": {}}
    if key is None:
        out["windChords"][""] = [form(c) for c in chords]
        return out
    for mode in MODES:
        out["windChords"][mode] = [form(c) for c in mapped[mode]]
        out["windAlts"][mode] = [[form(a) for a in options] for options in alts[mode]]
    return out
