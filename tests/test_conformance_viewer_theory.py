"""viewer/theory.py for the phone: its constants as data, and what it answers, for :viewer's viewer.theory; and the
stylesheets and scripts each kind of page inlines, for viewer.ViewerAssets.

The logic is Kotlin's (viewer.theory.Theory); everything theory.py states as data is written here, from the module
itself, so a change to a table or a pattern regenerates what the phone reads and the phone follows it.

The data, ``tests/conformance/data/caracole/viewer/theory.json`` (caracole/viewer/theory.json on the phone's
classpath, ``ViewerData.table("theory")``; ``viewer_corpus.data_json``), each member a constant of theory.py under
its own name, a dict's members in its order, a set as a sorted array:

- ``QUALITIES``: ``{name: [interval, …]}``; ``DISPLAY``, ``_NATURAL``, ``_ACCIDENTAL``, ``_ADDED``, ``_ALTERED``,
  ``_MODE_WORDS``: objects as they are; ``_THIRDS``: its keys as strings;
- ``_LETTERS``: a string; ``SHARPS``, ``FLATS``, ``_DEFAULT_SPELLING``, ``_MAJOR_TONICS``, ``MODES``, ``_COLOURS``,
  ``_STAND_INS``, ``_SYMMETRIC``: arrays; ``SCALES`` and ``_DEGREES``: ``{name: [steps]}``; ``_OPEN``: ``{mode:
  [tonic, …]}``; ``_OPEN_NOTES``: an array; ``MAX_CAPO``: a number;
- ``_RARE``: ``[[letter, accidental, spelled], …]`` in its order;
- ``_REWRITES``: ``[[pattern, replacement], …]`` in order, each replacement a template whose only escapes are
  ``\\1`` to ``\\9`` (a group), never followed by another digit (``_template``: ``\\0``, ``\\10`` or ``\\g<…>``
  fails generation, as Kotlin's ``Theory.expand`` would read them otherwise); ``patterns``: ``_ROOT``,
  ``_BASS``, ``_EXTENSION``, ``_SUS``, ``_ALTERATION``, ``_KEY``, as Python writes them (``.pattern``). None has
  a flag: their inline ones (``(?i:…)``) are Python's syntax, which core.py.PyRegex reads as Python does.

The vectors (``helpers.corpus.jsonl``), ``vectors/viewer/theory.jsonl``. A chord is ``[root, quality, bass, shown,
tones]`` with its trailing nulls left out (``tones`` its intervals sorted, for a chord outside QUALITIES); a key
``[tonic, mode]``. Each record is one of:

- ``parsed_of(names)``: for each of a batch of ``BATCH`` names, ``[parse_chord(name), parse_chord(name,
  strict=False)]``, the second left out where it is the first. The names are ``viewer_corpus.chord_names()`` and
  every string literal of tests/test_viewer_theory.py that starts with a letter A to G or holds a chord
  (``LITERALS_FROM``).
- ``chord_in(name, key, limit)``: for ``SHAPE_NAMES`` names of each shape of chord (its quality, its bass above its
  root and its tones; one more where a name writes its suffix otherwise than the viewer shows it), the loose chord of ``name`` and in ``key``,
  a seeded key: ``{"chord": …, "parts": [its intervals sorted, its pitch classes sorted, its suffix], "map":
  [map_chord(chord, key, mode) for each of MODES], "alternatives": alternatives(chord, key)}``, and with ``limit``
  (for one in five) ``"limited": alternatives(chord, key, limit)``.
- ``key_of(tonic, mode)``: ``spelling``, ``key_name``, ``scale`` (sorted), ``capo_hints`` as ``[[capo, limit,
  hints], …]`` (capos 0 to 7 at the default limit, then 0 at limits 0, 1 and 9), ``sounding`` on capos 0, 2, 5, 7,
  11 and 12, for every key of ``viewer_corpus.keys()``; ``caracole.viewer.theory.spelling`` of None.
- ``edge_of(tonic, mode)``: what Python's negative indexes, slices and modulo answer, for each key of
  ``EDGE_KEYS`` (a tonic below 0): ``{"key_of": key_of(key), "hints": [[capo, limit, hints], …] (capo_hints on
  capos 0 and ``EDGE_CAPOS``, at limits 2 and ``EDGE_LIMITS``), "sounding": [[capo, key], …], "shapes": [[capo,
  shapes_key(key, capo, played), bare_key(Key(tonic, "ionian"), capo, played)], …]}`` on ``EDGE_CAPOS``, where
  ``played`` is the one triad on the tonic of the key a capo lowers (``_diatonic_quality``), so a tab that names the
  sound is read so.
- ``parsed_keys(texts)``: ``parse_key`` of each of a batch of texts: every text of ``viewer_corpus.key_texts()``
  and each literal above, and 42 and None (no text).
- ``played_of(names, capos, texts)``: the chords a sheet plays (``names``, read as page.py reads them,
  ``parse_chord(name, strict=False)`` with those it reads as none left out): ``{"estimate": estimate_key(played),
  "named": [[named_key(text, capo, played), bare_key(parse_key(text), capo, played), shapes_key(named_key(…) or
  parse_key(text), capo, played)] for each capo, for each text]}``, null where ``parse_key(text)`` is None; for every
  sheet of ``viewer_corpus.sheets()`` and every progression of ``viewer_corpus.progressions()``, capos 0 and the
  sheet's own (else a seeded one), texts the key the sheet names (else a seeded letter alone), a seeded letter
  minor and one in a seeded mode.

``vectors/viewer/theory_assets.jsonl``: ``page_assets(kind)`` for each kind of page (``sheet``, ``songbook``,
``harmonica``): ``{"styles": [file, …], "scripts": [file, …]}``, the stylesheets and scripts its page inlines in
their order, read back from a page built (page.build_viewer, book.build_songbook,
harptab_page.build_harmonica_viewer) by the hashes its policy allows them by.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_theory.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import ast
import functools
import json
import random
import re
from pathlib import Path

from caracole.inline import sha256_source
from caracole.viewer import book, harptab_page, page, theory
from caracole.viewer.theory import MODES, Chord, Key
from helpers import viewer_corpus
from helpers.corpus import check, jsonl

MADE_BY = "tests/test_conformance_viewer_theory.py"
HELPER = "test_conformance_viewer_theory."
T = "caracole.viewer.theory."
TESTS = Path(__file__).resolve().parent
VIEWER = Path(theory.__file__).resolve().parent
LITERALS_FROM = ("test_viewer_theory.py",)
SEED = viewer_corpus.SEED + 100
PATTERNS = ("_ROOT", "_BASS", "_EXTENSION", "_SUS", "_ALTERATION", "_KEY")
LIMITS = (0, 1, 2, 3, 5, 12)
CAPOS = (1, 2, 3, 4, 5, 7, 9, 12, 14)
SOUNDING = (0, 2, 5, 7, 11, 12)
BATCH = 50
SHAPE_NAMES = 2
EDGE_KEYS = (Key(-1, "ionian"), Key(-5, "aeolian"), Key(-12, "lydian"), Key(-7, "dorian"))
EDGE_LIMITS = (-1, -2, -13)
EDGE_CAPOS = (-1, -2, -12, -14)


# --- the data ------------------------------------------------------------------------------------------------------


def _pattern(p: re.Pattern[str]) -> str:
    assert p.flags & ~re.UNICODE == 0, f"{p.pattern!r}: a flag the phone doesn't read"
    return p.pattern


def _template(replacement: str) -> str:
    escapes = r"(?:[^\\]|\\[1-9](?!\d))*"  # a group's \1 to \9, no other escape
    assert re.fullmatch(escapes, replacement), f"{replacement!r}: an escape the phone doesn't expand"
    return replacement


def constants() -> dict:
    return {
        "QUALITIES": {name: sorted(intervals) for name, intervals in theory.QUALITIES.items()},
        "DISPLAY": dict(theory.DISPLAY),
        "_NATURAL": dict(theory._NATURAL),
        "_LETTERS": theory._LETTERS,
        "SHARPS": list(theory.SHARPS),
        "FLATS": list(theory.FLATS),
        "_ACCIDENTAL": dict(theory._ACCIDENTAL),
        "_REWRITES": [[_pattern(p), _template(r)] for p, r in theory._REWRITES],
        "patterns": {name: _pattern(getattr(theory, name)) for name in PATTERNS},
        "_ADDED": dict(theory._ADDED),
        "_ALTERED": dict(theory._ALTERED),
        "MODES": list(theory.MODES),
        "SCALES": {mode: list(steps) for mode, steps in theory.SCALES.items()},
        "_MAJOR_TONICS": list(theory._MAJOR_TONICS),
        "_DEGREES": {name: list(degrees) for name, degrees in theory._DEGREES.items()},
        "_RARE": [[letter, accidental, spelled] for (letter, accidental), spelled in theory._RARE.items()],
        "_DEFAULT_SPELLING": list(theory._DEFAULT_SPELLING),
        "_MODE_WORDS": dict(theory._MODE_WORDS),
        "_COLOURS": list(theory._COLOURS),
        "_STAND_INS": list(theory._STAND_INS),
        "_THIRDS": {str(k): v for k, v in theory._THIRDS.items()},
        "_SYMMETRIC": list(theory._SYMMETRIC),
        "_OPEN": {mode: sorted(tonics) for mode, tonics in theory._OPEN.items()},
        "_OPEN_NOTES": sorted(theory._OPEN_NOTES),
        "MAX_CAPO": theory.MAX_CAPO,
    }


@functools.cache
def theory_json() -> str:
    return viewer_corpus.data_json(constants())


def test_theory_json_is_theory_pys_constants():
    check(viewer_corpus.VIEWER_DATA / "theory.json", theory_json())


def test_the_data_reads_back_as_theory_holds_it():
    data = json.loads(theory_json())
    assert {k: frozenset(v) for k, v in data["QUALITIES"].items()} == theory.QUALITIES
    assert list(data["QUALITIES"]) == list(theory.QUALITIES)
    assert [(re.compile(p), r) for p, r in data["_REWRITES"]] == theory._REWRITES
    for name, pattern in data["patterns"].items():
        assert re.compile(pattern) == getattr(theory, name)
    assert {(a, b): c for a, b, c in data["_RARE"]} == theory._RARE
    assert {int(k): v for k, v in data["_THIRDS"].items()} == theory._THIRDS
    assert {k: set(v) for k, v in data["_OPEN"].items()} == theory._OPEN


# --- the inputs ----------------------------------------------------------------------------------------------------


@functools.cache
def literals() -> tuple[str, ...]:
    found: dict[str, None] = {}
    for name in LITERALS_FROM:
        tree = ast.parse((TESTS / name).read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 24:
                text = node.value
                if text[:1] in "ABCDEFG" or text.strip()[:1] in "ABCDEFGabcdefg":
                    found[text] = None
    return tuple(sorted(s for s in found if not any(0xD800 <= ord(c) <= 0xDFFF for c in s)))


def chord_row(chord: Chord | None) -> list | None:
    if chord is None:
        return None
    row = [chord.root, chord.quality, chord.bass, chord.shown, None if chord.tones is None else sorted(chord.tones)]
    while row[-1] is None:
        row.pop()
    return row


def key_row(key: Key | None) -> list | None:
    return None if key is None else [key.tonic, key.mode]


# --- the vectors ---------------------------------------------------------------------------------------------------


def chord_in(name: str, key: Key, limit: int | None) -> dict:
    """The loose chord of ``name``, its parts, and in ``key`` map_chord to each mode and its alternatives (and with
    ``limit``)."""
    chord = theory.parse_chord(name, strict=False)
    out = {
        "chord": chord_row(chord),
        "parts": [sorted(chord.intervals), sorted(chord.pitch_classes), chord.suffix],
        "map": [chord_row(theory.map_chord(chord, key, mode)) for mode in MODES],
        "alternatives": [chord_row(c) for c in theory.alternatives(chord, key)],
    }
    if limit is not None:
        out["limited"] = [chord_row(c) for c in theory.alternatives(chord, key, limit)]
    return out


def parsed(name: str) -> list:
    strict = theory.parse_chord(name)
    loose = theory.parse_chord(name, strict=False)
    return [chord_row(strict)] if loose == strict else [chord_row(strict), chord_row(loose)]


def key_of(key: Key) -> dict:
    hints = [[capo, 2, theory.capo_hints(key, capo=capo)] for capo in range(8)]
    hints += [[0, limit, theory.capo_hints(key, limit)] for limit in (0, 1, 9)]
    return {
        "spelling": theory.spelling(key),
        "name": theory.key_name(key),
        "scale": sorted(theory.scale(key)),
        "capo_hints": [[capo, limit, [[fret, key_row(k)] for fret, k in found]] for capo, limit, found in hints],
        "sounding": [[capo, key_row(theory.sounding(key, capo))] for capo in SOUNDING],
    }


def edge_of(key: Key) -> dict:
    """``key_of`` a key whose tonic is below 0, and capo_hints, sounding, shapes_key and bare_key where a limit or a
    capo is below 0."""
    hints = [[capo, limit, theory.capo_hints(key, limit, capo=capo)] for capo in (0, *EDGE_CAPOS)
             for limit in (2, *EDGE_LIMITS)]
    shapes = []
    for capo in EDGE_CAPOS:
        lowered = Key((key.tonic - capo) % 12, key.mode)
        played = [Chord(lowered.tonic, theory._diatonic_quality(lowered.tonic, lowered, 3))]
        shapes.append([capo, key_row(theory.shapes_key(key, capo, played)),
                       key_row(theory.bare_key(Key(key.tonic, "ionian"), capo, played))])
    return {
        "key_of": key_of(key),
        "hints": [[capo, limit, [[fret, key_row(k)] for fret, k in found]] for capo, limit, found in hints],
        "sounding": [[capo, key_row(theory.sounding(key, capo))] for capo in EDGE_CAPOS],
        "shapes": shapes,
    }


def played_of(names: list[str], capos: list[int], texts: list[str]) -> dict:
    played = [c for c in (theory.parse_chord(n, strict=False) for n in names) if c is not None]
    named = []
    for capo in capos:
        for text in texts:
            parsed_key = theory.parse_key(text)
            if parsed_key is None:
                named.append(None)
                continue
            found = theory.named_key(text, capo, played)
            named.append([key_row(found), key_row(theory.bare_key(parsed_key, capo, played)),
                          key_row(theory.shapes_key(found or parsed_key, capo, played))])
    return {"estimate": key_row(theory.estimate_key(played)), "named": named}


def _batches(items: list) -> list[list]:
    return [items[i:i + BATCH] for i in range(0, len(items), BATCH)]


def _shape(chord: Chord) -> tuple:
    return chord.quality, None if chord.bass is None else (chord.bass - chord.root) % 12, chord.tones


def chord_records() -> list[dict]:
    names = list(dict.fromkeys(viewer_corpus.chord_names() + list(literals())))
    out = [{"fn": HELPER + "parsed_of", "args": [batch], "out": [parsed(n) for n in batch]} for batch in _batches(names)]
    rng = random.Random(SEED)
    keys = viewer_corpus.keys()
    shapes: dict[tuple, int] = {}
    for name in names:
        chord = theory.parse_chord(name, strict=False)
        if chord is None:
            continue
        shape = _shape(chord)
        wanted = SHAPE_NAMES + (chord.shown != theory.DISPLAY.get(chord.quality, chord.quality))
        if shapes.get(shape, 0) >= wanted:
            continue
        shapes[shape] = shapes.get(shape, 0) + 1
        key = rng.choice(keys)
        limit = rng.choice(LIMITS) if rng.random() < 0.2 else None
        out.append({"fn": HELPER + "chord_in", "args": [name, key_row(key), limit], "out": chord_in(name, key, limit)})
    return out


def key_records() -> list[dict]:
    out = [{"fn": HELPER + "key_of", "args": key_row(key), "out": key_of(key)} for key in viewer_corpus.keys()]
    out.append({"fn": T + "spelling", "args": [None], "out": theory.spelling(None)})
    out += [{"fn": HELPER + "edge_of", "args": key_row(key), "out": edge_of(key)} for key in EDGE_KEYS]
    texts = list(dict.fromkeys(viewer_corpus.key_texts() + list(literals()))) + [42, None]
    out += [{"fn": HELPER + "parsed_keys", "args": [batch], "out": [key_row(theory.parse_key(t)) for t in batch]}
            for batch in _batches(texts)]
    return out


def played_records() -> list[dict]:
    rng = random.Random(SEED + 1)
    out = []
    inputs = [(list(s.played), s.capo, s.key) for s in viewer_corpus.sheets()]
    inputs += [(list(p.chords), None, theory.key_name(p.key)) for p in viewer_corpus.progressions()]
    for names, capo, named in inputs:
        capos = [0, capo or rng.choice(CAPOS)]
        texts = [named or rng.choice(theory.SHARPS + theory.FLATS), rng.choice(theory.SHARPS + theory.FLATS) + "m",
                 f"{rng.choice(theory.FLATS)} {rng.choice(MODES)}"]
        out.append({"fn": HELPER + "played_of", "args": [names, capos, texts], "out": played_of(names, capos, texts)})
    return out


def test_theory_vectors_are_theory_pys_answers():
    records = chord_records() + key_records() + played_records()
    check(viewer_corpus.VIEWER_VECTORS / "theory.jsonl", jsonl(records, corpus="viewer/theory", made_by=MADE_BY))


# --- each page's assets --------------------------------------------------------------------------------------------

_SOURCES = re.compile(r"(script|style)-src ([^;]*);")


def page_assets(html: str) -> dict:
    """The stylesheets and scripts a page inlines, in order, by the hashes its policy allows them by."""
    by_source = {sha256_source(path.read_text(encoding="utf-8")): path.name
                 for path in sorted(VIEWER.iterdir()) if path.suffix in (".js", ".css")}
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', html).group(1)
    found = {kind: [by_source[s] for s in sources.split()] for kind, sources in _SOURCES.findall(policy)}
    return {"styles": found["style"], "scripts": found["script"]}


def pages() -> dict[str, str]:
    cho = viewer_corpus.sheet("fixture:chordpro/ug_sheet.cho").cho
    return {
        "sheet": page.build_viewer(cho),
        "songbook": book.build_songbook("Book", [book.BookSong("Title", "Artist", cho)]),
        "harmonica": harptab_page.build_harmonica_viewer("4 -4 5 -5 6", title="Title", tab_file="harmonica-1.txt"),
    }


def test_theory_assets_are_each_pages_stylesheets_and_scripts():
    records = [{"fn": HELPER + "page_assets", "args": [kind], "out": page_assets(html)} for kind, html in pages().items()]
    check(viewer_corpus.VIEWER_VECTORS / "theory_assets.jsonl",
          jsonl(records, corpus="viewer/theory_assets", made_by=MADE_BY))
