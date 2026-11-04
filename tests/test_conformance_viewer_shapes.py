"""viewer/voicings.py, instruments.py, harp.py and winds.py for the phone: their constants as data, and what they
answer, for :viewer's viewer.shapes (Voicings, Instruments), viewer.harp (Harp) and viewer.winds (Winds).

The logic is Kotlin's; what the modules state as data is written here from the modules themselves, so a change to a
table, a chart or a pattern regenerates what the phone reads. chords-db's fingerings are no data of this file: they
are viewer/'s own ``voicings.json`` and ``voicings-ukulele.json``, which :viewer's build copies byte for byte.

**The data** (``viewer_corpus.data_json``: each member a constant under its Python name, a dict's members in its
order), read by Kotlin's ``ViewerData.table(module)``:

- ``data/caracole/viewer/instruments.json``: ``INSTRUMENTS`` (each ``Instrument``'s fields, in the menu's order),
  ``EASY`` (``{table: [majors, minors]}``), ``LOW``, ``HIGH``, ``BASS``; and ``voicings``, voicings.py's own constants
  (``caracole/viewer/voicings.json`` is chords-db's data, so they can't be a file of that name): ``TUNING``,
  ``MAX_POSITIONS``, ``_FRET_SPAN`` and ``patterns``, ``_FINGERING``, ``_ENTRY``, ``_DEFINE_FRETS``,
  ``_DEFINE_FINGERS`` and ``_DEFINE_BASE`` as Python writes them (``.pattern``, no flags: core.py.PyRegex reads them
  as Python does).
- ``data/caracole/viewer/harp.json``: ``HOLES``, ``BLOW``, ``DRAW``, ``HARP_KEYS``, ``_LOWEST``, ``POSITIONS``,
  ``_ORDINALS`` (its keys as strings), ``CHORD_FIT`` (floats), ``TONIC_WEIGHT``, ``MINOR_BLUES``, ``MAJOR_BLUES``,
  ``_MODE_WORDS``; and ``harmony``, what harp.py reads of harmony.py: ``pentatonic``, each mode's box on C
  (``harmony.pentatonic(Key(0, mode))``), the key card's chip.
- ``data/caracole/viewer/winds.json``: ``_LETTERS``, ``SOLFEGE``, ``FLUTE_KEYS``, ``RECORDER_HOLES``,
  ``_HIGHEST_STEP``, ``WINDS`` (each ``Wind``'s fields), ``_FLUTE_CHART``, ``_RECORDER_CHART``, ``_GERMAN``,
  ``_FLUTE_EXTRAS``, ``_FLUTE_THUMB`` (``-`` null); and ``harmony``, what winds.py reads of harmony.py:
  ``_BASS_DEGREES``.

**The vectors** (``helpers.corpus.jsonl``), ``vectors/viewer/``, about a megabyte in all. A chord is ``[root,
quality, bass, shown, tones]`` with its trailing nulls left out (``tones`` sorted), a key ``[tonic, mode]``, a
position ``[frets, fingers, base fret, barres]`` as voicings.py has it. An answer that raised is ``{"err": its type's
name}``. A vector's line sorts an object's members, so an answer whose members' order a page keeps is **kept**:
``{"value": the answer, "sha256": …}``, the SHA-256 of ``json.dumps(answer, ensure_ascii=False, separators=(",",
":"))``, its members in Python's order (the order a page's data is written in), which Kotlin's
``core.json.PyJson.dumps(compact = true)`` writes alike; an answer too big to keep whole keeps its digest alone. The
inputs are ``viewer_corpus``'s (its chord names, keys, sheets and progressions; ``kinds()``, the first name of each
kind of chord it names: its quality, its bass above its root, its tones), the string literals of the modules' own
tests (``LITERALS_FROM``), and inputs drawn from ``SEED``, some sheets or instruments of each kind drawn too.

- ``voicings.jsonl``: ``fingerings_of(texts)`` (``parse_fingering`` of each), ``legends_of(lines)``
  (``chord_legend``: ``[[chord, position], …]``; the corpus's lines that are a legend, some that aren't, and seeded
  ones), ``defines_of(values)`` (``parse_define``), each over a batch of ``BATCH``; ``keys_of(names)``: each name's
  loose chord's ``[fingering, nearest, slash, shape_key, piano_key]`` (``voicing_keys``, ``shape_key``,
  ``instruments.piano_key``), null for no chord; ``positions_of(items)``: ``[position, tuning]`` → ``[notes_of,
  frets_from_nut]``; ``plays_of(items)``: ``[position, chord, tuning]`` → ``plays``; ``sheet_shapes_of(given, names,
  shift)``: ``{"shapes": sheet_shapes(given), kept, "guitar": [chord_shapes(GUITAR, chord, shift, given=shapes) for
  each name's loose chord]}`` for every corpus sheet that gives shapes (page.py's ``_given_shapes``; the names its
  given chords' and a few others) and seeded lists; ``page_voicings_of(keys)``: ``{"keys": …, "sha256": …}``.
- ``instruments.jsonl``: ``instrument_of(names)``; ``easy_keys(table)``, kept; ``is_easy_of(table, keys)``;
  ``ukulele_quality_of(fingerings)``; ``chord_of(name, shift)``: ``{"chord", "stacked", "piano", "piano_key",
  "on_root", "shapes": {id: chord_shapes(inst, chord, shift)}}`` for each of ``kinds()``, its shapes on a
  ``SHAPES_ON`` share of the instruments, drawn; ``page_of(fingerings, chords)``: what a page's data carries,
  ``{"voicings": [keys, sha256], "instruments": [keys, sha256], "entries": sha256, "near": the ukulele's}``, for one
  corpus sheet in three, its chords as written and in a drawn mode; ``entries`` of none, kept.
- ``harp_play.jsonl``: ``play_of(chords)``: each chord's ``entry(play(chord, harp))`` on the 12 harps, for every
  quality on C (with a drawn bass now and then) and each of ``kinds()``; ``texts_of(items)``: ``[chord, harp, key]``
  → ``play(chord, harp).text(spelling(key))``; ``steps_of(items)``: ``[chord, tonic]`` → ``chord_steps``.
- ``harp_choices.jsonl``: ``choices_of(names, key)``: ``{"candidates", "ranking": [ranking(key, order, choice) for
  each candidate in order], "choices": [[position, harp, mode, fit, chords, plays, substitutes], …], "header"}`` for
  each corpus sheet in its key or a drawn mode of it, and each progression in its key (and half of them in a drawn
  key); ``candidates`` of every key.
- ``harp_tables.jsonl``: ``tables_of(names, key)``: harp.py's ``tables`` for one corpus sheet in four whose chords
  (as written) are ``names`` in ``key``, its ``mapped`` and ``alts`` made as page.py makes them (``map_chord``,
  ``alternatives``): ``{"order": its members, "sha256": {member: …}}`` (and ``"whole"``, kept, for the first
  ``WHOLE_TABLES``); ``tables`` of no key; ``tables_in(names, key, modes)``, some modes alone and no alternatives,
  kept; the layout and the overlay's tables: ``layout_of(harp)``, ``ring``, ``holes`` (kept), ``key_scales``,
  ``outside_of(mode)``, ``layouts``, ``hole_tables`` (kept), ``positions_of(position)`` (``position_mode``,
  ``ordinal``, and ``harp_for`` on each tonic), ``position_text_of(tonic)`` (``position_of`` and ``position_text`` on
  each harp), ``hole_notes_of(harp)`` (``hole_note`` of every hole 0 to 11, breath, bend −1 to 4 and over, in that
  order), ``entry_text_of(items)``.
- ``winds.jsonl``: ``fingerings_of(wind, system)``: each note of ``NOTES`` → ``[[chart, text], …]``, each system and
  none and one the wind hasn't; ``fit_of(notes, wind)`` → ``[shift, written, outside]``; ``scale_notes`` of every
  key; ``steps_of(chords)`` → ``[chord_steps, chord_notes]``; ``interval_steps_of(items)``: ``[intervals, bass]`` →
  ``chord_steps`` of a chord on C of those intervals, for every set of intervals with its root (and drawn basses);
  ``solfege_of(names)``; ``fingering_data``, kept; ``tables_of(names, key)``: winds.py's ``tables``, kept, its
  ``mapped`` and ``alts`` as above, for one corpus sheet in four and every sheet with no key (the sheet's chords
  alone).

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_shapes.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import itertools
import json
import random
import re
from pathlib import Path
from typing import Any

from caracole.viewer import harmony, harp, instruments, page, voicings, winds
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import MODES, QUALITIES, Chord, Key, alternatives, map_chord, parse_chord, spelling
from helpers import viewer_corpus
from helpers.corpus import check, jsonl

MADE_BY = "tests/test_conformance_viewer_shapes.py"
HELPER = "test_conformance_viewer_shapes."
TESTS = Path(__file__).resolve().parent
LITERALS_FROM = ("test_viewer_voicings.py", "test_viewer_instruments.py", "test_viewer_harp.py",
                 "test_viewer_winds.py")
SEED = viewer_corpus.SEED + 300
BATCH = 50
WHOLE_TABLES = 3  # the first sheets whose harp tables are kept whole beside their digests
NOTES = range(50, 101)  # the notes asked of each wind's fingerings: below C4 to above C7
PATTERNS = ("_FINGERING", "_ENTRY", "_DEFINE_FRETS", "_DEFINE_FINGERS", "_DEFINE_BASE")
# Decimal digits Python's \d and int() read past ASCII: fullwidth, Arabic-Indic, extended Arabic-Indic, a
# mathematical one beyond the BMP.
ODD_DIGITS = ("３", "٣", "۷", "𝟑", "１", "０")
SPACES = (" ", "  ", "\t", "\u00a0", "\u3000", "\x1f")
SHAPES_ON = 0.15  # the share of the instruments a chord_of record asks for its shapes on, drawn


# --- the data ------------------------------------------------------------------------------------------------------


def _pattern(p: re.Pattern[str]) -> str:
    assert p.flags & ~re.UNICODE == 0, f"{p.pattern!r}: a flag the phone doesn't read"
    return p.pattern


def instruments_constants() -> dict:
    fields = ("id", "name", "kind", "tuning", "capo", "shapes", "easy", "voice", "sounds", "offset", "about", "tab")
    return {
        "voicings": {
            "TUNING": list(voicings.TUNING),
            "MAX_POSITIONS": voicings.MAX_POSITIONS,
            "_FRET_SPAN": voicings._FRET_SPAN,
            "patterns": {name: _pattern(getattr(voicings, name)) for name in PATTERNS},
        },
        "INSTRUMENTS": [{f: list(v) if isinstance(v := getattr(i, f), tuple) else v for f in fields}
                        for i in instruments.INSTRUMENTS],
        "EASY": {table: [list(majors), list(minors)] for table, (majors, minors) in instruments.EASY.items()},
        "LOW": instruments.LOW,
        "HIGH": instruments.HIGH,
        "BASS": instruments.BASS,
    }


def harp_constants() -> dict:
    return {
        "HOLES": harp.HOLES,
        "BLOW": list(harp.BLOW),
        "DRAW": list(harp.DRAW),
        "HARP_KEYS": list(harp.HARP_KEYS),
        "_LOWEST": harp._LOWEST,
        "POSITIONS": list(harp.POSITIONS),
        "_ORDINALS": {str(k): v for k, v in harp._ORDINALS.items()},
        "CHORD_FIT": dict(harp.CHORD_FIT),
        "TONIC_WEIGHT": harp.TONIC_WEIGHT,
        "MINOR_BLUES": list(harp.MINOR_BLUES),
        "MAJOR_BLUES": list(harp.MAJOR_BLUES),
        "_MODE_WORDS": dict(harp._MODE_WORDS),
        "harmony": {"pentatonic": {mode: list(harmony.pentatonic(Key(0, mode))) for mode in MODES}},
    }


def winds_constants() -> dict:
    fields = ("name", "low", "high", "sounds", "easy", "keys", "systems")
    return {
        "_LETTERS": list(winds._LETTERS),
        "SOLFEGE": dict(winds.SOLFEGE),
        "FLUTE_KEYS": list(winds.FLUTE_KEYS),
        "RECORDER_HOLES": list(winds.RECORDER_HOLES),
        "_HIGHEST_STEP": winds._HIGHEST_STEP,
        "WINDS": {name: {f: list(v) if isinstance(v := getattr(w, f), tuple) else v for f in fields}
                  for name, w in winds.WINDS.items()},
        "_FLUTE_CHART": {note: list(charts) for note, charts in winds._FLUTE_CHART.items()},
        "_RECORDER_CHART": dict(winds._RECORDER_CHART),
        "_GERMAN": dict(winds._GERMAN),
        "_FLUTE_EXTRAS": dict(winds._FLUTE_EXTRAS),
        "_FLUTE_THUMB": dict(winds._FLUTE_THUMB),
        "harmony": {"_BASS_DEGREES": list(harmony._BASS_DEGREES)},
    }


DATA = {"instruments": instruments_constants, "harp": harp_constants, "winds": winds_constants}


@functools.cache
def data_text(module: str) -> str:
    return viewer_corpus.data_json(DATA[module]())


def test_the_data_is_the_modules_constants():
    for module in DATA:
        check(viewer_corpus.VIEWER_DATA / f"{module}.json", data_text(module))


def test_the_data_reads_back_as_the_modules_hold_it():
    data = json.loads(data_text("instruments"))
    for name, pattern in data["voicings"]["patterns"].items():
        assert re.compile(pattern) == getattr(voicings, name)
    assert tuple(data["voicings"]["TUNING"]) == voicings.TUNING
    assert [instruments.Instrument(**{k: tuple(v) if k == "tuning" else v for k, v in i.items()})
            for i in data["INSTRUMENTS"]] == list(instruments.INSTRUMENTS)
    data = json.loads(data_text("harp"))
    assert {int(k): v for k, v in data["_ORDINALS"].items()} == harp._ORDINALS
    assert data["CHORD_FIT"] == harp.CHORD_FIT and all(isinstance(v, float) for v in data["CHORD_FIT"].values())
    data = json.loads(data_text("winds"))
    assert {k: winds.Wind(**{f: tuple(v) if isinstance(v, list) else v for f, v in w.items()})
            for k, w in data["WINDS"].items()} == winds.WINDS


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


def answer(fn, *args, **kwargs) -> Any:
    """``fn``'s answer, or ``{"err": …}`` naming what it raised."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - what Python raises is the vector's
        return {"err": type(e).__name__}


def sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def kept(value: Any) -> dict:
    """An answer whole, and its ``sha256``: a vector's line sorts an object's members, the digest keeps their order."""
    return {"value": value, "sha256": sha256(value)}


def _batches(items: list) -> list[list]:
    return [items[i:i + BATCH] for i in range(0, len(items), BATCH)]


@functools.cache
def literals() -> tuple[str, ...]:
    """The string literals of the modules' tests, at most 40 code points, in order."""
    found: dict[str, None] = {}
    for name in LITERALS_FROM:
        for node in ast.walk(ast.parse((TESTS / name).read_text("utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 40:
                found[node.value] = None
    return tuple(sorted(s for s in found if not any(0xD800 <= ord(c) <= 0xDFFF for c in s)))


@functools.cache
def names() -> tuple[str, ...]:
    """The chord names: the corpus's, then the literals that are chords."""
    out = dict.fromkeys(viewer_corpus.chord_names())
    out.update(dict.fromkeys(s for s in literals() if parse_chord(s, strict=False) is not None))
    return tuple(out)


def _kind(chord: Chord) -> tuple:
    return chord.quality, None if chord.bass is None else (chord.bass - chord.root) % 12, chord.tones


@functools.cache
def kinds() -> tuple[str, ...]:
    """One name of each kind of chord the corpus names (its quality, its bass above its root, its tones), the
    first."""
    seen: dict[tuple, str] = {}
    for name in names():
        chord = parse_chord(name, strict=False)
        if chord is not None:
            seen.setdefault(_kind(chord), name)
    return tuple(seen.values())


def _digit(rng: random.Random, value: int) -> str:
    """``value`` as a tab writes it, now and then in another script's digits (a single one alone)."""
    if value < 10 and rng.random() < 0.06:
        odd = rng.choice(ODD_DIGITS)
        return chr(ord(odd) - int(odd) + value)
    return str(value)


def _fret(rng: random.Random, high: int = 12) -> str:
    return rng.choice("xX") if rng.random() < 0.2 else _digit(rng, rng.randint(0, high))


def fingering_text(rng: random.Random) -> str:
    """A fingering as tabs write one, or nearly."""
    form = rng.random()
    if form < 0.4:
        text = "".join(_fret(rng, 9) for _ in range(rng.choice((6, 6, 6, 5, 7))))
    else:
        count = rng.choice((6, 6, 6, 6, 5, 7))
        separators = (" ", "-", ".", ",", " - ", "\t", "\u00a0", "  ", "-.", ", ")
        sep = rng.choice(separators)
        frets = [_fret(rng, rng.choice((5, 12, 24, 26))) for _ in range(count)]
        text = sep.join(frets) if rng.random() < 0.8 else "".join(f + rng.choice(separators) for f in frets)
    if rng.random() < 0.35:
        inner = rng.choice(("", " ", "  "))
        text = f"({inner}{text}{inner})" if rng.random() < 0.9 else rng.choice(("(", "")) + text + rng.choice((")", ""))
    if rng.random() < 0.3:
        text = rng.choice(SPACES) + text + rng.choice(SPACES + ("",))
    if rng.random() < 0.05:
        text = text.replace(rng.choice(text) if text else "", rng.choice("aZ("), 1)
    return text


def legend_line(rng: random.Random, chord_names: list[str]) -> str:
    """A line of a chord legend, or nearly."""
    parts = []
    for n in range(rng.choice((1, 1, 1, 2, 3))):
        if n:
            parts.append(rng.choice(("  ", " ", " | ", "; ", "|", ";", "\t", "   ")))
        name = rng.choice(chord_names) if rng.random() < 0.92 else rng.choice(("H", "x", "Cfoo", "N.C.", ""))
        parts.append(name + rng.choice(("", " ", "   ", ": ", " = ", " - ", "-", "=", ":", "\t")))
        parts.append(fingering_text(rng))
    line = "".join(parts)
    if rng.random() < 0.1:
        line += rng.choice((" in the chorus", " (x2)", " G", "  ", "|"))
    if rng.random() < 0.15:
        line = rng.choice(SPACES) + line
    return line


def define_value(rng: random.Random, chord_names: list[str]) -> str:
    """A ``{define}``'s value, or nearly."""
    name = rng.choice(chord_names) if rng.random() < 0.9 else rng.choice(("H", "Cfoo", "", "x"))
    values = ("-1", "x", "X", "n", "N", "0", "1", "2", "3", "4", "5", "7", "9", "10", "12", "03", "٣", "x1")
    parts = []
    if rng.random() < 0.6:
        parts.append(f"base-fret {_digit(rng, rng.choice((0, 1, 1, 2, 3, 5, 7, 9, 12)))}")
    if rng.random() < 0.92:
        count = rng.choice((6, 6, 6, 6, 5, 7))
        parts.append("frets " + " ".join(rng.choice(values) for _ in range(count)))
    if rng.random() < 0.4:
        fingers = ("0", "1", "2", "3", "4", "-", "x", "10", "T", "5")
        parts.append("fingers " + " ".join(rng.choice(fingers) for _ in range(rng.choice((6, 6, 5, 7)))))
    if rng.random() < 0.08:
        parts.append(rng.choice(("keys 0 4 7", "copy D", "display C")))
    rng.shuffle(parts)
    sep = rng.choice((" ", " ", "  ", "\t"))
    return rng.choice(("", " ")) + sep.join([name] + parts) + rng.choice(("", " ", "  "))


@functools.cache
def chords_db_positions() -> tuple[tuple[str, int, tuple], ...]:
    """Every position of chords-db's guitar data: (its key, its root, the position)."""
    out = []
    for key, roots in voicings.load_voicings().items():
        for root, positions in enumerate(roots):
            out += [(key, root, tuple(p)) for p in positions]
    return tuple(out)


def _chord_of_key(key: str, root: int) -> Chord:
    quality, _, interval = key.partition("/")
    return Chord(root, quality, None if not interval else (root + int(interval)) % 12)


@functools.cache
def sheets() -> tuple:
    """Each corpus sheet read, with its key as its page has it: (corpus sheet, sheet, key)."""
    out = []
    for s in viewer_corpus.sheets():
        sheet, key, _, _ = page._read_song(s.cho, s.key, s.key_source, 0)
        out.append((s, sheet, key))
    return tuple(out)


# --- voicings ------------------------------------------------------------------------------------------------------


def _given(given: list[tuple[Chord, list]]) -> list[list]:
    return [[chord_row(c), p] for c, p in given]


def voicings_records() -> list[dict]:
    rng = random.Random(SEED)
    chord_names = list(names())
    texts = list(dict.fromkeys(list(literals()) + [fingering_text(rng) for _ in range(400)]))
    out = [{"fn": HELPER + "fingerings_of", "args": [b], "out": [answer(voicings.parse_fingering, t) for t in b]}
           for b in _batches(texts)]

    lines: dict[str, None] = dict.fromkeys(literals())
    for s, sheet, _ in sheets():
        for line in s.cho.split("\n"):
            if voicings.chord_legend(line) or rng.random() < 0.05:
                lines[line] = None
    lines.update(dict.fromkeys(legend_line(rng, chord_names) for _ in range(300)))
    out += [{"fn": HELPER + "legends_of", "args": [b],
             "out": [_given(voicings.chord_legend(line)) for line in b]} for b in _batches(list(lines))]

    values: dict[str, None] = dict.fromkeys(literals())
    for _, sheet, _ in sheets():
        values.update(dict.fromkeys(sheet.defines))
    values.update(dict.fromkeys(define_value(rng, chord_names) for _ in range(300)))

    def define(value: str) -> Any:
        found = answer(voicings.parse_define, value)
        return found if found is None or isinstance(found, dict) else [chord_row(found[0]), found[1]]

    out += [{"fn": HELPER + "defines_of", "args": [b], "out": [define(v) for v in b]} for b in _batches(list(values))]

    def keys(name: str) -> list | None:
        chord = parse_chord(name, strict=False)
        return None if chord is None else [*voicings.voicing_keys(chord), voicings.shape_key(chord),
                                           instruments.piano_key(chord)]

    out += [{"fn": HELPER + "keys_of", "args": [b], "out": [keys(n) for n in b]} for b in _batches(chord_names)]

    positions = [list(p) for _, _, p in rng.sample(chords_db_positions(), 100)]
    positions += [p for p in (voicings.parse_fingering(fingering_text(rng)) for _ in range(60)) if p]
    found_defines = [voicings.parse_define(v) for v in values]
    positions += [d[1] for d in found_defines if d]
    uke = [list(p) for roots in voicings.load_voicings("ukulele").values() for ps in roots for p in ps]
    tunings = [list(i.tuning) for i in instruments.INSTRUMENTS if i.tuning]
    items = [[p, list(voicings.TUNING)] for p in positions]
    items += [[p, rng.choice(tunings[1:])] for p in rng.sample(uke, 40)]
    items += [[p, rng.choice(tunings)] for p in rng.sample(positions, 30)]  # some of another length: an error
    out += [{"fn": HELPER + "positions_of", "args": [b],
             "out": [answer(lambda p, t: [voicings.notes_of(p, tuple(t)), list(voicings.frets_from_nut(p))], *i)
                     for i in b]} for b in _batches(items)]

    pairs = []
    for key, root, p in rng.sample(chords_db_positions(), 150):
        pairs.append([list(p), chord_row(_chord_of_key(key, root)), list(voicings.TUNING)])
    for p in rng.sample(positions, 150):
        pairs.append([p, chord_row(parse_chord(rng.choice(chord_names), strict=False)), list(voicings.TUNING)])
    pairs = [p for p in pairs if p[1] is not None]
    pairs += [[p, chord_row(Chord(rng.randrange(12), rng.choice(("", "m", "7")))), t]
              for p, t in rng.sample(items[-110:-30], 40)]

    def plays(position, row, tuning):
        return voicings.plays(position, Chord(*row[:4], frozenset(row[4]) if len(row) > 4 else None), tuple(tuning))

    out += [{"fn": HELPER + "plays_of", "args": [b], "out": [answer(plays, *item) for item in b]}
            for b in _batches(pairs)]

    givens: list[tuple[list, list[str]]] = []
    for _, sheet, _ in sheets():
        given = page._given_shapes(sheet)
        if given:
            givens.append((given, list(sheet.chords)))
    for _ in range(30):
        given = []
        for _ in range(rng.randint(1, 6)):
            if rng.random() < 0.5:
                key, root, p = rng.choice(chords_db_positions())
                chord = _chord_of_key(key, root)
                p = list(p)
                if rng.random() < 0.5:
                    p = [p[0], "000000", p[2], []]
                if rng.random() < 0.3:  # the same frets from another base fret
                    nut = voicings.frets_from_nut(p)
                    held = [f for f in nut if f]
                    if held and min(held) > 1:
                        base = min(held) - 1
                        p = ["".join("x" if f is None else "0" if f == 0 else str(f - base + 1) for f in nut),
                             p[1], base, []]
            else:
                chord = parse_chord(rng.choice(chord_names), strict=False)
                p = voicings.parse_fingering(fingering_text(rng))
            if chord is not None and p is not None:
                given.append((chord, p))
            if given and rng.random() < 0.2:
                given.append(rng.choice(given))  # given twice
        givens.append((given, rng.sample(chord_names, 3) + [chord_name_of(c) for c, _ in given]))
    for given, sheet_names in givens:
        shift = rng.randrange(12) if rng.random() < 0.5 else 0
        shapes = voicings.sheet_shapes(given)
        guitar = []
        shown = {chord_name_of(c) for c, _ in given}
        sheet_names = [n for n in sheet_names if n in shown or rng.random() < 0.15]
        for name in sheet_names:
            chord = parse_chord(name, strict=False)
            guitar.append(None if chord is None else instruments.chord_shapes(instruments.GUITAR, chord, shift, shapes))
        out.append({"fn": HELPER + "sheet_shapes_of", "args": [_given(given), sheet_names, shift],
                    "out": {"shapes": kept(shapes), "guitar": guitar}})

    data = voicings.load_voicings()
    every = sorted(data)
    for _ in range(25):
        keys_asked = sorted(rng.sample(every, rng.randint(0, 12)) + rng.sample(("maj13", "foo", "m/3"), 1))
        found = voicings.page_voicings(set(keys_asked))
        out.append({"fn": HELPER + "page_voicings_of", "args": [keys_asked],
                    "out": {"keys": list(found), "sha256": sha256(found)}})
    return out


def chord_name_of(chord: Chord) -> str:
    """A chord's name as the viewer writes it with sharps: its root, its suffix, its bass."""
    names = spelling(None)
    return names[chord.root] + chord.suffix + ("" if chord.bass is None else "/" + names[chord.bass])


def test_voicings_vectors_are_voicings_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "voicings.jsonl",
          jsonl(voicings_records(), corpus="viewer/voicings", made_by=MADE_BY))


# --- instruments ---------------------------------------------------------------------------------------------------


def _row_chord(row: list) -> Chord:
    return Chord(*row[:4], frozenset(row[4]) if len(row) > 4 else None)


def instruments_records() -> list[dict]:
    rng = random.Random(SEED + 1)
    asked = [i.id for i in instruments.INSTRUMENTS] + [None, "", "banjo", "Guitar", "PIANO", " piano"]
    out = [{"fn": HELPER + "instrument_of", "args": [asked], "out": [instruments.instrument(n).id for n in asked]}]
    for table in instruments.EASY:
        out.append({"fn": "caracole.viewer.instruments.easy_keys", "args": [table],
                    "out": kept(instruments.easy_keys(table))})
        out.append({"fn": HELPER + "is_easy_of", "args": [table, [key_row(k) for k in viewer_corpus.keys()]],
                    "out": [instruments.is_easy(table, k) for k in viewer_corpus.keys()]})
    fingerings = sorted(set(voicings.load_voicings()) | set(QUALITIES) | {"foo", "m/3", "maj13"})
    out.append({"fn": HELPER + "ukulele_quality_of", "args": [fingerings],
                "out": [answer(instruments.ukulele_quality, f) for f in fingerings]})

    for name in kinds():
        chord = parse_chord(name, strict=False)
        shift = rng.randrange(12)
        root = rng.randrange(12)
        on = [i for i in instruments.INSTRUMENTS if rng.random() < SHAPES_ON]
        out.append({"fn": HELPER + "chord_of", "args": [name, shift], "out": {
            "chord": chord_row(chord),
            "stacked": instruments.stacked(chord),
            "piano": instruments.piano_positions(chord),
            "piano_key": instruments.piano_key(chord),
            "on_root": [root, chord_row(instruments.on_root(chord, root))],
            "shapes": {i.id: instruments.chord_shapes(i, chord, shift) for i in on},
        }})

    for s, sheet, key in sheets()[::3]:
        chords = [c for c in (parse_chord(n, strict=False) for n in sheet.chords) if c is not None]
        if key is not None:
            chords += [map_chord(c, key, rng.choice(MODES)) for c in chords]
        needed: set[str] = set()
        kinds_of: dict[str, Chord] = {}
        for c in chords:
            kinds_of.setdefault(instruments.piano_key(c), c)
            fingering, _, slash = voicings.voicing_keys(c)
            needed.add(fingering)
            if slash:
                needed.add(slash)
        fingerings_asked = sorted(needed)
        page_chords = list(kinds_of.values())
        guitar = voicings.page_voicings(needed)
        more = instruments.page_voicings(needed, page_chords)
        entries = instruments.entries(needed)
        out.append({"fn": HELPER + "page_of", "args": [fingerings_asked, [chord_row(c) for c in page_chords]],
                    "out": {"voicings": [list(guitar), sha256(guitar)], "instruments": [list(more), sha256(more)],
                            "entries": sha256(entries), "near": entries[1]["near"]}})
    out.append({"fn": "caracole.viewer.instruments.entries", "args": [[]], "out": kept(instruments.entries(set()))})
    return out


def test_instruments_vectors_are_instruments_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "instruments.jsonl",
          jsonl(instruments_records(), corpus="viewer/instruments", made_by=MADE_BY))


# --- the harmonica -------------------------------------------------------------------------------------------------


def _every_quality_on_c() -> list[Chord]:
    return [Chord(0, q, bass) for q in QUALITIES for bass in (None, *range(12))]


def harp_play_records() -> list[dict]:
    rng = random.Random(SEED + 2)
    chords = [c for c in _every_quality_on_c() if c.bass is None or rng.random() < 0.3]
    chords += [parse_chord(n, strict=False) for n in kinds()]
    out = [{"fn": HELPER + "play_of", "args": [[chord_row(c) for c in b]],
            "out": [[harp.entry(harp.play(c, h)) for h in range(12)] for c in b]} for b in _batches(chords)]
    keys = viewer_corpus.keys()
    items = []
    for c in chords:
        if c.bass is None or rng.random() < 0.1:
            items.append([chord_row(c), rng.randrange(12), key_row(rng.choice(keys + [None]))])
    out += [{"fn": HELPER + "texts_of", "args": [b],
             "out": [harp.play(_row_chord(c), h).text(spelling(None if k is None else Key(*k))) for c, h, k in b]}
            for b in _batches(items)]
    steps = [[chord_row(c), rng.randrange(12)] for c in chords if c.bass is None or rng.random() < 0.1]
    out += [{"fn": HELPER + "steps_of", "args": [b], "out": [harp.chord_steps(_row_chord(c), t) for c, t in b]}
            for b in _batches(steps)]
    return out


def test_harp_play_vectors_are_harp_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "harp_play.jsonl",
          jsonl(harp_play_records(), corpus="viewer/harp_play", made_by=MADE_BY))


def _choice_row(c: harp.HarpChoice) -> list:
    return [c.position, c.harp, c.mode, c.fit, c.chords, c.plays, c.substitutes]


def choices_of(chord_names: list[str], key: Key) -> dict:
    """What the harps for a song are chosen by: each candidate's ranking, the choices, the header line."""
    chords = [parse_chord(n, strict=False) for n in chord_names]
    distinct: dict[tuple, Chord] = {}
    for chord in chords:
        if chord is not None:
            distinct.setdefault((chord.root, chord.intervals, chord.bass), chord)
    ranked = []
    for order, position in enumerate(harp.candidates(key)):
        h = harp.harp_for(key.tonic, position)
        fit, plays, substitutes = 0.0, 0, 0
        for chord in distinct.values():
            kind = harp.play(chord, h).kind
            fit += harp.CHORD_FIT[kind] * (harp.TONIC_WEIGHT if chord.root == key.tonic else 1)
            plays += kind in ("yes", "part")
            substitutes += kind == "minor"
        choice = harp.HarpChoice(position, h, harp.position_mode(position), fit, len(distinct), plays, substitutes)
        ranked.append(list(harp.ranking(key, order, choice)))
    found = harp.choices(key, chords)
    return {"candidates": harp.candidates(key), "ranking": ranked, "choices": [_choice_row(c) for c in found],
            "header": harp.header_line(key, chords)}


def harp_choices_records() -> list[dict]:
    rng = random.Random(SEED + 3)
    inputs = []
    for s, sheet, key in sheets():
        key = key or rng.choice(viewer_corpus.keys())
        inputs.append((list(sheet.chords), key if rng.random() < 0.6 else Key(key.tonic, rng.choice(MODES))))
    for p in viewer_corpus.progressions():
        inputs.append((list(p.chords), p.key))
        if rng.random() < 0.5:
            inputs.append((list(p.chords), Key(rng.randrange(12), rng.choice(MODES))))
    out = [{"fn": HELPER + "choices_of", "args": [n, key_row(k)], "out": choices_of(n, k)} for n, k in inputs]
    out += [{"fn": "caracole.viewer.harp.candidates", "args": [key_row(k)], "out": harp.candidates(k)}
            for k in viewer_corpus.keys()]
    return out


def test_harp_choices_vectors_are_harp_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "harp_choices.jsonl",
          jsonl(harp_choices_records(), corpus="viewer/harp_choices", made_by=MADE_BY))


def mapped_and_alts(chord_names: list[str], key: Key) -> tuple[list, dict, dict]:
    """A sheet's chords as page.py reads them, and in each mode of ``key`` with their alternatives."""
    chords = [parse_chord(n, strict=False) for n in chord_names]
    mapped: dict[str, list] = {}
    alts: dict[str, list] = {}
    for mode in MODES:
        mapped[mode] = [None if c is None else map_chord(c, key, mode) for c in chords]
        alts[mode] = [[] if c is None else alternatives(c, Key(key.tonic, mode)) for c in mapped[mode]]
    return chords, mapped, alts


def harp_tables_records() -> list[dict]:
    out = []
    whole = 0
    for s, sheet, key in sheets()[::4]:
        if key is None:
            continue
        _, mapped, alts = mapped_and_alts(list(sheet.chords), key)
        tables = harp.tables(key, mapped, alts)
        record = {"order": list(tables), "sha256": {k: sha256(v) for k, v in tables.items()}}
        if whole < WHOLE_TABLES:
            record["whole"] = kept(tables)
            whole += 1
        out.append({"fn": HELPER + "tables_of", "args": [list(sheet.chords), key_row(key)], "out": record})
    out.append({"fn": "caracole.viewer.harp.tables", "args": [None, {}], "out": harp.tables(None, {})})
    one = list(viewer_corpus.sheets()[0].played[:4])
    _, mapped, _ = mapped_and_alts(one, Key(9, "aeolian"))
    for modes in (["aeolian"], ["ionian", "dorian"]):
        tables = harp.tables(Key(9, "aeolian"), {m: mapped[m] for m in modes})
        out.append({"fn": HELPER + "tables_in", "args": [one, [9, "aeolian"], modes], "out": kept(tables)})
    for h in range(12):
        lay = harp.layout(h)
        out.append({"fn": HELPER + "layout_of", "args": [h], "out": {
            "name": lay.name, "blow": list(lay.blow), "draw": list(lay.draw), "bend_breath": list(lay.bend_breath),
            "bends": [list(b) for b in lay.bends]}})
    out.append({"fn": "caracole.viewer.harp.ring", "args": [], "out": harp.ring()})
    out += [{"fn": "caracole.viewer.harp.holes", "args": [o], "out": kept(harp.holes(o))} for o in range(-1, 13)]
    out += [{"fn": "caracole.viewer.harp.key_scales", "args": [m], "out": harp.key_scales(m)} for m in MODES]
    out += [{"fn": HELPER + "outside_of", "args": [m], "out": [harp.outside(m, o) for o in range(12)]} for m in MODES]
    out.append({"fn": "caracole.viewer.harp.layouts", "args": [], "out": harp.layouts()})
    out.append({"fn": "caracole.viewer.harp.hole_tables", "args": [], "out": kept(harp.hole_tables())})
    out += [{"fn": HELPER + "positions_of", "args": [p], "out": {
        "mode": harp.position_mode(p), "ordinal": harp.ordinal(p), "harp_for": [harp.harp_for(t, p) for t in range(12)]}}
        for p in range(1, 13)]
    out += [{"fn": HELPER + "position_text_of", "args": [t], "out": {
        "position_of": [harp.position_of(t, h) for h in range(12)],
        "text": [harp.position_text(t, h) for h in range(12)]}} for t in range(12)]
    for h in range(12):
        notes = []
        for hole, breath, bend, over in itertools.product(range(12), ("blow", "draw", "suck"), range(-1, 5),
                                                          (False, True)):
            notes.append(answer(harp.hole_note, h, hole, breath, bend, over))
        out.append({"fn": HELPER + "hole_notes_of", "args": [h], "out": notes})
    items = [[None, "C"], [["yes", "draw", 2, 5], "G"], [["part", "blow", 1, 3, ""], "C"],
             [["minor", "draw", 4, 6, "m"], "D"], [["part", "draw", 1, 2, "5"], "F♯"]]
    out.append({"fn": HELPER + "entry_text_of", "args": [items], "out": [harp.entry_text(f, r) for f, r in items]})
    return out


def test_harp_tables_vectors_are_harp_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "harp_tables.jsonl",
          jsonl(harp_tables_records(), corpus="viewer/harp_tables", made_by=MADE_BY))


# --- the winds -----------------------------------------------------------------------------------------------------


def winds_records() -> list[dict]:
    rng = random.Random(SEED + 4)
    out = []
    for wind in winds.WINDS.values():
        for system in (None, *wind.systems, "boehm" if wind.name == "recorder" else "german"):
            try:
                found = [[[f.chart, f.text] for f in winds.fingerings(wind, n, system=system)] for n in NOTES]
            except ValueError:
                found = {"err": "ValueError"}
            out.append({"fn": HELPER + "fingerings_of", "args": [wind.name, system], "out": found})
    melodies = [[], [60], [55, 76], [48, 64], [96, 100], [30, 110], [79, 91]]
    for _ in range(80):
        low = rng.randint(20, 100)
        melodies.append(sorted(rng.randint(low, low + rng.choice((5, 12, 19, 30, 45))) for _ in range(rng.randint(1, 8))))
    for notes in melodies:
        for wind in winds.WINDS.values():
            fit = winds.fit(notes, wind)
            out.append({"fn": HELPER + "fit_of", "args": [notes, wind.name],
                        "out": [fit.shift, list(fit.written), list(fit.outside)]})
    out += [{"fn": "caracole.viewer.winds.scale_notes", "args": [key_row(k)], "out": winds.scale_notes(k)}
            for k in viewer_corpus.keys()]
    chords = [c for c in _every_quality_on_c() if c.bass is None] + [parse_chord(n, strict=False) for n in kinds()]
    chords = [c if rng.random() < 0.5 else instruments.on_root(c, rng.randrange(12)) for c in chords]
    out += [{"fn": HELPER + "steps_of", "args": [[chord_row(c) for c in b]],
             "out": [[winds.chord_steps(c), winds.chord_notes(c)] for c in b]} for b in _batches(chords)]
    sets = [[0, *s] for n in range(12) for s in itertools.combinations(range(1, 12), n)]
    items = [[s, None] for s in sets] + [[s, rng.randrange(12)] for s in rng.sample(sets, 100)]
    out += [{"fn": HELPER + "interval_steps_of", "args": [b],
             "out": [winds.chord_steps(Chord(0, "x", b_, None, frozenset(s))) for s, b_ in b]}
            for b in [items[i:i + 4 * BATCH] for i in range(0, len(items), 4 * BATCH)]]
    asked = list(winds._LETTERS) + spelling(Key(3, "ionian")) + ["Ebb", "B#", "Fbb", "C♯", "Sol", "G", "H", "", "c"]
    out.append({"fn": HELPER + "solfege_of", "args": [asked], "out": [answer(winds.solfege, n) for n in asked]})
    out.append({"fn": "caracole.viewer.winds.fingering_data", "args": [], "out": kept(winds.fingering_data())})
    for n, (s, sheet, key) in enumerate(sheets()):
        if n % 4 and key is not None:
            continue
        chords, mapped, alts = mapped_and_alts(list(sheet.chords), key or Key(0, "ionian"))
        out.append({"fn": HELPER + "tables_of", "args": [list(sheet.chords), key_row(key)],
                    "out": kept(winds.tables(chords, key, mapped, alts))})
    return out


def test_winds_vectors_are_winds_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "winds.jsonl", jsonl(winds_records(), corpus="viewer/winds", made_by=MADE_BY))
