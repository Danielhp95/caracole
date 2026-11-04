"""viewer/harmony.py and viewer/harmony_tables.py for the phone: their constants as data, and what they answer, for
:viewer's viewer.harmony.

The logic is Kotlin's (viewer.harmony.Harmony and HarmonyTables); everything the modules state as data is written
here, from the modules themselves, so a change to a table, a word or a pattern regenerates what the phone reads and
the phone follows it. The chord half (lane harmony): numerals, relations, families, the explanations and their tooltip
lines, the glossary, a chord's notes, the scale for a solo over it, the key's scale and its pentatonic box, and which
chord each one goes to (``_goes_to``). The progressions (lane harmony-progressions): a section's progression
(``progressions``: ``_fold``, ``_passes``, ``_varies``, ``_whole``, ``_contained``, ``_ending``), ``progression_key``,
``name_of``, ``read_typed``, ``catalogue_keys``; and harmony_tables.py's ``tables``, the tables a viewer's data carries.

The data, ``tests/conformance/data/caracole/viewer/harmony.json`` (caracole/viewer/harmony.json on the phone's
classpath, ``ViewerData.table("harmony")``; ``viewer_corpus.data_json``), each member a constant of harmony.py under
its own name, a dict's members in its order, a set's sorted (a set has no order):

- ``ROMANS``, ``_FAMILIES``, ``_BASS_DEGREES``: arrays;
- ``_SHAPES``: ``{quality: [lower case, sign, extension]}``, a numeral's shape for each quality of theory.QUALITIES;
- ``_BORROWS``: ``{mode: [mode, …]}``, the modes a major and a minor key borrow from, first the one asked first;
- ``_MODE_WORDS``, ``_IN_OCTAVE``, ``_EXTENSION_WORDS``, ``_SYMBOL_MEANINGS``: objects as they are;
- ``_OTHER_SCALES``: ``{name: [step, …]}``, the scales a solo may take besides the modes;
- ``CATALOGUE``: ``[[name, [numeral, …], source], …]``, in its order; ``_LOOPS``: the rows that loop, ``[[numeral,
  …], …]``, sorted; ``_ON_ITS_TONIC``, ``_TURNS_ON_ITS_TONIC``, ``_NATURAL_MINOR``: sorted arrays;
  ``_ON_THE_TONIC``, ``_STEPS``, ``_ACCIDENTALS``: objects; ``_LONGEST_CYCLE``: a number;
- ``patterns``: ``_TOKENS``, ``_NUMERAL``, ``_ROMAN_ONLY`` and ``_SEPARATORS`` as Python writes them (``.pattern``,
  no flag), which core.py.PyRegex reads as Python does;
- ``harmony_tables``: harmony_tables.py's own, ``{"patterns": {"_NOTE": …, "_AFTER_NOTE": …}}``.

What harmony.py says in a sentence (an explanation's "the V of …", a glossary line's meaning, a scale's name by a
chord's quality, an interval's name) is its code, and Kotlin's: every word of it is compared below.

The vectors (``helpers.corpus.jsonl``), ``vectors/viewer/harmony_chords.jsonl`` (the chord half),
``harmony_progressions.jsonl`` and ``harmony_tables.jsonl`` (below). A chord is ``[root, quality, bass,
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

``harmony_progressions.jsonl``: a progression is ``[numerals, repeats, name, ending, variations, contains]``, each of
``contains`` ``[name, times, numerals, key]`` (``Progression``, ``Contained``); a token ``[root, third]``
(``_token``). Each record is one of:

- ``progressions_of(chords, sections, key)``: ``[[name, progression] for each section with one]``
  (``progressions``), each chord the sections play once in ``chords`` and a section ``[name, [index in chords or
  null, …]]``. The sections: ``HAND``, the cases of tests/test_viewer_harmony.py (their chord names, "N.C."
  none), and ``RULE_SECTIONS``, each telling a rule from its near miss; each progression of
  ``viewer_corpus.progressions()`` played once in its key and in the relative one, within a longer section (``ODD``
  chords around it, which start no row), and twice with a pass that varies it, and the first of each row's in every
  turn of its cycle; the corpus sheets' sections (page.py's ``_places``, a section's chords as the page reads them,
  loosely), in their page's key (``page._read_song``; one
  ``mode-`` sheet in ``MODE_SHEETS_EVERY``, every other sheet) and, one sheet in ``OTHER_MODE_EVERY``, mapped into a
  seeded other mode as the page's ``mapped`` has them (``map_chord``);
  ``SYNTHETIC`` seeded sections: a cycle of a progression's or a mode's chords played round, passes changed, added to
  or cut, chords dressed (an extension, a suspension, a bass), a home ending, a chord before, N.C.s, a section that
  ends on the next's chord.
- ``fold_of(helds)``: ``[[cycle, repeats, varied, seams] for each held]`` (``_fold``), over ``FOLDS`` seeded
  sequences of numerals (cycles played round with passes varied, and random ones), ``BATCH`` a record.
- ``contained_of(items)``: ``[held, mode, seams]`` → ``[[name, times, numerals, key], …]`` (``_contained``), over
  ``CONTAINED`` seeded sections made of the catalogue's rows as ``_rows(mode)`` writes them, in every mode, joined
  with fillers, their seams ``_fold``'s or seeded; then ``RULE_CONTAINED``, each telling a rule from its near miss.
- ``ending_of(items)``: each list of cores → ``_ending``.
- ``typed_of(items)``: each typed text (a string, or a list of numerals) → ``[progression_key, name_of,
  read_typed]``: every row of the catalogue as a list and as typed (spaces, dashes, commas), in a minor key's own way,
  the hand cases of the module's tests, ``EDGE_TYPED`` and ``TYPED`` seeded texts.
- ``core_token_of(texts)``: each numeral's ``[_core, _token]``: every numeral the records above type or read.
- ``rows_of(mode)``: ``_rows(mode)``, each ``[name, tokens, numerals, own, loops, forms]``, for each of
  ``ROWS_MODES`` (the others' are read through ``progressions_of`` and ``contained_of``).
- ``catalogue_keys()``: ``[[key, name], …]``, in its order; ``name_keys()``: ``_name_keys()`` so.

``harmony_tables.jsonl``: a **kept** answer is ``{"value": the answer, "sha256": …}``, the SHA-256 of
``json.dumps(answer, ensure_ascii=False, separators=(",", ":"))``, its members in Python's order (a vector's line sorts
an object's members), which Kotlin's ``core.json.PyJson.dumps(compact = true)`` writes alike. Each record is one of:

- ``tables_of(names, key, places)``: ``tables`` for a sheet whose chords (as written) are ``names`` and whose
  places are ``places`` (``[[chord index, section], …]``, page.py's ``_places``), in ``key`` (its page's), its chords
  read loosely and ``mapped`` and ``alts`` made as page.py makes them (``map_chord``, ``alternatives``): ``{"order":
  its members, "sha256": {member: …}}``, and ``"whole"``, kept, for ``HAND_SHEETS`` (tests/test_viewer_numerals.py's),
  ``RULE_SHEETS`` (each telling a rule from its near miss) and the first ``WHOLE_TABLES`` corpus sheet of
  ``WHOLE_CHORDS`` chords at most. Then ``TABLES`` corpus sheets: every edge, fixture and qualities sheet with a key,
  then seeded mode and catalogue ones; and ``NO_KEY_TABLES`` of them with no key (``tones`` alone).
- ``parts_of(texts)``: each text's ``_parts``; ``text_of(texts, key)``: ``text_of`` (kept: a ``by`` object);
  ``pitch_class_of(notes)``; ``page_name_of(items)``: ``[chord, key, s]`` → ``page_name(chord, spelling(key), s)``;
  ``role_of(items)``: ``[chord, key]`` → ``role``.

A sheet is read as its page reads it (``page._read_song``'s sheet and key, without the page's data: ``_read``).
``test_the_rule_cases_answer_as_their_rules_say`` checks each rule case still answers as its rule says, so that a
mutation of one of those rules (which the seeded inputs alone left unseen) changes a record.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harmony.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import functools
import hashlib
import json
import random
import re
from dataclasses import replace
from typing import Any

from caracole.viewer import harmony, harmony_tables, page, theory
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import MODES, QUALITIES, Chord, Key, alternatives, map_chord, spelling
from helpers import viewer_corpus
from helpers.corpus import check, jsonl

MADE_BY = "tests/test_conformance_viewer_harmony.py"
HELPER = "test_conformance_viewer_harmony."
SEED = viewer_corpus.SEED + 200
PATTERNS = ("_TOKENS", "_NUMERAL", "_ROMAN_ONLY", "_SEPARATORS")
TABLES_PATTERNS = ("_NOTE", "_AFTER_NOTE")
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
        "CATALOGUE": [[name, list(numerals), source] for name, numerals, source in harmony.CATALOGUE],
        "_LOOPS": [list(numerals) for numerals in sorted(harmony._LOOPS)],
        "_ON_ITS_TONIC": sorted(harmony._ON_ITS_TONIC),
        "_TURNS_ON_ITS_TONIC": sorted(harmony._TURNS_ON_ITS_TONIC),
        "_ON_THE_TONIC": dict(harmony._ON_THE_TONIC),
        "_STEPS": dict(harmony._STEPS),
        "_ACCIDENTALS": dict(harmony._ACCIDENTALS),
        "_NATURAL_MINOR": sorted(harmony._NATURAL_MINOR),
        "_LONGEST_CYCLE": harmony._LONGEST_CYCLE,
        "patterns": {name: _pattern(getattr(harmony, name)) for name in PATTERNS},
        "harmony_tables": {"patterns": {name: _pattern(getattr(harmony_tables, name)) for name in TABLES_PATTERNS}},
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
    assert tuple((n, tuple(ns), s) for n, ns, s in data["CATALOGUE"]) == harmony.CATALOGUE
    assert frozenset(tuple(ns) for ns in data["_LOOPS"]) == harmony._LOOPS
    assert len(data["_LOOPS"]) == len(harmony._LOOPS)
    assert frozenset(data["_ON_ITS_TONIC"]) == harmony._ON_ITS_TONIC
    assert frozenset(data["_TURNS_ON_ITS_TONIC"]) == harmony._TURNS_ON_ITS_TONIC
    assert frozenset(data["_NATURAL_MINOR"]) == harmony._NATURAL_MINOR
    assert data["_ON_THE_TONIC"] == harmony._ON_THE_TONIC and data["_STEPS"] == harmony._STEPS
    assert data["_ACCIDENTALS"] == harmony._ACCIDENTALS and data["_LONGEST_CYCLE"] == harmony._LONGEST_CYCLE
    assert harmony._NO_TOKEN == (-1, ""), "Progressions.kt's NO_TOKEN"
    # Progressions.kt reads a roman's case and letters as ASCII (str.islower, str.upper): the pattern's romans are.
    assert all(r.isascii() for r in re.findall(r"[IVXivx]+", harmony._ROMAN))
    for name, pattern in data["harmony_tables"]["patterns"].items():
        assert re.compile(pattern) == getattr(harmony_tables, name)
    assert list(harmony_tables.SHIFTS) == list(range(12)), "HarmonyTables.kt's twelve shifts"


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


# --- the progressions ----------------------------------------------------------------------------------------------

PROGRESSION_SEED = SEED + 10
BATCH = 50
OTHER_MODE_EVERY = 4
MODE_SHEETS_EVERY = 3
ROWS_MODES = ("ionian", "aeolian", "dorian", "locrian")
SYNTHETIC = 200
FOLDS = 250
CONTAINED = 160
TYPED = 120
C = Key(0, "ionian")
A_MINOR = Key(9, "aeolian")
# tests/test_viewer_harmony.py's sections, as (key, [(section, chord names), …]); a single section is "Verse".
HAND: tuple[tuple[Key, tuple[tuple[str, str], ...]], ...] = tuple(
    (key, sections if isinstance(sections, tuple) else (("Verse", sections),)) for key, sections in (
        (A_MINOR, "Am F C G"), (C, "Am F C G " * 4), (C, "C C G G Am Am F F"), (A_MINOR, "Am G F E"),
        (C, "C7 F7 C7 G7 F7 C7"), (C, "C7 F7 C7 G7 F7 C7 G7"), (C, "C7 F7 C7 F7 C7 G7 F7 C7"), (C, "C F C G F C"),
        (C, "C7 F C7 G7 F C7"), (C, "C Am F G"), (C, "Dm7 G7 Cmaj7"), (A_MINOR, "Bm7b5 E7 Am"), (C, "C F G"),
        (C, "C Bb F"), (C, "Am Dm G C"), (C, "C G Am Em F C F G"), (C, "E7 A7 D7 G7"), (C, "F G Em Am"),
        (C, "C Dm Em F"), (C, "C E7 A7 D7 G7 C"), (C, "Am G F E"), (A_MINOR, "Am Dm G C"), (A_MINOR, "F G Em Am"),
        (C, "C G Am F C"), (C, "C G F C F"), (C, "Dm G C"), (A_MINOR, "Am E Am"), (C, "C F C"), (C, "C F G Am"),
        (C, "C Am"), (C, "G"), (C, "C D D7 G"), (C, "Cmaj7 G/B Am7 Fadd9"), (C, "C G7sus4 Am F/A"),
        (C, "C5 G5 A5 F5"), (C, "Csus2 G Asus4 F"), (C, "Dsus4 G C"), (A_MINOR, "Am7 G/B Fmaj7 E7"),
        (C, "C C/E G Gsus4 G Am Am7 F Fmaj7"),
        (Key(4, "aeolian"), "Em7 G Dsus4 A7sus4 " * 3 + "Cadd9 Dsus4 A7sus4 " + "Em7 G Dsus4 A7sus4 " * 4),
        (Key(7, "ionian"), "Em7 G Dsus4 A7sus4 " * 3 + "Cadd9 Dsus4 A7sus4 " + "Em7 G Dsus4 A7sus4 " * 4),
        (Key(4, "aeolian"), "Cadd9 Dsus4 Em7 " * 3 + "Cadd9 Dsus4 G G/F# Em7 Dsus4/F# A7sus4"),
        (C, "Dm C G Am F Bb C G Am F"), (C, "Dm7 G7 Cmaj7 Am G F E7 Am G F E7"),
        (C, "C7 F7 C7 G7 F7 C7 F7 C7 G7 F7 C7 Am"), (C, "Am F C G " * 2), (C, "C G Am Em"), (C, "F G Am C"),
        (A_MINOR, "F G E7 Am"), (A_MINOR, "F G Em7 Am7"), (A_MINOR, "Am G F G"), (A_MINOR, "Am G F Em " * 2),
        (Key(7, "ionian"), "G B C Cm"), (Key(7, "ionian"), "G Bm C Cm"), (Key(2, "aeolian"), "Dm C Bb A"),
        (Key(6, "aeolian"), "F#m E D C#7"), (Key(7, "ionian"), "Em D C B7"), (A_MINOR, "Am G F Em"),
        (Key(2, "aeolian"), "Dm7 C Bb Am7"), (C, "Am G F Em"), (A_MINOR, "Am G F E7"),
        (Key(7, "ionian"), "G D C G D C G D"), (C, "C G F " * 3), (C, "Em Am F G"), (Key(2, "ionian"), "F#m Bm G A"),
        (C, "C Am Dm G"), (C, "G C Am Dm"), (C, "C Am Dm G " * 4 + "C"), (C, "G C Dm " * 2), (C, "F G Am G"),
        (C, "C F G Am G F C"), (Key(5, "ionian"), "F Em7 A7 Dm Dm/C Bb C7 F"), (C, "Dm7 G7 Cmaj7 A7 " * 4),
        (C, "Am F G C " * 2 + "E7"), (C, "C G Am F " * 3 + "C G Am Dm"),
        (C, "C G Am F " * 2 + "C G Em Am F " + "C G Am F"), (C, "C G Am F " * 2 + "C Am F " + "C G Am F"),
        (C, "C G Am F " * 2 + "C Em Am F G " + "C G Am F"), (C, "C G Am F " * 3 + "Dm G C F"), (C, "C G Am F " * 4),
        (C, "C G Am F C G Am Dm " * 3), (C, "C G Am F " * 4 + "C G Am Dm " + "C G Am F " + "C G Am Dm"),
        (C, "C G Am F C G Am Em"), (C, "C G Am F C G Am Em C G Am Dm"), (C, "C G Am F " * 2 + "C"),
        (C, (("Intro", ""), ("Verse", "C G"), ("Bridge", "N.C."), ("Chorus", "Am F"))), (C, ()),
        (C, (("Verse", "C D"), ("Chorus", "G C"))), (C, "C N.C. G N.C. Am F"),
    ))
# Inputs that tell a rule from its near miss, which the seeded ones may not hold (test_the_rule_cases_answer_as_their_
# rules_say). A held suspension takes the next chord's third (``_merged``): Asus4 A is VI, so this is no pop
# progression, which it would be if the held chord kept the suspension's "?".
RULE_SECTIONS: tuple[tuple[Key, tuple[tuple[str, str], ...]], ...] = ((C, (("Verse", "C G Asus4 A F"),)),)
# ``_contained``: a run that ends on the chord it starts with may end on a seam (the blues twice round, its seams on
# its I's: the 12-bar blues ×2, none if a seam on its last chord cut it); and the chord it lends to the next run is
# held once (the blues lending its I to I–IV–V holds no more chords than the extended plagal progression and I–IV–V
# apart, which win on the fewest runs and the tonic; counted twice, the blues would).
RULE_CONTAINED: tuple[list, ...] = (
    [["I", "IV", "I", "V", "IV", "I", "IV", "I", "V", "IV", "I"], "ionian", [5, 10]],
    [["♭VI", "♭III", "♭VII", "IV", "I", "IV", "I", "V", "IV", "I", "IV", "V"], "ionian", []],
)
# Dressings a synthetic section's chord may wear: (suffix, the quality it is read as), by its third.
_DRESS_MAJOR = ("maj7", "7", "add9", "6", "sus4", "sus2", "5")
_DRESS_MINOR = ("m7", "m9", "m6", "sus4", "5")
FOLD_ALPHABET = ("I", "ii", "iii", "IV", "V", "vi", "♭VII", "V/V", "Imaj7", "vi7", "IVadd9", "Vsus4")
EDGE_TYPED: tuple[Any, ...] = (
    "", " ", "–", "— , -", "I", "x", "foo bar", "I V　vi\tIV", "I\nV\r\nvi", "I V vi",
    "I\x1cV\x1fvi\x85IV", "I​V", "Ⅰ Ⅴ", "Ｉ Ｖ", "I😀 V", "😀 I 😀", "#iv° V", "bII V I", "♯IV V", "VII7/V/3",
    "V/V/V", "V//V", "I/", "/V", "iiø7 V7 i", "I+ IV", "Isus4 I", "I5 IV5 V5", "vi/vi", "V7/IV IV", "V/iv iv",
    "I iv I", "b", "#", "♭", "IIII", "iv I V vi", "i ii° III iv v VI VII", "i bIII bVI bVII", "i ♭VII ♭VI ♭VII",
    "I,V,vi,IV", "I—V—vi—IV", "I - V - vi - IV", "vi IV I V vi IV I V", "I V vi IV I", "I I", "I I I",
    "V7/V V I", "V V I", "I/3 IV V", "I V7/IV IV V", "i V7/iv iv", "i I iv", "vii°/V V I", "viiø7/vi vi",
    "I V/vi IV iv", "III7 VI7 II7 V7", "V7/vi V7/ii V7/V V7", "IVmaj7 V7 iii7 vi", "i VII VI VII", "i7–iv–VII7",
    "i–iv–VII–III–VI–ii°–V–i", "i VII VI V", "i VII VI v", "I VII IV", "I V IV I V IV I V", "iii vi IV V",
    "IV V vi V", "I vi ii V", "V I vi ii", "vi IV I V", "i bVII bVI bVII", "VI VII i", "bVI bVII I", "IV iv I",
    "I iii IV", "I IV ii V", "iv bVII I", "bVI bIII bVII IV I", "ii V i", "Ⅳ", "i̇ V", "İ V", "ı V",
    ["i", "bVII", "VI"], ["I", "V", "vi", "IV"], ["vi", "IV", "I", "V"], ["IV", "I", "V", "vi", "IV", "I", "V", "vi"],
    ["Imaj7", "V7", "vi7", "IVadd9"], ["bVII", "IV", "I"], ["I", "♭VII", "IV"], ["I", "vi", "IV", "V"],
    ["V7/V", "V", "I"], ["V", "V", "I"], ["I/3", "IV", "V"], ["I", "IV", "V"], ["I", "V7/IV", "IV", "V"],
    ["i", "V7/iv", "iv"], ["i", "I", "iv"], [], [""], ["", "I"], ["I", "", "V"], ["x", "I"], ["I V", "vi"],
    ["i", "VII", "VI", "VII"], ["i", "III"], ["i", "x"], ["I", "VII"],
)


def progression_row(p: harmony.Progression) -> list:
    return [list(p.numerals), p.repeats, p.name, p.ending, p.variations, [contained_row(c) for c in p.contains]]


def contained_row(c: harmony.Contained) -> list:
    return [c.name, c.times, list(c.numerals), c.key]


def progressions_of(sections: list[tuple[str, list[Chord | None]]], key: Key) -> list:
    return [[name, progression_row(p)] for name, p in harmony.progressions(sections, key)]


def _hand_section(names: str) -> list[Chord | None]:
    return [None if n == "N.C." else theory.parse_chord(n) for n in names.split()]


def _relative(key: Key) -> Key:
    return Key((key.tonic + 9) % 12, "aeolian") if key.mode == "ionian" else Key((key.tonic + 3) % 12, "ionian")


def _loose(names) -> list[Chord | None]:
    return [theory.parse_chord(n, strict=False) for n in names]


def sheet_sections(sheet, chords: list[Chord | None]) -> list[tuple[str, list[Chord | None]]]:
    """A sheet's sections as harmony_tables reads them: page.py's ``_places``, each section by its number, the notes
    before the song none of them."""
    places = page._places(sheet)
    numbers = sorted({n for _, n in places if n >= 0})
    return [(str(n), [chords[i] for i, m in places if m == n]) for n in numbers]


def _read(cho: str, key: str | None, key_source: str | None) -> tuple:
    """A sheet as its page reads it, ``page._read_song``'s sheet and key without the page's data (which is most of its
    time: harmony_tables.tables and harp.py's, for every sheet): (sheet, its chords read loosely, the key of its
    shapes)."""
    sheet = parse_sheet(cho)
    chords = _loose(sheet.chords)
    return sheet, chords, page._song_key(sheet, chords, key, key_source)[0]


@functools.cache
def _read_sheets() -> tuple:
    """Each corpus sheet as its page reads it: (corpus sheet, sheet, its chords read loosely, its page's key)."""
    return tuple((s, *_read(s.cho, s.key, s.key_source)) for s in viewer_corpus.sheets())


def test_a_sheet_is_read_as_its_page_reads_it():
    named = (viewer_corpus.sheet(n) for n in ("edge-0", "fixture:ug/tab_chords.html"))
    for s in [*viewer_corpus.sheets()[::40], *named]:
        sheet, key, _, _ = page._read_song(s.cho, s.key, s.key_source, 0)
        assert _read(s.cho, s.key, s.key_source) == (sheet, _loose(sheet.chords), key), s.name
    for cho in HAND_SHEETS + RULE_SHEETS:
        sheet, key, _, _ = page._read_song(cho, None, None, 0)
        assert _read(cho, None, None) == (sheet, _loose(sheet.chords), key)


def _dressed(rng: random.Random, chord: Chord, share: float) -> Chord:
    """``chord`` as a sheet may write it: an extension, a suspension or a bass now and then."""
    if rng.random() >= share or chord.quality not in ("", "m"):
        return chord
    if rng.random() < 0.25:
        return replace(chord, bass=(chord.root + rng.choice((3, 4, 7, 10))) % 12)
    suffix = rng.choice(_DRESS_MINOR if chord.quality == "m" else _DRESS_MAJOR)
    return theory.parse_chord(theory.SHARPS[chord.root] + suffix) or chord


def _varied(rng: random.Random, cycle: list, pool: list) -> list:
    """A pass of ``cycle`` played otherwise: a chord changed, added or left out, a chord changed and one added or
    left out, or two changed."""
    played = list(cycle)
    how = rng.choice(("change", "add", "drop", "change+add", "change+drop", "two"))
    if "change" in how or how == "two":
        played[rng.randrange(len(played))] = rng.choice(pool)
    if how == "two":
        played[rng.randrange(len(played))] = rng.choice(pool)
    if how.endswith("add"):
        played.insert(rng.randrange(len(played) + 1), rng.choice(pool))
    if how.endswith("drop") and len(played) > 1:
        del played[rng.randrange(len(played))]
    return played


def _synthetic_sections(rng: random.Random) -> list[tuple[list[tuple[str, list[Chord | None]]], Key]]:
    rows = viewer_corpus.progressions()
    modes = [(s, chords, key) for s, _, chords, key in _read_sheets() if s.name.startswith("mode-")]
    out = []
    for n in range(SYNTHETIC):
        if rng.random() < 0.6:
            p = rng.choice(rows)
            key = p.key if rng.random() < 0.8 else _relative(p.key)
            cycle = _loose(p.chords)
        else:
            _, chords, key = rng.choice(modes)
            cycle = [c for c in chords if c is not None][: rng.randint(2, 6)]
        pool = [Chord((key.tonic + step) % 12, theory._diatonic_quality((key.tonic + step) % 12, key, 3))
                for step in theory.SCALES[key.mode]] + [Chord((key.tonic + 6) % 12, ""), Chord((key.tonic + 1) % 12, "")]
        played: list[Chord | None] = []
        if rng.random() < 0.2:
            played.append(rng.choice(pool))
        passes = rng.choice((1, 2, 2, 3, 4, 5, 8))
        varied_at = {rng.randrange(passes) for _ in range(rng.choice((0, 0, 1, 1, 2)))}
        for i in range(passes):
            played += _varied(rng, cycle, pool) if i in sorted(varied_at) else cycle
        if rng.random() < 0.3:
            played += cycle[: rng.randint(1, max(1, len(cycle) - 1))]  # home
        share = rng.choice((0, 0, 0.3, 0.7))
        held = rng.random() < 0.2
        dressed: list[Chord | None] = []
        for chord in played:
            chord = _dressed(rng, chord, share)
            dressed.append(chord)
            if held and rng.random() < 0.3:
                dressed.append(chord)  # a chord held over two lines
        if rng.random() < 0.15:
            dressed.insert(rng.randrange(len(dressed) + 1), None)
        sections = [("Verse", dressed)]
        if rng.random() < 0.25:  # a section that ends on the next one's chord, a secondary read across them
            sections.append(("Chorus", [Chord((dressed[0].root + 7) % 12 if dressed[0] else 7, "7"), *cycle[:2]]))
        if rng.random() < 0.1:
            sections.insert(0, ("Intro", []))
        out.append((sections, key))
    return out


def progression_inputs() -> list[tuple[list[tuple[str, list[Chord | None]]], Key]]:
    return list(_progression_inputs())


@functools.cache
def _progression_inputs() -> tuple[tuple[list[tuple[str, list[Chord | None]]], Key], ...]:
    rng = random.Random(PROGRESSION_SEED)
    inputs = [([(name, _hand_section(names)) for name, names in sections], key)
              for key, sections in HAND + RULE_SECTIONS]
    seen_rows: set[int] = set()
    for p in viewer_corpus.progressions():
        chords = _loose(p.chords)
        odd = [Chord((p.key.tonic + 6) % 12, "dim"), Chord((p.key.tonic + 1) % 12, "")]
        pool = [Chord(rng.randrange(12), rng.choice(("", "m", "7")))]
        inputs += [([("Verse", chords)], p.key), ([("Verse", chords)], _relative(p.key)),
                   ([("Verse", odd + chords + odd[:1])], p.key),
                   ([("Verse", chords + _varied(rng, chords, chords + pool) + chords)], p.key)]
        if p.row not in seen_rows:
            seen_rows.add(p.row)
            cycle = chords[:-1] if p.chords[0] == p.chords[-1] else chords
            inputs += [([("Verse", cycle[t:] + cycle[:t])], p.key) for t in range(1, len(cycle))]
    for n, (s, sheet, chords, key) in enumerate(_read_sheets()):
        if key is None:
            continue
        if not s.name.startswith("mode-") or n % MODE_SHEETS_EVERY == 0:
            inputs.append((sheet_sections(sheet, chords), key))
        if n % OTHER_MODE_EVERY == 0:
            mode = rng.choice([m for m in MODES if m != key.mode])
            mapped = [None if c is None else map_chord(c, key, mode) for c in chords]
            inputs.append((sheet_sections(sheet, mapped), Key(key.tonic, mode)))
    return tuple(inputs + _synthetic_sections(rng))


def _fold_inputs(rng: random.Random) -> list[list[str]]:
    out = []
    for _ in range(FOLDS):
        if rng.random() < 0.2:
            out.append([rng.choice(FOLD_ALPHABET[:6]) for _ in range(rng.randint(1, 24))])
            continue
        cycle = [rng.choice(FOLD_ALPHABET) for _ in range(rng.randint(1, 9))]
        held: list[str] = [rng.choice(FOLD_ALPHABET)] if rng.random() < 0.15 else []
        passes = rng.choice((1, 2, 2, 3, 3, 4, 6, 9))
        varied_at = {rng.randrange(passes) for _ in range(rng.choice((0, 1, 1, 2, 3)))}
        for i in range(passes):
            held += _varied(rng, cycle, list(FOLD_ALPHABET)) if i in sorted(varied_at) else cycle
        if rng.random() < 0.3:
            held += cycle[: rng.randint(1, len(cycle))]
        out.append(harmony._collapse(held) if rng.random() < 0.8 else held)
    return out


def fold_records() -> list[dict]:
    rng = random.Random(PROGRESSION_SEED + 1)
    helds = _fold_inputs(rng)
    return [{"fn": HELPER + "fold_of", "args": [batch],
             "out": [[list(c), r, v, list(s)] for c, r, v, s in (harmony._fold(h) for h in batch)]}
            for batch in (helds[i:i + BATCH] for i in range(0, len(helds), BATCH))]


def _contained_inputs(rng: random.Random) -> list[list]:
    out = []
    fillers = ("♯iv°", "♭II", "♭V", "VII", "iii7", "V/ii", "x")
    for n in range(CONTAINED):
        mode = MODES[n % len(MODES)]
        rows = harmony._rows(mode)
        held: list[str] = []
        for _ in range(rng.randint(1, 4)):
            if rng.random() < 0.3:
                held.append(rng.choice(fillers))
            row = rng.choice(rows)
            numerals = list(row.numerals)
            turn = rng.randrange(len(numerals)) if row.loops and rng.random() < 0.5 else 0
            numerals = numerals[turn:] + numerals[:turn]
            held += numerals * rng.choice((1, 1, 2, 3))
        if rng.random() < 0.2:
            held.append(rng.choice(fillers))
        held = harmony._collapse(held)
        seams = list(harmony._fold(held)[3]) if rng.random() < 0.6 else sorted(
            {rng.randrange(1, len(held)) for _ in range(rng.randint(0, 3))} if len(held) > 1 else set())
        out.append([held, mode, seams])
    return out + [list(item) for item in RULE_CONTAINED]


def contained_records() -> list[dict]:
    rng = random.Random(PROGRESSION_SEED + 2)
    items = _contained_inputs(rng)
    return [{"fn": HELPER + "contained_of", "args": [batch],
             "out": [[contained_row(c) for c in harmony._contained(held, mode, seams)] for held, mode, seams in batch]}
            for batch in (items[i:i + BATCH] for i in range(0, len(items), BATCH))]


def _typed_inputs(rng: random.Random) -> list[Any]:
    out: list[Any] = []
    for _, numerals, _ in harmony.CATALOGUE:
        out += [list(numerals), " ".join(numerals), "–".join(numerals), ", ".join(numerals)]
        if "i" in numerals:  # in a minor key's own way
            out.append(" ".join(n[1:] if n in ("♭III", "♭VI", "♭VII") else n for n in numerals))
    out += list(EDGE_TYPED)
    alphabet = FOLD_ALPHABET + ("i", "iv", "v", "bVII", "bVI", "bIII", "III", "VI", "VII", "ii°", "V7", "x", "")
    for _ in range(TYPED):
        words = [rng.choice(alphabet) for _ in range(rng.randint(0, 9))]
        out.append(words if rng.random() < 0.3 else "".join(
            w + rng.choice((" ", " ", "–", ", ", "  ", "\t", " - ")) for w in words).strip(" ") if words else "")
    return out


def typed_answer(typed: Any) -> list:
    return [harmony.progression_key(typed), harmony.name_of(typed), list(harmony.read_typed(typed))]


def _ending_inputs() -> list[list[str]]:
    out = [["V", "I"], ["V", "i"], ["IV", "I"], ["iv", "I"], ["IV", "i"], ["V", "vi"], ["V", "♭VI"], ["V", "VI"],
           ["I", "V"], ["V"], [], ["V", "V", "I"], ["I", "I"], ["V", "I", "I"], ["V/V", "V"], ["ii", "V", "I", "I"],
           ["IV", "V", "vi", "vi"], ["x", "I"], ["V", "x"], ["vi", "V"], ["IV", "IV"]]
    for key, sections in HAND:
        for _, names in sections:
            chords = [c for c in _hand_section(names) if c is not None]
            goes = harmony._goes_to(chords)
            out.append([harmony._core(harmony.numeral(c, key, g).text) for c, g in zip(chords, goes, strict=True)])
    return out


def _texts_read() -> list[str]:
    """Every numeral the typed records type and the catalogue writes, each once."""
    found: dict[str, None] = {}
    for typed in _typed_inputs(random.Random(PROGRESSION_SEED + 3)):
        words = typed if isinstance(typed, list) else [n for n in harmony._SEPARATORS.split(typed) if n]
        found.update(dict.fromkeys(words))
    for mode in MODES:
        for row in harmony._rows(mode):
            found.update(dict.fromkeys(row.numerals))
    found.update(dict.fromkeys(FOLD_ALPHABET))
    return list(found)


def sections_args(sections: list[tuple[str, list[Chord | None]]]) -> tuple[list, list]:
    """A record's sections, small: each chord they play once (``[chord, …]``), and each section ``[name, [its
    chords' indexes, null for none]]``."""
    chords: dict[Chord, int] = {}
    rows = []
    for _, played in sections:
        for c in played:
            if c is not None and c not in chords:
                chords[c] = len(chords)
                rows.append(chord_row(c))
    return rows, [[name, [None if c is None else chords[c] for c in played]] for name, played in sections]


def _token_row(t: tuple[int, str]) -> list:
    return [t[0], t[1]]


def progression_records() -> list[dict]:
    out = [{"fn": HELPER + "progressions_of", "args": [*sections_args(sections), key_row(key)],
            "out": progressions_of(sections, key)} for sections, key in progression_inputs()]
    out += fold_records() + contained_records()
    endings = _ending_inputs()
    out += [{"fn": HELPER + "ending_of", "args": [batch], "out": [harmony._ending(c) for c in batch]}
            for batch in (endings[i:i + BATCH] for i in range(0, len(endings), BATCH))]
    typed = _typed_inputs(random.Random(PROGRESSION_SEED + 3))
    out += [{"fn": HELPER + "typed_of", "args": [batch], "out": [typed_answer(t) for t in batch]}
            for batch in (typed[i:i + BATCH] for i in range(0, len(typed), BATCH))]
    texts = _texts_read()
    out += [{"fn": HELPER + "core_token_of", "args": [batch],
             "out": [[harmony._core(t), _token_row(harmony._token(t))] for t in batch]}
            for batch in (texts[i:i + BATCH] for i in range(0, len(texts), BATCH))]
    out += [{"fn": HELPER + "rows_of", "args": [mode], "out": [
        [row.name, [_token_row(t) for t in row.tokens], list(row.numerals), row.own, row.loops,
         [[_token_row(t) for t in form] for form in row.forms]] for row in harmony._rows(mode)]} for mode in ROWS_MODES]
    out.append({"fn": HELPER + "catalogue_keys", "args": [], "out": [list(kv) for kv in harmony.catalogue_keys().items()]})
    out.append({"fn": HELPER + "name_keys", "args": [], "out": [list(kv) for kv in harmony._name_keys().items()]})
    return out


def test_every_branch_of_the_progressions_is_in_the_vectors():
    folds = [harmony._fold(h) for h in _fold_inputs(random.Random(PROGRESSION_SEED + 1))]
    assert any(v for _, _, v, _ in folds) and any(r > 1 and not v for _, r, v, _ in folds)
    assert any(r == 1 for _, r, _, _ in folds)
    found = [p for sections, key in progression_inputs() for _, p in harmony.progressions(sections, key)]
    assert {p.ending for p in found} == {None, "authentic", "plagal", "deceptive", "half"}
    assert any(p.variations for p in found) and any(p.contains for p in found) and any(p.name for p in found)
    named = {p.name for p in found} | {c.name for p in found for c in p.contains}
    assert {name for name, _, _ in harmony.CATALOGUE} <= named
    assert any(len(p.contains) > 1 for p in found)


def test_harmony_progression_vectors_are_harmony_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "harmony_progressions.jsonl",
          jsonl(progression_records(), corpus="viewer/harmony_progressions", made_by=MADE_BY))


# --- harmony_tables.py ---------------------------------------------------------------------------------------------

TABLES_SEED = SEED + 20
TABLES = 40
WHOLE_TABLES = 1
# tests/test_viewer_numerals.py's sheets, kept whole: D read two ways (V/V going to G, C Lydian's II going to C), the
# minor key's V7, G7 as V7/IV.
HAND_SHEETS = (
    "{title: In C}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n[C]Made up [G]words to [Am]sing a[F]long\n"
    "[C]made up [G]words to [Am]sing a[F]long\n\n{comment: Bridge}\n[D]Five [G]six [D]seven [C]eight\n[Bb]Borrowed "
    "[F]from the [C]minor\n",
    "{title: In A minor}\n{artist: Synthetic}\n{key: Am}\n{comment: Verse}\n[Am]Down the [G]stairs we [F]go and "
    "[E7]on\n[Am]down the [G]stairs we [F]go and [E7]on\n",
    "{title: In G}\n{artist: Synthetic}\n{key: G}\n{comment: Verse}\n[G]Made up [G7]words to [C]sing a[G]long\n"
    "[G]made up [Em]words to [D7]sing a[G]long\n",
)
# Sheets that tell a rule of ``tables`` from its near miss, kept whole (test_the_rule_cases_answer_as_their_rules_say):
# D read otherwise than most of its places read it (V/V, going to G) at two places, going to C, which share the one
# reading added for it.
RULE_SHEETS = (
    "{title: D read two ways}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n[D]One [G]two [D]three [G]four\n"
    "[D]five [G]six [D]seven [C]eight\n[D]nine [C]ten\n",
)
WHOLE_CHORDS = 8  # a sheet whose tables are kept whole plays this many chords at most
NO_KEY_TABLES = 4


def sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def kept(value: Any) -> dict:
    """An answer whole, and its ``sha256``: a vector's line sorts an object's members, the digest keeps their order."""
    return {"value": value, "sha256": sha256(value)}


def mapped_and_alts(chords: list[Chord | None], key: Key) -> tuple[dict, dict]:
    """A sheet's chords in each mode of ``key`` with their alternatives, as page.py's ``_data`` makes them."""
    mapped: dict[str, list] = {}
    alts: dict[str, list] = {}
    for mode in MODES:
        mapped[mode] = [None if c is None else map_chord(c, key, mode) for c in chords]
        alts[mode] = [[] if c is None else alternatives(c, Key(key.tonic, mode)) for c in mapped[mode]]
    return mapped, alts


@functools.cache
def tables_sheets() -> tuple:
    """The sheets whose tables the vectors hold: every edge, fixture and qualities sheet with a key, then seeded mode
    and catalogue ones, ``TABLES`` in all; and ``NO_KEY_TABLES`` read with no key."""
    rng = random.Random(TABLES_SEED)
    read = [r for r in _read_sheets() if r[3] is not None]
    chosen = [r for r in read if r[0].name.startswith(("edge-", "fixture:", "qualities-"))]
    rest = [r for r in read if r not in chosen]
    chosen += [rest[i] for i in sorted(rng.sample(range(len(rest)), TABLES - len(chosen)))]
    no_key = [r for r in _read_sheets() if r[3] is None]
    no_key += [read[i] for i in sorted(rng.sample(range(len(read)), NO_KEY_TABLES - len(no_key)))]
    return tuple(chosen), tuple(no_key)


def tables_record(sheet, chords: list[Chord | None], key: Key | None, whole: bool) -> dict:
    places = page._places(sheet)
    if key is None:
        tables = harmony_tables.tables(chords, None, places, {}, {})
    else:
        mapped, alts = mapped_and_alts(chords, key)
        tables = harmony_tables.tables(chords, key, places, mapped, alts)
    out = {"order": list(tables), "sha256": {k: sha256(v) for k, v in tables.items()}}
    if whole:
        out["whole"] = kept(tables)
    return {"fn": HELPER + "tables_of", "args": [list(sheet.chords), key_row(key), [list(p) for p in places]],
            "out": out}


def _text_inputs() -> list[tuple[list[str], Key]]:
    """Lines whose notes text_of writes in each of its three ways."""
    out = []
    for key in (Key(0, "ionian"), Key(9, "aeolian"), Key(2, "dorian"), Key(6, "locrian")):
        out.append((["the same line"] * 12, key))
        out.append(([f"{spelling(Key((key.tonic + s) % 12, key.mode))[(key.tonic + s) % 12]} is home" for s in range(12)],
                    key))
        out.append(([f"in {s}" for s in range(12)], key))
    return out


def tables_records() -> list[dict]:
    out = []
    for cho in HAND_SHEETS + RULE_SHEETS:
        sheet, chords, key = _read(cho, None, None)
        out.append(tables_record(sheet, chords, key, True))
    keyed, no_key = tables_sheets()
    small = [n for n, (_, sheet, _, _) in enumerate(keyed) if len(sheet.chords) <= WHOLE_CHORDS][:WHOLE_TABLES]
    out += [tables_record(sheet, chords, key, n in small) for n, (_, sheet, chords, key) in enumerate(keyed)]
    out += [tables_record(sheet, chords, None, n == 0) for n, (_, sheet, chords, _) in enumerate(no_key)]
    texts = ["", "C", "Am", "Bbmaj7", "Bbass", "Dorian", "D Dorian", "C# Locrian", "G7 goes to C", "Ebm", "F♯m",
             "B♭ in the bass", "Asus4 Badd9 Caug Ddim Em", "Ab", "Abc", "A b", "Cb", "E#", "AB", "ABC", "xC", "C.",
             "Cm7", "Cmaj7", "C♯", "Csus", "Cadd", "Caug", "Cdim", "Cmin", "Cmo", "CDE", "(C)", "C/E", "the V of G",
             "V: the 5th chord of C major, major (upper case); points to C", "CaféD", "ÀB", "😀C😀", "Ć"]
    for _, _, chords, key in keyed[:6]:
        for c in chords[:6]:
            if c is not None:
                texts.append(harmony.explain(c, key))
    out.append({"fn": HELPER + "parts_of", "args": [texts], "out": [harmony_tables._parts(t) for t in texts]})
    out += [{"fn": HELPER + "text_of", "args": [lines, key_row(key)], "out": kept(harmony_tables.text_of(lines, key))}
            for lines, key in _text_inputs()]
    notes = ["C", "B#", "Fbb", "E#", "Cb", "Ab", "G##", "Dbb", "F♯", "B♭", "A", "Ebb", "Gb"]
    out.append({"fn": HELPER + "pitch_class_of", "args": [notes], "out": [harmony_tables.pitch_class(n) for n in notes]})
    rng = random.Random(TABLES_SEED + 1)
    names = [n for n in viewer_corpus.chord_names() if theory.parse_chord(n, strict=False) is not None]
    items = []
    for name in rng.sample(names, 60):
        items.append([chord_row(theory.parse_chord(name, strict=False)), key_row(rng.choice(viewer_corpus.keys() + [None])),
                      rng.randrange(12)])
    out.append({"fn": HELPER + "page_name_of", "args": [items], "out": [
        harmony_tables.page_name(_row_chord(c), spelling(None if k is None else Key(*k)), s) for c, k, s in items]})
    roles = [[chord_row(theory.parse_chord(name, strict=False)), key_row(rng.choice(viewer_corpus.keys()))]
             for name in rng.sample(names, 80)]
    out.append({"fn": HELPER + "role_of", "args": [roles], "out": [
        harmony_tables.role(_row_chord(c), Key(*k)) for c, k in roles]})
    return out


def _row_chord(row: list) -> Chord:
    row = row + [None] * (5 - len(row))
    return Chord(row[0], row[1], row[2], row[3], None if row[4] is None else frozenset(row[4]))


def test_the_tables_records_read_their_chords_back():
    for _, sheet, chords, key in tables_sheets()[0][:5]:
        assert [_row_chord(chord_row(c)) if c else None for c in chords] == chords


def test_harmony_tables_vectors_are_harmony_tables_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "harmony_tables.jsonl",
          jsonl(tables_records(), corpus="viewer/harmony_tables", made_by=MADE_BY))


def test_the_rule_cases_answer_as_their_rules_say():
    """``RULE_SECTIONS``, ``RULE_CONTAINED`` and ``RULE_SHEETS`` are in the vectors and answer as the rule each tells
    from its near miss says: so a port that breaks one of those rules fails a record."""
    key, sections = RULE_SECTIONS[0]
    held = [(name, _hand_section(names)) for name, names in sections]
    assert (held, key) in progression_inputs()
    (_, p), = harmony.progressions(held, key)
    assert p.numerals[2:4] == ("VIsus4", "V/ii") and p.name is None and not p.contains
    blues, plagal = (harmony._contained(held, mode, seams) for held, mode, seams in RULE_CONTAINED)
    assert [(c.name, c.times) for c in blues] == [("the 12-bar blues", 2)]
    assert [(c.name, c.times) for c in plagal] == [("the extended plagal progression", 1), ("I–IV–V", 1)]
    assert all(list(item) in _contained_inputs(random.Random(PROGRESSION_SEED + 2)) for item in RULE_CONTAINED)
    sheet, chords, key = _read(RULE_SHEETS[0], None, None)
    mapped, alts = mapped_and_alts(chords, key)
    tables = harmony_tables.tables(chords, key, page._places(sheet), mapped, alts)
    d = sheet.chords.index("D")
    assert tables["numerals"]["ionian"][d][0] == "V/V"
    assert len(tables["numerals"]["ionian"]) == len(chords) + 1 and tables["numerals"]["ionian"][-1][0] == "II"
    assert list(tables["places"]["ionian"].values()) == [len(chords)] * 2
