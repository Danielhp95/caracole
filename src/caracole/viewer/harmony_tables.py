"""What harmony.py says of a sheet, as the tables a viewer's data carries (page.py ``_data``), for viewer.js
to look up: it computes no theory of its own.

For each mode of the key's tonic (the chords as ``data.mapped[mode]`` has them), by **reading**: the reading
of chord ``i`` is ``i`` itself (the one most of its places on the sheet have), and a chord read otherwise
somewhere (D going to G is V/V, going to C a borrowed II) gets one more, after the chords, which
``places[mode]`` names for that place (by its index among the sheet's chords in the page's order, the
script's ``#sheet .c``):

- ``numerals[mode][r]``: ``[text, accidental, roman, quality, extension, bass, of]``
  (``harmony.Numeral``), null for a chord caracole can't read;
- ``families[mode][r]``: "home", "away", "pull", or null for a chord from outside the key;
- ``relations[mode][r]``: ``harmony.Relation.kind``;
- ``explains[mode][r]``: the tooltip's line (``harmony.explain``), as a **text**, below;
- ``altNumerals[mode][i]``: for each chord ``data.alts[mode][i]`` offers instead, its numeral's text after its
  ``role`` ("hImaj7": home; "b♭VII": borrowed);
- ``solo[mode][i]`` and ``altSolo[mode][i]``: the scale for a solo over the chord (``harmony.solo_scale``),
  by its index in ``scaleWords``: ``scales`` gives it by the chord's root as the page names it, a space and
  that word ("D Dorian"), as harmony.py names it and its notes ("D Dorian|D E F G A B C"; a root may be
  spelled otherwise there: "C# Locrian" for the page's Db);
- ``keyScale[mode]``, ``pentatonic[mode]``: the key's scale and its pentatonic box, as semitones above the
  tonic (``harmony.key_scale``, ``harmony.pentatonic``), and ``pentatonicName[mode]``; ``tuning``, the
  pitch class of each open string, low E first (``voicings.TUNING``), for the key's neck;
- ``progressions[mode]``: each section's ``[section, numerals, repeats, name, ending, key, chords, variations,
  contains]`` (``harmony.progressions``; ``section`` counts the sheet's ``section.sec`` elements, ``key`` is
  ``harmony.progression_key``, ``chords`` the chord played for each numeral of one cycle, by index, where the
  section first plays it whole, or null where they can't be told, ``variations`` the passes that play the
  cycle otherwise, and ``contains`` each progression of the catalogue played within the section, but its
  ``name``, as ``[name, times, key]``, its key the one ``#prog=`` finds it by);

and, for every mode alike, ``tones``: each chord the page can name (base or alternative, on every
transposition) by its name as viewer.js writes it (``nameOf``), as "C E G Bb|R 3 5 ♭7"
(``harmony.chord_tones``).

A **text** names notes, so it is written for every transposition of the key: a string where it names none
(the same in every key); a list of strings and pitch classes, a pitch class (in the key as written) to be
named as the page names it in the key shown, when that gives every transposition's text; else
``{"by": [12 texts]}``, the text on each transposition (0 to 11 semitones up). Every one is checked against
harmony.py's answer on all twelve.

Numerals don't change with the transposition or the capo (a I is a I in every key): one table per mode.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from caracole.viewer import harmony
from caracole.viewer.harmony import _goes_to
from caracole.viewer.theory import MODES, Chord, Key, note_pc, spelling
from caracole.viewer.voicings import TUNING

SHIFTS = range(12)
_NOTE = re.compile(r"(?<![A-Za-z])([A-G])([#b♯♭]?)")
# What may follow a note's name in a text: no letter, or a chord's suffix ("Am", "Bbmaj7", "Dsus4").
_AFTER_NOTE = re.compile(r"(?![a-z])|m|sus|add|aug|dim")


def shifted(chord: Chord | None, s: int) -> Chord | None:
    """``chord`` ``s`` semitones up."""
    if chord is None or s == 0:
        return chord
    return replace(chord, root=(chord.root + s) % 12, bass=None if chord.bass is None else (chord.bass + s) % 12)


def page_name(chord: Chord, names: Sequence[str], s: int = 0) -> str:
    """The chord ``s`` semitones up as viewer.js's ``nameOf`` names it, with ``names`` (``theory.spelling``
    of the key shown)."""
    bass = "" if chord.bass is None else "/" + names[(chord.bass + s) % 12]
    return names[(chord.root + s) % 12] + chord.suffix + bass


def _parts(text: str) -> list[str | int]:
    """``text`` cut at each note it names: its other words, and each note's pitch class."""
    out: list[str | int] = []
    at = 0
    for m in _NOTE.finditer(text):
        letter, accidental = m.groups()
        end = m.end()
        if accidental and not _AFTER_NOTE.match(text, end):  # "Bb" in "Bbass": the letter alone
            accidental, end = "", m.start() + 1
        if not _AFTER_NOTE.match(text, end):  # a word: "Dorian"
            continue
        out += [text[at:m.start()], note_pc(letter, accidental)]
        at = end
    out.append(text[at:])
    return [p for p in out if p != ""]


def fill(parts: Sequence[str | int], names: Sequence[str], s: int) -> str:
    """A text's parts on the transposition ``s``, each pitch class named by ``names``, as viewer.js does."""
    return "".join(p if isinstance(p, str) else names[(p + s) % 12] for p in parts)


def text_of(texts: Sequence[str], key: Key) -> Any:
    """The texts of one line on every transposition (``texts[s]``, in ``key`` ``s`` semitones up) as a
    **text** (the module's docstring)."""
    if all(t == texts[0] for t in texts):
        return texts[0]
    parts = _parts(texts[0])
    if all(fill(parts, spelling(Key((key.tonic + s) % 12, key.mode)), s) == texts[s] for s in SHIFTS):
        return parts
    return {"by": list(texts)}


def role(chord: Chord, key: Key) -> str:
    """A chord's role in one letter: its family's first ("h", "a", "p"), else its relation's ("b", "s", "l",
    "o")."""
    return (harmony.family(chord, key) or harmony.relation(chord, key).kind)[0]


def _numeral(n: harmony.Numeral) -> list[Any]:
    return [n.text, n.accidental, n.roman, n.quality, n.extension, n.bass, n.of]


def tables(chords: Sequence[Chord | None], key: Key | None, places: Sequence[tuple[int, int]],
           mapped: dict[str, Sequence[Chord | None]], alts: dict[str, Sequence[Sequence[Chord]]]) -> dict[str, Any]:
    """The tables for a sheet whose chords are ``chords`` (by index) and whose places are ``places``, each
    ``(chord index, section)`` in the page's order (section -1 for the notes before the song, which are no
    part of its progressions), in ``key``; ``mapped`` and ``alts`` are each mode's chords and alternatives,
    as the page's data has them. With no key, ``tones`` alone."""
    tones: dict[str, str] = {}

    def add_tones(chord: Chord | None, mode_key: Key | None) -> None:
        if chord is None:
            return
        for s in SHIFTS:
            shown = None if mode_key is None else Key((mode_key.tonic + s) % 12, mode_key.mode)
            name = page_name(chord, spelling(shown), s)
            if name not in tones:
                found = harmony.chord_tones(shifted(chord, s), shown)
                tones[name] = " ".join(n for n, _ in found) + "|" + " ".join(t for _, t in found)

    out: dict[str, Any] = {"tones": tones}
    if key is None:
        for chord in chords:
            add_tones(chord, None)
        return out
    out.update(numerals={}, families={}, relations={}, explains={}, places={}, altNumerals={},
               solo={}, altSolo={}, keyScale={}, pentatonic={}, pentatonicName={}, progressions={})
    words: list[str] = []
    scales: dict[str, str] = {}
    sections = sorted({n for _, n in places if n >= 0})

    def solo(chord: Chord, mode_key: Key) -> int:
        word = harmony.solo_scale(chord, mode_key)[0].split(" ", 1)[1]
        if word not in words:
            words.append(word)
        for s in SHIFTS:
            shown = Key((mode_key.tonic + s) % 12, mode_key.mode)
            full = spelling(shown)[(chord.root + s) % 12] + " " + word
            if full not in scales:
                name, notes = harmony.solo_scale(shifted(chord, s), shown)
                scales[full] = name + "|" + " ".join(notes)
        return words.index(word)

    for mode in MODES:
        mode_key = Key(key.tonic, mode)
        here = mapped[mode]
        played = [(k, i, n) for k, (i, n) in enumerate(places) if n >= 0 and here[i] is not None]
        after = dict(zip((k for k, _, _ in played), _goes_to([here[i] for _, i, _ in played]), strict=True))
        # Each chord read as most of its places read it (the first of those, in a tie), or with no chord after it.
        heard: dict[int, Counter] = {}
        goes_for: dict[tuple[int, str], Chord | None] = {}
        for k, i, _ in played:
            line = harmony.explain(here[i], mode_key, after[k])
            heard.setdefault(i, Counter())[line] += 1
            goes_for.setdefault((i, line), after[k])
        readings: list[tuple[Chord | None, Chord | None]] = [
            (chord, goes_for[(i, heard[i].most_common(1)[0][0])] if i in heard else None)
            for i, chord in enumerate(here)]
        lines = [None if c is None else harmony.explain(c, mode_key, g) for c, g in readings]
        by_place: dict[int, int] = {}
        for k, i, _ in played:
            line = harmony.explain(here[i], mode_key, after[k])
            if line != lines[i]:
                if line not in lines[len(here):]:
                    readings.append((here[i], after[k]))
                    lines.append(line)
                by_place[k] = len(here) + lines[len(here):].index(line)
        out["numerals"][mode] = [None if c is None else _numeral(harmony.numeral(c, mode_key, g)) for c, g in readings]
        out["families"][mode] = [None if c is None else harmony.family(c, mode_key) for c, _ in readings]
        out["relations"][mode] = [None if c is None else harmony.relation(c, mode_key, g).kind for c, g in readings]
        out["explains"][mode] = [
            None if c is None else text_of([harmony.explain(shifted(c, s), Key((key.tonic + s) % 12, mode),
                                                            shifted(g, s)) for s in SHIFTS], mode_key)
            for c, g in readings]
        out["places"][mode] = {str(k): r for k, r in by_place.items()}
        out["altNumerals"][mode] = [[role(a, mode_key) + harmony.numeral(a, mode_key).text for a in options]
                                    for options in alts[mode]]
        out["solo"][mode] = [None if c is None else solo(c, mode_key) for c in here]
        out["altSolo"][mode] = [[solo(a, mode_key) for a in options] for options in alts[mode]]
        for c in here:
            add_tones(c, mode_key)
        for options in alts[mode]:
            for a in options:
                add_tones(a, mode_key)
        out["keyScale"][mode] = [(pc - key.tonic) % 12 for pc in harmony.key_scale(mode_key)]
        box = [(pc - key.tonic) % 12 for pc in harmony.pentatonic(mode_key)]
        out["pentatonic"][mode] = box
        out["pentatonicName"][mode] = "major pentatonic" if 4 in box else "minor pentatonic"
        out["progressions"][mode] = _progressions(sections, played, here, after, mode_key)
    out["tuning"] = [note % 12 for note in TUNING]
    out["scaleWords"] = words
    out["scales"] = scales
    return out


def _progressions(sections: list[int], played: list[tuple[int, int, int]], here: Sequence[Chord | None],
                  after: dict[int, Chord | None], key: Key) -> list[list[Any]]:
    """Each section's progression (the module's docstring), its chords read as ``tables`` reads them."""
    chords_of: dict[int, list[Chord | None]] = {n: [] for n in sections}
    texts_of: dict[int, list[tuple[int, str]]] = {n: [] for n in sections}
    for k, i, n in played:
        chords_of[n].append(here[i])
        texts_of[n].append((i, harmony.numeral(here[i], key, after[k]).text))
    found = []
    for name, p in harmony.progressions([(str(n), chords_of[n]) for n in sections], key):
        n = int(name)
        texts = texts_of[n]
        held = [x for j, x in enumerate(texts) if j == 0 or x[1] != texts[j - 1][1]]
        words = [t for _, t in held]
        k = len(p.numerals)
        # The chords of the cycle where the section first plays it whole (after a pass that varies it, maybe).
        at = next((j for j in range(len(words) - k + 1) if words[j:j + k] == list(p.numerals)), None)
        indexes = None if at is None else [i for i, _ in held[at:at + k]]
        found.append([n, list(p.numerals), p.repeats, p.name, p.ending, harmony.progression_key(p.numerals),
                      indexes, p.variations, [[c.name, c.times, c.key] for c in p.contains]])
    return found
