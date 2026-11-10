"""viewer/version.py's page side and progressions.py for the phone: their constants as data, and what they answer, for
:viewer's viewer.version (``Versions``, ``KeyVersion``) and viewer.progressions (``Progressions``).

The logic is Kotlin's; what the modules state as data is written here from the modules themselves, so a change to a
pattern, a word list or a name regenerates what the phone reads and the phone follows it. What they say in a sentence
(``setting_problem``'s and ``key_version``'s words, a version's label) is their code, and Kotlin's: every word is
compared below. ``apply_version`` (a sheet's ChordPro rewritten for chordpro's PDF of a version) is the computer's
alone, and has no record.

**The data**, ``tests/conformance/data/caracole/viewer/version.json`` (``ViewerData.table("version")``;
``viewer_corpus.data_json``), one member a module:

- ``version``: ``patterns`` (``_DIGITS``, ``_INDEX``, ``_NUMBER``, ``_BAD_ESCAPE``, ``_TONIC``, ``_ESCAPED``,
  ``_KEY_NAME``, each ``{"pattern", "ignorecase"}`` as Python writes it, which core.py.PyRegex reads as Python does),
  ``MODE_NAMES``, ``_SAID``, ``CAPO_MAX`` and ``_FORM_SAFE`` (its bytes as characters, sorted);
- ``progressions``: ``KV``, ``UNNAMED``, ``patterns`` (``_TYPED``, ``_SEPARATORS``, ``_WORD``, ``_APOSTROPHES``),
  ``_GENERIC``, ``_SAYS_PROGRESSION``, ``_NOT_ALONE`` and ``_TITLES`` (sorted: a set has no order) and
  ``_NAME_LETTERS``.

**The vectors** (``helpers.corpus.jsonl``), in the viewer area, which is nearly full: so a batch's answers are kept
whole where a hand case or a literal of tests/test_viewer_version.py and tests/test_progressions.py asks them, and
otherwise by their **digest**, the first 16 hex digits of the SHA-256 of ``json.dumps(answers, ensure_ascii=False,
separators=(",", ":"))`` (Kotlin's ``PyJson.dumps(compact = true)`` writes the same bytes), one digest an item of the
first argument, so a mismatch names what is at fault. A key is ``[tonic, mode]`` or null; a version is its address as
``version_query`` writes it (it says all a version holds, every map in order), or the row ``[t, mode, capo, at, alt,
inst]`` with ``at`` ``[[index, shape], …]`` and ``alt`` ``[[mode, [[index, root, suffix, bass], …]], …]`` in the order
the dicts hold them; a setting ``[key, mode, capo, instrument]`` or null; a sheet ``[cho, key, capo]``, its ``cho`` a
text or a fixture's reference (``{"fixture": "chordpro/ug_sheet.cho"}``), its key and capo as its viewer reads them
(``page.viewer_key`` with the song's key and its source, ``parse_sheet(cho).capo``). Raised is ``{"error": str(e)}``.

``vectors/viewer/version.jsonl``, each record one of:

- ``from_query_of(queries)``: ``version_query(version_from_query(q))``, whole, and for the literals of
  tests/test_viewer_version.py (``TEST_QUERIES``) ``[version row, version_query]``; then ``EDGE_QUERIES`` (JavaScript's
  Number(), escapes that decode and don't, a name given twice, a name escaped) and ``QUERIES`` seeded ones.
- ``instruments_of(names)``: ``{"ids": instrument_ids(), "rows": [[instrument_of(n)'s id, _inst_of(n), played_on's id,
  instrument_words(played_on), version_query(for_instrument(Version(t=1, capo=3, inst=n), played_on))], …]}``.
- ``labels_of(items)``: each ``[query, key, capo_sheet]`` → ``[played_key's key, its capo, version_label,
  played_label]``, whole; ``labels_product(queries, keys, capos)``: those answers for every key and capo of each query,
  in that order, a digest a query.
- ``setting_problems_of(items)``: each ``[key, mode, capo, instrument]`` (any JSON value) → ``setting_problem``.
- ``in_setting_of(items)``: each ``[own, setting, shapes, capo_sheet]`` → the version, whole; ``in_setting_product(owns,
  settings, keys, capos)``: every setting, key and capo of each own version, a digest an own.
- ``key_versions_of(texts)``: each → ``{"kept": [key, mode, capo, alt, at, inst], "query": kept.query(), "label":
  kept.label()}``, null for none, or raised.
- ``kept_of(sheets, inputs)``: the versions kept by their key, its sheets written once, ``inputs`` and the answer
  objects by member: ``entries_hand`` (each ``[version, sheet]`` → ``version_entry``, whole, the tests'), ``entries``
  (``version_entry`` of every version of ``entry_versions`` and of the sheet's own, ``own[i]``: versions with swaps and
  shapes drawn from its chords, on each sheet, a digest a sheet), ``in_key_hand`` (each ``[entry, sheet]`` →
  ``version_query(in_key(key_version(entry), cho, key, capo))``, whole, the tests' ``kept_on``), ``in_key`` (every entry
  of ``in_key`` on each sheet, a digest a sheet: the tests' entries, those ``version_entry`` writes on the hand sheets
  and ``SEEDED_ENTRIES`` drawn ones) and ``own_versions`` (each ``[entry, transpose, sheet, song key, key source]`` →
  ``version_query`` of ``render.own_version``, an overrides.toml whose ``[version]`` and ``[transpose]`` hold the entry
  and the transpose for the song, or raised).

``vectors/viewer/progressions.jsonl``, each record one of:

- ``sheet_progressions_of(whole, more)``: each ``[cho, key, key source]`` → the kv text ``record`` writes
  (``json.dumps(sheet_progressions(…), ensure_ascii=False)``), null for none: ``{"whole": […], "digests": […]}``, the
  tests' sheets whole, then the fixtures' and the edges' a digest each; ``sheet_progressions_digests(sheets,
  variants)``: those of each sheet in each ``[key, key source]``, a digest a sheet, for ``SHEETS`` drawn ones (the
  catalogue's progressions in sections, repeated, held, varied, with N.C., chord legends, repeat marks, a preamble, a
  tab).
- ``library_of(records)``: kv rows (``[key, value]``, in order, into a fresh database) → ``library_progressions``,
  ``[[song id, [{"key", "plays"}, …]], …]`` in the order SQLite reads kv.
- ``catalogue_of()``: ``{"count", "sha256"}`` of ``catalogue()``'s ``[[key, name], …]``.
- ``label_of(keys)``; ``key_words_of(keys)``: every mode's keys on four tonics.
- ``read_progression_of(texts)``: each → ``[key, keys sorted, name, label]`` or null, whole;
  ``read_progression_digests(batches)``: a digest a batch of drawn texts (every catalogue row typed, turned, in dashes and commas, with ``b`` for
  ♭, in a minor key's own way, with extensions; its name in any case, in part, misspelt).
- ``songs_with_of(fixture, texts)``: a database of the fixture's songs and records (``helpers.corpus.replay_fixture``) →
  for each text, ``[[song key, sections, key], …]`` of ``songs_with(read_progression(text))``, ``[]`` for a text that
  reads as none.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_version.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import functools
import hashlib
import json
import random
import re
from types import SimpleNamespace
from typing import Any

from caracole import db, progressions
from caracole.normalize import identity_key
from caracole.overrides import Overrides
from caracole.render import own_version
from caracole.viewer import harmony, theory, version
from caracole.viewer.instruments import chord_shapes
from caracole.viewer.page import shapes_of, viewer_key
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import MODES, Key, alternatives, key_name, map_chord, parse_chord, spelling
from caracole.viewer.version import Setting, Version, version_query
from helpers import viewer_corpus
from helpers.corpus import check, fixture_bytes, fixture_ref, jsonl, replay_fixture

MADE_BY = "tests/test_conformance_viewer_version.py"
HELPER = "test_conformance_viewer_version."
SEED = viewer_corpus.SEED + 300
VERSION_PATTERNS = ("_DIGITS", "_INDEX", "_NUMBER", "_BAD_ESCAPE", "_TONIC", "_ESCAPED", "_KEY_NAME")
PROGRESSION_PATTERNS = ("_TYPED", "_SEPARATORS", "_WORD", "_APOSTROPHES")


# --- the data ------------------------------------------------------------------------------------------------------


def _patterns(module, names: tuple[str, ...]) -> dict:
    out = {}
    for name in names:
        p = getattr(module, name)
        assert p.flags & ~(re.UNICODE | re.IGNORECASE) == 0, f"{name}: a flag the phone doesn't read"
        inline = p.pattern.startswith("(?i)")
        out[name] = {"pattern": p.pattern, "ignorecase": bool(p.flags & re.IGNORECASE) and not inline}
    return out


def constants() -> dict:
    return {
        "version": {
            "patterns": _patterns(version, VERSION_PATTERNS),
            "MODE_NAMES": dict(version.MODE_NAMES),
            "_SAID": dict(version._SAID),
            "CAPO_MAX": version.CAPO_MAX,
            "_FORM_SAFE": "".join(sorted(chr(b) for b in version._FORM_SAFE)),
        },
        "progressions": {
            "KV": progressions.KV,
            "UNNAMED": progressions.UNNAMED,
            "patterns": _patterns(progressions, PROGRESSION_PATTERNS),
            "_GENERIC": sorted(progressions._GENERIC),
            "_SAYS_PROGRESSION": sorted(progressions._SAYS_PROGRESSION),
            "_NAME_LETTERS": progressions._NAME_LETTERS,
            "_NOT_ALONE": sorted(progressions._NOT_ALONE),
            "_TITLES": sorted(progressions._TITLES),
        },
    }


@functools.cache
def version_json() -> str:
    return viewer_corpus.data_json(constants())


def test_version_json_is_the_modules_constants():
    check(viewer_corpus.VIEWER_DATA / "version.json", version_json())


def test_the_data_reads_back_as_the_modules_hold_it():
    data = json.loads(version_json())
    for name, module in (("version", version), ("progressions", progressions)):
        for pattern_name, p in data[name]["patterns"].items():
            assert re.compile(p["pattern"], re.IGNORECASE if p["ignorecase"] else 0) == getattr(module, pattern_name)
    assert frozenset(data["version"]["_FORM_SAFE"].encode("ascii")) == version._FORM_SAFE
    for name in ("_GENERIC", "_SAYS_PROGRESSION", "_NOT_ALONE", "_TITLES"):
        assert frozenset(data["progressions"][name]) == getattr(progressions, name)
    # the capo a version's capo is kept to in _played is viewer.js's CAPO_MAX, a literal 11 there and in Kotlin
    assert version.CAPO_MAX == 11


# --- rows ----------------------------------------------------------------------------------------------------------


def key_row(key: Key | None) -> list | None:
    return None if key is None else [key.tonic, key.mode]


def key_of(row: list | None) -> Key | None:
    return None if row is None else Key(row[0], row[1])


def version_row(v: Version) -> list:
    return [v.t, v.mode, v.capo, [[i, n] for i, n in v.at.items()],
            [[mode, [[i, *swap] for i, swap in swaps.items()]] for mode, swaps in v.alt.items()], v.inst]


def kept_row(kept: version.KeyVersion) -> list:
    return [key_row(kept.key), kept.mode, kept.capo, [list(pair) for pair in kept.alt],
            [[name, list(frets)] for name, frets in kept.at], kept.inst]


def sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def digest(value: Any) -> str:
    """A batch's answers by the first 16 hex digits of their SHA-256: enough to tell they changed, in a quarter of the
    room."""
    return sha256(value)[:16]


def raised(e: Exception) -> dict:
    return {"error": str(e)}


# --- the address ---------------------------------------------------------------------------------------------------

ROUND_TRIP = ("t=-3&mode=dorian&capo=0&alt=dorian.0.4.m7.11%2Cdorian.3.1.7%25239.%2Clydian.2.0.6%252F9%252Ex.4"
              "&at=0.1%2C3.2")
# tests/test_viewer_version.py's.
TEST_QUERIES = (
    ROUND_TRIP, "#" + ROUND_TRIP, "", "fs=20&t=2&speed=8&chord=3&panel=1", "t=40", "t=-2.6", "t=up&mode=funky&capo=-1",
    "capo=", "capo=2.5", "at=1.0,2.x,03.1,4.2,4",
    "alt=dorian.1.2.m.,funky.1.2.m.,dorian.x.2.m.,dorian.2.2.m.y,dorian.3.2.%25zz.,dorian.4.2.%25E0%25A4.",
    "alt=dorian.1.2", "t=2&capo=0&at=1.1&inst=ukulele", "inst=piano", "inst=harmonica", "inst=flute", "inst=recorder",
    "inst=guitar", "inst=banjo",
)
# What the viewer's address may hold at the edges of what version_from_query reads.
EDGE_QUERIES = (
    "?" + ROUND_TRIP, "#", "?", "##t=3", "inst=ukulele-low-g", "inst=baritone", "inst=Piano", "inst=piano&inst=ukulele",
    # t as JavaScript's Number() reads it, within 11 semitones, rounded half up
    "t=+3", "t=.5", "t=-.5", "t=0.49999999999999994", "t=1e1", "t=1E-1", "t=1e999", "t=-1e999", "t= 4 ", "t=%204",
    "t=4%C2%A0", "t=4%E3%80%80", "t=5.", "t=0x10", "t=", "t=-0", "t=11.5", "t=-11.5", "t=-10.5", "t=2.5", "t=-2.5",
    "t=2&t=5", "%74=2", "t%3D2", "t+=2", "t=2+", "t=+", "t=1_0", "t=١", "t=Infinity", "t=NaN", "t", "t=3=4",
    # the capo
    "capo=0", "capo=-0", "capo=99.6", "capo=1e9", "capo=-0.4", "capo=+0.5", "capo= ", "capo=12", "capo=3&capo=4",
    "capo=x",
    # the mode
    "mode=Dorian", "mode=aeolian&mode=dorian", "mode=", "mode=locrian", "mode=ionian&t=-1",
    # the swaps: modes in the order the address names them, each one's chords by index
    "alt=lydian.0.5.maj7.,dorian.2.10.m7.", "alt=dorian.3.1.x.,dorian.1.2.y.", "alt=dorian.1.2.m.4.9",
    "alt=dorian.1.2.m", "alt=dorian.00.2.m.", "alt=dorian.1.00.m.07", "alt=dorian.1..m.",
    "alt=dorian.1.2.m%252E7.,dorian.1.3.%25E2%2599%25AD5.", "alt=dorian.1.2.♭5.", "alt=dorian.1.2.m+7.",
    "alt=dorian.1.2.m%2B7.", "alt=dorian.1.2.m%2525.", "alt=dorian.1.2.%25.", "alt=dorian.1.2.m%252.",
    "alt=dorian.1.2.%25C3.", "alt=dorian.1.2.%25C3%25A9.", "alt=dorian.1.2.%C3.", "alt=dorian.0.1.,dorian.0.2.m.",
    "alt=,,dorian.0.1..", "alt=aeolian.3.0.m.4,ionian.3.0..4,phrygian.1.1.dim.", "alt=dorian.1.2.m 7.",
    # the shapes
    "at=0.1,0.2", "at=1.007", "at=1.0", "at=x.1", "at=-1.2", "at=1.-2", "at=1.2.3", "at=", "at=1", "at=10.3,2.1",
    "at=0.00",
    # everything at once, and noise
    "t=-5&mode=mixolydian&capo=7&alt=mixolydian.0.7.7.&at=0.2&inst=ukulele&fs=2", "t=3&&&mode=phrygian", "=3&t=1",
    "t==3",
)
QUERIES = 25
_SUFFIXES = ("", "m", "7", "maj7", "m7b5", "sus4", "dim", "6%252F9", "7%2523%2539", "add9", "%25E2%2599%25AD5", "m%252E7",
             "%25zz", "%25C3")


def _seeded_queries(rng: random.Random) -> list[str]:
    out = []
    ids = version.instrument_ids()
    for _ in range(QUERIES):
        parts = []
        if rng.random() < 0.7:
            parts.append("t=" + rng.choice((str(rng.randint(-14, 14)), f"{rng.uniform(-13, 13):.2f}", "1e1", " 3", "x", "")))
        if rng.random() < 0.6:
            parts.append("mode=" + rng.choice((*MODES, "Dorian", "funky", "")))
        if rng.random() < 0.5:
            parts.append("capo=" + rng.choice((str(rng.randint(-2, 14)), "2.5", "x", "")))
        if rng.random() < 0.5:
            swaps = [f"{rng.choice((*MODES, 'funky'))}.{rng.randint(0, 9)}.{rng.randint(0, 12)}.{rng.choice(_SUFFIXES)}."
                     f"{rng.choice(('', str(rng.randint(0, 11))))}" for _ in range(rng.randint(1, 4))]
            parts.append("alt=" + ",".join(swaps))
        if rng.random() < 0.5:
            parts.append("at=" + ",".join(f"{rng.randint(0, 9)}.{rng.randint(0, 6)}" for _ in range(rng.randint(1, 3))))
        if rng.random() < 0.3:
            parts.append("inst=" + rng.choice((*ids, "banjo", "")))
        if rng.random() < 0.2:
            parts.append(rng.choice(("fs=20", "speed=3", "chord=2")))
        rng.shuffle(parts)
        out.append(("#" if rng.random() < 0.2 else "") + "&".join(parts))
    return out


def query_inputs() -> list[str]:
    return list(dict.fromkeys((*TEST_QUERIES, *EDGE_QUERIES, *_seeded_queries(random.Random(SEED)))))


def from_query_record() -> dict:
    """Each query's version as its address (which says all a version holds), and for the tests' its row too."""
    queries = query_inputs()
    out = []
    for q in queries:
        v = version.version_from_query(q)
        out.append([version_row(v), version_query(v)] if q in TEST_QUERIES else version_query(v))
    return {"fn": HELPER + "from_query_of", "args": [queries], "out": out}


def instruments_record() -> dict:
    names = [*version.instrument_ids(), "banjo", "", "Guitar", "PIANO", None]
    rows = []
    for name in names:
        inst = version.instrument_of(name)
        on = version.played_on(Version(inst=name))
        rows.append([None if inst is None else inst.id, version._inst_of(name), on.id, version.instrument_words(on),
                     version_query(version.for_instrument(Version(t=1, capo=3, inst=name), on))])
    return {"fn": HELPER + "instruments_of", "args": [names],
            "out": {"ids": list(version.instrument_ids()), "rows": rows}}


# --- where it plays, and its name ----------------------------------------------------------------------------------

G, E_MINOR = [7, "ionian"], [4, "aeolian"]
# tests/test_viewer_version.py's labels.
HAND_LABELS = (
    ("mode=dorian&capo=0", G, 0), ("", G, 2), ("t=3&capo=3", G, 2), ("t=1", E_MINOR, 2),
    ("t=-1&mode=ionian", [1, "ionian"], None), ("t=2&mode=lydian", [0, "ionian"], None), ("", None, 3),
    ("t=2&capo=0", None, 3), ("t=-4", None, None), ("capo=0", E_MINOR, 2), ("", None, None), ("t=-4&capo=1", None, None),
    ("t=2", [0, "ionian"], 3), ("inst=piano", G, 2), ("capo=4", G, 2), ("capo=4&inst=harmonica", G, 2),
    ("inst=ukulele", G, 2), ("inst=ukulele-low-g", G, 2), ("capo=0&inst=baritone", G, 2), ("inst=flute", G, 2),
    ("inst=piano", None, 3), ("t=-3&capo=0&inst=recorder", None, 3),
)
LABEL_QUERIES = (
    "", "t=3", "t=-3&capo=0", "mode=dorian", "t=-3&mode=mixolydian&capo=3", "t=3&mode=phrygian&capo=0", "t=11",
    "t=-11&capo=11", "capo=14", "mode=locrian&capo=1", "mode=aeolian", "mode=ionian", "mode=lydian&t=5",
    "t=3&inst=piano", "mode=dorian&capo=3&inst=piano", "t=-3&capo=0&inst=ukulele", "inst=harmonica", "t=2&inst=flute",
    "capo=5&inst=recorder", "t=-1&capo=2&inst=baritone", "capo=0&inst=ukulele-low-g", "t=6&mode=dorian&inst=piano",
    "capo=99", "t=-6&capo=6",
)
LABEL_KEYS = (None, [0, "ionian"], [9, "aeolian"], [7, "ionian"], [2, "dorian"], [4, "phrygian"], [5, "lydian"],
              [10, "mixolydian"], [11, "locrian"], [6, "ionian"], [1, "aeolian"], [3, "ionian"], [8, "aeolian"])
LABEL_CAPOS = (None, 0, 1, 2, 5, 11, 12, 14)


def label_answer(query: str, key: list | None, capo: int | None) -> list:
    v = version.version_from_query(query)
    k = key_of(key)
    played, played_capo = version.played_key(v, k, capo)
    return [key_row(played), played_capo, version.version_label(v, k, capo), version.played_label(v, k, capo)]


def label_records() -> list[dict]:
    items = [list(item) for item in HAND_LABELS]
    whole = {"fn": HELPER + "labels_of", "args": [items], "out": [label_answer(*item) for item in items]}
    digests = [digest([label_answer(q, k, c) for k in LABEL_KEYS for c in LABEL_CAPOS]) for q in LABEL_QUERIES]
    product = {"fn": HELPER + "labels_product", "args": [list(LABEL_QUERIES), list(LABEL_KEYS), list(LABEL_CAPOS)],
               "out": digests}
    return [whole, product]


# --- settings ------------------------------------------------------------------------------------------------------

SETTING_PROBLEMS = (
    [None, None, None, None], ["G", "dorian", 0, "guitar"], ["F#", None, 11, "ukulele-low-g"], ["Bb", "locrian", None, None],
    ["g", None, None, None], ["H", None, None, None], ["G#m", None, None, None], ["", None, None, None],
    ["Bb ", None, None, None], [1, None, None, None], [True, None, None, None], [1.5, None, None, None],
    [["G"], None, None, None], [{"k": "G"}, None, None, None], ["G\n", None, None, None], ["Gb", None, None, None],
    [None, "Dorian", None, None], [None, "", None, None], [None, 3, None, None], [None, ["dorian"], None, None],
    [None, None, -1, None], [None, None, 12, None], [None, None, True, None], [None, None, False, None],
    [None, None, 2.0, None], [None, None, "2", None], [None, None, 12345678901234567890, None], [None, None, 1e20, None],
    [None, None, -0.0, None], [None, None, 0.1, None], [None, None, None, "banjo"], [None, None, None, "Guitar"],
    [None, None, None, ""], [None, None, None, 1], [None, None, None, "harmonica"], ["H", "x", 99, "banjo"],
    [None, "x", 99, "banjo"], [None, None, 99, "banjo"], ["it's", None, None, None], ['say "G"', None, None, None],
    ["é​", None, None, None],
)


def setting_problems_record() -> dict:
    items = [list(item) for item in SETTING_PROBLEMS]
    return {"fn": HELPER + "setting_problems_of", "args": [items],
            "out": [version.setting_problem(*item) for item in items]}


def setting_of(row: list | None) -> Setting | None:
    return None if row is None else Setting(*row)


# tests/test_viewer_version.py's: the UG sheet's G shapes, capo 2.
HAND_SETTINGS = (
    ("t=1&at=0.1", [None, None, None, "ukulele"], G, 2), ("t=1&at=0.1", ["C", None, None, "piano"], G, 2),
    ("inst=piano", [None, None, None, "guitar"], G, 2), ("inst=piano", ["G", None, None, None], G, 2),
    ("inst=piano", ["G", None, None, None], None, None), ("t=2", None, G, 2), ("t=2", [None, None, None, None], G, 2),
    ("t=2&at=0.1", [None, None, 2, None], G, 2), ("t=2&at=0.1", [None, "dorian", None, None], G, 2),
    ("mode=dorian&capo=3", ["A", None, None, None], [9, "aeolian"], 0), ("", ["Bb", "lydian", 0, None], G, None),
    ("t=-1", ["E", None, 4, "harmonica"], G, 2), ("", [None, "funky", None, None], G, 2),
)
SETTING_OWNS = ("", "t=2", "t=-3&mode=dorian&capo=0", "capo=5&at=0.1,2.2", "t=1&at=0.1&inst=piano",
                "mode=aeolian&alt=aeolian.0.3.m7.&at=1.1", "inst=ukulele&capo=2", "t=5&mode=lydian&inst=harmonica",
                "capo=11", "t=-11&capo=0&inst=baritone", "mode=locrian", "t=4&capo=2&at=3.1&inst=ukulele-low-g")
SETTINGS = (None, [None, None, None, None], ["G", None, None, None], ["F#", None, None, None], ["Bb", None, None, None],
            ["C", "dorian", None, None], [None, "aeolian", None, None], [None, "funky", None, None],
            [None, None, 0, None], [None, None, 7, None], [None, None, None, "guitar"], [None, None, None, "piano"],
            [None, None, None, "ukulele"], ["E", None, 3, None], ["A", "mixolydian", 2, "ukulele"],
            ["D", None, None, "piano"], ["Eb", "phrygian", 0, "harmonica"], [None, "ionian", 4, "baritone"],
            ["B", "locrian", 11, None], ["Ab", None, None, "flute"])
SETTING_KEYS = (None, [7, "ionian"], [9, "aeolian"], [2, "dorian"], [0, "ionian"], [4, "aeolian"], [10, "lydian"],
                [11, "locrian"])
SETTING_CAPOS = (None, 0, 2, 7)


def in_setting_answer(own: str, setting: list | None, shapes: list | None, capo: int | None) -> str:
    return version_query(version.in_setting(version.version_from_query(own), setting_of(setting), key_of(shapes), capo))


def setting_records() -> list[dict]:
    items = [list(item) for item in HAND_SETTINGS]
    whole = {"fn": HELPER + "in_setting_of", "args": [items], "out": [in_setting_answer(*item) for item in items]}
    digests = [digest([in_setting_answer(own, s, k, c) for s in SETTINGS for k in SETTING_KEYS for c in SETTING_CAPOS])
               for own in SETTING_OWNS]
    product = {"fn": HELPER + "in_setting_product",
               "args": [list(SETTING_OWNS), [s for s in SETTINGS], list(SETTING_KEYS), list(SETTING_CAPOS)],
               "out": digests}
    return [setting_problems_record(), whole, product]


# --- a version kept by its key -------------------------------------------------------------------------------------

# tests/test_viewer_version.py's entries, and what key_version reads at its edges.
KEY_TEXTS = (
    "key=Gm&mode=dorian&capo=0", "t=2&mode=dorian&capo=0", "", "#key=F#m&mode=dorian&capo=2", "key=Bb",
    "key=A dorian&capo=0", "key=H", "key=g", "key=", "key=Gmin", "key=G dorien", "key=G&mode=dorien", "key=G&capo=12",
    "key=G&capo=two", "key=G&t=2",
    "key=G&alt=F.Fmaj7,F,Hm.Gm,F.x,a.b.c&at=Gm.x-x-5-7-8-6,3.1,Hm.x-0-2-2-1-0,Gm.2,Gm.x-x-x-x-x-x,Gm.1-2-3,Bb",
    "key=F#m&mode=dorian&capo=0&alt=C#7.C#7(b9)&at=F#m.x-4-4-6-7-5,C6%2E9.x-3-2-2-3-3,A%2CB.5-7-7-6-5-5,"
    "D%26%3D%25.x-x-0-2-3-2", "key=Bb dorian", "key=Dm&capo=3&inst=piano", "key=Dm&capo=3&inst=ukulele",
    "key=G&at=G.3-2-0-0-0-3&inst=ukulele", "key=G&at=G.0-2-3-2&inst=piano", "key=G&inst=banjo",
    "key=G&at=G.0-2-3-2&inst=ukulele", "key=Gm&capo=0&at=Gm.x-x-5-7-8-6",
    # at its edges
    "?key=A", "key=G&key=A", "key=%46%23m", "key=G%", "key=%FF", "key=G&capo=%31", "key=G&capo=01", "key=G&capo=",
    "key=G&capo=-1", "key=G&capo=99999999999999999999", "key=G&capo=1.0", "key=G&mode=", "key=G&inst=",
    "key=G&inst=guitar", "key=G&inst=harmonica&at=G.3-2-0-0-0-3", "key=G mixolydian", "key=Gm dorian",
    "key=G%20dorian", "key=G+dorian", "key=Cb", "key=E#", "key=G&t=", "&&key=A&&", "key", "Key=G", "key=G&mode=Dorian",
    "key=G&alt=F.Fmaj7,F.F7,%25zz.G,C.%E2%99%AD", "key=G&alt=E%E2%99%AD.Eb7,Bb%2Fd.C", "key=G&at=G.3-2-0-0-0-3,G.x-x-0-0-0-3",
    "key=G&at=G.100-2-0-0-0-3,G.3-2-0-0-0-%33,D.x-x-0-2-3-2", "key=G&at=G.%33-2-0-0-0-3", "key=G&alt=F%20.Fmaj7",
    "key=G&capo=%EF%BC%91", "key=Am&mode=aeolian", "key=A minor", "key=G&inst=ukulele-low-g&at=G.0-2-3-2",
    "key=C#&mode=locrian&capo=11&inst=baritone&at=C#.x-4-3-1-x",
)


def key_version_answer(text: str) -> Any:
    try:
        kept = version.key_version(text)
    except ValueError as e:
        return raised(e)
    if kept is None:
        return None
    return {"kept": kept_row(kept), "query": kept.query(), "label": kept.label()}


def key_versions_record() -> dict:
    texts = list(dict.fromkeys(KEY_TEXTS))
    return {"fn": HELPER + "key_versions_of", "args": [texts], "out": [key_version_answer(t) for t in texts]}


# The sheets in_key and version_entry read: tests/test_viewer_version.py's, then drawn ones.
IN_A_MINOR = "{title: T}\n{artist: A}\n{key: Am}\n[Am]una [F]can[C]ción [G]más\n"
IN_D_MINOR_CAPO_3 = "{title: T}\n{artist: A}\n{key: Dm}\n{capo: 3}\n[Dm]otra [Bb]le[F]tra [C]más\n"
IN_C_MAJOR = IN_A_MINOR.replace("{key: Am}", "{key: C major}")
NO_KEY = "{title: T}\n{artist: A}\n[N.C.]la [Hm]lo\n"
TAGGED_A = IN_A_MINOR.replace("{key: Am}", "{key: A}")
TAGGED_CM = IN_C_MAJOR.replace("{key: C major}", "{key: Cm}")
ITS_OWN = ("{title: T}\n{artist: A}\n{key: Gm}\n{define: Gm base-fret 10 frets x 1 3 3 2 1 fingers 0 1 3 4 2 1}\n"
           "{define: Gm base-fret 1 frets x x 0 3 3 3 fingers 0 0 0 1 1 1}\n[Gm]otra [Eb]le[Bb]tra [F]más\n")
OTHER = "{title: T}\n{artist: A}\n{key: Am}\n[Am]la [Dm]lo [E7]li\n"
ODD = "{title: Odd}\n{artist: A}\n{key: C}\n[N.C.]la [Cadd9(no3)]lo [Hm]li [G]le [(G)]lu\n[C] [N.C.] [*x2]\n"
LEGEND_LATER = ("{title: T}\n{artist: A}\n{key: Am}\n{comment: Verse}\n[Am]Una canció[C]n de [G]prueba\n\n"
                "{comment: Chords}\n[Am] [*x02210]\n[C] [*x32010]\n\n{comment: Chorus}\n[F]Otra [C]vez\n")


def sheet_of(chords: list[str]) -> str:
    return "{title: T}\n{artist: A}\n" + " ".join(f"[{c}]la" for c in chords) + "\n"


UG_CHO = fixture_ref("chordpro/ug_sheet.cho")
LEGEND_CHO = fixture_ref("chordpro/legend_sheet.cho")
# (cho, the song's key, its source), as page.viewer_key is given them.
HAND_SHEETS = (
    (IN_A_MINOR, None, None), (IN_D_MINOR_CAPO_3, None, None), (IN_C_MAJOR, None, None), (NO_KEY, None, None),
    (TAGGED_A, None, None), (TAGGED_A, "A", "audio"), (TAGGED_CM, None, None), (ITS_OWN, None, None),
    (OTHER, None, None), (sheet_of(["C", "G", "Am", "F", "C"]), None, None),
    (sheet_of(["Am", "F", "C", "G", "Am"]), None, None), (UG_CHO, None, None), (LEGEND_CHO, "Em", None),
    (LEGEND_CHO, None, None), (ODD, None, None), (LEGEND_LATER, None, None),
    ("{title: T}\n{artist: A}\n{key: G}\n{capo: 13}\n[G]la [C]lo [D]li [Em]le\n", None, None),
)
DRAWN_SHEETS = 7


def text_of(cho: Any) -> str:
    return fixture_bytes(cho).decode("utf-8") if isinstance(cho, dict) else cho


def _drawn_sheets(rng: random.Random) -> list[tuple[str, str | None, str | None]]:
    out = []
    for n in range(DRAWN_SHEETS):
        key = Key(rng.randrange(12), rng.choice(MODES))
        steps = theory.SCALES[key.mode]
        names = []
        for _ in range(rng.randint(3, 7)):
            root = (key.tonic + steps[rng.randrange(7)]) % 12
            if rng.random() < 0.15:
                root = rng.randrange(12)  # a chord outside the key
            quality = theory._diatonic_quality(root, key, rng.choice((3, 3, 4))) or rng.choice(("", "m", "7"))
            bass = (root + rng.choice((4, 7, 3))) % 12 if rng.random() < 0.15 else None
            names.append(viewer_corpus.chord_name(root, quality, key, bass))
        lines = ["{title: Drawn %d}" % n, "{artist: A}"]
        named = rng.choice((None, key_name(key), spelling(key)[key.tonic]))
        if named is not None:
            lines.append("{key: %s}" % named)
        capo = rng.choice((None, None, 0, 2, 5, 14))
        if capo is not None:
            lines.append("{capo: %d}" % capo)
        if rng.random() < 0.3:
            lines.append("{define: %s base-fret 3 frets x 1 3 3 2 1 fingers 0 1 3 4 2 1}" % names[0])
        lines.append("{comment: Verse}")
        lines.append(" ".join(f"[{c}]la" for c in names))
        if rng.random() < 0.4:
            lines += ["", "{comment: Chorus}", " ".join(f"[{c}]lo" for c in reversed(names))]
        song_key = rng.choice((None, None, key_name(key), "C"))
        out.append(("\n".join(lines) + "\n", song_key, rng.choice((None, "tab", "audio")) if song_key else None))
    return out


@functools.cache
def _sheets() -> tuple[tuple[Any, Key | None, int | None], ...]:
    found = []
    for cho, song_key, source in (*HAND_SHEETS, *_drawn_sheets(random.Random(SEED + 1))):
        text = text_of(cho)
        found.append((cho, viewer_key(text, song_key, source), parse_sheet(text).capo))
    return tuple(found)


def sheets_arg() -> list[list]:
    return [[cho, key_row(key), capo] for cho, key, capo in _sheets()]


# The versions every sheet keeps (version_entry), then each sheet's own: its chords played instead and its shapes.
ENTRY_VERSIONS = (
    "t=-2&mode=dorian", "t=-2", "t=-2&mode=aeolian", "t=1&capo=2", "", "t=2", "mode=aeolian", "t=2&capo=1",
    "t=-2&inst=piano", "inst=piano", "t=-2&at=0.1&inst=ukulele", "t=-2&at=0.2", "mode=dorian&capo=3", "capo=12",
    "capo=0&inst=harmonica", "t=5&mode=lydian&capo=7&inst=baritone", "mode=locrian&at=1.1,2.3",
    "t=-6&mode=phrygian&capo=0&inst=ukulele-low-g", "t=3&at=0.1,1.1,2.1,3.1&inst=flute",
)
OWN_VERSIONS = 2


def _own_versions(rng: random.Random, cho: str, key: Key | None) -> list[str]:
    if key is None:
        return []
    sheet = parse_sheet(cho)
    given = shapes_of(sheet)
    chords = [parse_chord(name, strict=False) for name in sheet.chords]
    readable = [i for i, c in enumerate(chords) if c is not None]
    out = []
    for _ in range(OWN_VERSIONS):
        mode = rng.choice(MODES)
        alt: dict[str, dict[int, tuple]] = {}
        for i in rng.sample(readable, min(2, len(readable))):
            offered = alternatives(map_chord(chords[i], key, mode), Key(key.tonic, mode))
            if offered:
                a = rng.choice(offered)
                alt.setdefault(mode, {})[i] = (a.root, a.suffix, a.bass)
        if rng.random() < 0.3:
            alt.setdefault(rng.choice(MODES), {})[0] = (0, "6/9.x", 4)
        inst = rng.choice((None, None, "ukulele", "piano", "baritone", "harmonica"))
        t = rng.randint(-6, 6)
        at = {}
        if readable:
            i = rng.choice(readable)
            listed = chord_shapes(version.played_on(Version(inst=inst)), chords[i], t, given)
            at[i] = rng.randint(1, max(1, len(listed)))  # past the list, sometimes: none
        out.append(version_query(Version(t=t, mode=mode if rng.random() < 0.7 else None,
                                         capo=rng.choice((None, 0, 2, 4, 13)), at=at, alt=alt, inst=inst)))
    return out


@functools.cache
def own_inputs() -> tuple[tuple[str, ...], ...]:
    rng = random.Random(SEED + 2)
    return tuple(tuple(_own_versions(rng, text_of(cho), key)) for cho, key, _ in _sheets())


def entry_answer(query: str, cho: Any, key: Key | None, capo: int | None) -> str | None:
    return version.version_entry(version.version_from_query(query), text_of(cho), key=key, capo_sheet=capo)


# tests/test_viewer_version.py's entries: [version, sheet index].
HAND_ENTRIES = (
    ("t=-2&mode=dorian", 0), ("t=-2", 0), ("t=-2&mode=aeolian", 0), ("t=1&capo=2", 1), ("", 1), ("t=2", 2),
    ("mode=aeolian", 2), ("t=2", 9), ("t=2", 0),
    ("t=-2&mode=dorian&at=0.2&alt=dorian.3.7.maj7.,lydian.1.5.maj7.", 0), ("t=-2&at=0.2", 0), ("t=2&capo=1", 3),
    ("", 3), ("t=-2&inst=piano", 0), ("inst=piano", 1), ("t=-2&at=0.1&inst=ukulele", 0),
)


# tests/test_viewer_version.py's kept_on cases: [entry, sheet index].
HAND_IN_KEY = (
    ("key=Gm&mode=dorian&capo=0", 0), ("key=Gm&mode=dorian&capo=0", 1), ("key=Gm&capo=0", 0), ("key=D&capo=0", 10),
    ("key=Bm&capo=0", 2), ("key=Gm&mode=dorian&capo=0", 2), ("key=C&mode=aeolian&capo=0", 0), ("key=Bm&capo=0", 4),
    ("key=Gm&capo=0", 4), ("key=Am&capo=0", 4), ("key=Bm&capo=0", 5), ("key=Gm&capo=0", 5),
    ("key=Gm&mode=dorian&capo=0", 4), ("key=Gm&mode=dorian&capo=0", 5), ("key=D&capo=0", 6),
    ("key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6", 0), ("key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6", 1),
    ("key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6", 8),
    ("key=Gm&mode=dorian&capo=0&at=Gm.1-1-1-1-1-1,Bb.6-8-8-7-6-6", 0), ("key=Gm&capo=0&at=Gm.x-x-5-7-8-6", 7),
    ("key=Gm&capo=0&at=Gm.x-x-x-3-3-3", 7), ("key=Gm&mode=dorian&capo=0", 3), ("key=Dm&capo=3&inst=piano", 1),
)
SEEDED_ENTRIES = 24
ENTRIES_FROM_VERSIONS = 30


def _seeded_entries(rng: random.Random) -> list[str]:
    names = [n for n in viewer_corpus.chord_names() if parse_chord(n.strip(), strict=False) is not None
             and n == n.strip() and n.isascii()]
    out = []
    for _ in range(SEEDED_ENTRIES):
        key = Key(rng.randrange(12), rng.choice(MODES))
        parts = [f"key={key_name(key)}"]
        if rng.random() < 0.4:
            parts.append("mode=" + rng.choice(MODES))
        if rng.random() < 0.7:
            parts.append(f"capo={rng.randint(0, 11)}")
        if rng.random() < 0.5:
            parts.append("alt=" + ",".join(f"{version._escape(rng.choice(names))}.{version._escape(rng.choice(names))}"
                                           for _ in range(rng.randint(1, 3))))
        inst = rng.choice((None, None, "ukulele", "piano", "baritone"))
        if rng.random() < 0.5:
            strings = 4 if inst in ("ukulele", "baritone") else 6
            parts.append("at=" + ",".join(
                f"{version._escape(rng.choice(names))}."
                + "-".join(rng.choice(("x", "0", "1", "2", "3", "5")) for _ in range(strings))
                for _ in range(rng.randint(1, 2))))
        if inst is not None:
            parts.append(f"inst={inst}")
        out.append("&".join(parts))
    return out


@functools.cache
def in_key_entries() -> tuple[str, ...]:
    """The tests' entries, those version_entry writes on the hand sheets, then drawn ones."""
    found: dict[str, None] = dict.fromkeys(e for e, _ in HAND_IN_KEY)
    made = []
    sheets = _sheets()
    for (cho, key, capo), own in zip(sheets[:len(HAND_SHEETS)], own_inputs(), strict=False):
        for q in (*ENTRY_VERSIONS, *own):
            entry = entry_answer(q, cho, key, capo)
            if entry is not None and entry not in found and entry not in made:
                made.append(entry)
    found.update(dict.fromkeys(random.Random(SEED + 3).sample(made, min(ENTRIES_FROM_VERSIONS, len(made)))))
    found.update(dict.fromkeys(_seeded_entries(random.Random(SEED + 4))))
    return tuple(found)


def in_key_answer(entry: str, cho: Any, key: Key | None, capo: int | None) -> str:
    return version_query(version.in_key(version.key_version(entry), text_of(cho), key=key, capo_sheet=capo))


# [entry, transpose, sheet index, the song's key, its source]: render.own_version's ways.
OWN_ITEMS = (
    (None, None, 0, None, None), (None, 3, 0, None, None), ("t=2&mode=dorian", None, 0, None, None),
    ("t=2&mode=dorian", 5, 0, None, None), ("mode=dorian", 5, 0, None, None), ("#mode=dorian", 5, 0, None, None),
    ("?t=0", 5, 0, None, None), ("%74=1", 5, 0, None, None), ("key=Gm&mode=dorian&capo=0", None, 0, None, None),
    ("key=Gm&mode=dorian&capo=0", 4, 1, None, None), ("key=Gm&mode=dorian&capo=0", None, 3, None, None),
    ("key=Bm&capo=0", None, 4, "A", "audio"), ("key=Bm&capo=0", None, 4, "Am", "tab"),
    ("key=Bm&capo=0", None, 2, "C", None), ("key=G&capo=2", None, 11, None, None), ("key=E&capo=0", None, 11, "E", "audio"),
    ("key=G&t=2", None, 0, None, None), ("key=H", None, 0, None, None), ("key=G&capo=12", 2, 0, None, None),
    ("key=Dm&capo=3&inst=piano", None, 1, None, None), ("key=Dm&capo=3&inst=ukulele", None, 9, None, None),
    ("t=2&inst=piano", None, 0, None, None), ("", 2, 0, None, None), ("fs=20", -2, 0, None, None),
    ("key=Am&alt=F.Fmaj7&at=Am.x-0-2-2-1-0", None, 12, "Em", None),
)


def own_answer(entry: str | None, transpose: int | None, i: int, song_key: str | None, source: str | None) -> Any:
    song = SimpleNamespace(key="artist - title", display="Artist - Title")
    overrides = Overrides(version={} if entry is None else {song.key: entry},
                          transpose={} if transpose is None else {song.key: transpose})
    try:
        return version_query(own_version(overrides, song, text_of(_sheets()[i][0]), song_key, source))
    except ValueError as e:
        return raised(e)


def kept_record() -> dict:
    """version_entry, in_key and render.own_version on the sheets, in one record, so its sheets are written once."""
    sheets = _sheets()
    entries = in_key_entries()
    inputs = {"entry_versions": list(ENTRY_VERSIONS), "own": [list(o) for o in own_inputs()],
              "entries_hand": [list(i) for i in HAND_ENTRIES], "in_key": list(entries),
              "in_key_hand": [list(i) for i in HAND_IN_KEY], "own_versions": [list(i) for i in OWN_ITEMS]}
    out = {
        "entries_hand": [entry_answer(q, *sheets[i]) for q, i in HAND_ENTRIES],
        "entries": [digest([entry_answer(q, cho, key, capo) for q in (*ENTRY_VERSIONS, *own)])
                    for (cho, key, capo), own in zip(sheets, own_inputs(), strict=True)],
        "in_key_hand": [in_key_answer(e, *sheets[i]) for e, i in HAND_IN_KEY],
        "in_key": [digest([in_key_answer(e, cho, key, capo) for e in entries]) for cho, key, capo in sheets],
        "own_versions": [own_answer(*item) for item in OWN_ITEMS],
    }
    return {"fn": HELPER + "kept_of", "args": [sheets_arg(), inputs], "out": out}


def version_records() -> list[dict]:
    return [from_query_record(), instruments_record(), *label_records(), *setting_records(), key_versions_record(),
            kept_record()]


@functools.cache
def version_vectors() -> str:
    return jsonl(version_records(), corpus="viewer/version", made_by=MADE_BY)


def test_version_vectors_are_version_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "version.jsonl", version_vectors())


def test_every_branch_of_the_versions_is_in_the_vectors():
    sheets = _sheets()
    answers = [in_key_answer(e, cho, key, capo) for cho, key, capo in sheets for e in in_key_entries()]
    assert any("alt=" in a for a in answers) and any("at=" in a for a in answers) and any("inst=" in a for a in answers)
    # the parallel key's reading (a sheet read from its own tonic) and the relative one's
    tagged = sheets[5]
    assert tagged[1] == Key(9, "ionian")
    assert in_key_answer("key=Gm&mode=dorian&capo=0", *tagged) == "t=-2&mode=dorian&capo=0"
    entries = [entry_answer(q, cho, key, capo) for (cho, key, capo), own in zip(sheets, own_inputs(), strict=True)
               for q in (*ENTRY_VERSIONS, *own)]
    assert None in entries and any("alt=" in (e or "") for e in entries) and any("at=" in (e or "") for e in entries)
    assert any("mode=" in (e or "") for e in entries) and any("inst=" in (e or "") for e in entries)
    assert any(e is not None and "capo=" not in e for e in entries)  # a capo past CAPO_MAX: the sheet's
    kept = [key_version_answer(t) for t in KEY_TEXTS]
    errors = {a["error"].split(" ")[0] for a in kept if isinstance(a, dict) and "error" in a}
    assert errors == {"a", "key", "mode", "capo", "instrument"}
    owns = [own_answer(*item) for item in OWN_ITEMS]
    assert any(isinstance(o, dict) for o in owns) and "t=5&mode=dorian" in owns


# --- progressions --------------------------------------------------------------------------------------------------

# tests/test_progressions.py's sheets.
CHO = ("{title: Synthetic Song}\n{artist: Placeholder Band}\n{key: C}\n{comment: Verse}\n"
       "[Am]Words to [F]sing, [C]only for the [G]test\n[Am]more [F]words, [C]still a [G]test\n"
       "{comment: Chorus}\n[C]la la [G]la, [Am]la la [F]la\n{comment: Outro}\n[C]end\n")
WITHIN = ("{title: Within}\n{key: C}\n{comment: Verse}\n[Dm]a [C]b [G]c [Am]d [F]e\n[Bb]f [C]g [G]h [Am]i [F]j\n"
          "{comment: Chorus}\n[C]k [E]l [F]m [Fm]n\n")
BLUES = "{title: X}\n{comment: A}\n[C]a [F]b [G]c\n"
HAND_PROGRESSIONS = (
    (CHO, None, None), (CHO, "Am", None), (CHO.replace("{key: C}\n", ""), None, None),
    ("{title: X}\n[G]one [D]two\n[Em]three [C]four\n", "G", None),
    ("{title: X}\nCadd9 (x32033)\n{comment: Verse}\n[N.C.]hey [G]one [N.C.]two [D]three\n", "G", None),
    ("{title: X}\nwords alone\n", None, None), ("{title: X}\n{comment: Intro}\n[N.C.]hey\n", "G", None),
    (WITHIN, None, None), (BLUES, "C", None), (CHO, "A", "audio"), (CHO, "C", "tab"), (CHO, "Em", "chords"),
    (UG_CHO, None, None), (UG_CHO, "Em", None), (LEGEND_CHO, None, None), (LEGEND_CHO, "D", "tab"), (ODD, None, None),
    (LEGEND_LATER, None, None),
    ("{title: X}\n{key: G}\n{start_of_chorus}\n[G]a [C]b\n[D]c [G]d\n{end_of_chorus}\n{comment: }\n[Em]e [C]f\n", None, None),
    ("{title: X}\n{key: D}\n{comment: Riff}\n{start_of_tab}\ne|---0---|\n{end_of_tab}\n[D] [A] [*x2]\n[Bm] [G] [*(x4)]\n",
     None, None),
    ("{title: X}\n{key: E}\n{comment: Held}\n[E]a [E]b [E]c\n{comment: Two}\n[E]a [A]b\n", None, None),
)
SHEETS = 14
VARIANTS = ([None, None], ["C", "tab"], ["Am", None])


def progression_text(cho: Any, key: str | None, source: str | None) -> str | None:
    found = progressions.sheet_progressions(text_of(cho), key, source)
    return None if found is None else json.dumps(found, ensure_ascii=False)


def _drawn_progression_sheets(rng: random.Random) -> list[str]:
    rows = viewer_corpus.progressions()
    out = []
    for n in range(SHEETS):
        lines = [f"{{title: Drawn {n}}}", "{artist: A}"]
        first = rng.choice(rows)
        if rng.random() < 0.6:
            lines.append(f"{{key: {key_name(first.key)}}}")
        if rng.random() < 0.3:
            lines += ["A note before the song", "Am  x02210"]
        for s in range(rng.randint(1, 3)):
            row = first if s == 0 else rng.choice(rows)
            chords = list(row.chords)
            if rng.random() < 0.3:
                chords = chords[1:] + chords[:1]  # a turn of it
            played = chords * rng.randint(1, 3)
            if rng.random() < 0.3:
                played.insert(rng.randrange(len(played)), "N.C.")
            if rng.random() < 0.3:
                i = rng.randrange(len(played))
                played.insert(i, played[i])  # a chord held
            if rng.random() < 0.3:
                played.append(rng.choice(("G7", "E7", "Fm", "Bb", "Dsus4", "C/E")))  # it varies, or ends elsewhere
            label = rng.choice(("Verse", "Chorus", "Bridge", "", "Intro"))
            lines.append(f"{{comment: {label}}}" if label or rng.random() < 0.5 else "")
            per = rng.randint(2, 4)
            for at in range(0, len(played), per):
                part = played[at:at + per]
                if rng.random() < 0.3:
                    lines.append(" ".join(f"[{c}]" for c in part) + " [*x2]")
                else:
                    lines.append(" ".join(f"[{c}]la" for c in part))
            if rng.random() < 0.15:
                lines += ["{start_of_tab}", "e|---0---|", "{end_of_tab}"]
            if rng.random() < 0.15:
                lines.append("[Am] [*x02210]")  # a chord legend's line: no chord played
        out.append("\n".join(lines) + "\n")
    return out


@functools.cache
def drawn_progression_sheets() -> tuple[str, ...]:
    return tuple(_drawn_progression_sheets(random.Random(SEED + 5)))


ODD_RECORDS = ([], "x", {"sections": "x"}, {"sections": [1, {"key": 2}, {"numerals": ["I"]}]},
               {"sections": [{"key": "I iii", "numerals": ["I", "iii"], "contains": "x"}]},
               {"sections": [{"key": "I iii", "numerals": ["I", "iii"],
                              "contains": [1, {"name": 2}, {"name": "the pop progression", "key": 3}]}]},
               {"sections": [{"key": "I iii", "numerals": ["I", "iii"], "contains": None}]},
               {"sections": [{"key": "I", "numerals": ["I"]}, {"key": "I V", "numerals": ["I", 5]}]},
               {"key": "C major", "sections": [{"key": "I V vi IV", "numerals": ["I", "V", "vi", "IV"],
                                                "name": "the pop progression",
                                                "contains": [{"name": "the Creep progression", "key": "I III IV iv",
                                                              "numerals": ["I", "III", "IV", "iv"]}]}]},
               {"sections": [{"key": "I V VI IV", "numerals": ["I", "V", "VI", "IV"], "name": "the pop progression"}]},
               {"sections": [{"key": "I V VI IV", "numerals": ["I", "V", "VI", "IV"], "name": 7}]})


# A record of one section that plays I–V, for the ids a record is or isn't kept by.
SMALL = json.dumps({"key": "C major", "sections": [{"key": "I V", "numerals": ["I", "V"]}]})


def library_inputs() -> list[list[str]]:
    rows = [[f"{progressions.KV}{n + 1}", json.dumps(odd, ensure_ascii=False)] for n, odd in enumerate(ODD_RECORDS)]
    for n, cho in enumerate((CHO, WITHIN)):
        rows.append([f"{progressions.KV}{100 + n}", progression_text(cho, None, None)])
    rows += [[f"{progressions.KV}x", SMALL], [f"{progressions.KV}", SMALL], [f"{progressions.KV}1a", SMALL],
             [f"{progressions.KV}٣", SMALL], [f"{progressions.KV}007", SMALL.replace('"I V"', '"I IV"').replace('"V"', '"IV"')],
             [f"{progressions.KV}7", SMALL], [f"{progressions.KV}200", "not json"],
             [f"{progressions.KV}201", '{"sections": [NaN]}'], [f"{progressions.KV}202", ""],
             ["render:progressionsx3", SMALL], ["render:3", SMALL]]
    return rows


def library_answer(conn, rows: list[list[str]]) -> list:
    replay_fixture(conn, [{"kv": k, "value": v} for k, v in rows])
    return [[song_id, entries] for song_id, entries in progressions.library_progressions(conn).items()]


# tests/test_progressions.py's texts, and what read_progression reads at its edges.
HAND_TEXTS = (
    "vi IV I V", "vi–IV–I–V", "I V vi IV", "vi, IV, I, V", "  IV I V vi ", "I bVII IV", "I ii iii", "I iii IV",
    "Imaj7 vi7 ii7 V7", "ii V I", "III7 VI7 II7 V7", "I III IV iv", "i bIII bVII IV", "iii vi IV V", "I vi ii V",
    "IV V vi V", "I V IV I V IV I V", "IV V iii vi", "i VII VI VII", "i bVII bVI v", "andalusian", "Andalusian Cadence",
    "the pop progression", "blues", "extended plagal", "lament", "the Creep progression", "backdoor", "royal road",
    "the royal road", "minor ii V i", "12 bar", "pop progression", "", "hello world", "I", "I I I", "V", "vi IV hello",
    "pop", "progression", "the cadence", "Wonderwall", "via", "The Road", "the bar", "a road", "minor", "Minor",
    "the minor", "creep", "Creep", "creep progression", "Andalusían", "andalusian's", "the 8-bar blues", "ragtime",
    "I—V—vi—IV", "I V vi IV", "♭VII IV I", "#iv° V", "I/3 V vi IV", "V/V V I", "vii°7 I", "Iadd9 Vsus4 vi IV",
    "i iv v i", "i VI III VII", "i VII", "I-V", "royal", "road", "the", "cadence progression", "plagal cadence",
    "doo-wop", "50s", "fifties", "circle of fifths", "the circle", "Aeolian", "shuttle", "Mixolydian", "puff",
)
TEXT_BATCH = 10


def _drawn_texts(rng: random.Random) -> list[str]:
    out = []
    for name, numerals, _ in harmony.CATALOGUE:
        numerals = list(numerals)
        turn = rng.randrange(len(numerals))
        turned = numerals[turn:] + numerals[:turn]
        out.append(" ".join(numerals))
        out.append("–".join(turned))
        out.append(", ".join(turned).replace("♭", "b").replace("♯", "#"))
        out.append(" ".join(n + rng.choice(("", "7", "maj7", "sus4", "add9")) for n in numerals))
        out.append(" ".join(n.lstrip("♭") if n.lstrip("♭").upper() in ("III", "VI", "VII") else n for n in numerals))
        words = name.split()
        out.append(rng.choice((name.upper(), name.title(), " ".join(rng.sample(words, max(1, len(words) - 1))))))
        out.append(name.replace("a", "á", 1).replace("e", "", 1))
    return out


@functools.cache
def drawn_texts() -> tuple[str, ...]:
    return tuple(dict.fromkeys(_drawn_texts(random.Random(SEED + 6))))


def read_answer(text: str) -> list | None:
    wanted = progressions.read_progression(text)
    return None if wanted is None else [wanted.key, sorted(wanted.keys), wanted.name, wanted.label]


# The songs songs_with reads, by their identity keys (as the library keeps them: list_songs re-keys none): their names
# sort by casefold (Straße before Strasse2, which lower case puts after it), then by id.
SONGS = (
    (1, "Placeholder Band", "Synthetic Song"), (2, "Another Band", "In A Minor"), (3, "Third Band", "Blues"),
    (4, "Placeholder Band", "Within"), (5, "another band", "Whole"), (6, "Ángel", "Straße"), (7, "ángel", "Strasse2"),
    (8, "Zed", "Nothing"),
)


def section(key: str, numerals: list[str], name: str | None = None, contains: list | None = None, **more) -> dict:
    """A record's section, as sheet_progressions writes one, with what a test needs of it."""
    out = {"key": key, "numerals": numerals, "name": name, **more}
    if contains is not None:
        out["contains"] = [{"name": n, "key": k, "numerals": ns} for n, k, ns in contains]
    return out


POP = section("I V vi IV", ["vi", "IV", "I", "V"], "the pop progression", section="Verse")
POP_MINOR = section("i ♭VI ♭III ♭VII", ["i", "♭VI", "♭III", "♭VII"], "the pop progression", section="Chorus")
# The songs' records: the pop progression played, in a minor key, within a section, a blues, nothing searchable.
RECORDS = {
    1: {"key": "C major", "sections": [POP, {**POP, "section": "Chorus", "numerals": ["I", "V", "vi", "IV"]}]},
    2: {"key": "A minor", "sections": [{**POP_MINOR, "section": "Verse"}, POP_MINOR]},
    3: {"key": "C major", "sections": [section("I IV V", ["I", "IV", "V"], section="A")]},
    4: {"key": "C major", "sections": [
        section("I ii V vi", ["ii", "I", "V", "vi"], None, [("the pop progression", "I V vi IV", ["I", "V", "vi", "IV"])],
                section="Verse"),
        section("I III IV iv", ["I", "III", "IV", "iv"], "the Creep progression", section="Chorus")]},
    5: {"key": "C major", "sections": [POP]},
    6: {"key": "G major", "sections": [{**POP, "section": None}, section("I", ["I"], section="Outro")]},
    7: {"key": "C major", "sections": [POP, section("I III IV iv", ["I", "III", "IV", "iv"], None,
                                               [("the Creep progression", "I III IV iv", ["I", "III", "IV", "iv"])],
                                               section="Bridge")]},
}


def songs_fixture() -> list[dict]:
    records = []
    for song_id, artist, title in SONGS:
        records.append({"table": "songs", "row": {
            "id": song_id, "key": identity_key(artist, title), "artist": artist, "title": title,
            "artists": json.dumps([artist]), "added_at": "2026-11-04T00:00:00Z", "created_at": "2026-11-04T00:00:00Z",
            "updated_at": "2026-11-04T00:00:00Z"}})
    for song_id, record in RECORDS.items():
        records.append({"kv": f"{progressions.KV}{song_id}", "value": json.dumps(record, ensure_ascii=False)})
    records.append({"kv": f"{progressions.KV}999", "value": json.dumps({"key": "C major", "sections": [
        {"key": "I V vi IV", "numerals": ["I", "V", "vi", "IV"]}]})})  # no such song: left out
    records.append({"kv": f"{progressions.KV}8", "value": json.dumps({"key": 3, "sections": [
        {"key": "I V vi IV", "numerals": ["I", "V", "vi", "IV"], "section": 5},
        {"key": "I V vi IV", "numerals": ["I", "V", "vi", "IV"], "section": ""},
        {"key": "I V vi IV", "numerals": ["I", "V", "vi", "IV"], "section": [1, "a"]},
        {"key": "I V vi IV", "numerals": ["I", "V", "vi", "IV"], "section": "Verse"},
        {"key": "I V vi IV", "numerals": ["I", "V", "vi", "IV"], "section": "Verse"},
        {"key": "I V vi IV", "numerals": ["I", "V", "vi", "IV"], "section": 1.5}]})})
    return records


SONGS_TEXTS = ("vi IV I V", "I IV V", "ii V I", "pop progression", "i bVI bIII bVII", "the Creep progression",
               "andalusian", "hello", "I V vi IV")


def songs_with_answer(conn, records: list[dict], texts: tuple[str, ...]) -> list:
    replay_fixture(conn, records)
    out = []
    for text in texts:
        wanted = progressions.read_progression(text)
        found = [] if wanted is None else progressions.songs_with(conn, wanted)
        out.append([[p.song.key, p.sections, p.key] for p in found])
    return out


def fresh(tmp_path, name: str):
    return db.connect(tmp_path / name / "caracole.sqlite")


WHOLE_PROGRESSIONS = 9  # tests/test_progressions.py's, kept whole; the rest by their digest


def progression_records(tmp_path) -> list[dict]:
    whole = [list(item) for item in HAND_PROGRESSIONS[:WHOLE_PROGRESSIONS]]
    more = [list(item) for item in HAND_PROGRESSIONS[WHOLE_PROGRESSIONS:]]
    out = [{"fn": HELPER + "sheet_progressions_of", "args": [whole, more],
            "out": {"whole": [progression_text(*i) for i in whole], "digests": [digest(progression_text(*i)) for i in more]}}]
    sheets = list(drawn_progression_sheets())
    variants = [list(v) for v in VARIANTS]
    out.append({"fn": HELPER + "sheet_progressions_digests", "args": [sheets, variants],
                "out": [digest([progression_text(cho, *v) for v in variants]) for cho in sheets]})
    rows = library_inputs()
    out.append({"fn": HELPER + "library_of", "args": [rows], "out": library_answer(fresh(tmp_path, "library"), rows)})
    pairs = [list(kv) for kv in progressions.catalogue().items()]
    out.append({"fn": HELPER + "catalogue_of", "args": [], "out": {"count": len(pairs), "sha256": sha256(pairs)}})
    keys = ["I V vi IV", "I", "", "I  V\tvi", " I ", "i ♭VI ♭III ♭VII", "I V"]
    out.append({"fn": HELPER + "label_of", "args": [keys], "out": [progressions.label(k) for k in keys]})
    every = [k for k in viewer_corpus.keys() if k.tonic in (0, 1, 6, 10)]
    out.append({"fn": HELPER + "key_words_of", "args": [[key_row(k) for k in every]],
                "out": [progressions.key_words(k) for k in every]})
    texts = list(dict.fromkeys(HAND_TEXTS))
    out.append({"fn": HELPER + "read_progression_of", "args": [texts], "out": [read_answer(t) for t in texts]})
    drawn = list(drawn_texts())
    batches = [drawn[i:i + TEXT_BATCH] for i in range(0, len(drawn), TEXT_BATCH)]
    out.append({"fn": HELPER + "read_progression_digests", "args": [batches],
                "out": [digest([read_answer(t) for t in batch]) for batch in batches]})
    fixture = songs_fixture()
    out.append({"fn": HELPER + "songs_with_of", "args": [fixture, list(SONGS_TEXTS)],
                "out": songs_with_answer(fresh(tmp_path, "songs"), fixture, SONGS_TEXTS)})
    return out


def test_progression_vectors_are_progressions_pys_answers(tmp_path):
    check(viewer_corpus.VIEWER_VECTORS / "progressions.jsonl",
          jsonl(progression_records(tmp_path), corpus="viewer/progressions", made_by=MADE_BY))


def test_every_branch_of_the_progressions_is_in_the_vectors(tmp_path):
    found = [progression_text(cho, *v) for cho in drawn_progression_sheets() for v in VARIANTS]
    assert None not in found[:3] and any('"contains": [{' in f for f in found if f)
    assert any('"section": null' in f for f in found if f) and any('"name": "the' in f for f in found if f)
    library = dict(library_answer(fresh(tmp_path, "library"), library_inputs()))
    assert 7 in library and 1 not in library and 200 not in library
    reads = [read_answer(t) for t in drawn_texts()]
    assert sum(r is None for r in reads) < len(reads) // 2 and any(r is None for r in reads)
    found = songs_with_answer(fresh(tmp_path, "songs"), songs_fixture(), SONGS_TEXTS)
    assert [identity_key("Zed", "Nothing"), ["5", "untitled section", "[1, 'a']", "Verse", "1.5"], ""] in found[0]
    assert [p[0] for p in found[-1] if "ngel" in p[0]] == [identity_key("Ángel", "Straße"), identity_key("ángel", "Strasse2")]
