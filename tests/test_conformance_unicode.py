"""Python's Unicode and string semantics, for the phone: the tables core/py/PyUnicode.kt reads, and the vectors
its tests check (core/py/: PyUnicodeTest, PyTest, PyRegexTest).

caracole's keys and searches lean on Python 3.14's ``unicodedata`` (16.0.0) and str methods: NFKD/NFKC/NFC,
``combining``, ``category``, ``"LATIN" in name(c)``, ``lower()`` with its Final_Sigma rule, ``upper()``,
``casefold()``, the ``is*`` predicates, and ``re``'s ``\\w \\s \\d \\b`` and IGNORECASE. The JDK has Unicode 13 and
Android's ICU varies by device, so the phone never asks either: it reads these tables, made from Python's own
answers.

Runtime data, tests/conformance/data/caracole/unicode/ (on the phone's classpath as caracole/unicode/). Every file is
UTF-8 text, ``\\n`` line ends, a first ``#`` line naming it and what made it; numbers are hex code points unless
said:

- ``flags.txt``: ``start end mask`` lines, the maximal runs of code points sharing a mask of the bits below, a mask
  of 0 left out. Bit 0 ``str.isalnum``, 1 ``isalpha``, 2 ``isdecimal``, 3 ``isdigit``, 4 ``isnumeric``, 5
  ``isspace``, 6 re's ``\\w`` (isalnum or ``_``), 7 ``isprintable``, 8 ``"LATIN" in unicodedata.name(c, "")``, 9
  cased (``islower() or isupper() or istitle()``: the Cased property), 10 case-ignorable (Final_Sigma's
  Case_Ignorable, read from ``lower()`` itself).
- ``category.txt``: ``start end Xx`` lines, the runs of one ``unicodedata.category``; ``Cn`` left out.
- ``combining.txt``: ``start end ccc`` lines, ``ccc`` decimal, the runs of one ``unicodedata.combining``; 0 left
  out.
- ``decomposition.txt``: ``cp kind cp…`` lines, ``unicodedata.decomposition`` one level deep, by code point. Kind
  ``c``: canonical, a primary composite (NFC composes its two code points back into it); ``x``: canonical,
  excluded from composition (a singleton, a non-starter decomposition, or CompositionExclusions.txt's: NFC of the
  code point is not itself); ``k``: compatibility (its ``<tag>`` dropped). Hangul syllables (U+AC00–D7A3) are left
  out: they decompose and compose by arithmetic (Unicode §3.12), as Python's own code does.
- ``case.txt``: ``cp lower upper casefold`` lines, each mapping ``str.lower``, ``str.upper`` or ``str.casefold``
  of the one code point (full mappings: ``İ`` lowers to two code points), its code points joined by ``+``, ``=``
  where it maps to itself; only code points one of the three maps elsewhere. ``Σ`` lowers to ``σ`` here: a string's
  ``lower()`` makes it ``ς`` in the Final_Sigma context, ``cased case-ignorable* Σ`` not followed by
  ``case-ignorable* cased`` (flags 9 and 10).
- ``ignorecase.txt``: one line a class of re.IGNORECASE, its members ascending, the smallest first (the
  representative, ``PyUnicode.ignoreCaseKey``); classes of one left out. Built as sre builds them: every code
  point grouped by ``_sre.unicode_tolower``, the groups ``re._casefix._EXTRA_CASES`` links joined. A pattern's
  literal ``c`` matches exactly its class under IGNORECASE (checked below), and a class's members are all in the
  BMP or all beyond it, so mapping each code point to its representative keeps a string's UTF-16 length.

Vectors, tests/conformance/vectors/unicode/:

- ``strings.jsonl``: ``code_points(name)`` records, the code points a predicate holds for (or a property's value
  at), as ``[start, end]`` (or ``[start, end, value]``) runs over every code point; ``mapped(cp)`` records, the
  string functions' answers (``MAPPED``'s order: lower, upper, casefold, nfc, nfd, nfkc, nfkd, the ignorecase
  representatives) for each code point a table maps elsewhere and Hangul's, sampled; then ``answers(s)`` records,
  every string function's answer by name, for curated and seeded random strings mixing scripts, combining marks,
  Hangul, Greek sigma and the planes beyond the BMP.
- ``py.jsonl``: ``round``, builtin ``sum`` of floats, ``str.split()``, ``str.strip()``, slices, ``len``,
  ``sorted``, ``Counter.most_common(1)``, ``bytes.lower`` (ASCII lowering) and ``%`` on ints. A float that isn't
  finite is written ``"inf"``, ``"-inf"`` or ``"nan"``.
- ``regex.jsonl``: ``re.findall``, ``re.split``, ``re.sub`` and ``re.fullmatch`` of ``\\w \\W \\s \\S \\d \\D \\b
  \\B`` over the random strings, Python's pattern syntax the phone translates (``core.py.PyRegex.compile``), sre's
  IGNORECASE over every class (``kw.flags``), and caracole's own patterns (normalize.py's, song_names.py's) over
  names like those they read. ``re.fullmatch`` answers the matched text or null; ``re.sub`` replaces with
  ``kw.repl``, a plain string.
"""

from __future__ import annotations

import _sre
import collections
import functools
import itertools
import math
import operator
import random
import re
import sys
import unicodedata
import warnings
from re._casefix import _EXTRA_CASES

import pytest

from helpers.corpus import DATA, VECTORS, check, jsonl

MADE_BY = "tests/test_conformance_unicode.py"
UNICODE = DATA / "unicode"
OUT = VECTORS / "unicode"
FN = "test_conformance_unicode"
MAX = 0x110000
HANGUL = range(0xAC00, 0xD7A4)
SEED = 20261103
FLAG_NAMES = ("alnum", "alpha", "decimal", "digit", "numeric", "space", "word", "printable", "latin", "cased",
              "case_ignorable")


def _is_surrogate(cp: int) -> bool:
    return 0xD800 <= cp <= 0xDFFF


def _ends_in_final_sigma(s: str) -> bool:
    return s.lower().endswith("ς")


@functools.cache
def _properties() -> tuple[list[int], list[str], list[int]]:
    """Every code point's flags, category and combining class, asked of Python a predicate at a time."""
    chars = list(map(chr, range(MAX)))
    categories = list(map(unicodedata.category, chars))
    combining = list(map(unicodedata.combining, chars))
    either = functools.partial(map, operator.or_)
    columns = [
        map(str.isalnum, chars), map(str.isalpha, chars), map(str.isdecimal, chars), map(str.isdigit, chars),
        map(str.isnumeric, chars), map(str.isspace, chars),
        either(map(str.isalnum, chars), map(operator.eq, chars, itertools.repeat("_"))),
        map(str.isprintable, chars),
        map(operator.contains, map(unicodedata.name, chars, itertools.repeat("")), itertools.repeat("LATIN")),
        either(either(map(str.islower, chars), map(str.isupper, chars)), map(str.istitle, chars)),
    ]
    flags = [0] * MAX
    for bit, column in enumerate(columns):
        for cp in itertools.compress(range(MAX), column):
            flags[cp] |= 1 << bit
    for cp in range(MAX):
        if categories[cp] in ("Cn", "Cs"):
            continue  # an unassigned code point is never case-ignorable (test_unassigned_code_points_…)
        # Case-ignorable, as lower() reads it: Σ after it and a cased letter before it is final only when lower()
        # looks past it, and after a space never.
        c = chars[cp]
        after_letter, after_space = _ends_in_final_sigma("A" + c + "Σ"), _ends_in_final_sigma(" " + c + "Σ")
        if after_letter != after_space:
            assert after_letter and not after_space
            flags[cp] |= 1 << 10
    return flags, categories, combining


def _runs(values, skip) -> list[tuple[int, int, object]]:
    """The maximal runs of equal values over every code point, as (start, end, value), those equal to ``skip``
    left out."""
    changes = [0, *itertools.compress(range(1, MAX), map(operator.ne, values[1:], values[:-1])), MAX]
    return [(a, b - 1, values[a]) for a, b in itertools.pairwise(changes) if values[a] != skip]


@functools.cache
def _flag_runs() -> list[tuple[int, int, object]]:
    return _runs(_properties()[0], 0)


@functools.cache
def _category_runs() -> list[tuple[int, int, object]]:
    return _runs(_properties()[1], "Cn")


@functools.cache
def _combining_runs() -> list[tuple[int, int, object]]:
    return _runs(_properties()[2], 0)


def _seq(cps) -> str:
    return "+".join(f"{c:04X}" for c in cps)


def _cps(s: str) -> list[int]:
    return [ord(c) for c in s]


def _header(name: str, what: str) -> str:
    return (f"# caracole/unicode/{name}: {what}; unicodedata {unicodedata.unidata_version}, Python "
            f"{sys.version.split()[0]}, made by {MADE_BY}\n")


# --- the tables ----------------------------------------------------------------------------------------------


def flags_txt() -> str:
    lines = [f"{s:04X} {e:04X} {v:X}\n" for s, e, v in _flag_runs()]
    return _header("flags.txt", "start end mask, bits " + " ".join(FLAG_NAMES)) + "".join(lines)


def category_txt() -> str:
    lines = [f"{s:04X} {e:04X} {v}\n" for s, e, v in _category_runs()]
    return _header("category.txt", "start end category, Cn left out") + "".join(lines)


def combining_txt() -> str:
    lines = [f"{s:04X} {e:04X} {v}\n" for s, e, v in _combining_runs()]
    return _header("combining.txt", "start end ccc (decimal), 0 left out") + "".join(lines)


@functools.cache
def _decompositions() -> list[tuple[int, str, list[int]]]:
    out = []
    decompositions = list(map(unicodedata.decomposition, map(chr, range(MAX))))
    for cp in itertools.compress(range(MAX), decompositions):
        if cp in HANGUL or _is_surrogate(cp):
            continue
        parts = decompositions[cp].split()
        if parts[0].startswith("<"):
            out.append((cp, "k", [int(p, 16) for p in parts[1:]]))
            continue
        seq = [int(p, 16) for p in parts]
        composes = unicodedata.normalize("NFC", chr(cp)) == chr(cp)
        if composes:
            assert len(seq) == 2 and unicodedata.combining(chr(seq[0])) == 0, hex(cp)
        out.append((cp, "c" if composes else "x", seq))
    return out


def decomposition_txt() -> str:
    lines = [f"{cp:04X} {kind} {' '.join(f'{c:04X}' for c in seq)}\n" for cp, kind, seq in _decompositions()]
    return _header("decomposition.txt", "cp kind(c composes, x excluded, k compatibility) cp...") + "".join(lines)


@functools.cache
def _case_mappings() -> list[tuple[int, str, str, str]]:
    out = []
    for c in map(chr, itertools.chain(range(0xD800), range(0xE000, MAX))):
        lower, upper, fold = c.lower(), c.upper(), c.casefold()
        if lower != c or upper != c or fold != c:
            out.append((ord(c), lower, upper, fold))
    return out


def case_txt() -> str:
    def col(c: str, mapped: str) -> str:
        return "=" if mapped == c else _seq(_cps(mapped))

    lines = [f"{cp:04X} {col(chr(cp), lo)} {col(chr(cp), up)} {col(chr(cp), fo)}\n"
             for cp, lo, up, fo in _case_mappings()]
    return _header("case.txt", "cp lower upper casefold, '+' joins, '=' itself") + "".join(lines)


@functools.cache
def _tolower() -> list[int]:
    return list(map(_sre.unicode_tolower, range(MAX)))


@functools.cache
def _tolower_groups() -> dict[int, list[int]]:
    """The code points ``_sre.unicode_tolower`` maps to each code point, ascending, where that is more than the code
    point alone (``_group`` gives any code point's)."""
    lowers = _tolower()
    groups: dict[int, list[int]] = {}
    for cp in itertools.compress(range(MAX), map(operator.ne, lowers, range(MAX))):
        groups.setdefault(lowers[cp], []).append(cp)
    for lower, members in groups.items():
        if lowers[lower] == lower:
            members.append(lower)
        members.sort()
    return groups


def _group(lower: int) -> list[int]:
    """The code points sre lowers to ``lower``."""
    return _tolower_groups().get(lower) or ([lower] if _tolower()[lower] == lower else [])


@functools.cache
def _ignorecase_classes() -> list[list[int]]:
    """sre's IGNORECASE classes of more than one code point, ascending by their smallest member: the groups of one
    lower case, joined where ``_EXTRA_CASES`` links them."""
    parent: dict[int, int] = {}

    def root(x: int) -> int:
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    for lower, others in sorted(_EXTRA_CASES.items()):
        for other in others:
            a, b = root(lower), root(other)
            if a != b:
                parent[max(a, b)] = min(a, b)
    lowers = set(_tolower_groups()) | set(_EXTRA_CASES) | {o for others in _EXTRA_CASES.values() for o in others}
    classes: dict[int, list[int]] = {}
    for lower in sorted(lowers):
        classes.setdefault(root(lower), []).extend(_group(lower))
    return sorted((sorted(m) for m in classes.values() if len(m) > 1), key=lambda m: m[0])


@functools.cache
def _representatives() -> dict[int, int]:
    return {cp: members[0] for members in _ignorecase_classes() for cp in members}


def ignorecase_txt() -> str:
    lines = [" ".join(f"{c:04X}" for c in members) + "\n" for members in _ignorecase_classes()]
    return _header("ignorecase.txt", "a class a line, its representative first") + "".join(lines)


TABLES = {"flags.txt": flags_txt, "category.txt": category_txt, "combining.txt": combining_txt,
          "decomposition.txt": decomposition_txt, "case.txt": case_txt, "ignorecase.txt": ignorecase_txt}


@pytest.mark.parametrize("name", sorted(TABLES))
def test_the_unicode_tables_are_pythons(name):
    check(UNICODE / name, TABLES[name]())


def test_unassigned_code_points_hold_no_property_and_combine_with_nothing():
    """_properties probes no Cn code point for case-ignorable: none is, and none has a flag, a combining class or a
    mapping."""
    flags = _properties()[0]
    rng = random.Random(SEED)
    unassigned = [cp for cp in range(MAX) if unicodedata.category(chr(cp)) == "Cn"]
    for cp in unassigned[:: max(1, len(unassigned) // 4000)] + rng.sample(unassigned, 2000):
        c = chr(cp)
        assert flags[cp] == 0, hex(cp)
        assert not _ends_in_final_sigma("A" + c + "Σ") and not _ends_in_final_sigma(" " + c + "Σ"), hex(cp)
        assert unicodedata.combining(c) == 0 and unicodedata.decomposition(c) == "", hex(cp)
        assert (c.lower(), c.upper(), c.casefold()) == (c, c, c), hex(cp)


def test_ignorecase_classes_are_exactly_what_sre_matches_and_keep_utf16_lengths():
    """A literal ``c`` under IGNORECASE matches ``lower(x)`` in ``{lower(c)} ∪ _EXTRA_CASES[lower(c)]`` (or ``c``
    alone when it is uncased): that set must be ``c``'s class, or mapping a subject to representatives would match
    what sre doesn't. And re's \\w \\s \\d must read a code point as they read its lower case, as sre reads them in an
    IGNORECASE character set."""
    rep = _representatives()
    members = {m[0]: m for m in _ignorecase_classes()}
    wrong = []
    cased = itertools.compress(range(MAX), map(_sre.unicode_iscased, range(MAX)))
    for cp in sorted(set(cased) | set(rep)):
        if _is_surrogate(cp):
            continue
        if not _sre.unicode_iscased(cp):
            matched = [cp]
        else:
            lower = _sre.unicode_tolower(cp)
            matched = sorted(x for k in (lower, *_EXTRA_CASES.get(lower, ())) for x in _group(k))
        if matched != members.get(rep.get(cp, cp), [cp]):
            wrong.append(f"U+{cp:04X} matches {_seq(matched)}, its class is {_seq(members.get(rep.get(cp, cp), [cp]))}")
    assert not wrong, "sre's IGNORECASE is not a partition: " + "; ".join(wrong[:20])
    assert all(len({c > 0xFFFF for c in m}) == 1 for m in _ignorecase_classes())
    flags, lowers = _properties()[0], _tolower()
    lowered = list(itertools.compress(range(MAX), map(operator.ne, lowers, range(MAX))))
    for bit in (5, 6, 2):  # \s, \w, \d (isdecimal)
        varies = [cp for cp in lowered if flags[cp] >> bit & 1 != flags[lowers[cp]] >> bit & 1]
        assert not varies, f"{FLAG_NAMES[bit]} differs from its lower case at {_seq(varies[:20])}"


# --- strings.jsonl -------------------------------------------------------------------------------------------


@functools.cache
def _all_text() -> str:
    """Every code point but the surrogates, in order."""
    return "".join(map(chr, itertools.chain(range(0xD800), range(0xE000, MAX))))


@functools.cache
def _re_runs(letter: str) -> list[list[int]]:
    """The runs of code points re's ``\\<letter>`` matches, read by re itself."""
    held = [False] * MAX
    for c in re.sub("\\" + letter.upper(), "", _all_text()):
        held[ord(c)] = True
    return [[s, e] for s, e, _ in _runs(held, False)]


def code_points(name: str) -> list[list]:
    """The code points ``name`` holds for, as [start, end] runs, or a property's [start, end, value] runs; re's
    classes read by re itself over every code point."""
    if name in ("re.\\w", "re.\\s", "re.\\d"):
        return _re_runs(name[-1])
    if name == "unicodedata.category":
        return [[s, e, v] for s, e, v in _category_runs()]
    if name == "unicodedata.combining":
        return [[s, e, v] for s, e, v in _combining_runs()]
    bit = {"str.isalnum": 0, "str.isalpha": 1, "str.isdecimal": 2, "str.isdigit": 3, "str.isnumeric": 4,
           "str.isspace": 5, "str.isprintable": 7, "latin_by_name": 8, "cased": 9, "case_ignorable": 10}[name]
    out: list[list[int]] = []
    for s, e, mask in _flag_runs():
        if mask >> bit & 1:
            if out and out[-1][1] == s - 1:
                out[-1][1] = e
            else:
                out.append([s, e])
    return out


CODE_POINT_SETS = ("str.isalnum", "str.isalpha", "str.isdecimal", "str.isdigit", "str.isnumeric", "str.isspace",
                   "str.isprintable", "re.\\w", "re.\\s", "re.\\d", "latin_by_name", "cased", "case_ignorable",
                   "unicodedata.category", "unicodedata.combining")


MAPPED = ("lower", "upper", "casefold", "nfc", "nfd", "nfkc", "nfkd", "ignorecase")


def mapped(cp: int) -> list[str]:
    """One code point's answers, in the order of ``MAPPED``."""
    found = answers(chr(cp))
    return [found[name] for name in MAPPED]


def answers(s: str) -> dict[str, object]:
    """Every string function the phone ports, on ``s``."""
    rep = _representatives()
    return {
        "lower": s.lower(), "upper": s.upper(), "casefold": s.casefold(),
        "nfc": unicodedata.normalize("NFC", s), "nfd": unicodedata.normalize("NFD", s),
        "nfkc": unicodedata.normalize("NFKC", s), "nfkd": unicodedata.normalize("NFKD", s),
        "isalnum": s.isalnum(), "isalpha": s.isalpha(), "isdigit": s.isdigit(), "isspace": s.isspace(),
        "ignorecase": "".join(chr(rep.get(ord(c), ord(c))) for c in s),
        "len": len(s),
    }


# Code points worth meeting: scripts, marks of many classes, the case and normalization oddities.
LATIN = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
POOLS = {
    "ascii": LATIN + " _-.,:;'!?()[]{}/\\\"&#@*+=~`^$%|<>",
    "latin": "àáâãäåæçèéêëìíîïñòóôõöøùúûüýÿßÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝŸĀāĂăĄąĆćČčĎďĐđĒēĘęĚěĞğĠġĦħĨĩĪīĮįİıĲĳĶķĹĺĽľŁłŃńŇňŉŊŋŌōŐőŒœŔŕŘřŚśŞşŠšŢţŤťŨũŪūŮůŰűŲųŴŵŶŷŹźŻżŽžſƀƁƂǄǅǆǇǈǉǊǋǌǰǱǲǳȘșȚțẞẠạẶặỆệỲỳ",
    "marks": "\u0300\u0301\u0302\u0303\u0304\u0306\u0307\u0308\u030a\u030b\u030c\u0323\u0327\u0328\u0331\u0345"
             "\u0591\u05b0\u05bc\u0610\u064b\u0651\u093c\u094d\u0e48\u0e38\u1dc0\u20d0\u302a\u302b\u3099\u309a"
             "\U0001d165\U0001d16d\U0001e944",
    "greek": "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρσςτυφχψωάέήίόύώΆΈΉΊΌΎΏΐΰϊϋϐϑϕϖϰϱϲϴϵϹἀἈᾳᾼῳῼΐ",
    "cyrillic": "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюяІіЇїЄєҐґᲀᲁᲂᲃᲄᲅᲆᲇᲈ",
    "cjk": "中文歌曲宋冬野安和桥南山南斑马你好世界的了在是我有他这个们来到時說們發髮國語臺灣丨乙㐀䶵豈﨑\u3000、。「」『』【】（）",
    "kana": "あいうえおかきくけこがぎアイウエオカキクケコガギヴヷーｱｲｳｶﾞﾊﾟ",
    "hangul": "가각간갇갈감갑값강개객갤갬힣한국어노래\u1100\u1101\u1112\u1161\u1162\u1175\u11a8\u11a9\u11c2\u3131\u314f",
    "indic": "ह\u093f\u0902द\u0940ग\u093eन\u093eक\u093cख\u093cग\u093cज\u093cड\u093cढ\u093cफ\u093cय\u093c०१२३४५६७८९অআইঈ০১২ত\u09beম\u09bfழ\u0bcdਪ\u0a70ਜ\u0a3eਬ\u0a40",
    "arabic": "مرحباالعربيةأإآؤئءةى٠١٢٣٤٥٦٧٨٩۰۱۲ﻻﷲ\u200f",
    "spaces": "\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2007\u200a\u2028\u2029\u202f"
              "\u205f\u3000\u200b\u180e\ufeff\u00ad",
    "digits": "0123456789０１２３４５６７８９²³¹¼½¾⁰⁴₀₁①②⑳ⅠⅡⅫⅷ〇一二三\U0001d7ce\U0001d7d8\U000104a0\U0001e950\U0001fbf0",
    "compat": "ﬁﬂﬀﬃﬄﬅﬆ™℠№℃℉Å Ω K㎏㍿ｶﾞ＃ＡＢａｂ㈱⁵ᵃᵇˢʰǲĲŀ\u2126\u212a\u212b\ufb2a\uff21\u2460\u3392",
    "special": "İıßẞſKÅŉǰΐΰẖẗẘẙẚﬓﬔﬕﬖﬗ\u0345\u0390\u03b0\u1e9e\u1fd3\u1fe3\u1f80\u1f88\u1fb3\u1fbc\u1fbe"
               "ᏸᏹᏺꭰꭱꮿᲐᲑᲒაბგ",
    "astral": "\U00010400\U00010428\U0001044f\U000104b0\U000104d8\U00010c80\U00010cc0\U0001e900\U0001e922"
              "\U0001d400\U0001d41a\U0001d4d0\U0001f600\U0001f468\U0001f3fb\U00020000\U0002a6d6\U0002f800"
              "\U000e0041\U000e0100\U000f0000\U0010fffd\U00016e40\U00016e60",
    "other": "\x00\x07\x7f\x80\x9f\ue000\uf8ff\ufffd\ufffe\uffff\u0378\u2fff\u061c\u200d\u200c\u2060\ufe0f",
}


def _random_strings(n: int) -> list[str]:
    rng = random.Random(SEED)
    pools = list(POOLS.values())
    out = []
    for _ in range(n):
        length = rng.choice((1, 2, 3, 4, 5, 6, 8, 10, 12, 16))
        favourite = rng.choice(pools)
        chars = [rng.choice(favourite if rng.random() < 0.6 else rng.choice(pools)) for _ in range(length)]
        out.append("".join(chars))
    return out


CURATED = [
    "", "ΤΡΥΠΕΣ", "ΤΡΥΠΕΣ ΣΑΣ", "Σ", "ΑΣ", "Α.Σ", "ΑΣ.", "ΑΣΑ", "Α'Σ'", "ΑΣ'Α", "ὈΔΥΣΣΕΎΣ", "ΑΣ\u0345", "1Σ", "aΣb",
    "ΣΑΣ σ ς", "\U00010400Σ", "Ꮳ\u00adΣ", "straße", "STRASSE", "ß", "ẞ", "ﬁ", "İstanbul", "ısırık", "ǅungla", "Ǆ",
    "ह\u093f\u0902द\u0940", "２０１１", "Ⅻ", "Song Dongye (宋冬野)", "安和桥", "Café Tacvba", "Cafe\u0301", "e\u0301\u0323",
    "e\u0323\u0301", "a\u0308\u0301", "\u0301a", "\u0345\u0301", "\u1100\u1161\u11a8", "\u1100\u1161", "가\u11a8",
    "\u1100\u0301\u1161", "\u0915\u093c", "\u0958", "Å", "\u212b", "\u2126", "\u212a", "ǰ\u0323", "ΐ", "\u1f80",
    "ﬃ", "ŉ", "ẖ", "ﾊﾟ", "ｶﾞ", "\u0f73", "\u0f75", "\u0f81", "\u1e9b\u0323", "\U0001d15e", "\U0001d160",
    "\u00c5\u0328", "a\u0328\u0301\u0303", "\u05d0\u05b7\u05bc", "\u0e40\u0e48\u0e32", "\U000110ab",
    "\U0001133b\U0001133e", "\u0b47\u0b3e", "\u09c7\u09be", "\u0d46\u0d3e", "\u1025\u102e", "\u3099\u304b",
    "か\u3099", "\x1c\x1d\x1e\x1f", "\x85", "\u2028\u2029", " \t\n", "a_b", "___", "١٢٣", "\U0001d7ce\U0001d7cf",
]


def _hangul_sample() -> list[int]:
    return list(HANGUL[::37]) + [HANGUL[0], HANGUL[1], HANGUL[27], HANGUL[28], HANGUL[-1]]


def strings_records() -> list[dict]:
    records = [{"fn": f"{FN}.code_points", "args": [name], "out": code_points(name)} for name in CODE_POINT_SETS]
    code = sorted({cp for cp, *_ in _decompositions()} | {cp for cp, *_ in _case_mappings()}
                  | set(_representatives()) | set(_hangul_sample()))
    records += [{"fn": f"{FN}.mapped", "args": [cp], "out": mapped(cp)} for cp in code]
    records += [{"fn": f"{FN}.answers", "args": [s], "out": answers(s)} for s in CURATED]
    records += [{"fn": f"{FN}.answers", "args": [s], "out": answers(s), "seed": SEED}
                for s in _random_strings(3000)]
    return records


@pytest.mark.slow  # about 2.5 s in a process of its own: every code point's properties, then 11,000 records
def test_strings_jsonl():
    check(OUT / "strings.jsonl", jsonl(strings_records(), corpus="unicode/strings", made_by=MADE_BY))


# --- py.jsonl ------------------------------------------------------------------------------------------------


def _f(x: float) -> float | str:
    """A float as JSON holds it: a non-finite one by name."""
    if math.isnan(x):
        return "nan"
    if x in (float("inf"), float("-inf")):
        return "inf" if x > 0 else "-inf"
    return x


ROUND = [0.25, 0.35, 0.45, 0.5, 1.5, 2.5, 2.675, 94.75, 94.745, 1e16, 1e16 + 2, 1.005, 0.125, 0.375, 1.255,
         -0.25, -0.04, -0.0, 0.0, 0.05, 0.15, 0.95, 99.95, 99.995, 0.1, 0.7, 1 / 3, 2 / 3, 1e-7, 5e-324,
         123456789.125, 4.35, 5.55, 8.345, 66.66666666666667, 87.5, 12.345, 0.045, 1.45, 2.345, 1e300,
         1.7976931348623157e308, 2 ** 52 + 0.5, 2.0 ** 53, 0.30000000000000004, 0.1 + 0.2, 4503599627370495.5,
         float("inf"), float("-inf"), float("nan"), 3.14159, 100.0, 85.71428571428571, 33.33333333333333]


def py_records() -> list[dict]:
    rng = random.Random(SEED)
    records: list[dict] = []
    floats = ROUND + [rng.uniform(-1000, 1000) for _ in range(150)] + [round(rng.uniform(0, 100), 3) + 0.0005
                                                                       for _ in range(150)]
    for x in floats:
        for digits in (0, 1, 2, 3):
            records.append({"fn": "round", "args": [_f(x), digits], "out": _f(round(x, digits))})
    sums = [[0.1] * 10, [1e100, 1.0, -1e100, 1.0], [], [0.0], [-0.0], [-0.0, -0.0], [1e308, 1e308],
            [float("inf"), 1.0], [float("inf"), float("-inf")], [1.0, float("nan")], [0.1, 0.2, 0.3],
            [1e16, 1.0, -1e16], [3.0, 1e-16, -3.0], [-1.0, 1e-17], [2.5] * 7, [0.1] * 3 + [-0.3]]
    sums += [[rng.uniform(-100, 100) for _ in range(rng.randrange(1, 30))] for _ in range(60)]
    sums += [[rng.choice((0.1, 0.2, 1 / 3, 1e-9, 1e9, 87.5, 66.7)) for _ in range(rng.randrange(1, 40))]
             for _ in range(40)]
    for xs in sums:
        records.append({"fn": "sum", "args": [[_f(x) for x in xs]], "out": _f(sum(xs))})
    spaced = ["", " ", "   ", "a", " a ", "a b", "  a  b  ", "\x1ca\x1db\x1ec\x1fd", "a\x85b", "\xa0a\xa0",
              "a\u2000b\u3000c", "\u200ba\u200b", "\u180ea", "\ufeffa", "a\u2028b\u2029c", "\t\n\x0b\x0c\ra\r\n",
              "宋冬野\u3000安和桥", "a\u202fb\u205fc", "\u1680x\u1680"]
    spaced += [s for s in _random_strings(3000)[:400]]
    for s in spaced:
        records.append({"fn": "str.split", "args": [s], "out": s.split()})
        records.append({"fn": "str.strip", "args": [s], "out": s.strip()})
        records.append({"fn": "len", "args": [s], "out": len(s)})
    sliced = ["", "abc", "a\U0001f600b", "\U00010400\U00010428\U0001044f", "宋冬野安和桥", "e\u0301x\U00020000y"]
    bounds = [None, -7, -3, -2, -1, 0, 1, 2, 3, 7]
    for s in sliced:
        for start in bounds:
            for stop in bounds:
                records.append({"fn": "slice", "args": [s, start, stop], "out": s[start:stop]})
    words = ["", "a", "b", "ab", "A", "Z", "z", "\ue000", "\uffff", "\ufffd", "\U00010000", "\U0001f600",
             "\U0010fffd", "é", "e\u0301", "\uff21", "ß", "\u00ff", "\u0100", "宋", "安", "aa", "a\ue000",
             "a\U00010000"]
    for _ in range(80):
        records.append({"fn": "sorted", "args": [xs := rng.sample(words, rng.randrange(2, 12))], "out": sorted(xs)})
    counted = [[], ["a"], ["b", "a", "a", "b"], ["a", "b"], ["x", "y", "y", "x", "z", "z"], ["b", "a", "b", "a", "a"]]
    counted += [[rng.choice("abcd") for _ in range(rng.randrange(1, 9))] for _ in range(40)]
    for xs in counted:
        common = collections.Counter(xs).most_common(1)
        records.append({"fn": "collections.Counter.most_common", "args": [xs, 1],
                        "out": common[0][0] if common else None})
    for s in ["Content-TYPE", "X-Caracole-Token", "ÀÉÎ", "İK\u212a", "ABCxyz0129", "ẞ", "Σ", "", "@[`{"]:
        records.append({"fn": "bytes.lower", "args": [s], "out": s.encode("utf-8").lower().decode("utf-8")})
    for a in (-7, -1, 0, 1, 7, 13, -13):
        for b in (-5, -3, 1, 3, 5, 12):
            records.append({"fn": "operator.mod", "args": [a, b], "out": operator.mod(a, b)})
    return records


def test_py_jsonl():
    check(OUT / "py.jsonl", jsonl(py_records(), corpus="unicode/py", made_by=MADE_BY))


# --- regex.jsonl ---------------------------------------------------------------------------------------------


def _call(fn: str, pattern: str, s: str, *, ignorecase: bool = False, repl: str | None = None) -> dict:
    flags = re.IGNORECASE if ignorecase else 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)  # "[[" and "&&" in SYNTAX, as Python reads them today
        return _answer(fn, pattern, s, flags, repl)


def _answer(fn: str, pattern: str, s: str, flags: int, repl: str | None) -> dict:
    if fn == "re.findall":
        out = re.findall(pattern, s, flags)
    elif fn == "re.split":
        out = re.split(pattern, s, flags=flags)
    elif fn == "re.fullmatch":
        m = re.fullmatch(pattern, s, flags)
        out = m.group(0) if m else None
    elif fn == "re.sub":
        out = re.sub(pattern, lambda _: repl, s, flags=flags)
    else:
        raise ValueError(fn)
    record: dict = {"fn": fn, "args": [pattern, s], "out": out}
    kw = {}
    if flags:
        kw["flags"] = "IGNORECASE"
    if repl is not None:
        kw["repl"] = repl
    if kw:
        record["kw"] = kw
    return record


# Python's pattern syntax, as PyRegex.compile translates it: each (fn, pattern, subjects).
SYNTAX = [
    ("re.findall", r".", ["a\nb\x85c\u2028d\re"]),
    ("re.findall", r"(?s).", ["a\nb"]),
    ("re.findall", r"^\w+$", ["abc\n", "abc\x85", "abc\u2028", "abc\r", "abc\n\n"]),
    ("re.findall", r"(?m)^\w+$", ["ab\ncd\x85ef\u2028gh\rij"]),
    ("re.findall", r"\w+\Z", ["abc\n", "abc"]),
    ("re.findall", r"\w+\z", ["abc\n", "abc"]),
    ("re.findall", r"\Aab", ["abab"]),
    ("re.findall", r"a{2}|b{,2}|c{1,}|d{}|e{,}|{x}|f{", ["aaabbbbcccd{}e{,}{x}f{ee"]),
    ("re.findall", r"[]a]+", ["]a]b"]),
    ("re.findall", r"[^]a]+", ["]a]b"]),
    ("re.findall", r"[\b]", ["a\bb"]),
    ("re.findall", r"[a\-z]+|[-a]|[a-]", ["a-z-b"]),
    ("re.findall", r"\v|\a|\f|\t", ["\x0b\x07\x0c\t\n\x85"]),
    ("re.findall", r"\x41é\U0001f600\0\07\101\x7f", ["A\xe9\U0001f600\x00\x07A\x7f"]),
    ("re.findall", r"[\x41-\x43à-å\U0001f600-\U0001f64f]+", ["ABCDàåæ\U0001f600\U0001f650"]),
    ("re.findall", r"(?P<l>\w)(?P=l)", ["aabccd\U00010400\U00010400"]),
    ("re.findall", r"(\w)\1", ["aabccd"]),
    ("re.findall", r"[^\W\d_]+", ["ab12_cd\u0663éŸ\U00010400\U0001d7ce"]),
    ("re.findall", r"[\w-]+", ["a-b c_d-"]),
    ("re.findall", r"[[]+|[a&&b]+|[--/]+|[a||b]+|[a~~b]+", ["[[&&--||~~ab./"]),
    ("re.findall", r"[\s\S]", ["a \U00010400"]),
    ("re.findall", r"[^\s\S]", ["a \U00010400"]),
    ("re.findall", r"\W", ["\U00010400a\U0001f600 "]),
    ("re.findall", r"\S+", ["a\x1cb\x85c\xa0d\u200be\u180ef"]),
    ("re.findall", r"\D+", ["a1b２c\u0663d\U0001d7cee"]),
    ("re.findall", r"(?#a comment)a(?:b|c)(?=d)(?!e)(?<=c)", ["acd ace abd"]),
    ("re.findall", r"(?<=\w)\.(?=\w)|(?<!\w)\.", [".a.b \U00010400.\U00010400 .."]),
    ("re.findall", r"a*?b|a+?c|a??d|(?>a+)e|a*+f|a++g|a?+h", ["aab aac ad aae aaf aag ah"]),
    ("re.findall", r"[.^$*+?(){}|]+", ["a.^$*+?(){}|b"]),
    ("re.findall", r"\.\^\$\*\+\?\(\)\{\}\|\[\]\\\/\-\#\ \é", [".^$*+?(){}|[]\\/-# é"]),
    ("re.findall", "a b#c", ["a b#c"]),
    ("re.findall", r"(?i:Ab)c|(?-i:x)", ["abc ABC abC aBc X x"]),
    ("re.findall", r"(?u)\w+", ["ab é"]),
    ("re.split", r"\b", ["", "a", " ", "a b", "ab cd", "\U00010400 \U00010400\U00010400 ", "ह\u093f\u0902द\u0940", "a\u0301b"]),
    ("re.split", r"\B", ["", "a", " ", "ab  cd", "\U00010400\U00010400 ", "ह\u093f\u0902द\u0940"]),
    ("re.split", r"(\s)", ["a b\x85c"]),
    ("re.split", r"(a)|b", ["xaybz"]),
    ("re.split", r"x*", ["axbc\U0001f600d"]),
    ("re.split", r"\W*", ["...words..."]),
    ("re.sub", r"[\W_]+", ["ह\u093f\u0902द\u0940", "Song Dongye (宋冬野)", "_a__b_", "ǅungla Žák"]),
    ("re.sub", r"\s+", ["a \t b\x85\x1cc\u3000d"]),
    ("re.sub", r"x*", ["abc", "\U0001f600x\U0001f600"]),
    ("re.sub", r"$", ["ab\n", "ab"]),
    ("re.fullmatch", r"\w+", ["hello", "hello\n", "宋冬野", "ह\u093f\u0902द\u0940", "a\u0301", "\U0001d7ce", "Ⅻ", "²"]),
    ("re.fullmatch", r"\d+", ["２０１１", "²", "١٢٣", "\U0001d7ce\U000104a0", "Ⅻ"]),
    ("re.fullmatch", r"\s+", ["\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000\u2028\u2029\u202f\u205f\u3000",
                              "\u200b", "\u180e", "\ufeff"]),
    ("re.fullmatch", r".*", ["a\nb", "a\x85b"]),
    ("re.fullmatch", r"a|ab", ["ab"]),
]
# What Python itself refuses: the phone refuses it too.
SYNTAX_ERRORS = [r"\e", r"\q", r"[\8]", r"(?L)a", r"a**", r"(", r"[a", r"[z-a]", r"*a", r"a{3,2}", r"(?P<1>a)",
                 r"\1", r"(a)\2", r"(?<=a*)b", r"[\w-z]", r"a)", r"(?P=x)", r"\x4", r"\u12", r"\400"]

# sre's IGNORECASE beyond single letters: classes, ranges, negation, caracole's own patterns' shapes.
IGNORECASE = [
    (r"[a-z]+", None), (r"[^a-z]+", None), (r"[α-ω]+", None), (r"[ä-ü]+", None), (r"[\w]+", None),
    (r"[\W\d]+", None), (r"[^\WI]+", None), (r"[ſß]", None), (r"[\U00010400-\U0001040f]+", None),
    (r"[^\U00010428]", None), (r"\bk\w*", None), (r"ΣΑΣ|σας", None), (r"straße|STRASSE", None),
    (r"İ|ı|i", None), ("\u0345|ι", None),
]


def _caracole_patterns() -> list[re.Pattern]:
    from caracole import normalize, song_names

    names = ["_APOSTROPHES", "_SPLIT", "_CJK", "_HAN", "_DASH_SUFFIX", "_PAREN_FEAT", "_PAREN_SUFFIX",
             "_ACOUSTIC_WORD", "_LIVE_WORD", "_PART_BREAK", "_FEATURING", "_BRACKETED", "_MORA"]
    out = [getattr(normalize, n) for n in names]
    out += [getattr(song_names, n) for n in ("_MARK", "_BY", "_YEAR", "_BRACKETS", "_TOPIC", "_LABEL")]
    return out


NAMES = [
    "Hotel California - 2013 Remaster", "Creep (Acoustic)", "Wonderwall - Live at Knebworth", "Hurt (feat. X)",
    "Ma Di (feat. 宋冬野)", "南山南（feat. 宋冬野）", "Song Dongye (宋冬野)", "【斑马斑马】Zebra Zebra", "Rock'n’Roll",
    "Clandestino - En Vivo", "Lamento Boliviano - Versión Acústica", "LIVE AND LET DIE", "Yesterday - Remastered 2009",
    "Sunday Bloody Sunday - Live From Red Rocks", "Africa by Toto", "Toto - Topic", "Toto VEVO", "Toto Official Channel",
    "Imagine (1971)", "Smells Like Teen Spirit (Remastered 2021)", "Hallelujah - From \"Shrek\" Soundtrack",
    "Ojitos Lindos - ACÚSTICO", "Hello / Adele", "Café Tacvba | Eres", "Desert Rose ~ Sting", "Kanpai // Kotaro",
    "Sakura sakura", "Tsunami", "Konnichiwa", "Shinkansen", "Kitte", "Matcha", "Ninja", "Itto", "ΚΑΛΗΜΕΡΑ ΣΑΣ",
    "Straße — Live", "İstanbul (Live)", "ΚΕΛΒΙΝ k\u212a", "x\u0301 (acústica)", "Dancing Queen – Single Version",
]


def regex_records() -> list[dict]:
    records = []
    strings = CURATED + _random_strings(3000)[:1000]
    for i, s in enumerate(strings):
        records.append(_call("re.findall", r"\w+", s))
        records.append(_call("re.split", r"[\W_]+", s))
        records.append(_call("re.findall", r"\d+", s))
        records.append(_call("re.split", r"\s+", s))
        records.append(_call("re.split", r"\b", s))
        if i % 3 == 0:
            records.append(_call("re.split", r"\B", s))
            records.append(_call("re.findall", r"\W\S|\D\s", s))
            records.append(_call("re.fullmatch", r"[\w\s]*", s))
    for fn, pattern, subjects in SYNTAX:
        for s in subjects:
            records.append(_call(fn, pattern, s, repl="-" if fn == "re.sub" else None))
    for pattern in SYNTAX_ERRORS:
        try:
            re.compile(pattern)
            raise AssertionError(f"{pattern!r} compiles")
        except re.error:
            pass
        records.append({"fn": "re.compile", "args": [pattern], "err": "re.error"})
    rng = random.Random(SEED)
    for members in _ignorecase_classes():
        subject = [chr(c) for c in members] + [chr(c ^ 1) for c in members] + list("aZ ")
        rng.shuffle(subject)
        letter = chr(rng.choice(members))
        records.append(_call("re.findall", re.escape(letter), "".join(subject), ignorecase=True))
    letters = [c for c in POOLS["latin"] + POOLS["greek"] + POOLS["cyrillic"] + POOLS["special"] + POOLS["astral"]
               + POOLS["compat"]]
    for pattern, _ in IGNORECASE:
        for _ in range(40):
            s = "".join(rng.choice(letters) for _ in range(rng.randrange(1, 12)))
            records.append(_call("re.findall", pattern, s, ignorecase=True))
    for compiled in _caracole_patterns():
        ignorecase = bool(compiled.flags & re.IGNORECASE)
        for s in NAMES:
            records.append(_call("re.findall", compiled.pattern, s, ignorecase=ignorecase))
            records.append(_call("re.sub", compiled.pattern, s, ignorecase=ignorecase, repl="|"))
    return records


def test_regex_jsonl():
    check(OUT / "regex.jsonl", jsonl(regex_records(), corpus="unicode/regex", made_by=MADE_BY))
