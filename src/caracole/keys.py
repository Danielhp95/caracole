"""A song's musical key: read from its tab, or estimated from its chords.

A key is written as its tonic, a letter with ``#`` or ``b``, followed by
" minor" for a minor key: "A minor", "C", "F#", "Bb minor". The spelling is
the source's ("Gb" stays "Gb"); ``same_key`` compares keys by sound. It is the
key of the chords as the sheet writes them, the shapes you play: with a capo,
the song sounds higher, as ChordPro's ``{key}`` has it.

``estimate_key`` finds the key of a chord progression, offline and with the
standard library: every chord's notes (root, third, fifth and, at half weight,
a seventh) make a histogram of the 12 pitch classes, weighted by how often or
how long each chord sounds. Its correlation with the Krumhansl–Kessler profile
of each of the 24 keys says which scale the song lives in (Krumhansl, 1990).
That alone can't tell a key from its relative minor (A minor and C major share
their notes), so the tonic chord decides: how much of the song it holds, and
whether the song starts and ends on it. Chords that fit no key well (a
correlation under ``MIN_FIT``) give no estimate.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

from caracole.chordpro import is_chord_line, normalize_chord

_LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SOLFEGE = {"do": "C", "re": "D", "mi": "E", "fa": "F", "sol": "G", "la": "A", "si": "B"}
_ACCIDENTALS = {"#": "#", "♯": "#", "b": "b", "♭": "b", "": ""}
_SHIFT = {"#": 1, "b": -1, "": 0}

# A key at the start of a text: "Am", "A minor", "F#m", "La menor", "Sib", "Do mayor".
# A letter tonic is a capital; solfège names come in any case.
_KEY_HEAD = re.compile(
    r"(?P<root>[A-G]|(?i:sol|do|re|mi|fa|la|si))(?P<acc>[#♯b♭])?"
    r"(?:\s*(?P<word>(?i:minor|menor|major|mayor|min|maj))|(?P<m>m))?"
    r"(?![\w#♯♭+/])"
)
# What introduces a key in a sheet's notes: "Key: G", "Key of Bb", "Tono: La menor".
_KEY_LABEL = re.compile(
    r"(?<!\w)(?i:key\s*(?:of\s+|[:=–—-]\s*)|(?:tono(?:\s+original)?|tonalidad|tonality)\s*[:=–—-]\s*)"
)
_DIRECTIVE = re.compile(r"\s*\{\s*(?i:key)\s*:\s*(.*?)\s*\}\s*")
_CHORD_TAG = re.compile(r"\[ch\](.*?)\[/ch\]")

# A chord name: a root, a quality and an optional bass ("F#m7b5", "C/G", "Fadd9").
_CHORD = re.compile(r"\s*([A-G])([#♯b♭]?)([^/\s]*)(?:/\S*)?\s*")
_QUALITY = re.compile(r"(?:maj|min|dim|aug|sus|add|alt|m|M|°|o|ø|Δ|\+|-|\d|[#b♯♭()^,.])*")
_ADDED = re.compile(r"add\d+")
_EXTENDED = re.compile(r"7|9|11|13")

# Krumhansl and Kessler's probe-tone ratings, from the tonic up by semitones.
_PROFILES = {
    False: (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88),
    True: (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17),
}
MIN_FIT = 0.6  # the correlation below which the chords fit no key
TONIC_SHARE = 0.3  # the weight of the tonic chord's share of the song
EDGE = 0.25  # the weight of starting, and of ending, on the tonic chord
# Spellings for a tonic the chords never spell themselves.
_MAJOR_NAMES = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
_MINOR_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B")


def parse_key(text: str) -> str | None:
    """A key as caracole writes it, from the ways tabs write one; None if ``text`` is no key.

    "Am", "A min" and "La menor" are "A minor"; "C", "C major" and "Do" are "C";
    "E♭" is "Eb". A chord that isn't a triad ("Am7") is no key.
    """
    m = _KEY_HEAD.fullmatch(text.strip())
    return _canonical(m) if m else None


def key_name(key: str) -> str:
    """The key with its mode spelled out, for people: "C major", "A minor"."""
    return key if key.endswith(" minor") else f"{key} major"


def same_key(a: str, b: str) -> bool:
    """Whether two keys sound the same: "F# minor" is "Gb minor"."""
    pa, pb = _pitch(a), _pitch(b)
    return pa is not None and pa == pb


def key_in_text(sheet: str) -> str | None:
    """The key a sheet states itself, in UG markup or plain text; None if it states none.

    A ChordPro ``{key: …}`` directive anywhere, or a note before the first chord
    line: "Key: G", "Key of Bb", "Tono: La menor", "Tonalidad: Re". Later notes
    are left alone, as they often describe a key change.
    """
    for raw in sheet.splitlines():
        directive = _DIRECTIVE.fullmatch(raw)
        if directive:
            found = parse_key(directive.group(1))
            if found:
                return found
    for raw in sheet.splitlines():
        if is_chord_line(raw):
            return None
        line = _CHORD_TAG.sub(lambda m: m.group(1), raw)
        for label in _KEY_LABEL.finditer(line):
            m = _KEY_HEAD.match(line, label.end())
            if m:
                return _canonical(m)
    return None


def chords_in_sheet(markup: str) -> list[str]:
    """The chords of a sheet in UG markup (``[ch]X[/ch]``), in order, with letter names."""
    names = (m.group(1).strip() for m in _CHORD_TAG.finditer(markup))
    return [normalize_chord(name) for name in names if name]


def estimate_key(chords: Iterable[str | tuple[str, float]]) -> str | None:
    """The key a progression is most likely in, or None (see the module's notes).

    Each item is a chord name, counted once, or a chord name and how long it
    sounds. Names that aren't chords ("N.C.", "x2") are skipped.
    """
    played: list[tuple[int, str | None, float, str]] = []  # root, triad, weight, spelling
    histogram = [0.0] * 12
    for item in chords:
        name, weight = (item, 1.0) if isinstance(item, str) else item
        chord = _chord(name)
        if chord is None or weight <= 0:
            continue
        root, spelling, triad, tones = chord
        played.append((root, triad, weight, spelling))
        for interval, share in tones:
            histogram[(root + interval) % 12] += share * weight
    if not played:
        return None
    total = sum(w for _, _, w, _ in played)
    (first, first_triad, _, _), (last, last_triad, _, _) = played[0], played[-1]
    best = (-math.inf, 0.0, 0, False)  # score, fit, tonic, minor
    for minor in (False, True):
        profile = _PROFILES[minor]
        for tonic in range(12):
            fit = _correlation(histogram, [profile[(pc - tonic) % 12] for pc in range(12)])
            share = sum(w * _tonic_chord(r, t, tonic, minor) for r, t, w, _ in played) / total
            starts = _tonic_chord(first, first_triad, tonic, minor)
            ends = _tonic_chord(last, last_triad, tonic, minor)
            score = fit + TONIC_SHARE * share + EDGE * (starts + ends)
            if score > best[0]:
                best = (score, fit, tonic, minor)
    _, fit, tonic, minor = best
    if fit < MIN_FIT:
        return None
    spellings = Counter(s for r, _, _, s in played if r == tonic)  # the chords' own spelling wins
    if spellings:
        name = spellings.most_common(1)[0][0]
    else:
        name = (_MINOR_NAMES if minor else _MAJOR_NAMES)[tonic]
    return f"{name} minor" if minor else name


# --- helpers -----------------------------------------------------------------------------


def _canonical(m: re.Match[str]) -> str:
    root = m.group("root")
    letter = _SOLFEGE.get(root.lower(), root)
    tonic = letter + _ACCIDENTALS[m.group("acc") or ""]
    word = (m.group("word") or "").lower()
    minor = bool(m.group("m")) or word in ("minor", "menor", "min")
    return f"{tonic} minor" if minor else tonic


def _pitch(key: str) -> tuple[int, bool] | None:
    """The tonic's pitch class (C is 0) and whether the key is minor."""
    canonical = parse_key(key)
    if canonical is None:
        return None
    tonic = canonical.removesuffix(" minor")
    return (_LETTERS[tonic[0]] + _SHIFT[tonic[1:]]) % 12, tonic != canonical


def _tonic_chord(root: int, triad: str | None, tonic: int, minor: bool) -> float:
    """How much a chord is the key's tonic chord: 1 for its triad, 0.5 for a power or sus chord on it."""
    if root != tonic:
        return 0.0
    return 1.0 if triad == ("minor" if minor else "major") else 0.5 if triad == "open" else 0.0


def _chord(name: str) -> tuple[int, str, str | None, list[tuple[int, float]]] | None:
    """A chord's root (pitch class) and its spelling, its triad, and its notes with their weights.

    The triad is "major", "minor", "open" (a power chord or a sus chord, with no
    third) or None (diminished, augmented). A bass note under a slash is left out.
    """
    m = _CHORD.fullmatch(normalize_chord(name.strip()))
    if not m or not _QUALITY.fullmatch(m.group(3)):
        return None
    letter, accidental, quality = m.group(1), _ACCIDENTALS[m.group(2)], m.group(3)
    root = (_LETTERS[letter] + _SHIFT[accidental]) % 12
    q = quality.lower()
    triad: str | None
    if q.startswith(("m7b5", "m7-5", "ø")):
        triad, third, fifth = None, 3, 6
    elif quality.startswith(("maj", "M", "Δ")):
        triad, third, fifth = "major", 4, 7
    elif q.startswith(("min", "m", "-")):
        triad, third, fifth = "minor", 3, 7
    elif q.startswith(("dim", "°", "o")):
        triad, third, fifth = None, 3, 6
    elif q.startswith(("aug", "+")):
        triad, third, fifth = None, 4, 8
    elif q.startswith("sus2"):
        triad, third, fifth = "open", 2, 7
    elif q.startswith("sus"):
        triad, third, fifth = "open", 5, 7
    elif q.startswith("5"):
        triad, third, fifth = "open", None, 7
    else:
        triad, third, fifth = "major", 4, 7
    tones: list[tuple[int, float]] = [(0, 1.0), (fifth, 1.0)]
    if third is not None:
        tones.append((third, 1.0))
    extended = _ADDED.sub("", quality)
    if "maj7" in extended.lower() or "M7" in extended or "Δ" in extended:
        tones.append((11, 0.5))
    elif q.startswith(("dim", "°", "o")) and "7" in extended:
        tones.append((9, 0.5))
    elif _EXTENDED.search(extended):
        tones.append((10, 0.5))
    return root, letter + accidental, triad, tones


def _correlation(a: list[float], b: list[float]) -> float:
    """Pearson's correlation of two equal-length lists; 0 when either is flat."""
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0
