"""The 10-hole diatonic harmonica in Richter tuning: its layout in every key, the positions it plays a song in,
the chords it plays, and the harps to pick for a song; with the tables a viewer's data carries. On top of
theory.py's chords and keys.

**The layout.** A C harp blows C E G C E G C E G C and draws D G B D F A B D F A, holes 1 to 10, from C4 up
(Wikipedia, "Richter-tuned harmonica"): the tonic triad on the blow, the rest of the scale on the draw. ``BLOW``
and ``DRAW`` are those notes in semitones above hole 1's blow note. A harp in another key is the same layout moved:
harps are named as they are sold (``HARP_KEYS``: Db, Eb, F#, Ab, Bb), and the standard ones run from the G harp,
the lowest (hole 1 blowing G3), up to the F# harp (F#4). On each hole the higher of its two reeds bends down a
semitone at a time to a semitone above the other: the draw on holes 1 to 6, the blow on 7 to 10 (``Layout.bends``;
none on 5 and 7). Bends are for melody alone: no chord here takes one.

**Positions**, numbered round the circle of fifths as Wikipedia numbers them: in the nth position a harp plays a
song whose tonic is n − 1 fifths above the harp's key. On a C harp the 1st is C (Ionian, "straight harp"), the 2nd
G (Mixolydian, "cross harp": the harp a fourth above the song), the 3rd D (Dorian, "slant harp": a whole tone
below), the 4th A (Aeolian), the 5th E (Phrygian), the 6th B (Locrian) and the 12th F (Lydian, which some call the
0th); the 7th to the 11th start on notes the harp lacks, and have no mode (``position_mode``). Thomann's "fourth
position" (rooted on blow 2) is this numbering's 5th: caracole names the harp's key and the mode with the number.

**Chords.** A harp plays a chord when a run of neighbouring holes on one breath sounds exactly its notes, its bass
too (``play``): on a C harp C is the blow (1–3), G draw 2–4, G7 draw 2–5, G9 draw 2–6, Dm draw 4–6, Dm6 draw 4–7,
B° draw 3–5, Bø7 draw 3–6 (Yerxa, "Harmonica For Dummies"). Of the runs that do, the one that starts on the
chord's bass, else its root, else any, the narrowest, then the lowest. Otherwise, in this order:

- *part*: its triad (root, third, fifth; a suspended chord's or a power chord's own notes) leaving out the rest,
  sixths, sevenths, ninths and a bass that is no note of the chord, when the harp plays that whole: Cmaj7 on a C
  harp is blow 1–3, as C;
- *minor*, a minor substitute: for a chord with a major third (and a perfect fifth, or none), the minor triad on
  its root, the harp's usual stand-in (the 2nd position's V, D on a C harp, is Dm, draw 4–6). Never the other way:
  a major triad clashes with a minor chord;
- *no*: not on this harp.

So the 1st position offers I, V7 and ii but no clean IV or vi; the 2nd I7, IV and a minor v; the 3rd i, IV and
♭VII, which suits a Dorian song.

**The harps for a song** (``choices``), at most three, best first. The candidates are the positions for the
song's mode (the 1st and 2nd for a mode with a major third, the 3rd, 4th and 5th for one with a minor third, and
the position whose own mode is the song's: the 12th for Lydian, the 6th for Locrian). They are ranked by how
well each plays the song's chords as they sound (each distinct chord: 1 when the harp plays it whole or as its
triad, ½ as a minor substitute, nothing otherwise; a chord on the song's tonic counts twice, the chord a song
rests on), then by how few notes the position's mode changes from the song's, then in the order above. A song in
G with a IV chord (G C D) takes a C harp in the 2nd position before a G harp in the 1st; a song in A minor takes
a G harp in the 3rd, whose draw 4–6 is its Am. Everything is relative to the song's tonic, so the choices follow
a transposition (and a capo, which a harmonica never takes: its player plays the key the song sounds in).

**The header line** (``header_line``): "Harmonica: C harp (2nd position) · G harp (1st)", the mode after the
position for any but the 1st and the 2nd ("G harp (3rd position, dorian)").

**The tables** a viewer's data carries (``tables``), for viewer.js to look up: it computes no theory of its own.
Every chord is relative to the key's tonic, so nothing in them changes with the transposition but the harps'
names, and the page names a harp ``harpKeys[(tonic + shift + offset) % 12]``, where ``tonic`` is the key as written
(``data.key.tonic``) and ``shift`` the semitones the song sounds above it (the transposition and the capo):

- ``harpKeys``: the 12 harps' names, by the key's pitch class (``HARP_KEYS``);
- ``harps[mode]``: the harps for the song in that mode, best first (``choices`` of ``data.mapped[mode]``), each
  ``[position, offset, label]``: ``offset`` the harp's key in semitones above the song's tonic (0 to 11), ``label``
  what the header line writes in its brackets ("2nd position", "1st", "4th, aeolian"), so the line is "Harmonica: "
  and each "<name> harp (<label>)", joined with " · ";
- ``harpForms``: what a chord plays on each of the 12 harps, a list of 12 **entries** by the harp's ``offset``
  above the song's tonic; each form once, shared by the chords that play alike;
- ``harpChords[mode][i]``: chord ``i``'s form (by its index in ``harpForms``), as ``data.mapped[mode]`` has it, or
  null for a chord caracole can't read; ``harpAlts[mode][i][j]``: the form of each chord ``data.alts[mode][i]``
  offers instead.

An **entry** is null for a chord not on that harp, else ``[kind, breath, first, last]`` ("yes": its own notes,
breath "blow" or "draw", holes ``first`` to ``last``) or ``[kind, breath, first, last, suffix]`` ("part" or
"minor": the chord played there is the chord's root, named as the page names it, and ``suffix``): ``entry_text``
writes one as the page shows it, "draw 2–5", "blow 1–3 (as C)", "draw 4–6 (as Dm, minor substitute)", "not on this
harp".

The answers are kept (``functools`` caches), as theory.py's are: chords and keys are frozen, these dataclasses
too, and a list handed out is a copy.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from caracole.viewer.theory import MODES, QUALITIES, SCALES, Chord, Key, scale

HOLES = 10
# A C harp's notes, holes 1 to 10, in semitones above hole 1's blow (C4): C E G C E G C E G C, D G B D F A B D F A.
BLOW = (0, 4, 7, 12, 16, 19, 24, 28, 31, 36)
DRAW = (2, 7, 11, 14, 17, 21, 23, 26, 29, 33)
# The harps' keys as they are sold, by pitch class.
HARP_KEYS = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
_LOWEST = 55  # G3, hole 1's blow on a G harp, the lowest of the standard keys (F#, the highest, blows F#4)
POSITIONS = tuple(range(1, 13))
_ORDINALS = {1: "st", 2: "nd", 3: "rd"}  # then "th", the 11th and the 12th too
_IONIAN = SCALES["ionian"]
_QUALITY_OF = {intervals: name for name, intervals in QUALITIES.items()}


@dataclass(frozen=True)
class Layout:
    """A harp's notes, holes 1 to 10, as MIDI numbers: ``harp`` is its key's pitch class."""

    harp: int
    blow: tuple[int, ...]
    draw: tuple[int, ...]

    @property
    def name(self) -> str:
        return HARP_KEYS[self.harp]

    @property
    def bend_breath(self) -> tuple[str, ...]:
        """The breath each hole bends on: its higher reed's."""
        return tuple("draw" if d > b else "blow" for b, d in zip(self.blow, self.draw, strict=True))

    @property
    def bends(self) -> tuple[tuple[int, ...], ...]:
        """Each hole's bent notes, a semitone at a time down from its higher reed to a semitone above the other."""
        return tuple(tuple(range(max(b, d) - 1, min(b, d), -1)) for b, d in zip(self.blow, self.draw, strict=True))


@functools.cache
def layout(harp: int) -> Layout:
    """The harp in the key of pitch class ``harp``."""
    low = _LOWEST + (harp - 7) % 12
    return Layout(harp % 12, tuple(low + n for n in BLOW), tuple(low + n for n in DRAW))


def position_mode(position: int) -> str | None:
    """The mode a harp plays in a position (1 to 12) with no bend: "mixolydian" for the 2nd; None for the 7th to
    the 11th, whose tonic the harp lacks."""
    interval = 7 * (position - 1) % 12
    return MODES[_IONIAN.index(interval)] if interval in _IONIAN else None


def harp_for(tonic: int, position: int) -> int:
    """The key (pitch class) of the harp that plays a song on ``tonic`` in ``position``: a song in G (7) takes a
    C harp (0) in the 2nd."""
    return (tonic - 7 * (position - 1)) % 12


def position_of(tonic: int, harp: int) -> int:
    """The position a harp in ``harp`` plays a song on ``tonic`` in, 1 to 12."""
    return (tonic - harp) * 7 % 12 + 1  # seven fifths make a fifth again: 7 is its own inverse modulo 12


def ordinal(position: int) -> str:
    """"1st", "2nd", "3rd", "4th"... "12th"."""
    return f"{position}{_ORDINALS.get(position, 'th')}"


# --- the chords a harp plays ----------------------------------------------------------------------


@dataclass(frozen=True)
class Playing:
    """How a harp plays a chord: ``kind`` "yes" (its own notes), "part" (its triad), "minor" (the minor triad on
    its root) or "no"; then the breath, "blow" or "draw", and the first and last holes, and ``played``, the chord
    those holes sound (the chord itself for "yes"); none of them for "no"."""

    kind: str
    breath: str | None
    holes: tuple[int, int] | None
    played: Chord | None

    def text(self, names: Sequence[str]) -> str:
        """"draw 2–5", "blow 1–3 (as C)", "draw 4–6 (as Dm, minor substitute)", "not on this harp": the chord
        played named with ``names`` (``theory.spelling`` of the key shown)."""
        if self.played is None or self.holes is None:
            return "not on this harp"
        return entry_text(entry(self), names[self.played.root])


# Each run of two or more neighbouring holes on one breath of a C harp: (breath, first, last, its notes' pitch
# classes, its lowest note's), first holes first, the narrowest first.
_RUNS = tuple(
    (breath, first, last, frozenset((60 + notes[h - 1]) % 12 for h in range(first, last + 1)), notes[first - 1] % 12)
    for width in range(2, HOLES + 1) for first in range(1, HOLES - width + 2)
    for breath, notes in (("blow", BLOW), ("draw", DRAW)) for last in (first + width - 1,)
)


def _run(pcs: frozenset[int], starts: Sequence[int]) -> tuple[str, int, int] | None:
    """The run of a C harp that sounds exactly ``pcs``: one starting on the first of ``starts`` that has one, else
    any; the narrowest, then the lowest."""
    found = [r for r in _RUNS if r[3] == pcs]
    for start in starts:
        if on := [r for r in found if r[4] == start]:
            found = on
            break
    if not found:
        return None
    breath, first, last, _, _ = min(found, key=lambda r: (r[2] - r[1], r[1]))
    return breath, first, last


def _triad(intervals: frozenset[int]) -> frozenset[int]:
    """A chord's triad: its root, its third (the major one when it has both: the other is a ♯9) or else its
    suspension, and its fifth (the perfect one when it has it, else its ♭5 or ♯5)."""
    third = {4} if 4 in intervals else {3} if 3 in intervals else {2, 5} & intervals
    fifth = {7} if 7 in intervals else {6, 8} & intervals
    return frozenset({0} | third | fifth)


@functools.lru_cache(maxsize=4096)
def _on_c(root: int, intervals: frozenset[int], bass: int | None) -> tuple[str, str | None, tuple[int, int] | None,
                                                                          str | None]:
    """How a C harp plays the chord: (kind, breath, holes, the quality played: None for the chord itself)."""
    pcs = frozenset((root + i) % 12 for i in intervals) | ({bass} if bass is not None else set())
    starts = ([bass] if bass is not None else []) + [root]
    if run := _run(pcs, starts):
        return "yes", run[0], run[1:], None
    triad = _triad(intervals)
    quality = _QUALITY_OF.get(triad)
    if quality is not None and triad != intervals | ({(bass - root) % 12} if bass is not None else set()):
        if run := _run(frozenset((root + i) % 12 for i in triad), [root]):
            return "part", run[0], run[1:], quality
    if 4 in intervals and (7 in intervals or not {6, 8} & intervals):
        if run := _run(frozenset((root + i) % 12 for i in (0, 3, 7)), [root]):
            return "minor", run[0], run[1:], "m"
    return "no", None, None, None


def play(chord: Chord, harp: int) -> Playing:
    """How the harp in the key of pitch class ``harp`` plays ``chord`` (the module's docstring)."""
    bass = None if chord.bass is None else (chord.bass - harp) % 12
    kind, breath, holes, quality = _on_c((chord.root - harp) % 12, chord.intervals, bass)
    if kind == "no":
        return Playing(kind, None, None, None)
    return Playing(kind, breath, holes, chord if quality is None else Chord(chord.root, quality))


def entry(playing: Playing) -> list[Any] | None:
    """A ``Playing`` as the tables' **entry** (the module's docstring)."""
    if playing.kind == "no" or playing.holes is None or playing.played is None:
        return None
    found: list[Any] = [playing.kind, playing.breath, *playing.holes]
    if playing.kind != "yes":
        found.append(playing.played.suffix)
    return found


def entry_text(found: Sequence[Any] | None, root: str) -> str:
    """An entry as the page writes it, the chord's root named ``root``: "draw 2–5", "blow 1–3 (as C)", "draw 4–6
    (as Dm, minor substitute)", "not on this harp"."""
    if found is None:
        return "not on this harp"
    where = f"{found[1]} {found[2]}–{found[3]}"
    if found[0] == "yes":
        return where
    return f"{where} (as {root}{found[4]}" + (", minor substitute)" if found[0] == "minor" else ")")


# --- the harps for a song -------------------------------------------------------------------------


@dataclass(frozen=True)
class HarpChoice:
    """A harp for a song: its position, its key (``harp``, a pitch class), the position's mode, and how it plays
    the song's chords: ``fit`` (the ranking's score), of ``chords`` distinct chords, ``plays`` whole or as their
    triad and ``substitutes`` as a minor one."""

    position: int
    harp: int
    mode: str | None
    fit: float
    chords: int
    plays: int
    substitutes: int

    @property
    def name(self) -> str:
        return HARP_KEYS[self.harp]


_OWN = {position_mode(p): p for p in POSITIONS if position_mode(p) is not None}


def choices(key: Key, chords: Sequence[Chord | None]) -> list[HarpChoice]:
    """The harps for a song in ``key`` whose chords (as they sound) are ``chords``, best first, at most three (the
    module's docstring). A chord caracole can't read (None) counts for nothing."""
    distinct: dict[tuple[int, frozenset[int], int | None], Chord] = {}
    for chord in chords:
        if chord is not None:
            distinct.setdefault((chord.root, chord.intervals, chord.bass), chord)
    return list(_choices(key, tuple(distinct.values())))


@functools.lru_cache(maxsize=1024)
def _choices(key: Key, chords: tuple[Chord, ...]) -> tuple[HarpChoice, ...]:
    candidates = [1, 2] if 4 in SCALES[key.mode] else [3, 4, 5]
    if _OWN[key.mode] not in candidates:
        candidates.append(_OWN[key.mode])
    found = []
    for order, position in enumerate(candidates):
        harp = harp_for(key.tonic, position)
        fit, plays, substitutes = 0.0, 0, 0
        for chord in chords:
            weight = 2 if chord.root == key.tonic else 1
            kind = play(chord, harp).kind
            if kind in ("yes", "part"):
                fit, plays = fit + weight, plays + 1
            elif kind == "minor":
                fit, substitutes = fit + weight / 2, substitutes + 1
        mode = position_mode(position)
        changed = len(scale(Key(key.tonic, mode)) ^ scale(key)) // 2 if mode else 7
        found.append(((-fit, changed, order), HarpChoice(position, harp, mode, fit, len(chords), plays, substitutes)))
    found.sort(key=lambda f: f[0])
    return tuple(choice for _, choice in found[:3])


def _label(n: int, choice: HarpChoice) -> str:
    """What the header line writes in the brackets of the ``n``th harp: "2nd position", "1st", "4th, aeolian"."""
    label = ordinal(choice.position) + (" position" if n == 0 else "")
    if choice.position not in (1, 2) and choice.mode:
        label += ", " + choice.mode
    return label


def header_line(key: Key, chords: Sequence[Chord | None]) -> str:
    """"Harmonica: C harp (2nd position) · G harp (1st)": the harps for a song in ``key`` whose chords (as they
    sound) are ``chords``."""
    return "Harmonica: " + " · ".join(
        f"{choice.name} harp ({_label(n, choice)})" for n, choice in enumerate(choices(key, chords)))


# --- the tables a viewer's data carries -----------------------------------------------------------


def tables(key: Key | None, mapped: dict[str, Sequence[Chord | None]],
           alts: dict[str, Sequence[Sequence[Chord]]] | None = None) -> dict[str, Any]:
    """The tables for a sheet in ``key`` whose chords in each mode are ``mapped[mode]`` (``data.mapped``) and their
    alternatives ``alts[mode]`` (``data.alts``), as the module's docstring says. With no key, none."""
    if key is None:
        return {}
    forms: list[list[Any]] = []
    known: dict[tuple, int] = {}

    def form(chord: Chord | None) -> int | None:
        if chord is None:
            return None
        entries = [entry(play(chord, (key.tonic + offset) % 12)) for offset in range(12)]
        index = known.setdefault(tuple(None if e is None else tuple(e) for e in entries), len(forms))
        if index == len(forms):
            forms.append(entries)
        return index

    out: dict[str, Any] = {"harpKeys": list(HARP_KEYS), "harps": {}, "harpForms": forms, "harpChords": {},
                           "harpAlts": {}}
    for mode in MODES:
        if mode not in mapped:
            continue
        found = choices(Key(key.tonic, mode), mapped[mode])
        out["harps"][mode] = [[c.position, (c.harp - key.tonic) % 12, _label(n, c)] for n, c in enumerate(found)]
        out["harpChords"][mode] = [form(c) for c in mapped[mode]]
        out["harpAlts"][mode] = [[form(a) for a in options] for options in (alts or {}).get(mode, [])]
    return out
