"""Python's format specs, rounding, difflib and East Asian width, for the phone: the vectors core/py/PyFormat.kt,
PySequence.kt and PyUnicode.eastAsianWidth answer (PyFormatTest, PySequenceTest; core.testing.replays.PyFormatRecords,
which the py area's PyReplay runs on the device: waiting on lane py-sites, whose PyReplay and test_conformance_py.py
these join).

What the phone's ports of caracole's text lean on: f-strings' ``f`` and ``%`` specs (Megalobiz's LRC stamps,
``{s:05.2f}``; a coverage's ``{x:.0%}``; a Q's ``{q:.2f}``), ``round(x)`` (LRCLIB's and Megalobiz's duration),
``difflib.SequenceMatcher(None, a, b, autojunk=False)`` (harpfit.py's lines matched word by word) and
``unicodedata.east_asian_width`` (chordpro.py's, page.py's and pdf_text.py's widths, youtube.py's wide letters). The
JVM's ``String.format`` is its locale's and rounds half-up on a decimal string; Python rounds half-even on the exact
binary value, and the phone must too.

Vectors, tests/conformance/vectors/py/ (a float that isn't finite is written ``"inf"``, ``"-inf"`` or ``"nan"``):

- ``format_numbers.jsonl``: ``format(x)`` records, ``out`` each spec of ``SPECS`` by name and what ``format(x, spec)``
  answered (``0W.Nf`` is ``PyFormat.fixed(x, N, W, zero=true)``, ``W.Nf`` with spaces, ``.N%`` ``PyFormat.percent``),
  over exact ties at every digit (``(2k+1)/2^(d+1)``, half of the last digit kept, and their neighbours a unit of the
  last place away), tied after ``%``'s ``x * 100``, curated values, durations as Megalobiz's stamps read them and
  seeded random doubles of every magnitude; then ``round(x)`` records, ``round()`` with no digits (half-even: a
  whole number), or ``err`` where Python raises (``ValueError`` for NaN, ``OverflowError`` for an infinity). Only
  values whose round() fits in a Long are asked: ``PyFormat.roundHalfEven`` answers a Long and throws past it.
- ``format_sequence.jsonl``: ``difflib.SequenceMatcher`` records, ``args`` the two sequences (a string stands for its
  characters, a list for its strings), ``out`` its ``ratio`` and ``matching_blocks`` (each ``[a, b, size]``, the
  last ``[len(a), len(b), 0]``): curated pairs, seeded random pairs over small alphabets (``find_longest_match``'s
  ties, the recursion, adjacent blocks merged; past 200 elements, where autojunk would have dropped the popular
  ones), and the words of the harmonica tab fixtures' lines as ``harpfit.words`` reads them, each line against the
  next and against itself with a word dropped, doubled or changed.
- ``format_width.jsonl``: one ``unicodedata.east_asian_width.code_points`` record, ``[start, end, width]`` runs over
  every code point, ``N`` left out (the table data/caracole/unicode/east_asian_width.txt holds the same, written by
  tests/test_conformance_unicode.py).
"""

from __future__ import annotations

import difflib
import functools
import itertools
import math
import random
import struct
import unicodedata

from helpers.corpus import FIXTURES, VECTORS, check, jsonl

from caracole.viewer.harpfit import words

MADE_BY = "tests/test_conformance_py_format.py"
OUT = VECTORS / "py"
SEED = 20261104
MAX = 0x110000
LONG = 2 ** 63
SPECS = (".0f", ".1f", ".2f", ".3f", "5.1f", "05.2f", "06.3f", "08.2f", ".0%", ".1%", ".2%")


def _f(x: float) -> float | str:
    """A float as JSON holds it: a non-finite one by name."""
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return x


# --- format_numbers.jsonl --------------------------------------------------------------------------------------


CURATED = [0.0, -0.0, math.inf, -math.inf, math.nan, 0.5, 1.5, 2.5, -2.5, -0.5, 0.125, 0.375, 2.675, 1.005, 0.005,
           0.045, 0.0005, 94.745, 99.995, 99.95, 9.995, 59.995, 59.999, 59.9951, 0.1, 0.2, 0.3, 0.1 + 0.2, 1 / 3,
           2 / 3, -1 / 3, 66.66666666666667, 85.71428571428571, 0.725, 0.835, 0.615, 1.255, 8.345, 12.345, 123456.789,
           1e16, 2.0 ** 53, 2.0 ** 53 + 2, 4503599627370495.5, 1e22, 1e23, 1e-7, -1e-7, 1e-300, 5e-324, -5e-324,
           2.2250738585072014e-308, 1.7976931348623157e308, -1.7976931348623157e308, 1e300, 0.999, 0.9995, 0.99995,
           -0.001, -0.004, -0.005, -0.0049, 9.5, 10.5, 99.5, 999.5, 0.0125, 0.00125, 0.000125, 0.07, 0.29, 0.57,
           1.15, 1.25, 1.35, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]


def _ties() -> list[float]:
    """Exact ties at each number of digits kept (``(2k+1)/2^(d+1)``, a whole number added, lies halfway at ``d``
    digits after the point: no other tie is a double), their negatives and their neighbours a unit of the last place
    away."""
    ties = sorted({whole + (2 * k + 1) / 2 ** (digits + 1)
                   for digits in range(5) for k in range(6) for whole in (0, 1, 42, 123456)})
    assert all(any(_is_tie(x, d) for d in range(5)) for x in ties)
    near = [math.nextafter(x, math.inf) for x in ties] + [math.nextafter(x, -math.inf) for x in ties]
    return ties + [-x for x in ties] + near


def _is_tie(x: float, digits: int) -> bool:
    """Whether ``x``'s exact value lies halfway between two numbers of ``digits`` decimals."""
    from fractions import Fraction

    scaled = Fraction(x) * 10 ** digits
    return scaled.denominator == 2


def _percent_ties() -> list[float]:
    """Values whose ``x * 100`` (in double, as ``%`` takes it) is an exact tie at 0 to 2 digits."""
    out = []
    for n in range(0, 2000, 37):
        for x in (n / 1000, n / 10000, n / 100000, (2 * n + 1) / 2000):
            if any(_is_tie(x * 100, d) for d in range(3)):
                out.append(x)
    return out


def _random_doubles(rng: random.Random) -> list[float]:
    out = [rng.uniform(-1000, 1000) for _ in range(60)]
    out += [rng.uniform(0, 1) for _ in range(50)]  # shares, for %
    out += [rng.randrange(0, 60000) / 1000 for _ in range(50)]  # Megalobiz's ms % 60000 / 1000
    out += [round(rng.uniform(0, 100), 3) + 0.0005 for _ in range(30)]
    out += [rng.uniform(-1, 1) * 10 ** rng.randrange(-12, 25) for _ in range(40)]
    bits = [struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))[0] for _ in range(60)]
    out += [x for x in bits if math.isfinite(x) and abs(x) < 1e60][:20]  # every magnitude, but a page of digits
    return out


@functools.cache
def _numbers() -> list[float]:
    rng = random.Random(SEED)
    seen: set[bytes] = set()
    out = []
    for x in CURATED + _ties() + _percent_ties() + _random_doubles(rng):
        key = struct.pack("<d", x)  # -0.0 is not 0.0; every NaN is one
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def _rounded(x: float) -> dict:
    try:
        return {"out": round(x)}
    except (ValueError, OverflowError) as e:
        return {"err": type(e).__name__}


ROUND = [0.5, 1.5, 2.5, 3.5, -0.5, -1.5, -2.5, 0.49999999999999994, 0.5000000000000001, 4503599627370495.5,
         4503599627370497.0, 2.0 ** 52 + 0.5, 2.0 ** 62, -(2.0 ** 63), 9.223372036854775e18, 1e18, -1e18, 1e-300]


def numbers_records() -> list[dict]:
    records: list[dict] = []
    for x in _numbers():
        records.append({"fn": "format", "args": [_f(x)], "out": {spec: format(x, spec) for spec in SPECS}})
    rng = random.Random(SEED + 1)
    halves = [n + 0.5 for n in range(-12, 13)] + [rng.randrange(-10 ** 6, 10 ** 6) + 0.5 for _ in range(40)]
    for x in ROUND + halves + _numbers():
        if math.isfinite(x) and abs(round(x)) >= LONG:
            continue  # past a Long: PyFormat.roundHalfEven throws (PyFormatTest)
        records.append({"fn": "round", "args": [_f(x)], **_rounded(x)})
    return records


def test_format_numbers_jsonl():
    check(OUT / "format_numbers.jsonl", jsonl(numbers_records(), corpus="py/format_numbers", made_by=MADE_BY))


def test_the_ties_are_ties_and_the_specs_round_them_half_even():
    ties = _ties()
    assert sum(1 for x in ties if any(_is_tie(x, d) for d in range(5))) >= 100
    assert format(0.125, ".2f") == "0.12" and format(0.375, ".2f") == "0.38" and format(2.5, ".0f") == "2"
    assert format(0.125, ".0%") == "12%"  # 12.5 exactly, to the even


# --- format_sequence.jsonl -------------------------------------------------------------------------------------


CURATED_PAIRS = [
    ("", ""), ("", "a"), ("a", ""), ("a", "a"), ("ab", "ba"), ("abxcd", "abcd"), ("qabxcd", "abycdf"),
    (" abcd", "abcd abcd"), ("abcd", "bcde"), ("aaaa", "aa"), ("aa", "aaaa"), ("abab", "baba"), ("abcabc", "cba"),
    ("private Thread currentThread;", "private volatile Thread currentThread;"), ("tide", "diet"),
    ("abcdefg", "gfedcba"), ("ababababab", "bababa"), ("xyz", "abc"), ("宋冬野安和桥", "安和桥宋冬野"),
    ("a\U0001f600b", "\U0001f600ab"), ("aXbXc", "aYbYc"),
    (["the", "road", "is", "long"], ["the", "long", "road"]),
    (["made", "up", "words", "for", "row", "one"], ["made", "up", "words", "for", "row", "two"]),
    (["la", "la", "la", "la"], ["la", "la"]), ([""], [""]), (["", "a"], ["a", ""]),
]


def _random_pairs(rng: random.Random) -> list[tuple[str, str]]:
    out = []
    for _ in range(600):
        alphabet = "abcde"[: rng.randrange(1, 6)]
        out.append(tuple("".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 24))) for _ in range(2)))
    for _ in range(12):  # past 200 elements, the popular ones kept (autojunk=False)
        alphabet = "abcdefgh"[: rng.randrange(2, 9)]
        a = "".join(rng.choice(alphabet) for _ in range(rng.randrange(150, 260)))
        b = "".join(rng.choice(alphabet) for _ in range(rng.randrange(200, 260)))
        out.append((a, b))
    for _ in range(50):  # one an edit of the other
        a = "".join(rng.choice("abcdefghij") for _ in range(rng.randrange(5, 40)))
        b = list(a)
        for _ in range(rng.randrange(1, 5)):
            at = rng.randrange(0, len(b) + 1)
            choice = rng.randrange(3)
            if choice == 0 and b:
                del b[min(at, len(b) - 1)]
            elif choice == 1:
                b.insert(at, rng.choice("abcdefghij"))
            elif b:
                b[min(at, len(b) - 1)] = rng.choice("abcdefghij")
        out.append((a, "".join(b)))
    return out


def _tab_lines() -> list[list[str]]:
    """The words of each line of the harmonica tab fixtures that has any letter, as harpfit.words reads them."""
    out = []
    for path in sorted((FIXTURES / "harptabs" / "tabs").glob("*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            said = words(line)
            if any(c.isalpha() for w in said for c in w):
                out.append(said)
    return out


def _harvested(rng: random.Random) -> list[tuple[list[str], list[str]]]:
    lines = _tab_lines()
    out = []
    for i, line in enumerate(lines):
        for other in lines[i + 1: i + 2]:
            out.append((line, other))
        edited = list(line)
        at = rng.randrange(len(edited))
        match rng.randrange(3):
            case 0:
                del edited[at]
            case 1:
                edited.insert(at, edited[at])
            case _:
                edited[at] = edited[at][::-1]
        out.append((line, edited))
    return out


def _sequence(x: str | list[str]) -> list[str]:
    return list(x)


def sequence_records() -> list[dict]:
    rng = random.Random(SEED + 2)
    records = []
    for a, b in itertools.chain(CURATED_PAIRS, _random_pairs(rng), _harvested(rng)):
        matcher = difflib.SequenceMatcher(None, _sequence(a), _sequence(b), autojunk=False)
        records.append({"fn": "difflib.SequenceMatcher", "args": [a, b],
                        "out": {"ratio": matcher.ratio(),
                                "matching_blocks": [list(m) for m in matcher.get_matching_blocks()]}})
    return records


def test_format_sequence_jsonl():
    check(OUT / "format_sequence.jsonl", jsonl(sequence_records(), corpus="py/format_sequence", made_by=MADE_BY))


def test_the_harvest_reads_words_and_the_long_pairs_would_have_been_autojunked():
    assert len(_tab_lines()) >= 100
    rng = random.Random(SEED + 2)
    long = [(a, b) for a, b in _random_pairs(rng) if len(b) >= 200]
    differ = sum(1 for a, b in long if difflib.SequenceMatcher(None, a, b).ratio()
                 != difflib.SequenceMatcher(None, a, b, autojunk=False).ratio())
    assert differ >= len(long) // 2  # so the vectors hold autojunk=False to its word


# --- format_width.jsonl ----------------------------------------------------------------------------------------


@functools.cache
def width_runs() -> list[list]:
    """``unicodedata.east_asian_width`` over every code point, as ``[start, end, width]`` runs, ``N`` left out."""
    widths = list(map(unicodedata.east_asian_width, map(chr, range(MAX))))
    changes = [0, *itertools.compress(range(1, MAX), map(str.__ne__, widths[1:], widths[:-1])), MAX]
    return [[a, b - 1, widths[a]] for a, b in itertools.pairwise(changes) if widths[a] != "N"]


def width_records() -> list[dict]:
    return [{"fn": "unicodedata.east_asian_width.code_points", "args": [], "out": width_runs()}]


def test_format_width_jsonl():
    check(OUT / "format_width.jsonl", jsonl(width_records(), corpus="py/format_width", made_by=MADE_BY))


def test_the_widths_name_every_value_python_has():
    assert {w for _, _, w in width_runs()} == {"W", "F", "H", "Na", "A"}

