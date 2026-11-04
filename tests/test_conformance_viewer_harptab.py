"""viewer/harptab.py for the phone: its constants as data, and what it answers, for :viewer's viewer.harptab.

The logic is Kotlin's (viewer.harptab.HarpTabs and its files); what harptab.py states as data is written here, from
the module itself, so a change to a preset, a word or a pattern regenerates what the phone reads. Two halves: the
reading (``vectors/viewer/harptab_read.jsonl``: the notations and their tokenizers, a line scanned, a tab's legends,
the candidates and their scores, the reading chosen, every reading weighed, a pin checked and read) and the layout
(``vectors/viewer/harptab_layout.jsonl``: the rows with their words and syllables, the sections, the tabber's notes
and prose, below).

**The data**, ``tests/conformance/data/caracole/viewer/harptab.json`` (caracole/viewer/harptab.json on the phone's
classpath, ``ViewerData.table("harptab")``; ``viewer_corpus.data_json``), each member a constant of harptab.py under
its own name, a dict's members in its order: the numbers (``TAB_STOP`` … ``ABOVE_SHARE``), ``BREATHS``, ``EFFECTS``,
``MEANINGS``, ``PLACES``; ``PRESETS``, ``DOTS`` and ``STAR_BENDS`` (a notation ``{"name", "symbols": [[text, means,
at, count], …], "bare", "fold"}``); ``_NUM``, ``_KINDS``, ``_SIGNS``, ``_CLOSE``, ``_LABEL_WORD``, ``PIN_NAMES``,
``_PIN_WORDS`` (``{word: [means, count]}``), ``_SAY``, ``_ORDER``, ``_VOWELS`` and ``_DIGRAPHS`` (sorted, a set has
no order); and ``patterns``, every compiled pattern as core.py.PyRegex reads it (``.pattern``, ``(?i)`` before it for
one compiled with ``re.I``, no other flag), ``_CHIPS``, ``_KEY_PATTERNS`` and ``_LEXICON`` (``[[means, pattern],
…]``) among them.

**The vectors** (``helpers.corpus.jsonl``), ``vectors/viewer/harptab_read.jsonl``. A symbol is ``[text, means, at,
count]``; a notation is ``"preset:<name>"`` for one of the presets, ``"star bends"`` for ``STAR_BENDS``, either with
``"+dots"`` when it is that with ``DOTS``, else ``{"name", "symbols", "bare", "fold"}``; a hole ``[hole, breath, bend,
over, button]``; a group ``[holes, kind, col, digit, text, hold, effects, join]`` (columns in code points, as
Python's); a scan ``[groups, coverage, unknown, label, used, free, prose, run, tokens, [is_row, missed, holey,
explained]]``, its ``used`` ``[[text, means, at, count, times], …]`` in the order it counted them; a reading
``[notation, source, explained, playable, score, margin, runner, confident, used, standard, said, spec]`` (its
notation the place of the tab's candidate it is, where it is one; ``spec``, ``spec_of``'s); a legend ``[lines,
symbols, at]``. A value kept by its digest is the first 16 hex digits of the SHA-256 of ``json.dumps(value,
ensure_ascii=False, separators=(",", ":"))`` (``short``). An answer that raised is ``{"err": its type's name,
"message": its words}``. Floats are Python's repr, compared to the bit. Each record is one of:

- ``tokens_of(notation)``: the patterns ``_tokens`` compiles for it, as Python writes them (``start``, ``before``,
  ``after``, ``apart``, ``join``, ``together``, null for none, and ``flags``, "i" or ""): for every notation the other
  records read a tab under (the presets, ``STAR_BENDS``, a legend's, a pin's), so ``_alt``'s order (longest first,
  then by code point), ``re.escape``'s rules and the lookbehinds are Python's to the character.
- ``scan_of(notations, lines)``: ``scan`` of each line under each notation (``[[answer, …] for each notation]``, one
  line's scan in ``WHOLE_EVERY`` whole, the others by digest): ``LITERALS_FROM``'s one-line strings with a
  digit in them (each under every preset, and ``STAR_BENDS``), ``ODD_LINES`` drawn lines of every notation's marks,
  words, brackets, odd digits and spaces, a batch of ``BATCH``, and ``ODD_NOTATION_LINES`` of each of
  ``ODD_NOTATIONS``' (notations made by hand, whose tokenizers sort, escape and fold what no preset has), and
  ``FOLD_LINES`` under ``FOLDED_I`` (a letter re.I reads where casefold doesn't: "ı" and "İ" an "i").
- ``legend_of(lines)``: ``legend`` of a batch of lines: each tab's, and seeded blocks of a legend's shapes.
- ``entry_of(items)``: ``[sym, meaning]`` → ``_entry``; ``meaning_of(texts)`` → ``_meaning``.
- ``tab_of(body, harp)``: the whole reading of one tab: ``{"chip", "legends", "in_legend", "candidates": [[notation,
  source], …], "found", "scored", "results": [[score, k, explained, playable], …], "scans": [each candidate's scans
  of every line, by digest], "read": the place of the candidate ``read`` keeps, "winner": its scans of the lines it
  scored (whole for ``WHOLE_TABS``, else by digest), "readings": ``readings(body, harp=)`` (the first's ``used``
  whole, the others' by digest; the first is ``read``'s), "pins": [[spec, the notation ``pinned`` reads, null, or its
  error, and for a notation ``read(notation=)``'s ``[reading (its ``used`` by digest), its scans of every line by
  digest]``, whole for ``WHOLE_TABS`` and ``FOLD_TABS``, else by its digest; null for none], …]}``.
  The tabs: tests/fixtures/harptabs/'s ``.txt`` tabs (``tabs/``,
  ``legends/``, ``spellings/``, ``layout/``), the ``<pre>`` of its three tab pages as ``harptabs.parse_tab_page``
  reads it, with the page's chip, ``LITERALS_FROM``'s strings of more than one line, and ``GENERATED`` tabs drawn in
  every notation (``generated_tab``: a melody a Richter harp plays, now and then a note none does, written in the
  notation's own marks with chords, shakes, splits, holds, bars, repeats, labels, words, a legend whose marks its
  holes carry, dots, the tabber's notes and seeded noise), some under a chip, and ``FOLD_TABS``. A body names its fixture
  (``{"fixture": …}``) or holds its text (``{"text": …}``).
- ``check_spec_of(specs)``: each spec → null, or the error ``check_spec`` raises: ``SPECS`` and every ``spec_of``
  above.
- ``text_of(texts)``: the Python string methods the port leans on beyond core.py's: ``[expand, swapcase,
  _fold_accents, _is_word alone, _is_word not alone]`` of each.

**The layout's vectors**, ``vectors/viewer/harptab_layout.jsonl``, in the shapes above. A row is ``["row", line,
lyric, label, parts, placement, confidence, trusted, above, digest]``: its ``parts`` each place's groups by their
places in the row's groups and the length of the words sung from there, in code points (the parts' words together end
``lyric.rstrip()``, so the lengths are the words), ``placement`` its Counter as a dict, ``digest`` its text, groups
and unknown by their digest (the groups are its line's scan, which harptab_read's records hold); a section's other
items ``["words", lines]``, ``["prose", text]``, ``["gap"]``, ``["legend", legend]``. Most answers are kept by their
digest, to keep the file within the viewer's budget (tests/conformance/budget.json): one compares as strictly, and
the whole ones, ``LayoutTest``'s cases and Python's own tell where an answer differs. Each record is one of:

- ``parse_of(tabs)``: each ``[body, harp, specs]`` → ``[layout for each spec]``, ``parse(body, harp=,
  notation=pinned(spec, body))`` (``spec`` null for none) as ``{"notes", "sections": [[label, chorus, items], …],
  "reading": its digest (``reading_digest``), "key", "missed", "chromatic", "legend", "harp", "convention",
  "readable", "kinds": each line's kind, a letter of ``_KINDS_SHORT``, "above": ``_above``'s}``, whole for
  ``LAYOUT_WHOLE``'s tabs read as they read, else by its digest. The tabs: harptab_read's (a text one as ``{"read":
  n}``, the body of that file's n-th ``tab_of`` record), and ``DRAWN`` tabs of ``layout_tab``'s; each read as it
  reads, then as its second reading's pin says (``spec_of``), where it has one that pins a notation.
- ``lines_of(tabs)``: each ``[body, places]`` → the digest of ``line_of``'s answer for each of the tab's lines there
  (``worded_lines``: every line of words, as ``parse`` prepares them), for ``LINES_FROM``'s tabs.
- ``line_of(lines)``: each line → ``[_is_label, _is_label(beside_row=True), _label_text (null unless either),
  _is_prose([line, "la la"]), _syllables, named_key([line])]``: ``EDGE_LINES``. ``named_key_of(blocks)``:
  ``named_key`` of a few blocks.
- ``syllable_starts_of(lyrics)``: ``EDGE_LYRICS`` and one in ``LYRICS_EVERY`` of the rows' words.
- ``align_of(items)``: ``[line, lyric, notation, reach, trusted]`` → ``align`` of the row ``scan(line)`` gives, with
  those words: ``[parts, placement]`` (``alignments``: holes on, near, inside and past the syllables, every row one
  ``align`` places).
- ``cuts_of(items)``: ``[lyric, [a, b], anchors, fixed]`` → ``_cuts``: drawn words, ``TIED_CUTS`` and ``MAX_CUTS``'s
  edges (``cut_inputs``).

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harptab.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import ast
import dataclasses
import functools
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

import pytest

from caracole import harptabs
from caracole.viewer import harptab
from caracole.viewer.harptab import (
    DOTS,
    PRESETS,
    STAR_BENDS,
    Notation,
    Reading,
    Scan,
    Symbol,
)
from helpers import viewer_corpus
from helpers.corpus import FIXTURES, check, fixture_bytes, fixture_ref, jsonl

MADE_BY = "tests/test_conformance_viewer_harptab.py"
HELPER = "test_conformance_viewer_harptab."
TESTS = Path(__file__).resolve().parent
LITERALS_FROM = ("test_viewer_harptab.py", "test_viewer_harptab_notation.py", "test_viewer_harptab_layout.py",
                 "test_viewer_harptab_page.py")
SEED = viewer_corpus.SEED + 700
BATCH = 50
GENERATED = 60  # tabs drawn
ODD_LINES = 240  # lines drawn for scan_of
TAB_PAGES = ("tab_25_piano-man.html", "tab_29910_knockin-on-heavens-door.html", "tab_89_la-bamba.html")
CHIPS = (None, None, None, "Diatonic", "Chromatic", "diatonic harmonica", "Key C")
WHOLE_EVERY = 40  # a scan_of record keeps one line's scan in this many whole, the others by their digest
WHOLE_TABS = ("harptabs/tabs/10228_", "harptabs/tabs/124_", "harptabs/legends/")  # winning scans kept whole

# The module's numbers, lists and patterns, by name; each pattern compiled with no flag but re.I.
NUMBERS = ("TAB_STOP", "HOLE_SHARE", "MISSED_SHARE", "REACH", "MAX_CUTS", "TAB_Q", "MARGIN", "ROW_TRUST",
           "LEGEND_WEIGHT", "ABOVE_LEAD", "ABOVE_SHARE")
LISTS = ("BREATHS", "EFFECTS", "MEANINGS", "PLACES")
PATTERNS = ("_DECOR", "_HOLD", "_TIME", "_ASIDE", "_DOT_BEFORE", "_LEAD_LABEL", "_LABEL_WORDS", "_LABEL_REST",
            "_CHORUS", "_URL", "_INSTRUCTION", "_WORD", "_LEGEND_LINE", "_PLACEHOLDER", "_TWO", "_THREE", "_BRACKET",
            "_SEPARATOR", "_VOWEL_RUN")

# Pins: what check_spec takes and what it refuses, in every way it says so.
SPECS: tuple[Any, ...] = (
    "signs", "brackets", "letters", "signs after", "barrett", "legend", "Signs", "", " signs", "mine", None, 1, 2.5,
    True, [], ["signs"], {}, {"as": "letters"}, {"as": "nope"}, {"as": 3}, {"as": None}, {"as": ["signs"]},
    {"as": {"a": 1}}, {"as": "legend"}, {"*": "bend"}, {"as": "signs", "*": "bend"}, {"(x)": "draw"},
    {"(4)": "draw"}, {"(4)": "bend"}, {"4": "blow"}, {"4": "bend"}, {"x": "draw"}, {"b4": "draw"}, {"4b": "blow"},
    {"4-4": "joins"}, {"4~4": "glissando"}, {"4-4": "hold"}, {"''": "double bend"}, {"b": "triple bend"},
    {"o": "overblow"}, {"(w)": "wah"}, {"*": "nope"}, {"*": 1}, {"*": None}, {"*": ["bend"]}, {" *": "bend"},
    {"* ": "bend"}, {"": "bend"}, {"   ": "bend"}, {"abcdefghijklm": "bend"}, {"abcdefghijkl": "mark"},
    {" *": "bend"}, {"𝄐": "hold"}, {"\t": "bend"}, {"[4]": "draw"}, {"{4}": "blow"}, {"N": "blow"},
    {"numero": "blow"}, {"4 4": "together"}, {"4,4": "together"}, {"4 and 4": "join"}, {"#": "blow"},
    {"as": "barrett", "+": "blow", "'": "bend"}, {"as": "letters", "B": "blow", "D": "draw", "*": "bend"},
    {"as": "signs", "(4)": "draw", "x": "mark"}, {"as": "brackets", "4": "draw"}, {"Σ": "bend"},
)


# --- the data -------------------------------------------------------------------------------------------------------


def _pattern(p: re.Pattern[str]) -> str:
    assert p.flags & ~(re.UNICODE | re.I) == 0, f"{p.pattern!r}: a flag the phone doesn't read"
    return p.pattern if re.compile(p.pattern).flags == p.flags else "(?i)" + p.pattern


def symbol_data(s: Symbol) -> list:
    return [s.text, s.means, s.at, s.count]


def notation_data(n: Notation) -> dict:
    return {"name": n.name, "symbols": [symbol_data(s) for s in n.symbols], "bare": n.bare, "fold": n.fold}


def harptab_constants() -> dict:
    out: dict[str, Any] = {name: getattr(harptab, name) for name in NUMBERS}
    out.update({name: list(getattr(harptab, name)) for name in LISTS})
    out["PRESETS"] = [notation_data(n) for n in PRESETS]
    out["DOTS"] = symbol_data(DOTS)
    out["STAR_BENDS"] = notation_data(STAR_BENDS)
    out["_NUM"] = harptab._NUM
    out["_KINDS"] = dict(harptab._KINDS)
    out["_SIGNS"] = harptab._SIGNS
    out["_CLOSE"] = dict(harptab._CLOSE)
    out["_LABEL_WORD"] = harptab._LABEL_WORD
    out["PIN_NAMES"] = list(harptab.PIN_NAMES)
    out["_PIN_WORDS"] = {word: list(v) for word, v in harptab._PIN_WORDS.items()}
    out["_SAY"] = dict(harptab._SAY)
    out["_ORDER"] = list(harptab._ORDER)
    out["_VOWELS"] = "".join(sorted(harptab._VOWELS))
    out["_DIGRAPHS"] = sorted(harptab._DIGRAPHS)
    out["patterns"] = {name: _pattern(getattr(harptab, name)) for name in PATTERNS}
    out["_CHIPS"] = {name: _pattern(p) for name, p in harptab._CHIPS.items()}
    out["_KEY_PATTERNS"] = [_pattern(p) for p in harptab._KEY_PATTERNS]
    out["_LEXICON"] = [[means, _pattern(p)] for means, p in harptab._LEXICON]
    return out


@functools.cache
def data_text() -> str:
    return viewer_corpus.data_json(harptab_constants())


def test_harptab_json_is_harptab_pys_constants():
    check(viewer_corpus.VIEWER_DATA / "harptab.json", data_text())


def test_the_data_reads_back_as_harptab_holds_it():
    data = json.loads(data_text())

    def notation(d: dict) -> Notation:
        return Notation(d["name"], tuple(Symbol(*s) for s in d["symbols"]), d["bare"], d["fold"])

    assert tuple(notation(d) for d in data["PRESETS"]) == PRESETS
    assert notation(data["STAR_BENDS"]) == STAR_BENDS and Symbol(*data["DOTS"]) == DOTS
    assert set(data["_VOWELS"]) == harptab._VOWELS and set(data["_DIGRAPHS"]) == harptab._DIGRAPHS
    for name, pattern in data["patterns"].items():
        own = getattr(harptab, name)
        assert re.compile(pattern).pattern == pattern and re.compile(pattern).flags == own.flags
    assert {k: tuple(v) for k, v in data["_PIN_WORDS"].items()} == harptab._PIN_WORDS


# --- the shapes of the records --------------------------------------------------------------------------------------


_KNOWN = {**{n: f"preset:{n.name}" for n in PRESETS}, STAR_BENDS: "star bends"}


def notation_row(n: Notation) -> Any:
    if n in _KNOWN:
        return _KNOWN[n]
    plain = Notation(n.name, tuple(s for s in n.symbols if s != DOTS), n.bare, n.fold)
    if plain != n and plain.changed((DOTS,)) == n and plain in _KNOWN:
        return _KNOWN[plain] + "+dots"
    return notation_data(n)


def hole_row(h: harptab.Hole) -> list:
    return [h.hole, h.breath, h.bend, h.over, h.button]


def group_row(g: harptab.Group) -> list:
    return [[hole_row(h) for h in g.holes], g.kind, g.col, g.digit, g.text, g.hold, list(g.effects), g.join]


def scan_row(s: Scan) -> list:
    return [[group_row(g) for g in s.groups], s.coverage, list(s.unknown), s.label,
            [[*key, times] for key, times in s.used.items()], s.free, s.prose, s.run, s.tokens,
            [s.is_row, s.missed, s.holey, s.explained]]


def notation_ref(n: Notation, candidates: list[tuple[Notation, str]]) -> Any:
    """A tab's notation: the place of the candidate it is, else ``notation_row``'s."""
    for k, (c, _) in enumerate(candidates):
        if c == n:
            return k
    return notation_row(n)


def reading_row(r: Reading, candidates: list[tuple[Notation, str]], whole: bool = True) -> dict:
    used = [[*key, times] for key, times in r.used]
    return [notation_ref(r.notation, candidates), r.source, r.explained, r.playable, r.score, r.margin, r.runner,
            r.confident, used if whole else short(used), r.standard, r.said(), harptab.spec_of(r)]


def legend_row(found: harptab.Legend) -> list:
    return [list(found.lines), [symbol_data(s) for s in found.symbols], list(found.at)]


def error(e: Exception) -> dict:
    return {"err": type(e).__name__, "message": str(e)}


def answer(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - what Python raises is the vector's
        return error(e)


def sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def short(value: Any) -> str:
    """A value's digest, its first 16 hex digits: a scan kept by it alone."""
    return sha256(value)[:16]


def scans_of(scans: list[Scan], whole: bool | None = None) -> list:
    """Each scan whole, or by its digest: every ``WHOLE_EVERY``-th whole where ``whole`` is None."""
    return [scan_row(s) if (whole if whole is not None else n % WHOLE_EVERY == 0) else short(scan_row(s))
            for n, s in enumerate(scans)]


def _batches(items: list) -> list[list]:
    return [items[i:i + BATCH] for i in range(0, len(items), BATCH)]


# --- the inputs -----------------------------------------------------------------------------------------------------


@functools.cache
def literals() -> tuple[str, ...]:
    """The string literals of the module's tests, in order, each once (no lone surrogate)."""
    found: dict[str, None] = {}
    for name in LITERALS_FROM:
        for node in ast.walk(ast.parse((TESTS / name).read_text("utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 4000:
                found[node.value] = None
    return tuple(s for s in found if not any(0xD800 <= ord(c) <= 0xDFFF for c in s))


def literal_lines() -> list[str]:
    return [s for s in literals() if "\n" not in s.strip("\n") and re.search(r"\d", s)]


def literal_bodies() -> list[str]:
    return [s for s in literals() if "\n" in s.strip("\n")]


# The holes a C harp plays: each hole's breaths, the bends down each has there, its overblow or overdraw.
_BENDS = {(1, "draw"): 1, (2, "draw"): 2, (3, "draw"): 3, (4, "draw"): 1, (6, "draw"): 1, (8, "blow"): 1,
          (9, "blow"): 1, (10, "blow"): 2}
_OVER = {1: "blow", 2: "blow", 3: "blow", 4: "blow", 5: "blow", 6: "blow", 7: "draw", 8: "draw", 9: "draw",
         10: "draw"}
_WORDS = ("la", "lo", "li", "love", "me", "do", "you", "know", "the", "road", "tomorrow", "heaven", "door", "knock",
          "sing", "harp", "blue", "moon", "río", "corazón", "Straße", "øl", "mere", "yeah", "oh", "baby", "night",
          "train", "whiskey", "amazing", "grace", "sweet", "sound", "tue", "te", "mon", "anci")
_SECTIONS = ("Verse", "Verse 1", "Verse 2", "Chorus", "[Chorus]", "Bridge", "Intro", "Outro", "Solo", "Riff",
             "Refrain", "Coro", "Estribillo", "Fill 1", "Chorus (x2)", "Verse:", "chorus-", "(Bridge)", "End",
             "Instrumental", "Next verse", "Repeat chorus")
_NOTES = ("Tabbed by someone", "I use an A harp", "Harp in Bb", "ARMONICA EN C", "Time: 3/4", "1:45",
          "www.example.com/tab", "https://harptabs.com/x", "Listen to the record", "Enjoy!", "Key: D",
          "Thanks to everyone", "Same as verse", "(nur Vers 1 + 2 !)", "played on a diatonic C harp", "harmonica: G",
          "Note: bend the 3", "This is a nice song to play")
_ODD = ("٣", "３", "𝟑", " ", "\t", "🎵", "é", "ß", "Σ", "K", "ſ", "$", "?", "^", "~", "|", "/", "\\", "§",
        "x2", "(x2)", "2x", "(2x)", "(hold)", "hold", "...", "----", "___", "*", ",", ";", ":", "=", ">", "·", "°",
        "<", "o", "O", "(", ")", "[", "]", "{", "}", "-", "+", "'", "’", '"', "”", "b", "B", "d", "D", "w", "(w)",
        "(W)", "(h)", "(DV)", "u", "x", "X", "ǅ", "İ", "ﬀ")
# Notations made by hand, whose tokenizers sort, escape and fold what no preset has: symbols beyond the BMP and in
# the private use area, a regex's specials, two of one letter, a letter whose case folds to another's (K, ſ).
ODD_NOTATIONS = (
    Notation("odd", (Symbol("𝄐", "hold", "after"), Symbol("ﬀ", "wah", "after"), Symbol("\ue000", "bend", "after"),
                     Symbol("x", "vibrato", "after"), Symbol("xo", "over", "after"), Symbol("[", "draw", "before"),
                     Symbol("((", "blow", "before"), Symbol("$", "join", "between"), Symbol("&", "together", "between"),
                     Symbol("~~", "glissando", "between"), Symbol("#", "mark", "after"), Symbol("u", "bend", "after", 2),
                     Symbol("{}", "draw", "around"), Symbol("^", "slide", "after"))),
    Notation("odd folded", (Symbol("ſ", "shake", "after"), Symbol("K", "trill", "after"), Symbol("Dr", "draw", "after"),
                            Symbol("bl", "blow", "after"), Symbol("ss", "bend", "after"), Symbol("é", "staccato", "after"),
                            Symbol("Ö", "wah", "after"), Symbol("\\", "join", "between"),
                            Symbol("+", "together", "between")), bare=None, fold=True),
    Notation("odd bare", (Symbol(".", "draw", "before"), Symbol("?", "bend", "before"), Symbol("|", "blow", "after"),
                          Symbol("*", "bend", "after"), Symbol(" ", "mark", "after")), bare="draw"),
)
ODD_NOTATION_LINES = 40  # lines of each drawn for scan_of
# A letter re.I reads as another that casefold keeps apart ("ı" and "İ" are an "i" to it, "K" a "k", "ſ" an "s"):
# the symbol a notation that folds means by it is the one its tokenizer read.
FOLDED_I = harptab.LETTERS.changed((Symbol("i", "wah", "after"), Symbol("k", "shake", "after"),
                                    Symbol("İ", "trill", "after", 1)), name="folded i")
FOLD_LINES = ("4bi 5di", "4bI 5dI", "4bı 5dı", "4bİ 5dİ", "4BK 5Dk", "4bſ", "4bİı -4", "4b i", "4bİİ", "ı4b")
FOLD_TABS = ("I = wah\nB = blow\nD = draw\n\n4B 5D 4BI 6D\n4Bı 5D\n",
             "4B 5D 4Bİ 6D\nla la la la\n4Bı 5D 6Dı\n\nİ = wah\nB = blow\nD = draw\n")
# The legends' lines: what tabs write, and odd symbols a tokenizer must escape, place and read.
_LEGEND_LINES = (
    "b = bend", "b = blow", "B= blow", "d = draw", "D= draw", "* = bend", "** = whole step bend", "(w) = Wah effect",
    "(W) = wah", "(h) = Hold", "(H) = hold", "~ = vibrato", "o = overblow", "O = overdraw", "' = half step bend",
    "'' = whole step bend", "''' = 1.5 step bend", "+ = blow", "- = draw", "-4 = draw", "4 = blow", "4' = bend",
    "(4) = draw", "(numero) = aspirar", "numero = soplar", "# = soplar", "(#) = aspirar", "x-x  Glisando",
    "x             Nota soplada", "(x)            Nota aspirada", "3-4 = slur", "4-4 = legato", "^ = bend",
    "$ = shake", "? = trill", "[x] = draw", "{ = bend", "\\ = bend", "| = bar", "/= A bar", "+- = draw",
    "𝄐 = hold", "u = bend", "U = bend", "Σ = draw", "k = blow", "< = slide", "* = button", "> = staccato",
    "s = shake", "t = trill", "v = vibrato", "g = glissando", "r = rest", "w = whole note", "h = half note",
    "4b = blow", "4d = draw", "4* = bend", "N = blow", "-N = draw", "(N) = draw", "### = blow", "1.5 = bend",
    "x = blow", "-x = draw", "x' = bend", "x'' = double bend", "x-x = joins", "x,x = chord", "xo = overblow",
    "b4 = bend", "B4 = bend", "4B = blow", "4D = draw", "4 => blow", "-4 -> draw", "4 - blow", "-4 – draw",
    "(4)b = bend", "(x)b: bend aspirado", "Key: D", "Chorus: hold on", "see www.example.com = draw",
)


def _hole(rng: random.Random) -> harptab.Hole:
    """A hole a C harp plays, now and then one it doesn't (a bend it hasn't, an overblow on the wrong breath)."""
    hole = rng.choice((1, 2, 3, 4, 4, 4, 5, 5, 6, 6, 6, 7, 8, 9, 10))
    breath = rng.choice(("blow", "draw"))
    bend = 0
    over = False
    if rng.random() < 0.18:
        bend = rng.randint(1, _BENDS.get((hole, breath), 1))
        if rng.random() < 0.1:
            bend = rng.randint(1, 3)
    elif rng.random() < 0.04:
        over = True
        breath = _OVER[hole] if rng.random() < 0.85 else breath
    return harptab.Hole(hole, breath, bend, over, rng.random() < 0.01)


def _bend_marks(rng: random.Random, count: int, marks: tuple[str, ...]) -> str:
    if count == 2 and rng.random() < 0.3:
        return rng.choice(('"', "”"))
    return rng.choice(marks) * count


def _written(rng: random.Random, h: harptab.Hole, style: str) -> str:
    """One hole as a tab of ``style`` writes it."""
    n = str(h.hole)
    if style in ("signs", "star bends"):
        sign = rng.choice(("-", "-", "-", "−", "–")) if h.breath == "draw" else rng.choice(("", "", "", "", "+"))
        bend = ""
        before = ""
        if h.bend:
            marks = ("'", "'", "’", "`", "b") if style == "signs" else ("*", "*", "'")
            if style == "signs" and rng.random() < 0.15:
                before = "b" * h.bend
            else:
                bend = _bend_marks(rng, h.bend, marks)
        out = before + sign + n + bend + ("o" if h.over else "")
        if h.button:
            out += rng.choice(("<", "*")) if style == "signs" else "<"
        return out
    if style == "brackets":
        bend = _bend_marks(rng, h.bend, ("'", "b", "’")) if h.bend else ""
        if h.breath == "draw":
            return f"({n}){bend}" if rng.random() < 0.7 else f"({n}{bend})"
        return rng.choice(("", "", "+")) + n + bend
    if style == "letters":
        letter = ("b" if h.breath == "blow" else "d")
        letter = letter.upper() if rng.random() < 0.3 else letter
        bend = _bend_marks(rng, h.bend, ("*", "*", "'")) if h.bend else ""
        return n + bend + letter
    if style == "signs after":
        sign = "+" if h.breath == "blow" else rng.choice(("-", "-", "−"))
        sign = "" if h.breath == "blow" and rng.random() < 0.3 else sign
        bend = _bend_marks(rng, h.bend, ("'", "’")) if h.bend else ""
        return n + sign + bend
    # barrett
    bend = _bend_marks(rng, h.bend, ("'", "’")) if h.bend else ""
    return n + ("+" if h.breath == "blow" else "") + bend


def _token(rng: random.Random, style: str) -> str:
    """A token of a row: a hole, holes together, a shake, a split, a run, with a hold, an effect or a bar now and
    then."""
    r = rng.random()
    if r < 0.07:
        holes = [_hole(rng) for _ in range(rng.randint(2, 3))]
        breath = holes[0].breath
        nums = sorted({h.hole for h in holes})
        if style in ("signs", "star bends", "signs after", "barrett"):
            inner = rng.choice((" ", "")).join(_written(rng, harptab.Hole(n, breath), style) for n in nums)
            token = rng.choice(("({})", "({})", "{{{}}}", "[{}]")).format(inner)
        elif style == "brackets":
            token = "(" + "".join(str(n) for n in nums) + ")"
        else:
            token = ",".join(str(n) for n in nums) + ("B" if breath == "blow" else "D")
    elif r < 0.12 and style in ("letters", "brackets"):
        token = "-".join(_written(rng, _hole(rng), style) for _ in range(rng.randint(2, 3)))
    else:
        token = _written(rng, _hole(rng), style)
    r = rng.random()
    if r < 0.06:
        token += rng.choice(("----", "--", "...", "___", "~", "~~"))
    elif r < 0.09:
        token += rng.choice(("(w)", "(h)", " (w)", "(W)", "(hold)", "o"))
    elif r < 0.11:
        token = rng.choice(("|", "||")) + " " + token
    return token


def _row(rng: random.Random, style: str, dots: bool) -> str:
    tokens = [_token(rng, style) for _ in range(rng.randint(2, 10))]
    if dots and rng.random() < 0.5:
        tokens = [("." + rng.choice(("", " ")) + t) if rng.random() < 0.3 else t for t in tokens]
    if rng.random() < 0.08:
        tokens.insert(rng.randrange(len(tokens) + 1), rng.choice(("x2", "(x2)", "2x", "|", "BOM BOM", "(percussions)",
                                                                  "tue", "$$$$", "(DV)", "3/4")))
    if rng.random() < 0.05:
        tokens.insert(rng.randrange(len(tokens) + 1), rng.choice(_ODD))
    line = ""
    for t in tokens:
        line += (rng.choice((" ", " ", " ", "  ", "   ", "\t")) if line else "") + t
    if rng.random() < 0.08:
        line = rng.choice(("Intro: ", "FILL 1 : ", "Chorus:", "(Riff 2): ", "SOLO 4:24 ", "Verse; ")) + line
    if rng.random() < 0.08:
        line = rng.choice(("  ", "\t", " ")) + line
    return line


def _legend_marks(block: list[str]) -> list[str]:
    """The symbols a legend's lines write, as they write them ("x'", "(w)", "^")."""
    return [m.group("sym") for line in block if (m := harptab._LEGEND_LINE.match(line))]


def _marked(rng: random.Random, row: str, marks: list[str]) -> str:
    """A row with its legend's marks on some of its holes: a mark's placeholder a hole, else the mark before or after
    the token."""
    if not marks:
        return row
    out = []
    for token in row.split(" "):
        if re.search(r"\d", token) and rng.random() < 0.35:
            sym = rng.choice(marks)
            hole = str(rng.randint(1, 10))
            if harptab._PLACEHOLDER.search(sym):
                token = harptab._PLACEHOLDER.sub(lambda _: hole, sym, count=rng.choice((1, 2)))
            else:
                token = sym + token if rng.random() < 0.4 else token + sym
        out.append(token)
    return " ".join(out)


def odd_notation_line(rng: random.Random, n: Notation) -> str:
    """A line of holes written with ``n``'s symbols, before, after and between them, and noise."""
    def of(at: str) -> list[str]:
        return [s.text for s in n.symbols if s.at == at]

    befores, afters, betweens = of("before"), of("after"), of("between")
    tokens = []
    for _ in range(rng.randint(2, 8)):
        t = str(rng.randint(1, 10))
        if befores and rng.random() < 0.4:
            t = rng.choice(befores) + t
        if afters and rng.random() < 0.5:
            t += rng.choice(afters) * rng.choice((1, 1, 2))
        if betweens and rng.random() < 0.25:
            t += rng.choice(betweens) + str(rng.randint(1, 10))
        if rng.random() < 0.1:
            t = rng.choice(("{", "(", "[")) + t + rng.choice(("}", ")", "]"))
        if n.fold and rng.random() < 0.3:
            t = t.swapcase()
        if rng.random() < 0.08:
            t = rng.choice(_ODD) + t
        tokens.append(t)
    return rng.choice((" ", "  ", "\t")).join(tokens)


def _lyric(rng: random.Random, count: int) -> str:
    words = [rng.choice(_WORDS) for _ in range(max(1, count + rng.randint(-2, 1)))]
    if rng.random() < 0.1:
        words[rng.randrange(len(words))] = rng.choice(("to-mor-row", "hea-vy,and", "air--", "des-ert", "BOOM"))
    text = " ".join(words)
    return text.capitalize() if rng.random() < 0.5 else text


def generated_tab(rng: random.Random, style: str) -> str:
    """A tab in ``style``'s notation (a preset's name, or "star bends"), drawn."""
    dots = rng.random() < 0.12
    lines: list[str] = []
    if rng.random() < 0.6:
        lines += [rng.choice(_NOTES) for _ in range(rng.randint(1, 3))] + [""]
    if rng.random() < 0.3:
        start = rng.randrange(len(_LEGEND_LINES))
        block = [_LEGEND_LINES[(start + k * rng.randint(1, 7)) % len(_LEGEND_LINES)] for k in range(rng.randint(2, 5))]
        legend_at_top = rng.random() < 0.5
        if legend_at_top:
            lines += block + [""]
    else:
        block, legend_at_top = [], True
    marks = _legend_marks(block) if rng.random() < 0.7 else []
    above = rng.random() < 0.15
    for _ in range(rng.randint(1, 4)):
        if rng.random() < 0.7:
            lines.append(rng.choice(_SECTIONS))
        for _ in range(rng.randint(1, 5)):
            row = _marked(rng, _row(rng, style, dots), marks)
            holes = len(row.split())
            sung = rng.random() < 0.7
            if sung and above:
                lines.append(_lyric(rng, holes))
            lines.append(row)
            if sung and not above:
                lines.append(_lyric(rng, holes))
            if rng.random() < 0.3:
                lines.append("")
        lines.append("")
        if rng.random() < 0.15:
            lines += [_lyric(rng, 6), _lyric(rng, 6), ""]
        if rng.random() < 0.1:
            lines += [rng.choice(_NOTES), ""]
    if block and not legend_at_top:
        lines += block
    if rng.random() < 0.05:
        lines.insert(rng.randrange(len(lines) + 1), "".join(rng.choice(_ODD) for _ in range(rng.randint(3, 12))))
    end = rng.choice(("\n", "\n", "\n", "\r\n", "\r"))
    return end.join(lines) + (end if rng.random() < 0.8 else "")


def odd_line(rng: random.Random) -> str:
    """A line of holes, marks and noise, for scan_of."""
    style = rng.choice([n.name for n in PRESETS] + ["star bends"])
    line = _row(rng, style, rng.random() < 0.2)
    for _ in range(rng.randint(0, 3)):
        at = rng.randrange(len(line) + 1)
        line = line[:at] + rng.choice(_ODD) + line[at:]
    return line


@functools.cache
def tabs() -> tuple[tuple[Any, str, str | None], ...]:
    """Every tab of the records: ``(body as a record holds it, its text, its chip)``."""
    out: list[tuple[Any, str, str | None]] = []
    rng = random.Random(SEED)
    for folder in ("tabs", "legends", "spellings", "layout"):
        for path in sorted((FIXTURES / "harptabs" / folder).glob("*.txt")):
            ref = fixture_ref(path)
            text = fixture_bytes(ref).decode("utf-8")
            out.append((ref, text, None))
            if rng.random() < 0.25:
                out.append((ref, text, rng.choice(CHIPS[3:])))
    for name in TAB_PAGES:
        page = harptabs.parse_tab_page(fixture_bytes(fixture_ref(f"harptabs/{name}")))
        out.append(({"text": page.body}, page.body, page.harp))
    for body in literal_bodies():
        out.append(({"text": body}, body, None))
    styles = [n.name for n in PRESETS] + ["star bends"]
    for k in range(GENERATED):
        style = styles[k % len(styles)]
        body = generated_tab(rng, style)
        chip = rng.choice(CHIPS) if style != "star bends" else rng.choice(("Diatonic", "Diatonic", None))
        out.append(({"text": body}, body, chip))
    out += [({"text": body}, body, None) for body in FOLD_TABS if body not in literal_bodies()]
    return tuple(out)


# --- the records ----------------------------------------------------------------------------------------------------


def tokens_row(n: Notation) -> dict:
    t = harptab._tokens(n)
    flags = re.I if n.fold else 0

    def src(p: re.Pattern | None) -> str | None:
        if p is None:
            return None
        assert p.flags & ~(re.UNICODE | re.I) == 0 and (p.flags & re.I) == flags
        return p.pattern

    return {"start": src(t.start), "before": src(t.before), "after": src(t.after), "apart": src(t.apart),
            "join": src(t.join), "together": src(t.together), "flags": "i" if n.fold else ""}


def _pins(body: str, found: list[Reading], candidates: list[tuple[Notation, str]], lines: list[str],
          chip: str | None, whole: bool) -> list:
    """Each pin of the tab: the notation it reads, and the tab read so (``read(notation=)``: "pinned", confident
    whatever its Q, no runner), ``[reading, its scans' digest]`` whole where ``whole`` says, else by its digest."""
    specs: list[Any] = ["legend", "signs", "letters"] + [harptab.spec_of(r) for r in found]
    specs += [{"as": "signs", "*": "bend"}, {"as": "brackets", "(x)": "draw", "x": "blow"}]
    out, seen = [], []
    for spec in specs:
        if spec in seen:
            continue
        seen.append(spec)
        got = answer(harptab.pinned, spec, body)
        if isinstance(got, Notation):
            reading, scans = harptab.read(lines, harp_chip=chip, notation=got)
            assert reading.source == "pinned" and reading.confident and reading.runner is None
            read_so = [reading_row(reading, candidates, whole=False), short([scan_row(s) for s in scans])]
            out.append([spec, notation_ref(got, candidates), read_so if whole else short(read_so)])
        else:
            out.append([spec, got, None])
    return out


def tab_record(ref: Any, body: str, chip: str | None, notations: dict) -> dict:
    found_chip, lines, legends, in_legend = harptab._prepared(body, chip)
    read_lines = ["" if n in in_legend else line for n, line in enumerate(lines)]
    candidates, found = harptab._candidates(read_lines, found_chip, legends)
    weighed = harptab._weighed(read_lines, candidates, found_chip, found)
    k = max(weighed.results, key=lambda r: (r[0], -r[1]))[1]
    reading = weighed.reading(k)
    readings = harptab.readings(body, harp=chip)
    for n, _ in candidates:
        notations.setdefault(n, None)
    out = {
        "chip": found_chip,
        "legends": [legend_row(b) for b in legends],
        "in_legend": sorted(in_legend),
        "candidates": [[notation_row(n), source] for n, source in candidates],
        "found": [symbol_data(s) for s in found],
        "scored": weighed.scored,
        "results": [[score, kk, explained, playable] for score, kk, explained, playable, _ in weighed.results],
        "scans": [short([scan_row(s) for s in scans]) for scans in weighed.scanned],
        "read": k,
        "winner": scans_of([weighed.scanned[k][i] for i in weighed.scored],
                           whole=isinstance(ref, dict) and ref.get("fixture", "").startswith(WHOLE_TABS)),
        "readings": [reading_row(r, candidates, whole=n == 0) for n, r in enumerate(readings)],
        "pins": _pins(body, readings, candidates, read_lines, found_chip,
                      whole=isinstance(ref, dict) and (ref.get("fixture", "").startswith(WHOLE_TABS)
                                                       or ref.get("text") in FOLD_TABS)),
    }
    assert reading_row(reading, candidates) == out["readings"][0]  # parse's is the first
    for spec in [harptab.spec_of(r) for r in readings]:
        pinned = harptab.pinned(spec, body)
        if pinned is not None:
            notations.setdefault(pinned, None)
    return {"fn": HELPER + "tab_of", "args": [ref, chip], "out": out}


@functools.cache
def records() -> tuple[dict, ...]:
    rng = random.Random(SEED + 1)
    notations: dict[Notation, None] = dict.fromkeys(PRESETS + (STAR_BENDS,))
    out: list[dict] = []

    tab_records = [tab_record(ref, body, chip, notations) for ref, body, chip in tabs()]

    lines = list(dict.fromkeys(literal_lines()))
    odd = list(dict.fromkeys(odd_line(rng) for _ in range(ODD_LINES)))
    def scan_record(ns: list[Notation], batch: list[str], every: int = WHOLE_EVERY) -> dict:
        return {"fn": HELPER + "scan_of", "args": [[notation_row(n) for n in ns], batch],
                "out": [[scan_row(s) if k % every == 0 else short(scan_row(s))
                         for k, s in enumerate(harptab.scan(line, notation=n) for line in batch)] for n in ns]}

    out += [scan_record(list(PRESETS) + [STAR_BENDS], batch) for batch in _batches(lines)]
    out += [scan_record(list(PRESETS), batch) for batch in _batches(odd)]
    for n in ODD_NOTATIONS:
        notations.setdefault(n, None)
        out.append(scan_record([n], [odd_notation_line(rng, n) for _ in range(ODD_NOTATION_LINES)], every=4))
    made = [n for n in list(notations)[len(PRESETS) + 1:] if n not in ODD_NOTATIONS]
    out += [scan_record(made[i:i + 8], [line for line in odd if rng.random() < 0.08])
            for i in range(0, len(made), 8)]
    notations.setdefault(FOLDED_I, None)
    out.append(scan_record([FOLDED_I, harptab.LETTERS], list(FOLD_LINES), every=1))

    blocks: list[list[str]] = [list(b) for b in (
        ["4b 5d", "", "(w) = Wah effect", "(h) = Hold", "* = bend", "D= draw", "b= blow"],
        ["Key: D", "Tuning: standard"], ["b = blow"], ["Chorus: x2", "Verse: 3"],
        ["see https://example.com/tab = draw", "https://example.com/b = blow"], ["4  -4  5", "-5  6  -6"])]
    for _ in range(60):
        block = [rng.choice(_LEGEND_LINES) for _ in range(rng.randint(1, 6))]
        if rng.random() < 0.3:
            block.insert(rng.randrange(len(block) + 1), rng.choice(("", "4 -4 5", "la la la", "Hey  hold  me")))
        blocks.append(block)
    out += [{"fn": HELPER + "legend_of", "args": [block], "out": [legend_row(b) for b in harptab.legend(block)]}
            for block in blocks]

    items = []
    for line in _LEGEND_LINES:
        m = harptab._LEGEND_LINE.match(line)
        if m:
            items.append([m.group("sym"), m.group("meaning")])
    items += [[rng.choice(("x", "(x)", "-x", "x-x", "4", "(4)b", "**", "N", "#", "b", "(numero)", "x,x")),
               rng.choice(("blow", "draw", "half step bend", "whole step bend", "1.5 step bend", "slur",
                           "Wah effect", "chord", "gliss", "nothing", "a bar", "tremolo", "button", "staccato",
                           "www.example.com", "three bends", "dos bends"))] for _ in range(80)]
    for batch in _batches(items):
        out.append({"fn": HELPER + "entry_of", "args": [batch],
                    "out": [answer(lambda s, m: None if (e := harptab._entry(s, m)) is None else symbol_data(e),
                                   s, m) for s, m in batch]})
    meanings = [m for _, m in items] + ["Soplado", "aspirar", "ÉXHALE", "Inhalé", "blowing and drawing", "draw/blow",
                                        "overblow", "over-draw", "holds", "sustain", "la wa wa", "headshake"]
    out.append({"fn": HELPER + "meaning_of", "args": [meanings], "out": [harptab._meaning(m) for m in meanings]})

    specs = list(SPECS)
    for record in tab_records:
        for reading in record["out"]["readings"]:
            if reading[-1] not in specs:
                specs.append(reading[-1])
    out += [{"fn": HELPER + "check_spec_of", "args": [batch], "out": [answer(harptab.check_spec, s) for s in batch]}
            for batch in _batches(specs)]

    texts = list(dict.fromkeys(list(_ODD) + list(_WORDS) + list(_LEGEND_LINES)[:20] + [
        "a\tb", "\tx", "abcdefg\th", "a\r\tb", "x\n\ty", "日本\t語", "🎵\tz", "a b", "ΑΣ", "ΑΣ Β", "aΣ", "Σa",
        "ΑΣ'", "ΑΣ.", "ΣΣ", "ǅungla", "ĲSSEL", "Ⓐⓑ", "ᾈ", "İstanbul", "Straße", "ﬃ", "(w)", "(W)", "bb", "Ⅻ",
        "café", "naïve", "Æon", "bcd", "rhythm", "x", "ab", "a", "4b", "øl", "œuvre", "Y", "z", "SB", "x2", "١٢"]))
    out += [{"fn": HELPER + "text_of", "args": [batch],
             "out": [[harptab.expand(t), t.swapcase(), harptab._fold_accents(t), harptab._is_word(t, alone=True),
                      harptab._is_word(t, alone=False)] for t in batch]} for batch in _batches(texts)]

    out += [{"fn": HELPER + "tokens_of", "args": [notation_row(n)], "out": tokens_row(n)} for n in notations]
    return tuple(out + tab_records)


def test_harptab_read_vectors_are_harptab_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "harptab_read.jsonl",
          jsonl(records(), corpus="viewer/harptab_read", made_by=MADE_BY))


def test_every_preset_and_every_kind_of_record_is_in_the_vectors():
    kinds = {r["fn"].removeprefix(HELPER) for r in records()}
    assert kinds == {"tab_of", "scan_of", "legend_of", "entry_of", "meaning_of", "check_spec_of", "text_of",
                     "tokens_of"}
    tab_records = [r["out"] for r in records() if r["fn"].endswith("tab_of")]
    read_as = {n.removesuffix("+dots") for out in tab_records if isinstance(n := out["candidates"][out["read"]][0], str)}
    assert {f"preset:{n.name}" for n in PRESETS} <= read_as
    sources = {out["readings"][0][1] for out in tab_records}
    assert sources == {"guessed", "legend"}
    errors = {json.dumps(a) for r in records() if r["fn"].endswith("check_spec_of") for a in r["out"] if a}
    assert len(errors) >= 15  # every way check_spec refuses, in its words


# --- the layout (lane harptab-layout): vectors/viewer/harptab_layout.jsonl -------------------------------------------

LAYOUT_SEED = SEED + 1000
# The tabs whose layout is kept whole (read as they read, unpinned): layout/'s small ones, between them rows with their
# words below and above, prose, the tabber's words, gaps and notes. Every other layout is kept by its digest.
LAYOUT_WHOLE = ("harptabs/layout/14346_", "harptabs/layout/16988_", "harptabs/layout/20960_",
                "harptabs/layout/23467_", "harptabs/layout/28721_")
LINES_FROM = ("harptabs/tabs/", "harptabs/layout/")  # the tabs whose lines of words lines_of reads
DRAWN = 24  # tabs drawn for the layout (layout_tab)
LYRICS_EVERY = 10  # of the rows' words, one in this many for syllable_starts_of
ALIGNMENTS = 150  # rows drawn for align_of
CUT_WORDS = 80  # words drawn for cuts_of
_KINDS_SHORT = {"legend": "l", "blank": "b", "holes": "h", "missed": "m", "text": "t"}
# Lines the layout reads as a section's name, a row's words, the tabber's prose or a harp's key, each way it reads
# them: test_viewer_harptab_layout.py's headings, and the edges of each rule (32 characters stripped, and 31, 33 and
# 34, "--", a colon, an address, a repeat mark, a key's sharp or flat).
EDGE_LINES = (
    "End of the road", "Break my heart", "Break it down", "Chorus", "INTRO", "fade:", "(D harp):", "Synth 1:",
    "bar 12:", "Refr.:", "(Chorus)", "[V1]", "2. Strophe:", "Harp: C", "A part:", "refrain :", "(Repetir 2x)",
    "Verse 2", "Harmonica solo", "Repeat chorus x2", "Chorus (x2)", "chorus-", "[Bridge]", "Verse", "-- ", "a--",
    "la la--", "x-", "one two three:", "one two three four:", "[one two three four five]", "(a b c d)",
    "(a b c d e)", "[]", "()", "[ ]", "Chorus: hold on", "Verse 1: la la la la", "www.example.com:",
    "see https://example.com", "Listen to the record", "Repeat after me", "Thanks!", "by the way", "tab by me",
    "next verses the same", "Same as before", "Then the bridge", "a" * 32 + ":", "a" * 33 + ":", "abc def " * 4,
    "Intro solo outro", "Estribillo", "Coro:", "estrofa 2", "Pre-chorus", "prechorus", "next verse", "last verse",
    "verso", "Melody", "Theme", "Part 2", "Ending", "end", "the end", "Break", "Interlude", "harp", "harmonica",
    "I use an A harp", "harp in Bb", "ARMONICA EN C", "A harp is a fine thing", "a harp in a minor key",
    "harmonica Diatonic", "A♭ harp", "F♯-harmonica", "harmonica key of F#", "armónica en D", "Bb-harp",
    "C harmonika", "harmonica: G", "Harp: C#m", "HARP IN e", "play it on a G  harp", "harp de A", "harp Ab.",
    "harpa en C", "AB harp", "Gb harmonica", "harmonica in B♭", "Øl, øl og mere øl.", "rhythm", "ÉXHALE", "日本語",
    "  indented words  ", "　wide space", "la\tla", "don't stop", "rock'n'roll", "4 5 6", "do 3, slip to 6",
    "a" * 31 + ":", "[" + "a" * 30 + "]", "(" + "a" * 30 + ")", "  " + "a" * 31 + "-  ", "Chorus " + "a" * 25,
    "[" + "a" * 31 + "]",
)
# Words a row is sung to, for syllable_starts and the rows drawn: hyphens, commas and stops inside a word and at its
# ends, letters of every script, digits.
EDGE_LYRICS = (
    "des-ert hea-vy,and", "On des-ert", "tomorrow", "air--", "la la la", "an - y - bo - dy", "-x x- -x-", "a--b",
    "a.b,c;d!e?f", "4-ever 2-day", "¿qué? ¡sí!", "Straße-weg", "日本-語 🎵-a", "corazón,mío", "x_y-z", "a,,b",
    "'tis-the", "rock'n'roll", "", "   ", " leading", "trailing   ", "ΑΣ-ΒΓ", "naïve-café", "a-1b", "a-_b",
)
# Words whose best cuts tie, or all but tie, between two ways that weigh each of _cuts' numbers apart (a cut's 0.6 a
# column from its hole, _rank's 0.8 and 1.6): each answer moves if one of them does.
TIED_CUTS = (
    ["nseadizt", [0, 8], [3, 4, 7], [0, 8]], ["aimifsw", [0, 7], [1, 2, 5], [0, 7]],
    ["pguipafvxr", [0, 10], [3, 4, 7], [0, 10]], ["paoxyw", [0, 6], [1, 4, 5], [0, 6]],
    ["tepfaushnpm", [0, 11], [3, 4, 9], [0, 11]], ["oehciygtzy", [0, 10], [1, 6, 8], [0, 10]],
    ["itxhuixxl", [0, 9], [1, 5, 8], [0, 9]], ["wrvhoyzbuii", [0, 11], [1, 10], [0, 11]],
    ["zphhiondeahl", [0, 12], [6, 11], [0, 12]], ["ziaerxl", [0, 7], [1, 4, 5], [0, 7]],
)


def parts_row(row: harptab.Row) -> list:
    """A row's parts: each place's groups by their places in the row's groups, and the length of the words sung from
    there (in code points; the parts' words together end the row's words, ``lyric.rstrip()``, so the lengths are
    the words)."""
    index = {id(g): n for n, g in enumerate(row.groups)}
    return [[[index[id(g)] for g in groups], len(text)] for groups, text in row.parts]


def row_item(row: harptab.Row) -> list:
    """A row: its line, words, label, parts (``parts_row``), placement, confidence, trusted, above, and its text,
    groups and what it left unknown by their digest (the groups are its line's scan, which harptab_read's records
    hold)."""
    joined = "".join(text for _, text in row.parts)
    assert row.lyric is None or row.lyric.rstrip().endswith(joined)
    return ["row", row.line, row.lyric, row.label, parts_row(row), dict(row.placement), row.confidence, row.trusted,
            row.above, short([row.text, [group_row(g) for g in row.groups], list(row.unknown)])]


def item_row(item: Any) -> list:
    if isinstance(item, harptab.Row):
        return row_item(item)
    if isinstance(item, harptab.Words):
        return ["words", list(item.lines)]
    if isinstance(item, harptab.Prose):
        return ["prose", item.text]
    if isinstance(item, harptab.Gap):
        return ["gap"]
    return ["legend", legend_row(item)]


def reading_digest(r: Reading) -> str:
    """A tab's reading by its digest: its notation as ``notation_row`` writes it, and the rest of ``reading_row``."""
    return short([notation_row(r.notation), r.source, r.explained, r.playable, r.score, r.margin, r.runner,
                  r.confident, [[*key, times] for key, times in r.used], r.standard, r.said()])


def tab_layout(t: harptab.Tab, kinds: str, above: bool) -> dict:
    return {"notes": t.notes,
            "sections": [[s.label, s.chorus, [item_row(i) for i in s.items]] for s in t.sections],
            "reading": reading_digest(t.reading), "key": t.key, "missed": t.missed, "chromatic": t.chromatic,
            "legend": legend_row(t.legend) if t.legend is not None else None, "harp": t.harp,
            "convention": t.convention, "readable": t.readable, "kinds": kinds, "above": above}


@dataclasses.dataclass(frozen=True)
class Laid:
    """One tab parsed for the records: as a record names it, read as it reads or as ``spec`` pins it."""
    ref: Any
    chip: str | None
    spec: Any
    tab: harptab.Tab
    layout: dict  # tab_layout's


def laid(ref: Any, body: str, chip: str | None, spec: Any, notation: Notation | None) -> Laid:
    """``parse(body, harp=chip, notation=)``, with its lines' kinds (each a letter of ``_KINDS_SHORT``) and whether it
    writes its words above its rows."""
    t = harptab.parse(body, harp=chip, notation=notation)
    found_chip, lines, legends, in_legend = harptab._prepared(body, chip)
    _, scans = harptab.read(["" if n in in_legend else line for n, line in enumerate(lines)], harp_chip=found_chip,
                            notation=notation, legends=legends)
    kinds = harptab._line_kinds(lines, scans, in_legend)
    above = harptab._above(lines, kinds, scans)
    return Laid(ref, chip, spec, t, tab_layout(t, "".join(_KINDS_SHORT[k] for k in kinds), above))


def layout_tabs() -> list[tuple[Any, str, str | None]]:
    """Every tab of harptab_read's records, a text one by its place among them (``{"read": n}``: the body of the
    n-th ``tab_of`` record of harptab_read.jsonl, so no body is written twice), and the layout's own drawn ones
    (``layout_tab``)."""
    rng = random.Random(LAYOUT_SEED)
    out = [(ref if "fixture" in ref else {"read": n}, body, chip) for n, (ref, body, chip) in enumerate(tabs())]
    out += [({"text": body}, body, rng.choice(CHIPS)) for body in (layout_tab(rng) for _ in range(DRAWN))]
    return out


@functools.cache
def layout_parses() -> tuple[tuple[tuple[Any, str, str | None], tuple[Laid, ...]], ...]:
    """Each tab of ``layout_tabs`` parsed as it reads, then as its second reading's pin says (``spec_of``) where it has
    one that pins a notation: the rows another notation draws, or a tab shown as written."""
    out = []
    for tab in layout_tabs():
        ref, body, chip = tab
        parses = [laid(ref, body, chip, None, None)]
        found = harptab.readings(body, harp=chip)
        if len(found) > 1:
            spec = harptab.spec_of(found[1])
            notation = harptab.pinned(spec, body)
            if notation is not None:
                parses.append(laid(ref, body, chip, spec, notation))
        out.append((tab, tuple(parses)))
    return tuple(out)


def _whole(p: Laid) -> bool:
    return p.spec is None and isinstance(p.ref, dict) and p.ref.get("fixture", "").startswith(LAYOUT_WHOLE)


_PROSE = ("Listen to the record first", "Repeat the chorus", "https://example.com/tab", "Enjoy it",
          "Play it slow", "Tabbed by me", "Then the bridge again", "Rest of the song the same")
_LABEL_ROWS = ("Intro: ", "FILL 1 : ", "(Riff 2): ", "Solo: ", "Verse; ", "Outro:", "Harp: ", "1: ")


def layout_tab(rng: random.Random) -> str:
    """A tab drawn for the layout: rows with their words under or above them, a section's name beside a row and words
    that start as one, a label leading a row, a line of holes too few to be a row, prose blocks, later verses, the
    harp's key in the tabber's notes, a slide, a legend, a row whose holes cut a long word."""
    style = rng.choice([n.name for n in PRESETS])
    above = rng.random() < 0.3
    lines: list[str] = []
    if rng.random() < 0.6:
        lines += [rng.choice(_NOTES + EDGE_LINES[70:90]) for _ in range(rng.randint(1, 3))]
        if rng.random() < 0.7:
            lines.append("")
    for _ in range(rng.randint(1, 4)):
        if rng.random() < 0.6:
            lines.append(rng.choice(_SECTIONS + EDGE_LINES[:30]))
        for _ in range(rng.randint(1, 5)):
            row = _row(rng, style, False)
            if rng.random() < 0.15:
                row = rng.choice(_LABEL_ROWS) + row
            if rng.random() < 0.05:
                row += rng.choice(("<", " -4<", " 5*"))
            holes = len(row.split())
            r = rng.random()
            words = (_lyric(rng, holes) if r < 0.6 else rng.choice(EDGE_LINES[:30]) if r < 0.7
                     else "a" + "bcdefghijklmnopqrstuvwxyz"[:rng.randint(3, 25)] if r < 0.75
                     else rng.choice(("do 3, slip to 6", " w    q q  q  q", "h  q  q   q q q q")) if r < 0.8
                     else None)
            if words is not None and above:
                lines.append(words)
            lines.append(row)
            if words is not None and not above:
                lines.append(words)
            if rng.random() < 0.3:
                lines.append("")
        lines.append("")
        r = rng.random()
        if r < 0.2:
            lines += [_lyric(rng, 6) for _ in range(rng.randint(2, 4))] + [""]
        elif r < 0.35:
            lines += [rng.choice(_PROSE)] + ([rng.choice(_PROSE)] if rng.random() < 0.5 else []) + [""]
        elif r < 0.45:
            lines += [rng.choice(_PROSE), _lyric(rng, 4), ""]
    if rng.random() < 0.1:
        lines += ["b = blow", "d = draw", ""]
    return "\n".join(lines) + "\n"


_ALIGN_TOKENS = ("4", "-4", "5", "-5", "6", "-6'", "(4 5)", "{-4 -5}", "[-2 -5]", "7o", "-3''", "8", "-8", "9", "10",
                 "+1", "-2", "3", "$", "(DV)", "x2", "BOM", "4----", "5~", "-4(w)", "|", "-4<", "tue")


def drawn_alignment(rng: random.Random) -> tuple[str, str]:
    """A row of holes and its words, drawn so its holes fall on, near, between and inside the words' syllables,
    before them and past their end."""
    r = rng.random()
    lyric = (rng.choice(EDGE_LYRICS) if r < 0.15 else
             " ".join("a" + "bcdefghijklmnopqrstuvwxyz"[:rng.randint(2, 25)] for _ in range(rng.randint(1, 2)))
             if r < 0.25 else _lyric(rng, rng.randint(1, 9)))
    if rng.random() < 0.2:
        lyric = rng.choice(("  ", " ", "      ")) + lyric
    cols = [s + rng.choice((0, 0, 0, 0, 1, -1, 2, -2, 3, -3, 4, -4)) for s in harptab.syllable_starts(lyric)
            if rng.random() < 0.8]
    cols += [rng.randint(0, len(lyric) + 6) for _ in range(rng.choice((0, 0, 1, 2, 4, 8)))]
    line = ""
    for c in sorted({max(0, c) for c in cols}):
        line = (line + " ") if line and c <= len(line) else line.ljust(c)
        line += rng.choice(_ALIGN_TOKENS)
    return line, lyric


_NOTATIONS_BY_ROW = {notation_row(n): n for n in PRESETS}


def alignments(rng: random.Random) -> list[list]:
    """``ALIGNMENTS`` rows for ``align_of``: ``[line, lyric, notation, reach, trusted]``, each one ``align`` can place
    (a trusted row with words has a group of holes, as every row ``parse`` trusts has: what it couldn't read goes with
    a hole), the others drawn again; a row of no holes is aligned played alone or shown as written."""
    notations = (harptab.SIGNS, harptab.SIGNS, harptab.SIGNS, harptab.BRACKETS, harptab.LETTERS)
    out: list[list] = []
    while len(out) < ALIGNMENTS:
        line, lyric = drawn_alignment(rng)
        notation = rng.choice(notations)
        reach = rng.choice((3, 3, 3, 3, 0, 1, 5))
        item = [line, lyric if rng.random() < 0.95 else None, notation_row(notation), reach, rng.random() < 0.95]
        groups = harptab.scan(line, notation=notation).groups
        if item[1] is not None and item[4] and groups and not any(g.holes for g in groups):
            continue
        out.append(item)
    return out


def drawn_cut(rng: random.Random) -> list:
    """A word with holes written inside it, for ``_cuts``: ``[lyric, [a, b], anchors, fixed]``."""
    letters = "aeiouybcdfghlmnprstvwxzáñ'"
    word = "".join(rng.choice(letters) for _ in range(rng.randint(2, 26)))
    before = rng.choice(("", "la ", "x-", "  "))
    lyric = before + word + rng.choice(("", " la", "--", ","))
    a, b = len(before), len(before) + len(word)
    inside = list(range(a + 1, b))
    anchors = sorted(rng.sample(inside, min(len(inside), rng.randint(1, 6)))) if inside else []
    fixed = sorted({a, b} | set(rng.sample(inside, min(len(inside), rng.choice((0, 0, 0, 1, 2))))))
    return [lyric, [a, b], anchors, fixed]


def cut_inputs(rng: random.Random) -> list[list]:
    """Drawn words, ``TIED_CUTS``, and the edges of ``MAX_CUTS``: one word's every way weighed (59 holes × 338
    places, just under), or none (59 × 339, just over: no cut), at exactly ``MAX_CUTS`` (100 × 200), and counts past
    any machine word."""
    out = [drawn_cut(rng) for _ in range(CUT_WORDS)] + [list(item) for item in TIED_CUTS]
    for holes, places in ((59, 338), (59, 339), (100, 200), (2, 3), (30, 77)):
        word = ("ba" * places)[:places + 1]
        anchors = sorted(rng.sample(range(1, places + 1), holes))
        out.append([word, [0, len(word)], anchors, [0, len(word)]])
    word = "a" + "bcdefghijklmnopqrstuvwxyz" * 3  # test_a_word_with_many_holes_inside_never_takes_long
    out.append([word, [0, len(word)], list(range(1, 60, 2)), [0, len(word)]])
    return out


def line_row(line: str) -> list:
    """A line as the layout reads it: whether it names a section, away from a row and beside one, its name then
    (null where it names none either way), whether a block it starts with a line of words is the tabber's prose, its
    syllables, and the harp's key it names."""
    label = harptab._is_label(line)
    beside = harptab._is_label(line, beside_row=True)
    return [label, beside, harptab._label_text(line) if label or beside else None,
            harptab._is_prose([line, "la la"]), harptab._syllables(line), harptab.named_key([line])]


def aligned(line: str, lyric: str | None, notation: Any, reach: int, trusted: bool) -> list:
    """``align`` of the row ``line`` scans to under ``notation`` with ``lyric`` (``trusted`` or not), at ``reach``:
    its parts (each place's groups by their places in the row) and placement."""
    row = harptab.Row(list(harptab.scan(line, notation=_NOTATIONS_BY_ROW[notation]).groups), lyric, trusted=trusted)
    harptab.align(row, reach)
    return [parts_row(row), dict(row.placement)]


def worded_lines(body: str) -> list[int]:
    """The places of a tab's lines of words (a letter in them), as ``parse`` prepares its lines."""
    return [n for n, line in enumerate(harptab._prepared(body, None)[1]) if re.search(r"[^\W\d_]", line)]


@functools.cache
def layout_records() -> tuple[dict, ...]:
    rng = random.Random(LAYOUT_SEED + 1)
    out: list[dict] = []
    parsed = layout_parses()
    for batch in _batches(list(parsed)):
        tabs_ = [[ref, chip, [p.spec for p in ps]] for (ref, _, chip), ps in batch]
        out.append({"fn": HELPER + "parse_of", "args": [tabs_],
                    "out": [[p.layout if _whole(p) else short(p.layout) for p in ps] for _, ps in batch]})
    worded = [(ref, worded_lines(body)) for ref, body, _ in layout_tabs()
              if isinstance(ref, dict) and ref.get("fixture", "").startswith(LINES_FROM)]
    prepared = {ref["fixture"]: harptab._prepared(body, None)[1] for ref, body, _ in layout_tabs() if "fixture" in ref}
    for batch in _batches(worded):
        out.append({"fn": HELPER + "lines_of", "args": [[[ref, numbers] for ref, numbers in batch]],
                    "out": [short([line_row(prepared[ref["fixture"]][n]) for n in numbers]) for ref, numbers in batch]})
    for batch in _batches(list(dict.fromkeys(EDGE_LINES))):
        out.append({"fn": HELPER + "line_of", "args": [batch], "out": [line_row(line) for line in batch]})
    blocks = [["la la", "I use an A harp", "harp in Bb"], ["harmonica Diatonic", "a harp in a minor key"], [],
              ["no key", "", "ARMONICA EN C", "G harp"]]
    out.append({"fn": HELPER + "named_key_of", "args": [blocks], "out": [harptab.named_key(b) for b in blocks]})
    lyrics = dict.fromkeys(r.lyric for _, ps in parsed for p in ps[:1] for r in p.tab.rows() if r.lyric is not None)
    for batch in _batches(list(dict.fromkeys(EDGE_LYRICS)) + list(lyrics)[::LYRICS_EVERY]):
        out.append({"fn": HELPER + "syllable_starts_of", "args": [batch],
                    "out": [harptab.syllable_starts(lyric) for lyric in batch]})
    for batch in _batches(alignments(rng)):
        out.append({"fn": HELPER + "align_of", "args": [batch], "out": [answer(aligned, *item) for item in batch]})
    for batch in _batches(cut_inputs(rng)):
        out.append({"fn": HELPER + "cuts_of", "args": [batch], "out": [cuts(*item) for item in batch]})
    return tuple(out)


def cuts(lyric: str, word: list[int], anchors: list[int], fixed: list[int]) -> list[int | None]:
    return harptab._cuts(lyric, (word[0], word[1]), anchors, fixed)


@functools.cache
def layout_jsonl() -> str:
    return jsonl(layout_records(), corpus="viewer/harptab_layout", made_by=MADE_BY)


def test_harptab_layout_vectors_are_harptab_pys_answers():
    check(viewer_corpus.VIEWER_VECTORS / "harptab_layout.jsonl", layout_jsonl())


def test_the_layout_vectors_hold_every_kind_of_record_and_of_item():
    """What the records hold, whole or by their digest: every kind of record, of item, of row and of placement."""
    records = [json.loads(line) for line in layout_jsonl().splitlines()[1:]]
    kinds = {r["fn"].removeprefix(HELPER) for r in records}
    assert kinds == {"parse_of", "lines_of", "line_of", "named_key_of", "syllable_starts_of", "align_of", "cuts_of"}
    parses = [p for _, ps in layout_parses() for p in ps]
    items = [i for p in parses for s in p.tab.sections for i in s.items]
    assert {type(i).__name__ for i in items} == {"Row", "Words", "Prose", "Gap", "Legend"}
    rows = [i for i in items if isinstance(i, harptab.Row)]
    assert {r.trusted for r in rows} == {True, False} and {r.above for r in rows} == {True, False}
    aligned_ = [out for r in records if r["fn"].endswith("align_of") for out in r["out"]]
    assert all(isinstance(out, list) for out in aligned_)  # no row align can't place
    assert {k for r in rows for k in r.placement} | {k for _, placement in aligned_ for k in placement} == {
        "snap", "split", "held", "gap"}
    assert {p.tab.readable for p in parses} == {True, False} and {p.tab.chromatic for p in parses} == {True, False}
    assert any(p.tab.key for p in parses) and any(p.tab.missed for p in parses)
    assert any(p.spec is not None for p in parses)  # read as pinned
    whole = [out for r in records if r["fn"].endswith("parse_of") for outs in r["out"] for out in outs
             if isinstance(out, dict)]
    assert len(whole) == len(LAYOUT_WHOLE)
    assert {item[0] for out in whole for s in out["sections"] for item in s[2]} >= {"row", "words", "prose", "gap"}
    assert {item[8] for out in whole for s in out["sections"] for item in s[2] if item[0] == "row"} == {True, False}
    cuts = [out for r in records if r["fn"].endswith("cuts_of") for out in r["out"]]
    assert any(all(c is None for c in out) for out in cuts) and any(None not in out for out in cuts)
    assert {len(line.strip()) for line in EDGE_LINES} >= {31, 32, 33, 34}


@pytest.mark.parametrize("rank", [(0.8, 0.81), (0.8, 0.79), (1.6, 1.61), (1.6, 1.59)])
def test_the_tied_cuts_tell_each_of_ranks_numbers_apart(monkeypatch, rank):
    """``TIED_CUTS`` answer otherwise when one of ``_rank``'s numbers moves by a hundredth either way."""
    want = [cuts(*item) for item in TIED_CUTS]
    was, now = rank
    real = harptab._rank

    def moved(lyric: str, k: int) -> float:
        got = real(lyric, k)
        return now if got == was else got

    monkeypatch.setattr(harptab, "_rank", moved)
    assert [cuts(*item) for item in TIED_CUTS] != want
