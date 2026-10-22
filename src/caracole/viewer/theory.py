"""Chord names, keys and modes: the music theory behind the sheet viewer.

Pitch classes are integers, 0 for C up to 11 for B. A chord is a root, a
quality and an optional bass note; the quality names a set of intervals above
the root (``QUALITIES``). Chord names are read the way sheets write them:
"Am7", "CM7", "C7M", "CΔ", "C°", "Cø", "C-7", "C(add9)", "Dsus2/F#", "C6/9".

The viewer asks the same questions for every song of a library, the same chords in the same
keys, so the answers are kept (``functools`` caches): chords and keys are frozen, and a list
handed out is a copy of the one kept.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

# Quality -> intervals above the root, in semitones. The names are the canonical
# ones: what the viewer shows for a chord it makes up (an alternative, a chord in
# another mode), and what its fingerings are filed under.
QUALITIES: dict[str, frozenset[int]] = {
    name: frozenset(intervals)
    for name, intervals in {
        "": (0, 4, 7),
        "m": (0, 3, 7),
        "5": (0, 7),
        "dim": (0, 3, 6),
        "aug": (0, 4, 8),
        "sus2": (0, 2, 7),
        "sus4": (0, 5, 7),
        "b5": (0, 4, 6),
        "6": (0, 4, 7, 9),
        "m6": (0, 3, 7, 9),
        "69": (0, 2, 4, 7, 9),
        "m69": (0, 2, 3, 7, 9),
        "7": (0, 4, 7, 10),
        "maj7": (0, 4, 7, 11),
        "m7": (0, 3, 7, 10),
        "mmaj7": (0, 3, 7, 11),
        "m7b5": (0, 3, 6, 10),
        "dim7": (0, 3, 6, 9),
        "7sus4": (0, 5, 7, 10),
        "7sus2": (0, 2, 7, 10),
        "add9": (0, 2, 4, 7),
        "madd9": (0, 2, 3, 7),
        "add11": (0, 4, 5, 7),
        "9": (0, 2, 4, 7, 10),
        "maj9": (0, 2, 4, 7, 11),
        "m9": (0, 2, 3, 7, 10),
        "9sus4": (0, 2, 5, 7, 10),
        "11": (0, 2, 4, 5, 7, 10),
        "m11": (0, 2, 3, 5, 7, 10),
        "13": (0, 2, 4, 7, 9, 10),
        "7b5": (0, 4, 6, 10),
        "aug7": (0, 4, 8, 10),
        "7b9": (0, 1, 4, 7, 10),
        "7#9": (0, 3, 4, 7, 10),
    }.items()
}
_BY_INTERVALS = {intervals: name for name, intervals in QUALITIES.items()}
# How a made-up chord's quality is written, where that differs from its name. A flat fifth
# goes in brackets: "Gb5" is a G-flat power chord, "G(b5)" is G, B and D-flat.
DISPLAY = {"mmaj7": "m(maj7)", "69": "6/9", "m69": "m6/9", "b5": "(b5)"}

_NATURAL = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_LETTERS = "CDEFGAB"
SHARPS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLATS = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
_ACCIDENTAL = {"": 0, "#": 1, "♯": 1, "b": -1, "♭": -1}
_ROOT = re.compile(r"([A-G])([#♯b♭]?)")
_BASS = re.compile(r"/([A-G])([#♯b♭]?)$")


@dataclass(frozen=True)
class Chord:
    """A chord: ``root`` and ``bass`` are pitch classes, ``quality`` a key of QUALITIES (or the
    normalized suffix of a chord outside it, whose intervals are then in ``tones``).

    ``shown`` is the suffix as the sheet wrote it ("M7" for a maj7), kept for display; None for
    a chord the viewer made up, which shows its quality.
    """

    root: int
    quality: str
    bass: int | None = None
    shown: str | None = None
    tones: frozenset[int] | None = None

    @functools.cached_property
    def intervals(self) -> frozenset[int]:
        return self.tones if self.tones is not None else QUALITIES[self.quality]

    @functools.cached_property
    def pitch_classes(self) -> frozenset[int]:
        pcs = {(self.root + i) % 12 for i in self.intervals}
        if self.bass is not None:
            pcs.add(self.bass)
        return frozenset(pcs)

    @property
    def suffix(self) -> str:
        """The suffix to show: as written, or the quality's usual spelling."""
        return self.shown if self.shown is not None else DISPLAY.get(self.quality, self.quality)


def note_pc(letter: str, accidental: str = "") -> int:
    return (_NATURAL[letter] + _ACCIDENTAL[accidental]) % 12


def parse_chord(text: str, *, strict: bool = True) -> Chord | None:
    """The chord a name stands for, or None when it is none ("N.C.", "x2", "H").

    With ``strict=False`` a chord whose suffix isn't understood ("Cfoo") still
    gives its root and bass, sounding as a major or (suffix "m...") minor triad:
    the viewer can still transpose it.
    """
    text = text.strip()
    m = _ROOT.match(text)
    if not m:
        return None
    root = note_pc(*m.groups())
    rest = text[m.end():]
    bass = None
    if b := _BASS.search(rest):
        bass = note_pc(*b.groups())
        rest = rest[: b.start()]
    normalized = _normalize(rest)
    tones = _intervals(normalized)
    if tones is None:
        if strict or "/" in rest:
            return None
        minor = normalized.startswith("m") and not normalized.startswith("maj")
        return Chord(root, normalized, bass, rest, QUALITIES["m" if minor else ""])
    quality = _BY_INTERVALS.get(tones)
    if quality is None:
        return Chord(root, normalized, bass, rest, tones)
    return Chord(root, quality, bass, rest)


# Spellings of a suffix, rewritten in order before it is read (see _intervals). A sign that starts the
# suffix is read before the same sign inside it: "+7" is augmented ("aug7"), "7+5" a sharp fifth ("7#5"),
# and "+5" the sharp fifth that makes an augmented triad. "Maj" is read before "mM", so "mMaj7" is the
# minor-major seventh ("mmaj7"), never "mmajaj7".
_REWRITES = [
    (re.compile(r"[()\s]"), ""),
    (re.compile(r"♯"), "#"),
    (re.compile(r"♭"), "b"),
    (re.compile(r"6/9"), "69"),
    (re.compile(r"^Δ$"), "maj7"),
    (re.compile(r"Δ"), "maj"),
    (re.compile(r"^ø7?"), "m7b5"),
    (re.compile(r"^[°o]"), "dim"),
    (re.compile(r"^-"), "m"),
    (re.compile(r"-(?=\d)"), "b"),
    (re.compile(r"^\+(?!5)"), "aug"),
    (re.compile(r"\+(?=\d)"), "#"),
    (re.compile(r"^\+"), "aug"),
    (re.compile(r"^min?"), "m"),
    (re.compile(r"Maj|MA|Ma"), "maj"),
    (re.compile(r"^mM"), "mmaj"),
    (re.compile(r"^M(?=\d)"), "maj"),
    (re.compile(r"^M$"), ""),
    (re.compile(r"ma(?!j|dd)"), "maj"),
    (re.compile(r"7M$"), "maj7"),
    (re.compile(r"^2$"), "sus2"),
    (re.compile(r"^4$"), "sus4"),
]
_EXTENSION = re.compile(r"(maj)?(69|13|11|9|7|6)?")
_SUS = re.compile(r"sus(2|4)?")
_ALTERATION = re.compile(r"add(?:2|4|6|9|11|13)|[b#](?:5|9|11|13)|no[35]")
_ADDED = {"2": 2, "9": 2, "4": 5, "11": 5, "6": 9, "13": 9}
# Every altered extension _ALTERATION reads (b5 and #5 alter the fifth instead). A flat eleventh
# sounds as the major third, a sharp thirteenth as the flat seventh: rare, but sheets write them.
_ALTERED = {"b9": 1, "#9": 3, "b11": 4, "#11": 6, "b13": 8, "#13": 10}


def _normalize(suffix: str) -> str:
    for pattern, replacement in _REWRITES:
        suffix = pattern.sub(replacement, suffix)
    return suffix


def _intervals(s: str) -> frozenset[int] | None:
    """The intervals a normalized suffix spells, or None when it spells none.

    A suffix is a triad (minor "m", "dim", "aug", else major), an extension
    ("6", "7", "maj7", "9", "11", "13", "69"), a suspension ("sus2", "sus4")
    and alterations ("b5", "#9", "add9", "no3"), each optional, in that order.
    """
    if s == "5":
        return QUALITIES["5"]
    third: int | None = 4
    fifth: int | None = 7
    seventh: int | None = None
    extra: set[int] = set()
    dim = False
    pos = 0
    if s.startswith("dim"):
        third, fifth, dim, pos = 3, 6, True, 3
    elif s.startswith("aug"):
        fifth, pos = 8, 3
    elif s.startswith("m") and not s.startswith("maj"):
        third, pos = 3, 1
    m = _EXTENSION.match(s, pos)
    maj, ext = m.groups()
    pos = m.end()
    if maj and ext is None and third == 3:
        ext = "7"  # "mmaj" is the minor-major seventh
    if maj and ext in ("6", "69"):
        return None
    if ext in ("7", "9", "11", "13"):
        seventh = 11 if maj else 9 if dim and ext == "7" else 10
        extra |= {"7": set(), "9": {2}, "11": {2, 5}, "13": {2, 9}}[ext]
    elif ext == "6":
        extra.add(9)
    elif ext == "69":
        extra |= {2, 9}
    if sus := _SUS.match(s, pos):
        third = 2 if sus.group(1) == "2" else 5
        pos = sus.end()
    while pos < len(s):
        alt = _ALTERATION.match(s, pos)
        if not alt:
            return None
        token = alt.group()
        if token.startswith("add"):
            extra.add(_ADDED[token[3:]])
        elif token == "b5":
            fifth = 6
        elif token == "#5":
            fifth = 8
        elif token == "no3":
            third = None
        elif token == "no5":
            fifth = None
        elif (altered := _ALTERED.get(token)) is not None:
            if token in ("b9", "#9"):
                extra.discard(2)  # an altered ninth replaces the natural one
            extra.add(altered)
        else:
            return None  # read by the pattern but not known: the suffix spells no chord
        pos = alt.end()
    tones = {0, *extra} | {t for t in (third, fifth, seventh) if t is not None}
    return frozenset(tones)


# --- keys and modes -------------------------------------------------------------------------

MODES = ("ionian", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "locrian")
SCALES: dict[str, tuple[int, ...]] = {
    "ionian": (0, 2, 4, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
}


@dataclass(frozen=True)
class Key:
    """A tonic (pitch class) and a mode, one of MODES: C major is Key(0, "ionian")."""

    tonic: int
    mode: str


# The major keys' tonics, spelled with the fewer accidentals (F# over Gb: six either way).
_MAJOR_TONICS = FLATS[:6] + SHARPS[6:7] + FLATS[7:]
# The scale degree (0-6) each interval above the tonic is written as. Chromatic notes are the
# altered degrees chord sheets write: b2, b3, #4, b6, b7 in a major mode; in a minor one, b5
# for the tritone, and the raised third, sixth and seventh (C#, F#, G# in A minor).
_DEGREES = {
    "major": (0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6),
    "minor": (0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6, 6),
}
# Spellings no chord sheet uses, written as their usual names instead.
_RARE = {("E", 1): "F", ("B", 1): "C", ("F", -1): "E", ("C", -1): "B"}
_DEFAULT_SPELLING = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")


def spelling(key: Key | None) -> list[str]:
    """The name of each pitch class (index) in ``key``: Bb in F major, A# in E major.

    With no key, the names chord sheets use most (C#, Eb, F#, Ab, Bb).
    """
    return list(_spelling(key))


@functools.cache
def _spelling(key: Key | None) -> tuple[str, ...]:
    if key is None:
        return _DEFAULT_SPELLING
    tonic_letter = _tonic_letter(key)
    degrees = _DEGREES["major" if 4 in SCALES[key.mode] else "minor"]
    names = [""] * 12
    for interval in range(12):
        pc = (key.tonic + interval) % 12
        letter = _LETTERS[(tonic_letter + degrees[interval]) % 7]
        names[pc] = _spell(letter, (pc - _NATURAL[letter] + 6) % 12 - 6)
    return tuple(names)


def _tonic_letter(key: Key) -> int:
    """The letter (index into "CDEFGAB") of the key's tonic: that degree of its relative major."""
    degree = MODES.index(key.mode)
    relative = (key.tonic - SCALES["ionian"][degree]) % 12
    return (_LETTERS.index(_MAJOR_TONICS[relative][0]) + degree) % 7


def _spell(letter: str, accidental: int) -> str:
    if accidental == 0:
        return letter
    if abs(accidental) == 1:
        return _RARE.get((letter, accidental)) or letter + ("#" if accidental > 0 else "b")
    pc = (_NATURAL[letter] + accidental) % 12  # a double sharp or flat
    return (SHARPS if accidental > 0 else FLATS)[pc]


@functools.cache
def key_name(key: Key) -> str:
    """"G", "Am", "D dorian": the key as a chord sheet writes it."""
    tonic = _spelling(key)[key.tonic]
    if key.mode == "ionian":
        return tonic
    if key.mode == "aeolian":
        return tonic + "m"
    return f"{tonic} {key.mode}"


_KEY = re.compile(
    r"\s*([A-Ga-g])([#♯b♭]?)\s*(m|M|(?i:minor|min|major|maj|ionian|dorian|phrygian|lydian"
    r"|mixolydian|aeolian|locrian))?\s*"
)
_MODE_WORDS = {"m": "aeolian", "M": "ionian", "min": "aeolian", "minor": "aeolian",
               "maj": "ionian", "major": "ionian"}


def parse_key(text: object) -> Key | None:
    """The key a tab or a tag names ("Am", "F#m", "Bb", "C minor", "A dorian"), or None."""
    if not isinstance(text, str):
        return None
    m = _KEY.fullmatch(text)
    if not m:
        return None
    letter, accidental, word = m.groups()
    word = word or "M"
    mode = _MODE_WORDS.get(word) or _MODE_WORDS.get(word.lower()) or word.lower()
    return Key(note_pc(letter.upper(), accidental), mode)


def scale(key: Key) -> frozenset[int]:
    """The key's pitch classes."""
    return frozenset((key.tonic + i) % 12 for i in SCALES[key.mode])


def estimate_key(chords: list[Chord]) -> Key | None:
    """The major or minor key the chords (in the order the sheet plays them) are most likely in.

    Each chord whose notes are all in a key counts for it (in a minor key, a dominant or
    leading-note chord may raise the seventh: E7 in A minor), and one with only its root in
    the key counts a little. The tonic chord counts again, and more when the song starts or
    ends on it; a major chord on the fifth, a little. Between relative
    keys (G major and E minor share every note) that decides. None without chords.
    """
    if not chords:
        return None
    best: tuple[float, Key] | None = None
    for mode in ("ionian", "aeolian"):
        for tonic in range(12):
            key = Key(tonic, mode)
            score = _key_score(chords, key)
            if best is None or score > best[0]:
                best = (score, key)
    return best[1] if best else None


def _key_score(chords: list[Chord], key: Key) -> float:
    notes = scale(key)
    third = 3 if key.mode == "aeolian" else 4
    dominant = (key.tonic + 7) % 12
    leading = (key.tonic + 11) % 12

    def is_tonic(chord: Chord) -> bool:
        return chord.root == key.tonic and third in chord.intervals

    score = 0.0
    for chord in chords:
        allowed = notes
        if key.mode == "aeolian" and chord.root in (dominant, leading):
            allowed = notes | {leading}
        if chord.pitch_classes <= allowed:
            score += 1
        elif chord.root in notes:
            score += 0.25
        if is_tonic(chord):
            score += 0.5
        if chord.root == dominant and 4 in chord.intervals:
            score += 0.25
    if is_tonic(chords[0]):
        score += 1.25
    if is_tonic(chords[-1]):  # tabs often end on an outro or a fade, so no more than the start
        score += 1.25
    return score


@functools.lru_cache(maxsize=4096)
def map_chord(chord: Chord, key: Key, mode: str) -> Chord:
    """The chord in ``mode`` on the same tonic: each note moves to the same scale degree there.

    C minor's Ab becomes C major's Am, and its Bb7 a Bm7b5. A note outside the key's
    scale stays where it is, so the G of C minor (with its raised seventh, B) stays G. When
    the notes make no chord of QUALITIES, the new mode's own triad or seventh chord on the
    new root stands in. A chord the change leaves alone is returned as it is.
    """
    if mode == key.mode:
        return chord
    src, dst = SCALES[key.mode], SCALES[mode]

    def move(pc: int) -> int:
        interval = (pc - key.tonic) % 12
        return (key.tonic + dst[src.index(interval)]) % 12 if interval in src else pc

    root = move(chord.root)
    intervals = frozenset((move((chord.root + i) % 12) - root) % 12 for i in chord.intervals)
    bass = None if chord.bass is None else move(chord.bass)
    if (root, intervals, bass) == (chord.root, chord.intervals, chord.bass):
        return chord
    quality = _BY_INTERVALS.get(intervals)
    if quality is None:
        quality = _diatonic_quality(root, Key(key.tonic, mode), 4 if len(chord.intervals) > 3 else 3)
    return Chord(root, quality, bass, chord.shown if quality == chord.quality else None)


def _diatonic_quality(root: int, key: Key, size: int) -> str:
    """The quality of the key's own chord of ``size`` notes (3 or 4), stacked in thirds on ``root``."""
    steps = SCALES[key.mode]
    interval = (root - key.tonic) % 12
    if interval not in steps:
        return ""
    degree = steps.index(interval)
    notes = [steps[(degree + 2 * k) % 7] for k in range(size)]
    return _BY_INTERVALS.get(frozenset((n - interval) % 12 for n in notes), "")


# Colours of a chord on its own root, best first, then the chords that may stand in for it.
_COLOURS = ("maj7", "7", "m7", "m7b5", "add9", "madd9", "sus2", "6", "m6", "sus4", "7sus4",
            "maj9", "9", "m9", "", "m", "dim", "dim7")
_STAND_INS = ("m", "", "dim", "m7", "7", "maj7", "m7b5", "dim7")
# Stand-ins a third below come first (vi for I), then a third above (iii for I).
_THIRDS = {9: 0, 8: 1, 4: 2, 3: 3}


def alternatives(chord: Chord, key: Key, limit: int = 8) -> list[Chord]:
    """Chords to play instead of ``chord`` that keep to ``key``, to change the feel.

    Every note of an alternative is in the key's scale or in the chord itself, and it
    shares at least two notes with the chord. First come colours on the same root (a
    seventh, add9, sus2, a sixth...), then an inversion (or, for a slash chord, its root
    position), then chords on other roots that share the most notes, a third below first.
    """
    return list(_alternatives(chord, key, limit))


@functools.lru_cache(maxsize=4096)
def _alternatives(chord: Chord, key: Key, limit: int) -> tuple[Chord, ...]:
    allowed = scale(key) | chord.pitch_classes
    core = frozenset((chord.root + i) % 12 for i in chord.intervals)

    def fits(candidate: Chord) -> bool:
        pcs = candidate.pitch_classes
        return pcs <= allowed and pcs != core and len(pcs & core) >= 2

    colours = [c for q in _COLOURS if fits(c := Chord(chord.root, q))][:4]
    if chord.bass is not None:
        turned = [Chord(chord.root, chord.quality, None, None, chord.tones)]
    else:
        third = next((t for t in (4, 3, 7, 5, 2) if t in chord.intervals), None)
        bass = None if third is None else (chord.root + third) % 12
        turned = [] if bass is None else [Chord(chord.root, chord.quality, bass, None, chord.tones)]
    others = [
        c for root in range(12) if root != chord.root and root in allowed
        for q in _STAND_INS if fits(c := Chord(root, q))
    ]
    others.sort(key=lambda c: (
        -len(c.pitch_classes & core),
        len(c.intervals) > 3,
        _THIRDS.get((c.root - chord.root) % 12, 4),
        _STAND_INS.index(c.quality),
    ))
    chosen = colours + turned
    for candidate in others:
        if len(chosen) >= limit:
            break
        if not any(_sounds_alike(candidate, c) for c in chosen):
            chosen.append(candidate)
    return tuple(chosen)


_SYMMETRIC = ("dim7", "aug")  # any of their notes may be called the root


def _sounds_alike(a: Chord, b: Chord) -> bool:
    """Same notes, and the same lowest one, or both a symmetric chord: G#dim7 and Ddim7."""
    if a.pitch_classes != b.pitch_classes:
        return False
    if a.quality in _SYMMETRIC and b.quality in _SYMMETRIC:
        return True
    low = (a.bass if a.bass is not None else a.root, b.bass if b.bass is not None else b.root)
    return low[0] == low[1]


# Keys whose chords are open shapes: by their tonic chord for major and minor, by their notes
# (those of C or G major) for the other modes.
_OPEN = {"ionian": {0, 2, 4, 7, 9}, "aeolian": {2, 4, 9}}
_OPEN_NOTES = {0, 7}
MAX_CAPO = 5


def _open(key: Key) -> bool:
    if key.mode in _OPEN:
        return key.tonic in _OPEN[key.mode]
    relative = (key.tonic - SCALES["ionian"][MODES.index(key.mode)]) % 12
    return relative in _OPEN_NOTES


def capo_hints(key: Key, limit: int = 2, *, capo: int = 0) -> list[tuple[int, Key]]:
    """Where to put a capo to play chords in ``key`` with open shapes: (fret, shapes' key).

    ``key`` is the key of the chords as played with the capo on fret ``capo`` (the sheet's
    own, 0 for none), so the song sounds ``capo`` semitones higher. The fret is where the capo
    goes then, 0 for no capo: up to MAX_CAPO above the sheet's, or lower, down to none (G
    shapes with capo 2, transposed down two, play with no capo). Nothing when the chords are
    open shapes already; otherwise up to ``limit`` frets, lowest first.
    """
    return list(_capo_hints(key, limit, capo))


@functools.cache
def _capo_hints(key: Key, limit: int, capo: int) -> tuple[tuple[int, Key], ...]:
    if _open(key):
        return ()
    sounds = sounding(key, capo).tonic
    hints = [(fret, Key((sounds - fret) % 12, key.mode))
             for fret in range(capo + MAX_CAPO + 1) if fret != capo]
    return tuple((fret, shapes) for fret, shapes in hints if _open(shapes))[:limit]


def sounding(shapes: Key, capo: int) -> Key:
    """The key a song sounds in, played in ``shapes`` with the capo on fret ``capo`` (0 for none):
    E minor shapes with capo 2 sound in F# minor."""
    return Key((shapes.tonic + capo) % 12, shapes.mode)


def shapes_key(named: Key, capo: int, played: list[Chord]) -> Key:
    """The key of the shapes played, from the key a tab names for a sheet with the capo on fret
    ``capo``, whose chords are ``played``.

    Tabs name either key: most the shapes' (Em for a song played in Em shapes with capo 2), some
    the one the song sounds in (UG's F# for a song played in C shapes with capo 6). The chords
    tell which: when their key has the notes of the named key lowered by the capo, the tab named
    the sound. Otherwise, and with no capo or no chords to go by, the named key is the shapes'.
    """
    if capo % 12 == 0:
        return named
    lowered = Key((named.tonic - capo) % 12, named.mode)
    found = estimate_key(played)
    return lowered if found is not None and scale(found) == scale(lowered) else named
