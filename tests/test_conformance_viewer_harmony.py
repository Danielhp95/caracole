"""viewer/harmony.py for the phone: its constants as data, and what it answers, for :viewer's viewer.harmony.

The logic is Kotlin's (viewer.harmony.Harmony); everything harmony.py states as data is written here, from the module
itself, so a change to a table, a word or a pattern regenerates what the phone reads and the phone follows it. This
is the chord half (lane harmony): numerals, relations, families, the explanations and their tooltip lines, the
glossary, a chord's notes, the scale for a solo over it, the key's scale and its pentatonic box, and which chord each
one goes to (``_goes_to``). Lane harmony-progressions adds the progressions, ``progression_key``, ``name_of``,
``read_typed`` and harmony_tables.py.

The data, ``tests/conformance/data/caracole/viewer/harmony.json`` (caracole/viewer/harmony.json on the phone's
classpath, ``ViewerData.table("harmony")``; ``viewer_corpus.data_json``), each member a constant of harmony.py under
its own name, a dict's members in its order:

- ``ROMANS``, ``_FAMILIES``, ``_BASS_DEGREES``: arrays;
- ``_SHAPES``: ``{quality: [lower case, sign, extension]}``, a numeral's shape for each quality of theory.QUALITIES;
- ``_BORROWS``: ``{mode: [mode, …]}``, the modes a major and a minor key borrow from, first the one asked first;
- ``_MODE_WORDS``, ``_IN_OCTAVE``, ``_EXTENSION_WORDS``, ``_SYMBOL_MEANINGS``: objects as they are;
- ``_OTHER_SCALES``: ``{name: [step, …]}``, the scales a solo may take besides the modes;
- ``patterns``: ``_TOKENS`` as Python writes it (``.pattern``, no flag), which core.py.PyRegex reads as Python does.

What harmony.py says in a sentence (an explanation's "the V of …", a glossary line's meaning, a scale's name by a
chord's quality, an interval's name) is its code, and Kotlin's: every word of it is compared below.

The vectors (``helpers.corpus.jsonl``), ``vectors/viewer/harmony_chords.jsonl``. A chord is ``[root, quality, bass,
shown, tones]`` with its trailing nulls left out (``tones`` its intervals sorted, for a chord outside QUALITIES); a
key ``[tonic, mode]``; a numeral ``[text, accidental, roman, quality, extension, bass, of]`` (``Numeral``, its text
first); a relation ``[kind, source, target]``; a chord's notes ``[[note, interval], …]`` (``chord_tones``); a scale
``[name, [note, …]]`` (``solo_scale``). Each record is one of:

- ``chord_in_keys(chord, keys, nexts)``, a chord batched with the keys and the chords it may go to: ``{"alone":
  chord_tones(chord, None), "in": [[family, chord_tones, solo_scale, [[numeral, relation, explain] for each of
  nexts]] for each of keys]}``, each of ``nexts`` a chord or null (no chord after it). The chords: each quality of
  theory.QUALITIES on a seeded root, in the keys of every tonic in a major and a minor mode and ``OTHER_TONICS``
  seeded tonic of each other mode (so every degree of the two, and one of each other, in their spellings); then,
  among ``viewer_corpus.chord_names()`` (read loosely, as page.py reads a sheet's), a slash chord of each bass above
  its root, a note of it or not, its quality one of QUALITIES or not, and ``OUTSIDE`` seeded chords of a quality
  outside QUALITIES (a suffix theory.py reads into tones, or one it can't read at all); then ``FIXED_OUTSIDE``, a chord
  for each way ``_shape`` reads a quality outside QUALITIES (dim, aug or ``+``, m, another, and a suffix it can't
  read), whatever the corpus holds; each in ``SHAPE_KEYS`` seeded keys. The chords it may go to are those a reading turns on (``_read``): none; for a dominant the triad a fifth
  below, and for a dominant seventh the dominant seventh there too; for a leading-tone chord the minor triad a half
  step above; and for one chord in ``OTHER_EVERY`` a seeded chord of another root.
- ``in_sequence(names, key)``: the chords a sheet plays (``names``, read as page.py reads them,
  ``parse_chord(name, strict=False)`` with those it reads as none left out), in ``key``: ``{"goes_to":
  _goes_to(played), "numerals": [numeral(c, key, g).text for each chord c and the one g it goes to], "glossary":
  glossary(played, key)}``, each glossary line ``[symbol, meaning, example]``. For every progression of
  ``viewer_corpus.progressions()`` in its key, every sheet of ``viewer_corpus.sheets()`` but the catalogue's (whose
  chords are those progressions) and ``SHEETS_OF_MODES`` seeded ones of the modes', each in the key it names
  (``theory.named_key``), else the one its chords are in (``estimate_key``), else a seeded one, and a fixture's and
  a ``qualities-`` sheet's in a seeded key of another mode too; and no chord at all.
- ``tooltips(chord, key, next)``: the tooltip's line on every transposition, as harmony_tables.py writes a text:
  ``[explain(chord s semitones up, key s up, next s up) for s in 0..11]``, for ``TOOLTIPS_EACH`` seeded readings of
  each quality's chord of the first kind of record (a key and a chord it may go to).
- ``key_scales()``: ``[[tonic, mode, key_scale(key), pentatonic(key)] for every key of viewer_corpus.keys()]``.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harmony.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import functools
import json
import random
import re
from dataclasses import replace

from caracole.viewer import harmony, theory
from caracole.viewer.theory import MODES, QUALITIES, Chord, Key
from helpers import viewer_corpus
from helpers.corpus import check, jsonl

MADE_BY = "tests/test_conformance_viewer_harmony.py"
HELPER = "test_conformance_viewer_harmony."
SEED = viewer_corpus.SEED + 200
PATTERNS = ("_TOKENS",)
OTHER_TONICS = 1
SHAPE_KEYS = 4
OUTSIDE = 40
OTHER_EVERY = 4
SHEETS_OF_MODES = 14
TOOLTIPS_EACH = 2
# A chord for each branch of _shape outside QUALITIES (test_every_way_shape_reads_a_quality_is_in_the_vectors).
FIXED_OUTSIDE = ("Caug9", "C+maj7", "Caug7#9", "Cdim9", "Cdim7b9", "Cm7b9", "Cmmaj9", "Cmaj7#11", "C7#9b13", "Cfoo",
                 "Cmfoo")


# --- the data ------------------------------------------------------------------------------------------------------


def _pattern(p: re.Pattern[str]) -> str:
    assert p.flags & ~re.UNICODE == 0, f"{p.pattern!r}: a flag the phone doesn't read"
    return p.pattern


def constants() -> dict:
    return {
        "ROMANS": list(harmony.ROMANS),
        "_SHAPES": {quality: [lower, sign, extension] for quality, (lower, sign, extension) in harmony._SHAPES.items()},
        "_BORROWS": {mode: list(modes) for mode, modes in harmony._BORROWS.items()},
        "_MODE_WORDS": dict(harmony._MODE_WORDS),
        "_FAMILIES": list(harmony._FAMILIES),
        "_BASS_DEGREES": list(harmony._BASS_DEGREES),
        "_IN_OCTAVE": dict(harmony._IN_OCTAVE),
        "_EXTENSION_WORDS": dict(harmony._EXTENSION_WORDS),
        "_SYMBOL_MEANINGS": dict(harmony._SYMBOL_MEANINGS),
        "_OTHER_SCALES": {name: list(steps) for name, steps in harmony._OTHER_SCALES.items()},
        "patterns": {name: _pattern(getattr(harmony, name)) for name in PATTERNS},
    }


@functools.cache
def harmony_json() -> str:
    return viewer_corpus.data_json(constants())


def test_harmony_json_is_harmony_pys_constants():
    check(viewer_corpus.VIEWER_DATA / "harmony.json", harmony_json())


def test_the_data_reads_back_as_harmony_holds_it():
    data = json.loads(harmony_json())
    assert tuple(data["ROMANS"]) == harmony.ROMANS
    assert {q: tuple(v) for q, v in data["_SHAPES"].items()} == harmony._SHAPES
    assert list(data["_SHAPES"]) == list(harmony._SHAPES)
    assert set(data["_SHAPES"]) == set(QUALITIES)
    assert {m: tuple(v) for m, v in data["_BORROWS"].items()} == harmony._BORROWS
    assert tuple(data["_FAMILIES"]) == harmony._FAMILIES
    assert tuple(data["_BASS_DEGREES"]) == harmony._BASS_DEGREES
    assert {n: tuple(v) for n, v in data["_OTHER_SCALES"].items()} == harmony._OTHER_SCALES
    assert all(r.isascii() for r in data["ROMANS"]), "Chords.kt's isLower reads a roman's ASCII letters"
    for name, pattern in data["patterns"].items():
        assert re.compile(pattern) == getattr(harmony, name)


# --- the inputs ----------------------------------------------------------------------------------------------------


def chord_row(chord: Chord | None) -> list | None:
    if chord is None:
        return None
    row = [chord.root, chord.quality, chord.bass, chord.shown, None if chord.tones is None else sorted(chord.tones)]
    while row[-1] is None:
        row.pop()
    return row


def key_row(key: Key | None) -> list | None:
    return None if key is None else [key.tonic, key.mode]


def numeral_row(n: harmony.Numeral) -> list:
    return [n.text, n.accidental, n.roman, n.quality, n.extension, n.bass, n.of]


def relation_row(r: harmony.Relation) -> list:
    return [r.kind, r.source, r.target]


def tones_row(tones: list[tuple[str, str]]) -> list:
    return [list(t) for t in tones]


def scale_row(scale: tuple[str, tuple[str, ...]]) -> list:
    return [scale[0], list(scale[1])]


def shifted(chord: Chord | None, s: int) -> Chord | None:
    if chord is None or s == 0:
        return chord
    return replace(chord, root=(chord.root + s) % 12, bass=None if chord.bass is None else (chord.bass + s) % 12)


def nexts_for(chord: Chord, rng: random.Random, n: int) -> list[Chord | None]:
    """The chords ``chord`` may go to that its reading turns on (the module's docstring)."""
    out: list[Chord | None] = [None]
    fifth_below = (chord.root + 5) % 12
    if harmony._dominant(chord):
        out.append(Chord(fifth_below, ""))
        if harmony._dominant_seventh(chord):
            out.append(Chord(fifth_below, "7"))
    if harmony._leading(chord):
        out.append(Chord((chord.root + 1) % 12, "m"))
    if n % OTHER_EVERY == 0:
        roots = [r for r in range(12) if r not in (chord.root, fifth_below, (chord.root + 1) % 12)]
        out.append(Chord(rng.choice(roots), rng.choice(("", "m", "7", "dim"))))
    return out


def _shape(chord: Chord) -> tuple:
    """A chord of the second kind's shape: a slash chord's by its bass above its root, whether that is a note of it
    and whether its quality is one of QUALITIES; another by its quality."""
    if chord.bass is None:
        return ("quality", chord.quality)
    bass = (chord.bass - chord.root) % 12
    return ("bass", bass, bass in chord.intervals, chord.tones is None)


@functools.cache
def _chords() -> tuple[tuple[Chord, tuple[Key, ...], tuple[Chord | None, ...]], ...]:
    """Each chord of the first kind of record, its keys and the chords it may go to."""
    rng = random.Random(SEED)
    found = []
    for quality in QUALITIES:
        root = rng.randrange(12)
        chord = theory.parse_chord(viewer_corpus.chord_name(root, quality), strict=False)
        keys = [Key(tonic, mode) for mode in ("ionian", "aeolian") for tonic in range(12)]
        keys += [Key(tonic, mode) for mode in MODES if mode not in ("ionian", "aeolian")
                 for tonic in sorted(rng.sample(range(12), OTHER_TONICS))]
        found.append((chord, tuple(keys)))
    seen = {_shape(chord) for chord, _ in found}
    slashed: list[Chord] = []
    outside: list[Chord] = []
    for name in viewer_corpus.chord_names():
        chord = theory.parse_chord(name, strict=False)
        if chord is None or _shape(chord) in seen:
            continue
        seen.add(_shape(chord))
        (outside if chord.bass is None else slashed).append(chord)
    chosen = slashed + [outside[i] for i in sorted(rng.sample(range(len(outside)), min(OUTSIDE, len(outside))))]
    fixed = [theory.parse_chord(name, strict=False) for name in FIXED_OUTSIDE]
    chosen += [chord for chord in fixed if chord not in chosen]
    all_keys = viewer_corpus.keys()
    found += [(chord, tuple(rng.sample(all_keys, SHAPE_KEYS))) for chord in chosen]
    rng = random.Random(SEED + 1)
    return tuple((chord, keys, tuple(nexts_for(chord, rng, n))) for n, (chord, keys) in enumerate(found))


def shape_branch(chord: Chord) -> str:
    """Which way harmony._shape reads the chord's quality, as its code goes."""
    q = chord.quality
    if q in harmony._SHAPES:
        return "table"
    if chord.tones is None or harmony._intervals(q) != chord.tones:
        return "unread"
    if q.startswith("dim"):
        return "dim"
    if q.startswith("aug"):
        return "aug"
    if q.startswith("m") and not q.startswith("maj"):
        return "m"
    return "other"


def test_every_way_shape_reads_a_quality_is_in_the_vectors():
    found = {shape_branch(chord) for chord, _, _ in _chords()}
    assert found == {"table", "unread", "dim", "aug", "m", "other"}
    for name in FIXED_OUTSIDE:
        chord = theory.parse_chord(name, strict=False)
        assert chord is not None and chord.quality not in QUALITIES, name


# --- the vectors ---------------------------------------------------------------------------------------------------


def chord_in_keys(chord: Chord, keys: list[Key], nexts: list[Chord | None]) -> dict:
    found = []
    for key in keys:
        reads = [[numeral_row(harmony.numeral(chord, key, n)), relation_row(harmony.relation(chord, key, n)),
                  harmony.explain(chord, key, n)] for n in nexts]
        found.append([harmony.family(chord, key), tones_row(harmony.chord_tones(chord, key)),
                      scale_row(harmony.solo_scale(chord, key)), reads])
    return {"alone": tones_row(harmony.chord_tones(chord, None)), "in": found}


def in_sequence(names: list[str], key: Key) -> dict:
    played = [c for c in (theory.parse_chord(n, strict=False) for n in names) if c is not None]
    goes = harmony._goes_to(played)
    return {
        "goes_to": [chord_row(g) for g in goes],
        "numerals": [harmony.numeral(c, key, g).text for c, g in zip(played, goes, strict=True)],
        "glossary": [list(line) for line in harmony.glossary(played, key)],
    }


def tooltips(chord: Chord, key: Key, next_chord: Chord | None) -> list[str]:
    return [harmony.explain(shifted(chord, s), Key((key.tonic + s) % 12, key.mode), shifted(next_chord, s))
            for s in range(12)]


def chord_records() -> list[dict]:
    return [{"fn": HELPER + "chord_in_keys",
             "args": [chord_row(chord), [key_row(k) for k in keys], [chord_row(c) for c in nexts]],
             "out": chord_in_keys(chord, list(keys), list(nexts))} for chord, keys, nexts in _chords()]


def _sequence_key(rng: random.Random, sheet: viewer_corpus.CorpusSheet, played: list[Chord]) -> Key:
    named = theory.named_key(sheet.key, sheet.capo or 0, played) if sheet.key else None
    return named or theory.estimate_key(played) or rng.choice(viewer_corpus.keys())


def sequence_records() -> list[dict]:
    rng = random.Random(SEED + 2)
    inputs: list[tuple[list[str], Key]] = [(list(p.chords), p.key) for p in viewer_corpus.progressions()]
    sheets = viewer_corpus.sheets()
    modes = [s for s in sheets if s.name.startswith("mode-")]
    chosen = [s for s in sheets if not s.name.startswith(("mode-", "catalogue-"))]
    chosen += [modes[i] for i in sorted(rng.sample(range(len(modes)), SHEETS_OF_MODES))]
    for sheet in chosen:
        names = list(sheet.played)
        played = [c for c in (theory.parse_chord(n, strict=False) for n in names) if c is not None]
        key = _sequence_key(rng, sheet, played)
        inputs.append((names, key))
        if sheet.name.startswith(("fixture:", "qualities-")):
            inputs.append((names, Key(rng.randrange(12), rng.choice([m for m in MODES if m != key.mode]))))
    inputs.append(([], Key(0, "ionian")))
    return [{"fn": HELPER + "in_sequence", "args": [names, key_row(key)], "out": in_sequence(names, key)}
            for names, key in inputs]


def tooltip_records() -> list[dict]:
    rng = random.Random(SEED + 3)
    out = []
    for chord, keys, nexts in _chords()[: len(QUALITIES)]:
        for _ in range(TOOLTIPS_EACH):
            key, after = rng.choice(keys), rng.choice(nexts)
            out.append({"fn": HELPER + "tooltips", "args": [chord_row(chord), key_row(key), chord_row(after)],
                        "out": tooltips(chord, key, after)})
    return out


def key_records() -> list[dict]:
    rows = [[k.tonic, k.mode, list(harmony.key_scale(k)), list(harmony.pentatonic(k))] for k in viewer_corpus.keys()]
    return [{"fn": HELPER + "key_scales", "args": [], "out": rows}]


def test_harmony_chord_vectors_are_harmony_pys_answers():
    records = chord_records() + sequence_records() + tooltip_records() + key_records()
    check(viewer_corpus.VIEWER_VECTORS / "harmony_chords.jsonl",
          jsonl(records, corpus="viewer/harmony_chords", made_by=MADE_BY))
