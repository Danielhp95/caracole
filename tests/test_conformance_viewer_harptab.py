"""viewer/harptab.py for the phone: its constants as data, and what it answers, for :viewer's viewer.harptab.

The logic is Kotlin's (viewer.harptab.HarpTabs and its files); what harptab.py states as data is written here, from
the module itself, so a change to a preset, a word or a pattern regenerates what the phone reads. This is the
reading half (lane harptab-read): the notations and their tokenizers, a line scanned, a tab's legends, the candidates
and their scores, the reading chosen, every reading weighed, a pin checked and read. Lane harptab-layout adds the
layout's records (rows, words, syllables) to ``vectors/viewer/harptab_layout.jsonl``.

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
  ``ODD_NOTATIONS``' (notations made by hand, whose tokenizers sort, escape and fold what no preset has).
- ``legend_of(lines)``: ``legend`` of a batch of lines: each tab's, and seeded blocks of a legend's shapes.
- ``entry_of(items)``: ``[sym, meaning]`` → ``_entry``; ``meaning_of(texts)`` → ``_meaning``.
- ``tab_of(body, harp)``: the whole reading of one tab: ``{"chip", "legends", "in_legend", "candidates": [[notation,
  source], …], "found", "scored", "results": [[score, k, explained, playable], …], "scans": [each candidate's scans
  of every line, by digest], "read": the place of the candidate ``read`` keeps, "winner": its scans of the lines it
  scored (whole for ``WHOLE_TABS``, else by digest), "readings": ``readings(body, harp=)`` (the first's ``used``
  whole, the others' by digest; the first is ``read``'s), "pins": [[spec, the notation ``pinned`` reads, null, or its
  error], …]}``. The tabs: tests/fixtures/harptabs/'s ``.txt`` tabs (``tabs/``,
  ``legends/``, ``spellings/``, ``layout/``), the ``<pre>`` of its three tab pages as ``harptabs.parse_tab_page``
  reads it, with the page's chip, ``LITERALS_FROM``'s strings of more than one line, and ``GENERATED`` tabs drawn in
  every notation (``generated_tab``: a melody a Richter harp plays, now and then a note none does, written in the
  notation's own marks with chords, shakes, splits, holds, bars, repeats, labels, words, a legend whose marks its
  holes carry, dots, the tabber's notes and seeded noise), some under a chip. A body names its fixture
  (``{"fixture": …}``) or holds its text (``{"text": …}``).
- ``check_spec_of(specs)``: each spec → null, or the error ``check_spec`` raises: ``SPECS`` and every ``spec_of``
  above.
- ``text_of(texts)``: the Python string methods the port leans on beyond core.py's: ``[expand, swapcase,
  _fold_accents, _is_word alone, _is_word not alone]`` of each.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harptab.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

from caracole import harptabs
from caracole.viewer import harptab
from caracole.viewer.harptab import (
    DOTS,
    PRESET,
    PRESETS,
    SIGNS,
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


def _pins(body: str, found: list[Reading], candidates: list[tuple[Notation, str]]) -> list:
    specs: list[Any] = ["legend", "signs", "letters"] + [harptab.spec_of(r) for r in found]
    specs += [{"as": "signs", "*": "bend"}, {"as": "brackets", "(x)": "draw", "x": "blow"}]
    out, seen = [], []
    for spec in specs:
        if spec in seen:
            continue
        seen.append(spec)
        got = answer(harptab.pinned, spec, body)
        out.append([spec, got if isinstance(got, dict) and "err" in got
                    else None if got is None else notation_ref(got, candidates)])
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
        "pins": _pins(body, readings, candidates),
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
