"""What each chord does in its key: Roman numerals, relations, families, the glossary's lines, a
chord's notes and the scale for a solo over it, the key's scale on the neck, and each section's
progression with its name and how it ends. On top of theory.py's chords and keys.

**Numerals** count the chord's root up from the key's tonic, written against the tonic's major
scale (theory.py's ``_DEGREES``): a degree the key lowers or raises gets ♭ or ♯, so A minor's C is
♭III and C Mixolydian's B♭ is ♭VII. Upper case for a chord with a major third (or none), lower case
for a minor or diminished one; then ° (diminished), ø (half-diminished), + (augmented) and the
extensions as the chord's name has them (V7, ii9, Isus4, I5). A slash chord's bass is its degree
above the chord's own root, in Arabic numerals (C/E is I/3, G/F is V/♭7, C/D is I/2: a bass that is
no note of the chord shows as what it is, never as an inversion); a Roman numeral after the slash
is the chord a secondary chord belongs to (V/V). The bass's degree is counted against the major
scale on the chord's root, as the numerals are against the tonic's, whether or not the bass is a
note of the chord: G7/F is V7/♭7 as G/F is, and Am/C is vi/♭3. A secondary chord with a bass
writes both, the target first: D/F# going to G in C is V/V/3.

**Relations**, in the order they are tried (one rule each, the common reading of pop and rock
analysis where two readings exist):

- *in the key*: every note of the chord (its bass too) is in the key's scale; in a minor
  (Aeolian) key a chord on the fifth or the seventh degree may raise the sixth and the seventh,
  so E7 and G♯°7 are A minor's V7 and vii°7, as ``theory.estimate_key`` counts them.
- *secondary*: a dominant (a major third, no major seventh) a fifth above a major or minor chord
  of the key other than the tonic (V/x), or a leading-tone chord (diminished or half-diminished)
  a half step below one (vii°/x). Read so when it goes to that chord, or when no mode on the
  tonic holds it (E major in C is V/vi wherever it goes). One a mode holds and that goes
  elsewhere is borrowed: D major in C going to C is C Lydian's II (rock's "Lydian II"), going
  to G it is V/V. A chord on the tonic is never secondary: C7 F7 in a blues is I7 IV7.
- *borrowed* from the first mode on the same tonic that holds it (with the minor key's raised
  sixth and seventh on its fifth and seventh degrees, as above). A major key borrows from its
  parallel minor first (modal mixture: ♭III, iv, ♭VI, ♭VII, ii°, vii°7 are "borrowed from C
  minor"; B♭ in C reads so, not as C Mixolydian's ♭VII), then from the modes nearest it:
  Mixolydian, Lydian, Dorian, Phrygian. A minor key borrows from the modes nearest it first,
  Dorian (rock's "Dorian IV": D major in A minor) and Phrygian (♭II), then its parallel major
  (the Picardy I), Mixolydian, Lydian. A key in another mode borrows from the modes that change
  the fewest of its notes first. Locrian, whose tonic chord is diminished, lends none: F♯ major
  in C is outside it, not Locrian's ♭V.
- *outside* the key otherwise.

**Families**, for a chord in the key, by its degree: home (I, iii, vi; i, ♭III, ♭VI), moving away
(ii, IV; ii°, iv), pulling home (V, vii°; v and ♭VII in a minor key, whose subtonic leads home in
rock's Aeolian cadence, ♭VII–i). None for a chord from outside the key.

**Progressions**: a section's chords as numerals, each read with the chord it goes to (the next on
the sheet on another root, the next section's after its last); a chord held over several lines
once, a cycle the section plays whole each time folded ("vi IV I V" ×4), named from ``CATALOGUE`` in any
rotation and key, and its ending. Names compare the numerals' roots alone (Imaj7 is I, I/3 is I;
V/V stays V/V), as ``progression_key`` does for searching.

The answers are kept (``functools`` caches), as theory.py's are: chords and keys are frozen, these
dataclasses too, and a list handed out is a copy.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from dataclasses import dataclass

from caracole.viewer.theory import (
    _DEGREES,
    _LETTERS,
    _NATURAL,
    MODES,
    SCALES,
    Chord,
    Key,
    _diatonic_quality,
    _intervals,
    _spell,
    scale,
    spelling,
)

ROMANS = ("I", "II", "III", "IV", "V", "VI", "VII")
_IONIAN = SCALES["ionian"]

# Each quality of theory.QUALITIES as a numeral writes it: (lower case, its sign, its extension).
_SHAPES: dict[str, tuple[bool, str, str]] = {
    "": (False, "", ""), "m": (True, "", ""), "5": (False, "", "5"), "dim": (True, "°", ""),
    "aug": (False, "+", ""), "sus2": (False, "", "sus2"), "sus4": (False, "", "sus4"),
    "b5": (False, "", "♭5"), "6": (False, "", "6"), "m6": (True, "", "6"), "69": (False, "", "6/9"),
    "m69": (True, "", "6/9"), "7": (False, "", "7"), "maj7": (False, "", "maj7"),
    "m7": (True, "", "7"), "mmaj7": (True, "", "maj7"), "m7b5": (True, "ø", "7"),
    "dim7": (True, "°", "7"), "7sus4": (False, "", "7sus4"), "7sus2": (False, "", "7sus2"),
    "add9": (False, "", "add9"), "madd9": (True, "", "add9"), "add11": (False, "", "add11"),
    "9": (False, "", "9"), "maj9": (False, "", "maj9"), "m9": (True, "", "9"),
    "9sus4": (False, "", "9sus4"), "11": (False, "", "11"), "m11": (True, "", "11"),
    "13": (False, "", "13"), "7b5": (False, "", "7♭5"), "aug7": (False, "+", "7"),
    "7b9": (False, "", "7♭9"), "7#9": (False, "", "7♯9"),
}


@dataclass(frozen=True)
class Numeral:
    """A chord's Roman numeral in a key, in its parts; ``text`` puts them together."""

    accidental: str  # "", "♭", "♯" against the tonic's major scale
    roman: str  # "I".."VII", lower case for minor and diminished
    quality: str  # "", "°", "ø", "+"
    extension: str  # "", "7", "maj7", "6", "9", "sus2", "sus4", "add9", "5", ...
    bass: str | None  # the bass's degree above the chord's root, for a slash chord: "3", "♭7"
    of: str | None  # the chord of the key a secondary chord belongs to: "V" in "V/V"

    @property
    def text(self) -> str:
        """"♭VII", "vii°7", "V7/V", "I/3", "V/V/3"."""
        text = self.accidental + self.roman + self.quality + self.extension
        if self.of is not None:
            text += "/" + self.of
        if self.bass is not None:
            text += "/" + self.bass
        return text


@dataclass(frozen=True)
class Relation:
    """How a chord stands to the key: ``kind`` is "in", "borrowed", "secondary", "leading" (a
    secondary leading-tone chord) or "outside"."""

    kind: str
    source: str | None  # the key a borrowed chord comes from: "C minor", "C Mixolydian"
    target: str | None  # the chord of the key a secondary chord belongs to, as named there: "G"


@dataclass(frozen=True)
class Progression:
    """A section's chords in numerals: one cycle, played ``repeats`` times."""

    numerals: tuple[str, ...]  # one cycle, repeats folded
    repeats: int
    name: str | None  # from CATALOGUE, in any rotation
    ending: str | None  # "authentic", "plagal", "half", "deceptive"


# Progressions with a common name, by their numerals' roots (as progression_key compares them).
# Sources: Wikipedia's articles "I–V–vi–IV progression", "'50s progression", "ii–V–I progression",
# "Three-chord song", "Twelve-bar blues" (the plain and the quick-change forms, each with and
# without the turnaround's V), "Andalusian cadence", "Plagal cadence" (the double plagal cadence,
# ♭VII–IV–I, the progression I–♭VII–IV turned round), "Circle progression", "Pachelbel's Canon",
# "Ragtime progression" and "Royal road progression". The first two read again in the relative
# minor, so a song in A minor read as C major, or the other way, finds the same name.
CATALOGUE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("the pop progression", ("I", "V", "vi", "IV")),
    ("the pop progression", ("i", "♭VI", "♭III", "♭VII")),
    ("the '50s progression", ("I", "vi", "IV", "V")),
    ("the '50s progression", ("♭III", "i", "♭VI", "♭VII")),
    ("ii–V–I", ("ii", "V", "I")),
    ("the minor ii–V–i", ("ii", "V", "i")),
    ("I–IV–V", ("I", "IV", "V")),
    ("the 12-bar blues", ("I", "IV", "I", "V", "IV", "I")),
    ("the 12-bar blues", ("I", "IV", "I", "V", "IV", "I", "V")),
    ("the 12-bar blues", ("I", "IV", "I", "IV", "I", "V", "IV", "I")),
    ("the 12-bar blues", ("I", "IV", "I", "IV", "I", "V", "IV", "I", "V")),
    ("the Andalusian cadence", ("i", "♭VII", "♭VI", "V")),
    ("I–♭VII–IV", ("I", "♭VII", "IV")),
    ("the circle of fifths", ("vi", "ii", "V", "I")),
    ("the Canon", ("I", "V", "vi", "iii", "IV", "I", "IV", "V")),
    ("the ragtime progression", ("V/vi", "V/ii", "V/V", "V")),
    ("the royal road", ("IV", "V", "iii", "vi")),
)

# The modes a key borrows from, first the one asked first (the module's docstring says why).
_BORROWS = {
    "ionian": ("aeolian", "mixolydian", "lydian", "dorian", "phrygian"),
    "aeolian": ("dorian", "phrygian", "ionian", "mixolydian", "lydian"),
}
_MODE_WORDS = {"ionian": "major", "aeolian": "minor"}
_FAMILIES = ("home", "away", "home", "away", "pull", "home", "pull")


def _ordinal(n: int) -> str:
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n, 'th')}"


def _mode_word(mode: str) -> str:
    return _MODE_WORDS.get(mode, mode.capitalize())


def _key_words(key: Key) -> str:
    """"C major", "A minor", "C Mixolydian"."""
    return f"{spelling(key)[key.tonic]} {_mode_word(key.mode)}"


def _degree(pc: int, key: Key) -> tuple[int, str]:
    """The degree (0-6) a pitch class is written as in ``key``, and its accidental against the
    tonic's major scale."""
    interval = (pc - key.tonic) % 12
    degree = _DEGREES["major" if 4 in SCALES[key.mode] else "minor"][interval]
    step = (interval - _IONIAN[degree] + 6) % 12 - 6
    return degree, {0: "", -1: "♭", 1: "♯"}[step]


# --- what a chord is ----------------------------------------------------------------------------


@functools.lru_cache(maxsize=4096)
def _shape(chord: Chord) -> tuple[bool, str, str]:
    """(lower case, sign, extension) of a chord's numeral."""
    if chord.quality in _SHAPES:
        return _SHAPES[chord.quality]
    q = chord.quality
    if chord.tones is None or _intervals(q) != chord.tones:  # a suffix theory.py couldn't read
        return 3 in chord.intervals and 4 not in chord.intervals, "", ""
    if q.startswith("dim"):
        lower, sign, rest = True, "°", q[3:]
    elif q.startswith("aug"):
        lower, sign, rest = False, "+", q[3:]
    elif q.startswith("m") and not q.startswith("maj"):
        lower, sign, rest = True, "", q[1:]
    else:
        lower, sign, rest = False, "", q
    return lower, sign, rest.replace("b", "♭").replace("#", "♯")


def _dominant(chord: Chord) -> bool:
    iv = chord.intervals
    return 4 in iv and 11 not in iv and (8 not in iv or 10 in iv)


def _leading(chord: Chord) -> bool:
    iv = chord.intervals
    return 3 in iv and 6 in iv and 4 not in iv and 7 not in iv


def _holds(key: Key, chord: Chord) -> bool:
    """Every note of the chord is in the key: in a minor key, a chord on the fifth or seventh
    degree may raise the sixth and seventh."""
    notes = scale(key)
    if key.mode == "aeolian" and (chord.root - key.tonic) % 12 in (7, 11):
        notes = notes | {(key.tonic + 9) % 12, (key.tonic + 11) % 12}
    return chord.pitch_classes <= notes


def _borrows(key: Key) -> tuple[str, ...]:
    if key.mode in _BORROWS:
        return _BORROWS[key.mode]
    own = set(SCALES[key.mode])
    others = [m for m in MODES if m not in (key.mode, "locrian")]
    return tuple(sorted(others, key=lambda m: (len(own - set(SCALES[m])), MODES.index(m))))


def _target(pc: int, key: Key) -> tuple[str, str] | None:
    """The chord of the key on ``pc`` a secondary chord can belong to, as (its numeral, its name):
    a major or minor triad of the key, not the tonic's. A minor key's fifth degree is V, its
    dominant."""
    if pc == key.tonic or (pc - key.tonic) % 12 not in SCALES[key.mode]:
        return None
    quality = _diatonic_quality(pc, key, 3)
    if quality not in ("", "m"):
        return None
    degree, accidental = _degree(pc, key)
    if key.mode == "aeolian" and degree == 4:
        quality = ""
    roman = ROMANS[degree].lower() if quality == "m" else ROMANS[degree]
    return accidental + roman, spelling(key)[pc] + quality


@dataclass(frozen=True)
class _Reading:
    kind: str
    source: Key | None = None
    target: int | None = None  # the pitch class of a secondary chord's target


@functools.lru_cache(maxsize=8192)
def _read(chord: Chord, key: Key, next_chord: Chord | None) -> _Reading:
    if _holds(key, chord):
        return _Reading("in")
    sources = [Key(key.tonic, m) for m in _borrows(key)]
    source = next((s for s in sources if _holds(s, chord)), None)
    if chord.root != key.tonic:
        for kind, fits, step in (("secondary", _dominant, 5), ("leading", _leading, 1)):
            target = (chord.root + step) % 12
            if fits(chord) and _target(target, key) is not None:
                resolves = next_chord is not None and next_chord.root == target
                if resolves or source is None:
                    return _Reading(kind, None, target)
    if source is not None:
        return _Reading("borrowed", source)
    return _Reading("outside")


# --- numerals and relations ---------------------------------------------------------------------

_BASS_DEGREES = ("1", "♭2", "2", "♭3", "3", "4", "♭5", "5", "♭6", "6", "♭7", "7")
# A chord tone's name, folded into one octave for the bass: the 9th in the bass is its 2nd.
_IN_OCTAVE = {"9": "2", "♭9": "♭2", "♯9": "♯2", "11": "4", "♯11": "♯4", "13": "6", "♭13": "♭6"}


def _bass(chord: Chord) -> str | None:
    if chord.bass is None or chord.bass == chord.root:
        return None
    interval = (chord.bass - chord.root) % 12
    if interval in chord.intervals:
        name = _tone_names(chord)[interval]
        return _IN_OCTAVE.get(name, name)
    return _BASS_DEGREES[interval]


@functools.lru_cache(maxsize=8192)
def numeral(chord: Chord, key: Key, next_chord: Chord | None = None) -> Numeral:
    """The chord's Roman numeral in ``key``; ``next_chord``, the chord it goes to (the next on
    another root: D D7 G's D goes to G), tells a secondary chord (the module's docstring has the
    rules)."""
    lower, sign, extension = _shape(chord)
    reading = _read(chord, key, next_chord)
    bass = _bass(chord)
    if reading.kind in ("secondary", "leading"):
        of = _target(reading.target, key)[0]
        roman = "V" if reading.kind == "secondary" else "vii"
        return Numeral("", roman, sign, extension, bass, of)
    degree, accidental = _degree(chord.root, key)
    roman = ROMANS[degree].lower() if lower else ROMANS[degree]
    return Numeral(accidental, roman, sign, extension, bass, None)


@functools.lru_cache(maxsize=8192)
def relation(chord: Chord, key: Key, next_chord: Chord | None = None) -> Relation:
    """How the chord stands to ``key``: in it, borrowed (and from where), a secondary dominant or
    leading-tone chord (and the chord of the key it belongs to), or outside it."""
    reading = _read(chord, key, next_chord)
    if reading.kind in ("secondary", "leading"):
        return Relation(reading.kind, None, _target(reading.target, key)[1])
    if reading.kind == "borrowed":
        return Relation("borrowed", _key_words(reading.source), None)
    return Relation(reading.kind, None, None)


@functools.lru_cache(maxsize=8192)
def family(chord: Chord, key: Key) -> str | None:
    """"home", "away" or "pull" for a chord in the key, by its degree; None for one outside it."""
    if not _holds(key, chord):
        return None
    return _FAMILIES[_degree(chord.root, key)[0]]


# --- words --------------------------------------------------------------------------------------

# An extension's part, in words that read after "with".
_EXTENSION_WORDS = {
    "5": "only its root and 5th", "6": "an added 6th", "6/9": "an added 6th and 9th",
    "7": "a 7th", "maj7": "a major 7th", "9": "a 7th and 9th", "maj9": "a major 7th and 9th",
    "11": "a 7th, 9th and 11th", "13": "a 7th, 9th and 13th", "add9": "an added 9th",
    "add11": "an added 11th", "sus2": "the 2nd in place of the 3rd",
    "sus4": "the 4th in place of the 3rd", "no3": "no 3rd", "no5": "no 5th",
}
# What a symbol means, for the glossary, where that is more than its words above.
_SYMBOL_MEANINGS = {
    "5": "a power chord: only the root and 5th, no 3rd",
    "7": "a 7th added, a minor 7th above the root (on a major chord, the dominant 7th)",
    "maj7": "a major 7th added, a half step below the root",
    "add9": "a 9th added, without the 7th",
    "add11": "an 11th added, without the 7th",
    "sus2": "suspended: the 2nd in place of the 3rd",
    "sus4": "suspended: the 4th in place of the 3rd",
}
_TOKENS = re.compile(r"maj\d+|add\d+|sus\d|6/9|[♭♯]\d+|no\d|\d+|.")


def _tokens(extension: str) -> list[str]:
    return _TOKENS.findall(extension)


def _token_words(token: str) -> str:
    if token in _EXTENSION_WORDS:
        return _EXTENSION_WORDS[token]
    if token[:1] in ("♭", "♯") and token[1:].isdigit():
        return f"a {'lowered' if token[0] == '♭' else 'raised'} {_ordinal(int(token[1:]))}"
    if token.isdigit():
        return f"a {_ordinal(int(token))}"
    return token


def _quality_words(chord: Chord, numeral_: Numeral) -> str:
    sign, tokens = numeral_.quality, _tokens(numeral_.extension)
    if sign in ("ø", "°") and tokens[:1] == ["7"]:
        tokens = tokens[1:]
        triad = ("half-diminished (ø7: a diminished chord with a minor 7th)" if sign == "ø"
                 else "diminished seventh (°7)")
    elif sign == "°":
        triad = "diminished (°)"
    elif sign == "+":
        triad = "augmented (+)"
    elif 4 in chord.intervals:
        triad = "major (upper case)"
    elif 3 in chord.intervals:
        triad = "minor (lower case)"
    else:
        triad = ""
    parts = " and ".join(f"{_token_words(t)} ({t})" for t in tokens)
    if triad and parts:
        return f"{triad} with {parts}"
    return triad or (f"with {parts}" if parts else "")


def _chord_name(chord: Chord, key: Key | None) -> str:
    names = spelling(key)
    bass = "" if chord.bass is None else "/" + names[chord.bass]
    return names[chord.root] + chord.suffix + bass


@functools.lru_cache(maxsize=8192)
def explain(chord: Chord, key: Key, next_chord: Chord | None = None) -> str:
    """The numeral's one line, naming the key it is read in: "vi: the 6th chord of C major, minor
    (lower case)", "♭VII: built on the lowered 7th degree of C major, major (upper case); borrowed
    from C minor", "V/V: the V of V in C major, major (upper case); leads to G"."""
    found = numeral(chord, key, next_chord)
    reading = _read(chord, key, next_chord)
    words = _key_words(key)
    degree, accidental = _degree(chord.root, key)
    ordinal = _ordinal(degree + 1)
    if reading.kind == "secondary":
        where = f"the V of {found.of} in {words}"
    elif reading.kind == "leading":
        where = f"the leading-tone chord of {found.of} in {words}"
    elif reading.kind == "in":
        where = f"the {ordinal} chord of {words}"
    elif accidental:
        where = f"built on the {'lowered' if accidental == '♭' else 'raised'} {ordinal} degree of {words}"
    else:
        where = f"built on the {ordinal} degree of {words}"
    line = f"{found.text}: {where}"
    if quality := _quality_words(chord, found):
        line += ", " + quality
    if found.bass is not None:
        bass = spelling(key)[chord.bass]
        interval = (chord.bass - chord.root) % 12
        if interval in chord.intervals:
            line += f"; {bass} in the bass, its {_ordinal(_number(_tone_names(chord)[interval]))}"
        else:
            line += (f"; {bass} in the bass, the {_degree_words(found.bass)} above its root, "
                     "not a note of the chord")
    target = None if reading.target is None else _target(reading.target, key)[1]
    if reading.kind in ("secondary", "leading"):
        goes = next_chord is not None and next_chord.root == reading.target
        line += f"; {'leads' if goes else 'points'} to {target}"
    elif reading.kind == "borrowed":
        line += f"; borrowed from {_key_words(reading.source)}"
    elif reading.kind == "outside":
        line += f"; outside {words}"
    return line


def _degree_words(label: str) -> str:
    """"3" -> "3rd", "♭7" -> "lowered 7th", "♯4" -> "raised 4th"."""
    digits = label.lstrip("♭♯")
    way = {"♭": "lowered ", "♯": "raised "}.get(label[:1], "")
    return way + _ordinal(int(digits))


def _goes_to(chords: Sequence[Chord]) -> list[Chord | None]:
    """The chord each one goes to: the next on another root (D D7 G: both D chords go to G)."""
    after: list[Chord | None] = []
    upcoming: Chord | None = None
    for chord in reversed(chords):
        if upcoming is not None and upcoming.root == chord.root:
            after.append(after[-1])
        else:
            after.append(upcoming)
        upcoming = chord
    return after[::-1]


def glossary(chords: Sequence[Chord], key: Key) -> list[tuple[str, str, str]]:
    """(symbol, meaning, example) for each symbol the numerals of ``chords`` use, the notation's
    order, each with the first of the song's chords that shows it ("G7 = V7"). The chords are in
    the order the sheet plays them: each is read with the next on another root as the chord it
    goes to."""
    return list(_glossary(tuple(chords), key))


@functools.lru_cache(maxsize=1024)
def _glossary(chords: tuple[Chord, ...], key: Key) -> tuple[tuple[str, str, str], ...]:
    tonic = spelling(key)[key.tonic]
    words = _key_words(key)
    found: dict[tuple[int, str], tuple[str, str, str]] = {}

    def note(rank: int, symbol: str, meaning: str, example: str) -> None:
        found.setdefault((rank, symbol), (symbol, meaning, example))

    for chord, after in zip(chords, _goes_to(chords), strict=True):
        n = numeral(chord, key, after)
        example = f"{_chord_name(chord, key)} = {n.text}"
        note(0, "I–VII", f"Roman numerals: the chord's root counted up the scale of {words}, "
                         f"from its tonic, {tonic} (I)", example)
        if n.of is None and n.quality != "+" and 4 in chord.intervals and not n.roman.islower():
            note(1, "I", "upper case: a major chord", example)
        if n.roman.islower() and n.quality == "":
            note(2, "i", "lower case: a minor chord", example)
        if n.accidental:
            way = "lower" if n.accidental == "♭" else "higher"
            note(3 if n.accidental == "♭" else 4, n.accidental,
                 f"a root a half step {way} than that degree of {tonic} major's scale", example)
        if n.quality == "°":
            note(5, "°", "diminished: a minor 3rd and a lowered 5th (°7: with a diminished 7th)", example)
        if n.quality == "ø":
            note(6, "ø", "half-diminished: a diminished chord with a minor 7th (m7♭5)", example)
        if n.quality == "+":
            note(7, "+", "augmented: a major 3rd and a raised 5th", example)
        for token in _tokens(n.extension):
            meaning = _SYMBOL_MEANINGS.get(token) or "with " + _token_words(token)
            note(8, token, meaning, example)
        if n.bass is not None:
            note(9, "/" + n.bass, f"a number after a slash: the bass note, the {_degree_words(n.bass)} "
                                  "above the chord's root", example)
        if n.of is not None and n.roman == "V":
            note(10, "V/x", "the V of x: a dominant leading to the chord x of the key "
                            "(V/V leads to the V)", example)
        if n.of is not None and n.roman == "vii":
            note(11, "vii°/x", "the leading-tone chord of x, a half step below the chord x of the "
                               "key", example)
    return tuple(found[k] for k in sorted(found, key=lambda k: k[0]))  # stable: first seen first


# --- notes and scales ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=4096)
def _tone_names(chord: Chord) -> dict[int, str]:
    """Each interval of the chord by its name: "R", "♭3", "5", "♭7", "9"..."""
    iv = chord.intervals
    seventh = 10 in iv or 11 in iv
    third = 3 in iv or 4 in iv
    diminished = 3 in iv and 6 in iv and 7 not in iv and not seventh
    names = {
        0: "R", 1: "♭9" if seventh else "♭2", 2: "9" if seventh or third else "2",
        3: "♯9" if 4 in iv else "♭3", 4: "3", 5: "11" if third else "4",
        6: "♯11" if 7 in iv else "♭5", 7: "5", 8: "♭13" if 7 in iv else "♯5",
        9: "♭♭7" if diminished else "13" if seventh else "6", 10: "♭7", 11: "7",
    }
    return {i: names[i] for i in iv}


def _letter_name(root_name: str, number: int, pc: int) -> str:
    """The note ``number`` letters up from ``root_name`` (1 is the root), sounding ``pc``."""
    letter = _LETTERS[(_LETTERS.index(root_name[0]) + number - 1) % 7]
    return _spell(letter, (pc - _NATURAL[letter] + 6) % 12 - 6)


def chord_tones(chord: Chord, key: Key | None) -> list[tuple[str, str]]:
    """The chord's notes with their intervals, low to high by degree: C7 is [("C", "R"),
    ("E", "3"), ("G", "5"), ("Bb", "♭7")]. Each note is spelled from the root's letter (E7's
    third is G#, even in C), the root as ``key`` spells it. A bass that is no note of the chord
    comes in by its degree above the root (C/D's D is its "2")."""
    return list(_chord_tones(chord, key))


def _number(label: str) -> int:
    return 1 if label == "R" else int(label.lstrip("♭♯"))


@functools.lru_cache(maxsize=4096)
def _chord_tones(chord: Chord, key: Key | None) -> tuple[tuple[str, str], ...]:
    root = spelling(key)[chord.root]
    tones = [(label, interval) for interval, label in _tone_names(chord).items()]
    if chord.bass is not None and (interval := (chord.bass - chord.root) % 12) not in chord.intervals:
        tones.append((_BASS_DEGREES[interval], interval))
    tones.sort(key=lambda t: (_number(t[0]), t[1]))
    return tuple((_letter_name(root, _number(label), (chord.root + interval) % 12), label)
                 for label, interval in tones)


# Scales a solo over a chord may take besides the modes, by their intervals above the root.
_OTHER_SCALES = {
    "Phrygian dominant": (0, 1, 4, 5, 7, 8, 10),
    "melodic minor": (0, 2, 3, 5, 7, 9, 11),
    "diminished (whole-half)": (0, 2, 3, 5, 6, 8, 9, 11),
    "diminished (half-whole)": (0, 1, 3, 4, 6, 7, 9, 10),
    "whole-tone": (0, 2, 4, 6, 8, 10),
}


def _by_quality(chord: Chord) -> tuple[str, ...]:
    """The scales for a chord by its quality, best first: Locrian for a half-diminished or
    diminished triad, the whole-half diminished scale for a diminished seventh (the usual
    reading: its notes are the chord's and a whole step above each), Mixolydian then the
    half-whole diminished scale for a dominant (♭9, ♯9), the whole-tone scale for an augmented
    chord, major (then Lydian) for a major one, Dorian (then minor, melodic minor) for a minor one,
    Mixolydian for one with no 3rd."""
    iv = chord.intervals
    if 3 in iv and 6 in iv and 7 not in iv:
        return ("diminished (whole-half)", "locrian") if 9 in iv else ("locrian", "diminished (whole-half)")
    if 4 in iv and 8 in iv and 7 not in iv:
        return ("whole-tone",)
    if 4 in iv and 10 in iv:
        return ("mixolydian", "diminished (half-whole)", "whole-tone")
    if 4 in iv:
        return ("ionian", "lydian", "mixolydian", "diminished (half-whole)")
    if 3 in iv:
        return ("dorian", "aeolian", "phrygian", "melodic minor")
    return ("mixolydian", "ionian", "lydian")


def _intervals_of(name: str) -> tuple[int, ...]:
    return SCALES.get(name) or _OTHER_SCALES[name]


def solo_scale(chord: Chord, key: Key) -> tuple[str, tuple[str, ...]]:
    """The scale for a solo over ``chord`` and its notes: ("D Dorian", ("D", "E", "F", ...)).

    The key's own mode on the chord's root for a chord in the key (Dm7 in C: D Dorian), the mode of
    the key a borrowed chord comes from (B♭ from C minor: B♭ Mixolydian), Mixolydian for a
    secondary dominant, Phrygian dominant for a minor key's dominant with its raised seventh (E7
    in A minor), and by quality otherwise (``_by_quality``); always one that holds every note
    of the chord. Read without the next chord, as a chord's card shows it.
    """
    return _solo_scale(chord, key)


@functools.lru_cache(maxsize=4096)
def _solo_scale(chord: Chord, key: Key) -> tuple[str, tuple[str, ...]]:
    reading = _read(chord, key, None)
    candidates: list[str] = []
    home = key if reading.kind == "in" else reading.source
    if home is not None and (chord.root - home.tonic) % 12 in SCALES[home.mode]:
        index = SCALES[home.mode].index((chord.root - home.tonic) % 12)
        candidates.append(MODES[(MODES.index(home.mode) + index) % 7])
    if home is not None and home.mode == "aeolian" and (chord.root - home.tonic) % 12 == 7:
        candidates.append("Phrygian dominant")
    if reading.kind == "secondary":
        candidates.append("mixolydian")
    candidates += _by_quality(chord)
    pcs = {(pc - chord.root) % 12 for pc in chord.pitch_classes}
    name = next((c for c in candidates if pcs <= set(_intervals_of(c))), candidates[0])
    root = spelling(key)[chord.root]
    steps = _intervals_of(name)
    if len(steps) == 7:
        notes = tuple(_letter_name(root, i + 1, (chord.root + s) % 12) for i, s in enumerate(steps))
    else:
        notes = tuple(spelling(key)[(chord.root + s) % 12] for s in steps)
    return f"{root} {_mode_word(name) if name in SCALES else name}", notes


@functools.cache
def key_scale(key: Key) -> tuple[int, ...]:
    """The key's pitch classes, from its tonic up."""
    return tuple((key.tonic + i) % 12 for i in SCALES[key.mode])


@functools.cache
def pentatonic(key: Key) -> tuple[int, ...]:
    """The key's pentatonic box, from its tonic up: the major pentatonic (1 2 3 5 6) for a key with
    a major third, the minor pentatonic (1 ♭3 4 5 ♭7) for one with a minor third, each the key's
    own degrees, so always notes of its scale (Locrian's has its ♭5)."""
    degrees = (0, 1, 2, 4, 5) if 4 in SCALES[key.mode] else (0, 2, 3, 4, 6)
    return tuple(key_scale(key)[d] for d in degrees)


# --- progressions -------------------------------------------------------------------------------

_ROMAN = r"([♭♯b#]?)(VII|VI|V|IV|III|II|I|vii|vi|v|iv|iii|ii|i)"
_NUMERAL = re.compile(_ROMAN + r"([^/]*)((?:/[^/]+)*)$")
_ROMAN_ONLY = re.compile(_ROMAN + r"[°ø+]?$")
_SEPARATORS = re.compile(r"[\s,–—-]+")


def _core(text: str) -> str:
    """A numeral's root, its case and the chord it is the V of: "Imaj7" -> "I", "V7/V/3" ->
    "V/V", "bVII" -> "♭VII". A text that is no numeral stays as it is."""
    m = _NUMERAL.match(text)
    if not m:
        return text
    accidental, roman, _, slashes = m.groups()
    core = {"b": "♭", "#": "♯"}.get(accidental, accidental) + roman
    for part in slashes.split("/")[1:]:
        if of := _ROMAN_ONLY.match(part):
            core += "/" + {"b": "♭", "#": "♯"}.get(of.group(1), of.group(1)) + of.group(2)
            break
    return core


def _collapse(items: Sequence[str]) -> list[str]:
    """A chord held over several lines once: consecutive repeats dropped."""
    return [x for i, x in enumerate(items) if i == 0 or x != items[i - 1]]


def _period(items: Sequence[str]) -> int:
    """The length of the shortest cycle ``items`` repeats whole."""
    n = len(items)
    return next(p for p in range(1, n + 1) if n % p == 0 and list(items) == list(items[:p]) * (n // p))


def progression_key(numerals: Sequence[str] | str) -> str:
    """A progression's key for searching, the same in every key, rotation and repeat: the
    numerals' roots ("Imaj7" is "I", "I/3" is "I", "V7/V" is "V/V"), a chord held twice once, the
    cycle once, turned to start where its numerals sort first: "vi IV I V" and "IV I V vi IV I V
    vi" are both "I V vi IV". ``numerals`` may be one string ("vi IV I V", "vi–IV–I–V")."""
    if isinstance(numerals, str):
        numerals = [n for n in _SEPARATORS.split(numerals) if n]
    cores = _collapse([_core(n) for n in numerals])
    while len(cores) > 1 and cores[0] == cores[-1]:
        cores.pop()
    if not cores:
        return ""
    cycle = cores[: _period(cores)]
    return " ".join(min(tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))))


@functools.cache
def _catalogue() -> dict[str, str]:
    names: dict[str, str] = {}
    for name, numerals in CATALOGUE:
        names.setdefault(progression_key(numerals), name)
    return names


def _ending(cores: Sequence[str]) -> str | None:
    """How a section ends: V–I authentic, IV–I plagal, V–vi deceptive, on V half."""
    cores = _collapse(cores)
    if len(cores) < 2:
        return None
    before, last = cores[-2], cores[-1]
    if last in ("I", "i") and before == "V":
        return "authentic"
    if last in ("I", "i") and before in ("IV", "iv"):
        return "plagal"
    if before == "V" and last in ("vi", "♭VI", "VI"):
        return "deceptive"
    if last == "V":
        return "half"
    return None


def progressions(sections: Sequence[tuple[str, Sequence[Chord | None]]],
                 key: Key) -> list[tuple[str, Progression]]:
    """Each section's progression, by its name, in the sheet's order: its chords as numerals, each
    read with the next chord on the sheet (across sections); a chord caracole can't read (None:
    N.C.) is left out, and a section with no chord it can read has none."""
    frozen = tuple((name, tuple(chords)) for name, chords in sections)
    return list(_progressions(frozen, key))


@functools.lru_cache(maxsize=1024)
def _progressions(sections: tuple[tuple[str, tuple[Chord | None, ...]], ...],
                  key: Key) -> tuple[tuple[str, Progression], ...]:
    played = [(i, c) for i, (_, chords) in enumerate(sections) for c in chords if c is not None]
    texts: list[list[str]] = [[] for _ in sections]
    for (i, chord), after in zip(played, _goes_to([c for _, c in played]), strict=True):
        texts[i].append(numeral(chord, key, after).text)
    found = []
    for (name, _), numerals in zip(sections, texts, strict=True):
        if not numerals:
            continue
        held = _collapse(numerals)
        period = _period(held)
        cycle = tuple(held[:period])
        found.append((name, Progression(cycle, len(held) // period,
                                        _catalogue().get(progression_key(cycle)),
                                        _ending([_core(t) for t in held]))))
    return tuple(found)
