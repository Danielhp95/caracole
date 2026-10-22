"""What each chord does in its key: Roman numerals, relations, families, the glossary's lines, a
chord's notes and the scale for a solo over it, the key's scale on the neck, and each section's
progression with its name and how it ends. On top of theory.py's chords and keys.

**Numerals** count the chord's root up from the key's tonic, written against the tonic's major
scale (theory.py's ``_DEGREES``): a degree the key lowers or raises gets ♭ or ♯, so A minor's C is
♭III and C Mixolydian's B♭ is ♭VII. Upper case for a chord with a major third (or none), lower case
for a minor or diminished one; then ° (diminished), ø (half-diminished), + (augmented) and the
extensions as the chord's name has them (V7, ii9, Isus4, I5; a 6/9 is I69, as the slash is the
bass's). A slash chord's bass is its degree
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
  so E7 and G♯°7 are A minor's V7 and vii°7, as ``theory.estimate_key`` counts them, and one on
  the tonic the seventh (Am(maj7) is A minor's i(maj7), and C minor's in C). But a dominant
  seventh of the key, on neither its tonic nor its fifth, that goes a fifth down to a chord of
  the key is secondary: G7 C in A minor is V7/♭III (G7 going elsewhere is ♭VII7).
- *secondary*: a dominant (a major third, no major seventh) a fifth above a major or minor chord
  of the key other than the tonic (V/x), or a leading-tone chord (diminished or half-diminished)
  a half step below one (vii°/x). Read so when it goes to that chord, or when no mode on the
  tonic holds it (E major in C is V/vi wherever it goes). One a mode holds and that goes
  elsewhere is borrowed: D major in C going to C is C Lydian's II (rock's "Lydian II"), going
  to G it is V/V. On the tonic, only a dominant seventh going to IV (iv) that is no dominant
  seventh itself: C Cmaj7 C7 F is I Imaj7 V7/IV IV, Am A7 Dm is i V7/iv iv, and a blues's C7 F7
  stays I7 IV7.
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
once; the cycle it repeats folded ("vi IV I V" ×4), even when a pass varies it by a chord changed,
added or left out, or in a cycle of four or more a chord changed and one added or left out ("×8, one
variation", ``_fold``); its name from ``CATALOGUE`` when the cycle is a progression of it whole, and
the ones the section plays within it, with the times (``Contained``: "contains the pop progression
×2"); and its ending. Names compare the chords' roots and thirds (``_token``): extensions and the bass
are left aside (Imaj7, I7 and I/3 are I), a chord with no third (sus2, sus4, a power chord) is major or
minor (Asus4 is vi as well as VI), and a secondary chord is the chord on its own root (V7/V is II7, so
the ragtime progression's III7 is the V7/vi a sheet's E7 reads as). A progression that loops
(``_LOOPS``) is named from any of its chords (vi–IV–I–V is the pop progression), within a longer
section from another than its first only when played twice; one that goes somewhere, from its first
alone (V–I–ii is no ii–V–I, I–vi–ii–V no circle of fifths, nor the blues's changes turned round a
blues), and within each pass of a section played round and round, never across two. Each is named in
any key, on its own tonic and, but the blues, the Aeolian cadence and the names that are numerals, read
in the relative key too, where a song whose key caracole read as the other of the two plays it (the pop
progression in A minor is i–♭VI–♭III–♭VII; the Aeolian shuttle there from its first chord alone).
``progression_key``, for searching, compares the numerals' roots alone (Imaj7 is I, I/3 is I; V/V
stays V/V, but V/IV, built on the tonic, is I); ``name_of`` names numerals typed, ``read_typed`` reads
them in a minor key's own way too ("i VII VI V" is i–♭VII–♭VI–V).

**Notes** keep one letter a degree, from the root up (G♯7's 3rd is B♯, F♯ major's 7th E♯; a double
sharp is "##", a double flat "bb"). The root is spelled as the key spells it, a secondary chord's
from the chord it belongs to (G♯°7 to Am in C, not A♭°7), and by its other name when that needs
fewer double sharps and flats (C♯m7♭5 in C, not D♭'s F♭, A♭♭ and C♭).

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
    FLATS,
    MODES,
    SCALES,
    SHARPS,
    Chord,
    Key,
    _diatonic_quality,
    _intervals,
    scale,
    spelling,
)

ROMANS = ("I", "II", "III", "IV", "V", "VI", "VII")
_IONIAN = SCALES["ionian"]

# Each quality of theory.QUALITIES as a numeral writes it: (lower case, its sign, its extension).
_SHAPES: dict[str, tuple[bool, str, str]] = {
    "": (False, "", ""), "m": (True, "", ""), "5": (False, "", "5"), "dim": (True, "°", ""),
    "aug": (False, "+", ""), "sus2": (False, "", "sus2"), "sus4": (False, "", "sus4"),
    "b5": (False, "", "♭5"), "6": (False, "", "6"), "m6": (True, "", "6"), "69": (False, "", "69"),
    "m69": (True, "", "69"), "7": (False, "", "7"), "maj7": (False, "", "maj7"),
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
class Contained:
    """A progression of ``CATALOGUE`` that a section plays within it: its name, the times the section plays it,
    its numerals the first time, and its name's key for searching (``progression_key`` of its first row's)."""

    name: str
    times: int
    numerals: tuple[str, ...]
    key: str


@dataclass(frozen=True)
class Progression:
    """A section's chords in numerals: one cycle, played ``repeats`` times, ``variations`` of them otherwise."""

    numerals: tuple[str, ...]  # one cycle, repeats folded
    repeats: int
    name: str | None  # from CATALOGUE: the cycle is that progression whole
    ending: str | None  # "authentic", "plagal", "half", "deceptive"
    variations: int = 0  # the passes of the cycle that play it otherwise, a chord changed, added or left out
    contains: tuple[Contained, ...] = ()  # the progressions of CATALOGUE played within it, but its name


# Progressions with a common name: (name, numerals, source), each in its own key, as a song plays it (upper
# case major, lower case minor, a secondary dominant as numeral() writes it: V/vi is III, the V of vi). A row
# is matched on its chords' roots and thirds alone: a chord's extensions and its bass are left aside, and a
# chord with no third (sus2, sus4, a power chord) is major or minor. Only names a musician would know, each
# with where it is so named: Wikipedia's articles, and Open Music Theory, 2nd edition (Gotham et al., 2021),
# part VII, Popular Music.
CATALOGUE: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("the pop progression", ("I", "V", "vi", "IV"),
     'Wikipedia, "I–V–vi–IV progression" (the Axis progression; vi–IV–I–V, its turn, Marc Hirsh\'s "sensitive '
     'female chord progression"); Open Music Theory 2e, 7.9 Four-Chord Schemas ("singer/songwriter")'),
    ("the '50s progression", ("I", "vi", "IV", "V"),
     'Wikipedia, "\'50s progression" (the doo-wop progression, the "Heart and Soul" chords, the "Stand by Me" '
     'changes); Open Music Theory 2e, 7.9 Four-Chord Schemas ("doo-wop")'),
    ("the circle of fifths", ("vi", "ii", "V", "I"), 'Wikipedia, "Circle progression" (vi–ii–V–I)'),
    ("the circle of fifths", ("I", "IV", "vii°", "iii", "vi", "ii", "V", "I"),
     'Wikipedia, "Circle progression" (I–IV–vii°–iii–vi–ii–V–I, every chord of the key)'),
    ("the circle of fifths", ("i", "iv", "♭VII", "♭III", "♭VI", "ii°", "V", "i"),
     'Wikipedia, "Circle progression" ("in a minor key, the progression is i–iv–VII–III–VI–ii°–V–i")'),
    ("Pachelbel's Canon", ("I", "V", "vi", "iii", "IV", "I", "IV", "V"),
     'Wikipedia, "Pachelbel\'s Canon" (I–V–vi–iii–IV–I–IV–V, in many pop songs)'),
    ("the royal road", ("IV", "V", "iii", "vi"),
     'Wikipedia, "Royal road progression" (ōdō shinkō, IVM7–V7–iii7–vi; in a minor key VIM7–VII7–v7–i)'),
    ("the double-plagal progression", ("♭VII", "IV", "I"),
     'Open Music Theory 2e, 7.8 Blues-Based Schemas and 7.12 Modal Schemas (Walter Everett\'s "double-plagal", '
     '♭VII–IV–I: the coda of "Hey Jude"; looped, I–♭VII–IV)'),
    ("the Creep progression", ("I", "V/vi", "IV", "iv"),
     'Wikipedia, "Creep (Radiohead song)" (G–B–C–Cm, I–V7/vi–IV–iv, as in "The Air That I Breathe"); Open '
     'Music Theory 2e, 7.11 Puff Schemas'),
    ("the Aeolian shuttle", ("i", "♭VII", "♭VI", "♭VII"),
     'Open Music Theory 2e, 7.12 Modal Schemas ("Aeolian shuttle i–♭VII–♭VI–♭VII", circling on its minor tonic: the '
     'chorus of "Somebody That I Used to Know"); Wikipedia, "List of chord progressions" (I–♭VII–♭VI–♭VII, minor)'),
    ("ii–V–I", ("ii", "V", "I"), 'Wikipedia, "ii–V–I progression"'),
    ("the minor ii–V–i", ("ii", "V", "i"), 'Wikipedia, "ii–V–I progression" (in C minor, Dm7♭5–G7–Cm)'),
    ("I–IV–V", ("I", "IV", "V"), 'Wikipedia, "Three-chord song" (scale degrees I, IV and V)'),
    ("the 12-bar blues", ("I", "IV", "I", "V", "IV", "I"),
     'Wikipedia, "Twelve-bar blues" (I–I–I–I–IV–IV–I–I–V–IV–I–I)'),
    ("the 12-bar blues", ("I", "IV", "I", "V", "IV", "I", "V"),
     'Wikipedia, "Twelve-bar blues" (with the turnaround\'s V)'),
    ("the 12-bar blues", ("I", "IV", "I", "IV", "I", "V", "IV", "I"),
     'Wikipedia, "Twelve-bar blues" (the quick change: IV in the second bar)'),
    ("the 12-bar blues", ("I", "IV", "I", "IV", "I", "V", "IV", "I", "V"),
     'Wikipedia, "Twelve-bar blues" (the quick change, with the turnaround\'s V)'),
    # Not the article's other 8-bar blues, I–V7–IV7–IV7–I–V7 IV7–I–V7: a chord held once (no bars), it is an I–V–IV
    # vamp played twice and a half, as many a verse plays it.
    ("the 8-bar blues", ("I", "V", "IV", "I", "V", "I", "V"),
     'Wikipedia, "Eight-bar blues" (I7–V7–IV7–IV7–I7–V7–I7–V7, "Key to the Highway"); Wikipedia, "List of chord '
     'progressions" (I–V–IV–IV–I–V–I–V)'),
    ("the Andalusian cadence", ("i", "♭VII", "♭VI", "V"),
     'Wikipedia, "Andalusian cadence" (i–♭VII–♭VI–V, "the minor descending tetrachord"); Open Music Theory 2e, '
     '7.10 Classical Schemas (the lament bass on a minor tonic, "most typically ... harmonized by I–♭VII–♭VI–V")'),
    ("the lament", ("i", "♭VII", "♭VI", "v"),
     'Open Music Theory 2e, 7.12 Modal Schemas (an Aeolian schema, "Lament i–♭VII–♭VI–v": with a minor v, where the '
     'Andalusian cadence has V; Eva Simons\'s "I Don\'t Like You")'),
    ("the ragtime progression", ("V/vi", "V/ii", "V/V", "V"),
     'Wikipedia, "Ragtime progression" (III7–VI7–II7–V7–I: each chord the V7 of the next)'),
    ("the ragtime progression", ("V/vi", "V/ii", "V/V", "V", "I"), 'Wikipedia, "Ragtime progression"'),
    ("the ragtime progression", ("I", "V/vi", "V/ii", "V/V", "V"), 'Wikipedia, "Ragtime progression" (from its I)'),
    ("the extended plagal progression", ("♭VI", "♭III", "♭VII", "IV", "I"),
     'Open Music Theory 2e, 7.8 Blues-Based Schemas ("extended plagal, ♭VI–♭III–♭VII–IV–I": the verse of Jimi '
     'Hendrix\'s "Hey Joe")'),
    ("the backdoor progression", ("iv", "♭VII", "I"),
     'Wikipedia, "Backdoor progression" (iv7–♭VII7–I, "the backdoor ii–V")'),
    ("the Aeolian cadence", ("♭VI", "♭VII", "i"), 'Open Music Theory 2e, 7.12 Modal Schemas (♭VI–♭VII–i, or I)'),
    ("the Aeolian cadence", ("♭VI", "♭VII", "I"),
     'Open Music Theory 2e, 7.12 Modal Schemas; Wikipedia, "List of chord progressions" (♭VI–♭VII–I)'),
    ("the minor plagal cadence", ("IV", "iv", "I"),
     'Wikipedia, "Plagal cadence" (the minor plagal cadence, iv–I, "often follows a major IV chord, creating an '
     'IV–iv–I progression"); Open Music Theory 2e, 7.8 Blues-Based Schemas (the "plagal sigh")'),
    ("the puff progression", ("I", "iii", "IV"),
     'Open Music Theory 2e, 7.11 Puff Schemas (I–iii–IV, after "Puff, the Magic Dragon")'),
    ("the puff progression", ("I", "V/vi", "IV"), 'Open Music Theory 2e, 7.11 Puff Schemas (its I–III♯–IV)'),
    ("the Montgomery-Ward bridge", ("I", "IV", "ii", "V"),
     'Wikipedia, "Montgomery-Ward bridge" (I7–IV7–ii7–V7, "Riepel\'s Monte")'),
)
# The rows that loop, by their numerals, so that a section may start on any of their chords, as their sources turn
# them: the pop progression's vi–IV–I–V, the double plagal looped I–♭VII–IV, the circle through every chord (a song
# may start it on its iv, as "Autumn Leaves" does). The others go somewhere and start on their first chord: the
# blues's changes turned round, "C G F C F", are no blues, nor V–I–ii a ii–V–I, iii–vi–IV–V the royal road or
# I–vi–ii–V the circle of fifths (jazz's turnaround, which "Circle progression" keeps apart from vi–ii–V–I).
_LOOPS = frozenset({
    ("I", "V", "vi", "IV"),  # the pop progression
    ("I", "vi", "IV", "V"),  # the '50s progression
    ("I", "IV", "vii°", "iii", "vi", "ii", "V", "I"),  # the circle of fifths through every chord
    ("i", "iv", "♭VII", "♭III", "♭VI", "ii°", "V", "i"),  # and in a minor key
    ("I", "V", "vi", "iii", "IV", "I", "IV", "V"),  # Pachelbel's Canon
    ("♭VII", "IV", "I"),  # the double-plagal progression
    ("I", "V/vi", "IV", "iv"),  # the Creep progression
    ("i", "♭VII", "♭VI", "♭VII"),  # the Aeolian shuttle
})
# Names read on the song's own tonic alone, never in its relative key (the others are: the pop progression in a
# song read in A minor rather than C major is i–♭VI–♭III–♭VII): the blues are major, the Aeolian cadence read in
# the relative major is a deceptive IV–V–vi, and a name that is numerals says where its tonic is.
_ON_ITS_TONIC = frozenset({"the 12-bar blues", "the 8-bar blues", "the Aeolian cadence", "ii–V–I",
                           "the minor ii–V–i", "I–IV–V"})
# Loops whose turns are named on their own tonic alone: the Aeolian shuttle circles on its minor tonic, and turned
# in the relative major (IV–V–vi–V) it is a major key's climb to its vi and back, no shuttle. Read in the relative
# key it is named from its first chord (vi–V–IV–V).
_TURNS_ON_ITS_TONIC = frozenset({"the Aeolian shuttle"})

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


def _key_words(key: Key, home: Key | None = None) -> str:
    """"C major", "A minor", "C Mixolydian". A key on ``home``'s tonic (the key a chord is
    borrowed from) spells it as ``home`` does: Eb minor in Eb major, never D# minor."""
    return f"{spelling(home or key)[key.tonic]} {_mode_word(key.mode)}"


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


def _dominant_seventh(chord: Chord | None) -> bool:
    return chord is not None and _dominant(chord) and 10 in chord.intervals


def _leading(chord: Chord) -> bool:
    iv = chord.intervals
    return 3 in iv and 6 in iv and 4 not in iv and 7 not in iv


def _holds(key: Key, chord: Chord) -> bool:
    """Every note of the chord is in the key: in a minor key, a chord on the fifth or seventh
    degree may raise the sixth and seventh, and one on the tonic the seventh (i(maj7))."""
    notes = scale(key)
    if key.mode == "aeolian":
        degree = (chord.root - key.tonic) % 12
        if degree in (7, 11):
            notes = notes | {(key.tonic + 9) % 12, (key.tonic + 11) % 12}
        elif degree == 0:
            notes = notes | {(key.tonic + 11) % 12}
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
    fifth_below = (chord.root + 5) % 12
    resolves = next_chord is not None and next_chord.root == fifth_below
    if _holds(key, chord):
        # A dominant seventh of the key (not its own V, not on its tonic) going a fifth down to a
        # chord of the key: G7 C in A minor is V7/♭III.
        if (resolves and _dominant_seventh(chord) and (chord.root - key.tonic) % 12 not in (0, 7)
                and _target(fifth_below, key) is not None):
            return _Reading("secondary", None, fifth_below)
        return _Reading("in")
    sources = [Key(key.tonic, m) for m in _borrows(key)]
    source = next((s for s in sources if _holds(s, chord)), None)
    if chord.root == key.tonic:
        # A tonic dominant seventh going to IV (iv) is its V7, unless that is a dominant seventh
        # too: C7 F is V7/IV, a blues's C7 F7 stays I7 IV7.
        if (resolves and _dominant_seventh(chord) and not _dominant_seventh(next_chord)
                and _target(fifth_below, key) is not None):
            return _Reading("secondary", None, fifth_below)
    else:
        for kind, fits, step in (("secondary", _dominant, 5), ("leading", _leading, 1)):
            target = (chord.root + step) % 12
            if fits(chord) and _target(target, key) is not None:
                goes = next_chord is not None and next_chord.root == target
                if goes or source is None:
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
        return Relation("borrowed", _key_words(reading.source, key), None)
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
    "5": "only its root and 5th", "6": "an added 6th", "69": "an added 6th and 9th",
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
_TOKENS = re.compile(r"maj\d+|add\d+|sus\d|69|[♭♯]\d+|no\d|\d+|.")


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


def _chord_name(chord: Chord, key: Key, next_chord: Chord | None) -> str:
    bass = "" if chord.bass is None else "/" + spelling(key)[chord.bass]
    return _root_name(chord, key, _read(chord, key, next_chord)) + chord.suffix + bass


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
        line += f"; borrowed from {_key_words(reading.source, key)}"
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
        example = f"{_chord_name(chord, key, after)} = {n.text}"
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


def _named(letter: str, pc: int) -> str:
    """``letter`` with the sharps or flats that make it sound ``pc``: E# and Cb stay, a double
    one is "##" or "bb"."""
    step = (pc - _NATURAL[letter] + 6) % 12 - 6
    return letter + ("#" * step if step > 0 else "b" * -step)


def _letter_name(root_name: str, number: int, pc: int) -> str:
    """The note ``number`` letters up from ``root_name`` (1 is the root), sounding ``pc``: one
    letter a degree, so G#7's 3rd is B#."""
    return _named(_LETTERS[(_LETTERS.index(root_name[0]) + number - 1) % 7], pc)


def _doubles(root_name: str, chord: Chord, steps: Sequence[int]) -> tuple[int, int]:
    """How many double sharps or flats the chord's notes, then the scale's (``steps``, a scale of
    seven), need when spelled up from ``root_name``."""
    def count(notes):
        return sum(len(n) > 2 for n in notes)
    tones = count(_letter_name(root_name, _number(label), (chord.root + i) % 12)
                  for i, label in _tone_names(chord).items())
    notes = count(_letter_name(root_name, n + 1, (chord.root + s) % 12)
                  for n, s in enumerate(steps)) if len(steps) == 7 else 0
    return tones, notes


def _root_name(chord: Chord, key: Key | None, reading: _Reading | None,
               steps: Sequence[int] = ()) -> str:
    """The chord's root as its notes are spelled from: as ``key`` spells it, but a secondary
    chord's from the chord it belongs to (G#dim7 to Am: a half step below A; a V/x a fifth above
    x), and the other name of the note when that spells the chord (then its scale) with fewer
    double sharps and flats (C#m7b5 in C, not Db's Fb, Abb and Cb)."""
    names = spelling(key)
    first = names[chord.root]
    if key is not None and reading is not None and reading.kind in ("secondary", "leading"):
        target = names[reading.target][0]
        letter = _LETTERS[(_LETTERS.index(target) + (4 if reading.kind == "secondary" else 6)) % 7]
        if len(name := _named(letter, chord.root)) <= 2:
            first = name
    candidates = [first] + [n for n in (SHARPS[chord.root], FLATS[chord.root]) if n != first]
    return min(candidates, key=lambda n: _doubles(n, chord, steps))  # the first of the best


def chord_tones(chord: Chord, key: Key | None) -> list[tuple[str, str]]:
    """The chord's notes with their intervals, low to high by degree: C7 is [("C", "R"),
    ("E", "3"), ("G", "5"), ("Bb", "♭7")]. Each note is spelled from the root's letter (E7's
    third is G#, even in C; G#7's B#), the root as the module's docstring says. A bass that is no note of the chord
    comes in by its degree above the root (C/D's D is its "2")."""
    return list(_chord_tones(chord, key))


def _number(label: str) -> int:
    return 1 if label == "R" else int(label.lstrip("♭♯"))


@functools.lru_cache(maxsize=4096)
def _chord_tones(chord: Chord, key: Key | None) -> tuple[tuple[str, str], ...]:
    if key is None:
        root = _root_name(chord, None, None)
    else:
        name = _scale_for(chord, key)
        root = _root_name(chord, key, _read(chord, key, None), _intervals_of(name))
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
    name = _scale_for(chord, key)
    steps = _intervals_of(name)
    root = _root_name(chord, key, _read(chord, key, None), steps)
    if len(steps) == 7:
        notes = tuple(_letter_name(root, i + 1, (chord.root + s) % 12) for i, s in enumerate(steps))
    else:  # no letter a degree: in sharps from a sharp root, in flats from a flat one
        names = SHARPS if "#" in root else FLATS if "b" in root else spelling(key)
        notes = (root, *(names[(chord.root + s) % 12] for s in steps[1:]))
    return f"{root} {_mode_word(name) if name in SCALES else name}", notes


@functools.lru_cache(maxsize=4096)
def _scale_for(chord: Chord, key: Key) -> str:
    """The name of the scale ``solo_scale`` gives for ``chord``: a mode or one of _OTHER_SCALES."""
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
    return next((c for c in candidates if pcs <= set(_intervals_of(c))), candidates[0])


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


# A V/x built on the tonic is the I it stands on, as names compare roots: C C7 F is I IV.
_ON_THE_TONIC = {"V/IV": "I", "V/iv": "I"}


def _core(text: str) -> str:
    """A numeral's root, its case and the chord it is the V of: "Imaj7" -> "I", "V7/V/3" ->
    "V/V", "bVII" -> "♭VII", "V7/IV" -> "I". A text that is no numeral stays as it is."""
    m = _NUMERAL.match(text)
    if not m:
        return text
    accidental, roman, _, slashes = m.groups()
    core = {"b": "♭", "#": "♯"}.get(accidental, accidental) + roman
    for part in slashes.split("/")[1:]:
        if of := _ROMAN_ONLY.match(part):
            core += "/" + {"b": "♭", "#": "♯"}.get(of.group(1), of.group(1)) + of.group(2)
            break
    return _ON_THE_TONIC.get(core, core)


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
    cycle = _cycle(numerals)
    if not cycle:
        return ""
    return " ".join(min(tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))))


def _cycle(numerals: Sequence[str]) -> list[str]:
    """The numerals' roots, a chord held twice once, a last chord that is the first again
    dropped, the cycle once: as written, not turned."""
    cores = _collapse([_core(n) for n in numerals])
    while len(cores) > 1 and cores[0] == cores[-1]:
        cores.pop()
    return cores[: _period(cores)] if cores else []


# --- the catalogue's names, where songs play them ---------------------------------------------------

_STEPS = {"I": 0, "II": 2, "III": 4, "IV": 5, "V": 7, "VI": 9, "VII": 11}
_ACCIDENTALS = {"": 0, "♭": -1, "b": -1, "♯": 1, "#": 1}
_NO_TOKEN = (-1, "")  # a text that is no numeral: it fits nothing
# A chord's root in semitones above the tonic, and its third: "M" major (or augmented), "m" minor (or diminished),
# "?" none (sus2, sus4, a power chord), which fits either.
Token = tuple[int, str]


@functools.lru_cache(maxsize=4096)
def _token(text: str) -> Token:
    """A numeral as names compare it: "Imaj7" and "I/3" are (0, "M"), "vi7" (9, "m"), "♭VIIsus4" (10, "?"),
    a secondary chord on its own root: "V7/V" is (2, "M"), II, and "vii°/V" (6, "m"), ♯iv°."""
    m = _NUMERAL.match(text)
    if not m:
        return _NO_TOKEN
    accidental, roman, rest, slashes = m.groups()
    root = _STEPS[roman.upper()] + _ACCIDENTALS[accidental]
    for part in slashes.split("/")[1:]:
        if of := _ROMAN_ONLY.match(part):
            root += _STEPS[of.group(2).upper()] + _ACCIDENTALS[of.group(1)]
            break
    third = "?" if "sus" in rest or rest == "5" else "m" if roman.islower() else "M"
    return root % 12, third


def _fits(played: Token, wanted: Token) -> bool:
    """A chord played fits one of a progression: the same root, and the same third or none."""
    return played[0] == wanted[0] and played[1] in (wanted[1], "?")


def _same(a: Token, b: Token) -> bool:
    """Two chords played are one harmony: the same root, and the same third or one with none."""
    return a[0] == b[0] and (a[1] == b[1] or "?" in (a[1], b[1]))


def _merged(texts: Sequence[str]) -> list[tuple[Token, int]]:
    """The numerals as names compare them, each with the index of its first: a chord held, whatever its
    extensions, its bass or its suspension (Dsus4 D), once."""
    out: list[tuple[Token, int]] = []
    for i, text in enumerate(texts):
        token = _token(text)
        if out and token != _NO_TOKEN and _same(out[-1][0], token):
            held, first = out[-1]
            out[-1] = ((held[0], token[1] if held[1] == "?" else held[1]), first)
        else:
            out.append((token, i))
    return out


def _closed(tokens: Sequence[Token]) -> tuple[Token, ...]:
    """A cycle of chords: a last chord that is the first again dropped, the shortest cycle it repeats once."""
    cycle = list(tokens)
    while len(cycle) > 1 and _same(cycle[0], cycle[-1]):
        cycle.pop()
    n = len(cycle)
    period = next((p for p in range(1, n + 1) if n % p == 0
                   and all(_same(cycle[i], cycle[i % p]) for i in range(n))), n)
    return tuple(cycle[:period])


@dataclass(frozen=True)
class _Row:
    """A row of the catalogue as a key reads it: on the key's tonic (``own``), or in its relative key."""

    name: str
    tokens: tuple[Token, ...]
    numerals: tuple[str, ...]  # as numeral() writes its chords in the key, for its key for searching
    own: bool
    loops: bool  # a section may start it on any of its chords
    forms: tuple[tuple[Token, ...], ...]  # every run of chords that plays it: as written, or each turn of a loop, its own first


def _row(name: str, tokens: tuple[Token, ...], numerals: tuple[str, ...], own: bool, loops: bool) -> _Row:
    if loops:
        cycle = _closed(tokens)
        forms = tuple(dict.fromkeys(cycle[i:] + cycle[:i] for i in range(len(cycle))))
    else:
        forms = (tokens,)
    return _Row(name, tokens, numerals, own, loops, forms)


# The tonic of each mode above the tonic of the major scale with its notes: D Dorian is C major's.
_PARENT = {mode: _IONIAN[n] for n, mode in enumerate(MODES)}


@functools.cache
def _rows(mode: str) -> tuple[_Row, ...]:
    """The catalogue as a key in ``mode`` reads it: each row on the key's tonic, then each read in the key's
    relative one, where the row's tonic is in the scale the key's notes make (the pop progression read in A
    minor, i–♭VI–♭III–♭VII; the Andalusian cadence in C major, vi–V–IV–V/vi): a row with a minor tonic (i) is
    in a minor key, the others in a major one. Not those of ``_ON_ITS_TONIC``, and those of
    ``_TURNS_ON_ITS_TONIC`` from their first chord alone."""
    own: list[_Row] = []
    relative: list[_Row] = []
    for name, numerals, _ in CATALOGUE:
        tokens = tuple(_token(n) for n in numerals)
        loops = numerals in _LOOPS
        own.append(_row(name, tokens, tuple(numerals), True, loops))
        home = "aeolian" if (0, "m") in tokens else "ionian"
        shift = (_PARENT[home] - _PARENT[mode]) % 12
        if name in _ON_ITS_TONIC or shift == 0:
            continue
        moved = tuple(((root + shift) % 12, third) for root, third in tokens)
        relative.append(_row(name, moved, _written(moved, Key(0, mode), loops), False,
                             loops and name not in _TURNS_ON_ITS_TONIC))
    return tuple(own + relative)


def _written(tokens: Sequence[Token], key: Key, loops: bool) -> tuple[str, ...]:
    """The numerals numeral() gives the triads of ``tokens`` in ``key``, each read with the next (a loop's last
    with its first)."""
    chords = [Chord(root, "m" if third == "m" else "") for root, third in tokens]
    after = chords[1:] + [chords[0] if loops else None]
    return tuple(numeral(c, key, a).text for c, a in zip(chords, after, strict=True))


def _whole(tokens: Sequence[Token], mode: str) -> str | None:
    """The catalogue's name for a cycle played whole: one of a row's forms (a loop's in any turn), the cycle
    and the row each closed (``_closed``); the first row that fits, those on the tonic first."""
    cycle = _closed(tokens)
    for row in _rows(mode):
        forms = row.forms if row.loops else (_closed(row.tokens),)
        if any(len(form) == len(cycle) and all(map(_fits, cycle, form)) for form in forms):
            return row.name
    return None


def _contained(held: Sequence[str], mode: str, seams: Sequence[int] = ()) -> tuple[Contained, ...]:
    """The catalogue's progressions a section plays (``held``: its numerals, a chord held once) as runs of its
    chords, in the order it first plays each, with the times. Runs share no chord, but a run that ends on the
    chord it starts with (the blues, on I) lends that chord to the next; of the ways to read the section so,
    the one whose runs hold the most chords, then the fewest runs (a longer progression rather than two that
    make it), then the most read on the key's own tonic, then the one that starts a run first. So Dm7 G7 Cmaj7 Am
    G F E7 is ii–V–I, then the Andalusian cadence.

    A loop is played from any of its chords, but from another than its own first only twice or more: played
    once within a section, vi–IV–V–I is a cadence there ("Yesterday"), no '50s progression. A section played
    round and round (``seams``: where each pass after the first starts, ``_fold``) is read from where each pass
    starts: a progression that goes somewhere is named within a pass, never across the seam of two (I–vi–ii–V
    round and round plays no circle of fifths, vi–ii–V–I, nor V–I–ii a ii–V–I), but for a run that ends on the
    chord it starts with, which may end on the next pass's first."""
    merged = _merged(held)
    tokens = [t for t, _ in merged]
    n = len(tokens)
    # Each seam as the index of the chord (merged) it falls on.
    cuts = sorted({max(i for i, (_, first) in enumerate(merged) if first <= seam) for seam in seams})
    starting: dict[int, list[tuple[int, int, bool, bool, str]]] = {}
    for order, row in enumerate(_rows(mode)):
        for turn, form in enumerate(row.forms):
            k = len(form)
            closes = form[0] == form[-1]
            found = [start for start in range(n - k + 1)
                     if all(_fits(tokens[start + j], form[j]) for j in range(k))]
            if not row.loops:
                last = k - 2 if closes else k - 1  # the run's last chord a seam may not fall within
                found = [start for start in found if not any(start < cut <= start + last for cut in cuts)]
            elif turn and _apart(found, k) < 2:
                continue
            for start in found:
                starting.setdefault(start, []).append((k, order, row.own, closes, row.name))
    # best[pos]: the best reading of the chords from pos on, as (chords held, -runs, runs on the tonic), and
    # the run it starts with there (None: the chord at pos is in none).
    best: list[tuple[int, int, int]] = [(0, 0, 0)] * (n + 1)
    pick: list[tuple[int, bool, str] | None] = [None] * (n + 1)
    for pos in range(n - 1, -1, -1):
        best[pos] = best[pos + 1]
        for k, _, own, closes, name in sorted(starting.get(pos, ()), key=lambda c: (-c[0], not c[2], c[1])):
            end = pos + k - 1 if closes else pos + k
            rest = best[end]
            # A chord lent to the next run is held once.
            score = (rest[0] + k - (closes and pick[end] is not None), rest[1] - 1, rest[2] + own)
            if score > best[pos] or (score == best[pos] and pick[pos] is None):
                best[pos], pick[pos] = score, (k, closes, name)
    times: dict[str, int] = {}
    first: dict[str, tuple[str, ...]] = {}
    pos = 0
    while pos < n:
        if pick[pos] is None:
            pos += 1
            continue
        k, closes, name = pick[pos]
        times[name] = times.get(name, 0) + 1
        first.setdefault(name, tuple(held[merged[i][1]] for i in range(pos, pos + k)))
        pos += k - 1 if closes else k
    keys = _name_keys()
    return tuple(Contained(name, count, first[name], keys[name]) for name, count in times.items())


def _apart(starts: Sequence[int], k: int) -> int:
    """How many runs of ``k`` chords starting at ``starts`` (in order) a section plays one after another, none
    sharing a chord."""
    count, free = 0, 0
    for start in starts:
        if start >= free:
            count, free = count + 1, start + k
    return count


@functools.cache
def _name_keys() -> dict[str, str]:
    """Each name's key for searching: its first row's ``progression_key``."""
    keys: dict[str, str] = {}
    for name, numerals, _ in CATALOGUE:
        keys.setdefault(name, progression_key(numerals))
    return keys


@functools.cache
def _named_keys() -> tuple[tuple[str, str], ...]:
    found: dict[str, str] = {}
    for mode in ("ionian", "aeolian"):
        for row in _rows(mode):
            found.setdefault(progression_key(row.numerals), row.name)
    return tuple(found.items())


def catalogue_keys() -> dict[str, str]:
    """Each reading of the catalogue's progressions by its ``progression_key``, as a section's is: every row on
    its own tonic first, then read in a major key and in a minor one ({"I V vi IV": "the pop progression",
    "i ♭VI ♭III ♭VII": "the pop progression", ...})."""
    return dict(_named_keys())


def name_of(numerals: Sequence[str] | str) -> str | None:
    """The catalogue's name for a progression's numerals typed ("vi IV I V", "III7 VI7 II7 V7", "i VII VI V":
    ``read_typed``), played whole, read in a major key or in a minor one, as a section's is (a progression that
    goes somewhere from its first chord alone: "iii vi IV V" is no royal road); None for none."""
    return _name_of(read_typed(numerals))


# The degrees a minor key's own numerals write unaltered and this module's notation lowers: its III, VI and VII.
_NATURAL_MINOR = frozenset({"III", "VI", "VII"})


def read_typed(numerals: Sequence[str] | str) -> tuple[str, ...]:
    """Numerals as typed ("vi IV I V", "vi–IV–I–V", or a list of them), in this module's notation: written in a
    minor key's own way, against its natural minor scale (a minor tonic, i, and no accidental, as Wikipedia writes
    the minor circle, i–iv–VII–III–VI–ii°–V–i), a major III, VI or VII is its ♭III, ♭VI or ♭VII ("i VII VI V" is
    i–♭VII–♭VI–V); others are as typed."""
    if isinstance(numerals, str):
        numerals = [n for n in _SEPARATORS.split(numerals) if n]
    found = [_NUMERAL.match(n) for n in numerals]
    if any(m is None or m.group(1) for m in found) or not any(m.group(2) == "i" for m in found):
        return tuple(numerals)
    return tuple("♭" + n if m.group(2) in _NATURAL_MINOR else n for n, m in zip(numerals, found, strict=True))


@functools.lru_cache(maxsize=1024)
def _name_of(numerals: tuple[str, ...]) -> str | None:
    tokens = [t for t, _ in _merged(numerals)]
    if not tokens or _NO_TOKEN in tokens:
        return None
    return _whole(tokens, "ionian") or _whole(tokens, "aeolian")


# --- a section's repeats -----------------------------------------------------------------------------

_LONGEST_CYCLE = 16  # chords: a cycle of more is no loop


def _fold(held: Sequence[str]) -> tuple[tuple[str, ...], int, int, tuple[int, ...]]:
    """A section's numerals (a chord held once) as one cycle, the times it is played, how many of those play it
    otherwise, and where each pass after the first starts (an index of ``held``): the shortest cycle it repeats
    whole; else the shortest one played whole twice or more, and more often than not, where each other pass
    plays it with one chord changed, or one added or left out, or, in a cycle of four chords or more, a chord
    changed and one added or left out as well (``_varies``: Wonderwall's verse, Em7 G Dsus4 A7sus4 with one pass
    on Cadd9 Dsus4 A7sus4, is i7–♭III–♭VIIsus4–IV7sus4 ×8, one variation); the section may end on the cycle's
    first chords, home, which is no pass. Else the whole section, once."""
    n = len(held)
    period = _period(held)
    if period < n:
        return tuple(held[:period]), n // period, 0, tuple(range(period, n, period))
    for p in range(2, min(_LONGEST_CYCLE, n // 2) + 1):
        at: dict[tuple[str, ...], list[int]] = {}
        for i in range(n - p + 1):
            at.setdefault(tuple(held[i:i + p]), []).append(i)
        best: tuple[tuple[str, ...], int, int, tuple[int, ...]] | None = None
        for s in range(min(p + 1, n - p) + 1):  # a first pass that varies it has a chord more at most
            cycle = tuple(held[s:s + p])
            passes = _passes(held, cycle, at[cycle])
            if passes is not None and (best is None or (passes[0], -passes[1]) > (best[1], -best[2])):
                best = (cycle, *passes)
        if best is not None:
            cycle, whole, varied, seams = best
            return cycle, whole + varied, varied, seams
    return tuple(held), 1, 0, ()


def _passes(held: Sequence[str], cycle: tuple[str, ...], starts: list[int]) -> tuple[int, int, tuple[int, ...]] | None:
    """The passes of ``cycle`` the section plays whole, the others (``_varies``), and where each after the first
    starts, the home it may end on too; None when the section is no such cycle (``_fold``)."""
    if len(starts) < 2:
        return None
    n, p = len(held), len(cycle)
    whole = varied = 0
    seams: list[int] = []
    j = 0
    while j < n:
        if j:
            seams.append(j)
        if tuple(held[j:j + p]) == cycle:
            whole += 1
            j += p
            continue
        k = next((i for i in starts if i > j), None)
        rest = tuple(held[j:] if k is None else held[j:k])
        if k is None and len(rest) < p and cycle[:len(rest)] == rest:
            break  # home: the section ends on the cycle's first chords
        if not _varies(rest, cycle):
            return None
        varied += 1
        if k is None:
            break
        j = k
    return (whole, varied, tuple(seams)) if whole >= 2 and whole > varied else None


def _varies(played: Sequence[str], cycle: Sequence[str]) -> bool:
    """A pass ``played`` plays ``cycle`` otherwise: with one chord changed, or one added or left out, or, in a
    cycle of four chords or more, a chord changed and one added or left out as well. Two chords changed are
    another line (C G Am F, then Dm G C F)."""
    longer, shorter = (played, cycle) if len(played) >= len(cycle) else (cycle, played)
    if len(longer) == len(shorter):
        return sum(x != y for x, y in zip(longer, shorter, strict=True)) <= 1
    if len(longer) - len(shorter) != 1:
        return False
    changed = 1 if len(cycle) >= 4 else 0
    return any(sum(x != y for x, y in zip(longer[:i] + longer[i + 1:], shorter, strict=True)) <= changed
               for i in range(len(longer)))


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
        cycle, repeats, varied, seams = _fold(held)
        whole = _whole([t for t, _ in _merged(cycle)], key.mode)
        contains = tuple(c for c in _contained(held, key.mode, seams) if c.name != whole)
        found.append((name, Progression(cycle, repeats, whole, _ending([_core(t) for t in held]), varied,
                                        contains)))
    return tuple(found)
